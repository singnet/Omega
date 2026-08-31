import os
import lib_llm_ext as llm
import providers
from src.logger import get_logger
from config import config_get_by_key
from typing import Dict, Any

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

    def prepare_args(self, content: str, max_tokens: int = 6000,
                                reasoning: str = "medium", **kwargs) -> Dict[str, Any]:
        sysmsg, usermsg = llm._split_system_user(content)
        args = {
            "instructions": sysmsg,
            "model": self._model_name,
            "input": usermsg,
            "max_output_tokens": max_tokens,
            "reasoning": {"effort": reasoning},
            "prompt_cache_key": config_get_by_key("OPENAI_PROMPT_CACHE_KEY", llm._stable_cache_key("openai", self._model_name, sysmsg)),
        }
        # GPT-5.5 supports only 24h; GPT-5.4 also supports extended retention.
        if self._model_name.startswith(("gpt-5.5", "gpt-5.4")):
            args["prompt_cache_retention"] = "24h"

        args.update(kwargs)
        return args

    def extract_raw_response(self, response):
        usage = getattr(response, "usage", None)
        if usage:
            input_tokens = getattr(usage, "input_tokens", None)
            output_tokens = getattr(usage, "output_tokens", None)
            total_tokens = getattr(usage, "total_tokens", None)
            details = getattr(usage, "input_tokens_details", None)
            cached_tokens = getattr(details, "cached_tokens", None) if details else None

            logger.info(
                f"[LLM_USAGE] provider={self._name} model={self._model_name} "
                f"input_tokens={input_tokens} output_tokens={output_tokens} "
                f"total_tokens={total_tokens} cached_tokens={cached_tokens}"
            )

        return response.output_text or ""

    def chat(self, content: str, max_tokens: int = 6000, reasoning: str = "medium", **kwargs) -> str:
        """Send chat request, initializing client if needed."""
        self._ensure_client()

        if self._client is None:
            raise RuntimeError(f"{self.name} not configured (set {self._var_name})")

        try:
            kwargs = self.prepare_args(content, max_tokens, reasoning, **kwargs)
            # TODO: This line is the only line which is different to
            # super().chat() implementation
            response = self._client.responses.create(**kwargs)
            raw = self.extract_raw_response(response)
            llm._log_raw(self._name, self._model_name, raw)
            resp = self._clean_text(raw)
            return resp
        except Exception as e:
            logger.exception(f"[AIProvider.chat]: Exception while communicating with LLM: {e}")
            return ""
