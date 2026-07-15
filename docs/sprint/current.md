# 当前迭代待办

> v0.3 阶段：角色体系基础。目标：让 Agent 从"只读/可写二值"升级为"有明确角色边界的能力实体"。

---

## v0.2 收尾（进行中）

- [ ] **前端多 Agent 时间线 v0**：把系统消息式展示升级为基础结构化 timeline
  - 为 research / handoff / tool / file change 事件定义统一 timeline item
  - 支持按 Agent 来源筛选或折叠
  - 区分模型上下文和前端展示
- [ ] **事件持久化**：research/handoff 事件存入 session，刷新后不丢失

---

## v0.3 — 角色体系基础

> 依赖：v0.2 收尾完成。
> 目标：没有这个，工作流引擎就是在沙滩上盖楼。

### P0：per-agent 工具权限策略

- [ ] 从 `is_read_only_tool_set()` / `has_write_tool()` 二值判断升级为 **per-agent 工具白名单**
- [ ] 路径约束：Agent 可配置 `allowed_paths` / `denied_paths`（如 coder 只能写 `src/`，不能碰 `config/`）
- [ ] 命令风险预算：per-agent 最大允许风险等级（如 reviewer 只能执行只读命令）
- [ ] `AgentDefinition` 扩展 `permissions` 字段
- [ ] 测试：权限边界、路径约束、风险预算拒绝场景

### P0：内置角色 Agent 定义

- [ ] **planner Agent**：只读工具 + 规划型 system prompt，产出结构化 task list
- [ ] **coder Agent**：全套读写工具（受权限约束）+ 编码型 system prompt
- [ ] **reviewer Agent**：只读工具 + diff 审查型 system prompt，产出 review report
- [ ] 默认 `agents.json` 从 1 个 "通用助手" 扩展为 4 个（main + planner + coder + reviewer）
- [ ] `role` 字段语义化：开始参与行为分流（如 `role=coder` 的 Agent 在 plan 阶段自动静默）

### P0：基础模块测试补全

- [ ] `SessionStore` save/load/list/delete
- [ ] `FileStagingArea` create/modify/delete/rollback + diff 生成验证
- [ ] `EditTool` 精确替换、重复匹配和换行兼容
- [ ] `PermissionManager` 审批流程、超时、拒绝

### P1：Setup Wizard

- [ ] 首次启动引导：API key 配置 → 模型选择 → 默认角色确认
- [ ] 检测是否首次运行（无 config.json / agents.json）

### P1：GUI 优化

- [ ] 设置弹窗分区 Tab：模型 / Agent / 工具权限 / 安全
- [ ] Agent 编辑面板增加权限配置 UI

---

## v0.4 预览 — 工作流引擎

> 依赖 v0.3 完成。此处仅列概要，不做具体拆解。

- 阶段管理器：`Phase` 扩展为 `PLANNING → CODING → REVIEWING`，带转换规则
- 自动触发：plan 产出 task list → 调度 coder，code 完成 → 调度 reviewer
- 阶段间结构化数据传递（`TaskList` → `DiffSet` → `ReviewReport`）
- reviewer 审查流：自动接收 diff，逐文件审查，反馈可回环到 coder

---

## v0.5 预览 — Agent 能力扩展

> 依赖 v0.4 完成。

- MCP 工具接入（stdio/HTTP 传输）
- per-agent MCP 装配
- skill 系统

## v0.6 预览 — 可视化

> 依赖 v0.4 完成。

- 结构化多 Agent 时间线 + 工作流泳道图
