# AI 开发文档

> 本文档面向开发者和 AI 协作助手，用于快速了解项目架构、代码规范和开发约定。

## 项目概述

Keke Teamwork 是一个本地多 Agent 协作工作台，当前处于 **v0.2** 阶段。核心能力：

- 单 Agent tool-calling 主循环 + 多 Agent 编排（Orchestrator）
- 只读并行 researcher 探索 + 安全 handoff 写入
- 工具分类注册与按分类自动分流
- 文件 staging / diff / 回滚 + 命令审批
- 会话持久化 + LLM 语义标题
- 自定义 Agent 角色（per-agent 模型 / 工具 / 提示词）
- React + Vite 前端，WebSocket 实时通信

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+、FastAPI、Uvicorn、WebSocket、OpenAI SDK |
| 前端 | React 19、TypeScript、Vite、lucide-react、react-markdown、highlight.js |
| 可选 | Anthropic SDK、Google GenAI SDK |

## 项目结构

```text
backend/
  agent.py              # Agent tool-calling 主循环
  orchestrator.py       # Agent 编排、委派和并行 researcher 入口
  ws_server.py          # FastAPI / WebSocket / API 路由
  config.py             # 应用配置与外观配置
  session.py            # 会话持久化
  agent_store.py        # Agent 定义持久化
  types.py              # 共享数据类型（AgentDefinition / Session / ToolContext 等）
  llm/
    client.py           # LLM 客户端（统一接口）
    providers.py        # OpenAI / Anthropic / Gemini provider 适配
  tools/
    base.py             # Tool 基类 + ToolCategory 枚举
    __init__.py         # 工具注册表 + 分类映射 + 分流辅助函数
    read.py  write.py  edit.py  console.py  grep.py  find.py  ls.py  delegate.py
  safety/
    file_staging.py     # 文件 staging / baseline / diff / rollback
    permission.py       # 命令审批管理

frontend/
  src/
    App.tsx             # 应用入口
    SessionContext.tsx  # 前端会话状态与 WebSocket 事件处理
    ws-client.ts        # WebSocket 客户端
    types.ts            # 前端类型定义
    theme.ts            # 主题配置
    components/         # UI 组件（AgentManager / ChatArea / SettingsDialog 等）

docs/
  ROADMAP.md            # 开发计划与里程碑
  SESSION_AGENDA.md     # 当前分支进展和下一步计划
  orchestrator-parallel-design.md  # 并行 researcher 设计草案

tests/
  test_delegate_agent.py
  test_orchestrator_parallel.py
  test_tool_categories.py

start.bat               # Windows 一键启动脚本
pyproject.toml          # Python 包配置
```

## 核心架构

### 消息执行路径

```
用户消息 → ws_server → AgentOrchestrator.run_user_message()
  ├─ Solo 模式 → 直接走单 Agent tool-calling 循环
  └─ 非 Solo 模式
       ├─ 触发并行只读 researcher（受 max_parallel_researchers 限制）
       │    └─ 合并摘要注入 main Agent 上下文（12k 字符上限）
       └─ main Agent 通过 delegate_agent 工具委派子任务
            ├─ 只读 Agent → 并行研究路径
            └─ 有写工具的 Agent → 安全 handoff（串行，复用 staging/permission）
```

### Agent 模型解析优先级

```
agent_def.model（per-agent 指定）
  → 角色回退值（research_model / coder_model，仅限 researcher/coder 角色）
    → main_model（全局默认）
```

`coder_model` / `research_model` / `title_model` 仅作为"默认回退值"。任何自定义角色只要设置了 `model` 字段，就优先使用 per-agent model。

### 工具分类注册

工具按 `ToolCategory` 枚举分类，分流逻辑基于分类自动判断：

| 分类 | 含义 | 有副作用 | 包含的工具 |
|---|---|---|---|
| `search` | 只读搜索和发现 | 否 | `read_file`、`grep_search`、`find_files`、`list_directory` |
| `file` | 文件读写和编辑 | 是 | `write_file`、`edit_file` |
| `shell` | 执行 shell 命令 | 是 | `run_console` |
| `coding` | 编排类工具 | 否 | `delegate_agent` |
| `mcp` | 预留 MCP 工具接入 | 待定 | （空，预留） |

**分流规则**：
- 拥有 `file` 或 `shell` 分类工具的 Agent → 有写能力 → 安全 handoff 路径
- 只有 `search` / `coding` 分类工具的 Agent → 只读 → 并行研究路径

新增工具只需在工具类上声明 `category` 类属性即可自动参与分流，无需修改 orchestrator。

### 关键模块职责

| 模块 | 职责 |
|---|---|
| `AgentOrchestrator` | 接管用户消息执行，协调并行研究、handoff、标题生成 |
| `Agent` | 单 Agent tool-calling 主循环（streaming + 多轮工具） |
| `AgentStore` | Agent 定义 CRUD，持久化到 `agents.json` |
| `SessionStore` | 会话持久化，存储在 `~/.keke-teamwork/sessions/` |
| `FileStagingArea` | 文件写入前记录 baseline，成功后生成 diff，异常时 rollback |
| `PermissionManager` | 非 YOLO 模式下命令审批（WebSocket 请求用户确认） |
| `LLMClient` | 统一 LLM 接口，支持 OpenAI / Anthropic / Gemini |

## 默认 Agent 定义

首次启动时写入 `agents.json`，包含 5 个示例角色：

| agent_id | 名称 | 角色 | 工具 | 说明 |
|---|---|---|---|---|
| `main` | 通用助手 | assistant | 全部工具 | 通用编程助手 |
| `researcher` | 研究员 | researcher | 只读工具 | 只读研究，分析代码库 |
| `coder` | 编码专家 | coder | 读写 + console | 专注编码实现 |
| `reviewer` | 代码审查员 | reviewer | 只读工具 | 检查代码质量和潜在问题 |
| `doc_writer` | 文档撰写师 | doc_writer | 读写 + 搜索（无 console） | 文档撰写 |

用户可创建任意自定义角色，不限于以上预设。

## 运行模式

| 模式 | 作用 |
|---|---|
| Auto Review | Agent 执行结束后自动展示文件变更 diff |
| YOLO | 跳过命令审批，直接执行 shell 命令（谨慎开启） |
| Solo | 强制使用 main Agent，不走多 Agent 编排 |

## 数据存储

```text
~/.keke-teamwork/
  config.json        # 应用配置（模型、端口等）
  appearance.json    # 外观配置（主题、壁纸等）
  agents.json        # Agent 定义
  sessions/          # 会话历史
  wallpapers/        # 自定义壁纸
```

## 开发与测试

### 后端测试

```bash
python -m unittest -v
```

当前 40 个测试通过，覆盖：
- 委派工具与 handoff 安全边界
- 并行 researcher 调度与合并
- LLM 标题生成与 fallback
- 工具分类注册与分流判断
- 主流程守卫

### 前端构建

```bash
cd frontend && npm run build
```

### 环境变量

| 变量 | 说明 |
|---|---|
| `CT_PROVIDER` | LLM 服务商（openai / anthropic / gemini） |
| `CT_API_KEY` | API Key |
| `CT_BASE_URL` | API 地址 |
| `CT_MODEL` | 主模型名 |
| `CT_CODER_MODEL` | coder 角色未指定 per-agent model 时的回退值 |
| `CT_RESEARCH_MODEL` | researcher 角色未指定 per-agent model 时的回退值 |
| `CT_TITLE_MODEL` | 标题生成未指定 model 时的回退值 |
| `CT_HOST` | 监听地址 |
| `CT_PORT` | 监听端口 |
| `CT_CONSOLE_TIMEOUT` | 命令执行超时（秒） |

## 代码规范

### 后端

- Python 3.11+，使用 `from __future__ import annotations` 延迟类型求值
- 类型注解：`str | None` 而非 `Optional[str]`
- dataclass 用于数据类型，Enum 用于分类
- 工具类继承 `Tool`，必须声明 `name`、`description`、`parameters`、`category`
- 所有新增后端行为都要有不依赖真实 LLM/API 的测试
- 不加入真实 LLM/API 调用测试

### 前端

- TypeScript strict 模式
- 组件放 `components/`，状态管理通过 `SessionContext`
- WebSocket 事件处理集中在 `SessionContext.tsx`
- Vite 构建已拆分 React / markdown / icons chunk

### 架构原则

1. 多 Agent 默认先只读协作
2. main Agent 或单一 coder 负责最终写入，避免并发写冲突
3. researcher 输出先合并、截断、标明来源，再进入 main Agent 上下文
4. 前端展示事件不等同于模型上下文，后续需要拆分 timeline 与 model messages
5. 所有新增后端行为都要有不依赖真实 LLM/API 的测试

## 当前限制

- 前端 research/handoff 事件以系统消息展示，尚未做独立时间线视图
- research/handoff 事件不持久化，刷新后丢失
- reviewer 审查流尚未落地
- `Checkpoint` / `FileSnapshot` 类型已定义，未形成完整回滚历史系统
- 命令审批是粗粒度策略，尚未做高危命令识别和只读命令白名单
- 基础模块（SessionStore、PermissionManager、FileStagingArea、EditTool）缺少独立测试

## 开发路线

详见 `docs/ROADMAP.md` 和 `docs/SESSION_AGENDA.md`。

当前优先级：

1. MCP 工具接入
2. 前端多 Agent 时间线结构化展示
3. 安全策略分层（命令风险分级、只读白名单、路径边界）
4. 基础模块测试补全
5. reviewer 审查流（research → plan → code → review 闭环）