"""In-process unit tests for src/config.py.

The configuration resolver checks command-line arguments, OMEGACLAW_<key>
environment variables, the YAML configuration file, and finally the supplied
default. Resolved values are cached until configuration is initialized again.

No container, no network, no token — same pattern as
unit/test_fileio_verified_writes.py: the module is loaded by file path.
"""
import importlib.util
import os

import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_CONFIG_PATH = os.path.join(_REPO_ROOT, "src", "config.py")


def _load_config():
    spec = importlib.util.spec_from_file_location("config_under_test", _CONFIG_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def config():
    return _load_config()


def test_config_module_exposes_public_api(config):
    assert hasattr(config, "config_get_by_key")
    assert hasattr(config, "command_line_to_dict")
    assert hasattr(config, "init_config")


def test_command_line_key_value_pairs(config):
    result = config.command_line_to_dict(["provider=OpenRouter", "model=free"])

    assert result == {"provider": "OpenRouter", "model": "free"}


def test_command_line_bare_argument_becomes_true(config):
    assert config.command_line_to_dict(["verbose"]) == {"verbose": True}


def test_command_line_splits_on_first_equals_only(config):
    result = config.command_line_to_dict(["url=http://host/?a=b"])

    assert result == {"url": "http://host/?a=b"}


def test_command_line_empty_value_is_empty_string(config):
    assert config.command_line_to_dict(["key="]) == {"key": ""}


def test_command_line_empty_list(config):
    assert config.command_line_to_dict([]) == {}


def test_default_used_when_nothing_configured(config):
    assert config.config_get_by_key("MISSING", "fallback") == "fallback"


def test_default_is_none_when_unspecified(config):
    assert config.config_get_by_key("MISSING") is None


def test_reads_from_command_line(config):
    config._COMMAND_LINE = {"provider": "OpenRouter"}

    assert config.config_get_by_key("provider", "Anthropic") == "OpenRouter"


def test_reads_from_environment_with_omegaclaw_prefix(config, monkeypatch):
    monkeypatch.setenv("OMEGACLAW_provider", "OpenRouter")

    assert config.config_get_by_key("provider", "Anthropic") == "OpenRouter"


def test_environment_key_without_prefix_is_ignored(config, monkeypatch):
    # Only OMEGACLAW_<key> is consulted, never the bare key.
    monkeypatch.setenv("provider", "OpenRouter")
    monkeypatch.delenv("OMEGACLAW_provider", raising=False)

    assert config.config_get_by_key("provider", "Anthropic") == "Anthropic"


def test_reads_from_config_file(config, monkeypatch):
    monkeypatch.delenv("OMEGACLAW_provider", raising=False)
    config._CONFIG_FILE = {"provider": "OpenRouter"}

    assert config.config_get_by_key("provider", "Anthropic") == "OpenRouter"


def test_init_config_reads_yaml_file(config, monkeypatch, tmp_path):
    # Goes through the real open() and yaml.safe_load(), not an injected dict.
    monkeypatch.delenv("OMEGACLAW_provider", raising=False)
    config_file = tmp_path / "config.yaml"
    config_file.write_text("provider: Anthropic\n", encoding="utf-8")

    config.init_config([f"config={config_file}"])

    assert config.config_get_by_key("provider", "Fallback") == "Anthropic"


def test_command_line_beats_environment_and_file(config, monkeypatch):
    config._COMMAND_LINE = {"provider": "OpenRouter"}
    monkeypatch.setenv("OMEGACLAW_provider", "OpenAI")
    config._CONFIG_FILE = {"provider": "Anthropic"}

    assert config.config_get_by_key("provider") == "OpenRouter"


def test_environment_beats_config_file(config, monkeypatch):
    monkeypatch.setenv("OMEGACLAW_provider", "OpenRouter")
    config._CONFIG_FILE = {"provider": "Anthropic"}

    assert config.config_get_by_key("provider", "DefaultProvider") == "OpenRouter"


def test_config_file_beats_default(config, monkeypatch):
    monkeypatch.delenv("OMEGACLAW_provider", raising=False)
    config._CONFIG_FILE = {"provider": "OpenRouter"}

    assert config.config_get_by_key("provider", "Anthropic") == "OpenRouter"


def test_resolved_value_is_cached(config):
    config._COMMAND_LINE = {"provider": "OpenRouter"}
    first_result = config.config_get_by_key("provider")

    config._COMMAND_LINE["provider"] = "Anthropic"
    second_result = config.config_get_by_key("provider")

    assert first_result == "OpenRouter"
    assert second_result == "OpenRouter"


def test_init_config_resets_old_cache(config, monkeypatch, tmp_path):
    monkeypatch.delenv("OMEGACLAW_model", raising=False)
    config._CONFIG["provider"] = "OldProvider"
    config_file = tmp_path / "config.yaml"
    config_file.write_text("provider: Anthropic\nmodel: free\n", encoding="utf-8")

    config.init_config([f"config={config_file}", "provider=OpenRouter"])

    assert config.config_get_by_key("provider") == "OpenRouter"
    assert config.config_get_by_key("model") == "free"
