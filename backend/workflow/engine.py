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
import time
from typing import TYPE_CHECKING

from backend.types import Phase, Session
from backend.events import (
    WorkflowCompletedEvent,
    WorkflowPlanShownEvent,
    WorkflowReviewResultEvent,
    WorkflowTaskCompletedEvent,
    WorkflowTaskStartedEvent,
)
from backend.workflow.parser import (
    parse_diff_set,
    parse_review_report,
    parse_task_list,
)
from backend.workflow.types import (
    DiffSet,
    PhaseGuard,
    ReviewReport,
    SubTask,
    TaskList,
    VERDICT_APPROVED,
    WorkflowState,
)

if TYPE_CHECKING:
    from backend.agent_store import AgentStore
    from backend.orchestrator import AgentOrchestrator, Broadcast
    from backend.session import SessionStore

logger = logging.getLogger(__name__)

MAX_RETRIES_PER_TASK = 3


class WorkflowRunner:
    """工作流阶段状态机主循环。

    使用方式（由 Orchestrator 在需要时调用）::

        runner = WorkflowRunner(orchestrator, agent_store, session_store)
        await runner.execute(session, user_text, broadcast)

    ``execute`` 是异步协程，内部可能执行多个阶段后返回
    （如因需用户介入而暂停，或因完成/出错而终止）。

    若传入 ``session_store``，则每次阶段转换后会自动持久化会话状态，
    支持进程重启后通过 CLI ``--resume`` 恢复。
    """

    def __init__(
        self,
        orchestrator: AgentOrchestrator,
        agent_store: AgentStore,
        session_store: SessionStore | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._agent_store = agent_store
        self._session_store = session_store

    # ─── 持久化 ───

    def _save_session(self, session: Session) -> None:
        """将会话状态持久化到 SessionStore。

        在每次阶段转换后调用，确保进程崩溃后可通过 ``--resume`` 恢复。
        若 ``session_store`` 未配置则静默跳过。
        """
        if self._session_store is None:
            return
        try:
            session.last_active_at = time.time()
            self._session_store.save(session)
            logger.debug("Session %s persisted at phase=%s", session.id, session.phase)
        except Exception as e:
            logger.warning("Failed to persist session %s: %s", session.id, e)

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
                    self._save_session(session)
                    continue
                session.workflow_state.task_list = task_list
                await self._broadcast_plan(session, broadcast)
                session.phase = Phase.PLAN_REVIEW
                # 暂停，等待用户确认计划
                self._save_session(session)
                return

            if phase == Phase.PLAN_REVIEW:
                # 由用户命令（approve_plan）触发进入此阶段，
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
                    self._save_session(session)
                    return
                session.workflow_state.current_diff_set = diff_set
                session.phase = Phase.CODE_REVIEW
                self._save_session(session)
                continue

            if phase == Phase.CODE_REVIEW:
                if session.auto_review:
                    session.phase = Phase.REVIEWING
                    continue
                # 非自动审查模式：暂停，等待用户手动触发审查
                self._save_session(session)
                return

            if phase == Phase.REVIEWING:
                report = await self._run_reviewer(session, broadcast)
                if report is None:
                    session.phase = Phase.ERROR
                    self._save_session(session)
                    return
                session.workflow_state.last_review_report = report
                # 结构化工作流事件：审查结果
                ws = session.workflow_state
                await WorkflowReviewResultEvent(
                    task_id=report.task_id,
                    verdict=report.overall_verdict,
                    summary=report.summary,
                    should_retry=report.should_retry,
                    retry_count=ws.retry_count,
                ).emit(broadcast)
                if report.should_retry:
                    ws = session.workflow_state
                    ws.retry_count += 1
                    if ws.retry_count >= MAX_RETRIES_PER_TASK:
                        # 重试上限 reached — 自动跳过当前任务
                        logger.warning(
                            "Task %s reached max retries (%d), auto-skipping",
                            ws.current_task.id if ws.current_task else "?",
                            MAX_RETRIES_PER_TASK,
                        )
                        await broadcast("agent.status", {
                            "phase": "error",
                            "detail": f"任务重试已达上限（{MAX_RETRIES_PER_TASK}次），自动跳过",
                        })
                        ws.current_diff_set = None
                        ws.last_review_report = None
                        session.coder_guidance_queue.clear()
                        await self._complete_task(session, broadcast, status="skipped")
                        self._save_session(session)
                        continue
                    session.phase = Phase.FEEDBACK
                    self._inject_review_feedback(session, report)
                    # 暂停，等待用户确认后重试
                    self._save_session(session)
                    return
                # 审查通过 → 推进到下一个子任务
                await self._complete_task(session, broadcast)
                self._save_session(session)
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
                self._save_session(session)
                return

            if phase == Phase.ERROR:
                # 等待用户介入恢复（resume 命令会重置阶段到 PLANNING/CODING）
                self._save_session(session)
                return

            # 兜底：未知阶段
            logger.warning("Unknown phase %s in workflow runner", phase)
            session.phase = Phase.ERROR
            return

    # ─── 用户命令处理 ───

    async def handle_user_command(
        self,
        session: Session,
        command: str,
        broadcast: Broadcast,
        *,
        user_text: str = "",
    ) -> bool:
        """处理用户在工作流暂停期间的命令。

        支持的命令：
        - ``approve_plan``：确认计划，从 PLAN_REVIEW → CODING
        - ``reject_plan``：拒绝计划，回到 INIT 重新规划
        - ``start_review``：手动触发审查，从 CODE_REVIEW → REVIEWING
        - ``skip_review``：跳过审查，从 CODE_REVIEW → 下一个子任务
        - ``retry``：审查不通过后重试，从 FEEDBACK → CODING
        - ``skip_task``：跳过当前子任务，从 FEEDBACK → 下一个子任务
        - ``abort``：中止工作流，从任意暂停阶段 → ERROR
        - ``resume``：从 ERROR 恢复到 PLANNING（重新规划）

        Args:
            session: 当前会话
            command: 命令名称
            broadcast: 广播闭包
            user_text: 可选的用户补充文本（如 reject_plan 后的新需求）

        Returns:
            True 表示命令已处理且状态已更新，可继续 execute()；
            False 表示命令不适用当前阶段或处理失败。
        """
        phase = session.phase
        ws = session.workflow_state

        logger.info(
            "User command '%s' at phase=%s session=%s",
            command, phase, session.id,
        )

        # ── approve_plan：PLAN_REVIEW → CODING ──
        if command == "approve_plan":
            if phase != Phase.PLAN_REVIEW:
                logger.warning("approve_plan not valid at phase=%s", phase)
                return False
            ws.plan_approved = True
            session.phase = Phase.CODING
            await broadcast("agent.status", {
                "phase": "coding",
                "detail": "计划已确认，开始编码...",
            })
            self._save_session(session)
            return True

        # ── reject_plan：PLAN_REVIEW → INIT ──
        if command == "reject_plan":
            if phase != Phase.PLAN_REVIEW:
                logger.warning("reject_plan not valid at phase=%s", phase)
                return False
            ws.plan_approved = False
            ws.task_list = None
            session.phase = Phase.INIT
            session.coder_guidance_queue.clear()
            await broadcast("agent.status", {
                "phase": "init",
                "detail": "计划已拒绝，请重新描述需求" if not user_text else f"重新规划：{user_text}",
            })
            self._save_session(session)
            return True

        # ── start_review：CODE_REVIEW → REVIEWING ──
        if command == "start_review":
            if phase != Phase.CODE_REVIEW:
                logger.warning("start_review not valid at phase=%s", phase)
                return False
            session.phase = Phase.REVIEWING
            self._save_session(session)
            return True

        # ── skip_review：CODE_REVIEW → 下一个子任务 ──
        if command == "skip_review":
            if phase != Phase.CODE_REVIEW:
                logger.warning("skip_review not valid at phase=%s", phase)
                return False
            await broadcast("agent.status", {
                "phase": "coding",
                "detail": "跳过审查，推进到下一个任务...",
            })
            await self._complete_task(session, broadcast, status="skipped")
            self._save_session(session)
            return True

        # ── retry：FEEDBACK → CODING ──
        if command == "retry":
            if phase != Phase.FEEDBACK:
                logger.warning("retry not valid at phase=%s", phase)
                return False
            ws.current_diff_set = None
            ws.last_review_report = None
            session.phase = Phase.CODING
            retry_info = f"（第 {ws.retry_count} 次重试）" if ws.retry_count > 0 else ""
            await broadcast("agent.status", {
                "phase": "coding",
                "detail": f"根据审查反馈重新编码{retry_info}...",
            })
            self._save_session(session)
            return True

        # ── skip_task：FEEDBACK → 下一个子任务 ──
        if command == "skip_task":
            if phase != Phase.FEEDBACK:
                logger.warning("skip_task not valid at phase=%s", phase)
                return False
            ws.current_diff_set = None
            ws.last_review_report = None
            session.coder_guidance_queue.clear()
            await broadcast("agent.status", {
                "phase": "coding",
                "detail": "跳过当前任务，推进到下一个...",
            })
            await self._complete_task(session, broadcast, status="skipped")
            self._save_session(session)
            return True

        # ── abort：任意暂停阶段 → ERROR ──
        if command == "abort":
            if phase in (Phase.COMPLETED, Phase.ERROR):
                logger.warning("abort not valid at phase=%s", phase)
                return False
            session.phase = Phase.ERROR
            await broadcast("agent.status", {
                "phase": "error",
                "detail": "工作流已被用户中止",
            })
            self._save_session(session)
            return True

        # ── undo：CODE_REVIEW / FEEDBACK → 回退上一个已完成任务 ──
        if command == "undo":
            if phase not in (Phase.CODE_REVIEW, Phase.FEEDBACK):
                logger.warning("undo not valid at phase=%s", phase)
                return False
            if not ws.completed_tasks:
                logger.warning("undo: no completed tasks to revert")
                return False

            # 弹出最后一个完成的任务
            last_task_id = ws.completed_tasks.pop()
            # 回退任务索引
            if ws.task_list and ws.task_list.current_task_index > 0:
                ws.task_list.current_task_index -= 1
                # 重置任务状态
                task = ws.task_list.current_task
                if task:
                    task.status = "pending"

            ws.current_diff_set = None
            ws.last_review_report = None
            ws.retry_count = 0
            session.coder_guidance_queue.clear()
            session.phase = Phase.CODING

            logger.info(
                "Undo: reverted task %s, back to index %d",
                last_task_id,
                ws.task_list.current_task_index if ws.task_list else 0,
            )
            await broadcast("agent.status", {
                "phase": "coding",
                "detail": f"已撤销任务 {last_task_id}，重新编码...",
            })
            self._save_session(session)
            return True

        # ── resume：ERROR → PLANNING ──
        if command == "resume":
            if phase != Phase.ERROR:
                logger.warning("resume not valid at phase=%s", phase)
                return False
            # 恢复到 PLANNING 重新规划
            ws.plan_approved = False
            ws.task_list = None
            ws.current_diff_set = None
            ws.last_review_report = None
            ws.completed_tasks.clear()
            session.coder_guidance_queue.clear()
            session.phase = Phase.INIT
            await broadcast("agent.status", {
                "phase": "init",
                "detail": "工作流已恢复，重新开始规划...",
            })
            self._save_session(session)
            return True

        logger.warning("Unknown workflow command: %s", command)
        return False

    # ─── 阶段执行器 ───

    async def _run_planner(
        self,
        session: Session,
        user_text: str,
        broadcast: Broadcast,
    ) -> TaskList | None:
        """运行 Planner Agent，产出 TaskList。

        调用 orchestrator.run_workflow_agent 执行 planner 角色 Agent，
        然后用 parse_task_list 解析文本产出。
        """
        logger.info("Running planner for session=%s", session.id)

        await broadcast("agent.status", {
            "phase": "planning",
            "detail": "正在分析需求并拆解任务...",
        })

        try:
            result, _ = await self._orchestrator.run_workflow_agent(
                agent_id="planner",
                session=session,
                user_message=user_text,
                broadcast=broadcast,
                phase=Phase.PLANNING,
            )
        except Exception as e:
            logger.exception("Planner agent failed")
            await broadcast("error", {
                "message": f"规划阶段执行失败: {e}",
                "recoverable": True,
            })
            return None

        task_list = parse_task_list(result.text)
        if task_list is None:
            logger.error("Failed to parse TaskList from planner output")
            await broadcast("error", {
                "message": "规划阶段产出解析失败——无法从 Agent 回复中提取任务列表",
                "recoverable": True,
            })
            return None

        logger.info(
            "Planner produced %d tasks for session=%s",
            task_list.total_count, session.id,
        )
        return task_list

    async def _run_coder(
        self,
        session: Session,
        task: SubTask,
        broadcast: Broadcast,
    ) -> DiffSet | None:
        """运行 Coder Agent 执行单个子任务，产出 DiffSet。

        调用 orchestrator.run_workflow_agent 执行 coder 角色 Agent，
        从 staging 捕获文件变更并转换为 DiffSet。
        """
        logger.info("Running coder for session=%s task=%s", session.id, task.id)

        task_message = self._build_coder_message(task, session)

        # 任务索引感知
        ws = session.workflow_state
        task_index = ws.task_list.current_task_index + 1 if ws and ws.task_list else 0
        task_total = ws.task_list.total_count if ws and ws.task_list else 0
        retry_info = f"（重试第 {ws.retry_count} 次）" if ws and ws.retry_count > 0 else ""
        index_str = f" {task_index}/{task_total}" if task_total > 0 else ""

        await broadcast("agent.status", {
            "phase": "coding",
            "detail": f"正在执行子任务{index_str}：{task.title}{retry_info}",
        })

        # 结构化工作流事件：任务开始
        await WorkflowTaskStartedEvent(
            task_id=task.id,
            title=task.title,
            description=task.description,
            task_index=task_index,
            total_count=task_total,
            retry_count=ws.retry_count if ws else 0,
        ).emit(broadcast)

        try:
            result, staging = await self._orchestrator.run_workflow_agent(
                agent_id="coder",
                session=session,
                user_message=task_message,
                broadcast=broadcast,
                phase=Phase.CODING,
            )
        except Exception as e:
            logger.exception("Coder agent failed")
            await broadcast("error", {
                "message": f"编码阶段执行失败: {e}",
                "recoverable": True,
            })
            return None

        # 从 staging 捕获文件变更
        if staging is not None:
            commit = staging.commit()
            if commit.files_changed > 0:
                diff_set = DiffSet.from_commit_result(task.id, commit)
                # 累计文件变更数
                if session.workflow_state:
                    session.workflow_state.total_files_changed += commit.files_changed
                logger.info(
                    "Coder produced %d file changes for task=%s",
                    commit.files_changed, task.id,
                )
            else:
                # 无文件变更——可能是纯分析任务
                diff_set = DiffSet(
                    task_id=task.id,
                    files_changed=0,
                    summary=result.text[:200] if result.text else "无文件变更",
                )
                logger.info("Coder produced no file changes for task=%s", task.id)
            return diff_set

        # 无 staging（理论上不应发生——coder 有写工具）
        logger.warning("Coder ran without staging, trying text parse")
        diff_set = parse_diff_set(result.text, task_id=task.id)
        if diff_set is not None:
            return diff_set

        return DiffSet(
            task_id=task.id,
            files_changed=0,
            summary=result.text[:200] if result.text else "",
        )

    async def _run_reviewer(
        self,
        session: Session,
        broadcast: Broadcast,
    ) -> ReviewReport | None:
        """运行 Reviewer Agent 审查当前 DiffSet，产出 ReviewReport。

        调用 orchestrator.run_workflow_agent 执行 reviewer 角色 Agent，
        然后用 parse_review_report 解析审查报告。
        """
        logger.info("Running reviewer for session=%s", session.id)

        ws = session.workflow_state
        diff = ws.current_diff_set if ws else None
        review_message = self._build_reviewer_message(diff, session)

        await broadcast("agent.status", {
            "phase": "reviewing",
            "detail": "正在审查代码变更...",
        })

        try:
            result, _ = await self._orchestrator.run_workflow_agent(
                agent_id="reviewer",
                session=session,
                user_message=review_message,
                broadcast=broadcast,
                phase=Phase.REVIEWING,
            )
        except Exception as e:
            logger.exception("Reviewer agent failed")
            await broadcast("error", {
                "message": f"审查阶段执行失败: {e}",
                "recoverable": True,
            })
            return None

        task_id = diff.task_id if diff else ""
        report = parse_review_report(result.text, task_id=task_id)
        if report is None:
            # 解析失败时默认通过，避免阻塞工作流
            logger.warning("Failed to parse ReviewReport, defaulting to approved")
            report = ReviewReport(
                task_id=task_id,
                overall_verdict=VERDICT_APPROVED,
                summary=result.text[:200] if result.text else "审查完成（解析失败，默认通过）",
                should_retry=False,
            )

        logger.info(
            "Reviewer verdict=%s should_retry=%s for task=%s",
            report.overall_verdict, report.should_retry, task_id,
        )
        return report

    # ─── 消息构建辅助 ───

    @staticmethod
    def _build_coder_message(task: SubTask, session: Session) -> str:
        """构建给 coder 的任务指令消息。

        包含阶段间上下文传递：planner 方案概述、已完成任务清单、任务索引。
        """
        ws = session.workflow_state
        task_index = ws.task_list.current_task_index + 1 if ws and ws.task_list else 0
        task_total = ws.task_list.total_count if ws and ws.task_list else 0
        index_prefix = f"（任务 {task_index}/{task_total}）" if task_total > 0 else ""

        parts = [f"请完成以下编码任务：{index_prefix}\n\n任务标题：{task.title}"]
        if task.description:
            parts.append(f"任务描述：{task.description}")
        if task.files_involved:
            parts.append(f"涉及文件：{', '.join(task.files_involved)}")
        if task.acceptance_criteria:
            parts.append(f"验收标准：{task.acceptance_criteria}")

        # 阶段间上下文传递：注入 planner 方案概述
        ws = session.workflow_state
        if ws and ws.task_list:
            if ws.task_list.overview:
                parts.append(f"\n（方案概述：{ws.task_list.overview}）")
            # 已完成任务清单（让 coder 知道前序进度，避免重复劳动）
            if ws.completed_tasks:
                completed_titles = []
                for tid in ws.completed_tasks:
                    t = next((t for t in ws.task_list.tasks if t.id == tid), None)
                    completed_titles.append(t.title if t else tid)
                parts.append(
                    f"（已完成任务：{', '.join(completed_titles)}）"
                )

        # 如果有审查反馈（FEEDBACK 阶段重试），附加到消息末尾
        if session.coder_guidance_queue:
            parts.append("\n---\n审查反馈（请根据以下反馈修改代码）：")
            parts.append("\n".join(session.coder_guidance_queue))
            session.coder_guidance_queue.clear()

        return "\n".join(parts)

    @staticmethod
    def _build_reviewer_message(diff: DiffSet | None, session: Session | None = None) -> str:
        """构建给 reviewer 的审查指令消息。

        包含阶段间上下文传递：当前任务上下文、已完成任务进度。
        """
        if diff is None:
            return "请审查最近的代码变更。"

        parts = ["请审查以下代码变更："]

        # 阶段间上下文传递：注入当前任务上下文
        if session and session.workflow_state:
            ws = session.workflow_state
            if ws.current_task:
                parts.append(f"\n审查目标任务：{ws.current_task.title}")
                if ws.current_task.acceptance_criteria:
                    parts.append(f"验收标准：{ws.current_task.acceptance_criteria}")
            if ws.completed_tasks:
                parts.append(
                    f"（前序已完成 {len(ws.completed_tasks)} 个任务）"
                )

        if diff.summary:
            parts.append(f"\n变更摘要：{diff.summary}")
        parts.append(f"变更文件数：{diff.files_changed}")
        if diff.combined_diff:
            # 截断过长的 diff
            diff_text = diff.combined_diff[:8000]
            if len(diff.combined_diff) > 8000:
                diff_text += "\n...(diff 已截断)"
            parts.append(f"\n--- Diff ---\n{diff_text}")
        if diff.test_results:
            parts.append(f"\n--- 测试结果 ---\n{diff.test_results}")

        parts.append(
            "\n请给出逐文件审查意见和总体判定。"
            "总体判定为 approved / needs_changes / rejected。"
        )
        return "\n".join(parts)

    # ─── 状态推进 ───

    async def _complete_task(
        self,
        session: Session,
        broadcast: Broadcast,
        *,
        status: str = "done",
    ) -> None:
        """标记当前任务完成并广播事件，然后推进到下一任务。"""
        ws = session.workflow_state
        task = ws.current_task if ws else None
        files_changed = ws.total_files_changed if ws else 0

        self._advance_to_next_task(session)

        # 广播任务完成事件
        await WorkflowTaskCompletedEvent(
            task_id=task.id if task else "",
            title=task.title if task else "",
            status=status,
            files_changed=files_changed,
            completed_count=len(ws.completed_tasks) if ws else 0,
            total_count=ws.task_list.total_count if ws and ws.task_list else 0,
        ).emit(broadcast)

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
        ws.retry_count = 0  # 重置重试计数

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
        # 结构化工作流事件：计划展示
        tasks_serialized = [
            {
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "status": t.status,
            }
            for t in tl.tasks
        ]
        await WorkflowPlanShownEvent(
            overview=tl.overview,
            tasks=tasks_serialized,
            risks=tl.risks,
            total_count=tl.total_count,
        ).emit(broadcast)

    async def _broadcast_completion(
        self,
        session: Session,
        broadcast: Broadcast,
    ) -> None:
        """广播工作流完成。"""
        ws = session.workflow_state
        total = ws.task_list.total_count if ws and ws.task_list else 0
        completed = ws.task_list.completed_count if ws and ws.task_list else 0
        files_changed = ws.total_files_changed if ws else 0
        skipped = total - len(ws.completed_tasks) if ws else 0
        await broadcast("agent.status", {
            "phase": "completed",
            "detail": f"全部完成：{completed}/{total} 个子任务，{files_changed} 个文件变更",
        })
        # 结构化工作流事件：工作流完成
        await WorkflowCompletedEvent(
            total_count=total,
            completed_count=len(ws.completed_tasks) if ws else 0,
            skipped_count=max(skipped, 0),
            files_changed=files_changed,
        ).emit(broadcast)
        session.phase = Phase.COMPLETED
