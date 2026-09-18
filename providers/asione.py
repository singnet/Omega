import lib_llm_ext as llm
import providers
from src.logger import get_logger
from config import config_get_by_key
from typing import Any

logger = get_logger(__name__)

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
        result["extra_body"] = {
            "enable_thinking": True,
            "thinking_budget": 6000
        }
        return result
