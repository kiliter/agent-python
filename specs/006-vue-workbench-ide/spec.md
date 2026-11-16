# 需求文档（Spec）：Vue 3 可视化资源治理工作台、四分区模板 IDE 与证据溯源前端

<!-- #Created By AiCoding(codex) -->

> **Spec Kit 使用约定**：产物文件名固定为 `spec.md`、`plan.md`、`tasks.md`；三类外部独立交付物按需确认，仅涉及项单独生成并建立链接，不涉及项只记录依据。本需求已全部交付并通过类型校验与多包生产构建验收，文中路径、组件、符号与 F2 品牌图标资产均已逐一核对源码事实；不适用章节保留标题并写明依据，不残留未替换占位符。
> **项目依据**：项目宪章 `.specify/memory/constitution.md`、`AGENTS.md` 及 `wiki/index.md`。

---

**功能分支**：`[006-vue-workbench-ide]`

**创建日期**：2026-11-16

**状态**：已交付归档

**输入**：智能申告报告填写与资源治理平台（`report-agent`）全栈研发工作拆分 —— 负责资源治理工作台前端架构（含 `F2` 智能光笔写单品牌图标资产：`frontend/public/favicon.svg`、`frontend/src/components/BrandMark.vue` 及 `index.html`/`App.vue`/`LoginView.vue` 接入）、四分区模板 IDE 与 CodeMirror 6 Jinja2 词法作用域编辑器、SSE 推理时间线与双向联动三页签证据溯源检查器、可视化网关契约编排与在线拨测、多页签保活与 48 项热更新配置中心。

## 基本信息 【核心】

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-006` |
| 需求名称 | Vue 3 可视化资源治理工作台、四分区模板 IDE 与证据溯源前端 |
| 核算工作量 | `33.0 人天`（项目总工作量 `250.0` 人天中的归档子规格 `006/008`） |
| 资料与证据来源 | 【高可信】代码事实：`frontend/index.html`、`frontend/public/favicon.svg`、`frontend/vite.config.ts`、`frontend/package.json`、`frontend/tsconfig.app.json`、`frontend/src/App.vue`、`frontend/src/constants/terms.ts`、`frontend/src/api/platformApi.ts`、`frontend/src/stores/{platform,workspaceTabs}.ts`、`frontend/src/utils/*`、`frontend/src/views/*`、`frontend/src/components/{BrandMark,ApiVisualEditor,AgentTimeline,EvidenceSourceInspector,FieldEvidenceTable,ReportPreviewContent,WorkspaceTabsBar,GlobalDrawers,GlobalModals,CodeMirrorEditor,StatusTag,SvgIcon}.vue`、`frontend/src/components/workbench/*`<br>【高可信】构建与类型证据：`npx vue-tsc --noEmit -p tsconfig.app.json`、`npm run build`、`frontend/dist/{index,embed}.html`<br>【中可信】契约与知识库：`docs/frontend-api-handoff.md`、`wiki/components/workbench-frontend.md`<br>【归档基线】既有需求拆分：`specs/006-vue-workbench-ide/` 原初版 `spec.md`、`plan.md`、`tasks.md`（18 项任务 / 33.0 人天） |
| 文档版本 | `2.0` |
| 文档状态 | 已交付归档 |

---

## 1. 业务背景与目标 【核心】

### 1.1 业务背景

前代申报系统的模板、规则脚本与接口契约依赖开发人员手工编写与重启发布，业务配置人员缺乏直观的正文变量高亮、无副作用实时渲染预览与可追溯的证据排查界面。在单智能体执行引擎与文件化 Git 发布治理底座就绪后，急需一套企业级 Vue 3 可视化资源治理工作台，将报告模板编排、纯文本技能维护、双协议统一网关契约编排、实时推理过程监控、运行审计排查、版本紧急回退与 `48` 项热配置管理整合为统一流畅的浏览器端生产力应用。

与此同时，企业内部治理系统常运行于反向代理子路径（如 `/agent/`）或受限局域网环境，对前端提出了四项严苛的工程要求：（1）相对资源基址（`base: './'`）与精细 `8` 分包按需加载，并向主工作台（`index.html`）与独立聊天嵌入入口（`embed.html`）复用零重型依赖的 `F2` 智能光笔写单品牌图标资产（`favicon.svg` + `BrandMark.vue`），严守 `embed` 包体洁净；（2）Jinja2 正文编辑器必须精准区分全局字段、局部 `for`/`set` 作用域与注释/字面量，防止误报错和重命名误替换；（3）调试预览与运行审计必须在同值多字段、长文本与海量网关结果中实现双向毫秒定位且避免 Vue 3 深层 Proxy 卡顿；（4）全工作区多页签切换必须支持 `<KeepAlive>` 保活与脏草稿拦截保护，同时遵循 `terms.ts` 统一通俗中文术语口径。

### 1.2 业务目标

- **GOAL-1**：构建基于 Vite 6 多入口、`base: './'` 相对基址、8 个精细 `manualChunks`、`10` 个按需懒加载 Hash 路由、亮暗双主题及统一 `F2` 品牌图标（`favicon.svg` + `BrandMark.vue`）的高性能工作台工程架构。
- **GOAL-2**：交付四分区可拖拽缩放模板 IDE（含 50px 六栏活动栏、24px `ide-statusbar` 与模板名称/说明编辑）、`CodeMirror 6` Jinja2 词法作用域编辑器（`analyzeJinjaBody` / `renameJinjaBodyVariable`）、350ms 防抖内存实时预览与 `409 DRAFT_CONFLICT` 解决弹窗。
- **GOAL-3**：交付消费 `/dryrun/stream` SSE 事件流的轮次折叠推理时间线（突出 `report_rejected` 与 `report_degraded` 联动）、基于 Jinja2 AST 对齐消歧同值字段的报告预览与三页签（`api`/`doc`/`input`）双向定位检查器，以及区分合法 0 行结果与 `not_found` 的运行审计视图。
- **GOAL-4**：交付保留注释同步的双协议 XML/JSON `ApiVisualEditor`（支持 `${$now}` 保护、五模式样例反推与未落盘 `test-call` 回填列）、技能/回归对比视图、锁首页拖拽保活多页签壳层（`KeepAlive max=12` + 聊天 `v-show`）、版本紧急切换与 `48` 项热更新配置中心。

---

## 2. 需求概述 【核心】

本需求对应 `report-agent` 平台的浏览器端可视化资源治理工作台前端（`RA-006`），全部接口直接对接 Spec 005（`RA-005`）提供的真实 `/api/v1/*` REST 与 SSE 端点，无任何本地写死业务 Mock。为兼容同工程内的嵌入式聊天窗口（`RA-007` `/embed.html`），工程入口、公共基础组件与零依赖品牌图标 `BrandMark.vue` 在多入口编译架构下共享隔离：主工作台按需拆分 `codemirror` 与 `element-plus`，确保 `embed` 构建产物零污染。

系统按四大核心用户场景递进构建：P1 阶段优先落盘四分区模板 IDE 与 Jinja2 词法作用域编辑器（`US1`），以及 SSE 实时推理时间线与三页签 AST 双向证据溯源检查器（`US2`）；P2 阶段完善可视化双协议网关接口编排与在线拨测回填、技能与回归对比视图（`US3`），最终收口统一 `F2` 品牌门户与侧栏标志、多页签保活工作区、版本紧急切换及 `48` 项运行配置热更新中心（`US4`）。

### 2.1 用户场景与测试

#### 用户故事 1（US1）— 四分区 IDE 模板工作台与 Jinja2 词法作用域编辑器（优先级：P1）

- **用户旅程**：作为模板配置工程师，我希望在一个类 IDE 四分区工作台内统一维护模板信息（名称与说明）、字段、入参、技能、回归用例与 `body.md.j2` 正文，在编辑或改名字段时获得实时词法作用域高亮、局部循环变量识别、自动联动重命名、内存态实时预览及乐观锁冲突恢复弹窗。
- **优先级理由**：模板编辑器是配置工程师日常使用频次最高的核心界面，消除手工编辑的变量失配与并发覆盖风险是平台可落地的核心前提（P1）。
- **独立测试**：打开 `TemplateWorkbenchView` 拖拽调整四分区宽度/高度，在 `CodeMirror` 中输入 `{{`、`｛｛` 与 `{% for item in 列表 %}` 核对 `jinjaHighlightPlugin` 芯片高亮与局部作用域，经 `handleApplyField` 修改字段名检查正文联动替换与 350ms 防抖预览，模拟 `409 DRAFT_CONFLICT` 验证恢复弹窗。
- **关联需求**：`FR-001`、`FR-002`、`FR-004`、`FR-005`、`FR-006`
- **验收场景**：
  1. **前提** 模板工作台加载完成且正文包含全局字段与 `{% for item in 列表 %}`/`{% set %}` 局部变量，**当** 用户在 `WorkbenchTemplateStage` 输入 `{{`（兼容全角 `｛｛`）或编辑正文时，**则** `analyzeJinjaBody` 联动 `jinjaHighlightPlugin` 精准区分已定义字段芯片（`.jinja-var`）、未定义字段警示（`.undefined`）、当前选中字段（`.is-ide-selected`）以及局部 `for`/`set` 作用域变量（不误报缺失），并提供含跨模板字段的自动补全候选；左侧 50px 活动栏支持切换「信息 / 字段 / 入参 / 技能 / 用例 / 历史」六类资产。
  2. **前提** 用户在 `WorkbenchRightInspector` 修改字段名或新增列表列并点击保存（`handleApplyField`），**当** 提交局部变更或更新临时编辑态字段定义时，**则** `renameJinjaBodyVariable` 同步重写正文中合法非局部引用（保留 `{# ... #}` 注释、字符串字面量与 `.attr` 属性链）、拦截 `RESERVED_JINJA_IDENTIFIERS` 保留字，触发 350ms 防抖调用内存态 `renderPreview` 刷新预览/分屏结果，并在底部 24px `ide-statusbar` 实时显示光标行列与语法诊断状态。
  3. **前提** 服务端存在更新的草稿修订号，**当** 保存动作触发 HTTP `409 DRAFT_CONFLICT` 时，**则** `GlobalModals` 自动弹出冲突恢复弹窗，提供「查看版本差异」（`openConflictDraftDiff`）、加载最新草稿或以当前工作区强制覆盖三种清晰选项。

#### 用户故事 2（US2）— SSE 实时推理时间线与双向联动三页签证据溯源检查器（优先级：P1）

- **用户旅程**：作为配置与运营人员，我希望在调试面板发起流式试运行或在运行记录页面复盘历史执行时，能实时看到按推理轮次组织的 12 类工具时间线与退回/降级预警，并通过点击报告正文片段或字段行双向精准高亮定位到网关结果集、单据原文行号或工单入参。
- **优先级理由**：智能填报可信度依赖于每项结论可被直观核验；消除同值多字段误定位与长运行卡顿是业务采信与日常排障的必经之路（P1）。
- **独立测试**：在 `WorkbenchDebugPanel` 填入通过正则校验的入参与单据发起 `/dryrun/stream`，核对 `AgentTimeline` 按轮次流式渲染与退回/降级点击联动；在存在同值异名字段与合法 0 行列表的运行详情中点击报告片段验证 `ReportPreviewContent` 与 `EvidenceSourceInspector` 双向平滑滚动聚焦高亮。
- **关联需求**：`FR-002`、`FR-003`、`FR-007`、`FR-008`
- **验收场景**：
  1. **前提** 用户在 `WorkbenchDebugPanel` 完成入参（自动 `.trim()` 与锚定正则检查）与单据输入并触发试运行，**当** 后端 `/dryrun/stream` 推送实时 SSE 事件流时，**则** 绑定 `AbortController` 的 `readSseStream` 实时驱动 `AgentTimeline` 按 `round` 渲染全部 12 类平台工具入出参详情，其中 `report_rejected`（`.tl-outcome-err`）与 `report_degraded`（`.tl-outcome-warn`）支持点击报错字段名直接聚焦证据链路，且抽屉支持全屏及 `Esc` 退出；长运行大数组经 `stabilizeRunDetail` 应用 `markRaw` 防过度代理卡顿。
  2. **前提** 运行结果中存在两个值完全相同但绑定不同模板变量（如 `{{商品名称}}` 与 `{{业务名称}}`）的文本片段，或存在合法检索为空的列表字段（`status="found", value=[]`），**当** `ReportPreviewContent` 经 `buildReportSegments`（优先 `alignReportWithTemplate` Jinja2 AST 结构对齐，降级时回退 `fallbackSegmentize`）渲染并响应鼠标悬浮或点击时，**则** `<Teleport to="body">` 悬浮层精确提示字段 KEY，点击报告片段或 `FieldEvidenceTable` 行均可双向驱动 `EvidenceSourceInspector` 自动切至对应页签（`api`、`doc` 或 `input`）并平滑滚动聚焦 `.evidence-highlight-mark` / `.row-highlight`，且合法空列表清晰显示 `无记录（0 行）` 而非报错 `not_found`。

#### 用户故事 3（US3）— 可视化双模式网关契约编排器、技能治理与回归抽屉（优先级：P2）

- **用户旅程**：作为接口与技能配置人员，我希望使用 4 页签可视化表单配合分屏 YAML 编辑统一网关的 XML/JSON 接口契约、直接粘贴响应样例一键推导抽取路径并发起未落盘在线拨测把真实列名回填进契约，同时维护纯文本技能文档并在回归测试页查看双版本字段差异详情抽屉。
- **优先级理由**：手写网关协议 YAML 及点分抽取路径容易出错；可视化同步、内嵌 `${$now}` 护栏与未落盘在线拨测回填能显著降低配置门槛与试错成本（P2）。
- **独立测试**：在 `ApiVisualEditor` 中切换 `unified-gateway-xml` / `unified-gateway-json`、插入 `${$now}` 核对请求预览与 `$` 参数拦截、粘贴响应样例反推列配置、发起 `test-call` 并执行 `syncColumnsFromTestResult`，再进入 `SkillsView` 与 `RegressionView` 验证技能回滚及 `reg-diff-detail` 抽屉。
- **关联需求**：`FR-003`、`FR-009`
- **验收场景**：
  1. **前提** 在 `ApisView` 打开任一契约的 `ApiVisualEditor`，**当** 切换 XML/JSON 连接器、编辑入参或点击快捷插入 `${$now}` 时，**则** 编辑器在保留原 YAML 前置注释与未知扩展键的前提下与 YAML 源码双向同步，并拦截在 `input` 中手动声明 `$` 开头保留参数，右侧折叠区实时生成脱敏 `operation_in` 请求信封预览。
  2. **前提** 用户在响应区粘贴样本 XML/JSON 响应，或携带未保存编辑器 YAML 发起在线拨测，**当** 点击一键反推或 `test-call` 后点击 `syncColumnsFromTestResult` 时，**则** 编辑器准确识别 `auto`/`object`/`list`/`scalar`/`none` 五种模式及 `flatten` 映射列并将真实拨测列名回填至契约列表，同步展示脱敏请求体与实时返回数据。
  3. **前提** 用户在 `SkillsView` 编辑 `SKILL.md` 并通过 `renderSafeMarkdown` 安全预览，或在 `RegressionView` 筛选模板查看差异表，**当** 触发双模式版本回滚（仅写入草稿 / 立即发布上线）或点击某差异行时，**则** `GlobalDrawers` 按需挂载展示 `reg-diff-detail` 抽屉（明确标识批量回归为第二阶段扩展能力）。

#### 用户故事 4（US4）— 多页签保活工作区、统一品牌标识、版本发布视图与 48 项热更新配置中心（优先级：P2）

- **用户旅程**：作为全平台使用者与运维管理员，我希望系统入口门户、浏览器页签与侧栏统一展示清晰专业的 `F2` 智能光笔品牌标识并适配亮暗双主题；在多模块与嵌入式聊天模拟间切换时保留编辑器上下文不被卸载、关闭脏草稿页签时受到保护拦截；并在版本中心执行紧急切换与在设置中心热更新或回滚全部 `48` 项配置及 `X-API-Key`。
- **优先级理由**：企业级治理工作台跨模块高频联动，统一的视觉品牌识别、无丢失页签保活、误关防呆与一站式配置运维页面直接决定日常操作安全性与体验（P2）。
- **独立测试**：访问 `LoginView`、`App.vue` 侧栏与浏览器标签图标核对 `F2` `BrandMark` 挂载与亮暗主题适配；拖拽 `WorkspaceTabsBar` 验证首页锁定、关闭未保存页签触发 `confirmDiscardIfDirty` 拦截、测试 `⌘K` 与 `⌘S` 快捷键、`ReleasesView` 跨版本资源跳转与紧急回退，并在 `SettingsView` 测试提示词时间线、`X-API-Key` 轮换及 `48` 项配置局部默认重置与 `cN` 回滚。
- **关联需求**：`FR-001`、`FR-002`、`FR-010`
- **验收场景**：
  1. **前提** 用户访问门户登录页 `LoginView` 或登录后进入主工作台 `App.vue`，**当** 页面完成渲染或在浅色/深色主题间切换时，**则** 浏览器标签页读取 `index.html` 内联 SVG Data URI / `public/favicon.svg` 呈现统一 `F2` 智能光笔图标，`LoginView` 品牌区与 `App.vue` 左侧栏分别挂载零外部重型依赖的 `BrandMark` 组件（`useId()` 隔离渐变 ID 防止多实例冲突，侧栏 `26px`、登录页 `38px`），并支持全局导航统一术语（`NAV_LABELS` / `NAV_GROUP_LABELS`）。
  2. **前提** 用户在工作区打开了多个路由页签与内嵌工单聊天页签，**当** 通过 `WorkspaceTabsBar` 拖拽调整顺序（首页固定第 0 位）、关闭含未保存修改的页签触发 `before-leave` 拦截，或激活内嵌聊天进入 `.main-wrapper.is-chat-fullscreen` 时，**则** `<KeepAlive :max="12">` 保持路由视图状态、`v-show` 维持 iframe 存活不重连，脏页签弹出保存/放弃/取消确认提示，退出登录时调用 `tabsStore.resetAll()` 清理动态聊天页签。
  3. **前提** 管理员进入 `ReleasesView` 或 `SettingsView`，**当** 对比两版本差异点击跳转、提交带必填原因的 `emergency-switch`、操作 `X-API-Key` 显隐/复制/清空/重生成，或保存/局部重置（保留 URL 与密钥）/回滚 `48` 项运行时配置时，**则** 所有状态与审计列表即时更新并受请求序号守卫保护防并发错序。

### 2.2 成功标准

- **SC-001**：前端工程在严格模式（`frontend/tsconfig.app.json`）下零报错通过 `npx vue-tsc --noEmit -p tsconfig.app.json`；`npm run build` 稳定产出包含 `vue-core`、`vue-state`、`markdown-lib`、`icons`、`element-plus`、`element-deps`、`codemirror`、`workbench-libs` 8 个 `manualChunks` 的产物，所有页面视图按需懒加载，且 `BrandMark.vue` 在被主工作台和嵌入页复用时不将 `element-plus` 或 `codemirror` 引入 `embed.html`。
- **SC-002**：模板正文编辑输入 `{{` / `｛｛` 或修改字段后，`350ms` 防抖内存态渲染预览无副作用刷新；字段重命名同步更新正文中 100% 合法非局部引用且零误伤 `{# ... #}` 注释、字符串字面量与 `.attr` 属性访问。
- **SC-003**：报告预览与证据检查器在同值多字段及跨 12 类工具的运行记录中，通过 `alignReportWithTemplate` 与双向高亮 100% 精准定位至对应 `resultId` 表格行、单据 `Lxxx` 行或工单入参，且清晰区分合法 0 行结果 `无记录（0 行）` 与 `not_found` 缺失占位。
- **SC-004**：`ApiVisualEditor` 完整支持 `unified-gateway-xml` 与 `unified-gateway-json` 双协议及 `auto`/`object`/`list`/`scalar`/`none` 五种提取模式，支持一键样本反推与未落盘 `test-call` 列同步回填。
- **SC-005**：`F2` 品牌图标在 `favicon.svg`、`index.html`、`LoginView.vue` 与 `App.vue` 完整落地并适配双主题；全局多页签支持最多 12 个 `<KeepAlive>` 路由视图与聊天 iframe `v-show` 保活，脏页签关闭动作 100% 拦截确认；设置中心完整覆盖提示词时间线、`X-API-Key` 轮换与 `48` 项热更新配置运维。

### 2.3 假设

- 前端工程与嵌入式聊天窗口前端（`RA-007` `/embed.html`）共用同一个 `frontend/` Vite 多入口工程、`BrandMark.vue` 轻量品牌组件、`sse.ts`/`markdown.ts`/`sanitizeHtml.ts`/`timelineFormat.ts` 等共享工具模块；`embed.html` 内部聊天组件规格归属 `RA-007`，本需求在主工作台侧仅负责宿主协同（`App.vue`、`workspaceTabs.ts`、`ChatSimView.vue`、`ChatIframeTabPane.vue`）。
- 本需求采用与 Spec 005 后端一致的真实 REST/SSE 契约（`docs/frontend-api-handoff.md`），开发态通过 Vite `server.proxy` 将 `/api` 转发至 `http://127.0.0.1:8000`；前端质量门禁以严格 `vue-tsc --noEmit`、Vite 多入口分包生产构建与联调验证为主。
- 本需求 `33.0` 人天按全周期工程交付口径归档核算（覆盖 Vite 工程与 `F2` 品牌资产搭建、API/Pinia/安全工具基座、四分区 IDE 与 CodeMirror Jinja2 插件、SSE 时间线与 AST 双向证据检查器、双协议可视化接口编排、多页签保活壳层与 `48` 项设置中心及构建/类型门禁修复）。

---

## 3. 术语与概念定义 【核心，如有新术语】

> 全界面通俗中文术语统一定义于 `frontend/src/constants/terms.ts`（`NAV_LABELS`、`NAV_GROUP_LABELS`）与 `wiki/components/workbench-frontend.md` 第 4 节（如「模板」「技能」「API」「运行记录」「回归测试」「版本发布」「系统设置」「浅色 / 深色」）；下表仅列本需求前端工程架构新增专用技术术语。

| 术语 | 英文/标识 | 定义 | 备注 |
| --- | --- | --- | --- |
| F2 智能光笔品牌资产 | `F2` / `BrandMark.vue` / `favicon.svg` | 平台统一视觉品牌标志（深蓝圆角底 + 白单据底板 + 蓝绿渐变光笔高亮条 + 电子笔与星芒），支持多实例渐变 ID 隔离与零重型依赖复用 | 接入 `index.html`、`App.vue`、`LoginView.vue` 并共享于 `embed.html` |
| Jinja 词法作用域分析 | `analyzeJinjaBody` | 前端纯函数扫描器，识别 `{{ }}` / `{% %}` / `{# #}`、过滤器、`is [not] hasDigit` 及 `{% for %}`/`{% set %}` 局部上下文变量，驱动芯片高亮与零误报缺失胶囊 | 配合 `RESERVED_JINJA_IDENTIFIERS` 拦截保留字 |
| AST 结构对齐分段 | `alignReportWithTemplate` | 基于 Jinja2 AST 控制流与占位结构将已渲染报告文本切片绑定至精确字段 Key 的算法，解决不同字段输出相同文本时的消歧问题 | 异常或结构失配时自动降级 `fallbackSegmentize` |
| 多页签工作区保活 | `WorkspaceTabs` / `<KeepAlive :max="12">` | 由 `useWorkspaceTabsStore` 管理的锁首页拖拽卡片页签体系，结合 Vue `<KeepAlive>` 与聊天 `v-show` 实现跨模块切换状态零丢失 | 集成 `before-leave` 脏草稿关闭挽救拦截 |
| 响应式降载 | `stabilizeRunDetail` (`markRaw`) | 对长运行明细中的 `events`、`toolCalls`、`apiResults`、`documentLines` 等海量只读数组执行 `markRaw`，剥离 Vue 3 深层 Proxy 开销 | 确保千行级证据与长链路渲染流畅 |

---

## 4. 用户角色 【核心】

| 角色 | 类型 | 本需求中可执行的操作与数据范围 | 权限/安全约束 |
| --- | --- | --- | --- |
| 平台管理员 / 系统维护 | 人工角色 | 登录门户、查看大盘与运行审计、执行版本紧急切换、编辑提示词与 `48` 项运行配置、管理 `X-API-Key` 轮换、在聊天模拟台联调 | 路由守卫校验 `/auth/me` 登录态，遇到 `401` 经 `auth:unauthorized` 跳回 `LoginView` 并清理敏感内存与页签 |
| 业务配置人员 / 模板开发者 | 人工角色 | 在 `TemplateWorkbenchView` 编排模板与四分区调试、使用 `ApiVisualEditor` 编排与拨测接口、维护技能 `SKILL.md`、沉淀回归用例 | 受服务端 `expected_revision` 乐观锁与 `409` 冲突对比弹窗约束；XSS 富文本受 `sanitizeHtml` 净化 |
| 宿主模拟联调方 | 内部协同角色 | 在 `ChatSimView` 构造工单入参、自动带出系统 Key 并通过 `ChatIframeTabPane` 启动全屏嵌入页签联调验证 `postMessage` | 仅向同源 iframe 握手并严格校验 `event.origin` 与 `event.source` |

---

## 5. 功能需求 【核心】

### 5.1 工程架构、品牌视觉与通信状态基础设施

#### FR-001 Vite 多入口精细分包、双主题及 F2 品牌图标资产

- **来源**：`frontend/vite.config.ts`、`frontend/index.html`、`frontend/public/favicon.svg`、`frontend/src/components/BrandMark.vue`、`frontend/src/router/index.ts`、`frontend/src/assets/styles.css`、`frontend/src/constants/terms.ts`
- **描述**：搭建适配子路径反代与严格 TypeScript 的 Vue 3.5 + Vite 6 多入口工程，建立亮暗双主题 CSS Token、统一术语常量表、8 分包拆包策略及全局 `F2` 智能光笔写单品牌图标体系。
- **关联用户故事/成功标准**：`US1`、`US4` / `SC-001`、`SC-005`
- **业务规则**：
  1. `vite.config.ts` 默认使用相对资源路径 `base: './'`，同时构建管理端 `index.html` 与轻量嵌入页 `embed.html` 两个入口，并将 `node_modules` 拆分为 `vue-core`、`vue-state`、`markdown-lib`、`icons`、`element-plus`、`element-deps`、`codemirror`、`workbench-libs` 8 个独立 chunk。
  2. `router/index.ts` 采用 `createWebHashHistory` 并对 `login`、`templates`、`workbench`、`skills`、`apis`、`runs`、`regression`、`releases`、`settings`、`chatSim` 全部 10 个视图启用动态懒加载。
  3. 品牌视觉采用 `F2` 智能光笔写单资产：`frontend/public/favicon.svg` 提供标准 64x64 矢量资产，`frontend/index.html` 在 `<head>` 内联 SVG `data:image/svg+xml` 图标实现离线/子路径零额外请求；`frontend/src/components/BrandMark.vue` 零外部重型依赖（仅引入 `vue` `useId`），以 `ra-f2-grad-${useId()}` 隔离线性渐变 ID 防止同页多实例冲突，接入 `App.vue` 左侧品牌区（`size=26`）与 `LoginView.vue` 登录主卡（`size=38`）。
  4. `styles.css` 定义 `[data-theme="light"]` 与 `[data-theme="dark"]` 完整双主题设计变量，主题偏好存储于独立的 `localStorage['report-agent-theme']`；`terms.ts` 集中维护 `NAV_LABELS` 与 `NAV_GROUP_LABELS`。
- **输入/触发**：页面加载、Hash 路由跳转、浅色/深色主题切换与 Vite 生产构建。
- **输出/结果**：按需拆分加载的视图、自适应主题与全场景一致的 `F2` 品牌图标渲染。
- **验收标准**：
  - AC-1：`npx vue-tsc --noEmit -p tsconfig.app.json` 与 `npm run build` 零报错完成，产物精确生成 8 个 `manualChunks` 且 `embed.html` 不引入 `element-plus` 与 `codemirror`；`BrandMark.vue` 挂载在 `App.vue` 与 `LoginView.vue` 显示正常无梯度 ID 冲突。
  - AC-2：在登录页与主工作台间切换亮暗主题时，DOM `data-theme` 与 `localStorage` 同步刷新且品牌区与图标清晰可辨。

#### FR-002 通信客户端、SSE 解析器与 Pinia 中心/页签状态机

- **来源**：`frontend/src/api/platformApi.ts`、`frontend/src/utils/sse.ts`、`frontend/src/stores/platform.ts`、`frontend/src/stores/workspaceTabs.ts`
- **描述**：封装全真实后端 REST/SSE 客户端、基于 `AbortController` 的换行容错流读取器与 Pinia 全局资源治理/多页签状态机。
- **关联用户故事/成功标准**：`US1`、`US2`、`US4` / `SC-001`、`SC-003`、`SC-005`
- **业务规则**：
  1. `platformApi.ts` 对接 `/api/v1/*`，兼容包装错误体 `{detail}` 提取 `ApiError(status, code, message, details)`；收到 HTTP `401` 时广播 `auth:unauthorized` 事件触发登出回跳。
  2. `readSseStream` 解析 `event:`、`data:` 与 `\r\n` 换行及尾帧刷新，发生取消或异常时强制 `reader.cancel()` 并静默忽略 `AbortError`。
  3. `usePlatformStore` 维护全量资源态、请求序号守卫（防止快速切换模板/修订/运行引发过期响应覆盖）及 `409` 冲突上下文；`stabilizeRunDetail` 对大数组执行 `markRaw` 消除深层响应式代理开销；`loadSettings` 支持 `preserveDirty` 保护未保存系统提示词草稿。
- **输入/触发**：路由切换、资源读写保存、试运行 SSE 触发、登出或 `401` 广播。
- **输出/结果**：强类型后端数据流、防竞态状态更新与实时响应式 UI 刷新。
- **验收标准**：
  - AC-1：连续快速切换两个模板或运行记录时，先发后到的过期响应被递增序号守卫丢弃，界面不发生错位闪烁。
  - AC-2：点击中断正在进行的 SSE 试运行或收到 `401` 响应时，流读取器立即取消连接且不弹出虚假报错。

#### FR-003 前端安全净化、Markdown LRU、Diff 与受限剪贴板工具库

- **来源**：`frontend/src/utils/sanitizeHtml.ts`、`frontend/src/utils/markdown.ts`、`frontend/src/utils/textDiff.ts`、`frontend/src/utils/listColumns.ts`、`frontend/src/utils/clipboard.ts`、`frontend/src/components/{SvgIcon,StatusTag}.vue`
- **描述**：构建跨工作台复用的零过度抽象纯函数安全/解析工具库与基础 UI 徽标组件。
- **关联用户故事/成功标准**：`US2`、`US3` / `SC-001`、`SC-004`
- **业务规则**：
  1. `sanitizeHtml` 基于浏览器原生 `DOMParser` 执行严格元素、属性与 URL 协议白名单过滤（阻断 `<script>`、`on*` 事件与 `javascript:` 链接）；`renderSafeMarkdown` 将 `marked` 与 `sanitizeHtml` 结合并维护容量 `32` 的 LRU 缓存。
  2. `textDiff.ts` 提供全量对照 `buildFullDiffRows` 与折叠上下文 `buildDiffRows`；`listColumns.ts` 解析与序列化 `列名 | 类型 | 说明` 管道格式；`copyToClipboard` 在 `navigator.clipboard` 不可用（如非 HTTPS 或受限 iframe）时回退隐藏文本域选中复制。
- **输入/触发**：技能/报告 Markdown 渲染、版本对比、列表列配置编辑及密钥/文本复制动作。
- **输出/结果**：XSS 免疫的安全 HTML、结构化行级 Diff、精确列数组与可靠剪贴板写入反馈。
- **验收标准**：
  - AC-1：向技能正文或报告传入含 `<img onerror=...>` 或 `[x](javascript:alert(1))` 的文本时，`renderSafeMarkdown` 均剥离危险脚本与协议。
  - AC-2：在普通 HTTP 非安全上下文下点击复制 API Key 或报文时，`copyToClipboard` 自动降级成功返回 `true`。

### 5.2 四分区模板 IDE 与 Jinja2 编辑器

#### FR-004 四分区可拖拽模板 IDE 骨架、六栏活动栏与状态栏

- **来源**：`frontend/src/views/TemplateWorkbenchView.vue`、`frontend/src/components/workbench/WorkbenchLeftExplorer.vue`、`frontend/src/views/TemplatesListView.vue`
- **描述**：提供可自由调整比例的四分区模板 IDE 主舞台、左侧双列资源浏览器、基线漂移条及实时状态栏，并支持模板清单总览与引用胶囊。
- **关联用户故事/成功标准**：`US1` / `SC-001`
- **业务规则**：
  1. `TemplateWorkbenchView` 组装左栏、中上正文舞台、中下调试区与右侧检查器共三组可拖拽分割条，以及底部 `24px` 高的 `ide-statusbar`（显示当前光标行列、词法诊断数与未保存标记）和顶部漂移告警条。
  2. `WorkbenchLeftExplorer` 包含 `50px` 竖向活动栏（6 项：`info` 信息、`fields` 字段、`inputs` 入参、`skills` 技能、`cases` 用例、`history` 历史）及可折叠资源列表：在「信息」栏直接编辑 `store.templateName` 与 `store.templateDescription`；字段列表接入 `SortableJS` 无 DOM 错位拖拽重排并支持跨模板字段一键引入。
  3. 正文出现未定义全局字段且非 `RESERVED_JINJA_IDENTIFIERS` 与局部 `for`/`set` 变量时，左侧「字段」栏显示一键新建胶囊；`TemplatesListView` 使用 `.ref-count-pill` 与限高 `240px` 滚动 `.ref-popover-list` 展示关联技能。
- **输入/触发**：拖拽分割条、点击 50px 活动栏、拖拽字段排序、点击快速新建字段胶囊或模板清单筛选。
- **输出/结果**：实时更新的四分区布局、模板属性与字段顺序变更以及即时关联列表弹窗。
- **验收标准**：
  - AC-1：拖拽左侧/右侧或调试区分割条尺寸即时平滑改变，再次点击当前活动栏图标折叠/展开列表面板；在「信息」分类修改模板名称或说明点击保存草稿后成功持久化至服务端。
  - AC-2：正文中出现的 `for` 循环迭代变量与 Jinja 保留关键字不触发左侧一键建字段缺失胶囊。

#### FR-005 CodeMirror 6 Jinja2 词法作用域编辑器与无副作用防抖预览

- **来源**：`frontend/src/utils/jinjaBody.ts`、`frontend/src/components/CodeMirrorEditor.vue`、`frontend/src/components/workbench/WorkbenchTemplateStage.vue`
- **描述**：基于 `CodeMirror 6` 构建具备专业 Jinja2 词法与局部变量作用域感知的模板正文编辑器，并提供四模式舞台切换与内存态 350ms 防抖预览。
- **关联用户故事/成功标准**：`US1` / `SC-002`
- **业务规则**：
  1. `analyzeJinjaBody` 逐段解析 `{# ... #}`、`{{ ... }}`、`{% ... %}`、字符串字面量、`| filter`、`is [not] hasDigit` 及 `{% for %}`/`{% set %}` 作用域栈，产出 `tags`、`fieldOccurrences`（定位区间）与结构化诊断。
  2. `WorkbenchTemplateStage` 注册 `jinjaHighlightPlugin` 装饰器为已定义字段（`.jinja-var`）、未定义变量（`.undefined`）与选中字段（`.is-ide-selected`）着色；输入 `{{` 或全角 `｛｛` 时自动弹出含已有字段与跨模板字段的补全列表，支持一键插入结构化 `{% if %}` 条件代码块。
  3. 支持「源码 / 实时预览 / 分屏 / 版本 Diff」四模式切换：编辑正文或未落盘字段定义后经过 `350ms` 防抖调用内存态 `renderPreview` 刷新预览结果，Diff 模式调用 `buildFullDiffRows` 对比草稿与线上正文。
- **输入/触发**：正文代码输入、全/半角插值触发、字段选中联动、模式切换与模板预览请求。
- **输出/结果**：语法芯片高亮、补全浮层、实时渲染预览文本与全量行级 Diff 视图。
- **验收标准**：
  - AC-1：输入 `｛｛` 自动触发候选字段列表；嵌套 `{% for r in 列表 %}{{ r.列 }}{% endfor %}` 中 `r` 识别为 `loopVar` 不标红为 `.undefined`。
  - AC-2：修改正文后 `350ms` 内自动调用内存预览接口更新右侧预览区，不产生草稿写盘请求。

#### FR-006 右侧属性检查器、字段重命名联动与 409 乐观锁冲突弹窗

- **来源**：`frontend/src/components/workbench/WorkbenchRightInspector.vue`、`frontend/src/components/GlobalModals.vue`
- **描述**：支持在右侧栏精细编辑字段类型、`list` 多态列、证据模式、`quoteWhole` 整段一致、日期格式与缺失策略，实现重命名正向联动并解决服务端乐观锁冲突。
- **关联用户故事/成功标准**：`US1` / `SC-002`
- **业务规则**：
  1. `handleApplyField` 校验字段名合法性并阻断 `RESERVED_JINJA_IDENTIFIERS`；字段改名时使用 `renameJinjaBodyVariable` 同步替换正文中合法变量引用（保留注释、字符串字面量、过滤器与属性链）并携带 `originalName` 与 `revision` 提交后端。
  2. 编辑 `list` 类型字段时接入 `listColumns` 校验列结构并限制证据类型为 `quote` 或 `derive`（不提供 `input`）。
  3. 任一草稿写请求触发 `409 DRAFT_CONFLICT` 时，`GlobalModals` 自动弹出冲突对比模态框，支持点击 `openConflictDraftDiff()` 查看线上/草稿差异、刷新拉取服务端版本或强制覆盖。
- **输入/触发**：右侧表单编辑并提交 `handleApplyField`、回归用例属性修改或 `409` 冲突响应。
- **输出/结果**：更新后字段 DTO、同步刷新后的正文文本或冲突解决弹窗交互。
- **验收标准**：
  - AC-1：通过 `handleApplyField` 将字段 `旧名称` 改为 `新名称`，正文 `{{旧名称}}` 与 `{% if 旧名称 %}` 同步变更为 `新名称`，而 `{# 旧名称 #}` 与 `"旧名称"` 原样保留。
  - AC-2：在多端并发场景收到 `409` 后点击「查看版本差异」正常展示对比视图，选择覆盖或重载后弹窗关闭并同步最新 `revision`。

### 5.3 实时推理时间线与双向证据溯源

#### FR-007 SSE 试运行控制台、12 类工具推理时间线与退回/降级联动

- **来源**：`frontend/src/components/workbench/WorkbenchDebugPanel.vue`、`frontend/src/components/AgentTimeline.vue`、`frontend/src/components/FieldEvidenceTable.vue`、`frontend/src/utils/timelineFormat.ts`
- **描述**：在工作台下方调试抽屉与运行详情页实现基于真实入参正则校验、190px 历史记录栏、SSE 流控及按轮次折叠展示 12 类平台工具与证据退回/降级交互。
- **关联用户故事/成功标准**：`US2` / `SC-003`
- **业务规则**：
  1. `WorkbenchDebugPanel` 左侧展示 `190px` 调试运行记录栏，顶部支持按模板用例一键填充与正交预设入参正则校验（`.trim()` + `^(?:...)$` 全串锚定），抽屉支持全屏缩放且按 `Esc` 键恢复；取消试运行通过 `dryRunAbortController` 安全中止 SSE 流。
  2. `AgentTimeline` 调用 `groupEventsByRound` 与 `describeToolEvent` 按轮次归纳显示全部 12 类平台工具入出参（含 `call_api` 展开记录表、`query_result` 条件摘要与 `load_skill` 批量存在性跳转）。
  3. 对 `report_rejected`（`.tl-outcome-err` 红色高亮）与 `report_degraded`（`.tl-outcome-warn` 琥珀色高亮）事件卡片中的关联字段名提供点击联动，直接选中并高亮对应字段证据与源码来源。
- **输入/触发**：入参表单与单据正文输入、试运行触发/取消、历史记录切换及时间线字段点击。
- **输出/结果**：实时滚动的轮次工具轨迹、字段明细表 `FieldEvidenceTable` 及选中高亮焦点。
- **验收标准**：
  - AC-1：输入不满足 `pattern` 正则的入参点击试运行被前端立即拦阻提示；触发流式试运行时按 `round` 实时追加工具调用卡并支持展开参数与返回记录。
  - AC-2：点击 `report_rejected` 卡片中的退回字段名，右侧证据检查器同步跳转并高亮对应依据。

#### FR-008 Jinja2 AST 同值消歧报告预览与三页签双向滚动定位检查器

- **来源**：`frontend/src/utils/reportSegments.ts`、`frontend/src/components/ReportPreviewContent.vue`、`frontend/src/components/EvidenceSourceInspector.vue`、`frontend/src/views/RunsView.vue`
- **描述**：实现精确消除同值多字段歧义的交互式报告正文预览、三页签（`api` / `doc` / `input`）证据双向平滑定位高亮及多条件运行审计台账查询。
- **关联用户故事/成功标准**：`US2` / `SC-003`
- **业务规则**：
  1. `buildReportSegments` 优先运行 `alignReportWithTemplate` 基于候选 Jinja2 模板结构定位各渲染值所属字段 Key；当模板缺失或对齐异常时降级至最长匹配 `fallbackSegmentize`。
  2. `ReportPreviewContent` 渲染带交互切片的报告正文，鼠标悬停即刻通过 `<Teleport to="body">` 展示无延迟、防裁剪字段 KEY 与证据来源胶囊，点击任意值高亮同类字段并联动 `EvidenceSourceInspector`。
  3. `EvidenceSourceInspector` 根据 `resolveEvidenceInspectorTab` 自动切换 `api`（网关 `resultId` 表行与单元格高亮）、`doc`（单据原文 `Lxxx` 行高亮）或 `input`（工单入参表高亮），自动平滑滚动使 `.evidence-highlight-mark` 或 `.row-highlight` 居中可见；当列表字段 `status="found"` 且 `value=[]` 时明确渲染中性态 `无记录（0 行）`，严格区分 `not_found`。
  4. `RunsView` 对接 `GET /api/v1/runs` 与 `GET /runs/{runId}`，支持多维过滤与一键「保存为回归用例」及「加载至试运行」（受脏草稿切换二次确认保护）。
- **输入/触发**：运行结果 `RunDetail`、报告片断悬浮/点击、字段表行点击与运行台账筛选条件。
- **输出/结果**：消歧切片报告视图、悬浮 Tooltip、三页签滚动定位聚焦高亮与运行详情面板。
- **验收标准**：
  - AC-1：同一份报告存在两个相同字符串值分属不同字段时，分别悬停与点击能准确弹出各自对应字段 KEY 并跳转到独立证据来源。
  - AC-2：列表字段查得 0 条记录时展示中性态 `无记录（0 行）`，而真实未查到字段展示缺省提示与原因，不混淆渲染。

### 5.4 双协议接口可视化编排、多页签工作区与设置中心

#### FR-009 双协议可视化网关编排器、技能 Markdown 编辑与回归抽屉

- **来源**：`frontend/src/components/ApiVisualEditor.vue`、`frontend/src/views/ApisView.vue`、`frontend/src/views/SkillsView.vue`、`frontend/src/views/RegressionView.vue`、`frontend/src/components/GlobalDrawers.vue`
- **描述**：提供集成 4 页签可视化表单与保留注释分屏 YAML 的统一网关编排器、未落盘 `test-call` 实时拨测与列回填、技能安全预览与双模式回滚，以及回归差异明细抽屉。
- **关联用户故事/成功标准**：`US3` / `SC-004`
- **业务规则**：
  1. `ApiVisualEditor` 支持 `unified-gateway-xml` 与 `unified-gateway-json` 双协议 4 页签可视化表单，序列化时合并保留原 YAML 前置注释与未知键；内置 `BUILTIN_PLACEHOLDERS`（`${$now}`）快捷插入按钮并阻止在 `input` 中手动声明 `$` 开头保留参数；右侧实时预览脱敏 `operation_in` 请求信封。
  2. 支持粘贴样本 XML/JSON 响应自动识别 `auto`/`object`/`list`/`scalar`/`none` 提取模式与 `flatten` 映射列；在 `ApisView` 基于未保存编辑器 YAML 发起 `test-call` 后，可通过 `syncColumnsFromTestResult` 将真实返回列名同步写入契约列定义。
  3. `SkillsView` 支持 `SKILL.md` 编辑、32 LRU `renderSafeMarkdown` 安全预览、草稿/上线双模式回滚与限高 `.ref-popover-list` 关联展示；`RegressionView` 与 `GlobalDrawers`（`reg-diff-detail`）支持模板范围筛选与双版本逐字段对比抽屉（明确标识批量回归为第二阶段扩展功能）。
- **输入/触发**：可视化表单编辑、`${$now}` 插入、响应样本粘贴反推、未落盘拨测、技能回滚与回归差异行点击。
- **输出/结果**：注释保真 YAML 文本、实时请求信封预览、推导/同步的 `records.columns`、安全 Markdown 视图与 `reg-diff-detail` 抽屉。
- **验收标准**：
  - AC-1：编辑包含手写注释和扩展字段的 API YAML 时，经可视化表单改超时并保存后注释和扩展字段完整保留；尝试手动新增 `$now` 入参被阻断提示。
  - AC-2：执行 `test-call` 并点击同步列定义后，响应数据列自动并入可视化列表且支持直接保存草稿。

#### FR-010 多页签保活工作区壳层、门户登录、版本中心与 48 项热更新设置中心

- **来源**：`frontend/src/App.vue`、`frontend/src/components/WorkspaceTabsBar.vue`、`frontend/src/stores/workspaceTabs.ts`、`frontend/src/views/LoginView.vue`、`frontend/src/views/ReleasesView.vue`、`frontend/src/views/SettingsView.vue`、`frontend/src/views/ChatSimView.vue`、`frontend/src/components/ChatIframeTabPane.vue`、`frontend/src/components/ChatSimTemplatePicker.vue`
- **描述**：构建全局可拖拽多页签工作区与门户认证页，完善版本时间线紧急切换及集提示词、密钥轮换与 48 项热更新于一体的设置中心。
- **关联用户故事/成功标准**：`US4` / `SC-005`
- **业务规则**：
  1. `LoginView.vue` 实现带全屏内联 SVG 工程网格、主题切换同步（`MutationObserver`）、输入进度条（`0/2`→`2/2`）与 `BrandMark`（`size=38`）的专业登录门户。
  2. `App.vue` 左侧展示可折叠三分组导航与 `BrandMark`（`size=26`），提供 `⌘K` 全局检索（兼容新旧术语关键字）与 `⌘S` 保存快捷键；右侧 `WorkspaceTabsBar` 支持锁首页 `SortableJS` 拖拽排序（重排前还原 DOM 再驱动状态避免 VNode 错位）、`<el-dropdown>` 批量关闭菜单与 `before-leave` 脏草稿挽救拦截（`confirmDiscardIfDirty`）；主区通过 `<KeepAlive :max="12">` 保活路由视图并通过 `v-show` + `.main-wrapper.is-chat-fullscreen` 保活全屏聊天模拟器 iframe。
  3. `ReleasesView` 展示全局时间线、任意两版本跨资源 Diff（支持资源名点击跳转定位）与带必填原因的 `emergency-switch` 弹窗。
  4. `SettingsView` 分三个子页签管理：提示词实时编辑与版本时间线对比回滚、`X-API-Key` 显隐/复制/清空/随机重生成管理卡片，以及覆盖全部 `48` 项配置的 4 组热更新表单（含 `clearLlmApiKey` / `clearGatewayAppId` / `clearGatewayAccessToken` 安全清空标志、空值默认值兜底 `parseNumOrDefault`、`handleResetDefaultParams` 仅重置参数保留地址与密钥、以及 `c1..cN` 修订对比与回滚/环境重同步）。
- **输入/触发**：页签拖拽/关闭、`⌘K`/`⌘S` 快捷键、紧急切换提交、`SettingsView` 表单保存/局部重置/回滚/重生成 API Key。
- **输出/结果**：保活不丢的编辑上下文、拦截确认弹窗、更新的线上版本与生效中的热配置状态。
- **验收标准**：
  - AC-1：在编辑未保存状态关闭对应页签或切换路由加载试运行数据时弹出确认弹窗，选取消则保留原工作区内容不丢失。
  - AC-2：在 `SettingsView` 点击「恢复默认参数」时仅数值/配额/枚举回到默认，`gatewayUrl`、`llmBaseUrl`、`llmModel` 与已填入密钥字段保持不变；提交修订回滚后页面实时刷新生效版本。

---

## 6. 非功能需求 【补充】

| 类型 | 编号 | 说明 | 验收方式 |
| --- | --- | --- | --- |
| 零业务硬编码与资源隔离（宪章 I） | `NFR-001` | 前端工作台、Jinja 分析器、报告分段算法与可视化接口编辑器完全基于服务端下发的动态 `TemplateItem` / `ApiItem` / `RunDetail` 数据驱动，禁止写入特定模板 ID 或业务规则硬编码 | 源码核对与多模板联调 |
| 强证据防幻觉展示（宪章 II） | `NFR-002` | `AgentTimeline`、`FieldEvidenceTable`、`ReportPreviewContent` 与 `EvidenceSourceInspector` 严格忠实展示后端状态，清晰分离 `无记录（0 行）` 合法空表与 `not_found` 缺失，醒目标示 `report_rejected` 与 `report_degraded` | `ReportPreviewContent.vue` / `EvidenceSourceInspector.vue` 逻辑核查 |
| 并发协同与前端响应式性能（宪章 III / V） | `NFR-003` | 全量写操作携带 `revision` 并适配 `409` 弹窗；`stabilizeRunDetail` 应用 `markRaw` 剥离大数组 Proxy；异步加载递增请求序号守卫防错序；`renderSafeMarkdown` 配置 32 条目 LRU 缓存；8 分包按需懒加载 | `vue-tsc`、构建分包检查与源码核验 |
| 前端 XSS 防护、零硬编码凭据与安全兜底（宪章 VI） | `NFR-004` | 外源 Markdown 与 HTML 渲染经 `DOMParser` 白名单 `sanitizeHtml` 净化；代码中零硬编码真实密钥或默认密码；网关与模型密钥在设置表单仅展示掩码与显式清空开关；剪贴板异常安全降级 | `sanitizeHtml.ts`、`clipboard.ts`、`SettingsView.vue` 核查 |
| 前端代码质量与多入口分包边界（宪章 VIII / 技术约束） | `NFR-005` | `npx vue-tsc --noEmit -p tsconfig.app.json` 全量严格模式零报错；`npm run build` 多入口分包洁净，`embed.html` 复用 `BrandMark.vue` 时零混入 `element-plus` 与 `codemirror`；新增组件与函数附带中文注释 | `vue-tsc`、`npm run build` 及检查 `frontend/dist/embed.html` |

---

## 7. 数据与存储需求 【补充】

> 本需求为浏览器端单页应用，所有持久化业务资源均通过 `/api/v1/*` 由后端文件化存储管理；前端仅使用浏览器本地轻量存储保存非敏感用户界面偏好与当前标签会话凭证。

| 数据对象/存储位置 | 变更类型 | 关键字段与口径 | 一致性/留存策略 | 关联需求 |
| --- | --- | --- | --- | --- |
| `localStorage['report-agent-theme']` | 读写 | 字符串枚举 `"light"` / `"dark"` | 独立键名与账号生命周期解耦，登出或切号不覆盖用户主题设置 | `FR-001`、`FR-010` |
| `sessionStorage['agent-python-token']` | 读写 | 会话 Bearer 令牌字符串（同源时另附 HttpOnly `ra_session` Cookie） | 登录写入，登出或捕获 `auth:unauthorized` 事件时自动清除 | `FR-002` |
| `localStorage` 侧栏折叠与编辑器偏好 | 读写 | 侧栏折叠状态与局部调试布局尺寸 | 异常受限环境下 `try/catch` 安全降级，不影响主流程渲染 | `FR-004`、`FR-010` |
| Pinia 内存态（`usePlatformStore` / `useWorkspaceTabsStore`） | 运行期内存 | 资源列表、当前工作草稿、脏状态标识、多页签数组、`KeepAlive` 队列、推理轨迹数组（`markRaw`） | 递增序号守卫防乱序；退出登录触发 `tabsStore.resetAll()` 清理动态聊天页签与测试密钥 | `FR-002`、`FR-010` |

---

## 8. 外部接口与集成 【补充】

| 接口/系统 | 方向 | 交互内容 | 是否新增 | 关联需求 | 备注 |
| --- | --- | --- | --- | --- | --- |
| Spec 005 后端治理 API（`/api/v1/*`） | 出站（HTTP / SSE） | 认证、模板/技能/接口/提示词全生命周期治理、在线拨测、版本 Diff 与紧急切换、运行查询与 48 项热配置 | 否（对接 `RA-005` 既有契约） | `FR-001`~`FR-010` | 开发态 Vite 代理至 `127.0.0.1:8000`，生产由 `FRONTEND_DIST` 同源托管 |
| Spec 007 嵌入式聊天 iframe（`embed.html`） | 宿主协同（`postMessage`） | `ChatSimView` / `ChatIframeTabPane` 向嵌入页签发送 `chat-init` 并接收 `chat-ready`、`chat-close-request` 及确认报告回执 | 否（对接 `RA-007` 既有协议） | `FR-010` | 严格校验同源 `origin` 与 `event.source`；共享轻量 `BrandMark.vue` |

### 8.1 出站网关与模型接口契约摘要（涉及时填写）

> 本需求不直接连接外部统一网关或大模型服务（相关协议调用由后端 Spec 004 / Spec 003 承担，前端仅通过 Spec 005 `/api/v1/apis/{name}/test-call` 与 `/api/v1/templates/{tid}/dryrun/stream` 间接触发并渲染回执）。

### 8.2 三类独立交付物涉及情况

| 独立文档 | 涉及情况 | 判断依据与范围摘要 | 确认来源/日期及关联需求 |
| --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 本需求为纯前端消费端，完整前后端 API 契约已归档于 `docs/frontend-api-handoff.md` | 归档重构基线确认（2026-11-16）；`FR-002`~`FR-010` |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 本需求不修改 `src/report_agent/seed/` 业务资源或 Java 迁移脚本 | 归档重构基线确认（2026-11-16）；`FR-001`~`FR-010` |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 前端编译产物直接由既定 `FRONTEND_DIST` 静态托管并遵循 `base: './'`，无新增环境变量或容器变更 | 归档重构基线确认（2026-11-16）；`FR-001`、`FR-010` |

---

## 9. 边界与约束 【补充】

### 9.1 范围边界

**本次需求包含（In Scope）：**

- `frontend/` 多入口工程骨架（`index.html`、`vite.config.ts`、`package.json`、`tsconfig.app.json`、`styles.css`、`terms.ts`、`router/index.ts`）与 `F2` 品牌图标资产（`public/favicon.svg`、`components/BrandMark.vue` 及在 `index.html`、`App.vue`、`LoginView.vue` 的接入）。
- `platformApi.ts`、Pinia 状态机（`platform.ts`、`workspaceTabs.ts`）与全套安全/解析纯函数工具（`jinjaBody.ts`、`listColumns.ts`、`reportSegments.ts`、`sanitizeHtml.ts`、`markdown.ts`、`sse.ts`、`textDiff.ts`、`timelineFormat.ts`、`clipboard.ts`）。
- 工作台主壳层及全部 10 个视图与对应组件：`LoginView`、`TemplatesListView`、`TemplateWorkbenchView`（含四分区子组件）、`SkillsView`、`ApisView`（含 `ApiVisualEditor`）、`RunsView`（含 `AgentTimeline`、`FieldEvidenceTable`、`EvidenceSourceInspector`、`ReportPreviewContent`）、`RegressionView`（含 `GlobalDrawers`）、`ReleasesView`、`SettingsView`、`ChatSimView`（宿主集成部分）。

**本次需求不包含（Out of Scope）：**

- `frontend/embed.html` 与 `frontend/src/embed/` 内部嵌入式聊天窗口 UI 与会话流协议实现（归属 `RA-007` `specs/007-embed-chat-router/`；本需求仅承担轻量共享组件 `BrandMark.vue` 零重型依赖兼容与宿主侧 `ChatIframeTabPane` 保活）。
- 后端 FastAPI 路由、鉴权逻辑、Git 存储引擎、单智能体运行时与 Java 资源迁移工具链（分别归属 `RA-001`~`RA-005`、`RA-008`）。
- 后端未提供的批量回归调度执行器（`RegressionView` 已明确标注批量执行入口为 Phase 2 预留扩展）。

### 9.2 技术与业务约束

- **多入口分包隔离红线**：任何供 `embed.html` 复用的公共组件（如 `BrandMark.vue`、`timelineFormat.ts`、`sse.ts`）严禁导入 `element-plus` 或 `codemirror`。
- **相对基址兼容**：必须保持 `base: './'`，禁止在模板资源或图片引用中使用绝对根路径 `/` 破坏 `/agent/` 反代部署。
- **术语单一来源**：主导航、页签与版本发布资源类型名须统一引自 `frontend/src/constants/terms.ts`，禁止散落硬编码旧术语；`⌘K` 搜索兼容保留旧词检索。

---

## 10. 异常场景与边界情况 【核心】

| 编号 | 场景描述 | 触发条件 | 预期处理方式 | 是否阻断主流程 | 优先级 | 关联需求 |
| --- | --- | --- | --- | --- | --- | --- |
| `EX-001` | 全角插值、Jinja 保留关键字与局部变量误建字段 | 编辑器输入全角 `｛｛`，或正文出现 `RESERVED_JINJA_IDENTIFIERS` 及 `for`/`set` 局部绑定名 | 兼容 `｛｛` 自动触发候选补全；`WorkbenchLeftExplorer` 不生成未定义快速建字段胶囊；`handleApplyField` 拒绝与保留关键字冲突的字段名 | 否（智能引导/精准拦截） | 高 | `FR-004`、`FR-005`、`FR-006` |
| `EX-002` | 同值多字段歧义与合法 0 行列表区分 | 报告多个不同变量渲染结果文本相同，或列表字段 `status="found", value=[]` | `buildReportSegments` 优先用 AST 结构对齐绑定准确字段 Key；合法 0 行列表中性展示 `无记录（0 行）` 而不误标红 `not_found` | 否（精准消歧展示） | 高 | `FR-008` |
| `EX-003` | SSE 流主动取消与大对象内存卡顿 | 用户在试运行期间切换模板、关闭调试抽屉或加载千行结果轨迹 | `dryRunAbortController.abort()` 中断流并静默吞掉 `AbortError`；`stabilizeRunDetail` 应用 `markRaw` 消除深层 Proxy 卡顿 | 否（平滑中止/防卡顿） | 高 | `FR-002`、`FR-007` |
| `EX-004` | 多人并发修改触发 `409` 或脏页签误关 | 保存草稿返回 `409 DRAFT_CONFLICT`，或存在未保存正文/设置时点击关闭页签/切路由 | 弹出冲突对比弹窗提供查看差异/刷新/强制覆盖；`before-leave` 与 `confirmDiscardIfDirty` 阻断切换并支持挽救或放弃 | 否（引导恢复/防丢） | 高 | `FR-006`、`FR-010` |
| `EX-005` | 非安全上下文剪贴板权限拒绝与外源 XSS | 在内网 HTTP 环境或嵌套 iframe 点击复制，或 Markdown/HTML 含恶意脚本与 `javascript:` 链接 | `copyToClipboard` 捕获异常降级隐藏文本域选中复制；`sanitizeHtml`（`DOMParser` 白名单）剥离危险元素、事件与伪协议 | 否（安全降级/净化） | 中 | `FR-003` |
| `EX-006` | 同页挂载多个 `BrandMark` 时 SVG 渐变 ID 冲突 | `App.vue`、`LoginView.vue` 或后续扩展视图同页出现多个品牌标志 | `BrandMark.vue` 使用 Vue `useId()` 为每个组件实例生成唯一 `ra-f2-grad-<id>`，彻底隔离渐变引用 | 否（组件内封装隔离） | 中 | `FR-001`、`FR-010` |

---

## 11. 待确认事项 【核心】

> 本需求为已交付归档功能重构，所有架构取舍与交付边界已闭环关闭，仅保留一项已登记的第二阶段演进计划供追溯。

| 编号 | 问题描述 | 影响范围 | 责任方 | 期望确认日期 | 状态 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `Q-001` | 回归测试视图（`RegressionView`）批量全量回归调度接口何时排期落地 | `FR-009`、`RegressionView.vue` | 平台产品与后端团队 | 2026-11-12 | 已关闭 | 当前页面仅展示真实版本差异与单条用例验证入口，界面与注释已明确标识批量回归为 Phase 2 扩展，不阻塞本期验收 |
| `Q-002` | `embed.html` 与主工作台共用 `BrandMark.vue` 是否会破坏独立构建分包隔离 | `FR-001`、`vite.config.ts` | 前端架构团队 | 2026-11-16 | 已关闭 | `BrandMark.vue` 仅依赖 `vue` 原生 `useId()`，生产构建实测已将独立小组件切出且 `embed.html` 零混入 `element-plus` 与 `codemirror` |

---

## 附录：原始需求描述 【补充】

```text
智能申告报告填写与资源治理平台（report-agent）全栈研发工作拆分（子规格 006/008，33.0 人天）：
负责资源治理工作台前端架构（同步纳入 F2 智能光笔品牌图标资产：frontend/public/favicon.svg、frontend/src/components/BrandMark.vue 及 index.html/App.vue/LoginView.vue 接入）、四分区模板 IDE 与 CodeMirror 6 Jinja2 词法作用域编辑器、SSE 推理时间线与双向联动三页签证据溯源检查器、可视化网关契约编排与在线拨测、多页签保活与 48 项热更新配置中心。
```

---

## 变更记录（Changelog）

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | Codex | 完成 `006-vue-workbench-ide` 初始归档拆分规格编制（33.0 人天） |
| 2.0 | 2026-11-16 | AiCoding | 按改造后中文 Spec-Kit 模板与 SDD 取证规范重构，补齐全量章节、三类交付物台账、`FR-001`~`FR-010` 验收标准，并同步纳入最新落地的 `F2` 品牌图标资产与接入事实 |

---

## 增量更新说明

> 本文档按 `report-agent` 中文 Spec-Kit 模板与 SDD 取证规范生成；后续如有视图拆解、品牌资产、编辑器规则或热配置表单字段变更，须同步更新对应章节与 `变更记录` 并联动刷新 `plan.md` 与 `tasks.md`。
