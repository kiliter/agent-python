# 智能申告报告填写平台（Python 后端）

<!-- #Created By AiCoding(codex) -->

这是一个基于 [Pydantic AI 2.x](https://pydantic.dev/docs/ai/) 的智能体服务，作用是按模板自动填写申告报告。整体方案如下：

- **全智能体**：一次请求只启动一个智能体。由大模型自己决定加载哪些 Skill、调用哪些接口、什么时候交卷。系统里没有 Groovy 脚本，也没有写死的业务策略。
- **证据校验**：每个字段值都必须附带证据，平台逐条核对。校验不通过就退回给模型重填，最多 3 次；仍不通过的字段按“找不到”处理。
- **全文件管理**：资源和运行记录都以文件形式放在一块 PVC 上，用 Git 管理版本，运行记录写 JSONL，不依赖数据库。
- **以模板为主体**：字段的取值要求、证据类型、找不到时的处理都定义在模板里。Skill 是纯文本的方法说明；接口只是声明式契约，不含业务逻辑。

前端在 `frontend/`，接口对接说明见 [docs/frontend-api-handoff.md](docs/frontend-api-handoff.md)。

## 快速开始

```bash
uv sync                                    # 安装依赖（Python 3.13）
cp .env.example .env                       # 按需修改模型地址、网关地址
ADMIN_BOOTSTRAP_PASSWORD=change-me uv run report-agent serve    # http://127.0.0.1:8000
uv run pytest                              # 运行测试（不调用真实模型）
```

- 第一次启动时，如果数据目录（`DATA_DIR`，默认 `./data`）为空，会用内置资源生成第一个版本 `r1`。内置资源从 Java 版（`/Users/zhangjialin/IdeaProjects/agent`）全量迁移而来：33 个模板（ID 100–132，与 Java 资源库一致）、11 个 Skill、3 个接口契约（`querySMSSendInfo`、`BOSS_QryBalanceFlowLog`、`cc_pretty_num_info_query`）、系统提示词和 mock 网关响应。迁移工具与一致性校验见 [tools/java_migration/README.md](tools/java_migration/README.md)。测试专用的示例模板 1001 在 `tests/fixtures/seed/`。
- 默认 `GATEWAY_MODE=mock`，接口调用读取 `data/mock-gateway/<接口名>.xml`。对接真实统一网关时，改为 `live` 并配置 `GATEWAY_URL`、`GATEWAY_APP_ID`、`GATEWAY_ACCESS_TOKEN`。
- 接口文档：`http://127.0.0.1:8000/docs`。

## 一次填写是怎么跑的

```
POST /api/v1/reports {templateId, params, document}
 └─ 捕获线上快照（releases/current → rN，整个运行期间不变）
 └─ 按模板入参定义校验 params
 └─ 生成本模板专属的交卷结构 submit_report（每个字段一个键，枚举限定可选值，证据限定来源类型）
 └─ Pydantic AI 智能体循环
      load_skill → date_range / text_contains → call_api（结果存工作区，只返回摘要）
      → query_result（按条件取完整记录）→ format_date → submit_report
      └─ output_validator：证据校验，不通过抛 ModelRetry 退回重填
 └─ Jinja2 渲染正文（记录实际展示了哪些字段）
 └─ 状态：报告中显示的字段都找到了为 SUCCESS，有缺失为 PARTIAL，运行出错为 FAILED
 └─ 写运行记录 runs/YYYY/MM/DD/index.jsonl + <runId>.json
```

模型可用的平台工具（`runtime/tools.py`）：

| 工具 | 作用 |
|---|---|
| `load_skill` | 读取 Skill 正文。只能加载模板 `skills` 列表中的 Skill：工具 Schema 的枚举只列这些，强行加载其它 Skill 会被退回 |
| `call_api` | 调用接口。只能调用模板中 Skill 声明的接口。参数按契约的 JSON Schema 校验，不合法会被退回 |
| `query_result` | 按条件筛选接口结果，支持 `equals`、`contains`、`notContains`、`normalizedContains`、`normalizedNotContains`，并可用 `before` 只比较某个子串之前的部分 |
| `normalize_text` / `text_contains` | 文本清洗（与 Java `StringCharCleaner` 规则一致），以及包含判断 |
| `date_range` / `format_date` | 计算某天或某月的起止时间、做日期格式转换。返回的 `callId` 可以作为推导证据引用 |

证据规则（`runtime/evidence.py`）：

| 证据类型 | 平台怎么核对 |
|---|---|
| `quote` | 引用的接口记录（`resultId`、`row`、`column`）或单据片段必须真实存在，值必须逐字出现在原文中。字段设置了 `quoteWhole` 时，值必须与原文完全一致 |
| `input` | 值必须等于引用的入参 |
| `derive` | 引用的来源都必须存在。引用了 `format_date` 时，值必须等于工具输出 |

<!-- #Created By AiCoding(codex) 列表字段与 Pebble 对齐说明 -->
列表字段（`type: list`）：值是行对象数组，正文用 `{% for item in 字段 %}…{{item.列名}}…{% endfor %}` 逐行输出。

```yaml
- name: 充值流水
  type: list
  evidence: quote          # 只能是 quote 或 derive
  whenMissing: empty       # 必须为 empty：找不到时按空列表渲染，循环不输出任何内容
  description: 客户的充值记录
  columns:                 # 至少一列；列名规则同字段名
    - name: 充值时间
      description: 充值时间
    - name: 提醒类型
      type: enum           # 列类型只能是 string（默认）或 enum
      values: [语音超额提醒, 流量超额提醒]
```

- 交卷时 `value` 为 `[{"充值时间": "...", "提醒类型": "..."}]`，每行必须且只能包含声明的列，枚举列只能填可选值。
- `quote` 列表字段：每个非空的文本列单元格都必须逐字出现在某条被引用的接口记录（整条记录任一列）或单据片段中；枚举列是归类结论，不做逐字核对。
- 发布校验会检查：循环变量的 `item.列名` 必须是已声明的列；`for` 只能遍历列表字段。

正文渲染与 Pebble 3.2.2 默认行为对齐：每个标签（`{% %}`、`{# #}`、`{{ }}`）后紧跟的一个换行会被去掉（不去掉标签前的缩进）；
另提供 `hasDigit` 测试（`{% if 标准资费 is hasDigit %}`），值中含有任意数字字符时为真，缺失字段为假。
渲染上下文统一由 `runtime/render.py` 的 `build_render_context` 生成。

## 文件存储（PVC）

```
/data
├── repo/                    Git 仓库（只存已发布内容），可推送到远端备份
├── drafts/<kind>/<key>/     草稿 + .meta.json（含乐观锁版本号）
├── releases/
│   ├── index.jsonl          版本元数据：base、commit、操作人、变更清单
│   ├── r1/ r2/ ...          不可变快照；超过 RELEASES_KEEP 的会被清理，需要时从 Git 重建
│   └── current -> rN        线上版本（原子切换软链接）
├── runs/YYYY/MM/DD/         运行记录
├── cases/<templateId>/      回归用例（不参与版本）
├── mock-gateway/            mock 网关样例响应
├── config/                  users.yaml、.token-secret（权限 600）
└── audit.jsonl              发布、回退、紧急切换、接口试调用日志
```

- **发布**：以当前线上版本为基准复制出构建目录，应用草稿，然后校验。校验只拦截本次变更新引入的错误。通过后提交 Git，rename 为 `rN`，再原子切换 `current`。任何一步失败，线上都不受影响。
- **单个资源回退**：可以把历史版本恢复到草稿，也可以直接发布为新版本。无论哪种方式，都只影响这一个资源。
- **紧急切换**：把 `current` 改指向历史版本，不生成新版本。之后的发布以切换后的版本为基准，不会把被撤掉的修改带回来。
- **并发**：必须**单进程**运行（`workers=1`、replicas=1、Recreate 策略）。写入由进程内写锁保护；运行记录由单个后台协程写入；所有文件都是先写临时文件再 rename。启动时清理未完成的构建目录，并确保线上版本存在。

### PVC 要求

- 块存储或 NFSv4（服务端 `sync` 导出），不要用 s3fs、ossfs 这类对象存储挂载。
- 访问模式 RWO 即可；回收策略 `Retain`；容量约 50 GB（以运行记录为主，默认保留 90 天）。
- 容器以非 root 用户运行，通过 `fsGroup` 获得写权限。
- 备份：定期把 `repo/` 推送到远端 Git，或打包归档 `/data`。

## 主要配置（环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATA_DIR` | `./data` | PVC 挂载目录 |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | OpenAI / `dummy` / `deepseek-v4-flash` | OpenAI 兼容接口 |
| `LLM_TEMPERATURE` / `LLM_TIMEOUT_S` / `LLM_HTTP_RETRIES` | 0 / 120 / 2 | |
| `LLM_STRICT_TOOLS` / `LLM_TOOL_CHOICE_REQUIRED` / `LLM_PARALLEL_TOOL_CALLS` | 不设置 | 内网推理服务不支持相应能力时设为 `false` |
| `AGENT_OUTPUT_MODE` | `tool` | 交卷方式：`tool`（调用 submit_report 工具）；`json_object`（Schema 写进提示词，`response_format=json_object`，DeepSeek 官方 API 用这个）；`native`（`response_format=json_schema`）；`prompted`（只靠提示词约束） |
| `AGENT_NATIVE_STRICT` | `true` | native 模式下以 strict json_schema 发送：所有键必填，oneOf 转为 anyOf |
| `AGENT_OUTPUT_RETRIES` / `AGENT_TOOL_RETRIES` | 3 / 2 | 证据校验重填次数 / 工具参数重试次数 |
| `AGENT_REQUEST_LIMIT` / `AGENT_TOOL_CALLS_LIMIT` / `AGENT_RUN_TIMEOUT_S` | 25 / 40 / 600 | 单次运行的上限 |
| `AGENT_MAX_CONCURRENT_RUNS` | 8 | 进程内同时运行的智能体数 |
| `GATEWAY_MODE` | `mock` | `live` 调用真实网关 |
| `GATEWAY_URL` / `GATEWAY_APP_ID` / `GATEWAY_ACCESS_TOKEN` | 空 | 请求地址为 `{GATEWAY_URL}/openapi_3` |
| `GATEWAY_XML_STYLE` | `java` | `java`：与现有 Java 报文逐字一致（字母序、`xsi:nil`）；`clean`：声明顺序、空标签 |
| `REPORT_API_KEYS` | 空 | 上游调用 `/api/v1/reports` 的 API Key，多个用逗号分隔；为空时不校验 |
| `ADMIN_TOKEN_SECRET` / `ADMIN_TOKEN_TTL_S` / `ADMIN_COOKIE_SECURE` | 自动生成 / 43200 / false | 管理端会话 |
| `ADMIN_BOOTSTRAP_PASSWORD` | 空 | 首次启动且没有任何用户时，用它创建 `admin` |
| `FRONTEND_DIST` | 空 | 配置后由本服务托管前端构建产物 |
| `RUNS_KEEP_DAYS` / `RELEASES_KEEP` | 90 / 50 | |

用户管理：`uv run report-agent user add --username xxx --display-name 张三 --role 业务维护`（交互输入密码）。

## 代码结构

```
src/report_agent/
├── config.py            配置
├── container.py         组件组装、种子初始化
├── main.py / cli.py     FastAPI 应用 / 命令行
├── domain/              模板、Skill、接口契约、Jinja2 正文、资源加载与校验
├── store/               PVC 文件存储：草稿、发布、版本、Git、用例、运行记录
├── gateway/             统一网关 XML 连接器、mock 网关
├── runtime/             智能体：工具、交卷结构、证据校验、提示词、运行编排
├── api/                 HTTP 接口、认证、前端数据结构转换
└── seed/                内置资源（由 tools/java_migration 从 Java 版迁移生成）
tests/                   单元测试与接口测试（scripted_model.py 是按演示脚本行动的假模型）
```

## 尚未完成

- 批量回归（`/regression/*`）：需要做成异步任务，下一步实现。
- 接入内网 DeepSeek V4-Flash 后的真实验证：工具调用稳定性、交卷结构遵守程度、耗时。目前测试只用假模型覆盖了流程和校验逻辑。
- 敏感数据：运行记录中保存了完整的手机号和单据原文（排查和“用此输入试运行”需要），是否需要脱敏或加密，待合规确认。
