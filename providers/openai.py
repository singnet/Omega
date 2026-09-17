import os
import lib_llm_ext as llm
from providers import *
from src.logger import get_logger
from config import config_get_by_key
from typing import Any
import json

logger = get_logger(__name__)

class OpenAIProvider(LLMProvider):

    def __init__(self):
        super().__init__()

    def start(self) -> None:
        openai_model = config_get_by_key("openai_model", "gpt-5.5")
        model = config_get_by_key("model", openai_model)
        self.delegate = OpenAIProviderImpl("OpenAI", "OPENAI_API_KEY",
                                           model, "https://api.openai.com/v1")

    def stop(self) -> None:
        self.delegate.stop()

    def chat(self, args: LLMRequest) -> LLMResponse:
        return self.delegate.chat(args)

def loadOmegaPlugin():
    registerLLMProvider("OpenAI", OpenAIProvider())

class OpenAIProviderImpl(llm.AIProvider):
    """OpenAI provider using the Responses API (reasoning models)."""

    def convert_message(self, message: LLMMessage) -> [dict]:
        if isinstance(message, LLMToolCallMessage):
            return [self.convert_tool_call(call) for call in message.calls]
        elif isinstance(message, LLMToolCallResponseMessage):
            return [{
                "type": "function_call_output",
                "call_id": message.callid,
                "output": message.content
            }]
        else:
            return [{
                "role": message.role,
                "content": message.content
            }]

    def convert_tool_call(self, call: LLMToolCall) -> dict:
        return {
            "type": "function_call",
            "call_id": call.id,
            "name": call.name,
            "arguments": json.dumps(call.arguments)
        }

    def convert_tool(self, tool: LLMTool) -> dict:
        return {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": { param.name: { "type": "string" } for param in tool.parameters },
                "required": [ param.name for param in tool.parameters ]
            }
        }

    def convert_request(self, request: LLMRequest) -> dict[str, Any]:
        default_cache_key = llm._stable_cache_key("openai",
                                                  self._model_name,
                                                  request.messages[0].content)
        input = []
        for msg in request.messages:
            input += self.convert_message(msg)
        result = {
            "model": self._model_name,
            "input": input,
            "max_output_tokens": request.max_tokens,
            "reasoning": { "effort": request.reasoning_mode },
            "prompt_cache_key": config_get_by_key("OPENAI_PROMPT_CACHE_KEY",
                                                  default_cache_key),
            "tools": [self.convert_tool(tool) for tool in request.tools],
            "tool_choice": "required",
        }

        # GPT-5.5 supports only 24h; GPT-5.4 also supports extended retention.
        if self._model_name.startswith(("gpt-5.5", "gpt-5.4")):
            result["prompt_cache_retention"] = "24h"

        return result

    def convert_response(self, raw):
        llm._log_responses_completion(self._name, self._model_name, raw)

        response =  LLMResponse()
        exhausted = getattr(raw.incomplete_details, "reason", None) == "max_output_tokens"
        for item in raw.output or []:
            if item.type != "function_call":
                continue
            tool_call = item
            tc = LLMToolCall().with_name(tool_call.name).with_id(tool_call.id)
            try:
                arguments = json.loads(tool_call.arguments)
            except json.JSONDecodeError as error:
                error_text = f"Invalid tool arguments from model: {error}"
                if exhausted:
                    error_text = f"{error_text}. {llm.LLM_TRUNCATED_CALL_HINT}"
                response.add_tool_call(tc.with_error(error_text))
            else:
                if isinstance(arguments, dict):
                    response.add_tool_call(tc.with_arguments(arguments))
                else:
                    response.add_tool_call(tc.with_error("Tool arguments must be a JSON object"))

        if not response.calls:
            logger.warning("LLM returned an empty response")
            if exhausted:
                response.add_tool_call(llm._llm_empty_response_call(raw.id))

        return response

    def chat(self, request: LLMRequest) -> LLMResponse:
        """Send chat request, initializing client if needed."""
        self._ensure_client()

        if self._client is None:
            raise RuntimeError(f"{self.name} not configured (set {self._var_name})")

        try:
            raw_request = self.convert_request(request)
            llm._log_raw("LLM_RAW_REQUEST", self._name, self._model_name, raw_request)
            raw_response = self._client.responses.create(**raw_request)
            llm._log_raw("LLM_RAW_RESPONSE", self._name, self._model_name, raw_response)
            return self.convert_response(raw_response)
        except Exception as e:
            error = f"Exception while communicating with LLM: {e}"
            logger.exception(f"[AIProvider.chat]: {error}")
            return LLMResponse().with_error(error)

