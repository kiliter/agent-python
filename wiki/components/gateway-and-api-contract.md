---
title: 网关契约与连接器组件剖析
type: component
tags: [component, gateway, api-contract, xml, json, mock, hot-reload]
sources:
  - src/report_agent/domain/api_contract.py
  - src/report_agent/domain/template.py
  - src/report_agent/gateway/base.py
  - src/report_agent/gateway/unified_xml.py
  - src/report_agent/gateway/mock.py
  - src/report_agent/gateway/reloadable.py
updated: 2026-11-13
---

# 网关契约与连接器组件剖析

<!-- #Created By AiCoding(codex) -->

外部业务系统取数能力由声明式领域模型 `src/report_agent/domain/api_contract.py` 与连接器实现层 `src/report_agent/gateway/` 共同承载，无需编写业务接口专属代码即可对接统一网关 XML/JSON 协议。

## 1. 声明式接口契约（`domain/api_contract.py#ApiContract`）

每个 `apis/<name>.yaml` 解析为一个不可变 `ApiContract` 实例，包含四大核心段落：

1. **连接器与治理策略**：
   - `connector`：`unified-gateway-xml`（默认）或 `unified-gateway-json`；
   - `processCode`：统一网关业务编码（如 `querySMSSendInfo`）；
   - `timeoutMs`（100～120,000 ms）、`retry.maxAttempts`（1～5 次，网络/5xx 指数退避重试）与 `idempotent`。
2. **入参 Schema（`input`）**：标准 JSON Schema（`type: object`），按 `self.input` 缓存 `Draft202012Validator`（`_validator_cache`），并在 `schema_errors` 与 `validate_args` 阶段接入 `safe_regex_compile` 拦截嵌套量词 ReDoS。
3. **请求报文构造（`request` + `build_request`）**：
   - 自动填充统一网关公共头默认值（`request_type="1"`、`organ_id="1"`、`request_source="1"`、`sysfunc_id=processCode` 等），允许契约按需覆盖（如 `BOSS_QryBalanceFlowLog` 覆盖 `organ_id="3001"`、`verify_code="1002"`）；
   - 支持 `${入参名}` 字符串插值，以及平台内置动态占位符 **`${$now}`**（定义在 `BUILTIN_PLACEHOLDERS`，每次组包时动态注入当前本地时间 `yyyyMMddHHmmss`，仅对替换出的容器对象按需拷贝，免除外层整包冗余 `deepcopy`）。
4. **响应判定与多模式记录抽取（`response`）**：
   - **判定顺序**：**先判 `noData`（如 `resp_desc` 含“无短信记录”或靓号 `ret_code == "1"`），命中即视为 `ok=True, count=0, noData=True`**；未命中时再判 `success`（`equals` + `missingAs: "success" | "failure"`；如 `BOSS_QryBalanceFlowLog` 与 `cc_pretty_num_info_query` 均设为 `missingAs: failure`，确保顶层网关报错无业务 `ret_code` 时准确判为 `ok=False`），错误描述自动兼容提取 `resp_desc`、`ret_msg` / `retMsg` 等字段。
   - **记录抽取（`RecordsSpec`）**：
     - `mode` 支持 5 种形态：`auto`（默认，兼容列表与单对象）、`list`、`object`、`scalar`、`none`；
     - XML 与 JSON 双协议统一支持点分深层列路径（`_extract_json_dotted` 与 XML 对齐：路径中途遇到 `list[dict]` 时自动遍历聚合非空值，多档次序列化为 JSON 数组文本，单值返回标量）与嵌套对象扁平化 `flatten: true`。

## 2. 统一网关客户端（`gateway/unified_xml.py#UnifiedGatewayXmlClient`）

### 2.1 Jackson 3 字节级兼容 XML 序列化（`build_request_xml`）

前代 Java 版的 `CommonRequestToolService#toXmlRequest` 使用 Jackson 3 `XmlMapper` 序列化 `XmlBaseRequest` POJO，具有鲜明特征。`build_request_xml` 提供两种 `GATEWAY_XML_STYLE`：
- **`style="java"`（默认）**：顶层字段严格按字母序排列（`_JAVA_ORDER`），契约未显式设置的公共字段输出 `<operator_id xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:nil="true"/>`，空字符串输出普通空标签 `<sendPort/>`，不带 `<?xml ...?>` 声明头。经 `tools/java_migration/check_skills.py` 对拍，与 Java 编译产物生成的真实报文**逐字节完全一致**。
- **`style="clean"`**：带 UTF-8 XML 声明头，省略值为 `None` 的公共字段标签。

### 2.2 防 XXE 安全的 XML 解析（`parse_xml`）与连接池/并发保护

标准库 `xml.etree.ElementTree` 默认允许内部实体扩展（存在 Billion Laughs 内存放大风险）。`parse_xml` 先经 `_check_xml_security` 在底层 `expat` 解析器上挂载 `EntityDeclHandler` 与 `StartDoctypeDeclHandler` 钩子，一旦响应报文包含任何 `<!DOCTYPE` 或 `<!ENTITY` 声明立即拒绝解析，随后剥离 XML Namespace 前缀并结合预编译脱敏正则掩码敏感凭证。同时 `UnifiedGatewayXmlClient` 内置异步并发信号量（`GATEWAY_MAX_CONCURRENCY`，默认 `32`）及匹配的 `httpx.Limits` 连接池上限，防止突发跨月查询洪峰打满下游统一网关。

### 2.3 JSON 连接器支持

当 `contract.connector == "unified-gateway-json"` 时，`UnifiedGatewayXmlClient` 自动将构造好的 `operation_in` 报文以 `application/json` 发送，并用 `parse_json_body` + `extract_json_records`（严格区分 `bool` 与 `int`，显式栈单遍扫描 `_first_json_text`）解析响应树，与 XML 共享一致的 `noData`/`success` 判定与多元素点分列抽取语义。

## 3. 本地 Mock 网关（`gateway/mock.py#MockGatewayClient`）

当 `GATEWAY_MODE=mock` 时启用，无需连接企业内网网关即可本地开发、跑单测与工作台试运行：
- **双目录查找优先级**：先查 `DATA_DIR/mock-gateway/`（方便运维放临时案例报文），未命中再回退 `fallback_root=SEED_DIR / "mock-gateway"`；
- **按路由值匹配特定案例**：优先查找 `{api_name}.{route_value}.{xml|json}`（如 `querySMSSendInfo.13900000000.xml` 模拟无短信空结果），未命中再回退通用正例 `{api_name}.{xml|json}`；
- 解析走与线上完全相同的 `parse_xml` / `parse_json_body` 契约抽取链路，确保契约路径配置在 Mock 阶段即可得到真实检验。

## 4. 零中断热重载包装器（`gateway/reloadable.py#ReloadableGatewayClient`）

管理员在工作台切换 `mock` / `live` 模式或修改网关地址、超时与 XML 风格（仅当 `_gateway_signature` 实际变化时触发重建）时，不能直接 `aclose()` 正在处理线上并发请求的 `httpx.AsyncClient`。`ReloadableGatewayClient` 采用**引用计数槽位（`_ClientSlot`）**机制：
1. 每次 `invoke()` 在锁内将当前活跃 `_ClientSlot.in_flight` 计数 `+1`，释放锁后执行异步网络 I/O；
2. `swap(new_client)` 原子替换活跃 `_ClientSlot` 并将旧槽位标记为 `retired = True`；
3. 若替换瞬间旧槽位 `in_flight <= 0` 则立即经 `aclose_retired()` 异步关闭旧客户端；若有在途请求，则由最后一个在 `finally` 中把 `in_flight` 减至 `0` 的请求协程挂起受跟踪后台关闭任务并通过 `asyncio.shield` 等待完成（防止外层请求取消中断连接池释放）。

## 相关页面

- [文件化资源存储与 Git 原子发布机制](../architecture/resource-release-and-store.md)
- [3 个内置网关接口契约速查](../reference/apis-catalog.md)
- [新增纯文本 Skill 与声明式网关接口契约指南](../guides/add-skill-and-api.md)
- [Java 资源迁移与一致性对拍指南](../guides/java-migration-and-verification.md)
