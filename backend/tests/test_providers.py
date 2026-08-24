import os
from unittest.mock import patch

from app.services.llm.provider_factory import get_provider


def test_all_v4_provider_constructors_use_independent_keys():
    env = {"CLOUDMIST_GPT_KEY":"x", "CLOUDMIST_CLAUDE_KEY":"x", "CLOUDMIST_QWEN_KEY":"x",
           "MINIMAX_API_KEY":"x", "DEEPSEEK_API_KEY":"x", "DASHSCOPE_API_KEY":"x"}
    with patch.dict(os.environ, env, clear=True):
        assert get_provider("claude").get_model_name() == "claude-sonnet-4-6"
        assert get_provider("qwen").get_model_name() == "qwen3-max"
        assert get_provider("minimax").get_model_name() == "MiniMax-M3"
        assert get_provider("deepseek").get_model_name() == "deepseek-v4-flash"
        assert get_provider("dashscope", "qwen3.8-max").get_model_name() == "qwen3.8-max"


def test_provider_missing_key_is_explicit():
    with patch.dict(os.environ, {}, clear=True):
        try:
            get_provider("dashscope")
        except RuntimeError as exc:
            assert "DASHSCOPE_API_KEY" in str(exc)
        else:
            raise AssertionError("missing key accepted")
