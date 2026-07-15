import os
import re
import subprocess
from pathlib import Path
from backend.types import ToolResult
from backend.tools.base import Tool, ToolCategory
from backend.safety.path_guard import resolve_path, check_agent_path_permissions, PathBoundaryError, AgentPathDeniedError


class GrepTool(Tool):
    """使用正则表达式搜索文件内容。"""

    name = "grep_search"
    category = ToolCategory.search
    description = "在文件中搜索匹配模式。优先使用 ripgrep，不可用时回退到 Python 实现。"
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "搜索模式（支持正则表达式）"},
            "path": {"type": "string", "description": "搜索的目录或文件（默认：work_dir）"},
            "include": {"type": "string", "description": "文件过滤的 glob 模式（如 '*.py'）"},
        },
        "required": ["pattern"],
    }

    async def execute(self, **kwargs) -> ToolResult:
        try:
            pattern = kwargs["pattern"]
            path_str = kwargs.get("path")
            include = kwargs.get("include")

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

            # Try ripgrep first
            try:
                cmd = ["rg", "--json", pattern, str(search_path)]
                if include:
                    cmd.extend(["--glob", include])

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

                if result.returncode == 0:
                    # Parse ripgrep JSON output
                    matches = []
                    for line in result.stdout.strip().split("\n"):
                        if not line:
                            continue
                        try:
                            import json
                            data = json.loads(line)
                            if data.get("type") == "match":
                                file_path = data["data"]["path"]["text"]
                                line_num = data["data"]["line_number"]
                                line_text = data["data"]["lines"]["text"].rstrip()
                                matches.append(f"{file_path}:{line_num}:{line_text}")
                        except (json.JSONDecodeError, KeyError):
                            continue

                    if matches:
                        # Limit to 100 results
                        if len(matches) > 100:
                            matches = matches[:100]
                            matches.append("... (结果已截断)")
                        return (True, "\n".join(matches))
                    else:
                        return (True, "未找到匹配")
                elif result.returncode == 1:
                    # No matches
                    return (True, "未找到匹配")
                # If rg fails for other reasons, fall through to Python implementation

            except (FileNotFoundError, subprocess.TimeoutExpired):
                # rg not found or timed out, fall back to Python
                pass

            # Python fallback implementation
            matches = []
            skip_dirs = {".git", "node_modules", "__pycache__", "venv", ".venv"}

            try:
                pattern_re = re.compile(pattern, re.IGNORECASE)
            except re.error as e:
                return (False, f"无效的正则表达式: {e}")

            if search_path.is_file():
                files_to_search = [search_path]
            else:
                files_to_search = []
                for root, dirs, files in os.walk(search_path):
                    # Skip directories
                    dirs[:] = [d for d in dirs if d not in skip_dirs]

                    for file in files:
                        file_path = Path(root) / file

                        # Filter by include pattern
                        if include:
                            if not file_path.match(include):
                                continue

                        files_to_search.append(file_path)

            # Search files
            for file_path in files_to_search:
                if len(matches) >= 100:
                    break

                try:
                    # Skip binary files
                    with open(file_path, "rb") as f:
                        chunk = f.read(8192)
                        if b"\x00" in chunk:
                            continue

                    # Read and search
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            for line_num, line in enumerate(f, start=1):
                                if pattern_re.search(line):
                                    rel_path = file_path.relative_to(self._ctx.work_dir)
                                    matches.append(f"{rel_path}:{line_num}:{line.rstrip()}")
                                    if len(matches) >= 100:
                                        break
                    except UnicodeDecodeError:
                        continue
                except Exception:
                    continue

            if matches:
                if len(matches) >= 100:
                    matches.append("... (results truncated)")
                return (True, "\n".join(matches))
            else:
                return (True, "No matches found")

        except Exception as e:
            return (False, f"Error: {e}")
