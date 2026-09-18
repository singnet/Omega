import os
from typing import Any
import lib_llm_ext as llm
import providers
from src.logger import get_logger
from config import config_get_by_key

logger = get_logger(__name__)

class OpenRouterProvider(providers.LLMProvider):

    def __init__(self):
        super().__init__()

    def start(self) -> None:
        openrouter_model = config_get_by_key("openrouter_model", "z-ai/glm-5.2")
        model = config_get_by_key("model", openrouter_model)
        self.delegate = OpenRouterProviderImpl("OpenRouter", "OPENROUTER_API_KEY",
                                               model, "https://openrouter.ai/api/v1")

    def stop(self) -> None:
        self.delegate.stop()

    def chat(self, args: providers.LLMRequest) -> providers.LLMResponse:
        return self.delegate.chat(args)

def loadOmegaPlugin():
    providers.registerLLMProvider("OpenRouter", OpenRouterProvider())

class OpenRouterProviderImpl(llm.AIProvider):
    """OpenRouter provider with reasoning mode enabled (reasoning tokens excluded from the response)."""

    def _openrouter_extra_body(self, request: providers.LLMRequest) -> dict[str, Any]:
        sysmsg = request.messages[0].content
        body = {
            "reasoning": {
                "enabled": True,
                "max_tokens": request.max_tokens,
                "exclude": True,
            }
        }

        # Helps OpenRouter sticky-route requests for better cache locality.
        # Keep this stable per agent/session.
        session_id = config_get_by_key("OPENROUTER_SESSION_ID")
        if not session_id and sysmsg:
            session_id = llm._stable_cache_key("openrouter", self._model_name, sysmsg)

        if session_id:
            body["session_id"] = session_id[:256]

        model = self._model_name.lower()

        # OpenRouter supports top-level cache_control for Anthropic Claude routes.
        if model.startswith("anthropic/"):
            body["cache_control"] = {
                "type": "ephemeral",
                "ttl": config_get_by_key("OPENROUTER_CACHE_TTL", "5m"),
            }

        return body

    def convert_request(self, request: providers.LLMRequest) -> dict[str, Any]:
        result = super().convert_request(request)
        result['extra_body'] = llm._merge_dicts(
            self._openrouter_extra_body(request),
            result.pop("extra_body", None),
        )
        return result
