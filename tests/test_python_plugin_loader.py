"""Regression tests for Python plugin module identity and import caching."""

import importlib
import sys

import pytest

import plugin


PLUGIN_SOURCE = """\
outbox = []
load_count = 0

def loadOmegaPlugin():
    global load_count
    load_count += 1
"""


@pytest.fixture
def plugin_file(tmp_path, monkeypatch):
    """Isolate the plugin registry, import path, and test module cache."""
    name = "omega_test_location_plugin"
    monkeypatch.setattr(plugin, "_plugins", {})
    monkeypatch.setattr(sys, "path", sys.path.copy())
    monkeypatch.delitem(sys.modules, name, raising=False)
    path = tmp_path / f"{name}.py"
    path.write_text(PLUGIN_SOURCE, encoding="utf-8")
    yield name, path
    sys.modules.pop(name, None)


def test_imports_share_the_plugin_module_and_state(plugin_file):
    name, path = plugin_file
    path.write_text(
        "import importlib\n"
        "self_reference = importlib.import_module(__name__)\n"
        + PLUGIN_SOURCE,
        encoding="utf-8",
    )
    plugin.loadPythonPlugin(name, str(path.parent))
    loaded = plugin._plugins[name].mod

    imported = importlib.import_module(name)
    imported.outbox.append("message from another module")

    assert imported is loaded
    assert loaded.self_reference is loaded
    assert imported.load_count == 1
    assert loaded.outbox == ["message from another module"]


def test_cached_plugin_keeps_identity_and_state(plugin_file, monkeypatch):
    name, path = plugin_file
    monkeypatch.syspath_prepend(str(path.parent))
    imported = importlib.import_module(name)
    imported.outbox.append("queued before plugin initialization")

    for load_count in (1, 2):
        plugin.loadPythonPlugin(name, str(path.parent))
        assert plugin._plugins[name].mod is imported
        assert imported.load_count == load_count
        assert imported.outbox == ["queued before plugin initialization"]


@pytest.mark.parametrize("preimported", [False, True])
def test_location_plugin_preserves_an_importable_same_named_package(
    plugin_file, monkeypatch, preimported
):
    name, path = plugin_file
    installed = path.parent / "installed"
    installed.mkdir()
    (installed / f"{name}.py").write_text(
        "client = object()\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(installed))
    existing = importlib.import_module(name) if preimported else None
    path.write_text(
        "import importlib\n"
        "dependency = importlib.import_module(__name__)\n"
        + PLUGIN_SOURCE,
        encoding="utf-8",
    )

    plugin.loadPythonPlugin(name, str(path.parent))
    loaded = plugin._plugins[name].mod
    dependency = importlib.import_module(name)

    assert loaded.load_count == 1
    assert loaded is not dependency
    assert loaded.dependency is dependency
    assert dependency.client is not None
    if preimported:
        assert dependency is existing


def test_failed_execution_clears_cache_and_allows_retry(plugin_file):
    name, path = plugin_file
    path.write_text(
        "raise RuntimeError('plugin import failed')\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="plugin import failed"):
        plugin.loadPythonPlugin(name, str(path.parent))

    assert name not in sys.modules
    assert name not in plugin._plugins

    path.write_text(PLUGIN_SOURCE, encoding="utf-8")
    plugin.loadPythonPlugin(name, str(path.parent))

    assert importlib.import_module(name) is plugin._plugins[name].mod
    assert plugin._plugins[name].mod.load_count == 1
