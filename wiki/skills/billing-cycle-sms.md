---
title: Skill 详解：billing-cycle-sms（账期短信提醒列表）
type: skill
tags: [skill, sms, billing-cycle-sms, list-field, expand-period]
sources:
  - src/report_agent/seed/skills/billing-cycle-sms/SKILL.md
  - src/report_agent/runtime/text_tools.py
  - src/report_agent/runtime/evidence.py
updated: 2026-11-12
---

# `billing-cycle-sms`：账期短信提醒列表

<!-- #Created By AiCoding(codex) -->

`billing-cycle-sms` 服务于模板 `119`（`套餐费用争议类`），按入参 `账单`（`yyyyMM$yyyyMM`）跨越的每个自然月逐月查询短信，将客户的活动到期资费变更提醒、语音超额提醒、流量超额提醒按“月 × 类型”聚合为结构化 5 列列表字段。

## 1. 基本契约

- **产出字段**：`账期短信提醒列表`（`type: list`，`evidence: derive`，固定 5 列）：
  1. `账期月`：`yyyy年M月`（月份不补零，如 `2026年10月`）
  2. `提醒类型`：枚举 `活动到期套餐资费变更` | `语音超额提醒` | `流量超额提醒`
  3. `提醒时间`：同月同类型所有短信发送时间按正序格式化为 `yyyy年M月d日 HH时mm分ss秒`，多条用顿号 `、` 连接
  4. `提醒次数`：同月同类型短信条数（数字字符串，如 `"2"`）
  5. `短信内容`：仅 `活动到期套餐资费变更` 填写同月该类短信原文（多条按时间正序用 `\n` 连接）；两类超额提醒固定填空串 `""`
- **关联接口**：`querySMSSendInfo`（按自然月逐月调用）
- **必填入参**：`手机号码`（11 位数字）、`账单`（必须严格匹配 `^(\d{6})\$(\d{6})$`，起止月份合法且结束月不早于开始月；不合法时不调接口，直接交 `not_found`）。

## 2. 确定性工具执行流程（二期升级版）

1. **展开自然月序列与首尾窗口（`expand_period`）**：
   - 在校验 `账单` 符合 `^(\d{6})\$(\d{6})$` 且开始月份 `<=` 结束月份后，调用 `expand_period`（跨度超过两个月如 `202610$202612` 时将 `$` 替换为 `-` 传入 `expand_period(period="202610-202612")` 以展开连续闭区间），直接从返回的 `monthRanges` 中读取每个月的 `month`、`start`（当月首日 `000000`）与 `end`（当月末日 `235959`）。
2. **逐月并发查询**：
   - 对 `monthRanges` 中每个月调用 `call_api("querySMSSendInfo", {"手机号码": 手机号码, "开始时间": start, "结束时间": end})`。
   - **严格失败语义**：只要**任意一个月** `ok=False`（网络超时或非“无短信记录”的网关异常），整个字段必须提交 `status="not_found"`（不得把某月报错掩盖成无记录）；某月 `ok=True, count=0` 则属正常无短信。
3. **跨月合并筛选与按月排序聚合（`query_result(resultIds=...)`）**：
   - 仅保留 `smsSendTime` 为合法 14 位数字且前 6 位落在 `[开始月份, 结束月份]` 闭区间内的短信（可用 `query_result(resultIds=[...], where=[{"column": "smsSendTime", "op": "between", "value": 开始月份, "endValue": 结束月份, "prefixLen": 6}, ...], orderBy={"column": "smsSendTime", "desc": false}, limit=100)` 一步跨月筛选并按发送时间正序排列）；
   - 按月份升序，同月内固定按 **活动到期套餐资费变更**（同时含 `到期提醒` 和 `资费标准`） → **语音超额提醒**（含 `通话使用提醒`） → **流量超额提醒**（含 `流量使用提醒`）顺序整理（同一条短信若命中多类关键词可同时计入多类）；
   - 使用 `format_date` 将每条 `smsSendTime` 转为 `yyyy年M月d日 HH时mm分ss秒`、将 `<yyyyMM>` 转为 `yyyy年M月`。

## 3. 空列表 `found: []` vs `not_found` 提交规范

- **各月均查询成功但 0 条命中**：提交 **`status="found", value=[]`**，并在 `evidence` 中附上本次调用的 `call_api` / `expand_period` / `query_result` 的成功工具 `callId`（或接口证据），使报告渲染为空且运行状态保持 **`SUCCESS`**；
- **入参非法或任一月份网关 `ok=False`**：提交 **`status="not_found", value=None`**，当模板进入列表循环分支时由 `TrackedList` 准确标为 **`PARTIAL`**。

## 相关页面

- [11 个纯文本业务 Skill 总览](README.md)
- [qry-balance：充值流水](qry-balance.md)
- [强证据核验机制](../architecture/evidence-system.md)
- [模板模型与渲染机制](../architecture/template-and-rendering.md)
