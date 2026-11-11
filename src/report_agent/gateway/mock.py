"""mock 网关：读取 data/mock-gateway 下的样例响应，用于本地开发和演示。

#Created By AiCoding(codex)
查找顺序：<接口名>.<手机号>.xml → <接口名>.xml。找不到时返回调用失败。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from ..domain.api_contract import ApiContract
from .base import ApiCallResult, decode_xml, parse_xml, xml_to_json_data
from .unified_xml import (build_request_json, build_request_xml, mask_json, mask_xml, parse_gateway_json_response,
                          parse_gateway_response)

_SAFE_MOCK_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")


class MockGatewayClient:
    """从文件读取响应的网关（支持 XML 与 JSON 双协议，JSON 模式兼容同名 XML 样例自动转换）。"""

    def __init__(self, root: Path, style: str = "java") -> None:
        self.root = root
        self.style = style

    async def aclose(self) -> None:
        return None

    def _safe_file(self, path: Path, root_resolved: Path) -> Path | None:
        try:
            resolved = path.resolve()
        except OSError:
            return None
        if not resolved.is_relative_to(root_resolved) or not resolved.is_file():
            return None
        return resolved

    async def invoke(self, contract: ApiContract, args: dict[str, Any]) -> ApiCallResult:
        start = time.monotonic()
        try:
            request = contract.build_request(args)
            contract.build_headers(args)
            if contract.is_json:
                preview = mask_json(build_request_json(contract.processCode, request, "mock", "mock"))
            else:
                preview = mask_xml(build_request_xml(contract.processCode, request, "mock", "mock", self.style))
        except ValueError as exc:
            return ApiCallResult(ok=False, error=f"请求报文组装失败：{exc}")
        if not _SAFE_MOCK_NAME_RE.match(contract.name or ""):
            return ApiCallResult(ok=False, error=f"非法的接口名称：{contract.name!r}", request_preview=preview)
        root_resolved = self.root.resolve()
        route = str(request.get("route_value") or "").strip()
        valid_route = bool(route and route.isascii() and route.isdigit())

        if contract.is_json:
            json_candidates: list[Path] = []
            if valid_route:
                json_candidates.append(self.root / f"{contract.name}.{route}.json")
            json_candidates.append(self.root / f"{contract.name}.json")
            for path in json_candidates:
                resolved = self._safe_file(path, root_resolved)
                if resolved is None:
                    continue
                try:
                    raw_bytes = resolved.read_bytes()
                except OSError as exc:
                    return ApiCallResult(ok=False, error=f"读取样例响应失败：{exc}", request_preview=preview)
                text = decode_xml(raw_bytes, None)
                cost = int((time.monotonic() - start) * 1000)
                return parse_gateway_json_response(contract, text, 200, cost, preview)

            xml_fallbacks: list[Path] = []
            if valid_route:
                xml_fallbacks.append(self.root / f"{contract.name}.{route}.xml")
            xml_fallbacks.append(self.root / f"{contract.name}.xml")
            for path in xml_fallbacks:
                resolved = self._safe_file(path, root_resolved)
                if resolved is None:
                    continue
                try:
                    raw_bytes = resolved.read_bytes()
                except OSError as exc:
                    return ApiCallResult(ok=False, error=f"读取样例响应失败：{exc}", request_preview=preview)
                xml_text = decode_xml(raw_bytes, None)
                try:
                    root_el = parse_xml(xml_text)
                    json_text = json.dumps(xml_to_json_data(root_el), ensure_ascii=False, indent=2)
                except Exception as exc:  # noqa: BLE001
                    return ApiCallResult(ok=False, error=f"样例 XML 转换 JSON 失败：{exc}", request_preview=preview)
                cost = int((time.monotonic() - start) * 1000)
                return parse_gateway_json_response(contract, json_text, 200, cost, preview)

            return ApiCallResult(ok=False, error=f"mock 模式下没有找到样例响应 {contract.name}.json",
                                 request_preview=preview)

        candidates: list[Path] = []
        if valid_route:
            candidates.append(self.root / f"{contract.name}.{route}.xml")
        candidates.append(self.root / f"{contract.name}.xml")
        for path in candidates:
            resolved = self._safe_file(path, root_resolved)
            if resolved is None:
                continue
            try:
                raw_bytes = resolved.read_bytes()
            except OSError as exc:
                return ApiCallResult(ok=False, error=f"读取样例响应失败：{exc}", request_preview=preview)
            text = decode_xml(raw_bytes, None)
            return parse_gateway_response(contract, text, 200, int((time.monotonic() - start) * 1000), preview)
        return ApiCallResult(ok=False, error=f"mock 模式下没有找到样例响应 {contract.name}.xml", request_preview=preview)
