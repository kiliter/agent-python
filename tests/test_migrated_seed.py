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
from report_agent.domain.resources import load_resource_dir, validate_all
from report_agent.runtime.render import build_render_context

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
    assert len(rs.templates) == 33 and len(rs.skills) == 11 and len(rs.apis) == 3


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
    """验证靓号相关字段配置支持多档活动名称拼接（derive）与非靓号默认值。#Created By AiCoding(codex)"""
    rs = load_resource_dir(PROD_SEED_DIR)
    cat_131 = rs.templates[131].definition.field("手机号类别")
    assert cat_131 is not None and cat_131.whenMissing == "value" and cat_131.defaultValue == "非靓号"
    for tid in (131, 132):
        tpl = rs.templates[tid]
        grade_field = tpl.definition.field("靓号等级")
        ev_field = tpl.definition.field("靓号活动名称")
        assert grade_field is not None and grade_field.evidence == "quote"
        assert ev_field is not None and ev_field.evidence == "derive"


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
