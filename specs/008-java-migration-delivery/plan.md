# 设计文档（Feature Design Spec）：Java 全量业务资产自动化迁移、四层黄金对拍与容器化一体交付

<!-- #Created By AiCoding(codex) -->
<!-- SPECKIT_PLAN_LAYOUT: inline-v1 -->

> **Spec Kit 使用约定**：本文件采用**单文件内联布局（inline-v1）**，研究决策、领域与存储模型、内部接口契约及验证指南全部内联维护在本文件四个锚点章节中，不另建 `research.md`、`data-model.md`、`contracts/` 或 `quickstart.md`。经核查 `spec.md` 第 8.2 节确认不额外生成三类外部独立交付物。

---

**分支**：`[008-java-migration-delivery]` | **日期**：2026-11-16 | **规格**：`./spec.md`

**输入**：`/specs/008-java-migration-delivery/spec.md`

## 基本信息

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-008` |
| 需求名称 | Java 全量业务资产自动化迁移、四层黄金对拍与容器化一体交付 |
| 对应需求文档 | `./spec.md` |
| 对应任务清单 | `./tasks.md` |
| 设计文档版本 | 2.0 |
| 设计人 | AiCoding (codex) |
| 核算工作量 | 19.0 人天 |
| 状态 | 已交付归档 |

---

## 1. 设计目标与范围 【核心】

### 1.1 设计目标（What / Why）

- **PLAN-GOAL-1**：通过配置驱动生成器（`tools/java_migration/generate.py` + `field_catalog.yaml` + `template_ids.yaml` + `template_descriptions.yaml`）实现 33 套 Java 模板、11 个 Groovy Skill 与 3 套 XML 契约向 Python 声明式资产的自动化迁移重建与历史缺陷（R2/R4/R5/R7/R8/R17）主动治理解耦，达成 `SC-001` 与 `SC-002`。
- **PLAN-GOAL-2**：构建 `verify_structure.py`（S1～S9 静态与 AST 门禁）、`verify_render.py`（`PebbleRenderHarness` 逐字渲染对比）、`check_skills.py`（`JavaXmlRequestHarness` / `JavaSkillGoldenHarness` 与 7 项专项修复断言）与 `smoke_run.py` 四层对拍管道，并通过 `tests/test_migrated_seed.py` 集成至日常 `pytest` 回归，达成 `SC-003`。
- **PLAN-GOAL-3**：完成三阶段非 root 单进程容器化方案（`Dockerfile`、`docker-entrypoint.sh`、`.github/workflows/docker-image.yml`）与 `_SubpathPrefixMiddleware` 子路径反代适配，并按 `wiki/SCHEMA.md` 规范沉淀 46 篇可演化 LLM Wiki 知识库，达成 `SC-004` 与 `SC-005`。

### 1.2 设计范围（Scope）

**包含：**

- `tools/java_migration/` 全套工具、字典与 3 个 Java Harness：`analyze_java.py`、`generate.py`、`verify_structure.py`、`verify_render.py`、`check_skills.py`、`smoke_run.py`、`field_catalog.yaml`、`template_ids.yaml`、`template_descriptions.yaml`、`README.md`、`MAPPING.md`、`TEMPLATES.md` 与 `harness/*.java`。
- `src/report_agent/seed/` 全量生产业务资源：33 套模板（`100..132/`）、11 个纯文本填报 Skill、3 个 XML 接口契约与 6 份 `mock-gateway` XML 样例。
- `tests/test_migrated_seed.py` 生产种子与迁移回归套件。
- 根目录容器与 CI 文件（`Dockerfile`、`docker-entrypoint.sh`、`.dockerignore`、`.env.example`、`.github/workflows/docker-image.yml`）以及 `src/report_agent/{main.py,config.py,cli.py}` 中 `_SubpathPrefixMiddleware`、`normalized_root_path` 与 `workers=1` 守护。
- `wiki/` 全部 46 篇知识文档及 `wiki/SCHEMA.md` / `wiki/index.md` / `wiki/log.md`。

**不包含：**

- 平台基础核心（领域模型、沙箱、单智能体运行引擎、12 工具代码、工作台 API/UI、嵌入式聊天窗口，见 001～007 子规格）。
- 测试隔离夹具 `tests/fixtures/seed/`（样例模板 `1001`）。

<a id="plan-research"></a>

### 1.3 研究与关键决策（Decision Log）

| ID | 决策点 | 备选方案 | 最终选择 | 依据与取舍理由 | 影响范围 |
| --- | --- | --- | --- | --- | --- |
| D1 | 模板资产迁移方式 | 手工逐一翻译 33 套模板 YAML 与正文字段 | 配置驱动生成器 `generate.py` + `field_catalog.yaml` 全量幂等重建 `seed/templates/` 与 `TEMPLATES.md` | 避免手改 33 套模板出现遗漏或字段漂移；字段语义、覆盖规则与正文生成逻辑完全可审计、可重复 | `tools/java_migration/generate.py`, `src/report_agent/seed/templates/` |
| D2 | 历史已知缺陷迁移策略 | 带病 1:1 复刻 Java Groovy 正则与 Pebble 空占位行为 | 借升级确定性平台原语与 S8/S9 AST 门禁主动根治 R2/R4/R5/R7/R8/R17 缺陷；极少数需保持一致的历史失配（模板 `116`）进白名单并挂账 | 既确保线上错误不再复发，又不擅自改变历史模板既有可见逻辑，在 `MAPPING.md` 与 `open-questions.md` 透明登记 | `seed/skills/`, `seed/templates/`, `verify_structure.py`, `wiki/lint/` |
| D3 | 对拍工具在无 JDK 环境下运行策略 | CI 强制安装全套 JDK + Java Maven 仓库 | 拆分 Python 自建回归与外部 Java Harness 用例；`tests/test_migrated_seed.py` 通过 `skipif` 自适应跳过外部 Harness | 保障无 JDK 容器和纯 Python 流水线稳定秒级跑通核心门禁，同时具备 Java 产物时一键执行千级场景逐字对拍 | `tests/test_migrated_seed.py`, `tools/java_migration/` |
| D4 | 反向代理任意子路径部署方案 | 每次按挂载前缀重新编译前端构建包 | 前端构建固定默认 `VITE_BASE_PATH=./` 相对基址 + 后端挂载 `_SubpathPrefixMiddleware` 自动 `307` 补斜杠并剥离前缀 | 一份 Docker 镜像同时支持域名根路径 `/` 与 `/agent` 等任意 Nginx 子路径，兼容剥离前缀和保留前缀两种转发模式 | `Dockerfile`, `frontend/vite.config.ts`, `src/report_agent/main.py`, `config.py` |
| D5 | 容器用户、依赖与镜像瘦身 | 单阶段打包带完整测试与开发依赖 | 三阶段构建（Node 22 → Python 3.13/`uv 0.7` `--frozen --no-dev` → 运行态 `USER 2000`）配 `.dockerignore` 剔除 `tests/`/`tools/`/`wiki/` | 最小化镜像体积与提权风险，仅预装运行时所需的 `git`（版本库）与 `tzdata`（上海时区） | `Dockerfile`, `.dockerignore`, `docker-entrypoint.sh` |
| D6 | 项目知识库组织形态 | 在文档中拷贝大段源码或标死源码行号 | 采用 Karpathy LLM Wiki 三层规范（`wiki/SCHEMA.md`）：YAML frontmatter + 符号引用 `路径#符号` + 双向相对链接 + 只追加 `log.md` | 杜绝行号随提交腐化失效，让人类和 Coding Agent 可在极少 Token 内高效检索全栈原理与历史决策 | `wiki/` 全部 46 篇文档 |

---

### 1.4 技术背景与项目结构

**语言/版本**：Python `>=3.12,<3.14`、Java 21（仅本地可选黄金对拍 Harness 使用）、Node.js 22 / POSIX Shell (`sh`)

**主要依赖**：`PyYAML>=6.0.2`、`Jinja2>=3.1`（AST 解析与沙箱渲染）、`uv:0.7`、`pytest`、Java `PebbleTemplateEngine` / `CommonRequestToolService` / `GroovyScriptEngine`（外部对拍依赖）、Docker Buildx & GitHub Actions

**存储**：内置随包静态资产 `src/report_agent/seed/`、迁移配置字典 `tools/java_migration/`、容器持久化挂载点 `DATA_DIR=/data` 与项目知识库 `wiki/`

**测试**：四层对拍（`verify_structure.py`、`verify_render.py`、`check_skills.py`、`smoke_run.py`）+ `tests/test_migrated_seed.py` + `ruff@0.11.0`

**目标平台**：Linux 容器（`python:3.13-slim`，`linux/amd64`，非 root `paasopt` UID `2000`，上海时区）及 macOS/Linux 本地开发对拍环境

**项目类型**：业务资产自动化迁移链 + 四层黄金对拍套件 + 容器化交付管道 + 结构化 LLM Wiki

**约束与规模/范围**：迁移 33 套生产模板（`100`～`132`）、11 个填报 Skill、3 个 XML 接口契约与 6 份 Mock 样例；构建 12 份工具文件与 3 个 Java Harness；交付 5 个容器/CI 文件与 46 篇 Wiki 文档；总工作量 `19.0` 人天

**源代码结构（真实目录落点）**：

```text
tools/java_migration/
├── analyze_java.py                             # 前代 Java 模板/规则/映射静态分析辅助工具
├── generate.py                                 # 幂等生成 33 套模板与 TEMPLATES.md 主脚本
├── field_catalog.yaml                          # 字段类型、证据模式、whenMissing、默认值与覆写配置字典
├── template_ids.yaml                           # 100~132 模板 ID 与 Java 编码强制锁定映射表
├── template_descriptions.yaml                  # 33 套模板适用场景业务说明字典
├── verify_structure.py                         # 第一层对拍：S1~S9 结构、规则、发布校验与 AST 门禁
├── verify_render.py                            # 第二层对拍：Java PebbleRenderHarness vs Python 多场景逐字比对
├── check_skills.py                             # 第三层对拍：XML 报文/Mock/11 Skill 黄金对拍与 7 项修复断言
├── smoke_run.py                                # 第四层对拍：临时数据副本 + 真实大模型 + Mock 网关端到端冒烟
├── README.md / MAPPING.md / TEMPLATES.md       # 迁移操作说明、R1~R17 差异账本与逐模板对照表
└── harness/
    ├── PebbleRenderHarness.java                # 调用 Java PebbleTemplateEngine.render() 黄金基准
    ├── JavaXmlRequestHarness.java              # 反射调用 CommonRequestToolService#toXmlRequest 黄金基准
    └── JavaSkillGoldenHarness.java             # 调用 GroovyScriptEngine 执行真实 Groovy 脚本黄金基准

src/report_agent/seed/
├── templates/100..132/                         # 33 套生产报告模板（template.yaml + body.md.j2）
├── skills/                                     # 11 个纯文本填报 Skill（外加聊天路由共 12 个）
├── apis/                                       # 3 个统一网关 XML 契约（querySMSSendInfo 等）
└── mock-gateway/                               # 6 份正例与无数据/失败 Mock XML 样例

tests/test_migrated_seed.py                     # 生产 seed 持续回归套件（含 skipif 外部 Java 适配）

Dockerfile                                      # Node 22 + Python 3.13 / uv 0.7 三阶段一体化镜像定义
docker-entrypoint.sh                            # 启动密钥预警与单进程 exec report-agent serve 入口
.dockerignore                                   # 剔除 .git/.venv/tests/tools/wiki/node_modules 等非运行资产
.env.example                                    # 全量 48+ 环境变量模板与子路径配置示例
.github/workflows/docker-image.yml              # 自动构建 linux/amd64 一体化镜像并推送 GHCR
src/report_agent/main.py / config.py / cli.py   # _SubpathPrefixMiddleware、normalized_root_path 与 workers=1 守护

wiki/
├── SCHEMA.md / index.md / log.md / overview.md / timeline.md
├── architecture/ (5 篇) / components/ (6 篇) / skills/ (13 篇)
└── decisions/ (5 篇) / guides/ (5 篇) / reference/ (4 篇) / lint/ (3 篇)  # 合计 46 篇文档
```

**禁止修改范围**：

- 严禁改动 `template_ids.yaml` 中已分配的 `100`～`132` ID；严禁去掉 `cli.py` 或 `docker-entrypoint.sh` 的 `workers=1` 限制；严禁在 `Dockerfile` 中以 root 运行或把 `.env` / `tests/` / `tools/` 打包进镜像。

#### 文档结构（本需求）

```text
specs/008-java-migration-delivery/
├── spec.md    # specify/clarify：需求规格、范围边界、挂账 Q-* 与验收标准
├── plan.md    # plan：研究决策、模型、内部契约与验证指南（inline-v1）
└── tasks.md   # tasks：可执行任务清单、测试矩阵与实测验收证据
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
| 原则 I：平台零业务硬编码与声明式资源隔离 | PASS | PASS | Java 服务层硬编码与 Groovy 脚本已全数迁移至 YAML、`SKILL.md` 与 `system-prompt.md` |
| 原则 II：单智能体规划、确定性原语与强证据防幻觉 | PASS | PASS | 11 个 Skill 升级确定性原语；模板 `121`/`标准资费` 设 `derive`；S8/S9 AST 与空列表证据防线封堵漏洞 |
| 原则 III：文件化 Git 原子发布与单进程并发安全（`workers=1`） | PASS | PASS | `seed/` 导入 `r1` 原子切换；容器启动与 CLI 硬锁定 `workers=1` 保护进程内读写锁 |
| 原则 IV–V：单文件内联设计、自动化测试隔离与 Mock 契约 | PASS | PASS | 单文件 `inline-v1`；`test_migrated_seed.py` 专测生产 `seed/` 且不干扰 `conftest.py`；6 份 Mock 样例覆盖无数据与失败分支 |
| 原则 VI–VII：安全脱敏、零硬编码凭证、事件与审计留痕 | PASS | PASS | 镜像 `USER 2000` 运行，`.dockerignore` 剔除 `.env`；`.env.example` 与 `wiki/` 无任何真实凭据 |
| 原则 VIII–X：最小改动、代码规范、Wiki 同步及三类外部交付物确认 | PASS | PASS | 46 篇 `wiki/` 按 `SCHEMA.md` 规范落地；三类外部独立交付物经核查不重复创建 |

### 1.6 复杂度跟踪

无（严格遵循项目宪章与既有架构约束；对模板 `116` 上游历史渠道枚举失配采取显式 S9 白名单与 `open-questions.md` 挂账机制，兼顾逐字等价迁移与新增误写阻断）。

### 1.7 Wiki 影响评估

- **结论**：涉及（本需求核心交付物即包含整套 46 篇 `wiki/` 知识库建设及维护流水线，当前仓库已同步落实，本轮 SDD 重构不额外新建或更改 `wiki/` 内容）
- **受影响页面**：`wiki/SCHEMA.md`、`wiki/index.md`、`wiki/log.md`、`wiki/guides/java-migration-and-verification.md`、`wiki/lint/java-divergence.md`、`wiki/lint/open-questions.md`、`wiki/decisions/adr-005-java-migration-and-bug-fixes.md`、`wiki/guides/dev-test-and-deploy.md` 等全部 46 篇。
- **同步项**：对应索引与 `log.md` 审计历史已随源码演进同步就位。

### 1.8 三类独立交付物设计检查

| 独立交付物 | 涉及情况与依据 | 设计与变更摘要 | 验证与回退设计 | 关联问题 |
| --- | --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs/Dockerfile 中） | 3 套迁移 XML 契约已存 `seed/apis/*.yaml` 与 `wiki/reference/apis-catalog.md` | 由 `check_skills.py` 与 `test_migrated_seed.py` 覆盖校验 | 无 |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs/Dockerfile 中） | 全量对照已存 `tools/java_migration/{TEMPLATES.md,MAPPING.md}` 及 `wiki/reference/` | 由 `generate.py` 与 `verify_structure.py` 核对一致 | 无 |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs/Dockerfile 中） | 容器编排与全量变量已存 `Dockerfile`、`docker-entrypoint.sh`、`.env.example` | 由 `Dockerfile` 与 `_SubpathPrefixMiddleware` 核查 | 无 |

---

## 2. 需求映射（Traceability） 【核心】

| 规格编号 | 类型 | 需求摘要 | 设计章节映射 | 后续任务映射 |
| --- | --- | --- | --- | --- |
| US1 / SC-001, SC-002 | 用户故事 | 33 模板/11 Skill/3 契约自动化迁移与缺陷修复 | 第 1.3、3、4、6 章 | `T001`–`T003`、`T005`–`T007` |
| US2 / SC-003 | 用户故事 | 四层黄金对拍工具链与自适应持续回归测试 | 第 3、5、6、10 章 | `T004`、`T008`、`T009` |
| US3 / SC-004, SC-005 | 用户故事 | 非 root 一体化容器、子路径反代与 46 篇 Wiki | 第 3、8、9、12 章 | `T010`、`T011`、`T012` |
| FR-001 | 功能需求 | `generate.py` 幂等生成、`pebble_to_jinja` 与模板 `115` 守卫 | 第 3、6 章 | `T001`–`T003` |
| FR-002 | 功能需求 | 生产 `seed/` 资产齐备与 `validate_all()` 零警告（无 `客户号码` 冲突） | 第 4、10 章 | `T005`、`T007` |
| FR-003 | 功能需求 | 11 个确定性工具 Skill 与 R2/R4/R5/R8/R17 缺陷修复 | 第 1.3、6、10 章 | `T005`、`T006`、`T007` |
| FR-004 | 功能需求 | `verify_structure.py` S1～S9 结构与 S8/S9 AST 门禁 | 第 3、6.2、10 章 | `T008` |
| FR-005 | 功能需求 | `verify_render.py`、`check_skills.py`（三大 Java Harness）与 `smoke_run.py` | 第 5、10 章 | `T004`、`T008`、`T009`、`T012` |
| FR-006 | 功能需求 | `tests/test_migrated_seed.py` 跨环境自适应回归测试 | 第 10 章 | `T009`、`T012` |
| FR-007 | 功能需求 | 三阶段 `Dockerfile`、`USER 2000`、`workers=1`、子路径中间件与 GHCR CI | 第 7、8、9、12 章 | `T010` |
| FR-008 | 功能需求 | 46 篇遵循 `wiki/SCHEMA.md` 规范的 Karpathy LLM Wiki 建设 | 第 3、4、13 章 | `T011`、`T012` |
| NFR-001 ~ NFR-005 | 非功能需求 | 零硬编码、AST 防线、非 root 单进程、零凭据与隔离可复现 | 第 7、11 章 | `T003`–`T012` |
| EX-001 ~ EX-005 | 异常边界 | 缺 JDK 跳过、模板 `116` 白名单、动态时间戳、空格对齐与反代前缀 | 第 6.2 节、第 10 章 | `T008`、`T009`、`T010` |
| Q-001, Q-002 | 挂账确认 | 模板 `116` 渠道字面量、孤立规则项、充值单位与重试次数挂账 | 第 15 章 | `T008`、`T011`、`T012` |

---

<a id="plan-data-model"></a>

## 3. 核心领域模型（Domain Model） 【核心】

### 3.1 领域对象清单

| 对象 / 类 | 所在文件 | 职责与核心属性 | 关键不变量（Invariant） |
| --- | --- | --- | --- |
| `field_catalog.yaml` Schema | `tools/java_migration/field_catalog.yaml` | 统一声明各字段的 `type`、`values`、`columns`、`evidence`、`quoteWhole`、`whenMissing`、`defaultValue`、`skills`、`guide` 及模板级 `overrides` | 除明确 `overrides` 覆写外全库共享一致语义，保障 33 套模板零漂移 |
| `TemplateIds` & `TemplateDescriptions` | `tools/java_migration/{template_ids,template_descriptions}.yaml` | 锁定 `100`～`132` 编号与 Java 编码映射及逐模板业务适用场景说明 | 严格一一对应 33 套线上模板，禁止重排或与测试模板 `1001` 混放 |
| AST 门禁检查器（S8 & S9） | `tools/java_migration/verify_structure.py` | `check_s8_placeholder_if_guards` 与 `check_s9_enum_compare_literals` 解析 `body.md.j2` 抽象语法树 | `placeholder` 字段条件若未安全排除占位符字面量立即阻断；未登记枚举失配立即阻断 |
| `KNOWN_UPSTREAM_ENUM_MISMATCHES` | `tools/java_migration/verify_structure.py` | 登记 `(116, "受理渠道")` 的 5 个上游历史渠道字面量白名单 | 仅允许打印提示并追踪于 `wiki/lint/open-questions.md`，不得放行新失配 |
| `_SubpathPrefixMiddleware` | `src/report_agent/main.py` | ASGI 中间件，依据 `Settings.normalized_root_path()` 兼容根路径与反代子路径挂载 | 仅对精确 `/prefix` 发 `307` 重定向至 `/prefix/`，对 `/prefix/*` 同步重写 `path` 与 `raw_path` |
| `WikiFrontmatter` 规范 | `wiki/SCHEMA.md` | 约束 `wiki/` 下 44 篇带头页面的 `title`/`type`/`tags`/`sources`/`updated` 及底部分享 `## 相关页面` | 禁止出现易变源码行号与真实密钥；`log.md` 严格只追加维护 |

### 3.2 状态机（如适用）

本需求聚焦静态资产自动化转换、离线对拍流水线、容器封装及文档沉淀，不涉及业务运行时状态机变更（模板 `r1` 导入及后续发布状态机复用 `002-git-store-hot-reload` 定义）。

---

## 4. 数据与存储设计（本需求范围） 【核心】

### 4.1 存储与缓存对象概览

| 对象/路径 | 变更类型 | 数据格式与字段要点 | 并发/清理/恢复策略 | 关联需求 |
| --- | --- | --- | --- | --- |
| `src/report_agent/seed/templates/100..132/` | 全量生成 | 33 组 `template.yaml` + `body.md.j2`（UTF-8 / LF 换行） | 由 `generate.py` 幂等全量覆盖重写，冷启动导入 `DATA_DIR/repo/` | FR-001, FR-002 |
| `src/report_agent/seed/{skills,apis,mock-gateway}/` | 迁移生成 | 11 套填报 `SKILL.md`（+1 路由 Skill）、3 套 XML YAML 契约、6 份脱敏 XML | 随包版本号版本化管理；单测隔离至 `tests/fixtures/seed/` 防污染 | FR-002, FR-003 |
| `wiki/` 46 篇文档与 `log.md` | 新增沉淀 | Markdown + YAML frontmatter + 相对路径互链 | 只追加 `log.md` 审计历史；变更需遵循 `SCHEMA.md` 校验 | FR-008 |
| 容器 `/data` 持久化挂载目录 | 部署映射 | 对应环境变量 `DATA_DIR=/data` | 容器构建属主赋予 `paasopt:paasopt`，挂载外部 PVC 确保无状态容器可重启恢复 | FR-007 |

---

<a id="plan-contracts"></a>

## 5. 接口与契约设计（API / Tools / Events） 【核心】

### 5.1 接口与契约清单

| 契约编号 | 类型 | 名称 / Path | 方向 | 关键入参 / 载荷 | 关键出参 / 响应 / 事件 | 鉴权与幂等 | 关联需求 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CLI-01 | CLI | `uv run python tools/java_migration/generate.py [--out DIR]` | 工程师 → 本地生成器 | Java 源路径（`JAVA_AGENT_HOME`）+ 本地字典 YAML | 33 套双文件模板 + `TEMPLATES.md` | 幂等重写 | FR-001 |
| CLI-02 | CLI | `uv run python tools/java_migration/verify_structure.py [--resources DIR]` | 工程师/CI → S1~S9 校验 | 目标 `seed` 资源目录 | 校验结果摘要 + `ℹ` 白名单提示 + 退出码 `0/1` | 只读幂等 | FR-004 |
| CLI-03 | CLI | `uv run python tools/java_migration/verify_render.py [--report FILE]` | 工程师/CI → Pebble 对拍 | 目标资源目录 + Java `PebbleRenderHarness` | 33 模板多场景逐字比对结果 + JSON diff 报告 | 只读幂等（依赖 JDK） | FR-005 |
| CLI-04 | CLI | `uv run python tools/java_migration/check_skills.py` | 工程师/CI → 报文/Skill 对拍 | `STAGING` 目录 + Java Harness（可选） | XML 逐字对拍 + Mock 检查 + 11 Skill 模拟 + 7 项修复断言 | 只读幂等（缺 JDK 自动跳过对照） | FR-005 |
| CLI-05 | CLI | `uv run python tools/java_migration/smoke_run.py [template_id]` | 工程师 → 临时沙箱冒烟 | 模板编号（默认 `101`）+ 测试用例 `C-01` | 运行状态 JSON + 字段取值列表 + 报告原文 | 临时副本隔离执行完毕销毁 | FR-005 |
| API-XML-01~03 | 网关契约 | `querySMSSendInfo` / `BOSS_QryBalanceFlowLog` / `cc_pretty_num_info_query` | 平台 → 统一网关 | 按 YAML `input` Schema（`${$now}` 注入时间） | `records` 列与 `no_data` / `failure` 判定 | `idempotent: true`、`retry.maxAttempts: 1` | FR-002, FR-003 |
| HTTP-MW-01 | ASGI 中间件 | `_SubpathPrefixMiddleware` | Nginx 反代 → FastAPI | `APP_ROOT_PATH` 配置前缀下的请求 `scope` | `/prefix` → `307 /prefix/`；`/prefix/*` 剥离前缀透传 | 无状态请求级改写 | FR-007 |

### 5.2 关键契约说明与错误语义

- `cc_pretty_num_info_query.yaml` 配置 `response.success.missingAs: failure`：当顶层网关返回 `<resp_code>9999</resp_code>` 且响应体缺失 `<content><ret_code>` 节点时，强制判定为接口故障（`ok=False`）而非“无数据”，防止网关超时被误判成“非靓号”。
- `docker-entrypoint.sh` 启动脚本检测 `LLM_API_KEY` 未设置或为 `dummy` 时仅输出中文提醒警告而不中断 Mock/工作台初始化；`cli.py` 与 entrypoint 强制固定 `workers=1` 确保进程内单写者并发模型不被破坏。

---

## 6. 业务流程设计（可直接编码） 【核心】

### 6.1 核心执行流程

```text
# 阶段一：资产迁移与四层对拍流
1. analyze_java.py 解析前代 .md / .rule / field-mappings.yml / skills 依赖 -> 校准 field_catalog.yaml 与 template_ids.yaml。
2. generate.py 读取配置字典 -> 执行 pebble_to_jinja（elseif->elif, null->none, LF 及模板 115 守卫）-> 推导 visible/inputs/evidence -> 生成 seed/templates/100..132/ 与 TEMPLATES.md。
3. 编制升级 11 个纯文本 SKILL.md 与 3 个 XML 契约及 6 份 Mock 样例 -> 依次通过 verify_structure.py (S1~S9)、verify_render.py (Pebble)、check_skills.py (XML/Groovy/7项修复) 与 smoke_run.py 验证，由 tests/test_migrated_seed.py 持续护航。

# 阶段二：容器一体化打包与反代流量流
1. Docker 构建：Node 22 (VITE_BASE_PATH=./ 编译多入口 index+embed) -> Python 3.13 + uv 0.7 (frozen 依赖) -> 运行镜像 (git + tzdata + USER 2000 + /data)。
2. 入口 docker-entrypoint.sh 校验变量后 exec report-agent serve (workers=1, proxy_headers=True)。
3. 请求到达 -> 若设 APP_ROOT_PATH，_SubpathPrefixMiddleware 对 /prefix 返回 307 /prefix/，对 /prefix/* 剥离 path/raw_path 后交由 FastAPI 路由与 StaticFiles SPA 处理。
```

### 6.2 并发控制与异常降级策略

| 异常/并发场景 | 检测时机 | 处理策略 | 是否中断主流程 | 可观测性输出 |
| --- | --- | --- | --- | --- |
| 宿主机缺失 JDK 或 Java 编译产物 | `test_migrated_seed.py` / `check_skills.py` 运行期 | `@pytest.mark.skipif` 跳过外部 Harness 用例，无条件执行 Python 自研回归与缺陷防线验证 | 否 | pytest 打印跳过原因与全套内置校验结果 |
| 模板正文存在无防护 placeholder 条件分支 | `verify_structure.py` S8 AST 扫描 | 阻断校验并返回非 0 退出码，提示缺失 `!= "{{字段名}}"` 守卫的具体行号 | 是（阻断门禁） | 明确报错行号与修复建议 |
| `body.md.j2` 枚举比较出现未登记异常字面量 | `verify_structure.py` S9 AST 扫描 | 命中模板 `116` 白名单打印 `ℹ` 提示，其他任意未知比较字面量直接阻断报错 | 是（未知失配） | 打印违规字段、字面量与合法枚举集合 |
| 容器冷启动缺少真实 LLM 密钥 | `docker-entrypoint.sh` 启动阶段 | 打印警告提示 `LLM_API_KEY 未配置或仍为默认值`，继续启动允许进工作台/Mock 调试 | 否 | 容器标准输出打印显式中文启动汇总与警告 |

---

## 7. 权限与安全控制（本需求范围） 【补充】

| 控制点 | 适用角色/调用方 | 校验机制与边界 |
| --- | --- | --- |
| 容器非 root 用户隔离 | 生产容器运行时 | `Dockerfile` 创建 `paasopt` 用户（UID `2000`）并通过 `USER 2000` 降权运行，仅授权 `/app` 与 `/data` 目录 |
| 构建上下文敏感目录屏蔽 | Docker 镜像构建流水线 | `.dockerignore` 显式剔除 `.git`、`.env`、`data`、`tests`、`tools`、`wiki` 与 `node_modules` |
| 反代可信来源控制 | Nginx / 反向代理链路 | `cli.py` 通过 `forwarded_allow_ips=settings.forwarded_allow_ips` 显式声明信任的代理 IP |
| 知识库与示例配置脱敏 | `wiki/` 与 `.env.example` | 严禁出现任何真实 `LLM_API_KEY`、工作台口令哈希或现网客户敏感信息 |

---

## 8. 前端 / 交互设计（如适用） 【补充】

本需求不涉及新增或修改前端 UI 页面与交互组件（前端多入口构建通过 `Dockerfile` 阶段 1 `ARG VITE_BASE_PATH=./` 输出相对路径静态产物，使 `index.html` 与 `embed.html` 原生兼容 `_SubpathPrefixMiddleware` 所承载的根路径与任意反代子路径，无须硬编码静态前缀）。

---

## 9. 配置与热更新开关 【补充】

| 配置项（Env / RuntimeConfig） | 类型 | 默认值 | 是否支持热更新 | 说明 |
| --- | --- | --- | --- | --- |
| `VITE_BASE_PATH` | `str`（构建参数） | `./` | 否（前端编译期） | 控制 Vite 资源引用前缀，默认相对路径适配任意反代子路径 |
| `APP_ROOT_PATH` | `str` | `""` | 否（应用启动期） | 反代挂载子路径前缀（如 `/agent`），非空时激活 `_SubpathPrefixMiddleware` |
| `FORWARDED_ALLOW_IPS` | `str` | `"127.0.0.1"` | 否（Uvicorn 启动期） | 信任的反代 IP 列表（反代/容器场景配 `*` 或网段） |
| `DATA_DIR` / `FRONTEND_DIST` | `Path` | `/data` / `/app/frontend/dist` | 否（启动期不变量） | 容器内数据卷与托管静态资源路径（详见 `.env.example` 与 `Dockerfile`） |

---

## 10. 测试设计（Test Strategy） 【核心】

### 10.1 测试范围与分层策略

| 测试类型 | 覆盖范围 | 桩/隔离策略 | 重点验证场景 |
| --- | --- | --- | --- |
| 静态结构与 AST 门禁 | 33 模板、12 Skill、3 契约与 Java 原模板对比 | 只读本地文件 + Jinja2 AST 解析 | `verify_structure.py` S1～S9（含模板 `115` S8 守卫与模板 `116` S9 白名单） |
| 渲染与报文/Groovy 黄金对拍 | 33 模板千级组合渲染、3 套 XML 报文、11 个 Skill 与 7 项修复断言 | `PebbleRenderHarness` / `JavaXmlRequestHarness` / `JavaSkillGoldenHarness`（可选 JDK）+ `MockGatewayClient` | 渲染零非预期差异、XML 逐字一致、R2/R4/R5/R7/R8/R17 缺陷防线 |
| 端到端回归套件 | `src/report_agent/seed/` 全量资产与修复断言 | `PROD_SEED_DIR` 显式加载 + `skipif` 跨环境兼容 + 不污染 `conftest.py` | `tests/test_migrated_seed.py` 全量回归（零警告、template-router、修复分支） |
| 沙箱真模型冒烟 | 临时复制的数据目录与指定模板端到端试跑 | `tmp` 沙箱目录 + `gateway_mode="mock"` | `smoke_run.py 101` 真实 LLM 输出（仅在配置真实 `LLM_API_KEY` 时手动执行） |

### 10.2 回归范围

- 全量测试套件 `uv run pytest -q`（共 196 条用例，含 `tests/test_migrated_seed.py`）。
- 后端静态代码检查 `uvx ruff@0.11.0 check src tests`。
- 迁移结构与 AST 专项脚本 `uv run python tools/java_migration/verify_structure.py`。

<a id="plan-quickstart"></a>

### 10.5 验证指南

- **环境与前置条件**：Python 3.13 + `uv`；运行完整外部 Java 对拍（`verify_render.py` 与 `check_skills.py` 对拍段）需本机具备 JDK 21、Maven 本地仓库依赖及 `JAVA_AGENT_HOME` 源码编译产物；运行 `smoke_run.py` 需配置有效 `LLM_API_KEY`。
- **验证命令**：
  ```bash
  # 1. 结构、规则、发布零警告与 S8/S9 AST 静态门禁验证（无需外部大模型）
  uv run python tools/java_migration/verify_structure.py

  # 2. 全量自动化测试与生产 seed 回归（在无 JDK 环境时自动 skipif 跳过外部 Java Harness 并执行全套内置断言）
  uv run pytest -q

  # 3. Python 静态代码规范检查
  uvx ruff@0.11.0 check src tests

  # 4. 仅在具备 JDK 21 与 Java 编译产物时单独执行渲染与 Groovy 对拍：
  uv run python tools/java_migration/verify_render.py
  uv run python tools/java_migration/check_skills.py

  # 5. 仅在配置了有效外网/内网 LLM 时执行临时沙箱端到端冒烟：
  uv run python tools/java_migration/smoke_run.py 101
  ```
- **预期结果**：`verify_structure.py` 输出 `检查模板 33 个，Skill 12 个，接口 3 个；发布校验 error 0 条，warning 0 条` 与 S8/S9 全通；`pytest` 196 passed；`ruff` 0 告警。

---

## 11. NFR 符合性自检 【核心】

| 自检主题 | 宪章依据 | 是否涉及 | 落实位置与验证方式 |
| --- | --- | --- | --- |
| 零业务硬编码与资源隔离 | I | 是 | 全部规则迁移至 `seed/templates/`、`seed/skills/`、`seed/apis/` 与 `system-prompt.md` |
| 强证据防幻觉与确定性计算 | II | 是 | 11 Skill 改用 12 原语；S8/S9 AST 与空列表防线阻止占位符恒真与假证据；`verify_structure.py` 与 `test_migrated_seed.py` 验证 |
| 文件化存储与 `workers=1` 并发安全 | III | 是 | `cli.py` 与 `docker-entrypoint.sh` 硬锁 `workers=1`，`Dockerfile` 预装 `git` 并挂 `/data` |
| 安全编码、脱敏与零凭据硬编码 | VI | 是 | 非 root `USER 2000`、`.dockerignore` 屏蔽 `.env`、`.env.example` 与 46 篇 `wiki/` 零密钥 |
| 知识库与可复现回归测试 | V、IX | 是 | `tests/test_migrated_seed.py` 自适应兼容跨环境运行；46 篇 `wiki/` 按 `SCHEMA.md` 同步落地 |

---

## 12. 发布与回退计划 【核心】

- **发布前置与步骤**：通过 `verify_structure.py`、`pytest`、`ruff` 与前端构建验证 → 触发 `.github/workflows/docker-image.yml` 或本地 `docker build` 构建一体镜像 → 挂载 PVC `/data`、配置 `.env`（含可选 `APP_ROOT_PATH` / `FORWARDED_ALLOW_IPS`）以非 root UID `2000` 单进程启动 → 探测 `/healthz` 返回 `UP`。
- **回退方案**：镜像回滚切换前一稳定 Tag；运行期模板或接口缺陷可通过工作台「版本发布」切换 `releases/current` 至上一 `rN`；反代子路径异常可将 `APP_ROOT_PATH` 置空恢复根路径模式。

---

## 13. 实施切片与建议顺序（Implementation Slices） 【核心】

| 切片 ID | 切片名称 | 对应 Phase / 任务范围 | 目标与涉及文件 | 核算工时（如适用） |
| --- | --- | --- | --- | --- |
| S-01 | Java 原资产分析与映射建库 | Phase 1（`T001`–`T002`） | `tools/java_migration/{analyze_java.py,README.md,MAPPING.md,template_ids.yaml,template_descriptions.yaml}` | 2.5 人天 |
| S-02 | 配置驱动生成器与 Java 黄金 Harness 底座 | Phase 2（`T003`–`T004`） | `tools/java_migration/{field_catalog.yaml,generate.py}`、`tools/java_migration/harness/*.java` | 3.5 人天 |
| S-03 | 33 模板、11 Skill、3 契约迁修与缺陷治理（MVP） | Phase 3 / US1（`T005`–`T007`） | `src/report_agent/seed/{templates/100..132,skills,apis,mock-gateway}/`、`TEMPLATES.md` | 5.5 人天 |
| S-04 | 四层黄金对拍脚本与自适应回归测试（MVP） | Phase 4 / US2（`T008`–`T009`） | `tools/java_migration/{verify_structure,verify_render,check_skills,smoke_run}.py`、`tests/test_migrated_seed.py` | 3.5 人天 |
| S-05 | 一体化非 root 容器、反代子路径与 46 篇 Wiki | Phase 5 / US3（`T010`–`T011`） | `Dockerfile`、`docker-entrypoint.sh`、`.dockerignore`、`.env.example`、`.github/workflows/docker-image.yml`、`main.py`/`config.py`/`cli.py`、`wiki/`（46 篇） | 2.5 人天 |
| S-06 | 迁移回归门禁、台账与 Wiki 审计收口 | Phase 6 / Polish（`T012`） | `tools/java_migration/`、`tests/test_migrated_seed.py`、`wiki/index.md`、`wiki/log.md` | 1.5 人天 |
| **合计** | **全周期设计切片总计** | **Phase 1–6（12 项任务）** | **完成 33 模板/11 Skill/3 契约迁修、四层对拍、一体容器与 46 篇 Wiki 交付** | **19.0 人天** |

---

## 14. 风险清单与缓解（Risks） 【补充】

| 风险 ID | 风险描述 | 影响 | 概率 | 缓解措施 |
| --- | --- | --- | --- | --- |
| R-1 | 生产环境容器以多 Worker 启动破坏单进程文件锁与内存对话通道 | 高 | 中 | `cli.py` 硬写死 `workers=1` 且 `docker-entrypoint.sh` 明确提示强制单进程运行 |
| R-2 | 外部 Java 工程或 JDK 缺失导致 CI 无法执行逐字对比测试阻断交付 | 中 | 高 | `test_migrated_seed.py` 采用 `@pytest.mark.skipif` 仅跳过外部 Harness 用例，无条件执行全量内置校验与缺陷防线测试 |
| R-3 | 占位符字段条件分支遗漏排除字面量造成隐蔽恒真渲染偏差 | 高 | 中 | `verify_structure.py` S8 AST 门禁扫描全库 `nodes.If` 阻断未排除占位符的真值判断 |
| R-4 | 模板 `116` 历史渠道枚举失配被误当新增 bug 掩盖或误放新失配 | 低 | 中 | S9 门禁使用显式 `KNOWN_UPSTREAM_ENUM_MISMATCHES` 白名单精准隔离，并转记 `Q-001` 待业务确认 |

---

## 15. 待确认事项（Design Open Questions） 【补充】

| 编号 | 问题摘要 | 对应 Spec Q-* | 当前结论 | 状态 |
| --- | --- | --- | --- | --- |
| DQ-1 | 模板 `116` 第 38 行 5 个历史渠道字面量业务收敛口径与 `retry.maxAttempts` / `.rule` 孤立规则 / 充值单位确认 | `Q-001`、`Q-002` | 技术实现已采用 S9 白名单隔离与等价兼容方案运行并挂账于 `wiki/lint/open-questions.md`，不阻塞工程交付与发布 | 待业务确认（非工程阻塞） |

---

## 附录 A：核心字段与状态约定（仅本需求）

- **静态对拍门禁（`S1`～`S9`）**：`S1` 模板ID映射、`S2` 正文逐字转换、`S3` 字段与 `visible` 属性、`S4` 非空取值说明、`S5` Skill/API 完整性、`S6` 循环列、`S7` `validate_all()` 0 error/0 warning、`S8` 占位符条件 AST 守卫、`S9` 枚举比较字面量 AST 校验。
- **重点历史缺陷编号（`MAPPING.md`）**：`R2`（活动编号误算日期及无到期日跳过）、`R4`（列表 0 行 `found: []` vs 缺失）、`R5`（靓号号码比对/空 `grade`/多档拼接/顶层故障拦截）、`R7`（同名 `客户号码` 入参告警消除）、`R8`（纯年月正则回溯）、`R17`（模板 `120`/`111`/`114`/`115` 占位符死分支）。

## 附录 B：AI 编码与交付约束

1. 修改 `field_catalog.yaml` 或 `generate.py` 后必须运行 `generate.py`、`verify_structure.py` 与 `pytest tests/test_migrated_seed.py` 校验 0 error / 0 warning。
2. `wiki/` 更新须严格遵守 `wiki/SCHEMA.md`，禁止引入源码行号与真实凭据，且不得突破 `AGENTS.md` 规定未经允许自动提交代码。

---

## 变更记录（Changelog）

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | AiCoding (codex) | 基于初期设计模板完成 008 技术实施归档 |
| 2.0 | 2026-11-16 | AiCoding (codex) | 按改造后 `inline-v1` 单文件内联设计模板重构，补齐 4 个锚点与 15 章架构设计，核对 S1～S9、`verify_structure.py` 实测结果及 46 篇 Wiki 与容器反代方案 |
