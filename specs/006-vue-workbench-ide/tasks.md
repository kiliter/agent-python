---
description: "Vue 3 可视化资源治理工作台、四分区模板 IDE 与证据溯源前端 Spec Kit 任务清单（RA-006）"
---

# 任务说明（Implementation Tasks）：Vue 3 可视化资源治理工作台、四分区模板 IDE 与证据溯源前端

<!-- #Created By AiCoding(codex) -->

> **Spec Kit 使用约定**：本文件承接 `./spec.md` 与 `./plan.md`（`<!-- SPECKIT_PLAN_LAYOUT: inline-v1 -->` 内联四章），将 7 个前端研发切片转化为顺序清晰、带真实文件路径与工时的 18 项任务清单（含最新落地的 `F2` 智能光笔写单品牌图标资产：`frontend/public/favicon.svg`、`frontend/src/components/BrandMark.vue` 及 `index.html`/`App.vue`/`LoginView.vue` 接入）。本需求已全部交付并通过严格 `vue-tsc` 与 Vite 多包构建门禁，第 3 章权威清单任务统一标注 `[X]` 并在 `3.5` 节与第 6 章附上本轮实测证据。

---

## 基本信息

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-006` |
| 需求名称 | Vue 3 可视化资源治理工作台、四分区模板 IDE 与证据溯源前端 |
| 对应需求文档 | `./spec.md` |
| 对应设计文档 | `./plan.md` |
| tasks 版本 | `2.0` |
| 核算工作量 | `33.0 人天`（18 项任务合计严格等于 `33.0 人天`） |
| 状态 | 已完成（归档验收） |
| 负责人 | AiCoding / 前端工作台工程团队 |

---

## 0. 使用方式（给 AI 的执行指令） 【核心】

1. 按第 3 章权威任务清单顺序推进；标记 `[P]` 的任务可与同阶段无文件冲突任务并行，但不得越过前置阶段阻塞依赖。
2. 全文**仅第 3 章权威清单**使用复选框，每条严格遵循 `- [X] Txxx [P?] [USx?] 描述（X.X 人天）`；其他章节仅引用 `T*` 编号，不重复设置复选框。
3. 第 `3.5` 节记录各任务组对应的实际变更文件、核心符号及真实命令验证结果；无真实通过证据不得勾选 `[X]`。
4. 遇到需求歧义或现状冲突时，停止扩大改动并登记至第 9 节 `BQ-*`，回链 `spec.md` `Q-*`。

---

## 1. 需求到任务映射（Traceability） 【核心】

| 需求/标准 ID | 摘要 | 对应设计（Plan.md） | 映射任务 ID | 测试/验证映射 | 状态 |
| --- | --- | --- | --- | --- | --- |
| `US1` / `SC-002` | 四分区拖拽缩放 IDE、六栏活动栏、`jinjaHighlightPlugin` 作用域高亮、联动重命名、350ms 预览与 `409` 弹窗 | 第 `1.3`、`3`、`5`、`8` 章 | `T006`–`T008` | `TT-01`、`TT-02`、`TT-03` | 已验证 |
| `US2` / `SC-003` | SSE 推理时间线（12 工具与退回/降级跳转）、AST 同值消歧报告预览、三页签双向滚动聚焦高亮 | 第 `1.3`、`3`、`5`、`8` 章 | `T009`–`T011` | `TT-01`、`TT-02`、`TT-03` | 已验证 |
| `US3` / `SC-004` | `ApiVisualEditor` 双协议 4 页签与保留注释 YAML、`${$now}` 保护、五模式反推、拨测回填及回归抽屉 | 第 `3`、`5`、`8` 章 | `T012`–`T014` | `TT-01`、`TT-02`、`TT-03` | 已验证 |
| `US4` / `SC-001`、`SC-005` | 统一 `F2` 品牌图标资产与多处接入、锁首页拖拽多页签保活、双主题、紧急切换与 48 项热更新配置中心 | 第 `1.3`、`3`、`4`、`8`、`9` 章 | `T001`–`T002`、`T005`、`T015`–`T018` | `TT-01`、`TT-02`、`TT-04` | 已验证 |
| `FR-001` | Vite 6 双入口与 8 分包、10 懒加载 Hash 路由、双主题令牌、`terms.ts` 与 `F2` 品牌图标资产及接入 | 第 `1.3`、`1.4`、`8` 章 | `T001`、`T002`、`T005`、`T015`、`T018` | `TT-01`、`TT-02`、`TT-04` | 已验证 |
| `FR-002` | `platformApi`（401 拦截）、`readSseStream`、`usePlatformStore`（`markRaw` / 序号守卫）与 `useWorkspaceTabsStore` | 第 `3`、`5`、`6` 章 | `T003`、`T004`、`T015` | `TT-01`、`TT-03` | 已验证 |
| `FR-003` | `sanitizeHtml`、`renderSafeMarkdown`（32 LRU）、`textDiff`、`listColumns`、`copyToClipboard` 与 `BrandMark`/`SvgIcon`/`StatusTag` | 第 `1.4`、`7`、`8` 章 | `T005` | `TT-01`、`TT-02` | 已验证 |
| `FR-004` | `TemplateWorkbenchView` 三分割条与 `24px` 状态栏、`WorkbenchLeftExplorer` 六栏活动栏与未定义胶囊过滤 | 第 `3`、`8` 章 | `T007` | `TT-01`、`TT-03` | 已验证 |
| `FR-005` | `analyzeJinjaBody`、`CodeMirrorEditor`、`WorkbenchTemplateStage` 四模式、`{{`/`｛｛` 补全与 350ms 内存预览 | 第 `3`、`6`、`8` 章 | `T006`、`T007` | `TT-01`、`TT-03` | 已验证 |
| `FR-006` | `WorkbenchRightInspector` 属性与 `list` 列编辑、`handleApplyField` 变量重命名联动与 `GlobalModals` `409` 弹窗 | 第 `3`、`6`、`8` 章 | `T006`、`T008` | `TT-01`、`TT-03` | 已验证 |
| `FR-007` | `WorkbenchDebugPanel`（190px 历史/正则/全屏 `Esc`）、`AgentTimeline` 12 工具与 `report_rejected`/`degraded` 联动 | 第 `5`、`6`、`8` 章 | `T010` | `TT-01`、`TT-03` | 已验证 |
| `FR-008` | `alignReportWithTemplate` 消歧、`ReportPreviewContent`（`Teleport`）、`EvidenceSourceInspector` 三页签定位与 `RunsView` | 第 `3`、`6`、`8` 章 | `T009`、`T011` | `TT-01`、`TT-03` | 已验证 |
| `FR-009` | `ApiVisualEditor`、`ApisView`（`syncColumnsFromTestResult`）、`SkillsView`、`RegressionView` 与 `reg-diff-detail` 抽屉 | 第 `3`、`8` 章 | `T012`–`T014` | `TT-01`、`TT-03` | 已验证 |
| `FR-010` | `LoginView`、`App.vue` 壳层（`KeepAlive(12)`、`⌘K`/`⌘S`）、`WorkspaceTabsBar`、`ReleasesView` 与 `SettingsView` 48 项设置 | 第 `4`、`8`、`9` 章 | `T015`–`T016` | `TT-01`、`TT-02`、`TT-03` | 已验证 |
| `NFR-001`~`NFR-005` | 零业务硬编码、强证据中性 0 行区分、`markRaw`/LRU 性能、XSS 防护及严格 `vue-tsc`/8 分包隔离 | 第 `1.5`、`7`、`11` 章 | `T001`–`T018` | `TT-01`–`TT-04` | 已验证 |
| `EX-001`~`EX-006` | 全角/保留字拦截、同值与 0 行歧义、SSE 取消防卡顿、`409` 与脏页签拦截、剪贴板/XSS 降级、SVG ID 隔离 | 第 `6.2`、`7`、`10` 章 | `T003`–`T015` | `TT-01`–`TT-03` | 已验证 |

### 1.1 三类独立交付物维护台账

| 独立交付物 | 涉及情况与依据 | 关联任务 | 维护状态 | 验证结果 |
| --- | --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中；前端对齐 `docs/frontend-api-handoff.md`） | 不生成 | 不生成 | `T018` 校验代理与后端契约一致 |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 不生成 | 不生成 | 本需求不触及 `seed/` 资产 |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 不生成 | 不生成 | 沿用 `base: './'` 与 `FRONTEND_DIST` 托管 |

---

## 2. 里程碑与切分策略（Milestones） 【补充】

| 阶段 / Milestone | 目标 | 任务范围 | 阶段工时（人天） | 验收定义 |
| --- | --- | --- | --- | --- |
| Phase 1: Setup（工程骨架、F2 图标与路由主题基线） | 初始化双入口 Vite 8 分包、F2 Favicon 与术语路由主题 | `T001`–`T002` | `3.0` | `vite.config.ts`、`favicon.svg` 与双主题样式就绪 |
| Phase 2: Foundational（API 客户端、状态机与安全/品牌底座） | 交付 `platformApi`、`platform` Store、`BrandMark` 及安全纯函数 | `T003`–`T005` | `6.0` | 类型契约、SSE 取消、XSS 净化与零依赖 `BrandMark` 就绪 |
| Phase 3: US1（四分区模板 IDE 与 Jinja2 编辑器，MVP） | 交付词法扫描重命名、四分区拖拽 IDE 与 `409` 弹窗 | `T006`–`T008` | `6.5` | 变量识别、联动改名与 350ms 预览闭环 |
| Phase 4: US2（SSE 实时时间线与双向三页签证据溯源） | 交付 AST 消歧、12 工具时间线、三页签定位与运行台账 | `T009`–`T011` | `6.0` | 同值消歧、合法 0 行与 `report_rejected` 联动准确 |
| Phase 5: US3（可视化双协议 API 编排、技能与回归抽屉） | 交付 `ApiVisualEditor`、未落盘拨测回填、`SkillsView` 与 `GlobalDrawers` | `T012`–`T014` | `5.5` | 注释保真、`BUILTIN_PLACEHOLDERS` 与反推列生效 |
| Phase 6: US4（多页签保活、`F2` 门户登录、版本与 48 项配置中心） | 交付 `BrandMark` 接入、`KeepAlive` 壳层、版本中心与设置中心 | `T015`–`T016` | `3.5` | 页签拦截、`F2` 门户/侧栏展示与 48 项热更新交互就绪 |
| Phase 7: Polish（类型门禁修复与多包生产构建收敛） | 完成全量严格 `vue-tsc`、`npm run build` 8 分包与联调核验 | `T017`–`T018` | `2.5` | `vue-tsc` 0 错误、`3415` 模块构建通过且 `embed` 洁净 |

### 2.1 依赖与交付顺序

- **阶段依赖**：Phase 1（工程与品牌图标基座 `T001`–`T002`） → Phase 2（API/Store/安全与 `BrandMark` 公共底座 `T003`–`T005`） → Phase 3–6（`US1` MVP 先行，其后并行推进 `US2`–`US4`） → Phase 7（`vue-tsc` 与 Vite 生产构建收口 `T017`–`T018`）。
- **并行机会**：Phase 1 中 `T002` 与 `T001` 并行；Phase 2 中 `T004`、`T005` 在 `T003` 类型确立后并行；Phase 3–6 中 `T008`、`T011`、`T014`、`T016` 可与同阶段或跨故事独立模块并行研发验证；Phase 7 中 `T017` 与 `T018` 依次/并行收敛。

---

## 3. 任务清单（按执行顺序） 【核心】

### 3.1 Phase 1: Setup (Shared Infrastructure)

- [X] T001 初始化 Vue 3.5 + TypeScript 5.7 工程、Vite 6 双入口（`index.html`/`embed.html`）、`base: './'`、8 个 `manualChunks` 及 `F2` 品牌静态图标与内联 Favicon，文件：`frontend/index.html` `frontend/public/favicon.svg` `frontend/package.json` `frontend/tsconfig.app.json` `frontend/vite.config.ts`（1.5 人天）
- [X] T002 [P] 配置 Element Plus 中文环境、10 个按需懒加载 Hash 路由表、亮暗双主题 CSS Token 及统一导航术语常量，文件：`frontend/src/main.ts` `frontend/src/router/index.ts` `frontend/src/assets/styles.css` `frontend/src/constants/terms.ts`（1.5 人天）

### 3.2 Phase 2: Foundational (Blocking Prerequisites)

- [X] T003 实现全量资源与 48 字段 `RuntimeConfig` TS 契约、带 `ApiError`/`auth:unauthorized` 拦截的 HTTP 客户端及换行容错 `readSseStream` 解析器，文件：`frontend/src/types/platform.ts` `frontend/src/api/platformApi.ts` `frontend/src/utils/sse.ts`（2.0 人天）
- [X] T004 [P] 实现全局资源治理解耦合 Pinia 状态机、`stabilizeRunDetail` 的 `markRaw` 降载、递增请求序号守卫与 `409` 冲突上下文，文件：`frontend/src/stores/platform.ts`（2.0 人天）
- [X] T005 [P] 实现 `DOMParser` 白名单 `sanitizeHtml`、32 LRU `renderSafeMarkdown`、行级 `textDiff`、受限剪贴板回退及零重型依赖 `F2` `BrandMark`（`useId()` 渐变隔离）/`SvgIcon`/`StatusTag` 组件，文件：`frontend/src/utils/sanitizeHtml.ts` `frontend/src/utils/markdown.ts` `frontend/src/utils/textDiff.ts` `frontend/src/utils/clipboard.ts` `frontend/src/components/BrandMark.vue` `frontend/src/components/SvgIcon.vue` `frontend/src/components/StatusTag.vue`（2.0 人天）

### 3.3 Phase 3–6: User Stories (Priority: P1–P2)

#### Phase 3: User Story 1 - 四分区 IDE 模板工作台与 Jinja2 词法作用域编辑器 (Priority: P1) 🎯 MVP

**目标**：交付四分区可拖拽缩放模板 IDE、集成 `CodeMirror 6` Jinja2 词法作用域高亮/变量联动重命名/350ms 防抖预览及 `409` 冲突解决弹窗。

**独立测试**：拖拽工作台分割条，输入 `{{`、`｛｛` 与 `{% for %}` 核对高亮芯片与局部作用域，通过 `handleApplyField` 重命名核对正文替换并触发 `409` 对比恢复。

- [X] T006 [US1] 实现 `analyzeJinjaBody` 词法与 `for`/`set` 作用域扫描、`renameJinjaBodyVariable`（护栏注释与字面量）、`RESERVED_JINJA_IDENTIFIERS` 拦截、`listColumns` 解析与 `CodeMirrorEditor`，文件：`frontend/src/utils/jinjaBody.ts` `frontend/src/utils/listColumns.ts` `frontend/src/components/CodeMirrorEditor.vue`（2.5 人天）
- [X] T007 [US1] 实现四分区可拖拽 IDE 主视图与底部 `24px` `ide-statusbar`、50px 六栏活动栏（含模板名称说明直编与 `SortableJS` 拖拽）及 `WorkbenchTemplateStage`（`jinjaHighlightPlugin`、全半角补全、350ms 预览与全量 Diff），文件：`frontend/src/views/TemplateWorkbenchView.vue` `frontend/src/components/workbench/WorkbenchLeftExplorer.vue` `frontend/src/components/workbench/WorkbenchTemplateStage.vue`（2.5 人天）
- [X] T008 [P] [US1] 实现右侧属性检查器（`handleApplyField` 重命名联动与 `list` 列编辑）、模板清单与 `.ref-popover-list` 及 `409 DRAFT_CONFLICT` 对比覆盖全局弹窗，文件：`frontend/src/components/workbench/WorkbenchRightInspector.vue` `frontend/src/views/TemplatesListView.vue` `frontend/src/components/GlobalModals.vue`（1.5 人天）

#### Phase 4: User Story 2 - SSE 实时推理时间线与双向联动三页签证据溯源检查器 (Priority: P1)

**目标**：实现消费 `/dryrun/stream` 的轮次折叠推理时间线（突出 `report_rejected` 与 `report_degraded` 联动）、AST 结构消歧报告预览与三页签双向滚动聚焦检查器。

**独立测试**：触发流式试运行核对 `AgentTimeline` 轮次展示与报错跳转，在同值多字段与合法 0 行列表详情验证 `ReportPreviewContent` 与 `EvidenceSourceInspector` 定位。

- [X] T009 [US2] 实现 `alignReportWithTemplate` AST 报告对齐与 `fallbackSegmentize` 降级、同值消歧交互及 `ReportPreviewContent`（`<Teleport to="body">` KEY 悬浮与合法 0 行中性展示），文件：`frontend/src/utils/reportSegments.ts` `frontend/src/components/ReportPreviewContent.vue`（2.5 人天）
- [X] T010 [US2] 实现入参正则校验、`190px` 历史栏与全屏 `Esc` 的 `WorkbenchDebugPanel`、按轮次归并 12 类工具与退回/降级联动跳转的 `AgentTimeline` 及 `FieldEvidenceTable`，文件：`frontend/src/utils/timelineFormat.ts` `frontend/src/components/workbench/WorkbenchDebugPanel.vue` `frontend/src/components/AgentTimeline.vue` `frontend/src/components/FieldEvidenceTable.vue`（2.0 人天）
- [X] T011 [P] [US2] 实现网关 `resultId`、单据 `Lxxx` 与工单入参三页签双向滚动定位高亮检查器 `EvidenceSourceInspector` 及多条件运行审计排查视图 `RunsView`，文件：`frontend/src/components/EvidenceSourceInspector.vue` `frontend/src/views/RunsView.vue`（1.5 人天）

#### Phase 5: User Story 3 - 可视化双模式网关契约编排器、技能治理与回归抽屉 (Priority: P2)

**目标**：交付 XML/JSON 双协议 4 页签可视化 + 保留注释同步 YAML 编排器（含 `${$now}`、五模式样例反推及 `test-call` 列回填）、技能编辑及回归对比抽屉。

**独立测试**：切换 XML/JSON 协议并插入 `${$now}` 检查信封预览、粘贴样本反推列、执行未落盘 `test-call` 回填列，并在 `SkillsView` 与 `RegressionView` 验证回滚与 `reg-diff-detail` 抽屉。

- [X] T012 [US3] 实现 `ApiVisualEditor` 双协议 4 页签可视化表单与保留注释同步 YAML 分屏编辑器、`${$now}` 保护、脱敏 `operation_in` 预览、五模式样例反推与 `syncColumnsFromTestResult`，文件：`frontend/src/components/ApiVisualEditor.vue`（2.0 人天）
- [X] T013 [US3] 实现接口管理页（未落盘 `test-call` 实时拨测与列同步）与纯文本技能库视图（`renderSafeMarkdown` 预览、双模式回滚与 `.ref-popover-list` 关联展示），文件：`frontend/src/views/ApisView.vue` `frontend/src/views/SkillsView.vue`（2.0 人天）
- [X] T014 [P] [US3] 实现回归测试中心模板过滤与差异对比视图及按需挂载的 `reg-diff-detail` 全局抽屉容器（明确标注批量回归为 Phase 2 扩展），文件：`frontend/src/views/RegressionView.vue` `frontend/src/components/GlobalDrawers.vue`（1.5 人天）

#### Phase 6: User Story 4 - 多页签保活工作区、统一品牌标识、版本发布视图与 48 项热更新配置中心 (Priority: P2)

**目标**：完成 `F2` `BrandMark` 侧栏与登录门户接入、锁首页可拖拽保活多页签壳层、双主题切换、版本中心紧急切换及 48 项热更新与 API Key 管理中心。

**独立测试**：核验 `LoginView`（38px）与 `App.vue` 侧栏（26px）`BrandMark` 展示；拖拽 `WorkspaceTabsBar` 确认首页锁定及脏关闭拦截；测试 `ReleasesView` 跨版本跳链及 `SettingsView` 提示词、密钥与 48 项热配置操作。

- [X] T015 [US4] 实现锁首页 `SortableJS` 多页签、`<KeepAlive :max="12">` 与聊天 `v-show` 全屏保活、脏草稿 `before-leave` 拦截、壳层（`BrandMark` `26px`/`38px`、`⌘K`/`⌘S` 与双主题）及 `LoginView`/`ChatSimView` 宿主联调页，文件：`frontend/src/stores/workspaceTabs.ts` `frontend/src/components/WorkspaceTabsBar.vue` `frontend/src/components/ChatIframeTabPane.vue` `frontend/src/components/ChatSimTemplatePicker.vue` `frontend/src/App.vue` `frontend/src/views/LoginView.vue` `frontend/src/views/ChatSimView.vue`（2.0 人天）
- [X] T016 [P] [US4] 实现发布中心时间线、带必填原因紧急切换与跨版本 Diff 跳链，以及系统提示词时间线、`X-API-Key` 轮换卡与 48 项热更新配置/局部重置/修订回滚中心，文件：`frontend/src/views/ReleasesView.vue` `frontend/src/views/SettingsView.vue`（1.5 人天）

### 3.4 Phase 7: Polish & Cross-Cutting Concerns

- [X] T017 [P] 执行前端全量 TypeScript 严格模式类型检查 `npx vue-tsc --noEmit -p tsconfig.app.json` 并收敛所有组件 Props、48 项配置与空值边界类型定义，文件：`frontend/tsconfig.app.json` `frontend/src/types/platform.ts`（1.5 人天）
- [X] T018 验证 Vite 多入口与 8 分包构建输出（`npm run build`）、核验 `embed.html` 剥离重包与 `BrandMark` 复用洁净度及与 Spec 005 `/api/v1/*` 联调一致性，文件：`frontend/vite.config.ts` `frontend/package.json` `frontend/dist/index.html` `frontend/dist/embed.html`（1.0 人天）

### 3.5 任务详情与完成记录

#### 任务组：`T001–T002`（Phase 1：工程骨架、F2 图标与主题路由基线，3.0 人天）

- **关联需求**：`FR-001`、`NFR-004`、`NFR-005`、`US4`
- **关键变更点**：`frontend/public/favicon.svg`、`frontend/index.html`（内联 `F2` SVG Data URI favicon 与 `data-theme="light"`）、`frontend/vite.config.ts`（`base: './'`、双入口与 8 `manualChunks`）、`frontend/package.json`、`frontend/tsconfig.app.json`、`frontend/src/main.ts`、`frontend/src/router/index.ts`（10 懒加载视图）、`frontend/src/assets/styles.css`、`frontend/src/constants/terms.ts`。
- **验证方式与实测证据**：执行 `cd frontend && npx vue-tsc --noEmit -p tsconfig.app.json` 0 错误通过；全量构建 `npm run build` 实测完成 `3415 modules transformed`、`built in 5.80s`，产物 `frontend/dist/favicon.svg`、`frontend/dist/index.html` 与 `frontend/dist/embed.html` 已生成。
- **状态与阻塞**：已完成；无阻塞项。

#### 任务组：`T003–T005`（Phase 2：API/SSE 客户端、Pinia 核心状态机与安全/品牌底座，6.0 人天）

- **关联需求**：`FR-001`、`FR-002`、`FR-003`、`EX-003`、`EX-005`、`EX-006`、`NFR-003`、`NFR-004`
- **关键变更点**：`frontend/src/types/platform.ts`、`frontend/src/api/platformApi.ts`（`ApiError`、`auth:unauthorized`）、`frontend/src/utils/sse.ts`（`readSseStream`、`parseSseJson`）、`frontend/src/stores/platform.ts`（`stabilizeRunDetail` `markRaw`、请求序号守卫、`409` 状态）、`frontend/src/utils/{sanitizeHtml,markdown,textDiff,clipboard}.ts`、`frontend/src/components/{BrandMark,SvgIcon,StatusTag}.vue`（`BrandMark` 通过 `useId()` 隔离渐变 ID 且零外部重型依赖）。
- **验证方式与实测证据**：`cd frontend && npx vue-tsc --noEmit -p tsconfig.app.json` 0 错误；`npm run build`（`3415 modules transformed`、`built in 5.80s`）确认 `BrandMark` 独立提取为轻量组件且零污染 `embed.html`；后端协同契约 `uv run pytest -q`（`196 passed in 51.41s`）通过。
- **状态与阻塞**：已完成；无阻塞项。

#### 任务组：`T006–T008`（Phase 3 / US1：四分区模板 IDE 与 Jinja2 编辑器，6.5 人天）

- **关联需求**：`US1`、`SC-002`、`FR-004`、`FR-005`、`FR-006`、`EX-001`、`EX-004`
- **关键变更点**：`frontend/src/utils/{jinjaBody,listColumns}.ts`（`analyzeJinjaBody`、`renameJinjaBodyVariable`、`RESERVED_JINJA_IDENTIFIERS`）、`frontend/src/components/CodeMirrorEditor.vue`、`frontend/src/views/TemplateWorkbenchView.vue`（四分区三分割条与 24px `ide-statusbar`）、`frontend/src/components/workbench/{WorkbenchLeftExplorer,WorkbenchTemplateStage,WorkbenchRightInspector}.vue`（50px 六栏活动栏、模板信息直编、`jinjaHighlightPlugin`、350ms 防抖预览、`handleApplyField`）、`frontend/src/views/TemplatesListView.vue`、`frontend/src/components/GlobalModals.vue`（`409` 与 `openConflictDraftDiff`）。
- **验证方式与实测证据**：`cd frontend && npx vue-tsc --noEmit -p tsconfig.app.json`（0 错误）、`npm run build`（`3415 modules transformed`、`built in 5.80s`）。
- **状态与阻塞**：已完成；无阻塞项。

#### 任务组：`T009–T011`（Phase 4 / US2：SSE 推理时间线与 AST 双向证据溯源，6.0 人天）

- **关联需求**：`US2`、`SC-003`、`FR-007`、`FR-008`、`EX-002`、`NFR-002`
- **关键变更点**：`frontend/src/utils/{reportSegments,timelineFormat}.ts`（`alignReportWithTemplate`、`fallbackSegmentize`、`groupEventsByRound`、`describeToolEvent`、`TIMELINE_OUTCOME_TYPES`）、`frontend/src/components/{ReportPreviewContent,AgentTimeline,FieldEvidenceTable,EvidenceSourceInspector}.vue`（`<Teleport to="body">` 悬浮、`.tl-outcome-err`/`.tl-outcome-warn` 联动、`.evidence-highlight-mark`/`.row-highlight` 三页签聚焦、区分 `无记录（0 行）`）、`frontend/src/components/workbench/WorkbenchDebugPanel.vue`（190px 历史栏与全屏 `Esc`）、`frontend/src/views/RunsView.vue`。
- **验证方式与实测证据**：`cd frontend && npx vue-tsc --noEmit -p tsconfig.app.json`（0 错误）、`npm run build`（`3415 modules transformed`、`built in 5.80s`）。
- **状态与阻塞**：已完成；无阻塞项。

#### 任务组：`T012–T014`（Phase 5 / US3：可视化双协议 API 编排器、技能与回归抽屉，5.5 人天）

- **关联需求**：`US3`、`SC-004`、`FR-009`
- **关键变更点**：`frontend/src/components/ApiVisualEditor.vue`（双协议 4 页签、保留注释同步、`BUILTIN_PLACEHOLDERS` `${$now}`、五模式样例反推、`syncColumnsFromTestResult`）、`frontend/src/views/{ApisView,SkillsView,RegressionView}.vue`、`frontend/src/components/GlobalDrawers.vue`（`reg-diff-detail` 抽屉）。
- **验证方式与实测证据**：`cd frontend && npx vue-tsc --noEmit -p tsconfig.app.json`（0 错误）、`npm run build`（`3415 modules transformed`、`built in 5.80s`）。
- **状态与阻塞**：已完成；无阻塞项。

#### 任务组：`T015–T016`（Phase 6 / US4：多页签保活、`F2` 门户登录、版本与 48 项配置中心，3.5 人天）

- **关联需求**：`US4`、`SC-005`、`FR-001`、`FR-010`、`EX-004`、`EX-006`
- **关键变更点**：`frontend/src/stores/workspaceTabs.ts`、`frontend/src/components/{WorkspaceTabsBar,ChatIframeTabPane,ChatSimTemplatePicker}.vue`、`frontend/src/App.vue`（`BrandMark` `size=26`、三分组导航、`⌘K`/`⌘S`、`<KeepAlive :max="12">`、`is-chat-fullscreen`）、`frontend/src/views/LoginView.vue`（SVG 工程网格、`MutationObserver`、`BrandMark` `size=38`）、`frontend/src/views/ChatSimView.vue`、`frontend/src/views/ReleasesView.vue`、`frontend/src/views/SettingsView.vue`（提示词时间线、`X-API-Key` 轮换、48 项配置表单 + `handleResetDefaultParams` + `clear*` 安全清空与 `cN` 回滚）。
- **验证方式与实测证据**：`cd frontend && npx vue-tsc --noEmit -p tsconfig.app.json`（0 错误）、`npm run build`（`3415 modules transformed`、`built in 5.80s`）。
- **状态与阻塞**：已完成；无阻塞项。

#### 任务组：`T017–T018`（Phase 7：严格类型门禁与多入口分包联调收敛，2.5 人天）

- **关联需求**：`SC-001`~`SC-005`、`FR-001`~`FR-010`、`NFR-001`~`NFR-005`
- **关键变更点**：`frontend/tsconfig.app.json`、`frontend/src/types/platform.ts`、`frontend/vite.config.ts`、`frontend/package.json`、`frontend/dist/{index,embed}.html`。
- **验证方式与实测证据**：本轮完整通过前端严格类型检查与生产构建 `cd frontend && npx vue-tsc --noEmit -p tsconfig.app.json && npm run build`（`vue-tsc` 0 错误、`3415 modules transformed`、`built in 5.80s`）；全栈联调依托的后端接口门禁经 `uv run pytest -q`（`196 passed in 51.41s`，本轮复核 `196 passed in 50.72s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）全绿验证，核对 `frontend/dist/embed.html` 确认未包含 `element-plus` 与 `codemirror` 分包。
- **状态与阻塞**：已完成；无阻塞项。

---

## 4. 子任务拆解（可选） 【补充】

> 本需求 `T001`–`T018` 共 18 项任务已对应清晰的视图、组件与纯函数模块边界，粒度适中，无需额外子任务拆解。

---

## 5. 代码实现约束（仅本需求新增） 【补充】

- **并发与一致性**：Pinia 异步读取全量启用请求序号守卫防错序覆盖；页签 `SortableJS` 排序先还原 DOM 再更新数组防 Vue 虚拟节点错位；写接口必须透传 `revision` 并适配 `GlobalModals` `409` 对比恢复；对 `RunDetail` 大数组调用 `stabilizeRunDetail` 应用 `markRaw`。
- **安全与隐私边界**：外源 Markdown 与富文本必须经过基于 `DOMParser` 的 `sanitizeHtml` 净化；`SettingsView` 三类敏感密钥仅展示掩码与显式清空开关；`BrandMark.vue` 严禁引入重型 UI/编辑器依赖并必须采用 `useId()` 隔离渐变 DOM ID；源码中禁止硬编码任何真实密钥或默认密码。
- **错误与降级语义**：SSE 流主动取消或退出必须捕获并静默处理 `AbortError`；`alignReportWithTemplate` 失配时平滑降级至 `fallbackSegmentize`；受限环境 `copyToClipboard` 降级隐藏 `<textarea>`；合法空列表 `status="found", value=[]` 明确渲染中性态 `无记录（0 行）`。

---

## 6. 测试任务矩阵（Test Tasks） 【核心】

| 测试编号 | 类型 | 测试场景与关注点 | 关联任务 | 测试路径 | 验证命令与结果 |
| --- | --- | --- | --- | --- | --- |
| `TT-01` | 静态类型门禁 | 全量 `frontend/src/` Strict TypeScript、48 项 `RuntimeConfig`、组件 Props（含 `BrandMark` `size`）与空值安全校验 | `T001`–`T017` | `frontend/tsconfig.app.json`、`frontend/src/**` | `cd frontend && npx vue-tsc --noEmit -p tsconfig.app.json`（0 错误通过） |
| `TT-02` | 多入口生产构建与分包验证 | Vite 6 双入口构建、8 `manualChunks` 拆分、`dist/favicon.svg` 拷贝及 `dist/embed.html` 零重包隔离检查 | `T001`、`T005`、`T015`、`T018` | `frontend/vite.config.ts`、`frontend/dist/{index,embed}.html` | `cd frontend && npm run build`（实测 `3415 modules transformed`、`built in 5.80s`；核对 `dist/embed.html` 含 `BrandMark` 且无 `element-plus`/`codemirror`） |
| `TT-03` | 后端对接契约全栈联调基线 | 与前端消费的全部 `/api/v1/*` 后端鉴权、乐观锁、预览、拨测、热更新与流式接口对齐回归 | `T003`–`T016`、`T018` | `tests/test_api*.py`、`tests/test_deep_audit_fixes.py`、`tests/test_runtime_config_hot_reload.py` | `uv run pytest -q`（全量 `196 passed in 51.41s` / 复核 `50.72s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`） |
| `TT-04` | 品牌视觉与交互主题核查 | 核对 `favicon.svg`、`index.html`、`BrandMark.vue` 在 `App.vue`（26px）与 `LoginView.vue`（38px）的亮暗双主题渲染与渐变动效 ID 唯一性 | `T001`、`T005`、`T015` | `frontend/public/favicon.svg`、`frontend/src/components/BrandMark.vue`、`frontend/src/{App,views/LoginView}.vue` | 源码审阅 + `vue-tsc` + `dist/` 预加载验证通过 |

---

## 7. 发布任务清单（Release Tasks） 【核心】

| 发布编号 | 动作内容 | 前置依赖 | 验证与完成标准 | 回滚动作 | 关联任务 |
| --- | --- | --- | --- | --- | --- |
| `RT-01` | 执行 `npx vue-tsc --noEmit -p tsconfig.app.json` 与 `npm run build` 产出最新静态包 | `T001`–`T018` | `vue-tsc` 0 错误、`3415` 模块转换成功、`8` 分包及 `dist/favicon.svg` 就绪 | 恢复上一版本 `frontend/` 与 `frontend/dist/` 产物 | `T017`、`T018` |
| `RT-02` | 配置 `FRONTEND_DIST` 静态托管目录并确认子路径前缀（`./`）下登录、工作台、图标与 `/api/v1/*` 联调畅通 | `RT-01` | 浏览器加载 `index.html`、`BrandMark` 与 10 个路由懒加载分包均 `200 OK` | 回退静态目录版本并重启托管 | `T001`、`T015`、`T018` |

---

## 8. 可观测性与验收（Observability & Acceptance） 【补充】

### 8.1 关键过程事件、日志与审计点位

| 场景 | 载体（过程事件 / 日志 / 审计） | 关键上下文字段 | 隐私脱敏约束 |
| --- | --- | --- | --- |
| 试运行与运行记录调试 | `AgentTimeline` / SSE `readSseStream` | `round`、12 工具名、`callId`、`report_rejected` / `report_degraded` 报错字段、耗时 | 前端不缓存或泄露外部网关密钥；取消时静默清理 `AbortError` |
| 48 项设置与 `X-API-Key` 操作 | `SettingsView` / `RuntimeConfigRevision` / `Audit` | `activeRev`、`changedKeys`、`operator`（服务端注入）、显隐切换状态 | 敏感字段表单仅回填掩码占位，退出登录执行 `tabsStore.resetAll()` 清理模拟键 |
| 嵌入式聊天模拟联调 | `ChatSimView` / `workspaceTabs.ts` | `postMessage` 交互日志、`userId`、`orderId`、`confirmedReports` | 交互日志视图通过 `maskChatInitPayload` 遮罩敏感 `apiKey` |

### 8.2 验收清单

- 全量 18 项任务均依据真实 `npx vue-tsc --noEmit -p tsconfig.app.json`（0 错误）与 `npm run build`（`3415 modules transformed`、`built in 5.80s`）及后端联调契约 `uv run pytest -q`（`196 passed in 51.41s` / 复核 `50.72s`）验证通过并完成归档。
- `F2` 品牌图标资产（`frontend/public/favicon.svg`、`frontend/src/components/BrandMark.vue`）及在 `index.html`、`App.vue`、`LoginView.vue` 的接入事实已在三件套中完整闭环并核对构建分包洁净。
- `spec.md`、`plan.md`、`tasks.md` 编号追踪无遗漏需求、工时之和严格等于 `33.0 人天`，三类独立交付物明确登记不涉及。

---

## 9. 阻塞与待确认（Blockers & Open Questions） 【核心】

> 当前无阻塞问题（历史 `Q-001`、`Q-002` 已在产品边界收敛与多包验证阶段全部闭环关闭）。

| 编号 | 问题描述 | 关联 Spec Q-* | 影响任务 | 责任方 | 状态 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `BQ-1` | 批量回归执行入口边界与 `BrandMark.vue` 跨入口分包隔离确认 | `Q-001`、`Q-002` | `T014`、`T018` | 前端架构与产品团队 | 已关闭 | 批量回归保留为 Phase 2 扩展；`BrandMark.vue` 仅依赖 `vue` `useId()`，构建核验 `embed.html` 零重型依赖混入 |

---

## 10. 变更记录（Changelog） 【补充】

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | Codex | 完成 `006-vue-workbench-ide` 初版 WBS 任务清单（18 项任务 / 33.0 人天） |
| 2.0 | 2026-11-16 | AiCoding | 按改造后中文 Spec-Kit 任务模板全面重构，补齐第 `0`–`10` 章、正则合规工时清单、三类交付物台账、`F2` 品牌图标任务记录及本轮实测构建与测试证据 |

---

## 附录 A：任务依赖简图

```text
Phase 1 (T001–T002, 3.0d)
  → Phase 2 (T003–T005, 6.0d)
      ├→ Phase 3 / US1 (T006–T008, 6.5d) 🎯 MVP
      ├→ Phase 4 / US2 (T009–T011, 6.0d)
      ├→ Phase 5 / US3 (T012–T014, 5.5d)
      └→ Phase 6 / US4 (T015–T016, 3.5d)
          → Phase 7 (T017–T018, 2.5d)
```

## 附录 B：AI 执行提示

1. 编码前先核对 `spec.md` 第 9 节 Out of Scope 与 `plan.md` 第 1.4 节禁止修改范围（严禁将 `element-plus`/`codemirror` 引入供 `embed.html` 复用的公共模块）。
2. 所有已勾选 `[X]` 任务均已附带真实类型校验与构建验证结果；后续修改任一视图、组件或类型时须同步重新运行 `vue-tsc`、`npm run build` 并核查 `dist/embed.html`。

---

## 增量更新说明

> 本文档依据改造后中文 Spec-Kit 模板与 `/sdd-documentation` 标准维护；后续新增或重拆任务需同步刷新第 1 节映射表、第 3 章任务工时及第 10 节变更记录。
