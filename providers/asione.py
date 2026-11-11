import lib_llm_ext as llm
import providers
from src.logger import get_logger
from config import config_get_by_key
from typing import Any

logger = get_logger(__name__)

# Share of max_tokens reserved for reasoning at each effort level; the rest stays for the answer.
# Ratios follow OpenRouter: https://openrouter.ai/docs/guides/best-practices/reasoning-tokens#reasoning-effort-level
REASONING_EFFORT_RATIO = {
    "none": 0.0,
    "minimal": 0.10,
    "low": 0.20,
    "medium": 0.50,
    "high": 0.80,
    "xhigh": 0.95,
    "max": 0.95,
}

def _reasoning_budget(max_tokens: int, effort: str) -> int:
    """Tokens reserved for reasoning; the rest of max_tokens stays for the answer."""
    return int(max_tokens * REASONING_EFFORT_RATIO.get(str(effort).lower(), 0.0))

class ASIOneProvider(providers.LLMProvider):

    def __init__(self):
        super().__init__()

    def start(self) -> None:
        asione_model = config_get_by_key("asione_model", "asi1-ultra")
        model = config_get_by_key("model", asione_model)
        self.delegate = ASIOneProviderImpl("ASIOne", "ASIONE_API_KEY",
                                           model, "https://api.asi1.ai/v1")

    def stop(self) -> None:
        self.delegate.stop()

    def chat(self, args: providers.LLMRequest) -> providers.LLMResponse:
        return self.delegate.chat(args)

def loadOmegaPlugin():
    providers.registerLLMProvider("ASIOne", ASIOneProvider())

class ASIOneProviderImpl(llm.AIProvider):
    """Lazy AI provider with on-demand initialization."""

    def convert_request(self, request: providers.LLMRequest) -> dict[str, Any]:
        result = super().convert_request(request)
        thinking_budget = _reasoning_budget(request.max_tokens,
                                            request.reasoning_mode)
        result["extra_body"] = {
            "enable_thinking": thinking_budget > 0,
            "thinking_budget": thinking_budget
        }
        return result
