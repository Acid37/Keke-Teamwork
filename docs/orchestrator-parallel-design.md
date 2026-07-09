# AgentOrchestrator 并行研究草案

## 范围

本文档记录第一版后端并行 researcher 雏形。当前实现只做只读研究，不给子 Agent 自动写文件、编辑文件或执行命令的权限。

## 对外接口

`AgentOrchestrator.run_parallel_research(...)` 是后续会话流程优先使用的入口。它负责解析父 Agent，然后调用 `run_parallel_researchers(...)`。

`AgentOrchestrator.run_parallel_entry(...)` 暂时保留为兼容入口，内部直接转发到 `run_parallel_research(...)`。

`AgentOrchestrator.run_parallel_researchers(...)` 接收：

- `agent_def`：父 Agent 定义，用于记录父级来源并避免委派给自己。
- `task`：研究任务描述。
- `context`：传给每个 researcher 的额外上下文。
- `timeout`：单个 researcher 的可选超时时间，单位秒。
- `max_workers`：最大并发 researcher 数量。

返回值是 `list[ParallelResearchResult]`。每个结果包含：

- `text`：研究文本；如果任务超时或失败且没有可合并内容，则为空字符串。
- `metadata.source`：researcher 的 Agent id。
- `metadata.agent_name`：researcher 显示名。
- `metadata.role`：角色标签。
- `metadata.timed_out`：该 researcher 是否超时。
- `error`：超时或异常信息。

`AgentOrchestrator.merge_parallel_research_results(...)` 是确定性合并入口。它接收 `list[ParallelResearchResult]`，不调用 LLM，返回 `MergedResearchResult`：

- `text`：可直接展示或交给后续主 Agent 的合并文本。
- `successful_sources`：进入正文合并的 researcher id 列表。
- `timed_out_sources`：超时 researcher id 列表。
- `errored_sources`：异常 researcher id 列表。

## Researcher 选择策略

第一版会从 `AgentStore.list_agents()` 中选择 `role == "researcher"` 的 Agent，并排除父 Agent 自己。如果没有独立 researcher，而父 Agent 本身就是 researcher，则允许以父 Agent 定义运行一个只读 worker。

每个 worker 都复用 `_run_delegated_agent`，因此工具权限仍被限制为：

- `read_file`
- `grep_search`
- `find_files`
- `list_directory`

委派时传入的 `ToolContext` 不包含 staging、permission manager，也不允许继续嵌套委派。

## 合并策略

当前版本已经提供不依赖 LLM 的确定性合并层，按固定规则组织结果：

1. 保留每条结果对应的 researcher id。
2. 过滤空文本的超时或失败结果，不把它们送入正文合并。
3. 保留超时和异常元数据，给 UI 或日志展示。
4. 生成稳定文本，后续可再交给父 Agent 或 planner 做语义总结。

合并层不会判断结论是否冲突，也不会重写 researcher 的文本；它只做来源分组、状态保留和稳定格式化。

## 超时策略

每个 researcher 使用 `asyncio.wait_for` 独立设置超时。超时后返回 `ParallelResearchResult`，其中 `metadata.timed_out == True`、`text == ""`、`error == "timed out"`。

整批任务使用 `asyncio.gather(..., return_exceptions=True)` 收集结果，避免某个 worker 失败导致整批取消。未预期异常会被转换成带 `error` 的结果对象，并标记 `timed_out == False`。

## 安全边界

- 不开启自动写入。
- researcher worker 不允许执行 shell 命令。
- 父会话可以累计 delegated agent 的 token usage，但子 worker 不能 stage 文件改动。
- UI 接入和最终 LLM 语义总结仍留到后续步骤。
