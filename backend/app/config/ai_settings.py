import os
from dataclasses import dataclass, field


AGENT_ROLES = frozenset({"drafting", "reviewer", "scribe", "foreshadow", "worldbuilder", "outliner", "context"})


@dataclass(frozen=True)
class AISettings:
    auto_publish: bool = False
    auto_adopt_canondelta: bool = False
    ai_generation_enabled: bool = field(default_factory=lambda: os.getenv("AI_GENERATION_ENABLED", "false").lower() == "true")
    enabled_agents: frozenset[str] = field(default_factory=lambda: frozenset(a.strip() for a in os.getenv("ENABLED_AGENTS", "").split(",") if a.strip()))
    distillation_provider: str = field(default_factory=lambda: os.getenv("DISTILLATION_PROVIDER", "auto").lower())
    ollama_base_url: str = field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "qwen3:8b"))
    ollama_timeout_s: int = 600
    ollama_max_retries: int = 2
    # Keep prompts within the default qwen3:8b 8K context window.
    distillation_chunk_chars: int = 2000
    distillation_overlap_chars: int = 200
    distillation_max_blocks: int = 24
    auto_adopt_distillation: bool = False


def get_ai_settings() -> AISettings:
    return AISettings()
