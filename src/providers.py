import logging
from typing import List, Self

logger = logging.getLogger(__name__)

_llmProviderRegistry = {}

class LLMTool:

    def __init__(self):
        self.name = None
        self.description = None
        self.parameters = []

    def with_name(self, name):
        self.name = name
        return self

    def with_description(self, description):
        self.description = description
        return self

    def add_parameter(self, parameter):
        self.parameters.append(parameter)
        return self

    def with_parameters(self, parameters):
        self.parameters = parameters
        return self

    def __repr__(self):
        return f"LLMTool[name={self.name!r}, description={self.description!r}, parameters={self.parameters!r}]"

class LLMToolParameter:

    def with_name(self, name):
        self.name = name
        return self

    def __repr__(self):
        return f"LLMToolParameter[name={self.name!r}]"

class LLMToolCall:

    def __init__(self):
        self.name = None
        self.id = None
        self.error = None
        self.arguments = {}
        self.tool = None

    def with_name(self, name):
        self.name = name
        return self

    def with_id(self, id):
        self.id = id
        return self

    def is_error(self):
        return bool(self.error)

    def with_error(self, error):
        self.error = error
        return self

    def set_error(self, error):
        self.error = error

    def add_argument(self, name, value):
        self.arguments[name] = value
        return self

    def with_arguments(self, arguments):
        self.arguments = arguments
        return self

    def set_tool(self, tool: LLMTool):
        self.tool = tool

    def __repr__(self):
        return f"LLMToolCall[id={self.id!r},name={self.name!r},arguments={self.arguments!r},error={self.error!r}]"

    def __eq__(self, other):
        return (self.name == other.name
                and self.id == other.id
                and self.error == other.error
                and self.arguments == other.arguments
                and self.tool == other.tool)

class LLMMessage:

    def __init__(self):
        self.role = None
        self.content = None

    def with_role(self, role):
        self.role = role
        return self

    def with_content(self, content):
        self.content = content
        return self

    def __repr__(self):
        return f"LLMMessage[role={self.role!r},content={self.content!r}]"

class LLMToolCallResponseMessage(LLMMessage):

    def __init__(self):
        super().__init__()
        self.callid = None

    def with_callid(self, callid):
        self.callid = callid
        return self

    def __repr__(self):
        return f"LLMToolCallResponseMessage[role={self.role!r},content={self.content!r},callid={self.callid!r}]"

class LLMToolCallMessage(LLMMessage):

    def __init__(self):
        super().__init__()
        self.calls: [LLMToolCall] = []

    def with_calls(self, calls):
        self.calls = calls
        return self

    def __repr__(self):
        return f"LLMToolCallMessage[role={self.role!r},content={self.content!r},calls={self.calls!r}]"

class LLMRequest:

    def __init__(self):
        self.messages: [LLMMessage] = []
        self.max_tokens = 6000
        self.reasoning_mode = "medium"
        self.tools = []
        self.tool_by_name = {}

    def add_message(self, message):
        self.messages.append(message)
        return self

    def with_messages(self, messages):
        self.messages = messages
        return self

    def with_max_tokens(self, max_tokens):
        self.max_tokens = max_tokens
        return self

    def with_reasoning_mode(self, reasoning_mode):
        self.reasoning_mode = reasoning_mode
        return self

    def with_tools(self, tools: List[LLMTool]):
        self.tools = tools
        self.tool_by_name = { t.name: t for t in tools }
        return self

    def has_tool(self, name):
        return name in self.tool_by_name

    def get_tool(self, name):
        return self.tool_by_name.get(name, None)

    def __repr__(self):
        return f"LLMRequest[messages={self.messages!r}, max_tokens={self.max_tokens!r}, reasoning_mode={self.reasoning_mode!r}, tools={self.tools!r}]"

class LLMResponse:

    def __init__(self):
        self.calls: List[LLMToolCall] = []
        self.error = None

    def add_tool_call(self, call: LLMToolCall) -> Self:
        self.calls.append(call)
        return self

    def with_error(self, error: str) -> Self:
        self.error = error
        return self

    def __repr__(self):
        return f"LLMResponse[calls={self.calls!r},error={self.error!r}]"

    def __eq__(self, other):
        return self.calls == other.calls and self.error == other.error

class LLMProvider:
    """LLM provider implementation"""

    def start(self) -> None:
        """Configure and start LLM provider"""
        pass

    def stop(self) -> None:
        """Stop and LLM provider and free resources"""
        pass

    def chat(self, request: LLMRequest) -> LLMResponse:
        """Chat with LLM provider"""
        raise NotImplementedError()

def registerLLMProvider(id: str, provider: LLMProvider) -> None:
    """
    Register LLM provider in the registry.

    Arguments:
    id: the identifier of the plugin which is used to load it
    provider: the implementation of the provider
    """
    global _llmProviderRegistry
    logger.info(f"registerLLMProvider: registering LLM provider {id}")
    _llmProviderRegistry[id] = provider

_llmprovider: LLMProvider = None

def llmProviderStart(provider):
    """Select and start one of the LLM providers registered by plugins"""
    global _llmprovider
    _llmprovider = _llmProviderRegistry.get(provider, None)
    if _llmprovider is None:
        error = f"llmProviderStart: LLM provider plugin {provider} is not registered"
        logger.error(error)
        raise RuntimeError(error)
    _llmprovider.start()

def llmProviderChat(request):
    """Chat via selected LLM provider"""
    global _llmprovider
    try:
        response = _llmprovider.chat(request)
        return _validate_response(request, response)
    except Exception:
        logger.exception("Exception while getting LLM response")
        return LLMResponse()

def _validate_response(request: LLMRequest, response: LLMResponse) -> LLMResponse:
    for call in response.calls:
        if call.is_error():
            continue
        if not request.has_tool(call.name):
            call.set_error(f"Unknown tool: {call.name!r}")
        call.set_tool(request.get_tool(call.name))
        for parameter in call.tool.parameters:
            if not parameter.name in call.arguments:
                call.set_error(f"Call tool parameter is not set: tool: {call.name!r}, parameter: {parameter.name!r}")
                break
    return response

def getTools(skills):
    """Form a list of tools for LLM from the list of skills"""
    tools = []
    for name, desc, params in skills:
        tool = LLMTool().with_name(name).with_description(desc)
        for param in params:
            tool.add_parameter(LLMToolParameter().with_name(param))
        tools.append(tool)
    return tools

def llmRequestMessage(role, content):
    return LLMMessage().with_role(role).with_content(content)

def llmToolCallResponseMessage(role, callid, content):
    return (LLMToolCallResponseMessage().with_role(role)
                                        .with_callid(callid)
                                        .with_content(content))

def llmToolCallMessage(role, calls: [LLMToolCall], content):
    return (LLMToolCallMessage().with_role(role)
                                .with_calls(calls)
                                .with_content(content))

def llmRequest(prompt, episodes, max_tokens, reasoning_mode, tools):
    return (LLMRequest().with_messages([prompt] + episodes)
                       .with_max_tokens(max_tokens)
                       .with_reasoning_mode(reasoning_mode)
                       .with_tools(tools))

def llmResponseIsEmpty(response: LLMResponse):
    return len(response.calls) == 0

def llmResponseCalls(response: LLMResponse):
    return response.calls

def llmResponseIsError(response: LLMResponse):
    return bool(response.error)

def llmResponseGetError(response: LLMResponse):
    return response.error

def llmToolCallGetName(call: LLMToolCall):
    return call.name

def llmToolCallGetId(call: LLMToolCall):
    return call.id

def llmToolCallGetArguments(call: LLMToolCall):
    return call.arguments

def llmToolCallIsError(call: LLMToolCall):
    return bool(call.error)

def llmToolCallGetError(call: LLMToolCall):
    return call.error

def llmToolCallToSExpr(call: LLMToolCall):
    sexpr = f"({call.name} "
    for parameter in call.tool.parameters:
        if parameter.name in call.arguments:
            arg = call.arguments[parameter.name]
            arg = arg.replace('"','\\"')
            sexpr = sexpr + f"\"{arg}\" "
    return sexpr[:-1] + ")"

