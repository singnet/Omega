"""Shared /memory-export command handling."""

import os
from pathlib import Path

from config import config_get_by_key
from embedding_models import DEFAULT_MODELS, DIMENSIONS, embedding_model
from helper import omega_version, projectRootDirectory
from src.logger import get_logger

logger = get_logger(__name__)

_TRANSFER_DIR = Path("/memory-transfer")

_transfer = None


def _resolve_memory_dir() -> Path:
    default = os.environ.get(
        "MEMORY_DIR",
        str(Path(projectRootDirectory()) / "memory"),
    )
    configured = config_get_by_key("memoryDirectory", default)
    return Path(str(configured)).expanduser().resolve()


def _resolve_chroma_path() -> Path:
    environment_path = os.environ.get("CHROMA_DB_PATH")
    if environment_path:
        return Path(environment_path).expanduser().resolve()

    default = str(Path(projectRootDirectory()).parents[1] / "chroma_db")
    configured = config_get_by_key("chromaDbPath", default)
    return Path(str(configured)).expanduser().resolve()


def _cloud_embedder(provider, model):
    def embed(texts):
        from import_knowledge.import_knowledge import embed_batch, init_embeddings

        init_embeddings(mode=provider.casefold(), model_name=model)
        return embed_batch(texts)

    return embed


def _embedding_options():
    provider = str(config_get_by_key("embeddingprovider", "Local")).strip()
    if provider.casefold() == "local":
        return {}
    model = embedding_model(provider, config_get_by_key("embeddingModel", ""))
    return {
        "embed_batch": _cloud_embedder(provider, model),
        "embedding_profile": {
            "provider": provider,
            "model": model,
            "vector_dimension": DIMENSIONS.get(model),
        },
    }


def create_memory_store():
    """Build an import-kb store from Omega's effective configuration."""
    from memory_portability.storage import MemoryStore

    return MemoryStore(
        memory_dir=_resolve_memory_dir(),
        chroma_path=_resolve_chroma_path(),
        collection_name="memories",
        **_embedding_options(),
    )


def _get_transfer():
    global _transfer
    if _transfer is None:
        from memory_portability import MemoryTransfer

        embedding_provider = str(config_get_by_key("embeddingprovider", "Local")).strip()
        if embedding_provider.casefold() not in {"local", *DEFAULT_MODELS}:
            raise ValueError(f"Unsupported embedding provider: {embedding_provider!r}")

        os.environ["EMBEDDING_PROVIDER"] = embedding_provider
        os.environ["OMEGA_VERSION"] = omega_version()
        _transfer = MemoryTransfer(
            transfer_dir=_TRANSFER_DIR,
            store=create_memory_store(),
        )
    return _transfer


_VALID_COMPONENTS = ("history", "ltm", "both")


def is_export_enabled() -> bool:
    value = config_get_by_key("memoryExportEnabled", False)
    return value is True or (
        isinstance(value, str) and value.strip().lower() == "true"
    )


def is_export_command(text: str) -> bool:
    command = text.strip().split(None, 1)
    if not command:
        return False
    name = command[0].lower()
    return name == "/memory-export" or name.startswith("/memory-export@")


def _command_arguments(text: str) -> str:
    parts = text.strip().split(None, 1)
    return parts[1].strip() if len(parts) == 2 else ""


def handle_export_command(
    text: str,
    authenticated_user_id: str | None = None,
) -> str | None:
    stripped = text.strip()

    if not is_export_command(stripped):
        return None

    if not is_export_enabled():
        return None

    if not authenticated_user_id:
        return "Memory export denied: an authenticated user is required."

    rest = _command_arguments(stripped)
    component = rest.lower()

    if component in _VALID_COMPONENTS:
        return _export(component)

    return (
        "Unknown /memory-export command. "
        "Use: /memory-export history|ltm|both"
    )


def _export(component: str) -> str:
    try:
        result = _get_transfer().export(component)
        return _format_export(result)
    except Exception as exc:
        logger.exception(f"memory_export: export failed: {exc}")
        return f"Memory export failed: {exc}"


def _format_export(result: dict) -> str:
    return (
        "Memory export complete\n"
        f"File:     {result.get('filename')}\n"
        f"Size:     {result.get('size')} bytes\n"
        f"SHA-256:  {result.get('sha256', result.get('checksum'))}\n"
        f"Records:  {result.get('record_count')}"
    )
