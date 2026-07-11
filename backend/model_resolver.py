"""模型解析与 LLM 客户端创建。"""

from __future__ import annotations

from backend.config import AppConfig
from backend.llm.client import LLMClient, LLMClientFactory
from backend.types import AgentDefinition


class ModelResolver:
    """解析 Agent 的有效模型并创建对应的 LLM 客户端。

    解析优先级（从高到低）：
    1. agent_def.model（per-agent 自定义模型别名或裸 model id）
    2. 全局角色回退值（coder_model / research_model / title_model → 引用 ModelInfo.name）
    3. main_model（引用 ModelInfo.name）
    """

    def __init__(
        self,
        config: AppConfig,
        llm: LLMClient,
        llm_factory: LLMClientFactory | None = None,
    ):
        self._config = config
        self._llm = llm
        self._llm_factory = llm_factory

    def resolve_model(self, agent_def: AgentDefinition) -> str:
        """解析 Agent 的有效模型（返回裸 model_id 字符串，用于 LLM 调用）。

        优先返回 ModelInfo 的 model_id（通过别名查），如果 agent_def.model
        不是别名（裸 model id），直接返回。
        """
        # 1. agent_def.model 优先
        if agent_def.model:
            model_info = self._config.get_model(agent_def.model)
            if model_info is not None:
                return model_info.model_id
            return agent_def.model
        # 2. 角色回退
        role_alias: str | None = None
        if agent_def.role == "researcher" and self._config.research_model:
            role_alias = self._config.research_model
        elif agent_def.role == "coder" and self._config.coder_model:
            role_alias = self._config.coder_model
        if role_alias:
            model_info = self._config.get_model(role_alias)
            if model_info is not None:
                return model_info.model_id
        # 3. main_model
        if self._config.main_model:
            model_info = self._config.get_model(self._config.main_model)
            if model_info is not None:
                return model_info.model_id
        return self._config.main_model

    def create_llm_for_agent(
        self,
        agent_def: AgentDefinition,
        effective_model: str,
        effective_provider: str,
    ) -> LLMClient:
        """为 Agent 创建 LLM 客户端。

        如果 agent_def 指定了自己的 model/provider，或者 effective 与默认不同，
        就创建新 client（多 provider 体系下必须这么做）。
        否则直接复用共享 llm。
        """
        if not (agent_def.provider or agent_def.model):
            # 没有 per-agent 配置，复用共享 LLM
            shared_model = getattr(self._llm, "model", None)
            if shared_model is not None and effective_model == shared_model:
                return self._llm
        # 优先用 factory（多 provider）
        if self._llm_factory is not None:
            try:
                return self._llm_factory.get_client(agent_def.model or None)
            except (ValueError, AssertionError):
                pass
        # 兜底：按 agent_def.provider 或 effective_provider 创建
        if agent_def.provider or agent_def.model:
            return LLMClient(
                provider=agent_def.provider or effective_provider,
                api_key=self._config.api_key,
                base_url=self._config.base_url,
                model=effective_model,
            )
        return LLMClient(
            provider=effective_provider,
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            model=effective_model,
        )