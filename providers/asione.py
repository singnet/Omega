import lib_llm_ext as llm
import providers
from src.logger import get_logger
from config import config_get_by_key
from typing import Dict, Any

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

    def chat(self, prompt: str, max_tokens: int = 6000, reasoning_mode: str = "medium") -> str:
        return self.delegate.chat(prompt, max_tokens, reasoning_mode)

def loadOmegaPlugin():
    providers.registerLLMProvider("ASIOne", ASIOneProvider())

class ASIOneProviderImpl(llm.AIProvider):
    """Lazy AI provider with on-demand initialization."""

    def prepare_args(self, content: str, max_tokens: int = 6000,
                                reasoning: str = "medium", **kwargs) -> Dict[str, Any]:
        sysmsg, usermsg = llm._split_system_user(content)
        return {
            "model": self._model_name,
            "messages": [
                {"role": "system", "content": sysmsg},
                {"role": "user", "content": usermsg}
            ],
            "max_tokens": max_tokens,
            "extra_body": {
                "enable_thinking": True,
                "thinking_budget": 6000
            },
            **kwargs
        }
