"""WorkflowRunner 用户命令处理单元测试。

覆盖 Step 6 实现：
- approve_plan / reject_plan（PLAN_REVIEW 阶段）
- start_review / skip_review（CODE_REVIEW 阶段）
- retry / skip_task（FEEDBACK 阶段）
- abort（任意暂停阶段）
- resume（ERROR 阶段）
- 阶段守卫（命令在错误阶段调用时返回 False）
- 未知命令处理
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.types import Phase, Session
from backend.workflow.engine import WorkflowRunner
from backend.workflow.types import (
    DiffSet,
    ReviewReport,
    SubTask,
    TaskList,
    WorkflowState,
    VERDICT_APPROVED,
    VERDICT_NEEDS_CHANGES,
)


# ─── Fixtures ───


@pytest.fixture
def mock_orchestrator():
    return MagicMock()


@pytest.fixture
def mock_agent_store():
    return MagicMock()


@pytest.fixture
def runner(mock_orchestrator, mock_agent_store):
    return WorkflowRunner(mock_orchestrator, mock_agent_store)


@pytest.fixture
def session() -> Session:
    return Session(
        id="test-session",
        work_dir=Path("/tmp/test"),
        phase=Phase.INIT,
    )


@pytest.fixture
def broadcast_log():
    calls = []

    async def broadcast(event_type: str, payload: dict):
        calls.append({"type": event_type, "payload": payload})

    return broadcast, calls


def _make_session_with_state(
    phase: Phase,
    tasks: list[SubTask] | None = None,
    current_task_index: int = 0,
    diff_set: DiffSet | None = None,
    review_report: ReviewReport | None = None,
) -> Session:
    """创建带 WorkflowState 的测试会话。"""
    session = Session(
        id="test-session",
        work_dir=Path("/tmp/test"),
        phase=phase,
    )
    ws = WorkflowState()
    if tasks:
        ws.task_list = TaskList(tasks=tasks, current_task_index=current_task_index)
    ws.current_diff_set = diff_set
    ws.last_review_report = review_report
    ws.plan_approved = phase not in (Phase.INIT, Phase.PLANNING, Phase.PLAN_REVIEW)
    session.workflow_state = ws
    return session


# ─── approve_plan 测试 ───


class TestApprovePlan:
    """approve_plan 命令测试。"""

    async def test_approve_plan_at_plan_review(self, runner, broadcast_log):
        broadcast, calls = broadcast_log
        session = _make_session_with_state(Phase.PLAN_REVIEW, tasks=[SubTask(id="t1", title="T1", description="D1")])

        result = await runner.handle_user_command(session, "approve_plan", broadcast)

        assert result is True
        assert session.phase == Phase.CODING
        assert session.workflow_state.plan_approved is True
        assert any(c["type"] == "agent.status" and c["payload"]["phase"] == "coding" for c in calls)

    async def test_approve_plan_at_wrong_phase(self, runner, broadcast_log):
        broadcast, calls = broadcast_log
        session = _make_session_with_state(Phase.CODING)

        result = await runner.handle_user_command(session, "approve_plan", broadcast)

        assert result is False
        assert session.phase == Phase.CODING  # 未改变


# ─── reject_plan 测试 ───


class TestRejectPlan:
    """reject_plan 命令测试。"""

    async def test_reject_plan_at_plan_review(self, runner, broadcast_log):
        broadcast, calls = broadcast_log
        session = _make_session_with_state(
            Phase.PLAN_REVIEW,
            tasks=[SubTask(id="t1", title="T1", description="D1")],
        )

        result = await runner.handle_user_command(session, "reject_plan", broadcast)

        assert result is True
        assert session.phase == Phase.INIT
        assert session.workflow_state.task_list is None
        assert session.workflow_state.plan_approved is False

    async def test_reject_plan_with_user_text(self, runner, broadcast_log):
        broadcast, calls = broadcast_log
        session = _make_session_with_state(
            Phase.PLAN_REVIEW,
            tasks=[SubTask(id="t1", title="T1", description="D1")],
        )

        result = await runner.handle_user_command(
            session, "reject_plan", broadcast, user_text="改用JWT认证")

        assert result is True
        assert session.phase == Phase.INIT
        # 应广播包含新需求的详情
        detail_calls = [c for c in calls if c["type"] == "agent.status"]
        assert any("改用JWT认证" in c["payload"]["detail"] for c in detail_calls)

    async def test_reject_plan_at_wrong_phase(self, runner, broadcast_log):
        broadcast, _ = broadcast_log
        session = _make_session_with_state(Phase.CODING)

        result = await runner.handle_user_command(session, "reject_plan", broadcast)

        assert result is False


# ─── start_review 测试 ───


class TestStartReview:
    """start_review 命令测试。"""

    async def test_start_review_at_code_review(self, runner, broadcast_log):
        broadcast, _ = broadcast_log
        session = _make_session_with_state(
            Phase.CODE_REVIEW,
            tasks=[SubTask(id="t1", title="T1", description="D1")],
            diff_set=DiffSet(task_id="t1"),
        )

        result = await runner.handle_user_command(session, "start_review", broadcast)

        assert result is True
        assert session.phase == Phase.REVIEWING

    async def test_start_review_at_wrong_phase(self, runner, broadcast_log):
        broadcast, _ = broadcast_log
        session = _make_session_with_state(Phase.PLAN_REVIEW)

        result = await runner.handle_user_command(session, "start_review", broadcast)

        assert result is False


# ─── skip_review 测试 ───


class TestSkipReview:
    """skip_review 命令测试。"""

    async def test_skip_review_advances_to_next_task(self, runner, broadcast_log):
        broadcast, calls = broadcast_log
        session = _make_session_with_state(
            Phase.CODE_REVIEW,
            tasks=[
                SubTask(id="t1", title="T1", description="D1"),
                SubTask(id="t2", title="T2", description="D2"),
            ],
            current_task_index=0,
            diff_set=DiffSet(task_id="t1"),
        )

        result = await runner.handle_user_command(session, "skip_review", broadcast)

        assert result is True
        assert session.phase == Phase.CODING
        assert session.workflow_state.task_list.current_task_index == 1
        assert "t1" in session.workflow_state.completed_tasks

    async def test_skip_review_last_task_to_completed(self, runner, broadcast_log):
        broadcast, _ = broadcast_log
        session = _make_session_with_state(
            Phase.CODE_REVIEW,
            tasks=[SubTask(id="t1", title="T1", description="D1")],
            current_task_index=0,
            diff_set=DiffSet(task_id="t1"),
        )

        result = await runner.handle_user_command(session, "skip_review", broadcast)

        assert result is True
        assert session.phase == Phase.COMPLETED

    async def test_skip_review_at_wrong_phase(self, runner, broadcast_log):
        broadcast, _ = broadcast_log
        session = _make_session_with_state(Phase.REVIEWING)

        result = await runner.handle_user_command(session, "skip_review", broadcast)

        assert result is False


# ─── retry 测试 ───


class TestRetry:
    """retry 命令测试。"""

    async def test_retry_at_feedback(self, runner, broadcast_log):
        broadcast, calls = broadcast_log
        session = _make_session_with_state(
            Phase.FEEDBACK,
            tasks=[SubTask(id="t1", title="T1", description="D1")],
            current_task_index=0,
            diff_set=DiffSet(task_id="t1"),
            review_report=ReviewReport(
                task_id="t1", overall_verdict=VERDICT_NEEDS_CHANGES,
                should_retry=True, summary="需修改",
            ),
        )

        result = await runner.handle_user_command(session, "retry", broadcast)

        assert result is True
        assert session.phase == Phase.CODING
        assert session.workflow_state.current_diff_set is None
        assert session.workflow_state.last_review_report is None

    async def test_retry_at_wrong_phase(self, runner, broadcast_log):
        broadcast, _ = broadcast_log
        session = _make_session_with_state(Phase.CODING)

        result = await runner.handle_user_command(session, "retry", broadcast)

        assert result is False


# ─── skip_task 测试 ───


class TestSkipTask:
    """skip_task 命令测试。"""

    async def test_skip_task_at_feedback(self, runner, broadcast_log):
        broadcast, _ = broadcast_log
        session = _make_session_with_state(
            Phase.FEEDBACK,
            tasks=[
                SubTask(id="t1", title="T1", description="D1"),
                SubTask(id="t2", title="T2", description="D2"),
            ],
            current_task_index=0,
            diff_set=DiffSet(task_id="t1"),
            review_report=ReviewReport(should_retry=True),
        )
        session.coder_guidance_queue.append("feedback")

        result = await runner.handle_user_command(session, "skip_task", broadcast)

        assert result is True
        assert session.phase == Phase.CODING
        assert session.workflow_state.task_list.current_task_index == 1
        assert session.workflow_state.current_diff_set is None
        assert session.workflow_state.last_review_report is None
        assert len(session.coder_guidance_queue) == 0  # cleared

    async def test_skip_task_at_wrong_phase(self, runner, broadcast_log):
        broadcast, _ = broadcast_log
        session = _make_session_with_state(Phase.CODE_REVIEW)

        result = await runner.handle_user_command(session, "skip_task", broadcast)

        assert result is False


# ─── abort 测试 ───


class TestAbort:
    """abort 命令测试。"""

    async def test_abort_at_plan_review(self, runner, broadcast_log):
        broadcast, calls = broadcast_log
        session = _make_session_with_state(Phase.PLAN_REVIEW)

        result = await runner.handle_user_command(session, "abort", broadcast)

        assert result is True
        assert session.phase == Phase.ERROR
        assert any(c["type"] == "agent.status" and "中止" in c["payload"]["detail"] for c in calls)

    async def test_abort_at_code_review(self, runner, broadcast_log):
        broadcast, _ = broadcast_log
        session = _make_session_with_state(Phase.CODE_REVIEW)

        result = await runner.handle_user_command(session, "abort", broadcast)

        assert result is True
        assert session.phase == Phase.ERROR

    async def test_abort_at_feedback(self, runner, broadcast_log):
        broadcast, _ = broadcast_log
        session = _make_session_with_state(Phase.FEEDBACK)

        result = await runner.handle_user_command(session, "abort", broadcast)

        assert result is True
        assert session.phase == Phase.ERROR

    async def test_abort_at_completed_returns_false(self, runner, broadcast_log):
        broadcast, _ = broadcast_log
        session = _make_session_with_state(Phase.COMPLETED)

        result = await runner.handle_user_command(session, "abort", broadcast)

        assert result is False
        assert session.phase == Phase.COMPLETED  # unchanged

    async def test_abort_at_error_returns_false(self, runner, broadcast_log):
        broadcast, _ = broadcast_log
        session = _make_session_with_state(Phase.ERROR)

        result = await runner.handle_user_command(session, "abort", broadcast)

        assert result is False


# ─── resume 测试 ───


class TestResume:
    """resume 命令测试。"""

    async def test_resume_from_error(self, runner, broadcast_log):
        broadcast, calls = broadcast_log
        session = _make_session_with_state(
            Phase.ERROR,
            tasks=[SubTask(id="t1", title="T1", description="D1")],
            diff_set=DiffSet(task_id="t1"),
            review_report=ReviewReport(),
        )
        session.workflow_state.completed_tasks = ["t0"]
        session.coder_guidance_queue.append("feedback")

        result = await runner.handle_user_command(session, "resume", broadcast)

        assert result is True
        assert session.phase == Phase.INIT
        assert session.workflow_state.task_list is None
        assert session.workflow_state.current_diff_set is None
        assert session.workflow_state.last_review_report is None
        assert len(session.workflow_state.completed_tasks) == 0
        assert len(session.coder_guidance_queue) == 0
        assert session.workflow_state.plan_approved is False

    async def test_resume_at_wrong_phase(self, runner, broadcast_log):
        broadcast, _ = broadcast_log
        session = _make_session_with_state(Phase.CODING)

        result = await runner.handle_user_command(session, "resume", broadcast)

        assert result is False


# ─── 未知命令 ───


class TestUnknownCommand:
    """未知命令处理测试。"""

    async def test_unknown_command_returns_false(self, runner, broadcast_log):
        broadcast, _ = broadcast_log
        session = _make_session_with_state(Phase.PLAN_REVIEW)

        result = await runner.handle_user_command(session, "nonexistent_command", broadcast)

        assert result is False


# ─── 命令 + execute 串联测试 ───


class TestCommandThenExecute:
    """验证 handle_user_command 后 execute 能正确继续。"""

    async def test_approve_plan_then_execute(self, runner, broadcast_log):
        """approve_plan 后 execute 应从 CODING 继续。"""
        broadcast, _ = broadcast_log
        session = _make_session_with_state(
            Phase.PLAN_REVIEW,
            tasks=[SubTask(id="t1", title="T1", description="D1")],
        )

        # approve_plan
        await runner.handle_user_command(session, "approve_plan", broadcast)
        assert session.phase == Phase.CODING

        # execute 应从 CODING 开始
        mock_result = MagicMock()
        mock_result.text = ""
        mock_commit = MagicMock()
        mock_commit.files_changed = 0
        mock_staging = MagicMock()
        mock_staging.commit.return_value = mock_commit

        runner._orchestrator.run_workflow_agent = AsyncMock(
            return_value=(mock_result, mock_staging))

        session.auto_review = True
        # Mock reviewer to return approved
        review_result = MagicMock()
        review_result.text = "---REVIEW_START---\n{\"overall_verdict\":\"approved\",\"should_retry\":false}\n---REVIEW_END---"
        call_count = [0]

        async def mock_run(**kwargs):
            call_count[0] += 1
            if kwargs["agent_id"] == "coder":
                return mock_result, mock_staging
            return review_result, None

        runner._orchestrator.run_workflow_agent = mock_run

        await runner.execute(session, "task", broadcast)
        assert session.phase == Phase.COMPLETED

    async def test_reject_plan_then_execute_replans(self, runner, broadcast_log):
        """reject_plan 后 execute 应从 INIT → PLANNING 重新规划。"""
        broadcast, _ = broadcast_log
        session = _make_session_with_state(
            Phase.PLAN_REVIEW,
            tasks=[SubTask(id="t1", title="T1", description="D1")],
        )

        # reject_plan
        await runner.handle_user_command(session, "reject_plan", broadcast)
        assert session.phase == Phase.INIT
        assert session.workflow_state.task_list is None

        # execute 应从 INIT → PLANNING
        planner_output = "---TASKLIST_START---\n{\"tasks\":[{\"id\":\"t1\",\"title\":\"T1\"}]}\n---TASKLIST_END---"
        runner._orchestrator.run_workflow_agent = AsyncMock(
            return_value=(MagicMock(text=planner_output), None))

        await runner.execute(session, "新需求", broadcast)
        assert session.phase == Phase.PLAN_REVIEW
        assert session.workflow_state.task_list is not None
        assert session.workflow_state.task_list.tasks[0].id == "t1"

    async def test_skip_review_then_execute_continues(self, runner, broadcast_log):
        """skip_review 后 execute 应从 CODING（下一任务）继续。"""
        broadcast, _ = broadcast_log
        session = _make_session_with_state(
            Phase.CODE_REVIEW,
            tasks=[
                SubTask(id="t1", title="T1", description="D1"),
                SubTask(id="t2", title="T2", description="D2"),
            ],
            current_task_index=0,
            diff_set=DiffSet(task_id="t1"),
        )
        session.auto_review = True

        await runner.handle_user_command(session, "skip_review", broadcast)
        assert session.phase == Phase.CODING
        assert session.workflow_state.task_list.current_task_index == 1

        # execute 应从 CODING 执行 task-2
        mock_result = MagicMock()
        mock_result.text = ""
        mock_commit = MagicMock()
        mock_commit.files_changed = 0
        mock_staging = MagicMock()
        mock_staging.commit.return_value = mock_commit

        review_result = MagicMock()
        review_result.text = "---REVIEW_START---\n{\"overall_verdict\":\"approved\",\"should_retry\":false}\n---REVIEW_END---"

        async def mock_run(**kwargs):
            if kwargs["agent_id"] == "coder":
                return mock_result, mock_staging
            return review_result, None

        runner._orchestrator.run_workflow_agent = mock_run

        await runner.execute(session, "task", broadcast)
        assert session.phase == Phase.COMPLETED
