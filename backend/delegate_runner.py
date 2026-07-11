"""委派与 handoff 子 Agent 执行。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from uuid import uuid4

from backend.agent import Agent
from backend.config import AppConfig
from backend.model_resolver import ModelResolver
from backend.prompt_builder import build_delegated_system_prompt, build_handoff_system_prompt
from backend.safety.file_staging import FileStagingArea
from backend.safety.permission import PermissionManager
from backend.tools import resolve_tools
from backend.types import AgentDefinition, AgentResult, Session, ToolContext

logger = logging.getLogger(__name__)

Broadcast = Callable[[str, dict], Awaitable[None]]

# 只读委派 Agent 允许使用的工具白名单
_READ_ONLY_TOOLS = ["read_file", "grep_search", "find_files", "list_directory"]


class DelegateRunner:
    """运行委派/handoff 子 Agent，返回紧凑摘要。

    - **委派**（delegate）：只读，无 staging，返回调研结论。
    - **handoff**：可写，复用父 Agent 的 staging/permission 边界，执行实际修改。
    """

    def __init__(
        self,
        config: AppConfig,
        agent_store,
        model_resolver: ModelResolver,
    ):
        self._config = config
        self._agent_store = agent_store
        self._model_resolver = model_resolver

    # ─── 公开接口 ───

    async def run_delegated(
        self,
        *,
        session: Session,
        broadcast: Broadcast,
        parent_agent_id: str,
        agent_id: str,
        task: str,
        context: str = "",
    ) -> str:
        """运行一个只读委派子 Agent，返回紧凑摘要。"""
        agent_def = self._agent_store.get_agent(agent_id)
        if not agent_def:
            raise ValueError(f"Agent '{agent_id}' not found")
        if agent_def.agent_id == parent_agent_id:
            raise ValueError("An agent cannot delegate to itself")

        agent_tools = resolve_tools([
            name for name in agent_def.tools
            if name in _READ_ONLY_TOOLS
        ])
        if not agent_tools:
            agent_tools = resolve_tools(_READ_ONLY_TOOLS)

        effective_model = self._model_resolver.resolve_model(agent_def)
        effective_provider = agent_def.provider or self._config.provider
        llm = self._model_resolver.create_llm_for_agent(agent_def, effective_model, effective_provider)

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

        broadcast_tool_call, broadcast_tool_result = self._make_tool_broadcasters(
            aid, arole, parent_agent_id, broadcast,
        )

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
            else build_delegated_system_prompt(session, agent_def)
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

        if result.error:
            raise RuntimeError(result.error)

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

        return self.format_delegate_result(agent_def, result)

    async def run_handoff(
        self,
        *,
        session: Session,
        broadcast: Broadcast,
        parent_agent_id: str,
        agent_id: str,
        task: str,
        context: str = "",
        staging: FileStagingArea,
        permission_mgr: PermissionManager,
    ) -> str:
        """运行一个串行子 Agent，复用父 Agent 的写入安全边界。"""
        agent_def = self._agent_store.get_agent(agent_id)
        if not agent_def:
            raise ValueError(f"Agent '{agent_id}' not found")
        if agent_def.agent_id == parent_agent_id:
            raise ValueError("An agent cannot delegate to itself")

        agent_tools = resolve_tools([
            name for name in agent_def.tools
            if name != "delegate_agent"
        ])
        effective_model = self._model_resolver.resolve_model(agent_def)
        effective_provider = agent_def.provider or self._config.provider
        llm = self._model_resolver.create_llm_for_agent(agent_def, effective_model, effective_provider)

        base_payload = {
            "agent_id": agent_def.agent_id,
            "agent_name": agent_def.name,
            "role": agent_def.role,
            "parent_agent_id": parent_agent_id,
            "task": task,
        }
        await broadcast("handoff.started", base_payload)
        await broadcast("agent.started", {
            **base_payload,
            "color": agent_def.color,
            "delegated": True,
            "handoff": True,
        })

        aid = agent_def.agent_id
        aname = agent_def.name
        arole = agent_def.role
        acolor = agent_def.color

        broadcast_tool_call, broadcast_tool_result = self._make_tool_broadcasters(
            aid, arole, parent_agent_id, broadcast,
        )

        child_context = ToolContext(
            session=session,
            work_dir=session.work_dir,
            staging=staging,
            permission_mgr=permission_mgr,
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
            else build_handoff_system_prompt(session, agent_def)
        )

        handoff_message = (
            f"[Handoff task from {parent_agent_id}]\n{task.strip()}\n\n"
            f"[Context]\n{context.strip() or '(none)'}\n\n"
            "Work only on this delegated task. File edits must go through the provided tools. "
            "Do not delegate further."
        )

        try:
            result = await agent.run(
                user_message=handoff_message,
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
        except Exception as exc:
            await broadcast("handoff.failed", {
                **base_payload,
                "error": str(exc),
            })
            raise

        if result.error:
            error_msg = result.error
            await broadcast("handoff.failed", {
                **base_payload,
                "error": error_msg,
            })
            raise RuntimeError(error_msg)

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
            "handoff": True,
        })
        await broadcast("handoff.completed", {
            **base_payload,
            "text": result.text,
        })
        await broadcast("agent.text", {
            "text": "",
            "source": arole,
            "is_final": True,
            "agent_id": aid,
            "agent_name": aname,
            "parent_agent_id": parent_agent_id,
        })

        return self.format_delegate_result(agent_def, result)

    # ─── 内部工具 ───

    @staticmethod
    def _make_tool_broadcasters(
        agent_id: str,
        agent_role: str,
        parent_agent_id: str,
        broadcast: Broadcast,
    ) -> tuple[
        Callable[[str, dict], Awaitable[None]],
        Callable[[str, bool, str], Awaitable[None]],
    ]:
        """创建 tool.call 广播闭包对，消除 handoff/delegate 间的重复代码。"""
        tool_call_ids: dict[str, list[str]] = {}

        async def broadcast_tool_call(name: str, args: dict):
            call_id = uuid4().hex[:8]
            tool_call_ids.setdefault(name, []).append(call_id)
            await broadcast("tool.call", {
                "name": name,
                "args": args,
                "stage": "running",
                "source": agent_role,
                "call_id": call_id,
                "agent_id": agent_id,
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
                "source": agent_role,
                "call_id": call_id,
                "success": success,
                "agent_id": agent_id,
                "parent_agent_id": parent_agent_id,
            })

        return broadcast_tool_call, broadcast_tool_result

    @staticmethod
    def format_delegate_result(agent_def: AgentDefinition, result: AgentResult) -> str:
        text = (result.text or "").strip()
        if len(text) > 12_000:
            text = text[:12_000] + "\n... (delegated result truncated)"
        return (
            f"Delegated agent '{agent_def.name}' ({agent_def.agent_id}, role={agent_def.role}) "
            f"completed.\n\n{text or '(no textual result)'}"
        )