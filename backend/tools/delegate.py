from backend.types import ToolResult
from backend.tools.base import Tool, ToolCategory


class DelegateTool(Tool):
    """Delegate a focused subtask to another configured agent."""

    name = "delegate_agent"
    category = ToolCategory.coding
    description = (
        "Delegate a focused read-only research subtask to another agent and return "
        "its summarized findings. First version is intended for researcher agents."
    )
    parameters = {
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "Target agent id, usually 'researcher'.",
                "default": "researcher",
            },
            "task": {
                "type": "string",
                "description": "Focused subtask for the target agent.",
            },
            "context": {
                "type": "string",
                "description": "Optional context, constraints, relevant files, or current findings.",
                "default": "",
            },
        },
        "required": ["agent_id", "task"],
    }

    async def execute(self, **kwargs) -> ToolResult:
        runner = getattr(self._ctx, "delegate_runner", None)
        if not runner:
            return (False, "Delegation is not available in this context")

        agent_id = kwargs.get("agent_id") or "researcher"
        task = (kwargs.get("task") or "").strip()
        context = (kwargs.get("context") or "").strip()

        if not task:
            return (False, "task is required")

        try:
            result = await runner(agent_id=agent_id, task=task, context=context)
            return (True, result)
        except Exception as e:
            return (False, f"Delegation failed: {e}")