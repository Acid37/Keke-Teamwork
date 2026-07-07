from backend.types import ToolSchema, ToolResult, ToolContext


class Tool:
    """Tool base class. Subclasses define name, description, parameters as class attributes."""

    name: str = ""
    description: str = ""
    parameters: dict = {}

    def __init__(self, context: ToolContext):
        self._ctx = context

    async def execute(self, **kwargs) -> ToolResult:
        raise NotImplementedError

    def to_schema(self) -> ToolSchema:
        return ToolSchema(self.name, self.description, self.parameters)
