"""模板管理接口：列表、工作台（正文/字段/入参/Skill/用例/试运行/历史）、发布与回退。

#Created By AiCoding(codex)
所有修改都写入草稿，发布后才影响线上请求。
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from ..domain.jinja_env import BodySyntaxError, TrackedValue, body_variables, render_body
from ..domain.resources import _RESERVED_FIELD_NAMES
from ..domain.template import Template, TemplateDef
from ..runtime.render import field_render
from ..runtime.runner import RunRequest
from ..store.cases import CaseStore
from ..store.fsutil import fmt_time
from ..store.layout import CASE_ID_RE, SAFE_ID_RE
from ..store.service import InvalidResource, ResourceNotFound, template_from_payload, tpl_ref
from .auth import require_user
from .common import bad_request, container, not_found, operator, sse_run
from .dto import (body_usage, dto_to_field, dto_to_input, field_to_dto, input_to_dto, ref_by_fields, template_item)
from .run_views import detail_view

router = APIRouter(prefix="/api/v1", tags=["模板"], dependencies=[Depends(require_user)])

_BAD_FIELD_NAME_RE = re.compile(r"[{}%\s]")


# ============================================================================ 工具函数
def _check_tid(tid: int) -> int:
    if tid <= 0:
        raise bad_request("模板编号必须为正整数", "INVALID_TEMPLATE_ID")
    return tid


def _check_case_id(case_id: str) -> str:
    if not CASE_ID_RE.match(case_id):
        raise bad_request("用例编号只能包含字母、数字、下划线和短横线（1~40 位）", "INVALID_CASE_ID")
    return case_id


def _working(request: Request, tid: int) -> Template:
    _check_tid(tid)
    tpl = container(request).service.template_working(tid)
    if tpl is None:
        raise not_found(f"模板 {tid} 不存在")
    return tpl


def _item(request: Request, tid: int) -> dict[str, Any]:
    _check_tid(tid)
    c = container(request)
    try:
        tpl = c.service.template_working(tid)
    except InvalidResource:
        tpl = c.service.template_online(tid)
    if tpl is None:
        raise not_found(f"模板 {tid} 不存在")
    _, live = c.service.live()
    return template_item(tpl, c.service.state(tpl_ref(tid), live), c.service.overlay(), c.runs.stats_7d(),
                         c.cases.count(tid))


def _detail(request: Request, tid: int, tpl: Template, version: str) -> dict[str, Any]:
    c = container(request)
    usage = body_usage(tpl.body)
    refs = ref_by_fields(tpl)
    state = c.service.state(tpl_ref(tid))
    return {
        "item": _item(request, tid), "version": version, "id": tpl.id, "name": tpl.name,
        "description": tpl.definition.description, "bodyText": tpl.body,
        "fields": [field_to_dto(f, usage, refs.get(f.name)) for f in tpl.definition.fields],
        "inputs": [input_to_dto(i) for i in tpl.definition.inputs], "skills": list(tpl.definition.skills),
        "offline": tpl.offline, "draft": state.draft,
    }


def _resolve_skills(request: Request, refs: list[str]) -> list[str]:
    """Skill 可以用标识或中文名称指定，统一转成标识。"""
    rs = container(request).service.overlay()
    out = []
    for ref in refs:
        sk = rs.skill_by_ref(ref)
        if sk is None:
            raise bad_request(f"Skill「{ref}」不存在", "SKILL_NOT_FOUND")
        if sk.id not in out:
            out.append(sk.id)
    return out


def _mutate(request: Request, tid: int, fn, revision: int | None = None) -> dict[str, Any]:
    """读取工作副本 → fn 修改定义字典与正文 → 保存草稿。"""
    tpl = _working(request, tid)
    data = tpl.definition.model_dump()
    body = fn(data, tpl.body)
    new_tpl = template_from_payload(tid, tpl, data, body if isinstance(body, str) else tpl.body)
    return container(request).service.save_template(new_tpl, operator(request), expected_revision=revision)


# ============================================================================ 列表与生命周期
@router.get("/templates")
def list_templates(request: Request) -> list[dict[str, Any]]:
    c = container(request)
    _, live = c.service.live()
    overlay = c.service.overlay()
    stats = c.runs.stats_7d()
    items = []
    for key in c.service.keys("template"):
        tid = int(key)
        tpl = overlay.templates.get(tid) or live.templates.get(tid)
        if tpl is None:
            continue
        items.append(template_item(tpl, c.service.state(tpl_ref(tid), live), overlay, stats, c.cases.count(tid)))
    return items


class CreateTemplateBody(BaseModel):
    id: int = Field(gt=0)
    name: str
    description: str = ""
    skills: list[str] = Field(default_factory=list)


@router.post("/templates")
def create_template(request: Request, body: CreateTemplateBody) -> dict[str, Any]:
    c = container(request)
    if c.drafts.exists(tpl_ref(body.id)) or c.service.template_online(body.id) is not None:
        raise bad_request(f"模板编号 {body.id} 已存在", "TEMPLATE_EXISTS")
    skills = _resolve_skills(request, body.skills)
    tpl = Template(definition=TemplateDef(id=body.id, name=body.name.strip() or f"模板{body.id}",
                                          description=body.description, skills=skills),
                   body=f"服务争议点1:{body.name.strip()}\n")
    c.service.save_template(tpl, operator(request), action="create")
    return _item(request, body.id)


class CopyTemplateBody(BaseModel):
    newId: int = Field(gt=0)
    newName: str
    copyCases: bool = True


@router.post("/templates/{tid}/copy")
def copy_template(request: Request, tid: int, body: CopyTemplateBody) -> dict[str, Any]:
    c = container(request)
    src = _working(request, tid)
    if c.drafts.exists(tpl_ref(body.newId)) or c.service.template_online(body.newId) is not None:
        raise bad_request(f"模板编号 {body.newId} 已存在", "TEMPLATE_EXISTS")
    defn = src.definition.model_copy(update={"id": body.newId, "name": body.newName.strip() or f"{src.name}（副本）"})
    c.service.save_template(Template(definition=defn, body=src.body), operator(request), action=f"copy:{tid}")
    if body.copyCases:
        c.cases.copy_all(tid, body.newId)
    return _item(request, body.newId)


class ReasonBody(BaseModel):
    reason: str = ""


@router.post("/templates/{tid}/offline")
def offline_template(request: Request, tid: int, body: ReasonBody | None = None) -> dict[str, Any]:
    _check_tid(tid)
    c = container(request)
    result = c.service.offline_template(tid, operator(request), (body.reason if body else ""))
    return {"id": tid, "status": c.service.state(tpl_ref(tid)).status, "rev": result.entry["rev"]}


@router.post("/templates/{tid}/restore")
def restore_template(request: Request, tid: int) -> dict[str, Any]:
    _check_tid(tid)
    c = container(request)
    c.service.restore_template(tid, operator(request))
    return {"id": tid, "status": c.service.state(tpl_ref(tid)).status}


# ============================================================================ 工作台读取
@router.get("/templates/cross-fields")
def cross_fields(request: Request, exclude: int | None = None) -> list[dict[str, Any]]:
    """其它模板中定义的字段（正文编辑器“跨模板字段”候选）。"""
    c = container(request)
    out = []
    for tid, tpl in sorted(c.service.overlay().templates.items()):
        if tid == exclude:
            continue
        for f in tpl.definition.fields:
            out.append(field_to_dto(f, from_template=f"{tid} {tpl.name}"))
    return out


@router.get("/templates/{tid}")
def get_template(request: Request, tid: int, version: str = Query("working")) -> dict[str, Any]:
    """version：working（草稿优先）/ draft / online / rN。"""
    _check_tid(tid)
    tpl = container(request).service.template_version(tid, version)
    if tpl is None:
        raise not_found(f"模板 {tid} 没有 {version} 版本")
    return _detail(request, tid, tpl, version)


@router.get("/templates/{tid}/fields")
def get_fields(request: Request, tid: int) -> list[dict[str, Any]]:
    tpl = _working(request, tid)
    usage, refs = body_usage(tpl.body), ref_by_fields(tpl)
    return [field_to_dto(f, usage, refs.get(f.name)) for f in tpl.definition.fields]


@router.get("/templates/{tid}/inputs")
def get_inputs(request: Request, tid: int) -> list[dict[str, Any]]:
    return [input_to_dto(i) for i in _working(request, tid).definition.inputs]


# ============================================================================ 草稿
class DraftBody(BaseModel):
    name: str | None = None
    description: str | None = None
    bodyText: str | None = None
    fields: list[dict[str, Any]] | None = None
    inputs: list[dict[str, Any]] | None = None
    skills: list[str] | None = None
    revision: int | None = Field(default=None, description="乐观锁：上次读取到的草稿版本号")


@router.put("/templates/{tid}/draft")
def save_draft(request: Request, tid: int, body: DraftBody) -> dict[str, Any]:
    _check_tid(tid)
    c = container(request)
    ref = tpl_ref(tid)
    try:
        base = c.service.template_working(tid)
    except InvalidResource:
        base = c.service.template_online(tid)
    if base is None and not c.drafts.exists(ref):
        raise not_found(f"模板 {tid} 不存在")
    data: dict[str, Any] = {"name": body.name, "description": body.description}
    if body.fields is not None:
        data["fields"] = [dto_to_field(f) for f in body.fields]
    if body.inputs is not None:
        data["inputs"] = [dto_to_input(i) for i in body.inputs]
    if body.skills is not None:
        data["skills"] = _resolve_skills(request, body.skills)
    tpl = template_from_payload(tid, base, data, body.bodyText)
    meta = c.service.save_template(tpl, operator(request), expected_revision=body.revision)
    issues = c.service.validate_template_working(tid, tpl)
    return {"savedAt": fmt_time(meta["updatedAt"]), "draft": meta, "issues": [i.to_dict() for i in issues]}


@router.post("/templates/{tid}/discard-draft")
def discard_draft(request: Request, tid: int) -> dict[str, Any]:
    _check_tid(tid)
    c = container(request)
    had_draft = c.service.discard(tpl_ref(tid))
    tpl = c.service.template_online(tid)
    if tpl is None:
        if not had_draft:
            raise not_found(f"模板 {tid} 不存在")
        return {"bodyText": "", "rev": "—", "deleted": True}
    state = c.service.state(tpl_ref(tid))
    return {"bodyText": tpl.body, "rev": state.online_rev or "—", "detail": _detail(request, tid, tpl, "online")}


@router.post("/templates/{tid}/validate")
def validate(request: Request, tid: int, body: DraftBody | None = None) -> dict[str, Any]:
    """校验工作副本；传入 body 时校验 body 描述的内容（不保存）。"""
    c = container(request)
    tpl = _working(request, tid)
    if body is not None and any(v is not None for v in body.model_dump(exclude={"revision"}).values()):
        data: dict[str, Any] = {"name": body.name, "description": body.description}
        if body.fields is not None:
            data["fields"] = [dto_to_field(f) for f in body.fields]
        if body.inputs is not None:
            data["inputs"] = [dto_to_input(i) for i in body.inputs]
        if body.skills is not None:
            data["skills"] = _resolve_skills(request, body.skills)
        tpl = template_from_payload(tid, tpl, data, body.bodyText)
    issues = c.service.validate_template_working(tid, tpl)
    state = c.service.state(tpl_ref(tid))
    drift = bool(state.draft and state.online_rev and state.base_rev and state.base_rev != state.online_rev)
    return {"errors": [i.to_dict() for i in issues if i.level == "error"],
            "warnings": [i.to_dict() for i in issues if i.level == "warning"],
            "drift": {"baseRev": state.base_rev, "onlineRev": state.online_rev} if drift else None,
            "casesCount": c.cases.count(tid)}


class PublishBody(BaseModel):
    note: str = ""


@router.post("/templates/{tid}/publish")
def publish(request: Request, tid: int, body: PublishBody) -> dict[str, Any]:
    _check_tid(tid)
    c = container(request)
    ref = tpl_ref(tid)
    if not c.drafts.exists(ref):
        if c.service.template_online(tid) is None:
            raise not_found(f"模板 {tid} 不存在")
        raise bad_request("没有需要发布的草稿", "NO_DRAFT")
    result = c.service.publish_draft(ref, operator(request), body.note)
    e = result.entry
    item = _item(request, tid)
    return {"rev": e["rev"], "status": item["status"], "publishedAt": fmt_time(e["time"]), "summary": e["summary"],
            "warnings": [i.to_dict() for i in result.warnings], "item": item}


class RollbackBody(BaseModel):
    targetRev: str
    mode: Literal["draft_only", "publish_now"] = "draft_only"
    reason: str = ""


@router.post("/templates/{tid}/rollback")
def rollback(request: Request, tid: int, body: RollbackBody) -> dict[str, Any]:
    _check_tid(tid)
    c = container(request)
    if body.mode == "publish_now" and not body.reason.strip():
        raise bad_request("直接回退上线必须填写原因")
    result = c.service.rollback(tpl_ref(tid), body.targetRev, body.mode, body.reason, operator(request))
    tpl = _working(request, tid)
    return {**result, "item": _item(request, tid), "detail": _detail(request, tid, tpl, "working")}


@router.get("/templates/{tid}/revisions")
def revisions(request: Request, tid: int) -> list[dict[str, Any]]:
    """修改过该模板的全部版本（最新在前），标出当前线上内容来自哪个版本。"""
    _check_tid(tid)
    c = container(request)
    ref = tpl_ref(tid)
    hist = c.releases.history(ref)
    if not hist and not c.drafts.exists(ref) and c.service.template_online(tid) is None:
        raise not_found(f"模板 {tid} 不存在")
    online = c.releases.online_change(ref)
    return [{"rev": e["rev"], "type": e.get("type"), "operator": e.get("operator"), "time": fmt_time(e.get("time")),
             "note": e.get("note") or e.get("summary"), "summary": e.get("summary"),
             "online": bool(online and online["rev"] == e["rev"])} for e in hist]


def _diff_fields(a: Template | None, b: Template | None) -> list[dict[str, Any]]:
    fa = {f.name: f for f in (a.definition.fields if a else [])}
    fb = {f.name: f for f in (b.definition.fields if b else [])}
    out = []
    for name in list(dict.fromkeys([*fa, *fb])):
        x, y = fa.get(name), fb.get(name)
        if x and not y:
            out.append({"change": "removed", "name": name, "a": field_to_dto(x), "b": None, "props": []})
        elif y and not x:
            out.append({"change": "added", "name": name, "a": None, "b": field_to_dto(y), "props": []})
        elif x and y and x != y:
            props = [k for k in x.model_dump() if x.model_dump()[k] != y.model_dump()[k]]
            out.append({"change": "modified", "name": name, "a": field_to_dto(x), "b": field_to_dto(y), "props": props})
    return out


def _diff_inputs(a: Template | None, b: Template | None) -> list[dict[str, Any]]:
    ia = {i.key: i for i in (a.definition.inputs if a else [])}
    ib = {i.key: i for i in (b.definition.inputs if b else [])}
    out = []
    for key in list(dict.fromkeys([*ia, *ib])):
        x, y = ia.get(key), ib.get(key)
        if x != y:
            out.append({"change": "removed" if not y else "added" if not x else "modified", "key": key,
                        "a": input_to_dto(x) if x else None, "b": input_to_dto(y) if y else None})
    return out


@router.get("/templates/{tid}/diff")
def diff(request: Request, tid: int, a: str = "draft", b: str = "online") -> dict[str, Any]:
    """对比两个版本（draft / online / working / rN）的字段、入参、正文和 Skill。"""
    _check_tid(tid)
    c = container(request)
    ta, tb = c.service.template_version(tid, a), c.service.template_version(tid, b)
    if ta is None and tb is None:
        raise not_found(f"模板 {tid} 没有 {a} 和 {b} 版本")
    return {"a": a, "b": b, "fields": _diff_fields(ta, tb), "inputs": _diff_inputs(ta, tb),
            "bodyA": ta.body if ta else "", "bodyB": tb.body if tb else "",
            "bodyIdentical": (ta.body if ta else "") == (tb.body if tb else ""),
            "skillsA": ta.definition.skills if ta else [], "skillsB": tb.definition.skills if tb else []}


class PreviewBody(BaseModel):
    bodyText: str | None = None
    values: dict[str, Any] = Field(default_factory=dict,
                                   description="字段名 → 值；不传或为 null 视为找不到。列表字段传行对象数组或其 JSON 字符串")


def _preview_rows(val: Any) -> Any:
    """预览用：列表字段的值可以是行数组或 JSON 字符串。#Created By AiCoding(codex)"""
    if isinstance(val, str) and val.strip():
        try:
            return json.loads(val)
        except ValueError:
            return None
    return val


@router.post("/templates/{tid}/render-preview")
def render_preview(request: Request, tid: int, body: PreviewBody) -> dict[str, Any]:
    """用给定字段值渲染正文，找不到的字段按 whenMissing 处理（正文编辑器右侧预览用）。"""
    tpl = _working(request, tid)
    text = body.bodyText if body.bodyText is not None else tpl.body
    ctx: dict[str, Any] = {}
    for f in tpl.definition.fields:
        val = body.values.get(f.name)
        if f.is_list:
            # #Created By AiCoding(codex) 列表字段与生产渲染走同一路径（找不到时为空列表）
            ctx[f.name] = field_render(f, {"status": "found", "value": _preview_rows(val)}).context_value
            continue
        if val not in (None, ""):
            ctx[f.name] = TrackedValue(str(val), f.name)
        else:
            missing = "" if f.whenMissing == "empty" else f.defaultValue if f.whenMissing == "value" else "{{" + f.name + "}}"
            ctx[f.name] = TrackedValue(missing, f.name, missing=True)
    try:
        undefined = sorted(body_variables(text) - set(ctx))
        for name in undefined:
            ctx[name] = TrackedValue("{{" + name + "}}", name, missing=True)
        rendered, used = render_body(text, ctx)
    except BodySyntaxError as exc:
        return {"text": "", "usedFields": [], "undefinedFields": [], "error": str(exc), "line": exc.lineno}
    except Exception as exc:  # noqa: BLE001
        return {"text": "", "usedFields": [], "undefinedFields": [], "error": f"渲染失败：{exc}"}
    return {"text": rendered, "usedFields": sorted(used), "undefinedFields": undefined, "error": None}


_RENAME_TAG_TOKEN_RE = re.compile(
    r"""('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")"""
    r"""|(\|\s*[A-Za-z_][A-Za-z0-9_]*)"""
    r"""|(\.\s*[^\W\d]\w*)"""
    r"""|([^\W\d]\w*)""",
    re.UNICODE,
)


def _rename_body_variable(text: str, old_name: str, new_name: str) -> str:
    """在 Jinja2 输出块 {{ ... }} / {{- ... -}} 与控制块 {% ... %} / {%- ... -%} 中安全重命名变量，
    跳过注释 {# ... #}、字符串字面量、过滤器名（| filter）及属性访问（.attr）。"""
    if not text or not old_name or old_name == new_name:
        return text
    out: list[str] = []
    n = len(text)
    i = 0
    while i < n:
        brace = text.find("{", i)
        if brace == -1 or brace + 1 >= n:
            out.append(text[i:])
            break
        nxt = text[brace + 1]
        if nxt not in ("#", "{", "%"):
            out.append(text[i:brace + 1])
            i = brace + 1
            continue
        out.append(text[i:brace])
        if nxt == "#":
            end_comment = text.find("#}", brace + 2)
            if end_comment == -1:
                out.append(text[brace:])
                break
            out.append(text[brace:end_comment + 2])
            i = end_comment + 2
            continue

        is_block = nxt == "%"
        close_tok = "%}" if is_block else "}}"
        open_end = brace + 3 if (brace + 2 < n and text[brace + 2] in "+-") else brace + 2
        quote_ch: str | None = None
        close_pos = -1
        j = open_end
        while j < n:
            ch = text[j]
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
            if text.startswith(close_tok, j):
                close_pos = j
                break
            j += 1

        if close_pos == -1:
            out.append(text[brace:])
            break

        inner = text[open_end:close_pos]
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

        out.append(text[brace:open_end])
        out.append(_RENAME_TAG_TOKEN_RE.sub(_sub_tok, inner))
        out.append(close_tok)
        i = close_pos + 2
    return "".join(out)


# ============================================================================ 字段 / 入参 / Skill 的细粒度修改
@router.put("/templates/{tid}/fields/{name}")
def save_field(request: Request, tid: int, name: str, body: dict[str, Any]) -> dict[str, Any]:
    """新增或修改一个字段。改名时传 originalName（不传时把路径中的 name 当作原名）。
    改名会同步替换正文中的 {{旧名}}、{{- 旧名 -}} 与 {% if 旧名 %} 等引用。"""
    new = dto_to_field(body)
    if not new["name"]:
        new["name"] = name.strip()
    if (
        not new["name"]
        or not new["name"].isidentifier()
        or new["name"].startswith("_")
        or new["name"] in _RESERVED_FIELD_NAMES
        or _BAD_FIELD_NAME_RE.search(new["name"])
    ):
        raise bad_request(
            f"字段名「{new['name']}」不合法：只能使用中英文、数字和下划线，不能以下划线或数字开头，且不能为模板保留字",
            "INVALID_FIELD_NAME",
        )
    original = str(body.get("originalName") or name).strip()
    revision = body.get("revision")

    def fn(data: dict[str, Any], text: str) -> str:
        fields = data["fields"]
        orig_idx = next((i for i, f in enumerate(fields) if f["name"] == original), None)
        target_idx = next((i for i, f in enumerate(fields) if f["name"] == new["name"]), None)
        if original != new["name"]:
            if target_idx is not None and target_idx != orig_idx:
                raise bad_request(f"字段「{new['name']}」已存在", "FIELD_EXISTS")
            if orig_idx is None:
                fields.append(new)
            else:
                fields[orig_idx] = new
            text = _rename_body_variable(text, original, new["name"])
        else:
            if orig_idx is None:
                fields.append(new)
            else:
                fields[orig_idx] = new
        return text

    _mutate(request, tid, fn, revision)
    tpl = _working(request, tid)
    f = tpl.definition.field(new["name"])
    return field_to_dto(f, body_usage(tpl.body), ref_by_fields(tpl).get(f.name)) if f else new


@router.delete("/templates/{tid}/fields/{name}")
def delete_field(request: Request, tid: int, name: str, force: bool = False) -> dict[str, Any]:
    tpl = _working(request, tid)
    if tpl.definition.field(name) is None:
        raise not_found(f"字段「{name}」不存在")
    usage = body_usage(tpl.body).get(name, 0)
    if usage and not force:
        raise bad_request(f"字段「{name}」在正文中被引用 {usage} 次，请先移除引用", "FIELD_IN_USE", usage=usage)

    def fn(data: dict[str, Any], text: str) -> str:
        data["fields"] = [f for f in data["fields"] if f["name"] != name]
        return text

    _mutate(request, tid, fn)
    return {"deletedName": name}


class BatchEvidenceBody(BaseModel):
    fieldNames: list[str]
    evidenceType: Literal["quote", "input", "derive"]


@router.post("/templates/{tid}/fields/batch-evidence")
def batch_evidence(request: Request, tid: int, body: BatchEvidenceBody) -> dict[str, Any]:
    names = set(body.fieldNames)
    count = 0

    def fn(data: dict[str, Any], text: str) -> str:
        nonlocal count
        for f in data["fields"]:
            if f["name"] in names:
                f["evidence"] = body.evidenceType
                count += 1
        return text

    _mutate(request, tid, fn)
    return {"updatedCount": count}


class OrderBody(BaseModel):
    names: list[str]


@router.put("/templates/{tid}/fields-order")
def reorder_fields(request: Request, tid: int, body: OrderBody) -> dict[str, Any]:
    """字段排序（拖拽后提交完整的字段名顺序）。"""

    def fn(data: dict[str, Any], text: str) -> str:
        by_name = {f["name"]: f for f in data["fields"]}
        if len(body.names) != len(by_name) or set(body.names) != set(by_name):
            raise bad_request("排序列表必须包含且只包含全部字段（不能重复或遗漏）")
        data["fields"] = [by_name[n] for n in body.names]
        return text

    _mutate(request, tid, fn)
    return {"names": body.names}


class SkillsBody(BaseModel):
    skills: list[str]


@router.put("/templates/{tid}/skills")
def update_skills(request: Request, tid: int, body: SkillsBody) -> dict[str, Any]:
    """设置模板允许加载的 Skill（标识或中文名称都可以）。"""
    skills = _resolve_skills(request, body.skills)

    def fn(data: dict[str, Any], text: str) -> str:
        data["skills"] = skills
        return text

    _mutate(request, tid, fn)
    return {"skills": skills}


# ============================================================================ 用例
def _case_dto(case) -> dict[str, Any]:
    total = len(case.expectedValues)
    return {**case.model_dump(), "mobile": case.inputs.get("手机号码", ""), "busiName": case.inputs.get("业务名称", ""),
            "createTime": case.inputs.get("创建时间", ""), "busiMonth": case.inputs.get("业务月份", ""),
            "expectedCount": f"{sum(1 for v in case.expectedValues.values() if v)} / {total}" if total else "—",
            "updatedAt": fmt_time(case.updatedAt)}


@router.get("/templates/{tid}/cases")
def list_cases(request: Request, tid: int) -> list[dict[str, Any]]:
    _working(request, tid)
    return [_case_dto(c) for c in container(request).cases.list(tid)]


@router.post("/templates/{tid}/cases")
def create_case(request: Request, tid: int, body: dict[str, Any]) -> dict[str, Any]:
    c = container(request)
    _working(request, tid)
    raw_id = str(body.get("id") or "").strip()
    if raw_id:
        _check_case_id(raw_id)
    case_id = raw_id or c.cases.next_id(tid)
    if c.cases.get(tid, case_id) is not None:
        case_id = c.cases.next_id(tid)
    data = {**body, "id": case_id}
    if body.get("fromRunId"):
        from_run_id = str(body["fromRunId"]).strip()
        if not SAFE_ID_RE.match(from_run_id):
            raise bad_request("运行记录编号格式不合法", "INVALID_RUN_ID")
        run = c.runs.get(from_run_id)
        if run is None:
            raise not_found(f"运行记录 {from_run_id} 不存在")
        data.setdefault("inputs", run.get("inputs") or {})
        data.setdefault("documentText", run.get("document") or "")
        data.setdefault("expectedValues", {
            # #Created By AiCoding(codex) 列表字段的值转为 JSON 文本保存
            str(f["name"]): ("" if f.get("value") is None else json.dumps(f["value"], ensure_ascii=False)
                             if isinstance(f.get("value"), (list, dict)) else str(f.get("value")))
            for f in (run.get("fields") or [])
            if isinstance(f, dict) and f.get("name") and (f.get("status") or f.get("runStatus")) == "found"
        })
        data.setdefault("source", "由运行记录转入")
    try:
        case = c.cases.save(tid, CaseStore.from_payload(data))
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    return _case_dto(case)


@router.put("/templates/{tid}/cases/{case_id}")
def update_case(request: Request, tid: int, case_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _working(request, tid)
    _check_case_id(case_id)
    c = container(request)
    base = c.cases.get(tid, case_id)
    if base is None:
        raise not_found(f"用例 {case_id} 不存在")
    case = c.cases.save(tid, CaseStore.from_payload({**body, "id": case_id}, base))
    return _case_dto(case)


@router.delete("/templates/{tid}/cases/{case_id}")
def delete_case(request: Request, tid: int, case_id: str) -> dict[str, Any]:
    _working(request, tid)
    _check_case_id(case_id)
    if not container(request).cases.delete(tid, case_id):
        raise not_found(f"用例 {case_id} 不存在")
    return {"deletedId": case_id}


# ============================================================================ 试运行
class DryRunBody(BaseModel):
    targetVersion: Literal["draft", "online"] = "draft"
    inputs: dict[str, Any] = Field(default_factory=dict)
    documentText: str = ""
    caseId: str | None = None


def _dry_request(request: Request, tid: int, body: DryRunBody) -> RunRequest:
    _check_tid(tid)
    c = container(request)
    inputs, doc = dict(body.inputs), body.documentText
    if body.caseId:
        _check_case_id(body.caseId)
        case = c.cases.get(tid, body.caseId)
        if case is None:
            raise not_found(f"用例 {body.caseId} 不存在")
        inputs = {**case.inputs, **inputs}
        doc = doc or case.documentText
    return RunRequest(template_id=tid, inputs={k: "" if v is None else str(v) for k, v in inputs.items()},
                      document=doc, entry="试运行", target=body.targetVersion, operator=operator(request),
                      extra={"caseId": body.caseId} if body.caseId else {})


@router.post("/templates/{tid}/dryrun")
async def dry_run(request: Request, tid: int, body: DryRunBody) -> dict[str, Any]:
    out = await container(request).runner.run(_dry_request(request, tid, body))
    return detail_view(out)


@router.post("/templates/{tid}/dryrun/stream")
async def dry_run_stream(request: Request, tid: int, body: DryRunBody):
    """SSE：event=event 为过程事件，event=final 为完整结果，event=error 为启动失败。"""
    return sse_run(container(request).runner, _dry_request(request, tid, body), detail_view)


__all__ = ["router", "ResourceNotFound"]
