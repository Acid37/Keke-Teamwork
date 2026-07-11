import asyncio
import os
from backend.types import ToolResult
from backend.tools.base import Tool, ToolCategory


class ConsoleTool(Tool):
    """执行 shell 命令。"""

    name = "run_console"
    category = ToolCategory.shell
    description = "执行 shell 命令并返回输出。"
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的 shell 命令"},
            "timeout": {"type": "integer", "description": "超时时间（秒，默认 30）", "default": 30},
        },
        "required": ["command"],
    }

    async def execute(self, **kwargs) -> ToolResult:
        try:
            command = kwargs["command"]
            timeout = kwargs.get("timeout", 30)

            # Check permission if permission_mgr available
            if self._ctx.permission_mgr:
                try:
                    perm_result = self._ctx.permission_mgr.check(command)
                    if perm_result == "deny":
                        return (False, "命令被权限规则拒绝")
                    if perm_result == "needs_approval":
                        approved = await self._ctx.permission_mgr.request_approval(command)
                        if not approved:
                            return (False, "命令被用户拒绝或审批超时")
                except Exception as e:
                    return (False, f"命令审批失败: {e}")

            # Execute command
            try:
                process = await asyncio.create_subprocess_shell(
                    command,
                    cwd=str(self._ctx.work_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env=os.environ.copy(),
                )

                # Wait for completion with timeout
                try:
                    stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                    return (False, f"命令执行超时（{timeout} 秒）")

                # Decode output
                output = stdout.decode("utf-8", errors="replace")

                # Truncate output if too long
                console_max_output = 200
                lines = output.split("\n")
                if len(lines) > console_max_output:
                    lines = lines[:console_max_output]
                    lines.append(f"... (输出已截断，省略 {len(output.split(chr(10))) - console_max_output} 行)")
                    output = "\n".join(lines)

                # Broadcast if callback available
                if self._ctx.broadcast:
                    try:
                        await self._ctx.broadcast("console.output", {
                            "command": command, "output": output,
                        })
                    except Exception:
                        pass  # Non-critical

                # Return based on return code
                success = process.returncode == 0
                return (success, output)

            except Exception as e:
                return (False, f"执行命令错误: {e}")

        except Exception as e:
            return (False, f"错误: {e}")
