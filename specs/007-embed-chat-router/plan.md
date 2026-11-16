# 设计文档（Feature Design Spec）：嵌入式聊天选模板窗口、结构化路由智能体与增量记忆压缩系统

<!-- #Created By AiCoding(codex) -->
<!-- SPECKIT_PLAN_LAYOUT: inline-v1 -->

> **Spec Kit 使用约定**：本文件采用**单文件内联布局（inline-v1）**，研究决策、领域与存储模型、内部接口契约及验证指南全部内联维护在本文件四个锚点章节中，不另建 `research.md`、`data-model.md`、`contracts/` 或 `quickstart.md`。经核查 `spec.md` 第 8.2 节确认不额外生成三类外部独立交付物。

---

**分支**：`[007-embed-chat-router]` | **日期**：2026-11-16 | **规格**：`./spec.md`

**输入**：`/specs/007-embed-chat-router/spec.md`

## 基本信息

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-007` |
| 需求名称 | 嵌入式聊天选模板窗口、结构化路由智能体与增量记忆压缩系统 |
| 对应需求文档 | `./spec.md` |
| 对应任务清单 | `./tasks.md` |
| 设计文档版本 | 2.0 |
| 设计人 | AiCoding (codex) |
| 核算工作量 | 33.0 人天 |
| 状态 | 已交付归档 |

---

## 1. 设计目标与范围 【核心】

### 1.1 设计目标（What / Why）

- **PLAN-GOAL-1**：面向外部工单系统构建安全零耦合的嵌入式聊天入口（`/embed.html` + `/api/v1/chat/*`），实现 `postMessage` 锁定来源握手、双轨防降级鉴权、64 分片会话持久化与指纹无损演进，达成 `SC-001`、`SC-002` 与 `SC-005`。
- **PLAN-GOAL-2**：建立严格只读隔离的 `ChatAgent` 结构化路由智能体（4 只读工具 + `@agent.output_validator` 自愈重试 + 全库 33 模板 `template-router` Skill 双向交叉校验）与锁外异步增量滚动记忆压缩（16 项热更参数），达成 `SC-003` 与 `SC-004` 且零侵入 `AgentRunner` 强证据域。
- **PLAN-GOAL-3**：交付纯亮色极简多入口前端（内联 F2 SVG favicon + `BrandMark.vue` 轻量品牌组件 + 11 个自定义组件 + 等比缩放舞台）及管理端左右双栏模拟联调台，实现从选模板、补参、双视图 SSE 断点续接到三级确认幂等审计的全栈闭环。

### 1.2 设计范围（Scope）

**包含：**

- 后端域 `src/report_agent/chat/`（`__init__.py`、`store.py`、`agent.py`、`manager.py`、`steps.py`、`service.py`）与 API 路由 `src/report_agent/api/routes_chat.py`（11 个端点）。
- `src/report_agent/seed/skills/template-router/SKILL.md` 及 `src/report_agent/domain/resources.py` 路由双向校验规则。
- `src/report_agent/config.py` 与 `src/report_agent/store/runtime_config.py` 中 16 项 `chat_*` 运行期热更新参数体系。
- 前端独立多入口 `frontend/embed.html`、`frontend/vite.config.ts`、`frontend/src/components/BrandMark.vue`、`frontend/src/embed/*`（根控 `ChatEmbedApp.vue` + 7 辅助模块 + 11 个专有组件）及管理端 `ChatSimView.vue`、`ChatIframeTabPane.vue`、`ChatSimTemplatePicker.vue`。
- 对接契约 `docs/chat-embed-api.md` 与测试套件 `tests/test_chat.py`、`tests/test_chat_compaction.py`、`tests/test_review_api_chat.py`。

**不包含：**

- 核心报告填报管道 `AgentRunner`、12 个确定性原语、网关连接器与通用工作台 9 大管理视图（由 001～006 归属覆盖）。
- 外部工单宿主系统的自有前端业务页面改造。
- 脱离单进程内存协调架构引入 Redis 或关系型数据库集群。

<a id="plan-research"></a>

### 1.3 研究与关键决策（Decision Log）

| ID | 决策点 | 备选方案 | 最终选择 | 依据与取舍理由 | 影响范围 |
| --- | --- | --- | --- | --- | --- |
| D1 | 跨窗通信与凭证存放 | URL Query 传 Key / Cookie 共享 / `localStorage` | `postMessage` 校验 `event.source` + 锁定首个 `lockedOrigin`，`apiKey` 仅存前端闭包的内存变量并受单调 `initGen` 保护 | 防止恶意弹窗伪造指令，杜绝密钥落入浏览器历史或持久存储，消灭快速切单异步竞态 | `ChatEmbedApp.vue`, `chatApi.ts`, `docs/chat-embed-api.md` |
| D2 | 双轨鉴权与防越权校验 | 仅传 Cookie fallback 或不绑 `sessionId` | 显式 `X-API-Key` 优先校验防 Cookie 降级劫持；`draft` 严格限 `caller.kind=="user"`；`/runs/*` 强校验 `X-Chat-Session-Id`/`?sessionId=` 并统一报 `404 RUN_NOT_FOUND` | 阻断同源环境下失效 Key 借管理员 Cookie 越权以及跨会话探测 `runId` 的安全隐患 | `routes_chat.py`, `chat/service.py` |
| D3 | 会话并发读写与大模型隔离 | 全局单锁 / 持有会话锁调大模型 | `ChatStore` 64 分片线程锁 + 256 LRU 深拷贝 + 有界弱引用 `_SessionLock`；LLM 推理及滚动摘要均在锁外异步执行，落盘重入锁校验锚点 | 命中缓存零磁盘 I/O 零线程切换；防止耗时模型阻塞心跳、并发写回覆盖或唤醒过期视图 | `chat/store.py`, `chat/service.py` |
| D4 | 路由隔离与防幻觉策略 | 直接透传网关工具给聊天助手 | `ChatAgent` 仅开放 4 个只读工具（`load_skill` 锁定 `template-router`），`ChatAction` + `@agent.output_validator` 触发 `ModelRetry` 自愈 | 物理隔断网关写与填报工具；实时修正下线模板、多卡歧义及空正文改写；`rewrite` 复位 `confirmed=false` | `chat/agent.py`, `seed/skills/template-router/` |
| D5 | 滚动记忆摘要一致性 | 无压缩无限塞历史 / 直接截断丢早期对话 | 达阈值（默认 24）锁外 `summarize_history`，重入锁验证 `cutoff > cur_up_to` 与 `anchor_msg_id` 单调落盘；自动失败无缝退回滑窗；摘要仅前置注入聊天提示词 | 保证长对话背景连贯性，防止异步摘要覆盖新对话，同时物理隔离 `AgentRunner` `<document>` 证据域 | `chat/agent.py`, `chat/service.py` |
| D6 | 嵌入页拆包与品牌图标引入 | 共用工作台单包（含 Element Plus）或外链图标请求 | Vite 多入口拆包将 `embed.html` 彻底剥离重型依赖；`embed.html` 内联 F2 SVG data URI favicon，`ChatEmbedApp.vue` 复用轻量 `BrandMark.vue`（4.2KB）并挂载全部浮层弹窗于 `.embed-stage` | `embed` 首屏 JS/CSS 体积缩减约 80%，兼顾与工作台品牌视觉统一和零额外资源网络往返 | `frontend/embed.html`, `frontend/vite.config.ts`, `BrandMark.vue`, `ChatEmbedApp.vue` |

---

### 1.4 技术背景与项目结构

**语言/版本**：Python `>=3.12,<3.14`（运行时 `3.13`）、TypeScript `5.8`（`tsconfig.app.json` 严格模式）、Vue `3.5`（`<script setup lang="ts">`）

**主要依赖**：FastAPI `>=0.115`、`pydantic-ai-slim[openai]==2.67.0`、Pydantic `>=2.12`、Vite `6`（Rollup 多入口 `manualChunks`）、`marked`、`lucide-vue-next`、Element Plus（仅管理端模拟台使用）

**存储**：`DATA_DIR/chats/<sid[:2]>/<sid>.json`（64 分片 JSON + 256 LRU 深拷贝）、`DATA_DIR/audit.jsonl` 只追加审计日志、`DATA_DIR/config/runtime/current.json`（`0600` 热更新配置）、`RunStore` 异步运行档案及内存态 `_RunChannel`

**测试**：`pytest` + `httpx.AsyncClient`（ASGI）+ `FunctionModel` 桩模型（`tests/test_chat.py`、`tests/test_chat_compaction.py`、`tests/test_review_api_chat.py`）、`ruff@0.11.0`、`vue-tsc --noEmit` 与 Vite 多入口产包校验

**目标平台**：Linux 容器 / macOS 本地开发环境单进程 Uvicorn（`workers=1`）+ 现代桌面浏览器（外部系统内嵌 `iframe` 及管理端模拟页签）

**项目类型**：全栈模块（FastAPI REST/SSE 领域服务 + Vue 3 独立轻量嵌入式前端 + 管理端模拟工作台集成）

**约束与规模/范围**：后端 6 个 `chat/` 核心模块（3,534 行）+ `routes_chat.py`（326 行）+ 1 份 33 模板 `template-router` Skill + 16 项热更参数；前端 1 个独立入口 + 轻量 `BrandMark.vue` + 8 个 `embed/` 主控/工具文件 + 11 个交互组件 + 3 个管理端模拟组件；3 套自动化测试文件（3,326 行），总核算 `33.0` 人天

**源代码结构（真实目录落点）**：

```text
src/report_agent/
├── api/
│   └── routes_chat.py                          # /api/v1/chat/* 11 个 REST/SSE 路由、双轨鉴权与跨会话校验
├── chat/
│   ├── __init__.py                             # 包导出契约（ChatAgent, ChatRunManager, ChatService, ChatStore, StepMapper）
│   ├── store.py                                # 64 分片文件锁、256 LRU 深拷贝、弱引用协程锁与 SHA-256 会话/指纹
│   ├── agent.py                                # ChatAgent、ChatAction、4 只读工具、summarizer 滚动摘要与 cfg_int/cfg_float
│   ├── manager.py                              # ChatRunManager 单会话互斥、_RunChannel 双游标广播/重放与 shield 取消
│   ├── steps.py                                # StepMapper 9 类图标映射与 sanitize_error_text 隐私掩码脱敏
│   └── service.py                              # ChatService 生命周期、指纹演进、锁外压缩、动作分发、历史补全与确认审计
├── domain/resources.py                         # validate_skill / validate_template 对 template-router 双向校验
├── config.py / store/runtime_config.py         # 16 项 chat_* 热更新参数定义、跨字段校验与配置快照发布
└── seed/skills/template-router/SKILL.md        # 33 套在线模板（100~132）纯文本路由规则库

frontend/
├── embed.html                                  # 轻量级嵌入式独立 HTML 入口（内联 F2 SVG data URI favicon）
├── vite.config.ts                              # 多入口（index + embed）与 8 个 manualChunks 拆包隔离
└── src/
    ├── components/
    │   ├── BrandMark.vue                       # F2 智能光笔写单轻量 SVG 组件（useId 隔离渐变、零重型依赖）
    │   ├── ChatIframeTabPane.vue               # 管理端顶部全局页签全幅 v-show 保活 iframe 容器
    │   └── ChatSimTemplatePicker.vue           # 模板示例与回归用例一键预填参数/单据弹窗
    ├── views/ChatSimView.vue                   # 管理端左右双栏模拟联调工作台（postMessage 日志 + 回传结果）
    └── embed/
        ├── main.ts / embed.css / types.ts      # 纯亮色引导入口、设计令牌与完整 TS 类型契约
        ├── chatApi.ts / markdown.ts            # 内存态 apiKey/sessionId、SSE 解析与安全渲染复用
        ├── stageToast.ts / useStageFloatTip.ts # 挂载于等比舞台内的轻提示与防裁剪浮层定位工具
        ├── ChatEmbedApp.vue                    # 安全握手、等比舞台、BrandMark 顶栏/欢迎区接入与双视图流控主控
        └── components/                         # 11 个零重型依赖自定义子组件
            ├── ChatInput.vue                   # 24px 圆角悬浮输入舱（防 IME 组字回车误触发）
            ├── RecommendCard.vue               # 单外框多列推荐卡（搜索筛选 + 缺参角标 + 一键运行/预览）
            ├── AskParamsCard.vue               # 双列补参表单与安全正则预检
            ├── RunCard.vue                     # 可折叠双视图步骤卡片 + 内联报告容器
            ├── ReportInlineCard.vue            # 行内报告卡（版本切换 + AI 改写未校验标识）
            ├── RawEventsTimeline.vue           # 按轮次聚合的原样过程事件时间线（markRaw 优化）
            ├── PreviewDialog.vue               # 三态（预览/源码/左右分栏）全屏报告审阅弹窗
            ├── TemplateStructureDialog.vue     # 填充样例 / Jinja2 原稿 / 入参字段三栏检查器弹窗
            ├── SwitchTemplateDialog.vue        # 全部模板检索与推荐优先排序弹窗
            ├── StageConfirmDialog.vue          # 舞台内 PARTIAL 缺失二次确认与丢弃微调确认框
            └── VersionSelect.vue               # 跟随等比舞台坐标系自适应的轻量版本下拉选择器

docs/chat-embed-api.md                          # 前后端与外部宿主系统集成对接权威契约
tests/
├── test_chat.py                                # 全链路测试（鉴权、指纹演进、路由自愈、续接、预览、原样、确认审计）
├── test_chat_compaction.py                     # 滚动记忆压缩测试（阈值触发、二次合并、失败退化、手动归档与隔离）
└── test_review_api_chat.py                     # 审查专项回归（防 Key 降级劫持、回退版本确认、缓存并发与脱敏边界）
```

**禁止修改范围**：

- 严禁改动 `tests/conftest.py` 的全局 `SEED_DIR` 隔离机制；严禁在 `src/report_agent/chat/` 中硬编码特定模板 ID 或引入网关调用工具；严禁在 `frontend/src/embed/` 导入 `element-plus` / `codemirror` / `pinia` / `vue-router`。

#### 文档结构（本需求）

```text
specs/007-embed-chat-router/
├── spec.md    # specify/clarify：需求规格、范围边界、F2/BrandMark 与验收标准
├── plan.md    # plan：研究决策、模型、内部契约与验证指南（inline-v1）
└── tasks.md   # tasks：可执行任务清单、测试矩阵与实测验收证据
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
| 原则 I：平台零业务硬编码与声明式资源隔离 | PASS | PASS | 33 模板分流规则完全封装于 `seed/skills/template-router/SKILL.md`，平台源码无任何模板号/业务规则硬编码 |
| 原则 II：单智能体规划、确定性原语与强证据防幻觉 | PASS | PASS | `ChatAgent` 限 4 只读工具 + `@agent.output_validator`；`memorySummary` 与 `AgentRunner` `<document>` 彻底隔离；`rewrite` 标示未校验 |
| 原则 III：文件化 Git 原子发布与单进程并发安全（`workers=1`） | PASS | PASS | `ChatStore` 64 分片锁 + 固定锁序 + `write_json` 原子写；`ChatService` 锁外调模型、锁内校验 `anchor_msg_id`；`ChatRunManager` 零竞态登记 |
| 原则 IV–V：单文件内联设计、自动化测试隔离与 Mock 契约 | PASS | PASS | `plan.md` 采用 `inline-v1`；3 套测试使用 `FunctionModel` 与 ASGI 隔离夹具覆盖全分支且无外网模型请求；`embed.html` 保持纯净分包 |
| 原则 VI–VII：安全脱敏、零硬编码凭证、事件与审计留痕 | PASS | PASS | `origin` 锁定、`apiKey` 仅存内存、`require_chat_caller` 防降级、`StepMapper` 全量脱敏、`chat-confirm` 服务端身份记入 `audit.jsonl` |
| 原则 VIII–X：最小改动、代码规范、Wiki 同步及三类外部交付物确认 | PASS | PASS | 已有 `wiki/components/chat-embed.md` 与 `docs/chat-embed-api.md` 同步齐备；三类外部独立交付物已核对确认不重复生成 |

### 1.6 复杂度跟踪

无（严格遵守项目宪章与既有架构约束；仅通过 Vite 多入口分包将 `embed.html` 与重型工作台隔离，且遵循 `workers=1` 单进程协同模型）。

### 1.7 Wiki 影响评估

- **结论**：涉及（相关架构与组件规范已同步沉淀于 `wiki/` 既有页面，本轮 SDD 三件套重构归档不再重复修改 `wiki/`）
- **受影响页面**：`wiki/components/chat-embed.md`、`wiki/skills/template-router.md`、`wiki/components/api-and-auth.md`、`wiki/components/workbench-frontend.md`、`wiki/reference/configuration.md`
- **同步项**：对应 `wiki/index.md` 登记及 `wiki/log.md` 演进记录均已同步完成。

### 1.8 三类独立交付物设计检查

| 独立交付物 | 涉及情况与依据 | 设计与变更摘要 | 验证与回退设计 | 关联问题 |
| --- | --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs/Dockerfile 中） | `docs/chat-embed-api.md` 已作为对外 `postMessage` 与 `/api/v1/chat/*` 权威契约存在 | 由 `tests/test_chat.py` 校验端点与数据结构对齐 | 无 |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs/Dockerfile 中） | 仅含新增纯文本 `template-router/SKILL.md`，不涉及迁移规则脚本 | 由 `test_migrated_seed.py` 覆盖校验 33 模板 | 无 |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs/Dockerfile 中） | 16 项 `chat_*` 参数默认内置兜底且由既有 `.env.example` 与配置中心托管 | 由 `test_chat_compaction.py` 与 `RuntimeConfig` 单测覆盖 | 无 |

---

## 2. 需求映射（Traceability） 【核心】

| 规格编号 | 类型 | 需求摘要 | 设计章节映射 | 后续任务映射 |
| --- | --- | --- | --- | --- |
| US1 / SC-002 | 用户故事 | 安全握手、双轨鉴权与 64 分片指纹演进 | 第 1.3 节、第 3–5、7 章 | `T003`、`T004`、`T006`、`T007`、`T008` |
| US2 / SC-004 | 用户故事 | 受限只读 `ChatAgent` 五动作路由与 `template-router` 自愈 | 第 3、5、6 章 | `T009`、`T010`、`T011` |
| US3 / SC-003 | 用户故事 | 锁外异步增量滚动记忆压缩与 16 项热更配置 | 第 3、6、9 章 | `T012`、`T013`、`T014` |
| US4 / SC-001, SC-005 | 用户故事 | 轻量 `embed.html`（含 F2/`BrandMark`）、双视图续接、三级确认与模拟台 | 第 3、5、6、8 章 | `T002`、`T005`、`T015`、`T016` |
| FR-001 | 功能需求 | `postMessage` 双向安全握手与内存凭证 `initGen` 防重 | 第 5、7、8 章 | `T001`、`T008` |
| FR-002 | 功能需求 | 双轨防降级鉴权与 `X-Chat-Session-Id` 跨会话防越权 | 第 5、7 章 | `T004`、`T007` |
| FR-003 | 功能需求 | `ChatStore` 64 分片、256 LRU 深拷贝与指纹演进清理 | 第 4、6 章 | `T003`、`T006` |
| FR-004 | 功能需求 | `ChatAgent` 4 只读工具、`ChatAction` 验证与 `send_message` 分发 | 第 3、5、6 章 | `T009`、`T010` |
| FR-005 | 功能需求 | `template-router` 全 33 模板编制与 4 类双向交叉校验 | 第 3、10 章 | `T011`、`T018` |
| FR-006 | 功能需求 | 锁外异步滚动摘要、单调落盘、手动 `/compact` 与 16 项热更 | 第 3、6、9 章 | `T012`、`T013`、`T014` |
| FR-007 | 功能需求 | `ChatRunManager` 并发互斥、`shield` 取消、双游标续接与重启恢复 | 第 3、5、6 章 | `T005`、`T016`、`T017` |
| FR-008 | 功能需求 | `StepMapper` 9 类图标与 `sanitize_error_text` 全量脱敏 | 第 5、7 章 | `T005`、`T017` |
| FR-009 | 功能需求 | `confirm_run` 三级门禁、`edited`/`rewritten` 判定与幂等 `chat-confirm` | 第 3、5、6 章 | `T016`、`T017` |
| FR-010 | 功能需求 | `embed.html` 轻量包、F2 SVG/`BrandMark`、等比舞台与模拟联调台 | 第 8 章 | `T002`、`T015`、`T016`、`T018` |
| NFR-001 ~ NFR-006 | 非功能需求 | 证据隔离、锁序、`origin` 与脱敏、审计、轻量分包与沙箱兼容 | 第 7、8、11 章 | `T002`–`T018` |
| EX-001 ~ EX-006 | 异常边界 | 改写链接自愈、回退旧版确认、越权探测、重启自愈、沙箱兼容与退化 | 第 6.2 节、第 10 章 | `T006`、`T007`、`T013`、`T015`、`T016`、`T017` |

---

<a id="plan-data-model"></a>

## 3. 核心领域模型（Domain Model） 【核心】

### 3.1 领域对象清单

| 对象 / 类 | 所在文件 | 职责与核心属性 | 关键不变量（Invariant） |
| --- | --- | --- | --- |
| `ChatSession` | `src/report_agent/chat/store.py` & `service.py` | 持久会话实体，含 `sessionId`、`userId`、`orderId`、`target`、`inputs`/`inputSources`、`inputsVersion`、`document`、`fingerprint`、`memorySummary`、`summarizedUpTo`、`recommended`、`confirmed`、`confirmRecords`、`messages` | `sessionId` 为 `SHA-256(userId+"\x00"+orderId)[:32]`；对外 `_build_view` 剥离 `document` 与 `fingerprint` |
| `ChatAction` / `RecommendPick` | `src/report_agent/chat/agent.py` | `ChatAgent` 单轮严格结构化输出（`extra="forbid"`），含 `action` 枚举、`text`、`recommendations`（≤3）、`templateId`、`inputs` 字典、`runId`、`markdown` | 仅可推荐在线模板且不重复；`rewrite` 仅可作用当前会话 `SUCCESS`/`PARTIAL` 且有版本卡片 |
| `ChatSummaryOutput` | `src/report_agent/chat/agent.py` | `summarizer` 智能体滚动摘要输出模型，含非空 `summary` 字段 | 长度严控不超过 `chat_max_memory_summary_chars`（超出裁切带省略号）；严禁充当填报证据 |
| `RunCompletion` / `_RunChannel` | `src/report_agent/chat/manager.py` | 管理单次聊天后台运行的异步事件通道，持有 `StepMapper`、`raw_events`、`asyncio.Condition`、`task` 及 `finished_mono` | 单会话同时最多 1 条活跃通道；返回 `run_id` 前完成登记消除订阅竞态 |
| `RunCard` / `ReportVersion` | `src/report_agent/chat/service.py` & `frontend/src/embed/types.ts` | 会话消息内嵌报告运行实例，记录 `status`、`stale`、`templateOffline`、`missingShown`、`versions`（`v1=original`，后续 `rewrite`）与 `confirmed` | 追加 `rewrite` 版本时必须复位 `confirmed=false`；已下线模板可确认禁重跑 |
| `ChatCaller` / `ChatError` | `src/report_agent/chat/service.py` | 调用方身份值对象（`kind="user"|"key"`, `name`）与带状态码/错误码的领域异常 | `target="draft"` 仅限 `caller.kind == "user"`；所有校验错误统一映射规范错误码 |

### 3.2 状态机（如适用）

```text
# 后台运行卡片状态流转：
[发起 start_run] --> RUNNING
  RUNNING --(runner 全部展示字段 found)--> SUCCESS
  RUNNING --(runner 存在缺失展示字段)--> PARTIAL
  RUNNING --(入参校验失败/运行异常)--> FAILED
  RUNNING --(用户 cancel_run 取消)--> CANCELLED
  RUNNING --(进程重启后 _RunChannel 丢失)--> INTERRUPTED

# 前端嵌入页连接阶段流转：
[挂载校验 query] --(缺 userId/orderId)--> invalid
[挂载校验通过] --> waiting (每500ms发送 chat-ready)
  waiting --(10s 超时未收 chat-init)--> no-init
  waiting --(收到合法 chat-init)--> loading --(POST /sessions 成功)--> ready
  loading --(接口报错)--> error
```

---

## 4. 数据与存储设计（本需求范围） 【核心】

### 4.1 存储与缓存对象概览

| 对象/路径 | 变更类型 | 数据格式与字段要点 | 并发/清理/恢复策略 | 关联需求 |
| --- | --- | --- | --- | --- |
| `DATA_DIR/chats/<sid[:2]>/<sid>.json` | 新增 | UTF-8 JSON 会话全量字典（含 `confirmRecords` 与内部 `document`/`fingerprint`） | 64 分片线程互斥 + `_stripe_lock -> _cache_guard` 固定锁序 + `write_json`（`fsync + os.replace`）；按 `RUNS_KEEP_DAYS` 自动清理文件与空分片目录 | FR-003 |
| `ChatStore._cache` & `_locks_weak` | 新增（内存） | 256 容量 `OrderedDict` LRU 缓存；弱引用 + 最近 512 强引用 `_SessionLock` 协程锁池 | 读写均返回 `copy.deepcopy` 隔离外部原地修改；命中心缓存免磁盘 I/O 与免切线程；`cleanup` 跳过锁定中会话并同步驱逐缓存 | FR-003 |
| `_RunChannel` 内存通道池 | 新增（内存） | 256 容量 `OrderedDict`，保存 `steps` 与 `raw_events` 双序列表 | 已完成通道保留 `600s`；淘汰或进程重启后回退 `ChatStore` 与 `RunStore` 持久化查询 | FR-007 |
| `_run_to_session` 索引 | 新增（内存） | 4096 容量 `OrderedDict`（`runId -> sessionId`） | 缓存未命中时通过 `_scan_sessions_for_run` + `has_run_id` 冷扫描且不污染 LRU | FR-002 |
| `DATA_DIR/audit.jsonl` | 修改 | 只追加 JSON Lines，新增 `action="chat-confirm"` 记录 | 经 `Publisher.audit` 写盘，操作人取自 `caller.name`，幂等重放不重复写 | FR-009 |

---

<a id="plan-contracts"></a>

## 5. 接口与契约设计（API / Tools / Events） 【核心】

### 5.1 接口与契约清单

| 契约编号 | 类型 | 名称 / Path | 方向 | 关键入参 / 载荷 | 关键出参 / 响应 / 事件 | 鉴权与幂等 | 关联需求 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| API-01 | HTTP | `POST /api/v1/chat/sessions` | 嵌入端/模拟台 → 后端 | `{userId, orderId, inputs, document, target?}` | `ChatSession`（含 `created`、`inputsChanged`） | 双轨鉴权；`draft` 限 `user`；同 `userId+orderId` 幂等恢复 | FR-002, FR-003 |
| API-02 | HTTP | `GET /api/v1/chat/sessions/{sid}` | 嵌入端 → 后端 | `sid`（32 位 hex） | `ChatSession` 视图（触发重启自愈与历史改写链接补全） | 双轨鉴权；只读安全 | FR-003, FR-007 |
| API-03 | HTTP SSE | `POST /api/v1/chat/sessions/{sid}/messages` | 嵌入端 → 后端 | `{text, auto?}` | SSE：`status` / `message`（upsert）/ `error` / `done` | 双轨鉴权；先 `precheck_message` 拦截 4xx；15s 心跳 | FR-004, FR-006 |
| API-04 | HTTP | `POST /api/v1/chat/sessions/{sid}/compact` | 嵌入端 → 后端 | `{}` | `{compacted, summarizedCount, summarizedUpTo, memorySummary, session}` | 双轨鉴权；不足门槛零调用幂等返回 `compacted: false` | FR-006 |
| API-05 | HTTP | `GET /api/v1/chat/sessions/{sid}/templates` | 嵌入端 → 后端 | `?q=关键词` | `[{templateId, templateName, description, offline, recommendLevel, lastStatus}]` | 双轨鉴权；推荐模板优先排序 | FR-010 |
| API-06 | HTTP | `GET /api/v1/chat/sessions/{sid}/templates/{template_id}` | 嵌入端 → 后端 | `sid`、`template_id` | `TemplatePreview`（`bodyText`, `sampleMarkdown`, `inputs`, `fields`） | 双轨鉴权；剥离 Java 规则尾注；已下线模板可预览 | FR-010 |
| API-07 | HTTP | `POST /api/v1/chat/sessions/{sid}/runs` | 嵌入端 → 后端 | `{templateId, inputs?}` | `{message: ChatMessage, session}`（缺参返 `ask_params`，齐备返 `RUNNING`） | 双轨鉴权；活跃互斥锁防并发重跑（`409`） | FR-007 |
| API-08 | HTTP SSE | `GET /api/v1/chat/runs/{run_id}/events` | 嵌入端 → 后端 | `?after=N&includeRaw=0&rawAfter=M`、头 `Last-Event-ID`、`X-Chat-Session-Id` | SSE：`step`（含 `id: seq`）/ `raw` / `final` / `error` | 双轨鉴权 + `X-Chat-Session-Id` 绑定防越权；断线重放 | FR-002, FR-007 |
| API-09 | HTTP | `GET /api/v1/chat/runs/{run_id}/raw` | 嵌入端 → 后端 | `?sessionId=` / 头 `X-Chat-Session-Id` | `{runId, status, events: RawProcessEvent[]}` | 双轨鉴权 + 跨会话绑定；通道淘汰回退 `RunStore` | FR-002, FR-007 |
| API-10 | HTTP | `POST /api/v1/chat/runs/{run_id}/cancel` | 嵌入端 → 后端 | `?sessionId=` / 头 `X-Chat-Session-Id` | `{ok: true}` | 双轨鉴权 + 跨会话绑定；无活跃通道安全幂等 | FR-007 |
| API-11 | HTTP | `POST /api/v1/chat/runs/{run_id}/confirm` | 嵌入端 → 后端 | `{markdown, acknowledgePartial?}`、头 `X-Chat-Session-Id` | `{payload: ReportConfirmedPayload, session}` | 双轨鉴权 + 绑定；状态门禁 + 同负载重放幂等 | FR-009 |
| PM-01 | `postMessage` | `chat-ready` / `chat-init` / `report-confirmed` / `chat-close-request` | 宿主 ↔ `iframe` | 参见 `docs/chat-embed-api.md` §1 | 双向事件信封 | 校验 `event.source === host` 与 `lockedOrigin` | FR-001, FR-010 |

### 5.2 关键契约说明与错误语义

- `401 INVALID_API_KEY` / 未认证：请求头携带无效 `X-API-Key` 时立即拒绝，绝不回退管理端 Cookie/Bearer 降级放行；`403 DRAFT_FORBIDDEN`：仅持 Key 调用方试图读写 `draft` 会话；`400 INVALID_SESSION_KEY` / `INVALID_TARGET` / `EMPTY_MESSAGE`：参数越界或空白消息提前拦截；`404 SESSION_NOT_FOUND` / `RUN_NOT_FOUND` / `TEMPLATE_UNAVAILABLE`：越权访问他人 `runId` 或 `runId`/`sid` 格式非法统一伪装返回 `404 RUN_NOT_FOUND`；`409 RUN_IN_PROGRESS` / `PARTIAL_NEEDS_ACK`（携带 `missingShown`）；`400 NOT_CONFIRMABLE`；`504 CHAT_COMPACT_TIMEOUT` / `502 CHAT_COMPACT_ERROR`。
- `ChatAgent` 内部 4 个只读工具：`load_skill(name)`、`list_templates(keyword)`、`get_template(templateId)`、`get_run_result(runId)`。

---

## 6. 业务流程设计（可直接编码） 【核心】

### 6.1 核心执行流程

```text
1. 宿主打开 /embed.html?userId=<u>&orderId=<o> -> 渲染顶栏/欢迎区 BrandMark（F2）-> 每 500ms 发送 chat-ready。
2. 收到首个宿主 chat-init -> 锁定 lockedOrigin，apiKey 存内存，递增 initGen -> 调用 POST /api/v1/chat/sessions。
3. 后端 open_session：双轨鉴权 -> 生成 sid -> 比对 inputs_fingerprint：变更则递增 inputsVersion、合并保留「用户补充」键值、标旧卡 stale=true、追加 divider；调用 _heal_interrupted_in_place。
4. 空会话自动触发 sendChat('', true) -> send_message 持锁落盘/取史 -> 释放锁 ->（若未归档 ≥ 触发阈值且非 auto：SSE status「正在压缩…」，锁外调 summarizer，重入锁校验 anchor_msg_id 写回）-> 捕获快照 -> 锁外调用 ChatAgent.run() -> 输出经 output_validator 核验自愈。
5. 按动作分发：recommend / ask_params / start_run / rewrite（追加版本、复位 confirmed=false、关联 rewriteRunId）-> 经 SSE 推送 message/done。
6. 若 start_run 启动后台填报：ChatRunManager 同步注册 _RunChannel -> runner 执行通过 StepMapper 脱敏映射为 9 类 RunStep 并保存 raw_events -> 前端订阅 ?after=N&includeRaw=1&rawAfter=M 流式渲染双视图 -> asyncio.shield 保护落盘。
7. 用户审阅/全屏编辑/改写后点击确认 -> confirm_run 校验状态（SUCCESS/PARTIAL+ack）与幂等性 -> 写入 audit.jsonl("chat-confirm") -> postToParent 回传 report-confirmed 与 chat-close-request。
```

### 6.2 并发控制与异常降级策略

| 异常/并发场景 | 检测时机 | 处理策略 | 是否中断主流程 | 可观测性输出 |
| --- | --- | --- | --- | --- |
| 同会话并发启动多次填报 | `ChatRunManager.start()` / `send_message(start_run)` | 检测 `_active_by_session` 存在运行任务，接口返 `409 RUN_IN_PROGRESS`，对话返忙提示消息 | 是（阻止二次启动） | 保持原运行卡片状态与步骤流 |
| 自动滚动摘要模型超时或异常 | `send_message()` 锁外压缩阶段 | 捕获除 `CancelledError` 外的异常，记录脱敏警告日志，回退 `chat_max_history_messages` 滑窗继续推理 | 否 | 结构化警告日志 `log.warning`（含脱敏原因） |
| 并发发消息与压缩摘要乱序冲突 | `_persist_compaction_if_monotonic` 重入锁阶段 | 校验 `cutoff > cur_up_to` 与 `cur_msgs[cutoff-1]["id"] == anchor_msg_id`，不一致则放弃覆盖 | 否 | 保障历史数组完整不丢失新消息 |
| 服务重启中断或 SSE 连接断开 | 会话读取 / 重连 `GET /runs/{id}/events` | `_heal_interrupted_in_place` 将残留 `RUNNING` 恢复 `INTERRUPTED`；客户端用 `after`+`rawAfter` 断点续接，通道淘汰后从 `RunStore` 重放 | 否 | 卡片展示重跑按钮及「服务重启导致运行中断」提示 |
| 历史改写消息缺失绑定元数据 | `_build_view` / 前端 `rewriteTargetMap` | `_backfill_legacy_rewrite_links` 按 5s 窗口 + `runId` 一对一补齐 `rewriteRunId` 与 `rewriteVersionNo` | 否 | 回复气泡下方正常渲染对应 `ReportInlineCard` |

---

## 7. 权限与安全控制（本需求范围） 【补充】

| 控制点 | 适用角色/调用方 | 校验机制与边界 |
| --- | --- | --- |
| `require_chat_caller` | 所有 `/api/v1/chat/*` 调用方 | 先检非空 `X-API-Key`（经 `require_report_key` 常量时间 `hmac.compare_digest` 校验），通过后再解析 Cookie/Bearer 身份防止管理端降级劫持 |
| `_ensure_caller_allowed` | 涉及 `target="draft"` 会话请求 | 强制要求 `caller.kind == "user"`，拒绝仅持 API Key 读取或篡改草稿会话，返回 `403 DRAFT_FORBIDDEN` |
| `_extract_expected_sid` & `resolve_session_for_run` | `/runs/{run_id}/{events,raw,cancel,confirm}` | 强制校验 `X-Chat-Session-Id` / `?sessionId=` 与 `run_id` 真实归属会话一致，防止枚举越权 |
| `onWindowMessage` 跨域防护 | `/embed.html` 前端父子窗口 | 校验 `event.source === getHostWindow()` 且锁定首个合法 `lockedOrigin`；`apiKey` 仅留存内存并于卸载清零 |
| `ChatStore._resolve_path` | 持久化文件读写与清理 | `SESSION_ID_RE` 正则限制 + `ensure_within` 防止软链逃逸或路径穿越 |
| `StepMapper.sanitize_error_text` | 运行步骤与异常错误信息 | 掩码 Bearer、API Key、键值凭据、引号字面量、POSIX/Windows 路径及 ≥8 位敏感数字与身份证号并截断 120 字 |

---

## 8. 前端 / 交互设计（如适用） 【补充】

| 视图/组件 | 职责 | 关键状态与交互 | 关联接口 |
| --- | --- | --- | --- |
| `frontend/embed.html` & `BrandMark.vue` | 独立无管理端外壳入口与统一品牌图标 | `embed.html` 内联 F2 SVG data URI favicon；`ChatEmbedApp.vue` 在 52px 顶栏（`:size="22"` `.assistant-brand-logo`）与空会话欢迎区（`:size="46"` `.welcome-brand-logo`）挂载轻量 `BrandMark.vue`（`useId()` 隔离渐变 ID），不引入重型 UI 库 | — |
| `ChatEmbedApp.vue` & `embed.css` | 纯亮色全幅等比缩放聊天主控台 | `BASE_WIDTH=1280`、`MIN_STAGE_HEIGHT=640`、`scaleFactor <= 1` 铺满视口，顶栏一键切换自适应模式；52px 毛玻璃顶栏含入参浮层、「记忆 (N)」/ 手动压缩按钮（随 `manualCompactKeepRecent`/`manualCompactMinMessages` 联动）、模板库与关闭；`max-width: 840px` 中央对话流含水位分隔线 | API-01 ~ API-11, PM-01 |
| `RunCard.vue` / `ReportInlineCard.vue` / `RawEventsTimeline.vue` | 运行过程与行内报告展示控制 | 折叠/展开切换「精简步骤（9 类图标）」与按轮次聚合的「原样运行记录（`markRaw` `O(1)` 追加）」；支持行内/AI 改写气泡下方报告卡与草稿状态双向同步 | API-08, API-09 |
| `PreviewDialog` / `TemplateStructureDialog` / `SwitchTemplateDialog` / `StageConfirmDialog` / `VersionSelect` | 舞台内轻浮层与全屏编辑弹窗 | 全部挂载 `.embed-stage` 内等比缩放；提供三态（渲染/源码/分栏）全屏对比编辑器、三栏模板检查器（样例/Jinja2 高亮/字段清单）与 `PARTIAL` 二次确认弹框 | API-05, API-06, API-11 |
| `ChatSimView.vue` / `ChatIframeTabPane.vue` / `ChatSimTemplatePicker.vue` | 管理端模拟联调台与全幅页签保活 | 左右双栏配置入参单据（支持从模板/回归用例预填与内存态系统 Key 自动同步）、点击打开顶部 `智能填报 · <orderId>` 页签由 `v-show` 保活承载 `/embed.html`，右栏实时审计双向 `postMessage` 与回传结果 | PM-01, API-01 |

---

## 9. 配置与热更新开关 【补充】

| 配置项（Env / RuntimeConfig） | 类型 | 默认值 | 是否支持热更新 | 说明 |
| --- | --- | --- | --- | --- |
| `CHAT_MAX_DOC_CHARS` / `chatMaxDocChars` | `int` | `12000` | 是 | 注入聊天 Agent 上下文的单据最大字符数（`500~200000`） |
| `CHAT_MAX_HISTORY_MESSAGES` / `chatMaxHistoryMessages` | `int` | `20` | 是 | 聊天窗口单轮携带最近原文消息上限（`1~200`） |
| `CHAT_MAX_RUN_CARDS` / `chatMaxRunCards` | `int` | `8` | 是 | 上下文注入最近运行卡片数量上限（`1~50`） |
| `CHAT_MAX_MARKDOWN_PREVIEW_CHARS` / `chatMaxMarkdownPreviewChars` | `int` | `1500` | 是 | 上下文卡片报告正文预览截断上限（`100~20000`） |
| `CHAT_COMPACT_TRIGGER_MESSAGES` / `chatCompactTriggerMessages` | `int` | `24` | 是 | 自动触发增量压缩的未归档消息阈值（`2~500`，须 `> keepRecent`） |
| `CHAT_COMPACT_KEEP_RECENT` / `chatCompactKeepRecent` | `int` | `12` | 是 | 自动压缩保留的最近原文消息数（`1~200`） |
| `CHAT_MANUAL_COMPACT_KEEP_RECENT` / `chatManualCompactKeepRecent` | `int` | `6` | 是 | 手动 `/compact` 保留的最近原文条数（`1~200`） |
| `CHAT_MANUAL_COMPACT_MIN_SLICE` / `chatManualCompactMinSlice` | `int` | `2` | 是 | 手动压缩最小可归档切片（`1~100`，控制前端触发下限） |
| `CHAT_MAX_MEMORY_SUMMARY_CHARS` / `chatMaxMemorySummaryChars` | `int` | `1200` | 是 | 滚动摘要字符上限（`200~10000`） |
| `CHAT_MAX_SUMMARY_MSG_CHARS` / `chatMaxSummaryMsgChars` | `int` | `800` | 是 | 待压缩切片单条文本截断上限（`100~10000`） |
| `CHAT_REQUEST_LIMIT` / `chatRequestLimit` | `int` | `8` | 是 | 聊天智能体单轮请求模型上限（`1~50`） |
| `CHAT_TOOL_CALLS_LIMIT` / `chatToolCallsLimit` | `int` | `16` | 是 | 聊天智能体单轮只读工具调用上限（`1~100`） |
| `CHAT_TIMEOUT_S` / `chatTimeoutS` | `float` | `120.0` | 是 | 聊天路由单轮超时秒数（`> 0`） |
| `CHAT_SUMMARY_REQUEST_LIMIT` / `chatSummaryRequestLimit` | `int` | `3` | 是 | 摘要智能体单次压缩模型请求上限（`1~20`） |
| `CHAT_SUMMARY_TOOL_CALLS_LIMIT` / `chatSummaryToolCallsLimit` | `int` | `4` | 是 | 摘要智能体工具调用上限（`1~30`） |
| `CHAT_SUMMARY_TIMEOUT_S` / `chatSummaryTimeoutS` | `float` | `60.0` | 是 | 摘要智能体超时秒数（`> 0`） |
| `REPORT_API_KEYS` / `reportApiKeys` | `str` | `""` | 是 | 嵌入端共用 `X-API-Key` 白名单（逗号分隔，模拟台自动带出内存态 Key） |

---

## 10. 测试设计（Test Strategy） 【核心】

### 10.1 测试范围与分层策略

| 测试类型 | 覆盖范围 | 桩/隔离策略 | 重点验证场景 |
| --- | --- | --- | --- |
| 单元测试 | `ChatStore`、`StepMapper`、`sanitize_error_text`、`_effective_memory_state`、`validate_skill` | 临时目录 `tmp_path` + 内存对象 | 64 分片锁/缓存深拷贝/清理、9 类图标与隐私掩码、损坏摘要自愈、33 模板交叉规则 |
| 集成测试 | `/api/v1/chat/*` 11 端点全链路、`ChatAgent`、`summarizer`、`ChatRunManager`、`ChatService` | `httpx.AsyncClient`（ASGI）+ `FunctionModel` 双/三路桩模型 | 双轨鉴权与 `X-Chat-Session-Id` 越权、指纹演进、路由自愈、双游标续接、滚动压缩与隔离、改写与三级幂等审计 |
| 前端类型与分包构建 | `frontend/src/embed/*`、`BrandMark.vue`、`ChatSimView.vue`、`vite.config.ts` | `vue-tsc --noEmit` 与 Vite `npm run build` | 严格 TypeScript 零报错、`dist/embed.html` 剥离重型 chunk 并正确预加载轻量 `BrandMark.vue` |

### 10.2 回归范围

- 全量后端测试 `uv run pytest -q`（共 196 条用例，含 `tests/test_chat.py`、`tests/test_chat_compaction.py`、`tests/test_review_api_chat.py`、`tests/test_migrated_seed.py`）。
- 后端代码检查 `uvx ruff@0.11.0 check src tests`。
- 前端类型编译与多入口打包构建 `cd frontend && npx vue-tsc --noEmit -p tsconfig.app.json && npm run build`。

<a id="plan-quickstart"></a>

### 10.5 验证指南

- **环境与前置条件**：Python 3.13 + `uv`、Node.js + `frontend/node_modules`，无需外网 LLM 或真实统一网关。
- **验证命令**：
  ```bash
  # 1. 后端全量测试与聊天专题回归（含双/三路 FunctionModel 与 SEED_DIR 隔离）
  uv run pytest -q

  # 2. 后端 Ruff 静态代码检查
  uvx ruff@0.11.0 check src tests

  # 3. 前端 TypeScript 严格校验与多入口产包构建（检查 dist/embed.html 是否洁净）
  cd frontend && npx vue-tsc --noEmit -p tsconfig.app.json && npm run build
  ```
- **预期结果**：后端 `pytest` 全量 196 passed、`ruff` 0 告警、前端 `vue-tsc` 0 错误、`vite build` 顺利输出 `dist/embed.html` 且不包含 `element-plus` / `codemirror` 等重型 chunk。

---

## 11. NFR 符合性自检 【核心】

| 自检主题 | 宪章依据 | 是否涉及 | 落实位置与验证方式 |
| --- | --- | --- | --- |
| 零业务硬编码与资源隔离 | I | 是 | 路由规则外置 `seed/skills/template-router/SKILL.md`，受 `domain/resources.py` 双向检查；`test_migrated_seed.py` 验证 |
| 强证据防幻觉与确定性计算 | II | 是 | `ChatAgent` 4 只读工具 + `output_validator` 自愈；`memorySummary` 与填报 `<document>` 隔离；`test_chat_compaction.py` 验证 |
| 文件化存储与 `workers=1` 并发安全 | III | 是 | `ChatStore` 64 分片 + 锁序 `_stripe_lock -> _cache_guard`；锁外 LLM + 锁内锚点；`test_review_api_chat.py` 验证 |
| 安全编码、脱敏与零凭据硬编码 | VI | 是 | `origin` 锁定、`apiKey` 内存存放、`require_chat_caller` 防降级、`StepMapper` 全脱敏；`test_chat.py` 与 `test_review_api_chat.py` 验证 |
| 过程事件、阶段日志与审计留痕 | VII | 是 | `status`/`step`/`raw`/`final`/`error` SSE 规范推流；`chat-confirm` 写盘 `audit.jsonl`；`test_chat.py` 验证 |

---

## 12. 发布与回退计划 【核心】

- **发布前置与步骤**：执行 `uv run pytest -q`、`uvx ruff@0.11.0 check src tests`、`vue-tsc --noEmit` 与 `npm run build` 核查 `dist/embed.html` 洁净无重型 chunk → 确保 `template-router/SKILL.md` 发布校验 `0 errors, 0 warnings` → 启动单进程服务（`workers=1`）检查 `/healthz` 与 `/embed.html`。
- **回退方案**：模板路由规则异常可通过平台版本管理切换 `releases/current` 至上一稳定 `rN`；16 项 `chat_*` 配置异常可通过 `/api/v1/settings/runtime/rollback/{rev}` 秒级回滚至历史修订 `cN`；前后端包异常直接切换发布镜像或 Git 版本回退。

---

## 13. 实施切片与建议顺序（Implementation Slices） 【核心】

| 切片 ID | 切片名称 | 对应 Phase / 任务范围 | 目标与涉及文件 | 核算工时（如适用） |
| --- | --- | --- | --- | --- |
| S-01 | 后端契约与多入口轻前端骨架 | Phase 1（`T001`–`T002`） | `chat/__init__.py`、`docs/chat-embed-api.md`、`frontend/embed.html`（含 F2 SVG icon）、`BrandMark.vue`、`vite.config.ts`、`src/embed/{main.ts,embed.css,types.ts}` | 3.0 人天 |
| S-02 | 分片持久化、双轨路由与脱敏运行底座 | Phase 2（`T003`–`T005`） | `chat/store.py`、`api/routes_chat.py`、`chat/manager.py`、`chat/steps.py` | 6.0 人天 |
| S-03 | 安全握手、防越权校验与指纹演进（MVP） | Phase 3 / US1（`T006`–`T008`） | `chat/service.py`、`api/routes_chat.py`、`frontend/src/embed/chatApi.ts`、`ChatEmbedApp.vue` | 6.5 人天 |
| S-04 | 只读路由智能体与 `template-router` 自愈（MVP） | Phase 4 / US2（`T009`–`T011`） | `chat/agent.py`、`chat/service.py`、`seed/skills/template-router/SKILL.md`、`domain/resources.py` | 6.0 人天 |
| S-05 | 锁外滚动记忆压缩与 16 项热更新 | Phase 5 / US3（`T012`–`T014`） | `chat/agent.py`、`chat/service.py`、`routes_chat.py`、`config.py`、`runtime_config.py`、`tests/test_chat_compaction.py` | 5.5 人天 |
| S-06 | 轻量嵌入组件、`BrandMark` 接入与模拟台 | Phase 6 / US4（`T015`–`T016`） | `ChatEmbedApp.vue`（含顶栏/欢迎区 `BrandMark`）、11 个 `embed/components/`、3 工具文件、`chat/service.py`、`ChatSimView.vue`、`ChatIframeTabPane.vue`、`ChatSimTemplatePicker.vue` | 3.5 人天 |
| S-07 | 全链路回归测试与前后端门禁验收 | Phase 7 / Polish（`T017`–`T018`） | `tests/test_chat.py`、`tests/test_review_api_chat.py`、`pytest`/`ruff`/`vue-tsc`/`vite build` 收口校验 | 2.5 人天 |
| **合计** | **全周期设计切片总计** | **Phase 1–7（18 项任务）** | **完整交付嵌入式聊天后端、轻量化前端与模拟台全栈闭环** | **33.0 人天** |

---

## 14. 风险清单与缓解（Risks） 【补充】

| 风险 ID | 风险描述 | 影响 | 概率 | 缓解措施 |
| --- | --- | --- | --- | --- |
| R-1 | 前端开发者误在 `src/embed/` 引入 Element Plus / Pinia 等管理端库导致独立入口体积暴涨 | 高 | 低 | 在 `vite.config.ts` 独立拆包并每次构建检查 `dist/embed.html` preload 列表（当前 `BrandMark` 仅 4.2KB，零重依赖） |
| R-2 | 多轮并发发消息时锁外摘要生成完成落后于最新对话导致水位回退覆盖 | 高 | 中 | `_persist_compaction_if_monotonic` 重入 `_SessionLock` 校验 `cutoff > cur_up_to` 与 `anchor_msg_id` 精确一致才落盘 |
| R-3 | 外部沙箱浏览器禁用 Web Storage 或传送 `'null'` `origin` 引发脚本异常 | 中 | 中 | `readAdminToken` / `readInitialScaleMode` 包裹 `try/catch` 回退内存模式，`postToParent` 对 `'null'` 源降级 `'*'` |
| R-4 | 仅持 `X-API-Key` 调用方在同源环境下借管理端 Cookie 降级绕过访问草稿 | 高 | 低 | `require_chat_caller` 优先验证非空 `X-API-Key`，无效立即 `401`，`open_session` 再检已有会话 `target` |

---

## 15. 待确认事项（Design Open Questions） 【补充】

设计阶段关键技术取舍已闭环，无未关闭 `DQ-*`（与 `spec.md` 第 11 节 `Q-001`、`Q-002` 保持一致并已全数关闭）。

---

## 附录 A：核心字段与状态约定（仅本需求）

- **消息类型（`ChatMessage.kind`）**：`text`（可含 `rewriteRunId`、`rewriteVersionNo`）、`divider`、`recommend`、`ask_params`、`run`、`confirmed`。
- **运行状态（`RunStatus`）**：`RUNNING`、`SUCCESS`、`PARTIAL`、`FAILED`、`CANCELLED`、`INTERRUPTED`。
- **`StepMapper` 9 类语义图标**：`start`、`skill`、`api`、`filter`、`tool`、`check`、`warn`、`error`、`done`。
- **`ChatAction.action` 五动作枚举**：`reply`、`recommend`、`ask_params`、`start_run`、`rewrite`。
- **报告版本类型（`ReportVersion.kind`）**：`original`（经 `EvidenceChecker` 核验）、`rewrite`（未经证据校验）。

## 附录 B：AI 编码与交付约束

1. 先阅读 `spec.md`、本 `plan.md` 与 `tasks.md`，按 `T001`–`T018` 顺序与依赖约束核对交付物，严禁越界实现 Out of Scope 内容。
2. 所有已勾选完成 `[X]` 的任务均已附有真实命令验证输出，严禁虚构或跳过校验门禁。

---

## 变更记录（Changelog）

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | AiCoding (codex) | 基于初期设计模板完成 007 技术实施归档 |
| 2.0 | 2026-11-16 | AiCoding (codex) | 按改造后 `inline-v1` 单文件内联设计模板重构，补齐 4 个锚点与 15 章架构设计，并同步 `embed.html` 内联 F2 SVG icon 与 `BrandMark.vue` 组件集成事实 |
