---
title: 环境变量与运行期配置参考
type: reference
tags: [reference, configuration, env, settings, hot-reload]
sources:
  - src/report_agent/config.py
  - src/report_agent/store/fsutil.py
  - src/report_agent/store/runtime_config.py
  - src/report_agent/container.py
  - src/report_agent/runtime/tools.py
  - src/report_agent/chat/agent.py
  - .env.example
updated: 2026-11-13
---

# 环境变量与运行期配置参考

<!-- #Created By AiCoding(codex) -->

平台配置由 `src/report_agent/config.py#Settings`（基于 `pydantic-settings`，环境变量名与字段名大小写不敏感映射，自动读取 `.env`）提供启动基线；其中**大模型、智能体运行与平台工具限额、统一网关与并发、资源与数据留存周期、调用凭证以及嵌入式聊天与上下文压缩**共 **48 项**运行参数已纳入 `RuntimeConfigStore`（`DATA_DIR/config/runtime/current.json`），支持在工作台「引擎与系统设置」**在线编辑、一键恢复默认值、从环境变量重同步与按修订号（`c1`..`cN`）热回退，无需重启服务**。

## 1. 完整环境变量清单

### 1.1 数据目录、生命周期与静态托管

| 环境变量 | `Settings` 字段 | 默认值 | 支持在线热更 | 取值范围 / 说明 |
|----------|-----------------|--------|--------------|-----------------|
| `DATA_DIR` | `data_dir` | `./data`（Docker 内 `/data`） | 否（启动期不变量） | PVC 持久化根目录，存放 `repo/`、`releases/`、`drafts/`、`runs/`、`chats/`、`cases/`、`config/` 与 `audit.jsonl` |
| `SEED_ON_EMPTY` | `seed_on_empty` | `true` | 否（启动期不变量） | `DATA_DIR` 为空时是否自动用内置 `seed/` 初始化首个发布版本 `r1` |
| `RELEASES_KEEP` | `releases_keep` | `50` | **是**（`releasesKeep`） | `1~500`；磁盘保留的已物化发布目录 `releases/rN/` 数量上限，更早版本按需从 Git 恢复 |
| `RUNS_KEEP_DAYS` | `runs_keep_days` | `90` | **是**（`runsKeepDays`） | `0~3650`；运行记录与聊天会话留存天数（`0` 表示永久保留不清理） |
| `FRONTEND_DIST` | `frontend_dist` | `None` | 否（启动期不变量） | 前端构建产物目录（如 `frontend/dist`），配置后由本服务直接托管 SPA |
| `LOG_LEVEL` | `log_level` | `INFO` | 否（启动期不变量） | 应用与 Uvicorn 日志级别 |
| `LOG_DIR` | `log_dir` | `None` | 否（启动期不变量） | 日志文件输出目录，不配置时仅输出到标准控制台 |

### 1.2 大模型（OpenAI 兼容接口）配置

| 环境变量 | `Settings` 字段 | 默认值 | 支持在线热更 | 取值范围 / 说明 |
|----------|-----------------|--------|--------------|-----------------|
| `LLM_BASE_URL` | `llm_base_url` | `https://api.openai.com/v1` | **是**（`llmBaseUrl`） | 非空 `http://` 或 `https://` 地址；OpenAI 兼容推理服务地址 |
| `LLM_API_KEY` | `llm_api_key` | `dummy` | **是**（`llmApiKey`） | 模型服务 API Key（`SecretStr` 保护，管理端掩码脱敏展示） |
| `LLM_MODEL` | `llm_model` | `deepseek-v4-flash` | **是**（`llmModel`） | 非空模型名称标识（禁止控制字符） |
| `LLM_TEMPERATURE` | `llm_temperature` | `0.0` | **是**（`llmTemperature`） | `0~2`；采样温度，推荐 `0.0` 保持确定性推理 |
| `LLM_MAX_TOKENS` | `llm_max_tokens` | `None` | **是**（`llmMaxTokens`） | `>= 1` 或 `null`；单次模型输出最大 Token 上限（留空走服务端默认） |
| `LLM_TIMEOUT_S` | `llm_timeout_s` | `120.0` | **是**（`llmTimeoutS`） | `> 0`；单次模型 HTTP 请求超时秒数 |
| `LLM_HTTP_RETRIES` | `llm_http_retries` | `2` | **是**（`llmHttpRetries`） | `0~10`；模型 HTTP 层针对网络错误与 5xx 的自动重试次数 |
| `LLM_PARALLEL_TOOL_CALLS` | `llm_parallel_tool_calls` | `true` | **是**（`llmParallelToolCalls`） | `true` / `false` / `null`；是否允许模型单轮并行调用多个工具（`null` 使用服务端默认） |
| `LLM_STRICT_TOOLS` | `llm_strict_tools` | `None` | **是**（`llmStrictTools`） | `true` / `false` / `null`；是否声明 strict 工具定义（内网推理框架不支持时可设为 `false`） |
| `LLM_TOOL_CHOICE_REQUIRED` | `llm_tool_choice_required` | `None` | **是**（`llmToolChoiceRequired`） | `true` / `false` / `null`；推理服务端是否支持 `tool_choice=required` |

### 1.3 智能体运行、证据校验与平台工具限额

| 环境变量 | `Settings` 字段 | 默认值 | 支持在线热更 | 取值范围 / 说明 |
|----------|-----------------|--------|--------------|-----------------|
| `AGENT_OUTPUT_MODE` | `agent_output_mode` | `tool` | **是**（`agentOutputMode`） | `tool` \| `native` \| `json_object` \| `prompted`；结构化交卷通道 |
| `AGENT_NATIVE_STRICT` | `agent_native_strict` | `true` | **是**（`agentNativeStrict`） | `native` 模式下是否发送 strict `json_schema` 约束解码 |
| `AGENT_OUTPUT_RETRIES` | `agent_output_retries` | `3` | **是**（`agentOutputRetries`） | `0~10`；`EvidenceChecker` 证据校验未通过时，最多退回让模型重交几次 |
| `AGENT_TOOL_RETRIES` | `agent_tool_retries` | `2` | **是**（`agentToolRetries`） | `0~10`；工具入参不合法时，最多让模型修正重试几次 |
| `AGENT_REQUEST_LIMIT` | `agent_request_limit` | `25` | **是**（`agentRequestLimit`） | `1~200`；单次运行请求模型轮次上限 |
| `AGENT_TOOL_CALLS_LIMIT` | `agent_tool_calls_limit` | `120` | **是**（`agentToolCallsLimit`） | `1~500`；单次运行工具调用总次数上限（支撑 12～36 个月跨账期查询） |
| `AGENT_RUN_TIMEOUT_S` | `agent_run_timeout_s` | `600.0` | **是**（`agentRunTimeoutS`） | `> 0`；单次报告生成总超时秒数 |
| `AGENT_MAX_CONCURRENT_RUNS` | `agent_max_concurrent_runs` | `8` | **是**（`agentMaxConcurrentRuns`） | `1~128`；进程内并发运行智能体的动态限流器（`_DynamicLimiter`）上限 |
| `AGENT_PREVIEW_ROWS` | `agent_preview_rows` | `10` | **是**（`agentPreviewRows`） | `1~200`；`call_api` 返回给模型的摘要预览最大行数 |
| `AGENT_QUERY_DEFAULT_LIMIT` | `agent_query_default_limit` | `20` | **是**（`agentQueryDefaultLimit`） | `1~500`（且 `<= agentQueryMaxLimit`）；`query_result` 未传 `limit` 时的默认返回行数 |
| `AGENT_QUERY_MAX_LIMIT` | `agent_query_max_limit` | `100` | **是**（`agentQueryMaxLimit`） | `1~1000`；`query_result` 单次允许返回的最大行数上限 |
| `AGENT_MAX_PERIOD_MONTHS` | `agent_max_period_months` | `36` | **是**（`agentMaxPeriodMonths`） | `1~120`；`expand_period` 单次允许展开的最大月份跨度 |

### 1.4 嵌入式聊天与滚动上下文压缩配额

| 环境变量 | `Settings` 字段 | 默认值 | 支持在线热更 | 取值范围 / 说明 |
|----------|-----------------|--------|--------------|-----------------|
| `CHAT_MAX_DOC_CHARS` | `chat_max_doc_chars` | `12000` | **是**（`chatMaxDocChars`） | `500~200000`；聊天窗口注入提示词的单据正文最大字符数 |
| `CHAT_MAX_HISTORY_MESSAGES` | `chat_max_history_messages` | `20` | **是**（`chatMaxHistoryMessages`） | `1~200`；聊天窗口单轮携带的最近原文消息最大条数 |
| `CHAT_MAX_RUN_CARDS` | `chat_max_run_cards` | `8` | **是**（`chatMaxRunCards`） | `1~50`；聊天窗口注入上下文的最近运行卡片数量上限 |
| `CHAT_MAX_MARKDOWN_PREVIEW_CHARS` | `chat_max_markdown_preview_chars` | `1500` | **是**（`chatMaxMarkdownPreviewChars`） | `100~20000`；聊天窗口运行卡片报告正文预览截断字符数 |
| `CHAT_COMPACT_TRIGGER_MESSAGES` | `chat_compact_trigger_messages` | `24` | **是**（`chatCompactTriggerMessages`） | `2~500`（且 `> chatCompactKeepRecent`）；触发自动增量上下文压缩的未归档消息阈值 |
| `CHAT_COMPACT_KEEP_RECENT` | `chat_compact_keep_recent` | `12` | **是**（`chatCompactKeepRecent`） | `1~200`；自动压缩后保留在最近对话历史中的原文消息条数 |
| `CHAT_MANUAL_COMPACT_KEEP_RECENT` | `chat_manual_compact_keep_recent` | `6` | **是**（`chatManualCompactKeepRecent`） | `1~200`；手动调用 `/compact` 后保留的最近原文消息条数 |
| `CHAT_MANUAL_COMPACT_MIN_SLICE` | `chat_manual_compact_min_slice` | `2` | **是**（`chatManualCompactMinSlice`） | `1~100`；手动压缩至少需可归档的最小切片条数（前端禁用下限 `manualCompactMinMessages = keep + minSlice`） |
| `CHAT_MAX_MEMORY_SUMMARY_CHARS` | `chat_max_memory_summary_chars` | `1200` | **是**（`chatMaxMemorySummaryChars`） | `200~10000`；滚动记忆摘要最大字符数上限 |
| `CHAT_MAX_SUMMARY_MSG_CHARS` | `chat_max_summary_msg_chars` | `800` | **是**（`chatMaxSummaryMsgChars`） | `100~10000`；待压缩消息单条文本截取上限 |
| `CHAT_REQUEST_LIMIT` | `chat_request_limit` | `8` | **是**（`chatRequestLimit`） | `1~50`；聊天路由智能体单轮最多请求模型次数 |
| `CHAT_TOOL_CALLS_LIMIT` | `chat_tool_calls_limit` | `16` | **是**（`chatToolCallsLimit`） | `1~100`；聊天路由智能体单轮最多调用只读工具次数 |
| `CHAT_TIMEOUT_S` | `chat_timeout_s` | `120.0` | **是**（`chatTimeoutS`） | `> 0`；聊天路由智能体单轮推理超时秒数 |
| `CHAT_SUMMARY_REQUEST_LIMIT` | `chat_summary_request_limit` | `3` | **是**（`chatSummaryRequestLimit`） | `1~20`；滚动记忆摘要智能体单次压缩最多请求模型次数 |
| `CHAT_SUMMARY_TOOL_CALLS_LIMIT` | `chat_summary_tool_calls_limit` | `4` | **是**（`chatSummaryToolCallsLimit`） | `1~30`；滚动记忆摘要智能体单次压缩最多调用工具次数 |
| `CHAT_SUMMARY_TIMEOUT_S` | `chat_summary_timeout_s` | `60.0` | **是**（`chatSummaryTimeoutS`） | `> 0`；滚动记忆摘要智能体单次压缩超时秒数 |

### 1.5 统一网关连接配置

| 环境变量 | `Settings` 字段 | 默认值 | 支持在线热更 | 取值范围 / 说明 |
|----------|-----------------|--------|--------------|-----------------|
| `GATEWAY_MODE` | `gateway_mode` | `mock` | **是**（`gatewayMode`） | `live`（调用真实统一网关 HTTP 接口）或 `mock`（读取本地 `mock-gateway/` 样例） |
| `GATEWAY_URL` | `gateway_url` | `""` | **是**（`gatewayUrl`） | 统一网关地址（`gatewayMode=live` 时必填且需以 `http://` 或 `https://` 开头） |
| `GATEWAY_APP_ID` | `gateway_app_id` | `""` | **是**（`gatewayAppId`） | 统一网关应用标识凭证（`SecretStr`） |
| `GATEWAY_ACCESS_TOKEN` | `gateway_access_token` | `""` | **是**（`gatewayAccessToken`） | 统一网关访问令牌（`SecretStr`） |
| `GATEWAY_XML_STYLE` | `gateway_xml_style` | `java` | **是**（`gatewayXmlStyle`） | `java`（对齐 Java Jackson 3 字母序与空值 `xsi:nil`）或 `clean`（声明序、无 `xsi:nil`） |
| `GATEWAY_CONNECT_TIMEOUT_S` | `gateway_connect_timeout_s` | `5.0` | **是**（`gatewayConnectTimeoutS`） | `> 0`；网关 TCP 连接超时秒数 |
| `GATEWAY_MAX_CONCURRENCY` | `gateway_max_concurrency` | `32` | **是**（`gatewayMaxConcurrency`） | `1~512`；进程内调用真实统一网关（`UnifiedGatewayXmlClient`）的最大并发请求信号量上限 |

### 1.6 管理端与上游接口认证

| 环境变量 | `Settings` 字段 | 默认值 | 支持在线热更 | 说明 |
|----------|-----------------|--------|--------------|------|
| `ADMIN_TOKEN_SECRET` | `admin_token_secret` | `None` | 否（启动期不变量） | 工作台会话签名密钥；未配时自动生成并保存在 `DATA_DIR/config/.token-secret` |
| `ADMIN_TOKEN_TTL_S` | `admin_token_ttl_s` | `43200`（12h） | 否（启动期不变量） | 工作台登录会话有效秒数 |
| `ADMIN_COOKIE_SECURE` | `admin_cookie_secure` | `false` | 否（启动期不变量） | HTTPS 部署时设为 `true` |
| `ADMIN_BOOTSTRAP_PASSWORD` | `admin_bootstrap_password` | `None` | 否（启动期不变量） | 首次启动且无任何用户时，自动使用该密码初始化 `admin` 账号 |
| `REPORT_API_KEYS` | `report_api_keys` | `""` | **是**（`reportApiKeys`） | 上游接口 `/api/v1/reports*` 与嵌入式聊天接口 `/api/v1/chat/*` 共用的 `X-API-Key` 白名单（支持逗号分隔多把密钥），可通过管理端 `/api/v1/settings/api-key*` 在线查看、修改、清空或一键重新生成并免重启热生效；生产必填 |

## 2. 全链路默认值兜底与跨字段校验

1. **环境变量启动兜底（`config.py#Settings._fallback_blank_non_nullable_scalars`）**：`_NON_NULLABLE_SCALAR_FIELDS` 覆盖全部 40 个非可空标量配置项；当 `.env` 或环境中把这类配置留空（如 `CHAT_TIMEOUT_S=`）或传 `None` 时，`model_validator(mode="before")` 自动剔除空键值，交由 `Field` 内置默认值兜底，避免启动阶段因空串解析整数/浮点失败而崩溃。
2. **持久化快照与补丁兜底（`store/runtime_config.py#RuntimeConfig`）**：
   - `RuntimeConfig.from_storage_dict` 从历史 `current.json` 或 `revisions/cN.json` 恢复配置时，若遇到旧版快照缺失新增字段、非可空字段为 `None` 或非字符串字段为空白字符串，自动按 `fallback_settings`（默认内置 `Settings(_env_file=None)`）补齐默认值并归一化写回；
   - `RuntimeConfig.apply_patch` 对非字符串且非可空的数值字段在补丁缺省、`None` 或空白串时保持当前生效值；前端工作台表单留空时则由 `SettingsView.vue` 的 `parseNumOrDefault` 回填 `DEFAULT_RUNTIME_CONFIG` 默认值后再提交，确保前端与后端一致「留空回退默认值」。
3. **工具与聊天消费侧防越界兜底**：`src/report_agent/runtime/tools.py#_setting_int` 与 `src/report_agent/chat/agent.py#cfg_int` / `cfg_float` 在读取配置时统一过滤 `None`、`bool`、非数字、`NaN`/`Inf` 及越界值，兜底回退模块内置默认常量。
4. **跨字段校验约束（`RuntimeConfig.validate`）**：
   - `agentQueryDefaultLimit <= agentQueryMaxLimit`（结果筛选默认行数不能大于最大行数）；
   - `chatCompactTriggerMessages > chatCompactKeepRecent`（自动压缩触发阈值必须严格大于保留原文条数）；
   - `gatewayMode == "live"` 时 `gatewayUrl` 不能为空且必须为有效 `http://` / `https://` 地址；
   - `llmBaseUrl` 与 `llmModel` 非空且不含控制字符；所有数值与枚举项均校验区间与正数约束，任一不通过即抛出 `RuntimeConfigValidationError`（映射 HTTP `400 INVALID_RUNTIME_CONFIG`）。

## 3. 配置生效优先级、热重载链路与启动期不变量边界

1. **生效优先级**：`DATA_DIR/config/runtime/current.json`（工作台在线热更新） > 进程环境变量 > `.env` > `Settings` 内置默认值。
2. **免重启热重载传播（`container.py#Container.apply_runtime_config`）**：
   - **网关与并发**：比较 `_gateway_signature`（包含 `gateway_mode`、`gateway_url`、`gateway_app_id`、`gateway_access_token`、`gateway_xml_style`、`gateway_connect_timeout_s`、`gateway_max_concurrency`），变化时新建 `UnifiedGatewayXmlClient` / `MockGatewayClient` 并通过 `ReloadableGatewayClient.swap` 原子排空切换；
   - **报告引擎与发布保留数**：同步更新 `container.settings`、`releases.keep` 并调用 `runner.reload_config`（同时刷新动态限流器与 Agent 缓存）；
   - **平台工具、聊天与清理任务**：`query_result` / `expand_period` 每次执行实时读取 `deps.settings`；`ChatAgent` / `ChatService` 每次按 `c.settings` 动态计算提示词上限、滚动压缩阈值与模型缓存键；`RunStore.cleanup` / `ChatStore.cleanup` 按当前 `c.settings.runs_keep_days` 执行留存清理。
3. **原子 0600 落盘与启动自愈**：`RuntimeConfigStore` 复用 `store/fsutil.py#write_json(..., mode=0o600)` 与 `append_jsonl(..., mode=0o600)`，在写入前先对临时文件描述符设 `0600` 权限再写入、`fsync`、`os.replace` 替换，杜绝任何微秒的明文密钥权限裸露窗口；若 `current.json` 意外缺失但 `index.jsonl` / `revisions/c*.json` 存在，启动阶段自动校验恢复最新修订快照。
4. **启动期不变量边界（仅 9 项不支持热更）**：仅 `DATA_DIR`、`SEED_ON_EMPTY`（涉及存储根目录与冷启动种子挂载）、`ADMIN_TOKEN_SECRET`、`ADMIN_TOKEN_TTL_S`、`ADMIN_COOKIE_SECURE`、`ADMIN_BOOTSTRAP_PASSWORD`（涉及启动期会话签名密钥与首启管理员初始化）、`LOG_LEVEL`、`LOG_DIR`（涉及进程日志处理器初始化）以及 `FRONTEND_DIST`（涉及静态资源路由挂载）属于启动期不变量，其余 48 项均已完全开放运行期热更新。

## 相关页面

- [文件化资源存储与 Git 原子发布机制](../architecture/resource-release-and-store.md)
- [FastAPI 路由与鉴权组件剖析](../components/api-and-auth.md)
- [嵌入式聊天选模板窗口组件剖析](../components/chat-embed.md)
- [Vue 3 资源工作台前端剖析](../components/workbench-frontend.md)
- [本地开发、测试与部署指南](../guides/dev-test-and-deploy.md)
