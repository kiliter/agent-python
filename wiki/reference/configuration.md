---
title: 环境变量与运行期配置参考
type: reference
tags: [reference, configuration, env, settings, hot-reload]
sources:
  - src/report_agent/config.py
  - src/report_agent/store/fsutil.py
  - src/report_agent/store/runtime_config.py
  - .env.example
updated: 2026-11-13
---

# 环境变量与运行期配置参考

<!-- #Created By AiCoding(codex) -->

平台配置由 `src/report_agent/config.py#Settings`（基于 `pydantic-settings`，环境变量名与字段名大小写不敏感映射，自动读取 `.env`）提供启动基线；其中**大模型、智能体运行限额、统一网关与调用凭证**共 26 项核心参数支持在工作台「系统设置」通过 `RuntimeConfigStore`（`DATA_DIR/config/runtime/current.json`）**在线热重载覆盖与按修订号（`c1`..`cN`）回退，无需重启服务**。

## 1. 完整环境变量清单

### 1.1 数据目录、生命周期与静态托管

| 环境变量 | `Settings` 字段 | 默认值 | 支持在线热更 | 说明 |
|----------|-----------------|--------|--------------|------|
| `DATA_DIR` | `data_dir` | `./data`（Docker 内 `/data`） | 否 | PVC 持久化根目录，存放 `repo/`、`releases/`、`drafts/`、`runs/`、`chats/`、`cases/`、`config/` 与 `audit.jsonl` |
| `SEED_ON_EMPTY` | `seed_on_empty` | `true` | 否 | `DATA_DIR` 为空时是否自动用内置 `seed/` 初始化首个发布版本 `r1` |
| `RELEASES_KEEP` | `releases_keep` | `50` | 否 | 磁盘保留的已物化发布目录 `releases/rN/` 数量上限，更早版本按需从 Git 恢复 |
| `RUNS_KEEP_DAYS` | `runs_keep_days` | `90` | 否 | 运行记录保留天数（`0` 表示永久保留不清理） |
| `FRONTEND_DIST` | `frontend_dist` | `None` | 否 | 前端构建产物目录（如 `frontend/dist`），配置后由本服务直接托管 SPA |
| `LOG_LEVEL` | `log_level` | `INFO` | 否 | 应用与 Uvicorn 日志级别 |
| `LOG_DIR` | `log_dir` | `None` | 否 | 日志文件输出目录，不配置时仅输出到标准控制台 |

### 1.2 大模型（OpenAI 兼容接口）配置

| 环境变量 | `Settings` 字段 | 默认值 | 支持在线热更 | 说明 |
|----------|-----------------|--------|--------------|------|
| `LLM_BASE_URL` | `llm_base_url` | `https://api.openai.com/v1` | **是**（`llmBaseUrl`） | OpenAI 兼容推理服务地址 |
| `LLM_API_KEY` | `llm_api_key` | `dummy` | **是**（`llmApiKey`） | 模型服务 API Key（`SecretStr` 保护，管理端掩码脱敏展示） |
| `LLM_MODEL` | `llm_model` | `deepseek-v4-flash` | **是**（`llmModel`） | 模型名称标识 |
| `LLM_TEMPERATURE` | `llm_temperature` | `0.0` | **是**（`llmTemperature`） | 采样温度，推荐 `0.0` 保持确定性推理 |
| `LLM_MAX_TOKENS` | `llm_max_tokens` | `None` | **是**（`llmMaxTokens`） | 单次模型输出最大 Token 上限（不设则走服务端默认） |
| `LLM_TIMEOUT_S` | `llm_timeout_s` | `120.0` | **是**（`llmTimeoutS`） | 单次模型 HTTP 请求超时秒数 |
| `LLM_HTTP_RETRIES` | `llm_http_retries` | `2` | **是**（`llmHttpRetries`） | 模型 HTTP 层针对网络错误与 5xx 的自动重试次数 |
| `LLM_PARALLEL_TOOL_CALLS` | `llm_parallel_tool_calls` | `true` | **是**（`llmParallelToolCalls`） | 是否允许模型单轮并行调用多个工具（默认开启，`None` 使用服务端默认） |
| `LLM_STRICT_TOOLS` | `llm_strict_tools` | `None` | **是**（`llmStrictTools`） | 是否声明 strict 工具定义（内网推理框架不支持时可设为 `false`） |
| `LLM_TOOL_CHOICE_REQUIRED` | `llm_tool_choice_required` | `None` | **是**（`llmToolChoiceRequired`） | 推理服务端是否支持 `tool_choice=required` |

### 1.3 智能体运行与证据校验控制

| 环境变量 | `Settings` 字段 | 默认值 | 支持在线热更 | 说明 |
|----------|-----------------|--------|--------------|------|
| `AGENT_OUTPUT_MODE` | `agent_output_mode` | `tool` | **是**（`agentOutputMode`） | 结构化交卷通道：`tool`（调用 `submit_report` 工具）\| `native`（`json_schema`）\| `json_object`（DeepSeek 官方兼容）\| `prompted` |
| `AGENT_NATIVE_STRICT` | `agent_native_strict` | `true` | **是**（`agentNativeStrict`） | `native` 模式下是否发送 strict `json_schema` 约束解码 |
| `AGENT_OUTPUT_RETRIES` | `agent_output_retries` | `3` | **是**（`agentOutputRetries`） | `EvidenceChecker` 证据校验未通过时，最多退回让模型重交几次 |
| `AGENT_TOOL_RETRIES` | `agent_tool_retries` | `2` | **是**（`agentToolRetries`） | 工具入参不合法时，最多让模型修正重试几次 |
| `AGENT_REQUEST_LIMIT` | `agent_request_limit` | `25` | **是**（`agentRequestLimit`） | 单次运行请求模型轮次上限 |
| `AGENT_TOOL_CALLS_LIMIT` | `agent_tool_calls_limit` | `120` | **是**（`agentToolCallsLimit`） | 单次运行工具调用总次数上限（支撑 12～36 个月跨账期查询） |
| `AGENT_RUN_TIMEOUT_S` | `agent_run_timeout_s` | `600.0` | **是**（`agentRunTimeoutS`） | 单次报告生成总超时秒数 |
| `AGENT_MAX_CONCURRENT_RUNS` | `agent_max_concurrent_runs` | `8` | **是**（`agentMaxConcurrentRuns`） | 进程内并发运行智能体的动态限流器（`_DynamicLimiter`）上限 |
| `AGENT_PREVIEW_ROWS` | `agent_preview_rows` | `10` | **是**（`agentPreviewRows`） | `call_api` 返回给模型的摘要预览最大行数 |

### 1.4 统一网关连接配置

| 环境变量 | `Settings` 字段 | 默认值 | 支持在线热更 | 说明 |
|----------|-----------------|--------|--------------|------|
| `GATEWAY_MODE` | `gateway_mode` | `mock` | **是**（`gatewayMode`） | `live`（调用真实统一网关 HTTP 接口）或 `mock`（读取本地 `mock-gateway/` 样例） |
| `GATEWAY_URL` | `gateway_url` | `""` | **是**（`gatewayUrl`） | 统一网关地址（`live` 模式下必填） |
| `GATEWAY_APP_ID` | `gateway_app_id` | `""` | **是**（`gatewayAppId`） | 统一网关应用标识凭证（`SecretStr`） |
| `GATEWAY_ACCESS_TOKEN` | `gateway_access_token` | `""` | **是**（`gatewayAccessToken`） | 统一网关访问令牌（`SecretStr`） |
| `GATEWAY_XML_STYLE` | `gateway_xml_style` | `java` | **是**（`gatewayXmlStyle`） | `java`（对齐 Java Jackson 3 字母序与空值 `xsi:nil`）或 `clean`（声明序、无 `xsi:nil`） |
| `GATEWAY_CONNECT_TIMEOUT_S` | `gateway_connect_timeout_s` | `5.0` | **是**（`gatewayConnectTimeoutS`） | 网关 TCP 连接超时秒数 |
| `GATEWAY_MAX_CONCURRENCY` | `gateway_max_concurrency` | `32` | 否 | 进程内调用真实统一网关（`UnifiedGatewayXmlClient`）的最大并发请求信号量上限 |

### 1.5 管理端与上游接口认证

| 环境变量 | `Settings` 字段 | 默认值 | 支持在线热更 | 说明 |
|----------|-----------------|--------|--------------|------|
| `ADMIN_TOKEN_SECRET` | `admin_token_secret` | `None` | 否 | 工作台会话签名密钥；未配时自动生成并保存在 `DATA_DIR/config/.token-secret` |
| `ADMIN_TOKEN_TTL_S` | `admin_token_ttl_s` | `43200`（12h） | 否 | 工作台登录会话有效秒数 |
| `ADMIN_COOKIE_SECURE` | `admin_cookie_secure` | `false` | 否 | HTTPS 部署时设为 `true` |
| `ADMIN_BOOTSTRAP_PASSWORD` | `admin_bootstrap_password` | `None` | 否 | 首次启动且无任何用户时，自动使用该密码初始化 `admin` 账号 |
| `REPORT_API_KEYS` | `report_api_keys` | `""` | **是**（`reportApiKeys`） | 上游接口 `/api/v1/reports*` 与嵌入式聊天接口 `/api/v1/chat/*` 共用的 `X-API-Key` 白名单（支持逗号分隔多把密钥），可通过管理端 `/api/v1/settings/api-key*` 在线查看、修改、清空或一键重新生成并免重启热生效；生产必填 |

## 2. 配置生效优先级与安全持久化

1. **优先级**：`DATA_DIR/config/runtime/current.json`（工作台在线热更新） > 进程环境变量 > `.env` > `Settings` 默认值。
2. **原子 0600 落盘与启动自愈**：`RuntimeConfigStore` 复用 `store/fsutil.py#write_json(..., mode=0o600)` 与 `append_jsonl(..., mode=0o600)`，在写入前先对临时文件描述符设 `0600` 权限再写入、`fsync`、`os.replace` 替换，杜绝任何微秒的明文密钥权限裸露窗口；若 `current.json` 意外缺失但 `index.jsonl` / `revisions/c*.json` 存在，启动阶段自动校验恢复最新修订快照。

## 相关页面

- [文件化资源存储与 Git 原子发布机制](../architecture/resource-release-and-store.md)
- [FastAPI 路由与鉴权组件剖析](../components/api-and-auth.md)
- [本地开发、测试与部署指南](../guides/dev-test-and-deploy.md)
