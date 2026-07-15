# 路线图

> 版本：v0.3 规划 | 2026-07-15

## 产品定位

Keke Teamwork 的核心价值是**多 Agent 角色协作工作流**，而非单纯的工具平台。

两层架构：
- **工作流层**：定义"谁在什么时候做什么"（Plan → Code → Review 闭环）。
- **Agent 能力层**：每个角色 Agent 都是完整的 tool-calling 实体，可装配任意工具、MCP、skill。

方向判定：工作流是骨架，Agent 能力是肌肉。先搭骨架，再长肌肉。

---

## 里程碑

### 已完成

| 里程碑 | 内容 | 状态 |
|---|---|---|
| v0.2-alpha | Orchestrator 最小实现 + Solo 兼容 | ✅ |
| v0.2-beta | delegate_agent + 只读 researcher 协作 | ✅ |
| v0.2-rc | research summary 注入 + safe handoff + LLM 标题 | ✅ |
| v0.2 | 前端时间线 + 事件持久化 + 安全加固 + 测试收敛 | ✅ |

### 计划中

| 里程碑 | 内容 | 依赖 |
|---|---|---|
| **v0.3** | 角色体系基础：per-agent 权限 + 内置角色 + 测试补全 | v0.2 |
| **v0.4** | 工作流引擎：Plan → Code → Review 闭环 | v0.3 |
| **v0.5** | MCP 工具生态 + Agent 能力扩展 | v0.4 |
| **v0.6** | 前端结构化多 Agent 时间线 | v0.4 |

---

## 分阶段详情

### v0.3 — 角色体系基础（当前）

> **为什么先做这个**：没有细粒度权限和内置角色定义，工作流就是在沙滩上盖楼。

- [x] **per-agent 工具权限策略**：从二值（能写/不能写）升级为 per-agent 工具白名单 + 路径约束 + 命令风险预算
- [x] **内置角色 Agent 定义**：planner / coder / reviewer 三个默认 Agent，各有差异化 toolset + system prompt
- [x] **role 字段语义化**：`role` 不再是纯标签，开始参与分流判断（与 toolset 共同决定行为）
- [x] **基础模块测试补全**：`SessionStore`、`FileStagingArea`、`EditTool`、`PermissionManager` 独立测试
- [x] **事件持久化**：research/handoff/timeline 事件存入 session，刷新不丢失
- [x] **Setup Wizard**：首次启动引导配置 API key、模型、默认角色
- [x] **GUI 优化**：设置页安全 Tab + Agent 权限编辑 UI

### v0.4 — 工作流引擎

> **为什么权限和角色之后才做**：阶段转换、自动触发、结构化产出——这些依赖明确的角色边界。

- [ ] **阶段管理器**：`Phase` 扩展为 `PLANNING → CODING → REVIEWING`，阶段转换规则 + 进入/退出守卫
- [ ] **自动触发**：plan 产出结构化 task list → 自动调度 coder；code 完成 → 自动调度 reviewer
- [ ] **阶段间数据传递**：plan 产出 `TaskList` 结构体，coder 产出 `DiffSet`，reviewer 产出 `ReviewReport`
- [ ] **reviewer 审查流**：自动接收 coder 的 diff，逐文件审查并生成反馈，反馈可回环到 coder
- [ ] **中断与恢复**：用户可在任意阶段介入修正，工作流可挂起和恢复

### v0.5 — Agent 能力扩展

> **为什么工作流之后才做**：每个角色先有明确的"岗位职责"，再给装备。

- [ ] **MCP 工具接入**：实现 `mcp` 分类工具的接口和运行时，支持 stdio/HTTP 传输
- [ ] **per-agent MCP 装配**：planner 可接 Jira/GitHub Issues，coder 可接包管理/API 文档，reviewer 可接 lint/测试报告
- [ ] **skill 系统**：Agent 可加载领域 skill（如"React 专家"、"数据库优化"），注入 system prompt
- [ ] **上下文治理增强**：按阶段自动剪枝上下文，plan 阶段不需要 diff 历史，review 阶段不需要 plan 草稿

### v0.6 — 可视化

> **为什么最后做**：先有真正的工作流数据，再做展示。不粉饰空壳。

- [ ] **前端多 Agent 时间线**：工作流阶段 + 各 Agent 实时状态 + 阶段间产物预览
- [ ] **按角色/阶段筛选折叠**
- [ ] **工作流可视化**：Plan → Code → Review 泳道图，阶段卡片带产物摘要
- [ ] **手风琴式消息历史**：区分模型上下文和前端展示

---

## 架构原则

1. **工作流驱动，Agent 执行**：工作流决定调度，Agent 决定执行。两层解耦。
2. **角色 = 工具集 + 权限边界 + 行为提示词**：`role` 不是标签，是完整的 Agent 配置剖面。
3. **每个 Agent 都是完整的能力实体**：无论是 planner、coder 还是 reviewer，都拥有完整的 tool-calling 循环，能独立装配 MCP/skill。
4. **阶段间数据结构化**：不靠纯文本注入传递信息。plan → task list，code → diff set，review → report。
5. **写操作单一出口**：无论工作流中有多少个 Agent，同一时刻只有一个 Agent 持有写权限，避免并发冲突。
6. **前端展示 ≠ 模型上下文**：timeline 是给人看的，model messages 是给 LLM 看的，两者独立管理。
7. **所有新增后端行为要有不依赖真实 LLM/API 的测试。**
