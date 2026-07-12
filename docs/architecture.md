# 架构文档

> 项目架构、技术栈、核心流程和安全设计。

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

tests/
  test_delegate_agent.py
  test_orchestrator_parallel.py
  test_tool_categories.py
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
  → main_model（全局默认）
```

`role` 字段只是显示/组织标签，不触发任何模型回退或特殊工具分流。
所有自定义角色只要设置了 `model` 字段，就优先使用 per-agent model；否则统一回退到 `main_model`。
`title_model` 仅用于会话标题生成服务，不属于 Agent 角色模型映射。

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
| `PermissionManager` | 命令审批，集成风险分级（只读自动放行、高危强制审批） |
| `CommandRisk` | 命令风险分类（read_only / normal / dangerous） |
| `PathGuard` | 路径边界保护，禁止工具访问 `work_dir` 外路径 |
| `LLMClient` | 统一 LLM 接口，支持 OpenAI / Anthropic / Gemini |

### 安全分层

#### 命令风险分级

`backend/safety/command_risk.py` 将 shell 命令分为三级：

| 级别 | 含义 | 审批行为 |
|---|---|---|
| `read_only` | 只读命令（`ls`、`git status`、`cat` 等） | 自动放行，无需审批 |
| `normal` | 普通命令（`git add`、`npm install` 等） | 非 YOLO 模式需审批，YOOLO 模式放行 |
| `dangerous` | 高危命令（`rm -rf`、`git push --force`、`shutdown` 等） | 始终需要审批，即使 YOLO 模式 |

`PermissionManager.check()` 根据风险级别决定审批流程：
- `read_only` → `"allow"`
- `dangerous` → `"needs_approval"`（即使 YOLO）
- `normal` → YOLO 模式 `"allow"`，否则 `"needs_approval"`

#### 路径边界保护

`backend/safety/path_guard.py` 确保所有 file/search 类工具只能访问 `work_dir` 内的路径：

- `resolve_path(path_str, work_dir)` — 解析路径并检查边界，越界抛出 `PathBoundaryError`
- 相对路径自动拼接 `work_dir`，绝对路径直接检查
- `..` 逃逸、绝对路径越界、符号链接指向外部均被拦截
- 已接入 `read_file`、`write_file`、`edit_file`、`grep_search`、`find_files`、`list_directory`

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
| `CT_TITLE_MODEL` | 标题生成未指定 model 时的回退值 |
| `CT_HOST` | 监听地址 |
| `CT_PORT` | 监听端口 |
| `CT_CONSOLE_TIMEOUT` | 命令执行超时（秒） |
