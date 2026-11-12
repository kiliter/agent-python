"""接口契约内置占位符 ${$now} 测试（统一网关公共字段 request_time）。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import re
from datetime import datetime

from report_agent.domain.api_contract import builtin_values, fixed_params, parse_api_yaml
from report_agent.gateway.unified_xml import build_request_json, build_request_preview, build_request_xml

CONTRACT_YAML = """
name: BOSS_QryBalanceFlowLog
title: 充值流水查询
processCode: BOSS_QryBalanceFlowLog
input:
  type: object
  required: [手机号码]
  additionalProperties: false
  properties:
    手机号码:
      type: string
      pattern: '^1\\d{10}$'
request:
  route_type: '2'
  route_value: ${手机号码}
  request_time: ${$now}
  content:
    billId: ${手机号码}
    queryTime: ${$now}
"""


def test_builtin_values_format():
    assert builtin_values(datetime(2026, 1, 2, 3, 4, 5)) == {"$now": "20260102030405"}


def test_now_placeholder_is_valid_and_substituted():
    api = parse_api_yaml(CONTRACT_YAML)
    assert api.schema_errors() == []
    before = datetime.now().strftime("%Y%m%d%H%M%S")
    req = api.build_request({"手机号码": "13900001234"})
    after = datetime.now().strftime("%Y%m%d%H%M%S")
    assert re.fullmatch(r"\d{14}", req["request_time"]) and before <= req["request_time"] <= after
    assert req["content"]["queryTime"] == req["request_time"]
    # 模型参数不能覆盖内置占位符
    assert api.build_request({"手机号码": "13900001234", "$now": "x"})["request_time"] != "x"

    xml = build_request_xml(api.processCode, req, "app", "token", "java")
    assert f"<request_time>{req['request_time']}</request_time>" in xml
    assert 'request_time xmlns:xsi' not in xml
    clean = build_request_xml(api.processCode, req, "app", "token", "clean")
    assert f"<request_time>{req['request_time']}</request_time>" in clean
    js = build_request_json(api.processCode, req, "app", "token")
    assert f'"request_time": "{req["request_time"]}"' in js


def test_now_placeholder_without_request_time_keeps_nil():
    api = parse_api_yaml(CONTRACT_YAML.replace("  request_time: ${$now}\n", ""))
    xml = build_request_xml(api.processCode, api.build_request({"手机号码": "13900001234"}), "a", "t", "java")
    assert '<request_time xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:nil="true"/>' in xml


def test_builtin_placeholder_schema_errors():
    unknown = parse_api_yaml(CONTRACT_YAML.replace("request_time: ${$now}", "request_time: ${$today}"))
    assert any("未知的内置占位符" in e and "$today" in e for e in unknown.schema_errors())
    declared = parse_api_yaml(CONTRACT_YAML.replace("    手机号码:\n      type: string\n",
                                                    "    $now:\n      type: string\n    手机号码:\n      type: string\n"))
    assert any("$ 开头" in e for e in declared.schema_errors())
    undeclared = parse_api_yaml(CONTRACT_YAML.replace("billId: ${手机号码}", "billId: ${号码}"))
    assert any("未在 input 中声明的参数 ${号码}" in e for e in undeclared.schema_errors())


def test_preview_and_fixed_params_with_now():
    api = parse_api_yaml(CONTRACT_YAML)
    preview = build_request_preview(api, {})
    assert re.search(r"<request_time>\d{14}</request_time>", preview)
    assert "${手机号码}" in preview                                     # 未提供的普通参数仍保留占位符
    fixed = {p["name"]: p["value"] for p in fixed_params(api.request)}
    assert fixed["request_time"] == "${$now}" and fixed["content.queryTime"] == "${$now}"
    assert "route_value" not in fixed
