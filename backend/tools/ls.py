from pathlib import Path
from backend.types import ToolResult
from backend.tools.base import Tool, ToolCategory


class LsTool(Tool):
    """List directory contents in tree format."""

    name = "list_directory"
    category = ToolCategory.search
    description = "List directory contents in a tree format with configurable depth."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path to list (default: work_dir)"},
            "depth": {"type": "integer", "description": "Depth of directory tree to display (default: 2)", "default": 2},
        },
        "required": [],
    }

    async def execute(self, **kwargs) -> ToolResult:
        try:
            path_str = kwargs.get("path")
            depth = kwargs.get("depth", 2)

            # Resolve path
            if path_str:
                target_path = Path(path_str)
                if not target_path.is_absolute():
                    target_path = self._ctx.work_dir / target_path
            else:
                target_path = self._ctx.work_dir

            if not target_path.exists():
                return (False, f"Path not found: {target_path}")
            if not target_path.is_dir():
                return (False, f"Not a directory: {target_path}")

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
                return (False, f"Error listing directory: {e}")

            tree_string = "\n".join(tree_lines)
            return (True, tree_string)

        except Exception as e:
            return (False, f"Error: {e}")
