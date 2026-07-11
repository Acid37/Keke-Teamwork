# SESSION AGENDA

分支：`feature/orchestrator-parallel`  
日期：2026-07-10

## 已完成

- [x] 快速 CI，执行 `python -m unittest -v`。
- [x] 修复默认 unittest 发现路径。
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
- [x] 左侧栏圆角修复（`--radius-md` token 补全）。
- [x] 单窗口启动（`start.bat` 前台运行）。
- [x] 当前测试：`python -m unittest -v`，21 个测试通过。
- [x] 当前前端：`npm run build` 通过。

## 下一步

### 阶段 1：角色真正自定义（已完成）

- [x] 去掉 `_resolve_model` 角色硬编码，所有角色统一走 `agent_def.model → 角色回退 → main_model`。
- [x] 前端 Agent 管理已支持 per-agent 模型选择（`formModel` 字段 + 模型下拉框）。
- [x] Agent 分流从角色名判断改为工具权限判断（`_is_read_only_agent` / `_has_write_tools`）。
- [x] 全局配置里的 `coder_model`/`research_model`/`title_model` 降级为"默认回退值"文档说明。
- [x] 默认 Agent 定义从 3 个扩展到示例集（main/researcher/coder/reviewer/doc_writer），展示自定义能力。

### 阶段 2：工具可插拔（为非 coding 场景预留）

- [x] 工具注册改为分类注册（`coding`/`search`/`file`/`shell`/`mcp`），Agent 定义里按分类选工具。
- [ ] 预留 MCP 工具接入接口。
- [x] `delegate_agent` 的只读/handoff 分流逻辑从硬编码工具列表改为按工具分类判断。

### 阶段 3：GUI 参考 MoFox 优化

- [ ] 首次启动 Setup Wizard（参考 MoFox 的 `SetupWizard.tsx`）。
- [ ] 设置弹窗分区优化（模型/Agent/工具/安全 分 Tab，参考 MoFox 的 `SettingsModal`）。
- [ ] 前端多 Agent 时间线结构化。

### 阶段 4：安全分层

- [x] 命令风险分级（高危/只读/普通）。
- [x] 只读命令白名单（`git status`/`ls` 等直接放行）。
- [x] 路径边界保护（禁止访问 `work_dir` 外）。
- [ ] per-agent 工具权限策略（参考 MoFox 的 `PermissionLevel`）。

## 暂不做

- 不允许并行 researcher 写文件。
- 不加入真实 LLM/API 调用测试。
- 不重构完整 timeline/session 持久化模型（先做事件持久化）。
- 不把 researcher 原始全文无节制注入 main Agent 上下文。
