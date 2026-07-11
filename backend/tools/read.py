from pathlib import Path
from backend.types import ToolResult
from backend.tools.base import Tool, ToolCategory


class ReadTool(Tool):
    """Read file contents with line numbers."""

    name = "read_file"
    category = ToolCategory.search
    description = "Read the contents of a file. Supports line range selection and handles large files intelligently."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to read (relative to work_dir or absolute)"},
            "start_line": {"type": "integer", "description": "Start line number (1-based, optional)"},
            "end_line": {"type": "integer", "description": "End line number (1-based, optional)"},
        },
        "required": ["path"],
    }

    async def execute(self, **kwargs) -> ToolResult:
        try:
            path_str = kwargs["path"]
            start_line = kwargs.get("start_line")
            end_line = kwargs.get("end_line")

            # Resolve path relative to work_dir
            file_path = Path(path_str)
            if not file_path.is_absolute():
                file_path = self._ctx.work_dir / file_path

            # Check file exists
            if not file_path.exists():
                return (False, f"File not found: {file_path}")
            if not file_path.is_file():
                return (False, f"Not a file: {file_path}")

            # Detect binary files
            try:
                with open(file_path, "rb") as f:
                    chunk = f.read(8192)
                    if b"\x00" in chunk:
                        return (False, f"Binary file detected: {file_path}")
            except Exception as e:
                return (False, f"Error reading file: {e}")

            # Read with utf-8 encoding, fallback to latin-1
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except UnicodeDecodeError:
                try:
                    with open(file_path, "r", encoding="latin-1") as f:
                        lines = f.readlines()
                except Exception as e:
                    return (False, f"Error reading file: {e}")

            total_lines = len(lines)

            # Handle large files
            if total_lines > 500 and start_line is None and end_line is None:
                # Show first 50 + last 50 lines
                first_50 = lines[:50]
                last_50 = lines[-50:]
                omitted = total_lines - 100

                content_lines = []
                for i, line in enumerate(first_50, start=1):
                    content_lines.append(f"{i:4d} | {line.rstrip()}")

                content_lines.append(f"     | ... ({omitted} lines omitted) ...")

                for i, line in enumerate(last_50, start=total_lines - 49):
                    content_lines.append(f"{i:4d} | {line.rstrip()}")

                content = "\n".join(content_lines)
            elif start_line is not None or end_line is not None:
                # Show specific range (1-based)
                start_idx = (start_line - 1) if start_line else 0
                end_idx = end_line if end_line else total_lines

                # Clamp to valid range
                start_idx = max(0, min(start_idx, total_lines))
                end_idx = max(start_idx, min(end_idx, total_lines))

                selected_lines = lines[start_idx:end_idx]
                content_lines = []
                for i, line in enumerate(selected_lines, start=start_idx + 1):
                    content_lines.append(f"{i:4d} | {line.rstrip()}")

                content = "\n".join(content_lines)
            else:
                # Show all lines
                content_lines = []
                for i, line in enumerate(lines, start=1):
                    content_lines.append(f"{i:4d} | {line.rstrip()}")
                content = "\n".join(content_lines)

            return (True, content)

        except Exception as e:
            return (False, f"Error: {e}")
