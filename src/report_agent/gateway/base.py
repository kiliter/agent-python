"""网关调用的公共结构：调用结果、XML 解析、按契约抽取记录。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
import xml.parsers.expat as expat
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..domain.api_contract import ApiContract

MAX_XML_CHARS = 5_000_000
MAX_JSON_CHARS = 5_000_000
_XSI_NIL_ATTRS = ("{http://www.w3.org/2001/XMLSchema-instance}nil", "xsi:nil", "nil")
# XML 1.0 非法控制字符（保留 \t \n \r）及代理对/非字符，以及对应的数字字符引用
_INVALID_XML_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
_INVALID_XML_CHAR_REF_RE = re.compile(
    r"&#(?:0*(?:[0-8]|1[12]|1[4-9]|2\d|3[01])|x0*(?:[0-8bcef]|1[0-9a-f]));",
    re.IGNORECASE,
)


@dataclass
class ApiCallResult:
    """一次接口调用的结果。records 中每条记录是 列名→文本 的字典。"""

    ok: bool
    records: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None
    http_status: int | None = None
    cost_ms: int = 0
    raw: str = ""
    request_preview: str = ""
    no_data: bool = False
    attempts: int = 1


class GatewayClient(Protocol):
    """接口调用方。"""

    async def invoke(self, contract: ApiContract, args: dict[str, Any]) -> ApiCallResult: ...

    async def aclose(self) -> None: ...


_DECL_RE = re.compile(rb"^(?:\xef\xbb\xbf)?\s*<\?xml[^>]*encoding=[\"']([A-Za-z0-9_\-]+)[\"']", re.I)


def sanitize_xml_text(text: str) -> str:
    """移除 XML 1.0 不允许的控制字符与非法数字字符引用。"""
    if not text:
        return ""
    cleaned = text.lstrip("\ufeff")
    cleaned = _INVALID_XML_CHAR_REF_RE.sub("", cleaned)
    return _INVALID_XML_CHARS_RE.sub("", cleaned)


def decode_xml(body: bytes, header_charset: str | None) -> str:
    """把响应字节解码为文本：优先 XML 声明中的编码，其次 HTTP 头，最后 UTF-8。"""
    if body.startswith(b"\xef\xbb\xbf"):
        body = body[3:]
    m = _DECL_RE.match(body)
    for enc in (m.group(1).decode("ascii", "ignore") if m else None, header_charset, "utf-8", "gb18030"):
        if not enc:
            continue
        try:
            return body.decode(enc).lstrip("\ufeff")
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace").lstrip("\ufeff")


def _check_xml_security(xml_text: str) -> None:
    """使用 expat 词法钩子拦截 DOCTYPE 与外部/内部实体声明（防范 XXE 与实体扩展攻击）。"""
    parser = expat.ParserCreate()

    def _forbid(*_args: Any) -> None:
        raise ET.ParseError("禁止 XML 包含 DOCTYPE 或实体（ENTITY）声明")

    parser.StartDoctypeDeclHandler = _forbid
    parser.EntityDeclHandler = _forbid
    parser.UnparsedEntityDeclHandler = _forbid
    parser.ExternalEntityRefHandler = _forbid  # type: ignore[assignment]
    try:
        parser.Parse(xml_text, True)
    except expat.ExpatError as exc:
        raise ET.ParseError(str(exc)) from exc


def parse_xml(text: str) -> ET.Element:
    """解析 XML 文本（去掉声明、清理非法控制字符并防范 XXE/实体扩展）。"""
    if not text or not text.strip():
        raise ET.ParseError("响应内容为空")
    if len(text) > MAX_XML_CHARS:
        raise ET.ParseError(f"XML 报文超过最大长度限制（{MAX_XML_CHARS} 字符）")
    cleaned = sanitize_xml_text(text)
    cleaned = re.sub(r"^\s*<\?xml[^>]*\?>", "", cleaned, count=1).strip()
    if not cleaned:
        raise ET.ParseError("响应内容为空")
    _check_xml_security(cleaned)
    return ET.fromstring(cleaned)


def _local_tag(tag: Any) -> str:
    """提取不带 XML 命名空间与前缀的本地标签名；注释或处理指令节点返回空串。"""
    if not isinstance(tag, str):
        return ""
    if "}" in tag:
        tag = tag.rsplit("}", 1)[-1]
    if ":" in tag:
        tag = tag.rsplit(":", 1)[-1]
    return tag


def _is_xsi_nil(el: ET.Element) -> bool:
    """判断元素是否声明了 xsi:nil="true"。"""
    for attr in _XSI_NIL_ATTRS:
        val = el.attrib.get(attr)
        if val is not None and val.strip().lower() in ("true", "1"):
            return True
    for k, v in el.attrib.items():
        if _local_tag(k) == "nil" and v.strip().lower() in ("true", "1"):
            return True
    return False


def _find_all(root: ET.Element, path: str) -> list[ET.Element]:
    """按 a.b.c 路径查找元素（兼容默认命名空间与前缀）；第一段可以是根元素名。最后一段匹配全部同名子元素。"""
    parts = [_local_tag(p) for p in path.split(".") if p.strip()]
    if not parts:
        return []
    if parts[0] == _local_tag(root.tag):
        parts = parts[1:]
    nodes = [root]
    for part in parts:
        nxt: list[ET.Element] = []
        for node in nodes:
            nxt.extend(child for child in node if _local_tag(child.tag) == part)
        nodes = nxt
        if not nodes:
            break
    return nodes


def text_at(root: ET.Element, path: str) -> str | None:
    """路径处第一个元素的文本；不存在返回 None，xsi:nil 返回空串。"""
    found = _find_all(root, path)
    if not found:
        return None
    if _is_xsi_nil(found[0]):
        return ""
    return (found[0].text or "").strip()


def _is_empty_record_node(el: ET.Element) -> bool:
    """判断记录节点是否为空占位标签（如 <smsList/> 或 <smsList xsi:nil="true"/>）。"""
    if _is_xsi_nil(el):
        return True
    children = [c for c in el if isinstance(c.tag, str)]
    return not children and not (el.text or "").strip()


def element_to_record(el: ET.Element) -> dict[str, str]:
    """把一条记录元素转成 子元素名→文本。没有子元素时整个文本作为 value。"""
    children = [c for c in el if isinstance(c.tag, str)]
    if not children:
        return {"value": "" if _is_xsi_nil(el) else (el.text or "").strip()}
    rec: dict[str, str] = {}
    for child in children:
        key = _local_tag(child.tag)
        if not key:
            continue
        if _is_xsi_nil(child):
            rec[key] = ""
        elif not any(isinstance(sub.tag, str) for sub in child):
            rec[key] = (child.text or "").strip()
        else:
            rec[key] = ET.tostring(child, encoding="unicode")
    return rec


def extract_records(contract: ApiContract, root: ET.Element) -> ApiCallResult:
    """按契约 response 判断成功并抽取记录。"""
    resp = contract.response
    root_name = _local_tag(root.tag)
    rec_parts = [_local_tag(p) for p in resp.records.path.split(".") if p.strip()]
    if len(rec_parts) >= 2 and root_name != rec_parts[0]:
        if not any(_local_tag(c.tag) == rec_parts[0] for c in root):
            return ApiCallResult(ok=False, error=f"响应根元素异常：期望 {rec_parts[0]}，实际为 {root_name or '未知'}")
    records_nodes = [n for n in _find_all(root, resp.records.path) if not _is_empty_record_node(n)]
    for rule in resp.noData:
        val = text_at(root, rule.path)
        if val is None:
            continue
        if (rule.equals is not None and val == rule.equals) or (rule.contains and rule.contains in val):
            return ApiCallResult(ok=True, records=[], no_data=True)
    if resp.success is not None:
        code = text_at(root, resp.success.path)
        if code is None:
            if resp.success.missingAs == "failure":
                return ApiCallResult(ok=False, error=f"响应中没有 {resp.success.path}")
        elif code != resp.success.equals:
            desc = _first_text(root, ["resp_desc", "respDesc", "message", "msg", "faultstring"])
            return ApiCallResult(ok=False, error=f"业务返回码 {code}" + (f"：{desc}" if desc else ""))
    records = [element_to_record(n) for n in records_nodes]
    return ApiCallResult(ok=True, records=records, no_data=not records)


def _first_text(root: ET.Element, tags: list[str]) -> str | None:
    wanted = set(tags)
    for tag in tags:
        for el in root.iter():
            if _local_tag(el.tag) == tag and not _is_xsi_nil(el) and (el.text or "").strip():
                return (el.text or "").strip()
        if tag not in wanted:
            continue
    return None


# ============================================================================ JSON 响应解析与记录抽取
def parse_json_body(text: str) -> Any:
    """解析网关 JSON 响应文本，校验非空、最大字符数与嵌套深度防范 DoS。"""
    if not text or not text.strip():
        raise ValueError("响应内容为空")
    if len(text) > MAX_JSON_CHARS:
        raise ValueError(f"JSON 报文超过最大长度限制（{MAX_JSON_CHARS} 字符）")
    cleaned = text.lstrip("\ufeff").strip()
    if not cleaned:
        raise ValueError("响应内容为空")
    try:
        return json.loads(cleaned)
    except RecursionError as exc:
        raise ValueError("JSON 报文嵌套层级过深") from exc


def _json_traverse(start: Any, parts: list[str]) -> list[Any]:
    """按点分路径逐层展开 JSON 节点（遇到列表自动展开，跳过 None）。"""
    if start is None:
        return []
    nodes: list[Any] = list(start) if isinstance(start, list) else [start]
    for part in parts:
        nxt: list[Any] = []
        for cur in nodes:
            if isinstance(cur, dict) and part in cur:
                val = cur[part]
                if isinstance(val, list):
                    nxt.extend(item for item in val if item is not None)
                elif val is not None:
                    nxt.append(val)
        nodes = nxt
        if not nodes:
            break
    return nodes


def _json_find_all(data: Any, path: str) -> list[Any]:
    """按 a.b.c 点分路径查找 JSON 节点，兼容顶层带或不带 operation_out 包裹键。"""
    parts = [p.strip() for p in (path or "").split(".") if p.strip()]
    if not parts:
        if data is None:
            return []
        return list(data) if isinstance(data, list) else [data]
    if parts[0] == "operation_out":
        if isinstance(data, dict) and "operation_out" in data:
            return _json_traverse(data.get("operation_out"), parts[1:])
        return _json_traverse(data, parts[1:])
    direct = _json_traverse(data, parts)
    if direct:
        return direct
    if isinstance(data, dict) and isinstance(data.get("operation_out"), dict):
        return _json_traverse(data["operation_out"], parts)
    return []


def _json_cell_to_str(val: Any) -> str:
    """把 JSON 字段值转为记录列字符串：None 转空串，布尔转 true/false，子对象/数组转紧凑 JSON。"""
    if val is None:
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (dict, list)):
        try:
            return json.dumps(val, ensure_ascii=False, separators=(",", ":"))
        except RecursionError as exc:
            raise ValueError("JSON 字段嵌套层级过深") from exc
    return str(val)


def json_text_at(data: Any, path: str) -> str | None:
    """读取 JSON 点分路径处首个节点的字符串值；不存在或为 null 返回 None。"""
    found = _json_find_all(data, path)
    if not found:
        return None
    val = found[0]
    if val is None:
        return None
    text = _json_cell_to_str(val)
    return text.strip() if isinstance(val, str) else text


def _is_empty_json_record(item: Any) -> bool:
    if item is None:
        return True
    if isinstance(item, (dict, list)) and not item:
        return True
    if isinstance(item, str) and not item.strip():
        return True
    return False


def _json_item_to_record(item: Any) -> dict[str, str]:
    """把单个 JSON 记录节点转换为 列名→文本 字典；标量节点映射为 {'value': ...}。"""
    if isinstance(item, dict):
        return {str(k): _json_cell_to_str(v) for k, v in item.items() if str(k)}
    return {"value": _json_cell_to_str(item)}


def _first_json_text(data: Any, keys: list[str]) -> str | None:
    """按优先级在 JSON 树中递归查找首个非空错误说明字段。"""
    for target in keys:
        found = _find_json_key_first(data, target)
        if found:
            return found
    return None


def _find_json_key_first(node: Any, key: str) -> str | None:
    """使用显式栈迭代查找首个匹配键的非空标量说明（防范超深嵌套 JSON 触发 RecursionError）。"""
    stack: list[Any] = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if key in cur and cur[key] is not None and not isinstance(cur[key], (dict, list)):
                s = _json_cell_to_str(cur[key]).strip()
                if s:
                    return s
            vals = list(cur.values())
            for v in reversed(vals):
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            for item in reversed(cur):
                if isinstance(item, (dict, list)):
                    stack.append(item)
    return None


def extract_json_records(contract: ApiContract, data: Any) -> ApiCallResult:
    """按契约 response 判断 JSON 响应成功状态并抽取记录列表。"""
    if not isinstance(data, (dict, list)):
        return ApiCallResult(ok=False, error="JSON 响应顶层必须是对象或数组")
    resp = contract.response
    try:
        for rule in resp.noData:
            val = json_text_at(data, rule.path)
            if val is None:
                continue
            if (rule.equals is not None and val == rule.equals) or (rule.contains and rule.contains in val):
                return ApiCallResult(ok=True, records=[], no_data=True)
        if resp.success is not None:
            code = json_text_at(data, resp.success.path)
            if code is None:
                if resp.success.missingAs == "failure":
                    return ApiCallResult(ok=False, error=f"响应中没有 {resp.success.path}")
            elif code != resp.success.equals:
                desc = _first_json_text(data, ["resp_desc", "respDesc", "message", "msg", "error_msg", "faultstring"])
                return ApiCallResult(ok=False, error=f"业务返回码 {code}" + (f"：{desc}" if desc else ""))
        raw_items = _json_find_all(data, resp.records.path)
        records = [_json_item_to_record(item) for item in raw_items if not _is_empty_json_record(item)]
        return ApiCallResult(ok=True, records=records, no_data=not records)
    except (RecursionError, ValueError) as exc:
        return ApiCallResult(ok=False, error=f"JSON 响应抽取失败：{exc}")


def _xml_node_to_json(el: ET.Element) -> Any:
    """递归将 XML 元素无损转换为等价 JSON 值（同名兄弟节点自动聚合成数组，xsi:nil 转为 None）。"""
    if _is_xsi_nil(el):
        return None
    children = [c for c in el if isinstance(c.tag, str)]
    if not children:
        return (el.text or "").strip()
    obj: dict[str, Any] = {}
    for child in children:
        key = _local_tag(child.tag)
        if not key:
            continue
        val = _xml_node_to_json(child)
        if key in obj:
            if isinstance(obj[key], list):
                obj[key].append(val)
            else:
                obj[key] = [obj[key], val]
        else:
            obj[key] = val
    return obj


def xml_to_json_data(root: ET.Element) -> dict[str, Any]:
    """将统一网关 XML 根元素无损转换为等价的 {operation_out: ...} JSON 字典结构。"""
    root_key = _local_tag(root.tag) or "operation_out"
    return {root_key: _xml_node_to_json(root)}
