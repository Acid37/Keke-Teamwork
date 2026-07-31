"""工作流引擎核心数据类型。

定义阶段间传递的结构化产出物：
- TaskList：Planner 产出 → Coder 消费
- DiffSet：Coder 产出 → Reviewer 消费
- ReviewReport：Reviewer 产出 → Coder / User 消费
- WorkflowState：工作流运行时状态（持久化到 session JSON）
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.types import FileDiff, Session


# ─── 子任务状态常量 ───

TASK_PENDING = "pending"
TASK_IN_PROGRESS = "in_progress"
TASK_DONE = "done"
TASK_SKIPPED = "skipped"

# ─── 审查判定常量 ───

VERDICT_APPROVED = "approved"
VERDICT_NEEDS_CHANGES = "needs_changes"
VERDICT_REJECTED = "rejected"

# ─── 严重级别常量 ───

SEVERITY_BLOCKER = "blocker"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"


# ─── 阶段间数据结构 ───


@dataclass
class SubTask:
    """单个子任务（Planner 产出）。

    Attributes:
        id: 任务标识，如 "task-1"
        title: 简短标题，如 "创建 User 模型"
        description: 详细描述
        files_involved: 预估涉及的文件路径列表
        acceptance_criteria: 验收标准
        priority: 优先级（数字越小越优先）
        status: 执行状态
    """

    id: str
    title: str
    description: str
    files_involved: list[str] = field(default_factory=list)
    acceptance_criteria: str = ""
    priority: int = 0
    status: str = TASK_PENDING

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> SubTask:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class TaskList:
    """规划产出物（Planner 产出 → Coder 消费）。

    Attributes:
        overview: 方案概述
        tasks: 有序子任务列表
        risks: 识别到的风险
        estimated_effort: 预估工时
        current_task_index: 当前执行的子任务索引
    """

    overview: str = ""
    tasks: list[SubTask] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    estimated_effort: str = ""
    current_task_index: int = 0

    @property
    def current_task(self) -> SubTask | None:
        """当前正在执行或待执行的子任务，None 表示全部完成。"""
        if self.current_task_index < len(self.tasks):
            return self.tasks[self.current_task_index]
        return None

    @property
    def completed_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == TASK_DONE)

    @property
    def total_count(self) -> int:
        return len(self.tasks)

    def advance(self) -> SubTask | None:
        """推进到下一个子任务，返回新的当前任务（None 表示全部完成）。"""
        # 标记当前任务为完成
        if self.current_task and self.current_task.status == TASK_IN_PROGRESS:
            self.current_task.status = TASK_DONE
        self.current_task_index += 1
        return self.current_task

    def to_dict(self) -> dict:
        return {
            "overview": self.overview,
            "tasks": [t.to_dict() for t in self.tasks],
            "risks": self.risks,
            "estimated_effort": self.estimated_effort,
            "current_task_index": self.current_task_index,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TaskList:
        tasks = [SubTask.from_dict(t) for t in data.get("tasks", [])]
        return cls(
            overview=data.get("overview", ""),
            tasks=tasks,
            risks=data.get("risks", []),
            estimated_effort=data.get("estimated_effort", ""),
            current_task_index=data.get("current_task_index", 0),
        )


@dataclass
class DiffSet:
    """编码产出物（Coder 产出 → Reviewer 消费）。

    复用已有 ``CommitResult`` 的字段，但增加了 task_id 关联。

    Attributes:
        task_id: 对应的子任务 ID
        files_changed: 变更文件数
        diffs: 文件级 diff 列表（复用 backend.types.FileDiff）
        combined_diff: 合并 diff 文本
        summary: 变更摘要
        test_results: coder 运行的测试结果（可选）
    """

    task_id: str = ""
    files_changed: int = 0
    diffs: list[dict] = field(default_factory=list)  # 序列化后的 FileDiff
    combined_diff: str = ""
    summary: str = ""
    test_results: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> DiffSet:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_commit_result(cls, task_id: str, commit: object) -> DiffSet:
        """从 CommitResult 构造 DiffSet。

        Args:
            task_id: 关联的子任务 ID
            commit: CommitResult 实例（含 files_changed, diffs, combined_diff, summary）
        """
        # 将 FileDiff dataclass 序列化为 dict
        diffs_serialized = []
        for d in commit.diffs:
            if hasattr(d, "to_dict"):
                diffs_serialized.append(d.to_dict())
            elif hasattr(d, "__dict__"):
                diffs_serialized.append({
                    "path": str(d.path) if hasattr(d, "path") else "",
                    "action": getattr(d, "action", ""),
                    "diff_text": getattr(d, "diff_text", ""),
                    "new_content": getattr(d, "new_content", None),
                })
            else:
                diffs_serialized.append(d)

        return cls(
            task_id=task_id,
            files_changed=commit.files_changed,
            diffs=diffs_serialized,
            combined_diff=commit.combined_diff,
            summary=commit.summary,
        )


@dataclass
class FileReview:
    """单文件审查意见。

    Attributes:
        file_path: 文件路径
        issues: 发现的问题列表
        suggestions: 改进建议列表
        severity: 严重级别 ("blocker" | "warning" | "info")
    """

    file_path: str = ""
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    severity: str = SEVERITY_INFO

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> FileReview:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ReviewReport:
    """审查报告（Reviewer 产出 → Coder / User 消费）。

    Attributes:
        task_id: 对应子任务 ID
        overall_verdict: 总体判定 ("approved" | "needs_changes" | "rejected")
        file_reviews: 逐文件审查意见
        summary: 审查摘要
        should_retry: 是否需要 coder 修改后重审
    """

    task_id: str = ""
    overall_verdict: str = VERDICT_APPROVED
    file_reviews: list[FileReview] = field(default_factory=list)
    summary: str = ""
    should_retry: bool = False

    @property
    def is_approved(self) -> bool:
        return self.overall_verdict == VERDICT_APPROVED

    @property
    def has_blockers(self) -> bool:
        return any(
            fr.severity == SEVERITY_BLOCKER and fr.issues
            for fr in self.file_reviews
        )

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "overall_verdict": self.overall_verdict,
            "file_reviews": [fr.to_dict() for fr in self.file_reviews],
            "summary": self.summary,
            "should_retry": self.should_retry,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ReviewReport:
        file_reviews = [
            FileReview.from_dict(fr) for fr in data.get("file_reviews", [])
        ]
        return cls(
            task_id=data.get("task_id", ""),
            overall_verdict=data.get("overall_verdict", VERDICT_APPROVED),
            file_reviews=file_reviews,
            summary=data.get("summary", ""),
            should_retry=data.get("should_retry", False),
        )


# ─── 工作流运行时状态 ───


@dataclass
class WorkflowState:
    """工作流运行时状态（持久化到 session JSON）。

    在 Session 上挂载此对象，记录工作流引擎的当前进度。

    Attributes:
        task_list: 规划产出物
        current_diff_set: 当前编码产出
        last_review_report: 最近一次审查报告
        plan_approved: 用户是否已确认计划
        completed_tasks: 已完成的子任务 ID 列表
        user_command_queue: 待处理的用户命令队列
    """

    task_list: TaskList | None = None
    current_diff_set: DiffSet | None = None
    last_review_report: ReviewReport | None = None
    plan_approved: bool = False
    completed_tasks: list[str] = field(default_factory=list)
    user_command_queue: list[dict] = field(default_factory=list)
    retry_count: int = 0
    total_files_changed: int = 0

    @property
    def current_task(self) -> SubTask | None:
        """当前正在执行的子任务。"""
        if self.task_list:
            return self.task_list.current_task
        return None

    def to_dict(self) -> dict:
        return {
            "task_list": self.task_list.to_dict() if self.task_list else None,
            "current_diff_set": self.current_diff_set.to_dict() if self.current_diff_set else None,
            "last_review_report": self.last_review_report.to_dict() if self.last_review_report else None,
            "plan_approved": self.plan_approved,
            "completed_tasks": self.completed_tasks,
            "user_command_queue": self.user_command_queue,
            "retry_count": self.retry_count,
            "total_files_changed": self.total_files_changed,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> WorkflowState | None:
        if not data:
            return None
        task_list = None
        if data.get("task_list"):
            task_list = TaskList.from_dict(data["task_list"])
        diff_set = None
        if data.get("current_diff_set"):
            diff_set = DiffSet.from_dict(data["current_diff_set"])
        review_report = None
        if data.get("last_review_report"):
            review_report = ReviewReport.from_dict(data["last_review_report"])
        return cls(
            task_list=task_list,
            current_diff_set=diff_set,
            last_review_report=review_report,
            plan_approved=data.get("plan_approved", False),
            completed_tasks=data.get("completed_tasks", []),
            user_command_queue=data.get("user_command_queue", []),
            retry_count=data.get("retry_count", 0),
            total_files_changed=data.get("total_files_changed", 0),
        )


# ─── 阶段转换守卫 ───


class PhaseGuard:
    """阶段转换守卫条件。

    每个方法检查是否允许从当前阶段进入目标阶段。
    所有方法返回 bool，不抛异常。
    """

    @staticmethod
    def can_enter_planning(session: Session) -> bool:
        """允许进入 PLANNING：从 INIT / ERROR / COMPLETED。"""
        from backend.types import Phase
        return session.phase in (Phase.INIT, Phase.ERROR, Phase.COMPLETED)

    @staticmethod
    def can_enter_plan_review(session: Session) -> bool:
        """允许进入 PLAN_REVIEW：有 TaskList 且来自 PLANNING。"""
        from backend.types import Phase
        return (
            session.phase == Phase.PLANNING
            and session.workflow_state is not None
            and session.workflow_state.task_list is not None
        )

    @staticmethod
    def can_enter_coding(session: Session) -> bool:
        """允许进入 CODING：有 TaskList 且计划已确认。"""
        from backend.types import Phase
        ws = session.workflow_state
        return (
            session.phase in (Phase.PLAN_REVIEW, Phase.FEEDBACK, Phase.CODING)
            and ws is not None
            and ws.task_list is not None
            and ws.plan_approved
        )

    @staticmethod
    def can_enter_reviewing(session: Session) -> bool:
        """允许进入 REVIEWING：当前子任务有 diff 产出。"""
        from backend.types import Phase
        ws = session.workflow_state
        return (
            session.phase == Phase.CODE_REVIEW
            and ws is not None
            and ws.current_diff_set is not None
        )

    @staticmethod
    def can_enter_feedback(session: Session) -> bool:
        """允许进入 FEEDBACK：审查报告要求重试。"""
        from backend.types import Phase
        ws = session.workflow_state
        return (
            session.phase == Phase.REVIEWING
            and ws is not None
            and ws.last_review_report is not None
            and ws.last_review_report.should_retry
        )

    @staticmethod
    def can_enter_completed(session: Session) -> bool:
        """允许进入 COMPLETED：所有子任务完成。"""
        from backend.types import Phase
        ws = session.workflow_state
        if ws is None or ws.task_list is None:
            return False
        return (
            session.phase in (Phase.REVIEWING, Phase.CODE_REVIEW)
            and ws.task_list.current_task is None
        )
