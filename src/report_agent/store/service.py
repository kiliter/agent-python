"""资源服务：把“线上版本 + 草稿”组合成管理端需要的工作副本、状态和操作。

#Created By AiCoding(codex)
状态规则（与前端 ResourceStatus 一致）：
  线上有、未下线：有草稿 → PUBLISHED_DRAFT，否则 PUBLISHED
  线上有、已下线：有草稿 → DRAFT，否则 OFFLINE
  线上没有：有草稿 → DRAFT
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Any, Literal

import yaml
from pydantic import ValidationError

from ..domain.api_contract import ApiContract, parse_api_yaml
from ..domain.resources import (Issue, ResourceSet, SYSTEM_PROMPT_FILE, load_template_dir, validate_api,
                                validate_skill, validate_template)
from ..domain.skill import SKILL_FILE, Skill, SkillParseError, parse_skill_markdown
from ..domain.template import (BODY_FILE, OFFLINE_FILE, TEMPLATE_FILE, Template, TemplateDef, dump_template_yaml,
                               parse_template_yaml)
from .drafts import DraftConflict, DraftStore
from .fsutil import now_iso
from .layout import REV_RE, SYSTEM_PROMPT_KEY, DataLayout, InvalidResource, ResourceRef, ensure_within
from .publisher import Change, NothingToPublish, Publisher, PublishResult
from .releases import ReleaseStore

log = logging.getLogger(__name__)

Status = Literal["DRAFT", "PUBLISHED", "PUBLISHED_DRAFT", "OFFLINE"]


class ResourceNotFound(KeyError):
    """资源不存在。"""


def _check_version(version: str) -> str:
    if version in ("working", "draft", "online", ""):
        return version
    if not isinstance(version, str) or not REV_RE.match(version):
        raise InvalidResource(f"版本号「{version}」格式不合法")
    return version


@dataclass
class ResourceState:
    """资源在管理端展示的状态信息。"""

    ref: ResourceRef
    status: Status
    online_rev: str | None
    base_rev: str | None
    draft: dict[str, Any] | None
    last_published_at: str | None
    publisher: str | None
    in_live: bool
    offline: bool


def tpl_ref(tid: int | str) -> ResourceRef:
    return ResourceRef("template", str(tid))


def skill_ref(sid: str) -> ResourceRef:
    return ResourceRef("skill", sid)


def api_ref(name: str) -> ResourceRef:
    return ResourceRef("api", name)


SP_REF = ResourceRef("system-prompt", SYSTEM_PROMPT_KEY)


class ResourceService:
    """管理端资源操作的入口。"""

    def __init__(self, layout: DataLayout, releases: ReleaseStore, drafts: DraftStore, publisher: Publisher,
                 lock: threading.RLock) -> None:
        self.layout = layout
        self.releases = releases
        self.drafts = drafts
        self.publisher = publisher
        self.lock = lock
        self._draft_mutation_seq = 0
        self._overlay_lock = threading.Lock()
        self._overlay_cache: tuple[tuple[Any, ...], ResourceSet] | None = None

    def _bump_draft_seq(self) -> None:
        """草稿或发布状态变更时递增序号，使 overlay() 内存缓存立即失效。"""
        with self._overlay_lock:
            self._draft_mutation_seq += 1
            self._overlay_cache = None

    def _drafts_fingerprint(self) -> tuple[tuple[str, str, str, int, int], ...]:
        """采集 drafts/ 下活跃草稿文件的轻量 (kind, key, file, mtime_ns, size) 指纹，兼顾直接写盘测试场景。"""
        root = self.layout.drafts
        if not root.is_dir():
            return ()
        entries: list[tuple[str, str, str, int, int]] = []
        try:
            with os.scandir(root) as kind_it:
                for kind_entry in kind_it:
                    if kind_entry.name.startswith(".") or not kind_entry.is_dir(follow_symlinks=False):
                        continue
                    try:
                        with os.scandir(kind_entry.path) as key_it:
                            for key_entry in key_it:
                                if key_entry.name.startswith(".") or not key_entry.is_dir(follow_symlinks=False):
                                    continue
                                try:
                                    with os.scandir(key_entry.path) as file_it:
                                        for f_entry in file_it:
                                            try:
                                                if not f_entry.is_file(follow_symlinks=False):
                                                    continue
                                                st = f_entry.stat(follow_symlinks=False)
                                                entries.append((
                                                    kind_entry.name,
                                                    key_entry.name,
                                                    f_entry.name,
                                                    st.st_mtime_ns,
                                                    st.st_size,
                                                ))
                                            except OSError:
                                                continue
                                except OSError:
                                    continue
                    except OSError:
                        continue
        except OSError:
            return ()
        entries.sort()
        return tuple(entries)

    def _check_missing_draft_conflict(
        self,
        ref: ResourceRef,
        expected_revision: int | None,
        change: dict[str, Any] | None,
    ) -> None:
        """当客户端携带正整数草稿 revision 但服务端草稿已被他人发布或丢弃时，触发 409 冲突保护。"""
        if expected_revision is not None and expected_revision > 0 and not self.drafts.exists(ref):
            raise DraftConflict({
                "kind": ref.kind,
                "key": ref.key,
                "revision": 0,
                "baseRev": change["rev"] if change else None,
                "updatedBy": (change or {}).get("operator", ""),
                "updatedAt": (change or {}).get("time", ""),
                "status": "NO_DRAFT",
            })

    # ================================================================ 通用
    def live(self) -> tuple[str | None, ResourceSet]:
        rev = self.releases.live_rev()
        return (rev, self.releases.snapshot(rev)) if rev else (None, ResourceSet())

    def _in_live(self, ref: ResourceRef, rs: ResourceSet) -> tuple[bool, bool]:
        """（线上是否存在，是否已下线）。"""
        if ref.kind == "template":
            tpl = rs.templates.get(int(ref.key)) if ref.key.isdigit() else None
            return (tpl is not None, bool(tpl and tpl.offline))
        if ref.kind == "skill":
            return (ref.key in rs.skills, False)
        if ref.kind == "api":
            return (ref.key in rs.apis, False)
        return (bool(rs.system_prompt), False)

    def state(self, ref: ResourceRef, rs: ResourceSet | None = None) -> ResourceState:
        """计算资源状态。"""
        if rs is None:
            _, rs = self.live()
        in_live, offline = self._in_live(ref, rs)
        draft = self.drafts.meta(ref)
        if not in_live and not draft and ref.kind != "system-prompt":
            raise ResourceNotFound(ref.label())
        change = self.releases.online_change(ref) if in_live else None
        if in_live and not offline:
            status: Status = "PUBLISHED_DRAFT" if draft else "PUBLISHED"
        elif in_live and offline:
            status = "DRAFT" if draft else "OFFLINE"
        else:
            status = "DRAFT"
        online_rev = change["rev"] if change and not offline else None
        base_rev = (draft or {}).get("baseRev") if draft else online_rev
        return ResourceState(
            ref=ref, status=status, online_rev=online_rev, base_rev=base_rev, draft=draft,
            last_published_at=change["time"] if change else None,
            publisher=change["operator"] if change else None, in_live=in_live, offline=offline,
        )

    def keys(self, kind: str) -> list[str]:
        """线上与草稿中该类资源的全部标识。"""
        _, rs = self.live()
        if kind == "template":
            live_keys = [str(k) for k in rs.templates]
        elif kind == "skill":
            live_keys = list(rs.skills)
        elif kind == "api":
            live_keys = list(rs.apis)
        else:
            live_keys = [SYSTEM_PROMPT_KEY]
        keys = list(dict.fromkeys([*live_keys, *self.drafts.list_keys(kind)]))
        if kind == "template":
            keys.sort(key=lambda k: int(k) if k.isdigit() else 0)
        return keys

    def discard(self, ref: ResourceRef) -> bool:
        """放弃草稿。"""
        deleted = self.drafts.delete(ref)
        if deleted:
            self._bump_draft_seq()
        return deleted

    def publish_draft(self, ref: ResourceRef, operator: str, note: str = "", type_label: str = "发布",
                      summary: str | None = None) -> PublishResult:
        """发布某个资源的草稿。草稿与线上内容语义相同（例如只是重新保存）时拒绝发布。"""
        if self._same_as_online(ref):
            raise NothingToPublish("草稿内容与线上版本一致，无需发布")
        title = self.title_of(ref)
        summary = summary or f"{type_label} {self.summary_label(ref, title)}"
        result = self.publisher.publish([Change(ref, "publish", title=title, source="draft")], operator,
                                        type_label, summary, note)
        self._bump_draft_seq()
        return result

    def _same_as_online(self, ref: ResourceRef) -> bool:
        """草稿解析后是否与线上一致（忽略 YAML 注释、键顺序等格式差异）。"""
        try:
            if ref.kind == "template":
                draft, online = self._template_from_draft(int(ref.key)), self.template_online(int(ref.key))
                return bool(draft and online and not online.offline and draft.definition == online.definition
                            and draft.body == online.body)
            if ref.kind == "skill":
                draft_md, online_sk = self.drafts.read_file(ref, SKILL_FILE), self.skill_online(ref.key)
                return bool(draft_md is not None and online_sk and draft_md == online_sk.markdown)
            if ref.kind == "api":
                draft_api, online_api = self._api_from_draft(ref.key), self.api_online(ref.key)
                return bool(draft_api and online_api and draft_api == online_api)
            text = self.drafts.read_file(ref, SYSTEM_PROMPT_FILE)
            return text is not None and text == self.system_prompt("online")
        except (InvalidResource, ValueError):
            return False

    def summary_label(self, ref: ResourceRef, title: str) -> str:
        """版本说明中的资源描述，模板格式为“模板 1001（名称）”，前端依赖这个格式解析。"""
        if ref.kind == "template":
            return f"模板 {ref.key}（{title}）"
        if ref.kind == "skill":
            return f"Skill {ref.key}（{title}）"
        if ref.kind == "api":
            return f"接口 {ref.key}（{title}）" if title and title != ref.key else f"接口 {ref.key}"
        return "系统提示词"

    def title_of(self, ref: ResourceRef) -> str:
        """资源的中文名称（优先草稿）。"""
        try:
            if ref.kind == "template":
                tpl = self.template_working(int(ref.key))
                return tpl.name if tpl else ref.key
            if ref.kind == "skill":
                sk = self.skill_working(ref.key)
                return sk.title if sk else ref.key
            if ref.kind == "api":
                api = self.api_working(ref.key)
                return api.title if api else ref.key
        except (InvalidResource, ValueError):
            pass
        return "系统提示词" if ref.kind == "system-prompt" else ref.key

    def rollback(self, ref: ResourceRef, target_rev: str, mode: Literal["draft_only", "publish_now"],
                 reason: str, operator: str) -> dict[str, Any]:
        """把资源恢复到某个历史版本：draft_only 只写入草稿；publish_now 直接发布为新版本。"""
        self.releases.entry(target_rev)
        tree = self.releases.ensure_materialized(target_rev)
        target_path = tree / ref.tree_path()
        if not target_path.exists():
            raise ResourceNotFound(f"{ref.label()} 在 {target_rev} 中不存在")
        target_offline = ref.kind == "template" and (target_path / OFFLINE_FILE).exists()
        title = self.title_of(ref)
        if mode == "publish_now":
            summary = f"回退 {self.summary_label(ref, title)} 至 {target_rev}" + (f"（{reason}）" if reason else "")
            with self.lock:
                result = self.publisher.publish(
                    [Change(ref, "rollback", title=title, source="tree", source_dir=tree)],
                    operator, "回退", summary, reason)
                self.drafts.delete(ref)
                self._bump_draft_seq()
            return {
                "mode": mode,
                "rev": result.entry["rev"],
                "targetRev": target_rev,
                "targetOffline": target_offline,
            }
        files = self._files_from_tree(ref, tree)
        state_online = self.releases.online_change(ref)
        action = f"rollback:{target_rev}:offline-source" if target_offline else f"rollback:{target_rev}"
        with self.lock:
            self.drafts.write(ref, files, operator, base_rev=state_online["rev"] if state_online else None,
                              action=action)
            self.drafts.rebase(ref, state_online["rev"] if state_online else None, action=action)
            self._bump_draft_seq()
        out: dict[str, Any] = {
            "mode": mode,
            "rev": target_rev,
            "targetRev": target_rev,
            "targetOffline": target_offline,
        }
        if target_offline:
            out["warning"] = (
                f"注意：目标版本 {target_rev} 中该模板处于已下线归档状态；"
                "恢复到草稿仅载入其模板定义与正文（不含下线标记），核对发布后将作为上线版本生效"
            )
        return out

    def _files_from_tree(self, ref: ResourceRef, tree) -> dict[str, str]:
        """从一棵发布树中取出资源文件内容（用于写入草稿）。"""
        path = ensure_within(tree, tree / ref.tree_path())
        if ref.is_dir():
            return {p.name: p.read_text(encoding="utf-8") for p in path.iterdir()
                    if p.is_file() and not p.is_symlink() and p.name not in (OFFLINE_FILE, ".meta.json")}
        return {self.drafts.single_file_name(ref): path.read_text(encoding="utf-8")}

    @staticmethod
    def _clone_resource_set(rs: ResourceSet) -> ResourceSet:
        """返回浅拷贝，避免外部调用方修改缓存字典或问题列表。"""
        return ResourceSet(
            system_prompt=rs.system_prompt,
            templates=dict(rs.templates),
            skills=dict(rs.skills),
            apis=dict(rs.apis),
            load_issues=list(rs.load_issues),
        )

    def overlay(self) -> ResourceSet:
        """线上资源叠加全部草稿（试运行“用草稿”及工作台聚合读取使用），按 (live_rev, seq, 草稿指纹) 缓存。"""
        with self._overlay_lock:
            seq = self._draft_mutation_seq
        live_rev, live = self.live()
        fp = self._drafts_fingerprint()
        cache_key = (live_rev, seq, fp)
        with self._overlay_lock:
            if (
                self._draft_mutation_seq == seq
                and self._overlay_cache is not None
                and self._overlay_cache[0] == cache_key
            ):
                return self._clone_resource_set(self._overlay_cache[1])

        rs = ResourceSet(system_prompt=live.system_prompt, templates=dict(live.templates),
                         skills=dict(live.skills), apis=dict(live.apis))
        for key in self.drafts.list_keys("template"):
            try:
                tpl = self._template_from_draft(int(key))
                if tpl:
                    rs.templates[tpl.id] = tpl
            except (InvalidResource, ValueError) as exc:
                rs.load_issues.append(Issue("error", "DRAFT_INVALID", str(exc), "template", key))
        for key in self.drafts.list_keys("skill"):
            try:
                sk = self._skill_from_draft(key)
                if sk:
                    rs.skills[sk.id] = sk
            except (InvalidResource, ValueError) as exc:
                rs.load_issues.append(Issue("error", "DRAFT_INVALID", str(exc), "skill", key))
        for key in self.drafts.list_keys("api"):
            try:
                api = self._api_from_draft(key)
                if api:
                    rs.apis[api.name] = api
            except (InvalidResource, ValueError) as exc:
                rs.load_issues.append(Issue("error", "DRAFT_INVALID", str(exc), "api", key))
        sp = self.drafts.read_file(SP_REF, SYSTEM_PROMPT_FILE)
        if sp is not None:
            rs.system_prompt = sp

        # 在锁外做复核 IO，写入缓存前在锁内同时复核 seq 与 live_rev
        cur_fp = (
            self._drafts_fingerprint()
            if self.releases.live_rev() == live_rev and self._draft_mutation_seq == seq
            else None
        )
        if cur_fp == fp:
            with self._overlay_lock:
                if self._draft_mutation_seq == seq and self.releases.live_rev() == live_rev:
                    self._overlay_cache = (cache_key, rs)
        return self._clone_resource_set(rs)

    # ================================================================ 模板
    def _template_from_draft(self, tid: int) -> Template | None:
        ref = tpl_ref(tid)
        if not self.drafts.exists(ref):
            return None
        try:
            return load_template_dir(self.layout.draft_dir(ref))
        except (ValidationError, yaml.YAMLError, ValueError, OSError) as exc:
            raise InvalidResource(f"模板 {tid} 草稿无法解析：{exc}") from exc

    def template_online(self, tid: int) -> Template | None:
        _, rs = self.live()
        return rs.templates.get(tid)

    def template_working(self, tid: int) -> Template | None:
        """草稿优先，没有草稿取线上。"""
        return self._template_from_draft(tid) or self.template_online(tid)

    def template_at(self, tid: int, rev: str) -> Template | None:
        """某个历史版本中的模板。"""
        y = self.releases.read_file_at(rev, f"templates/{tid}/{TEMPLATE_FILE}")
        if y is None:
            return None
        body = self.releases.read_file_at(rev, f"templates/{tid}/{BODY_FILE}") or ""
        offline = self.releases.read_file_at(rev, f"templates/{tid}/{OFFLINE_FILE}") is not None
        return Template(definition=parse_template_yaml(y), body=body, offline=offline)

    def template_version(self, tid: int, version: str) -> Template | None:
        """version: working / draft / online / rN。"""
        version = _check_version(version)
        if version in ("working", ""):
            return self.template_working(tid)
        if version == "draft":
            return self._template_from_draft(tid)
        if version == "online":
            return self.template_online(tid)
        return self.template_at(tid, version)

    def save_template(self, tpl: Template, operator: str, expected_revision: int | None = None,
                      action: str = "edit") -> dict[str, Any]:
        """保存模板草稿。"""
        ref = tpl_ref(tpl.id)
        change = self.releases.online_change(ref)
        files = {TEMPLATE_FILE: dump_template_yaml(tpl.definition), BODY_FILE: tpl.body}
        with self.lock:
            self._check_missing_draft_conflict(ref, expected_revision, change)
            meta = self.drafts.write(ref, files, operator, base_rev=change["rev"] if change else None,
                                     expected_revision=expected_revision, action=action)
        self._bump_draft_seq()
        return meta

    def validate_template_working(self, tid: int, tpl: Template | None = None) -> list[Issue]:
        """校验模板工作副本（Skill 引用按“线上 + 草稿”判断）。"""
        tpl = tpl or self.template_working(tid)
        if tpl is None:
            raise ResourceNotFound(f"模板 {tid}")
        return validate_template(tpl, self.overlay())

    def offline_template(self, tid: int, operator: str, reason: str = "") -> PublishResult:
        """下线模板：生成新版本，模板文件保留，只加下线标记。"""
        ref = tpl_ref(tid)
        online = self.template_online(tid)
        if online is None and not self.drafts.exists(ref):
            raise ResourceNotFound(f"模板 {tid} 不存在")
        if online is not None and online.offline:
            raise NothingToPublish(f"模板 {tid} 已处于下线状态")
        title = self.title_of(ref)
        marker = {"by": operator, "at": now_iso(), "reason": reason}
        result = self.publisher.publish([Change(ref, "offline", title=title, source="none", offline_marker=marker)],
                                        operator, "下线", f"下线 {self.summary_label(ref, title)}", reason)
        self._bump_draft_seq()
        return result

    def restore_template(self, tid: int, operator: str) -> dict[str, Any]:
        """恢复已下线的模板：用线上内容生成一份草稿，发布后重新上线。"""
        tpl = self.template_online(tid)
        if tpl is None or not tpl.offline:
            raise ResourceNotFound(f"模板 {tid} 未下线")
        if self.drafts.exists(tpl_ref(tid)):
            return self.drafts.meta(tpl_ref(tid)) or {}
        return self.save_template(Template(definition=tpl.definition, body=tpl.body), operator, action="restore")

    # ================================================================ Skill
    def _skill_from_draft(self, sid: str) -> Skill | None:
        text = self.drafts.read_file(skill_ref(sid), SKILL_FILE)
        if text is None:
            return None
        try:
            return parse_skill_markdown(text)
        except (SkillParseError, ValidationError, yaml.YAMLError, ValueError, OSError) as exc:
            raise InvalidResource(f"Skill {sid} 草稿无法解析：{exc}") from exc

    def skill_online(self, sid: str) -> Skill | None:
        _, rs = self.live()
        return rs.skills.get(sid)

    def skill_working(self, sid: str) -> Skill | None:
        return self._skill_from_draft(sid) or self.skill_online(sid)

    def skill_markdown(self, sid: str, version: str = "working") -> str | None:
        """Skill 原文。草稿无法解析时也返回原文，便于继续编辑。"""
        version = _check_version(version)
        if version in ("working", "draft", ""):
            text = self.drafts.read_file(skill_ref(sid), SKILL_FILE)
            if text is not None or version == "draft":
                return text
            version = "online"
        if version == "online":
            sk = self.skill_online(sid)
            return sk.markdown if sk else None
        return self.releases.read_file_at(version, f"skills/{sid}/{SKILL_FILE}")

    def save_skill(self, sid: str, markdown: str, operator: str, expected_revision: int | None = None,
                   action: str = "edit") -> dict[str, Any]:
        """保存 Skill 草稿（先检查 frontmatter 能解析且 name 与标识一致）。"""
        try:
            skill = parse_skill_markdown(markdown)
        except (SkillParseError, ValidationError) as exc:
            raise InvalidResource(str(exc)) from exc
        if skill.id != sid:
            raise InvalidResource(f"frontmatter 中 name={skill.id} 必须与 Skill 标识 {sid} 一致")
        ref = skill_ref(sid)
        change = self.releases.online_change(ref)
        with self.lock:
            self._check_missing_draft_conflict(ref, expected_revision, change)
            meta = self.drafts.write(ref, {SKILL_FILE: markdown}, operator,
                                     base_rev=change["rev"] if change else None,
                                     expected_revision=expected_revision, action=action)
        self._bump_draft_seq()
        return meta

    def validate_skill_working(self, sid: str) -> list[Issue]:
        sk = self.skill_working(sid)
        if sk is None:
            raise ResourceNotFound(f"Skill {sid}")
        return validate_skill(sk, self.overlay())

    # ================================================================ 接口
    def _api_from_draft(self, name: str) -> ApiContract | None:
        text = self.drafts.read_file(api_ref(name), f"{name}.yaml")
        if text is None:
            return None
        try:
            return parse_api_yaml(text)
        except (ValidationError, yaml.YAMLError, ValueError, OSError) as exc:
            raise InvalidResource(f"接口 {name} 草稿无法解析：{exc}") from exc

    def api_online(self, name: str) -> ApiContract | None:
        _, rs = self.live()
        return rs.apis.get(name)

    def api_working(self, name: str) -> ApiContract | None:
        return self._api_from_draft(name) or self.api_online(name)

    def api_yaml(self, name: str, version: str = "working") -> str | None:
        """接口契约 YAML 原文。"""
        version = _check_version(version)
        if version in ("working", "draft", ""):
            text = self.drafts.read_file(api_ref(name), f"{name}.yaml")
            if text is not None or version == "draft":
                return text
            version = "online"
        if version == "online":
            rev = self.releases.live_rev()
            return self.releases.read_file_at(rev, f"apis/{name}.yaml") if rev else None
        return self.releases.read_file_at(version, f"apis/{name}.yaml")

    def save_api(self, name: str, yaml_text: str, operator: str, expected_revision: int | None = None,
                 action: str = "edit") -> dict[str, Any]:
        """保存接口草稿（先检查 YAML 能解析、name 一致、Schema 合法）。"""
        try:
            api = parse_api_yaml(yaml_text)
        except (ValidationError, yaml.YAMLError, ValueError) as exc:
            raise InvalidResource(f"接口 YAML 无法解析：{exc}") from exc
        if api.name != name:
            raise InvalidResource(f"YAML 中 name={api.name} 必须与接口编码 {name} 一致")
        errors = [i.message for i in validate_api(api)]
        if errors:
            raise InvalidResource("；".join(errors))
        ref = api_ref(name)
        change = self.releases.online_change(ref)
        with self.lock:
            self._check_missing_draft_conflict(ref, expected_revision, change)
            meta = self.drafts.write(ref, {f"{name}.yaml": yaml_text}, operator,
                                     base_rev=change["rev"] if change else None,
                                     expected_revision=expected_revision, action=action)
        self._bump_draft_seq()
        return meta

    # ================================================================ 系统提示词
    def system_prompt(self, version: str = "working") -> str:
        version = _check_version(version)
        if version in ("working", "draft", ""):
            text = self.drafts.read_file(SP_REF, SYSTEM_PROMPT_FILE)
            if text is not None:
                return text
            if version == "draft":
                return ""
            version = "online"
        if version == "online":
            _, rs = self.live()
            return rs.system_prompt
        return self.releases.read_file_at(version, SYSTEM_PROMPT_FILE) or ""

    def save_system_prompt(self, text: str, operator: str, expected_revision: int | None = None) -> dict[str, Any]:
        if not text.strip():
            raise InvalidResource("系统提示词不能为空")
        change = self.releases.online_change(SP_REF)
        with self.lock:
            self._check_missing_draft_conflict(SP_REF, expected_revision, change)
            meta = self.drafts.write(SP_REF, {SYSTEM_PROMPT_FILE: text}, operator,
                                     base_rev=change["rev"] if change else None, expected_revision=expected_revision)
        self._bump_draft_seq()
        return meta


def template_from_payload(tid: int, base: Template | None, defn_data: dict[str, Any], body: str | None) -> Template:
    """用管理端提交的数据构造模板（未提供的部分沿用 base）。"""
    data = base.definition.model_dump() if base else {"id": tid, "name": f"模板{tid}"}
    data.update({k: v for k, v in defn_data.items() if v is not None})
    data["id"] = tid
    try:
        defn = TemplateDef.model_validate(data)
    except ValidationError as exc:
        raise InvalidResource(f"模板定义不合法：{exc}") from exc
    return Template(definition=defn, body=body if body is not None else (base.body if base else ""))
