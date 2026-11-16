# 设计文档（Feature Design Spec）：Vue 3 可视化资源治理工作台、四分区模板 IDE 与证据溯源前端

<!-- #Created By AiCoding(codex) -->
<!-- SPECKIT_PLAN_LAYOUT: inline-v1 -->

> **Spec Kit 使用约定**：本文件采用**单文件内联布局（inline-v1）**，研究决策、领域与存储模型、内部接口契约及验证指南全部内联维护在本文件四个锚点章节中，不另建 `research.md`、`data-model.md`、`contracts/` 或 `quickstart.md`。本归档拆分仅生成标准 SDD 三件套，三类外部独立交付物均在 `1.8` 节记录不涉及依据；全文严格对照 `frontend/` 源码、构建产物与 `vue-tsc` 实测结果编写。

---

**分支**：`[006-vue-workbench-ide]` | **日期**：2026-11-16 | **规格**：`./spec.md`

**输入**：`/specs/006-vue-workbench-ide/spec.md`

## 基本信息

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-006` |
| 需求名称 | Vue 3 可视化资源治理工作台、四分区模板 IDE 与证据溯源前端 |
| 对应需求文档 | `./spec.md` |
| 对应任务清单 | `./tasks.md` |
| 设计文档版本 | `2.0` |
| 设计人 | AiCoding |
| 核算工作量 | `33.0 人天`（7 个实施切片合计 `33.0 人天`） |
| 状态 | 已交付归档 |

---

## 1. 设计目标与范围 【核心】

### 1.1 设计目标（What / Why）

- **PLAN-GOAL-1**：基于 Vue 3 + Vite 6 构建具备 `base: './'` 子路径反代适应力、`8` 分包按需懒加载、亮暗双主题、统一通俗术语（`terms.ts`）与 `F2` 智能光笔写单品牌视觉系统（`public/favicon.svg` + `index.html` + `BrandMark.vue`）的前端架构（对应 `SC-001`、`SC-005`）。
- **PLAN-GOAL-2**：实现四分区可拖拽缩放模板 IDE，依托自研 Jinja2 词法作用域引擎（`analyzeJinjaBody` / `renameJinjaBodyVariable`）与 `CodeMirror 6` 装饰器消除变量失配与注释误替换，并提供 `350ms` 防抖无副作用内存预览与 `409` 乐观锁解决流（对应 `SC-002`）。
- **PLAN-GOAL-3**：交付消费 `/dryrun/stream` 的轮次折叠推理时间线（突出 `report_rejected`/`report_degraded` 联动）、Jinja2 AST 优先消歧报告分段（`alignReportWithTemplate`）与 `api`/`doc`/`input` 三页签双向高亮检查器，配合 `markRaw` 保障海量轨迹流畅度（对应 `SC-003`）。
- **PLAN-GOAL-4**：交付保留注释与扩展键的双协议 `ApiVisualEditor`（支持 `${$now}`、五模式样例反推与未落盘 `test-call` 回填）、锁首页拖拽与 `<KeepAlive :max="12">` 多页签壳层、版本紧急切换及 `48` 项配置热更新设置中心（对应 `SC-004`、`SC-005`）。

### 1.2 设计范围（Scope）

**包含：**

- 工程与构建骨架：`frontend/index.html`、`frontend/public/favicon.svg`、`frontend/package.json`、`frontend/tsconfig.app.json`、`frontend/vite.config.ts`、`frontend/src/main.ts`、`frontend/src/router/index.ts`、`frontend/src/assets/styles.css`、`frontend/src/constants/terms.ts`。
- 通信、状态与纯函数基座：`frontend/src/types/platform.ts`、`frontend/src/api/platformApi.ts`、`frontend/src/stores/{platform,workspaceTabs}.ts`、`frontend/src/utils/{jinjaBody,listColumns,reportSegments,sanitizeHtml,markdown,sse,textDiff,timelineFormat,clipboard}.ts`。
- 全局组件与全部 10 个视图：`frontend/src/App.vue`、`frontend/src/components/{BrandMark,CodeMirrorEditor,ApiVisualEditor,AgentTimeline,FieldEvidenceTable,EvidenceSourceInspector,ReportPreviewContent,WorkspaceTabsBar,ChatIframeTabPane,ChatSimTemplatePicker,GlobalDrawers,GlobalModals,StatusTag,SvgIcon}.vue`、`frontend/src/components/workbench/*` 及 `frontend/src/views/*`。

**不包含：**

- `frontend/embed.html` 与 `frontend/src/embed/` 专属嵌入式聊天窗口界面与路由交互（归属 `RA-007` `specs/007-embed-chat-router/`；本需求仅负责多入口分包隔离与共享无重型依赖组件 `BrandMark.vue`）。
- 后端 `/api/v1/*` 接口实现与存储/运行时引擎（归属 `RA-001`~`RA-005`、`RA-008`）。

<a id="plan-research"></a>

### 1.3 研究与关键决策（Decision Log）

| ID | 决策点 | 备选方案 | 最终选择 | 依据与取舍理由 | 影响范围 |
| --- | --- | --- | --- | --- | --- |
| `D1` | `F2` 品牌图标与多入口加载策略 | 外部 SVG 文件引用 + 图标字体库 | `public/favicon.svg` + `index.html` 内联 SVG Data URI `<link rel="icon">` + 零重型依赖 `BrandMark.vue`（`useId()` 隔离渐变 ID） | 内联 Data URI 在子路径反代和离线环境零额外请求；`BrandMark.vue` 仅依赖 `vue` `useId()`，可安全复用至 `App.vue`、`LoginView.vue` 及 `embed.html` 而不污染嵌入页独立分包 | `index.html`、`public/favicon.svg`、`BrandMark.vue`、`App.vue`、`LoginView.vue` |
| `D2` | Jinja2 编辑器高亮与重命名策略 | 使用通用 Jinja 语法包 + 正则全局字符串替换 | 自研纯函数 `analyzeJinjaBody` + `renameJinjaBodyVariable` + CodeMirror `jinjaHighlightPlugin` | 通用高亮不识别动态字段列表和 `for`/`set` 局部作用域，极易误报未定义字段；自研词法器精准跳过 `{# ... #}`、字面量、过滤器与 `.attr` | `utils/jinjaBody.ts`、`WorkbenchTemplateStage.vue`、`WorkbenchRightInspector.vue` |
| `D3` | 报告与证据双向定位同值消歧 | 仅按渲染文本子串查找首处匹配 | 优先 `alignReportWithTemplate`（基于模板 AST 控制流与插值顺序对齐），失败时降级 `fallbackSegmentize` 最长串匹配 | 当两个不同字段渲染出相同文本时，字符串检索必定错位；AST 对齐绑定精确字段 Key，并在 `ReportPreviewContent` 与三页签检查器间零歧义联动 | `utils/reportSegments.ts`、`ReportPreviewContent.vue`、`EvidenceSourceInspector.vue` |
| `D4` | 长轨迹渲染防卡顿与快速切换并发竞争 | 保持全量响应式深代理 + 无序号过滤 | `stabilizeRunDetail` 对大数组执行 `markRaw` + Store 递增请求序号守卫 + `readSseStream` 绑定 `AbortController` | 剥离 Vue 3 对千行工具记录与时间线事件的深层 Proxy 追踪开销；请求序号守卫避免快切模板/运行详情时慢请求覆盖新界面 | `stores/platform.ts`、`utils/sse.ts`、`WorkbenchDebugPanel.vue` |
| `D5` | 双协议网关 YAML 注释保真与多页签保活 | 每次保存直接重新生成全量 YAML / 切换路由销毁组件 | `yaml` 库保留前置注释与扩展键局部回写 + `BUILTIN_PLACEHOLDERS` 隔离 `${$now}`；`WorkspaceTabsBar`（`SortableJS` 锁首页）+ `<KeepAlive :max="12">` + `v-show` iframe | 保护工程师手工编写注释和高级扩展配置不被可视化编辑覆盖；`KeepAlive` 与 `v-show` 防止高频跨模块切换丢失未保存草稿和重建聊天上下文 | `ApiVisualEditor.vue`、`App.vue`、`WorkspaceTabsBar.vue`、`stores/workspaceTabs.ts` |

---

### 1.4 技术背景与项目结构

**语言/版本**：TypeScript `~5.7.2`（`tsconfig.app.json` 开启 `strict: true`，目标 `ES2022`）+ Vue `^3.5.13` 单文件组件

**主要依赖**：Vite `^6.0.5`、Pinia `^2.3.1`、Vue Router `^4.5.0`、Element Plus `^2.9.1`（`zhCn` 中文包）、CodeMirror `^6.0.1`、Marked `^15.0.3`、Diff `^7.0.0`、YAML `^2.6.1`、SortableJS `^1.15.6`、Lucide-Vue-Next `^0.468.0`

**存储**：`localStorage['report-agent-theme']`（亮暗主题）、`sessionStorage['agent-python-token']`（Bearer 令牌）与 Pinia 内存状态机；全部业务数据持久化于后端 `/api/v1/*`

**测试**：`npx vue-tsc --noEmit -p tsconfig.app.json` + `npm run build`（验证 `8` chunk 输出与 `embed.html` 依赖隔离）+ 代理联调验收（端口 `5175` 代理 `/api` 至 `http://127.0.0.1:8000`）

**目标平台**：现代桌面浏览器（由 FastAPI `FRONTEND_DIST` 静态托管或 Nginx 子路径反向代理提供服务）

**项目类型**：Vite 多入口 SPA 资源治理工作台前端应用（主工作台 `index.html` 与关联组件/视图）

**约束与规模/范围**：严格保持 `embed` 入口剥离重型依赖；覆盖 `10` 个懒加载路由视图、`18` 个工作台与全局组件、`9` 个纯函数工具模块及 `2` 个 Pinia Store，按 `33.0 人天` 归档核算

**源代码结构（真实目录落点）**：

```text
frontend/
├── index.html                                 # 工作台 SPA 入口（data-theme="light" + 内联 F2 SVG Data URI icon）
├── package.json                               # Vue 3.5.13 / Pinia 2.3.1 / CodeMirror 6 / Element Plus 2.9.1 / Vite 6.0.5
├── tsconfig.app.json                          # 严格 TypeScript ES2022 配置与 @/* 路径映射
├── vite.config.ts                             # base: './'、/api 代理、index+embed 双入口与 8 manualChunks 拆包
├── public/
│   └── favicon.svg                            # F2 智能光笔写单 64x64 静态 SVG 品牌图标资产
└── src/
    ├── main.ts                                # Element Plus zhCn、暗色样式引入、Pinia 与 Router 挂载
    ├── App.vue                                # 三分组导航与 BrandMark(:size="26")、50px 顶栏、⌘K、⌘S、KeepAlive(12) 与全屏聊天保活
    ├── assets/styles.css                      # [data-theme="light" / "dark"] 双主题令牌与全局规范样式
    ├── constants/terms.ts                     # NAV_LABELS 与 NAV_GROUP_LABELS 通俗统一术语常量
    ├── router/index.ts                        # 10 个动态懒加载 Hash 路由表
    ├── types/platform.ts                      # 前后端完整 TS 契约（含 48 字段 RuntimeConfig 与 RunDetail）
    ├── api/platformApi.ts                     # REST/SSE 客户端、ApiError 包装解包与 auth:unauthorized 事件广播
    ├── stores/
    │   ├── platform.ts                        # 全局资源状态机、stabilizeRunDetail(markRaw)、序号防竞态、409 冲突态
    │   └── workspaceTabs.ts                   # Sortable 锁首页页签、before-leave 脏草稿拦截、聊天页签与重置逻辑
    ├── utils/
    │   ├── jinjaBody.ts                       # analyzeJinjaBody（for/set 作用域与诊断）、renameJinjaBodyVariable、RESERVED_JINJA_IDENTIFIERS
    │   ├── listColumns.ts                     # formatListColumns / parseListColumns 管道列解析
    │   ├── reportSegments.ts                  # alignReportWithTemplate AST 对齐与 fallbackSegmentize 消歧
    │   ├── sanitizeHtml.ts                    # escapeHtml、sanitizeUrl、DOMParser 白名单 sanitizeHtml
    │   ├── markdown.ts                        # 32 条 LRU 缓存与 XSS 净化 renderSafeMarkdown
    │   ├── sse.ts                             # readSseStream / parseSseJson 与 AbortError 安全取消
    │   ├── textDiff.ts                        # buildFullDiffRows / buildDiffRows 行级对比算法
    │   ├── timelineFormat.ts                  # groupEventsByRound、describeToolEvent（12 工具）、TIMELINE_OUTCOME_TYPES
    │   └── clipboard.ts                       # navigator.clipboard 异常回退 copyToClipboard
    ├── views/
    │   ├── LoginView.vue                      # 政企认证门户登录页（SVG 工程网格 + 主题同步 + BrandMark :size="38"）
    │   ├── TemplatesListView.vue              # 模板总览表、状态筛选与关联技能 .ref-popover-list
    │   ├── TemplateWorkbenchView.vue          # 四分区可拖拽模板 IDE 主视图与底部 24px ide-statusbar
    │   ├── SkillsView.vue                     # 纯文本技能编辑、Markdown 安全预览与双模式回滚
    │   ├── ApisView.vue                       # 双协议网关接口库、未落盘 test-call 拨测与列回填视图
    │   ├── RunsView.vue                       # 多维运行台账检索与三页签证据审计排查视图
    │   ├── RegressionView.vue                 # 模板范围回归测试 KPI 概览与差异表（标注批量为二期扩展）
    │   ├── ReleasesView.vue                   # 全局版本时间线、跨版本 Diff 跳转与紧急切换视图
    │   ├── SettingsView.vue                   # 系统提示词时间线、X-API-Key 轮换与 48 项热更新/局部重置中心
    │   └── ChatSimView.vue                    # 嵌入式聊天窗口模拟联调宿主控制台
    └── components/
        ├── BrandMark.vue                      # F2 智能光笔写单 SVG 组件（零重型依赖 + useId 隔离渐变 ID）
        ├── CodeMirrorEditor.vue               # CodeMirror 6 受控包装组件
        ├── ApiVisualEditor.vue                # 双协议 4 页签可视化 + YAML 分屏同步编排器
        ├── AgentTimeline.vue                  # 轮次折叠推理时间线与退回/降级联动跳转组件
        ├── FieldEvidenceTable.vue             # 字段提取值与证据溯源明细表
        ├── EvidenceSourceInspector.vue        # 网关 resultId / 单据 Lxxx / 工单入参三页签高亮检查器
        ├── ReportPreviewContent.vue           # 可交互报告正文渲染与 Teleport KEY 悬浮提示
        ├── WorkspaceTabsBar.vue               # 锁首页 SortableJS 多页签栏与快捷批量关闭菜单
        ├── ChatIframeTabPane.vue / ChatSimTemplatePicker.vue # 宿主嵌入式聊天 iframe 保活容器与入参选择器
        ├── GlobalDrawers.vue                  # 异步按需挂载全局抽屉（含 reg-diff-detail）
        ├── GlobalModals.vue                   # 409 冲突对比、校验与紧急回退弹窗容器
        ├── StatusTag.vue / SvgIcon.vue        # 状态徽标与图标包装组件
        └── workbench/
            ├── WorkbenchLeftExplorer.vue      # 50px 六栏活动栏、Sortable 字段拖拽、未定义快速建字段胶囊
            ├── WorkbenchTemplateStage.vue     # 四模式画布、jinjaHighlightPlugin、自动补全与 350ms 防抖预览
            ├── WorkbenchRightInspector.vue    # 双态属性/证据检查器与 handleApplyField 变量重命名联动
            └── WorkbenchDebugPanel.vue        # 入参正则检验、190px 历史记录栏、SSE 流控与全屏缩放抽屉
```

**禁止修改范围**：

- 严禁在 `frontend/src/components/BrandMark.vue` 或 `utils/sse.ts`、`utils/markdown.ts`、`utils/timelineFormat.ts` 等共享模块中引入 `element-plus` 或 `codemirror`，否则会破坏 `embed.html` 轻量分包边界。
- 本需求不修改 `frontend/src/embed/` 内部聊天实现（归属 `RA-007`）及 `src/report_agent/` 后端代码（归属 `RA-001`~`RA-005`）。

#### 文档结构（本需求）

```text
specs/006-vue-workbench-ide/
├── spec.md    # specify/clarify：需求规格、范围边界与验收标准
├── plan.md    # plan：研究决策、模型、内部契约与验证指南（inline-v1）
└── tasks.md   # tasks：可执行任务清单、测试矩阵与验收证据
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
| 原则 I：平台零业务硬编码与声明式资源隔离 | `PASS` | `PASS` | 所有表单、Jinja 高亮、报告分段与可视化 API 编辑均由服务端返回的动态字段/模板/契约元数据驱动 |
| 原则 II：单智能体规划、确定性原语与强证据防幻觉 | `PASS` | `PASS` | `AgentTimeline`、`ReportPreviewContent` 与 `EvidenceSourceInspector` 如实区分合法 `无记录（0 行）` 与 `not_found`，突出渲染退回与降级 |
| 原则 III：文件化 Git 原子发布与单进程并发安全（`workers=1`） | `PASS` | `PASS` | 全量写操作透传 `revision` 并适配 `409` 对比恢复弹窗，协同后端乐观锁与原子发布工作流 |
| 原则 IV–V：单文件内联设计、自动化测试隔离与 Mock 契约 | `PASS` | `PASS` | `inline-v1` 单文件布局；删除本地 Mock 数据，启用严格 `vue-tsc` 与 8 分包构建门禁；`markRaw` + LRU 保障渲染性能 |
| 原则 VI–VII：安全脱敏、零硬编码凭证、事件与审计留痕 | `PASS` | `PASS` | `DOMParser` 白名单 `sanitizeHtml` 防 XSS；源码零真实密钥；`SettingsView` 对三类运行密钥仅做掩码编辑与清空开关控制 |
| 原则 VIII–X：最小改动、代码规范、Wiki 同步及三类外部交付物确认 | `PASS` | `PASS` | `embed.html` 实测零混入 `element-plus` / `codemirror`；三类独立交付物明确记录不涉及；Wiki 既有组件页对齐 |

### 1.6 复杂度跟踪

| 偏离或额外复杂度 | 必要性说明 | 未采用更简方案的原因 |
| --- | --- | --- |
| 无（严格遵守项目宪章与既有约束） | 自研 `analyzeJinjaBody`、`alignReportWithTemplate` 与 `yaml` 保留注释合并序列化均聚焦 IDE 级精度与防覆盖痛点，未引入冗余外部状态库 | 通用正则/字符串替换无法避免注释、局部循环变量与同值多字段错位问题 |

### 1.7 Wiki 影响评估

- **结论**：不涉及新建或改动 `wiki/` 页面（本次归档重构仅将既有 Spec 006 三件套升级为标准中文 SDD 格式，不改写仓库代码与知识库）。
- **受影响页面**：既有架构已沉淀于 `wiki/components/workbench-frontend.md`（含统一术语表、10 视图、四分区工作台与 48 项配置交互）；顺带核对代码注意到最新落地的 `frontend/public/favicon.svg`、`frontend/src/components/BrandMark.vue` 品牌组件与 `WorkbenchLeftExplorer.vue` 六栏活动栏尚未单独在 `wiki/components/workbench-frontend.md` 列出，后续增量更新知识库时可按需补充。
- **同步项**：本次归档拆分不安排额外 `wiki/` 改动任务。

### 1.8 三类独立交付物设计检查

| 独立交付物 | 涉及情况与依据 | 设计与变更摘要 | 验证与回退设计 | 关联问题 |
| --- | --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 前端严格消费 `docs/frontend-api-handoff.md` 既有接口契约 | `vue-tsc` 类型校验 `types/platform.ts` | 无 |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 不涉及 `seed/` 生产模板或迁移规则改动 | 不涉及 | 无 |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 产物继续经既有 `FRONTEND_DIST` 托管，无新环境变量 | `npm run build` 检查 `dist/` | 无 |

---

## 2. 需求映射（Traceability） 【核心】

| 规格编号 | 类型 | 需求摘要 | 设计章节映射 | 后续任务映射 |
| --- | --- | --- | --- | --- |
| `US1` / `SC-002` | 用户故事 / 成功标准 | 四分区拖拽 IDE、6 栏活动栏、`jinjaHighlightPlugin` 作用域高亮、联动重命名、350ms 预览与 `409` 弹窗 | 第 `1.3`、`3`、`5`、`8` 章 | `T006`–`T008` |
| `US2` / `SC-003` | 用户故事 / 成功标准 | SSE 实时时间线（12 工具与退回/降级联动）、AST 消歧 `ReportPreviewContent`、三页签滚动定位及合法 0 行区分 | 第 `1.3`、`3`、`5`、`8` 章 | `T009`–`T011` |
| `US3` / `SC-004` | 用户故事 / 成功标准 | `ApiVisualEditor` 双协议 4 页签 + YAML 注释保留同步、`${$now}` 护栏、五模式反推、拨测回填与技能/回归抽屉 | 第 `3`、`5`、`8` 章 | `T012`–`T014` |
| `US4` / `SC-001`、`SC-005` | 用户故事 / 成功标准 | 统一 `F2` 品牌资产、`KeepAlive` 锁首页多页签、脏草稿拦截、双主题、紧急切换与 48 项设置中心 | 第 `1.3`、`3`、`4`、`8`、`9` 章 | `T001`–`T002`、`T005`、`T015`–`T018` |
| `FR-001` | 功能需求 | Vite 6 双入口与 8 分包、10 懒加载 Hash 路由、双主题令牌、`terms.ts` 与 `F2` 品牌图标资产及接入 | 第 `1.3`、`1.4`、`8` 章 | `T001`、`T002`、`T005`、`T015`、`T018` |
| `FR-002` | 功能需求 | `platformApi`（401 拦截）、`readSseStream`、`usePlatformStore`（`markRaw` / 序号守卫）与 `useWorkspaceTabsStore` | 第 `3`、`5`、`6` 章 | `T003`、`T004`、`T015` |
| `FR-003` | 功能需求 | `sanitizeHtml`、`renderSafeMarkdown`（32 LRU）、`textDiff`、`listColumns`、`copyToClipboard` 与基础图标组件 | 第 `1.4`、`7`、`8` 章 | `T005` |
| `FR-004` | 功能需求 | `TemplateWorkbenchView` 三分割条与 `24px` 状态栏、`WorkbenchLeftExplorer` 六栏活动栏与未定义胶囊过滤 | 第 `3`、`8` 章 | `T007` |
| `FR-005` | 功能需求 | `analyzeJinjaBody`、`CodeMirrorEditor`、`WorkbenchTemplateStage` 四模式、`{{`/`｛｛` 补全与 350ms 内存预览 | 第 `3`、`6`、`8` 章 | `T006`、`T007` |
| `FR-006` | 功能需求 | `WorkbenchRightInspector` 属性与 `list` 列编辑、`handleApplyField` 变量联动重命名与 `GlobalModals` `409` 弹窗 | 第 `3`、`6`、`8` 章 | `T006`、`T008` |
| `FR-007` | 功能需求 | `WorkbenchDebugPanel`（190px 历史/正则/全屏 `Esc`）、`AgentTimeline` 12 工具与 `report_rejected`/`degraded` 联动 | 第 `5`、`6`、`8` 章 | `T010` |
| `FR-008` | 功能需求 | `alignReportWithTemplate` 消歧、`ReportPreviewContent`（`Teleport`）、`EvidenceSourceInspector` 三页签定位与 `RunsView` | 第 `3`、`6`、`8` 章 | `T009`、`T011` |
| `FR-009` | 功能需求 | `ApiVisualEditor`、`ApisView`（`syncColumnsFromTestResult`）、`SkillsView`、`RegressionView` 与 `reg-diff-detail` 抽屉 | 第 `3`、`8` 章 | `T012`–`T014` |
| `FR-010` | 功能需求 | `LoginView`、`App.vue` 壳层（`KeepAlive(12)`、`⌘K`/`⌘S`）、`WorkspaceTabsBar`、`ReleasesView` 与 `SettingsView` 48 项热配置 | 第 `4`、`8`、`9` 章 | `T015`–`T016` |
| `NFR-001`~`NFR-005` | 非功能需求 | 零业务硬编码、强证据中性空列表区分、`markRaw`/LRU 性能、XSS 防护及严格 `vue-tsc`/8 分包隔离 | 第 `1.5`、`7`、`11` 章 | `T001`–`T018` |
| `EX-001`~`EX-006` | 异常边界 | 全角与保留字防误建、同值与 0 行歧义、SSE 取消防卡顿、`409` 与脏页签拦截、剪贴板/XSS 降级、SVG ID 隔离 | 第 `6.2`、`7`、`10` 章 | `T003`–`T015` |

---

<a id="plan-data-model"></a>

## 3. 核心领域模型（Domain Model） 【核心】

### 3.1 领域对象清单

| 对象 / 类 | 所在文件 | 职责与核心属性 | 关键不变量（Invariant） |
| --- | --- | --- | --- |
| `BrandMark`（`F2` 品牌图标组件） | `frontend/src/components/BrandMark.vue` | 零外部重型依赖渲染智能光笔写单矢量标志，接收 `size?: number`（默认 `28`） | 使用 `useId()` 生成唯一渐变 ID `ra-f2-grad-${useId()}`，保障同页多实例及 `embed.html` 复用零冲突、零重包污染 |
| `JinjaBodyAnalysis` | `frontend/src/utils/jinjaBody.ts` | 封装词法扫描输出：`tags`、`fieldOccurrences`、`usageCounts` 与作用域变量集合 | 识别 `{% for %}`/`{% set %}` 局部变量与 `RESERVED_JINJA_IDENTIFIERS`，禁止将局部变量误标为未定义全局字段 |
| `ReportSegment` & `EvidenceFocus` | `frontend/src/utils/reportSegments.ts` | 报告切片（`plain`/`found`/`missing`/`placeholder`/`list`）及绑定字段 Key 与三页签证据焦点 | 优先用 Jinja2 AST 结构对齐 `alignReportWithTemplate` 消除同值歧义；合法 `found` 空列表独立标示 `无记录（0 行）` |
| `WorkspaceTab`（`RouteWorkspaceTab` / `ChatWorkspaceTab`） | `frontend/src/stores/workspaceTabs.ts` | 顶部多页签工作区模型，承载 `key`、`navKey`、`closable`、`orderId`、`keepAliveName` | 首页 `#tab-templates` 永久锁定第 0 位且不可关闭；关闭或切走脏草稿前须经 `confirmDiscardIfDirty` 二次确认 |
| `VisualApiDraftModel` | `frontend/src/components/ApiVisualEditor.vue` | 4 页签可视化编辑中间模型，覆盖连接器类型、入参、`operation_in`、`noData`/`success` 与抽取列 | `BUILTIN_PLACEHOLDERS` 限制 `$` 开头保留参数（如 `${$now}`）禁止手写为入参；保留原 YAML 注释与未知键 |
| `RuntimeFormModel` | `frontend/src/views/SettingsView.vue` | 映射后端 `48` 项热配置表单 + 3 项安全清除开关（`clearLlmApiKey`/`clearGatewayAppId`/`clearGatewayAccessToken`） | `handleResetDefaultParams` 仅重置参数值，保留 `gatewayUrl`、`llmBaseUrl`、`llmModel` 与已填密钥；前置校验大小关系 |

### 3.2 状态机（如适用）

```text
# 1. 工作区多页签与脏草稿拦截流转
当前路由页签 (dirty = false) --(关闭或切页签)--> 直接激活目标页签 / 卸载或隐藏
当前路由页签 (dirty = true)  --(before-leave / closeTab)--> confirmDiscardIfDirty()
    ├── 选择「保存并继续」--> 提交保存接口成功后切换
    ├── 选择「放弃修改」  --> 回滚局部未保存状态并允许切换
    └── 选择「取消」      --> 返回 false 阻止 ElTabs 切换，保留当前编辑上下文

# 2. 模板舞台编辑与内存实时预览
正文/临时字段变更 --(触发 scheduleStaticPreview(350))--> 防抖 350ms 计时
    ├── 期间再次输入 --> 重置计时器
    └── 到期触发     --> POST /templates/{tid}/render-preview (内存态渲染，不改草稿 revision)
```

---

## 4. 数据与存储设计（本需求范围） 【核心】

### 4.1 存储与缓存对象概览

| 对象/路径 | 变更类型 | 数据格式与字段要点 | 并发/清理/恢复策略 | 关联需求 |
| --- | --- | --- | --- | --- |
| `usePlatformStore` 内存状态 | 内存读写 | 资源清单、当前详情、草稿状态、运行详情 `RunDetail` 与 `409` 冲突状态 | `stabilizeRunDetail` 对大数组执行 `markRaw`；递增请求序号守卫丢弃过期响应 | `FR-002`、`FR-006`、`FR-007` |
| `useWorkspaceTabsStore` 内存状态 | 内存读写 | 页签顺序数组、活跃页签 Key、动态聊天页签列表与确认报告回执 | `SortableJS` 拖拽前还原 DOM 再修改数组防 VNode 错位；登出执行 `resetAll()` 清空动态页签 | `FR-002`、`FR-010` |
| `markdown.ts` LRU 缓存 | 内存只读缓存 | `Map<string, string>` 映射 Markdown 文本 → 净化后 HTML | 容量上限 `32` 条，命中移至队尾，超限驱逐最久未使用条目 | `FR-003`、`FR-009` |
| `localStorage['report-agent-theme']` | 本地持久化 | 字符串 `"light"` / `"dark"` | `LoginView.vue` 通过 `MutationObserver` 同步 `documentElement` 与本地状态；登出不清除 | `FR-001`、`FR-010` |
| `sessionStorage['agent-python-token']` | 会话级本地存储 | 登录成功签发的 Bearer Token | `auth:unauthorized` 或主动登出立即移除，防残留过期令牌 | `FR-002` |

---

<a id="plan-contracts"></a>

## 5. 接口与契约设计（API / Tools / Events） 【核心】

> 前端不对外暴露独立后端接口，本节记录前端封装消费 `RA-005` 接口、SSE 流协议、内部组件契约及宿主 `postMessage` 协同协议。

### 5.1 接口与契约清单

| 契约编号 | 类型 | 名称 / Path | 方向 | 关键入参 / 载荷 | 关键出参 / 响应 / 事件 | 鉴权与幂等 | 关联需求 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `FE-API-1` | HTTP Client | `platformApi.*` (`frontend/src/api/platformApi.ts`) | 前端 → `/api/v1/*` | 携带 Cookie / `Bearer` 头及结构化载荷 | 统一解析 `{code, message}` 抛出 `ApiError`，401 派发 `auth:unauthorized` | 同源 Cookie 或 Bearer；错误统一透传 | `FR-002` |
| `FE-API-2` | SSE Stream | `readSseStream(resp, onEvent, signal)` | 后端 SSE → 前端 | `Response`、`AbortSignal` | 解析 `event: event` / `final` / `error` 回调，`AbortError` 安全静默中止 | 单次绑定 `dryRunAbortController` | `FR-002`、`FR-007` |
| `FE-COMP-1` | Vue 组件 | `BrandMark.vue` | `App`/`LoginView` → 组件 | `size?: number`（默认 `28`） | 无障碍 `aria-hidden="true"` F2 矢量 SVG（`useId` 梯度隔离） | 零重型依赖，支持同页多实例与 `embed` 复用 | `FR-001`、`FR-010` |
| `FE-COMP-2` | Vue 组件 | `ReportPreviewContent` ↔ `EvidenceSourceInspector` | 组件双向事件 | `activeFieldName`、`fields`、`bodyCandidates`、`apiResults`、`documentLines` | `select` 事件触发三页签自动切换并滚动居中高亮 `.evidence-highlight-mark` | 纯响应式状态驱动 | `FR-008` |
| `FE-COMP-3` | Vue 组件 | `ApiVisualEditor.vue` | `ApisView` ↔ 编辑器 | `yamlText`、拨测返回 `records`/`columns` | 双向保留注释 YAML 同步、脱敏信封预览、暴露 `syncColumnsFromTestResult()` | 拦截 `$` 手动入参声明 | `FR-009` |
| `FE-HOST-1` | 宿主协议 | `ChatIframeTabPane` / `ChatSimView` ↔ `/embed.html` | 父页面 ↔ iframe `postMessage` | `chat-init`（`userId`、`orderId`、`inputs`、`document`、`apiKey`、`target`） | 接收 `chat-ready`、`chat-close-request` 及确认报告回执 | 仅同源 `origin` 与 `event.source` 放行 | `FR-010` |

### 5.2 关键契约说明与错误语义

- **`ApiError` 与 `409 DRAFT_CONFLICT`**：`platformApi` 兼容 FastAPI 默认 `{detail}` 与自定义 `{code, message, current, issues, errors}` 格式；当写草稿接口返回 `409 DRAFT_CONFLICT` 时，`usePlatformStore` 捕获异常并将服务端返回的 `current` 元数据挂载至冲突状态，自动弹出 `GlobalModals` 供用户决定对比、重载或强制覆盖。
- **`detail_view` 与 `report_rejected`/`report_degraded` 展示语义**：`AgentTimeline` 通过 `TIMELINE_OUTCOME_TYPES` 映射节点视觉样式，`.tl-outcome-err`（红色）表示被 `EvidenceChecker` 退回，`.tl-outcome-warn`（琥珀色）表示字段级联降级；点击报错字段名直接聚焦对应 `EvidenceSourceInspector` 数据源。

---

## 6. 业务流程设计（可直接编码） 【核心】

### 6.1 核心执行流程

```text
# 流程 A：模板 IDE 联动编辑、350ms 防抖预览与字段改名
1. WorkbenchLeftExplorer 触发字段选择，同步更新 store.selectedFieldName 与 WorkbenchTemplateStage 高亮芯片 (.is-ide-selected)。
2. 用户编辑正文时，analyzeJinjaBody 实时重算 tags 与作用域局部变量，CodeMirror 装饰插件刷新芯片，并调用 scheduleStaticPreview(350)。
3. 用户在 WorkbenchRightInspector 修改字段名点击 handleApplyField：
   a. 校验非保留字 RESERVED_JINJA_IDENTIFIERS；
   b. 调用 renameJinjaBodyVariable 同步替换正文合法引用（跳过注释/字面量/过滤器/.attr）；
   c. 调用 PUT /api/v1/templates/{tid}/fields/{name}（附 originalName 与 revision）；若 409 则唤醒 GlobalModals 冲突处理。

# 流程 B：SSE 流式试运行与 AST 双向证据溯源
1. WorkbenchDebugPanel 对必填及带 pattern 的入参执行 .trim() + 整串正则校验后，创建 dryRunAbortController 发起 POST /dryrun/stream。
2. readSseStream 实时派发轮次与工具过程事件至 AgentTimeline（经 markRaw 降载存储）；结束帧写入完整 RunDetail。
3. ReportPreviewContent 调用 buildReportSegments（优先 alignReportWithTemplate，异常回退 fallbackSegmentize）渲染消歧切片。
4. 用户点击报告值、FieldEvidenceTable 行或时间线退回字段名 -> resolveEvidenceInspectorTab 自动切至 api/doc/input -> scrollIntoView 居中高亮目标元素。
```

### 6.2 并发控制与异常降级策略

| 异常/并发场景 | 检测时机 | 处理策略 | 是否中断主流程 | 可观测性输出 |
| --- | --- | --- | --- | --- |
| 快速连续切换模板/修订/运行详情 | 异步请求发起与返回时 | 递增并发请求计数器，响应返回时比对序号，过期响应直接丢弃不覆写 Store | 否（自动对齐最新操作） | 无错位界面闪烁 |
| 在试运行 SSE 期间切换模板或关闭面板 | 切换前置钩子或用户点击停止 | 调用 `dryRunAbortController.abort()` 中断流，在 `readSseStream` 中取消 `reader` 并吞掉 `AbortError` | 否（干净停止流） | 状态复位为可再次试运行 |
| 模板未保存/未发布致 AST 对齐异常 | `buildReportSegments` 分段计算时 | `alignReportWithTemplate` 返回空或失配时自动平滑回退 `fallbackSegmentize` 最长串匹配 | 否（仍可交互高亮） | 切片高亮正常工作 |
| 非 HTTPS/iframe 受限环境复制失败 | 点击复制 API Key/报文时 | `copyToClipboard` 捕获 `navigator.clipboard` 异常后创建隐藏 `<textarea>` 执行选中复制降级 | 否（复制仍成功） | 返回复制状态触发界面提示 |

---

## 7. 权限与安全控制（本需求范围） 【补充】

| 控制点 | 适用角色/调用方 | 校验机制与边界 |
| --- | --- | --- |
| 登录态路由守卫与自动登出 | 全部受保护工作台视图 | 启动及切换时调用 `GET /api/v1/auth/me` 验证会话；`platformApi` 收到 `401` 广播 `auth:unauthorized`，跳转 `/login` 并执行 `tabsStore.resetAll()` |
| XSS 富文本与 URL 净化 | 技能正文、报告文本与辅助富文本展示 | `sanitizeHtml.ts` 使用 `DOMParser` 剥离危险标签、`on*` 属性及 `javascript:`/`vbscript:` 等伪协议；`renderSafeMarkdown` 统一套用净化 |
| 运行期敏感密钥表单隔离 | `SettingsView` 系统设置管理员 | `gatewayAppId`、`gatewayAccessToken`、`llmApiKey` 仅显示脱敏掩码或提供独立 `clear*` 开关；`handleResetDefaultParams` 严格保护已填 URL 与密钥不被重置 |
| 宿主 iframe `postMessage` 校验 | `ChatSimView` / `ChatIframeTabPane` | 仅向同源 `/embed.html` 下发并校验 `event.origin === window.location.origin` 与匹配 `event.source` |

---

## 8. 前端 / 交互设计（如适用） 【补充】

| 视图/组件 | 职责 | 关键状态与交互 | 关联接口 |
| --- | --- | --- | --- |
| `favicon.svg` + `index.html` + `BrandMark.vue` | 统一 `F2` 智能光笔写单品牌标识 | 浏览器图标使用 `public/favicon.svg` 与 `index.html` 内联 SVG Data URI；`BrandMark.vue` 通过 `useId()` 隔离渐变 ID，零重型依赖，供 `App.vue`(26px)、`LoginView.vue`(38px) 及 `embed.html` 共用 | 静态资源 / 组件内聚 |
| `LoginView.vue` | 政企门户登录页 | 纯内联 SVG 工程制图底纹、`MutationObserver` 联动亮暗主题、`0/2`→`2/2` 输入就绪条、`BrandMark(:size="38")` | `POST /api/v1/auth/login` |
| `App.vue` + `WorkspaceTabsBar.vue` | 全局导航壳层与多页签工作区 | 可折叠 3 组侧栏 + `BrandMark(:size="26")`、50px 顶栏（`⌘K` 检索兼容新旧术语、`⌘S` 全局保存）、锁首页 `SortableJS` 页签、`<KeepAlive :max="12">`、`v-show` 全屏聊天容器与脏草稿 `before-leave` 拦截 | `GET /auth/me`、各资源保存接口 |
| `TemplateWorkbenchView.vue` + `workbench/*` | 四分区可拖拽模板 IDE | 三组分割条、50px 六栏活动栏（含模板「信息」直接编辑）、`jinjaHighlightPlugin`、350ms 防抖预览、24px `ide-statusbar`、190px 调试历史栏与 SSE 抽屉 | `/templates/*`、`/render-preview`、`/dryrun/stream` |
| `ReportPreviewContent.vue` + `EvidenceSourceInspector.vue` + `AgentTimeline.vue` | 消歧报告预览、时间线与三页签溯源 | AST 结构消歧、`Teleport` 悬浮提示、三页签滚动定位（`.evidence-highlight-mark`/`.row-highlight`）、12 工具轮次卡与 `report_rejected`/`degraded` 点击跳转、区分 `无记录（0 行）` | `/runs/*`、`/dryrun*` |
| `ApiVisualEditor.vue` + `ApisView.vue` + `SkillsView.vue` + `RegressionView.vue` | 双协议网关编排、技能与回归视图 | 4 页签可视化 + YAML 注释保留同步、`${$now}` 保护、五模式样本反推、`syncColumnsFromTestResult` 列回填、技能安全预览与 `reg-diff-detail` 抽屉 | `/apis/*`、`/skills/*` |
| `ReleasesView.vue` + `SettingsView.vue` | 版本发布与 48 项热更新配置中心 | 跨版本 Diff 跳链、带必填原因 `emergency-switch`、系统提示词时间线、`X-API-Key` 轮换卡、48 项配置分栏对比、局部默认重置与 `cN` 回滚 | `/releases/*`、`/settings/*` |

---

## 9. 配置与热更新开关 【补充】

> 前端工程自身无后端式运行期配置持久化文件，仅支持以下构建/开发期环境变量；后端 `48` 项 `RuntimeConfig` 参数的 UI 编辑界面与映射契约在 `SettingsView.vue` 与 `types/platform.ts` 中完整对应实现。

| 配置项（Env / Build） | 类型 | 默认值 | 是否支持热更新 | 说明 |
| --- | --- | --- | --- | --- |
| `VITE_BASE_PATH` | `str` | `'./'` | 否（构建期） | Vite `base` 资源基址，默认相对路径以兼容根路径与反代子路径部署 |
| `VITE_API_BASE_URL` | `str` | `'api/v1'` | 否（构建期） | 前端 `platformApi.ts` 请求基址，相对路径自动对齐当前反代前缀 |
| `VITE_BACKEND_PROXY` | `str` | `'http://127.0.0.1:8000'` | 否（开发服务器） | Vite dev server `/api` 代理目标地址 |

---

## 10. 测试设计（Test Strategy） 【核心】

### 10.1 测试范围与分层策略

| 测试类型 | 覆盖范围 | 桩/隔离策略 | 重点验证场景 |
| --- | --- | --- | --- |
| 静态类型门禁 | `frontend/src/**/*.ts`、`*.tsx`、`*.vue` | `tsconfig.app.json`（`strict: true`，`ES2022`） | 48 项 `RuntimeConfig` 类型对齐、`BrandMark` props 与组件 Ref 类型安全、零隐式 `any`/空值报错 |
| 多入口分包与产物校验 | `index.html`、`embed.html`、`public/favicon.svg`、`dist/` | `npm run build`（`vue-tsc -b && vite build`） | 确认 8 个 `manualChunks` 正确切出；检查 `dist/embed.html` 预加载清单确认零引入 `element-plus` 与 `codemirror`；`dist/favicon.svg` 完整拷贝 |
| 全栈联调与交互验收 | 登录、模板 IDE、SSE 试运行、三页签定位、API 拨测、多页签与设置中心 | 本地 Vite 5175 + `report-agent serve` + Mock 网关 | `409` 冲突弹窗、字段改名正文联动、同值消歧高亮、0 行列表、`emergency-switch` 与 `F2` 图标亮暗渲染 |

### 10.2 回归范围

- 每次修改 `frontend/src/` 或共享组件（如 `BrandMark.vue`）后，必须执行全量 `npx vue-tsc --noEmit -p tsconfig.app.json` 与 `npm run build`，并核验 `frontend/dist/embed.html` 与 `frontend/dist/index.html` 分包隔离不变。

<a id="plan-quickstart"></a>

### 10.5 验证指南

- **环境与前置条件**：Node.js + `npm ci` 已安装 `frontend/node_modules`，需本地联调时预先启动 `uv run report-agent serve`。
- **验证命令**：
  ```bash
  cd frontend
  npx vue-tsc --noEmit -p tsconfig.app.json
  npm run build
  ```
- **预期结果**：`vue-tsc` 0 错误退出，`vite build` 顺利完成（如实测 `3415 modules transformed`），生成 `dist/index.html`、`dist/embed.html`、`dist/favicon.svg` 与 `8` 个独立依赖分包，且 `dist/embed.html` 不引用 `element-plus` 或 `codemirror`。

---

## 11. NFR 符合性自检 【核心】

| 自检主题 | 宪章依据 | 是否涉及 | 落实位置与验证方式 |
| --- | --- | --- | --- |
| 零业务硬编码与资源隔离 | I | 是 | 视图与算法完全基于接口下发 `TemplateDetail`/`ApiDetail`/`RunDetail` 动态驱动，源码审阅零模板编号硬编码 |
| 强证据防幻觉与确定性计算 | II | 是 | `ReportPreviewContent`、`EvidenceSourceInspector` 与 `AgentTimeline` 忠实反映退回/降级与 0 行结果 |
| 文件化存储与 `workers=1` 并发安全 | III | 是 | 前端透传 `revision` 并适配 `409` 弹窗，配合后端乐观锁保障协同无覆盖 |
| 安全编码、脱敏与零凭据硬编码 | VI | 是 | `sanitizeHtml` 净化 XSS、`BrandMark` 隔离梯度 ID、设置表单掩码与 `clear*` 开关、源码零真实凭据 |
| 多入口分包边界与构建检查 | VIII / 技术约束 | 是 | `BrandMark.vue` 零重型依赖；`vue-tsc` 0 错误与 `npm run build` 实测通过且 `embed.html` 保持纯净 |

---

## 12. 发布与回退计划 【核心】

- **发布前置与步骤**：执行 `cd frontend && npx vue-tsc --noEmit -p tsconfig.app.json && npm run build` 产出最新 `frontend/dist/` → 核验 `dist/favicon.svg`、`dist/index.html`、`dist/embed.html` 与 `assets/` 分包完整 → 由后端 `FRONTEND_DIST` 或容器镜像静态层托管上线。
- **回退方案**：若新构建前端静态包出现兼容性或交互异常，直接回退 `frontend/` 源码与 `frontend/dist/` 构建目录版本并重新发布容器或刷新静态托管目录即可秒级恢复。

---

## 13. 实施切片与建议顺序（Implementation Slices） 【核心】

> 与 `tasks.md` 7 个阶段及 18 项任务严格对齐，切片工时精确加总为 `33.0 人天`。

| 切片 ID | 切片名称 | 对应 Phase / 任务范围 | 目标与涉及文件 | 核算工时（如适用） |
| --- | --- | --- | --- | --- |
| `S-01` | Vite 多入口 8 分包、F2 Favicon 与路由/主题基线 | Phase 1（`T001`–`T002`） | `index.html`、`public/favicon.svg`、`package.json`、`tsconfig.app.json`、`vite.config.ts`、`main.ts`、`router/index.ts`、`styles.css`、`terms.ts` | `3.0 人天` |
| `S-02` | REST/SSE 客户端、Pinia 核心状态机与 `BrandMark` 安全组件底座 | Phase 2（`T003`–`T005`） | `types/platform.ts`、`api/platformApi.ts`、`utils/{sse,sanitizeHtml,markdown,textDiff,clipboard}.ts`、`stores/platform.ts`、`BrandMark.vue`、`SvgIcon.vue`、`StatusTag.vue` | `6.0 人天` |
| `S-03` | 四分区模板 IDE 与 CodeMirror 6 Jinja2 词法作用域编辑器（MVP） | Phase 3 / US1（`T006`–`T008`） | `utils/{jinjaBody,listColumns}.ts`、`CodeMirrorEditor.vue`、`TemplateWorkbenchView.vue`、`TemplatesListView.vue`、`GlobalModals.vue`、`components/workbench/{WorkbenchLeftExplorer,WorkbenchTemplateStage,WorkbenchRightInspector}.vue` | `6.5 人天` |
| `S-04` | SSE 实时推理时间线与 AST 消歧三页签双向证据溯源 | Phase 4 / US2（`T009`–`T011`） | `utils/{reportSegments,timelineFormat}.ts`、`ReportPreviewContent.vue`、`WorkbenchDebugPanel.vue`、`AgentTimeline.vue`、`FieldEvidenceTable.vue`、`EvidenceSourceInspector.vue`、`RunsView.vue` | `6.0 人天` |
| `S-05` | 可视化双协议网关编排器、技能治理与回归抽屉 | Phase 5 / US3（`T012`–`T014`） | `ApiVisualEditor.vue`、`ApisView.vue`、`SkillsView.vue`、`RegressionView.vue`、`GlobalDrawers.vue` | `5.5 人天` |
| `S-06` | 多页签保活壳层、`F2` 门户登录、版本中心与 48 项设置中心 | Phase 6 / US4（`T015`–`T016`） | `stores/workspaceTabs.ts`、`WorkspaceTabsBar.vue`、`ChatIframeTabPane.vue`、`ChatSimTemplatePicker.vue`、`App.vue`、`LoginView.vue`、`ChatSimView.vue`、`ReleasesView.vue`、`SettingsView.vue` | `3.5 人天` |
| `S-07` | 严格 TypeScript 门禁修复与多入口生产构建验收 | Phase 7（`T017`–`T018`） | `tsconfig.app.json`、`vite.config.ts`、`package.json` 及全量构建产物核验 | `2.5 人天` |

---

## 14. 风险清单与缓解（Risks） 【补充】

| 风险 ID | 风险描述 | 影响 | 概率 | 缓解措施 |
| --- | --- | --- | --- | --- |
| `R-1` | 公共组件误引入 `element-plus` 或 `codemirror` 导致 `embed.html` 体积暴涨 | 高 | 低 | 为 `BrandMark.vue` 等共享组件设立零重型依赖红线，并在 `npm run build` 后核验 `dist/embed.html` 预加载清单 |
| `R-2` | 千行级推理轨迹与海量网关结果触发 Vue 3 深度响应式卡顿 | 高 | 中 | 在 `stores/platform.ts` 中通过 `stabilizeRunDetail` 对只读明细大数组执行 `markRaw` 剥离 Proxy 追踪 |
| `R-3` | 多标签与组件 `<KeepAlive>` 缓存导致切换回资源页面显示过期或丢失未保存草稿 | 中 | 中 | `workspaceTabs.ts` 实现 `before-leave` 脏草稿挽救拦截与干净切回刷新机制，递增请求序号过滤过期异步响应 |

---

## 15. 待确认事项（Design Open Questions） 【补充】

> 设计阶段关键技术取舍已全部闭环，无未关闭 `DQ-*`。

| 编号 | 问题摘要 | 对应 Spec Q-* | 当前结论 | 状态 |
| --- | --- | --- | --- | --- |
| `DQ-1` | 回归测试视图批量全量回归接口未就绪前的界面交互边界 | `Q-001` | 仅展示真实版本对比数据与单条试跑能力，界面注释明确标识批量自动回归为 Phase 2 扩展 | 已关闭 |
| `DQ-2` | `BrandMark.vue` 跨双入口复用与同页多实例渐变 ID 安全方案 | `Q-002` | 采用零外部重型依赖 SFC + Vue `useId()` 隔离渐变 ID，构建验证零侵入 `embed.html` | 已关闭 |

---

## 附录 A：核心字段与状态约定（仅本需求）

- **前端导航与页签常量**：主导航、页签与发布类型名统一引自 `frontend/src/constants/terms.ts` 的 `NAV_LABELS` 与 `NAV_GROUP_LABELS`；`<KeepAlive :max="12">` 上限 `12` 个路由页签，动态聊天页签与 `#tab-templates`（锁定下标 `0`）共存在 `useWorkspaceTabsStore`。
- **关键 UI 时序与尺寸常量**：模板内存预览防抖 `350ms`、Markdown LRU 缓存 `32` 条、左侧活动栏宽 `50px`（6 栏 `IdeLeftSection`）、调试历史窄栏宽 `190px`、IDE 底部状态栏高 `24px`、顶部壳层栏高 `50px`、关联引用弹窗列表限高 `240px`、`BrandMark` 默认尺寸 `28px`（侧栏 `26px` / 登录门户 `38px`）。
- **Vite 8 分包命名**：`vue-core`、`vue-state`、`markdown-lib`、`icons`、`element-plus`、`element-deps`、`codemirror`、`workbench-libs`。

## 附录 B：AI 编码与交付约束

1. 先阅读 `spec.md`、本 `plan.md` 与 `tasks.md`，按 `T001`–`T018` 顺序实施，不实现 Out of Scope 内容。
2. 所有已勾选完成 `[X]` 的任务必须附有真实命令验证输出，严禁“仅写完未验证即标完成”。

---

## 变更记录（Changelog）

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | Codex | 完成 `006-vue-workbench-ide` 初始前端架构设计文档（33.0 人天） |
| 2.0 | 2026-11-16 | AiCoding | 按改造后 `inline-v1` 单文件 Plan 模板重构，补充四大内联锚点、宪章检查表、Wiki 评估、三类交付物台账及最新 `F2` 品牌图标资产与构建事实 |
