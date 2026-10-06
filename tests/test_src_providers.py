import providers
from providers import *

def test_validate_repsonse_no_tool():
    tool = (LLMTool().with_name('foo')
            .with_description('Test tool')
            .add_parameter(LLMToolParameter().with_name('bar')))
    request = LLMRequest().add_tool(tool)
    response = LLMResponse().add_tool_call(LLMToolCall().with_name('foo')
                                           .with_id('call#0')
                                           .add_argument('bar', 'test'))
    response = LLMResponse().add_tool_call(LLMToolCall().with_name('foo')
                                           .with_id('call#0')
                                           .add_argument('bar', 'test')
                                           .with_tool(tool))
    assert providers._validate_response(request, response) == expected

def test_validate_repsonse_no_tool():
    request = LLMRequest().add_tool(LLMTool().with_name('foo')
                                    .with_description('Test tool')
                                    .add_parameter(LLMToolParameter().with_name('bar')))
    response = LLMResponse().add_tool_call(LLMToolCall().with_name('baz'))
    expected = LLMResponse().add_tool_call(LLMToolCall().with_name('baz')
                                           .with_error("Unknown tool: 'baz'"))
    assert providers._validate_response(request, response) == expected

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
