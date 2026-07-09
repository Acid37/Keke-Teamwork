from __future__ import annotations

import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from backend.agent_store import AgentStore
from backend.config import AppConfig
from backend.orchestrator import AgentOrchestrator
from backend.types import AgentDefinition, AgentResult, ParallelResearchResult, Session, TokenUsage, ToolContext


class FakeBroadcast:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def __call__(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))


class FakeStore:
    def __init__(self, agents: list[AgentDefinition]) -> None:
        self._agents = {agent.agent_id: agent for agent in agents}

    def list_agents(self) -> list[AgentDefinition]:
        return list(self._agents.values())

    def get_agent(self, agent_id: str) -> AgentDefinition | None:
        return self._agents.get(agent_id)


def make_agent(agent_id: str, role: str = "researcher") -> AgentDefinition:
    return AgentDefinition(
        agent_id=agent_id,
        name=agent_id.title(),
        role=role,
        tools=["read_file", "grep_search", "find_files", "list_directory"],
    )


class MainFlowFakeAgent:
    def __init__(
        self,
        llm,
        *,
        model: str,
        temperature: float,
        max_tool_rounds: int,
        agent_id: str,
        role: str,
        agent_name: str,
    ) -> None:
        self.tools = []
        self.system_prompt = ""
        self.agent_id = agent_id
        self.role = role
        self.agent_name = agent_name

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
        await on_text("main response")
        return AgentResult(
            text="main response",
            thinking="",
            tool_calls_history=[],
            usage=TokenUsage(input_tokens=1, output_tokens=2),
            messages=[
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": "main response"},
            ],
        )


class ParallelResearcherTests(IsolatedAsyncioTestCase):
    async def test_parallel_researchers_return_partial_timeout_results(self) -> None:
        main = make_agent("main", role="assistant")
        researchers = [make_agent("alpha"), make_agent("beta"), make_agent("slow")]
        store = FakeStore([main, *researchers])
        orchestrator = AgentOrchestrator(
            config=AppConfig(),
            llm=object(),
            agent_store=store,
            permission_managers={},
        )
        session = Session(id="parallel-session", work_dir=Path("."))
        broadcast = FakeBroadcast()
        started: list[str] = []

        async def fake_delegated_agent(**kwargs) -> str:
            agent_id = kwargs["agent_id"]
            started.append(agent_id)
            if agent_id == "slow":
                await asyncio.sleep(0.20)
            else:
                await asyncio.sleep(0.01)
            return f"findings from {agent_id}"

        orchestrator._run_delegated_agent = fake_delegated_agent  # type: ignore[method-assign]

        start = time.perf_counter()
        results = await orchestrator.run_parallel_researchers(
            session=session,
            broadcast=broadcast,
            agent_def=main,
            task="inspect orchestration",
            context="unit test",
            timeout=0.05,
            max_workers=3,
        )
        elapsed = time.perf_counter() - start

        self.assertEqual(len(results), 3)
        self.assertLess(elapsed, 0.15)
        self.assertCountEqual(started, ["alpha", "beta", "slow"])

        by_source: dict[str, ParallelResearchResult] = {
            result.metadata["source"]: result for result in results
        }
        self.assertEqual(by_source["alpha"].text, "findings from alpha")
        self.assertEqual(by_source["beta"].text, "findings from beta")
        self.assertFalse(by_source["alpha"].metadata["timed_out"])
        self.assertFalse(by_source["beta"].metadata["timed_out"])
        self.assertTrue(by_source["slow"].metadata["timed_out"])
        self.assertEqual(by_source["slow"].error, "timed out")

        failed_events = [event for event in broadcast.events if event[0] == "research.failed"]
        self.assertEqual(len(failed_events), 1)
        self.assertEqual(failed_events[0][1]["agent_id"], "slow")
        self.assertEqual(failed_events[0][1]["parent_agent_id"], "main")
        self.assertTrue(failed_events[0][1]["timed_out"])
        self.assertEqual(failed_events[0][1]["error"], "timed out")

        merge_candidates = [result.text for result in results if result.text]
        self.assertEqual(merge_candidates, ["findings from alpha", "findings from beta"])

    async def test_parallel_research_broadcasts_lifecycle_events(self) -> None:
        main = make_agent("main", role="assistant")
        researchers = [make_agent("alpha"), make_agent("beta")]
        orchestrator = AgentOrchestrator(
            config=AppConfig(max_parallel_researchers=2),
            llm=object(),
            agent_store=FakeStore([main, *researchers]),
            permission_managers={},
        )
        session = Session(id="broadcast-session", work_dir=Path("."))
        broadcast = FakeBroadcast()

        async def fake_delegated_agent(**kwargs) -> str:
            return f"findings from {kwargs['agent_id']}"

        orchestrator._run_delegated_agent = fake_delegated_agent  # type: ignore[method-assign]

        results = await orchestrator.run_parallel_research(
            session=session,
            broadcast=broadcast,
            agent_id="main",
            task="inspect broadcast events",
            context="unit test",
        )

        self.assertEqual(len(results), 2)
        event_types = [event_type for event_type, _ in broadcast.events]
        self.assertEqual(event_types.count("research.started"), 2)
        self.assertEqual(event_types.count("research.result"), 2)
        self.assertEqual(event_types.count("research.completed"), 1)

        started_payloads = [payload for event_type, payload in broadcast.events if event_type == "research.started"]
        self.assertCountEqual(
            [payload["agent_id"] for payload in started_payloads],
            ["alpha", "beta"],
        )
        for payload in started_payloads:
            self.assertEqual(payload["parent_agent_id"], "main")
            self.assertEqual(payload["task"], "inspect broadcast events")
            self.assertEqual(payload["role"], "researcher")

        result_payloads = [payload for event_type, payload in broadcast.events if event_type == "research.result"]
        self.assertCountEqual(
            [payload["text"] for payload in result_payloads],
            ["findings from alpha", "findings from beta"],
        )
        for payload in result_payloads:
            self.assertFalse(payload["timed_out"])
            self.assertIsNone(payload["error"])

        completed_payload = [payload for event_type, payload in broadcast.events if event_type == "research.completed"][0]
        self.assertEqual(completed_payload["parent_agent_id"], "main")
        self.assertEqual(completed_payload["task"], "inspect broadcast events")
        self.assertEqual(completed_payload["result_count"], 2)
        self.assertCountEqual(completed_payload["successful_sources"], ["alpha", "beta"])
        self.assertEqual(completed_payload["timed_out_sources"], [])
        self.assertEqual(completed_payload["errored_sources"], [])
        self.assertIn("### alpha", completed_payload["merged_text"])
        self.assertIn("### beta", completed_payload["merged_text"])

    async def test_parallel_entry_uses_configured_worker_limit(self) -> None:
        main = make_agent("main", role="assistant")
        researchers = [make_agent("alpha"), make_agent("beta")]
        config = AppConfig(max_parallel_researchers=1)
        orchestrator = AgentOrchestrator(
            config=config,
            llm=object(),
            agent_store=FakeStore([main, *researchers]),
            permission_managers={},
        )
        session = Session(id="entry-session", work_dir=Path("."))
        broadcast = FakeBroadcast()
        active = 0
        max_active = 0

        async def fake_delegated_agent(**kwargs) -> str:
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return f"findings from {kwargs['agent_id']}"

        orchestrator._run_delegated_agent = fake_delegated_agent  # type: ignore[method-assign]

        results = await orchestrator.run_parallel_entry(
            session=session,
            broadcast=broadcast,
            agent_id="main",
            task="inspect worker limit",
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(max_active, 1)

    async def test_parallel_entry_uses_default_agent_store_researcher(self) -> None:
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            store = AgentStore(data_dir)
            config = AppConfig(data_dir=data_dir)
            orchestrator = AgentOrchestrator(
                config=config,
                llm=object(),
                agent_store=store,
                permission_managers={},
            )
            session = Session(id="default-store-session", work_dir=data_dir)
            broadcast = FakeBroadcast()
            calls: list[dict] = []

            async def fake_delegated_agent(**kwargs) -> str:
                calls.append(kwargs)
                return f"default findings from {kwargs['agent_id']}"

            orchestrator._run_delegated_agent = fake_delegated_agent  # type: ignore[method-assign]

            results = await orchestrator.run_parallel_entry(
                session=session,
                broadcast=broadcast,
                agent_id="main",
                task="inspect default agents",
                context="real AgentStore defaults",
            )

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].metadata["source"], "researcher")
            self.assertEqual(results[0].metadata["role"], "researcher")
            self.assertFalse(results[0].metadata["timed_out"])
            self.assertEqual(results[0].text, "default findings from researcher")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["parent_agent_id"], "main")
            self.assertEqual(calls[0]["agent_id"], "researcher")

    async def test_parallel_research_alias_uses_clear_entry_name(self) -> None:
        main = make_agent("main", role="assistant")
        researcher = make_agent("researcher")
        orchestrator = AgentOrchestrator(
            config=AppConfig(),
            llm=object(),
            agent_store=FakeStore([main, researcher]),
            permission_managers={},
        )
        session = Session(id="clear-name-session", work_dir=Path("."))
        broadcast = FakeBroadcast()

        async def fake_delegated_agent(**kwargs) -> str:
            return f"findings from {kwargs['agent_id']}"

        orchestrator._run_delegated_agent = fake_delegated_agent  # type: ignore[method-assign]

        results = await orchestrator.run_parallel_research(
            session=session,
            broadcast=broadcast,
            agent_id="main",
            task="inspect clear entry name",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].metadata["source"], "researcher")

    async def test_run_user_message_triggers_parallel_research_when_not_solo(self) -> None:
        with TemporaryDirectory() as tmp:
            main = make_agent("main", role="assistant")
            researcher = make_agent("researcher")
            orchestrator = AgentOrchestrator(
                config=AppConfig(max_parallel_researchers=1),
                llm=object(),
                agent_store=FakeStore([main, researcher]),
                permission_managers={},
            )
            session = Session(id="run-flow-session", work_dir=Path(tmp), solo_mode=False)
            broadcast = FakeBroadcast()

            async def fake_delegated_agent(**kwargs) -> str:
                return f"findings from {kwargs['agent_id']}"

            orchestrator._run_delegated_agent = fake_delegated_agent  # type: ignore[method-assign]

            with patch("backend.orchestrator.Agent", MainFlowFakeAgent):
                await orchestrator.run_user_message(
                    session=session,
                    text="inspect the project",
                    agent_id="main",
                    broadcast=broadcast,
                )

        event_types = [event_type for event_type, _ in broadcast.events]
        self.assertIn("research.started", event_types)
        self.assertIn("research.result", event_types)
        self.assertIn("research.completed", event_types)
        self.assertIn("agent.completed", event_types)

    async def test_run_user_message_skips_parallel_research_in_solo_mode(self) -> None:
        with TemporaryDirectory() as tmp:
            main = make_agent("main", role="assistant")
            researcher = make_agent("researcher")
            orchestrator = AgentOrchestrator(
                config=AppConfig(max_parallel_researchers=1),
                llm=object(),
                agent_store=FakeStore([main, researcher]),
                permission_managers={},
            )
            session = Session(id="solo-flow-session", work_dir=Path(tmp), solo_mode=True)
            broadcast = FakeBroadcast()

            async def fake_delegated_agent(**kwargs) -> str:
                raise AssertionError("solo mode should not run parallel research")

            orchestrator._run_delegated_agent = fake_delegated_agent  # type: ignore[method-assign]

            with patch("backend.orchestrator.Agent", MainFlowFakeAgent):
                await orchestrator.run_user_message(
                    session=session,
                    text="inspect the project",
                    agent_id="main",
                    broadcast=broadcast,
                )

        event_types = [event_type for event_type, _ in broadcast.events]
        self.assertNotIn("research.started", event_types)
        self.assertNotIn("research.completed", event_types)
        self.assertIn("agent.completed", event_types)

    def test_merge_parallel_research_results_keeps_status_metadata(self) -> None:
        merged = AgentOrchestrator.merge_parallel_research_results([
            ParallelResearchResult(
                text="alpha conclusion",
                metadata={"source": "alpha", "timed_out": False},
            ),
            ParallelResearchResult(
                text="",
                metadata={"source": "slow", "timed_out": True},
                error="timed out",
            ),
            ParallelResearchResult(
                text="",
                metadata={"source": "broken", "timed_out": False},
                error="boom",
            ),
        ])

        self.assertIn("### alpha", merged.text)
        self.assertIn("alpha conclusion", merged.text)
        self.assertIn("超时 researcher：slow", merged.text)
        self.assertIn("异常 researcher：broken", merged.text)
        self.assertEqual(merged.successful_sources, ["alpha"])
        self.assertEqual(merged.timed_out_sources, ["slow"])
        self.assertEqual(merged.errored_sources, ["broken"])

    def test_merge_parallel_research_results_handles_empty_input(self) -> None:
        merged = AgentOrchestrator.merge_parallel_research_results([])

        self.assertEqual(merged.text, "没有可合并的 researcher 结果。")
        self.assertEqual(merged.successful_sources, [])
        self.assertEqual(merged.timed_out_sources, [])
        self.assertEqual(merged.errored_sources, [])
