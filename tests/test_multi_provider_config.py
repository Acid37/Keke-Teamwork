"""多 provider / 多 model 配置测试。"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from backend.config import APIProvider, AppConfig, ModelInfo


class APIProviderTests(TestCase):
    """APIProvider dataclass 测试。"""

    def test_default_values(self) -> None:
        p = APIProvider(name="test")
        self.assertEqual(p.name, "test")
        self.assertEqual(p.client_type, "openai")
        self.assertEqual(p.base_url, "")
        self.assertEqual(p.api_key, "")
        self.assertTrue(p.enabled)

    def test_to_dict_masks_key(self) -> None:
        p = APIProvider(name="deepseek", client_type="openai", base_url="https://x", api_key="sk-12345678abcdef")
        d = p.to_dict(mask_key=True)
        self.assertEqual(d["name"], "deepseek")
        self.assertIn("api_key_masked", d)
        self.assertNotEqual(d["api_key_masked"], "sk-12345678abcdef")
        self.assertIn("****", d["api_key_masked"])

    def test_to_dict_short_key(self) -> None:
        p = APIProvider(name="x", api_key="short")
        d = p.to_dict(mask_key=True)
        self.assertEqual(d["api_key_masked"], "****")


class ModelInfoTests(TestCase):
    """ModelInfo dataclass 测试。"""

    def test_basic(self) -> None:
        m = ModelInfo(name="main", model_id="gpt-4o", provider_name="openai")
        self.assertEqual(m.name, "main")
        self.assertEqual(m.model_id, "gpt-4o")
        self.assertEqual(m.provider_name, "openai")
        self.assertIsNone(m.max_context)
        self.assertEqual(m.extra_params, {})

    def test_to_dict(self) -> None:
        m = ModelInfo(name="m", model_id="gpt-4", provider_name="openai", max_context=128000)
        d = m.to_dict()
        self.assertEqual(d["name"], "m")
        self.assertEqual(d["max_context"], 128000)


class AppConfigMultiProviderTests(TestCase):
    """AppConfig 多 provider 架构测试。"""

    def test_empty_config_has_empty_providers(self) -> None:
        cfg = AppConfig()
        self.assertEqual(cfg.providers, [])
        self.assertEqual(cfg.models, [])

    def test_migrate_legacy_creates_default_provider_and_model(self) -> None:
        cfg = AppConfig(
            provider="openai",
            api_key="sk-xxx",
            base_url="https://api.deepseek.com",
            main_model="deepseek-chat",
        )
        cfg._migrate_legacy()
        self.assertEqual(len(cfg.providers), 1)
        self.assertEqual(cfg.providers[0].client_type, "openai")
        self.assertEqual(cfg.providers[0].base_url, "https://api.deepseek.com")
        self.assertEqual(cfg.providers[0].api_key, "sk-xxx")
        self.assertEqual(len(cfg.models), 1)
        self.assertEqual(cfg.models[0].name, "main")
        self.assertEqual(cfg.models[0].model_id, "deepseek-chat")
        self.assertEqual(cfg.models[0].provider_name, cfg.providers[0].name)
        self.assertEqual(cfg.main_model, "main")

    def test_migrate_legacy_preserves_title_only(self) -> None:
        cfg = AppConfig(
            provider="openai",
            api_key="sk",
            base_url="https://api.deepseek.com",
            main_model="deepseek-chat",
            title_model="deepseek-chat",
        )
        cfg._migrate_legacy()
        names = {m.name for m in cfg.models}
        self.assertIn("main", names)
        # title_model 和 main_model 相同，不会重复创建
        self.assertEqual(len([m for m in cfg.models if m.model_id == "deepseek-chat"]), 1)
        # 但 main_model 引用别名
        self.assertEqual(cfg.main_model, "main")

    def test_migrate_legacy_inferred_provider_name(self) -> None:
        cfg = AppConfig(provider="openai", base_url="https://api.deepseek.com")
        cfg._migrate_legacy()
        self.assertEqual(cfg.providers[0].name, "deepseek")

        cfg2 = AppConfig(provider="openai", base_url="https://api.moonshot.cn/v1")
        cfg2._migrate_legacy()
        self.assertEqual(cfg2.providers[0].name, "kimi")

        cfg3 = AppConfig(provider="openai", base_url="https://dashscope.aliyuncs.com/v1")
        cfg3._migrate_legacy()
        self.assertEqual(cfg3.providers[0].name, "qwen")

        cfg4 = AppConfig(provider="anthropic", api_key="sk-ant")
        cfg4._migrate_legacy()
        self.assertEqual(cfg4.providers[0].name, "anthropic")
        self.assertEqual(cfg4.providers[0].client_type, "anthropic")

    def test_get_provider_and_model(self) -> None:
        cfg = AppConfig()
        cfg.providers = [
            APIProvider(name="p1", client_type="openai", base_url="https://a", api_key="k1"),
            APIProvider(name="p2", client_type="anthropic", api_key="k2"),
        ]
        cfg.models = [
            ModelInfo(name="m1", model_id="gpt-4", provider_name="p1"),
            ModelInfo(name="m2", model_id="claude", provider_name="p2"),
        ]
        self.assertEqual(cfg.get_provider("p1").api_key, "k1")
        self.assertIsNone(cfg.get_provider("nope"))
        self.assertEqual(cfg.get_model("m1").model_id, "gpt-4")
        self.assertIsNone(cfg.get_model("nope"))

    def test_get_main_and_title_model(self) -> None:
        cfg = AppConfig(main_model="main", title_model=None)
        cfg.providers = [APIProvider(name="p", client_type="openai", base_url="https://a", api_key="k")]
        cfg.models = [
            ModelInfo(name="main", model_id="gpt-4", provider_name="p"),
        ]
        self.assertEqual(cfg.get_main_model().model_id, "gpt-4")
        self.assertEqual(cfg.get_title_model().model_id, "gpt-4")

    def test_effective_title_resolve_alias(self) -> None:
        cfg = AppConfig(main_model="main", title_model="title")
        cfg.providers = [APIProvider(name="p", client_type="openai", base_url="https://a", api_key="k")]
        cfg.models = [
            ModelInfo(name="main", model_id="gpt-4", provider_name="p"),
            ModelInfo(name="title", model_id="cheap-title", provider_name="p"),
        ]
        self.assertEqual(cfg.effective_title_model, "cheap-title")

    def test_to_dict_includes_providers_and_models(self) -> None:
        cfg = AppConfig()
        cfg.providers = [APIProvider(name="p", client_type="openai", base_url="https://a", api_key="sk-12345678")]
        cfg.models = [ModelInfo(name="m", model_id="gpt-4", provider_name="p")]
        d = cfg.to_dict()
        self.assertIn("providers", d)
        self.assertIn("models", d)
        self.assertEqual(len(d["providers"]), 1)
        self.assertEqual(len(d["models"]), 1)
        # api_key 脱敏
        self.assertIn("****", d["providers"][0]["api_key_masked"])

    def test_save_load_roundtrip(self) -> None:
        import os
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            # 把 Path.home() 临时指向 tmp
            original_home = os.environ.get("USERPROFILE")
            os.environ["USERPROFILE"] = str(home)
            try:
                cfg = AppConfig()
                cfg.providers = [
                    APIProvider(name="p1", client_type="openai", base_url="https://a", api_key="k1", enabled=True),
                    APIProvider(name="p2", client_type="anthropic", api_key="k2", enabled=False),
                ]
                cfg.models = [
                    ModelInfo(name="m1", model_id="gpt-4", provider_name="p1", max_context=128000),
                    ModelInfo(name="m2", model_id="claude", provider_name="p2"),
                ]
                cfg.main_model = "m1"
                cfg.save()

                # 读回（不要迁移，因为文件已经包含新结构）
                loaded = AppConfig._load_from_file()
                self.assertEqual(len(loaded.providers), 2)
                self.assertEqual(loaded.providers[0].name, "p1")
                self.assertEqual(loaded.providers[0].api_key, "k1")
                self.assertEqual(loaded.providers[1].client_type, "anthropic")
                self.assertFalse(loaded.providers[1].enabled)
                self.assertEqual(len(loaded.models), 2)
                self.assertEqual(loaded.models[0].model_id, "gpt-4")
                self.assertEqual(loaded.models[0].max_context, 128000)
                self.assertEqual(loaded.main_model, "m1")
            finally:
                if original_home is None:
                    os.environ.pop("USERPROFILE", None)
                else:
                    os.environ["USERPROFILE"] = original_home

    def test_load_handles_missing_providers_field(self) -> None:
        """旧格式 config.json 没有 providers/models 字段时，迁移能正常进行。"""
        import os
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            data_dir = home / ".keke-teamwork"
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "config.json").write_text(json.dumps({
                "provider": "openai",
                "api_key": "sk-legacy",
                "base_url": "https://api.deepseek.com",
                "main_model": "deepseek-chat",
            }, ensure_ascii=False), encoding="utf-8")
            original_home = os.environ.get("USERPROFILE")
            os.environ["USERPROFILE"] = str(home)
            try:
                cfg = AppConfig._load_from_file()
                self.assertEqual(cfg.provider, "openai")
                self.assertEqual(cfg.api_key, "sk-legacy")
                self.assertEqual(cfg.main_model, "deepseek-chat")
                cfg._migrate_legacy()
                self.assertEqual(len(cfg.providers), 1)
                self.assertEqual(cfg.providers[0].name, "deepseek")
                self.assertEqual(cfg.providers[0].api_key, "sk-legacy")
                self.assertEqual(len(cfg.models), 1)
                self.assertEqual(cfg.models[0].model_id, "deepseek-chat")
            finally:
                if original_home is None:
                    os.environ.pop("USERPROFILE", None)
                else:
                    os.environ["USERPROFILE"] = original_home