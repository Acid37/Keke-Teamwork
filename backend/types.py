"""Shared data types for all modules."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4


# ─── LLM related ───

@dataclass
class ToolSchema:
    """Tool JSON Schema description, passed directly to OpenAI SDK."""
    name: str
    description: str
    parameters: dict  # JSON Schema object


@dataclass
class ToolCall:
    """A tool call returned by the LLM."""
    id: str
    name: str
    args: dict  # Parsed argument dict


@dataclass
class StreamEvent:
    """One streaming event yielded per chunk."""
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


# ─── Tool execution ───

ToolResult = tuple[bool, str]  # (success, output_text)


# ─── File changes ───

@dataclass
class FileDiff:
    path: Path
    action: str          # "create" | "modify" | "delete"
    diff_text: str       # unified diff format
    new_content: str | None = None


@dataclass
class CommitResult:
    files_changed: int
    diffs: list[FileDiff]
    combined_diff: str
    summary: str


# ─── Checkpoints ───

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


# ─── Session ───

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


# ─── Tool context ───

@dataclass
class ToolContext:
    """Execution context injected into every tool.

    Tools access external state (session, staging, etc.) through this
    object so they remain stateless and testable.
    """
    session: Session
    work_dir: Path
    staging: Any = None  # FileStagingArea | None (avoid circular import)
    checkpoint_mgr: Any = None  # CheckpointManager | None
    permission_mgr: Any = None  # PermissionManager | None
    broadcast: Callable[..., Awaitable[None]] | None = None
    interrupt_check: Callable[[], bool] | None = None


# ─── Agent definition ───

@dataclass
class AgentDefinition:
    """A customizable agent role definition stored in agents.json."""
    agent_id: str
    name: str                        # display name, e.g. "方案规划师"
    role: str                        # role tag, e.g. "planner", "coder"
    system_prompt: str = ""
    provider: str | None = None      # override global provider
    model: str | None = None         # override global main_model
    temperature: float = 0.7
    tools: list[str] = field(default_factory=lambda: [
        "read_file", "write_file", "edit_file",
        "run_console", "grep_search", "find_files", "list_directory",
    ])
    max_tool_rounds: int = 50
    color: str = "#4a9eff"           # frontend display color
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


# ─── Agent result ───

@dataclass
class AgentResult:
    text: str
    thinking: str
    tool_calls_history: list[dict]
    usage: TokenUsage
    messages: list[dict]
