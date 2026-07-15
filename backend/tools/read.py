from pathlib import Path
from backend.types import ToolResult
from backend.tools.base import Tool, ToolCategory
from backend.safety.path_guard import resolve_path, check_agent_path_permissions, PathBoundaryError, AgentPathDeniedError


class ReadTool(Tool):
    """读取文件内容，带行号显示。"""

    name = "read_file"
    category = ToolCategory.search
    description = "读取文件内容。支持行范围选择，智能处理大文件。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对于 work_dir 或绝对路径）"},
            "start_line": {"type": "integer", "description": "起始行号（从 1 开始，可选）"},
            "end_line": {"type": "integer", "description": "结束行号（从 1 开始，可选）"},
        },
        "required": ["path"],
    }

    async def execute(self, **kwargs) -> ToolResult:
        try:
            path_str = kwargs["path"]
            start_line = kwargs.get("start_line")
            end_line = kwargs.get("end_line")

            # Resolve path relative to work_dir, with boundary protection
            try:
                file_path = resolve_path(path_str, self._ctx.work_dir)
            except PathBoundaryError as e:
                return (False, str(e))

            # Check agent-level path permissions
            try:
                check_agent_path_permissions(file_path, self._ctx.work_dir, self._ctx.agent_permissions)
            except AgentPathDeniedError as e:
                return (False, str(e))

            # Check file exists
            if not file_path.exists():
                return (False, f"文件未找到: {file_path}")
            if not file_path.is_file():
                return (False, f"不是一个文件: {file_path}")

            # Detect binary files
            try:
                with open(file_path, "rb") as f:
                    chunk = f.read(8192)
                    if b"\x00" in chunk:
                        return (False, f"检测到二进制文件: {file_path}")
            except Exception as e:
                return (False, f"读取文件错误: {e}")

            # Read with utf-8 encoding, fallback to latin-1
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except UnicodeDecodeError:
                try:
                    with open(file_path, "r", encoding="latin-1") as f:
                        lines = f.readlines()
                except Exception as e:
                    return (False, f"读取文件错误: {e}")

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
            return (False, f"错误: {e}")
