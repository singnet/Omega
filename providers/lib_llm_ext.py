import os, hashlib
import openai
from typing import Optional, Tuple, Dict, Any
from config import config_get_by_key
from src.helper import quote_arg

PROMPT_DELIMITER = ":-:-:-:"
LLM_EMPTY_RESPONSE_MESSAGE = (
    "The agent didn\'t return an answer: reasoning exceeded the token limit for "
    "this response before it could produce one."
    "\n\n"
    "If you are not an administrator: ask the Omega administrator to lower "
    "the reasoning level or raise the response token budget - or try breaking "
    "your request into smaller, simpler steps."
    "\n\n"
    "If you are the Omega administrator: check whether the model supports a "
    "lower reasoning level and set it via 'reasoningMode' "
    "(e.g. high → medium → low). Alternatively, raise 'maxOutputToken' - "
    "reasoning and the final answer draw from the same token limit, so higher "
    "reasoning levels need a higher token limit."
)

from src.logger import get_logger


logger = get_logger(__name__)

def _log_raw(provider: str, model: str, raw: str) -> None:
    logger.debug(f"[LLM_RAW] provider={provider} model={model} chars={len(raw or '')} raw={raw!r}")

def _log_chat_completion(provider: str, model: str, response) -> None:
    """Report how the completion budget was actually spent (Chat Completions API)."""
    finish_reason = getattr(response.choices[0], "finish_reason", None)
    usage = getattr(response, "usage", None)
    details = getattr(usage, "completion_tokens_details", None)
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    line = (
        f"[LLM_USAGE] provider={provider} model={model} "
        f"finish_reason={finish_reason} "
        f"prompt_tokens={getattr(usage, 'prompt_tokens', None)} "
        f"cached_tokens={getattr(prompt_details, 'cached_tokens', None)} "
        f"completion_tokens={getattr(usage, 'completion_tokens', None)} "
        f"reasoning_tokens={getattr(details, 'reasoning_tokens', None)} "
    )
    logger.debug(line)

def _log_responses_completion(provider: str, model: str, response) -> None:
    """Report how the completion budget was actually spent (Responses API).
    """
    incomplete_details = getattr(response, "incomplete_details", None)
    usage = getattr(response, "usage", None)
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    line = (
        f"[LLM_USAGE] provider={provider} model={model} "
        f"status={getattr(response, 'status', None)} "
        f"incomplete_reason={getattr(incomplete_details, 'reason', None)} "
        f"input_tokens={getattr(usage, 'input_tokens', None)} "
        f"cached_tokens={getattr(input_details, 'cached_tokens', None)} "
        f"output_tokens={getattr(usage, 'output_tokens', None)} "
        f"reasoning_tokens={getattr(output_details, 'reasoning_tokens', None)} "
    )
    logger.debug(line)

def _llm_empty_response_command() -> str:
    """Return an explanatory message as a MeTTa `send` command when the LLM
    spends the entire output token budget on reasoning and returns no content.
    """
    return f"(send {quote_arg(LLM_EMPTY_RESPONSE_MESSAGE)})"

def _split_system_user(content: str) -> Tuple[str, str]:
    """
    MeTTa sends:
        <system/context> :-:-:-: <last human/wakeup message>

    Keep the split intact so providers receive a real system prompt.
    """
    if PROMPT_DELIMITER not in content:
        return "", content.strip()

    sysmsg, _, usermsg = content.partition(PROMPT_DELIMITER)
    sysmsg = sysmsg.strip()
    usermsg = usermsg.strip()

    if not usermsg:
        usermsg = "EMPTY / NO NEW USER INPUT."

    return sysmsg, usermsg

def _stable_cache_key(provider: str, model: str, sysmsg: str) -> str:
    """
    Stable key for requests sharing the same system-prefix family.
    Do not include the user message here.
    """
    marker = " LAST_SKILL_USE_RESULTS: "
    stable = sysmsg.split(marker, 1)[0].strip()
    digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]
    return f"{provider.lower()}:{model}:{digest}"


def _merge_dicts(base: Optional[Dict[str, Any]], extra: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(base or {})
    merged.update(extra or {})
    return merged

class AbstractAIProvider:
    def __init__(self, name: str):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def chat(self, content: str, max_tokens: int = 6000, reasoning: str = "medium", **kwargs) -> str:
        raise NotImplementedError

    @property
    def is_available(self) -> bool:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

class AIProvider(AbstractAIProvider):
    """Lazy AI provider with on-demand initialization."""

    def __init__(self, name: str, var_name: str, model_name: str, base_url: str):
        super().__init__(name)
        self._var_name = var_name
        self._model_name = model_name
        self._base_url = base_url
        self._client = None  # lazy initialization

    def _ensure_client(self):
        """Initialize client on first use."""
        if self._client is None:
            self._client = self._create_client()

    def _create_client(self) -> Optional[openai.OpenAI]:
        """Create OpenAI client from environment."""
        proxy_url = config_get_by_key("GATEWAY_URL")
        if proxy_url:
            prefix = self._name.lower()
            base_url = f"{proxy_url.rstrip('/')}/{prefix}/"
            logger.info(f"[AIProvider._create_client]: Connecting via proxy: {base_url}")
            return openai.OpenAI(
                    api_key="proxy",
                    base_url=base_url,
                    )
        if self._var_name in os.environ:
            return openai.OpenAI(api_key=os.environ.get(self._var_name), base_url=self._base_url)

        return None

    @property
    def is_available(self) -> bool:
        """Check if provider is configured (without initializing)."""
        return bool(config_get_by_key("GATEWAY_URL")) or bool(os.environ.get(self._var_name))

    def _build_messages(self, content: str):
        sysmsg, usermsg = _split_system_user(content)

        if sysmsg:
            return [
                {"role": "system", "content": sysmsg},
                {"role": "user", "content": usermsg},
            ]

        return [{"role": "user", "content": usermsg}]

    def chat(self, content: str, max_tokens: int = 6000, reasoning: str = "medium", **kwargs) -> str:
        """Send chat request, initializing client if needed."""
        self._ensure_client()

        if self._client is None:
            raise RuntimeError(f"{self.name} not configured (set {self._var_name})")

        try:
            response = self._client.chat.completions.create(
                model=self._model_name,
                messages=self._build_messages(content),
                max_tokens=max_tokens,
                **kwargs
            )

            raw = response.choices[0].message.content or ""
            _log_raw(self._name, self._model_name, raw)
            _log_chat_completion(self._name, self._model_name, response)
            if not raw:
                logger.warning("LLM returned an empty response")
                raw = _llm_empty_response_command()
            resp = self._clean_text(raw)
            return resp
        except Exception as e:
            logger.exception(f"[AIProvider.chat]: Exception while communicating with LLM: {e}")
            return ""

    def _clean_text(self, text: str) -> str:
        """Unescape special characters."""
        return text.replace("_quote_", '"').replace("_apostrophe_", "'").replace("</arg_value>", " ") \
                    .replace("</tool_call>", " ").replace("<arg_value>", " ").replace("<tool_call>", " ")

    def stop(self) -> None:
        self._client.close()
        self._client = None


_embedding_model = None

def initLocalEmbedding():
    model_name="intfloat/e5-large-v2"
    global _embedding_model
    os.environ["HF_HUB_OFFLINE"] = "1"
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer(model_name)
    return _embedding_model

def useLocalEmbedding(atom):
    global _embedding_model
    if _embedding_model is None:
        raise RuntimeError("Call initLocalEmbedding() first.")
    return _embedding_model.encode(
        atom,
        normalize_embeddings=True
    ).tolist()


