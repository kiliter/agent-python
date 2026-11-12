---
title: Skill 详解：qry-balance（充值流水）
type: skill
tags: [skill, balance, qry-balance, list-field, expand-period, bugfix-r8]
sources:
  - src/report_agent/seed/skills/qry-balance/SKILL.md
  - src/report_agent/seed/apis/BOSS_QryBalanceFlowLog.yaml
  - src/report_agent/runtime/tools.py
  - src/report_agent/runtime/text_tools.py
updated: 2026-11-12
---

# `qry-balance`：充值流水（余额流水查询）

<!-- #Created By AiCoding(codex) -->

`qry-balance` 服务于模板 `106`（`充值争议处理通用模板`）与模板 `107`（`充值错号处理类`），按充值时间跨越的账期调用 `BOSS_QryBalanceFlowLog` 查询预付费充值流水，过滤并倒序生成 4 列原文引用列表。

## 1. 基本契约

- **产出字段**：`充值流水`（`type: list`，`evidence: quote`，固定 4 列，**全部原样取自接口列，不做日期格式化、不做金额分转元**）：
  1. `充值时间` ← `payDatetime`（如 `20260705144056`）
  2. `支付方式` ← `payTypeName`
  3. `充值金额` ← `amount`（如 `5000`）
  4. `流水号` ← `soNbr`
- **关联接口**：`BOSS_QryBalanceFlowLog`（请求头 `request_time` 由契约 `${$now}` 自动注入当前 14 位时间）
- **入参要求**（二期已清理冗余同名入参 `客户号码`）：
  - **被查号码**：按优先级依次取第一个非空入参：`充值号码` → `手机号码`（若 `extraInfo` JSON 中提供充值号码按模板入参说明配合提取），去掉非数字后必须恰好 11 位；
  - **充值时间**：入参 `充值时间`（支持 `yyyyMMdd`、`yyyyMMdd-yyyyMMdd`、`yyyyMM`、`yyyy年M月d日` 等）；无法识别出合法年月时不调接口，提交 `not_found`。

## 2. 确定性工具执行流程（二期全工具化与 R8 修复后）

1. **展开查询账期与起止日期（`expand_period`）**：
   - 调用 `expand_period(period=充值时间)`，返回 `{callId, ok, months, monthRanges, startDate, endDate, startTime, endTime}`：
     - 纯年月 `"202607"` → 自动展开为整月闭区间：`months=["202607"]`，`startDate="20260701"`，`endDate="20260731"`；
     - 单日 `"20260705"` → `months=["202607"]`，`startDate="20260705"`，`endDate="20260705"`；
     - 跨月区间 `"20260730-20260802"` → `months=["202607", "202608"]`，`startDate="20260730"`，`endDate="20260802"`。
2. **逐账期调用网关**：
   - 对 `months` 中每个账期调用 `call_api("BOSS_QryBalanceFlowLog", {"手机号码": <11位号码>, "账期": "<yyyyMM>"})`；
   - **严格失败判定**：任一账期 `ok=False`（如缺少 `resp_code` 或返回 `7003` 能力编排错误）→ 整个字段必须提交 `status="not_found"`。
3. **跨账期合并、日期区间过滤与倒序排列（一次 `query_result` 完成）**：
   - 将所有成功账期的 `resultId` 组成列表 `resultIds=["r1", "r2", ...]`，调用一次 `query_result`：
     - 使用 `{"column": "payDatetime", "op": "between", "value": startDate, "endValue": endDate, "prefixLen": 8}` 截取 `payDatetime` 前 8 位（`yyyyMMdd`）与 `[startDate, endDate]` 闭区间比较；
     - 指定 `orderBy: {"column": "payDatetime", "desc": true}`、`limit: 100`，由工具确定性完成跨账期合并与稳定倒序。

## 3. 空列表语义与二期修复的历史缺陷（R8）

- **查清无流水 vs 接口报错**：所有账期 `ok=True` 但无符合条件记录时，提交 **`status="found", value=[]`** 并附上结果为 0 行的 `query_result(total==0)` 或各账期 `call_api(count==0)` 的工具 `callId` 证据（严禁引用 `load_skill` 或非空结果集 `api` 证据），报告渲染为空且运行状态为 **`SUCCESS`**；任一账期 `ok=False` 或缺参则交 `status="not_found", value=None`，由于模板 106/107 正文直接执行 `{% for item in 充值流水 %}`，`TrackedList` 将运行状态准确判定为 **`PARTIAL`**。
- **修复 Java R8 正则回溯缺陷**：前代 Java Groovy 在过滤日期时使用 `(20\d{2})\D*(\d{1,2})\D*(\d{1,2})`，当上游传入纯年月 `"202607"` 时，正则回溯将其强行拆解成 `2026` 年 `0` 月 `7` 日（`"20260007"`），把该月所有真实流水（`202607xx`）全部当成区间外记录误删。二期由 `expand_period` 将纯年月自动展开为当月首尾真实日期（`20260701`～`20260731`），彻底修复了纯账期查询查不出流水的缺陷。

## 相关页面

- [11 个纯文本业务 Skill 总览](README.md)
- [billing-cycle-sms：账期短信提醒列表](billing-cycle-sms.md)
- [3 个内置网关接口契约速查](../reference/apis-catalog.md)
- [Java 行为差异与二期主动修复台账](../lint/java-divergence.md)
