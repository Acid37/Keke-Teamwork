"""类型化 WebSocket 事件定义。

用 dataclass 替代散落的 ``broadcast("xxx.yyy", {...})`` 调用，
使事件协议有单一事实来源，并支持自动生成前端 TypeScript 类型。

使用方式::

    from backend.events import AgentTextEvent

    await AgentTextEvent(
        text="hello", source="assistant", is_final=False,
        agent_id="main", agent_name="通用助手", role="assistant", color="#4a9eff",
    ).emit(broadcast)

迁移策略：``broadcast("agent.text", {...})`` 可逐步替换为
``AgentTextEvent(...).emit(broadcast)``，两者产生完全相同的 WS 消息。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# ─── 事件类型常量 ───

# 会话生命周期
SESSION_READY = "session.ready"
SESSION_LIST = "session.list"
SESSION_TITLE_UPDATED = "session.title.updated"

# Agent 执行
AGENT_STATUS = "agent.status"
AGENT_STARTED = "agent.started"
AGENT_TEXT = "agent.text"
AGENT_THINKING = "agent.thinking"
AGENT_COMPLETED = "agent.completed"

# 工具调用
TOOL_CALL = "tool.call"
CONSOLE_OUTPUT = "console.output"

# 文件变更
FILES_CHANGED = "files.changed"

# 并行研究
RESEARCH_STARTED = "research.started"
RESEARCH_RESULT = "research.result"
RESEARCH_FAILED = "research.failed"
RESEARCH_COMPLETED = "research.completed"

# Handoff
HANDOFF_STARTED = "handoff.started"
HANDOFF_COMPLETED = "handoff.completed"
HANDOFF_FAILED = "handoff.failed"

# 审批
APPROVAL_REQUEST = "approval.request"

# 错误
ERROR = "error"

# 目录浏览
BROWSE_DIRECTORY_RESULT = "browse.directory_result"


# ─── 事件基类 ───

BroadcastFn = Any  # Callable[[str, dict], Awaitable[None]]，用 Any 避免循环导入


@dataclass
class WSEvent:
    """所有 WebSocket 事件的基类。

    子类需声明 ``_event_type`` 类属性，并通过 dataclass 字段定义 payload。
    ``emit()`` 方法将自身序列化为 ``{type, payload}`` 并调用 broadcast。
    """

    _event_type: str = field(default="", repr=False, compare=False)

    @property
    def event_type(self) -> str:
        return self._event_type

    def to_payload(self) -> dict:
        """序列化为 payload 字典（排除内部字段）。"""
        d = asdict(self)
        d.pop("_event_type", None)
        # 移除 None 值的 Optional 字段，减少 WS 传输量
        return {k: v for k, v in d.items() if v is not None}

    async def emit(self, broadcast: BroadcastFn) -> None:
        """通过 broadcast 函数发送此事件。"""
        await broadcast(self.event_type, self.to_payload())


# ─── 会话生命周期 ───


@dataclass
class SessionReadyEvent(WSEvent):
    _event_type: str = field(default=SESSION_READY, repr=False, compare=False)

    session_id: str = ""
    title: str = ""
    phase: str = ""
    history: list[dict] = field(default_factory=list)
    work_dir: str = ""
    auto_review: bool = True
    yolo_mode: bool = False
    solo_mode: bool = False
    usage: dict | None = None
    timeline_events: list[dict] = field(default_factory=list)


@dataclass
class SessionListEvent(WSEvent):
    _event_type: str = field(default=SESSION_LIST, repr=False, compare=False)

    sessions: list[dict] = field(default_factory=list)


@dataclass
class SessionTitleUpdatedEvent(WSEvent):
    _event_type: str = field(default=SESSION_TITLE_UPDATED, repr=False, compare=False)

    session_id: str = ""
    title: str = ""


# ─── Agent 执行 ───


@dataclass
class AgentStatusEvent(WSEvent):
    _event_type: str = field(default=AGENT_STATUS, repr=False, compare=False)

    phase: str = ""
    detail: str | None = None


@dataclass
class AgentStartedEvent(WSEvent):
    _event_type: str = field(default=AGENT_STARTED, repr=False, compare=False)

    agent_id: str = ""
    agent_name: str = ""
    role: str = ""
    color: str = ""
    parent_agent_id: str | None = None
    delegated: bool | None = None
    handoff: bool | None = None


@dataclass
class AgentTextEvent(WSEvent):
    _event_type: str = field(default=AGENT_TEXT, repr=False, compare=False)

    text: str = ""
    source: str = ""
    is_final: bool = False
    agent_id: str | None = None
    agent_name: str | None = None
    role: str | None = None
    color: str | None = None
    parent_agent_id: str | None = None


@dataclass
class AgentThinkingEvent(WSEvent):
    _event_type: str = field(default=AGENT_THINKING, repr=False, compare=False)

    text: str = ""
    source: str = ""
    agent_id: str | None = None
    agent_name: str | None = None
    parent_agent_id: str | None = None


@dataclass
class AgentCompletedEvent(WSEvent):
    _event_type: str = field(default=AGENT_COMPLETED, repr=False, compare=False)

    agent_id: str = ""
    agent_name: str = ""
    role: str = ""
    summary: str = ""
    usage: dict | None = None
    parent_agent_id: str | None = None
    delegated: bool | None = None
    handoff: bool | None = None


# ─── 工具调用 ───


@dataclass
class ToolCallEvent(WSEvent):
    _event_type: str = field(default=TOOL_CALL, repr=False, compare=False)

    name: str = ""
    args: dict = field(default_factory=dict)
    stage: str = "running"  # "running" | "completed"
    source: str = ""
    call_id: str = ""
    agent_id: str | None = None
    parent_agent_id: str | None = None
    success: bool | None = None  # stage=completed 时携带


@dataclass
class ConsoleOutputEvent(WSEvent):
    _event_type: str = field(default=CONSOLE_OUTPUT, repr=False, compare=False)

    output: str = ""
    exit_code: int | None = None
    call_id: str = ""
    command: str | None = None


# ─── 文件变更 ───


@dataclass
class FileChangeItem:
    path: str
    action: str  # "create" | "modify" | "delete"
    diff_text: str


@dataclass
class FilesChangedEvent(WSEvent):
    _event_type: str = field(default=FILES_CHANGED, repr=False, compare=False)

    summary: str = ""
    combined_diff: str = ""
    files: list[dict] = field(default_factory=list)


# ─── 并行研究 ───


@dataclass
class ResearchStartedEvent(WSEvent):
    _event_type: str = field(default=RESEARCH_STARTED, repr=False, compare=False)

    agent_id: str = ""
    agent_name: str = ""
    role: str = ""
    parent_agent_id: str = ""
    task: str = ""


@dataclass
class ResearchResultEvent(WSEvent):
    _event_type: str = field(default=RESEARCH_RESULT, repr=False, compare=False)

    agent_id: str = ""
    agent_name: str = ""
    role: str = ""
    parent_agent_id: str = ""
    task: str = ""
    text: str = ""
    timed_out: bool = False
    error: str | None = None


@dataclass
class ResearchFailedEvent(WSEvent):
    _event_type: str = field(default=RESEARCH_FAILED, repr=False, compare=False)

    agent_id: str = ""
    agent_name: str = ""
    role: str = ""
    parent_agent_id: str = ""
    task: str = ""
    text: str = ""
    timed_out: bool = False
    error: str | None = None


@dataclass
class ResearchCompletedEvent(WSEvent):
    _event_type: str = field(default=RESEARCH_COMPLETED, repr=False, compare=False)

    parent_agent_id: str = ""
    task: str = ""
    merged_text: str = ""
    successful_sources: list[str] = field(default_factory=list)
    timed_out_sources: list[str] = field(default_factory=list)
    errored_sources: list[str] = field(default_factory=list)
    result_count: int = 0


# ─── Handoff ───


@dataclass
class HandoffStartedEvent(WSEvent):
    _event_type: str = field(default=HANDOFF_STARTED, repr=False, compare=False)

    agent_id: str = ""
    agent_name: str = ""
    role: str = ""
    parent_agent_id: str = ""
    task: str = ""


@dataclass
class HandoffCompletedEvent(WSEvent):
    _event_type: str = field(default=HANDOFF_COMPLETED, repr=False, compare=False)

    agent_id: str = ""
    agent_name: str = ""
    role: str = ""
    parent_agent_id: str = ""
    task: str = ""
    text: str = ""


@dataclass
class HandoffFailedEvent(WSEvent):
    _event_type: str = field(default=HANDOFF_FAILED, repr=False, compare=False)

    agent_id: str = ""
    agent_name: str = ""
    role: str = ""
    parent_agent_id: str = ""
    task: str = ""
    error: str = ""


# ─── 审批 ───


@dataclass
class ApprovalRequestEvent(WSEvent):
    _event_type: str = field(default=APPROVAL_REQUEST, repr=False, compare=False)

    request_id: str = ""
    command: str = ""
    risk_level: str | None = None
    timeout_seconds: int = 120


# ─── 错误 ───


@dataclass
class ErrorEvent(WSEvent):
    _event_type: str = field(default=ERROR, repr=False, compare=False)

    message: str = ""
    recoverable: bool = True


# ─── 目录浏览 ───


@dataclass
class BrowseDirectoryResultEvent(WSEvent):
    _event_type: str = field(default=BROWSE_DIRECTORY_RESULT, repr=False, compare=False)

    path: str = ""
    parent: str | None = None
    entries: list[dict] = field(default_factory=list)
    error: str | None = None


# ─── 事件注册表（供 export_schema 使用）───

EVENT_REGISTRY: dict[str, type[WSEvent]] = {
    SESSION_READY: SessionReadyEvent,
    SESSION_LIST: SessionListEvent,
    SESSION_TITLE_UPDATED: SessionTitleUpdatedEvent,
    AGENT_STATUS: AgentStatusEvent,
    AGENT_STARTED: AgentStartedEvent,
    AGENT_TEXT: AgentTextEvent,
    AGENT_THINKING: AgentThinkingEvent,
    AGENT_COMPLETED: AgentCompletedEvent,
    TOOL_CALL: ToolCallEvent,
    CONSOLE_OUTPUT: ConsoleOutputEvent,
    FILES_CHANGED: FilesChangedEvent,
    RESEARCH_STARTED: ResearchStartedEvent,
    RESEARCH_RESULT: ResearchResultEvent,
    RESEARCH_FAILED: ResearchFailedEvent,
    RESEARCH_COMPLETED: ResearchCompletedEvent,
    HANDOFF_STARTED: HandoffStartedEvent,
    HANDOFF_COMPLETED: HandoffCompletedEvent,
    HANDOFF_FAILED: HandoffFailedEvent,
    APPROVAL_REQUEST: ApprovalRequestEvent,
    ERROR: ErrorEvent,
    BROWSE_DIRECTORY_RESULT: BrowseDirectoryResultEvent,
}
