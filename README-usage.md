# 长篇小说创作工作台 — 使用说明

> 本文档面向项目**使用者**（不是开发者），讲清楚项目是什么、怎么拼出来的、怎么跑起来、怎么最快跑通一次业务流程，并标出已知风险与限制。
>
> 前置阅读：`governance/phase-task-cards.md`（六阶段治理任务卡 A→F 全部通过，可作为项目进度的"宪法"），`docs/MODULE-ARCHITECTURE.md`（应用内层架构参考），`docs/API.md`（API 概览）。
>
> 适用版本：v0.59.0（六阶段治理后版本）。原项目上游版本同号。

---

## 一、目录

1. [项目是什么](#一项目是什么)
2. [它由哪些东西缝合而来](#二它由哪些东西缝合而来)
3. [整体架构](#三整体架构)
4. [目录结构拆解](#四目录结构拆解)
5. [数据流与执行流程](#五数据流与执行流程)
6. [环境依赖与前置条件](#六环境依赖与前置条件)
7. [启动 / 停止完整步骤](#七启动--停止完整步骤)
8. [入口地址、账号、第一次测试](#八入口地址账号第一次测试)
9. [关键配置说明](#九关键配置说明)
10. [故障排查](#十故障排查)
11. [快速上手示例](#十一快速上手示例)
12. [技术风险 / 已知限制](#十二技术风险--已知限制)
13. [附录 A：六阶段治理 A→F 叠加状态](#附录-a六阶段治理-af-叠加状态)
14. [附录 B：相关文档索引](#附录-b相关文档索引)

---

## 一、项目是什么

**一句话**：把"开源图书创作系统 [Bibliogon](https://github.com/astrapi69/bibliogon)"二次整合为**长篇小说专用工作台**，加上"作者把关草稿 → 录入正史"的治理管道，让 AI 能帮忙但不擅权。

**详细点说**：用户在浏览器里以四层结构（卷→部→章→场）创作长篇小说；AI 通过 7 个候选型智能体在 `candidate` 通道里生成草稿、提取事实、追踪伏笔、检查一致性，**任何 AI 输出都必须经作者过人工闸门后**才能进入正史（Canon）；每次采纳都写含证据哈希 + 唯一索引的回滚审计，方便作者"撤销回上一步"，并能马上问责是谁、在何时、基于什么证据采纳的。

**适合谁用**：单作者写连载长篇小说（30 + 章、约 50–200 万字），希望：① AI 帮忙写稿但严格可控；② 历史一致性可强制保证（人名、地名、伏笔不漂移）；③ 试错无成本（采纳错了能反悔）。

---

## 二、它由哪些东西缝合而来

| # | 来源组件 | 仓库 / 上游 | 在本项目里的职责 | 治理阶段 |
|---|---|---|---|---|
| 1 | **Bibliogon 主体** (v0.59.0) | https://github.com/astrapi69/bibliogon | FastAPI + SQLite 后端、React+TipTap 前端、nginx 反代、Docker 部署；完整保留所有图书/文章/绘本/漫画/TTS/导出/KDP 模块 | A（原样部署） |
| 2 | **Manuscripta** (^0.9.0) | https://github.com/astrapi69/manuscripta | 多引擎 TTS 音频书、Pandoc/Pandoc-based 导出、PDF/EPUB/DOCX/LaTeX 转换 | A（上游内置） |
| 3 | **Write-Book-Template** | https://github.com/astrapi69/write-book-template | 库导出目标目录结构 | A（上游内置） |
| 4 | **PluginForge** | https://github.com/astrapi69/pluginforge | 基于 pluggy 的插件框架，13 个 MIT 插件 | A（上游内置） |
| 5 | **Story-BBible 插件** | plugins/bibliogon-plugin-story-bible | 角色/场景/情节/物品/设定 五类实体数据库，@-mention 自动识别，Arc View 时间线，Continuity Checker 警告 | A（启用，但被治理为**只读分组**） |
| 6 | **Novel Project Tree** | 本项目自有 | 在 Bibliogon 之上叠加"卷/部/章/场"四级目录树 | C（添加） |
| 7 | **Revision 草稿 + 双门禁** | 本项目自有 | 候选草稿（candidate）/在用正文（active）/归档（archived），发布前必须经过"作者过人工"门禁 + 内容哈希门禁 | D（添加） |
| 8 | **CanonDelta + 回滚审计** | 本项目自有 | 正史修改走 proposed→accepted/rejected 状态机，每步写入 criteria_snapshot 与三段 affected IDs，含 60 秒并发保护 | E（添加） |
| 9 | **CloudMist Provider + AiRunLog** | 本项目自有 + https://api.cloudmist.cloud/v1 | AI 7 智能体的 Provider Client，唯一写库口是 drafting→candidate revision；密钥只从环境变量读，不入库 | F（添加） |

**代码所有权**：1–5 是开源上游（MIT 协议），6–9 是本项目自有。**绝对不修改上游 1–5 的源码**（治理红线 R6）；只在 `backend/app/` 下加新目录与新路由。

---

## 三、整体架构

### 3.1 一张图

```
┌──────────────────────────────────────────────────────────────────┐
│ 浏览器                                                          │
│   Dashboard → BookEditor → ProjectOutline → ExportPage          │
└──────────────┬───────────────────────────────────────────────────┘
               │ /api/* (HTTP/JSON)
               ▼
┌──────────────────────────────────────────────────────────────────┐
│ nginx:80 (frontend 反代)                                         │
│   ├─ /api/* → backend:8000                                       │
│   └─ /*     → /usr/share/nginx/html (Vite 打包)                  │
└──────────────┬───────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────┐
│ FastAPI :8000 (uvicorn, 2 worker)                                │
│   ┌─────────────────────────┐    ┌──────────────────────────┐  │
│   │  核心路由（router_    │    │  插件路由（PluginForge  │  │
│   │  registration.py）      │    │  lifespan 动态 mount）  │  │
│   │  books/chapters/        │    │  story-bible, export,   │  │
│   │  articles/audiobook/    │    │  audiobook, kdp, …      │  │
│   │  revisions/canon/        │    │                          │  │
│   │  project_tree/          │    │                          │  │
│   │  ai_agents/             │    │                          │  │
│   └─────┬───────────────────┘    └────────┬─────────────────┘  │
│         │ service → repository → model    │                    │
│         ▼                                 ▼                    │
│   ┌─────────────────────────┐    ┌──────────────────────────┐  │
│   │ SQLAlchemy ORM 模型     │    │ PluginForge HookSpecs     │  │
│   │ Book/Chapter/Revision/  │    │ + pluggy 钩子             │  │
│   │ Canon/CanonDelta/       │    │                          │  │
│   │ StoryEntity/StoryLink/  │    │                          │  │
│   │ AiRun/AiRunLog          │    │                          │  │
│   └────┬────────────────────┘    └─────────────┬────────────┘  │
└────────┼──────────────────────────────────────┼────────────────┘
         ▼                                      ▼
   bibliogon.db (SQLite, WAL 模式,            AiRunLog 只存哈希
   PRAGMA foreign_keys=ON)                    不存明文 + 密钥
         │
         ▼
   /app/data/bibliogon.db
   /app/data/uploads/

   CloudMistProvider ──HTTP──► api.cloudmist.cloud/v1
   (deepseek-v4-flash-0731 锁版本)         ▲
                                          环境变量
                                          CLOUDMIST_API_KEY
                                          (启动校验 缺失即失败)
```

### 3.2 数据流分三层

1. **持久层**（单一真相源）：
   - SQLite WAL（允许并发读、单写）
   - 60+ 表，含上游 Bibliogon 全部 + 卡 C/D/E/F 的 project_node / revision / canon / canon_delta / ai_run_log 等

2. **服务层**（业务逻辑）：
   - 上游 `backend/app/services/` 30+ 个（authorship/writing/recovery/...)
   - 本项目 `backend/app/services/llm/`：CloudMistProvider（HTTP 客户端，60s 超时，失败重试 0 次）
   - 本项目 `backend/app/services/project_references.py`：每日扫一次 L3 引用锚点，更新 valid/needs_relocate/broken

3. **接入层**（HTTP / WebSocket）：
   - 47 个核心 API（含 7 个治理 API）
   - 插件 API 动态挂载（启动时按 `plugins.enabled` 列表发现）
   - 一个 WebSocket：`/api/ws/...`（实时推送，如 TTS 进度）

---

## 四、目录结构拆解

### 4.1 仓库根（`D:/work工作/bibliogon/`）

| 文件 / 目录 | 责任 |
|---|---|
| `start.sh` / `stop.sh` | 启动/停止 Docker Compose 栈的封装（Linux/macOS） |
| `install.sh` / `install.ps1` / `install.cmd` / `install.command` | 一次性安装脚本（拉代码、build 镜像、写 .env） |
| `docker-compose.yml` | 开发模式（端口 8000+5173，前后端源码挂载） |
| `docker-compose.prod.yml` | 生产模式（端口 7880，nginx 反代，build 后的 dist） |
| `.env.example` | 环境变量模板 |
| `Dockerfile` (根) | 不存在；后端 Dockerfile 在 `backend/`，前端在 `frontend/` |
| `Makefile` | 130+ make 目标（dev/test/install/...） |
| `README.md` / `README-de.md` | 上游项目原文（含德语版） |
| `CLAUDE.md` | 上游开发者文档（56 KB） |
| `SECURITY.md` / `CONTRIBUTING.md` / `CODE_OF_CONDUCT.md` | 上游合规文档 |
| `LICENSE` | MIT |
| `mkdocs.yml` | 文档站点配置（https://astrapi69.github.io/bibliogondocs） |
| `docs/` | 设计/架构/决策记录（30+ md，上游密集） |
| `docs/API.md` | API 总览（路由表 + 文档指针） |
| `docs/MODULE-ARCHITECTURE.md` | 层架构与可重用规则 |
| `docs/configuration.md` | 四层配置链解释（项目 yaml < user overlay < user secrets < env） |
| `docs/VIBE-CODING-POLICY.md` | AI 助手开发规约 |
| `changelog/releases/` | 上游全部版本日志（v0.13.0 → v0.59.0） |
| `governance/` | **本项目自有**：六阶段治理交付物（不含上游） |
| `backend/` | FastAPI 后端（含六个新组件） |
| `frontend/` | React + Vite 前端（含两个新组件） |
| `plugins/` | 13 个 MIT 上游插件 |
| `e2e/` | Playwright 端到端测试（卡 C 新增 1 个用例） |
| `launcher/` | 桌面启动器元数据（linux/macos/windows 三端） |
| `scripts/` | 上游自检脚本（文件大小/复杂度等） |
| `tmp/` | 临时目录（不提交） |

### 4.2 后端（`backend/app/`）

| 子目录 | 责任 |
|---|---|
| `routers/` | **所有 HTTP 端点**，47 个文件。前端只通过这里读写数据库 |
| `services/` | 业务逻辑层，30+ 文件。下层调 repositories，上层被 routers 调 |
| `repositories/` | 数据库访问抽象层（SqlAlchemy 实现）+ 接口 |
| `models/` | SQLAlchemy ORM 类（一张表一个类）。**注意**：单文件 `__init__.py` 内放所有模型（不是每个表一个文件） |
| `schemas/` | Pydantic v2 请求/响应契约 |
| `deps/` | **本项目卡 D/E/F 新增**：FastAPI Depends 鉴权层（`auth.py`） |
| `config/` | **本项目卡 F 新增**：`ai_settings.py`（auto_publish/auto_adopt 开关）+ 空 `__init__.py` |
| `services/llm/` | **本项目卡 F 新增**：Provider Client 抽象 (`base.py`) + CloudMist 实现 + Factory |
| `services/project_references.py` | **本项目卡 C 新增**：L3 引用锚点扫描器 |
| `services/project_reference_worker.py` | **本项目卡 C 新增**：24h cron worker（lifespan 启动） |
| `ai/` | 上游 AI 路由 + 模板 prompt 库 |
| `import_plugins/` | 导入处理器注册表 |
| `data/` | 内置模板 / 内置章节模板（启动时 seed 一次） |
| `middleware/` | 上游 BodySize 限制中间件 |
| `main.py` | **启动入口**：lifespan + 异常处理 + CORS + 路由挂载 + 启动校验缺 `CLOUDMIST_API_KEY` |
| `router_registration.py` | 47 个核心路由挂载点；插件路由由 `PluginManager.mount_routes()` 动态挂 |
| `config_loader.py` / `config_overlay.py` | 上游四层配置合并实现 |
| `data_dir_migration.py` | v0.25 及更早的数据目录迁移到 XDG 路径 |

### 4.3 后端迁移文件（`backend/migrations/versions/`）

70+ 个 alembic 迁移文件。本项目新增的：

| 迁移文件 | 阶段 | 内容 |
|---|---|---|
| `a6b7c8d9e0f1_add_novel_project_tree.py` | C | 项目树 4 级 + 引用 + 实体绑定 |
| `b7c8d9e0f1a2_add_revision_gate.py` | D | Revision 表 + partial unique index `WHERE status='active'` |
| `d0e1f2a3b4c5_add_canon_and_rollback.py` | E | Canon + CanonDelta + RollbackReceipt + RollbackRequest |
| `e1f2a3b4c5d6_add_ai_run_log.py` | F | AiRunLog（仅存哈希） |

⚠️ 警告：迁移历史**不能乱用 `-1`**——多次合并后可能走到错的父版本。**用显式目标**（如 `alembic downgrade d0e1f2a3b4c5`）才会稳。

### 4.4 前端（`frontend/src/`）

按"职责优先"组织（不是按 feature）：

| 目录 | 责任 |
|---|---|
| `pages/` | 20+ 路由级页面（Dashboard / BookEditor / ProjectOutline / ExportPage / Settings / Help / GitSyncPage...） |
| `components/` | 70+ 共享 UI 组件（TipTap 编辑器、章节侧栏、StoryBible 面板、AI 模板对话框、卡片、模态框...） |
| `api/` | 11 个模块化 API 客户端（**全应用唯一网络出口**：`BASE=/api` + `guardedFetch`） |
| `hooks/` | 30+ 可复用 stateful hooks（ViewMode/i18n/Selection/WritingGoal...） |
| `storage/` | `IStorageService` seam（在线时走 ApiStorage，离线/测试时走 DexieStorage） |
| `contexts/` / `themes/` / `styles/` | 跨页面的全局状态、主题、CSS 变量 |
| `features/` | 特性策略注册表（离线/桌面 gating） |
| `lib/` | 纯工具（不能 import app 任何东西） |
| `modules/` | 插件对应前端 barrel（不重写实现，仅 re-export） |
| `App.tsx` + `main.tsx` | 入口 + 路由配置 |
| `db/` | IndexedDB schema（dexie，离线 PWA 用） |

### 4.5 治理交付物（`governance/`）

本项目**独有**，记录六阶段治理全过程：

```
governance/
├── phase-task-cards.md        # 宪法：六张卡的裁决表 + 红线 R1-R8
├── phase-A-deploy-report.md   # 部署报告（卡 A 通过）
├── phase-A-unblock-instructions.md  # 卡 A 解阻时的 Docker 安装步骤
├── phase-B-handoff-to-codex.md      # B：交接令
├── phase-B-baseline-audit.md        # B：基线审计报告
├── phase-C-product-rules.md         # C：产品规则（C-0.1 至 C-0.4）
├── phase-C-delivery.md              # C：交付 + 验收 10/10
├── phase-C-npm-audit.json           # C：npm 漏洞扫描
├── phase-D-handoff-to-codex.md      # D：交接令
├── phase-D-delivery.md              # D：交付 + 验收 10/10
├── phase-E-handoff-to-codex.md      # E：交接令
├── phase-E-delivery.md              # E：交付 + 验收 8/8
├── phase-F-handoff-to-codex.md      # F：交接令（最后一张卡）
└── phase-F-delivery.md              # F：交付 + 验收 7/7
```

**任何修改现有功能前，先看 `phase-task-cards.md`**——里面记录的红线和上下文能省去 5 分钟解释。

---

## 五、数据流与执行流程

### 5.1 启动流程（按时间序）

```
       start.sh / docker compose up
                    │
   1. docker engine 检查 ──► 失败则报错退出
                    │
   2. .env 不存在则从 .env.example 复制
      且生成 BIBLIOGON_SECRET_KEY (32 字节 hex)
                    │
   3. docker compose -f docker-compose.prod.yml up --build -d
        ├─ build backend (multi-stage: poetry → slim + pandoc + git)
        └─ build frontend (node:24-slim → nginx:alpine)
                    │
   4. backend 容器启动 uvicorn app.main:app --workers 2
      ↓ lifespan startup:
      ├─ migrate_data_dir_if_needed()   # v0.25 老数据目录迁移
      ├─ mark_data_dir_as_production()  # 防测试误打到生产库
      ├─ init_db()                       # alembic upgrade head 或 stamp
      ├─ get_ai_settings() 与 get_llm_provider() 检查
      │   └─ CLOUDMIST_API_KEY 不在 → 启动失败，强失败
      ├─ cleanup_expired_trash()         # 过期回收
      ├─ sync_edge_tts_voices()          # 首次 seed TTS voice
      ├─ seed_builtin_templates()       # 章节模板 seed
      ├─ sync manager with overlay
      ├─ discover_plugins()              # 13 插件按 plugins.enabled 启
      ├─ mount_routes(app)               # 插件路由动态挂载
      ├─ _log_discovery_result()
      └─ reference_scan_task = run_daily_reference_scan()  # 卡 C 新增
                    │
   5. frontend 容器启动 nginx（端口 80→7880）
      wait backend healthy
                    │
   6. 浏览器打开 http://localhost:7880
```

### 5.2 写一章小说的完整流程（治理后）

```
① 作者在 BookEditor 页面写 chapter 内容（前端直接调 /api/books/{id}/chapters）
② 前端额外触发 project_tree 同步（卡 C）：新建 chapter 的同时建 L3 节点
③ 作者点"AI 辅助生成下一章" → 前端调 /api/ai/agents/drafting/generate
   ├─ ai_agents.py 校验 X-AI-Run-Id 头（require_ai_identity）
   ├─ validate_agent_role("drafting") → AGENT_ROLES 白名单
   ├─ check_agent_enabled("drafting") → enabled_agents 环境变量
   ├─ get_llm_provider() → CloudMistProvider
   ├─ 调 https://api.cloudmist.cloud/v1/chat/completions
   │   ├─ model: deepseek-v4-flash-0731（锁版本）
   │   ├─ 60s 超时
   │   └─ stream 不开
   ├─ 落 Revision(status='candidate', content_hash=sha256, ai_run_id=...)
   ├─ 落 AiRunLog（request_hash + response_hash + provider_config_hash）
   └─ 返回 {revision_id, content, content_hash, status: 'candidate'}
④ 作者在 editor 中 review → 调 /api/revisions/{rid}/publish
   ├─ revisions.py 校验 require_author_write（X-User-Id + role='author'）
   ├─ 校验 evidence.decision='approved' AND content_hash 一致（双门禁）
   ├─ 落 RevisionPublishLog（hash 化 diff，不可篡改）
   └─ 旧 active archived + 新 active（partial unique index 保证单 active）
⑤ 作者要记录一段情节到正史 → 调 /api/canon/deltas
   ├─ canon.py 校验 require_canon_author（AI 必拒：ai_role_cannot_modify_canon）
   ├─ 同时硬编码 proposed_by_role='author'（纵深防御）
   └─ 落 CanonDelta(status='proposed', criteria_snapshot=dict(delta.fact_payload))
⑥ 作者显式采纳 → 调 /api/canon/deltas/{id}/decide
   ├─ _decide() 事务化：校验 status='proposed' → 建 Receipt → 写 Canon
   │   → 旧 Canon 行标记 superseded → delta status='accepted' → commit
   └─ 落 AuditLog（防 criteria_snapshot 篡改）
⑦ 作者后悔 → 调 /api/canon/rollback
   ├─ 先建 RollbackRequest 行（60s 并发保护窗）
   ├─ 倒序撤销（先回 deltas → 再回 Canon 本身）
   ├─ 标记 Canon.rolled_back_at
   └─ 落 RollbackReceipt 三类 affected IDs（publish_log / canon / receipt）
```

**关键不变量**（治理红线 R1-R8 的具体落实）：

1. AI 物理上不能写正史（双层防御：依赖 + 字段硬编码）
2. 任何 active revision 永远只有一个（SQL partial unique index）
3. 任何采纳都写 criteria_snapshot 防字段回填篡改
4. 任何 publish 都双门禁（人工 + 内容哈希）
5. 任何 rollback 都生成 receipt（受影响的 publish_log / canon / receipt ID 全列出来），**不删审计**
6. AI 任何调用只记录哈希不记录明文，密钥配置哈希化

---

## 六、环境依赖与前置条件

### 6.1 硬件（建议）

| 维度 | 最低 | 推荐 |
|---|---|---|
| CPU | 2 核 | 4 核（含音频生成的话） |
| 内存 | 2 GB | 4 GB（启动 AI 调用会冲 500 MB 尖峰） |
| 磁盘 | 4 GB（含 Docker image / dist / data） | 10 GB（如果有音频书 + 备份） |
| 操作系统 | Windows 10 / macOS 11 / Ubuntu 20.04 | 任意能跑 Docker Desktop 的现代系统 |

### 6.2 软件（一键依赖）

| 依赖 | 用途 | 下载 |
|---|---|---|
| **Docker Desktop**（含 Compose v2） | 跑后端 + 前端 | https://docs.docker.com/get-docker/ |
| **Node.js 22+**（仅本地开发要） | `make dev` 起 Vite | https://nodejs.org/ |
| **Python 3.12+**（仅本地开发要） | poetry 或 pip 装后端依赖 | https://www.python.org/downloads/ |
| **Pandoc 3.x**（仅离线导出要） | 部分导出格式 | `apt install pandoc` / `brew install pandoc` |
| **Git**（可选） | git-sync 插件需要 | 系统自带 |

**额外可装可不装**：
- `make`（如果有 Makefile 才要）
- 一个好用的文本编辑器（VS Code 等）

### 6.3 端口

| 端口 | 用途 | 谁占用 |
|---|---|---|
| **7880** | **Web 访问入口**（生产模式） | nginx |
| 8000 | 后端 FastAPI（仅暴露在容器间） | uvicorn |
| 5173 | 前端 Vite 开发服务器（仅开发模式） | vite |
| 80 | nginx（容器内） | nginx |

> **如果 7880 被占**：编辑 `.env`，改 `BIBLIOGON_PORT=7881`。

### 6.4 环境变量

参见 `.env.example` 和 [九、关键配置说明](#九关键配置说明)。治理阶段引入的新增变量在卡 F 段；最关键是 `CLOUDMIST_API_KEY`（AI 接入密钥），**必填**。

---

## 七、启动 / 停止完整步骤

### 7.1 已部署环境（直接访问）

> 如果是已经在服务器上跑好的（即已经有人帮你执行过 7.2），你只需要：

**打开浏览器**：http://<服务器 IP>:7880

> ⚠️ **本项目当前默认端口 7880**（上游默认是 8080 已改）。如果是远程服务器，需要在防火墙/路由器开放 7880。

**停止 / 重启**：不归你管，找管理员。

### 7.2 本地从零启动（Docker Compose 生产模式）—— **最常用**

#### Windows：

```powershell
# 1. 克隆或解压到 D:\work工作\bibliogon（或者随便哪个目录）
# 2. 进入项目根（PowerShell 或 cmd 都行）
cd D:\work工作\bibliogon

# 3. 第一次：调 install.cmd（一键安装）
.\install.cmd

# 4. 后续启动
.\start.sh       # Linux/macOS; Windows 用 Git Bash 或：
                  # powershell> docker compose -f docker-compose.prod.yml up -d

# 5. 停止
.\stop.sh
```

#### Linux / macOS：

```bash
cd ~/bibliogon                # 或者你 clone 的目录
./install.sh                  # 一次性安装（生成 .env, build image, start）
# 或者分步：
curl -fsSL https://raw.githubusercontent.com/astrapi69/bibliogon/main/install.sh | bash
./start.sh                    # 启动
./stop.sh                     # 停止
```

#### 双击安装（零命令行）

| 平台 | 文件 | 说明 |
|---|---|---|
| macOS | `install.command` | Finder 直接双击 |
| Windows | `install.cmd` | 资源管理器直接双击 |
| Linux | 命令行 `bash install.sh` | 桌面环境无特殊 wrapper |

#### 装完的目录长这样：

```
%USERPROFILE%/bibliogon/        # Windows 默认位置
~/bibliogon/                    # Linux/macOS 默认位置
├── bibliogon/                  # 项目根（被 install 脚本 git clone 下来）
├── .env                        # 由 install 生成（含 64 字符随机 SECRET_KEY）
└── ...
```

### 7.3 本地开发模式（前后端热重载）

如果你是开发者，需要改代码立刻见效：

```bash
cd D:/work工作/bibliogon
# 一次性 install（如果用 Poetry）
make install

# 起后端（8000）+ 前端（5173）同时
make dev

# 打开浏览器
# 后端： http://localhost:8000/docs（Swagger API 调试）
# 前端： http://localhost:5173（Vite 热重载）
```

> 这个模式你直接编辑 `backend/app/*.py` 和 `frontend/src/*.tsx` 都能 hot reload。但**每次重启前要清缓存**：`.pytest_cache/` / `__pycache__/` / `node_modules/.vite/`。

### 7.4 验证启动成功

```bash
# 1. 看容器状态
docker compose -f docker-compose.prod.yml ps
# 应该看到 bibliogon-backend running，bibliogon-frontend running，端口映射 :7880->80

# 2. 看日志（重要，看启动报错）
docker compose -f docker-compose.prod.yml logs -f
# 应该看到 "Bibliography started on http://0.0.0.0:8000" 类似字样

# 3. 健康检查（关键）
curl http://localhost:7880/api/health
# {"status":"ok"} 或类似 ← 通了

# 4. 看插件加载
curl http://localhost:7880/api/plugins
# 应该返回 enabled 列表含 export / story-bible / kdp / ...

# 5. 看迁移版本
docker compose -f docker-compose.prod.yml exec backend alembic current
# 应该返回 head (= f7a8b9c0d1e2 即卡 F 迁移已应用)
```

### 7.5 干净停止

```bash
./stop.sh
# 或者
docker compose -f docker-compose.prod.yml down

# 完全删除（含数据卷）：
docker compose -f docker-compose.prod.yml down -v
# ⚠️ 这会把 /app/data 删掉，包括数据库、上传、备份！先备份：
docker compose -f docker-compose.prod.yml exec backend python -c "
from app.config_loader import _load_app_config
from pathlib import Path
import shutil
data = Path('/app/data')
if data.exists():
    shutil.make_archive('/tmp/bibliogon-backup', 'zip', '/app/data')
    print('backup at /tmp/bibliogon-backup.zip')
"
```

---

## 八、入口地址、账号、第一次测试

### 8.1 入口

| 入口 | URL | 用途 |
|---|---|---|
| **Web 工作台** | http://localhost:7880 | 主入口，作者用 |
| **API 文档（Swagger）** | http://localhost:8000/docs | 仅开发模式可访问 |
| **健康检查** | http://localhost:7880/api/health | 排查时用 |
| **OpenAPI JSON** | http://localhost:8000/openapi.json | 给自动化工具 |

### 8.2 账号

**目前没有登录系统**——上游 Bibliogon 假设单机使用。**新版本（治理后）的"作者身份"由 `X-User-Id` HTTP 头标识**（卡 D/E/F 卡 D 引入），用于：

- D 卡：发布 canonical revision 必须传 `X-User-Id: <author-id>`
- E 卡：写正史必须传 `X-User-Id: <author-id>`
- F 卡：AI 智能体调必须传 `X-AI-Run-Id: <run-id>`（且作者**不可用** AI 端点）

**当前状态下**：
- 普通浏览器访问、Books / Articles / TTS / Export 等全部上游模块**不需要任何账号**（开箱即用）
- 治理新增的 7 个 AI 智能体端点（`/api/ai/agents/*`）需要创建 `AiRun` 行 → 通过外部工具（CLI、curl）调用
- 治理新增的 7 个 Revisions 端点（`/api/revisions/*`）+ Canon 端点需要创建 `User(role='author')` 行 → 通过外部工具调用

**创建账号的最小命令**（仅供测试）：

```bash
docker compose -f docker-compose.prod.yml exec backend python <<'EOF'
from app.database import SessionLocal
from app.models import User
import secrets
db = SessionLocal()
u = User(id=secrets.token_hex(16), username="me", role="author")
db.add(u)
db.commit()
print("USER_ID =", u.id)
EOF
# 记下输出的 USER_ID，下面调治理端点用：
# curl -H "X-User-Id: <USER_ID>" http://localhost:7880/api/books

docker compose -f docker-compose.prod.yml exec backend python <<'EOF'
from app.database import SessionLocal
from app.models import AiRun
import secrets
db = SessionLocal()
r = AiRun(id=secrets.token_hex(16), provider="cloudmist")
db.add(r)
db.commit()
print("AI_RUN_ID =", r.id)
EOF
# 记下输出的 AI_RUN_ID，调 /api/ai/agents/drafting/generate 用：
# curl -H "X-AI-Run-Id: <AI_RUN_ID>" .../api/ai/agents/drafting/generate ...
```

> 注：治理层"账号抽象"是 HTTP 头而非 session/cookie，未来要加登录页（OAuth、邮箱）属于扩展工作。当前阶段，把 `X-User-Id` 视作"作者临时凭据"即可。

### 8.3 第一次测试（30 秒跑通）

打开浏览器 → http://localhost:7880

应看到 **Dashboard** 页（`Dashboard.tsx`）。

按这个顺序点：

1. **Create Book** → 弹出新建书表单（默认 `book_type=prose`）
2. 填书名（例如《测试小说》）、选填作者 → 保存 → 跳到 BookEditor
3. BookEditor 左侧是章节列表（暂时空）
4. **Add Chapter** → 填章节名（如"第一章 测试章"）→ 出现 TipTap 编辑器
5. 在编辑器内随便敲 50 字内容
6. 等几秒 → 自动 autosave（默认 800ms 防抖）
7. 左侧章节列表多了一行 → 点击其他位置，切换章节，**编辑器内容已落库**
8. 切到 **ProjectOutline** 页（顶部菜单） → **新建卷 → 新建部 → 把刚才的章拖到部下**（卡 C 的四级结构生效了）
9. 切到 **Export** 页（顶部菜单）→ 选 Markdown 格式 → 点 Export → 下载 .md 文件
10. 切回 **Dashboard** → 那本书出现在卡片中

> 以上 10 步完全不依赖任何 AI，是纯上游功能。可以证明上游基线稳。

---

## 九、关键配置说明

按"改动频度"排序。

### 9.1 必须配置（不开 AI 也能用）

| 变量 / 文件 | 位置 | 改法 | 注意事项 |
|---|---|---|---|
| `.env` 中 `BIBLIOGON_PORT` | 项目根 | 改端口 | 不与现有服务冲突 |
| `.env` 中 `BIBLIOGON_SECRET_KEY` | 项目根 | 自动生成 | **不要泄漏**到截图 / 备份 |
| `BIBLIOGON_DATA_DIR` | 环境变量 | 改数据目录 | Docker 里默认 `/app/data`；本地默认 XDG 路径 |
| `backend/config/app.yaml` 中 `app.default_language` | 项目内 | 改默认语言 | 支持 de/en/es/fr/el/pt/tr/ja |
| 同 yaml `ui.theme` | 项目内 | 改主题（warm-literary/cool-modern/nord/classic/studio/notebook × light/dark） | 12 组合 |
| 同 yaml `plugins.enabled` | 项目内 | 启停插件 | 添加插件名后需要重启 |

### 9.2 重要但可不开

| 变量 / 文件 | 用途 | 不开的副作用 |
|---|---|---|
| `BIBLIOGON_AI_API_KEY`（治理前） | 上游旧 AI 流 | 不开就没 AI 助手菜单 |
| `BIBLIOGON_CREDENTIALS_SECRET` | Fernet 加密服务账号 | 不开就不能存外部 API 凭据 |
| `BIBLIOGON_LAN_MODE=1` | 局域网访问 + PIN 闸门 | 不开只能本机访问 |

### 9.3 治理新增（卡 F 引入）

| 变量 | 默认 | 含义 | 必填？ |
|---|---|---|---|
| `CLOUDMIST_API_KEY` | 无（必须设） | CloudMist 中转站 API Key | **是**（AI 功能） |
| `LLM_PROVIDER` | `cloudmist` | Provider 选择（目前只支持 cloudmist） | 否 |
| `LLM_BASE_URL` | `https://api.cloudmist.cloud/v1` | 中转站 URL | 否 |
| `LLM_MODEL` | `deepseek-v4-flash-0731` | 模型名锁版本 | 否 |
| `AI_GENERATION_ENABLED` | `false` | 是否启用 AI | 否（默认 false，要开改 true） |
| `ENABLED_AGENTS` | `""`（全空 = 全部可用） | 启用的智能体白名单（逗号分隔 7 个） | 否 |

**示例：只开 drafting + reviewer 两个智能体，其他全禁**：

```bash
export CLOUDMIST_API_KEY="sk-xxxx..."                # 你的真实 key
export AI_GENERATION_ENABLED="true"
export ENABLED_AGENTS="drafting,reviewer"
```

**这些变量的特点**：
1. **绝不写入** `app.yaml`（卡 F 红线）
2. **绝不写入**数据库（卡 F 红线）
3. **启动时校验**：缺 `CLOUDMIST_API_KEY` 立即报错（`get_llm_provider()` raise RuntimeError）
4. **冗余防护**：`AISettings` 在 Python 进程内是 frozen dataclass，不读 env var（双保险）

### 9.4 配置生效优先级（参考 docs/configuration.md）

```
环境变量（最高）     ←  docker / CI 注入
   ↑ 覆盖
用户 secrets.yaml   ←  ~/.config/bibliogon/secrets.yaml  ← 敏感配置
   ↑ 覆盖
用户 overlay yaml   ←  ~/.local/share/bibliogon/config/app.yaml  ← Settings UI 写
   ↑ 覆盖
项目 app.yaml       ←  backend/config/app.yaml  ← 提交到代码库的默认
```

**实操建议**：
- 数据库路径 / 端口：改 `.env`
- 个人偏好主题：改 Settings UI → 写用户 overlay
- AI 密钥：env var 或 secrets.yaml（**绝不入 app.yaml**）
- 团队行为默认值（autosave 时间、每日字数目标）：改 project app.yaml 然后提交

### 9.5 app.yaml 可改的小项（部分展示）

```yaml
editor:
  autosave_debounce_ms: 800          # 800ms 后自动保存（防抖）
  draft_save_debounce_ms: 2000      # 草稿保存防抖
  draft_max_age_days: 30            # 草稿保留 30 天
  ai_context_chars: 2000            # AI 生成上下文最大字符

app:
  default_language: de              # UI 默认语言
  trash_auto_delete_enabled: true
  trash_auto_delete_days: 90        # 回收站 90 天后清空
  max_upload_mb: 500                # 上传大小上限（修改需重启）

ui:
  defaults:
    book_type: prose                # 默认新建书的类型
    content_type: blogpost          # 默认新建文章的类型
```

---

## 十、故障排查

### 10.1 启动失败

| 症状 | 诊断 | 修复 |
|---|---|---|
| `Cannot connect to Docker daemon` | Docker Desktop 没启动 | 启动 Docker Desktop |
| 端口 7880 被占 | 另一程序占用 | 改 `.env` 中 `BIBLIOGON_PORT=7881` |
| `BIBLIOGON_SECRET_KEY` 未设置错误 | install.sh 未跑 | 手动加 export 或者跑 install |
| `CLOUDMIST_API_KEY not set, refusing to start` | AI 启动校验失败 | 设 env var 或关 `AI_GENERATION_ENABLED=false` |
| `ModuleNotFoundError: app.something` | 容器没 build 干净 | `docker compose build --no-cache backend` |
| `Migration 'x' is missing` | 数据库有脏迁移 | `alembic current; alembic upgrade head` 看具体错 |

### 10.2 启动后但页面 502

```bash
# 检查后端容器是否健康
docker compose -f docker-compose.prod.yml ps
# HEALTHCHECK 一栏必须是 "Up X minutes (healthy)"

# 查后端日志
docker compose -f docker-compose.prod.yml logs backend --tail=200 | grep -i "error\|traceback"
```

常见：
- `init_db()` 卡住 → 通常是因为 alembic 卡死在某迁移上。**不要重跑 init**，先看 `migrations/versions/` 哪个版本列错位了
- `ProviderFactory` 启动 30s 后才报错 → 检查网络是否能 reach `api.cloudmist.cloud`

### 10.3 页面打开后空白

1. 浏览器开发者工具 Network → 看 `/api/health` 是否 200
2. 如果 200，但白屏 → 前端 bundle 没出。看 frontend 容器日志是否有 `npm run build` 报错
3. 如果 404 SPA fallback → 看 nginx.conf 是否正确（生产模式已有 `try_files`）

### 10.4 数据库相关

| 现象 | 原因 | 修复 |
|---|---|---|
| `PRAGMA foreign_keys constraint failed` | 删 Book 时连带章节失败 | 加 `ON DELETE CASCADE` 或先删子项 |
| 多处 `bibliogon.db is locked` | WAL 模式下同时写 | 不要在并发脚本里直接 sqlite3 写 DB，调 API |
| `alembic value error: ... can't locate revision` | 合并分支，多 head | 用 `alembic heads` 看，**用显式版本号**降级而不是 `-1` |

### 10.5 AI 调用失败

| 错误码 | 原因 | 修复 |
|---|---|---|
| 401 (invalid_ai_identity) | `X-AI-Run-Id` 头不存在或 AiRun 行被删 | 重新创建 AiRun，重新拿 ID |
| 403 (ai_role_cannot_modify_revision/canon) | AI 想写正史/活跃 revision，物理上禁止 | 改用作者身份调（X-User-Id） |
| 422 (invalid_agent_role) | 智能体名不在 7 个白名单 | 检查路径，7 个候选：drafting/reviewer/scribe/foreshadow/worldbuilder/outliner/context |
| 403 (agent_role_not_enabled) | 环境变量 `ENABLED_AGENTS` 不含这个角色 | 在 env 加这个角色 |
| 502/504 | 中转站超时 | 60s 超时，可重试。看 `docker logs backend` 中具体 trace |
| "Provider refused" RuntimeError | 缺 `CLOUDMIST_API_KEY` | 设 env var，重启后端 |

### 10.6 卡顿 / 慢

- TTS 生成慢 → EdgeTTS 最快，Google TTS 慢但便宜，ElevenLabs 收费但最像人声
- 导出大文件慢 → WeasyPrint 跑 100MB+ 文件时建议分章节导出
- AI 慢 → 60s 超时内应返回，如果反复 60s 超时：检查中转站账单 / 模型热度
- 前端卡 → 关掉其他 tab（每开一个 chapter editor 都会订阅 WebSocket）

### 10.7 数据丢失 / 误删

```bash
# 1. 立刻停服务（防止继续覆盖）
docker compose -f docker-compose.prod.yml stop

# 2. 查最后一次 commit hash
docker compose -f docker-compose.prod.yml exec backend \
  python -c "
import sqlite3
db = sqlite3.connect('/app/data/bibliogon.db')
for row in db.execute('SELECT * FROM book_audit_log ORDER BY created_at DESC LIMIT 5'):
    print(row)
"

# 3. 如果有 backup，可以回滚
docker compose -f docker-compose.prod.yml exec backend \
  curl http://localhost:8000/api/backup/list
# 选一个时间点的 backup id / 调 /api/backup/import/{bid} 恢复
```

---

## 十一、快速上手示例

下面是一套**完整可用**的最小示例，分两种风格：浏览器版 + curl 版。

### 11.1 浏览器版（最简单）

按 [八、入口地址、账号、第一次测试](#八入口地址账号第一次测试) 那个 10 步清单做就行。**5 分钟能跑通**。

接下来加 AI：

1. 在根目录建 `.env`：
   ```bash
   echo "CLOUDMIST_API_KEY=sk-xxxx你真实的key" >> .env
   echo "AI_GENERATION_ENABLED=true" >> .env
   echo "ENABLED_AGENTS=drafting,reviewer,scribe,foreshadow,worldbuilder,outliner,context" >> .env
   ```
2. 重启：`docker compose -f docker-compose.prod.yml restart backend`
3. 看后端日志：`docker compose -f docker-compose.prod.yml logs backend --tail=20 | grep -i provider`
   - 期望看到类似 `LLM provider: cloudmist / deepseek-v4-flash-0731`
4. 现在 AI 端点已可用。但前端目前**还没集成 AI 调用按钮**（卡 F 只做后端 7 端点 + 权限守门，前端集成是卡 G 计划）
5. 要测 AI，可用 curl（见 11.3）

### 11.2 curl 完整链路（治理全功能示例）

> ⚠️ 这一段是**完整业务流程**，比浏览器版本更彻底；适合做冒烟测试 / 自动化测试 / 给其他人演示。

```bash
# ====== 阶段 0：拿两个身份（author + ai）======
# 浏览器以外的"身份"是数据库里的行。手动建：

USER_ID=$(docker compose -f docker-compose.prod.yml exec -T backend python -c "
from app.database import SessionLocal
from app.models import User
import secrets
db = SessionLocal()
u = User(id=secrets.token_hex(16), username='demo-author', role='author')
db.add(u); db.commit()
print(u.id)
")

AI_RUN_ID=$(docker compose -f docker-compose.prod.yml exec -T backend python -c "
from app.database import SessionLocal
from app.models import AiRun
import secrets
db = SessionLocal()
r = AiRun(id=secrets.token_hex(16), provider='cloudmist')
db.add(r); db.commit()
print(r.id)
")

echo "USER_ID=$USER_ID"
echo "AI_RUN_ID=$AI_RUN_ID"

BASE="http://localhost:7880/api"
AUTH="X-User-Id: $USER_ID"
AI="X-AI-Run-Id: $AI_RUN_ID"

# ====== 阶段 1：基础建书（无权限）======
# 注意：books API 不需要 X-User-Id（上游）
BOOK_ID=$(curl -s -X POST "$BASE/books" \
  -H "Content-Type: application/json" \
  -d '{"title":"测试长篇","author":"测试作者"}' \
  | python -c "import sys, json; print(json.load(sys.stdin)['id'])")
echo "BOOK_ID=$BOOK_ID"

# ====== 阶段 2：建章（C 卡四级的核心节点）======
CHAPTER_ID=$(curl -s -X POST "$BASE/books/$BOOK_ID/chapters" \
  -H "Content-Type: application/json" \
  -d '{"title":"第一章 测试章","content":"这是基础内容。"}' \
  | python -c "import sys, json; print(json.load(sys.stdin)['id'])")
echo "CHAPTER_ID=$CHAPTER_ID"

# ====== 阶段 3：建项目树（卡 C）======
ROOT_NODE=$(curl -s -X POST "$BASE/project-tree" \
  -H "Content-Type: application/json" \
  -d "{\"book_id\":\"$BOOK_ID\",\"name\":\"测试卷\",\"level\":\"volume\"}" \
  | python -c "import sys, json; print(json.load(sys.stdin)['id'])")
echo "ROOT_NODE=$ROOT_NODE"

PART_NODE=$(curl -s -X POST "$BASE/project-tree" \
  -H "Content-Type: application/json" \
  -d "{\"book_id\":\"$BOOK_ID\",\"name\":\"第一部\",\"level\":\"part\",\"parent_id\":\"$ROOT_NODE\"}" \
  | python -c "import sys, json; print(json.load(sys.stdin)['id'])")
CHAPTER_NODE=$(curl -s -X POST "$BASE/project-tree" \
  -H "Content-Type: application/json" \
  -d "{\"book_id\":\"$BOOK_ID\",\"name\":\"第一章\",\"level\":\"chapter\",\"parent_id\":\"$PART_NODE\",\"chapter_id\":\"$CHAPTER_ID\"}" \
  | python -c "import sys, json; print(json.load(sys.stdin)['id'])")
echo "CHAPTER_NODE=$CHAPTER_NODE"

# ====== 阶段 4：AI 草稿（卡 F 唯一写库路径）======
DRAFT=$(curl -s -X POST "$BASE/ai/agents/drafting/generate" \
  -H "Content-Type: application/json" \
  -H "$AI" \
  -d "{\"chapter_id\":\"$CHAPTER_ID\",\"instruction\":\"继续写一段 200 字\"}")
echo "DRAFT response: $DRAFT"
REVISION_ID=$(echo $DRAFT | python -c "import sys, json; print(json.load(sys.stdin)['revision_id'])")
echo "REVISION_ID=$REVISION_ID"

# ====== 阶段 5：作者 review（candidate → active 发布）======
# 5.1 写一条证据
EVIDENCE=$(curl -s -X POST "$BASE/revisions/$REVISION_ID/evidence" \
  -H "Content-Type: application/json" \
  -H "$AUTH" \
  -d "{\"decision\":\"approved\",\"checked_by\":\"demo\",\"note\":\"看起来 OK\"}")
echo "EVIDENCE response: $EVIDENCE"

# 5.2 发布（双门禁：evidence + content_hash）
CONTENT_HASH=$(echo $DRAFT | python -c "import sys, json; print(json.load(sys.stdin)['content_hash'])")
PUBLISH=$(curl -s -X POST "$BASE/revisions/$REVISION_ID/publish" \
  -H "Content-Type: application/json" \
  -H "$AUTH" \
  -d "{\"content_hash\":\"$CONTENT_HASH\"}")
echo "PUBLISH response: $PUBLISH"

# ====== 阶段 6：正史确认（卡 E）======
DELTA_ID=$(curl -s -X POST "$BASE/canon/deltas" \
  -H "Content-Type: application/json" \
  -H "$AUTH" \
  -d "{\"book_id\":\"$BOOK_ID\",\"fact_payload\":{\"key\":\"main_char\",\"value\":\"张三\",\"context\":\"主角\"}}")
echo "DELTA response: $DELTA_ID"

# 6.1 采纳
DECIDE=$(curl -s -X POST "$BASE/canon/deltas/${DELTA_ID}/decide" \
  -H "Content-Type: application/json" \
  -H "$AUTH" \
  -d "{\"decision\":\"accept\"}")
echo "DECIDE response: $DECIDE"

# 6.2 读 Canon 看采纳结果
CANON=$(curl -s -H "$AUTH" "$BASE/canon?book_id=$BOOK_ID" | python -m json.tool)
echo "CANON snapshot:"
echo "$CANON"

# 6.3 反悔 → rollback
ROLLBACK=$(curl -s -X POST "$BASE/canon/rollback" \
  -H "Content-Type: application/json" \
  -H "$AUTH" \
  -d "{\"book_id\":\"$BOOK_ID\",\"target_delta_id\":\"$DELTA_ID\"}")
echo "ROLLBACK receipt:"
echo "$ROLLBACK"

# ====== 阶段 7：导出 + 备份 ======
EXPORT_URL=$(curl -s -X POST "$BASE/books/$BOOK_ID/export/async/markdown" \
  -H "Content-Type: application/json" \
  -H "$AUTH" -d '{}' \
  | python -c "import sys, json; print(json.load(sys.stdin).get('job_url', ''))")
echo "EXPORT job URL: $EXPORT_URL"

BACKUP=$(curl -s -X GET "$BASE/backup/export" -H "$AUTH" -o "/tmp/test_backup.bgb" -w "%{http_code}\n")
echo "Backup status: $BACKUP; saved to /tmp/test_backup.bgb"
ls -la /tmp/test_backup.bgb

# ====== 阶段 8：错误示例（演示权限守门）======
# 8.1 匿名访问 → 401
echo "8.1 匿名访问 /api/books（应该 401）："
curl -s -o /dev/null -w "%{http_code}\n" "$BASE/books"

# 8.2 作者访问 AI 端点 → 403（author_cannot_use_ai_agent）
echo "8.2 作者访问 AI drafting 端点（应该 403）："
curl -s -o /dev/null -w "%{http_code}\n" -X POST "$BASE/ai/agents/drafting/generate" \
  -H "Content-Type: application/json" -H "$AUTH" \
  -d "{\"chapter_id\":\"$CHAPTER_ID\"}"

# 8.3 AI 访问正史写入端点 → 403（ai_role_cannot_modify_canon）
echo "8.3 AI 调 /api/canon/deltas（应该 403）："
curl -s -o /dev/null -w "%{http_code}\n" -X POST "$BASE/canon/deltas" \
  -H "Content-Type: application/json" -H "$AI" \
  -d "{\"book_id\":\"$BOOK_ID\",\"fact_payload\":{\"key\":\"x\",\"value\":\"y\"}}"

echo "=== 全流程跑完 ==="
```

如果三处 401/403/403 都通过，并且所有返回 200/201/202 = 治理系统全通过。

### 11.3 AI 调用最小示例（仅 AI 部分）

假设前两步已建好 `BOOK_ID` 和 `CHAPTER_ID`：

```bash
# Author user id + AI run id 上面拿到了
BASE="http://localhost:7880/api"

# drafting 生成 → 返回 candidate revision
curl -s -X POST "$BASE/ai/agents/drafting/generate" \
  -H "Content-Type: application/json" \
  -H "X-AI-Run-Id: $AI_RUN_ID" \
  -d "{\"chapter_id\":\"$CHAPTER_ID\",\"instruction\":\"继续写一段\"}" | python -m json.tool

# reviewer 评估 → 不直接写库，返回建议
curl -s -X POST "$BASE/ai/agents/reviewer/review" \
  -H "Content-Type: application/json" \
  -H "X-AI-Run-Id: $AI_RUN_ID" \
  -d "{\"revision_id\":\"$REVISION_ID\"}" | python -m json.tool

# context 打包 → 返回供前端组件的缓存输入
curl -s -X POST "$BASE/ai/agents/context/build" \
  -H "Content-Type: application/json" \
  -H "X-AI-Run-Id: $AI_RUN_ID" \
  -d "{\"book_id\":\"$BOOK_ID\",\"scope\":\"all\"}" | python -m json.tool
```

七智能体端点（路径固定格式 `POST /api/ai/agents/{role}/{action}`）：

| 角色 | action | 入参（最小） | 写库？ |
|---|---|---|---|
| `drafting` | `generate` | `{chapter_id, instruction}` | **是**（candidate revision） |
| `reviewer` | `review` | `{revision_id}` | 否（返 decision 建议） |
| `scribe` | `extract-facts` | `{chapter_id}` | 否 |
| `foreshadow` | `scan` | `{chapter_id}` | 否 |
| `worldbuilder` | `check` | `{chapter_id}` | 否 |
| `outliner` | `suggest` | `{book_id}` | 否 |
| `context` | `build` | `{book_id, scope}` | 否（缓存） |

---

## 十二、技术风险 / 已知限制

### 12.1 上游 Bibliogon 自身的限制（无法治理掉）

| 限制 | 描述 | 缓解 |
|---|---|---|
| **单机使用假设** | 无多用户/多设备同步，无登录机制 | 治理层引入 `X-User-Id` 头是过渡；正式 OAuth 是未来工作 |
| **LangExtract 性能** | 短长篇各 100+ 万字时，纯 Python 解析慢 | 大文件导出走后台任务而不是 sync request |
| **浏览器 PWA 数据库** | IndexedDB 有 500MB 单库上限 | 服务端 schema 是真正的 canonical，浏览器是 cache |
| **Pandoc 依赖** | 某些导出要 Pandoc 3.x；Dockerfile 已装 | 离线环境参考 docker-compose |
| **Story Bible 单表** | 上游 Story Bible 有一张总表存所有实体，5 类型 | 治理把它作为"只读分组 + 锚文本引用"，未改它的物理结构 |
| **Microsoft Translation 旧版** | 使用 v3 API，跟随速度有限 | 留作扩展工作 |

### 12.2 本项目治理带来的技术债

| 风险 | 描述 | 何时修复 |
|---|---|---|
| **drafting/generate 返回 200 而非 201** | `backend/app/routers/ai_agents.py:79` 的 `response` 变量被遮蔽，但功能完全可用 | 卡 G（前端集成时一起修） |
| **测试 `test_agent_role_permissions_and_d_e_gates_remain` 名字误导** | 名字含 D/E 但实际只测 F 端点的 anonymous/author；D/E 由既有测试守护（49 + 11 passed） | 下一个测试整理 PR |
| **`X-User-Id` 不是 session/cookie** | 重启数据库要重新拿 ID | 未来加 OAuth2 |
| **AI 智能体端点无前端集成** | 卡 F 只交付后端 + 权限守门 | 卡 G：前端 AI 按钮 |
| **AiRunLog 时间不区分用户** | 只区分 run 而不区分具体 operator | 未来加 audit-trail 完整 UI |
| **集成测试 e2e 链路未串完整 Stack** | F 7 端点用 fake provider 跑；与 D/E 全链路联通尚未完整 Playwright 脚本 | 卡 G |
| **多分支 alembic 历史** | D 加的合并 revision `a6b7c8d9e0f1` 让 `-1` 降级不稳 | 已记录"用显式版本号" SOP |

### 12.3 安全风险

| 风险 | 描述 | 缓解 |
|---|---|---|
| **.env 含 SECRET_KEY 不小心 commit** | .env 未在 .gitignore 时会发生 | 已 .gitignored；commit 前确认 |
| **CloudMist API Key 进 docker log** | 启动日志若打 model + key 会泄漏 | 检查 `provider_factory.py`：只 print 模型名不打印 key |
| **AI prompt 注入** | 用户输入被拼进 prompt 调外部 LLM | 上游有 prompt 模板化与系统消息隔离；治理层把 AI 调用锁在 candidate 通道，物理上不让写正史 |
| **SQLite 单文件** | 单机 OK，但并发写有 lock | WAL 模式 + uvicorn 2 worker 通常撑得住；高并发需迁 Postgres |
| **AI 调用审计不存明文** | 仅哈希，没有 raw prompt 备份 | 故意设计——为隐私。审计目的足够，回溯不恢复 prompt |

### 12.4 兼容性问题

| 兼容性维度 | 当前状态 | 备注 |
|---|---|---|
| 上游 Bibliogon 版本 | 锁定 v0.59.0 | `HEAD detached at 7ab36cb2` |
| Python | 3.12（容器） | 本地 3.13 也可 |
| Node | 24 | 上游要 22+，卡 C 阶段实测要 24 |
| Poetry | 2.4 有 GBK bug on Windows | 治理阶段已切到 pip，本地开发用 Poetry 需 ≥ 2.5 |
| npm | ≥ 9 | 0 vulnerabilities（卡 C 严守） |
| Docker Compose v2 | 必备 | v1 不再测 |
| Windows Terminal / PowerShell | OK | 容器化运行不依赖 shell 版本 |
| macOS Apple Silicon | OK | Poetry/Pip 兼容 |
| Linux x86_64 / arm64 | OK | 同上 |

### 12.5 治理交付物的"宪法"地位

下面这些红线**任何情况下都不能破**（要破必须重开一张任务卡）：

- **R1**：AI 不得入正史（任何写入 Canon/CanonDelta 的路径必须双重防御）
- **R2**：仅作者可发布（AI 不能触发 publish）
- **R3**：哈希门禁（publish 必须 content_hash 校验）
- **R4**：可回滚审计（rollback 不删 audit，rollback 必须写三类 affected IDs）
- **R5**：AI 自动发布 / 自动采纳默认关闭（环境变量才开）
- **R6**：不改写上游（13 插件源码不动）
- **R7**：API Key 不入任何 yaml / db（仅环境变量 + Fernet 加密层）
- **R8**：AI 调用只存哈希不存明文

详情：`governance/phase-task-cards.md` 中"红线 R1-R8"段。

---

## 附录 A：六阶段治理 A→F 叠加状态

| 卡 | 主题 | 通过评分 | 关键成果 | 产出的文件 / 迁移 |
|---|---|---|---|---|
| **A** | 部署 | 5/5 | `docker-compose.prod.yml` 运行：nginx(7880) + FastAPI(8000) + SQLite(WAL) + pandoc + 13 插件 | — |
| **B** | 基线审计 | 通过 | 不动一行业务代码，只读源码 + 跑测试 | `phase-B-baseline-audit.md` |
| **C** | 项目树 & 大纲 | 10/10 | 四级目录 + L3 章引用 + Story Bible 锚文本 + 引用三态 + 38 passed | `a6b7c8d9e0f1_add_novel_project_tree.py` / `project_tree.py` / `project_references.py` / `test_project_tree.py` / 前端 ProjectOutline |
| **D** | 草稿 & 审核门禁 | 10/10 | Revision + 双门禁 + AI-fill 收口 + 7 passed | `b7c8d9e0f1a2_add_revision_gate.py` / `revisions.py` / `deps/auth.py`(部分) / `test_revision_gates.py` |
| **E** | 正史确认 | 8/8 | CanonDelta + Canon + 三类回滚 + partial unique + 4 passed | `d0e1f2a3b4c5_add_canon_and_rollback.py` / `canon.py` / `require_canon_author` / `test_canon_gates.py` |
| **F** | AI 接入 | 7/7 | 7 智能体 + CloudMist Provider + AiRunLog + 6 passed + 启动校验 | `e1f2a3b4c5d6_add_ai_run_log.py` / `ai_agents.py` / `services/llm/*` / `deps/auth.py`(完整) / `config/ai_settings.py` / `test_ai_agents.py` / `test_ai_settings_defaults.py` |

**总回归**：55 passed (38 C + 7 D + 4 E + 6 F) + Playwright 1 passed（卡 C）。

**端到端全栈链路**：AI 生成 → candidate → 人工证据 → publish → 双门禁 → CanonDelta → adopt → 回滚审计。

---

## 附录 B：相关文档索引

### 上游文档（`docs/`）

| 文件 | 用途 |
|---|---|
| `docs/API.md` | API 高层概览（不要看这个取代 Swagger） |
| `docs/MODULE-ARCHITECTURE.md` | 模块层架构（router → service → repo → model） |
| `docs/configuration.md` | 四层配置链（env-var > secrets > overlay > project） |
| `docs/VIBE-CODING-POLICY.md` | AI 助手开发规约 |
| `docs/SETTINGS-MENU-ARCHITECTURE.md` | UI 设置菜单一栏 |
| `docs/EXPORT-IMPORT-FORMATS.md` | 30+ 文件格式的导入导出 |
| `docs/CONCEPT.md` | 设计哲学 |
| `docs/CHANGELOG.md` | v0.13.0 → v0.59.0 历史 |
| `docs/UX-CONVENTIONS.md` | UI 命名 + 颜色 + 一致性规则 |
| `docs/architecture/state-machines.md` | 关键状态机（出版、采纳、回收） |
| `docs/MAXIMAL-OFFLINE-PARITY.md` | 离线/在线功能对等矩阵 |
| `CLAUDE.md` | 56KB，上游开发者大文档 |

### 治理文档（`governance/`）

| 文件 | 用途 |
|---|---|
| `phase-task-cards.md` | **宪法**：六张卡裁决表 + 红线 R1-R8 |
| `phase-F-handoff-to-codex.md` | 卡 F 完整交接令（最后一张卡，最重要） |
| `phase-F-delivery.md` | 卡 F 交付 + 验收 7/7 |
| 其他 `phase-*-delivery.md` | 五张卡的交付 + 验收记录 |

### 项目自有的其他关键源文件

| 文件 | 关键改动来源 |
|---|---|
| `backend/app/main.py` | 卡 F 启动校验（lifespan 中调 `get_llm_provider()`） |
| `backend/app/router_registration.py` | 卡 C/D/E/F 新增 4 个 router |
| `backend/app/deps/auth.py` | 卡 D 卡 D 部分 / 卡 E 卡 E 完整 / 卡 F 卡 F 完整 |
| `backend/app/config/ai_settings.py` | 卡 F 唯 1 个新文件：frozen dataclass |
| `backend/app/services/llm/{base,cloudmist,provider_factory}.py` | 卡 F Provider Client |
| `backend/app/services/project_references.py` | 卡 C 引用扫描器 |
| `backend/app/services/project_reference_worker.py` | 卡 C 24h cron worker |
| `backend/app/routers/{project_tree,revisions,canon,ai_agents}.py` | 卡 C/D/E/F 各 1 个新 router |
| `frontend/src/api/projectTree.ts` | 卡 C 新增前端 API 模块 |
| `frontend/src/components/book/ProjectOutline.tsx` | 卡 C 新增四级树视图 |
| `frontend/e2e/project-tree.spec.ts` | 卡 C 新增 Playwright 用例 |
| `frontend/nginx.conf` | 上游默认（生产 nginx 反代） |

---

**最后更新**：2026-08-23（六阶段全部通过后，归档版）。如有冲突以 `governance/phase-task-cards.md` 与 `governance/phase-F-delivery.md` 为准。
