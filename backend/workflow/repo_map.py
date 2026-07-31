"""Repo Map — 项目结构地图。

深度扫描工作目录，生成包含函数/类签名的紧凑文本，
注入各阶段 Agent 的 system prompt，避免 Agent 重复用工具探索代码。

输出示例::

    backend/
      workflow/
        engine.py: class WorkflowRunner — execute(), handle_user_command(), _run_planner()
        types.py: class SubTask, class TaskList, class DiffSet, class ReviewReport
      cli.py: main(), _run_workflow_cli()
    tests/
      test_workflow.py: TestExecute, TestApprovePlan

设计原则：
- 只扫描源码文件（.py/.ts/.tsx/.js/.jsx/.go/.rs/.java）
- 用 AST 提取 Python 签名，正则提取其他语言
- token 预算控制（默认 ~2000 token）
- 跳过 .gitignore 中的目录
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# ─── 常量 ───

_SKIP_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv",
    "venv", "env", ".tox", ".mypy_cache", ".pytest_cache", "dist",
    "build", ".eggs", ".idea", ".vscode", ".trae-cn", "egg-info",
    ".next", ".nuxt", "target", "bin", "obj",
}

_SKIP_SUFFIXES = {".pyc", ".pyo", ".so", ".dll", ".exe", ".png", ".jpg",
                  ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip",
                  ".tar", ".gz", ".lock", ".min.js", ".min.css"}

_SOURCE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs",
                      ".java", ".kt", ".swift", ".rb", ".cpp", ".c", ".h"}

_MAX_DEPTH = 4
_MAX_FILES = 200
_MAX_FILE_SIGS = 8  # 每个文件最多提取的签名数
_MAX_CHARS = 6000   # 总字符上限（约 2000 token）


# ─── 公开接口 ───


def build_repo_map(work_dir: Path, *, max_chars: int = _MAX_CHARS) -> str:
    """构建项目结构地图。

    Args:
        work_dir: 项目根目录
        max_chars: 输出最大字符数

    Returns:
        紧凑的项目结构文本，可直接注入 prompt
    """
    try:
        lines = _scan_directory(work_dir, max_chars)
        result = "\n".join(lines)
        if len(result) > max_chars:
            result = result[:max_chars] + "\n...(repo map 已截断)"
        return result
    except Exception as e:
        logger.warning("Failed to build repo map: %s", e)
        return ""


# ─── 目录扫描 ───


def _scan_directory(work_dir: Path, max_chars: int) -> list[str]:
    """递归扫描目录，返回 repo map 行列表。"""
    lines: list[str] = []
    file_count = 0

    def _scan(path: Path, prefix: str, depth: int) -> None:
        nonlocal file_count
        if depth > _MAX_DEPTH or file_count > _MAX_FILES:
            return
        if len("\n".join(lines)) > max_chars:
            return

        try:
            children = sorted(
                path.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except (PermissionError, OSError):
            return

        # 过滤
        visible = [
            child for child in children
            if child.name not in _SKIP_DIRS
            and not any(child.name.endswith(s) for s in _SKIP_SUFFIXES)
            and not child.name.startswith(".")
        ]

        for child in visible:
            if len("\n".join(lines)) > max_chars:
                lines.append(f"{prefix}...")
                return

            if child.is_dir():
                # 只扫描包含源码的目录
                if _has_source_files(child, depth):
                    lines.append(f"{prefix}{child.name}/")
                    extension = "  "
                    _scan(child, prefix + extension, depth + 1)
            elif child.suffix in _SOURCE_EXTENSIONS:
                sigs = _extract_signatures(child)
                if sigs:
                    lines.append(f"{prefix}{child.name}: {sigs}")
                else:
                    lines.append(f"{prefix}{child.name}")
                file_count += 1

    _scan(work_dir, "", 0)
    return lines


def _has_source_files(path: Path, depth: int) -> bool:
    """检查目录（或其子目录）是否包含源码文件，避免扫描空目录。"""
    if depth >= _MAX_DEPTH:
        return False
    try:
        for child in path.iterdir():
            if child.is_file() and child.suffix in _SOURCE_EXTENSIONS:
                return True
            if child.is_dir() and child.name not in _SKIP_DIRS:
                if _has_source_files(child, depth + 1):
                    return True
    except (PermissionError, OSError):
        pass
    return False


# ─── 签名提取 ───


def _extract_signatures(path: Path) -> str:
    """从源码文件提取函数/类签名，返回紧凑文本。"""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""

    ext = path.suffix
    if ext == ".py":
        return _extract_py_signatures(content)
    elif ext in (".ts", ".tsx", ".js", ".jsx"):
        return _extract_js_signatures(content)
    elif ext == ".go":
        return _extract_go_signatures(content)
    elif ext == ".rs":
        return _extract_rust_signatures(content)
    elif ext in (".java", ".kt"):
        return _extract_java_signatures(content)
    else:
        return ""


def _extract_py_signatures(content: str) -> str:
    """用 AST 提取 Python 函数/类签名。"""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return ""

    sigs: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if len(sigs) >= _MAX_FILE_SIGS:
            break

        if isinstance(node, ast.ClassDef):
            # 提取类的方法（前 3 个）
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not item.name.startswith("_"):
                        methods.append(item.name + "()")
                    if len(methods) >= 3:
                        break
            if methods:
                sigs.append(f"class {node.name} — {', '.join(methods)}")
            else:
                sigs.append(f"class {node.name}")

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
                sigs.append(f"{prefix}{node.name}()")

    return ", ".join(sigs)


def _extract_js_signatures(content: str) -> str:
    """正则提取 JS/TS 函数/类签名。"""
    sigs: list[str] = []

    # function declarations
    for m in re.finditer(r"(?:export\s+)?(?:async\s+)?function\s+(\w+)", content):
        if len(sigs) >= _MAX_FILE_SIGS:
            break
        sigs.append(m.group(1) + "()")

    # arrow functions / const
    for m in re.finditer(r"(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(", content):
        if len(sigs) >= _MAX_FILE_SIGS:
            break
        if not m.group(1).startswith("_"):
            sigs.append(m.group(1) + "()")

    # class declarations
    for m in re.finditer(r"(?:export\s+)?class\s+(\w+)", content):
        if len(sigs) >= _MAX_FILE_SIGS:
            break
        sigs.append(f"class {m.group(1)}")

    # React components (function Component())
    for m in re.finditer(r"function\s+([A-Z]\w*)\s*\(", content):
        name = m.group(1) + "()"
        if name not in sigs:
            sigs.append(name)

    return ", ".join(sigs[:_MAX_FILE_SIGS])


def _extract_go_signatures(content: str) -> str:
    """正则提取 Go 函数/类型签名。"""
    sigs: list[str] = []

    for m in re.finditer(r"^func\s+(?:\([^)]*\)\s+)?(\w+)\s*\(", content, re.MULTILINE):
        if len(sigs) >= _MAX_FILE_SIGS:
            break
        sigs.append(m.group(1) + "()")

    for m in re.finditer(r"^type\s+(\w+)\s+", content, re.MULTILINE):
        if len(sigs) >= _MAX_FILE_SIGS:
            break
        sigs.append(f"type {m.group(1)}")

    return ", ".join(sigs[:_MAX_FILE_SIGS])


def _extract_rust_signatures(content: str) -> str:
    """正则提取 Rust 函数/结构体签名。"""
    sigs: list[str] = []

    for m in re.finditer(r"(?:pub\s+)?(?:async\s+)?fn\s+(\w+)", content):
        if len(sigs) >= _MAX_FILE_SIGS:
            break
        sigs.append(m.group(1) + "()")

    for m in re.finditer(r"(?:pub\s+)?struct\s+(\w+)", content):
        if len(sigs) >= _MAX_FILE_SIGS:
            break
        sigs.append(f"struct {m.group(1)}")

    return ", ".join(sigs[:_MAX_FILE_SIGS])


def _extract_java_signatures(content: str) -> str:
    """正则提取 Java/Kotlin 类/方法签名。"""
    sigs: list[str] = []

    for m in re.finditer(r"(?:public|private|protected)?\s*(?:class|interface)\s+(\w+)", content):
        if len(sigs) >= _MAX_FILE_SIGS:
            break
        sigs.append(f"class {m.group(1)}")

    for m in re.finditer(r"(?:public|private|protected)\s+(?:static\s+)?(?:\w+\s+)+(\w+)\s*\(", content):
        if len(sigs) >= _MAX_FILE_SIGS:
            break
        name = m.group(1)
        if name not in sigs:
            sigs.append(name + "()")

    return ", ".join(sigs[:_MAX_FILE_SIGS])
