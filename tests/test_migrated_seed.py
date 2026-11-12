"""迁移后内置资源（src/report_agent/seed）的回归测试。

#Created By AiCoding(codex)
- 不依赖 Java 工程的检查始终执行：资源可加载、发布校验零 error 且零 warning、无同名“客户号码”入参、
  模板 120 `有设备押金` 渲染分支修复、靓号字段配置、模板 ID 与 Java 资源库一致。
- 依赖 Java 工程（/Users/.../agent 源码与编译产物、JDK）的一致性校验在环境具备时执行，否则跳过：
  结构与规则一致性（verify_structure）、Pebble/Jinja2 渲染等价（verify_render）、Skill 与缺陷修复对拍（check_skills）。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from report_agent.container import SEED_DIR as PROD_SEED_DIR
from report_agent.domain.jinja_env import render_body
from report_agent.domain.resources import (
    ROUTER_SKILL_ID,
    _ROUTER_TPL_HEADING_RE,
    ResourceSet,
    load_resource_dir,
    validate_all,
    validate_skill,
    validate_template,
)
from report_agent.domain.skill import parse_skill_markdown
from report_agent.domain.template import Template
from report_agent.gateway.base import extract_records, parse_xml
from report_agent.runtime.evidence import EvidenceChecker
from report_agent.runtime.render import build_render_context
from report_agent.runtime.workspace import ApiResult, Workspace

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools/java_migration"
JAVA_AGENT = Path("/Users/zhangjialin/IdeaProjects/agent")


def test_prod_seed_loads_and_validates_zero_warnings():
    """验证内置资源加载正常且发布校验达到 0 errors, 0 warnings。#Created By AiCoding(codex)"""
    rs = load_resource_dir(PROD_SEED_DIR)
    assert not rs.load_issues
    issues = validate_all(rs)
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    assert errors == []
    assert warnings == []
    assert len(rs.templates) == 33 and len(rs.skills) == 12 and len(rs.apis) == 3


def test_template_router_skill_coverage_and_cross_validation():
    """验证生产 seed 中 template-router 覆盖全部 33 个在线模板，且交叉校验准确拦截各类违例。#Created By AiCoding(codex)"""
    rs = load_resource_dir(PROD_SEED_DIR)
    assert ROUTER_SKILL_ID in rs.skills
    router = rs.skills[ROUTER_SKILL_ID]
    assert router.meta.apis == []
    covered = {int(m.group(1)) for m in _ROUTER_TPL_HEADING_RE.finditer(router.body)}
    assert covered == set(range(100, 133))
    assert validate_all(rs) == []

    # 1) 声明业务接口时报错 ROUTER_SKILL_HAS_APIS
    bad_api_skill = parse_skill_markdown(
        "---\nname: template-router\ntitle: 模板路由\ndescription: 路由\napis:\n  - querySMSSendInfo\n---\n\n"
        + router.body
    )
    api_issues = validate_skill(bad_api_skill, rs)
    assert any(i.level == "error" and i.code == "ROUTER_SKILL_HAS_APIS" for i in api_issues)

    # 2) 缺少在线模板（漏 100）+ 引用不存在模板（999）与已下线模板（131）
    custom_templates = dict(rs.templates)
    custom_templates[131] = Template(definition=rs.templates[131].definition, body=rs.templates[131].body, offline=True)
    custom_templates[132] = Template(definition=rs.templates[132].definition, body=rs.templates[132].body, offline=True)
    custom_rs = ResourceSet(
        system_prompt=rs.system_prompt,
        templates=custom_templates,
        skills=dict(rs.skills),
        apis=dict(rs.apis),
    )
    headings = "\n\n".join(f"### {tid} 模板\n说明" for tid in [*range(101, 132), 999])
    partial_skill = parse_skill_markdown(
        f"---\nname: template-router\ntitle: 模板路由\ndescription: 路由\napis: []\n---\n\n{headings}\n"
    )
    router_issues = validate_skill(partial_skill, custom_rs)
    not_found_msgs = [i.message for i in router_issues if i.level == "error" and i.code == "ROUTER_TEMPLATE_NOT_FOUND"]
    uncovered_msgs = [i.message for i in router_issues if i.level == "warning" and i.code == "ROUTER_TEMPLATE_UNCOVERED"]
    assert len(not_found_msgs) == 2
    assert any("999" in m for m in not_found_msgs)
    assert any("131" in m for m in not_found_msgs)
    assert len(uncovered_msgs) == 1
    assert "100（不知情业务办理争议处理类）" in uncovered_msgs[0]

    # 3) 填报模板误关联 template-router 时报 ROUTER_SKILL_IN_TEMPLATE warning
    tpl100_def = rs.templates[100].definition.model_copy(
        update={"skills": [*rs.templates[100].definition.skills, ROUTER_SKILL_ID]}
    )
    tpl_issues = validate_template(Template(definition=tpl100_def, body=rs.templates[100].body), rs)
    assert any(i.level == "warning" and i.code == "ROUTER_SKILL_IN_TEMPLATE" for i in tpl_issues)

    # 4) 不含 template-router 的 ResourceSet 不产生任何报错或警告
    no_router_rs = ResourceSet(
        system_prompt=rs.system_prompt,
        templates=dict(rs.templates),
        skills={k: v for k, v in rs.skills.items() if k != ROUTER_SKILL_ID},
        apis=dict(rs.apis),
    )
    assert validate_all(no_router_rs) == []


def test_no_customer_phone_input_collision():
    """验证所有模板不再定义与字段同名的“客户号码”入参（消除 106/107/131/132 发布警告）。#Created By AiCoding(codex)"""
    rs = load_resource_dir(PROD_SEED_DIR)
    for tid, tpl in rs.templates.items():
        input_keys = [i.key for i in tpl.definition.inputs]
        assert "客户号码" not in input_keys, f"模板 {tid} 仍包含冗余入参 客户号码"
    for tid in (106, 107, 131, 132):
        field_names = {f.name for f in rs.templates[tid].definition.fields}
        assert "客户号码" in field_names
    assert rs.templates[106].definition.field("充值流水").visible is True
    assert rs.templates[107].definition.field("充值流水").visible is True
    assert rs.templates[119].definition.field("账期短信提醒列表").visible is True


def test_template_120_deposit_else_branch_fix():
    """验证模板 120（宽带业务续约争议类）中 有设备押金 缺失时进入 {% else %} 分支。#Created By AiCoding(codex)"""
    rs = load_resource_dir(PROD_SEED_DIR)
    tpl = rs.templates[120]
    dep_field = tpl.definition.field("有设备押金")
    assert dep_field is not None and dep_field.whenMissing == "empty"

    missing_report = {
        f.name: {"status": "not_found", "value": None, "evidence": [], "reasoning": ""}
        for f in tpl.definition.fields
    }
    missing_report["商品名称"] = {
        "status": "found",
        "value": "千兆宽带包年",
        "evidence": [{"type": "input", "key": "业务名称"}],
        "reasoning": "",
    }
    rendered_missing, _ = render_body(tpl.body, build_render_context(tpl, missing_report))
    assert "- 无千兆宽带包年设备押金记录。" in rendered_missing
    assert "- 设备押金{押金金额}元已于{退还日期}退还至{退还账户}。" not in rendered_missing

    found_report = dict(missing_report)
    found_report["有设备押金"] = {
        "status": "found",
        "value": "有",
        "evidence": [{"type": "document", "quote": "押金"}],
        "reasoning": "",
    }
    rendered_found, _ = render_body(tpl.body, build_render_context(tpl, found_report))
    assert "- 设备押金{押金金额}元已于{退还日期}退还至{退还账户}。" in rendered_found
    assert "- 无千兆宽带包年设备押金记录。" not in rendered_found


def test_pretty_number_fields_config():
    """验证靓号相关字段配置支持多档活动名称拼接（derive）、非靓号默认值及顶层网关报错拦截。#Created By AiCoding(codex)"""
    rs = load_resource_dir(PROD_SEED_DIR)
    cat_131 = rs.templates[131].definition.field("手机号类别")
    assert cat_131 is not None and cat_131.whenMissing == "value" and cat_131.defaultValue == "非靓号"
    for tid in (131, 132):
        tpl = rs.templates[tid]
        grade_field = tpl.definition.field("靓号等级")
        ev_field = tpl.definition.field("靓号活动名称")
        assert grade_field is not None and grade_field.evidence == "quote"
        assert ev_field is not None and ev_field.evidence == "derive"

    pretty_api = rs.apis["cc_pretty_num_info_query"]
    assert pretty_api.response.success is not None and pretty_api.response.success.missingAs == "failure"
    err_res = extract_records(
        pretty_api,
        parse_xml("<operation_out><response><resp_code>9999</resp_code><resp_desc>超时</resp_desc></response></operation_out>"),
    )
    assert err_res.ok is False and err_res.no_data is False
    nodata_res = extract_records(
        pretty_api,
        parse_xml("<operation_out><content><ret_code>1</ret_code><ret_msg>号码不存在</ret_msg></content></operation_out>"),
    )
    assert nodata_res.ok is True and nodata_res.no_data is True and nodata_res.records == []


def test_batch2_seed_consistency_fixes():
    """验证 Batch 2 模板与 Skill 一致性修复：安装地址/标准资费 derive、111/114/115 违约责任分支、deadlineDate 入参等。#Created By AiCoding(codex)"""
    rs = load_resource_dir(PROD_SEED_DIR)

    # 1) 模板 121 安装地址支持 extraInfo 回退（evidence=derive）
    tpl121 = rs.templates[121]
    addr_field = tpl121.definition.field("安装地址")
    assert addr_field is not None and addr_field.evidence == "derive" and addr_field.defaultValue == "无"
    rep121 = {f.name: {"status": "not_found", "value": None, "evidence": [], "reasoning": ""} for f in tpl121.definition.fields}
    rep121["安装地址"] = {
        "status": "found",
        "value": "南京市鼓楼区中山北路1号",
        "evidence": [{"type": "input", "key": "extraInfo"}],
        "reasoning": "单据无安装地址，从 extraInfo 提取",
    }
    issues_121 = EvidenceChecker(
        tpl121, {"extraInfo": '{"安装地址":"南京市鼓楼区中山北路1号"}'}, "", Workspace()
    ).check(rep121)
    assert issues_121 == []

    # 2) 10 个模板的标准资费为 derive，允许将“月费10元”标准化为“10元/月”
    tariff_tids = (100, 101, 102, 103, 104, 116, 119, 122, 125, 126)
    for tid in tariff_tids:
        tf = rs.templates[tid].definition.field("标准资费")
        assert tf is not None and tf.evidence == "derive", f"模板 {tid} 标准资费应为 derive"
    tpl100 = rs.templates[100]
    ws100 = Workspace()
    ws100.add_result(ApiResult(
        result_id="r1", api="querySMSSendInfo", title="短信", args={}, ok=True, error=None, columns={},
        records=[{"smsContent": "您已办理套餐，月费10元。", "smsSendTime": "20261105100000"}], cost_ms=1,
    ))
    rep100 = {f.name: {"status": "not_found", "value": None, "evidence": [], "reasoning": ""} for f in tpl100.definition.fields}
    rep100["标准资费"] = {
        "status": "found",
        "value": "10元/月",
        "evidence": [{"type": "api", "resultId": "r1", "row": 0, "column": "smsContent"}],
        "reasoning": "月费10元标准化为10元/月",
    }
    assert EvidenceChecker(tpl100, {}, "", ws100).check(rep100) == []

    # 3) 模板 111 / 114 / 115 违约责任恒真分支修复
    for tid in (111, 114):
        tpl = rs.templates[tid]
        bf = tpl.definition.field("违约责任")
        assert bf is not None and bf.visible is False and bf.whenMissing == "empty"
        miss_rep = {f.name: {"status": "not_found", "value": None, "evidence": [], "reasoning": ""} for f in tpl.definition.fields}
        rendered_miss, _ = render_body(tpl.body, build_render_context(tpl, miss_rep))
        assert "支付违约金" not in rendered_miss
        hit_rep = dict(miss_rep)
        hit_rep["违约责任"] = {"status": "found", "value": "提前解约需赔付违约金", "evidence": [], "reasoning": ""}
        rendered_hit, _ = render_body(tpl.body, build_render_context(tpl, hit_rep))
        assert "支付违约金" in rendered_hit

    tpl115 = rs.templates[115]
    bf115 = tpl115.definition.field("违约责任")
    assert bf115 is not None and bf115.visible is True and bf115.whenMissing == "placeholder"
    miss115 = {f.name: {"status": "not_found", "value": None, "evidence": [], "reasoning": ""} for f in tpl115.definition.fields}
    rendered115_miss, used115_miss = render_body(tpl115.body, build_render_context(tpl115, miss115))
    assert "(4)违约责任：{{违约责任}}" in rendered115_miss
    assert "1. 违约行为：" not in rendered115_miss
    assert "违约行为" not in used115_miss and "违约时间" not in used115_miss
    hit115 = dict(miss115)
    hit115["违约责任"] = {"status": "found", "value": "机卡分离停机", "evidence": [], "reasoning": ""}
    rendered115_hit, used115_hit = render_body(tpl115.body, build_render_context(tpl115, hit115))
    assert "(4)违约责任：机卡分离停机" in rendered115_hit
    assert "1. 违约行为：{{违约行为}}" in rendered115_hit
    assert "违约行为" in used115_hit and "违约时间" in used115_hit

    # 4) 5 个模板补齐可选入参 deadlineDate；模板 107 客户号码优先级与活动时间说明补全；reminder-sms 不回退办理日
    for tid in (105, 108, 112, 120, 129):
        dl_inp = rs.templates[tid].definition.input("deadlineDate")
        assert dl_inp is not None and dl_inp.required is False, f"模板 {tid} 应包含可选入参 deadlineDate"
    cust107 = rs.templates[107].definition.field("客户号码")
    assert cust107 is not None and cust107.description.startswith("优先取入参「extraInfo」中的充值号码")
    act100 = rs.templates[100].definition.field("活动时间")
    assert act100 is not None and '"type":"api"' in act100.description and "订购短信" in act100.description
    rem_skill = rs.skills["reminder-sms"].body
    assert "绝不用作提醒短信查询日" in rem_skill
    assert "直接退回入参 `创建时间` 当天日期" not in rem_skill


def test_prod_seed_template_ids_match_java_resource_db():
    """验证 33 个模板 ID 与 Java 资源库一致。#Created By AiCoding(codex)"""
    ids = yaml.safe_load((TOOLS / "template_ids.yaml").read_text(encoding="utf-8"))["templates"]
    rs = load_resource_dir(PROD_SEED_DIR)
    assert {t.name: t.id for t in rs.templates.values()} == ids
    assert 1001 not in rs.templates  # 测试模板已移到 tests/fixtures/seed


def _run_tool(script: str) -> subprocess.CompletedProcess:
    """运行 tools/java_migration 下的校验脚本。#Created By AiCoding(codex)"""
    return subprocess.run([sys.executable, str(TOOLS / script)], cwd=ROOT, capture_output=True, text=True,
                          timeout=600)


@pytest.mark.skipif(not (JAVA_AGENT / "pdf-agent-parse/src/main/resources").exists(), reason="缺少 Java 工程源码")
def test_structure_consistent_with_java():
    """结构与规则一致性校验（0 errors, 0 warnings）。#Created By AiCoding(codex)"""
    res = _run_tool("verify_structure.py")
    assert res.returncode == 0, res.stdout + res.stderr


@pytest.mark.skipif(
    shutil.which("java") is None
    or not (JAVA_AGENT / "pdf-agent-parse/target/classes/com/agile/agent/pdf/parse/template").exists(),
    reason="缺少 JDK 或 Java 编译产物",
)
def test_render_equivalent_to_java_pebble():
    """Pebble 与 Jinja2 渲染对拍校验（含模板 120 修复分支验证）。#Created By AiCoding(codex)"""
    res = _run_tool("verify_render.py")
    assert res.returncode == 0, res.stdout[-4000:] + res.stderr[-2000:]


def test_skills_and_phase2_bug_fixes():
    """运行 check_skills.py 验证接口报文、11 个 Skill 确定性工具模拟及二期 4 类缺陷修复断言。#Created By AiCoding(codex)"""
    res = _run_tool("check_skills.py")
    assert res.returncode == 0, res.stdout[-4000:] + res.stderr[-2000:]
