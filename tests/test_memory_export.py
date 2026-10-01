import importlib
import importlib.util
import hashlib
import json
import os
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def handler(monkeypatch):
    logger_mod = types.ModuleType("src.logger")
    logger_mod.get_logger = lambda name: __import__("logging").getLogger(name)
    monkeypatch.setitem(sys.modules, "src.logger", logger_mod)

    monkeypatch.delitem(sys.modules, "memory_portability", raising=False)

    spec = importlib.util.spec_from_file_location(
        "memory_export_under_test",
        REPO_ROOT / "src" / "memory_export.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.is_export_enabled = lambda: True
    return module

def test_export_command_requires_policy(handler):
    exported = []
    handler._get_transfer = lambda: types.SimpleNamespace(
        export=lambda component: exported.append(component) or {
            "filename": "memory.tar.gz",
            "size": 1,
            "sha256": "abc",
            "record_count": 1,
        }
    )

    assert "Memory export complete" in handler.handle_export_command(
        "/memory-export both", "authenticated-user"
    )
    assert exported == ["both"]

    handler.is_export_enabled = lambda: False
    assert handler.handle_export_command(
        "/memory-export both", "authenticated-user"
    ) is None
    assert exported == ["both"]


def test_export_requires_authenticated_user(handler):
    handler._get_transfer = lambda: pytest.fail(
        "an unauthenticated command must not start an export"
    )

    assert handler.handle_export_command("/memory-export both") == (
        "Memory export denied: an authenticated user is required."
    )

def test_module_import_does_not_require_memory_portability(handler):
    assert "memory_portability" not in sys.modules
    assert handler.is_export_command("/memory-export both")


def test_entrypoint_configures_memory_transfer_directory():
    entrypoint = (REPO_ROOT / "entrypoint.sh").read_text(encoding="utf-8")

    assert 'transfer_dir="/memory-transfer"' in entrypoint

@pytest.mark.parametrize("component", ["history", "ltm", "both"])
def test_export_runs_immediately(handler, component):
    exported = []
    handler._get_transfer = lambda: types.SimpleNamespace(
        export=lambda component: exported.append(component) or {
            "filename": "memory.tar.gz",
            "size": 1,
            "sha256": "abc",
            "record_count": 1,
        }
    )
    reply = handler.handle_export_command(
        f"/memory-export {component}", "authenticated-user"
    )
    assert exported == [component]
    assert "memory.tar.gz" in reply
    assert "SHA-256:  abc" in reply


def test_confirmation_command_is_no_longer_supported(handler):
    handler._get_transfer = lambda: pytest.fail(
        "the removed confirmation command must not start an export"
    )

    reply = handler.handle_export_command(
        "/memory-export confirm old-token", "authenticated-user"
    )

    assert reply == (
        "Unknown /memory-export command. "
        "Use: /memory-export history|ltm|both"
    )

def test_transfer_uses_effective_runtime_embedding_provider(handler, monkeypatch):
    created = []

    class FakeTransfer:
        def __init__(self, **kwargs):
            created.append({
                **kwargs,
                "embedding_provider": os.environ["EMBEDDING_PROVIDER"],
            })

    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    package = types.ModuleType("memory_portability")
    package.MemoryTransfer = FakeTransfer
    monkeypatch.setitem(sys.modules, "memory_portability", package)
    monkeypatch.setattr(handler, "create_memory_store", lambda: "configured-store")
    monkeypatch.setattr(
        handler,
        "config_get_by_key",
        lambda key, default=None: "OpenAI" if key == "embeddingprovider" else default,
    )
    handler._transfer = None

    transfer = handler._get_transfer()

    assert transfer is handler._transfer
    assert created == [{
        "transfer_dir": handler._TRANSFER_DIR,
        "store": "configured-store",
        "embedding_provider": "OpenAI",
    }]


def test_transfer_exposes_runtime_omega_version(handler, monkeypatch):
    created = []

    class FakeTransfer:
        def __init__(self, **kwargs):
            created.append({
                **kwargs,
                "omega_version": os.environ.get("OMEGA_VERSION"),
            })

    monkeypatch.delenv("OMEGA_VERSION", raising=False)
    package = types.ModuleType("memory_portability")
    package.MemoryTransfer = FakeTransfer
    monkeypatch.setitem(sys.modules, "memory_portability", package)
    monkeypatch.setattr(handler, "create_memory_store", lambda: "configured-store")
    monkeypatch.setattr(handler, "omega_version", lambda: "v1.2.3")
    handler._transfer = None

    transfer = handler._get_transfer()

    assert transfer is handler._transfer
    assert created == [{
        "transfer_dir": handler._TRANSFER_DIR,
        "store": "configured-store",
        "omega_version": "v1.2.3",
    }]


def test_memory_store_receives_explicit_omega_storage_configuration(
    handler,
    monkeypatch,
    tmp_path,
):
    created_stores = []

    class FakeStore:
        def __init__(self, **kwargs):
            created_stores.append(kwargs)

    package = types.ModuleType("memory_portability")
    package.__path__ = []
    storage = types.ModuleType("memory_portability.storage")
    storage.MemoryStore = FakeStore
    monkeypatch.setitem(sys.modules, "memory_portability", package)
    monkeypatch.setitem(sys.modules, "memory_portability.storage", storage)

    memory_dir = tmp_path / "custom-memory"
    chroma_path = tmp_path / "custom-chroma"
    monkeypatch.setattr(handler, "_resolve_memory_dir", lambda: memory_dir)
    monkeypatch.setattr(handler, "_resolve_chroma_path", lambda: chroma_path)
    monkeypatch.setattr(
        handler,
        "config_get_by_key",
        lambda key, default=None: "Local" if key == "embeddingprovider" else default,
    )

    store = handler.create_memory_store()

    assert isinstance(store, FakeStore)
    assert created_stores == [
        {
            "memory_dir": memory_dir,
            "chroma_path": chroma_path,
            "collection_name": "memories",
        }
    ]


def install_fake_memory_store(monkeypatch, tmp_path):
    created_stores = []

    class FakeStore:
        def __init__(self, **kwargs):
            created_stores.append(kwargs)

    package = types.ModuleType("memory_portability")
    package.__path__ = []
    storage = types.ModuleType("memory_portability.storage")
    storage.MemoryStore = FakeStore
    monkeypatch.setitem(sys.modules, "memory_portability", package)
    monkeypatch.setitem(sys.modules, "memory_portability.storage", storage)
    return created_stores


def install_fake_import_kb(monkeypatch):
    calls = []
    package = types.ModuleType("import_knowledge")
    package.__path__ = []
    module = types.ModuleType("import_knowledge.import_knowledge")
    module.init_embeddings = lambda mode, model_name=None: calls.append(
        ("init", mode, model_name)
    )
    module.embed_batch = lambda texts: calls.append(("embed", list(texts))) or [
        [0.5] * 3 for _ in texts
    ]
    monkeypatch.setitem(sys.modules, "import_knowledge", package)
    monkeypatch.setitem(sys.modules, "import_knowledge.import_knowledge", module)
    return calls


def configure(monkeypatch, handler, tmp_path, provider, config_model="",
              env_provider="Local", env_model="env-only-model"):
    monkeypatch.setenv("EMBEDDING_PROVIDER", env_provider)
    monkeypatch.setenv("EMBEDDING_MODEL", env_model)
    settings = {"embeddingprovider": provider, "embeddingModel": config_model}
    monkeypatch.setattr(
        handler,
        "config_get_by_key",
        lambda key, default=None: settings.get(key, default),
    )
    monkeypatch.setattr(handler, "_resolve_memory_dir", lambda: tmp_path / "memory")
    monkeypatch.setattr(handler, "_resolve_chroma_path", lambda: tmp_path / "chroma")


def test_asicloud_memory_store_embeds_with_asicloud_default_model(
    handler,
    monkeypatch,
    tmp_path,
):
    stores = install_fake_memory_store(monkeypatch, tmp_path)
    calls = install_fake_import_kb(monkeypatch)
    configure(monkeypatch, handler, tmp_path, "ASICloud")

    handler.create_memory_store()

    assert stores[0]["embedding_profile"] == {
        "provider": "ASICloud",
        "model": "WhereIsAI/UAE-Large-V1",
        "vector_dimension": 1024,
    }
    assert stores[0]["embed_batch"](["imported fact"]) == [[0.5, 0.5, 0.5]]
    assert calls == [
        ("init", "asicloud", "WhereIsAI/UAE-Large-V1"),
        ("embed", ["imported fact"]),
    ]


def test_memory_store_uses_the_configured_model(
    handler,
    monkeypatch,
    tmp_path,
):
    stores = install_fake_memory_store(monkeypatch, tmp_path)
    calls = install_fake_import_kb(monkeypatch)
    configure(
        monkeypatch, handler, tmp_path, "ASICloud", config_model="BAAI/bge-base-en-v1.5"
    )

    handler.create_memory_store()
    stores[0]["embed_batch"](["imported fact"])

    assert stores[0]["embedding_profile"] == {
        "provider": "ASICloud",
        "model": "BAAI/bge-base-en-v1.5",
        "vector_dimension": None,
    }
    assert calls[0] == ("init", "asicloud", "BAAI/bge-base-en-v1.5")


def test_memory_store_uses_the_runtime_model_inside_the_agent(
    handler,
    monkeypatch,
    tmp_path,
):
    stores = install_fake_memory_store(monkeypatch, tmp_path)
    install_fake_import_kb(monkeypatch)
    configure(
        monkeypatch,
        handler,
        tmp_path,
        "OpenAI",
        config_model="text-embedding-3-small",
    )

    handler.create_memory_store()

    assert stores[0]["embedding_profile"]["provider"] == "OpenAI"
    assert stores[0]["embedding_profile"]["model"] == "text-embedding-3-small"


def test_memory_store_ignores_embedding_environment_variables(
    handler,
    monkeypatch,
    tmp_path,
):
    stores = install_fake_memory_store(monkeypatch, tmp_path)
    install_fake_import_kb(monkeypatch)
    configure(monkeypatch, handler, tmp_path, "Local", env_provider="ASICloud")

    handler.create_memory_store()

    assert stores == [
        {
            "memory_dir": tmp_path / "memory",
            "chroma_path": tmp_path / "chroma",
            "collection_name": "memories",
        }
    ]


def test_entrypoint_passes_container_arguments_to_memory_portability():
    entrypoint = (REPO_ROOT / "entrypoint.sh").read_text(encoding="utf-8")

    assert "init_config(sys.argv[1:])" in entrypoint
    assert "init_config([])" not in entrypoint
    assert entrypoint.count(
        """su nobody -s /bin/sh -c 'exec python3 -c "$MEMORY_PORTABILITY_PYTHON" "$@"' sh "$@\""""
    ) == 2


def test_export_is_allowed_for_asicloud_embeddings(handler, monkeypatch):
    created = []
    package = types.ModuleType("memory_portability")
    package.MemoryTransfer = lambda **kwargs: created.append(kwargs) or "transfer"
    monkeypatch.setitem(sys.modules, "memory_portability", package)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "Local")
    monkeypatch.setenv("OMEGA_VERSION", "unset")
    monkeypatch.setattr(handler, "omega_version", lambda: "test")
    monkeypatch.setattr(handler, "create_memory_store", lambda: "configured-store")
    monkeypatch.setattr(
        handler,
        "config_get_by_key",
        lambda key, default=None: "ASICloud" if key == "embeddingprovider" else default,
    )
    handler._transfer = None

    assert handler._get_transfer() == "transfer"
    assert os.environ["EMBEDDING_PROVIDER"] == "ASICloud"


def test_export_rejects_providers_without_embeddings(handler, monkeypatch):
    package = types.ModuleType("memory_portability")
    package.MemoryTransfer = lambda **kwargs: pytest.fail("transfer must not start")
    monkeypatch.setitem(sys.modules, "memory_portability", package)
    monkeypatch.setattr(
        handler,
        "config_get_by_key",
        lambda key, default=None: "Anthropic" if key == "embeddingprovider" else default,
    )
    handler._transfer = None

    with pytest.raises(ValueError, match="Anthropic"):
        handler._get_transfer()


def test_storage_paths_are_resolved_from_omega_config(
    handler,
    monkeypatch,
    tmp_path,
):
    configured = {
        "memoryDirectory": str(tmp_path / "configured-memory"),
        "chromaDbPath": str(tmp_path / "configured-chroma"),
    }
    monkeypatch.delenv("CHROMA_DB_PATH", raising=False)
    monkeypatch.setattr(
        handler,
        "config_get_by_key",
        lambda key, default=None: configured.get(key, default),
    )

    assert handler._resolve_memory_dir() == tmp_path / "configured-memory"
    assert handler._resolve_chroma_path() == tmp_path / "configured-chroma"


def test_websocket_defers_memory_export_to_core_dispatch(monkeypatch):
    config = types.ModuleType("config")
    config.config_get_by_key = lambda key, default=None: default
    logger_mod = types.ModuleType("src.logger")
    logger_mod.get_logger = lambda name: __import__("logging").getLogger(name)
    channels = types.ModuleType("channels")
    channels.CommChannel = object
    channels.registerCommChannel = lambda *args: None
    monkeypatch.setitem(sys.modules, "config", config)
    monkeypatch.setitem(sys.modules, "src.logger", logger_mod)
    monkeypatch.setitem(sys.modules, "channels", channels)

    spec = importlib.util.spec_from_file_location(
        "wschat_under_test", REPO_ROOT / "channels" / "wschat.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    received = []
    replies = []
    module._enqueue_user_message = lambda *args: received.append(args)
    module.send_message = replies.append

    module._handle_frame(json.dumps({
        "type": "user_message", "seq": 1, "text": "/memory-export both"
    }))
    assert received == [(1, "/memory-export both")]
    assert replies == []


def test_commchannel_receive_dispatches_control_commands(monkeypatch):
    authenticated_user_id = "telegram-user-123"
    auth = types.ModuleType("auth")
    auth.is_auth_enabled = lambda: True
    auth.get_channel_authenticated_user_id = lambda channel: (
        authenticated_user_id if channel == "TELEGRAM" else None
    )
    monkeypatch.setitem(sys.modules, "auth", auth)

    principals: list[str] = []
    control = types.ModuleType("src.memory_export")
    control.is_export_command = lambda text: text == "/memory-export both"
    control.handle_export_command = lambda text, principal: (
        principals.append(principal) or "Memory export complete"
    )
    monkeypatch.setitem(sys.modules, "src.memory_export", control)

    monkeypatch.delitem(sys.modules, "channels", raising=False)
    channels = importlib.import_module("channels")

    replies: list[str] = []
    channels._commchannel = types.SimpleNamespace(
        receive=lambda: "alice: /memory-export both | alice: hello",
        send=replies.append,
    )
    channels._commchannel_id = "telegram"

    assert channels.commChannelReceive() == "alice: hello"
    assert principals == [authenticated_user_id]
    assert replies == ["Memory export complete"]


def test_commchannel_receive_denies_export_without_authenticated_user(monkeypatch):
    auth = types.ModuleType("auth")
    auth.is_auth_enabled = lambda: False
    auth.get_channel_authenticated_user_id = lambda *_: pytest.fail(
        "disabled authentication must not resolve a user ID"
    )
    monkeypatch.setitem(sys.modules, "auth", auth)

    control = types.ModuleType("src.memory_export")
    control.is_export_command = lambda text: text == "/memory-export both"
    control.handle_export_command = lambda text, principal: (
        "Memory export denied: an authenticated user is required."
        if principal is None
        else pytest.fail("an unauthenticated command received a principal")
    )
    monkeypatch.setitem(sys.modules, "src.memory_export", control)

    monkeypatch.delitem(sys.modules, "channels", raising=False)
    channels = importlib.import_module("channels")

    replies: list[str] = []
    channels._commchannel = types.SimpleNamespace(
        receive=lambda: "alice: /memory-export both",
        send=replies.append,
    )
    channels._commchannel_id = "telegram"

    assert channels.commChannelReceive() == ""
    assert replies == ["Memory export denied: an authenticated user is required."]


def test_commchannel_receive_dispatches_websocket_export(monkeypatch):
    websocket_token = "private-websocket-token"
    config = types.ModuleType("config")
    config.config_get_by_key = lambda key, default=None: (
        websocket_token if key == "WS_TOKEN" else default
    )
    monkeypatch.setitem(sys.modules, "config", config)

    commands: list[str] = []
    principals: list[str] = []
    control = types.ModuleType("src.memory_export")
    control.is_export_command = lambda text: text == "/memory-export both"
    control.handle_export_command = lambda text, principal: (
        commands.append(text)
        or principals.append(principal)
        or "Memory export complete"
    )
    monkeypatch.setitem(sys.modules, "src.memory_export", control)

    monkeypatch.delitem(sys.modules, "channels", raising=False)
    channels = importlib.import_module("channels")

    replies: list[str] = []
    channels._commchannel = types.SimpleNamespace(
        receive=lambda: "/memory-export both",
        send=replies.append,
    )
    channels._commchannel_id = "websocket"

    assert channels.commChannelReceive() == ""
    assert commands == ["/memory-export both"]
    assert principals == [
        f"websocket:{hashlib.sha256(websocket_token.encode('utf-8')).hexdigest()}"
    ]
    assert websocket_token not in principals[0]
    assert replies == ["Memory export complete"]


def test_websocket_export_requires_bearer_token(monkeypatch):
    config = types.ModuleType("config")
    config.config_get_by_key = lambda key, default=None: default
    monkeypatch.setitem(sys.modules, "config", config)

    monkeypatch.delitem(sys.modules, "channels", raising=False)
    channels = importlib.import_module("channels")
    channels._commchannel_id = "websocket"

    assert channels._authenticated_export_principal() is None


def test_commchannel_receive_does_not_consume_command_mentions(monkeypatch):
    control = types.ModuleType("src.memory_export")
    control.is_export_command = lambda text: text == "/memory-export both"
    control.handle_export_command = lambda *_: pytest.fail(
        "a command mentioned in normal text must not execute"
    )
    monkeypatch.setitem(sys.modules, "src.memory_export", control)

    monkeypatch.delitem(sys.modules, "channels", raising=False)
    channels = importlib.import_module("channels")

    message = "alice: please use /memory-export both"
    channels._commchannel = types.SimpleNamespace(
        receive=lambda: message,
        send=lambda *_: pytest.fail("normal messages must not generate replies"),
    )
    channels._commchannel_id = "telegram"

    assert channels.commChannelReceive() == message
