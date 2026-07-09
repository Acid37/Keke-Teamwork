# Coding Teamwork 路线图

> 版本：v0.1 -> v0.2  
> 日期：2026-07-10  
> 当前定位：本地 coding assistant 工作台已可用，正在从单 Agent 执行演进到只读多 Agent 协作。

## 当前状态

### 已落地能力

| 模块 | 状态 | 说明 |
|---|---|---|
| Web UI 工作台 | 已可用 | 支持项目打开、最近项目、聊天流、工具调用卡片、设置面板和外观配置。 |
| 单 Agent Tool Calling | 已可用 | `backend/agent.py` 已实现 LLM streaming、tool calls 和多轮工具循环。 |
| 本地代码工具 | 已可用 | 支持读文件、写文件、编辑、grep、find、ls 和 console。 |
| FileStagingArea | 已接入 | 文件写入会记录 baseline，成功后可生成 diff，异常或中断时尝试 rollback。 |
| 命令审批 | 已接入 | 非 YOLO 模式下，`run_console` 执行前通过 WebSocket 请求用户审批。 |
| 三模式开关 | 已生效 | `yolo_mode`、`auto_review`、`solo_mode` 已接入后端执行路径。 |
| Agent CRUD | 已可用 | 可创建、编辑、删除 Agent 定义，并配置模型、工具和提示词。 |
| Orchestrator 编排入口 | 已接入 | `AgentOrchestrator.run_user_message()` 已接管用户消息执行路径。 |
| 只读委派 | 已接入 | `delegate_agent` 可运行只读子 Agent，默认限制为读文件、搜索和列目录。 |
| 并行 researcher | 初版已落地 | 非 Solo 模式下可受控触发只读 researcher，并广播研究事件。 |
| 前端 research 事件展示 | 初版已落地 | 前端将 researcher 开始、结果、失败和完成状态展示为独立系统消息。 |
| 自动化测试 | 初版已落地 | 当前 `python -m unittest -v` 运行 13 个测试通过。 |

### 仍未完整落地

| 模块 | 状态 | 说明 |
|---|---|---|
| Research summary 注入 | 下一步 | researcher 合并结果目前只广播和展示，尚未进入 main Agent 上下文。 |
| writer / coder / reviewer handoff | 未落地 | 尚未实现安全写入交接、审查和最终交付链路。 |
| 历史事件持久化 | 不完整 | research 事件和工具事件尚未作为独立 timeline 持久化。 |
| Checkpoint 历史回滚 | 类型预留 | `Checkpoint` / `FileSnapshot` 已定义，但未形成完整历史系统。 |
| 安全策略细分 | 粗粒度 | 仍缺少高危命令识别、只读白名单和路径边界保护。 |

## v0.2 目标

v0.2 的核心目标是：

> 从可运行的单 Agent coding assistant，升级为具备只读研究、受控交接和可观察过程的多 Agent coding teamwork。

验收时应满足：

1. Solo 模式仍能稳定回退到当前单 Agent 路径。
2. 非 Solo 模式可以触发只读 researcher 并发探索。
3. researcher 输出能以稳定事件展示，并能以受限摘要交给 main Agent。
4. writer / coder / reviewer 的写入能力必须通过明确 handoff 和审批边界。
5. 关键后端模块具备基础测试，CI 能运行快速测试。

## 当前分支进展

分支：`feature/orchestrator-parallel`

已完成提交方向：

- 快速 CI 和 unittest 默认发现。
- 并行 researcher 调度入口。
- 默认 `AgentStore` researcher 分发测试。
- 中文设计文档和 PR 模板。
- 确定性 researcher 结果合并。
- `research.started` / `research.result` / `research.failed` / `research.completed` 后端事件。
- 非 Solo 主流程受控触发只读并行研究。
- 前端最小展示 researcher 事件。
- README、SESSION_AGENDA 和并行研究设计文档同步。

当前验证：

- `python -m unittest -v`：13 个测试通过。
- `npm run build`：前端构建通过。

## 下一步优先级

### 1. Research Summary 注入 main Agent

目标：让 main Agent 真正参考并行 researcher 的合并结论，但避免上下文膨胀。

建议实现：

- 增加摘要格式化函数，输入 `MergedResearchResult` 和原始任务。
- 输出紧凑的 `[Parallel Research Summary]` 文本。
- 包含成功来源、超时来源、异常来源和合并正文。
- 设置固定长度上限，例如 8k 或 12k 字符。
- 非 Solo 模式下注入 main Agent 输入；Solo 模式完全不注入。

验收标准：

- [ ] main Agent 输入中包含 research summary。
- [ ] Solo 模式不触发 researcher，也不注入 summary。
- [ ] 超时和异常来源会出现在 summary 中。
- [ ] 超长 summary 会被截断。
- [ ] `python -m unittest -v` 通过。

### 2. 安全 handoff 设计

目标：在允许 coder/reviewer 写文件前，先明确权限、审批和回滚边界。

建议实现：

- 设计 writer/coder handoff 的触发条件。
- 写入前必须经过 `PermissionManager` 或显式用户批准。
- 避免多个 Agent 同时写同一批文件。
- 明确 FileStagingArea 的冲突和 rollback 策略。

### 3. 前端多 Agent 时间线

目标：把当前系统消息式展示升级为结构化 timeline。

建议实现：

- 区分模型上下文、前端展示和文件变更记录。
- 为 research / delegate / tool / file change 事件定义统一 timeline item。
- 支持按 Agent 来源筛选或折叠。

### 4. 测试与安全加固

优先补充：

- `SessionStore` save/load/list/delete。
- `AppConfig` 文件配置与环境变量覆盖。
- `PermissionManager` approve/deny/timeout。
- `FileStagingArea` create/modify/delete/rollback。
- `EditTool` 精确替换、重复匹配和换行兼容。
- LLM provider message conversion。

安全增强：

- 命令风险分级。
- 只读命令白名单。
- 高危命令强制二次确认。
- 限制工具访问 `work_dir` 外路径。
- 对 `.env`、密钥文件和系统目录增加保护提示。

## 里程碑

| 里程碑 | 内容 | 状态 |
|---|---|---|
| v0.2-alpha | Orchestrator 最小实现 + Solo 兼容 | 已完成 |
| v0.2-beta | `delegate_agent` + 只读 researcher 基础协作 | 基本完成 |
| v0.2-rc | researcher summary 注入 + 前端可观察流程 | 下一步 |
| v0.2 | 安全 handoff + 测试和文档收敛 | 待推进 |

## 架构原则

1. 多 Agent 默认先只读协作。
2. main Agent 或单一 coder 负责最终写入，避免并发写冲突。
3. researcher 输出先合并、截断、标明来源，再进入 main Agent 上下文。
4. 前端展示事件不等同于模型上下文，后续需要拆分 timeline 与 model messages。
5. 所有新增后端行为都要有不依赖真实 LLM/API 的测试。

## 参考文档

- `README.md`：项目总览和使用说明。
- `docs/SESSION_AGENDA.md`：当前分支任务和下一步执行计划。
- `docs/orchestrator-parallel-design.md`：并行 researcher 设计草案。
