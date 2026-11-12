---
title: Vue 3 资源工作台前端剖析
type: component
tags: [component, frontend, vue3, workbench, codemirror, sse]
sources:
  - frontend/package.json
  - frontend/vite.config.ts
  - frontend/embed.html
  - frontend/src/App.vue
  - frontend/src/router/index.ts
  - frontend/src/stores/platform.ts
  - frontend/src/stores/workspaceTabs.ts
  - frontend/src/components/WorkspaceTabsBar.vue
  - frontend/src/components/ChatIframeTabPane.vue
  - frontend/src/api/platformApi.ts
  - frontend/src/views/ChatSimView.vue
  - docs/frontend-api-handoff.md
  - docs/chat-embed-api.md
updated: 2026-11-12
---

# Vue 3 资源工作台前端剖析

<!-- #Created By AiCoding(codex) -->

`frontend/` 基于 **Vue 3.5 + TypeScript 5.8 + Vite 6 + Pinia 3 + Element Plus + CodeMirror 6** 构建，采用 Vite 多页入口同时产出两套前端应用（全部数据直接对接后端 `/api/v1` 真实接口，无本地写死 Mock 回退）：
1. **资源治理工作台（`index.html`）**：面向业务维护人员与平台管理员的可视化资源 IDE、版本治理与联调中心；
2. **嵌入式聊天选模板窗口（`embed.html` + `src/embed/`）**：供外部工单系统以 iframe 嵌入的轻量对话选模板与报告确认页，绕开工作台登录导航守卫，通过 `postMessage` 与父页面握手通信（详见 [嵌入式聊天选模板窗口组件剖析](chat-embed.md)）。

## 1. 工作台路由视图全景（`frontend/src/router/index.ts`）

主工作台采用 Hash 路由（`createWebHashHistory`），并在路由守卫中通过 `GET /api/v1/auth/me` 校验登录态。全部核心页面视图（`frontend/src/views/`）均采用动态路由懒加载（`() => import(...)`），配合 `vite.config.ts` 的 `workbench-libs` 分包策略（隔离 Element Plus / CodeMirror 重型依赖），消除首屏 `/login` 预加载大包开销：

| 路由路径 | 视图组件 | 核心功能 |
|----------|----------|----------|
| `/login` | `LoginView.vue` | 工作台账号密码登录，展示锁定倒计时与错误提示 |
| `/templates` | `TemplatesListView.vue` | 33+ 模板总览卡片/表格、状态筛选（已发布 / 有草稿 / 草稿 / 已下线）、新建/复制/下线/恢复 |
| `/workbench` | `TemplateWorkbenchView.vue` | **核心 IDE 式模板工作台**：左栏导航（字段 / 入参 / Skill / 用例 / 历史）、中栏双模式编辑器（代码 / 实时预览 / 分屏 / 版本 Diff）、右栏属性检查器与 SSE 试运行证据溯源 |
| `/skills` | `SkillsView.vue` | 纯文本 `SKILL.md` 在线编辑器（含 11 个填报 Skill 与聊天路由 `template-router`）、关联接口标签、被引用模板追踪与独立发布回退 |
| `/apis` | `ApisView.vue` | 网关接口契约管理：支持可视化表单（`ApiVisualEditor`）与原始 YAML 双模式编辑，内置在线参数拨测与报文预览 |
| `/runs` | `RunsView.vue` | 历史运行审计台账：多维检索（含 `聊天窗口` 入口）、查看单次运行的渲染报告、完整推理轨迹与证据定位，支持一键“保存为回归用例” |
| `/regression` | `RegressionView.vue` | 模板回归测试用例管理与单条试跑验证 |
| `/releases` | `ReleasesView.vue` | 全局版本时间线（`r1`..`rN`）、版本间资源变更 Diff 对比及生产紧急版本切换（`emergency-switch`） |
| `/chat-sim` | `ChatSimView.vue` | **嵌入式聊天窗口模拟联调台（PC 左右双栏工作台 + 联动全局页签栏）**：左栏配置 `userId`/`orderId`/`target`/`apiKey`（挂载自动带出系统 Key、支持同步/复制/跳转系统设置）、通过 `ChatSimTemplatePicker.vue` 预填模板入参或载入回归用例、编辑 `inputs` 与 `document`，点击「在顶部新页签打开聊天窗口」即在全局页签栏新增 `智能填报 · <orderId>` 页签；右栏支持页签切换或上下分栏查看 `postMessage` 实时报文流与 `report-confirmed` 确认回传报告 |
| `/settings` | `SettingsView.vue` | 系统提示词编辑与版本回退、大模型与网关运行期配置在线热更新及修订回滚 |

## 2. 核心交互组件（`frontend/src/components/`）

| 组件文件 | 职责说明 |
|----------|----------|
| `WorkspaceTabsBar.vue` + `ChatIframeTabPane.vue` | **右侧全局多页签导航与动态聊天保活面板**：基于 Element Plus `<el-tabs type="card">` + `SortableJS` 拖拽重排（锁死固定首页签 `核查模板`，重排前还原 DOM 顺序再由 Pinia `splice` 驱动避免 VNode 错位）+ `<el-dropdown>` 快捷关闭菜单（关闭当前/其他/右侧/全部可关页签），适配亮/暗双主题；`ChatIframeTabPane.vue` 以 `100% × 100%` 承载无边框 `/embed.html` `<iframe>`（`v-show` 保活，严格校验同源 `origin` 与 `event.source` 执行 `chat-ready` ↔ `chat-init` 握手及回传） |
| `JinjaBodyEditor.vue` + `CodeMirrorEditor.vue` + `WorkbenchTemplateStage.vue` | 基于 CodeMirror 6 定制的 Jinja2 / Markdown / YAML 代码编辑器，支持 `{{字段名}}` 芯片高亮、未定义变量提示与实时沙箱渲染预览（携带内存编辑态 `fields`）联动；装饰器仅在 `docChanged` / `viewportChanged` 或显式高亮注解触发时按可视范围 `visibleRanges` 重算，避免无关输入抖动 |
| `WorkbenchDebugPanel.vue` | 模板在线试运行入参表单与单据面板：对声明了 `pattern` 的入参自动执行 `.trim()` 与整串锚定 `^(?:...)$` 校验（对齐后端 `re.fullmatch`） |
| `ApiVisualEditor.vue` | 将复杂的 `apis/*.yaml`（连接器类型、JSON Schema 入参表、请求报文映射、`noData`/`success` 判定条件、多模式记录抽取列）转化为直观表单双向同步编辑 |
| `AgentTimeline.vue` | 消费 `/dryrun/stream` SSE 事件流，按模型推理轮次（`round`）实时渲染 `load_skill`、`call_api`、`query_result` 等工具调用耗时，并以醒目红色卡片标出 `report_rejected`（证据校验退回）与 `report_degraded`（降级）步骤 |
| `FieldEvidenceTable.vue` + `EvidenceSourceInspector.vue` | 字段核验结果表与三页签证据溯源检查器：点击任一字段（包括列表字段展开的子行），右侧自动跳转至对应网关结果集 `resultId` 高亮目标行/列，或跳转至单据原文高亮 `Lxxx` 行，或高亮工单入参 |
| `ReportPreviewContent.vue` | 最终报告渲染展示面板，支持点击已填入的字段值反向联动定位右侧证据源 |
| `GlobalDrawers.vue` + `GlobalModals.vue` | 承载字段精细配置抽屉（类型、`list` 子列编辑器、证据等级、`quoteWhole`、日期 `format`、缺失回退策略，重命名时自动携带 `originalName`）、发布前校验弹窗（有 `errors` 禁用确认按钮、展示 `warnings` 与基线 `drift` 漂移警告）以及 409 `DRAFT_CONFLICT` 多人编辑冲突处理弹窗（拉取服务端最新 `draft` 与本地编辑态做真实差异对比） |

## 3. 全局状态与并发安全协同（`stores/platform.ts` + `stores/workspaceTabs.ts`）

- **全局工作区多页签与保活拦截（`App.vue` + `stores/workspaceTabs.ts`）**：`App.vue` 在 `.main-content` 内以 `<KeepAlive :max="12">` 缓存路由模块页签，并与 `v-for` + `v-show` 渲染的动态聊天窗口页签并列保活；切换或关闭含未保存草稿的编辑页签时强制二次确认拦截（取消则保持原页签选中态），顶部页签切回 `skills`/`apis`/`runs` 自动恢复详情子视图，退出登录（`currentNav === 'login'`）自动调用 `tabsStore.resetAll()` 销毁全部动态聊天页签与内存密钥。
- **本地工作区缓冲 + 全链路乐观锁同步**：在 `TemplateWorkbenchView` 中修改正文、入参时更新 Pinia 内存状态并标记 `dirty`（离开页面触发 `unsaved-leave` 二次确认）；整包保存（`PUT /templates/{id}/draft`）与所有细粒度变更操作（单字段保存/删除、拖拽排序、批量改证据类型、增删绑定 Skill）均携带当前 `draft.revision` 并在成功后同步写回服务端返回的新 `revision`（同时在前端主动拦截将 `list` 字段批量改为 `input` 证据）。若遇 409 冲突自动弹出冲突对比引导刷新。
- **SSE 实时流解析（`api/platformApi.ts`）**：基于 `fetch` + `ReadableStream` 解析标准 `event: event` / `event: final` / `event: error` 帧（天然携带同源 Cookie 与自定义头，克服原生 `EventSource` 不支持 `POST` 请求体的限制）。

## 相关页面

- [嵌入式聊天选模板窗口组件剖析](chat-embed.md)
- [FastAPI 路由与鉴权组件剖析](api-and-auth.md)
- [AgentRunner 运行时组件剖析](agent-runner.md)
- [新增与维护报告模板实操指南](../guides/add-template.md)
- [本地开发、测试与部署指南](../guides/dev-test-and-deploy.md)
