from backend.types import ToolResult
from backend.tools.base import Tool, ToolCategory


class EditTool(Tool):
    """在文件中搜索并替换文本。"""

    name = "edit_file"
    category = ToolCategory.file
    description = "替换文件中的文本。old_text 必须与文件内容完全匹配（包括空白字符）。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对于 work_dir 或绝对路径）"},
            "old_text": {"type": "string", "description": "要查找的文本（必须完全匹配）"},
            "new_text": {"type": "string", "description": "替换后的文本"},
        },
        "required": ["path", "old_text", "new_text"],
    }

    async def execute(self, **kwargs) -> ToolResult:
        try:
            path_str = kwargs["path"]
            old_text = kwargs["old_text"]
            new_text = kwargs["new_text"]

            file_path = self._resolve_and_check_path(path_str)
            if isinstance(file_path, tuple):
                return file_path

            # Check file exists
            if not file_path.exists():
                return (False, f"文件未找到: {file_path}")
            if not file_path.is_file():
                return (False, f"不是一个文件: {file_path}")

            # Read current content
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                try:
                    with open(file_path, "r", encoding="latin-1") as f:
                        content = f.read()
                except Exception as e:
                    return (False, f"读取文件错误: {e}")

            # Count occurrences
            count = content.count(old_text)

            # If not found, try CRLF/LF normalized match
            if count == 0:
                content_normalized = content.replace("\r\n", "\n")
                old_text_normalized = old_text.replace("\r\n", "\n")
                count = content_normalized.count(old_text_normalized)

                if count == 0:
                    return (False, "未在文件中找到该文本。请确保文本与文件内容完全匹配。")
                elif count > 1:
                    return (False, f"文本匹配到 {count} 处。请提供更多上下文以确保唯一定位。")

                # Perform replacement on normalized content
                new_content_normalized = content_normalized.replace(old_text_normalized, new_text, 1)

                # Preserve original line endings
                if "\r\n" in content:
                    new_content = new_content_normalized.replace("\n", "\r\n")
                else:
                    new_content = new_content_normalized
            else:
                if count > 1:
                    return (False, f"文本匹配到 {count} 处。请提供更多上下文以确保唯一定位。")

                # Perform replacement
                new_content = content.replace(old_text, new_text, 1)

            # Write the file
            if hasattr(self._ctx, "staging") and self._ctx.staging:
                self._ctx.staging.stage_write(file_path, new_content)
            else:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(new_content)

            return (True, f"Edited: {path_str} (1 replacement)")

        except Exception as e:
            return (False, f"错误: {e}")
