"""结构化产出物解析器。

从 LLM 自然语言回复中提取结构化数据：
- parse_task_list：从 Planner 回复中提取 TaskList
- parse_diff_set：从 Coder 回复中提取 DiffSet
- parse_review_report：从 Reviewer 回复中提取 ReviewReport

解析策略（方案 A 优先）：
1. 标记分隔：在 prompt 中要求 LLM 以 ---XXX_START--- / ---XXX_END--- 标记输出 JSON
2. 标记间内容做 JSON 解析
3. 解析失败则用启发式回退（按编号拆分等）
"""

from __future__ import annotations

import json
import logging
import re

from backend.workflow.types import (
    DiffSet,
    FileReview,
    ReviewReport,
    SubTask,
    TaskList,
    VERDICT_APPROVED,
    VERDICT_NEEDS_CHANGES,
    VERDICT_REJECTED,
    SEVERITY_BLOCKER,
    SEVERITY_WARNING,
    SEVERITY_INFO,
)

logger = logging.getLogger(__name__)

# ─── 标记常量 ───

_TASKLIST_START = "---TASKLIST_START---"
_TASKLIST_END = "---TASKLIST_END---"
_DIFFSET_START = "---DIFFSET_START---"
_DIFFSET_END = "---DIFFSET_END---"
_REVIEW_START = "---REVIEW_START---"
_REVIEW_END = "---REVIEW_END---"


# ─── TaskList 解析 ───


def parse_task_list(text: str) -> TaskList | None:
    """从 LLM 文本回复中提取 TaskList。

    优先尝试 JSON 标记解析，失败则用启发式编号拆分。

    Args:
        text: Planner Agent 的完整文本回复

    Returns:
        TaskList 实例，解析失败返回 None
    """
    # 方案 A：JSON 标记解析
    task_list = _try_parse_task_list_json(text)
    if task_list is not None:
        logger.debug("TaskList parsed via JSON markers")
        return task_list

    # 方案 B：启发式回退
    task_list = _heuristic_parse_tasks(text)
    if task_list is not None:
        logger.debug("TaskList parsed via heuristic fallback")
        return task_list

    logger.warning("Failed to parse TaskList from text (length=%d)", len(text))
    return None


def _try_parse_task_list_json(text: str) -> TaskList | None:
    """尝试从 ---TASKLIST_START--- / ---TASKLIST_END--- 标记间提取 JSON。"""
    pattern = re.compile(
        re.escape(_TASKLIST_START) + r"\s*(.*?)\s*" + re.escape(_TASKLIST_END),
        re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return None

    raw = match.group(1).strip()
    # 去除可能的 ```json ... ``` 包裹
    raw = _strip_code_fence(raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.debug("JSON decode failed for TaskList, trying lenient parse")
        data = _lenient_json_parse(raw)
        if data is None:
            return None

    return _build_task_list_from_dict(data)


def _build_task_list_from_dict(data: dict) -> TaskList | None:
    """从字典构建 TaskList，处理字段名差异。"""
    tasks_data = data.get("tasks") or data.get("subtasks") or []
    if not tasks_data:
        return None

    tasks: list[SubTask] = []
    for i, t in enumerate(tasks_data):
        if not isinstance(t, dict):
            continue
        task = SubTask(
            id=t.get("id") or f"task-{i + 1}",
            title=t.get("title") or t.get("name") or f"任务 {i + 1}",
            description=t.get("description") or t.get("desc") or "",
            files_involved=t.get("files_involved") or t.get("files") or [],
            acceptance_criteria=t.get("acceptance_criteria") or t.get("criteria") or "",
            priority=t.get("priority", 0),
            status=t.get("status", "pending"),
        )
        tasks.append(task)

    return TaskList(
        overview=data.get("overview") or data.get("summary") or "",
        tasks=tasks,
        risks=data.get("risks") or [],
        estimated_effort=data.get("estimated_effort") or data.get("effort") or "",
    )


def _heuristic_parse_tasks(text: str) -> TaskList | None:
    """启发式解析：按编号列表（1. 2. 3.）拆分子任务。"""
    # 匹配 "1. 标题" 或 "1) 标题" 或 "- 标题" 开头的行
    task_pattern = re.compile(r"^\s*(?:\d+[\.\)]\s*|[-*]\s+)(.+)", re.MULTILINE)
    matches = task_pattern.findall(text)

    if len(matches) < 1:
        return None

    tasks: list[SubTask] = []
    for i, line in enumerate(matches):
        line = line.strip()
        if not line:
            continue
        # 尝试拆分标题和描述（冒号或换行分隔）
        parts = re.split(r"[:：\n]", line, maxsplit=1)
        title = parts[0].strip()
        description = parts[1].strip() if len(parts) > 1 else ""

        tasks.append(SubTask(
            id=f"task-{i + 1}",
            title=title,
            description=description,
        ))

    if not tasks:
        return None

    return TaskList(
        overview="",
        tasks=tasks,
    )


# ─── DiffSet 解析 ───


def parse_diff_set(text: str, task_id: str = "") -> DiffSet | None:
    """从 LLM 文本回复中提取 DiffSet。

    Coder Agent 通常通过工具调用产生 diff，但也可能在回复中
    包含结构化的变更摘要。

    Args:
        text: Coder Agent 的完整文本回复
        task_id: 对应的子任务 ID

    Returns:
        DiffSet 实例，解析失败返回 None
    """
    # 方案 A：JSON 标记解析
    diff_set = _try_parse_diff_set_json(text, task_id)
    if diff_set is not None:
        logger.debug("DiffSet parsed via JSON markers")
        return diff_set

    # 方案 B：提取文本中的 diff 块
    diff_text = _extract_diff_block(text)
    if diff_text:
        logger.debug("DiffSet parsed via diff block extraction")
        files_changed = _count_files_in_diff(diff_text)
        summary = _extract_summary_line(text)
        return DiffSet(
            task_id=task_id,
            files_changed=files_changed,
            combined_diff=diff_text,
            summary=summary,
        )

    logger.warning("Failed to parse DiffSet from text (length=%d)", len(text))
    return None


def _try_parse_diff_set_json(text: str, task_id: str) -> DiffSet | None:
    """尝试从 ---DIFFSET_START--- / ---DIFFSET_END--- 标记间提取 JSON。"""
    pattern = re.compile(
        re.escape(_DIFFSET_START) + r"\s*(.*?)\s*" + re.escape(_DIFFSET_END),
        re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return None

    raw = match.group(1).strip()
    raw = _strip_code_fence(raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    return DiffSet(
        task_id=data.get("task_id") or task_id,
        files_changed=data.get("files_changed", 0),
        diffs=data.get("diffs") or [],
        combined_diff=data.get("combined_diff") or "",
        summary=data.get("summary") or "",
        test_results=data.get("test_results"),
    )


def _extract_diff_block(text: str) -> str:
    """从文本中提取 unified diff 格式块（```diff ... ``` 或裸 diff）。"""
    # 尝试提取 ```diff ... ``` 代码块
    diff_fence = re.compile(r"```diff\s*\n(.*?)```", re.DOTALL)
    match = diff_fence.search(text)
    if match:
        return match.group(1).strip()

    # 尝试提取以 --- / +++ 开头的 diff 块
    diff_lines = []
    in_diff = False
    for line in text.splitlines():
        if line.startswith("--- ") or line.startswith("diff --git"):
            in_diff = True
        if in_diff:
            diff_lines.append(line)
            # diff 块结束标志：空行后非 diff 内容
            if not line.strip() and diff_lines:
                # 向前看是否有更多 diff 行
                continue
    if diff_lines:
        return "\n".join(diff_lines).strip()

    return ""


def _count_files_in_diff(diff_text: str) -> int:
    """统计 diff 中涉及的文件数（按 diff --git 或 --- 行计数）。"""
    git_headers = re.findall(r"^diff --git", diff_text, re.MULTILINE)
    if git_headers:
        return len(git_headers)
    file_headers = re.findall(r"^--- ", diff_text, re.MULTILINE)
    return len(file_headers) if file_headers else 0


def _extract_summary_line(text: str) -> str:
    """从文本中提取变更摘要（标记块之前的第一段文字）。"""
    # 取标记前的文本
    idx = text.find(_DIFFSET_START)
    if idx > 0:
        text = text[:idx]
    # 取前几行非空文本作为摘要
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return lines[0] if lines else ""


# ─── ReviewReport 解析 ───


def parse_review_report(text: str, task_id: str = "") -> ReviewReport | None:
    """从 LLM 文本回复中提取 ReviewReport。

    Args:
        text: Reviewer Agent 的完整文本回复
        task_id: 对应的子任务 ID

    Returns:
        ReviewReport 实例，解析失败返回 None
    """
    # 方案 A：JSON 标记解析
    report = _try_parse_review_json(text, task_id)
    if report is not None:
        logger.debug("ReviewReport parsed via JSON markers")
        return report

    # 方案 B：启发式解析
    report = _heuristic_parse_review(text, task_id)
    if report is not None:
        logger.debug("ReviewReport parsed via heuristic fallback")
        return report

    logger.warning("Failed to parse ReviewReport from text (length=%d)", len(text))
    return None


def _try_parse_review_json(text: str, task_id: str) -> ReviewReport | None:
    """尝试从 ---REVIEW_START--- / ---REVIEW_END--- 标记间提取 JSON。"""
    pattern = re.compile(
        re.escape(_REVIEW_START) + r"\s*(.*?)\s*" + re.escape(_REVIEW_END),
        re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return None

    raw = match.group(1).strip()
    raw = _strip_code_fence(raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = _lenient_json_parse(raw)
        if data is None:
            return None

    verdict = data.get("overall_verdict") or data.get("verdict") or VERDICT_APPROVED
    # 规范化 verdict
    verdict = _normalize_verdict(verdict)

    file_reviews_data = data.get("file_reviews") or []
    file_reviews: list[FileReview] = []
    for fr in file_reviews_data:
        if not isinstance(fr, dict):
            continue
        file_reviews.append(FileReview(
            file_path=fr.get("file_path") or fr.get("path") or "",
            issues=fr.get("issues") or [],
            suggestions=fr.get("suggestions") or [],
            severity=_normalize_severity(fr.get("severity", SEVERITY_INFO)),
        ))

    should_retry = data.get("should_retry")
    if should_retry is None:
        should_retry = verdict == VERDICT_NEEDS_CHANGES

    return ReviewReport(
        task_id=data.get("task_id") or task_id,
        overall_verdict=verdict,
        file_reviews=file_reviews,
        summary=data.get("summary") or "",
        should_retry=should_retry,
    )


def _heuristic_parse_review(text: str, task_id: str) -> ReviewReport | None:
    """启发式解析审查报告。

    检测关键词判断总体判定，按文件路径模式拆分逐文件意见。
    """
    text_lower = text.lower()

    # 判定总体结论（优先级：rejected > needs_changes > approved）
    # 先检查最严重的判定，避免"拒绝...通过测试"被误判为 approved
    if any(kw in text_lower for kw in ("拒绝", "驳回", "reject", "rejected")):
        verdict = VERDICT_REJECTED
        should_retry = True
    elif any(kw in text_lower for kw in ("需要修改", "需修改", "needs_changes", "needs change", "建议修改")):
        verdict = VERDICT_NEEDS_CHANGES
        should_retry = True
    elif any(kw in text_lower for kw in ("批准", "通过", "approve", "approved", "lgtm")):
        verdict = VERDICT_APPROVED
        should_retry = False
    else:
        # 无法判定时默认通过
        verdict = VERDICT_APPROVED
        should_retry = False

    # 按文件路径拆分审查意见
    file_reviews: list[FileReview] = []
    # 匹配文件路径行：`文件：path.py` 或 `[path.py]` 或 `path.py:`
    file_pattern = re.compile(
        r"(?:文件[：:]\s*|[\[]\s*)([\w./\\]+\.\w+)(?:\s*[\]]|[：:])",
        re.MULTILINE,
    )
    file_matches = file_pattern.finditer(text)

    for match in file_matches:
        file_path = match.group(1)
        # 取该文件路径之后到下一个文件路径之前的文本
        start = match.end()
        next_match = file_pattern.search(text, start)
        end = next_match.start() if next_match else len(text)
        section = text[start:end].strip()

        issues = []
        suggestions = []
        severity = SEVERITY_INFO

        for line in section.splitlines():
            line = line.strip()
            if not line:
                continue
            line_lower = line.lower()
            if any(kw in line_lower for kw in ("blocker", "严重", "阻断", "必须")):
                severity = SEVERITY_BLOCKER
                issues.append(line)
            elif any(kw in line_lower for kw in ("warning", "警告", "建议", "should")):
                if severity != SEVERITY_BLOCKER:
                    severity = SEVERITY_WARNING
                suggestions.append(line)
            elif line.startswith(("-", "*", "•")):
                issues.append(line.lstrip("-*• "))

        if file_path:
            file_reviews.append(FileReview(
                file_path=file_path,
                issues=issues,
                suggestions=suggestions,
                severity=severity,
            ))

    return ReviewReport(
        task_id=task_id,
        overall_verdict=verdict,
        file_reviews=file_reviews,
        summary=_extract_summary_line(text),
        should_retry=should_retry,
    )


# ─── 辅助函数 ───


def _strip_code_fence(text: str) -> str:
    """去除 ```json ... ``` 或 ``` ... ``` 包裹。"""
    text = text.strip()
    if text.startswith("```"):
        # 去掉第一行（```json 或 ```）
        lines = text.splitlines()
        if len(lines) >= 2:
            text = "\n".join(lines[1:])
            # 去掉末尾的 ```
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3].rstrip()
    return text


def _lenient_json_parse(text: str) -> dict | None:
    """宽松 JSON 解析：尝试修复常见格式问题后解析。"""
    # 尝试去除尾部逗号
    cleaned = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 尝试提取第一个 { ... } 块
    brace_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _normalize_verdict(verdict: str) -> str:
    """规范化审查判定值。"""
    v = verdict.lower().strip()
    if v in ("approved", "approve", "通过", "批准", "lgtm"):
        return VERDICT_APPROVED
    if v in ("needs_changes", "needs change", "needs_changes", "需修改", "需要修改", "建议修改"):
        return VERDICT_NEEDS_CHANGES
    if v in ("rejected", "reject", "拒绝", "驳回"):
        return VERDICT_REJECTED
    return VERDICT_APPROVED


def _normalize_severity(severity: str) -> str:
    """规范化严重级别。"""
    s = severity.lower().strip()
    if s in ("blocker", "严重", "阻断", "critical", "must"):
        return SEVERITY_BLOCKER
    if s in ("warning", "警告", "warn", "should"):
        return SEVERITY_WARNING
    return SEVERITY_INFO
