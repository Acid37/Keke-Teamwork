"""工作流引擎数据类型单元测试。

覆盖：
- SubTask / TaskList 的序列化/反序列化、状态推进
- DiffSet 的 from_commit_result 构造
- ReviewReport 的判定属性
- WorkflowState 的完整序列化/反序列化往返
- PhaseGuard 守卫条件
- SessionStore 持久化 workflow_state 往返
- Phase enum 新增成员
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from backend.types import Phase, Session, FileDiff, CommitResult, TokenUsage
from backend.session import SessionStore
from backend.workflow.types import (
    SubTask,
    TaskList,
    DiffSet,
    FileReview,
    ReviewReport,
    WorkflowState,
    PhaseGuard,
    TASK_PENDING,
    TASK_IN_PROGRESS,
    TASK_DONE,
    VERDICT_APPROVED,
    VERDICT_NEEDS_CHANGES,
    VERDICT_REJECTED,
    SEVERITY_BLOCKER,
    SEVERITY_WARNING,
    SEVERITY_INFO,
)


# ─── SubTask ───


class TestSubTask:
    def test_creation_defaults(self):
        t = SubTask(id="task-1", title="创建模型", description="创建 User 模型")
        assert t.status == TASK_PENDING
        assert t.priority == 0
        assert t.files_involved == []
        assert t.acceptance_criteria == ""

    def test_to_dict_roundtrip(self):
        t = SubTask(
            id="task-1",
            title="创建模型",
            description="创建 User 模型",
            files_involved=["models/user.py", "models/__init__.py"],
            acceptance_criteria="User 类可实例化",
            priority=1,
            status=TASK_IN_PROGRESS,
        )
        d = t.to_dict()
        assert d["id"] == "task-1"
        assert d["files_involved"] == ["models/user.py", "models/__init__.py"]

        t2 = SubTask.from_dict(d)
        assert t2.id == t.id
        assert t2.title == t.title
        assert t2.files_involved == t.files_involved
        assert t2.status == t.status

    def test_from_dict_ignores_unknown_keys(self):
        t = SubTask.from_dict({
            "id": "task-1",
            "title": "test",
            "description": "desc",
            "unknown_field": "ignored",
        })
        assert t.id == "task-1"
        assert not hasattr(t, "unknown_field")


# ─── TaskList ───


class TestTaskList:
    def _make_task_list(self, n: int = 3) -> TaskList:
        tasks = [
            SubTask(id=f"task-{i}", title=f"任务 {i}", description=f"描述 {i}")
            for i in range(1, n + 1)
        ]
        return TaskList(
            overview="方案概述",
            tasks=tasks,
            risks=["风险1"],
            estimated_effort="2h",
        )

    def test_current_task(self):
        tl = self._make_task_list(3)
        assert tl.current_task is not None
        assert tl.current_task.id == "task-1"

    def test_current_task_none_when_exhausted(self):
        tl = self._make_task_list(2)
        tl.current_task_index = 2
        assert tl.current_task is None

    def test_advance(self):
        tl = self._make_task_list(3)
        # 标记当前为进行中
        tl.current_task.status = TASK_IN_PROGRESS
        next_task = tl.advance()
        assert next_task is not None
        assert next_task.id == "task-2"
        # 前一个应标记为完成
        assert tl.tasks[0].status == TASK_DONE

    def test_advance_to_exhaustion(self):
        tl = self._make_task_list(1)
        tl.current_task.status = TASK_IN_PROGRESS
        result = tl.advance()
        assert result is None
        assert tl.tasks[0].status == TASK_DONE

    def test_completed_count(self):
        tl = self._make_task_list(3)
        tl.tasks[0].status = TASK_DONE
        tl.tasks[1].status = TASK_DONE
        assert tl.completed_count == 2
        assert tl.total_count == 3

    def test_to_dict_roundtrip(self):
        tl = self._make_task_list(2)
        d = tl.to_dict()
        assert d["overview"] == "方案概述"
        assert len(d["tasks"]) == 2

        tl2 = TaskList.from_dict(d)
        assert tl2.overview == tl.overview
        assert len(tl2.tasks) == 2
        assert tl2.tasks[0].id == "task-1"
        assert tl2.current_task_index == 0


# ─── DiffSet ───


class TestDiffSet:
    def test_from_commit_result(self):
        commit = CommitResult(
            files_changed=2,
            diffs=[
                FileDiff(
                    path=Path("src/main.py"),
                    action="modify",
                    diff_text="--- a\n+++ b\n",
                    new_content="print('hello')",
                ),
                FileDiff(
                    path=Path("src/utils.py"),
                    action="create",
                    diff_text="--- /dev/null\n+++ b\n",
                ),
            ],
            combined_diff="full diff text",
            summary="新增 utils.py，修改 main.py",
        )

        ds = DiffSet.from_commit_result("task-1", commit)
        assert ds.task_id == "task-1"
        assert ds.files_changed == 2
        assert len(ds.diffs) == 2
        assert ds.diffs[0]["path"] == "src\\main.py" or ds.diffs[0]["path"] == "src/main.py"
        assert ds.combined_diff == "full diff text"
        assert ds.summary == "新增 utils.py，修改 main.py"

    def test_to_dict_roundtrip(self):
        ds = DiffSet(
            task_id="task-2",
            files_changed=1,
            diffs=[{"path": "test.py", "action": "create", "diff_text": "...", "new_content": None}],
            combined_diff="diff",
            summary="summary",
            test_results="3 passed",
        )
        d = ds.to_dict()
        ds2 = DiffSet.from_dict(d)
        assert ds2.task_id == "task-2"
        assert ds2.test_results == "3 passed"


# ─── ReviewReport ───


class TestReviewReport:
    def test_is_approved(self):
        r = ReviewReport(overall_verdict=VERDICT_APPROVED)
        assert r.is_approved is True

    def test_is_not_approved(self):
        r = ReviewReport(overall_verdict=VERDICT_NEEDS_CHANGES)
        assert r.is_approved is False

    def test_has_blockers(self):
        r = ReviewReport(
            file_reviews=[
                FileReview(file_path="a.py", issues=["bug"], severity=SEVERITY_BLOCKER),
                FileReview(file_path="b.py", issues=["style"], severity=SEVERITY_WARNING),
            ],
        )
        assert r.has_blockers is True

    def test_no_blockers(self):
        r = ReviewReport(
            file_reviews=[
                FileReview(file_path="a.py", issues=["style"], severity=SEVERITY_WARNING),
            ],
        )
        assert r.has_blockers is False

    def test_to_dict_roundtrip(self):
        r = ReviewReport(
            task_id="task-1",
            overall_verdict=VERDICT_NEEDS_CHANGES,
            file_reviews=[
                FileReview(file_path="a.py", issues=["bug1"], suggestions=["fix1"], severity=SEVERITY_BLOCKER),
            ],
            summary="需要修改",
            should_retry=True,
        )
        d = r.to_dict()
        r2 = ReviewReport.from_dict(d)
        assert r2.task_id == "task-1"
        assert r2.overall_verdict == VERDICT_NEEDS_CHANGES
        assert len(r2.file_reviews) == 1
        assert r2.file_reviews[0].severity == SEVERITY_BLOCKER
        assert r2.should_retry is True


# ─── WorkflowState ───


class TestWorkflowState:
    def test_empty_state_to_dict(self):
        ws = WorkflowState()
        d = ws.to_dict()
        assert d["task_list"] is None
        assert d["current_diff_set"] is None
        assert d["last_review_report"] is None
        assert d["plan_approved"] is False

    def test_from_dict_none(self):
        assert WorkflowState.from_dict(None) is None
        assert WorkflowState.from_dict({}) is None

    def test_full_roundtrip(self):
        ws = WorkflowState(
            task_list=TaskList(
                overview="计划",
                tasks=[SubTask(id="task-1", title="T1", description="D1")],
                risks=["风险"],
                estimated_effort="1h",
            ),
            current_diff_set=DiffSet(
                task_id="task-1",
                files_changed=1,
                combined_diff="diff",
                summary="摘要",
            ),
            last_review_report=ReviewReport(
                task_id="task-1",
                overall_verdict=VERDICT_APPROVED,
                summary="通过",
            ),
            plan_approved=True,
            completed_tasks=["task-1"],
        )
        d = ws.to_dict()
        ws2 = WorkflowState.from_dict(d)

        assert ws2 is not None
        assert ws2.task_list is not None
        assert ws2.task_list.overview == "计划"
        assert len(ws2.task_list.tasks) == 1
        assert ws2.task_list.tasks[0].id == "task-1"
        assert ws2.current_diff_set is not None
        assert ws2.current_diff_set.task_id == "task-1"
        assert ws2.last_review_report is not None
        assert ws2.last_review_report.is_approved
        assert ws2.plan_approved is True
        assert ws2.completed_tasks == ["task-1"]

    def test_current_task_property(self):
        ws = WorkflowState(
            task_list=TaskList(
                tasks=[SubTask(id="t1", title="T1", description="D1")],
            ),
        )
        assert ws.current_task is not None
        assert ws.current_task.id == "t1"

    def test_current_task_none_when_no_task_list(self):
        ws = WorkflowState()
        assert ws.current_task is None


# ─── PhaseGuard ───


class TestPhaseGuard:
    def _make_session(self, phase: Phase, workflow_state: WorkflowState | None = None) -> Session:
        return Session(
            id="test-session",
            work_dir=Path("/tmp/test"),
            phase=phase,
            workflow_state=workflow_state,
        )

    def test_can_enter_planning_from_init(self):
        s = self._make_session(Phase.INIT)
        assert PhaseGuard.can_enter_planning(s) is True

    def test_can_enter_planning_from_error(self):
        s = self._make_session(Phase.ERROR)
        assert PhaseGuard.can_enter_planning(s) is True

    def test_can_enter_planning_from_completed(self):
        s = self._make_session(Phase.COMPLETED)
        assert PhaseGuard.can_enter_planning(s) is True

    def test_cannot_enter_planning_from_coding(self):
        s = self._make_session(Phase.CODING)
        assert PhaseGuard.can_enter_planning(s) is False

    def test_can_enter_plan_review(self):
        ws = WorkflowState(task_list=TaskList(tasks=[SubTask(id="t1", title="T", description="D")]))
        s = self._make_session(Phase.PLANNING, ws)
        assert PhaseGuard.can_enter_plan_review(s) is True

    def test_cannot_enter_plan_review_without_task_list(self):
        ws = WorkflowState()
        s = self._make_session(Phase.PLANNING, ws)
        assert PhaseGuard.can_enter_plan_review(s) is False

    def test_can_enter_coding(self):
        ws = WorkflowState(
            task_list=TaskList(tasks=[SubTask(id="t1", title="T", description="D")]),
            plan_approved=True,
        )
        s = self._make_session(Phase.PLAN_REVIEW, ws)
        assert PhaseGuard.can_enter_coding(s) is True

    def test_cannot_enter_coding_without_approval(self):
        ws = WorkflowState(
            task_list=TaskList(tasks=[SubTask(id="t1", title="T", description="D")]),
            plan_approved=False,
        )
        s = self._make_session(Phase.PLAN_REVIEW, ws)
        assert PhaseGuard.can_enter_coding(s) is False

    def test_can_enter_reviewing(self):
        ws = WorkflowState(
            task_list=TaskList(tasks=[SubTask(id="t1", title="T", description="D")]),
            current_diff_set=DiffSet(task_id="t1"),
        )
        s = self._make_session(Phase.CODE_REVIEW, ws)
        assert PhaseGuard.can_enter_reviewing(s) is True

    def test_cannot_enter_reviewing_without_diff(self):
        ws = WorkflowState()
        s = self._make_session(Phase.CODE_REVIEW, ws)
        assert PhaseGuard.can_enter_reviewing(s) is False

    def test_can_enter_feedback(self):
        ws = WorkflowState(
            last_review_report=ReviewReport(should_retry=True),
        )
        s = self._make_session(Phase.REVIEWING, ws)
        assert PhaseGuard.can_enter_feedback(s) is True

    def test_cannot_enter_feedback_without_retry(self):
        ws = WorkflowState(
            last_review_report=ReviewReport(should_retry=False),
        )
        s = self._make_session(Phase.REVIEWING, ws)
        assert PhaseGuard.can_enter_feedback(s) is False

    def test_can_enter_completed(self):
        ws = WorkflowState(
            task_list=TaskList(
                tasks=[SubTask(id="t1", title="T", description="D")],
                current_task_index=1,  # 越界 → current_task is None
            ),
        )
        s = self._make_session(Phase.REVIEWING, ws)
        assert PhaseGuard.can_enter_completed(s) is True

    def test_cannot_enter_completed_with_remaining_tasks(self):
        ws = WorkflowState(
            task_list=TaskList(
                tasks=[SubTask(id="t1", title="T", description="D")],
                current_task_index=0,  # 还有任务
            ),
        )
        s = self._make_session(Phase.REVIEWING, ws)
        assert PhaseGuard.can_enter_completed(s) is False


# ─── Phase enum ───


class TestPhaseEnum:
    def test_new_phases_exist(self):
        assert Phase.PLANNING == "planning"
        assert Phase.PLAN_REVIEW == "plan_review"
        assert Phase.CODE_REVIEW == "code_review"
        assert Phase.REVIEWING == "reviewing"
        assert Phase.FEEDBACK == "feedback"
        assert Phase.COMPLETED == "completed"

    def test_existing_phases_preserved(self):
        assert Phase.INIT == "init"
        assert Phase.RESEARCHING == "researching"
        assert Phase.THINKING == "thinking"
        assert Phase.CODING == "coding"
        assert Phase.READY == "ready"
        assert Phase.ERROR == "error"

    def test_phase_from_string(self):
        assert Phase("planning") == Phase.PLANNING
        assert Phase("plan_review") == Phase.PLAN_REVIEW
        assert Phase("completed") == Phase.COMPLETED
        # 向后兼容
        assert Phase("init") == Phase.INIT
        assert Phase("ready") == Phase.READY


# ─── SessionStore 持久化 workflow_state ───


class TestSessionStoreWorkflowState:
    def test_save_load_with_workflow_state(self):
        with TemporaryDirectory() as tmpdir:
            store = SessionStore(Path(tmpdir))
            ws = WorkflowState(
                task_list=TaskList(
                    overview="方案",
                    tasks=[
                        SubTask(id="task-1", title="T1", description="D1"),
                        SubTask(id="task-2", title="T2", description="D2"),
                    ],
                    risks=["风险"],
                    estimated_effort="2h",
                ),
                plan_approved=True,
                completed_tasks=["task-1"],
            )
            session = Session(
                id="test-wf",
                work_dir=Path(tmpdir),
                phase=Phase.CODING,
                workflow_state=ws,
            )
            store.save(session)

            loaded = store.load("test-wf")
            assert loaded is not None
            assert loaded.phase == Phase.CODING
            assert loaded.workflow_state is not None
            assert loaded.workflow_state.task_list is not None
            assert loaded.workflow_state.task_list.overview == "方案"
            assert len(loaded.workflow_state.task_list.tasks) == 2
            assert loaded.workflow_state.task_list.tasks[0].id == "task-1"
            assert loaded.workflow_state.plan_approved is True
            assert loaded.workflow_state.completed_tasks == ["task-1"]

    def test_save_load_without_workflow_state(self):
        with TemporaryDirectory() as tmpdir:
            store = SessionStore(Path(tmpdir))
            session = Session(
                id="test-no-wf",
                work_dir=Path(tmpdir),
                phase=Phase.INIT,
                workflow_state=None,
            )
            store.save(session)

            loaded = store.load("test-no-wf")
            assert loaded is not None
            assert loaded.workflow_state is None

    def test_save_load_with_full_workflow_state(self):
        """测试包含所有字段的完整往返。"""
        with TemporaryDirectory() as tmpdir:
            store = SessionStore(Path(tmpdir))
            ws = WorkflowState(
                task_list=TaskList(
                    overview="完整方案",
                    tasks=[
                        SubTask(
                            id="task-1",
                            title="创建模型",
                            description="创建 User 模型",
                            files_involved=["models/user.py"],
                            acceptance_criteria="可实例化",
                            priority=1,
                            status=TASK_DONE,
                        ),
                        SubTask(
                            id="task-2",
                            title="实现 API",
                            description="实现登录接口",
                            files_involved=["api/auth.py"],
                            acceptance_criteria="返回 token",
                            priority=2,
                            status=TASK_IN_PROGRESS,
                        ),
                    ],
                    risks=["数据库迁移风险"],
                    estimated_effort="4h",
                    current_task_index=1,
                ),
                current_diff_set=DiffSet(
                    task_id="task-2",
                    files_changed=2,
                    diffs=[{"path": "api/auth.py", "action": "create", "diff_text": "...", "new_content": None}],
                    combined_diff="full diff",
                    summary="实现登录接口",
                    test_results="5 passed",
                ),
                last_review_report=ReviewReport(
                    task_id="task-1",
                    overall_verdict=VERDICT_NEEDS_CHANGES,
                    file_reviews=[
                        FileReview(
                            file_path="models/user.py",
                            issues=["缺少索引"],
                            suggestions=["添加 db_index"],
                            severity=SEVERITY_WARNING,
                        ),
                    ],
                    summary="需要添加索引",
                    should_retry=True,
                ),
                plan_approved=True,
                completed_tasks=["task-1"],
                user_command_queue=[{"type": "workflow.skip_review"}],
            )
            session = Session(
                id="test-full-wf",
                work_dir=Path(tmpdir),
                phase=Phase.FEEDBACK,
                workflow_state=ws,
            )
            store.save(session)

            loaded = store.load("test-full-wf")
            assert loaded is not None
            assert loaded.phase == Phase.FEEDBACK
            assert loaded.workflow_state is not None

            # TaskList
            tl = loaded.workflow_state.task_list
            assert tl.overview == "完整方案"
            assert tl.current_task_index == 1
            assert len(tl.tasks) == 2
            assert tl.tasks[0].status == TASK_DONE
            assert tl.tasks[1].status == TASK_IN_PROGRESS
            assert tl.tasks[0].files_involved == ["models/user.py"]

            # DiffSet
            ds = loaded.workflow_state.current_diff_set
            assert ds is not None
            assert ds.task_id == "task-2"
            assert ds.files_changed == 2
            assert ds.test_results == "5 passed"

            # ReviewReport
            rr = loaded.workflow_state.last_review_report
            assert rr is not None
            assert rr.overall_verdict == VERDICT_NEEDS_CHANGES
            assert rr.should_retry is True
            assert len(rr.file_reviews) == 1
            assert rr.file_reviews[0].severity == SEVERITY_WARNING

            # 其他字段
            assert loaded.workflow_state.plan_approved is True
            assert loaded.workflow_state.completed_tasks == ["task-1"]
            assert loaded.workflow_state.user_command_queue == [{"type": "workflow.skip_review"}]

    def test_load_old_session_without_workflow_state_field(self):
        """加载不含 workflow_state 字段的旧 session JSON。"""
        with TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            sessions_dir.mkdir()
            old_data = {
                "id": "old-session",
                "work_dir": tmpdir,
                "phase": "init",
                "messages": [],
                "yolo_mode": False,
                "auto_review": True,
                "solo_mode": False,
                "usage_total": {"input_tokens": 0, "output_tokens": 0},
                "title": "Old",
                "created_at": 0,
                "last_active_at": 0,
                "events": [],
                # 注意：没有 "workflow_state" 字段
            }
            (sessions_dir / "old-session.json").write_text(
                json.dumps(old_data), encoding="utf-8"
            )

            store = SessionStore(Path(tmpdir))
            loaded = store.load("old-session")
            assert loaded is not None
            assert loaded.workflow_state is None
            assert loaded.phase == Phase.INIT
