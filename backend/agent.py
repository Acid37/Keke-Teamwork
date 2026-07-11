"""Agent 运行时——核心 Tool Calling 循环。

一个 Agent = LLM + 私有工具集 + 双层循环：
  外层循环：调用 LLM → 获取响应
  内层循环：如果有 tool calls → 执行工具 → 回馈结果 → 重复
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from backend.llm.client import LLMClient
from backend.tools.base import Tool
from backend.types import (
    AgentResult,
    StreamEvent,
    TokenUsage,
    ToolCall,
    ToolContext,
    ToolSchema,
)

logger = logging.getLogger(__name__)


class Agent:
    """Agent = LLM + private tool set + Tool Calling loop.

    Subclasses set `tools` (list of Tool subclasses) and `system_prompt`.
    """

    # Subclass overrides
    tools: list[type[Tool]] = []
    system_prompt: str = ""

    def __init__(
        self,
        llm: LLMClient,
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tool_rounds: int = 50,
        agent_id: str = "main",
        role: str = "assistant",
        agent_name: str = "助手",
    ):
        self._llm = llm
        self._model = model or llm._model
        self._temperature = temperature
        self._default_max_rounds = max_tool_rounds
        # Agent identity — broadcast in callbacks so the frontend can
        # distinguish between different agents in multi-agent mode.
        self.agent_id = agent_id
        self.role = role
        self.agent_name = agent_name

    async def run(
        self,
        user_message: str,
        *,
        # Streaming callbacks
        on_text: Callable[[str], Awaitable[None]] | None = None,
        on_thinking: Callable[[str], Awaitable[None]] | None = None,
        on_tool_call: Callable[[str, dict], Awaitable[None]] | None = None,
        on_tool_result: Callable[[str, bool, str], Awaitable[None]] | None = None,
        # Mid-execution guidance
        guidance_queue: asyncio.Queue[str] | None = None,
        # Context control
        max_tool_rounds: int = 50,
        context_limit: int = 100_000,
        # Tool context (injected into tools)
        tool_context: ToolContext | None = None,
        # Existing messages to continue from
        existing_messages: list[dict] | None = None,
    ) -> AgentResult:
        """Run the Agent's Tool Calling loop.

        Returns AgentResult with final text, tool call history, and token usage.
        """
        # Build initial messages
        if existing_messages:
            messages = list(existing_messages)
        else:
            messages = []
            if self.system_prompt:
                messages.append({"role": "system", "content": self.system_prompt})
            messages.append({"role": "user", "content": user_message})

        # Create tool instances
        tool_map = self._create_tools(tool_context)
        tool_schemas = [t.to_schema() for t in tool_map.values()]

        total_text = ""
        total_thinking = ""
        tool_history: list[dict] = []
        usage = TokenUsage()
        tool_rounds = 0
        llm_error: str | None = None

        while True:
            # ── Call LLM ──
            round_text = ""
            round_thinking = ""
            tool_calls: list[ToolCall] = []

            try:
                async for event in self._llm.chat(
                    messages=messages,
                    tools=tool_schemas or None,
                    model=self._model,
                    temperature=self._temperature,
                ):
                    if event.text_delta:
                        round_text += event.text_delta
                        if on_text:
                            await on_text(event.text_delta)

                    if event.thinking_delta:
                        round_thinking += event.thinking_delta
                        if on_thinking:
                            await on_thinking(event.thinking_delta)

                    if event.tool_calls:
                        tool_calls = event.tool_calls

                    if event.finish:
                        break

            except Exception as e:
                logger.exception("LLM call failed")
                error_msg = f"LLM error: {e}"
                if on_text:
                    await on_text(f"\n\n[Error: {error_msg}]")
                total_text += f"\n\n[Error: {error_msg}]"
                llm_error = error_msg
                break

            total_text += round_text
            total_thinking += round_thinking

            # ── No tool calls → check guidance or finish ──
            if not tool_calls:
                # Check guidance queue (0.35s grace period like MoFox)
                if guidance_queue:
                    await asyncio.sleep(0.35)
                    if not guidance_queue.empty():
                        guidance_items = []
                        while not guidance_queue.empty():
                            guidance_items.append(guidance_queue.get_nowait())
                        guidance_text = "\n".join(guidance_items)
                        messages.append({
                            "role": "user",
                            "content": f"[User Guidance]\n{guidance_text}",
                        })
                        continue
                break  # No tools, no guidance → done

            # ── Has tool calls → execute them ──
            # Build assistant message with tool calls (OpenAI format)
            assistant_msg: dict = {"role": "assistant", "content": round_text or None}
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.args, ensure_ascii=False),
                    },
                }
                for tc in tool_calls
            ]
            messages.append(assistant_msg)

            # Execute each tool
            for tc in tool_calls:
                if on_tool_call:
                    await on_tool_call(tc.name, tc.args)

                tool = tool_map.get(tc.name)
                if not tool:
                    result_text = f"Error: Unknown tool '{tc.name}'"
                    success = False
                else:
                    try:
                        success, result_text = await tool.execute(**tc.args)
                    except Exception as e:
                        logger.exception("Tool %s execution failed", tc.name)
                        success = False
                        result_text = f"Error executing {tc.name}: {e}"

                if on_tool_result:
                    await on_tool_result(tc.name, success, result_text)

                # Truncate result to prevent context explosion
                truncated = result_text[:50_000]
                if len(result_text) > 50_000:
                    truncated += f"\n... (truncated, {len(result_text)} total chars)"

                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": truncated,
                })

                tool_history.append({
                    "name": tc.name,
                    "args": tc.args,
                    "result": result_text[:2000],  # shorter for history
                    "success": success,
                })

            # Check guidance queue after tool execution
            if guidance_queue and not guidance_queue.empty():
                guidance_items = []
                while not guidance_queue.empty():
                    guidance_items.append(guidance_queue.get_nowait())
                guidance_text = "\n".join(guidance_items)
                messages.append({
                    "role": "user",
                    "content": f"[User Guidance]\n{guidance_text}",
                })

            # Context compression check
            estimated = self._estimate_tokens(messages)
            if estimated > context_limit * 0.85:
                logger.info(
                    "Context limit approaching (%d tokens estimated), compressing",
                    estimated,
                )
                messages = await self._compress_context(messages, context_limit)

            tool_rounds += 1
            if tool_rounds >= max_tool_rounds:
                logger.warning("Max tool rounds (%d) reached, stopping", max_tool_rounds)
                if on_text:
                    await on_text("\n\n[Warning: Maximum tool call rounds reached]")
                break

        return AgentResult(
            text=total_text,
            thinking=total_thinking,
            tool_calls_history=tool_history,
            usage=usage,
            messages=messages,
            error=llm_error,
        )

    # ─── Internal helpers ───

    def _create_tools(self, context: ToolContext | None) -> dict[str, Tool]:
        """Instantiate tool classes with the given context."""
        if context is None:
            # Create a minimal context
            from backend.types import Session, Phase
            from pathlib import Path
            context = ToolContext(
                session=Session(id="tmp", work_dir=Path(".")),
                work_dir=Path("."),
            )
        return {t.name: t(context) for t in self.tools}

    @staticmethod
    def _estimate_tokens(messages: list[dict]) -> int:
        """Rough token estimate: total chars / 3 (good enough for CJK mixed)."""
        total_chars = sum(
            len(str(m.get("content", "") or ""))
            + len(json.dumps(m.get("tool_calls", []), ensure_ascii=False))
            for m in messages
        )
        return total_chars // 3

    async def _compress_context(
        self, messages: list[dict], limit: int
    ) -> list[dict]:
        """Compress context by summarizing old messages with LLM.

        Strategy:
        1. Keep the system prompt (first message if role=system)
        2. Keep the last 3 rounds of conversation untouched
        3. Summarize everything in between
        """
        # Find system message
        system_msgs = []
        conversation = []
        for msg in messages:
            if msg["role"] == "system" and not conversation:
                system_msgs.append(msg)
            else:
                conversation.append(msg)

        if len(conversation) <= 6:
            return messages  # Too short to compress

        # Split: old messages to summarize + recent to keep
        keep_count = 6  # last 3 rounds (each round = assistant + tool result)
        old_msgs = conversation[:-keep_count]
        recent_msgs = conversation[-keep_count:]

        # Build summary prompt
        summary_input = json.dumps(old_msgs, ensure_ascii=False, default=str)
        if len(summary_input) > 30_000:
            summary_input = summary_input[:30_000] + "\n...(truncated)"

        summary_prompt = (
            "Summarize the following conversation history concisely. "
            "Focus on: what was the user's goal, what tools were called, "
            "what were the key results, and what is the current state.\n\n"
            f"Conversation:\n{summary_input}"
        )

        try:
            summary_text = ""
            async for event in self._llm.chat(
                messages=[{"role": "user", "content": summary_prompt}],
                max_tokens=2000,
            ):
                if event.text_delta:
                    summary_text += event.text_delta
                if event.finish:
                    break
        except Exception:
            logger.warning("Context compression LLM call failed, keeping original")
            return messages

        # Rebuild messages: system + summary + recent
        compressed = system_msgs + [
            {
                "role": "system",
                "content": (
                    f"[Previous conversation summary]\n{summary_text}\n"
                    "[End of summary — continue from where the conversation left off]"
                ),
            }
        ] + recent_msgs

        old_est = self._estimate_tokens(messages)
        new_est = self._estimate_tokens(compressed)
        logger.info(
            "Context compressed: %d → %d estimated tokens (%d messages → %d)",
            old_est, new_est, len(messages), len(compressed),
        )

        return compressed
