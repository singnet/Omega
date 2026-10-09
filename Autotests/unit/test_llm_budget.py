"""Unit tests for LLM token-budget handling in providers/ (no container, network or token)."""
import importlib.util
import logging
import os
import re
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
            file_name = "openai.py" if name == "openai_provider" else f"{name}.py"
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

SEND = (P.LLMTool().with_name("send").with_description("Send a message to the user")
        .add_parameter(P.LLMToolParameter().with_name("content")))
ACCEPTED_CALL_ID = re.compile(r"[a-zA-Z0-9_-]{1,40}")


def make_request(max_tokens=6000, reasoning="medium"):
    return P.llmRequest(P.llmRequestMessage("system", "You are an agent."),
                        [P.llmRequestMessage("user", "Write an empty line to /tmp/paths.txt")],
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


FALLBACK = [("send", {"content": llm.LLM_EMPTY_RESPONSE_MESSAGE})]


def test_normal_reply_is_returned_after_a_single_call():
    create = FakeCreate(chat_response([tool_call("call_1", "send", '{"content": "hi"}')], "tool_calls",
                                      completion_tokens=40, reasoning_tokens=30))
    assert calls_of(make_openrouter(create).chat(make_request())) == [("send", {"content": "hi"})]
    assert len(create.calls) == 1


def test_empty_reply_out_of_budget_is_explained():
    create = FakeCreate(chat_response(None, "length"))
    assert calls_of(make_openrouter(create).chat(make_request())) == FALLBACK


def test_empty_reply_with_stop_is_not_blamed_on_the_budget(caplog):
    create = FakeCreate(chat_response(None, "stop", completion_tokens=0, reasoning_tokens=0))
    response = make_openrouter(create).chat(make_request())
    assert response.calls == []
    assert response.error is None
    assert swallowed_errors(caplog) == []


def test_openai_empty_reply_out_of_budget_is_explained():
    create = FakeCreate(responses_response([reasoning_item()], "incomplete", "max_output_tokens"))
    assert calls_of(make_openai(create).chat(make_request(max_tokens=120))) == FALLBACK


def test_openai_empty_reply_without_incomplete_reason_returns_empty(caplog):
    create = FakeCreate(responses_response([reasoning_item()], "completed", output_tokens=0, reasoning_tokens=0))
    response = make_openai(create).chat(make_request())
    assert response.calls == []
    assert response.error is None
    assert swallowed_errors(caplog) == []


def test_asione_empty_reply_out_of_budget_is_explained():
    create = FakeCreate(chat_response(None, "length"))
    assert calls_of(make_asione(create).chat(make_request())) == FALLBACK


@pytest.mark.parametrize("make, raw", [
    (make_anthropic, chat_response(None, "length", response_id="msg_011CfXndPVaGDxcDvUYYQix7")),
    (make_openrouter, chat_response(None, "length", response_id="gen-1790687552-MJzliERx3wnTcsh78Ec3")),
    (make_asione, chat_response(None, "length", response_id="chatcmpl-52715fd4-f334-454f-b192-9924424d61f3")),
    (make_openai, responses_response([reasoning_item()], "incomplete", "max_output_tokens")),
], ids=["anthropic", "openrouter", "asione", "openai"])
def test_fallback_call_id_is_accepted_by_providers(make, raw):
    response = make(FakeCreate(raw)).chat(make_request())
    assert calls_of(response) == FALLBACK
    assert ACCEPTED_CALL_ID.fullmatch(response.calls[0].id)


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
