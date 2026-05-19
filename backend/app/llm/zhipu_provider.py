import json
import logging

from openai import AsyncOpenAI

from app.config import settings
from app.llm.base_provider import (
    BaseLLMProvider,
    ChatMessage,
    ModelInfo,
    StreamingChunk,
    ToolDefinition,
)

logger = logging.getLogger(__name__)

MODELS = {
    "glm-4-plus": ModelInfo(name="glm-4-plus", provider="zhipu", max_tokens=128000),
    "glm-4-flash": ModelInfo(name="glm-4-flash", provider="zhipu", max_tokens=128000),
    "glm-4-long": ModelInfo(name="glm-4-long", provider="zhipu", max_tokens=128000),
    "glm-4": ModelInfo(name="glm-4", provider="zhipu", max_tokens=128000),
}


class ZhipuProvider(BaseLLMProvider):
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.ZHIPU_API_KEY,
            base_url=settings.ZHIPU_BASE_URL,
        )

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

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        model = model or settings.ZHIPU_MODEL
        kwargs: dict = {
            "model": model,
            "messages": self._format_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = self._format_tools(tools)

        active_tool_calls: dict[int, dict] = {}

        try:
            stream = await self.client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                # Text content
                if delta.content:
                    yield StreamingChunk(type="text_delta", text=delta.content)

                # Tool calls
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in active_tool_calls:
                            active_tool_calls[idx] = {
                                "id": tc_delta.id or "",
                                "name": "",
                                "arguments": "",
                            }
                            yield StreamingChunk(
                                type="tool_call_start",
                                tool_call_id=tc_delta.id or "",
                            )

                        tc = active_tool_calls[idx]
                        if tc_delta.id:
                            tc["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tc["name"] = tc_delta.function.name
                                yield StreamingChunk(
                                    type="tool_call_delta",
                                    tool_call_id=tc["id"],
                                    tool_call_name=tc_delta.function.name,
                                )
                            if tc_delta.function.arguments:
                                tc["arguments"] += tc_delta.function.arguments

                # Finish
                if choice.finish_reason:
                    # Emit completed tool calls
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

                    if hasattr(chunk, "usage") and chunk.usage:
                        yield StreamingChunk(
                            type="usage",
                            usage={
                                "prompt_tokens": chunk.usage.prompt_tokens or 0,
                                "completion_tokens": chunk.usage.completion_tokens or 0,
                                "total_tokens": chunk.usage.total_tokens or 0,
                            },
                        )

                    yield StreamingChunk(type="done")

        except Exception as e:
            logger.error(f"Zhipu API error: {e}")
            yield StreamingChunk(type="error", text=str(e))

    async def count_tokens(self, text: str) -> int:
        return len(text) // 4  # Rough estimate

    def get_model_info(self, model: str) -> ModelInfo:
        return MODELS.get(model, ModelInfo(name=model, provider="zhipu", max_tokens=4096))

    async def validate_api_key(self) -> bool:
        try:
            await self.client.models.list()
            return True
        except Exception:
            return False
