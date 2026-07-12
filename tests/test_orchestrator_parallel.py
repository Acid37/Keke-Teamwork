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
from backend.research_runner import ResearchRunner
from backend.title_service import TitleService
from backend.tools import is_read_only_tool_set, has_write_tool
from backend.types import AgentDefinition, AgentResult, ParallelResearchResult, Session, TokenUsage, ToolContext


LAST_MAIN_AGENT_CALL: dict = {}


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
        context_limit: int = 100_000,
        on_text,
        on_thinking,
        on_tool_call,
        on_tool_result,
    ) -> AgentResult:
        LAST_MAIN_AGENT_CALL.clear()
        LAST_MAIN_AGENT_CALL.update({
            "user_message": user_message,
            "existing_messages": existing_messages,
        })
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

        orchestrator._delegate_runner.run_delegated = fake_delegated_agent  # type: ignore[method-assign]

        start = time.perf_counter()
        results = await orchestrator._research_runner.run_researchers(
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

        orchestrator._delegate_runner.run_delegated = fake_delegated_agent  # type: ignore[method-assign]

        merged = await orchestrator._research_runner.run_research(
            session=session,
            broadcast=broadcast,
            agent_id="main",
            task="inspect broadcast events",
            context="unit test",
        )

        self.assertCountEqual(merged.successful_sources, ["alpha", "beta"])
        self.assertIn("### alpha", merged.text)
        self.assertIn("### beta", merged.text)
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

        orchestrator._delegate_runner.run_delegated = fake_delegated_agent  # type: ignore[method-assign]

        merged = await orchestrator._research_runner.run_research(
            session=session,
            broadcast=broadcast,
            agent_id="main",
            task="inspect worker limit",
        )

        self.assertCountEqual(merged.successful_sources, ["alpha", "beta"])
        self.assertEqual(max_active, 1)

    async def test_parallel_entry_with_readonly_agents(self) -> None:
        """使用真实 AgentStore，手动添加只读 Agent 验证并行研究。"""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            store = AgentStore(data_dir)
            # 手动添加只读 Agent（默认 AgentStore 只有 main）
            store.save_agent(AgentDefinition(
                agent_id="lib-researcher",
                name="库研究员",
                role="researcher",
                tools=["read_file", "grep_search", "find_files", "list_directory"],
            ))
            store.save_agent(AgentDefinition(
                agent_id="code-reviewer",
                name="代码审查员",
                role="reviewer",
                tools=["read_file", "grep_search", "find_files", "list_directory"],
            ))
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

            orchestrator._delegate_runner.run_delegated = fake_delegated_agent  # type: ignore[method-assign]

            merged = await orchestrator._research_runner.run_research(
                session=session,
                broadcast=broadcast,
                agent_id="main",
                task="inspect default agents",
                context="real AgentStore defaults",
            )

            # 手动添加的两个只读 Agent 都应被选为并行 researcher 候选
            # （按工具权限分流，不按角色名）。
            self.assertCountEqual(merged.successful_sources, ["lib-researcher", "code-reviewer"])
            self.assertIn("default findings from lib-researcher", merged.text)
            self.assertIn("default findings from code-reviewer", merged.text)
            self.assertEqual(len(calls), 2)
            parent_ids = {c["parent_agent_id"] for c in calls}
            self.assertEqual(parent_ids, {"main"})

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

        orchestrator._delegate_runner.run_delegated = fake_delegated_agent  # type: ignore[method-assign]

        merged = await orchestrator._research_runner.run_research(
            session=session,
            broadcast=broadcast,
            agent_id="main",
            task="inspect clear entry name",
        )

        self.assertEqual(merged.successful_sources, ["researcher"])
        self.assertIn("findings from researcher", merged.text)

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

            orchestrator._delegate_runner.run_delegated = fake_delegated_agent  # type: ignore[method-assign]

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
        self.assertIn("inspect the project", LAST_MAIN_AGENT_CALL["user_message"])
        self.assertIn("[Parallel Research Summary]", LAST_MAIN_AGENT_CALL["user_message"])
        self.assertIn("findings from researcher", LAST_MAIN_AGENT_CALL["user_message"])
        self.assertEqual(
            LAST_MAIN_AGENT_CALL["existing_messages"][-1]["content"],
            LAST_MAIN_AGENT_CALL["user_message"],
        )
        self.assertEqual(session.messages[0]["content"], "inspect the project")
        self.assertNotIn("[Parallel Research Summary]", session.messages[0]["content"])

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

            orchestrator._delegate_runner.run_delegated = fake_delegated_agent  # type: ignore[method-assign]

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
        self.assertEqual(LAST_MAIN_AGENT_CALL["user_message"], "inspect the project")
        self.assertNotIn("[Parallel Research Summary]", LAST_MAIN_AGENT_CALL["user_message"])

    def test_merge_parallel_research_results_keeps_status_metadata(self) -> None:
        merged = ResearchRunner.merge([
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
        merged = ResearchRunner.merge([])

        self.assertEqual(merged.text, "没有可合并的 researcher 结果。")
        self.assertEqual(merged.successful_sources, [])
        self.assertEqual(merged.timed_out_sources, [])
        self.assertEqual(merged.errored_sources, [])

    def test_research_summary_for_agent_includes_status_and_truncates(self) -> None:
        merged = ResearchRunner.merge([
            ParallelResearchResult(
                text="alpha conclusion " * 20,
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

        summary = ResearchRunner.format_summary_for_agent(
            task="inspect summary",
            merged=merged,
            max_chars=240,
        )

        self.assertIn("[Parallel Research Summary]", summary)
        self.assertIn("原始任务：inspect summary", summary)
        self.assertIn("成功来源：alpha", summary)
        self.assertIn("超时来源：slow", summary)
        self.assertIn("异常来源：broken", summary)
        self.assertTrue(summary.endswith("\n... (parallel research summary truncated)"))

    def test_generate_session_title_from_first_user_message(self) -> None:
        session = Session(id="title-session", work_dir=Path("D:/example-project"))

        self.assertTrue(TitleService.should_generate_title(session))
        title = TitleService.generate_title(
            "请帮我修复左侧栏会话标题显示问题，并补测试",
            session.work_dir,
        )

        self.assertEqual(title, "修复左侧栏会话标题显示问题，并补测试")

    def test_should_not_replace_project_or_user_session_title(self) -> None:
        project_session = Session(
            id="project-title-session",
            work_dir=Path("D:/keke_teamwork"),
            title="keke_teamwork",
        )
        user_session = Session(
            id="user-title-session",
            work_dir=Path("D:/keke_teamwork"),
            title="左侧栏 UI 优化",
        )
        placeholder_session = Session(
            id="placeholder-title-session",
            work_dir=Path("D:/keke_teamwork"),
            title="Session 04:07",
        )

        self.assertFalse(TitleService.should_generate_title(project_session))
        self.assertFalse(TitleService.should_generate_title(user_session))
        self.assertTrue(TitleService.should_generate_title(placeholder_session))

    async def test_llm_title_generation_updates_session_and_broadcasts(self) -> None:
        from backend.types import StreamEvent

        main = make_agent("main", role="assistant")
        orchestrator = AgentOrchestrator(
            config=AppConfig(),
            llm=object(),
            agent_store=FakeStore([main]),
            permission_managers={},
        )
        session = Session(id="llm-title-session", work_dir=Path("D:/proj"), title="Session 04:07")
        broadcast = FakeBroadcast()

        async def fake_chat(*, messages, system=None, model=None, max_tokens=64, temperature=0.3, stream=True, **kw):
            yield StreamEvent(text_delta="修复左侧栏圆角")
            yield StreamEvent(finish=True)

        class FakeLLM:
            async def chat(self, **kwargs):
                async for event in fake_chat(**kwargs):
                    yield event

        orchestrator._title_service._llm = FakeLLM()  # type: ignore[assignment]

        await orchestrator._title_service.update_title_with_llm(
            session=session,
            user_text="请帮我修复左侧栏圆角问题",
            broadcast=broadcast,
        )

        self.assertEqual(session.title, "修复左侧栏圆角")
        title_events = [e for e in broadcast.events if e[0] == "session.title.updated"]
        self.assertEqual(len(title_events), 1)
        self.assertEqual(title_events[0][1]["session_id"], "llm-title-session")
        self.assertEqual(title_events[0][1]["title"], "修复左侧栏圆角")

    async def test_llm_title_generation_falls_back_on_error(self) -> None:
        main = make_agent("main", role="assistant")
        orchestrator = AgentOrchestrator(
            config=AppConfig(),
            llm=object(),
            agent_store=FakeStore([main]),
            permission_managers={},
        )
        session = Session(id="fallback-title-session", work_dir=Path("D:/proj"), title="修复左侧栏…")
        broadcast = FakeBroadcast()

        class BrokenLLM:
            async def chat(self, **kwargs):
                raise RuntimeError("API unavailable")
                yield  # noqa: unreachable — make it an async generator

        orchestrator._title_service._llm = BrokenLLM()  # type: ignore[assignment]

        await orchestrator._title_service.update_title_with_llm(
            session=session,
            user_text="请帮我修复左侧栏圆角问题",
            broadcast=broadcast,
        )

        self.assertEqual(session.title, "修复左侧栏…")
        title_events = [e for e in broadcast.events if e[0] == "session.title.updated"]
        self.assertEqual(len(title_events), 0)

    async def test_title_model_uses_dedicated_llm_client(self) -> None:
        from unittest.mock import patch as _patch
        from backend.types import StreamEvent

        main = make_agent("main", role="assistant")
        config = AppConfig(title_model="cheap-flash-model")
        orchestrator = AgentOrchestrator(
            config=config,
            llm=object(),
            agent_store=FakeStore([main]),
            permission_managers={},
        )
        session = Session(id="dedicated-title-session", work_dir=Path("D:/proj"), title="Session 04:07")
        broadcast = FakeBroadcast()

        async def fake_chat(*, messages, system=None, model=None, max_tokens=64, temperature=0.3, stream=True, **kw):
            self.assertEqual(model, "cheap-flash-model")
            yield StreamEvent(text_delta="轻量标题")
            yield StreamEvent(finish=True)

        class FakeLLM:
            def __init__(self, **kw):
                self.created_with = kw

            async def chat(self, **kwargs):
                async for event in fake_chat(**kwargs):
                    yield event

        with _patch("backend.title_service.LLMClient", FakeLLM):
            await orchestrator._title_service.update_title_with_llm(
                session=session,
                user_text="请帮我优化性能",
                broadcast=broadcast,
            )

        self.assertEqual(session.title, "轻量标题")
        title_events = [e for e in broadcast.events if e[0] == "session.title.updated"]
        self.assertEqual(len(title_events), 1)

    def test_tool_based_role_classification(self) -> None:
        """Agent 分流应基于工具权限而非角色名。"""
        read_only_custom = AgentDefinition(
            agent_id="analyst",
            name="数据分析师",
            role="analyst",
            tools=["read_file", "grep_search", "find_files", "list_directory"],
        )
        write_custom = AgentDefinition(
            agent_id="writer",
            name="文档撰写师",
            role="writer",
            tools=["read_file", "write_file", "edit_file"],
        )
        mixed = AgentDefinition(
            agent_id="hybrid",
            name="混合角色",
            role="custom",
            tools=["read_file", "run_console"],
        )

        self.assertTrue(is_read_only_tool_set(read_only_custom.tools))
        self.assertFalse(has_write_tool(read_only_custom.tools))

        self.assertFalse(is_read_only_tool_set(write_custom.tools))
        self.assertTrue(has_write_tool(write_custom.tools))

        self.assertFalse(is_read_only_tool_set(mixed.tools))
        self.assertTrue(has_write_tool(mixed.tools))
