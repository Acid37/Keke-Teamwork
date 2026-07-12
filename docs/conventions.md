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

1. 多 Agent 默认先只读协作
2. main Agent 或单一 coder 负责最终写入，避免并发写冲突
3. researcher 输出先合并、截断、标明来源，再进入 main Agent 上下文
4. 前端展示事件不等同于模型上下文，后续需要拆分 timeline 与 model messages
5. 所有新增后端行为都要有不依赖真实 LLM/API 的测试
