import os
import sys

import providers

FRAME_TOOLS = {
    'new-frame', 'new-autonomous-frame', 'switch-mode', 'switch-frame',
    'send_probe', 'show-root-frame', 'show-current-frame', 'show-frame-index',
    'show-active-framespace', 'show-completed-framespace', 'show-frame-relation',
    'ctx-add-hypothesis', 'ctx-add-result', 'complete-goals-stm',
    'complete-goals-ltm', 'clear-frame-junk',
}


def prepare_prompt_renderer():
    """Let lib_llm initialize without real credentials; tests make no API calls."""
    os.environ.setdefault('OPENAI_API_KEY', 'context-plugin-test')


def block_frame_backend_import():
    """Simulate an unavailable backend for the startup-failure test."""
    sys.modules['frame_relation'] = None


def unblock_frame_backend_import():
    sys.modules.pop('frame_relation', None)


def result_call(tools):
    request = providers.LLMRequest().with_tools(tools)
    response = providers.LLMResponse().add_tool_call(
        providers.LLMToolCall().with_name('ctx-add-result').with_id('frame-result-1')
        .with_arguments({'variant': 'checked', 'metrics': 'frame tool result'}))
    response = providers._validate_response(request, response)
    assert not response.is_error()
    assert not response.calls[0].is_error()
    return providers.llmResponseToSExpr(response)


def has_completion_tool(tools):
    matches = [tool for tool in tools if tool.name == 'complete-goals-stm']
    return len(matches) == 1 and [p.name for p in matches[0].parameters] == ['summary']


def has_all_frame_tools(tools):
    return FRAME_TOOLS <= {tool.name for tool in tools}


def is_frame_tool(name):
    """Check whether a registered skill belongs to the context plugin."""
    return name in FRAME_TOOLS


def has_no_frame_tools(tools):
    return FRAME_TOOLS.isdisjoint(tool.name for tool in tools)
