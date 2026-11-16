"""Offline coverage of Responses output carried through native messages."""
import importlib.util
import json
import sys
import types
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def modules(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root))
    openai = types.ModuleType("openai")
    openai.OpenAI = object
    config = types.ModuleType("config")
    config.config_get_by_key = lambda key, default=None: default
    monkeypatch.setitem(sys.modules, "openai", openai)
    monkeypatch.setitem(sys.modules, "config", config)
    loaded = {}
    for name, path in (("providers", "src/providers.py"),
                       ("lib_llm_ext", "providers/lib_llm_ext.py"),
                       ("omega_openai", "providers/omega_openai.py")):
        spec = importlib.util.spec_from_file_location(name, root / path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        loaded[name] = module
    return NS(p=loaded["providers"],
              chat=loaded["lib_llm_ext"].AIProvider("Compatible", "UNUSED", "fixture", ""),
              responses=loaded["omega_openai"].OpenAIProviderImpl("OpenAI", "UNUSED", "fixture", ""))


def output_item(fields):
    return NS(**fields, model_dump=lambda **kwargs: deepcopy(fields))


def follow_up(p, response):
    return (p.LLMRequest()
            .with_messages([p.llmRequestMessage("system", "offline context"),
                            p.llmResponseMessage(response)] + [
                p.llmToolCallResponseMessage("tool", call.id, "PIN-SUCCESS")
                for call in response.calls]))


@pytest.mark.parametrize("parallel", [False, True])
def test_responses_round_trip_preserves_output(modules, parallel):
    p = modules.p
    output = [
        dict(type="reasoning", id="rs_opaque", summary=[],
             encrypted_content="opaque-offline-fixture"),
        dict(type="function_call", id="fc_item_42", call_id="call_actual_73",
             name="pin", arguments='{"message":"value"}', status="completed"),
    ]
    ids = ["call_actual_73"]
    if parallel:
        output += [
            dict(type="reasoning", id="rs_second", summary=[], encrypted_content="opaque-second"),
            dict(type="function_call", id="fc_item_43", call_id="call_actual_74",
                 name="pin", arguments='{"message":"second"}', status="completed"),
            dict(type="message", id="msg_note", role="assistant", status="completed",
                 content=[dict(type="output_text", text="A note", annotations=[])]),
        ]
        ids.append("call_actual_74")
    tools = p.getTools([("pin", "Pin a message", ["message"])])
    raw = NS(output=[output_item(item) for item in output])
    response = p._validate_response(p.LLMRequest().with_tools(tools),
                                    modules.responses.convert_response(raw))
    assert [call.id for call in response.calls] == ids
    assert all(call_id in p.llmResponseToSExpr(response) for call_id in ids)
    wire = modules.responses.convert_request(follow_up(p, response))
    assert wire["input"][1:1 + len(output)] == output
    calls = [item for item in wire["input"] if item.get("type") == "function_call"]
    results = [item for item in wire["input"] if item.get("type") == "function_call_output"]
    assert [item["call_id"] for item in calls] == ids
    assert [item["call_id"] for item in results] == ids
    assert all(item["call_id"] != "fc_item_42" for item in calls + results)
    assert len(calls) == len(response.calls)
    assert modules.responses.convert_request(follow_up(p, response)) == wire


def test_response_message_keeps_existing_provider_conversion(modules):
    p = modules.p
    call = p.LLMToolCall().with_id("call_generic").with_name("pin").with_arguments({"message": "x"})
    response = p.LLMResponse().add_tool_call(call)
    request = follow_up(p, response)
    legacy = follow_up(p, response)
    legacy.messages[1] = p.llmToolCallMessage("assistant", response.calls, "[TOOL CALL]")
    assert modules.chat.convert_request(request) == modules.chat.convert_request(legacy)
    assert modules.responses.convert_request(request) == modules.responses.convert_request(legacy)
    expected = modules.chat.convert_request(request)
    response.with_provider_data({"openai_responses": [output_item(dict(type="reasoning", id="rs"))]})
    assert modules.chat.convert_request(follow_up(p, response)) == expected


def test_responses_replay_keeps_local_fallback_call(modules):
    p = modules.p
    reasoning = dict(type="reasoning", id="rs_opaque", summary=[], encrypted_content="opaque")
    raw = NS(output=[output_item(reasoning)], incomplete_details=NS(reason="max_output_tokens"))
    response = modules.responses.convert_response(raw)
    wire = modules.responses.convert_request(follow_up(p, response))
    assert wire["input"][1] == reasoning
    call = wire["input"][2]
    result = wire["input"][3]
    assert call["type"] == "function_call"
    assert call["name"] == "send"
    assert json.loads(call["arguments"]) == response.calls[0].arguments
    assert call["call_id"] == result["call_id"] == response.calls[0].id
