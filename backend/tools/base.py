from enum import Enum
from pathlib import Path

from backend.types import ToolSchema, ToolResult, ToolContext
from backend.safety.path_guard import (
    resolve_path,
    check_agent_path_permissions,
    PathBoundaryError,
    AgentPathDeniedError,
)


class ToolCategory(str, Enum):
    """工具分类，用于权限路由和可插拔注册。

    分类说明：
        file    — 文件读写和编辑（read_file, write_file, edit_file）
        search  — 只读搜索和发现（grep_search, find_files, list_directory）
        shell   — 执行 shell 命令（run_console）
        coding  — 无直接副作用，仅用于编排（delegate_agent）
        mcp     — 预留 MCP 工具接入
    """
    file = "file"
    search = "search"
    shell = "shell"
    coding = "coding"
    mcp = "mcp"


class Tool:
    """工具基类。子类通过类属性定义 name、description、parameters。"""

    name: str = ""
    description: str = ""
    parameters: dict = {}
    category: ToolCategory = ToolCategory.file  # 子类覆盖此属性

    def __init__(self, context: ToolContext):
        self._ctx = context

    async def execute(self, **kwargs) -> ToolResult:
        raise NotImplementedError

    def to_schema(self) -> ToolSchema:
        return ToolSchema(self.name, self.description, self.parameters)

    def _resolve_and_check_path(self, path_str: str | None) -> tuple[bool, str] | Path:
        """解析路径 + 检查 Agent 权限。成功返回 Path，失败返回 (False, msg)。"""
        try:
            target = resolve_path(path_str, self._ctx.work_dir) if path_str is not None else self._ctx.work_dir.resolve()
        except PathBoundaryError as e:
            return (False, str(e))
        try:
            check_agent_path_permissions(target, self._ctx.work_dir, self._ctx.agent_permissions)
        except AgentPathDeniedError as e:
            return (False, str(e))
        return target
