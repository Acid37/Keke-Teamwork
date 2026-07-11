# SESSION AGENDA

分支：`dev`  
日期：2026-07-12

## 已完成

### 基础设施
- [x] 快速 CI，执行 `python -m unittest -v`。
- [x] 修复默认 unittest 发现路径。
- [x] 单窗口启动（`start.bat` 前台运行）。
- [x] 左侧栏圆角修复（`--radius-md` token 补全）。
- [x] 当前测试：87 个测试通过（40 原有 + 47 安全分层新增）。

### 编排与多 Agent
- [x] 并行 researcher 调度入口（`Semaphore` 限并发、超时隔离）。
- [x] researcher worker 保持只读工具边界。
- [x] 确定性合并层 `merge_parallel_research_results(...)`。
- [x] `research.*` 生命周期事件广播。
- [x] 非 Solo 主流程受控触发只读并行研究。
- [x] 前端展示 researcher 事件。
- [x] Research summary 注入 main Agent 上下文（12k 字符上限，Solo 不注入）。
- [x] 会话历史不污染：摘要只进主 Agent 上下文，持久消息保留用户原文。
- [x] 安全 handoff：`delegate_agent` 对 coder 走串行 handoff，复用 staging/permission。
- [x] handoff 禁止嵌套委派。
- [x] `handoff.*` 事件和前端展示。
- [x] LLM 语义标题生成（异步、算法 fallback）。
- [x] 独立 `title_model` 配置（可选轻量模型）。
- [x] 标题持久化（LLM 生成后存入 SessionStore）。
- [x] 会话创建保护（无项目时禁用新建会话）。

### 阶段 1：角色真正自定义（已完成）
- [x] 去掉 `_resolve_model` 角色硬编码，所有角色统一走 `agent_def.model → 角色回退 → main_model`。
- [x] 前端 Agent 管理已支持 per-agent 模型选择。
- [x] Agent 分流从角色名判断改为工具权限判断。
- [x] 全局配置里的 `coder_model`/`research_model`/`title_model` 降级为"默认回退值"文档说明。
- [x] 默认 Agent 定义扩展到 5 个示例（main/researcher/coder/reviewer/doc_writer）。

### 阶段 2：工具可插拔（已完成）
- [x] 工具注册改为分类注册（`coding`/`search`/`file`/`shell`/`mcp`）。
- [x] `delegate_agent` 的只读/handoff 分流逻辑从硬编码工具列表改为按工具分类判断。
- [ ] 预留 MCP 工具接入接口（后续单独做）。

### 阶段 4：安全分层（已完成）
- [x] 命令风险分级（高危/只读/普通）。
- [x] 只读命令白名单（`git status`/`ls` 等直接放行）。
- [x] 路径边界保护（禁止访问 `work_dir` 外，工具集成完成）。
- [ ] per-agent 工具权限策略（参考 MoFox 的 `PermissionLevel`）。

### 中文化（v0.2 收尾）
- [x] 系统提示词改中文（main / 只读委派 / handoff 三个默认 prompt）。
- [x] 工具描述和参数说明改中文（base.py + 所有工具类）。
- [x] 工具返回给 LLM 的错误消息改中文。
- [x] 后端关键模块 docstring 改中文。
- [x] 新增 `AI开发文档.md`，README 精简为用户视角。
- [x] 修复 6 处测试断言匹配新的中文消息。

## 下一步

### 阶段 5：orchestrator.py 重构（高优先级）
**问题**：当前 `orchestrator.py` 1100+ 行，承担 7+ 个职责。

计划拆分：
- `orchestrator.py` — 只做消息分发，< 200 行
- `research_runner.py` — 并行研究 + 合并，~250 行
- `delegate_runner.py` — 合并 `_run_handoff_agent` / `_run_delegated_agent` 消除重复，~300 行
- `title_service.py` — 标题生成，~120 行
- `prompt_builder.py` — 三个系统提示词，~80 行
- `model_resolver.py` — 模型解析 + LLM 客户端创建，~50 行

**目标**：消除 ~300 行重复代码，每个模块 < 300 行。

### 阶段 4 剩余
- [ ] per-agent 工具权限策略（参考 MoFox 的 `PermissionLevel`）。

### 阶段 3：GUI 优化
- [ ] 首次启动 Setup Wizard。
- [ ] 设置弹窗分区优化（模型/Agent/工具/安全 分 Tab）。
- [ ] 前端多 Agent 时间线结构化。

### ROADMAP P2：事件持久化
- [ ] research/handoff 事件存入 session，刷新后不丢失。

### 基础模块测试补全
- [ ] `SessionStore` save/load/list/delete。
- [ ] `FileStagingArea` create/modify/delete/rollback。
- [ ] `EditTool` 精确替换、重复匹配和换行兼容。

## 暂不做

- 不允许并行 researcher 写文件。
- 不加入真实 LLM/API 调用测试。
- 不重构完整 timeline/session 持久化模型（先做事件持久化）。
- 不把 researcher 原始全文无节制注入 main Agent 上下文。

## 本次提交记录（2026-07-12）

提交 `202fde0`：安全分层 + 中文化提示词与文档
- 新增 `command_risk.py`、`path_guard.py`
- 接入风险分级 + 路径边界
- 全部提示词、工具描述、错误消息、关键 docstring 改为中文
- 新增 47 个安全分层测试（总计 87 个）
- 文档：SESSION_AGENDA、ROADMAP、AI开发文档
