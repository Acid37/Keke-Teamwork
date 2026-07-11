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

# 工具名 → 类映射，用于解析 Agent 工具列表
TOOL_REGISTRY: dict[str, type[Tool]] = {cls.name: cls for cls in ALL_TOOLS}

# 分类 → 工具名集合，从工具类的 category 属性派生
CATEGORY_TOOLS: dict[ToolCategory, frozenset[str]] = {
    cat: frozenset(cls.name for cls in ALL_TOOLS if cls.category == cat)
    for cat in ToolCategory
}

# 有副作用的工具分类（写文件或执行 shell 命令）。
# 拥有这些分类工具的 Agent 不是只读 Agent。
WRITE_CATEGORIES: frozenset[ToolCategory] = frozenset({
    ToolCategory.file,
    ToolCategory.shell,
})


def resolve_tools(names: list[str]) -> list[type[Tool]]:
    """将工具名字符串解析为 Tool 类，跳过未知的名称。"""
    return [TOOL_REGISTRY[n] for n in names if n in TOOL_REGISTRY]


def tools_in_category(category: ToolCategory) -> frozenset[str]:
    """返回属于指定分类的所有工具名。"""
    return CATEGORY_TOOLS.get(category, frozenset())


def is_read_only_tool_set(tool_names: list[str]) -> bool:
    """判断工具集是否只读（不含任何写分类工具）。"""
    write_names = set()
    for cat in WRITE_CATEGORIES:
        write_names |= CATEGORY_TOOLS.get(cat, frozenset())
    return not any(t in write_names for t in tool_names)


def has_write_tool(tool_names: list[str]) -> bool:
    """判断工具集是否包含写工具（属于写分类的任意工具）。"""
    write_names = set()
    for cat in WRITE_CATEGORIES:
        write_names |= CATEGORY_TOOLS.get(cat, frozenset())
    return any(t in write_names for t in tool_names)
