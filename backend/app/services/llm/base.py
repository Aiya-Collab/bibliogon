from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class Message:
    role: str
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    raw_response: dict[str, Any] = field(default_factory=dict)


class LLMProviderError(Exception):
    pass


class LLMProvider(ABC):
    @abstractmethod
    def get_provider_name(self) -> str: ...

    @abstractmethod
    def get_model_name(self) -> str: ...

    @abstractmethod
    async def chat(self, messages: list[Message], **kwargs: Any) -> LLMResponse: ...

    async def stream_chat(self, messages: list[Message], **kwargs: Any) -> AsyncIterator[str]:
        response = await self.chat(messages, **kwargs)
        yield response.content
