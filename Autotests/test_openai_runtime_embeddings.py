import importlib.util
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RAG_MODULE_PATH = REPO_ROOT / "src" / "rag.py"
MEMORY_METTA_PATH = REPO_ROOT / "src" / "memory.metta"


def load_rag_module(monkeypatch, config=None, expected_model="text-embedding-3-large"):
    created_clients = []
    settings = {"GATEWAY_URL": "http://gateway:8080", **(config or {})}

    class FakeEmbeddings:
        def create(self, *, model, input):
            assert model == expected_model
            assert input == ["runtime probe"]
            return types.SimpleNamespace(
                data=[types.SimpleNamespace(embedding=[0.1, 0.2, 0.3])]
            )

    class FakeOpenAI:
        def __init__(self, *, base_url=None, api_key=None):
            self.base_url = base_url
            self.api_key = api_key
            self.embeddings = FakeEmbeddings()
            created_clients.append(self)

    openai_module = types.ModuleType("openai")
    openai_module.OpenAI = FakeOpenAI
    chromadb_module = types.ModuleType("chromadb")
    config_module = types.ModuleType("config")
    config_module.config_get_by_key = (
        lambda key, default=None: settings.get(key, default)
    )
    llm_module = types.ModuleType("lib_llm_ext")
    llm_module.initLocalEmbedding = lambda: None
    llm_module.useLocalEmbedding = lambda text: [0.0]

    monkeypatch.syspath_prepend(str(REPO_ROOT))
    monkeypatch.setitem(sys.modules, "openai", openai_module)
    monkeypatch.setitem(sys.modules, "chromadb", chromadb_module)
    monkeypatch.setitem(sys.modules, "config", config_module)
    monkeypatch.setitem(sys.modules, "lib_llm_ext", llm_module)

    spec = importlib.util.spec_from_file_location("rag_under_test", RAG_MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, created_clients


def test_runtime_openai_embedding_uses_proxy_and_returns_single_vector(monkeypatch):
    rag, clients = load_rag_module(monkeypatch)

    assert rag.cloud_embed("runtime probe") == [0.1, 0.2, 0.3]
    assert len(clients) == 1
    assert clients[0].base_url == "http://gateway:8080/openai/"
    assert clients[0].api_key == "unused"


def test_runtime_embedding_uses_the_configured_provider_and_model(monkeypatch):
    rag, clients = load_rag_module(
        monkeypatch,
        config={"embeddingprovider": "ASICloud",
                "embeddingModel": "WhereIsAI/UAE-Large-V1"},
        expected_model="WhereIsAI/UAE-Large-V1",
    )

    assert rag.cloud_embed("runtime probe") == [0.1, 0.2, 0.3]
    assert clients[0].base_url == "http://gateway:8080/asicloud/"


def test_memory_metta_routes_openai_embeddings_to_rag_wrapper():
    memory_metta = MEMORY_METTA_PATH.read_text(encoding="utf-8")

    assert "(py-call (rag.cloud_embed (string-safe $str)))" in memory_metta
    assert "useGPTEmbedding" not in memory_metta
