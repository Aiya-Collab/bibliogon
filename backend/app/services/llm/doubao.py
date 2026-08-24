"""豆包 (Doubao) Provider - 字节跳动火山引擎 / CloudMist 中转，OpenAI 兼容。

用户桌面 使用.txt (2026-08-24) 提供模型：
- doubao-seed-1-6-thinking-250615  ⚠️ **thinking 模式**：max_tokens 必须 ≥ 4000
- doubao-seed-2-0-mini-260428     ✅ 快速 mini 版，正常 max_tokens

特点（豆包官方介绍）：
- 中文网文适配天花板（番茄小说/京味/口语最强）
- 但长文不稳，复杂多线伏笔弱
- 适合对白润色、都市/言情/校园/生活流
- 不适合长篇、复杂多线伏笔、蒸馏结构化输出

治理红线：H-R1 AI 不得入正史，蒸馏后必须作者手动 adopt。
"""
import re
import time
from typing import Any

import httpx

from .base import LLMProvider, LLMProviderError, LLMResponse, Message


# 豆包 thinking 模式模型（max_tokens 必须足够大）
THINKING_MODELS = {"doubao-seed-1-6-thinking-250615"}
DOUBAO_DEFAULT_MAX_TOKENS = 4000
DOUBAO_MINI_DEFAULT_MAX_TOKENS = 2000


class DoubaoProvider(LLMProvider):
    """豆包 seed 系列 - OpenAI 兼容。

    base_url:  https://api.cloudmist.cloud/v1 （通过 CloudMist 中转，与 gpt-5.5 共用 base_url）
    api_key:   CLOUDMIST_API_KEY 环境变量（用户桌面使用.txt 第 1 行共用密钥）
    model:     doubao-seed-1-6-thinking-250615 或 doubao-seed-2-0-mini-260428
    """

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        # thinking 模式标志
        self.is_thinking = model in THINKING_MODELS
        self.default_max_tokens = (
            DOUBAO_DEFAULT_MAX_TOKENS if self.is_thinking else DOUBAO_MINI_DEFAULT_MAX_TOKENS
        )

    def get_provider_name(self) -> str:
        return "doubao"

    def get_model_name(self) -> str:
        return self.model

    async def chat(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": [m.__dict__ for m in messages],
            "stream": False,
        }
        # thinking 模式强制 max_tokens ≥ 4000（避免 reasoning 耗光 token）
        max_tokens = kwargs.get("max_tokens", self.default_max_tokens)
        if self.is_thinking and max_tokens < DOUBAO_DEFAULT_MAX_TOKENS:
            max_tokens = DOUBAO_DEFAULT_MAX_TOKENS
        payload["max_tokens"] = max_tokens
        payload["temperature"] = kwargs.get("temperature", 0.8)

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
            # thinking 模式可能返回 reasoning_content
            choice = body.get("choices", [{}])[0].get("message", {})
            raw = (
                str(choice.get("content") or "")
                + str(choice.get("reasoning_content") or "")
            )
            # 剥离 <think>...</think> 块（兼容豆包 thinking 格式）
            content = re.sub(r"<think>.*?</think>\s*", "", raw, flags=re.DOTALL).strip()
            usage = body.get("usage", {})
            return LLMResponse(
                content,
                body.get("model", self.model),
                int(usage.get("prompt_tokens", 0)),
                int(usage.get("completion_tokens", 0)),
                int((time.perf_counter() - started) * 1000),
                body,
            )
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise LLMProviderError(str(exc)) from exc