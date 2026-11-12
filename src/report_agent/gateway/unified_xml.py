"""统一网关 XML 连接器：POST {GATEWAY_URL}/openapi_3，报文根元素 operation_in / operation_out。

#Created By AiCoding(codex)
协议来自现有 Java 实现（CommonRequestToolService#xmlNytool + XmlBaseRequest）：
  - 无签名，鉴权只靠报文中的 app_id、access_token；
  - java 风格：与 Jackson XmlMapper 实际输出逐字一致（顶层元素按字母序、未赋值字段输出 xsi:nil、无 XML 声明）；
  - clean 风格：按声明顺序、空值输出空标签、带 UTF-8 声明。网关确认兼容后可切换。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any
from xml.sax.saxutils import escape

import httpx

from ..domain.api_contract import ApiContract
from .base import (ApiCallResult, decode_xml, extract_json_records, extract_records, parse_json_body, parse_xml,
                   sanitize_xml_text)

log = logging.getLogger(__name__)

OPENAPI_PATH = "/openapi_3"
_NIL = ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:nil="true"'
_XML_TAG_RE = re.compile(r"^[A-Za-z_][\w.\-]*$")
# XmlBaseRequest 字段默认值
_DEFAULTS = {"request_type": "1", "organ_id": "1", "route_type": "1", "request_source": "1"}
# 非空才覆盖默认值的字段（Java setIfNotNull）
_IF_NOT_BLANK = ("request_type", "organ_id", "route_type", "route_value", "request_source", "request_time",
                 "verify_code")
# 只要提供（含空串）就保留的字段（Java setIfPresent）
_IF_PRESENT = ("operator_id", "request_seq")
_JAVA_ORDER = sorted(["process_code", "app_id", "access_token", "request_type", "organ_id", "operator_id",
                      "route_type", "route_value", "request_seq", "request_source", "request_time", "verify_code",
                      "content"])
_CLEAN_ORDER = ["process_code", "app_id", "access_token", "request_type", "organ_id", "operator_id", "route_type",
                "route_value", "request_seq", "request_source", "request_time", "verify_code", "content"]
_JSON_ORDER = ["process_code", "app_id", "access_token", "request_type", "organ_id", "route_type", "route_value",
               "operator_id", "request_seq", "request_source", "request_time", "verify_code", "content"]
_ENVELOPE_KEYS = frozenset(_JSON_ORDER)


def _validate_tag(tag: str) -> str:
    if not isinstance(tag, str) or not _XML_TAG_RE.match(tag):
        raise ValueError(f"非法的 XML 标签名：{tag!r}")
    return tag


def _element(tag: str, value: Any, style: str) -> str:
    """序列化一个元素。dict 递归，list 输出同名重复元素，None 按风格输出 nil 或空标签。"""
    _validate_tag(tag)
    if value is None:
        return f"<{tag}{_NIL}/>" if style == "java" else f"<{tag}></{tag}>"
    if isinstance(value, dict):
        inner = "".join(_element(str(k), v, style) for k, v in value.items())
        return f"<{tag}>{inner}</{tag}>"
    if isinstance(value, list):
        return "".join(_element(tag, v, style) for v in value)
    if isinstance(value, bool):
        value = "true" if value else "false"
    cleaned = sanitize_xml_text(str(value))
    return f"<{tag}>{escape(cleaned)}</{tag}>"


def build_request_xml(process_code: str, request: dict[str, Any], app_id: str, access_token: str,
                      style: str = "java") -> str:
    """按统一网关协议组装 operation_in 报文。"""
    request = request if isinstance(request, dict) else {}
    fields: dict[str, Any] = {
        "process_code": process_code,
        "app_id": request.get("app_id", app_id),
        "access_token": request.get("access_token", access_token),
        **_DEFAULTS,
        "operator_id": None, "route_value": None, "request_seq": None, "request_time": None, "verify_code": None,
    }
    for key in _IF_NOT_BLANK:
        val = request.get(key)
        if val is not None and str(val).strip():
            fields[key] = str(val)
    for key in _IF_PRESENT:
        if key in request and request[key] is not None:
            fields[key] = str(request[key])
    content = request.get("content")
    fields["content"] = content if isinstance(content, dict) else {}
    if style == "java":
        return "<operation_in>" + "".join(_element(k, fields[k], style) for k in _JAVA_ORDER) + "</operation_in>"
    for key in ("operator_id", "request_seq", "route_value"):
        if fields[key] is None:
            fields[key] = ""
    order = [k for k in _CLEAN_ORDER if not (k in ("request_time", "verify_code") and fields[k] is None)]
    return ('<?xml version="1.0" encoding="UTF-8"?><operation_in>'
            + "".join(_element(k, fields[k], style) for k in order) + "</operation_in>")


_MASK_TAGS = ("app_id", "access_token")
_MASK_NONEMPTY_TAGS = ("verify_code",)
_PHONE_TAGS = ("route_value", "userMobile", "mobile", "phone", "billId", "msisdn")
_PHONE_11_RE = re.compile(r"^\d{11}$")
_XML_MASK_RES = (
    *((re.compile(rf"(<{tag}>)[^<]*(</{tag}>)"), r"\1***\2") for tag in _MASK_TAGS),
    *((re.compile(rf"(<{tag}>)(?!\$\{{[^}}]+\}}<)[^<]+(</{tag}>)"), r"\1***\2") for tag in _MASK_NONEMPTY_TAGS),
    *((re.compile(rf"(<{tag}>)(\d{{3}})\d{{4}}(\d{{4}})(</{tag}>)"), r"\1\2****\3\4") for tag in _PHONE_TAGS),
)
_JSON_FALLBACK_MASK_RES = (
    *((re.compile(rf'("{tag}"\s*:\s*)"[^"]*"'), r'\1"***"') for tag in (*_MASK_TAGS, *_MASK_NONEMPTY_TAGS)),
    *((re.compile(rf'("{tag}"\s*:\s*")(\d{{3}})\d{{4}}(\d{{4}}")'), r"\1\2****\3") for tag in _PHONE_TAGS),
)


def mask_xml(xml: str) -> str:
    """日志与管理端展示用的脱敏报文。"""
    for pattern, repl in _XML_MASK_RES:
        xml = pattern.sub(repl, xml)
    return xml


def _sanitize_json_value(val: Any, _depth: int = 0) -> Any:
    """递归清理 JSON 字符串中的非法控制字符，保留原生标量/数组/对象类型并限制最大嵌套深度。"""
    if _depth > 128:
        raise ValueError("JSON 请求体嵌套层级超过安全上限（128 层）")
    if isinstance(val, str):
        return sanitize_xml_text(val)
    if isinstance(val, dict):
        return {str(k): _sanitize_json_value(v, _depth + 1) for k, v in val.items()}
    if isinstance(val, list):
        return [_sanitize_json_value(v, _depth + 1) for v in val]
    return val


def _build_request_json_obj(
    process_code: str, request: dict[str, Any], app_id: str, access_token: str
) -> dict[str, Any]:
    """按统一网关 JSON 协议构造 {"operation_in": {...}} 请求字典。"""
    raw_req = request if isinstance(request, dict) else {}
    if isinstance(raw_req.get("operation_in"), dict) and set(raw_req.keys()) == {"operation_in"}:
        raw_req = raw_req["operation_in"]
    fields: dict[str, Any] = {
        "process_code": sanitize_xml_text(str(process_code)),
        "app_id": sanitize_xml_text(str(raw_req.get("app_id", app_id))),
        "access_token": sanitize_xml_text(str(raw_req.get("access_token", access_token))),
        **_DEFAULTS,
        "route_value": None,
        "operator_id": None,
        "request_seq": None,
        "request_time": None,
        "verify_code": None,
    }
    for key in _IF_NOT_BLANK:
        val = raw_req.get(key)
        if val is not None and str(val).strip():
            fields[key] = sanitize_xml_text(str(val))
    for key in _IF_PRESENT:
        if key in raw_req and raw_req[key] is not None:
            fields[key] = sanitize_xml_text(str(raw_req[key]))
    raw_content = raw_req.get("content")
    fields["content"] = _sanitize_json_value(raw_content) if raw_content is not None else {}

    envelope: dict[str, Any] = {k: fields[k] for k in _JSON_ORDER}
    for k, v in raw_req.items():
        ks = str(k)
        if ks not in _ENVELOPE_KEYS:
            envelope[ks] = _sanitize_json_value(v)
    return {"operation_in": envelope}


def build_request_json(process_code: str, request: dict[str, Any], app_id: str, access_token: str) -> str:
    """按统一网关 JSON 协议组装 {"operation_in": {...}} UTF-8 格式化请求报文。"""
    return json.dumps(_build_request_json_obj(process_code, request, app_id, access_token), ensure_ascii=False, indent=2)


def _mask_json_node(node: Any) -> Any:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k in _MASK_TAGS:
                out[k] = "***"
            elif k in _MASK_NONEMPTY_TAGS:
                if v is None or v == "":
                    out[k] = v
                elif isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                    out[k] = v
                else:
                    out[k] = "***"
            elif k in _PHONE_TAGS:
                if isinstance(v, (str, int)) and not isinstance(v, bool):
                    s = str(v)
                    out[k] = f"{s[:3]}****{s[7:]}" if _PHONE_11_RE.match(s) else v
                else:
                    out[k] = _mask_json_node(v)
            else:
                out[k] = _mask_json_node(v)
        return out
    if isinstance(node, list):
        return [_mask_json_node(item) for item in node]
    return node


def mask_json(text: str) -> str:
    """脱敏统一网关 JSON 报文（app_id/access_token/verify_code 与 11 位手机号），输出 2 空格缩进 JSON。"""
    try:
        parsed = json.loads(text)
    except Exception:  # noqa: BLE001
        fallback = text
        for pattern, repl in _JSON_FALLBACK_MASK_RES:
            fallback = pattern.sub(repl, fallback)
        return fallback
    return json.dumps(_mask_json_node(parsed), ensure_ascii=False, indent=2)


def build_masked_request_json(process_code: str, request: dict[str, Any]) -> str:
    """直接构造脱敏后的 JSON 请求预览文本，避免重复反序列化开销。"""
    obj = _build_request_json_obj(process_code, request, "preview", "preview")
    return json.dumps(_mask_json_node(obj), ensure_ascii=False, indent=2)


def build_request_preview(contract: ApiContract, args: dict[str, Any] | None = None, style: str = "java") -> str:
    """按契约协议生成脱敏请求预览报文；未传入的参数保留 ${参数名} 占位符。"""
    preview_req = contract.build_preview_request(args or {})
    if contract.is_json:
        return build_masked_request_json(contract.processCode, preview_req)
    return mask_xml(build_request_xml(contract.processCode, preview_req, "preview", "preview", style))


def _merge_http_headers(defaults: dict[str, str], custom: dict[str, str]) -> dict[str, str]:
    """合并默认网关请求头与契约自定义安全请求头（忽略大小写去重）。"""
    merged = dict(defaults)
    lower_to_actual = {k.lower(): k for k in merged}
    for k, v in (custom or {}).items():
        existing = lower_to_actual.get(k.lower())
        if existing:
            merged.pop(existing, None)
        merged[k] = v
        lower_to_actual[k.lower()] = k
    return merged


def _classify_http_error(status: int) -> str:
    """将非 200 HTTP 状态码分类为明确的网关错误说明。"""
    if 300 <= status < 400:
        return f"网关返回重定向 HTTP {status}（已禁止跟随重定向）"
    if status in (401, 403):
        return f"网关鉴权失败 HTTP {status}"
    if status == 404:
        return "网关地址不存在 HTTP 404"
    if status == 429:
        return "网关限流 HTTP 429"
    if 400 <= status < 500:
        return f"网关请求被拒绝 HTTP {status}"
    if status >= 500:
        return f"网关服务端错误 HTTP {status}"
    return f"网关返回非预期状态 HTTP {status}"


class UnifiedGatewayXmlClient:
    """真实统一网关调用（内置可配置并发信号量保护）。#Created By AiCoding(codex)"""

    def __init__(self, base_url: str, app_id: str, access_token: str, style: str = "java",
                 connect_timeout_s: float = 5.0, max_concurrency: int | None = None) -> None:
        clean_url = (base_url or "").strip()
        if not clean_url:
            raise ValueError("GATEWAY_MODE=live 时必须配置 GATEWAY_URL")
        if not clean_url.startswith(("http://", "https://")):
            raise ValueError("GATEWAY_URL 必须以 http:// 或 https:// 开头")
        if max_concurrency is None:
            env_val = (os.getenv("GATEWAY_MAX_CONCURRENCY") or "").strip()
            try:
                eff_concurrency = int(env_val) if env_val else 32
            except ValueError:
                eff_concurrency = 32
        else:
            eff_concurrency = int(max_concurrency)
        self.url = clean_url.rstrip("/") + OPENAPI_PATH
        self.app_id = app_id
        self.access_token = access_token
        self.style = style
        self.connect_timeout_s = connect_timeout_s
        self.max_concurrency = max(1, eff_concurrency)
        self._sem = asyncio.Semaphore(self.max_concurrency)
        self._client = httpx.AsyncClient(
            follow_redirects=False,
            limits=httpx.Limits(
                max_connections=max(100, self.max_concurrency),
                max_keepalive_connections=min(32, self.max_concurrency),
            ),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def invoke(self, contract: ApiContract, args: dict[str, Any]) -> ApiCallResult:
        """调用接口。按 contract.is_json 分发 JSON 或 XML 请求，复用相同的超时与幂等重试策略。"""
        try:
            request = contract.build_request(args)
            custom_headers = contract.build_headers(args)
            if contract.is_json:
                req_obj = _build_request_json_obj(contract.processCode, request, self.app_id, self.access_token)
                payload = json.dumps(req_obj, ensure_ascii=False, indent=2)
                preview = json.dumps(_mask_json_node(req_obj), ensure_ascii=False, indent=2)
                headers = _merge_http_headers(
                    {"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"},
                    custom_headers,
                )
            else:
                payload = build_request_xml(contract.processCode, request, self.app_id, self.access_token, self.style)
                preview = mask_xml(payload)
                headers = _merge_http_headers(
                    {"Content-Type": "application/xml", "Accept": "application/xml"},
                    custom_headers,
                )
        except ValueError as exc:
            return ApiCallResult(ok=False, error=f"请求报文组装失败：{exc}")
        attempts = contract.retry.maxAttempts if contract.idempotent else 1
        timeout = httpx.Timeout(contract.timeoutMs / 1000, connect=self.connect_timeout_s)
        payload_bytes = payload.encode("utf-8")
        start = time.monotonic()
        last_error = ""
        for attempt in range(1, attempts + 1):
            try:
                async with self._sem:
                    resp = await self._client.post(
                        self.url, content=payload_bytes, timeout=timeout, headers=headers,
                    )
            except httpx.ConnectTimeout as exc:
                last_error = f"网关连接超时（>{self.connect_timeout_s:g}s）：{type(exc).__name__} {exc}".strip()
                log.warning("网关 %s 第 %d/%d 次调用连接超时：%s", contract.processCode, attempt, attempts, exc)
                if attempt < attempts:
                    await asyncio.sleep(0.5 * 2 ** (attempt - 1))
                    continue
                return ApiCallResult(ok=False, error=last_error, cost_ms=_ms(start), request_preview=preview,
                                     attempts=attempt)
            except httpx.TimeoutException as exc:
                last_error = f"网关响应超时（>{contract.timeoutMs}ms）：{type(exc).__name__} {exc}".strip()
                log.warning("网关 %s 第 %d/%d 次调用响应超时：%s", contract.processCode, attempt, attempts, exc)
                if attempt < attempts:
                    await asyncio.sleep(0.5 * 2 ** (attempt - 1))
                    continue
                return ApiCallResult(ok=False, error=last_error, cost_ms=_ms(start), request_preview=preview,
                                     attempts=attempt)
            except httpx.TransportError as exc:
                last_error = f"网关调用失败：{type(exc).__name__} {exc}".strip()
                log.warning("网关 %s 第 %d/%d 次调用网络异常：%s", contract.processCode, attempt, attempts, exc)
                if attempt < attempts:
                    await asyncio.sleep(0.5 * 2 ** (attempt - 1))
                    continue
                return ApiCallResult(ok=False, error=last_error, cost_ms=_ms(start), request_preview=preview,
                                     attempts=attempt)
            except (httpx.HTTPError, RuntimeError) as exc:
                last_error = f"网关请求异常：{type(exc).__name__} {exc}".strip()
                return ApiCallResult(ok=False, error=last_error, cost_ms=_ms(start), request_preview=preview,
                                     attempts=attempt)
            cost = _ms(start)
            text = decode_xml(resp.content, resp.charset_encoding)
            log.info("网关 %s 返回 HTTP %s，%d ms，%d 字节", contract.processCode, resp.status_code, cost, len(resp.content))
            if resp.status_code != 200:
                err_msg = _classify_http_error(resp.status_code)
                if resp.status_code in (429, 502, 503, 504) and contract.idempotent and attempt < attempts:
                    last_error = err_msg
                    log.warning("网关 %s 第 %d/%d 次返回 HTTP %s，准备重试", contract.processCode, attempt, attempts,
                                resp.status_code)
                    await asyncio.sleep(0.5 * 2 ** (attempt - 1))
                    continue
                return ApiCallResult(ok=False, error=err_msg, http_status=resp.status_code,
                                     cost_ms=cost, raw=text[:20000], request_preview=preview, attempts=attempt)
            if contract.is_json:
                return parse_gateway_json_response(contract, text, resp.status_code, cost, preview, attempt)
            return parse_gateway_response(contract, text, resp.status_code, cost, preview, attempt)
        return ApiCallResult(ok=False, error=last_error or "网关调用失败", cost_ms=_ms(start), request_preview=preview)


def parse_gateway_response(contract: ApiContract, text: str, status: int | None, cost: int, preview: str,
                           attempts: int = 1) -> ApiCallResult:
    """解析网关 XML 响应文本。"""
    try:
        root = parse_xml(text)
    except Exception as exc:  # noqa: BLE001 - XML 解析错误类型较多
        return ApiCallResult(ok=False, error=f"响应不是合法的 XML：{exc}", http_status=status, cost_ms=cost,
                             raw=text[:20000], request_preview=preview, attempts=attempts)
    result = extract_records(contract, root)
    result.http_status = status
    result.cost_ms = cost
    result.raw = text if len(text) <= 200000 else text[:200000]
    result.request_preview = preview
    result.attempts = attempts
    return result


def parse_gateway_json_response(contract: ApiContract, text: str, status: int | None, cost: int, preview: str,
                                attempts: int = 1) -> ApiCallResult:
    """解析网关 JSON 响应文本，并输出格式化 raw 报文。"""
    try:
        data = parse_json_body(text)
    except (Exception, RecursionError) as exc:  # noqa: BLE001
        return ApiCallResult(ok=False, error=f"响应不是合法的 JSON：{exc}", http_status=status, cost_ms=cost,
                             raw=text[:20000], request_preview=preview, attempts=attempts)
    try:
        result = extract_json_records(contract, data)
    except (Exception, RecursionError) as exc:  # noqa: BLE001
        return ApiCallResult(ok=False, error=f"JSON 响应解析失败：{exc}", http_status=status, cost_ms=cost,
                             raw=text[:20000], request_preview=preview, attempts=attempts)
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


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
