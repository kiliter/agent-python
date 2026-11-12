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
_XML_DECL_STRIP_RE = re.compile(r"^\s*<\?xml[^>]*\?>")
_DOCTYPE_OR_ENTITY_HINT_RE = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)", re.IGNORECASE)


def sanitize_xml_text(text: str) -> str:
    """移除 XML 1.0 不允许的控制字符与非法数字字符引用。#Created By AiCoding(codex)"""
    if not text:
        return ""
    cleaned = text.lstrip("\ufeff")
    if "&#" in cleaned:
        cleaned = _INVALID_XML_CHAR_REF_RE.sub("", cleaned)
    if _INVALID_XML_CHARS_RE.search(cleaned):
        cleaned = _INVALID_XML_CHARS_RE.sub("", cleaned)
    return cleaned


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
    """单遍安全解析 XML 文本（仅在出现 DOCTYPE/ENTITY 字面线索时启用 expat 词法复核，防范 XXE/实体扩展并放行 CDATA）。#Created By AiCoding(codex)"""
    if not text or not text.strip():
        raise ET.ParseError("响应内容为空")
    if len(text) > MAX_XML_CHARS:
        raise ET.ParseError(f"XML 报文超过最大长度限制（{MAX_XML_CHARS} 字符）")
    cleaned = sanitize_xml_text(text)
    if cleaned.lstrip().startswith("<?xml"):
        cleaned = _XML_DECL_STRIP_RE.sub("", cleaned, count=1).strip()
    else:
        cleaned = cleaned.strip()
    if not cleaned:
        raise ET.ParseError("响应内容为空")
    if _DOCTYPE_OR_ENTITY_HINT_RE.search(cleaned):
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


_MAX_FLATTEN_DEPTH = 128


def _find_all(root: ET.Element, path: str) -> list[ET.Element]:
    """按 a.b.c 路径查找元素（兼容默认命名空间与前缀）；空路径匹配根元素，第一段可以是根元素名。"""
    if not (path or "").strip():
        return [root]
    parts = [_local_tag(p) for p in path.split(".") if p.strip()]
    if not parts:
        return [root]
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


def _group_xml_children(parent: ET.Element) -> list[tuple[str, list[ET.Element]]]:
    order: list[str] = []
    grouped: dict[str, list[ET.Element]] = {}
    for c in parent:
        if not isinstance(c.tag, str):
            continue
        k = _local_tag(c.tag)
        if not k:
            continue
        if k not in grouped:
            order.append(k)
            grouped[k] = []
        grouped[k].append(c)
    return [(k, grouped[k]) for k in order]


def _flatten_xml_element(el: ET.Element) -> dict[str, str]:
    """显式栈递归展平 XML 记录节点，嵌套子元素生成 parent.child 点分列名。"""
    children = [c for c in el if isinstance(c.tag, str)]
    if not children:
        return {"value": "" if _is_xsi_nil(el) else (el.text or "").strip()}
    rec: dict[str, str] = {}
    stack: list[tuple[str, list[ET.Element], int]] = [
        (k, els, 1) for k, els in reversed(_group_xml_children(el))
    ]
    while stack:
        key, els, depth = stack.pop()
        if len(els) > 1:
            rec[key] = _json_cell_to_str([_xml_node_to_json(x) for x in els])
            continue
        node = els[0]
        if _is_xsi_nil(node):
            rec[key] = ""
            continue
        sub_children = [c for c in node if isinstance(c.tag, str)]
        if not sub_children:
            rec[key] = (node.text or "").strip()
        elif depth >= _MAX_FLATTEN_DEPTH:
            rec[key] = ET.tostring(node, encoding="unicode")
        else:
            grouped_sub = _group_xml_children(node)
            if not grouped_sub:
                rec[key] = (node.text or "").strip()
            else:
                for sub_k, sub_els in reversed(grouped_sub):
                    stack.append((f"{key}.{sub_k}", sub_els, depth + 1))
    return rec


def _extract_xml_dotted(el: ET.Element, dotted_key: str) -> tuple[bool, str]:
    """按显式声明的点分列名（如 userInfo.userName）从 XML 元素提取嵌套子路径值。"""
    parts = [_local_tag(p) for p in dotted_key.split(".") if p.strip()]
    if len(parts) < 2:
        return False, ""
    nodes: list[ET.Element] = [el]
    for part in parts:
        nxt: list[ET.Element] = []
        for node in nodes:
            if _is_xsi_nil(node):
                continue
            nxt.extend(c for c in node if isinstance(c.tag, str) and _local_tag(c.tag) == part)
        if not nxt:
            return False, ""
        nodes = nxt
    if len(nodes) == 1:
        target = nodes[0]
        if _is_xsi_nil(target):
            return True, ""
        sub_els = [c for c in target if isinstance(c.tag, str)]
        if not sub_els:
            return True, (target.text or "").strip()
        return True, ET.tostring(target, encoding="unicode")
    non_empty: list[Any] = []
    for n in nodes:
        val = _xml_node_to_json(n)
        if _is_empty_json_record(val):
            continue
        non_empty.append(val)
    if not non_empty:
        return True, ""
    if len(non_empty) == 1:
        return True, _json_cell_to_str(non_empty[0])
    return True, _json_cell_to_str(non_empty)


def _xml_scalar_to_record(el: ET.Element) -> dict[str, str]:
    """将匹配到的 XML 节点作为标量行 {'value': ...} 提取。"""
    if _is_xsi_nil(el):
        return {"value": ""}
    children = [c for c in el if isinstance(c.tag, str)]
    if not children:
        return {"value": (el.text or "").strip()}
    return {"value": ET.tostring(el, encoding="unicode")}


def element_to_record(
    el: ET.Element,
    *,
    flatten: bool = False,
    columns: dict[str, str] | None = None,
) -> dict[str, str]:
    """把一条记录元素转成 子元素名→文本。没有子元素时整个文本作为 value；支持嵌套展平与点分列提取。"""
    if flatten:
        rec = _flatten_xml_element(el)
    else:
        children = [c for c in el if isinstance(c.tag, str)]
        if not children:
            return {"value": "" if _is_xsi_nil(el) else (el.text or "").strip()}
        rec = {}
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
    if columns:
        for col_key in columns:
            if "." in col_key and col_key not in rec:
                found, val = _extract_xml_dotted(el, col_key)
                if found:
                    rec[col_key] = val
    return rec


_AUTO_LIST_CONTAINER_KEYS = frozenset({
    "list", "total", "count", "totalCount", "page", "pageNo", "pageNum", "pageSize", "pages", "hasMore", "nextCursor",
})


def _auto_unwrap_xml_list(nodes: list[ET.Element], columns: dict[str, str] | None) -> list[ET.Element]:
    """mode='auto' 时，若路径指向诸如 operation_out.content 的包裹节点且其下仅含 <list> 记录集（及分页元数据），自动解包 <list>。"""
    if len(nodes) != 1:
        return nodes
    cols = columns or {}
    if "list" in cols or any(k.startswith("list.") for k in cols):
        return nodes
    children = [c for c in nodes[0] if isinstance(c.tag, str)]
    list_children = [c for c in children if _local_tag(c.tag) == "list"]
    if not list_children or not all(_local_tag(c.tag) in _AUTO_LIST_CONTAINER_KEYS for c in children):
        return nodes
    if not any(any(isinstance(gc.tag, str) for gc in lc) or _is_empty_record_node(lc) for lc in list_children):
        return nodes
    return [c for c in list_children if not _is_empty_record_node(c)]


def extract_records(contract: ApiContract, root: ET.Element) -> ApiCallResult:
    """按契约 response 判断成功并按 records.mode 抽取记录。"""
    resp = contract.response
    mode = resp.records.mode
    if mode != "none":
        root_name = _local_tag(root.tag)
        rec_parts = [_local_tag(p) for p in (resp.records.path or "").split(".") if p.strip()]
        if len(rec_parts) >= 2 and root_name != rec_parts[0]:
            if not any(_local_tag(c.tag) == rec_parts[0] for c in root):
                return ApiCallResult(ok=False, error=f"响应根元素异常：期望 {rec_parts[0]}，实际为 {root_name or '未知'}")
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
            desc = _first_text(root, ["resp_desc", "respDesc", "ret_msg", "retMsg", "message", "msg", "faultstring"])
            return ApiCallResult(ok=False, error=f"业务返回码 {code}" + (f"：{desc}" if desc else ""))
    if mode == "none":
        return ApiCallResult(ok=True, records=[], no_data=False)
    records_nodes = [n for n in _find_all(root, resp.records.path) if not _is_empty_record_node(n)]
    if mode == "scalar":
        records = [_xml_scalar_to_record(n) for n in records_nodes]
        return ApiCallResult(ok=True, records=records, no_data=not records)
    if mode == "auto":
        records_nodes = _auto_unwrap_xml_list(records_nodes, resp.records.columns)
    elif mode == "object":
        records_nodes = records_nodes[:1]
    records = [
        element_to_record(n, flatten=resp.records.flatten, columns=resp.records.columns)
        for n in records_nodes
    ]
    return ApiCallResult(ok=True, records=records, no_data=not records)


def _first_text(root: ET.Element, tags: list[str]) -> str | None:
    if not tags:
        return None
    top = tags[0]
    wanted = set(tags)
    found_by_tag: dict[str, str] = {}
    for el in root.iter():
        tag = _local_tag(el.tag)
        if tag in wanted and tag not in found_by_tag and not _is_xsi_nil(el):
            txt = (el.text or "").strip()
            if txt:
                if tag == top:
                    return txt
                found_by_tag[tag] = txt
                if len(found_by_tag) == len(wanted):
                    break
    for tag in tags:
        if tag in found_by_tag:
            return found_by_tag[tag]
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


def _flatten_json_dict(d: dict[str, Any]) -> dict[str, str]:
    """显式栈递归展平嵌套 JSON 字典，生成 parent.child 点分列名并防范超深嵌套栈溢出。"""
    rec: dict[str, str] = {}
    stack: list[tuple[str, Any, int]] = [
        (str(k), v, 1) for k, v in reversed(list(d.items())) if str(k)
    ]
    while stack:
        key, val, depth = stack.pop()
        if isinstance(val, dict):
            if not val:
                rec[key] = ""
            elif depth >= _MAX_FLATTEN_DEPTH:
                rec[key] = _json_cell_to_str(val)
            else:
                for sub_k, sub_v in reversed(list(val.items())):
                    sk = str(sub_k)
                    if sk:
                        stack.append((f"{key}.{sk}", sub_v, depth + 1))
        else:
            rec[key] = _json_cell_to_str(val)
    return rec


def _extract_json_dotted(item: dict[str, Any], dotted_key: str) -> tuple[bool, str]:
    """按显式声明的点分列名（如 userInfo.userName 或 level_info.event_name）从 JSON 字典提取嵌套值。

    #Created By AiCoding(codex)
    对齐 XML _extract_xml_dotted：路径段遇到 list 时遍历列表内字典聚合非空值（单值返回标量字符串，多值序列化为紧凑 JSON 数组）。
    """
    parts = [p.strip() for p in dotted_key.split(".") if p.strip()]
    if len(parts) < 2:
        return False, ""
    nodes: list[Any] = [item]
    saw_list = False
    for idx, part in enumerate(parts):
        is_last = idx == len(parts) - 1
        nxt: list[Any] = []
        found_key = False
        for cur in nodes:
            if isinstance(cur, dict) and part in cur:
                found_key = True
                val = cur[part]
                if isinstance(val, list) and not is_last:
                    saw_list = True
                    nxt.extend(x for x in val if x is not None)
                else:
                    nxt.append(val)
        if not found_key:
            return False, ""
        if not nxt:
            return (True, "") if is_last else (False, "")
        nodes = nxt
    if not saw_list and len(nodes) == 1:
        return True, _json_cell_to_str(nodes[0])
    non_empty: list[Any] = []
    for n in nodes:
        if _is_empty_json_record(n):
            continue
        non_empty.append(n.strip() if isinstance(n, str) else n)
    if not non_empty:
        return True, ""
    if len(non_empty) == 1:
        return True, _json_cell_to_str(non_empty[0])
    return True, _json_cell_to_str(non_empty)


def _json_item_to_record(
    item: Any,
    *,
    flatten: bool = False,
    columns: dict[str, str] | None = None,
) -> dict[str, str]:
    """把单个 JSON 记录节点转换为 列名→文本 字典；支持嵌套展平与点分列提取。"""
    if isinstance(item, dict):
        rec = _flatten_json_dict(item) if flatten else {str(k): _json_cell_to_str(v) for k, v in item.items() if str(k)}
        if columns:
            for col_key in columns:
                if "." in col_key and col_key not in rec:
                    found, val = _extract_json_dotted(item, col_key)
                    if found:
                        rec[col_key] = val
        return rec
    return {"value": _json_cell_to_str(item)}


def _first_json_text(data: Any, keys: list[str]) -> str | None:
    """按优先级在 JSON 树中单遍迭代查找首个非空错误说明字段（显式栈防范超深嵌套触发 RecursionError）。"""
    if not keys:
        return None
    top = keys[0]
    wanted = set(keys)
    found_by_key: dict[str, str] = {}
    stack: list[Any] = [data]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k in wanted and k not in found_by_key and v is not None and not isinstance(v, (dict, list)):
                    s = _json_cell_to_str(v).strip()
                    if s:
                        if k == top:
                            return s
                        found_by_key[k] = s
            if len(found_by_key) == len(wanted):
                break
            vals = list(cur.values())
            for v in reversed(vals):
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            for item in reversed(cur):
                if isinstance(item, (dict, list)):
                    stack.append(item)
    for target in keys:
        if target in found_by_key:
            return found_by_key[target]
    return None


def _auto_unwrap_json_list(items: list[Any], columns: dict[str, str] | None) -> list[Any]:
    """mode='auto' 时，若路径指向诸如 operation_out.content 的包裹字典且仅含 list 数组（及分页元数据），自动解包 list。"""
    if len(items) != 1 or not isinstance(items[0], dict):
        return items
    d = items[0]
    cols = columns or {}
    if "list" not in d or not isinstance(d["list"], list):
        return items
    if "list" in cols or any(k.startswith("list.") for k in cols):
        return items
    if not (set(d.keys()) <= _AUTO_LIST_CONTAINER_KEYS):
        return items
    return [item for item in d["list"] if not _is_empty_json_record(item)]


def extract_json_records(contract: ApiContract, data: Any) -> ApiCallResult:
    """按契约 response 判断 JSON 响应成功状态并按 records.mode 抽取记录列表。"""
    resp = contract.response
    mode = resp.records.mode
    if mode not in ("scalar", "none") and not isinstance(data, (dict, list)):
        return ApiCallResult(ok=False, error="JSON 响应顶层必须是对象或数组")
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
                desc = _first_json_text(
                    data, ["resp_desc", "respDesc", "ret_msg", "retMsg", "message", "msg", "error_msg", "faultstring"]
                )
                return ApiCallResult(ok=False, error=f"业务返回码 {code}" + (f"：{desc}" if desc else ""))
        if mode == "none":
            return ApiCallResult(ok=True, records=[], no_data=False)
        raw_items = [item for item in _json_find_all(data, resp.records.path) if not _is_empty_json_record(item)]
        if mode == "scalar":
            records = [{"value": _json_cell_to_str(item)} for item in raw_items]
            return ApiCallResult(ok=True, records=records, no_data=not records)
        if mode == "auto":
            raw_items = _auto_unwrap_json_list(raw_items, resp.records.columns)
        elif mode == "object":
            raw_items = raw_items[:1]
        records = [
            _json_item_to_record(item, flatten=resp.records.flatten, columns=resp.records.columns)
            for item in raw_items
        ]
        return ApiCallResult(ok=True, records=records, no_data=not records)
    except (RecursionError, ValueError) as exc:
        return ApiCallResult(ok=False, error=f"JSON 响应抽取失败：{exc}")


def _xml_node_to_json(el: ET.Element, _depth: int = 0) -> Any:
    """递归将 XML 元素无损转换为等价 JSON 值（同名兄弟节点自动聚合成数组，xsi:nil 转为 None）。"""
    if _is_xsi_nil(el):
        return None
    children = [c for c in el if isinstance(c.tag, str)]
    if not children:
        return (el.text or "").strip()
    if _depth >= _MAX_FLATTEN_DEPTH:
        return ET.tostring(el, encoding="unicode")
    obj: dict[str, Any] = {}
    for child in children:
        key = _local_tag(child.tag)
        if not key:
            continue
        val = _xml_node_to_json(child, _depth + 1)
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
