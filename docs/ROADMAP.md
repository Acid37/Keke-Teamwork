# Keke Teamwork 路线图

> 版本：v0.2  
> 日期：2026-07-10  
> 当前定位：本地多 Agent 协作工作台，已具备只读研究、安全 handoff、工具权限分流和 LLM 语义标题。

## 当前状态

### 已落地能力

| 模块 | 状态 | 说明 |
|---|---|---|
| Web UI 工作台 | 已可用 | 项目打开、最近项目、聊天流、工具调用卡片、设置面板、外观配置。 |
| 单 Agent Tool Calling | 已可用 | LLM streaming、tool calls、多轮工具循环。 |
| 本地代码工具 | 已可用 | 读文件、写文件、编辑、grep、find、ls、console。 |
| FileStagingArea | 已接入 | 文件写入记录 baseline，成功后生成 diff，异常时 rollback。 |
| 命令审批 | 已接入 | 非 YOLO 模式下 `run_console` 执行前通过 WebSocket 请求审批。 |
| 三模式开关 | 已生效 | `yolo_mode`、`auto_review`、`solo_mode`。 |
| Agent CRUD | 已可用 | 创建、编辑、删除 Agent 定义，配置模型、工具和提示词。 |
| Orchestrator 编排 | 已接入 | `AgentOrchestrator.run_user_message()` 接管用户消息执行路径。 |
| 只读委派 | 已接入 | `delegate_agent` 对 researcher 走只读路径。 |
| 并行 researcher | 已落地 | 非 Solo 模式受控触发，`Semaphore` 限并发，超时隔离。 |
| Research summary 注入 | 已落地 | 合并摘要以 `[Parallel Research Summary]` 注入 main Agent 上下文，12k 字符上限。 |
| 安全 handoff | 已落地 | `delegate_agent` 对 coder 等非 researcher 走串行 handoff，复用主流程 staging/permission。 |
| Handoff 事件展示 | 已落地 | 前端展示 `handoff.started` / `handoff.completed` / `handoff.failed`。 |
| LLM 语义标题 | 已落地 | 异步 LLM 生成会话标题，支持独立 `title_model` 配置，算法 fallback。 |
| 单窗口启动 | 已落地 | `start.bat` 改为前台单窗口运行。 |
| 自动化测试 | 已落地 | `python -m unittest -v` 运行 87 个测试通过。 |

### 仍未完整落地

| 模块 | 状态 | 说明 |
|---|---|---|
| 前端时间线结构化 | 未落地 | research/handoff 事件目前只转成系统消息，未做独立 timeline 视图。 |
| 事件持久化 | 未落地 | research/handoff 事件不持久化，刷新后丢失。 |
| reviewer 审查流 | 未落地 | coder handoff 完成后尚无自动 reviewer 审查环节。 |
| Checkpoint 历史回滚 | 类型预留 | `Checkpoint` / `FileSnapshot` 已定义，未接入完整历史系统。 |
| 安全策略细分 | 已落地 | 命令风险分级（只读/普通/高危）、只读白名单自动放行、高危命令强制审批、路径边界保护。 |
| 基础模块测试 | 不完整 | `SessionStore`、`AppConfig`、`PermissionManager`、`FileStagingArea`、`EditTool` 缺少独立测试。 |

## v0.2 验收标准

1. Solo 模式稳定回退到单 Agent 路径。
2. 非 Solo 模式可触发只读 researcher 并发探索。
3. researcher 输出以受限摘要注入 main Agent 上下文。
4. coder handoff 通过明确 staging/permission 边界，禁止嵌套委派。
5. 关键后端模块具备基础测试，CI 能运行快速测试。

## 下一步优先级

### 1. 前端多 Agent 时间线

目标：把系统消息式展示升级为结构化 timeline。

- 为 research / handoff / tool / file change 事件定义统一 timeline item。
- 支持按 Agent 来源筛选或折叠。
- 区分模型上下文和前端展示。

### 2. 事件持久化

目标：research/handoff 事件存入 session，刷新后不丢失。

### 3. 安全策略细分

- 命令风险分级（高危 / 只读 / 普通）。
- 只读命令白名单（`git status`、`ls` 等直接放行）。
- 高危命令强制二次确认。
- 限制工具访问 `work_dir` 外路径。

### 4. 基础模块测试补全

- `SessionStore` save/load/list/delete。
- `AppConfig` 文件配置与环境变量覆盖。
- `PermissionManager` approve/deny/timeout。
- `FileStagingArea` create/modify/delete/rollback。
- `EditTool` 精确替换、重复匹配和换行兼容。

### 5. reviewer 审查流

- coder handoff 完成后自动触发 reviewer Agent。
- 形成 research → plan → code → review 闭环。

## 里程碑

| 里程碑 | 内容 | 状态 |
|---|---|---|
| v0.2-alpha | Orchestrator 最小实现 + Solo 兼容 | 已完成 |
| v0.2-beta | delegate_agent + 只读 researcher 协作 | 已完成 |
| v0.2-rc | research summary 注入 + safe handoff + LLM 标题 | 已完成 |
| v0.2 | 前端时间线 + 事件持久化 + 安全加固 + 测试收敛 | 进行中 |

## 架构原则

1. 多 Agent 默认先只读协作。
2. main Agent 或单一 coder 负责最终写入，避免并发写冲突。
3. researcher 输出先合并、截断、标明来源，再进入 main Agent 上下文。
4. 前端展示事件不等同于模型上下文，后续需要拆分 timeline 与 model messages。
5. 所有新增后端行为都要有不依赖真实 LLM/API 的测试。
