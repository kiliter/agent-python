"""统一网关 JSON/XML 双协议契约、报文组装、脱敏预览、响应抽取与 Mock 自动转换测试。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from fixture_paths import SEED_DIR
from report_agent.domain.api_contract import ConnectorType, fixed_params, parse_api_yaml
from report_agent.gateway.base import MAX_JSON_CHARS, extract_json_records, parse_json_body
from report_agent.gateway.mock import MockGatewayClient
from report_agent.gateway.unified_xml import (UnifiedGatewayXmlClient, build_request_json, build_request_preview,
                                              mask_json, parse_gateway_json_response)

SMS_XML_API = parse_api_yaml((SEED_DIR / "apis/querySMSSendInfo.yaml").read_text(encoding="utf-8"))

JSON_CONTRACT_YAML = """
name: queryOrderJson
title: 订单查询（JSON）
description: 查询客户订单明细
connector: unified-gateway-json
processCode: queryOrderInfo
timeoutMs: 8000
retry:
  maxAttempts: 2
idempotent: true
headers:
  X-Channel-Id: "eshop"
  X-Trace-Mobile: "${手机号码}"
input:
  type: object
  required: [手机号码, 开始时间]
  additionalProperties: false
  properties:
    手机号码:
      type: string
      pattern: '^1\\d{10}$'
    开始时间:
      type: string
      pattern: '^\\d{14}$'
    验证码:
      type: string
request:
  route_type: "2"
  route_value: "${手机号码}"
  verify_code: "${验证码}"
  sys_tag: "CRM_V5"
  content:
    mobile: "${手机号码}"
    query:
      startTime: "${开始时间}"
      includeHistory: true
      channels: ["APP", "HOTLINE"]
      pageSize: 20
response:
  success:
    path: operation_out.response.resp_code
    equals: "0000"
    missingAs: failure
  noData:
    - path: operation_out.response.resp_code
      equals: "2004"
    - path: operation_out.response.resp_desc
      contains: "无订单记录"
  records:
    path: operation_out.content.orderList
    columns:
      orderId: 订单流水
      offerName: 商品名称
      fee: 资费
      active: 是否生效
      detail: 扩展详情
"""


def test_json_contract_schema_headers_and_fixed_params():
    api = parse_api_yaml(JSON_CONTRACT_YAML)
    assert api.connector == "unified-gateway-json"
    assert api.is_json is True
    assert not SMS_XML_API.is_json
    assert ConnectorType.__args__ == ("unified-gateway-xml", "unified-gateway-json")
    assert api.schema_errors() == []

    # JSON 契约允许包含非 XML 标签字符的 JSON 键（如 @type），但拦截空键名
    json_special_key = api.model_copy(update={"request": {"content": {"@type": "order"}}})
    assert json_special_key.schema_errors() == []
    json_empty_key = api.model_copy(update={"request": {"content": {"": "bad"}}})
    assert any("空的 JSON 键名" in e for e in json_empty_key.schema_errors())

    # headers 安全校验：禁止 CRLF 注入、受保护头覆盖、未声明占位符
    crlf_hdr = api.model_copy(update={"headers": {"X-Evil": "ok\r\nInjected: 1"}})
    assert any("换行或控制字符" in e for e in crlf_hdr.schema_errors())
    with pytest.raises(ValueError, match="换行或控制字符"):
        crlf_hdr.build_headers({"手机号码": "13900001234"})

    host_hdr = api.model_copy(update={"headers": {"Host": "evil.example", "Content-Length": "99"}})
    hdr_errs = host_hdr.schema_errors()
    assert any("Host" in e for e in hdr_errs) and any("Content-Length" in e for e in hdr_errs)

    undeclared_hdr = api.model_copy(update={"headers": {"X-Req": "${未知入参}"}})
    assert any("headers 引用了未在 input 中声明的参数 ${未知入参}" in e for e in undeclared_hdr.schema_errors())

    # fixed_params 支持列表紧凑序列化与布尔值展示，且跳过含占位符的字段
    fp = {item["name"]: item["value"] for item in fixed_params(api.request)}
    assert fp["route_type"] == "2"
    assert fp["sys_tag"] == "CRM_V5"
    assert fp["content.query.includeHistory"] == "true"
    assert fp["content.query.channels"] == '["APP","HOTLINE"]'
    assert fp["content.query.pageSize"] == "20"
    assert "content.mobile" not in fp and "content.query.startTime" not in fp


def test_build_request_json_masking_and_preview():
    api = parse_api_yaml(JSON_CONTRACT_YAML)
    built_req = api.build_request({"手机号码": "13800138000", "开始时间": "20261105000000", "验证码": "654321"})
    raw_json = build_request_json(api.processCode, built_req, "APP_SECRET", "TOKEN_SECRET")
    parsed = json.loads(raw_json)
    op = parsed["operation_in"]
    assert op["process_code"] == "queryOrderInfo"
    assert op["app_id"] == "APP_SECRET" and op["access_token"] == "TOKEN_SECRET"
    assert op["route_type"] == "2" and op["route_value"] == "13800138000"
    assert op["verify_code"] == "654321"
    assert op["sys_tag"] == "CRM_V5"
    assert op["content"]["query"]["includeHistory"] is True
    assert op["content"]["query"]["channels"] == ["APP", "HOTLINE"]
    assert op["content"]["query"]["pageSize"] == 20

    masked = mask_json(raw_json)
    assert "\n  " in masked  # 2 空格缩进
    masked_op = json.loads(masked)["operation_in"]
    assert masked_op["app_id"] == "***"
    assert masked_op["access_token"] == "***"
    assert masked_op["verify_code"] == "***"
    assert masked_op["route_value"] == "138****8000"
    assert masked_op["content"]["mobile"] == "138****8000"

    # build_request_preview：只传部分参数时，已传手机号被脱敏，未传参数保留 ${参数名} 占位符
    json_preview = build_request_preview(api, {"手机号码": "13912345678"})
    prev_op = json.loads(json_preview)["operation_in"]
    assert prev_op["app_id"] == "***" and prev_op["access_token"] == "***"
    assert prev_op["route_value"] == "139****5678"
    assert prev_op["content"]["mobile"] == "139****5678"
    assert prev_op["content"]["query"]["startTime"] == "${开始时间}"
    assert prev_op["verify_code"] == "${验证码}"

    xml_preview = build_request_preview(SMS_XML_API, {"手机号码": "13912345678"})
    assert "139****5678" in xml_preview
    assert "<startDate>${开始时间}</startDate>" in xml_preview
    assert "<endDate>${结束时间}</endDate>" in xml_preview
    assert "<access_token>***</access_token>" in xml_preview


def test_parse_and_extract_json_records_variants():
    api = parse_api_yaml(JSON_CONTRACT_YAML)

    with pytest.raises(ValueError, match="为空"):
        parse_json_body("   ")
    with pytest.raises(ValueError, match="最大长度"):
        parse_json_body('{"a":"' + ("x" * MAX_JSON_CHARS) + '"}')

    # 1) 标准 operation_out 包裹 + 列表记录（含 None、空对象过滤，子对象/数组转紧凑 JSON，标量转字符串）
    wrapped_data = {
        "operation_out": {
            "response": {"resp_code": "0000", "resp_desc": "ok"},
            "content": {
                "orderList": [
                    {
                        "orderId": 10001,
                        "offerName": "5G智享套餐",
                        "fee": 129.0,
                        "active": True,
                        "remark": None,
                        "detail": {"eff": "次月", "tags": ["5G", "语音"]},
                    },
                    None,
                    {},
                ]
            },
        }
    }
    res1 = extract_json_records(api, wrapped_data)
    assert res1.ok and not res1.no_data and len(res1.records) == 1
    assert res1.records[0] == {
        "orderId": "10001",
        "offerName": "5G智享套餐",
        "fee": "129.0",
        "active": "true",
        "remark": "",
        "detail": '{"eff":"次月","tags":["5G","语音"]}',
    }

    # 2) 顶层不带 operation_out 包裹 + 单对象自动转为单行记录
    unwrapped_single = {
        "response": {"resp_code": "0000"},
        "content": {"orderList": {"orderId": "A02", "offerName": "流量包"}},
    }
    res2 = extract_json_records(api, unwrapped_single)
    assert res2.ok and res2.records == [{"orderId": "A02", "offerName": "流量包"}]

    # 3) noData 命中（equals 与 contains）
    res_nodata_eq = extract_json_records(api, {"response": {"resp_code": "2004", "resp_desc": "empty"}})
    assert res_nodata_eq.ok and res_nodata_eq.no_data and res_nodata_eq.records == []
    res_nodata_ct = extract_json_records(api, {"response": {"resp_code": "9001", "resp_desc": "该时段无订单记录"}})
    assert res_nodata_ct.ok and res_nodata_ct.no_data and res_nodata_ct.records == []

    # 4) 业务失败码 + error_msg / message 提取 + missingAs=failure
    res_err = extract_json_records(api, {"response": {"resp_code": "5001", "error_msg": "下游账务中心超时"}})
    assert not res_err.ok and res_err.error == "业务返回码 5001：下游账务中心超时"
    res_missing = extract_json_records(api, {"content": {"orderList": []}})
    assert not res_missing.ok and "operation_out.response.resp_code" in (res_missing.error or "")

    # 5) 非法 JSON 响应容错
    bad_resp = parse_gateway_json_response(api, "{not-valid-json", 200, 3, "{}")
    assert not bad_resp.ok and "不是合法的 JSON" in (bad_resp.error or "")


async def test_unified_gateway_client_json_dispatch_and_retry(monkeypatch):
    async def _fast_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
    api = parse_api_yaml(JSON_CONTRACT_YAML)
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        if len(captured_requests) == 1:
            return httpx.Response(503, text='{"error":"busy"}')
        return httpx.Response(
            200,
            json={
                "operation_out": {
                    "response": {"resp_code": "0000"},
                    "content": {"orderList": [{"orderId": "ORD-1", "offerName": "宽带提速包"}]},
                }
            },
        )

    gw = UnifiedGatewayXmlClient("http://gw.example", "REAL_APP", "REAL_TOKEN")
    gw._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    res = await gw.invoke(api, {"手机号码": "13900001234", "开始时间": "20261105103012"})
    await gw.aclose()

    assert res.ok and res.attempts == 2
    assert res.records == [{"orderId": "ORD-1", "offerName": "宽带提速包"}]
    req = captured_requests[-1]
    assert "application/json" in req.headers["content-type"]
    assert req.headers["accept"] == "application/json"
    assert req.headers["x-channel-id"] == "eshop"
    assert req.headers["x-trace-mobile"] == "13900001234"
    sent_json = json.loads(req.content.decode("utf-8"))
    assert sent_json["operation_in"]["process_code"] == "queryOrderInfo"
    assert "REAL_TOKEN" not in res.request_preview and "139****1234" in res.request_preview


async def test_mock_gateway_json_lookup_and_xml_lossless_fallback(tmp_path: Path):
    # 1) 现有 XML 接口直接切换为 unified-gateway-json 时，自动将同名 .xml 无损转换为等价 JSON 响应
    sms_as_json = SMS_XML_API.model_copy(update={"connector": "unified-gateway-json"})
    seed_mock = MockGatewayClient(SEED_DIR / "mock-gateway")
    fallback_res = await seed_mock.invoke(
        sms_as_json,
        {"手机号码": "13900001234", "开始时间": "20261105000000", "结束时间": "20261105235959"},
    )
    assert fallback_res.ok and len(fallback_res.records) == 5
    assert fallback_res.records[3]["smsContent"].startswith("【业务办理成功提醒】")
    raw_parsed = json.loads(fallback_res.raw)
    assert raw_parsed["operation_out"]["response"]["resp_code"] == "0000"
    assert json.loads(fallback_res.request_preview)["operation_in"]["route_value"] == "139****1234"

    # 2) 优先命中 <name>.<route>.json，其次 <name>.json，不存在时返回明确 .json 提示
    api = parse_api_yaml(JSON_CONTRACT_YAML)
    mock_dir = tmp_path / "mock-gateway"
    mock_dir.mkdir()
    (mock_dir / "queryOrderJson.json").write_text(
        json.dumps({"response": {"resp_code": "0000"}, "content": {"orderList": [{"orderId": "DEFAULT"}]}}),
        encoding="utf-8",
    )
    (mock_dir / "queryOrderJson.13900001234.json").write_text(
        json.dumps({"response": {"resp_code": "0000"}, "content": {"orderList": [{"orderId": "BY_ROUTE"}]}}),
        encoding="utf-8",
    )
    client = MockGatewayClient(mock_dir)
    r_route = await client.invoke(api, {"手机号码": "13900001234", "开始时间": "20261105000000"})
    assert r_route.ok and r_route.records == [{"orderId": "BY_ROUTE"}]

    r_default = await client.invoke(api, {"手机号码": "13800009999", "开始时间": "20261105000000"})
    assert r_default.ok and r_default.records == [{"orderId": "DEFAULT"}]

    missing_api = api.model_copy(update={"name": "nonExistentJsonApi"})
    r_missing = await client.invoke(missing_api, {"手机号码": "13800009999", "开始时间": "20261105000000"})
    assert not r_missing.ok and r_missing.error == "mock 模式下没有找到样例响应 nonExistentJsonApi.json"


def test_deeply_nested_json_and_header_control_chars_safety():
    api = parse_api_yaml(JSON_CONTRACT_YAML)

    # 1) 构造 1500 层超深嵌套对象（远超默认递归栈上限），验证 extract_json_records 与 parse_gateway_json_response 不抛 RecursionError
    deep_obj: dict = {"leaf": "end"}
    for _ in range(1500):
        deep_obj = {"next": deep_obj}
    deep_payload = {"operation_out": {"response": {"resp_code": "9999"}, "deep": deep_obj}}
    res_extract = extract_json_records(api, deep_payload)
    assert not res_extract.ok and "9999" in (res_extract.error or "")

    deep_json_str = '{"response":{"resp_code":"9999"},"deep":' + ('{"a":' * 1500) + '1' + ('}' * 1500) + '}'
    res_parse = parse_gateway_json_response(api, deep_json_str, 200, 1, "{}")
    assert not res_parse.ok and res_parse.error

    # 2) 请求头值中的控制字符（\x01~\x08, \x1f, \x7f）在静态 schema_errors 与动态参数替换 build_headers 中均被拦截，合法 \t 放行
    for ctrl in ("\x01", "\x07", "\x1f", "\x7f"):
        bad_static = api.model_copy(update={"headers": {"X-Custom": f"val{ctrl}bad"}})
        assert any("控制字符" in e for e in bad_static.schema_errors())
        dyn_hdr = api.model_copy(update={"headers": {"X-Auth-Code": "${验证码}"}})
        with pytest.raises(ValueError, match="控制字符"):
            dyn_hdr.build_headers({"手机号码": "13900001234", "验证码": f"123{ctrl}456"})

    tab_hdr = api.model_copy(update={"headers": {"X-Custom": "part1\tpart2"}})
    assert tab_hdr.schema_errors() == []
    assert tab_hdr.build_headers({"手机号码": "13900001234"})["X-Custom"] == "part1\tpart2"

