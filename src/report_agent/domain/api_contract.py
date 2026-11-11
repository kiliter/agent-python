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
from typing import Any, Literal

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, field_validator

ConnectorType = Literal["unified-gateway-xml", "unified-gateway-json"]

_PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)\}")
_XML_TAG_RE = re.compile(r"^[A-Za-z_][\w.\-]*$")
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_PROTECTED_HEADERS = frozenset({"host", "content-length", "transfer-encoding"})


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
    """记录列表的位置与列说明（列说明会展示给模型）。"""

    path: str
    columns: dict[str, str] = Field(default_factory=dict)


class SummarySpec(_Base):
    """call_api 返回给模型的摘要大小。"""

    maxPreviewChars: int = 60
    previewRows: int | None = None


class ResponseSpec(_Base):
    """返回结构。"""

    success: SuccessSpec | None = None
    noData: list[NoDataRule] = Field(default_factory=list)
    records: RecordsSpec
    summary: SummarySpec = Field(default_factory=SummarySpec)


class ApiContract(_Base):
    """apis/<name>.yaml 的内容。"""

    name: str
    title: str = ""
    description: str = ""
    connector: ConnectorType = "unified-gateway-xml"
    processCode: str
    timeoutMs: int = Field(default=10000, ge=100, le=120000)
    retry: RetrySpec = Field(default_factory=RetrySpec)
    idempotent: bool = True
    headers: dict[str, str] = Field(default_factory=dict)
    input: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    request: dict[str, Any] = Field(default_factory=dict)
    response: ResponseSpec

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

    @property
    def is_json(self) -> bool:
        """是否为统一网关 JSON 协议连接器。"""
        return self.connector == "unified-gateway-json"

    def schema_errors(self) -> list[str]:
        """检查 input 是否为合法的 JSON Schema，以及 request/headers 引用的参数与头部安全性。"""
        errors: list[str] = []
        if not self.processCode.strip():
            errors.append("processCode 不能为空")
        try:
            Draft202012Validator.check_schema(self.input)
        except (SchemaError, re.error) as exc:
            errors.append(f"input 不是合法的 JSON Schema：{exc.message if isinstance(exc, SchemaError) else exc}")
        for pat_path, pat in _collect_patterns(self.input):
            try:
                re.compile(pat)
            except re.error as exc:
                errors.append(f"input.{pat_path} 的正则不合法：{exc}")
        if not self.is_json:
            for bad_tag in sorted(_collect_bad_xml_tags(self.request)):
                errors.append(f"request 中包含非法的 XML 标签名：{bad_tag!r}")
        else:
            if _has_empty_json_keys(self.request):
                errors.append("request 中包含空的 JSON 键名")
        errors.extend(_validate_headers_dict(self.headers))
        declared = set((self.input.get("properties") or {}).keys()) if isinstance(self.input, dict) else set()
        for ref in sorted(_collect_placeholders(self.request)):
            if ref not in declared:
                errors.append(f"request 引用了未在 input 中声明的参数 ${{{ref}}}")
        for ref in sorted(_collect_placeholders(self.headers)):
            if ref not in declared:
                errors.append(f"headers 引用了未在 input 中声明的参数 ${{{ref}}}")
        return errors

    def validate_args(self, args: dict[str, Any]) -> list[str]:
        """按 input Schema 校验模型给的参数，返回中文错误列表。"""
        if not isinstance(args, dict):
            return ["参数必须是键值对象"]
        try:
            validator = Draft202012Validator(self.input)
            raw_errors = sorted(validator.iter_errors(args), key=lambda e: list(e.path))
        except (SchemaError, re.error) as exc:
            return [f"接口参数 Schema 不合法：{exc}"]
        errors = []
        for err in raw_errors:
            where = ".".join(str(p) for p in err.path) or "参数"
            errors.append(f"{where}：{err.message}")
        return errors

    def build_request(self, args: dict[str, Any]) -> dict[str, Any]:
        """把 request 模板中的 ${参数} 替换为实际值（只替换字符串，不执行任何表达式）。"""
        return _substitute(copy.deepcopy(self.request), args or {})

    def build_preview_request(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """把已提供的参数替换进 request，未提供的参数保留 ${参数名} 占位符供预览展示。"""
        return _substitute(copy.deepcopy(self.request), args or {}, keep_unresolved=True)

    def build_headers(self, args: dict[str, Any] | None = None) -> dict[str, str]:
        """渲染并校验自定义安全请求头（拦截 CRLF 注入与受保护请求头覆盖）。"""
        if not self.headers:
            return {}
        rendered_raw = _substitute(copy.deepcopy(self.headers), args or {})
        rendered = {str(k).strip(): ("" if v is None else str(v)) for k, v in rendered_raw.items()}
        errs = _validate_headers_dict(rendered)
        if errs:
            raise ValueError("；".join(errs))
        return rendered

    def param_hint(self) -> str:
        """给模型看的一行参数说明。"""
        props = self.input.get("properties") or {}
        required = set(self.input.get("required") or [])
        parts = []
        for key, spec in props.items():
            desc = spec.get("description") or spec.get("pattern") or spec.get("type", "")
            parts.append(f"{key}{'（必填）' if key in required else ''}：{desc}")
        return "；".join(parts) or "无参数"

    def preview_rows(self, default: int) -> int:
        return self.response.summary.previewRows or default


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
            return None if val is None else val

        def _repl(m: re.Match[str]) -> str:
            key = m.group(1)
            val = args.get(key)
            if keep_unresolved and (key not in args or val is None or val == ""):
                return m.group(0)
            return "" if val is None else str(val)

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


def _validate_headers_dict(headers: dict[str, str]) -> list[str]:
    """校验自定义 HTTP 头（禁止空键、控制字符/CRLF 注入以及覆盖受保护头）。"""
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
        if not _HEADER_NAME_RE.match(k_stripped):
            errs.append(f"headers 请求头名称 {k!r} 格式不合法")
            continue
        if k_stripped.lower() in _PROTECTED_HEADERS:
            errs.append(f"headers 不允许覆盖受保护请求头 {k_stripped!r}")
    return errs


def _collect_patterns(node: Any, prefix: str = "") -> list[tuple[str, str]]:
    """收集 JSON Schema 中的全部 pattern 正则表达式。"""
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        pat = node.get("pattern")
        if isinstance(pat, str):
            found.append((f"{prefix}pattern", pat))
        for k, v in node.items():
            found.extend(_collect_patterns(v, f"{prefix}{k}."))
    elif isinstance(node, list):
        for idx, v in enumerate(node):
            found.extend(_collect_patterns(v, f"{prefix}[{idx}]."))
    return found


def _collect_bad_xml_tags(node: Any) -> set[str]:
    """收集 request 字典中非法的 XML 元素标签名。"""
    bad: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            tag = str(k)
            if not _XML_TAG_RE.match(tag):
                bad.add(tag)
            bad |= _collect_bad_xml_tags(v)
    elif isinstance(node, list):
        for v in node:
            bad |= _collect_bad_xml_tags(v)
    return bad


def parse_api_yaml(text: str) -> ApiContract:
    """解析接口契约 YAML。"""
    data = yaml.safe_load(text)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("接口契约 YAML 顶层必须是键值映射对象")
    return ApiContract.model_validate(data)


def fixed_params(request: dict[str, Any], prefix: str = "") -> list[dict[str, str]]:
    """列出 request 模板中不引用参数的固定值（管理端展示用）。"""
    result: list[dict[str, str]] = []
    for key, val in request.items():
        name = f"{prefix}{key}"
        if isinstance(val, dict):
            result.extend(fixed_params(val, prefix=f"{name}."))
        elif isinstance(val, str) and _PLACEHOLDER_RE.search(val):
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
