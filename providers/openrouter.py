import os
import openai
from typing import Optional, Dict, Any
import lib_llm_ext as llm
import providers
from src.logger import get_logger
from config import config_get_by_key

logger = get_logger(__name__)

# Share of the completion budget OpenRouter reserves for reasoning at each effort level.
# Models that accept only reasoning.max_tokens get the same split, computed here.
# See: https://openrouter.ai/docs/guides/best-practices/reasoning-tokens#reasoning-effort-level
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
    ratio = REASONING_EFFORT_RATIO.get((effort or "none").lower(), 0.0)
    return int(max_tokens * ratio)

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

    def chat(self, prompt: str, max_tokens: int = 6000, reasoning_mode: str = "medium") -> str:
        return self.delegate.chat(prompt, max_tokens, reasoning_mode)

def loadOmegaPlugin():
    providers.registerLLMProvider("OpenRouter", OpenRouterProvider())

class OpenRouterProviderImpl(llm.AIProvider):
    """OpenRouter provider with reasoning mode enabled (reasoning tokens excluded from the response)."""

    def _create_client(self) -> Optional[openai.OpenAI]:
        """Create OpenRouter client from environment."""
        proxy_url = config_get_by_key("GATEWAY_URL")
        if proxy_url:
            base_url = f"{proxy_url.rstrip('/')}/openrouter/"
            logger.info(f"[OpenRouterProviderImpl._create_client]: Connecting via proxy: {base_url}")
            return openai.OpenAI(
                    api_key="proxy",
                    base_url=base_url,
                    )
        if self._var_name in os.environ:
            return openai.OpenAI(api_key=os.environ.get(self._var_name), base_url=self._base_url)

        return None

    def _openrouter_extra_body(self, content: str, max_tokens: int, reasoning: str) -> Dict[str, Any]:
        is_anthropic = self._model_name.lower().startswith("anthropic/")
        sysmsg, _ = llm._split_system_user(content)
        # OpenRouter Anthropic models support `max_tokens` for reasoning,
        # while other models expect an effort level.
        reasoning_config = (
            {"max_tokens": _reasoning_budget(max_tokens, reasoning)} if is_anthropic
            else {"effort": reasoning}
        )
        body = {
            "reasoning": {
                "enabled": True,
                **reasoning_config,
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

        # OpenRouter supports top-level cache_control for Anthropic Claude routes.
        if is_anthropic:
            body["cache_control"] = {
                "type": "ephemeral",
                "ttl": config_get_by_key("OPENROUTER_CACHE_TTL", "5m"),
            }

        return body


    def chat(self, content: str, max_tokens: int = 6000, reasoning: str = "medium", **kwargs) -> str:
        extra_body = llm._merge_dicts(
            self._openrouter_extra_body(content, max_tokens, reasoning),
            kwargs.pop("extra_body", None),
        )

        return super().chat(
            content=content,
            max_tokens=max_tokens,
            reasoning=reasoning,
            extra_body=extra_body,
            **kwargs,
        )
