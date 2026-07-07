# Coding Teamwork 开发计划书

> 版本：v0.1 → v0.2  
> 日期：2026-07-07  
> 当前定位：单 Agent coding assistant 已可运行；安全基线已初步接入；下一阶段重点是兑现 “Teamwork” 多 Agent 协作。

## 一、当前状态

### 已落地能力

| 模块 | 状态 | 说明 |
|---|---|---|
| Web UI 工作台 | ✅ 已可用 | 支持项目打开、最近项目、聊天流、工具调用卡片、设置面板和外观配置。 |
| 单 Agent Tool Calling | ✅ 已可用 | `backend/agent.py` 已实现 LLM streaming + tool calls + 多轮工具循环。 |
| 本地代码工具 | ✅ 已可用 | 具备读文件、写文件、编辑、grep、find、ls、console 等工具。 |
| FileStagingArea | ✅ 已接入 | 文件写入会记录 baseline，成功后可生成 diff，异常/中断时尝试 rollback。 |
| 命令审批 | ✅ 已接入 | 非 YOLO 模式下 `run_console` 执行前通过 WebSocket 请求用户审批。 |
| 三模式开关 | ✅ 已生效 | `yolo_mode`、`auto_review`、`solo_mode` 已接入后端执行路径。 |
| 会话持久化 | ✅ 已可用 | 会话保存到 `~/.coding-teamwork/sessions`。 |
| Agent CRUD | ✅ 已可用 | 可创建、编辑、删除 Agent 定义，并配置模型、工具、提示词等。 |
| 多 provider 支持 | ✅ 初步可用 | 支持 OpenAI-compatible、Anthropic、Gemini。 |
| 外观系统 | ✅ 已可用 | 支持主题色、字体、壁纸、暗色/亮色/自动模式。 |

### 未落地或不完整能力

| 模块 | 状态 | 问题 |
|---|---|---|
| Orchestrator 编排器 | ❌ 未实现 | 当前没有统一的多 Agent 调度入口。 |
| Agent 委派 / handoff | ❌ 未实现 | 主 Agent 不能把子任务委托给其他 Agent。 |
| 并行 researcher | ❌ 未实现 | `max_parallel_researchers` 有配置但未使用。 |
| coder/research 模型路由 | ⚠️ 部分预留 | `coder_model` / `research_model` 有配置项，但角色路由未完整接入。 |
| Checkpoint 历史回滚 | ⚠️ 类型预留 | `Checkpoint` / `FileSnapshot` 已定义，但尚未形成可用历史系统。 |
| 自动化测试 | ❌ 缺失 | 当前没有测试文件，后续演进风险较高。 |
| 安全策略细分 | ⚠️ 粗粒度 | 目前主要是审批/YOLO，缺少高危命令识别、只读白名单和路径边界保护。 |
| 历史事件持久化 | ⚠️ 不完整 | 前端工具卡片、文件变更等事件尚未完整作为 timeline 保存。 |

## 二、v0.2 核心目标

v0.2 的目标不是继续堆 UI，而是让项目名副其实：

> 从 “单 Agent coding assistant” 升级为 “可编排的多 Agent coding teamwork”。

验收时应满足：

1. 主 Agent 可以委派子任务给其他 Agent。
2. researcher / coder / reviewer 至少形成一条可运行协作链路。
3. Solo 模式仍能回退到当前单 Agent 运行路径。
4. 多 Agent 运行过程中的消息、工具调用和文件变更能在前端区分来源。
5. 关键后端模块具备基础测试。

## 三、阶段计划

### Phase A — 文档和稳定性基线

目标：让项目能力边界清楚，降低后续开发误判。

- [x] 新增根目录 `README.md`
- [x] 更新 `docs/ROADMAP.md`
- [ ] 补充 LICENSE 或明确私有项目状态
- [ ] 标注 UI 中尚未完全生效的 `coder_model` / `research_model`
- [ ] 梳理一份最小测试清单

### Phase B — Orchestrator 最小实现

目标：引入统一编排入口，但不一次性做复杂工作流。

当前进展：

- [x] 新增 `backend/orchestrator.py`
- [x] 将单 Agent 执行流程封装到 `AgentOrchestrator.run_user_message()`
- [x] `WebSocketServer._handle_user_message()` 改为委托 Orchestrator
- [x] Solo 模式仍强制使用 `main` Agent
- [ ] 增加 Orchestrator 基础测试
- [x] 在 Orchestrator 内暴露子 Agent runner，供 `delegate_agent` 使用

建议新增：

```text
backend/orchestrator.py
```

核心职责：

1. 接收 `session`、`agent_id`、用户消息和广播回调。
2. 根据 `session.solo_mode` 决定：
   - Solo ON：沿用当前单 Agent 路径。
   - Solo OFF：走 orchestrator 调度路径。
3. 提供统一的 Agent 创建和运行封装。
4. 负责把子 Agent 结果汇总给主 Agent。

建议验收：

- [x] `_handle_user_message` 中 Agent 运行逻辑被迁移/封装到 Orchestrator。
- [x] Solo 模式行为保持不变。
- [x] 非 Solo 模式至少可以由 Orchestrator 调用 main Agent。
- [ ] 现有 WebSocket 事件不破坏前端显示。

### Phase C — `delegate_agent` 工具

目标：让主 Agent 具备“委派任务”的能力。

当前进展：

- [x] 新增 `backend/tools/delegate.py`
- [x] `main` 默认工具列表加入 `delegate_agent`
- [x] `ToolContext` 增加 `delegate_runner`
- [x] Orchestrator 提供只读子 Agent runner
- [x] 子 Agent 默认限制为 `read_file` / `grep_search` / `find_files` / `list_directory`
- [ ] 增加 `delegate_agent` 自动化测试
- [ ] 改进前端多 Agent 时间线展示

建议新增：

```text
backend/tools/delegate.py
```

工具参数：

| 参数 | 说明 |
|---|---|
| `agent_id` | 目标 Agent ID，例如 `researcher`、`coder`、`reviewer`。 |
| `task` | 子任务描述。 |
| `context` | 可选上下文，如相关文件、约束、当前发现。 |

执行策略：

1. `delegate_agent` 不直接 new 独立系统，应调用 Orchestrator 提供的子 Agent runner。
2. 子 Agent 默认可读文件和搜索，但写文件权限应按角色和工具配置决定。
3. 子 Agent 输出作为 tool result 回传给主 Agent。
4. 前端通过 `agent.started` / `agent.completed` / `agent.text` 区分来源。

建议验收：

- [x] main Agent 可以调用 `delegate_agent`。
- [x] 子 Agent 可独立完成只读研究任务。
- [x] 子 Agent 结果能回到主 Agent 上下文。
- [x] 前端能显示子 Agent 的名称和角色。

### Phase D — 并行 researcher

目标：兑现 “Teamwork” 的第一类真实收益：并行探索代码库。

实现建议：

1. Orchestrator 支持创建多个 researcher 子任务。
2. 使用 `asyncio.gather` 并行运行。
3. 使用 `AppConfig.max_parallel_researchers` 限制并发。
4. researcher 默认只配置只读工具：
   - `read_file`
   - `grep_search`
   - `find_files`
   - `list_directory`
5. 汇总结果后交给 coder 或 main Agent。

建议验收：

- [ ] 一个复杂任务可拆成多个 researcher 子问题。
- [ ] 并行数量受配置限制。
- [ ] researcher 不具备写文件和运行命令权限，除非用户显式配置。
- [ ] 汇总结果简洁，不污染过多上下文。

### Phase E — 角色模型路由

目标：让已有模型配置真正生效。

路由规则建议：

| Agent role | 默认模型 |
|---|---|
| `researcher` | `research_model`，为空则 `main_model` |
| `coder` | `coder_model`，为空则 `main_model` |
| `reviewer` | `main_model` 或后续新增 `review_model` |
| 其他 | `main_model` |

同时保留 AgentDefinition 中的 `model` 作为最高优先级 override：

```text
agent.model > role model > main_model
```

建议验收：

- [x] researcher 默认使用 `research_model`。
- [x] coder 默认使用 `coder_model`。
- [x] Agent 自定义 model 优先级最高。
- [ ] 设置界面文案与实际行为一致。

### Phase F — 测试与安全加固

目标：防止多 Agent 后复杂状态失控。

优先测试：

- [ ] `SessionStore` save/load/list/delete
- [ ] `AppConfig` 文件配置与环境变量覆盖
- [ ] `PermissionManager` approve/deny/timeout
- [ ] `FileStagingArea` create/modify/delete/rollback
- [ ] `EditTool` 精确替换、重复匹配、换行兼容
- [ ] LLM provider message conversion
- [ ] Orchestrator solo / non-solo 路径
- [ ] `delegate_agent` 成功和失败路径

安全增强：

- [ ] 命令风险分级
- [ ] 只读命令白名单
- [ ] 高危命令强制二次确认
- [ ] 限制工具访问 `work_dir` 外路径
- [ ] 对 `.env`、密钥文件、系统目录增加保护提示
- [ ] 明确二进制文件不参与文本 rollback 的边界

## 四、建议里程碑

| 里程碑 | 内容 | 目标 |
|---|---|---|
| v0.2-alpha | Orchestrator 最小实现 + Solo 兼容 | 编排入口成型，不破坏现有功能。 |
| v0.2-beta | `delegate_agent` + researcher/coder 基础协作 | 初步兑现 Teamwork。 |
| v0.2-rc | 并行 researcher + 角色模型路由 + 基础测试 | 可用于真实项目试用。 |
| v0.2 | 安全加固 + 文档完善 + 已知问题收敛 | 形成较稳定版本。 |

## 五、架构演进建议

### 1. 分离模型上下文和前端时间线

当前 `session.messages` 同时承担：

- 发给模型的上下文
- 前端历史展示来源

后续建议拆分：

```text
session.model_messages   # LLM 上下文
session.timeline_events  # UI 展示事件
session.file_changes     # 文件变更记录
```

这样可以避免多 Agent 场景下工具卡片、diff、thinking 和 assistant 消息混在一起难以恢复。

### 2. 将 Agent 运行封装为可复用 runner

当前 `_handle_user_message` 里包含较多职责：

- AgentDefinition 解析
- LLM client 选择
- tool context 创建
- 回调广播
- staging commit/rollback
- session 保存

建议逐步抽出：

```text
AgentRunner
Orchestrator
ToolExecutionContextFactory
```

不要一次性大重构，优先围绕 Orchestrator 抽最小必要代码。

### 3. 多 Agent 默认先只读协作

第一版 Teamwork 不建议让多个 Agent 同时写文件。更稳的路径是：

1. 多 researcher 并行只读探索。
2. main/planner 汇总方案。
3. 单 coder 写文件。
4. reviewer 审查 diff。

这能减少写入冲突和 rollback 复杂度。

## 六、当前风险

1. **上下文膨胀**：多 Agent 结果如果直接全部塞回主上下文，会很快超过模型窗口。
2. **文件写入冲突**：多个 Agent 同时写文件会让 staging/rollback 复杂度暴涨。
3. **WebSocket 事件归属**：需要确保每个事件都有 `agent_id`、`role`、`call_id`。
4. **工具权限过大**：Agent 管理允许配置工具，但缺少角色级默认安全策略。
5. **无测试保护**：当前状态下大改 Orchestrator 容易破坏现有单 Agent 流程。

## 七、近期推荐顺序

1. 写 Orchestrator 最小壳，保持现有行为不变。
2. 把 `_handle_user_message` 中 Agent 运行逻辑抽成 runner。
3. 增加 `delegate_agent`，先支持只读 researcher。
4. 补 `PermissionManager`、`FileStagingArea`、`SessionStore` 测试。
5. 加角色模型路由。
6. 再做并行 researcher。

核心原则：

> **先让一个主 Agent 安全地委派一个只读子 Agent；稳定后再并行，再允许写入。**
