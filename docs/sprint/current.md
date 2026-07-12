# 当前迭代待办

> 当前 v0.2 阶段的进行中和待办任务。

## 进行中

- [ ] **前端多 Agent 时间线**：把系统消息式展示升级为结构化 timeline
  - 为 research / handoff / tool / file change 事件定义统一 timeline item
  - 支持按 Agent 来源筛选或折叠
  - 区分模型上下文和前端展示
- [ ] **事件持久化**：research/handoff 事件存入 session，刷新后不丢失

## 待办

- [ ] **MCP 工具接入**：预留的 `mcp` 分类工具接口
- [ ] **per-agent 工具权限策略**：参考 MoFox 的 `PermissionLevel`
- [ ] **首批启动 Setup Wizard**
- [ ] **GUI 优化**：设置弹窗分区优化（模型/Agent/工具/安全分 Tab）
- [ ] **基础模块测试补全**：
  - `SessionStore` save/load/list/delete
  - `FileStagingArea` create/modify/delete/rollback
  - `EditTool` 精确替换、重复匹配和换行兼容
- [ ] **reviewer 审查流**：coder handoff 完成后自动触发 reviewer Agent，形成 research → plan → code → review 闭环
