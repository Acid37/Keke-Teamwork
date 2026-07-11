from enum import Enum

from backend.types import ToolSchema, ToolResult, ToolContext


class ToolCategory(str, Enum):
    """Tool classification for permission routing and pluggable registration.

    Categories:
        file    — read/write/edit files (read_file, write_file, edit_file)
        search  — read-only search and discovery (grep_search, find_files, list_directory)
        shell   — execute shell commands (run_console)
        coding  — no direct side effects, orchestration only (delegate_agent)
        mcp     — reserved for future MCP tools
    """
    file = "file"
    search = "search"
    shell = "shell"
    coding = "coding"
    mcp = "mcp"


class Tool:
    """Tool base class. Subclasses define name, description, parameters as class attributes."""

    name: str = ""
    description: str = ""
    parameters: dict = {}
    category: ToolCategory = ToolCategory.file  # subclasses override

    def __init__(self, context: ToolContext):
        self._ctx = context

    async def execute(self, **kwargs) -> ToolResult:
        raise NotImplementedError

    def to_schema(self) -> ToolSchema:
        return ToolSchema(self.name, self.description, self.parameters)
