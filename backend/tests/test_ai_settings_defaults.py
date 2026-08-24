import os
from unittest import mock

from app.config.ai_settings import get_ai_settings
from app.services.llm.cloudmist import CloudMistProvider
from app.services.llm.provider_factory import get_llm_provider


def test_default_ai_settings_have_auto_publish_and_auto_adopt_disabled():
    settings = get_ai_settings()
    assert settings.auto_publish is False
    assert settings.auto_adopt_canondelta is False


def test_auto_publish_setting_cannot_be_enabled_without_explicit_opt_in():
    with mock.patch.dict(os.environ, {"AI_AUTOPUBLISH": "true"}):
        settings = get_ai_settings()
        assert settings.auto_publish is False


def test_provider_requires_environment_key_and_never_reads_app_yaml_key():
    with mock.patch.dict(os.environ, {}, clear=True):
        try:
            get_llm_provider()
            assert False, "provider started without CLOUDMIST_API_KEY"
        except RuntimeError as exc:
            assert "CLOUDMIST_API_KEY" in str(exc)


def test_provider_factory_uses_cloudmist_defaults():
    with mock.patch.dict(os.environ, {"CLOUDMIST_API_KEY": "test-secret"}, clear=True):
        provider = get_llm_provider()
        assert isinstance(provider, CloudMistProvider)
        assert provider.get_provider_name() == "cloudmist"
        assert provider.get_model_name() == "deepseek-v4-flash-0731"
