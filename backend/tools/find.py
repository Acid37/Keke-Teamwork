import os
from pathlib import Path
from backend.types import ToolResult
from backend.tools.base import Tool, ToolCategory


class FindTool(Tool):
    """Find files by name pattern."""

    name = "find_files"
    category = ToolCategory.search
    description = "Find files matching a glob pattern."
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern to match files (e.g., '*.py', '**/*.ts')"},
            "path": {"type": "string", "description": "Directory to search in (default: work_dir)"},
        },
        "required": ["pattern"],
    }

    async def execute(self, **kwargs) -> ToolResult:
        try:
            pattern = kwargs["pattern"]
            path_str = kwargs.get("path")

            # Resolve path
            if path_str:
                search_path = Path(path_str)
                if not search_path.is_absolute():
                    search_path = self._ctx.work_dir / search_path
            else:
                search_path = self._ctx.work_dir

            if not search_path.exists():
                return (False, f"Path not found: {search_path}")
            if not search_path.is_dir():
                return (False, f"Not a directory: {search_path}")

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
                    matches.append("... (results truncated)")
                return (True, "\n".join(matches))
            else:
                return (True, "No files found")

        except Exception as e:
            return (False, f"Error: {e}")
