"""Batch 4 专项回归测试：鉴权防冲刷与并发限流、细粒度草稿乐观锁与预览对齐、存储读路径热缓存优化。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import asyncio
from datetime import date
import json
from pathlib import Path
import time

from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest

from report_agent.api import routes_system
from report_agent.api.auth import (
    LoginGuard,
    TokenService,
    User,
    UserStore,
    verify_password as raw_verify_password,
)
from report_agent.main import create_app
from report_agent.store.cases import CaseDef
from report_agent.store.layout import DataLayout
from report_agent.store.releases import ReleaseStore
from report_agent.store.runs import RunStore
from report_agent.store.service import template_from_payload, tpl_ref


@pytest.fixture
def client(container):
    """创建带测试管理员账号的同步 TestClient。"""
    UserStore(container.layout.config / "users.yaml").upsert(
        "chenxiaoyun", "pass-1234", "陈晓芸", "业务维护"
    )
    app = create_app(container=container)
    with TestClient(app) as cl:
        yield cl


def _login(client: TestClient) -> dict[str, str]:
    r = client.post(
        "/api/v1/auth/login",
        json={"username": "chenxiaoyun", "password": "pass-1234"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ======================================================================== A. 鉴权防冲刷与登录并发保护


def test_login_guard_anti_eviction_and_ip_limit():
    """海量随机未知用户名失败请求（含单次与满阈值锁定冲刷）绝不能驱逐真实账号锁定态，且支持 IP 维度限流。"""
    guard = LoginGuard(
        max_failures=5,
        lock_s=300,
        max_entries=64,
        ip_max_failures=8,
        max_ip_entries=64,
    )

    # 1. 锁定真实账号 admin，并让真实账号 operator 累积 3 次失败
    for _ in range(5):
        guard.fail("admin", known_user=True, client_ip="10.10.0.1")
    for _ in range(3):
        guard.fail("operator", known_user=True, client_ip="10.10.0.2")

    with pytest.raises(HTTPException) as exc:
        guard.check("admin")
    assert exc.value.status_code == 429

    # 2. 伪造 3000 个单次随机未知账号 + 200 个打满 5 次锁定的随机未知账号进行冲刷
    for i in range(3000):
        guard.fail(f"ghost_once_{i}", known_user=False, client_ip=f"192.168.{i // 250}.{i % 250}")
    for i in range(200):
        for _ in range(5):
            guard.fail(f"ghost_locked_{i}", known_user=False, client_ip=f"172.16.{i // 250}.{i % 250}")

    # 容量受控，且真实账号 admin 锁定记录与 operator 失败计数完好无损
    assert len(guard._fails) <= 64
    with pytest.raises(HTTPException) as exc2:
        guard.check("admin")
    assert exc2.value.status_code == 429

    # operator 只需再错 2 次即触发锁定（证明之前的 3 次计数未被未知账号冲掉）
    guard.fail("operator", known_user=True)
    guard.check("operator")  # 第 4 次尚未锁定
    guard.fail("operator", known_user=True)  # 第 5 次锁定
    with pytest.raises(HTTPException):
        guard.check("operator")

    # 3. 同一来源 IP 连续爆破不同随机未知账号达到 ip_max_failures 后按 IP 拦截
    attacker_ip = "203.0.113.99"
    for i in range(8):
        guard.fail(f"enum_user_{i}", known_user=False, client_ip=attacker_ip)
    with pytest.raises(HTTPException) as ip_exc:
        guard.check("brand_new_target", client_ip=attacker_ip)
    assert ip_exc.value.status_code == 429
    # 正常其它 IP 不受影响
    guard.check("brand_new_target", client_ip="203.0.113.100")

    # 登录成功后清理账号与该 IP 的失败计数
    guard.success("admin", client_ip=attacker_ip)
    guard.check("admin", client_ip=attacker_ip)


def test_token_service_revoked_capacity_and_expiry():
    """TokenService._revoked 具备容量上限与过期清理兜底，高频登出不会无限膨胀。"""
    svc = TokenService(b"unit-test-hmac-secret-key", ttl_s=3600, max_revoked=64)

    tokens = [svc.issue(User(f"user_{i}", "测试员", "平台管理")) for i in range(120)]
    for tok in tokens:
        verified = svc.verify(tok)
        assert verified is not None
        svc.revoke(verified[1])
        assert len(svc._revoked) <= 64

    # 最近吊销的 64 个令牌均不可再通过校验
    for tok in tokens[-64:]:
        assert svc.verify(tok) is None

    # 模拟已过期的吊销记录在下次 revoke 时被自动清理
    for nonce in list(svc._revoked.keys())[:20]:
        svc._revoked[nonce] = time.time() - 10
    fresh = svc.issue(User("active_user", "活跃用户", "业务维护"))
    verified_fresh = svc.verify(fresh)
    assert verified_fresh is not None
    svc.revoke(verified_fresh[1])
    assert len(svc._revoked) <= 45


@pytest.mark.anyio
async def test_login_endpoint_async_semaphore_and_known_user_protection(container, monkeypatch):
    """登录接口异步卸载 PBKDF2 且受 _LOGIN_SEM 并发信号量保护，不阻塞其它轻量接口。"""
    UserStore(container.layout.config / "users.yaml").upsert(
        "chenxiaoyun", "pass-1234", "陈晓芸", "业务维护"
    )
    app = create_app(container=container)

    active = 0
    max_active = 0

    def slow_verify(password: str, stored: str) -> bool:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        try:
            time.sleep(0.04)
            return raw_verify_password(password, stored)
        finally:
            active -= 1

    monkeypatch.setattr(routes_system, "verify_password", slow_verify)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resps = await asyncio.gather(
                *[
                    ac.post(
                        "/api/v1/auth/login",
                        json={"username": "chenxiaoyun", "password": "pass-1234"},
                        headers={"X-Forwarded-For": f"10.0.1.{i + 1}"},
                    )
                    for i in range(10)
                ]
            )
    assert all(r.status_code == 200 for r in resps)
    # 信号量上限为 4：并发度大于 1（真线程池并行）且严格不超过 4
    assert 1 < max_active <= 4


# ======================================================================== B. 细粒度草稿乐观锁、列表证据拦截与实时预览


def test_fine_grained_draft_optimistic_locking(client: TestClient):
    """细粒度草稿修改接口（save_field / reorder_fields / batch_evidence / update_skills / delete_field）均支持乐观锁并返回最新 revision。"""
    h = _login(client)

    # 初始线上态尚无草稿，revision=None；首次细粒度新增字段生成 revision=1
    r1 = client.put(
        "/api/v1/templates/1001/fields/临时核查项",
        headers=h,
        json={
            "name": "临时核查项",
            "visible": True,
            "type": "文本",
            "evidenceType": "quote",
            "whenMissing": "置空",
            "description": "测试细粒度乐观锁",
            "revision": None,
        },
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["revision"] == 1 and r1.json()["draft"]["revision"] == 1

    # 传入过期 revision=0 触发 409 冲突（save_field）
    conflict = client.put(
        "/api/v1/templates/1001/fields/临时核查项",
        headers=h,
        json={
            "name": "临时核查项",
            "visible": True,
            "type": "文本",
            "evidenceType": "derive",
            "whenMissing": "置空",
            "description": "过期版本修改",
            "revision": 0,
        },
    )
    assert conflict.status_code == 409 and conflict.json()["code"] == "DRAFT_CONFLICT"
    assert conflict.json()["current"]["revision"] == 1

    # batch_evidence：旧 revision 409，正确 revision=1 升至 2，未传 revision 向后兼容升至 3
    assert (
        client.post(
            "/api/v1/templates/1001/fields/batch-evidence",
            headers=h,
            json={"fieldNames": ["临时核查项"], "evidenceType": "derive", "revision": 0},
        ).status_code
        == 409
    )
    r2 = client.post(
        "/api/v1/templates/1001/fields/batch-evidence",
        headers=h,
        json={"fieldNames": ["临时核查项"], "evidenceType": "derive", "revision": 1},
    )
    assert r2.status_code == 200 and r2.json()["revision"] == 2
    r3 = client.post(
        "/api/v1/templates/1001/fields/batch-evidence",
        headers=h,
        json={"fieldNames": ["临时核查项"], "evidenceType": "quote"},
    )
    assert r3.status_code == 200 and r3.json()["revision"] == 3

    # reorder_fields：旧 revision 409，正确 revision=3 升至 4
    fields = client.get("/api/v1/templates/1001/fields", headers=h).json()
    names = [f["name"] for f in fields]
    reordered = [names[-1], *names[:-1]]
    assert (
        client.put(
            "/api/v1/templates/1001/fields-order",
            headers=h,
            json={"names": reordered, "revision": 1},
        ).status_code
        == 409
    )
    r4 = client.put(
        "/api/v1/templates/1001/fields-order",
        headers=h,
        json={"names": reordered, "revision": 3},
    )
    assert r4.status_code == 200 and r4.json()["revision"] == 4

    # update_skills：旧 revision 409，正确 revision=4 升至 5
    assert (
        client.put(
            "/api/v1/templates/1001/skills",
            headers=h,
            json={"skills": ["document-match"], "revision": 2},
        ).status_code
        == 409
    )
    r5 = client.put(
        "/api/v1/templates/1001/skills",
        headers=h,
        json={"skills": ["办理短信核查", "document-match"], "revision": 4},
    )
    assert r5.status_code == 200 and r5.json()["revision"] == 5

    # delete_field：旧 revision 409（支持 query 与 body），正确 revision=5 升至 6
    assert (
        client.delete("/api/v1/templates/1001/fields/临时核查项?revision=4", headers=h).status_code
        == 409
    )
    r6 = client.request(
        "DELETE",
        "/api/v1/templates/1001/fields/临时核查项",
        headers=h,
        json={"revision": 5},
    )
    assert r6.status_code == 200 and r6.json()["revision"] == 6

    # 放弃草稿后，客户端仍携带旧草稿 revision=6 发起修改应返回 409 NO_DRAFT，防止静默覆盖
    client.post("/api/v1/templates/1001/discard-draft", headers=h)
    stale_after_discard = client.put(
        "/api/v1/templates/1001/skills",
        headers=h,
        json={"skills": ["document-match"], "revision": 6},
    )
    assert stale_after_discard.status_code == 409
    assert stale_after_discard.json()["current"]["status"] == "NO_DRAFT"


def test_reject_list_field_input_evidence(client: TestClient):
    """列表字段（type=list）在单字段保存与批量改证据接口中均禁止将 evidence 设为 input。"""
    h = _login(client)

    # 1. 直接保存 evidenceType=input 的列表字段 -> 400 拦截
    bad_create = client.put(
        "/api/v1/templates/1001/fields/退费明细列表",
        headers=h,
        json={
            "name": "退费明细列表",
            "visible": True,
            "type": "列表",
            "columns": [{"name": "账期", "type": "文本", "enumValues": [], "description": "月份"}],
            "evidenceType": "input",
            "whenMissing": "置空",
            "description": "退费列表",
        },
    )
    assert bad_create.status_code == 400
    assert bad_create.json()["code"] == "INVALID_FIELD_EVIDENCE"

    # 2. 先合法创建 quote 列表字段，再尝试通过 batch-evidence 批量改为 input -> 400 拦截且原值不变
    ok_create = client.put(
        "/api/v1/templates/1001/fields/退费明细列表",
        headers=h,
        json={
            "name": "退费明细列表",
            "visible": True,
            "type": "列表",
            "columns": [{"name": "账期", "type": "文本", "enumValues": [], "description": "月份"}],
            "evidenceType": "quote",
            "whenMissing": "置空",
            "description": "退费列表",
        },
    )
    assert ok_create.status_code == 200, ok_create.text

    bad_batch = client.post(
        "/api/v1/templates/1001/fields/batch-evidence",
        headers=h,
        json={"fieldNames": ["退费明细列表"], "evidenceType": "input"},
    )
    assert bad_batch.status_code == 400
    assert bad_batch.json()["code"] == "INVALID_FIELD_EVIDENCE"

    saved_field = next(
        f for f in client.get("/api/v1/templates/1001/fields", headers=h).json() if f["name"] == "退费明细列表"
    )
    assert saved_field["evidenceType"] == "quote"


def test_render_preview_in_memory_fields(client: TestClient):
    """render-preview 传入未保存的内存 fields（含 whenMissing/defaultValue/列表列定义）时立即生效且不污染磁盘草稿。"""
    h = _login(client)
    detail = client.get("/api/v1/templates/1001", headers=h).json()

    # 构造未落盘的字段变更：修改已有字段默认值 + 新增一个未保存列表字段
    mem_fields = []
    for f in detail["fields"]:
        if f["name"] == "二次确认短信":
            f = {**f, "whenMissing": "默认值", "defaultValue": "【内存实时预览默认短信】"}
        mem_fields.append(f)
    mem_fields.append(
        {
            "name": "未保存套餐清单",
            "visible": True,
            "type": "列表",
            "columns": [
                {"name": "名称", "type": "文本", "enumValues": [], "description": ""},
                {"name": "资费", "type": "文本", "enumValues": [], "description": ""},
            ],
            "evidenceType": "quote",
            "whenMissing": "置空",
            "defaultValue": "",
            "description": "内存预览测试",
        }
    )

    body_text = (
        "短信结论：{{二次确认短信}}\n"
        "{% for item in 未保存套餐清单 %}{{item.名称}}:{{item.资费}};{% endfor %}"
    )
    resp = client.post(
        "/api/v1/templates/1001/render-preview",
        headers=h,
        json={
            "bodyText": body_text,
            "fields": mem_fields,
            "values": {
                "未保存套餐清单": json.dumps(
                    [{"名称": "5G畅享包", "资费": "30元"}], ensure_ascii=False
                )
            },
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["error"] is None
    assert "【内存实时预览默认短信】" in data["text"]
    assert "5G畅享包:30元;" in data["text"]
    assert data["undefinedFields"] == []

    # 确认磁盘工作区并未被写入草稿
    assert client.get("/api/v1/templates/1001", headers=h).json()["draft"] is None


# ======================================================================== C. 存储读路径与热快照性能优化


def test_release_store_try_live_snapshot(container):
    """ReleaseStore.try_live_snapshot 命中内存缓存时直接同步返回，未预热或切换至未缓存版本时返回 None。"""
    fresh_store = ReleaseStore(container.layout, container.repo, container.releases.lock)
    assert fresh_store.try_live_snapshot() is None

    rev, rs = fresh_store.live_snapshot()
    assert rev == "r1"
    fast = fresh_store.try_live_snapshot()
    assert fast is not None
    assert fast[0] == "r1" and fast[1] is rs

    # 发布新版本 r2 后，fresh_store 尚未加载 r2 快照 -> try_live_snapshot 返回 None，回退加载后再次命中
    tpl = container.service.template_working(1001)
    container.service.save_template(
        template_from_payload(1001, tpl, {"name": "快照缓存测试"}, None), "测试员"
    )
    container.service.publish_draft(tpl_ref(1001), "测试员")

    assert fresh_store.try_live_snapshot() is None
    rev2, rs2 = fresh_store.live_snapshot()
    assert rev2 == "r2"
    assert fresh_store.try_live_snapshot() == ("r2", rs2)


def test_case_store_fast_count(container, monkeypatch):
    """CaseStore.count 仅扫描目录元数据与轻量头部，不调用 _load_file 全量反序列化，且精准排除坏文件与隐藏文件。"""
    cases = container.cases
    for tid in range(100, 133):
        for idx in range(1, 6):
            cases.save(tid, CaseDef(id=f"C-{idx:02d}", name=f"用例{idx}", inputs={"手机号": "13800138000"}))

    # 混入隐藏文件、非法命名文件、语法损坏文件、非字典列表 YAML 文件
    t100_dir = container.layout.cases / "100"
    (t100_dir / ".hidden.yaml").write_text("id: C-99\nname: 隐藏\n", encoding="utf-8")
    (t100_dir / "bad name!.yaml").write_text("id: C-98\nname: 非法名\n", encoding="utf-8")
    (t100_dir / "C-corrupt.yaml").write_text(":::invalid_yaml", encoding="utf-8")
    (t100_dir / "C-list.yaml").write_text("- item1\n- item2\n", encoding="utf-8")

    # 禁止 count() 走 _load_file 全量读取
    def forbid_load_file(*_args, **_kwargs):
        raise AssertionError("CaseStore.count() 不应调用 _load_file 全量解析 YAML！")

    monkeypatch.setattr(cases, "_load_file", forbid_load_file)

    t0 = time.perf_counter()
    counts = [cases.count(tid) for tid in range(100, 133)]
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert all(c == 5 for c in counts)
    assert elapsed_ms < 50.0


def test_overlay_cache_and_offline_rollback_warning(container, client: TestClient, monkeypatch):
    """ResourceService.overlay 命中缓存免磁盘重读，任意草稿变更/直写立即失效；回退下线历史版本至草稿返回明确告警。"""
    svc = container.service
    tpl = svc.template_working(1001)
    svc.save_template(template_from_payload(1001, tpl, {"name": "草稿V1"}, None), "测试员")

    # 首次构建 overlay 缓存
    rs1 = svc.overlay()
    assert rs1.templates[1001].name == "草稿V1"

    read_calls = 0
    orig_loader = svc._template_from_draft

    def tracked_loader(tid: int):
        nonlocal read_calls
        read_calls += 1
        return orig_loader(tid)

    monkeypatch.setattr(svc, "_template_from_draft", tracked_loader)

    # 连续读取 overlay 命中内存缓存，0 次磁盘重读，且返回隔离浅拷贝
    rs2 = svc.overlay()
    assert read_calls == 0
    assert rs2.templates[1001].name == "草稿V1"
    assert rs2 is not rs1 and rs2.templates is not rs1.templates

    # 即使绕过 service 直接通过 drafts.write 修改草稿文件，目录指纹变化也会自动失效缓存
    raw_yaml = container.drafts.read_file(tpl_ref(1001), "template.yaml")
    raw_body = container.drafts.read_file(tpl_ref(1001), "body.md.j2")
    assert raw_yaml is not None and raw_body is not None
    container.drafts.write(
        tpl_ref(1001),
        {"template.yaml": raw_yaml.replace("草稿V1", "直写草稿V2"), "body.md.j2": raw_body},
        operator="直写测试",
        base_rev="r1",
    )
    rs3 = svc.overlay()
    assert read_calls == 1
    assert rs3.templates[1001].name == "直写草稿V2"

    # 测试历史下线版本（r2 含 .offline）通过 API 执行 draft_only 回退时的明确提示
    svc.discard(tpl_ref(1001))
    off_res = svc.offline_template(1001, "测试员", "临时停用")
    offline_rev = off_res.entry["rev"]  # r2（带 .offline）
    svc.restore_template(1001, "测试员")
    svc.publish_draft(tpl_ref(1001), "测试员", "重新上线")  # r3

    h = _login(client)
    rb = client.post(
        "/api/v1/templates/1001/rollback",
        headers=h,
        json={"targetRev": offline_rev, "mode": "draft_only", "reason": "核查历史下线快照"},
    )
    assert rb.status_code == 200, rb.text
    rb_data = rb.json()
    assert rb_data["targetOffline"] is True
    assert "已下线" in rb_data["warning"]
    assert container.drafts.read_file(tpl_ref(1001), ".offline") is None


@pytest.mark.anyio
async def test_run_store_startup_orphan_recovery_and_fast_pagination(tmp_path: Path, monkeypatch):
    """RunStore.start() 启动阶段一次性恢复孤儿详情文件，日常分页按 mtime/size 走内存缓存，零 glob 扫描。"""
    layout = DataLayout(tmp_path / "data")
    today = date.today()
    day_prefix = today.strftime("%Y%m%d")
    ddir = layout.runs / f"{today.year:04d}" / f"{today.month:02d}" / f"{today.day:02d}"
    ddir.mkdir(parents=True, exist_ok=True)

    # 1. 构造 1 条孤儿详情 JSON（未写入 index.jsonl）+ 2500 条索引流水
    orphan_id = f"{day_prefix}080000000orphan1"
    orphan_detail = {
        "runId": orphan_id,
        "templateId": 1001,
        "templateName": "业务办理争议类",
        "target": "online",
        "rev": "r1",
        "entry": "API调用",
        "status": "SUCCESS",
        "startTime": f"{today.isoformat()} 08:00:00",
        "durationMs": 320,
        "rounds": 2,
        "foundCount": 5,
        "totalCount": 5,
        "inputs": {"手机号码": "13900009999", "业务名称": "流量包"},
    }
    (ddir / f"{orphan_id}.json").write_text(
        json.dumps(orphan_detail, ensure_ascii=False), encoding="utf-8"
    )

    lines = [
        json.dumps(
            {
                "runId": f"{day_prefix}09{(i // 60) % 60:02d}{i % 60:02d}000bulk{i:04d}",
                "templateId": 1001,
                "templateName": "业务办理争议类",
                "rev": "r1",
                "entry": "API调用",
                "status": "SUCCESS",
                "startTime": f"{today.isoformat()} 09:{(i // 60) % 60:02d}:{i % 60:02d}",
                "durationMs": 500,
                "rounds": 3,
                "found": 5,
                "total": 5,
                "mobile": f"1380000{i % 10000:04d}",
                "busiName": "套餐变更",
                "batchNo": "",
            },
            ensure_ascii=False,
        )
        for i in range(2500)
    ]
    (ddir / "index.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    store = RunStore(layout)
    await store.start()
    try:
        # 启动恢复已将孤儿记录补写进 index.jsonl
        first_page = store.list(date_from=today, date_to=today, limit=20, offset=0)
        assert len(first_page) == 20
        orphan_matches = store.list(
            date_from=today,
            date_to=today,
            limit=10,
            predicate=lambda r: r["runId"] == orphan_id,
        )
        assert len(orphan_matches) == 1 and orphan_matches[0]["mobile"] == "13900009999"

        # 拦截 Path.glob：验证启动后日常分页读取绝不再触发目录 *.json glob 扫描
        orig_glob = Path.glob

        def guard_glob(self_path: Path, pattern: str):
            if pattern == "*.json":
                raise AssertionError("日常分页读取严禁执行全目录 *.json glob 扫描！")
            return orig_glob(self_path, pattern)

        monkeypatch.setattr(Path, "glob", guard_glob)

        t0 = time.perf_counter()
        page = store.list(date_from=today, date_to=today, limit=50, offset=100)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert len(page) == 50
        assert elapsed_ms < 25.0
    finally:
        await store.stop()
