import pytest
from app.services.llm import Message
from app.services.llm import provider_factory


@pytest.mark.asyncio
async def test_fallback_moves_to_next_provider(monkeypatch):
    calls = []
    class Fake:
        def __init__(self, name): self.name = name
        async def chat(self, messages, **kwargs):
            calls.append(self.name)
            if len(calls) < 3: raise RuntimeError("provider down")
            return type("R", (), {"content":"ok"})()
    monkeypatch.setattr(provider_factory, "get_provider", lambda name, model=None: Fake(name))
    result = await provider_factory.call_with_fallback("draft_chapter_main", [Message("user", "hi")])
    assert result.content == "ok"
    assert calls[:3] == ["claude", "dashscope_max", "minimax"]
