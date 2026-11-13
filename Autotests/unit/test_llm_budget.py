"""Unit tests for LLM token-budget handling in providers/ (no container, network or token)."""
import importlib.util
import logging
import os
import sys
import types
from types import SimpleNamespace as NS

import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_PROVIDERS_DIR = os.path.join(_REPO_ROOT, "providers")
_SRC_DIR = os.path.join(_REPO_ROOT, "src")

if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _exec(name, path, register):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if register:
        sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_modules():
    openai_stub = types.ModuleType("openai")
    openai_stub.OpenAI = object

    config_stub = types.ModuleType("config")
    config_stub.config_get_by_key = lambda key, default=None: default

    stubs = {"openai": openai_stub, "config": config_stub}
    saved = {name: sys.modules.get(name) for name in list(stubs) + ["providers", "lib_llm_ext"]}
    sys.modules.update(stubs)
    try:
        loaded = {"providers": _exec("providers", os.path.join(_SRC_DIR, "providers.py"), True)}
        for name in ("lib_llm_ext", "openrouter", "openai_provider", "asione"):
            file_name = "omega_openai.py" if name == "openai_provider" else f"{name}.py"
            loaded[name] = _exec(name, os.path.join(_PROVIDERS_DIR, file_name), name == "lib_llm_ext")
        return loaded
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


_MODULES = _load_modules()
P = _MODULES["providers"]
llm = _MODULES["lib_llm_ext"]
openrouter = _MODULES["openrouter"]
openai_provider = _MODULES["openai_provider"]
asione = _MODULES["asione"]
IDLE_MESSAGE = "[NO NEW USER INPUT. CONTINUE AUTONOMOUS WORK.]"


@pytest.fixture(autouse=True)
def no_pending_limit_notice():
    llm._limit_notice_pending = False
SEND = (P.LLMTool().with_name("send").with_description("Send a message to the user")
        .add_parameter(P.LLMToolParameter().with_name("content")))


def make_request(
    max_tokens=6000,
    reasoning="medium",
    content="Write an empty line to /tmp/paths.txt",
):
    return P.llmRequest(P.llmRequestMessage("system", "You are an agent."),
                        [P.llmRequestMessage("user", content)],
                        max_tokens, reasoning, [SEND])


def tool_call(call_id, name, arguments):
    return NS(id=call_id, type="function", function=NS(name=name, arguments=arguments))


def chat_response(tool_calls, finish_reason, completion_tokens=6000, reasoning_tokens=6000,
                  response_id="chatcmpl-8f3a2c1d9e7b4a6c"):
    return NS(
        id=response_id,
        choices=[NS(index=0, finish_reason=finish_reason,
                    message=NS(role="assistant", content=None, tool_calls=tool_calls))],
        usage=NS(prompt_tokens=2900, completion_tokens=completion_tokens, total_tokens=2900 + completion_tokens,
                 prompt_tokens_details=NS(cached_tokens=2600),
                 completion_tokens_details=NS(reasoning_tokens=reasoning_tokens)),
    )


def function_call(item_id, name, arguments):
    return NS(type="function_call", id=item_id, call_id="call_" + item_id[3:], name=name,
              arguments=arguments, status="completed")


def reasoning_item():
    return NS(type="reasoning", id="rs_0c889d49c22b6f01006abbb9", summary=[])


def responses_response(output, status, reason=None, output_tokens=120, reasoning_tokens=120,
                       response_id="resp_0c889d49c22b6f01006abbb943f13487d282b88815139a52"):
    return NS(
        id=response_id,
        output=output,
        status=status,
        incomplete_details=NS(reason=reason) if reason else None,
        usage=NS(input_tokens=1200, output_tokens=output_tokens, total_tokens=1200 + output_tokens,
                 input_tokens_details=NS(cached_tokens=0),
                 output_tokens_details=NS(reasoning_tokens=reasoning_tokens)),
    )


class FakeCreate:
    """Returns the queued responses in order and records every call's kwargs."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_openrouter(create, model="z-ai/glm-5.2"):
    provider = openrouter.OpenRouterProviderImpl("OpenRouter", "OPENROUTER_API_KEY", model, "https://openrouter.ai/api/v1")
    provider._client = NS(chat=NS(completions=NS(create=create)))
    return provider


def make_anthropic(create):
    provider = llm.AIProvider("Anthropic", "ANTHROPIC_API_KEY", "claude-opus-4-8", "https://api.anthropic.com/v1/")
    provider._client = NS(chat=NS(completions=NS(create=create)))
    return provider


def make_openai(create):
    provider = openai_provider.OpenAIProviderImpl("OpenAI", "OPENAI_API_KEY", "gpt-5.5", "https://api.openai.com/v1")
    provider._client = NS(responses=NS(create=create))
    return provider


def make_asione(create):
    provider = asione.ASIOneProviderImpl("ASIOne", "ASIONE_API_KEY", "asi1-ultra", "https://api.asi1.ai/v1")
    provider._client = NS(chat=NS(completions=NS(create=create)))
    return provider


def calls_of(response):
    return [(call.name, call.arguments) for call in response.calls]


def swallowed_errors(caplog):
    return [r for r in caplog.records if r.exc_info]


def assert_limit_notice(response):
    assert response.calls == []
    assert response.error is None
    assert response.output_limit_reached is True
    assert response.limit_notice == llm.LLM_OUTPUT_LIMIT_MARKER
    assert llm.llmLimitNotice(response) == llm.LLM_EMPTY_RESPONSE_MESSAGE


def assert_no_limit_notice(response):
    assert response.calls == []
    assert response.error is None
    assert response.output_limit_reached is True
    assert response.limit_notice == ""
    assert llm.llmLimitNotice(response) == ""


def test_normal_reply_is_returned_after_a_single_call():
    create = FakeCreate(chat_response([tool_call("call_1", "send", '{"content": "hi"}')], "tool_calls",
                                      completion_tokens=40, reasoning_tokens=30))
    assert calls_of(make_openrouter(create).chat(make_request())) == [("send", {"content": "hi"})]
    assert len(create.calls) == 1


def test_empty_reply_out_of_budget_is_explained():
    create = FakeCreate(chat_response(None, "length"))
    assert_limit_notice(make_openrouter(create).chat(make_request()))


def test_empty_reply_with_stop_is_not_blamed_on_the_budget(caplog):
    create = FakeCreate(chat_response(None, "stop", completion_tokens=0, reasoning_tokens=0))
    response = make_openrouter(create).chat(make_request())
    assert response.calls == []
    assert response.error is None
    assert swallowed_errors(caplog) == []


@pytest.mark.parametrize("output", [None, [], [reasoning_item()]])
def test_openai_empty_reply_out_of_budget_is_explained(output):
    create = FakeCreate(responses_response(output, "incomplete", "max_output_tokens"))
    assert_limit_notice(make_openai(create).chat(make_request(max_tokens=120)))


def test_openai_empty_reply_without_incomplete_reason_returns_empty(caplog):
    create = FakeCreate(responses_response([reasoning_item()], "completed", output_tokens=0, reasoning_tokens=0))
    response = make_openai(create).chat(make_request())
    assert response.calls == []
    assert response.error is None
    assert swallowed_errors(caplog) == []


def test_asione_empty_reply_out_of_budget_is_explained():
    create = FakeCreate(chat_response(None, "length"))
    assert_limit_notice(make_asione(create).chat(make_request()))


@pytest.mark.parametrize("make, response", [
    (make_openrouter, lambda: chat_response(None, "length")),
    (make_asione, lambda: chat_response(None, "length")),
    (make_openai, lambda: responses_response([], "incomplete", "max_output_tokens")),
])
@pytest.mark.parametrize("content", ["", IDLE_MESSAGE])
def test_empty_reply_out_of_budget_without_a_user_message_sends_nothing(
    make, response, content
):
    provider = make(FakeCreate(response()))
    result = provider.chat(make_request(content=content))
    assert_no_limit_notice(result)


def test_limit_notice_comes_once_after_a_step_without_an_answer():
    provider = make_openrouter(FakeCreate(
        chat_response(
            [tool_call("call_query", "query", '{"query": "hash maps"}')],
            "length",
        ),
        chat_response(None, "length"),
        chat_response(None, "length"),
    ))
    response = provider.chat(make_request())
    assert calls_of(response) == [("query", {"query": "hash maps"})]
    assert response.error is None
    assert response.limit_notice == ""
    assert llm.llmLimitNotice(response) == ""
    assert_limit_notice(provider.chat(make_request(content=IDLE_MESSAGE)))
    assert_no_limit_notice(provider.chat(make_request(content=IDLE_MESSAGE)))


@pytest.mark.parametrize("preceding_calls", [
    [],
    [tool_call("call_query", "query", '{"query": "x"}')],
], ids=["send", "query_then_send"])
def test_limit_notice_is_skipped_once_the_user_got_an_answer(preceding_calls):
    calls = preceding_calls + [
        tool_call("call_send", "send", '{"content": "hi"}'),
    ]
    provider = make_openrouter(FakeCreate(
        chat_response(calls, "tool_calls"),
        chat_response(None, "length"),
    ))
    response = provider.chat(make_request())
    expected = [("query", {"query": "x"})] if preceding_calls else []
    assert calls_of(response) == expected + [("send", {"content": "hi"})]
    assert response.error is None
    assert llm.llmLimitNotice(response) == ""
    assert_no_limit_notice(provider.chat(make_request(content=IDLE_MESSAGE)))


def test_every_user_message_cut_by_the_limit_gets_its_own_notice():
    provider = make_openrouter(FakeCreate(*(chat_response(None, "length") for _ in range(4))))
    assert_limit_notice(provider.chat(make_request()))
    assert_no_limit_notice(provider.chat(make_request(content=IDLE_MESSAGE)))
    assert_limit_notice(provider.chat(make_request()))
    assert_no_limit_notice(provider.chat(make_request(content=IDLE_MESSAGE)))


@pytest.mark.parametrize("make, raw", [
    (make_anthropic, chat_response(None, "length", response_id="msg_011CfXndPVaGDxcDvUYYQix7")),
    (make_openrouter, chat_response(None, "length", response_id="gen-1790687552-MJzliERx3wnTcsh78Ec3")),
    (make_asione, chat_response(None, "length", response_id="chatcmpl-52715fd4-f334-454f-b192-9924424d61f3")),
    (make_openai, responses_response([reasoning_item()], "incomplete", "max_output_tokens")),
], ids=["anthropic", "openrouter", "asione", "openai"])
def test_limit_notice_is_returned_by_each_provider(make, raw):
    response = make(FakeCreate(raw)).chat(make_request())
    assert_limit_notice(response)


@pytest.mark.parametrize("effort, max_tokens, want_budget, want_enabled", [
    ("medium", 6000, 3000, True),
    ("high", 6000, 4800, True),
    ("medium", 120, 60, True),
    ("none", 6000, 0, False),
])
def test_asione_reasoning_budget(effort, max_tokens, want_budget, want_enabled):
    create = FakeCreate(chat_response([tool_call("call_1", "send", '{"content": "hi"}')], "tool_calls",
                                      completion_tokens=40, reasoning_tokens=30))
    make_asione(create).chat(make_request(max_tokens=max_tokens, reasoning=effort))
    body = create.calls[0]["extra_body"]
    assert body["thinking_budget"] == want_budget
    assert body["enable_thinking"] is want_enabled


@pytest.mark.parametrize("effort, want", [
    ("medium", {"enabled": True, "effort": "medium", "exclude": True}),
    ("none", {"enabled": False, "effort": "none", "exclude": True}),
])
def test_openrouter_reasoning_body(effort, want):
    create = FakeCreate(chat_response([tool_call("call_1", "send", '{"content": "hi"}')], "tool_calls",
                                      completion_tokens=40, reasoning_tokens=30))
    make_openrouter(create).chat(make_request(reasoning=effort))
    assert create.calls[0]["extra_body"]["reasoning"] == want


def test_usage_is_logged_at_info(caplog):
    caplog.set_level(logging.INFO)
    create = FakeCreate(chat_response([tool_call("call_1", "send", '{"content": "hi"}')], "tool_calls",
                                      completion_tokens=40, reasoning_tokens=30))
    make_openrouter(create).chat(make_request())
    usage = [r for r in caplog.records if "[LLM_USAGE]" in r.getMessage()]
    assert usage and all(r.levelno == logging.INFO for r in usage)
    assert "finish_reason=tool_calls" in usage[0].getMessage()


def test_openai_usage_is_logged_at_info(caplog):
    caplog.set_level(logging.INFO)
    create = FakeCreate(responses_response([function_call("fc_0a91f2f3ca744bea", "send", '{"content": "hi"}')],
                                           "completed", output_tokens=40, reasoning_tokens=30))
    make_openai(create).chat(make_request())
    usage = [r for r in caplog.records if "[LLM_USAGE]" in r.getMessage()]
    assert usage and all(r.levelno == logging.INFO for r in usage)


def test_api_error_is_reported_in_the_response():
    create = FakeCreate(RuntimeError("401 invalid api key"))
    response = make_openrouter(create).chat(make_request())
    assert response.calls == []
    assert "401 invalid api key" in response.error
