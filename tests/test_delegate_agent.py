from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from backend.agent_store import AgentStore
from backend.config import AppConfig
from backend.orchestrator import AgentOrchestrator
from backend.safety.file_staging import FileStagingArea
from backend.safety.permission import PermissionManager
from backend.tools import TOOL_REGISTRY
from backend.tools.delegate import DelegateTool
from backend.types import AgentDefinition, AgentResult, Phase, Session, TokenUsage, ToolContext


class FakeBroadcast:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def __call__(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))


class DelegateAgentTests(IsolatedAsyncioTestCase):
    async def test_delegate_tool_invokes_runner(self) -> None:
        session = Session(id="sess-1", work_dir=Path("."))
        calls: list[tuple[str, str, str]] = []

        async def fake_runner(*, agent_id: str, task: str, context: str = "") -> str:
            calls.append((agent_id, task, context))
            return f"{agent_id}:{task}:{context or '(none)'}"

        tool = DelegateTool(
            ToolContext(
                session=session,
                work_dir=Path("."),
                delegate_runner=fake_runner,
            )
        )

        success, result = await tool.execute(
            agent_id="researcher",
            task="find the main entry point",
            context="app startup",
        )

        self.assertTrue(success)
        self.assertIn("researcher:find the main entry point:app startup", result)
        self.assertEqual(calls, [("researcher", "find the main entry point", "app startup")])

    async def test_delegate_tool_rejects_missing_runner(self) -> None:
        session = Session(id="sess-2", work_dir=Path("."))
        tool = DelegateTool(
            ToolContext(
                session=session,
                work_dir=Path("."),
            )
        )

        success, result = await tool.execute(agent_id="researcher", task="inspect")

        self.assertFalse(success)
        self.assertIn("当前上下文不支持委派", result)

    async def test_orchestrator_delegated_agent_is_read_only(self) -> None:
        with TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            session = Session(id="session-1", work_dir=work_dir)
            session.phase = Phase.THINKING

            researcher = AgentDefinition(
                agent_id="researcher",
                name="研究员",
                role="researcher",
                model=None,
                provider=None,
                temperature=0.2,
                tools=[
                    "read_file",
                    "write_file",
                    "edit_file",
                    "run_console",
                    "grep_search",
                    "find_files",
                    "list_directory",
                ],
                max_tool_rounds=10,
                color="#9ece6a",
                system_prompt="",
            )

            class FakeStore:
                def __init__(self, agent: AgentDefinition) -> None:
                    self.agent = agent

                def get_agent(self, agent_id: str) -> AgentDefinition | None:
                    if agent_id == "researcher":
                        return self.agent
                    if agent_id == "main":
                        return AgentDefinition(
                            agent_id="main",
                            name="通用助手",
                            role="assistant",
                            model=None,
                            provider=None,
                            temperature=0.7,
                            tools=["read_file", "write_file", "edit_file", "run_console"],
                            max_tool_rounds=20,
                            color="#4a9eff",
                            system_prompt="",
                        )
                    return None

            config = AppConfig()
            config.provider = "openai"
            config.api_key = "test-key"
            config.base_url = "https://example.invalid/v1"
            config.main_model = "shared-model"
            config.research_model = "shared-model"
            config.coder_model = "shared-model"
            store = FakeStore(researcher)
            broadcast = FakeBroadcast()

            class FakeAgent:
                instances: list["FakeAgent"] = []

                def __init__(self, llm, *, model: str, temperature: float, max_tool_rounds: int, agent_id: str, role: str, agent_name: str):
                    self.llm = llm
                    self.model = model
                    self.temperature = temperature
                    self.max_tool_rounds = max_tool_rounds
                    self.agent_id = agent_id
                    self.role = role
                    self.agent_name = agent_name
                    self.tools = []
                    self.system_prompt = ""
                    self.last_tool_context = None
                    self.last_user_message = None
                    FakeAgent.instances.append(self)

                async def run(
                    self,
                    *,
                    user_message: str,
                    tool_context: ToolContext,
                    existing_messages,
                    max_tool_rounds: int,
                    on_text,
                    on_thinking,
                    on_tool_call,
                    on_tool_result,
                ) -> AgentResult:
                    self.last_user_message = user_message
                    self.last_tool_context = tool_context
                    tool_names = [tool.name for tool in self.tools]
                    self.tool_names = tool_names
                    self.assert_read_only_toolset(tool_names)
                    self.assert_read_only_context(tool_context)
                    await on_text("researching")
                    await on_thinking("checking files")
                    return AgentResult(
                        text="found the entry point",
                        thinking="",
                        tool_calls_history=[],
                        usage=TokenUsage(input_tokens=3, output_tokens=7),
                        messages=[{"role": "assistant", "content": "found the entry point"}],
                    )

                @staticmethod
                def assert_read_only_toolset(tool_names: list[str]) -> None:
                    assert "write_file" not in tool_names
                    assert "edit_file" not in tool_names
                    assert "run_console" not in tool_names
                    assert "read_file" in tool_names
                    assert "grep_search" in tool_names

                @staticmethod
                def assert_read_only_context(tool_context: ToolContext) -> None:
                    assert tool_context.staging is None
                    assert tool_context.permission_mgr is None
                    assert tool_context.delegate_runner is None

            orchestrator = AgentOrchestrator(
                config=config,
                llm=object(),
                agent_store=store,
                permission_managers={},
            )

            with patch("backend.orchestrator.Agent", FakeAgent):
                result = await orchestrator._run_delegated_agent(
                    session=session,
                    broadcast=broadcast,
                    parent_agent_id="main",
                    agent_id="researcher",
                    task="find the startup path",
                    context="focus on backend entrypoints",
                )

            self.assertIn("Delegated agent '研究员'", result)
            self.assertIn("found the entry point", result)
            self.assertEqual(session.usage_total.input_tokens, 3)
            self.assertEqual(session.usage_total.output_tokens, 7)
            self.assertTrue(any(event[0] == "agent.started" and event[1].get("delegated") for event in broadcast.events))
            self.assertTrue(any(event[0] == "agent.completed" and event[1].get("delegated") for event in broadcast.events))
            self.assertEqual(len(FakeAgent.instances), 1)
            self.assertEqual(FakeAgent.instances[0].tool_names.count("write_file"), 0)

    async def test_orchestrator_handoff_agent_reuses_write_safety_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            session = Session(id="session-handoff", work_dir=work_dir)
            session.phase = Phase.THINKING

            coder = AgentDefinition(
                agent_id="coder",
                name="编码专家",
                role="coder",
                model=None,
                provider=None,
                temperature=0.5,
                tools=["read_file", "write_file", "edit_file", "run_console", "delegate_agent"],
                max_tool_rounds=10,
                color="#e0af68",
                system_prompt="",
            )

            class FakeStore:
                def get_agent(self, agent_id: str) -> AgentDefinition | None:
                    if agent_id == "coder":
                        return coder
                    if agent_id == "main":
                        return AgentDefinition(
                            agent_id="main",
                            name="通用助手",
                            role="assistant",
                            tools=["delegate_agent"],
                        )
                    return None

            config = AppConfig()
            config.provider = "openai"
            config.api_key = "test-key"
            config.base_url = "https://example.invalid/v1"
            config.main_model = "shared-model"
            config.coder_model = "shared-model"
            broadcast = FakeBroadcast()
            staging = FileStagingArea(work_dir)
            permission_mgr = PermissionManager(broadcast=broadcast, yolo_mode=True)

            class FakeAgent:
                instances: list["FakeAgent"] = []

                def __init__(self, llm, *, model: str, temperature: float, max_tool_rounds: int, agent_id: str, role: str, agent_name: str):
                    self.tools = []
                    self.system_prompt = ""
                    self.agent_id = agent_id
                    self.role = role
                    self.agent_name = agent_name
                    self.tool_names: list[str] = []
                    self.last_tool_context: ToolContext | None = None
                    self.last_user_message = ""
                    FakeAgent.instances.append(self)

                async def run(
                    self,
                    *,
                    user_message: str,
                    tool_context: ToolContext,
                    existing_messages,
                    max_tool_rounds: int,
                    on_text,
                    on_thinking,
                    on_tool_call,
                    on_tool_result,
                ) -> AgentResult:
                    self.last_user_message = user_message
                    self.last_tool_context = tool_context
                    self.tool_names = [tool.name for tool in self.tools]
                    await on_text("coding")
                    return AgentResult(
                        text="implemented delegated change",
                        thinking="",
                        tool_calls_history=[],
                        usage=TokenUsage(input_tokens=5, output_tokens=11),
                        messages=[{"role": "assistant", "content": "implemented delegated change"}],
                    )

            orchestrator = AgentOrchestrator(
                config=config,
                llm=object(),
                agent_store=FakeStore(),
                permission_managers={},
            )

            with patch("backend.orchestrator.Agent", FakeAgent):
                result = await orchestrator._run_handoff_agent(
                    session=session,
                    broadcast=broadcast,
                    parent_agent_id="main",
                    agent_id="coder",
                    task="implement a focused change",
                    context="touch one file only",
                    staging=staging,
                    permission_mgr=permission_mgr,
                )

            self.assertIn("Delegated agent '编码专家'", result)
            self.assertIn("implemented delegated change", result)
            self.assertEqual(session.usage_total.input_tokens, 5)
            self.assertEqual(session.usage_total.output_tokens, 11)
            self.assertEqual(len(FakeAgent.instances), 1)
            fake_agent = FakeAgent.instances[0]
            self.assertIn("write_file", fake_agent.tool_names)
            self.assertIn("edit_file", fake_agent.tool_names)
            self.assertIn("run_console", fake_agent.tool_names)
            self.assertNotIn("delegate_agent", fake_agent.tool_names)
            self.assertIs(fake_agent.last_tool_context.staging, staging)
            self.assertIs(fake_agent.last_tool_context.permission_mgr, permission_mgr)
            self.assertIsNone(fake_agent.last_tool_context.delegate_runner)
            self.assertIn("[Handoff task from main]", fake_agent.last_user_message)
            self.assertIn("Do not delegate further", fake_agent.last_user_message)
            event_types = [event_type for event_type, _ in broadcast.events]
            self.assertIn("handoff.started", event_types)
            self.assertIn("handoff.completed", event_types)
            self.assertNotIn("handoff.failed", event_types)
            completed = [payload for event_type, payload in broadcast.events if event_type == "handoff.completed"][0]
            self.assertEqual(completed["agent_id"], "coder")
            self.assertEqual(completed["parent_agent_id"], "main")
            self.assertEqual(completed["text"], "implemented delegated change")

    async def test_run_user_message_dispatches_coder_delegate_to_handoff(self) -> None:
        with TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            main = AgentDefinition(
                agent_id="main",
                name="通用助手",
                role="assistant",
                tools=["delegate_agent"],
            )
            coder = AgentDefinition(
                agent_id="coder",
                name="编码专家",
                role="coder",
                tools=["read_file", "write_file", "edit_file", "run_console", "delegate_agent"],
            )

            class FakeStore:
                def list_agents(self) -> list[AgentDefinition]:
                    return [main, coder]

                def get_agent(self, agent_id: str) -> AgentDefinition | None:
                    if agent_id == "main":
                        return main
                    if agent_id == "coder":
                        return coder
                    return None

            config = AppConfig()
            config.provider = "openai"
            config.api_key = "test-key"
            config.base_url = "https://example.invalid/v1"
            config.main_model = "shared-model"
            config.coder_model = "shared-model"
            session = Session(id="session-flow-handoff", work_dir=work_dir, solo_mode=False)
            broadcast = FakeBroadcast()

            class FakeAgent:
                handoff_tool_names: list[str] = []

                def __init__(self, llm, *, model: str, temperature: float, max_tool_rounds: int, agent_id: str, role: str, agent_name: str):
                    self.agent_id = agent_id
                    self.role = role
                    self.tools = []
                    self.system_prompt = ""

                async def run(
                    self,
                    *,
                    user_message: str,
                    tool_context: ToolContext,
                    existing_messages,
                    max_tool_rounds: int,
                    on_text,
                    on_thinking,
                    on_tool_call,
                    on_tool_result,
                ) -> AgentResult:
                    if self.agent_id == "main":
                        delegated = await tool_context.delegate_runner(
                            agent_id="coder",
                            task="implement focused change",
                            context="from main flow",
                        )
                        await on_text("main saw " + delegated)
                        return AgentResult(
                            text="main completed",
                            thinking="",
                            tool_calls_history=[],
                            usage=TokenUsage(input_tokens=1, output_tokens=2),
                            messages=[
                                {"role": "user", "content": user_message},
                                {"role": "assistant", "content": "main completed"},
                            ],
                        )

                    FakeAgent.handoff_tool_names = [tool.name for tool in self.tools]
                    self.assert_handoff_context(tool_context)
                    await on_text("coder done")
                    return AgentResult(
                        text="coder done",
                        thinking="",
                        tool_calls_history=[],
                        usage=TokenUsage(input_tokens=3, output_tokens=4),
                        messages=[{"role": "assistant", "content": "coder done"}],
                    )

                @staticmethod
                def assert_handoff_context(tool_context: ToolContext) -> None:
                    assert tool_context.staging is not None
                    assert tool_context.permission_mgr is not None
                    assert tool_context.delegate_runner is None

            orchestrator = AgentOrchestrator(
                config=config,
                llm=object(),
                agent_store=FakeStore(),
                permission_managers={},
            )

            with patch("backend.orchestrator.Agent", FakeAgent):
                await orchestrator.run_user_message(
                    session=session,
                    text="please implement this",
                    agent_id="main",
                    broadcast=broadcast,
                )

            self.assertIn("write_file", FakeAgent.handoff_tool_names)
            self.assertNotIn("delegate_agent", FakeAgent.handoff_tool_names)
            event_types = [event_type for event_type, _ in broadcast.events]
            self.assertIn("handoff.started", event_types)
            self.assertIn("handoff.completed", event_types)
            self.assertIn("agent.completed", event_types)
            self.assertEqual(session.phase, Phase.READY)
            self.assertEqual(session.usage_total.input_tokens, 4)
            self.assertEqual(session.usage_total.output_tokens, 6)

    def test_tool_registry_contains_delegate_agent(self) -> None:
        self.assertIn("delegate_agent", TOOL_REGISTRY)
