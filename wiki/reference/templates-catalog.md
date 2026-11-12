---
title: 33 个生产模板完整清单
type: reference
tags: [reference, templates, catalog, migration]
sources:
  - tools/java_migration/TEMPLATES.md
  - tools/java_migration/template_ids.yaml
  - tools/java_migration/field_catalog.yaml
updated: 2026-11-12
---

# 33 个生产模板完整清单

<!-- #Created By AiCoding(codex) -->

`src/report_agent/seed/templates/` 内置了从前代 Java 资源库（`AGENT_TEMPLATE_CFG`）完整迁移并治理后的 **33 个生产申告报告模板**（模板 ID `100` ～ `132`），全量通过静态发布校验（**0 error / 0 warning**）。

## 1. 全量模板对照表

| ID | 模板名称（原 Java 编码） | 字段数 | 中间字段（`visible: false`） | 列表字段（`type: list`） | 绑定的业务 Skill | 模板入参（`inputs`） |
|----|-------------------------|--------|-----------------------------|-------------------------|------------------|---------------------|
| 100 | 不知情业务办理争议处理类 | 16 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 101 | 业务办理争议类 | 16 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 102 | 业务办理合规类 | 16 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 103 | 业务办理告知争议类 | 11 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 104 | 业务办理未授权争议处理类 | 16 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 105 | 优惠活动到期资费恢复争议处理模板 | 15 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms`, `reminder-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 106 | 充值争议处理通用模板 | 2 | — | `充值流水` | `qry-balance` | 手机号码、充值号码、充值时间、extraInfo |
| 107 | 充值错号处理类 | 2 | — | `充值流水` | `qry-balance` | 手机号码、充值号码、充值时间、extraInfo |
| 108 | 合约到期处理类 | 15 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms`, `reminder-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 109 | 合约协议争议类 | 13 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 110 | 合约及违约金争议处理类 | 13 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 111 | 合约套餐提前解约处理类 | 14 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 112 | 合约延续争议类 | 22 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms`, `renewal-reminder-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 113 | 合约期内业务取消违约金争议类 | 13 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 114 | 合约活动提前解约类 | 14 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 115 | 合约活动违约争议处理模板 | 19 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 116 | 增值业务扣费争议处理模板 | 16 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 117 | 套餐变更与降档争议处理类 | 13 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 118 | 套餐变更争议类 | 11 | — | — | `original-package-name`, `business-sms`, `accept-type`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 119 | 套餐费用争议类 | 29 | — | `账期短信提醒列表` | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms`, `billing-cycle-sms` | 手机号码、业务名称、创建时间、业务月份、账单 |
| 120 | 宽带业务续约争议类 | 16 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms`, `reminder-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 121 | 宽带业务费用争议类 | 16 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份、extraInfo |
| 122 | 携号转网协议冲突类 | 17 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms`, `number-portability-sms` | 手机号码、业务名称、创建时间、业务月份、extraInfo |
| 123 | 活动办理争议类 | 13 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 124 | 流量使用争议类 | 11 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 125 | 流量扣费争议处理模板 | 13 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 126 | 营销宣传不符类 | 18 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 127 | 营销承诺不兑现类 | 13 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 128 | 营销活动争议类 | 13 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 129 | 营销活动到期费用争议处理类 | 15 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms`, `reminder-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 130 | 营销活动误导办理类 | 13 | — | — | `accept-type`, `business-sms`, `second-confirmation-sms`, `verification-sms` | 手机号码、业务名称、创建时间、业务月份 |
| 131 | 过户业务受阻类 | 14 | `受理渠道` | — | `pretty-number-info`, `business-sms`, `accept-type` | 手机号码、业务名称、创建时间、业务月份 |
| 132 | 靓号协议争议类 | 13 | `受理渠道` | — | `pretty-number-info`, `business-sms`, `accept-type` | 手机号码、业务名称、创建时间、业务月份 |

## 2. 特殊模板结构说明

- **纯充值流水模板（`106`、`107`）**：仅包含 `客户号码`（标量）与 `充值流水`（4 列 `list`）共 2 个字段，不挂载短信类 Skill。
- **隐式中间字段模板（`131`、`132`）**：正文不直接输出 `{{受理渠道}}`，但 `受理日期` 的业务规则依赖 `受理渠道` 结论，因此自动识别并声明了 `visible: false` 的中间字段 `受理渠道`。
- **含列表字段的综合模板（`119`）**：字段最多（29 个），同时涵盖业务办理短信举证与跨月 `账期短信提醒列表`（5 列 `list`）。
- **测试夹具专用模板（`1001`）**：仅存在于 `tests/fixtures/seed/templates/1001/` 供 `pytest` 单元测试使用，不在生产 `seed/` 目录中。

## 相关页面

- [模板模型与渲染机制](../architecture/template-and-rendering.md)
- [11 个纯文本业务 Skill 总览](../skills/README.md)
- [新增与维护报告模板实操指南](../guides/add-template.md)
- [Java 资源迁移与一致性对拍指南](../guides/java-migration-and-verification.md)
