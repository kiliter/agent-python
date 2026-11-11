"""文本工具与统一网关报文测试。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from jinja2.exceptions import SecurityError, UndefinedError

from report_agent.container import SEED_DIR
from report_agent.domain.api_contract import parse_api_yaml
from report_agent.domain.jinja_env import TrackedValue, render_body
from report_agent.domain.resources import load_resource_dir
from report_agent.domain.template import body_variable_lines
from report_agent.gateway.base import MAX_XML_CHARS, decode_xml, parse_xml
from report_agent.gateway.mock import MockGatewayClient
from report_agent.gateway.unified_xml import (UnifiedGatewayXmlClient, build_request_xml, mask_xml,
                                              parse_gateway_response)
from report_agent.runtime.text_tools import (MAX_REGEX_LENGTH, convert_date, date_range, normalize_text,
                                             normalized_contains, safe_regex_compile)

SMS_API = parse_api_yaml((SEED_DIR / "apis/querySMSSendInfo.yaml").read_text(encoding="utf-8"))
NIL = ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:nil="true"'


def test_normalize_matches_java_rules():
    assert normalize_text("5G智享套餐（个人版）") == "5G智享套餐个人版"
    assert normalize_text("5G智享套餐(个人版)") == "5G智享套餐个人版"
    assert normalize_text("ＡＢＣ，１２３。") == "ABC123"
    assert normalize_text("a b\nc", " \n") == "abc"
    assert normalized_contains("办理业务：5G智享套餐(个人版)", "5G智享套餐（个人版）")
    assert not normalized_contains("任意", "")


def test_dates():
    assert convert_date("20261005", "yyyyMMdd", "yyyy年M月d号") == "2026年10月5号"
    assert convert_date("2026-11-05 10:12:08", "yyyy-MM-dd HH:mm:ss", "yyyy年M月d号 H时m分") == "2026年11月5号 10时12分"
    assert date_range("20261105103012", "day") == ("20261105000000", "20261105235959")
    assert date_range("20260215", "month") == ("20260201000000", "20260228235959")
    with pytest.raises(ValueError):
        convert_date("2026105", "yyyyMMdd", "yyyy")


def test_java_style_request_matches_existing_service():
    """与 Java XmlMapper 实际输出逐字一致（字母序 + xsi:nil + 无声明）。"""
    req = SMS_API.build_request({"手机号码": "13800138000", "开始时间": "20260501000000", "结束时间": "20260501235959"})
    xml = build_request_xml("querySMSSendInfo", req, "APP", "TOKEN", "java")
    expected = (
        "<operation_in><access_token>TOKEN</access_token><app_id>APP</app_id><content>"
        "<userMobile>13800138000</userMobile><startDate>20260501000000</startDate><endDate>20260501235959</endDate>"
        "<sendType>0</sendType><sendPort></sendPort><busiType>0</busiType></content>"
        f"<operator_id{NIL}/><organ_id>1</organ_id><process_code>querySMSSendInfo</process_code>"
        f"<request_seq{NIL}/><request_source>1</request_source><request_time{NIL}/><request_type>1</request_type>"
        f"<route_type>2</route_type><route_value>13800138000</route_value><verify_code{NIL}/></operation_in>"
    )
    assert xml == expected
    masked = mask_xml(xml)
    assert "TOKEN" not in masked and "138****8000" in masked


def test_clean_style_request():
    req = SMS_API.build_request({"手机号码": "13800138000", "开始时间": "20260501000000", "结束时间": "20260501235959"})
    xml = build_request_xml("querySMSSendInfo", req, "APP", "TOKEN", "clean")
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?><operation_in><process_code>')
    assert "xsi:nil" not in xml and "<operator_id></operator_id>" in xml and "request_time" not in xml


def test_args_validation_and_escaping():
    assert SMS_API.validate_args({"手机号码": "139", "开始时间": "1", "结束时间": "2"})
    assert SMS_API.validate_args({"手机号码": "13900001234", "开始时间": "20261105000000",
                                  "结束时间": "20261105235959", "多余": "x"})
    req = SMS_API.build_request({"手机号码": "<x>&", "开始时间": "a", "结束时间": "b"})
    assert "&lt;x&gt;&amp;" in build_request_xml("p", req, "a", "t")


def test_parse_success_and_no_data_gbk():
    ok = parse_gateway_response(SMS_API, (SEED_DIR / "mock-gateway/querySMSSendInfo.xml").read_text("utf-8"), 200, 1, "")
    assert ok.ok and len(ok.records) == 5 and ok.records[3]["smsContent"].startswith("【业务办理成功提醒】")
    body = ('<?xml version="1.0" encoding="GBK"?><operation_out><response><resp_result>1</resp_result>'
            '<resp_code>1</resp_code><resp_desc>号码不存在或该时间段内无短信记录!</resp_desc></response>'
            '</operation_out>').encode("gbk")
    nodata = parse_gateway_response(SMS_API, decode_xml(body, None), 200, 1, "")
    assert nodata.ok and nodata.no_data and nodata.records == []
    err = parse_gateway_response(SMS_API, "<operation_out><response><resp_code>9999</resp_code>"
                                          "<resp_desc>系统繁忙</resp_desc></response></operation_out>", 200, 1, "")
    assert not err.ok and "9999" in err.error and "系统繁忙" in err.error
    only_content = parse_gateway_response(
        SMS_API, "<operation_out><content><smsList><smsContent>x</smsContent></smsList></content></operation_out>",
        200, 1, "")
    assert only_content.ok and only_content.records == [{"smsContent": "x"}]


def test_xxe_entity_expansion_and_cdata_safety():
    xxe = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        "<operation_out><content><smsList><smsContent>&xxe;</smsContent></smsList></content></operation_out>"
    )
    res_xxe = parse_gateway_response(SMS_API, xxe, 200, 1, "")
    assert not res_xxe.ok and "DOCTYPE" in (res_xxe.error or "")

    billion_laughs = (
        '<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;">]>'
        "<operation_out><content><smsList><smsContent>&lol2;</smsContent></smsList></content></operation_out>"
    )
    res_entity = parse_gateway_response(SMS_API, billion_laughs, 200, 1, "")
    assert not res_entity.ok and "DOCTYPE" in (res_entity.error or "")

    oversized = "<operation_out>" + ("x" * MAX_XML_CHARS) + "</operation_out>"
    res_big = parse_gateway_response(SMS_API, oversized, 200, 1, "")
    assert not res_big.ok and "最大长度" in (res_big.error or "")

    cdata_xml = (
        "<operation_out><response><resp_code>0000</resp_code></response>"
        "<content><smsList><smsContent><![CDATA[<!DOCTYPE html>尊敬的客户您好]]></smsContent></smsList></content>"
        "</operation_out>"
    )
    res_cdata = parse_gateway_response(SMS_API, cdata_xml, 200, 1, "")
    assert res_cdata.ok and res_cdata.records == [{"smsContent": "<!DOCTYPE html>尊敬的客户您好"}]


def test_illegal_control_chars_and_tag_injection_protection():
    req = SMS_API.build_request({
        "手机号码": "13800138000\x00\x07",
        "开始时间": "20260501000000\x1f",
        "结束时间": "20260501235959",
    })
    xml = build_request_xml("querySMSSendInfo", req, "APP", "TOKEN", "java")
    assert "\x00" not in xml and "\x07" not in xml and "\x1f" not in xml
    assert parse_xml(xml).tag == "operation_in"

    dirty_resp = (
        "\ufeff<?xml version='1.0' encoding='UTF-8'?>"
        "<operation_out><response><resp_code>0000</resp_code></response>"
        "<content><smsList><smsContent>测试\x00\x08&#0;&#x07;\n第二行</smsContent></smsList></content></operation_out>"
    )
    parsed = parse_gateway_response(SMS_API, dirty_resp, 200, 1, "")
    assert parsed.ok and parsed.records == [{"smsContent": "测试\n第二行"}]

    with pytest.raises(ValueError, match="非法的 XML 标签名"):
        build_request_xml("querySMSSendInfo", {"content": {"bad><inject": "1"}}, "APP", "TOKEN")

    masked = mask_xml("<operation_in><verify_code>889900</verify_code><msisdn>13912345678</msisdn></operation_in>")
    assert "889900" not in masked and "<verify_code>***</verify_code>" in masked and "139****5678" in masked


def test_xml_namespaces_xsi_nil_empty_records_and_invalid_root():
    ns_xml = (
        '<ns0:operation_out xmlns:ns0="http://cmcc.example/openapi" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<ns0:response><ns0:resp_code>0000</ns0:resp_code></ns0:response>"
        "<ns0:content>"
        '<ns0:smsList><ns0:smsContent>首条短信</ns0:smsContent><ns0:sendPort xsi:nil="true"/></ns0:smsList>'
        "<ns0:smsList/>"
        '<ns0:smsList xsi:nil="true"/>'
        "</ns0:content></ns0:operation_out>"
    )
    res = parse_gateway_response(SMS_API, ns_xml, 200, 1, "")
    assert res.ok and not res.no_data
    assert res.records == [{"smsContent": "首条短信", "sendPort": ""}]

    empty_placeholder = (
        "<operation_out><response><resp_code>0000</resp_code></response>"
        "<content><smsList/></content></operation_out>"
    )
    res_empty = parse_gateway_response(SMS_API, empty_placeholder, 200, 1, "")
    assert res_empty.ok and res_empty.no_data and res_empty.records == []

    html_proxy_err = "<html><body><h1>502 Bad Gateway</h1></body></html>"
    res_html = parse_gateway_response(SMS_API, html_proxy_err, 200, 1, "")
    assert not res_html.ok and "响应根元素异常" in (res_html.error or "")


async def test_unified_gateway_http_status_classification_timeout_and_retry(monkeypatch):
    async def _fast_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

    with pytest.raises(ValueError, match="http://"):
        UnifiedGatewayXmlClient("ftp://gateway.example", "app", "tok")

    args = {"手机号码": "13900001234", "开始时间": "20261105000000", "结束时间": "20261105235959"}

    # 1) 连接超时重试与分类
    timeout_calls = 0

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        nonlocal timeout_calls
        timeout_calls += 1
        raise httpx.ConnectTimeout("connect timed out", request=request)

    gw = UnifiedGatewayXmlClient("http://gw.example", "app", "secret-token")
    gw._client = httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler), follow_redirects=False)
    r_timeout = await gw.invoke(SMS_API, args)
    await gw.aclose()
    assert not r_timeout.ok and "连接超时" in (r_timeout.error or "")
    assert timeout_calls == SMS_API.retry.maxAttempts and r_timeout.attempts == SMS_API.retry.maxAttempts
    assert "secret-token" not in r_timeout.request_preview

    # 2) 302 重定向与 401 鉴权失败不重试且明确分类
    for code, keyword in [(302, "重定向"), (401, "鉴权失败"), (404, "地址不存在")]:
        seen = 0

        def status_handler(request: httpx.Request, status_code: int = code) -> httpx.Response:
            nonlocal seen
            seen += 1
            return httpx.Response(status_code, text="error", headers={"Location": "http://evil.example"})

        gw = UnifiedGatewayXmlClient("http://gw.example", "app", "tok")
        gw._client = httpx.AsyncClient(transport=httpx.MockTransport(status_handler), follow_redirects=False)
        r_status = await gw.invoke(SMS_API, args)
        await gw.aclose()
        assert not r_status.ok and r_status.http_status == code and keyword in (r_status.error or "")
        assert seen == 1

    # 3) 幂等接口遇到 503 自动重试恢复；非幂等接口不重试
    flaky_calls = 0
    ok_xml = "<operation_out><response><resp_code>0000</resp_code></response><content/></operation_out>"

    def flaky_handler(request: httpx.Request) -> httpx.Response:
        nonlocal flaky_calls
        flaky_calls += 1
        if flaky_calls == 1:
            return httpx.Response(503, text="Service Unavailable")
        return httpx.Response(200, text=ok_xml)

    gw = UnifiedGatewayXmlClient("http://gw.example", "app", "tok")
    gw._client = httpx.AsyncClient(transport=httpx.MockTransport(flaky_handler), follow_redirects=False)
    r_recovered = await gw.invoke(SMS_API, args)
    await gw.aclose()
    assert r_recovered.ok and r_recovered.attempts == 2

    non_idem = SMS_API.model_copy(update={"idempotent": False})
    flaky_calls = 0
    gw2 = UnifiedGatewayXmlClient("http://gw.example", "app", "tok")
    gw2._client = httpx.AsyncClient(transport=httpx.MockTransport(flaky_handler), follow_redirects=False)
    r_non_idem = await gw2.invoke(non_idem, args)
    await gw2.aclose()
    assert not r_non_idem.ok and r_non_idem.http_status == 503 and r_non_idem.attempts == 1


async def test_mock_gateway_sandbox_traversal_protection(tmp_path: Path):
    mock_dir = tmp_path / "mock-gateway"
    mock_dir.mkdir()
    secret_xml = tmp_path / "outside.xml"
    secret_xml.write_text("<operation_out><response><resp_code>0000</resp_code></response></operation_out>", "utf-8")

    client = MockGatewayClient(mock_dir)
    bad_name_contract = SMS_API.model_copy(update={"name": "../outside"})
    res1 = await client.invoke(bad_name_contract, {"手机号码": "13900001234", "开始时间": "1", "结束时间": "2"})
    assert not res1.ok and "非法的接口名称" in (res1.error or "")

    res2 = await client.invoke(SMS_API, {"手机号码": "../../outside", "开始时间": "1", "结束时间": "2"})
    assert not res2.ok and "没有找到样例响应" in (res2.error or "")


def test_api_contract_and_resource_loader_resilience(tmp_path: Path):
    bad_api = SMS_API.model_copy(update={
        "input": {"type": "object", "properties": {"手机号码": {"type": "string", "pattern": "[unclosed"}}},
        "request": {"content": {"bad<tag>": "${手机号码}"}},
    })
    errs = bad_api.schema_errors()
    assert any("正则不合法" in e for e in errs) and any("非法的 XML 标签名" in e for e in errs)
    val_errs = bad_api.validate_args({"手机号码": "13900001234"})
    assert val_errs and "Schema" in val_errs[0]

    # 资源目录中存在损坏 YAML 时不崩溃，记入 load_issues
    (tmp_path / "system-prompt.md").write_text("系统提示词", "utf-8")
    (tmp_path / "apis").mkdir()
    (tmp_path / "apis/broken.yaml").write_text("name: [unclosed\n", "utf-8")
    (tmp_path / "apis/querySMSSendInfo.yaml").write_text(
        (SEED_DIR / "apis/querySMSSendInfo.yaml").read_text("utf-8"), "utf-8"
    )
    rs = load_resource_dir(tmp_path)
    assert "querySMSSendInfo" in rs.apis
    assert any(i.code == "LOAD_FAILED" and i.key == "broken" for i in rs.load_issues)


def test_jinja_sandbox_undefined_and_filter_tracking():
    with pytest.raises(SecurityError):
        render_body("{{ ''.__class__.__mro__ }}", {})

    text, used = render_body(
        "业务：{{ 业务名称 | trim }}；未知：{{ 未定义字段 }}{% if 未定义条件 %}不应出现{% endif %}",
        {"业务名称": TrackedValue("  5G套餐  ", "业务名称")},
    )
    assert text == "业务：5G套餐；未知：{{未定义字段}}"
    assert used == {"业务名称", "未定义字段"}

    with pytest.raises(UndefinedError):
        render_body("{{ 未定义字段 }}", {}, strict_undefined=True)

    lines = body_variable_lines("第一行\n{{- 订购短信 | trim -}}\n第三行 {{ 业务名称 }}")
    assert lines == {"订购短信": [2], "业务名称": [3]}


def test_date_range_separated_dates_and_regex_guards():
    assert date_range("2026-1-12 09:05:00", "day") == ("20260112000000", "20260112235959")
    assert date_range("2024/2/5", "month") == ("20240201000000", "20240229235959")
    with pytest.raises(ValueError):
        safe_regex_compile("[unclosed")
    with pytest.raises(ValueError):
        safe_regex_compile("a" * (MAX_REGEX_LENGTH + 1))
    with pytest.raises(ValueError):
        convert_date("20261005", "yyyyMMdd", "纯文字无占位符")
