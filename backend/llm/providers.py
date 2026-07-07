"""LLM provider implementations for OpenAI-compatible, Anthropic, and Gemini APIs."""

import json
import logging
import uuid
from collections.abc import AsyncIterator

from backend.types import ToolCall, StreamEvent

logger = logging.getLogger(__name__)


class OpenAICompatProvider:
    """Provider for OpenAI-compatible APIs (including DeepSeek, etc.)."""

    def __init__(self, api_key: str, base_url: str):
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    @staticmethod
    def _prepare_messages(messages: list[dict], system: str | None) -> list[dict]:
        """Prepend a system message if provided."""
        if system:
            return [{"role": "system", "content": system}, *messages]
        return list(messages)

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        model: str = "",
        max_tokens: int = 8192,
        temperature: float = 0.7,
    ) -> AsyncIterator[StreamEvent]:
        prepared = self._prepare_messages(messages, system)

        kwargs: dict = {
            "model": model,
            "messages": prepared,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools

        # Accumulators for streaming tool calls
        tool_accum: dict[int, dict] = {}  # index -> {id, name, arguments_str}

        try:
            stream = await self._client.chat.completions.create(**kwargs)

            async for chunk in stream:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                finish_reason = chunk.choices[0].finish_reason

                # Text content
                if delta.content:
                    yield StreamEvent(text_delta=delta.content)

                # Thinking / reasoning content (DeepSeek R1)
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    yield StreamEvent(thinking_delta=reasoning)

                # Tool call deltas
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_accum:
                            tool_accum[idx] = {
                                "id": tc_delta.id or "",
                                "name": tc_delta.function.name if tc_delta.function and tc_delta.function.name else "",
                                "arguments": "",
                            }
                        else:
                            if tc_delta.id:
                                tool_accum[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_accum[idx]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_accum[idx]["arguments"] += tc_delta.function.arguments

                # Finish reason — emit accumulated tool calls
                if finish_reason:
                    if tool_accum:
                        calls = []
                        for idx in sorted(tool_accum):
                            entry = tool_accum[idx]
                            try:
                                args = json.loads(entry["arguments"]) if entry["arguments"] else {}
                            except json.JSONDecodeError:
                                logger.warning(
                                    "Failed to parse tool arguments for %s: %r",
                                    entry["name"],
                                    entry["arguments"],
                                )
                                args = {}
                            calls.append(ToolCall(
                                id=entry["id"],
                                name=entry["name"],
                                args=args,
                            ))
                        yield StreamEvent(tool_calls=calls, finish=True)
                    else:
                        yield StreamEvent(finish=True)
                    return

        except Exception:
            logger.exception("OpenAI-compatible API call failed")
            raise


class AnthropicProvider:
    """Provider for the Anthropic Claude API."""

    def __init__(self, api_key: str):
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)

    @staticmethod
    def _convert_tools(tools: list[dict] | None) -> list[dict]:
        """Convert OpenAI-format tools to Claude format."""
        if not tools:
            return []
        claude_tools = []
        for t in tools:
            func = t.get("function", {})
            claude_tools.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
        return claude_tools

    @staticmethod
    def _convert_messages(messages: list[dict]) -> tuple[list[dict], str | None]:
        """Convert OpenAI-format messages to Claude format.

        Returns (converted_messages, system_prompt).
        """
        system_prompt: str | None = None
        converted: list[dict] = []

        for msg in messages:
            role = msg["role"]

            # System messages are extracted separately
            if role == "system":
                system_prompt = (system_prompt or "") + msg.get("content", "") + "\n"
                continue

            # Tool result messages: role "tool" -> role "user" with tool_result blocks
            if role == "tool":
                converted.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg["tool_call_id"],
                            "content": msg.get("content", ""),
                        }
                    ],
                })
                continue

            # Assistant messages with tool calls -> content blocks
            if role == "assistant":
                content_blocks: list[dict] = []
                if msg.get("content"):
                    content_blocks.append({"type": "text", "text": msg["content"]})
                for tc in msg.get("tool_calls", []):
                    func = tc.get("function", {})
                    raw_args = func.get("arguments", "{}")
                    if isinstance(raw_args, str):
                        try:
                            args_dict = json.loads(raw_args)
                        except json.JSONDecodeError:
                            args_dict = {}
                    else:
                        args_dict = raw_args
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": func.get("name", ""),
                        "input": args_dict,
                    })
                if not content_blocks:
                    content_blocks.append({"type": "text", "text": ""})
                converted.append({"role": "assistant", "content": content_blocks})
                continue

            # Regular user message
            converted.append({
                "role": role,
                "content": msg.get("content", ""),
            })

        return AnthropicProvider._merge_consecutive_roles(converted), system_prompt

    @staticmethod
    def _merge_consecutive_roles(messages: list[dict]) -> list[dict]:
        """Merge consecutive messages with the same role (Claude requires strict alternation)."""
        if not messages:
            return messages

        merged: list[dict] = [messages[0]]
        for msg in messages[1:]:
            prev = merged[-1]
            if msg["role"] == prev["role"]:
                # Merge content blocks
                prev_content = prev["content"]
                curr_content = msg["content"]
                if isinstance(prev_content, str):
                    prev_content = [{"type": "text", "text": prev_content}]
                if isinstance(curr_content, str):
                    curr_content = [{"type": "text", "text": curr_content}]
                prev["content"] = prev_content + curr_content
            else:
                merged.append(msg)
        return merged

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        model: str = "",
        max_tokens: int = 8192,
        temperature: float = 0.7,
    ) -> AsyncIterator[StreamEvent]:
        converted_messages, extracted_system = self._convert_messages(messages)
        # Prefer explicit system param; fall back to extracted system from messages
        system_text = system or extracted_system

        claude_tools = self._convert_tools(tools)

        kwargs: dict = {
            "model": model or "claude-sonnet-4-20250514",
            "messages": converted_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_text:
            kwargs["system"] = system_text
        if claude_tools:
            kwargs["tools"] = claude_tools

        try:
            async with self._client.messages.stream(**kwargs) as stream:
                tool_accum: dict[int, dict] = {}  # block index -> {id, name, input_json}

                async for event in stream:
                    event_type = event.type

                    if event_type == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use":
                            tool_accum[event.index] = {
                                "id": block.id,
                                "name": block.name,
                                "input_json": "",
                            }

                    elif event_type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            yield StreamEvent(text_delta=delta.text)
                        elif delta.type == "thinking_delta":
                            yield StreamEvent(thinking_delta=delta.thinking)
                        elif delta.type == "input_json_delta":
                            idx = event.index
                            if idx in tool_accum:
                                tool_accum[idx]["input_json"] += delta.partial_json

                    elif event_type == "message_delta":
                        # Stream finished
                        if tool_accum:
                            calls = []
                            for idx in sorted(tool_accum):
                                entry = tool_accum[idx]
                                try:
                                    args = json.loads(entry["input_json"]) if entry["input_json"] else {}
                                except json.JSONDecodeError:
                                    logger.warning(
                                        "Failed to parse Claude tool arguments for %s",
                                        entry["name"],
                                    )
                                    args = {}
                                calls.append(ToolCall(
                                    id=entry["id"],
                                    name=entry["name"],
                                    args=args,
                                ))
                            yield StreamEvent(tool_calls=calls, finish=True)
                        else:
                            yield StreamEvent(finish=True)
                        return

        except Exception:
            logger.exception("Anthropic API call failed")
            raise


class GeminiProvider:
    """Provider for the Google Gemini API."""

    def __init__(self, api_key: str):
        from google import genai

        self._client = genai.Client(api_key=api_key)

    @staticmethod
    def _convert_tools(tools: list[dict] | None) -> list | None:
        """Convert OpenAI-format tools to Gemini FunctionDeclaration objects."""
        if not tools:
            return None
        from google.genai import types

        declarations = []
        for t in tools:
            func = t.get("function", {})
            declarations.append(types.FunctionDeclaration(
                name=func["name"],
                description=func.get("description", ""),
                parameters=func.get("parameters", {"type": "object", "properties": {}}),
            ))
        return [types.Tool(function_declarations=declarations)]

    @staticmethod
    def _convert_messages(messages: list[dict]) -> list[dict]:
        """Convert OpenAI-format messages to Gemini Content objects."""
        contents: list[dict] = []

        for msg in messages:
            role = msg["role"]

            # Skip system messages — handled via config
            if role == "system":
                continue

            # Tool response -> function response
            if role == "tool":
                contents.append({
                    "role": "function",
                    "parts": [{"function_response": {
                        "name": msg.get("name", ""),
                        "response": {"result": msg.get("content", "")},
                    }}],
                })
                continue

            # Assistant with tool calls
            if role == "assistant":
                parts: list[dict] = []
                if msg.get("content"):
                    parts.append({"text": msg["content"]})
                for tc in msg.get("tool_calls", []):
                    func = tc.get("function", {})
                    raw_args = func.get("arguments", "{}")
                    if isinstance(raw_args, str):
                        try:
                            args_dict = json.loads(raw_args)
                        except json.JSONDecodeError:
                            args_dict = {}
                    else:
                        args_dict = raw_args
                    parts.append({"function_call": {
                        "name": func.get("name", ""),
                        "args": args_dict,
                    }})
                if not parts:
                    parts.append({"text": ""})
                contents.append({"role": "model", "parts": parts})
                continue

            # Regular user message
            contents.append({
                "role": "user",
                "parts": [{"text": msg.get("content", "")}],
            })

        return contents

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        model: str = "",
        max_tokens: int = 8192,
        temperature: float = 0.7,
    ) -> AsyncIterator[StreamEvent]:
        from google.genai import types

        contents = self._convert_messages(messages)
        gemini_tools = self._convert_tools(tools)

        config_kwargs: dict = {
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            config_kwargs["system_instruction"] = system
        if gemini_tools:
            config_kwargs["tools"] = gemini_tools

        config = types.GenerateContentConfig(**config_kwargs)

        model_name = model or "gemini-2.5-flash"

        try:
            tool_accum: dict[int, dict] = {}  # index -> {name, args_json}

            async for chunk in self._client.models.generate_content_stream(
                model=model_name,
                contents=contents,
                config=config,
            ):
                if not chunk.candidates:
                    continue

                candidate = chunk.candidates[0]

                # Process content parts
                if candidate.content and candidate.content.parts:
                    for part_idx, part in enumerate(candidate.content.parts):
                        # Text content
                        if part.text:
                            yield StreamEvent(text_delta=part.text)

                        # Thinking content
                        if part.thought:
                            if part.text:
                                yield StreamEvent(thinking_delta=part.text)

                        # Function calls (tool calls)
                        if part.function_call:
                            fc = part.function_call
                            # Use a stable key combining name and index
                            key = part_idx
                            if key not in tool_accum:
                                tool_accum[key] = {
                                    "name": fc.name or "",
                                    "args": dict(fc.args) if fc.args else {},
                                }

                # Check for finish
                if candidate.finish_reason:
                    if tool_accum:
                        calls = []
                        for key in sorted(tool_accum):
                            entry = tool_accum[key]
                            calls.append(ToolCall(
                                id=f"call_{uuid.uuid4().hex[:24]}",
                                name=entry["name"],
                                args=entry["args"],
                            ))
                        yield StreamEvent(tool_calls=calls, finish=True)
                    else:
                        yield StreamEvent(finish=True)
                    return

        except Exception:
            logger.exception("Gemini API call failed")
            raise
