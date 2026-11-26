---
title: Skill 详解：template-router（聊天与自动填报模板路由）
type: skill
tags: [skill, template-router, chat, routing, auto-route, validation]
sources:
  - src/report_agent/seed/skills/template-router/SKILL.md
  - src/report_agent/domain/skill.py
  - src/report_agent/domain/resources.py
  - src/report_agent/runtime/router.py
  - src/report_agent/runtime/runner.py
  - src/report_agent/chat/agent.py
updated: 2026-11-26
---

# `template-router`：聊天与自动填报模板路由

<!-- #Created By AiCoding(codex) -->

`template-router` 是平台第 12 个内置纯文本 Skill，采用 `scope: chat` 作用域（未显式声明时按标识自动兼容为 `chat`），同时服务于两类模板路由场景：① 嵌入式聊天窗口路由智能体（`ChatAgent`）的交互式选模板推荐；② 上游填报接口（`POST /api/v1/reports`、`/reports/stream`、`/reports/composite`）未传 `templateId` 时的无状态自动模板路由器（`TemplateRouter`）。它将全部 33 个在线生产模板（`100`～`132`）的适用场景、典型投诉特征、关键入参与相近模板辨析沉淀为可热发布的 `SKILL.md` 与分级子文档，遵循平台「零业务硬编码」原则。

## 1. 基本契约与职责边界

- **加载主体**：由 `src/report_agent/chat/agent.py#ChatAgent` 与 `src/report_agent/runtime/router.py#TemplateRouter` 共同复用的只读路由工具（`load_skill`、`list_templates`、`get_template`）加载（默认优先加载 `template-router`）；单模板填报执行智能体（`AgentRunner` 的填报阶段）仍自动排除所有 `scope: chat` 技能，确保路由知识不污染填报上下文。
- **网关隔离**：frontmatter 声明 `scope: chat` 与 `apis: []`，不关联也不调用任何外部业务网关接口。
- **两类消费模式的决策边界**：
  - **交互式聊天选模板（`ChatAgent`）**：根据上游传入的 `inputs`（如 `业务名称`、`手机号码`、账期/违约金等）与 `document`（电子协议/工单正文）给出最多 3 个候选模板推荐（`RecommendPick{templateId, reason, level}`，匹配度分 `高` / `中` / `低`），并在客户描述模糊时通过辨析要点引导补充信息，而非盲目启动填报。
  - **无模板自动路由填报（`TemplateRouter`）**：在单次请求锁定的同一份 `(rev, ResourceSet)` 快照上先加载路由规则并产出最多 3 个候选；为满足上游自动化直通要求，采用**最高置信度优先且不阻塞**原则——在所有有效在线候选中按置信度（`高 > 中 > 低`）稳定排序，始终选用置信度最高的模板直接进入强证据填报管道（即便最高仅为 `低` 也不阻塞运行）。仅当无可用在线模板、模型未产出任何有效在线候选或路由调用异常时返回 `422 TEMPLATE_ROUTE_FAILED`（不写入 `RunStore`）；命中模板但缺少必填入参时返回 `400 INVALID_INPUT` 并附带已命中的 `templateId`、`templateName` 与 `routing`（同样不写入 `RunStore`）。

## 2. 分层目录结构与 `### <ID>` 章节约定

`src/report_agent/seed/skills/template-router/` 采用 **L1 主路由索引 + L2 子目录按需懒加载** 分层结构，`ChatAgent` 与 `TemplateRouter` 均通过 `load_skill` 按需加载，避免单次将 33 个模板全部塞入上下文：

1. **L1 主文档 `SKILL.md`**（约 60 行精简总控）：
   - 强特征专属入参直达规则（`充值号码`/`充值时间`、`账单`、`安装地址`、`deadlineDate`）；
   - 6 大业务族总览与相对链接索引表；
   - 置信度（`高`/`中`/`低`）与最多 3 个推荐输出要求。
2. **L2 分类细则子文档 `references/*.md`（6 篇，共覆盖 100～132 全部 33 个模板）**：
   - `references/order-and-marketing.md`：业务办理与营销宣传族（100～105、123、126～130，12 个）
   - `references/contract-and-penalty.md`：合约解约、续约与违约金族（108～115，8 个）
   - `references/plan-and-traffic.md`：套餐变更、账单与流量族（117～119、124、125，5 个）
   - `references/recharge.md`：话费充值与错充族（106、107，2 个）
   - `references/broadband.md`：宽带开户、续约与押金族（120、121，2 个）
   - `references/special-services.md`：增值业务、携转与过户/靓号专项族（116、122、131、132，4 个）
3. **固定三级标题格式**：每个在线模板在所属子文档（或 `SKILL.md`）中均使用以 `### <模板ID>` 开头的 Markdown 三级标题登记（匹配正则 `src/report_agent/domain/resources.py#_ROUTER_TPL_HEADING_RE = r"^###\s+(\d{1,10})\b"`），`validate_skill` 自动跨 `SKILL.md` 与所有子文档扫描并校验相对链接可达性。

## 3. 发布门禁交叉校验规则（`domain/resources.py`）

为防止模板新增、下线或编辑后路由知识库与线上模板集合脱节，`validate_skill` 与 `validate_template` 对 `ROUTER_SKILL_ID = "template-router"` 实施四项双向静态校验：

| 校验代码 | 级别 | 触发位置与判定条件 | 治理目的 |
|----------|------|--------------------|----------|
| `ROUTER_SKILL_HAS_APIS` | `error` | `template-router` 的 frontmatter `apis` 非空 | 严禁模板路由 Skill 绑定外部网关接口，阻断错误发布 |
| `ROUTER_TEMPLATE_NOT_FOUND` | `error` | `template-router` 正文 `### <ID>` 引用的模板在当前 `ResourceSet` 中不存在，或处于已下线（`tpl.offline == True`）状态 | 阻断路由说明指向幽灵模板或已下线模板（下线某模板时需同步从路由清单移除或更新） |
| `ROUTER_TEMPLATE_UNCOVERED` | `warning` | 当前 `ResourceSet` 中存在未下线的在线模板（`not tpl.offline`），其 ID 未出现在 `template-router` 的任何 `### <ID>` 章节中 | 新增或恢复上线模板时主动提醒维护人员补充路由规则；内置生产 `seed/` 覆盖全部 `100`～`132` 共 33 个模板，保持 `0 error / 0 warning` |
| `ROUTER_SKILL_IN_TEMPLATE` | `warning` | 任意填报模板 `template.yaml` 的 `skills` 列表包含了 `template-router` | 提示 `template-router` 仅用于聊天选模板与前置自动路由，不应挂载到单模板填报工作区 |

> **测试夹具兼容**：若某个最小测试资源集（如单元测试使用的 `tests/fixtures/seed/`）未包含 `template-router` 目录，`validate_all` 不会报任何缺失错误或警告；同时 `ChatAgent` 与 `TemplateRouter` 在未配置 `template-router` 时均会自动优雅回退，改用 `list_templates` + `get_template` 检索在线模板。

## 相关页面

- [12 个纯文本 Skill 总览](README.md)
- [单智能体请求处理管道](../architecture/request-pipeline.md)
- [FastAPI 路由与鉴权组件剖析](../components/api-and-auth.md)
- [嵌入式聊天选模板窗口组件剖析](../components/chat-embed.md)
- [33 个生产模板完整清单](../reference/templates-catalog.md)
- [新增纯文本 Skill 与网关契约实操指南](../guides/add-skill-and-api.md)
