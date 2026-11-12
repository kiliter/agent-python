# AGENTS.md

<!-- #Created By AiCoding(codex) -->

本文件为 Codex、Claude Code 等 AI 编码 Agent 在本仓库中工作提供统一指引；`CLAUDE.md` 通过相对路径软链接指向本文件，所有规则只在此处维护。

## 项目概述

这是一个基于 **Python 3.13 + FastAPI + Pydantic AI** 的智能申告报告填写与资源治理平台（`report-agent`）。服务根据上游传入的单据文本（`document`）、结构化入参（`params`）与指定的报告模板（`templateId`），自动完成接口取数、规则判定、证据核验与报告渲染，同时提供可嵌入外部工单系统的聊天选模板窗口（`/embed.html` + `/api/v1/chat/*`）与配套的可视化资源工作台。

平台设计遵循以下核心原则：

- **零业务硬编码**：平台代码不包含任何特定模板、短信关键词或接口字段的业务逻辑。平台只提供通用确定性原语（文本清洗、结构化筛选、日期提取与偏移、正则提取、格式转换等）与证据核验引擎；所有业务知识完全承载于可热发布的**模板（`template.yaml` + `body.md.j2`）**、**纯文本 Skill（`SKILL.md`）**与**声明式接口契约（`apis/*.yaml`）**中。
- **单智能体自主规划 + 结构化交卷**：由单个 Pydantic AI `Agent` 在同一次运行工作区（`Workspace`）内自主按需加载 Skill、调用接口与确定性工具，最终通过严格 JSON Schema 生成的 `submit_report` 模型一次性提交所有字段值、证据链与推理说明，替代前代 Java 版（`pdf-agent-parse`）的三 Agent 串联编排与 Groovy 脚本引擎。
- **强证据校验与级联降级**：`@agent.output_validator` 在交卷阶段调用 `EvidenceChecker.check()`，按字段声明的 `quote`（原文逐字出现）/ `input`（入参非空原值）/ `derive`（规则推导，含 `VALUE_TOOLS` 日期格式化单值/批量输出核验，禁引 `load_skill` 或无真实支撑的 `not_found` 前置字段）模式逐项核验（含 `list` 字段逐行核验、0 行结果 `found: []` 强制核对 `count==0` / `total==0` 查询证明与缺失 `not_found` 区分、含指向环节点的字段依赖环检测）。校验不通过时精确退回错误字段重填；重试耗尽后执行部分挽救（`_salvage_partial_report`）与全量 `not_found` 依赖链级联降级（`_cascade_degraded_fields`），绝不让未经核验的幻觉进入最终报告。
- **Git 版本化资源治理**：业务人员在工作台编辑的草稿存储于 `drafts/`，测试验证通过后通过 Git 提交并导出不可变快照 `releases/rN/`，再以 `os.replace` 原子切换 `releases/current` 软链接上线，支持毫秒级紧急版本切换与历史自动恢复。

## 常用开发与校验命令

### 后端与环境管理（`uv`）

```bash
# 安装依赖（含开发与测试依赖）
uv sync --extra dev

# 初始化数据目录（导入内置 seed 资源并发布初始版本 r1，幂等）
uv run report-agent init

# 创建或更新工作台管理员账号（口令走 PBKDF2-HMAC-SHA256 哈希，不存明文）
uv run report-agent user add --username admin --password '<PASSWORD>' --display-name 系统管理员 --role 平台管理

# 启动服务（默认 0.0.0.0:8000；必须单进程 workers=1，见部署注意事项）
uv run report-agent serve
# 开发态如需热重载源码，可用 factory 模式启动单进程 uvicorn：
uv run uvicorn report_agent.main:create_app --factory --reload

# 运行全量测试套件
# 注意：tests/conftest.py 的 autouse fixture 会自动将 report_agent.container.SEED_DIR 隔离到
# tests/fixtures/seed/（样例模板 1001），避免单元测试受生产 seed（模板 100~132）改动影响；
# tests/test_migrated_seed.py 则专门针对 src/report_agent/seed/ 生产资源做契约与结构回归。
uv run pytest

# 运行单个测试文件或用例
uv run pytest tests/test_agent_runtime.py -k "test_name"

# Python 静态代码检查
uvx ruff@0.11.0 check src tests
```

### 前端工作台（`frontend/`）

```bash
# 安装前端依赖并执行 TypeScript 类型检查 + 生产构建
cd frontend && npm ci
npx vue-tsc --noEmit -p tsconfig.app.json
npm run build

# 本地联调启动（/api 自动代理至 http://127.0.0.1:8000）
VITE_USE_MOCK=false npm run dev
```

### Java 资源迁移与一致性对拍套件（`tools/java_migration/`）

当同步或校验前代 Java 仓库（默认路径 `/Users/zhangjialin/IdeaProjects/agent`，可通过 `JAVA_AGENT_HOME` 覆盖）迁移而来的 33 个生产模板、11 个填报 Skill（另含平台内置的 1 个聊天路由 Skill `template-router`，共 12 个 Skill）与 3 个接口契约时使用：

```bash
# 1. 从 Java 模板/rule/field-mappings + field_catalog.yaml 重新生成 seed/templates 与 TEMPLATES.md
uv run python tools/java_migration/generate.py

# 2. 结构与发布静态校验（S1~S9：模板集合、正文转换、字段/隐式依赖、规则覆盖、Skill/API 引用、AST 占位符/枚举静态门禁、0 error / 0 warning）
uv run python tools/java_migration/verify_structure.py

# 3. Java Pebble 真实引擎 vs Python Jinja2 沙箱多场景逐字渲染等价对拍
uv run python tools/java_migration/verify_render.py

# 4. Skill frontmatter、接口契约 Schema、统一网关 XML 字节级对拍及 Groovy vs Python 原语逻辑对拍
uv run python tools/java_migration/check_skills.py

# 5. 端到端冒烟（真实大模型 + Mock 网关，在临时数据目录副本上试跑指定模板，默认 101）
uv run python tools/java_migration/smoke_run.py 101
```

## 技术栈与目录结构速查

### 核心技术栈

- **Python**: `>=3.12,<3.14`（容器镜像基于 `python:3.13-slim` + `uv:0.7`）
- **Web 框架**: FastAPI `>=0.115` + Uvicorn `>=0.32`（支持 REST 与 SSE `text/event-stream`）
- **Agent 框架**: `pydantic-ai-slim[openai]==2.67.0` + Pydantic `>=2.12`
- **模板渲染**: Jinja2 `>=3.1`（`SandboxedEnvironment`，定制 Pebble 兼容换行裁剪与 `hasDigit`）
- **HTTP 与网关**: `httpx>=0.28` + `xml.etree.ElementTree`（含 expat XXE 防护）+ `jsonschema>=4.23` + `pyyaml>=6.0.2`
- **前端工作台**: Vue `3.5` + TypeScript `5.8` + Vite `6` + Pinia `3` + Vue Router `4` + Element Plus + CodeMirror `6`

### 代码目录结构

```text
agent-python/
├── src/report_agent/
│   ├── main.py / cli.py / config.py / container.py   # 应用入口、CLI、环境变量配置、依赖装配容器
│   ├── api/            # FastAPI 路由（routes_templates / routes_resources / routes_system / routes_chat）、会话与 API Key 鉴权（auth.py）、运行视图转换（run_views.py）
│   ├── chat/           # 嵌入式聊天窗口后端：会话分片存储（store.py）、聊天路由智能体（agent.py）、运行通道与步骤脱敏映射（manager.py / steps.py）、会话编排服务（service.py）
│   ├── domain/         # 领域模型与校验：模板（template.py）、Jinja2 沙箱与 TrackedValue/TrackedList（jinja_env.py）、纯文本 Skill（skill.py）、接口契约（api_contract.py）、全量交叉校验（resources.py）
│   ├── gateway/        # 外部网关连接器：抽象基类（base.py）、统一网关 XML/JSON 客户端（unified_xml.py）、本地 Mock 网关（mock.py）、热更新引用计数包装器（reloadable.py）
│   ├── runtime/        # 单智能体运行时：主管道（runner.py）、动态交卷模型（output_model.py）、证据核验器（evidence.py）、12 个平台工具（tools.py + text_tools.py）、渲染上下文（render.py）、提示词与模型工厂（prompt.py / model_factory.py）、工作区（workspace.py）
│   ├── store/          # 文件化存储与发布：目录布局（layout.py）、Git 仓库封装（git_repo.py）、草稿箱（drafts.py）、快照发布器（publisher.py / releases.py）、叠加视图服务（service.py）、运行记录异步写队列（runs.py）、回归用例（cases.py）、运行期配置热更新存储（runtime_config.py）
│   └── seed/           # 随包内置的生产初始资源：33 个模板（100~132）、12 个 Skill（11 个填报 Skill + 1 个聊天路由 Skill template-router）、3 个网关接口契约、mock-gateway 样例与 system-prompt.md
├── frontend/           # Vue 3 资源治理工作台与嵌入式聊天窗口（index.html + embed.html 多页入口，构建产物由 FRONTEND_DIST 托管）
├── tools/java_migration/ # Java 资源迁移生成器、Java Harness 与四层自动化对拍脚本
├── tests/              # pytest 单元测试与集成测试（含 ScriptedModel 确定性桩模型）
├── docs/               # 前后端对接说明与嵌入式聊天窗口契约（chat-embed-api.md）等工程文档
└── wiki/               # 按 Karpathy LLM Wiki 模式维护的项目知识库
```

### 运行时数据目录（`DATA_DIR`，默认 `./data`）

| 子路径 | 作用 |
|--------|------|
| `repo/` | 内部 Git 仓库（分支 `main`），每次资源发布、下线或回退上线都会产生一次带结构化 Trailer 的 Git Commit |
| `releases/` | 发布历史索引 `index.jsonl`、不可变版本目录 `r1/`..`rN/`（含 `.release.json`，默认保留最近 50 个目录，更早版本可经 `git archive` 按需恢复），以及指向当前线上版本的原子软链接 `current` |
| `drafts/` | 未发布的编辑草稿（`templates/<id>/`、`skills/<id>/`、`apis/<name>/`、`system-prompt/`），附带 `.meta.json` 乐观锁修订号 `revision` 与基准版本 `baseRev` |
| `runs/YYYY/MM/DD/` | 按日期分区的运行记录索引 `index.jsonl` 与完整运行详情 `<runId>.json`（由 `RunStore` 单协程异步队列顺序落盘） |
| `chats/<sid[:2]>/` | 嵌入式聊天窗口按 `(userId, orderId)` 哈希分片持久化的会话文件 `<sessionId>.json`（随 `RUNS_KEEP_DAYS` 自动清理过期会话） |
| `cases/<templateId>/` | 模板关联的回归测试用例 `<caseId>.yaml` |
| `mock-gateway/` | `GATEWAY_MODE=mock` 时优先读取的数据目录 Mock 响应文件（未命中时回退 `seed/mock-gateway/`） |
| `config/` | 工作台账号库 `users.yaml`、HMAC 会话密钥 `.token-secret`，以及运行期热重载配置 `runtime/`（`current.json`、`index.jsonl`、`revisions/cN.json`，权限 `0600`） |
| `audit.jsonl` | 登录、草稿变更、发布、回退、紧急切换、运行期配置变更与聊天报告确认（`chat-confirm`）的只追加审计日志 |

## 核心架构要点

### 1. 单 Agent 执行流（`runtime/runner.py#AgentRunner.run`）

1. **资源快照锁定**：按 `target` 捕获不可变 `ResourceSet`（上游调用固定取 `"online"` 即 `releases/current`，优先走 `ReleaseStore.try_live_snapshot()` 内存快路径；工作台试运行可选 `"draft"` 叠加视图，带 `ResourceService.overlay()` 指纹缓存），保证单次运行全程不受并发发布影响。
2. **入参校验与工作区初始化**：先对 `req.inputs` 统一 `.strip()` 去首尾空白，再经 `validate_inputs` 按 `template.yaml` 的 `inputs`（必填与正则 `pattern`）做快速失败校验；创建 `Workspace` 记录所有接口结果（`r1`, `r2`...，含幂等调用去重缓存）、工具调用（`t1`, `t2`...）、惰性单据定位索引 `DocumentIndex` 并通过 `EventSink` 推送 SSE 过程事件。
3. **动态生成与缓存交卷 Schema**：`build_report_model(template)` 基于模板字段定义动态构造严格 Pydantic 模型（`extra="forbid"`）：普通/枚举/日期字段产成单值结论，列表字段（`type: list`）生成强类型行对象数组 `list[RowModel]`；默认通过 `ToolOutput(..., name="submit_report")` 注册交卷工具（亦支持 `native` / `json_object` / `prompted` 输出模式），线上模式按 `(rev, tpl.id, bundle.seq)` 有界缓存 `(report_model, agent)`。
4. **ReAct 工具循环**：`Agent` 携带系统提示词与 `build_task_instructions` 动态任务说明（仅暴露当前模板白名单内的 Skill 与 API 摘要、剥离字段 `原规则（Java）：` 对照注释、并一并展示 `deps.inputs` 中未列入 `tpl.inputs` 的非空附加参数）自主规划调用平台工具（默认开启 `llm_parallel_tool_calls=True`、单次工具调用上限 `agent_tool_calls_limit=120`；全局并发由 `_DynamicLimiter` 与不可变 `_RuntimeBundle` 保证在线热重载原子切换）。
5. **强证据校验与重试/挽救**：模型交卷时触发 `@agent.output_validator` 中的 `EvidenceChecker.check()`：
   - 严守防幻觉闭环：空列表 `found: []` 仅接受 `call_api(count==0)` / `query_result(total==0)` 工具 `callId` 或 0 行 `api` / `document` 证据；任何字段均禁引 `load_skill` 或空串 `input`；`derive` 字段禁止无真实有效来源支撑地引用 `not_found` 前置字段；字段依赖环检测同时覆盖指向环的环外节点。
   - 存在违例且未达 `AGENT_OUTPUT_RETRIES`（默认 3 次）时，抛出 `ModelRetry` 将具体字段错误退回模型重填，发出 `report_rejected` 事件；
   - 重试耗尽后，直接降级或通过 `_salvage_partial_report()` 将仍不合规的字段强制降级为 `not_found`，再由 `_cascade_degraded_fields()` 沿字段级 `{"type": "field", "name": ...}` 证据链递归降级所有引用已降级字段或悬空依赖 `not_found` 前置字段的下游字段，发出 `report_degraded` 事件。
6. **Jinja2 沙箱渲染与三级状态判定**：
   - `field_render` / `build_render_context()` 将字段结论包装为 `TrackedValue`（标量字段，经过滤器转换仍保留 `field_names` 追踪）与 `TrackedList`（列表字段）：仅在 `{{ 字段 }}` 实际输出或 `{% for item in 列表 %}` 实际迭代时才通过 `ContextVar`（`_ACTIVE_USED`）标记该字段 `shown=True`（单纯用于 `{% if %}` 条件判断不标记为已展示）。
   - Jinja2 沙箱（`_TrackedSandboxEnvironment`）启用 `trim_blocks=True` + `_PebbleNewlineTrimExtension` 与 `is hasDigit` 测试，共享沙箱环境并以 `@lru_cache(maxsize=256)` 缓存预编译 `Template`，保持与前代 Java Pebble 3.2.2 模板逐字等价。
   - **三级运行状态**：异常/超时/超轮次上限或渲染异常为 `FAILED`；渲染后所有 `shown=True` 的可见字段均已找到（或 `whenMissing == "value"`，含列表字段合法查得 0 行 `status="found", value=[]`）为 `SUCCESS`；任一实际展示且无固定默认值的可见字段或列表处于 `not_found`（`missingShown` 非空）则为 `PARTIAL`。

### 2. 确定性平台工具集（共 12 个）

定义在 `src/report_agent/runtime/tools.py`（`build_tools`）与 `src/report_agent/runtime/text_tools.py`：

| 工具名 | 职责说明 |
|--------|----------|
| `load_skill` | 按单个 `name` 或批量 `names: list[str]` 按需加载当前模板白名单内的 `SKILL.md` 完整正文及可调用接口参数提示 |
| `call_api` | 按接口契约校验入参并调用外部统一网关（`live`，受 `GATEWAY_MAX_CONCURRENCY` 并发信号量保护）或本地样例（`mock`）；对 `idempotent: true` 的相同 `(name, args)` 在同一工作区自动共享在途请求并复用成功 `ApiResult`，返回含 `callId`、`resultId`、`count` 与截断预览 |
| `query_result` | 在工作区单个（`resultId`）或多个（`resultIds` 合并）接口结果上执行结构化过滤（支持 `equals`、`contains`、`notContains`、`normalizedContains`、`normalizedNotContains`、`startsWith`、`between`；支持 `before` 截断、`prefixLen` 前缀截取与 `anyOf` OR 条件组）、严格列名校验（含 0 行结果）、排序与限量读取，返回含 `callId`、`total` 与 `rows` |
| `normalize_text` | 确定性文本清洗（NFKC 归一化 + 去除零宽字符、固定中英文标点及可选 `extraChars`，对齐 Java `StringCharCleaner`） |
| `text_contains` | 判断 `target` 是否包含于 `text`（省略 `text` 时查单据全文；`normalize=True` 时默认一并剥离空白与换行符 `" \t\r\n\u3000"`，兼容跨行折行 PDF 匹配） |
| `date_range` | 提取合法分隔/紧凑日期（兼容带前缀文本与 `unit="month"` 下的 `yyyyMM`/`yyyy-M`/`yyyy年M月`）计算所在日（`day`）或自然月（`month`）的起止 14 位时间戳（`000000`～`235959`） |
| `format_date` | Java 风格日期时间格式确定性转换，支持单值 `value` 或批量 `values: list[str]`（唯一列入 `VALUE_TOOLS` 的工具：`derive` 字段引用其 `callId` 时核验提交值等于 `value` 或 `values` 任一元素） |
| `extract_dates` | 从文本（省略时取单据全文）按 4 条严格规则扫描（中文日期强制显式 `[日号]` 结尾）并经真实日历校验提取日期（8 位 `yyyyMMdd`，支持 `defaultYear` 补全年份，绝不误匹配活动编号/套餐档位/手机号），返回 `{callId, ok, dates, sorted, min, max, count}` |
| `date_shift` | 按真实日历（含大小月、跨年、闰年）对基准日期做天数偏移，支持单点或 `[days, endDays]` 区间并返回 14 位 `start` / `end` 窗口 |
| `expand_period` | 解析多账期（双段 `yyyyMM$yyyyMM` 按闭区间展开，多段 `$`/`,`/`;` 离散去重）、区间（`-`/`~`/`至`/`到`）、纯年月或具体日期，统一按月份升序输出 `months`、`monthRanges` 及 `startDate` / `endDate` |
| `time_diff` | 计算两个时间戳之间的精确秒级有符号差值 `diffSeconds`、绝对距离 `absSeconds` 与先后顺序 `later` |
| `regex_extract` | 使用安全编译正则（`safe_regex_compile` 基于语法树拦截嵌套重复量词防 ReDoS 回溯，单次文本上限 `200,000` 字符）提取指定捕获组非空匹配项，返回去重 `matches`、`allMatches`、`first` 与 `count` |

### 3. 三类文件化资源规范

1. **模板（`templates/<id>/`）**：
   - `template.yaml`：定义 `id`、`name`、`fields`（支持 `string`、`enum`、`date`、`list` 四种类型；`evidence` 取 `quote` / `input` / `derive`；`whenMissing` 取 `placeholder` / `empty` / `value`；支持 `quoteWhole` 整条引用约束与 `visible: false` 中间依赖字段）、`inputs` 与关联 `skills`。
   - `body.md.j2`：Jinja2 报告正文模板。
2. **纯文本 Skill（`skills/<id>/SKILL.md`）**：
   - YAML frontmatter（`name`、`title`、`description`、`apis`）+ Markdown 纯文本步骤说明，无任何可执行脚本。内置 11 个供填报智能体按需加载的取数/判定 Skill，以及 1 个供嵌入式聊天窗口专用的模板路由 Skill `template-router`（`apis: []`，按 `### <ID>` 三级标题维护全部在线模板的路由规则并受发布门禁交叉校验）。
3. **网关接口契约（`apis/<name>.yaml`）**：
   - 声明 `connector`（`unified-gateway-xml` 或 `unified-gateway-json`）、`processCode`、JSON Schema `input`、`request` 报文映射（支持 `${入参名}` 与平台内置占位符 `${$now}` 动态注入当前 `yyyyMMddHHmmss`），以及 `response` 判定与记录抽取规则（`success`、`noData`、`records.mode` 支持 `auto` / `object` / `list` / `scalar` / `none`、点分列路径与 `flatten`）。

### 4. 嵌入式聊天选模板窗口（`/embed.html` + `/api/v1/chat/*`）

1. **iframe 握手与双轨鉴权**：外部工单系统通过 iframe 嵌入 `/embed.html?userId=<u>&orderId=<o>`（工作台同时提供模拟联调页），经 `postMessage`（`chat-ready` ↔ `chat-init`）锁定首个父页面 `origin` 并仅在内存中持有 `apiKey`。`/api/v1/chat/*` 同时支持 `X-API-Key`（仅允许 `target="online"`）与管理端登录态（允许 `target="draft"`）；同一 `(userId, orderId)` 自动恢复原会话，上层入参或单据指纹变化时递增 `inputsVersion`、保留未冲突的用户补充入参并将旧运行卡片标为 `stale`。
2. **结构化模板路由与脱敏流式填报**：`ChatAgent` 通过只读工具加载 `template-router` 与在线模板元数据，输出经 `@agent.output_validator` 校验的 `ChatAction`（`reply` / `recommend` / `ask_params` / `start_run` / `rewrite`）；用户选定模板且补齐必填/正则参数后，由 `ChatRunManager` 在后台调用 `AgentRunner`（`entry="聊天窗口"`，单会话并发互斥），`StepMapper` 将过程事件脱敏映射为友好中文步骤并通过 SSE（支持 `?after=N` 与 `Last-Event-ID` 断点续接）实时推送；确认报告（`confirm`，对 `PARTIAL` 要求显式 `acknowledgePartial`，对 AI `rewrite` 版本醒目标注未经证据校验）具备幂等保护并写入 `audit.jsonl`，最终向父页面回传 `report-confirmed` 与 `chat-close-request`（完整契约见 `docs/chat-embed-api.md`）。

## 代码规范、Git 规范与知识库维护

### 代码与安全规范

- **AI 生成标记**：新增或由 AI 生成的代码文件、脚本与规范文档应在头部注释中加入固定标记：`#Created By AiCoding(codex)`（Markdown 中使用 `<!-- #Created By AiCoding(codex) -->`）。
- **中文注释**：核心类、函数、复杂分支与业务背景说明使用清晰准确的中文注释；维护已有文件时保留无关原有注释。
- **严禁硬编码凭证**：严禁在代码、测试、配置文件或 `wiki/` 中写入任何真实的 `LLM_API_KEY`、工作台口令、网关密钥或生产敏感数据。运行期热更新配置（`config/runtime/`）包含密钥，仅允许存放于受忽略的 `DATA_DIR` 内。
- **单进程部署约束**：存储层（乐观锁草稿、Git 发布互斥锁、`RunStore` 单写协程、`ChatStore` 会话锁与 `ChatRunManager` 运行通道、`AuthService` 登录防爆破计数、`ReloadableGatewayClient` 热更新槽位）均按单进程内存并发模型设计，生产运行 Uvicorn 必须保持 `workers=1`。

### Git Commit 规范

提交信息使用中文，前缀约定如下：

| 前缀 | 含义 | 示例 |
|------|------|------|
| `feat:` | 新增平台能力、工具或前端特性 | `feat: 新增确定性日期与正则平台工具并支持列表空结果证据核验` |
| `fix:` | 修复缺陷或历史迁移问题 | `fix: 修复模板 120 有设备押金缺失占位导致分支恒真问题` |
| `refactor:` | 重构代码结构（不改变外部契约） | `refactor: 抽离独立渲染上下文模块避免循环引用` |
| `docs:` | 更新文档、`AGENTS.md` 或 `wiki/` | `docs: 建立 agent-python LLM Wiki 知识库与架构决策记录` |
| `test:` | 新增或调整测试用例与对拍脚本 | `test: 补充 TrackedList 分支追踪与部分降级单元测试` |
| `chore:` | 构建配置、依赖版本或杂项调整 | `chore: 锁定 ruff 检查规则与前端构建脚本` |

### 项目知识库（`wiki/`）使用与维护

`wiki/` 是按 Karpathy LLM Wiki 模式维护的结构化项目知识库，代码始终是最终事实来源：

1. **先查后答**：在回答架构设计、组件职责、某个业务 Skill 逻辑、模板字段配置或 Java 迁移差异前，**先读取 `wiki/index.md`** 定位对应页面，再按需下钻到具体页面与源码核实。
2. **同步维护**：当修改了平台工具签名、证据核验规则、模板/Skill/接口契约、运行配置或修复了迁移差异后，必须按照 `wiki/SCHEMA.md` 同步更新受影响的 `wiki/` 页面与 `wiki/index.md`，并在 `wiki/log.md` 末尾追加变更记录。
