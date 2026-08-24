import os
from unittest.mock import patch

import pytest

from app.services.llm.cloudmist import CloudMistProvider
from app.services.llm.deepseek import DeepSeekProvider
from app.services.llm.doubao import DoubaoProvider
from app.services.llm.minimax import MiniMaxProvider
from app.services.llm.ollama import OllamaProvider
from app.services.llm.qwen_dashscope import DashScopeProvider
from app.services.llm.provider_factory import get_distillation_provider, get_distillation_provider_by_name


def settings(provider="cloudmist"):
    return type("S", (), {"distillation_provider": provider, "ollama_base_url": "http://localhost:11434", "ollama_model": "qwen3:8b", "ollama_timeout_s": 60, "ollama_max_retries": 2, "llm_model": "gpt-5.5"})()


def test_all_named_routes(monkeypatch):
    env = {"CLOUDMIST_GPT_KEY":"x", "CLOUDMIST_DOUBAO_KEY":"x", "MINIMAX_API_KEY":"x", "DEEPSEEK_API_KEY":"x", "DASHSCOPE_API_KEY":"x"}
    with patch.dict(os.environ, env, clear=True):
        assert isinstance(get_distillation_provider_by_name("cloudmist", settings()), CloudMistProvider)
        assert isinstance(get_distillation_provider_by_name("ollama", settings()), OllamaProvider)
        assert isinstance(get_distillation_provider_by_name("minimax", settings()), MiniMaxProvider)
        assert isinstance(get_distillation_provider_by_name("deepseek", settings()), DeepSeekProvider)
        assert isinstance(get_distillation_provider_by_name("doubao", settings()), DoubaoProvider)
        assert isinstance(get_distillation_provider_by_name("dashscope", settings()), DashScopeProvider)


def test_unknown_returns_none():
    assert get_distillation_provider_by_name("nonexistent", settings()) is None


def test_case_insensitive(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "x")
    assert isinstance(get_distillation_provider_by_name("MiNiMaX", settings()), MiniMaxProvider)


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MINIMAX_API_KEY"):
        get_distillation_provider_by_name("minimax", settings())


def test_legacy_selector_still_works(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "x")
    assert isinstance(get_distillation_provider(settings("minimax")), MiniMaxProvider)
