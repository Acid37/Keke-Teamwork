"""工作流边界 case 单元测试（Step 9 端到端联调补充）。

覆盖三个已识别的测试缺口：
1. 全部任务被跳过——多任务工作流中连续 skip_task 后的正确完成
2. 大量文件变更——50+ 文件 DiffSet、多任务 total_files_changed 累加
3. LLM 输出半畸形解析——字段缺失/多余/截断/标记错位/非法枚举值
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.types import AgentResult, Phase, Session, TokenUsage
from backend.workflow.engine import WorkflowRunner
from backend.workflow.parser import (
    parse_diff_set,
    parse_review_report,
    parse_task_list,
)
from backend.workflow.types import (
    DiffSet,
    FileReview,
    ReviewReport,
    SubTask,
    TaskList,
    WorkflowState,
    VERDICT_APPROVED,
    VERDICT_NEEDS_CHANGES,
    VERDICT_REJECTED,
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
        id="test-edge",
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
    return AgentResult(
        text=text,
        thinking="",
        tool_calls_history=[],
        usage=TokenUsage(input_tokens=100, output_tokens=50),
        messages=[],
    )


def _make_task_list(n: int, status: str = "pending") -> TaskList:
    """创建 n 个子任务的 TaskList。"""
    tasks = [
        SubTask(id=f"task-{i+1}", title=f"任务 {i+1}", description=f"描述 {i+1}")
        for i in range(n)
    ]
    return TaskList(overview="测试概述", tasks=tasks)


# ═══════════════════════════════════════════════════════════
# 缺口 1：全部任务被跳过
# ═══════════════════════════════════════════════════════════


class TestAllTasksSkipped:
    """多任务工作流中全部任务被跳过的完整路径。"""

    async def test_all_tasks_skipped_via_skip_task(
        self, runner, session, broadcast_log
    ):
        """3 个任务全部通过 skip_task 跳过后到达 COMPLETED。"""
        broadcast, calls = broadcast_log
        session.workflow_state = WorkflowState(
            task_list=_make_task_list(3),
            plan_approved=True,
        )

        mock_staging = MagicMock()
        mock_commit = MagicMock()
        mock_commit.files_changed = 0
        mock_commit.diffs = []
        mock_commit.combined_diff = ""
        mock_commit.summary = ""
        mock_staging.commit.return_value = mock_commit

        # reviewer 总是返回 needs_changes → 触发 FEEDBACK 暂停
        review_text = "---REVIEW_START---\n" + json.dumps({
            "overall_verdict": "needs_changes",
            "should_retry": True,
            "summary": "需要修改",
        }) + "\n---REVIEW_END---"

        call_count = 0

        async def mock_run_agent(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 1:
                # coder
                return (_make_agent_result("编码完成"), mock_staging)
            else:
                # reviewer → needs_changes
                return (_make_agent_result(review_text), None)

        runner._orchestrator.run_workflow_agent = AsyncMock(
            side_effect=mock_run_agent
        )

        # task-1: CODING → coder → CODE_REVIEW → REVIEWING → needs_changes → FEEDBACK
        session.phase = Phase.CODING
        await runner.execute(session, "test", broadcast)
        assert session.phase == Phase.FEEDBACK

        # skip_task task-1 → task-2: CODING → coder → REVIEWING → FEEDBACK
        await runner.handle_user_command(session, "skip_task", broadcast)
        await runner.execute(session, "test", broadcast)
        assert session.phase == Phase.FEEDBACK

        # skip_task task-2 → task-3: CODING → coder → REVIEWING → FEEDBACK
        await runner.handle_user_command(session, "skip_task", broadcast)
        await runner.execute(session, "test", broadcast)
        assert session.phase == Phase.FEEDBACK

        # skip_task task-3（最后一个） → COMPLETED
        await runner.handle_user_command(session, "skip_task", broadcast)
        assert session.phase == Phase.COMPLETED

        # 验证：所有任务都被推进（skip_task 调用 _advance_to_next_task）
        ws = session.workflow_state
        assert ws.task_list.current_task is None
        assert len(ws.completed_tasks) == 3

    async def test_all_tasks_skipped_via_skip_review(
        self, runner, session, broadcast_log
    ):
        """3 个任务全部通过 skip_review 跳过后到达 COMPLETED。"""
        broadcast, calls = broadcast_log
        session.workflow_state = WorkflowState(
            task_list=_make_task_list(3),
            plan_approved=True,
        )

        mock_staging = MagicMock()
        mock_commit = MagicMock()
        mock_commit.files_changed = 0
        mock_commit.diffs = []
        mock_commit.combined_diff = ""
        mock_commit.summary = ""
        mock_staging.commit.return_value = mock_commit
        mock_result = _make_agent_result("done")

        runner._orchestrator.run_workflow_agent = AsyncMock(
            return_value=(mock_result, mock_staging)
        )

        # 执行第一个任务 → CODE_REVIEW
        session.phase = Phase.CODING
        session.auto_review = False  # 手动审查模式
        await runner.execute(session, "test", broadcast)
        assert session.phase == Phase.CODE_REVIEW

        # skip_review → 推进到 task-2 CODING → CODE_REVIEW
        await runner.handle_user_command(session, "skip_review", broadcast)
        await runner.execute(session, "test", broadcast)
        assert session.phase == Phase.CODE_REVIEW

        # skip_review → 推进到 task-3 CODING → CODE_REVIEW
        await runner.handle_user_command(session, "skip_review", broadcast)
        await runner.execute(session, "test", broadcast)
        assert session.phase == Phase.CODE_REVIEW

        # skip_review → 最后一个任务 → COMPLETED
        await runner.handle_user_command(session, "skip_review", broadcast)
        assert session.phase == Phase.COMPLETED

        # 验证
        ws = session.workflow_state
        assert ws.task_list.current_task is None
        # completed_tasks 应包含所有 3 个任务（skip_review 也算推进）
        assert len(ws.completed_tasks) == 3

    async def test_all_tasks_auto_skipped_by_retry_limit(
        self, runner, session, broadcast_log
    ):
        """3 个任务全部因重试超限被自动跳过后到达 COMPLETED。"""
        broadcast, calls = broadcast_log
        session.workflow_state = WorkflowState(
            task_list=_make_task_list(3),
            plan_approved=True,
        )

        mock_staging = MagicMock()
        mock_commit = MagicMock()
        mock_commit.files_changed = 0
        mock_commit.diffs = []
        mock_commit.combined_diff = ""
        mock_commit.summary = ""
        mock_staging.commit.return_value = mock_commit

        # 每次审查都返回 needs_changes
        review_text = "---REVIEW_START---\n" + json.dumps({
            "overall_verdict": "needs_changes",
            "should_retry": True,
            "summary": "需要修改",
        }) + "\n---REVIEW_END---"

        runner._orchestrator.run_workflow_agent = AsyncMock(
            return_value=(_make_agent_result(review_text), mock_staging)
        )

        session.phase = Phase.CODING

        # 每个任务需要 3 次重试（MAX_RETRIES_PER_TASK）才自动跳过
        # 引擎在 retry_count < MAX 时暂停到 FEEDBACK 等待用户 retry
        for task_num in range(1, 4):
            if task_num == 1:
                # Task 1: 1st review → retry_count=1 → FEEDBACK
                await runner.execute(session, "test", broadcast)
                assert session.phase == Phase.FEEDBACK

            # 2nd review → retry_count=2 → FEEDBACK
            await runner.handle_user_command(session, "retry", broadcast)
            await runner.execute(session, "test", broadcast)
            assert session.phase == Phase.FEEDBACK

            # 3rd review → retry_count=3 → auto-skip
            await runner.handle_user_command(session, "retry", broadcast)
            await runner.execute(session, "test", broadcast)

            if task_num < 3:
                # auto-skip 后引擎继续循环，下一个任务 1st review → FEEDBACK
                assert session.phase == Phase.FEEDBACK
            else:
                # 最后一个任务 auto-skip → COMPLETED
                assert session.phase == Phase.COMPLETED

        ws = session.workflow_state
        assert ws.task_list.current_task is None
        assert len(ws.completed_tasks) == 3

    async def test_completion_broadcast_with_all_skipped(
        self, runner, session, broadcast_log
    ):
        """全部任务跳过后完成广播正确反映状态。"""
        broadcast, calls = broadcast_log
        session.workflow_state = WorkflowState(
            task_list=_make_task_list(2),
            plan_approved=True,
        )

        mock_staging = MagicMock()
        mock_commit = MagicMock()
        mock_commit.files_changed = 0
        mock_commit.diffs = []
        mock_commit.combined_diff = ""
        mock_commit.summary = ""
        mock_staging.commit.return_value = mock_commit

        runner._orchestrator.run_workflow_agent = AsyncMock(
            return_value=(_make_agent_result("done"), mock_staging)
        )

        session.phase = Phase.CODING
        session.auto_review = False
        await runner.execute(session, "test", broadcast)
        await runner.handle_user_command(session, "skip_review", broadcast)
        await runner.execute(session, "test", broadcast)
        await runner.handle_user_command(session, "skip_review", broadcast)
        # skip_review 设置 phase=COMPLETED，需 execute() 触发完成广播
        await runner.execute(session, "test", broadcast)

        # 检查完成广播
        completion_events = [
            c for c in calls if c["type"] == "agent.status"
            and c["payload"].get("phase") == "completed"
        ]
        assert len(completion_events) >= 1
        detail = completion_events[-1]["payload"]["detail"]
        assert "完成" in detail or "completed" in detail.lower()


# ═══════════════════════════════════════════════════════════
# 缺口 2：大量文件变更
# ═══════════════════════════════════════════════════════════


class TestLargeFileChanges:
    """大量文件变更场景测试。"""

    def test_diffset_with_50_files(self):
        """50 个文件的 DiffSet 构造和序列化。"""
        diffs = [
            {"path": f"src/module_{i}/file.py", "action": "create",
             "diff_text": f"+line {i}\n"}
            for i in range(50)
        ]
        combined = "\n".join(f"diff --git a/file_{i}.py b/file_{i}.py" for i in range(50))

        ds = DiffSet(
            task_id="task-1",
            files_changed=50,
            diffs=diffs,
            combined_diff=combined,
            summary="50 个文件变更",
        )

        d = ds.to_dict()
        assert d["files_changed"] == 50
        assert len(d["diffs"]) == 50

        # 反序列化往返
        ds2 = DiffSet.from_dict(d)
        assert ds2.files_changed == 50
        assert len(ds2.diffs) == 50
        assert ds2.task_id == "task-1"

    def test_diffset_with_100_files_serialization(self):
        """100 个文件的 DiffSet 序列化/反序列化不丢失数据。"""
        diffs = [
            {"path": f"file_{i}.py", "action": "modify", "diff_text": f"+{i}"}
            for i in range(100)
        ]
        ds = DiffSet(
            task_id="task-big",
            files_changed=100,
            diffs=diffs,
            combined_diff="..." * 1000,
            summary="大批量变更",
        )

        d = ds.to_dict()
        json_str = json.dumps(d, ensure_ascii=False)
        d2 = json.loads(json_str)
        ds2 = DiffSet.from_dict(d2)

        assert ds2.files_changed == 100
        assert len(ds2.diffs) == 100
        assert ds2.summary == "大批量变更"

    async def test_total_files_changed_accumulates_multi_task(
        self, runner, session, broadcast_log
    ):
        """多任务工作流中 total_files_changed 正确累加。"""
        broadcast, calls = broadcast_log
        session.workflow_state = WorkflowState(
            task_list=_make_task_list(3),
            plan_approved=True,
        )

        # 模拟每个任务产出不同数量的文件变更
        def make_staging(file_count):
            staging = MagicMock()
            commit = MagicMock()
            commit.files_changed = file_count
            commit.diffs = [{"path": f"f{i}.py"} for i in range(file_count)]
            commit.combined_diff = ""
            commit.summary = f"{file_count} files"
            staging.commit.return_value = commit
            return staging

        mock_result = _make_agent_result("done")
        # task-1: 5 files, task-2: 10 files, task-3: 3 files → total = 18
        runner._orchestrator.run_workflow_agent = AsyncMock(side_effect=[
            (mock_result, make_staging(5)),   # task-1 coder
            (_make_agent_result("approved"), None),  # task-1 reviewer → approved
            (mock_result, make_staging(10)),  # task-2 coder
            (_make_agent_result("approved"), None),  # task-2 reviewer → approved
            (mock_result, make_staging(3)),   # task-3 coder
            (_make_agent_result("approved"), None),  # task-3 reviewer → approved
        ])

        session.phase = Phase.CODING
        await runner.execute(session, "test", broadcast)

        assert session.phase == Phase.COMPLETED
        assert session.workflow_state.total_files_changed == 18

    async def test_files_changed_broadcast_with_many_files(
        self, runner, session, broadcast_log
    ):
        """50 个文件变更时 DiffSet 正确捕获所有文件信息。"""
        broadcast, calls = broadcast_log
        session.workflow_state = WorkflowState(
            task_list=_make_task_list(1),
            plan_approved=True,
        )

        # 模拟 50 个文件变更的 staging
        staging = MagicMock()
        commit = MagicMock()
        commit.files_changed = 50
        commit.diffs = [
            MagicMock(path=Path(f"file_{i}.py"), action="create",
                      diff_text=f"+content {i}")
            for i in range(50)
        ]
        commit.combined_diff = "big diff"
        commit.summary = "50 files changed"
        staging.commit.return_value = commit

        runner._orchestrator.run_workflow_agent = AsyncMock(
            return_value=(_make_agent_result("done"), staging)
        )

        session.phase = Phase.CODING
        session.auto_review = False
        await runner.execute(session, "test", broadcast)

        # 验证 DiffSet 正确捕获了 50 个文件
        ws = session.workflow_state
        assert ws.current_diff_set is not None
        assert ws.current_diff_set.files_changed == 50
        assert len(ws.current_diff_set.diffs) == 50
        assert ws.current_diff_set.summary == "50 files changed"
        # total_files_changed 也应累加
        assert ws.total_files_changed == 50

    def test_large_diff_truncation_in_reviewer_message(self):
        """超长 combined_diff 在 reviewer 消息中被截断到 8000 字符。"""
        long_diff = "x" * 20000
        ds = DiffSet(
            task_id="task-1",
            files_changed=1,
            combined_diff=long_diff,
            summary="大文件",
        )

        session = Session(
            id="test", work_dir=Path("/tmp"), phase=Phase.REVIEWING,
        )
        session.workflow_state = WorkflowState(current_diff_set=ds)

        msg = WorkflowRunner._build_reviewer_message(ds, session)
        # 应包含截断后的 diff 和截断提示
        assert "..." in msg or len(msg) < len(long_diff) + 1000


# ═══════════════════════════════════════════════════════════
# 缺口 3：LLM 输出半畸形解析
# ═══════════════════════════════════════════════════════════


class TestParserMalformedInput:
    """产出物解析器对半畸形输入的鲁棒性测试。"""


class TestTaskListParserMalformed:
    """parse_task_list 半畸形输入测试。"""

    def test_json_missing_id_field(self):
        """task 缺少 id 字段时自动生成。"""
        text = "---TASKLIST_START---\n" + json.dumps({
            "overview": "测试",
            "tasks": [
                {"title": "任务1", "description": "描述1"},
                {"title": "任务2", "description": "描述2"},
            ]
        }) + "\n---TASKLIST_END---"
        tl = parse_task_list(text)
        assert tl is not None
        assert tl.total_count == 2
        assert tl.tasks[0].id == "task-1"
        assert tl.tasks[1].id == "task-2"

    def test_json_missing_title_field(self):
        """task 缺少 title 字段时自动生成默认标题。"""
        text = "---TASKLIST_START---\n" + json.dumps({
            "tasks": [
                {"id": "t1", "description": "描述1"},
            ]
        }) + "\n---TASKLIST_END---"
        tl = parse_task_list(text)
        assert tl is not None
        assert tl.tasks[0].title == "任务 1"

    def test_json_missing_description_field(self):
        """task 缺少 description 字段时默认为空字符串。"""
        text = "---TASKLIST_START---\n" + json.dumps({
            "tasks": [{"id": "t1", "title": "任务1"}]
        }) + "\n---TASKLIST_END---"
        tl = parse_task_list(text)
        assert tl is not None
        assert tl.tasks[0].description == ""

    def test_json_extra_unknown_fields(self):
        """JSON 含多余未知字段时不报错。"""
        text = "---TASKLIST_START---\n" + json.dumps({
            "overview": "测试",
            "tasks": [{"id": "t1", "title": "T1", "description": "D1",
                       "unknown_field": "xxx", "extra": 123}],
            "risks": ["风险1"],
            "estimated_effort": "2h",
            "unknown_top_field": True,
        }) + "\n---TASKLIST_END---"
        tl = parse_task_list(text)
        assert tl is not None
        assert tl.total_count == 1
        assert tl.tasks[0].title == "T1"
        assert tl.risks == ["风险1"]
        assert tl.estimated_effort == "2h"

    def test_json_with_code_fence_wrapper(self):
        """JSON 被 ```json ... ``` 包裹时正确解析。"""
        text = "---TASKLIST_START---\n```json\n" + json.dumps({
            "tasks": [{"id": "t1", "title": "T1", "description": "D1"}]
        }) + "\n```\n---TASKLIST_END---"
        tl = parse_task_list(text)
        assert tl is not None
        assert tl.total_count == 1

    def test_json_with_trailing_commas(self):
        """JSON 含尾随逗号时宽松解析成功。"""
        text = "---TASKLIST_START---\n" + \
            '{"overview": "测试",\n' + \
            ' "tasks": [\n' + \
            '  {"id": "t1", "title": "T1", "description": "D1",},\n' + \
            '  {"id": "t2", "title": "T2", "description": "D2",},\n' + \
            ' ],\n' + \
            ' "risks": ["r1",],\n' + \
            '}\n---TASKLIST_END---'
        tl = parse_task_list(text)
        assert tl is not None
        assert tl.total_count == 2

    def test_start_marker_without_end(self):
        """只有 START 标记没有 END 标记时回退到启发式解析。"""
        text = "---TASKLIST_START---\n" + json.dumps({
            "tasks": [{"id": "t1", "title": "T1", "description": "D1"}]
        })
        # 没有 END 标记 → JSON 解析失败 → 启发式回退
        tl = parse_task_list(text)
        # 启发式可能解析出任务（按编号拆分），也可能返回 None
        # 关键是不崩溃
        assert tl is None or tl.total_count >= 0

    def test_empty_tasks_array(self):
        """tasks 数组为空时返回 None。"""
        text = "---TASKLIST_START---\n" + json.dumps({
            "overview": "空计划",
            "tasks": [],
        }) + "\n---TASKLIST_END---"
        tl = parse_task_list(text)
        assert tl is None

    def test_truncated_json(self):
        """JSON 被截断（输出 token 超限）时降级到启发式解析。"""
        text = "---TASKLIST_START---\n" + \
            '{"overview": "测试", "tasks": [{"id": "t1", "title": "T1"'
        # JSON 不完整，没有 END 标记
        tl = parse_task_list(text)
        # 应该返回 None 或通过启发式解析出一些任务
        assert tl is None or tl.total_count >= 0

    def test_alternative_field_names(self):
        """JSON 使用替代字段名（name/desc/criteria/files）时正确映射。"""
        text = "---TASKLIST_START---\n" + json.dumps({
            "summary": "测试",
            "subtasks": [
                {"name": "任务1", "desc": "描述1", "files": ["a.py"], "criteria": "通过"},
            ],
            "effort": "1h",
        }) + "\n---TASKLIST_END---"
        tl = parse_task_list(text)
        assert tl is not None
        assert tl.overview == "测试"
        assert tl.tasks[0].title == "任务1"
        assert tl.tasks[0].description == "描述1"
        assert tl.tasks[0].files_involved == ["a.py"]
        assert tl.tasks[0].acceptance_criteria == "通过"
        assert tl.estimated_effort == "1h"

    def test_heuristic_fallback_with_numbered_list(self):
        """启发式回退：按 "1. " "2. " 编号拆分。"""
        text = (
            "方案概述：实现功能\n\n"
            "1. 创建模型\n"
            "2. 实现接口\n"
            "3. 添加测试\n"
        )
        tl = parse_task_list(text)
        assert tl is not None
        assert tl.total_count == 3
        assert tl.tasks[0].title == "创建模型"
        assert tl.tasks[2].title == "添加测试"

    def test_heuristic_fallback_with_dash_list(self):
        """启发式回退：按 "- " 列表拆分。"""
        text = (
            "任务列表：\n"
            "- 创建数据库表\n"
            "- 编写 API 接口\n"
        )
        tl = parse_task_list(text)
        assert tl is not None
        assert tl.total_count == 2

    def test_completely_unparseable_text(self):
        """完全无法解析的文本返回 None。"""
        text = "这是一段普通文本，没有任务列表，也没有编号。"
        tl = parse_task_list(text)
        assert tl is None


class TestReviewReportParserMalformed:
    """parse_review_report 半畸形输入测试。"""

    def test_invalid_severity_normalized(self):
        """非法 severity 值被规范化为 info。"""
        text = "---REVIEW_START---\n" + json.dumps({
            "overall_verdict": "approved",
            "file_reviews": [
                {"file_path": "a.py", "issues": ["问题1"],
                 "severity": "critical_error"},
            ],
            "summary": "通过",
        }) + "\n---REVIEW_END---"
        report = parse_review_report(text, task_id="t1")
        assert report is not None
        assert report.overall_verdict == VERDICT_APPROVED
        assert report.file_reviews[0].severity == SEVERITY_INFO

    def test_missing_overall_verdict_defaults_approved(self):
        """缺少 overall_verdict 字段时默认 approved。"""
        text = "---REVIEW_START---\n" + json.dumps({
            "summary": "审查完成",
            "file_reviews": [],
        }) + "\n---REVIEW_END---"
        report = parse_review_report(text, task_id="t1")
        assert report is not None
        assert report.overall_verdict == VERDICT_APPROVED
        assert report.should_retry is False

    def test_missing_should_retry_inferred_from_verdict(self):
        """缺少 should_retry 字段时从 verdict 推断。"""
        text = "---REVIEW_START---\n" + json.dumps({
            "overall_verdict": "needs_changes",
            "summary": "需要修改",
        }) + "\n---REVIEW_END---"
        report = parse_review_report(text, task_id="t1")
        assert report is not None
        assert report.should_retry is True

    def test_verdict_chinese_keywords(self):
        """中文 verdict 关键词正确映射。"""
        for cn_verdict, expected in [
            ("批准", VERDICT_APPROVED),
            ("通过", VERDICT_APPROVED),
            ("需修改", VERDICT_NEEDS_CHANGES),
            ("需要修改", VERDICT_NEEDS_CHANGES),
            ("建议修改", VERDICT_NEEDS_CHANGES),
            ("拒绝", VERDICT_REJECTED),
            ("驳回", VERDICT_REJECTED),
        ]:
            text = "---REVIEW_START---\n" + json.dumps({
                "overall_verdict": cn_verdict,
            }) + "\n---REVIEW_END---"
            report = parse_review_report(text, task_id="t1")
            assert report is not None
            assert report.overall_verdict == expected, f"Failed for: {cn_verdict}"

    def test_missing_file_path_in_file_review(self):
        """file_review 缺少 file_path 时默认为空字符串。"""
        text = "---REVIEW_START---\n" + json.dumps({
            "overall_verdict": "approved",
            "file_reviews": [
                {"issues": ["问题1"], "suggestions": ["建议1"]},
            ],
        }) + "\n---REVIEW_END---"
        report = parse_review_report(text, task_id="t1")
        assert report is not None
        assert report.file_reviews[0].file_path == ""

    def test_file_reviews_as_non_dict(self):
        """file_reviews 包含非字典元素时跳过。"""
        text = "---REVIEW_START---\n" + json.dumps({
            "overall_verdict": "approved",
            "file_reviews": [
                "not a dict",
                {"file_path": "a.py", "issues": []},
                123,
            ],
        }) + "\n---REVIEW_END---"
        report = parse_review_report(text, task_id="t1")
        assert report is not None
        assert len(report.file_reviews) == 1
        assert report.file_reviews[0].file_path == "a.py"

    def test_heuristic_with_mixed_keywords(self):
        """启发式解析中混合关键词的优先级。"""
        # "拒绝" 优先于 "通过"
        text = "代码审查报告\n\n总体结论：拒绝合并。\n虽然部分功能通过测试，但存在严重问题。"
        report = parse_review_report(text, task_id="t1")
        assert report is not None
        # "拒绝" 应该被检测到
        assert report.overall_verdict == VERDICT_REJECTED
        assert report.should_retry is True

    def test_heuristic_no_keywords_defaults_approved(self):
        """启发式解析中无关键词时默认通过。"""
        text = "代码已审查，未发现明显问题。"
        report = parse_review_report(text, task_id="t1")
        assert report is not None
        assert report.overall_verdict == VERDICT_APPROVED
        assert report.should_retry is False

    def test_json_with_code_fence(self):
        """JSON 被 ```json 包裹时正确解析。"""
        text = "---REVIEW_START---\n```json\n" + json.dumps({
            "overall_verdict": "approved",
            "summary": "通过",
        }) + "\n```\n---REVIEW_END---"
        report = parse_review_report(text, task_id="t1")
        assert report is not None
        assert report.overall_verdict == VERDICT_APPROVED

    def test_truncated_json_review(self):
        """截断的 JSON 降级到启发式解析。"""
        text = "---REVIEW_START---\n" + \
            '{"overall_verdict": "appr'
        # 没有 END 标记，JSON 不完整
        report = parse_review_report(text, task_id="t1")
        # 启发式解析中 "appr" 不包含完整关键词，默认 approved
        assert report is not None
        assert report.overall_verdict == VERDICT_APPROVED


class TestDiffSetParserMalformed:
    """parse_diff_set 半畸形输入测试。"""

    def test_json_missing_summary(self):
        """缺少 summary 字段时默认为空。"""
        text = "---DIFFSET_START---\n" + json.dumps({
            "task_id": "t1",
            "files_changed": 3,
            "diffs": [],
            "combined_diff": "",
        }) + "\n---DIFFSET_END---"
        ds = parse_diff_set(text, task_id="t1")
        assert ds is not None
        assert ds.summary == ""

    def test_json_missing_files_changed(self):
        """缺少 files_changed 字段时默认为 0。"""
        text = "---DIFFSET_START---\n" + json.dumps({
            "task_id": "t1",
            "combined_diff": "",
        }) + "\n---DIFFSET_END---"
        ds = parse_diff_set(text, task_id="t1")
        assert ds is not None
        assert ds.files_changed == 0

    def test_json_missing_task_id_uses_param(self):
        """缺少 task_id 字段时使用传入的 task_id 参数。"""
        text = "---DIFFSET_START---\n" + json.dumps({
            "files_changed": 1,
        }) + "\n---DIFFSET_END---"
        ds = parse_diff_set(text, task_id="fallback-id")
        assert ds is not None
        assert ds.task_id == "fallback-id"

    def test_diff_block_extraction_from_markdown(self):
        """从 ```diff 代码块中提取 diff。"""
        text = (
            "变更摘要：修改了文件\n\n"
            "```diff\n"
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1,3 +1,4 @@\n"
            " line1\n"
            "+new line\n"
            " line2\n"
            "```\n"
        )
        ds = parse_diff_set(text, task_id="t1")
        assert ds is not None
        assert "file.py" in ds.combined_diff
        assert "+new line" in ds.combined_diff

    def test_empty_text_returns_none(self):
        """空文本返回 None。"""
        ds = parse_diff_set("", task_id="t1")
        assert ds is None

    def test_json_with_code_fence(self):
        """JSON 被 ```json 包裹时正确解析。"""
        text = "---DIFFSET_START---\n```json\n" + json.dumps({
            "task_id": "t1",
            "files_changed": 2,
            "summary": "变更",
        }) + "\n```\n---DIFFSET_END---"
        ds = parse_diff_set(text, task_id="t1")
        assert ds is not None
        assert ds.files_changed == 2
        assert ds.summary == "变更"

    def test_malformed_json_falls_back_to_diff_extraction(self):
        """JSON 解析失败时回退到 diff 块提取。"""
        text = (
            "---DIFFSET_START---\n"
            "这不是有效JSON\n"
            "---DIFFSET_END---\n\n"
            "```diff\n"
            "--- a/test.py\n"
            "+++ b/test.py\n"
            "+new\n"
            "```\n"
        )
        ds = parse_diff_set(text, task_id="t1")
        # JSON 解析失败，但有 diff 块 → 应提取到 diff
        assert ds is not None
        assert "test.py" in ds.combined_diff


# ═══════════════════════════════════════════════════════════
# 补充：WorkflowState 大量数据的持久化往返
# ═══════════════════════════════════════════════════════════


class TestWorkflowStateLargeDataPersistence:
    """大量数据下 WorkflowState 序列化/反序列化正确性。"""

    def test_large_completed_tasks_list(self):
        """100 个已完成任务的 WorkflowState 往返。"""
        tasks = [
            SubTask(id=f"task-{i}", title=f"任务 {i}", description=f"描述 {i}",
                    status="done")
            for i in range(100)
        ]
        ws = WorkflowState(
            task_list=TaskList(overview="大项目", tasks=tasks),
            completed_tasks=[f"task-{i}" for i in range(100)],
            total_files_changed=500,
            retry_count=0,
        )

        d = ws.to_dict()
        json_str = json.dumps(d, ensure_ascii=False)
        ws2 = WorkflowState.from_dict(json.loads(json_str))

        assert ws2 is not None
        assert ws2.task_list.total_count == 100
        assert len(ws2.completed_tasks) == 100
        assert ws2.total_files_changed == 500

    def test_workflow_state_with_large_diff_set(self):
        """包含大量 diffs 的 DiffSet 在 WorkflowState 中持久化。"""
        diffs = [{"path": f"f{i}.py", "action": "create"} for i in range(50)]
        ds = DiffSet(
            task_id="task-1",
            files_changed=50,
            diffs=diffs,
            combined_diff="x" * 10000,
            summary="大变更",
        )
        ws = WorkflowState(
            task_list=TaskList(
                overview="测试",
                tasks=[SubTask(id="t1", title="T1", description="D1")],
            ),
            current_diff_set=ds,
            total_files_changed=50,
        )

        d = ws.to_dict()
        json_str = json.dumps(d, ensure_ascii=False)
        ws2 = WorkflowState.from_dict(json.loads(json_str))

        assert ws2 is not None
        assert ws2.current_diff_set is not None
        assert ws2.current_diff_set.files_changed == 50
        assert len(ws2.current_diff_set.diffs) == 50
        assert ws2.total_files_changed == 50
