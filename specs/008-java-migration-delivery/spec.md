# 需求文档（Spec）：Java 全量业务资产自动化迁移、四层黄金对拍与容器化一体交付

<!-- #Created By AiCoding(codex) -->

> **Spec Kit 使用约定**：产物文件名固定为 `spec.md`、`plan.md`、`tasks.md`；三类外部独立交付物按需确认，仅涉及项单独生成并建立链接，不涉及项只记录依据。生成时已将全部占位提示替换为真实取证内容；不适用章节保留标题并说明 `本需求不涉及` 及原因；不确定/挂账事项标注 `【待确认】` 并统一登记于第 11 节 `Q-*`。
> **项目依据**：项目宪章 `.specify/memory/constitution.md`、`AGENTS.md`、`wiki/guides/java-migration-and-verification.md` 及 `wiki/lint/java-divergence.md`。遵循先取证后写作原则，所有模板数量、缺陷编号、对拍脚本与容器配置均已核对当前源码。

---

**功能分支**：`[008-java-migration-delivery]`

**创建日期**：2026-11-16

**状态**：已交付归档

**输入**：用户描述："智能申告报告填写与资源治理平台（`report-agent`）全栈研发归档拆分（`RA-008`）：前代 Java 版（`pdf-agent-parse`）33 套生产模板、11 个填报 Skill 与 3 个接口契约自动化迁移与缺陷主动修复、四层黄金标准对拍与回归测试、前后端一体化 Docker 容器与反代子路径适配、以及 46 篇 Karpathy LLM Wiki 知识库沉淀。"

## 基本信息 【核心】

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-008` |
| 需求名称 | Java 全量业务资产自动化迁移、四层黄金对拍与容器化一体交付 |
| 核算工作量 | 19.0 人天 |
| 资料与证据来源 | 1. **迁移生成器与对拍工具链（高可信）**：`tools/java_migration/{generate.py,analyze_java.py,verify_structure.py,verify_render.py,check_skills.py,smoke_run.py}`、`tools/java_migration/{field_catalog.yaml,template_ids.yaml,template_descriptions.yaml,README.md,MAPPING.md,TEMPLATES.md}`、`tools/java_migration/harness/*.java`；<br>2. **生产内置资源集（高可信）**：`src/report_agent/seed/templates/100..132/`、`src/report_agent/seed/skills/`、`src/report_agent/seed/apis/`、`src/report_agent/seed/mock-gateway/`；<br>3. **容器与反代交付源码（高可信）**：`Dockerfile`、`docker-entrypoint.sh`、`.dockerignore`、`.env.example`、`.github/workflows/docker-image.yml`、`src/report_agent/{main.py,config.py,cli.py}`；<br>4. **回归测试与知识库（高可信）**：`tests/test_migrated_seed.py`、`wiki/` 全部 46 篇文档（含 `SCHEMA.md`、`index.md`、`log.md`、`lint/java-divergence.md`、`lint/open-questions.md`） |
| 文档版本 | 2.0 |
| 文档状态 | 已交付归档 |

---

## 1. 业务背景与目标 【核心】

### 1.1 业务背景

`report-agent` 平台需平替前代 Java 版本（`pdf-agent-parse`）的线上业务能力。前代系统在生产中积累了 33 套 Markdown/Pebble 报告模板、33 份 `.rule` 规则、11 个依赖 Groovy 动态脚本的取数 Skill 以及 3 个统一网关 XML 接口契约，同时存在若干线上隐性缺陷（活动编号被宽松正则误算为非法日期、纯年月回溯失真、靓号匹配与空等级失一致、同名入参警告、缺失占位符恒真导致违约金死分支等）。

如果采用手工逐个复制改写模板与脚本，不仅 33 套模板极易在分支逻辑和隐藏变量上引入人为失真，更会把旧 Groovy 缺陷带入新平台。因此亟需构建配置驱动的幂等迁移生成器、面向“零业务硬编码 + 确定性工具”的新版声明式资源体系、多层次黄金对拍门禁，以及支持任意反代子路径的单进程一体化 Docker 交付管道和结构化 LLM Wiki 工程知识库。

### 1.2 业务目标

- **GOAL-1**：实现 33 套生产模板（`100`～`132`）、11 个纯文本填报 Skill、3 个统一网关 XML 接口契约与 6 份 `mock-gateway` 样例的自动化迁移重建，使 `validate_all()` 达到 `0 errors, 0 warnings` 并彻底修复 R2/R4/R5/R7/R8/R17 历史缺陷。
- **GOAL-2**：建立从静态结构 AST 扫描（S1～S9）、Java Pebble 逐字渲染对比、XML/Groovy 脚本黄金对拍到沙箱真模型端到端试跑的四层自动化对拍体系，并固化为可跨环境自适应执行的 `pytest` 回归套件。
- **GOAL-3**：交付三阶段非 root（UID 2000）单进程（`workers=1`）前后端一体化容器镜像、任意子路径反代适配能力与自动化 GHCR 发布流水线，并按 `wiki/SCHEMA.md` 沉淀 46 篇高质量可演进知识库。

---

## 2. 需求概述 【核心】

本需求承接平台底座（001～007），完成前代 Java 系统全部存量生产业务资产向 `report-agent` 声明式文件架构的迁移、缺陷治理、等价性验证及最终容器化交付封装。在资产迁移侧，以 `tools/java_migration/field_catalog.yaml`、`template_ids.yaml` 与 `template_descriptions.yaml` 为静态配置基准，通过 `generate.py` 幂等生成 `src/report_agent/seed/templates/100..132/` 与 `TEMPLATES.md`，并把前代 Groovy 脚本改写为基于平台 12 个确定性原语的纯文本 `SKILL.md`（同步在后续演进中清理原 Java 对照尾巴，保持说明聚焦当前平台取值逻辑）。

在质量与交付侧，建设 `verify_structure.py`（S1～S9 静态与 AST 门禁）、`verify_render.py`（`PebbleRenderHarness` 逐字对拍）、`check_skills.py`（`JavaXmlRequestHarness` / `JavaSkillGoldenHarness` 与 7 项二期修复断言）及 `smoke_run.py` 四层防线，并通过 `tests/test_migrated_seed.py` 纳入日常回归；同时落地三阶段多架构友好 `Dockerfile`、`_SubpathPrefixMiddleware` 与 46 篇结构化 `wiki/` 知识文档。

### 2.1 用户场景与测试

#### 用户故事 1（US1）— 全量业务资产自动化迁移与历史缺陷主动修复（优先级：P1）

- **用户旅程**：作为业务配置与迁移工程师，我希望通过配置驱动的幂等生成脚本重建 33 套生产模板与对照清单，并将 11 个 Groovy Skill 和 3 个 XML 契约无损升级为使用平台确定性工具的纯文本资产，同时根治前代线上缺陷与发布警告。
- **优先级理由**：生产模板、Skill 与网关契约是新平台替代旧系统正式上线的业务前提，必须在 MVP 阶段确保零失真且不“带病平移”。
- **独立测试**：不启动外网大模型或 JDK，直接运行 `tests/test_migrated_seed.py` 中的无 Java 依赖用例验证 33 套生产模板 `validate_all()` 达到 `0 errors, 0 warnings`、无同名「客户号码」入参警告、模板 `120`/`111`/`114`/`115` 占位符分支修复、`121`/`标准资费` `derive` 推导及 `cc_pretty_num_info_query` 顶层故障拦截。
- **关联需求**：FR-001, FR-002, FR-003
- **验收场景**：
  1. **前提** Java 模板目录、`.rule` 规则、`field_catalog.yaml`、`template_ids.yaml` 与 `template_descriptions.yaml` 就绪，**当** 执行 `uv run python tools/java_migration/generate.py`，**则** 幂等生成 `src/report_agent/seed/templates/100..132/` 下的 `template.yaml`（精准区分 `visible: true` 输出字段与 `visible: false` 隐式依赖字段、移除冗余 `客户号码` 入参、为 `105/108/112/120/129` 补齐可选 `deadlineDate`、注入场景适用说明、将 `121` `安装地址` 与 10 个模板 `标准资费` 设为 `evidence: derive`）与 Pebble 等价 `body.md.j2`（含模板 `115` 第 59 行占位符排除守卫）并同步更新 `TEMPLATES.md`。
  2. **前提** 11 个纯文本填报 Skill 与 3 个 XML 契约（`querySMSSendInfo`、`BOSS_QryBalanceFlowLog`、`cc_pretty_num_info_query`）及 6 份 `mock-gateway` XML 样例就绪，**当** 面对含活动编号的短信、纯年月 `202607`、跨月 `202607$202610`、多档 JSON 数组活动名或网关故障报文时，**则** `reminder-sms` 准确跳过无合法日期且无 `deadlineDate` 情况（提取合法日 `20271201` 不误识 `20614901`）；`qry-balance` 展开整月流水；`billing-cycle-sms` 闭区间展开 4 个月；`pretty-number-info` 按 `msisdn` 过滤、拦截空 `grade` 判非靓号、顿号拼接多档名且契约 `missingAs: failure` 拦截网关错误。
  3. **前提** 模板 `120` 缺失 `有设备押金` 或模板 `111`/`114`/`115` 缺失 `违约责任`，**当** 执行沙箱 `render_body()`，**则** `120` 进入 `{% else %}` 输出无设备押金记录，`111`/`114` 隐藏违约金尾段，`115` 第 19 行保留占位符而第 59 行安全跳过违约行为段且不污染 `missingShown`。

#### 用户故事 2（US2）— 四层黄金标准自动化对拍与回归验证（优先级：P1）

- **用户旅程**：作为迁移质量验收工程师，我希望依托静态结构扫描、Java Pebble 真实引擎渲染比对、XML/Groovy 黄金对拍和沙箱端到端冒烟四层工具链验证新旧系统行为完全一致或差异受控，并确保这些校验固化进 CI 与 `pytest`。
- **优先级理由**：仅靠人工抽查无法兜底 33 套复杂分支模板与 11 个业务 Skill 的边界等价性，四层自动化对拍提供了客观可重复的上线门禁。
- **独立测试**：运行 `uv run python tools/java_migration/verify_structure.py` 验证 S1～S9 全项 `0 errors, 0 warnings`；运行 `uv run pytest tests/test_migrated_seed.py` 验证无 Java 依赖回归断言与自适应跳过的外部 Harness 用例。
- **关联需求**：FR-004, FR-005, FR-006
- **验收场景**：
  1. **前提** 生产 `seed` 资源与 Java 源码对照环境就绪，**当** 执行 `verify_structure.py`，**则** 依次通过 `S1`（ID 与编码一一对应）、`S2`（正文逐字一致）、`S3`（字段集与 `visible` 一致）、`S4`（有规则字段非空说明校验）、`S5`（Skill 依赖与接口存在）、`S6`（循环列完整）、`S7`（发布校验 `0 errors, 0 warnings`）、`S8`（AST 拦截缺失排除守卫的占位符恒真条件）与 `S9`（AST 校验枚举比较字面量，仅对已登记的模板 `116` 上游白名单输出 `ℹ` 提示）。
  2. **前提** 本机具备 JDK 21 与 Java 编译产物，**当** 执行 `verify_render.py` 与 `check_skills.py`，**则** `PebbleRenderHarness` 验证全 33 套模板千级组合渲染零非预期 diff；`JavaXmlRequestHarness` 验证 3 套 XML 报文与 `xml-nytool` 逐字一致；`JavaSkillGoldenHarness` 与 `verify_phase2_bug_fixes()` 验证 11 个 Skill 正常对拍与 7 项二期缺陷防线全部通过。
  3. **前提** 测试环境未安装 JDK 或缺少 Java 工程源码，**当** CI 运行 `uv run pytest -q`，**则** `tests/test_migrated_seed.py` 通过 `pytest.mark.skipif` 优雅跳过外部 Java Harness 用例，同时无条件强制完成内置资源加载、`template-router` 覆盖、缺陷专项修复及 `check_skills.py` 校验。

#### 用户故事 3（US3）— 前后端一体化容器交付与 Karpathy LLM Wiki 知识库沉淀（优先级：P2）

- **用户旅程**：作为运维部署工程师与团队新成员，我希望直接通过多阶段 Docker 镜像在根路径或任意 Nginx 子路径下以非 root 单进程启动完整服务，并通过符合元规范的 LLM Wiki 快速掌握平台架构、模板、Skill 与历史差异台账。
- **优先级理由**：容器构建标准化、子路径反代零改造适应与结构化文档沉淀是将研发成果安全交付生产并降低后续维护成本的关键闭环。
- **独立测试**：审查 `Dockerfile`、`.dockerignore`、`docker-entrypoint.sh` 与 `.github/workflows/docker-image.yml`；校验 `create_app()` 在配置 `APP_ROOT_PATH` 下对 `/agent` 与 `/agent/*` 的重定向和前缀剥离；检查 `wiki/` 全部 46 个文档的 frontmatter、路径有效性及 `log.md` 记录。
- **关联需求**：FR-007, FR-008
- **验收场景**：
  1. **前提** 代码仓库具备多入口前端与 `pyproject.toml`/`uv.lock`，**当** 执行本地 `docker build` 或触发 `.github/workflows/docker-image.yml`，**则** 阶段 1（Node 22）以 `VITE_BASE_PATH=./` 编译输出 `index.html` 与 `embed.html`，阶段 2（Python 3.13 + `uv 0.7`）通过 `uv sync --frozen --no-dev` 锁定依赖，阶段 3 切换非 root `paasopt`（`USER 2000`）、安装 `git` 与 `Asia/Shanghai` 时区并由 `docker-entrypoint.sh` 强制单进程（`workers=1`）启动服务，`.dockerignore` 严格排除 `tests/`、`tools/`、`wiki/` 等非运行产物。
  2. **前提** 生产环境设置 `APP_ROOT_PATH=/agent` 与 `FORWARDED_ALLOW_IPS=*` 且前端挂载于 `Nginx /agent/` 后，**当** 请求 `/agent` 或保留前缀的 `/agent/api/v1/...`、`/agent/embed.html`，**则** `_SubpathPrefixMiddleware` 将 `/agent` 307 重定向至 `/agent/`，并对带前缀请求同步重写 `path` 与 `raw_path` 无感透传内部路由与静态 SPA。
  3. **前提** 开发者查阅或维护平台知识，**当** 按 `wiki/index.md` 索引浏览 `wiki/` 目录，**则** 可获取遵循 `wiki/SCHEMA.md` 编写的 46 篇文档（根层 5 篇 + `architecture/` 5 篇 + `components/` 6 篇 + `skills/` 13 篇 + `decisions/` 5 篇 + `guides/` 5 篇 + `reference/` 4 篇 + `lint/` 3 篇），全部页面具备合法 YAML frontmatter、零源码易变行号、零敏感凭据与完整相对双向链接。

### 2.2 成功标准

- **SC-001**：`src/report_agent/seed/` 全量就绪 33 套生产模板（`100`～`132`）、12 个纯文本 Skill（11 填报 + `template-router`）、3 套网关接口契约及 6 份 Mock XML，执行 `validate_all()` 严格保持 `0 errors, 0 warnings`。
- **SC-002**：Java 历史遗留缺陷与契约隐患修复达 100% 回归覆盖（涵盖 R2、R4、R5、R7、R8、R17 及模板 `121`/10 模板 `标准资费` `derive` 治理），`tests/test_migrated_seed.py` 核心回归全部通过。
- **SC-003**：四层对拍体系落地：`verify_structure.py` 实测 `S1`～`S9` 全面通过（检查模板 33 个、Skill 12 个、接口 3 个，`0 errors, 0 warnings`）；`verify_render.py` 与 `check_skills.py` 在具备 Java 环境时覆盖千级渲染场景、3 套 XML 报文及 7 项专项断言。
- **SC-004**：`Dockerfile` 多阶段一体构建严格排除 `tests/`、`tools/`、`wiki/`、`node_modules/` 等非运行文件，运行态固定 `USER 2000`、`workers=1`、`proxy_headers=True` 并支持根路径与任意反代子路径零改造部署。
- **SC-005**：`wiki/` 知识库稳定沉淀 46 篇结构化文档，100% 符合 `wiki/SCHEMA.md` 元规范（无断链、无源码行号、无真实凭据、含 `log.md` 演进审计记录）。

### 2.3 假设

- **外部 Java 与 JDK 依赖可选性**：`verify_structure.py` 依赖 `JAVA_AGENT_HOME` 下 `.md`/`.rule` 源码，`verify_render.py` 与 `check_skills.py` 对拍环节依赖本机 JDK 21 与前代 Maven 编译产物；缺失外部依赖时，`tests/test_migrated_seed.py` 自动优雅跳过相关外部调用并保证核心 Python 回归全量通行。
- **测试种子隔离假设**：常规单元测试受 `tests/conftest.py` 保护隔离至 `tests/fixtures/seed/`（样例模板 `1001`），避免生产种子微调打破框架单元测试；生产 `seed/` 的全部门禁由 `tests/test_migrated_seed.py` 专责守护。
- **单进程与持久化卷假设**：容器部署必须将 PVC 挂载至 `/data`（`DATA_DIR`）并保持单进程 `workers=1`（由 `cli.py` 与 `docker-entrypoint.sh` 硬保障）。
- **工作量核算口径**：本子规格 `19.0` 人天按已交付归档口径核算，覆盖自动化生成器与分析脚手架、33 模板/11 Skill/3 接口迁修、三大 Java Harness 与四层对拍套件、`test_migrated_seed.py`、容器交付与子路径中间件以及 46 篇 LLM Wiki 编撰。

---

## 3. 术语与概念定义 【核心，如有新术语】

> 通用平台术语已在 `wiki/reference/glossary.md` 引用定义，以下仅列本迁移与交付需求中的专有术语：

| 术语 | 英文/标识 | 定义 | 备注 |
| --- | --- | --- | --- |
| 四层黄金对拍 | Four-Layer Parity | 由 `verify_structure.py`（结构/AST）、`verify_render.py`（Pebble 渲染）、`check_skills.py`（XML/Groovy/修复）与 `smoke_run.py`（沙箱 LLM 冒烟）构成的分层验证链 | 支撑无盲区替代前代 Java 版 |
| Java Harness | `PebbleRenderHarness` / `JavaXmlRequestHarness` / `JavaSkillGoldenHarness` | 直接反射或调用前代 Java 编译产物与 Maven JAR 输出标准对照结果的 3 个独立 Java 命令行程序 | 存放于 `tools/java_migration/harness/` |
| 隐式中间字段 | Implicit Dependent Field（`visible: false`） | 未直接在模板正文输出，但在 `.rule` 中通过插值被其他字段规则依赖的隐藏字段 | 在 `template.yaml` 中标记 `visible: false` |
| 占位符恒真守卫 | S8 Placeholder Guard | 针对 `whenMissing: "placeholder"` 字段在 Jinja2 条件表达式中排除 `{{字段名}}` 字面量以避免分支恒真的 AST 校验规则 | 阻断模板 115 第 59 行类死分支回归 |
| 已知上游枚举白名单 | `KNOWN_UPSTREAM_ENUM_MISMATCHES` | 在 S9 枚举 AST 门禁中为保持与线上 Java 原模板一致而显式登记的历史枚举失配清单（如模板 `116`） | 仅打印提示并挂账待确认，严禁静默漏放新失配 |

---

## 4. 用户角色 【核心】

| 角色 | 类型 | 本需求中可执行的操作与数据范围 | 权限/安全约束 |
| --- | --- | --- | --- |
| 迁移与平台工程师 | 人工角色 | 维护 `field_catalog.yaml`、运行 `generate.py` 重建 `seed/`、执行四层对拍与修复历史缺陷 | 仅对本地/开发源码与受控种子目录操作；禁止向仓库提交生产密钥 |
| 运维与发布工程师 | 人工/系统角色 | 配置 `.env`、使用 `Dockerfile` / GHCR 工作流打包部署并配置 Nginx 反代参数 `APP_ROOT_PATH` 与 `/data` PVC | 容器以非 root `paasopt`（UID 2000）单进程运行；严禁修改 `workers=1` |
| 知识库阅读与维护 Agent | 人工/智能体角色 | 通过 `wiki/index.md` 查询架构决策、模板目录、Skill 卡片与差异台账，按 `wiki/SCHEMA.md` 增量维护 `log.md` | 不得将 `wiki/` 当作业务源码反转篡改运行时行为，严禁记录真实凭证与行号 |

---

## 5. 功能需求 【核心】

### 5.1 自动化资产分析、生成与历史缺陷治理

#### FR-001 配置驱动的自动化模板生成与 Pebble 语法无损转换

- **来源**：`tools/java_migration/{analyze_java.py,generate.py,field_catalog.yaml,template_ids.yaml,template_descriptions.yaml,TEMPLATES.md}`
- **描述**：提供可重复执行的静态分析与全量模板生成工具，机械转换 Java 源模板并自动推导字段结构、可见性与入参声明。
- **关联用户故事/成功标准**：US1 / SC-001
- **业务规则**：
  1. `template_ids.yaml` 强制锁定 `100`～`132` 编号与前代 Java 模板编码一对一映射；`template_descriptions.yaml` 维护逐模板业务场景说明；`field_catalog.yaml` 声明字段类型、证据模式、`whenMissing`、`defaultValue`、关联 Skill 与 `overrides` 模板级覆写。
  2. `generate.py`（`pebble_to_jinja`）执行确定性语法转换：`{% elseif %}` → `{% elif %}`、`null` → `none`、CRLF → LF，并对模板 `115`（合约活动违约争议处理模板）第 59 行自动注入 `and 违约责任 != "{{违约责任}}"` 守卫，同时消除 YAML 折叠块中文/全角标点间多余空格（`_CJK_SPACE_RE`）。
  3. 自动扫描正文输出变量（`visible: true`）与 `.rule` 隐式规则依赖中间字段（`visible: false`），并按依赖链推导所需入参集合（`need_inputs`），生成 33 套 `template.yaml` + `body.md.j2` 及对照表 `TEMPLATES.md`（且字段 `description` 仅清晰表述取值规则而不拼接旧版 `原规则（Java）：` 尾注）。
- **输入/触发**：运行 `uv run python tools/java_migration/generate.py`。
- **输出/结果**：幂等生成 `src/report_agent/seed/templates/100..132/` 与 `tools/java_migration/TEMPLATES.md`。
- **验收标准**：
  - AC-1：重复执行 `generate.py` 产出完全一致的 33 套双文件模板，全部 ID 精确覆盖 `100`～`132`。
  - AC-2：隐式依赖字段全部正确标为 `visible: false`，模板 `115` 第 59 行准确包含占位符排除条件。

#### FR-002 生产 `seed` 资源体系就绪与零警告发布门禁

- **来源**：`src/report_agent/seed/`、`tools/java_migration/generate.py`（`INPUT_DEFS`）、`tests/test_migrated_seed.py`
- **描述**：完整落盘生产级内置种子资源并通过平台发布校验 `validate_all()`，彻底消除前代兼容性冗余告警。
- **关联用户故事/成功标准**：US1 / SC-001, SC-002
- **业务规则**：
  1. `src/report_agent/seed/` 必须完整包含 33 套生产模板（`100`～`132`，不含测试用模板 `1001`）、12 个纯文本 Skill（11 个填报取数 Skill + `template-router`）、3 套统一网关 XML 契约（`querySMSSendInfo`、`BOSS_QryBalanceFlowLog`、`cc_pretty_num_info_query`）及 6 份覆盖正例/无数据/失败分支的 `mock-gateway` XML 样例。
  2. `querySMSSendInfo.yaml` 移除过严的“31 天跨度”说明，补充真实返回列 `smsSendStatus`/`userMobile`/`remark`/`staffId` 并置 `retry.maxAttempts: 1`；`BOSS_QryBalanceFlowLog.yaml` 采用 `${$now}` 动态注入请求时间；3 个契约 `schema_errors()` 全部为空。
  3. 剔除历史为兼容注入的冗余入参 `客户号码`，彻底消除模板 `106`/`107`/`131`/`132` 的 4 条 `FIELD_SAME_AS_INPUT` 警告。
- **输入/触发**：`load_resource_dir(PROD_SEED_DIR)` 与 `validate_all(rs)`。
- **输出/结果**：加载无问题，发布校验 `0 errors, 0 warnings`。
- **验收标准**：
  - AC-1：`test_prod_seed_loads_and_validates_zero_warnings` 与 `test_no_customer_phone_input_collision` 验证 `validate_all()` 为空列表，无任一模板含 `客户号码` 入参。

#### FR-003 Groovy 转纯文本确定性 Skill 与历史缺陷修复

- **来源**：`src/report_agent/seed/skills/*`、`tools/java_migration/MAPPING.md`、`src/report_agent/seed/templates/`
- **描述**：使用平台 12 个确定性原语替换前代 Groovy 脚本与隐含服务层硬编码策略，并根治已知线上缺陷。
- **关联用户故事/成功标准**：US1 / SC-002
- **业务规则**：
  1. **R2 修复（`reminder-sms` / `renewal-reminder-sms`）**：使用 `extract_dates` 真日历扫描，避免活动编号（如 `25JS206149`）误判日期 `20614901`；为 `105/108/112/120/129` 补齐可选入参 `deadlineDate` 并优先采信；无合法日期且无 `deadlineDate` 时直接跳过接口查询返回 `not_found`，绝不回退 `创建时间` 当天误命中办理短信。
  2. **R5 修复（`pretty-number-info` + 网关契约）**：使用 `query_result` 精确比对 `msisdn == 手机号码`；`grade` 为空或无匹配一律判为非靓号（模板默认值 `非靓号`）；多档 JSON 数组活动名按顿号 `、` 拼接且 `靓号活动名称` 为 `derive`；`cc_pretty_num_info_query.yaml` 设置 `response.success.missingAs: failure` 拦截顶层网关报错。
  3. **R8 与 R4 修复（`qry-balance` / `billing-cycle-sms`）**：使用 `expand_period` 展开纯年月（如 `202607`）与 `$` 跨月闭区间并配合 `query_result(resultIds=..., between, prefixLen=8)` 消除年月回溯丢流水缺陷；入参齐备且网关 `ok=true` 命中 0 行时按 `status="found", value=[]` 提交并绑定 `total=0`/`count=0` 查询证据。
  4. **R17 与衍生推导治理**：模板 `120` `有设备押金` 与模板 `111`/`114` `违约责任` 设 `whenMissing: empty`、模板 `115` 保留占位符但第 59 行排除占位符字面量；模板 `121` `安装地址`（支持 `extraInfo` 回退）与 10 套模板 `标准资费` 设 `evidence: derive`；前代服务层硬编码策略全量收敛进模板字段说明与 `system-prompt.md`。
- **输入/触发**：沙箱渲染、工具链模拟与证据校验测试。
- **输出/结果**：全量 11 个纯文本填报 Skill 及修复后模板配置通过契约与规则断言。
- **验收标准**：
  - AC-1：`test_template_120_deposit_else_branch_fix`、`test_pretty_number_fields_config`、`test_batch2_seed_consistency_fixes` 与 `check_skills.py#verify_phase2_bug_fixes` 全部通过。

### 5.2 四层黄金标准自动化对拍与持续回归

#### FR-004 第一层结构一致性与 `S8`/`S9` AST 静态门禁

- **来源**：`tools/java_migration/verify_structure.py`
- **描述**：对全部模板正文、字段属性、Skill 映射及发布规则执行跨系统静态比对与 Jinja2 AST 安全门禁。
- **关联用户故事/成功标准**：US2 / SC-003
- **业务规则**：
  1. 完整执行 `S1`（模板集与 ID 编码一致性）、`S2`（正文转换逐字一致）、`S3`（字段集与 `visible` 属性一致）、`S4`（有规则字段非空说明校验）、`S5`（Skill 依赖及 API 存在性）、`S6`（循环列完整）与 `S7`（`validate_all()` 0 error / 0 warning）。
  2. `check_s8_placeholder_if_guards` 解析 Jinja2 AST 的 `nodes.If` 节点：凡对 `whenMissing == "placeholder"` 字段作真值或 `!= ""`/`!= none` 判断者，必须显式排除 `{{字段名}}`（或采用安全的 `is hasDigit` / 具体字面量 `==`/`in` 比较），否则阻断报错。
  3. `check_s9_enum_compare_literals` 校验顶层及循环内枚举字段比较常量是否在可选值 `values` 内：仅放行并在控制台以 `ℹ` 标记 `KNOWN_UPSTREAM_ENUM_MISMATCHES` 中登记的模板 `116` 历史渠道字面量，其余未登记误写立即阻断。
- **输入/触发**：`uv run python tools/java_migration/verify_structure.py [--resources DIR]`。
- **输出/结果**：校验摘要、可选白名单提示及退出码（0 通过 / 1 阻断）。
- **验收标准**：
  - AC-1：实测运行 `verify_structure.py` 检查模板 33 个、Skill 12 个、接口 3 个，输出 `0 errors, 0 warnings` 与 S8/S9 门禁全通过。

#### FR-005 二/三/四层 Java 黄金对拍 Harness 与真实模型沙箱冒烟

- **来源**：`tools/java_migration/{verify_render.py,check_skills.py,smoke_run.py}`、`tools/java_migration/harness/*.java`
- **描述**：利用 3 个直接对接前代 Java 编译产物与 Groovy 引擎的 Harness 程序完成渲染、报文与脚本黄金对拍，并提供端到端真实模型冒烟能力。
- **关联用户故事/成功标准**：US2 / SC-003
- **业务规则**：
  1. `verify_render.py` 调用 `PebbleRenderHarness.java` 批量构建全命中（含/不含数字）、全缺失、枚举单值及全组合（上限 512）、条件置空标量与 0/1/3 行列表场景，对齐 CRLF/`{{ 字段 }}` 空格差异并对模板 `120`/`111`/`114`/`115` 修复段作预期检验，验证其余文本与 Java Pebble 逐字 0 差异。
  2. `check_skills.py` 调用 `JavaXmlRequestHarness.java` 与 `JavaSkillGoldenHarness.java`：验证 3 套契约 XML 序列化与 Jackson 3 `xml-nytool` 逐字一致（动态 `<request_time>` 校验 14 位数字后归一化比较）；校验 6 份 Mock 响应解析；运行平台确定性工具模拟 11 个 Skill 与 Groovy 真值对拍并执行 `verify_phase2_bug_fixes()` 7 项专项修复断言。
  3. `smoke_run.py` 复制当前 `DATA_DIR` 至临时沙箱，强制 `gateway_mode="mock"` 在指定模板 ID（默认 `101`）执行一次真实大模型全链路试跑并在结束时删除临时目录。
- **输入/触发**：执行 `verify_render.py`、`check_skills.py` 或 `smoke_run.py [tid]`。
- **输出/结果**：JSON diff 报告、逐项 `[OK]/[FAIL]` 清单及试运行字段结果原文。
- **验收标准**：
  - AC-1：在具备 JDK 环境时 `verify_render.py` 与 `check_skills.py` 全部返回退出码 0；在无 JDK 环境时 `check_skills.py` 报文模拟与 7 项缺陷修复断言仍 100% 通过。

#### FR-006 自适应跨环境 `tests/test_migrated_seed.py` 回归测试保护

- **来源**：`tests/test_migrated_seed.py`、`tests/conftest.py`
- **描述**：将生产 `seed/` 校验与对拍工具纳入 `pytest` 体系，实现与常规单元测试夹具隔离、与外部 JDK 环境自适应兼容。
- **关联用户故事/成功标准**：US2 / SC-001, SC-002
- **业务规则**：
  1. `tests/conftest.py` 隔离普通测试至样例模板 `1001`，`test_migrated_seed.py` 显式引入 `PROD_SEED_DIR` 验证生产资源加载零警告、`template-router` 全覆盖、`客户号码` 冲突消除、`120`/`121`/`标准资费`/`111`/`114`/`115`/`deadlineDate` 修复、模板 ID 匹配及 `check_skills.py`。
  2. 对依赖 `/Users/.../agent` 源码与 JDK 的 `test_structure_consistent_with_java` 与 `test_render_equivalent_to_java_pebble` 通过 `@pytest.mark.skipif` 检测目录和 `java` 可执行文件，缺失时优雅跳过而不导致纯 Python 环境 CI 误挂。
- **输入/触发**：`uv run pytest -q` 或 `uv run pytest tests/test_migrated_seed.py`。
- **输出/结果**：全量无外部环境依赖测试 100% 稳定通过。
- **验收标准**：
  - AC-1：本轮全量 `uv run pytest -q`（`196 passed in 51.41s`）稳定执行并包含 `test_migrated_seed.py` 全部生产回归用例。

### 5.3 容器一体化交付与 LLM Wiki 知识库

#### FR-007 多阶段一体化容器构建、单进程守护与子路径反代适配

- **来源**：`Dockerfile`、`docker-entrypoint.sh`、`.dockerignore`、`.env.example`、`.github/workflows/docker-image.yml`、`src/report_agent/{main.py,config.py,cli.py}`
- **描述**：构建安全轻量化前后端一体化容器镜像与自动推送工作流，并通过反向代理子路径中间件支持灵活挂载部署。
- **关联用户故事/成功标准**：US3 / SC-004
- **业务规则**：
  1. `Dockerfile` 采用三阶段构建：`frontend-builder`（Node 22 + `VITE_BASE_PATH=./` 编译输出多入口产物）→ `backend-builder`（Python 3.13 + `uv 0.7` `uv sync --frozen --no-dev`）→ 运行阶段（安装 `git` 与 `Asia/Shanghai` 时区、创建 `paasopt` UID `2000`、`USER 2000`、挂载 `/data`、`FRONTEND_DIST=/app/frontend/dist`）。
  2. `.dockerignore` 严格排除 `.git`、`.venv`、`.env`、`data`、`frontend/node_modules`、`frontend/dist`、`tests`、`tools`、`wiki` 等非运行目录。
  3. `docker-entrypoint.sh` 对 `LLM_API_KEY` 为空或默认值 `dummy` 输出显式启动警告，并调用 `report-agent serve`；`cli.py` 固定锁定 `workers=1`、`proxy_headers=True` 与 `forwarded_allow_ips=settings.forwarded_allow_ips`。
  4. 当配置 `APP_ROOT_PATH`（经 `Settings.normalized_root_path()` 规范化为 `/prefix`）时，`create_app()` 注册 `_SubpathPrefixMiddleware`：对精确命中 `/prefix` 的 HTTP 请求 `307` 重定向至 `/prefix/`，对 `/prefix/*` 请求同步剥离 `path` 与 `raw_path` 前缀并兼容静态 SPA 与 API 路由。
  5. `.github/workflows/docker-image.yml` 配置 `linux/amd64` 镜像多标签构建与推送至 `ghcr.io`。
- **输入/触发**：Docker 构建、容器启动、反代子路径 HTTP 请求或 Git 推送/手动触发 Actions。
- **输出/结果**：单进程非 root 容器镜像运行服务；任意子路径反代无感访问工作台、`embed.html` 与 `/api/v1/*`。
- **验收标准**：
  - AC-1：`Dockerfile`、`.dockerignore`、`docker-entrypoint.sh`、`cli.py`（`workers=1`）及 `_SubpathPrefixMiddleware` 逻辑核查完整准确。

#### FR-008 Karpathy LLM Wiki 分层知识库体系沉淀

- **来源**：`wiki/SCHEMA.md`、`wiki/index.md`、`wiki/log.md` 及 `wiki/` 全部 46 篇文档
- **描述**：构建长期可演化的分层项目知识图谱，为后续开发者与编码 Agent 提供统一可检索的架构、组件、Skill、ADR 与差异台账。
- **关联用户故事/成功标准**：US3 / SC-005
- **业务规则**：
  1. 全库共 46 篇 Markdown 文档：根层 5 篇（`SCHEMA.md`、`index.md`、`log.md`、`overview.md`、`timeline.md`）、`architecture/` 5 篇、`components/` 6 篇、`skills/` 13 篇（`README.md` + 12 个 Skill 卡片）、`decisions/` 5 篇 ADR、`guides/` 5 篇、`reference/` 4 篇及 `lint/` 3 篇。
  2. 除 `SCHEMA.md` 与 `log.md` 外其余 44 篇均须以标准 YAML frontmatter（`title`/`type`/`tags`/`sources`/`updated`）开头，并在文末提供 `## 相关页面` 相对双向链接。
  3. 正文严格禁止写入易随提交漂移的源码行号（统一写 `路径#符号名`），严禁出现真实 API Key/口令/生产数据；所有变更按时间顺追加记录至 `wiki/log.md`；业务待确认事项统一挂账于 `wiki/lint/open-questions.md`。
- **输入/触发**：系统演进或资产变更后执行 Ingest 与 Lint 维护。
- **输出/结果**：全库零断链、零孤立页且与源码实事单一来源对齐的 46 篇 Wiki 文档。
- **验收标准**：
  - AC-1：全库 46 个 `.md` 文件数量、目录结构、YAML frontmatter 与 `log.md` 追加记录核查一致。

---

## 6. 非功能需求 【补充】

| 类型 | 编号 | 说明 | 验收方式 |
| --- | --- | --- | --- |
| 零业务硬编码迁移目标 | `NFR-001`（宪章 I） | 将前代 Java 服务层硬编码策略（如 `applyAcceptDatePolicy`、`applyTerminalInfoPolicy`、`reconcileWithSkillValues`）及 Groovy 脚本全面转化为声明式 YAML、`SKILL.md` 与 `system-prompt.md`，不向 `src/report_agent/` 注入特定模板硬编码 | 代码与 `MAPPING.md` 核查 |
| 强证据防幻觉静态与动态防线 | `NFR-002`（宪章 II） | `field_catalog.yaml` 准确区分 `quote`/`input`/`derive`；`verify_structure.py` S8/S9 AST 门禁阻断恒真死分支与非法枚举误写；`check_skills.py` 验证空列表不得引用 `load_skill` | `verify_structure.py` 与 `check_skills.py` 验证 |
| 单进程安全与轻量化容器镜像 | `NFR-003`（宪章 III、VIII） | 容器启动固定 `workers=1` 与 `USER 2000` 非 root 运行；`.dockerignore` 排除 `tests/`、`tools/`、`wiki/`、`node_modules/` 最小化镜像体积与攻击面 | `Dockerfile`、`docker-entrypoint.sh`、`cli.py`、`.dockerignore` 审查 |
| 零凭据泄露与反代安全 | `NFR-004`（宪章 VI） | `.env.example` 与 `wiki/` 严禁包含真实 `LLM_API_KEY`、工作台口令或现网数据；`docker-entrypoint.sh` 对空或 `dummy` 密钥发出警告；`forwarded_allow_ips` 显式可控 | 安全审查 `.env.example`、`wiki/` 与 `docker-entrypoint.sh` |
| 知识库与测试隔离可复现 | `NFR-005`（宪章 V、IX） | `tests/conftest.py` 与 `test_migrated_seed.py` 双向隔离且跨无 JDK 环境可运行；`wiki/` 遵循 `SCHEMA.md` 无行号耦合与只追加日志约束 | `uv run pytest -q` 与 Wiki 目录/链接核验 |

---

## 7. 数据与存储需求 【补充】

| 数据对象/存储位置 | 变更类型 | 关键字段与口径 | 一致性/留存策略 | 关联需求 |
| --- | --- | --- | --- | --- |
| `src/report_agent/seed/` | 新增/全量生成 | 33 套双文件模板 `100..132/`、11 个填报 Skill（共 12 个）、3 个 XML 契约、6 份 `mock-gateway` XML 与 `system-prompt.md` | 随代码库版本管理，冷启动 `seed_on_empty=true` 时导入 `DATA_DIR/repo/` 成为初始 `r1` | FR-001 ~ FR-003 |
| `tools/java_migration/*.yaml` | 新增 | `field_catalog.yaml`、`template_ids.yaml`、`template_descriptions.yaml` 元数据配置字典 | 人工维护配置单一事实来源，`generate.py` 幂等覆盖输出 | FR-001 |
| 容器运行 `/data` PVC 目录 | 配置约定 | 映射环境变量 `DATA_DIR=/data`（存储 `repo/`、`releases/`、`drafts/`、`runs/`、`chats/`、`cases/`、`config/`、`audit.jsonl`） | 容器 `chown paasopt:paasopt`，持久化挂载确保重启不丢数据 | FR-007 |
| `wiki/` 知识图谱（46 篇） | 新增 | 带 YAML frontmatter 的分层 Markdown 文档与只追加 `log.md` | 按 `wiki/SCHEMA.md` 增量同步，零断链维护 | FR-008 |

---

## 8. 外部接口与集成 【补充】

| 接口/系统 | 方向 | 交互内容 | 是否新增 | 关联需求 | 备注 |
| --- | --- | --- | --- | --- | --- |
| 平台 → 统一网关（3 契约） | 出站 | `querySMSSendInfo`、`BOSS_QryBalanceFlowLog`（`${$now}`）、`cc_pretty_num_info_query`（`missingAs: failure`） | 是（迁移内置契约） | FR-002, FR-003, FR-005 | 协议 `unified-gateway-xml`（`style=java`）；契约位于 `src/report_agent/seed/apis/` |
| 对拍工具 → 本地 Java 编译产物 | 本地进程调用 | 调用 `PebbleRenderHarness`、`JavaXmlRequestHarness`、`JavaSkillGoldenHarness` 获取黄金真值 | 是（仅测试/对拍工具） | FR-005, FR-006 | 依赖 `JAVA_AGENT_HOME` 与 JDK 21；缺省时由 `skipif` 跳过 |
| Nginx 反代 ↔ 应用 `_SubpathPrefixMiddleware` | 入站（HTTP/WS） | 在任意前缀（如 `/agent`）下重定向 `/agent -> /agent/` 并剥离前缀透传 `X-Forwarded-*` | 是 | FR-007 | 受 `APP_ROOT_PATH` 与 `FORWARDED_ALLOW_IPS` 控制 |
| CI → GitHub Container Registry | 出站 | `docker/build-push-action` 自动打包推送多标签镜像 | 是 | FR-007 | 配置位于 `.github/workflows/docker-image.yml` |

### 8.1 出站网关与模型接口契约摘要（涉及时填写）

| 接口/工具 | 调用方向 | 协议与端点 | 路由/识别字段 | 成功判定 | 关键失败与降级策略 |
| --- | --- | --- | --- | --- | --- |
| `querySMSSendInfo` | 平台 → 统一网关 | `unified-gateway-xml`（`processCode=querySMSSendInfo`） | `手机号码`（`route_type=2`） | `response.resp_code == "0000"`；特定无记录码判 `no_data` | `retry.maxAttempts=1`；非无记录故障置 `ok=false` 且字段退回 `not_found` |
| `BOSS_QryBalanceFlowLog` | 平台 → 统一网关 | `unified-gateway-xml`（`processCode=BOSS_QryBalanceFlowLog`） | `手机号码`、`账期`（`${$now}` 填 `request_time`） | 响应成功节点及返回码匹配 | `retry.maxAttempts=1`；7003 等错误判失败并置列表 `not_found` |
| `cc_pretty_num_info_query` | 平台 → 统一网关 | `unified-gateway-xml`（`processCode=cc_pretty_num_info_query`） | `手机号码` | `content.ret_code == "0"`（`1` 判无数据非靓号） | `missingAs: failure` 拦截缺失 `content.ret_code` 的顶层网关 `resp_code=9999` 报错 |

### 8.2 三类独立交付物涉及情况

| 独立文档 | 涉及情况 | 判断依据与范围摘要 | 确认来源/日期及关联需求 |
| --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs/Dockerfile 中） | 迁移的三套 XML 接口已存于 `seed/apis/*.yaml` 且摘要沉淀于 `wiki/reference/apis-catalog.md`，无对外 REST 集成新契约 | 归档拆分要求（2026-11-16）；FR-002 |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs/Dockerfile 中） | 全量模板对照表、缺陷映射与迁移清单已存于 `tools/java_migration/{TEMPLATES.md,MAPPING.md}` 及 `wiki/reference/` | 归档拆分要求（2026-11-16）；FR-001, FR-002 |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs/Dockerfile 中） | 容器编排与全量变量说明已存于 `Dockerfile`、`docker-entrypoint.sh`、`.env.example` 及 `wiki/guides/dev-test-and-deploy.md` | 归档拆分要求（2026-11-16）；FR-007 |

---

## 9. 边界与约束 【补充】

### 9.1 范围边界

**本次需求包含（In Scope）：**

- 前代 Java 33 套生产模板（`100`～`132`）、11 个填报 Skill、3 个 XML 接口契约及 6 份 Mock 响应的迁移生成与 R2/R4/R5/R7/R8/R17 缺陷修复。
- `tools/java_migration/` 全套分析、生成、四层对拍脚本与 3 个 Java Harness 程序及文档（`README.md`、`MAPPING.md`、`TEMPLATES.md`）。
- `tests/test_migrated_seed.py` 跨环境自适应回归套件。
- 根目录 `Dockerfile`、`docker-entrypoint.sh`、`.dockerignore`、`.env.example`、`.github/workflows/docker-image.yml` 及 `APP_ROOT_PATH` / `_SubpathPrefixMiddleware` / `workers=1` 守护。
- `wiki/` 全部 46 篇文档与 `SCHEMA.md` / `index.md` / `log.md` 规范维护。

**本次需求不包含（Out of Scope）：**

- 平台核心运行时领域模型、Jinja2 沙箱、12 个确定性工具、工作台后端 API、前端工作台 IDE 及嵌入式聊天窗口（由 001～007 子规格覆盖）。
- 外部统一网关现网服务改造、真实客户生产隐私数据导入或线下硬件环境部署运维。
- `tests/fixtures/seed/` 中仅用于单元测试隔离的样例模板 `1001`。

### 9.2 技术与业务约束

- `template_ids.yaml` 中 `100`～`132` 编号不得随意重排或删改，以兼容上游系统历史工单路由调用。
- 已运行环境启动后内置 `seed/` 仅在冷启动空目录（`SEED_ON_EMPTY=true`）导入一次，已部署实例变更资源需经工作台或发布接口操作。
- 生产容器绝对禁止配置多进程 Worker（`workers > 1`），且严禁在容器中内置真实生产密钥。

---

## 10. 异常场景与边界情况 【核心】

| 编号 | 场景描述 | 触发条件 | 预期处理方式 | 是否阻断主流程 | 优先级 | 关联需求 |
| --- | --- | --- | --- | --- | --- | --- |
| EX-001 | 测试宿主机缺失 JDK 21 或 Java 工程目录 | 纯 Python CI 环境执行 `uv run pytest` | `test_migrated_seed.py` 通过 `@pytest.mark.skipif` 跳过依赖外部 Java 的两项用例，无条件执行资源零警告、修复断言与 `check_skills.py` | 否 | 高 | FR-006 |
| EX-002 | 上游 Java 原模板自带枚举失配（模板 116） | `verify_structure.py` S9 扫描模板 `116` 第 38 行 5 个历史渠道字面量 | 通过 `KNOWN_UPSTREAM_ENUM_MISMATCHES` 白名单显式放行并打印 `ℹ` 提示、记入 `Q-001` 待业务确认，拦截其他未知枚举失配 | 否 | 中 | FR-004 |
| EX-003 | `BOSS_QryBalanceFlowLog` 动态时间戳报文对拍 | Java 实时读取当前时间生成 `<request_time>` 与 Python `${$now}` 存在秒级漂移 | `check_skills.py` 先正则校验证明两边 `<request_time>` 均为合法 14 位数字，再统一归一化为 `<request_time>TS</request_time>` 逐字比对 | 否 | 中 | FR-005 |
| EX-004 | Pebble 与 Jinja2 正文空格/换行及修复段差异 | 对比 Java 原模板和含 R17 修复的模板 `120`/`111`/`114`/`115` | `verify_render.py` 归一化 CRLF 与 `{{ 字段 }}` 空格，对 4 个主动修复段落检验新预期并逐字比对剩余全部正文 | 否 | 高 | FR-005 |
| EX-005 | 容器启动缺密钥或反代未剥离前缀访问 | 容器 `LLM_API_KEY` 为空/`dummy`；或请求直接打向 `/agent` 无尾斜杠 | `docker-entrypoint.sh` 打印显式中文警告不静默失败；`_SubpathPrefixMiddleware` 自动 `307` 跳 `/agent/` 并剥离前缀透传 `raw_path` | 否 | 高 | FR-007 |

---

## 11. 待确认事项 【核心】

> 以下事项在工程迁移中已采取与前代 Java 一致的兼容处理或安全挂账措施，**不阻塞本次工程实现与回归上线**，保留至业务侧最终拍板后在工作台模板资源层在线调整发布。

| 编号 | 问题描述 | 影响范围 | 责任方 | 期望确认日期 | 状态 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| Q-001 | 模板 `116`（`增值业务扣费争议处理模板` 第 38 行）保留自 Java 原模板的 5 个历史渠道字面量（`合作方平台`、`电视端`、`APP`、`短信`、`一级电渠`）不在 `accept-type` 标准枚举 `["热线","掌上营业厅","其他"]` 内，应归并至 `"掌上营业厅"` 还是扩展新枚举值【待确认】 | 模板 `116` / `verify_structure.py` S9 白名单 | 业务产品负责人 | 待业务排期确定 | 待确认（工程已登记 `KNOWN_UPSTREAM_ENUM_MISMATCHES` 不阻塞） | 暂保持与 Java 原模板 S2 逐字一致，待业务确认后可在工作台在线修改并去掉 S9 白名单 |
| Q-002 | 历史 `.rule` 中 21 个模板存在未被正文引用的孤立规则字段、现网 `BOSS_QryBalanceFlowLog` 充值金额单位（元/分）及幂等只读契约 `retry.maxAttempts` 是否需在切流前由 `1` 调为 `2`【待确认】 | `wiki/lint/open-questions.md`、`src/report_agent/seed/apis/*.yaml` | 业务运营与网关对接方 | 灰度切流前 | 待确认（工程按等价基线运行不阻塞） | 均已沉淀于 `wiki/lint/open-questions.md`，后续灰度报文验证后直接通过配置发布变更 |

---

## 附录：原始需求描述 【补充】

```text
智能申告报告填写与资源治理平台（report-agent）全栈研发工作拆分（RA-008 / 19.0 人天）：
负责前代 Java 版（pdf-agent-parse）33 套生产报告模板（100~132）、11 个填报 Skill 与 3 个接口契约的
自动化迁移与线上历史缺陷修复、四层黄金标准对拍工具链与全量回归测试、前后端一体化 Docker 容器构建与
反代子路径支持以及 46 篇 Karpathy LLM Wiki 知识库沉淀。
```

---

## 变更记录（Changelog）

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | AiCoding (codex) | 基于初期 Spec Kit 模板完成 008 子规格归档整理（3 US、FR-001~008、19.0 人天） |
| 2.0 | 2026-11-16 | AiCoding (codex) | 按改造后中文 Spec-Kit 与 `/sdd-documentation` 标准重构全章节，补齐证据分级、S8/S9 AST 门禁及 `open-questions` 挂账 `Q-001`/`Q-002`，对齐最新生成/说明口径并核准三类独立交付物台账 |

---

## 增量更新说明

> 本文档按 `report-agent` 中文 Spec-Kit 模板与 SDD 取证规范生成并定稿归档；后续若业务侧确认关闭 `Q-001`/`Q-002`、新增迁移批次模板或修改容器构建基线，须同步刷新本规格与 `plan.md` / `tasks.md` 并追加 `wiki/log.md`。
