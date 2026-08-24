import time
from typing import Any

import httpx

from .base import LLMProvider, LLMProviderError, LLMResponse, Message


class CloudMistProvider(LLMProvider):
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model

    def get_provider_name(self) -> str:
        return "cloudmist"

    def get_model_name(self) -> str:
        return self.model

    async def chat(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        payload = {"model": self.model, "messages": [m.__dict__ for m in messages], "stream": False}
        payload.update({k: v for k, v in kwargs.items() if k in {"temperature", "max_tokens"}})
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(f"{self.base_url}/chat/completions", json=payload,
                                              headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
            response.raise_for_status()
            body = response.json()
            choice = body.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = body.get("usage", {})
            return LLMResponse(str(choice), body.get("model", self.model), int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)), int((time.perf_counter() - started) * 1000), body)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise LLMProviderError(str(exc)) from exc
