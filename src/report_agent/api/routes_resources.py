"""Skill 库、接口库、系统提示词的管理接口。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Literal

import yaml
from fastapi import APIRouter, Body, Depends, Query, Request
from pydantic import BaseModel, Field, ValidationError

from ..domain.api_contract import parse_api_yaml
from ..domain.resources import SYSTEM_PROMPT_FILE, validate_api
from ..domain.skill import build_skill_markdown
from ..gateway import unified_xml
from ..store.fsutil import fmt_time
from ..store.layout import API_NAME_RE, REV_RE, SKILL_ID_RE
from ..store.runtime_config import RuntimeConfigStore, RuntimeConfigValidationError
from ..store.service import SP_REF, InvalidResource, api_ref, skill_ref
from .auth import require_user
from .common import bad_request, container, not_found, operator
from .dto import api_item, skill_item

router = APIRouter(prefix="/api/v1", tags=["Skill / 接口 / 系统提示词"], dependencies=[Depends(require_user)])

_SKILL_ID_RE = SKILL_ID_RE
_API_NAME_RE = API_NAME_RE


def _check_skill_id(sid: str) -> str:
    if not _SKILL_ID_RE.match(sid):
        raise bad_request("Skill 标识只能使用小写字母、数字和短横线，最长 64 位", "INVALID_SKILL_ID")
    return sid


def _check_api_name(name: str) -> str:
    if not _API_NAME_RE.match(name):
        raise bad_request("接口编码只能使用字母、数字、下划线和短横线，且以字母开头", "INVALID_API_NAME")
    return name


class PublishBody(BaseModel):
    note: str = ""


class RollbackBody(BaseModel):
    targetRev: str
    mode: Literal["draft_only", "publish_now"] = "draft_only"
    reason: str = ""


def _revisions(request: Request, ref) -> list[dict[str, Any]]:
    c = container(request)
    online = c.releases.online_change(ref)
    return [{"rev": e["rev"], "type": e.get("type"), "operator": e.get("operator"), "time": fmt_time(e.get("time")),
             "note": e.get("note") or e.get("summary"), "summary": e.get("summary"),
             "online": bool(online and online["rev"] == e["rev"])} for e in c.releases.history(ref)]


# ============================================================================ Skill
def _safe_overlay(c):
    try:
        return c.service.overlay()
    except (InvalidResource, ValueError):
        _, live = c.service.live()
        return live


def _skill_refs(request: Request, sid: str) -> list[str]:
    rs = _safe_overlay(container(request))
    return [f"{t.id} {t.name}" for t in sorted(rs.templates.values(), key=lambda t: t.id) if sid in t.definition.skills]


def _skill_item(request: Request, sid: str) -> dict[str, Any]:
    c = container(request)
    try:
        sk = c.service.skill_working(sid)
    except (InvalidResource, ValueError):
        sk = c.service.skill_online(sid)
    if sk is None:
        raise not_found(f"Skill {sid} 不存在")
    return skill_item(sk, c.service.state(skill_ref(sid)), _skill_refs(request, sid), c.runs.stats_7d())


@router.get("/skills")
def list_skills(request: Request) -> list[dict[str, Any]]:
    c = container(request)
    _, live = c.service.live()
    overlay = _safe_overlay(c)
    stats = c.runs.stats_7d()
    out = []
    for sid in c.service.keys("skill"):
        sk = overlay.skills.get(sid) or live.skills.get(sid)
        if sk is None:
            continue
        refs = [f"{t.id} {t.name}" for t in sorted(overlay.templates.values(), key=lambda t: t.id)
                if sid in t.definition.skills]
        out.append(skill_item(sk, c.service.state(skill_ref(sid), live), refs, stats))
    return out


class CreateSkillBody(BaseModel):
    id: str
    name: str
    description: str = ""
    apis: list[str] = Field(default_factory=list)


@router.post("/skills")
def create_skill(request: Request, body: CreateSkillBody) -> dict[str, Any]:
    c = container(request)
    _check_skill_id(body.id)
    if c.drafts.exists(skill_ref(body.id)) or c.service.skill_online(body.id) is not None:
        raise bad_request(f"Skill {body.id} 已存在", "SKILL_EXISTS")
    md = build_skill_markdown(body.id, body.name.strip() or body.id, body.description, body.apis)
    c.service.save_skill(body.id, md, operator(request), action="create")
    return _skill_item(request, body.id)


@router.get("/skills/{sid}")
def get_skill(request: Request, sid: str, version: str = Query("working")) -> dict[str, Any]:
    _check_skill_id(sid)
    c = container(request)
    md = c.service.skill_markdown(sid, version)
    if md is None:
        raise not_found(f"Skill {sid} 没有 {version} 版本")
    return {"item": _skill_item(request, sid), "version": version, "markdown": md,
            "draft": c.drafts.meta(skill_ref(sid))}


class SkillDraftBody(BaseModel):
    markdown: str
    revision: int | None = None


@router.put("/skills/{sid}/draft")
def save_skill_draft(request: Request, sid: str, body: SkillDraftBody) -> dict[str, Any]:
    _check_skill_id(sid)
    c = container(request)
    if not c.drafts.exists(skill_ref(sid)) and c.service.skill_online(sid) is None:
        raise not_found(f"Skill {sid} 不存在")
    meta = c.service.save_skill(sid, body.markdown, operator(request), expected_revision=body.revision)
    issues = c.service.validate_skill_working(sid)
    return {"savedAt": fmt_time(meta["updatedAt"]), "draft": meta, "issues": [i.to_dict() for i in issues]}


@router.post("/skills/{sid}/discard-draft")
def discard_skill_draft(request: Request, sid: str) -> dict[str, Any]:
    _check_skill_id(sid)
    c = container(request)
    had_draft = c.service.discard(skill_ref(sid))
    online = c.service.skill_online(sid)
    if not had_draft and online is None:
        raise not_found(f"Skill {sid} 不存在")
    return {"markdown": online.markdown if online else None, "deleted": online is None}


@router.post("/skills/{sid}/validate")
def validate_skill(request: Request, sid: str) -> dict[str, Any]:
    _check_skill_id(sid)
    c = container(request)
    issues = c.service.validate_skill_working(sid)
    state = c.service.state(skill_ref(sid))
    drift = bool(state.draft and state.online_rev and state.base_rev and state.base_rev != state.online_rev)
    return {"errors": [i.to_dict() for i in issues if i.level == "error"],
            "warnings": [i.to_dict() for i in issues if i.level == "warning"],
            "drift": {"baseRev": state.base_rev, "onlineRev": state.online_rev} if drift else None}


@router.post("/skills/{sid}/publish")
def publish_skill(request: Request, sid: str, body: PublishBody) -> dict[str, Any]:
    _check_skill_id(sid)
    c = container(request)
    ref = skill_ref(sid)
    if not c.drafts.exists(ref):
        if c.service.skill_online(sid) is None:
            raise not_found(f"Skill {sid} 不存在")
        raise bad_request("没有需要发布的草稿", "NO_DRAFT")
    result = c.service.publish_draft(ref, operator(request), body.note)
    item = _skill_item(request, sid)
    return {"id": sid, "status": item["status"], "rev": result.entry["rev"],
            "publishedAt": fmt_time(result.entry["time"]), "warnings": [i.to_dict() for i in result.warnings],
            "item": item}


@router.get("/skills/{sid}/revisions")
def skill_revisions(request: Request, sid: str) -> list[dict[str, Any]]:
    _check_skill_id(sid)
    c = container(request)
    ref = skill_ref(sid)
    revs = _revisions(request, ref)
    if not revs and not c.drafts.exists(ref) and c.service.skill_online(sid) is None:
        raise not_found(f"Skill {sid} 不存在")
    return revs


@router.post("/skills/{sid}/rollback")
def rollback_skill(request: Request, sid: str, body: RollbackBody) -> dict[str, Any]:
    _check_skill_id(sid)
    if body.mode == "publish_now" and not body.reason.strip():
        raise bad_request("直接回退上线必须填写原因")
    c = container(request)
    result = c.service.rollback(skill_ref(sid), body.targetRev, body.mode, body.reason, operator(request))
    return {**result, "item": _skill_item(request, sid), "markdown": c.service.skill_markdown(sid)}


# ============================================================================ 接口
def _api_refs(request: Request, name: str) -> list[str]:
    rs = _safe_overlay(container(request))
    return [s.title for s in rs.skills.values() if name in s.meta.apis]


def _api_item(request: Request, name: str) -> dict[str, Any]:
    c = container(request)
    try:
        api = c.service.api_working(name)
    except (InvalidResource, ValueError):
        api = c.service.api_online(name)
    if api is None:
        raise not_found(f"接口 {name} 不存在")
    return api_item(api, c.service.state(api_ref(name)), _api_refs(request, name), c.runs.stats_7d())


@router.get("/apis")
def list_apis(request: Request) -> list[dict[str, Any]]:
    c = container(request)
    _, live = c.service.live()
    overlay = _safe_overlay(c)
    stats = c.runs.stats_7d()
    out = []
    for name in c.service.keys("api"):
        api = overlay.apis.get(name) or live.apis.get(name)
        if api is None:
            continue
        refs = [s.title for s in overlay.skills.values() if name in s.meta.apis]
        out.append(api_item(api, c.service.state(api_ref(name), live), refs, stats))
    return out


class CreateApiBody(BaseModel):
    name: str
    title: str
    description: str = ""
    processCode: str | None = None
    connector: Literal["unified-gateway-xml", "unified-gateway-json"] = "unified-gateway-xml"
    format: Literal["xml", "json", "XML", "JSON"] | None = None


def _resolve_connector(body: CreateApiBody) -> str:
    if body.format is not None:
        return "unified-gateway-json" if body.format.lower() == "json" else "unified-gateway-xml"
    return body.connector


def _new_api_yaml(body: CreateApiBody) -> str:
    connector = _resolve_connector(body)
    data = {
        "name": body.name, "title": body.title.strip() or body.name, "description": body.description,
        "connector": connector, "processCode": body.processCode or body.name, "timeoutMs": 10000,
        "retry": {"maxAttempts": 1}, "idempotent": True,
        "input": {"type": "object", "required": ["手机号码"], "additionalProperties": False,
                  "properties": {"手机号码": {"type": "string", "pattern": r"^1\d{10}$", "description": "11 位手机号"}}},
        "request": {"route_type": "2", "route_value": "${手机号码}", "content": {"userMobile": "${手机号码}"}},
        "response": {"success": {"path": "operation_out.response.resp_code", "equals": "0000"},
                     "records": {"path": "operation_out.content", "columns": {}}},
    }
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000)


@router.post("/apis")
def create_api(request: Request, body: CreateApiBody) -> dict[str, Any]:
    c = container(request)
    _check_api_name(body.name)
    if c.drafts.exists(api_ref(body.name)) or c.service.api_online(body.name) is not None:
        raise bad_request(f"接口 {body.name} 已存在", "API_EXISTS")
    c.service.save_api(body.name, _new_api_yaml(body), operator(request), action="create")
    return _api_item(request, body.name)


@router.get("/apis/{name}")
def get_api(request: Request, name: str, version: str = Query("working")) -> dict[str, Any]:
    _check_api_name(name)
    c = container(request)
    text = c.service.api_yaml(name, version)
    if text is None:
        raise not_found(f"接口 {name} 没有 {version} 版本")
    return {"item": _api_item(request, name), "version": version, "yamlText": text, "draft": c.drafts.meta(api_ref(name))}


class ApiDraftBody(BaseModel):
    yamlText: str | None = None
    api: dict[str, Any] | None = Field(default=None, description="只改 title/description/timeoutMs/retry 时可以不传 yamlText")
    revision: int | None = None


@router.put("/apis/{name}/draft")
def save_api_draft(request: Request, name: str, body: ApiDraftBody) -> dict[str, Any]:
    _check_api_name(name)
    c = container(request)
    if not c.drafts.exists(api_ref(name)) and c.service.api_online(name) is None:
        raise not_found(f"接口 {name} 不存在")
    text = body.yamlText
    if text is None:
        current = c.service.api_yaml(name)
        if current is None:
            raise not_found(f"接口 {name} 不存在")
        try:
            data = yaml.safe_load(current) or {}
        except yaml.YAMLError as exc:
            raise bad_request(f"当前接口 YAML 无法解析：{exc}") from exc
        if not isinstance(data, dict):
            raise bad_request("当前接口 YAML 顶层结构必须是映射对象")
        patch = body.api or {}
        for key in ("title", "description", "processCode"):
            if key in patch and patch[key] is not None:
                data[key] = str(patch[key])
        if patch.get("connector") in ("unified-gateway-xml", "unified-gateway-json"):
            data["connector"] = patch["connector"]
        elif isinstance(patch.get("format"), str) and patch["format"].lower() in ("xml", "json"):
            data["connector"] = "unified-gateway-json" if patch["format"].lower() == "json" else "unified-gateway-xml"
        if isinstance(patch.get("headers"), dict):
            data["headers"] = {str(k): str(v) for k, v in patch["headers"].items() if v is not None}
        if "idempotent" in patch and patch["idempotent"] is not None:
            data["idempotent"] = bool(patch["idempotent"])
        if patch.get("timeoutMs") is not None:
            try:
                timeout_ms = int(patch["timeoutMs"])
            except (TypeError, ValueError) as exc:
                raise bad_request("超时时间 timeoutMs 必须为正整数") from exc
            if timeout_ms <= 0:
                raise bad_request("超时时间 timeoutMs 必须大于 0")
            data["timeoutMs"] = timeout_ms
        if patch.get("retry") is not None:
            raw_retry = patch["retry"].get("maxAttempts") if isinstance(patch["retry"], dict) else patch["retry"]
            try:
                max_attempts = int(raw_retry)
            except (TypeError, ValueError) as exc:
                raise bad_request("重试次数 retry 必须为正整数") from exc
            if max_attempts < 1:
                raise bad_request("重试次数 retry 必须大于等于 1")
            data["retry"] = {"maxAttempts": max_attempts}
        text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000)
    try:
        meta = c.service.save_api(name, text, operator(request), expected_revision=body.revision)
    except ValueError as exc:
        raise bad_request(f"接口 YAML 无法解析：{exc}") from exc
    return {"savedAt": fmt_time(meta["updatedAt"]), "draft": meta}


@router.post("/apis/{name}/discard-draft")
def discard_api_draft(request: Request, name: str) -> dict[str, Any]:
    _check_api_name(name)
    c = container(request)
    had_draft = c.service.discard(api_ref(name))
    online = c.service.api_online(name)
    if not had_draft and online is None:
        raise not_found(f"接口 {name} 不存在")
    return {"yamlText": c.service.api_yaml(name, "online"), "deleted": online is None}


@router.post("/apis/{name}/publish")
def publish_api(request: Request, name: str, body: PublishBody | None = None) -> dict[str, Any]:
    _check_api_name(name)
    c = container(request)
    ref = api_ref(name)
    if not c.drafts.exists(ref):
        if c.service.api_online(name) is None:
            raise not_found(f"接口 {name} 不存在")
        raise bad_request("没有需要发布的草稿", "NO_DRAFT")
    try:
        result = c.service.publish_draft(ref, operator(request), body.note if body else "")
    except ValueError as exc:
        raise bad_request(f"接口 YAML 无法解析：{exc}") from exc
    item = _api_item(request, name)
    return {"name": name, "status": item["status"], "rev": result.entry["rev"],
            "publishedAt": fmt_time(result.entry["time"]), "item": item}


@router.get("/apis/{name}/revisions")
def api_revisions(request: Request, name: str) -> list[dict[str, Any]]:
    _check_api_name(name)
    c = container(request)
    ref = api_ref(name)
    revs = _revisions(request, ref)
    if not revs and not c.drafts.exists(ref) and c.service.api_online(name) is None:
        raise not_found(f"接口 {name} 不存在")
    return revs


@router.post("/apis/{name}/rollback")
def rollback_api(request: Request, name: str, body: RollbackBody) -> dict[str, Any]:
    _check_api_name(name)
    if body.mode == "publish_now" and not body.reason.strip():
        raise bad_request("直接回退上线必须填写原因")
    c = container(request)
    result = c.service.rollback(api_ref(name), body.targetRev, body.mode, body.reason, operator(request))
    return {**result, "item": _api_item(request, name), "yamlText": c.service.api_yaml(name)}


class ApiValidateBody(BaseModel):
    yamlText: str | None = None
    sampleParams: dict[str, Any] = Field(default_factory=dict)


def _guess_connector_from_text(yaml_text: str) -> str:
    try:
        raw = yaml.safe_load(yaml_text)
        if isinstance(raw, dict) and raw.get("connector") == "unified-gateway-json":
            return "unified-gateway-json"
    except Exception:  # noqa: BLE001
        pass
    if re.search(r"^\s*connector\s*:\s*['\"]?unified-gateway-json['\"]?\s*$", yaml_text, re.MULTILINE):
        return "unified-gateway-json"
    return "unified-gateway-xml"


@router.post("/apis/{name}/validate")
def validate_api_contract(request: Request, name: str, body: ApiValidateBody | None = None) -> dict[str, Any]:
    """校验接口契约 YAML（含语法/结构/占位符）并生成脱敏 XML/JSON 请求预览报文。"""
    _check_api_name(name)
    c = container(request)
    yaml_text = body.yamlText if body is not None else None
    sample_params = dict(body.sampleParams) if (body is not None and isinstance(body.sampleParams, dict)) else {}
    if yaml_text is None:
        yaml_text = c.service.api_yaml(name)
        if yaml_text is None:
            raise not_found(f"接口 {name} 不存在")
    try:
        api = parse_api_yaml(yaml_text)
    except ValidationError as exc:
        conn = _guess_connector_from_text(yaml_text)
        errs = [f"{'.'.join(str(p) for p in e['loc']) or '契约'}：{e['msg']}" for e in exc.errors()]
        return {"ok": False, "errors": errs, "connector": conn,
                "format": "json" if conn == "unified-gateway-json" else "xml", "requestPreview": ""}
    except (yaml.YAMLError, ValueError) as exc:
        conn = _guess_connector_from_text(yaml_text)
        return {"ok": False, "errors": [f"YAML 解析失败：{exc}"], "connector": conn,
                "format": "json" if conn == "unified-gateway-json" else "xml", "requestPreview": ""}

    errors: list[str] = []
    if api.name != name:
        errors.append(f"YAML 中 name={api.name} 必须与接口编码 {name} 一致")
    errors.extend(i.message for i in validate_api(api))

    is_json = bool(getattr(api, "is_json", api.connector == "unified-gateway-json"))
    fmt = "json" if is_json else "xml"
    preview = ""
    preview_fn = getattr(unified_xml, "build_request_preview", None)
    try:
        if preview_fn is not None:
            preview = preview_fn(api, sample_params, style=c.settings.gateway_xml_style)
        else:
            req_data = api.build_request(sample_params)
            preview = unified_xml.mask_xml(
                unified_xml.build_request_xml(api.processCode, req_data, "***", "***", c.settings.gateway_xml_style)
            )
    except Exception as exc:  # noqa: BLE001
        if not errors:
            errors.append(f"请求预览生成失败：{exc}")

    return {"ok": len(errors) == 0, "errors": errors, "connector": api.connector,
            "format": fmt, "requestPreview": preview}


class TestCallBody(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    yamlText: str | None = Field(default=None, description="用未保存的 YAML 试调用；不传使用工作副本")


@router.post("/apis/{name}/test-call")
async def test_call(request: Request, name: str, body: TestCallBody) -> dict[str, Any]:
    """按契约校验参数并真实调用一次网关（mock 模式读样例文件）。调用会写审计日志。"""
    _check_api_name(name)
    c = container(request)
    if body.yamlText is not None:
        try:
            api = parse_api_yaml(body.yamlText)
        except Exception as exc:  # noqa: BLE001
            raise bad_request(f"YAML 无法解析：{exc}") from exc
        if api.name != name:
            raise bad_request(f"YAML 中 name={api.name} 必须与接口编码 {name} 一致", "API_NAME_MISMATCH")
        schema_errors = [i.message for i in validate_api(api)]
        if schema_errors:
            raise bad_request("；".join(schema_errors), "INVALID_API_SCHEMA", errors=schema_errors)
    else:
        try:
            api = c.service.api_working(name)
        except (InvalidResource, ValueError) as exc:
            raise bad_request(f"接口 YAML 无法解析：{exc}") from exc
    if api is None:
        raise not_found(f"接口 {name} 不存在")
    errors = api.validate_args(body.params)
    if errors:
        raise bad_request("参数不合法", "INVALID_PARAMS", errors=errors)
    res = await c.gateway.invoke(api, body.params)
    is_json = bool(getattr(api, "is_json", api.connector == "unified-gateway-json"))
    fmt = "json" if is_json else "xml"
    op = operator(request)
    await asyncio.to_thread(
        c.publisher.audit,
        "api-test-call",
        op,
        {"api": name, "connector": api.connector, "ok": res.ok, "costMs": res.cost_ms},
    )
    return {"ok": res.ok, "error": res.error, "costMs": res.cost_ms, "httpStatus": res.http_status,
            "noData": res.no_data, "format": fmt, "connector": api.connector,
            "rawXml": res.raw, "requestXml": res.request_preview,
            "rawBody": res.raw, "requestBody": res.request_preview,
            "records": [{"row": i, **r} for i, r in enumerate(res.records)], "columns": api.response.records.columns}


# ============================================================================ 系统提示词
def _sp_state(request: Request) -> dict[str, Any]:
    c = container(request)
    state = c.service.state(SP_REF)
    return {"sysPromptText": c.service.system_prompt("working"), "sysPromptStatus": state.status,
            "onlineText": c.service.system_prompt("online"), "onlineRev": state.online_rev,
            "baseRev": state.base_rev, "draft": state.draft}


@router.get("/settings/system-prompt")
def get_system_prompt(request: Request, version: str = Query("working")) -> dict[str, Any]:
    c = container(request)
    ver = version if version != "" else "working"
    if ver not in ("working", "online", "draft") and not REV_RE.match(ver):
        raise bad_request(f"版本号「{version}」格式不合法", "INVALID_VERSION")
    if ver == "draft" and not c.drafts.exists(SP_REF):
        raise not_found("系统提示词没有未发布的草稿版本")
    if REV_RE.match(ver):
        text = c.releases.read_file_at(ver, SYSTEM_PROMPT_FILE)
        if text is None:
            raise not_found(f"系统提示词没有 {ver} 版本")
    else:
        text = c.service.system_prompt(ver)
    return {**_sp_state(request), "version": ver, "versionText": text}


class SysPromptBody(BaseModel):
    sysPromptText: str | None = None
    note: str = ""
    revision: int | None = None


@router.put("/settings/system-prompt/draft")
def save_system_prompt(request: Request, body: SysPromptBody) -> dict[str, Any]:
    c = container(request)
    if body.sysPromptText is None:
        raise bad_request("sysPromptText 不能为空")
    c.service.save_system_prompt(body.sysPromptText, operator(request), body.revision)
    return {"status": c.service.state(SP_REF).status, **_sp_state(request)}


@router.post("/settings/system-prompt/publish")
def publish_system_prompt(request: Request, body: SysPromptBody) -> dict[str, Any]:
    """发布系统提示词。传入 sysPromptText 时先保存为草稿再发布。"""
    c = container(request)
    if body.sysPromptText is not None:
        c.service.save_system_prompt(body.sysPromptText, operator(request))
    if not c.drafts.exists(SP_REF):
        raise bad_request("没有需要发布的草稿", "NO_DRAFT")
    result = c.service.publish_draft(SP_REF, operator(request), body.note)
    return {
        "status": c.service.state(SP_REF).status,
        "rev": result.entry["rev"],
        "publishedAt": fmt_time(result.entry["time"]),
        **_sp_state(request),
    }


@router.post("/settings/system-prompt/discard-draft")
def discard_system_prompt(request: Request) -> dict[str, Any]:
    container(request).service.discard(SP_REF)
    return _sp_state(request)


@router.post("/settings/system-prompt/rollback")
def rollback_system_prompt(request: Request, body: RollbackBody) -> dict[str, Any]:
    if body.mode == "publish_now" and not body.reason.strip():
        raise bad_request("直接回退上线必须填写原因")
    c = container(request)
    result = c.service.rollback(SP_REF, body.targetRev, body.mode, body.reason, operator(request))
    return {**result, "status": c.service.state(SP_REF).status, **_sp_state(request)}


@router.get("/settings/system-prompt/revisions")
def system_prompt_revisions(request: Request) -> list[dict[str, Any]]:
    return _revisions(request, SP_REF)


# ============================================================================ 运行配置（统一网关 + 大模型热更新）
def _runtime_store(c) -> RuntimeConfigStore:
    if c.runtime_config is None:
        c.runtime_config = RuntimeConfigStore(c.layout, c.lock)
        c.runtime_config.bootstrap_or_load(c.env_settings or c.settings)
    return c.runtime_config


@router.get("/settings/model")
def model_info(request: Request) -> dict[str, Any]:
    """当前模型与运行参数（不含密钥）。"""
    c = container(request)
    s = c.settings
    active_rev = _runtime_store(c).active_rev()
    return {
        "model": s.llm_model,
        "baseUrl": s.llm_base_url,
        "temperature": s.llm_temperature,
        "maxTokens": s.llm_max_tokens,
        "timeoutS": s.llm_timeout_s,
        "httpRetries": s.llm_http_retries,
        "outputMode": s.agent_output_mode,
        "outputRetries": s.agent_output_retries,
        "toolRetries": s.agent_tool_retries,
        "requestLimit": s.agent_request_limit,
        "toolCallsLimit": s.agent_tool_calls_limit,
        "runTimeoutS": s.agent_run_timeout_s,
        "maxConcurrentRuns": s.agent_max_concurrent_runs,
        "gatewayMode": s.gateway_mode,
        "gatewayUrl": s.gateway_url,
        "gatewayXmlStyle": s.gateway_xml_style,
        "gatewayConnectTimeoutS": s.gateway_connect_timeout_s,
        "activeRev": active_rev,
    }


@router.get("/settings/runtime")
def get_runtime_settings(request: Request) -> dict[str, Any]:
    """读取当前生效的运行配置（密钥已脱敏）与版本元数据。"""
    return _runtime_store(container(request)).public_state()


def _flag_bool(raw: Any, name: str) -> bool:
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    raise bad_request(f"{name} 必须是布尔值", "INVALID_RUNTIME_CONFIG")


@router.put("/settings/runtime")
async def update_runtime_settings(request: Request, body: Any = Body(default=None)) -> dict[str, Any]:
    """更新并持久化运行配置，成功后立即在进程内热重载网关与模型客户端（免重启）。"""
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise bad_request("请求体必须是 JSON 对象", "INVALID_RUNTIME_CONFIG")
    nested = body.get("config")
    if nested is not None and not isinstance(nested, dict):
        raise bad_request("config 字段必须是 JSON 对象", "INVALID_RUNTIME_CONFIG")
    patch = {**(nested or {}), **body}
    raw_note = patch.get("note", "")
    if raw_note is not None and not isinstance(raw_note, str):
        raise bad_request("note 必须是字符串", "INVALID_RUNTIME_CONFIG")
    clear_llm = _flag_bool(patch.get("clearLlmApiKey"), "clearLlmApiKey")
    clear_app_id = _flag_bool(patch.get("clearGatewayAppId"), "clearGatewayAppId")
    clear_token = _flag_bool(patch.get("clearGatewayAccessToken"), "clearGatewayAccessToken")

    c = container(request)
    op = operator(request)

    def _do_update() -> tuple[dict[str, Any], bool]:
        store = _runtime_store(c)
        _, did_change = store.update(
            patch,
            op,
            clear_llm_api_key=clear_llm,
            clear_gateway_app_id=clear_app_id,
            clear_gateway_access_token=clear_token,
            note=raw_note or "",
        )
        if did_change:
            c.apply_runtime_config()
        return store.public_state(), did_change

    try:
        state, changed = await asyncio.to_thread(_do_update)
    except RuntimeConfigValidationError as exc:
        raise bad_request(str(exc), "INVALID_RUNTIME_CONFIG", errors=exc.errors) from exc

    if changed and hasattr(c.gateway, "aclose_retired"):
        await c.gateway.aclose_retired()
    return state


@router.get("/settings/runtime/revisions")
def list_runtime_revisions(request: Request) -> list[dict[str, Any]]:
    """按版本号倒序返回运行配置修订历史（含变更字段列表与脱敏快照）。"""
    return _runtime_store(container(request)).revisions()


class RuntimeRollbackBody(BaseModel):
    targetRev: str = ""
    reason: str = ""


@router.post("/settings/runtime/rollback")
async def rollback_runtime_settings(request: Request, body: RuntimeRollbackBody) -> dict[str, Any]:
    """回退运行配置至指定历史版本 cN，生成新版本并立即热重载生效。"""
    c = container(request)
    op = operator(request)

    def _do_rollback() -> dict[str, Any]:
        store = _runtime_store(c)
        store.rollback(body.targetRev, body.reason, op)
        c.apply_runtime_config()
        return {**store.public_state(), "targetRev": body.targetRev.strip()}

    try:
        out = await asyncio.to_thread(_do_rollback)
    except RuntimeConfigValidationError as exc:
        raise bad_request(str(exc), "INVALID_RUNTIME_CONFIG", errors=exc.errors) from exc
    if hasattr(c.gateway, "aclose_retired"):
        await c.gateway.aclose_retired()
    return out


class RuntimeSyncEnvBody(BaseModel):
    note: str = ""


@router.post("/settings/runtime/sync-env")
async def sync_runtime_settings_from_env(request: Request, body: RuntimeSyncEnvBody | None = None) -> dict[str, Any]:
    """从进程启动时的环境变量重新同步运行配置并立即热重载生效。"""
    c = container(request)
    op = operator(request)
    note_val = body.note if body else ""

    def _do_sync() -> tuple[dict[str, Any], bool]:
        store = _runtime_store(c)
        _, did_change = store.sync_from_env(
            c.env_settings or c.settings,
            op,
            note=note_val,
        )
        if did_change:
            c.apply_runtime_config()
        return store.public_state(), did_change

    try:
        state, changed = await asyncio.to_thread(_do_sync)
    except RuntimeConfigValidationError as exc:
        raise bad_request(str(exc), "INVALID_RUNTIME_CONFIG", errors=exc.errors) from exc
    if changed and hasattr(c.gateway, "aclose_retired"):
        await c.gateway.aclose_retired()
    return state
