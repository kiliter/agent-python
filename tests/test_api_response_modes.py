"""接口契约非数组响应模式（auto / object / list / scalar / none）、根路径与嵌套展平测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from report_agent.config import Settings
from fixture_paths import SEED_DIR
from report_agent.domain.api_contract import ApiContract, RecordsSpec, parse_api_yaml
from report_agent.domain.resources import ResourceSet, load_resource_dir
from report_agent.domain.template import FieldDef, Template, TemplateDef
from report_agent.gateway.base import ApiCallResult, extract_json_records, extract_records, parse_json_body, parse_xml
from report_agent.runtime.deps import RunDeps
from report_agent.runtime.evidence import EvidenceChecker
from report_agent.runtime.tools import call_api, query_result
from report_agent.runtime.workspace import EventSink, Workspace


class _StubGateway:
    def __init__(self, result: ApiCallResult) -> None:
        self._result = result

    async def invoke(self, contract: ApiContract, args: dict) -> ApiCallResult:
        return self._result

    async def aclose(self) -> None:
        return None


def _make_ctx(deps: RunDeps) -> RunContext[RunDeps]:
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage(), prompt="", retry=0, max_retries=1)


def test_records_spec_defaults_and_backward_compatibility():
    # 默认 RecordsSpec：mode="auto", path="operation_out.content", flatten=False
    default_spec = RecordsSpec()
    assert default_spec.mode == "auto"
    assert default_spec.path == "operation_out.content"
    assert default_spec.flatten is False
    assert default_spec.columns == {}

    # 省略 records 或省略 response 均可正常解析
    minimal = parse_api_yaml(
        """
name: pingGateway
processCode: pingGateway
"""
    )
    assert minimal.response.records.mode == "auto"
    assert minimal.response.records.path == "operation_out.content"
    assert minimal.schema_errors() == []

    no_records_key = parse_api_yaml(
        """
name: submitOrder
processCode: submitOrder
response:
  success:
    path: operation_out.response.resp_code
    equals: "0000"
"""
    )
    assert no_records_key.response.records.mode == "auto"
    assert no_records_key.response.records.path == "operation_out.content"

    # 允许 path 为空串或 YAML null
    empty_path = parse_api_yaml(
        """
name: rootObjApi
connector: unified-gateway-json
processCode: rootObjApi
response:
  records:
    mode: object
    path: ""
    columns:
      custName: 客户姓名
"""
    )
    assert empty_path.response.records.path == ""
    assert empty_path.schema_errors() == []

    null_fields = parse_api_yaml(
        """
name: nullFieldsApi
processCode: nullFieldsApi
response:
  noData:
  records:
    mode: none
    path:
    columns:
"""
    )
    assert null_fields.response.records.mode == "none"
    assert null_fields.response.records.path == ""
    assert null_fields.response.records.columns == {}

    # 非法 mode 触发校验异常
    with pytest.raises(ValidationError):
        parse_api_yaml(
            """
name: invalidModeApi
processCode: invalidModeApi
response:
  records:
    mode: unsupported_mode
"""
        )

    # 存量种子契约保持 100% 兼容
    sms_api = parse_api_yaml((SEED_DIR / "apis/querySMSSendInfo.yaml").read_text(encoding="utf-8"))
    assert sms_api.response.records.mode == "auto"
    assert sms_api.response.records.path == "operation_out.content.smsList"
    assert sms_api.response.records.flatten is False


async def test_mode_none_xml_json_and_call_api_note(tmp_path):
    xml_none_api = parse_api_yaml(
        """
name: auditNotifyXml
title: 稽核通知下发
connector: unified-gateway-xml
processCode: auditNotify
response:
  success:
    path: result.code
    equals: "0"
    missingAs: failure
  noData:
    - path: result.code
      equals: "204"
  records:
    mode: none
"""
    )
    # 自定义根标签 <result> 在 mode=none 下不因默认 operation_out.content 报错，且 no_data=False
    res_xml_ok = extract_records(xml_none_api, parse_xml("<result><code>0</code><msg>accepted</msg></result>"))
    assert res_xml_ok.ok is True
    assert res_xml_ok.records == []
    assert res_xml_ok.no_data is False

    res_xml_nodata = extract_records(xml_none_api, parse_xml("<result><code>204</code></result>"))
    assert res_xml_nodata.ok is True
    assert res_xml_nodata.records == []
    assert res_xml_nodata.no_data is True

    res_xml_fail = extract_records(xml_none_api, parse_xml("<result><code>500</code><msg>系统异常</msg></result>"))
    assert res_xml_fail.ok is False
    assert "500" in (res_xml_fail.error or "") and "系统异常" in (res_xml_fail.error or "")

    json_none_api = xml_none_api.model_copy(update={"connector": "unified-gateway-json"})
    res_json_ok = extract_json_records(json_none_api, {"result": {"code": "0"}})
    assert res_json_ok.ok is True and res_json_ok.records == [] and res_json_ok.no_data is False

    res_json_err = extract_json_records(json_none_api, {"result": {"code": "403", "message": "无权限"}})
    assert res_json_err.ok is False and res_json_err.error == "业务返回码 403：无权限"

    # 验证 tools.call_api 在 mode="none" 时的 note 语义
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", llm_api_key="test")
    rs = load_resource_dir(SEED_DIR)
    rs.apis["auditNotifyXml"] = xml_none_api
    tpl = next(iter(rs.templates.values()))

    ws_ok = Workspace()
    deps_ok = RunDeps(
        run_id="run_none_ok",
        rev="test",
        settings=settings,
        resources=rs,
        template=tpl,
        allowed_skills=[],
        allowed_apis=["auditNotifyXml"],
        inputs={},
        document="",
        gateway=_StubGateway(res_xml_ok),
        workspace=ws_ok,
        events=EventSink(),
    )
    out_ok = await call_api(_make_ctx(deps_ok), "auditNotifyXml", {})
    assert out_ok["ok"] is True
    assert out_ok["count"] == 0
    assert out_ok["note"] == "接口调用成功（该契约声明无业务记录体）"

    # 当命中 noData 规则时，仍返回 "没有记录"
    ws_nd = Workspace()
    deps_nd = RunDeps(
        run_id="run_none_nd",
        rev="test",
        settings=settings,
        resources=rs,
        template=tpl,
        allowed_skills=[],
        allowed_apis=["auditNotifyXml"],
        inputs={},
        document="",
        gateway=_StubGateway(res_xml_nodata),
        workspace=ws_nd,
        events=EventSink(),
    )
    out_nd = await call_api(_make_ctx(deps_nd), "auditNotifyXml", {})
    assert out_nd["ok"] is True
    assert out_nd["note"] == "没有记录"


def test_mode_scalar_preserves_falsy_values_and_root_scalars():
    json_scalar_api = parse_api_yaml(
        """
name: checkFlagJson
connector: unified-gateway-json
processCode: checkFlag
response:
  success:
    path: operation_out.response.resp_code
    equals: "0000"
  records:
    mode: scalar
    path: operation_out.content.flag
    columns:
      value: 校验结果
"""
    )
    for raw_val, expected_str in [(False, "false"), (0, "0"), ("false", "false"), ("0", "0"), (True, "true"), (99.5, "99.5")]:
        payload = {"operation_out": {"response": {"resp_code": "0000"}, "content": {"flag": raw_val}}}
        res = extract_json_records(json_scalar_api, payload)
        assert res.ok is True and res.no_data is False
        assert res.records == [{"value": expected_str}]

    # null / 缺失时视为无数据
    res_null = extract_json_records(
        json_scalar_api,
        {"operation_out": {"response": {"resp_code": "0000"}, "content": {"flag": None}}},
    )
    assert res_null.ok is True and res_null.no_data is True and res_null.records == []

    # JSON 顶层标量（path=""）
    root_scalar_json = parse_api_yaml(
        """
name: rootScalarJson
connector: unified-gateway-json
processCode: rootScalar
response:
  records:
    mode: scalar
    path: ""
"""
    )
    assert extract_json_records(root_scalar_json, parse_json_body("false")).records == [{"value": "false"}]
    assert extract_json_records(root_scalar_json, parse_json_body("0")).records == [{"value": "0"}]
    assert extract_json_records(root_scalar_json, parse_json_body('"PASS"')).records == [{"value": "PASS"}]

    # XML 标量：保留 "false"、"0"，过滤 xsi:nil 与空标签，支持根标签 path=""
    xml_scalar_api = parse_api_yaml(
        """
name: checkBalanceXml
connector: unified-gateway-xml
processCode: checkBalance
response:
  success:
    path: operation_out.response.resp_code
    equals: "0000"
  records:
    mode: scalar
    path: operation_out.content.balance
    columns:
      value: 账户余额
"""
    )
    for xml_val in ("0", "false", "108.50"):
        xml_doc = (
            f"<operation_out><response><resp_code>0000</resp_code></response>"
            f"<content><balance>{xml_val}</balance></content></operation_out>"
        )
        res_x = extract_records(xml_scalar_api, parse_xml(xml_doc))
        assert res_x.ok is True and res_x.no_data is False
        assert res_x.records == [{"value": xml_val}]

    nil_xml = (
        '<operation_out xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<response><resp_code>0000</resp_code></response>"
        '<content><balance xsi:nil="true"/></content></operation_out>'
    )
    res_nil = extract_records(xml_scalar_api, parse_xml(nil_xml))
    assert res_nil.ok is True and res_nil.no_data is True and res_nil.records == []

    root_scalar_xml = parse_api_yaml(
        """
name: rootScalarXml
connector: unified-gateway-xml
processCode: rootScalarXml
response:
  records:
    mode: scalar
    path: ""
"""
    )
    res_root_xml = extract_records(root_scalar_xml, parse_xml("<flag>false</flag>"))
    assert res_root_xml.ok is True and res_root_xml.records == [{"value": "false"}]


def test_single_object_and_root_path_parity_xml_and_json():
    # 默认 path="operation_out.content" 抽取单对象
    single_obj_xml_api = parse_api_yaml(
        """
name: queryCustProfile
connector: unified-gateway-xml
processCode: queryCustProfile
response:
  success:
    path: operation_out.response.resp_code
    equals: "0000"
  records:
    columns:
      custName: 客户姓名
      starLevel: 星级
"""
    )
    xml_body = (
        "<operation_out><response><resp_code>0000</resp_code></response>"
        "<content><custName>李四</custName><starLevel>五星</starLevel></content></operation_out>"
    )
    r_xml = extract_records(single_obj_xml_api, parse_xml(xml_body))
    assert r_xml.ok is True and r_xml.records == [{"custName": "李四", "starLevel": "五星"}]

    # mode="object" 在多节点输入下严格只取首行 (row=0)
    strict_obj_json = parse_api_yaml(
        """
name: strictSingleObj
connector: unified-gateway-json
processCode: strictSingleObj
response:
  records:
    mode: object
    path: operation_out.content
"""
    )
    r_single_from_list = extract_json_records(
        strict_obj_json,
        {"operation_out": {"content": [{"id": "1"}, {"id": "2"}]}},
    )
    assert r_single_from_list.ok is True and r_single_from_list.records == [{"id": "1"}]

    # 根路径 path="" 在 XML 与 JSON 下保持一致的单对象抽取语义
    root_xml_api = parse_api_yaml(
        """
name: customRootXml
connector: unified-gateway-xml
processCode: customRootXml
response:
  success:
    path: code
    equals: "0"
  records:
    mode: object
    path: ""
"""
    )
    r_root_xml = extract_records(
        root_xml_api,
        parse_xml("<userProfile><code>0</code><userName>王五</userName><city>南京</city></userProfile>"),
    )
    assert r_root_xml.ok is True
    assert r_root_xml.records == [{"code": "0", "userName": "王五", "city": "南京"}]

    root_json_api = root_xml_api.model_copy(update={"connector": "unified-gateway-json"})
    r_root_json = extract_json_records(root_json_api, {"code": "0", "userName": "王五", "city": "南京"})
    assert r_root_json.ok is True
    assert r_root_json.records == [{"code": "0", "userName": "王五", "city": "南京"}]

    # mode=auto + path=operation_out.content 遇到标准 content.list 包裹时自动解包多行；mode=object 则严格保留单行对象
    auto_json_api = parse_api_yaml(
        """
name: queryPkgAutoJson
connector: unified-gateway-json
processCode: queryPkgAuto
response:
  records:
    path: operation_out.content
    columns:
      pkgCode: 套餐编码
"""
    )
    list_wrapped_json = {
        "operation_out": {
            "content": {
                "total": 2,
                "list": [{"pkgCode": "P1"}, {"pkgCode": "P2"}],
            }
        }
    }
    r_auto_json_list = extract_json_records(auto_json_api, list_wrapped_json)
    assert r_auto_json_list.ok is True
    assert r_auto_json_list.records == [{"pkgCode": "P1"}, {"pkgCode": "P2"}]

    obj_json_api = parse_api_yaml(
        """
name: queryPkgObjJson
connector: unified-gateway-json
processCode: queryPkgObj
response:
  records:
    mode: object
    path: operation_out.content
"""
    )
    r_strict_obj = extract_json_records(obj_json_api, list_wrapped_json)
    assert r_strict_obj.ok is True
    assert len(r_strict_obj.records) == 1 and r_strict_obj.records[0]["total"] == "2"

    auto_xml_api = auto_json_api.model_copy(update={"connector": "unified-gateway-xml"})
    r_auto_xml_list = extract_records(
        auto_xml_api,
        parse_xml(
            "<operation_out><content><total>2</total>"
            "<list><pkgCode>P1</pkgCode></list><list><pkgCode>P2</pkgCode></list>"
            "</content></operation_out>"
        ),
    )
    assert r_auto_xml_list.ok is True
    assert r_auto_xml_list.records == [{"pkgCode": "P1"}, {"pkgCode": "P2"}]


async def test_nested_flatten_and_explicit_dotted_columns_with_evidence(tmp_path):
    # 1. flatten=True：递归展平 JSON 嵌套字典与 XML 嵌套子标签
    flat_json_api = parse_api_yaml(
        """
name: queryOrderDetailJson
connector: unified-gateway-json
processCode: queryOrderDetail
response:
  success:
    path: operation_out.response.resp_code
    equals: "0000"
  records:
    mode: object
    path: operation_out.content
    flatten: true
    columns:
      orderId: 订单号
      userInfo.userName: 客户姓名
      userInfo.contact.mobile: 联系号码
"""
    )
    nested_json = {
        "operation_out": {
            "response": {"resp_code": "0000"},
            "content": {
                "orderId": "ORD-9001",
                "userInfo": {
                    "userName": "赵六",
                    "vip": True,
                    "contact": {"mobile": "13912345678", "email": None},
                },
                "emptyMeta": {},
                "tags": ["政企", "5G"],
            },
        }
    }
    res_flat_json = extract_json_records(flat_json_api, nested_json)
    assert res_flat_json.ok is True
    assert res_flat_json.records == [
        {
            "orderId": "ORD-9001",
            "userInfo.userName": "赵六",
            "userInfo.vip": "true",
            "userInfo.contact.mobile": "13912345678",
            "userInfo.contact.email": "",
            "emptyMeta": "",
            "tags": '["政企","5G"]',
        }
    ]

    flat_xml_api = flat_json_api.model_copy(update={"connector": "unified-gateway-xml"})
    nested_xml = (
        '<operation_out xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<response><resp_code>0000</resp_code></response>"
        "<content>"
        "<orderId>ORD-9001</orderId>"
        "<userInfo><userName>赵六</userName><contact><mobile>13912345678</mobile>"
        '<email xsi:nil="true"/></contact></userInfo>'
        "<tags>政企</tags><tags>5G</tags>"
        "</content></operation_out>"
    )
    res_flat_xml = extract_records(flat_xml_api, parse_xml(nested_xml))
    assert res_flat_xml.ok is True
    assert res_flat_xml.records == [
        {
            "orderId": "ORD-9001",
            "userInfo.userName": "赵六",
            "userInfo.contact.mobile": "13912345678",
            "userInfo.contact.email": "",
            "tags": '["政企","5G"]',
        }
    ]

    # 2. flatten=False：保持顶层紧凑 JSON / XML 原文兼容，同时提取 columns 中显式声明的点分列
    selective_json_api = parse_api_yaml(
        """
name: selectiveColsJson
connector: unified-gateway-json
processCode: selectiveCols
response:
  records:
    path: operation_out.content
    flatten: false
    columns:
      orderId: 订单号
      detail.eff: 生效方式
      detail.cnt: 数量
      detail.missingKey: 不存在列
"""
    )
    res_sel_json = extract_json_records(
        selective_json_api,
        {"operation_out": {"content": {"orderId": "A1", "detail": {"eff": "立即生效", "cnt": 0}}}},
    )
    assert res_sel_json.ok is True
    assert res_sel_json.records == [
        {
            "orderId": "A1",
            "detail": '{"eff":"立即生效","cnt":0}',
            "detail.eff": "立即生效",
            "detail.cnt": "0",
        }
    ]

    selective_xml_api = selective_json_api.model_copy(update={"connector": "unified-gateway-xml"})
    res_sel_xml = extract_records(
        selective_xml_api,
        parse_xml(
            "<operation_out><content><orderId>A1</orderId>"
            "<detail><eff>立即生效</eff><cnt>0</cnt></detail></content></operation_out>"
        ),
    )
    assert res_sel_xml.ok is True
    assert res_sel_xml.records[0]["orderId"] == "A1"
    assert res_sel_xml.records[0]["detail"] == "<detail><eff>立即生效</eff><cnt>0</cnt></detail>"
    assert res_sel_xml.records[0]["detail.eff"] == "立即生效"
    assert res_sel_xml.records[0]["detail.cnt"] == "0"
    assert "detail.missingKey" not in res_sel_xml.records[0]

    # 3. 验证 query_result 与 EvidenceChecker 对点分列名的完整支持
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", llm_api_key="test")
    tpl = Template(
        definition=TemplateDef(
            id=2001,
            name="单对象核查模板",
            fields=[FieldDef(name="客户姓名", type="string", evidence="quote", description="接口客户姓名")],
        ),
        body="客户：{{ 客户姓名 }}",
    )
    rs = ResourceSet(templates={2001: tpl}, apis={"queryOrderDetailJson": flat_json_api})
    ws = Workspace()
    deps = RunDeps(
        run_id="run_flat_1",
        rev="test",
        settings=settings,
        resources=rs,
        template=tpl,
        allowed_skills=[],
        allowed_apis=["queryOrderDetailJson"],
        inputs={},
        document="",
        gateway=_StubGateway(res_flat_json),
        workspace=ws,
        events=EventSink(),
    )
    call_out = await call_api(_make_ctx(deps), "queryOrderDetailJson", {})
    rid = call_out["resultId"]
    qr = await query_result(_make_ctx(deps), resultId=rid, columns=["userInfo.userName"])
    assert qr["total"] == 1
    assert qr["rows"] == [{"userInfo.userName": "赵六", "row": 0}]

    checker = EvidenceChecker(tpl, {}, "", ws)
    issues = checker.check(
        {
            "客户姓名": {
                "status": "found",
                "value": "赵六",
                "evidence": [{"type": "api", "resultId": rid, "row": 0, "column": "userInfo.userName"}],
            }
        }
    )
    assert issues == []
