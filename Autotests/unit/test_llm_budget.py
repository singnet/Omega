"""Unit tests for LLM token-budget handling in providers/ (no container, network or token)."""
import importlib.util
import json
import logging
import os
import sys
import types
from types import SimpleNamespace as NS

import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_PROVIDERS_DIR = os.path.join(_REPO_ROOT, "providers")

if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _load_modules():
    openai_stub = types.ModuleType("openai")
    openai_stub.OpenAI = object

    config_stub = types.ModuleType("config")
    config_stub.config_get_by_key = lambda key, default=None: default

    providers_stub = types.ModuleType("providers")
    providers_stub.LLMProvider = object
    providers_stub.registerLLMProvider = lambda name, provider: None

    stubs = {"openai": openai_stub, "config": config_stub, "providers": providers_stub}
    saved = {name: sys.modules.get(name) for name in list(stubs) + ["lib_llm_ext"]}
    sys.modules.update(stubs)
    try:
        loaded = {}
        for name in ("lib_llm_ext", "openrouter", "openai_provider", "asione"):
            file_name = "openai.py" if name == "openai_provider" else f"{name}.py"
            spec = importlib.util.spec_from_file_location(name, os.path.join(_PROVIDERS_DIR, file_name))
            module = importlib.util.module_from_spec(spec)
            if name == "lib_llm_ext":
                sys.modules["lib_llm_ext"] = module
            spec.loader.exec_module(module)
            loaded[name] = module
        return loaded
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


_MODULES = _load_modules()
llm = _MODULES["lib_llm_ext"]
openrouter = _MODULES["openrouter"]
openai_provider = _MODULES["openai_provider"]
asione = _MODULES["asione"]

PROMPT = "You are an agent. :-:-:-: Write an empty line to /tmp/paths.txt"


def chat_response(content, finish_reason, completion_tokens=6000, reasoning_tokens=6000):
    return NS(
        choices=[NS(index=0, finish_reason=finish_reason,
                    message=NS(role="assistant", content=content))],
        usage=NS(prompt_tokens=2900, completion_tokens=completion_tokens, total_tokens=2900 + completion_tokens,
                 prompt_tokens_details=NS(cached_tokens=2600),
                 completion_tokens_details=NS(reasoning_tokens=reasoning_tokens)),
    )


def responses_response(output_text, status, reason=None, output_tokens=120, reasoning_tokens=120):
    return NS(
        output_text=output_text,
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


def make_openai(create):
    provider = openai_provider.OpenAIProviderImpl("OpenAI", "OPENAI_API_KEY", "gpt-5.5", "https://api.openai.com/v1")
    provider._client = NS(responses=NS(create=create))
    return provider


def make_asione(create):
    provider = asione.ASIOneProviderImpl("ASIOne", "ASIONE_API_KEY", "asi1-ultra", "https://api.asi1.ai/v1")
    provider._client = NS(chat=NS(completions=NS(create=create)))
    return provider


def sent_text(reply):
    """Text of a single `(send "...")` command, or None if reply is not one."""
    if not (reply.startswith("(send ") and reply.endswith(")")):
        return None
    return json.loads(reply[len("(send "):-1])


def swallowed_errors(caplog):
    return [r for r in caplog.records if r.exc_info]


def test_normal_reply_is_returned_after_a_single_call():
    create = FakeCreate(chat_response('(send "hi")', "stop", completion_tokens=40, reasoning_tokens=30))
    assert make_openrouter(create).chat(PROMPT) == '(send "hi")'
    assert len(create.calls) == 1


def test_empty_reply_out_of_budget_is_explained():
    create = FakeCreate(chat_response("", "length"))
    assert sent_text(make_openrouter(create).chat(PROMPT)) == llm.LLM_EMPTY_RESPONSE_MESSAGE


def test_empty_reply_with_stop_is_not_blamed_on_the_budget(caplog):
    create = FakeCreate(chat_response("", "stop", completion_tokens=0, reasoning_tokens=0))
    assert make_openrouter(create).chat(PROMPT) == ""
    assert swallowed_errors(caplog) == []


def test_openai_empty_reply_out_of_budget_is_explained():
    create = FakeCreate(responses_response("", "incomplete", "max_output_tokens"))
    assert sent_text(make_openai(create).chat(PROMPT, max_tokens=120)) == llm.LLM_EMPTY_RESPONSE_MESSAGE


def test_openai_empty_reply_without_incomplete_reason_returns_empty(caplog):
    create = FakeCreate(responses_response("", "completed", output_tokens=0, reasoning_tokens=0))
    assert make_openai(create).chat(PROMPT) == ""
    assert swallowed_errors(caplog) == []


def test_asione_empty_reply_out_of_budget_is_explained():
    create = FakeCreate(chat_response("", "length"))
    assert sent_text(make_asione(create).chat(PROMPT)) == llm.LLM_EMPTY_RESPONSE_MESSAGE


@pytest.mark.parametrize("effort, max_tokens, want_budget, want_enabled", [
    ("medium", 6000, 3000, True),
    ("high", 6000, 4800, True),
    ("medium", 120, 60, True),
    ("none", 6000, 0, False),
])
def test_asione_reasoning_budget(effort, max_tokens, want_budget, want_enabled):
    create = FakeCreate(chat_response('(send "hi")', "stop", completion_tokens=40, reasoning_tokens=30))
    make_asione(create).chat(PROMPT, max_tokens=max_tokens, reasoning=effort)
    body = create.calls[0]["extra_body"]
    assert body["thinking_budget"] == want_budget
    assert body["enable_thinking"] is want_enabled


@pytest.mark.parametrize("effort, want", [
    ("medium", {"enabled": True, "effort": "medium", "exclude": True}),
    ("none", {"enabled": False, "effort": "none", "exclude": True}),
])
def test_openrouter_reasoning_body(effort, want):
    create = FakeCreate(chat_response('(send "hi")', "stop", completion_tokens=40, reasoning_tokens=30))
    make_openrouter(create).chat(PROMPT, reasoning=effort)
    assert create.calls[0]["extra_body"]["reasoning"] == want


def test_usage_is_logged_at_info(caplog):
    caplog.set_level(logging.INFO)
    create = FakeCreate(chat_response('(send "hi")', "stop", completion_tokens=40, reasoning_tokens=30))
    make_openrouter(create).chat(PROMPT)
    usage = [r for r in caplog.records if "[LLM_USAGE]" in r.getMessage()]
    assert usage and all(r.levelno == logging.INFO for r in usage)
    assert "finish_reason=stop" in usage[0].getMessage()


def test_openai_usage_is_logged_at_info(caplog):
    caplog.set_level(logging.INFO)
    create = FakeCreate(responses_response('(send "hi")', "completed", output_tokens=40, reasoning_tokens=30))
    make_openai(create).chat(PROMPT)
    usage = [r for r in caplog.records if "[LLM_USAGE]" in r.getMessage()]
    assert usage and all(r.levelno == logging.INFO for r in usage)


def test_api_error_returns_empty_string():
    create = FakeCreate(RuntimeError("401 invalid api key"))
    assert make_openrouter(create).chat(PROMPT) == ""
