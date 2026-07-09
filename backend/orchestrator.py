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
from backend.types import AgentDefinition, AgentResult, MergedResearchResult, ParallelResearchResult, Phase, Session, ToolContext

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

        agent_def = self._resolve_agent(agent_id)
        if not agent_def:
            await broadcast("error", {
                "message": "No agent definitions available",
                "recoverable": True,
            })
            return

        effective_model = self._resolve_model(agent_def)
        effective_provider = agent_def.provider or self._config.provider
        llm = self._create_llm_for_agent(agent_def, effective_model, effective_provider)

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

        if self._should_run_parallel_research(session, agent_def):
            try:
                await self.run_parallel_research(
                    session=session,
                    task=text,
                    context="用户消息进入主 Agent 前的只读研究。",
                    agent_id=agent_def.agent_id,
                    broadcast=broadcast,
                )
            except Exception as exc:
                logger.exception("Parallel research preflight failed")
                await broadcast("research.failed", {
                    "agent_id": "parallel-research",
                    "agent_name": "Parallel Research",
                    "role": "researcher",
                    "parent_agent_id": agent_def.agent_id,
                    "task": text,
                    "text": "",
                    "timed_out": False,
                    "error": str(exc),
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
            delegate_runner=lambda **kwargs: self._run_delegated_agent(
                session=session,
                broadcast=broadcast,
                parent_agent_id=aid,
                **kwargs,
            ),
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

    async def run_parallel_entry(
        self,
        *,
        session: Session,
        task: str,
        context: str = "",
        agent_id: str = "main",
        broadcast: Broadcast,
        timeout: float | None = None,
        max_workers: int | None = None,
    ) -> list[ParallelResearchResult]:
        """兼容入口：运行一次只读并行研究。优先使用 run_parallel_research。"""
        return await self.run_parallel_research(
            session=session,
            task=task,
            context=context,
            agent_id=agent_id,
            broadcast=broadcast,
            timeout=timeout,
            max_workers=max_workers,
        )

    async def run_parallel_research(
        self,
        *,
        session: Session,
        task: str,
        context: str = "",
        agent_id: str = "main",
        broadcast: Broadcast,
        timeout: float | None = None,
        max_workers: int | None = None,
    ) -> list[ParallelResearchResult]:
        """面向会话流程的只读并行研究入口。"""
        agent_def = self._resolve_agent(agent_id)
        if not agent_def:
            return []
        results = await self.run_parallel_researchers(
            session=session,
            broadcast=broadcast,
            agent_def=agent_def,
            task=task,
            context=context,
            timeout=timeout,
            max_workers=max_workers or self._config.max_parallel_researchers,
        )
        merged = self.merge_parallel_research_results(results)
        await broadcast("research.completed", {
            "parent_agent_id": agent_def.agent_id,
            "task": task,
            "merged_text": merged.text,
            "successful_sources": merged.successful_sources,
            "timed_out_sources": merged.timed_out_sources,
            "errored_sources": merged.errored_sources,
            "result_count": len(results),
        })
        return results

    async def run_parallel_researchers(
        self,
        *,
        session: Session,
        broadcast: Broadcast,
        agent_def: AgentDefinition,
        task: str,
        context: str = "",
        timeout: float | None = None,
        max_workers: int = 3,
    ) -> list[ParallelResearchResult]:
        """并发运行可用的 researcher Agent，且只允许只读工具。"""
        max_workers = max(1, max_workers)
        candidates = [
            candidate
            for candidate in self._agent_store.list_agents()
            if candidate.role == "researcher" and candidate.agent_id != agent_def.agent_id
        ]
        if not candidates and agent_def.role == "researcher":
            candidates = [agent_def]

        semaphore = asyncio.Semaphore(max_workers)

        async def run_one(researcher: AgentDefinition) -> ParallelResearchResult:
            async with semaphore:
                base_payload = {
                    "agent_id": researcher.agent_id,
                    "agent_name": researcher.name,
                    "role": researcher.role,
                    "parent_agent_id": agent_def.agent_id,
                    "task": task,
                }
                await broadcast("research.started", base_payload)
                try:
                    result_text = await asyncio.wait_for(
                        self._run_delegated_agent(
                            session=session,
                            broadcast=broadcast,
                            parent_agent_id=agent_def.agent_id,
                            agent_id=researcher.agent_id,
                            task=task,
                            context=context,
                        ),
                        timeout=timeout,
                    )
                    await broadcast("research.result", {
                        **base_payload,
                        "text": result_text,
                        "timed_out": False,
                        "error": None,
                    })
                    return ParallelResearchResult(
                        text=result_text,
                        metadata={
                            "source": researcher.agent_id,
                            "agent_name": researcher.name,
                            "role": researcher.role,
                            "timed_out": False,
                        },
                    )
                except asyncio.TimeoutError:
                    await broadcast("research.failed", {
                        **base_payload,
                        "text": "",
                        "timed_out": True,
                        "error": "timed out",
                    })
                    return ParallelResearchResult(
                        text="",
                        metadata={
                            "source": researcher.agent_id,
                            "agent_name": researcher.name,
                            "role": researcher.role,
                            "timed_out": True,
                        },
                        error="timed out",
                    )
                except Exception as exc:
                    await broadcast("research.failed", {
                        **base_payload,
                        "text": "",
                        "timed_out": False,
                        "error": str(exc),
                    })
                    return ParallelResearchResult(
                        text="",
                        metadata={
                            "source": researcher.agent_id,
                            "agent_name": researcher.name,
                            "role": researcher.role,
                            "timed_out": False,
                        },
                        error=str(exc),
                    )

        gathered = await asyncio.gather(
            *(run_one(researcher) for researcher in candidates),
            return_exceptions=True,
        )
        results: list[ParallelResearchResult] = []
        for item in gathered:
            if isinstance(item, ParallelResearchResult):
                results.append(item)
            elif isinstance(item, Exception):
                results.append(ParallelResearchResult(
                    text="",
                    metadata={"source": "unknown", "timed_out": False},
                    error=str(item),
                ))
        return results

    @staticmethod
    def merge_parallel_research_results(
        results: list[ParallelResearchResult],
    ) -> MergedResearchResult:
        """确定性合并 researcher 结果，不调用 LLM。"""
        successful_sections: list[str] = []
        successful_sources: list[str] = []
        timed_out_sources: list[str] = []
        errored_sources: list[str] = []

        for result in results:
            source = str(result.metadata.get("source") or "unknown")
            if result.metadata.get("timed_out"):
                timed_out_sources.append(source)
                continue
            if result.error:
                errored_sources.append(source)
                continue

            text = result.text.strip()
            if text:
                successful_sources.append(source)
                successful_sections.append(f"### {source}\n{text}")

        if successful_sections:
            merged_text = "\n\n".join(successful_sections)
        else:
            merged_text = "没有可合并的 researcher 结果。"

        status_lines: list[str] = []
        if timed_out_sources:
            status_lines.append("超时 researcher：" + ", ".join(timed_out_sources))
        if errored_sources:
            status_lines.append("异常 researcher：" + ", ".join(errored_sources))
        if status_lines:
            merged_text = merged_text + "\n\n---\n" + "\n".join(status_lines)

        return MergedResearchResult(
            text=merged_text,
            successful_sources=successful_sources,
            timed_out_sources=timed_out_sources,
            errored_sources=errored_sources,
        )

    async def _run_delegated_agent(
        self,
        *,
        session: Session,
        broadcast: Broadcast,
        parent_agent_id: str,
        agent_id: str,
        task: str,
        context: str = "",
    ) -> str:
        """运行一个委派子 Agent，并返回紧凑摘要。

        第一版刻意保持只读：即使 Agent 定义里包含更多权限，委派 Agent
        也只会拿到读文件、搜索和列目录工具。这样在明确 handoff 与冲突处理
        机制前，可以避免并发写入冲突。
        """
        agent_def = self._agent_store.get_agent(agent_id)
        if not agent_def:
            raise ValueError(f"Agent '{agent_id}' not found")
        if agent_def.agent_id == parent_agent_id:
            raise ValueError("An agent cannot delegate to itself")

        allowed_tools = [
            "read_file",
            "grep_search",
            "find_files",
            "list_directory",
        ]
        agent_tools = resolve_tools([
            name for name in agent_def.tools
            if name in allowed_tools
        ])
        if not agent_tools:
            agent_tools = resolve_tools(allowed_tools)

        effective_model = self._resolve_model(agent_def)
        effective_provider = agent_def.provider or self._config.provider
        llm = self._create_llm_for_agent(agent_def, effective_model, effective_provider)

        await broadcast("agent.started", {
            "agent_id": agent_def.agent_id,
            "agent_name": agent_def.name,
            "role": agent_def.role,
            "color": agent_def.color,
            "parent_agent_id": parent_agent_id,
            "delegated": True,
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
                "parent_agent_id": parent_agent_id,
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
                "parent_agent_id": parent_agent_id,
            })

        child_context = ToolContext(
            session=session,
            work_dir=session.work_dir,
            staging=None,
            permission_mgr=None,
            delegate_runner=None,
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
            else self._build_delegated_system_prompt(session, agent_def)
        )

        delegated_message = (
            f"[Delegated task from {parent_agent_id}]\n{task.strip()}\n\n"
            f"[Context]\n{context.strip() or '(none)'}\n\n"
            "Return concise findings, cite relevant files when possible, and do not modify files."
        )

        result = await agent.run(
            user_message=delegated_message,
            tool_context=child_context,
            existing_messages=None,
            max_tool_rounds=agent_def.max_tool_rounds,
            on_text=lambda t: broadcast("agent.text", {
                "text": t,
                "source": arole,
                "is_final": False,
                "agent_id": aid,
                "agent_name": aname,
                "role": arole,
                "color": acolor,
                "parent_agent_id": parent_agent_id,
            }),
            on_thinking=lambda t: broadcast("agent.thinking", {
                "text": t,
                "source": arole,
                "agent_id": aid,
                "agent_name": aname,
                "parent_agent_id": parent_agent_id,
            }),
            on_tool_call=broadcast_tool_call,
            on_tool_result=broadcast_tool_result,
        )

        session.usage_total += result.usage
        await broadcast("agent.completed", {
            "agent_id": aid,
            "agent_name": aname,
            "role": arole,
            "summary": result.text[:200] if result.text else "",
            "usage": {
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
            },
            "parent_agent_id": parent_agent_id,
            "delegated": True,
        })

        await broadcast("agent.text", {
            "text": "",
            "source": arole,
            "is_final": True,
            "agent_id": aid,
            "agent_name": aname,
            "parent_agent_id": parent_agent_id,
        })

        return self._format_delegate_result(agent_def, result)

    def _resolve_agent(self, agent_id: str) -> AgentDefinition | None:
        return self._agent_store.get_agent(agent_id) or self._agent_store.get_agent("main")

    def _should_run_parallel_research(
        self,
        session: Session,
        agent_def: AgentDefinition,
    ) -> bool:
        """判断当前用户消息是否应触发只读并行研究。"""
        if session.solo_mode or agent_def.role == "researcher":
            return False
        return any(
            candidate.role == "researcher" and candidate.agent_id != agent_def.agent_id
            for candidate in self._agent_store.list_agents()
        )

    def _resolve_model(self, agent_def: AgentDefinition) -> str:
        if agent_def.model:
            return agent_def.model
        if agent_def.role == "researcher" and self._config.research_model:
            return self._config.research_model
        if agent_def.role == "coder" and self._config.coder_model:
            return self._config.coder_model
        return self._config.main_model

    def _create_llm_for_agent(
        self,
        agent_def: AgentDefinition,
        effective_model: str,
        effective_provider: str,
    ) -> LLMClient:
        if agent_def.provider or agent_def.model or effective_model != self._config.main_model:
            return LLMClient(
                provider=effective_provider,
                api_key=self._config.api_key,
                base_url=self._config.base_url,
                model=effective_model,
            )
        return self._llm

    @staticmethod
    def _format_delegate_result(agent_def: AgentDefinition, result: AgentResult) -> str:
        text = (result.text or "").strip()
        if len(text) > 12_000:
            text = text[:12_000] + "\n... (delegated result truncated)"
        return (
            f"Delegated agent '{agent_def.name}' ({agent_def.agent_id}, role={agent_def.role}) "
            f"completed.\n\n{text or '(no textual result)'}"
        )

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

    @staticmethod
    def _build_delegated_system_prompt(session: Session, agent_def: AgentDefinition) -> str:
        """Build the default prompt for read-only delegated agents."""
        return f"""You are {agent_def.name}, a read-only delegated coding assistant.

Your job is to investigate focused subtasks for another agent. You may inspect
the local project using read/search/list tools, but you must not modify files,
run shell commands, or perform broad unrelated work.

Working directory: {session.work_dir}

Guidelines:
- Stay focused on the delegated task.
- Cite relevant files and symbols when possible.
- Prefer concise findings over long explanations.
- Explicitly mention uncertainty or missing information.
- Do not attempt to edit files or execute commands.
"""