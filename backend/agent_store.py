"""Agent 定义存储——agents.json 的 CRUD 操作。"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from backend.types import AgentDefinition

logger = logging.getLogger(__name__)

# ─── 默认 Agent（首次运行时写入） ───

_DEFAULT_AGENTS: list[dict] = [
    {
        "agent_id": "main",
        "name": "通用助手",
        "role": "assistant",
        "system_prompt": "",  # filled dynamically by build_system_prompt
        "provider": None,
        "model": None,
        "temperature": 0.7,
        "tools": [
            "read_file", "write_file", "edit_file",
            "run_console", "grep_search", "find_files", "list_directory",
            "delegate_agent",
        ],
        "max_tool_rounds": 50,
        "max_context": None,
        "color": "#4a9eff",
        "description": "通用编程助手，拥有全部工具权限",
        "permissions": None,  # None = 无额外限制（完全向后兼容）
    },
    {
        "agent_id": "planner",
        "name": "方案规划师",
        "role": "planner",
        "system_prompt": "",
        "provider": None,
        "model": None,
        "temperature": 0.7,
        "tools": [
            "read_file", "grep_search", "find_files", "list_directory",
            "delegate_agent",
        ],
        "max_tool_rounds": 30,
        "max_context": None,
        "color": "#f0a040",
        "description": "只读探索 + 委派：拆解任务、分析需求、产出结构化计划",
        "permissions": {
            "max_command_risk": "read_only",
            "allow_delegation": True,
            "allow_handoff": False,
        },
    },
    {
        "agent_id": "coder",
        "name": "编码专家",
        "role": "coder",
        "system_prompt": "",
        "provider": None,
        "model": None,
        "temperature": 0.3,
        "tools": [
            "read_file", "write_file", "edit_file",
            "run_console", "grep_search", "find_files", "list_directory",
        ],
        "max_tool_rounds": 80,
        "max_context": None,
        "color": "#50c878",
        "description": "专注编码实现，不允许委派给其他 Agent",
        "permissions": {
            "max_command_risk": "normal",
            "allow_delegation": False,
            "allow_handoff": True,
        },
    },
    {
        "agent_id": "reviewer",
        "name": "代码审查员",
        "role": "reviewer",
        "system_prompt": "",
        "provider": None,
        "model": None,
        "temperature": 0.3,
        "tools": [
            "read_file", "grep_search", "find_files", "list_directory",
            "run_console",
        ],
        "max_tool_rounds": 30,
        "max_context": None,
        "color": "#d080f0",
        "description": "只读审查：检查 diff 质量、安全性、风格一致性",
        "permissions": {
            "max_command_risk": "read_only",
            "allow_delegation": False,
            "allow_handoff": True,
        },
    },
]


class AgentStore:
    """管理持久化在 agents.json 中的 Agent 定义。"""

    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._file = data_dir / "agents.json"
        self._agents: dict[str, AgentDefinition] = {}
        self._load()

    # ─── 公开接口 ───

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
            raise ValueError("不能删除默认的 'main' Agent")
        del self._agents[agent_id]
        self._persist()
        logger.info("Agent 已删除: %s", agent_id)
        return True

    # ─── 内部方法 ───

    def _load(self) -> None:
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text(encoding="utf-8"))
                for item in data:
                    agent = AgentDefinition.from_dict(item)
                    self._agents[agent.agent_id] = agent
                logger.info("Loaded %d agents from %s", len(self._agents), self._file)
            except Exception:
                logger.warning("加载 agents.json 失败，使用默认值", exc_info=True)
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
        """原子写入：临时文件 + os.replace。"""
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
