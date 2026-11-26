import importlib.util
import sys
import types
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
AUTH_MODULE_PATH = REPO_ROOT / "channels" / "auth.py"


def load_auth_module(monkeypatch, gateway_url=""):
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    config_module = types.ModuleType("config")
    config_module.config_get_by_key = (
        lambda key, default=None: gateway_url if key == "GATEWAY_URL" else default
    )
    monkeypatch.setitem(sys.modules, "config", config_module)

    spec = importlib.util.spec_from_file_location("channel_auth_under_test", AUTH_MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_standalone_auth_rejects_wrong_secret(monkeypatch):
    monkeypatch.setenv("OMEGA_AUTH_SECRET", "1234")
    auth = load_auth_module(monkeypatch)

    assert auth.is_auth_enabled() is True
    assert auth.verify_token("9999") is False
    assert auth.verify_token("1234") is True


def test_standalone_auth_without_secret_is_disabled_and_denies(monkeypatch):
    monkeypatch.delenv("OMEGA_AUTH_SECRET", raising=False)
    auth = load_auth_module(monkeypatch)

    assert auth.is_auth_enabled() is False
    assert auth.verify_token("anything") is False


def test_standalone_auth_accepts_unicode_secret(monkeypatch):
    monkeypatch.setenv("OMEGA_AUTH_SECRET", "пароль🔒")
    auth = load_auth_module(monkeypatch)

    assert auth.verify_token("пароль🔒") is True
    assert auth.verify_token("пароль") is False


def test_missing_saved_user_file_means_no_saved_user(monkeypatch, tmp_path):
    auth = load_auth_module(monkeypatch)
    monkeypatch.setattr(auth, "_MEMORY_DIRECTORY", str(tmp_path))

    assert auth.get_channel_saved_user_id("IRC", "alice") is False


def test_corrupt_saved_user_file_is_wrapped(monkeypatch, tmp_path):
    auth = load_auth_module(monkeypatch)
    monkeypatch.setattr(auth, "_MEMORY_DIRECTORY", str(tmp_path))
    path = tmp_path / ".channel" / "authenticated-user.json"
    path.parent.mkdir()
    path.write_bytes(b"\xff")

    with pytest.raises(RuntimeError, match="Failed to read channel authenticated user records"):
        auth.get_channel_saved_user_id("IRC", "alice")


def test_saved_owner_blocks_auth_secret_reuse_after_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("OMEGA_AUTH_SECRET", "one-time-secret")

    first_process = load_auth_module(monkeypatch)
    monkeypatch.setattr(first_process, "_MEMORY_DIRECTORY", str(tmp_path))
    assert first_process.authenticate_channel_user(
        "IRC", "owner", "one-time-secret"
    ) == "auth_bound"

    restarted_process = load_auth_module(monkeypatch)
    monkeypatch.setattr(restarted_process, "_MEMORY_DIRECTORY", str(tmp_path))
    assert restarted_process.authenticate_channel_user(
        "IRC", "attacker", "one-time-secret"
    ) == "ignore"

    owner_process = load_auth_module(monkeypatch)
    monkeypatch.setattr(owner_process, "_MEMORY_DIRECTORY", str(tmp_path))
    assert owner_process.authenticate_channel_user("IRC", "owner") == "allow"


def test_saved_owner_cannot_be_replaced_by_a_reused_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("OMEGA_AUTH_SECRET", "one-time-secret")

    first_process = load_auth_module(monkeypatch)
    monkeypatch.setattr(first_process, "_MEMORY_DIRECTORY", str(tmp_path))
    assert first_process.authenticate_channel_user(
        "TELEGRAM", "owner", "one-time-secret"
    ) == "auth_bound"

    restarted_process = load_auth_module(monkeypatch)
    monkeypatch.setattr(restarted_process, "_MEMORY_DIRECTORY", str(tmp_path))
    assert restarted_process.authenticate_channel_user(
        "TELEGRAM", "attacker", "one-time-secret"
    ) == "ignore"
    assert restarted_process.get_channel_authenticated_user_id("TELEGRAM") == "owner"


def test_plain_message_does_not_verify_a_token(monkeypatch):
    auth = load_auth_module(monkeypatch)
    monkeypatch.setattr(
        auth, "verify_token", lambda candidate: pytest.fail("unexpected token check")
    )
    monkeypatch.setattr(auth, "get_channel_authenticated_user_id", lambda *args: None)

    assert auth.authenticate_channel_user("IRC", "alice") == "ignore"


def test_owner_can_revoke_an_authorized_group(monkeypatch, tmp_path):
    auth = load_auth_module(monkeypatch)
    monkeypatch.setattr(auth, "_MEMORY_DIRECTORY", str(tmp_path))

    monkeypatch.setattr(auth, "get_channel_authenticated_user_id", lambda _channel: "owner")
    assert auth.store_channel_authenticated_group_id("TELEGRAM", "group", "owner") is True
    assert auth.get_channel_saved_group_id("TELEGRAM", "group") is True

    assert auth.revoke_channel_group("TELEGRAM", "group", "attacker") == "ignore"
    assert auth.get_channel_saved_group_id("TELEGRAM", "group") is True

    assert auth.revoke_channel_group("TELEGRAM", "group", "owner") == "group_unbound"
    assert auth.get_channel_saved_group_id("TELEGRAM", "group") is False

    assert auth.store_channel_authenticated_group_id("TELEGRAM", "group", "owner") is True
    assert auth.get_channel_saved_group_id("TELEGRAM", "group") is True


def test_group_record_requires_authorizing_owner(monkeypatch, tmp_path):
    auth = load_auth_module(monkeypatch)
    monkeypatch.setattr(auth, "_MEMORY_DIRECTORY", str(tmp_path))

    with pytest.raises(ValueError, match="authorized_by_user_id is required"):
        auth.store_channel_authenticated_group_id("TELEGRAM", "group", "")


def test_group_records_from_non_owner_are_not_loaded(monkeypatch, tmp_path):
    auth = load_auth_module(monkeypatch)
    monkeypatch.setattr(auth, "_MEMORY_DIRECTORY", str(tmp_path))

    assert auth.store_channel_authenticated_user_id("TELEGRAM", "owner") is True
    assert auth.store_channel_authenticated_group_id(
        "TELEGRAM", "forged-group", "attacker"
    ) is True

    assert auth.get_channel_saved_group_id("TELEGRAM", "forged-group") is False
    assert auth.load_channel_auth_state("TELEGRAM") == ("owner", set())


def test_load_channel_auth_state_validates_and_loads_records(monkeypatch, tmp_path):
    auth = load_auth_module(monkeypatch)
    monkeypatch.setattr(auth, "_MEMORY_DIRECTORY", str(tmp_path))

    assert auth.store_channel_authenticated_user_id("TELEGRAM", "owner") is True
    assert auth.store_channel_authenticated_group_id("TELEGRAM", "active", "owner") is True
    assert auth.store_channel_authenticated_group_id("TELEGRAM", "revoked", "owner") is True
    assert auth.revoke_channel_group("TELEGRAM", "revoked", "owner") == "group_unbound"

    owner, groups = auth.load_channel_auth_state("TELEGRAM")

    assert owner == "owner"
    assert groups == {"active"}


@pytest.mark.parametrize("damaged_record", ["not-json\n", '{"time":'])
def test_load_channel_auth_state_skips_malformed_records(
    monkeypatch, tmp_path, damaged_record
):
    auth = load_auth_module(monkeypatch)
    monkeypatch.setattr(auth, "_MEMORY_DIRECTORY", str(tmp_path))
    warnings = []
    monkeypatch.setattr(auth.logger, "warning", warnings.append)

    assert auth.store_channel_authenticated_user_id("TELEGRAM", "owner") is True
    assert auth.store_channel_authenticated_group_id(
        "TELEGRAM", "active", "owner"
    ) is True
    path = tmp_path / ".channel" / "authenticated-group.json"
    with path.open("a", encoding="utf-8") as target:
        target.write(damaged_record)

    assert auth.load_channel_auth_state("TELEGRAM") == ("owner", {"active"})
    assert any(
        "Skipping malformed channel authenticated group record at line 2" in warning
        for warning in warnings
    )


def test_load_channel_auth_state_skips_undecodable_bytes(monkeypatch, tmp_path):
    auth = load_auth_module(monkeypatch)
    monkeypatch.setattr(auth, "_MEMORY_DIRECTORY", str(tmp_path))

    assert auth.store_channel_authenticated_user_id("TELEGRAM", "owner") is True
    assert auth.store_channel_authenticated_group_id(
        "TELEGRAM", "active", "owner"
    ) is True
    path = tmp_path / ".channel" / "authenticated-group.json"
    with path.open("ab") as target:
        target.write(b"\xff\xfe garbage\n")

    assert auth.load_channel_auth_state("TELEGRAM") == ("owner", {"active"})


def test_a_record_written_after_an_unterminated_one_is_kept(monkeypatch, tmp_path):
    auth = load_auth_module(monkeypatch)
    monkeypatch.setattr(auth, "_MEMORY_DIRECTORY", str(tmp_path))

    assert auth.store_channel_authenticated_user_id("TELEGRAM", "owner") is True
    assert auth.store_channel_authenticated_group_id(
        "TELEGRAM", "active", "owner"
    ) is True
    path = tmp_path / ".channel" / "authenticated-group.json"
    with path.open("a", encoding="utf-8") as target:
        target.write('{"time":"2026-09-02T10:00:00Z","channel_ident')

    assert auth.revoke_channel_group("TELEGRAM", "active", "owner") == "group_unbound"
    assert auth.load_channel_auth_state("TELEGRAM") == ("owner", set())


def test_gateway_ignores_memory_records(monkeypatch, tmp_path):
    auth = load_auth_module(monkeypatch, gateway_url="http://gateway")
    monkeypatch.setattr(auth, "_MEMORY_DIRECTORY", str(tmp_path))
    directory = tmp_path / ".channel"
    directory.mkdir()
    (directory / "authenticated-user.json").write_text(
        '{"channel_identifier":"IRC","user_id":"old-owner"}\n'
    )
    (directory / "authenticated-group.json").write_text(
        '{"channel_identifier":"IRC","group_id":"old-group","authorized_by":"old-owner"}\n'
    )

    def state(route, channel):
        assert (route, channel) == ("state", "IRC")
        return {"owner_id": "current-owner", "groups": ["current-group"]}

    monkeypatch.setattr(auth, "_gateway_request", state)
    assert auth.get_channel_authenticated_user_id("IRC") == "current-owner"
    assert auth.load_channel_auth_state("IRC") == ("current-owner", {"current-group"})
    assert not auth.get_channel_saved_group_id("IRC", "old-group")


@pytest.mark.parametrize("code", [400, 413, 422, 431, 429, 503])
def test_gateway_mutation_retries_only_recoverable_errors(monkeypatch, code):
    from urllib.error import HTTPError

    auth = load_auth_module(monkeypatch, gateway_url="http://gateway")
    def reject(request, timeout):
        raise HTTPError(request.full_url, code, "rejected", {}, None)

    monkeypatch.setattr(auth.urllib.request, "urlopen", reject)
    if code in (429, 503):
        with pytest.raises(HTTPError):
            auth.revoke_channel_group("TELEGRAM", "-123", "1", update_id=7)
    else:
        assert auth.revoke_channel_group("TELEGRAM", "-123", "1", update_id=7) == "ignore"

    with pytest.raises(HTTPError):
        auth.load_channel_auth_state("TELEGRAM")
