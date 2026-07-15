from backend.types import ToolResult
from backend.tools.base import Tool, ToolCategory


class DelegateTool(Tool):
    """将聚焦子任务委派给其他已配置的 Agent。"""

    name = "delegate_agent"
    category = ToolCategory.coding
    description = (
        "将聚焦的子任务委派给其他 Agent，并返回其汇总结论。"
        "只读 Agent 走并行研究路径，有写工具的 Agent 走安全 handoff 路径。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "目标 Agent 的 ID，通常为 'researcher' 或 'coder'。",
                "default": "researcher",
            },
            "task": {
                "type": "string",
                "description": "委派给目标 Agent 的聚焦子任务。",
            },
            "context": {
                "type": "string",
                "description": "可选的上下文、约束、相关文件或当前发现。",
                "default": "",
            },
        },
        "required": ["agent_id", "task"],
    }

    async def execute(self, **kwargs) -> ToolResult:
        runner = getattr(self._ctx, "delegate_runner", None)
        if not runner:
            return (False, "当前上下文不支持委派")

        # Check agent-level permission: allow_delegation
        perms = getattr(self._ctx, "agent_permissions", None)
        if perms and not getattr(perms, "allow_delegation", True):
            return (False, "当前 Agent 不允许委派任务给其他 Agent")

        agent_id = kwargs.get("agent_id") or "researcher"
        task = (kwargs.get("task") or "").strip()
        context = (kwargs.get("context") or "").strip()

        if not task:
            return (False, "task 参数是必需的")

        try:
            result = await runner(agent_id=agent_id, task=task, context=context)
            return (True, result)
        except Exception as e:
            return (False, f"委派失败: {e}")