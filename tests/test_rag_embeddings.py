import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture
def cloud_embeddings(monkeypatch):
    openai = types.ModuleType("openai")
    openai.OpenAI = Mock()
    local = types.ModuleType("lib_llm_ext")
    local.initLocalEmbedding = Mock()
    local.useLocalEmbedding = Mock()
    monkeypatch.setitem(sys.modules, "openai", openai)
    monkeypatch.setitem(sys.modules, "chromadb", types.ModuleType("chromadb"))
    monkeypatch.setitem(sys.modules, "lib_llm_ext", local)

    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root))
    spec = importlib.util.spec_from_file_location(
        "rag_embeddings_under_test", root / "src" / "rag.py"
    )
    rag = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rag)
    settings = {"GATEWAY_URL": "http://gateway:8080"}
    monkeypatch.setattr(
        rag, "config_get_by_key", lambda key, default=None: settings.get(key, default)
    )

    def embed(*, model, input):
        # Simulate valid 8192-token inputs at the API's aggregate token limit.
        if len(input) * 8192 > 300_000:
            raise ValueError("maximum 300000 tokens per request")
        return types.SimpleNamespace(data=[
            types.SimpleNamespace(embedding=[float(text)]) for text in input
        ])

    openai.OpenAI.return_value.embeddings.create.side_effect = embed
    return rag, openai.OpenAI, settings


def test_cloud_embeddings_batch_large_files_and_keep_input_order(cloud_embeddings):
    rag, client, _ = cloud_embeddings
    texts = [str(i) for i in range(70)]

    assert rag.cloud_embed_batch(texts) == [[float(i)] for i in range(70)]

    calls = client.return_value.embeddings.create.call_args_list
    assert [len(call.kwargs["input"]) for call in calls] == [32, 32, 6]
    assert [text for call in calls for text in call.kwargs["input"]] == texts
    client.assert_called_once_with(
        base_url="http://gateway:8080/openai/", api_key="unused"
    )


@pytest.mark.parametrize("size", [2, "2"])
def test_cloud_embeddings_use_configured_batch_size(cloud_embeddings, size):
    rag, client, settings = cloud_embeddings
    settings.update(embeddingprovider="ASICloud", embeddingBatchSize=size)

    assert rag.cloud_embed_batch(["0", "1", "2"]) == [[0.0], [1.0], [2.0]]

    calls = client.return_value.embeddings.create.call_args_list
    assert [call.kwargs for call in calls] == [
        {"model": "WhereIsAI/UAE-Large-V1", "input": ["0", "1"]},
        {"model": "WhereIsAI/UAE-Large-V1", "input": ["2"]},
    ]
    client.assert_called_once_with(
        base_url="http://gateway:8080/asicloud/", api_key="unused"
    )


def test_empty_cloud_embeddings_do_not_create_a_client(cloud_embeddings):
    rag, client, _ = cloud_embeddings

    assert rag.cloud_embed_batch([]) == []

    client.assert_not_called()


@pytest.mark.parametrize("size", [0, -1, "invalid", "1.5", 1.5, True, None])
def test_invalid_batch_size_fails_before_request(cloud_embeddings, size):
    rag, client, settings = cloud_embeddings
    settings["embeddingBatchSize"] = size

    with pytest.raises(ValueError, match="embeddingBatchSize must be a positive integer"):
        rag.cloud_embed_batch(["0"])

    client.assert_not_called()


def test_later_batch_failure_does_not_return_partial_embeddings(cloud_embeddings):
    rag, client, settings = cloud_embeddings
    settings["embeddingBatchSize"] = 2
    error = ValueError("provider unavailable")
    create = client.return_value.embeddings.create
    create.side_effect = [
        types.SimpleNamespace(data=[
            types.SimpleNamespace(embedding=[0.0]),
            types.SimpleNamespace(embedding=[1.0]),
        ]),
        error,
    ]

    with pytest.raises(RuntimeError, match="Embedding request failed") as exc:
        rag.cloud_embed_batch(["0", "1", "2", "3", "4"])

    assert exc.value.__cause__ is error
    assert create.call_count == 2
    assert create.call_args.kwargs["input"] == ["2", "3"]
