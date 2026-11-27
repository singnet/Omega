from unittest.mock import Mock

import providers


def serialize_mock_response(monkeypatch, name, call_id):
    request = providers.LLMRequest().add_tool(providers.LLMTool().with_name("nop"))
    call = providers.LLMToolCall().with_name(name).with_id(call_id)
    provider = Mock(spec=providers.LLMProvider)
    provider.chat.return_value = providers.LLMResponse().add_tool_call(call)
    monkeypatch.setattr(providers, "_llmprovider", provider)
    return providers.llmResponseToSExpr(providers.llmProviderChat(request))


def test_expression_in_unknown_tool_name_is_a_string(monkeypatch):
    result = serialize_mock_response(monkeypatch, "(+ 20 22)", "call-1")
    assert result == """(("call-1" (Error ("(+ 20 22)") "Unknown tool: '(+ 20 22)'")))"""


def test_expression_in_valid_tool_call_id_is_a_string(monkeypatch):
    result = serialize_mock_response(monkeypatch, "nop", "(+ 20 22)")
    assert result == '(("(+ 20 22)" ("nop")))'
