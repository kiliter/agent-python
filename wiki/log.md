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

