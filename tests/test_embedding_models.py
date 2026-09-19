import pytest

import config
import embedding_models


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    for name in ("_CONFIG", "_COMMAND_LINE", "_CONFIG_FILE"):
        monkeypatch.setattr(config, name, getattr(config, name))


@pytest.mark.parametrize(
    "provider, model",
    [
        ("ASICloud", "WhereIsAI/UAE-Large-V1"),
        ("OpenAI", "text-embedding-3-large"),
    ],
)
def test_shipped_config_resolves_to_the_provider_default(provider, model):
    config.init_config([f"embeddingprovider={provider}"])

    configured = config.config_get_by_key("embeddingModel", "")

    assert embedding_models.embedding_model(provider, configured) == model


def test_explicit_model_wins_over_the_provider_default():
    assert embedding_models.embedding_model(
        "ASICloud", "BAAI/bge-base-en-v1.5"
    ) == "BAAI/bge-base-en-v1.5"


def test_provider_defaults_match_import_kb():
    import_knowledge = pytest.importorskip("import_knowledge.import_knowledge")

    for provider, model in embedding_models.DEFAULT_MODELS.items():
        assert import_knowledge.PROVIDERS[provider]["default_model"] == model
