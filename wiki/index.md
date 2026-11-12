---
title: 项目知识库总目录
type: overview
tags: [index, catalog, navigation]
sources:
  - wiki/SCHEMA.md
  - AGENTS.md
updated: 2026-11-12
---

# 项目知识库总目录（`report-agent`）

<!-- #Created By AiCoding(codex) -->

欢迎查阅 `agent-python`（智能申告报告填写与资源治理平台）项目知识库。回答任何架构、组件、业务 Skill 或迁移对拍问题前，请先通过本目录定位目标页面；维护规范见 [SCHEMA.md](SCHEMA.md)，维护历史见 [log.md](log.md)。

## 全局总览

- [overview.md](overview.md) — 项目定位、零业务硬编码理念、与前代 Java 版（`pdf-agent-parse`）架构对比及核心规模指标（33 模板 / 12 Skill / 3 接口 / 12 工具）。
- [timeline.md](timeline.md) — 从单智能体底座搭建、Vue 3 工作台与配置热重载，到 Java 全量资源迁移、二期确定性工具及嵌入式聊天选模板窗口的演进脉络。

## 核心架构（`architecture/`）

- [architecture/request-pipeline.md](architecture/request-pipeline.md) — 单智能体请求全链路管道（快照锁定 → 动态 Schema → 工具循环 → 证据校验与级联降级 → 渲染与三级状态 `SUCCESS` / `PARTIAL` / `FAILED`）。
- [architecture/evidence-system.md](architecture/evidence-system.md) — `quote` / `input` / `derive` 强证据核验机制、`VALUE_TOOLS`、列表逐行核验与空数组 `found: []` vs `not_found` 校验契约。
- [architecture/template-and-rendering.md](architecture/template-and-rendering.md) — `template.yaml` + `body.md.j2` 资源模型、`TrackedValue` / `TrackedList` 实际展示分支追踪及 Pebble 兼容渲染细节。
- [architecture/resource-release-and-store.md](architecture/resource-release-and-store.md) — 文件系统存储布局、内部 Git 版本库、`releases/current` 原子软链接切换、草稿叠加视图与异步运行记录落盘。
- [architecture/deterministic-tools.md](architecture/deterministic-tools.md) — “模型负责语义、平台原语负责计算”设计边界及 12 个确定性平台工具的完整规格与组合模式。

## 组件剖析（`components/`）

- [components/agent-runner.md](components/agent-runner.md) — `runtime/runner.py`、`output_model.py`、`prompt.py`、`render.py` 与 `workspace.py` 的单智能体执行引擎实现。
- [components/platform-tools.md](components/platform-tools.md) — `runtime/tools.py` 与 `runtime/text_tools.py` 中 12 个平台工具、多结果集 `query_result` 过滤引擎与防 ReDoS 实现。
- [components/gateway-and-api-contract.md](components/gateway-and-api-contract.md) — `domain/api_contract.py` 声明式网关契约、`${$now}` 占位符、XML（Jackson 3 风格）与 JSON 双协议连接器、Mock 网关及热更新引用计数排空。
- [components/api-and-auth.md](components/api-and-auth.md) — FastAPI REST / SSE 路由分层（工作台、上游报告与嵌入式聊天）、会话 Cookie 与 `X-API-Key` 鉴权体系、防暴力破解及运行期配置热重载接口。
- [components/chat-embed.md](components/chat-embed.md) — 嵌入式聊天选模板窗口（`embed.html` + `/api/v1/chat/*`）：`postMessage` 握手与 `origin` 锁定、`ChatStore` 会话演进、`ChatAgent` 结构化路由、`StepMapper` 脱敏进度流与确认审计。
- [components/workbench-frontend.md](components/workbench-frontend.md) — `frontend/` Vue 3 + Pinia + CodeMirror 6 资源工作台与多页构建架构（含聊天窗口模拟联调视图）、证据溯源面板与乐观锁交互。

## 业务 Skill 详解（`skills/`）

- [skills/README.md](skills/README.md) — 12 个纯文本 `SKILL.md` 总览（11 个填报取数 Skill + 1 个聊天路由 Skill）、上游依赖图、网关接口映射、确定性工具使用矩阵及与 Java Groovy 版的对照。
- [skills/business-sms.md](skills/business-sms.md) — `business-sms`：查询工单创建当日下发的办理成功告知短信（“编号”前清洗匹配、排除退订短信），充当 4 个下游 Skill 的核心上游。
- [skills/accept-type.md](skills/accept-type.md) — `accept-type`：不调接口，基于 `订购短信` 正文中的“热线渠道”/“线上渠道”关键词判定受理渠道（热线 / 掌上营业厅 / 其他）。
- [skills/second-confirmation-sms.md](skills/second-confirmation-sms.md) — `second-confirmation-sms`：按“订购确认提醒 → 订购提醒”双优先级筛选包含“回复”的二次确认短信。
- [skills/verification-sms.md](skills/verification-sms.md) — `verification-sms`：筛选业务名称匹配且包含“动态验证码”的下发验证码短信。
- [skills/original-package-name.md](skills/original-package-name.md) — `original-package-name`：以 `订购短信` 发送时间为基准，用 `time_diff` 找时间距离最近的“退订提醒”短信并用 `regex_extract` 提取双引号内原套餐名。
- [skills/reminder-sms.md](skills/reminder-sms.md) — `reminder-sms`：用 `extract_dates` 提取 `订购短信` 中的最大合法到期日期，查询当日包含“提醒”的活动到期提醒短信与日期（已修复 Java R2 活动编号误识别缺陷）。
- [skills/renewal-reminder-sms.md](skills/renewal-reminder-sms.md) — `renewal-reminder-sms`：结合 `extract_dates`、`date_shift`（±31 天窗口）、`regex_extract` 与 `query_result(anyOf=...)` 一次识别合约到期延续/结束提醒与续约成功提醒共 6 个字段。
- [skills/number-portability-sms.md](skills/number-portability-sms.md) — `number-portability-sms`：查询工单创建当日包含“携号转网告知提醒”的短信，同步产出发送日期与携转资格回复短信。
- [skills/billing-cycle-sms.md](skills/billing-cycle-sms.md) — `billing-cycle-sms`：用 `expand_period` 展开账单起止月份逐月查短信，聚合生成“活动到期套餐资费变更 / 语音超额提醒 / 流量超额提醒” 5 列列表字段（支持 0 行 `found: []`）。
- [skills/qry-balance.md](skills/qry-balance.md) — `qry-balance`：用 `expand_period` 逐账期调用 `BOSS_QryBalanceFlowLog`，跨结果集 `query_result(resultIds=..., between)` 过滤并倒序生成 4 列充值流水列表（已修复 Java R8 年月回溯缺陷）。
- [skills/pretty-number-info.md](skills/pretty-number-info.md) — `pretty-number-info`：调用 `cc_pretty_num_info_query` 并核验本机号码、`grade` 非空及多档次活动名顿号拼接，产出靓号等级、靓号活动名称与手机号类别（已修复 Java R5 四项缺陷）。
- [skills/template-router.md](skills/template-router.md) — `template-router`：嵌入式聊天窗口专用模板路由知识库，按 `### <ID>` 维护 33 个在线模板分流规则并由 `validate_skill` 双向交叉校验。

## 架构决策记录（`decisions/`）

- [decisions/adr-001-single-agent-and-evidence.md](decisions/adr-001-single-agent-and-evidence.md) — ADR-001：采用单智能体自主规划 + 强证据校验替代 Java 三 Agent 编排。
- [decisions/adr-002-text-skill-and-deterministic-tools.md](decisions/adr-002-text-skill-and-deterministic-tools.md) — ADR-002：采用纯文本 `SKILL.md` + 平台确定性工具原语替代 Groovy 脚本引擎。
- [decisions/adr-003-file-store-and-git-release.md](decisions/adr-003-file-store-and-git-release.md) — ADR-003：采用文件系统 + 内部 Git 版本库 + `releases/current` 原子软链替代关系型数据库资源表。
- [decisions/adr-004-jinja2-pebble-and-tracked-list.md](decisions/adr-004-jinja2-pebble-and-tracked-list.md) — ADR-004：采用 Jinja2 沙箱对齐 Pebble 渲染语义，并以 `TrackedValue` / `TrackedList` 精确判定报告完整度。
- [decisions/adr-005-java-migration-and-bug-fixes.md](decisions/adr-005-java-migration-and-bug-fixes.md) — ADR-005：Java 生产资源自动化迁移对拍体系与二期历史缺陷主动修复决策。

## 操作指南（`guides/`）

- [guides/add-template.md](guides/add-template.md) — 新增与维护申告报告模板实操指南（字段建模、证据选型、列表列定义、Jinja2 分支与发布校验）。
- [guides/add-skill-and-api.md](guides/add-skill-and-api.md) — 新增纯文本 Skill 与声明式网关接口契约（XML / JSON）实操指南。
- [guides/dev-test-and-deploy.md](guides/dev-test-and-deploy.md) — 本地开发、测试 Fixture 隔离机制、前后端联调与 Docker 单进程部署指南。
- [guides/java-migration-and-verification.md](guides/java-migration-and-verification.md) — Java 资源迁移生成器与四层一致性验证脚本使用手册。
- [guides/troubleshooting.md](guides/troubleshooting.md) — 常见运行与治理问题排障手册（`PARTIAL`/`FAILED` 溯源、证据退回、网关异常、乐观锁冲突与登录锁定）。

## 参考速查（`reference/`）

- [reference/configuration.md](reference/configuration.md) — `Settings` 环境变量全集与运行期热更新配置项速查表。
- [reference/templates-catalog.md](reference/templates-catalog.md) — 33 个生产模板（`100`～`132`）完整目录（模板名称、字段数、列表/中间字段、关联 Skill 与入参）。
- [reference/apis-catalog.md](reference/apis-catalog.md) — 3 个内置网关接口契约（`querySMSSendInfo`、`BOSS_QryBalanceFlowLog`、`cc_pretty_num_info_query`）参数与响应速查。
- [reference/glossary.md](reference/glossary.md) — 业务领域与平台工程核心术语对照表。

## 质量审计与差异台账（`lint/`）

- [lint/known-issues.md](lint/known-issues.md) — 当前架构已知约束与工程注意事项（单进程部署、批量回归规划、Mock 静态文件边界等）。
- [lint/java-divergence.md](lint/java-divergence.md) — 与 Java 版（`pdf-agent-parse`）的行为差异全表及二期主动修复缺陷（R2 / R5 / R8 / R17 模板 `120` 与 `111`/`114`/`115` 占位符死分支 / 同名入参警告 / 字段推导治理）核查单。
- [lint/open-questions.md](lint/open-questions.md) — 待业务侧进一步确认的规则细节（含模板 `116` `受理渠道` 历史枚举分支失配、未引用 `.rule`、充值金额单位等）与后续演进议题。

## 相关页面

- [项目总览](overview.md)
- [演进时间线](timeline.md)
- [单智能体请求处理管道](architecture/request-pipeline.md)
- [嵌入式聊天选模板窗口组件剖析](components/chat-embed.md)
- [12 个纯文本 Skill 总览](skills/README.md)
