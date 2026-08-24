"""MiniMax Provider - M3 reasoning model, OpenAI 兼容。

POC 验证（2026-08-24）：
- 接口连通：✅ 0.22s
- 写小说：✅ max_tokens=4000 输出 617 字顶级
- 蒸馏：✅ JSON 提取 6 人物 + 时空 + 冲突
- 长上下文：✅ 10K 字符 3.61s
- 关键发现：M3 是 reasoning model，max_tokens<4000 时思考耗光 token 正文为空

治理红线：不影响 R1-R8（治理门禁不依赖 provider），AiRunLog 记录 provider_name。
"""
import re
import time
from typing import Any

import httpx

from .base import LLMProvider, LLMProviderError, LLMResponse, Message


# M3 默认 max_tokens 下限，避免 reasoning 耗光 token
MINIMAX_DEFAULT_MAX_TOKENS = 4000


class MiniMaxProvider(LLMProvider):
    """MiniMax M3 reasoning model.

    base_url:  https://api.minimaxi.com/v1
    api_key:   MINIMAX_API_KEY 环境变量
    model:     MiniMax-M3（M3 是 reasoning model，必须 max_tokens >= 4000）
    """

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def get_provider_name(self) -> str:
        return "minimax"

    def get_model_name(self) -> str:
        return self.model

    async def chat(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": [m.__dict__ for m in messages],
            "stream": False,
        }
        # 强制 max_tokens >= 4000（M3 reasoning 模型特征）
        max_tokens = kwargs.get("max_tokens", MINIMAX_DEFAULT_MAX_TOKENS)
        if max_tokens < MINIMAX_DEFAULT_MAX_TOKENS:
            max_tokens = MINIMAX_DEFAULT_MAX_TOKENS
        payload["max_tokens"] = max_tokens
        payload["temperature"] = kwargs.get("temperature", 0.7)

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
            # M3 返回 reasoning_content（思考块）和 content（正式回复），两者合并去 think 标签
            choice = body.get("choices", [{}])[0].get("message", {})
            raw = (
                str(choice.get("content") or "")
                + str(choice.get("reasoning_content") or "")
            )
            # 剥离 <think>...</think> 块
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