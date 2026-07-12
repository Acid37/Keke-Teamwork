# 变更日志

> 按时间倒序记录的版本历史和提交日志。

## 2026-07-12 — 上下文治理 + 阶段 5 重构收尾

提交 `202fde0`（#3）：
- README 去掉"预设角色/角色映射"表述，统一改为"自定义 Agent/默认模型/标题模型"
- 待办说明补充当前真实状态

提交 `202fde0`（#2）：
- **连通 context_limit**：`ModelResolver.resolve_context_limit()`，优先级 `AgentDefinition.max_context` → `ModelInfo.max_context` → 默认 100k
- **激活 project_context**：新增 `context_builder.py`，首次消息时扫描项目语言/框架/目录结构，注入三个系统提示词
- **改进压缩质量**：压缩提示词中文化，token 估算改为 CJK 1:1 + ASCII 4:1
- **orchestrator.py 瘦身**：371 → 247 行，提取 5 个私有方法
- **delegate_runner.py 瘦身**：398 → 202 行，提取 `_validate` / `_run_child` 消除 delegate/handoff 重复
- 新增 23 个测试（总计 125 个）

## 2026-07-12 — 安全分层 + 中文化

提交 `202fde0`（#1）：
- 新增 `command_risk.py`、`path_guard.py`
- 接入风险分级 + 路径边界
- 全部提示词、工具描述、错误消息、关键 docstring 改为中文
- 新增 47 个安全分层测试（总计 87 个）

## 2026-07-10 — v0.2-rc：多 Agent 协作基础

### 基础设施
- 快速 CI，执行 `python -m unittest -v`
- 修复默认 unittest 发现路径
- 单窗口启动（`start.bat` 前台运行）
- 左侧栏圆角修复

### 编排与多 Agent
- 并行 researcher 调度入口（`Semaphore` 限并发、超时隔离）
- researcher worker 保持只读工具边界
- 确定性合并层 `merge_parallel_research_results(...)`
- `research.*` 生命周期事件广播
- 非 Solo 主流程受控触发只读并行研究
- 前端展示 researcher 事件
- Research summary 注入 main Agent 上下文（12k 字符上限，Solo 不注入）
- 会话历史不污染：摘要只进主 Agent 上下文，持久消息保留用户原文
- 安全 handoff：`delegate_agent` 对 coder 走串行 handoff，复用 staging/permission
- handoff 禁止嵌套委派
- `handoff.*` 事件和前端展示
- LLM 语义标题生成（异步、算法 fallback）
- 独立 `title_model` 配置（可选轻量模型）
- 标题持久化（LLM 生成后存入 SessionStore）
- 会话创建保护（无项目时禁用新建会话）

### 角色自定义（阶段 1）
- 去掉模型解析角色硬编码，所有 Agent 统一走 `agent_def.model → main_model`
- 前端 Agent 管理已支持 per-agent 模型选择
- Agent 分流从角色名判断改为工具权限判断
- `role` 字段降级为纯标签，不触发运行时特殊行为
- 默认 Agent 定义精简为仅保留 `main`，用户按需自定义角色
- `coder_model`/`research_model` 已移除；仅保留 `title_model` 用于标题生成服务

### 工具可插拔（阶段 2）
- 工具注册改为分类注册（`coding`/`search`/`file`/`shell`/`mcp`）
- `delegate_agent` 的只读/handoff 分流逻辑从硬编码工具列表改为按工具分类判断
- 预留 MCP 工具接入接口（后续单独做）
