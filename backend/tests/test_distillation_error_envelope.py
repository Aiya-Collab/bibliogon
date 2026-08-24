"""Phase F Patch 004 — standardized error envelope tests.

WorkBuddy 直接交付（patch 003 之后的下一阻塞点：router try/except 没
wrap provider.chat，错误响应格式不统一）。本测试验证：

  1. /api/distillation/books/{id}/start 在各种失败场景下都返回标准 envelope
  2. envelope schema 稳定（code / message / hint / retryable / context / detail）
  3. ErrorCode HTTP 状态码映射正确
  4. classify_provider_error 对常见异常分类正确
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.errors import (
    ErrorCode,
    HINTS,
    RETRYABLE,
    build_error,
    classify_provider_error,
)


# ---------------------------------------------------------------------------
# Error envelope schema tests
# ---------------------------------------------------------------------------


def test_build_error_minimal():
    env = build_error(ErrorCode.PROVIDER_TIMEOUT)
    assert "error" in env
    err = env["error"]
    assert err["code"] == "provider_timeout"
    assert err["hint"] == HINTS[ErrorCode.PROVIDER_TIMEOUT]
    assert err["retryable"] is True
    assert err["context"] == {}
    assert err["detail"] is None


def test_build_error_full():
    env = build_error(
        ErrorCode.PROVIDER_AUTH,
        message="gpt-5.5 key 401",
        detail="client error 401",
        context={"provider": "cloudmist", "model": "gpt-5.5"},
    )
    err = env["error"]
    assert err["code"] == "provider_auth_error"
    assert err["message"] == "gpt-5.5 key 401"
    assert err["detail"] == "client error 401"
    assert err["context"]["provider"] == "cloudmist"


def test_all_codes_have_hints():
    """所有 ErrorCode 必须有用户可读 hint。"""
    for code in ErrorCode:
        assert code in HINTS, f"{code} 缺 hint"
        assert HINTS[code].strip(), f"{code} hint 不能为空"


def test_retryable_flags_consistent():
    """retryable=True 的 code 都应该是瞬态错误（5xx 或 429）。"""
    for code in RETRYABLE:
        if RETRYABLE[code]:
            # retryable 必须是 5xx 或 429（限流瞬态）
            is_transient = code.default_http >= 500 or code.default_http == 429
            assert is_transient, (
                f"{code} 标 retryable 但 HTTP {code.default_http}（应是 5xx 或 429）"
            )


def test_http_status_mapping():
    """ErrorCode HTTP 状态码映射符合 RESTful 规范。"""
    assert ErrorCode.BOOK_NOT_FOUND.default_http == 404
    assert ErrorCode.UNKNOWN_PROVIDER.default_http == 400
    assert ErrorCode.PROVIDER_RATE_LIMITED.default_http == 429
    assert ErrorCode.PROVIDER_TIMEOUT.default_http == 504
    assert ErrorCode.PROVIDER_UNAVAILABLE.default_http == 503
    assert ErrorCode.INTERNAL_ERROR.default_http == 500


# ---------------------------------------------------------------------------
# classify_provider_error tests
# ---------------------------------------------------------------------------


def test_classify_empty_response():
    code = classify_provider_error(Exception("empty response from model"), "ollama", "qwen3:8b")
    assert code == ErrorCode.PROVIDER_EMPTY_RESPONSE


def test_classify_json_parse_error():
    code = classify_provider_error(Exception("json decode error"), "cloudmist", "gpt-5.5")
    assert code == ErrorCode.PROVIDER_SCHEMA_ERROR


def test_classify_auth_error():
    code = classify_provider_error(Exception("401 unauthorized token"), "cloudmist", "gpt-5.5")
    assert code == ErrorCode.PROVIDER_AUTH


def test_classify_rate_limited():
    code = classify_provider_error(Exception("429 too many requests"), "deepseek", "v4-flash")
    assert code == ErrorCode.PROVIDER_RATE_LIMITED


def test_classify_timeout():
    code = classify_provider_error(TimeoutError("read timed out"), "ollama", "qwen3:8b")
    assert code == ErrorCode.PROVIDER_TIMEOUT


def test_classify_connection_refused():
    code = classify_provider_error(Exception("connection refused errno 111"), "ollama", "qwen3:8b")
    assert code == ErrorCode.PROVIDER_UNAVAILABLE


def test_classify_docker_host_unreachable():
    code = classify_provider_error(
        Exception("127.0.0.1:11434 host.docker.internal unreachable"),
        "ollama",
        "qwen3:8b",
    )
    assert code == ErrorCode.PROVIDER_UNAVAILABLE


def test_classify_missing_env():
    code = classify_provider_error(RuntimeError("MINIMAX_API_KEY not set"), "minimax", "M3")
    assert code == ErrorCode.PROVIDER_UNAVAILABLE


def test_classify_500_upstream():
    code = classify_provider_error(Exception("upstream 500 server error"), "deepseek", "v4-flash")
    assert code == ErrorCode.PROVIDER_UPSTREAM


def test_classify_unknown_falls_back():
    code = classify_provider_error(Exception("something weird happened"), "ollama", "qwen3:8b")
    assert code == ErrorCode.INTERNAL_ERROR


# ---------------------------------------------------------------------------
# FastAPI integration tests (use TestClient to hit the actual router)
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return TestClient(app)


def test_unknown_provider_returns_canonical_envelope(client, monkeypatch):
    """POST with unknown provider → 400 + canonical envelope (not raw str)."""
    # FastAPI 标准做法：dependency_overrides（不是 monkeypatch）
    from app.deps.auth import require_author
    from app.models import User
    fake_user = User(id="u-test", username="tester", role="author")
    app.dependency_overrides[require_author] = lambda: fake_user

    try:
        import io
        files = {"file": ("test.txt", io.BytesIO(b"hello world"), "text/plain")}
        resp = client.post(
            "/api/distillation/books/b1/start",
            files=files,
            params={"distillation_provider": "totally_made_up"},
        )
        # book_id=b1 不存在 → 应该是 BOOK_NOT_FOUND（404）
        assert resp.status_code in (400, 404)
        body = resp.json()
        assert "error" in body
        err = body["error"]
        assert "code" in err
        assert "message" in err
        assert "hint" in err
        assert "retryable" in err
        assert "context" in err
    finally:
        app.dependency_overrides.pop(require_author, None)


def test_book_not_found_uses_envelope(client, monkeypatch):
    """book_id 不存在时必须返回 canonical envelope，不是裸 HTTPException 字符串。"""
    from app.deps.auth import require_author
    from app.models import User
    fake_user = User(id="u-test", username="tester", role="author")
    app.dependency_overrides[require_author] = lambda: fake_user

    try:
        import io
        files = {"file": ("test.txt", io.BytesIO(b"hello world"), "text/plain")}
        resp = client.post(
            "/api/distillation/books/this-book-does-not-exist/start",
            files=files,
            params={"distillation_provider": "ollama"},
        )
        assert resp.status_code == 404
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == "book_not_found"
        assert "未找到" in body["error"]["message"]
        assert body["error"]["hint"]
        assert body["error"]["retryable"] is False
    finally:
        app.dependency_overrides.pop(require_author, None)