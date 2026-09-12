import os
import lib_llm_ext as llm
import providers
from src.logger import get_logger
from config import config_get_by_key

logger = get_logger(__name__)

class OpenAIProvider(providers.LLMProvider):

    def __init__(self):
        super().__init__()

    def start(self) -> None:
        openai_model = config_get_by_key("openai_model", "gpt-5.5")
        model = config_get_by_key("model", openai_model)
        self.delegate = OpenAIProviderImpl("OpenAI", "OPENAI_API_KEY",
                                           model, "https://api.openai.com/v1")

    def stop(self) -> None:
        self.delegate.stop()

    def chat(self, prompt: str, max_tokens: int = 6000, reasoning_mode: str = "medium") -> str:
        return self.delegate.chat(prompt, max_tokens, reasoning_mode)

def loadOmegaPlugin():
    providers.registerLLMProvider("OpenAI", OpenAIProvider())

class OpenAIProviderImpl(llm.AIProvider):
    """OpenAI provider using the Responses API (reasoning models)."""

    def chat(self, content: str, max_tokens: int = 6000, reasoning: str = "medium", **kwargs) -> str:
        """Send chat request via the Responses API, initializing client if needed."""
        self._ensure_client()

        if self._client is None:
            raise RuntimeError(f"{self.name} not configured (set {self._var_name})")

        sysmsg, usermsg = llm._split_system_user(content)

        try:
            create_kwargs = {
                "instructions": sysmsg,
                "model": self._model_name,
                "input": usermsg,
                "max_output_tokens": max_tokens,
                "reasoning": {"effort": reasoning},
                "prompt_cache_key": config_get_by_key("OPENAI_PROMPT_CACHE_KEY", llm._stable_cache_key("openai", self._model_name, sysmsg)),
            }
            # GPT-5.5 supports only 24h; GPT-5.4 also supports extended retention.
            if self._model_name.startswith(("gpt-5.5", "gpt-5.4")):
                create_kwargs["prompt_cache_retention"] = "24h"

            create_kwargs.update(kwargs)

            response = self._client.responses.create(**create_kwargs)

            raw = response.output_text or ""
            llm._log_raw(self._name, self._model_name, raw)
            llm._log_responses_completion(self._name, self._model_name, response)
            if not raw:
                logger.warning("LLM returned an empty response")
                raw = llm._llm_empty_response_command()
            return self._clean_text(raw)
        except Exception as e:
            logger.exception(f"[OpenAIProviderImpl.chat]: Exception while communicating with LLM: {e}")
            return ""
