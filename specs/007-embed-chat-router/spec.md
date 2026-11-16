# 需求文档（Spec）：嵌入式聊天选模板窗口、结构化路由智能体与增量记忆压缩系统

<!-- #Created By AiCoding(codex) -->

> **Spec Kit 使用约定**：产物文件名固定为 `spec.md`、`plan.md`、`tasks.md`；三类外部独立交付物按需确认，仅涉及项单独生成并建立链接，不涉及项只记录依据。生成时已将全部占位提示替换为真实取证内容；不适用章节保留标题并说明 `本需求不涉及` 及原因。
> **项目依据**：项目宪章 `.specify/memory/constitution.md`、`AGENTS.md`、`wiki/components/chat-embed.md` 与 `docs/chat-embed-api.md`。遵循先取证后写作原则，所有接口、字段、配置及前端组件均已核对仓库源码与测试。

---

**功能分支**：`[007-embed-chat-router]`

**创建日期**：2026-11-16

**状态**：已交付归档

**输入**：用户描述："智能申告报告填写与资源治理平台（`report-agent`）全栈研发归档拆分（`RA-007`）：嵌入式聊天选模板窗口、结构化路由智能体、增量记忆压缩系统、SSE 双视图断点续接、三级确认审计、F2 品牌图标及模拟联调工作台。"

## 基本信息 【核心】

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-007` |
| 需求名称 | 嵌入式聊天选模板窗口、结构化路由智能体与增量记忆压缩系统 |
| 核算工作量 | 33.0 人天 |
| 资料与证据来源 | 1. **后端实现源码（高可信）**：`src/report_agent/chat/{__init__.py,store.py,agent.py,manager.py,steps.py,service.py}`、`src/report_agent/api/routes_chat.py`、`src/report_agent/domain/resources.py`、`src/report_agent/config.py`、`src/report_agent/store/runtime_config.py`；<br>2. **前端实现源码（高可信）**：`frontend/embed.html`、`frontend/vite.config.ts`、`frontend/src/components/BrandMark.vue`、`frontend/src/embed/{main.ts,embed.css,types.ts,chatApi.ts,markdown.ts,stageToast.ts,useStageFloatTip.ts,ChatEmbedApp.vue}`、`frontend/src/embed/components/*.vue`、`frontend/src/views/ChatSimView.vue`、`frontend/src/components/{ChatIframeTabPane.vue,ChatSimTemplatePicker.vue}`；<br>3. **生产路由资源与接口契约（高可信）**：`src/report_agent/seed/skills/template-router/SKILL.md`、`docs/chat-embed-api.md`；<br>4. **自动化测试与知识库证据（高可信）**：`tests/test_chat.py`、`tests/test_chat_compaction.py`、`tests/test_review_api_chat.py`、`wiki/components/chat-embed.md`、`wiki/skills/template-router.md` |
| 文档版本 | 2.0 |
| 文档状态 | 已交付归档 |

---

## 1. 业务背景与目标 【核心】

### 1.1 业务背景

前代报告填写服务主要由上游工单系统传入固定模板编号直接生成报告，但坐席人员在复杂申告受理场景下往往面对 33 套业务报告模板（`100`～`132`）难以准确选型，且单据正文分散、入参不齐或运行后需要对部分表述做二次润色。直接让上游工单系统改造选模板逻辑或引入重型管理端工作台会导致跨系统耦合高、嵌入首屏加载慢且凭证安全边界模糊。

为此，平台需要向外部工单系统提供一套可无边框嵌入页内标签页（In-Page Tab `<iframe>`）的轻量级聊天选模板窗口 `/embed.html` 与 `/api/v1/chat/*` 后端域：在不侵入主填写引擎 `AgentRunner` 的前提下，通过受控 `postMessage` 握手获取工单上下文，利用严格只读隔离的 `ChatAgent` 自动推荐并驱动模板运行，同时通过锁外异步增量滚动记忆压缩（Rolling Summary）解决长对话上下文膨胀问题，最终以可核对的改写与三级确认门禁将报告回传给外部工单系统。

### 1.2 业务目标

- **GOAL-1**：交付面向外部工单系统的安全跨窗集成通道（`postMessage` 锁定 `lockedOrigin`、防降级双轨鉴权、跨会话 `runId` 防越权隔离及 64 分片无损指纹演进存储）。
- **GOAL-2**：构建受限只读路由智能体 `ChatAgent` 与覆盖全库 33 个在线模板的 `template-router` Skill，实现结构化五动作路由、自愈重试与 `AgentRunner` 强证据域物理隔离。
- **GOAL-3**：落地锁外异步增量滚动记忆压缩与 16 项 `chat_*` 运行期热更新配置，保障长对话不遗忘早期诉求且自动压缩异常时零中断回退滑窗。
- **GOAL-4**：交付零 Element Plus / CodeMirror / Pinia / Vue Router 的纯亮色独立多入口前端 `embed.html`（集成 `F2 智能光笔写单` 品牌图标与 `BrandMark.vue`、等比缩放舞台、双视图 SSE 断点续接、三级确认审计及管理端左右双栏模拟联调台）。

---

## 2. 需求概述 【核心】

本需求构建 `report-agent` 平台中面向外部工单系统的嵌入式聊天选模板与报告辅助确认全栈能力，后端新增独立子包 `src/report_agent/chat/` 与 `src/report_agent/api/routes_chat.py`（共 11 个 REST/SSE 端点），在生产资源库 `src/report_agent/seed/skills/template-router/` 维护覆盖 33 个在线模板的纯文本路由规则并接入 `domain/resources.py` 双向发布门禁；前端在 `frontend/vite.config.ts` 中将 `embed.html` 与管理端 `index.html` 拆分为独立多入口，构建完全剥离重型依赖的流式嵌入应用。

同时，嵌入式窗口内集成 `F2 智能光笔写单` 视觉品牌标志（`embed.html` 内联 SVG data URI favicon 与 `frontend/src/components/BrandMark.vue` 组件分别渲染于 52px 顶栏和欢迎英雄区），并在管理端工作台内通过 `ChatSimView.vue` 与 `ChatIframeTabPane.vue` 提供高保真左右双栏模拟联调能力，使内部维护人员可在发布前完整验证草稿态与线上态全链路交互。

### 2.1 用户场景与测试

#### 用户故事 1（US1）— 安全握手、双轨鉴权与分片持久化演进（优先级：P1）

- **用户旅程**：作为外部工单坐席或宿主系统接入方，我希望在页内 `<iframe src="/embed.html?userId=<u>&orderId=<o>">` 中打开聊天窗口后自动完成安全握手与鉴权建连，并在工单刷新、重入或上层入参变化时恢复历史对话且不丢失我手工补充的字段值。
- **优先级理由**：跨系统凭证安全、防伪造/降级越权与并发会话状态一致性是嵌入式多租户窗口上线运行的首要底座（MVP 前置）。
- **独立测试**：使用 `httpx.AsyncClient`（ASGI 传输）不启动真实大模型验证 401/403/404 鉴权隔离、`ChatStore` 64 分片并发安全与路径拦截、`inputs_fingerprint` 增量演进以及前端握手超时/源窗口校验逻辑。
- **关联需求**：FR-001, FR-002, FR-003
- **验收场景**：
  1. **前提** 外部嵌入页持有有效 `X-API-Key` 请求 `POST /api/v1/chat/sessions` 并传入 `target="online"`，**当** 后端完成双轨鉴权并定位会话，**则** 系统返回以 `session_id_for(userId, orderId)`（`SHA-256` 前 32 位小写 hex）落盘于 `DATA_DIR/chats/<sid[:2]>/<sid>.json` 的 `ChatSession` 视图；若同一仅持 Key 的调用方试图读写 `target="draft"` 会话或混传错误 `X-API-Key` 与管理端 Cookie，则分别严格拦截返回 `403 DRAFT_FORBIDDEN` 与 `401 INVALID_API_KEY`。
  2. **前提** 已存在包含历史消息、「用户补充」字段与历史运行卡片的会话，**当** 父页面下发新 `chat-init` 使 `inputs_fingerprint` 变更，**则** 后端原子递增 `inputsVersion`、保留未冲突的「用户补充」非空键值并移除旧「上层」遗留键、将全部历史 `run` 卡片标为 `stale: true` 并追加 `divider` 系统消息。
  3. **前提** 子窗口处于 `waiting` 状态每 500ms 发送 `chat-ready`，**当** 父页面 10 秒未响应或有无关弹窗/非 `lockedOrigin` 发送伪造 `chat-init`，**则** 10 秒后页面展示「未收到上层参数」兜底提示，伪造消息因 `event.source !== host` 或 `origin` 不匹配被静默丢弃，高频连续 `chat-init` 通过单调递增 `initGen` 丢弃过期异步响应。

#### 用户故事 2（US2）— 受限只读结构化路由与自愈重试（优先级：P1）

- **用户旅程**：作为外部工单坐席，我希望打开空会话后无需手动输入即可获得最多 3 个最匹配模板的推荐及缺失参数提示，在对话中直接补充参数或要求启动/改写报告时得到准确响应，且不触发越权接口调用或模板幻觉。
- **优先级理由**：准确选模板、识别缺参并驱动运行与口径润色是聊天窗口的核心业务价值所在（MVP 核心闭环）。
- **独立测试**：通过 `pydantic_ai.models.function.FunctionModel` 构造多轮脚本桩模型，脱离真实外网大模型独立验证 `auto=true` 首轮推荐、非 `template-router` Skill 拒载、`@agent.output_validator` 捕获下线模板与空改写触发 `ModelRetry` 自愈、`start_run` 与 `rewrite` 版本叠加复位 `confirmed=false`。
- **关联需求**：FR-004, FR-005
- **验收场景**：
  1. **前提** 在线资源库发布 `template-router` Skill 与 33 套在线模板（`100`～`132`），**当** 新建空会话自动发送 `auto=true` 至 `POST /api/v1/chat/sessions/{sid}/messages`，**则** `ChatAgent` 调用 `load_skill("template-router")` 并提交最多 3 个不重复且在线的 `RecommendPick`（含 `高`/`中`/`低` 等级与依据），同时计算实时 `missingRequired` 清单。
  2. **前提** `ChatAgent` 在某轮推理误推荐已下线或不存在的模板 ID、返回空推荐列表或尝试调用 `load_skill("business-sms")`，**当** 进入工具校验或 `@agent.output_validator`，**则** `load_skill` 返回拒载提示阻止越权，校验器抛出携带可用在线模板 ID 列表的 `ModelRetry` 引导模型自我纠正。
  3. **前提** 会话存在状态为 `SUCCESS` 或 `PARTIAL` 的运行卡片，**当** 用户要求精简或调整措辞口径，**则** `ChatAgent` 必须输出 `action="rewrite"` 与完整 `markdown`（单卡可改写时允许自动补齐 `runId`，多卡时要求明确指定），后端追加 `kind="rewrite"` 的 `ReportVersion`、复位 `card["confirmed"]=false` 并下发带 `rewriteRunId` 与 `rewriteVersionNo` 的助手 `text` 消息。

#### 用户故事 3（US3）— 锁外异步增量滚动记忆压缩系统（优先级：P2）

- **用户旅程**：作为高频处理长工单对话的坐席及平台管理员，我希望长对话时系统自动提炼早期诉求与否决过的模板而不拖慢并发响应、不污染核查事实证据，并且我能随时手动压缩早期上下文或在线调整压缩配额参数。
- **优先级理由**：多轮反复问询场景下，增量滚动压缩能防止上下文 Token 溢出与意图遗忘，同时锁外执行大模型推理守住单进程会话并发吞吐与强证据隔离底线。
- **独立测试**：运行 `tests/test_chat_compaction.py`（三路脚本桩模型）独立测试短对话（<24 条）零压缩、达阈值触发二次滚动增量合并、自动压缩失败无缝降级滑窗、手动 `/compact` 幂等门槛拦截与 504/502 错误、损坏摘要状态自愈以及 `AgentRunner` `<document>` 绝对隔离。
- **关联需求**：FR-006
- **验收场景**：
  1. **前提** 会话未归档消息数（`len(history_before) - summarizedUpTo`）达到 `chat_compact_trigger_messages`（默认 24 条），**当** 用户发送非 `auto` 对话消息，**则** 系统落盘用户消息并释放 `_SessionLock` 后推送 SSE `status`「正在压缩早期对话上下文…」，锁外调用 `ChatAgent.summarize_history()` 将早期切片（保留最近 `chat_compact_keep_recent` 默认 12 条）与已有 `memorySummary` 合并提炼至不超过 `chat_max_memory_summary_chars`（默认 1200 字），随后在锁内验证 `cutoff > cur_up_to` 与 `anchor_msg_id` 锚点一致后原子写回；摘要提示词显式声明严禁作为填报字段证据且绝不注入 `AgentRunner`。
  2. **前提** 自动压缩期间 `summarizer` 超时或抛出异常，**当** `send_message()` 捕获异常，**则** 记录脱敏警告日志并无感退回最近 `chat_max_history_messages` 条滑动窗口继续推理，不阻断用户对话；若用户主动请求 `POST /api/v1/chat/sessions/{sid}/compact` 遇超时或失败，则明确返回 `504 CHAT_COMPACT_TIMEOUT` 或 `502 CHAT_COMPACT_ERROR`。
  3. **前提** 未归档消息数少于 `manualCompactMinMessages`（`chat_manual_compact_keep_recent + chat_manual_compact_min_slice`，默认 `6 + 2 = 8` 条），**当** 请求 `/compact` 接口，**则** 直接幂等返回 `compacted: false`、`summarizedCount: 0` 且零大模型调用；管理端修改任意 16 项 `chat_*` 热更新参数后立即触发 `ChatAgent` 缓存快照重建生效。

#### 用户故事 4（US4）— 轻量级流式嵌入前端、SSE 双视图断点续接、品牌标志与模拟联调台（优先级：P2）

- **用户旅程**：作为外部工单坐席与内部联调配置人员，我希望嵌入窗口首屏秒开且视觉品牌与主工作台一致，在对话流内实时查看脱敏或原样运行轨迹、断线无感续接、全屏对比编辑改写报告并经二次确认门禁安全回传，同时能在管理端模拟页签中一键联调。
- **优先级理由**：极简独立的打包体量与高效的内联卡片/弹窗/模拟台闭环直接决定了业务一线使用体验与运维交付验收效率。
- **独立测试**：执行 `npx vue-tsc --noEmit -p tsconfig.app.json` 与 `npm run build` 验证多入口打包及 `dist/embed.html` 零重型依赖；在 `tests/test_chat.py` / `tests/test_review_api_chat.py` 验证双游标 SSE 重放、脱敏规则、重启 `INTERRUPTED` 自愈、`PARTIAL` 二次确认门禁与幂等审计；在 `ChatSimView.vue` 打开全局页签完成联调闭环。
- **关联需求**：FR-007, FR-008, FR-009, FR-010
- **验收场景**：
  1. **前提** `/embed.html` 独立入口加载完成且 `ChatRunManager` 正在后台执行填报，**当** 前端渲染顶部 52px 毛玻璃栏与空会话欢迎区，并在运行卡片切换「精简步骤（9 类图标）」与「原样运行记录（`RawEventsTimeline`）」或遭遇网络断线重连，**则** 顶栏（22px）与欢迎区（46px）展示轻量 `BrandMark.vue`（`F2 智能光笔写单`）图标且页面 `<link rel="icon">` 使用内联 F2 SVG；运行流同时按 `?after=N`、`includeRaw=1&rawAfter=M` 与 `Last-Event-ID` 续接，服务重启后遗留 `RUNNING` 卡片自动转为 `INTERRUPTED` 并从 `RunStore` 补齐原样事件。
  2. **前提** 用户点击「确认使用此报告」提交正文，**当** 状态为 `FAILED`/`RUNNING`/`CANCELLED`/`INTERRUPTED` 时或 `PARTIAL` 未带 `acknowledgePartial: true` 时，**则** 分别返回 `400 NOT_CONFIRMABLE` 与 `409 PARTIAL_NEEDS_ACK`（携带 `missingShown` 驱动 `StageConfirmDialog` 二次确认）；确认通过后精准计算 `edited` 与 `rewritten`、重放幂等不重复写 `chat-confirm` 审计日志，并向 `lockedOrigin` 发送 `report-confirmed` 与 `chat-close-request`。
  3. **前提** 平台配置人员打开 `/#/chat-sim` 左右双栏模拟联调台，**当** 通过 `ChatSimTemplatePicker.vue` 预填模板或回归用例参数并点击「在顶部新页签打开聊天窗口」，**则** 顶部全局页签栏激活 `智能填报 · <orderId>` 页签由 `ChatIframeTabPane.vue` 全幅 `v-show` 保活承载 `/embed.html`，右栏实时打印双向 `postMessage` 报文流与确认回传报告。

### 2.2 成功标准

- **SC-001**：`embed.html` 生产构建完全剥离 Element Plus、CodeMirror 6、Pinia 与 Vue Router，实际产物 `embed` 专属 JS 约 `108 KB`、CSS 约 `80 KB`、轻量 `BrandMark.vue` 独立 chunk 约 `4.2 KB`（总核心体积较加载 >1.6 MB 的管理端 UI/编辑器依赖缩减约 80%），`dist/embed.html` 零重型依赖 chunk 预加载。
- **SC-002**：`ChatStore` 采用 64 分片线程锁与 256 容量 LRU 深拷贝缓存，命中内存缓存实现零磁盘 I/O 与零线程切换直出，路径校验 100% 拦截非法 `sid` 与软链穿越，超期未锁定会话随 `RUNS_KEEP_DAYS` 自动清理率达 100%。
- **SC-003**：增量滚动记忆压缩接入 16 项 `chat_*` 热更新配置后，默认支持未归档达 24 条触发压缩并保留最近 12 条原文、摘要严格控制在 1,200 字以内（手动压缩保留最近 6 条、触发门槛 8 条），自动压缩异常 100% 无感回退滑窗且 `AgentRunner` `<document>` 证据域隔离率 100%。
- **SC-004**：全库 `template-router` Skill 100% 覆盖 33 个在线模板（`100`～`132`）且发布校验 `validate_all()` 0 error / 0 warning；`StepMapper` 对隐私凭据、本地路径、引号字面量与长数字/身份证实现 100% 掩码脱敏；`tests/test_chat.py`、`tests/test_chat_compaction.py` 与 `tests/test_review_api_chat.py` 全部用例 100% 通过。
- **SC-005**：SSE 进度流支持 `?after=N`、`rawAfter=M` 与 `Last-Event-ID` 断线续接（15s 心跳保活、异常 `error` 帧收尾、通道最长 600s / 256 容量驻留），三级确认门禁拦截与重复提交幂等审计零冗余写盘率达 100%。

### 2.3 假设

- **单进程内存协调假设**：`ChatRunManager` 的 `_channels` / `_active_by_session`、`ChatStore` 的 `_locks_weak` 以及 `ChatService` 的 `_run_to_session` 均运行在单进程 Uvicorn（`workers=1`）内；服务重启由 `_heal_interrupted_in_place` 自动识别并恢复遗留 `RUNNING` 状态。
- **外部宿主集成假设**：外部工单系统按 `docs/chat-embed-api.md` 契约以同源或跨域页内 `<iframe>` 打开 `/embed.html?userId=<u>&orderId=<o>`，及时监听 `chat-ready` 并下发 `chat-init`（服务端开启 `REPORT_API_KEYS` 时携带有效 `apiKey`），并处理 `report-confirmed` 与 `chat-close-request`。
- **模型规格兼容假设**：`ChatAgent` 与 `summarizer` 共享 `AgentRunner` 的底层模型与 `agent_output_mode`（`tool` / `native` / `json_object` / `prompted`），并在运行期配置变化时按快照键自动重建实例。
- **工作量核算口径**：本子规格 `33.0` 人天按已交付全栈归档口径核算，覆盖后端聊天领域层与接口路由、路由 Skill 编制、滚动记忆压缩与 16 项热更配置、纯亮色轻量化嵌入前端（含 F2 品牌图标集成）、管理端模拟联调台及三套自动化测试套件。

---

## 3. 术语与概念定义 【核心，如有新术语】

> 通用平台术语（如「模板」「技能」「API」「运行记录」「系统设置」）已在 `wiki/reference/glossary.md` 与 `frontend/src/constants/terms.ts` 统一定义，以下仅列本需求新增或易引发歧义的专有术语：

| 术语 | 英文/标识 | 定义 | 备注 |
| --- | --- | --- | --- |
| 锁定来源域 | `lockedOrigin` | 子窗口首次收到来自宿主窗口的合法 `chat-init` 时锁定的 `event.origin` 值 | 防止后续第三方弹窗/跨源伪造指令 |
| 入参来源标记 | `inputSources` | 区分每个入参键值来源于上层工单（`上层`）或坐席补充（`用户补充`）的映射 | 决定上层重传 `chat-init` 时的保留与覆盖策略 |
| 增量滚动记忆摘要 | `memorySummary` / `summarizedUpTo` | 将早期已归档消息与原有摘要合并提炼后的精炼背景文本及对应归档前缀水位线 | 严禁充当 `AgentRunner` 填报证据 |
| 边界锚点消息 | `anchor_msg_id` | 压缩发生时待归档切片最后一条消息的 `id`，用于在锁内核对切片未被并发改写 | 与 `cutoff > cur_up_to` 共同保障单调写回 |
| 双视图步骤流 | `StepMapper` / `RawProcessEvent` | 面向一线坐席的 9 类图标脱敏 `RunStep` 与按轮次展示的原样过程事件流 | 实时 SSE 通过 `?after=N` 与 `rawAfter=M` 协同推送 |
| 品牌标志组件 | `BrandMark`（`F2 智能光笔写单`） | 零外部重型依赖的轻量级 SVG 品牌图标组件，配合 `useId()` 隔离线性渐变 DOM ID | 同步内联至 `embed.html` favicon 与前端顶栏/欢迎区 |

---

## 4. 用户角色 【核心】

| 角色 | 类型 | 本需求中可执行的操作与数据范围 | 权限/安全约束 |
| --- | --- | --- | --- |
| 外部工单坐席 | 人工角色（经外部宿主嵌入） | 浏览推荐/全部模板、查看结构预览、补全入参发起 `online` 运行、对话改写润色、审核确认回传报告 | 仅允许访问自身 `(userId, orderId)` 对应的 `online` 会话；禁止操作 `draft` |
| 外部工单宿主系统 | 外部/系统角色 | 通过 `postMessage` 下发 `chat-init`（含 `apiKey`、`inputs`、`document`）并接收 `chat-ready`、`report-confirmed`、`chat-close-request`；调用 `/api/v1/chat/*` | 携带有效 `X-API-Key`（配置 `REPORT_API_KEYS` 时）；`target` 仅限 `online` |
| 平台配置/运维人员 | 人工角色（管理端登录用户） | 在 `/#/chat-sim` 模拟联调（支持 `online` 与 `draft`）、顶部页签全幅交互、在设置中心调整 16 项 `chat_*` 与 `REPORT_API_KEYS` | 须持有有效管理端登录态（Cookie `ra_session` 或 Bearer Token）；`audit.jsonl` 记录真实 `user.display_name` |

---

## 5. 功能需求 【核心】

### 5.1 安全握手、双轨鉴权与分片会话持久化

#### FR-001 父子窗口 `postMessage` 双向安全握手与内存态凭证管理

- **来源**：`frontend/src/embed/ChatEmbedApp.vue`、`frontend/src/embed/chatApi.ts`、`docs/chat-embed-api.md` §1
- **描述**：实现外部宿主页面与嵌入 `iframe` 之间的双向安全通信握手协议，保障敏感凭证不落地、非宿主指令不响应。
- **关联用户故事/成功标准**：US1 / SC-005
- **业务规则**：
  1. 子窗口挂载后若 `userId` 与 `orderId` 齐全，每 500ms 向宿主窗口（优先 `window.parent !== window`，回退未关闭的 `window.opener`）发送 `{type:'chat-ready', userId, orderId}`；若 10 秒内未收到 `chat-init` 则切换至 `no-init` 提示态。
  2. 接收 `message` 事件时必须严格校验 `event.source === host` 且 `data.type === 'chat-init'`；首次收到合法包时永久记录 `lockedOrigin = event.origin`，后续仅接收 `event.origin === lockedOrigin` 的消息；回传时若 `lockedOrigin === 'null'`（沙箱 iframe）自动降级目标源为 `'*'`。
  3. 每次 `handleInit` 递增单调计数器 `initGen`，当父页面高频重复下发 `chat-init` 时，过期异步请求的响应在 `gen !== initGen` 时立即丢弃。
  4. `apiKey` 与 `sessionId` 仅存放于 `chatApi.ts` 模块内存变量中，严禁写入 URL 查询串、`localStorage` 或 `sessionStorage`，组件卸载 `onBeforeUnmount` 时主动清零。
- **输入/触发**：页面加载、`message` 事件（`chat-init`）、确认回传或点击顶栏关闭按钮。
- **输出/结果**：向宿主发送 `chat-ready`、`report-confirmed` 或 `chat-close-request`；页面阶段在 `invalid`/`waiting`/`no-init`/`loading`/`ready`/`error` 间流转。
- **验收标准**：
  - AC-1：正常嵌入挂载后 500ms 内发出首次 `chat-ready`，收到 `chat-init` 后停止定时器并将 `apiKey` 仅留存内存。
  - AC-2：来自非宿主窗口或非 `lockedOrigin` 的伪造 `chat-init` 静默忽略；连续快速下发两次 `chat-init` 时仅最终一次生效。

#### FR-002 双轨防降级鉴权与跨会话 `runId` 防越权校验

- **来源**：`src/report_agent/api/routes_chat.py`（`require_chat_caller`、`_extract_expected_sid`）、`src/report_agent/chat/service.py`（`_ensure_caller_allowed`、`resolve_session_for_run`）
- **描述**：保护全部 11 个 `/api/v1/chat/*` 接口，杜绝 API Key 降级绕过管理端身份及跨会话 `runId` 枚举探测。
- **关联用户故事/成功标准**：US1 / SC-004
- **业务规则**：
  1. `require_chat_caller` 先检查请求头是否存在非空 `X-API-Key`：若存在，必须先经 `require_report_key` 常量时间比对校验通过（非法立即返回 `401 INVALID_API_KEY`，禁止降级使用同源 Cookie）；Key 校验通过或未传 Key 时再识别管理端 Cookie/Bearer，全部缺失且服务端配置了 `REPORT_API_KEYS` 时拒绝访问。
  2. 仅当调用方身份为管理端登录用户（`caller.kind == "user"`）时允许创建、读取或操作 `target="draft"` 会话，否则返回 `403 DRAFT_FORBIDDEN`；已存在的 `draft` 会话同样禁止 API Key 调用方以传 `target="online"` 的方式绕过读取。
  3. `/api/v1/chat/runs/{run_id}/{events,raw,cancel,confirm}` 支持可选头 `X-Chat-Session-Id` 与查询参数 `?sessionId=`：两者同传且不等直接返回 `404 RUN_NOT_FOUND`；若提供了预期 `sid` 但格式不满足 `SESSION_ID_RE`（32 位小写 hex）或与 `run_id` 实际所属会话不匹配，统一返回 `404 RUN_NOT_FOUND` 不暴露目标运行是否存在。
- **输入/触发**：`/api/v1/chat/*` HTTP/SSE 请求。
- **输出/结果**：返回 `ChatCaller(kind="user"|"key", name=...)` 或结构化 HTTP 401/403/404 错误。
- **验收标准**：
  - AC-1：管理端登录态下携带错误 `X-API-Key` 请求会话接口，服务端返回 `401` 而不降级放行；API Key 接入 `target="draft"` 或已存在草稿会话返回 `403 DRAFT_FORBIDDEN`。
  - AC-2：传入其他合法会话 ID 作为 `X-Chat-Session-Id` 请求他人 `runId` 的 `/events`、`/raw`、`/cancel` 或 `/confirm`，全部返回 `404 RUN_NOT_FOUND`。

#### FR-003 64 分片会话持久化与入参指纹无损演进

- **来源**：`src/report_agent/chat/store.py`、`src/report_agent/chat/service.py`（`open_session`）
- **描述**：按 `(userId, orderId)` 稳定映射与持久化聊天会话，高并发安全读写并在上层入参变化时无损合并上下文。
- **关联用户故事/成功标准**：US1 / SC-002
- **业务规则**：
  1. 使用 `session_id_for(user_id, order_id)` 生成 `SHA-256` 前 32 位小写十六进制 `sessionId`（校验 `userId`/`orderId` 非空、无 `\x00`、长度 ≤ 128），文件路径落盘于 `DATA_DIR/chats/<sid[:2]>/<sid>.json`，经 `ensure_within` 双重防御路径穿越与软链逃逸。
  2. `ChatStore` 采用 64 条分片线程互斥锁、256 容量 `OrderedDict` LRU 深拷贝缓存及有界弱引用协程互斥锁池 `_locks_weak`；严格遵守 `_stripe_lock(sid) -> _cache_guard` 固定锁序，`aget()` 命中内存缓存直接返回深拷贝副本，冷文件加载与异步 `asave()`（`fsync + os.replace`）卸载至工作线程。
  3. 仅只读探测 `has_run_id()` 在冷文件扫描时先用字符串过滤再解析 JSON，且不污染热缓存；`cleanup(keep_days)` 清理过期未加锁会话文件及空分片目录并同步驱逐内存缓存。
  4. `open_session` 比对 `inputs_fingerprint(clean_inputs, clean_doc)`：指纹变更时原子递增 `inputsVersion`，保留未与本次上层入参冲突的「用户补充」非空键值并清除旧「上层」遗留键，将历史所有 `run` 卡片标记 `stale: true` 并追加 `divider` 系统消息。
- **输入/触发**：`POST /api/v1/chat/sessions`、周期清理任务 `_cleanup_loop`。
- **输出/结果**：原子落盘的会话 JSON 及严格脱敏剔除内部字段（不直接透出 `document` 原文与 `fingerprint`）的 `ChatSession` 视图。
- **验收标准**：
  - AC-1：同一 `(userId, orderId)` 重进复用相同 `sessionId`；上层重传变化入参后 `inputsVersion` 加 1，非冲突「用户补充」键保留，旧「上层」遗留键清除，历史 `run` 卡片均为 `stale: true`。
  - AC-2：对同一分片或已过期清理会话执行并发读写与 `cleanup`，无缓存脏读与已删会话复活。

### 5.2 受限只读路由智能体与 `template-router` 规则库

#### FR-004 受限只读 `ChatAgent` 五动作路由与自愈重试

- **来源**：`src/report_agent/chat/agent.py`、`src/report_agent/chat/service.py`（`send_message`）
- **描述**：提供严格只读隔离的路由智能体，输出结构化决策并经运行时校验自我纠错。
- **关联用户故事/成功标准**：US2 / SC-004
- **业务规则**：
  1. `ChatAgent` 仅注册 4 个只读工具：`load_skill`（仅允许 `template-router`，其他名称立即返回拒载提示）、`list_templates`（仅列出在线模板）、`get_template`（自动经 `strip_java_rule_note` 剥离 `原规则（Java）：` 历史对照尾注）及 `get_run_result`（读取当前会话内已产生运行的字段结论与 `reasoning`）。
  2. 强制通过 `ChatAction`（`extra="forbid"`）提交 `reply` / `recommend` / `ask_params` / `start_run` / `rewrite` 五种动作之一，并对提取的 `inputs` 字符串执行去空白清洗。
  3. `@agent.output_validator` 实时拦截：空推荐或推荐不存在/已下线模板（去重并截断最多 3 个）、`ask_params`/`start_run` 指定无效模板、`rewrite` 无可改写卡片/多卡未指定 `runId`（单卡自动补全）/无效 `runId` 或空 `markdown`、以及 `reply` 空文本，全部抛出明确指引的 `ModelRetry` 触发自愈。
  4. `ChatService.send_message` 分发各动作并在同一会话锁内合并提取的 `inputs` 记为「用户补充」：`start_run` 若遇会话运行中则产出友好忙提示而不覆盖活跃运行；`rewrite` 向 `versions` 追加 `kind="rewrite"` 版本、将卡片 `confirmed` 复位为 `false` 并生成附带 `rewriteRunId` 与 `rewriteVersionNo` 的助手 `text` 消息。
- **输入/触发**：`POST /api/v1/chat/sessions/{sid}/messages`（`{text, auto}`）。
- **输出/结果**：SSE 流依次推送 `status`、`message`（按 `id` upsert）、`error`（如遇异常）与最终 `done`。
- **验收标准**：
  - AC-1：自动首轮触发不写入用户文本消息即推荐最多 3 个在线模板并计算 `missingRequired`；非 `template-router` 调用被拒载。
  - AC-2：模型输出已下线模板或 `rewrite` 空 `markdown` 时触发 `ModelRetry` 二次修正成功；发起 `rewrite` 后 `confirmed` 准确复位为 `false`。

#### FR-005 `template-router` 路由 Skill 编制与发布双向交叉校验

- **来源**：`src/report_agent/seed/skills/template-router/SKILL.md`、`src/report_agent/domain/resources.py`
- **描述**：将全库 33 个在线模板分流知识封装为可热更新的纯文本资源，并在发布前执行静态交叉门禁检查。
- **关联用户故事/成功标准**：US2 / SC-004
- **业务规则**：
  1. `src/report_agent/seed/skills/template-router/SKILL.md` 必须覆盖在线生产模板 `100`～`132` 全部 33 个模板，以 `### <ID>` 三级标题显式登记适用情景、核心字段与排除边界，且 frontmatter 中 `apis` 保持为空列表 `[]`。
  2. `domain/resources.py#validate_skill` 对 `ROUTER_SKILL_ID = "template-router"` 强制执行双向校验：声明非空 `apis` 报 `ROUTER_SKILL_HAS_APIS` 错误；引用不存在或已下线模板报 `ROUTER_TEMPLATE_NOT_FOUND` 错误；存在未被路由文档覆盖的在线模板发出 `ROUTER_TEMPLATE_UNCOVERED` 警告。
  3. `validate_template` 检测若普通填报模板在 `skills` 中误声明 `template-router`，发出 `ROUTER_SKILL_IN_TEMPLATE` 警告。
- **输入/触发**：资源加载与 `validate_all()` / 平台发布流。
- **输出/结果**：全库生产种子通过 `validate_all()` 达到 `0 errors, 0 warnings`。
- **验收标准**：
  - AC-1：`tests/test_migrated_seed.py#test_template_router_skill_coverage_and_cross_validation` 验证 100～132 覆盖率为 100% 且全部 4 类校验错误/警告按预期触发。

### 5.3 锁外异步增量滚动记忆压缩与参数热更新

#### FR-006 增量滚动记忆摘要、单调锚点落盘与 16 项热更新配置

- **来源**：`src/report_agent/chat/agent.py`、`src/report_agent/chat/service.py`（`_persist_compaction_if_monotonic`、`compact_session`、`_effective_memory_state`）、`src/report_agent/config.py`、`src/report_agent/store/runtime_config.py`
- **描述**：在保护并发响应与强证据隔离的前提下，实现自动与手动两套对话历史滚动摘要归档及参数在线热更新。
- **关联用户故事/成功标准**：US3 / SC-003
- **业务规则**：
  1. 短对话（未归档消息数小于 `chat_compact_trigger_messages` 默认 24 条）保持零压缩，`summarizedUpTo=0`，不额外消耗大模型请求。
  2. 当非 `auto` 对话且未归档消息数（`len(history_before) - summarizedUpTo`）达到触发阈值时：先在会话锁内落盘用户消息并释放锁，经 SSE 推送 `status` 事件「正在压缩早期对话上下文…」，锁外异步调用 `ChatAgent.summarize_history()` 将 `[summarizedUpTo : len - keep_recent]` 切片与原 `memorySummary` 合并提炼至不超过 `chat_max_memory_summary_chars`（默认 1200 字，超出截断带省略号）。
  3. 摘要落盘 `_persist_compaction_if_monotonic` 必须在重新获取 `_SessionLock` 后校验 `cutoff > cur_up_to` 且 `cur_msgs[cutoff - 1]["id"] == anchor_msg_id`，仅一致时才原子写回新 `memorySummary` 与 `summarizedUpTo`，防止并发乱序覆盖。
  4. 自动压缩超时或异常时静默记录脱敏警告日志并优雅退回纯滑动窗口继续推理；手动触发 `POST /api/v1/chat/sessions/{sid}/compact` 在未归档数小于 `keep_manual + min_slice`（默认 `6 + 2 = 8` 条）时幂等返回 `compacted: false`（零模型调用），遇超时或失败分别返回 `504 CHAT_COMPACT_TIMEOUT` 与 `502 CHAT_COMPACT_ERROR`。
  5. `build_chat_user_prompt` 注入摘要段落显式申明「仅供理解对话背景与改写口径偏好，严禁作为填报字段证据」，`memorySummary` 与填报侧 `AgentRunner` 完全隔离；损坏或越界状态经 `_effective_memory_state` 自动自愈为 `('', 0)`。
  6. `Settings` 与 `RuntimeConfig` 接入全部 16 项 `chat_*` 配置（含 `chatCompactTriggerMessages > chatCompactKeepRecent` 跨字段约束），支持工作台在线热更新并由 `ChatAgent` 按配置快照键动态刷新缓存实例。
- **输入/触发**：普通消息达到阈值自动触发、`POST /sessions/{sid}/compact` 手动触发、系统设置更新热重载。
- **输出/结果**：持久化更新 `memorySummary` 与 `summarizedUpTo`；会话视图附带 `manualCompactKeepRecent` 与 `manualCompactMinMessages` 驱动前端状态联动。
- **验收标准**：
  - AC-1：通过 `tests/test_chat_compaction.py` 验证短会话零压缩、二次滚动增量合并、损坏状态自愈及 `AgentRunner` `<document>` 隔离。
  - AC-2：修改 16 项 `chat_*` 热更配置后无需重启服务，下一轮对话或压缩立即采用新阈值与超时控制。

### 5.4 后台通道续接、步骤脱敏、三级确认与轻量前端/模拟台

#### FR-007 后台运行通道并发互斥、双游标 SSE 续接与重启自愈

- **来源**：`src/report_agent/chat/manager.py`、`src/report_agent/chat/service.py`（`start_run`、`stream_events`、`get_run_raw_events`、`_heal_interrupted_in_place`）、`src/report_agent/api/routes_chat.py`
- **描述**：管理聊天内触发的后台填报任务生命周期，实现零竞态事件订阅、断线重放与进程重启状态自愈。
- **关联用户故事/成功标准**：US4 / SC-005
- **业务规则**：
  1. `ChatRunManager.start()` 对同会话存在活跃任务时抛错并由服务层映射 `409 RUN_IN_PROGRESS`；在启动异步任务与返回 `run_id` 前同步将 `_RunChannel` 写入 `_channels` 与 `_active_by_session`，杜绝极快完成或立即订阅引起的竞态漏事件。
  2. `cancel()` 支持取消正在运行的任务，并在 `_execute` 收尾回调落盘阶段采用 `asyncio.shield` 保护会话写回不因客户端断连或并发取消中断。
  3. `GET /api/v1/chat/runs/{run_id}/events` 支持 `?after=N`、`Last-Event-ID`（取最大值）与 `includeRaw=1&rawAfter=M` 双游标实时推送与通道保留期内（默认 `keep_done_s = 600s`、上限 `256` 通道）断线重放，并由 `_sse_chat_stream` 每 15s 发送 `: keep-alive` 保活。
  4. 通道淘汰或进程重启后，`stream_events` 从持久化会话的 `steps` 与 `RunStore` 的原样事件重放并发送 `final` 闭合；`get_run_raw_events` 优先读内存通道，淘汰后按需从 `RunStore` 补齐；会话视图读取时通过 `_heal_interrupted_in_place` 自动将无活跃通道的 `RUNNING` 卡片恢复为 `INTERRUPTED`。
- **输入/触发**：`POST /sessions/{sid}/runs`、`GET /runs/{run_id}/events`、`GET /runs/{run_id}/raw`、`POST /runs/{run_id}/cancel`。
- **输出/结果**：有序双游标 SSE 事件流（`step`、`raw`、`final`、`error`）与原子落盘运行卡片。
- **验收标准**：
  - AC-1：并发启动同会话第二次运行返回 `409 RUN_IN_PROGRESS`；停止运行后卡片转为 `CANCELLED`。
  - AC-2：模拟进程重建容器后查询原会话，原 `RUNNING` 卡片自动变为 `INTERRUPTED` 且支持从 `RunStore` 拉取原样事件。

#### FR-008 `StepMapper` 脱敏转换与隐私信息掩码引擎

- **来源**：`src/report_agent/chat/steps.py`
- **描述**：将引擎底层 `ProcessEvent` 转化为对外部坐席友好且绝对不泄露内部路径、密钥与客户敏感数据的进度步骤。
- **关联用户故事/成功标准**：US4 / SC-004
- **业务规则**：
  1. `StepMapper.feed` 过滤屏蔽模型内部轮次与思考事件（`model_request`、`model_text`），不占用 `seq`。
  2. 将可见事件映射为 9 类规范图标（`start`、`skill`、`api`、`filter`、`tool`、`check`、`warn`、`error`、`done`），仅向前端输出公开标题、命中条数及安全统计摘要，绝不透传网关原始报文、客户文本或正则提取结果。
  3. `sanitize_error_text` 对任意异常文本统一折叠空白并依次掩码：`Bearer ...` 令牌、`sk-/rk-/ak-/pk-` Key 前缀、键值凭据（`api_key`/`access_token`/`secret`/`password`/`authorization`）、单双引号字面量（长度 ≥ 4）、POSIX/Windows 本地文件路径、18 位身份证号及 ≥ 8 位敏感数字串，且超过 120 字符强制截断带省略号。
- **输入/触发**：后台运行 `listener` 回调、异常捕获日志与 SSE 错误帧生成。
- **输出/结果**：结构化脱敏 `RunStep` 字典序列与安全的错误提示消息。
- **验收标准**：
  - AC-1：包含本地绝对路径、Bearer Token、双引号客户姓名/手机号及 11 位手机号的错误文本经过 `sanitize_error_text` 后 100% 替换掩码为 `***` 且长度不超过 121 字符。

#### FR-009 三级确认门禁、幂等审计与回传信封

- **来源**：`src/report_agent/chat/service.py`（`confirm_run`）、`src/report_agent/api/routes_chat.py`
- **描述**：对人工选定使用的报告正文执行状态与完整度门禁校验、准确识别人工微调与 AI 改写标记、幂等记录审计日志并生成宿主回传载荷。
- **关联用户故事/成功标准**：US4 / SC-005
- **业务规则**：
  1. 仅当目标运行状态为 `SUCCESS` 或 `PARTIAL` 时允许确认，否则返回 `400 NOT_CONFIRMABLE`；状态为 `PARTIAL` 且请求体 `acknowledgePartial` 不为 `true` 时拦截返回 `409 PARTIAL_NEEDS_ACK`（载荷包含 `missingShown` 字段列表）。
  2. 对比提交的 `markdown` 与最新版本原文确定 `edited` 布尔值，依据最新版本 `kind == "rewrite"` 确定 `rewritten` 布尔值；更新各运行卡片 `confirmed` 排他标记及会话级 `confirmed` 摘要。
  3. 仅当当前卡片已处于 `confirmed` 且提交的 `runId`、`markdown`、`edited`、`rewritten` 与最近一次 `confirmRecords` 完全一致时视为幂等重放（不重复追加 `confirmed` 消息与审计日志）；若中途经过 AI 改写复位了 `confirmed=false` 再选回原始版本提交确认，正常写新确认审计记录。
  4. 通过 `self.publisher.audit("chat-confirm", caller.name, audit_payload)` 将真实认证操作人身份写入 `DATA_DIR/audit.jsonl`。
- **输入/触发**：`POST /api/v1/chat/runs/{run_id}/confirm`（`{markdown, acknowledgePartial}`）。
- **输出/结果**：返回 `{payload, session}`，其中 `payload` 含 `{type:'report-confirmed', userId, orderId, templateId, templateName, runId, status, markdown, edited, rewritten}`。
- **验收标准**：
  - AC-1：四种状态拦截与 `PARTIAL` 缺项弹窗二次确认行为 100% 准确；重复提交相同已确认内容审计日志条数不变；改写后切回 `v1` 再次确认正确记录新审计。

#### FR-010 轻量化 `embed.html` 前端（含 `F2` 品牌图标）、双栏模拟台与全球保活页签

- **来源**：`frontend/embed.html`、`frontend/vite.config.ts`、`frontend/src/components/BrandMark.vue`、`frontend/src/embed/*`、`frontend/src/views/ChatSimView.vue`、`frontend/src/components/{ChatIframeTabPane.vue,ChatSimTemplatePicker.vue}`
- **描述**：构建完全剥离重型依赖的独立嵌入聊天页面，统一接入 `F2 智能光笔写单` 品牌视觉体系，并在管理端提供高保真模拟联调闭环。
- **关联用户故事/成功标准**：US4 / SC-001
- **业务规则**：
  1. **独立轻量构建与 F2 品牌图标接入**：`frontend/vite.config.ts` 将 `embed.html` 设为独立多页入口，严禁在 `src/embed/` 引入 Element Plus、CodeMirror 6、Pinia 或 Vue Router。`frontend/embed.html` 内联 `<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,..." />`（`F2 智能光笔写单` SVG 图标）；`ChatEmbedApp.vue` 复用零重型依赖组件 `frontend/src/components/BrandMark.vue`（基于 Vue 3 `useId()` 隔离 `#ra-f2-grad-*` 渐变 ID），在 52px 毛玻璃顶栏左侧渲染 `:size="22"`（`.assistant-brand-logo`）并在空会话欢迎英雄区渲染 `:size="46"`（`.welcome-brand-logo`）。
  2. **纯亮色等比舞台与自适应切换**：锁定 `color-scheme: light`，基于 `BASE_WIDTH = 1280`、`MIN_STAGE_HEIGHT = 640` 全幅无灰边缩放（`scaleFactor` 封顶 1.0），支持顶栏一键切换自适应模式并安全容错 `localStorage` 受限场景；全部浮层（入参浮层、记忆摘要浮层）、轻提示（`stageToast.ts` / `useStageFloatTip.ts`）、确认框（`StageConfirmDialog.vue`）及版本下拉框（`VersionSelect.vue`）均挂载于 `.embed-stage` 内。
  3. **居中对话流与 11 个专有组件**：在 `max-width: 840px` 中央消息列与底部 24px 圆角悬浮输入舱（`ChatInput.vue`，防中文 IME 误触）内，支持推荐卡片（`RecommendCard.vue`）、双列补参正则预检（`AskParamsCard.vue`）、双视图运行轨迹（`RunCard.vue` + `RawEventsTimeline.vue` + `O(1)` `markRaw` 追加）、行内紧凑报告卡片（`ReportInlineCard.vue` + 归档记忆水位线 + 改写消息下方自动绑定卡片并支持 `_backfill_legacy_rewrite_links` 历史兼容）以及三大支持页内全屏的居中弹窗（`PreviewDialog.vue` 三态分栏编辑、`TemplateStructureDialog.vue` 三栏检查器、`SwitchTemplateDialog.vue` 换模板检索）。
  4. **管理端左右双栏模拟联调台**：`ChatSimView.vue` 左栏提供工单参数、`online`/`draft` 版本切换、自动同步内存态 `REPORT_API_KEYS` 及 `ChatSimTemplatePicker.vue` 一键预填，点击打开后由顶部全局页签容器 `ChatIframeTabPane.vue` 全幅 `v-show` 保活承载 `/embed.html`，右栏实时展示双向 `postMessage` 日志与 `report-confirmed` 回传结果并响应 `chat-close-request` 自动闭合页签。
- **输入/触发**：用户打开 `/embed.html` 或管理端打开 `/#/chat-sim`。
- **输出/结果**：极简轻量化编译产物（`dist/embed.html` 仅预加载 `vue-core`、`BrandMark.vue`、`markdown-lib`、`icons` 等轻量 chunk）与完整模拟联调视图。
- **验收标准**：
  - AC-1：`npx vue-tsc --noEmit -p tsconfig.app.json` 0 错误、`npm run build` 成功生成独立 `dist/embed.html` 且不含 `element-plus` / `codemirror` 等重型 chunk。
  - AC-2：顶栏（22px）与欢迎区（46px）正确挂载 `BrandMark.vue`，`embed.html` 页签展示 F2 品牌 SVG 图标，模拟页可闭环完成选模板、补参、运行、改写、确认与自动关页签。

---

## 6. 非功能需求 【补充】

| 类型 | 编号 | 说明 | 验收方式 |
| --- | --- | --- | --- |
| 智能体防幻觉与隔离边界 | `NFR-001`（宪章 I、II） | 1. 路由知识全量封装于 `template-router/SKILL.md` 零业务硬编码；<br>2. `ChatAgent` 严禁注册调用网关或写文件工具，仅限 4 只读工具 + `@agent.output_validator` 自愈；<br>3. `memorySummary` 绝对隔离于 `AgentRunner` `<document>` 与填报证据链；`rewrite` 版本显式标注未校验 | `tests/test_chat.py`、`tests/test_chat_compaction.py`、`validate_all()` 静态门禁 |
| 单进程并发与锁序安全 | `NFR-002`（宪章 III） | 1. 基于 `workers=1` 单进程模型；`ChatStore` 严格遵从 `_stripe_lock(sid) -> _cache_guard` 锁序及 `write_json`（`fsync + os.replace`）原子落盘；<br>2. `ChatService` 仅持 `_SessionLock` 做状态读改写与单调水位锚点校验，所有大模型推理锁外异步执行；<br>3. `ChatRunManager` 返回前同步注册 `_RunChannel` 消灭订阅竞态 | `tests/test_review_api_chat.py` 并发冷读/清理竞态单测与 `tests/test_chat.py` 互斥校验 |
| 跨窗安全与全链路脱敏 | `NFR-003`（宪章 VI） | 1. `postMessage` 锁定 `event.source` 与首个 `lockedOrigin`，`apiKey` 不进 URL 与本地持久化存储；<br>2. 显式 `X-API-Key` 优先校验防 Cookie 降级；`X-Chat-Session-Id` 拦截跨会话探测；<br>3. `StepMapper.sanitize_error_text` 掩码 Bearer/Key/引号字面量/路径/长数字且截断至 120 字 | `tests/test_chat.py`、`tests/test_review_api_chat.py` 越权与脱敏用例 |
| 过程事件与审计留痕 | `NFR-004`（宪章 VII） | 每次运行与压缩进度实时经 SSE `status`/`step`/`raw`/`final`/`error` 推送并收尾；确认报告动作以服务端认证身份 `caller.name` 不可伪造记入 `DATA_DIR/audit.jsonl`（动作类型 `chat-confirm`） | 检查 `audit.jsonl` 审计结构与 `tests/test_chat.py` 幂等断言 |
| 前端轻量拆包与性能防卡顿 | `NFR-005`（宪章 V、VIII） | 1. `embed.html` 剥离重型 UI 包体积降约 80%（`embed` JS ~108KB + CSS ~80KB + `BrandMark` 4.2KB）；<br>2. 高频 SSE 原样事件使用 `markRaw` + `O(1)` 尾部追加避免全表排序与响应式性能损耗；<br>3. `ChatStore` 命中缓存零磁盘 I/O 与零线程切换 | `npm run build` 产物大小核查与 `ChatEmbedApp.vue` 代码审查 |
| 沙箱与跨域存储兼容性 | `NFR-006`（兼容可用性） | 在禁用 `localStorage`/`sessionStorage` 的第三方无痕环境或沙箱 `'null'` `origin` iframe 中，前端静默捕获异常并回退内存级 `currentApiKey` 与默认 `scaled` 模式，回传目标降级 `'*'` 保障核心流程不阻断 | 代码静态检查 `ChatEmbedApp.vue` / `chatApi.ts` 异常分支 |

---

## 7. 数据与存储需求 【补充】

| 数据对象/存储位置 | 变更类型 | 关键字段与口径 | 一致性/留存策略 | 关联需求 |
| --- | --- | --- | --- | --- |
| `DATA_DIR/chats/<sid[:2]>/<sid>.json` | 新增 | `sessionId`、`userId`、`orderId`、`target`、`inputs`、`inputSources`、`inputsVersion`、`document`、`fingerprint`、`seq`、`recommended`、`confirmed`、`confirmRecords`、`memorySummary`、`summarizedUpTo`、`messages` | 64 分片线程锁 + `write_json` 原子写盘 + 256 LRU 深拷贝缓存 + 会话协程锁；随 `RUNS_KEEP_DAYS` 定期清理 | FR-003, FR-006, FR-009 |
| `DATA_DIR/audit.jsonl` | 修改（新增动作） | `action="chat-confirm"`、`operator`（服务端 `caller.name`）、`sessionId`、`userId`、`orderId`、`runId`、`templateId`、`status`、`edited`、`rewritten` | 只追加写盘，重复确认幂等不重记；由 `Publisher.audit` 持久化 | FR-009 |
| `DATA_DIR/config/runtime/current.json` | 修改（新增配置） | 新增 16 项 `chat_*` 配置项及 `reportApiKeys` 联动读取 | `0600` 权限原子落盘，支持 `c1..cN` 修订回滚 | FR-006 |
| 内存态 `_RunChannel` & `_run_to_session` | 新增 | 实时脱敏 `steps`、`raw_events`、`asyncio.Condition`、`finished_mono`；`runId -> sessionId` 4096 条 LRU 索引 | 单进程驻留，已完成通道保留 `600s`（上限 `256` 条），进程重启自动失效并按 `RunStore` 与 `_heal_interrupted_in_place` 恢复 | FR-007 |

---

## 8. 外部接口与集成 【补充】

| 接口/系统 | 方向 | 交互内容 | 是否新增 | 关联需求 | 备注 |
| --- | --- | --- | --- | --- | --- |
| 外部工单宿主页面 ↔ `/embed.html` | 双向（`postMessage`） | `chat-ready`、`chat-init`、`report-confirmed`、`chat-close-request` | 是 | FR-001, FR-010 | 校验 `event.source` 与 `lockedOrigin`；契约见 `docs/chat-embed-api.md` §1 |
| 嵌入页 / 管理端模拟页 ↔ 平台后端 `/api/v1/chat/*` | 入站（HTTP REST / SSE） | 11 个会话/压缩/模板/运行/流式事件/原样记录/取消/确认端点 | 是 | FR-002 ~ FR-009 | 契约见 `docs/chat-embed-api.md` §2 & §4 |
| `ChatAgent` / `summarizer` → LLM 推理网关 | 出站（OpenAI 兼容 API） | 路由五动作结构化决策与滚动历史记忆摘要提炼 | 否（复用 `AgentRunner`） | FR-004, FR-006 | 共享 `AgentRunner` 模型、热更新配置与输出规格模式 |

### 8.1 出站网关与模型接口契约摘要（涉及时填写）

本需求不涉及新增或变更出站统一业务网关接口（`ChatAgent` 严格禁止调用外部业务网关）；模型调用沿用 `AgentRunner` 既有 `OpenAI` 兼容推理通道，仅新增 `submit_chat_action`（`ChatAction`）与 `submit_chat_summary`（`ChatSummaryOutput`）两个结构化输出契约。

### 8.2 三类独立交付物涉及情况

| 独立文档 | 涉及情况 | 判断依据与范围摘要 | 确认来源/日期及关联需求 |
| --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs/Dockerfile 中） | 本需求对外集成契约已由既有 `docs/chat-embed-api.md` 完整维护，本次为存量归档规范重构，不重复创建独立交付文档 | 归档拆分要求（2026-11-16）；FR-001, FR-002 |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs/Dockerfile 中） | 仅维护单个配套路由资源 `seed/skills/template-router/SKILL.md`，不涉及批量生产模板/契约迁移脚本改造 | 归档拆分要求（2026-11-16）；FR-005 |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs/Dockerfile 中） | 16 项 `chat_*` 参数均带默认值兜底并已纳入既有热更新及 `.env.example`，不涉及新增基础设施拓扑 | 归档拆分要求（2026-11-16）；FR-006 |

---

## 9. 边界与约束 【补充】

### 9.1 范围边界

**本次需求包含（In Scope）：**

- 后端 `src/report_agent/chat/` 全模块与 `src/report_agent/api/routes_chat.py` 11 个接口端点。
- `template-router/SKILL.md` 全模板路由编制及 `domain/resources.py` 路由双向交叉校验规则。
- 16 项 `chat_*` 参数接入 `config.py` / `runtime_config.py` 在线热更新体系。
- 前端独立多入口 `frontend/embed.html`（含内联 F2 SVG favicon）、`frontend/src/components/BrandMark.vue` 在顶栏与欢迎区的接入、`frontend/src/embed/*` 全部交互组件，以及管理端模拟联调台 `ChatSimView.vue` / `ChatIframeTabPane.vue` / `ChatSimTemplatePicker.vue`。
- `docs/chat-embed-api.md` 契约对齐及 `tests/test_chat.py`、`test_chat_compaction.py`、`test_review_api_chat.py` 自动化测试套件。

**本次需求不包含（Out of Scope）：**

- 核心填报引擎 `AgentRunner`、证据校验器 `EvidenceChecker` 与 12 个确定性工具的底层逻辑重构（分别归属 003/004 子规格，本需求仅通过 `RunRequest` 发起运行并消费 `ProcessEvent`）。
- 工作台四分区模板 IDE、CodeMirror 6 编辑器、API 可视化编排器与暗黑主题重构（归属 006 子规格）。
- 外部工单宿主系统的业务侧页面改造与生产 Nginx 运维变更。
- 脱离现有单进程模型引入 Redis/外部关系型数据库做分布式会话共享。

### 9.2 技术与业务约束

- 严禁在平台 Python/TS 源码内硬编码任何特定模板编号或业务路由规则，全量分流逻辑必须外置 `template-router/SKILL.md`。
- 前端 `frontend/src/embed/` 绝对禁止导入 `element-plus`、`codemirror`、`pinia` 或 `vue-router`，以保证独立入口轻量化与加载性能。
- `ChatAgent` 及其 `memorySummary` 绝对禁止访问网关或渗入 `AgentRunner` 的 `<document>` / 证据域。
- 所有存储互斥锁、内存通道 `_RunChannel` 与弱引用锁池均假设服务端按单进程 Uvicorn（`workers=1`）部署。

---

## 10. 异常场景与边界情况 【核心】

| 编号 | 场景描述 | 触发条件 | 预期处理方式 | 是否阻断主流程 | 优先级 | 关联需求 |
| --- | --- | --- | --- | --- | --- | --- |
| EX-001 | 历史存量 AI 改写消息缺失 `rewriteRunId` 关联 | 加载早期落盘的旧会话（助手改写回复未带 `rewriteRunId` / `rewriteVersionNo`） | 后端 `_backfill_legacy_rewrite_links`（5 秒窗口 + 正文 `runId` + 语义关键词）与前端 `rewriteTargetMap`（2 秒窗口）执行一对一消歧补全并渲染下方报告卡 | 否 | 中 | FR-010 |
| EX-002 | AI 改写复位后重新选回原版本提交确认 | 用户先确认 `v1`，经 AI 改写生成 `v2`（卡片 `confirmed` 复位为 `false`），随后在版本下拉框选回 `v1` 再确认 | 因当前卡片处于未确认态或 `rewritten`/`edited` 属性变化，不误判为幂等重放，正常生成新确认审计日志并刷新 `confirmed` | 否 | 高 | FR-009 |
| EX-003 | 跨会话探测他人 `runId` 越权访问 | 合法会话携带自己的 `X-Chat-Session-Id` 或 `?sessionId=` 请求他人 `runId` 的 `/events`/`/raw`/`/cancel`/`/confirm` | `_extract_expected_sid` 与 `resolve_session_for_run` 拦截不匹配或非法格式，统一返回 `404 RUN_NOT_FOUND` 不泄露信息 | 是（阻断越权请求） | 高 | FR-002 |
| EX-004 | 后端重启后遗留 `RUNNING` 卡片与 SSE 流异常收尾 | 进程重启内存 `_RunChannel` 清空时读取会话；或 SSE 泵内部捕获异常 | 读取视图时 `_heal_interrupted_in_place` 自动将无活跃通道卡片置为 `INTERRUPTED`；SSE 流捕获异常发送脱敏 `error` 帧并回收泵协程 | 否（自愈可重跑） | 高 | FR-007 |
| EX-005 | 第三方无痕或跨域沙箱禁用了 Web Storage / 传递 `'null'` origin | 宿主 iframe 启用严格 sandbox 或禁用 `localStorage` / `sessionStorage` | `readAdminToken()` 与 `readInitialScaleMode()` 捕获安全异常并退回内存变量和 `scaled` 模式；`postToParent` 遇到 `'null'` origin 自动降级为 `'*'` | 否 | 中 | FR-001, FR-010 |
| EX-006 | 自动记忆压缩失败或存储摘要字段损坏 | 自动摘要请求模型超时/异常；或历史 JSON 中 `summarizedUpTo` 越界/非整数 | 自动压缩失败记录脱敏警告日志后无感退回最近 `N` 条滑窗不阻断对话；`_effective_memory_state` 自动将损坏状态自愈为 `('', 0)`（手动 `/compact` 超时/失败返回 504/502） | 否（自动压缩） | 高 | FR-006 |

---

## 11. 待确认事项 【核心】

> 所有已确认或澄清闭环的问题均在此沉淀追踪。

| 编号 | 问题描述 | 影响范围 | 责任方 | 期望确认日期 | 状态 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| Q-001 | 嵌入页 `F2 智能光笔写单` 品牌图标在轻量独立入口中的复用方式（是否需要单独切 SVG 静态文件还是随轻组件按需加载） | `frontend/embed.html`、`ChatEmbedApp.vue`、`BrandMark.vue` | 前端架构 | 2026-11-16 | 已关闭 | 确认 `embed.html` `<link rel="icon">` 采用内联 F2 SVG data URI 免额外请求，`ChatEmbedApp.vue` 直接复用零重型依赖组件 `BrandMark.vue`（仅 ~4.2KB chunk，隔离 `useId()` 渐变 ID） |
| Q-002 | 外部工单系统是否必须配合部署多节点 Redis 以支撑嵌入聊天窗口会话状态 | `ChatStore`、`ChatRunManager` | 平台架构 | 2026-11-16 | 已关闭 | 确认沿用单进程 `workers=1` 部署契约（由 `cli.py` 与 `docker-entrypoint.sh` 强制锁定），无须引入外部 Redis/数据库，无未关闭阻塞问题 |

---

## 附录：原始需求描述 【补充】

```text
智能申告报告填写与资源治理平台（report-agent）全栈研发工作拆分（RA-007 / 33.0 人天）：
负责外部工单系统 iframe 嵌入式聊天窗口（postMessage 握手与 origin 锁定、双轨防劫持鉴权、
64 分片会话持久化与入参指纹演进）、受限只读 ChatAgent 结构化路由、锁外异步增量滚动记忆压缩、
SSE 双视图断点续接、三级确认审计、embed.html 与 ChatEmbedApp.vue 中接入 F2 品牌图标与 BrandMark.vue，
以及工作台左右双栏模拟联调台。
```

---

## 变更记录（Changelog）

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | AiCoding (codex) | 基于初期 Spec Kit 模板完成 007 子规格归档整理（4 US、FR-001~010、33.0 人天） |
| 2.0 | 2026-11-16 | AiCoding (codex) | 按改造后中文 Spec-Kit 与 `/sdd-documentation` 标准重构全章节，核对分级取证来源，补充 `embed.html` 内联 F2 品牌图标与 `ChatEmbedApp.vue` 复用 `BrandMark.vue` 实事，并核准三类独立交付物台账 |

---

## 增量更新说明

> 本文档按 `report-agent` 中文 Spec-Kit 模板与 SDD 取证规范生成并定稿归档；后续若新增聊天端点、调整 `postMessage` 协议或变更嵌入入口品牌资源，须同步更新对应章节与 `变更记录` 并联动刷新 `plan.md` 与 `tasks.md`。
