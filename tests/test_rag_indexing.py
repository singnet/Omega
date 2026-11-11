"""Startup indexing tests with event-controlled embeddings."""

import importlib.util
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 5


@pytest.fixture
def rag_fixture(monkeypatch, tmp_path):
    monkeypatch.delenv("CHROMA_DB_PATH", raising=False)
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "lib_llm_ext",
        SimpleNamespace(
            initLocalEmbedding=lambda: None, useLocalEmbedding=lambda _: []
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "lib_chromadb",
        SimpleNamespace(COLLECTION=Mock(get=Mock(return_value={"ids": []}))),
    )
    spec = importlib.util.spec_from_file_location(
        "rag_indexing_test", REPO_ROOT / "src/rag.py"
    )
    rag = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rag)
    settings = {}
    monkeypatch.setattr(
        rag, "config_get_by_key", lambda key, default=None: settings.get(key, default)
    )
    monkeypatch.setattr(rag, "_resolve_knowledge_dir", lambda: str(tmp_path))
    (tmp_path / "guide.md").write_text("Knowledge", encoding="utf-8")
    entered, release = threading.Event(), threading.Event()
    calls = []

    def embed(texts):
        calls.append(threading.get_ident())
        entered.set()
        assert release.wait(TIMEOUT)
        return [[1.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr(rag, "local_embed_batch", embed)
    yield rag, settings, entered, release, calls
    release.set()
    if rag._knowledge_worker is not None:
        rag._knowledge_worker.join(TIMEOUT)
        assert not rag._knowledge_worker.is_alive()


@pytest.mark.parametrize("value", [None, False, "false", True, "true"])
def test_startup_indexing_mode(rag_fixture, value):
    rag, settings, entered, release, calls = rag_fixture
    if value is not None:
        settings["knowledgeIndexingBackground"] = value
    background = value is True or value == "true"
    returned = threading.Event()
    results = []

    def startup():
        results.append(rag.init_knowledge("Local"))
        returned.set()

    caller = threading.Thread(target=startup)
    caller.start()
    try:
        assert entered.wait(TIMEOUT)
        if background:
            assert returned.wait(TIMEOUT)
            assert rag._knowledge_worker.daemon
            assert calls != [caller.ident]
        else:
            assert calls == [caller.ident]
            assert not returned.is_set()
    finally:
        release.set()
        caller.join(TIMEOUT)
    assert not caller.is_alive()
    assert results == [
        (
            "Knowledge indexing started in background"
            if background
            else "Knowledge: 1 files (0 unchanged, 1 re-indexed)"
        )
    ]


def test_concurrent_initializations_start_one_worker(rag_fixture):
    rag, settings, entered, release, calls = rag_fixture
    settings["knowledgeIndexingBackground"] = True
    barrier = threading.Barrier(4)

    def initialize(_):
        barrier.wait(TIMEOUT)
        return rag.init_knowledge("Local")

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(initialize, range(4)))
        assert entered.wait(TIMEOUT)
        assert results.count("Knowledge indexing started in background") == 1
        assert results.count("Knowledge indexing already running") == 3
        assert len(calls) == 1
    finally:
        release.set()


def test_background_failure_is_logged(rag_fixture, monkeypatch, caplog):
    rag, settings, _, _, _ = rag_fixture
    settings["knowledgeIndexingBackground"] = True

    def broken_embed(texts):
        raise ValueError("provider unavailable")

    monkeypatch.setattr(rag, "local_embed_batch", broken_embed)
    with caplog.at_level(logging.ERROR):
        rag.init_knowledge("Local")
        rag._knowledge_worker.join(TIMEOUT)
    assert any(
        record.exc_info and "provider unavailable" in record.message
        for record in caplog.records
    )


@pytest.mark.parametrize("has_files", [True, False])
def test_background_completion_is_logged(rag_fixture, tmp_path, caplog, has_files):
    rag, settings, _, release, _ = rag_fixture
    settings["knowledgeIndexingBackground"] = True
    if not has_files:
        (tmp_path / "guide.md").unlink()
    release.set()
    with caplog.at_level(logging.INFO):
        rag.init_knowledge("Local")
        rag._knowledge_worker.join(TIMEOUT)
    expected = (
        "Knowledge: 1 files (0 unchanged, 1 re-indexed)"
        if has_files
        else "No markdown .md files found in directory knowledge-priors, bypassing knowledge load..."
    )
    assert expected in caplog.messages
