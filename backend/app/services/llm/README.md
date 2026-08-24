# AI providers

The backend supports independent environment-variable credentials for CloudMist GPT/Claude/Qwen, MiniMax, DeepSeek and Alibaba DashScope. DashScope exposes only the four configured Qwen aliases (`qwen3.8-max`, `qwen3.7-max`, `qwen3.7-plus`, `qwen3.7-flash`); `qwen3.8-max` is capped at 1500 output tokens because of its reasoning budget.

Scene routing and the fallback chain are defined in `provider_factory.py`. Doubao remains as an isolated compatibility provider but is intentionally absent from the effective v4 route table. Credentials are never included in source, tests or reports.
