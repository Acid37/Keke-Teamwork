# Coding Teamwork

> 一个自研的本地多 Agent 协作工作台：用 Web UI 管理项目、会话、模型、自定义 Agent 角色，并通过工具调用帮助你阅读、搜索、修改和运行本地代码。

Coding Teamwork 当前处于 **v0.2** 阶段。它已经具备单 Agent 编码助手、文件变更审查、命令审批、会话持久化、自定义 Agent 管理、只读多 Agent 并行研究、安全 handoff、LLM 语义标题和工具权限分流。

## 当前定位

Coding Teamwork 不是普通聊天壳，也还不是完整成熟的多 Agent IDE。当前更准确的定位是：

> **一个可运行的本地多 Agent 协作工作台，支持自定义角色、工具权限分流和 LLM 语义标题。**

它适合用来：

- 打开本地项目并和 Agent 对话
- 让 Agent 阅读、搜索、编辑项目文件
- 在执行终端命令前请求用户审批
- 查看 Agent 写入文件后的 diff
- 管理不同 Agent 角色、模型、工具权限和提示词
- 创建任意自定义角色（不限于预设角色），按工具权限自动分流
- 在非 Solo 模式下尝试并行 researcher 只读探索代码库
- 尝试 OpenAI-compatible / Anthropic / Gemini 等模型提供方

## 功能概览

### 已支持

- **Web UI 工作台**：React + Vite 前端，支持项目打开、最近项目、聊天流、工具调用卡片和设置面板。
- **Agent Tool Calling Loop**：后端 Agent 可流式调用 LLM，并根据模型返回的 tool calls 执行工具。
- **本地代码工具**：支持读取文件、写入文件、编辑文件、搜索内容、查找文件、列目录和执行命令。
- **文件变更审查**：写入通过 `FileStagingArea` 记录 baseline，执行成功后生成 unified diff。
- **异常回滚**：Agent 被中断或执行异常时，会尝试回滚本轮文件写入。
- **命令审批**：非 YOLO 模式下，`run_console` 执行前会弹出审批框。
- **YOLO / Auto Review / Solo 模式**：可控制命令审批、diff 展示和是否强制单 Agent。
- **会话持久化**：会话存储在用户目录下，支持恢复历史项目与会话。
- **模型配置**：支持 OpenAI 兼容接口、Anthropic 和 Gemini，并提供常见 OpenAI-compatible 服务商预设。
- **Agent 管理**：可创建和编辑任意自定义 Agent 定义，包括名称、角色、模型、温度、工具列表、最大工具轮次和系统提示词。角色不限于预设名称，任何角色都能独立配置模型。
- **工具权限分流**：Agent 分流（只读研究 vs 安全 handoff）基于工具权限自动判断，不再依赖角色名。只有只读工具的 Agent 走并行研究路径，有写工具的 Agent 走安全 handoff 路径。
- **外观设置**：支持主题色、暗色/亮色/自动模式、字体大小和壁纸。
- **Orchestrator 编排入口**：`AgentOrchestrator` 已接管用户消息执行路径，并保持 Solo 模式兼容。
- **只读委派**：`delegate_agent` 可把聚焦子任务委派给其他 Agent，默认限制为读文件、搜索和列目录。
- **并行 researcher**：非 Solo 模式下可受控触发多个 researcher 并发探索，受 `max_parallel_researchers` 限制。
- **Research summary 注入**：researcher 合并结论以受限摘要注入 main Agent 上下文，12k 字符上限，Solo 模式不注入。
- **安全 handoff**：`delegate_agent` 对有写工具的 Agent 走串行 handoff，复用主流程 staging/permission 边界，禁止嵌套委派。
- **Handoff 事件展示**：前端展示 `handoff.started` / `handoff.completed` / `handoff.failed`。
- **LLM 语义标题**：异步 LLM 生成会话标题，支持独立 `title_model` 配置（可选轻量模型），算法 fallback。
- **单窗口启动**：`start.bat` 前台单窗口运行，关闭窗口即停服务。
- **基础测试与 CI**：已补充委派、并行研究、handoff、标题生成、工具权限分类和主流程守卫测试；CI 执行 `python -m unittest -v`。

### 计划支持

- 工具可插拔分类注册（coding/search/file/shell/mcp），为非 coding 场景预留
- MCP 工具接入
- 首次启动 Setup Wizard
- 前端多 Agent 时间线结构化展示
- research/handoff 事件持久化
- 安全策略分层（命令风险分级、只读白名单、路径边界保护）
- Checkpoint 历史回滚系统
- 基础模块独立测试（SessionStore、PermissionManager、FileStagingArea 等）

## 技术栈

### 后端

- Python 3.11+
- FastAPI
- Uvicorn
- WebSocket
- OpenAI Python SDK
- 可选：Anthropic SDK、Google GenAI SDK

### 前端

- React 19
- TypeScript
- Vite
- lucide-react
- react-markdown
- highlight.js

## 项目结构

```text
backend/
  agent.py              # Agent tool-calling 主循环
  orchestrator.py       # Agent 编排、委派和并行 researcher 入口
  ws_server.py          # FastAPI / WebSocket / API 路由
  config.py             # 应用配置与外观配置
  session.py            # 会话持久化
  agent_store.py        # Agent 定义持久化
  llm/                  # LLM provider 适配层
  tools/                # 本地代码工具
  safety/               # 文件 staging 与命令审批

frontend/
  src/
    App.tsx
    SessionContext.tsx  # 前端会话状态与 WebSocket 事件处理
    ws-client.ts        # WebSocket 客户端
    components/         # UI 组件

docs/
  ROADMAP.md            # 开发计划与里程碑
  SESSION_AGENDA.md     # 当前分支进展和下一步计划
  orchestrator-parallel-design.md # 并行 researcher 设计草案

start.bat               # Windows 一键启动脚本
pyproject.toml          # Python 包配置
```

## 快速开始

### 环境要求

- Windows/macOS/Linux 均可运行；当前仓库提供了 Windows 一键启动脚本。
- Python 3.11+
- Node.js 18+
- 一个可用的 LLM API Key

### Windows 一键启动

双击运行：

```text
start.bat
```

脚本会自动：

1. 检查 Python 和 Node.js
2. 安装后端依赖
3. 安装前端依赖
4. 构建前端
5. 启动后端服务
6. 打开浏览器访问 `http://127.0.0.1:8765/`

### 首次配置模型

启动后进入页面右上角设置：

1. 选择服务商
2. 填入 API Key
3. 设置 API 地址和模型名
4. 保存配置

默认配置偏向 DeepSeek OpenAI-compatible 接口：

```text
Provider: openai
Base URL: https://api.deepseek.com/v1
Model: deepseek-chat
```

也可以通过环境变量覆盖配置：

```text
CT_PROVIDER
CT_API_KEY
CT_BASE_URL
CT_MODEL
CT_CODER_MODEL
CT_RESEARCH_MODEL
CT_TITLE_MODEL
CT_HOST
CT_PORT
CT_CONSOLE_TIMEOUT
```

## 使用方式

1. 打开 Web UI。
2. 点击“打开项目”，选择一个本地代码目录。
3. 在聊天框输入开发任务。
4. 如果 Agent 需要执行命令，确认审批弹窗。
5. 如果 Agent 修改了文件，查看自动生成的 diff。

## 三种运行模式

| 模式 | 作用 |
|---|---|
| Auto Review | Agent 执行结束后自动展示文件变更 diff。 |
| YOLO | 跳过命令审批，直接执行 shell 命令。请谨慎开启。 |
| Solo | 强制使用 main Agent，为未来多 Agent 编排预留。 |

关闭 Solo 后，当前分支会在存在只读 Agent 时先运行只读并行研究，把合并摘要注入 main Agent 上下文，并把研究状态作为独立消息展示。main Agent 也可以通过 `delegate_agent` 把写入任务安全 handoff 给有写工具的 Agent，该 Agent 复用主流程的 staging/permission 边界，但不能嵌套委派。分流基于工具权限自动判断，不依赖角色名。

## 可用工具

| 工具 | 说明 |
|---|---|
| `read_file` | 读取文件内容。 |
| `write_file` | 创建或覆盖文件。 |
| `edit_file` | 精确搜索并替换文本。 |
| `run_console` | 在项目目录下执行 shell 命令。 |
| `grep_search` | 使用正则搜索文件内容。 |
| `find_files` | 按名称模式查找文件。 |
| `list_directory` | 列出目录树。 |
| `delegate_agent` | 将子任务委派给其他 Agent；只读 Agent 走并行研究路径，有写工具的 Agent 走安全 handoff。 |

## 数据存储

用户配置、会话、Agent 定义和壁纸等数据默认保存在：

```text
~/.coding-teamwork
```

其中包括：

- `config.json`
- `appearance.json`
- `agents.json`
- `sessions/`
- `wallpapers/`

## 当前限制

- 前端 research/handoff 事件目前以系统消息展示，尚未做独立时间线视图。
- research/handoff 事件不持久化，刷新页面后丢失。
- reviewer 审查流尚未落地（coder handoff 完成后无自动审查）。
- `Checkpoint` / `FileSnapshot` 类型已定义，但未形成完整回滚历史系统。
- 文件 staging 会扫描项目文本文件，大项目上可能有性能压力。
- 命令审批目前是粗粒度策略，尚未做高危命令识别和只读命令白名单。
- 基础模块（SessionStore、PermissionManager、FileStagingArea、EditTool）缺少独立测试。

## 开发路线

详见 `docs/ROADMAP.md`。

当前优先级：

1. 工具可插拔分类注册，为非 coding 场景预留。
2. MCP 工具接入。
3. 前端多 Agent 时间线结构化展示。
4. 安全策略分层（命令风险分级、只读白名单、路径边界）。
5. 基础模块测试补全。

当前已验证：

- `python -m unittest -v`：22 个测试通过。
- `npm run build`：前端构建通过。

## 许可证

当前仓库尚未声明许可证。发布或开源前建议补充明确的 LICENSE 文件。