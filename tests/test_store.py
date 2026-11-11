"""文件存储测试：草稿、发布、回退、紧急切换、下线恢复、校验拦截。

#Created By AiCoding(codex)
"""

from __future__ import annotations

from datetime import date
import os
import shutil

import pytest

from report_agent.config import Settings
from report_agent.container import build_container
from report_agent.store.cases import CaseDef, CaseStore
from report_agent.store.drafts import DraftConflict
from report_agent.store.git_repo import GitError
from report_agent.store.layout import InvalidResource, ResourceRef, ensure_within
from report_agent.store.publisher import NothingToPublish, PublishError
from report_agent.store.releases import ReleaseNotFound
from report_agent.store.service import SP_REF, ResourceNotFound, api_ref, skill_ref, template_from_payload, tpl_ref
from scripted_model import scripted_model


def _edit_name(c, name: str):
    tpl = c.service.template_working(1001)
    return c.service.save_template(template_from_payload(1001, tpl, {"name": name}, None), "测试员")


def test_seed_creates_first_release(container):
    c = container
    assert c.releases.live_rev() == "r1"
    assert (c.layout.releases / "r1" / "templates/1001/template.yaml").exists()
    assert os.readlink(c.layout.current) == "r1"
    assert c.repo.head() == c.releases.entry("r1")["commit"]
    assert c.service.state(tpl_ref(1001)).status == "PUBLISHED"


def test_draft_publish_and_rollback(container):
    c = container
    meta = _edit_name(c, "业务办理争议类（新）")
    assert meta["baseRev"] == "r1" and meta["revision"] == 1
    assert c.service.state(tpl_ref(1001)).status == "PUBLISHED_DRAFT"
    assert c.service.template_online(1001).name == "业务办理争议类"   # 线上不受草稿影响

    with pytest.raises(DraftConflict):
        c.service.save_template(c.service.template_working(1001), "别人", expected_revision=0)

    result = c.service.publish_draft(tpl_ref(1001), "测试员", "改名")
    assert result.entry["rev"] == "r2" and result.entry["base"] == "r1"
    assert result.entry["summary"] == "发布 模板 1001（业务办理争议类（新））"
    assert c.service.template_online(1001).name == "业务办理争议类（新）"
    assert not c.drafts.exists(tpl_ref(1001))
    assert c.service.state(tpl_ref(1001)).online_rev == "r2"

    # 回退到 r1：先恢复到草稿，再发布
    c.service.rollback(tpl_ref(1001), "r1", "draft_only", "", "测试员")
    assert c.service.template_working(1001).name == "业务办理争议类"
    assert c.service.template_online(1001).name == "业务办理争议类（新）"
    r = c.service.rollback(tpl_ref(1001), "r1", "publish_now", "改名有误", "测试员")
    assert r["rev"] == "r3" and c.service.template_online(1001).name == "业务办理争议类"
    assert [e["rev"] for e in c.releases.history(tpl_ref(1001))] == ["r3", "r2", "r1"]


def test_nothing_to_publish(container):
    c = container
    c.service.save_template(c.service.template_working(1001), "测试员")
    with pytest.raises(NothingToPublish):
        c.service.publish_draft(tpl_ref(1001), "测试员")
    assert c.releases.live_rev() == "r1"


def test_publish_blocked_by_validation(container):
    c = container
    tpl = c.service.template_working(1001)
    broken = template_from_payload(1001, tpl, {}, tpl.body + "\n{{客户星级}}")
    c.service.save_template(broken, "测试员")
    with pytest.raises(PublishError) as exc:
        c.service.publish_draft(tpl_ref(1001), "测试员")
    assert any(i.code == "BODY_UNDEFINED_FIELD" and i.field == "客户星级" for i in exc.value.issues)
    assert c.releases.live_rev() == "r1"
    assert not list(c.layout.releases.glob(".build-*"))


def test_emergency_switch_then_publish_builds_on_switched(container):
    c = container
    _edit_name(c, "版本二")
    c.service.publish_draft(tpl_ref(1001), "测试员")
    c.service.save_system_prompt("新的系统提示词", "测试员")
    c.service.publish_draft(SP_REF, "测试员")
    assert c.releases.live_rev() == "r3"

    c.publisher.emergency_switch("r1", "值班员", "线上异常")
    assert c.releases.live_rev() == "r1"
    assert c.service.template_online(1001).name == "业务办理争议类"
    assert c.service.state(tpl_ref(1001)).online_rev == "r1"

    # 切换后只改系统提示词并发布：模板仍保持 r1 的内容（不会把 r2 的改名带回来）
    c.service.save_system_prompt("切换后的提示词", "测试员")
    entry = c.service.publish_draft(SP_REF, "测试员").entry
    assert entry["base"] == "r1"
    assert c.service.template_online(1001).name == "业务办理争议类"
    assert c.service.state(tpl_ref(1001)).online_rev == "r1"


def test_offline_and_restore(container):
    c = container
    c.service.offline_template(1001, "测试员", "停用")
    assert c.service.state(tpl_ref(1001)).status == "OFFLINE"
    c.service.restore_template(1001, "测试员")
    assert c.service.state(tpl_ref(1001)).status == "DRAFT"
    c.service.publish_draft(tpl_ref(1001), "测试员")
    assert c.service.state(tpl_ref(1001)).status == "PUBLISHED"
    assert not c.service.template_online(1001).offline


def test_pruned_release_is_restored_from_git(container):
    c = container
    _edit_name(c, "版本二")
    c.service.publish_draft(tpl_ref(1001), "测试员")
    shutil.rmtree(c.layout.releases / "r1")
    c.releases._snapshots.clear()
    assert c.service.template_at(1001, "r1").name == "业务办理争议类"
    c.publisher.emergency_switch("r1", "值班员", "测试恢复")
    assert (c.layout.releases / "r1" / "templates/1001/body.md.j2").exists()


def test_resource_ref_and_layout_traversal_protection(container, tmp_path):
    c = container
    for bad_tid in ("0", "-1", "../1001", "1001/../../etc", "1001a", ""):
        with pytest.raises(InvalidResource):
            tpl_ref(bad_tid)
    for bad_sid in ("", "../secret", "Bad_Upper", "-leading", "a/b", "a\x00b"):
        with pytest.raises(InvalidResource):
            skill_ref(bad_sid)
    for bad_api in ("", "123api", "../query", "api/sub", "bad space"):
        with pytest.raises(InvalidResource):
            api_ref(bad_api)
    with pytest.raises(InvalidResource):
        ResourceRef("system-prompt", "other")
    with pytest.raises(InvalidResource):
        ResourceRef("unknown", "1001")  # type: ignore[arg-type]

    for bad_rev in ("", "r0", "r-1", "../releases", "r1/../../etc", "main"):
        with pytest.raises(InvalidResource):
            c.layout.release_dir(bad_rev)

    base = tmp_path / "base"
    sibling = tmp_path / "base_evil" / "x.txt"
    base.mkdir()
    with pytest.raises(InvalidResource):
        ensure_within(base, sibling)
    with pytest.raises(InvalidResource):
        ensure_within(base, base / ".." / "outside.txt")

    # Git 命令参数注入与路径穿越防护
    with pytest.raises(GitError):
        c.repo.show("--help", "templates/1001/template.yaml")
    with pytest.raises(GitError):
        c.repo.diff_name_status("-n", "HEAD")
    head = c.repo.head()
    assert head is not None
    assert c.repo.show(head, "../secret") is None
    assert c.repo.show(head, "/etc/passwd") is None


def test_case_store_traversal_and_corrupted_yaml_resilience(container):
    c = container
    for bad_tid in (0, -10, True):
        with pytest.raises(InvalidResource):
            c.cases.list(bad_tid)  # type: ignore[arg-type]
    for bad_cid in ("", "../users", "../../config/users", "C-01/evil", "bad space"):
        with pytest.raises(InvalidResource):
            c.cases.get(1001, bad_cid)
        with pytest.raises(InvalidResource):
            c.cases.delete(1001, bad_cid)
        with pytest.raises(InvalidResource):
            c.cases.save(1001, CaseDef(id=bad_cid, name="非法"))

    # 混入损坏的 YAML 与非对象 YAML，不影响正常用例读取与计数
    case_dir = c.layout.cases / "1001"
    (case_dir / "C-bad1.yaml").write_text("::: not valid yaml ::: [", encoding="utf-8")
    (case_dir / "C-bad2.yaml").write_text("- item1\n- item2\n", encoding="utf-8")
    assert c.cases.count(1001) == 1
    assert [x.id for x in c.cases.list(1001)] == ["C-01"]
    assert c.cases.get(1001, "C-bad1") is None

    mapped = CaseStore.from_payload({
        "id": "C-02", "name": "映射测试", "mobile": 13900009999,
        "inputs": {"自定义": None}, "expectedValues": {"争议类型": None, "受理渠道": "手厅"},
    })
    assert mapped.inputs["手机号码"] == "13900009999" and mapped.inputs["自定义"] == ""
    assert mapped.expectedValues == {"争议类型": "", "受理渠道": "手厅"}


def test_draft_atomic_write_and_corruption_resilience(container, monkeypatch):
    c = container
    ref = tpl_ref(1001)
    meta1 = c.drafts.write(ref, {"template.yaml": "id: 1001\nname: 初稿\n", "extra.txt": "old"}, "测试员", "r1")
    assert meta1["revision"] == 1
    assert c.drafts.read_file(ref, "extra.txt") == "old"

    # 二次原子覆盖写入应清理上一次残留的旧文件，且不留临时目录
    meta2 = c.drafts.write(ref, {"template.yaml": "id: 1001\nname: 二稿\n"}, "测试员", "r1", expected_revision=1)
    assert meta2["revision"] == 2
    assert c.drafts.read_file(ref, "extra.txt") is None
    assert not [p for p in (c.layout.drafts / "template").iterdir() if p.name.startswith(".")]

    # 非法草稿文件名拦截，且失败后原草稿保持完整
    with pytest.raises(InvalidResource):
        c.drafts.write(ref, {"../escape.yaml": "x"}, "测试员", "r1")
    with pytest.raises(InvalidResource):
        c.drafts.write(ref, {".meta.json": "{}"}, "测试员", "r1")
    assert c.drafts.read_file(ref, "template.yaml") == "id: 1001\nname: 二稿\n"

    # 模拟切换草稿目录时 os.replace 抛错，验证自动从 .bak 恢复原草稿
    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        if str(src).endswith(".tmp") and str(dst).endswith("/1001"):
            calls["n"] += 1
            raise OSError("simulated replace failure")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        c.drafts.write(ref, {"template.yaml": "id: 1001\nname: 失败稿\n"}, "测试员", "r1")
    monkeypatch.undo()
    assert calls["n"] == 1
    assert c.drafts.read_file(ref, "template.yaml") == "id: 1001\nname: 二稿\n"
    assert c.drafts.meta(ref)["revision"] == 2

    # 损坏的 .meta.json 与遗留临时目录不会拖垮扫描和启动恢复
    bad_dir = c.layout.drafts / "template" / "1002"
    bad_dir.mkdir(parents=True)
    (bad_dir / ".meta.json").write_text("{corrupted", encoding="utf-8")
    stale_tmp = c.layout.drafts / "template" / ".1001.999.abcd.tmp"
    stale_tmp.mkdir(parents=True)
    assert c.drafts.meta(tpl_ref(1002)) is None
    assert c.drafts.list_keys("template") == ["1001"]
    c.releases.recover()
    assert not stale_tmp.exists()


def test_publish_after_emergency_switch_to_git_head_and_rollback_safety(container, monkeypatch):
    c = container
    _edit_name(c, "版本二")
    c.service.publish_draft(tpl_ref(1001), "测试员")
    assert c.releases.live_rev() == "r2"

    # 紧急切回 r1（此时 Git HEAD 仍是 r2 的“版本二”，但线上已经是 r1 的“业务办理争议类”）
    c.publisher.emergency_switch("r1", "值班员", "回退线上")
    assert c.releases.live_rev() == "r1"

    # 重新把模板改成与 r2 相同的“版本二”并发布，不应被误判为 NothingToPublish
    _edit_name(c, "版本二")
    r3 = c.service.publish_draft(tpl_ref(1001), "测试员").entry
    assert r3["rev"] == "r3" and r3["base"] == "r1"
    assert c.service.template_online(1001).name == "版本二"

    # 模拟发布后半段写索引异常：Git HEAD、线上指针、草稿都必须安全回滚
    prev_head = c.repo.head()
    _edit_name(c, "版本四失败演练")

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(c.releases, "add", boom)
    with pytest.raises(OSError, match="disk full"):
        c.service.publish_draft(tpl_ref(1001), "测试员")
    monkeypatch.undo()

    assert c.releases.live_rev() == "r3"
    assert c.repo.head() == prev_head
    assert not c.repo.has_changes()
    assert c.drafts.exists(tpl_ref(1001))
    assert not list(c.layout.releases.glob(".build-*"))


def test_offline_idempotency_and_unseeded_system_prompt(container, tmp_path):
    c = container
    with pytest.raises(ResourceNotFound):
        c.service.offline_template(9999, "测试员", "不存在")
    c.service.offline_template(1001, "测试员", "首次下线")
    with pytest.raises(NothingToPublish):
        c.service.offline_template(1001, "测试员", "重复下线")

    with pytest.raises(InvalidResource):
        c.service.template_version(1001, "../r1")
    with pytest.raises(ReleaseNotFound):
        c.releases.read_file_at("../r1", "system-prompt.md")
    with pytest.raises(InvalidResource):
        c.releases.read_file_at("r1", "../../config/users.yaml")

    # 索引文件混入半行损坏记录时仍能正常解析历史版本
    with c.layout.release_index.open("a", encoding="utf-8") as fh:
        fh.write("{half broken line\n[]\n{\"rev\":\"bad\"}\n")
    c.releases._entries = None
    assert [e["rev"] for e in c.releases.entries()] == ["r1", "r2"]

    # 空库（未 seed）场景下系统提示词单例状态应为 DRAFT 而非 404
    empty_settings = Settings(_env_file=None, data_dir=tmp_path / "empty_data", seed_on_empty=False,
                              gateway_mode="mock", llm_api_key="test", admin_token_secret="test-secret")
    empty_c = build_container(empty_settings, model=scripted_model())
    assert empty_c.service.state(SP_REF).status == "DRAFT"


def test_run_store_bidirectional_recovery_pagination_and_window_stats(container):
    c = container
    today = date.today()
    ds = today.strftime("%Y%m%d")

    r_ok = f"{ds}100000001aaaaaaa"
    r_part = f"{ds}100000002bbbbbbb"
    r_broken_detail = f"{ds}100000003ccccccc"
    r_orphan = f"{ds}100000004ddddddd"
    r_ancient = "19990102090000000eeeeeee"

    c.runs.submit(
        {"runId": r_ok, "startTime": f"{today.isoformat()}T10:00:01+08:00", "templateId": 1001,
         "templateName": "业务办理争议类", "rev": "r1", "entry": "上游调用", "status": "SUCCESS",
         "mobile": "13900000001", "busiName": "套餐变更", "found": 10, "total": 10, "durationMs": 1200,
         "rounds": 4, "skills": ["business-sms-check"], "apiCalls": [{"name": "querySMSSendInfo", "ok": True, "ms": 80}],
         "retries": 0},
        {"runId": r_ok, "status": "SUCCESS", "templateId": 1001, "report": "正常报告",
         "inputs": {"手机号码": "13900000001"}, "foundCount": 10, "totalCount": 10, "durationMs": 1200},
    )
    c.runs.submit(
        {"runId": r_part, "startTime": f"{today.isoformat()}T10:01:01+08:00", "templateId": 1001,
         "templateName": "业务办理争议类", "rev": "r1", "entry": "试运行", "status": "PARTIAL",
         "mobile": "13900000002", "busiName": "宽带新装", "found": 6, "total": 10, "durationMs": 2400,
         "rounds": 6, "skills": ["business-sms-check"], "apiCalls": [{"name": "querySMSSendInfo", "ok": False, "ms": 320}],
         "retries": 1},
        {"runId": r_part, "status": "PARTIAL", "templateId": 1001, "report": "部分报告",
         "inputs": {"手机号码": "13900000002"}, "foundCount": 6, "totalCount": 10, "durationMs": 2400},
    )
    c.runs.submit(
        {"runId": r_broken_detail, "startTime": f"{today.isoformat()}T10:02:01+08:00", "templateId": 1001,
         "templateName": "业务办理争议类", "rev": "r1", "entry": "上游调用", "status": "FAILED",
         "mobile": "13900000003", "busiName": "流量争议", "found": 0, "total": 10, "durationMs": 500,
         "rounds": 1, "skills": [], "apiCalls": [], "retries": 2, "error": "上游超时"},
        {"runId": r_broken_detail, "status": "FAILED"},
    )
    c.runs.submit(
        {"runId": r_ancient, "startTime": "1999-01-02T09:00:00+08:00", "templateId": 1001,
         "templateName": "历史归档", "rev": "r1", "entry": "上游调用", "status": "SUCCESS",
         "found": 5, "total": 5, "durationMs": 800, "rounds": 2},
        {"runId": r_ancient, "status": "SUCCESS", "report": "1999"},
    )

    day_dir = c.layout.runs / f"{today.year:04d}" / f"{today.month:02d}" / f"{today.day:02d}"
    # 1) 损坏 r_broken_detail 的详情 JSON，验证 get() 能从 index.jsonl 降级恢复
    (day_dir / f"{r_broken_detail}.json").write_bytes(b"{corrupted-json-\xff")
    recovered = c.runs.get(r_broken_detail)
    assert recovered is not None and recovered["recoveredFromIndex"] is True
    assert recovered["status"] == "FAILED" and recovered["inputs"]["手机号码"] == "13900000003"
    assert len(recovered["validationRounds"]) == 2

    # 2) 写入一个未登记到 index.jsonl 的孤儿详情文件 + 往 index.jsonl 追加坏行，验证 list() 双向容错
    (day_dir / f"{r_orphan}.json").write_text(
        f'{{"runId": "{r_orphan}", "status": "SUCCESS", "templateId": 1001, "templateName": "孤儿恢复", '
        f'"inputs": {{"手机号码": "13900000004"}}, "foundCount": 8, "totalCount": 8, "durationMs": 1500}}',
        encoding="utf-8",
    )
    with (day_dir / "index.jsonl").open("ab") as fh:
        fh.write(b"\xff\xfe{truncated\n123\n{\"runId\":\"invalid\"}\n")

    today_runs = c.runs.list(today, today, limit=10)
    assert [x["runId"] for x in today_runs] == [r_orphan, r_broken_detail, r_part, r_ok]

    # 3) 超大日期跨度扫描与 offset/limit 分页
    all_runs = c.runs.list(date(1970, 1, 1), date(2099, 12, 31), limit=2, offset=1)
    assert [x["runId"] for x in all_runs] == [r_broken_detail, r_part]
    tail_runs = c.runs.list(date(1970, 1, 1), date(2099, 12, 31), limit=5, offset=4)
    assert [x["runId"] for x in tail_runs] == [r_ancient]

    # 4) 非法 run_id 防护
    assert c.runs.get("../etc/passwd") is None
    with pytest.raises(InvalidResource):
        c.runs.submit({"runId": "../bad"}, {})

    # 5) 窗口统计聚合校验
    win = c.runs.window_stats(days=7, today=today)
    s = win["summary"]
    assert s["total"] == 4 and s["success"] == 2 and s["partial"] == 1 and s["failed"] == 1
    assert s["successRate"] == 50.0 and s["foundFields"] == 24 and s["totalFields"] == 38
    assert s["p95DurationMs"] == 2400 and s["avgDurationMs"] == 1400
    assert len(s["daily"]) == 7 and s["daily"][-1]["total"] == 4
    assert win["skills"]["business-sms-check"] == 2
    assert len(win["apis"]["querySMSSendInfo"]) == 2
