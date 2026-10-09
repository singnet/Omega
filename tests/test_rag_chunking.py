import importlib.util
import logging
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def rag(monkeypatch):
    """Load src/rag.py with embedding and storage deps stubbed."""
    logger_mod = types.ModuleType("src.logger")
    logger_mod.get_logger = lambda name: logging.getLogger(name)
    monkeypatch.setitem(sys.modules, "src.logger", logger_mod)

    chromadb_mod = types.ModuleType("chromadb")
    chromadb_mod.PersistentClient = lambda **kwargs: None
    monkeypatch.setitem(sys.modules, "chromadb", chromadb_mod)

    openai_mod = types.ModuleType("openai")
    openai_mod.OpenAI = object
    monkeypatch.setitem(sys.modules, "openai", openai_mod)

    llm_mod = types.ModuleType("lib_llm_ext")
    llm_mod.initLocalEmbedding = lambda: None
    llm_mod.useLocalEmbedding = lambda text: []
    monkeypatch.setitem(sys.modules, "lib_llm_ext", llm_mod)

    config_mod = types.ModuleType("config")
    config_mod.config_get_by_key = lambda key, default=None: default
    monkeypatch.setitem(sys.modules, "config", config_mod)

    embedding_mod = types.ModuleType("embedding_models")
    embedding_mod.embedding_model = lambda provider, model: model
    monkeypatch.setitem(sys.modules, "embedding_models", embedding_mod)

    spec = importlib.util.spec_from_file_location(
        "rag_under_test", REPO_ROOT / "src" / "rag.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def largest(chunks):
    return max(len(c["text"]) for c in chunks)


def test_headingless_file_is_not_returned_whole(rag):
    text = ("word " * 3000 + "\n\n") * 8
    chunks = rag._chunk_markdown(text, "plain.md")

    assert len(chunks) > 1
    assert largest(chunks) <= rag.MAX_CHUNK_CHARS


def test_single_heading_does_not_change_the_bound(rag):
    text = ("word " * 3000 + "\n\n") * 8

    without = rag._chunk_markdown(text, "plain.md")
    with_heading = rag._chunk_markdown("# Chapter\n\n" + text, "with.md")

    assert largest(without) <= rag.MAX_CHUNK_CHARS
    assert largest(with_heading) <= rag.MAX_CHUNK_CHARS


def test_paragraph_longer_than_the_cap_is_cut(rag):
    # One paragraph, no blank lines.
    chunks = rag._chunk_markdown("# H\n\n" + "word " * 30000, "nl.md")

    assert largest(chunks) <= rag.MAX_CHUNK_CHARS


def test_text_with_no_whitespace_is_cut_mid_token(rag):
    chunks = rag._chunk_markdown("x" * (rag.MAX_CHUNK_CHARS * 3), "blob.md")

    assert largest(chunks) <= rag.MAX_CHUNK_CHARS
    assert "".join(c["text"] for c in chunks) == "x" * (rag.MAX_CHUNK_CHARS * 3)


def test_cuts_prefer_whitespace_boundaries(rag):
    chunks = rag._chunk_markdown("word " * 30000, "words.md")

    assert largest(chunks) <= rag.MAX_CHUNK_CHARS
    for chunk in chunks:
        assert "wor d" not in chunk["text"]
        assert chunk["text"].startswith("word")
        assert chunk["text"].endswith("word")


def test_headingless_chunks_keep_the_filename_breadcrumb(rag):
    chunks = rag._chunk_markdown(("word " * 3000 + "\n\n") * 8, "plain.md")

    assert {c["breadcrumb"] for c in chunks} == {"plain.md"}


def test_short_headingless_file_stays_one_chunk(rag):
    chunks = rag._chunk_markdown("just a short note", "note.md")

    assert chunks == [{"text": "just a short note", "breadcrumb": "note.md"}]


def test_heading_structure_and_breadcrumbs_are_preserved(rag):
    text = (
        "# Top\n\n" + "a" * 200 + "\n\n"
        "## Nested\n\n" + "b" * 200 + "\n\n"
        "# Second\n\n" + "c" * 200 + "\n"
    )
    chunks = rag._chunk_markdown(text, "doc.md")

    assert [c["breadcrumb"] for c in chunks] == [
        "doc.md > Top",
        "doc.md > Top > Nested",
        "doc.md > Second",
    ]


def test_paragraph_join_does_not_leave_a_fragment(rag):
    # Two paragraphs landing within the "\n\n" join of the cap.
    a = " ".join(["word"] * 600)
    b = " ".join(["word"] * 600) + "s"
    chunks = rag._chunk_markdown("# H\n\n" + a + "\n\n" + b, "t.md")

    assert [len(c["text"]) for c in chunks] == [2999, 3000]


def test_text_before_the_first_heading_is_kept(rag):
    doc = "Text before the first heading.\n\n# Heading\n\nText after the heading.\n"
    chunks = rag._chunk_markdown(doc, "t.md")

    assert "Text before the first heading." in " ".join(c["text"] for c in chunks)


def test_long_preamble_becomes_its_own_section(rag):
    preamble = "a" * 500
    chunks = rag._chunk_markdown(preamble + "\n\n# Heading\n\n" + "b" * 500, "t.md")

    assert chunks[0] == {"text": preamble, "breadcrumb": "t.md"}
    assert chunks[1]["breadcrumb"] == "t.md > Heading"


def test_bare_hash_line_is_not_a_heading(rag):
    chunks = rag._chunk_markdown("Body text.\n\n#\n35\n", "t.md")

    assert {c["breadcrumb"] for c in chunks} == {"t.md"}
    assert "35" in " ".join(c["text"] for c in chunks)


def test_warns_when_a_file_has_no_headings(rag, caplog):
    with caplog.at_level(logging.WARNING):
        rag._chunk_markdown(("word " * 3000 + "\n\n") * 8, "plain.md")

    assert "no headings, chunking on paragraphs" in caplog.text


def test_warns_when_a_character_level_cut_is_needed(rag, caplog):
    with caplog.at_level(logging.WARNING):
        rag._chunk_markdown("# H\n\n" + "word " * 30000, "nl.md")

    assert "cut to MAX_CHUNK_CHARS" in caplog.text
