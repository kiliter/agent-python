"""Java 对拍环境路径与依赖 Classpath 统一解析模块。

#Created By AiCoding(codex)
统一管理 JAVA_AGENT_HOME 目录推导、Java Harness 按源码 mtime 增量编译，以及依赖 Jar 发现：
1. 优先复用 Java 工程打包目录（如 release/windows/pdf-agent-parse-windows/lib/*）通配加载；
2. 本地未生成 release 包时，自动回退扫描 ~/.m2/repository（或 MAVEN_REPO）下对应构件的最新版本 Jar，
   避免在多个脚本中重复硬编码易过期的补丁版本号。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

DEFAULT_JAVA_AGENT_HOME = "/Users/zhangjialin/IdeaProjects/agent"


def get_java_agent_home() -> Path:
    """读取前代 Java 仓库根目录（支持 JAVA_AGENT_HOME 环境变量覆盖）。"""
    return Path(os.environ.get("JAVA_AGENT_HOME", DEFAULT_JAVA_AGENT_HOME))


JAVA_AGENT = get_java_agent_home()
JAVA_RES = JAVA_AGENT / "pdf-agent-parse/src/main/resources"
JAVA_TPL_DIR = JAVA_RES / "template/md"
JAVA_RULE_DIR = JAVA_RES / "agent/rule"
JAVA_SKILL_DIR = JAVA_RES / "agent/skills"
JAVA_FIELD_MAPPINGS = JAVA_RES / "agent/config/field-mappings.yml"
JAVA_CLASSES = JAVA_AGENT / "pdf-agent-parse/target/classes"

# 回退本地 Maven 仓库时所需的构件坐标（group_path, artifact_id）
_M2_CORE_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("tools/jackson/core", "jackson-core"),
    ("tools/jackson/core", "jackson-databind"),
    ("tools/jackson/dataformat", "jackson-dataformat-xml"),
    ("com/fasterxml/jackson/core", "jackson-annotations"),
    ("com/fasterxml/woodstox", "woodstox-core"),
    ("org/codehaus/woodstox", "stax2-api"),
    ("org/springframework", "spring-webflux"),
    ("org/springframework", "spring-web"),
    ("org/springframework", "spring-core"),
    ("io/projectreactor", "reactor-core"),
    ("org/reactivestreams", "reactive-streams"),
    ("org/slf4j", "slf4j-api"),
    ("org/apache/groovy", "groovy"),
    ("org/apache/groovy", "groovy-xml"),
    ("org/apache/groovy", "groovy-json"),
    ("org/apache/commons", "commons-lang3"),
    ("commons-logging", "commons-logging"),
)
_M2_PEBBLE_ARTIFACT = ("io/pebbletemplates", "pebble")
_M2_OPTIONAL_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("org/unbescape", "unbescape"),
)

_SKIP_CLASSIFIERS = ("-sources.jar", "-javadoc.jar", "-tests.jar", "-test-sources.jar")


def _version_sort_key(version: str) -> list[tuple[int, int | str]]:
    """按自然数字分段比较 Maven 版本号，确保 3.1.10 > 3.1.4。"""
    key: list[tuple[int, int | str]] = []
    for part in re.split(r"(\d+)", version):
        if not part:
            continue
        if part.isdigit():
            key.append((1, int(part)))
        else:
            key.append((0, part))
    return key


def _find_latest_m2_jar(m2_root: Path, group_path: str, artifact_id: str) -> Path | None:
    """在本地 Maven 仓库中查找指定构件最新版本的二进制 Jar。"""
    art_dir = m2_root / group_path / artifact_id
    if not art_dir.is_dir():
        return None
    candidates: list[tuple[list[tuple[int, int | str]], Path]] = []
    for ver_dir in art_dir.iterdir():
        if not ver_dir.is_dir():
            continue
        jar = ver_dir / f"{artifact_id}-{ver_dir.name}.jar"
        if jar.is_file() and not any(jar.name.endswith(suf) for suf in _SKIP_CLASSIFIERS):
            candidates.append((_version_sort_key(ver_dir.name), jar))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def _candidate_lib_dirs(java_agent: Path) -> tuple[Path, ...]:
    """返回候选的本地已打包 Java 依赖 lib 目录（按优先级排列）。"""
    return (
        java_agent / "release/windows/pdf-agent-parse-windows/lib",
        java_agent / "release/linux/pdf-agent-parse-linux/lib",
        java_agent / "pdf-agent-parse/target/lib",
        java_agent / "pdf-agent-parse/target/dependency",
    )


def resolve_java_dep_entries(
    java_agent: Path | None = None,
    *,
    m2_repo: Path | None = None,
    require_pebble: bool = False,
) -> list[str] | None:
    """解析 Java 第三方依赖 classpath 项列表（优先打包 lib/*，回退 ~/.m2/repository）。"""
    base = java_agent or get_java_agent_home()
    for lib_dir in _candidate_lib_dirs(base):
        if not lib_dir.is_dir():
            continue
        has_jars = any(lib_dir.glob("*.jar"))
        if not has_jars:
            continue
        if require_pebble and not any(lib_dir.glob("pebble-*.jar")):
            continue
        return [f"{lib_dir}/*"]

    m2 = m2_repo or Path(os.environ.get("MAVEN_REPO", str(Path.home() / ".m2/repository")))
    if not m2.is_dir():
        return None
    required = list(_M2_CORE_ARTIFACTS)
    if require_pebble:
        required.append(_M2_PEBBLE_ARTIFACT)
    resolved: list[str] = []
    for group_path, artifact_id in required:
        jar = _find_latest_m2_jar(m2, group_path, artifact_id)
        if jar is None:
            return None
        resolved.append(str(jar))
    for group_path, artifact_id in _M2_OPTIONAL_ARTIFACTS:
        opt_jar = _find_latest_m2_jar(m2, group_path, artifact_id)
        if opt_jar is not None:
            resolved.append(str(opt_jar))
    return resolved


def resolve_java_classpath(
    java_agent: Path | None = None,
    *,
    require_javac: bool = False,
    require_pebble: bool = False,
) -> str | None:
    """拼接 target/classes 与第三方依赖的完整 Java classpath；环境不具备时返回 None。"""
    if shutil.which("java") is None:
        return None
    if require_javac and shutil.which("javac") is None:
        return None
    base = java_agent or get_java_agent_home()
    classes = base / "pdf-agent-parse/target/classes"
    if not classes.is_dir():
        return None
    deps = resolve_java_dep_entries(base, require_pebble=require_pebble)
    if not deps:
        return None
    return os.pathsep.join([str(classes), *deps])


def has_java_render_env(java_agent: Path | None = None) -> bool:
    """检查当前宿主机是否同时具备 JDK、PebbleTemplateEngine 编译产物与 Java 依赖目录。"""
    base = java_agent or get_java_agent_home()
    if not (base / "pdf-agent-parse/target/classes/com/agile/agent/pdf/parse/template").is_dir():
        return False
    return resolve_java_classpath(base, require_javac=True, require_pebble=True) is not None


def compile_java_harness(src_file: Path, build_dir: Path, cp: str) -> str:
    """按 .java 与 .class 的 st_mtime 增量编译指定 Harness，返回包含 build_dir 的运行期 classpath。"""
    class_file = build_dir / f"{src_file.stem}.class"
    need_compile = (
        not class_file.is_file()
        or src_file.stat().st_mtime > class_file.stat().st_mtime
    )
    if need_compile:
        build_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["javac", "-encoding", "UTF-8", "-cp", cp, "-d", str(build_dir), str(src_file)],
            check=True,
            capture_output=True,
        )
    return f"{build_dir}{os.pathsep}{cp}"
