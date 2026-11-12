---
name: reminder-sms
title: 提醒短信与提醒日期
description: 模板需要“提醒短信”或“提醒日期”（活动/业务到期前下发的提醒短信正文及其发送日期）时加载。查询日期由订购短信正文中的最大合法日期决定，依赖 business-sms。两个字段来自同一条短信，只查询一次。
apis:
  - querySMSSendInfo
---

<!-- #Created By AiCoding(codex) 迁移自 Java skills/reminder-sms，二期升级采用 extract_dates + date_shift 修复活动编号误识别为日期缺陷 -->

# 提醒短信与提醒日期

## 适用场景

模板字段 `提醒短信`、`提醒日期`（如“合约到期处理类”“优惠活动到期资费恢复争议处理模板”：“我公司于{{提醒日期}}下发活动到期提醒短信，内容：{{提醒短信}}”）。两个字段**必须来自同一条短信记录**。

## 依赖与入参

| 来源 | 要求 |
|---|---|
| 字段 `订购短信` | 必须先有结论；没有时先 `load_skill("business-sms")`；未传截止日期入参且 `订购短信` 为 `not_found` 时直接跳过查询，两个字段提交 `not_found` |
| 入参 手机号码 | 必填（11 位手机号，缺失时不调用接口，两个字段 `not_found`） |
| 入参 创建时间 | 用于给“M月d日”这类不带年份的日期补年份，以及在订购短信无合法日期时作为回退查询日 |
| 入参 deadlineDate（或模板定义的截止日期入参，可选） | 若模板提供并传入非空值，优先解析该日期作为查询日期 |

## 第 1 步：用 `extract_dates` 确定查询日期（严禁手算或使用宽松正则）

1. 若入参中传入了非空的 `deadlineDate`（或模板定义的截止日期入参），优先调用 `extract_dates(text=deadlineDate, defaultYear=创建时间)`，当返回 `count > 0` 时直接取返回的 `max`（8 位 `yyyyMMdd`）作为目标日期。
2. 否则调用确定性工具 `extract_dates(text=订购短信, defaultYear=创建时间)` 提取严格经日历合法性校验的日期：
   - 工具只识别真实合法日期（`yyyy年M月d日/号`、`yyyy-M-d`/`yyyy/M/d`/`yyyy.M.d`、独立 8 位 `yyyyMMdd`，以及用 `创建时间` 补全年份的 `M月d日/号`），**绝不会**把 `（编号：25JS206149）。\n1.` 等字母数字活动编号或流水号子串误识别成日期。
   - 若返回 `count > 0`：取返回的 `max`（最大合法日期 `yyyyMMdd`）作为目标日期。
   - 若返回 `count == 0`（订购短信中无任何合法日期）：直接退回入参 `创建时间` 当天日期（下一步直接调用 `date_shift(date=创建时间, days=0)` 或 `date_range(time=创建时间, unit="day")`，支持 14 位 `yyyyMMddHHmmss`；若 `创建时间` 也无法解析出合法日期则跳过查询，两个字段提交 `not_found`）。

示例（订购短信片段）：`您已于2026年11月05日在热线渠道成功办理“XX”活动（编号：25JS206149）。\n1.活动时间：2026年12月1日00:00:00-2027年12月1日00:00:00。`
- 调用 `extract_dates(text=订购短信, defaultYear=创建时间)` → `dates=["20261105", "20261201", "20271201"]`，`max="20271201"`（活动编号 `25JS206149` 不会被误算为 `20614901`）。

## 第 2 步：用 `date_shift` 计算当天窗口并查询

1. 调用 `date_shift(date=目标日期, days=0)`（或 `date_range(time=目标日期, unit="day")`），直接使用返回的 `start`（`<目标日期>000000`）和 `end`（`<目标日期>235959`）。
2. 调用 `call_api("querySMSSendInfo", {"手机号码": 手机号码, "开始时间": start, "结束时间": end})`（若本次运行已用完全相同的参数调用过，直接复用 `resultId`）。
3. `count=0`（含“无短信记录”）→ 两个字段 `not_found`；`ok=false` → 两个字段 `not_found` 并写明失败原因。

## 第 3 步：识别

```json
{
  "resultId": "<resultId>",
  "where": [{"column": "smsContent", "op": "contains", "value": "提醒"}],
  "orderBy": {"column": "smsSendTime", "desc": true},
  "limit": 1
}
```

- 只要正文原文包含“提醒”即为候选（**不按业务名称过滤**，与 Java 一致）。
- 多条时按 `smsSendTime` 倒序取第一条。没有候选 → 两个字段 `not_found`。

## 提交要求

- `提醒短信`（`quote` 整条原样引用）：值为选中记录 `smsContent` 完整原文；`evidence` 只写 `[{"type":"api","resultId":...,"row":...,"column":"smsContent"}]`（在 `reasoning` 中说明查询日期提取过程）。
- `提醒日期`（`derive`）：同一条记录的 `smsSendTime` 调用 `format_date(value=smsSendTime, fromPattern="yyyyMMddHHmmss", toPattern="yyyy-MM-dd")`（模板字段另行定义了展示格式时按模板格式），直接使用工具输出；`evidence` 引用该 `format_date` 的 `{"type":"tool","callId":...}`、`extract_dates` / `date_shift` 的 `{"type":"tool","callId":...}`、选中记录 `{"type":"api","resultId":...,"row":...,"column":"smsSendTime"}` 以及 `{"type":"field","name":"订购短信"}`。
