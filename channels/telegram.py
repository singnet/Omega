import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
import auth
from src.logger import get_logger
from delivery_queue import PendingMessages
import channels
from config import config_get_by_key

logger = get_logger(__name__)

_running = False
_msg_lock = threading.Lock()
_state_lock = threading.Lock()
_inbox = deque()
_default_chat_id = ""
_outbox = PendingMessages()
_deferred_default_outbox = PendingMessages()

_bot_token = ""
_api_base = ""
_bot_username= ""
_poll_timeout = 20
_offset = None
_connected = False
_admin_allowed_chats = set()
_owner_id = None
_authorized_groups = set()

_auto_bound_chat = ""

_BIND_COMMANDS = ("/bind", "/authorize_group")
_UNBIND_COMMANDS = ("/unbind", "/unauthorize_group")
_ROUTED_MESSAGE_RE = re.compile(
    r"^\s*\[(-?\d*)\]\s*\[(\d*)\]\s*(.*)$",
    re.DOTALL,
)
_TARGET_ONLY_MESSAGE_RE = re.compile(r"^\s*\[(-?\d+)\]\s*(.*)$", re.DOTALL)


def _enqueue_message(msg, chat_id, reply_to_id=None):
    with _msg_lock:
        _inbox.append(
            (
                str(chat_id),
                str(reply_to_id) if reply_to_id is not None else "",
                str(msg),
            )
        )


def getLastMessage():
    with _msg_lock:
        if not _inbox:
            return ""
        chat_id, reply_to_id, message = _inbox.popleft()
    return f"[{chat_id}] [{reply_to_id}] {message}"


def _ready_to_send():
    return _connected


def _deliver_outbound(item):
    target_chat, reply_to_id, chunk = item
    params = {"chat_id": target_chat, "text": chunk}
    if reply_to_id:
        params["reply_parameters"] = json.dumps(
            {
                "message_id": int(reply_to_id),
                "allow_sending_without_reply": True,
            },
            separators=(",", ":"),
        )
    _api_call(
        "sendMessage",
        params,
        timeout=15,
        use_post=True,
    )


def _flush_outbox():
    try:
        _outbox.flush(_deliver_outbound, _ready_to_send)
    except Exception as exc:
        logger.warning(f"Telegram send failed; retaining queued message: {exc}")


def _ready_to_route_deferred_default():
    with _state_lock:
        return bool(_default_chat_id)


def _route_deferred_default(item):
    reply_to_id, chunk = item
    with _state_lock:
        target_chat = str(_default_chat_id or "").strip()
    if not target_chat:
        raise RuntimeError("Telegram owner DM is not available")
    _outbox.put((target_chat, reply_to_id, chunk))


def _flush_deferred_default_outbox():
    try:
        _deferred_default_outbox.flush(
            _route_deferred_default,
            _ready_to_route_deferred_default,
        )
    except Exception as exc:
        logger.warning(
            f"Telegram deferred send failed; retaining queued message: {exc}"
        )
        return
    _flush_outbox()


def _parse_outbound_message(text):
    """Return target, reply message ID, body, and whether routing was explicit."""
    match = _ROUTED_MESSAGE_RE.match(text)
    if match:
        return match.group(1), match.group(2), match.group(3), True

    # Backward compatibility with the upstream Telegram form: [chat_id] body.
    match = _TARGET_ONLY_MESSAGE_RE.match(text)
    if match:
        return match.group(1), "", match.group(2), True

    return "", "", text, False


def _is_allowed_outbound_target(chat_id):
    chat_id = str(chat_id or "").strip()
    if not chat_id:
        return False

    if auth.is_auth_enabled():
        return chat_id == str(_owner_id or "") or chat_id in _authorized_groups

    if _admin_allowed_chats:
        return chat_id in _admin_allowed_chats
    return chat_id in {str(_default_chat_id or ""), str(_auto_bound_chat or "")}


def send_message(text, target_chat=None, reply_to_id=None):
    text = str(text).replace("\\n", "\n").replace("\r", "")
    if not text:
        return False

    trusted_target = str(target_chat or "").strip()
    if trusted_target:
        target_chat = trusted_target
        reply_to_id = str(reply_to_id or "").strip()
    else:
        parsed_target, parsed_reply, text, routed = _parse_outbound_message(text)
        target_chat = parsed_target or str(_default_chat_id or "").strip()
        reply_to_id = parsed_reply
        if routed and parsed_target and not _is_allowed_outbound_target(parsed_target):
            logger.warning(
                f"Telegram send rejected: target chat {parsed_target} is not authorized"
            )
            return False

    if not text:
        logger.warning("Telegram send skipped: routed message body is empty")
        return False

    max_len = 3900
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)]
    if not target_chat:
        _deferred_default_outbox.extend((reply_to_id, chunk) for chunk in chunks)
        logger.info("Telegram send deferred until an owner DM is available")
        return True

    outbound = [(target_chat, reply_to_id, chunk) for chunk in chunks]
    _outbox.extend(outbound)
    _flush_outbox()
    return True


# ---------------------------------------------------------------------------
# Authorization.

def _parse_auth_candidate(msg):
    text = msg.strip()
    lower = text.lower()
    if lower.startswith("auth "):
        return text[5:].strip()
    if lower.startswith("/auth "):
        return text[6:].strip()
    return text


def _is_auth_command(msg):
    lower = msg.strip().lower()
    return lower.startswith("auth ") or lower.startswith("/auth ")


def _first_token(msg):
    stripped = msg.strip()
    if not stripped:
        return ""
    return stripped.split(None, 1)[0].lower()


def _is_targeted_command(msg, commands):
    token = _first_token(msg)
    command, separator, target_username = token.partition("@")

    if command not in commands:
        return False

    if not separator:
        return True

    return bool(_bot_username) and target_username == _bot_username


def _is_bind_command(msg):
    return _is_targeted_command(msg, _BIND_COMMANDS)


def _is_unbind_command(msg):
    return _is_targeted_command(msg, _UNBIND_COMMANDS)


def _command_argument(msg):
    parts = str(msg or "").strip().split(None, 1)
    return parts[1].strip() if len(parts) == 2 else ""


def _is_allowed_message(chat_id, user_id, chat_type, msg, update_id=None):
    global _auto_bound_chat, _owner_id, _default_chat_id

    auth_enabled = auth.is_auth_enabled()

    if not auth_enabled:
        if _admin_allowed_chats:
            return "allow" if chat_id in _admin_allowed_chats else "ignore"
        with _state_lock:
            if _auto_bound_chat and chat_id != _auto_bound_chat:
                return "ignore"
            if not _auto_bound_chat:
                _auto_bound_chat = chat_id
                _default_chat_id = chat_id
        return "allow"

    owner_id = _owner_id

    is_owner_bootstrap = (
        owner_id is None
        and chat_type == "private"
        and _is_auth_command(msg)
    )
    is_owner_private_chat = (
        owner_id is not None
        and chat_type == "private"
        and user_id == owner_id
    )
    is_owner_group_bind = (
        owner_id is not None
        and chat_type != "private"
        and user_id == owner_id
        and _is_bind_command(msg)
    )

    if (
        _admin_allowed_chats
        and chat_id not in _admin_allowed_chats
        and not is_owner_bootstrap
        and not is_owner_private_chat
        and not is_owner_group_bind
    ):
        return "ignore"

    if owner_id is None:
        if is_owner_bootstrap:
            candidate = _parse_auth_candidate(msg)
            state = auth.authenticate_channel_user("TELEGRAM", user_id, candidate)
            if state in {"auth_bound", "allow"}:
                with _state_lock:
                    _owner_id = user_id
                    _default_chat_id = chat_id
                return "auth_bound"
            return state
        return "ignore"

    if chat_type == "private":
        if user_id == owner_id and _is_unbind_command(msg):
            group_id = _command_argument(msg)
            if re.fullmatch(r"-[1-9][0-9]{0,18}", group_id):
                state = auth.revoke_channel_group("TELEGRAM", group_id, user_id, update_id=update_id)
                if state == "group_unbound":
                    _authorized_groups.discard(group_id)
                    _admin_allowed_chats.discard(group_id)
                return state
            return "ignore"
        return "allow" if user_id == owner_id else "ignore"

    # Anything that isn't "private" is a group/supergroup chat.
    if _is_unbind_command(msg):
        if user_id == owner_id:
            state = auth.revoke_channel_group("TELEGRAM", chat_id, user_id, update_id=update_id)
            if state == "group_unbound":
                _authorized_groups.discard(chat_id)
                _admin_allowed_chats.discard(chat_id)
            return state
        return "ignore"

    if chat_id in _authorized_groups:
        return "allow"

    if user_id == owner_id and _is_bind_command(msg):
        state = auth.authorize_channel_group("TELEGRAM", chat_id, user_id, update_id=update_id)
        if state in {"allow", "group_bound"}:
            _authorized_groups.add(chat_id)
            _admin_allowed_chats.add(chat_id)
        return state

    return "ignore"


def _display_name(user, chat):
    username = str(user.get("username", "")).strip()
    if username:
        return f"@{username}"

    first = str(user.get("first_name", "")).strip()
    last = str(user.get("last_name", "")).strip()
    full = f"{first} {last}".strip()
    if full:
        return full

    title = str(chat.get("title", "")).strip()
    if title:
        return title

    return "telegram_user"


def _api_call(method, params=None, timeout=30, use_post=False):
    if not _api_base:
        raise RuntimeError("Telegram adapter not initialized")

    params = params or {}
    encoded = urllib.parse.urlencode(params).encode("utf-8")
    url = f"{_api_base}/{method}"

    if use_post:
        req = urllib.request.Request(url, data=encoded)
    else:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url)

    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", errors="ignore"))

    if not payload.get("ok"):
        raise RuntimeError(payload.get("description", f"{method} failed"))

    return payload.get("result")

def _initialize_bot_identity():
    global _bot_username

    try:
        result = _api_call("getMe", timeout=10)
        if not isinstance(result, dict):
            raise RuntimeError("Telegram getMe returned an invalid response")
        username = str(result.get("username", "")).strip().lstrip("@").lower()
        if not username:
            raise RuntimeError("Telegram getMe did not return the bot username")
    except Exception as exc:
        _bot_username = ""
        logger.warning(f"Could not read Telegram bot identity: {exc}")
        return False

    _bot_username = username
    return True


def _process_update(update):
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return

    text = message.get("text")
    if not text:
        return

    chat = message.get("chat") or {}
    user = message.get("from") or {}
    chat_id = str(chat.get("id", "")).strip()
    user_id = str(user.get("id", "")).strip()
    chat_type = str(chat.get("type", "")).strip()
    message_id = message.get("message_id")
    if not chat_id or not user_id:
        return

    state = _is_allowed_message(chat_id, user_id, chat_type, text, update.get("update_id"))
    display_name = _display_name(user, chat)

    if state == "allow":
        _flush_deferred_default_outbox()
        _enqueue_message(f"{display_name}: {text}", chat_id, message_id)
    elif state == "auth_bound":
        send_message(
            f"Authentication successful. {display_name} is now the bot owner. "
            "Send /bind in a group to open it to everyone there.",
            chat_id,
            message_id
        )
        _flush_deferred_default_outbox()
    elif state == "group_bound":
        send_message(
            "This group is now authorized. All members can talk to the bot here.",
            chat_id,
            message_id
        )
    elif state == "group_unbound":
        send_message("This group is no longer authorized.", chat_id, message_id)



def _poll_loop():
    global _connected, _offset
    logger.info("Polling started")

    while _running:
        try:
            params = {"timeout": int(_poll_timeout)}
            with _state_lock:
                if _offset is not None:
                    params["offset"] = _offset

            updates = _api_call("getUpdates", params=params, timeout=int(_poll_timeout) + 10) or []
            _connected = True
            _flush_outbox()

            for update in updates:
                update_id = update.get("update_id")
                _process_update(update)
                if isinstance(update_id, int):
                    with _state_lock:
                        if _offset is None or (update_id + 1) > _offset:
                            _offset = update_id + 1
        except Exception as exc:
            _connected = False
            logger.warning(f"Poll error: {exc}")
            time.sleep(2)

    _connected = False
    logger.info("Polling stopped")


def _parse_admin_allowed_chats(chat_id_config, allowed_config):
    ids = set()
    single = str(chat_id_config or "").strip()
    if single:
        ids.add(single)
    for part in str(allowed_config or "").split(","):
        part = part.strip()
        if part:
            ids.add(part)
    return ids


def start_telegram(chat_id="", allowed_chat_ids="", poll_timeout=20):
    global _running, _bot_token, _api_base, _poll_timeout, _offset, _connected
    global _default_chat_id
    global _admin_allowed_chats, _auto_bound_chat, _owner_id, _authorized_groups

    proxy = auth.get_proxy_url()
    if proxy:
        _bot_token = "proxy"
        _api_base = f"{proxy}/telegram"
    else:
        _bot_token = os.environ.get("TG_BOT_TOKEN", "").strip()
        if not _bot_token:
            raise ValueError("TG_BOT_TOKEN is required")
        _api_base = f"https://api.telegram.org/bot{_bot_token}"

    _admin_allowed_chats = _parse_admin_allowed_chats(chat_id, allowed_chat_ids)
    _auto_bound_chat = ""
    if auth.is_auth_enabled():
        _owner_id, _authorized_groups = auth.load_channel_auth_state("TELEGRAM")
        _admin_allowed_chats.update(_authorized_groups)
        # Telegram private chat IDs are the owner's user ID, so persisted
        # ownership gives proactive messages a safe destination after restart.
        _default_chat_id = str(_owner_id or chat_id or "").strip()
    else:
        _owner_id, _authorized_groups = None, set()
        _default_chat_id = str(chat_id or "").strip()

    with _msg_lock:
        _inbox.clear()
    _outbox.clear()
    _deferred_default_outbox.clear()

    try:
        _poll_timeout = max(1, int(poll_timeout))
    except Exception as e:
        logger.warning(f"Invalid poll_timeout {poll_timeout!r}, falling back to 20: {e}")
        _poll_timeout = 20

    _offset = None
    _running = True
    _connected = False
    if _admin_allowed_chats:
        logger.info(f"Starting adapter, admin-restricted to chats: {sorted(_admin_allowed_chats)}")
    else:
        logger.info("Starting adapter with no admin chat restriction")

    _initialize_bot_identity()

    t = threading.Thread(target=_poll_loop, daemon=True)
    t.start()
    return t


def stop_telegram():
    global _running
    _running = False


class TelegramChannel(channels.CommChannel):

    def __init__(self):
        super().__init__()

    def start(self) -> None:
        chat_id = config_get_by_key("TG_CHAT_ID", "")
        allowed_chat_ids = config_get_by_key("TG_ALLOWED_CHAT_IDS", "")
        poll_timeout = int(config_get_by_key("TG_POLL_TIMEOUT", 20))
        start_telegram(chat_id, allowed_chat_ids, poll_timeout)

    def stop(self) -> None:
        stop_telegram()

    def receive(self) -> str:
        return getLastMessage()

    def send(self, message: str) -> None:
        send_message(message)


def loadOmegaPlugin():
    channels.registerCommChannel("telegram", TelegramChannel())
