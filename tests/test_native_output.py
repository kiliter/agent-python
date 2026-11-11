"""native（json_schema）交卷模式测试：用假的 OpenAI 兼容服务检查实际请求体，并跑通完整运行。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import json

import httpx
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from report_agent.config import Settings
from report_agent.container import build_container
from report_agent.runtime.runner import RunRequest
from scripted_model import ORDER_SMS, build_report


def _reply(message: dict) -> httpx.Response:
    return httpx.Response(200, json={
        "id": "x", "object": "chat.completion", "created": 0, "model": "deepseek-v4-flash",
        "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})


def _fake_llm(calls: list[dict]):
    """第 1 次：并行调用 call_api 和 format_date；第 2 次：交卷（订购短信故意截断）；第 3 次：改正后交卷。"""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return _reply({"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "call_api", "arguments": json.dumps(
                    {"name": "querySMSSendInfo", "args": {"手机号码": "13900001234", "开始时间": "20261105000000",
                                                          "结束时间": "20261105235959"}}, ensure_ascii=False)}},
                {"id": "c2", "type": "function", "function": {"name": "format_date", "arguments": json.dumps(
                    {"value": "20261105", "fromPattern": "yyyyMMdd", "toPattern": "yyyy年M月d号"}, ensure_ascii=False)}},
            ]})
        tool_msg = next(m for m in body["messages"] if m["role"] == "tool" and m.get("tool_call_id") == "c2")
        date_call = json.loads(tool_msg["content"])["callId"]
        sms = ORDER_SMS[:-3] if len(calls) == 2 else ORDER_SMS
        return _reply({"role": "assistant", "content": json.dumps(build_report(sms, date_call), ensure_ascii=False)})

    return handler


async def test_native_json_schema_mode(tmp_path, case_c01):
    calls: list[dict] = []
    client = AsyncOpenAI(base_url="http://fake-llm/v1", api_key="k",
                         http_client=httpx.AsyncClient(transport=httpx.MockTransport(_fake_llm(calls))))
    model = OpenAIChatModel("deepseek-v4-flash", provider=OpenAIProvider(openai_client=client))
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", agent_output_mode="native")
    c = build_container(settings, model=model)

    out = await c.runner.run(RunRequest(1001, case_c01["inputs"], case_c01["documentText"]))

    rf = calls[0]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["name"] == "submit_report"
    assert rf["json_schema"]["strict"] is True
    schema = rf["json_schema"]["schema"]
    assert set(schema["required"]) == {f.name for f in c.service.template_online(1001).definition.fields}
    assert "oneOf" not in json.dumps(schema)                        # strict 模式下转换为 anyOf
    assert "submit_report" not in [t["function"]["name"] for t in calls[0]["tools"]]
    assert len(calls) == 3
    assert [e["type"] for e in out["events"] if e["type"].startswith("report_")] == ["report_rejected",
                                                                                   "report_accepted"]
    assert out["status"] == "SUCCESS", out["error"]
    assert next(f for f in out["fields"] if f["name"] == "受理日期")["value"] == "2026年11月5号"


async def test_json_object_mode_for_deepseek(tmp_path, case_c01):
    """json_object 模式（DeepSeek 官方 API）：response_format 只能是 json_object，Schema 写进消息，消息中必须含 JSON 字样。"""
    from report_agent.runtime.model_factory import build_model

    calls: list[dict] = []
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", agent_output_mode="json_object",
                        llm_base_url="http://fake-llm/v1", llm_model="deepseek-flash")
    model = build_model(settings)
    model._provider._client._client = httpx.AsyncClient(transport=httpx.MockTransport(_fake_llm(calls)))  # type: ignore[attr-defined]
    c = build_container(settings, model=model)

    out = await c.runner.run(RunRequest(1001, case_c01["inputs"], case_c01["documentText"]))

    for body in calls:
        assert body["response_format"] == {"type": "json_object"}
    first_text = json.dumps(calls[0]["messages"], ensure_ascii=False)
    assert "JSON" in first_text and "订购短信" in first_text          # Schema 已写入消息
    assert "call_api" in [t["function"]["name"] for t in calls[0]["tools"]]
    assert out["status"] == "SUCCESS", out["error"]
    assert [e["type"] for e in out["events"] if e["type"].startswith("report_")] == ["report_rejected",
                                                                                   "report_accepted"]


async def test_prompted_mode_omits_response_format_and_salvages_partial_fenced_json(tmp_path, case_c01):
    """prompted 模式下不发送 response_format，且模型用 ```json 包裹并漏掉个别字段耗尽重试时能做字段级降级。"""
    from report_agent.runtime.model_factory import build_model

    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return _reply({"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "call_api", "arguments": json.dumps(
                    {"name": "querySMSSendInfo", "args": {"手机号码": "13900001234", "开始时间": "20261105000000",
                                                          "结束时间": "20261105235959"}}, ensure_ascii=False)}},
                {"id": "c2", "type": "function", "function": {"name": "format_date", "arguments": json.dumps(
                    {"value": "20261105", "fromPattern": "yyyyMMdd", "toPattern": "yyyy年M月d号"}, ensure_ascii=False)}},
            ]})
        tool_msg = next(m for m in body["messages"] if m["role"] == "tool" and m.get("tool_call_id") == "c2")
        date_call = json.loads(tool_msg["content"])["callId"]
        partial = build_report(ORDER_SMS, date_call)
        partial.pop("二次确认短信")
        fenced = "```json\n" + json.dumps(partial, ensure_ascii=False) + "\n```"
        return _reply({"role": "assistant", "content": fenced})

    settings = Settings(
        _env_file=None, data_dir=tmp_path / "data", agent_output_mode="prompted",
        agent_output_retries=1, llm_base_url="http://fake-llm/v1", llm_model="deepseek-flash",
    )
    model = build_model(settings)
    model._provider._client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[attr-defined]
    c = build_container(settings, model=model)

    out = await c.runner.run(RunRequest(1001, case_c01["inputs"], case_c01["documentText"]))

    for body in calls:
        assert "response_format" not in body
    assert out["status"] == "PARTIAL", out["error"]
    by_name = {f["name"]: f for f in out["fields"]}
    assert by_name["二次确认短信"]["status"] == "not_found" and by_name["二次确认短信"]["validationFailed"] is True
    assert by_name["订购短信"]["status"] == "found" and by_name["订购短信"]["value"] == ORDER_SMS
    assert by_name["受理日期"]["status"] == "found" and by_name["受理日期"]["value"] == "2026年11月5号"
