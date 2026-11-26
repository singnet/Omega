import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
CHANNELS_DIRECTORY = REPO_ROOT / "channels"


def load_telegram(monkeypatch, auth_enabled=True):
    state = {"owner": None, "groups": set()}
    auth = types.ModuleType("auth")
    auth.is_auth_enabled = lambda: auth_enabled
    auth.get_proxy_url = lambda: ""
    auth.load_channel_auth_state = lambda _channel: (
        state["owner"],
        {group for channel, group in state["groups"] if channel == "TELEGRAM"},
    )
    auth.get_channel_authenticated_user_id = lambda channel: state["owner"]
    auth.get_channel_saved_group_id = lambda channel, group: (
        channel, str(group)
    ) in state["groups"]

    def authenticate_channel_user(channel, user, candidate=None):
        if candidate != "secret" or state["owner"] is not None:
            return "ignore"
        state["owner"] = str(user)
        return "auth_bound"

    def authorize_channel_group(channel, group, requester, update_id=None):
        if str(requester) != state["owner"]:
            return "ignore"
        state["groups"].add((channel, str(group)))
        return "group_bound"

    def revoke_channel_group(channel, group, requester, update_id=None):
        key = (channel, str(group))
        if str(requester) != state["owner"] or key not in state["groups"]:
            return "ignore"
        state["groups"].remove(key)
        return "group_unbound"

    auth.authenticate_channel_user = authenticate_channel_user
    auth.authorize_channel_group = authorize_channel_group
    auth.revoke_channel_group = revoke_channel_group
    monkeypatch.setitem(sys.modules, "auth", auth)

    config = types.ModuleType("config")
    config.config_get_by_key = lambda _key, default=None: default
    monkeypatch.setitem(sys.modules, "config", config)
    channels = types.ModuleType("channels")
    channels.CommChannel = type("CommChannel", (), {"__init__": lambda self: None})
    channels.registerCommChannel = lambda *_args: None
    monkeypatch.setitem(sys.modules, "channels", channels)
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    monkeypatch.syspath_prepend(str(CHANNELS_DIRECTORY))

    path = CHANNELS_DIRECTORY / "telegram.py"
    spec = importlib.util.spec_from_file_location("telegram_multichat_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exposes_omega_plugin_entrypoint(monkeypatch):
    telegram = load_telegram(monkeypatch)

    assert callable(telegram.loadOmegaPlugin)


def test_reply_uses_the_chat_that_supplied_the_message(monkeypatch):
    telegram = load_telegram(monkeypatch, auth_enabled=False)
    telegram._connected = True
    telegram._admin_allowed_chats = {"101", "-202"}
    sent = []
    telegram._api_call = lambda method, params, **_kwargs: sent.append((method, params))

    telegram._enqueue_message("dm message", "101", 11)
    telegram._enqueue_message("group message", "-202", 12)
    assert telegram.getLastMessage() == "[101] [11] dm message"
    telegram.send_message("[101] [11] dm reply")
    assert telegram.getLastMessage() == "[-202] [12] group message"
    telegram.send_message("[-202] [12] group reply")

    assert [params["chat_id"] for _, params in sent] == ["101", "-202"]
    assert [
        json.loads(params["reply_parameters"])["message_id"]
        for _, params in sent
    ] == [11, 12]


def test_identical_messages_from_different_chats_are_processed(monkeypatch):
    telegram = load_telegram(monkeypatch, auth_enabled=False)
    telegram._connected = True
    telegram._enqueue_message("same message", "101", 21)
    telegram._enqueue_message("same message", "-202", 22)

    assert telegram.getLastMessage() == "[101] [21] same message"
    assert telegram.getLastMessage() == "[-202] [22] same message"
    assert telegram.getLastMessage() == ""


def test_failed_delivery_retains_the_original_chat(monkeypatch):
    telegram = load_telegram(monkeypatch, auth_enabled=False)
    telegram._connected = True
    telegram._admin_allowed_chats = {"101", "-202"}
    attempts = []

    def flaky_api(method, params, **_kwargs):
        attempts.append((method, params.copy()))
        if len(attempts) == 1:
            raise RuntimeError("temporary failure")

    telegram._api_call = flaky_api
    telegram._enqueue_message("dm message", "101", 31)
    assert telegram.getLastMessage() == "[101] [31] dm message"

    telegram.send_message("[101] [31] dm reply")
    telegram._enqueue_message("group message", "-202", 32)
    # A failed outbound delivery does not block the inbound queue.
    assert telegram.getLastMessage() == "[-202] [32] group message"

    telegram._flush_outbox()
    assert [params["chat_id"] for _, params in attempts] == ["101", "101"]


def test_proactive_message_uses_authenticated_owner_dm(monkeypatch):
    telegram = load_telegram(monkeypatch)
    telegram._connected = True
    telegram._owner_id = "101"
    telegram._default_chat_id = "101"
    sent = []
    telegram._api_call = lambda method, params, **_kwargs: sent.append((method, params))

    telegram.send_message("startup message")

    assert sent[0][1]["chat_id"] == "101"
    assert "reply_parameters" not in sent[0][1]


def test_proactive_message_before_auth_is_sent_after_owner_binding(monkeypatch):
    telegram = load_telegram(monkeypatch)
    telegram._connected = True
    sent = []
    telegram._api_call = lambda method, params, **_kwargs: sent.append((method, params))

    assert telegram.send_message("OmegaClaw version=test") is True
    assert sent == []

    telegram._process_update(
        {
            "message": {
                "message_id": 42,
                "text": "auth secret",
                "chat": {"id": 101, "type": "private"},
                "from": {"id": 101, "username": "owner"},
            }
        }
    )

    assert [params["text"] for _, params in sent] == [
        "Authentication successful. @owner is now the bot owner. "
        "Send /bind in a group to open it to everyone there.",
        "OmegaClaw version=test",
    ]
    assert all(params["chat_id"] == "101" for _, params in sent)
    assert json.loads(sent[0][1]["reply_parameters"]) == {
        "message_id": 42,
        "allow_sending_without_reply": True,
    }
    assert "reply_parameters" not in sent[1][1]

def test_missing_route_fields_fall_back_to_owner_without_reply(monkeypatch):
    telegram = load_telegram(monkeypatch)
    telegram._connected = True
    telegram._owner_id = "101"
    telegram._default_chat_id = "101"
    sent = []
    telegram._api_call = lambda method, params, **_kwargs: sent.append((method, params))

    assert telegram.send_message("[] [] proactive message") is True

    assert sent[0][1] == {"chat_id": "101", "text": "proactive message"}


def test_generated_target_must_be_owner_or_authorized_group(monkeypatch):
    telegram = load_telegram(monkeypatch)
    telegram._connected = True
    telegram._owner_id = "101"
    telegram._default_chat_id = "101"
    telegram._authorized_groups = {"-202"}
    sent = []
    telegram._api_call = lambda method, params, **_kwargs: sent.append((method, params))

    assert telegram.send_message("[-202] [] allowed") is True
    assert telegram.send_message("[-999] [] rejected") is False

    assert [params["chat_id"] for _, params in sent] == ["-202"]


def test_cached_authorization_avoids_disk_reads_per_message(monkeypatch):
    telegram = load_telegram(monkeypatch)
    telegram._owner_id = "owner"
    telegram._authorized_groups = {"group"}
    telegram.auth.get_channel_authenticated_user_id = lambda *_args: (_ for _ in ()).throw(
        AssertionError("unexpected owner file read")
    )
    telegram.auth.get_channel_saved_group_id = lambda *_args: (_ for _ in ()).throw(
        AssertionError("unexpected group file read")
    )

    assert telegram._is_allowed_message("owner-dm", "owner", "private", "hello") == "allow"
    assert telegram._is_allowed_message("group", "member", "group", "hello") == "allow"


def test_get_me_failure_does_not_abort_initialization(monkeypatch):
    telegram = load_telegram(monkeypatch, auth_enabled=False)
    telegram._bot_username = "stale-name"
    telegram._api_call = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("temporary Telegram failure")
    )

    assert telegram._initialize_bot_identity() is False
    assert telegram._bot_username == ""


def test_invalid_auth_state_stops_startup_before_telegram_is_polled(monkeypatch):
    telegram = load_telegram(monkeypatch)
    monkeypatch.setenv("TG_BOT_TOKEN", "token")
    telegram.auth.load_channel_auth_state = lambda _channel: (_ for _ in ()).throw(
        RuntimeError("malformed authorization state")
    )
    telegram._api_call = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("Telegram API called before authorization validation")
    )

    with pytest.raises(RuntimeError, match="malformed authorization state"):
        telegram.start_telegram()


def test_startup_restores_owner_default_and_bound_groups(monkeypatch):
    telegram = load_telegram(monkeypatch)
    monkeypatch.setenv("TG_BOT_TOKEN", "token")
    telegram.auth.load_channel_auth_state = lambda _channel: ("101", {"-202"})
    telegram._initialize_bot_identity = lambda: True

    class FakeThread:
        def start(self):
            return None

    telegram.threading.Thread = lambda **_kwargs: FakeThread()

    telegram.start_telegram(allowed_chat_ids="-303")

    assert telegram._default_chat_id == "101"
    assert telegram._authorized_groups == {"-202"}
    assert telegram._admin_allowed_chats == {"-202", "-303"}


def test_offset_advances_only_after_update_processing(monkeypatch):
    telegram = load_telegram(monkeypatch, auth_enabled=False)
    update = {
        "update_id": 7,
        "message": {
            "message_id": 41,
            "text": "hello",
            "chat": {"id": 101, "type": "private"},
            "from": {"id": "user", "username": "alice"},
        },
    }
    telegram._running = True
    telegram._offset = None
    telegram._flush_outbox = lambda: None

    def get_updates(*_args, **_kwargs):
        telegram._running = False
        return [update]

    telegram._api_call = get_updates
    telegram._poll_loop()

    assert telegram._offset == 8
    assert telegram.getLastMessage() == "[101] [41] @alice: hello"


def test_failed_update_processing_retains_offset(monkeypatch):
    telegram = load_telegram(monkeypatch, auth_enabled=False)
    telegram._running = True
    telegram._offset = None
    telegram._flush_outbox = lambda: None
    telegram.time.sleep = lambda _seconds: None

    def get_updates(*_args, **_kwargs):
        telegram._running = False
        return [{"update_id": 7, "message": {"text": "hello"}}]

    telegram._api_call = get_updates
    telegram._process_update = lambda _update: (_ for _ in ()).throw(
        RuntimeError("authorization state failure")
    )
    telegram._poll_loop()

    assert telegram._offset is None


def test_owner_binds_group_without_exposing_secret(monkeypatch):
    telegram = load_telegram(monkeypatch)
    telegram._bot_username = "examplebot"

    # A secret sent in a group cannot establish an owner.
    assert telegram._is_allowed_message("group", "1", "group", "auth secret") == "ignore"
    # The owner authenticates once in a private DM.
    assert telegram._is_allowed_message("dm", "1", "private", "auth secret") == "auth_bound"
    assert telegram._default_chat_id == "dm"
    assert telegram._is_allowed_message("dm", "2", "private", "hello") == "ignore"
    # Only that owner can open the group; then every group member is allowed.
    assert telegram._is_allowed_message("group", "2", "group", "/bind") == "ignore"
    assert telegram._is_allowed_message("group", "1", "group", "/bind@ExampleBot") == "group_bound"
    assert "group" in telegram._authorized_groups
    assert "group" in telegram._admin_allowed_chats
    assert telegram._is_allowed_message("group", "2", "group", "hello") == "allow"
    assert telegram._is_allowed_message("other-group", "2", "group", "hello") == "ignore"


def test_bind_command_targets_this_bot_only(monkeypatch):
    telegram = load_telegram(monkeypatch)
    telegram._bot_username = "examplebot"

    assert telegram._is_bind_command("/bind")
    assert telegram._is_bind_command("/authorize_group")

    assert telegram._is_bind_command("/bind@ExampleBot")
    assert telegram._is_bind_command("/BIND@examplebot")
    assert telegram._is_bind_command("/authorize_group@ExampleBot")

    assert not telegram._is_bind_command("/bind@AnotherBot")
    assert not telegram._is_bind_command("/authorize_group@AnotherBot")
    assert not telegram._is_bind_command("/binder@ExampleBot")

    assert telegram._is_unbind_command("/unbind")
    assert telegram._is_unbind_command("/UNBIND@examplebot")
    assert not telegram._is_unbind_command("/unbind@AnotherBot")


def test_only_owner_can_unbind_group(monkeypatch):
    telegram = load_telegram(monkeypatch)
    telegram._bot_username = "examplebot"

    assert telegram._is_allowed_message("dm", "1", "private", "auth secret") == "auth_bound"
    assert telegram._is_allowed_message("group", "1", "group", "/bind") == "group_bound"
    assert telegram._is_allowed_message("group", "2", "group", "/unbind") == "ignore"
    assert telegram._is_allowed_message("group", "2", "group", "hello") == "allow"
    assert telegram._is_allowed_message("group", "1", "group", "/unbind@ExampleBot") == "group_unbound"
    assert "group" not in telegram._authorized_groups
    assert "group" not in telegram._admin_allowed_chats
    assert telegram._is_allowed_message("group", "2", "group", "hello") == "ignore"


def test_owner_can_unbind_group_from_dm(monkeypatch):
    telegram = load_telegram(monkeypatch)

    assert telegram._is_allowed_message("dm", "1", "private", "auth secret") == "auth_bound"
    assert telegram._is_allowed_message("-202", "1", "group", "/bind") == "group_bound"
    assert telegram._is_allowed_message("dm", "1", "private", "/unbind -202") == "group_unbound"
    assert "-202" not in telegram._authorized_groups
    assert "-202" not in telegram._admin_allowed_chats
    assert telegram._is_allowed_message("-202", "2", "group", "hello") == "ignore"


def test_configured_chats_are_a_hard_boundary_when_auth_is_disabled(monkeypatch):
    telegram = load_telegram(monkeypatch, auth_enabled=False)
    telegram._admin_allowed_chats = telegram._parse_admin_allowed_chats(
        "legacy-chat", "group-a, group-b"
    )

    assert telegram._is_allowed_message("legacy-chat", "1", "private", "hello") == "allow"
    assert telegram._is_allowed_message("group-a", "2", "group", "hello") == "allow"
    assert telegram._is_allowed_message("unlisted", "3", "group", "hello") == "ignore"


def test_allowlist_still_permits_owner_dm_bootstrap(monkeypatch):
    telegram = load_telegram(monkeypatch)
    telegram._admin_allowed_chats = {"approved-group"}

    assert telegram._is_allowed_message("owner-dm", "1", "private", "auth secret") == "auth_bound"
    assert telegram._is_allowed_message("owner-dm", "1", "private", "hello") == "allow"
    assert telegram._is_allowed_message("unlisted-group", "2", "group", "hello") == "ignore"


def test_owner_bind_can_expand_configured_runtime_allowlist(monkeypatch):
    telegram = load_telegram(monkeypatch)
    telegram._admin_allowed_chats = {"configured-group"}

    assert telegram._is_allowed_message("owner-dm", "1", "private", "auth secret") == "auth_bound"
    assert telegram._is_allowed_message("new-group", "1", "group", "/bind") == "group_bound"
    assert "new-group" in telegram._admin_allowed_chats
    assert "new-group" in telegram._authorized_groups


def test_invalid_unbind_does_not_block_following_update(monkeypatch):
    telegram = load_telegram(monkeypatch)
    telegram._owner_id = "101"
    telegram._running = True
    monkeypatch.setattr(telegram.auth, "revoke_channel_group",
                        lambda *args, **kwargs: pytest.fail("invalid group reached auth backend"))

    def poll(*args, **kwargs):
        telegram._running = False
        return [{"update_id": index, "message": {
            "message_id": index, "text": text, "from": {"id": 101, "username": "alice"},
            "chat": {"id": 101, "type": "private"}}}
            for index, text in enumerate(("/unbind " + "я" * 4000, "hello"), start=7)]

    monkeypatch.setattr(telegram, "_api_call", poll)
    telegram._poll_loop()
    assert telegram._offset == 9
    assert telegram.getLastMessage() == "[101] [8] @alice: hello"
