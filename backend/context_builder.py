"""项目上下文构建。

扫描工作目录，生成项目背景摘要（语言、框架、目录结构），
注入 Agent 系统提示词，帮助 Agent 了解项目环境。
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 忽略的目录名（扫描时跳过）
_SKIP_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv",
    "venv", "env", ".tox", ".mypy_cache", ".pytest_cache", "dist",
    "build", ".eggs", "*.egg-info", ".idea", ".vscode", "egg-info",
}

# 最大扫描深度
_MAX_DEPTH = 2

# 每层最大条目数
_MAX_ENTRIES_PER_LEVEL = 15

# 摘要最大字符数
_MAX_SUMMARY_CHARS = 2000


def build_project_context(work_dir: Path) -> dict:
    """扫描工作目录，生成项目上下文摘要。

    返回字典结构：
    {
        "languages": ["python", "typescript"],
        "frameworks": ["fastapi", "react"],
        "structure": "backend/\n  ...\nfrontend/\n  ...",
        "summary": "Python + TypeScript 项目，使用 FastAPI 和 React..."
    }
    """
    languages: list[str] = []
    frameworks: list[str] = []

    # ─── 检测语言和框架 ───
    _detect_languages(work_dir, languages, frameworks)

    # ─── 生成目录树摘要 ───
    structure = _build_tree_summary(work_dir)

    # ─── 生成文字摘要 ───
    parts: list[str] = []
    if languages:
        parts.append("语言：" + "、".join(languages))
    if frameworks:
        parts.append("框架/工具：" + "、".join(frameworks))
    if structure:
        parts.append("目录结构：\n" + structure)
    summary = "\n".join(parts)
    if len(summary) > _MAX_SUMMARY_CHARS:
        summary = summary[:_MAX_SUMMARY_CHARS] + "\n...(项目摘要已截断)"

    return {
        "languages": languages,
        "frameworks": frameworks,
        "structure": structure,
        "summary": summary,
    }


def _detect_languages(
    work_dir: Path,
    languages: list[str],
    frameworks: list[str],
) -> None:
    """通过配置文件检测项目使用的语言和框架。"""
    # Python
    if (work_dir / "pyproject.toml").exists() or (work_dir / "setup.py").exists():
        languages.append("python")
        _detect_python_frameworks(work_dir, frameworks)

    # JavaScript / TypeScript
    pkg = work_dir / "package.json"
    if pkg.exists():
        languages.append("javascript")
        _detect_js_frameworks(pkg, languages, frameworks)

    tsconfig = work_dir / "tsconfig.json"
    if tsconfig.exists() and "typescript" not in languages:
        languages.append("typescript")

    # Go
    if (work_dir / "go.mod").exists():
        languages.append("go")

    # Rust
    if (work_dir / "Cargo.toml").exists():
        languages.append("rust")

    # Java
    if (work_dir / "pom.xml").exists() or (work_dir / "build.gradle").exists():
        languages.append("java")

    # C/C++
    if (work_dir / "CMakeLists.txt").exists():
        languages.append("c/c++")


def _detect_python_frameworks(work_dir: Path, frameworks: list[str]) -> None:
    """从 pyproject.toml 检测 Python 框架。"""
    pyproject = work_dir / "pyproject.toml"
    if not pyproject.exists():
        return
    try:
        text = pyproject.read_text(encoding="utf-8")
    except Exception:
        return
    text_lower = text.lower()
    candidates = [
        ("fastapi", "fastapi"),
        ("flask", "flask"),
        ("django", "django"),
        ("pydantic", "pydantic"),
        ("pytest", "pytest"),
        ("uvicorn", "uvicorn"),
        ("httpx", "httpx"),
        ("aiohttp", "aiohttp"),
    ]
    for keyword, name in candidates:
        if keyword in text_lower:
            frameworks.append(name)


def _detect_js_frameworks(
    pkg: Path,
    languages: list[str],
    frameworks: list[str],
) -> None:
    """从 package.json 检测 JS/TS 框架。"""
    import json
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except Exception:
        return
    deps: dict = {}
    deps.update(data.get("dependencies", {}))
    deps.update(data.get("devDependencies", {}))
    candidates = [
        ("react", "react"),
        ("vue", "vue"),
        ("next", "next.js"),
        ("vite", "vite"),
        ("express", "express"),
        ("typescript", "typescript"),
        ("tailwindcss", "tailwindcss"),
        ("svelte", "svelte"),
    ]
    for pkg_name, display_name in candidates:
        if pkg_name in deps:
            frameworks.append(display_name)


def _build_tree_summary(work_dir: Path) -> str:
    """生成简化的目录树文本。"""
    lines: list[str] = []

    def _scan(path: Path, prefix: str, depth: int) -> None:
        if depth > _MAX_DEPTH:
            return
        try:
            children = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        except (PermissionError, OSError):
            return
        # 过滤跳过目录
        visible = [
            child for child in children
            if child.name not in _SKIP_DIRS
            and not child.name.endswith(".egg-info")
        ]
        visible = visible[:_MAX_ENTRIES_PER_LEVEL]
        for i, child in enumerate(visible):
            is_last = (i == len(visible) - 1)
            connector = "└── " if is_last else "├── "
            suffix = "/" if child.is_dir() else ""
            lines.append(f"{prefix}{connector}{child.name}{suffix}")
            if child.is_dir():
                extension = "    " if is_last else "│   "
                _scan(child, prefix + extension, depth + 1)

    _scan(work_dir, "", 0)
    return "\n".join(lines)