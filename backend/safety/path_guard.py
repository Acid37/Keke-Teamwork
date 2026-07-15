"""路径边界保护，用于文件和搜索工具。

确保工具不能访问项目 work_dir 之外的路径。
防止 Agent 读取或修改系统文件、用户凭据等敏感数据。

v0.3：新增 per-agent 路径约束（allowed_paths / denied_paths）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any  # noqa: F401 — AgentPermissions 惰性引用


class PathBoundaryError(Exception):
    """路径尝试逃逸 work_dir 边界时抛出。"""

    def __init__(self, path: Path, work_dir: Path):
        self.path = path
        self.work_dir = work_dir
        super().__init__(
            f"路径 '{path}' 在项目目录 '{work_dir}' 之外。"
            f"路径边界保护已拒绝访问。"
        )


class AgentPathDeniedError(Exception):
    """Agent 权限禁止访问该路径时抛出。"""

    def __init__(self, path: Path, reason: str = ""):
        self.path = path
        self.reason = reason
        msg = f"Agent 权限禁止访问路径 '{path}'"
        if reason:
            msg += f"：{reason}"
        super().__init__(msg)


def resolve_path(path_str: str, work_dir: Path) -> Path:
    """解析相对于 work_dir 的路径字符串。

    - 相对路径会与 work_dir 拼接。
    - 绝对路径直接使用，但必须在 work_dir 范围内。
    - 符号链接会被解析以检查真实目标。

    参数：
        path_str: 工具参数中的路径字符串。
        work_dir: 项目工作目录。

    返回：
        解析后的绝对路径。

    抛出：
        PathBoundaryError: 解析后的路径在 work_dir 之外。
    """
    raw = Path(path_str)
    if not raw.is_absolute():
        resolved = (work_dir / raw).resolve()
    else:
        resolved = raw.resolve()

    work_dir_resolved = work_dir.resolve()

    # 检查解析后的路径是否在 work_dir 内
    try:
        resolved.relative_to(work_dir_resolved)
    except ValueError:
        raise PathBoundaryError(resolved, work_dir_resolved) from None

    return resolved


def is_within_work_dir(path: Path, work_dir: Path) -> bool:
    """检查路径是否在 work_dir 内，不抛出异常。

    参数：
        path: 要检查的路径（应为已解析的绝对路径）。
        work_dir: 项目工作目录。

    返回：
        路径在 work_dir 内返回 True，否则返回 False。
    """
    try:
        path.resolve().relative_to(work_dir.resolve())
        return True
    except (ValueError, OSError):
        return False


def check_agent_path_permissions(
    resolved_path: Path,
    work_dir: Path,
    agent_permissions: Any,  # AgentPermissions | None
) -> None:
    """检查 Agent 是否有权访问给定路径（在 work_dir 边界检查之后调用）。

    校验顺序：denied_paths → allowed_paths。
    - denied_paths 优先：一旦匹配，直接拒绝。
    - allowed_paths：若配置了白名单，路径必须匹配至少一条。
    - permissions 为 None 时一律放行（向后兼容）。

    参数：
        resolved_path: 已经 resolve_path() 处理过的绝对路径。
        work_dir: 项目工作目录（已 resolve）。
        agent_permissions: AgentPermissions 或 None。

    抛出：
        AgentPathDeniedError: 权限拒绝。
    """
    if agent_permissions is None:
        return

    try:
        rel = resolved_path.relative_to(work_dir.resolve())
    except ValueError:
        # 不在 work_dir 内——resolve_path 已拦截，兜底
        raise AgentPathDeniedError(resolved_path, "不在项目目录内") from None

    rel_str = rel.as_posix()

    # 1) denied_paths 优先
    denied = getattr(agent_permissions, "denied_paths", None) or []
    for pattern in denied:
        if _glob_match(rel_str, pattern):
            raise AgentPathDeniedError(resolved_path, f"匹配拒绝规则 '{pattern}'")

    # 2) allowed_paths 白名单
    allowed = getattr(agent_permissions, "allowed_paths", None)
    if allowed:
        for pattern in allowed:
            if _glob_match(rel_str, pattern):
                return
        raise AgentPathDeniedError(
            resolved_path,
            f"不在允许路径范围内（allowed_paths={allowed}）",
        )


def _glob_match(rel_path: str, pattern: str) -> bool:
    """用 Path.match 做路径 glob 匹配，正确区分目录分隔符。"""
    return Path(rel_path).match(pattern)