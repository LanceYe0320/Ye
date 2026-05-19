import json
import logging
from typing import Any, AsyncIterator, Callable, Awaitable

from app.llm.base_provider import (
    BaseLLMProvider,
    ChatMessage,
    StreamingChunk,
    ToolCall,
    ToolDefinition,
    ToolResult,
)

logger = logging.getLogger(__name__)

ToolHandler = Callable[..., Awaitable[str]]


class ToolExecutor:
    def __init__(self, provider: BaseLLMProvider):
        self.provider = provider
        self._handlers: dict[str, ToolHandler] = {}
        self._definitions: list[ToolDefinition] = []

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: ToolHandler,
    ):
        self._handlers[name] = handler
        self._definitions.append(
            ToolDefinition(name=name, description=description, parameters=parameters)
        )

    @property
    def definitions(self) -> list[ToolDefinition]:
        return self._definitions

    async def execute_tool(self, tool_call: ToolCall) -> ToolResult:
        handler = self._handlers.get(tool_call.name)
        if not handler:
            return ToolResult(
                tool_call_id=tool_call.id,
                content=f"Unknown tool: {tool_call.name}",
                is_error=True,
            )
        try:
            result = await handler(**tool_call.arguments)
            return ToolResult(tool_call_id=tool_call.id, content=result)
        except Exception as e:
            logger.error(f"Tool execution error ({tool_call.name}): {e}")
            return ToolResult(
                tool_call_id=tool_call.id,
                content=f"Error: {e}",
                is_error=True,
            )

    async def run_agentic_loop(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        max_iterations: int = 10,
    ) -> AsyncIterator[StreamingChunk]:
        current_messages = list(messages)

        for iteration in range(max_iterations):
            pending_tool_calls: list[ToolCall] = []
            assistant_content = ""
            collected_usage = {}

            async for chunk in self.provider.chat(
                messages=current_messages,
                tools=self._definitions if self._definitions else None,
                model=model,
            ):
                if chunk.type == "text_delta":
                    yield chunk

                elif chunk.type == "tool_call_end":
                    try:
                        args = json.loads(chunk.tool_call_arguments)
                    except json.JSONDecodeError:
                        args = {}
                    pending_tool_calls.append(
                        ToolCall(
                            id=chunk.tool_call_id,
                            name=chunk.tool_call_name,
                            arguments=args,
                        )
                    )
                    yield chunk

                elif chunk.type == "usage":
                    collected_usage = chunk.usage

                elif chunk.type == "done":
                    if not pending_tool_calls:
                        return

                    assistant_msg = ChatMessage(
                        role="assistant",
                        content=assistant_content,
                        tool_calls=pending_tool_calls,
                    )
                    current_messages.append(assistant_msg)

                    for tc in pending_tool_calls:
                        yield StreamingChunk(
                            type="tool_execution_start",
                            text=f"Executing: {tc.name}",
                            tool_call_id=tc.id,
                        )
                        result = await self.execute_tool(tc)

                        yield StreamingChunk(
                            type="tool_execution_result",
                            text=result.content[:2000],
                            tool_call_id=tc.id,
                        )

                        current_messages.append(
                            ChatMessage(
                                role="tool",
                                content=result.content,
                                tool_call_id=tc.id,
                            )
                        )

                elif chunk.type == "error":
                    yield chunk
                    return

        yield StreamingChunk(type="text_delta", text="[Reached maximum tool iterations]")
