# 需求文档（Spec）：12 项确定性平台工具原语与双协议热更新外部网关连接器

<!-- #Created By AiCoding(codex) -->

> **Spec Kit 使用约定**：产物文件名固定为 `spec.md`、`plan.md`、`tasks.md`；三类外部独立交付物按需确认，仅涉及项单独生成并建立链接，不涉及项只记录依据。生成时已将全部模板占位提示替换为核实后的实际内容；不适用章节保留标题并说明 `本需求不涉及` 及依据。
> **项目依据**：项目宪章 `.specify/memory/constitution.md`、`AGENTS.md` 及 `wiki/index.md`。遵循先取证后写作原则，优先核对代码、测试与运行证据，不把推测写成事实。

---

**功能分支**：`004-deterministic-tools-gateway`

**创建日期**：2026-11-16

**状态**：已交付归档

**输入**：用户描述："智能申告报告填写与资源治理平台（`report-agent`）全栈研发工作拆分 —— 负责向智能体暴露的 12 个确定性平台工具（白名单 Skill 批量加载、工作区幂等去重调用、多结果集结构化过滤与 9 项文本/日历/时间差/防 ReDoS 正则原语）以及 XML/JSON 双协议统一网关、双级本地 Mock 与引用计数热更新客户端。"

## 基本信息 【核心】

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-004` |
| 需求名称 | 12 项确定性平台工具原语与双协议热更新外部网关连接器 |
| 核算工作量 | 33.0 人天（全栈研发工作拆分 250.0 人天之子规格 `004/008`） |
| 资料与证据来源 | 1. **核心源码（高可信）**：`src/report_agent/runtime/{tools.py,text_tools.py}`、`src/report_agent/gateway/{__init__.py,base.py,unified_xml.py,mock.py,reloadable.py}`、`src/report_agent/config.py`<br>2. **自动化测试（高可信）**：`tests/{test_deterministic_tools.py,test_text_and_gateway.py,test_api_json_gateway.py,test_api_response_modes.py,test_review_runtime.py,test_review_fixes_runtime.py,test_runtime_config_hot_reload.py}`<br>3. **实测运行证据（最高可信）**：本轮全量测试 `uv run pytest -q`（`196 passed in 51.41s`）与静态检查 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）<br>4. **架构与规范依据（参考级）**：`.specify/memory/constitution.md`、`AGENTS.md`、`wiki/architecture/deterministic-tools.md`、`wiki/components/{platform-tools.md,gateway-and-api-contract.md}`、`wiki/decisions/adr-002-text-skill-and-deterministic-tools.md` |
| 文档版本 | 2.0 |
| 文档状态 | 已交付归档 |

---

## 1. 业务背景与目标 【核心】

### 1.1 业务背景

在客户申告报告填报过程中，大模型直接处理原始跨行 PDF 单据文本、多账期查询窗口、闰年大小月偏移、秒级短信时间比对与复杂正则表达式时，极易产生算术偏差或编造数值；同时前代 Java 系统中通过 Groovy 脚本硬编码调用网关接口与字符清洗规则，无法热更新且难以在 Python 侧无缝延续。此外，真实生产统一网关兼有存量 Jackson `XmlMapper` 格式的 XML 报文与新增 JSON 协议接口，面临 XXE 实体扩展攻击、超深嵌套 JSON 导致栈溢出、并发压垮网关以及运行期热切换网关配置会撕裂在途连接池等典型工程痛点。

为此，必须在平台中建立职责分离的工具原语与外部网关连接器层：一方面用 12 项确定性平台工具（3 项资源查询调度 + 9 项纯函数计算）将所有机械推理与取数从大模型黑盒接管至可控代码，并把所有外部业务规则完全隔离在声明式 `SKILL.md` 与 `ApiContract` 资源之外；另一方面构造兼具 `java`/`clean` XML 字节等价兼容、JSON 原生协议、XXE/ReDoS/显式栈深度防护、双级本地 Mock 与引用计数排空热切的网关子系统，支撑安全、零硬编码、零中断的全天候运行。

### 1.2 业务目标

- **GOAL-1**：向智能体暴露 12 项领域无关的确定性平台工具，使白名单 Skill 加载、工作区级幂等去重取数、跨结果集结构化筛选以及全部文本/日历/时间差/正则提取均具备唯一可追溯 `callId` 账本与 `ModelRetry` 自我纠错能力。
- **GOAL-2**：彻底接管易出错的大模型日期、文本与账期心算（`extract_dates`、`date_shift`、`expand_period`、`time_diff`、`format_date`、`regex_extract` 等），结合 `safe_regex_compile` 语法树预检阻断灾难性回溯 ReDoS。
- **GOAL-3**：通过 `UnifiedGatewayXmlClient` 与 `gateway/base.py` 提供 `java`/`clean` 风格 XML 与 JSON 双协议统一网关接入能力，确保 `java` 风格报文与前代 Jackson 输出逐字节一致，并在解析入口全面阻断 XXE、`DOCTYPE`/`ENTITY`、超长报文及超深嵌套溢出。
- **GOAL-4**：通过 `MockGatewayClient`（含安全路径校验与 XML→JSON 自动无损回退）和 `ReloadableGatewayClient`（引用计数排空与 `asyncio.shield` 释放）支持离线免外部网关开发测试以及线上毫秒级零泄漏配置热切。

---

## 2. 需求概述 【核心】

本需求涵盖智能体运行工具暴露层（`src/report_agent/runtime/tools.py`、`text_tools.py`）与外部统一网关连接器层（`src/report_agent/gateway/{__init__.py,base.py,unified_xml.py,mock.py,reloadable.py}`）。在运行期间，工具通过 `build_tools(tool_retries)` 注册入单智能体实例：`load_skill` 与 `call_api` 借助 `_prepare_load_skill` / `_prepare_call_api` 钩子把当前模板白名单注入工具 JSON Schema `enum`（名单为空时自动隐藏）；`call_api` 通过 `(name, canonical_json_args)` 与 `asyncio.shield` 实现同工作区并发去重与 leader 取消平滑接管；`query_result` 支持单/多 `resultIds` 合并过滤、7 类操作符、0 行表全量列名校验与失败月份阻断。

在计算与连接层，9 项确定性纯函数驻留于 `text_tools.py`，支持无上下文单测及 Java 规则对拍验证，并通过 `tools.py` 注入 `Workspace` 默认原文及统一错因处理 `_fail_or_retry`。所有网关通讯面向 `GatewayClient` 协议：`UnifiedGatewayXmlClient` 访问 `{GATEWAY_URL}/openapi_3` 实施并发信号量保护、禁重定向、响应敏感字段脱敏与幂等指数退避重试；`MockGatewayClient` 从双级目录安全加载并无损转换 XML/JSON 样例；`ReloadableGatewayClient` 协调热更新切换瞬间的槽位引用计数，确保新调用即时生效且老连接池彻底关闭不泄漏。

### 2.1 用户场景与测试

#### 用户故事 1（US1）— 白名单 Skill 批量加载、幂等并发调用与跨结果集结构化查询（优先级：P1）

- **用户旅程**：作为受限运行在工作区内的单智能体（以及关注安全边界的平台架构师），我需要仅能看到当前模板白名单内的 Skill 和业务接口，通过一次调用批量读取多份 `SKILL.md`、在不重复打爆网关且兼容并发协程部分取消的前提下调用接口，并使用 `query_result` 跨多个接口结果按多条件合并筛选排序。
- **优先级理由**：知识检索、幂等取数与结构化筛选是智能体获取一切业务事实的三项支柱工具，直接决定准确性与并发稳健性。
- **独立测试**：构造带 `RunDeps` 的 `Workspace` 与可控延迟/失败桩网关，独立调用 `load_skill`、`call_api` 与 `query_result`，验证白名单隐藏与 `enum` 约束、leader 取消后生存协程接管、`resultIds` 合并过滤、布尔 `limit` 与 0 行结果非法列名拦截。
- **关联需求**：`FR-001`、`FR-002`、`FR-003`、`FR-004`
- **验收场景**：
  1. **前提** 模板关联了白名单 `allowed_skills` 与 `allowed_apis`，且某接口声明 `idempotent=true`，**当** 模型调用 `load_skill(names=[...])` 并并发发出参数键值对等价的 `call_api` 请求，**则** `load_skill` 去重拼接返回内容并登记 `loaded_skills`（越权或空参触发 `ModelRetry`），并发 `call_api` 仅向网关发送 1 次请求并共享同一 `resultId`（各自独立分配 `callId`；`ok=false` 不入缓存）；若白名单为空则准备钩子返回 `None` 隐藏该工具。
  2. **前提** 两个并发协程共享同一个在途幂等 `call_api` `Future`，**当** 先发的 leader 协程被外部取消（`CancelledError`），**则** 先发协程向上抛出取消异常，存活等待协程感知后自动重新接管并发起网关调用写入唯一成功结果，不连带崩溃存活调用方。
  3. **前提** 工作区存有多个接口结果（含 `no_data=true` 的 0 行结果），**当** 模型传入 `resultIds`、`where`（含 `between` + `prefixLen`）、`anyOf`、`orderBy` 与 `columns` 调用 `query_result`，**则** 工具校验 `Condition`/`OrderBy`（`extra="forbid"`）、非布尔正整数 `limit` 及所有列名均在全量已知列集合内（0 行结果亦不放行错列名），成功返回附来源 `resultId` 与 `row` 的结果集；若 `resultIds` 中含任一 `ok=false` 结果则返回结构化报错，不静默忽略。

#### 用户故事 2（US2）— 接管大模型心算的 9 项纯函数确定性文本、日历与防 ReDoS 工具集（优先级：P1）

- **用户旅程**：作为报告填写智能体及平台防幻觉架构保障，面对跨行折行单据、全角标点、易混淆数字编号（如活动号与手机号）、闰年日历偏移、多账期展开与正则抓提等机械逻辑，我必须交由纯 Python 确定性工具执行计算并在重试耗尽时平滑降级。
- **优先级理由**：用纯确定性算法彻底消除大模型在日期算术、跨行匹配与正则表达式上出现幻觉及 CPU 卡死的根源。
- **独立测试**：运行 `tests/test_deterministic_tools.py`、`tests/test_text_and_gateway.py` 与 `tests/test_review_fixes_runtime.py`，针对 9 项纯函数及工具包装器逐一检验闰平年 2 月边界、无“日/号”数字防误吸、36 个月账期限制及 5 类嵌套量词 ReDoS 拦截。
- **关联需求**：`FR-001`、`FR-005`
- **验收场景**：
  1. **前提** 文本含全角标点、零宽字符、跨行折行、无“日/号”后缀数字（如 `2026年10月5G特惠包`）、11 位手机号或活动编号（如 `25JS206149`），**当** 调用 `normalize_text`、`text_contains`（默认剥离半/全角空白与换行）与 `extract_dates`（可配 `defaultYear` 补全 `M月d日/号`），**则** `text_contains` 命中跨行折行串，`extract_dates` 仅提取真实日历 8 位 `yyyyMMdd` 及有序统计而绝不误吸干扰数字。
  2. **前提** 需要计算单日/整月窗口、转换日期格式、日历加减、展开多账期或比较秒级时间差，**当** 调用 `date_range`、`format_date`（单值 `value` 或批量 `values` 接入 `VALUE_TOOLS`）、`date_shift`、`expand_period`（2 段有序 `A$B` 闭区间、多段离散排序、连接符区间，受 `agent_max_period_months` 默认 36 限制）与 `time_diff`，**则** 精确依据 Python `calendar`/`datetime`/`timedelta` 输出并拒绝布尔或越界月份参数。
  3. **前提** 传入合法或恶意嵌套量词正则（如 `(a+)+`、`([a-z]*)*`、`(?:a|b+){2,}`），**当** 调用 `regex_extract`（经 `safe_regex_compile` 语法树拦截及 `MAX_REGEX_TEXT_LENGTH = 200_000` 文本上限保护），**则** 高危正则在编译前被 `ValueError` 阻断触发 `ModelRetry`，合法正则提取非空去重 `matches`/`allMatches`/`first`/`count`（无捕获组且 `group=1` 时自动回退 `group=0`）。

#### 用户故事 3（US3）— XML/JSON 双协议统一网关客户端、XXE 安全防护与并发保护（优先级：P2）

- **用户旅程**：作为生产态对外通信边界的运维与安全负责人，我希望 `UnifiedGatewayXmlClient` 在真实网关模式下无缝兼容前代 Java Jackson XML 与新 JSON 双协议接口，在严格防范 XXE/实体扩展、超深嵌套 JSON 溢出和 3xx 重定向的同时，提供安全自定义请求头、报文脱敏预览、信号量限流与幂等指数退避重试。
- **优先级理由**：外联网关是平台唯一出站系统接口边界，必须兼顾历史字节级兼容与全维度安全防护。
- **独立测试**：基于 `httpx.MockTransport` 模拟正常响应、GBK 无数据报文、CDATA 含 `<!DOCTYPE html>`、真实 XXE/Billion Laughs 攻击载荷、1500 层深 JSON、302/401/404/503 状态码及 6 并发（限流 2）执行测试。
- **关联需求**：`FR-006`、`FR-007`、`FR-008`
- **验收场景**：
  1. **前提** 传入 XML 或 JSON 接口契约与入参，**当** 生成请求体与脱敏预览，**则** `java` 风格 XML 按字母序输出且空值带 `xsi:nil="true"`，并与 Java `XmlMapper` 逐字节一致；非法 XML 标签被 `_validate_tag` 拦阻；JSON 保留原生结构与自定义安全头；`mask_xml`/`mask_json`/`build_request_preview` 脱敏 `app_id`/`access_token`/`verify_code` 与 11 位手机号且保留 `${占位符}`。
  2. **前提** 网关返回含 BOM/控制字符的 XML、GBK 无记录报文、CDATA 中含 `<!DOCTYPE html>` 的正常短信、真实 XXE/实体扩展载荷、超长报文（`> 5,000,000` 字符）或 1500 层深 JSON，**当** 执行 `parse_xml`/`extract_records` 或 `parse_json_body`/`extract_json_records`，**则** 正常 CDATA 短信顺利通过，`DOCTYPE`/`ENTITY` 与超限报文被拒，1500 层深 JSON 通过显式栈安全处理且支持 `auto`/`object`/`list`/`scalar`/`none` 五模式和点分列聚合。
  3. **前提** 配置并发限额 `max_concurrency`、禁用重定向且接口声明 `idempotent=true`，**当** 遭遇超时、传输异常或 HTTP `429`/`502`/`503`/`504`，**则** 并发峰值为信号量严格限流，瞬态异常按 `0.5 * 2^(attempt-1)` 指数退避重试；3xx/401/403/404 与非幂等请求立即分类报错不重试。

#### 用户故事 4（US4）— 双级覆盖本地 `MockGatewayClient` 与引用计数热更新网关代理（优先级：P2）

- **用户旅程**：作为本地开发调试人员与高可用热配置维护者，我希望在 Mock 模式下能通过 `data/mock-gateway` 优先覆盖 `seed/mock-gateway`、防路径穿越且允许 JSON 契约自动复用转换同名 XML 样例；同时在运行期切换网关配置时，`ReloadableGatewayClient` 通过引用计数排空在途请求并安全关闭旧连接池而不中断在线业务。
- **优先级理由**：双级 Mock 降低全套模板联调成本，引用计数排空保障运行期热更新“不断链、零泄漏”。
- **独立测试**：构造含路径穿越名称、11 位路由号样例、跨格式 XML→JSON 回退目录测 `MockGatewayClient`；构造带慢关闭 `aclose()` 桩并用超时取消在途任务测 `ReloadableGatewayClient.swap`。
- **关联需求**：`FR-009`、`FR-010`
- **验收场景**：
  1. **前提** 配置双级目录 `root` 与 `fallback_root`，**当** `MockGatewayClient.invoke` 处理带 11 位数字 `route_value` 的请求时，**则** 按先 `root` 后 `fallback_root`、先 `<name>.<route>.json/.xml` 后 `<name>.json/.xml` 命中；JSON 接口无 `.json` 文件但有同名 `.xml` 时通过 `xml_to_json_data` 无损转换响应；非法接口名或目录外软链接被立即拒止。
  2. **前提** `ReloadableGatewayClient` 存在多个在途 `invoke` 请求，**当** 执行 `swap(new_client)`，**则** 后续新请求立即路由至 `new_client`，原槽位在途请求完成后待 `in_flight` 归零自动调用 `aclose`；空闲被换下旧客户端立即进入异步退役队列。
  3. **前提** 某在途旧请求在 `swap` 后遭遇外层超时或外部取消（`CancelledError`），**当** `invoke` 进入 `finally` 且 `old_slot.in_flight` 归零，**则** 通过独立后台任务加 `asyncio.shield` 保护执行 `_safe_aclose`，确保旧连接池完全关闭不泄漏，应用停机 `aclose()` 清空全部活跃与退役槽位。

### 2.2 成功标准

- **SC-001**：12 项平台工具完整注册与权限隔离率 100% —— `build_tools()` 严格返回指定的 12 个工具，`VALUE_TOOLS` 仅包含 `{"format_date"}`，任意非白名单 Skill/API 无法通过 Schema 暴露或调用。
- **SC-002**：幂等请求去重与 cancel 接管成功率 100% —— 同工作区并发多发等价参数幂等 `call_api` 时底层网关物理调用严格为 1 次，leader 协程取消后存活协程 100% 接管完成；失败调用绝不写入幂等缓存。
- **SC-003**：确定性计算与正则拦截准确率 100% —— 闰平年、无“日/号”后缀干扰过滤、36 个月上限及 5 类高危 ReDoS 嵌套量词语法树阻断测试用例 100% 通过。
- **SC-004**：XML/JSON 双协议与安全边界达标 —— `java` 风格 XML 请求与 Java `XmlMapper` 逐字节 100% 一致；XXE/Billion Laughs 拦截率 100% 且正常 CDATA 短信放行率 100%；1500 层深 JSON 无 `RecursionError`；信号量并发峰值不超过 `max_concurrency`。
- **SC-005**：Mock 跨格式回退与热切零泄漏 —— JSON 接口利用同名 XML 样例无损转换准确率 100%；`ReloadableGatewayClient` 切换与取消排空下旧客户端 `aclose()` 完成率 100%；全部专项及全量后端套件（`uv run pytest -q` `196 passed in 51.41s`）与静态检查（`uvx ruff@0.11.0 check src tests`）零失败零告警。

### 2.3 假设

- **上下游职责边界**：`ApiContract` YAML 解析、`validate_args` 校验、`build_request`/`build_headers` 构造与 `safe_regex_compile` 来自 `RA-001`（`domain`）；工具注册载体 `AgentRunner`、工作区 `Workspace` 宿主与交卷核验属于 `RA-003`；网关热配置持久化与触发热重载接口位于 `RA-002` 与 `RA-005`。
- **网关协议假定**：生产统一网关暴露于 `{GATEWAY_URL}/openapi_3`，以报文内 `app_id`/`access_token` 鉴权并支持自定义安全头，禁止自动跟随 HTTP 3xx 重定向以防 SSRF。
- **单进程并发约束**：`UnifiedGatewayXmlClient` 信号量、`Workspace` 幂等复用态与 `ReloadableGatewayClient` 槽位引用计数均作用在单进程内存中，要求生产部署保持 `workers=1`。
- **工时核算口径**：本子规格 `33.0 人天` 覆盖 12 项平台工具（1,430 行源码）、网关连接器 5 个模块（1,373 行源码，总源码 2,803 行）以及 3 份专属测试套件（1,029 行）及关联安全加固测试的研发、对拍与验收全周期投入。

---

## 3. 术语与概念定义 【核心，如有新术语】

> 通用平台术语参见 `wiki/reference/glossary.md`；本表列出工具原语与网关连接器专属术语。

| 术语 | 英文/标识 | 定义 | 备注 |
| --- | --- | --- | --- |
| 确定性平台工具 | `build_tools` / 12 Tools | 面向单智能体暴露的 3 项资源查询调度工具与 9 项文本/日历/时间差/正则纯函数工具的统称，零业务逻辑硬编码 | 每次调用均写入 `Workspace.tool_calls` 并生成 `callId`（`t1..`） |
| 幂等并发接管 | `_idempotent_inflight` + `asyncio.shield` | 同一 `Workspace` 内多协程并发调用相同 `(name, canonical_json_args)` 幂等接口时，共享未决 `Future`；若 leader 协程取消，存活等待协程循环重夺控制权发起一次新请求 | 失败 `ApiResult(ok=False)` 不写入 `_idempotent_cache` |
| Jackson 兼容风格 | `gateway_xml_style="java"` | 与前代 Java `XmlMapper` 逐字对齐的 XML 序列化风格：无 `<?xml?>` 声明、顶层标签按字母序排列、空字段输出 `xsi:nil="true"` | 默认模式；可选切换 `"clean"` 风格 |
| 显式栈深嵌套展平 | `_MAX_FLATTEN_DEPTH` (`128`) | XML/JSON 展平及 JSON 错误搜索采用显式迭代栈替代递归，深度超过 `128` 层退化为原始串，避免触发 Python 默认递归栈上限 `RecursionError` | `MAX_XML_CHARS`/`MAX_JSON_CHARS` 上限 `5,000,000` |
| 引用计数排空槽位 | `_ClientSlot` | `ReloadableGatewayClient` 内封装底层 `client`、`in_flight`、`retired`、`closed` 状态的槽位对象，支撑 `swap` 后待在途归零安全释放连接池 | 经 `threading.Lock` 与 `asyncio.shield` 保护 |

---

## 4. 用户角色 【核心】

| 角色 | 类型 | 本需求中可执行的操作与数据范围 | 权限/安全约束 |
| --- | --- | --- | --- |
| 单智能体（大模型） | AI 运行参与者 | 通过 `build_tools()` 注册清单查询白名单 Skill、调用白名单接口并执行检索和确定性文本/日期运算 | `load_skill` 与 `call_api` 受 `prepare` 动态 `enum` 限制，越权即触发 `ModelRetry` |
| 外部统一网关 | 外部系统角色 | 接收平台发送的 `POST {GATEWAY_URL}/openapi_3` XML 或 JSON 请求并回传业务报文 | 以报文内 `app_id`/`access_token` 鉴权；禁止跟随 3xx 重定向 |
| 平台开发/测试人员与运行容器 | 内部/运维角色 | 在 Mock 模式下借双级文件目录联调；在 Live 模式下通过 `ReloadableGatewayClient` 热更新网关参数 | Mock 路径严格经 `_SAFE_MOCK_NAME_RE` 与 `is_relative_to` 防穿越校验；凭据热配置不落代码 |

---

## 5. 功能需求 【核心】

### 5.1 12 项确定性平台工具暴露与核心调度

#### FR-001 固定 12 项平台工具注册、记账与退回降级机制

- **来源**：`src/report_agent/runtime/tools.py`
- **描述**：统一向智能体注册 12 个通用平台工具，建立 `callId` 账本、过程事件发射及统一容错机制。
- **关联用户故事/成功标准**：`US1`, `US2` / `SC-001`
- **业务规则**：
  1. `build_tools(tool_retries)` 严格按序注册 12 个工具：`load_skill`、`call_api`、`query_result`、`normalize_text`、`text_contains`、`date_range`、`format_date`、`extract_dates`、`date_shift`、`expand_period`、`time_diff`、`regex_extract`。
  2. 每次成功或失败调用经 `_record` 在 `Workspace.tool_calls` 分配顺序 `callId`（`t1`, `t2`...）并发射 `tool` 过程事件。
  3. 非白名单或参数异常统一调用 `_fail_or_retry`：当 `ctx.retry < ctx.max_retries` 时抛出 `ModelRetry` 引导模型自纠；耗尽重试额度则返回包含 `callId` 与 `ok: False` 的结构化报错而不崩溃整次运行。
- **输入/触发**：`Agent` 挂载工具集与触发工具调用。
- **输出/结果**：标准工具返回字典及工作区 `ToolCall` 记录。
- **验收标准**：
  - AC-1：`build_tools(2)` 返回的工具名称精确等于上述 12 个工具名且顺序稳定。
  - AC-2：工具参数错误在重试额度内抛 `ModelRetry`，耗尽后返回含 `callId` 的结构化错误字典。

#### FR-002 `load_skill` 白名单隔离与单/批量去重加载

- **来源**：`src/report_agent/runtime/tools.py`
- **描述**：提供受模板白名单约束的纯文本 `SKILL.md` 读取能力，支持批量加载以减少模型交互轮次。
- **关联用户故事/成功标准**：`US1` / `SC-001`
- **业务规则**：
  1. `_prepare_load_skill` 从 `RunDeps.allowed_skills` 过滤有效列表并写入参数 `name` 和 `names`（支持 `items` 或 `anyOf` 分支）的 JSON Schema `enum`；当白名单为空时返回 `None` 自动隐藏该工具。
  2. `load_skill` 接收 `name` 与/或 `names: list[str]`，剔除空白并按请求保序去重；同时传入空名单或包含任意未授权 Skill 触发 `_fail_or_retry`。
  3. 合法加载的标识登记至 `workspace.loaded_skills`，单传 `name` 时返回精简标题块与接口 `param_hint()`，批量时以 `\n---\n\n` 拼接输出。
- **输入/触发**：模型调用 `load_skill(name=..., names=...)`。
- **输出/结果**：拼接后的 Skill Markdown 文档及关联接口参数提示。
- **验收标准**：
  - AC-1：传入 `names=["skill-a", "skill-a", "skill-b"]` 时去重拼接输出且 `workspace.loaded_skills` 不重不漏。
  - AC-2：模板 `allowed_skills` 为空时，传给模型的工具列表不包含 `load_skill`。

#### FR-003 `call_api` 参数校验、幂等去重与取消接管

- **来源**：`src/report_agent/runtime/tools.py`
- **描述**：代表智能体安全调用白名单网关接口，实现工作区级幂等请求去重、并发取消接管与摘要截断保护。
- **关联用户故事/成功标准**：`US1` / `SC-001`, `SC-002`
- **业务规则**：
  1. `_prepare_call_api` 将 `allowed_apis` 注入 `name.enum` 并在工具描述末尾拼接可用接口与参数提示；无可用接口时隐藏该工具。
  2. 调用前校验白名单归属及 `contract.validate_args(clean_args)`。
  3. 若 `contract.idempotent=True`，以 `(name, json.dumps(clean_args, sort_keys=True, ensure_ascii=False, default=str))` 为键：优先命中 `_idempotent_cache`；若有在途 `Future` 则通过 `await asyncio.shield(inflight)` 等待；若捕捉 `asyncio.CancelledError` 且当前任务自身未处于取消态（`cur_task.cancelling() == 0`），自动循环重接控制权并发起请求。
  4. 捕获网关意外异常转化为 `ApiCallResult(ok=False)` 不阻断运行；`ok=False` 绝不写入 `_idempotent_cache`；成功结果完整存 `Workspace.results`，仅向模型返回按 `maxPreviewChars` 和 `agent_preview_rows` 截断的摘要预览与 `resultId`。
- **输入/触发**：模型调用 `call_api(name, args)`。
- **输出/结果**：含 `callId`、`resultId`、`ok`、`count`、`columns`、`preview` 与提示的响应字典。
- **验收标准**：
  - AC-1：同工作区并发调用参数顺序不同的等价幂等接口时仅触发 1 次底层 `gateway.invoke`，各自独立分配 `callId` 但共享 `resultId`。
  - AC-2：leader 协程取消后存活等待协程自动重发调用并正常返回唯一成功结果；首轮失败不写入缓存。

#### FR-004 `query_result` 单/多结果集结构化过滤引擎

- **来源**：`src/report_agent/runtime/tools.py`
- **描述**：对工作区已存的一个或多个完整接口结果执行 `AND`/`OR` 条件筛选、列投影、排序及严格列名核验。
- **关联用户故事/成功标准**：`US1` / `SC-001`
- **业务规则**：
  1. 定义 `Condition` 与 `OrderBy` 模型（均设 `extra="forbid"`），`Condition.op` 支持 `equals`、`contains`、`notContains`、`normalizedContains`、`normalizedNotContains`、`startsWith`、`between`，支持 `before` 截断和 `prefixLen` 前缀截取（要求正整数，非布尔；`between` 校验 `endValue` 非空且下限不大于上限）。
  2. 支持 `resultId` 单结果模式与 `resultIds` 去重多结果合并模式；多结果模式任一元素为空或指向 `ok=False` 结果立即报错（含失败 `resultId` 与 `callId`），防止静默漏掉失败月份，每行额外附带来源 `resultId` 和行号 `row`。
  3. `_validate_query_columns` 汇集 `r.columns.keys()` 与实际记录键形成全量已知列集，即使接口 0 行记录也不放行拼写错误的筛选列、排序列或投影列；禁止布尔值 `limit`，未传或超限按 `agent_query_default_limit`（默认 20）与 `agent_query_max_limit`（默认 100）约束。
- **输入/触发**：模型调用 `query_result(...)`。
- **输出/结果**：`{callId, resultId/resultIds, total, rows}` 或报错。
- **验收标准**：
  - AC-1：对多月结果使用 `resultIds` 结合 `where(between + prefixLen)`、`anyOf` 和 `orderBy(desc=True)` 准确合并返回带来源 `resultId` 和 `row` 的匹配行。
  - AC-2：对 `no_data=True` 的 0 行结果传入不存在列名时，稳定报错提示可用列名。

### 5.2 9 项确定性纯函数计算原语

#### FR-005 文本、日历、账期、时间差与防 ReDoS 正则纯函数及工具包装

- **来源**：`src/report_agent/runtime/text_tools.py`、`src/report_agent/runtime/tools.py`
- **描述**：提供 9 项无业务硬编码的纯函数算法与带默认 `document` 注入的工具外壳，全面接管机械计算。
- **关联用户故事/成功标准**：`US2` / `SC-003`
- **业务规则**：
  1. `normalize_text` / `text_contains`：使用 `@lru_cache(maxsize=64)` 缓存 NFKC + `FIXED_CHARS_TO_REMOVE` + `_ZERO_WIDTH_CHARS` + `extra_chars` 转换表；`text_contains` 在 `normalize=True` 时额外剥离半/全角空格、制表符与换行以命中跨行折行文本，不传 `text` 时默认读工作区单据全文。
  2. `date_range(time, unit)` & `format_date`（`convert_date`）：`date_range` 兼容带前缀分隔/紧凑日期及 `unit="month"` 下的 6 位年月；`format_date` 使用 `@lru_cache(maxsize=128)` 编译 Java 风格格式并同时支持单值 `value` 与非空批量列表 `values`（且是唯一进入 `VALUE_TOOLS` 的工具）。
  3. `extract_dates(text, defaultYear)`：执行 4 类正则扫描（中文年月日必须以 `日/号` 结尾、同分隔符年月日、独立 8 位 `yyyyMMdd`、带 `defaultYear` 的 `M月d日/号`），全部经 `_date()` 真实日历验证剔除 2 月 30 日等非法日期，并杜绝误吸活动编号与 11 位手机号，返回去重保序 `dates`、升序 `sorted`、`min`、`max`、`count`。
  4. `date_shift` & `time_diff`：`date_shift` 支持 `days`/`endDays`（禁布尔及起点晚于终点）输出真实日历偏移与 14 位起止时间戳；`time_diff` 计算精确秒差 `{diffSeconds, absSeconds, later}`。
  5. `expand_period`：4 级解析（`$`/`，`/`;` 等多段——恰好 2 段有序 `A$B` 展闭区间，否则离散去重升序；单一纯年月；区间连接符 `~`/`至`/`-` 区分日期内连字符；单日或时间戳），受 `agent_max_period_months`（`MAX_PERIOD_MONTHS=36`）约束。
  6. `regex_extract`：调用 `safe_regex_compile` 拦截嵌套量词 ReDoS，校验文本不超过 `MAX_REGEX_TEXT_LENGTH = 200_000` 字符，提取非空去重 `matches`/`allMatches`/`first`/`count`（无捕获组且 `group=1` 时自动取 `group=0`）。
- **输入/触发**：纯函数直接调用或智能体工具调用。
- **输出/结果**：确定性计算结果结构字典（含 `callId`）或经 `_fail_or_retry` 抛出 `ModelRetry`。
- **验收标准**：
  - AC-1：9 项纯函数在平/闰年边界、活动编号防误吸、多账期展开超 36 个月拦截及 5 类高危 ReDoS 拦截上 100% 命中预期。
  - AC-2：文本/提取工具不传 `text` 时自动读取 `ctx.deps.document`，入参类型错误（如 `bool` 传入 `days`/`group`）安全拦截并进入重试。

### 5.3 双协议统一网关客户端与安全防护

#### FR-006 网关抽象契约、`expat` 防 XXE 与 XML/JSON 对称五模式抽取

- **来源**：`src/report_agent/gateway/base.py`
- **描述**：定义 `GatewayClient` 协议与 `ApiCallResult` 数据类，构建双协议响应解码、安全校验与对称记录抽取基座。
- **关联用户故事/成功标准**：`US3` / `SC-004`
- **业务规则**：
  1. `decode_xml` 依序按 XML 声明 `encoding` → HTTP 头编码 → `utf-8` → `gb18030` 解码并剥离 BOM；`sanitize_xml_text` 清除非法控制字符与非法数字字符引用。
  2. `parse_xml` 限制报文上限 `MAX_XML_CHARS = 5_000_000`，当文本出现 `DOCTYPE`/`ENTITY` 线索时触发 `expat` 词法钩子 `_check_xml_security` 拦截声明，但正常放行出现在 CDATA 内容块中的 `<!DOCTYPE html>` 短信原文。
  3. `parse_json_body` 限制 `MAX_JSON_CHARS = 5_000_000` 并捕获深度触发的 `RecursionError`；`_flatten_xml_element`、`_flatten_json_dict` 与 `_first_json_text` 全部使用显式栈，最大展平深度 `_MAX_FLATTEN_DEPTH = 128`。
  4. `extract_records` 与 `extract_json_records` 严格对齐：`noData` 优先级高于 `success`，支持 `auto`（含标准 `content.list` 自动解包）、`object`、`list`、`scalar`（保留 `"0"`/`"false"`）、`none` 五模式，以及通过 `_extract_xml_dotted` / `_extract_json_dotted` 同步实现点分列跨嵌套与多节点/数组聚合；并导出 `xml_to_json_data` 无损转换。
- **输入/触发**：接收响应字节流/文本与 `ApiContract`。
- **输出/结果**：标准化的 `ApiCallResult` 对象。
- **验收标准**：
  - AC-1：真实 XXE 与 Billion Laughs 被 `expat` 阻断，而包裹在 `<![CDATA[...]]>` 中的 HTML `DOCTYPE` 短信正常放行抽取。
  - AC-2：1500 层深嵌套 JSON 错误报文或嵌套字典在显式栈遍历下无 `RecursionError` 安全处理；XML 与 JSON 在五种模式下抽取等价。

#### FR-007 `UnifiedGatewayXmlClient` 双协议组包、脱敏预览与安全头合并

- **来源**：`src/report_agent/gateway/unified_xml.py`
- **描述**：按照统一网关 `/openapi_3` 规范构造 `java`/`clean` 风格 XML 及原生 JSON 请求体、脱敏展示文本及合并安全头。
- **关联用户故事/成功标准**：`US3` / `SC-004`
- **业务规则**：
  1. `build_request_xml` 支持 `java`（无 XML 声明、`_JAVA_ORDER` 字母序、`xsi:nil="true"`，与前代 Java Jackson `XmlMapper` 输出逐字节一致）与 `clean`（UTF-8 声明与空标签）双风格；所有标签名经 `_validate_tag` 防注入校验，值经 `sanitize_xml_text` 与 `escape` 转义。
  2. `_build_request_json_obj` / `build_request_json` 构造 `{"operation_in": {...}}` 结构（支持解包单层 `operation_in`），维持原生布尔/数值/数组结构并限制请求体嵌套深度上限 `128` 层。
  3. `mask_xml`、`mask_json`（异常回退正则）与 `build_request_preview` 对 `app_id`、`access_token`、`verify_code` 与 11 位手机号（`route_value`、`userMobile` 等）脱敏且保留 `${占位符}`。
  4. `_merge_http_headers` 以大小写无关覆写方式将契约自定义安全请求头合并到默认 `Content-Type`/`Accept` 请求头中。
- **输入/触发**：`UnifiedGatewayXmlClient.invoke` 或管理端预览调试调用 `build_request_preview`。
- **输出/结果**：可直接发送的载荷与安全脱敏预览字符串。
- **验收标准**：
  - AC-1：`java` 风格序列化字节串与 Java `XmlMapper` 对拍基准 100% 一致；非法 XML 标签名（如含 `<` 或空格）触发 `ValueError`。
  - AC-2：脱敏预览隐藏凭证与中间 4 位手机号，同时保留未传参数 `${参数名}` 占位符。

#### FR-008 真实网关并发保护、禁用重定向、HTTP 分类与幂等退避重试

- **来源**：`src/report_agent/gateway/unified_xml.py`
- **描述**：为外联 HTTP 调用建立 SSRF、连接池过载与瞬态故障恢复防线。
- **关联用户故事/成功标准**：`US3` / `SC-004`
- **业务规则**：
  1. 初始化强制校验 `base_url` 非空且仅限 `http://` 或 `https://`，拼接 `/openapi_3`；`httpx.AsyncClient` 强制设 `follow_redirects=False` 并配置 `httpx.Limits(max_connections=max(100, max_concurrency), max_keepalive_connections=min(32, max_concurrency))`。
  2. 每次请求通过 `async with self._sem:` 受 `asyncio.Semaphore(max_concurrency)`（默认取 `GATEWAY_MAX_CONCURRENCY=32`）限流。
  3. 非 200 响应经 `_classify_http_error` 明确归类 3xx（提示禁止重定向）、401/403、404、429、4xx、5xx。
  4. 仅当 `contract.idempotent=True` 时，对 `ConnectTimeout`、`TimeoutException`、`TransportError` 及 HTTP `429`/`502`/`503`/`504` 按 `0.5 * 2 ** (attempt - 1)` 指数退避重试（总次数上限 `contract.retry.maxAttempts`）；非幂等、3xx、401/403、404 等单次即止；成功响应 `raw` 字段限截前 `200,000` 字符（大于 `200,000` 跳过 `indent=2` 格式化，错误报文截前 `20,000` 字符）。
- **输入/触发**：`UnifiedGatewayXmlClient.invoke(contract, args)`。
- **输出/结果**：含 `attempts`、`cost_ms`、`http_status`、`request_preview`、`raw` 的 `ApiCallResult`。
- **验收标准**：
  - AC-1：并发发出 6 个请求且 `max_concurrency=2` 时实测最高并发严格不超过 2。
  - AC-2：HTTP 302 不自动跳转并报重定向错；幂等接口遇到 503 重试成功且记录正确 `attempts`，非幂等接口遇到 503 不重试。

### 5.4 双级本地 Mock 与热更新代理

#### FR-009 双级安全 `MockGatewayClient` 与 XML→JSON 无损回退

- **来源**：`src/report_agent/gateway/mock.py`
- **描述**：提供脱机与测试环境使用的本地文件网关，具备目录逃逸拦截与跨格式样例自动转换能力。
- **关联用户故事/成功标准**：`US4` / `SC-005`
- **业务规则**：
  1. 先构造脱敏 `request_preview` 并校验契约名称匹配 `_SAFE_MOCK_NAME_RE = ^[A-Za-z0-9_\-]{1,128}$`；`route_value` 仅当全为 ASCII 数字时参与精确路由拼装。
  2. `_search_roots` 按优先 `root`（`data/mock-gateway`）再 `fallback_root`（`seed/mock-gateway`）去重排序；对每次文件读取通过 `Path.resolve().is_relative_to(root_resolved)` 与 `.is_file()` 严格阻断路径穿越与目录外软链接逃逸。
  3. 命中顺序为 `<name>.<route>.json/.xml` → `<name>.json/.xml`；当 `contract.is_json=True` 且未命中 `.json` 文件时，自动搜索同名 `.xml` 样例并经 `parse_xml` + `xml_to_json_data` 无损转回 JSON 文本后走 `parse_gateway_json_response` 抽取。
- **输入/触发**：`MockGatewayClient.invoke(contract, args)`。
- **输出/结果**：标准 `ApiCallResult`（含脱敏预览与解析状态）。
- **验收标准**：
  - AC-1：合法路由号优先命中 `root` 下带路由号样例，缺失时自动回退至 `fallback_root` 或默认文件。
  - AC-2：尝试 `../secret` 等非法名称或指向根目录外的软链接文件被立即拦截拒绝；JSON 契约成功自动复用同名 `.xml` 样例无损输出。

#### FR-010 `ReloadableGatewayClient` 引用计数排空热更新代理

- **来源**：`src/report_agent/gateway/reloadable.py`
- **描述**：包装真实或 Mock 网关实例，实现运行期配置热重载时新老实例无缝平滑切换与连接池零泄漏释放。
- **关联用户故事/成功标准**：`US4` / `SC-005`
- **业务规则**：
  1. 使用 `threading.Lock` 保护当前槽位 `_slot`（`_ClientSlot` 记录 `client`、`in_flight`、`retired`、`closed`）、`_retired_inflight` 与 `_pending_close`。
  2. `invoke` 在锁内捕获当前 `slot` 并将 `in_flight += 1`；退出（含正常返回、异常或外层 `CancelledError`）时递减 `in_flight`：若 `slot.retired` 且 `in_flight <= 0` 且未关闭，标记 `closed=True` 并挂入后台任务配合 `await asyncio.shield(task)` 执行 `_safe_aclose(slot.client)`，确保外层取消时底层连接池依然能完成释放。
  3. `swap(new_client)` 原子将旧槽位标为 `retired=True` 并切换 `_slot`：若旧槽位当前 `in_flight <= 0` 则入 `_pending_close` 并异步调度 `aclose_retired()`；若仍在途则记入 `_retired_inflight` 等待最后调用退出时关闭；同对象调用直接返回 `None`。
  4. 应用退出调用 `aclose()` 时排空 `_pending_close`、等待全部 `_closing_tasks` 并依次关闭活跃与尚未关闭的退役实例。
- **输入/触发**：`ReloadableGatewayClient.invoke`、`swap`、`aclose_retired`、`aclose`。
- **输出/结果**：新调用零感知路由最新客户端，退役客户端连接池 100% 异步释放。
- **验收标准**：
  - AC-1：在途请求执行中调用 `swap(new_client)`，后续新调用立即使用新实例，旧请求正常结束后旧实例自动触发 `aclose()`。
  - AC-2：在途请求遭遇 `asyncio.TimeoutError` / `CancelledError` 取消后，退役慢关闭实例依然完整完成 `aclose()`。

---

## 6. 非功能需求 【补充】

| 类型 | 编号 | 说明 | 验收方式 |
| --- | --- | --- | --- |
| 零业务硬编码与纯正性 | `NFR-001`（宪章原则 I, II） | `tools.py`、`text_tools.py` 与 `gateway/` 严禁硬编码具体模板 ID、业务名称或网关 `processCode`；`VALUE_TOOLS` 严格维持 `{"format_date"}` | 代码审阅与 `tests/test_deterministic_tools.py` 校验 |
| 单进程并发与资源池安全 | `NFR-002`（宪章原则 III） | `Workspace` 幂等字典、`UnifiedGatewayXmlClient` 信号量与 `ReloadableGatewayClient` 槽位计数基于单进程 `workers=1` 设计；连接池与并发阈值可配置 | `tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py`、`tests/test_runtime_config_hot_reload.py` |
| 解析与算法防 DoS 边界 | `NFR-003`（宪章原则 V, VI） | XML/JSON 严格限制 `5,000,000` 字符、展平最大 `128` 层、显式栈防 1500 层 `RecursionError`；正则经 `safe_regex_compile` 拦截且文本限 `200,000` 字符；`expand_period` 跨度限 `36` 月 | `tests/test_api_json_gateway.py`、`tests/test_text_and_gateway.py` |
| 安全防注入与敏感信息脱敏 | `NFR-004`（宪章原则 VI） | 禁止 HTTP 重定向、`expat` 防 XXE/实体扩展、XML 标签 `_validate_tag`、Mock 路径 `is_relative_to` 防穿越；`mask_xml`/`mask_json` 对凭证及手机号脱敏且源码无明文密钥 | `tests/test_text_and_gateway.py`、`tests/test_api_json_gateway.py` |
| 过程事件可观测性 | `NFR-005`（宪章原则 VII） | 12 项工具每次调用登记 `callId` 并推 `tool` 事件；网关记录 `cost_ms`、`attempts`、`http_status` 与脱敏 `request_preview` | `tests/test_review_fixes_runtime.py` |
| 前端与分包隔离边界 | `NFR-006`（宪章原则 VIII） | 本需求不涉及前端页面或构建分包修改；仅向管理端调试/运行预览接口提供脱敏报文与 `requestPreview` 数据 | 核对改动文件路径及 `git status` |

---

## 7. 数据与存储需求 【补充】

> 工具执行状态存于单次运行内存工作区，网关模块无数据库状态；仅 `MockGatewayClient` 只读访问本地样例目录。

| 数据对象/存储位置 | 变更类型 | 关键字段与口径 | 一致性/留存策略 | 关联需求 |
| --- | --- | --- | --- | --- |
| `Workspace` 幂等与工具账本（内存） | 使用/写入 | `_idempotent_cache`、`_idempotent_inflight`、`results`（`rN`）、`tool_calls`（`tN`）、`loaded_skills` | 单次运行生命期内存态；失败结果不写入 `_idempotent_cache` | `FR-001`~`FR-004` |
| `text_tools` 算法缓存（内存） | 新增 | `_build_remove_table`（`lru_cache(64)`）、`_compile_date_pattern`（`lru_cache(128)`） | 进程内只读纯函数缓存，固定有界容量 | `FR-005` |
| `DATA_DIR/mock-gateway/` 与 `src/report_agent/seed/mock-gateway/` | 只读 | `<接口名>.<route>.json/.xml` 或 `<接口名>.json/.xml` | 只读访问，严格路径越界与文件名正则检查 | `FR-009` |

---

## 8. 外部接口与集成 【补充】

| 接口/系统 | 方向 | 交互内容 | 是否新增 | 关联需求 | 备注 |
| --- | --- | --- | --- | --- | --- |
| 统一网关服务（`{GATEWAY_URL}/openapi_3`） | 出站 | 发送 `operation_in` XML（`java`/`clean`）或 JSON（`{"operation_in": {...}}`）请求，接收 `operation_out` 响应 | 是（连接器实现） | `FR-006`~`FR-008` | 真实模式由 `UnifiedGatewayXmlClient` 发起 |
| 本地样例文件系统（`MockGatewayClient`） | 只读本地 I/O | 读取 `.json` / `.xml` 脱敏样例并支持 XML→JSON 无损转换 | 是（本地 Mock 实现） | `FR-009` | 单元测试及离线演示默认启用 |
| 单智能体运行器（`RA-003`） | 入站（Python 工具/协议） | 通过 `build_tools` 暴露 12 工具及通过 `ReloadableGatewayClient` 代理调用网关 | 否（对接 `RunDeps`） | `FR-001`~`FR-005`, `FR-010` | 共享 `Workspace` 与 `Settings` |

### 8.1 出站网关与模型接口契约摘要（涉及时填写）

| 接口/工具 | 调用方向 | 协议与端点 | 路由/识别字段 | 成功判定 | 关键失败与降级策略 |
| --- | --- | --- | --- | --- | --- |
| 统一网关通用接口（`querySMSSendInfo`、`BOSS_QryBalanceFlowLog`、`cc_pretty_num_info_query` 及后续扩展契约） | 平台 → `{GATEWAY_URL}/openapi_3` | HTTP POST（`application/xml` 或 `application/json`） | `processCode` + 报文内 `app_id` / `access_token` | `noData` 优先于 `success` 规则判定；HTTP 200 且满足 `success.path == equals` | 3xx/401/403/404 及非幂等立即返 `ok=False`；幂等瞬态错误按 `0.5 * 2^(attempt-1)` 指数退避重试 |

### 8.2 三类独立交付物涉及情况

| 独立文档 | 涉及情况 | 判断依据与范围摘要 | 确认来源/日期及关联需求 |
| --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 本需求实现向外部已有统一网关发起出站协议适配与平台内部 12 工具暴露，不新增或变更面向外部上游系统的 REST/SSE/`postMessage` 入站接口契约 | 归档拆分确认 / 2026-11-16；`FR-001`~`FR-010` |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 本需求只构建通用连接器与双级 Mock 引擎，不包含批量生产模板、`SKILL.md`、`apis/*.yaml` 或 `seed/mock-gateway` 资产迁移清单（归属 `RA-008`） | 归档拆分确认 / 2026-11-16；`FR-009` |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | `GATEWAY_*` 及 `AGENT_*` 环境变量与运行期热配置均已纳入项目既有基线配置体系，本次归档不涉及容器镜像或运维动作变更 | 归档拆分确认 / 2026-11-16；`FR-008`, `FR-010` |

---

## 9. 边界与约束 【补充】

### 9.1 范围边界

**本次需求包含（In Scope）：**

- `src/report_agent/runtime/tools.py` 与 `src/report_agent/runtime/text_tools.py`（12 项平台工具及 9 项纯函数算法）。
- `src/report_agent/gateway/{__init__.py,base.py,unified_xml.py,mock.py,reloadable.py}`（网关抽象协议、解析抽取基座、双协议客户端、双级 Mock 与引用计数热更新代理）。
- 核心测试验证：`tests/test_deterministic_tools.py`、`tests/test_text_and_gateway.py`、`tests/test_api_json_gateway.py`（并协同 `test_api_response_modes.py`、`test_review_runtime.py`、`test_review_fixes_runtime.py`、`test_runtime_config_hot_reload.py` 交叉验证）。

**本次需求不包含（Out of Scope）：**

- `ApiContract` YAML 解析建模与 `safe_regex_compile` 源码实现（归属 `RA-001`，本需求直接复用调用）。
- `AgentRunner` 运行主回路、`EvidenceChecker` 交卷校验与 `Workspace` 结构定义（归属 `RA-003`）。
- 运行期热配置持久化存储 `runtime_config.py` 与工作台热配置 API（归属 `RA-002` 与 `RA-005`）。
- 生产 3 个 `apis/*.yaml` 契约文件与 `seed/mock-gateway/` 脱敏样例文件编写（归属 `RA-008`）。

### 9.2 技术与业务约束

- **禁止向 `VALUE_TOOLS` 私自扩展**：除 `format_date` 外，其余工具输出不得绕过 `EvidenceChecker` 直接当成最终报告核验等价来源。
- **Mock 与网关安全红线**：`follow_redirects=False`、`_SAFE_MOCK_NAME_RE`、`is_relative_to`、`expat` XXE 防护与显式栈 `_MAX_FLATTEN_DEPTH` 禁止任何分支绕过。
- **测试隔离边界**：禁止在单元测试中发起真实内网统一网关请求，必须使用 `httpx.MockTransport` 或临时目录上的 `MockGatewayClient`。

---

## 10. 异常场景与边界情况 【核心】

| 编号 | 场景描述 | 触发条件 | 预期处理方式 | 是否阻断主流程 | 优先级 | 关联需求 |
| --- | --- | --- | --- | --- | --- | --- |
| `EX-001` | 工具重试耗尽降级 | `date_range`/`format_date`/`date_shift`/`expand_period`/`time_diff`/`regex_extract`/`query_result` 连续入参错误或空 `values: []` | 前 `tool_retries` 次抛 `ModelRetry` 纠偏，耗尽由 `_fail_or_retry` 返回含 `callId` 与 `ok: False` 的结构化字典 | 否（交由模型报 `not_found`） | 高 | `FR-001`, `FR-004`, `FR-005` |
| `EX-002` | 超大或超深嵌套报文 DoS | XML/JSON 超过 `5,000,000` 字符或 JSON 嵌套 1500 层触发原生递归限制 | 入口按最大长度直接拦截；展平与错误文本提取全面采用显式栈控制（限 `128` 层），大于 `200,000` 字符跳过 `indent=2` 美化 | 否（当前接口记 `ok=False`） | 高 | `FR-006`, `FR-008` |
| `EX-003` | 点分列跨数组与空节点对齐 | `records.columns` 配 `level_info.event_name` 穿过同名多节点或数组，含 `xsi:nil`/`None`/空白 | `_extract_xml_dotted` 与 `_extract_json_dotted` 同步过滤空值——全空 `""`、单值标量文本、多值紧凑 JSON 数组 | 否 | 中 | `FR-006` |
| `EX-004` | 幂等在途 leader 协程被取消 | 多协程等待同参数幂等 `call_api` 时，发起请求的 leader 协程被取消 | leader 正常抛出 `CancelledError`，存活等待协程检测自身未取消后自动重接网关请求写入唯一结果 | 否（健康协程平滑完成） | 高 | `FR-003` |
| `EX-005` | Mock 非法命名或目录外软链 | 契约名含 `../` 等特殊字符或样例文件为指向根目录外软链接 | `_SAFE_MOCK_NAME_RE` 与 `Path.resolve().is_relative_to()` 阻断读取并返回失败，绝不泄露出目录外宿主文件 | 否（返 `ok=False`） | 高 | `FR-009` |
| `EX-006` | 热切后在途退役请求被超时取消 | `ReloadableGatewayClient.swap` 后旧槽位在途请求遇超时取消并恰好 `in_flight` 归零 | `finally` 中通过独立后台任务配合 `asyncio.shield` 执行 `_safe_aclose`，保证慢关闭连接池完整关闭 | 否（外层接收取消，连接池不泄漏） | 高 | `FR-010` |

---

## 11. 待确认事项 【核心】

> 本需求为已交付归档之工具与网关基础子系统，全部协议、边界与安全问题均已在实现与回归验证中闭环解决，当前无未关闭阻塞问题。

| 编号 | 问题描述 | 影响范围 | 责任方 | 期望确认日期 | 状态 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `Q-001` | 统一网关 JSON 新接口与存量 Java XML 接口是否共享连接器、脱敏规则与 Mock 样例转换路径 | `FR-006`, `FR-007`, `FR-009` | 网关架构组 | 2026-11-16 | 已关闭 | `UnifiedGatewayXmlClient` 按 `contract.is_json` 分发双协议并共享信号量与重试策略；`MockGatewayClient` 支持 XML→JSON 自动无损回退且两者五模式点分列抽取完全等价 |

---

## 附录：原始需求描述 【补充】

```text
智能申告报告填写与资源治理平台（report-agent）全栈研发工作拆分（子规格 004/008，需求编号 RA-004，33.0 人天）：
负责向智能体暴露的 12 个确定性平台工具（load_skill 白名单批量加载、call_api 工作区幂等去重与 leader 取消接管、query_result 多结果集与 0 行列名检验、以及 normalize_text/text_contains/date_range/format_date/extract_dates/date_shift/expand_period/time_diff/regex_extract 9 项纯函数确定性文本/日历/正则原语）以及 XML/JSON 双协议统一网关连接器、expat 防 XXE、显式栈深嵌套防护、双级本地 Mock 网关和引用计数排空热更新代理。
```

---

## 变更记录（Changelog）

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | AiCoding(codex) | 依据 `report-agent` 工具与网关源码及测试基线完成初版规格拆分归档 |
| 2.0 | 2026-11-16 | AiCoding(codex) | 按改造后中文 Spec-Kit 模板与 `/sdd-documentation` 取证标准重构升级为全章节闭环 SDD 规格文档 |

---

## 增量更新说明

> 本文档按 `report-agent` 中文 Spec-Kit 模板与 SDD 取证规范生成；后续如有范围或契约变更，同步更新对应章节与 `变更记录` 并联动刷新 `plan.md` 与 `tasks.md`。
