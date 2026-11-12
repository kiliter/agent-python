---
title: Skill 详解：pretty-number-info（靓号信息）
type: skill
tags: [skill, pretty-number, cc_pretty_num_info_query, bugfix-r5]
sources:
  - src/report_agent/seed/skills/pretty-number-info/SKILL.md
  - src/report_agent/seed/apis/cc_pretty_num_info_query.yaml
updated: 2026-11-12
---

# `pretty-number-info`：靓号信息

<!-- #Created By AiCoding(codex) -->

`pretty-number-info` 服务于模板 `131`（`过户业务受阻类`）与模板 `132`（`靓号协议争议类`），一次调用靓号查询接口同时判定客户的手机号类别（靓号 / 非靓号）、靓号等级与靓号营销活动名称。

## 1. 基本契约

- **产出字段（共 3 个，共享同一次接口调用）**：
  1. `手机号类别`（`enum`：`靓号` | `非靓号`，`evidence: derive`，`whenMissing: value`，`defaultValue: "非靓号"`）
  2. `靓号等级`（`string`，`evidence: quote`，`whenMissing: placeholder`，取接口 `grade` 原值如 `GRADE_002`，不做翻译）
  3. `靓号活动名称`（`string`，`evidence: derive`，`whenMissing: placeholder`，取接口 `level_info.event_name`，多档次时用顿号 `、` 连接）
- **关联接口**：`cc_pretty_num_info_query`
- **必填入参**：`手机号码`（11 位纯数字；二期已移除冗余同名入参 `客户号码`，统一使用 `手机号码`）。入参缺失或格式非法时不调接口，3 个字段提交 `not_found`（模板 131 在非靓号分支自动跳过等级与活动名称，模板 132 缺失时保留占位符与 Pebble 一致）。

## 2. 确定性工具执行流程（二期修复 R5 后）

1. **调用靓号接口**：调用 `call_api("cc_pretty_num_info_query", {"手机号码": 手机号码})`。
   - `ok=True, count=0`（含网关 `ret_code=1`“号码不存在”，契约已声明为 `noData`）：确认属于**非靓号**；
   - `ok=False`（网关超时或其它异常）：3 个字段提交 `not_found` 并如实写明接口报错原因。
2. **精确匹配本机号码记录**：
   - 当 `count >= 1` 时，调用 `query_result` 筛选 **`msisdn == 手机号码`** 的记录（`{"column": "msisdn", "op": "equals", "value": 手机号码}`），不再盲目取第一条非空记录。
3. **核验 `grade` 非空与多档次活动名拼接**：
   - **若未命中本机号码记录，或命中记录的 `grade` 列为空**：按**非靓号**处理（3 个字段提交 `not_found`，模板默认输出 `非靓号` 与空串，或按非靓号规则明确提交）；
   - **若 `grade` 非空（确认为真实靓号）**：
     - `手机号类别` = `"靓号"`（引用该记录 `msisdn` / `grade` 列）；
     - `靓号等级` = `grade` 原值（`evidence: quote` 引用 `grade` 列）；
     - `靓号活动名称`：若 `level_info.event_name` 为单个字符串则原样取用；若存在多个档次（契约点分列返回 JSON 数组文本如 `["活动A", "活动B"]`），去掉空项后以中文顿号 `、` 连接为 `"活动A、活动B"`（配合 `derive` 证据引用 `level_info.event_name` 列）。

## 3. 二期主动修复的前代 Java 缺陷（R5）

前代 Java Groovy 脚本在靓号抽取上存在三处代码与业务文档自相矛盾的缺陷，二期已全部修正：
1. **核对号码一致性**：Java `SKILL.md` 要求按传入手机号匹配，但 Groovy 代码直接取第一条 `msisdn` 非空的记录；现用 `query_result` 精确匹配 `msisdn == 手机号码`。
2. **空等级不再误判靓号**：Java 代码在记录存在但 `grade` 为空串时仍输出 `手机号类别=靓号`，导致报告出现“客户号码为靓号，靓号等级为（空）”的病句；现统一要求 `grade` 非空才认定为靓号。
3. **多档次活动名可读分隔**：Java Groovy 使用 XML `event_name.text()` 把多个档次名无分隔符硬拼成一团，Python 初版点分列直接暴露原始 JSON 方括号串；现规范为顿号 `、` 连接。

## 相关页面

- [11 个纯文本业务 Skill 总览](README.md)
- [3 个内置网关接口契约速查](../reference/apis-catalog.md)
- [Java 行为差异与二期主动修复台账](../lint/java-divergence.md)
