"""Agent definition store — CRUD for agents.json."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from backend.types import AgentDefinition

logger = logging.getLogger(__name__)

# ─── Default agents (written on first run) ───

_DEFAULT_AGENTS: list[dict] = [
    {
        "agent_id": "main",
        "name": "通用助手",
        "role": "assistant",
        "system_prompt": "",  # filled dynamically by _build_system_prompt
        "provider": None,
        "model": None,
        "temperature": 0.7,
        "tools": [
            "read_file", "write_file", "edit_file",
            "run_console", "grep_search", "find_files", "list_directory",
            "delegate_agent",
        ],
        "max_tool_rounds": 50,
        "color": "#4a9eff",
        "description": "通用编程助手，拥有全部工具权限",
    },
    {
        "agent_id": "researcher",
        "name": "研究员",
        "role": "researcher",
        "system_prompt": "",
        "provider": None,
        "model": None,
        "temperature": 0.3,
        "tools": ["read_file", "grep_search", "find_files", "list_directory"],
        "max_tool_rounds": 30,
        "color": "#9ece6a",
        "description": "只读研究角色，用于分析代码库和搜索信息",
    },
    {
        "agent_id": "coder",
        "name": "编码专家",
        "role": "coder",
        "system_prompt": "",
        "provider": None,
        "model": None,
        "temperature": 0.5,
        "tools": ["read_file", "write_file", "edit_file", "run_console"],
        "max_tool_rounds": 50,
        "color": "#e0af68",
        "description": "专注编码实现，拥有文件读写和命令执行权限",
    },
]


class AgentStore:
    """Manages agent definitions persisted in agents.json."""

    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._file = data_dir / "agents.json"
        self._agents: dict[str, AgentDefinition] = {}
        self._load()

    # ─── Public API ───

    def list_agents(self) -> list[AgentDefinition]:
        return list(self._agents.values())

    def get_agent(self, agent_id: str) -> AgentDefinition | None:
        return self._agents.get(agent_id)

    def save_agent(self, definition: AgentDefinition) -> None:
        self._agents[definition.agent_id] = definition
        self._persist()
        logger.info("Agent saved: %s", definition.agent_id)

    def delete_agent(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        if agent_id == "main":
            raise ValueError("Cannot delete the default 'main' agent")
        del self._agents[agent_id]
        self._persist()
        logger.info("Agent deleted: %s", agent_id)
        return True

    # ─── Internal ───

    def _load(self) -> None:
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text(encoding="utf-8"))
                for item in data:
                    agent = AgentDefinition.from_dict(item)
                    self._agents[agent.agent_id] = agent
                logger.info("Loaded %d agents from %s", len(self._agents), self._file)
            except Exception:
                logger.warning("Failed to load agents.json, using defaults", exc_info=True)
                self._write_defaults()
        else:
            self._write_defaults()

    def _write_defaults(self) -> None:
        for item in _DEFAULT_AGENTS:
            agent = AgentDefinition.from_dict(item)
            self._agents[agent.agent_id] = agent
        self._persist()
        logger.info("Created default agents.json with %d agents", len(self._agents))

    def _persist(self) -> None:
        """Atomic write: temp file + os.replace."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        data = [a.to_dict() for a in self._agents.values()]
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(self._data_dir), suffix=".tmp"
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, str(self._file))
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
