"""context_limit 配置链路测试。

验证 ModelResolver.resolve_context_limit 的优先级链：
ModelInfo.max_context → AgentDefinition.max_context → 默认 100k。
"""

import unittest
from unittest.mock import MagicMock

from backend.config import AppConfig, ModelInfo
from backend.model_resolver import ModelResolver
from backend.types import AgentDefinition


class ContextLimitTests(unittest.TestCase):
    def _make_resolver(self, config: AppConfig) -> ModelResolver:
        return ModelResolver(config, llm=MagicMock())

    def test_default_context_limit_is_100k(self):
        """无任何配置时应返回默认值 100_000。"""
        config = AppConfig()
        resolver = self._make_resolver(config)
        agent = AgentDefinition(agent_id="main", name="main", role="assistant")
        self.assertEqual(resolver.resolve_context_limit(agent), 100_000)

    def test_agent_def_max_context_overrides_everything(self):
        """AgentDefinition.max_context 优先级最高。"""
        config = AppConfig()
        config.models = [ModelInfo(name="main", model_id="m1", provider_name="p", max_context=200_000)]
        config.main_model = "main"
        resolver = self._make_resolver(config)
        agent = AgentDefinition(agent_id="main", name="main", role="assistant", max_context=50_000)
        self.assertEqual(resolver.resolve_context_limit(agent), 50_000)

    def test_model_info_max_context_used_when_no_agent_override(self):
        """无 AgentDefinition.max_context 时，使用 ModelInfo.max_context。"""
        config = AppConfig()
        config.models = [ModelInfo(name="main", model_id="m1", provider_name="p", max_context=128_000)]
        config.main_model = "main"
        resolver = self._make_resolver(config)
        agent = AgentDefinition(agent_id="main", name="main", role="assistant")
        self.assertEqual(resolver.resolve_context_limit(agent), 128_000)

    def test_falls_back_to_default_when_model_info_has_no_max_context(self):
        """ModelInfo.max_context 为 None 时回退到默认 100k。"""
        config = AppConfig()
        config.models = [ModelInfo(name="main", model_id="m1", provider_name="p", max_context=None)]
        config.main_model = "main"
        resolver = self._make_resolver(config)
        agent = AgentDefinition(agent_id="main", name="main", role="assistant")
        self.assertEqual(resolver.resolve_context_limit(agent), 100_000)

    def test_agent_model_context_used_when_no_agent_override(self):
        """Agent 显式指定 model 时，应通过该 model 别名查找 max_context。"""
        config = AppConfig()
        config.models = [
            ModelInfo(name="main", model_id="m1", provider_name="p", max_context=100_000),
            ModelInfo(name="custom", model_id="r1", provider_name="p", max_context=32_000),
        ]
        config.main_model = "main"
        resolver = self._make_resolver(config)
        agent = AgentDefinition(agent_id="researcher", name="researcher", role="researcher", model="custom")
        self.assertEqual(resolver.resolve_context_limit(agent), 32_000)

    def test_falls_back_to_main_model_context(self):
        """Agent 未指定 model 时，应通过 main_model 别名查找 max_context。"""
        config = AppConfig()
        config.models = [
            ModelInfo(name="main", model_id="m1", provider_name="p", max_context=64_000),
        ]
        config.main_model = "main"
        resolver = self._make_resolver(config)
        agent = AgentDefinition(agent_id="coder", name="coder", role="coder")
        self.assertEqual(resolver.resolve_context_limit(agent), 64_000)

    def test_agent_def_max_context_overrides_model_config(self):
        """AgentDefinition.max_context 优先于模型配置。"""
        config = AppConfig()
        config.models = [
            ModelInfo(name="custom", model_id="r1", provider_name="p", max_context=32_000),
        ]
        config.main_model = "main"
        resolver = self._make_resolver(config)
        agent = AgentDefinition(
            agent_id="custom-agent", name="custom-agent", role="assistant",
            model="custom", max_context=16_000)
        self.assertEqual(resolver.resolve_context_limit(agent), 16_000)


if __name__ == "__main__":
    unittest.main()