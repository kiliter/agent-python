"""创建大模型客户端（OpenAI 兼容接口，内网 DeepSeek V4-Flash 等）。

#Created By AiCoding(codex)
推理服务对 strict 工具定义、tool_choice=required 的支持程度不一，可通过环境变量覆盖模型能力声明。
"""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from ..config import Settings


def build_model(settings: Settings) -> OpenAIChatModel:
    """按配置创建模型。HTTP 层重试与超时交给 openai SDK。"""
    client = AsyncOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value(),
        timeout=settings.llm_timeout_s,
        max_retries=settings.llm_http_retries,
    )
    provider = OpenAIProvider(openai_client=client)
    model = OpenAIChatModel(settings.llm_model, provider=provider)
    overrides: dict[str, Any] = {}
    # 按交卷方式声明推理服务的结构化输出能力：
    #   json_object：只支持 response_format=json_object（如 DeepSeek 官方 API），禁止发送 json_schema
    #   prompted：不发送任何 response_format，只靠提示词约束
    if settings.agent_output_mode == "json_object":
        overrides["supports_json_object_output"] = True
        overrides["supports_json_schema_output"] = False
    elif settings.agent_output_mode == "prompted":
        overrides["supports_json_object_output"] = False
        overrides["supports_json_schema_output"] = False
    if settings.llm_strict_tools is not None:
        overrides["openai_supports_strict_tool_definition"] = settings.llm_strict_tools
    if settings.llm_tool_choice_required is not None:
        overrides["openai_supports_tool_choice_required"] = settings.llm_tool_choice_required
        overrides["supports_forced_tool_choice"] = settings.llm_tool_choice_required
    if overrides:
        model = OpenAIChatModel(settings.llm_model, provider=provider, profile={**dict(model.profile), **overrides})
    return model


def build_model_settings(settings: Settings) -> dict[str, Any]:
    """每次请求的模型参数。"""
    ms: dict[str, Any] = {"temperature": settings.llm_temperature, "timeout": settings.llm_timeout_s}
    if settings.llm_max_tokens:
        ms["max_tokens"] = settings.llm_max_tokens
    if settings.llm_parallel_tool_calls is not None:
        ms["parallel_tool_calls"] = settings.llm_parallel_tool_calls
    return ms
