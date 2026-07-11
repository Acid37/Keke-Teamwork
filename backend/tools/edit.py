from pathlib import Path
from backend.types import ToolResult
from backend.tools.base import Tool, ToolCategory


class EditTool(Tool):
    """Search and replace text in files."""

    name = "edit_file"
    category = ToolCategory.file
    description = "Replace text in a file. The old_text must match exactly (including whitespace)."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to edit (relative to work_dir or absolute)"},
            "old_text": {"type": "string", "description": "Text to find (must match exactly)"},
            "new_text": {"type": "string", "description": "Text to replace with"},
        },
        "required": ["path", "old_text", "new_text"],
    }

    async def execute(self, **kwargs) -> ToolResult:
        try:
            path_str = kwargs["path"]
            old_text = kwargs["old_text"]
            new_text = kwargs["new_text"]

            # Resolve path relative to work_dir
            file_path = Path(path_str)
            if not file_path.is_absolute():
                file_path = self._ctx.work_dir / file_path

            # Check file exists
            if not file_path.exists():
                return (False, f"File not found: {file_path}")
            if not file_path.is_file():
                return (False, f"Not a file: {file_path}")

            # Read current content
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                try:
                    with open(file_path, "r", encoding="latin-1") as f:
                        content = f.read()
                except Exception as e:
                    return (False, f"Error reading file: {e}")

            # Count occurrences
            count = content.count(old_text)

            # If not found, try CRLF/LF normalized match
            if count == 0:
                content_normalized = content.replace("\r\n", "\n")
                old_text_normalized = old_text.replace("\r\n", "\n")
                count = content_normalized.count(old_text_normalized)

                if count == 0:
                    return (False, "Text not found in file. Make sure the text matches exactly.")
                elif count > 1:
                    return (False, f"Text matches {count} locations. Provide more context for a unique match.")

                # Perform replacement on normalized content
                new_content_normalized = content_normalized.replace(old_text_normalized, new_text, 1)

                # Preserve original line endings
                if "\r\n" in content:
                    new_content = new_content_normalized.replace("\n", "\r\n")
                else:
                    new_content = new_content_normalized
            else:
                if count > 1:
                    return (False, f"Text matches {count} locations. Provide more context for a unique match.")

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
            return (False, f"Error: {e}")
