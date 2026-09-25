"""Unit tests for the provider timeout status message.

When a provider request runs out of time and the client's retries are gone, the
provider used to return an empty string. The loop then had nothing to run, so
the turn ended without a word to the user and the task looked abandoned (#321).
The timeout now comes back as a `send` command carrying a status message, the
same way a reply cut off by the token limit already does.

No container, no network, no API key, and no provider SDK: `openai` and the
configuration module are stubbed before the module under test is loaded, the
same pattern as test_openclaw_unit.py.
"""
import importlib.util
import os
import sys
import types

import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_LIB_LLM_EXT_PATH = os.path.join(_REPO_ROOT, "providers", "lib_llm_ext.py")
_HELPER_PATH = os.path.join(_REPO_ROOT, "src", "helper.py")

# lib_llm_ext.py does `from src.helper import quote_arg` (repo-root package).
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


class _StubAPITimeoutError(Exception):
    """Stands in for openai.APITimeoutError: the client's own timeout."""


class _StubAPIConnectionError(Exception):
    """Stands in for openai.APIConnectionError: the request never got an answer."""


def _install_stubs():
    config_stub = types.ModuleType("config")
    config_stub.config_get_by_key = lambda key, default=None: None
    sys.modules["config"] = config_stub

    openai_stub = types.ModuleType("openai")
    openai_stub.APITimeoutError = _StubAPITimeoutError
    openai_stub.APIConnectionError = _StubAPIConnectionError
    openai_stub.OpenAI = object  # only referenced in a type annotation
    sys.modules["openai"] = openai_stub


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def llm():
    saved = {name: sys.modules.get(name) for name in ("config", "openai")}
    _install_stubs()
    try:
        yield _load("lib_llm_ext_under_test", _LIB_LLM_EXT_PATH)
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


@pytest.fixture(scope="module")
def helper():
    return _load("helper_under_test", _HELPER_PATH)


def _gateway_error(status):
    error = Exception(f"{status} Gateway Time-out")
    error.status_code = status
    return error


class _RaisingClient:
    """Stand-in for the OpenAI client whose chat call always fails."""

    def __init__(self, error):
        def create(**kwargs):
            raise error

        completions = types.SimpleNamespace(create=create)
        self.chat = types.SimpleNamespace(completions=completions)


def _provider(llm, error):
    provider = llm.AIProvider("OpenAIAPI", "OPENAIAPI_API_KEY", "test-model", "http://localhost/v1/")
    provider._client = _RaisingClient(error)
    return provider


# --- which failures count as a timeout ---------------------------------------

def test_client_timeout_is_a_timeout(llm):
    assert llm._is_timeout_error(_StubAPITimeoutError("timed out"))


@pytest.mark.parametrize("status", [408, 504, 524])
def test_gateway_timeout_statuses_are_a_timeout(llm, status):
    assert llm._is_timeout_error(_gateway_error(status))


@pytest.mark.parametrize("status", [400, 429, 500, 502])
def test_other_statuses_are_not_a_timeout(llm, status):
    assert not llm._is_timeout_error(_gateway_error(status))


def test_a_plain_error_is_not_a_timeout(llm):
    assert not llm._is_timeout_error(ValueError("boom"))


# --- what chat() returns ------------------------------------------------------

def _is_timeout_notice(result):
    return result.startswith('(send "LLM request timed out at ') and result.endswith('")')


def test_chat_tells_the_user_when_the_client_times_out(llm):
    assert _is_timeout_notice(_provider(llm, _StubAPITimeoutError("timed out")).chat("prompt"))


def test_chat_tells_the_user_when_the_gateway_times_out(llm):
    assert _is_timeout_notice(_provider(llm, _gateway_error(504)).chat("prompt"))


def test_chat_still_returns_nothing_for_other_failures(llm):
    assert _provider(llm, ValueError("boom")).chat("prompt") == ""


# --- the message has to survive the parser the loop runs it through ----------

def test_the_timeout_command_parses_into_one_send(llm, helper):
    parsed = helper.balance_parentheses(llm._llm_timeout_command())
    assert parsed.startswith('((send "')
    assert parsed.endswith('"))')
    assert parsed.count("(send ") == 1


# --- one attempt, so the timeout is reported when the first request gives up --

def _client_kwargs(llm, monkeypatch, gateway):
    captured = {}

    def recorder(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(llm.openai, "OpenAI", recorder)
    monkeypatch.setattr(
        llm, "config_get_by_key",
        lambda key, default=None: gateway if key == "GATEWAY_URL" else default,
    )
    if gateway is None:
        monkeypatch.setenv("OPENAIAPI_API_KEY", "dummy")
    provider = llm.AIProvider("OpenAIAPI", "OPENAIAPI_API_KEY", "test-model", "http://localhost/v1/")
    assert provider._create_client() is not None
    return captured


def test_the_proxy_client_makes_one_attempt(llm, monkeypatch):
    assert _client_kwargs(llm, monkeypatch, "http://localhost:8080")["max_retries"] == 0


def test_the_direct_client_makes_one_attempt(llm, monkeypatch):
    assert _client_kwargs(llm, monkeypatch, None)["max_retries"] == 0


# --- which failures are worth another attempt --------------------------------

@pytest.mark.parametrize("status", [409, 429, 500, 502, 503, 522, 529])
def test_transient_statuses_are_retried(llm, status):
    assert llm._is_transient_error(_gateway_error(status))


@pytest.mark.parametrize("status", [408, 504, 524])
def test_timeout_statuses_are_not_retried(llm, status):
    assert not llm._is_transient_error(_gateway_error(status))


def test_a_client_timeout_is_not_retried(llm):
    assert not llm._is_transient_error(_StubAPITimeoutError("timed out"))


def test_a_connection_error_is_retried(llm):
    assert llm._is_transient_error(_StubAPIConnectionError("no answer"))


def test_a_plain_error_is_not_retried(llm):
    assert not llm._is_transient_error(ValueError("boom"))


# --- how _retrying behaves ----------------------------------------------------

def _counting_call(errors):
    """Raise each error in turn, then return a sentinel. Records the attempts."""
    calls = []

    def call():
        calls.append(len(calls) + 1)
        if calls[-1] <= len(errors):
            raise errors[calls[-1] - 1]
        return "answer"

    return call, calls


def test_a_transient_failure_is_retried_until_it_succeeds(llm, monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    call, calls = _counting_call([_gateway_error(503)])
    assert llm._retrying(call, "OpenAIAPI") == "answer"
    assert len(calls) == 2


def test_a_timeout_is_attempted_once(llm, monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    call, calls = _counting_call([_StubAPITimeoutError("timed out")] * 3)
    with pytest.raises(_StubAPITimeoutError):
        llm._retrying(call, "OpenAIAPI")
    assert len(calls) == 1


def test_transient_failures_stop_at_the_attempt_limit(llm, monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    call, calls = _counting_call([_gateway_error(503)] * 5)
    with pytest.raises(Exception):
        llm._retrying(call, "OpenAIAPI")
    assert len(calls) == llm.CHAT_ATTEMPTS


def test_a_slow_transient_failure_is_not_retried(llm, monkeypatch):
    """A failure that already took longer than the budget is not transient in
    any useful sense, so the caller hears about it instead of waiting again."""
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    clock = iter([0, llm.CHAT_RETRY_BUDGET_SECONDS + 1])
    monkeypatch.setattr(llm.time, "monotonic", lambda: next(clock))
    call, calls = _counting_call([_gateway_error(503)] * 3)
    with pytest.raises(Exception):
        llm._retrying(call, "OpenAIAPI")
    assert len(calls) == 1


# --- the wait between attempts follows Retry-After ----------------------------

def _retry_after_error(status, value):
    error = _gateway_error(status)
    error.response = types.SimpleNamespace(headers={"retry-after": value})
    return error


def test_retry_after_in_seconds_is_honoured(llm):
    assert llm._retry_delay(_retry_after_error(429, "5"), 1) == 5.0


def test_retry_after_as_a_date_falls_back_to_the_backoff(llm):
    delay = llm._retry_delay(_retry_after_error(429, "Wed, 21 Oct 2026 07:28:00 GMT"), 1)
    assert delay == llm.CHAT_RETRY_BACKOFF_SECONDS


def test_without_retry_after_the_backoff_grows(llm):
    assert llm._retry_delay(_gateway_error(503), 1) == llm.CHAT_RETRY_BACKOFF_SECONDS
    assert llm._retry_delay(_gateway_error(503), 2) == llm.CHAT_RETRY_BACKOFF_SECONDS * 2


def test_the_retry_waits_as_long_as_the_provider_asked(llm, monkeypatch):
    slept = []
    monkeypatch.setattr(llm.time, "sleep", slept.append)
    call, calls = _counting_call([_retry_after_error(429, "5")])
    assert llm._retrying(call, "OpenAIAPI") == "answer"
    assert slept == [5.0]
    assert len(calls) == 2


def test_a_retry_after_beyond_the_budget_is_not_waited_out(llm, monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    call, calls = _counting_call([_retry_after_error(429, str(llm.CHAT_RETRY_BUDGET_SECONDS + 10))] * 3)
    with pytest.raises(Exception):
        llm._retrying(call, "OpenAIAPI")
    assert len(calls) == 1


# --- two timeouts in a row must both reach the user --------------------------

def test_the_notice_carries_the_time_so_repeats_are_not_identical(llm, monkeypatch):
    """`send` drops a message equal to the last one it sent, so two notices in a
    row have to differ or the second turn goes unanswered."""
    clock = iter(["05:14:17", "05:15:52"])
    monkeypatch.setattr(llm.time, "strftime", lambda fmt: next(clock))
    first = llm._llm_timeout_command()
    second = llm._llm_timeout_command()
    assert "05:14:17" in first and "05:15:52" in second
    assert first != second
