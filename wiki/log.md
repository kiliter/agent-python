# 项目知识库维护日志（Log）

<!-- #Created By AiCoding(codex) -->

本文件按时间顺序只追加记录 `wiki/` 的初始化、资料摄入（`ingest`）、专题沉淀（`query`）与全库健康检查（`lint`）历史。格式约定见 [SCHEMA.md](SCHEMA.md)。

## [2026-11-12] ingest | 初始化 agent-python LLM Wiki 知识库与 AGENTS.md

- 通读 `src/report_agent/`（`api`、`domain`、`gateway`、`runtime`、`store`、`seed`）、`frontend/`、`tools/java_migration/`、`tests/` 与 `docs/frontend-api-handoff.md`，建立根目录 `AGENTS.md`（及 `CLAUDE.md` 软链接）与完整的 `wiki/` 三层知识库。
- 编写核心架构页（`architecture/` 5 篇）、组件剖析页（`components/` 5 篇）、业务 Skill 卡片（`skills/` 12 篇）、架构决策记录（`decisions/` ADR-001～ADR-005）、实操指南（`guides/` 5 篇）、参考速查表（`reference/` 4 篇）与质量差异审计台账（`lint/` 3 篇）。
- 完整记录与前代 Java 版（`pdf-agent-parse`）的架构演进关系、33 个生产模板（`100`～`132`）、11 个纯文本 Skill、3 个声明式网关接口契约与 12 个确定性平台工具。

## [2026-11-12] lint | 对齐二期 platform 与 migration 最终落地契约并完成全库健康检查

- 对照二期 `@platform` 最终落地的 `config.py`、`runtime/{runner,evidence,tools,text_tools}.py` 与 `domain/jinja_env.py`，逐字核准全部环境变量名（`AGENT_*`、`GATEWAY_MODE=live|mock`、`REPORT_API_KEYS`）、12 个确定性工具入参/返回字典结构、`TrackedList` 渲染分支追踪及列表空结果 `status="found", value=[]` 证据校验规则。
- 对照二期 `@migration` 最终落地的 `seed/skills/*/SKILL.md`、`seed/templates/100..132/`、`TEMPLATES.md` 与 `MAPPING.md`，对齐 R2（`reminder-sms`）、R5（`pretty-number-info`）、R7（移除同名入参 `客户号码`，33 模板 `validate_all` 0 error / 0 warning）、R8（`qry-balance` 纯年月整月展开）与 R17（模板 120 `有设备押金` `whenMissing: empty`）全部细节及 2,240 个 Pebble/Jinja2 渲染对拍场景。
- 执行全库只读自动化 Lint：确认 `CLAUDE.md -> AGENTS.md` 软链接有效、42 个带头页面 YAML frontmatter 与 `sources` 路径 100% 合法、全库相对链接零断链、`wiki/index.md` 零遗漏零孤立页。

## [2026-11-12] ingest | 全量代码审查修复（Batch 1~4）

- 同步 `AGENTS.md`、`wiki/reference/{configuration,glossary}.md` 与 `wiki/architecture/*`、`wiki/components/*`：更新默认 `AGENT_TOOL_CALLS_LIMIT=120`、`LLM_PARALLEL_TOOL_CALLS=true`、`GATEWAY_MAX_CONCURRENCY=32`、批量 `load_skill` / `format_date`、同工作区幂等 `call_api` 去重、`call_api`/`query_result` 返回 `callId`、收紧后的空列表证据规则（仅认 `count==0` / `total==0` 查询证明，禁引 `load_skill`）、前置 `not_found` 字段全量级联降级、`extract_dates` `[日号]` 边界、`date_range` 6 位月与前缀分隔日期、`text_contains` 默认剥离空白、`expand_period` 双段 `$` 闭区间升序展开与 ReDoS 嵌套量词拦截。
- 同步运行时与存储/Web 性能安全优化：记录 Jinja2 编译 `lru_cache`、`(report_model, agent)` 版本缓存、`DocumentIndex` 预分词、`ReleaseStore`/`CaseStore`/`RunStore`/`overlay` 读路径缓存与启动恢复、细粒度草稿接口乐观锁 `revision` 校验、`LoginGuard` 已知账号防挤出与 IP 桶限流及前端路由懒加载优化。
- 同步生产资源治理（`wiki/skills/*`、`wiki/reference/{templates-catalog,apis-catalog}.md`）：记录 `reminder-sms` 无合法到期日直接跳过查询（不回退 `创建时间` 当天）、`accept-type` 前置 `not_found` 规范提交、`cc_pretty_num_info_query` `missingAs: failure`、模板 `121` `安装地址` 与 10 个模板 `标准资费` 改为 `derive`、模板 `111`/`114`/`115` `违约责任` 空值分支修复及 5 个模板补齐 `deadlineDate` 入参。
- 更新 `wiki/lint/{java-divergence,known-issues,open-questions}.md` 与 `wiki/guides/*`、`wiki/decisions/*`：增补 `verify_structure.py` S8/S9 AST 静态门禁，并在 `open-questions.md` 明确登记模板 `116`（`body.md.j2` 第 38 行）源自 Java 原模板的 `受理渠道` 枚举分支失配待业务确认事项。

## [2026-11-12] ingest | 新增嵌入式聊天选模板窗口（chat-embed）与模板路由 Skill（template-router）

- 新增 [components/chat-embed.md](components/chat-embed.md)：记录 `/embed.html` + `/api/v1/chat/*` 全链路架构，涵盖父子窗口 `postMessage` 握手与首个 `origin` 锁定、`ChatStore` 分片持久化与上层/用户补充入参合并指纹演进、`ChatAgent` 结构化五类动作与 `@agent.output_validator` 自愈、`ChatRunManager` 单会话并发互斥与 `StepMapper` 隐私脱敏步骤映射、SSE `?after=N` / `Last-Event-ID` 断点续接、`rewrite` 未核验标记以及 `confirm` 幂等审计与重启 `INTERRUPTED` 恢复。
- 新增 [skills/template-router.md](skills/template-router.md)：记录第 12 个内置纯文本 Skill `template-router` 的聊天路由职责、`### <ID>` 三级标题模板登记约定，以及 `domain/resources.py` 新增的四项交叉校验规则（`ROUTER_SKILL_HAS_APIS`、`ROUTER_TEMPLATE_NOT_FOUND`、`ROUTER_TEMPLATE_UNCOVERED`、`ROUTER_SKILL_IN_TEMPLATE`）。
- 同步更新 `AGENTS.md`、[index.md](index.md)、[overview.md](overview.md)、[skills/README.md](skills/README.md)、[components/api-and-auth.md](components/api-and-auth.md) 与 [components/workbench-frontend.md](components/workbench-frontend.md) 中的内置 Skill 规模（12 个）、`chat/` 代码与 `chats/` 数据目录、`require_chat_caller` 双轨鉴权及工作台聊天窗口模拟视图（含 `ChatSimTemplatePicker.vue` 模板示例入参预填、回归用例一键载入、系统设置 `reportApiKeys` 在线配置/明文查看/重新生成热重载与模拟页自动带出系统 Key）。

## [2026-11-12] ingest | 聊天窗口新增模板结构样例预览、原样运行过程事件流与跨会话防越权绑定

- 更新 [components/chat-embed.md](components/chat-embed.md) 与 `docs/chat-embed-api.md`：记录新增 `GET /api/v1/chat/sessions/{sid}/templates/{templateId}`（`ChatService.get_template_preview`）样例预渲染逻辑、`ChatRunManager` 原样过程事件实时流与 `GET /api/v1/chat/runs/{runId}/raw` 持久化回退、`/runs/{runId}/*` 的 `X-Chat-Session-Id` / `sessionId` 跨会话防越权绑定，以及 `ChatEmbedApp.vue` 默认 `BASE_WIDTH = 560` 等比缩放舞台与自适应布局回退设计。
- 同步对齐 [reference/configuration.md](reference/configuration.md) 与 [components/api-and-auth.md](components/api-and-auth.md)：将支持在线热更新的核心配置计数更新为 26 项（含 `REPORT_API_KEYS` -> `reportApiKeys`），补齐 `DATA_DIR/chats/`、`require_chat_caller` 鉴权优先级与 `routes_chat.py` 全部 10 个聊天窗口端点说明。

## [2026-11-12] ingest | 嵌入式聊天工作台全面 PC 桌面化与模拟台页内多页签整页铺满重构

- 更新 [components/chat-embed.md](components/chat-embed.md) 与 `docs/chat-embed-api.md`：记录 `/embed.html` 升级为 `BASE_WIDTH = 1360`、`MIN_STAGE_HEIGHT = 680` 的 PC 宽屏全幅等比缩放双栏工作台（消除窄屏留白灰边，保留等比缩放与自适应布局切换），右栏常驻 `报告预览`（含左右分栏实时对比）、`运行记录`（精简步骤 ↔ 原样记录）、`模板预览`、`模板库` 与 `工单入参` 5 个业务标签页。
- 更新 [components/workbench-frontend.md](components/workbench-frontend.md)：记录 `ChatSimView.vue` 重构为纯页内多页签（In-Page Tabs：`父页面参数` 双列卡片、动态 `聊天窗口 · 工单号`、`postMessage 交互日志`、`回传报告结果` 双栏对比）与默认整页铺满模式（顶部保留 40px 页内页签栏，下方 `/embed.html` iframe 占满 `100vw × calc(100vh - 40px)` 整个浏览器页面，`v-show` 保活且支持 `ESC` 切换及 `chat-close-request` 自动关闭跳转），彻底移除移动端窄屏宽度切换项。


## [2026-11-12] ingest | 管理端右侧全局多页签栏（ElTabs + SortableJS）与 ChatGPT Web 单栏流式聊天窗口重构

- 更新 [components/workbench-frontend.md](components/workbench-frontend.md)：记录管理端新增右侧全局多页签导航栏 `WorkspaceTabsBar.vue`（基于 Element Plus `<el-tabs type="card">` + `SortableJS` 拖拽重排 + `<el-dropdown>` 快捷关闭菜单）、全局工作区多页签仓库 `stores/workspaceTabs.ts`、动态聊天保活面板 `ChatIframeTabPane.vue`（`100% × 100%` `v-show` 保活）以及 `App.vue` 路由页签 `<KeepAlive>` 缓存与未保存草稿拦截；同步记录 `ChatSimView.vue` 重构为清爽的 PC 左右双栏模拟联调台（点击「在顶部新页签打开聊天窗口」在全局页签栏新增 `智能填报 · <orderId>` 页签）。
- 更新 [components/chat-embed.md](components/chat-embed.md) 与 `docs/chat-embed-api.md`：记录 `/embed.html` 重构为 ChatGPT Web PC 端风格纯亮色单栏居中流式界面（`BASE_WIDTH = 1280`、`MIN_STAGE_HEIGHT = 640` 等比缩放舞台 + 自适应切换，中央 `max-width: 840px` 消息流内联 `RecommendCard`、`AskParamsCard` 与含「精简步骤 ↔ 原样运行记录」及内联报告正文卡片的 `RunCard`，底部 24px 大圆角输入舱 `ChatInput`，以及挂载于 `.embed-stage` 内并全部支持一键页内全屏切换的 `PreviewDialog`、`TemplateStructureDialog`、`SwitchTemplateDialog` 三大详情弹窗）。

## [2026-11-12] ingest | 修复聊天窗口 AI 改写报告在当前回复气泡下方直接展示报告卡片与历史会话兼容补全

- 更新 `src/report_agent/chat/service.py` 与 `src/report_agent/chat/agent.py`：`ChatService.send_message` 在 `action="rewrite"` 分支生成未确认新改写版本时将 `card["confirmed"]` 复位为 `False`，并在追加的助手 `text` 回复消息上附带 `rewriteRunId` 与 `rewriteVersionNo`；`ChatService._build_view`（`_backfill_legacy_rewrite_links`）对存量历史会话中未带 `rewriteRunId` 的改写回复按 `createdAt` 5 秒窗口及正文 `runId` 做一对一自动补全（不误绑普通答疑消息）；`CHAT_SYSTEM_PROMPT` 强化禁止以 `action="reply"` 口头假装改写而不提交完整 `markdown`。
- 更新 `tests/test_chat.py`、[components/chat-embed.md](components/chat-embed.md) 与 `docs/chat-embed-api.md`：补充 `rewriteRunId`/`rewriteVersionNo`、`card["confirmed"]` 复位及存量历史会话一对一自动补全回归断言，同步前后端契约与组件文档。

## [2026-11-13] ingest | 全栈四分支深度代码审查修复、公共原语收敛与分包性能优化

- 同步更新 [architecture/resource-release-and-store.md](architecture/resource-release-and-store.md)、[components/gateway-and-api-contract.md](components/gateway-and-api-contract.md) 与 [reference/configuration.md](reference/configuration.md)：记录 `store/fsutil.py` 统一 `mode=0o600` 原子写入与审计追加原语、`store/layout.py` 双层软链接守卫（`ensure_within` / `ensure_entry_within`）、`main.py` 重启读取持久化 `c.settings` 修复、`RuntimeConfigStore` 待恢复态自愈与 `cfg.validate()` 校验、`RunStore` `_write_lock` 排空互斥，以及 `ReloadableGatewayClient`（`_ClientSlot` + `asyncio.shield`）仅在 `_gateway_signature` 变更时热切换网关。
- 同步更新 [architecture/request-pipeline.md](architecture/request-pipeline.md)、[architecture/evidence-system.md](architecture/evidence-system.md)、[architecture/template-and-rendering.md](architecture/template-and-rendering.md)、[architecture/deterministic-tools.md](architecture/deterministic-tools.md)、[components/agent-runner.md](components/agent-runner.md) 与 [components/platform-tools.md](components/platform-tools.md)：记录 `safe_regex_compile` 下沉至 `domain/template.py`（显式栈非递归防 ReDoS）、`_find_reachable_cycle` 自环不入 `safe_nodes`、`has_supporting_real_source` 剔除自引证据与级联降级、标量字段拒收容器值、`call_api` 幂等在途取消自动接管，以及 `query_result` 单/多结果集统一管线与 `Condition`/`OrderBy` `extra="forbid"` 约束。
- 同步更新 [components/api-and-auth.md](components/api-and-auth.md) 与 [components/chat-embed.md](components/chat-embed.md)：记录 `api/common.py` 共享 SSE 与严格乐观锁 `parse_expected_revision`（拦截布尔/负值返回 `400 INVALID_REVISION`）、`_login_semaphore()` 跨事件循环限流与口令长度边界、`ChatService.open_session` 草稿会话防 API Key 降级劫持、`ChatStore` 64 分片锁与异步冷读盘串行化、`confirm_run` 改写切回旧版幂等判定修复，以及 `sanitize_error_text` 全链路路径/凭证脱敏。
- 同步更新 [components/workbench-frontend.md](components/workbench-frontend.md) 与 [components/chat-embed.md](components/chat-embed.md)：移除已清理死代码 `JinjaBodyEditor.vue` 及不可达旧抽屉描述，记录新增共享工具模块 `frontend/src/utils/{jinjaBody,sse,markdown,textDiff,timelineFormat,clipboard}.ts`、`ApiVisualEditor.vue` `${$now}` 占位符对齐、异步请求序号守卫与 `markRaw` 降载，以及 `embed.html` 剥离 `ElementPlus`/`CodeMirror` 重型依赖（`VersionSelect.vue`、`StageConfirmDialog.vue`、`stageToast.ts`，构建体积缩减约 80%）。

## [2026-11-13] ingest | IDE 级紧凑布局优化、工作台关联弹窗收敛与聊天窗口右侧全屏

- 更新 [components/workbench-frontend.md](components/workbench-frontend.md)：记录 `SkillsView.vue` / `ApisView.vue` / `TemplatesListView.vue` 采用单行省略配 `<el-tooltip>` 悬浮查看摘要，并以全局 `.ref-count-pill` + 限高滚动 `.ref-popover-list`（`max-height: 240px`）统一重构模板与 Skill 关联展示；同步记录 `App.vue` + `styles.css` 在聊天窗口激活时以 `.main-wrapper.is-chat-fullscreen` 隐藏顶栏与全局页签栏实现右侧全屏承载。
- 更新 [components/chat-embed.md](components/chat-embed.md)：记录 `/embed.html` 向 VS Code / IDEA 紧凑尺度收敛（`13px` 基础字号、`scaleFactor <= 1` 封顶、`920px` 对话流、标准蓝 `#2563eb` 用户气泡）、`RecommendCard.vue` 单外框多列子卡 + 搜索 + 眼睛图标预览、`ReportInlineCard.vue` 与 `PreviewDialog.vue` 单行不换行顶栏 + 顶部状态 Tag 悬浮 `.eb-tip` 替代占位提示横幅，以及全图标化操作按钮与重复全屏字符图标清理。
- 追加重构 [components/chat-embed.md](components/chat-embed.md)：新增零依赖防裁剪悬浮提示 `useStageFloatTip.ts`（`.eb-float-tip`）；将 `SwitchTemplateDialog.vue` 改造为单行 `42px` 搜索筛选顶栏 + 粘性表头紧致表格（`编号 / 模板名称 / 状态与匹配 / 模板说明 / 操作`）；将 `TemplateStructureDialog.vue` 改造为单行 `40px` 合并顶栏 + `38px` 紧凑底栏，Tab 3（入参与字段）由左右分栏重构为上下全宽独立滚动粘性表头 IDE 检查器（字段名不换行，规则单行省略配悬浮全文及点击行内展开）。

## [2026-11-13] ingest | 嵌入式聊天窗口新增阈值触发增量上下文压缩（Rolling Summary）与手动归档接口

- 更新 `docs/chat-embed-api.md`：在 `ChatSession` 补充 `memorySummary` 与 `summarizedUpTo` 字段，补充 `POST /sessions/{sid}/messages` 达 24 条阈值时推送「正在压缩早期对话上下文…」SSE `status` 的说明，新增 `POST /sessions/{sid}/compact` 手动上下文压缩接口契约（不足 8 条幂等返回 `compacted: false`、504/502 错误码）及顶栏/水位线轻量交互要点。
- 更新 [components/chat-embed.md](components/chat-embed.md)：记录 `chat/agent.py#ChatAgent.summarize_history`（`ChatSummaryOutput` / `submit_chat_summary` 及 `COMPACT_TRIGGER_MESSAGES = 24`、`COMPACT_KEEP_RECENT = 12`、`MANUAL_COMPACT_KEEP_RECENT = 6`、`MAX_MEMORY_SUMMARY_CHARS = 1_200` 等阈值常量）、`chat/service.py`（`_effective_memory_state`、锁外调模型与 `_persist_compaction_if_monotonic` 单调锚点落盘、自动压缩失败无感降级、`compact_session`）、与 `AgentRunner` `<document>` 证据域绝对隔离边界，以及 `ChatEmbedApp.vue` 记忆摘要胶囊/浮层与归档水位分隔线。
- 更新 [components/api-and-auth.md](components/api-and-auth.md)：将 `routes_chat.py` 挂载端点总数由 10 个更新为 11 个，补充 `POST /sessions/{sid}/compact` 手动压缩归档接口。

## [2026-11-13] ingest | 全面开放 48 项运行期配置在线热更新与全链路默认值兜底

- 更新 `.env.example` 与 `docs/chat-embed-api.md`：补齐 3 个平台工具限额环境变量（`AGENT_QUERY_DEFAULT_LIMIT`、`AGENT_QUERY_MAX_LIMIT`、`AGENT_MAX_PERIOD_MONTHS`）与 16 个嵌入式聊天/滚动压缩环境变量（`CHAT_*`），标注默认值、留空回退默认值与工作台在线热更新支持；在 `ChatSession` 契约中新增 `manualCompactKeepRecent`（默认 `6`）与 `manualCompactMinMessages`（默认 `8`）及热更新说明。
- 更新 [reference/configuration.md](reference/configuration.md) 与 [index.md](index.md)：将支持免重启热更新的运行期配置由 26 项扩展为 48 项（新增平台工具限额 3 项、网关并发与留存周期 3 项、聊天与上下文压缩配额 16 项），梳理 `Settings._fallback_blank_non_nullable_scalars`、`RuntimeConfig.from_storage_dict` / `apply_patch` 与消费侧 `cfg_int` / `cfg_float` / `_setting_int` 全链路默认值兜底、跨字段校验约束及仅保留 9 项启动期不变量边界。
- 更新 [components/chat-embed.md](components/chat-embed.md) 与 [components/workbench-frontend.md](components/workbench-frontend.md)：记录 16 项聊天/压缩参数接入 `RuntimeConfig` 免重启热生效及 `manualCompactKeepRecent`/`manualCompactMinMessages` 联动 `ChatEmbedApp.vue` 手动压缩按钮状态；同步记录 `SettingsView.vue` 新增「聊天会话与滚动上下文压缩配额」「平台工具限额与历史数据留存」表单分组、空值默认兜底、「恢复默认参数」按钮与 48 项历史快照对比标签。


## [2026-11-16] ingest | 前端界面术语统一为通俗叫法

- 全量替换 `frontend/src`、`index.html`、`embed.html` 中的界面文案与注释：核查模板→模板、Skill 能力库/规程→技能、API调用/契约→API、运行流水记录→运行记录、基准回归测试→回归测试、发布版本基线→版本发布、引擎与系统设置→系统设置；同步清理基线、快照、编排、取证、命中、兜底、热更新、数智、中台、台账、极昼云台/省网大屏等表述。
- 新增 `frontend/src/constants/terms.ts`（`NAV_LABELS` / `NAV_GROUP_LABELS`），由 `App.vue`、`stores/workspaceTabs.ts`、`ReleasesView.vue` 统一引用；⌘K 检索关键词保留旧叫法。
- 更新 [components/workbench-frontend.md](components/workbench-frontend.md)：同步页面名称并新增「前端统一术语」对照表。

## [2026-11-16] ingest | 工作台支持编辑模板名称与说明，内置资源去除 Java 迁移口径

- 前端：模板编辑左侧活动栏新增「信息」分类（`IdeLeftSection = 'info'`），右侧属性区可编辑模板名称与说明，随「保存草稿」经 `PUT /templates/{id}/draft` 的 `name` / `description` 提交；「新建模板」弹窗新增选填「模板说明」。
- 内置模板：33 个 `template.yaml` 的 `description` 改为描述模板适用场景与核查内容（来源 `tools/java_migration/template_descriptions.yaml`）；字段说明不再附带 `原规则（Java）：` 尾注，guide 中的“与 Java 一致”等表述改为直接描述取值方法；文件头不再声明“由 Java 模板生成”。
- 生成与校验工具：`generate.py` 读取 `template_descriptions.yaml` 并停止拼接原规则；`verify_structure.py` 的 S4 改为校验“有 rule 的字段必须写有非空取值说明”。
- 技能 / API / 系统提示词：清理 `SKILL.md` 头注释与正文中的“迁移自 Java / 与 Java 一致”说法、3 个接口契约 YAML 注释中的 Java 对照，删除系统提示词中关于“原规则（Java）”的说明。运行时 `prompt.py` / `chat/agent.py` 仍保留剥离 `原规则（Java）：` 尾注的兼容逻辑，用于已有数据目录中的历史模板。
- 注意：内置资源只在新数据目录 `report-agent init` 时导入，已部署环境需在工作台逐个修改模板说明后发布。


## [2026-11-26] ingest | 新增常规 HTTP 接口连接器（`connector: http`）及工作台可视化配置支持

- 领域与网关：在 `domain/api_contract.py` 扩展 `ConnectorType` 新增 `"http"`，支持 `method`（GET/POST/PUT/DELETE/PATCH）、`url`（含 `${参数}`/`${$now}` 占位符校验与构建）、`query`、`bodyType`（`json`/`form`/`text`/`none`）及 `response.format`（`auto`/`json`/`xml`/`text`），`http` 类型免填 `processCode`；新增 `gateway/http_client.py` 承载常规 HTTP 请求组装、凭证头/敏感查询参数脱敏预览及 JSON/XML/纯文本/204 响应解析；在 `gateway/unified_xml.py` 与 `gateway/mock.py` 中分别集成直连 HTTP 调度（复用意向信号量、禁止重定向与幂等重试）及 `.json`/`.xml`/`.txt` 本地 Mock 回放。
- 接口与前端：更新 `api/dto.py`、`api/routes_resources.py`（创建/局部更新/校验预览/试调用）及前端 `types/platform.ts`、`platformApi.ts`、`stores/platform.ts`、`GlobalModals.vue`、`ApisView.vue` 与 `ApiVisualEditor.vue`，实现常规 HTTP 接口的新建、协议筛选、URL/Method/Headers/Query/Body/Response 可视化双向编辑与在线试调用。
- 测试与文档：新增 `tests/test_api_http_connector.py` 覆盖契约校验、脱敏预览、直连重试、Mock 回放与管理端路由全链路，同步更新 [components/gateway-and-api-contract.md](components/gateway-and-api-contract.md)、[guides/add-skill-and-api.md](guides/add-skill-and-api.md) 与 [index.md](index.md)。

## [2026-11-26] ingest | 新增 Skill 三态作用域（`scope: template | global | chat`）与 `maxPreviewChars: -1` 全文保留

- **Skill 作用域模型**：在 `domain/skill.py` 新增 `SkillScope = Literal["template", "global", "chat"]`（默认 `template`，`template-router` 未声明时向后兼容为 `chat`）；在 `domain/resources.py` 新增 `ResourceSet.global_report_skills` / `chat_skills` / `allowed_skills` 并升级 `allowed_apis`，使 `scope: global` 技能及其 API 自动注入全部填报模板，同时新增 `GLOBAL_SKILL_REDUNDANT`、`CHAT_SKILL_IN_TEMPLATE`、`CHAT_SKILL_HAS_APIS` 交叉校验；`runtime/runner.py` 改用 `rs.allowed_skills(tpl)`，`chat/agent.py` 升级为允许加载全部 `scope: chat` 技能；内置 `seed/skills/template-router/SKILL.md` 显式补充 `scope: chat`。
- **预览全文保留与错误描述增强**：`domain/api_contract.py#SummarySpec.maxPreviewChars` 支持 `-1` 表示不截断，`runtime/tools.py#_format_api_success_payload` 在不截断且全行命中时返回明确未截断提示；`gateway/base.py` 补充 `resultDesc` / `errMsg` / `errorMessage` 错误描述自动提取。
- **管理端与前端工作台**：`api/dto.py`、`api/routes_resources.py` 与前端 `SkillsView.vue`、`GlobalModals.vue`、`WorkbenchLeftExplorer.vue`、`WorkbenchRightInspector.vue`、`ApiVisualEditor.vue` 完整支持 Skill 三态作用域新建、筛选、展示、模板绑定过滤与全局自动持有分组展示。
- **测试与文档**：新增 `tests/test_skill_scope.py`，扩展 `tests/test_api_http_connector.py`，同步更新 [skills/README.md](skills/README.md) 与 [skills/template-router.md](skills/template-router.md)。

## [2026-11-26] ingest | 新增多文件 Skill 子目录 Markdown 渐进式懒加载全栈支持

- **领域模型与静态校验**：在 `domain/skill.py` 为 `Skill` 新增 `docs: dict[str, str]` 字段及 `normalize_skill_doc_path`、`validate_skill_docs_map`、`extract_doc_title`、`resolve_skill_doc_link`、`extract_md_doc_links`、`load_skill_dir`（允许同级及最多两级子目录下的 `.md` 文档，单技能上限 50 篇 / 单篇 20 万字符，严禁软链接、隐藏段与 `..` 穿越）；`domain/resources.py` 接入 `load_skill_dir` 并在 `validate_skill` 新增相对链接断链阻塞校验（`SKILL_DOC_NOT_FOUND`）、不可达孤儿文档提示（`SKILL_DOC_UNREFERENCED`）以及 `template-router` 跨 `SKILL.md` 与所有子文档的 `### <ID>` 扫描。
- **存储层与快照发布**：升级 `store/drafts.py`（`DraftStore.write` 支持 Skill 嵌套子目录原子写盘、新增 `read_dir_files`）与 `store/service.py`（`_drafts_fingerprint` 递归指纹、`_files_from_tree` 递归回退、`_same_as_online` 比对主文档与全部子文档、`skill_docs`、`save_skill` 兼容保留已有子文档）。
- **运行时与聊天懒加载**：在 `runtime/tools.py` 与 `chat/agent.py` 统一扩展 `load_skill(name, names, doc, docs)`，实现 L1 主文档自动附带子文档索引、L2 按需懒加载单/多篇子文档，不新增第 13 个平台工具。
- **接口与前端工作台**：扩展 `api/dto.py`（`docsCount`、`docPaths`）与 `api/routes_resources.py`（`GET/PUT/discard-draft/rollback` 读写 `docs`）；改造 `SkillsView.vue` 为三栏多文件 IDE（左侧可折叠目录树、新建/重命名/删除/一键复制相对链接、预览区点击相对 `.md` 链接跳转或一键创建、版本历史逐文件 Diff）。
- **测试与文档**：新增 `tests/test_skill_docs.py`，同步更新 [skills/README.md](skills/README.md) 与 [architecture/deterministic-tools.md](architecture/deterministic-tools.md)。
- **内置模板路由拆分**：将 `seed/skills/template-router/SKILL.md`（原 280 行）重构为精简 L1 分流总控 + `references/` 下 6 篇按业务族懒加载的参考文档（完整覆盖 `100`～`132` 全部 33 个在线模板，`validate_all` 保持 0 error / 0 warning），同步更新 [skills/template-router.md](skills/template-router.md) 与 `tests/test_migrated_seed.py`。

## [2026-11-26] ingest | 新增一单多业务复合工单编排（方案 A）、可编辑汇总大模板、聊天紧凑小卡片与回退草稿自动清理

- **编辑状态与草稿自愈修复**：在 `store/service.py` 全量资源（模板、Skill、API、系统提示词、汇总大模板）及 `rollback(..., mode="draft_only")` 统一接入 `_clear_draft_if_same_as_online`，内容改回与线上一致时自动清理冗余草稿并返回 `cleared: true`；前端 `stores/platform.ts` 与 `SettingsView.vue` 改用快照/语义深度比对消除回退后假脏态。
- **多业务汇总大模板资源（`composite-template.md.j2`）**：新增 `domain/composite.py` 与内置 `seed/composite-template.md.j2`，纳入 `ResourceKind`、`store/layout.py`、`store/service.py` 与 `routes_resources.py`（`/api/v1/settings/composite-template*` 含实时样例预览），并在 `SettingsView.vue` 提供「汇总大模板」可视化 Jinja2 编辑器、实时预览与版本回退。
- **并发复合编排与跨子项幂等缓存（`runtime/composite.py`）**：新增 `SharedGatewayClient`（跨子项 `asyncio.shield` 并发去重并统计 `cache_hits`）与 `CompositeRunner`（同一快照并发执行多商品 × 多模板、部分子项失败隔离、Jinja2 确定性拼装 + 可选大模型二次润色保留确定性原版），对外开放 `POST /api/v1/reports/composite` 与 `POST /api/v1/reports/composite/polish`。
- **嵌入式聊天紧凑小卡片与多业务编排**：将 `ReportInlineCard.vue` 收敛为 ~84px 紧凑可点击摘要小卡片（点击弹出 `PreviewDialog` 查看全文）；扩展 `chat/{store,agent,manager,service}.py`、`routes_chat.py`（`POST /sessions` 支持 `items[]`，新增 `/composite-runs` 与 `/runs/{runId}/polish`）及前端 `CompositeRunDialog.vue`、`ChatEmbedApp.vue`、`ChatSimView.vue`（多商品列表与一键示例预设），保持 `embed.html` 零 `element-plus`/`codemirror` 依赖。
- **测试与文档**：新增 `tests/test_composite.py`，同步更新 [components/api-and-auth.md](components/api-and-auth.md) 与 [components/chat-embed.md](components/chat-embed.md)。

## [2026-11-26] ingest | 上游报告接口支持未传 `templateId` 自动调用 `template-router` 按最高置信度路由并填报

- **两阶段同快照自动路由（`runtime/router.py` + `runtime/runner.py` + `runtime/composite.py`）**：新增无状态 `TemplateRouter`，与 `ChatAgent` 共享只读路由工具（`load_skill`、`list_templates`、`get_template`），在单次请求锁定的同一份 `(rev, ResourceSet)` 快照上优先加载 `template-router` Skill（L1 主文档 + L2 `references/*.md` 懒加载，未配置时自动回退 `list_templates` + `get_template`），按置信度（`高 > 中 > 低`）稳定排序并始终选用最高置信度在线模板直接执行填报（低置信度不阻塞）；同步支持 `POST /api/v1/reports`、`/reports/stream` 与 `/reports/composite`（各 `items[i].templateId`）省略或传 `null` 触发自动路由。
- **接口响应、过程事件与前置失败边界**：`report_view` 补充 `templateName`，自动路由时额外返回 `routing`（显式传 `templateId` 时不附带，100% 向后兼容）；`detail_view`（`GET /api/v1/runs/{runId}`）透传 `routing`，SSE 过程事件在 `round=0` 新增 `route_started` / `route_completed` / `route_failed`；无可用在线模板、无有效在线候选或路由异常时返回 `422 TEMPLATE_ROUTE_FAILED`（附 `reason`、`candidates`），命中模板但缺少必填入参时返回 `400 INVALID_INPUT`（附 `templateId`、`templateName`、`routing`），两类前置失败均不写入 `RunStore`。
- **文档与知识库同步**：同步更新 `docs/frontend-api-handoff.md`、[architecture/request-pipeline.md](architecture/request-pipeline.md)、[components/api-and-auth.md](components/api-and-auth.md)、[skills/template-router.md](skills/template-router.md) 与 [index.md](index.md)。

## [2026-11-26] ingest | 新增模板 / 技能 / API 删除功能与五项治理保护规则

- **后端存储、门禁与路由**：在 `store/cases.py` 新增 `CaseStore.delete_all`；在 `store/publisher.py` 允许删除/下线模板时将未修改 `template-router` 的 `ROUTER_TEMPLATE_NOT_FOUND` 转为 `warnings` 不阻塞（编辑发布 `template-router` 自身仍严格报错），且 `action="delete"` 同步清理残余草稿；在 `store/service.py` 新增 `ResourceInUseError`、`ResourceDeleteForbidden`、`delete_template`、`skill_template_references`、`delete_skill`、`api_skill_references`、`delete_api`；在 `routes_templates.py`、`routes_resources.py` 与 `main.py` 暴露 `DELETE /api/v1/templates/{tid}`、`DELETE /api/v1/skills/{sid}`、`DELETE /api/v1/apis/{name}` 及 `409 RESOURCE_IN_USE` / `400 SKILL_DELETE_FORBIDDEN` 异常映射。
- **前端工作台与测试**：在 `platformApi.ts`、`stores/platform.ts`、`TemplatesListView.vue`、`SkillsView.vue`、`ApisView.vue` 补齐删除按钮、二次确认弹窗与禁用态原因提示；新增 `tests/test_resource_delete.py` 并同步 `docs/frontend-api-handoff.md` 与 [architecture/resource-release-and-store.md](architecture/resource-release-and-store.md)。

## [2026-11-26] ingest | 新增全平台回归测试工作台（方案 B）与未绑定模板自动路由回归支持

- **存储与执行引擎（`store/cases.py` + `store/layout.py` + `runtime/regression.py`）**：扩展 `CaseStore` 支持未绑定模板自动路由作用域 `cases/auto/`（`tid=None` / `scope="auto"`）、新增 `expectedTemplateId` / `lastMatchedTemplateId` 字段、`list_all()` 跨作用域聚合与 `move()` 迁移；新增 `RegressionStore`（落盘至 `DATA_DIR/regressions/`，默认保留最近 50 批）与 `RegressionRunner`（复用 `AgentRunner` + `TemplateRouter` 执行 `single`/`compare` 批量并发回归，计算路由偏差、期望值偏差与双版逐字段差异并回写用例状态）。
- **后端路由与前端工作台（`api/routes_regression.py` + `RegressionView.vue` + `GlobalDrawers.vue`）**：新增 `/api/v1/regression/*`（用例 CRUD/迁移、`/adopt-baseline` 局部与全量基线采纳、`/run/stream` SSE 实时回归、`/batches*` 历史批次查询）；重构 `RegressionView.vue` 落地方案 B 双 Tab 工作台（用例列表 + 逐字段差异对比、自动路由与模板范围筛选、单版/双版模式切换、实时进度条、新建/编辑自动路由用例弹窗与差异抽屉快捷采纳/跳转运行详单）。
- **测试与文档**：新增 `tests/test_regression.py`，同步更新 [architecture/resource-release-and-store.md](architecture/resource-release-and-store.md)、[components/api-and-auth.md](components/api-and-auth.md) 与 [components/workbench-frontend.md](components/workbench-frontend.md)。

## [2026-11-26] ingest | Jinja2 AST 条件分支短路优化与运行记录单页离线 ChatUI 模拟回放 HTML 导出

- **正文条件分支短路（`domain/jinja_env.py` + `runtime/prompt.py` + `seed/system-prompt.md`）**：新增 `body_field_conditions()` 静态解析正文 `if`/`elif` AST，结合枚举全覆盖过滤、自保护条件保护、循环局部变量隔离与跨字段说明依赖保护，在任务提示词中自动标注受条件保护字段及其触发条件，引导模型优先确定控制字段（如 `受理渠道`、`争议类型`），对未命中分支跳过专属 Skill 加载与接口查询并直接提交 `not_found`，全平台 30 个带条件模板自动受益。
- **运行记录离线模拟回放 HTML 导出（`api/run_export.py` + `api/routes_system.py` + `RunsView.vue`）**：新增 `POST /api/v1/runs/export-html`（支持单条及最多 50 条多选打包为单个零外链离线 HTML），复刻 ChatUI 单栏对话流、自动路由卡片、可折叠 `.thinking-bar`（精简步骤 ↔ 原样运行记录动态回放、倍速/暂停/重播/跳过动画）、流式报告卡片、入参/单据浮层与字段证据弹窗；前端 `RunsView.vue` 列表页支持多选批量导出，详情页支持单条一键导出。
- **测试与文档**：新增 `tests/test_run_export.py`，同步更新 [components/api-and-auth.md](components/api-and-auth.md) 与 [components/workbench-frontend.md](components/workbench-frontend.md)。
