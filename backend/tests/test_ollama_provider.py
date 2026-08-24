import pytest
from app.services.llm.ollama import OllamaProvider

@pytest.mark.asyncio
async def test_ollama_unavailable_without_daemon_or_model():
    provider = OllamaProvider(base_url="http://127.0.0.1:1")
    assert await provider.is_available() is False
