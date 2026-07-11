from pathlib import Path
from backend.types import ToolResult
from backend.tools.base import Tool, ToolCategory
from backend.safety.path_guard import resolve_path, PathBoundaryError


class WriteTool(Tool):
    """写入或创建文件。"""

    name = "write_file"
    category = ToolCategory.file
    description = "写入内容到文件。如果文件不存在则创建，已存在则覆盖。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对于 work_dir 或绝对路径）"},
            "content": {"type": "string", "description": "要写入的文件内容"},
        },
        "required": ["path", "content"],
    }

    async def execute(self, **kwargs) -> ToolResult:
        try:
            path_str = kwargs["path"]
            content = kwargs["content"]

            # Resolve path relative to work_dir, with boundary protection
            try:
                file_path = resolve_path(path_str, self._ctx.work_dir)
            except PathBoundaryError as e:
                return (False, str(e))

            # Get relative path for display
            try:
                rel_path = file_path.relative_to(self._ctx.work_dir)
            except ValueError:
                rel_path = file_path

            # Check if staging is available
            if hasattr(self._ctx, "staging") and self._ctx.staging:
                self._ctx.staging.stage_write(file_path, content)
                return (True, f"File written: {rel_path} ({len(content)} bytes)")
            else:
                # Create parent directories
                file_path.parent.mkdir(parents=True, exist_ok=True)

                # Write directly
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)

                return (True, f"File written: {rel_path} ({len(content)} bytes)")

        except Exception as e:
            return (False, f"写入文件错误: {e}")
