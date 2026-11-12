---
name: qry-balance
title: 充值流水（余额流水查询）
description: 充值争议类模板需要“充值流水”（列表字段，每行：充值时间、支付方式、充值金额、流水号）时加载。按充值时间展开账期与起止日期查询预付费充值余额流水。
apis:
  - BOSS_QryBalanceFlowLog
---

<!-- #Created By AiCoding(codex) 迁移自 Java skills/qry-balance，二期升级采用 expand_period + query_result(resultIds, between) + 列表空值 found/[] 语义，修复纯年月 202607 回溯缺陷与客户号码同名入参警告 -->

# 充值流水

## 适用场景

列表字段 `充值流水`（`type: list`），模板用 `{% for item in 充值流水 %}…{{item.充值时间}}通过{{item.支付方式}}充值{{item.充值金额}}元（订单号：{{item.流水号}}）…{% endfor %}` 循环。

每一行固定 4 列（列名必须完全一致），**全部按接口原文取值，不做日期格式化、不做金额分转元或任何转换**：

| 列 | 取自接口列 |
|---|---|
| 充值时间 | `payDatetime`（原值，如 `20260705144056`） |
| 支付方式 | `payTypeName` |
| 充值金额 | `amount`（原值，如 `5000`） |
| 流水号 | `soNbr` |

## 需要的入参

| 入参 | 要求 |
|---|---|
| 查询号码 | `充值号码`（或 `extraInfo` 中的 `充值号码`）有值时优先取 `充值号码`，否则取 `手机号码`（**不读取名为“客户号码”的入参**）；去掉非数字后必须恰好 11 位 |
| 充值时间 | 优先取入参 `充值时间`；为空时按模板规则从 `extraInfo` 中提取 `办理日期`。支持 `yyyyMMdd`、纯年月 `yyyyMM`（如 `202607`）、`yyyy-MM-dd`、`yyyy年M月d日`、日期/年月区间（如 `20260705-20260808`、`202607-202609`）等 |

任一缺失、查询号码不是 11 位数字，或充值时间无法通过 `expand_period` 解析出合法账期时，不要调用接口，字段提交 `status="not_found"`、`value=null`。

## 第 1 步：用 `expand_period` 展开查询账期与起止日期（严禁手算正则）

调用确定性工具 `expand_period(period=<充值时间文本>)`：
- 返回 `{callId, ok, months, monthRanges, startDate, endDate, startTime, endTime}`。
- 例如：
  - 纯年月 `"202607"` → 自动展开为整月：`months=["202607"]`，`startDate="20260701"`，`endDate="20260731"`（绝不会出现旧版正则回溯成 `20260007` 的缺陷）；
  - 单日 `"20260705"` → `months=["202607"]`，`startDate="20260705"`，`endDate="20260705"`；
  - 跨月区间 `"20260730-20260802"` → `months=["202607", "202608"]`，`startDate="20260730"`，`endDate="20260802"`。
- 若 `ok=false`，不调用接口，字段提交 `status="not_found"`、`value=null` 并写明原因。

## 第 2 步：逐账期查询接口

对 `months` 中的每个账期 `<yyyyMM>` 调用 `call_api("BOSS_QryBalanceFlowLog", {"手机号码": <11位查询号码>, "账期": "<yyyyMM>"})`，互不依赖的账期可并行发出。

- 任一账期 `ok=false`（HTTP 失败、缺少 `resp_code`、`resp_code≠0000` 如 `7003`）→ 整个字段提交 `status="not_found"`、`value=null`，写明失败账期与返回码/描述（**不得**把接口报错当作无流水）。
- 业务成功但 `count=0` → 该账期没有流水，继续合并其余账期。

## 第 3 步：用 `query_result` 一次完成跨账期合并、日期区间过滤与倒序排列

收集第 2 步全部成功账期的 `resultId` 列表，调用一次 `query_result`：

```json
{
  "resultIds": ["<r1>", "<r2>"],
  "where": [
    {
      "column": "payDatetime",
      "op": "between",
      "value": "<expand_period返回的startDate>",
      "endValue": "<expand_period返回的endDate>",
      "prefixLen": 8
    }
  ],
  "orderBy": {"column": "payDatetime", "desc": true},
  "limit": 100,
  "columns": ["payDatetime", "payTypeName", "amount", "soNbr"]
}
```

- `prefixLen: 8` 会自动截取 `payDatetime` 前 8 位（`yyyyMMdd`）与 `[startDate, endDate]` 闭区间比较，`orderBy` 按 `payDatetime` 倒序排列，多账期返回的每行自带对应的 `resultId` 和 `row`。
- 若接口中存在极少数 `payDatetime` 为空或不足 8 位数字的异常记录需要核实，也可不带 `where` 查看，但正常 14 位 `payDatetime` 统一以上述 `between` + `prefixLen=8` 结果为准。

## 提交要求

- **有命中流水时（`rows` 非空）**：
  - 提交 `status="found"`，`value` 是行对象数组，每行四个键：`充值时间`、`支付方式`、`充值金额`、`流水号`，值分别与该记录的 `payDatetime`、`payTypeName`、`amount`、`soNbr` **逐字完全一致**。
  - `evidence` 为字段级列表：每一行引用其来源接口记录 `{"type":"api","resultId": row["resultId"], "row": row["row"], "column": "payDatetime"}`（平台按整条记录核对该行全部单元格）。
- **所有账期查询成功（`ok=true`）但命中 0 条流水时（各账期 `count=0` 或区间筛选后 `total=0`）**：
  - **必须提交 `status="found"`、`value=[]`**，并在 `evidence` 中附上结果为 0 行的查询证据：
    - 若原接口返回 `count > 0` 但按日期区间筛选后 `total == 0`（或跨账期汇总 0 行），**必须**引用第 3 步 `total == 0` 的 `query_result` 返回的 `{"type":"tool","callId":"..."}`；
    - 若原接口直接返回 `count == 0`，可引用该 `call_api` 返回的 `{"type":"tool","callId":"..."}`（或 `count == 0` 结果的 `{"type":"api","resultId":"...","row":0,"column":""}`），以及第 3 步 `total == 0` 的 `query_result` `callId`；
    - 严禁在原接口 `count > 0` 时引用 `type="api"` 充当空列表证据，也严禁引用 `load_skill` 的 `callId`！`reasoning` 写明“各账期接口查询成功，指定充值时间范围内无流水记录”。
- **仅当缺少必要入参、充值时间无法解析，或任一账期接口调用失败（`ok=false`）时**：
  - 提交 `status="not_found"`、`value=null`。
