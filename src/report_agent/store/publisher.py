"""发布器：以线上版本为基准，应用一组变更，校验后生成新版本并切换上线。

#Created By AiCoding(codex)
步骤（全程持有进程内写锁）：
  1. 复制线上快照到 releases/.build-rN；
  2. 应用变更（草稿内容、历史版本内容、下线标记）；
  3. 校验：只拦截本次变更新引入的错误，避免历史遗留问题阻塞所有发布；
  4. 把构建结果同步到 repo 工作区并提交 Git；
  5. rename 为 releases/rN，追加索引，原子切换 current；
  6. 删除已发布的草稿，写审计日志。
任何一步失败都会删除构建目录，线上版本不受影响。
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..domain.resources import Issue, ResourceSet, load_resource_dir, validate_all
from ..domain.template import OFFLINE_FILE
from .drafts import DraftStore
from .fsutil import append_audit, atomic_write_text, now_iso, replace_dir_contents, trees_equal
from .git_repo import GitRepo
from .layout import META_FILE, DataLayout, ResourceRef, copy_resource, ensure_within, remove_resource
from .releases import ReleaseStore

log = logging.getLogger(__name__)

ChangeAction = Literal["publish", "rollback", "offline", "delete"]


@dataclass
class Change:
    """一项变更。source=draft 时取草稿内容；source=tree 时从 source_dir 这棵树复制。"""

    ref: ResourceRef
    action: ChangeAction
    title: str = ""
    source: Literal["draft", "tree", "none"] = "draft"
    source_dir: Path | None = None
    offline_marker: dict[str, Any] | None = None


class PublishError(RuntimeError):
    """校验不通过，阻止发布。"""

    def __init__(self, issues: list[Issue]) -> None:
        super().__init__("；".join(i.message for i in issues[:5]))
        self.issues = issues


class NothingToPublish(RuntimeError):
    """变更后的内容与线上完全一致。"""


@dataclass
class PublishResult:
    entry: dict[str, Any]
    warnings: list[Issue] = field(default_factory=list)


def _issue_key(i: Issue) -> tuple:
    return (i.level, i.code, i.kind, i.key, i.field, i.message)


class Publisher:
    """负责生成新版本。"""

    def __init__(self, layout: DataLayout, repo: GitRepo, releases: ReleaseStore, drafts: DraftStore,
                 lock: threading.RLock) -> None:
        self.layout = layout
        self.repo = repo
        self.releases = releases
        self.drafts = drafts
        self.lock = lock

    def publish(self, changes: list[Change], operator: str, type_label: str, summary: str,
                note: str = "") -> PublishResult:
        """应用变更并发布为新版本。任何步骤异常均回滚构建目录与 Git 工作区。"""
        with self.lock:
            base_rev = self.releases.live_rev()
            base_dir = self.releases.ensure_materialized(base_rev) if base_rev else None
            n = self.releases.next_number()
            rev = f"r{n}"
            build = self.layout.releases / f".build-{rev}"
            if build.exists():
                shutil.rmtree(build)
            prev_head = self.repo.head()
            repo_touched = False
            try:
                if base_dir is not None:
                    shutil.copytree(base_dir, build, ignore=shutil.ignore_patterns(".release.json"))
                else:
                    build.mkdir(parents=True)
                for ch in changes:
                    self._apply(ch, build)

                new_rs = load_resource_dir(build)
                base_rs = self.releases.snapshot(base_rev) if base_rev else ResourceSet(system_prompt="-")
                base_keys = {_issue_key(i) for i in validate_all(base_rs)}
                new_issues = validate_all(new_rs)
                changed = {(c.ref.kind, c.ref.key) for c in changes}
                blocking = [i for i in new_issues if i.level == "error" and _issue_key(i) not in base_keys]
                if blocking:
                    raise PublishError(blocking)
                warnings = [i for i in new_issues if i.level == "warning" and (i.kind, i.key) in changed]

                if trees_equal(base_dir, build, ignore={".git", ".release.json", META_FILE}):
                    raise NothingToPublish("内容与线上版本一致，无需发布")

                repo_touched = True
                replace_dir_contents(self.repo.path, build, keep={".git"})
                message = f"{summary}\n\nRelease: {rev}\nBase: {base_rev or '-'}\nOperator: {operator}\n"
                if note:
                    message += f"Note: {note}\n"
                commit = self.repo.commit_all(message, operator)
                entry = {
                    "rev": rev,
                    "n": n,
                    "base": base_rev,
                    "commit": commit,
                    "time": now_iso(),
                    "operator": operator,
                    "type": type_label,
                    "summary": summary,
                    "note": note,
                    "changes": [{"kind": c.ref.kind, "key": c.ref.key, "action": c.action, "title": c.title}
                                for c in changes],
                }
                self.releases.add(entry, build)
            except BaseException:
                shutil.rmtree(build, ignore_errors=True)
                final = self.layout.releases / rev
                if final.exists() and self.releases.live_rev() != rev and not self.releases.has(rev):
                    shutil.rmtree(final, ignore_errors=True)
                if repo_touched and not self.releases.has(rev):
                    try:
                        self.repo.reset_to(prev_head)
                    except Exception:  # noqa: BLE001
                        log.exception("回滚 Git 工作区失败")
                raise

            for ch in changes:
                if ch.source == "draft":
                    self.drafts.delete(ch.ref)
            self.audit("publish", operator, {"rev": rev, "base": base_rev, "summary": summary, "note": note})
            try:
                self.releases.prune()
            except OSError:
                log.exception("清理旧版本目录失败")
            log.info("发布完成 %s（基于 %s）：%s", rev, base_rev, summary)
            return PublishResult(entry=entry, warnings=warnings)

    def _apply(self, ch: Change, build: Path) -> None:
        """把一项变更写入构建目录。"""
        if ch.action == "offline":
            target = ensure_within(build, build / ch.ref.tree_path())
            if not target.exists():
                raise PublishError([Issue("error", "NOT_PUBLISHED", f"{ch.ref.label()} 不在线上，无法下线",
                                          ch.ref.kind, ch.ref.key)])
            atomic_write_text(target / OFFLINE_FILE, json.dumps(ch.offline_marker or {}, ensure_ascii=False))
            return
        if ch.action == "delete":
            remove_resource(build, ch.ref)
            return
        if ch.source == "draft":
            if not self.drafts.exists(ch.ref):
                raise PublishError([Issue("error", "NO_DRAFT", f"{ch.ref.label()} 没有草稿", ch.ref.kind, ch.ref.key)])
            self.drafts.apply_to_tree(ch.ref, build)
        elif ch.source == "tree" and ch.source_dir is not None:
            copy_resource(ch.source_dir, build, ch.ref)

    def emergency_switch(self, rev: str, operator: str, reason: str) -> None:
        """紧急把线上切到某个历史版本，不生成新版本。"""
        with self.lock:
            before = self.releases.live_rev()
            self.releases.switch(rev)
            self.audit("emergency-switch", operator, {"from": before, "to": rev, "reason": reason})
            log.warning("线上版本由 %s 紧急切换到 %s，操作人 %s，原因：%s", before, rev, operator, reason)

    def audit(self, action: str, operator: str, detail: dict[str, Any]) -> None:
        """追加审计日志。"""
        with self.lock:
            append_audit(self.layout.audit, action, operator, detail)
