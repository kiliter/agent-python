---
title: Vue 3 资源工作台前端剖析
type: component
tags: [component, frontend, vue3, workbench, codemirror, sse]
sources:
  - frontend/package.json
  - frontend/src/router/index.ts
  - frontend/src/stores/platform.ts
  - frontend/src/api/platformApi.ts
  - docs/frontend-api-handoff.md
updated: 2026-11-12
---

# Vue 3 资源工作台前端剖析

<!-- #Created By AiCoding(codex) -->

`frontend/` 是面向业务维护人员与平台管理员的可视化资源治理与智能体调试工作台，基于 **Vue 3.5 + TypeScript 5.8 + Vite 6 + Pinia 3 + Element Plus + CodeMirror 6** 构建，全部数据直接对接后端 `/api/v1` 真实接口（无本地写死 Mock 回退）。

## 1. 路由视图全景（`frontend/src/router/index.ts`）

应用采用 Hash 路由（`createWebHashHistory`），并在路由守卫中通过 `GET /api/v1/auth/me` 校验登录态，共包含 9 个核心页面视图（`frontend/src/views/`）：

| 路由路径 | 视图组件 | 核心功能 |
|----------|----------|----------|
| `/login` | `LoginView.vue` | 工作台账号密码登录，展示锁定倒计时与错误提示 |
| `/templates` | `TemplatesListView.vue` | 33+ 模板总览卡片/表格、状态筛选（已发布 / 有草稿 / 草稿 / 已下线）、新建/复制/下线/恢复 |
| `/workbench` | `TemplateWorkbenchView.vue` | **核心 IDE 式模板工作台**：左栏导航（字段 / 入参 / Skill / 用例 / 历史）、中栏双模式编辑器（代码 / 实时预览 / 分屏 / 版本 Diff）、右栏属性检查器与 SSE 试运行证据溯源 |
| `/skills` | `SkillsView.vue` | 纯文本 `SKILL.md` 在线编辑器、关联接口标签、被引用模板追踪与独立发布回退 |
| `/apis` | `ApisView.vue` | 网关接口契约管理：支持可视化表单（`ApiVisualEditor`）与原始 YAML 双模式编辑，内置在线参数拨测与报文预览 |
| `/runs` | `RunsView.vue` | 历史运行审计台账：多维检索、查看单次运行的渲染报告、完整推理轨迹与证据定位，支持一键“保存为回归用例” |
| `/regression` | `RegressionView.vue` | 模板回归测试用例管理与单条试跑验证 |
| `/releases` | `ReleasesView.vue` | 全局版本时间线（`r1`..`rN`）、版本间资源变更 Diff 对比及生产紧急版本切换（`emergency-switch`） |
| `/settings` | `SettingsView.vue` | 系统提示词编辑与版本回退、大模型与网关运行期配置在线热更新及修订回滚 |

## 2. 核心交互组件（`frontend/src/components/`）

| 组件文件 | 职责说明 |
|----------|----------|
| `JinjaBodyEditor.vue` + `CodeMirrorEditor.vue` | 基于 CodeMirror 6 定制的 Jinja2 / Markdown / YAML 代码编辑器，支持 `{{字段名}}` 高亮、未定义变量提示与实时沙箱渲染预览联动 |
| `ApiVisualEditor.vue` | 将复杂的 `apis/*.yaml`（连接器类型、JSON Schema 入参表、请求报文映射、`noData`/`success` 判定条件、多模式记录抽取列）转化为直观表单双向同步编辑 |
| `AgentTimeline.vue` | 消费 `/dryrun/stream` SSE 事件流，按模型推理轮次（`round`）实时渲染 `load_skill`、`call_api`、`query_result` 等工具调用耗时，并以醒目红色卡片标出 `report_rejected`（证据校验退回）与 `report_degraded`（降级）步骤 |
| `FieldEvidenceTable.vue` + `EvidenceSourceInspector.vue` | 字段核验结果表与三页签证据溯源检查器：点击任一字段（包括列表字段展开的子行），右侧自动跳转至对应网关结果集 `resultId` 高亮目标行/列，或跳转至单据原文高亮 `Lxxx` 行，或高亮工单入参 |
| `ReportPreviewContent.vue` | 最终报告渲染展示面板，支持点击已填入的字段值反向联动定位右侧证据源 |
| `GlobalDrawers.vue` + `GlobalModals.vue` | 承载字段精细配置抽屉（类型、`list` 子列编辑器、证据等级、`quoteWhole`、日期 `format`、缺失回退策略，重命名时自动携带 `originalName`）、发布前校验弹窗（有 `errors` 禁用确认按钮、展示 `warnings` 与基线 `drift` 漂移警告）以及 409 `DRAFT_CONFLICT` 多人编辑冲突处理弹窗 |

## 3. 全局状态与并发安全协同（`stores/platform.ts`）

- **本地工作区缓冲 + 整包乐观锁提交**：在 `TemplateWorkbenchView` 中修改正文、字段、入参或绑定 Skill 时，先更新 Pinia 内存状态并标记 `dirty`（离开页面触发 `unsaved-leave` 二次确认）；点击“保存草稿”时携带 `draft.revision` 调 `PUT /templates/{id}/draft`，若遇 409 冲突自动弹出冲突对比引导刷新。
- **SSE 实时流解析（`api/platformApi.ts`）**：基于 `fetch` + `ReadableStream` 解析标准 `event: event` / `event: final` / `event: error` 帧（天然携带同源 Cookie 与自定义头，克服原生 `EventSource` 不支持 `POST` 请求体的限制）。

## 相关页面

- [FastAPI 路由与鉴权组件剖析](api-and-auth.md)
- [AgentRunner 运行时组件剖析](agent-runner.md)
- [新增与维护报告模板实操指南](../guides/add-template.md)
- [本地开发、测试与部署指南](../guides/dev-test-and-deploy.md)
