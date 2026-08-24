"""Provider construction, scene routing and failure fallback."""
import hashlib, json, os
from .cloudmist import CloudMistProvider
from .deepseek import DeepSeekProvider
from .doubao import DoubaoProvider
from .minimax import MiniMaxProvider
from .ollama import OllamaProvider
from .qwen_dashscope import DASHSCOPE_BASE_URL, DashScopeProvider

DEFAULT_BASE_URL = "https://api.cloudmist.cloud/v1"
DEFAULT_MODEL = "deepseek-v4-flash-0731"
SCENE_ROUTES = {
 "draft_chapter_main": ("claude", "claude-sonnet-4-6"), "draft_chapter_quality": ("dashscope", "qwen3.7-max"),
 "draft_chapter_quick": ("dashscope", "qwen3.7-flash"), "draft_chapter_fallback": ("minimax", "MiniMax-M3"),
 "dialogue_polish": ("minimax", "MiniMax-M3"), "dialogue_polish_fallback": ("dashscope", "qwen3.7-plus"),
 "audit_style": ("qwen", "qwen3-max"), "audit_logic": ("claude", "claude-sonnet-4-6"),
 "distill_json": ("deepseek", "deepseek-v4-flash"), "distill_json_fallback": ("dashscope", "qwen3.7-plus"),
 "distill_summary": ("dashscope", "qwen3.7-plus"), "distill_summary_fallback": ("claude", "claude-sonnet-4-6"),
 "long_context": ("dashscope", "qwen3.7-max"), "stable_minimum": ("gpt", "gpt-5.5"),
 "quick_draft": ("dashscope", "qwen3.7-flash"), "quick_draft_fallback": ("deepseek", "deepseek-v4-flash"),
 "gold_quote": ("dashscope", "qwen3.8-max")}
FALLBACK_CHAIN = ("claude", "dashscope_max", "minimax", "deepseek", "dashscope_plus", "dashscope_flash", "qwen", "gpt")

def _required(name):
    value = os.environ.get(name)
    if not value: raise RuntimeError(f"{name} not set, refusing to start")
    return value
def _cloud(key, model): return CloudMistProvider(os.getenv("CLOUDMIST_BASE_URL", DEFAULT_BASE_URL), _required(key), model)
def _dash(model): return DashScopeProvider(os.getenv("DASHSCOPE_BASE_URL", DASHSCOPE_BASE_URL), _required("DASHSCOPE_API_KEY"), model)

def get_provider(provider, model=None):
    p = provider.lower()
    if p in {"cloudmist", "gpt"}:
        if not os.getenv("CLOUDMIST_API_KEY") and not os.getenv("CLOUDMIST_GPT_KEY"):
            raise RuntimeError("CLOUDMIST_API_KEY or CLOUDMIST_GPT_KEY not set, refusing to start")
        return _cloud("CLOUDMIST_API_KEY" if os.getenv("CLOUDMIST_API_KEY") else "CLOUDMIST_GPT_KEY", model or DEFAULT_MODEL)
    if p == "claude": return _cloud("CLOUDMIST_CLAUDE_KEY", model or "claude-sonnet-4-6")
    if p == "qwen": return _cloud("CLOUDMIST_QWEN_KEY", model or "qwen3-max")
    if p == "minimax": return MiniMaxProvider(os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1"), _required("MINIMAX_API_KEY"), model or "MiniMax-M3")
    if p == "deepseek": return DeepSeekProvider(os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"), _required("DEEPSEEK_API_KEY"), model or "deepseek-v4-flash")
    if p == "dashscope" or p.startswith("dashscope_"):
        return _dash(model or {"dashscope_max":"qwen3.7-max", "dashscope_plus":"qwen3.7-plus", "dashscope_flash":"qwen3.7-flash"}.get(p, "qwen3.7-max"))
    if p == "doubao": return DoubaoProvider(os.getenv("CLOUDMIST_BASE_URL", DEFAULT_BASE_URL), _required("CLOUDMIST_DOUBAO_KEY"), model or "doubao-seed-2-0-mini-260428")
    raise ValueError(f"unknown provider: {provider}")
def get_llm_provider(): return get_provider(os.getenv("LLM_PROVIDER", "cloudmist"), os.getenv("LLM_MODEL", DEFAULT_MODEL))
def get_provider_for_scene(scene):
    if scene not in SCENE_ROUTES: raise ValueError(f"unknown scene: {scene}")
    p, m = SCENE_ROUTES[scene]; return get_provider(p, m)
def __getattr__(name):
    if name.startswith("get_") and name.endswith("_provider") and name[4:-9] in SCENE_ROUTES:
        return lambda: get_provider_for_scene(name[4:-9])
    raise AttributeError(name)
async def call_with_fallback(scene, messages, **kwargs):
    last = None
    sequence = (SCENE_ROUTES[scene][0],) + tuple(x for x in FALLBACK_CHAIN if x != SCENE_ROUTES[scene][0])
    for p in sequence:
        try: return await get_provider(p, SCENE_ROUTES[scene][1] if p == SCENE_ROUTES[scene][0] else None).chat(messages, **kwargs)
        except Exception as exc: last = exc
    raise RuntimeError(f"all providers failed for {scene}") from last
def get_distillation_provider(settings):
    if settings.distillation_provider == "ollama": return OllamaProvider(settings.ollama_base_url, settings.ollama_model, settings.ollama_timeout_s, settings.ollama_max_retries)
    if settings.distillation_provider in {"cloudmist", "minimax", "deepseek", "doubao"}: return get_provider(settings.distillation_provider)
    return None

def get_distillation_provider_by_name(provider_name: str, settings):
    """Resolve a distillation provider from the request override.

    Unknown names return ``None`` so the HTTP layer can report a deterministic 400.
    This intentionally coexists with the legacy settings-based selector.
    """
    name = (provider_name or "").lower()
    if name == "auto":
        name = "ollama"
    if name == "ollama":
        return OllamaProvider(settings.ollama_base_url, settings.ollama_model,
                              settings.ollama_timeout_s, settings.ollama_max_retries)
    if name == "cloudmist":
        model = getattr(settings, "llm_model", None) or os.getenv("LLM_MODEL", "gpt-5.5")
        key = next((os.environ.get(k) for k in ("CLOUDMIST_GPT_KEY", "CLOUDMIST_CLAUDE_KEY", "CLOUDMIST_QWEN_KEY", "CLOUDMIST_DOUBAO_KEY", "CLOUDMIST_API_KEY") if os.environ.get(k)), None)
        if not key:
            raise RuntimeError("no CloudMist key configured")
        return CloudMistProvider(os.getenv("CLOUDMIST_BASE_URL", DEFAULT_BASE_URL), key, model)
    if name == "minimax": return get_provider("minimax")
    if name == "deepseek": return get_provider("deepseek")
    if name == "doubao":
        key = os.environ.get("CLOUDMIST_DOUBAO_KEY") or os.environ.get("CLOUDMIST_API_KEY")
        if not key: raise RuntimeError("CLOUDMIST_DOUBAO_KEY not set")
        return DoubaoProvider(os.getenv("CLOUDMIST_BASE_URL", DEFAULT_BASE_URL), key, os.getenv("DOUBAO_MODEL", "doubao-seed-2-0-mini-260428"))
    if name == "dashscope": return get_provider("dashscope", os.getenv("DASHSCOPE_MODEL", "qwen3.7-plus"))
    return None
def provider_config_hash(provider):
    payload = {"provider": provider.get_provider_name(), "model": provider.get_model_name(), "base_url": provider.base_url}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
