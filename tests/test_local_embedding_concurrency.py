"""Shared local inference must exclude concurrent tokenizer/model access."""

import importlib.util
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

TIMEOUT = 5
REPO_ROOT = Path(__file__).resolve().parents[1]


def test_local_encodes_do_not_overlap(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=object))
    spec = importlib.util.spec_from_file_location(
        "local_embedding_test", REPO_ROOT / "providers/lib_llm_ext.py"
    )
    llm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(llm)
    entered, release, second_attempt = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    actual_lock = llm._embedding_lock

    class ObservedLock:
        """Signal that the second caller reached the real inference lock."""

        def __enter__(self):
            if threading.current_thread() is second:
                second_attempt.set()
            actual_lock.acquire()

        def __exit__(self, *args):
            actual_lock.release()

    monkeypatch.setattr(llm, "_embedding_lock", ObservedLock())
    calls, results, errors = [], [], []

    def encode(text, normalize_embeddings):
        calls.append(text)
        assert normalize_embeddings is True
        if text == "first":
            entered.set()
            assert release.wait(TIMEOUT)
        return SimpleNamespace(tolist=lambda: [1.0, 0.0])

    llm._embedding_model = SimpleNamespace(encode=encode)

    def run(text):
        try:
            results.append(llm.useLocalEmbedding(text))
        except Exception as exc:
            errors.append(exc)

    first = threading.Thread(target=run, args=("first",))
    second = threading.Thread(target=run, args=("second",))
    first.start()
    try:
        assert entered.wait(TIMEOUT)
        second.start()
        assert second_attempt.wait(TIMEOUT)
        assert calls == ["first"]
        assert not results
    finally:
        release.set()
        first.join(TIMEOUT)
        if second.ident is not None:
            second.join(TIMEOUT)
    assert not first.is_alive() and not second.is_alive()
    assert not errors
    assert calls == ["first", "second"]
    assert results == [[1.0, 0.0], [1.0, 0.0]]
