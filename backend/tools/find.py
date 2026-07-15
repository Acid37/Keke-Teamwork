import os
from pathlib import Path
from backend.types import ToolResult
from backend.tools.base import Tool, ToolCategory
from backend.safety.path_guard import resolve_path, check_agent_path_permissions, PathBoundaryError, AgentPathDeniedError


class FindTool(Tool):
    """按名称模式查找文件。"""

    name = "find_files"
    category = ToolCategory.search
    description = "查找匹配 glob 模式的文件。"
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "文件匹配的 glob 模式（如 '*.py', '**/*.ts'）"},
            "path": {"type": "string", "description": "搜索目录（默认：work_dir）"},
        },
        "required": ["pattern"],
    }

    async def execute(self, **kwargs) -> ToolResult:
        try:
            pattern = kwargs["pattern"]
            path_str = kwargs.get("path")

            # Resolve path with boundary protection
            if path_str:
                try:
                    search_path = resolve_path(path_str, self._ctx.work_dir)
                except PathBoundaryError as e:
                    return (False, str(e))
            else:
                search_path = self._ctx.work_dir.resolve()

            # Check agent-level path permissions
            try:
                check_agent_path_permissions(search_path, self._ctx.work_dir, self._ctx.agent_permissions)
            except AgentPathDeniedError as e:
                return (False, str(e))

            if not search_path.exists():
                return (False, f"路径未找到: {search_path}")
            if not search_path.is_dir():
                return (False, f"不是一个目录: {search_path}")

            # Directories to skip
            skip_dirs = {".git", "node_modules", "__pycache__", "venv", ".venv", "dist", "build"}

            # Find files
            matches = []

            def should_skip(path: Path) -> bool:
                """Check if path contains any skip directories."""
                for part in path.parts:
                    if part in skip_dirs:
                        return True
                return False

            # Use rglob for recursive search
            for file_path in search_path.rglob(pattern):
                if file_path.is_file() and not should_skip(file_path.relative_to(search_path)):
                    try:
                        rel_path = file_path.relative_to(search_path)
                        matches.append(str(rel_path))
                    except ValueError:
                        continue

                    if len(matches) >= 200:
                        break

            if matches:
                # Sort results
                matches.sort()
                if len(matches) >= 200:
                    matches.append("... (结果已截断)")
                return (True, "\n".join(matches))
            else:
                return (True, "未找到匹配文件")

        except Exception as e:
            return (False, f"错误: {e}")
