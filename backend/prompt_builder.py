"""系统提示词构建。"""

from __future__ import annotations

from backend.types import AgentDefinition, Phase, Session


def _project_context_block(session: Session, *, compact: bool = False) -> str:
    """从 session.project_context 生成提示词注入段落。

    compact=True 时只注入语言/框架摘要，不包含目录树（用于委派/handoff Agent）。
    """
    ctx = session.project_context
    if not ctx or not isinstance(ctx, dict):
        return ""
    summary = ctx.get("summary", "")
    if not summary:
        return ""
    if compact:
        # 精简版：只保留语言和框架行
        lines = summary.splitlines()
        compact_lines = [
            line for line in lines
            if line.startswith("语言：") or line.startswith("框架")
        ]
        if compact_lines:
            return "\n项目背景：" + "；".join(compact_lines) + "\n"
        return ""
    return f"\n项目背景：\n{summary}\n"


def build_system_prompt(session: Session, agent_def: AgentDefinition | None = None) -> str:
    """构建 main Agent / 通用 Assistant 的默认系统提示词。"""
    role = agent_def.role if agent_def else "assistant"
    context_block = _project_context_block(session)
    tools_block = _tools_block(agent_def)

    base = _ROLE_BASE_PROMPTS.get(role, _ROLE_BASE_PROMPTS["assistant"])
    return base.format(work_dir=session.work_dir, context_block=context_block, tools_block=tools_block)


_ROLE_BASE_PROMPTS: dict[str, str] = {
    "assistant": (
        "你是一个乐于助人的编程助手，帮助用户完成软件开发任务。\n"
        "\n"
        "{tools_block}"
        "工作目录：{work_dir}{context_block}\n"
        "行为准则：\n"
        "- 修改文件前先读取，了解上下文\n"
        "- 小改动使用 edit_file（保留周围代码）\n"
        "- 仅在创建新文件或完全重写时使用 write_file\n"
        "- 修改后尽可能运行测试验证\n"
        "- 修改前先解释你的思路\n"
        "- 不确定项目结构时，先用 list_directory 和 grep_search 探索\n"
    ),
    "planner": (
        "你是一个方案规划师，负责分析用户需求并拆解为可执行的任务计划。\n"
        "你从不直接写代码——你的职责是产出清晰、可操作的结构化计划。\n"
        "\n"
        "{tools_block}"
        "工作目录：{work_dir}{context_block}\n"
        "行为准则：\n"
        "- 先用 grep_search / list_directory 全面了解项目现状\n"
        "- 分析需求涉及哪些文件、模块、接口\n"
        "- 将任务拆解为独立、可验证的子任务清单\n"
        "- 每个子任务标注涉及的文件、预估影响范围、验收标准\n"
        "- 如需进一步调研，使用 delegate_agent 委派给只读 Agent\n"
        "- 输出格式：先概述方案，再列出 1. 2. 3. ... 有序子任务\n"
    ),
    "coder": (
        "你是一个编码专家，专注于将明确的子任务转化为高质量代码实现。\n"
        "你不做需求分析或方案规划——你的职责是高效、准确地完成编码任务。\n"
        "\n"
        "{tools_block}"
        "工作目录：{work_dir}{context_block}\n"
        "行为准则：\n"
        "- 修改前先读取相关文件\n"
        "- 小改动使用 edit_file，新文件使用 write_file\n"
        "- 保持与项目现有风格一致\n"
        "- 修改后运行相关测试验证\n"
        "- 总结所做的变更、验证结果和残留风险\n"
        "- 不要做范围外的工作——只完成委派给你的具体任务\n"
    ),
    "reviewer": (
        "你是一个代码审查员，负责检查代码变更的质量、安全性和一致性。\n"
        "你不写代码、不执行有副作用的命令——你的职责是审查和反馈。\n"
        "\n"
        "{tools_block}"
        "工作目录：{work_dir}{context_block}\n"
        "行为准则：\n"
        "- 仔细阅读变更涉及的文件\n"
        "- 检查：逻辑正确性、边界条件、错误处理、安全风险\n"
        "- 检查：代码风格是否与项目一致\n"
        "- 检查：是否有遗漏的测试、文档更新\n"
        "- 使用 git diff / git log 等只读命令查看变更\n"
        "- 输出：逐文件审查意见 + 总体评价 + 改进建议\n"
        "- 不要修改任何文件\n"
    ),
}


def _tools_block(agent_def: AgentDefinition | None) -> str:
    """从 Agent 工具列表生成工具说明段落。"""
    if not agent_def or not agent_def.tools:
        return ""
    tool_descriptions = {
        "read_file": "read_file: 读取文件内容（带行号）",
        "write_file": "write_file: 创建或覆盖文件",
        "edit_file": "edit_file: 在文件中搜索并替换文本",
        "run_console": "run_console: 执行 shell 命令",
        "grep_search": "grep_search: 使用正则搜索文件内容",
        "find_files": "find_files: 按名称模式查找文件",
        "list_directory": "list_directory: 以树形结构列出目录内容",
        "delegate_agent": "delegate_agent: 委派子任务给其他 Agent",
    }
    lines = ["你可以使用以下工具："]
    for name in agent_def.tools:
        if name in tool_descriptions:
            lines.append(f"- {tool_descriptions[name]}")
    lines.append("")
    return "\n".join(lines)


def build_delegated_system_prompt(session: Session, agent_def: AgentDefinition) -> str:
    """构建只读委派 Agent 的默认提示词。"""
    context_block = _project_context_block(session, compact=True)
    return f"""你是 {agent_def.name}，一个只读的委派编程助手。

你的职责是为其他 Agent 调研聚焦的子任务。你可以使用读/搜索/列表工具检查本地项目，
但不能修改文件、执行 shell 命令，或做与任务无关的广泛操作。

工作目录：{session.work_dir}{context_block}
行为准则：
- 严格聚焦在委派任务上。
- 尽可能引用相关文件和符号。
- 偏好简洁的发现而非冗长的解释。
- 明确说明不确定性和缺失信息。
- 不要尝试编辑文件或执行命令。
"""


def build_handoff_system_prompt(session: Session, agent_def: AgentDefinition) -> str:
    """构建串行 handoff Agent 的默认提示词。"""
    context_block = _project_context_block(session, compact=True)
    return f"""你是 {agent_def.name}，一个委派的 {agent_def.role} Agent。

你的职责是为父 Agent 完成一个聚焦的 handoff 任务。
你可以使用角色分配的工具，但所有文件变更必须通过工具/staging 边界，
shell 命令必须遵守配置的审批规则。不要将工作委派给其他 Agent。

工作目录：{session.work_dir}{context_block}
行为准则：
- 严格在委派任务和给定上下文中工作。
- 偏好小的、可审查的文件变更。
- 编辑前先读取相关文件。
- 仅在有用时运行聚焦的验证命令。
- 总结所做的变更、验证的内容以及任何残留风险。
"""


# ─── 阶段感知提示词注入 ───


def _repo_map_block(session: Session) -> str:
    """从 session.repo_map 生成项目结构地图注入段落。"""
    repo_map = getattr(session, "repo_map", None)
    if not repo_map:
        return ""
    return f"\n项目结构地图：\n{repo_map}\n"


def _completed_tasks_block(session: Session) -> str:
    """构建已完成任务摘要，供 coder/reviewer 了解前序进度。"""
    ws = session.workflow_state
    if ws is None or ws.task_list is None or not ws.completed_tasks:
        return ""
    tl = ws.task_list
    lines = [f"已完成的子任务（{len(ws.completed_tasks)}/{tl.total_count}）："]
    for tid in ws.completed_tasks:
        # 从 task_list 中查找标题
        task = next((t for t in tl.tasks if t.id == tid), None)
        title = task.title if task else tid
        lines.append(f"  - {tid}: {title}")
    return "\n" + "\n".join(lines) + "\n"


def _plan_overview_block(session: Session) -> str:
    """注入 planner 产出的方案概述和风险，供 coder/reviewer 理解全局目标。"""
    ws = session.workflow_state
    if ws is None or ws.task_list is None:
        return ""
    tl = ws.task_list
    parts: list[str] = []
    if tl.overview:
        parts.append(f"方案概述：{tl.overview}")
    if tl.risks:
        parts.append("风险提示：" + "；".join(tl.risks))
    if not parts:
        return ""
    return "\n全局上下文：\n" + "\n".join(parts) + "\n"


def build_phase_prompt(
    session: Session,
    agent_def: AgentDefinition | None,
    phase: Phase,
) -> str:
    """构建阶段感知的系统提示词。

    在 base system prompt 之上，根据当前工作流阶段注入上下文：
    - 所有阶段：注入 repo_map（项目结构地图）
    - PLANNING：引导产出结构化 TaskList
    - CODING：注入当前 SubTask 详情 + planner 方案概述 + 已完成任务
    - REVIEWING：注入待审查的 DiffSet + 任务上下文 + 已完成任务
    - FEEDBACK：注入审查反馈（供 coder 重试）

    非工作流阶段或缺失 workflow_state 时，返回 base prompt + repo_map。
    """
    base = build_system_prompt(session, agent_def)

    # 所有工作流阶段都注入 repo_map
    repo_block = _repo_map_block(session)
    if repo_block:
        base += repo_block

    ws = session.workflow_state

    if phase == Phase.PLANNING:
        base += (
            "\n\n当前阶段：需求分析与任务规划。\n"
            "请将用户需求拆解为结构化的子任务计划。\n"
            "输出格式要求：先给出方案概述，再列出编号子任务清单。\n"
            "每个子任务需包含：标题、详细描述、涉及文件、验收标准。\n"
            "如果识别到风险或依赖，也请一并列出。\n"
        )
        return base

    if phase == Phase.CODING:
        if ws is None or ws.current_task is None:
            return base

        # 阶段间上下文传递：planner 产出 → coder 消费
        plan_block = _plan_overview_block(session)
        if plan_block:
            base += plan_block

        completed_block = _completed_tasks_block(session)
        if completed_block:
            base += completed_block

        task = ws.current_task
        task_block = (
            f"\n\n当前阶段：编码实现。\n"
            f"当前任务：{task.title}\n"
            f"任务描述：{task.description}\n"
        )
        if task.files_involved:
            task_block += f"涉及文件：{', '.join(task.files_involved)}\n"
        if task.acceptance_criteria:
            task_block += f"验收标准：{task.acceptance_criteria}\n"
        if session.coder_guidance_queue:
            task_block += (
                "\n审查反馈（请根据以下反馈修改）：\n"
                + "\n---\n".join(session.coder_guidance_queue)
                + "\n"
            )
        base += task_block
        return base

    if phase == Phase.REVIEWING:
        if ws is None or ws.current_diff_set is None:
            return base

        # 阶段间上下文传递：planner 方案概述 + 当前任务上下文
        plan_block = _plan_overview_block(session)
        if plan_block:
            base += plan_block

        completed_block = _completed_tasks_block(session)
        if completed_block:
            base += completed_block

        # 当前任务上下文（让 reviewer 知道在审查什么任务）
        if ws.current_task:
            base += (
                f"\n当前审查的任务：{ws.current_task.title}\n"
                f"任务描述：{ws.current_task.description}\n"
            )
            if ws.current_task.acceptance_criteria:
                base += f"验收标准：{ws.current_task.acceptance_criteria}\n"

        diff = ws.current_diff_set
        diff_text = diff.combined_diff[:8000] if diff.combined_diff else ""
        review_block = (
            f"\n\n当前阶段：代码审查。\n"
            f"变更摘要：{diff.summary}\n"
            f"变更文件数：{diff.files_changed}\n"
        )
        if diff_text:
            review_block += f"\n待审查变更（diff）：\n{diff_text}\n"
        if diff.test_results:
            review_block += f"\n测试结果：\n{diff.test_results}\n"
        base += review_block
        return base

    if phase == Phase.FEEDBACK:
        if ws is None or ws.last_review_report is None:
            return base

        # FEEDBACK 阶段也注入已完成任务上下文
        completed_block = _completed_tasks_block(session)
        if completed_block:
            base += completed_block

        report = ws.last_review_report
        feedback_block = (
            f"\n\n当前阶段：根据审查反馈修改代码。\n"
            f"审查摘要：{report.summary}\n"
        )
        for fr in report.file_reviews:
            if fr.issues:
                feedback_block += (
                    f"\n  [{fr.file_path}] ({fr.severity})\n"
                    f"  问题：{'; '.join(fr.issues)}\n"
                )
            if fr.suggestions:
                feedback_block += (
                    f"  建议：{'; '.join(fr.suggestions)}\n"
                )
        base += feedback_block
        return base

    return base