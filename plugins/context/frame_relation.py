from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

import chromadb
from openai import OpenAI
import lib_llm_ext
from config import config_get_by_key

CHROMA_DB_PATH = os.environ.get("CHROMA_DB_PATH", "./chroma_db")
FRAME_SKETCH_COLLECTION_BASE = os.environ.get("FRAME_SKETCH_COLLECTION", "cfv2_frame_sketches")
FRAME_EMBED_MODEL = os.environ.get("FRAME_EMBED_MODEL", "text-embedding-3-large")

_chroma_client = None
_collections: dict[str, Any] = {}
_openai_client = None
_local_embedding_ready = False


def _provider_name(provider: Any) -> str:
    p = str(provider or "OpenAI").strip().strip('"')
    p = re.sub(r"[^A-Za-z0-9_\-]", "", p)
    return p or "OpenAI"


def _collection_name(provider: str) -> str:
    # Separate collections prevent dimension conflicts between OpenAI and Local embeddings.
    return f"{FRAME_SKETCH_COLLECTION_BASE}_{provider.lower()}"[:63]


def _get_collection(provider: str):
    global _chroma_client, _collections
    provider = _provider_name(provider)
    name = _collection_name(provider)
    if name not in _collections:
        if _chroma_client is None:
            _chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        _collections[name] = _chroma_client.get_or_create_collection(
            name=name,
            embedding_function=None,
        )
    return _collections[name]


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()
    return _openai_client


# -----------------------------------------------------------------------------
# S-expression helpers
# -----------------------------------------------------------------------------

def _balanced_end(s: str, start: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    return len(s)


def _find_exprs_with_head(s: str, head: str) -> list[str]:
    out: list[str] = []
    needle = f"({head}"
    i = 0
    while True:
        i = s.find(needle, i)
        if i < 0:
            break
        after = i + len(needle)
        if after < len(s) and not s[after].isspace() and s[after] != ")":
            i = after
            continue
        end = _balanced_end(s, i)
        out.append(s[i:end])
        i = end
    return out


def _field(expr: str, name: str, default: str = "") -> str:
    needle = f"({name}"
    i = 0
    while True:
        i = expr.find(needle, i)
        if i < 0:
            return default
        after = i + len(needle)
        if after < len(expr) and not expr[after].isspace() and expr[after] != ")":
            i = after
            continue
        end = _balanced_end(expr, i)
        inner = expr[i + 1:end - 1].strip()
        if inner == name:
            return default
        return inner[len(name):].strip()


def _first_field(expr: str, names: list[str], default: str = "") -> str:
    for name in names:
        value = _field(expr, name, "")
        if value not in ("", "()"):
            return value
    return default


def _strip_outer_quotes(x: Any) -> str:
    s = "" if x is None else str(x).strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def _compact(x: Any, limit: int = 900) -> str:
    s = _strip_outer_quotes(x)
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= limit else s[:limit - 16] + "...<truncated>"


def _sym(x: Any, default: str = "UNKNOWN") -> str:
    s = _strip_outer_quotes(x)
    s = re.sub(r"[^A-Za-z0-9_\-:.]", "", s)
    return s or default


def _quote(x: Any) -> str:
    s = "" if x is None else str(x)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def _float(x: Any, default: float = 0.0) -> float:
    try:
        return float(_strip_outer_quotes(x))
    except Exception:
        return default


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# -----------------------------------------------------------------------------
# Frame parsing/document creation
# -----------------------------------------------------------------------------

def _parse_frame_sketches(compact_frames_repr: str) -> list[dict[str, Any]]:
    """
    Accepts compact Frame atoms, not FrameSketch atoms.

    Expected:
    ((Frame (frameID FrameA) (parentID ParentA) (status Active)
            (priority 1.0) (deliverable "goal") (results "summary")) ...)
    """
    frames: list[dict[str, Any]] = []
    for expr in _find_exprs_with_head(str(compact_frames_repr), "Frame"):
        frame_id = _first_field(expr, ["frameID", "FrameID"], "")
        if frame_id in ("", "()"):
            continue
        frames.append({
            "frameID": _sym(frame_id),
            "parentID": _sym(_first_field(expr, ["parentID", "parent-frameID"], "")),
            "status": _sym(_first_field(expr, ["status"], "")),
            "priority": _float(_first_field(expr, ["priority"], "0.0")),
            "deliverable": _compact(_first_field(expr, ["deliverable", "deliverables"], ""), 900),
            "results": _compact(_first_field(expr, ["results"], ""), 900),
            "source": _sym(_first_field(expr, ["source"], "")),
            "mode": _sym(_first_field(expr, ["mode", "frame-mode"], "")),
        })
    return frames


def _frame_document(frame: dict[str, Any]) -> str:
    # This exact text is embedded and stored.
    return (
        f"(Frame "
        f"(frameID {frame['frameID']}) "
        f"(parentID {frame['parentID']}) "
        f"(status {frame['status']}) "
        f"(priority {frame['priority']}) "
        f"(deliverable {frame['deliverable']}) "
        f"(results {frame['results']}))"
    )


def _frame_metadata(frame: dict[str, Any], provider: str, content_hash: str) -> dict[str, Any]:
    return {
        "frameID": frame["frameID"],
        "parentID": frame["parentID"],
        "status": frame["status"],
        "priority": float(frame["priority"]),
        "source": frame["source"],
        "mode": frame["mode"],
        "embeddingProvider": provider,
        "contentHash": content_hash,
    }


# -----------------------------------------------------------------------------
# Embedding providers
# -----------------------------------------------------------------------------

def _coerce_vector(value: Any) -> list[float]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [float(x) for x in value]
    if hasattr(value, "tolist"):
        return [float(x) for x in value.tolist()]
    text = str(value).strip().replace("[", " ").replace("]", " ")
    text = text.replace("(", " ").replace(")", " ").replace(",", " ")
    nums = re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", text)
    return [float(n) for n in nums]


def _embed_texts_openai(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    client = _get_openai_client()
    response = client.embeddings.create(model=FRAME_EMBED_MODEL, input=texts)
    return [list(item.embedding) for item in response.data]


def _embed_texts_local(texts: list[str]) -> list[list[float]]:
    """
    Uses your existing local embedding module:
      lib_llm_ext.initLocalEmbedding()
      lib_llm_ext.useLocalEmbedding(text)
    """
    global _local_embedding_ready
    if not texts:
        return []

    if not _local_embedding_ready:
        try:
            lib_llm_ext.initLocalEmbedding()
        except Exception:
            pass
        _local_embedding_ready = True

    return [_coerce_vector(lib_llm_ext.useLocalEmbedding(str(t))) for t in texts]


def _embed_texts(texts: list[str], provider: str) -> list[list[float]]:
    provider = _provider_name(provider)
    if provider.lower() == "openai":
        return _embed_texts_openai(texts)
    if provider.lower() == "local":
        return _embed_texts_local(texts)
    raise ValueError(f"Unknown embedding provider: {provider}")


# -----------------------------------------------------------------------------
# Chroma upsert/search using explicit embeddings
# -----------------------------------------------------------------------------

def _existing_hashes(collection, ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    try:
        result = collection.get(ids=ids, include=["metadatas"])
    except Exception:
        return {}
    out: dict[str, str] = {}
    for fid, meta in zip(result.get("ids", []) or [], result.get("metadatas", []) or []):
        if meta and "contentHash" in meta:
            out[str(fid)] = str(meta["contentHash"])
    return out


def _upsert_changed_frames(frames: list[dict[str, Any]], provider: str) -> dict[str, list[float]]:
    """
    Upserts only new/changed frames.
    Returns embeddings computed during this call: frameID -> embedding.
    """
    if not frames:
        return {}

    provider = _provider_name(provider)
    collection = _get_collection(provider)

    ids = [f["frameID"] for f in frames if f["frameID"] != "UNKNOWN"]
    old_hashes = _existing_hashes(collection, ids)

    changed_frames = []
    changed_docs = []
    changed_hashes = []

    for frame in frames:
        fid = frame["frameID"]
        if not fid or fid == "UNKNOWN":
            continue
        doc = _frame_document(frame)
        content_hash = _hash_text(f"{provider}:{FRAME_EMBED_MODEL}:{doc}")
        if old_hashes.get(fid) == content_hash:
            continue
        changed_frames.append(frame)
        changed_docs.append(doc)
        changed_hashes.append(content_hash)

    if not changed_frames:
        return {}

    embeddings = _embed_texts(changed_docs, provider)
    computed: dict[str, list[float]] = {}

    upsert_ids = []
    upsert_docs = []
    upsert_metas = []
    upsert_embeddings = []

    for frame, doc, content_hash, emb in zip(changed_frames, changed_docs, changed_hashes, embeddings):
        fid = frame["frameID"]
        computed[fid] = emb
        upsert_ids.append(fid)
        upsert_docs.append(doc)
        upsert_metas.append(_frame_metadata(frame, provider, content_hash))
        upsert_embeddings.append(emb)

    collection.upsert(
        ids=upsert_ids,
        embeddings=upsert_embeddings,
        documents=upsert_docs,
        metadatas=upsert_metas,
    )

    return computed


def _search_top_k(query_frame: dict[str, Any], query_embedding: list[float], provider: str, top_k: int) -> list[dict[str, Any]]:
    if not query_embedding:
        return []

    collection = _get_collection(provider)
    if collection.count() <= 1:
        return []

    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=max(1, int(top_k) + 1),
        include=["documents", "metadatas", "distances"],
    )

    ids = result.get("ids", [[]])[0]
    docs = result.get("documents", [[]])[0]
    metas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    hits: list[dict[str, Any]] = []
    for hit_id, doc, meta, distance in zip(ids, docs, metas, distances):
        if hit_id == query_frame["frameID"]:
            continue
        hits.append({
            "frameID": str(hit_id),
            "document": doc,
            "metadata": meta or {},
            "distance": float(distance),
        })
        if len(hits) >= int(top_k):
            break
    return hits


# -----------------------------------------------------------------------------
# Classifier
# -----------------------------------------------------------------------------

def _parse_relation_classes(relation_classes_repr: str) -> list[str]:
    classes = re.findall(r"[A-Za-z][A-Za-z0-9_\-]*", str(relation_classes_repr))
    ignored = {"RelationClasses", "ClassList", "List", "Set", "Class", "Classes"}
    classes = [c for c in classes if c not in ignored]
    return list(dict.fromkeys(classes)) if classes else ["RelatedButSeparate", "Unrelated"]


def _call_selected_llm(content: str, max_tokens: int, reasoning_mode: str) -> str:
    import providers

    # Classification is an internal result, not a user-facing send operation.
    tools = providers.getTools([
        ("frame_relations", "Return the relation classification as JSON", ["json"]),
    ])
    request = providers.llmRequest(
        providers.llmRequestMessage("system", "Classify frame relations and return JSON using frame_relations."),
        [providers.llmRequestMessage("user", content)],
        max_tokens, reasoning_mode, tools,
    )
    response = providers.llmProviderChat(request)
    if response.is_error():
        raise RuntimeError(f"Frame relation classification failed: {response.error}")
    for call in response.calls:
        if call.name == "frame_relations" and not call.is_error():
            return str(call.arguments["json"])
    raise RuntimeError("Frame relation classifier did not return a valid frame_relations call")


def _call_classifier_llm(payload: dict[str, Any]) -> dict[str, Any]:
    system_prompt = """
You classify the relationship between one query frame and each candidate frame.
The purpose is to compose these frames in order to create a more sound and coherent
context-frame.

Return only valid JSON with this schema:
{
  "relations": [
    {
      "frameID1": "query frame id",
      "frameID2": "candidate frame id",
      "class": "one allowed relation class",
      "reason": "short reason",
      "confidence": 0.0
    }
  ]
}

Rules:
- Use only the allowed relation classes.
- frameID1 must be the query frame ID.
- frameID2 must be one of the candidate frame IDs.
- Confidence must be between 0 and 1.
- Be conservative.
- If related but unsafe to merge/compose, use RelatedButSeparate if available.
- If unrelated, do not include them in your answer.
- Do not invent frame IDs.
- Do not output markdown.
""".strip()

    user_text = json.dumps(payload, ensure_ascii=False)
    content = (
        f"{system_prompt}"
        "\n\n"
        f"{user_text}"
    )
    max_tokens = max(
        1,
        int(config_get_by_key("maxOutputToken", 6000)),
    )
    reasoning_mode = str(
        config_get_by_key("reasoningMode", "medium")
    )
    raw = _call_selected_llm(content, max_tokens, reasoning_mode).strip()

    try:
        return json.loads(raw)
    except Exception:
        match = re.search(r"\{.*\}", raw, flags=re.S)
        return json.loads(match.group(0)) if match else {"relations": []}


def _classify_relations(query_frame: dict[str, Any], hits: list[dict[str, Any]], relation_classes: list[str]) -> list[dict[str, Any]]:
    if not hits:
        return []

    payload = {
        "allowed_relation_classes": relation_classes,
        "query_frame": {
            "frameID": query_frame["frameID"],
            "parentID": query_frame["parentID"],
            "status": query_frame["status"],
            "priority": query_frame["priority"],
            "deliverable": query_frame["deliverable"],
            "results": query_frame["results"],
        },
        "candidate_frames": [
            {
                "frameID": hit["frameID"],
                "distance": hit["distance"],
                "document": hit["document"],
                "metadata": hit["metadata"],
            }
            for hit in hits
        ],
    }

    data = _call_classifier_llm(payload)
    allowed = set(relation_classes)
    candidate_ids = {hit["frameID"] for hit in hits}

    if "Unrelated" in allowed:
        default_class = "Unrelated"
    elif "RelatedButSeparate" in allowed:
        default_class = "RelatedButSeparate"
    else:
        default_class = relation_classes[0]

    clean: list[dict[str, Any]] = []
    for item in data.get("relations", []):
        frame_id_1 = _sym(item.get("frameID1", query_frame["frameID"]))
        frame_id_2 = _sym(item.get("frameID2", ""))

        if frame_id_1 != query_frame["frameID"]:
            frame_id_1 = query_frame["frameID"]
        if frame_id_2 not in candidate_ids:
            continue

        rel_class = _sym(item.get("class", default_class))
        if rel_class not in allowed:
            rel_class = default_class

        confidence = max(0.0, min(1.0, _float(item.get("confidence", 0.0), 0.0)))
        clean.append({
            "frameID1": frame_id_1,
            "frameID2": frame_id_2,
            "class": rel_class,
            "reason": _compact(item.get("reason", ""), 300),
            "confidence": confidence,
        })
    return clean


def _relations_to_sexpr(relations: list[dict[str, Any]]) -> str:
    if not relations:
        return "()"
    atoms = []
    for relation in relations:
        atoms.append(
            f"(Relation "
            f"(FrameID-1 {relation['frameID1']}) "
            f"(FrameID-2 {relation['frameID2']}) "
            f"(Class {relation['class']}) "
            f"(Reason {_quote(relation['reason'])}) "
            f"(Confidence {relation['confidence']:.4f}))"
        )
    return f"({' '.join(atoms)})"


# -----------------------------------------------------------------------------
# Main MeTTa py-call entrypoint
# -----------------------------------------------------------------------------

def cfv2_compose_frame_relations(
    compact_frames_repr: str,
    query_frame_id_repr: str,
    relation_classes_repr: str,
    embedding_provider_repr: str = "OpenAI",
    top_k: int = 5,
) -> str:
    """
    Args:
        compact_frames_repr:
            repr string containing compact Frame atoms, with no embedding field.

        query_frame_id_repr:
            current/new frame ID.

        relation_classes_repr:
            allowed classes, e.g.
            (DuplicateOf ContinuationOf SubgoalOf ParentOf DependsOn Blocks
             Supersedes SameProject SameFailureCluster RelatedButSeparate Unrelated)

        embedding_provider_repr:
            OpenAI or Local. Local calls lib_llm_ext.useLocalEmbedding.

        top_k:
            retrieved candidate count.

    Returns:
        String S-expression:
        ((Relation (FrameID-1 FrameA) (FrameID-2 FrameB)
                   (Class ContinuationOf) (Reason "...") (Confidence 0.8600)) ...)
    """
    provider = _provider_name(embedding_provider_repr)
    frames = _parse_frame_sketches(compact_frames_repr)
    query_frame_id = _sym(query_frame_id_repr)
    relation_classes = _parse_relation_classes(relation_classes_repr)

    if not frames or not query_frame_id:
        return "()"

    frame_by_id = {frame["frameID"]: frame for frame in frames}
    query_frame = frame_by_id.get(query_frame_id)
    if query_frame is None:
        return "()"

    computed_embeddings = _upsert_changed_frames(frames, provider)

    query_embedding = computed_embeddings.get(query_frame_id)
    if query_embedding is None:
        query_embedding = _embed_texts([_frame_document(query_frame)], provider)[0]

    hits = _search_top_k(query_frame, query_embedding, provider, top_k)
    if not hits:
        return "()"

    relations = _classify_relations(query_frame, hits, relation_classes)
    return _relations_to_sexpr(relations)
