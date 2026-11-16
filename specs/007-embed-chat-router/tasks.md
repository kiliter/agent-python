---
description: "基于需求设计的 Spec Kit 实现任务清单（RA-007 嵌入式聊天选模板窗口、结构化路由智能体与增量记忆压缩系统）"
---

# 任务说明（Implementation Tasks）：嵌入式聊天选模板窗口、结构化路由智能体与增量记忆压缩系统

<!-- #Created By AiCoding(codex) -->

> **Spec Kit 使用约定**：本文件承接 `spec.md` 与 `plan.md`（`<!-- SPECKIT_PLAN_LAYOUT: inline-v1 -->` 内联四章），将设计切片转化为顺序清晰、带文件路径、可独立验证的 18 项任务清单（共 `33.0` 人天）。第 3 章权威清单已对照真实测试与构建验证证据全部勾选 `[X]` 归档。

---

## 基本信息

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-007` |
| 需求名称 | 嵌入式聊天选模板窗口、结构化路由智能体与增量记忆压缩系统 |
| 对应需求文档 | `./spec.md` |
| 对应设计文档 | `./plan.md` |
| tasks 版本 | 2.0 |
| 核算工作量 | 33.0 人天 |
| 状态 | 已完成（归档验收） |
| 负责人 | AiCoding (codex) |

---

## 0. 使用方式（给 AI 的执行指令） 【核心】

1. 按第 3 章权威任务清单顺序推进；标记 `[P]` 的任务可与同组无冲突任务并行，但不得越过前置阻塞依赖。
2. 权威复选框仅存在于第 3 章，格式为 `- [X] T001 [P?] [USx?] 描述（含精确文件路径与工时）`；其他章节仅引用 `T*` 编号，不重复建复选框。
3. 每完成一项任务，在第 3.5 节同步更新实际变更文件与真实执行的验证命令及通过输出；无实测或构建证据不得勾选完成 `[X]`。
4. 若遇需求歧义或现状冲突，停止扩大实现并登记于第 9 节 `BQ-*`，回链 `spec.md` `Q-*`。

---

## 1. 需求到任务映射（Traceability） 【核心】

| 需求/标准 ID | 摘要 | 对应设计（Plan.md） | 映射任务 ID | 测试/验证映射 | 状态 |
| --- | --- | --- | --- | --- | --- |
| US1 / SC-002 | 安全握手、双轨鉴权与 64 分片指纹演进 | 第 1.3、3–5、7 章 | `T003`、`T004`、`T006`、`T007`、`T008` | `TT-01`、`TT-02`、`TT-03` | 已验证 |
| US2 / SC-004 | 受限只读 `ChatAgent` 五动作路由与 `template-router` 自愈 | 第 3、5、6 章 | `T009`、`T010`、`T011` | `TT-03`、`TT-06` | 已验证 |
| US3 / SC-003 | 锁外异步增量滚动记忆压缩与 16 项热更配置 | 第 3、6、9 章 | `T012`、`T013`、`T014` | `TT-04` | 已验证 |
| US4 / SC-001, SC-005 | 轻量 `embed.html`（含 F2/`BrandMark`）、双视图续接、三级确认与模拟台 | 第 3、5、6、8 章 | `T002`、`T005`、`T015`、`T016` | `TT-02`、`TT-03`、`TT-05` | 已验证 |
| FR-001 | `postMessage` 握手、`lockedOrigin` 锁定与内存态 `apiKey` | 第 5、7、8 章 | `T001`、`T008` | `TT-05`、`TT-07` | 已验证 |
| FR-002 | 双轨防降级鉴权与 `X-Chat-Session-Id` 跨会话防越权 | 第 5、7 章 | `T004`、`T007` | `TT-02`、`TT-03` | 已验证 |
| FR-003 | `ChatStore` 64 分片、256 LRU 深拷贝与指纹演进清理 | 第 4、6 章 | `T003`、`T006` | `TT-01`、`TT-02`、`TT-03` | 已验证 |
| FR-004 | `ChatAgent` 4 只读工具、`ChatAction` 与 `send_message` 分发 | 第 3、5、6 章 | `T009`、`T010` | `TT-03` | 已验证 |
| FR-005 | `template-router` 33 模板编制与双向发布交叉门禁 | 第 3、10 章 | `T011`、`T018` | `TT-06` | 已验证 |
| FR-006 | 锁外滚动摘要、单调锚点、手动 `/compact` 与 16 项热更 | 第 3、6、9 章 | `T012`、`T013`、`T014` | `TT-04` | 已验证 |
| FR-007 | `ChatRunManager` 并发互斥、`shield` 取消与双游标 SSE 续接 | 第 3、5、6 章 | `T005`、`T016`、`T017` | `TT-03`、`TT-07` | 已验证 |
| FR-008 | `StepMapper` 9 类图标与 `sanitize_error_text` 全量掩码脱敏 | 第 5、7 章 | `T005`、`T017` | `TT-01`、`TT-02` | 已验证 |
| FR-009 | `confirm_run` 三级门禁、`edited`/`rewritten` 与幂等审计 | 第 3、5、6 章 | `T016`、`T017` | `TT-02`、`TT-03` | 已验证 |
| FR-010 | `embed.html` 轻量包、F2 SVG/`BrandMark`、等比舞台与模拟台 | 第 8 章 | `T002`、`T015`、`T016`、`T018` | `TT-05` | 已验证 |
| NFR-001 ~ NFR-006 | 证据隔离、锁序、`origin` 与脱敏、审计、轻量分包与沙箱兼容 | 第 7、8、11 章 | `T002`–`T018` | `TT-01`–`TT-07` | 已验证 |
| EX-001 ~ EX-006 | 改写自愈、回退旧版确认、越权探测、重启恢复、沙箱与降级 | 第 6.2 节、第 10 章 | `T006`、`T007`、`T013`、`T015`、`T016`、`T017` | `TT-02`、`TT-03`、`TT-04` | 已验证 |

### 1.1 三类独立交付物维护台账

| 独立交付物 | 涉及情况与依据 | 关联任务 | 维护状态 | 验证结果 |
| --- | --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs/Dockerfile 中） | 不生成（已存在 `docs/chat-embed-api.md`） | 不生成 | 契约已由 `T001`、`T018` 与 `tests/test_chat.py` 覆盖校验 |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs/Dockerfile 中） | 不生成 | 不生成 | `template-router/SKILL.md` 由 `test_migrated_seed.py` 校验通过 |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs/Dockerfile 中） | 不生成 | 不生成 | 16 项 `chat_*` 配置默认兜底且由 `test_chat_compaction.py` 验证 |

---

## 2. 里程碑与切分策略（Milestones） 【补充】

| 阶段 / Milestone | 目标 | 任务范围 | 阶段工时（人天） | 验收定义 |
| --- | --- | --- | --- | --- |
| Phase 1: 准备（Setup） | 聊天领域包导出、契约文档与多入口独立打包底座（含 F2/`BrandMark`） | `T001`–`T002` | 3.0 | 前后端入口与 TS/API 契约就绪 |
| Phase 2: 基础前置（Foundational） | 分片持久存储、双轨鉴权 SSE 路由与脱敏后台运行管理器 | `T003`–`T005` | 6.0 | 存储互斥锁、SSE 心跳与脱敏底座可测 |
| Phase 3: 用户故事 1（P1 🎯 MVP） | 安全握手、`X-Chat-Session-Id` 绑定与入参指纹演进 | `T006`–`T008` | 6.5 | 跨窗安全与指纹演进测试全部通过 |
| Phase 4: 用户故事 2（P1 🎯 MVP） | 受限只读 `ChatAgent` 五动作自愈与 33 模板 `template-router` | `T009`–`T011` | 6.0 | 桩模型路由自愈与发布校验零警告通过 |
| Phase 5: 用户故事 3（P2） | 锁外增量滚动记忆压缩、手动 `/compact` 与 16 项热更配置 | `T012`–`T014` | 5.5 | `tests/test_chat_compaction.py` 全通过 |
| Phase 6: 用户故事 4（P2） | 轻量嵌入 UI（`BrandMark` + 11 组件）、三级确认与双栏模拟台 | `T015`–`T016` | 3.5 | 确认幂等审计通过、`dist/embed.html` 洁净 |
| Phase 7: 收尾与门禁（Polish） | 全链路安全回归测试、静态检查与前后端类型构建验收 | `T017`–`T018` | 2.5 | `pytest`/`ruff`/`vue-tsc`/`vite build` 全过 |
| **合计** | **全周期工作量汇总** | **`T001`–`T018`（18 项）** | **33.0** | **全部交付物经实测验收闭环** |

### 2.1 依赖与交付顺序

- **阶段依赖**：Phase 1（准备） → Phase 2（基础前置，阻塞所有用户故事） → Phase 3（US1）→ Phase 4（US2）→ Phase 5（US3）与 Phase 6（US4）在底层接口与 `ChatAgent` 稳态后并行收敛 → Phase 7（收尾集成门禁）。
- **并行机会**：Phase 1 的 `T002`、Phase 2 的 `T004`/`T005`、Phase 3 的 `T008`、Phase 4 的 `T011`、Phase 5 的 `T014`、Phase 6 的 `T016` 及 Phase 7 的 `T017` 均已标注 `[P]`。

---

## 3. 任务清单（按执行顺序） 【核心】

> 格式约束：`Setup`、`Foundational`、`Polish` 阶段严禁使用 `[USx]` 标签；`User Story` 阶段必须带 `[USx]` 标签；`[P]` 位于 `Txxx` 之后、`[USx]` 之前；每条明确文件路径与工时。

### 3.1 Phase 1: Setup (Shared Infrastructure)

- [X] T001 初始化嵌入式聊天后端领域包导出接口与前后端对接契约文档，文件：`src/report_agent/chat/__init__.py`、`docs/chat-embed-api.md`（1.5 人天）
- [X] T002 [P] 配置嵌入式窗口独立多入口拆包、内联 F2 SVG 图标、轻量品牌组件与纯亮色设计令牌体系，文件：`frontend/embed.html`、`frontend/vite.config.ts`、`frontend/src/components/BrandMark.vue`、`frontend/src/embed/main.ts`、`frontend/src/embed/embed.css`、`frontend/src/embed/types.ts`（1.5 人天）

### 3.2 Phase 2: Foundational (Blocking Prerequisites)

- [X] T003 实现 `ChatStore` 会话持久化引擎（32 位 SHA-256 标识、64 分片线程锁、256 容量 LRU 深拷贝、弱引用 `_SessionLock`、路径边界防穿越与定期清理），文件：`src/report_agent/chat/store.py`（2.0 人天）
- [X] T004 [P] 搭建 `/api/v1/chat/*` FastAPI 11 端点路由、防降级双轨鉴权 `require_chat_caller` 与 15s 心跳保活通用 SSE 包装器 `_sse_chat_stream`，文件：`src/report_agent/api/routes_chat.py`（2.0 人天）
- [X] T005 [P] 实现后台运行通道管理器 `ChatRunManager`（单会话互斥、`asyncio.shield` 安全落盘与双游标重放）及 `StepMapper` 9 类图标映射与 `sanitize_error_text` 隐私脱敏，文件：`src/report_agent/chat/manager.py`、`src/report_agent/chat/steps.py`（2.0 人天）

### 3.3 Phase 3–6: User Stories (P1 → P2)

#### Phase 3: User Story 1 - 安全握手、双轨鉴权与分片持久化演进 (Priority: P1) 🎯 MVP

**目标**：交付父子窗口 `origin` 锁定握手、防跨会话探测 `runId` 校验与入参指纹无损演进机制。

**独立测试**：使用 ASGI 客户端验证 401/403/404 鉴权隔离、`inputsVersion` 递增/「用户补充」保留/旧卡片 `stale` 标记，以及前端握手超时与源校验。

- [X] T006 [US1] 实现 `ChatService` 会话生命周期核心编排（`open_session`、`get_session_view`、`inputs_fingerprint` 增量对比、保留「用户补充」、清理旧「上层」、`stale` 标记、`divider` 追加及重启 `INTERRUPTED` 自愈），文件：`src/report_agent/chat/service.py`（2.5 人天）
- [X] T007 [US1] 实现跨会话 `runId` 防越权校验 `_extract_expected_sid` 与 `resolve_session_for_run`（支持 `X-Chat-Session-Id` 头与 `?sessionId=` 绑定及不污染 LRU 的冷文件扫描），文件：`src/report_agent/api/routes_chat.py`、`src/report_agent/chat/service.py`（2.5 人天）
- [X] T008 [P] [US1] 实现内存态 `apiKey` 客户端与父子 `postMessage` 安全握手协议（500ms `chat-ready` 轮询、10s 超时兜底、`event.source` 校验、首次 `lockedOrigin` 锁定与 `initGen` 竞态防重），文件：`frontend/src/embed/chatApi.ts`、`frontend/src/embed/ChatEmbedApp.vue`（1.5 人天）

#### Phase 4: User Story 2 - 受限只读结构化路由与自愈重试 (Priority: P1) 🎯 MVP

**目标**：实现受限只读 `ChatAgent` 五动作输出自愈与全库 33 模板 `template-router` Skill 双向交叉校验。

**独立测试**：借 `FunctionModel` 桩模型验证自动首轮推荐、非 `template-router` Skill 拒载、`@agent.output_validator` 触发 `ModelRetry` 自愈与 `validate_skill` 门禁。

- [X] T009 [US2] 实现 `ChatAgent` 结构化路由智能体（`ChatAction` 五动作约束、4 只读工具 `load_skill`/`list_templates`/`get_template`/`get_run_result`、`strip_java_rule_note` 与 `@agent.output_validator` 自愈重试），文件：`src/report_agent/chat/agent.py`（2.5 人天）
- [X] T010 [US2] 实现 `ChatService.send_message` 五动作流式分发编排（自动推荐、提取 `inputs` 合并落盘、`ask_params` 正则预检、`start_run` 互斥与 `rewrite` 版本叠加及 `confirmed` 复位），文件：`src/report_agent/chat/service.py`（2.0 人天）
- [X] T011 [P] [US2] 编制覆盖 100～132 全部 33 套在线模板的 `template-router` 纯文本路由 Skill 并接入 `validate_skill` / `validate_template` 四项双向发布校验规则，文件：`src/report_agent/seed/skills/template-router/SKILL.md`、`src/report_agent/domain/resources.py`（1.5 人天）

#### Phase 5: User Story 3 - 锁外异步增量滚动记忆压缩系统 (Priority: P2)

**目标**：落地阈值触发锁外异步滚动归档、单调水位线锚点落盘、手动 `/compact` 接口及 16 项热更新配置体系。

**独立测试**：运行 `tests/test_chat_compaction.py` 验证短对话零压缩、二次滚动合并、异常退回滑窗、手动归档下限幂等保护与 `AgentRunner` `<document>` 隔离。

- [X] T012 [US3] 实现 `summarizer` 滚动记忆提炼智能体、`ChatSummaryOutput` 长度校验、`build_chat_user_prompt` 安全摘要注入与 16 项参数实时缓存刷新，文件：`src/report_agent/chat/agent.py`（2.0 人天）
- [X] T013 [US3] 实现 `ChatService` 锁外异步增量归档管道（`_persist_compaction_if_monotonic` 单调水位线与 `anchor_msg_id` 校验、自动异常退回滑窗、`_effective_memory_state` 损坏自愈与 `compact_session` 端点），文件：`src/report_agent/chat/service.py`、`src/report_agent/api/routes_chat.py`（2.0 人天）
- [X] T014 [P] [US3] 将 16 项 `chat_*` 配置项接入环境变量、运行期热更新存储及跨字段验证，并编写滚动记忆压缩专项测试套件，文件：`src/report_agent/config.py`、`src/report_agent/store/runtime_config.py`、`tests/test_chat_compaction.py`（1.5 人天）

#### Phase 6: User Story 4 - 轻量级流式嵌入前端、SSE 双视图断点续接、品牌标志与模拟联调台 (Priority: P2)

**目标**：交付零重型依赖纯亮色等比舞台与 `BrandMark` 接入、双视图 SSE 续接、三级确认审计及管理端双栏模拟联调工作台。

**独立测试**：在 `ChatSimView.vue` 打开全局保活页签联调模板预览、双视图续接、全屏分栏编辑与 `PARTIAL` 二次确认回传，核验 `dist/embed.html` 构建结果。

- [X] T015 [US4] 实现纯亮色单栏流式前端主控（`BASE_WIDTH=1280` 等比缩放舞台、顶栏 22px 与欢迎区 46px `BrandMark.vue` 集成、双游标 SSE 断线续接、归档水位线/记忆浮层、共享报告草稿及 11 个专有轻量交互组件），文件：`frontend/src/embed/ChatEmbedApp.vue`、`frontend/src/embed/markdown.ts`、`frontend/src/embed/stageToast.ts`、`frontend/src/embed/useStageFloatTip.ts`、`frontend/src/components/BrandMark.vue`、`frontend/src/embed/components/ChatInput.vue`、`frontend/src/embed/components/RecommendCard.vue`、`frontend/src/embed/components/AskParamsCard.vue`、`frontend/src/embed/components/RunCard.vue`、`frontend/src/embed/components/ReportInlineCard.vue`、`frontend/src/embed/components/RawEventsTimeline.vue`、`frontend/src/embed/components/PreviewDialog.vue`、`frontend/src/embed/components/TemplateStructureDialog.vue`、`frontend/src/embed/components/SwitchTemplateDialog.vue`、`frontend/src/embed/components/StageConfirmDialog.vue`、`frontend/src/embed/components/VersionSelect.vue`（2.0 人天）
- [X] T016 [P] [US4] 实现后端 `confirm_run` 三级门禁幂等 `chat-confirm` 审计、历史改写链接补全 `_backfill_legacy_rewrite_links`、`get_template_preview` 及管理端左右双栏模拟联调台与全幅 `v-show` 保活页签载体，文件：`src/report_agent/chat/service.py`、`frontend/src/views/ChatSimView.vue`、`frontend/src/components/ChatIframeTabPane.vue`、`frontend/src/components/ChatSimTemplatePicker.vue`（1.5 人天）

### 3.4 Phase 7: Polish & Cross-Cutting Concerns

- [X] T017 [P] 编写嵌入式聊天全链路集成测试及安全/并发/脱敏/改写回退专项审查回归测试，文件：`tests/test_chat.py`、`tests/test_review_api_chat.py`（1.5 人天）
- [X] T018 执行前后端全量自动化测试、Ruff 静态代码检查、`vue-tsc` 严格类型校验、Vite 多入口产包体积与 `dist/embed.html` 洁净度核验，文件：`src/report_agent/chat/`、`frontend/src/embed/`、`docs/chat-embed-api.md`（1.0 人天）

### 3.5 任务详情与完成记录

#### 任务组：`T001`–`T005`（契约骨架、F2 品牌入口、存储与通道底座）

- **关联需求**：`FR-001`、`FR-002`、`FR-003`、`FR-007`、`FR-008`、`FR-010`、`US1`、`US4`
- **关键变更点**：建立 `src/report_agent/chat/` 与 `/api/v1/chat/*` 11 端点骨架；配置 `frontend/vite.config.ts` 多入口拆包；在 `frontend/embed.html` 接入内联 F2 SVG data URI favicon；新增共享零重型依赖 `frontend/src/components/BrandMark.vue`（`useId()` 隔离渐变 ID）；落地 `ChatStore`（64 分片 + 256 LRU）、`ChatRunManager`、`StepMapper`（9 类图标 + `sanitize_error_text`）。
- **验证方式与实测证据**：本轮实测 `cd frontend && npx vue-tsc --noEmit -p tsconfig.app.json && npm run build` 确认 `vue-tsc` 0 错误、`3415 modules transformed`、`built in 5.80s`，构建产物 `frontend/dist/embed.html` 仅预加载 `vue-core`、`BrandMark.vue`、`markdown-lib`、`markdown`、`icons`、`timelineFormat` 等轻量化模块，完全不含 `element-plus` / `codemirror` 重型 chunk；`tests/test_chat.py#test_chat_store_and_step_mapper_unit` 在全量 `uv run pytest -q`（`196 passed in 51.41s`）中通过。
- **状态与阻塞**：已完成；无未决阻塞。

#### 任务组：`T006`–`T011`（安全握手、指纹演进、只读路由与 `template-router`）

- **关联需求**：`FR-001`～`FR-005`、`US1`、`US2`、`EX-003`
- **关键变更点**：在 `ChatService` 实现 `open_session`（`inputs_fingerprint` 增量对比与保留「用户补充」）、`resolve_session_for_run`（`X-Chat-Session-Id` 防越权）及 `send_message` 五动作分发；在 `ChatAgent` 实现 4 个只读工具与 `@agent.output_validator` 自愈；在 `seed/skills/template-router/SKILL.md` 与 `domain/resources.py` 落地 33 模板规则与 4 项交叉校验；在 `chatApi.ts` / `ChatEmbedApp.vue` 实现 `lockedOrigin` 锁定与 `initGen` 防重。
- **验证方式与实测证据**：本轮全量实测 `uv run pytest -q`（`196 passed in 51.41s`）包含 `tests/test_chat.py`（鉴权边界、指纹演进、自动推荐自愈、防越权隔离）与 `tests/test_migrated_seed.py#test_template_router_skill_coverage_and_cross_validation`（33 模板全覆盖与 4 类校验码）全部通过。
- **状态与阻塞**：已完成；无未决阻塞。

#### 任务组：`T012`–`T014`（锁外滚动记忆压缩与 16 项热更新）

- **关联需求**：`FR-006`、`US3`、`EX-006`、`NFR-001`、`NFR-002`
- **关键变更点**：新增 `ChatSummaryOutput` 与 `ChatAgent.summarize_history()`；在 `ChatService` 实现锁外压缩、`_persist_compaction_if_monotonic` 锚点校验、自动失败退回滑窗、`_effective_memory_state` 自愈及 `/compact` 手动端点；在 `config.py` 与 `runtime_config.py` 接入 16 项 `chat_*` 热更配置。
- **验证方式与实测证据**：本轮全量实测 `uv run pytest -q`（`196 passed in 51.41s`）包含 `tests/test_chat_compaction.py`（短会话零压缩、二次滚动合并、自动异常优雅退化、手动 `/compact` 下限与 504/502、损坏状态自愈及 16 项热重载、与 `AgentRunner` `<document>` 绝对隔离）全部通过。
- **状态与阻塞**：已完成；无未决阻塞。

#### 任务组：`T015`–`T018`（纯亮色前端、`BrandMark` 接入、确认审计与全量门禁）

- **关联需求**：`FR-007`～`FR-010`、`US4`、`EX-001`、`EX-002`、`EX-004`、`EX-005`
- **关键变更点**：`ChatEmbedApp.vue` 在顶栏（`:size="22"`）与空会话欢迎区（`:size="46"`）接入 `BrandMark.vue`，实现等比舞台、11 个专有轻量组件、归档水位分隔线、记忆摘要浮层与双游标续接；`ChatService` 落地 `confirm_run` 三级确认幂等审计与 `_backfill_legacy_rewrite_links` 历史改写自愈；管理端落地 `ChatSimView.vue`、`ChatIframeTabPane.vue`、`ChatSimTemplatePicker.vue`。
- **验证方式与实测证据**：
  1. `uv run pytest -q`：全量 `196 passed in 51.41s`（覆盖 `tests/test_chat.py`、`tests/test_chat_compaction.py`、`tests/test_review_api_chat.py`、`tests/test_migrated_seed.py`）。
  2. `uvx ruff@0.11.0 check src tests`：`All checks passed!`。
  3. `cd frontend && npx vue-tsc --noEmit -p tsconfig.app.json && npm run build`：`vue-tsc` 0 错误、`3415 modules transformed`、`built in 5.80s`、`dist/embed.html` 洁净无重型 chunk（`embed` JS 108K / CSS 80K / `BrandMark` 4.2K）。
- **状态与阻塞**：已完成；无未决阻塞。

---

## 4. 子任务拆解（可选） 【补充】

本需求 `T001`–`T018` 任务粒度已适中且各含清晰文件边界与实测证据，无需额外子任务拆解。

---

## 5. 代码实现约束（仅本需求新增） 【补充】

- **并发与一致性**：`ChatStore` 严格遵从 `_stripe_lock(sid) -> _cache_guard` 固定锁序，`aget()`/`save()`/`asave()` 均返回 `copy.deepcopy`；大模型调用与摘要压缩一律在 `_SessionLock` 锁外执行，落盘校验 `cutoff > cur_up_to` 与 `anchor_msg_id`；`ChatRunManager.start()` 返回前同步写入 `_channels` 与 `_active_by_session`。
- **安全与隐私边界**：`require_chat_caller` 优先检非空 `X-API-Key` 阻断降级；`postMessage` 锁定 `event.source` 与 `lockedOrigin`、`apiKey` 仅留内存；`StepMapper.sanitize_error_text` 掩码所有密钥/引号字面量/路径/长数字且截断至 120 字；`frontend/src/embed/` 严禁导入 `element-plus` / `codemirror`。
- **错误与降级语义**：跨会话探测 `runId` 统一返 `404 RUN_NOT_FOUND`；自动压缩异常无感退回滑窗，手动压缩超限/失败返回 `504 CHAT_COMPACT_TIMEOUT` / `502 CHAT_COMPACT_ERROR`；服务重启残留 `RUNNING` 自动自愈为 `INTERRUPTED`。

---

## 6. 测试任务矩阵（Test Tasks） 【核心】

| 测试编号 | 类型 | 测试场景与关注点 | 关联任务 | 测试路径 | 验证命令与结果 |
| --- | --- | --- | --- | --- | --- |
| TT-01 | 单元测试 | `ChatStore` 64 分片/缓存/清理与 `StepMapper` 9 类图标及隐私掩码 | `T003`、`T005` | `tests/test_chat.py` | `uv run pytest -q`（全量 `196 passed in 51.41s`，已通过） |
| TT-02 | 安全/边界测试 | 双轨防降级鉴权、跨会话 `runId` 隔离、`rewrite` 后回退 `v1` 再确认与冷扫描并发 | `T004`、`T007`、`T016`、`T017` | `tests/test_review_api_chat.py`、`tests/test_chat.py` | `uv run pytest -q`（全量 `196 passed in 51.41s`，已通过） |
| TT-03 | 端到端集成测试 | 握手/指纹演进、路由自愈、双游标 SSE 续接、原样记录、取消与三级确认幂等审计 | `T006`、`T009`、`T010`、`T016`、`T017` | `tests/test_chat.py` | `uv run pytest -q`（全量 `196 passed in 51.41s`，已通过） |
| TT-04 | 滚动压缩专项测试 | 短会话零压缩、二次滚动合并、失败退化、手动 `/compact`、损坏自愈、热更与隔离 | `T012`、`T013`、`T014` | `tests/test_chat_compaction.py` | `uv run pytest -q`（全量 `196 passed in 51.41s`，已通过） |
| TT-05 | 前端类型与分包构建 | 严格 TS 类型检查、`embed.html` 剥离重依赖及 F2/`BrandMark` 产包验证 | `T002`、`T008`、`T015`、`T018` | `frontend/src/embed/`、`frontend/embed.html` | `cd frontend && npx vue-tsc --noEmit -p tsconfig.app.json && npm run build`（0 错误，`3415 modules transformed`，`built in 5.80s`，`dist/embed.html` 洁净无重型 chunk） |
| TT-06 | 资源路由交叉回归 | `template-router` 33 模板全覆盖与 `ROUTER_*` 4 项报错/警告规则 | `T011`、`T018` | `tests/test_migrated_seed.py` | `uv run pytest -q`（全量 `196 passed in 51.41s`，已通过） |
| TT-07 | 代码静态门禁 | Python 后端与测试集规范风格静态扫描 | `T018` | `src/`、`tests/` | `uvx ruff@0.11.0 check src tests`（`All checks passed!`） |

---

## 7. 发布任务清单（Release Tasks） 【核心】

| 发布编号 | 动作内容 | 前置依赖 | 验证与完成标准 | 回滚动作 | 关联任务 |
| --- | --- | --- | --- | --- | --- |
| RT-01 | 后端全量单测、Ruff 门禁与前端多入口生产打包收敛 | `T001`–`T017` | `196 passed`、`ruff` 0 告警、`vue-tsc` 0 错误、`dist/embed.html` 洁净无重型 chunk | 代码版本回退 | `T018` |
| RT-02 | 发布包含 `template-router` 的线上快照至 `releases/current` | `RT-01` | `validate_all()` 达到 `0 errors, 0 warnings` | `releases/current` 切回上一 `rN` | `T011`、`T018` |
| RT-03 | 单进程（`workers=1`）启动校验 `/healthz`、`/embed.html` 与 16 项热更新配置 | `RT-02` | 健康检查通过、模拟联调台完成握手/填报/回传闭环 | 配置回滚 `cN` 或容器镜像回退 | `T014`、`T016`、`T018` |

---

## 8. 可观测性与验收（Observability & Acceptance） 【补充】

### 8.1 关键过程事件、日志与审计点位

| 场景 | 载体（过程事件 / 日志 / 审计） | 关键上下文字段 | 隐私脱敏约束 |
| --- | --- | --- | --- |
| 对话路由与记忆压缩 | SSE `status` & `logging` | `sid`、压缩状态提示、脱敏异常原因 | 警告日志与错误信息经 `sanitize_error_text` 掩码，不记录密钥与单据正文 |
| 后台运行双视图流 | SSE `step` & `raw` & `final` / `error` | `seq`、`icon`、`runId`、`status`、`missingShown` | `StepMapper` 屏蔽模型思考事件，掩码 Bearer/Key/引号参数/路径/长数字 |
| 报告确认回传 | `DATA_DIR/audit.jsonl` | `action="chat-confirm"`、`operator`（`caller.name`）、`sessionId`、`runId`、`edited`、`rewritten` | 严禁采信前端提交操作人字段；幂等重放不重复写盘 |

### 8.2 验收清单

- 全部 18 项权威任务（`33.0` 人天）已依据 `pytest`、`ruff`、`vue-tsc`、`vite build` 真实通过证据完成核验。
- `spec.md`、`plan.md`、`tasks.md` 全量追溯映射覆盖 `US1`–`US4`、`FR-001`–`FR-010`、`SC-001`–`SC-005`、`NFR-001`–`NFR-006` 与 `EX-001`–`EX-006`。
- `frontend/embed.html` 内联 F2 品牌图标与 `ChatEmbedApp.vue` 复用 `BrandMark.vue` 事实已完整同步。
- 已有 `wiki/components/chat-embed.md` 与 `docs/chat-embed-api.md` 同步一致，三类独立交付物台账已核准不额外生成空文件。

---

## 9. 阻塞与待确认（Blockers & Open Questions） 【核心】

当前无阻塞问题（历史 `Q-001`、`Q-002` 均已澄清关闭，详见 `spec.md` 第 11 节）。

| 编号 | 问题描述 | 关联 Spec Q-* | 影响任务 | 责任方 | 状态 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| BQ-1 | 无未关闭阻塞事项 | `Q-001`, `Q-002` | 无 | 项目团队 | 已关闭 | `F2`/`BrandMark` 轻量复用及单进程 `workers=1` 部署边界均已最终确认闭合 |

---

## 10. 变更记录（Changelog） 【补充】

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | AiCoding (codex) | 完成 007 子规格 18 项任务拆解与 33.0 人天验收归档 |
| 2.0 | 2026-11-16 | AiCoding (codex) | 按改造后中文 Spec-Kit 任务模板重整为第 0～10 章规范结构，严格统一第 3 章任务清单格式与工时配比，并同步 `embed.html`/`BrandMark.vue` 接入与最新全量实测验收证据 |

---

## 附录 A：任务依赖简图

```text
Phase 1 Setup (T001, T002)
  └──> Phase 2 Foundational (T003, T004, T005)
         ├──> Phase 3 US1 (T006 → T007, T008)
         │      └──> Phase 4 US2 (T009 → T010, T011)
         │             ├──> Phase 5 US3 (T012 → T013, T014)
         │             └──> Phase 6 US4 (T015, T016)
         └──────────────────────────┴──> Phase 7 Polish (T017, T018)
```

## 附录 B：AI 执行提示

1. 编码与审查前先核对 `spec.md` 第 9 节 Out of Scope 与 `plan.md` 第 1.4 节禁止修改范围（严禁在 `src/embed/` 引入重型依赖或修改 `tests/conftest.py` 隔离边界）。
2. 所有已勾选 `[X]` 任务均具备真实测试/构建命令验证证据，若后续修改 `chat/` 或 `embed/` 源码，须重新执行 TT-01～TT-07 门禁后方可重新签收。

---

## 增量更新说明

> 本文档依据改造后中文 Spec-Kit 模板与 `/sdd-documentation` 标准维护；后续新增聊天能力或重拆任务时须同步刷新第 1 节映射表、第 3.5 节实测记录与第 10 节变更记录。
