"""模板正文使用的 Jinja2 环境，以及带“使用追踪”的渲染。

#Created By AiCoding(codex)
渲染时每个字段值包装成 TrackedValue（str 子类），{{ }} 输出时经过 finalize 记录字段名，
这样可以知道最终报告实际展示了哪些字段，用来判断 SUCCESS / PARTIAL。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextvars import ContextVar
from functools import lru_cache, wraps
import re
from typing import Any

from jinja2 import Environment, StrictUndefined, Template as JinjaTemplate, TemplateSyntaxError, Undefined, meta, nodes
from jinja2.compiler import CodeGenerator, Frame
from jinja2.exceptions import SecurityError
from jinja2.ext import Extension
from jinja2.lexer import TOKEN_DATA, TOKEN_VARIABLE_END, Token, TokenStream
from jinja2.nodes import EvalContext
from jinja2.runtime import Context
from jinja2.sandbox import ImmutableSandboxedEnvironment
from jinja2.utils import missing as _jinja_missing

_ACTIVE_USED: ContextVar[set[str] | None] = ContextVar("_ACTIVE_USED", default=None)

# #Created By AiCoding(codex) Jinja2 保留关键字（禁止作为模板字段名/列名，供领域层与 API 层统一复用）
RESERVED_FIELD_NAMES: set[str] = {
    "true", "false", "none", "True", "False", "None",
    "if", "elif", "else", "endif", "for", "endfor", "in", "and", "or", "not", "is",
    "set", "block", "endblock", "macro", "endmacro", "call", "filter", "import", "from", "include", "extends",
}
_RESERVED_FIELD_NAMES = RESERVED_FIELD_NAMES


class TrackedList(list):
    """带字段名与缺失标记的列表值，仅在实际迭代（{% for %}）、下标/切片访问或直接输出时将字段名记入 used。

    #Created By AiCoding(codex)
    {% if 列表字段 %} 调用 bool(TrackedList)（走 __len__），不会触发 __iter__，因此不会误记为已展示；
    只有进入生效分支执行 {% for item in 列表字段 %}、切片/下标取值（或 {{ 列表字段 }} 输出）时才记录字段名。
    """

    field_name: str
    missing: bool

    def __init__(
        self,
        iterable: Iterable[Any] = (),
        field_name: str = "",
        missing: bool = False,
        *,
        on_iter: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(iterable)
        self.field_name = field_name
        self.missing = missing
        self._on_iter = on_iter

    def _mark_used(self) -> None:
        if self.field_name:
            if self._on_iter is not None:
                self._on_iter(self.field_name)
            active_used = _ACTIVE_USED.get()
            if active_used is not None:
                active_used.add(self.field_name)

    def __iter__(self) -> Iterator[Any]:
        self._mark_used()
        return super().__iter__()

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, slice):
            self._mark_used()
            return TrackedList(
                super().__getitem__(key),
                field_name=self.field_name,
                missing=self.missing,
                on_iter=self._on_iter,
            )
        item = super().__getitem__(key)
        self._mark_used()
        return item


class TrackedValue(str):
    """带字段名的字符串值，比较、拼接（~、+、% 格式化）及常见字符串过滤后仍保留全部关联字段名追踪。"""

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
        extra_names = new.field_names if isinstance(new, TrackedValue) else ()
        extra_missing = new.missing if isinstance(new, TrackedValue) else False
        return self._wrap(super().replace(old, new, count), extra_names=extra_names, extra_missing=extra_missing)

    def lower(self) -> "TrackedValue":
        return self._wrap(super().lower())

    def upper(self) -> "TrackedValue":
        return self._wrap(super().upper())

    def title(self) -> "TrackedValue":
        return self._wrap(super().title())

    def capitalize(self) -> "TrackedValue":
        return self._wrap(super().capitalize())

    def casefold(self) -> "TrackedValue":
        return self._wrap(super().casefold())

    def swapcase(self) -> "TrackedValue":
        return self._wrap(super().swapcase())

    def center(self, width: int, fillchar: str = " ") -> "TrackedValue":  # type: ignore[override]
        extra_names = fillchar.field_names if isinstance(fillchar, TrackedValue) else ()
        extra_missing = fillchar.missing if isinstance(fillchar, TrackedValue) else False
        return self._wrap(super().center(width, fillchar), extra_names=extra_names, extra_missing=extra_missing)

    def ljust(self, width: int, fillchar: str = " ") -> "TrackedValue":  # type: ignore[override]
        extra_names = fillchar.field_names if isinstance(fillchar, TrackedValue) else ()
        extra_missing = fillchar.missing if isinstance(fillchar, TrackedValue) else False
        return self._wrap(super().ljust(width, fillchar), extra_names=extra_names, extra_missing=extra_missing)

    def rjust(self, width: int, fillchar: str = " ") -> "TrackedValue":  # type: ignore[override]
        extra_names = fillchar.field_names if isinstance(fillchar, TrackedValue) else ()
        extra_missing = fillchar.missing if isinstance(fillchar, TrackedValue) else False
        return self._wrap(super().rjust(width, fillchar), extra_names=extra_names, extra_missing=extra_missing)

    def zfill(self, width: int) -> "TrackedValue":  # type: ignore[override]
        return self._wrap(super().zfill(width))

    def expandtabs(self, tabsize: int = 8) -> "TrackedValue":  # type: ignore[override]
        return self._wrap(super().expandtabs(tabsize))

    def removeprefix(self, prefix: str) -> "TrackedValue":  # type: ignore[override]
        return self._wrap(super().removeprefix(prefix))

    def removesuffix(self, suffix: str) -> "TrackedValue":  # type: ignore[override]
        return self._wrap(super().removesuffix(suffix))

    def partition(self, sep: str) -> tuple["TrackedValue", "TrackedValue", "TrackedValue"]:  # type: ignore[override]
        head, mid, tail = super().partition(sep)
        return (self._wrap(head), self._wrap(mid), self._wrap(tail))

    def rpartition(self, sep: str) -> tuple["TrackedValue", "TrackedValue", "TrackedValue"]:  # type: ignore[override]
        head, mid, tail = super().rpartition(sep)
        return (self._wrap(head), self._wrap(mid), self._wrap(tail))

    def split(self, sep: str | None = None, maxsplit: int = -1) -> list["TrackedValue"]:  # type: ignore[override]
        return [self._wrap(p) for p in super().split(sep, maxsplit)]

    def rsplit(self, sep: str | None = None, maxsplit: int = -1) -> list["TrackedValue"]:  # type: ignore[override]
        return [self._wrap(p) for p in super().rsplit(sep, maxsplit)]

    def splitlines(self, keepends: bool = False) -> list["TrackedValue"]:  # type: ignore[override]
        return [self._wrap(p) for p in super().splitlines(keepends)]

    def join(self, iterable: Iterable[Any]) -> "TrackedValue":
        items = list(iterable)
        names, any_missing = _collect_tracked_sources(items)
        return self._wrap(super().join(items), extra_names=names, extra_missing=any_missing)

    def format(self, *args: Any, **kwargs: Any) -> "TrackedValue":
        raw = super().format(*args, **kwargs)
        names, any_missing = _collect_tracked_sources((*args, *kwargs.values()))
        return self._wrap(raw, extra_names=names, extra_missing=any_missing)

    def format_map(self, mapping: Any) -> "TrackedValue":
        raw = super().format_map(mapping)
        names, any_missing = _collect_tracked_sources((mapping,))
        return self._wrap(raw, extra_names=names, extra_missing=any_missing)

    def __mod__(self, args: Any) -> "TrackedValue":
        raw = super().__mod__(args)
        names, any_missing = _collect_tracked_sources((args,))
        return self._wrap(raw, extra_names=names, extra_missing=any_missing)

    def __mul__(self, count: Any) -> "TrackedValue":
        res = super().__mul__(count)
        return self._wrap(res) if isinstance(res, str) else res  # type: ignore[return-value]

    def __rmul__(self, count: Any) -> "TrackedValue":
        res = super().__rmul__(count)
        return self._wrap(res) if isinstance(res, str) else res  # type: ignore[return-value]

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
    """重写 ~ 拼接、+ 与 % 运算，避免 CPython 字符串运算剥离 TrackedValue 追踪信息。"""

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

    def visit_Mod(self, node: nodes.Mod, frame: Frame) -> None:
        self.write("environment._tracked_mod(")
        self.visit(node.left, frame)
        self.write(", ")
        self.visit(node.right, frame)
        self.write(")")


def _collect_tracked_sources(items: Iterable[Any]) -> tuple[list[str], bool]:
    """收集过滤器/格式化入参中携带的 TrackedValue 字段名与缺失标记（跳过 Jinja 运行时上下文对象）。#Created By AiCoding(codex)"""
    names: list[str] = []
    any_missing = False

    def _visit(obj: Any) -> None:
        nonlocal any_missing
        # 显式跳过 Jinja2 Context / Environment / EvalContext，防止 @pass_context 过滤器误扫全量上下文变量污染 used
        if isinstance(obj, (Context, Environment, EvalContext)):
            return
        if isinstance(obj, TrackedValue):
            for fn in obj.field_names:
                if fn not in names:
                    names.append(fn)
            if obj.missing:
                any_missing = True
        elif isinstance(obj, TrackedList):
            if obj.field_name and obj.field_name not in names:
                names.append(obj.field_name)
            if obj.missing:
                any_missing = True
            for el in list.__iter__(obj):
                _visit(el)
        elif isinstance(obj, (list, tuple)):
            for el in obj:
                _visit(el)
        elif isinstance(obj, Mapping):
            for k, v in obj.items():
                _visit(k)
                _visit(v)

    for item in items:
        _visit(item)
    return names, any_missing


def _wrap_tracked_result(res: Any, sources: Iterable[Any]) -> Any:
    """若过滤器返回 str 且入参含追踪来源，则包装回 TrackedValue 以免丢失 used 追踪。#Created By AiCoding(codex)"""
    if not isinstance(res, str):
        return res
    names, any_missing = _collect_tracked_sources(sources)
    if isinstance(res, TrackedValue):
        if not names and not any_missing:
            return res
        return res._wrap(str.__str__(res), extra_names=names, extra_missing=any_missing)
    if names:
        return TrackedValue(res, names[0], missing=any_missing, field_names=names)
    return res


def _wrap_filter_func(fn: Callable[..., Any]) -> Callable[..., Any]:
    """包装 Jinja2 内置过滤器以保留 TrackedValue 字段追踪（同时通过 @wraps 保留 jinja_pass_arg）。#Created By AiCoding(codex)"""
    pass_arg = getattr(fn, "jinja_pass_arg", None)

    @wraps(fn)
    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        res = fn(*args, **kwargs)
        if isinstance(res, str):
            tracked_args = args[1:] if pass_arg is not None and args else args
            return _wrap_tracked_result(res, (*tracked_args, *kwargs.values()))
        return res

    return _wrapped


class _TrackedTemplate(JinjaTemplate):
    """在模板渲染期间绑定当前环境的 used 集合，使 TrackedList.__iter__ 能准确记录被遍历的列表字段。

    #Created By AiCoding(codex)
    当外层（如 render_body）已通过 _ACTIVE_USED 绑定独立 used 集合时直接复用，确保预编译模板并发渲染互不串扰。
    """

    def render(self, *args: Any, **kwargs: Any) -> str:
        env_used = getattr(self.environment, "_used", None)
        if env_used is None and _ACTIVE_USED.get() is not None:
            return super().render(*args, **kwargs)
        token = _ACTIVE_USED.set(env_used)
        try:
            return super().render(*args, **kwargs)
        finally:
            _ACTIVE_USED.reset(token)

    async def render_async(self, *args: Any, **kwargs: Any) -> str:
        env_used = getattr(self.environment, "_used", None)
        if env_used is None and _ACTIVE_USED.get() is not None:
            return await super().render_async(*args, **kwargs)
        token = _ACTIVE_USED.set(env_used)
        try:
            return await super().render_async(*args, **kwargs)
        finally:
            _ACTIVE_USED.reset(token)


class _TrackedSandboxEnvironment(ImmutableSandboxedEnvironment):
    code_generator_class = _TrackedCodeGenerator
    template_class = _TrackedTemplate
    _strict_undefined: bool = False
    _used: set[str] | None = None

    def call_filter(
        self,
        name: str,
        value: Any,
        args: Sequence[Any] | None = None,
        kwargs: Mapping[str, Any] | None = None,
        context: Any = None,
        eval_ctx: Any = None,
    ) -> Any:
        res = super().call_filter(name, value, args, kwargs, context, eval_ctx)
        return _wrap_tracked_result(res, (value, *(args or ()), *(kwargs or {}).values()))

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

    def _materialize_mod_arg(self, obj: Any) -> Any:
        if isinstance(obj, Undefined) and obj._undefined_obj is _jinja_missing and obj._undefined_name:
            uname = str(obj._undefined_name)
            return TrackedValue("{{" + uname + "}}", uname, missing=True)
        if isinstance(obj, tuple):
            return tuple(self._materialize_mod_arg(x) for x in obj)
        if isinstance(obj, dict):
            return {k: self._materialize_mod_arg(v) for k, v in obj.items()}
        return obj

    def _tracked_mod(self, left: Any, right: Any) -> Any:
        if not self._strict_undefined:
            if isinstance(left, Undefined) and left._undefined_obj is _jinja_missing and left._undefined_name:
                uname = str(left._undefined_name)
                left = TrackedValue("{{" + uname + "}}", uname, missing=True)
            if isinstance(left, str):
                right = self._materialize_mod_arg(right)
        if isinstance(left, TrackedValue):
            return left.__mod__(right)
        if isinstance(left, str):
            return _wrap_tracked_result(left % right, (left, right))
        return left % right


def _test_has_digit(value: Any) -> bool:
    """Jinja 测试 hasDigit：值存在且文本中至少含一个 Unicode 数字字符（对齐 Java Character::isDigit）。

    #Created By AiCoding(codex)
    None 与任何 Undefined（含渲染为 {{字段}} 占位符的缺失字段）一律返回 False，不抛异常；
    缺失字段的占位文本 {{标准资费}} 本身不含数字，因此同样为 False。
    """
    if value is None or isinstance(value, Undefined):
        return False
    text = str.__str__(value) if isinstance(value, str) else str(value)
    return any(ch.isdigit() for ch in text)


class _PebbleNewlineTrimExtension(Extension):
    """模拟 Pebble 3.2.2 默认 newLineTrimming 对 {{ }} 输出标签的处理。

    #Created By AiCoding(codex)
    Pebble 会去掉每个标签（{% %}、{# #}、{{ }}）后紧跟的一个换行；Jinja 的 trim_blocks 只覆盖前两种，
    这里在词法流中把紧跟 variable_end 的 data 记号开头的一个换行去掉（词法器已把 \\r\\n 统一为 \\n）。
    不使用 -}} 写法，因为那会吞掉全部空白；纯文本中的字面 }} 不是 variable_end 记号，不受影响。
    """

    def filter_stream(self, stream: TokenStream) -> Iterable[Token]:
        prev_variable_end = False
        for token in stream:
            if prev_variable_end and token.type == TOKEN_DATA and token.value.startswith("\n"):
                prev_variable_end = False
                rest = token.value[1:]
                if not rest:
                    continue
                token = Token(token.lineno, TOKEN_DATA, rest)
            prev_variable_end = token.type == TOKEN_VARIABLE_END
            yield token


def make_environment(used: set[str] | None = None, *, strict_undefined: bool = False) -> Environment:
    """创建沙箱化的 Jinja2 环境。传入 used 集合时，记录被输出的字段名。

    #Created By AiCoding(codex)
    换行处理对齐 Pebble 3.2.2 默认值：trim_blocks=True 去掉 {% %} / {# #} 后的一个换行，
    _PebbleNewlineTrimExtension 去掉 {{ }} 后的一个换行；不开启 lstrip_blocks。
    另注册 Pebble 迁移模板使用的 hasDigit 测试。
    """

    def finalize(value: Any) -> Any:
        active_used = _ACTIVE_USED.get()
        target_used = active_used if active_used is not None else used
        if isinstance(value, Undefined):
            if strict_undefined or value._undefined_obj is not _jinja_missing or not value._undefined_name:
                value._fail_with_undefined_error()
            name = str(value._undefined_name)
            if target_used is not None:
                target_used.add(name)
            return "{{" + name + "}}"
        if target_used is not None:
            if isinstance(value, TrackedValue):
                target_used.update(value.field_names)
            elif isinstance(value, TrackedList) and value.field_name:
                target_used.add(value.field_name)
        return "" if value is None else value

    env = _TrackedSandboxEnvironment(
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        extensions=[_PebbleNewlineTrimExtension],
        undefined=StrictUndefined if strict_undefined else _PlaceholderUndefined,
        finalize=finalize,
    )
    env._strict_undefined = strict_undefined
    env._used = used
    for unsafe_global in ("cycler", "joiner", "lipsum", "namespace"):
        env.globals.pop(unsafe_global, None)
    for filter_name, filter_fn in list(env.filters.items()):
        env.filters[filter_name] = _wrap_filter_func(filter_fn)
    env.tests["hasDigit"] = _test_has_digit
    return env


_PARSE_ENV = make_environment()
_RENDER_ENV_STRICT = make_environment(strict_undefined=True)


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
    try:
        return set(meta.find_undeclared_variables(parse_body(body)))
    except TemplateSyntaxError as exc:
        raise BodySyntaxError(f"第 {exc.lineno} 行语法错误：{exc.message}", exc.lineno) from exc


def _unwrap_iter_name(expr: nodes.Node) -> nodes.Name | None:
    cur = expr
    while True:
        if isinstance(cur, nodes.Filter) and cur.node is not None:
            cur = cur.node
        elif isinstance(cur, nodes.Getitem):
            cur = cur.node
        else:
            break
    return cur if isinstance(cur, nodes.Name) and cur.ctx == "load" else None


def printed_variables(body: str) -> set[str]:
    """正文中直接输出（{{ 变量 }}）或在循环内输出单元格的变量。#Created By AiCoding(codex)"""
    tree = parse_body(body)
    try:
        undeclared = set(meta.find_undeclared_variables(tree))
    except TemplateSyntaxError as exc:
        raise BodySyntaxError(f"第 {exc.lineno} 行语法错误：{exc.message}", exc.lineno) from exc
    names: set[str] = set()
    for output in tree.find_all(nodes.Output):
        for node in output.find_all(nodes.Name):
            if node.ctx == "load" and node.name in undeclared:
                names.add(node.name)
    for loop in tree.find_all(nodes.For):
        iter_name = _unwrap_iter_name(loop.iter)
        if iter_name is not None and iter_name.name in undeclared:
            if any(True for _ in loop.find_all(nodes.Output)):
                names.add(iter_name.name)
    return names


_RENAME_TAG_TOKEN_RE = re.compile(
    r"""('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")"""
    r"""|(\|\s*[^\W\d]\w*)"""
    r"""|(\.\s*[^\W\d]\w*)"""
    r"""|([^\W\d]\w*)""",
    re.UNICODE,
)


def rename_body_variable(body_text: str, old_name: str, new_name: str) -> str:
    """在 Jinja2 输出块 {{ ... }} / {{- ... -}} 与控制块 {% ... %} / {%- ... -%} 中安全重命名顶层变量。

    #Created By AiCoding(codex)
    跳过注释 {# ... #}、单双引号字符串字面量、过滤器名（| filter）及属性后缀（.attr）。
    """
    if not body_text or not old_name or old_name == new_name:
        return body_text
    out: list[str] = []
    n = len(body_text)
    i = 0
    while i < n:
        brace = body_text.find("{", i)
        if brace == -1 or brace + 1 >= n:
            out.append(body_text[i:])
            break
        nxt = body_text[brace + 1]
        if nxt not in ("#", "{", "%"):
            out.append(body_text[i : brace + 1])
            i = brace + 1
            continue
        out.append(body_text[i:brace])
        if nxt == "#":
            end_comment = body_text.find("#}", brace + 2)
            if end_comment == -1:
                out.append(body_text[brace:])
                break
            out.append(body_text[brace : end_comment + 2])
            i = end_comment + 2
            continue

        is_block = nxt == "%"
        close_tok = "%}" if is_block else "}}"
        open_end = brace + 3 if (brace + 2 < n and body_text[brace + 2] in "+-") else brace + 2
        quote_ch: str | None = None
        close_pos = -1
        j = open_end
        while j < n:
            ch = body_text[j]
            if quote_ch is not None:
                if ch == "\\" and j + 1 < n:
                    j += 2
                    continue
                if ch == quote_ch:
                    quote_ch = None
                j += 1
                continue
            if ch in ("'", '"'):
                quote_ch = ch
                j += 1
                continue
            if body_text.startswith(close_tok, j):
                close_pos = j
                break
            j += 1

        if close_pos == -1:
            out.append(body_text[brace:])
            break

        inner = body_text[open_end:close_pos]
        first_ident = True

        def _sub_tok(m: re.Match[str]) -> str:
            nonlocal first_ident
            ident = m.group(4)
            if not ident:
                return m.group(0)
            if is_block and first_ident:
                first_ident = False
                return m.group(0)
            return new_name if ident == old_name else m.group(0)

        out.append(body_text[brace:open_end])
        out.append(_RENAME_TAG_TOKEN_RE.sub(_sub_tok, inner))
        out.append(close_tok)
        i = close_pos + 2
    return "".join(out)


_COMPARE_OPS = {
    "eq": "==",
    "ne": "!=",
    "gt": ">",
    "gteq": ">=",
    "lt": "<",
    "lteq": "<=",
    "in": "in",
    "notin": "not in",
}


def _collect_loaded_vars(node: nodes.Node, local_vars: frozenset[str], undeclared: set[str]) -> set[str]:
    """收集 AST 子树中引用的顶层模板变量（排除循环/set 局部变量）。#Created By AiCoding(codex)"""
    found: set[str] = set()
    for n in node.find_all(nodes.Name):
        if n.ctx == "load" and n.name not in local_vars and n.name in undeclared:
            found.add(n.name)
    return found


def _uses_local_var(node: nodes.Node, local_vars: frozenset[str]) -> bool:
    """判断表达式是否引用了循环/赋值等局部绑定变量。"""
    if not local_vars:
        return False
    return any(n.ctx == "load" and n.name in local_vars for n in node.find_all(nodes.Name))


def _format_const(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def _format_cond_expr(node: nodes.Node) -> str | None:
    """将 Jinja2 条件 AST 格式化为简洁可读的条件文本；遇到无法静态表达的节点返回 None。#Created By AiCoding(codex)"""
    if isinstance(node, nodes.Name):
        return node.name
    if isinstance(node, nodes.Const):
        return _format_const(node.value)
    if isinstance(node, nodes.Getattr):
        base = _format_cond_expr(node.node)
        return f"{base}.{node.attr}" if base else None
    if isinstance(node, nodes.Compare):
        left = _format_cond_expr(node.expr)
        if not left:
            return None
        parts = [left]
        for op in node.ops:
            sym = _COMPARE_OPS.get(op.op)
            right = _format_cond_expr(op.expr)
            if not sym or not right:
                return None
            parts.append(f"{sym} {right}")
        return " ".join(parts)
    if isinstance(node, nodes.Test):
        target = _format_cond_expr(node.node)
        if not target:
            return None
        if node.args or node.kwargs:
            return None
        return f"{target} is {node.name}"
    if isinstance(node, nodes.Not):
        if isinstance(node.node, nodes.Test) and not node.node.args and not node.node.kwargs:
            target = _format_cond_expr(node.node.node)
            return f"{target} is not {node.node.name}" if target else None
        inner = _format_cond_expr(node.node)
        return f"not ({inner})" if inner else None
    if isinstance(node, nodes.And):
        left = _format_cond_expr(node.left)
        right = _format_cond_expr(node.right)
        if not left or not right:
            return None
        if isinstance(node.left, nodes.Or):
            left = f"({left})"
        if isinstance(node.right, nodes.Or):
            right = f"({right})"
        return f"{left} and {right}"
    if isinstance(node, nodes.Or):
        left = _format_cond_expr(node.left)
        right = _format_cond_expr(node.right)
        if not left or not right:
            return None
        return f"{left} or {right}"
    if isinstance(node, nodes.Filter):
        base = _format_cond_expr(node.node)
        if not base or node.args or node.kwargs:
            return None
        return f"{base}|{node.name}"
    return None


def _target_names(node: nodes.Node) -> set[str]:
    """提取 for / assign 目标中绑定的局部变量名。"""
    return {n.name for n in node.find_all(nodes.Name) if n.ctx == "store"}


@lru_cache(maxsize=256)
def body_field_conditions(body: str) -> dict[str, tuple[str, tuple[str, ...]]]:
    """静态分析正文 Jinja2 AST，提取仅在条件分支中使用的字段及其展示条件。

    #Created By AiCoding(codex)
    返回：{字段名: (可读展示条件文本, 条件所依赖的控制字段名元组)}。
    保守原则（保证永不误跳过必查字段）：
    1. 只要字段在任一无条件位置出现（含直接输出、顶层 if 条件求值、无条件 for 迭代），均不放入返回表；
    2. 在 if/elif 条件表达式中出现的字段本身（如「违约责任 is defined」），会先以外层守卫记录一次使用，
       从而防止自保护字段误判为“可跳过”；
    3. 仅依赖外层顶层字段的条件才纳入守卫；引用了循环局部变量的 if 条件不作为外层字段的跳过条件；
    4. else 分支保守继承外层条件（不凭否定条件跳过），避免误漏兜底分支。
    """
    if not body or not body.strip():
        return {}
    try:
        tree = parse_body(body)
        undeclared = set(meta.find_undeclared_variables(tree))
    except (BodySyntaxError, TemplateSyntaxError):
        return {}
    if not undeclared:
        return {}

    # 每个变量记录每次出现的守卫：(条件文本元组, 依赖控制变量集合)；None 表示无条件出现
    occurrences: dict[str, list[tuple[tuple[str, ...], frozenset[str]] | None]] = {}

    def _record(var_names: Iterable[str], guard_terms: tuple[str, ...], guard_vars: frozenset[str]) -> None:
        entry = None if not guard_terms else (guard_terms, guard_vars)
        for v in var_names:
            occurrences.setdefault(v, []).append(entry)

    def _walk(
        stmts: Sequence[nodes.Node],
        guard_terms: tuple[str, ...],
        guard_vars: frozenset[str],
        local_vars: frozenset[str],
    ) -> None:
        cur_locals = set(local_vars)
        for stmt in stmts:
            if isinstance(stmt, nodes.Output):
                _record(_collect_loaded_vars(stmt, frozenset(cur_locals), undeclared), guard_terms, guard_vars)
            elif isinstance(stmt, nodes.If):
                # 主 if 条件表达式本身在外层守卫下求值
                test_vars = _collect_loaded_vars(stmt.test, frozenset(cur_locals), undeclared)
                _record(test_vars, guard_terms, guard_vars)

                cond_text = None if _uses_local_var(stmt.test, frozenset(cur_locals)) else _format_cond_expr(stmt.test)
                if cond_text and test_vars:
                    body_terms = (*guard_terms, cond_text)
                    body_vars = guard_vars | frozenset(test_vars)
                else:
                    body_terms, body_vars = guard_terms, guard_vars
                _walk(stmt.body, body_terms, body_vars, frozenset(cur_locals))

                # elif 分支：elif 条件自身为进入该分支的必要条件（满足 Soundness，条件不成立绝不进入）
                for elif_node in stmt.elif_:
                    e_vars = _collect_loaded_vars(elif_node.test, frozenset(cur_locals), undeclared)
                    _record(e_vars, guard_terms, guard_vars)
                    e_text = (
                        None
                        if _uses_local_var(elif_node.test, frozenset(cur_locals))
                        else _format_cond_expr(elif_node.test)
                    )
                    if e_text and e_vars:
                        e_body_terms = (*guard_terms, e_text)
                        e_body_vars = guard_vars | frozenset(e_vars)
                    else:
                        e_body_terms, e_body_vars = guard_terms, guard_vars
                    _walk(elif_node.body, e_body_terms, e_body_vars, frozenset(cur_locals))

                # else 分支保守沿用外层守卫，避免复杂否定条件导致误跳过
                if stmt.else_:
                    _walk(stmt.else_, guard_terms, guard_vars, frozenset(cur_locals))
            elif isinstance(stmt, nodes.For):
                _record(_collect_loaded_vars(stmt.iter, frozenset(cur_locals), undeclared), guard_terms, guard_vars)
                loop_locals = frozenset(cur_locals | _target_names(stmt.target) | {"loop"})
                _walk(stmt.body, guard_terms, guard_vars, loop_locals)
                if stmt.else_:
                    _walk(stmt.else_, guard_terms, guard_vars, frozenset(cur_locals))
            elif isinstance(stmt, nodes.Assign):
                _record(_collect_loaded_vars(stmt.node, frozenset(cur_locals), undeclared), guard_terms, guard_vars)
                cur_locals.update(_target_names(stmt.target))
            elif isinstance(stmt, nodes.AssignBlock):
                _walk(stmt.body, guard_terms, guard_vars, frozenset(cur_locals))
                cur_locals.update(_target_names(stmt.target))
            else:
                _record(_collect_loaded_vars(stmt, frozenset(cur_locals), undeclared), guard_terms, guard_vars)

    _walk(tree.body, (), frozenset(), frozenset())

    result: dict[str, tuple[str, tuple[str, ...]]] = {}
    for var_name, occs in occurrences.items():
        if not occs or any(o is None for o in occs):
            continue
        branch_texts: list[str] = []
        dep_vars: list[str] = []
        for occ in occs:
            assert occ is not None
            terms, gvars = occ
            # 自依赖保护：若字段名自身出现在守卫控制变量中，必须视为无条件必查
            if var_name in gvars:
                branch_texts = []
                break
            joined = " and ".join(f"({t})" if " or " in t and len(terms) > 1 else t for t in terms)
            if joined not in branch_texts:
                branch_texts.append(joined)
            for gv in sorted(gvars):
                if gv not in dep_vars:
                    dep_vars.append(gv)
        if not branch_texts:
            continue
        cond_str = branch_texts[0] if len(branch_texts) == 1 else " 或 ".join(f"({b})" for b in branch_texts)
        result[var_name] = (cond_str, tuple(dep_vars))
    return result


@lru_cache(maxsize=256)
def _compile_body_template(body: str, strict_undefined: bool = False) -> JinjaTemplate:
    """预编译并缓存 Jinja2 模板对象（上限 256 个），消除每次渲染重编译 AST 的开销。#Created By AiCoding(codex)"""
    env = _RENDER_ENV_STRICT if strict_undefined else _PARSE_ENV
    try:
        return env.from_string(body)
    except TemplateSyntaxError as exc:
        raise BodySyntaxError(f"第 {exc.lineno} 行语法错误：{exc.message}", exc.lineno) from exc


def render_body(body: str, context: dict[str, Any], *, strict_undefined: bool = False) -> tuple[str, set[str]]:
    """渲染正文，返回（文本，实际输出的字段名集合）。#Created By AiCoding(codex)"""
    template = _compile_body_template(body, strict_undefined)
    used: set[str] = set()
    token = _ACTIVE_USED.set(used)
    try:
        text = template.render(context or {})
    except SecurityError as exc:
        raise SecurityError(f"模板安全沙箱拦截：{exc}") from exc
    finally:
        _ACTIVE_USED.reset(token)
    return text, used
