"""mock 网关：读取 data/mock-gateway 下的样例响应，用于本地开发和演示。

#Created By AiCoding(codex)
查找顺序：<接口名>.<手机号>.xml → <接口名>.xml。找不到时返回调用失败。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

from ..domain.api_contract import ApiContract
from ..domain.sanitize import sanitize_sensitive_text
from .base import (
    ApiCallResult,
    decode_xml,
    parse_gateway_json_response,
    parse_gateway_response,
    parse_xml,
    xml_to_json_data,
)
from .http_client import parse_http_response, prepare_http_request
from .unified_xml import build_masked_request_json, build_request_xml, mask_xml

_SAFE_MOCK_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")
_SAFE_MOCK_ROUTE_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_PHONE_11_RE = re.compile(r"^1\d{10}$")
_PREFERRED_PHONE_KEYS = (
    "手机号码",
    "客户号码",
    "联系号码",
    "号码",
    "mobile",
    "mobileNo",
    "userMobile",
    "user_mobile",
    "phone",
    "phoneNo",
    "msisdn",
    "billId",
    "bill_id",
    "route_value",
)
_PHONE_KEY_HINTS = ("手机", "号码", "电话", "mobile", "phone", "msisdn", "billid", "bill_id", "route")


def _extract_http_mock_route(args: dict[str, Any]) -> str:
    """从入参中提取可用于定位专属 Mock 样例的安全路由值（优先手机号参数与 11 位手机号值）。#Created By AiCoding(codex)"""
    if not isinstance(args, dict):
        return ""
    for preferred in _PREFERRED_PHONE_KEYS:
        val = str(args.get(preferred) or "").strip()
        if val and _SAFE_MOCK_ROUTE_RE.match(val):
            return val
    for k, raw in args.items():
        low_k = str(k).lower()
        val = str(raw or "").strip()
        if val and any(h in low_k for h in _PHONE_KEY_HINTS) and _SAFE_MOCK_ROUTE_RE.match(val):
            return val
    for val in args.values():
        s = str(val or "").strip()
        if s and s.isascii() and _PHONE_11_RE.match(s):
            return s
    for val in args.values():
        s = str(val or "").strip()
        if s and s.isascii() and s.isdigit() and len(s) <= 32:
            return s
    return ""


def _http_mock_exts(resp_format: str) -> tuple[str, ...]:
    fmt = (resp_format or "auto").lower()
    if fmt == "xml":
        return ("xml", "json", "txt")
    if fmt == "text":
        return ("txt", "json", "xml")
    return ("json", "xml", "txt")


class MockGatewayClient:
    """从文件读取响应的网关（支持 XML 与 JSON 双协议，优先读取 root，未命中时可选回退 fallback_root）。"""

    def __init__(self, root: Path, style: str = "java", fallback_root: Path | None = None) -> None:
        self.root = root
        self.style = style
        self.fallback_root = fallback_root

    async def aclose(self) -> None:
        return None

    def _search_roots(self) -> list[tuple[Path, Path]]:
        roots: list[tuple[Path, Path]] = []
        seen: set[Path] = set()
        for candidate in (self.root, self.fallback_root):
            if candidate is None:
                continue
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved not in seen:
                seen.add(resolved)
                roots.append((candidate, resolved))
        return roots

    @staticmethod
    def _safe_file(path: Path, root_resolved: Path) -> Path | None:
        try:
            resolved = path.resolve()
        except OSError:
            return None
        if not resolved.is_relative_to(root_resolved) or not resolved.is_file():
            return None
        return resolved

    def _find_candidate(self, names: list[str], roots: list[tuple[Path, Path]]) -> Path | None:
        for base, base_resolved in roots:
            for fname in names:
                resolved = self._safe_file(base / fname, base_resolved)
                if resolved is not None:
                    return resolved
        return None

    async def invoke(self, contract: ApiContract, args: dict[str, Any]) -> ApiCallResult:
        return await asyncio.to_thread(self._invoke_sync, contract, args)

    def _invoke_sync(self, contract: ApiContract, args: dict[str, Any]) -> ApiCallResult:
        start = time.monotonic()
        if contract.is_http:
            return self._invoke_http_mock(contract, args, start)
        try:
            request = contract.build_request(args)
            contract.build_headers(args)
            if contract.is_json:
                preview = build_masked_request_json(contract.processCode, request)
            else:
                preview = mask_xml(build_request_xml(contract.processCode, request, "mock", "mock", self.style))
        except ValueError as exc:
            return ApiCallResult(ok=False, error=sanitize_sensitive_text(f"请求报文组装失败：{exc}"))
        if not _SAFE_MOCK_NAME_RE.match(contract.name or ""):
            return ApiCallResult(ok=False, error=f"非法的接口名称：{contract.name!r}", request_preview=preview)
        roots = self._search_roots()
        route = str(request.get("route_value") or "").strip()
        if not route:
            fallback_route = _extract_http_mock_route(args)
            if fallback_route.isascii() and _PHONE_11_RE.match(fallback_route):
                route = fallback_route
        valid_route = bool(route and route.isascii() and route.isdigit())

        if contract.is_json:
            json_names = ([f"{contract.name}.{route}.json"] if valid_route else []) + [f"{contract.name}.json"]
            json_hit = self._find_candidate(json_names, roots)
            if json_hit is not None:
                try:
                    raw_bytes = json_hit.read_bytes()
                except OSError as exc:
                    return ApiCallResult(
                        ok=False,
                        error=sanitize_sensitive_text(f"读取样例响应失败：{exc}"),
                        request_preview=preview,
                    )
                text = decode_xml(raw_bytes, None)
                cost = int((time.monotonic() - start) * 1000)
                return parse_gateway_json_response(contract, text, 200, cost, preview)

            xml_names = ([f"{contract.name}.{route}.xml"] if valid_route else []) + [f"{contract.name}.xml"]
            xml_hit = self._find_candidate(xml_names, roots)
            if xml_hit is not None:
                try:
                    raw_bytes = xml_hit.read_bytes()
                except OSError as exc:
                    return ApiCallResult(
                        ok=False,
                        error=sanitize_sensitive_text(f"读取样例响应失败：{exc}"),
                        request_preview=preview,
                    )
                xml_text = decode_xml(raw_bytes, None)
                try:
                    root_el = parse_xml(xml_text)
                    json_text = json.dumps(xml_to_json_data(root_el), ensure_ascii=False, indent=2)
                except Exception as exc:  # noqa: BLE001
                    return ApiCallResult(
                        ok=False,
                        error=sanitize_sensitive_text(f"样例 XML 转换 JSON 失败：{exc}"),
                        request_preview=preview,
                    )
                cost = int((time.monotonic() - start) * 1000)
                return parse_gateway_json_response(contract, json_text, 200, cost, preview)

            return ApiCallResult(ok=False, error=f"mock 模式下没有找到样例响应 {contract.name}.json",
                                 request_preview=preview)

        xml_names = ([f"{contract.name}.{route}.xml"] if valid_route else []) + [f"{contract.name}.xml"]
        xml_hit = self._find_candidate(xml_names, roots)
        if xml_hit is not None:
            try:
                raw_bytes = xml_hit.read_bytes()
            except OSError as exc:
                return ApiCallResult(
                    ok=False,
                    error=sanitize_sensitive_text(f"读取样例响应失败：{exc}"),
                    request_preview=preview,
                )
            text = decode_xml(raw_bytes, None)
            return parse_gateway_response(contract, text, 200, int((time.monotonic() - start) * 1000), preview)
        return ApiCallResult(ok=False, error=f"mock 模式下没有找到样例响应 {contract.name}.xml", request_preview=preview)

    def _invoke_http_mock(self, contract: ApiContract, args: dict[str, Any], start: float) -> ApiCallResult:
        """常规 HTTP 接口本地 Mock 回放：按 <接口名>[.<路由值>].<json|xml|txt> 查找样例并走同一响应解析链路。#Created By AiCoding(codex)"""
        try:
            prepared = prepare_http_request(contract, args)
        except ValueError as exc:
            return ApiCallResult(ok=False, error=sanitize_sensitive_text(f"HTTP 请求组装失败：{exc}"))
        if not _SAFE_MOCK_NAME_RE.match(contract.name or ""):
            return ApiCallResult(ok=False, error=f"非法的接口名称：{contract.name!r}",
                                 request_preview=prepared.preview)
        roots = self._search_roots()
        route = _extract_http_mock_route(args)
        exts = _http_mock_exts(contract.response.format)
        candidates: list[str] = []
        if route:
            candidates.extend(f"{contract.name}.{route}.{ext}" for ext in exts)
        candidates.extend(f"{contract.name}.{ext}" for ext in exts)
        hit = self._find_candidate(candidates, roots)
        if hit is None:
            return ApiCallResult(
                ok=False,
                error=f"mock 模式下没有找到样例响应 {contract.name}.{exts[0]}（也支持 .xml / .txt）",
                request_preview=prepared.preview,
            )
        try:
            raw_bytes = hit.read_bytes()
        except OSError as exc:
            return ApiCallResult(
                ok=False,
                error=sanitize_sensitive_text(f"读取样例响应失败：{exc}"),
                request_preview=prepared.preview,
            )
        ext_ct = {".json": "application/json", ".xml": "application/xml", ".txt": "text/plain"}.get(
            hit.suffix.lower(), ""
        )
        cost = int((time.monotonic() - start) * 1000)
        return parse_http_response(contract, raw_bytes, 200, cost, prepared.preview, content_type=ext_ct)
