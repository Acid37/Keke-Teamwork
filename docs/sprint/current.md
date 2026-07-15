# 当前迭代待办

> 上次更新：2026-07-15 | 当前阶段：v0.3 完成 → v0.4 准备

---

## v0.2 遗留（并入 v0.4）

- [ ] **前端多 Agent 时间线 v0**：系统消息式 → 结构化 timeline
- [ ] **事件持久化**：research/handoff 事件持久化（工作流引擎前置依赖）

---

## v0.3 — 角色体系基础 ✅ 已完成

### P0：per-agent 工具权限策略 ✅

- [x] 从二值判断升级为 per-agent 细粒度权限
- [x] 路径约束：`allowed_paths` / `denied_paths`
- [x] 命令风险预算：`max_command_risk`
- [x] `AgentDefinition.permissions`（`AgentPermissions` dataclass）
- [x] 27 个新测试

### P0：内置角色 Agent 定义 ✅

- [x] planner / coder / reviewer 三内置角色 + main
- [x] 默认 `agents.json` 4 个 Agent
- [x] `role` 语义化：`build_system_prompt()` 角色专属提示词

### P0：基础模块测试补全 ✅

- [x] SessionStore (14) + FileStagingArea (19) + EditTool (13) + PermissionManager (19)
- [x] 总计 217 测试全部通过

### P1：Setup Wizard ✅

- [x] 三步引导：服务商 → API Key → 角色一览
- [x] 首次运行检测（`setup_completed`）

### P1：GUI 优化 ✅

- [x] 设置分区 Tab：模型 / Agent / 外观 / 安全
- [x] Agent 权限编辑 UI（路径约束、风险预算、委派/Handoff 开关）
- [x] 安全设置页：YOLO / 自动审查 / Solo 全局开关

### v0.3 代码质量改进 ✅

- [x] APIProvider.to_dict 明文 key 泄露修复
- [x] QUICK_PRESETS / CLIENT_TYPE_OPTIONS 提取到 constants.ts
- [x] Tool 基类 `_resolve_and_check_path()` — 消除 6 工具 × 8 行重复
- [x] AgentPermissions/AgentDefinition.to_dict 统一 asdict()
- [x] ws_server.py PUT /api/agents permissions setattr Bug 修复
- [x] 前端 utils/api.ts + useAsyncAction.ts — 消除 21 处 fetch/setBusy 重复
- [x] edit.py newline='' 修复 — 消除 Linux CI CRLF 失败（+ 回归守卫测试）
- [x] conventions.md 补充新约定（newline / api.ts / useAsyncAction / _resolve_and_check_path）
- [x] 四轮审查：0 死导入，0 lint error，净减 201 行

---

## v0.4 — 工作流引擎（即将开始）

> 📐 设计文档：[docs/designs/workflow-engine.md](../designs/workflow-engine.md)
>
> 分步实施：Step 1 数据类型 → Step 9 E2E 联调，估时 ~7d

| Step | 内容 | 估时 |
|---|---|---|
| 1 | `TaskList` / `DiffSet` / `ReviewReport` / `WorkflowState` 数据类型 | 0.5d |
| 2 | `WorkflowRunner` 状态机骨架 | 1d |
| 3 | 阶段提示词增强 + 上下文剪枝 | 0.5d |
| 4 | 产出物解析（文本标记 + tool call 兜底） | 0.5d |
| 5 | plan → code → review 自动触发串联 | 1d |
| 6 | 用户命令处理（确认/跳过/中断） | 0.5d |
| 7 | 阶段状态持久化 + 恢复 | 0.5d |
| 8 | 前端工作流时间线 | 1.5d |
| 9 | 端到端联调 | 1d |

## v0.6 预览 — 可视化

> 依赖 v0.4 完成。

- 结构化多 Agent 时间线 + 工作流泳道图
