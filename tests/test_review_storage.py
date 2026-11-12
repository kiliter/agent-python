"""存储治理层（store）、外部网关层（gateway）、应用入口与 CLI 审查回归测试。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import threading
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import report_agent.store.releases as releases_mod
from fixture_paths import SEED_DIR
from report_agent.cli import main as cli_main
from report_agent.config import Settings
from report_agent.container import build_container, build_gateway
from report_agent.domain.api_contract import parse_api_yaml
from report_agent.gateway.base import (
    ApiCallResult,
    _extract_json_dotted,
    _extract_xml_dotted,
    _first_json_text,
    parse_xml,
)
from report_agent.gateway.mock import MockGatewayClient
from report_agent.gateway.reloadable import ReloadableGatewayClient
from report_agent.gateway.unified_xml import UnifiedGatewayXmlClient, parse_gateway_json_response
from report_agent.main import create_app
from report_agent.store.cases import CaseDef
from report_agent.store.fsutil import append_jsonl, write_json
from report_agent.store.git_repo import GitError, GitRepo
from report_agent.store.layout import InvalidResource, ResourceRef, ensure_within, remove_resource
from report_agent.store.publisher import Change
from report_agent.store.runs import RunStore
from report_agent.store.runtime_config import RuntimeConfigValidationError
from scripted_model import scripted_model


def test_lifespan_restart_preserves_persisted_report_api_keys(tmp_path: Path) -> None:
    """不传预构建 container 重启应用时，lifespan 必须使用持久化生效配置而非原始环境变量，防止鉴权旁路。"""
    env_settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        gateway_mode="mock",
        llm_api_key="test",
        admin_token_secret="test-secret",
        report_api_keys="",
    )
    c_init = build_container(env_settings, model=scripted_model())
    assert c_init.runtime_config is not None
    c_init.runtime_config.update({"reportApiKeys": "persisted-key-alpha,persisted-key-beta"}, "admin")
    asyncio.run(c_init.gateway.aclose())

    # 模拟真实生产重启：仅传入原始 env_settings（其 report_api_keys 为空），由 lifespan 内部调用 build_container
    app = create_app(env_settings)
    with TestClient(app) as client:
        assert app.state.report_keys == {"persisted-key-alpha", "persisted-key-beta"}
        unauth = client.post("/api/v1/reports", json={"templateId": 999999, "params": {}, "document": "x"})
        assert unauth.status_code == 401

        authed = client.post(
            "/api/v1/reports",
            headers={"X-API-Key": "persisted-key-alpha"},
            json={"templateId": 999999, "params": {}, "document": "x"},
        )
        assert authed.status_code == 404


async def test_gateway_concurrency_wiring_mock_fallback_and_closed_invoke(tmp_path: Path) -> None:
    """校验 gateway_max_concurrency 透传、Mock 网关回退内置目录以及已关闭客户端调用不抛未捕获异常。"""
    live_settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        gateway_mode="live",
        gateway_url="https://gw.example.com",
        gateway_app_id="app1",
        gateway_access_token="tok1",
        gateway_max_concurrency=180,
    )
    c = build_container(live_settings, model=scripted_model())
    try:
        assert isinstance(c.gateway, ReloadableGatewayClient)
        live_gw = c.gateway.current
        assert isinstance(live_gw, UnifiedGatewayXmlClient)
        assert live_gw.max_concurrency == 180

        # 修改 env_settings 的并发度后触发 apply_runtime_config，网关签名变化应重建实例
        assert c.env_settings is not None
        c.env_settings = c.env_settings.model_copy(update={"gateway_max_concurrency": 64})
        c.apply_runtime_config()
        swapped_gw = c.gateway.current
        assert isinstance(swapped_gw, UnifiedGatewayXmlClient)
        assert swapped_gw is not live_gw
        assert swapped_gw.max_concurrency == 64
    finally:
        await c.gateway.aclose()

    # 客户端已关闭后调用 invoke，应捕获 RuntimeError 返回 ok=False 而非崩溃
    contract = parse_api_yaml((SEED_DIR / "apis/querySMSSendInfo.yaml").read_text(encoding="utf-8"))
    closed_gw = UnifiedGatewayXmlClient("https://gw.example.com", "app", "tok", max_concurrency=4)
    await closed_gw.aclose()
    closed_res = await closed_gw.invoke(
        contract,
        {"手机号码": "13900001234", "开始时间": "20261105000000", "结束时间": "20261105235959"},
    )
    assert closed_res.ok is False
    assert "RuntimeError" in (closed_res.error or "")

    # MockGatewayClient 在 data/mock-gateway 缺少标准样例但放入自定义文件时，应回退到内置 SEED_DIR/mock-gateway
    mock_settings = Settings(_env_file=None, data_dir=tmp_path / "mock_data", gateway_mode="mock")
    c_mock = build_container(mock_settings, model=scripted_model())
    try:
        for p in c_mock.layout.mock_gateway.iterdir():
            p.unlink()
        (c_mock.layout.mock_gateway / "customOnly.xml").write_text("<root/>", encoding="utf-8")
        gw = build_gateway(c_mock.settings, c_mock.layout)
        assert isinstance(gw, MockGatewayClient)
        hit = await gw.invoke(
            contract,
            {"手机号码": "13900001234", "开始时间": "20261105000000", "结束时间": "20261105235959"},
        )
        assert hit.ok is True
        assert len(hit.records) >= 1
    finally:
        await c_mock.gateway.aclose()


async def test_runtime_config_recovery_when_current_missing_or_corrupted(tmp_path: Path) -> None:
    """current.json 丢失或字段类型损坏时，启动组装应先从 cN 快照恢复再构建网关/模型，并严格保持 0600 权限。"""
    env_settings = Settings(_env_file=None, data_dir=tmp_path / "data", gateway_mode="mock", llm_model="env-model")
    c1 = build_container(env_settings, model=scripted_model())
    assert c1.runtime_config is not None
    c1.runtime_config.update(
        {
            "llmModel": "recovered-model-v2",
            "gatewayMode": "live",
            "gatewayUrl": "https://gw-v2.example.com",
            "reportApiKeys": "recovered-api-key",
        },
        "admin",
    )
    await c1.gateway.aclose()

    # 1) 删除 current.json 后重启 build_container：exists() 仍识别历史快照并在构建网关前恢复 c2
    c1.runtime_config.current_path.unlink()
    c2 = build_container(env_settings, model=scripted_model())
    try:
        assert c2.runtime_config is not None
        assert c2.runtime_config.active_rev() == "c2"
        assert c2.settings.llm_model == "recovered-model-v2"
        assert c2.settings.report_api_key_set() == {"recovered-api-key"}
        assert isinstance(c2.gateway.current, UnifiedGatewayXmlClient)
        assert c2.runtime_config.current_path.is_file()

        for secret_file in (
            c2.runtime_config.current_path,
            c2.runtime_config.index_path,
            c2.runtime_config.revisions_dir / "c2.json",
        ):
            mode = stat.S_IMODE(secret_file.stat().st_mode)
            assert mode == 0o600

        # revisions() 返回防御性浅拷贝，外部篡改不污染缓存
        revs = c2.runtime_config.revisions()
        revs[0]["config"]["llmModel"] = "mutated"
        assert c2.runtime_config.revisions()[0]["config"]["llmModel"] == "recovered-model-v2"

        # 2) current.json 写入损坏的字段类型：bootstrap_or_load 应自动回退至 c2 快照而不崩溃
        write_json(
            c2.runtime_config.current_path,
            {"activeRev": "c2", "n": "bad-int", "config": {"llmTemperature": "not-a-float"}},
            mode=0o600,
        )
        snap = c2.runtime_config.bootstrap_or_load(env_settings)
        assert snap.rev == "c2"
        assert snap.config.llmModel == "recovered-model-v2"

        # 3) 历史快照 c1.json 字段损坏时，rollback 抛 RuntimeConfigValidationError（400）而非未捕获 ValueError
        write_json(
            c2.runtime_config.revisions_dir / "c1.json",
            {"rev": "c1", "n": 1, "config": {"llmTimeoutS": "corrupted-float"}},
            mode=0o600,
        )
        with pytest.raises(RuntimeConfigValidationError):
            c2.runtime_config.rollback("c1", "测试损坏回退", "admin")
    finally:
        await c2.gateway.aclose()


def test_fsutil_permissions_and_symlink_escape_guards(container, tmp_path: Path) -> None:
    """验证 fsutil 0600 原子权限写入，以及 layout/drafts/cases/service 对软链接逃逸与目录软链的拦截。"""
    sec_json = tmp_path / "sec" / "secret.json"
    sec_jsonl = tmp_path / "sec" / "secret.jsonl"
    write_json(sec_json, {"token": "abc"}, mode=0o600)
    append_jsonl(sec_jsonl, {"event": "ok"}, mode=0o600)
    assert stat.S_IMODE(sec_json.stat().st_mode) == 0o600
    assert stat.S_IMODE(sec_jsonl.stat().st_mode) == 0o600

    outside = tmp_path / "outside"
    outside.mkdir()
    outside_secret = outside / "keep.txt"
    outside_secret.write_text("sensitive", encoding="utf-8")

    # ensure_within 拦截指向外部目录的软链接逃逸
    base = tmp_path / "sandbox"
    base.mkdir()
    escape_link = base / "escape"
    os.symlink(outside, escape_link)
    with pytest.raises(InvalidResource):
        ensure_within(base, escape_link)
    with pytest.raises(InvalidResource):
        ensure_within(base, escape_link / "keep.txt")

    # DraftStore 忽略目录软链接，且 delete / remove_resource 安全摘除内部目录软链而不误删目标目录内容
    internal_target = container.layout.drafts / ".internal_dir"
    internal_target.mkdir(parents=True)
    (internal_target / " marker.txt").write_text("stay", encoding="utf-8")

    skill_drafts_dir = container.layout.drafts / "skill"
    skill_drafts_dir.mkdir(parents=True, exist_ok=True)
    os.symlink(outside, skill_drafts_dir / "evil-skill")
    assert "evil-skill" not in container.drafts.list_keys("skill")

    # 草稿目录内放入指向外部文件的软链时，read_file 拦截抛 InvalidResource
    ref = ResourceRef("skill", "accept-type")
    container.drafts.write(ref, {"SKILL.md": "---\nname: accept-type\ntitle: t\ndescription: d\n---\nbody"}, "u", "r1")
    draft_dir = container.layout.draft_dir(ref)
    (draft_dir / "SKILL.md").unlink()
    os.symlink(outside_secret, draft_dir / "SKILL.md")
    with pytest.raises(InvalidResource):
        container.drafts.read_file(ref, "SKILL.md")
    container.drafts.delete(ref)

    # remove_resource 遇到树内目录软链时只 unlink 软链，不调 shutil.rmtree 报错或删目标
    tree_root = tmp_path / "tree"
    (tree_root / "skills").mkdir(parents=True)
    real_inside = tree_root / ".real_inside"
    real_inside.mkdir()
    (real_inside / "keep.md").write_text("ok", encoding="utf-8")
    os.symlink(real_inside, tree_root / "skills" / "accept-type")
    remove_resource(tree_root, ref)
    assert not (tree_root / "skills" / "accept-type").exists()
    assert (real_inside / "keep.md").is_file()

    # CaseStore 跳过软链接用例文件，overlay 指纹跳过软链
    container.cases.save(1001, CaseDef(id="C-10", name="正常用例"))
    case_dir = container.layout.cases / "1001"
    outside_yaml = outside / "C-99.yaml"
    outside_yaml.write_text("id: C-99\nname: 外部软链\n", encoding="utf-8")
    os.symlink(outside_yaml, case_dir / "C-99.yaml")
    ids = [c.id for c in container.cases.list(1001)]
    assert "C-10" in ids
    assert "C-99" not in ids
    assert container.cases.count(1001) == len(ids)

    overlay_rs = container.service.overlay()
    assert 1001 in overlay_rs.templates
    assert outside_secret.read_text(encoding="utf-8") == "sensitive"


def test_release_rollback_on_symlink_failure_and_read_file_at_fast_miss(
    container, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证首次空仓 Git 回滚、发布切换软链失败的完整事务回滚，以及物化快照缺失文件 0 git 子进程开销。"""
    # 1) 空 Git 仓库首次提交后 reset_to(None)，必须恢复为未诞生分支（head() is None）
    empty_repo = GitRepo(tmp_path / "empty_repo")
    empty_repo.ensure_init()
    assert empty_repo.head() is None
    (empty_repo.path / "hello.txt").write_text("v1", encoding="utf-8")
    first_sha = empty_repo.commit_all("init", "tester")
    assert empty_repo.head() == first_sha
    empty_repo.reset_to(None)
    assert empty_repo.head() is None
    assert not (empty_repo.path / "hello.txt").exists()

    # Git 子进程超时统一转为 GitError
    def _timeout_run(*_a, **_kw):
        raise subprocess.TimeoutExpired(cmd=["git"], timeout=1)

    monkeypatch.setattr(subprocess, "run", _timeout_run)
    with pytest.raises(GitError, match="超时"):
        empty_repo.head()
    monkeypatch.undo()

    # 2) Publisher.publish 在 atomic_symlink 抛异常时，完整回滚 index.jsonl、releases/r2 与 Git HEAD，且保留草稿
    prev_head = container.repo.head()
    sp_ref = ResourceRef("system-prompt", "system-prompt")
    container.service.save_system_prompt("新的系统提示词草稿", "tester")

    def _fail_symlink(_target: str, _link: Path) -> None:
        raise OSError("simulated symlink failure")

    monkeypatch.setattr(releases_mod, "atomic_symlink", _fail_symlink)
    with pytest.raises(OSError, match="simulated symlink failure"):
        container.publisher.publish([Change(sp_ref, "publish", "系统提示词")], "tester", "发布", "测试失败回滚")
    monkeypatch.undo()

    assert container.releases.live_rev() == "r1"
    assert not container.releases.has("r2")
    assert not (container.layout.releases / "r2").exists()
    assert container.repo.head() == prev_head
    assert container.drafts.exists(sp_ref)

    # 3) 物化快照存在 .release.json 时，读取不存在的 .offline 直接返回 None，不触发 repo.show 子进程
    show_calls: list[tuple[str, str]] = []
    orig_show = container.repo.show

    def _spy_show(commit: str, path: str) -> bytes | None:
        show_calls.append((commit, path))
        return orig_show(commit, path)

    monkeypatch.setattr(container.repo, "show", _spy_show)
    assert container.releases.read_file_at("r1", "templates/1001/.offline") is None
    assert show_calls == []

    # 4) prune 原子重命名清理旧快照后不残留 .prune-*，且已清理版本的 read_file_at 自动回退 repo.show
    container.releases.keep = 1
    container.service.publish_draft(sp_ref, "tester")
    assert container.releases.live_rev() == "r2"
    assert not list(container.layout.releases.glob(".prune-*"))
    assert not (container.layout.releases / "r1").exists()
    assert container.releases.read_file_at("r1", "system-prompt.md") is not None
    assert len(show_calls) == 1


async def test_run_store_concurrent_stop_drain_index_fallback_and_cleanup(container) -> None:
    """验证 RunStore 并发停止与线程投递无损落盘、取消排空、详情缺失索引缓存降级及空目录清理。"""
    runs: RunStore = container.runs
    await runs.start()

    def _make_pair(idx: int, day_prefix: str = "20261112") -> tuple[dict, dict]:
        rid = f"{day_prefix}120000{idx:03d}abcdefg"
        summary = {
            "runId": rid,
            "startTime": "2026-11-12T12:00:00+08:00",
            "templateId": 1001,
            "templateName": "样例",
            "rev": "r1",
            "status": "SUCCESS",
            "mobile": "13900001234",
            "found": 2,
            "total": 2,
            "durationMs": 50,
            "rounds": 1,
        }
        detail = {**summary, "inputs": {"手机号码": "13900001234"}, "report": f"ok-{idx}", "fields": []}
        return summary, detail

    for i in range(15):
        runs.submit(*_make_pair(i))

    # 并发执行 stop() 与工作线程同步回退 submit()
    def _sync_submit_worker() -> None:
        for j in range(15, 25):
            runs.submit(*_make_pair(j))

    worker = threading.Thread(target=_sync_submit_worker)
    worker.start()
    await runs.stop()
    worker.join()

    listed = runs.list(date_from=date(2026, 11, 12), date_to=date(2026, 11, 12), limit=100)
    assert len(listed) == 25
    assert not runs._pending

    # 验证后台任务被外部取消时，finally 块仍将队列残留项同步排空落盘
    await runs.start()
    assert runs._queue is not None and runs._task is not None
    s_cancel, d_cancel = _make_pair(99)
    runs._pending[s_cancel["runId"]] = (s_cancel, d_cancel)
    runs._queue.put_nowait((s_cancel, d_cancel))
    runs._task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await runs._task
    runs._queue = None
    runs._task = None
    got_cancel = runs.get(s_cancel["runId"])
    assert got_cancel is not None and got_cancel["report"] == "ok-99"
    assert not runs._pending

    # 删除单条 <runId>.json，验证 get() 从当日已缓存索引摘要降级恢复
    target_id = _make_pair(0)[0]["runId"]
    loc = runs._run_path(target_id)
    assert loc is not None
    loc[2].unlink()
    degraded = runs.get(target_id)
    assert degraded is not None
    assert degraded.get("recoveredFromIndex") is True
    assert degraded["inputs"]["手机号码"] == "13900001234"

    # 写入远古日期记录并执行 cleanup，验证过期日目录及变空的月/年父目录一并清理
    runs.submit(*_make_pair(1, day_prefix="20200102"))
    old_year_dir = runs.root / "2020"
    assert old_year_dir.is_dir()
    removed = runs.cleanup(keep_days=30)
    assert removed == 1
    assert not old_year_dir.exists()


async def test_reloadable_gateway_shield_and_xml_json_parity_and_cli_init(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证 ReloadableGatewayClient 取消防泄漏、XML/JSON 多节点空值过滤对齐、深层错误抽取与 CLI init。"""
    contract = parse_api_yaml((SEED_DIR / "apis/querySMSSendInfo.yaml").read_text(encoding="utf-8"))

    class _SlowCloseGateway:
        def __init__(self) -> None:
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.closed = False

        async def invoke(self, _contract, _args) -> ApiCallResult:
            self.entered.set()
            await self.release.wait()
            return ApiCallResult(ok=True, records=[])

        async def aclose(self) -> None:
            await asyncio.sleep(0.02)
            self.closed = True

    gw1 = _SlowCloseGateway()
    gw2 = _SlowCloseGateway()
    proxy = ReloadableGatewayClient(gw1)
    task = asyncio.create_task(proxy.invoke(contract, {}))
    await gw1.entered.wait()
    proxy.swap(gw2)

    # 在途请求被取消时，退役的 gw1 仍必须通过 shield 的后台关闭任务完成释放
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.05)
    assert gw1.closed is True
    await proxy.aclose()
    assert gw2.closed is True

    # XML _extract_xml_dotted 与 JSON _extract_json_dotted 在多节点含 xsi:nil / 空值时结果完全一致
    xml_one_valid = parse_xml(
        '<row xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<level_info><event_name xsi:nil="true"/></level_info>'
        "<level_info><event_name>黄金档</event_name></level_info>"
        "<level_info><event_name>   </event_name></level_info>"
        "</row>"
    )
    json_one_valid = {
        "level_info": [{"event_name": None}, {"event_name": "黄金档"}, {"event_name": "   "}],
    }
    assert _extract_xml_dotted(xml_one_valid, "level_info.event_name") == (True, "黄金档")
    assert _extract_json_dotted(json_one_valid, "level_info.event_name") == (True, "黄金档")

    xml_all_nil = parse_xml(
        '<row xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<level_info><event_name xsi:nil="true"/></level_info>'
        "<level_info><event_name/></level_info>"
        "</row>"
    )
    json_all_nil = {"level_info": [{"event_name": None}, {"event_name": ""}]}
    assert _extract_xml_dotted(xml_all_nil, "level_info.event_name") == (True, "")
    assert _extract_json_dotted(json_all_nil, "level_info.event_name") == (True, "")

    # _first_json_text 单遍显式栈扫描：严格按候选键优先级返回且支持 400 层深嵌套不栈溢出
    deep: dict = {"resp_desc": "高优错误描述"}
    for _ in range(400):
        deep = {"child": deep}
    payload_err = {"msg": "低优错误描述", "nested": deep}
    assert _first_json_text(payload_err, ["resp_desc", "ret_msg", "msg"]) == "高优错误描述"

    # 超大 JSON 响应（>200,000 字符）不执行整包缩进序列化，raw 严格截断至 200,000 字符
    json_contract = parse_api_yaml((SEED_DIR / "apis/querySMSSendInfo.yaml").read_text(encoding="utf-8")).model_copy(
        update={"connector": "unified-gateway-json"}
    )
    big_body = json.dumps(
        {
            "operation_out": {
                "resp_code": "0000",
                "content": {"smsList": [{"smsContent": "x" * 210_000}]},
            }
        }
    )
    assert len(big_body) > 200_000
    big_res = parse_gateway_json_response(json_contract, big_body, 200, 12, "{}")
    assert big_res.ok is True
    assert len(big_res.raw) == 200_000

    # CLI init 命令初始化数据目录并干净关闭网关
    cli_data = tmp_path / "cli_init_data"
    monkeypatch.setattr(
        "report_agent.cli.get_settings",
        lambda: Settings(_env_file=None, data_dir=cli_data, gateway_mode="mock"),
    )
    assert cli_main(["init"]) == 0
    await asyncio.sleep(0)
    assert (cli_data / "releases" / "current").is_symlink()
