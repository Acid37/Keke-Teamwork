"""WebSocket server — handles frontend connections and dispatches to orchestrator."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from backend.agent_store import AgentStore
from backend.config import AppearanceConfig, AppConfig
from backend.llm.client import LLMClient
from backend.orchestrator import AgentOrchestrator
from backend.safety.permission import PermissionManager
from backend.session import SessionStore
from backend.tools import ALL_TOOLS
from backend.types import (
    AgentDefinition,
    Phase,
    Session,
)
from backend.assets import (
    PRESETS as WALLPAPER_PRESETS,
    ensure_presets as ensure_wallpaper_presets,
    get_preset_dir as get_wallpaper_preset_dir,
    resolve_preset_path as resolve_wallpaper_preset,
)

logger = logging.getLogger(__name__)


class WebSocketServer:
    """WebSocket server that bridges frontend ↔ Agent runtime."""

    def __init__(self, config: AppConfig):
        self._config = config
        self._llm = self._create_llm(config)
        self._store = SessionStore(config.data_dir)
        self._agent_store = AgentStore(config.data_dir)
        self._appearance = AppearanceConfig.load()
        self._active_sessions: dict[str, Session] = {}
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._permission_managers: dict[str, PermissionManager] = {}
        self._orchestrator = self._create_orchestrator()

    @staticmethod
    def _create_llm(config: AppConfig) -> LLMClient:
        return LLMClient(
            provider=config.provider,
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.main_model,
        )

    def _reload_llm(self) -> None:
        """Recreate the LLM client after config change."""
        self._llm = self._create_llm(self._config)
        self._orchestrator = self._create_orchestrator()

    def _create_orchestrator(self) -> AgentOrchestrator:
        return AgentOrchestrator(
            config=self._config,
            llm=self._llm,
            agent_store=self._agent_store,
            permission_managers=self._permission_managers,
        )

    def create_app(self) -> FastAPI:
        """Create the FastAPI app with WebSocket endpoint."""
        app = FastAPI(title="Coding Teamwork")

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @app.websocket("/ws")
        async def ws_endpoint(websocket: WebSocket):
            await websocket.accept()
            await self._handle_connection(websocket)

        @app.get("/api/sessions")
        async def list_sessions():
            return self._store.list_sessions()

        @app.delete("/api/sessions/{session_id}")
        async def delete_session_http(session_id: str):
            self._store.delete(session_id)
            if session_id in self._active_sessions:
                del self._active_sessions[session_id]
            return {"status": "ok"}

        @app.get("/api/config")
        async def get_config():
            return self._config.to_dict()

        @app.put("/api/config")
        async def update_config(request: Request):
            """Update config fields and reload LLM client.

            Accepts a JSON body with any subset of config fields.
            The api_key field is only updated if it doesn't contain '****'
            (i.e. if the user actually typed a new key).
            """
            body = await request.json()
            updates = {}
            for key in ("provider", "base_url", "main_model", "coder_model", "research_model"):
                if key in body:
                    updates[key] = body[key] or None
            # API key: only update if user provided a new one (not masked)
            if "api_key" in body:
                new_key = body["api_key"]
                if new_key and "****" not in new_key:
                    updates["api_key"] = new_key

            self._config.update(**updates)
            self._reload_llm()
            logger.info("Config updated: %s", list(updates.keys()))
            return {"status": "ok", "config": self._config.to_dict()}

        @app.get("/api/models")
        async def list_models():
            """Fetch available models from the configured API."""
            import httpx

            cfg = self._config
            # Anthropic doesn't have a models listing endpoint
            if cfg.provider == "anthropic":
                return {"models": [
                    "claude-sonnet-4-20250514",
                    "claude-opus-4-20250514",
                    "claude-3-5-sonnet-20241022",
                    "claude-3-5-haiku-20241022",
                ]}

            # OpenAI-compatible: GET {base_url}/models
            try:
                base = cfg.base_url.rstrip("/")
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        f"{base}/models",
                        headers={"Authorization": f"Bearer {cfg.api_key}"},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    models = [m["id"] for m in data.get("data", [])]
                    models.sort()
                    return {"models": models}
            except Exception as e:
                logger.warning("Failed to fetch models: %s", e)
                return {"models": [], "error": str(e)}

        # ─── Agent CRUD ───

        @app.get("/api/agents")
        async def list_agents():
            agents = self._agent_store.list_agents()
            return {"agents": [a.to_dict() for a in agents]}

        @app.post("/api/agents")
        async def create_agent(request: Request):
            body = await request.json()
            try:
                definition = AgentDefinition.from_dict(body)
                if not definition.agent_id:
                    return JSONResponse({"error": "agent_id is required"}, status_code=400)
                existing = self._agent_store.get_agent(definition.agent_id)
                if existing:
                    return JSONResponse(
                        {"error": f"Agent '{definition.agent_id}' already exists"},
                        status_code=409,
                    )
                self._agent_store.save_agent(definition)
                return {"status": "ok", "agent": definition.to_dict()}
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=400)

        @app.get("/api/agents/{agent_id}")
        async def get_agent(agent_id: str):
            agent = self._agent_store.get_agent(agent_id)
            if not agent:
                return JSONResponse(
                    {"error": f"Agent '{agent_id}' not found"}, status_code=404
                )
            return {"agent": agent.to_dict()}

        @app.put("/api/agents/{agent_id}")
        async def update_agent(agent_id: str, request: Request):
            body = await request.json()
            existing = self._agent_store.get_agent(agent_id)
            if not existing:
                return JSONResponse(
                    {"error": f"Agent '{agent_id}' not found"}, status_code=404
                )
            # Merge body into existing definition
            for key, value in body.items():
                if hasattr(existing, key) and key != "agent_id":
                    setattr(existing, key, value)
            self._agent_store.save_agent(existing)
            return {"status": "ok", "agent": existing.to_dict()}

        @app.delete("/api/agents/{agent_id}")
        async def delete_agent(agent_id: str):
            try:
                deleted = self._agent_store.delete_agent(agent_id)
                if not deleted:
                    return JSONResponse(
                        {"error": f"Agent '{agent_id}' not found"}, status_code=404
                    )
                return {"status": "ok"}
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)

        @app.get("/api/tools")
        async def list_tools():
            tools = []
            for cls in ALL_TOOLS:
                tools.append({
                    "name": cls.name,
                    "description": cls.description,
                    "parameters": cls.parameters,
                })
            return {"tools": tools}

        # ─── Appearance API ───

        @app.get("/api/appearance")
        async def get_appearance():
            return self._appearance.to_dict()

        @app.put("/api/appearance")
        async def update_appearance(request: Request):
            body = await request.json()
            self._appearance.update(**body)
            logger.info("Appearance updated: %s", list(body.keys()))
            return {"status": "ok", "appearance": self._appearance.to_dict()}

        @app.get("/api/wallpaper/status")
        async def wallpaper_status():
            """Return structured wallpaper state: existence + type + filename."""
            fname = self._appearance.wallpaper
            if not fname:
                return {
                    "has_wallpaper": False,
                    "wallpaper_type": "none",
                    "wallpaper_filename": None,
                    "wallpaper_blur": self._appearance.wallpaper_blur,
                    "wallpaper_opacity": self._appearance.wallpaper_opacity,
                }
            ext = Path(fname).suffix.lower()
            kind = "video" if ext in {".mp4", ".webm"} else "image"
            return {
                "has_wallpaper": True,
                "wallpaper_type": kind,
                "wallpaper_filename": fname,
                "wallpaper_blur": self._appearance.wallpaper_blur,
                "wallpaper_opacity": self._appearance.wallpaper_opacity,
            }

        @app.post("/api/wallpaper")
        async def upload_wallpaper(file: UploadFile = File(...)):
            """Upload a wallpaper (image or video). Saves to data_dir/wallpapers/.

            Returns the *full* updated appearance config so the frontend
            can sync state immediately (no need to wait for debounced save).
            """
            wallpapers_dir = self._config.data_dir / "wallpapers"
            wallpapers_dir.mkdir(parents=True, exist_ok=True)

            image_exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
            video_exts = {".mp4", ".webm"}
            all_exts = image_exts | video_exts

            filename = Path(file.filename or "wallpaper").name
            ext = Path(filename).suffix.lower()
            if ext not in all_exts:
                return JSONResponse(
                    {"error": f"Unsupported format. Allowed: {', '.join(sorted(all_exts))}"},
                    status_code=400,
                )

            content = await file.read()
            is_video = ext in video_exts
            max_size = 50 * 1024 * 1024 if is_video else 10 * 1024 * 1024
            if len(content) > max_size:
                kind_cn = "视频" if is_video else "图片"
                max_mb = max_size // (1024 * 1024)
                return JSONResponse(
                    {"error": f"壁纸{kind_cn}过大（最大 {max_mb}MB）"},
                    status_code=400,
                )

            dest = wallpapers_dir / f"wallpaper{ext}"
            dest.write_bytes(content)

            # Remove any older wallpaper with a different extension
            for old in wallpapers_dir.glob("wallpaper.*"):
                if old != dest:
                    try:
                        old.unlink()
                    except OSError:
                        pass

            filename_saved = dest.name
            self._appearance.wallpaper = filename_saved
            self._appearance.save()
            return {
                "status": "ok",
                "filename": filename_saved,
                "wallpaper_type": "video" if is_video else "image",
                "appearance": self._appearance.to_dict(),
            }

        @app.get("/api/wallpaper")
        async def get_wallpaper():
            """Serve the current wallpaper file (no-cache). Auto-heals: if
            the file is missing but config still references it, clear it."""
            fname = self._appearance.wallpaper
            if not fname:
                return JSONResponse({"error": "No wallpaper set"}, status_code=404)
            wp_path = self._config.data_dir / "wallpapers" / fname
            if not wp_path.exists():
                self._appearance.wallpaper = None
                self._appearance.save()
                logger.warning("Wallpaper file missing, cleared reference: %s", wp_path)
                return JSONResponse({"error": "Wallpaper file not found"}, status_code=404)
            response = FileResponse(wp_path)
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            return response

        @app.delete("/api/wallpaper")
        async def delete_wallpaper():
            """Delete current wallpaper (file + config). Returns updated appearance."""
            if self._appearance.wallpaper:
                wp_path = self._config.data_dir / "wallpapers" / self._appearance.wallpaper
                if wp_path.exists():
                    wp_path.unlink()
                self._appearance.wallpaper = None
                self._appearance.save()
            return {"status": "ok", "appearance": self._appearance.to_dict()}

        # ─── Preset Wallpapers ───

        @app.get("/api/wallpaper/presets")
        async def list_wallpaper_presets():
            """List built-in preset wallpapers."""
            assets_root = Path(__file__).resolve().parent / "assets"
            presets = ensure_wallpaper_presets(assets_root)
            return {"presets": presets}

        @app.get("/api/wallpaper/presets/{preset_id}")
        async def get_wallpaper_preset_file(preset_id: str):
            """Serve a preset wallpaper SVG file (no-cache)."""
            assets_root = Path(__file__).resolve().parent / "assets"
            path = resolve_wallpaper_preset(assets_root, preset_id)
            if path is None or not path.exists():
                return JSONResponse({"error": f"Unknown preset: {preset_id}"}, status_code=404)
            response = FileResponse(path, media_type="image/svg+xml")
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            return response

        @app.post("/api/wallpaper/preset/{preset_id}")
        async def apply_wallpaper_preset(preset_id: str):
            """Apply a built-in preset as the current wallpaper.

            Copies the preset SVG into the user wallpapers directory so
            downstream GET /api/wallpaper keeps working uniformly.
            """
            assets_root = Path(__file__).resolve().parent / "assets"
            src = resolve_wallpaper_preset(assets_root, preset_id)
            if src is None or not src.exists():
                return JSONResponse({"error": f"Unknown preset: {preset_id}"}, status_code=404)

            wallpapers_dir = self._config.data_dir / "wallpapers"
            wallpapers_dir.mkdir(parents=True, exist_ok=True)

            # Remove any old user wallpaper
            for old in wallpapers_dir.glob("wallpaper.*"):
                try:
                    old.unlink()
                except OSError:
                    pass

            dest = wallpapers_dir / "wallpaper.svg"
            dest.write_bytes(src.read_bytes())

            self._appearance.wallpaper = dest.name
            self._appearance.save()
            return {"status": "ok", "filename": dest.name, "appearance": self._appearance.to_dict()}

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        # ─── Work directory picker ───

        @app.post("/api/workdir/dialog")
        async def pick_workdir():
            """Open a native folder-picker and return the chosen path.

            Uses tkinter.filedialog (built into Python on most platforms,
            including Windows). Falls back to returning the current working
            directory on headless systems.
            """
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                # Lift above any fullscreen windows
                root.attributes("-topmost", True)
                path = filedialog.askdirectory(
                    title="选择工作目录",
                    mustexist=True,
                )
                root.destroy()
                if not path:
                    return {"path": None, "cancelled": True}
                return {"path": str(Path(path).resolve()), "cancelled": False}
            except Exception as e:
                logger.warning("Native folder picker failed: %s", e)
                return JSONResponse(
                    {"error": str(e), "path": None, "cancelled": True},
                    status_code=200,  # Don't surface as error — return best-effort
                )

        # Serve frontend static files (production build)
        # All static responses carry Cache-Control: no-store so the browser
        # always re-fetches when the user reopens the app — prevents the
        # "still seeing the old UI after rebuild" trap.
        frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
        if frontend_dist.exists():
            _NO_CACHE = "no-store, no-cache, must-revalidate, max-age=0"

            @app.get("/")
            async def serve_index():
                response = HTMLResponse((frontend_dist / "index.html").read_text(encoding="utf-8"))
                response.headers["Cache-Control"] = _NO_CACHE
                return response

            @app.get("/favicon.ico")
            async def serve_favicon_ico():
                ico_path = frontend_dist / "favicon.ico"
                if ico_path.exists():
                    return FileResponse(ico_path, media_type="image/x-icon", headers={"Cache-Control": _NO_CACHE})
                return JSONResponse({"error": "Not found"}, status_code=404)

            @app.get("/favicon.png")
            async def serve_favicon_png():
                png_path = frontend_dist / "favicon.png"
                if png_path.exists():
                    return FileResponse(png_path, media_type="image/png", headers={"Cache-Control": _NO_CACHE})
                return JSONResponse({"error": "Not found"}, status_code=404)

            # Serve /assets/* with no-cache. We mount StaticFiles for the path
            # resolution and wrap it with a middleware that injects the header.
            from starlette.types import ASGIApp, Receive, Scope, Send

            class NoCacheStaticMiddleware:
                """Inject Cache-Control: no-store into every static asset response."""

                def __init__(self, app: ASGIApp):
                    self.app = app

                async def __call__(self, scope: Scope, receive: Receive, send: Send):
                    if scope["type"] != "http":
                        await self.app(scope, receive, send)
                        return

                    async def send_wrapper(message):
                        if message["type"] == "response.headers":
                            headers = list(message.get("headers", []))
                            # Drop any existing cache directives
                            headers = [
                                (k, v) for (k, v) in headers
                                if k.lower() not in (b"cache-control", b"etag", b"last-modified")
                            ]
                            headers.append((b"cache-control", _NO_CACHE.encode("latin-1")))
                            message["headers"] = headers
                        await send(message)

                    await self.app(scope, receive, send_wrapper)

            app.add_middleware(NoCacheStaticMiddleware)
            app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="static")

        return app

    async def _handle_connection(self, ws: WebSocket) -> None:
        """Handle a single WebSocket connection."""
        session: Session | None = None
        client_id = uuid4().hex[:8]
        logger.info("Client connected: %s", client_id)

        try:
            async for raw in ws.iter_text():
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await self._send_error(ws, "Invalid JSON")
                    continue

                msg_type = msg.get("type", "")
                payload = msg.get("payload", {})

                try:
                    match msg_type:
                        case "session.init":
                            session = await self._handle_session_init(
                                ws, payload
                            )

                        case "user.message":
                            if not session:
                                await self._send_error(ws, "No active session")
                                continue
                            text = payload.get("text", "")
                            agent_id = payload.get("agent_id", "main")
                            if text:
                                # Run agent in background task
                                task = asyncio.create_task(
                                    self._handle_user_message(
                                        ws, session, text, agent_id
                                    )
                                )
                                self._running_tasks[session.id] = task

                        case "user.interrupt":
                            if session:
                                await self._handle_interrupt(session)

                        case "session.list":
                            sessions = self._store.list_sessions()
                            await self._send(ws, "session.list", {
                                "sessions": sessions,
                            })

                        case "session.delete":
                            await self._handle_session_delete(ws, payload)
                            sessions = self._store.list_sessions()
                            await self._send(ws, "session.list", {
                                "sessions": sessions,
                            })

                        case "project.open":
                            session = await self._handle_project_open(ws, payload)

                        case "browse.directory":
                            await self._handle_browse_directory(ws, payload)

                        case "auto_review.toggle":
                            if session:
                                session.auto_review = payload.get("enabled", True)
                                self._store.save(session)

                        case "yolo.toggle":
                            if session:
                                session.yolo_mode = payload.get("enabled", False)
                                manager = self._permission_managers.get(session.id)
                                if manager:
                                    manager.set_yolo_mode(session.yolo_mode)
                                self._store.save(session)

                        case "solo.toggle":
                            if session:
                                session.solo_mode = payload.get("enabled", False)
                                self._store.save(session)

                        case "approval.response":
                            if session:
                                manager = self._permission_managers.get(session.id)
                                if manager:
                                    manager.resolve(
                                        payload.get("request_id", ""),
                                        bool(payload.get("approved", False)),
                                    )

                        case _:
                            logger.warning(
                                "Unknown message type: %s", msg_type
                            )

                except Exception as e:
                    logger.exception("Error handling message %s", msg_type)
                    await self._send_error(ws, str(e))

        except WebSocketDisconnect:
            logger.info("Client disconnected: %s", client_id)
        except Exception:
            logger.exception("WebSocket connection error")
        finally:
            # Clean up running tasks
            if session and session.id in self._running_tasks:
                task = self._running_tasks.pop(session.id)
                task.cancel()

    # ─── Message handlers ───

    async def _handle_project_open(
        self, ws: WebSocket, payload: dict
    ) -> Session:
        """Open a project directory. Reuses the most recent session for the
        same work_dir if one exists; otherwise creates a new one."""
        work_dir_str = payload.get("working_directory", ".")
        work_dir = Path(work_dir_str).resolve()

        # Look for an existing session with the same work_dir
        existing = None
        for s in self._store.list_sessions():
            if s.get("work_dir") == str(work_dir):
                existing = self._store.load(s["session_id"])
                if existing:
                    break

        if existing:
            session = existing
            session.last_active_at = time.time()
            self._store.save(session)
        else:
            session = Session(
                id=uuid4().hex[:12],
                work_dir=work_dir,
                title=f"{work_dir.name}",
            )

        self._active_sessions[session.id] = session
        self._store.save(session)
        await self._send_session_ready(ws, session)
        sessions = self._store.list_sessions()
        await self._send(ws, "session.list", {"sessions": sessions})
        return session

    async def _handle_session_delete(self, ws: WebSocket, payload: dict) -> None:
        """Delete a session by id."""
        sid = payload.get("session_id", "")
        if not sid:
            await self._send_error(ws, "session_id is required")
            return
        self._store.delete(sid)
        if sid in self._active_sessions:
            del self._active_sessions[sid]
        logger.info("Session deleted: %s", sid)

    async def _handle_browse_directory(self, ws: WebSocket, payload: dict) -> None:
        """Browse a server-side directory. Returns entries + parent."""
        path_str = payload.get("path", ".")
        try:
            target = Path(path_str)
            if not target.is_absolute():
                target = target.resolve()
        except Exception:
            target = Path.home()

        # Windows drive root: list drives
        if target == Path("/") or str(target).lower() in ("\\", "/") or not target.exists():
            # List drives on Windows
            import os as _os
            drives = []
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                d = Path(f"{letter}:\\")
                if d.exists():
                    drives.append({"name": f"{letter}:\\", "is_dir": True})
            if drives:
                await self._send(ws, "browse.directory_result", {
                    "path": "根目录",
                    "parent": None,
                    "entries": drives,
                })
                return
            target = Path.home()

        try:
            parent = str(target.parent) if target.parent != target else None
            entries = []
            for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                try:
                    if child.name.startswith(".") and child.name not in (".",):
                        continue  # Skip hidden
                    entries.append({"name": child.name, "is_dir": child.is_dir()})
                except PermissionError:
                    continue
            await self._send(ws, "browse.directory_result", {
                "path": str(target),
                "parent": parent,
                "entries": entries,
            })
        except PermissionError:
            await self._send(ws, "browse.directory_result", {
                "path": str(target),
                "parent": None,
                "entries": [],
                "error": "Permission denied",
            })

    async def _handle_session_init(
        self, ws: WebSocket, payload: dict
    ) -> Session:
        """Create or resume a session."""
        session_id = payload.get("session_id")
        work_dir_str = payload.get("work_dir", ".")
        work_dir = Path(work_dir_str).resolve()

        if session_id:
            # Try to resume
            session = self._store.load(session_id)
            if session:
                self._active_sessions[session.id] = session
                await self._send_session_ready(ws, session)
                return session

        # Create new session
        session = Session(
            id=uuid4().hex[:12],
            work_dir=work_dir,
            title=f"Session {time.strftime('%H:%M')}",
        )
        self._active_sessions[session.id] = session
        self._store.save(session)

        await self._send_session_ready(ws, session)

        # Also send session list
        sessions = self._store.list_sessions()
        await self._send(ws, "session.list", {"sessions": sessions})

        return session

    async def _handle_user_message(
        self, ws: WebSocket, session: Session, text: str,
        agent_id: str = "main",
    ) -> None:
        """Process a user message through the orchestrator."""
        async def broadcast(event_type: str, payload: dict):
            await self._send(ws, event_type, payload)

        try:
            await self._orchestrator.run_user_message(
                session=session,
                text=text,
                agent_id=agent_id,
                broadcast=broadcast,
            )

        except Exception as e:
            logger.exception("Orchestrator execution failed")
            session.phase = Phase.ERROR
            await self._send_error(ws, f"Orchestrator error: {e}")
            await self._send(ws, "agent.status", {
                "phase": "error", "detail": str(e),
            })

        finally:
            self._store.save(session)
            await self._send(ws, "session.list", {
                "sessions": self._store.list_sessions(),
            })
            # Clean up running task
            if session.id in self._running_tasks:
                self._running_tasks.pop(session.id, None)
            self._permission_managers.pop(session.id, None)

    async def _handle_interrupt(self, session: Session) -> None:
        """Interrupt the current agent execution."""
        session.interrupt_requested = True
        task = self._running_tasks.get(session.id)
        if task and not task.done():
            task.cancel()
        logger.info("Interrupt requested for session %s", session.id)

    # ─── Helpers ───

    async def _send(self, ws: WebSocket, event_type: str, payload: dict) -> None:
        """Send a JSON message to the client."""
        try:
            msg = {
                "type": event_type,
                "payload": payload,
                "id": uuid4().hex[:8],
            }
            await ws.send_text(json.dumps(msg, ensure_ascii=False))
        except Exception:
            logger.warning("Failed to send WebSocket message: %s", event_type)

    async def _send_error(self, ws: WebSocket, message: str) -> None:
        await self._send(ws, "error", {
            "message": message,
            "recoverable": True,
        })

    async def _send_session_ready(
        self, ws: WebSocket, session: Session
    ) -> None:
        await self._send(ws, "session.ready", {
            "session_id": session.id,
            "title": session.title,
            "phase": session.phase.value,
            "history": session.messages,
            "work_dir": str(session.work_dir),
            "auto_review": session.auto_review,
            "yolo_mode": session.yolo_mode,
            "solo_mode": session.solo_mode,
            "usage": {
                "input_tokens": session.usage_total.input_tokens,
                "output_tokens": session.usage_total.output_tokens,
            },
        })

# ─── ASGI entry points ─────────────────────────────────────────────
# Uvicorn's reload mode requires the app to be importable as a string
# (e.g. "backend.ws_server:app") and a module-level callable. We expose
# both styles here so main.py can pick the right one based on reload
# mode, and so external runners (uvicorn CLI, gunicorn, etc.) work too.

def create_app() -> FastAPI:
    """Module-level factory. uvicorn --factory calls this.

    Reads the latest AppConfig + AppearanceConfig from disk on every
    invocation, which is what we want when the process is reloaded.
    """
    config = AppConfig.load()
    return WebSocketServer(config).create_app()


# Module-level singleton used when reload is disabled (faster startup,
# avoids re-loading config on every import).
_app_config = AppConfig.load()
_app_instance = WebSocketServer(_app_config)
app = _app_instance.create_app()
