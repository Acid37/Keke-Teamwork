"""所有模块共享的数据类型。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4


# ─── LLM 相关 ───

@dataclass
class ToolSchema:
    """工具的 JSON Schema 描述，直接传递给 OpenAI SDK。"""
    name: str
    description: str
    parameters: dict  # JSON Schema 对象


@dataclass
class ToolCall:
    """LLM 返回的工具调用。"""
    id: str
    name: str
    args: dict  # 解析后的参数字典


@dataclass
class StreamEvent:
    """每个流式块产生的事件。"""
    text_delta: str | None = None
    thinking_delta: str | None = None
    tool_calls: list[ToolCall] | None = None
    finish: bool = False


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __iadd__(self, other: TokenUsage) -> TokenUsage:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        return self


# ─── 工具执行 ───

ToolResult = tuple[bool, str]  # (是否成功, 输出文本)


# ─── 文件变更 ───

@dataclass
class FileDiff:
    path: Path
    action: str          # "create" | "modify" | "delete"
    diff_text: str       # unified diff 格式
    new_content: str | None = None


@dataclass
class CommitResult:
    files_changed: int
    diffs: list[FileDiff]
    combined_diff: str
    summary: str


# ─── 检查点 ───

@dataclass
class FileSnapshot:
    path: Path
    action: str          # "create" | "modify" | "delete"
    original_content: bytes | None
    original_mode: int | None


@dataclass
class Checkpoint:
    id: str
    tool_name: str
    description: str
    snapshots: list[FileSnapshot]
    timestamp: float = 0.0
    reversible: bool = True

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()
        if not self.id:
            self.id = uuid4().hex[:8]


# ─── 会话 ───

class Phase(str, Enum):
    INIT = "init"
    RESEARCHING = "researching"
    THINKING = "thinking"
    CODING = "coding"
    READY = "ready"
    ERROR = "error"


@dataclass
class Session:
    id: str
    work_dir: Path
    phase: Phase = Phase.INIT
    messages: list[dict] = field(default_factory=list)
    project_context: dict | None = None
    checkpoints: list[Checkpoint] = field(default_factory=list)
    yolo_mode: bool = False
    auto_review: bool = True
    solo_mode: bool = False
    interrupt_requested: bool = False
    coder_guidance_queue: list[str] = field(default_factory=list)
    usage_total: TokenUsage = field(default_factory=TokenUsage)
    title: str = ""
    created_at: float = 0.0
    last_active_at: float = 0.0

    def __post_init__(self):
        now = time.time()
        if self.created_at == 0.0:
            self.created_at = now
        if self.last_active_at == 0.0:
            self.last_active_at = now


# ─── 工具上下文 ───

@dataclass
class ToolContext:
    """注入到每个工具的执行上下文。

    工具通过此对象访问外部状态（会话、暂存区等），
    使工具本身保持无状态且可测试。
    """
    session: Session
    work_dir: Path
    staging: Any = None  # FileStagingArea | None（避免循环导入）
    checkpoint_mgr: Any = None  # CheckpointManager | None
    permission_mgr: Any = None  # PermissionManager | None
    delegate_runner: Any = None  # delegate_agent 工具的回调（避免循环导入）
    broadcast: Callable[..., Awaitable[None]] | None = None
    interrupt_check: Callable[[], bool] | None = None


# ─── Agent 定义 ───

@dataclass
class AgentDefinition:
    """可自定义的 Agent 角色定义，存储在 agents.json 中。"""
    agent_id: str
    name: str                        # 显示名称，如 "方案规划师"
    role: str                        # 角色标签，如 "planner"、"coder"
    system_prompt: str = ""
    provider: str | None = None      # 覆盖全局 provider
    model: str | None = None         # 覆盖全局 main_model
    temperature: float = 0.7
    tools: list[str] = field(default_factory=lambda: [
        "read_file", "write_file", "edit_file",
        "run_console", "grep_search", "find_files", "list_directory",
        "delegate_agent",
    ])
    max_tool_rounds: int = 50
    color: str = "#4a9eff"           # 前端显示颜色
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "role": self.role,
            "system_prompt": self.system_prompt,
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "tools": self.tools,
            "max_tool_rounds": self.max_tool_rounds,
            "color": self.color,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AgentDefinition:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


# ─── Agent 结果 ───

@dataclass
class AgentResult:
    text: str
    thinking: str
    tool_calls_history: list[dict]
    usage: TokenUsage
    messages: list[dict]
    error: str | None = None  # LLM 调用失败时设置，非 None 表示执行失败


@dataclass
class ParallelResearchResult:
    """单个 researcher 的研究结果和调度元数据。"""

    text: str
    metadata: dict
    error: str | None = None


@dataclass
class MergedResearchResult:
    """多 researcher 结果的确定性合并产物。"""

    text: str
    successful_sources: list[str]
    timed_out_sources: list[str]
    errored_sources: list[str]
