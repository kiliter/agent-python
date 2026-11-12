---
title: 3 个内置网关接口契约速查
type: reference
tags: [reference, apis, gateway, xml, querySMSSendInfo, BOSS_QryBalanceFlowLog, cc_pretty_num_info_query]
sources:
  - src/report_agent/seed/apis/querySMSSendInfo.yaml
  - src/report_agent/seed/apis/BOSS_QryBalanceFlowLog.yaml
  - src/report_agent/seed/apis/cc_pretty_num_info_query.yaml
updated: 2026-11-12
---

# 3 个内置网关接口契约速查

<!-- #Created By AiCoding(codex) -->

`src/report_agent/seed/apis/` 内置了支撑全部 11 个业务 Skill 的 **3 个统一网关 XML 接口契约**。所有契约均采用 `connector: unified-gateway-xml`、`timeoutMs: 10000`、`retry.maxAttempts: 1`，生成的 XML 请求报文与前代 Java Jackson 3 `XmlMapper` 字节级一致。

## 1. `querySMSSendInfo` — 短信发送记录查询

- **被引用 Skill（8 个）**：`business-sms`、`second-confirmation-sms`、`verification-sms`、`original-package-name`、`reminder-sms`、`renewal-reminder-sms`、`number-portability-sms`、`billing-cycle-sms`
- **入参 Schema**：
  - `手机号码`（必填，`^1\d{10}$`）：11 位客户手机号
  - `开始时间`（必填，`^\d{14}$`）：`yyyyMMddHHmmss`
  - `结束时间`（必填，`^\d{14}$`）：`yyyyMMddHHmmss`（不限制 31 天跨度，支持 `renewal-reminder-sms` 一次查询 63 天）
- **请求头与报文特点**：`route_type='2'`、`route_value=${手机号码}`；`content` 包含 `userMobile`、`startDate`、`endDate`、`sendType='0'`、`sendPort=''`（普通空标签）、`busiType='0'`；其余未设公共头走 `xsi:nil="true"`。
- **成功与无数据判定**：
  - `noData`：`operation_out.response.resp_desc` 包含 `"无短信记录"`（现网无短信时返回 `resp_code=1`，归为正常 0 条记录 `ok=True, count=0, noData=True`）；
  - `success`：`operation_out.response.resp_code == "0000"`（`missingAs: success`）。
- **抽取路径与列（`operation_out.content.smsList`）**：`smsSendTime`、`smsContent`、`sendPort`、`sendType`、`busiType`、`smsSendStatus`、`userMobile`、`remark`、`staffId`。

## 2. `BOSS_QryBalanceFlowLog` — 预付费充值余额流水查询

- **被引用 Skill（1 个）**：`qry-balance`（一次只查一个自然月账期）
- **入参 Schema**：
  - `手机号码`（必填，`^\d{11}$`）：11 位客户号码
  - `账期`（必填，`^\d{4}(0[1-9]|1[0-2])$`）：查询账期 `yyyyMM`（如 `202607`）
- **请求头与报文特点**：覆盖公共头 `organ_id='3001'`、`operator_id=''`、`request_seq=''`、`verify_code='1002'`，并使用内置动态占位符 **`request_time: ${$now}`** 在每次组包时自动填入当前 `yyyyMMddHHmmss`；`content` 包含 `userMobile` 与 `cycle`。
- **成功与无数据判定**：
  - `success`：`operation_out.response.resp_code == "0000"`，且 **`missingAs: failure`**（缺少 `resp_code` 或返回 `7003` 等非 `0000` 码一律严判为 `ok=False`，禁止当作无流水）；
  - 业务成功但无 `listBusiRec` 节点时自然返回 0 条记录。
- **抽取路径与列（`operation_out.content.listBusiRec`）**：`payDatetime`、`payTypeName`、`amount`（接口原值，不做分转元）、`soNbr`、`svcNum`、`channelId`、`acctbookType`、`charFrom`、`paidMonth`、`tradeOpId`。

## 3. `cc_pretty_num_info_query` — 靓号号码信息查询

- **被引用 Skill（1 个）**：`pretty-number-info`
- **入参 Schema**：
  - `手机号码`（必填，`^\d{11}$`）：11 位手机号
- **请求头与报文特点**：`route_type='2'`、`route_value=${手机号码}`，`content.msisdn_list.msisdn=${手机号码}`。
- **成功与无数据判定**：
  - `noData`：`operation_out.content.ret_code == "1"`（如“号码不存在”，优先命中并归为正常非靓号 0 条记录 `ok=True, count=0, noData=True`）；
  - `success`：`operation_out.content.ret_code == "0"`，且 **`missingAs: failure`**（当网关返回顶层异常如 `<resp_code>9999</resp_code>` 且报文缺失 `<content><ret_code>` 时，严格判为 `ok=False` 并提取错误描述，避免把网关级故障静默误判为“非靓号”）。
- **抽取路径与列（`operation_out.content.msisdn_list`）**：`msisdn`、`grade`（如 `GRADE_002`）、`price`、`default_event_code`，以及点分嵌套列 `level_info.level`、`level_info.event_code`、`level_info.event_name`（多档次时自动存为 JSON 数组字符串）、`level_info.event_description`。

## 相关页面

- [网关契约与连接器组件剖析](../components/gateway-and-api-contract.md)
- [11 个纯文本业务 Skill 总览](../skills/README.md)
- [新增纯文本 Skill 与声明式网关接口契约指南](../guides/add-skill-and-api.md)
