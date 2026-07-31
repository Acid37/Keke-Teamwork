"""工作流状态持久化与恢复单元测试。

覆盖 Step 7 实现：
- WorkflowRunner 自动持久化（_save_session 在阶段转换后触发）
- SessionStore 完整保存/加载 workflow_state 往返
- 从各阶段恢复会话（PLAN_REVIEW / CODE_REVIEW / FEEDBACK / ERROR / COMPLETED）
- _save_session 错误处理（不崩溃）
- 无 session_store 时向后兼容
- CLI --resume 路径验证
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.types import Phase, Session, TokenUsage
from backend.session import SessionStore
from backend.workflow.engine import WorkflowRunner
from backend.workflow.types import (
    DiffSet,
    FileReview,
    ReviewReport,
    SubTask,
    TaskList,
    WorkflowState,
    TASK_DONE,
    TASK_IN_PROGRESS,
    VERDICT_APPROVED,
    VERDICT_NEEDS_CHANGES,
    SEVERITY_BLOCKER,
    SEVERITY_INFO,
)


# ─── Fixtures ───


@pytest.fixture
def mock_orchestrator():
    return MagicMock()


@pytest.fixture
def mock_agent_store():
    return MagicMock()


@pytest.fixture
def tmp_data_dir():
    with TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def session_store(tmp_data_dir):
    return SessionStore(tmp_data_dir)


@pytest.fixture
def runner_with_store(mock_orchestrator, mock_agent_store, session_store):
    return WorkflowRunner(mock_orchestrator, mock_agent_store, session_store)


@pytest.fixture
def runner_no_store(mock_orchestrator, mock_agent_store):
    return WorkflowRunner(mock_orchestrator, mock_agent_store)


@pytest.fixture
def broadcast_log():
    calls = []

    async def broadcast(event_type: str, payload: dict):
        calls.append({"type": event_type, "payload": payload})

    return broadcast, calls


def _make_subtask(
    id: str = "task-1",
    title: str = "创建模型",
    status: str = TASK_IN_PROGRESS,
) -> SubTask:
    return SubTask(
        id=id,
        title=title,
        description=f"实现 {title}",
        files_involved=["src/models.py"],
        acceptance_criteria="可实例化",
        status=status,
    )


def _make_session(
    phase: Phase = Phase.PLAN_REVIEW,
    session_id: str = "test-persist-001",
    tasks: list[SubTask] | None = None,
    current_task_index: int = 0,
    diff_set: DiffSet | None = None,
    review_report: ReviewReport | None = None,
    plan_approved: bool = False,
) -> Session:
    """创建带完整 WorkflowState 的测试会话。"""
    session = Session(
        id=session_id,
        work_dir=Path("/tmp/test"),
        phase=phase,
        title="测试任务",
    )
    ws = WorkflowState()
    if tasks is not None:
        ws.task_list = TaskList(
            overview="测试方案",
            tasks=tasks,
            risks=["依赖外部 API"],
            estimated_effort="2h",
            current_task_index=current_task_index,
        )
    ws.current_diff_set = diff_set
    ws.last_review_report = review_report
    ws.plan_approved = plan_approved
    ws.completed_tasks = [t.id for t in (tasks or []) if t.status == TASK_DONE]
    session.workflow_state = ws
    return session


# ─── _save_session 基础测试 ───


class TestSaveSession:
    """_save_session 方法测试。"""

    def test_save_with_store(self, runner_with_store, session_store):
        """有 session_store 时正常保存。"""
        session = _make_session(Phase.PLAN_REVIEW)
        runner_with_store._save_session(session)

        loaded = session_store.load("test-persist-001")
        assert loaded is not None
        assert loaded.phase == Phase.PLAN_REVIEW

    def test_save_without_store(self, runner_no_store):
        """无 session_store 时静默跳过，不报错。"""
        session = _make_session(Phase.PLAN_REVIEW)
        # 不应抛异常
        runner_no_store._save_session(session)

    def test_save_updates_last_active_at(self, runner_with_store, session_store):
        """保存时更新 last_active_at。"""
        session = _make_session(Phase.INIT)
        old_ts = session.last_active_at
        import time
        time.sleep(0.01)
        runner_with_store._save_session(session)
        assert session.last_active_at > old_ts

    def test_save_error_does_not_crash(self, mock_orchestrator, mock_agent_store):
        """session_store.save 抛异常时不影响工作流。"""
        broken_store = MagicMock()
        broken_store.save.side_effect = RuntimeError("disk full")

        runner = WorkflowRunner(mock_orchestrator, mock_agent_store, broken_store)
        session = _make_session(Phase.CODING)

        # 不应抛异常
        runner._save_session(session)
        broken_store.save.assert_called_once()


# ─── 自动持久化：handle_user_command ───


class TestAutoSaveOnCommand:
    """用户命令处理后自动持久化。"""

    async def test_approve_plan_persists(
        self, runner_with_store, session_store, broadcast_log,
    ):
        broadcast, _ = broadcast_log
        session = _make_session(
            Phase.PLAN_REVIEW,
            tasks=[_make_subtask()],
        )
        runner_with_store._save_session = MagicMock(wraps=runner_with_store._save_session)

        await runner_with_store.handle_user_command(session, "approve_plan", broadcast)

        runner_with_store._save_session.assert_called()
        loaded = session_store.load("test-persist-001")
        assert loaded is not None
        assert loaded.phase == Phase.CODING
        assert loaded.workflow_state.plan_approved is True

    async def test_abort_persists(
        self, runner_with_store, session_store, broadcast_log,
    ):
        broadcast, _ = broadcast_log
        session = _make_session(
            Phase.CODING,
            tasks=[_make_subtask()],
            plan_approved=True,
        )

        await runner_with_store.handle_user_command(session, "abort", broadcast)

        loaded = session_store.load("test-persist-001")
        assert loaded is not None
        assert loaded.phase == Phase.ERROR

    async def test_resume_persists(
        self, runner_with_store, session_store, broadcast_log,
    ):
        broadcast, _ = broadcast_log
        session = _make_session(Phase.ERROR)

        await runner_with_store.handle_user_command(session, "resume", broadcast)

        loaded = session_store.load("test-persist-001")
        assert loaded is not None
        assert loaded.phase == Phase.INIT

    async def test_no_store_no_crash_on_command(
        self, runner_no_store, broadcast_log,
    ):
        """无 session_store 时命令处理正常工作。"""
        broadcast, _ = broadcast_log
        session = _make_session(
            Phase.PLAN_REVIEW,
            tasks=[_make_subtask()],
        )

        result = await runner_no_store.handle_user_command(session, "approve_plan", broadcast)

        assert result is True
        assert session.phase == Phase.CODING


# ─── 完整序列化往返 ───


class TestFullRoundTrip:
    """完整 WorkflowState 保存/加载往返测试。"""

    def test_plan_review_roundtrip(self, session_store):
        """PLAN_REVIEW 阶段状态完整往返。"""
        tasks = [
            _make_subtask("task-1", "创建模型"),
            _make_subtask("task-2", "创建视图"),
        ]
        session = _make_session(
            Phase.PLAN_REVIEW,
            tasks=tasks,
            plan_approved=False,
        )

        session_store.save(session)
        loaded = session_store.load(session.id)

        assert loaded is not None
        assert loaded.phase == Phase.PLAN_REVIEW
        assert loaded.workflow_state is not None
        assert loaded.workflow_state.plan_approved is False
        assert loaded.workflow_state.task_list is not None
        assert loaded.workflow_state.task_list.total_count == 2
        assert loaded.workflow_state.task_list.overview == "测试方案"
        assert loaded.workflow_state.task_list.risks == ["依赖外部 API"]
        assert loaded.workflow_state.task_list.estimated_effort == "2h"

    def test_coding_roundtrip(self, session_store):
        """CODING 阶段（含 diff_set）完整往返。"""
        diff = DiffSet(
            task_id="task-1",
            files_changed=2,
            diffs=[{"path": "src/models.py", "action": "create", "diff_text": "@@..."}],
            combined_diff="--- a\n+++ b\n@@...",
            summary="新增 User 模型",
        )
        session = _make_session(
            Phase.CODING,
            tasks=[_make_subtask()],
            diff_set=diff,
            plan_approved=True,
        )

        session_store.save(session)
        loaded = session_store.load(session.id)

        assert loaded is not None
        assert loaded.phase == Phase.CODING
        ws = loaded.workflow_state
        assert ws.current_diff_set is not None
        assert ws.current_diff_set.task_id == "task-1"
        assert ws.current_diff_set.files_changed == 2
        assert ws.current_diff_set.summary == "新增 User 模型"

    def test_feedback_roundtrip(self, session_store):
        """FEEDBACK 阶段（含 review_report）完整往返。"""
        report = ReviewReport(
            task_id="task-1",
            overall_verdict=VERDICT_NEEDS_CHANGES,
            file_reviews=[
                FileReview(
                    file_path="src/models.py",
                    issues=["缺少类型注解"],
                    suggestions=["添加 type hints"],
                    severity=SEVERITY_BLOCKER,
                ),
            ],
            summary="需要修改",
            should_retry=True,
        )
        session = _make_session(
            Phase.FEEDBACK,
            tasks=[_make_subtask()],
            review_report=report,
            plan_approved=True,
        )

        session_store.save(session)
        loaded = session_store.load(session.id)

        assert loaded is not None
        assert loaded.phase == Phase.FEEDBACK
        ws = loaded.workflow_state
        assert ws.last_review_report is not None
        assert ws.last_review_report.overall_verdict == VERDICT_NEEDS_CHANGES
        assert ws.last_review_report.should_retry is True
        assert len(ws.last_review_report.file_reviews) == 1
        fr = ws.last_review_report.file_reviews[0]
        assert fr.file_path == "src/models.py"
        assert fr.severity == SEVERITY_BLOCKER

    def test_completed_roundtrip(self, session_store):
        """COMPLETED 阶段完整往返。"""
        tasks = [
            SubTask(id="t1", title="T1", description="D1", status=TASK_DONE),
            SubTask(id="t2", title="T2", description="D2", status=TASK_DONE),
        ]
        session = _make_session(
            Phase.COMPLETED,
            tasks=tasks,
            current_task_index=2,
            plan_approved=True,
        )

        session_store.save(session)
        loaded = session_store.load(session.id)

        assert loaded is not None
        assert loaded.phase == Phase.COMPLETED
        ws = loaded.workflow_state
        assert ws.task_list.completed_count == 2
        assert ws.task_list.current_task is None
        assert set(ws.completed_tasks) == {"t1", "t2"}

    def test_empty_workflow_state_roundtrip(self, session_store):
        """空 WorkflowState 往返。"""
        session = Session(
            id="empty-session",
            work_dir=Path("/tmp/test"),
            phase=Phase.INIT,
        )
        session.workflow_state = WorkflowState()

        session_store.save(session)
        loaded = session_store.load(session.id)

        assert loaded is not None
        assert loaded.workflow_state is not None
        assert loaded.workflow_state.task_list is None
        assert loaded.workflow_state.plan_approved is False

    def test_none_workflow_state_roundtrip(self, session_store):
        """workflow_state=None 往返。"""
        session = Session(
            id="none-ws-session",
            work_dir=Path("/tmp/test"),
            phase=Phase.INIT,
        )
        session.workflow_state = None

        session_store.save(session)
        loaded = session_store.load(session.id)

        assert loaded is not None
        assert loaded.workflow_state is None


# ─── 恢复场景测试 ───


class TestResumeFromPhases:
    """从不同阶段恢复会话测试。"""

    def test_resume_from_plan_review(self, session_store):
        """从 PLAN_REVIEW 恢复——计划仍在，等待用户确认。"""
        tasks = [_make_subtask("task-1", "创建模型")]
        session = _make_session(Phase.PLAN_REVIEW, tasks=tasks)

        session_store.save(session)
        loaded = session_store.load(session.id)

        assert loaded.phase == Phase.PLAN_REVIEW
        assert loaded.workflow_state.task_list is not None
        assert loaded.workflow_state.task_list.total_count == 1
        assert loaded.workflow_state.plan_approved is False

    def test_resume_from_code_review(self, session_store):
        """从 CODE_REVIEW 恢复——代码已产出，等待审查决策。"""
        diff = DiffSet(task_id="task-1", files_changed=1, summary="修改完成")
        session = _make_session(
            Phase.CODE_REVIEW,
            tasks=[_make_subtask()],
            diff_set=diff,
            plan_approved=True,
        )

        session_store.save(session)
        loaded = session_store.load(session.id)

        assert loaded.phase == Phase.CODE_REVIEW
        assert loaded.workflow_state.current_diff_set is not None
        assert loaded.workflow_state.current_diff_set.task_id == "task-1"

    def test_resume_from_feedback(self, session_store):
        """从 FEEDBACK 恢复——审查未通过，等待重试决策。"""
        report = ReviewReport(
            task_id="task-1",
            overall_verdict=VERDICT_NEEDS_CHANGES,
            should_retry=True,
            summary="需要修改",
        )
        session = _make_session(
            Phase.FEEDBACK,
            tasks=[_make_subtask()],
            review_report=report,
            plan_approved=True,
        )

        session_store.save(session)
        loaded = session_store.load(session.id)

        assert loaded.phase == Phase.FEEDBACK
        assert loaded.workflow_state.last_review_report is not None
        assert loaded.workflow_state.last_review_report.should_retry is True

    def test_resume_from_error(self, session_store):
        """从 ERROR 恢复——等待用户决定是否重新规划。"""
        session = _make_session(Phase.ERROR)

        session_store.save(session)
        loaded = session_store.load(session.id)

        assert loaded.phase == Phase.ERROR

    def test_resume_preserves_completed_tasks(self, session_store):
        """恢复时保留已完成的任务记录。"""
        tasks = [
            SubTask(id="t1", title="T1", description="D1", status=TASK_DONE),
            SubTask(id="t2", title="T2", description="D2", status=TASK_IN_PROGRESS),
        ]
        session = _make_session(
            Phase.CODING,
            tasks=tasks,
            current_task_index=1,
            plan_approved=True,
        )

        session_store.save(session)
        loaded = session_store.load(session.id)

        ws = loaded.workflow_state
        assert "t1" in ws.completed_tasks
        assert ws.task_list.current_task_index == 1
        assert ws.task_list.current_task.id == "t2"

    def test_resume_preserves_usage(self, session_store):
        """恢复时保留 token 使用统计。"""
        session = _make_session(Phase.PLAN_REVIEW)
        session.usage_total = TokenUsage(input_tokens=5000, output_tokens=1200)

        session_store.save(session)
        loaded = session_store.load(session.id)

        assert loaded.usage_total.input_tokens == 5000
        assert loaded.usage_total.output_tokens == 1200

    def test_resume_preserves_messages(self, session_store):
        """恢复时保留消息历史。"""
        session = _make_session(Phase.PLAN_REVIEW)
        session.messages = [
            {"role": "user", "content": "实现登录功能"},
            {"role": "assistant", "content": "好的，让我分析..."},
        ]

        session_store.save(session)
        loaded = session_store.load(session.id)

        assert len(loaded.messages) == 2
        assert loaded.messages[0]["role"] == "user"

    def test_resume_preserves_title(self, session_store):
        """恢复时保留任务标题（用于恢复时获取任务描述）。"""
        session = _make_session(Phase.PLAN_REVIEW)
        session.title = "实现用户认证模块"

        session_store.save(session)
        loaded = session_store.load(session.id)

        assert loaded.title == "实现用户认证模块"


# ─── 多次保存覆盖测试 ───


class TestMultipleSaves:
    """多次保存/覆盖测试。"""

    def test_save_overwrite(self, session_store):
        """同一会话多次保存，后一次覆盖前一次。"""
        session = _make_session(Phase.INIT)
        session_store.save(session)

        session.phase = Phase.PLAN_REVIEW
        session.workflow_state.plan_approved = True
        session_store.save(session)

        loaded = session_store.load(session.id)
        assert loaded.phase == Phase.PLAN_REVIEW
        assert loaded.workflow_state.plan_approved is True

    def test_multiple_sessions(self, session_store):
        """多个会话同时保存，互不干扰。"""
        s1 = _make_session(Phase.PLAN_REVIEW, session_id="session-1")
        s2 = _make_session(Phase.CODING, session_id="session-2", plan_approved=True)

        session_store.save(s1)
        session_store.save(s2)

        loaded1 = session_store.load("session-1")
        loaded2 = session_store.load("session-2")

        assert loaded1.phase == Phase.PLAN_REVIEW
        assert loaded2.phase == Phase.CODING

    def test_list_sessions_includes_workflow_phase(self, session_store):
        """list_sessions 返回的摘要包含工作流阶段。"""
        s1 = _make_session(Phase.PLAN_REVIEW, session_id="s1")
        s2 = _make_session(Phase.COMPLETED, session_id="s2")

        session_store.save(s1)
        session_store.save(s2)

        sessions = session_store.list_sessions()
        phases = {s["session_id"]: s["phase"] for s in sessions}
        assert phases["s1"] == "plan_review"
        assert phases["s2"] == "completed"


# ─── execute() 中的自动保存 ───


class TestAutoSaveInExecute:
    """execute() 主循环中自动保存测试。"""

    async def test_planning_to_plan_review_saves(
        self, runner_with_store, session_store, broadcast_log,
    ):
        """PLANNING → PLAN_REVIEW 转换后自动保存。"""
        broadcast, _ = broadcast_log

        # Mock planner 返回有效 TaskList
        task_list = TaskList(tasks=[_make_subtask()])
        runner_with_store._run_planner = AsyncMock(return_value=task_list)

        session = _make_session(Phase.INIT)

        await runner_with_store.execute(session, "测试任务", broadcast)

        loaded = session_store.load("test-persist-001")
        assert loaded is not None
        assert loaded.phase == Phase.PLAN_REVIEW
        assert loaded.workflow_state.task_list is not None

    async def test_error_on_planner_saves(
        self, runner_with_store, session_store, broadcast_log,
    ):
        """Planner 失败 → ERROR 时自动保存。"""
        broadcast, _ = broadcast_log
        runner_with_store._run_planner = AsyncMock(return_value=None)

        session = _make_session(Phase.INIT)

        await runner_with_store.execute(session, "测试任务", broadcast)

        loaded = session_store.load("test-persist-001")
        assert loaded is not None
        assert loaded.phase == Phase.ERROR

    async def test_completed_saves(
        self, runner_with_store, session_store, broadcast_log,
    ):
        """COMPLETED 阶段自动保存。"""
        broadcast, _ = broadcast_log

        # 设置所有任务已完成
        tasks = [SubTask(id="t1", title="T1", description="D1", status=TASK_DONE)]
        session = _make_session(
            Phase.COMPLETED,
            tasks=tasks,
            current_task_index=1,
            plan_approved=True,
        )

        await runner_with_store.execute(session, "测试任务", broadcast)

        loaded = session_store.load("test-persist-001")
        assert loaded is not None
        assert loaded.phase == Phase.COMPLETED

    async def test_no_store_execute_works(
        self, runner_no_store, broadcast_log,
    ):
        """无 session_store 时 execute() 正常工作。"""
        broadcast, _ = broadcast_log

        task_list = TaskList(tasks=[_make_subtask()])
        runner_no_store._run_planner = AsyncMock(return_value=task_list)

        session = _make_session(Phase.INIT)

        await runner_no_store.execute(session, "测试任务", broadcast)

        assert session.phase == Phase.PLAN_REVIEW


# ─── 恢复后继续执行测试 ───


class TestResumeAndContinue:
    """恢复后继续执行测试。"""

    async def test_resume_plan_review_then_approve(
        self, runner_with_store, session_store, broadcast_log,
    ):
        """恢复 PLAN_REVIEW 会话 → approve_plan → 继续。"""
        broadcast, _ = broadcast_log

        # 保存一个 PLAN_REVIEW 会话
        tasks = [_make_subtask("task-1", "创建模型")]
        session = _make_session(Phase.PLAN_REVIEW, tasks=tasks)
        session_store.save(session)

        # 模拟重新加载（新 runner 实例）
        loaded = session_store.load(session.id)
        assert loaded is not None

        # 执行 approve_plan
        result = await runner_with_store.handle_user_command(
            loaded, "approve_plan", broadcast,
        )

        assert result is True
        assert loaded.phase == Phase.CODING

        # 验证已持久化新状态
        reloaded = session_store.load(session.id)
        assert reloaded.phase == Phase.CODING

    async def test_resume_error_then_resume_command(
        self, runner_with_store, session_store, broadcast_log,
    ):
        """恢复 ERROR 会话 → resume 命令 → 回到 INIT。"""
        broadcast, _ = broadcast_log

        session = _make_session(Phase.ERROR)
        session_store.save(session)

        loaded = session_store.load(session.id)
        assert loaded is not None

        result = await runner_with_store.handle_user_command(
            loaded, "resume", broadcast,
        )

        assert result is True
        assert loaded.phase == Phase.INIT

        reloaded = session_store.load(session.id)
        assert reloaded.phase == Phase.INIT

    async def test_resume_preserves_task_progress(
        self, runner_with_store, session_store, broadcast_log,
    ):
        """恢复后任务进度（current_task_index）保持正确。"""
        broadcast, _ = broadcast_log

        # 第一个任务已完成，第二个正在执行
        tasks = [
            SubTask(id="t1", title="T1", description="D1", status=TASK_DONE),
            SubTask(id="t2", title="T2", description="D2", status=TASK_IN_PROGRESS),
            SubTask(id="t3", title="T3", description="D3"),
        ]
        session = _make_session(
            Phase.CODE_REVIEW,
            tasks=tasks,
            current_task_index=1,
            plan_approved=True,
        )
        session_store.save(session)

        loaded = session_store.load(session.id)
        ws = loaded.workflow_state
        assert ws.task_list.current_task_index == 1
        assert ws.task_list.current_task.id == "t2"
        assert "t1" in ws.completed_tasks

    async def test_resume_skip_review_advances(
        self, runner_with_store, session_store, broadcast_log,
    ):
        """恢复 CODE_REVIEW → skip_review → 推进到下一任务。"""
        broadcast, _ = broadcast_log

        tasks = [
            SubTask(id="t1", title="T1", description="D1", status=TASK_IN_PROGRESS),
            SubTask(id="t2", title="T2", description="D2"),
        ]
        session = _make_session(
            Phase.CODE_REVIEW,
            tasks=tasks,
            current_task_index=0,
            plan_approved=True,
        )
        session_store.save(session)

        loaded = session_store.load(session.id)

        result = await runner_with_store.handle_user_command(
            loaded, "skip_review", broadcast,
        )

        assert result is True
        # skip_review 推进到下一个任务
        assert loaded.phase == Phase.CODING
        assert loaded.workflow_state.task_list.current_task_index == 1

        reloaded = session_store.load(session.id)
        assert reloaded.phase == Phase.CODING
