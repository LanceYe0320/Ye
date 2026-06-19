from __future__ import annotations

import asyncio
import json
import logging
import random
import time

from app.config import settings
from app.llm.base_provider import (
    BaseLLMProvider,
    ChatMessage,
    ModelInfo,
    StreamingChunk,
    ToolDefinition,
)

logger = logging.getLogger(__name__)

_RETRYABLE_ERRORS = {"rate_limit", "timeout", "connection", "overloaded", "529", "ssl", "index out of range", "close_notify", "readuntil", "application data"}
_RETRY_INITIAL_DELAY_MS = 2000
_RETRY_BACKOFF_FACTOR = 2
_RETRY_MAX_DELAY_MS = 30000
_RETRY_MAX_ATTEMPTS = 3

MODELS = {
    # GLM-5 系列（旗舰）
    "glm-5.2": ModelInfo(name="glm-5.2", provider="zhipu", max_tokens=1_000_000),
    "glm-5.1": ModelInfo(name="glm-5.1", provider="zhipu", max_tokens=200_000),
    "glm-5": ModelInfo(name="glm-5", provider="zhipu", max_tokens=128_000),
    "glm-5-turbo": ModelInfo(name="glm-5-turbo", provider="zhipu", max_tokens=128_000),
    # GLM-4.7 系列
    "glm-4.7": ModelInfo(name="glm-4.7", provider="zhipu", max_tokens=128_000),
    "glm-4.7-flashx": ModelInfo(name="glm-4.7-flashx", provider="zhipu", max_tokens=128_000),
    # GLM-4.6 系列
    "glm-4.6": ModelInfo(name="glm-4.6", provider="zhipu", max_tokens=200_000),
    # GLM-4 经典系列
    "glm-4-plus": ModelInfo(name="glm-4-plus", provider="zhipu", max_tokens=128_000),
    "glm-4-flash": ModelInfo(name="glm-4-flash", provider="zhipu", max_tokens=128_000),
    "glm-4-long": ModelInfo(name="glm-4-long", provider="zhipu", max_tokens=128_000),
    "glm-4": ModelInfo(name="glm-4", provider="zhipu", max_tokens=128_000),
}

_TOKEN_TTL_MS = 30 * 60 * 1000  # 30 minutes


def _b64url(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _generate_jwt(api_key: str) -> str:
    """Generate Zhipu JWT token using raw hmac — no PyJWT dependency."""
    import hmac
    import hashlib

    key_id, secret = api_key.split(".", 1)
    now_ms = int(round(time.time() * 1000))

    header = _b64url(json.dumps({"alg": "HS256", "sign_type": "SIGN"}).encode())
    payload = _b64url(json.dumps({
        "api_key": key_id,
        "exp": now_ms + _TOKEN_TTL_MS,
        "timestamp": now_ms,
    }).encode())

    msg = f"{header}.{payload}"
    sig = _b64url(hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest())
    return f"{msg}.{sig}"


def _parse_sse_line(line: str) -> dict | None:
    """Parse a single SSE line: 'data: {...}' → dict, or None."""
    if not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if payload == "[done]":
        return {"_done": True}
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


class ZhipuProvider(BaseLLMProvider):
    def __init__(self):
        self._api_key = settings.ZHIPU_API_KEY
        self._base_url = settings.ZHIPU_BASE_URL.rstrip("/")
        self._token: str | None = None
        self._token_at: float = 0.0
        self._http = None

    def _get_http(self):
        if self._http is None:
            from app.llm.raw_http import AsyncClient
            self._http = AsyncClient(timeout=180.0, connect_timeout=15.0)
        return self._http

    async def aclose(self):
        """Close the underlying HTTP client. Call on shutdown.

        Swallows 'Event loop is closed' / transport errors so callers can run
        this unconditionally in a finally block without noisy tracebacks during
        interpreter teardown.
        """
        if self._http is not None:
            try:
                await self._http.aclose()
            except (RuntimeError, OSError, Exception):
                pass
            self._http = None

    def _get_token(self) -> str:
        if self._token is None or time.time() - self._token_at > 600:
            self._token = _generate_jwt(self._api_key)
            self._token_at = time.time()
        return self._token

    def _format_messages(self, messages: list[ChatMessage]) -> list[dict]:
        result = []
        for msg in messages:
            d: dict = {"role": msg.role}
            if msg.tool_call_id:
                d["tool_call_id"] = msg.tool_call_id
                d["content"] = msg.content
            elif msg.tool_calls:
                d["content"] = msg.content or ""
                d["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in msg.tool_calls
                ]
            else:
                d["content"] = msg.content
            result.append(d)
        return result

    # Incremental message formatting cache
    _fmt_cache_key: int = 0
    _fmt_cache_result: list[dict] | None = None
    _fmt_cache_id: int = 0

    def _format_messages_fast(self, messages: list[ChatMessage]) -> list[dict]:
        if not messages:
            return []
        msg_count = len(messages)
        first_id = id(messages[0])

        # Always rebuild from scratch when messages change (tool results invalidate cache)
        if msg_count != self._fmt_cache_key:
            self._fmt_cache_result = self._format_messages(messages)
            self._fmt_cache_key = msg_count
            self._fmt_cache_id = first_id
            return self._fmt_cache_result

        if first_id == self._fmt_cache_id and self._fmt_cache_result is not None:
            return self._fmt_cache_result

        self._fmt_cache_result = self._format_messages(messages)
        self._fmt_cache_key = msg_count
        self._fmt_cache_id = first_id
        return self._fmt_cache_result

    @staticmethod
    def _format_one(msg: ChatMessage) -> dict:
        d: dict = {"role": msg.role}
        if msg.tool_call_id:
            d["tool_call_id"] = msg.tool_call_id
            d["content"] = msg.content
        elif msg.tool_calls:
            d["content"] = msg.content or ""
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in msg.tool_calls
            ]
        else:
            d["content"] = msg.content
        return d

    def _format_tools(self, tools: list[ToolDefinition]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    _cached_tools_key: tuple | None = None
    _cached_tools_value: list[dict] | None = None

    def _format_tools_cached(self, tools: list[ToolDefinition]) -> list[dict]:
        key = tuple((t.name, t.description) for t in tools)
        if key != self._cached_tools_key:
            self._cached_tools_key = key
            self._cached_tools_value = self._format_tools(tools)
        return self._cached_tools_value

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        _retry_count: int = 0,
    ):
        model = model or settings.ZHIPU_MODEL
        body: dict = {
            "model": model,
            "messages": self._format_messages_fast(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            body["tools"] = self._format_tools_cached(tools)
            body["tool_choice"] = "auto"

        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

        active_tool_calls: dict[int, dict] = {}

        try:
            client = self._get_http()
            json_body = json.dumps(body).encode("utf-8")
            req_headers = dict(headers)
            resp = await client.post(url, headers=req_headers, body=json_body)

            if resp.status == 401 and _retry_count < 2:
                # Token expired — force refresh and retry
                logger.info("401 received, refreshing JWT token and retrying")
                self._token = _generate_jwt(self._api_key)
                self._token_at = time.time()
                async for chunk in self.chat(
                    messages=messages, tools=tools, model=model,
                    temperature=temperature, max_tokens=max_tokens,
                    _retry_count=_retry_count + 1,
                ):
                    yield chunk
                return

            if resp.status >= 400:
                error_body = await resp.read()
                error_text = error_body.decode("utf-8", errors="replace")
                raise Exception(f"API {resp.status}: {error_text}")

            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue

                data = _parse_sse_line(line)
                if data is None:
                    continue
                if data.get("_done"):
                    for idx, tc in active_tool_calls.items():
                        try:
                            args = json.loads(tc["arguments"])
                        except json.JSONDecodeError:
                            args = {}
                        yield StreamingChunk(
                            type="tool_call_end",
                            tool_call_id=tc["id"],
                            tool_call_name=tc["name"],
                            tool_call_arguments=json.dumps(args),
                        )

                    yield StreamingChunk(type="done")
                    return

                choices = data.get("choices", [])
                if not choices:
                    continue

                choice = choices[0]
                delta = choice.get("delta", {})
                finish_reason = choice.get("finish_reason")

                content = delta.get("content")
                if content:
                    yield StreamingChunk(type="text_delta", text=content)

                tc_list = delta.get("tool_calls")
                if tc_list:
                    for tc_delta in tc_list:
                        idx = tc_delta.get("index", 0)
                        if idx not in active_tool_calls:
                            active_tool_calls[idx] = {
                                "id": tc_delta.get("id", ""),
                                "name": "",
                                "arguments": "",
                            }
                            yield StreamingChunk(
                                type="tool_call_start",
                                tool_call_id=tc_delta.get("id", ""),
                            )

                        tc = active_tool_calls[idx]
                        if tc_delta.get("id"):
                            tc["id"] = tc_delta["id"]
                        func = tc_delta.get("function", {})
                        if func.get("name"):
                            tc["name"] = func["name"]
                            yield StreamingChunk(
                                type="tool_call_delta",
                                tool_call_id=tc["id"],
                                tool_call_name=func["name"],
                            )
                        if func.get("arguments"):
                            tc["arguments"] += func["arguments"]

                if finish_reason:
                    for idx, tc in active_tool_calls.items():
                        try:
                            args = json.loads(tc["arguments"])
                        except json.JSONDecodeError:
                            args = {}
                        yield StreamingChunk(
                            type="tool_call_end",
                            tool_call_id=tc["id"],
                            tool_call_name=tc["name"],
                            tool_call_arguments=json.dumps(args),
                        )

                    usage_data = data.get("usage")
                    if usage_data:
                        yield StreamingChunk(
                            type="usage",
                            usage={
                                "prompt_tokens": usage_data.get("prompt_tokens", 0),
                                "completion_tokens": usage_data.get("completion_tokens", 0),
                                "total_tokens": usage_data.get("total_tokens", 0),
                            },
                        )

                    yield StreamingChunk(type="done")
                    return

        except Exception as e:
            import traceback
            error_str = str(e).lower()
            logger.error(f"Zhipu API error: {e}\n{traceback.format_exc()}")
            is_retryable = any(err in error_str for err in _RETRYABLE_ERRORS)
            if is_retryable and _retry_count < _RETRY_MAX_ATTEMPTS:
                delay_ms = _RETRY_INITIAL_DELAY_MS * (_RETRY_BACKOFF_FACTOR ** _retry_count)
                delay_ms = min(delay_ms, _RETRY_MAX_DELAY_MS)
                jitter = random.uniform(0.5, 1.5)
                wait = delay_ms * jitter / 1000
                logger.warning(f"Retryable API error (attempt {_retry_count + 1}/{_RETRY_MAX_ATTEMPTS}), retrying in {wait:.1f}s: {e}")
                await asyncio.sleep(wait)
                async for chunk in self.chat(
                    messages=messages,
                    tools=tools,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    _retry_count=_retry_count + 1,
                ):
                    yield chunk
                return
            logger.error(f"Zhipu API error: {e}")
            yield StreamingChunk(type="error", text=str(e))

    async def count_tokens(self, text: str) -> int:
        # Better estimation for GLM tokenizer:
        # Chinese chars ~1.3 tokens, ASCII words ~0.25 tokens per char
        # Code/punctuation ~0.4 tokens per char
        chinese = 0
        ascii_alpha = 0
        other = 0
        for c in text:
            if '一' <= c <= '鿿':
                chinese += 1
            elif c.isascii() and (c.isalpha() or c == '_'):
                ascii_alpha += 1
            else:
                other += 1
        # ASCII words: avg ~5 chars per word, ~1 token per word
        words_approx = ascii_alpha / 4.5
        return int(chinese * 1.3 + words_approx + other * 0.4)

    def get_model_info(self, model: str) -> ModelInfo:
        return MODELS.get(model, ModelInfo(name=model, provider="zhipu", max_tokens=4096))

    async def validate_api_key(self) -> bool:
        try:
            client = self._get_http()
            resp = await client.get(
                f"{self._base_url}/models",
                headers={"Authorization": f"Bearer {self._get_token()}"},
            )
            return resp.status == 200
        except Exception:
            return False
