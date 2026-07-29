"""WorkflowRunner 状态机骨架单元测试。

覆盖：
- execute() 主循环各阶段流转
- 用户介入暂停点（PLAN_REVIEW、CODE_REVIEW）
- _advance_to_next_task 状态推进
- _inject_review_feedback 注入逻辑
- 错误路径（_run_* 返回 None）
- 空 task list / 全部完成路径
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.types import Phase, Session, TokenUsage
from backend.workflow.engine import WorkflowRunner
from backend.workflow.types import (
    DiffSet,
    FileReview,
    ReviewReport,
    SubTask,
    TaskList,
    WorkflowState,
    VERDICT_APPROVED,
    VERDICT_NEEDS_CHANGES,
    SEVERITY_BLOCKER,
    SEVERITY_INFO,
    SEVERITY_WARNING,
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
    """返回一个广播闭包，将所有广播收集到列表中。"""
    calls = []

    async def broadcast(event_type: str, payload: dict):
        calls.append({"type": event_type, "payload": payload})

    return broadcast, calls


# ─── execute() 主循环 ───


class TestExecuteInit:
    """从 INIT 阶段启动工作流。"""

    async def test_init_to_plan_review(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log
        mock_task_list = TaskList(
            overview="方案",
            tasks=[SubTask(id="task-1", title="T1", description="D1")],
        )

        with patch.object(runner, "_run_planner", new=AsyncMock(return_value=mock_task_list)):
            await runner.execute(session, "实现登录功能", broadcast)

        assert session.phase == Phase.PLAN_REVIEW
        assert session.workflow_state is not None
        assert session.workflow_state.task_list is not None
        assert session.workflow_state.task_list.tasks[0].id == "task-1"
        # 应广播 planning 和 plan_review 状态
        assert any(c["type"] == "agent.status" and c["payload"]["phase"] == "planning" for c in calls)
        assert any(c["type"] == "agent.status" and c["payload"]["phase"] == "plan_review" for c in calls)

    async def test_init_planner_returns_none_goes_error(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log

        with patch.object(runner, "_run_planner", new=AsyncMock(return_value=None)):
            await runner.execute(session, "实现登录功能", broadcast)

        assert session.phase == Phase.ERROR


class TestExecutePlanReview:
    """PLAN_REVIEW → CODING 流转。"""

    async def test_plan_review_approved_to_coding(self, runner, session, broadcast_log):
        broadcast, _ = broadcast_log
        session.phase = Phase.PLAN_REVIEW
        session.auto_review = False  # 停在 CODE_REVIEW，不进入 REVIEWING
        session.workflow_state = WorkflowState(
            task_list=TaskList(
                tasks=[SubTask(id="task-1", title="T1", description="D1")],
            ),
        )
        mock_diff = DiffSet(task_id="task-1")

        with patch.object(runner, "_run_coder", new=AsyncMock(return_value=mock_diff)):
            await runner.execute(session, "实现登录功能", broadcast)

        assert session.phase == Phase.CODE_REVIEW
        assert session.workflow_state.plan_approved is True
        assert session.workflow_state.current_diff_set is not None

    async def test_plan_review_empty_tasks_to_completed(self, runner, session, broadcast_log):
        broadcast, _ = broadcast_log
        session.phase = Phase.PLAN_REVIEW
        session.workflow_state = WorkflowState(
            task_list=TaskList(tasks=[]),
        )
        mock_diff = DiffSet()

        with patch.object(runner, "_run_coder", new=AsyncMock(return_value=mock_diff)):
            await runner.execute(session, "实现登录功能", broadcast)

        # 空任务列表 → 直接完成
        assert session.phase == Phase.COMPLETED


class TestExecuteCodeReview:
    """CODE_REVIEW → REVIEWING / 暂停 流转。"""

    async def test_auto_review_enabled_to_reviewing(self, runner, session, broadcast_log):
        broadcast, _ = broadcast_log
        session.phase = Phase.CODE_REVIEW
        session.auto_review = True
        session.workflow_state = WorkflowState(
            task_list=TaskList(tasks=[SubTask(id="task-1", title="T1", description="D1")]),
            current_diff_set=DiffSet(task_id="task-1"),
        )
        mock_report = ReviewReport(should_retry=False)

        with patch.object(runner, "_run_reviewer", new=AsyncMock(return_value=mock_report)):
            await runner.execute(session, "实现登录功能", broadcast)

        assert session.phase == Phase.COMPLETED
        assert session.workflow_state.last_review_report is not None

    async def test_auto_review_disabled_pauses(self, runner, session, broadcast_log):
        broadcast, _ = broadcast_log
        session.phase = Phase.CODE_REVIEW
        session.auto_review = False
        session.workflow_state = WorkflowState(
            task_list=TaskList(tasks=[SubTask(id="task-1", title="T1", description="D1")]),
            current_diff_set=DiffSet(task_id="task-1"),
        )

        await runner.execute(session, "实现登录功能", broadcast)

        # 非自动审查：暂停，等待用户命令
        assert session.phase == Phase.CODE_REVIEW


class TestExecuteReviewing:
    """REVIEWING → FEEDBACK / CODING / COMPLETED 流转。"""

    async def test_review_needs_changes_to_feedback(self, runner, session, broadcast_log):
        broadcast, _ = broadcast_log
        session.phase = Phase.REVIEWING
        session.workflow_state = WorkflowState(
            task_list=TaskList(tasks=[SubTask(id="task-1", title="T1", description="D1")]),
            current_diff_set=DiffSet(task_id="task-1"),
        )
        mock_report = ReviewReport(should_retry=True)

        with patch.object(runner, "_run_reviewer", new=AsyncMock(return_value=mock_report)):
            await runner.execute(session, "实现登录功能", broadcast)

        assert session.phase == Phase.FEEDBACK
        assert len(session.coder_guidance_queue) == 1

    async def test_review_approved_advance_to_next_task(self, runner, session, broadcast_log):
        broadcast, _ = broadcast_log
        session.phase = Phase.REVIEWING
        session.auto_review = False  # 停在 CODE_REVIEW，验证任务推进状态
        session.workflow_state = WorkflowState(
            task_list=TaskList(
                tasks=[
                    SubTask(id="task-1", title="T1", description="D1"),
                    SubTask(id="task-2", title="T2", description="D2"),
                ],
                current_task_index=0,
            ),
            current_diff_set=DiffSet(task_id="task-1"),
        )
        mock_report = ReviewReport(should_retry=False)
        mock_diff = DiffSet(task_id="task-2")

        with patch.object(runner, "_run_reviewer", new=AsyncMock(return_value=mock_report)), \
             patch.object(runner, "_run_coder", new=AsyncMock(return_value=mock_diff)):
            await runner.execute(session, "实现登录功能", broadcast)

        assert session.phase == Phase.CODE_REVIEW
        assert session.workflow_state.task_list.current_task_index == 1
        assert "task-1" in session.workflow_state.completed_tasks
        assert session.workflow_state.current_diff_set is not None
        assert session.workflow_state.last_review_report is None

    async def test_review_approved_last_task_to_completed(self, runner, session, broadcast_log):
        broadcast, _ = broadcast_log
        session.phase = Phase.REVIEWING
        session.workflow_state = WorkflowState(
            task_list=TaskList(
                tasks=[SubTask(id="task-1", title="T1", description="D1")],
                current_task_index=0,
            ),
            current_diff_set=DiffSet(task_id="task-1"),
        )
        mock_report = ReviewReport(should_retry=False)

        with patch.object(runner, "_run_reviewer", new=AsyncMock(return_value=mock_report)):
            await runner.execute(session, "实现登录功能", broadcast)

        assert session.phase == Phase.COMPLETED
        assert "task-1" in session.workflow_state.completed_tasks


class TestExecuteFeedback:
    """FEEDBACK → CODING 流转。"""

    async def test_feedback_cleans_and_returns_to_coding(self, runner, session, broadcast_log):
        broadcast, _ = broadcast_log
        session.phase = Phase.FEEDBACK
        session.auto_review = False  # 停在 CODE_REVIEW，不进入 REVIEWING
        session.workflow_state = WorkflowState(
            task_list=TaskList(tasks=[SubTask(id="task-1", title="T1", description="D1")]),
            current_diff_set=DiffSet(task_id="task-1"),
            last_review_report=ReviewReport(should_retry=True),
        )
        mock_diff = DiffSet(task_id="task-1")

        with patch.object(runner, "_run_coder", new=AsyncMock(return_value=mock_diff)):
            await runner.execute(session, "实现登录功能", broadcast)

        assert session.phase == Phase.CODE_REVIEW
        assert session.workflow_state.current_diff_set is not None
        assert session.workflow_state.last_review_report is None


class TestExecuteCompleted:
    """COMPLETED 阶段。"""

    async def test_completed_broadcasts_and_returns(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log
        session.phase = Phase.COMPLETED
        session.workflow_state = WorkflowState(
            task_list=TaskList(
                tasks=[SubTask(id="task-1", title="T1", description="D1")],
            ),
        )

        await runner.execute(session, "实现登录功能", broadcast)

        assert session.phase == Phase.COMPLETED
        assert any(
            c["type"] == "agent.status" and c["payload"]["phase"] == "completed"
            for c in calls
        )


class TestExecuteError:
    """ERROR 阶段。"""

    async def test_error_returns_immediately(self, runner, session, broadcast_log):
        broadcast, _ = broadcast_log
        session.phase = Phase.ERROR

        await runner.execute(session, "实现登录功能", broadcast)

        assert session.phase == Phase.ERROR


# ─── 状态推进 ───


class TestAdvanceToNextTask:
    def test_advance_sets_next_task(self, runner, session):
        session.workflow_state = WorkflowState(
            task_list=TaskList(
                tasks=[
                    SubTask(id="task-1", title="T1", description="D1"),
                    SubTask(id="task-2", title="T2", description="D2"),
                ],
                current_task_index=0,
            ),
            current_diff_set=DiffSet(),
            last_review_report=ReviewReport(),
        )
        runner._advance_to_next_task(session)
        assert session.phase == Phase.CODING
        assert session.workflow_state.task_list.current_task_index == 1
        assert session.workflow_state.completed_tasks == ["task-1"]
        assert session.workflow_state.current_diff_set is None
        assert session.workflow_state.last_review_report is None

    def test_advance_to_completion(self, runner, session):
        session.workflow_state = WorkflowState(
            task_list=TaskList(
                tasks=[SubTask(id="task-1", title="T1", description="D1")],
                current_task_index=0,
            ),
        )
        runner._advance_to_next_task(session)
        assert session.phase == Phase.COMPLETED
        assert "task-1" in session.workflow_state.completed_tasks

    def test_advance_with_no_workflow_state(self, runner, session):
        session.workflow_state = None
        runner._advance_to_next_task(session)
        assert session.phase == Phase.COMPLETED


class TestInjectReviewFeedback:
    def test_inject_single_file(self, runner, session):
        report = ReviewReport(
            summary="需要修改",
            file_reviews=[
                FileReview(file_path="a.py", issues=["bug1"], suggestions=["fix1"], severity=SEVERITY_BLOCKER),
            ],
        )
        runner._inject_review_feedback(session, report)
        assert len(session.coder_guidance_queue) == 1
        assert "需要修改" in session.coder_guidance_queue[0]
        assert "[a.py]" in session.coder_guidance_queue[0]
        assert "bug1" in session.coder_guidance_queue[0]

    def test_inject_multiple_files(self, runner, session):
        report = ReviewReport(
            summary="多项问题",
            file_reviews=[
                FileReview(file_path="a.py", issues=["bug"], severity=SEVERITY_BLOCKER),
                FileReview(file_path="b.py", issues=["style"], severity=SEVERITY_WARNING),
                FileReview(file_path="c.py", issues=[], severity=SEVERITY_INFO),  # 空 issues 不输出
            ],
        )
        runner._inject_review_feedback(session, report)
        assert len(session.coder_guidance_queue) == 1
        assert "多项问题" in session.coder_guidance_queue[0]
        assert "[a.py]" in session.coder_guidance_queue[0]
        assert "[b.py]" in session.coder_guidance_queue[0]
        assert "[c.py]" not in session.coder_guidance_queue[0]


# ─── 端到端循环 ───


class TestEndToEndLoop:
    """完整工作流：INIT → PLANNING → PLAN_REVIEW → CODING → CODE_REVIEW
    → REVIEWING → FEEDBACK → CODING → CODE_REVIEW → REVIEWING → COMPLETED
    """

    async def test_full_loop_with_retry(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log
        task_list = TaskList(
            tasks=[SubTask(id="task-1", title="T1", description="D1")],
        )

        # 第一轮：INIT → PLAN_REVIEW（暂停）
        with patch.object(runner, "_run_planner", new=AsyncMock(return_value=task_list)):
            await runner.execute(session, "实现登录功能", broadcast)
        assert session.phase == Phase.PLAN_REVIEW

        # 第二轮：PLAN_REVIEW → CODE_REVIEW（手动审查模式，停在 CODE_REVIEW）
        session.auto_review = False
        mock_diff = DiffSet(task_id="task-1")
        with patch.object(runner, "_run_coder", new=AsyncMock(return_value=mock_diff)):
            await runner.execute(session, "实现登录功能", broadcast)
        assert session.phase == Phase.CODE_REVIEW

        # 第三轮：CODE_REVIEW(auto) → FEEDBACK（需要重试）
        session.auto_review = True
        mock_report_retry = ReviewReport(should_retry=True)
        with patch.object(runner, "_run_reviewer", new=AsyncMock(return_value=mock_report_retry)):
            await runner.execute(session, "实现登录功能", broadcast)
        assert session.phase == Phase.FEEDBACK
        assert len(session.coder_guidance_queue) == 1

        # 第四轮：FEEDBACK → CODE_REVIEW（coder 重试，手动审查模式）
        session.auto_review = False
        with patch.object(runner, "_run_coder", new=AsyncMock(return_value=mock_diff)):
            await runner.execute(session, "实现登录功能", broadcast)
        assert session.phase == Phase.CODE_REVIEW
        assert session.workflow_state.current_diff_set is not None
        assert session.workflow_state.last_review_report is None

        # 第五轮：CODE_REVIEW(auto) → COMPLETED（审查通过）
        session.auto_review = True
        mock_report_approved = ReviewReport(should_retry=False)
        with patch.object(runner, "_run_reviewer", new=AsyncMock(return_value=mock_report_approved)):
            await runner.execute(session, "实现登录功能", broadcast)
        assert session.phase == Phase.COMPLETED
        assert "task-1" in session.workflow_state.completed_tasks

    async def test_multi_task_no_retry(self, runner, session, broadcast_log):
        broadcast, _ = broadcast_log
        task_list = TaskList(
            tasks=[
                SubTask(id="task-1", title="T1", description="D1"),
                SubTask(id="task-2", title="T2", description="D2"),
            ],
        )

        with patch.object(runner, "_run_planner", new=AsyncMock(return_value=task_list)):
            await runner.execute(session, "实现登录功能", broadcast)
        assert session.phase == Phase.PLAN_REVIEW

        # PLAN_REVIEW → CODING(task-1) → CODE_REVIEW → REVIEWING(approved)
        # → CODING(task-2) → CODE_REVIEW → REVIEWING(approved) → COMPLETED
        mock_diff = DiffSet(task_id="task-1")
        mock_report = ReviewReport(should_retry=False)

        with patch.object(runner, "_run_coder", new=AsyncMock(return_value=mock_diff)), \
             patch.object(runner, "_run_reviewer", new=AsyncMock(return_value=mock_report)):
            await runner.execute(session, "实现登录功能", broadcast)

        assert session.phase == Phase.COMPLETED
        assert session.workflow_state.completed_tasks == ["task-1", "task-2"]
