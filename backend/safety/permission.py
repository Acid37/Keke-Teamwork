"""命令审批管理器，用于 console 工具执行前的审批。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import uuid4

from backend.safety.command_risk import CommandRisk, classify_command


class PermissionManager:
    """通过 WebSocket 请求用户审批 shell 命令。

    风险分级：
    - read_only: 自动放行（无需用户确认）
    - normal:    标准审批流程（YOLO 模式跳过，否则需确认）
    - dangerous: 始终需要明确审批，即使 YOLO 模式
    """

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

    def check(self, command: str, max_command_risk: str = "dangerous") -> str:
        """返回 allow / deny / needs_approval。

        使用命令风险分级：
        - read_only 命令始终放行
        - dangerous 命令始终需审批（即使 YOLO）
        - normal 命令遵循 YOLO 模式

        max_command_risk 为 Agent 的风险预算上限。若命令风险超过此预算，
        直接 deny（即使命令本身是 normal）。例如 max_command_risk="read_only"
        的 Agent 不能执行任何 normal 或 dangerous 命令。
        """
        if not command.strip():
            return "deny"

        risk = classify_command(command)

        # 风险预算检查：命令风险等级超过 Agent 预算 → 拒绝
        risk_order = {"read_only": 0, "normal": 1, "dangerous": 2}
        budget = risk_order.get(max_command_risk, 1)
        cmd_risk = risk_order.get(risk.value, 1)
        if cmd_risk > budget:
            return "deny"

        if risk == CommandRisk.read_only:
            return "allow"

        if risk == CommandRisk.dangerous:
            # 高危命令始终需要明确审批
            return "needs_approval"

        # 普通命令
        if self._yolo_mode:
            return "allow"
        return "needs_approval"

    def set_yolo_mode(self, enabled: bool) -> None:
        """更新活动会话的审批行为。"""
        self._yolo_mode = enabled

    async def request_approval(self, command: str) -> bool:
        """请求前端审批并等待响应。"""
        if self._yolo_mode:
            # YOLO 模式：只有 read_only 命令能通过 check() 到这里
            # 高危命令即使在 YOLO 模式下也需要审批
            risk = classify_command(command)
            if risk != CommandRisk.dangerous:
                return True

        request_id = uuid4().hex[:12]
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[request_id] = future

        risk = classify_command(command)
        await self._broadcast("approval.request", {
            "request_id": request_id,
            "command": command,
            "risk_level": risk.value,
            "timeout_seconds": self._timeout_seconds,
        })

        try:
            return await asyncio.wait_for(future, timeout=self._timeout_seconds)
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending.pop(request_id, None)

    def resolve(self, request_id: str, approved: bool) -> bool:
        """处理待审批请求。未知请求返回 False。"""
        future = self._pending.get(request_id)
        if not future or future.done():
            return False
        future.set_result(bool(approved))
        return True
