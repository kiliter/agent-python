---
description: "12 项确定性平台工具原语与双协议热更新外部网关连接器（RA-004）标准 SDD 任务清单"
---

# 任务说明（Implementation Tasks）：12 项确定性平台工具原语与双协议热更新外部网关连接器

<!-- #Created By AiCoding(codex) -->

> **Spec Kit 使用约定**：本文件承接 `spec.md` 与 `plan.md`（`inline-v1` 单文件内联布局），将设计切片转化为顺序清晰、带精确文件路径、可独立验证的 18 项任务清单（合计 `33.0 人天`）。所有 18 项任务均已依托本轮实测通过的 `uv run pytest -q`（`196 passed in 51.41s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）完成归档验收。

---

## 基本信息

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-004` |
| 需求名称 | 12 项确定性平台工具原语与双协议热更新外部网关连接器 |
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
| `US1` / `SC-001`, `SC-002` | 白名单 `load_skill`/`call_api` 幂等去重接管与 `query_result` 合并过滤 | 第 3、5、6 章 | `T005`, `T006`, `T007`, `T008` | `TT-01`, `TT-04` | 已验证 |
| `US2` / `SC-003` | 9 项纯函数确定性文本/日历/账期/时间差/防 ReDoS 工具原语 | 第 3、5、6 章 | `T002`, `T009`, `T010`, `T011` | `TT-01`, `TT-02` | 已验证 |
| `US3` / `SC-004` | XML/JSON 双协议 `UnifiedGatewayXmlClient`、XXE/显式栈防护、脱敏与限流重试 | 第 3、5、6 章 | `T001`, `T003`, `T004`, `T012`, `T013`, `T014` | `TT-02`, `TT-03` | 已验证 |
| `US4` / `SC-005` | 双级沙箱 `MockGatewayClient`（含 XML→JSON）与 `ReloadableGatewayClient` 热排空 | 第 3、4、6、9 章 | `T015`, `T016` | `TT-03`, `TT-05` | 已验证 |
| `FR-001` | 固定 12 工具注册、`_record` `callId` 账本及 `_fail_or_retry` | 第 5.1, 6.2 节 | `T005`, `T010` | `TT-01` | 已验证 |
| `FR-002` | `load_skill` 单/批量去重与动态 `enum` 隐藏机制 | 第 5.1 节 | `T006`, `T008` | `TT-01`, `TT-04` | 已验证 |
| `FR-003` | `call_api` 参数校验、幂等并发 `asyncio.shield` 取消接管与预览截断 | 第 5.1, 6.2 节 | `T006`, `T008` | `TT-04` | 已验证 |
| `FR-004` | `query_result` 单/多结果合并、7 操作符、0 行已知列校验与失败阻断 | 第 3.1, 5.1 节 | `T007`, `T008` | `TT-01`, `TT-04` | 已验证 |
| `FR-005` | 9 项确定性纯函数（4 规则扫描、36 月限额、防 ReDoS 等）与工具外壳 | 第 4.1, 5.1 节 | `T002`, `T009`, `T010`, `T011` | `TT-01`, `TT-02` | 已验证 |
| `FR-006` | `GatewayClient` 协议、`decode_xml`、`expat` 防 XXE、显式栈展平与对称五模式 | 第 3.1, 5.1 节 | `T001`, `T003`, `T004`, `T017` | `TT-02`, `TT-03`, `TT-05` | 已验证 |
| `FR-007` | `java`/`clean` XML 组包、JSON 组包、脱敏预览与安全头合并 | 第 5.1 节 | `T012`, `T014` | `TT-02`, `TT-03` | 已验证 |
| `FR-008` | 禁重定向、并发信号量（默认 32）、HTTP 分类与幂等指数退避重试 | 第 6.2, 9 章 | `T013`, `T014` | `TT-02`, `TT-03` | 已验证 |
| `FR-009` | `MockGatewayClient` 双级安全检索与 XML→JSON 自动无损转换 | 第 4.1, 5.1 节 | `T015`, `T016` | `TT-02`, `TT-03`, `TT-05` | 已验证 |
| `FR-010` | `ReloadableGatewayClient` 引用计数排空与 `asyncio.shield` 释放连接池 | 第 3.2, 6.2 节 | `T015`, `T016` | `TT-05` | 已验证 |
| `NFR-001`~`NFR-006` | 零硬编码、单进程并发、防 DoS/XXE/SSRF/ReDoS、脱敏与观测 | 第 1.5, 10, 11 章 | `T014`, `T016`, `T017`, `T018` | `TT-02`~`TT-06` | 已验证 |
| `EX-001`~`EX-006` | 工具降级、1500 层深 DoS、点分列空值对齐、leader 取消接管、路径穿越与退役释放 | 第 6.2, 10.1 节 | `T008`, `T014`, `T016`, `T017` | `TT-03`~`TT-05` | 已验证 |

### 1.1 三类独立交付物维护台账

| 独立交付物 | 涉及情况与依据 | 关联任务 | 维护状态 | 验证结果 |
| --- | --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中；引用 `spec.md` 第 8.2 节） | 不生成 | 不涉及 | 仅适配出站统一网关 `/openapi_3` 与内部工具接口，未变更外部上游入站契约 |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中；引用 `spec.md` 第 8.2 节） | 不生成 | 不涉及 | 生产 `apis/*.yaml` 与 `seed/mock-gateway` 资产清单归属 `RA-008` |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中；引用 `spec.md` 第 8.2 节） | 不生成 | 不涉及 | `GATEWAY_*` 及 `AGENT_*` 环境变量沿用项目基线配置，不涉及镜像与运维动作 |

---

## 2. 里程碑与切分策略（Milestones） 【补充】

| 阶段 / Milestone | 目标 | 任务范围 | 阶段工时（人天） | 验收定义 |
| --- | --- | --- | --- | --- |
| Phase 1: Setup | 网关包初始化、安全上限常量与文本标点清除基线 | `T001`–`T002` | 3.0 | 契约协议与确定性字符集常量就绪 |
| Phase 2: Foundational | `expat` 反 XXE、显式栈五模式抽取与工具公共记账框架 | `T003`–`T005` | 6.0 | 安全解析底座与 `build_tools` 脚手架就绪 |
| Phase 3: User Story 1 (P1 · MVP) | `load_skill` 批量隔离、`call_api` 幂等接管与 `query_result` | `T006`–`T008` | 6.5 | 核心取数与跨结果合并过滤测试通过 |
| Phase 4: User Story 2 (P1) | 9 项确定性纯函数（日历/账期/时间差/防 ReDoS）与包装 | `T009`–`T011` | 6.0 | 日历边界、账期上限与 5 类 ReDoS 拦截通过 |
| Phase 5: User Story 3 (P2) | `UnifiedGatewayXmlClient` 双协议组包、脱敏与信号量重试 | `T012`–`T014` | 5.5 | Java 字节对拍、1500 层 JSON 与限流重试通过 |
| Phase 6: User Story 4 (P2) | 双级 `MockGatewayClient` 与 `ReloadableGatewayClient` 热排空 | `T015`–`T016` | 3.5 | 路径防逃逸、XML→JSON 与取消防泄漏通过 |
| Phase 7: Polish | 响应模式交叉复核、全量 `pytest` 与 `ruff` 静态检查 | `T017`–`T018` | 2.5 | 全量 `196 passed`、`ruff` 零警告验收完成 |

### 2.1 依赖与交付顺序

- **阶段依赖**：`Phase 1`（Setup） → `Phase 2`（Foundational，阻塞核心解析与工具挂载） → `Phase 3`（US1 三大取数工具）、`Phase 4`（US2 9 项计算原语）与 `Phase 5`（US3 真实网关）并行推进 → `Phase 6`（US4 本地 Mock 与热排空代理） → `Phase 7`（Polish 联合回归收口）。
- **并行机会**：`T004`（对称抽取）与 `T005`（工具框架）独立成文件可并行；`US1`、`US2` 与 `US3` 主体模块与测试文件相互独立可并行验证。

---

## 3. 任务清单（按执行顺序） 【核心】

> 格式约束：`Setup`、`Foundational`、`Polish` 阶段严禁使用 `[USx]` 标签；`User Story` 阶段必须带 `[USx]` 标签；`[P]` 位于 `Txxx` 之后、`[USx]` 之前；所有任务均以真实测试与静态检查输出为依据标记为 `[X]`。

### 3.1 Phase 1: Setup (Shared Infrastructure)

- [X] T001 初始化外部网关连接器包结构 `src/report_agent/gateway/__init__.py` 并定义 XML/JSON 安全长度上限、显式栈深度上限与 `ApiCallResult`/`GatewayClient` 协议于 `src/report_agent/gateway/base.py`（1.5 人天）
- [X] T002 [P] 定义 Java `StringCharCleaner` 兼容清洗字符集 `FIXED_CHARS_TO_REMOVE`、零宽字符集与文本/账期安全限制常量（`MAX_REGEX_TEXT_LENGTH`、`MAX_PERIOD_MONTHS`）于 `src/report_agent/runtime/text_tools.py`（1.5 人天）

### 3.2 Phase 2: Foundational (Blocking Prerequisites)

- [X] T003 实现 XML 多编码解码 `decode_xml`、控制字符清洗 `sanitize_xml_text`、基于 `expat` 词法钩子的 `parse_xml`（阻断 `DOCTYPE`/`ENTITY` 并放行 CDATA）与 `parse_json_body` 于 `src/report_agent/gateway/base.py`（2.0 人天）
- [X] T004 [P] 实现显式栈嵌套展平、点分列跨数组聚合与完全对称的 XML/JSON `auto`/`object`/`list`/`scalar`/`none` 五模式抽取及 `xml_to_json_data` 于 `src/report_agent/gateway/base.py`（2.0 人天）
- [X] T005 [P] 实现工具公共登记记账 `_record`、重试/降级出口 `_fail_or_retry` 与 12 项平台工具装配入口 `build_tools` 于 `src/report_agent/runtime/tools.py`（2.0 人天）

### 3.3 Phase 3–6: User Stories (Priority: P1–P2)

#### Phase 3: User Story 1 - 白名单 Skill 批量加载、幂等并发调用与跨结果集结构化查询 (Priority: P1) 🎯 MVP

**目标**：交付受模板白名单约束的 `load_skill`、`call_api`（工作区幂等去重与 leader 取消接管）以及支持跨月合并过滤和 0 行列名检验的 `query_result`。

**独立测试**：运行 `tests/test_deterministic_tools.py`、`tests/test_review_runtime.py` 与 `tests/test_review_fixes_runtime.py` 验证白名单隐藏、取消接管与合并筛选。

- [X] T006 [US1] 实现 `load_skill`（单/批量去重加载与 `_prepare_load_skill` 动态 `enum`）与 `call_api`（参数校验、`_idempotent_cache`/`_idempotent_inflight` + `asyncio.shield` 并发取消接管与摘要截断）于 `src/report_agent/runtime/tools.py`（2.5 人天）
- [X] T007 [US1] 实现 `Condition`/`OrderBy`（`extra="forbid"`）与 `query_result` 筛选排序引擎（支持 `startsWith`/`between`/`before`/`prefixLen`、`anyOf`、`resultIds` 合并及 0 行全量列名自检）于 `src/report_agent/runtime/tools.py`（2.5 人天）
- [X] T008 [P] [US1] 补充 `load_skill` 批量/越权拦截、`call_api` leader 取消接管及失败重试复用、`query_result` 单/多结果筛选与参数校验测试于 `tests/test_deterministic_tools.py`、`tests/test_review_runtime.py` 与 `tests/test_review_fixes_runtime.py`（1.5 人天）

#### Phase 4: User Story 2 - 接管大模型心算的 9 项纯函数确定性文本、日历与防 ReDoS 工具集 (Priority: P1)

**目标**：交付 9 项纯函数确定性工具并暴露给单智能体，取代大模型手工计算文本归一化、日期提取、格式转换、日历偏移、多账期展开、时间差与正则抽提。

**独立测试**：运行 `tests/test_deterministic_tools.py` 与 `tests/test_text_and_gateway.py`，校验闰平年边界、干扰数字防误吸、36 月上限与 5 类 ReDoS 语法树拦截。

- [X] T009 [US2] 实现纯函数确定性核心算法 `normalize_text`、`normalized_contains`、`parse_date`/`format_date`/`convert_date`、`date_range` 与支持 4 类日历规则及 `defaultYear` 的 `extract_dates` 于 `src/report_agent/runtime/text_tools.py`（2.5 人天）
- [X] T010 [US2] 实现 `date_shift`、支持 4 级解析及跨度上限的 `expand_period`、`time_diff` 及基于 `safe_regex_compile` 的 `regex_extract` 于 `src/report_agent/runtime/text_tools.py` 并在 `src/report_agent/runtime/tools.py` 暴露全部 9 项工具包装器（2.0 人天）
- [X] T011 [P] [US2] 编写 9 项确定性原语单元测试（涵盖闰平年日历、无“日/号”后缀干扰项、36 月上限、5 类 ReDoS 嵌套量词拦截与 `VALUE_TOOLS` 批量输出比对）于 `tests/test_deterministic_tools.py`、`tests/test_text_and_gateway.py` 与 `tests/test_review_fixes_runtime.py`（1.5 人天）

#### Phase 5: User Story 3 - XML/JSON 双协议统一网关客户端、XXE 安全防护与并发保护 (Priority: P2)

**目标**：实现兼容前代 Java `XmlMapper` 与原生 JSON 的 `UnifiedGatewayXmlClient`，落实敏感字段脱敏、自定义安全头、禁止重定向、并发信号量与幂等指数退避重试。

**独立测试**：使用 `httpx.MockTransport` 运行 Java XML 字节对拍、XXE/1500 层深 JSON 防御、HTTP 错误分类及信号量并发测试。

- [X] T012 [US3] 实现 `build_request_xml`（`java`/`clean` 风格与 `_validate_tag` 防注入）、`build_request_json`、`mask_xml`/`mask_json`/`build_request_preview` 脱敏及 `_merge_http_headers` 安全头合并于 `src/report_agent/gateway/unified_xml.py`（2.0 人天）
- [X] T013 [US3] 实现 `UnifiedGatewayXmlClient` 异步调用引擎（`follow_redirects=False`、`asyncio.Semaphore` 并发保护、`httpx.Limits` 连接池、`_classify_http_error`、幂等指数退避重试与 200,000 字符响应截断）于 `src/report_agent/gateway/unified_xml.py`（2.0 人天）
- [X] T014 [P] [US3] 编写 XML Java 字节级对拍、JSON 双协议派发、自定义安全头拦截、1500 层深 JSON 与并发信号量实测于 `tests/test_text_and_gateway.py`、`tests/test_api_json_gateway.py` 与 `tests/test_review_fixes_runtime.py`（1.5 人天）

#### Phase 6: User Story 4 - 双级覆盖本地 `MockGatewayClient` 与引用计数热更新网关代理 (Priority: P2)

**目标**：交付防目录穿越且支持 XML→JSON 无损自动转换的双级 `MockGatewayClient`，以及通过引用计数排空与 `asyncio.shield` 释放连接池的 `ReloadableGatewayClient`。

**独立测试**：验证非法文件名拦截、XML 转 JSON 自动命中，以及热切换加超时取消下旧网关连接的零泄漏释放。

- [X] T015 [US4] 实现双级目录查找、`_SAFE_MOCK_NAME_RE`/`is_relative_to` 逃逸防护及 XML→JSON 无损转换的 `MockGatewayClient` 于 `src/report_agent/gateway/mock.py` 与引用计数排空热更新代理 `ReloadableGatewayClient` 于 `src/report_agent/gateway/reloadable.py`（2.0 人天）
- [X] T016 [P] [US4] 编写 `MockGatewayClient` 路径穿越防护、跨格式回退命中与 `ReloadableGatewayClient` 热切换及在途取消防泄漏测试于 `tests/test_text_and_gateway.py`、`tests/test_api_json_gateway.py`、`tests/test_review_storage.py` 与 `tests/test_runtime_config_hot_reload.py`（1.5 人天）

### 3.4 Phase 7: Polish & Cross-Cutting Concerns

- [X] T017 [P] 结合 `tests/test_api_response_modes.py` 交叉验证五类记录抽取、点分列跨数组空值对齐、显式栈边界与无递归异常回归（1.5 人天）
- [X] T018 运行全量 `pytest` 回归套件与 `ruff` 静态检查，核对全部工具原语、网关模块与 `wiki/` 架构文档一致性并完成验收收口（1.0 人天）

### 3.5 任务详情与完成记录

#### 任务组：`T001`–`T002`（Phase 1: Setup）

- **关联需求**：`FR-005`、`FR-006`、`US2`、`US3`
- **关键变更点**：`src/report_agent/gateway/__init__.py`、`ApiCallResult`/`GatewayClient`/`MAX_XML_CHARS`/`MAX_JSON_CHARS`/`_MAX_FLATTEN_DEPTH`（`gateway/base.py`）、`FIXED_CHARS_TO_REMOVE`/`_ZERO_WIDTH_CHARS`/`MAX_REGEX_TEXT_LENGTH`/`MAX_PERIOD_MONTHS`（`text_tools.py`）。
- **验证方式与实测证据**：作为基础设施纳入本轮全量 `uv run pytest -q`（`196 passed in 51.41s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）验证通过。
- **状态与阻塞**：已完成，无阻塞项。

#### 任务组：`T003`–`T005`（Phase 2: Foundational）

- **关联需求**：`FR-001`、`FR-006`、`US1`、`US3`
- **关键变更点**：`decode_xml`、`sanitize_xml_text`、`parse_xml`（`expat` 防 XXE）、`parse_json_body`、`_flatten_xml_element`、`_flatten_json_dict`、`extract_records`、`extract_json_records`、`xml_to_json_data`（`gateway/base.py`）；`_record`、`_fail_or_retry`、`build_tools`（`tools.py`）。
- **验证方式与实测证据**：覆盖于 `tests/test_text_and_gateway.py`、`tests/test_api_json_gateway.py` 与 `tests/test_api_response_modes.py`，随本轮 `uv run pytest -q`（`196 passed in 51.41s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）全部通过。
- **状态与阻塞**：已完成，无阻塞项。

#### 任务组：`T006`–`T008`（Phase 3: US1 取数与合并过滤工具）

- **关联需求**：`FR-002`、`FR-003`、`FR-004`、`US1`、`SC-001`、`SC-002`、`EX-004`
- **关键变更点**：`load_skill`、`_prepare_load_skill`、`call_api`、`_prepare_call_api`（含 `_idempotent_cache`/`_idempotent_inflight` + `asyncio.shield`）、`Condition`、`OrderBy`、`query_result`、`_validate_query_columns`（`tools.py`）；对应测试位于 `tests/test_deterministic_tools.py`、`tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py`。
- **验证方式与实测证据**：`test_call_api_and_query_result_call_id_and_idempotent_dedup`、`test_call_api_idempotent_leader_cancellation_handoff_and_retry_dedup`、`test_query_result_unified_single_and_multi_filtering`、`test_query_result_enhanced_operators_anyof_and_multi_results` 等用例随本轮 `uv run pytest -q`（`196 passed in 51.41s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）全部通过。
- **状态与阻塞**：已完成，无阻塞项。

#### 任务组：`T009`–`T011`（Phase 4: US2 9 项确定性计算原语）

- **关联需求**：`FR-001`、`FR-005`、`US2`、`SC-003`、`EX-001`
- **关键变更点**：`normalize_text`、`normalized_contains`、`parse_date`/`format_date`/`convert_date`、`date_range`、`extract_dates`、`date_shift`、`expand_period`、`time_diff`、`regex_extract`（`text_tools.py`）与 9 项异步工具包装器（`tools.py`）；对应测试位于 `tests/test_deterministic_tools.py`、`tests/test_text_and_gateway.py`、`tests/test_review_fixes_runtime.py`。
- **验证方式与实测证据**：覆盖 `test_value_tools_invariant_and_registered_tools`、`test_extract_dates_rules_and_calendar_validation`、`test_expand_period_months_ranges_and_single_values`、`test_deterministic_primitives_redos_and_batch_tools` 等用例，随本轮 `uv run pytest -q`（`196 passed in 51.41s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）全部通过。
- **状态与阻塞**：已完成，无阻塞项。

#### 任务组：`T012`–`T014`（Phase 5: US3 双协议统一网关连接器）

- **关联需求**：`FR-007`、`FR-008`、`US3`、`SC-004`、`EX-002`
- **关键变更点**：`build_request_xml`、`build_request_json`、`mask_xml`/`mask_json`/`build_request_preview`、`_merge_http_headers`、`_classify_http_error`、`UnifiedGatewayXmlClient`、`parse_gateway_response`、`parse_gateway_json_response`（`unified_xml.py`）；对应测试位于 `tests/test_text_and_gateway.py`、`tests/test_api_json_gateway.py`、`tests/test_review_fixes_runtime.py`。
- **验证方式与实测证据**：覆盖 `test_java_style_request_matches_existing_service`、`test_xxe_entity_expansion_and_cdata_safety`、`test_unified_gateway_http_status_classification_timeout_and_retry`、`test_deeply_nested_json_and_header_control_chars_safety`、`test_gateway_json_list_dotted_ret_msg_and_concurrency_semaphore` 等用例，随本轮 `uv run pytest -q`（`196 passed in 51.41s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）全部通过。
- **状态与阻塞**：已完成，无阻塞项。

#### 任务组：`T015`–`T016`（Phase 6: US4 双级 Mock 与热排空代理）

- **关联需求**：`FR-009`、`FR-010`、`US4`、`SC-005`、`EX-005`、`EX-006`
- **关键变更点**：`MockGatewayClient`（`mock.py`）；`ReloadableGatewayClient`、`_ClientSlot`（`reloadable.py`）；对应测试位于 `tests/test_text_and_gateway.py`、`tests/test_api_json_gateway.py`、`tests/test_review_storage.py`、`tests/test_runtime_config_hot_reload.py`。
- **验证方式与实测证据**：覆盖 `test_mock_gateway_sandbox_traversal_protection`、`test_mock_gateway_json_lookup_and_xml_lossless_fallback`、`test_injected_test_doubles_preserved_and_inflight_gateway_drained` 及 `tests/test_review_storage.py` 中 `ReloadableGatewayClient` 取消排空测试，随本轮 `uv run pytest -q`（`196 passed in 51.41s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）全部通过。
- **状态与阻塞**：已完成，无阻塞项。

#### 任务组：`T017`–`T018`（Phase 7: Polish 与最终验收）

- **关联需求**：`NFR-001`~`NFR-006`、`EX-003`
- **关键变更点**：`tests/test_api_response_modes.py`（`test_nested_flatten_and_explicit_dotted_columns_with_evidence` 等跨协议五模式一致性回归）及全仓库验证收口。
- **验证方式与实测证据**：本轮全量执行 `uv run pytest -q` 输出 `196 passed in 51.41s`；静态检查 `uvx ruff@0.11.0 check src tests` 输出 `All checks passed!`。
- **状态与阻塞**：已完成，无阻塞项。

---

## 4. 子任务拆解（可选） 【补充】

> 本需求 `T001`–`T018` 粒度已对齐单模块与独立验证目标，无需额外子任务拆解。

---

## 5. 代码实现约束（仅本需求新增） 【补充】

- **并发与一致性**：`call_api` 幂等复用在 `ok=False` 时严禁写入 `_idempotent_cache`；`UnifiedGatewayXmlClient` 信号量限流与 `ReloadableGatewayClient` 槽位引用计数均遵循单进程 `workers=1` 模型。
- **安全与隐私边界**：禁止向 `VALUE_TOOLS` 扩展除 `format_date` 外的工具；禁止绕过 `follow_redirects=False`、`_SAFE_MOCK_NAME_RE`、`is_relative_to`、`expat` XXE 钩子与 `safe_regex_compile`；脱敏函数必须保护 `app_id`/`access_token`/`verify_code` 与 11 位手机号（保留 `${占位符}`）。
- **错误与降级语义**：工具参数错误均走 `_fail_or_retry` 先打回 `ModelRetry`，耗尽则返回含 `callId` 的 `ok=False` 结构化报错；网关非幂等及 3xx/401/403/404 报错单次即止不重试。

---

## 6. 测试任务矩阵（Test Tasks） 【核心】

| 测试编号 | 类型 | 测试场景与关注点 | 关联任务 | 测试路径 | 验证命令与结果 |
| --- | --- | --- | --- | --- | --- |
| `TT-01` | 确定性工具测试 | 12 工具签名、`VALUE_TOOLS` 不变量、4 规则日期扫描、账期/偏移/秒差/正则、`query_result` 多条件过滤 | `T005`, `T007`, `T008`, `T009`, `T010`, `T011` | `tests/test_deterministic_tools.py` | 随全量 `uv run pytest -q`（`196 passed in 51.41s`）验证通过 |
| `TT-02` | XML 网关与安全测试 | `java`/`clean` XML 组包、Java 字节对拍、`expat` XXE 与 CDATA 分辨、HTTP 分类重试、Mock 防穿越 | `T003`, `T011`, `T012`, `T013`, `T014`, `T016` | `tests/test_text_and_gateway.py` | 随全量 `uv run pytest -q`（`196 passed in 51.41s`）验证通过 |
| `TT-03` | JSON 双协议与防溢出测试 | JSON/XML 双协议派发、自定义安全头拦截、1500 层深嵌套 JSON 防溢出、Mock XML→JSON 无损转换 | `T004`, `T012`, `T013`, `T014`, `T015`, `T016` | `tests/test_api_json_gateway.py` | 随全量 `uv run pytest -q`（`196 passed in 51.41s`）验证通过 |
| `TT-04` | 幂等接管与并发信号量测试 | `call_api` 幂等并发去重与 leader 取消接管、`query_result` 合并 0 行列检查、5 类 ReDoS 与并发信号量 | `T006`, `T008`, `T011`, `T014` | `tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py` | 随全量 `uv run pytest -q`（`196 passed in 51.41s`）验证通过 |
| `TT-05` | 热排空与五模式交叉测试 | `ReloadableGatewayClient` 取消排空、XML/JSON 点分列多节点对齐、`auto`/`object`/`list`/`scalar`/`none` 模式 | `T004`, `T015`, `T016`, `T017` | `tests/test_review_storage.py`、`tests/test_api_response_modes.py`、`tests/test_runtime_config_hot_reload.py` | 随全量 `uv run pytest -q`（`196 passed in 51.41s`）验证通过 |
| `TT-06` | 全量门禁与静态检查 | 全仓库无真实外网/网关套件回归与 `ruff` 静态检查 | `T018` | `src/`、`tests/` | `uv run pytest -q`（`196 passed in 51.41s`）；`uvx ruff@0.11.0 check src tests`（`All checks passed!`） |

---

## 7. 发布任务清单（Release Tasks） 【核心】

| 发布编号 | 动作内容 | 前置依赖 | 验证与完成标准 | 回滚动作 | 关联任务 |
| --- | --- | --- | --- | --- | --- |
| `RT-01` | 运行后端全量测试与静态检查门禁 | `T001`–`T017` 完成 | `uv run pytest -q` 全量 196 项通过且 `ruff` 零警告 | 回退变更代码提交 | `T018` |
| `RT-02` | 校验网关运行模式配置（`GATEWAY_MODE`、`GATEWAY_URL`、`GATEWAY_XML_STYLE`、`GATEWAY_MAX_CONCURRENCY`） | `RT-01` | Live 校验 `http://`/`https://`，Mock 校验样例目录与健康接口正常 | 切回 `GATEWAY_MODE=mock` 或回退配置修订 `cN` | `T013`, `T015`, `T018` |
| `RT-03` | 单进程容器启动及热切 `ReloadableGatewayClient.swap` 排空巡检 | `RT-01`, `RT-02` | 热切换网关参数后无在途报错与套接字泄露 | 回退配置修订 `cN` 或容器镜像 | `T015`, `T018` |

---

## 8. 可观测性与验收（Observability & Acceptance） 【补充】

### 8.1 关键过程事件、日志与审计点位

| 场景 | 载体（过程事件 / 日志 / 审计） | 关键上下文字段 | 隐私脱敏约束 |
| --- | --- | --- | --- |
| 12 项平台工具调用 | `EventSink` (`tool`)、`Workspace.tool_calls` | `callId`, `tool`, `args`, `ok`, `result` | `text_contains`/`regex_extract` 未传 `text` 时记录 `"<单据全文>"` 摘要 |
| 真实/Mock 网关调用与重试 | `logging` (`unified_xml.py`)、`ApiResult` | `processCode`, `attempt`, `http_status`, `costMs`, `requestPreview`, `raw` | `requestPreview` 自动隐藏 `app_id`/`access_token`/`verify_code` 与 11 位手机号；`raw` 截断上限保护 |
| 退役网关实例回收 | `logging` (`reloadable.py`) | 退役客户端释放状态与后台任务完成态 | 不记录任何认证凭据明文 |

### 8.2 验收清单

- 第 3 章 18 项权威任务已全部依据 `uv run pytest -q`（`196 passed in 51.41s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）真实输出核验完成。
- `spec.md`、`plan.md` 与 `tasks.md` 间 `US1`~`US4`、`FR-001`~`FR-010`、`SC-001`~`SC-005`、`NFR-001`~`NFR-006`、`EX-001`~`EX-006` 全链路闭环无遗漏、工时合计严格等于 `33.0 人天`。
- 三类外部独立交付物与 `wiki/` 影响已在第 1.1 节与 `plan.md` 第 1.7–1.8 节核对闭环。

---

## 9. 阻塞与待确认（Blockers & Open Questions） 【核心】

> 当前无阻塞问题（历史 `Q-001` 与 `DQ-1` 已闭环关闭）。

| 编号 | 问题描述 | 关联 Spec `Q-*` | 影响任务 | 责任方 | 状态 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `BQ-1` | XML/JSON 双协议共客户端路由与 Mock 同名 XML 自动转换 JSON 验收确认 | `Q-001` | `T004`, `T012`, `T015` | 网关架构组 | 已关闭 | 双协议组包、脱敏与五模式抽取全量验证通过 |

---

## 10. 变更记录（Changelog） 【补充】

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | AiCoding(codex) | 完成 `004-deterministic-tools-gateway` 初版任务拆解与归档 |
| 2.0 | 2026-11-16 | AiCoding(codex) | 按改造后中文 Spec-Kit 模板重构任务结构，补齐映射追踪、任务详情组、测试/发布/可观测矩阵与实测证据 |

---

## 附录 A：任务依赖简图

```text
Phase 1: Setup (T001, T002)
   └─▶ Phase 2: Foundational (T003, T004, T005)
          ├─▶ Phase 3: US1 (T006 ─▶ T007 ─▶ T008)
          ├─▶ Phase 4: US2 (T009 ─▶ T010 ─▶ T011)
          ├─▶ Phase 5: US3 (T012 ─▶ T013 ─▶ T014)
          └─▶ Phase 6: US4 (T015 ─▶ T016)
                    └─▶ Phase 7: Polish (T017 ─▶ T018)
```

## 附录 B：AI 执行提示

1. 编码与复核前核对 `spec.md` 第 9 节 Out of Scope 与 `plan.md` 第 1.4 节禁止修改范围，不越界改动 `domain/`、`store/`、`runner.py`/`evidence.py` 或 `frontend/`。
2. 所有已勾选 `[X]` 任务均以真实执行的测试与静态检查输出为依据，严禁虚构单独运行耗时。

---

## 增量更新说明

> 本文档依据改造后中文 Spec-Kit 模板与 `/sdd-documentation` 标准维护；后续新增或重拆任务需同步刷新第 1 节映射表与第 10 节变更记录。
