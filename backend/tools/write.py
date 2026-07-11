from pathlib import Path
from backend.types import ToolResult
from backend.tools.base import Tool, ToolCategory


class WriteTool(Tool):
    """Write or create files."""

    name = "write_file"
    category = ToolCategory.file
    description = "Write content to a file. Creates the file if it doesn't exist, overwrites if it does."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to write (relative to work_dir or absolute)"},
            "content": {"type": "string", "description": "Content to write to the file"},
        },
        "required": ["path", "content"],
    }

    async def execute(self, **kwargs) -> ToolResult:
        try:
            path_str = kwargs["path"]
            content = kwargs["content"]

            # Resolve path relative to work_dir
            file_path = Path(path_str)
            if not file_path.is_absolute():
                file_path = self._ctx.work_dir / file_path

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
            return (False, f"Error writing file: {e}")
