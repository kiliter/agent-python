---
title: Vue 3 资源工作台前端剖析
type: component
tags: [component, frontend, vue3, workbench, codemirror, sse]
sources:
  - frontend/package.json
  - frontend/vite.config.ts
  - frontend/embed.html
  - frontend/src/App.vue
  - frontend/src/assets/styles.css
  - frontend/src/router/index.ts
  - frontend/src/stores/platform.ts
  - frontend/src/stores/workspaceTabs.ts
  - frontend/src/components/WorkspaceTabsBar.vue
  - frontend/src/components/ChatIframeTabPane.vue
  - frontend/src/components/GlobalDrawers.vue
  - frontend/src/components/workbench/WorkbenchTemplateStage.vue
  - frontend/src/components/workbench/WorkbenchRightInspector.vue
  - frontend/src/api/platformApi.ts
  - frontend/src/utils/jinjaBody.ts
  - frontend/src/utils/sse.ts
  - frontend/src/utils/markdown.ts
  - frontend/src/utils/textDiff.ts
  - frontend/src/utils/timelineFormat.ts
  - frontend/src/utils/clipboard.ts
  - frontend/src/views/TemplatesListView.vue
  - frontend/src/views/SkillsView.vue
  - frontend/src/views/ApisView.vue
  - frontend/src/views/ChatSimView.vue
  - frontend/src/views/SettingsView.vue
  - frontend/src/types/platform.ts
  - docs/frontend-api-handoff.md
  - docs/chat-embed-api.md
updated: 2026-11-13
---

# Vue 3 资源工作台前端剖析

<!-- #Created By AiCoding(codex) -->

`frontend/` 基于 **Vue 3.5 + TypeScript 5.8 + Vite 6 + Pinia 3 + Element Plus + CodeMirror 6** 构建，采用 Vite 多页入口同时产出两套前端应用（全部数据直接对接后端 `/api/v1` 真实接口，无本地写死 Mock 回退）：
1. **资源治理工作台（`index.html`）**：面向业务维护人员与平台管理员的可视化资源 IDE、版本治理与联调中心；
2. **嵌入式聊天选模板窗口（`embed.html` + `src/embed/`）**：供外部工单系统以 iframe 嵌入的轻量对话选模板与报告确认页，绕开工作台登录导航守卫，通过 `postMessage` 与父页面握手通信（详见 [嵌入式聊天选模板窗口组件剖析](chat-embed.md)）。

## 1. 工作台路由视图全景（`frontend/src/router/index.ts`）

主工作台采用 Hash 路由（`createWebHashHistory`），并在路由守卫中通过 `GET /api/v1/auth/me` 校验登录态。全部核心页面视图（`frontend/src/views/`）均采用动态路由懒加载（`() => import(...)`），配合 `vite.config.ts` 的精细化分包策略（拆分 `vue-core`、`vue-state`、`markdown-lib`、`icons`、`element-plus`、`element-deps`、`codemirror`、`workbench-libs`，使 `codemirror` 与 `workbench-libs` 按需在进入编辑器视图时加载，同时让独立入口 `embed.html` 完全剥离 `element-plus` 与 `codemirror`），大幅降低首屏加载体积：

| 路由路径 | 视图组件 | 核心功能 |
|----------|----------|----------|
| `/login` | `LoginView.vue` | 工作台账号密码登录，展示锁定倒计时与错误提示 |
| `/templates` | `TemplatesListView.vue` | 33+ 模板总览表格、状态筛选（已发布 / 有草稿 / 草稿 / 已下线）、新建/复制/下线/恢复；关联 Skill 规程列采用 `.ref-count-pill` 计数胶囊 + 限高滚动 `<el-popover>`（`.ref-popover-panel` / `.ref-popover-list`） |
| `/workbench` | `TemplateWorkbenchView.vue` | **核心 IDE 式模板工作台**：左栏导航（字段 / 入参 / Skill / 用例 / 历史）、中栏双模式编辑器（代码 / 实时预览 / 分屏 / 版本 Diff）、右栏属性检查器与 SSE 试运行证据溯源 |
| `/skills` | `SkillsView.vue` | 纯文本 `SKILL.md` 在线编辑器（含 11 个填报 Skill 与聊天路由 `template-router`）；「核查业务规程摘要」单行省略配 `<el-tooltip>` 悬浮查看全文，「被核查模板引用」采用全局 `.ref-popover-list` 限高滚动面板（`max-height: 240px`），避免列表过长撑大页面 |
| `/apis` | `ApisView.vue` | 网关接口契约管理：可视化表单（`ApiVisualEditor`）与原始 YAML 双模式编辑及在线拨测；接口说明单行省略配 `<el-tooltip>` 悬浮提示，关联 Skill 规程列与 `SkillsView.vue` 一致采用数量胶囊 + 限高滚动 `<el-popover>` |
| `/runs` | `RunsView.vue` | 历史运行审计台账：多维检索（含 `聊天窗口` 入口）、查看单次运行的渲染报告、完整推理轨迹与证据定位，支持一键“保存为回归用例” |
| `/regression` | `RegressionView.vue` | 模板回归测试用例管理与单条试跑验证 |
| `/releases` | `ReleasesView.vue` | 全局版本时间线（`r1`..`rN`）、版本间资源变更 Diff 对比及生产紧急版本切换（`emergency-switch`） |
| `/chat-sim` | `ChatSimView.vue` | **嵌入式聊天窗口模拟联调台（PC 左右双栏工作台 + 右侧全屏聊天联动）**：左栏配置 `userId`/`orderId`/`target`/`apiKey`（挂载自动带出系统 Key、支持同步/复制/跳转系统设置）、通过 `ChatSimTemplatePicker.vue` 预填模板入参或载入回归用例、编辑 `inputs` 与 `document`，点击「打开聊天窗口」在右侧全屏承载 `/embed.html` 聊天窗口（`.main-wrapper.is-chat-fullscreen` 自动隐藏 `.topbar` 与全局页签栏以最大化可视区域，点击左侧导航或回传 `chat-close-request` 返回双栏联调台查看 `postMessage` 实时报文流与确认回传报告） |
| `/settings` | `SettingsView.vue` | 系统提示词编辑与版本回退、48 项引擎/网关/工具/聊天与上下文压缩运行期配置在线热更新、一键恢复默认参数及 `c1`..`cN` 修订回滚 |

## 2. 核心交互组件（`frontend/src/components/`）

| 组件文件 | 职责说明 |
|----------|----------|
| `WorkspaceTabsBar.vue` + `ChatIframeTabPane.vue` | **右侧全局多页签导航与动态聊天保活面板**：基于 Element Plus `<el-tabs type="card">` + `SortableJS` 拖拽重排（锁死固定首页签 `核查模板`，重排前还原 DOM 顺序再由 Pinia `splice` 驱动避免 VNode 错位）+ `<el-dropdown>` 快捷关闭菜单（关闭当前/其他/右侧/全部可关页签），适配亮/暗双主题；`ChatIframeTabPane.vue` 以 `100% × 100%` 承载无边框 `/embed.html` `<iframe>`（`v-show` 保活，激活时 `App.vue` 通过 `.main-wrapper.is-chat-fullscreen` 隐藏 `.topbar` 与页签栏实现右侧全屏展示，严格校验同源 `origin` 与 `event.source` 执行 `chat-ready` ↔ `chat-init` 握手及回传） |
| `CodeMirrorEditor.vue` + `WorkbenchTemplateStage.vue` + `src/utils/jinjaBody.ts` | 基于 CodeMirror 6 定制的 Jinja2 / Markdown / YAML 代码编辑器与共享词法作用域分析器（`analyzeJinjaBody` / `renameJinjaBodyVariable`），完整识别 `{{ }}` / `{% %}` / `{# #}`、`{% for item in 列表 %}` 循环绑定变量、`| filter` 与 `is [not] hasDigit` 测试，支持 `{{字段名}}` 芯片高亮、零误报未定义变量提示、字段重命名同步替换输出块与控制块，以及携带内存编辑态 `fields` 的实时沙箱渲染预览联动 |
| `WorkbenchDebugPanel.vue` | 模板在线试运行入参表单与单据面板：对声明了 `pattern` 的入参自动执行 `.trim()` 与整串锚定 `^(?:...)$` 校验（对齐后端 `safe_regex_fullmatch`） |
| `ApiVisualEditor.vue` | 将复杂的 `apis/*.yaml`（连接器类型、JSON Schema 入参表、请求报文映射、`noData`/`success` 判定条件、多模式记录抽取列）转化为直观表单双向同步编辑，原生对齐后端 `BUILTIN_PLACEHOLDERS`（识别 `${$now}` 内置动态占位符、拦截非法 `$xxx` 参数名） |
| `AgentTimeline.vue` + `src/utils/timelineFormat.ts` | 消费 `/dryrun/stream` SSE 事件流，与聊天窗 `RawEventsTimeline.vue` 共享轮次（`round`）归并与全部 12 个平台工具的格式化逻辑（支持批量 `load_skill(names)` 存在性校验跳转、`query_result` 多表/OR 参数展示），并以醒目红色卡片标出 `report_rejected`（证据校验退回）与 `report_degraded`（降级）步骤 |
| `FieldEvidenceTable.vue` + `EvidenceSourceInspector.vue` | 字段核验结果表与三页签证据溯源检查器：点击任一字段（包括列表字段展开的子行），右侧自动跳转至对应网关结果集 `resultId` 高亮目标行/列，或跳转至单据原文高亮 `Lxxx` 行，或高亮工单入参 |
| `ReportPreviewContent.vue` | 最终报告渲染展示面板，支持点击已填入的字段值反向联动定位右侧证据源 |
| `WorkbenchRightInspector.vue` + `GlobalDrawers.vue` + `GlobalModals.vue` | `WorkbenchRightInspector.vue` 内联承载字段精细属性配置（类型、`list` 子列编辑器、证据等级、`quoteWhole`、日期 `format`、缺失回退策略，重命名自动携带 `originalName`）与回归用例编辑；`GlobalDrawers.vue` 按需懒挂载（`v-if="store.activeDrawer"`）承载双版本回归差异溯源抽屉（`reg-diff-detail`）；`GlobalModals.vue` 承载发布前校验弹窗与 409 `DRAFT_CONFLICT` 多人编辑冲突对比弹窗 |
| `src/utils/{sse,markdown,textDiff,clipboard}.ts` | 跨工作台与嵌入窗复用的零过度抽象基础工具：统一 SSE 流读取与取消释放（`readSseStream`）、带 32 条目 LRU 缓存的 `marked` + `sanitizeHtml` 安全渲染（`renderSafeMarkdown`）、行级对比与上下文折叠（`diffLines`）及剪贴板复制（`copyToClipboard`） |
| `SettingsView.vue`（引擎与系统设置） | 覆盖全部 **48 项**运行期配置的分栏展示（`gatewaySpecRows` / `engineSpecRows` / `chatSpecRows`）与 4 组在线热更新编辑表单（含新增的「3. 聊天会话与滚动上下文压缩配额」与「4. 平台工具限额与历史数据留存」分组）：通过 `DEFAULT_RUNTIME_CONFIG` 与 `parseNumOrDefault` 对空值/缺省项自动兜底回填默认值，并做 `agentQueryMaxLimit >= agentQueryDefaultLimit`、`chatCompactTriggerMessages > chatCompactKeepRecent` 前端预校验；提供「恢复默认参数」按钮（`handleResetDefaultParams`）仅重置数值/配额/枚举模式并保护 `gatewayUrl`、`llmBaseUrl`、`llmModel` 与已填密钥；Tab 3（引擎与网关配置回滚）通过 `COMPARE_CONFIG_KEYS` 与 `RUNTIME_KEY_LABELS` 呈现全量 48 项中文对照与历史快照差异对比 |

## 3. 全局状态与并发安全协同（`stores/platform.ts` + `stores/workspaceTabs.ts`）

- **全局工作区多页签与保活拦截（`App.vue` + `stores/workspaceTabs.ts`）**：`App.vue` 在 `.main-content` 内以 `<KeepAlive :max="12">` 缓存路由模块页签，并与 `v-for` + `v-show` 渲染的动态聊天窗口页签并列保活；切换或关闭含未保存草稿的编辑页签（含从运行记录执行 `loadRunIntoDryRun` 跨模板跳转）时强制二次确认拦截（取消则保持原页签与试运行预设不变），顶部页签切回 `skills`/`apis`/`runs` 自动恢复详情子视图，退出登录（`currentNav === 'login'`）自动调用 `tabsStore.resetAll()` 销毁全部动态聊天页签与内存密钥。
- **本地工作区缓冲、异步竞态防护与响应式降载**：在 `TemplateWorkbenchView` 中修改正文、入参时更新 Pinia 内存状态并标记 `dirty`（`loadSettings` 对系统提示词同样启用 `preserveDirty` 脏草稿保护）；整包保存（`PUT /templates/{id}/draft`）与所有细粒度变更操作均携带当前 `draft.revision` 并在成功后写回新 `revision`。快速切换模板、修订、运行记录与设置时通过递增请求序号守卫丢弃过期异步响应，并对 `dryRunEvents`、`RunDetail` 大数组及聊天 `rawEvents` 使用 `markRaw` 消除深层 Proxy 开销。
- **SSE 实时流解析（`api/platformApi.ts` + `utils/sse.ts`）**：基于 `fetch` + `ReadableStream` 的共享 `readSseStream` 解析标准 `event: event` / `event: final` / `event: error` 帧（兼容 `\r\n` 与尾帧 flush，异常或 `AbortController` 取消时强制 `reader.cancel()` 释放连接）。

## 相关页面

- [环境变量与运行期配置参考](../reference/configuration.md)
- [嵌入式聊天选模板窗口组件剖析](chat-embed.md)
- [FastAPI 路由与鉴权组件剖析](api-and-auth.md)
- [AgentRunner 运行时组件剖析](agent-runner.md)
- [新增与维护报告模板实操指南](../guides/add-template.md)
- [本地开发、测试与部署指南](../guides/dev-test-and-deploy.md)
