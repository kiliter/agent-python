---
title: 常见故障排查手册
type: guide
tags: [guide, troubleshooting, partial, failed, evidence, gateway, auth]
sources:
  - src/report_agent/runtime/runner.py
  - src/report_agent/runtime/evidence.py
  - src/report_agent/gateway/unified_xml.py
  - src/report_agent/api/auth.py
  - src/report_agent/store/drafts.py
updated: 2026-11-12
---

# 常见故障排查手册

<!-- #Created By AiCoding(codex) -->

本手册按工作台与线上高频观测现象归类，提供快速定位根因与修复路径的操作清单。

## 1. 报告运行状态为 `PARTIAL`（部分完成）

**现象**：接口返回 `status: "PARTIAL"`，报告已生成但带有 `{{字段名}}` 占位符、默认值或缺失某段列表。

**排查步骤**：
1. 打开工作台「运行记录（`/runs`）」查看该 `runId` 的 **`missingShown` 数组**——数组里列出的就是**真正出现在报告已命中分支里、但最终状态为 `not_found` 的罪魁字段**。
2. 在「字段结果表」中点开该字段查看 `reasoning` 与标签：
   - **带有 `validationFailed: true`（证据校验未通过降级）**：切到「时间线」看红色 `report_rejected` / `report_degraded` 事件：
     - 若报“未在所引用的原文中逐字出现”：检查模型是否对 `quote` 字段自己改写了日期格式却没调用 `format_date`，或该字段实际属于归纳总结却被误配成了 `evidence: quote`（应改为 `derive`）；
     - 若报“上游字段证据校验未通过，级联降级”：先修上游字段（通常是 `订购短信`）。
   - **未触发校验退回，模型主动交了 `not_found`**：
     - 检查入参是否缺失（如未传 `业务月份`、`账单` 格式不是 `yyyyMM$yyyyMM`）；
     - 检查「接口结果」页签是否有某次调用 `ok: false`（例如 `BOSS_QryBalanceFlowLog` 返回 `resp_code=7003`）；
     - 若列表字段（如 `充值流水`）所有接口都 `ok: true` 只是 0 条记录，模型却误交了 `not_found`：检查对应 `SKILL.md` 是否明确要求“查询成功但 0 条记录时提交 `status="found", value=[]` 并附成功调用证据”。

## 2. 报告运行状态为 `FAILED`（运行失败）

**现象**：`status: "FAILED"`，`report` 为空，`error` 非空。

| 常见 `error` 信息 | 根因 | 解决方案 |
|-------------------|------|----------|
| `TimeoutError` / 连接超时 | 下游大模型单轮响应超过 `LLM_TIMEOUT_S`（默认 120s），或整次工单执行超过 `AGENT_RUN_TIMEOUT_S`（默认 600s） | 在「系统设置 -> 运行期配置」适当调大 `llmTimeoutS` / `agentRunTimeoutS`，或检查大模型服务端负载 |
| `UsageLimitExceeded`（超出请求轮次或工具调用上限） | 模型在某个工具报错上死循环重试，或跨十几个账期逐月查询超过了 `AGENT_REQUEST_LIMIT`（25）/ `AGENT_TOOL_CALLS_LIMIT`（40） | 查看时间线定位重复调用的工具；若属正常大跨度账单，可在运行期配置调高上限 |
| 服务端不支持 `json_schema` / `response_format` 报错 | 当前私有化模型网关不支持 `AGENT_OUTPUT_MODE=native` 与 Tool Calling 同时开启 | 在运行期配置或 `.env` 中将 `AGENT_OUTPUT_MODE` 切换为默认的 `tool`（使用 `submit_report` 工具交卷） |

## 3. 网关拨测或线上调用接口失败

- **`GATEWAY_MODE=live` 下报错 `GATEWAY_URL 未配置` 或连接拒绝**：进入「系统设置 -> 运行期配置」核对 `gatewayUrl`、`gatewayAppId` 与 `gatewayAccessToken`（平台会自动在末尾拼接 `/openapi_3`）；若在本地无内网环境调试，将 `gatewayMode` 切回 `mock`。
- **网关返回报文正常，但平台判为 `ok=false`**：
  - 打开该接口 YAML 的 `response` 段，核对返回码路径（如短信与余额流水在 `operation_out.response.resp_code`，而靓号接口在 `operation_out.content.ret_code`）；
  - 若网关在“查无记录”时返回非 `0000` 错误码（如短信接口返回 `resp_code=1, resp_desc="...无短信记录!"`），必须在 `response.noData` 中配置匹配规则，否则会被 `success` 当成接口故障拦截。
- **报 `XML 中禁止使用 DOCTYPE / ENTITY`**：外部网关可能返回了非业务 XML（例如 Nginx/防火墙拦截返回的 HTML `<!DOCTYPE html>` 错误页），检查网关代理地址与鉴权头。

## 4. 工作台操作常见报错

- **保存草稿返回 `409 DRAFT_CONFLICT`**：另一位维护人员在你打开页面后保存过同一资源的草稿（乐观锁 `revision` 不匹配）。先复制备份本地修改，刷新工作台拉取最新草稿后再合并保存。
- **删除字段返回 `400 FIELD_IN_USE`**：`body.md.j2` 正文中仍存在 `{{该字段名}}` 或 `{% if 该字段名 %}` 引用。先从正文中删掉引用再删字段（或确认无误后使用强制删除）。
- **点击发布按钮置灰或返回 `422 PUBLISH_BLOCKED`**：发布预检存在 `error`（如删除了仍被某个线上模板引用的 Skill 或 API，或正文中写了未声明的 `{{变量}}`），按弹窗列出的错误项逐条修复即可。
- **登录返回 `429 LOGIN_LOCKED`**：同一账号连续输错密码满 5 次触发防爆破保护，等待 5 分钟自动解锁，或由运维执行 `uv run report-agent user add --username <账号> --password '<新密码>'` 重置口令。

## 相关页面

- [单智能体请求处理管道](../architecture/request-pipeline.md)
- [强证据核验机制](../architecture/evidence-system.md)
- [网关契约与连接器组件剖析](../components/gateway-and-api-contract.md)
- [本地开发、测试与部署指南](dev-test-and-deploy.md)
