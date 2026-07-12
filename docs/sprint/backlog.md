# 积压任务池

> 已确认暂不处理、或有价值但未排期的长期任务。

## 暂不做（边界声明）

- 不允许并行 researcher 写文件
- 不加入真实 LLM/API 调用测试
- 不重构完整 timeline/session 持久化模型（先做事件持久化）
- 不把 researcher 原始全文无节制注入 main Agent 上下文

## 长期积压

- `Checkpoint` / `FileSnapshot` 类型已定义，未形成完整回滚历史系统
- 前端 research/handoff 事件以系统消息展示，尚未做独立时间线视图（已在 current.md 排期）
- research/handoff 事件不持久化，刷新后丢失（已在 current.md 排期）
- reviewer 审查流尚未落地（已在 current.md 排期）
- per-agent 工具权限策略尚未落地（已在 current.md 排期）
- 基础模块（SessionStore、FileStagingArea、EditTool）缺少独立测试（已在 current.md 排期）

## 已完成（归档）

> 以下能力已在 v0.2 中落地，记录在此供回溯。

- Web UI 工作台：项目打开、最近项目、聊天流、工具调用卡片、设置面板、外观配置
- 单 Agent Tool Calling：LLM streaming、tool calls、多轮工具循环
- 本地代码工具：读文件、写文件、编辑、grep、find、ls、console
- FileStagingArea：文件写入记录 baseline，成功后生成 diff，异常时 rollback
- 命令审批：非 YOLO 模式下 `run_console` 执行前通过 WebSocket 请求审批
- 三模式开关：`yolo_mode`、`auto_review`、`solo_mode`
- Agent CRUD：创建、编辑、删除 Agent 定义，配置模型、工具和提示词
- Orchestrator 编排：`AgentOrchestrator.run_user_message()` 接管用户消息执行路径
- 只读委派：`delegate_agent` 对 researcher 走只读路径
- 并行 researcher：非 Solo 模式受控触发，`Semaphore` 限并发，超时隔离
- Research summary 注入：合并摘要以 `[Parallel Research Summary]` 注入 main Agent 上下文，12k 字符上限
- 安全 handoff：`delegate_agent` 对 coder 等非 researcher 走串行 handoff，复用主流程 staging/permission
- Handoff 事件展示：前端展示 `handoff.started` / `handoff.completed` / `handoff.failed`
- LLM 语义标题：异步 LLM 生成会话标题，支持独立 `title_model` 配置，算法 fallback
- 单窗口启动：`start.bat` 改为前台单窗口运行
- 自动化测试：125 个测试通过
- 安全分层：命令风险分级（只读/普通/高危）、只读白名单自动放行、高危命令强制审批、路径边界保护
