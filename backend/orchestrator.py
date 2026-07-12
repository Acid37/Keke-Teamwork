"""Agent 编排层。

编排入口：保持现有单 Agent 行为不变，但将执行流程移到 orchestrator 边界内，
以便添加委派/handoff 和并行 researcher，而不再膨胀 ws_server.py。
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
from backend.context_builder import build_project_context
from backend.delegate_runner import DelegateRunner
from backend.model_resolver import ModelResolver
from backend.prompt_builder import build_system_prompt
from backend.research_runner import ResearchRunner
from backend.safety.file_staging import FileStagingArea
from backend.safety.permission import PermissionManager
from backend.session import SessionStore
from backend.title_service import TitleService
from backend.tools import ALL_TOOLS, has_write_tool, is_read_only_tool_set, resolve_tools
from backend.types import AgentDefinition, Phase, Session, ToolContext

logger = logging.getLogger(__name__)

Broadcast = Callable[[str, dict], Awaitable[None]]


def _make_tool_broadcasters(
    agent_id: str, agent_role: str, broadcast: Broadcast,
) -> tuple[Callable[[str, dict], Awaitable[None]], Callable[[str, bool, str], Awaitable[None]]]:
    """创建 tool.call 广播闭包对。"""
    tool_call_ids: dict[str, list[str]] = {}

    async def broadcast_tool_call(name: str, args: dict):
        call_id = uuid4().hex[:8]
        tool_call_ids.setdefault(name, []).append(call_id)
        await broadcast("tool.call", {
            "name": name, "args": args, "stage": "running",
            "source": agent_role, "call_id": call_id, "agent_id": agent_id,
        })

    async def broadcast_tool_result(name: str, success: bool, result: str):
        call_id = tool_call_ids.get(name, []).pop(0) if tool_call_ids.get(name) else uuid4().hex[:8]
        await broadcast("tool.call", {
            "name": name, "args": {"result": result}, "stage": "completed",
            "source": agent_role, "call_id": call_id, "success": success, "agent_id": agent_id,
        })

    return broadcast_tool_call, broadcast_tool_result


class AgentOrchestrator:
    """协调会话中的 Agent 执行。

    职责仅限于消息分发与组件接线——并行研究、委派/handoff、
    标题生成、模型解析和提示词构建分别委托到独立模块。
    """

    def __init__(self, *, config: AppConfig, llm, agent_store: AgentStore,
                 permission_managers: dict[str, PermissionManager],
                 session_store: SessionStore | None = None, llm_factory=None):
        self._config = config
        self._llm = llm
        self._agent_store = agent_store
        self._permission_managers = permission_managers
        self._model_resolver = ModelResolver(config, llm, llm_factory=llm_factory)
        self._delegate_runner = DelegateRunner(config, agent_store, self._model_resolver)
        self._research_runner = ResearchRunner(config, agent_store, self._delegate_runner)
        self._title_service = TitleService(config, session_store, llm)

    # ─── 主入口 ───

    async def run_user_message(self, *, session: Session, text: str,
                               agent_id: str = "main", broadcast: Broadcast) -> None:
        """通过编排层处理一条用户消息。"""
        session.phase = Phase.THINKING
        session.last_active_at = time.time()
        session.messages.append({"role": "user", "content": text})

        # 首次用户消息时构建项目上下文
        if len(session.messages) == 1 and session.project_context is None:
            try:
                session.project_context = build_project_context(session.work_dir)
            except Exception:
                logger.debug("项目上下文构建失败", exc_info=True)

        # 标题生成
        if self._title_service.should_generate_title(session):
            session.title = self._title_service.generate_title(text, session.work_dir)
            asyncio.create_task(self._title_service.update_title_with_llm(
                session=session, user_text=text, broadcast=broadcast))

        # 解析 Agent
        if session.solo_mode:
            agent_id = "main"
        agent_def = self._resolve_agent(agent_id)
        if not agent_def:
            await broadcast("error", {"message": "No agent definitions available", "recoverable": True})
            return

        aid, aname, arole, acolor = agent_def.agent_id, agent_def.name, agent_def.role, agent_def.color
        effective_model = self._model_resolver.resolve_model(agent_def)
        llm = self._model_resolver.create_llm_for_agent(
            agent_def, effective_model, agent_def.provider or self._config.provider)
        context_limit = self._model_resolver.resolve_context_limit(agent_def)

        await broadcast("agent.status", {"phase": "thinking", "detail": "Processing..."})
        await broadcast("agent.started", {
            "agent_id": aid, "agent_name": aname, "role": arole, "color": acolor})

        # 并行研究
        research_summary = await self._run_parallel_research(session, text, agent_def, broadcast)

        # 构建工具上下文
        staging = FileStagingArea(session.work_dir)
        permission_mgr = PermissionManager(broadcast=broadcast, yolo_mode=session.yolo_mode)
        self._permission_managers[session.id] = permission_mgr
        tool_context = self._build_tool_context(session, aid, staging, permission_mgr, broadcast)
        broadcast_tool_call, broadcast_tool_result = _make_tool_broadcasters(aid, arole, broadcast)

        # 构建 Agent
        agent = self._create_agent(llm, agent_def, effective_model, session)

        # 构建消息并运行
        agent_user_message = ResearchRunner.build_agent_user_message(
            user_text=text, research_summary=research_summary)
        agent_existing_messages = [*session.messages[:-1], {"role": "user", "content": agent_user_message}]

        try:
            result = await agent.run(
                user_message=agent_user_message, tool_context=tool_context,
                existing_messages=agent_existing_messages,
                max_tool_rounds=agent_def.max_tool_rounds, context_limit=context_limit,
                on_text=lambda t: broadcast("agent.text", {
                    "text": t, "source": arole, "is_final": False,
                    "agent_id": aid, "agent_name": aname, "role": arole, "color": acolor}),
                on_thinking=lambda t: broadcast("agent.thinking", {
                    "text": t, "source": arole, "agent_id": aid, "agent_name": aname}),
                on_tool_call=broadcast_tool_call, on_tool_result=broadcast_tool_result,
            )
            if result.error:
                raise RuntimeError(result.error)
            await self._finalize_success(
                session, result, text, agent_user_message,
                research_summary, staging, broadcast, aid, aname, arole)
        except asyncio.CancelledError:
            staging.rollback()
            session.phase = Phase.READY
            await self._broadcast_agent_end(broadcast, aid, aname, arole, "\n\n[被用户中断]", "ready", "Interrupted")
        except Exception as e:
            staging.rollback()
            logger.exception("Agent execution failed")
            session.phase = Phase.ERROR
            await broadcast("error", {"message": f"Agent error: {e}", "recoverable": True})
            await broadcast("agent.status", {"phase": "error", "detail": str(e)})
        finally:
            self._permission_managers.pop(session.id, None)

    # ─── 私有方法 ───

    async def _run_parallel_research(self, session, text, agent_def, broadcast) -> str:
        """执行并行研究，返回摘要字符串（失败时返回空串）。"""
        if not self._research_runner.should_run_research(session, agent_def):
            return ""
        try:
            merged = await self._research_runner.run_research(
                session=session, task=text, context="用户消息进入主 Agent 前的只读研究。",
                agent_id=agent_def.agent_id, broadcast=broadcast)
            return self._research_runner.format_summary_for_agent(task=text, merged=merged)
        except Exception as exc:
            logger.exception("Parallel research preflight failed")
            await broadcast("research.failed", {
                "agent_id": "parallel-research", "agent_name": "Parallel Research",
                "role": "researcher", "parent_agent_id": agent_def.agent_id,
                "task": text, "text": "", "timed_out": False, "error": str(exc)})
            return ""

    def _build_tool_context(self, session, aid, staging, permission_mgr, broadcast) -> ToolContext:
        """构建工具执行上下文，包含子 Agent 委派闭包。"""
        async def run_child_agent(agent_id: str, task: str, context: str = "") -> str:
            child_def = self._agent_store.get_agent(agent_id)
            if child_def and has_write_tool(child_def.tools):
                return await self._delegate_runner.run_handoff(
                    session=session, broadcast=broadcast, parent_agent_id=aid,
                    agent_id=agent_id, task=task, context=context,
                    staging=staging, permission_mgr=permission_mgr)
            return await self._delegate_runner.run_delegated(
                session=session, broadcast=broadcast, parent_agent_id=aid,
                agent_id=agent_id, task=task, context=context)

        return ToolContext(
            session=session, work_dir=session.work_dir, staging=staging,
            permission_mgr=permission_mgr, delegate_runner=run_child_agent,
            broadcast=broadcast, interrupt_check=lambda: session.interrupt_requested)

    def _create_agent(self, llm, agent_def, effective_model, session) -> Agent:
        """构建 Agent 实例，设置工具和系统提示词。"""
        agent = Agent(llm, model=effective_model, temperature=agent_def.temperature,
                     max_tool_rounds=agent_def.max_tool_rounds,
                     agent_id=agent_def.agent_id, role=agent_def.role, agent_name=agent_def.name)
        agent.tools = resolve_tools(agent_def.tools) if agent_def.tools else ALL_TOOLS
        agent.system_prompt = agent_def.system_prompt if agent_def.system_prompt else build_system_prompt(session)
        return agent

    async def _finalize_success(self, session, result, text, agent_user_message,
                                research_summary, staging, broadcast, aid, aname, arole) -> None:
        """处理 Agent 执行成功后的收尾：消息还原、提交、广播。"""
        session.messages = result.messages
        # 还原研究摘要注入的用户消息为原始文本
        if research_summary and session.messages:
            for msg in reversed(session.messages):
                if msg.get("role") == "user" and msg.get("content") == agent_user_message:
                    msg["content"] = text
                    break
        session.usage_total += result.usage
        session.phase = Phase.READY

        commit = staging.commit()
        if commit.files_changed and session.auto_review:
            await broadcast("files.changed", {
                "summary": commit.summary, "combined_diff": commit.combined_diff,
                "files": [{"path": str(d.path), "action": d.action, "diff_text": d.diff_text}
                          for d in commit.diffs]})

        await broadcast("agent.completed", {
            "agent_id": aid, "agent_name": aname, "role": arole,
            "summary": result.text[:200] if result.text else "",
            "usage": {"input_tokens": result.usage.input_tokens, "output_tokens": result.usage.output_tokens}})
        await self._broadcast_agent_end(broadcast, aid, aname, arole, "", "ready", None)

    async def _broadcast_agent_end(self, broadcast, aid, aname, arole, text, phase, detail) -> None:
        """广播 Agent 结束事件（最终文本 + 状态）。"""
        await broadcast("agent.text", {
            "text": text, "source": arole, "is_final": True,
            "agent_id": aid, "agent_name": aname})
        await broadcast("agent.status", {"phase": phase, "detail": detail})

    def _resolve_agent(self, agent_id: str) -> AgentDefinition | None:
        return self._agent_store.get_agent(agent_id) or self._agent_store.get_agent("main")

    @classmethod
    def _is_read_only_agent(cls, agent_def: AgentDefinition) -> bool:
        return is_read_only_tool_set(agent_def.tools)

    @classmethod
    def _has_write_tools(cls, agent_def: AgentDefinition) -> bool:
        return has_write_tool(agent_def.tools)