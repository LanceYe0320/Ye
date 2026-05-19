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
