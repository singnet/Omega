import os
import random
import socket
import threading
import time
import textwrap
import auth
from src.logger import get_logger
from delivery_queue import PartialDeliveryError, PendingMessages
import channels
from config import config_get_by_key

logger = get_logger(__name__)

_running = False
_sock = None
_sock_lock = threading.Lock()
_last_message = ""
_msg_lock = threading.Lock()
_channel = None
_connected = False
_auth_lock = threading.Lock()
_authenticated_nick = None
_outbox = PendingMessages()
_nick = None
_sender_prefix = None
IRC_MAX_LINE_BYTES = 512
# Reserve a long username (including a possible '~') and a full DNS hostname
# until the server supplies our actual nick!user@host in our JOIN echo.
IRC_FALLBACK_NICK_BYTES = 30
IRC_FALLBACK_USER_BYTES = 33
IRC_FALLBACK_HOST_BYTES = 255

def _send(cmd):
    wire = (cmd + "\r\n").encode("utf-8")
    if len(wire) > IRC_MAX_LINE_BYTES:
        raise ValueError(f"IRC line exceeds {IRC_MAX_LINE_BYTES} bytes ({len(wire)} bytes)")
    with _sock_lock:
        if _sock is None:
            raise RuntimeError("IRC channel is not connected")
        _sock.sendall(wire)
    time.sleep(1)

def _set_last(msg):
    global _last_message
    with _msg_lock:
        if _last_message == "":
            _last_message = msg
        else:
            _last_message = _last_message + " | " + msg

def getLastMessage():
    global _last_message
    with _msg_lock:
        tmp = _last_message
        _last_message = ""
        return tmp


def _normalize_nick(nick):
    return nick.strip().lower()


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

def _is_allowed_message(nick, msg):
    global _authenticated_nick
    norm_nick = _normalize_nick(nick)
    with _auth_lock:
        if not auth.is_auth_enabled():
            return "allow"
        if _authenticated_nick is not None:
            return "allow" if norm_nick == _authenticated_nick else "ignore"
        auth_candidate = _parse_auth_candidate(msg) if _is_auth_command(msg) else None
        user_id_check = auth.authenticate_channel_user('IRC', norm_nick, auth_candidate)
        if user_id_check in ["auth_bound", "allow"]:
            _authenticated_nick = norm_nick
            return user_id_check
        else:
            return "ignore"

def _ready_to_send():
    return _connected and bool(_channel)


def _sender_prefix_bytes():
    sender_prefix = _sender_prefix
    if sender_prefix is not None:
        return len(f":{sender_prefix} ".encode("utf-8"))
    nick_bytes = max(IRC_FALLBACK_NICK_BYTES, len((_nick or "").encode("utf-8")))
    # ':', '!', '@', and the space separating the prefix from the command.
    return nick_bytes + IRC_FALLBACK_USER_BYTES + IRC_FALLBACK_HOST_BYTES + 4


def _update_sender_identity(parts):
    global _nick, _sender_prefix
    if len(parts) < 3:
        return
    command = parts[1]
    if command == "001":
        _nick = parts[2]
        return
    if not _nick:
        return
    if command == "396" and len(parts) > 3 and parts[2] == _nick:
        # A server can change our visible host after registration.
        if _sender_prefix is not None:
            _sender_prefix = _sender_prefix.rsplit("@", 1)[0] + "@" + parts[3]
        return
    source = parts[0].removeprefix(":")
    sender, separator, userhost = source.partition("!")
    if sender != _nick or not separator or "@" not in userhost:
        return
    if command == "JOIN":
        _sender_prefix = source
    elif command == "NICK":
        _nick = parts[2].removeprefix(":")
        _sender_prefix = f"{_nick}!{userhost}"
    elif command == "CHGHOST" and len(parts) > 3:
        _sender_prefix = f"{_nick}!{parts[2]}@{parts[3].removeprefix(':')}"


def _take_utf8_chunk(text, max_bytes):
    """Return the first part that fits the byte budget without splitting a character."""
    size = 0
    for index, character in enumerate(text):
        char_bytes = len(character.encode("utf-8"))
        if char_bytes > max_bytes:
            raise ValueError("IRC target leaves insufficient room for a UTF-8 character")
        if size + char_bytes > max_bytes:
            return text[:index]
        size += char_bytes
    return text


def _deliver_outbound(chunk):
    sent_characters = 0
    try:
        while sent_characters < len(chunk):
            # The receiver can update our identity while _send throttles writes.
            # Re-split only the unsent text using the latest prefix each time.
            prefix = f"PRIVMSG {_channel} :"
            budget = IRC_MAX_LINE_BYTES - len((prefix + "\r\n").encode("utf-8"))
            budget -= _sender_prefix_bytes()
            part = _take_utf8_chunk(chunk[sent_characters:], budget)
            _send(prefix + part)
            sent_characters += len(part)
    except Exception as exc:
        if sent_characters:
            raise PartialDeliveryError(chunk[sent_characters:]) from exc
        raise


def _flush_outbox():
    try:
        _outbox.flush(_deliver_outbound, _ready_to_send)
    except Exception as exc:
        logger.warning(f"IRC send failed; retaining queued message: {exc}")


def _irc_session(channel, server, port, nick):
    global _running, _sock, _connected, _nick, _sender_prefix
    _connected = False
    _nick = nick
    _sender_prefix = None
    logger.info(f"Connecting to {server}:{port} as {nick} for channel {channel}")
    sock = None
    try:
        sock = socket.create_connection((server, int(port)), timeout=15)
        sock.settimeout(60)
        logger.info("TCP connected")
    except OSError as e:
        raise ConnectionError(f"IRC connect failed: {e}") from e

    with _sock_lock:
        _sock = sock

    try:
        # Request the single capability we need directly (IRCv3 CAP REQ).
        # NICK/USER still allow registration on servers without CAP support.
        cap_pending = True
        _send("CAP REQ :chghost")
        _send(f"NICK {nick}")
        _send(f"USER {nick} 0 * :{nick}")
        read_buffer = ""
        while _running:
            try:
                data = sock.recv(4096).decode(errors="ignore")
            except socket.timeout:
                logger.debug("IRC receive timed out, polling again")
                _flush_outbox()
                continue
            if not data:
                raise ConnectionError("IRC server closed the connection")
            read_buffer += data
            while "\r\n" in read_buffer:
                line, read_buffer = read_buffer.split("\r\n", 1)
                if not line:
                    continue
                if line.startswith("PING"):
                    _send(f"PONG {line.split()[1]}")
                parts = line.split()
                _update_sender_identity(parts)
                if (cap_pending and len(parts) > 3 and parts[1] == "CAP"
                        and parts[3] in {"ACK", "NAK"}):
                    _send("CAP END")
                    cap_pending = False
                elif (len(parts) > 3 and parts[1] == "421"
                      and parts[3] == "CAP"):
                    cap_pending = False
                elif len(parts) > 1 and parts[1] == "001":
                    cap_pending = False
                    logger.info(f"Registered. Joining {_channel}")
                    _send(f"JOIN {_channel}")
                elif (
                    len(parts) > 3
                    and parts[1] == "366"
                    and parts[3].lower() == _channel.lower()
                ):
                    logger.info(f"Joined {_channel}")
                    _connected = True
                    _flush_outbox()
                elif len(parts) > 1 and parts[1] in {"403", "405", "471", "473", "474", "475"}:
                    logger.error(f"Join failed: {line}")
                elif len(parts) > 1 and parts[1] == "433":
                    raise ConnectionError(f"Nickname in use: {line}")
                elif line.startswith(":") and " PRIVMSG " in line:
                    try:
                        prefix, trailing = line[1:].split(" PRIVMSG ", 1)
                        sender_nick = prefix.split("!", 1)[0]

                        if " :" not in trailing:
                            continue  # malformed, ignore safely

                        msg = trailing.split(" :", 1)[1]
                        state = _is_allowed_message(sender_nick, msg)
                        if state == "allow":
                            _set_last(f"{sender_nick}: {msg}")
                        elif state == "auth_bound":
                            send_message(f"Authentication successful for {sender_nick}.")
                    except Exception as e:
                        logger.exception(f"Exception caught {repr(e)}")
    finally:
        _connected = False
        _sender_prefix = None
        with _sock_lock:
            if _sock is sock:
                _sock = None
        if sock is not None:
            sock.close()
        logger.info("Disconnected")


def _irc_loop(channel, server, port, nick):
    backoff_seconds = 1
    while _running:
        try:
            _irc_session(channel, server, port, nick)
            backoff_seconds = 1
        except socket.timeout:
            logger.debug("IRC receive timed out, reconnecting")
        except Exception as exc:
            if _running:
                logger.warning(f"IRC connection error: {exc}")

        if not _running:
            break
        logger.info(f"Reconnecting IRC in {backoff_seconds}s")
        time.sleep(backoff_seconds)
        backoff_seconds = min(backoff_seconds * 2, 30)

def start_irc(channel, server="irc.libera.chat", port=6667, nick="omega"):
    global _running, _channel, _connected
    nick = f"{nick}{random.randint(1000, 9999)}"
    if not channel.startswith("#"):
        channel = f"#{channel}"
    _running = True
    _connected = False
    _channel = channel
    t = threading.Thread(target=_irc_loop, args=(channel, server, port, nick), daemon=True)
    t.start()
    return t

def stop_irc():
    global _running
    _running = False
    with _sock_lock:
        sock = _sock
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

def send_message(text):
    max_len = 400
    segments = str(text).replace("\r", "").split("\\n")
    lines = []
    for segment in segments:
        lines.extend(textwrap.wrap(segment, width=max_len, break_long_words=True, break_on_hyphens=False))
    _outbox.extend(lines)
    _flush_outbox()

class IRCChannel(channels.CommChannel):

    def __init__(self):
        super().__init__()

    def start(self) -> None:
        channel = config_get_by_key("IRC_channel", "##omega")
        server = config_get_by_key("IRC_server", "irc.quakenet.org")
        port = int(config_get_by_key("IRC_port", 6667))
        user = config_get_by_key("IRC_user", "omega")
        start_irc(channel, server, port, user)

    def stop(self) -> None:
        stop_irc()

    def receive(self) -> str:
        return getLastMessage()

    def send(self, message: str) -> None:
        send_message(message)

def loadOmegaPlugin():
    channels.registerCommChannel("irc", IRCChannel())
