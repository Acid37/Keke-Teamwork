# 新会话启动提示词 — Step 9 端到端联调

> 直接复制下方内容粘贴到新会话即可。

---

继续 v0.4 工作流引擎开发。当前项目在 `d:\Keke Teamwork`，后端引擎 Step 1-7 + 打磨阶段已全部完成，517 个测试通过。

**本次目标：Step 9 端到端联调（约 1 天）**

## 核心任务

1. **真实 LLM 全链路验证**：用真实 LLM 跑通 CLI 完整工作流（plan → code → review → feedback → completed），验证产出物解析器在真实 LLM 输出下的鲁棒性，重点关注格式偏离、多余文本、Markdown 包裹等真实场景
2. **`--resume` 恢复机制验证**：中断后重连能从正确阶段继续，确认 session JSON 状态持久化与恢复逻辑一致
3. **`/undo` 命令验证**：在真实场景下验证状态回退，确认文件变更和 WorkflowState 都能正确回滚
4. **边界 case 补充测试**：
   - LLM 输出格式偏离预期时的降级处理
   - 空 TaskList（planner 返回 0 个任务）
   - 单任务工作流
   - 全部任务被跳过 / 全部重试超限
   - 大量文件变更场景
5. **修复联调中发现的问题**，确保修复后测试仍然全绿

## 关键文件

| 模块 | 文件 |
|------|------|
| 引擎核心 | `backend/workflow/engine.py`、`backend/orchestrator.py` |
| CLI | `backend/cli.py`、`backend/cli_display.py` |
| 解析器 | `backend/workflow/parser.py` |
| 类型定义 | `backend/workflow/types.py`、`backend/types.py` |
| Prompt 构建 | `backend/prompt_builder.py` |
| 项目结构扫描 | `backend/workflow/repo_map.py` |
| 测试 | `tests/` 目录下已有 517 个测试 |
| 设计文档 | `docs/designs/工作流引擎.md` |
| 迭代文档 | `docs/sprint/当前迭代.md` |

## 项目约定

- CLI 是工作流引擎开发期间的主要验证界面
- FEEDBACK 循环重试上限 3 次，超限自动跳过当前任务
- WorkflowState 包含 `retry_count` 和 `total_files_changed` 字段，持久化到 session JSON
- 任务进度指示：broadcast 显示"任务 1/5"，coder 消息含"（任务 2/5）"，重试显示"（重试第 N 次）"
- 不引入真实 LLM/API 调用到单元测试中；联调验证通过手动或脚本执行
- 每完成一个子任务先提交 Git，commit message 用中文，格式如 `feat: 端到端联调 - xxx` 或 `fix: xxx`

## 联调前确认

1. **LLM 配置**：确认 `.env` 或环境变量中 API Key 已配置，模型可用
2. **测试基线**：联调开始前先运行 `python -m pytest tests/ -q` 确认 517 个测试全绿
3. **Git 状态**：确认工作区干净，无未提交改动

## 预期产出物

- 联调问题清单及修复记录（更新到 `docs/sprint/当前迭代.md`）
- 新增边界 case 测试（合并到 `tests/` 对应文件）
- 联调完成后更新迭代文档，标注 Step 9 完成状态
- 最终测试全绿，准备进入 Step 8（前端工作流时间线）

## 启动方式

先读项目记忆（`c:\Users\25830\.trae-cn\memory\projects\` 下当前项目目录）和迭代文档 `docs/sprint/当前迭代.md` 了解完整上下文，然后开始联调。
