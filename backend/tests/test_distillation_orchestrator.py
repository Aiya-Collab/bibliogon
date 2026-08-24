from app.config.ai_settings import AISettings
from app.services.distillation.orchestrator import distillation_context_metadata


def test_default_chunk_chars_is_qwen_context_safe():
    assert AISettings().distillation_chunk_chars == 2000


def test_context_metadata_records_num_ctx():
    assert distillation_context_metadata(AISettings()) == {"num_ctx_used": 2000}


def test_context_metadata_tracks_override():
    settings = AISettings(distillation_chunk_chars=1500)
    assert distillation_context_metadata(settings)["num_ctx_used"] == 1500


def test_chunk_is_positive():
    assert AISettings().distillation_chunk_chars > 0


def test_overlap_remains_bounded():
    settings = AISettings()
    assert settings.distillation_overlap_chars < settings.distillation_chunk_chars
