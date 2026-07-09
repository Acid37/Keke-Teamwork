# SESSION AGENDA

目标：记录 `feature/orchestrator-parallel` 当前进展，并为下一步多 Agent 协作继续留出清晰入口。

## 当前已完成

- [x] 创建 `feature/orchestrator-parallel` 分支。
- [x] 新增快速 CI，执行 `python -m unittest -v`。
- [x] 修复默认 unittest 发现路径。
- [x] 在 `AgentOrchestrator` 中加入并行 researcher 入口。
- [x] researcher worker 保持只读工具边界。
- [x] 加入单 worker 超时、异常隔离和部分结果返回。
- [x] 加入默认 `AgentStore` researcher 分发覆盖。
- [x] 增加确定性合并层 `merge_parallel_research_results(...)`。
- [x] 更新中文设计文档和 PR 模板。
- [x] 后端广播 `research.started` / `research.result` / `research.failed` / `research.completed`。
- [x] 非 Solo 主流程受控触发只读并行研究。
- [x] 前端将 researcher 事件展示为独立系统消息。
- [x] 最新测试结果：`python -m unittest -v`，13 个测试全部通过。
- [x] 最新前端验证：`npm run build` 通过。

## 等待确认的下一步

后端事件、主流程受控接入和前端最小展示已经落地。下一步建议进入“研究结果如何被 main Agent 使用”的设计与实现，但仍保持只读 researcher 边界。

1. 后端广播事件设计
	- 已定义 researcher 生命周期事件：`research.started`、`research.result`、`research.completed`、`research.failed`。
	- 每个事件需要包含 `agent_id`、`agent_name`、`role`、`parent_agent_id`、`task`、`timed_out`、`error` 等稳定字段。
	- 暂不把 researcher 输出混入主 Agent 的最终回答，先作为独立事件展示和记录。

2. 主流程受控接入
	- 已在 `session.solo_mode == False`、存在 researcher Agent、父 Agent 不是 researcher 时触发。
	- 初版可以先广播合并结果，不改变 main Agent 的回答逻辑。
	- 保持并行 researcher 只读，不开放写文件、编辑文件或执行命令。

3. 前端展示接入
	- 已在聊天时间线中以系统消息展示 researcher 开始、结果、超时、异常和整批完成状态。
	- researcher 输出应和 main Agent 输出区分来源。
	- 前端展示完成前，后端事件字段不要频繁变更。

4. 下一步：研究结果进入 main Agent 上下文
	- 设计一个紧凑的 research summary 注入方式，避免把所有 researcher 原文塞进上下文。
	- 建议先只注入 `research.completed.merged_text` 的截断摘要，并标明来源和失败状态。
	- 需要测试 main Agent 收到的 `existing_messages` 或 user prompt 中包含研究摘要，同时不影响 Solo 模式。

5. 手动验证路径
	- 增加开发用 mock 或脚本，验证非 solo 模式下 researcher 事件顺序。
	- 单元测试继续避免真实 LLM/API 调用。

6. 工作树整理
	- 当前有未纳入本特性提交的文档改动：`docs/ROADMAP.md`、`docs/SESSION_AGENDA.md`。
	- `docs/ROADMAP.md` 是否提交需要单独确认。
	- 本文件用于记录下一步计划，可在用户确认后作为文档提交。

## 暂不做

- 暂不允许并行 researcher 写文件。
- 暂不加入真实 LLM 调用测试。
- 暂不实现复杂语义总结或冲突判断。
- 暂不重构完整 timeline/session 持久化模型。
- 暂不把 researcher 原始全文无节制注入 main Agent 上下文。

## 下一次开工建议

从“研究结果进入 main Agent 上下文”开始。开工前先确认摘要注入格式和长度限制，避免并行研究让模型上下文快速膨胀。

## 实施规划

### 阶段 1：后端事件协议

目标：先把 researcher 生命周期事件定清楚，给后续主流程和前端一个稳定协议。

改动范围：

- 阅读 `backend/ws_server.py` 中现有广播事件格式。
- 阅读前端 WebSocket 消费路径，确认当前事件命名和字段约定。
- 在后端定义 researcher 事件 payload，优先保持普通 `dict`，暂不引入复杂事件系统。
- 补测试，验证事件字段包含来源、父 Agent、任务、状态和错误信息。

建议事件：

- `research.started`：某个 researcher 开始执行。
- `research.result`：某个 researcher 返回结果。
- `research.failed`：某个 researcher 异常或超时。
- `research.completed`：整批 researcher 完成，并包含确定性合并摘要。

验收标准：

- [x] 事件字段稳定，前端可以直接消费。
- [x] 超时和异常不会中断整批事件广播。
- [x] 单元测试不依赖真实 LLM/API。

### 阶段 2：主流程受控接入

目标：让非 Solo 模式下的用户消息可以触发并行研究，但不破坏现有 main Agent 回答链路。

改动范围：

- 在 `AgentOrchestrator.run_user_message()` 中增加受控触发点。
- 触发条件先保持保守：`session.solo_mode == False`、存在 researcher、当前父 Agent 不是 researcher。
- 初版只广播 researcher 结果和合并摘要，不直接改写 main Agent 最终回答。
- 补 solo / non-solo 测试，确认现有单 Agent 行为不变。

验收标准：

- [x] Solo 模式完全沿用现有路径。
- [x] 非 Solo 模式能触发 researcher 事件。
- [x] researcher 仍只使用只读工具。
- [x] `python -m unittest -v` 通过。

### 阶段 3：前端展示

目标：让用户看得见 researcher 在工作，并能区分 main Agent 与 researcher 输出。

改动范围：

- 在 WebSocket client/type 中补 researcher 事件类型。
- 在会话状态中保存 researcher 事件或转换成 timeline 项。
- 增加轻量 UI：开始、成功、超时、失败、整批完成状态。
- researcher 输出先作为独立记录展示，不混入 assistant 普通消息。

验收标准：

- [x] 前端能展示 researcher 来源和状态。
- [x] 超时/失败有明确状态，不显示成普通成功回答。
- [x] main Agent 消息展示不回退。

### 阶段 4：验证和提交

目标：完成最小可演示链路，并保持每一步可回滚。

改动范围：

- 增加开发用 mock 或测试夹具，验证事件顺序。
- 每个逻辑阶段单独提交。
- 每次提交前运行 `python -m unittest -v`。
- 前端接入后补一次本地运行和基本交互检查。

验收标准：

- [x] 后端测试绿色。
- [x] 前端类型检查或构建通过。
- [x] 文档同步更新。
- [x] 不误提交无关文件，尤其是 `docs/ROADMAP.md` 的既有改动。

### 推荐提交顺序

1. `Define research broadcast events`
2. `Wire parallel research into orchestrator flow`
3. `Show researcher events in frontend`
4. `Document parallel research integration`
