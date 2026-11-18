import importlib.util
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
        for name in ("lib_llm_ext", "openrouter", "openai_provider", "asione", "openaiapi"):
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
openaiapi = _MODULES["openaiapi"]


def tool(name, description, *params):
    result = P.LLMTool().with_name(name).with_description(description)
    for param in params:
        result = result.add_parameter(P.LLMToolParameter().with_name(param))
    return result


SEND = tool("send", "Send a message to the user", "content")
NOP = tool("nop", "Perform no action.")
SHELL = tool("shell", "Run a command", "timeout", "command", "cwd")
TOOLS = [SEND, NOP, SHELL]


def make_request(tools=None):
    return P.llmRequest(P.llmRequestMessage("system", "You are an agent."),
                        [P.llmRequestMessage("user", "hello")],
                        6000, "medium", TOOLS if tools is None else tools)


def parameters_of(tool_obj):
    names = [param.name for param in tool_obj.parameters]
    return {"type": "object", "properties": {name: {"type": "string"} for name in names},
            "required": names, "additionalProperties": False}


def chat_form(tool_obj):
    return {"type": "function",
            "function": {"name": tool_obj.name, "description": tool_obj.description, "strict": True,
                         "parameters": parameters_of(tool_obj)}}


def responses_form(tool_obj):
    return {"type": "function", "name": tool_obj.name, "description": tool_obj.description, "strict": True,
            "parameters": parameters_of(tool_obj)}


def tool_call(call_id, name, arguments):
    return NS(id=call_id, type="function", function=NS(name=name, arguments=arguments))


def chat_response(tool_calls, finish_reason):
    return NS(
        id="chatcmpl-8f3a2c1d9e7b4a6c",
        choices=[NS(index=0, finish_reason=finish_reason,
                    message=NS(role="assistant", content=None, tool_calls=tool_calls))],
        usage=NS(prompt_tokens=2900, completion_tokens=40, total_tokens=2940,
                 prompt_tokens_details=NS(cached_tokens=2600),
                 completion_tokens_details=NS(reasoning_tokens=30)),
    )


def function_call(item_id, name, arguments):
    return NS(type="function_call", id=item_id, call_id="call_" + item_id[3:], name=name,
              arguments=arguments, status="completed")


def responses_response(output, status):
    return NS(
        id="resp_0c889d49c22b6f01006abbb943f13487d282b88815139a52",
        output=output,
        status=status,
        incomplete_details=None,
        usage=NS(input_tokens=1200, output_tokens=120, total_tokens=1320,
                 input_tokens_details=NS(cached_tokens=0),
                 output_tokens_details=NS(reasoning_tokens=120)),
    )


class FakeCreate:
    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


def make_openrouter(create, model="z-ai/glm-5.2"):
    provider = openrouter.OpenRouterProviderImpl("OpenRouter", "OPENROUTER_API_KEY", model, "https://openrouter.ai/api/v1")
    provider._client = NS(chat=NS(completions=NS(create=create)))
    return provider


def make_openrouter_anthropic(create):
    return make_openrouter(create, model="anthropic/claude-opus-4-8")


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


CHAT_FACTORIES = [make_anthropic, make_openrouter, make_openrouter_anthropic, make_asione]
CHAT_IDS = ["anthropic", "openrouter", "openrouter-anthropic-model", "asione"]


@pytest.fixture(params=CHAT_FACTORIES, ids=CHAT_IDS)
def chat_provider(request):
    return request.param(FakeCreate())


def test_chat_tools_have_exact_shape(chat_provider):
    assert chat_provider.convert_request(make_request())["tools"] == [chat_form(t) for t in TOOLS]


def test_chat_tools_are_strict(chat_provider):
    for item in chat_provider.convert_request(make_request())["tools"]:
        assert item["function"]["strict"] is True


def test_chat_parameters_forbid_additional_properties(chat_provider):
    for item in chat_provider.convert_request(make_request())["tools"]:
        assert item["function"]["parameters"]["additionalProperties"] is False


def test_chat_required_lists_parameters_in_order(chat_provider):
    by_name = {item["function"]["name"]: item for item in chat_provider.convert_request(make_request())["tools"]}
    assert by_name["shell"]["function"]["parameters"]["required"] == ["timeout", "command", "cwd"]
    assert by_name["send"]["function"]["parameters"]["required"] == ["content"]


def test_chat_tool_choice_is_required(chat_provider):
    assert chat_provider.convert_request(make_request())["tool_choice"] == "required"


def test_chat_uses_max_tokens(chat_provider):
    raw = chat_provider.convert_request(make_request())
    assert raw["max_tokens"] == 6000
    assert "max_output_tokens" not in raw


def test_chat_tool_without_parameters(chat_provider):
    item = chat_provider.convert_request(make_request([NOP]))["tools"][0]
    assert item["function"]["parameters"]["properties"] == {}
    assert item["function"]["parameters"]["required"] == []


def test_chat_tools_keep_count_and_order(chat_provider):
    names = [item["function"]["name"] for item in chat_provider.convert_request(make_request())["tools"]]
    assert names == ["send", "nop", "shell"]


def test_responses_tools_have_exact_shape():
    assert make_openai(FakeCreate()).convert_request(make_request())["tools"] == [responses_form(t) for t in TOOLS]


def test_responses_tools_are_flat():
    for item in make_openai(FakeCreate()).convert_request(make_request())["tools"]:
        assert "function" not in item
        assert item["name"]


def test_responses_tools_are_strict():
    for item in make_openai(FakeCreate()).convert_request(make_request())["tools"]:
        assert item["strict"] is True


def test_responses_parameters_forbid_additional_properties():
    for item in make_openai(FakeCreate()).convert_request(make_request())["tools"]:
        assert item["parameters"]["additionalProperties"] is False


def test_responses_required_lists_parameters_in_order():
    by_name = {item["name"]: item for item in make_openai(FakeCreate()).convert_request(make_request())["tools"]}
    assert by_name["shell"]["parameters"]["required"] == ["timeout", "command", "cwd"]
    assert by_name["send"]["parameters"]["required"] == ["content"]


def test_responses_tool_choice_is_required():
    assert make_openai(FakeCreate()).convert_request(make_request())["tool_choice"] == "required"


def test_responses_uses_max_output_tokens():
    raw = make_openai(FakeCreate()).convert_request(make_request())
    assert raw["max_output_tokens"] == 6000
    assert "max_tokens" not in raw


def test_responses_tool_without_parameters():
    item = make_openai(FakeCreate()).convert_request(make_request([NOP]))["tools"][0]
    assert item["parameters"]["properties"] == {}
    assert item["parameters"]["required"] == []


def test_responses_tools_keep_count_and_order():
    names = [item["name"] for item in make_openai(FakeCreate()).convert_request(make_request())["tools"]]
    assert names == ["send", "nop", "shell"]


@pytest.mark.parametrize("make", [make_openrouter, make_openrouter_anthropic, make_asione],
                         ids=["openrouter", "openrouter-anthropic-model", "asione"])
def test_extra_body_leaves_tool_fields_of_base_provider(make):
    request = make_request()
    raw = make(FakeCreate()).convert_request(request)
    base = make_anthropic(FakeCreate()).convert_request(request)
    assert raw["tools"] == base["tools"]
    assert raw["tool_choice"] == base["tool_choice"]
    assert "tools" not in raw.get("extra_body", {})
    assert "tool_choice" not in raw.get("extra_body", {})


@pytest.mark.parametrize("make", CHAT_FACTORIES, ids=CHAT_IDS)
def test_chat_sends_converted_tool_fields(make):
    create = FakeCreate(chat_response([tool_call("call_1", "nop", "{}")], "tool_calls"))
    make(create).chat(make_request())
    assert create.calls[0]["tools"] == [chat_form(t) for t in TOOLS]
    assert create.calls[0]["tool_choice"] == "required"


def test_responses_sends_converted_tool_fields():
    create = FakeCreate(responses_response([function_call("fc_0c889d49c22b6f01", "nop", "{}")], "completed"))
    make_openai(create).chat(make_request())
    assert create.calls[0]["tools"] == [responses_form(t) for t in TOOLS]
    assert create.calls[0]["tool_choice"] == "required"


def registered_providers(monkeypatch):
    registry = {}
    monkeypatch.setattr(P, "registerLLMProvider", lambda name, provider: registry.__setitem__(name, provider))
    openaiapi.loadOmegaPlugin()
    return registry


@pytest.mark.parametrize("name", ["OpenAIAPI", "ASICloud", "Anthropic"])
def test_registered_wrapper_sends_converted_tool_fields(monkeypatch, name):
    provider = registered_providers(monkeypatch)[name]
    provider.start()
    create = FakeCreate(chat_response([tool_call("call_1", "nop", "{}")], "tool_calls"))
    provider.delegate._client = NS(chat=NS(completions=NS(create=create)))
    provider.chat(make_request())
    sent = create.calls[0]
    assert sent["tools"] == [chat_form(t) for t in TOOLS]
    assert sent["tool_choice"] == "required"
    assert sent["max_tokens"] == 6000
    assert all(item["function"]["strict"] is True for item in sent["tools"])
