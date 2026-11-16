<!--
同步影响报告
- 版本变更：1.0.0（参照企业级中文 Spec-Kit 宪章体系完成首次正式定版，全面适配 report-agent 单智能体与文件化治理架构）
- 涵盖原则：I–X 十项核心原则、技术与交付约束、六道开发质量门与治理条款
- 同步状态：
  - AGENTS.md / CLAUDE.md（同步按本宪章重整工程约束与 Spec 开发流程）
  - .specify/templates/{spec,plan,tasks}-template.md（同步采用中文单文件内联布局 inline-v1 与十章体系）
  - .agents/skills/speckit-{plan,tasks,analyze}/SKILL.md（同步单文件 Plan 兼容约定）
-->
# report-agent 项目宪章

<!-- #Created By AiCoding(codex) -->

## 核心原则

### I. 平台零业务硬编码与声明式资源隔离

`src/report_agent/` 平台核心源码 MUST 保持零业务硬编码，不得包含任何特定模板编号、短信关键词、业务套餐规则或外部接口专属逻辑。所有业务规则与渠道知识 MUST 外置承载于文件化资源体系：`templates/<id>/`（`template.yaml` + `body.md.j2`）、纯文本 `skills/<id>/SKILL.md`（含 `template-router`）及声明式网关契约 `apis/<name>.yaml`。

新增业务能力时，MUST 优先通过模板字段配置、Skill 文档编排、声明式接口契约与通用确定性工具原语实现；只有在确认所有既有原语均无法表达跨模板通用能力时，方可评审扩充平台工具或领域模型。理由：将易变的核查规则留在热发布资源层，是实现免重启治理与 33+ 模板零硬编码的前提。

### II. 单智能体自主规划、确定性原语与强证据防幻觉闭环

报告填写 MUST 由单个 `AgentRunner` 在共享 `Workspace` 内自主规划执行，并通过 `build_report_model` 动态生成的严格 Pydantic 交卷模型（`extra="forbid"`）提交结论与证据链；日历展开、日期偏移、时间差、文本清洗与正则提取等机械计算 MUST 交由 `runtime/tools.py` 与 `runtime/text_tools.py` 提供的 12 个确定性原语执行，禁止依赖大模型心算。

所有 `found` 字段结论 MUST 经过 `EvidenceChecker.check()` 核验（`quote` / `quoteWhole` / `input` / `derive` / `VALUE_TOOLS` / 列表逐行核验 / 空列表 `found: []` 零行查询证明），严禁引用 `load_skill` 或空值入参，并完整执行可达依赖环检测与不变点级联降级；Jinja2 沙箱渲染 MUST 通过 `TrackedValue` 与 `TrackedList` 精准追踪实际展示字段，准确判定 `SUCCESS` / `PARTIAL` / `FAILED`。嵌入聊天路由 `ChatAgent` 与填报引擎的上下文及证据域 MUST 保持绝对隔离，早期记忆摘要 `memorySummary` 严禁注入填报 `<document>` 或 `RunRequest.inputs`。理由：任何未经核验的模型推断进入终稿都会直接造成线上误判。

### III. 文件化 Git 原子发布与单进程并发安全（workers=1）

平台资源治理 MUST 依托 `DATA_DIR` 文件系统拓扑、内部 Git 仓库（`repo/`）与不可变发布快照（`releases/rN/`）运行，严禁引入外部关系型数据库或分布式协调组件破坏轻量化部署边界。线上快照切换 MUST 通过 `os.replace` 原子替换 `releases/current` 软链接完成；任何资源发布 MUST 先对整棵候选资源树执行 `validate_all()` 静态交叉校验，阻断跨模板断链、语法错误与 `template-router` 失配。

存储层（草稿乐观锁 `revision`、`Publisher` 发布互斥锁、`RunStore` 单协程异步写队列、`ChatStore` 64 分片锁与 `ChatRunManager`、`AuthService` 登录防爆破计数、`ReloadableGatewayClient` 引用计数槽位）均基于单进程异步并发模型设计，生产 Uvicorn 运行 MUST 严格锁定 `workers=1`；所有路径拼装 MUST 经过白名单正则与 `ensure_within` / `ensure_entry_within` 防穿越校验，敏感配置文件强制保持 `0600` 权限。理由：单进程内锁序与原子重命名是零数据库依赖下强一致性的根本保障。

### IV. 规格驱动开发与单文件内联设计边界

需求研发原则上 MUST 按 `需求收敛` → `speckit-specify` → `speckit-clarify` → `speckit-plan` → `speckit-tasks` → `speckit-analyze` → `speckit-implement` 推进（存量功能梳理或归档拆分按指定口径对齐事实并注明依据）。需求收敛阶段只澄清业务目标、范围边界、术语与异常取舍，MUST NOT 提前编写业务实现代码。

设计产物统一采用**单文件内联 Plan 布局**（`<!-- SPECKIT_PLAN_LAYOUT: inline-v1 -->`）：研究决策（`#plan-research`）、领域与数据设计（`#plan-data-model`）、内部接口与事件契约（`#plan-contracts`）及可执行验证指南（`#plan-quickstart`）均内联维护于 `plan.md` 中，不额外生成 `research.md`、`data-model.md`、`contracts/` 或 `quickstart.md`。每个需求目录仅包含 `spec.md`、`plan.md`、`tasks.md` 及按原则 X 经确认生成的外部交付物。理由：避免需求目录碎片化，使 AI 在有限上下文窗口内一次读全设计依据。

### V. 可复现自动化测试、本地 Mock 网关契约与性能边界

涉及领域模型、沙箱渲染、确定性工具、证据核验、存储并发、接口鉴权、聊天路由、前端关键交互或迁移工具链的变更 MUST 补充对应自动化测试（后端使用 `pytest` + `ScriptedModel` / `FunctionModel` 确定性桩模型，禁止单元测试访问外网大模型或真实内网网关）。核心单元测试 MUST 受 `tests/conftest.py` 的 `SEED_DIR` 隔离机制保护，生产 33 套模板资产变动 MUST 同步通过 `tests/test_migrated_seed.py` 回归。

涉及网关契约 `apis/<name>.yaml` 新增或调整时，MUST 同步检查并维护 `mock-gateway/` 脱敏样例（含无数据/错误分支）及接口字段校验覆盖；修改 Java 迁移资产或平台渲染/报文语义时，MUST 运行 `verify_structure.py`、`check_skills.py` 与 `verify_render.py`（环境具备 JDK 时）对拍验证。除非用户明确提出，MUST NOT 擅自新增压测脚本或脱离实测依据编造性能基线指标，但实现层仍 MUST 避免无界循环、主事件循环阻塞 I/O 与前端大对象深层响应式代理开销（如保留 `markRaw` 与流式取消释放）。理由：确定性测试桩与四层对拍体系是零外网依赖持续验证的基础。

### VI. 安全、隐私脱敏与零凭证硬编码

代码、测试、样例报文、配置文件、`specs/` 文档及 `wiki/` 知识库中 MUST NOT 出现任何真实 `LLM_API_KEY`、工作台口令、签名密钥（`ra_` 正式密钥等）或真实客户敏感数据；运行期含密钥配置只允许存于 `DATA_DIR/config/runtime/`（`0600` 权限）。

外部 XML 解析 MUST 挂载 `expat` 安全钩子阻断 `<!DOCTYPE` 与 `<!ENTITY`；受控正则编译 MUST 经 `safe_regex_compile` 显式栈检查拦截嵌套重复量词防止 ReDoS；工作台会话口令 MUST 保持 PBKDF2-HMAC-SHA256（60 万次迭代）+ `LoginGuard` 账号/IP 双轨限流，上游 API Key 校验 MUST 使用 `hmac.compare_digest` 常量时间比对，聊天嵌入页 MUST 锁定首个合法 `postMessage` `origin` 并将凭证仅保留在内存中；对外错误响应与聊天脱敏步骤流 MUST 经 `sanitize_error_text` 或等效机制屏蔽本地路径、凭证与长数字，禁止泄露内部异常堆栈。理由：平台同时服务内网治理工作台与外部工单 iframe 嵌入，安全防线不可降级。

### VII. 关键路径过程事件、阶段日志与审计留痕

报告生成与嵌入式聊天关键执行链路（快照锁定、入参校验、模型轮次、工具调用、证据退回 `report_rejected`、部分降级 `report_degraded`、会话压缩、运行取消与报告确认）MUST 通过 `Workspace` / `EventSink` 或结构化日志完整记录上下文（`runId`、`templateId`、`sessionId`、状态与失败原因），禁止静默吞错。

所有管理端写操作与聊天报告确认动作 MUST 以当前服务端已认证身份（`user.display_name` 或 `chat:{userId}`）不可伪造地记入 `DATA_DIR/audit.jsonl`，严禁信任前端请求体提交的伪造操作人字段；日志与运行时事件流 MUST 遵守原则 VI 脱敏边界，严禁打印完整密钥或 Authorization 明文。理由：申报报告直接面向投诉核查与稽核留痕，每笔输出必须做到证据可溯、操作可追。

### VIII. 新增源码格式、中文注释与最小改动边界

新增代码、脚本与文档 MUST 保持改动聚焦，严禁在需求任务中捎带无关目录重构、顺手升级依赖或批量格式化存量代码；交付物 MUST 完整，不留 `TODO`、`FIXME`、占位空函数或死代码。新增文件头部应保留 `#Created By AiCoding(codex)`（Markdown 为 `<!-- #Created By AiCoding(codex) -->`）标记，核心类、函数及复杂边界逻辑 MUST 编写准确的中文注释与 docstring，维护存量文件时 MUST 保留无关原有注释。

交付前 MUST 按作用域执行对应工具链静态检查并如实记录结果：后端 Python 使用 `uvx ruff@0.11.0 check src tests` 与 `uv run pytest`；前端 TypeScript/Vue 使用 `npx vue-tsc --noEmit -p tsconfig.app.json` 与 `npm run build`（并确保 `embed.html` 产物不混入 `element-plus` / `codemirror` 重型依赖）。未实际运行的检查 MUST 标明未执行，不得勾选为已验证通过。理由：保持清晰的变更差异与静态零告警基线，降低后续审查与回归成本。

### IX. 知识库（wiki/）同步与文档职责隔离

`wiki/`（按 Karpathy LLM Wiki 模式组织）、`specs/` 与 `docs/` 各司其职：`specs/` 记录单次需求的规格、设计、任务与验收追溯；`docs/` 维护对外集成契约（如 `chat-embed-api.md`、`frontend-api-handoff.md`）；`wiki/` 只沉淀跨需求长期有效的架构、组件、Skill 与决策知识。

当修改平台工具签名、证据核验规则、核心运行管道、配置项、模板/Skill/契约或修复迁移差异后，MUST 按 `wiki/SCHEMA.md` 同步更新受影响页面与 `wiki/index.md`，并在 `wiki/log.md` 末尾追加记录，避免按单次需求编号在 `wiki/` 新建碎片页。理由：确保代码、规格与持久化项目知识长期保持单源一致。

### X. 外部独立交付物的确认与按需生成

正式生成需求规格或拆解任务前，MUST 依据需求真实影响判定并在 `spec.md` 第 8.2 节记录以下三类外部独立交付物是否涉及（未明确确认前不得自行臆造生成）：

1. **`接口文档.md`**：仅当新增或实质变更面向外部上游系统的 REST/SSE 或 `postMessage` 集成契约时按需生成或指向 `docs/` 权威契约；仅涉及内部工作台调整或复用既有接口时不触发。
2. **`资源迁移与Seed清单.md`**：仅当涉及批量新增/重构 `src/report_agent/seed/` 生产模板/Skill/契约或变更 `tools/java_migration/` 规则字典时触发；普通平台逻辑迭代不触发。
3. **`部署与配置变更单.md`**：仅当新增环境变量、修改 `Dockerfile`/`docker-entrypoint.sh`、容器卷拓扑或需运维执行停机/升级配置动作时触发；纯代码逻辑或默认热更新配置不触发。

不涉及的交付物 MUST NOT 创建空壳文件或失效链接，仅在 `spec.md`、`plan.md` 与 `tasks.md` 台账中写明不涉及依据；涉及的交付物必须在 `tasks.md` 中安排独立同步与核验任务。理由：严格约束交付物边界，避免制造冗余无效文档。

## 技术与交付约束

- **运行环境与核心技术栈**：Python `>=3.12,<3.14`（容器基于 `python:3.13-slim` + `uv:0.7`）、FastAPI + Uvicorn（单进程 `workers=1`）、Pydantic AI `2.67.0` + Pydantic `>=2.12`、Jinja2 `>=3.1`、`httpx>=0.28`、`jsonschema`、`pyyaml`；前端 Vue `3.5` + TypeScript `5.8` + Vite `6` + Pinia `3` + Vue Router `4` + Element Plus + CodeMirror `6`。版本以 `pyproject.toml`、`uv.lock` 与 `frontend/package.json` 为准。
- **前端构建分包边界**：`frontend/vite.config.ts` 的 `embed` 入口服务外部 iframe，MUST 保持轻量独立分包，不得在 `src/embed/` 中引入 `element-plus` 或 `codemirror`。
- **禁止自动提交与危险操作**：未经用户明确指令，MUST NOT 自动执行 `git commit`、`git push`、`git merge`、生产发布操作或绕过权限/访问边界；不得修改 `tests/conftest.py` 的全局隔离假设而污染生产 `seed/` 测试边界。
- **单向代码规模建议**：新增后端函数宜保持职责单一、浅层嵌套，复杂逻辑拆分为可单独单测的辅助原语，避免在多模块重复实现等价清洗、鉴权或状态映射逻辑。

## 开发流程与质量门

任何 MUST 违反项均阻塞推进至下一阶段，不得以 `Complexity Tracking` 豁免：

1. **需求门（Specify / Clarify）**：`spec.md` 必须明确需求编号、业务目标、范围与 Out of Scope、用户故事（`US*`）、功能需求（`FR-*`）、适用非功能需求（`NFR-*`）、异常边界（`EX-*`）、可验证成功标准（`SC-*`）及三类外部交付物确认结论；实质歧义登记为 `Q-*`（或 `[NEEDS CLARIFICATION: Q-x ...]`），关闭后再设计。
2. **计划门（Plan）**：`plan.md` 必须保留 `<!-- SPECKIT_PLAN_LAYOUT: inline-v1 -->` 及 `#plan-research`、`#plan-data-model`、`#plan-contracts`、`#plan-quickstart` 四个锚点，研究前、设计后完成宪章检查表并给出代码落点与证据；明确 `Wiki 影响评估`、安全隐私与单进程并发边界，列出可执行验证命令与测试范围。
3. **任务门（Tasks）**：`tasks.md` 必须将全部 `FR-*`、`NFR-*`、`SC-*`、`EX-*` 映射至连续 `T001...` 任务及 `TT-*` 测试矩阵、`RT-*` 发布清单，维护三类外部交付物台账；Wiki 受影响时单列同步任务；每个任务标注清晰文件路径与验收条件。
4. **分析门（Analyze）**：实现前执行交叉一致性检查，核验 `spec.md` / `plan.md` / `tasks.md` 编号追踪全覆盖、零冲突、零关键需求遗漏、零宪章违例与单文件 Plan 锚点完备。
5. **实现门（Implement）**：严格按任务依赖顺序落实代码与测试，不得超出 Out of Scope；未获测试命令真实通过证据前，不得将对应 `T*` 标为完成 `[X]`。
6. **完成门（Verify & Close）**：相关 `pytest`、`ruff check`、`vue-tsc`、`vite build` 或四层迁移校验实际通过并记录原始结果；安全扫描零真实凭据；`wiki/` 同步（如涉及）与文档追踪矩阵闭环一致。

## 治理

本宪章是 `report-agent` 仓库规格设计、任务拆解与工程交付的最高治理依据；`AGENTS.md`、`wiki/` 指南与 `.specify/templates/` 模板若与本宪章冲突，一律以本宪章为准。修订本宪章须由用户明确发起或确认，采用语义化版本号（删除或不兼容重定义原则升 MAJOR；新增原则或实质扩展治理范围升 MINOR；澄清表述升 PATCH）并同步记录变更影响。

**版本**: 1.0.0 | **批准日期**: 2026-11-16 | **最后修订**: 2026-11-16
