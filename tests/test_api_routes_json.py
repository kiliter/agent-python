"""双协议（XML / JSON）API 管理路由、DTO、在线校验预览与试调用测试。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import json

import pytest
import yaml
from fastapi.testclient import TestClient

from report_agent.api.auth import UserStore
from report_agent.main import create_app


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


def test_api_list_and_create_dual_protocol_dtos(client: TestClient):
    # 未登录访问新增 validate 端点应返回 401
    assert client.post("/api/v1/apis/querySMSSendInfo/validate", json={}).status_code == 401

    h = _login(client)

    # 1. 存量接口默认返回 XML 协议字段与完整兼容结构
    apis = client.get("/api/v1/apis", headers=h).json()
    sms_api = next(a for a in apis if a["name"] == "querySMSSendInfo")
    assert sms_api["connector"] == "unified-gateway-xml"
    assert sms_api["format"] == "XML"
    assert sms_api["type"] == "统一网关 XML"
    assert sms_api["headers"] == {}
    assert sms_api["idempotent"] is True

    # 2. 通过 connector="unified-gateway-json" 新建 JSON 接口
    r_json = client.post(
        "/api/v1/apis",
        headers=h,
        json={
            "name": "queryOrderJson",
            "title": "订单办理JSON查询",
            "description": "按手机号查询订单记录（JSON 协议）",
            "processCode": "qryOrderJsonV1",
            "connector": "unified-gateway-json",
        },
    )
    assert r_json.status_code == 200, r_json.text
    order_item = r_json.json()
    assert order_item["name"] == "queryOrderJson"
    assert order_item["connector"] == "unified-gateway-json"
    assert order_item["format"] == "JSON"
    assert order_item["type"] == "统一网关 JSON"
    assert order_item["processCode"] == "qryOrderJsonV1"
    assert order_item["headers"] == {}
    assert order_item["idempotent"] is True
    assert order_item["status"] == "DRAFT"

    detail = client.get("/api/v1/apis/queryOrderJson", headers=h).json()
    parsed_yaml = yaml.safe_load(detail["yamlText"])
    assert parsed_yaml["connector"] == "unified-gateway-json"
    assert parsed_yaml["processCode"] == "qryOrderJsonV1"

    # 3. 通过可选 format="JSON" 参数新建 JSON 接口
    r_fmt = client.post(
        "/api/v1/apis",
        headers=h,
        json={"name": "queryBillJson", "title": "账单JSON查询", "format": "JSON"},
    )
    assert r_fmt.status_code == 200, r_fmt.text
    assert r_fmt.json()["connector"] == "unified-gateway-json"
    assert r_fmt.json()["format"] == "JSON"
    assert r_fmt.json()["type"] == "统一网关 JSON"

    # 4. 局部草稿更新 headers / idempotent / processCode 并发布上线
    r_patch = client.put(
        "/api/v1/apis/queryOrderJson/draft",
        headers=h,
        json={
            "api": {
                "title": "订单办理JSON查询（升级）",
                "headers": {"X-Channel": "eshop", "X-Scene": "audit"},
                "idempotent": False,
            }
        },
    )
    assert r_patch.status_code == 200, r_patch.text
    updated_item = client.get("/api/v1/apis/queryOrderJson", headers=h).json()["item"]
    assert updated_item["title"] == "订单办理JSON查询（升级）"
    assert updated_item["headers"] == {"X-Channel": "eshop", "X-Scene": "audit"}
    assert updated_item["idempotent"] is False

    r_pub = client.post("/api/v1/apis/queryOrderJson/publish", headers=h, json={"note": "上线 JSON 订单接口"})
    assert r_pub.status_code == 200, r_pub.text
    assert r_pub.json()["item"]["status"] == "PUBLISHED"
    assert r_pub.json()["item"]["connector"] == "unified-gateway-json"
    assert r_pub.json()["item"]["format"] == "JSON"


def test_api_validate_endpoint_preview_and_live_error_handling(client: TestClient):
    h = _login(client)

    # 新建一个 JSON 接口用于工作副本校验
    client.post(
        "/api/v1/apis",
        headers=h,
        json={"name": "validateDemoJson", "title": "校验演示接口", "connector": "unified-gateway-json"},
    )

    # 1. 不传 sampleParams 时，保留 ${手机号码} 占位符并脱敏鉴权字段
    r_unfilled = client.post("/api/v1/apis/validateDemoJson/validate", headers=h, json={})
    assert r_unfilled.status_code == 200, r_unfilled.text
    v1 = r_unfilled.json()
    assert v1["ok"] is True and v1["errors"] == []
    assert v1["connector"] == "unified-gateway-json" and v1["format"] == "json"
    preview_doc = json.loads(v1["requestPreview"])
    assert preview_doc["operation_in"]["process_code"] == "validateDemoJson"
    assert preview_doc["operation_in"]["app_id"] == "***"
    assert preview_doc["operation_in"]["access_token"] == "***"
    assert preview_doc["operation_in"]["route_value"] == "${手机号码}"
    assert preview_doc["operation_in"]["content"]["userMobile"] == "${手机号码}"

    # 2. 传入 sampleParams 时，替换参数并对手机号中间 4 位脱敏
    r_filled = client.post(
        "/api/v1/apis/validateDemoJson/validate",
        headers=h,
        json={"sampleParams": {"手机号码": "13912345678"}},
    )
    assert r_filled.status_code == 200
    v2 = r_filled.json()
    assert v2["ok"] is True
    preview_filled = json.loads(v2["requestPreview"])
    assert preview_filled["operation_in"]["route_value"] == "139****5678"
    assert preview_filled["operation_in"]["content"]["userMobile"] == "139****5678"

    # 3. 存量 XML 接口校验与 XML 预览
    r_xml = client.post(
        "/api/v1/apis/querySMSSendInfo/validate",
        headers=h,
        json={"sampleParams": {"手机号码": "13900001234"}},
    )
    assert r_xml.status_code == 200
    vx = r_xml.json()
    assert vx["ok"] is True and vx["format"] == "xml" and vx["connector"] == "unified-gateway-xml"
    assert "<operation_in>" in vx["requestPreview"]
    assert "<app_id>***</app_id>" in vx["requestPreview"]
    assert "139****1234" in vx["requestPreview"]

    # 4. YAML 语法错误、Pydantic 字段错误、name 不一致、未声明占位符、受保护请求头均返回 HTTP 200 + ok=False
    r_syntax = client.post(
        "/api/v1/apis/validateDemoJson/validate",
        headers=h,
        json={"yamlText": "connector: unified-gateway-json\nname: [unclosed"},
    )
    assert r_syntax.status_code == 200
    assert r_syntax.json()["ok"] is False
    assert r_syntax.json()["format"] == "json"
    assert r_syntax.json()["errors"]

    r_pydantic = client.post(
        "/api/v1/apis/validateDemoJson/validate",
        headers=h,
        json={"yamlText": "name: validateDemoJson\nconnector: invalid-conn\nprocessCode: p1\nresponse:\n  records:\n    path: a.b\n"},
    )
    assert r_pydantic.status_code == 200
    assert r_pydantic.json()["ok"] is False and r_pydantic.json()["errors"]

    base_yaml = client.get("/api/v1/apis/validateDemoJson", headers=h).json()["yamlText"]
    r_mismatch = client.post(
        "/api/v1/apis/validateDemoJson/validate",
        headers=h,
        json={"yamlText": base_yaml.replace("name: validateDemoJson", "name: anotherName", 1)},
    )
    assert r_mismatch.status_code == 200
    assert r_mismatch.json()["ok"] is False
    assert any("必须与接口编码 validateDemoJson 一致" in e for e in r_mismatch.json()["errors"])

    bad_contract = yaml.safe_load(base_yaml)
    bad_contract["headers"] = {"Host": "evil.example.com", "X-Trace": "${未声明参数}"}
    r_header_err = client.post(
        "/api/v1/apis/validateDemoJson/validate",
        headers=h,
        json={"yamlText": yaml.safe_dump(bad_contract, allow_unicode=True, sort_keys=False)},
    )
    assert r_header_err.status_code == 200
    assert r_header_err.json()["ok"] is False
    assert len(r_header_err.json()["errors"]) >= 2

    # 5. 接口不存在（未传 yamlText）返回 404，非法接口名返回 400
    assert client.post("/api/v1/apis/noSuchApi/validate", headers=h, json={}).status_code == 404
    assert client.post("/api/v1/apis/123bad/validate", headers=h, json={}).status_code == 400


def test_api_test_call_json_mock_and_xml_fallback(client: TestClient, container):
    h = _login(client)

    # 1. 新建原生 JSON 接口并写入 .json mock 样例响应文件
    r_create = client.post(
        "/api/v1/apis",
        headers=h,
        json={
            "name": "queryPackageJson",
            "title": "套餐办理JSON查询",
            "processCode": "qryPkgJson",
            "connector": "unified-gateway-json",
        },
    )
    assert r_create.status_code == 200
    detail = client.get("/api/v1/apis/queryPackageJson", headers=h).json()
    contract_doc = yaml.safe_load(detail["yamlText"])
    contract_doc["headers"] = {"X-App-Scene": "complaint-audit"}
    contract_doc["response"]["records"]["columns"] = {"pkgCode": "套餐编码", "pkgName": "套餐名称"}
    client.put(
        "/api/v1/apis/queryPackageJson/draft",
        headers=h,
        json={"yamlText": yaml.safe_dump(contract_doc, allow_unicode=True, sort_keys=False)},
    )

    mock_json_payload = {
        "operation_out": {
            "response": {"resp_code": "0000", "resp_desc": "success"},
            "content": {
                "list": [
                    {"pkgCode": "PKG-5G-129", "pkgName": "5G智享套餐129元档"},
                    {"pkgCode": "PKG-DATA-10G", "pkgName": "10GB流量加油包"},
                ]
            },
        }
    }
    (container.layout.mock_gateway / "queryPackageJson.json").write_text(
        json.dumps(mock_json_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    r_call = client.post(
        "/api/v1/apis/queryPackageJson/test-call",
        headers=h,
        json={"params": {"手机号码": "13900001234"}},
    )
    assert r_call.status_code == 200, r_call.text
    res_json = r_call.json()
    assert res_json["ok"] is True
    assert res_json["format"] == "json"
    assert res_json["connector"] == "unified-gateway-json"
    assert res_json["rawBody"] == res_json["rawXml"]
    assert res_json["requestBody"] == res_json["requestXml"]
    assert json.loads(res_json["requestBody"])["operation_in"]["route_value"] == "139****1234"
    assert json.loads(res_json["rawBody"])["operation_out"]["response"]["resp_code"] == "0000"
    assert len(res_json["records"]) == 2
    assert res_json["records"][0]["pkgName"] == "5G智享套餐129元档"
    assert res_json["columns"] == {"pkgCode": "套餐编码", "pkgName": "套餐名称"}

    # 2. 将存量 XML 接口通过 yamlText 临时切为 unified-gateway-json 试调用（触发同名 .xml 自动转 JSON）
    sms_yaml = client.get("/api/v1/apis/querySMSSendInfo", headers=h).json()["yamlText"]
    sms_as_json = sms_yaml.replace("connector: unified-gateway-xml", "connector: unified-gateway-json", 1)
    r_fallback = client.post(
        "/api/v1/apis/querySMSSendInfo/test-call",
        headers=h,
        json={
            "params": {"手机号码": "13900001234", "开始时间": "20261105000000", "结束时间": "20261105235959"},
            "yamlText": sms_as_json,
        },
    )
    assert r_fallback.status_code == 200, r_fallback.text
    fb = r_fallback.json()
    assert fb["ok"] is True
    assert fb["format"] == "json"
    assert fb["connector"] == "unified-gateway-json"
    assert len(fb["records"]) == 5
    assert json.loads(fb["requestBody"])["operation_in"]["process_code"] == "querySMSSendInfo"

    # 3. 原生 XML 接口试调用仍返回 format="xml" 且双字段完全对齐
    r_xml_call = client.post(
        "/api/v1/apis/querySMSSendInfo/test-call",
        headers=h,
        json={"params": {"手机号码": "13900001234", "开始时间": "20261105000000", "结束时间": "20261105235959"}},
    )
    assert r_xml_call.status_code == 200
    xc = r_xml_call.json()
    assert xc["ok"] is True
    assert xc["format"] == "xml" and xc["connector"] == "unified-gateway-xml"
    assert xc["rawBody"] == xc["rawXml"] and "<operation_out>" in xc["rawBody"]
    assert xc["requestBody"] == xc["requestXml"] and "<operation_in>" in xc["requestBody"]


def test_non_mapping_yaml_draft_and_corrupted_working_copy_handling(client: TestClient, container):
    from report_agent.store.service import api_ref

    h = _login(client)

    # 1. PUT /apis/{name}/draft 提交合法但顶层非映射对象的 YAML（标量/列表）时返回 400 而非 500
    for non_map_yaml in ("123", "[1, 2]", "hello"):
        r_bad = client.put(
            "/api/v1/apis/querySMSSendInfo/draft",
            headers=h,
            json={"yamlText": non_map_yaml},
        )
        assert r_bad.status_code == 400, f"{non_map_yaml!r} -> {r_bad.status_code}: {r_bad.text}"
        assert "映射" in r_bad.json()["message"] or "YAML" in r_bad.json()["message"]

    # 2. 磁盘上若已存在非映射 YAML 损坏草稿：详情/列表安全回退至线上版本（200），试调用/发布返回 400
    container.drafts.write(api_ref("querySMSSendInfo"), {"querySMSSendInfo.yaml": "[1, 2]"}, "tester", base_rev="r1")
    assert client.get("/api/v1/apis", headers=h).status_code == 200
    assert client.get("/api/v1/skills", headers=h).status_code == 200
    detail = client.get("/api/v1/apis/querySMSSendInfo", headers=h)
    assert detail.status_code == 200
    assert detail.json()["item"]["name"] == "querySMSSendInfo"

    r_tc = client.post(
        "/api/v1/apis/querySMSSendInfo/test-call",
        headers=h,
        json={"params": {"手机号码": "13900001234"}},
    )
    assert r_tc.status_code == 400

    r_pub = client.post("/api/v1/apis/querySMSSendInfo/publish", headers=h, json={"note": "bad"})
    assert r_pub.status_code in (400, 422)

