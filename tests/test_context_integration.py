"""repo_map 集成 + 阶段间上下文传递 单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.prompt_builder import (
    _completed_tasks_block,
    _plan_overview_block,
    _repo_map_block,
    build_phase_prompt,
)
from backend.types import AgentDefinition, Phase, Session
from backend.workflow.engine import WorkflowRunner
from backend.workflow.types import (
    DiffSet,
    SubTask,
    TaskList,
    WorkflowState,
)


# ─── Fixtures ───


@pytest.fixture
def session() -> Session:
    return Session(id="test-ctx", work_dir=Path("/tmp/test"), phase=Phase.INIT)


@pytest.fixture
def agent_def() -> AgentDefinition:
    return AgentDefinition(
        agent_id="test",
        name="测试助手",
        role="assistant",
        tools=["read_file"],
    )


@pytest.fixture
def session_with_plan(session: Session) -> Session:
    """带完整 TaskList 的 session（模拟 planner 已产出）。"""
    session.workflow_state = WorkflowState(
        task_list=TaskList(
            overview="实现用户认证模块",
            risks=["需注意密码加密强度"],
            tasks=[
                SubTask(id="task-1", title="创建 User 模型", description="实现 User dataclass"),
                SubTask(id="task-2", title="实现登录接口", description="POST /api/login"),
                SubTask(id="task-3", title="编写测试", description="单元测试 + 集成测试"),
            ],
        )
    )
    return session


# ─── _repo_map_block 测试 ───


class TestRepoMapBlock:
    """repo_map 注入段落测试。"""

    def test_empty_repo_map_returns_empty(self, session):
        session.repo_map = None
        assert _repo_map_block(session) == ""

    def test_empty_string_returns_empty(self, session):
        session.repo_map = ""
        assert _repo_map_block(session) == ""

    def test_non_empty_returns_block(self, session):
        session.repo_map = "backend/\n  engine.py: class WorkflowRunner"
        block = _repo_map_block(session)
        assert "项目结构地图" in block
        assert "backend/" in block
        assert "class WorkflowRunner" in block


# ─── _completed_tasks_block 测试 ───


class TestCompletedTasksBlock:
    """已完成任务摘要测试。"""

    def test_no_workflow_state_returns_empty(self, session):
        session.workflow_state = None
        assert _completed_tasks_block(session) == ""

    def test_no_completed_tasks_returns_empty(self, session_with_plan):
        assert _completed_tasks_block(session_with_plan) == ""

    def test_with_completed_tasks(self, session_with_plan):
        ws = session_with_plan.workflow_state
        ws.completed_tasks = ["task-1", "task-2"]
        block = _completed_tasks_block(session_with_plan)
        assert "已完成的子任务" in block
        assert "2/3" in block
        assert "创建 User 模型" in block
        assert "实现登录接口" in block

    def test_completed_task_id_not_in_list(self, session_with_plan):
        ws = session_with_plan.workflow_state
        ws.completed_tasks = ["unknown-id"]
        block = _completed_tasks_block(session_with_plan)
        assert "unknown-id" in block


# ─── _plan_overview_block 测试 ───


class TestPlanOverviewBlock:
    """planner 方案概述注入测试。"""

    def test_no_workflow_state_returns_empty(self, session):
        session.workflow_state = None
        assert _plan_overview_block(session) == ""

    def test_no_overview_returns_empty(self, session):
        session.workflow_state = WorkflowState(
            task_list=TaskList(tasks=[SubTask(id="t1", title="T1", description="D")])
        )
        assert _plan_overview_block(session) == ""

    def test_with_overview_only(self, session):
        session.workflow_state = WorkflowState(
            task_list=TaskList(overview="重构认证模块", tasks=[])
        )
        block = _plan_overview_block(session)
        assert "全局上下文" in block
        assert "重构认证模块" in block

    def test_with_overview_and_risks(self, session):
        session.workflow_state = WorkflowState(
            task_list=TaskList(
                overview="实现用户认证",
                risks=["密码加密强度", "SQL 注入风险"],
                tasks=[],
            )
        )
        block = _plan_overview_block(session)
        assert "全局上下文" in block
        assert "实现用户认证" in block
        assert "密码加密强度" in block
        assert "SQL 注入风险" in block


# ─── build_phase_prompt + repo_map 集成测试 ───


class TestPhasePromptWithRepoMap:
    """build_phase_prompt 注入 repo_map 测试。"""

    def test_planning_with_repo_map(self, session, agent_def):
        session.repo_map = "src/\n  main.py: hello()"
        prompt = build_phase_prompt(session, agent_def, Phase.PLANNING)
        assert "项目结构地图" in prompt
        assert "src/" in prompt
        assert "当前阶段：需求分析与任务规划" in prompt

    def test_coding_with_repo_map(self, session_with_plan, agent_def):
        session_with_plan.repo_map = "backend/\n  cli.py: main()"
        prompt = build_phase_prompt(session_with_plan, agent_def, Phase.CODING)
        assert "项目结构地图" in prompt
        assert "backend/" in prompt

    def test_reviewing_with_repo_map(self, session_with_plan, agent_def):
        session_with_plan.repo_map = "tests/\n  test_foo.py: TestFoo"
        ws = session_with_plan.workflow_state
        ws.current_diff_set = DiffSet(task_id="task-1", summary="改了点东西")
        prompt = build_phase_prompt(session_with_plan, agent_def, Phase.REVIEWING)
        assert "项目结构地图" in prompt

    def test_no_repo_map_doesnt_inject(self, session, agent_def):
        session.repo_map = None
        prompt = build_phase_prompt(session, agent_def, Phase.PLANNING)
        assert "项目结构地图" not in prompt


# ─── 阶段间上下文传递测试 ───


class TestCrossPhaseContextCoding:
    """CODING 阶段注入 planner 上下文测试。"""

    def test_coding_injects_plan_overview(self, session_with_plan, agent_def):
        prompt = build_phase_prompt(session_with_plan, agent_def, Phase.CODING)
        assert "全局上下文" in prompt
        assert "实现用户认证模块" in prompt
        assert "需注意密码加密强度" in prompt

    def test_coding_injects_completed_tasks(self, session_with_plan, agent_def):
        ws = session_with_plan.workflow_state
        ws.completed_tasks = ["task-1"]
        prompt = build_phase_prompt(session_with_plan, agent_def, Phase.CODING)
        assert "已完成的子任务" in prompt
        assert "创建 User 模型" in prompt
        assert "1/3" in prompt

    def test_coding_no_completed_tasks_no_block(self, session_with_plan, agent_def):
        prompt = build_phase_prompt(session_with_plan, agent_def, Phase.CODING)
        assert "已完成的子任务" not in prompt

    def test_coding_no_overview_no_plan_block(self, session, agent_def):
        session.workflow_state = WorkflowState(
            task_list=TaskList(tasks=[SubTask(id="t1", title="T1", description="D")])
        )
        prompt = build_phase_prompt(session, agent_def, Phase.CODING)
        assert "全局上下文" not in prompt


class TestCrossPhaseContextReviewing:
    """REVIEWING 阶段注入任务上下文测试。"""

    def test_reviewing_injects_task_context(self, session_with_plan, agent_def):
        ws = session_with_plan.workflow_state
        ws.current_diff_set = DiffSet(task_id="task-1", summary="变更")
        prompt = build_phase_prompt(session_with_plan, agent_def, Phase.REVIEWING)
        assert "当前审查的任务" in prompt
        assert "创建 User 模型" in prompt

    def test_reviewing_injects_plan_overview(self, session_with_plan, agent_def):
        ws = session_with_plan.workflow_state
        ws.current_diff_set = DiffSet(task_id="task-1", summary="变更")
        prompt = build_phase_prompt(session_with_plan, agent_def, Phase.REVIEWING)
        assert "全局上下文" in prompt
        assert "实现用户认证模块" in prompt

    def test_reviewing_injects_completed_tasks(self, session_with_plan, agent_def):
        ws = session_with_plan.workflow_state
        ws.current_diff_set = DiffSet(task_id="task-2", summary="变更")
        ws.completed_tasks = ["task-1"]
        prompt = build_phase_prompt(session_with_plan, agent_def, Phase.REVIEWING)
        assert "已完成的子任务" in prompt

    def test_reviewing_no_task_list_no_context(self, session, agent_def):
        session.workflow_state = WorkflowState(
            current_diff_set=DiffSet(task_id="t1", summary="变更")
        )
        prompt = build_phase_prompt(session, agent_def, Phase.REVIEWING)
        assert "当前审查的任务" not in prompt
        assert "全局上下文" not in prompt


class TestCrossPhaseContextFeedback:
    """FEEDBACK 阶段注入已完成任务上下文测试。"""

    def test_feedback_injects_completed_tasks(self, session_with_plan, agent_def):
        from backend.workflow.types import ReviewReport

        ws = session_with_plan.workflow_state
        ws.last_review_report = ReviewReport(summary="需修改")
        ws.completed_tasks = ["task-1"]
        prompt = build_phase_prompt(session_with_plan, agent_def, Phase.FEEDBACK)
        assert "已完成的子任务" in prompt
        assert "创建 User 模型" in prompt

    def test_feedback_no_completed_no_block(self, session_with_plan, agent_def):
        from backend.workflow.types import ReviewReport

        ws = session_with_plan.workflow_state
        ws.last_review_report = ReviewReport(summary="需修改")
        prompt = build_phase_prompt(session_with_plan, agent_def, Phase.FEEDBACK)
        assert "已完成的子任务" not in prompt


# ─── _build_coder_message 上下文传递测试 ───


class TestCoderMessageContext:
    """_build_coder_message 阶段间上下文传递测试。"""

    @staticmethod
    def _make_runner():
        """创建一个不依赖 orchestrator 的 runner 实例。"""
        return WorkflowRunner.__new__(WorkflowRunner)

    def test_coder_message_includes_overview(self):
        runner = self._make_runner()
        session = Session(id="s1", work_dir=Path("/tmp"))
        session.workflow_state = WorkflowState(
            task_list=TaskList(
                overview="重构数据层",
                tasks=[SubTask(id="t1", title="T1", description="D1")],
            )
        )
        task = SubTask(id="t1", title="T1", description="D1")
        msg = runner._build_coder_message(task, session)
        assert "方案概述" in msg
        assert "重构数据层" in msg

    def test_coder_message_includes_completed_tasks(self):
        runner = self._make_runner()
        session = Session(id="s1", work_dir=Path("/tmp"))
        session.workflow_state = WorkflowState(
            task_list=TaskList(
                tasks=[
                    SubTask(id="t1", title="创建模型", description="D1"),
                    SubTask(id="t2", title="实现接口", description="D2"),
                ]
            ),
            completed_tasks=["t1"],
        )
        task = SubTask(id="t2", title="实现接口", description="D2")
        msg = runner._build_coder_message(task, session)
        assert "已完成任务" in msg
        assert "创建模型" in msg

    def test_coder_message_no_overview_omits_block(self):
        runner = self._make_runner()
        session = Session(id="s1", work_dir=Path("/tmp"))
        session.workflow_state = WorkflowState(
            task_list=TaskList(tasks=[SubTask(id="t1", title="T1", description="D1")])
        )
        task = SubTask(id="t1", title="T1", description="D1")
        msg = runner._build_coder_message(task, session)
        assert "方案概述" not in msg

    def test_coder_message_no_workflow_state(self):
        runner = self._make_runner()
        session = Session(id="s1", work_dir=Path("/tmp"))
        task = SubTask(id="t1", title="T1", description="D1")
        msg = runner._build_coder_message(task, session)
        assert "T1" in msg
        assert "方案概述" not in msg
        assert "已完成任务" not in msg


# ─── _build_reviewer_message 上下文传递测试 ───


class TestReviewerMessageContext:
    """_build_reviewer_message 阶段间上下文传递测试。"""

    @staticmethod
    def _make_runner():
        return WorkflowRunner.__new__(WorkflowRunner)

    def test_reviewer_message_includes_task_context(self):
        runner = self._make_runner()
        session = Session(id="s1", work_dir=Path("/tmp"))
        session.workflow_state = WorkflowState(
            task_list=TaskList(
                tasks=[SubTask(
                    id="t1", title="实现登录",
                    description="POST /login",
                    acceptance_criteria="返回 JWT",
                )],
            ),
            current_diff_set=DiffSet(task_id="t1", summary="变更"),
        )
        diff = session.workflow_state.current_diff_set
        msg = runner._build_reviewer_message(diff, session)
        assert "审查目标任务" in msg
        assert "实现登录" in msg
        assert "返回 JWT" in msg

    def test_reviewer_message_includes_completed_count(self):
        runner = self._make_runner()
        session = Session(id="s1", work_dir=Path("/tmp"))
        session.workflow_state = WorkflowState(
            task_list=TaskList(
                tasks=[SubTask(id="t1", title="T1", description="D1")],
            ),
            completed_tasks=["t1"],
            current_diff_set=DiffSet(task_id="t2", summary="变更"),
        )
        diff = session.workflow_state.current_diff_set
        msg = runner._build_reviewer_message(diff, session)
        assert "前序已完成" in msg
        assert "1" in msg

    def test_reviewer_message_no_session_omits_context(self):
        runner = self._make_runner()
        diff = DiffSet(task_id="t1", summary="变更")
        msg = runner._build_reviewer_message(diff)
        assert "审查目标任务" not in msg
        assert "前序已完成" not in msg

    def test_reviewer_message_no_workflow_state(self):
        runner = self._make_runner()
        session = Session(id="s1", work_dir=Path("/tmp"))
        diff = DiffSet(task_id="t1", summary="变更")
        msg = runner._build_reviewer_message(diff, session)
        assert "审查目标任务" not in msg
