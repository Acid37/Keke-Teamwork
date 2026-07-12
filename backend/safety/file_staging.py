"""文件写入暂存区（write-ahead staging）。

核心模式：写入前记录原始内容 → 立即写入磁盘 → 成功则生成 diff / 失败则回滚。

为什么立即写入磁盘（而非临时文件）？
因为 console 命令需要看到真实的磁盘状态。如果只写入临时文件，
后续的 console 命令（如 npm run build）无法读取新写入的文件。
"""

from __future__ import annotations

import difflib
import logging
from pathlib import Path

from backend.types import CommitResult, FileDiff

logger = logging.getLogger(__name__)


class FileStagingArea:
    """File write-ahead staging area with immediate materialization."""

    SKIP_DIRS = {
        ".git", "node_modules", "__pycache__", "venv", ".venv",
        "dist", "build", ".next", ".turbo", ".cache", ".idea",
    }
    MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB

    def __init__(self, work_dir: Path, linked_dirs: list[Path] | None = None):
        self._work_dir = work_dir.resolve()
        self._linked_dirs = linked_dirs or []
        # path → original content (None means file didn't exist = new file)
        self._baseline: dict[Path, str | None] = {}
        self._tracked_paths: set[Path] = set()
        self.capture_baseline()

    # ─── Baseline ───

    def capture_baseline(self) -> None:
        """Walk work_dir and record all text file contents."""
        dirs = [self._work_dir] + [d.resolve() for d in self._linked_dirs]
        for base in dirs:
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if self._should_skip(path):
                    continue
                try:
                    content = path.read_text(encoding="utf-8")
                    self._baseline[path.resolve()] = content
                    self._tracked_paths.add(path.resolve())
                except (UnicodeDecodeError, PermissionError, OSError):
                    pass  # binary or inaccessible

    def _should_skip(self, path: Path) -> bool:
        """Check if a path should be skipped during baseline capture."""
        if path.is_file() and path.stat().st_size > self.MAX_FILE_SIZE:
            return True
        parts = path.parts
        for skip in self.SKIP_DIRS:
            if skip in parts:
                return True
        return False

    # ─── Staging operations ───

    def stage_write(self, path: Path, content: str) -> None:
        """Stage a file write. Records baseline on first touch, then writes."""
        resolved = (self._work_dir / path).resolve() if not path.is_absolute() else path.resolve()

        # Record baseline if first time touching this file
        if resolved not in self._baseline:
            if resolved.exists():
                try:
                    self._baseline[resolved] = resolved.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    self._baseline[resolved] = None
            else:
                self._baseline[resolved] = None

        self._tracked_paths.add(resolved)

        # Write immediately to disk
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")

    def stage_edit(self, path: Path, old_text: str, new_text: str) -> None:
        """Stage a search-and-replace edit."""
        resolved = (self._work_dir / path).resolve() if not path.is_absolute() else path.resolve()

        try:
            current = resolved.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            raise ValueError(f"Cannot read file for editing: {e}") from e

        new_content = current.replace(old_text, new_text, 1)
        if new_content == current:
            raise ValueError("old_text not found in file (no replacement made)")

        self.stage_write(path, new_content)

    def observe_path(self, path: Path) -> None:
        """Add a path to tracking. Used before console commands that may modify files."""
        resolved = (self._work_dir / path).resolve() if not path.is_absolute() else path.resolve()
        if resolved not in self._baseline:
            if resolved.exists():
                try:
                    self._baseline[resolved] = resolved.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    self._baseline[resolved] = None
            else:
                self._baseline[resolved] = None
        self._tracked_paths.add(resolved)

    # ─── Commit / Rollback ───

    def commit(self) -> CommitResult:
        """Commit all staged changes. Compare baseline vs current disk state."""
        diffs: list[FileDiff] = []

        all_paths = set(self._baseline.keys()) | self._tracked_paths

        for resolved in sorted(all_paths):
            original = self._baseline.get(resolved)

            if resolved.exists():
                try:
                    current = resolved.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
            else:
                current = None

            if original == current:
                continue  # no change

            try:
                rel_path = resolved.relative_to(self._work_dir)
            except ValueError:
                rel_path = resolved

            if original is None and current is not None:
                action = "create"
                diff_text = self._make_diff(rel_path, "", current or "")
            elif original is not None and current is None:
                action = "delete"
                diff_text = self._make_diff(rel_path, original or "", "")
            else:
                action = "modify"
                diff_text = self._make_diff(rel_path, original or "", current or "")

            diffs.append(FileDiff(
                path=rel_path,
                action=action,
                diff_text=diff_text,
                new_content=current,
            ))

        combined = "\n".join(d.diff_text for d in diffs)
        summary = f"{len(diffs)} file(s) changed"
        if diffs:
            details = ", ".join(f"{d.action} {d.path}" for d in diffs[:5])
            if len(diffs) > 5:
                details += f", ... and {len(diffs) - 5} more"
            summary += f": {details}"

        return CommitResult(
            files_changed=len(diffs),
            diffs=diffs,
            combined_diff=combined,
            summary=summary,
        )

    def rollback(self) -> None:
        """Rollback all files to baseline state."""
        for resolved, original in self._baseline.items():
            try:
                if original is None:
                    # New file → delete
                    resolved.unlink(missing_ok=True)
                else:
                    # Modified file → restore
                    resolved.write_text(original, encoding="utf-8")
            except OSError as e:
                logger.warning("Failed to rollback %s: %s", resolved, e)

        # Clean up empty directories created during staging
        for path in self._tracked_paths:
            if not path.exists() and path.parent != self._work_dir:
                try:
                    # Try to remove empty parent dirs
                    parent = path.parent
                    while parent != self._work_dir:
                        parent.rmdir()  # only removes if empty
                        parent = parent.parent
                except OSError:
                    pass

    # ─── Helpers ───

    @staticmethod
    def _make_diff(path: Path, old: str, new: str) -> str:
        """Generate unified diff text."""
        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
        return "".join(diff)
