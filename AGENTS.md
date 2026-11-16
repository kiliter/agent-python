# agent-python

<!-- #Created By AiCoding(codex) -->

本文件为 Codex、Claude Code、Antigravity 等 AI 编码 Agent 在本仓库工作提供统一工程指引；`CLAUDE.md` 通过相对路径软链接指向本文件，所有仓库级规则只在此处维护。

## 项目

智能申告报告填写与资源治理平台（`report-agent`）：基于单智能体自主规划、确定性平台工具与强证据核验的申告核查与可视化治理全栈平台（详见 `wiki/overview.md`）。

当前重点：平台稳健运行 + 知识库/SDD 规范对齐 + 按需接入新模板与渠道集成需求。
决策优先级：1) 强证据零幻觉与线上运行稳定性  2) 平台零业务硬编码与单进程并发安全  3) 可维护性与 AI Agent 可操作性。

## 技术栈

Python 3.13（`>=3.12,<3.14`，容器 `python:3.13-slim` + `uv:0.7`）· FastAPI `>=0.115` + Uvicorn `>=0.32`（单进程 `workers=1`）· `pydantic-ai-slim[openai]==2.67.0` + Pydantic `>=2.12` · Jinja2 `>=3.1`（`SandboxedEnvironment`）· `httpx>=0.28` + `xml.etree.ElementTree`（含 `expat` XXE 防护）+ `jsonschema>=4.23` + `pyyaml>=6.0.2` · 前端 Vue `3.5` + TypeScript `5.8` + Vite `6` + Pinia `3` + Vue Router `4` + Element Plus + CodeMirror `6` · 存储采用文件系统（`DATA_DIR`）+ 内部 Git 版本库 + 原子软链接（无外部关系型数据库）。

版本以 `pyproject.toml`、`uv.lock` 与 `frontend/package.json` 为准，不要假设未核实的版本号。

## 命令

### 后端与测试（`uv`）

```bash
# 安装依赖（含开发与测试依赖）
uv sync --extra dev

# 初始化数据目录（导入内置 seed 资源并发布初始版本 r1，幂等）
uv run report-agent init

# 创建或更新工作台管理员账号（口令走 PBKDF2-HMAC-SHA256 哈希，不存明文）
uv run report-agent user add --username admin --password '<PASSWORD>' --display-name 系统管理员 --role 平台管理

# 启动服务（默认 0.0.0.0:8000；必须单进程 workers=1）
uv run report-agent serve
# 开发态热重载启动单进程 uvicorn：
uv run uvicorn report_agent.main:create_app --factory --reload

# 运行全量测试套件
# 说明：tests/conftest.py 的 autouse fixture 会将 report_agent.container.SEED_DIR 隔离至
# tests/fixtures/seed/（样例模板 1001），防止单元测试受生产 seed（模板 100~132）改动影响；
# tests/test_migrated_seed.py 则专门针对 src/report_agent/seed/ 生产资源做契约与结构回归。
uv run pytest

# 运行单个测试文件或用例
uv run pytest tests/test_agent_runtime.py -k "test_name"

# Python 静态代码检查
uvx ruff@0.11.0 check src tests
```

### 前端工作台与嵌入窗口（`frontend/`）

```bash
cd frontend && npm ci
npx vue-tsc --noEmit -p tsconfig.app.json
npm run build

# 本地联调启动（/api 自动代理至 http://127.0.0.1:8000）
VITE_USE_MOCK=false npm run dev
```

### Java 资源迁移与一致性对拍套件（`tools/java_migration/`）

当同步或校验前代 Java 仓库（默认 `/Users/zhangjialin/IdeaProjects/agent`，可通过 `JAVA_AGENT_HOME` 覆盖）迁移而来的 33 个生产模板、11 个填报 Skill 与 3 个接口契约时使用：

```bash
# 1. 重新生成 seed/templates 与 TEMPLATES.md
uv run python tools/java_migration/generate.py

# 2. 结构与发布静态校验（S1~S9：0 error / 0 warning）
uv run python tools/java_migration/verify_structure.py

# 3. Java Pebble 真实引擎 vs Python Jinja2 沙箱多场景逐字渲染等价对拍
uv run python tools/java_migration/verify_render.py

# 4. Skill frontmatter、接口契约 Schema、统一网关 XML 字节级对拍及 Groovy vs Python 原语对拍
uv run python tools/java_migration/check_skills.py

# 5. 端到端冒烟（真实大模型 + Mock 网关，在临时数据目录副本上试跑指定模板，默认 101）
uv run python tools/java_migration/smoke_run.py 101
```

改完代码默认运行与改动直接相关的测试及静态检查；交付前必须报告实际运行的命令与真实结果，未执行的验证不得标为完成。

## 通用约束

- **完整交付**：不留 `TODO`、`FIXME`、占位空实现或注释掉的死代码。
- **改动聚焦**：不捎带无关重构或顺手升级依赖；每处改动应能说明与当前需求的直接关联，收尾时核对 `git status` / `git diff` 确认未扩散范围。
- **优先复用**：优先复核并复用既有原语、领域校验器与工具模块，遵循 DRY、KISS、YAGNI。
- **实事求是**：实施前明确可验收标准，完成后报告真实命令输出；未运行或跳过的检查须明确说明原因。
- **禁止越权与自动提交**：未经用户明确要求不自动执行 `git commit`、`git push`、`git merge` 或生产部署；不确定时坦诚说明并给出选项。
- **AI 生成标记与中文注释**：新增或由 AI 生成的代码、脚本与文档在头部标注 `#Created By AiCoding(codex)`（Markdown 使用 `<!-- #Created By AiCoding(codex) -->`）；核心类、函数及复杂边界逻辑用清晰中文注释说明“为什么”，保留既有无关注释。
- **零凭据硬编码**：严禁在代码、测试、配置文件、文档或 `wiki/` 中写入任何真实 `LLM_API_KEY`、工作台口令、正式 `ra_` 密钥或敏感客户生产数据；含密钥的运行期热更新配置仅允许存于受忽略的 `DATA_DIR/config/runtime/`（`0600` 权限）。

### 日志、审计与过程事件

- 报告运行与嵌入式聊天关键链路（快照锁定、入参校验、模型轮次、工具调用、证据退回 `report_rejected`、部分降级 `report_degraded`、会话压缩、取消与确认）须通过 `Workspace` / `EventSink` 或结构化日志保留完整上下文，禁止静默吞错。
- 所有写操作及聊天确认审计（`audit.jsonl`）中的操作人一律取自服务端已认证身份（`user.display_name` 或 `chat:{userId}`），严禁采信前端提交的伪造操作人字段。
- 对外错误响应、运行详单与聊天脱敏步骤流必须屏蔽本地路径、认证凭证（如 `Authorization` / `Bearer` / `sk-`）与敏感字段原值，不得向外透出内部异常堆栈。

### 新增源码格式（只管新代码，不动老代码）

- **Python**：遵循 `pyproject.toml` 与 `uvx ruff@0.11.0 check src tests` 规范；保持类型注解清晰，避免长函数与过深嵌套。
- **TypeScript / Vue / CSS**：遵循 `npx vue-tsc --noEmit -p tsconfig.app.json` 与仓库既有 Vue 3 `<script setup lang="ts">`、CSS 变量双主题规范；不得因格式化破坏 Jinja2 或 HTML/SVG 属性契约。
- **YAML / Markdown / Jinja2**：保持既有键序与模板空白控制语义（如 Pebble 兼容换行裁剪），不得对无关历史模板批量重写。
- **范围控制**：新文件可整文件整理；存量文件仅格式化与检查本次新编写的代码段，未经要求禁止全目录批量格式化。

## 项目约束

- **零业务硬编码**：`src/report_agent/` 禁止出现任何特定模板编号、短信关键词、套餐规则或外部接口专属逻辑；业务知识全部承载于 `templates/<id>/`（`template.yaml` + `body.md.j2`）、纯文本 `skills/<id>/SKILL.md` 与声明式契约 `apis/*.yaml`。
- **单智能体与强证据防幻觉**：日历推算、秒差、清洗、结构化筛选与正则提取等机械计算统一由 `tools.py` / `text_tools.py` 的 12 个确定性原语执行；交卷结论须经 `EvidenceChecker.check()` 核验，重试耗尽后执行部分挽救与不变点级联降级；`ChatAgent` 上下文与 `memorySummary` 绝对禁止混入填报 `<document>` 或 `RunRequest.inputs`。
- **单进程部署约束（`workers=1`）**：存储层（乐观锁草稿、Git 发布互斥锁、`RunStore` 单写协程、`ChatStore` 64 分片锁与 `ChatRunManager`、`AuthService` 登录防爆破计数、`ReloadableGatewayClient` 引用计数槽位）均按单进程内存并发模型设计，生产 Uvicorn 必须严格保持 `workers=1`。
- **原子发布与路径边界**：版本切换必须通过 `os.replace` 原子覆盖 `releases/current`；任何资源发布前必须整棵加载执行 `validate_all()`；所有磁盘拼装路径必须经白名单正则与 `ensure_within` / `ensure_entry_within` 防软链逃逸校验。
- **测试隔离与 Mock 边界**：自动化单元测试使用 `ScriptedModel` / `FunctionModel` 与 `mock-gateway/`，禁止在单测中请求外网大模型或真实内网网关；新增或修改网关契约时须同步维护 `mock-gateway/` 脱敏样例并补充校验测试。
- **前端多入口分包边界**：`frontend/embed.html` 服务外部系统 iframe 嵌入，必须严格保持剥离 `element-plus` 与 `codemirror` 重型依赖，构建后确认 `embed` 产物洁净。
- **性能基线边界**：除非用户在具体需求中明确提出，不擅自引入压测或量化性能基线任务；实现层仍须避免阻塞主事件循环的同步文件/哈希计算及大数组深层响应式代理开销（使用 `asyncio.to_thread` 与 `markRaw`）。
- **Git Commit 前缀规范**：使用中文提交信息，约定前缀：`feat:`（新特性）、`fix:`（缺陷修复）、`refactor:`（重构不改契约）、`docs:`（文档/规格/Wiki）、`test:`（测试与对拍）、`chore:`（构建/依赖/杂项）。

## 核心架构与资源速查

### 目录结构

```text
agent-python/
├── src/report_agent/
│   ├── main.py / cli.py / config.py / container.py   # 应用入口、CLI、环境变量配置、依赖装配容器
│   ├── api/            # FastAPI 路由（routes_templates / routes_resources / routes_system / routes_chat）、鉴权（auth.py）、视图转换（run_views.py）
│   ├── chat/           # 嵌入式聊天窗口后端：分片存储（store.py）、聊天路由智能体（agent.py）、运行通道与步骤脱敏（manager.py / steps.py）、编排服务（service.py）
│   ├── domain/         # 领域模型与校验：模板（template.py）、Jinja2 沙箱与 TrackedValue/TrackedList（jinja_env.py）、Skill（skill.py）、接口契约（api_contract.py）、交叉校验（resources.py）
│   ├── gateway/        # 外部网关连接器：抽象基类（base.py）、统一网关 XML/JSON 客户端（unified_xml.py）、本地 Mock 网关（mock.py）、热更新引用计数包装（reloadable.py）
│   ├── runtime/        # 单智能体运行时：主管道（runner.py）、动态交卷模型（output_model.py）、证据核验（evidence.py）、12 个平台工具（tools.py + text_tools.py）、渲染（render.py）、提示词与模型工厂（prompt.py / model_factory.py）、工作区（workspace.py）
│   ├── store/          # 文件化存储与发布：目录布局（layout.py）、Git 封装（git_repo.py）、草稿箱（drafts.py）、发布器（publisher.py / releases.py）、叠加视图（service.py）、异步运行账本（runs.py）、用例（cases.py）、热更新配置（runtime_config.py）
│   └── seed/           # 内置生产资源：33 个模板（100~132）、12 个 Skill（11 个填报 + template-router）、3 个接口契约、mock-gateway 样例与 system-prompt.md
├── frontend/           # Vue 3 工作台（index.html）与嵌入式聊天窗口（embed.html）多入口前端
├── tools/java_migration/ # Java 资源迁移生成器、Java Harness 与四层对拍工具链
├── tests/              # pytest 单元测试与集成测试（含 ScriptedModel 确定性桩模型）
├── specs/              # Spec-Kit 需求规格、内联设计与任务清单（spec.md / plan.md / tasks.md）
├── docs/               # 前后端对接说明与嵌入式聊天窗口契约（chat-embed-api.md）等工程文档
└── wiki/               # 按 Karpathy LLM Wiki 模式维护的项目知识库
```

### 运行时数据目录（`DATA_DIR`，默认 `./data`）

| 子路径 | 作用 |
|---|---|
| `repo/` | 内部 Git 仓库（分支 `main`），每次发布、下线或回退上线均产生带结构化 Trailer 的 Commit |
| `releases/` | 发布历史索引 `index.jsonl`、不可变快照目录 `r1/`..`rN/`（默认保留最近 50 个，更早可经 `git archive` 按需恢复）及原子软链接 `current` |
| `drafts/` | 未发布草稿（`templates/<id>/`、`skills/<id>/`、`apis/<name>/`、`system-prompt/`），附带 `.meta.json`（`revision`、`baseRev`） |
| `runs/YYYY/MM/DD/` | 按日分区运行索引 `index.jsonl` 与运行详情 `<runId>.json`（由 `RunStore` 单协程异步队列顺序落盘） |
| `chats/<sid[:2]>/` | 嵌入式聊天窗口按 `(userId, orderId)` SHA-256 分片持久化的会话 `<sessionId>.json`（随 `RUNS_KEEP_DAYS` 清理） |
| `cases/<templateId>/` | 模板关联的回归测试用例 `<caseId>.yaml` |
| `mock-gateway/` | `GATEWAY_MODE=mock` 优先读取的自定义 Mock 响应（未命中回退 `seed/mock-gateway/`） |
| `config/` | 工作台账号库 `users.yaml`、HMAC 密钥 `.token-secret` 及运行期热更新配置 `runtime/`（权限 `0600`） |
| `audit.jsonl` | 登录、草稿变更、发布、回退、紧急切换、配置热更与聊天确认（`chat-confirm`）的只追加审计日志 |

### 12 个确定性平台工具与资源要点

- **调度与查询（3 个）**：`load_skill`（单个或批量加载白名单 Skill）、`call_api`（入参 Schema 校验 + 网关调用 + 同工作区幂等 Future 共享去重）、`query_result`（单表/多表 `resultIds` 合并过滤、严格列名校验含 0 行结果、`anyOf`/`between`/`prefixLen`、排序限量）。
- **文本、日历与正则原语（9 个）**：`normalize_text`、`text_contains`（跨行空白折叠）、`date_range`、`format_date`（`VALUE_TOOLS` 强核验转换，支持单值与批量 `values`）、`extract_dates`（4 规则真实日历扫描）、`date_shift`、`expand_period`（`$` 账期闭区间与离散升序展开）、`time_diff`、`regex_extract`（基于 `safe_regex_compile` 显式栈拦截嵌套量词防 ReDoS）。
- **单 Agent 管道与三级状态**：快照锁定 → 入参清洗校验 → `build_report_model`（`tool`/`native`/`json_object`/`prompted`）→ ReAct 循环 → `@agent.output_validator`（`quote`/`input`/`derive` + 列表逐行 + `found: []` 零行证明 + 可达环检测 + 不动点级联降级）→ Jinja2 沙箱渲染（`TrackedValue`/`TrackedList` 追踪实际展示字段）→ `SUCCESS` / `PARTIAL` / `FAILED`。

## Spec 开发流程

`.specify/memory/constitution.md` 是仓库 Spec-Kit 与实现流程的最高治理文件，本文件不得削弱其 `MUST` 约束；修订原则须单独更新宪章并同步变更记录。

标准流程：`需求收敛` → `speckit-specify` → `clarify` → `plan` → `tasks` → `analyze` → `implement`，除非用户明确授权跳过，不得越级。

### 入口映射

| 逻辑阶段 | Codex / Antigravity 技能 | Kiro Prompt |
|---|---|---|
| constitution / specify / clarify / plan / tasks / analyze / implement | `$speckit-<阶段>`（读 `.agents/skills/speckit-*/SKILL.md`） | `/speckit.<阶段>`（读 `.kiro/prompts/speckit.*.md`） |
| 辅助：checklist / converge / taskstoissues | `$speckit-<阶段>` | `/speckit.<阶段>` |

- `.specify/integration.json` 登记了 `kiro-cli`、`kimi` 与 `agy`，按当前会话环境选用对应入口，不混用语法。

### 需求收敛

进入 Spec Kit 编写前必须确认：业务目标、In Scope / Out of Scope、用户角色、异常与边界、验收标准及三类外部交付物涉及结论；有实质歧义时按“决策协议”给 3 选项。用户未确认需求范围前，不提前编写业务实现代码。

### 单文件内联 Plan 与三类外部独立交付物

- **单文件内联布局**：所有 `plan.md` 均采用 `<!-- SPECKIT_PLAN_LAYOUT: inline-v1 -->` 单文件内联格式，研究决策（`#plan-research`）、领域与存储模型（`#plan-data-model`）、内部接口契约（`#plan-contracts`）和验证指南（`#plan-quickstart`）直接内联于 `plan.md`，不另建 `research.md`、`data-model.md`、`contracts/` 或 `quickstart.md`。
- **三类外部独立交付物（先确认、按需生成）**：仅当确认涉及时生成并维护 `接口文档.md`、`资源迁移与Seed清单.md`、`部署与配置变更单.md`；不涉及项只记录判断依据，严禁创建空文件或失效链接。

### Wiki 影响门

- **plan**：第 `1.7` 节必须完成 `Wiki 影响评估`，写明“涉及 / 不涉及”及依据；涉及时逐项列出受影响的 `wiki/` 规范页面与索引。
- **tasks**：与 plan 一致，涉及时拆出独立 Wiki 同步与相对链接检查任务。
- **analyze**：核对 Spec / Plan / Tasks 对 Wiki 评估结论一致，且未按单次需求编号在 `wiki/` 新建碎片页。
- **implement**：按 `wiki/SCHEMA.md` 同步更新公共架构/组件/Skill 页面、`wiki/index.md` 与 `wiki/log.md` 变更记录。

### 跨 Agent 接续

接手既有需求或重构工作时，先读取本文件、`.specify/memory/constitution.md` 与目标 `specs/<dir>/` 产物，检查 `git status --short` 保留既有上下文，按产物完整度（而非仅看文件是否存在）判断进度，状态冲突时停止扩大写入并向用户报告。

## 深入了解

- 项目知识总入口 → [wiki/index.md](wiki/index.md)（回答架构、组件、Skill 或迁移问题前必读）
- 请求处理全链路 → [wiki/architecture/request-pipeline.md](wiki/architecture/request-pipeline.md)
- 强证据核验与防幻觉 → [wiki/architecture/evidence-system.md](wiki/architecture/evidence-system.md)
- 模板模型与 Jinja2 沙箱 → [wiki/architecture/template-and-rendering.md](wiki/architecture/template-and-rendering.md)
- 存储布局与 Git 原子发布 → [wiki/architecture/resource-release-and-store.md](wiki/architecture/resource-release-and-store.md)
- 12 个确定性平台工具 → [wiki/architecture/deterministic-tools.md](wiki/architecture/deterministic-tools.md)
- 嵌入式聊天窗口契约与剖析 → [docs/chat-embed-api.md](docs/chat-embed-api.md)、[wiki/components/chat-embed.md](wiki/components/chat-embed.md)
- Java 迁移与四层对拍指南 → [wiki/guides/java-migration-and-verification.md](wiki/guides/java-migration-and-verification.md)
- 已知约束与待确认台账 → [wiki/lint/known-issues.md](wiki/lint/known-issues.md)、[wiki/lint/open-questions.md](wiki/lint/open-questions.md)

## 决策协议

- 架构调整、新增外部依赖、存储或跨模块契约变更：提供方案对比、推荐选项与影响面，等待确认后再动手。
- 局部实现细节：直接落实并将关键取舍写入中文注释。
- 需求不清：给出 3 个具体可行选项与推荐理由，不做宽泛开放式追问。
- 不确定或遇阻时：坦诚说明已发现事实与缺口，不猜测臆造后直接执行。
