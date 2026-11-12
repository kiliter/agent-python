---
title: Skill 详解：template-router（聊天模板路由）
type: skill
tags: [skill, template-router, chat, routing, validation]
sources:
  - src/report_agent/seed/skills/template-router/SKILL.md
  - src/report_agent/domain/resources.py
  - src/report_agent/chat/agent.py
updated: 2026-11-12
---

# `template-router`：聊天模板路由

<!-- #Created By AiCoding(codex) -->

`template-router` 是平台第 12 个内置纯文本 Skill，也是**唯一专供嵌入式聊天窗口路由智能体（`ChatAgent`）使用的模板分流知识库**。它将全部 33 个在线生产模板（`100`～`132`）的适用场景、典型投诉特征、关键入参与相近模板辨析沉淀为可热发布的 `SKILL.md`，遵循平台「零业务硬编码」原则。

## 1. 基本契约与职责边界

- **加载主体**：仅由 `src/report_agent/chat/agent.py` 中的聊天路由智能体通过只读工具 `load_skill("template-router")` 加载；填报执行智能体（`AgentRunner`）不加载该 Skill。
- **网关隔离**：frontmatter 固定声明 `apis: []`，不关联也不调用任何外部业务网关接口。
- **输出目标**：指导 `ChatAgent` 根据上游传入的 `inputs`（如 `业务名称`、`手机号码`、账期/违约金等）与 `document`（电子协议/工单正文）给出最多 3 个候选模板推荐（`RecommendPick{templateId, reason, level}`，匹配度分 `高` / `中` / `低`），并在客户描述模糊时通过辨析要点引导补充信息，而非盲目启动填报。

## 2. 文档结构与 `### <ID>` 章节约定

`src/report_agent/seed/skills/template-router/SKILL.md` 由两部分组成：

1. **路由判定总则与模板族辨析**：先归纳各大争议族的分流决策树——包括业务办理争议族（`100`/`101`/`102`/`103`/`104`/`123`）、合约解约与违约金族（`108`～`115`）、套餐变更与资费争议族（`117`/`118`/`119`）、交费充值族（`106`/`107`）、宽带装移机与押金族（`120`/`121`）、流量超套与封顶族（`124`/`125`）、营销宣传与优惠到期族（`105`/`126`～`130`），以及增值业务（`116`）、携号转网（`122`）、过户（`131`）、靓号（`132`）专项模板。
2. **全量在线模板清单（固定三级标题格式）**：每个在线模板必须使用以 `### <模板ID>` 开头的 Markdown 三级标题登记（匹配正则 `src/report_agent/domain/resources.py#_ROUTER_TPL_HEADING_RE = r"^###\s+(\d{1,10})\b"`），例如：
   ```markdown
   ### 101 业务办理争议类
   - 适用场景：...
   - 典型特征/关键词：...
   - 关键入参：...
   - 相近模板区分：...
   ```

## 3. 发布门禁交叉校验规则（`domain/resources.py`）

为防止模板新增、下线或编辑后路由知识库与线上模板集合脱节，`validate_skill` 与 `validate_template` 对 `ROUTER_SKILL_ID = "template-router"` 实施四项双向静态校验：

| 校验代码 | 级别 | 触发位置与判定条件 | 治理目的 |
|----------|------|--------------------|----------|
| `ROUTER_SKILL_HAS_APIS` | `error` | `template-router` 的 frontmatter `apis` 非空 | 严禁聊天路由 Skill 绑定外部网关接口，阻断错误发布 |
| `ROUTER_TEMPLATE_NOT_FOUND` | `error` | `template-router` 正文 `### <ID>` 引用的模板在当前 `ResourceSet` 中不存在，或处于已下线（`tpl.offline == True`）状态 | 阻断路由说明指向幽灵模板或已下线模板（下线某模板时需同步从路由清单移除或更新） |
| `ROUTER_TEMPLATE_UNCOVERED` | `warning` | 当前 `ResourceSet` 中存在未下线的在线模板（`not tpl.offline`），其 ID 未出现在 `template-router` 的任何 `### <ID>` 章节中 | 新增或恢复上线模板时主动提醒维护人员补充路由规则；内置生产 `seed/` 覆盖全部 `100`～`132` 共 33 个模板，保持 `0 error / 0 warning` |
| `ROUTER_SKILL_IN_TEMPLATE` | `warning` | 任意填报模板 `template.yaml` 的 `skills` 列表包含了 `template-router` | 提示 `template-router` 仅用于聊天选模板，不应挂载到单模板填报工作区 |

> **测试夹具兼容**：若某个最小测试资源集（如单元测试使用的 `tests/fixtures/seed/`）未包含 `template-router` 目录，`validate_all` 不会报任何缺失错误或警告；同时 `ChatAgent` 的 `load_skill` 工具在未配置 `template-router` 时会自动优雅回退，提示模型改用 `list_templates` 检索在线模板。

## 相关页面

- [12 个纯文本 Skill 总览](README.md)
- [嵌入式聊天选模板窗口组件剖析](../components/chat-embed.md)
- [33 个生产模板完整清单](../reference/templates-catalog.md)
- [新增纯文本 Skill 与网关契约实操指南](../guides/add-skill-and-api.md)
