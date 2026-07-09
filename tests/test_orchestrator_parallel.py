from __future__ import annotations

import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase

from backend.agent_store import AgentStore
from backend.config import AppConfig
from backend.orchestrator import AgentOrchestrator
from backend.types import AgentDefinition, ParallelResearchResult, Session


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

        merge_candidates = [result.text for result in results if result.text]
        self.assertEqual(merge_candidates, ["findings from alpha", "findings from beta"])

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
