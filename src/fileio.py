"""Verified file writes for the write-file / append-file / write-file-b64 skills.

The string these functions return is the skill result the agent sees. It is
built exclusively from a read-back of the file on disk after the operation
(size, sha256, head/tail snippets) — ground truth the agent can only relay,
not compose. Failures return an explicit *-FAILED string instead of raising,
so the agent loop always receives a result it can act on.
"""
import base64
import hashlib
import os
import re

from src.logger import get_logger

logger = get_logger(__name__)

SNIPPET_BYTES = 80
HASH_MAX_BYTES = 2_000_000


def _snippet(raw):
    # escape backslashes first so literal \n in content stays distinguishable
    # from a real newline in the rendered snippet
    text = raw.decode("utf-8", errors="replace")
    return text.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n")


def _readback(path):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(SNIPPET_BYTES)
        if size > 2 * SNIPPET_BYTES:
            f.seek(-SNIPPET_BYTES, os.SEEK_END)
            tail = f.read(SNIPPET_BYTES)
        else:
            tail = b""
    if size <= HASH_MAX_BYTES:
        with open(path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()[:16]
    else:
        digest = "skipped(large)"
    return size, digest, _snippet(head), _snippet(tail)


def _line_separator(path):
    """Newline needed to start a new line at the end of path, empty when
    the file is empty or already ends with one. Read as bytes so a
    multi-byte character at the end is not decoded from its middle."""
    try:
        if os.path.getsize(path) == 0:
            return b""
        with open(path, "rb") as f:
            f.seek(-1, os.SEEK_END)
            return b"" if f.read(1) == b"\n" else b"\n"
    except OSError:
        return b""


def _write(path, data, append):
    path = str(path)
    word = "APPEND" if append else "WRITE"
    if append:
        data = _line_separator(path) + data + b"\n"
    try:
        with open(path, "ab" if append else "wb") as f:
            f.write(data)
        size, digest, head, tail = _readback(path)
        logger.info(f"[FILE_IO] {word.lower()} ok file={path} bytes={size} sha256={digest}")
        return (f"{word}-VERIFIED file={path} bytes={size} sha256={digest} "
                f"head='{head}' tail='{tail}'")
    except Exception as e:  # the skill must return a result, never raise into the loop
        logger.error(f"[FILE_IO] {word.lower()} failed file={path} err={e}")
        return f"{word}-FAILED file={path}: {e}"


def write_file(path, content):
    return _write(path, str(content).encode("utf-8"), append=False)


def append_file(path, content):
    path = str(path)
    if not os.path.exists(path):
        logger.error(f"[FILE_IO] append failed file={path} err=file does not exist")
        return f"APPEND-FAILED file={path}: file does not exist"
    return _write(path, str(content).encode("utf-8"), append=True)


def write_file_b64(path, content_b64):
    try:
        # tolerate MIME-style line-wrapped base64 (embedded whitespace)
        data = base64.b64decode(re.sub(r"\s+", "", str(content_b64)), validate=True)
    except Exception as e:
        logger.error(f"[FILE_IO] write failed file={path} err=invalid base64")
        return f"WRITE-FAILED file={path}: invalid base64 ({e})"
    return _write(path, data, append=False)


def delete_file(path):
    path = str(path)
    if not os.path.lexists(path):
        logger.error(f"[FILE_IO] delete failed file={path} err=file does not exist")
        return f"DELETE-FAILED file={path}: file does not exist"
    if os.path.isdir(path):
        logger.error(f"[FILE_IO] delete failed file={path} err=path is a directory")
        return f"DELETE-FAILED file={path}: path is a directory"
    try:
        os.remove(path)
    except Exception as e:  # the skill must return a result, never raise into the loop
        logger.error(f"[FILE_IO] delete failed file={path} err={e}")
        return f"DELETE-FAILED file={path}: {e}"
    if os.path.exists(path):  # race: something recreated it between remove() and here
        logger.error(f"[FILE_IO] delete verification failed file={path} still exists after remove")
        return f"DELETE-FAILED file={path}: file still exists after removal"
    logger.info(f"[FILE_IO] delete ok file={path}")
    return f"DELETE-VERIFIED file={path}"