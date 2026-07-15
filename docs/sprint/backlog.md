# 积压任务池

> 已确认暂不处理、或有价值但未排期的长期任务。

## 暂不做（边界声明）

- 不允许并行 Agent 同时写文件——同一时刻只有一个 Agent 持有写权限
- 不引入真实 LLM/API 调用测试——保持测试纯确定性
- 不把 researcher/子 Agent 原始全文无节制注入主 Agent 上下文——始终走摘要+截断
- 不把"前端多 Agent 时间线"提前到工作流引擎之前——先有数据再有展示

## 长期积压（v0.6+）

- `Checkpoint` / `FileSnapshot` 类型已定义，未形成完整回滚历史系统
- 工作流模板市场：用户可分享和导入预定义工作流（如"代码审查"、"技术调研"、"重构"）
- 多项目并行会话：同时打开多个项目，每个有独立会话和工作流
- Agent 间直接通信协议：不通过 orchestrator 中转，Agent 可直接向其他 Agent 发送结构化消息
- 工作流断点续跑：会话关闭后重开，从上次中断的阶段继续
- 人机协同工作流：在特定阶段（如 plan 产出后）暂停等待用户审核，用户可修改计划后继续

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
