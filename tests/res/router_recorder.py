import providers
from providers import LLMProvider, LLMResponse, LLMTool, LLMToolCall, registerLLMProvider

SERVED = []


class RecorderDelegate:

    def __init__(self):
        self._model_name = None
        self._var_name = None
        self._base_url = None
        self._gateway_route = None

    def chat(self, request):
        SERVED.append(f"{self._gateway_route}@{self._model_name}@{self._var_name}")
        call = LLMToolCall().with_name("ping").with_id("call#0")
        return LLMResponse().add_tool_call(call)


class RecorderProvider(LLMProvider):

    def start(self):
        self.delegate = RecorderDelegate()

    def chat(self, request):
        return self.delegate.chat(request)


def register(name):
    registerLLMProvider(name, RecorderProvider())
    return name


def reset():
    SERVED.clear()
    return "reset"


def served():
    return "+".join(SERVED)


def tools():
    return [LLMTool().with_name("ping").with_description("ping tool")]


def select_irc_channel():
    import channels
    import irc
    channels._commchannel = irc.IRCChannel()
    return "irc"
