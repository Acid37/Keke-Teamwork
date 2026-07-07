"""Command approval manager for console tool execution."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import uuid4


class PermissionManager:
    """Requests user approval for shell commands over WebSocket."""

    def __init__(
        self,
        *,
        broadcast: Callable[[str, dict], Awaitable[None]],
        yolo_mode: bool = False,
        timeout_seconds: int = 120,
    ):
        self._broadcast = broadcast
        self._yolo_mode = yolo_mode
        self._timeout_seconds = timeout_seconds
        self._pending: dict[str, asyncio.Future[bool]] = {}

    def check(self, command: str) -> str:
        """Return allow / deny / needs_approval for a command."""
        if not command.strip():
            return "deny"
        if self._yolo_mode:
            return "allow"
        return "needs_approval"

    def set_yolo_mode(self, enabled: bool) -> None:
        """Update approval behavior for an active session."""
        self._yolo_mode = enabled

    async def request_approval(self, command: str) -> bool:
        """Ask the frontend for approval and wait for the response."""
        if self._yolo_mode:
            return True

        request_id = uuid4().hex[:12]
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[request_id] = future

        await self._broadcast("approval.request", {
            "request_id": request_id,
            "command": command,
            "timeout_seconds": self._timeout_seconds,
        })

        try:
            return await asyncio.wait_for(future, timeout=self._timeout_seconds)
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending.pop(request_id, None)

    def resolve(self, request_id: str, approved: bool) -> bool:
        """Resolve a pending approval request. Returns False if unknown."""
        future = self._pending.get(request_id)
        if not future or future.done():
            return False
        future.set_result(bool(approved))
        return True
