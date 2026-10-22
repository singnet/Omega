"""Real persistent Chroma + PeTTa bridge; put the bridge directory on PYTHONPATH."""

import importlib.util
import sys
import threading
import types
from pathlib import Path
from unittest.mock import Mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 30


def test_background_indexing_and_runtime_memory_share_persistent_collection(
    monkeypatch, tmp_path
):
    chromadb = pytest.importorskip(
        "chromadb", reason="real Chroma integration requires chromadb"
    )
    bridge_spec = importlib.util.find_spec("lib_chromadb")
    if bridge_spec is None:
        pytest.skip("PeTTa lib_chromadb bridge is required on PYTHONPATH")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    custom_path = tmp_path / "custom-chroma"
    monkeypatch.setenv("CHROMA_DB_PATH", str(custom_path))
    # Execute the actual bridge in an isolated directory, including its client creation.
    spec = importlib.util.spec_from_file_location("lib_chromadb", bridge_spec.origin)
    bridge = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "lib_chromadb", bridge)
    spec.loader.exec_module(bridge)
    llm = types.ModuleType("lib_llm_ext")
    llm.initLocalEmbedding = lambda: None
    llm.useLocalEmbedding = lambda text: [1.0, 0.0, 0.0]
    monkeypatch.setitem(sys.modules, "lib_llm_ext", llm)
    spec = importlib.util.spec_from_file_location(
        "rag_chroma_test", REPO_ROOT / "src/rag.py"
    )
    rag = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rag)
    client_factory = Mock(wraps=chromadb.PersistentClient)
    monkeypatch.setattr(chromadb, "PersistentClient", client_factory)
    monkeypatch.setenv("CHROMA_DB_PATH", str(tmp_path / "chroma_db"))
    rag._configure_chroma_from_env()
    client_factory.assert_not_called()
    monkeypatch.setenv("CHROMA_DB_PATH", str(custom_path))
    monkeypatch.setattr(
        rag,
        "config_get_by_key",
        lambda key, default=None: (
            True if key == "knowledgeIndexingBackground" else default
        ),
    )
    knowledge = tmp_path / "knowledge-priors"
    knowledge.mkdir()
    # Enough records to exercise the HNSW batch buffer as well as its index.
    for i in range(120):
        (knowledge / f"{i:03}.md").write_text(f"prior {i:03}", encoding="utf-8")
    monkeypatch.setattr(rag, "_resolve_knowledge_dir", lambda: str(knowledge))
    entered, release = threading.Event(), threading.Event()

    def embed(texts):
        if texts == ["prior 060"]:
            entered.set()
            assert release.wait(TIMEOUT)
        return [[1.0, 0.0, 0.0] for text in texts]

    monkeypatch.setattr(rag, "local_embed_batch", embed)
    try:
        assert rag.init_knowledge("Local") == "Knowledge indexing started in background"
        assert bridge.CLIENT.get_settings().persist_directory == str(custom_path)
        assert entered.wait(TIMEOUT)
        collection = bridge.COLLECTION
        monkeypatch.setenv("CHROMA_DB_PATH", str(tmp_path / "later-env"))
        assert rag._get_collection() is collection is bridge.COLLECTION
        client_factory.assert_called_once_with(path=str(custom_path))
        assert bridge.COLLECTION.count() >= 100
        time, text = bridge.query([1.0, 0.0, 0.0], 1)[0]
        assert time == "knowledge_prior" and text.startswith("prior ")
        bridge.remember("runtime while indexing", [0.0, 1.0, 0.0], "runtime")
        assert bridge.query([0.0, 1.0, 0.0], 1) == [
            ["runtime", "runtime while indexing"]
        ]
    finally:
        release.set()
    try:
        # Foreground reads/writes continue as the remaining background upserts run.
        for i in range(3):
            bridge.remember(f"runtime {i}", [0.0, 1.0, 0.0], "runtime")
            assert bridge.query([1.0, 0.0, 0.0], 1)[0][0] == "knowledge_prior"
    finally:
        rag._knowledge_worker.join(TIMEOUT)
    assert not rag._knowledge_worker.is_alive()
    assert bridge.COLLECTION.get(ids=["119.md_chunk_0"])["documents"] == ["prior 119"]
