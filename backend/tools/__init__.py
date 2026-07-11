from backend.tools.base import Tool, ToolCategory
from backend.tools.read import ReadTool
from backend.tools.write import WriteTool
from backend.tools.edit import EditTool
from backend.tools.console import ConsoleTool
from backend.tools.grep import GrepTool
from backend.tools.find import FindTool
from backend.tools.ls import LsTool
from backend.tools.delegate import DelegateTool

ALL_TOOLS = [
    ReadTool,
    WriteTool,
    EditTool,
    ConsoleTool,
    GrepTool,
    FindTool,
    LsTool,
    DelegateTool,
]

# Name → class mapping for resolving agent tool lists
TOOL_REGISTRY: dict[str, type[Tool]] = {cls.name: cls for cls in ALL_TOOLS}

# Category → set of tool names, derived from class category attribute
CATEGORY_TOOLS: dict[ToolCategory, frozenset[str]] = {
    cat: frozenset(cls.name for cls in ALL_TOOLS if cls.category == cat)
    for cat in ToolCategory
}

# Tool names that have side effects (write to files or execute shell commands).
# Agents with any of these tools are NOT read-only.
WRITE_CATEGORIES: frozenset[ToolCategory] = frozenset({
    ToolCategory.file,
    ToolCategory.shell,
})


def resolve_tools(names: list[str]) -> list[type[Tool]]:
    """Resolve tool name strings to Tool classes, skipping unknown names."""
    return [TOOL_REGISTRY[n] for n in names if n in TOOL_REGISTRY]


def tools_in_category(category: ToolCategory) -> frozenset[str]:
    """Return all tool names belonging to a category."""
    return CATEGORY_TOOLS.get(category, frozenset())


def is_read_only_tool_set(tool_names: list[str]) -> bool:
    """True if none of the given tool names belong to a write category."""
    write_names = set()
    for cat in WRITE_CATEGORIES:
        write_names |= CATEGORY_TOOLS.get(cat, frozenset())
    return not any(t in write_names for t in tool_names)


def has_write_tool(tool_names: list[str]) -> bool:
    """True if any of the given tool names belong to a write category."""
    write_names = set()
    for cat in WRITE_CATEGORIES:
        write_names |= CATEGORY_TOOLS.get(cat, frozenset())
    return any(t in write_names for t in tool_names)
