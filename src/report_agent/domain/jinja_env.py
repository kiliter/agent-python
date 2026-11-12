"""模板正文使用的 Jinja2 环境，以及带“使用追踪”的渲染。

#Created By AiCoding(codex)
渲染时每个字段值包装成 TrackedValue（str 子类），{{ }} 输出时经过 finalize 记录字段名，
这样可以知道最终报告实际展示了哪些字段，用来判断 SUCCESS / PARTIAL。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from jinja2 import Environment, StrictUndefined, TemplateSyntaxError, Undefined, meta, nodes
from jinja2.compiler import CodeGenerator, Frame
from jinja2.exceptions import SecurityError
from jinja2.sandbox import ImmutableSandboxedEnvironment
from jinja2.utils import missing as _jinja_missing


class TrackedValue(str):
    """带字段名的字符串值，比较、拼接（~ 与 +）及常见字符串过滤后仍保留全部关联字段名追踪。"""

    field_name: str
    field_names: tuple[str, ...]
    missing: bool

    def __new__(
        cls,
        value: str,
        field_name: str,
        missing: bool = False,
        *,
        field_names: Iterable[str] | None = None,
    ) -> "TrackedValue":
        obj = super().__new__(cls, value)
        names = tuple(dict.fromkeys([*(field_names or ()), *([field_name] if field_name else [])]))
        obj.field_name = names[0] if names else field_name
        obj.field_names = names
        obj.missing = missing
        return obj

    def _wrap(
        self,
        value: str,
        *,
        extra_names: Iterable[str] = (),
        extra_missing: bool = False,
    ) -> "TrackedValue":
        merged = tuple(dict.fromkeys([*self.field_names, *extra_names]))
        primary = merged[0] if merged else self.field_name
        return TrackedValue(value, primary, self.missing or extra_missing, field_names=merged)

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

    def __add__(self, other: Any) -> "TrackedValue":
        if isinstance(other, TrackedValue):
            return self._wrap(
                str.__add__(self, other),
                extra_names=other.field_names,
                extra_missing=other.missing,
            )
        if isinstance(other, Undefined):
            other_str = str(other)
            uname = (
                str(other._undefined_name)
                if (other._undefined_obj is _jinja_missing and other._undefined_name)
                else ""
            )
            return self._wrap(
                str.__add__(self, other_str),
                extra_names=(uname,) if uname else (),
                extra_missing=True,
            )
        if isinstance(other, str):
            return self._wrap(str.__add__(self, other))
        return NotImplemented

    def __radd__(self, other: Any) -> "TrackedValue":
        if isinstance(other, TrackedValue):
            return other.__add__(self)
        if isinstance(other, Undefined):
            other_str = str(other)
            uname = (
                str(other._undefined_name)
                if (other._undefined_obj is _jinja_missing and other._undefined_name)
                else ""
            )
            names = tuple(dict.fromkeys([*([uname] if uname else []), *self.field_names]))
            return TrackedValue(
                str.__add__(other_str, self),
                names[0] if names else self.field_name,
                True,
                field_names=names,
            )
        if isinstance(other, str):
            return self._wrap(str.__add__(other, self))
        return NotImplemented


class _PlaceholderUndefined(Undefined):
    """顶层未定义变量在条件中视为假，直接输出时渲染为 {{变量名}} 占位符；对象属性缺失仍报错。"""

    def __str__(self) -> str:
        if self._undefined_obj is _jinja_missing and self._undefined_name:
            return "{{" + str(self._undefined_name) + "}}"
        self._fail_with_undefined_error()


class _TrackedCodeGenerator(CodeGenerator):
    """重写 ~ 拼接与 + 运算，避免 CPython str_join / str.__add__ 剥离 TrackedValue 追踪信息。"""

    def visit_Concat(self, node: nodes.Concat, frame: Frame) -> None:
        self.write("environment._tracked_concat((")
        for arg in node.nodes:
            self.visit(arg, frame)
            self.write(", ")
        self.write("))")

    def visit_Add(self, node: nodes.Add, frame: Frame) -> None:
        self.write("environment._tracked_add(")
        self.visit(node.left, frame)
        self.write(", ")
        self.visit(node.right, frame)
        self.write(")")


class _TrackedSandboxEnvironment(ImmutableSandboxedEnvironment):
    code_generator_class = _TrackedCodeGenerator
    _strict_undefined: bool = False

    def _tracked_concat(self, seq: Iterable[Any]) -> str:
        parts: list[str] = []
        names: list[str] = []
        any_missing = False
        for item in seq:
            if isinstance(item, Undefined):
                if self._strict_undefined or item._undefined_obj is not _jinja_missing or not item._undefined_name:
                    item._fail_with_undefined_error()
                uname = str(item._undefined_name)
                parts.append("{{" + uname + "}}")
                if uname not in names:
                    names.append(uname)
                any_missing = True
            elif isinstance(item, TrackedValue):
                parts.append(str.__str__(item))
                for fn in item.field_names:
                    if fn not in names:
                        names.append(fn)
                if item.missing:
                    any_missing = True
            elif item is None:
                parts.append("")
            else:
                parts.append(str(item))
        joined = "".join(parts)
        if names:
            return TrackedValue(joined, names[0], missing=any_missing, field_names=names)
        return joined

    def _tracked_add(self, left: Any, right: Any) -> Any:
        if not self._strict_undefined:
            if isinstance(left, Undefined) and left._undefined_obj is _jinja_missing and left._undefined_name and isinstance(right, (str, Undefined)):
                uname = str(left._undefined_name)
                left = TrackedValue("{{" + uname + "}}", uname, missing=True)
            if isinstance(right, Undefined) and right._undefined_obj is _jinja_missing and right._undefined_name and isinstance(left, str):
                uname = str(right._undefined_name)
                right = TrackedValue("{{" + uname + "}}", uname, missing=True)
        if isinstance(left, TrackedValue):
            res = left.__add__(right)
            if res is not NotImplemented:
                return res
        if isinstance(right, TrackedValue):
            res = right.__radd__(left)
            if res is not NotImplemented:
                return res
        return left + right


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
            used.update(value.field_names)
        return "" if value is None else value

    env = _TrackedSandboxEnvironment(
        autoescape=False,
        keep_trailing_newline=True,
        undefined=StrictUndefined if strict_undefined else _PlaceholderUndefined,
        finalize=finalize,
    )
    env._strict_undefined = strict_undefined
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
