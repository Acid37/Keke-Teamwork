"""LLMClient 门面——所有 LLM provider 的统一接口。"""

import logging
from collections.abc import AsyncIterator

from backend.types import ToolSchema, StreamEvent
from backend.llm.providers import OpenAICompatProvider, AnthropicProvider, GeminiProvider

logger = logging.getLogger(__name__)


class LLMClient:
    """高级 LLM 客户端，路由到对应的 provider。"""

    def __init__(
        self,
        provider: str,
        api_key: str,
        base_url: str | None = None,
        model: str = "",
    ):
        self._model = model
        match provider:
            case "openai":
                assert base_url, "OpenAI-compatible provider requires base_url"
                self._provider = OpenAICompatProvider(api_key, base_url)
            case "anthropic":
                self._provider = AnthropicProvider(api_key)
            case "gemini":
                self._provider = GeminiProvider(api_key)
            case _:
                raise ValueError(f"Unknown provider: {provider}")

    async def chat(
        self,
        messages: list[dict],
        tools: list[ToolSchema] | None = None,
        system: str | None = None,
        model: str | None = None,
        stream: bool = True,
        max_tokens: int = 8192,
        temperature: float = 0.7,
    ) -> AsyncIterator[StreamEvent]:
        """Send a chat completion request and yield streaming events.

        Args:
            messages: Conversation messages in OpenAI format.
            tools: Tool schemas to make available to the model.
            system: Optional system prompt.
            model: Model override (falls back to constructor default).
            stream: Whether to stream (currently always streams).
            max_tokens: Maximum tokens in the response.
            temperature: Sampling temperature.

        Yields:
            StreamEvent objects with text_delta, thinking, tool_calls, or finish.
        """
        # Convert ToolSchema list to OpenAI-format tool dicts
        tools_param = None
        if tools:
            tools_param = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]

        effective_model = model or self._model

        logger.debug(
            "LLMClient.chat: model=%s, tools=%d, messages=%d",
            effective_model,
            len(tools_param) if tools_param else 0,
            len(messages),
        )

        async for event in self._provider.chat(
            messages=messages,
            tools=tools_param,
            system=system,
            model=effective_model,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            yield event
