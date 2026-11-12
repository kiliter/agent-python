# Java Skill → Python Skill 迁移映射

<!-- #Created By AiCoding(codex) Java（Spring AI + Groovy）→ Python（Pydantic AI）Skill 与接口契约迁移说明、二期缺陷修复与预期差异清单 -->

## 1. 产物清单（已安装到 `src/report_agent/seed/`）

| 路径 | 说明 |
|---|---|
| `skills/<name>/SKILL.md` | 11 个 Skill，名称与 Java 完全一致，二期全面升级使用平台确定性工具与列表新语义 |
| `apis/querySMSSendInfo.yaml` | 短信查询契约（seed 版的修正版，见 §3） |
| `apis/BOSS_QryBalanceFlowLog.yaml` | 预付费充值余额流水查询契约 |
| `apis/cc_pretty_num_info_query.yaml` | 靓号信息查询契约 |
| `mock-gateway/*.xml` | mock 响应：每个接口一个正例；`*.13900000000.xml` 为无数据/失败样例（mock 按 `route_value` 选文件） |
| `tools/java_migration/check_skills.py` | 校验脚本：`uv run python tools/java_migration/check_skills.py`（Java 报文、Groovy 正常场景对拍及二期缺陷修复专项断言） |
| `tools/java_migration/harness/*.java` | 校验用 Java 程序：调用 Java 编译产物 `CommonRequestToolService#toXmlRequest`、`PebbleTemplateEngine#render`，以及用 `GroovyScriptEngine` 执行真实的 `assembly/extract.groovy` |

## 2. 对照表

| Java Skill | Python Skill | 接口（processCode） | 填写字段 | 需要的入参 | 依赖 | 核心确定性工具 |
|---|---|---|---|---|---|---|
| business-sms | business-sms | querySMSSendInfo | 订购短信 | 手机号码、业务名称、创建时间 | — | `date_range`、`query_result(normalizedContains, before="编号")` |
| accept-type | accept-type | 无 | 受理渠道（热线/掌上营业厅/其他，默认其他） | — | business-sms（字段证据 `type=field name=订购短信`） | `text_contains(normalize=false)` |
| second-confirmation-sms | second-confirmation-sms | querySMSSendInfo | 二次确认短信 | 手机号码、业务名称、创建时间 | — | `date_range`、`query_result` |
| verification-sms | verification-sms | querySMSSendInfo | 验证码短信 | 手机号码、业务名称、创建时间 | — | `date_range`、`query_result` |
| original-package-name | original-package-name | querySMSSendInfo | 原套餐名称 | 手机号码、创建时间 | business-sms | `date_range`、`query_result`、`time_diff`、`regex_extract` |
| reminder-sms | reminder-sms | querySMSSendInfo | 提醒短信、提醒日期（yyyy-MM-dd） | 手机号码、创建时间（仅补年份）、deadlineDate（可选） | business-sms | `extract_dates`、`date_shift`、`query_result`、`format_date` |
| renewal-reminder-sms | renewal-reminder-sms | querySMSSendInfo | 续约提醒类型、到期续约提醒时间、到期续约提醒短信内容、是否续约成功、续约成功提醒时间、续约成功提醒短信内容 | 手机号码、业务名称、创建时间（补年份）、deadlineDate（可选） | business-sms | `extract_dates`、`date_shift`、`regex_extract`、`query_result(anyOf)`、`format_date` |
| number-portability-sms | number-portability-sms | querySMSSendInfo | 发送日期（yyyy-MM-dd）、携转资格回复短信 | 手机号码、创建时间 | — | `date_range`、`query_result`、`format_date` |
| billing-cycle-sms | billing-cycle-sms | querySMSSendInfo（逐月） | 账期短信提醒列表（list：账期月/提醒类型/提醒时间/提醒次数/短信内容） | 手机号码、账单（`yyyyMM$yyyyMM` 闭区间） | — | `expand_period`、`query_result(resultIds, between)`、`format_date` |
| qry-balance | qry-balance | BOSS_QryBalanceFlowLog（逐账期） | 充值流水（list：充值时间/支付方式/充值金额/流水号） | 充值号码（含 extraInfo）→手机号码、充值时间（含 extraInfo 办理日期） | — | `expand_period`、`query_result(resultIds, between prefixLen=8)` |
| pretty-number-info | pretty-number-info | cc_pretty_num_info_query | 靓号等级、靓号活动名称、手机号类别 | 手机号码 | — | `query_result(equals msisdn)` |

入参规范：以当前 Python 系统中文入参名为准，不注入与正文字段重名的 `客户号码` 入参，关联 `reminder-sms` / `renewal-reminder-sms` 的 5 个模板（`105, 108, 112, 120, 129`）显式声明可选入参 `deadlineDate`，全量资源 `validate_all` 保持 **0 errors, 0 warnings**。

模板配置要点：
- `受理渠道`：`enum [热线, 掌上营业厅, 其他]`，`whenMissing: value`，`defaultValue: 其他`（`订购短信` 为 `not_found` 时直接提交 `not_found` 走默认值，不引用 `not_found` 前置字段）。
- `手机号类别`：`whenMissing: value`，`defaultValue: 非靓号`；`靓号等级`（`quote`）、`靓号活动名称`（`derive`，支持多档 JSON 数组按 `、` 拼接）：`whenMissing: placeholder`；`cc_pretty_num_info_query.yaml` 配置 `response.success.missingAs: failure`，顶层网关故障（无 `content.ret_code`）准确判为 `ok=false`。
- `安装地址`（模板 121）：`evidence: derive`，`whenMissing: value`，`defaultValue: 无`（单据有地址引 `document`，无单据时从 `extraInfo` 提取并引 `input: extraInfo`）。
- `标准资费`（模板 `100, 101, 102, 103, 104, 116, 119, 122, 125, 126`）：`evidence: derive`，支持将原文“月费10元”标准化为“10元/月”并引用单据或订购短信记录。
- `有设备押金`（模板 120）与 `违约责任`（模板 111、114）：`whenMissing: empty`；模板 115 `违约责任` 保留 `whenMissing: placeholder`（第 19 行直接输出）并在第 59 行条件补加 `and 违约责任 != "{{违约责任}}"`，彻底消除占位符恒真分支。
- `是否续约成功`：找不到时提交 `not_found`（不得推断为“否”），模板 `{% if 是否续约成功 == "是" %}` 自然不展示。
- `订购短信`、`二次确认短信`、`验证码短信`、各类短信内容：`evidence: quote`，`quoteWhole: true`。
- 列表字段（`充值流水`、`账期短信提醒列表`）：必要入参齐备且接口调用成功（`ok=true`）但命中 0 行时，提交 `status="found"`、`value=[]`，并引用 `total=0` 的 `query_result` 或 `count=0` 的 `call_api` 工具 `callId`（严禁引用 `load_skill` 或非空表 `api`）；仅缺参或接口失败（`ok=false`）时提交 `status="not_found"`、`value=null`。

## 3. 接口契约与对拍校验结果

全部 `schema_errors()` 为空；`check_skills.py` 用 Java 编译产物生成真实报文并逐字比较：

| 契约 | 结果 |
|---|---|
| querySMSSendInfo | 与 Java `xml-nytool` 报文**逐字一致**（`route_type=2`、`sendPort` 空标签、公共字段 `xsi:nil`、Jackson 3 字母序） |
| cc_pretty_num_info_query | **逐字一致** |
| BOSS_QryBalanceFlowLog | **逐字一致**（`organ_id=3001`、`operator_id`/`request_seq` 空标签、`verify_code=1002`；`request_time` 用内置占位符 `${$now}` 取当前时间，与 Java 相同） |

seed `querySMSSendInfo.yaml` 的修正：
1. `结束时间` 说明去掉“跨度不超过 31 天”（`renewal-reminder-sms` 一次查 63 天，`billing-cycle-sms` 查整月）；
2. `records.columns` 补 `smsSendStatus`、`userMobile`、`remark`、`staffId`（真实响应字段）；
3. `retry.maxAttempts` 改为 1（与 Java 一致）。

Skill 逻辑校验：`check_skills.py` 使用平台确定性工具函数在 mock 数据上模拟全部 11 个 Skill：
- 正常场景与 Java Groovy 脚本真实输出完全一致；
- 二期修复的历史缺陷场景（见 §4 R2、R4、R5、R8）通过专项回归断言验证。

## 4. 二期已修复的 Java 缺陷与语义差异说明

### 二期已修复项（与旧 Java 缺陷行为的预期差异）

- **R2 `reminder-sms` 活动编号误识别为日期缺陷与无到期日跳过策略（已修复）**：
  - **旧 Java 行为**：宽松正则 `(\d{4})\D{0,3}(\d{1,2})\D{0,3}(\d{1,2})` 不做日历校验，会把 `（编号：25JS206149）。\n1.` 误算成非法日期 `20614901`，导致查询窗口变成 `20614901000000～20614901235959` 而查不到提醒短信。
  - **Python 现行行为**：改用确定性工具 `extract_dates(text=订购短信, defaultYear=创建时间)` 提取经日历合法性校验的真实日期（传入非空 `deadlineDate` 时优先解析；若未传 `deadlineDate` 且订购短信 `count == 0` 无合法到期日，与 Java 一致**直接跳过接口查询**并返回 `not_found`，绝不回退 `创建时间` 当天以防误取办理日 `【订购提醒】`），再用 `date_shift(date=目标日期, days=0)` 生成当天窗口。示例短信正确提取 `20271201`（窗口 `20271201000000～20271201235959`）。
- **R3 确定性逻辑手算风险（二期已解决）**：
  - 平台已补齐确定性工具：`extract_dates`、`date_shift`、`expand_period`、`time_diff`、`regex_extract`，并增强 `query_result` 支持 `startsWith`、`between`（含 `endValue`、`prefixLen`）、`anyOf` 或条件组、`resultIds` 多结果合并筛选排序。全部 Skill 已由手算规则升级为工具调用。
- **R4 `list` 字段空值 vs 缺失语义（二期已升级）**：
  - **旧行为**：0 行记录统一提交 `not_found`，且接口失败或缺失时模板遍历空列表仍被判为 `SUCCESS`。
  - **Python 现行行为**：入参齐备且接口调用成功（`ok=true`）但命中 0 行时，提交 `status="found"`、`value=[]` 并附 `tool`/`api` 证据，渲染为空且状态为 `SUCCESS`；缺参或接口报错（`ok=false`）时提交 `status="not_found"`、`value=null`，当模板生效分支实际迭代该 `TrackedList` 时运行状态准确判为 `PARTIAL`。
- **R5 靓号 `pretty-number-info` 代码与规格不一致缺陷（二期已修复）**：
  - **旧 Java 行为**：不核对返回记录 `msisdn` 是否等于查询号码而直接取首条；`grade` 为空时仍输出 `手机号类别=靓号`；多档 `level_info` 的 `event_name` 直接无分隔符拼接。
  - **Python 现行行为**：用 `query_result` 按 `msisdn == 手机号码` 精确过滤；无匹配记录或匹配记录 `grade` 为空时一律按非靓号处理（三个字段提交 `not_found`，由模板默认值输出 `非靓号` 与空字符串）；多档 JSON 数组文本提取非空活动名称按中文顿号 `、` 拼接（`靓号活动名称` 为 `evidence: derive`）。
- **R7 同名入参 `客户号码` 发布警告（二期已消除）**：
  - 移除 `generate.py` 中为兼容 Java 注入的 `客户号码` 入参，消除模板 106、107、131、132 的 4 条 `FIELD_SAME_AS_INPUT` 警告。`qry-balance` 号码优先级为 `充值号码`（含 `extraInfo` 中的 `充值号码`）→ `手机号码`；`pretty-number-info` 直接使用 `手机号码`。
- **R8 `qry-balance` 纯年月 `202607` 正则回溯缺陷（二期已修复）**：
  - **旧 Java 行为**：过滤阶段正则 `(20\d{2})\D*(\d{1,2})\D*(\d{1,2})` 把纯年月 `202607` 回溯成 `20260007`，导致整月充值流水全部被误过滤丢弃。
  - **Python 现行行为**：改用 `expand_period(period=充值时间)` + `query_result(resultIds=..., where=[between prefixLen=8])`，纯年月 `202607` 自动展开为整月 `20260701～20260731`，正确保留该月全部流水并按 `payDatetime` 倒序排列。
- **R10 日期窗口计算（二期已统一）**：
  - 统一通过经日历校验的 `date_range`、`extract_dates`、`date_shift`、`expand_period` 计算起止时间，不再向网关拼接非法日期。
- **R17 模板 120 `有设备押金` 与模板 111 / 114 / 115 `违约责任` 占位符恒真/死分支缺陷（已修复）**：
  - **旧 Java 行为**：`PebbleTemplateEngine.render()` 把空/缺失变量填充为非空占位符 `"{{ 字段名 }}"`，导致模板 120 `{% if 有设备押金 %}` 恒真（`{% else %}` 死代码），模板 111 / 114 / 115 `{% if 违约责任 != "" %}` 恒真（缺失时仍输出违约金/违约行为段落）。
  - **Python 现行行为**：`field_catalog.yaml` 将模板 120 `有设备押金` 与模板 111、114 `违约责任`（`visible: false`）设为 `whenMissing: empty`；`generate.py` 为模板 115 第 59 行条件补加 `and 违约责任 != "{{违约责任}}"`（保留第 19 行占位符输出），同时在 `verify_structure.py` 增加 S8/S9 AST 静态门禁阻断回归。

### 其余已确认的常规说明（保持不变）

- **R1 余额流水 `request_time`（已解决）**：契约使用内置占位符 `${$now}`（当前时间 `yyyyMMddHHmmss`），报文与 Java 逐字一致。
- **R6 Java 字段映射间接层**：Python 直接按模板字段（`靓号等级`、`靓号活动名称`、`手机号类别`、`充值流水`）定义与取值，无需 Java `field-mappings.yml` 的中间键。
- **R9 短信接口业务失败**：非“无短信记录”的 `resp_code≠0000` 在 Python 中判为 `ok=false`，字段提交 `not_found`。
- **R11 服务层硬编码策略**：`removeSmsAcceptDate`、`applyAcceptDatePolicy`、`resolveKvSourceText`、`applyTerminalInfoPolicy`、`reconcileWithSkillValues` 均已编码进模板字段说明与全局系统提示词。
- **R12 清洗规则**：Python `normalize_text` 比 Java `StringCharCleaner` 额外清理零宽字符（`\ufeff\u200b\u200c\u200d`）。
- **R13 复用查询**：同一次运行内相同参数调用 `querySMSSendInfo` 时复用 `resultId`，减少重复网关请求。
- **R14 号码格式**：契约校验 `^1\d{10}$` 11 位手机号。
- **R15 mock 局限**：`mock-gateway` 按 `route_value` 路由静态 XML，不按时间窗口过滤记录，仅影响本地 mock 调试。
- **R16 排序平手**：Python 稳定排序与 Groovy 相同，时间相同时保持接口原始记录顺序。
