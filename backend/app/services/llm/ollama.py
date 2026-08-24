import time
from typing import Any

import httpx

from .base import LLMProvider, LLMProviderError, LLMResponse, Message


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str = "http://127.0.0.1:11434", model: str = "qwen3:8b", timeout_s: int = 600, max_retries: int = 2):
        self.base_url, self.model, self.timeout_s, self.max_retries = base_url.rstrip("/"), model, timeout_s, max_retries

    def get_provider_name(self) -> str:
        return "ollama"

    def get_model_name(self) -> str:
        return self.model

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/api/tags")
            return response.status_code == 200 and any(self.model in item.get("name", "") for item in response.json().get("models", []))
        except Exception:
            return False

    async def chat(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        payload = {"model": self.model, "messages": [m.__dict__ for m in messages], "stream": False,
                   "options": {"temperature": kwargs.get("temperature", 0.3), "top_p": kwargs.get("top_p", 0.9), "num_ctx": kwargs.get("num_ctx", 8192)}}
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                started = time.perf_counter()
                async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                    response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                body = response.json()
                usage = body.get("prompt_eval_count", 0), body.get("eval_count", 0)
                return LLMResponse(body.get("message", {}).get("content", ""), self.model, usage[0], usage[1], int((time.perf_counter() - started) * 1000), body)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                last = exc
                if attempt >= self.max_retries:
                    break
        raise LLMProviderError(str(last)) from last
