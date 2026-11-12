"""应用配置。

#Created By AiCoding(codex)
所有配置都来自环境变量（或工作目录下的 .env 文件），密钥类配置使用 SecretStr，避免误打到日志。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """运行时配置，字段名即环境变量名（不区分大小写）。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---------------- 数据目录（PVC 挂载点） ----------------
    data_dir: Path = Field(default=Path("./data"), description="PVC 挂载目录，所有资源、草稿、发布快照和运行记录都在这里")
    seed_on_empty: bool = Field(default=True, description="数据目录为空时，用内置示例资源初始化第一个发布版本")
    releases_keep: int = Field(default=50, description="保留多少个已物化的发布快照目录，更早的需要时再从 Git 恢复")
    runs_keep_days: int = Field(default=90, description="运行记录保留天数，0 表示不清理")

    # ---------------- 大模型（OpenAI 兼容接口） ----------------
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr = SecretStr("dummy")
    llm_model: str = "deepseek-v4-flash"
    llm_temperature: float = 0.0
    llm_max_tokens: int | None = None
    llm_timeout_s: float = Field(default=120.0, description="单次模型请求超时")
    llm_http_retries: int = Field(default=2, description="模型 HTTP 层自动重试次数（网络错误、5xx）")
    llm_parallel_tool_calls: bool | None = Field(default=True, description="是否允许模型并行调用工具，None 表示使用服务端默认")
    llm_strict_tools: bool | None = Field(default=None, description="是否声明 strict 工具定义；内网推理服务不支持时设为 false")
    llm_tool_choice_required: bool | None = Field(default=None, description="推理服务是否支持 tool_choice=required")

    # ---------------- 智能体运行 ----------------
    agent_output_mode: Literal["tool", "native", "json_object", "prompted"] = Field(
        default="tool",
        description="结构化交卷方式：tool=调用 submit_report 工具；native=json_schema；"
                    "json_object=Schema 写入提示词 + response_format=json_object（DeepSeek 官方 API）；prompted=只靠提示词约束",
    )
    agent_native_strict: bool = Field(
        default=True, description="native 模式下以 strict json_schema 发送（所有键必填、oneOf 转 anyOf），推理服务按 Schema 约束解码"
    )
    agent_output_retries: int = Field(default=3, description="证据校验不通过时，最多让模型重新交卷几次")
    agent_tool_retries: int = Field(default=2, description="工具参数不合法时，最多让模型重试几次")
    agent_request_limit: int = Field(default=25, description="单次运行最多请求模型多少轮")
    agent_tool_calls_limit: int = Field(default=120, description="单次运行最多调用多少次工具")
    agent_run_timeout_s: float = Field(default=600.0, description="单次运行总超时")
    agent_max_concurrent_runs: int = Field(default=8, description="进程内同时运行的智能体数量上限")
    agent_preview_rows: int = Field(default=10, description="call_api 摘要中最多预览多少行")

    # ---------------- 统一网关 ----------------
    gateway_mode: Literal["live", "mock"] = Field(default="mock", description="live=调用真实统一网关；mock=读取 data/mock-gateway 下的样例响应")
    gateway_url: str = ""
    gateway_app_id: SecretStr = SecretStr("")
    gateway_access_token: SecretStr = SecretStr("")
    gateway_xml_style: Literal["java", "clean"] = Field(
        default="java", description="java=与现有 Java 实现逐字一致（字母序、空值 xsi:nil）；clean=声明顺序、无 xsi:nil"
    )
    gateway_connect_timeout_s: float = 5.0
    gateway_max_concurrency: int = Field(default=32, description="进程内调用真实统一网关的最大并发请求数")

    # ---------------- 管理端认证 ----------------
    admin_token_secret: SecretStr | None = Field(default=None, description="会话令牌签名密钥；不配置时自动生成并保存在数据目录")
    admin_token_ttl_s: int = 12 * 3600
    admin_cookie_secure: bool = Field(default=False, description="HTTPS 部署时设为 true")
    admin_bootstrap_password: SecretStr | None = Field(
        default=None, description="首次启动且没有任何用户时，用这个密码创建 admin 账号"
    )

    # ---------------- 上游业务接口认证 ----------------
    report_api_keys: str = Field(default="", description="上游调用 /api/v1/reports 的 API Key，多个用逗号分隔；为空表示不校验")

    # ---------------- 日志 ----------------
    log_level: str = "INFO"
    log_dir: Path | None = Field(default=None, description="日志文件目录，不配置时只输出到控制台")

    # ---------------- 前端 ----------------
    frontend_dist: Path | None = Field(default=None, description="前端构建产物目录（frontend/dist），配置后由本服务托管")

    def report_api_key_set(self) -> set[str]:
        """解析上游 API Key 列表。"""
        return {k.strip() for k in self.report_api_keys.split(",") if k.strip()}


@lru_cache
def get_settings() -> Settings:
    """进程内单例配置。"""
    return Settings()
