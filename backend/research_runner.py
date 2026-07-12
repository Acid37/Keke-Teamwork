"""并行只读研究调度与结果合并。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from backend.config import AppConfig
from backend.delegate_runner import DelegateRunner
from backend.tools import is_read_only_tool_set
from backend.types import AgentDefinition, MergedResearchResult, ParallelResearchResult, Session

logger = logging.getLogger(__name__)

Broadcast = Callable[[str, dict], Awaitable[None]]


class ResearchRunner:
    """并发运行只读 Agent 做并行研究，确定性合并结果。"""

    def __init__(
        self,
        config: AppConfig,
        agent_store,
        delegate_runner: DelegateRunner,
    ):
        self._config = config
        self._agent_store = agent_store
        self._delegate_runner = delegate_runner

    # ─── 公开接口 ───

    async def run_research(
        self,
        *,
        session: Session,
        task: str,
        context: str = "",
        agent_id: str = "main",
        broadcast: Broadcast,
        timeout: float | None = None,
        max_workers: int | None = None,
    ) -> MergedResearchResult:
        """面向会话流程的只读并行研究入口。"""
        agent_def = self._agent_store.get_agent(agent_id) or self._agent_store.get_agent("main")
        if not agent_def:
            return self.merge([])
        results = await self.run_researchers(
            session=session,
            broadcast=broadcast,
            agent_def=agent_def,
            task=task,
            context=context,
            timeout=timeout,
            max_workers=max_workers or self._config.max_parallel_researchers,
        )
        merged = self.merge(results)
        await broadcast("research.completed", {
            "parent_agent_id": agent_def.agent_id,
            "task": task,
            "merged_text": merged.text,
            "successful_sources": merged.successful_sources,
            "timed_out_sources": merged.timed_out_sources,
            "errored_sources": merged.errored_sources,
            "result_count": len(results),
        })
        return merged

    async def run_researchers(
        self,
        *,
        session: Session,
        broadcast: Broadcast,
        agent_def: AgentDefinition,
        task: str,
        context: str = "",
        timeout: float | None = None,
        max_workers: int = 3,
    ) -> list[ParallelResearchResult]:
        """并发运行可用的只读 Agent，且只允许只读工具。"""
        max_workers = max(1, max_workers)
        candidates = [
            candidate
            for candidate in self._agent_store.list_agents()
            if is_read_only_tool_set(candidate.tools) and candidate.agent_id != agent_def.agent_id
        ]
        if not candidates and is_read_only_tool_set(agent_def.tools):
            candidates = [agent_def]

        semaphore = asyncio.Semaphore(max_workers)

        async def run_one(researcher: AgentDefinition) -> ParallelResearchResult:
            async with semaphore:
                base_payload = {
                    "agent_id": researcher.agent_id,
                    "agent_name": researcher.name,
                    "role": researcher.role,
                    "parent_agent_id": agent_def.agent_id,
                    "task": task,
                }
                await broadcast("research.started", base_payload)
                try:
                    result_text = await asyncio.wait_for(
                        self._delegate_runner.run_delegated(
                            session=session,
                            broadcast=broadcast,
                            parent_agent_id=agent_def.agent_id,
                            agent_id=researcher.agent_id,
                            task=task,
                            context=context,
                        ),
                        timeout=timeout,
                    )
                    await broadcast("research.result", {
                        **base_payload,
                        "text": result_text,
                        "timed_out": False,
                        "error": None,
                    })
                    return ParallelResearchResult(
                        text=result_text,
                        metadata={
                            "source": researcher.agent_id,
                            "agent_name": researcher.name,
                            "role": researcher.role,
                            "timed_out": False,
                        },
                    )
                except asyncio.TimeoutError:
                    await broadcast("research.failed", {
                        **base_payload,
                        "text": "",
                        "timed_out": True,
                        "error": "timed out",
                    })
                    return ParallelResearchResult(
                        text="",
                        metadata={
                            "source": researcher.agent_id,
                            "agent_name": researcher.name,
                            "role": researcher.role,
                            "timed_out": True,
                        },
                        error="timed out",
                    )
                except Exception as exc:
                    await broadcast("research.failed", {
                        **base_payload,
                        "text": "",
                        "timed_out": False,
                        "error": str(exc),
                    })
                    return ParallelResearchResult(
                        text="",
                        metadata={
                            "source": researcher.agent_id,
                            "agent_name": researcher.name,
                            "role": researcher.role,
                            "timed_out": False,
                        },
                        error=str(exc),
                    )

        gathered = await asyncio.gather(
            *(run_one(researcher) for researcher in candidates),
            return_exceptions=True,
        )
        results: list[ParallelResearchResult] = []
        for item in gathered:
            if isinstance(item, ParallelResearchResult):
                results.append(item)
            elif isinstance(item, Exception):
                results.append(ParallelResearchResult(
                    text="",
                    metadata={"source": "unknown", "timed_out": False},
                    error=str(item),
                ))
        return results

    def should_run_research(
        self,
        session: Session,
        agent_def: AgentDefinition,
    ) -> bool:
        """判断当前用户消息是否应触发只读并行研究。

        按工具权限判断而非角色名：只要存在其他只读 Agent 可作为
        researcher 候选，就触发并行研究。
        """
        if session.solo_mode:
            return False
        return any(
            is_read_only_tool_set(candidate.tools) and candidate.agent_id != agent_def.agent_id
            for candidate in self._agent_store.list_agents()
        )

    # ─── 纯函数（无副作用，可独立测试） ───

    @staticmethod
    def merge(
        results: list[ParallelResearchResult],
    ) -> MergedResearchResult:
        """确定性合并 researcher 结果，不调用 LLM。"""
        successful_sections: list[str] = []
        successful_sources: list[str] = []
        timed_out_sources: list[str] = []
        errored_sources: list[str] = []

        for result in results:
            source = str(result.metadata.get("source") or "unknown")
            if result.metadata.get("timed_out"):
                timed_out_sources.append(source)
                continue
            if result.error:
                errored_sources.append(source)
                continue

            text = result.text.strip()
            if text:
                successful_sources.append(source)
                successful_sections.append(f"### {source}\n{text}")

        if successful_sections:
            merged_text = "\n\n".join(successful_sections)
        else:
            merged_text = "没有可合并的 researcher 结果。"

        status_lines: list[str] = []
        if timed_out_sources:
            status_lines.append("超时 researcher：" + ", ".join(timed_out_sources))
        if errored_sources:
            status_lines.append("异常 researcher：" + ", ".join(errored_sources))
        if status_lines:
            merged_text = merged_text + "\n\n---\n" + "\n".join(status_lines)

        return MergedResearchResult(
            text=merged_text,
            successful_sources=successful_sources,
            timed_out_sources=timed_out_sources,
            errored_sources=errored_sources,
        )

    @staticmethod
    def build_agent_user_message(*, user_text: str, research_summary: str) -> str:
        if not research_summary:
            return user_text
        return f"{user_text.rstrip()}\n\n{research_summary}"

    @staticmethod
    def format_summary_for_agent(
        *,
        task: str,
        merged: MergedResearchResult,
        max_chars: int = 12_000,
    ) -> str:
        """格式化受限的只读发现结果，注入 main Agent 上下文。"""
        summary = (
            "[Parallel Research Summary]\n"
            "这些是只读 researcher 在主 Agent 执行前得到的参考结论；"
            "请结合项目实际情况判断，不要把它们当成已完成修改。\n\n"
            f"原始任务：{task.strip()}\n\n"
            f"成功来源：{', '.join(merged.successful_sources) or '(none)'}\n"
            f"超时来源：{', '.join(merged.timed_out_sources) or '(none)'}\n"
            f"异常来源：{', '.join(merged.errored_sources) or '(none)'}\n\n"
            f"{merged.text.strip() or '没有可合并的 researcher 结果。'}"
        )
        if len(summary) <= max_chars:
            return summary
        return summary[:max_chars] + "\n... (parallel research summary truncated)"