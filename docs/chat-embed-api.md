<!-- #Created By AiCoding(codex) -->
# 嵌入式聊天选模板窗口 · 前后端对接契约

`/embed.html?userId=<u>&orderId=<o>` 采用 **ChatGPT Web PC 端单栏居中流式对话架构（纯亮色 Light-Only，`max-width: 840px` 居中会话流 + 底部 24px 大圆角悬浮输入舱 + 页内大尺寸居中详情弹窗）** 设计。推荐外部工单系统以**系统内的全幅页内 Tab 页签（In-Page Tab）**承载无边框 `<iframe>` 打开。页面挂载后先与父页面握手获取鉴权 key、结构化入参与单据，再由聊天路由 Agent 在居中对话流内推送模板推荐卡片；用户选中模板后运行填报，可在对话流内联运行卡片实时查看进度、直接查看与复制生成报告，或呼出大尺寸报告编辑对比弹窗、模板结构预览弹窗与全部模板检索弹窗（均支持页内全屏切换），确认后回传给父页面。

## 1. 父页面 ↔ iframe 协议（postMessage）

| 方向 | 消息 | 说明 |
|------|------|------|
| iframe → 父 | `{type:'chat-ready', userId, orderId}` | 加载后每 500ms 发一次，收到 init 后停止；10s 内没收到 init 时页面显示「未收到上层参数」 |
| 父 → iframe | `{type:'chat-init', apiKey, inputs, document, target?}` | `inputs` 为对象（值转字符串）；`target` 只有管理端模拟页会传 `'draft'` |
| iframe → 父 | `{type:'report-confirmed', userId, orderId, templateId, templateName, runId, status, markdown, edited, rewritten}` | 确认接口成功后发送 |
| iframe → 父 | `{type:'chat-close-request'}` | 紧跟在 report-confirmed 之后发送，由父页面决定关闭该页内 Tab 页签或隐藏 iframe |

- **宿主校验与 `origin` 锁定**：聊天页优先取 `window.parent !== window` 的父页面作为宿主窗口（若单独通过 `window.opener` 打开亦做兼容回退），严格校验 `event.source` 等于当前宿主窗口，并在**首次收到 `chat-init` 时锁定 `event.origin`**，后续只接受该 `origin` 的消息，回传时 `targetOrigin` 也固定使用该 `origin`（同源管理端模拟页同样适用）
- 父页面可以随时再发一次 `chat-init` 更新入参，iframe 会重新调用 `POST /chat/sessions`
- `apiKey` 只保存在内存中，不写入 URL 或持久存储

## 2. 鉴权与会话隔离

所有 `/api/v1/chat/*` 接口满足以下任一条件即可调用：
- 请求头 `X-API-Key`（服务端配置了 `REPORT_API_KEYS` / `reportApiKeys` 时必须有效；未配置则不校验。若显式携带非空 `X-API-Key` 则先校验 Key 有效性，错误 Key 即便有管理端登录态也立即返回 401；Key 通过后再识别管理端身份以兼容模拟页使用 `target='draft'`）
- 管理端登录态（Cookie `ra_session` 或 `Authorization: Bearer`）：供管理端模拟页使用，且只有这种方式允许 `target='draft'`

chat-init 中的 `apiKey` 为空时不带 `X-API-Key`（同源模拟页依赖 Cookie / Bearer）。

跨会话 `runId` 防越权：`/api/v1/chat/runs/{runId}/{events,raw,cancel,confirm}` 支持可选请求头 `X-Chat-Session-Id: <sessionId>` 或可选查询参数 `?sessionId=<sessionId>`（未传时保持向后兼容）；一旦传入非空值但格式非法或与 `runId` 实际所属会话不一致，服务端统一返回 `404 RUN_NOT_FOUND`。

## 3. 数据结构

```ts
type RunStatus = 'RUNNING' | 'SUCCESS' | 'PARTIAL' | 'FAILED' | 'CANCELLED' | 'INTERRUPTED'

interface ChatSession {
  sessionId: string; userId: string; orderId: string; target: 'online' | 'draft'
  createdAt: string; updatedAt: string
  inputs: Record<string, string>
  inputSources: Record<string, '上层' | '用户补充'>
  inputsVersion: number            // 上层入参指纹每变化一次 +1
  documentChars: number
  activeRunId: string | null
  confirmed: { runId: string; templateId: number; templateName: string; confirmedAt: string;
               edited: boolean; rewritten: boolean } | null
  messages: ChatMessage[]
  created?: boolean                // 仅 POST /sessions 返回
  inputsChanged?: boolean          // 仅 POST /sessions 返回
}

interface BaseMessage { id: string; role: 'user' | 'assistant' | 'system'; createdAt: string }

type ChatMessage = BaseMessage & (
  | { kind: 'text'; text: string; rewriteRunId?: string; rewriteVersionNo?: number }  // AI 改写回复携带关联 runId 与新版本号（存量历史会话自动补全）
  | { kind: 'divider'; text: string }                       // 「入参已更新」等分隔
  | { kind: 'recommend'; text: string; items: RecommendItem[] }
  | { kind: 'ask_params'; text: string; templateId: number; templateName: string; params: ParamSpec[] }
  | { kind: 'run' } & RunCard
  | { kind: 'confirmed'; text: string; runId: string }
)

interface RecommendItem { templateId: number; templateName: string; reason: string;
  level: '高' | '中' | '低'; missingRequired: string[]; offline: boolean }

interface ParamSpec { key: string; required: boolean; description: string; sample: string;
  pattern: string | null; value: string; error: string | null }

interface RunCard {
  runId: string; templateId: number; templateName: string; status: RunStatus
  rev: string; inputsVersion: number
  stale: boolean                   // 入参已更新，属于旧入参
  templateOffline: boolean         // 模板已下线：可以确认，禁止重跑
  steps: RunStep[]                 // 结束后保存全部步骤；运行中可能只有部分步骤，需配合 events 接口
  durationMs: number; error: string | null
  missingShown: string[]; foundCount: number; totalCount: number
  versions: ReportVersion[]        // 第一条为 original；改写时追加 rewrite
  confirmed: boolean               // 当前版本栈已确认；触发 AI 改写生成未确认新版本时自动复位为 false
}

interface ReportVersion { no: number; kind: 'original' | 'rewrite'; markdown: string;
  createdAt: string; note: string }   // rewrite 版本未经证据校验，界面上必须醒目标记

interface RunStep { seq: number; atMs: number;
  icon: 'start' | 'skill' | 'api' | 'filter' | 'tool' | 'check' | 'warn' | 'error' | 'done'
  text: string; ok: boolean }

interface RawProcessEvent {
  seq: number; type: string; atMs: number; round: number
  [key: string]: unknown
}

interface TemplatePreview {
  templateId: number; templateName: string; description: string
  offline: boolean; rev: string
  bodyText: string                 // Jinja2 模板原稿
  sampleMarkdown: string           // 按枚举首项/默认值/占位符预填充渲染后的样例正文
  inputs: Array<{ key: string; required: boolean; description: string; sample: string;
                  pattern: string | null; currentValue: string }>
  fields: Array<{ name: string; type: 'string' | 'enum' | 'date' | 'list';
                  values: string[]; columns: Array<{ name: string; type: string; values: string[] }>;
                  description: string }>   // 仅包含 visible=true 且剥离 Java 历史对照注释后的字段
}
```

## 4. 接口（前缀 `/api/v1/chat`）

| 接口 | 请求 | 响应 |
|------|------|------|
| `POST /sessions` | `{userId, orderId, inputs, document, target?}` | `ChatSession`（同一 userId+orderId 恢复原会话；入参指纹变化时 `inputsChanged=true`，并追加 divider 消息，旧 run 卡片 `stale=true`） |
| `GET /sessions/{sid}` | — | `ChatSession` |
| `POST /sessions/{sid}/messages` | `{text, auto?}` | **SSE**：`status` `{text}`；`message` `ChatMessage`（**按 id upsert**：同 id 表示更新，例如改写后的 run 卡片；动作为 `rewrite` 时还会追加携带 `rewriteRunId` 与 `rewriteVersionNo` 的助手 `text` 消息）；`error` `{code, message}`；最后 `done` `{session}`。`auto=true` 表示打开时的自动推荐（不产生用户消息）。动作为运行时会返回一条 `RUNNING` 的 run 消息，前端随后订阅其 events |
| `GET /sessions/{sid}/templates?q=` | — | `[{templateId, templateName, description, offline, recommendLevel, lastStatus}]`（换模板弹窗用：本次推荐结果排在前面，`lastStatus` 为本会话最近一次运行状态） |
| `GET /sessions/{sid}/templates/{templateId}` | — | `TemplatePreview`（模板结构详情、入参当前值、可见字段说明与样例填充预览；已下线模板仍允许预览并标记 `offline=true`；不存在返回 `404 TEMPLATE_UNAVAILABLE`） |
| `POST /sessions/{sid}/runs` | `{templateId, inputs?}` | `{message: ChatMessage, session: ChatSession}`：缺少必填参数或格式不对时返回 `ask_params` 消息，否则返回 `RUNNING` 的 run 消息。`inputs` 合并到会话并标记来源为「用户补充」。错误：`409 RUN_IN_PROGRESS`、`404 TEMPLATE_UNAVAILABLE` |
| `GET /runs/{runId}/events?after=N&includeRaw=0&rawAfter=M` | 也支持 `Last-Event-ID` 请求头 | **SSE**：`step`（`id: seq`，data 为 `RunStep`）；当 `includeRaw=1` 时一并推送 `raw`（无 `id`，data 为 `seq > rawAfter` 的 `RawProcessEvent`）；结束时发 `final`（data 为更新后的 run `ChatMessage`），然后断开；每 15s 发一次 `: keep-alive`。已结束的运行会先重放游标之后的 `raw`（若启用）与 `step`，再发 `final` |
| `GET /runs/{runId}/raw` | — | `{runId, status, events: RawProcessEvent[]}`（按需拉取某次运行的原始过程事件：优先读内存通道，淘汰后从 `RunStore` 持久化记录读取；校验归属当前聊天会话与 `draft` 权限） |
| `POST /runs/{runId}/cancel` | — | `{ok: true}` |
| `POST /runs/{runId}/confirm` | `{markdown, acknowledgePartial?}` | `{payload, session}`，payload 即 report-confirmed 消息体。错误：`400 NOT_CONFIRMABLE`（FAILED/RUNNING/CANCELLED/INTERRUPTED）、`409 PARTIAL_NEEDS_ACK`（返回 `missingShown`）。重复确认是幂等的 |

`edited` = 提交的 markdown 与最新版本不同；`rewritten` = 最新版本是 rewrite。

## 5. 交互要点

- **纯亮色单栏全幅等比缩放舞台与自适应回退**：嵌入页锁定明亮清爽的纯亮色（`color-scheme: light`，不受管理端暗色主题影响），默认启用基于桌面宽屏基准 `BASE_WIDTH = 1280`、`MIN_STAGE_HEIGHT = 640` 的全幅等比例缩放（动态计算 `stageW = Math.max(BASE_WIDTH, vw / s)` 与 `stageH = vh / s` 100% 铺满整个浏览器窗口，消除两侧留白灰边；全部详情弹窗、确认框与轻提示挂载在 `.embed-stage` 内同屏等比缩放），52px 极简毛玻璃顶栏提供「工单入参」页内浮层、「等比缩放 / 自适应」回退按钮、「浏览全部模板」与「关闭窗口」入口
- **ChatGPT Web 风格居中对话流 + 内联业务卡片 + 页内全屏详情弹窗**：彻底取消左右分栏挤压，所有对话与动作均收敛于中央 `max-width: 840px` 流式消息列与底部 24px 圆角悬浮输入舱（`ChatInput.vue`）：
  1. `内联推荐与补参卡片`：`RecommendCard.vue` 在消息流内展示推荐理由、匹配度与缺失必填项，支持一键「预览模板」或「使用此模板」；缺参时在流内展示 `AskParamsCard.vue` 双列补参表单
  2. `内联运行与报告成果卡（RunCard.vue + 行内报告文档卡片）`：运行过程支持折叠/展开并一键切换脱敏「精简步骤」与按轮次展示的「原样运行记录（`RawEventsTimeline.vue`）」；运行完成后直接在流内渲染可阅读的报告正文卡片，且当用户在对话中触发 AI 改写（`action='rewrite'`）时，最新助手简短改写说明气泡下方同样直接渲染对应改写版本的完整报告卡片（含 `AI 改写 vN` 标识、版本切换、AI 改写未校验提示横幅、「复制」、「⤢ 弹窗预览 / 编辑」、「换模板」、「重新核查」与「✓ 确认使用此报告」；针对升级前的历史存量会话，后端 `_build_view` 会一对一自动补齐 `rewriteRunId` 与 `rewriteVersionNo`）
  3. `三大页内居中弹窗（均支持 ⤢ 页内全屏 / ⤡ 退出全屏）`：`PreviewDialog.vue`（`渲染预览 | Markdown 源码编辑 | 左右分栏实时对比` 三态报告审阅与确认回传）、`TemplateStructureDialog.vue`（填充效果样例、Jinja2 原稿、入参当前值与可见核查字段清单）及 `SwitchTemplateDialog.vue`（双列卡片检索全部模板，支持查看结构或立即运行）
- **管理端右侧全局多页签栏 + 模拟联调双栏工作台**：管理端壳层（`App.vue` + `WorkspaceTabsBar.vue`）基于 Element Plus `ElTabs` 与 `SortableJS` 提供统一的右侧顶部全局多页签导航（路由页签 `<KeepAlive>` 保活 + 未保存草稿拦截 + 拖拽重排 + 快捷关闭菜单）。`/#/chat-sim`（`ChatSimView.vue`）采用清爽的 PC 左右双栏卡片布局（左栏配置父页面参数与单据，右栏支持页签切换或上下分栏查看 `postMessage` 实时报文流与 `report-confirmed` 回传报告）；点击「在顶部新页签打开聊天窗口」即在全局页签栏新增并激活 `智能填报 · <orderId>` 页签，由 `ChatIframeTabPane.vue` 以 `100% × 100%` 全幅承载无边框 `/embed.html` `<iframe>`（`v-show` 保活不重载），收到 `chat-close-request` 自动关闭该聊天页签并切回模拟页展示确认报告
- 每个会话同时只能有一个运行；运行中禁用「换模板 / 重跑 / 确认」，并显示「停止」
- PARTIAL 确认前弹窗列出 `missingShown` 二次确认；FAILED 不允许确认
- `stale` 卡片显示「旧入参」角标；`templateOffline` 卡片提示「该模板已下线」并禁止重跑
- 断线或刷新后：加载 session，存在 `activeRunId` 时用 `after=<已有最大 seq>`（及 `includeRaw=1&rawAfter=<已有最大 raw seq>`）续接 events；历史运行切换到「原样运行记录」时按需请求 `GET /runs/{runId}/raw`
