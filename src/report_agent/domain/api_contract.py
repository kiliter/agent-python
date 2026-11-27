"""接口契约：模型可以调用的业务接口的声明式定义。

#Created By AiCoding(codex)
契约只描述“接受哪些参数、固定值是什么、返回结构在哪里”，不包含任何业务判断。
平台按 input 校验模型给的参数，按 request 组包，按 response 把返回值转成记录列表。
文件格式：apis/<name>.yaml。
"""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from typing import Any, Literal
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

from .template import safe_regex_compile

ConnectorType = Literal["unified-gateway-xml", "unified-gateway-json", "http"]
HttpMethod = Literal["GET", "POST", "PUT", "DELETE", "PATCH"]
HttpBodyType = Literal["json", "form", "text", "none"]
HttpResponseFormat = Literal["auto", "json", "xml", "text"]
RecordsMode = Literal["auto", "object", "list", "scalar", "none"]

_PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)\}")
_XML_TAG_RE = re.compile(r"^[A-Za-z_][\w.\-]*$")
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_PROTECTED_HEADERS = frozenset({"host", "content-length", "transfer-encoding"})
# #Created By AiCoding(codex) 内置占位符：名称以 $ 开头为平台保留，不来自模型参数，也不能在 input 中声明。
# ${$now} → 组包时刻的本地时间 yyyyMMddHHmmss（对齐 Java 统一网关公共字段 request_time 的取值）。
BUILTIN_PLACEHOLDERS: dict[str, str] = {"$now": "组包时刻的本地时间 yyyyMMddHHmmss"}


def builtin_values(now: datetime | None = None) -> dict[str, str]:
    """内置占位符在本次组包时的取值（同一次组包内取同一时刻）。#Created By AiCoding(codex)"""
    moment = now or datetime.now()
    return {"$now": moment.strftime("%Y%m%d%H%M%S")}


def _with_builtins(args: dict[str, Any] | None) -> dict[str, Any]:
    """合并模型参数与内置占位符取值；内置值优先，模型参数不能覆盖。#Created By AiCoding(codex)"""
    merged = {k: v for k, v in (args or {}).items() if not str(k).startswith("$")}
    merged.update(builtin_values())
    return merged


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RetrySpec(_Base):
    """平台自动重试策略：只对网络错误和超时生效。"""

    maxAttempts: int = Field(default=1, ge=1, le=5)


class SuccessSpec(_Base):
    """业务成功判断：path 处的值等于 equals。path 不存在时按 missingAs 处理。"""

    path: str
    equals: str
    missingAs: Literal["success", "failure"] = "success"


class NoDataRule(_Base):
    """“无数据”判断：命中时视为成功且 0 条记录（例如“该时间段内无短信记录”）。"""

    path: str
    equals: str | None = None
    contains: str | None = None


class RecordsSpec(_Base):
    """业务记录抽取模式、节点路径与列说明（列说明会展示给模型）。"""

    mode: RecordsMode = "auto"
    path: str = "operation_out.content"
    flatten: bool = False
    columns: dict[str, str] = Field(default_factory=dict)

    @field_validator("path", mode="before")
    @classmethod
    def _normalize_path(cls, val: Any) -> Any:
        return "" if val is None else val

    @field_validator("columns", mode="before")
    @classmethod
    def _normalize_columns(cls, val: Any) -> Any:
        if val is None:
            return {}
        if isinstance(val, dict):
            return {str(k): ("" if v is None else str(v) if isinstance(v, (int, float, bool, str)) else v)
                    for k, v in val.items()}
        return val


_UNLIMITED_PREVIEW_ROWS = 1_000_000


class SummarySpec(_Base):
    """call_api 返回给模型的摘要大小（maxPreviewChars / previewRows 为 -1 时表示不截断全量保留）。#Created By AiCoding(codex)"""

    maxPreviewChars: int = 60
    previewRows: int | None = None

    @field_validator("maxPreviewChars")
    @classmethod
    def _validate_max_preview_chars(cls, val: int) -> int:
        if isinstance(val, bool) or (val != -1 and val < 1):
            raise ValueError("maxPreviewChars 须为正整数或 -1（-1 表示不限制预览字数）")
        return val

    @field_validator("previewRows")
    @classmethod
    def _validate_preview_rows(cls, val: int | None) -> int | None:
        if isinstance(val, bool) or (val is not None and val != -1 and val < 1):
            raise ValueError("previewRows 须为正整数或 -1（-1 表示不限制预览行数）")
        return val


class ResponseSpec(_Base):
    """返回结构。"""

    format: HttpResponseFormat = "auto"
    success: SuccessSpec | None = None
    noData: list[NoDataRule] = Field(default_factory=list)
    records: RecordsSpec = Field(default_factory=RecordsSpec)
    summary: SummarySpec = Field(default_factory=SummarySpec)

    @field_validator("format", mode="before")
    @classmethod
    def _normalize_format(cls, val: Any) -> Any:
        if val is None or (isinstance(val, str) and not val.strip()):
            return "auto"
        return val.strip().lower() if isinstance(val, str) else val

    @field_validator("noData", mode="before")
    @classmethod
    def _normalize_no_data(cls, val: Any) -> Any:
        return [] if val is None else val

    @field_validator("records", "summary", mode="before")
    @classmethod
    def _normalize_sub_specs(cls, val: Any) -> Any:
        return {} if val is None else val


class ApiContract(_Base):
    """apis/<name>.yaml 的内容。"""

    name: str
    title: str = ""
    description: str = ""
    connector: ConnectorType = "unified-gateway-xml"
    processCode: str = ""
    method: HttpMethod = "POST"
    url: str = ""
    query: dict[str, Any] = Field(default_factory=dict)
    bodyType: HttpBodyType = "json"
    timeoutMs: int = Field(default=10000, ge=100, le=120000)
    retry: RetrySpec = Field(default_factory=RetrySpec)
    idempotent: bool = True
    headers: dict[str, str] = Field(default_factory=dict)
    input: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    request: Any = Field(default_factory=dict)
    response: ResponseSpec = Field(default_factory=ResponseSpec)
    _validator_cache: tuple[dict[str, Any], Draft202012Validator] | None = PrivateAttr(default=None)

    @field_validator("processCode", "url", mode="before")
    @classmethod
    def _normalize_str_fields(cls, val: Any) -> Any:
        return "" if val is None else str(val)

    @field_validator("method", mode="before")
    @classmethod
    def _normalize_method(cls, val: Any) -> Any:
        if val is None or (isinstance(val, str) and not val.strip()):
            return "POST"
        return val.strip().upper() if isinstance(val, str) else val

    @field_validator("bodyType", mode="before")
    @classmethod
    def _normalize_body_type(cls, val: Any) -> Any:
        if val is None or (isinstance(val, str) and not val.strip()):
            return "json"
        return val.strip().lower() if isinstance(val, str) else val

    @field_validator("query", mode="before")
    @classmethod
    def _normalize_query(cls, val: Any) -> Any:
        return {} if val is None else val

    @field_validator("response", mode="before")
    @classmethod
    def _normalize_response(cls, val: Any) -> Any:
        return {} if val is None else val

    @field_validator("headers", mode="before")
    @classmethod
    def _normalize_headers(cls, val: Any) -> Any:
        if val is None:
            return {}
        if not isinstance(val, dict):
            return val
        normalized: dict[str, Any] = {}
        for k, v in val.items():
            key = "" if k is None else str(k)
            if v is None:
                normalized[key] = ""
            elif isinstance(v, bool):
                normalized[key] = "true" if v else "false"
            elif isinstance(v, (int, float, str)):
                normalized[key] = str(v)
            else:
                normalized[key] = v
        return normalized

    @model_validator(mode="after")
    def _check_connector_request_shape(self) -> ApiContract:
        """统一网关契约保持 request 为字典对象；常规 HTTP 未显式配置 records.path 时默认置为空根路径。#Created By AiCoding(codex)"""
        if self.connector != "http":
            if self.request is None:
                self.request = {}
            elif not isinstance(self.request, dict):
                raise ValueError("统一网关接口契约的 request 必须是键值映射对象")
        elif "path" not in self.response.records.model_fields_set:
            self.response.records.path = ""
        return self

    @property
    def is_json(self) -> bool:
        """是否为统一网关 JSON 协议连接器。"""
        return self.connector == "unified-gateway-json"

    @property
    def is_http(self) -> bool:
        """是否为常规 HTTP 连接器（不经统一网关信封）。#Created By AiCoding(codex)"""
        return self.connector == "http"

    def _get_validator(self) -> Draft202012Validator:
        """获取并按 input 字典引用缓存编译后的 JSON Schema 校验器，同时拦截高危 ReDoS 正则。#Created By AiCoding(codex)"""
        if not isinstance(self.input, dict):
            raise ValueError("input 必须是 JSON Schema 对象")
        cached = self._validator_cache
        if cached is not None and cached[0] is self.input:
            return cached[1]
        Draft202012Validator.check_schema(self.input)
        for pat_path, pat in _collect_patterns(self.input):
            try:
                safe_regex_compile(pat)
            except ValueError as exc:
                raise ValueError(f"input.{pat_path} 的正则不合法：{exc}") from exc
        validator = Draft202012Validator(self.input)
        self._validator_cache = (self.input, validator)
        return validator

    def schema_errors(self) -> list[str]:
        """检查 input 是否为合法的 JSON Schema，以及 url/query/request/headers 引用参数与安全性。"""
        errors: list[str] = []
        if not isinstance(self.input, dict):
            errors.append("input 不是合法的 JSON Schema：顶层必须是对象")
        else:
            try:
                Draft202012Validator.check_schema(self.input)
            except (SchemaError, re.error) as exc:
                errors.append(f"input 不是合法的 JSON Schema：{exc.message if isinstance(exc, SchemaError) else exc}")
            for pat_path, pat in _collect_patterns(self.input):
                try:
                    safe_regex_compile(pat)
                except ValueError as exc:
                    errors.append(f"input.{pat_path} 的正则不合法：{exc}")

        if self.is_http:
            errors.extend(_validate_http_url_template(self.url))
            if any(k is None or not str(k).strip() for k in self.query):
                errors.append("query 中包含空的参数名")
            if self.bodyType == "json":
                if self.request is not None and _has_empty_json_keys(self.request):
                    errors.append("request 中包含空的 JSON 键名")
            elif self.bodyType == "form":
                if self.request is not None:
                    if not isinstance(self.request, dict):
                        errors.append("bodyType=form 时 request 必须是键值映射对象")
                    elif any(k is None or not str(k).strip() for k in self.request):
                        errors.append("bodyType=form 时 request 中包含空的表单键名")
            elif self.bodyType == "text":
                # 默认空字典 {} 视作未配置纯文本内容；其他非字符串类型报错
                if self.request is not None and self.request != {} and not isinstance(self.request, str):
                    errors.append("bodyType=text 时 request 必须是字符串")
        else:
            if not self.processCode.strip():
                errors.append("processCode 不能为空")
            if not self.is_json:
                for bad_tag in sorted(_collect_bad_xml_tags(self.request)):
                    errors.append(f"request 中包含非法的 XML 标签名：{bad_tag!r}")
            else:
                if _has_empty_json_keys(self.request):
                    errors.append("request 中包含空的 JSON 键名")

        errors.extend(_validate_headers_dict(self.headers, allow_placeholders=True))
        for idx, rule in enumerate(self.response.noData):
            if rule.equals is None and (rule.contains is None or rule.contains == ""):
                errors.append(f"response.noData[{idx}] 不可同时省略 equals 与 contains（至少填写一项）")
        props_raw = self.input.get("properties") if isinstance(self.input, dict) else None
        declared = set(props_raw.keys()) if isinstance(props_raw, dict) else set()
        # #Created By AiCoding(codex) 以 $ 开头的名称是内置占位符：不需要（也不允许）在 input 中声明
        for key in sorted(k for k in declared if str(k).startswith("$")):
            errors.append(f"input 参数名 {key!r} 以 $ 开头，$ 开头的名称保留给内置占位符")

        placeholder_sources: list[tuple[str, Any]] = [("headers", self.headers)]
        if self.is_http:
            placeholder_sources.extend([("url", self.url), ("query", self.query)])
            if self.bodyType != "none":
                placeholder_sources.append(("request", self.request))
        else:
            placeholder_sources.insert(0, ("request", self.request))

        for where, node in placeholder_sources:
            for ref in sorted(_collect_placeholders(node)):
                if ref.startswith("$"):
                    if ref not in BUILTIN_PLACEHOLDERS:
                        errors.append(f"{where} 引用了未知的内置占位符 ${{{ref}}}（可用：{'、'.join(BUILTIN_PLACEHOLDERS)}）")
                elif ref not in declared:
                    errors.append(f"{where} 引用了未在 input 中声明的参数 ${{{ref}}}")
        return errors

    def validate_args(self, args: dict[str, Any]) -> list[str]:
        """按 input Schema 校验模型给的参数，返回中文错误列表。"""
        if not isinstance(args, dict):
            return ["参数必须是键值对象"]
        try:
            validator = self._get_validator()
            raw_errors = sorted(validator.iter_errors(args), key=lambda e: [str(p) for p in e.path])
        except (SchemaError, re.error, ValueError) as exc:
            msg = exc.message if isinstance(exc, SchemaError) else str(exc)
            return [f"接口参数 Schema 不合法：{msg}"]
        errors = []
        for err in raw_errors:
            where = ".".join(str(p) for p in err.path) or "参数"
            errors.append(f"{where}：{err.message}")
        return errors

    def build_request(self, args: dict[str, Any]) -> Any:
        """把 request 模板中的 ${参数} 替换为实际值（只替换字符串，不执行任何表达式）；${$now} 等内置占位符同时替换。"""
        return _substitute(self.request, _with_builtins(args))

    def build_preview_request(self, args: dict[str, Any] | None = None) -> Any:
        """把已提供的参数替换进 request，未提供的参数保留 ${参数名} 占位符供预览展示；内置占位符按当前时刻渲染。"""
        return _substitute(self.request, _with_builtins(args), keep_unresolved=True)

    def build_query(self, args: dict[str, Any] | None = None, *, keep_unresolved: bool = False) -> dict[str, Any]:
        """渲染 URL 查询参数字典（跳过值为 None 的可选参数）。#Created By AiCoding(codex)"""
        if not self.query:
            return {}
        rendered = _substitute(self.query, _with_builtins(args), keep_unresolved=keep_unresolved)
        if not isinstance(rendered, dict):
            return {}
        out: dict[str, Any] = {}
        for k, v in rendered.items():
            key = str(k).strip()
            if not key or v is None:
                continue
            out[key] = v
        return out

    def build_url(self, args: dict[str, Any] | None = None, *, keep_unresolved: bool = False) -> str:
        """渲染常规 HTTP 目标 URL 并合并 query 查询参数，拦截非法协议、端口、主机占位符及路径注入。#Created By AiCoding(codex)"""
        raw_tpl = self.url or ""
        if _has_url_ctrl_chars(raw_tpl):
            raise ValueError("HTTP 请求 URL 包含非法换行或控制字符")
        raw_url = raw_tpl.strip()
        if not raw_url:
            raise ValueError("HTTP 接口 url 不能为空")
        if not raw_url.lower().startswith(("http://", "https://")):
            raise ValueError("HTTP 请求 URL 必须以 http:// 或 https:// 开头")
        if _url_authority_has_placeholder(raw_url):
            raise ValueError("HTTP 请求 URL 不允许在主机或端口部分使用参数占位符")
        tpl_parsed = urlsplit(raw_url)
        if not tpl_parsed.hostname:
            raise ValueError("HTTP 请求 URL 缺少合法主机名")
        try:
            _ = tpl_parsed.port
        except ValueError as exc:
            raise ValueError("HTTP 请求 URL 端口不合法") from exc

        merged_args = _with_builtins(args)
        rendered_path = _substitute_url_path(tpl_parsed.path, merged_args, keep_unresolved=keep_unresolved)
        rendered_inline_query = _substitute_url_component(tpl_parsed.query, merged_args, keep_unresolved=keep_unresolved)
        rendered_fragment = _substitute_url_component(tpl_parsed.fragment, merged_args, keep_unresolved=keep_unresolved)
        rendered_url = urlunsplit((
            tpl_parsed.scheme,
            tpl_parsed.netloc,
            rendered_path,
            rendered_inline_query,
            rendered_fragment,
        ))
        if _has_url_ctrl_chars(rendered_url):
            raise ValueError("HTTP 请求 URL 包含非法换行或控制字符")
        parsed = urlsplit(rendered_url)
        if not parsed.hostname:
            raise ValueError("HTTP 请求 URL 缺少合法主机名")
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("HTTP 请求 URL 端口不合法") from exc

        query_map = self.build_query(args, keep_unresolved=keep_unresolved)
        if not query_map:
            return rendered_url
        pairs: list[tuple[str, str]] = []
        for k, v in query_map.items():
            if isinstance(v, list):
                for item in v:
                    if item is not None:
                        pairs.append((k, _query_scalar_str(item)))
            else:
                pairs.append((k, _query_scalar_str(v)))
        if not pairs:
            return rendered_url
        if keep_unresolved:
            encoded_extra = "&".join(f"{k}={v}" for k, v in pairs)
        else:
            encoded_extra = urlencode(pairs, doseq=True)
        merged_query = f"{parsed.query}&{encoded_extra}" if parsed.query else encoded_extra
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, merged_query, parsed.fragment))

    def build_headers(self, args: dict[str, Any] | None = None, *, keep_unresolved: bool = False) -> dict[str, str]:
        """渲染并校验自定义安全请求头（拦截 CRLF 注入、非 ASCII 字符与受保护请求头覆盖）。"""
        if not self.headers:
            return {}
        rendered_raw = _substitute(self.headers, _with_builtins(args), keep_unresolved=keep_unresolved)
        rendered = {str(k).strip(): _query_scalar_str(v) if v is not None else "" for k, v in rendered_raw.items()}
        errs = _validate_headers_dict(rendered, allow_placeholders=keep_unresolved)
        if errs:
            raise ValueError("；".join(errs))
        return rendered

    def param_hint(self) -> str:
        """给模型看的一行参数说明。"""
        props_raw = self.input.get("properties") if isinstance(self.input, dict) else None
        props = props_raw if isinstance(props_raw, dict) else {}
        req_raw = self.input.get("required") if isinstance(self.input, dict) else None
        required = set(req_raw) if isinstance(req_raw, list) else set()
        parts = []
        for key, spec in props.items():
            spec_dict = spec if isinstance(spec, dict) else {}
            desc = spec_dict.get("description") or spec_dict.get("pattern") or spec_dict.get("type", "")
            parts.append(f"{key}{'（必填）' if key in required else ''}：{desc}")
        return "；".join(parts) or "无参数"

    def preview_rows(self, default: int) -> int:
        configured = self.response.summary.previewRows
        if configured is None:
            return default
        if configured == -1:
            return _UNLIMITED_PREVIEW_ROWS
        return configured


def _collect_placeholders(node: Any) -> set[str]:
    """收集 request/headers 模板中引用的参数名（显式栈迭代，防范超深嵌套栈溢出）。"""
    found: set[str] = set()
    stack: list[Any] = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, str):
            found.update(m.group(1) for m in _PLACEHOLDER_RE.finditer(cur))
        elif isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return found


def _substitute(node: Any, args: dict[str, Any], *, keep_unresolved: bool = False) -> Any:
    """递归替换占位符。整段就是一个占位符时保留原值类型；keep_unresolved=True 时未提供的参数保留 ${参数}。"""
    if isinstance(node, str):
        whole = _PLACEHOLDER_RE.fullmatch(node)
        if whole:
            key = whole.group(1)
            val = args.get(key)
            if keep_unresolved and (key not in args or val is None or val == ""):
                return node
            if val is None:
                return None
            return copy.deepcopy(val) if isinstance(val, (dict, list)) else val

        def _repl(m: re.Match[str]) -> str:
            key = m.group(1)
            val = args.get(key)
            if keep_unresolved and (key not in args or val is None or val == ""):
                return m.group(0)
            return "" if val is None else _query_scalar_str(val)

        return _PLACEHOLDER_RE.sub(_repl, node)
    if isinstance(node, dict):
        return {k: _substitute(v, args, keep_unresolved=keep_unresolved) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute(v, args, keep_unresolved=keep_unresolved) for v in node]
    return node


def _has_empty_json_keys(node: Any) -> bool:
    """检查 JSON request 模板中是否存在空键名（显式栈迭代）。"""
    stack: list[Any] = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k is None or not str(k).strip():
                    return True
                stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return False


def _validate_headers_dict(headers: dict[str, str], *, allow_placeholders: bool = False) -> list[str]:
    """校验自定义 HTTP 头（禁止空键、控制字符/CRLF 注入、非可见 ASCII 以及覆盖受保护头）。#Created By AiCoding(codex)"""
    errs: list[str] = []
    for raw_k, raw_v in (headers or {}).items():
        k = str(raw_k)
        v = "" if raw_v is None else str(raw_v)
        if not k.strip():
            errs.append("headers 中包含空的请求头名称")
            continue
        bad_key_ctrl = any(ord(ch) < 32 or ord(ch) == 127 for ch in k)
        bad_val_ctrl = any((ord(ch) < 32 and ch != "\t") or ord(ch) == 127 for ch in v)
        if any(ch in k or ch in v for ch in ("\r", "\n", "\x00")) or bad_key_ctrl or bad_val_ctrl:
            errs.append(f"headers 请求头 {k!r} 含有非法换行或控制字符")
            continue
        k_stripped = k.strip()
        if not k_stripped.isascii() or not _HEADER_NAME_RE.fullmatch(k_stripped):
            errs.append(f"headers 请求头名称 {k!r} 格式不合法（仅允许可见 ASCII token 字符）")
            continue
        val_check = _PLACEHOLDER_RE.sub("", v) if allow_placeholders else v
        if any(ord(ch) > 126 for ch in val_check):
            errs.append(f"headers 请求头 {k_stripped!r} 的值含有非 ASCII 字符")
            continue
        if k_stripped.lower() in _PROTECTED_HEADERS:
            errs.append(f"headers 不允许覆盖受保护请求头 {k_stripped!r}")
    return errs


def _collect_patterns(node: Any, prefix: str = "") -> list[tuple[str, str]]:
    """收集 JSON Schema 中的全部 pattern 正则表达式（显式栈迭代，防范超深嵌套栈溢出）。"""
    found: list[tuple[str, str]] = []
    stack: list[tuple[Any, str]] = [(node, prefix)]
    while stack:
        cur, cur_prefix = stack.pop()
        if isinstance(cur, dict):
            pat = cur.get("pattern")
            if isinstance(pat, str):
                found.append((f"{cur_prefix}pattern", pat))
            items = list(cur.items())
            for k, v in reversed(items):
                stack.append((v, f"{cur_prefix}{k}."))
        elif isinstance(cur, list):
            for idx in range(len(cur) - 1, -1, -1):
                stack.append((cur[idx], f"{cur_prefix}[{idx}]."))
    return found


def _collect_bad_xml_tags(node: Any) -> set[str]:
    """收集 request 字典中非法的 XML 元素标签名（显式栈迭代）。"""
    bad: set[str] = set()
    stack: list[Any] = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                tag = str(k)
                if not _XML_TAG_RE.match(tag):
                    bad.add(tag)
                stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return bad


def parse_api_yaml(text: str) -> ApiContract:
    """解析接口契约 YAML。"""
    data = yaml.safe_load(text)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("接口契约 YAML 顶层必须是键值映射对象")
    return ApiContract.model_validate(data)


def _has_url_ctrl_chars(url: str) -> bool:
    """检查 URL 中是否包含换行符、空字节或其他 ASCII 控制字符。#Created By AiCoding(codex)"""
    return any(ch in ("\r", "\n", "\x00") or ord(ch) < 32 or ord(ch) == 127 for ch in url)


def _url_authority_has_placeholder(url: str) -> bool:
    """检查 URL 的 scheme://authority（主机/端口/用户信息）部分是否包含动态参数占位符。#Created By AiCoding(codex)"""
    if "://" not in url:
        return bool(_PLACEHOLDER_RE.search(url))
    scheme, after = url.split("://", 1)
    if _PLACEHOLDER_RE.search(scheme):
        return True
    end = len(after)
    for sep in ("/", "?", "#"):
        pos = after.find(sep)
        if pos != -1 and pos < end:
            end = pos
    return bool(_PLACEHOLDER_RE.search(after[:end]))


def _substitute_url_path(path: str, args: dict[str, Any], *, keep_unresolved: bool = False) -> str:
    """安全替换 URL 路径中的 ${参数}，对参数值执行严格百分号编码以拦截 ? / # / 空格 / ../ 路径注入。#Created By AiCoding(codex)"""
    if not path:
        return ""

    def _repl(m: re.Match[str]) -> str:
        key = m.group(1)
        val = args.get(key)
        if keep_unresolved and (key not in args or val is None or val == ""):
            return m.group(0)
        if val is None:
            return ""
        encoded = quote(_query_scalar_str(val), safe="")
        if encoded == ".":
            return "%2E"
        if encoded == "..":
            return "%2E%2E"
        return encoded

    return _PLACEHOLDER_RE.sub(_repl, path)


def _substitute_url_component(comp: str, args: dict[str, Any], *, keep_unresolved: bool = False) -> str:
    """安全替换内联 URL query/fragment 中的 ${参数}，防止 & 或 # 截断注入。#Created By AiCoding(codex)"""
    if not comp:
        return ""

    def _repl(m: re.Match[str]) -> str:
        key = m.group(1)
        val = args.get(key)
        if keep_unresolved and (key not in args or val is None or val == ""):
            return m.group(0)
        if val is None:
            return ""
        return quote(_query_scalar_str(val), safe="")

    return _PLACEHOLDER_RE.sub(_repl, comp)


def _validate_http_url_template(url: str) -> list[str]:
    """静态校验常规 HTTP 接口的 URL 模板（支持路径/查询参数含 ${参数} 占位符，禁止动态主机与非法端口）。#Created By AiCoding(codex)"""
    raw = url or ""
    if _has_url_ctrl_chars(raw):
        return ["HTTP 接口 url 包含非法换行或控制字符"]
    clean = raw.strip()
    if not clean:
        return ["HTTP 接口 url 不能为空"]
    if not clean.lower().startswith(("http://", "https://")):
        return ["HTTP 接口 url 必须以 http:// 或 https:// 开头"]
    if _url_authority_has_placeholder(clean):
        return ["HTTP 接口 url 不允许在主机或端口部分使用参数占位符"]
    probe = _PLACEHOLDER_RE.sub("placeholder", clean)
    parsed = urlsplit(probe)
    if not parsed.hostname:
        return ["HTTP 接口 url 缺少合法主机名"]
    try:
        _ = parsed.port
    except ValueError:
        return ["HTTP 接口 url 端口不合法"]
    return []


def _query_scalar_str(val: Any) -> str:
    """把 query 参数值转为字符串：布尔值保持 true/false，结构化对象转紧凑 JSON。#Created By AiCoding(codex)"""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False, separators=(",", ":"))
    return str(val)


def fixed_params(request: Any, prefix: str = "") -> list[dict[str, str]]:
    """列出 request 模板中不引用参数的固定值（管理端展示用）。"""
    if not isinstance(request, dict):
        return []
    result: list[dict[str, str]] = []
    for key, val in request.items():
        name = f"{prefix}{key}"
        if isinstance(val, dict):
            result.extend(fixed_params(val, prefix=f"{name}."))
        elif isinstance(val, str) and _PLACEHOLDER_RE.search(val):
            # #Created By AiCoding(codex) 只引用内置占位符（如 ${$now}）的值不依赖模型参数，按固定值展示原样模板
            refs = _collect_placeholders(val)
            if refs and all(r in BUILTIN_PLACEHOLDERS for r in refs):
                result.append({"name": name, "value": val})
            continue
        elif isinstance(val, list):
            if _collect_placeholders(val):
                continue
            result.append({"name": name, "value": json.dumps(val, ensure_ascii=False, separators=(",", ":"))})
        elif isinstance(val, bool):
            result.append({"name": name, "value": "true" if val else "false"})
        else:
            result.append({"name": name, "value": "" if val is None else str(val)})
    return result
