"""In-process unit tests for the parsing helpers in src/helper.py.
No container, no network, no token — same pattern as
test_fileio_verified_writes.py: the module is loaded by file path.
"""
import datetime
import importlib.util
import os
import sys

import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_HELPER_PATH = os.path.join(_REPO_ROOT, "src", "helper.py")

# helper.py does `from src.logger import get_logger` (repo-root package) at import time.
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _load_helper():
    spec = importlib.util.spec_from_file_location("helper_under_test", _HELPER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def helper():
    return _load_helper()


# --- normalize_string -----------------------------------------------------

def test_normalize_string_decodes_bytes(helper):
    assert helper.normalize_string(b"abc") == "abc"


def test_normalize_string_passes_through_str(helper):
    assert helper.normalize_string("abc") == "abc"


def test_normalize_string_drops_invalid_utf8_instead_of_raising(helper):
    assert helper.normalize_string(b"a\xffb") == "ab"


def test_normalize_string_stringifies_non_text(helper):
    assert helper.normalize_string(123) == "123"


# --- extract_timestamp ----------------------------------------------------

def test_extract_timestamp_parses_leading_history_stamp(helper):
    assert helper.extract_timestamp('("2026-07-30 12:00:00" foo)') == datetime.datetime(
        2026, 7, 30, 12, 0, 0
    )


def test_extract_timestamp_returns_none_when_absent(helper):
    assert helper.extract_timestamp("no timestamp here") is None
