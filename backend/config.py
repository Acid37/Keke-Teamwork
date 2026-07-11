"""Application configuration."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class AppConfig:
    """Application config. Loaded from JSON file, with env var overrides."""

    # ─── LLM ───
    provider: str = "openai"          # "openai" | "anthropic" | "gemini"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    main_model: str = "deepseek-v4-flash"
    coder_model: str | None = None    # None = same as main
    research_model: str | None = None # None = same as main
    title_model: str | None = None    # None = same as main

    # ─── Server ───
    host: str = "127.0.0.1"
    port: int = 8765

    # ─── Console ───
    console_timeout: int = 30         # seconds
    console_max_output: int = 200     # max output lines

    # ─── Research ───
    max_parallel_researchers: int = 6

    # ─── Paths ───
    data_dir: Path = field(default_factory=lambda: Path.home() / ".keke-teamwork")

    @property
    def config_file(self) -> Path:
        return self.data_dir / "config.json"

    @classmethod
    def load(cls) -> AppConfig:
        """Load config: JSON file first, then env var overrides on top."""
        config = cls._load_from_file()
        # Env vars override file values
        if v := os.getenv("CT_PROVIDER"):
            config.provider = v
        if v := os.getenv("CT_API_KEY"):
            config.api_key = v
        if v := os.getenv("CT_BASE_URL"):
            config.base_url = v
        if v := os.getenv("CT_MODEL"):
            config.main_model = v
        if v := os.getenv("CT_CODER_MODEL"):
            config.coder_model = v
        if v := os.getenv("CT_RESEARCH_MODEL"):
            config.research_model = v
        if v := os.getenv("CT_TITLE_MODEL"):
            config.title_model = v
        if v := os.getenv("CT_HOST"):
            config.host = v
        if v := os.getenv("CT_PORT"):
            config.port = int(v)
        if v := os.getenv("CT_CONSOLE_TIMEOUT"):
            config.console_timeout = int(v)
        return config

    @classmethod
    def from_env(cls) -> AppConfig:
        """Alias for load() — loads file + env overrides."""
        return cls.load()

    @classmethod
    def _load_from_file(cls) -> AppConfig:
        """Load from JSON config file. Returns defaults if file doesn't exist."""
        default_dir = Path.home() / ".keke-teamwork"
        config_path = default_dir / "config.json"
        if not config_path.exists():
            return cls()
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            # Filter to only known fields
            known = {f.name for f in cls.__dataclass_fields__.values()}
            filtered = {k: v for k, v in data.items() if k in known and k != "data_dir"}
            return cls(**filtered)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            import logging
            logging.getLogger(__name__).warning("Failed to load config file: %s", e)
            return cls()

    def save(self) -> None:
        """Persist current config to JSON file."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        # Don't persist data_dir (it's derived from home)
        data.pop("data_dir", None)
        self.config_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def update(self, **kwargs) -> None:
        """Update config fields and save to file."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.save()

    def to_dict(self) -> dict:
        """Serialize to dict (for API response). Hides full api_key."""
        data = asdict(self)
        data.pop("data_dir", None)
        # Mask API key: show first 4 + last 4 chars
        key = data.get("api_key", "")
        if len(key) > 8:
            data["api_key_masked"] = key[:4] + "****" + key[-4:]
        else:
            data["api_key_masked"] = "****" if key else ""
        return data

    @property
    def effective_coder_model(self) -> str:
        return self.coder_model or self.main_model

    @property
    def effective_research_model(self) -> str:
        return self.research_model or self.main_model

    @property
    def effective_title_model(self) -> str:
        return self.title_model or self.main_model


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
        # Atomic write: write to temp file in same dir, then os.replace
        fd, tmp_path = tempfile.mkstemp(
            dir=config_path.parent, suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, config_path)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def update(self, **kwargs) -> None:
        """Update fields and save to file."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.save()

    def to_dict(self) -> dict:
        """Serialize to dict (for API response)."""
        return asdict(self)
