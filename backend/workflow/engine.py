"""WorkflowRunner — 工作流引擎状态机。

负责 Plan → Code → Review 的阶段流转：
- 决定「现在该干什么」
- 阶段间数据：TaskList → DiffSet → ReviewReport
- 自动触发：产出物就绪 → 调度下一阶段

原则：WorkflowRunner 不关心 Agent 内部怎么执行（tool-calling
循环仍走现有 Agent.run()），只关心阶段产出物和转换条件。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.types import Phase, Session
from backend.workflow.types import (
    DiffSet,
    PhaseGuard,
    ReviewReport,
    TaskList,
    WorkflowState,
)

if TYPE_CHECKING:
    from backend.agent_store import AgentStore
    from backend.orchestrator import AgentOrchestrator, Broadcast

logger = logging.getLogger(__name__)


class WorkflowRunner:
    """工作流阶段状态机主循环。

    使用方式（由 Orchestrator 在需要时调用）::

        runner = WorkflowRunner(orchestrator, agent_store)
        await runner.execute(session, user_text, broadcast)

    ``execute`` 是异步协程，内部可能执行多个阶段后返回
    （如因需用户介入而暂停，或因完成/出错而终止）。
    """

    def __init__(
        self,
        orchestrator: AgentOrchestrator,
        agent_store: AgentStore,
    ) -> None:
        self._orchestrator = orchestrator
        self._agent_store = agent_store

    # ─── 主入口 ───

    async def execute(
        self,
        session: Session,
        user_text: str,
        broadcast: Broadcast,
    ) -> None:
        """工作流主循环：自动推进阶段直到需要用户输入或完成/出错。"""
        if session.workflow_state is None:
            session.workflow_state = WorkflowState()

        while True:
            phase = session.phase
            logger.info("WorkflowRunner phase=%s session=%s", phase, session.id)

            if phase == Phase.INIT:
                await self._start_planning(session, user_text, broadcast)
                continue

            if phase == Phase.PLANNING:
                task_list = await self._run_planner(session, user_text, broadcast)
                if task_list is None:
                    session.phase = Phase.ERROR
                    continue
                session.workflow_state.task_list = task_list
                await self._broadcast_plan(session, broadcast)
                session.phase = Phase.PLAN_REVIEW
                # 暂停，等待用户确认计划
                return

            if phase == Phase.PLAN_REVIEW:
                # 由用户命令（workflow.approve_plan）触发进入此阶段，
                # 守卫已在外部检查过
                session.workflow_state.plan_approved = True
                session.phase = Phase.CODING
                continue

            if phase == Phase.CODING:
                task = session.workflow_state.current_task
                if task is None:
                    # 所有子任务已耗尽 → 完成
                    session.phase = Phase.COMPLETED
                    continue
                task.status = "in_progress"
                diff_set = await self._run_coder(session, task, broadcast)
                if diff_set is None:
                    session.phase = Phase.ERROR
                    return
                session.workflow_state.current_diff_set = diff_set
                session.phase = Phase.CODE_REVIEW
                continue

            if phase == Phase.CODE_REVIEW:
                if session.auto_review:
                    session.phase = Phase.REVIEWING
                    continue
                # 非自动审查模式：暂停，等待用户手动触发审查
                return

            if phase == Phase.REVIEWING:
                report = await self._run_reviewer(session, broadcast)
                if report is None:
                    session.phase = Phase.ERROR
                    return
                session.workflow_state.last_review_report = report
                if report.should_retry:
                    session.phase = Phase.FEEDBACK
                    self._inject_review_feedback(session, report)
                    # 暂停，等待用户确认后重试
                    return
                # 审查通过 → 推进到下一个子任务
                self._advance_to_next_task(session)
                # 若还有剩余任务则继续 CODING，否则自动进入 COMPLETED
                continue

            if phase == Phase.FEEDBACK:
                # FEEDBACK → CODING：用户确认后重试当前任务
                session.workflow_state.current_diff_set = None
                session.workflow_state.last_review_report = None
                session.phase = Phase.CODING
                continue

            if phase == Phase.COMPLETED:
                await self._broadcast_completion(session, broadcast)
                return

            if phase == Phase.ERROR:
                # 等待用户介入恢复（resume 命令会重置阶段到 PLANNING/CODING）
                return

            # 兜底：未知阶段
            logger.warning("Unknown phase %s in workflow runner", phase)
            session.phase = Phase.ERROR
            return

    # ─── 阶段执行器（占位符，Step 3-5 逐步填充）───

    async def _run_planner(
        self,
        session: Session,
        user_text: str,
        broadcast: Broadcast,
    ) -> TaskList | None:
        """运行 Planner Agent，产出 TaskList。

        Step 3 实现：构建阶段感知的 system prompt + user message，
        调用 Agent.run() 并解析文本产出为 TaskList。
        """
        logger.info("Running planner for session=%s", session.id)
        # TODO(v0.4-step3): 实际调用 planner Agent
        return None

    async def _run_coder(
        self,
        session: Session,
        task: object,  # SubTask
        broadcast: Broadcast,
    ) -> DiffSet | None:
        """运行 Coder Agent 执行单个子任务，产出 DiffSet。

        Step 4 实现：复用现有 orchestrator 的 Agent 执行 + staging 逻辑。
        """
        logger.info("Running coder for session=%s task=%s", session.id, task.id)
        # TODO(v0.4-step4): 实际调用 coder Agent
        return None

    async def _run_reviewer(
        self,
        session: Session,
        broadcast: Broadcast,
    ) -> ReviewReport | None:
        """运行 Reviewer Agent 审查当前 DiffSet，产出 ReviewReport。

        Step 5 实现：构建 reviewer prompt（含 diff），解析审查报告。
        """
        logger.info("Running reviewer for session=%s", session.id)
        # TODO(v0.4-step5): 实际调用 reviewer Agent
        return None

    # ─── 状态推进 ───

    def _advance_to_next_task(self, session: Session) -> None:
        """当前子任务审查通过，推进到下一个任务。"""
        ws = session.workflow_state
        if ws is None or ws.task_list is None:
            session.phase = Phase.COMPLETED
            return

        ws.completed_tasks.append(ws.task_list.current_task.id)
        next_task = ws.task_list.advance()

        # 清理本轮产物
        ws.current_diff_set = None

        if next_task is None:
            session.phase = Phase.COMPLETED
            # 最后一个任务完成，保留 last_review_report 供历史查看
        else:
            session.phase = Phase.CODING
            ws.last_review_report = None

    def _inject_review_feedback(self, session: Session, report: ReviewReport) -> None:
        """将审查反馈注入 session 的 coder_guidance_queue，供下次 coder 读取。"""
        feedback_lines = [f"审查反馈：{report.summary}"]
        for fr in report.file_reviews:
            if fr.issues:
                feedback_lines.append(
                    f"  [{fr.file_path}] " + "; ".join(fr.issues)
                )
        session.coder_guidance_queue.append("\n".join(feedback_lines))

    # ─── 广播辅助 ───

    async def _start_planning(
        self,
        session: Session,
        user_text: str,
        broadcast: Broadcast,
    ) -> None:
        """进入 PLANNING 阶段前的准备：广播状态。"""
        session.phase = Phase.PLANNING
        await broadcast("agent.status", {
            "phase": "planning",
            "detail": "正在分析需求并拆解任务...",
        })

    async def _broadcast_plan(
        self,
        session: Session,
        broadcast: Broadcast,
    ) -> None:
        """广播计划产出到前端（用户确认用）。"""
        ws = session.workflow_state
        if ws is None or ws.task_list is None:
            return
        tl = ws.task_list
        await broadcast("agent.status", {
            "phase": "plan_review",
            "detail": f"计划已产出：{tl.total_count} 个子任务",
        })
        # Step 8 前端可视化时扩展为 workflow.plan_shown 事件

    async def _broadcast_completion(
        self,
        session: Session,
        broadcast: Broadcast,
    ) -> None:
        """广播工作流完成。"""
        ws = session.workflow_state
        total = ws.task_list.total_count if ws and ws.task_list else 0
        completed = ws.task_list.completed_count if ws and ws.task_list else 0
        await broadcast("agent.status", {
            "phase": "completed",
            "detail": f"全部完成：{completed}/{total} 个子任务",
        })
        session.phase = Phase.COMPLETED
