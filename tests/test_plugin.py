import importlib
import sys
import textwrap
import types
from pathlib import Path

import pytest

import plugin


REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE_SOURCE = """\
    import sys

    visible_during_execution = sys.modules.get(__name__)
    outbox = []
    initialized = False
    load_count = 0

    def loadOmegaPlugin():
        global initialized, load_count
        initialized = True
        load_count += 1
"""


@pytest.fixture
def plugin_file(tmp_path, monkeypatch):
    monkeypatch.setattr(plugin, "_plugins", {})
    monkeypatch.setattr(sys, "path", sys.path.copy())

    def create(source=PROBE_SOURCE, name="omega_issue_360_probe"):
        path = tmp_path / f"{name}.py"
        path.write_text(textwrap.dedent(source), encoding="utf-8")
        # Track the previous value so imports are undone even if the test fails.
        monkeypatch.setitem(sys.modules, name, None)
        del sys.modules[name]
        return name, str(tmp_path)

    return create


@pytest.fixture(params=["location", "pythonpath"])
def loaded_probe(request, plugin_file, monkeypatch):
    name, location = plugin_file()
    if request.param == "pythonpath":
        monkeypatch.syspath_prepend(location)
        location = None
    plugin.loadPythonPlugin(name, location)
    loaded = plugin._plugins[name].mod
    assert loaded.initialized is True
    return name, loaded


def test_import_returns_loaded_plugin(loaded_probe):
    name, loaded = loaded_probe
    assert importlib.import_module(name) is loaded


def test_import_shares_initialized_state_and_outbox(loaded_probe):
    name, loaded = loaded_probe
    imported = importlib.import_module(name)
    imported.outbox.append("message from helper")
    assert (imported.initialized, loaded.outbox) == (
        True, ["message from helper"],
    )


def test_plugin_is_visible_during_execution(loaded_probe):
    _, loaded = loaded_probe
    assert loaded.visible_during_execution is loaded


def test_self_import_returns_initializing_module(plugin_file):
    name, location = plugin_file("""\
        import importlib
        myself = importlib.import_module(__name__)

        def loadOmegaPlugin():
            pass
    """)
    plugin.loadPythonPlugin(name, location)
    loaded = plugin._plugins[name].mod
    assert loaded.myself is loaded


def test_import_before_plugin_load_reuses_module(plugin_file, monkeypatch):
    name, location = plugin_file()
    monkeypatch.syspath_prepend(location)
    imported = importlib.import_module(name)
    imported.outbox.append("queued before loading")

    plugin.loadPythonPlugin(name, location)

    assert plugin._plugins[name].mod is imported
    assert imported.initialized is True
    assert imported.outbox == ["queued before loading"]


@pytest.mark.parametrize("second_location", ["same", None, ""])
def test_repeated_load_does_not_repeat_entrypoint(plugin_file, second_location):
    name, location = plugin_file()
    plugin.loadPythonPlugin(name, location)
    first = plugin._plugins[name].mod
    first.outbox.append("queued")

    plugin.loadPythonPlugin(name, location if second_location == "same" else second_location)

    assert plugin._plugins[name].mod is first
    assert first.load_count == 1
    assert first.outbox == ["queued"]


@pytest.mark.parametrize("failure", ["RuntimeError", "SystemExit"])
def test_execution_failure_removes_partial_module(plugin_file, failure):
    name, location = plugin_file(f"raise {failure}('execution failed')")
    exception = RuntimeError if failure == "RuntimeError" else SystemExit
    with pytest.raises(exception, match="execution failed"):
        plugin.loadPythonPlugin(name, location)
    assert name not in sys.modules
    assert name not in plugin._plugins

    Path(location, f"{name}.py").write_text(textwrap.dedent(PROBE_SOURCE))
    plugin.loadPythonPlugin(name, location)
    assert importlib.import_module(name) is plugin._plugins[name].mod


@pytest.mark.parametrize("existing_kind", ["other_file", "no_file", "blocked"])
def test_name_collision_does_not_replace_existing_module(plugin_file, existing_kind):
    name, location = plugin_file()
    existing = types.ModuleType(name)
    if existing_kind == "other_file":
        existing.__file__ = str(Path(location, "other.py"))
    elif existing_kind == "blocked":
        existing = None
    sys.modules[name] = existing

    with pytest.raises(RuntimeError, match="already.*module"):
        plugin.loadPythonPlugin(name, location)

    assert sys.modules[name] is existing
    assert name not in plugin._plugins


def test_loaded_plugin_cannot_be_replaced_by_another_location(plugin_file, tmp_path):
    name, location = plugin_file()
    plugin.loadPythonPlugin(name, location)
    first = plugin._plugins[name].mod
    other = tmp_path / "other"
    other.mkdir()
    (other / f"{name}.py").write_text(textwrap.dedent(PROBE_SOURCE))

    with pytest.raises(RuntimeError, match="already.*module"):
        plugin.loadPythonPlugin(name, str(other))

    assert sys.modules[name] is first
    assert plugin._plugins[name].mod is first


def test_failed_entrypoint_is_not_registered_as_loaded(plugin_file):
    name, location = plugin_file("""\
        attempts = 0
        def loadOmegaPlugin():
            global attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("entrypoint failed")
    """)
    with pytest.raises(RuntimeError, match="entrypoint failed"):
        plugin.loadPythonPlugin(name, location)
    assert name not in plugin._plugins

    plugin.loadPythonPlugin(name, location)
    assert plugin._plugins[name].mod.attempts == 2


def test_missing_entrypoint_is_not_registered_as_loaded(plugin_file):
    name, location = plugin_file("value = 1")
    with pytest.raises(RuntimeError, match="No loadOmegaPlugin"):
        plugin.loadPythonPlugin(name, location)
    assert name not in plugin._plugins


def test_shipped_providers_preserve_openai_sdk(plugin_file, monkeypatch):
    import providers

    # The CI host has no provider SDKs; only module identity is under test.
    sdk = types.ModuleType("openai")
    sdk.OpenAI = type("OpenAI", (), {})
    monkeypatch.setitem(sys.modules, "openai", sdk)
    monkeypatch.setattr(providers, "_llmProviderRegistry", {})
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    for name in ("lib_llm_ext", "openaiapi", "asione", "openrouter", "omega_openai", "mockprovider"):
        monkeypatch.setitem(sys.modules, name, None)
        del sys.modules[name]

    entries = [entry for entry in plugin.listPlugins() if entry[2] == str(REPO_ROOT / "providers")]
    for _, name, location in entries:
        plugin.loadPythonPlugin(name, location)
        assert importlib.import_module(name) is plugin._plugins[name].mod

    assert importlib.import_module("openai") is sdk
    assert callable(sdk.OpenAI)
    assert "OpenAI" in providers._llmProviderRegistry
    assert providers._llmProviderRegistry["OpenAI"].__class__.__module__ == "omega_openai"


def test_telegram_import_uses_registered_channels_outbox(plugin_file, monkeypatch):
    import channels

    monkeypatch.setattr(channels, "_commChannelRegistry", {})
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    monkeypatch.setitem(sys.modules, "telegram", None)
    del sys.modules["telegram"]
    auth = types.ModuleType("auth")
    auth.is_auth_enabled = lambda: False
    monkeypatch.setitem(sys.modules, "auth", auth)
    config = types.ModuleType("config")
    config.config_get_by_key = lambda key, default=None: default
    monkeypatch.setitem(sys.modules, "config", config)

    plugin.loadPythonPlugin("telegram", str(REPO_ROOT / "channels"))
    loaded = plugin._plugins["telegram"].mod
    imported = importlib.import_module("telegram")
    sent = []
    monkeypatch.setattr(loaded, "_api_call", lambda method, params, **kwargs: sent.append(params))
    loaded._default_chat_id = "101"

    imported.send_message("from helper", target_chat="101")
    channels._commChannelRegistry["telegram"].send("from registered channel")
    assert sent == []

    loaded._connected = True
    loaded._flush_outbox()

    assert [item["text"] for item in sent] == ["from helper", "from registered channel"]
    assert all(item["chat_id"] == "101" for item in sent)
