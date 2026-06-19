from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator


class ToolType(str, Enum):
    FUNCTION = "function"


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass
class ChatMessage:
    role: str  # "user", "assistant", "system", "tool"
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass
class StreamingChunk:
    type: str  # "text_delta", "tool_call_start", "tool_call_delta", "tool_call_end", "usage", "done"
    text: str = ""
    tool_call_id: str = ""
    tool_call_name: str = ""
    tool_call_arguments: str = ""
    usage: dict[str, int] = field(default_factory=dict)


@dataclass
class ModelInfo:
    name: str
    provider: str
    max_tokens: int
    supports_tools: bool = True
    supports_vision: bool = False


class ToolAbortError(Exception):
    """Raised when a tool failure triggers ABORT strategy — propagates to the agentic loop."""
    def __init__(self, tool_name: str, error_message: str):
        self.tool_name = tool_name
        self.error_message = error_message
        super().__init__(f"Tool '{tool_name}' aborted: {error_message}")


class ToolEscalationError(Exception):
    """Raised when a tool failure triggers ESCALATE strategy — needs human intervention."""
    def __init__(self, tool_name: str, error_message: str):
        self.tool_name = tool_name
        self.error_message = error_message
        super().__init__(f"Tool '{tool_name}' requires human intervention: {error_message}")


class BaseLLMProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamingChunk]:
        """Stream chat completions."""
        ...

    @abstractmethod
    async def count_tokens(self, text: str) -> int:
        """Estimate token count for text."""
        ...

    @abstractmethod
    def get_model_info(self, model: str) -> ModelInfo:
        """Get information about a specific model."""
        ...

    @abstractmethod
    async def validate_api_key(self) -> bool:
        """Check if the configured API key is valid."""
        ...
