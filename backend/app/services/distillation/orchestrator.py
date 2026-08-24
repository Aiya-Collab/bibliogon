from app.config.ai_settings import AISettings
from app.services.llm.ollama import OllamaProvider


async def choose_provider(settings: AISettings):
    if settings.distillation_provider == "ollama":
        provider = OllamaProvider(settings.ollama_base_url, settings.ollama_model, settings.ollama_timeout_s, settings.ollama_max_retries)
        if not await provider.is_available(): raise RuntimeError("ollama_unavailable")
        return provider
    if settings.distillation_provider == "cloudmist":
        from app.services.llm.provider_factory import get_llm_provider
        return get_llm_provider()
    local = OllamaProvider(settings.ollama_base_url, settings.ollama_model, settings.ollama_timeout_s, settings.ollama_max_retries)
    if await local.is_available(): return local
    from app.services.llm.provider_factory import get_llm_provider
    return get_llm_provider()


def distillation_context_metadata(settings: AISettings) -> dict[str, int]:
    return {"num_ctx_used": settings.distillation_chunk_chars}
