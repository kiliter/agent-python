"""嵌入式聊天选模板窗口：会话存储、运行过程步骤映射、后台运行管理与对话服务。

#Created By AiCoding(codex)
"""

from __future__ import annotations

from .manager import ChatRunManager, RunCompletion
from .steps import StepMapper, events_to_steps
from .store import SESSION_ID_RE, ChatStore, inputs_fingerprint, session_id_for

__all__ = [
    "SESSION_ID_RE",
    "ChatRunManager",
    "ChatStore",
    "RunCompletion",
    "StepMapper",
    "events_to_steps",
    "inputs_fingerprint",
    "session_id_for",
]
