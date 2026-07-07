from backend.tools.base import Tool
from backend.tools.read import ReadTool
from backend.tools.write import WriteTool
from backend.tools.edit import EditTool
from backend.tools.console import ConsoleTool
from backend.tools.grep import GrepTool
from backend.tools.find import FindTool
from backend.tools.ls import LsTool

ALL_TOOLS = [ReadTool, WriteTool, EditTool, ConsoleTool, GrepTool, FindTool, LsTool]

# Name → class mapping for resolving agent tool lists
TOOL_REGISTRY: dict[str, type[Tool]] = {cls.name: cls for cls in ALL_TOOLS}


def resolve_tools(names: list[str]) -> list[type[Tool]]:
    """Resolve tool name strings to Tool classes, skipping unknown names."""
    return [TOOL_REGISTRY[n] for n in names if n in TOOL_REGISTRY]
