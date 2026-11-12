# 前端对接说明（后端 `/api/v1`）

<!-- #Created By AiCoding(codex) 给前端智能体的对接文档：后端已实现的接口、与现有 platformApi.ts 的差异、前端必须修改的地方。 -->

后端代码在 `src/report_agent/`，接口实现见 `src/report_agent/api/`。本文所说的“前端”指 `frontend/`。

## 1. 联调方式

1. 启动后端：`uv run report-agent serve`（默认端口 8000，与 `vite.config.ts` 的代理默认值一致）。
2. 启动前端：`VITE_USE_MOCK=false npm run dev`，`/api` 请求由 Vite 代理到后端。
3. 首次启动需要账号：
   - 方式一：设置 `ADMIN_BOOTSTRAP_PASSWORD=xxx`，启动时自动创建 `admin`。
   - 方式二：执行 `uv run report-agent user add --username chenxiaoyun --display-name 陈晓芸 --role 业务维护`。
4. 也可以由后端直接托管前端：先执行 `npm run build`，再设置 `FRONTEND_DIST=frontend/dist`。

### 会话

- `POST /auth/login` 成功后，后端同时返回 `token`，并写入 HttpOnly Cookie `ra_session`（SameSite=Strict）。
- 同源访问时，前端不需要自己保存 token。保留 `Authorization: Bearer` 也可以。
- 前端传的 `operator` 字段会被忽略。操作人一律取登录会话中的显示名。

### 错误格式

所有错误都返回 JSON：`{code, message, ...}`。

| HTTP | code | 含义 |
|---|---|---|
| 400 | `BAD_REQUEST` / `INVALID_RESOURCE` / `INVALID_INPUT` / `INVALID_PARAMS` / `FIELD_IN_USE` / `NO_DRAFT` / `*_EXISTS` | 请求内容不合法 |
| 401 | `UNAUTHORIZED` / `INVALID_CREDENTIALS` / `INVALID_API_KEY` | 未登录、密码错误、API Key 错误 |
| 404 | `NOT_FOUND` / `RELEASE_NOT_FOUND` / `TEMPLATE_UNAVAILABLE` | 资源不存在 |
| 409 | `DRAFT_CONFLICT`（附 `current` 草稿元数据） / `NOTHING_TO_PUBLISH` | 草稿被别人改过 / 与线上一致无需发布 |
| 422 | `PUBLISH_BLOCKED`（附 `issues`） / `VALIDATION_ERROR` | 发布校验不通过 / 请求体结构错误 |
| 429 | `LOGIN_LOCKED` | 连续登录失败 5 次，锁定 5 分钟 |

## 2. 前端必须修改的地方（不改就无法真实联调）

> 更新：下表各项已在 `frontend/` 中改完。前端的 mock 数据（`src/mocks/data.ts`）已删除，`platformApi.ts` 只调用真实后端。本表保留作为改动说明。

| # | 问题 | 位置 | 修改建议 |
|---|---|---|---|
| 1 | 请求失败自动改用 mock，后端报错在界面上看不到 | `platformApi.ts` 的 `requestJson` | `VITE_USE_MOCK=false` 时不再回退 mock。按错误格式提示 `message`；收到 401 跳转登录页 |
| 2 | 登录前就执行 `bootstrap()`，没有路由守卫 | `App.vue`、`router/index.ts` | 先调 `GET /auth/me`。返回 401 时进入登录页；成功后再执行 bootstrap，并用返回值设置当前用户 |
| 3 | 切换模板后不重新拉取，正文固定为 `DEFAULT_BODY_TEXT` | `stores/platform.ts` 的 `openTemplateWorkbench` | 打开工作台时调 `GET /templates/{id}`，一次拿到 `bodyText`、`fields`、`inputs`、`skills`、`draft`；用例列表另调 `GET /templates/{id}/cases` |
| 4 | Skill 正文由前端生成 | `getSkillMarkdown` | 调 `GET /skills/{id}` 取 `markdown` |
| 5 | 接口 YAML 是全局唯一的 mock 字符串 | `apiYamlText` | 调 `GET /apis/{name}` 取 `yamlText`。现在的 `DEFAULT_API_YAML` 缺少 `response` 段，提交后会被后端以 400 拒绝 |
| 6 | 系统提示词从不读取，回退版本写死为 r32/r43 | `SettingsView.vue` | 调 `GET /settings/system-prompt`；历史列表用 `GET /settings/system-prompt/revisions`；回退传真实的 `targetRev` |
| 7 | 模板的 `skills` 按中文名匹配 | `TemplateWorkbenchView.vue` 的 `currentTemplateSkills` | 后端 `skills` 返回 Skill **标识**，另返回 `skillNames`（中文名）。前端改为按 `s.id` 匹配。`PUT /templates/{id}/skills` 和 `PUT /draft` 的 `skills` 传标识或中文名都可以 |
| 8 | 字段改名时旧字段不会删除 | `GlobalDrawers.vue` | `PUT /templates/{id}/fields/{新名}` 的请求体带 `originalName: 旧名`。后端同时把正文中的 `{{旧名}}` 替换为新名，前端不必再本地替换 |
| 9 | 拖拽排序没有接口 | 字段页签 | 调 `PUT /templates/{id}/fields-order`，传 `{names: [...]}`；也可以整包保存草稿 |
| 10 | 发布弹窗中的校验结果、漂移提示、回归摘要都是写死的 | `GlobalModals.vue` | 打开弹窗时调 `POST /templates/{id}/validate`，用返回的 `errors`、`warnings`、`drift` 渲染。有 `errors` 时禁用“确认发布”。回归摘要第二阶段再做，先隐藏 |
| 11 | 试运行只读取耗时、轮数、接口次数，报告和时间线写死 | 试运行页签、`AgentTimeline.vue`、`EvidenceSourceInspector.vue` | 直接使用响应中的 `fields`、`report`、`events`、`apiResults`、`documentLines`、`inputs`、`toolCalls`，见第 4.3 节。建议改用 SSE 接口实时显示轨迹 |
| 12 | 历史页签的修订列表和版本对比写死 | `TemplateWorkbenchView.vue` | `GET /templates/{id}/revisions`；对比用 `GET /templates/{id}/diff?a=draft&b=online`（a、b 取 `draft`、`online` 或 `rN`） |
| 13 | 运行详情全部写死，并复用了工作台的字段 | `RunsView.vue` | 调 `GET /runs/{runId}`，结构与试运行响应一致。列表筛选可以交给后端：`GET /runs?mobile=&templateId=&status=&dateFrom=&dateTo=` |
| 14 | 版本整体差异写死 | `ReleasesView.vue` 的 `KNOWN_REV_CHANGES` | `GET /releases/diff?a=r1&b=r2`；每个版本的变更清单在 `GET /releases` 的 `changes` 中 |
| 15 | “保存用例”只传名称，“转为用例”写到当前模板 | `createRegressionCase`、`RunsView.vue` | 从试运行或运行记录保存时，传 `{name, fromRunId}`，后端自动带入入参、单据和找到的字段值。路径中的模板 id 用运行记录的 `templateId` |
| 16 | 上传 PDF 提取文字 | 试运行页签 | **已确定不做**：单据文本由外部传入。删除“上传 PDF”按钮，只保留文本框 |
| 17 | 模型信息卡片写死 | `SettingsView.vue` | `GET /settings/model` |
| 18 | 保存冲突弹窗写死 | `GlobalModals.vue` 的 conflict | 保存草稿时带上 `revision`（取自 `detail.draft.revision`）。收到 409 `DRAFT_CONFLICT` 时，用 `current.updatedBy` 和 `current.updatedAt` 显示提示 |

## 3. 接口清单

“现有”表示 `platformApi.ts` 里已经调用的接口，“新增”表示后端新增、前端需要接入的接口。

### 3.1 认证

| 方法 | 路径 | 请求 | 响应 | 备注 |
|---|---|---|---|---|
| POST | `/auth/login` | `{username, password}` | `{token, username, displayName, role}` | 现有 |
| POST | `/auth/logout` | – | `{ok:true}` | 现有 |
| GET | `/auth/me` | – | `{username, displayName, role}` | 新增 |

### 3.2 模板

| 方法 | 路径 | 请求 | 响应 | 备注 |
|---|---|---|---|---|
| GET | `/templates` | – | `TemplateItem[]` | 现有。多了 `description`、`skillNames`、`draftRevision` |
| POST | `/templates` | `{id, name, description?, skills?}` | `TemplateItem` | 现有，生成草稿 |
| POST | `/templates/{id}/copy` | `{newId, newName, copyCases?=true}` | `TemplateItem` | 现有，`sourceId` 取自路径 |
| POST | `/templates/{id}/offline` | `{reason?}` | `{id, status, rev}` | 现有。下线会生成新版本 |
| POST | `/templates/{id}/restore` | – | `{id, status:'DRAFT'}` | 现有。恢复为草稿，发布后重新上线 |
| GET | `/templates/{id}?version=working\|draft\|online\|rN` | – | `TemplateDetail` | **新增** |
| GET | `/templates/{id}/fields` | – | `TemplateField[]` | 现有 |
| GET | `/templates/cross-fields?exclude={id}` | – | `TemplateField[]`（带 `fromTemplate`） | 现有，建议带 `exclude` |
| GET | `/templates/{id}/inputs` | – | `TemplateInput[]` | 现有。多了 `pattern` |
| PUT | `/templates/{id}/draft` | `{bodyText?, fields?, inputs?, skills?, name?, description?, revision?}` | `{savedAt, draft, issues}` | 现有。`issues` 是保存后的校验结果 |
| POST | `/templates/{id}/discard-draft` | – | `{bodyText, rev, detail}` | 现有 |
| POST | `/templates/{id}/validate` | 可选，结构同 draft（只校验不保存） | `{errors, warnings, drift, casesCount}` | **新增** |
| POST | `/templates/{id}/publish` | `{note}` | `{rev, publishedAt, summary, warnings, item}` | 现有 |
| POST | `/templates/{id}/rollback` | `{targetRev, mode:'draft_only'\|'publish_now', reason}` | `{mode, rev, targetRev, item, detail}` | 现有。`publish_now` 时 `reason` 必填 |
| GET | `/templates/{id}/revisions` | – | `[{rev, type, operator, time, note, summary, online}]` | **新增** |
| GET | `/templates/{id}/diff?a=&b=` | – | `{fields:[{change, name, a, b, props}], inputs, bodyA, bodyB, bodyIdentical, skillsA, skillsB}` | **新增**，正文逐行 diff 由前端计算 |
| POST | `/templates/{id}/render-preview` | `{bodyText?, values:{字段名:值}}` | `{text, usedFields, undefinedFields, error, line?}` | **新增**，替代前端的伪渲染 |
| PUT | `/templates/{id}/fields/{name}` | `TemplateField`，可带 `originalName`、`revision` | `TemplateField` | 现有 |
| DELETE | `/templates/{id}/fields/{name}?force=false` | – | `{deletedName}` | 现有。正文仍在引用时返回 400 `FIELD_IN_USE` |
| POST | `/templates/{id}/fields/batch-evidence` | `{fieldNames, evidenceType}` | `{updatedCount}` | 现有 |
| PUT | `/templates/{id}/fields-order` | `{names}` | `{names}` | **新增** |
| PUT | `/templates/{id}/skills` | `{skills}` | `{skills}`（标识） | 现有 |
| GET/POST | `/templates/{id}/cases` | POST：`RegressionCase` 部分字段，或 `{name, fromRunId}` | `RegressionCase` | 现有。多了 `inputs`、`documentText`、`expectedValues`、`lastRunId` |
| PUT/DELETE | `/templates/{id}/cases/{caseId}` | `RegressionCase` | `RegressionCase` / `{deletedId}` | 现有 |
| POST | `/templates/{id}/dryrun` | `{targetVersion:'draft'\|'online', inputs, documentText, caseId?}` | `RunDetail` | 现有，响应扩充见 4.3。传 `caseId` 时自动带入用例的入参和单据 |
| POST | `/templates/{id}/dryrun/stream` | 同上 | SSE | **新增**，见第 5 节 |

### 3.3 Skill、接口、系统提示词

| 方法 | 路径 | 请求 | 响应 | 备注 |
|---|---|---|---|---|
| GET | `/skills` | – | `SkillItem[]` | 现有 |
| POST | `/skills` | `{id, name, description, apis}` | `SkillItem` | 现有。`id` 只能用小写字母、数字和短横线 |
| GET | `/skills/{id}?version=` | – | `{item, markdown, draft}` | **新增** |
| PUT | `/skills/{id}/draft` | `{markdown, revision?}` | `{savedAt, draft, issues}` | 现有。frontmatter 的 `name` 必须等于 id |
| POST | `/skills/{id}/discard-draft`、`/validate`、`/publish`（`{note}`）、`/rollback` | | | `publish` 为现有，其余新增 |
| GET | `/skills/{id}/revisions` | – | 同模板 | **新增** |
| GET | `/apis` | – | `ApiItem[]`（带 `params`、`fixedParams`、`processCode`） | 现有。参数表不再需要写死 |
| POST | `/apis` | `{name, title, description, processCode?}` | `ApiItem` | 现有，自动生成骨架 YAML |
| GET | `/apis/{name}?version=` | – | `{item, yamlText, draft}` | **新增** |
| PUT | `/apis/{name}/draft` | `{yamlText}`；或 `{api:{title, description, timeoutMs, retry}}`（只改这几项） | `{savedAt, draft}` | 现有。YAML 不合法返回 400 |
| POST | `/apis/{name}/publish`、`/discard-draft`、`/rollback`；GET `/revisions` | | | `publish` 为现有，其余新增 |
| POST | `/apis/{name}/test-call` | `{params, yamlText?}` | `{ok, error, costMs, httpStatus, noData, rawXml, requestXml, records:[{row,...}], columns}` | 现有。`requestJson` 不再需要，`requestXml` 是脱敏后的实际报文 |
| GET | `/settings/system-prompt` | – | `{sysPromptText, sysPromptStatus, onlineText, onlineRev, baseRev, draft}` | 现有 |
| PUT | `/settings/system-prompt/draft` | `{sysPromptText, revision?}` | `{status, ...}` | 现有 |
| POST | `/settings/system-prompt/publish` | `{sysPromptText?, note?}` | `{status, rev}` | 现有 |
| POST | `/settings/system-prompt/rollback` | `{targetRev, mode?='draft_only'}` | `{sysPromptText, status, ...}` | 现有 |
| POST | `/settings/system-prompt/discard-draft`；GET `/settings/system-prompt/revisions` | | | **新增** |
| GET | `/settings/model` | – | `{model, baseUrl, temperature, timeoutS, outputMode, outputRetries, requestLimit, toolCallsLimit, gatewayMode, ...}` | **新增** |

### 3.4 发布版本与运行记录

| 方法 | 路径 | 请求 | 响应 | 备注 |
|---|---|---|---|---|
| GET | `/releases?limit=100` | – | `[{rev, type, time, operator, summary, note, isLive, base, changes:[{kind, key, action, title}]}]` | 现有，最新在前 |
| GET | `/releases/{rev}` | – | 同上单条 | **新增** |
| GET | `/releases/diff?a=&b=` | – | `{changes:[{kind, key, label, change:'added'\|'modified'\|'removed', files}]}` | **新增** |
| POST | `/releases/emergency-switch` | `{targetRev, reason}` | `{activeRev}` | 现有。不生成新版本，之后的发布以切换后的版本为基准 |
| GET | `/runs?dateFrom=&dateTo=&mobile=&templateId=&template=&status=&entry=&batchNo=&q=&limit=` | – | `RunRecord[]` | 现有。默认最近 7 天；多了 `templateId`、`durationMs`、`error`、`retries` |
| GET | `/runs/{runId}?withMessages=false` | – | `RunDetail` | **新增** |

### 3.5 上游调用（API Key：请求头 `X-API-Key`）

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| POST | `/reports` | `{templateId, params:{入参名:值}, document, batchNo?}` | `{runId, status, templateId, rev, report, error, fields:[{name, visible, shown, status, value, source, reason}], missingShown, durationMs}` |
| POST | `/reports/stream` | 同上 | SSE，`final` 为上面的结构 |

### 3.6 暂不提供（第二阶段）

- `GET /regression/diffs`、`POST /regression/execute`：批量回归需要做成异步任务（每条用例要跑一次完整智能体），下一步实现。在此之前前端可以先隐藏入口。
- `POST /documents/extract-pdf`：已确定不做，单据文本由外部传入。

## 4. 数据结构

### 4.1 TemplateField（与 `types/platform.ts` 兼容，新增若干属性）

```ts
interface TemplateField {
  name: string; visible: boolean; type: '文本'|'枚举'|'日期'|'列表'; enumValues: string[]
  columns?: { name: string; type: '文本'|'枚举'; enumValues: string[]; description: string }[]  // 新增：列表字段的列定义
  evidenceType: 'quote'|'input'|'derive'; whenMissing: '保留占位'|'置空'|'默认值'; defaultValue: string
  description: string
  format?: string | null          // 新增：日期展示格式，如 yyyy年M月d号
  quoteWhole?: boolean            // 新增：原文引用必须整条一致（短信正文类字段勾选）
  bodyUsageCount: number          // 后端计算
  refByFields: string[]           // 说明中提到本字段的其它字段
  fromTemplate?: string           // 仅跨模板字段
  // 以下只在试运行 / 运行详情中有值
  runStatus: 'found'|'not_found'; runValue: string; evidenceLabel: string; reasoning: string
  runRows?: Record<string, string>[] // 新增：列表字段的运行结果行（runValue 为其 JSON 文本）
  evidenceTarget: { tab: 'api'|'doc'|'input'; resultId?: string; row?: number; column?: string; line?: number; key?: string }
  retried?: boolean               // 证据校验退回过、模型重填过
  validationFailed?: boolean      // 重试用完仍不通过，被按“找不到”处理
  shown?: boolean                 // 是否出现在最终报告中（条件分支没走到的为 false）
  evidence?: Evidence[]           // 模型提交的原始证据
}
type Evidence =
  | { type: 'api'; resultId: string; row: number; column: string }
  | { type: 'document'; quote: string }
  | { type: 'input'; key: string }
  | { type: 'tool'; callId: string }
  | { type: 'field'; name: string }
```

保存时，前端可以把 `run*`、`bodyUsageCount` 等属性原样传回，后端会忽略。

### 4.2 TemplateDetail（`GET /templates/{id}`）

```ts
interface TemplateDetail {
  item: TemplateItem; version: string; id: number; name: string; description: string
  bodyText: string; fields: TemplateField[]; inputs: TemplateInput[]; skills: string[]; offline: boolean
  draft: null | { baseRev: string|null; revision: number; updatedAt: string; updatedBy: string; createdAt: string; createdBy: string; action: string }
}
```

### 4.3 RunDetail（试运行响应、运行详情）

```ts
interface RunDetail {
  runId: string; status: 'SUCCESS'|'PARTIAL'|'FAILED'; error: string|null; rev: string   // 'r3' 或 'r3+草稿'
  target: 'draft'|'online'; entry: '上游调用'|'试运行'|'回归'; operator: string
  record: RunRecord
  durationSec: number; rounds: number; apiCallCount: number; foundCount: number; totalCount: number
  missingShown: string[]          // 报告中显示了、但没找到的字段（PARTIAL 的原因）
  retriedFields: string[]         // 被证据校验退回过的字段（“重填”筛选用）
  report: string                  // 渲染后的报告文本
  fields: TemplateField[]
  inputs: Record<string,string>; documentText: string; documentLines: {line:number; text:string}[]
  apiResults: { resultId: string; api: string; title: string; args: object; ok: boolean; error: string|null
                columns: Record<string,string>; records: ({row:number} & Record<string,string>)[]
                costMs: number; noData: boolean; requestPreview: string; raw: string }[]
  smsRecords: SmsRecord[]         // 兼容旧组件：apiResults[0] 的记录
  toolCalls: { callId: string; tool: string; args: object; output: any; atMs: number; ok: boolean }[]
  events: ProcessEvent[]          // 智能体轨迹，见第 5 节
  usage: { requests: number; toolCalls: number; inputTokens: number; outputTokens: number }
  skillsLoaded: string[]; validationRounds: { field: string; message: string }[][]; model: string
}
```

页面映射：

- **证据定位面板**：`evidenceTarget.tab='api'` 时，在 `apiResults` 中按 `resultId` 找到结果，再高亮 `row` 行；`'doc'` 时高亮 `documentLines[line-1]`；`'input'` 时高亮 `inputs[key]`。
- **“入参与工具”页签**：列出 `inputs` 和 `toolCalls`。
- **报告预览**：用 `report`。如需点击字段值定位证据，用 `fields[].runValue` 在报告中匹配。

## 5. 过程事件与 SSE

试运行、上游调用都有 `/stream` 版本。返回 `text/event-stream`，事件格式：

```
event: event
data: {"seq":3,"type":"tool","atMs":812,"round":1,"tool":"load_skill","callId":"t1","args":{...},"ok":true,"result":{...}}

event: final
data: {RunDetail 或 上游 report 结构}

event: error          // 入参不合法、模板不存在等启动前错误
data: {"code":"INVALID_INPUT","message":"...","errors":[...]}
```

`: keep-alive` 注释行每 15 秒发一次，前端忽略即可。客户端断开不会取消运行。

`ProcessEvent.type` 的取值（时间线组件按 `round` 分组展示）：

| type | 附加字段 | 含义 |
|---|---|---|
| `run_started` | `runId, templateId, templateName, rev, skills, apis` | 开始运行 |
| `model_request` | – | 第 `round` 轮请求模型 |
| `model_text` | `text` | 模型输出的说明文字 |
| `tool` | `tool, callId, args, ok, result` | 一次平台工具调用。`tool` 取值：`load_skill`、`call_api`、`query_result`、`normalize_text`、`text_contains`、`date_range`、`format_date`。`call_api` 的 `result` 带 `resultId`、`count`、`costMs` |
| `report_rejected` | `attempt, issues:[{field, message}]` | 交卷被证据校验退回（时间线中的红色步骤） |
| `report_accepted` | `attempt` | 交卷通过 |
| `report_degraded` | `attempt, issues, fields` | 重试用完，`fields` 按“找不到”处理 |
| `run_failed` | `error` | 运行失败（模型不可用、超时、超过轮数上限等） |

## 6. 状态与版本号的含义

- `status`：
  - 线上有、没有草稿：`PUBLISHED`。
  - 线上有、有草稿：`PUBLISHED_DRAFT`。
  - 只有草稿：`DRAFT`。
  - 下线且没有草稿：`OFFLINE`。
  - 下线后恢复：变成 `DRAFT`，发布后重新上线。
- 版本号 `rN` 是全局递增的发布版本，每次发布、回退上线、下线都会生成一个。
- 资源的 `onlineRev` 是当前线上内容中**最后一次修改该资源**的版本，不是全局线上版本。例如线上是 r9，而模板 1001 最后一次修改在 r5，那么 1001 的 `onlineRev` 是 `r5`。
- `baseRev` 是草稿所基于的版本。`baseRev ≠ onlineRev` 说明草稿期间别人发布过该资源，此时显示漂移提示，提示别人发布过修改。
- 全局线上版本：取 `GET /releases` 中 `isLive=true` 的那一条，或 `GET /healthz` 的 `liveRev`。
