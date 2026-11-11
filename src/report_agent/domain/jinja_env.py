"""模板正文使用的 Jinja2 环境，以及带“使用追踪”的渲染。

#Created By AiCoding(codex)
渲染时每个字段值包装成 TrackedValue（str 子类），{{ }} 输出时经过 finalize 记录字段名，
这样可以知道最终报告实际展示了哪些字段，用来判断 SUCCESS / PARTIAL。
"""

from __future__ import annotations

from typing import Any

from jinja2 import Environment, StrictUndefined, TemplateSyntaxError, Undefined, meta, nodes
from jinja2.exceptions import SecurityError
from jinja2.sandbox import ImmutableSandboxedEnvironment
from jinja2.utils import missing as _jinja_missing


class TrackedValue(str):
    """带字段名的字符串值，比较、拼接及常见字符串过滤后仍保留字段名追踪。"""

    field_name: str
    missing: bool

    def __new__(cls, value: str, field_name: str, missing: bool = False) -> "TrackedValue":
        obj = super().__new__(cls, value)
        obj.field_name = field_name
        obj.missing = missing
        return obj

    def _wrap(self, value: str) -> "TrackedValue":
        return TrackedValue(value, self.field_name, self.missing)

    def strip(self, chars: str | None = None) -> "TrackedValue":
        return self._wrap(super().strip(chars))

    def lstrip(self, chars: str | None = None) -> "TrackedValue":
        return self._wrap(super().lstrip(chars))

    def rstrip(self, chars: str | None = None) -> "TrackedValue":
        return self._wrap(super().rstrip(chars))

    def replace(self, old: str, new: str, count: int = -1) -> "TrackedValue":  # type: ignore[override]
        return self._wrap(super().replace(old, new, count))

    def lower(self) -> "TrackedValue":
        return self._wrap(super().lower())

    def upper(self) -> "TrackedValue":
        return self._wrap(super().upper())

    def title(self) -> "TrackedValue":
        return self._wrap(super().title())

    def __getitem__(self, key: Any) -> "TrackedValue":
        return self._wrap(super().__getitem__(key))


class _PlaceholderUndefined(Undefined):
    """顶层未定义变量在条件中视为假，直接输出时渲染为 {{变量名}} 占位符；对象属性缺失仍报错。"""

    def __str__(self) -> str:
        if self._undefined_obj is _jinja_missing and self._undefined_name:
            return "{{" + str(self._undefined_name) + "}}"
        self._fail_with_undefined_error()


def make_environment(used: set[str] | None = None, *, strict_undefined: bool = False) -> Environment:
    """创建沙箱化的 Jinja2 环境。传入 used 集合时，记录被输出的字段名。"""

    def finalize(value: Any) -> Any:
        if isinstance(value, Undefined):
            if strict_undefined or value._undefined_obj is not _jinja_missing or not value._undefined_name:
                value._fail_with_undefined_error()
            name = str(value._undefined_name)
            if used is not None:
                used.add(name)
            return "{{" + name + "}}"
        if used is not None and isinstance(value, TrackedValue):
            used.add(value.field_name)
        return "" if value is None else value

    env = ImmutableSandboxedEnvironment(
        autoescape=False,
        keep_trailing_newline=True,
        undefined=StrictUndefined if strict_undefined else _PlaceholderUndefined,
        finalize=finalize,
    )
    for unsafe_global in ("cycler", "joiner", "lipsum", "namespace"):
        env.globals.pop(unsafe_global, None)
    return env


_PARSE_ENV = make_environment()


class BodySyntaxError(ValueError):
    """正文语法错误，带行号。"""

    def __init__(self, message: str, lineno: int | None) -> None:
        super().__init__(message)
        self.lineno = lineno


def parse_body(body: str) -> nodes.Template:
    """解析正文语法，失败抛 BodySyntaxError。"""
    try:
        return _PARSE_ENV.parse(body)
    except TemplateSyntaxError as exc:
        raise BodySyntaxError(f"第 {exc.lineno} 行语法错误：{exc.message}", exc.lineno) from exc


def body_variables(body: str) -> set[str]:
    """正文中引用的全部变量（输出和条件判断都算）。"""
    return set(meta.find_undeclared_variables(parse_body(body)))


def printed_variables(body: str) -> set[str]:
    """正文中直接输出（{{ 变量 }}）的变量。"""
    tree = parse_body(body)
    undeclared = set(meta.find_undeclared_variables(tree))
    names: set[str] = set()
    for output in tree.find_all(nodes.Output):
        for node in output.find_all(nodes.Name):
            if node.ctx == "load" and node.name in undeclared:
                names.add(node.name)
    return names


def render_body(body: str, context: dict[str, Any], *, strict_undefined: bool = False) -> tuple[str, set[str]]:
    """渲染正文，返回（文本，实际输出的字段名集合）。"""
    used: set[str] = set()
    env = make_environment(used, strict_undefined=strict_undefined)
    try:
        template = env.from_string(body)
    except TemplateSyntaxError as exc:
        raise BodySyntaxError(f"第 {exc.lineno} 行语法错误：{exc.message}", exc.lineno) from exc
    try:
        text = template.render(**(context or {}))
    except SecurityError as exc:
        raise SecurityError(f"模板安全沙箱拦截：{exc}") from exc
    return text, used
