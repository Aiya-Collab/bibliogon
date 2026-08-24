"""Standardized error response schema for AI novel platform.

Engineering goals (Phase F Patch 004):
  - Frontend can parse a single error envelope regardless of failure layer
  - Error codes are stable; messages are human-readable; hints are actionable
  - Every error response carries: code / message / hint / retryable / context

Frontend contract (response body):
    {
      "error": {
        "code": "provider_timeout",
        "message": "qwen3:8b 蒸馏超时",
        "hint": "Provider 响应超时…",
        "retryable": true,
        "context": { provider, model, ... },
        "detail": "underlying error string"
      }
    }
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Error taxonomy
# ---------------------------------------------------------------------------

class ErrorCode(str, Enum):
    # --- 4xx: client errors ---
    BOOK_NOT_FOUND = "book_not_found"
    RUN_NOT_FOUND = "run_not_found"
    STAGING_NOT_FOUND = "staging_not_found"
    UNKNOWN_PROVIDER = "unknown_provider"
    INVALID_MODEL = "invalid_model"
    FILE_PARSE_ERROR = "file_parse_error"

    # --- 5xx: server / dependency errors ---
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_AUTH = "provider_auth_error"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    PROVIDER_BAD_REQUEST = "provider_bad_request"
    PROVIDER_UPSTREAM = "provider_upstream_error"
    PROVIDER_EMPTY_RESPONSE = "provider_empty_response"
    PROVIDER_SCHEMA_ERROR = "provider_schema_error"
    INTERNAL_ERROR = "internal_error"

    @property
    def default_http(self) -> int:
        m = {
            "BOOK_NOT_FOUND": 404, "RUN_NOT_FOUND": 404, "STAGING_NOT_FOUND": 404,
            "UNKNOWN_PROVIDER": 400, "INVALID_MODEL": 400, "FILE_PARSE_ERROR": 400,
            "PROVIDER_AUTH": 502, "PROVIDER_BAD_REQUEST": 502,
            "PROVIDER_RATE_LIMITED": 429, "PROVIDER_TIMEOUT": 504,
            "PROVIDER_UNAVAILABLE": 503, "PROVIDER_UPSTREAM": 502,
            "PROVIDER_EMPTY_RESPONSE": 502, "PROVIDER_SCHEMA_ERROR": 502,
            "INTERNAL_ERROR": 500,
        }
        return m[self.name]


HINTS: Dict[ErrorCode, str] = {
    ErrorCode.BOOK_NOT_FOUND: "请先在项目里创建这本书再试。",
    ErrorCode.RUN_NOT_FOUND: "蒸馏任务不存在或已被删除。",
    ErrorCode.STAGING_NOT_FOUND: "该候选条目已被采纳或拒绝。",
    ErrorCode.UNKNOWN_PROVIDER: "请从 ollama/cloudmist/deepseek/minimax/dashscope/doubao 中选择一个。",
    ErrorCode.INVALID_MODEL: "请检查模型名拼写（如 qwen3:8b / gpt-5.5 / claude-sonnet-4-6）。",
    ErrorCode.FILE_PARSE_ERROR: "请上传 UTF-8 编码的纯文本或 markdown 文件。",
    ErrorCode.PROVIDER_UNAVAILABLE: "请检查 Provider 是否启动 / API key 是否配置（参考 docker-compose 环境变量）。",
    ErrorCode.PROVIDER_TIMEOUT: "Provider 响应超时，请稍后重试或切换更快的 Provider。",
    ErrorCode.PROVIDER_AUTH: "API key 无权访问该模型，请联系管理员。",
    ErrorCode.PROVIDER_RATE_LIMITED: "上游限流，请稍候再试或切换 Provider。",
    ErrorCode.PROVIDER_BAD_REQUEST: "请求格式被上游拒绝，请检查模型名 / 参数。",
    ErrorCode.PROVIDER_UPSTREAM: "上游服务异常，请稍候再试。",
    ErrorCode.PROVIDER_EMPTY_RESPONSE: "模型返回为空，请重试。",
    ErrorCode.PROVIDER_SCHEMA_ERROR: "模型输出无法解析，请重试或换更强的模型。",
    ErrorCode.INTERNAL_ERROR: "请稍后重试或联系开发者（检查 backend 日志）。",
}

RETRYABLE: Dict[ErrorCode, bool] = {
    ErrorCode.PROVIDER_TIMEOUT: True,
    ErrorCode.PROVIDER_RATE_LIMITED: True,
    ErrorCode.PROVIDER_UPSTREAM: True,
    ErrorCode.PROVIDER_EMPTY_RESPONSE: True,
    ErrorCode.PROVIDER_SCHEMA_ERROR: True,
}


def build_error(
    code: ErrorCode,
    *,
    message: Optional[str] = None,
    detail: Optional[Any] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    msg = message or code.name.replace("_", " ").title()
    return {
        "error": {
            "code": code.value,
            "message": msg,
            "hint": HINTS.get(code, ""),
            "retryable": RETRYABLE.get(code, False),
            "context": context or {},
            "detail": detail,
        }
    }


# ---------------------------------------------------------------------------
# Custom exception so we don't get wrapped in FastAPI's "detail" envelope
# ---------------------------------------------------------------------------

class ApiError(Exception):
    """Raise inside a route. Body is the canonical envelope, no FastAPI wrapper."""

    def __init__(self, code: ErrorCode, *, message=None, detail=None, context=None):
        self.code = code
        self.body = build_error(code, message=message, detail=detail, context=context)
        self.status_code = code.default_http
        super().__init__(self.body["error"]["message"])


def raise_api_error(
    code: ErrorCode,
    *,
    message: Optional[str] = None,
    detail: Optional[Any] = None,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    raise ApiError(code, message=message, detail=detail, context=context)


def register_exception_handler(app) -> None:
    """Mount the ApiError handler so error envelope sits at body top-level.

    Usage in app.main:
        from app.services.errors import register_exception_handler
        register_exception_handler(app)
    """
    from fastapi.responses import JSONResponse

    @app.exception_handler(ApiError)
    async def _api_error_handler(request, exc: ApiError):
        return JSONResponse(status_code=exc.status_code, content=exc.body)


# ---------------------------------------------------------------------------
# Provider error classifier
# ---------------------------------------------------------------------------

def classify_provider_error(exc: Exception, provider_name: str, model: str) -> ErrorCode:
    msg = (str(exc) or "").lower()
    type_name = type(exc).__name__.lower()

    if "empty" in msg and ("response" in msg or "content" in msg):
        return ErrorCode.PROVIDER_EMPTY_RESPONSE
    if "json" in msg or "schema" in msg or "parse" in msg:
        return ErrorCode.PROVIDER_SCHEMA_ERROR
    if "401" in msg or "403" in msg or "auth" in msg or "permission" in msg or "无权" in msg:
        return ErrorCode.PROVIDER_AUTH
    if "429" in msg or "rate" in msg or "too many" in msg or "限流" in msg:
        return ErrorCode.PROVIDER_RATE_LIMITED
    if "timeout" in msg or "timed out" in msg or type_name == "timeouterror":
        return ErrorCode.PROVIDER_TIMEOUT
    if (
        "connection" in msg or "refused" in msg or "unreachable" in msg
        or "dns" in msg or "resolve" in msg
        or "errno 111" in msg or "errno 110" in msg
        or "host.docker.internal" in msg or "127.0.0.1" in msg
    ):
        return ErrorCode.PROVIDER_UNAVAILABLE
    if "400" in msg or "bad request" in msg or "invalid" in msg:
        return ErrorCode.PROVIDER_BAD_REQUEST
    if "500" in msg or "502" in msg or "503" in msg or "504" in msg or "upstream" in msg:
        return ErrorCode.PROVIDER_UPSTREAM
    if type_name == "runtimeerror" and ("not set" in msg or "missing" in msg):
        return ErrorCode.PROVIDER_UNAVAILABLE
    return ErrorCode.INTERNAL_ERROR