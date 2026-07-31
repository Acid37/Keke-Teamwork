"""WorkflowRunner 阶段执行器单元测试。

覆盖 Step 5 实现：
- _run_planner：调用 orchestrator + 解析 TaskList
- _run_coder：调用 orchestrator + 从 staging 捕获 DiffSet
- _run_reviewer：调用 orchestrator + 解析 ReviewReport
- _build_coder_message / _build_reviewer_message 消息构建
- 异常路径（orchestrator 抛异常）
- 端到端串联（mock orchestrator，验证 plan → code → review 全流程）
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.types import AgentResult, Phase, Session, TokenUsage
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
    calls = []

    async def broadcast(event_type: str, payload: dict):
        calls.append({"type": event_type, "payload": payload})

    return broadcast, calls


def _make_agent_result(text: str = "") -> AgentResult:
    """创建测试用 AgentResult。"""
    return AgentResult(
        text=text,
        thinking="",
        tool_calls_history=[],
        usage=TokenUsage(input_tokens=100, output_tokens=50),
        messages=[],
    )


# ─── _run_planner 测试 ───


class TestRunPlanner:
    """Planner 阶段执行器测试。"""

    async def test_planner_success(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log
        planner_output = """
根据需求分析，拆解如下：

---TASKLIST_START---
{
  "overview": "实现用户登录",
  "tasks": [
    {"id": "task-1", "title": "创建模型", "description": "创建 User 模型"},
    {"id": "task-2", "title": "实现API", "description": "实现登录API"}
  ],
  "risks": ["需要考虑密码加密"]
}
---TASKLIST_END---
"""
        mock_result = _make_agent_result(planner_output)
        runner._orchestrator.run_workflow_agent = AsyncMock(
            return_value=(mock_result, None))

        task_list = await runner._run_planner(session, "实现登录功能", broadcast)

        assert task_list is not None
        assert task_list.total_count == 2
        assert task_list.tasks[0].id == "task-1"
        assert task_list.tasks[0].title == "创建模型"
        assert task_list.tasks[1].id == "task-2"
        assert task_list.overview == "实现用户登录"
        assert "需要考虑密码加密" in task_list.risks

        # 验证调用了 orchestrator
        runner._orchestrator.run_workflow_agent.assert_called_once()
        call_kwargs = runner._orchestrator.run_workflow_agent.call_args.kwargs
        assert call_kwargs["agent_id"] == "planner"
        assert call_kwargs["phase"] == Phase.PLANNING
        assert call_kwargs["user_message"] == "实现登录功能"

    async def test_planner_parse_failure(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log
        # 无法解析的输出
        mock_result = _make_agent_result("我不知道怎么做")
        runner._orchestrator.run_workflow_agent = AsyncMock(
            return_value=(mock_result, None))

        task_list = await runner._run_planner(session, "任务", broadcast)

        assert task_list is None
        # 应广播错误
        assert any(c["type"] == "error" for c in calls)

    async def test_planner_orchestrator_exception(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log
        runner._orchestrator.run_workflow_agent = AsyncMock(
            side_effect=RuntimeError("LLM 连接失败"))

        task_list = await runner._run_planner(session, "任务", broadcast)

        assert task_list is None
        assert any(c["type"] == "error" for c in calls)

    async def test_planner_broadcasts_status(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log
        mock_result = _make_agent_result("---TASKLIST_START---\n{\"tasks\":[{\"id\":\"t1\",\"title\":\"T1\"}]}\n---TASKLIST_END---")
        runner._orchestrator.run_workflow_agent = AsyncMock(
            return_value=(mock_result, None))

        await runner._run_planner(session, "任务", broadcast)

        # 应广播 planning 状态
        assert any(
            c["type"] == "agent.status" and c["payload"]["phase"] == "planning"
            for c in calls
        )


# ─── _run_coder 测试 ───


class TestRunCoder:
    """Coder 阶段执行器测试。"""

    async def test_coder_with_staging_changes(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log
        task = SubTask(id="task-1", title="T1", description="D1")

        # Mock staging with file changes
        mock_commit = MagicMock()
        mock_commit.files_changed = 2
        mock_commit.diffs = []
        mock_commit.combined_diff = "--- a/file.py\n+++ b/file.py\n"
        mock_commit.summary = "修改了两个文件"

        mock_staging = MagicMock()
        mock_staging.commit.return_value = mock_commit

        mock_result = _make_agent_result("编码完成")
        runner._orchestrator.run_workflow_agent = AsyncMock(
            return_value=(mock_result, mock_staging))

        diff_set = await runner._run_coder(session, task, broadcast)

        assert diff_set is not None
        assert diff_set.task_id == "task-1"
        assert diff_set.files_changed == 2
        assert diff_set.summary == "修改了两个文件"
        mock_staging.commit.assert_called_once()

    async def test_coder_no_file_changes(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log
        task = SubTask(id="task-1", title="T1", description="D1")

        mock_commit = MagicMock()
        mock_commit.files_changed = 0

        mock_staging = MagicMock()
        mock_staging.commit.return_value = mock_commit

        mock_result = _make_agent_result("分析完成，无需修改")
        runner._orchestrator.run_workflow_agent = AsyncMock(
            return_value=(mock_result, mock_staging))

        diff_set = await runner._run_coder(session, task, broadcast)

        assert diff_set is not None
        assert diff_set.files_changed == 0
        assert "分析完成" in diff_set.summary

    async def test_coder_no_staging_fallback(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log
        task = SubTask(id="task-1", title="T1", description="D1")

        mock_result = _make_agent_result("done")
        runner._orchestrator.run_workflow_agent = AsyncMock(
            return_value=(mock_result, None))

        diff_set = await runner._run_coder(session, task, broadcast)

        # 无 staging 时应返回空 DiffSet
        assert diff_set is not None
        assert diff_set.task_id == "task-1"
        assert diff_set.files_changed == 0

    async def test_coder_exception(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log
        task = SubTask(id="task-1", title="T1", description="D1")

        runner._orchestrator.run_workflow_agent = AsyncMock(
            side_effect=RuntimeError("Coder failed"))

        diff_set = await runner._run_coder(session, task, broadcast)

        assert diff_set is None
        assert any(c["type"] == "error" for c in calls)

    async def test_coder_broadcasts_status(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log
        task = SubTask(id="task-1", title="创建模型", description="D1")

        mock_commit = MagicMock()
        mock_commit.files_changed = 0
        mock_staging = MagicMock()
        mock_staging.commit.return_value = mock_commit

        mock_result = _make_agent_result("done")
        runner._orchestrator.run_workflow_agent = AsyncMock(
            return_value=(mock_result, mock_staging))

        await runner._run_coder(session, task, broadcast)

        assert any(
            c["type"] == "agent.status" and c["payload"]["phase"] == "coding"
            for c in calls
        )


# ─── _run_reviewer 测试 ───


class TestRunReviewer:
    """Reviewer 阶段执行器测试。"""

    async def test_reviewer_success(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log
        session.workflow_state = WorkflowState(
            current_diff_set=DiffSet(task_id="task-1", summary="变更摘要"),
        )

        review_output = """
---REVIEW_START---
{
  "overall_verdict": "approved",
  "summary": "代码质量良好",
  "should_retry": false
}
---REVIEW_END---
"""
        mock_result = _make_agent_result(review_output)
        runner._orchestrator.run_workflow_agent = AsyncMock(
            return_value=(mock_result, None))

        report = await runner._run_reviewer(session, broadcast)

        assert report is not None
        assert report.overall_verdict == VERDICT_APPROVED
        assert report.should_retry is False
        assert report.summary == "代码质量良好"
        assert report.task_id == "task-1"

    async def test_reviewer_needs_changes(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log
        session.workflow_state = WorkflowState(
            current_diff_set=DiffSet(task_id="task-1"),
        )

        review_output = """
---REVIEW_START---
{
  "overall_verdict": "needs_changes",
  "summary": "需要修改",
  "should_retry": true,
  "file_reviews": [
    {"file_path": "src/main.py", "issues": ["bug"], "severity": "blocker"}
  ]
}
---REVIEW_END---
"""
        mock_result = _make_agent_result(review_output)
        runner._orchestrator.run_workflow_agent = AsyncMock(
            return_value=(mock_result, None))

        report = await runner._run_reviewer(session, broadcast)

        assert report is not None
        assert report.overall_verdict == VERDICT_NEEDS_CHANGES
        assert report.should_retry is True
        assert len(report.file_reviews) == 1

    async def test_reviewer_parse_failure_defaults_approved(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log
        session.workflow_state = WorkflowState(
            current_diff_set=DiffSet(task_id="task-1"),
        )

        mock_result = _make_agent_result("无法解析的输出")
        runner._orchestrator.run_workflow_agent = AsyncMock(
            return_value=(mock_result, None))

        report = await runner._run_reviewer(session, broadcast)

        # 解析失败时默认通过
        assert report is not None
        assert report.overall_verdict == VERDICT_APPROVED
        assert report.should_retry is False

    async def test_reviewer_exception(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log
        session.workflow_state = WorkflowState(
            current_diff_set=DiffSet(task_id="task-1"),
        )

        runner._orchestrator.run_workflow_agent = AsyncMock(
            side_effect=RuntimeError("Reviewer failed"))

        report = await runner._run_reviewer(session, broadcast)

        assert report is None
        assert any(c["type"] == "error" for c in calls)

    async def test_reviewer_no_diff(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log
        session.workflow_state = WorkflowState()

        mock_result = _make_agent_result("---REVIEW_START---\n{\"overall_verdict\":\"approved\"}\n---REVIEW_END---")
        runner._orchestrator.run_workflow_agent = AsyncMock(
            return_value=(mock_result, None))

        report = await runner._run_reviewer(session, broadcast)

        assert report is not None
        assert report.task_id == ""


# ─── 消息构建测试 ───


class TestMessageBuilders:
    """消息构建辅助方法测试。"""

    def test_build_coder_message_basic(self, runner, session):
        task = SubTask(id="t1", title="创建模型", description="创建 User 模型")
        msg = runner._build_coder_message(task, session)

        assert "创建模型" in msg
        assert "创建 User 模型" in msg
        assert "任务标题" in msg

    def test_build_coder_message_with_files(self, runner, session):
        task = SubTask(
            id="t1", title="T1", description="D1",
            files_involved=["src/models.py", "src/db.py"],
            acceptance_criteria="测试通过",
        )
        msg = runner._build_coder_message(task, session)

        assert "src/models.py" in msg
        assert "src/db.py" in msg
        assert "测试通过" in msg

    def test_build_coder_message_with_feedback(self, runner, session):
        task = SubTask(id="t1", title="T1", description="D1")
        session.coder_guidance_queue.append("修复 bug")
        msg = runner._build_coder_message(task, session)

        assert "审查反馈" in msg
        assert "修复 bug" in msg
        # 消息构建后应清空 guidance queue
        assert len(session.coder_guidance_queue) == 0

    def test_build_reviewer_message_with_diff(self, runner):
        diff = DiffSet(
            task_id="t1",
            files_changed=2,
            combined_diff="--- a/file.py\n+++ b/file.py\n",
            summary="修改了两个文件",
            test_results="所有测试通过",
        )
        msg = runner._build_reviewer_message(diff)

        assert "修改了两个文件" in msg
        assert "2" in msg
        assert "所有测试通过" in msg
        assert "approved" in msg or "needs_changes" in msg

    def test_build_reviewer_message_no_diff(self, runner):
        msg = runner._build_reviewer_message(None)
        assert "审查" in msg

    def test_build_reviewer_message_truncates_long_diff(self, runner):
        long_diff = "x" * 10000
        diff = DiffSet(task_id="t1", combined_diff=long_diff)
        msg = runner._build_reviewer_message(diff)

        # diff 应被截断
        assert "截断" in msg
        assert len(msg) < 10000


# ─── 端到端串联测试 ───


class TestEndToEndFlow:
    """端到端工作流串联测试（mock orchestrator）。

    验证 plan → code → review 全流程，
    确保各阶段正确调用 orchestrator 并处理产出物。
    """

    async def test_full_flow_auto_review(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log
        session.auto_review = True

        # 准备各阶段 mock 返回
        planner_output = "---TASKLIST_START---\n{\"tasks\":[{\"id\":\"t1\",\"title\":\"T1\"}]}\n---TASKLIST_END---"
        coder_result = _make_agent_result("编码完成")

        mock_commit = MagicMock()
        mock_commit.files_changed = 1
        mock_commit.diffs = []
        mock_commit.combined_diff = "diff"
        mock_commit.summary = "修改"
        mock_staging = MagicMock()
        mock_staging.commit.return_value = mock_commit

        reviewer_output = "---REVIEW_START---\n{\"overall_verdict\":\"approved\",\"should_retry\":false}\n---REVIEW_END---"
        reviewer_result = _make_agent_result(reviewer_output)

        call_count = [0]

        async def mock_run_workflow_agent(**kwargs):
            call_count[0] += 1
            if kwargs["agent_id"] == "planner":
                return _make_agent_result(planner_output), None
            elif kwargs["agent_id"] == "coder":
                return coder_result, mock_staging
            elif kwargs["agent_id"] == "reviewer":
                return reviewer_result, None
            return _make_agent_result(""), None

        runner._orchestrator.run_workflow_agent = mock_run_workflow_agent

        # 第一次执行：INIT → PLANNING → PLAN_REVIEW
        await runner.execute(session, "实现功能", broadcast)
        assert session.phase == Phase.PLAN_REVIEW
        assert call_count[0] == 1  # planner called

        # 用户确认计划 → 第二次执行
        await runner.execute(session, "实现功能", broadcast)
        # auto_review=True → 应自动进入审查并完成
        assert session.phase == Phase.COMPLETED
        assert call_count[0] == 3  # planner + coder + reviewer

        # 验证工作流状态
        ws = session.workflow_state
        assert ws is not None
        assert "t1" in ws.completed_tasks

    async def test_full_flow_with_retry(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log
        session.auto_review = True

        planner_output = "---TASKLIST_START---\n{\"tasks\":[{\"id\":\"t1\",\"title\":\"T1\"}]}\n---TASKLIST_END---"

        mock_commit = MagicMock()
        mock_commit.files_changed = 1
        mock_commit.diffs = []
        mock_commit.combined_diff = "diff"
        mock_commit.summary = "修改"
        mock_staging = MagicMock()
        mock_staging.commit.return_value = mock_commit

        review_fail_output = "---REVIEW_START---\n{\"overall_verdict\":\"needs_changes\",\"should_retry\":true}\n---REVIEW_END---"
        review_pass_output = "---REVIEW_START---\n{\"overall_verdict\":\"approved\",\"should_retry\":false}\n---REVIEW_END---"

        review_count = [0]

        async def mock_run_workflow_agent(**kwargs):
            if kwargs["agent_id"] == "planner":
                return _make_agent_result(planner_output), None
            elif kwargs["agent_id"] == "coder":
                return _make_agent_result("编码完成"), mock_staging
            elif kwargs["agent_id"] == "reviewer":
                review_count[0] += 1
                if review_count[0] == 1:
                    return _make_agent_result(review_fail_output), None
                return _make_agent_result(review_pass_output), None
            return _make_agent_result(""), None

        runner._orchestrator.run_workflow_agent = mock_run_workflow_agent

        # INIT → PLAN_REVIEW
        await runner.execute(session, "任务", broadcast)
        assert session.phase == Phase.PLAN_REVIEW

        # 确认计划 → CODING → CODE_REVIEW → REVIEWING → FEEDBACK（审查不通过）
        await runner.execute(session, "任务", broadcast)
        assert session.phase == Phase.FEEDBACK

        # FEEDBACK → CODING → CODE_REVIEW → REVIEWING → COMPLETED（审查通过）
        await runner.execute(session, "任务", broadcast)
        assert session.phase == Phase.COMPLETED

        # 验证审查被调用了两次
        assert review_count[0] == 2

    async def test_full_flow_no_auto_review(self, runner, session, broadcast_log):
        broadcast, calls = broadcast_log
        session.auto_review = False  # 不自动审查

        planner_output = "---TASKLIST_START---\n{\"tasks\":[{\"id\":\"t1\",\"title\":\"T1\"}]}\n---TASKLIST_END---"

        mock_commit = MagicMock()
        mock_commit.files_changed = 1
        mock_commit.diffs = []
        mock_commit.combined_diff = "diff"
        mock_commit.summary = "修改"
        mock_staging = MagicMock()
        mock_staging.commit.return_value = mock_commit

        async def mock_run_workflow_agent(**kwargs):
            if kwargs["agent_id"] == "planner":
                return _make_agent_result(planner_output), None
            elif kwargs["agent_id"] == "coder":
                return _make_agent_result("编码完成"), mock_staging
            return _make_agent_result(""), None

        runner._orchestrator.run_workflow_agent = mock_run_workflow_agent

        # INIT → PLAN_REVIEW
        await runner.execute(session, "任务", broadcast)
        assert session.phase == Phase.PLAN_REVIEW

        # 确认 → CODING → CODE_REVIEW（暂停，不自动审查）
        await runner.execute(session, "任务", broadcast)
        assert session.phase == Phase.CODE_REVIEW

        # 验证 reviewer 未被调用
        assert session.workflow_state.last_review_report is None
