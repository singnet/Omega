import os, hashlib
import openai
from providers import *
from typing import Optional, Tuple, Dict, Any
from config import config_get_by_key
import json

PROMPT_DELIMITER = ":-:-:-:"

from src.logger import get_logger


logger = get_logger(__name__)

def _log_raw(kind, provider: str, model: str, raw: Dict) -> None:
    logger.debug(f"[{kind}] provider={provider} model={model} raw={raw!r}")

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

    def chat(self, request: LLMRequest) -> LLMResponse:
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

    def convert_message(self, message: LLMMessage) -> Dict:
        result = { "role": message.role, "content": message.content }
        if isinstance(message, LLMToolCallResponseMessage):
            result["tool_call_id"] = message.callid
        if isinstance(message, LLMToolCallMessage):
            result["tool_calls"] = [self.convert_tool_call(call) for call in message.calls]
        return result

    def convert_tool_call(self, call: LLMToolCall) -> Dict:
        return {
            "type": "function",
            "id": call.id,
            "function": {
                "name": call.name,
                "arguments": json.dumps(call.arguments)
            }
        }

    def convert_tool(self, tool: LLMTool) -> Dict:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": { param.name: { "type": "string" } for param in tool.parameters },
                    "required": [ param.name for param in tool.parameters ]
                }
            }
        }

    def convert_request(self, request: LLMRequest) -> Dict[str, Any]:
        return {
            "model": self._model_name,
            "messages": [self.convert_message(msg) for msg in request.messages],
            "max_tokens": request.max_tokens,
            "tools": [self.convert_tool(tool) for tool in request.tools],
            "tool_choice": "required",
        }

    def convert_response(self, raw):
        response =  LLMResponse()

        message = raw.choices[0].message
        if not message.tool_calls:
            return response

        for tool_call in message.tool_calls:
            tc = LLMToolCall().with_name(tool_call.function.name).with_id(tool_call.id)
            try:
                arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as error:
                response.add_tool_call(tc.with_error(f"Invalid tool arguments from model: {error}"))
            else:
                if isinstance(arguments, dict):
                    response.add_tool_call(tc.with_arguments(arguments))
                else:
                    response.add_tool_call(tc.with_error("Tool arguments must be a JSON object"))

        return response

    def chat(self, request: LLMRequest) -> LLMResponse:
        """Send chat request, initializing client if needed."""
        self._ensure_client()

        if self._client is None:
            raise RuntimeError(f"{self.name} not configured (set {self._var_name})")

        try:
            raw_request = self.convert_request(request)
            _log_raw("LLM_RAW_REQUEST", self._name, self._model_name, raw_request)
            raw_response = self._client.chat.completions.create(**raw_request)
            _log_raw("LLM_RAW_RESPONSE", self._name, self._model_name, raw_response)
            return self.convert_response(raw_response)
        except Exception as e:
            error = f"Exception while communicating with LLM: {e}"
            logger.exception(f"[AIProvider.chat]: {error}")
            return LLMResponse().with_error(error)

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


