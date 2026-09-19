import lib_llm_ext as llm
import providers
from src.logger import get_logger
from config import config_get_by_key

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

    def chat(self, prompt: str, max_tokens: int = 6000, reasoning_mode: str = "medium") -> str:
        return self.delegate.chat(prompt, max_tokens, reasoning_mode)

def loadOmegaPlugin():
    providers.registerLLMProvider("ASIOne", ASIOneProvider())

class ASIOneProviderImpl(llm.AIProvider):
    """Lazy AI provider with on-demand initialization."""

    def __init__(self, name: str, var_name: str, model_name: str, base_url: str):
        super().__init__(name, var_name, model_name, base_url)

    def chat(self, content: str, max_tokens: int = 6000, reasoning: str = "medium", **kwargs) -> str:
        """Send chat request, initializing client if needed."""
        self._ensure_client()

        if self._client is None:
            raise RuntimeError(f"{self.name} not configured (set {self._var_name})")

        sysmsg, usermsg = content.split(":-:-:-:")
        thinking_budget = _reasoning_budget(max_tokens, reasoning)
        try:
            response = self._client.chat.completions.create(
                model=self._model_name,
                messages=[{"role": "system", "content": sysmsg},
                          {"role": "user", "content": usermsg}],
                max_tokens=max_tokens,
                extra_body={
                    "enable_thinking": thinking_budget > 0,
                    "thinking_budget": thinking_budget
                },
                **kwargs
            )

            raw = response.choices[0].message.content or ""
            finish_reason = getattr(response.choices[0], "finish_reason", None)
            llm._log_raw(self._name, self._model_name, raw)
            llm._log_chat_completion(self._name, self._model_name, response)
            if not raw:
                logger.warning("LLM returned an empty response")
                if finish_reason == "length":
                    raw = llm._llm_empty_response_command()
            resp = self._clean_text(raw)
            return resp
        except Exception as e:
            logger.exception(f"[ASIOneProviderImpl.chat]: Exception while communicating with LLM: {e}")
            return ""
