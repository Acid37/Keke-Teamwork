"""Agent orchestration layer.

Phase B starts here: keep the current single-Agent behavior intact, but move
the execution workflow behind an orchestrator boundary so delegate/handoff and
parallel researchers can be added without further bloating ws_server.py.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from backend.agent import Agent
from backend.agent_store import AgentStore
from backend.config import AppConfig
from backend.llm.client import LLMClient
from backend.safety.file_staging import FileStagingArea
from backend.safety.permission import PermissionManager
from backend.tools import ALL_TOOLS, resolve_tools
from backend.types import Phase, Session, ToolContext

logger = logging.getLogger(__name__)

Broadcast = Callable[[str, dict], Awaitable[None]]


class AgentOrchestrator:
    """Coordinates Agent execution for a session.

    The first implementation intentionally preserves the existing single-Agent
    path. The important change is ownership: WebSocketServer no longer needs to
    know how to build agents, staging, permission managers, and callbacks.
    """

    def __init__(
        self,
        *,
        config: AppConfig,
        llm: LLMClient,
        agent_store: AgentStore,
        permission_managers: dict[str, PermissionManager],
    ):
        self._config = config
        self._llm = llm
        self._agent_store = agent_store
        self._permission_managers = permission_managers

    async def run_user_message(
        self,
        *,
        session: Session,
        text: str,
        agent_id: str = "main",
        broadcast: Broadcast,
    ) -> None:
        """Process one user message through the orchestration layer."""
        session.phase = Phase.THINKING
        session.last_active_at = time.time()

        # Add user message to history.
        session.messages.append({"role": "user", "content": text})
        if self._should_generate_title(session):
            session.title = self._generate_session_title(text, session.work_dir)

        # Phase B placeholder: solo mode keeps current behavior explicit.
        if session.solo_mode:
            agent_id = "main"

        agent_def = self._agent_store.get_agent(agent_id)
        if not agent_def:
            agent_def = self._agent_store.get_agent("main")
        if not agent_def:
            await broadcast("error", {
                "message": "No agent definitions available",
                "recoverable": True,
            })
            return

        effective_model = agent_def.model or self._config.main_model
        effective_provider = agent_def.provider or self._config.provider

        if agent_def.provider or agent_def.model:
            llm = LLMClient(
                provider=effective_provider,
                api_key=self._config.api_key,
                base_url=self._config.base_url,
                model=effective_model,
            )
        else:
            llm = self._llm

        agent_tools = resolve_tools(agent_def.tools) if agent_def.tools else ALL_TOOLS

        await broadcast("agent.status", {
            "phase": "thinking",
            "detail": "Processing...",
        })

        await broadcast("agent.started", {
            "agent_id": agent_def.agent_id,
            "agent_name": agent_def.name,
            "role": agent_def.role,
            "color": agent_def.color,
        })

        aid = agent_def.agent_id
        aname = agent_def.name
        arole = agent_def.role
        acolor = agent_def.color

        tool_call_ids: dict[str, list[str]] = {}

        async def broadcast_tool_call(name: str, args: dict):
            call_id = uuid4().hex[:8]
            tool_call_ids.setdefault(name, []).append(call_id)
            await broadcast("tool.call", {
                "name": name,
                "args": args,
                "stage": "running",
                "source": arole,
                "call_id": call_id,
                "agent_id": aid,
            })

        async def broadcast_tool_result(name: str, success: bool, result: str):
            call_id = (
                tool_call_ids.get(name, []).pop(0)
                if tool_call_ids.get(name)
                else uuid4().hex[:8]
            )
            await broadcast("tool.call", {
                "name": name,
                "args": {"result": result},
                "stage": "completed",
                "source": arole,
                "call_id": call_id,
                "success": success,
                "agent_id": aid,
            })

        staging = FileStagingArea(session.work_dir)
        permission_mgr = PermissionManager(
            broadcast=broadcast,
            yolo_mode=session.yolo_mode,
        )
        self._permission_managers[session.id] = permission_mgr

        tool_context = ToolContext(
            session=session,
            work_dir=session.work_dir,
            staging=staging,
            permission_mgr=permission_mgr,
            broadcast=broadcast,
            interrupt_check=lambda: session.interrupt_requested,
        )

        agent = Agent(
            llm,
            model=effective_model,
            temperature=agent_def.temperature,
            max_tool_rounds=agent_def.max_tool_rounds,
            agent_id=aid,
            role=arole,
            agent_name=aname,
        )
        agent.tools = agent_tools
        agent.system_prompt = (
            agent_def.system_prompt
            if agent_def.system_prompt
            else self._build_system_prompt(session)
        )

        try:
            result = await agent.run(
                user_message=text,
                tool_context=tool_context,
                existing_messages=session.messages[:-1],
                max_tool_rounds=agent_def.max_tool_rounds,
                on_text=lambda t: broadcast("agent.text", {
                    "text": t,
                    "source": arole,
                    "is_final": False,
                    "agent_id": aid,
                    "agent_name": aname,
                    "role": arole,
                    "color": acolor,
                }),
                on_thinking=lambda t: broadcast("agent.thinking", {
                    "text": t,
                    "source": arole,
                    "agent_id": aid,
                    "agent_name": aname,
                }),
                on_tool_call=broadcast_tool_call,
                on_tool_result=broadcast_tool_result,
            )

            session.messages = result.messages
            session.usage_total += result.usage
            session.phase = Phase.READY

            commit = staging.commit()
            if commit.files_changed and session.auto_review:
                await broadcast("files.changed", {
                    "summary": commit.summary,
                    "combined_diff": commit.combined_diff,
                    "files": [
                        {
                            "path": str(diff.path),
                            "action": diff.action,
                            "diff_text": diff.diff_text,
                        }
                        for diff in commit.diffs
                    ],
                })

            await broadcast("agent.completed", {
                "agent_id": aid,
                "agent_name": aname,
                "role": arole,
                "summary": result.text[:200] if result.text else "",
                "usage": {
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                },
            })

            await broadcast("agent.text", {
                "text": "",
                "source": arole,
                "is_final": True,
                "agent_id": aid,
                "agent_name": aname,
            })

            await broadcast("agent.status", {
                "phase": "ready",
                "detail": None,
            })

        except asyncio.CancelledError:
            staging.rollback()
            session.phase = Phase.READY
            await broadcast("agent.text", {
                "text": "\n\n[被用户中断]",
                "source": arole,
                "is_final": True,
                "agent_id": aid,
                "agent_name": aname,
            })
            await broadcast("agent.status", {
                "phase": "ready",
                "detail": "Interrupted",
            })

        except Exception as e:
            staging.rollback()
            logger.exception("Agent execution failed")
            session.phase = Phase.ERROR
            await broadcast("error", {
                "message": f"Agent error: {e}",
                "recoverable": True,
            })
            await broadcast("agent.status", {
                "phase": "error",
                "detail": str(e),
            })

        finally:
            self._permission_managers.pop(session.id, None)

    @staticmethod
    def _should_generate_title(session: Session) -> bool:
        """Only replace placeholder titles, never project/user-provided names."""
        import re

        title = (session.title or "").strip()
        return not title or bool(re.fullmatch(r"Session \d{2}:\d{2}", title))

    @staticmethod
    def _generate_session_title(text: str, work_dir) -> str:
        """Create a short deterministic title from the first user message."""
        import re

        cleaned = re.sub(r"[`*_#>\[\](){}]", "", text).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"^(请|帮我|麻烦|能不能|可以)?\s*", "", cleaned)
        if not cleaned:
            cleaned = work_dir.name or "新会话"
        if len(cleaned) > 24:
            cleaned = cleaned[:24].rstrip() + "…"
        return cleaned

    @staticmethod
    def _build_system_prompt(session: Session) -> str:
        """Build the default system prompt for the main agent."""
        return f"""You are a helpful coding assistant. You help users with software development tasks.

You have access to the following tools:
- read_file: Read file contents with line numbers
- write_file: Create or overwrite a file
- edit_file: Search and replace text in a file
- run_console: Execute shell commands
- grep_search: Search file contents with regex
- find_files: Find files by name pattern
- list_directory: List directory contents in tree format

Working directory: {session.work_dir}

Guidelines:
- Read files before modifying them to understand context
- Use edit_file for small changes (preserves surrounding code)
- Use write_file only for new files or complete rewrites
- Run tests after making changes when possible
- Explain your reasoning before making changes
- If unsure about the project structure, use list_directory and grep_search first
"""