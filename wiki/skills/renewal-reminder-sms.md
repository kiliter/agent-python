---
title: Skill 详解：renewal-reminder-sms（续约提醒短信）
type: skill
tags: [skill, sms, renewal-reminder-sms, date-shift, anyOf]
sources:
  - src/report_agent/seed/skills/renewal-reminder-sms/SKILL.md
  - src/report_agent/runtime/tools.py
  - src/report_agent/runtime/text_tools.py
updated: 2026-11-12
---

# `renewal-reminder-sms`：续约提醒短信

<!-- #Created By AiCoding(codex) -->

`renewal-reminder-sms` 服务于模板 `112`（`合约延续争议类`），围绕 `订购短信` 中的活动到期基准日发起一次前后各 31 天（共 63 天）的大窗口短信查询，同时核查并填报 **6 个续约相关字段**。

## 1. 基本契约

- **产出字段（共 6 个）**：
  1. `续约提醒类型`（`enum`：`到期延续` | `到期结束`，`evidence: derive`）
  2. `到期续约提醒时间`（`date`：`yyyy-MM-dd`，`evidence: derive`）
  3. `到期续约提醒短信内容`（`string`，`evidence: quote`，`quoteWhole: true`）
  4. `是否续约成功`（`enum`：找到续约成功提醒时填 `是`，**未找到时必须提交 `not_found`，严禁臆断填“否”**，`evidence: derive`）
  5. `续约成功提醒时间`（`date`：`yyyy-MM-dd`，`evidence: derive`）
  6. `续约成功提醒短信内容`（`string`，`evidence: quote`，`quoteWhole: true`）
- **关联接口**：`querySMSSendInfo`
- **上游依赖**：字段 `订购短信`（`not_found` 时 6 个字段全部交 `not_found`）
- **入参要求**：`手机号码`（11 位数字）、`业务名称`（可空，空时仅靠活动编号匹配）、`创建时间`（补年份用）、`deadlineDate`（可选）。

## 2. 确定性工具执行流程（二期全工具化升级）

1. **提取到期基准日（`extract_dates`）**：
   - 调用 `extract_dates(text=订购短信, defaultYear=创建时间)`（若传入非空 `deadlineDate` 则一并调用后取两者最大日期），取返回的 `max`（8 位 `yyyyMMdd`）作为到期基准日；若无合法日期则 6 个字段全部提交 `not_found`。
2. **计算 ±31 天跨月查询窗口（`date_shift`）**：
   - 调用 `date_shift(date=max_date, days=-31, endDays=31)`，由平台按真实日历（自动处理大小月、跨年与闰年）算出 63 天窗口的 `start`（`yyyyMMdd000000`）与 `end`（`yyyyMMdd235959`）；
   - 调用一次 `call_api("querySMSSendInfo", {"手机号码": 手机号码, "开始时间": start, "结束时间": end})`。
3. **提取活动编号并一次完成 OR 过滤（`regex_extract` + `query_result(anyOf=...)`）**：
   - 调用 `regex_extract(pattern=r"[（(]编号[:：]\s*([A-Za-z0-9_-]+)[）)]", text=订购短信)`（未带括号时用 `r"编号\s*[:：]?\s*([A-Za-z0-9_-]+)"`）取出全部活动编号；
   - 构造 `anyOf` 条件数组（`业务名称` 非空时加入 `normalizedContains(smsContent, 业务名称)`，每个活动编号加入 `normalizedContains(smsContent, 编号)`），一次调用 `query_result(resultId=..., anyOf=[...], orderBy={"column": "smsSendTime", "desc": true}, limit=100)` 锁定全部属于本次业务的短信集合。
4. **双轨分类判定**：
   - **A. 续约成功提醒**：在本次业务短信集合中匹配包含 `【续约成功提醒】` 或 `[续约成功提醒]` 的最新一条记录；
   - **B. 到期提醒**：在本次业务短信集合中按优先级判定每条记录类型后取最新一条有类型的候选：
     1. 含 `【续约确认提醒】` 或 `[续约确认提醒]` → `到期延续`；
     2. 含 `【到期提醒】` 或 `[到期提醒]`：
        - 先判结束词（`次月起失效` / `到期自动关闭` / `活动结束后自动失效` / `到期后自动失效` / `不再延续`）→ `到期结束`（结束词优先）；
        - 再判延续词（`下月继续生效` / `继续生效` / `自动延续` / `自动续订` / `自动续展`）→ `到期延续`。
5. **交叉覆盖与格式化输出**：
   - 若存在 **A（续约成功提醒）**：`是否续约成功 = "是"`，且**无论 B 原先判为何种类型，`续约提醒类型` 强制覆盖为 `"到期延续"`**（续约成功是最终事实）；
   - 原文引用字段（`到期续约提醒短信内容`、`续约成功提醒短信内容`）`evidence` 仅填对应记录 `smsContent` 的 `api` 证据；两个时间推导字段调用 `format_date(..., toPattern="yyyy-MM-dd")` 转换并附上 `format_date` 的 `callId`、`smsSendTime` 列与 `{"type": "field", "name": "订购短信"}`；两个枚举推导字段附上 `smsContent` 列、工具 `callId` 与 `{"type": "field", "name": "订购短信"}`。

## 相关页面

- [11 个纯文本业务 Skill 总览](README.md)
- [business-sms：订购短信](business-sms.md)
- [reminder-sms：提醒短信与提醒日期](reminder-sms.md)
- [确定性平台工具设计](../architecture/deterministic-tools.md)
