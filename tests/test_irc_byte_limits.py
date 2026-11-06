"""Check the actual UTF-8 bytes passed to the IRC socket."""
import importlib.util
import sys
import types
from pathlib import Path

import pytest


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
    prefix = f"PRIVMSG {channel} :".encode("utf-8")
    assert frames
    payloads = []
    for frame in frames:
        assert len(frame) <= 512
        assert frame.startswith(prefix)
        assert frame.endswith(b"\r\n")
        payloads.append(frame[len(prefix):-2].decode("utf-8"))
    assert "".join(payloads) == text
    assert len(module._outbox) == 0


def test_payload_at_byte_boundary(irc):
    module, frames = irc
    # #omega has 18 bytes of command/target/CRLF overhead.
    module.send_message("я" * 247)
    assert [len(frame) for frame in frames] == [512]


def test_one_multibyte_character_over_boundary(irc):
    module, frames = irc
    module.send_message("я" * 248)
    assert [len(frame) for frame in frames] == [512, 20]


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

    module._sock = types.SimpleNamespace(sendall=frames.append)
    module.send_message("tail")
    prefix = b"PRIVMSG #omega :"
    assert "".join(frame[len(prefix):-2].decode("utf-8") for frame in frames) == text + "tail"
    assert all(len(frame) <= 512 for frame in frames)
    assert len(module._outbox) == 0
