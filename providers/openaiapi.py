import os
import lib_llm_ext as llm
import providers
from config import config_get_by_key
from typing import Any


def _flag_is_on(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.lower() == "true")


class OpenAIAPIProviderImpl(llm.AIProvider):

    def convert_request(self, request: providers.LLMRequest) -> dict[str, Any]:
        result = super().convert_request(request)
        reasoning = request.reasoning_mode
        if reasoning and _flag_is_on(config_get_by_key("supportsReasoningEffort", False)):
            result["extra_body"] = {"reasoning_effort": str(reasoning).lower()}
        return result


class OpenAIAPI(providers.LLMProvider):

    _delegate_class = OpenAIAPIProviderImpl

    def __init__(self, name):
        super().__init__()
        self._name = name

    def api_token_var(self):
        return config_get_by_key("api_token_var", "OPENAIAPI_API_KEY")

    def model(self):
        openaiapi_model = config_get_by_key("openaiapi_model", "qwen3.5:9b")
        return config_get_by_key("model", openaiapi_model)

    def base_url(self):
        return config_get_by_key("openaiapi_url", "http://localhost:11434/v1/")

    def start(self) -> None:
        self.delegate = self._delegate_class(self._name, self.api_token_var(),
                                             self.model(), self.base_url())

    def stop(self) -> None:
        self.delegate.stop()

    def chat(self, args: providers.LLMRequest) -> providers.LLMResponse:
        return self.delegate.chat(args)


class OpenAIAPIPreconfigured(OpenAIAPI):

    _delegate_class = llm.AIProvider

    def __init__(self, name, api_token_var, default_model, base_url):
        super().__init__(name)
        self._api_token_var = api_token_var
        self._default_model = default_model
        self._base_url = base_url

    def api_token_var(self):
        return self._api_token_var

    def model(self):
        return config_get_by_key("model", self._default_model)

    def base_url(self):
        return self._base_url

def loadOmegaPlugin():
    providers.registerLLMProvider("OpenAIAPI", OpenAIAPI("OpenAIAPI"))
    asicloud_model = config_get_by_key("asicloud_model", "minimax/minimax-m3")
    providers.registerLLMProvider("ASICloud", OpenAIAPIPreconfigured("ASICloud", "ASI_API_KEY", asicloud_model, "https://inference.asicloud.cudos.org/v1"))
    anthropic_model = config_get_by_key("anthropic_model", "claude-opus-4-8")
    providers.registerLLMProvider("Anthropic", OpenAIAPIPreconfigured("Anthropic", "ANTHROPIC_API_KEY", anthropic_model, "https://api.anthropic.com/v1/"))
