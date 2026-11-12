"""模板正文使用的 Jinja2 环境，以及带“使用追踪”的渲染。

#Created By AiCoding(codex)
渲染时每个字段值包装成 TrackedValue（str 子类），{{ }} 输出时经过 finalize 记录字段名，
这样可以知道最终报告实际展示了哪些字段，用来判断 SUCCESS / PARTIAL。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextvars import ContextVar
from functools import lru_cache, wraps
from typing import Any

from jinja2 import Environment, StrictUndefined, Template as JinjaTemplate, TemplateSyntaxError, Undefined, meta, nodes
from jinja2.compiler import CodeGenerator, Frame
from jinja2.exceptions import SecurityError
from jinja2.ext import Extension
from jinja2.lexer import TOKEN_DATA, TOKEN_VARIABLE_END, Token, TokenStream
from jinja2.sandbox import ImmutableSandboxedEnvironment
from jinja2.utils import missing as _jinja_missing

_ACTIVE_USED: ContextVar[set[str] | None] = ContextVar("_ACTIVE_USED", default=None)


class TrackedList(list):
    """带字段名与缺失标记的列表值，仅在实际迭代（{% for %}）或直接输出时将字段名记入 used。

    #Created By AiCoding(codex)
    {% if 列表字段 %} 调用 bool(TrackedList)（走 __len__），不会触发 __iter__，因此不会误记为已展示；
    只有进入生效分支执行 {% for item in 列表字段 %}（或 {{ 列表字段 }} 输出）时才记录字段名。
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

    def __iter__(self) -> Iterator[Any]:
        if self.field_name:
            if self._on_iter is not None:
                self._on_iter(self.field_name)
            active_used = _ACTIVE_USED.get()
            if active_used is not None:
                active_used.add(self.field_name)
        return super().__iter__()


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

    def removeprefix(self, prefix: str) -> "TrackedValue":  # type: ignore[override]
        return self._wrap(super().removeprefix(prefix))

    def removesuffix(self, suffix: str) -> "TrackedValue":  # type: ignore[override]
        return self._wrap(super().removesuffix(suffix))

    def split(self, sep: str | None = None, maxsplit: int = -1) -> list["TrackedValue"]:  # type: ignore[override]
        return [self._wrap(p) for p in super().split(sep, maxsplit)]

    def rsplit(self, sep: str | None = None, maxsplit: int = -1) -> list["TrackedValue"]:  # type: ignore[override]
        return [self._wrap(p) for p in super().rsplit(sep, maxsplit)]

    def splitlines(self, keepends: bool = False) -> list["TrackedValue"]:  # type: ignore[override]
        return [self._wrap(p) for p in super().splitlines(keepends)]

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


def _collect_tracked_sources(items: Iterable[Any]) -> tuple[list[str], bool]:
    """收集过滤器入参（含 list/tuple 容器元素）中携带的 TrackedValue 字段名与缺失标记。#Created By AiCoding(codex)"""
    names: list[str] = []
    any_missing = False

    def _visit(obj: Any) -> None:
        nonlocal any_missing
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

    @wraps(fn)
    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        res = fn(*args, **kwargs)
        if isinstance(res, str):
            return _wrap_tracked_result(res, (*args, *kwargs.values()))
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
        if isinstance(loop.iter, nodes.Name) and loop.iter.ctx == "load" and loop.iter.name in undeclared:
            if any(True for _ in loop.find_all(nodes.Output)):
                names.add(loop.iter.name)
    return names


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
