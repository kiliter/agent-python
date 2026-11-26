"""常规 HTTP 连接器（connector: http）契约、组装脱敏、直连调度、Mock 回放与管理端路由测试。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from report_agent.api.auth import UserStore
from report_agent.domain.api_contract import fixed_params, parse_api_yaml
from report_agent.gateway.http_client import build_http_request_preview, prepare_http_request
from report_agent.gateway.mock import MockGatewayClient
from report_agent.gateway.unified_xml import UnifiedGatewayXmlClient, build_request_preview
from report_agent.main import create_app

HTTP_POST_JSON_YAML = """
name: queryUserOrdersHttp
title: 订单中心常规 HTTP 查询
description: 直连外部订单中心 REST API，不经统一网关信封
connector: http
method: post
url: https://orders.internal.example/api/v1/users/${手机号码}/orders
bodyType: json
timeoutMs: 8000
retry:
  maxAttempts: 2
idempotent: true
headers:
  Authorization: "Bearer secret-token-999"
  X-Api-Key: "key-abc-123"
  X-Trace-Time: "${$now}"
  X-Caller: "report-agent"
query:
  channel: "app"
  api_key: "query-secret-777"
  mobile: "${手机号码}"
input:
  type: object
  required: [手机号码]
  additionalProperties: false
  properties:
    手机号码:
      type: string
      pattern: '^1\\d{10}$'
    起始日期:
      type: string
request:
  mobile: "${手机号码}"
  startDate: "${起始日期}"
  pageSize: 20
  includeDetail: true
response:
  format: auto
  success:
    path: code
    equals: "0"
    missingAs: failure
  noData:
    - path: code
      equals: "4040"
    - path: message
      contains: "无订单"
  records:
    mode: list
    path: data.items
    columns:
      orderId: 订单号
      product.name: 商品名称
      amount: 金额
"""


def test_http_contract_validation_and_fixed_params():
    api = parse_api_yaml(HTTP_POST_JSON_YAML)
    assert api.connector == "http"
    assert api.is_http is True
    assert api.is_json is False
    assert api.method == "POST"
    assert api.bodyType == "json"
    assert api.processCode == ""
    assert api.schema_errors() == []

    # 校验错误覆盖：空 URL、非法协议、URL 控制字符、未声明占位符、受保护头、form/text/json 形态错误
    assert any("url 不能为空" in e for e in api.model_copy(update={"url": ""}).schema_errors())
    assert any("http:// 或 https://" in e for e in api.model_copy(update={"url": "ftp://example.com/a"}).schema_errors())
    assert any("换行或控制字符" in e for e in api.model_copy(update={"url": "https://a.com/x\r\n"}).schema_errors())
    assert any("主机名" in e for e in api.model_copy(update={"url": "https:///only-path"}).schema_errors())

    bad_url_ph = api.model_copy(update={"url": "https://a.com/${未知参数}"})
    assert any("url 引用了未在 input 中声明的参数 ${未知参数}" in e for e in bad_url_ph.schema_errors())

    bad_query_ph = api.model_copy(update={"query": {"q": "${未知查询参数}"}})
    assert any("query 引用了未在 input 中声明的参数 ${未知查询参数}" in e for e in bad_query_ph.schema_errors())

    bad_builtin = api.model_copy(update={"headers": {"X-Bad": "${$unknown}"}})
    assert any("未知的内置占位符 ${$unknown}" in e for e in bad_builtin.schema_errors())

    bad_form = api.model_copy(update={"bodyType": "form", "request": ["not-a-dict"]})
    assert any("bodyType=form" in e for e in bad_form.schema_errors())

    bad_text = api.model_copy(update={"bodyType": "text", "request": {"k": "v"}})
    assert any("bodyType=text" in e for e in bad_text.schema_errors())

    bad_json_key = api.model_copy(update={"bodyType": "json", "request": {"": "bad"}})
    assert any("空的 JSON 键名" in e for e in bad_json_key.schema_errors())

    # fixed_params 对非 dict（如数组/字符串/None）安全返回空列表
    assert fixed_params(["a", "b"]) == []
    assert fixed_params("raw-text") == []
    assert fixed_params(None) == []
    fp = {item["name"]: item["value"] for item in fixed_params(api.request)}
    assert fp["pageSize"] == "20" and fp["includeDetail"] == "true"


def test_http_request_prepare_and_masking_preview():
    api = parse_api_yaml(HTTP_POST_JSON_YAML)

    # 1. 未填完整参数时的脱敏预览：保留 ${手机号码} / ${起始日期}，屏蔽凭证头与敏感 query
    preview_unfilled = build_request_preview(api, {})
    assert preview_unfilled.startswith("POST https://orders.internal.example/api/v1/users/${手机号码}/orders?")
    assert "api_key=***" in preview_unfilled
    assert "Authorization: ***" in preview_unfilled
    assert "X-Api-Key: ***" in preview_unfilled
    assert "secret-token-999" not in preview_unfilled
    assert "key-abc-123" not in preview_unfilled
    assert "query-secret-777" not in preview_unfilled
    assert "X-Caller: report-agent" in preview_unfilled
    assert '"startDate": "${起始日期}"' in preview_unfilled

    # 2. 真实组装：请求发出真实凭证与编码 URL，预览脱敏凭证与手机号
    prepared = prepare_http_request(api, {"手机号码": "13800138000", "起始日期": "20261101"})
    assert prepared.method == "POST"
    assert prepared.url.startswith("https://orders.internal.example/api/v1/users/13800138000/orders?")
    assert "channel=app" in prepared.url
    assert "api_key=query-secret-777" in prepared.url
    assert prepared.headers["Authorization"] == "Bearer secret-token-999"
    assert prepared.headers["X-Api-Key"] == "key-abc-123"
    assert prepared.headers["Content-Type"] == "application/json; charset=utf-8"
    assert prepared.payload_bytes is not None
    sent_body = json.loads(prepared.payload_bytes.decode("utf-8"))
    assert sent_body["mobile"] == "13800138000"
    assert sent_body["startDate"] == "20261101"

    # 预览文本彻底屏蔽敏感信息
    assert "secret-token-999" not in prepared.preview
    assert "key-abc-123" not in prepared.preview
    assert "query-secret-777" not in prepared.preview
    assert "138****8000" in prepared.preview
    assert build_http_request_preview(api, {"手机号码": "13912345678"}).count("139****5678") >= 2


async def test_http_live_dispatch_json_retry_form_xml_text_and_204(monkeypatch):
    async def _fast_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

    # 1. POST JSON 直连目标地址 + 503 幂等重试 + JSON 嵌套点分列抽取
    api_json = parse_api_yaml(HTTP_POST_JSON_YAML)
    captured: list[httpx.Request] = []

    def handler_json(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if len(captured) == 1:
            return httpx.Response(503, text="service busy")
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json; charset=utf-8"},
            json={
                "code": 0,
                "data": {
                    "items": [
                        {"orderId": "ORD-9001", "product": {"name": "千兆宽带"}, "amount": 199},
                    ]
                },
            },
        )

    gw = UnifiedGatewayXmlClient("http://unused-gateway.internal", "APP", "TOK")
    gw._client = httpx.AsyncClient(transport=httpx.MockTransport(handler_json), follow_redirects=False)
    res = await gw.invoke(api_json, {"手机号码": "13900001234", "起始日期": "20261101"})
    await gw.aclose()

    assert res.ok and not res.no_data and res.attempts == 2 and res.http_status == 200
    assert len(captured) == 2
    assert str(captured[0].url).startswith("https://orders.internal.example/api/v1/users/13900001234/orders?")
    assert "/openapi_3" not in str(captured[0].url)
    assert captured[0].headers["authorization"] == "Bearer secret-token-999"
    assert res.records == [{"orderId": "ORD-9001", "product": '{"name":"千兆宽带"}', "amount": "199", "product.name": "千兆宽带"}]

    # 2. GET + bodyType=none + Query + JSON 根对象直出
    api_get = parse_api_yaml("""
name: getProfileHttp
title: 获取用户画像
connector: http
method: GET
url: https://crm.internal.example/profile
bodyType: none
query:
  uid: "${用户ID}"
input:
  type: object
  required: [用户ID]
  properties:
    用户ID: { type: string }
response:
  records:
    mode: object
    path: ""
    columns:
      name: 姓名
      tier: 等级
""")
    seen_get: list[httpx.Request] = []

    def handler_get(request: httpx.Request) -> httpx.Response:
        seen_get.append(request)
        return httpx.Response(200, json={"name": "张三", "tier": "VIP"})

    gw2 = UnifiedGatewayXmlClient("http://unused-gateway.internal", "APP", "TOK")
    gw2._client = httpx.AsyncClient(transport=httpx.MockTransport(handler_get), follow_redirects=False)
    res_get = await gw2.invoke(api_get, {"用户ID": "u-100"})
    await gw2.aclose()

    assert res_get.ok and res_get.records == [{"name": "张三", "tier": "VIP"}]
    assert seen_get[0].method == "GET" and str(seen_get[0].url) == "https://crm.internal.example/profile?uid=u-100"
    assert seen_get[0].content == b""

    # 3. PUT Form 表单请求 + XML 响应解析
    api_form_xml = parse_api_yaml("""
name: updateFlagHttp
title: 表单提交返回 XML
connector: http
method: PUT
url: https://legacy.internal.example/flag
bodyType: form
input:
  type: object
  required: [号码]
  properties:
    号码: { type: string }
request:
  mobile: "${号码}"
  action: "query"
response:
  format: xml
  success:
    path: resp.code
    equals: "200"
  records:
    path: resp.item
    columns:
      flag: 标识
""")
    seen_put: list[httpx.Request] = []

    def handler_put(request: httpx.Request) -> httpx.Response:
        seen_put.append(request)
        return httpx.Response(200, headers={"Content-Type": "application/xml"}, text="<resp><code>200</code><item><flag>ACTIVE</flag></item></resp>")

    gw3 = UnifiedGatewayXmlClient("http://unused-gateway.internal", "APP", "TOK")
    gw3._client = httpx.AsyncClient(transport=httpx.MockTransport(handler_put), follow_redirects=False)
    res_put = await gw3.invoke(api_form_xml, {"号码": "13800138000"})
    await gw3.aclose()

    assert res_put.ok and res_put.records == [{"flag": "ACTIVE"}]
    assert seen_put[0].method == "PUT"
    assert "application/x-www-form-urlencoded" in seen_put[0].headers["content-type"]
    assert "mobile=13800138000" in seen_put[0].content.decode("utf-8")

    # 4. POST 纯文本请求 + 纯文本响应 & HTTP 204 空响应
    api_text = parse_api_yaml("""
name: echoTextHttp
title: 纯文本接口
connector: http
method: POST
url: https://text.internal.example/echo
bodyType: text
input:
  type: object
  required: [内容]
  properties:
    内容: { type: string }
request: "HELLO:${内容}"
response:
  format: text
  noData:
    - path: ""
      contains: "EMPTY_RESULT"
  records:
    mode: scalar
    path: ""
""")

    def handler_text(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        if "empty" in body:
            return httpx.Response(200, headers={"Content-Type": "text/plain"}, text="EMPTY_RESULT")
        if "204" in body:
            return httpx.Response(204)
        return httpx.Response(200, headers={"Content-Type": "text/plain"}, text=f"ACK:{body}")

    gw4 = UnifiedGatewayXmlClient("http://unused-gateway.internal", "APP", "TOK")
    gw4._client = httpx.AsyncClient(transport=httpx.MockTransport(handler_text), follow_redirects=False)
    r_ok = await gw4.invoke(api_text, {"内容": "world"})
    r_nd = await gw4.invoke(api_text, {"内容": "empty"})
    r_204 = await gw4.invoke(api_text, {"内容": "204"})
    await gw4.aclose()

    assert r_ok.ok and r_ok.records == [{"value": "ACK:HELLO:world"}] and r_ok.raw == "ACK:HELLO:world"
    assert r_nd.ok and r_nd.no_data and r_nd.records == []
    assert r_204.ok and r_204.no_data and r_204.http_status == 204 and r_204.records == []

    # 5. 3xx 重定向不被跟随且报明确错误
    gw5 = UnifiedGatewayXmlClient("http://unused-gateway.internal", "APP", "TOK")
    gw5._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _req: httpx.Response(302, headers={"Location": "https://other.example"})),
        follow_redirects=False,
    )
    r_redir = await gw5.invoke(api_get, {"用户ID": "u-1"})
    await gw5.aclose()
    assert not r_redir.ok and r_redir.http_status == 302 and "重定向" in (r_redir.error or "")


async def test_http_mock_gateway_lookup(tmp_path: Path):
    api = parse_api_yaml(HTTP_POST_JSON_YAML)
    (tmp_path / "queryUserOrdersHttp.json").write_text(
        json.dumps({"code": 0, "data": {"items": [{"orderId": "M-1", "product": {"name": "默认套餐"}, "amount": 50}]}}),
        encoding="utf-8",
    )
    (tmp_path / "queryUserOrdersHttp.13900000000.json").write_text(
        json.dumps({"code": 4040, "message": "查无订单"}),
        encoding="utf-8",
    )
    mock = MockGatewayClient(tmp_path)

    r_default = await mock.invoke(api, {"手机号码": "13800138000"})
    assert r_default.ok and not r_default.no_data
    assert r_default.records[0]["orderId"] == "M-1"
    assert r_default.records[0]["product.name"] == "默认套餐"
    assert "Authorization: ***" in r_default.request_preview

    r_nodata = await mock.invoke(api, {"手机号码": "13900000000"})
    assert r_nodata.ok and r_nodata.no_data and r_nodata.records == []

    r_miss = await mock.invoke(api.model_copy(update={"name": "missingHttpApi"}), {"手机号码": "13800138000"})
    assert not r_miss.ok and "missingHttpApi" in (r_miss.error or "")


@pytest.fixture
def client(container):
    UserStore(container.layout.config / "users.yaml").upsert("chenxiaoyun", "pass-1234", "陈晓芸", "业务维护")
    app = create_app(container=container)
    with TestClient(app) as cl:
        yield cl


def _login(client: TestClient) -> dict[str, str]:
    r = client.post("/api/v1/auth/login", json={"username": "chenxiaoyun", "password": "pass-1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_http_api_routes_create_patch_validate_test_call_and_publish(client: TestClient, container):
    h = _login(client)

    # 1. 创建常规 HTTP 接口
    r_create = client.post(
        "/api/v1/apis",
        headers=h,
        json={
            "name": "queryExtOrderHttp",
            "title": "外部订单 HTTP 查询",
            "description": "直连外部订单系统",
            "connector": "http",
            "method": "POST",
            "url": "https://ext.example.com/api/orders",
        },
    )
    assert r_create.status_code == 200, r_create.text
    item = r_create.json()
    assert item["connector"] == "http"
    assert item["format"] == "HTTP"
    assert item["type"] == "常规 HTTP"
    assert item["method"] == "POST"
    assert item["url"] == "https://ext.example.com/api/orders"
    assert item["bodyType"] == "json"

    # 2. 局部草稿更新 method / url / headers / query
    r_patch = client.put(
        "/api/v1/apis/queryExtOrderHttp/draft",
        headers=h,
        json={
            "api": {
                "method": "GET",
                "bodyType": "none",
                "url": "https://ext.example.com/api/v2/orders",
                "headers": {"Authorization": "Bearer secret-123"},
                "query": {"scene": "audit"},
            }
        },
    )
    assert r_patch.status_code == 200, r_patch.text

    # 3. 校验预览接口：返回 format="http" 且脱敏 Authorization
    r_val = client.post("/api/v1/apis/queryExtOrderHttp/validate", headers=h, json={})
    assert r_val.status_code == 200, r_val.text
    val = r_val.json()
    assert val["ok"] is True and val["connector"] == "http" and val["format"] == "http"
    assert val["requestPreview"].startswith("GET https://ext.example.com/api/v2/orders?scene=audit")
    assert "Authorization: ***" in val["requestPreview"]
    assert "secret-123" not in val["requestPreview"]

    # 4. 非法 URL 校验返回 ok=False
    bad_yaml = yaml.safe_dump(
        {
            "name": "queryExtOrderHttp",
            "connector": "http",
            "method": "GET",
            "url": "ftp://invalid.example.com/orders",
        },
        allow_unicode=True,
    )
    r_bad = client.post("/api/v1/apis/queryExtOrderHttp/validate", headers=h, json={"yamlText": bad_yaml})
    assert r_bad.status_code == 200
    assert r_bad.json()["ok"] is False and r_bad.json()["connector"] == "http"

    # 5. 放置 Mock 响应并执行试调用 + 发布上线
    (container.layout.mock_gateway / "queryExtOrderHttp.json").write_text(
        json.dumps({"list": [{"orderId": "EXT-1", "status": "PAID"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    r_call = client.post("/api/v1/apis/queryExtOrderHttp/test-call", headers=h, json={"params": {}})
    assert r_call.status_code == 200, r_call.text
    call_res = r_call.json()
    assert call_res["ok"] is True
    assert call_res["connector"] == "http"
    assert call_res["format"] == "json"
    assert call_res["records"] == [{"row": 0, "orderId": "EXT-1", "status": "PAID"}]
    assert "Authorization: ***" in call_res["requestBody"]
    assert "EXT-1" in call_res["rawBody"]

    r_pub = client.post("/api/v1/apis/queryExtOrderHttp/publish", headers=h, json={"note": "发布常规 HTTP 接口"})
    assert r_pub.status_code == 200, r_pub.text
    assert r_pub.json()["item"]["status"] == "PUBLISHED"
    assert r_pub.json()["item"]["connector"] == "http"


def test_summary_max_preview_chars_unlimited_and_result_desc():
    from pydantic import ValidationError

    from report_agent.gateway.base import extract_json_records
    from report_agent.runtime.tools import _format_api_success_payload
    from report_agent.runtime.workspace import ApiResult

    api = parse_api_yaml("""
name: queryPdfTextHttp
title: 查询单据正文
connector: http
method: POST
url: https://pdf.internal.example/query-pdf-text
bodyType: json
response:
  format: json
  success:
    path: resultCode
    equals: "0"
    missingAs: failure
  records:
    mode: scalar
    path: pdfText
    columns:
      value: PDF 正文
  summary:
    maxPreviewChars: -1
""")
    assert api.response.summary.maxPreviewChars == -1

    # 非法值（0 与 -2）被拒绝
    for bad_val in (0, -2):
        with pytest.raises(ValidationError, match="maxPreviewChars"):
            parse_api_yaml(f"""
name: badSummaryHttp
connector: http
url: https://pdf.internal.example/a
response:
  summary:
    maxPreviewChars: {bad_val}
""")

    # 成功返回单条超长 pdfText，maxPreviewChars=-1 时完整保留不截断，且 note 提示未截断
    long_text = "单据正文段落-" * 1000
    ok_res = extract_json_records(
        api,
        {"resultCode": "0", "resultDesc": "查询成功", "caseNo": "C001", "pdfText": long_text},
    )
    assert ok_res.ok and ok_res.records == [{"value": long_text}]

    ws_res = ApiResult(
        result_id="r1",
        api="queryPdfTextHttp",
        title="查询单据正文",
        args={},
        records=ok_res.records,
        columns=api.response.records.columns,
        ok=True,
        error=None,
        cost_ms=12,
    )
    payload = _format_api_success_payload(api, ws_res, default_preview_rows=5)
    assert payload["preview"] == [{"value": long_text, "row": 0}]
    assert "未截断" in payload["note"]

    # 行数超过预览行数时仍提示使用 query_result
    ws_multi = ApiResult(
        result_id="r2",
        api="queryPdfTextHttp",
        title="查询单据正文",
        args={},
        records=[{"value": "row0"}, {"value": "row1"}],
        columns=api.response.records.columns,
        ok=True,
        error=None,
        cost_ms=10,
    )
    payload_multi = _format_api_success_payload(api, ws_multi, default_preview_rows=1)
    assert len(payload_multi["preview"]) == 1
    assert "query_result" in payload_multi["note"]

    # 业务失败时自动提取 resultDesc 作为报错说明
    fail_res = extract_json_records(
        api,
        {"resultCode": "1", "resultDesc": "查询参数不合法", "caseNo": "", "pdfText": ""},
    )
    assert not fail_res.ok and fail_res.error == "业务返回码 1：查询参数不合法"
