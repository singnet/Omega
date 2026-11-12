"""Check client writes and the lines forwarded with the server's prefix."""
import importlib.util
import sys
import types
from collections import deque
from pathlib import Path

import pytest


class _ChghostServerSocket:
    """Model registration and notify subscribed clients of a username change.

    This is a protocol model, not a live IRC server. Changing only the username
    isolates CHGHOST from the separate host-only 396 notification. The IRCv3
    fallback QUIT/JOIN is for other clients sharing channels with this client:
    https://ircv3.net/specs/extensions/chghost
    """

    def __init__(self, module, frames, text, change_username, cap_reply):
        self.module = module
        self.frames = frames
        self.text = text
        self.change_username = change_username
        self.cap_reply = cap_reply
        self.incoming = deque()
        self.forwarded = []
        self.client_identities = []
        self.nick = None
        self.user_received = False
        self.negotiating = False
        self.registered = False
        self.joined = False
        self.chghost = False
        self.change_processed = False
        self.delivery_triggered = False
        self.sender = "omega1234!omega1234@host.example"

    def _enqueue(self, line):
        self.incoming.append((line + "\r\n").encode())

    def sendall(self, frame):
        self.frames.append(frame)
        parts = frame.decode().strip().split()
        if parts[0] == "CAP":
            if parts[1] == "LS":
                self.negotiating = not self.registered
                self._enqueue(":server CAP * LS :chghost")
            elif parts[1] == "REQ":
                if self.cap_reply == "unsupported":
                    self._enqueue(":server 421 * CAP :Unknown command")
                    return
                if self.cap_reply == "ignored":
                    return
                self.negotiating = not self.registered
                requested = " ".join(parts[2:]).removeprefix(":").split()
                response = self.cap_reply if requested == ["chghost"] else "NAK"
                if response == "ACK":
                    self.chghost = True
                self._enqueue(f":server CAP * {response} :{' '.join(requested)}")
            elif parts[1] == "END":
                self.negotiating = False
        elif parts[0] == "NICK":
            self.nick = parts[1]
        elif parts[0] == "USER":
            self.user_received = True
        elif parts[0] == "JOIN":
            assert self.registered
            self.joined = True
            self._enqueue(f":{self.sender} JOIN :#omega")
            self._enqueue(":server 366 omega1234 #omega :End of names")
        elif parts[0] == "PRIVMSG":
            assert self.joined
            self.client_identities.append(self.module._sender_prefix)
            self.forwarded.append(f":{self.sender} ".encode() + frame)

        if (self.nick and self.user_received
                and not self.registered and not self.negotiating):
            self.registered = True
            self._enqueue(":server 001 omega1234 :Welcome")

    def recv(self, size):
        if self.incoming:
            return self.incoming.popleft()
        assert self.joined, "Client stalled during CAP negotiation/registration"
        if not self.change_processed:
            self.change_processed = True
            if self.change_username:
                old_sender = self.sender
                new_user = "verylongserverassignedusername"
                self.sender = f"omega1234!{new_user}@host.example"
                if self.chghost:
                    self._enqueue(f":{old_sender} CHGHOST {new_user} host.example")
            # Let the receive loop process CHGHOST before queuing outbound text.
            self._enqueue("PING :after-identity-change")
            return self.incoming.popleft()
        if not self.delivery_triggered:
            self.delivery_triggered = True
            self.module._outbox.put(self.text)
            raise self.module.socket.timeout("trigger normal outbox poll")
        return b""

    def settimeout(self, seconds):
        pass

    def close(self):
        pass


@pytest.mark.parametrize("sender", [
    "omega1234!omega1234@host.example",
    "n" * 64 + "!~" + "u" * 32 + "@" + "h" * 200,
    "бот!юзер@хост.example",
])
def test_forwarded_message_preserves_all_emoji(irc, sender):
    module, frames = irc
    module._sender_prefix = sender
    text = "🙂" * 400
    module.send_message(text)
    prefix = f":{sender} PRIVMSG #omega :".encode("utf-8")
    forwarded = [f":{sender} ".encode("utf-8") + frame for frame in frames]
    assert forwarded
    assert all(len(frame) <= 512 for frame in forwarded)
    assert "".join(frame[len(prefix):-2].decode("utf-8") for frame in forwarded) == text
    assert len(module._outbox) == 0


@pytest.fixture
def irc(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root))
    monkeypatch.syspath_prepend(str(root / "channels"))
    monkeypatch.setitem(sys.modules, "auth", types.ModuleType("auth"))
    config = types.ModuleType("config")
    config.config_get_by_key = lambda key, default=None: default
    monkeypatch.setitem(sys.modules, "config", config)
    spec = importlib.util.spec_from_file_location("irc_under_test", root / "channels/irc.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.time = types.SimpleNamespace(sleep=lambda seconds: None)
    module._channel = "#omega"
    module._nick = "omega1234"
    module._sender_prefix = "omega1234!omega1234@host.example"
    module._connected = True
    frames = []
    module._sock = types.SimpleNamespace(sendall=frames.append)
    return module, frames


@pytest.mark.parametrize(
    "text",
    ["a" * 1200, "я" * 300, "🙂" * 130, "я" * 400, "aя🙂" * 400],
    ids=["ascii", "cyrillic", "emoji", "400-characters", "mixed"],
)
@pytest.mark.parametrize("channel", ["#omega", "#" + "я" * 20], ids=["short", "utf8-target"])
def test_message_fits_wire_limit_without_losing_text(irc, text, channel):
    module, frames = irc
    module._channel = channel
    module.send_message(text)
    sender = f":{module._sender_prefix} ".encode("utf-8")
    prefix = sender + f"PRIVMSG {channel} :".encode("utf-8")
    assert frames
    payloads = []
    for frame in frames:
        frame = sender + frame
        assert len(frame) <= 512
        assert frame.startswith(prefix)
        assert frame.endswith(b"\r\n")
        payloads.append(frame[len(prefix):-2].decode("utf-8"))
    assert "".join(payloads) == text
    assert len(module._outbox) == 0


def test_payload_at_byte_boundary(irc):
    module, frames = irc
    # 18 bytes for command/target/CRLF, plus 34 for the server prefix.
    module.send_message("я" * 230)
    assert [len(frame) + 34 for frame in frames] == [512]


def test_one_multibyte_character_over_boundary(irc):
    module, frames = irc
    module.send_message("я" * 231)
    assert [len(frame) + 34 for frame in frames] == [512, 54]


def test_queued_message_uses_target_at_delivery(irc):
    module, frames = irc
    module._connected = False
    module.send_message("🙂" * 300)
    assert frames == []
    module._channel = "#" + "я" * 20
    module._connected = True
    module._flush_outbox()
    prefix = f"PRIVMSG {module._channel} :".encode("utf-8")
    assert all(len(frame) <= 512 for frame in frames)
    assert "".join(frame[len(prefix):-2].decode("utf-8") for frame in frames) == "🙂" * 300


def test_send_rejects_oversized_command_before_socket_write(irc):
    module, frames = irc
    with pytest.raises(ValueError, match="512"):
        module._send("x" * 511)
    assert frames == []


def test_send_accepts_exact_wire_boundary(irc):
    module, frames = irc
    module._send("x" * 510)
    assert frames == [b"x" * 510 + b"\r\n"]


def test_ascii_wrapping_and_literal_newlines_are_preserved(irc):
    module, frames = irc
    module.send_message("a" * 401 + "\\nhello")
    prefix = b"PRIVMSG #omega :"
    assert [frame[len(prefix):-2] for frame in frames] == [b"a" * 400, b"a", b"hello"]


@pytest.mark.parametrize("successful_parts", [0, 1, 2])
def test_retry_preserves_only_unsent_text(irc, successful_parts):
    module, frames = irc
    text = "🙂" * 400

    def fail_after_parts(frame):
        if len(frames) == successful_parts:
            raise OSError("connection lost")
        frames.append(frame)

    module._sock = types.SimpleNamespace(sendall=fail_after_parts)
    module.send_message(text)
    assert len(frames) == successful_parts
    assert len(module._outbox) == 1

    # A second failed retry must not discard the remaining text.
    module._flush_outbox()
    assert len(frames) == successful_parts
    assert len(module._outbox) == 1

    # Reconnect can change the visible host; the remainder needs a new budget.
    old_sender = module._sender_prefix
    module._sender_prefix = "omega1234!~user@" + "h" * 200
    module._sock = types.SimpleNamespace(sendall=frames.append)
    module.send_message("tail")
    prefix = b"PRIVMSG #omega :"
    assert "".join(frame[len(prefix):-2].decode("utf-8") for frame in frames) == text + "tail"
    for index, frame in enumerate(frames):
        sender = old_sender if index < successful_parts else module._sender_prefix
        assert len(f":{sender} ".encode() + frame) <= 512
    assert len(module._outbox) == 0


@pytest.mark.parametrize("nick", ["omega1234", "n" * 80])
def test_unknown_identity_reserves_long_username_and_hostname(irc, nick):
    module, frames = irc
    module._nick = nick
    module._sender_prefix = None
    sender = nick + "!~" + "u" * 32 + "@" + "h" * 255
    module.send_message("🙂" * 400)
    assert frames
    assert all(len(f":{sender} ".encode() + frame) <= 512 for frame in frames)
    assert "".join(frame.split(b" :", 1)[1][:-2].decode() for frame in frames) == "🙂" * 400
    assert len(module._outbox) == 0


def test_no_room_for_character_retains_message(irc):
    module, frames = irc
    module._sender_prefix = "n!u@" + "h" * 489
    module.send_message("🙂")
    assert frames == []
    assert len(module._outbox) == 1
    module._sender_prefix = "n!u@host"
    module._flush_outbox()
    assert len(frames) == 1
    assert frames[0].endswith("🙂\r\n".encode())
    assert len(module._outbox) == 0


@pytest.mark.parametrize("identity_lines, expected", [
    ([], "omega1234!~serveruser@visible.example"),
    ([":other!user@other.example JOIN :#omega"], "omega1234!~serveruser@visible.example"),
    ([":omega1234!~serveruser@visible.example NICK :longerbotname"],
     "longerbotname!~serveruser@visible.example"),
    ([":omega1234!~serveruser@visible.example CHGHOST newuser longer.host.example"],
     "omega1234!newuser@longer.host.example"),
    ([":server 396 omega1234 hidden.example :is now your displayed host"],
     "omega1234!~serveruser@hidden.example"),
])
def test_session_learns_identity_before_flushing(irc, monkeypatch, identity_lines, expected):
    module, frames = irc
    module._connected = False
    module.send_message("🙂" * 400)
    module._sender_prefix = "stale!user@previous.connection"
    module._running = True
    # The server-selected nick and username need not match the requested ones.
    lines = [
        ":server 001 omega1234 :Welcome",
        ":omega1234!~serveruser@visible.example JOIN :#omega",
        *identity_lines,
        ":server 366 omega1234 #omega :End of names",
    ]
    identities = []
    incoming = iter([("\r\n".join(lines) + "\r\n").encode(), b""])

    def sendall(frame):
        identities.append(module._sender_prefix)
        frames.append(frame)

    sock = types.SimpleNamespace(
        sendall=sendall, recv=lambda size: next(incoming),
        settimeout=lambda seconds: None, close=lambda: None,
    )
    monkeypatch.setattr(module.socket, "create_connection", lambda *args, **kwargs: sock)
    with pytest.raises(ConnectionError, match="closed"):
        module._irc_session("#omega", "test.invalid", 6667, "requestednick")
    assert frames[:3] == [b"CAP REQ :chghost\r\n", b"NICK requestednick\r\n",
                          b"USER requestednick 0 * :requestednick\r\n"]
    assert identities[:3] == [None, None, None]  # No stale identity on reconnect.
    messages = [frame for frame in frames if frame.startswith(b"PRIVMSG ")]
    assert messages
    assert identities[-len(messages):] == [expected] * len(messages)
    assert all(len(f":{expected} ".encode() + frame) <= 512 for frame in messages)
    assert "".join(frame.split(b" :", 1)[1][:-2].decode() for frame in messages) == "🙂" * 400
    assert len(module._outbox) == 0
    assert module._sender_prefix is None
    assert not module._connected


@pytest.mark.parametrize("change", [None, "NICK", "396", "CHGHOST"],
                         ids=["unchanged-control", "nick-grows", "host-grows", "user-grows"])
def test_identity_change_between_parts_preserves_forwarded_text(irc, change):
    module, frames = irc
    original_sender = module._sender_prefix
    forwarded = []
    text = "🙂" * 400

    def sendall(frame):
        frames.append(frame)
        forwarded.append(f":{module._sender_prefix} ".encode() + frame)

    def between_writes(seconds):
        # Deterministically schedule the receiver's identity update during
        # _send's throttle, after the first write and before the second one.
        if len(frames) != 1:
            return
        if change == "NICK":
            line = f":{original_sender} NICK :omega_with_a_longer_nick"
        elif change == "396":
            line = ":server 396 omega1234 a-very-long-visible-hostname.example.net :hidden host"
        elif change == "CHGHOST":
            line = f":{original_sender} CHGHOST verylongserverassignedusername host.example"
        else:
            return
        module._update_sender_identity(line.split())

    module._sock = types.SimpleNamespace(sendall=sendall)
    module.time = types.SimpleNamespace(sleep=between_writes)
    module.send_message(text)

    assert len(frames) > 1
    if change:
        assert module._sender_prefix != original_sender
    assert all(len(frame) <= 512 for frame in frames)
    assert "".join(frame.split(b" :", 1)[1][:-2].decode() for frame in frames) == text
    sizes = [len(frame) for frame in forwarded]
    assert max(sizes) <= 512, f"forwarded sizes={sizes}; outbox={len(module._outbox)}"
    assert "".join(frame.split(b" :", 1)[1][:-2].decode() for frame in forwarded) == text
    assert len(module._outbox) == 0


@pytest.mark.parametrize("change_username, cap_reply", [
    (False, "ACK"), (True, "ACK"), (False, "NAK"),
    (False, "unsupported"), (False, "ignored"),
], ids=["unchanged-control", "username-changes", "cap-rejected", "no-cap", "cap-ignored"])
def test_session_with_cap_gated_chghost_preserves_forwarded_text(
        irc, monkeypatch, change_username, cap_reply):
    module, frames = irc
    module._connected = False
    module._running = True
    text = "🙂" * 400
    sock = _ChghostServerSocket(module, frames, text, change_username, cap_reply)
    monkeypatch.setattr(module.socket, "create_connection", lambda *args, **kwargs: sock)
    with pytest.raises(ConnectionError, match="closed"):
        module._irc_session("#omega", "test.invalid", 6667, "omega1234")

    assert sock.forwarded
    assert sock.delivery_triggered
    assert all(len(frame) <= 512 for frame in frames)
    assert "".join(frame.split(b" :", 1)[1][:-2].decode() for frame in sock.forwarded) == text
    sizes = [len(frame) for frame in sock.forwarded]
    caps = [frame.decode().strip() for frame in frames if frame.startswith(b"CAP ")]
    expected_caps = ["CAP REQ :chghost"]
    if cap_reply in {"ACK", "NAK"}:
        expected_caps.append("CAP END")
    assert caps == expected_caps
    assert max(sizes) <= 512, (
        f"forwarded sizes={sizes}; outbox={len(module._outbox)}; CAP={caps}; "
        f"client identity={sock.client_identities[0]}; server identity={sock.sender}"
    )
    assert len(module._outbox) == 0


def test_identity_growth_retains_unsent_text_when_no_character_fits(irc):
    module, frames = irc
    original_sender = module._sender_prefix
    text = "🙂" * 400

    def between_writes(seconds):
        module._update_sender_identity(
            f":server 396 omega1234 {'h' * 489} :hidden host".split())

    module.time = types.SimpleNamespace(sleep=between_writes)
    module.send_message(text)
    assert len(frames) == 1
    assert len(module._outbox) == 1
    module._sender_prefix = original_sender
    module.time = types.SimpleNamespace(sleep=lambda seconds: None)
    module._flush_outbox()
    assert len(module._outbox) == 0
    assert "".join(frame.split(b" :", 1)[1][:-2].decode() for frame in frames) == text
    assert all(len(f":{original_sender} ".encode() + frame) <= 512 for frame in frames)
