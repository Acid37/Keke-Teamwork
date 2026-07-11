"""应用配置。"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ─── 多提供商 / 多模型 ───

VALID_CLIENT_TYPES = ("openai", "anthropic", "gemini")


@dataclass
class APIProvider:
    """单个 LLM 服务商。

    支持多家同时使用（DeepSeek + Anthropic + OpenAI 等），
    每个 Provider 用 name 标识，ModelInfo.provider_name 引用之。
    """

    name: str                                # "deepseek"、"anthropic"、"openai"
    client_type: str = "openai"               # openai | anthropic | gemini
    base_url: str = ""                        # OpenAI 兼容必填；anthropic/gemini 可空
    api_key: str = ""
    enabled: bool = True

    def to_dict(self, mask_key: bool = True) -> dict:
        d = asdict(self)
        if mask_key and self.api_key:
            if len(self.api_key) > 8:
                d["api_key_masked"] = self.api_key[:4] + "****" + self.api_key[-4:]
            else:
                d["api_key_masked"] = "****" if self.api_key else ""
        return d


@dataclass
class ModelInfo:
    """单个模型引用。

    通过 provider_name 引用一个 APIProvider，通过 model_id 引用
    服务商侧的模型标识符（如 deepseek-chat、gpt-4o）。
    """

    name: str                                # 用户起的别名 "main-fast"、"coder-pro"
    model_id: str                            # 实际 API 调用时用的 model id
    provider_name: str                       # 引用 APIProvider.name
    max_context: int | None = None
    extra_params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AppConfig:
    """应用配置。从 JSON 文件加载，环境变量可覆盖。"""

    # ─── LLM（向后兼容的旧字段）───
    provider: str = "openai"          # "openai" | "anthropic" | "gemini"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    main_model: str = "deepseek-v4-flash"
    coder_model: str | None = None
    research_model: str | None = None
    title_model: str | None = None

    # ─── 多提供商（新架构）───
    providers: list[APIProvider] = field(default_factory=list)
    models: list[ModelInfo] = field(default_factory=list)

    # ─── 服务器 ───
    host: str = "127.0.0.1"
    port: int = 8765

    # ─── 命令执行 ───
    console_timeout: int = 30
    console_max_output: int = 200

    # ─── 研究 ───
    max_parallel_researchers: int = 6

    # ─── 路径 ───
    data_dir: Path = field(default_factory=lambda: Path.home() / ".keke-teamwork")

    # ───────────────────────────────────────────
    # 加载 / 保存
    # ───────────────────────────────────────────

    @property
    def config_file(self) -> Path:
        return self.data_dir / "config.json"

    @classmethod
    def load(cls) -> AppConfig:
        """加载配置：先读 JSON 文件，再迁移旧字段，最后用环境变量覆盖。"""
        config = cls._load_from_file()
        config._migrate_legacy()
        config._apply_env_overrides()
        return config

    @classmethod
    def from_env(cls) -> AppConfig:
        return cls.load()

    @classmethod
    def _load_from_file(cls) -> AppConfig:
        default_dir = Path.home() / ".keke-teamwork"
        config_path = default_dir / "config.json"
        if not config_path.exists():
            return cls(data_dir=default_dir)
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            known = {f.name for f in cls.__dataclass_fields__.values()}
            filtered: dict[str, Any] = {}
            for k, v in data.items():
                if k == "data_dir":
                    continue
                if k in ("providers", "models"):
                    filtered[k] = v
                elif k in known:
                    filtered[k] = v
            if "providers" in filtered:
                filtered["providers"] = [APIProvider(**p) for p in filtered["providers"]]
            if "models" in filtered:
                filtered["models"] = [ModelInfo(**m) for m in filtered["models"]]
            filtered["data_dir"] = default_dir
            return cls(**filtered)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning("加载配置文件失败: %s", e)
            return cls(data_dir=default_dir)

    def _migrate_legacy(self) -> None:
        """从旧字段（provider/api_key/base_url/main_model）迁移到新结构。

        迁移规则：
        - 如果 providers 为空，用旧 provider/api_key/base_url 生成一个默认 provider。
        - 如果 models 为空，用旧 main_model/coder/research/title 生成 model 别名。
        """
        if not self.providers:
            default_name = self._infer_default_provider_name()
            self.providers = [APIProvider(
                name=default_name,
                client_type=self.provider,
                base_url=self.base_url if self.provider == "openai" else "",
                api_key=self.api_key,
                enabled=True,
            )]
        if not self.models:
            default_provider = self.providers[0].name
            # 先收集已用过的 model_id，避免重复创建
            used_ids: set[str] = set()
            self.models.append(ModelInfo(
                name="main",
                model_id=self.main_model,
                provider_name=default_provider,
            ))
            used_ids.add(self.main_model)
            self.main_model = "main"
            if self.coder_model and self.coder_model not in used_ids:
                self.models.append(ModelInfo(
                    name="coder",
                    model_id=self.coder_model,
                    provider_name=default_provider,
                ))
                used_ids.add(self.coder_model)
                self.coder_model = "coder"
            if self.research_model and self.research_model not in used_ids:
                self.models.append(ModelInfo(
                    name="researcher",
                    model_id=self.research_model,
                    provider_name=default_provider,
                ))
                used_ids.add(self.research_model)
                self.research_model = "researcher"
            if self.title_model and self.title_model not in used_ids:
                self.models.append(ModelInfo(
                    name="title",
                    model_id=self.title_model,
                    provider_name=default_provider,
                ))
                used_ids.add(self.title_model)
                self.title_model = "title"

    def _infer_default_provider_name(self) -> str:
        """从 base_url 和 client_type 推断一个友好的默认 provider 名字。"""
        # 优先按 client_type 判断
        if self.provider == "anthropic":
            return "anthropic"
        if self.provider == "gemini":
            return "gemini"
        url = (self.base_url or "").lower()
        if "deepseek" in url:
            return "deepseek"
        if "anthropic" in url:
            return "anthropic"
        if "generativelanguage" in url or "gemini" in url:
            return "gemini"
        if "moonshot" in url or "kimi" in url:
            return "kimi"
        if "dashscope" in url or "aliyun" in url:
            return "qwen"
        if "bigmodel" in url or "zhipu" in url:
            return "glm"
        if "openai.com" in url:
            return "openai"
        return "default"

    def _apply_env_overrides(self) -> None:
        if v := os.getenv("CT_PROVIDER"):
            self.provider = v
        if v := os.getenv("CT_API_KEY"):
            self.api_key = v
        if v := os.getenv("CT_BASE_URL"):
            self.base_url = v
        if v := os.getenv("CT_MODEL"):
            self.main_model = v
        if v := os.getenv("CT_CODER_MODEL"):
            self.coder_model = v
        if v := os.getenv("CT_RESEARCH_MODEL"):
            self.research_model = v
        if v := os.getenv("CT_TITLE_MODEL"):
            self.title_model = v
        if v := os.getenv("CT_HOST"):
            self.host = v
        if v := os.getenv("CT_PORT"):
            self.port = int(v)
        if v := os.getenv("CT_CONSOLE_TIMEOUT"):
            self.console_timeout = int(v)

    def save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data.pop("data_dir", None)
        self.config_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def update(self, **kwargs) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.save()

    # ───────────────────────────────────────────
    # 向后兼容：effective_*_model 返回裸 model_id
    # ───────────────────────────────────────────

    def _resolve_alias_to_model_id(self, alias: str | None) -> str:
        """把别名解析为裸 model_id；找不到则返回原值（兼容旧用法）。"""
        if not alias:
            return ""
        model_info = self.get_model(alias)
        if model_info is not None:
            return model_info.model_id
        return alias

    @property
    def effective_coder_model(self) -> str:
        return self._resolve_alias_to_model_id(
            self.coder_model or self.main_model
        )

    @property
    def effective_research_model(self) -> str:
        return self._resolve_alias_to_model_id(
            self.research_model or self.main_model
        )

    @property
    def effective_title_model(self) -> str:
        return self._resolve_alias_to_model_id(
            self.title_model or self.main_model
        )

    # ───────────────────────────────────────────
    # 多提供商查询
    # ───────────────────────────────────────────

    def get_provider(self, name: str) -> APIProvider | None:
        for p in self.providers:
            if p.name == name:
                return p
        return None

    def get_model(self, name: str) -> ModelInfo | None:
        """按别名查找模型。"""
        for m in self.models:
            if m.name == name:
                return m
        return None

    def get_model_for_role(self, role: str | None) -> ModelInfo | None:
        """根据角色返回对应的 ModelInfo。"""
        alias_map = {
            "main": self.main_model,
            "coder": self.coder_model or self.main_model,
            "researcher": self.research_model or self.main_model,
            "title": self.title_model or self.main_model,
        }
        alias = alias_map.get(role or "main", self.main_model)
        if not alias:
            return None
        model = self.get_model(alias)
        if model:
            return model
        # 兼容旧用法：alias 本身就是裸 model id
        if self.providers:
            return ModelInfo(
                name=alias,
                model_id=alias,
                provider_name=self.providers[0].name,
            )
        return None

    # ───────────────────────────────────────────
    # 序列化（API 响应）
    # ───────────────────────────────────────────

    def to_dict(self) -> dict:
        """序列化为字典（用于 API 响应）。"""
        return {
            "provider": self.provider,
            "api_key": self.api_key,
            "api_key_masked": self._mask_key(self.api_key),
            "base_url": self.base_url,
            "main_model": self.main_model,
            "coder_model": self.coder_model,
            "research_model": self.research_model,
            "title_model": self.title_model,
            "host": self.host,
            "port": self.port,
            "console_timeout": self.console_timeout,
            "console_max_output": self.console_max_output,
            "max_parallel_researchers": self.max_parallel_researchers,
            "providers": [p.to_dict(mask_key=True) for p in self.providers],
            "models": [m.to_dict() for m in self.models],
        }

    @staticmethod
    def _mask_key(key: str) -> str:
        if len(key) > 8:
            return key[:4] + "****" + key[-4:]
        return "****" if key else ""


@dataclass
class AppearanceConfig:
    """Appearance configuration. Persisted to appearance.json with atomic write."""

    mode: str = "dark"                  # dark / light / auto
    theme_color: str = "#4a9eff"        # accent color hex
    wallpaper: str | None = None        # wallpaper filename (in data_dir/wallpapers/)
    wallpaper_blur: float = 10.0        # blur 0-30
    wallpaper_opacity: float = 0.5      # opacity 0-1
    font_size: int = 14                 # base font size 12-20
    accent_preset: str = "blue"         # preset name or "custom"

    @property
    def config_file(self) -> Path:
        data_dir = Path.home() / ".keke-teamwork"
        return data_dir / "appearance.json"

    @classmethod
    def load(cls) -> AppearanceConfig:
        """Load from JSON file. Returns defaults if file doesn't exist."""
        config_path = cls().config_file
        if not config_path.exists():
            return cls()
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            known = {f.name for f in cls.__dataclass_fields__.values()}
            filtered = {k: v for k, v in data.items() if k in known}
            return cls(**filtered)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning("Failed to load appearance config: %s", e)
            return cls()

    def save(self) -> None:
        """Persist to JSON file with atomic write."""
        config_path = self.config_file
        config_path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        fd, tmp_path = tempfile.mkstemp(
            dir=config_path.parent, suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, config_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def update(self, **kwargs) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.save()

    def to_dict(self) -> dict:
        return asdict(self)