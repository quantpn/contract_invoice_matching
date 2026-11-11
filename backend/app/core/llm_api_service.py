"""LLMApiService refactored 1:1 from et-addons/ai/utils/llm_api_service.py.
Handles OpenAI (/responses, /embeddings, /audio/transcriptions) and Google Gemini (:generateContent, /openai/embeddings),
including multi-turn tool calling and __end_message early termination.
"""
import copy
import json
import logging
import os
import time
import typing
from typing import Any, Callable

import requests

from .ai_logging import ai_response_logging, api_call_logging, get_ai_logging_session
from .exceptions import UserError
from .llm_providers import get_llm_model_and_reasoning

_logger = logging.getLogger(__name__)


class Embedding(typing.TypedDict):
    index: int
    embedding: list[float]
    object: str


class EmbeddingResponse(typing.TypedDict):
    object: str
    data: list[Embedding]
    model: str
    usage: dict


# Global runtime config store (replaces odoo ir.config_parameter while keeping identical keys)
_RUNTIME_CONFIG: dict[str, str] = {
    "ai.openai_key": os.getenv("ODOO_AI_CHATGPT_TOKEN") or os.getenv("OPENAI_API_KEY") or "",
    "ai.google_key": os.getenv("ODOO_AI_GEMINI_TOKEN") or os.getenv("GEMINI_API_KEY") or "",
    "ai.max_successive_calls": "20",
    "ai.max_tool_calls_per_call": "20",
}


def set_config_parameter(key: str, value: str) -> None:
    _RUNTIME_CONFIG[key] = value


def get_config_parameter(key: str, default: str = "") -> str:
    return _RUNTIME_CONFIG.get(key) or default


class LLMApiService:
    def __init__(self, provider: str = "openai", api_key: str | None = None) -> None:
        self.provider = provider
        self.explicit_api_key = api_key
        base_url = None
        if self.provider == "openai":
            base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        elif self.provider == "google":
            base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
        else:
            raise NotImplementedError(f"Unsupported provider: {self.provider}")

        self.base_url = base_url

    def get_embedding(
        self,
        input: str | list[str] | list[int] | list[list[int]],
        dimensions: int | None = 1536,
        model: str = "text-embedding-3-small",
        encoding_format: str | None = None,
        user: str | None = None,
    ) -> EmbeddingResponse:
        body: dict[str, Any] = {
            "input": input,
            "model": model,
        }
        self._add_if_set(body, "encoding_format", encoding_format)
        if self.provider == "openai" and dimensions:
            self._add_if_set(body, "dimensions", dimensions)
        self._add_if_set(body, "user", user)

        return self._request(
            method="post",
            endpoint="/embeddings",
            headers=self._get_base_headers(),
            body=body,
        )

    def _format_for_embedding(self, content: str, mode: str, title: str | None = None) -> str:
        if self.provider != "google":
            return content

        if mode == "query":
            return f"task: question answering | query: {content}"

        if mode == "document":
            return f"title: {title} | text: {content}"
        return content

    def get_transcription(
        self,
        data: bytes,
        mimetype: str = "audio/ogg",
        model: str = "whisper-1",
        language: str | None = None,
        prompt: str | None = None,
        response_format: str = "verbose_json",
        temperature: float | None = None,
    ) -> str | None:
        if response_format not in ["json", "verbose_json"]:
            raise NotImplementedError(
                f"Response format '{response_format}' is not supported. Request must return json!"
            )

        headers = {
            "Authorization": f"Bearer {self._get_api_token()}",
        }
        body: dict[str, Any] = {
            "model": model,
            "response_format": response_format,
        }
        self._add_if_set(body, "prompt", prompt)
        self._add_if_set(body, "language", language)
        self._add_if_set(body, "temperature", temperature)

        start = time.perf_counter()
        response = self._request(
            method="post",
            endpoint="/audio/transcriptions",
            headers=headers,
            body={},
            data=body,
            files={"file": ("audio", data, mimetype)},
            timeout=550,
        )
        elapsed = time.perf_counter() - start

        if not response or "text" not in response:
            _logger.warning("No transcription received.")
            return None

        _logger.info("Transcription job done in %.1fs", elapsed)
        return response.get("text")

    def _add_if_set(self, d: dict, key: str, value: Any) -> None:
        if value is not None:
            d[key] = value

    def _get_base_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._get_api_token()}",
        }

    def _get_api_token(self) -> str:
        if self.explicit_api_key:
            return self.explicit_api_key

        provider_config = {
            "openai": {
                "config_key": "ai.openai_key",
                "env_vars": ["ODOO_AI_CHATGPT_TOKEN", "OPENAI_API_KEY"],
            },
            "google": {
                "config_key": "ai.google_key",
                "env_vars": ["ODOO_AI_GEMINI_TOKEN", "GEMINI_API_KEY"],
            },
        }
        config = provider_config.get(self.provider)
        if config is None:
            raise UserError(f"Unsupported provider '{self.provider}'")

        api_key = get_config_parameter(config["config_key"])
        if not api_key:
            for env_var in config["env_vars"]:
                if val := os.getenv(env_var):
                    api_key = val
                    break

        if api_key:
            return api_key.strip()

        raise UserError(
            f"Chưa cấu hình API Key cho nhà cung cấp '{self.provider}'. "
            "Vui lòng nhập API Key trên phần Cấu hình AI ở thanh công cụ."
        )

    def _request(
        self,
        method: str,
        endpoint: str,
        headers: dict[str, str],
        body: dict,
        data: dict | None = None,
        files: dict | None = None,
        params: dict | None = None,
        base_url: str | None = None,
        timeout: int = 90,
    ) -> dict:
        route = f"{base_url or self.base_url}/{endpoint.strip('/')}"
        try:
            response = requests.request(
                method,
                route,
                params=params,
                headers=headers,
                json=body if not files else None,
                data=data,
                timeout=timeout,
                files=files,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            error = repr(e)
            if e.response is not None:
                try:
                    resp_json = e.response.json()
                    if isinstance(resp_json, list) and resp_json:
                        resp_json = resp_json[0]
                    if isinstance(resp_json, dict) and (
                        json_error := resp_json.get("error", {}).get("message")
                    ):
                        error = json_error
                    else:
                        error = json.dumps(resp_json, indent=2, ensure_ascii=False)
                except ValueError:
                    error = e.response.text
                if not error:
                    error = repr(e)

            _logger.warning("LLM API request failed: %s", error)
            raise UserError(f"LLM API Error ({self.provider}): {error}")

    def _request_llm_openai(
        self,
        llm_model: str,
        system_prompts: list[str],
        user_prompts: list[str],
        tools: dict | None = None,
        files: list[dict] | None = None,
        schema: dict | None = None,
        temperature: float = 0.5,
        inputs: tuple | list = (),
        web_grounding: bool = False,
    ):
        """Make a single request to the OpenAI /responses endpoint.
        Refactored from et-addons/ai/utils/llm_api_service.py.
        """
        llm_model, reasoning = get_llm_model_and_reasoning(llm_model, temperature)
        user_content = [{"type": "input_text", "text": prompt} for prompt in user_prompts]

        if files:
            def _build_file(idx, file):
                if file["mimetype"] == "text/plain":
                    return {
                        "type": "input_text",
                        "text": f"[{file.get('file_ref', f'<file_#{idx}>')}]\n{file['value']}",
                    }

                file_uri = f"data:{file['mimetype']};base64,{file['value']}"
                if file["mimetype"] == "application/pdf":
                    return {
                        "type": "input_file",
                        "filename": f"file_{idx}.pdf",
                        "file_data": file_uri,
                    }

                assert file["mimetype"].startswith("image/")
                return {"type": "input_image", "image_url": file_uri, "detail": "high"}

            user_content.extend(_build_file(idx, file) for idx, file in enumerate(files, start=1))

        input_messages = []
        if system_prompts:
            input_messages.append(
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": prompt} for prompt in system_prompts],
                }
            )
        if user_content:
            input_messages.append({"role": "user", "content": user_content})
        input_messages.extend(inputs)

        body: dict[str, Any] = {
            "model": llm_model,
            "input": input_messages,
            "store": False,
        }

        if reasoning is None:
            body["temperature"] = temperature
        elif not tools and web_grounding:
            body["reasoning"] = {"effort": "none"}
        else:
            body["include"] = ["reasoning.encrypted_content"]
            body["reasoning"] = {"effort": reasoning}

        if schema:
            body["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "json_schema",
                    "schema": schema,
                    "strict": True,
                },
            }

        if tools:
            body["tools"] = self._to_open_ai_tool_schema(
                [
                    {
                        "description": tool_description,
                        "parameters": copy.deepcopy(tool_parameter_schema),
                        "type": "function",
                        "name": tool_name,
                        "strict": True,
                    }
                    for tool_name, (
                        tool_description,
                        __,
                        __,
                        tool_parameter_schema,
                    ) in tools.items()
                ]
            )
            body["parallel_tool_calls"] = True

        if web_grounding:
            body.setdefault("tools", []).append({"type": "web_search_preview"})

        with api_call_logging(body["input"], tools) as record_response:
            response, to_call, next_inputs, request_token_usage = self._request_llm_openai_helper(
                body, tools, inputs
            )
            if record_response:
                record_response(to_call, response, request_token_usage)
            return response, to_call, next_inputs

    def _request_llm_openai_helper(self, body: dict, tools: dict | None = None, inputs=()):
        llm_response = self._request(
            method="post",
            endpoint="/responses",
            headers=self._get_base_headers(),
            body=body,
        )

        to_call = []
        response = []
        next_inputs = list(inputs or ())

        output_lines = llm_response.get("output") or []
        has_tool_calls = any(line.get("type") == "function_call" for line in output_lines)

        for line in output_lines:
            if line.get("type") == "function_call":
                tool_name = line.get("name", "")
                try:
                    arguments = json.loads(line.get("arguments") or "{}")
                except json.decoder.JSONDecodeError:
                    _logger.error("AI: Malformed arguments: %s", line)
                    continue

                to_call.append((tool_name, line.get("call_id"), arguments))
                next_inputs.append(line)

            elif not has_tool_calls:
                if text := line.get("text"):
                    response.append(text)
                elif line.get("type") == "message":
                    response.extend(t for c in line.get("content", ()) if (t := c.get("text")))

        request_token_usage = {}
        if usage := llm_response.get("usage"):
            request_token_usage["input_tokens"] = usage.get("input_tokens", 0)
            request_token_usage["cached_tokens"] = usage.get("input_tokens_details", {}).get(
                "cached_tokens", 0
            )
            request_token_usage["output_tokens"] = usage.get("output_tokens", 0)

        return response, to_call, next_inputs, request_token_usage

    def _clean_schema_for_gemini(self, schema: Any) -> Any:
        """Normalize JSON Schema for Gemini's responseSchema / functionDeclarations."""
        if not isinstance(schema, dict):
            return schema
        cleaned = {}
        for k, v in schema.items():
            if k == "additionalProperties":
                continue
            if k == "type" and isinstance(v, list):
                non_null = [t for t in v if t != "null"]
                cleaned["type"] = non_null[0] if non_null else "string"
                if "null" in v:
                    cleaned["nullable"] = True
            elif isinstance(v, dict):
                cleaned[k] = self._clean_schema_for_gemini(v)
            elif isinstance(v, list):
                cleaned[k] = [self._clean_schema_for_gemini(item) for item in v]
            else:
                cleaned[k] = v
        return cleaned

    def _request_llm_google(
        self,
        llm_model: str,
        system_prompts: list[str],
        user_prompts: list[str],
        tools: dict | None = None,
        files: list[dict] | None = None,
        schema: dict | None = None,
        temperature: float = 0.5,
        inputs: tuple | list = (),
        web_grounding: bool = False,
    ):
        """Make a single request to Google Gemini :generateContent API.
        Refactored from et-addons/ai/utils/llm_api_service.py.
        """
        llm_model, reasoning = get_llm_model_and_reasoning(llm_model, temperature)
        body: dict[str, Any] = {
            "contents": [],
            "generationConfig": {
                "temperature": temperature,
            },
        }

        if system_prompts:
            body["systemInstruction"] = {
                "parts": [{"text": prompt} for prompt in system_prompts],
            }
        if user_prompts:
            body["contents"].append(
                {
                    "role": "user",
                    "parts": [{"text": prompt} for prompt in user_prompts],
                }
            )

        body["contents"].extend(inputs)

        if files:
            def _build_file(idx, file):
                if file["mimetype"] == "text/plain":
                    return {"text": f"[{file.get('file_ref', f'<file_#{idx}>')}]\n{file['value']}"}
                return {"inline_data": {"mime_type": file["mimetype"], "data": file["value"]}}

            body["contents"].append(
                {
                    "role": "user",
                    "parts": [_build_file(idx, file) for idx, file in enumerate(files, start=1)],
                }
            )

        if schema and not tools:
            body["generationConfig"]["responseMimeType"] = "application/json"
            body["generationConfig"]["responseSchema"] = self._clean_schema_for_gemini(schema)

        if tools:
            body["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "description": tool_description,
                            "parameters": self._clean_schema_for_gemini(
                                copy.deepcopy(tool_parameter_schema)
                            ),
                            "name": tool_name,
                        }
                        for tool_name, (
                            tool_description,
                            __,
                            __,
                            tool_parameter_schema,
                        ) in tools.items()
                    ]
                }
            ]

        if llm_model == "gemini-2.5-flash":
            body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 512}

        with api_call_logging(body["contents"], tools) as record_response:
            response = None
            to_call = []
            next_inputs = list(inputs)
            request_token_usage = {}
            for attempt in range(3):
                response, to_call, next_inputs, request_token_usage = (
                    self._request_llm_google_helper(body, llm_model, inputs)
                )
                if response or to_call:
                    break
                _logger.warning("Gemini failed to generate a response, retrying...")
            if not (response or to_call):
                response = ["Error: failed to generate a response, try again later."]
            if record_response:
                record_response(to_call, response, request_token_usage)
            return response, to_call, next_inputs

    def _request_llm_google_helper(self, body: dict, llm_model: str, inputs=()):
        llm_response = self._request(
            method="post",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            headers={"x-goog-api-key": self._get_api_token(), "Content-Type": "application/json"},
            endpoint=f"/models/{llm_model}:generateContent",
            params={},
            body=body,
        )

        to_call = []
        response = []
        next_inputs = list(inputs or ())

        candidates = llm_response.get("candidates") or []
        has_tool_calls = any(
            part.get("functionCall")
            for candidate in candidates
            for part in candidate.get("content", {}).get("parts") or []
        )

        for candidate in candidates:
            for line in candidate.get("content", {}).get("parts") or ():
                if f_info := line.get("functionCall"):
                    to_call.append((f_info["name"], f_info["name"], f_info.get("args", {})))
                    next_inputs.append({"role": "model", "parts": [line]})
                elif not has_tool_calls:
                    if r := line.get("text"):
                        response.append(r)

        request_token_usage = {}
        if usage := llm_response.get("usageMetadata"):
            request_token_usage["input_tokens"] = usage.get("promptTokenCount", 0)
            request_token_usage["cached_tokens"] = usage.get("cachedContentTokenCount", 0)
            request_token_usage["output_tokens"] = usage.get("candidatesTokenCount", 0)

        return response, to_call, next_inputs, request_token_usage

    def _request_llm(self, *args, **kwargs):
        if self.provider == "openai":
            return self._request_llm_openai(*args, **kwargs)
        if self.provider == "google":
            return self._request_llm_google(*args, **kwargs)
        raise NotImplementedError(f"Unsupported provider: {self.provider}")

    def request_llm(
        self,
        llm_model: str,
        system_prompts: list[str],
        user_prompts: list[str],
        tools: dict[str, tuple[str, bool, Callable[[dict[str, Any]], Any], dict]] | None = None,
        files: list[dict] | None = None,
        schema: dict | None = None,
        temperature: float = 0.5,
        inputs: list[dict] | None = None,
        web_grounding: bool = False,
    ) -> list[str]:
        """Orchestrate multi-step LLM calls and tool execution until completion."""
        with ai_response_logging(get_llm_model_and_reasoning(llm_model, temperature)[0]):
            return self._request_llm_silent(
                llm_model=llm_model,
                system_prompts=system_prompts,
                user_prompts=user_prompts,
                tools=tools,
                files=files,
                schema=schema,
                temperature=temperature,
                inputs=inputs,
                web_grounding=web_grounding,
            )

    def _request_llm_silent(
        self,
        llm_model: str,
        system_prompts: list[str],
        user_prompts: list[str],
        tools: dict[str, tuple[str, bool, Callable[[dict[str, Any]], Any], dict]] | None = None,
        files: list[dict] | None = None,
        schema: dict | None = None,
        temperature: float = 0.5,
        inputs: list[dict] | None = None,
        web_grounding: bool = False,
    ) -> list[str]:
        """Wraps `_request_llm` to handle multiple calls, tool execution, and `__end_message` termination."""
        AI_MAX_SUCCESSIVE_CALLS = int(get_config_parameter("ai.max_successive_calls", "20"))
        AI_MAX_TOOL_CALLS_PER_CALL = int(get_config_parameter("ai.max_tool_calls_per_call", "20"))

        if tools:
            tools = copy.deepcopy(tools)
            for __, allow_end_message, __, tool_parameter_schema in tools.values():
                if (
                    allow_end_message
                    and "__end_message" not in tool_parameter_schema["properties"]
                ):
                    tool_parameter_schema["properties"]["__end_message"] = {
                        "type": "string",
                        "description": (
                            "If you are not waiting a result and you are done, write here your last message "
                            "(it must follow the instructions). If you will do an action after this one, leave it empty."
                        ),
                    }
                if (
                    "__end_message" in tool_parameter_schema["properties"]
                    and "__end_message" not in tool_parameter_schema["required"]
                ):
                    tool_parameter_schema["required"].append("__end_message")

        inputs = list(inputs or [])

        if self.provider == "google":
            converted_inputs = []
            for i in inputs:
                if "parts" in i:
                    converted_inputs.append(i)
                else:
                    converted_inputs.append(
                        {
                            "role": "user" if i.get("role") == "user" else "model",
                            "parts": [{"text": str(i.get("content", ""))}],
                        }
                    )
            inputs = converted_inputs

        all_responses: list[str] = []
        api_call = 0
        for api_call in range(AI_MAX_SUCCESSIVE_CALLS):
            responses, next_actions, inputs = self._request_llm(
                llm_model,
                system_prompts,
                user_prompts if api_call == 0 else [],
                files=files if api_call == 0 else None,
                inputs=inputs,
                schema=schema if not tools else None,
                tools=tools,
                temperature=temperature,
                web_grounding=web_grounding,
            )
            all_responses.extend(responses)

            if not next_actions:
                break

            done = False
            session = get_ai_logging_session()
            if session:
                session["tool_calls"] += min(len(next_actions), AI_MAX_TOOL_CALLS_PER_CALL)

            for i, (tool_name, call_id, arguments) in enumerate(next_actions):
                if i >= AI_MAX_TOOL_CALLS_PER_CALL:
                    _logger.warning("AI: Tool call limit reached, stopping further tool calls")
                    inputs.append(
                        self._build_tool_call_response(
                            call_id,
                            "Error: This tool call isn't processed because of tool call limit, try again",
                        )
                    )
                    continue

                if not tools or tool_name not in tools:
                    _logger.error("AI: Try to call a forbidden action %s", tool_name)
                    inputs.append(
                        self._build_tool_call_response(
                            call_id,
                            f"Error: unknown tool '{tool_name}'. Try again with the correct tool name.",
                        )
                    )
                    continue

                has_end_message = "__end_message" in arguments
                end_message = arguments.pop("__end_message", None)
                result, error = tools[tool_name][2](arguments=arguments)

                inputs.append(self._build_tool_call_response(call_id, result))

                if has_end_message and error is None:
                    done = True
                    if end_response := end_message and end_message.strip():
                        all_responses.append(end_response)
                        _logger.info("AI: action terminate early: %s", end_response)
                    else:
                        _logger.info("AI: action terminate early with empty message")

            if done:
                break

        _logger.info("AI: API calls %s", api_call + 1)

        if not all_responses:
            error_msg = "Processing loop ended with no response."
            if api_call + 1 >= AI_MAX_SUCCESSIVE_CALLS:
                error_msg = "Number of successive API calls exceeded, please try again with a more precise request."
            raise ValueError(error_msg)

        return all_responses

    def _to_open_ai_tool_schema(self, schema: list[dict]) -> list[dict]:
        """Convert the tool schema for OpenAI /responses strict mode."""
        if self.provider != "openai":
            return schema

        for tool in schema:
            required = tool["parameters"]["required"]
            non_required = set(tool["parameters"]["properties"]) - set(required)
            for name in non_required:
                prop_type = tool["parameters"]["properties"][name]["type"]
                if not isinstance(prop_type, list):
                    tool["parameters"]["properties"][name]["type"] = [prop_type, "null"]
            tool["parameters"]["required"].extend(non_required)
            tool["parameters"]["additionalProperties"] = False
        return schema

    def _build_tool_call_response(self, tool_call_id: str, return_value: Any) -> dict:
        """Build the response payload for a tool call."""
        if self.provider == "openai":
            return {
                "type": "function_call_output",
                "call_id": tool_call_id,
                "output": str(return_value),
            }

        if self.provider == "google":
            return {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "name": tool_call_id,
                            "response": {"result": str(return_value)},
                        },
                    }
                ],
            }

        raise NotImplementedError(f"Unsupported provider: {self.provider}")

