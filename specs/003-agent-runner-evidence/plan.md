# 设计文档（Feature Design Spec）：单智能体执行管道、动态交卷模型与强证据核验防幻觉引擎

<!-- #Created By AiCoding(codex) -->
<!-- SPECKIT_PLAN_LAYOUT: inline-v1 -->

> **Spec Kit 使用约定**：本模板采用**单文件内联布局（inline-v1）**，研究决策、领域与存储模型、内部接口契约及验证指南全部内联维护在本文件四个锚点章节中，不另建 `research.md`、`data-model.md`、`contracts/` 或 `quickstart.md`。仅当 `spec.md` 第 8.2 节确认涉及三类外部独立交付物时，才生成对应独立文件并在本文件建立链接。不适用章节保留标题并说明 `本需求不涉及` 及依据。

---

**分支**：`003-agent-runner-evidence` | **日期**：2026-11-16 | **规格**：`./spec.md`

**输入**：`/specs/003-agent-runner-evidence/spec.md`

## 基本信息

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-003` |
| 需求名称 | 单智能体执行管道、动态交卷模型与强证据核验防幻觉引擎 |
| 对应需求文档 | `./spec.md` |
| 对应任务清单 | `./tasks.md` |
| 设计文档版本 | 2.0 |
| 设计人 | AiCoding(codex) |
| 核算工作量 | 33.0 人天 |
| 状态 | 已交付归档 |

---

## 1. 设计目标与范围 【核心】

### 1.1 设计目标（What / Why）

- **PLAN-GOAL-1**：在 `src/report_agent/runtime/` 构建基于 Pydantic AI 单一 `Agent` 的核心执行管道，以动态编译的 `Report{suffix}` 严格交卷模型（`extra="forbid"`）和四模式适配器（`tool`/`native`/`json_object`/`prompted`）取代前代多智能体串行与 Groovy 脚本引擎，实现平台零业务硬编码。
- **PLAN-GOAL-2**：在 `@agent.output_validator` 内置确定性 `EvidenceChecker`（`quote`/`quoteWhole`/`input`/`derive`/`VALUE_TOOLS`/空列表 0 行证明/图环检测），并在耗尽 `ModelRetry` 时通过 `_salvage_partial_report` 与 `_cascade_degraded_fields` 执行字段级挽救及不动点级联降级，确保零幻觉前提下最大化报告可用率。
- **PLAN-GOAL-3**：提供不可变 `_RuntimeBundle` 热切、跨线程安全 `_DynamicLimiter` 并发门控、抗篡改 `EventSink` 过程流与基于 `DocumentIndex` 的行列偏移溯源定位，满足 `50` 行列表核验 `< 5.0 ms`、取消先落盘后重抛及 `128` 槽 LRU 缓存复用目标。

### 1.2 设计范围（Scope）

**包含：**

- `src/report_agent/runtime/` 下 8 个运行时模块：`__init__.py`、`deps.py`、`workspace.py`、`output_model.py`、`evidence.py`、`prompt.py`、`model_factory.py`、`runner.py`。
- 平台全局系统提示词 `src/report_agent/seed/system-prompt.md`。
- 离线脚本化假模型桩与 4 套运行时专项测试：`tests/scripted_model.py`、`tests/test_agent_runtime.py`、`tests/test_native_output.py`、`tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py`。

**不包含：**

- `domain/` 模板/Skill/契约解析、Jinja2 沙箱与 `runtime/render.py` 渲染上下文构建（`RA-001`）。
- 12 个工具函数实体（`runtime/tools.py`、`runtime/text_tools.py`）与外部网关客户端（`gateway/`）（`RA-004`）。
- `store/` 文件存储、Git 发布与 `RunStore` 底层写队列（`RA-002`）。
- `api/` REST/SSE 鉴权路由、`chat/` 嵌入聊天路由及 `frontend/` Vue 工作台界面（`RA-005`、`RA-006`、`RA-007`）。

<a id="plan-research"></a>

### 1.3 研究与关键决策（Decision Log）

| ID | 决策点 | 备选方案 | 最终选择 | 依据与取舍理由 | 影响范围 |
| --- | --- | --- | --- | --- | --- |
| D1 | 单智能体规划与四模式结构化交卷 | 多智能体串联编排 vs 单 `Agent.iter()` + 多模式 `Output` 适配器 | 单智能体统一会话 + `tool`/`native`/`json_object`/`prompted` 能力覆写 | 单会话保留工具检索全上下文，避免信息折损；`model_factory.py` 按 `agent_output_mode` 覆写能力位兼容不同厂商 OpenAI 服务 | `runner.py`, `model_factory.py`, `prompt.py` |
| D2 | 动态交卷 Schema 与列名冲突防护 | 固定通用字典交卷 vs 运行期 `pydantic.create_model` 动态树（行字段用 `c0..` + `alias`） | `build_report_model` 动态生成 `Report{suffix}` / `Row{suffix}_{idx}` / `FieldAnswer{suffix}_{n}` | 将模板必填键、枚举 `Literal` 与 `discriminator="type"` 证据白名单下沉为 JSON Schema；`c0, c1` 规避中文列名与 `BaseModel` 内置属性冲突 | `output_model.py` |
| D3 | 列表高频 `quote` 证据核验性能优化 | 朴素 `O(rows × evidence × cols)` 嵌套循环正则对比 vs `(resultId, row)` 去重展开 + `\x00` 拼接检索串 + 懒构建 `Decimal` 集合 | 循环外去重展开与 `\x00` 拼接集合预索引 | 消除了 50 行 × 150 条重复引用场景下的海量重复空白折叠计算，将中位耗时压至 `< 5.0 ms` 且与 `_values_equivalent` 语义完全对齐 | `evidence.py` |
| D4 | 证据失败挽救与依赖环/悬空收敛 | 校验失败整份报错 `FAILED` vs `_salvage_partial_report` + 共享 `has_supporting_real_source` 不动点级联降级 | 不动点收敛级联降级 + `_find_reachable_cycle`（含 `safe_nodes` 防自环误放行） | 绝不放行任何无实源或环依赖字段，同时保住已经校验通过的健康字段产出 `PARTIAL`；排除自引用防止掩盖下游悬空引用 | `evidence.py`, `runner.py` |
| D5 | 运行期配置热重载与并发控制 | 原生 `asyncio.Semaphore`（固定配额） vs 冻结 `_RuntimeBundle` + 自研 `_DynamicLimiter` | 不可变 `_RuntimeBundle` + 跨线程安全 `_DynamicLimiter` | 原生信号量无法从配置线程安全下调或跨线程唤醒队列；`_RuntimeBundle` 确保在途运行零撕裂，`_DynamicLimiter` 支持 `set_limit` 动态调额并清理失效 `Future` | `runner.py` |

---

### 1.4 技术背景与项目结构

**语言/版本**：Python 3.13（`pyproject.toml` 声明兼容 `>=3.12,<3.14`），全异步 `asyncio` 协程模型。

**主要依赖**：`pydantic-ai-slim[openai]==2.67.0`（`Agent`、`ToolOutput`、`NativeOutput`、`PromptedOutput`、`ModelRetry`、`UsageLimits`）、`pydantic>=2.12,<3`、`openai`（`AsyncOpenAI`）、标准库 `asyncio` / `collections.OrderedDict` / `decimal.Decimal` / `bisect` / `re` / `dataclasses`。

**存储**：运行中间态存于内存 `Workspace` 与 `AgentRunner._agent_cache`（128 槽 LRU）；通过 `ReleaseStore`/`ResourceService` 只读捕获快照并向 `RunStore` 提交异步落盘，本模块不直接写盘。

**测试**：`pytest>=8.3,<9`、`pytest-asyncio>=0.24,<2`、`httpx.MockTransport`、Pydantic AI `FunctionModel` / `TestModel` 与脚本桩 `tests/scripted_model.py`；静态检查 `uvx ruff@0.11.0 check src tests`。

**目标平台**：Linux / macOS 服务端容器（严格单进程 Uvicorn `workers=1`）。

**项目类型**：单仓库后端核心运行时模块（`src/report_agent/runtime/` 与 `src/report_agent/seed/system-prompt.md`）。

**约束与规模/范围**：严格禁止业务硬编码；交卷 Schema 全树启用 `extra="forbid"`；默认并发 `agent_max_concurrent_runs=8`、轮次上限 `25`、工具上限 `120`、总超时 `600s`、重试上限 `3`；覆盖 `8` 个源码文件（共 `2,260` 行）、`1` 份全局提示词（`23` 行）与 `5` 份测试/桩文件（`2,254` 行），合计 `33.0` 人天。

**源代码结构（真实目录落点）**：

```text
src/report_agent/
├── runtime/
│   ├── __init__.py          # runtime 包标识（1 行）
│   ├── deps.py              # RunDeps 运行期不可变快照与依赖注入上下文（31 行）
│   ├── workspace.py         # Workspace、ApiResult、ToolCall、ProcessEvent、EventSink、queue_listener（156 行）
│   ├── output_model.py      # build_report_model / Row{suffix}_{idx} / 证据联合体 / report_to_dict（178 行）
│   ├── evidence.py          # EvidenceChecker、DocumentIndex、VALUE_TOOLS、图环与不动点支撑判定（896 行）
│   ├── prompt.py            # build_task_instructions、EVIDENCE_RULES 与 Java 对照注释剥离（113 行）
│   ├── model_factory.py     # build_model（4 模式 profile 覆写）与 build_model_settings（54 行）
│   └── runner.py            # AgentRunner、_RuntimeBundle、_DynamicLimiter、降级挽救与状态渲染输出（831 行）
└── seed/
    └── system-prompt.md     # 平台全局系统提示词（23 行）

tests/
├── scripted_model.py            # 脚本化 FunctionModel 桩（104 行）
├── test_agent_runtime.py        # 交卷模型、证据校验、重试降级与 DocumentIndex 定位测试（323 行）
├── test_native_output.py        # tool/native/json_object/prompted 四模式及代码块挽救测试（137 行）
├── test_review_runtime.py       # 自引用环、标量容器防御、限流器、取消保留等加固测试（889 行）
└── test_review_fixes_runtime.py # 热缓存、提示词清理、50 行列表性能基准与级联降级端到端测试（801 行）
```

**禁止修改范围**：

- `src/report_agent/domain/` 与 `src/report_agent/store/` 既有领域契约与存储结构（本子规格仅只读调用，不修改其接口语义）。
- `src/report_agent/runtime/tools.py`、`text_tools.py` 与 `src/report_agent/gateway/`（归属 `RA-004`）。
- `tests/conftest.py` 的全局 `SEED_DIR` 隔离机制及 `frontend/` 前端工程目录。

#### 文档结构（本需求）

```text
specs/003-agent-runner-evidence/
├── spec.md    # 需求规格、范围边界、4 个用户故事、FR-001~FR-010 与验收标准
├── plan.md    # 单文件内联设计：研究决策、领域契约、流程与验证指南（inline-v1）
└── tasks.md   # 18 项任务清单（33.0 人天）、实测证据与追踪验收台账
```

| 设计产物 | 权威位置 |
| --- | --- |
| 研究结论与技术决策 | [1.3 研究与关键决策](#plan-research) |
| 领域实体与存储设计 | [第 3–4 章](#plan-data-model) |
| 内部接口与事件契约 | [第 5 章](#plan-contracts) |
| 可执行验证指南 | [10.5 验证指南](#plan-quickstart) |

### 1.5 宪章检查

| 质量门 | 研究前 | 设计后 | 核查证据 |
| --- | --- | --- | --- |
| 原则 I：平台零业务硬编码与声明式资源隔离 | PASS | PASS | 交卷 Schema、提示词、证据规则全由 `Template` 元数据与 `ResourceSet` 驱动，代码不含具体业务编号/关键词分支 |
| 原则 II：单智能体规划、确定性原语与强证据防幻觉 | PASS | PASS | 单 `AgentRunner` + `EvidenceChecker`（`quote`/`quoteWhole`/`input`/`derive`/`VALUE_TOOLS`/空表 0 行证明/图环与不动点降级）+ `field_render`/`render_body` 闭环 |
| 原则 III：文件化 Git 原子发布与单进程并发安全（`workers=1`） | PASS | PASS | 入口锁定不可变快照 `rev`，`(rev, tpl.id, bundle.seq)` 缓存与 `_DynamicLimiter` 适配单进程并发 |
| 原则 IV–V：单文件内联设计、自动化测试隔离与 Mock 契约 | PASS | PASS | 采用 `inline-v1` 单文件布局；测试通过 `ScriptedModel`/`FunctionModel`/`MockTransport` 隔离运行 |
| 原则 VI–VII：安全脱敏、零硬编码凭证、事件与审计留痕 | PASS | PASS | `llm_api_key` 使用 `SecretStr`；`EventSink` 防止键覆盖且运行取消与异常均先完整写入 `RunStore` |
| 原则 VIII–X：最小改动、代码规范、Wiki 同步及三类外部交付物确认 | PASS | PASS | `ruff` 零警告、`pytest` 全通过；`wiki/` 已于历史交付同步且三类外部交付物确认不涉及 |

### 1.6 复杂度跟踪

| 偏离或额外复杂度 | 必要性说明 | 未采用更简方案的原因 |
| --- | --- | --- |
| 自研 `_DynamicLimiter` 替代标准 `asyncio.Semaphore` | 管理端运行期需支持动态调整 `agent_max_concurrent_runs`，且调用方可能从配置线程跨线程下调或上调限额 | 原生 `asyncio.Semaphore` 修改内部计数无法跨线程安全唤醒排队协程，且下调上限会引起并发错乱或死锁 |
| 列表 `quote` 证据核验预计算 `\x00` 拼接检索串与懒构建 `Decimal` 集合 | 典型长表（50 行 × 4 列 × 150 条引用）若按行/列嵌套扫描会引发反复全串归一化 CPU 尖峰 | 朴素三层循环随行数 × 证据数平方级增长，实测预索引方案稳定 `< 5.0 ms` 且与 `_values_equivalent` 语义 100% 一致 |

### 1.7 Wiki 影响评估

- **结论**：涉及（历史交付已按规范同步对齐；本次仅将既有规格升级改造为标准 SDD 三件套，不修改代码与契约，无需新建或修改 `wiki/` 页面）。
- **受影响页面**：
  - `wiki/architecture/request-pipeline.md`（单智能体请求全链路管道）
  - `wiki/architecture/evidence-system.md`（强证据核验与防幻觉规则）
  - `wiki/components/agent-runner.md`（`runner.py`/`output_model.py`/`prompt.py`/`workspace.py` 组件剖析）
  - `wiki/decisions/adr-001-single-agent-and-evidence.md`（单智能体与强证据架构决策）
- **同步项**：已确认上述 `wiki/` 权威页面、`wiki/index.md` 与 `wiki/log.md` 均已就位并符合 `wiki/SCHEMA.md`（不按单次需求编号在 `wiki/` 新建碎片页）。

### 1.8 三类独立交付物设计检查

| 独立交付物 | 涉及情况与依据 | 设计与变更摘要 | 验证与回退设计 | 关联问题 |
| --- | --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 不新增对外 HTTP/SSE/`postMessage` 接口 | 沿用内部 `AgentRunner` Python 调用契约，无外部接口回归项 | 无 |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 仅维护 1 份通用平台 `system-prompt.md`，非模板/Skill 迁移需求 | 通过 `validate_all`（`SYSTEM_PROMPT_EMPTY` 门禁）验证系统提示词非空 | 无 |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 沿用 `Settings` 既有环境变量及运行时热配置项，无容器拓扑变化 | 启动前配置按 `Settings` 默认兜底与热重载单测验证 | 无 |

---

## 2. 需求映射（Traceability） 【核心】

| 规格编号 | 类型 | 需求摘要 | 设计章节映射 | 后续任务映射 |
| --- | --- | --- | --- | --- |
| `US1` / `SC-003` | 用户故事/标准 | 单智能体编排、四模式交卷、`Report{id}` Schema 与 128 槽模型缓存 | 第 3、5、6 章 | `T006`, `T007`, `T008` |
| `US2` / `SC-001`, `SC-002` | 用户故事/标准 | `EvidenceChecker`、`DocumentIndex`、列表高速去重核验与空表 0 行证明 | 第 3、5、6 章 | `T009`, `T010`, `T011` |
| `US3` / `SC-001` | 用户故事/标准 | `ModelRetry` 打回重填、候选挽救、图环检测与不动点级联降级 | 第 3、6 章 | `T012`, `T013`, `T014` |
| `US4` / `SC-004`, `SC-005` | 用户故事/标准 | `_RuntimeBundle` 热切、`_DynamicLimiter` 控流、`EventSink` 与溯源输出 | 第 4、5、6、9 章 | `T015`, `T016` |
| `FR-001` | 功能需求 | 快照捕获、模板状态核验、入参裁剪与防 ReDoS 校验 | 第 5、6.1 节 | `T003`, `T007` |
| `FR-002` | 功能需求 | 动态构造严格交卷模型 `Report{suffix}` 与列表 `Row{suffix}_{idx}` | 第 3.1 节 | `T006`, `T008` |
| `FR-003` | 功能需求 | `build_model` 四模式能力覆写与 128 槽 `(rev, tpl.id, bundle.seq)` LRU | 第 4.1, 5.1 节 | `T005`, `T007`, `T008` |
| `FR-004` | 功能需求 | 白名单提示词组装与 `原规则（Java）：` 剥离 | 第 5.1 节 | `T001`, `T007`, `T017` |
| `FR-005` | 功能需求 | `EvidenceChecker` 标量/列表/空列表核验与 `DocumentIndex` 定位 | 第 3.1, 6.1 节 | `T009`, `T010`, `T011` |
| `FR-006` | 功能需求 | 可达环探测 `_find_reachable_cycle` 与共享实源不动点计算 | 第 3.1, 6.2 节 | `T012`, `T014` |
| `FR-007` | 功能需求 | `ModelRetry` 打回、`_salvage_partial_report` 与 `_cascade_degraded_fields` | 第 3.2, 6.2 节 | `T013`, `T014` |
| `FR-008` | 功能需求 | `_RuntimeBundle` 热切与跨线程 `_DynamicLimiter` 并发治理 | 第 3.1, 6.2, 9 章 | `T015`, `T016` |
| `FR-009` | 功能需求 | `EventSink`/`queue_listener` 轨迹流与超时/取消先写盘后透传 | 第 5.1, 6.2 节 | `T004`, `T016`, `T018` |
| `FR-010` | 功能需求 | `field_render`/`render_body`、三态判定、`not_found` 清空证据与 `evidenceTarget` | 第 6.1, 8 章 | `T015`, `T016` |
| `NFR-001`~`NFR-006` | 非功能需求 | 零硬编码、单进程安全、`< 5.0 ms` 列表性能、防泄露与可观测 | 第 1.5, 10, 11 章 | `T011`, `T016`, `T017`, `T018` |
| `EX-001`~`EX-006` | 异常边界 | 自引用环、容器误填、取消/超时、跨线程循环关闭、零字段模板与缺字段挽救 | 第 6.2, 10.1 节 | `T011`, `T014`, `T016`, `T017` |

---

<a id="plan-data-model"></a>

## 3. 核心领域模型（Domain Model） 【核心】

### 3.1 领域对象清单

| 对象 / 类 | 所在文件 | 职责与核心属性 | 关键不变量（Invariant） |
| --- | --- | --- | --- |
| `RunRequest` | `src/report_agent/runtime/runner.py` | 上游请求描述符：`template_id`, `inputs`, `document`, `entry`, `target`, `operator`, `extra`, `run_id` | `target` 限 `"online"` / `"draft"`；支持调用方预分配 `run_id` |
| `RunDeps` | `src/report_agent/runtime/deps.py` | 单次运行不可变依赖快照：`run_id`, `rev`, `resources`, `template`, `inputs`, `document`, `allowed_skills`, `allowed_apis`, `workspace`, `events`, `gateway`, `settings` | 入口捕获锁定，整次多轮模型/工具交互中只读不变 |
| `Workspace` / `ApiResult` / `ToolCall` / `ProcessEvent` | `src/report_agent/runtime/workspace.py` | 运行期内存工作区及过程载体：`results`（`rN`）、`tool_calls`（`tN`）、`loaded_skills`、`validation_rounds`、`_doc_index`、`EventSink` | `ProcessEvent.to_dict()` 结构字段 `seq`/`type`/`atMs`/`round` 不可被载荷覆盖 |
| `Report{suffix}` / `Row{suffix}_{idx}` / `FieldAnswer{suffix}_{n}` | `src/report_agent/runtime/output_model.py` | 动态生成 Pydantic 交卷模型树与 `ApiEvidence`/`DocumentEvidence`/`ToolEvidence`/`InputEvidence{suffix}`/`FieldEvidence{suffix}` | 全部模型 `extra="forbid"`；`ApiEvidence.row` 禁止布尔；标量仅受文本/枚举约束 |
| `EvidenceChecker` / `DocumentIndex` / `FieldIssue` | `src/report_agent/runtime/evidence.py` | 确定性证据校检器、单据惰性索引与问题载体 `{field, message}` | `VALUE_TOOLS = {"format_date"}`；`DocumentIndex._locate_cache` 上限 `512` 项；共享 `has_supporting_real_source` |
| `_RuntimeBundle` / `_DynamicLimiter` | `src/report_agent/runtime/runner.py` | 冻结配置快照（含递增 `seq`）与动态并发门控器（`_limit`, `_inflight`, `_waiters`, `_loop`） | 单次运行持固定 `_RuntimeBundle` 不撕裂；`_DynamicLimiter` 下调不超发，升额支持跨线程安全唤醒 |

### 3.2 状态机（如适用）

```text
[入参校验] --(不合法/模板下线)--> [TemplateUnavailable / InputValidationError (零 Token 阻断)]
    │ (合法)
    ▼
[RUNNING (agent.iter 循环)] --(交卷校验通过)--> [report_accepted] --> [_finish 渲染]
    │                                                                      │
    ├─(issues & retry < max_retries)--> [report_rejected + ModelRetry]     ├─(error or render_error)--> FAILED
    ├─(retry 耗尽且无异常)--> [report_degraded + 级联降级] --> [_finish]    ├─(missingShown 非空)------> PARTIAL
    ├─(UnexpectedModelBehavior & 有候选)--> [_salvage_partial_report] ----┘ (否则)--------------------> SUCCESS
    └─(超时 / 超限 / ModelAPIError / CancelledError)--> [run_failed] --> [_finish (FAILED)] --> (异步写 RunStore; 取消则重抛)
```

---

## 4. 数据与存储设计（本需求范围） 【核心】

> 本子规格运行中仅管理内存结构，只读消费 `ReleaseStore`/`ResourceService`，通过 `RunStore.submit` 异步委托 `RA-002` 完成运行记录写盘。

### 4.1 存储与缓存对象概览

| 对象/路径 | 变更类型 | 数据格式与字段要点 | 并发/清理/恢复策略 | 关联需求 |
| --- | --- | --- | --- | --- |
| `AgentRunner._agent_cache`（内存） | 新增 | `OrderedDict[(rev, tpl.id, bundle.seq) -> (report_model, agent)]` | 仅 `target="online"` 写入；最大 `128` 槽 LRU 淘汰；`reload_config` 递增 `bundle.seq` 自然隔离 | `FR-003`, `FR-008` |
| `Workspace._doc_index`（内存） | 新增 | `DocumentIndex`（惰性缓存 `lines`、`line_starts`、`_norm_doc`、`_doc_map`、`_locate_cache`） | 单次运行绑定 `document` 原文复用，`_locate_cache` 上限 `512` 项，随运行结束释放 | `FR-005`, `FR-010` |
| `DATA_DIR/runs/YYYY/MM/DD/`（委托写） | 只写调用 | `RunSummary`（`index.jsonl`）与完整详单 `<runId>.json` | 通过 `self.runs.submit(summary, detail)` 送入单协程异步队列落盘 | `FR-009`, `FR-010` |

---

<a id="plan-contracts"></a>

## 5. 接口与契约设计（API / Tools / Events） 【核心】

### 5.1 接口与契约清单

| 契约编号 | 类型 | 名称 / Path | 方向 | 关键入参 / 载荷 | 关键出参 / 响应 / 事件 | 鉴权与幂等 | 关联需求 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `API-1` | 内部 Python API | `AgentRunner.run(req, listener)` | 调用方 → `runner.py` | `RunRequest`, `Callable[[ProcessEvent], None]` | 运行结果字典 `{runId, status, report, fields, missingShown, events, usage, ...}` | 依赖上层鉴权；支持外部预传 `run_id` | `FR-001`, `FR-009`, `FR-010` |
| `API-2` | 内部 Python API | `AgentRunner.reload_config(settings, rebuild_model=True)` | 配置管理 → `runner.py` | 新 `Settings` 快照、`rebuild_model` 标志 | 原子替换 `_RuntimeBundle` 并执行 `_sem.set_limit` | 单进程安全替换；不中断在途任务 | `FR-008` |
| `API-3` | 内部校验契约 | `EvidenceChecker.check(report)` | `runner.py` → `evidence.py` | 交卷字典 `{字段名: {status, value, evidence, reasoning}}` | `list[FieldIssue]`（`{field, message}`） | 纯确定性无副作用校验 | `FR-005`, `FR-006` |
| `EVT-1` | 过程事件流（SSE 基础） | `EventSink.emit` / `queue_listener` | `Workspace` → `routes_*` / `chat/` | 事件类型与业务数据字典 | 规范事件 `run_started`, `model_request`, `model_text`, `tool`, `report_rejected`, `report_accepted`, `report_degraded`, `run_failed` | 强保底保护 `seq`/`type`/`atMs`/`round`；跨线程安全 | `FR-009` |
| `LLM-1` | 出站 HTTP JSON | `build_model` / `OpenAIChatModel` | `model_factory.py` → `{LLM_BASE_URL}` | `instructions`, `tools`, `response_format`（4 模式适配）, `messages` | 工具调用列表或结构化 JSON / 文本 | Bearer `llm_api_key`（`SecretStr`）；按 `llm_http_retries` 重试 | `FR-003` |

### 5.2 关键契约说明与错误语义

- **前置拦截错误**：模板不存在或 `online` 已下线抛出 `TemplateUnavailable`（上层路由通常映射 HTTP `404`/`409`）；入参缺失或正则不匹配抛出 `InputValidationError`（包含逐字段中文错误列表，上层映射 `400`/`422`）。
- **四输出模式行为差异**：
  - `tool`：注入 `submit_report` 工具定义由模型通过工具调用交卷；
  - `native`：发送 `NativeOutput(report_model, name="submit_report", strict=settings.agent_native_strict)`，不向模型暴露 `submit_report` 工具，且在 strict 模式规避 `oneOf`；
  - `json_object`：覆写模型能力仅保留 `supports_json_object_output=True`，通过 `PromptedOutput` 把 JSON Schema 写进系统提示并请求 `response_format={"type": "json_object"}`；
  - `prompted`：关闭所有 `response_format` 支持标记，仅凭指令与 Markdown 代码块容错解析（`_extract_json_dict`）交卷。
- **过程事件防覆写与容错**：`ProcessEvent.to_dict()` 先展开 `data` 再覆写 `seq`/`type`/`atMs`/`round`；`queue_listener` 在循环关闭或跨线程投递异常时兜底捕获并安全入队，禁止事件推送异常中断报告生成。

---

## 6. 业务流程设计（可直接编码） 【核心】

### 6.1 核心执行流程

```text
1. 【快照锁定与前置校验】生成/读取 run_id → 捕获 rev 与只读 ResourceSet → 检查模板存在与在线状态 → .strip() 清洗 inputs 并调用 validate_inputs（含 safe_regex_fullmatch）。
2. 【运行时装配与缓存命中】提取当前 _RuntimeBundle 局部快照 → 构建 RunDeps 与 EventSink → 发射 run_started → online 模式查 128 槽 LRU _agent_cache 或调用 build_report_model + _build_agent。
3. 【限流与单智能体循环】进入 _DynamicLimiter 门控与 asyncio.timeout → 启动 agent.iter(USER_PROMPT, deps, UsageLimits) → 逐轮发射 model_request / model_text，工具经 build_tools 执行并入 Workspace。
4. 【强证据出口核验与打回/降级】@agent.output_validator 调用 EvidenceChecker.check() → 有问题且未超限则发射 report_rejected 并抛 ModelRetry → 超限或 UnexpectedModelBehavior 则执行部分挽救与沿依赖图不动点级联降级（report_degraded）。
5. 【渲染、状态判定与异步落盘】_finish 统一调用 field_render 与 render_body → 清空 not_found 证据 → 计算 missingShown 与 SUCCESS/PARTIAL/FAILED → DocumentIndex 生成 evidenceTarget → runs.submit 异步写盘 → 若为 CancelledError 原样重抛。
```

### 6.2 并发控制与异常降级策略

| 异常/并发场景 | 检测时机 | 处理策略 | 是否中断主流程 | 可观测性输出 |
| --- | --- | --- | --- | --- |
| 校验违例且未达重试上限 | `@agent.output_validator` | 写入 `validation_rounds`，抛 `ModelRetry(format_issues(issues))` 引导仅修问题字段 | 否（继续重试轮次） | 发射 `report_rejected`（含字段问题列表） |
| 重试耗尽或 `UnexpectedModelBehavior` | 校验出口或 `iter` 异常捕获 | 调用 `_extract_candidate_report` + `_salvage_partial_report` + `_cascade_degraded_fields`，仅合法字段保留 `found` | 否（降级进入 `_finish`，通常为 `PARTIAL`） | 发射 `report_degraded`（含降级字段集合） |
| 环依赖 / 自引用 / 悬空 `not_found` | `EvidenceChecker.check` 或 `_cascade_degraded_fields` | 剔除自引用禁入 `safe_nodes`，不动点迭代检查 `has_supporting_real_source` 同步降级受波及下游字段 | 否（受影响字段强制 `not_found`） | 记入 `FieldIssue` 与 `validationRounds` |
| 热切降额/升额并发门控 | `reload_config` / `__aenter__` | `_DynamicLimiter` 下调允许在途自然完成、新来等待；升额跨线程 `call_soon_threadsafe` 唤醒；排队取消归还名额 | 否（排队或隔离平滑切换） | 在途维持旧 `_RuntimeBundle`，并发度受控 |
| 超时 / 超限 / 模型异常 / `CancelledError` | `AgentRunner.run` 外层 `try/except` | 记录 `error`（取消记 `"运行已取消"`）、提取 `usage`/`messages`、经 `_finish` 和 `RunStore` 落盘后再视情况重抛取消异常 | 是（结果标记 `FAILED`） | 发射 `run_failed` 与写入 `RunStore` |

---

## 7. 权限与安全控制（本需求范围） 【补充】

> 本需求处于平台内部运行时层，沿用上层路由鉴权与全局密钥保护约束。

| 控制点 | 适用角色/调用方 | 校验机制与边界 |
| --- | --- | --- |
| 白名单工具与提示词隔离 | 单智能体（大模型） | `RunDeps.allowed_skills` / `allowed_apis` 仅从模板与 `ResourceSet` 交集计算，`prompt.py` 仅暴露白名单内摘要 |
| 大模型凭证保护 | `model_factory.py` | `Settings.llm_api_key` 使用 `SecretStr`，为空回退 `"EMPTY"`，不进入 `RunDeps` 摘要、日志或 `events` |
| 交卷契约与载荷保护 | `output_model.py`, `workspace.py` | 全树启用 `extra="forbid"`；`ApiEvidence.row` 禁止布尔；`ProcessEvent.to_dict()` 拒绝业务键覆写系统序号与事件类型 |

---

## 8. 前端 / 交互设计（如适用） 【补充】

> 本需求不涉及前端页面或交互变更；仅向工作台与嵌入式窗口输出标准 `fields[].evidenceLabel`、`fields[].evidenceTarget`（含 `tab`/`resultId`/`row`/`column`/`line`/`endLine`/`offset`/`endOffset`/`matches`）与 `ProcessEvent` 实时事件流，前端展示渲染归属 `RA-006` 与 `RA-007`。

---

## 9. 配置与热更新开关 【补充】

| 配置项（Env / RuntimeConfig） | 类型 | 默认值 | 是否支持热更新 | 说明 |
| --- | --- | --- | --- | --- |
| `llm_base_url` / `llm_model` / `llm_api_key` | `str` / `SecretStr` | `"https://api.openai.com/v1"` / `"deepseek-v4-flash"` | 是 | `reload_config(rebuild_model=True)` 重建模型与热切 `_RuntimeBundle` |
| `llm_temperature` / `llm_max_tokens` / `llm_timeout_s` / `llm_http_retries` | `float` / `int` | `0.0` / `None` / `120.0` / `2` | 是 | 控制模型采样、最大输出与 HTTP 层自动重试 |
| `llm_parallel_tool_calls` / `llm_strict_tools` / `llm_tool_choice_required` | `bool \| None` | `True` / `None` / `None` | 是 | 覆写厂商对并行工具、strict Schema 与强制工具调用的兼容声明 |
| `agent_output_mode` / `agent_native_strict` | `Literal` / `bool` | `"tool"` / `True` | 是 | 切换 `tool` / `native` / `json_object` / `prompted` 四种结构化交卷模式 |
| `agent_output_retries` / `agent_tool_retries` | `int` | `3` / `2` | 是 | 控制证据打回上限与工具参数自纠上限（后者驱动刷新 `_RuntimeBundle.tools`） |
| `agent_request_limit` / `agent_tool_calls_limit` / `agent_run_timeout_s` | `int` / `float` | `25` / `120` / `600.0` | 是 | 控制单次运行轮次、工具次数与总超时 |
| `agent_max_concurrent_runs` | `int` | `8` | 是 | 控制进程内并发数，热切时由 `_DynamicLimiter.set_limit` 实时调整 |

---

## 10. 测试设计（Test Strategy） 【核心】

### 10.1 测试范围与分层策略

| 测试类型 | 覆盖范围 | 桩/隔离策略 | 重点验证场景 |
| --- | --- | --- | --- |
| 单元测试 | `output_model`, `evidence`, `prompt`, `model_factory`, `_DynamicLimiter`, `EventSink` | 内存 `Workspace`、`Template` 构造、独立时间测量 | 四类证据核验、空列表 0 行证明、自环与环外节点、容器防御、50 行列表 `< 5.0 ms`、`DocumentIndex` 偏移与多匹配、`queue_listener` 跨/闭循环 |
| 集成/回归测试 | `AgentRunner.run` 全链路、四模式 HTTP 报文、热更新与并发取消 | `tests/scripted_model.py`、`httpx.MockTransport`、临时 `DATA_DIR`（受 `conftest.py` 隔离） | `tool`/`native`/`json_object`/`prompted` 端到端闭环、重试打回自纠、缺字段部分挽救、级联降级、`CancelledError` 落盘重抛 |

### 10.2 回归范围

- 运行时与领域交叉回归：`tests/test_agent_runtime.py`、`tests/test_native_output.py`、`tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py`、`tests/test_runtime_config_hot_reload.py`。
- 全仓库无外网集成套件与静态检查：`uv run pytest -q` 与 `uvx ruff@0.11.0 check src tests`。

<a id="plan-quickstart"></a>

### 10.5 验证指南

- **环境与前置条件**：macOS / Linux，Python 3.13 + `uv` 已就绪（`uv sync --extra dev`），全过程无需真实外网大模型或内网网关。
- **验证命令**：
  ```bash
  # 运行全量测试套件（含全部 runtime 专项测试）
  uv run pytest -q

  # 单独按需聚焦运行时核心文件回归（快速自检）
  uv run pytest tests/test_agent_runtime.py tests/test_native_output.py tests/test_review_runtime.py tests/test_review_fixes_runtime.py -q

  # Python 静态代码规范检查
  uvx ruff@0.11.0 check src tests
  ```
- **预期结果**：全量测试 `uv run pytest -q` 输出 `196 passed in 51.41s`，`uvx ruff@0.11.0 check src tests` 输出 `All checks passed!`（0 error / 0 warning）。

---

## 11. NFR 符合性自检 【核心】

| 自检主题 | 宪章依据 | 是否涉及 | 落实位置与验证方式 |
| --- | --- | --- | --- |
| 零业务硬编码与资源隔离 | I | 是 | `runtime/` 8 模块与 `system-prompt.md` 不包含任何特定模板/套餐规则，经人工审阅与通用模板单测验证 |
| 强证据防幻觉与确定性计算 | II | 是 | `output_model.py` + `evidence.py` + `runner.py` 构成闭环防线，经 `test_agent_runtime.py` 等 4 套测试全面验证 |
| 文件化存储与 `workers=1` 并发安全 | III | 是 | 入口快照锁定、`128` 槽 LRU 缓存与 `_DynamicLimiter` 按单进程异步模型设计并经并发测试验证 |
| 安全编码、脱敏与零凭据硬编码 | VI | 是 | `SecretStr` 承载 `llm_api_key`、`safe_regex_fullmatch` 入参正则防 ReDoS、`tests/` 全部使用假模型与脱敏样例 |
| 过程事件、阶段日志与审计留痕 | VII | 是 | `EventSink` 全过程记录、取消先落盘 `RunStore` 后重抛并记录 `validationRounds` 与 `usage` |

---

## 12. 发布与回退计划 【核心】

- **发布前置与步骤**：执行 `uv run pytest -q` 与 `uvx ruff@0.11.0 check src tests` 全量通过 → 确认 `uvicorn` 启动参数保持单进程 `workers=1` → 部署新镜像并检查健康接口 `/healthz`；若仅需切换 `system-prompt.md` 或模型参数，优先使用工作台在线发布或配置热更新无需重启。
- **回退方案**：`system-prompt.md` 可通过内部 Git 发布历史切换 `releases/current` 软链接秒级回滚；热更新模型参数可通过配置版本 `cN` 回滚并调用 `reload_config` 生效；运行时源码升级缺陷通过容器镜像版本回退。

---

## 13. 实施切片与建议顺序（Implementation Slices） 【核心】

| 切片 ID | 切片名称 | 对应 Phase / 任务范围 | 目标与涉及文件 | 核算工时 |
| --- | --- | --- | --- | --- |
| `S-01` | 运行时包骨架、全局系统提示词与脚本化测试底座 | Phase 1 (`T001`–`T002`) | `src/report_agent/runtime/__init__.py`、`src/report_agent/seed/system-prompt.md`、`tests/scripted_model.py` | 3.0 人天 |
| `S-02` | 运行期核心底座（依赖上下文、工作区事件管道与四模式模型工厂） | Phase 2 (`T003`–`T005`) | `src/report_agent/runtime/{deps.py,workspace.py,model_factory.py}` | 6.0 人天 |
| `S-03` | 动态交卷 Schema、白名单提示词与单智能体四模式编排缓存 | Phase 3 (`T006`–`T008`) | `src/report_agent/runtime/{output_model.py,prompt.py,runner.py}`、`tests/{test_agent_runtime.py,test_native_output.py}` | 6.5 人天 |
| `S-04` | `DocumentIndex` 定位、强证据核验与列表 0 行/高速索引防线 | Phase 4 (`T009`–`T011`) | `src/report_agent/runtime/evidence.py`、`tests/{test_agent_runtime.py,test_review_fixes_runtime.py}` | 6.0 人天 |
| `S-05` | 打回重试自纠、部分挽救、可达环检测与不动点级联降级 | Phase 5 (`T012`–`T014`) | `src/report_agent/runtime/{evidence.py,runner.py}`、`tests/{test_review_runtime.py,test_review_fixes_runtime.py}` | 5.5 人天 |
| `S-06` | `_RuntimeBundle` 热切、`_DynamicLimiter` 并发控流与状态/溯源输出 | Phase 6 (`T015`–`T016`) | `src/report_agent/runtime/runner.py`、`tests/{test_review_runtime.py,test_review_fixes_runtime.py}` | 3.5 人天 |
| `S-07` | 边界容错巩固、全量回归验证与静态检查收口 | Phase 7 (`T017`–`T018`) | 全面审查回归与 `pytest` / `ruff` 验收闭环 | 2.5 人天 |
| **合计** | **全 7 个切片、18 项任务** | **`T001`–`T018`** | **完整运行时编排与防幻觉子系统** | **33.0 人天** |

---

## 14. 风险清单与缓解（Risks） 【补充】

| 风险 ID | 风险描述 | 影响 | 概率 | 缓解措施 |
| --- | --- | --- | --- | --- |
| `R-1` | 不同第三方 OpenAI 兼容网关对 `json_schema` `strict` 或 `tool_choice` 支持差异导致交卷解析失败 | 高 | 中 | 在 `model_factory.py` 提供 `tool`/`native`/`json_object`/`prompted` 4 种输出模式与能力覆写开关，并配合 `_extract_json_dict` 与 `_salvage_partial_report` 兜底 |
| `R-2` | 高并发下配置热重载时若旧任务与新配置交叉或限流计数错位可能引发竞态撕裂或死锁 | 高 | 低 | `_RuntimeBundle` 全字段冻结并在 `run` 入口局部锁定；`_DynamicLimiter` 由 `set_limit` 跨线程安全投递 `_wake_waiters` 并清理关闭循环的 `Future` |
| `R-3` | 复杂嵌套列表模板核验耗时过高拖慢输出校验环 | 中 | 低 | 按 `(resultId, row)` 去重展开并预构建集合与 `\x00` 拼接串，确保 50 行 × 150 条引用中位 `< 5.0 ms` |

---

## 15. 待确认事项（Design Open Questions） 【补充】

> 设计阶段关键技术取舍已全部闭环并通过自动化测试验收，当前无未关闭 `DQ-*`。

| 编号 | 问题摘要 | 对应 Spec `Q-*` | 当前结论 | 状态 |
| --- | --- | --- | --- | --- |
| `DQ-1` | 跨不同模型网关的 `output_mode` 降级与列表 0 行 `PARTIAL` 判定口径 | `Q-001` | 四模式运行期可热配切换；列表 `status="found", value=[]`（附 0 行证据）在正文循环渲染下判定为 `SUCCESS` | 已关闭 |

---

## 附录 A：核心字段与状态约定（仅本需求）

- **结构化输出模式枚举（`agent_output_mode`）**：`"tool"` | `"native"` | `"json_object"` | `"prompted"`
- **运行终态（`status`）**：`"SUCCESS"` | `"PARTIAL"` | `"FAILED"`
- **过程事件类型（`ProcessEvent.type`）**：`"run_started"` | `"model_request"` | `"model_text"` | `"tool"` | `"report_rejected"` | `"report_accepted"` | `"report_degraded"` | `"run_failed"`
- **受限工具值核对白名单（`VALUE_TOOLS`）**：`{"format_date"}`
- **关键内置容量上限**：`_MAX_AGENT_CACHE = 128`、`DocumentIndex._locate_cache` 上限 `512`、`model_text` 截取 `2000` 字

## 附录 B：AI 编码与交付约束

1. 先阅读 `spec.md`、本 `plan.md` 与 `tasks.md`，按 `T001`–`T018` 顺序实施，不实现 Out of Scope 内容。
2. 所有已勾选完成 `[X]` 的任务必须附有真实命令验证输出，严禁“仅写完未验证即标完成”。

---

## 变更记录（Changelog）

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | AiCoding(codex) | 依据 `report-agent` 运行时源码完成初版架构设计归档 |
| 2.0 | 2026-11-16 | AiCoding(codex) | 升级为 `inline-v1` 单文件内联设计布局，补齐四锚点、宪章门禁、Wiki 评估与全量可追溯映射 |
