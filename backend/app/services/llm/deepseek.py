"""DeepSeek Provider - deepseek-v4-flash, OpenAI 兼容。

DeepSeek 平台：https://platform.deepseek.com/
base_url:  https://api.deepseek.com/v1
model:     deepseek-v4-flash（快/便宜版本，比 V3 主模型便宜）

POC 待跑（sandbox 异常时跳过）：
- 用户已注册并获取 key（使用.txt 第 8-9 行）
- 卡 H 蒸馏可用作 deepseek-v4-flash 备选（user 已确认 DeepSeek 不是首选蒸馏）
"""
import time
from typing import Any

import httpx

from .base import LLMProvider, LLMProviderError, LLMResponse, Message


class DeepSeekProvider(LLMProvider):
    """DeepSeek v4-flash model, OpenAI 兼容。

    base_url:  https://api.deepseek.com/v1
    api_key:   DEEPSEEK_API_KEY 环境变量
    model:     deepseek-v4-flash
    """

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def get_provider_name(self) -> str:
        return "deepseek"

    def get_model_name(self) -> str:
        return self.model

    async def chat(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": [m.__dict__ for m in messages],
            "stream": False,
        }
        payload.update({k: v for k, v in kwargs.items() if k in {"temperature", "max_tokens"}})

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
            response.raise_for_status()
            body = response.json()
            choice = body.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = body.get("usage", {})
            return LLMResponse(
                str(choice),
                body.get("model", self.model),
                int(usage.get("prompt_tokens", 0)),
                int(usage.get("completion_tokens", 0)),
                int((time.perf_counter() - started) * 1000),
                body,
            )
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise LLMProviderError(str(exc)) from exc