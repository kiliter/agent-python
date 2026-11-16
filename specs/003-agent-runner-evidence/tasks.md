---
description: "单智能体执行管道、动态交卷模型与强证据核验防幻觉引擎（RA-003）标准 SDD 任务清单"
---

# 任务说明（Implementation Tasks）：单智能体执行管道、动态交卷模型与强证据核验防幻觉引擎

<!-- #Created By AiCoding(codex) -->

> **Spec Kit 使用约定**：本文件承接 `spec.md` 与 `plan.md`（`inline-v1` 单文件内联布局），将设计切片转化为顺序清晰、带精确文件路径、可独立验证的 18 项任务清单（合计 `33.0 人天`）。所有 18 项任务均已依托本轮实测通过的 `uv run pytest -q`（`196 passed in 51.41s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）完成归档验收。

---

## 基本信息

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-003` |
| 需求名称 | 单智能体执行管道、动态交卷模型与强证据核验防幻觉引擎 |
| 对应需求文档 | `./spec.md` |
| 对应设计文档 | `./plan.md` |
| tasks 版本 | 2.0 |
| 核算工作量 | 33.0 人天 |
| 状态 | 已完成（归档验收） |
| 负责人 | AiCoding(codex) |

---

## 0. 使用方式（给 AI 的执行指令） 【核心】

1. 按第 3 章权威任务清单顺序推进；标记 `[P]` 的任务可与同组无冲突任务并行，但不得越过前置阻塞依赖。
2. 权威复选框仅存在于第 3 章，每条以 `- [X]`（或待执行时 `- [ ]`）加 `Txxx` 编号、可选 `[P]`、故事阶段必填 `[USx]` 及全角工时括号结尾；其他章节仅引用 `T*` 编号，不重复建复选框。
3. 第 3.5 节记录各任务组实际变更文件、核心符号及真实执行的验证命令与通过输出；无实测或构建证据不得勾选完成。
4. 若后续迭代遇需求歧义或现状冲突，停止扩大实现并登记于第 9 节 `BQ-*`，回链 `spec.md` `Q-*`。

---

## 1. 需求到任务映射（Traceability） 【核心】

| 需求/标准 ID | 摘要 | 对应设计（Plan.md） | 映射任务 ID | 测试/验证映射 | 状态 |
| --- | --- | --- | --- | --- | --- |
| `US1` / `SC-003` | 单智能体编排、四模式交卷、`Report{id}` Schema 与 128 槽模型缓存 | 第 3、5、6 章 | `T001`, `T002`, `T005`, `T006`, `T007`, `T008` | `TT-01`, `TT-02` | 已验证 |
| `US2` / `SC-001`, `SC-002` | `EvidenceChecker`、`DocumentIndex`、列表高速去重与空表 0 行证明 | 第 3、5、6 章 | `T009`, `T010`, `T011` | `TT-03` | 已验证 |
| `US3` / `SC-001` | `ModelRetry` 打回重填、部分挽救、可达环检测与级联降级 | 第 3、6 章 | `T012`, `T013`, `T014` | `TT-04` | 已验证 |
| `US4` / `SC-004`, `SC-005` | `_RuntimeBundle` 热切、`_DynamicLimiter` 控流、`EventSink` 与溯源输出 | 第 4、5、6、9 章 | `T004`, `T015`, `T016` | `TT-05` | 已验证 |
| `FR-001` | 快照捕获、模板状态核验、入参裁剪与防 ReDoS 校验 | 第 5、6.1 节 | `T003`, `T007`, `T008` | `TT-01`, `TT-06` | 已验证 |
| `FR-002` | 动态构造严格 `Report{suffix}`、`Row{suffix}_{idx}` 与证据联合体 | 第 3.1 节 | `T006`, `T008`, `T017` | `TT-01`, `TT-06` | 已验证 |
| `FR-003` | `build_model` 四模式能力覆写与 128 槽 LRU 缓存 | 第 4.1, 5.1 节 | `T005`, `T007`, `T008` | `TT-02` | 已验证 |
| `FR-004` | 白名单提示词组装与 `原规则（Java）：` 对照注释剥离 | 第 5.1 节 | `T001`, `T007`, `T017` | `TT-01`, `TT-06` | 已验证 |
| `FR-005` | `DocumentIndex` 定位、标量容器防御、`VALUE_TOOLS` 与列表核验 | 第 3.1, 6.1 节 | `T009`, `T010`, `T011` | `TT-03` | 已验证 |
| `FR-006` | 可达环探测 `_find_reachable_cycle` 与共享实源不动点计算 | 第 3.1, 6.2 节 | `T012`, `T014` | `TT-04` | 已验证 |
| `FR-007` | `ModelRetry` 打回、`_salvage_partial_report` 与 `_cascade_degraded_fields` | 第 3.2, 6.2 节 | `T013`, `T014` | `TT-04` | 已验证 |
| `FR-008` | `_RuntimeBundle` 热切与跨线程安全 `_DynamicLimiter` | 第 3.1, 6.2, 9 章 | `T015`, `T016` | `TT-05` | 已验证 |
| `FR-009` | `EventSink`/`queue_listener` 轨迹流与异常取消先写盘后透传 | 第 5.1, 6.2 节 | `T004`, `T015`, `T016` | `TT-05`, `TT-06` | 已验证 |
| `FR-010` | 统一渲染、三态判定、`not_found` 清空证据与 `evidenceTarget` | 第 6.1, 8 章 | `T015`, `T016` | `TT-05` | 已验证 |
| `NFR-001`~`NFR-006` | 零硬编码、单进程安全、`< 5.0 ms` 性能、零凭据硬编码与全链路事件 | 第 1.5, 10, 11 章 | `T011`, `T016`, `T017`, `T018` | `TT-03`, `TT-05`, `TT-06` | 已验证 |
| `EX-001`~`EX-006` | 自环掩盖、标量容器、取消重抛、闭循环监听、零字段与缺字段挽救 | 第 6.2, 10.1 节 | `T011`, `T014`, `T016`, `T017` | `TT-03`~`TT-06` | 已验证 |

### 1.1 三类独立交付物维护台账

| 独立交付物 | 涉及情况与依据 | 关联任务 | 维护状态 | 验证结果 |
| --- | --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中；引用 `spec.md` 第 8.2 节） | 不生成 | 不涉及 | 仅维护进程内 `AgentRunner` Python 契约，未变更对外 REST/SSE 契约 |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中；引用 `spec.md` 第 8.2 节） | 不生成 | 不涉及 | 仅含 1 份通用平台 `system-prompt.md`，经 `validate_all` 核验非空 |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中；引用 `spec.md` 第 8.2 节） | 不生成 | 不涉及 | 沿用既有 `Settings` 基线环境变量，不改容器镜像与拓扑 |

---

## 2. 里程碑与切分策略（Milestones） 【补充】

| 阶段 / Milestone | 目标 | 任务范围 | 阶段工时（人天） | 验收定义 |
| --- | --- | --- | --- | --- |
| Phase 1: Setup | 运行时包初始化、全局提示词规范与脚本化假模型底座 | `T001`–`T002` | 3.0 | 包骨架、提示词与离线桩就绪 |
| Phase 2: Foundational | `RunDeps`、`Workspace`/`EventSink` 与四模式 `model_factory` | `T003`–`T005` | 6.0 | 公共上下文、事件管道与模型构建就绪 |
| Phase 3: User Story 1 (P1 · MVP) | 动态交卷 Schema、白名单提示词、四模式编排与 LRU 缓存 | `T006`–`T008` | 6.5 | 四种输出模式与前置校验试跑通过 |
| Phase 4: User Story 2 (P1) | `DocumentIndex`、强证据核验与列表 0 行/高速索引防线 | `T009`–`T011` | 6.0 | 标量/列表/空列表校验与性能指标 `< 5.0 ms` 通过 |
| Phase 5: User Story 3 (P2) | `ModelRetry` 打回、部分挽救、可达环探测与不动点降级 | `T012`–`T014` | 5.5 | 环检测与级联收敛通过端到端测试 |
| Phase 6: User Story 4 (P2) | `_RuntimeBundle` 热切、`_DynamicLimiter` 控流与状态/溯源输出 | `T015`–`T016` | 3.5 | 并发调额、取消保留与溯源定位通过 |
| Phase 7: Polish | 边界巩固回归、全量 `pytest` 与 `ruff` 静态门禁收口 | `T017`–`T018` | 2.5 | 全量 `196 passed`、`ruff` 零警告验收完成 |

### 2.1 依赖与交付顺序

- **阶段依赖**：`Phase 1`（Setup） → `Phase 2`（Foundational，阻塞所有用户故事） → `Phase 3`（US1 主管道）与 `Phase 4`（US2 证据核验）并行展开 → `Phase 5`（US3 打回与级联降级，依赖 US1/US2）与 `Phase 6`（US4 热切与控流，依赖 US1）推进 → `Phase 7`（Polish 全量收口）。
- **并行机会**：Phase 2 内 `T004`（`workspace.py`）与 `T005`（`model_factory.py`）独立成文件可并行；Phase 3～6 中各测试任务（`T008`、`T011`、`T014`、`T016`、`T017`）与后续实现并行。

---

## 3. 任务清单（按执行顺序） 【核心】

> 格式约束：`Setup`、`Foundational`、`Polish` 阶段严禁使用 `[USx]` 标签；`User Story` 阶段必须带 `[USx]` 标签；`[P]` 位于 `Txxx` 之后、`[USx]` 之前；所有任务均以真实测试与静态检查输出为依据标记为 `[X]`。

### 3.1 Phase 1: Setup (Shared Infrastructure)

- [X] T001 初始化智能体运行时包结构 `src/report_agent/runtime/__init__.py` 并编写包含通用工作流程、单据归属判定与空列表防幻觉铁律的系统提示词 `src/report_agent/seed/system-prompt.md`（1.5 人天）
- [X] T002 [P] 构建离线确定性脚本化模型测试桩 `tests/scripted_model.py`（覆盖 `load_skill`/`call_api`/`format_date` 交互、首轮截断退回与二轮修正交卷）（1.5 人天）

### 3.2 Phase 2: Foundational (Blocking Prerequisites)

- [X] T003 实现单次运行不可变依赖快照上下文 `RunDeps` 于 `src/report_agent/runtime/deps.py`（2.0 人天）
- [X] T004 [P] 实现工作区 `Workspace`、`ApiResult`、`ToolCall`、`ProcessEvent`、`EventSink` 与抗异常跨线程 `queue_listener` 于 `src/report_agent/runtime/workspace.py`（2.0 人天）
- [X] T005 [P] 实现 OpenAI 兼容模型客户端与四模式能力覆写 `build_model` / `build_model_settings` 于 `src/report_agent/runtime/model_factory.py`（2.0 人天）

### 3.3 Phase 3–6: User Stories (Priority: P1–P2)

#### Phase 3: User Story 1 - 单智能体统一编排、动态交卷 Schema 与线上模型缓存 (Priority: P1) 🎯 MVP

**目标**：实现严格动态交卷模型 `Report{suffix}`、白名单任务提示词、入参快速失败校验、四模式运行管道与 `128` 槽 LRU 缓存。

**独立测试**：通过 `tests/test_agent_runtime.py` 与 `tests/test_native_output.py` 验证 `tool`/`native`/`json_object`/`prompted` 报文与 Schema 约束。

- [X] T006 [US1] 实现动态构造严格交卷模型（`Report{suffix}`、`Row{suffix}_{idx}` 别名映射、`extra="forbid"`、证据白名单联合体与 `ApiEvidence.row` 防布尔验证）于 `src/report_agent/runtime/output_model.py`（2.5 人天）
- [X] T007 [US1] 实现白名单任务提示词组装 `build_task_instructions`（含 `原规则（Java）：` 剥离）于 `src/report_agent/runtime/prompt.py` 与 `AgentRunner` 快照锁定、`validate_inputs` 校验、四模式调度及 128 槽 LRU 缓存于 `src/report_agent/runtime/runner.py`（2.5 人天）
- [X] T008 [P] [US1] 编写动态交卷 Schema 校验、入参快速失败拦截及四种结构化输出模式 HTTP 请求报文测试于 `tests/test_agent_runtime.py` 与 `tests/test_native_output.py`（1.5 人天）

#### Phase 4: User Story 2 - `quote`/`input`/`derive` 强证据核验与列表零记录防线 (Priority: P1)

**目标**：实现 `DocumentIndex` 惰性索引与 `EvidenceChecker` 全规则确定性核验，涵盖容器防御、`quoteWhole`、`VALUE_TOOLS`、高速列表去重与空列表 0 行查询证明。

**独立测试**：直接构造 `Workspace` 与 `ApiResult` 验证 `EvidenceChecker` 错因定位及 50 行列表核验 `< 5.0 ms` 基准。

- [X] T009 [US2] 实现惰性单据定位索引 `DocumentIndex`（行偏移映射、多空白折叠与 512 项缓存）与 `_values_equivalent` 标量等价比较原语于 `src/report_agent/runtime/evidence.py`（2.5 人天）
- [X] T010 [US2] 实现 `EvidenceChecker` 主校验器，覆盖 `quote`/`input`/`derive` 核验、`VALUE_TOOLS`（`format_date` 单值及批量 `values`）、`_check_empty_list_evidence` 空列表 0 行证明及 `_check_list_field` 高速去重索引核验于 `src/report_agent/runtime/evidence.py`（2.0 人天）
- [X] T011 [P] [US2] 补充单据空白折叠定位、合法空列表 vs 伪造空表、`load_skill` 拦截与 50 行列表 `< 5.0 ms` 性能基准测试于 `tests/test_agent_runtime.py` 与 `tests/test_review_fixes_runtime.py`（1.5 人天）

#### Phase 5: User Story 3 - `ModelRetry` 打回重填、超限挽救与依赖图级联降级 (Priority: P2)

**目标**：实现校检退回重填、候选提取与局部字段挽救、图可达环探测及沿依赖图不动点级联降级。

**独立测试**：构造首轮截断重填、重试耗尽缺字段、`C -> A <-> B` 环路与 `甲 -> 甲` 自引用场景验证收敛状态。

- [X] T012 [US3] 实现共享实源判定 `has_supporting_real_source`、不动点悬空支撑计算 `_compute_supported_found_fields` 与防自环剪枝环探测 `_find_reachable_cycle` 于 `src/report_agent/runtime/evidence.py`（2.0 人天）
- [X] T013 [US3] 实现 `@agent.output_validator` 打回 `ModelRetry`、候选提取 `_extract_json_dict`/`_extract_candidate_report`、部分挽救 `_salvage_partial_report` 与不动点级联降级 `_cascade_degraded_fields` 于 `src/report_agent/runtime/runner.py`（2.0 人天）
- [X] T014 [P] [US3] 补充 `ModelRetry` 重试耗尽挽救、自引用掩盖隔离、`C -> A <-> B` 环检出与自报 `not_found` 端到端级联降级测试于 `tests/test_review_runtime.py` 与 `tests/test_review_fixes_runtime.py`（1.5 人天）

#### Phase 6: User Story 4 - 零撕裂在线热切、动态并发限流、轨迹事件流与证据溯源 (Priority: P2)

**目标**：实现不可变 `_RuntimeBundle` 热切、跨线程安全 `_DynamicLimiter` 控流、`SUCCESS`/`PARTIAL`/`FAILED` 三态渲染判定、残留证据清空及前端溯源输出。

**独立测试**：验证跨线程调额门控与唤醒、取消任务落盘后原样重抛、以及多匹配单据 `evidenceTarget` 输出。

- [X] T015 [US4] 实现 `_RuntimeBundle` 原子热切 `reload_config`、跨线程安全 `_DynamicLimiter` 与 `_finish` 三态判定、`not_found` 清空证据及 `_evidence_label` 溯源解析于 `src/report_agent/runtime/runner.py`（2.0 人天）
- [X] T016 [P] [US4] 编写 `_DynamicLimiter` 降额/升额及失效 `Future` 清理、事件队列闭环容错、`not_found` 证据清空与 `CancelledError` 落盘保留测试于 `tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py` 与 `tests/test_runtime_config_hot_reload.py`（1.5 人天）

### 3.4 Phase 7: Polish & Cross-Cutting Concerns

- [X] T017 [P] 补充零字段草稿模板容错、重复入参去重、空白描述裁剪、空 `llm_api_key` 兜底与 `ProcessEvent` 系统字段防覆写边界回归测试于 `tests/test_agent_runtime.py` 与 `tests/test_review_runtime.py`（1.5 人天）
- [X] T018 运行全量 `pytest` 回归套件与 `ruff` 静态检查，核验所有运行时源码、测试与 `wiki/` 架构文档一致性并完成验收收口（1.0 人天）

### 3.5 任务详情与完成记录

#### 任务组：`T001`–`T002`（Phase 1: Setup）

- **关联需求**：`FR-004`、`US1`
- **关键变更点**：`src/report_agent/runtime/__init__.py`、`src/report_agent/seed/system-prompt.md`（通用工作流、单据归属判别与空列表规则）、`tests/scripted_model.py`（`ORDER_SMS`、`build_report` 及工具/二轮纠偏脚本桩）。
- **验证方式与实测证据**：作为全量测试基础桩纳入本轮实测 `uv run pytest -q`（`196 passed in 51.41s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）一并验证通过。
- **状态与阻塞**：已完成，无阻塞项。

#### 任务组：`T003`–`T005`（Phase 2: Foundational）

- **关联需求**：`FR-001`、`FR-003`、`FR-009`、`US1`、`US4`
- **关键变更点**：`RunDeps`（`deps.py`）；`Workspace`、`ApiResult`、`ToolCall`、`ProcessEvent`、`EventSink`、`queue_listener`（`workspace.py`）；`build_model`、`build_model_settings`（`model_factory.py`）。
- **验证方式与实测证据**：覆盖于 `tests/test_agent_runtime.py`、`tests/test_native_output.py` 与 `tests/test_review_runtime.py`（`test_eventsink_queue_listener_same_loop_and_closed_loop` 等），随本轮 `uv run pytest -q`（`196 passed in 51.41s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）验证通过。
- **状态与阻塞**：已完成，无阻塞项。

#### 任务组：`T006`–`T008`（Phase 3: US1 MVP）

- **关联需求**：`FR-001`~`FR-004`、`US1`、`SC-003`
- **关键变更点**：`build_report_model`、`Row{suffix}_{idx}`、`FieldAnswer{suffix}_{n}`、`ApiEvidence`（`output_model.py`）；`build_task_instructions`（`prompt.py`）；`AgentRunner.run`、`validate_inputs`、`128` 槽 `_agent_cache`（`runner.py`）；`tests/test_agent_runtime.py`、`tests/test_native_output.py`。
- **验证方式与实测证据**：覆盖 `test_report_model_is_template_specific`、`test_input_validation`、`test_native_json_schema_mode`、`test_json_object_mode_for_deepseek`、`test_prompted_mode_omits_response_format_and_salvages_partial_fenced_json` 等用例，随本轮 `uv run pytest -q`（`196 passed in 51.41s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）全部通过。
- **状态与阻塞**：已完成，无阻塞项。

#### 任务组：`T009`–`T011`（Phase 4: US2 强证据核验）

- **关联需求**：`FR-005`、`US2`、`SC-001`、`SC-002`、`NFR-003`
- **关键变更点**：`DocumentIndex`、`_values_equivalent`、`EvidenceChecker`、`VALUE_TOOLS`、`_check_empty_list_evidence`、`_check_list_field`（`evidence.py`）；`tests/test_agent_runtime.py`、`tests/test_review_fixes_runtime.py`。
- **验证方式与实测证据**：`test_evidence_checker`、`test_empty_list_evidence_strict_validation` 与 `test_list_field_quote_evidence_dedup_and_perf`（验证 50 行 × 4 列 × 150 条引用中位耗时 `< 5.0 ms`）等用例随本轮 `uv run pytest -q`（`196 passed in 51.41s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）全部通过。
- **状态与阻塞**：已完成，无阻塞项。

#### 任务组：`T012`–`T014`（Phase 5: US3 重试打回与级联降级）

- **关联需求**：`FR-006`、`FR-007`、`US3`、`EX-001`、`EX-002`、`EX-006`
- **关键变更点**：`has_supporting_real_source`、`_compute_supported_found_fields`、`_find_reachable_cycle`（`evidence.py`）；`_extract_json_dict`、`_extract_candidate_report`、`_salvage_partial_report`、`_degrade_failed_fields`、`_cascade_degraded_fields`（`runner.py`）；`tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py`。
- **验证方式与实测证据**：覆盖 `test_retries_exhausted_degrades_field`、`test_missing_fields_in_model_output_salvaged_gracefully`、`test_self_reference_cannot_mask_not_found_dependency_and_cascades`、`test_ref_exists_cycle_tail_and_self_reported_not_found_cascade` 等用例，随本轮 `uv run pytest -q`（`196 passed in 51.41s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）全部通过。
- **状态与阻塞**：已完成，无阻塞项。

#### 任务组：`T015`–`T016`（Phase 6: US4 热更新、控流与溯源）

- **关联需求**：`FR-008`、`FR-009`、`FR-010`、`US4`、`SC-004`、`SC-005`、`EX-003`、`EX-004`
- **关键变更点**：`_RuntimeBundle`、`_DynamicLimiter`、`AgentRunner.reload_config`、`_finish`、`_evidence_label`（`runner.py`）；`tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py`、`tests/test_runtime_config_hot_reload.py`。
- **验证方式与实测证据**：覆盖 `test_runtime_defaults_prompt_cache_doc_index_and_dynamic_limiter`、`test_runner_clears_not_found_evidence_and_preserves_cancelled_error`、`test_document_multi_match_offset_and_line_locating` 等用例，随本轮 `uv run pytest -q`（`196 passed in 51.41s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）全部通过。
- **状态与阻塞**：已完成，无阻塞项。

#### 任务组：`T017`–`T018`（Phase 7: Polish 与最终验收）

- **关联需求**：`NFR-001`~`NFR-006`、`EX-005`
- **关键变更点**：`tests/test_agent_runtime.py`（`test_zero_field_template_and_invalid_input_regex_and_workspace_guards`）、`tests/test_review_runtime.py`（`test_scalar_field_rejects_list_or_dict_in_evidence_and_salvage`）以及全量运行检查与代码规范审阅。
- **验证方式与实测证据**：本轮全量执行 `uv run pytest -q` 输出 `196 passed in 51.41s`；静态检查 `uvx ruff@0.11.0 check src tests` 输出 `All checks passed!`。
- **状态与阻塞**：已完成，无阻塞项。

---

## 4. 子任务拆解（可选） 【补充】

> 本需求 `T001`–`T018` 粒度已对齐单模块与独立验证目标，无需额外子任务拆解。

---

## 5. 代码实现约束（仅本需求新增） 【补充】

- **并发与一致性**：`AgentRunner.run` 入口一次捕获 `rev`、`ResourceSet` 与 `_RuntimeBundle` 局部引用；`online` 模型缓存键严格绑定 `(rev, tpl.id, bundle.seq)`（上限 `128` 槽）；`_DynamicLimiter` 与工作区按单进程 `workers=1` 内存模型运行。
- **安全与隐私边界**：`llm_api_key` 经 `SecretStr` 读取，测试仅使用 `FunctionModel` / `MockTransport`；入参校验正则经 `safe_regex_fullmatch` 防 ReDoS；交卷全树 `extra="forbid"` 且 `ApiEvidence.row` 拒绝 `bool`。
- **错误与降级语义**：校验不通过未超限抛 `ModelRetry(format_issues(issues))`，超限或异常调用 `_salvage_partial_report` + `_cascade_degraded_fields` 收敛降级并清空所有 `not_found` 字段残留 `evidence`；遭遇 `CancelledError` 必须先写出 `RunStore` 后再原样重抛。

---

## 6. 测试任务矩阵（Test Tasks） 【核心】

| 测试编号 | 类型 | 测试场景与关注点 | 关联任务 | 测试路径 | 验证命令与结果 |
| --- | --- | --- | --- | --- | --- |
| `TT-01` | 单元/端到端测试 | 动态模型构建、入参校验、工具隔离、多空白/多匹配定位与零字段模板 | `T002`, `T006`, `T008`, `T011`, `T017` | `tests/test_agent_runtime.py` | 随全量 `uv run pytest -q`（`196 passed in 51.41s`）验证通过 |
| `TT-02` | 协议适配集成测试 | `native`（`strict` 与 `oneOf` 消解）、`json_object` 与 `prompted` 代码块挽救 | `T005`, `T007`, `T008` | `tests/test_native_output.py` | 随全量 `uv run pytest -q`（`196 passed in 51.41s`）验证通过 |
| `TT-03` | 性能与专项核验测试 | 50 行 × 150 条 `api` 证据 `< 5.0 ms`、空列表 0 行证明、`DocumentIndex` 缓存、热重载限流 | `T009`, `T010`, `T011`, `T016` | `tests/test_review_fixes_runtime.py` | 随全量 `uv run pytest -q`（`196 passed in 51.41s`）验证通过 |
| `TT-04` | 安全与降级加固测试 | 自引用防掩盖、`C -> A <-> B` 环检测、容器标量拒收、闭循环监听与 `CancelledError` 保留 | `T004`, `T012`, `T013`, `T014`, `T016`, `T017` | `tests/test_review_runtime.py` | 随全量 `uv run pytest -q`（`196 passed in 51.41s`）验证通过 |
| `TT-05` | 热配置联动测试 | `AgentRunner.reload_config` 刷新工具/模型参数、并发度切换与历史配置回滚 | `T015`, `T016` | `tests/test_runtime_config_hot_reload.py` | 随全量 `uv run pytest -q`（`196 passed in 51.41s`）验证通过 |
| `TT-06` | 全量门禁与静态检查 | 全仓库无外网测试套件回归与代码风格、类型/导入检查 | `T018` | `src/`、`tests/` | `uv run pytest -q`（`196 passed in 51.41s`）；`uvx ruff@0.11.0 check src tests`（`All checks passed!`） |

---

## 7. 发布任务清单（Release Tasks） 【核心】

| 发布编号 | 动作内容 | 前置依赖 | 验证与完成标准 | 回滚动作 | 关联任务 |
| --- | --- | --- | --- | --- | --- |
| `RT-01` | 运行后端全量测试与静态检查门禁 | `T001`–`T017` 完成 | `uv run pytest -q` 全量 196 项通过且 `ruff` 零警告 | 回退变更代码提交 | `T018` |
| `RT-02` | 确认 `system-prompt.md` 纳入内置 seed 与发布快照 `releases/current` 校验 | `RT-01` | `validate_all` 无 `SYSTEM_PROMPT_EMPTY` 阻塞错误 | 切回前一 `releases/rN` 软链接 | `T001`, `T018` |
| `RT-03` | 单进程 `workers=1` 容器运行参数及在线热切巡检 | `RT-01`, `RT-02` | `/healthz` 就绪且 `reload_config` 后新请求切换生效 | 回退配置修订 `cN` 或容器镜像 | `T015`, `T018` |

---

## 8. 可观测性与验收（Observability & Acceptance） 【补充】

### 8.1 关键过程事件、日志与审计点位

| 场景 | 载体（过程事件 / 日志 / 审计） | 关键上下文字段 | 隐私脱敏约束 |
| --- | --- | --- | --- |
| 运行启动与模型多轮推理 | `EventSink` (`run_started`/`model_request`/`model_text`) | `runId`, `templateId`, `rev`, `skills`, `apis`, `seq`, `atMs`, `round` | `model_text` 仅保留前 2000 字；不包含 `llm_api_key` |
| 交卷校验与打回/降级 | `EventSink` (`report_rejected`/`report_accepted`/`report_degraded`)、`Workspace.validation_rounds` | `attempt`, `issues`（`{field, message}`）, `fields` | 不输出底层网关密钥或内部异常堆栈 |
| 失败、超时与取消运行 | `EventSink` (`run_failed`)、`logging`、`RunStore` | `runId`, `templateId`, `status="FAILED"`, `error`, `usage`, `messages` | 取消记为 `"运行已取消"`，敏感凭据不入日志与运行摘要 |

### 8.2 验收清单

- 第 3 章 18 项权威任务已全部依据 `uv run pytest -q`（`196 passed in 51.41s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）真实输出核验完成。
- `spec.md`、`plan.md` 与 `tasks.md` 间 `US1`~`US4`、`FR-001`~`FR-010`、`SC-001`~`SC-005`、`NFR-001`~`NFR-006`、`EX-001`~`EX-006` 全链路闭环无遗漏、工时合计严格等于 `33.0 人天`。
- 三类外部独立交付物与 `wiki/` 影响已在第 1.1 节与 `plan.md` 第 1.7–1.8 节核对闭环。

---

## 9. 阻塞与待确认（Blockers & Open Questions） 【核心】

> 当前无阻塞问题（历史 `Q-001` 与 `DQ-1` 已闭环关闭）。

| 编号 | 问题描述 | 关联 Spec `Q-*` | 影响任务 | 责任方 | 状态 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `BQ-1` | 四种结构化输出模式与空列表 `found: []` 校验验收口径确认 | `Q-001` | `T007`, `T010`, `T015` | 架构组 / 运行时团队 | 已关闭 | 四模式热配适配与空列表 0 行证明机制已全量验证通过 |

---

## 10. 变更记录（Changelog） 【补充】

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | AiCoding(codex) | 完成 `003-agent-runner-evidence` 初版任务拆解与归档 |
| 2.0 | 2026-11-16 | AiCoding(codex) | 按改造后中文 Spec-Kit 模板重构任务结构，补齐映射追踪、任务详情组、测试/发布/可观测矩阵与实测证据 |

---

## 附录 A：任务依赖简图

```text
Phase 1: Setup (T001, T002)
   └─▶ Phase 2: Foundational (T003, T004, T005)
          ├─▶ Phase 3: US1 (T006 ─▶ T007 ─▶ T008)
          ├─▶ Phase 4: US2 (T009 ─▶ T010 ─▶ T011)
          │         └─▶ Phase 5: US3 (T012 ─▶ T013 ─▶ T014)
          └─▶ Phase 6: US4 (T015 ─▶ T016)
                    └─▶ Phase 7: Polish (T017 ─▶ T018)
```

## 附录 B：AI 执行提示

1. 编码与复核前核对 `spec.md` 第 9 节 Out of Scope 与 `plan.md` 第 1.4 节禁止修改范围，不越界改动 `tools.py`/`gateway/`/`domain/`/`store/`。
2. 所有已勾选 `[X]` 任务均以真实执行的测试与静态检查输出为依据，严禁虚构单独运行耗时。

---

## 增量更新说明

> 本文档依据改造后中文 Spec-Kit 模板与 `/sdd-documentation` 标准维护；后续新增或重拆任务需同步刷新第 1 节映射表与第 10 节变更记录。
