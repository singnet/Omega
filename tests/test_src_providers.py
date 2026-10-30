import pytest

import providers
from providers import *


def _tool(name, *params):
    tool = LLMTool().with_name(name).with_description(f"{name} tool")
    for param in params:
        tool.add_parameter(LLMToolParameter().with_name(param))
    return tool


def _call(callid, name, **arguments):
    return LLMToolCall().with_name(name).with_id(callid).with_arguments(dict(arguments))


def _request(episodes):
    return llmRequest(llmRequestMessage("system", "prompt"), episodes, 100, "medium", [])


def _tool_results(request):
    return [(m.callid, m.content) for m in request.messages if isinstance(m, LLMToolCallResponseMessage)]


NON_STRINGS = pytest.mark.parametrize("value", [42, 4.2, True, None, ["a"], {"k": "v"}],
                                      ids=["int", "float", "bool", "none", "list", "dict"])


def test_validate_response_valid_call():
    tool = _tool('foo', 'bar')
    request = LLMRequest().add_tool(tool)
    response = LLMResponse().add_tool_call(_call('call#0', 'foo', bar='test'))
    call = providers._validate_response(request, response).calls[0]
    assert call.error is None
    assert call.tool is tool


def test_validate_response_no_tool():
    request = LLMRequest().add_tool(_tool('foo', 'bar'))
    response = LLMResponse().add_tool_call(LLMToolCall().with_name('baz'))
    expected = LLMResponse().add_tool_call(LLMToolCall().with_name('baz')
                                           .with_error("Unknown tool: 'baz'"))
    assert providers._validate_response(request, response) == expected

def test_validate_response_no_tool_call():
    request = LLMRequest().add_tool(_tool('foo', 'bar'))
    response = LLMResponse()
    expected = LLMResponse().with_error("List of tool calls is empty")
    assert providers._validate_response(request, response) == expected


@NON_STRINGS
def test_validate_response_rejects_non_string_argument(value):
    request = LLMRequest().add_tool(_tool('foo', 'bar'))
    response = LLMResponse().add_tool_call(_call('call#0', 'foo', bar=value))
    call = providers._validate_response(request, response).calls[0]
    assert call.is_error()
    assert "'bar'" in call.error


@NON_STRINGS
def test_non_string_argument_becomes_error_call_in_sexpr(value):
    request = LLMRequest().add_tool(_tool('foo', 'bar'))
    response = providers._validate_response(
        request, LLMResponse().add_tool_call(_call('call#0', 'foo', bar=value)))
    assert llmResponseToSExpr(response).startswith('((call#0 (Error (foo "')


def test_non_string_argument_is_escaped_in_error_sexpr():
    request = LLMRequest().add_tool(_tool('foo', 'bar'))
    response = providers._validate_response(
        request, LLMResponse().add_tool_call(_call('call#0', 'foo', bar=["a"])))
    assert '(foo "[\\"a\\"]")' in llmResponseToSExpr(response)


def test_error_that_is_not_a_string_is_converted_in_sexpr():
    call = _call('call#0', 'foo').with_error(ValueError("bad value"))
    assert llmToolCallToSExpr(call) == '(call#0 (Error (foo) "bad value"))'


def test_llm_tool_call_to_sexpr():
    tool = (LLMTool().with_name('foo')
            .with_description('Test tool')
            .add_parameter(LLMToolParameter().with_name('bar')))
    call = (LLMToolCall().with_name('foo')
            .with_id('call#0')
            .add_argument('bar', 'test'))
    call.set_tool(tool)
    assert llmToolCallToSExpr(call) == '(call#0 (foo "test"))'


def test_llm_tool_call_to_sexpr_escape():
    tool = (LLMTool().with_name('foo')
            .with_description('Test tool')
            .add_parameter(LLMToolParameter().with_name('bar')))
    call = (LLMToolCall().with_name('foo')
            .with_id('call#0')
            .add_argument('bar', 'test"\\'))
    call.set_tool(tool)
    assert llmToolCallToSExpr(call) == '(call#0 (foo "test\\"\\\\"))'


def test_error_text_is_escaped_in_sexpr():
    call = _call('call#0', 'foo').with_error('Invalid \\uXXXX escape: "x"')
    assert llmToolCallToSExpr(call) == '(call#0 (Error (foo) "Invalid \\\\uXXXX escape: \\"x\\""))'


def test_get_tools_does_not_deduplicate_tools():
    tools = getTools([("send", "Send v1", ["content"]),
                      ("pin", "Pin", ["message"]),
                      ("send", "Send v2", ["content"])])
    assert [tool.name for tool in tools] == ["send", "pin", "send"]
    assert tools[0].description == "Send v1"
    assert tools[2].description == "Send v2"


def test_request_does_not_add_a_result_for_a_call_without_one():
    calls = [_call("call_a", "read-file", filename="/tmp/missing"), _call("call_b", "send", content="hi")]
    request = _request([llmToolCallMessage("assistant", calls, "[TOOL CALL]"),
                        llmToolCallResponseMessage("tool", "call_b", "SUCCESS, RETURN: None"),
                        llmRequestMessage("user", "next")])
    results = _tool_results(request)
    assert [callid for callid, _ in results] == ["call_b"]
    assert results[0][1] == "SUCCESS, RETURN: None"
    assert [m.role for m in request.messages] == ["system", "assistant", "tool", "user"]


def test_request_does_not_merge_results_that_share_a_call_id():
    calls = [_call("call_a", "metta", sexpression="(superpose (1 2 3))")]
    request = _request([llmToolCallMessage("assistant", calls, "[TOOL CALL]"),
                        llmToolCallResponseMessage("tool", "call_a", 'SUCCESS, RETURN: "1"'),
                        llmToolCallResponseMessage("tool", "call_a", 'SUCCESS, RETURN: "2"'),
                        llmToolCallResponseMessage("tool", "call_a", 'SUCCESS, RETURN: "3"'),
                        llmRequestMessage("user", "next")])
    results = _tool_results(request)
    assert [callid for callid, _ in results] == ["call_a", "call_a", "call_a"]
    assert results[0][1] == 'SUCCESS, RETURN: "1"'
    assert results[1][1] == 'SUCCESS, RETURN: "2"'
    assert results[2][1] == 'SUCCESS, RETURN: "3"'


def test_request_keeps_paired_results_as_they_are():
    calls = [_call("call_a", "pin", message="x"), _call("call_b", "send", content="hi")]
    request = _request([llmToolCallMessage("assistant", calls, "[TOOL CALL]"),
                        llmToolCallResponseMessage("tool", "call_a", "PIN-SUCCESS"),
                        llmToolCallResponseMessage("tool", "call_b", "SUCCESS, RETURN: None"),
                        llmRequestMessage("user", "next")])
    assert _tool_results(request) == [("call_a", "PIN-SUCCESS"), ("call_b", "SUCCESS, RETURN: None")]
    assert [m.role for m in request.messages] == ["system", "assistant", "tool", "tool", "user"]


def test_request_does_not_drop_an_assistant_message_without_calls():
    request = _request([llmToolCallMessage("assistant", [], "[TOOL CALL]"),
                        llmRequestMessage("user", "next")])
    assert [m.role for m in request.messages] == ["system", "assistant", "user"]


def test_request_does_not_drop_a_result_with_an_unknown_call_id():
    request = _request([llmToolCallMessage("assistant", [_call("call_a", "pin", message="x")], "[TOOL CALL]"),
                        llmToolCallResponseMessage("tool", "call_a", "PIN-SUCCESS"),
                        llmToolCallResponseMessage("tool", "call_zzz", "SUCCESS, RETURN: stray"),
                        llmRequestMessage("user", "next")])
    assert _tool_results(request) == [("call_a", "PIN-SUCCESS"), ("call_zzz", "SUCCESS, RETURN: stray")]


def test_request_matches_a_result_whose_call_id_is_not_a_string():
    request = _request([llmToolCallMessage("assistant", [_call("7", "pin", message="x")], "[TOOL CALL]"),
                        llmToolCallResponseMessage("tool", 7, "PIN-SUCCESS"),
                        llmRequestMessage("user", "next")])
    assert [content for _, content in _tool_results(request)] == ["PIN-SUCCESS"]


def test_llm_provider_chat_preserves_provider_exception_as_error(monkeypatch):
    class BrokenProvider:
        def chat(self, request):
            raise RuntimeError("provider exploded")

    monkeypatch.setattr(providers, "_llmprovider", BrokenProvider())

    response = providers.llmProviderChat(_request([]))

    assert response.is_error()
    assert "provider exploded" in str(response.error)


def test_llm_provider_chat_preserves_terminal_exception_status(monkeypatch):
    class AuthenticationError(Exception):
        status_code = 401

    class BrokenProvider:
        def chat(self, request):
            raise AuthenticationError("unauthorized")

    monkeypatch.setattr(providers, "_llmprovider", BrokenProvider())

    response = providers.llmProviderChat(_request([]))

    assert response.is_error()
    assert "unauthorized" in str(response.error)
    assert response.is_terminal_error()
    assert providers.llmResponseIsTerminalError(response)


def test_message_history_retains_last_ten_complete_exchanges():
    history = []

    for number in range(12):
        history = providers.appendAndTrimMessageHistory(
            history, providers.llmRequestMessage("user", f"user-{number}")
        )
        history = providers.appendAndTrimMessageHistory(
            history, providers.llmToolCallMessage("assistant", [], f"assistant-{number}")
        )
        history = providers.appendAndTrimMessageHistory(
            history,
            providers.llmToolCallResponseMessage(
                "tool", f"call-{number}", f"result-{number}"
            ),
        )

    assert len(history) == 30
    assert [history[index].content for index in range(0, 30, 3)] == [
        f"user-{number}" for number in range(2, 12)
    ]
    assert [history[index].content for index in range(1, 30, 3)] == [
        f"assistant-{number}" for number in range(2, 12)
    ]
    assert [history[index].content for index in range(2, 30, 3)] == [
        f"result-{number}" for number in range(2, 12)
    ]


def test_terminal_provider_errors_are_marked_terminal():
    response = LLMResponse().with_error(
        "subscription_sharing_usage_limit_exceeded"
    )
    assert response.is_error()
    assert response.is_terminal_error()
    assert providers.llmResponseIsTerminalError(response)


@pytest.mark.parametrize(
    "message",
    ["budget exceeded", "The account has exceeded budget for this period"],
)
def test_budget_exhaustion_messages_are_terminal(message):
    assert providers._is_terminal_provider_error(RuntimeError(message))


def test_http_authentication_errors_are_terminal():
    class ProviderError(Exception):
        status_code = 401

    assert providers._is_terminal_provider_error(ProviderError("unauthorized"))
    assert providers._is_terminal_provider_error(
        type("ForbiddenError", (Exception,), {"status_code": 403})("forbidden")
    )


def test_transient_rate_limit_is_not_automatically_terminal():
    response = LLMResponse().with_error("rate limit exceeded; please retry")
    assert response.is_error()
    assert not response.is_terminal_error()


def test_terminal_error_can_be_set_explicitly():
    response = LLMResponse().with_error(
        "provider-specific failure", terminal=True
    )
    assert response.is_error()
    assert response.is_terminal_error()


@pytest.mark.parametrize(
    "message",
    [
        "Request failed; previous attempt was unauthorized",
        "Retry later; billing limit message from upstream docs",
    ],
)
def test_unrelated_error_text_does_not_trigger_terminal_classification(message):
    assert not providers._is_terminal_provider_error(RuntimeError(message))
