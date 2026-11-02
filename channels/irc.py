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
IRC_MAX_LINE_BYTES = 512

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


def _split_utf8(text, max_bytes):
    start = 0
    size = 0
    for index, character in enumerate(text):
        char_bytes = len(character.encode("utf-8"))
        if char_bytes > max_bytes:
            raise ValueError("IRC target leaves insufficient room for a UTF-8 character")
        if size + char_bytes > max_bytes:
            yield text[start:index]
            start = index
            size = 0
        size += char_bytes
    if start < len(text):
        yield text[start:]


def _deliver_outbound(chunk):
    prefix = f"PRIVMSG {_channel} :"
    budget = IRC_MAX_LINE_BYTES - len((prefix + "\r\n").encode("utf-8"))
    sent_characters = 0
    try:
        for part in _split_utf8(chunk, budget):
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
    global _running, _sock, _connected
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
                if len(parts) > 1 and parts[1] == "001":
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
