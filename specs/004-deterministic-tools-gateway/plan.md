# 设计文档（Feature Design Spec）：12 项确定性平台工具原语与双协议热更新外部网关连接器

<!-- #Created By AiCoding(codex) -->
<!-- SPECKIT_PLAN_LAYOUT: inline-v1 -->

> **Spec Kit 使用约定**：本模板采用**单文件内联布局（inline-v1）**，研究决策、领域与存储模型、内部接口契约及验证指南全部内联维护在本文件四个锚点章节中，不另建 `research.md`、`data-model.md`、`contracts/` 或 `quickstart.md`。仅当 `spec.md` 第 8.2 节确认涉及三类外部独立交付物时，才生成对应独立文件并在本文件建立链接。不适用章节保留标题并说明 `本需求不涉及` 及依据。

---

**分支**：`004-deterministic-tools-gateway` | **日期**：2026-11-16 | **规格**：`./spec.md`

**输入**：`/specs/004-deterministic-tools-gateway/spec.md`

## 基本信息

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-004` |
| 需求名称 | 12 项确定性平台工具原语与双协议热更新外部网关连接器 |
| 对应需求文档 | `./spec.md` |
| 对应任务清单 | `./tasks.md` |
| 设计文档版本 | 2.0 |
| 设计人 | AiCoding(codex) |
| 核算工作量 | 33.0 人天 |
| 状态 | 已交付归档 |

---

## 1. 设计目标与范围 【核心】

### 1.1 设计目标（What / Why）

- **PLAN-GOAL-1**：在 `src/report_agent/runtime/text_tools.py` 与 `tools.py` 实现并向单智能体暴露 12 个无业务硬编码的通用确定性工具（3 项资源查询调度 + 9 项文本/日历/账期/时间差/防 ReDoS 正则原语），彻底接管模型容易产生幻觉与算术误差的计算环节并记入唯一 `callId` 账本。
- **PLAN-GOAL-2**：在 `src/report_agent/gateway/` 实现面向 `GatewayClient` 协议的统一连接器体系：提供与 Java Jackson `XmlMapper` 逐字节等价的 `java` 风格与 `clean` 风格 XML、原生 JSON 双协议、`expat` XXE 防护、显式栈深嵌套防 DoS、信号量限流与幂等指数退避重试。
- **PLAN-GOAL-3**：交付双级路径安全检索且支持 XML→JSON 自动无损转换的 `MockGatewayClient`，以及借助 `_ClientSlot` 引用计数排空与 `asyncio.shield` 安全释放连接池的 `ReloadableGatewayClient` 热更新代理。

### 1.2 设计范围（Scope）

**包含：**

- `src/report_agent/runtime/text_tools.py`（640 行）与 `src/report_agent/runtime/tools.py`（790 行）。
- `src/report_agent/gateway/{__init__.py,base.py,unified_xml.py,mock.py,reloadable.py}`（共 1,373 行）。
- 专项单元测试与对拍测试：`tests/test_deterministic_tools.py`、`tests/test_text_and_gateway.py`、`tests/test_api_json_gateway.py`（及协同 `test_api_response_modes.py`、`test_review_runtime.py`、`test_review_fixes_runtime.py`、`test_runtime_config_hot_reload.py`）。

**不包含：**

- `domain/` 声明式契约解析、`ApiContract` 模型与 `safe_regex_compile` 编译器源码（`RA-001`）。
- `AgentRunner` 智能体循环调度、`EvidenceChecker` 与 `Workspace` 宿主体（`RA-003`）。
- 运行期热配置持久化 `runtime_config.py` 与工作台热更新 API（`RA-002`、`RA-005`）。
- 生产 `seed/apis/*.yaml` 与 `seed/mock-gateway/` 脱敏样例内容维护（`RA-008`）。

<a id="plan-research"></a>

### 1.3 研究与关键决策（Decision Log）

| ID | 决策点 | 备选方案 | 最终选择 | 依据与取舍理由 | 影响范围 |
| --- | --- | --- | --- | --- | --- |
| D1 | 纯函数核心与工具包装分层 | 在工具异步函数内直写算法逻辑 vs `text_tools.py`（纯函数） + `tools.py`（`RunContext` 包装与 `_record` 记账） | 纯函数独立分层解耦 | 除智能体调用外，`runner.py`/`evidence.py` 与 `tools/java_migration/check_skills.py` 对拍脚本可直接无上下文测试与复用 | `text_tools.py`, `tools.py` |
| D2 | 幂等接口并发去重与取消接管 | 广播失败给所有等待方 vs `_idempotent_inflight` + `asyncio.shield` 接管循环 | `asyncio.shield` 等待与存活协程循环接管 | 避免单一并发调用方取消导致同批健康查询连带崩溃；同时保持失败 `ok=False` 不入缓存确保可重试 | `tools.py` |
| D3 | 双协议同客户端兼容 Java XML | 拆分 XML 与 JSON 两套独立客户端 vs 单一 `UnifiedGatewayXmlClient` 按 `contract.is_json` 分发 | 统一客户端共享连接池、信号量、脱敏与重试策略 | 降低资源池管理复杂度；保留 `_JAVA_ORDER` + `xsi:nil` 与 Jackson `XmlMapper` 逐字节一致，支持热切 `clean` 风格 | `unified_xml.py`, `base.py` |
| D4 | 安全防 XXE、深嵌套 DoS 与对称抽取 | 引入重型第三方 XML/解析库或默认递归 vs `expat` 词法钩子（线索词触发）+ 显式栈遍历（深度限 128） | 标准库 `expat` 词法钩子 + 显式迭代栈 | 零额外三方依赖；放行含 `<!DOCTYPE html>` 的 CDATA 正常短信并阻断真实 XXE；杜绝 1500 层深 JSON 引发 `RecursionError` | `gateway/base.py` |
| D5 | 在线热更新网关零泄漏关闭 | 全局读写异步锁阻塞切流 vs `_ClientSlot` 引用计数排空 + `asyncio.shield` 后台关闭任务 | `threading.Lock` 保护槽位原子 `swap` 与退役排空 | 热切换即时生效无需停等慢请求；即使旧在途请求遇外层超时取消仍通过后台任务加 `shield` 完整关流 | `gateway/reloadable.py` |

---

### 1.4 技术背景与项目结构

**语言/版本**：Python 3.13（`pyproject.toml` 声明兼容 `>=3.12,<3.14`），纯异步 HTTP I/O 与无阻塞确定性计算。

**主要依赖**：`pydantic-ai-slim[openai]==2.67.0`（`Tool`、`ToolDefinition`、`ModelRetry`、`RunContext`）、`pydantic>=2.12,<3`、`httpx>=0.28,<1`、标准库 `xml.etree.ElementTree` / `xml.parsers.expat` / `xml.sax.saxutils` / `unicodedata` / `calendar` / `datetime` / `re` / `threading` / `asyncio`。

**存储**：工具账本与幂等复用态暂存 `RunDeps.workspace` 内存；网关侧无写盘状态，`MockGatewayClient` 只读访问 `DATA_DIR/mock-gateway`（`root`）与内置 `src/report_agent/seed/mock-gateway`（`fallback_root`）。

**测试**：`pytest>=8.3,<9`、`pytest-asyncio>=0.24,<2`、`httpx.MockTransport` 流量桩与临时沙箱文件目录；静态检查 `uvx ruff@0.11.0 check src tests`。

**目标平台**：Linux / macOS 容器环境（单进程 Uvicorn `workers=1`）。

**项目类型**：单仓库后端平台工具原语与外部统一网关连接器子系统。

**约束与规模/范围**：`GATEWAY_MAX_CONCURRENCY` 默认 `32`；禁用 HTTP 自动重定向防 SSRF；XML/JSON 报文限 `5,000,000` 字符、`raw` 保留 `200,000` 字符、展平显式栈限 `128` 层；`regex_extract` 限 `200,000` 字符、账期展开限 `36` 月；覆盖 `7` 个源码文件（共 `2,803` 行）与 `3` 份专属测试文件（`1,029` 行），合计 `33.0` 人天。

**源代码结构（真实目录落点）**：

```text
src/report_agent/
├── runtime/
│   ├── text_tools.py    # 9 项纯函数确定性文本/日历/账期/时间差/防 ReDoS 正则算法（640 行）
│   └── tools.py         # 向 Agent 暴露的 12 个工具包装器、动态权限注入、幂等接管与 query_result 引擎（790 行）
└── gateway/
    ├── __init__.py      # gateway 包标识（1 行）
    ├── base.py          # GatewayClient 协议、ApiCallResult、expat 防 XXE、显式栈展平与对称五模式抽取（685 行）
    ├── unified_xml.py   # UnifiedGatewayXmlClient、Java/Clean XML 与 JSON 组包、脱敏预览与信号量重试（422 行）
    ├── mock.py          # MockGatewayClient 双级目录安全检索、防穿越与 XML→JSON 自动无损转换（124 行）
    └── reloadable.py    # ReloadableGatewayClient 槽位引用计数排空与 shield 连接池释放（141 行）

tests/
├── test_deterministic_tools.py  # 5 项新确定性工具与 query_result 多结果/anyOf/between 测试（391 行）
├── test_text_and_gateway.py     # 文本清洗、Java XML 字节对拍、XXE 防护、HTTP 分类与 Mock 沙箱测试（311 行）
└── test_api_json_gateway.py     # JSON/XML 双协议组包、安全请求头、1500 层深 JSON 与 Mock 自动转换测试（327 行）
```

**禁止修改范围**：

- `src/report_agent/domain/api_contract.py` 与 `template.py`（`safe_regex_compile` 等基线契约归属 `RA-001`）。
- `src/report_agent/runtime/runner.py`、`evidence.py`、`workspace.py`（归属 `RA-003`）。
- `src/report_agent/store/`、`api/`、`chat/` 与 `frontend/` 目录。

#### 文档结构（本需求）

```text
specs/004-deterministic-tools-gateway/
├── spec.md    # 需求规格、范围边界、4 个用户故事、FR-001~FR-010 与验收标准
├── plan.md    # 单文件内联设计：研究决策、领域契约、流程与验证指南（inline-v1）
└── tasks.md   # 18 项任务清单（33.0 人天）、实测证据与追踪验收台账
```

| 设计产物 | 权威位置 |
| --- | --- |
| 研究结论与技术决策 | [1.3 研究与关键决策](#plan-research) |
| 领域实体与存储设计 | [第 3–4 章](#plan-data-model) |
| 内部接口与事件契约 | [第 5 章](#plan-contracts) |
| 可执行验证指南 | [10.5 验证指南](#plan-quickstart) |

### 1.5 宪章检查

| 质量门 | 研究前 | 设计后 | 核查证据 |
| --- | --- | --- | --- |
| 原则 I：平台零业务硬编码与声明式资源隔离 | PASS | PASS | 12 工具全部为通用确定性原语；网关端点/路由/报文格式完全由 `ApiContract` 驱动 |
| 原则 II：单智能体规划、确定性原语与强证据防幻觉 | PASS | PASS | 每项工具分配 `callId` 供追溯；`format_date` 入 `VALUE_TOOLS`；日历/账期/正则计算完全交由代码执行 |
| 原则 III：文件化 Git 原子发布与单进程并发安全（`workers=1`） | PASS | PASS | `MockGatewayClient` 只读沙箱；`ReloadableGatewayClient` 借 `threading.Lock` 保护槽位符合单进程并发边界 |
| 原则 IV–V：单文件内联设计、自动化测试隔离与 Mock 契约 | PASS | PASS | 采用 `inline-v1` 布局；使用 `MockTransport` 与临时目录测试，严禁访问真实外网/内网网关 |
| 原则 VI–VII：安全脱敏、零硬编码凭证、事件与审计留痕 | PASS | PASS | `mask_xml`/`mask_json` 脱敏凭证及手机号；防 XXE/ReDoS/深嵌套溢出/SSRF/路径穿越；每次调用记录 `tool` 事件 |
| 原则 VIII–X：最小改动、代码规范、Wiki 同步及三类外部交付物确认 | PASS | PASS | `ruff` 与 `pytest` 零错误；`wiki/` 已历史对齐；三类外部交付物确认不涉及 |

### 1.6 复杂度跟踪

| 偏离或额外复杂度 | 必要性说明 | 未采用更简方案的原因 |
| --- | --- | --- |
| `call_api` 幂等在途 `asyncio.shield` 接管循环 | 多工具并发调用同一幂等接口时，先发 leader 协程可能因超时或局部停止取消而中断共享 `Future` | 直接广播取消异常给等待方会连带打崩健康请求，而彻底放弃去重会成倍穿透外部网关 |
| XML/JSON 解析抽取与报错查找采用显式迭代栈 | 外部响应或恶意载荷可能含 1500 层以上深嵌套节点，极易打爆 Python 1000 帧默认递归栈 | 调高 `sys.setrecursionlimit` 存在 C 栈段错误风险，显式迭代栈在恒定栈深下稳定兜底（展平深限 `128`） |

### 1.7 Wiki 影响评估

- **结论**：涉及（历史交付已按规范同步对齐；本次仅将既有规格升级改造为标准 SDD 三件套，不修改代码与契约，无需新建或修改 `wiki/` 页面）。
- **受影响页面**：
  - `wiki/architecture/deterministic-tools.md`（12 个确定性工具规格与组合模式）
  - `wiki/components/platform-tools.md`（`tools.py`/`text_tools.py` 实现细节与防 ReDoS）
  - `wiki/components/gateway-and-api-contract.md`（双协议统一网关、Mock 与热更新引用计数排空）
  - `wiki/decisions/adr-002-text-skill-and-deterministic-tools.md`（纯文本 Skill 与确定性工具替代 Groovy 决策）
- **同步项**：上述 `wiki/` 规范页、`wiki/index.md` 与 `wiki/log.md` 已在原交付周期更新完毕并满足 `wiki/SCHEMA.md` 约定。

### 1.8 三类独立交付物设计检查

| 独立交付物 | 涉及情况与依据 | 设计与变更摘要 | 验证与回退设计 | 关联问题 |
| --- | --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 不新增面向外部调用方的 HTTP/SSE/`postMessage` 入站接口契约 | 出站网关契约由 `MockTransport` 与 Java 字节对拍保障 | 无 |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 本需求只做连接器引擎，不含 `seed/` 下 3 套接口 YAML 或 Mock 样例内容迁移 | `MockGatewayClient` 与 `verify_structure.py` 解耦验证 | 无 |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | `GATEWAY_*` 及 `AGENT_*` 环境变量与运行时热配置均已随项目基线完成配置 | 通过 `Settings` 校验及热重载回归测试验证 | 无 |

---

## 2. 需求映射（Traceability） 【核心】

| 规格编号 | 类型 | 需求摘要 | 设计章节映射 | 后续任务映射 |
| --- | --- | --- | --- | --- |
| `US1` / `SC-001`, `SC-002` | 用户故事/标准 | 白名单 `load_skill`/`call_api` 幂等去重接管与 `query_result` 合并过滤 | 第 3、5、6 章 | `T005`, `T006`, `T007`, `T008` |
| `US2` / `SC-003` | 用户故事/标准 | 9 项纯函数确定性文本/日历/账期/时间差/防 ReDoS 工具原语 | 第 3、5、6 章 | `T002`, `T009`, `T010`, `T011` |
| `US3` / `SC-004` | 用户故事/标准 | XML/JSON 双协议 `UnifiedGatewayXmlClient`、XXE/显式栈防护、脱敏与限流重试 | 第 3、5、6 章 | `T003`, `T004`, `T012`, `T013`, `T014` |
| `US4` / `SC-005` | 用户故事/标准 | 双级沙箱 `MockGatewayClient`（含 XML→JSON）与 `ReloadableGatewayClient` 热排空 | 第 3、4、6、9 章 | `T015`, `T016` |
| `FR-001` | 功能需求 | 固定 12 工具注册、`_record` `callId` 账本及 `_fail_or_retry` | 第 5.1, 6.2 节 | `T005` |
| `FR-002` | 功能需求 | `load_skill` 单/批量去重与动态 `enum` 隐藏机制 | 第 5.1 节 | `T006`, `T008` |
| `FR-003` | 功能需求 | `call_api` 参数校验、幂等并发 `asyncio.shield` 取消接管与预览截断 | 第 5.1, 6.2 节 | `T006`, `T008` |
| `FR-004` | 功能需求 | `query_result` 单/多结果合并、7 操作符、0 行已知列校验与失败阻断 | 第 3.1, 5.1 节 | `T007`, `T008` |
| `FR-005` | 功能需求 | 9 项确定性纯函数（4 规则扫描、36 月限额、防 ReDoS 等）与工具外壳 | 第 4.1, 5.1 节 | `T002`, `T009`, `T010`, `T011` |
| `FR-006` | 功能需求 | `GatewayClient` 协议、`decode_xml`、`expat` XXE 防护、显式栈展平与对称五模式抽取 | 第 3.1, 5.1 节 | `T001`, `T003`, `T004`, `T017` |
| `FR-007` | 功能需求 | `java`/`clean` XML 组包、JSON 组包、脱敏预览与安全头合并 | 第 5.1 节 | `T012`, `T014` |
| `FR-008` | 功能需求 | 禁重定向、并发信号量（默认 32）、HTTP 状态分类与幂等指数退避重试 | 第 6.2, 9 章 | `T013`, `T014` |
| `FR-009` | 功能需求 | `MockGatewayClient` 双级目录安全定位与 XML→JSON 自动无损转换 | 第 4.1, 5.1 节 | `T015`, `T016` |
| `FR-010` | 功能需求 | `ReloadableGatewayClient` 引用计数排空与 `asyncio.shield` 释放连接池 | 第 3.2, 6.2 节 | `T015`, `T016` |
| `NFR-001`~`NFR-006` | 非功能需求 | 零硬编码、单进程并发安全、防 DoS/XXE/SSRF/ReDoS、脱敏与观测 | 第 1.5, 10, 11 章 | `T014`, `T016`, `T017`, `T018` |
| `EX-001`~`EX-006` | 异常边界 | 工具降级、1500 层深 DoS、点分列空值对齐、leader 取消接管、路径穿越与退役取消释放 | 第 6.2, 10.1 节 | `T008`, `T014`, `T016`, `T017` |

---

<a id="plan-data-model"></a>

## 3. 核心领域模型（Domain Model） 【核心】

### 3.1 领域对象清单

| 对象 / 类 | 所在文件 | 职责与核心属性 | 关键不变量（Invariant） |
| --- | --- | --- | --- |
| `Condition` / `OrderBy` | `src/report_agent/runtime/tools.py` | 结构化筛选条件（`column`, `op`, `value`, `before`, `endValue`, `prefixLen`）与排序声明（`column`, `desc`） | 均启用 `extra="forbid"`；`prefixLen` 为正整数且非 `bool`；`op="between"` 需非空且 `value <= endValue` |
| `ApiCallResult` | `src/report_agent/gateway/base.py` | 网关标准调用结果：`ok`, `records`, `error`, `http_status`, `cost_ms`, `raw`, `request_preview`, `no_data`, `attempts` | `records` 统一规范为 `list[dict[str, str]]` |
| `GatewayClient` (Protocol) | `src/report_agent/gateway/base.py` | 外部网关统一异步抽象协议：`invoke(contract, args)`、`aclose()` | 由 `UnifiedGatewayXmlClient`、`MockGatewayClient` 与 `ReloadableGatewayClient` 共同实现 |
| `UnifiedGatewayXmlClient` | `src/report_agent/gateway/unified_xml.py` | 真实统一网关客户端：管理 `url`（`/openapi_3`）、`style`、`max_concurrency`、`asyncio.Semaphore` 与 `httpx.AsyncClient` | 强制 `http://`/`https://` 与 `follow_redirects=False`；并发严格受信号量限流 |
| `MockGatewayClient` | `src/report_agent/gateway/mock.py` | 双级本地文件网关：`root`、`fallback_root`、`style` | 契约名匹配 `_SAFE_MOCK_NAME_RE`、路径经 `is_relative_to` 验证不逃逸 |
| `_ClientSlot` / `ReloadableGatewayClient` | `src/report_agent/gateway/reloadable.py` | 热更新槽位（`client`, `in_flight`, `retired`, `closed`）及代理管理器 | `threading.Lock` 保护槽位引用计数，`in_flight` 归零自动通过 `asyncio.shield` 释放 |

### 3.2 状态机（如适用）

```text
[Active _ClientSlot (retired=False, in_flight=N)]
    │
    ├─(invoke 进入)──▶ in_flight += 1
    ├─(invoke 退出)──▶ in_flight -= 1 (未 retired 继续复用)
    │
    └─(swap(new_client))──▶ 切换 _slot=新槽位; 旧槽位置 retired=True:
                              ├─(in_flight == 0)──▶ closed=True → 入 _pending_close → 异步 aclose_retired()
                              └─(in_flight > 0)───▶ 入 _retired_inflight → 末个 invoke 退出(含 CancelledError)置 closed=True → spawn + asyncio.shield(_safe_aclose)
```

---

## 4. 数据与存储设计（本需求范围） 【核心】

> 网关运行期无持久化数据库或本地写盘动作；中间状态托管于工作区内存及只读样例目录。

### 4.1 存储与缓存对象概览

| 对象/路径 | 变更类型 | 数据格式与字段要点 | 并发/清理/恢复策略 | 关联需求 |
| --- | --- | --- | --- | --- |
| `Workspace._idempotent_cache` / `_idempotent_inflight` | 使用/写入 | `(name, canonical_json_args) -> ApiResult` / `asyncio.Future[ApiResult]` | 仅在 `contract.idempotent=True` 且 `result.ok=True` 入缓存；随单次运行生命周期释放 | `FR-003` |
| `text_tools._build_remove_table` / `_compile_date_pattern` | 新增 | `@lru_cache(maxsize=64)` 标点转换表、`@lru_cache(maxsize=128)` 日期正则 | 进程内只读无状态 LRU 缓存 | `FR-005` |
| `DATA_DIR/mock-gateway/` 与 `src/report_agent/seed/mock-gateway/` | 只读 | `<name>.<route>.json/.xml`、` <name>.json/.xml` | 只读访问，严格路径越界拦截 | `FR-009` |

---

<a id="plan-contracts"></a>

## 5. 接口与契约设计（API / Tools / Events） 【核心】

### 5.1 接口与契约清单

| 契约编号 | 类型 | 名称 / Path | 方向 | 关键入参 / 载荷 | 关键出参 / 响应 / 事件 | 鉴权与幂等 | 关联需求 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `TOOL-1` | 智能体工具集 | `build_tools(tool_retries)` → 12 项工具 | `Agent` ↔ `tools.py` | 合法 JSON Schema 参数、`RunContext[RunDeps]` | 含 `callId` 的 JSON 结构化响应 + `EventSink` `tool` 事件 | `load_skill`/`call_api` 经 `prepare` 动态设 `enum`；`call_api` 支持工作区幂等 | `FR-001`~`FR-005` |
| `PURE-1` | 纯函数原语 | `text_tools.*`（9 项确定性原语） | `tools.py`/`check_skills.py` → `text_tools.py` | 原始字符串、基准日期、格式、账期文本、安全正则 | 确定性结构字典（`dates`, `start/end`, `months`, `diffSeconds`, `matches`） | 纯函数无副作用；非法入参抛 `ValueError` | `FR-005` |
| `GW-1` | 出站 HTTP 网关 | `UnifiedGatewayXmlClient.invoke` → `{GATEWAY_URL}/openapi_3` | 平台 → 统一网关 | `java`/`clean` XML 或 `{"operation_in": {...}}` JSON + 合并安全头 | `ApiCallResult`（含五模式记录抽取、`raw`、`request_preview`、`attempts`） | 报文 `app_id`/`access_token`；幂等瞬态错按 `0.5 * 2^(attempt-1)` 退避 | `FR-006`~`FR-008` |
| `GW-2` | 本地 Mock 网关 | `MockGatewayClient.invoke` | 平台 → 本地文件 | `ApiContract`, `args` | 命中 `.json`/`.xml` 或 XML 无损转 JSON 解析的 `ApiCallResult` | 校验 `_SAFE_MOCK_NAME_RE` 与 `is_relative_to` 防穿越 | `FR-009` |
| `GW-3` | 热更新代理 | `ReloadableGatewayClient.{invoke, swap, aclose_retired, aclose}` | `AgentRunner`/`container` ↔ `reloadable.py` | `new_client` 实例、`contract`、`args` | 无中断透传 `ApiCallResult` 并排空清理旧连接池 | `threading.Lock` + 引用计数 + `asyncio.shield` | `FR-010` |

### 5.2 关键契约说明与错误语义

- **工具错误处理统一流**：12 项工具任何白名单越权或入参约束违例均通过 `_fail_or_retry` 记入 `Workspace.tool_calls(ok=False)` 并发射 `tool` 事件；当 `ctx.retry < ctx.max_retries` 时抛出 `ModelRetry` 引导大模型自纠，耗尽则回传包含 `callId`、`ok: False` 与 `error` 的降级字典，让智能体得以保留已成功部分字段。
- **HTTP 状态分类与重试边界**：`_classify_http_error` 将非 `200` 响应映射为中文分类消息（`3xx` 重定向禁止、`401/403` 鉴权失败、`404` 地址不存在、`429` 限流、`4xx` 请求拒绝、`5xx` 服务端错）；严格只在 `contract.idempotent=True` 时对网络超时、`TransportError` 及 HTTP `429`/`502`/`503`/`504` 进行重试。
- **双协议响应统一语义**：XML 与 JSON 解析严格遵从 `noData` 先于 `success` 规则，五种 `records.mode`（`auto`、`object`、`list`、`scalar`、`none`）及点分列跨数组提取产出等价的 `list[dict[str, str]]`。

---

## 6. 业务流程设计（可直接编码） 【核心】

### 6.1 核心执行流程

```text
1. 【白名单注入与工具调用】运行装配 build_tools → 模型获取受 allowed_skills/allowed_apis 动态 enum 过滤后的工具定义 → 调工具触发 _record 分配 tN 并推送 tool 事件。
2. 【幂等合并与计算执行】若为计算/检索工具，转调 text_tools 纯函数或 query_result 合并/过滤排序引擎（0 行亦校验全量已知列名）；若为 call_api，校验入参 Schema 后在幂等键上查询 _idempotent_cache 或 asyncio.shield 等待 _idempotent_inflight。
3. 【网关协议适配与请求安全】经 ReloadableGatewayClient 在当前 _ClientSlot 上增加引用计数 → Live 模式组 java/clean XML 或 JSON 报文、合并安全头、过 Semaphore 限流发送（禁止 3xx）；Mock 模式按双级沙箱检索并按需 XML→JSON 转换。
4. 【安全解析与对称抽取】decode_xml/sanitize_xml_text/parse_xml（expat 防 XXE）或 parse_json_body（显式栈）校验长度与安全 → 依 noData/success 与五模式抽取记录存入 Workspace.results，返截断预览摘要；退出槽位引用归零时安全释放旧客户端。
```

### 6.2 并发控制与异常降级策略

| 异常/并发场景 | 检测时机 | 处理策略 | 是否中断主流程 | 可观测性输出 |
| --- | --- | --- | --- | --- |
| 幂等 `call_api` leader 被取消 | `await asyncio.shield(inflight)` 捕获 `CancelledError` | 检测当前任务自身未取消（`cancelling() == 0`）后循环接管重发并写入唯一结果 | 否（健康协程继续执行） | 仅记录实际成功调用事件与 `resultId` |
| 工具校验/计算参数越界 | 工具入口或 `text_tools` 抛 `ValueError` | 调用 `_fail_or_retry`：在额度内 `ModelRetry`，耗尽返 `{"callId": ..., "ok": False, "error": ...}` | 否 | 记入 `Workspace.tool_calls(ok=False)` 与 `tool` 事件 |
| 外部 XXE / 嵌套过深 / 5xx | `parse_xml`/`parse_json_body`/`invoke` | XXE 与超长报文直接拒绝；显式栈防 1500 层溢；幂等瞬态 HTTP 错按指数退避重试 | 否（返 `ApiResult(ok=False)` 交模型按找不到处理） | 记录 `http_status`、`attempts`、`cost_ms` 与脱敏 `request_preview` |
| 热更新切换瞬间旧在途遇取消 | `ReloadableGatewayClient.invoke` `finally` | `in_flight` 归零后由独立异步任务 + `asyncio.shield` 执行 `_safe_aclose` 确保释放 | 否（外层正常接收取消，不漏关句柄） | 调试日志与彻底清理连接池 |

---

## 7. 权限与安全控制（本需求范围） 【补充】

| 控制点 | 适用角色/调用方 | 校验机制与边界 |
| --- | --- | --- |
| 工具白名单与 `VALUE_TOOLS` 边界 | 智能体大模型 | `_prepare_load_skill`/`_prepare_call_api` 注入模板授权列表且为空隐藏；`VALUE_TOOLS` 仅限 `{"format_date"}` |
| 正则与 XML 安全解析 | 工具与网关入/出站 | `safe_regex_compile` 拦截嵌套重复量词 + `200,000` 字符文本限制；`expat` 钩子禁 `DOCTYPE`/`ENTITY` 并放行 CDATA；`_validate_tag` 防 XML 注入 |
| 敏感字段脱敏与 SSRF 防护 | 网关日志与 HTTP 客户端 | `mask_xml`/`mask_json`/`build_request_preview` 隐去凭证与手机号（保留 `${占位符}`）；`follow_redirects=False` 防重定向 |
| 本地 Mock 文件系统隔离 | `MockGatewayClient` | 契约名匹配 `_SAFE_MOCK_NAME_RE`，`route_value` 限纯数字，路径经 `resolve().is_relative_to()` 验证防目录穿越 |

---

## 8. 前端 / 交互设计（如适用） 【补充】

> 本需求不涉及前端页面或交互变更；仅通过 `ApiResult.request_preview` 与 `ToolCall` 向工作台调试与运行详单面板提供脱敏后的报文及调用账本展示数据（前端展现归属 `RA-006`）。

---

## 9. 配置与热更新开关 【补充】

| 配置项（Env / RuntimeConfig） | 类型 | 默认值 | 是否支持热更新 | 说明 |
| --- | --- | --- | --- | --- |
| `agent_tool_retries` | `int` | `2` | 是 | 工具参数不合法时最大 `ModelRetry` 次数，通过 `reload_config` 刷新工具列表 |
| `agent_preview_rows` | `int` | `10` | 是 | `call_api` 向模型返回的摘要预览最大行数 |
| `agent_query_default_limit` / `agent_query_max_limit` | `int` | `20` / `100` | 是 | `query_result` 缺省返回行数与最大截断上限 |
| `agent_max_period_months` | `int` | `36` | 是 | `expand_period` 允许展开的最大账期月数上限 |
| `gateway_mode` / `gateway_url` | `Literal` / `str` | `"mock"` / `""` | 是 | 切换本地 Mock 与生产统一网关（`live` 校验 `http://`/`https://`） |
| `gateway_app_id` / `gateway_access_token` | `SecretStr` | `""` | 是 | 统一网关报文鉴权凭据，热重载时通过 `ReloadableGatewayClient.swap` 平滑切换 |
| `gateway_xml_style` / `gateway_connect_timeout_s` / `gateway_max_concurrency` | `Literal` / `float` / `int` | `"java"` / `5.0` / `32` | 是 | XML 序列化风格、连接超时及单客户端并发信号量上限 |

---

## 10. 测试设计（Test Strategy） 【核心】

### 10.1 测试范围与分层策略

| 测试类型 | 覆盖范围 | 桩/隔离策略 | 重点验证场景 |
| --- | --- | --- | --- |
| 单元测试 | `text_tools`, `tools`, `gateway/base`, `unified_xml`, `mock`, `reloadable` | 内存字典、临时目录、自定义慢 `aclose()` 桩 | 9 项纯函数与闰平年/ReDoS 边界、XML 字节对拍、XXE/CDATA 分辨、显式栈处理 1500 层 JSON、路径逃逸、热更新排空 |
| 集成/交叉测试 | `call_api` 幂等并发、`query_result` 跨月合并、全网关五模式抽取 | `httpx.MockTransport`、可控挂起/取消协程与多 `ApiResult` | leader 取消接管、3xx/4xx/5xx 重试、Mock XML→JSON 无损转换、热切配置与旧网关清理 |

### 10.2 回归范围

- 核心工具与网关专属测试：`tests/test_deterministic_tools.py`、`tests/test_text_and_gateway.py`、`tests/test_api_json_gateway.py`。
- 交叉响应模式与运行时加固回归：`tests/test_api_response_modes.py`、`tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py`、`tests/test_runtime_config_hot_reload.py`。

<a id="plan-quickstart"></a>

### 10.5 验证指南

- **环境与前置条件**：macOS / Linux，Python 3.13 + `uv` 就绪（`uv sync --extra dev`），全过程无需真实统一网关或外网连接。
- **验证命令**：
  ```bash
  # 运行全量测试套件（含全部工具与网关测试）
  uv run pytest -q

  # 单独按需聚焦工具与网关测试（快速自检）
  uv run pytest tests/test_deterministic_tools.py tests/test_text_and_gateway.py tests/test_api_json_gateway.py tests/test_api_response_modes.py -q

  # Python 静态代码规范检查
  uvx ruff@0.11.0 check src tests
  ```
- **预期结果**：全量测试 `uv run pytest -q` 输出 `196 passed in 51.41s`，`uvx ruff@0.11.0 check src tests` 输出 `All checks passed!`（0 error / 0 warning）。

---

## 11. NFR 符合性自检 【核心】

| 自检主题 | 宪章依据 | 是否涉及 | 落实位置与验证方式 |
| --- | --- | --- | --- |
| 零业务硬编码与资源隔离 | I | 是 | `tools.py`/`text_tools.py`/`gateway/` 无任何业务规则与特定模板编码 |
| 强证据防幻觉与确定性计算 | II | 是 | 12 工具全部登记 `callId`；仅 `format_date` 入 `VALUE_TOOLS`；日历/文本/账期全部代码确定性计算 |
| 文件化存储与 `workers=1` 并发安全 | III | 是 | `ReloadableGatewayClient` 引用计数与信号量按单进程并发设计，Mock 目录仅只读防越界 |
| 安全编码、脱敏与零凭据硬编码 | VI | 是 | `expat` 防 XXE、显式栈防溢出、禁重定向、防 ReDoS、`mask_xml`/`mask_json` 脱敏及零硬编码密钥 |
| 过程事件、阶段日志与审计留痕 | VII | 是 | 工具统一经 `_record` 推 `tool` 事件；网关记录 `cost_ms`/`attempts`/`http_status` 与脱敏预览 |

---

## 12. 发布与回退计划 【核心】

- **发布前置与步骤**：全量执行 `uv run pytest -q` 与 `uvx ruff@0.11.0 check src tests` 通过 → 验证网关配置 `GATEWAY_MODE`（`mock`/`live`）、`GATEWAY_URL`、`GATEWAY_XML_STYLE` 与 `GATEWAY_MAX_CONCURRENCY` → 启动单进程服务并检查健康端；运行期需变更网关模式、端点、密钥或并发上限时通过管理端热配置调用 `ReloadableGatewayClient.swap` 平滑切换。
- **回退方案**：网关参数/地址/密钥错误通过运行期配置版本 `cN` 一键回滚并触发 `swap` 排空清理；代码级故障回退容器镜像或 Git 历史提交版本。

---

## 13. 实施切片与建议顺序（Implementation Slices） 【核心】

| 切片 ID | 切片名称 | 对应 Phase / 任务范围 | 目标与涉及文件 | 核算工时 |
| --- | --- | --- | --- | --- |
| `S-01` | 网关包结构、安全边界常量与文本清洗字符集 | Phase 1 (`T001`–`T002`) | `src/report_agent/gateway/{__init__.py,base.py}`、`src/report_agent/runtime/text_tools.py` | 3.0 人天 |
| `S-02` | XML/JSON 安全解析基座、显式栈五模式抽取与工具记账框架 | Phase 2 (`T003`–`T005`) | `src/report_agent/gateway/base.py`、`src/report_agent/runtime/tools.py` | 6.0 人天 |
| `S-03` | 白名单 `load_skill`/`call_api` 幂等取消接管与 `query_result` 合并过滤 | Phase 3 (`T006`–`T008`) | `src/report_agent/runtime/tools.py`、`tests/{test_deterministic_tools.py,test_review_runtime.py}` | 6.5 人天 |
| `S-04` | 9 项确定性文本、日历、账期、时间差与防 ReDoS 正则原语及工具包装 | Phase 4 (`T009`–`T011`) | `src/report_agent/runtime/{text_tools.py,tools.py}`、`tests/{test_deterministic_tools.py,test_text_and_gateway.py,test_review_fixes_runtime.py}` | 6.0 人天 |
| `S-05` | `UnifiedGatewayXmlClient` 双协议组包、脱敏预览、信号量与重试引擎 | Phase 5 (`T012`–`T014`) | `src/report_agent/gateway/unified_xml.py`、`tests/{test_text_and_gateway.py,test_api_json_gateway.py,test_review_fixes_runtime.py}` | 5.5 人天 |
| `S-06` | 双级 `MockGatewayClient`（含 XML→JSON）与 `ReloadableGatewayClient` 热排空 | Phase 6 (`T015`–`T016`) | `src/report_agent/gateway/{mock.py,reloadable.py}`、`tests/{test_text_and_gateway.py,test_api_json_gateway.py,test_runtime_config_hot_reload.py}` | 3.5 人天 |
| `S-07` | 跨模式一致性复核、全量套件回归与静态质量验收 | Phase 7 (`T017`–`T018`) | 跨响应模式交叉核验与全仓库 `pytest` / `ruff` 验收收口 | 2.5 人天 |
| **合计** | **全 7 个切片、18 项任务** | **`T001`–`T018`** | **12 项确定性平台工具与双协议网关子系统** | **33.0 人天** |

---

## 14. 风险清单与缓解（Risks） 【补充】

| 风险 ID | 风险描述 | 影响 | 概率 | 缓解措施 |
| --- | --- | --- | --- | --- |
| `R-1` | 外部网关返回超长或上千层畸形嵌套 JSON/XML 引起内存飙升或 `RecursionError` | 高 | 中 | 严格限制 `MAX_XML_CHARS`/`MAX_JSON_CHARS` 为 `5,000,000` 字符，展平与错误文本遍历全用显式栈且深限 `128`，大于 `200,000` 字符跳过美化 |
| `R-2` | 高并发下配置热切网关或 leader 取消导致在途连接泄露或同批请求连带出错 | 高 | 低 | `call_api` 用 `asyncio.shield` 接管重试；`ReloadableGatewayClient` 以 `_ClientSlot` 引用计数与后台 `shield` 释放保证零泄漏 |
| `R-3` | 文本日期或正则规则出现误吸（如活动号、手机号、ReDoS 嵌套量词） | 中 | 中 | `extract_dates` 强制前后非字母数字边界、中文需“日/号”后缀与真实日历验证；`regex_extract` 复用 `safe_regex_compile` 语法树阻断 |

---

## 15. 待确认事项（Design Open Questions） 【补充】

> 设计阶段关键技术取舍已全部闭环并通过自动化测试验收，当前无未关闭 `DQ-*`。

| 编号 | 问题摘要 | 对应 Spec `Q-*` | 当前结论 | 状态 |
| --- | --- | --- | --- | --- |
| `DQ-1` | 双协议网关共池分发与 Mock 跨格式自动转换一致性 | `Q-001` | `UnifiedGatewayXmlClient` 按 `contract.is_json` 分发、`MockGatewayClient` 支持 XML→JSON 无损回退、五模式点分列抽取全对称 | 已关闭 |

---

## 附录 A：核心字段与状态约定（仅本需求）

- **12 个平台工具清单**：`load_skill`、`call_api`、`query_result`、`normalize_text`、`text_contains`、`date_range`、`format_date`、`extract_dates`、`date_shift`、`expand_period`、`time_diff`、`regex_extract`
- **`Condition.op` 支持算子**：`"equals"` | `"contains"` | `"notContains"` | `"normalizedContains"` | `"normalizedNotContains"` | `"startsWith"` | `"between"`
- **核心上限常量**：`MAX_XML_CHARS = 5_000_000`、`MAX_JSON_CHARS = 5_000_000`、`_MAX_FLATTEN_DEPTH = 128`、`MAX_REGEX_TEXT_LENGTH = 200_000`、`MAX_PERIOD_MONTHS = 36`、`VALUE_TOOLS = {"format_date"}`

## 附录 B：AI 编码与交付约束

1. 先阅读 `spec.md`、本 `plan.md` 与 `tasks.md`，按 `T001`–`T018` 顺序实施，不实现 Out of Scope 内容。
2. 所有已勾选完成 `[X]` 的任务必须附有真实命令验证输出，严禁“仅写完未验证即标完成”。

---

## 变更记录（Changelog）

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | AiCoding(codex) | 依据 `report-agent` 工具与网关源码完成初版架构设计归档 |
| 2.0 | 2026-11-16 | AiCoding(codex) | 升级为 `inline-v1` 单文件内联设计布局，补齐四锚点、宪章门禁、Wiki 评估与全量可追溯映射 |
