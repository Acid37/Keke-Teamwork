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

### 短期

1. **前端时间线结构化** — 把 research/handoff 事件从系统消息升级为独立 timeline 视图。
2. **事件持久化** — research/handoff 事件存入 session，刷新后不丢失。
3. **基础模块测试** — `SessionStore`、`AppConfig`、`PermissionManager`、`FileStagingArea`、`EditTool`。

### 中期

4. **安全策略细分** — 命令风险分级、只读白名单、路径边界保护。
5. **reviewer 审查流** — coder handoff 完成后自动触发 reviewer。
6. **Checkpoint 历史回滚** — 接入已定义的 `Checkpoint` / `FileSnapshot`。

## 暂不做

- 不允许并行 researcher 写文件。
- 不加入真实 LLM/API 调用测试。
- 不重构完整 timeline/session 持久化模型（先做事件持久化）。
- 不把 researcher 原始全文无节制注入 main Agent 上下文。
