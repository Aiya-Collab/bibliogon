# Phase G Patch 008 蒸馏 UI Smoke

前置：`docker compose up -d` 后 backend/frontend/nginx 均为 Up；宿主 Ollama 已按 README 常驻；浏览器打开 `http://localhost:7880` 并登录。

- [ ] 访问 `http://localhost:7880/books/<book_id>`，替换为已有书籍 ID。
- [ ] 工具栏显示 `DistillButton`，点击“蒸馏拆书”。
- [ ] 确认 1 秒内出现 loading/处理中状态。
- [ ] 等待最多 90 秒，列表显示至少 5 条 outline（目标素材可验证 73 条）。
- [ ] 点击“采纳”后确认进入正史；采纳必须是作者手动操作。

失败时记录浏览器网络响应、run_id 和 backend 日志，交由 WorkBuddy 继续诊断。
