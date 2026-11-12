<!-- #Created By AiCoding(codex) 由 generate.py 生成 -->
# 模板迁移对照表

| ID | 模板（Java 编码） | 字段数 | 中间字段（Java 隐式依赖） | 列表字段 | Skill | 入参 | 未使用的 rule（Java 同样忽略） |
|---|---|---|---|---|---|---|---|
| 100 | 不知情业务办理争议处理类 | 16 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | - |
| 101 | 业务办理争议类 | 16 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | - |
| 102 | 业务办理合规类 | 16 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | - |
| 103 | 业务办理告知争议类 | 11 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | 编号、活动名称、活动时间、活动内容、客户承诺 |
| 104 | 业务办理未授权争议处理类 | 16 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | - |
| 105 | 优惠活动到期资费恢复争议处理模板 | 15 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms, reminder-sms | 手机号码、业务名称、创建时间、业务月份、deadlineDate | 编号、活动名称 |
| 106 | 充值争议处理通用模板 | 2 | - | 充值流水 | qry-balance | 手机号码、充值号码、充值时间、extraInfo | 充值时间 |
| 107 | 充值错号处理类 | 2 | - | 充值流水 | qry-balance | 手机号码、充值号码、充值时间、extraInfo | - |
| 108 | 合约到期处理类 | 15 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms, reminder-sms | 手机号码、业务名称、创建时间、业务月份、deadlineDate | 编号、活动名称 |
| 109 | 合约协议争议类 | 13 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | 编号、活动名称 |
| 110 | 合约及违约金争议处理类 | 13 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | 编号、活动名称 |
| 111 | 合约套餐提前解约处理类 | 14 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | 编号、活动名称 |
| 112 | 合约延续争议类 | 22 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms, renewal-reminder-sms | 手机号码、业务名称、创建时间、业务月份、deadlineDate | 编号、活动名称 |
| 113 | 合约期内业务取消违约金争议类 | 13 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | 编号、活动名称 |
| 114 | 合约活动提前解约类 | 14 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | 编号、活动名称 |
| 115 | 合约活动违约争议处理模板 | 19 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | 编号、活动名称、客户承诺 |
| 116 | 增值业务扣费争议处理模板 | 16 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | - |
| 117 | 套餐变更与降档争议处理类 | 13 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | 编号、活动名称 |
| 118 | 套餐变更争议类 | 11 | - | - | original-package-name, business-sms, accept-type, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | - |
| 119 | 套餐费用争议类 | 29 | - | 账期短信提醒列表 | accept-type, business-sms, second-confirmation-sms, verification-sms, billing-cycle-sms | 手机号码、业务名称、创建时间、业务月份、账单 | - |
| 120 | 宽带业务续约争议类 | 16 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms, reminder-sms | 手机号码、业务名称、创建时间、业务月份、deadlineDate | 编号、活动名称 |
| 121 | 宽带业务费用争议类 | 16 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份、extraInfo | 编号、活动名称 |
| 122 | 携号转网协议冲突类 | 17 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms, number-portability-sms | 手机号码、业务名称、创建时间、业务月份、extraInfo | 编号、活动名称 |
| 123 | 活动办理争议类 | 13 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | 编号、活动名称 |
| 124 | 流量使用争议类 | 11 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | 编号、活动名称、活动时间、活动内容、客户承诺 |
| 125 | 流量扣费争议处理模板 | 13 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | - |
| 126 | 营销宣传不符类 | 18 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | 编号、活动名称 |
| 127 | 营销承诺不兑现类 | 13 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | 编号、活动名称 |
| 128 | 营销活动争议类 | 13 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | 编号、活动名称 |
| 129 | 营销活动到期费用争议处理类 | 15 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms, reminder-sms | 手机号码、业务名称、创建时间、业务月份、deadlineDate | 编号、活动名称 |
| 130 | 营销活动误导办理类 | 13 | - | - | accept-type, business-sms, second-confirmation-sms, verification-sms | 手机号码、业务名称、创建时间、业务月份 | 编号、活动名称 |
| 131 | 过户业务受阻类 | 14 | 受理渠道 | - | pretty-number-info, business-sms, accept-type | 手机号码、业务名称、创建时间、业务月份 | 活动名称 |
| 132 | 靓号协议争议类 | 13 | 受理渠道 | - | pretty-number-info, business-sms, accept-type | 手机号码、业务名称、创建时间、业务月份 | 手机号类别、活动名称 |
