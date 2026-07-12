"""路径边界保护，用于文件和搜索工具。

确保工具不能访问项目 work_dir 之外的路径。
防止 Agent 读取或修改系统文件、用户凭据等敏感数据。
"""

from __future__ import annotations

from pathlib import Path


class PathBoundaryError(Exception):
    """路径尝试逃逸 work_dir 边界时抛出。"""

    def __init__(self, path: Path, work_dir: Path):
        self.path = path
        self.work_dir = work_dir
        super().__init__(
            f"路径 '{path}' 在项目目录 '{work_dir}' 之外。"
            f"路径边界保护已拒绝访问。"
        )


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