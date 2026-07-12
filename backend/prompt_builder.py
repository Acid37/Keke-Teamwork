"""系统提示词构建。"""

from __future__ import annotations

from backend.types import AgentDefinition, Session


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


def build_system_prompt(session: Session) -> str:
    """构建 main Agent 的默认系统提示词。"""
    context_block = _project_context_block(session)
    return f"""你是一个乐于助人的编程助手，帮助用户完成软件开发任务。

你可以使用以下工具：
- read_file: 读取文件内容（带行号）
- write_file: 创建或覆盖文件
- edit_file: 在文件中搜索并替换文本
- run_console: 执行 shell 命令
- grep_search: 使用正则搜索文件内容
- find_files: 按名称模式查找文件
- list_directory: 以树形结构列出目录内容

工作目录：{session.work_dir}{context_block}
行为准则：
- 修改文件前先读取，了解上下文
- 小改动使用 edit_file（保留周围代码）
- 仅在创建新文件或完全重写时使用 write_file
- 修改后尽可能运行测试验证
- 修改前先解释你的思路
- 不确定项目结构时，先用 list_directory 和 grep_search 探索
"""


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