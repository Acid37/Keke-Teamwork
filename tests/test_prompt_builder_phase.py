"""build_phase_prompt 单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.prompt_builder import build_phase_prompt
from backend.types import AgentDefinition, Phase, Session
from backend.workflow.types import (
    DiffSet,
    FileReview,
    ReviewReport,
    SubTask,
    TaskList,
    WorkflowState,
    SEVERITY_BLOCKER,
    SEVERITY_WARNING,
)


@pytest.fixture
def session() -> Session:
    return Session(id="test-session", work_dir=Path("/tmp/test"), phase=Phase.INIT)


@pytest.fixture
def agent_def() -> AgentDefinition:
    return AgentDefinition(
        agent_id="test",
        name="测试助手",
        role="assistant",
        tools=["read_file"],
    )


class TestBuildPhasePromptBase:
    """非工作流阶段返回基础提示词。"""

    def test_init_phase_returns_base(self, session, agent_def):
        prompt = build_phase_prompt(session, agent_def, Phase.INIT)
        assert "你是一个乐于助人的编程助手" in prompt
        assert "当前阶段" not in prompt

    def test_plan_review_returns_base(self, session, agent_def):
        prompt = build_phase_prompt(session, agent_def, Phase.PLAN_REVIEW)
        assert "当前阶段" not in prompt

    def test_code_review_returns_base(self, session, agent_def):
        prompt = build_phase_prompt(session, agent_def, Phase.CODE_REVIEW)
        assert "当前阶段" not in prompt

    def test_completed_returns_base(self, session, agent_def):
        prompt = build_phase_prompt(session, agent_def, Phase.COMPLETED)
        assert "当前阶段" not in prompt

    def test_error_returns_base(self, session, agent_def):
        prompt = build_phase_prompt(session, agent_def, Phase.ERROR)
        assert "当前阶段" not in prompt


class TestBuildPhasePromptPlanning:
    """PLANNING 阶段注入规划引导。"""

    def test_planning_adds_guidance(self, session, agent_def):
        prompt = build_phase_prompt(session, agent_def, Phase.PLANNING)
        assert "当前阶段：需求分析与任务规划" in prompt
        assert "子任务计划" in prompt


class TestBuildPhasePromptCoding:
    """CODING 阶段注入子任务详情。"""

    def test_coding_injects_task_details(self, session, agent_def):
        session.workflow_state = WorkflowState(
            task_list=TaskList(
                tasks=[
                    SubTask(
                        id="task-1",
                        title="创建用户模型",
                        description="实现 User 数据类",
                        files_involved=["models.py"],
                        acceptance_criteria="通过单元测试",
                    )
                ]
            )
        )
        prompt = build_phase_prompt(session, agent_def, Phase.CODING)
        assert "当前阶段：编码实现" in prompt
        assert "创建用户模型" in prompt
        assert "models.py" in prompt
        assert "通过单元测试" in prompt

    def test_coding_missing_task_returns_base(self, session, agent_def):
        session.workflow_state = WorkflowState(task_list=TaskList(tasks=[]))
        prompt = build_phase_prompt(session, agent_def, Phase.CODING)
        assert "当前阶段" not in prompt

    def test_coding_injects_feedback(self, session, agent_def):
        session.workflow_state = WorkflowState(
            task_list=TaskList(tasks=[SubTask(id="task-1", title="T1", description="D1")]),
        )
        session.coder_guidance_queue.append("缺少边界检查")
        prompt = build_phase_prompt(session, agent_def, Phase.CODING)
        assert "审查反馈" in prompt
        assert "缺少边界检查" in prompt


class TestBuildPhasePromptReviewing:
    """REVIEWING 阶段注入 diff。"""

    def test_reviewing_injects_diff(self, session, agent_def):
        session.workflow_state = WorkflowState(
            current_diff_set=DiffSet(
                task_id="task-1",
                files_changed=2,
                combined_diff="+def hello():\n+    pass\n",
                summary="添加 hello 函数",
                test_results="1 passed",
            )
        )
        prompt = build_phase_prompt(session, agent_def, Phase.REVIEWING)
        assert "当前阶段：代码审查" in prompt
        assert "添加 hello 函数" in prompt
        assert "+def hello():" in prompt
        assert "1 passed" in prompt

    def test_reviewing_missing_diff_returns_base(self, session, agent_def):
        session.workflow_state = WorkflowState()
        prompt = build_phase_prompt(session, agent_def, Phase.REVIEWING)
        assert "当前阶段" not in prompt


class TestBuildPhasePromptFeedback:
    """FEEDBACK 阶段注入审查反馈。"""

    def test_feedback_injects_report(self, session, agent_def):
        session.workflow_state = WorkflowState(
            last_review_report=ReviewReport(
                summary="需要修改",
                file_reviews=[
                    FileReview(
                        file_path="a.py",
                        issues=["缺少类型注解"],
                        suggestions=["添加类型提示"],
                        severity=SEVERITY_BLOCKER,
                    ),
                    FileReview(
                        file_path="b.py",
                        issues=["命名不规范"],
                        severity=SEVERITY_WARNING,
                    ),
                ],
            )
        )
        prompt = build_phase_prompt(session, agent_def, Phase.FEEDBACK)
        assert "当前阶段：根据审查反馈修改代码" in prompt
        assert "需要修改" in prompt
        assert "a.py" in prompt
        assert "缺少类型注解" in prompt
        assert "添加类型提示" in prompt
        assert "b.py" in prompt

    def test_feedback_missing_report_returns_base(self, session, agent_def):
        session.workflow_state = WorkflowState()
        prompt = build_phase_prompt(session, agent_def, Phase.FEEDBACK)
        assert "当前阶段" not in prompt

    def test_feedback_no_workflow_state_returns_base(self, session, agent_def):
        session.workflow_state = None
        prompt = build_phase_prompt(session, agent_def, Phase.FEEDBACK)
        assert "当前阶段" not in prompt
