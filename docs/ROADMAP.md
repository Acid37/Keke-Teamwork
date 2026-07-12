# 路线图

> 版本：v0.2 | 2026-07-10

## 里程碑

| 里程碑 | 内容 | 状态 |
|---|---|---|
| v0.2-alpha | Orchestrator 最小实现 + Solo 兼容 | 已完成 |
| v0.2-beta | delegate_agent + 只读 researcher 协作 | 已完成 |
| v0.2-rc | research summary 注入 + safe handoff + LLM 标题 | 已完成 |
| v0.2 | 前端时间线 + 事件持久化 + 安全加固 + 测试收敛 | 进行中 |

## 下一步优先级

### 1. MCP 工具接入
- 实现 `mcp` 分类工具的接口和运行时支持

### 2. 前端多 Agent 时间线
- 为 research / handoff / tool / file change 事件定义统一 timeline item
- 支持按 Agent 来源筛选或折叠
- 区分模型上下文和前端展示

### 3. per-agent 工具权限策略
- 参考 MoFox 的 `PermissionLevel` 实现 per-agent 细粒度权限

### 4. 基础模块测试补全
- `SessionStore`、`AppConfig`、`PermissionManager`、`FileStagingArea`、`EditTool` 独立测试

### 5. reviewer 审查流
- coder handoff 完成后自动触发 reviewer Agent
- 形成 research → plan → code → review 闭环

## 架构原则

1. 多 Agent 默认先只读协作
2. main Agent 或单一 coder 负责最终写入，避免并发写冲突
3. researcher 输出先合并、截断、标明来源，再进入 main Agent 上下文
4. 前端展示事件不等同于模型上下文，后续需要拆分 timeline 与 model messages
5. 所有新增后端行为都要有不依赖真实 LLM/API 的测试
