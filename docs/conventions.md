# 代码规范

> 后端和前端开发约定。

## 后端

- Python 3.11+，使用 `from __future__ import annotations` 延迟类型求值
- 类型注解：`str | None` 而非 `Optional[str]`
- dataclass 用于数据类型，Enum 用于分类
- 工具类继承 `Tool`，必须声明 `name`、`description`、`parameters`、`category`
- 所有新增后端行为都要有不依赖真实 LLM/API 的测试
- 不加入真实 LLM/API 调用测试

## 前端

- TypeScript strict 模式
- 组件放 `components/`，状态管理通过 `SessionContext`
- WebSocket 事件处理集中在 `SessionContext.tsx`
- Vite 构建已拆分 React / markdown / icons chunk

## 架构原则

1. **工作流驱动，Agent 执行**：工作流决定调度，Agent 决定执行。两层解耦。
2. **角色 = 工具集 + 权限边界 + 行为提示词**：`role` 不是标签，是完整的 Agent 配置剖面。
3. **每个 Agent 都是完整的能力实体**：无论 planner、coder 还是 reviewer，都拥有完整的 tool-calling 循环，能独立装配 MCP/skill。
4. **阶段间数据结构化**：不靠纯文本注入传递信息。plan → task list，code → diff set，review → report。
5. **写操作单一出口**：无论工作流中有多少个 Agent，同一时刻只有一个 Agent 持有写权限，避免并发冲突。
6. **前端展示 ≠ 模型上下文**：timeline 是给人看的，model messages 是给 LLM 看的，两者独立管理。
7. **所有新增后端行为都要有不依赖真实 LLM/API 的测试。**
