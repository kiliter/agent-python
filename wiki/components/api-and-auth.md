---
title: FastAPI 路由与鉴权组件剖析
type: component
tags: [component, api, auth, sse, security, runtime-config]
sources:
  - src/report_agent/main.py
  - src/report_agent/container.py
  - src/report_agent/api/auth.py
  - src/report_agent/api/common.py
  - src/report_agent/api/routes_templates.py
  - src/report_agent/api/routes_resources.py
  - src/report_agent/api/routes_system.py
  - src/report_agent/api/routes_chat.py
  - src/report_agent/api/run_views.py
updated: 2026-11-12
---

# FastAPI 路由与鉴权组件剖析

<!-- #Created By AiCoding(codex) -->

Web 接口层位于 `src/report_agent/main.py`、`container.py` 与 `src/report_agent/api/` 下，同时承担面向业务人员的**资源工作台管理接口**、面向外部上游系统的**报告生成服务接口**以及面向 iframe 集成的**嵌入式聊天窗口接口**。

## 1. 应用装配与单栈托管（`main.py` + `container.py`）

- **`AppContainer`（`container.py`）**：集中装配 `DataLayout`、`ResourceService`、`RunStore`、`CaseStore`、`AuthService`、`AuditLog`、`RuntimeConfigStore`、`ReloadableGatewayClient`、`AgentRunner` 与 `ChatService`（含 `ChatStore`、`ChatRunManager`）。在 `lifespan` 启动钩子中自动执行 `resources.bootstrap(seed_dir)`（首次启动自动从 `seed/` 初始化 `r1`）、引导管理员账号、启动 `RunStore` 后台写协程与周期清理协程（同步清理过期运行记录与 `ChatStore` 会话），退出时优雅排空在途聊天运行任务。
- **统一错误契约**：全局异常处理器将 `PlatformError`、`InputValidationError`（400）、`TemplateUnavailableError`（404）、`DraftConflictError`（409）、`PublishValidationError`（422）与 `RequestValidationError`（422）统一格式化为 `{code, message, ...}` JSON 结构。
- **前端多页与 SPA 单体托管**：若配置了 `FRONTEND_DIST`（如 `frontend/dist`）且目录存在，`main.py` 自动挂载静态产物（如 `/embed.html` 直接命中独立嵌入页构建文件），并对非 `/api/`、`/healthz` 的工作台前端路径做 SPA `index.html` 路由回退（同时拦截路径逃逸），支持单容器一体化交付。

## 2. 鉴权体系与安全防护（`api/auth.py` + `api/routes_chat.py`）

平台按接口消费场景提供三类鉴权依赖：

| 鉴权依赖 | 适用接口范围 | 凭证传递方式 | 安全机制细节 |
|----------|--------------|--------------|--------------|
| `require_user` | 工作台全部管理、编辑、试运行、版本与配置接口 | HttpOnly Cookie `ra_session`（`SameSite=Strict`）或 `Authorization: Bearer <token>` | 口令采用 **PBKDF2-HMAC-SHA256（600,000 次迭代 + 随机盐）** 存储于 `users.yaml`，登录接口通过 `asyncio.to_thread` + `_LOGIN_SEM = asyncio.Semaphore(4)` 将 CPU 密集型哈希校验移出事件循环并限制并发；会话采用带过期时间的 HMAC-SHA256 签名令牌 + 有界服务端登出吊销列表（`TokenService._revoked` 上限 `max_revoked=4096` 并惰性淘汰过期令牌）；`LoginGuard` 双轨防爆破：同一账号连续输错 5 次自动锁定 5 分钟（返回 HTTP 429 `LOGIN_LOCKED`），通过 `_known_users` 保护真实账号与活跃锁定项不被随机不存在账号挤出，并叠加客户端来源 IP 失败计数桶（`_ip_fails`）拦截撞库洪泛 |
| `require_report_key` | 上游系统直连填报接口 `POST /api/v1/reports`、`/reports/stream` | 请求头 `X-API-Key` | 实时读取 `container.settings.report_api_key_set()`（支持逗号分隔多把密钥平滑轮换与在线热更），使用 `hmac.compare_digest` 逐项常量时间比对；未配置时仅在开发态放行 |
| `require_chat_caller` | 嵌入式聊天接口 `/api/v1/chat/*` | 请求头 `X-API-Key` **或**管理端会话令牌 | 当请求显式携带非空 `X-API-Key` 时，先走 `require_report_key` 严格校验密钥有效性（错误 Key 即便有管理端登录态也立即返回 HTTP 401），通过后再识别管理端登录态返回 `ChatCaller(kind="user")`（兼容工作台模拟页携带系统 Key 使用 `target="draft"`），否则返回 `ChatCaller(kind="key")`；未携带 `X-API-Key` 时优先识别管理端有效登录态，未登录再回退 `require_report_key`。`ChatCaller(kind="key")` 仅允许 `target="online"`，访问 `"draft"` 返回 HTTP 403 `DRAFT_FORBIDDEN` |

此外，所有写操作的审计人（`operator`）一律强制取自当前登录会话 `user.display_name`，忽略前端请求体中传入的任何同名字段，防止伪造操作人。

## 3. 路由模块拆分

### 3.1 `routes_templates.py`：模板全生命周期与试运行

- 模板列表、创建、复制、下线（生成新版本）、恢复为草稿；
- `GET /templates/{id}?version=working|draft|online|rN` 统一详情读取；
- 草稿整包保存、单字段新增/重命名（带 `originalName` 自动同步替换正文 `{{旧名}}`）、删除（被正文引用时非强制删除返回 400 `FIELD_IN_USE`）、拖拽排序 `fields-order`、批量修改证据类型（拦截将 `type: list` 字段改为非法的 `evidence: input`，返回 400 `INVALID_RESOURCE`）、绑定 Skill 更新 `skills`。所有细粒度写草稿接口均支持传入可选乐观锁 `revision`（不匹配时返回 409 `DRAFT_CONFLICT`），并在响应中返回最新 `revision` / `draft` 供前端同步；
- 在线 Jinja2 沙箱实时渲染预览 `POST /templates/{id}/render-preview`（支持传入未落盘的内存编辑态 `fields` 定义实时预览字段增改效果）；
- 发布前校验 `POST /templates/{id}/validate`（返回 `errors`、`warnings`、`drift` 基线漂移提示）、单点发布、版本历史、结构化 Diff 与回退；
- 回归用例 CRUD（支持传 `fromRunId` 从某次真实运行一键提取入参、单据和期望字段值生成用例）；
- 在线试运行 `dryrun` 与 SSE 流式轨迹 `dryrun/stream`。

### 3.2 `routes_resources.py`：Skill、网关契约与系统提示词

- **Skill 管理（`/skills`）**：列表（统计被多少模板引用及近 7 天加载次数）、新建、草稿编辑（校验 frontmatter `name` 与目录名一致及关联接口存在性）、发布、回退与修订记录；
- **接口契约管理（`/apis`）**：列表（自动提取动态参数与固定公共参数）、新建骨架、YAML 全文或基础属性草稿保存、发布、回退，以及**在线接口拨测 `POST /apis/{name}/test-call`**（支持传入未保存的编辑态 `yamlText` 直接向网关发起真实或 Mock 试调，返回脱敏后的实际请求 XML/JSON、原始响应与抽取出的二维记录表）；
- **系统提示词管理（`/settings/system-prompt`）**：读取、草稿保存、发布（支持 `expectedRevision` / `revision` 乐观锁校验）与版本回退；
- **模型、运行期热重载与调用凭证管理（`/settings/model`、`/settings/runtime*`、`/settings/api-key*`）**：查看当前生效配置、在线修改并免重启热重载 LLM / 网关参数与 `reportApiKeys`（`/settings/runtime` 及修订历史仅展示脱敏值 `reportApiKeysMasked`；管理端专用 `/settings/api-key` 与 `/settings/api-key/regenerate` 支持查看完整密钥、自定义多密钥/清空免鉴权及一键重新生成 `ra_` 高强度随机密钥，立即对 `/reports*` 与 `/chat/*` 生效）。

### 3.3 `routes_system.py`：发布中心、运行记录、热更新配置与上游服务

- **版本中心（`/releases`）**：版本流水列表、任意两版本跨资源级 Diff（`GET /releases/diff?a=r1&b=r2`）、毫秒级全局紧急切换 `POST /releases/emergency-switch`；
- **运行记录（`/runs`）**：多维筛选查询（日期区间、手机号、模板 ID、状态 `SUCCESS`/`PARTIAL`/`FAILED`、入口、批次号、全文检索）与单次运行完整溯源详情 `GET /runs/{runId}`；
- **模型与运行期热重载（`/settings/model`、`/settings/runtime`）**：查看当前生效配置、在线修改并热重载 LLM / 网关参数、查看修订历史与一键回退；
- **上游报告生成（`/reports`、`/reports/stream`）**：由 `api/run_views.py#to_upstream_report` 将内部运行结果裁剪为精简稳定的上游集成契约。

### 3.4 `routes_chat.py`：嵌入式聊天窗口与模板路由接口

挂载于 `/api/v1/chat`，提供契约 `docs/chat-embed-api.md` 定义的 10 个端点：会话创建/恢复与入参更新（`POST /sessions`、`GET /sessions/{sid}`）、SSE 对话与自动模板推荐（`POST /sessions/{sid}/messages`）、候选模板检索（`GET /sessions/{sid}/templates`）、模板结构与预渲染样例预览（`GET /sessions/{sid}/templates/{template_id}`）、参数校验与后台运行启动（`POST /sessions/{sid}/runs`）、支持 `?after=N`、`Last-Event-ID` 断点续接及 `includeRaw` / `rawAfter` 原样过程事件推送的运行事件流（`GET /runs/{run_id}/events`）、原样过程事件按需拉取（`GET /runs/{run_id}/raw`）、手动取消（`POST /runs/{run_id}/cancel`）以及幂等审计确认（`POST /runs/{run_id}/confirm`）。其中 `/runs/{run_id}/*` 四个端点均支持可选请求头 `X-Chat-Session-Id` 或查询参数 `sessionId` 做跨会话归属防越权校验。内部机制详见 [嵌入式聊天选模板窗口组件剖析](chat-embed.md)。

## 相关页面

- [嵌入式聊天选模板窗口组件剖析](chat-embed.md)
- [单智能体请求处理管道](../architecture/request-pipeline.md)
- [文件化资源存储与 Git 原子发布机制](../architecture/resource-release-and-store.md)
- [Vue 3 资源工作台前端剖析](workbench-frontend.md)
- [环境变量与运行期配置参考](../reference/configuration.md)
