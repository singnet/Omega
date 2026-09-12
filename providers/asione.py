import lib_llm_ext as llm
import providers
from src.logger import get_logger
from config import config_get_by_key

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

    def __init__(self, name: str, var_name: str, model_name: str, base_url: str):
        super().__init__(name, var_name, model_name, base_url)

    def chat(self, content: str, max_tokens: int = 6000, reasoning: str = "medium", **kwargs) -> str:
        """Send chat request, initializing client if needed."""
        self._ensure_client()

        if self._client is None:
            raise RuntimeError(f"{self.name} not configured (set {self._var_name})")

        sysmsg, usermsg = content.split(":-:-:-:")
        try:
            response = self._client.chat.completions.create(
                model=self._model_name,
                messages=[{"role": "system", "content": sysmsg},
                          {"role": "user", "content": usermsg}],
                max_tokens=max_tokens,
                extra_body={
                    "enable_thinking": True,
                    "thinking_budget": 6000 
                },
                **kwargs
            )

            raw = response.choices[0].message.content
            llm._log_raw(self._name, self._model_name, raw)
            llm._log_chat_completion(self._name, self._model_name, response)
            if not raw:
                logger.warning("LLM returned an empty response")
                raw = llm._llm_empty_response_command()
            resp = self._clean_text(raw)
            return resp
        except Exception as e:
            logger.exception(f"[ASIOneProviderImpl.chat]: Exception while communicating with LLM: {e}")
            return ""
