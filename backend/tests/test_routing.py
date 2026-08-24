import os
from unittest.mock import patch

from app.services.llm.provider_factory import SCENE_ROUTES, get_provider_for_scene


def test_v4_scene_routes():
    env = {"CLOUDMIST_CLAUDE_KEY":"x", "CLOUDMIST_QWEN_KEY":"x", "CLOUDMIST_GPT_KEY":"x",
           "MINIMAX_API_KEY":"x", "DEEPSEEK_API_KEY":"x", "DASHSCOPE_API_KEY":"x"}
    with patch.dict(os.environ, env, clear=True):
        for scene, (_, model) in SCENE_ROUTES.items():
            assert get_provider_for_scene(scene).get_model_name() == model
