---
title: Skill 详解：reminder-sms（提醒短信与提醒日期）
type: skill
tags: [skill, sms, reminder-sms, extract-dates, bugfix-r2]
sources:
  - src/report_agent/seed/skills/reminder-sms/SKILL.md
  - src/report_agent/runtime/text_tools.py
updated: 2026-11-12
---

# `reminder-sms`：提醒短信与提醒日期

<!-- #Created By AiCoding(codex) -->

`reminder-sms` 服务于合约到期、宽带续约及优惠到期资费恢复等模板（`105`、`108`、`120`、`129`），根据 `订购短信` 正文中注明的活动最大截止日期，查询到期当天系统下发的提醒短信正文及发送日期。

## 1. 基本契约

- **产出字段**（两个字段必须来自**同一条**短信记录）：
  - `提醒短信`（`type: string`，`evidence: quote`，`quoteWhole: true`）
  - `提醒日期`（`type: date`，默认展示格式 `yyyy-MM-dd`，`evidence: derive`）
- **关联接口**：`querySMSSendInfo`
- **上游依赖**：字段 `订购短信`（未传截止日期入参且 `订购短信` 为 `not_found` 时直接跳过，两字段均交 `not_found`）
- **入参要求**：`手机号码`（必填）、`创建时间`（用于给不带年份的 `M月d日` 补齐年份，并在订购短信无合法日期时作为回退查询日）、`deadlineDate`（可选到期日入参，非空时优先采用）。

## 2. 确定性工具执行流程（二期修复 R2 后）

1. **提取目标查询日期（`extract_dates`）**：
   - 若传入了非空的 `deadlineDate`（或模板定义的截止日期入参），优先调用 `extract_dates(text=deadlineDate, defaultYear=创建时间)`，当 `count > 0` 时取返回的 `max`（8 位 `yyyyMMdd`）；
   - 否则调用 `extract_dates(text=订购短信, defaultYear=创建时间)`，当 `count > 0` 时取返回的 `max`（最大合法日期 `yyyyMMdd`）；
   - 若返回 `count == 0`（订购短信中无任何合法日期），回退使用入参 `创建时间` 当天日期（若 `创建时间` 也无法解析出合法日期则跳过查询，提交 `not_found`）。
2. **计算当天查询窗口（`date_shift`）**：
   - 调用 `date_shift(date=目标日期, days=0)`（或 `date_range(time=目标日期, unit="day")`）得到 `<目标日期>000000` ～ `<目标日期>235959`；
   - 调用 `call_api("querySMSSendInfo", {"手机号码": 手机号码, "开始时间": start, "结束时间": end})`（同参数已查过时复用 `resultId`）。
3. **筛选“提醒”短信**：
   ```json
   {
     "resultId": "<resultId>",
     "where": [{"column": "smsContent", "op": "contains", "value": "提醒"}],
     "orderBy": {"column": "smsSendTime", "desc": true},
     "limit": 1
   }
   ```
   - 只要正文原文包含“提醒”即命中（不按业务名称二次过滤，与业务规则一致），按 `smsSendTime` 倒序取最新一条。
4. **格式化日期并提交**：
   - `提醒短信`（`quote`）：值为命中记录 `smsContent` 完整原文，`evidence` 仅填 `[{"type":"api","resultId":...,"row":...,"column":"smsContent"}]`；
   - `提醒日期`（`derive`）：调用 `format_date(value=smsSendTime, fromPattern="yyyyMMddHHmmss", toPattern="yyyy-MM-dd")`（若模板字段声明了特定展示格式则按模板格式），直接使用工具输出，`evidence` 引用 `format_date` / `extract_dates` / `date_shift` 的 `callId`、选中记录 `smsSendTime` 列及 `{"type":"field","name":"订购短信"}`。

## 3. 二期主动修复的前代 Java 缺陷（R2）

在前代 Java Groovy 脚本中，规则 2 使用了极度宽松且无日历校验的正则 `(\d{4})\D{0,3}(\d{1,2})\D{0,3}(\d{1,2})`。由于现网几乎每条订购短信都形如 `（编号：25JS206149）。\n1.活动时间：2026年12月1日-2027年12月1日`，该宽松正则会把编号末尾加序号 `206149）。\n1` 拆解为 **2061 年 49 月 01 日（`20614901`）**，在按字符串比大小时压过真实的 `20271201`，导致网关去查 `20614901000000` 而永远查不到提醒短信。

二期改用平台确定性工具 `extract_dates`（严格分隔符 + 真实日历校验）后，直接精准锁定 `20271201`，彻底根治了该线上顽疾。

## 相关页面

- [11 个纯文本业务 Skill 总览](README.md)
- [business-sms：订购短信](business-sms.md)
- [renewal-reminder-sms：续约提醒短信](renewal-reminder-sms.md)
- [Java 行为差异与二期主动修复台账](../lint/java-divergence.md)
