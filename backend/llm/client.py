"""LLMClient 门面——所有 LLM provider 的统一接口。

包含：
- LLMClient: 单 provider 客户端（保持向后兼容）
- LLMClientFactory: 多 provider 工厂，按 model 别名创建客户端
"""

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
        self._client_type = provider
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

    @property
    def client_type(self) -> str:
        return self._client_type

    @property
    def model(self) -> str:
        return self._model

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
        """Send a chat completion request and yield streaming events."""
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


class LLMClientFactory:
    """多 provider 工厂——按 model 别名按需创建 LLMClient。

    用于多提供商架构：根据 AppConfig 中的 providers/models 列表，
    在调用时动态选 provider 建 client，缓存以避免重复创建。
    """

    def __init__(self, config):
        self._config = config
        self._cache: dict[tuple[str, str], LLMClient] = {}

    def get_client(self, model_alias: str | None) -> LLMClient:
        """按 model 别名返回对应的 LLMClient。

        未指定别名或找不到时，回退到 main_model 对应的模型。
        """
        model_info = None
        if model_alias:
            model_info = self._config.get_model(model_alias)
        if model_info is None:
            model_info = self._config.get_main_model()
        if model_info is None and self._config.providers:
            # 兜底：第一个 provider + alias 当 model_id
            class _FallbackModel:
                def __init__(self, mid: str, pname: str):
                    self.model_id = mid
                    self.provider_name = pname
            model_info = _FallbackModel(
                mid=model_alias or "",
                pname=self._config.providers[0].name,
            )
        if model_info is None:
            raise ValueError("No model configured")

        provider = self._config.get_provider(model_info.provider_name)
        if provider is None:
            raise ValueError(f"Provider '{model_info.provider_name}' not found")

        cache_key = (provider.name, model_info.model_id)
        if cache_key in self._cache:
            return self._cache[cache_key]

        client = LLMClient(
            provider=provider.client_type,
            api_key=provider.api_key,
            base_url=provider.base_url,
            model=model_info.model_id,
        )
        self._cache[cache_key] = client
        return client

    def invalidate(self) -> None:
        """配置变更后清空缓存。"""
        self._cache.clear()