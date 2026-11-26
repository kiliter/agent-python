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
from ..domain.composite import (
    COMPOSITE_TEMPLATE_FILE,
    COMPOSITE_TEMPLATE_KEY,
    DEFAULT_COMPOSITE_TEMPLATE,
    validate_composite_template,
)
from ..domain.resources import (ROUTER_SKILL_ID, Issue, ResourceSet, SYSTEM_PROMPT_FILE, load_template_dir,
                                validate_api, validate_skill, validate_template)
from ..domain.skill import SKILL_FILE, Skill, SkillParseError, load_skill_dir, parse_skill_markdown
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


class ResourceInUseError(RuntimeError):
    """资源仍被其他资源引用，禁止删除。#Created By AiCoding(codex)"""

    def __init__(self, message: str, references: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.references = references


class ResourceDeleteForbidden(RuntimeError):
    """受保护规则限制的资源禁止删除（例如非 template 作用域的 Skill）。#Created By AiCoding(codex)"""

    def __init__(self, message: str, code: str = "DELETE_FORBIDDEN") -> None:
        super().__init__(message)
        self.code = code


_SKILL_SCOPE_LABELS: dict[str, str] = {
    "template": "按模板绑定",
    "global": "全局填报",
    "chat": "聊天助手专用",
}


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
CT_REF = ResourceRef("composite-template", COMPOSITE_TEMPLATE_KEY)


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
        """递归采集 drafts/ 下活跃草稿文件的轻量 (kind, key, rel_path, mtime_ns, size) 指纹，兼顾嵌套子文档与直接写盘测试。"""
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
                                # #Created By AiCoding(codex) 显式栈递归遍历，感知 Skill 子目录文档的变更
                                stack: list[tuple[str, str]] = [(key_entry.path, "")]
                                while stack:
                                    cur_path, rel_prefix = stack.pop()
                                    try:
                                        with os.scandir(cur_path) as file_it:
                                            for f_entry in file_it:
                                                try:
                                                    rel_name = f"{rel_prefix}/{f_entry.name}" if rel_prefix else f_entry.name
                                                    if f_entry.is_dir(follow_symlinks=False):
                                                        if not f_entry.name.startswith("."):
                                                            stack.append((f_entry.path, rel_name))
                                                        continue
                                                    if not f_entry.is_file(follow_symlinks=False):
                                                        continue
                                                    st = f_entry.stat(follow_symlinks=False)
                                                    entries.append((
                                                        kind_entry.name,
                                                        key_entry.name,
                                                        rel_name,
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
        if ref.kind == "composite-template":
            return (bool(rs.composite_template), False)
        return (bool(rs.system_prompt), False)

    def state(self, ref: ResourceRef, rs: ResourceSet | None = None) -> ResourceState:
        """计算资源状态。"""
        if rs is None:
            _, rs = self.live()
        in_live, offline = self._in_live(ref, rs)
        draft = self.drafts.meta(ref)
        if not in_live and not draft and ref.kind not in ("system-prompt", "composite-template"):
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
        elif kind == "composite-template":
            live_keys = [COMPOSITE_TEMPLATE_KEY]
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

    def _clear_draft_if_same_as_online(
        self,
        ref: ResourceRef,
        operator: str,
        expected_revision: int | None,
        change: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """当保存的内容与当前线上未下线版本完全一致时，校验乐观锁并自动清理冗余草稿，避免出现“显示有草稿却无法发布”的状态矛盾。#Created By AiCoding(codex)"""
        with self.lock:
            self._check_missing_draft_conflict(ref, expected_revision, change)
            current = self.drafts.meta(ref)
            if expected_revision is not None and current and int(current.get("revision", 0)) != expected_revision:
                raise DraftConflict(current)
            if current is not None:
                self.drafts.delete(ref)
                self._bump_draft_seq()
        return {
            "kind": ref.kind,
            "key": ref.key,
            "baseRev": change["rev"] if change else None,
            "revision": None,
            "updatedAt": now_iso(),
            "updatedBy": operator,
            "action": "synced-with-online",
            "cleared": True,
        }

    def publish_draft(self, ref: ResourceRef, operator: str, note: str = "", type_label: str = "发布",
                      summary: str | None = None) -> PublishResult:
        """发布某个资源的草稿。草稿不存在或与线上内容语义相同时拒绝发布。"""
        if not self.drafts.exists(ref) or self._same_as_online(ref):
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
                draft_files = self.drafts.read_dir_files(ref)
                online_sk = self.skill_online(ref.key)
                if draft_files is None or online_sk is None:
                    return False
                draft_md = draft_files.get(SKILL_FILE)
                draft_docs = {k: v for k, v in draft_files.items() if k != SKILL_FILE}
                return bool(draft_md is not None and draft_md == online_sk.markdown and draft_docs == online_sk.docs)
            if ref.kind == "api":
                draft_api, online_api = self._api_from_draft(ref.key), self.api_online(ref.key)
                return bool(draft_api and online_api and draft_api == online_api)
            if ref.kind == "composite-template":
                text = self.drafts.read_file(ref, COMPOSITE_TEMPLATE_FILE)
                online_ct = self.composite_template("online")
                return bool(text is not None and online_ct and text == online_ct)
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
        if ref.kind == "composite-template":
            return "汇总大模板"
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
        if ref.kind == "system-prompt":
            return "系统提示词"
        if ref.kind == "composite-template":
            return "汇总大模板"
        return ref.key

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
        cleared = False
        with self.lock:
            self.drafts.write(ref, files, operator, base_rev=state_online["rev"] if state_online else None,
                              action=action)
            self.drafts.rebase(ref, state_online["rev"] if state_online else None, action=action)
            # #Created By AiCoding(codex) 若恢复的历史版本内容与当前线上未下线版本一致，自动清理冗余草稿，避免“有草稿却无法发布”
            if self._same_as_online(ref):
                self.drafts.delete(ref)
                cleared = True
            self._bump_draft_seq()
        out: dict[str, Any] = {
            "mode": mode,
            "rev": target_rev,
            "targetRev": target_rev,
            "targetOffline": target_offline,
            "cleared": cleared,
        }
        if target_offline:
            out["warning"] = (
                f"注意：目标版本 {target_rev} 中该模板处于已下线归档状态；"
                "恢复到草稿仅载入其模板定义与正文（不含下线标记），核对发布后将作为上线版本生效"
            )
        return out

    def _files_from_tree(self, ref: ResourceRef, tree) -> dict[str, str]:
        """从一棵发布树中递归取出资源文件内容（用于回退恢复到草稿，支持 Skill 子目录文档）。#Created By AiCoding(codex)"""
        path = ensure_within(tree, tree / ref.tree_path())
        if ref.is_dir():
            out: dict[str, str] = {}
            stack: list[tuple[Any, str]] = [(path, "")]
            while stack:
                cur, rel_prefix = stack.pop()
                for p in sorted(cur.iterdir(), key=lambda x: x.name):
                    if p.is_symlink() or p.name in (OFFLINE_FILE, ".meta.json", ".DS_Store"):
                        continue
                    rel_posix = f"{rel_prefix}/{p.name}" if rel_prefix else p.name
                    if p.is_dir():
                        stack.append((p, rel_posix))
                    elif p.is_file():
                        out[rel_posix] = p.read_text(encoding="utf-8")
            return out
        return {self.drafts.single_file_name(ref): path.read_text(encoding="utf-8")}

    @staticmethod
    def _clone_resource_set(rs: ResourceSet) -> ResourceSet:
        """返回浅拷贝，避免外部调用方修改缓存字典或问题列表。"""
        return ResourceSet(
            system_prompt=rs.system_prompt,
            composite_template=rs.composite_template,
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

        rs = ResourceSet(system_prompt=live.system_prompt, composite_template=live.composite_template,
                         templates=dict(live.templates), skills=dict(live.skills), apis=dict(live.apis))
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
        ct = self.drafts.read_file(CT_REF, COMPOSITE_TEMPLATE_FILE)
        if ct is not None:
            rs.composite_template = ct

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
        """保存模板草稿；若与当前线上未下线版本完全一致，自动清理冗余草稿并恢复为已发布状态。"""
        ref = tpl_ref(tpl.id)
        change = self.releases.online_change(ref)
        online = self.template_online(tpl.id)
        if online is not None and not online.offline and tpl.definition == online.definition and tpl.body == online.body:
            return self._clear_draft_if_same_as_online(ref, operator, expected_revision, change)
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

    def delete_template(self, tid: int, operator: str, reason: str = "") -> dict[str, Any]:
        """直接删除模板（不因 template-router 残留引用阻断）：纯草稿直接移除，已发布则发布新版本移除。#Created By AiCoding(codex)"""
        ref = tpl_ref(tid)
        with self.lock:
            online = self.template_online(tid)
            has_draft = self.drafts.exists(ref)
            if online is None and not has_draft:
                raise ResourceNotFound(f"模板 {tid} 不存在")
            title = self.title_of(ref)
            if online is None:
                self.drafts.delete(ref)
                self._bump_draft_seq()
                self.publisher.audit("delete-draft", operator, {
                    "kind": "template",
                    "key": str(tid),
                    "title": title,
                    "reason": reason,
                })
                return {"id": tid, "deleted": True, "rev": None, "warnings": []}
            result = self.publisher.publish(
                [Change(ref, "delete", title=title, source="none")],
                operator,
                "删除",
                f"删除 {self.summary_label(ref, title)}",
                reason,
            )
            self._bump_draft_seq()
            return {
                "id": tid,
                "deleted": True,
                "rev": result.entry["rev"],
                "warnings": [i.to_dict() for i in result.warnings],
            }

    # ================================================================ Skill
    def _skill_from_draft(self, sid: str) -> Skill | None:
        ref = skill_ref(sid)
        if not self.drafts.exists(ref):
            return None
        draft_dir = self.layout.draft_dir(ref)
        if not (draft_dir / SKILL_FILE).exists():
            return None
        try:
            return load_skill_dir(draft_dir)
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

    def skill_docs(self, sid: str, version: str = "working") -> dict[str, str] | None:
        """读取指定版本的 Skill 子文档映射表（相对 POSIX 路径 -> 原文）。#Created By AiCoding(codex)"""
        version = _check_version(version)
        ref = skill_ref(sid)
        if version in ("working", "draft", ""):
            files = self.drafts.read_dir_files(ref)
            if files is not None:
                return {k: v for k, v in files.items() if k != SKILL_FILE}
            if version == "draft":
                return None
            version = "online"
        if version == "online":
            sk = self.skill_online(sid)
            return dict(sk.docs) if sk else None
        if self.releases.read_file_at(version, f"skills/{sid}/{SKILL_FILE}") is None:
            return None
        snap = self.releases.snapshot(version)
        sk = snap.skills.get(sid)
        if sk is not None:
            return dict(sk.docs)
        # 历史快照中若主文件损坏未进 skills，回退直接扫描物化目录
        tree = self.releases.ensure_materialized(version)
        files = self._files_from_tree(ref, tree)
        return {k: v for k, v in files.items() if k != SKILL_FILE}

    def save_skill(
        self,
        sid: str,
        markdown: str,
        operator: str,
        expected_revision: int | None = None,
        action: str = "edit",
        docs: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """保存 Skill 草稿（校验 frontmatter、name 一致及全部子文档路径与大小）。#Created By AiCoding(codex)"""
        ref = skill_ref(sid)
        if docs is None:
            # 向后兼容：仅提交 SKILL.md 的旧调用方不误删已有的子目录文档
            try:
                effective_docs = self.skill_docs(sid, "working") or {}
            except (InvalidResource, ValueError):
                effective_docs = {}
        else:
            effective_docs = docs
        try:
            skill = parse_skill_markdown(markdown, docs=effective_docs)
        except (SkillParseError, ValidationError) as exc:
            raise InvalidResource(str(exc)) from exc
        if skill.id != sid:
            raise InvalidResource(f"frontmatter 中 name={skill.id} 必须与 Skill 标识 {sid} 一致")
        change = self.releases.online_change(ref)
        online_sk = self.skill_online(sid)
        if online_sk is not None and markdown == online_sk.markdown and skill.docs == online_sk.docs:
            return self._clear_draft_if_same_as_online(ref, operator, expected_revision, change)
        files = {SKILL_FILE: markdown, **skill.docs}
        with self.lock:
            self._check_missing_draft_conflict(ref, expected_revision, change)
            meta = self.drafts.write(ref, files, operator,
                                     base_rev=change["rev"] if change else None,
                                     expected_revision=expected_revision, action=action)
        self._bump_draft_seq()
        return meta

    def validate_skill_working(self, sid: str) -> list[Issue]:
        sk = self.skill_working(sid)
        if sk is None:
            raise ResourceNotFound(f"Skill {sid}")
        return validate_skill(sk, self.overlay())

    def skill_template_references(self, sid: str) -> list[dict[str, Any]]:
        """查找所有（线上 + 草稿）关联了指定 Skill 的模板清单。#Created By AiCoding(codex)"""
        _, live = self.live()
        refs_by_id: dict[int, dict[str, Any]] = {}
        for tid, tpl in sorted(live.templates.items()):
            if sid in tpl.definition.skills:
                refs_by_id[tid] = {
                    "kind": "template",
                    "key": str(tid),
                    "id": tid,
                    "name": tpl.name,
                    "label": f"{tid} {tpl.name}",
                    "scope": "online",
                    "offline": bool(tpl.offline),
                }
        for key in self.drafts.list_keys("template"):
            if not key.isdigit():
                continue
            tid = int(key)
            try:
                draft_tpl = self._template_from_draft(tid)
            except (InvalidResource, ValueError):
                continue
            if draft_tpl is None or sid not in draft_tpl.definition.skills:
                continue
            if tid in refs_by_id:
                refs_by_id[tid]["scope"] = "both"
                refs_by_id[tid]["name"] = draft_tpl.name
                refs_by_id[tid]["label"] = f"{tid} {draft_tpl.name}"
            else:
                refs_by_id[tid] = {
                    "kind": "template",
                    "key": str(tid),
                    "id": tid,
                    "name": draft_tpl.name,
                    "label": f"{tid} {draft_tpl.name}",
                    "scope": "draft",
                    "offline": False,
                }
        return [refs_by_id[tid] for tid in sorted(refs_by_id)]

    def delete_skill(self, sid: str, operator: str, reason: str = "") -> dict[str, Any]:
        """删除技能：仅允许删除绑定模板（scope=template）且未被任何模板关联的技能。#Created By AiCoding(codex)"""
        ref = skill_ref(sid)
        with self.lock:
            online = self.skill_online(sid)
            has_draft = self.drafts.exists(ref)
            if online is None and not has_draft:
                raise ResourceNotFound(f"Skill {sid} 不存在")
            draft_sk: Skill | None = None
            if has_draft:
                try:
                    draft_sk = self._skill_from_draft(sid)
                except (InvalidResource, ValueError):
                    draft_sk = None
            title = (draft_sk.title if draft_sk else None) or (online.title if online else None) or sid
            # 规则 4：只允许删除绑定模板（scope == "template"）的技能；线上或草稿任一为 global/chat 均禁止删除
            for candidate in (online, draft_sk):
                if candidate is not None and candidate.scope != "template":
                    scope_cn = _SKILL_SCOPE_LABELS.get(candidate.scope, candidate.scope)
                    raise ResourceDeleteForbidden(
                        f"技能「{title}」（{sid}）作用域为「{scope_cn}」，仅允许删除绑定模板的技能",
                        code="SKILL_DELETE_FORBIDDEN",
                    )
            if sid == ROUTER_SKILL_ID:
                raise ResourceDeleteForbidden(
                    f"内置路由技能「{title}」（{sid}）不允许删除",
                    code="SKILL_DELETE_FORBIDDEN",
                )
            # 规则 2：技能删除前必须没有任何模板关联
            refs = self.skill_template_references(sid)
            if refs:
                preview = "、".join(r["label"] for r in refs[:5])
                more = f" 等 {len(refs)} 个模板" if len(refs) > 5 else ""
                raise ResourceInUseError(
                    f"技能「{title}」（{sid}）仍被模板（{preview}{more}）关联，请先在模板中解除关联后再删除",
                    references=refs,
                )
            if online is None:
                self.drafts.delete(ref)
                self._bump_draft_seq()
                self.publisher.audit("delete-draft", operator, {
                    "kind": "skill",
                    "key": sid,
                    "title": title,
                    "reason": reason,
                })
                return {"id": sid, "deleted": True, "rev": None}
            result = self.publisher.publish(
                [Change(ref, "delete", title=title, source="none")],
                operator,
                "删除",
                f"删除 {self.summary_label(ref, title)}",
                reason,
            )
            self._bump_draft_seq()
            return {"id": sid, "deleted": True, "rev": result.entry["rev"]}

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
        online_api = self.api_online(name)
        if online_api is not None and api == online_api:
            return self._clear_draft_if_same_as_online(ref, operator, expected_revision, change)
        with self.lock:
            self._check_missing_draft_conflict(ref, expected_revision, change)
            meta = self.drafts.write(ref, {f"{name}.yaml": yaml_text}, operator,
                                     base_rev=change["rev"] if change else None,
                                     expected_revision=expected_revision, action=action)
        self._bump_draft_seq()
        return meta

    def api_skill_references(self, name: str) -> list[dict[str, Any]]:
        """查找所有（线上 + 草稿，涵盖 template/global/chat 全部作用域）关联了指定 API 的技能清单。#Created By AiCoding(codex)"""
        _, live = self.live()
        refs_by_id: dict[str, dict[str, Any]] = {}
        for sid, sk in sorted(live.skills.items()):
            if name in sk.meta.apis:
                refs_by_id[sid] = {
                    "kind": "skill",
                    "key": sid,
                    "id": sid,
                    "name": sk.title,
                    "label": f"{sk.title}（{sid}）",
                    "skillScope": sk.scope,
                    "scope": "online",
                }
        for sid in self.drafts.list_keys("skill"):
            try:
                draft_sk = self._skill_from_draft(sid)
            except (InvalidResource, ValueError):
                continue
            if draft_sk is None or name not in draft_sk.meta.apis:
                continue
            if sid in refs_by_id:
                refs_by_id[sid]["scope"] = "both"
                refs_by_id[sid]["name"] = draft_sk.title
                refs_by_id[sid]["label"] = f"{draft_sk.title}（{sid}）"
                refs_by_id[sid]["skillScope"] = draft_sk.scope
            else:
                refs_by_id[sid] = {
                    "kind": "skill",
                    "key": sid,
                    "id": sid,
                    "name": draft_sk.title,
                    "label": f"{draft_sk.title}（{sid}）",
                    "skillScope": draft_sk.scope,
                    "scope": "draft",
                }
        return [refs_by_id[sid] for sid in sorted(refs_by_id)]

    def delete_api(self, name: str, operator: str, reason: str = "") -> dict[str, Any]:
        """删除 API：要求没有任何技能（含全局技能与聊天技能）关联该接口。#Created By AiCoding(codex)"""
        ref = api_ref(name)
        with self.lock:
            online = self.api_online(name)
            has_draft = self.drafts.exists(ref)
            if online is None and not has_draft:
                raise ResourceNotFound(f"接口 {name} 不存在")
            title = self.title_of(ref)
            # 规则 3 & 5：API 删除必须没有任何技能关联（挂在 global 技能下的基础 API 天然被锁住）
            refs = self.api_skill_references(name)
            if refs:
                preview = "、".join(r["label"] for r in refs[:5])
                more = f" 等 {len(refs)} 个技能" if len(refs) > 5 else ""
                raise ResourceInUseError(
                    f"接口「{title}」（{name}）仍被技能（{preview}{more}）关联，请先解除技能关联后再删除",
                    references=refs,
                )
            if online is None:
                self.drafts.delete(ref)
                self._bump_draft_seq()
                self.publisher.audit("delete-draft", operator, {
                    "kind": "api",
                    "key": name,
                    "title": title,
                    "reason": reason,
                })
                return {"name": name, "deleted": True, "rev": None}
            result = self.publisher.publish(
                [Change(ref, "delete", title=title, source="none")],
                operator,
                "删除",
                f"删除 {self.summary_label(ref, title)}",
                reason,
            )
            self._bump_draft_seq()
            return {"name": name, "deleted": True, "rev": result.entry["rev"]}

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
        online_text = self.system_prompt("online")
        if online_text and text == online_text:
            return self._clear_draft_if_same_as_online(SP_REF, operator, expected_revision, change)
        with self.lock:
            self._check_missing_draft_conflict(SP_REF, expected_revision, change)
            meta = self.drafts.write(SP_REF, {SYSTEM_PROMPT_FILE: text}, operator,
                                     base_rev=change["rev"] if change else None, expected_revision=expected_revision)
        self._bump_draft_seq()
        return meta

    # ================================================================ 汇总大模板（复合工单）
    def composite_template(self, version: str = "working", *, fallback_default: bool = False) -> str:
        """读取汇总大模板（working / draft / online / rN）；线上尚未发布过时可按需回退内置默认模板。#Created By AiCoding(codex)"""
        version = _check_version(version)
        if version in ("working", "draft", ""):
            text = self.drafts.read_file(CT_REF, COMPOSITE_TEMPLATE_FILE)
            if text is not None:
                return text
            if version == "draft":
                return ""
            version = "online"
        if version == "online":
            _, rs = self.live()
            if rs.composite_template:
                return rs.composite_template
            return DEFAULT_COMPOSITE_TEMPLATE if fallback_default else ""
        return self.releases.read_file_at(version, COMPOSITE_TEMPLATE_FILE) or ""

    def save_composite_template(
        self, text: str, operator: str, expected_revision: int | None = None
    ) -> dict[str, Any]:
        """保存汇总大模板草稿（先校验 Jinja2 语法与样例渲染；若与线上一致则自动清理冗余草稿）。#Created By AiCoding(codex)"""
        errs = validate_composite_template(text)
        if errs:
            raise InvalidResource("；".join(errs))
        change = self.releases.online_change(CT_REF)
        online_text = self.composite_template("online")
        if online_text and text == online_text:
            return self._clear_draft_if_same_as_online(CT_REF, operator, expected_revision, change)
        with self.lock:
            self._check_missing_draft_conflict(CT_REF, expected_revision, change)
            meta = self.drafts.write(
                CT_REF,
                {COMPOSITE_TEMPLATE_FILE: text},
                operator,
                base_rev=change["rev"] if change else None,
                expected_revision=expected_revision,
            )
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
