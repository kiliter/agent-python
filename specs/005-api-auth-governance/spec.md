# 需求文档（Spec）：REST/SSE 服务网关、三轨安全鉴权体系与全生命周期治理接口

<!-- #Created By AiCoding(codex) -->

> **Spec Kit 使用约定**：产物文件名固定为 `spec.md`、`plan.md`、`tasks.md`；三类外部独立交付物按需确认，仅涉及项单独生成并建立链接，不涉及项只记录依据。本需求已全部交付并通过自动化验收，文中所有路径、符号、错误码与配置项均与当前仓库源码及测试事实一致；不适用章节保留标题并写明依据，不残留未替换占位符。
> **项目依据**：项目宪章 `.specify/memory/constitution.md`、`AGENTS.md` 及 `wiki/index.md`。

---

**功能分支**：`[005-api-auth-governance]`

**创建日期**：2026-11-16

**状态**：已交付归档

**输入**：智能申告报告填写与资源治理平台（`report-agent`）全栈研发工作拆分 —— 负责 FastAPI 应用工厂与容器生命周期装配、防爆破会话与多密钥轮换三轨鉴权、模板细粒度编辑乐观锁与在线试运行接口、Skill/API（含在线拨测）与提示词治理接口、跨版本 Diff 与紧急切换及上游报表服务契约。

## 基本信息 【核心】

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-005` |
| 需求名称 | REST/SSE 服务网关、三轨安全鉴权体系与全生命周期治理接口 |
| 核算工作量 | `33.0 人天`（项目总工作量 `250.0` 人天中的归档子规格 `005/008`） |
| 资料与证据来源 | 【高可信】代码事实：`src/report_agent/main.py`、`container.py`、`config.py`、`store/runtime_config.py`、`src/report_agent/api/__init__.py`、`auth.py`、`common.py`、`dto.py`、`run_views.py`、`routes_templates.py`、`routes_resources.py`、`routes_system.py`<br>【高可信】测试证据：`tests/test_api.py`、`tests/test_api_and_store_fixes.py`、`tests/test_api_routes_json.py`、`tests/test_deep_audit_fixes.py`、`tests/test_runtime_config_hot_reload.py`<br>【中可信】契约与知识库：`docs/frontend-api-handoff.md`、`wiki/components/api-and-auth.md`、`wiki/reference/configuration.md`<br>【归档基线】既有需求拆分：`specs/005-api-auth-governance/` 原初版 `spec.md`、`plan.md`、`tasks.md`（18 项任务 / 33.0 人天） |
| 文档版本 | `2.0` |
| 文档状态 | 已交付归档 |

---

## 1. 业务背景与目标 【核心】

### 1.1 业务背景

`report-agent` 智能申告报告填写与资源治理平台同时服务三类核心接入方：面向业务配置人员与平台管理员的 Vue 3 可视化治理工作台、面向外部工单系统的同步/流式报表生成上游服务，以及以 iframe 嵌入外部系统的智能填报聊天窗口。所有业务规则均保存在文件化资产（`templates/`、`skills/`、`apis/`、`system-prompt.md`）与 `DATA_DIR` 发布快照中，亟需一层高可靠、无数据库依赖、强安全边界的 FastAPI 服务网关来统一承担组件装配、鉴权防护、全生命周期编辑治理与运行时热更新调度。

在多配置人员协同维护模板/技能/接口契约与生产线上高频调用的双重压力下，接口层需要解决四大关键工程痛点：（1）认证接口若无并发节流、恒定时间假校验与分桶防撞库保护，极易因 600,000 次 PBKDF2 高迭代算力放大或随机用户名喷洒导致服务雪崩与已锁真实账号被驱逐；（2）整包覆盖草稿编辑会导致多人协作互相覆盖、字段重命名破坏 Jinja2 正文引用或误删在用字段；（3）双协议统一网关（XML/JSON）接口契约及运行期配置若只能在落盘发布或重启容器后才可验证与生效，将严重拖慢排障与线上参数调优节奏；（4）历史运行数据在模板字段演进后可能出现 `templateDef` 破损或非预期值，需确保审计详情与统计大盘永不崩溃，且一切写操作审计身份不可由前端伪造。

### 1.2 业务目标

- **GOAL-1**：构建单进程高可靠应用装配入口（`create_app` + `Container`），原生支持子路径反向代理部署（`APP_ROOT_PATH`）、SPA 前端静态产物安全托管、周期性过期清理与统一结构化 JSON 错误映射。
- **GOAL-2**：落地覆盖管理端会话（PBKDF2 600k + `LoginGuard` + `TokenService`）、上游报表调用（可热轮换 `X-API-Key`）与嵌入式聊天协同（`require_chat_caller` 引用协同）的三轨安全鉴权体系，抵御撞库、计时侧信道与算力放大攻击。
- **GOAL-3**：交付全资源细粒度 `expected_revision` 乐观锁治理接口，支持模板单字段增改/重命名联动/防误删、内存态沙箱预览、未落盘双协议网关接口在线拨测（`test-call`）与从历史运行一键沉淀回归用例。
- **GOAL-4**：交付全局跨版本 Diff、毫秒级无冗余提交紧急回退切换（`emergency-switch`）、破损历史数据容错审计详情，以及覆盖全部 `48` 项 `_ORDERED_FIELDS` 参数和 `X-API-Key` 的免重启热更新治理闭环。

---

## 2. 需求概述 【核心】

本需求对应 `report-agent` 平台后端 FastAPI Web 网关与全生命周期治理接口层（`RA-005`），向上承接 Spec 006 Vue 3 工作台前端与外部上游业务系统调用，向下通过 `Container` 显式注入并调度 Spec 001（领域模型与 Jinja2 沙箱）、Spec 002（文件化 Git 发布与乐观锁草稿存储）、Spec 003（`AgentRunner` 单智能体引擎）与 Spec 004（`ReloadableGatewayClient` 外部网关连接器）。

交付能力按四个核心业务场景组织：其一，容器装配、反代前缀剥离中间件、抗算力放大登录守卫与 `X-API-Key` 上游报表 REST/SSE 服务；其二，面向模板 IDE 的细粒度乐观锁字段编排、正文变量联动重命名、内存态实时预览、用例抽取与 SSE 试运行；其三，纯文本 Skill 容错覆盖治理、双协议 XML/JSON 网关契约局部补丁与未落盘在线拨测，以及系统提示词多版本查阅和 API Key 轮换；其四，跨版本差异审计、毫秒级紧急软链接切换、多维运行统计与 `48` 项 `RuntimeConfig` 免重启热生效。

### 2.1 用户场景与测试

#### 用户故事 1（US1）— 防爆破工作台会话鉴权与可轮换上游报告服务接口（优先级：P1）

- **用户旅程**：作为工作台管理员/配置人员或上游工单系统集成方，我希望通过防爆破会话接口安全登录管理工作台，并通过可随时在线轮换的多组 `X-API-Key` 稳定调用同步/流式报告生成服务，即使在子路径反向代理与流式客户端意外断连情况下也不丢审计记录与保活连接。
- **优先级理由**：鉴权网关与上游报告生成入口是平台对外暴露的唯一安全边界与生产业务出口，必须作为 P1 MVP 优先闭环。
- **独立测试**：向 FastAPI `TestClient` 依次发起错误口令登录、未知用户喷洒、并发登录、`POST /api/v1/auth/logout` 吊销校验、子路径前缀访问及轮换前后 `X-API-Key` 调用 `POST /api/v1/reports` 与 `POST /api/v1/reports/stream` 即可完成独立验证。
- **关联需求**：`FR-001`、`FR-002`、`FR-003`
- **验收场景**：
  1. **前提** 已初始化 `UserStore` 与 `LoginGuard(max_failures=5, lock_s=300, ip_max_failures=20)`，**当** 未知用户名或错误口令请求 `POST /api/v1/auth/login` 时，**则** 系统使用 `DUMMY_PASSWORD_HASH` 执行等成本 PBKDF2-HMAC-SHA256（`_ITERATIONS = 600_000`）线程离线校验（受单事件循环信号量 `_LOGIN_MAX_CONCURRENCY = 4` 限制）并基于直连 `request.client.host` 累计失败次数；触发账号或 IP 阈值后返回 HTTP `429`（`code="LOGIN_LOCKED"`），成功登录签发 `HttpOnly`、`SameSite=strict` 的 `ra_session` Cookie 与 Bearer Token，且未知用户持续撞库不会驱逐 `_known_users` 保护桶中的真实锁定记录。
  2. **前提** 用户已登录并获取有效会话令牌，**当** 调用 `POST /api/v1/auth/logout` 后再次携带该旧 Token 访问受保护接口，**则** `TokenService` 依据撤销 nonce 表（`max_revoked = 8192`）立即拒绝并返回 HTTP `401`（`code="UNAUTHORIZED"`）。
  3. **前提** 服务端配置了至少一个有效密钥（`report_api_key_set()`），**当** 上游系统携带合法 `X-API-Key` 调用 `POST /api/v1/reports` 或 `POST /api/v1/reports/stream` 时，**则** `require_report_key` 通过 `hmac.compare_digest` 常量时间比对放行并强制锁定 `target="online"`、`entry="上游调用"`、`operator="upstream"` 执行填报，SSE 流每 `15` 秒发送 `: keep-alive` 保活帧且后台协程受 `_BG_TASKS` 强引用托管，客户端中途断开后仍安全完成运行并落盘。

#### 用户故事 2（US2）— 细粒度乐观锁模板编排、沙箱实时预览与在线试运行接口（优先级：P1）

- **用户旅程**：作为模板配置工程师，我希望在工作台对报告模板元数据、单字段、排序、入参、关联技能与正文进行细粒度增量修改，在修改字段名时自动联动修正正文引用并拦截误删，在不写盘状态下实时预览渲染效果，以及在线流式试运行并从真实运行一键沉淀回归用例。
- **优先级理由**：模板资产高频协同编辑极易引发多人互相覆盖或正文变量断裂；完善的细粒度乐观锁与即时试运行闭环是工作台核心生产力基础（P1）。
- **独立测试**：携带一致与过期 `revision` 并发请求模板字段编辑/重命名/删除接口，传入内存态未落盘 `fields` 调用 `POST /api/v1/templates/{tid}/render-preview`，以及调用 `POST /api/v1/templates/{tid}/dryrun/stream` 和 `POST /api/v1/templates/{tid}/cases` 即可独立完成验证。
- **关联需求**：`FR-004`、`FR-005`
- **验收场景**：
  1. **前提** 模板草稿当前修订号为 `N`，**当** 客户端携带 `revision=N` 与 `originalName` 调用 `PUT /api/v1/templates/{tid}/fields/{name}` 重命名字段时，**则** 服务端原子更新字段定义并通过 `_rename_body_variable` 同步重写正文输出块与控制块中的合法变量引用（保留 `{# ... #}` 注释、字符串字面量、过滤器与 `.attr` 属性访问），同时拦截 `_RESERVED_FIELD_NAMES` 保留字及 `list` 类型设置 `evidence="input"`（`400 INVALID_FIELD_EVIDENCE`）；若传入 `revision != N` 则返回 HTTP `409`（`code="DRAFT_CONFLICT"`）并附带 `current` 草稿元数据，传入布尔或负数则经 `parse_expected_revision` 返回 HTTP `400`（`code="INVALID_REVISION"`）。
  2. **前提** 模板正文中仍在引用某字段且请求未传 `force=true`，**当** 调用 `DELETE /api/v1/templates/{tid}/fields/{name}` 时，**则** 接口通过 `_resolve_delete_field_revision` 解析查询参数或请求体中的乐观锁版本号并返回 HTTP `400`（`code="FIELD_IN_USE"`）阻止误删；传入临时未落盘 `fields` 调用 `POST /api/v1/templates/{tid}/render-preview` 时基于内存临时模板执行 Jinja2 沙箱渲染且不改动磁盘草稿。
  3. **前提** 模板具备有效草稿及试运行入参，**当** 调用 `POST /api/v1/templates/{tid}/dryrun/stream` 或基于该 `runId` 调用 `POST /api/v1/templates/{tid}/cases`（传入 `fromRunId`）时，**则** 流式端点以 `detail_view` 推送完整调试结果与过程事件，用例创建端点自动抽取 `inputs`、`documentText` 及所有 `found` 字段期望值（含列表 JSON 字符串及 `"0"`/`"False"` 非空假值）。

#### 用户故事 3（US3）— 技能、双协议网关契约在线拨测与提示词治理接口（优先级：P2）

- **用户旅程**：作为配置工程师，我希望统一治理纯文本 `SKILL.md`、双协议（`unified-gateway-xml` / `unified-gateway-json`）网关接口契约与全局系统提示词，支持局部补丁保存、草稿损坏容错隔离、未落盘接口在线沙箱拨测（`test-call`），并在需要时即时重置对外 `X-API-Key`。
- **优先级理由**：接口契约与技能方法论直接决定取数准确率，未落盘在线拨测与密钥即时轮换能将配置错误阻断在发布前并保证服务免重启安全切钥（P2）。
- **独立测试**：对 `/api/v1/skills/*`、`/api/v1/apis/*`、`/api/v1/settings/system-prompt*` 与 `/api/v1/settings/api-key*` 依次执行损坏草稿降级列表、局部 `ApiDraftBody.api` 补丁、带临时 `yamlText` 的 `test-call` 拨测及密钥重生成调用即可完成验证。
- **关联需求**：`FR-006`、`FR-007`、`FR-008`
- **验收场景**：
  1. **前提** 网关接口存在可编辑工作副本，**当** 客户端调用 `PUT /api/v1/apis/{name}/draft` 仅传入 `api` 结构化补丁字段（如 `timeoutMs`、`processCode`、`connector`、`retry`），或携带未保存 `yamlText` 与测试参数调用 `POST /api/v1/apis/{name}/test-call` 时，**则** 草稿接口仅更新对应字段保留其余结构；拨测接口经 `_prepare_test_call_api` 校验 `api.name == name`（不一致返回 `400 API_NAME_MISMATCH`）、契约 Schema（`400 INVALID_API_SCHEMA`）及入参（`400 INVALID_PARAMS`）后在当前网关实例执行并记录 `api-test-call` 审计事件，全程不覆盖磁盘草稿。
  2. **前提** 某草稿资源目录中存在语法损坏或非 Mapping YAML 文件，**当** 调用 `GET /api/v1/skills`、`GET /api/v1/apis` 或 `POST /api/v1/apis/{name}/validate` 时，**则** 列表接口经 `_safe_overlay` 安全降级回退读取线上快照不崩溃，`validate` 返回结构化错误及脱敏后的 `requestPreview`（XML/JSON 预览报文）；系统提示词支持 `version=working|online|draft|rN` 四种基准读取与草稿发布/回滚。
  3. **前提** 管理员拥有管理端有效会话，**当** 调用 `POST /api/v1/settings/api-key/regenerate` 或 `PUT /api/v1/settings/api-key` 时，**则** 服务端生成形如 `ra_` 前缀的高强度随机密钥（或按请求清洗更新/清空并校验非法控制字符），经 `_apply_runtime_mutation` 原子持久化至 `RuntimeConfigStore` 并立即同步 `request.app.state.report_keys` 与 `container.settings` 生效。

#### 用户故事 4（US4）— 跨版本 Diff、紧急切换、运行台账容错与 48 项配置热更新 API（优先级：P2）

- **用户旅程**：作为运维人员或平台管理员，我希望在版本中心对比任意两个已发布版本的全局跨资源差异、在故障时执行毫秒级紧急软链接回退、按多条件检索运行台账与统计大盘（容错历史破损记录），并在线热更新、回滚或环境变量同步全部 `48` 项运行时配置而无需重启进程。
- **优先级理由**：生产可观测性、秒级止血与免重启参数调优是系统稳定运行和低运维成本的核心支撑（P2）。
- **独立测试**：调用 `GET /api/v1/releases/diff`、带非空 `reason` 调用 `POST /api/v1/releases/emergency-switch`、读取人工构造缺失/破损 `templateDef` 的运行记录、更新并回滚 `48` 项 `RuntimeConfig` 后核验 `audit.jsonl` 中的 `operator` 身份即可独立验证。
- **关联需求**：`FR-009`、`FR-010`
- **验收场景**：
  1. **前提** 发布仓库已存在 `r1`、`r2` 等快照，**当** 管理员提交带非空 `reason` 的 `POST /api/v1/releases/emergency-switch` 指定目标版本 `targetRev` 时，**则** 系统直接原子切换 `releases/current` 软链接并保留原版本序号，不生成冗余版本条目；调用 `GET /api/v1/releases/diff?a=r1&b=r2` 返回跨模板、技能、接口与系统提示词的全量 `added`/`modified`/`removed` 资源差异清单。
  2. **前提** 管理员通过 `PUT /api/v1/settings/runtime` 更新大模型、网关或聊天压缩配置（覆盖 `_ORDERED_FIELDS` 共 `48` 项）并可选提交 `clearLlmApiKey` 等显式清空布尔标志，**当** 请求执行完毕后，**则** `RuntimeConfigStore` 以 `0600` 权限持久化新修订版本 `cN`、调用 `c.apply_runtime_config()` 原子更新并发参数与模型实例、网关签名变更时通过 `await c.gateway.aclose_retired()` 异步释放退役连接池，且支持 `POST /api/v1/settings/runtime/rollback` 与 `sync-env` 操作。
  3. **前提** 运行台账中存在 `templateDef` 缺失/结构演进破损或字段值包含 `"0"`/`"False"`/非数字字符串的历史运行 JSON，**当** 调用 `GET /api/v1/runs/{run_id}` 或 `GET /api/v1/system/overview?days=7` 时，**则** `detail_view` 通过 `_fallback_field_def` 与 `safe_int` 安全降级展示且保留 `"0"`/`"False"` 非空假值，所有写接口审计日志中的 `operator` 均强制由 `operator(request)` 从服务端认证会话 `request.state.user.displayName` 提取，完全忽略客户端 Body 伪造字段。

### 2.2 成功标准

- **SC-001**：管理端登录鉴权全链路严格执行 `600,000` 次 PBKDF2-HMAC-SHA256 迭代、单循环 `4` 并发信号量限流、`DUMMY_PASSWORD_HASH` 防枚举校验以及双轨防爆破锁定（账号 `5` 次 / 直连 IP `20` 次触发 `429 LOGIN_LOCKED` 锁定 `300` 秒），`tests/test_api_and_store_fixes.py` 相关用例全部通过。
- **SC-002**：全部模板、技能、接口与系统提示词写接口 100% 强校验 `expected_revision`（并发过期请求返回 `409 DRAFT_CONFLICT`，非法版本类型返回 `400 INVALID_REVISION`）与不可伪造登录态 `operator`，字段重命名正文同步替换不误伤注释与字面量。
- **SC-003**：在线 SSE 流（`/api/v1/reports/stream` 与 `/api/v1/templates/{tid}/dryrun/stream`）稳定每 `15` 秒发送 `: keep-alive` 保活帧，客户端断开后后台任务受 `_BG_TASKS` 保护 100% 完整落盘。
- **SC-004**：紧急版本切换接口（`POST /api/v1/releases/emergency-switch`）以原子软链接切换立即生效且不产生冗余发布号；运行期热配置 API 完整覆盖 `_ORDERED_FIELDS` 全部 `48` 项配置，单次 `PUT /api/v1/settings/runtime` 即可完成配置落盘、热重载与退役网关连接释放。
- **SC-005**：未落盘接口拨测（`test-call`）、内存态渲染预览（`render-preview`）实现 100% 磁盘草稿零副作用；在损坏草稿 YAML、非 Mapping YAML、子路径反代 `/agent` 及破损历史 `templateDef` 运行数据的回归测试中保持零 `500` 未捕获异常。

### 2.3 假设

- 本需求严格运行于 Uvicorn 单进程部署模型（`--workers 1`），`LoginGuard` 内存限流桶、`TokenService` 撤销表、`_BG_TASKS` 任务集合与 `Container.apply_runtime_config()` 均依赖进程内一致性；多副本横向扩展不属于本需求范围。
- 当环境与运行期均未配置 `REPORT_API_KEYS`（密钥集合为空）时，`require_report_key` 按既有约定进入免密放行模式以兼容内网联调，生产部署应通过环境变量或 `/api/v1/settings/api-key*` 接口显式配置密钥。
- 本需求 `33.0` 人天按全周期工程交付口径归档核算（覆盖应用装配、三轨鉴权、全生命周期 REST/SSE 接口、热配置与 API Key 轮换路由、四大集成回归测试集及交接文档编撰）。

---

## 3. 术语与概念定义 【核心，如有新术语】

> 通用平台术语见 `wiki/reference/glossary.md`；下表定义本需求接口与鉴权领域专用概念。

| 术语 | 英文/标识 | 定义 | 备注 |
| --- | --- | --- | --- |
| 三轨安全鉴权 | `require_user` / `require_report_key` / `require_chat_caller` | 按接入方身份隔离的三套 FastAPI 鉴权依赖：工作台会话令牌（Cookie/Bearer）、上游业务 `X-API-Key` 及嵌入式聊天双轨协同鉴权 | `require_chat_caller` 定义在 `routes_chat.py`（归属 `RA-007`），复用 `auth.py` 能力 |
| 草稿乐观锁 | `expected_revision` | 写草稿或提交局部字段变更时客户端提交的基准修订号，由 `parse_expected_revision` 校验并在失配时拒绝覆盖 | 冲突返回 HTTP `409 DRAFT_CONFLICT` 附 `current` |
| 安全覆盖视图 | `_safe_overlay` | 在加载资源列表或引用关系时捕获局部草稿损坏异常（`InvalidResource` / `ValueError`），自动回退至线上快照 `live` 视图的容错机制 | 防止单个破损草稿 YAML 导致全站列表不可用 |
| 运行期热配置快照 | `RuntimeSnapshot` (`c1..cN`) | 由 `RuntimeConfigStore` 管理的带版本号 `48` 项配置持久化快照，修改后通过 `Container.apply_runtime_config` 免重启同步至内存组件 | 磁盘目录权限严格限制为 `0600` |
| 双态运行视图 | `detail_view` / `report_view` | 由 `api/run_views.py` 对同一运行记录分别输出的完整工作台溯源结构与精简上游调用结构 | `detail_view` 对破损历史字段具备降级容错 |

---

## 4. 用户角色 【核心】

| 角色 | 类型 | 本需求中可执行的操作与数据范围 | 权限/安全约束 |
| --- | --- | --- | --- |
| 平台管理员 / 系统维护 | 人工角色 | 登录工作台、管理发布版本、执行 `emergency-switch` 紧急回退、编辑与回滚 `48` 项 `RuntimeConfig`、重置/轮换上游 `X-API-Key` | 必须通过 `require_user` 会话鉴权；受 `LoginGuard` 双轨防爆破约束；审计操作人取自 `user.displayName` |
| 业务配置人员 / 模板开发者 | 人工角色 | 创建/编辑/校验/发布/回退模板、技能、网关接口与系统提示词，执行内存预览、未落盘 `test-call` 拨测、在线试运行与回归用例提取 | 必须通过 `require_user` 鉴权；所有写操作受 `expected_revision` 乐观锁保护 |
| 上游业务工单系统 | 外部系统角色 | 调用 `POST /api/v1/reports` 与 `POST /api/v1/reports/stream` 获取同步或 SSE 流式申告报告结果，探活 `/healthz` 或 `/api/v1/health` | 经 `require_report_key` 使用 `hmac.compare_digest` 校验 `X-API-Key`；强制锁定 `target="online"`，禁止访问草稿态 |
| 嵌入式聊天宿主协同方 | 内部协同模块 | 复用 `auth.py` 会话校验、`require_report_key`、统一异常映射与 `/api/v1/chat/*` 路由挂载点 | 具体聊天会话及路由协议实现归属 `RA-007`（`routes_chat.py`） |

---

## 5. 功能需求 【核心】

### 5.1 应用装配、反代路由与生命周期治理

#### FR-001 FastAPI 应用工厂、反代中间件、日志清理与 SPA 安全托管

- **来源**：`src/report_agent/main.py`、`src/report_agent/container.py`、`src/report_agent/config.py`
- **描述**：系统通过 `create_app` 与 `Container` 统一完成应用生命周期装配、幂等日志初始化、异常格式收敛、子路径反向代理支持、24 小时后台过期数据清理与前端构建产物静态托管。
- **关联用户故事/成功标准**：`US1` / `SC-005`
- **业务规则**：
  1. `lifespan` 启动时装配或加载已注入的 `Container`，优先恢复持久化 `RuntimeConfig` 并以 `c.settings` 为唯一生效配置；无用户且设置 `ADMIN_BOOTSTRAP_PASSWORD` 时自动创建 `admin` 账号；启动 `c.runs.start()` 与 24 小时周期 `_cleanup_loop` 清理过期运行与聊天会话；关闭时取消清理任务、排空 `chat`、停止 `runs` 并关闭 `gateway`。
  2. `setup_logging` 幂等安装控制台与按天轮转文件日志（`TimedRotatingFileHandler(..., backupCount=30)`），避免重复初始化或句柄泄漏。
  3. 配置 `APP_ROOT_PATH`（经 `normalized_root_path()` 标准化）时挂载 `_SubpathPrefixMiddleware`：精确命中前缀（如 `/agent`）且为 HTTP 请求时返回保留查询串的 `307` 重定向至 `/agent/`；以 `/agent/` 开头的请求剥离前缀更新 `scope["path"]` 与 `scope["raw_path"]`。
  4. `install_error_handlers` 将 `HTTPException`、`RequestValidationError`、`ResourceNotFound`、`ReleaseNotFound`、`TemplateUnavailable`、`InvalidResource`、`NothingToPublish`、`DraftConflict`、`PublishError`、`InputValidationError`、`ChatError` 与 `GitError` 统一映射为 JSON 错误载荷（`GitError` 仅记日志不对外泄露堆栈）。
  5. 配置 `FRONTEND_DIST` 且目录存在时挂载 `/assets`，静态兜底路由对 `/api` 或 `/api/*` 返回 JSON `404 NOT_FOUND`，其余路径校验 `target.is_relative_to(dist_dir)` 防目录穿越并返回目标文件或回退 `index.html`。
- **输入/触发**：ASGI 启动/关闭事件、`APP_ROOT_PATH`、`FRONTEND_DIST` 与任意 HTTP/SSE 请求。
- **输出/结果**：标准 FastAPI 应用实例、结构化 JSON 错误响应、`GET /healthz` 与 `GET /api/v1/health` 状态输出及静态页面响应。
- **验收标准**：
  - AC-1：配置 `APP_ROOT_PATH=/agent` 时请求 `/agent` 返回 `307` 重定向至 `/agent/`，请求 `/agent/api/v1/health` 正常返回状态且请求 `/api/nonexistent` 返回 JSON `404 NOT_FOUND` 而非 `index.html`。
  - AC-2：触发 `DraftConflict` 返回 `409 DRAFT_CONFLICT` 附带 `current`，触发 `PublishError` 返回 `422 PUBLISH_BLOCKED` 附带 `issues`，触发 `GitError` 返回脱敏 `500 GIT_ERROR`。

### 5.2 三轨安全鉴权与上游报告服务接口

#### FR-002 防爆破工作台会话鉴权体系

- **来源**：`src/report_agent/api/auth.py`、`src/report_agent/api/routes_system.py`
- **描述**：面向工作台前端提供登录、登出与当前身份自检接口，全链路防护口令撞库、计时枚举、算力放大 DoS 与超长令牌内存攻击。
- **关联用户故事/成功标准**：`US1` / `SC-001`
- **业务规则**：
  1. `UserStore` 使用 PBKDF2-HMAC-SHA256（`_ITERATIONS = 600_000` + 16 字节随机盐）存储 `users.yaml`（权限 `0o600`），按 `(st_mtime_ns, st_size)` 缓存并在线程锁外计算哈希；限制 `MAX_USERNAME_LEN = 128` 与 `MAX_PASSWORD_LEN = 1024`。
  2. `POST /api/v1/auth/login` 通过按事件循环 `WeakKeyDictionary` 隔离的 `_login_semaphore()`（`_LOGIN_MAX_CONCURRENCY = 4`）与 `asyncio.to_thread` 离线校验口令；用户不存在或无有效哈希时使用 `DUMMY_PASSWORD_HASH` 执行等成本校验。
  3. `LoginGuard` 默认单账号连续失败 `max_failures=5` 次锁定 `lock_s=300` 秒、直连来源 IP（仅取 `request.client.host`，不盲信代理头）连续失败 `ip_max_failures=20` 次锁定，超长键经 `_bound_guard_key` 转 SHA-256 摘要，并借助 `_known_users` 集合保护真实账号失败计数/锁定不被海量随机用户名驱逐。
  4. `TokenService` 签发 HMAC-SHA256 令牌并强制 `_MAX_TOKEN_LEN = 4096`；登录同时在响应体返回 `token` 并写入 `HttpOnly`、`SameSite=strict` 的 `ra_session` Cookie；`POST /api/v1/auth/logout` 将 nonce 加入带过期淘汰与 `max_revoked = 8192` 容量上限的撤销表；`require_user` 同时支持 `Authorization: Bearer` 与 Cookie 双载体。
- **输入/触发**：`POST /api/v1/auth/login`、`POST /api/v1/auth/logout`、`GET /api/v1/auth/me` 与所有管理端接口请求头/Cookie。
- **输出/结果**：登录态 JSON `{token, username, displayName, role}` + `ra_session` Cookie，或 `401`/`429` 错误响应。
- **验收标准**：
  - AC-1：同一真实账号或未知账号连续失败 5 次、或同一直连 IP 失败 20 次后返回 HTTP `429 LOGIN_LOCKED`；在桶满场景下喷洒未知账号不会驱逐已锁定的真实账号保护记录。
  - AC-2：调用 `/auth/logout` 后再次携带原 Token 访问受保护端点立即返回 HTTP `401 UNAUTHORIZED`；携带超过 `1024` 字符口令快速拒绝并计数不触发高迭代哈希放大。

#### FR-003 上游业务报表同步与 SSE 流式服务接口

- **来源**：`src/report_agent/api/routes_system.py`、`src/report_agent/api/auth.py`、`src/report_agent/api/common.py`、`src/report_agent/api/run_views.py`
- **描述**：面向外部业务系统提供同步与流式申告报告生成接口，强制锁定线上发布快照与精简契约视图。
- **关联用户故事/成功标准**：`US1` / `SC-003`
- **业务规则**：
  1. `require_report_key` 每次请求优先读取 `container.settings.report_api_key_set()`（为空时回退 `app.state.report_keys`）；密钥非空时强制校验 `X-API-Key` 并通过 `hmac.compare_digest` 逐项比对，缺失或无效返回 HTTP `401 INVALID_API_KEY`。
  2. `_report_request` 校验 `templateId > 0`（否则返回 `400 INVALID_TEMPLATE_ID`），构建 `RunRequest` 时强制锁定 `target="online"`、`entry="上游调用"`、`operator="upstream"` 并透传可选 `batchNo`。
  3. `POST /api/v1/reports` 同步等待 `runner.run` 后经 `report_view` 返回裁剪契约；`POST /api/v1/reports/stream` 通过 `sse_run` 返回流式响应（`SSE_HEADERS` 含 `Cache-Control: no-cache` 与 `X-Accel-Buffering: no`），首帧输出 `: connected`，队列空闲每 `15` 秒输出 `: keep-alive`，后台协程注册至 `_BG_TASKS` 强引用集合确保客户端断开不中止执行与落盘。
- **输入/触发**：携带 `X-API-Key` 与 `ReportBody`（`templateId`、`params`、`document`、`batchNo`）的 `POST /api/v1/reports` 或 `/reports/stream`。
- **输出/结果**：`report_view` 结构化 JSON，或 `event: event` / `event: final` / `event: error` 标准 SSE 帧流。
- **验收标准**：
  - AC-1：热更新新增或替换 `reportApiKeys` 后无需重启进程，旧密钥立即返回 `401 INVALID_API_KEY`，新密钥放行并返回 `target="online"` 结果。
  - AC-2：SSE 流式客户端在接收首个事件后主动断连，后台填报任务仍在 `_BG_TASKS` 保护下完成并写入 `RunStore`。

### 5.3 模板细粒度乐观锁、预览、用例与试运行

#### FR-004 模板全生命周期与细粒度乐观锁编排接口

- **来源**：`src/report_agent/api/routes_templates.py`、`src/report_agent/api/common.py`、`src/report_agent/api/dto.py`
- **描述**：支持模板列表、新建、复制、上下线、跨模板字段汇总、整包草稿保存及单字段/排序/证据批量/技能绑定的细粒度增量编辑，全程强制乐观锁与语义一致性防护。
- **关联用户故事/成功标准**：`US2` / `SC-002`
- **业务规则**：
  1. 全部模板写接口通过 `parse_expected_revision` 严格校验 `revision`（允许 `None` 或非负 `int`，拒绝 `bool` 与负数返回 `400 INVALID_REVISION`）；不匹配当前草稿修订号时抛出 `DraftConflict` 返回 `409 DRAFT_CONFLICT`。
  2. `PUT /api/v1/templates/{tid}/fields/{name}` 校验字段名满足合法标识符（非 `_` 开头、不含保留名 `_RESERVED_FIELD_NAMES` 与 `[{}%\s]`）、禁止将 `type="list"` 设为 `evidence="input"`（返回 `400 INVALID_FIELD_EVIDENCE`）；当 `originalName != new["name"]` 时执行 `_rename_body_variable` 同步重写正文 `{{ ... }}` / `{% ... %}` 变量引用，并安全跳过 `{# ... #}` 注释、字符串字面量、过滤器名及 `.attr` 属性链。
  3. `DELETE /api/v1/templates/{tid}/fields/{name}` 通过 `_resolve_delete_field_revision` 同时兼容查询参数与 JSON Body 中的 `revision`，若正文字段引用计数 `body_usage > 0` 且 `force=false` 则返回 `400 FIELD_IN_USE`。
  4. `POST /api/v1/templates/{tid}/fields/batch-evidence`、`PUT /api/v1/templates/{tid}/fields-order`、`PUT /api/v1/templates/{tid}/skills`、`PUT /api/v1/templates/{tid}/draft` 与 `offline` / `restore` / `publish` / `rollback` 均强制由 `operator(request)` 提取认证身份落审计与 Git 记录。
- **输入/触发**：`/api/v1/templates` 系列 CRUD、草稿、发布与细粒度编辑请求。
- **输出/结果**：最新 `TemplateItem`、`TemplateDetail`、字段 DTO（含 `usage`、`refByFields`）与更新后的 `revision` / `draft` 元数据。
- **验收标准**：
  - AC-1：并发携带同一 `revision` 修改同一模板字段，先到者成功递增修订号，后者收到 `409 DRAFT_CONFLICT` 附最新 `current` 状态；将字段 `a` 改为 `b` 后，正文 `{{a}}` 与 `{% if a %}` 同步变更为 `b`，而 `{# a #}`、`"a"` 与 `x.a` 保持原样。
  - AC-2：向 `list` 字段提交 `evidence="input"` 返回 `400 INVALID_FIELD_EVIDENCE`；删除正文仍在引用的字段且未传 `force=true` 返回 `400 FIELD_IN_USE`。

#### FR-005 内存态沙箱实时预览、版本差异、用例沉淀与在线试运行

- **来源**：`src/report_agent/api/routes_templates.py`、`src/report_agent/api/run_views.py`
- **描述**：提供无副作用的内存态 Jinja2 沙箱渲染预览、带基线漂移提示的发布前校验、跨版本 Diff、回归用例全生命周期管理及支持历史复用与 SSE 实时追踪的试运行接口。
- **关联用户故事/成功标准**：`US2` / `SC-002`、`SC-003`、`SC-005`
- **业务规则**：
  1. `POST /api/v1/templates/{tid}/render-preview` 支持传入未落盘 `bodyText` 与临时 `fields`（经 `_parse_preview_fields` 构造内存态 `Template`），按生产一致逻辑（`field_render` / `TrackedValue` / `render_body`）渲染并识别 `usedFields`、`undefinedFields` 与语法错误行号，不写入磁盘草稿。
  2. `POST /api/v1/templates/{tid}/validate` 支持传入未落盘 `DraftBody` 执行只读校验，经 `validation_result_with_drift` 输出 `errors`、`warnings` 与草稿基线漂移 `drift`（`baseRev != onlineRev`）；`GET /api/v1/templates/{tid}/diff` 比较 `draft` / `online` / `rN` 的字段、入参、技能与正文差异。
  3. `POST /api/v1/templates/{tid}/cases` 支持从既有 `fromRunId` 自动抽取运行入参、`document` 及所有 `status="found"` 字段期望值（列表值自动 JSON 序列化，完整保留 `"0"`/`"False"` 非空假值，跳过空或无状态条目）。
  4. `POST /api/v1/templates/{tid}/dryrun` 与 `/dryrun/stream` 支持选择 `targetVersion="draft"|"online"`，传入 `caseId` 时自动回填关联用例入参/单据并在成功后更新 `lastRunId`，返回完整 `detail_view`。
- **输入/触发**：预览载荷 `PreviewBody`、校验体 `DraftBody`、用例载荷及 `DryRunBody`。
- **输出/结果**：渲染文本及使用字段集、校验与漂移结构、版本 Diff、`RegressionCase` DTO 及同步/SSE `detail_view`。
- **验收标准**：
  - AC-1：传入未落盘 `fields` 与 `bodyText` 调用 `render-preview` 返回准确渲染结果与 `usedFields`，随后读取草稿修订号与文件内容保持零改动。
  - AC-2：调用 `POST /api/v1/templates/{tid}/cases` 传入含数值 `"0"` 与列表字段的 `fromRunId`，新用例正确保存全量 `inputs`、`documentText` 与序列化后的 `expectedValues`。

### 5.4 Skill/API 契约治理、提示词与 48 项热更新运维接口

#### FR-006 纯文本 Skill 全生命周期治理与损坏草稿安全回退

- **来源**：`src/report_agent/api/routes_resources.py`
- **描述**：提供纯文本 Skill 列表（含引用模板与近 7 天加载统计）、新建、多版本读取、带乐观锁草稿保存、校验、发布与版本回滚接口，并隔离单个损坏草稿风险。
- **关联用户故事/成功标准**：`US3` / `SC-002`、`SC-005`
- **业务规则**：
  1. `GET /api/v1/skills`、`GET /api/v1/skills/{sid}` 通过 `_safe_overlay` 与异常处理在当前草稿 `SKILL.md` 损坏时安全回退展示线上版本，避免单点配置语法错误阻塞整个治理工作台。
  2. `POST /api/v1/skills` 通过 `_check_skill_id` 校验 `SKILL_ID_RE`，防止路径穿越与重名冲突（`400 SKILL_EXISTS`）。
  3. `PUT /api/v1/skills/{sid}/draft`、`validate`、`publish`、`discard-draft`、`rollback` 与 `revisions` 均受 `parse_expected_revision`（写草稿）与 `check_rollback_reason`（直接发布上线模式强制填写 `reason`）约束。
- **输入/触发**：`/api/v1/skills` 与 `/api/v1/skills/{sid}/*` 请求。
- **输出/结果**：`skill_item` DTO（含 `refTemplates`、`refsCount`、`loads7d`）、Markdown 正文及发布/校验结果。
- **验收标准**：
  - AC-1：工作区某 Skill 草稿被手工写入非法 frontmatter 后，调用 `GET /api/v1/skills` 仍正常返回 HTTP `200` 并安全回退显示其线上生效版本内容。

#### FR-007 双协议网关接口治理、脱敏预览与未落盘在线拨测

- **来源**：`src/report_agent/api/routes_resources.py`
- **描述**：提供统一网关 XML/JSON 双协议接口契约治理、局部属性补丁保存、脱敏请求报文预览及基于未落盘 `yamlText` 的在线沙箱拨测（`test-call`）。
- **关联用户故事/成功标准**：`US3` / `SC-002`、`SC-005`
- **业务规则**：
  1. `POST /api/v1/apis` 支持创建 `unified-gateway-xml` 或 `unified-gateway-json` 新接口骨架；`PUT /api/v1/apis/{name}/draft` 支持传完整 `yamlText` 或局部 `api` 补丁对象（仅修改 `title`、`description`、`processCode`、`connector`/`format`、`headers`、`idempotent`、`timeoutMs`、`retry`，严格校验正整数与非布尔类型）。
  2. `POST /api/v1/apis/{name}/validate` 支持对传入临时 `yamlText` 或当前工作副本执行静态校验，并生成脱敏后的真实网关请求预览 `requestPreview`（XML 或 JSON）。
  3. `POST /api/v1/apis/{name}/test-call` 经 `_prepare_test_call_api` 在工作线程中执行校验：若传入 `yamlText`，严格要求解析后 `api.name == name`（否则返回 `400 API_NAME_MISMATCH`）及 `validate_api` 零错误（`400 INVALID_API_SCHEMA`）；校验 `api.validate_args(body.params)`（`400 INVALID_PARAMS`）后调用 `await c.gateway.invoke(api, body.params)` 返回原始报文、脱敏请求报文、耗时与抽取记录，写入 `api-test-call` 审计日志，且不写盘覆盖原草稿。
- **输入/触发**：`/api/v1/apis` 系列治理、校验及拨测请求 `TestCallBody`。
- **输出/结果**：`api_item` DTO（含协议标识、动态入参、固定入参）、脱敏 `requestPreview` 与 `test-call` 响应字典。
- **验收标准**：
  - AC-1：传入未保存且修改了入参/抽取列的 `yamlText` 发起 `test-call` 成功返回真实或 Mock 抽取行并记录 `api-test-call` 审计；若 `yamlText` 内 `name` 与 URL `{name}` 不符立即返回 `400 API_NAME_MISMATCH`。

#### FR-008 系统提示词多基准治理与上游 API Key 实时轮换

- **来源**：`src/report_agent/api/routes_resources.py`
- **描述**：支持系统提示词四视角版本查阅及草稿发布/回滚，并提供独立的管理端 `X-API-Key` 读取、清空更新与高强度随机密钥一键重生成接口。
- **关联用户故事/成功标准**：`US3` / `SC-001`、`SC-004`
- **业务规则**：
  1. `GET /api/v1/settings/system-prompt` 支持 `version=working|online|draft|rN` 校验（非法格式返回 `400 INVALID_VERSION`，缺失草稿或版本返回 `404`），同时返回 `working`/`online` 文本与漂移状态。
  2. `PUT /draft`、`POST /publish` 支持可选 `revision` 乐观锁与传入正文一步保存并发布。
  3. `GET /api/v1/settings/api-key`、`PUT /api/v1/settings/api-key` 与 `POST /api/v1/settings/api-key/regenerate` 受 `require_user` 保护：修改或清空 `apiKeys` 时拦截控制字符，重生成接口生成 `ra_<secrets.token_urlsafe(24)>` 新密钥，均通过 `_apply_runtime_mutation` 持久化至 `RuntimeConfigStore` 并立即刷新 `request.app.state.report_keys` 与 `c.settings`。
- **输入/触发**：`/api/v1/settings/system-prompt*` 与 `/api/v1/settings/api-key*` HTTP 请求。
- **输出/结果**：提示词状态与文本字典、`_api_key_payload`（含 `configured`、`apiKeys`、`primaryKey`、`masked`、`count`、`activeRev`）及运行配置状态。
- **验收标准**：
  - AC-1：调用 `POST /api/v1/settings/api-key/regenerate` 后立即使用新返回的 `primaryKey` 访问 `/api/v1/reports` 成功，原密钥同步失效返回 `401 INVALID_API_KEY`。

#### FR-009 发布历史跨版本 Diff、毫秒级紧急切换与容错运行台账

- **来源**：`src/report_agent/api/routes_system.py`、`src/report_agent/api/run_views.py`、`src/report_agent/api/dto.py`
- **描述**：支持全局发布流水检索、任意双版本跨资源 Diff、毫秒级紧急切换线上版本、多维度运行台账检索及历史破损记录安全详情与大盘统计输出。
- **关联用户故事/成功标准**：`US4` / `SC-004`、`SC-005`
- **业务规则**：
  1. `GET /api/v1/releases/diff?a=&b=` 通过 `c.repo.diff_name_status` 对比两个发布快照 commit 差异，归并输出涉及的 `template`、`skill`、`api`、`system-prompt` 变更类型（`added`/`modified`/`removed`）及变动文件列表。
  2. `POST /api/v1/releases/emergency-switch` 强制校验非空 `reason` 与目标版本存在性，调用 `c.publisher.emergency_switch` 原子切换 `releases/current` 软链接，保留既有 `rN` 序号不生成新版本记录。
  3. `GET /api/v1/runs` 校验 `limit >= 1`、`offset >= 0`、`dateFrom <= dateTo` 与正整数 `templateId`，支持 `mobile`、`template`、`status`、`entry`、`batchNo`、`q` 多维组合筛选分页；`GET /api/v1/runs/{run_id}` 校验 `SAFE_ID_RE` 后经 `detail_view` 输出详情。
  4. `detail_view` 对缺失或损坏 `templateDef` 通过 `_fallback_field_def` 容错重建字段定义，对非整数计数字段经 `safe_int` 降级，并正确保留 `"0"`/`"False"` 非空值；`GET /api/v1/system/overview` 聚合 `days`（`1~365`）窗口内模板、技能、接口与运行时关键指标。
- **输入/触发**：`/api/v1/releases*`、`/api/v1/runs*` 与 `/api/v1/system/overview` 查询或切换请求。
- **输出/结果**：版本列表与资源差异清单、`{"activeRev": ...}`、分页 `run_record` 列表、`detail_view` 详情与大盘统计响应。
- **验收标准**：
  - AC-1：执行 `emergency-switch` 切回历史 `r1` 后，`/api/v1/health` 立即返回 `liveRev="r1"` 且 `releases` 总数未增加。
  - AC-2：读取缺失 `templateDef` 或含非法字符串 `durationMs` 的历史运行记录时，`/api/v1/runs/{run_id}` 正常返回 HTTP `200` 且字段值展示完整。

#### FR-010 48 项运行期热更新配置中心接口

- **来源**：`src/report_agent/api/routes_resources.py`、`src/report_agent/store/runtime_config.py`、`src/report_agent/container.py`
- **描述**：提供覆盖大模型、智能体运行、平台工具限额、聊天会话/压缩及统一网关等全部 `48` 项 `_ORDERED_FIELDS` 参数的查询、更新、历史对比、修订回滚与环境变量重同步接口，实现免重启原子生效。
- **关联用户故事/成功标准**：`US4` / `SC-004`
- **业务规则**：
  1. `GET /api/v1/settings/model` 返回当前生效非敏感运行参数（含网关并发与聊天压缩阈值）与 `activeRev`；`GET /api/v1/settings/runtime` 返回经过密钥掩码处理的完整 `48` 项公开状态（`mask_secret` / `mask_api_keys`）。
  2. `PUT /api/v1/settings/runtime` 校验 `clearLlmApiKey`、`clearGatewayAppId`、`clearGatewayAccessToken`、`clearReportApiKeys` 布尔标记，在工作线程调用 `RuntimeConfigStore.update` 验证跨字段约束并以 `0600` 权限落盘版本 `cN`；若有变更则立即调用 `c.apply_runtime_config()` 热重构模型/运行器/网关并同步 `request.app.state.report_keys`，随后异步调用 `await c.gateway.aclose_retired()` 优雅回收旧连接池。
  3. `GET /api/v1/settings/runtime/revisions`、`POST /api/v1/settings/runtime/rollback` 与 `POST /api/v1/settings/runtime/sync-env` 支持查看变更字段日志（不含明文密钥）、按 `cN` 回退生效及重新从启动环境变量同步。
- **输入/触发**：`/api/v1/settings/model` 与 `/api/v1/settings/runtime*` 请求。
- **输出/结果**：掩码后 `RuntimeSnapshot` 公开视图、修订列表与最新生效状态。
- **验收标准**：
  - AC-1：通过 `PUT /api/v1/settings/runtime` 修改网关地址、模型名称与 `chatCompactTriggerMessages` 后，`GET /api/v1/settings/model` 立即反映新值且旧网关客户端异步回收无句柄泄漏；响应中密钥仅显示掩码。

---

## 6. 非功能需求 【补充】

| 类型 | 编号 | 说明 | 验收方式 |
| --- | --- | --- | --- |
| 零业务硬编码与资源隔离（宪章 I） | `NFR-001` | `src/report_agent/api/`、`main.py` 与 `container.py` 禁止硬编码任何特定模板编号、业务规则或专用接口名；`_rename_body_variable` 与 `dto.py` 完全按通用模型与模板正文字面运行 | 代码审查与 `test_api.py` 多模板回归校验 |
| 强证据防幻觉与上下文隔离（宪章 II） | `NFR-002` | 上游 `/reports*` 强制绑定 `target="online"`；`detail_view` 与 `report_view` 如实透传 `found` / `not_found` / `retriedFields` / `validationRounds` 与 `missingShown`，不改写或掩饰证据缺失结论 | `test_api.py` 上游与试运行视图断言 |
| 单进程并发安全与路径防穿越（宪章 III） | `NFR-003` | 依赖 `uvicorn --workers 1` 进程内锁模型；`routes_templates` / `routes_resources` / `routes_system` 对路径参数严格应用 `SAFE_ID_RE`、`SKILL_ID_RE`、`API_NAME_RE`、`CASE_ID_RE` 与 `REV_RE`，`spa()` 强制校验 `target.is_relative_to(dist_dir)`，`runtime/` 与 `users.yaml` 强制 `0600` 权限 | `test_api.py#test_resource_id_validation_traversal_and_not_found_contracts` 与 `test_deep_audit_fixes.py` |
| 安全编码、防 DoS 与隐私脱敏（宪章 VI） | `NFR-004` | 口令 600k PBKDF2 校验受 `_LOGIN_MAX_CONCURRENCY=4` 与 `DUMMY_PASSWORD_HASH` 保护；`LoginGuard` 保护真实用户免被未知用户挤出并限流直连 IP；API Key 走 `hmac.compare_digest`；`validate` 请求预览、`runtime` 接口及 `GitError` 响应均不泄密或内部堆栈 | `test_api_and_store_fixes.py`、`test_runtime_config_hot_reload.py`、`test_deep_audit_fixes.py` |
| 关键路径审计留痕与代码规范（宪章 VII–VIII） | `NFR-005` | 所有写操作（模板/技能/接口编辑发布、拨测 `api-test-call`、配置变更/回滚、紧急切换）均强制取 `operator(request)` 写入 `audit.jsonl`；SSE 断连任务受 `_BG_TASKS` 托管确保日志/运行落盘完整；通过 `uvx ruff@0.11.0` 静态检查 | `test_deep_audit_fixes.py` 与 `uvx ruff@0.11.0 check src tests` |
| 前端多入口分包边界（宪章 技术约束） | `N/A`（接口层不适用） | 本需求不直接产出前端代码或构建分包，仅由 `main.py` 托管 `FRONTEND_DIST` 并隔离 `/api/*` 与 SPA 回退，实际前端分包归属 `RA-006` | `test_deep_audit_fixes.py` SPA 托管用例验证 |

---

## 7. 数据与存储需求 【补充】

> 底层 Git 仓库、发布快照、草稿与运行账本核心存储引擎设计归属 `RA-002`（`specs/002-git-store-hot-reload/`）；本需求重点管理认证凭据文件、`RuntimeConfigStore` 热更新快照及进程内鉴权/并发控制状态。

| 数据对象/存储位置 | 变更类型 | 关键字段与口径 | 一致性/留存策略 | 关联需求 |
| --- | --- | --- | --- | --- |
| `DATA_DIR/config/users.yaml` | 读写（`UserStore`） | `users[]` 含 `username`、`displayName`、`role`、`passwordHash`（`pbkdf2_sha256$600000$...`） | 线程锁 + 原子写盘 + `0600` 权限 + `(st_mtime_ns, st_size)` 读缓存 | `FR-002` |
| `DATA_DIR/config/.token-secret` | 读写（`TokenService`） | 自动生成的 48 字节 URL-safe HMAC 签名密钥 | 原子创建 + `0600` 权限；环境变量 `ADMIN_TOKEN_SECRET` 优先 | `FR-002` |
| `DATA_DIR/config/runtime/current.json`、`index.jsonl`、`revisions/cN.json` | 读写（`RuntimeConfigStore`） | `activeRev`、`operator`、`source`、`time`、`note` 及 `48` 项 `_ORDERED_FIELDS` 全量配置 | `Container.lock` 互斥 + `0600` 权限 + `index.jsonl` 脱敏不含密钥 + `cN.json` 不可变快照支持精确回退 | `FR-008`、`FR-010` |
| `DATA_DIR/audit.jsonl` | 只追加（审计日志） | `time`、`action`（如 `api-test-call` / `emergency-switch` / `runtime-config-*`）、`operator`、`detail` | 仅取已认证 `operator(request)` 或 `"upstream"`，拒绝客户端伪造 | `FR-004`~`FR-010` |
| 进程内存态：`LoginGuard` / `TokenService._revoked` / `_BG_TASKS` / `_LOGIN_SEMS` | 内存读写 | 账号/IP 失败计数与锁定截止时间（上限 4096 条）、已撤销 Token nonce 表（上限 8192 条）、活跃 SSE 后台任务强引用、事件循环信号量 | 单进程内存态（`workers=1`）；定时与惰性过期淘汰；优雅关闭排空连接 | `FR-001`~`FR-003` |

---

## 8. 外部接口与集成 【补充】

| 接口/系统 | 方向 | 交互内容 | 是否新增 | 关联需求 | 备注 |
| --- | --- | --- | --- | --- | --- |
| Vue 3 工作台前端（`RA-006`） | 入站（HTTP / SSE） | 会话认证、全量模板/技能/接口/提示词/版本/运行台账/设置中心 REST API 与 `/dryrun/stream` SSE | 否（既有归档接口） | `FR-001`~`FR-010` | 契约登记于 `docs/frontend-api-handoff.md` |
| 上游业务工单系统 | 入站（HTTP / SSE） | `POST /api/v1/reports`、`POST /api/v1/reports/stream` 与 `/healthz`（`X-API-Key` 鉴权） | 否（既有归档接口） | `FR-001`、`FR-003` | 响应结构固定为 `report_view` |
| 嵌入式聊天子路由（`RA-007`） | 内部协同（路由挂载 + 生命周期） | 在 `create_app` 挂载 `chat_router`、`_cleanup_loop` 清理过期聊天会话、优雅关闭 `c.chat.aclose()`，共享 `require_report_key` 与 `verify_request_user` | 否（既有归档接口） | `FR-001`、`FR-002`、`FR-008` | 具体 `/api/v1/chat/*` 端点归属 `RA-007` |
| 统一网关（通过 `ReloadableGatewayClient`） | 出站（封装转发） | 在 `POST /api/v1/apis/{name}/test-call` 调用 `await c.gateway.invoke(api, params)` 执行实时/Mock 拨测，在配置变更时 `aclose_retired()` | 否（复用 `RA-004` 网关接口） | `FR-007`、`FR-010` | 具体 XML/JSON 报文拼装与连接池归属 `RA-004` |

### 8.1 出站网关与模型接口契约摘要（涉及时填写）

> 本需求不直接新增或修改出站统一网关协议或大模型调用适配器（底层实现分别归属 `RA-004` `gateway/` 与 `RA-003` `runtime/model_factory.py`）；本接口层仅在在线拨测 `POST /api/v1/apis/{name}/test-call` 与运行时热更新时通过 `Container.gateway` / `Container.apply_runtime_config()` 调度既定网关与模型客户端，参数校验与错误映射遵循既有 `ApiContract` 与 `RuntimeConfigValidationError` 契约。

### 8.2 三类独立交付物涉及情况

| 独立文档 | 涉及情况 | 判断依据与范围摘要 | 确认来源/日期及关联需求 |
| --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 对外前后端 REST/SSE 契约已完整沉淀于 `docs/frontend-api-handoff.md` 与 `docs/chat-embed-api.md`，本次 SDD 重构不另建空壳或重复文档 | 归档重构基线确认（2026-11-16）；`FR-001`~`FR-010` |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 本需求仅涉及后端接口与热配置代码，不修改 `src/report_agent/seed/` 33 模板资产与 `tools/java_migration/` 迁移工具 | 归档重构基线确认（2026-11-16）；`FR-001`~`FR-010` |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 本次归档仅梳理存量已交付代码与配置能力（48 项环境变量均已纳入既有 `.env.example` 与 `config.py`），无新增运维发布动作 | 归档重构基线确认（2026-11-16）；`FR-001`、`FR-010` |

---

## 9. 边界与约束 【补充】

### 9.1 范围边界

**本次需求包含（In Scope）：**

- `src/report_agent/main.py`、`container.py`、`config.py` 应用工厂、容器生命周期装配、子路径反代中间件与 SPA 托管边界。
- `src/report_agent/api/auth.py`、`common.py`、`dto.py`、`run_views.py`、`routes_templates.py`、`routes_resources.py`、`routes_system.py` 全量 REST/SSE 接口、三轨鉴权底座与双态运行视图。
- `src/report_agent/store/runtime_config.py` 中 `48` 项 `_ORDERED_FIELDS` 热更新模型、验证、`0600` 版本持久化与回滚同步存储接口，以及 `docs/frontend-api-handoff.md` 契约对齐。
- 面向鉴权、乐观锁、双协议接口拨测、深度审计修复与热更新配置的自动化测试验证集。

**本次需求不包含（Out of Scope）：**

- Jinja2 沙箱、模板/Skill/API 底层领域模型与 `validate_all` 静态校验逻辑（归属 `RA-001` `specs/001-domain-jinja-sandbox/`）。
- Git 发布仓储、草稿存储底层、`RunStore` 异步队列与 `CaseStore` 实现（归属 `RA-002` `specs/002-git-store-hot-reload/`）。
- 单智能体 `AgentRunner` 执行管道、动态输出模型与证据核验引擎（归属 `RA-003` `specs/003-agent-runner-evidence/`）。
- 12 个确定性平台工具与网关 XML/JSON 底层客户端实现（归属 `RA-004` `specs/004-deterministic-tools-gateway/`）。
- Vue 3 工作台 UI（归属 `RA-006`）、嵌入式聊天端点 `/api/v1/chat/*` 与 `ChatService`（归属 `RA-007`）、Java 迁移工具与 Docker 容器构建（归属 `RA-008`）。

### 9.2 技术与业务约束

- **单进程部署硬约束（`workers=1`）**：`LoginGuard`、`TokenService`、`_BG_TASKS`、乐观锁写盘与网关热更新均依赖单进程内存一致性，生产严禁开启多 Worker。
- **操作人防伪造约束**：所有写接口严禁采信客户端请求体提供的 `operator` 字段，一律通过 `operator(request)` 取自登录态 `request.state.user.displayName`。
- **零凭据硬编码约束**：测试、示例代码与契约文档中禁止出现真实线上 `LLM_API_KEY`、管理端明文口令或正式 `ra_` 调用密钥。

---

## 10. 异常场景与边界情况 【核心】

| 编号 | 场景描述 | 触发条件 | 预期处理方式 | 是否阻断主流程 | 优先级 | 关联需求 |
| --- | --- | --- | --- | --- | --- | --- |
| `EX-001` | 子路径反代访问不带尾部斜杠与错误 `/api/*` 路径 | 配置 `APP_ROOT_PATH=/agent` 时请求精确路径 `/agent`，或配置 `FRONTEND_DIST` 时请求不存在的 `/api/foo` | `_SubpathPrefixMiddleware` 对 `/agent` 返回保留查询串的 `307` 重定向至 `/agent/`；`spa()` 对 `/api/*` 返回 JSON `404 NOT_FOUND` 而不回退 `index.html` | 否（自动规范化/精准报错） | 高 | `FR-001` |
| `EX-002` | 未知用户撞库驱逐与超长口令/Token 攻击 | 恶意请求大量随机不存在用户名、超长用户名（>128）/口令（>1024）或超长 Token（>4096） | 超长用户名先 SHA-256 定长摘要再计数，超长口令/Token 直接快速失败不进入 PBKDF2/HMAC 解码；`LoginGuard` 分离 `_known_users` 与淘汰优先序避免驱逐已锁定真实账号 | 否（仅阻断恶意请求） | 高 | `FR-002` |
| `EX-003` | 模板并发乐观锁冲突、字段改名保护与在用误删拦截 | 携带过期/非法 `revision` 提交变更、`list` 字段误设 `evidence="input"`、或删除正文中仍在引用的字段且未设 `force=true` | 非法 `revision` 返 `400 INVALID_REVISION`，过期版本返 `409 DRAFT_CONFLICT` 附 `current`；非法列表证据返 `400 INVALID_FIELD_EVIDENCE`；删除在用字段返 `400 FIELD_IN_USE`；重命名精准跳过注释/字面量/属性链 | 是（阻断错误写盘） | 高 | `FR-004` |
| `EX-004` | 草稿目录 YAML 损坏或上传非 Mapping YAML | 某技能或接口草稿文件语法破坏，或向 `PUT /apis/{name}/draft` 提交列表/标量 YAML | 列表与校验通过 `_safe_overlay` 自动降级展示线上有效快照；非 Mapping YAML 或损坏草稿写盘时返回 HTTP `400` 而不引发 `500` 崩溃 | 否（局部回退/报错隔离） | 高 | `FR-006`、`FR-007` |
| `EX-005` | 未落盘网关拨测 `test-call` 篡改接口名或传非法参数 | 传入 `yamlText` 的 `api.name` 与 URL `{name}` 不符、Schema 校验失败或入参缺失/类型错误 | `_prepare_test_call_api` 依次抛出 `400 API_NAME_MISMATCH`、`400 INVALID_API_SCHEMA`、`400 INVALID_PARAMS`，禁止越权套壳发起网关调用，且对磁盘草稿零副作用 | 是（阻断非法拨测） | 中 | `FR-007` |
| `EX-006` | 历史运行记录 `templateDef` 缺失破损或上游密钥全清空 | 查看老旧演进结构/损坏 `templateDef` 的运行记录，或通过 `PUT /settings/api-key` 清空全部 `reportApiKeys` | `detail_view` 经 `_fallback_field_def` 与 `safe_int` 安全降级保留 `"0"`/`"False"`；清空密钥仅当无控制字符时通过 `clear_report_api_keys=True` 切换受控免密模式并写入审计 | 否（安全降级/审计留痕） | 中 | `FR-003`、`FR-008`、`FR-009` |

---

## 11. 待确认事项 【核心】

> 本需求为已交付归档功能重构，历史需求争议已全部在架构设计与深度审计修复阶段拍板闭环，当前无未关闭阻塞项。

| 编号 | 问题描述 | 影响范围 | 责任方 | 期望确认日期 | 状态 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `Q-001` | 上游报表接口在 `REPORT_API_KEYS` 为空时是否允许降级匿名放行 | `FR-003`、`require_report_key` | 平台架构与安全负责人 | 2026-11-12 | 已确认 | 保留受控免密回退以支撑内网无密开发联调，启动日志明确打印警告，生产通过环境或 `/settings/api-key` 配置多密钥立即热生效 |
| `Q-002` | 登录防爆破客户端 IP 是否采信 `X-Forwarded-For` 请求头 | `FR-002`、`_client_ip` | 安全审计团队 | 2026-11-13 | 已关闭 | 为防止客户端伪造 `X-Forwarded-For` 绕过 IP 限流或恶意封禁他人，`_client_ip` 仅读取直连 `request.client.host` |

---

## 附录：原始需求描述 【补充】

```text
智能申告报告填写与资源治理平台（report-agent）全栈研发工作拆分（子规格 005/008，33.0 人天）：
负责 FastAPI 应用工厂与容器生命周期装配、防爆破会话与多密钥轮换三轨鉴权、模板细粒度编辑乐观锁与在线试运行接口、Skill/API（含在线拨测）与提示词治理接口、跨版本 Diff 与紧急切换及上游报表服务契约。
```

---

## 变更记录（Changelog）

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | Codex | 完成 `005-api-auth-governance` 初始归档拆分规格编制（33.0 人天） |
| 2.0 | 2026-11-16 | AiCoding | 按改造后中文 Spec-Kit 模板与 SDD 取证规范全面升级重构，核对并补齐全量章节、三类独立交付物台账、`FR-001`~`FR-010` 验收标准与代码实测依据 |

---

## 增量更新说明

> 本文档按 `report-agent` 中文 Spec-Kit 模板与 SDD 取证规范生成；后续如有接口契约、鉴权策略或运行期热配置字段增减，须同步更新对应章节与 `变更记录` 并联动刷新 `plan.md` 与 `tasks.md`。
