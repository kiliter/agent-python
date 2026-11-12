---
title: 新增纯文本 Skill 与声明式网关接口契约指南
type: guide
tags: [guide, skill, api-contract, gateway, tools]
sources:
  - src/report_agent/domain/skill.py
  - src/report_agent/domain/api_contract.py
  - src/report_agent/runtime/tools.py
  - src/report_agent/gateway/mock.py
updated: 2026-11-12
---

# 新增纯文本 Skill 与声明式网关接口契约指南

<!-- #Created By AiCoding(codex) -->

当新模板需要接入新的外部业务查询接口，或沉淀一套跨模板复用的取数筛选规则时，无需编写任何 Python 后端代码——只需先声明一份网关接口契约（`apis/<name>.yaml`），再编写一份纯文本 `SKILL.md`。

## 1. 第一步：编写声明式网关契约（`apis/<name>.yaml`）

契约标识 `name` 必须匹配 `^[A-Za-z][A-Za-z0-9_-]{0,63}$`。可在工作台「接口管理」用可视化表单创建，核心结构如下：

```yaml
name: queryUserContractInfo
title: 客户合约档案查询
description: 按 11 位手机号查询客户在途合约列表。
connector: unified-gateway-xml      # 或 unified-gateway-json
processCode: queryUserContractInfo  # 统一网关 sysfunc_id / process_code
timeoutMs: 10000
retry:
  maxAttempts: 1
idempotent: true
input:
  type: object
  required: [手机号码]
  additionalProperties: false
  properties:
    手机号码:
      type: string
      pattern: '^1\d{10}$'
      description: 11 位客户手机号
request:
  route_type: '2'
  route_value: ${手机号码}
  request_time: ${$now}             # 可选：内置占位符，每次调用自动填入当前 yyyyMMddHHmmss
  content:
    userMobile: ${手机号码}
response:
  noData:                           # 先判无数据：命中即视为 ok=true, count=0, noData=true
    - path: operation_out.response.resp_desc
      contains: 无记录
  success:                          # 再判成功码：missingAs 控制节点缺失时算成功还是失败
    path: operation_out.response.resp_code
    equals: '0000'
    missingAs: failure
  records:
    path: operation_out.content.contractList
    mode: auto                      # auto | list | object | scalar | none
    columns:
      contractId: 合约编码
      contractName: 合约名称
      effTime: 生效时间 yyyyMMddHHmmss
      expTime: 失效时间 yyyyMMddHHmmss
  summary:
    maxPreviewChars: 60
```

### 契约调试技巧

1. **放置本地 Mock 报文**：在 `DATA_DIR/mock-gateway/` 下放入 `queryUserContractInfo.xml`（正例）与 `queryUserContractInfo.13900000000.xml`（无数据/异常样例，按 `route_value` 路由）；
2. **在线拨测**：在工作台「接口管理」页点击「在线测试」，输入手机号查看脱敏后的实际请求报文（验证 Jackson 3 XML 标签顺序与 `xsi:nil`）及抽取出的二维列数据。

## 2. 第二步：编写纯文本 `SKILL.md`（`skills/<id>/SKILL.md`）

Skill 标识 `id` 必须使用小写字母、数字与短横线（`^[a-z0-9][a-z0-9_-]{0,63}$`），且 frontmatter 的 `name` 必须与 `id` 完全一致：

```markdown
---
name: user-contract-info
title: 客户在途合约查询
description: 模板需要“在途合约名称”或“合约到期日”时加载。
apis:
  - queryUserContractInfo
---

# 客户在途合约查询

## 适用场景
模板字段 `在途合约名称`、`合约到期日`。

## 需要的入参
- `手机号码`：11 位数字，缺失或格式不符时不要调用接口，提交 `not_found`。

## 查询与筛选步骤（必须用确定性工具执行）
1. 调用 `call_api("queryUserContractInfo", {"手机号码": 手机号码})`。
   - `ok=false` → 提交 `not_found` 并写明报错信息；
   - `ok=true` 且 `count=0` → 提交 `not_found`。
2. 调用 `query_result` 按 `normalizedContains` 匹配业务名称，按 `expTime` 倒序取第 1 条。
3. `合约到期日` 必须调用 `format_date(value=expTime, fromPattern="yyyyMMddHHmmss", toPattern="yyyy-MM-dd")` 转换。

## 提交要求
- `在途合约名称`：取 `contractName` 原文，证据 `{"type":"api","resultId":...,"row":...,"column":"contractName"}`。
- `合约到期日`：直接使用 `format_date` 输出，证据附上 `format_date` 的 `callId` 与该行 `expTime` 列。
```

### 编写高质量 `SKILL.md` 的四条铁律

1. **禁止让大模型心算确定性步骤**：
   - 从文本找日期求最值 → 写明调用 `extract_dates`；
   - 加减天数算窗口 → 写明调用 `date_shift`；
   - 展开账期区间 → 写明调用 `expand_period`；
   - 算两条记录的秒级距离 → 写明调用 `time_diff`；
   - 提取正则捕获组 → 写明调用 `regex_extract`；
   - 筛表排序（含跨月合并或 OR 条件） → 写明调用 `query_result`（用 `resultIds` / `anyOf` / `between` / `normalizedContains`），明确写上“严禁目测预览筛选”。
2. **明确区分 `ok=false` 与 `count=0`**：尤其对列表字段，各月 `ok=true` 但无命中记录时要求提交 `status="found", value=[]`（附上结果为 0 行的 `query_result(total=0)` 或 `call_api(count=0)` 的工具 `callId` 证据，严禁引用 `load_skill`），而任一接口 `ok=false` 时必须提交 `status="not_found"`。
3. **写清相同参数复用 `resultId`**：若多个 Skill 查同一个接口且参数相同（如工单创建当天短信），嘱咐模型直接复用已有 `resultId`。
4. **绑定到模板**：最后在目标模板的 `skills` 列表中勾选该新 Skill（未勾选的 Skill 会被 `load_skill` 权限拦截）。

## 相关页面

- [确定性平台工具设计](../architecture/deterministic-tools.md)
- [网关契约与连接器组件剖析](../components/gateway-and-api-contract.md)
- [11 个纯文本业务 Skill 总览](../skills/README.md)
- [新增与维护报告模板实操指南](add-template.md)
