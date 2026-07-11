"""会话持久化——JSON 文件存储，原子写入。"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from uuid import uuid4

from backend.types import Phase, Session, TokenUsage

logger = logging.getLogger(__name__)


class SessionStore:
    """JSON 文件会话持久化。

    存储路径：{data_dir}/sessions/{session_id}.json
    原子写入：先写临时文件再 os.replace()。
    """

    def __init__(self, data_dir: Path):
        self._sessions_dir = data_dir / "sessions"
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    def save(self, session: Session) -> None:
        """保存会话状态到 JSON 文件。"""
        path = self._sessions_dir / f"{session.id}.json"
        data = self._serialize(session)
        self._atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))

    def load(self, session_id: str) -> Session | None:
        """Load session from JSON file. None if not found."""
        path = self._sessions_dir / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return self._deserialize(data)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Failed to load session %s: %s", session_id, e)
            return None

    def list_sessions(self) -> list[dict]:
        """List all sessions (summary only, no messages)."""
        sessions = []
        for path in sorted(self._sessions_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data["id"],
                    "title": data.get("title", ""),
                    "phase": data.get("phase", "init"),
                    "created_at": data.get("created_at", 0),
                    "last_active_at": data.get("last_active_at", 0),
                    "work_dir": data.get("work_dir", ""),
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return sessions

    def delete(self, session_id: str) -> None:
        """Delete a session file."""
        path = self._sessions_dir / f"{session_id}.json"
        path.unlink(missing_ok=True)

    # ─── Serialization ───

    @staticmethod
    def _serialize(session: Session) -> dict:
        return {
            "id": session.id,
            "work_dir": str(session.work_dir),
            "phase": session.phase.value,
            "messages": session.messages,
            "project_context": session.project_context,
            "yolo_mode": session.yolo_mode,
            "auto_review": session.auto_review,
            "solo_mode": session.solo_mode,
            "usage_total": {
                "input_tokens": session.usage_total.input_tokens,
                "output_tokens": session.usage_total.output_tokens,
            },
            "title": session.title,
            "created_at": session.created_at,
            "last_active_at": session.last_active_at,
        }

    @staticmethod
    def _deserialize(data: dict) -> Session:
        usage = data.get("usage_total", {})
        return Session(
            id=data["id"],
            work_dir=Path(data["work_dir"]),
            phase=Phase(data.get("phase", "init")),
            messages=data.get("messages", []),
            project_context=data.get("project_context"),
            yolo_mode=data.get("yolo_mode", False),
            auto_review=data.get("auto_review", True),
            solo_mode=data.get("solo_mode", False),
            usage_total=TokenUsage(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            ),
            title=data.get("title", ""),
            created_at=data.get("created_at", 0),
            last_active_at=data.get("last_active_at", 0),
        )

    # ─── Atomic write ───

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        """Write to temp file then atomically replace."""
        import os
        import tempfile

        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, str(path))
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
