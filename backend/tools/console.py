import asyncio
import os
from backend.types import ToolResult
from backend.tools.base import Tool


class ConsoleTool(Tool):
    """Execute shell commands."""

    name = "run_console"
    description = "Execute a shell command and return the output."
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default: 30)", "default": 30},
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
                        return (False, "Command denied by permission rules")
                    if perm_result == "needs_approval":
                        approved = await self._ctx.permission_mgr.request_approval(command)
                        if not approved:
                            return (False, "Command denied by user or approval timed out")
                except Exception as e:
                    return (False, f"Command approval failed: {e}")

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
                    return (False, f"Command timed out after {timeout} seconds")

                # Decode output
                output = stdout.decode("utf-8", errors="replace")

                # Truncate output if too long
                console_max_output = 200
                lines = output.split("\n")
                if len(lines) > console_max_output:
                    lines = lines[:console_max_output]
                    lines.append(f"... (output truncated, {len(output.split(chr(10))) - console_max_output} more lines)")
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
                return (False, f"Error executing command: {e}")

        except Exception as e:
            return (False, f"Error: {e}")
