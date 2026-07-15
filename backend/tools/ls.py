from pathlib import Path
from backend.types import ToolResult
from backend.tools.base import Tool, ToolCategory


class LsTool(Tool):
    """以树形结构列出目录内容。"""

    name = "list_directory"
    category = ToolCategory.search
    description = "以树形结构列出目录内容，可配置显示深度。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目录路径（默认：work_dir）"},
            "depth": {"type": "integer", "description": "目录树显示深度（默认：2）", "default": 2},
        },
        "required": [],
    }

    async def execute(self, **kwargs) -> ToolResult:
        try:
            path_str = kwargs.get("path")
            depth = kwargs.get("depth", 2)

            target_path = self._resolve_and_check_path(path_str)
            if isinstance(target_path, tuple):
                return target_path

            if not target_path.exists():
                return (False, f"路径未找到: {target_path}")
            if not target_path.is_dir():
                return (False, f"不是一个目录: {target_path}")

            # Directories to skip
            skip_dirs = {".git", "node_modules", "__pycache__", "venv", ".venv", "dist", "build", ".next", ".cache", ".idea"}

            # Build tree
            tree_lines = []

            def build_tree(current_path: Path, indent: int, max_depth: int):
                if indent > max_depth:
                    return

                try:
                    # Get sorted list of items
                    items = sorted(current_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
                except PermissionError:
                    return

                for item in items:
                    # Skip hidden and excluded directories
                    if item.is_dir():
                        if item.name in skip_dirs or item.name.startswith("."):
                            continue

                        # Add directory with trailing slash
                        tree_lines.append("  " * indent + item.name + "/")

                        # Recurse
                        if indent < max_depth:
                            build_tree(item, indent + 1, max_depth)
                    else:
                        # Add file
                        tree_lines.append("  " * indent + item.name)

            # Start building tree from target_path
            try:
                tree_lines.append(target_path.name + "/")
                build_tree(target_path, 1, depth)
            except Exception as e:
                return (False, f"列出目录错误: {e}")

            tree_string = "\n".join(tree_lines)
            return (True, tree_string)

        except Exception as e:
            return (False, f"错误: {e}")
