import pytest

import config
from config import command_line_to_dict


def test_command_line_numeric_values_match_yaml_scalar_types(isolated_config):
    config._COMMAND_LINE = command_line_to_dict(
        ["maxFeedback=25000", "sleepInterval=0.5", "temperature=-1.25e-2"]
    )
    expected = {
        "maxFeedback": 25000,
        "sleepInterval": 0.5,
        "temperature": -0.0125,
    }
    config._CONFIG_FILE = expected.copy()
    for key, value in expected.items():
        actual = config.config_get_by_key(key)
        assert actual == value
        assert type(actual) is type(value)


def test_command_line_strings_and_flag_keep_existing_semantics():
    values = command_line_to_dict(
        ["provider=OpenAI", "IRC_channel=001", "maxFeedback"]
    )

    assert values == {
        "provider": "OpenAI",
        "IRC_channel": "001",
        "maxFeedback": True,
    }


@pytest.fixture
def isolated_config(monkeypatch):
    for name in ("_CONFIG", "_COMMAND_LINE", "_CONFIG_FILE"):
        monkeypatch.setattr(config, name, {})


@pytest.mark.parametrize("default", [50000, 0, 0.5])
def test_bare_numeric_option_rejected_from_default(isolated_config, default):
    config._COMMAND_LINE = command_line_to_dict(["maxFeedback"])
    with pytest.raises(ValueError, match="maxFeedback.*numeric value"):
        config.config_get_by_key("maxFeedback", default)


def test_bare_numeric_option_rejected_from_yaml(isolated_config):
    config._COMMAND_LINE = command_line_to_dict(["maxFeedback"])
    config._CONFIG_FILE = {"maxFeedback": 50000}
    with pytest.raises(ValueError, match="maxFeedback.*numeric value"):
        config.config_get_by_key("maxFeedback")


def test_cached_bare_option_cannot_bypass_numeric_validation(isolated_config):
    config._COMMAND_LINE = command_line_to_dict(["maxFeedback"])
    assert config.config_get_by_key("maxFeedback") is True
    with pytest.raises(ValueError, match="maxFeedback.*numeric value"):
        config.config_get_by_key("maxFeedback", 50000)


@pytest.mark.parametrize("default", [False, True, None])
def test_bare_boolean_flags_remain_supported(isolated_config, default):
    config._COMMAND_LINE = command_line_to_dict(["memoryExportEnabled"])
    config._CONFIG_FILE = {"memoryExportEnabled": False}
    assert config.config_get_by_key("memoryExportEnabled", default) is True


def test_explicit_numeric_override_reaches_config_consumer(isolated_config):
    config._COMMAND_LINE = command_line_to_dict(["maxFeedback=25000"])
    config._CONFIG_FILE = {"maxFeedback": 50000}
    value = config.config_get_by_key("maxFeedback", 50000)
    assert type(value) is int
    assert value + 1 == 25001


@pytest.mark.parametrize("key,value,default", [
    ("IRC_channel", "123", "##omega"),
    ("IRC_channel", "001", "##omega"),
    ("OPENROUTER_SESSION_ID", "123", None),
    ("WS_TOKEN", "1e3", ""),
    ("model", "0.5", "default-model"),
    ("config", "123", "config/config.yaml"),
])
def test_numeric_looking_string_settings_are_preserved(
    isolated_config, key, value, default
):
    config._COMMAND_LINE = command_line_to_dict([f"{key}={value}"])
    actual = config.config_get_by_key(key, default)
    assert actual == value
    assert type(actual) is str


def test_cached_untyped_lookup_does_not_prevent_numeric_conversion(isolated_config):
    config._COMMAND_LINE = command_line_to_dict(["maxFeedback=25000"])
    assert config.config_get_by_key("maxFeedback") == "25000"
    assert config.config_get_by_key("maxFeedback", 50000) == 25000


def test_string_default_takes_precedence_over_numeric_yaml(isolated_config):
    config._COMMAND_LINE = command_line_to_dict(["IRC_channel=123"])
    config._CONFIG_FILE = {"IRC_channel": 456}
    assert config.config_get_by_key("IRC_channel", "##omega") == "123"
