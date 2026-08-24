"""Alibaba DashScope OpenAI-compatible Qwen provider."""
import time
from typing import Any

import httpx

from .base import LLMProvider, LLMProviderError, LLMResponse, Message

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
QWEN_MODELS = frozenset({"qwen3.8-max", "qwen3.7-max", "qwen3.7-plus", "qwen3.7-flash"})


class DashScopeProvider(LLMProvider):
    def __init__(self, base_url: str, api_key: str, model: str = "qwen3.7-max"):
        if model not in QWEN_MODELS:
            raise ValueError(f"unsupported DashScope model: {model}")
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model

    def get_provider_name(self) -> str:
        return "dashscope"

    def get_model_name(self) -> str:
        return self.model

    async def chat(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        # qwen3.8-max spends substantial budget on reasoning; keep its default bounded.
        requested = kwargs.get("max_tokens")
        max_tokens = min(int(requested), 1500) if requested is not None else 1500
        payload = {"model": self.model, "messages": [m.__dict__ for m in messages], "stream": False,
                   "max_tokens": max_tokens}
        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(f"{self.base_url}/chat/completions", json=payload,
                                              headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
            response.raise_for_status()
            body = response.json()
            message = body.get("choices", [{}])[0].get("message", {})
            content = message.get("content") or message.get("reasoning_content") or ""
            usage = body.get("usage", {})
            completion = usage.get("completion_tokens", usage.get("output_tokens", 0))
            return LLMResponse(str(content), body.get("model", self.model), int(usage.get("prompt_tokens", 0)),
                               int(completion), int((time.perf_counter() - started) * 1000), body)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError(str(exc)) from exc
