"""Entry point — starts the backend server."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import uvicorn

from backend.config import AppConfig


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    config = AppConfig.load()

    if not config.api_key:
        print(
            "WARNING: API key not set. Configure it via UI at http://localhost:{}/ "
            "or set CT_API_KEY environment variable.".format(config.port),
            file=sys.stderr,
        )

    # Hot-reload support. Opt-in via env var so production runs stay stable.
    reload_enabled = os.getenv("CT_RELOAD", "").lower() in ("1", "true", "yes")
    backend_dir = str(Path(__file__).resolve().parent)
    reload_dirs: list[str] | None = None
    if reload_enabled:
        custom = os.getenv("CT_RELOAD_DIR", "").strip()
        reload_dirs = [custom] if custom else [backend_dir]

    print(f"Starting Keke Teamwork server on {config.host}:{config.port}")
    print(f"  Provider: {config.provider}")
    print(f"  Model:    {config.main_model}")
    print(f"  Base URL: {config.base_url}")
    print(f"  Data dir: {config.data_dir}")
    if config.config_file.exists():
        print(f"  Config:   {config.config_file}")
    if reload_enabled:
        print(f"  Reload:   ENABLED (watching {', '.join(reload_dirs or [])})")
    else:
        print("  Reload:   disabled (set CT_RELOAD=1 to enable)")
    print()
    print(f"  Open http://{config.host}:{config.port}/ in your browser")
    print()

    if reload_enabled:
        uvicorn.run(
            "backend.ws_server:create_app",
            host=config.host,
            port=config.port,
            log_level="info",
            reload=True,
            reload_dirs=reload_dirs,
            factory=True,
        )
    else:
        # Use asyncio + uvicorn.Server directly — uvicorn.run() installs
        # signal handlers that are very slow on Python 3.14.
        import asyncio
        from backend.ws_server import app

        server = uvicorn.Server(
            uvicorn.Config(app, host=config.host, port=config.port, log_level="info")
        )
        asyncio.run(server.serve())


if __name__ == "__main__":
    main()
