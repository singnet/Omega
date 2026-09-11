import os
import re
import glob
import hashlib
import chromadb
import openai
from   lib_llm_ext import initLocalEmbedding, useLocalEmbedding
from src.logger import get_logger
from config import config_get_by_key

logger = get_logger(__name__)

# --- Constants -----------------------------------------------------------

EMBEDDING_MODEL = "text-embedding-3-large"
COLLECTION_NAME = "memories"
TOP_K = 5
MIN_CHUNK_CHARS = 100
MAX_CHUNK_CHARS = 6000

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.environ.get(
    "CHROMA_DB_PATH",
    "/PeTTa/chroma_db" if os.path.isdir("/PeTTa/chroma_db") else
    os.path.join(_PROJECT_ROOT, "..", "..","chroma_db")
)

# --- Lazy ChromaDB client ------------------------------------------------

_client = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is None:
        os.makedirs(DB_PATH, exist_ok=True)
        _client = chromadb.PersistentClient(path=DB_PATH)
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=None,
        )
    return _collection


# --- Helpers -------------------------------------------------------------

HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)


def _resolve_knowledge_dir():
    return os.path.join(_PROJECT_ROOT, "knowledge-priors")


def _file_hash(filepath):
    return hashlib.md5(open(filepath, "rb").read()).hexdigest()


def _decode_metta(s):
    return (s.replace("_quote_", '"')
             .replace("_newline_", "\n")
             .replace("_apostrophe_", "'"))


# --- Chunking ------------------------------------------------------------

def _chunk_markdown(text, filename):
    """Heading-aware markdown chunking with breadcrumb tracking."""
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return [{"text": text.strip(), "breadcrumb": filename}]

    sections = []
    stack = {}  # level -> heading text

    for i, m in enumerate(matches):
        level = len(m.group(1))
        heading = m.group(2).strip()

        # Clear deeper headings from stack
        for lvl in list(stack):
            if lvl >= level:
                del stack[lvl]
        stack[level] = heading

        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()

        breadcrumb = filename + " > " + " > ".join(
            stack[k] for k in sorted(stack)
        )
        sections.append({"text": body, "breadcrumb": breadcrumb, "heading": heading})

    # Skip Table of Contents section
    sections = [s for s in sections if "table of contents" not in s["heading"].lower()]

    # Merge small sections into next sibling
    merged = []
    carry = ""
    carry_bc = ""
    for s in sections:
        combined = (carry + "\n\n" + s["text"]).strip() if carry else s["text"]
        bc = carry_bc or s["breadcrumb"]
        if len(combined) < MIN_CHUNK_CHARS and s is not sections[-1]:
            carry = combined
            carry_bc = bc
        else:
            merged.append({"text": combined, "breadcrumb": bc})
            carry = ""
            carry_bc = ""
    if carry:
        if merged:
            merged[-1]["text"] += "\n\n" + carry
        else:
            merged.append({"text": carry, "breadcrumb": carry_bc})

    # Split large sections on paragraph boundaries
    final = []
    for s in merged:
        if len(s["text"]) <= MAX_CHUNK_CHARS:
            final.append(s)
            continue
        paragraphs = s["text"].split("\n\n")
        chunk_text = ""
        for p in paragraphs:
            if chunk_text and len(chunk_text) + len(p) > MAX_CHUNK_CHARS:
                final.append({"text": chunk_text.strip(), "breadcrumb": s["breadcrumb"]})
                chunk_text = p
            else:
                chunk_text = (chunk_text + "\n\n" + p).strip()
        if chunk_text.strip():
            final.append({"text": chunk_text.strip(), "breadcrumb": s["breadcrumb"]})

    return final


# --- Embedding -----------------------------------------------------------

def cloud_embed_batch(texts):
    """Embed a list of texts via an OpenAI-compatible API. Returns list of float vectors."""
    model = config_get_by_key("embeddingModel", EMBEDDING_MODEL)
    provider = str(config_get_by_key("embeddingprovider", "OpenAI"))
    proxy_url = config_get_by_key("GATEWAY_URL")
    if proxy_url:
        client = openai.OpenAI(base_url=f"{proxy_url.rstrip('/')}/{provider.lower()}/", api_key="unused")
    else:
        client = openai.OpenAI()
    try:
        resp = client.embeddings.create(model=model, input=texts)
    except Exception as e:
        raise RuntimeError(f"Embedding request failed: {e}") from e
    return [item.embedding for item in resp.data]


def cloud_embed(text):
    """Embed one runtime memory string via the configured OpenAI route."""
    return cloud_embed_batch([text])[0]


def local_embed_batch(texts):
    """Embed a list of texts via lib_llm_ext local embeddings."""
    if isinstance(texts, str):
        texts = [texts]

    if not texts:
        return []

    initLocalEmbedding()

    return [
        useLocalEmbedding(text)
        for text in texts
    ]

# --- Hash sentinel docs --------------------------------------------------

def _hash_id(filename):
    return f"hash_{filename}"


def _get_stored_hash(collection, filename):
    try:
        result = collection.get(ids=[_hash_id(filename)], include=["metadatas"])
        if result["ids"]:
            return result["metadatas"][0].get("hash")
    except Exception as e:
        logger.warning(f"{filename}: could not read stored hash, re-indexing: {e}")
    return None


def _store_hash(collection, filename, hash_val, embedding_dim):
    """Store a hash sentinel doc. Uses a zero-vector as dummy embedding."""
    collection.upsert(
        ids=[_hash_id(filename)],
        embeddings=[[0.0] * embedding_dim],
        documents=[f"hash sentinel for {filename}"],
        metadatas=[{"type": "hash", "hash": hash_val, "source": filename}],
    )


# --- Init & Query --------------------------------------------------------

_embedding_dim = None
_last_query = None
_last_result = None


def init_knowledge(embedding_selection):
    """Chunk, embed, and store knowledge files. Skips unchanged files."""
    global _embedding_dim, _last_query, _last_result
    _last_query = None
    _last_result = None
    logger.info(f"Embedding type selected is {embedding_selection}")

    try:
        collection = _get_collection()
        knowledge_dir = _resolve_knowledge_dir()

        if not os.path.isdir(knowledge_dir):
            return f"Knowledge dir not found: {knowledge_dir}, bypassing knowledge load..."

        md_files = sorted(glob.glob(os.path.join(knowledge_dir, "*.md")))
        if not md_files:
            return "No markdown .md files found in directory knowledge-priors, bypassing knowledge load..."

        unchanged = 0
        reindexed = 0

        for filepath in md_files:
            filename = os.path.basename(filepath)
            current_hash = _file_hash(filepath)
            stored_hash = _get_stored_hash(collection, filename)

            if stored_hash == current_hash:
                logger.debug(f"{filename}: unchanged (skipped)")
                unchanged += 1
                continue

            # Delete old chunks for this file
            try:
                old = collection.get(where={"source": filename}, include=[])
                if old["ids"]:
                    collection.delete(ids=old["ids"])
            except Exception as e:
                logger.warning(f"{filename}: could not delete old chunks, stale chunks may remain: {e}")

            # Chunk and embed
            text = open(filepath, "r", encoding="utf-8").read()
            chunks = _chunk_markdown(text, filename)
            if not chunks:
                continue

            texts = [c["text"] for c in chunks]
            if embedding_selection == "Local":
                embeddings = local_embed_batch(texts)
            elif embedding_selection.lower() in ("asicloud", "openai"):
                embeddings = cloud_embed_batch(texts)
            else:
                raise NotImplementedError(f"Unsupported embedding provider: {embedding_selection}")
            if not embeddings:
                logger.warning(f"{filename}: embedding failed, skipping")
                continue

            if _embedding_dim is None:
                _embedding_dim = len(embeddings[0])

            # Store chunks
            ids = [f"{filename}_chunk_{i}" for i in range(len(chunks))]
            metadatas = [
                {
                    "source": filename,
                    "breadcrumb": c["breadcrumb"],
                    "type": "chunk",
                    "time": "knowledge_prior"
                }
                for c in chunks
            ]
            collection.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
            )

            # Store hash sentinel
            _store_hash(collection, filename, current_hash, _embedding_dim)

            logger.info(f"{filename}: indexed {len(chunks)} chunks")
            reindexed += 1

        total = unchanged + reindexed
        return f"Knowledge: {total} files ({unchanged} unchanged, {reindexed} re-indexed)"

    except Exception as e:
        logger.exception(f"Knowledge init failed: {e}", exc_info=True)
        return f"Knowledge init failed: {e}"
