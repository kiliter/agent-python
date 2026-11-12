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
  - src/report_agent/api/run_views.py
updated: 2026-11-12
---

# FastAPI 路由与鉴权组件剖析

<!-- #Created By AiCoding(codex) -->

Web 接口层位于 `src/report_agent/main.py`、`container.py` 与 `src/report_agent/api/` 下，同时承担面向业务人员的**资源工作台管理接口**与面向外部上游系统的**报告生成服务接口**。

## 1. 应用装配与单栈托管（`main.py` + `container.py`）

- **`AppContainer`（`container.py`）**：集中装配 `DataLayout`、`ResourceService`、`RunStore`、`CaseStore`、`AuthService`、`AuditLog`、`RuntimeConfigStore`、`ReloadableGatewayClient` 与 `AgentRunner`。在 `lifespan` 启动钩子中自动执行 `resources.bootstrap(seed_dir)`（首次启动自动从 `seed/` 初始化 `r1`）、引导管理员账号并启动 `RunStore` 后台写协程。
- **统一错误契约**：全局异常处理器将 `PlatformError`、`InputValidationError`（400）、`TemplateUnavailableError`（404）、`DraftConflictError`（409）、`PublishValidationError`（422）与 `RequestValidationError`（422）统一格式化为 `{code, message, ...}` JSON 结构。
- **前端 SPA 单体托管**：若配置了 `FRONTEND_DIST`（如 `frontend/dist`）且目录存在，`main.py` 自动挂载静态资源并对非 `/api/`、`/healthz` 路径做 SPA `index.html` 路由回退（同时拦截路径逃逸），支持单容器一体化交付。

## 2. 双轨鉴权与安全防护（`api/auth.py`）

平台按调用方身份隔离两套互不交叉的鉴权依赖：

| 鉴权依赖 | 适用接口范围 | 凭证传递方式 | 安全机制细节 |
|----------|--------------|--------------|--------------|
| `require_user` | 工作台全部管理、编辑、试运行、版本与配置接口 | HttpOnly Cookie `ra_session`（`SameSite=Strict`）或 `Authorization: Bearer <token>` | 口令采用 **PBKDF2-HMAC-SHA256（600,000 次迭代 + 随机盐）** 存储于 `users.yaml`；会话采用带过期时间的 HMAC-SHA256 签名令牌 + 服务端登出吊销列表；同一账号连续输错 5 次自动锁定 5 分钟（返回 HTTP 429 `LOGIN_LOCKED`） |
| `require_api_key` | 上游系统接口 `POST /api/v1/reports`、`/reports/stream` | 请求头 `X-API-Key` | 当配置了非空 `REPORT_API_KEYS`（支持逗号分隔多把密钥平滑轮换）时，使用 `hmac.compare_digest` 逐项常量时间比对；未设置环境变量时仅在开发态放行 |

此外，所有写操作的审计人（`operator`）一律强制取自当前登录会话 `user.display_name`，忽略前端请求体中传入的任何同名字段，防止伪造操作人。

## 3. 路由模块拆分

### 3.1 `routes_templates.py`：模板全生命周期与试运行

- 模板列表、创建、复制、下线（生成新版本）、恢复为草稿；
- `GET /templates/{id}?version=working|draft|online|rN` 统一详情读取；
- 草稿整包保存、单字段新增/重命名（带 `originalName` 自动同步替换正文 `{{旧名}}`）、删除（被正文引用时非强制删除返回 400 `FIELD_IN_USE`）、拖拽排序 `fields-order`、批量修改证据类型；
- 在线 Jinja2 沙箱实时渲染预览 `POST /templates/{id}/render-preview`；
- 发布前校验 `POST /templates/{id}/validate`（返回 `errors`、`warnings`、`drift` 基线漂移提示）、单点发布、版本历史、结构化 Diff 与回退；
- 回归用例 CRUD（支持传 `fromRunId` 从某次真实运行一键提取入参、单据和期望字段值生成用例）；
- 在线试运行 `dryrun` 与 SSE 流式轨迹 `dryrun/stream`。

### 3.2 `routes_resources.py`：Skill、网关契约与系统提示词

- **Skill 管理（`/skills`）**：列表（统计被多少模板引用及近 7 天加载次数）、新建、草稿编辑（校验 frontmatter `name` 与目录名一致及关联接口存在性）、发布、回退与修订记录；
- **接口契约管理（`/apis`）**：列表（自动提取动态参数与固定公共参数）、新建骨架、YAML 全文或基础属性草稿保存、发布、回退，以及**在线接口拨测 `POST /apis/{name}/test-call`**（支持传入未保存的编辑态 `yamlText` 直接向网关发起真实或 Mock 试调，返回脱敏后的实际请求 XML/JSON、原始响应与抽取出的二维记录表）；
- **系统提示词管理（`/settings/system-prompt`）**：读取、草稿保存、发布与版本回退。

### 3.3 `routes_system.py`：发布中心、运行记录、热更新配置与上游服务

- **版本中心（`/releases`）**：版本流水列表、任意两版本跨资源级 Diff（`GET /releases/diff?a=r1&b=r2`）、毫秒级全局紧急切换 `POST /releases/emergency-switch`；
- **运行记录（`/runs`）**：多维筛选查询（日期区间、手机号、模板 ID、状态 `SUCCESS`/`PARTIAL`/`FAILED`、入口、批次号、全文检索）与单次运行完整溯源详情 `GET /runs/{runId}`；
- **模型与运行期热重载（`/settings/model`、`/settings/runtime`）**：查看当前生效配置、在线修改并热重载 LLM / 网关参数、查看修订历史与一键回退；
- **上游报告生成（`/reports`、`/reports/stream`）**：由 `api/run_views.py#to_upstream_report` 将内部运行结果裁剪为精简稳定的上游集成契约。

## 相关页面

- [单智能体请求处理管道](../architecture/request-pipeline.md)
- [文件化资源存储与 Git 原子发布机制](../architecture/resource-release-and-store.md)
- [Vue 3 资源工作台前端剖析](workbench-frontend.md)
- [环境变量与运行期配置参考](../reference/configuration.md)
