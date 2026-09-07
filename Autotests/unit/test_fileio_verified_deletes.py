"""In-process unit tests for src/fileio.py (verified file deletes).

The delete-file skill returns a result string built from a read-back of the
filesystem after the operation (does the path still exist?) -- ground truth
the agent relays instead of a static success atom it could confabulate
around. Failures return explicit DELETE-FAILED strings instead of raising,
matching the WRITE-VERIFIED / WRITE-FAILED contract in
test_fileio_verified_writes.py.

No container, no network, no token -- same pattern as
mock_websocket/test_wschat_unit.py: the module is loaded by file path.
"""
import importlib.util
import logging
import os
import sys

import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_FILEIO_PATH = os.path.join(_REPO_ROOT, "src", "fileio.py")

if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _load_fileio():
    spec = importlib.util.spec_from_file_location("fileio_under_test", _FILEIO_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fileio():
    return _load_fileio()


def test_delete_removes_existing_file_and_verifies(fileio, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    target = tmp_path / "out.txt"
    target.write_bytes(b"hello world")

    result = fileio.delete_file(str(target))

    assert not target.exists()
    assert result == f"DELETE-VERIFIED file={target}"
    assert "[FILE_IO] delete ok" in caplog.text


def test_delete_missing_file_fails_without_raising(fileio, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    target = tmp_path / "absent.txt"

    result = fileio.delete_file(str(target))

    assert result == f"DELETE-FAILED file={target}: file does not exist"
    assert "[FILE_IO] delete failed" in caplog.text


def test_delete_directory_fails_without_raising(fileio, tmp_path):
    target = tmp_path / "a_directory"
    target.mkdir()

    result = fileio.delete_file(str(target))

    assert target.exists()  # directory must be left untouched
    assert result == f"DELETE-FAILED file={target}: path is a directory"


def test_delete_result_path_matches_input_exactly(fileio, tmp_path):
    # regression guard: result string must echo the path as given, not a
    # resolved/normalized variant, so the agent can match it back to its request.
    sub = tmp_path / "sub"
    sub.mkdir()
    target = tmp_path / "sub" / ".." / "out.txt"
    real = tmp_path / "out.txt"
    real.write_bytes(b"x")

    result = fileio.delete_file(str(target))

    assert not real.exists()
    assert result == f"DELETE-VERIFIED file={target}"
