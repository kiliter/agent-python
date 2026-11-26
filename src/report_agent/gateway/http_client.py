"""常规 HTTP 连接器支持模块：请求组装、敏感凭证脱敏预览与响应体解析。

#Created By AiCoding(codex)
不走统一网关 /openapi_3 与 operation_in/operation_out 信封，按契约声明直接组装
METHOD / URL / Query / Headers / Body（json | form | text | none），响应解析复用
平台既有 JSON/XML 记录抽取能力并兼容纯文本与 204 空响应。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..domain.api_contract import ApiContract
from .base import ApiCallResult, decode_xml, extract_json_records, extract_records, parse_json_body, parse_xml

_SENSITIVE_KEY_KEYWORDS = (
    "authorization",
    "cookie",
    "token",
    "secret",
    "password",
    "passwd",
    "apikey",
    "api-key",
    "api_key",
    "credential",
    "sign",
    "signature",
)
_PHONE_KEY_KEYWORDS = ("mobile", "phone", "msisdn", "billid", "route_value")
_PHONE_11_RE = re.compile(r"^\d{11}$")
_WHOLE_PLACEHOLDER_RE = re.compile(r"^\$\{[^}]+\}$")


@dataclass
class PreparedHttpRequest:
    """一次常规 HTTP 请求的组装结果（含实际发送字节与脱敏预览文本）。"""

    method: str
    url: str
    headers: dict[str, str]
    payload_bytes: bytes | None
    preview: str


def _is_sensitive_key(name: str) -> bool:
    """判断请求头/参数/字段名是否属于凭证或敏感鉴权信息。"""
    low = (name or "").strip().lower()
    if not low:
        return False
    return any(kw in low for kw in _SENSITIVE_KEY_KEYWORDS)


def _is_phone_key(name: str) -> bool:
    low = (name or "").strip().lower()
    return any(kw in low for kw in _PHONE_KEY_KEYWORDS)


def _mask_scalar_by_key(key: str, val: Any) -> Any:
    """按字段名对敏感凭证与 11 位手机号脱敏；预览态未解析的 ${参数} 占位符保持原样。"""
    if isinstance(val, str) and _WHOLE_PLACEHOLDER_RE.match(val.strip()):
        return val
    if _is_sensitive_key(key):
        if val is None or val == "":
            return val
        return "***"
    if _is_phone_key(key) and isinstance(val, (str, int)) and not isinstance(val, bool):
        s = str(val)
        if _PHONE_11_RE.match(s):
            return f"{s[:3]}****{s[7:]}"
    return val


def mask_http_headers(headers: dict[str, str]) -> dict[str, str]:
    """脱敏 HTTP 请求头，屏蔽 Authorization / Token / Cookie / API-Key 等凭证原值。"""
    return {k: str(_mask_scalar_by_key(k, v)) for k, v in (headers or {}).items()}


def mask_http_url(url: str, *, keep_unresolved: bool = False) -> str:
    """脱敏 URL 中的认证口令与敏感 Query 参数（如 token/api_key/password/手机号）。"""
    if not url:
        return ""
    parsed = urlsplit(url)
    netloc = parsed.netloc
    if "@" in netloc:
        userinfo, hostport = netloc.rsplit("@", 1)
        if ":" in userinfo:
            user, _ = userinfo.split(":", 1)
            netloc = f"{user}:***@{hostport}"
        else:
            netloc = f"***@{hostport}"
    query = parsed.query
    if query:
        if keep_unresolved:
            parts: list[str] = []
            for seg in query.split("&"):
                if "=" in seg:
                    qk, qv = seg.split("=", 1)
                    parts.append(f"{qk}={_mask_scalar_by_key(qk, qv)}")
                else:
                    parts.append(seg)
            query = "&".join(parts)
        else:
            masked_pairs = [(k, str(_mask_scalar_by_key(k, v))) for k, v in parse_qsl(query, keep_blank_values=True)]
            query = urlencode(masked_pairs, doseq=True)
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, parsed.fragment))


def _mask_body_tree(node: Any) -> Any:
    """递归脱敏 JSON / 表单请求体中的凭证字段与 11 位手机号。"""
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in node.items():
            ks = str(k)
            if isinstance(v, (dict, list)):
                out[ks] = _mask_body_tree(v)
            else:
                out[ks] = _mask_scalar_by_key(ks, v)
        return out
    if isinstance(node, list):
        return [_mask_body_tree(item) for item in node]
    return node


def _merge_headers(defaults: dict[str, str], custom: dict[str, str]) -> dict[str, str]:
    """合并默认请求头与契约自定义请求头（忽略大小写，以用户配置优先）。"""
    merged = dict(defaults)
    lower_map = {k.lower(): k for k in merged}
    for k, v in (custom or {}).items():
        existed = lower_map.get(k.lower())
        if existed:
            merged.pop(existed, None)
        merged[k] = v
        lower_map[k.lower()] = k
    return merged


def _form_pairs(data: dict[str, Any]) -> list[tuple[str, str]]:
    """将表单字典转为 URL 编码键值列表（跳过 None，布尔转 true/false）。"""
    pairs: list[tuple[str, str]] = []
    for k, v in data.items():
        key = str(k).strip()
        if not key or v is None:
            continue
        if isinstance(v, list):
            for item in v:
                if item is None:
                    continue
                pairs.append((key, _scalar_to_text(item)))
        else:
            pairs.append((key, _scalar_to_text(v)))
    return pairs


def _scalar_to_text(val: Any) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False, separators=(",", ":"))
    return str(val)


def _format_http_preview(
    method: str,
    masked_url: str,
    masked_headers: dict[str, str],
    masked_body_text: str,
) -> str:
    """生成便于工作台与运行详单阅读的类 HTTP 请求脱敏预览文本。"""
    lines = [f"{method} {masked_url}"]
    for k, v in masked_headers.items():
        lines.append(f"{k}: {v}")
    if masked_body_text:
        lines.append("")
        lines.append(masked_body_text)
    return "\n".join(lines)


def _serialize_body(
    contract: ApiContract,
    req_data: Any,
    *,
    keep_unresolved: bool = False,
) -> tuple[dict[str, str], bytes | None, str]:
    """按 contract.bodyType 生成 (默认请求头, 原始发送字节, 脱敏预览体文本)。"""
    btype = contract.bodyType
    if btype == "none":
        return {"Accept": "application/json, */*"}, None, ""

    if btype == "json":
        obj = {} if req_data is None else req_data
        raw_text = json.dumps(obj, ensure_ascii=False, indent=2)
        masked_text = json.dumps(_mask_body_tree(obj), ensure_ascii=False, indent=2)
        return (
            {"Content-Type": "application/json; charset=utf-8", "Accept": "application/json, */*"},
            raw_text.encode("utf-8"),
            masked_text,
        )

    if btype == "form":
        if req_data is None:
            req_dict: dict[str, Any] = {}
        elif isinstance(req_data, dict):
            req_dict = req_data
        else:
            raise ValueError("bodyType=form 时 request 必须是键值映射对象")
        pairs = _form_pairs(req_dict)
        raw_text = urlencode(pairs, doseq=True)
        masked_dict = _mask_body_tree(req_dict)
        masked_pairs = _form_pairs(masked_dict)
        if keep_unresolved:
            masked_text = "&".join(f"{k}={v}" for k, v in masked_pairs)
        else:
            masked_text = urlencode(masked_pairs, doseq=True)
        return (
            {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8", "Accept": "application/json, */*"},
            raw_text.encode("utf-8"),
            masked_text,
        )

    if btype == "text":
        if req_data is None or req_data == {}:
            raw_text = ""
        elif isinstance(req_data, str):
            raw_text = req_data
        else:
            raise ValueError("bodyType=text 时 request 必须是字符串")
        return (
            {"Content-Type": "text/plain; charset=utf-8", "Accept": "*/*"},
            raw_text.encode("utf-8"),
            raw_text,
        )

    raise ValueError(f"不支持的请求体类型：{btype}")


def prepare_http_request(contract: ApiContract, args: dict[str, Any] | None = None) -> PreparedHttpRequest:
    """组装真实常规 HTTP 请求（含最终 URL、完整请求头、请求体字节与脱敏预览）。"""
    safe_args = args or {}
    final_url = contract.build_url(safe_args, keep_unresolved=False)
    custom_headers = contract.build_headers(safe_args, keep_unresolved=False)
    req_data = contract.build_request(safe_args)
    default_headers, payload_bytes, masked_body = _serialize_body(contract, req_data, keep_unresolved=False)
    merged_headers = _merge_headers(default_headers, custom_headers)
    preview = _format_http_preview(
        contract.method,
        mask_http_url(final_url, keep_unresolved=False),
        mask_http_headers(merged_headers),
        masked_body,
    )
    return PreparedHttpRequest(
        method=contract.method,
        url=final_url,
        headers=merged_headers,
        payload_bytes=payload_bytes,
        preview=preview,
    )


def build_http_request_preview(contract: ApiContract, args: dict[str, Any] | None = None) -> str:
    """按常规 HTTP 契约生成脱敏预览报文；未传入参数保留 ${参数名} 占位符。"""
    safe_args = args or {}
    preview_url = contract.build_url(safe_args, keep_unresolved=True)
    custom_headers = contract.build_headers(safe_args, keep_unresolved=True)
    req_data = contract.build_preview_request(safe_args)
    default_headers, _, masked_body = _serialize_body(contract, req_data, keep_unresolved=True)
    merged_headers = _merge_headers(default_headers, custom_headers)
    return _format_http_preview(
        contract.method,
        mask_http_url(preview_url, keep_unresolved=True),
        mask_http_headers(merged_headers),
        masked_body,
    )


def detect_http_response_format(
    contract: ApiContract,
    text: str,
    content_type: str | None = None,
) -> str:
    """判定常规 HTTP 响应体的解析格式：json / xml / text。"""
    configured = (contract.response.format or "auto").lower()
    if configured in ("json", "xml", "text"):
        return configured
    ct = (content_type or "").lower()
    stripped = (text or "").lstrip("\ufeff").strip()
    if "json" in ct or stripped.startswith(("{", "[")):
        return "json"
    if "xml" in ct or stripped.startswith("<"):
        return "xml"
    return "text"


def _parse_text_response(
    contract: ApiContract,
    text: str,
    status: int | None,
    cost: int,
    preview: str,
    attempts: int,
) -> ApiCallResult:
    """解析纯文本 HTTP 响应，兼容 noData / success / records.mode 语义并保留原始 raw 响应体。"""
    resp = contract.response
    stripped = text.strip()
    raw_clipped = text if len(text) <= 200_000 else text[:200_000]

    for rule in resp.noData:
        if (rule.equals is not None and stripped == rule.equals) or (rule.contains and rule.contains in stripped):
            return ApiCallResult(
                ok=True,
                records=[],
                http_status=status,
                cost_ms=cost,
                raw=raw_clipped,
                request_preview=preview,
                no_data=True,
                attempts=attempts,
            )

    if resp.success is not None:
        if not stripped:
            if resp.success.missingAs == "failure":
                return ApiCallResult(
                    ok=False,
                    error=f"响应内容为空，缺少 {resp.success.path}",
                    http_status=status,
                    cost_ms=cost,
                    raw=raw_clipped[:20_000],
                    request_preview=preview,
                    attempts=attempts,
                )
        elif stripped != resp.success.equals:
            return ApiCallResult(
                ok=False,
                error=f"响应文本不满足成功期望 {resp.success.equals!r}",
                http_status=status,
                cost_ms=cost,
                raw=raw_clipped[:20_000],
                request_preview=preview,
                attempts=attempts,
            )

    if resp.records.mode == "none":
        return ApiCallResult(
            ok=True,
            records=[],
            http_status=status,
            cost_ms=cost,
            raw=raw_clipped,
            request_preview=preview,
            no_data=False,
            attempts=attempts,
        )

    if not stripped:
        return ApiCallResult(
            ok=True,
            records=[],
            http_status=status,
            cost_ms=cost,
            raw=raw_clipped,
            request_preview=preview,
            no_data=True,
            attempts=attempts,
        )

    return ApiCallResult(
        ok=True,
        records=[{"value": stripped}],
        http_status=status,
        cost_ms=cost,
        raw=raw_clipped,
        request_preview=preview,
        no_data=False,
        attempts=attempts,
    )


def parse_http_response(
    contract: ApiContract,
    raw_body: bytes | str,
    status: int | None,
    cost: int,
    preview: str,
    *,
    content_type: str | None = None,
    charset: str | None = None,
    attempts: int = 1,
) -> ApiCallResult:
    """解析常规 HTTP 响应体，按格式分发至 JSON / XML 契约抽取或纯文本响应处理。"""
    text = decode_xml(raw_body, charset) if isinstance(raw_body, (bytes, bytearray)) else str(raw_body)
    stripped = text.lstrip("\ufeff").strip()

    # 空响应体（如 HTTP 204 No Content）处理
    if not stripped:
        resp = contract.response
        if resp.records.mode == "none":
            return ApiCallResult(
                ok=True,
                records=[],
                http_status=status,
                cost_ms=cost,
                raw="",
                request_preview=preview,
                no_data=False,
                attempts=attempts,
            )
        if resp.success is not None and resp.success.missingAs == "failure":
            return ApiCallResult(
                ok=False,
                error=f"响应内容为空，缺少 {resp.success.path}",
                http_status=status,
                cost_ms=cost,
                raw="",
                request_preview=preview,
                attempts=attempts,
            )
        return ApiCallResult(
            ok=True,
            records=[],
            http_status=status,
            cost_ms=cost,
            raw="",
            request_preview=preview,
            no_data=True,
            attempts=attempts,
        )

    fmt = detect_http_response_format(contract, text, content_type)
    if fmt == "json":
        try:
            data = parse_json_body(text)
        except (Exception, RecursionError) as exc:  # noqa: BLE001
            return ApiCallResult(
                ok=False,
                error=f"响应不是合法的 JSON：{exc}",
                http_status=status,
                cost_ms=cost,
                raw=text[:20_000],
                request_preview=preview,
                attempts=attempts,
            )
        try:
            result = extract_json_records(contract, data)
        except (Exception, RecursionError) as exc:  # noqa: BLE001
            return ApiCallResult(
                ok=False,
                error=f"JSON 响应解析失败：{exc}",
                http_status=status,
                cost_ms=cost,
                raw=text[:20_000],
                request_preview=preview,
                attempts=attempts,
            )
        result.http_status = status
        result.cost_ms = cost
        if len(text) <= 200_000:
            try:
                pretty = json.dumps(data, ensure_ascii=False, indent=2)
            except (Exception, RecursionError):  # noqa: BLE001
                pretty = text
            result.raw = pretty if len(pretty) <= 200_000 else pretty[:200_000]
        else:
            result.raw = text[:200_000]
        result.request_preview = preview
        result.attempts = attempts
        return result

    if fmt == "xml":
        try:
            root = parse_xml(text)
        except Exception as exc:  # noqa: BLE001
            return ApiCallResult(
                ok=False,
                error=f"响应不是合法的 XML：{exc}",
                http_status=status,
                cost_ms=cost,
                raw=text[:20_000],
                request_preview=preview,
                attempts=attempts,
            )
        result = extract_records(contract, root)
        result.http_status = status
        result.cost_ms = cost
        result.raw = text if len(text) <= 200_000 else text[:200_000]
        result.request_preview = preview
        result.attempts = attempts
        return result

    return _parse_text_response(contract, text, status, cost, preview, attempts)
