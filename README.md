# Keke Teamwork

> 一个自研的本地多 Agent 协作工作台：用 Web UI 管理项目、会话、模型和自定义 Agent，并通过工具调用帮助你阅读、搜索、修改和运行本地代码。

Keke Teamwork 当前处于 **v0.2** 阶段。它已经具备单 Agent 编码助手、文件变更审查、命令审批、会话持久化、自定义 Agent 管理、只读多 Agent 并行研究、安全 handoff、LLM 语义标题和工具权限分流。

## 当前定位

Keke Teamwork 不是普通聊天壳，也还不是完整成熟的多 Agent IDE。当前更准确的定位是：

> **一个可运行的本地多 Agent 协作工作台，支持自定义 Agent、工具权限分流和 LLM 语义标题。**

它适合用来：

- 打开本地项目并和 Agent 对话
- 让 Agent 阅读、搜索、编辑项目文件
- 在执行终端命令前请求用户审批
- 查看 Agent 写入文件后的 diff
- 管理不同 Agent、模型、工具权限和提示词
- 创建任意自定义 Agent，按工具权限自动分流
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
- **Agent 管理**：可创建和编辑任意自定义 Agent 定义，包括名称、标签、模型、温度、工具列表、最大工具轮次和系统提示词。
- **工具权限分流**：Agent 分流（只读研究 vs 安全 handoff）基于工具分类自动判断，不再依赖角色名。
- **外观设置**：支持主题色、暗色/亮色/自动模式、字体大小和壁纸。
- **只读并行研究**：非 Solo 模式下可受控触发多个只读 Agent 并发探索，合并摘要注入 main Agent 上下文。
- **安全 handoff**：`delegate_agent` 对有写工具的 Agent 走串行 handoff，复用主流程 staging/permission 边界，禁止嵌套委派。
- **LLM 语义标题**：异步 LLM 生成会话标题，支持独立 `title_model` 配置，算法 fallback。
- **单窗口启动**：`start.bat` 前台单窗口运行，关闭窗口即停服务。

### 计划支持

- MCP 工具接入
- 首次启动 Setup Wizard
- 前端多 Agent 时间线结构化展示
- per-agent 工具权限策略
- reviewer 审查流（research → plan → code → review 闭环）
- Checkpoint 历史回滚系统

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
6. 在终端打印访问地址（默认不自动打开浏览器）

启动后可手动打开：

```text
http://127.0.0.1:8765/
```

如果确实需要自动打开浏览器，可运行：

```text
start.bat --open-browser
```

### 首次配置模型

启动后进入页面右上角设置：

1. 选择服务商
2. 填入 API Key
3. 设置 API 地址和模型名
4. 保存配置

默认配置兼容任意 OpenAI-compatible 接口，例如：

```text
Provider: openai
Base URL: https://api.deepseek.com
Model: deepseek-v4-flash
```

也可以通过环境变量覆盖配置，详见 `docs/architecture.md`。

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
| Solo | 强制使用 main Agent，不走多 Agent 编排。 |

关闭 Solo 后，在存在只读 Agent 时会先运行只读并行研究，把合并摘要注入默认 Agent 上下文。主流程也可以通过 `delegate_agent` 把写入任务安全 handoff 给有写工具的 Agent。分流基于工具分类自动判断，不依赖标签名。

## 数据存储

用户配置、会话、Agent 定义和壁纸等数据默认保存在：

```text
~/.keke-teamwork
```

## 开发者文档

项目架构和工具分类等技术细节，详见 [`docs/architecture.md`](docs/architecture.md)。  
代码规范和架构原则，详见 [`docs/conventions.md`](docs/conventions.md)。  
开发路线和当前待办，详见 [`docs/roadmap.md`](docs/roadmap.md) 和 [`docs/sprint/current.md`](docs/sprint/current.md)。

## 许可证

本仓库采用 **MIT License**，详见 `LICENSE`。