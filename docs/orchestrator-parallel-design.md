# AgentOrchestrator Parallel Research Draft

## Scope

This draft covers the first backend-only parallel researcher slice. It is intentionally read-only and does not grant automatic write, edit, or console permissions to child agents.

## Public Interface

`AgentOrchestrator.run_parallel_entry(...)` is the high-level entry point for a future orchestration flow. It resolves the parent agent and delegates to `run_parallel_researchers(...)`.

`AgentOrchestrator.run_parallel_researchers(...)` accepts:

- `agent_def`: parent agent definition used for parent metadata and self-delegation avoidance.
- `task`: focused research prompt.
- `context`: optional extra context shared with every researcher.
- `timeout`: optional per-researcher timeout in seconds.
- `max_workers`: maximum concurrent researcher tasks.

It returns `list[ParallelResearchResult]`. Each result contains:

- `text`: textual findings, empty when the task failed before producing a mergeable result.
- `metadata.source`: researcher agent id.
- `metadata.agent_name`: display name.
- `metadata.role`: role tag.
- `metadata.timed_out`: whether this researcher exceeded the per-task timeout.
- `error`: timeout or exception text, when applicable.

## Researcher Selection

The first implementation selects stored agents with `role == "researcher"` and excludes the parent agent id. If no separate researcher is available and the parent itself is a researcher, it can run that parent definition as a single read-only worker.

All worker execution goes through `_run_delegated_agent`, which already constrains tools to:

- `read_file`
- `grep_search`
- `find_files`
- `list_directory`

The delegated `ToolContext` does not include staging, permission manager, or nested delegation.

## Merge Strategy

This slice does not synthesize a final merged answer yet. Callers can treat non-empty `result.text` values as merge candidates and inspect `metadata` for source attribution.

The intended next step is a deterministic merge phase that:

1. Keeps every source result attached to its researcher id.
2. Filters empty timed-out or failed results from merge input.
3. Preserves timeout/error metadata for UI display.
4. Uses a parent/planner agent to summarize agreements, conflicts, and cited files.

## Timeout Strategy

Timeout is applied per researcher with `asyncio.wait_for`. A timeout returns a `ParallelResearchResult` with `metadata.timed_out == True`, empty `text`, and `error == "timed out"`.

The orchestration batch uses `asyncio.gather(..., return_exceptions=True)` so one failed worker does not cancel the entire research batch. Unexpected exceptions become result objects with `error` populated and `timed_out == False`.

## Safety Notes

- No automatic writes are enabled.
- No shell execution is enabled for researcher workers.
- The parent session can accumulate usage through delegated agents, but child workers cannot stage file changes.
- UI integration and final merge synthesis are intentionally left for a later step.
