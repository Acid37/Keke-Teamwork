"""CLI 交互模式（REPL）单元测试。

覆盖：
- _interactive_args 参数命名空间构造
- INTERACTIVE_HELP 包含全部命令
- 输入 exit / q 直接退出
- 输入任务描述 → 分发到 _start_new_workflow
- /list 分发到会话列表
- /resume 分发到恢复逻辑
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from backend.cli import INTERACTIVE_HELP, _interactive_args, _run_interactive_cli


def _patch_input(monkeypatch, values):
    """将内置 input 替换为依次返回 values 的假实现。

    输入耗尽时抛 EOFError（模拟终端 EOF），让 _run_interactive_cli
    走正常的优雅退出路径，而不是以 StopIteration 崩溃。
    """
    it = iter(values)

    def fake_input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError("输入已耗尽")

    monkeypatch.setattr("builtins.input", fake_input)


class _FakeConfig:
    """最小配置替身：交互模式只在 /list 时访问 config，相关测试均已 patch。"""


def _run_interactive() -> int:
    """运行交互模式，传入最小配置替身。

    交互模式只在 /list 分支访问 config，而所有测试都已 patch 掉该路径，
    因此 _FakeConfig 无需实现 AppConfig 的任何字段。
    """
    return asyncio.run(_run_interactive_cli(_FakeConfig()))  # type: ignore[arg-type]


def test_interactive_args_defaults() -> None:
    args = _interactive_args("实现登录", Path("D:/my-project"), yolo=True)
    assert args.task == "实现登录"
    assert args.work_dir == str(Path("D:/my-project"))
    assert args.yolo is True
    assert args.no_auto_review is False
    assert args.resume is None


def test_interactive_help_contains_commands() -> None:
    assert "/workdir" in INTERACTIVE_HELP
    assert "/resume" in INTERACTIVE_HELP
    assert "exit" in INTERACTIVE_HELP


def test_interactive_exit_returns_zero(monkeypatch) -> None:
    """输入 exit 应直接退出并返回 0。"""
    _patch_input(monkeypatch, ["exit"])
    code = _run_interactive()
    assert code == 0


def test_interactive_quit_returns_zero(monkeypatch) -> None:
    """输入 q 也应退出。"""
    _patch_input(monkeypatch, ["q"])
    code = _run_interactive()
    assert code == 0


def test_interactive_task_dispatch(monkeypatch) -> None:
    """输入任务描述 → 调用 _start_new_workflow，work_dir 默认当前目录。"""
    calls: list[tuple[str, str]] = []

    async def fake_start(args, config):
        calls.append((args.task, args.work_dir))
        return 0

    monkeypatch.setattr("backend.cli._start_new_workflow", fake_start)
    _patch_input(monkeypatch, ["实现登录功能", "q"])

    code = _run_interactive()
    assert code == 0
    assert calls == [("实现登录功能", str(Path.cwd()))]


def test_interactive_list_dispatch(monkeypatch) -> None:
    """/list 应调用 _list_sessions，不应启动工作流。"""
    listed: list[bool] = []
    started: list[bool] = []

    def fake_list(config):
        listed.append(True)
        return 0

    async def fake_start(args, config):
        started.append(True)
        return 0

    monkeypatch.setattr("backend.cli._list_sessions", fake_list)
    monkeypatch.setattr("backend.cli._start_new_workflow", fake_start)
    _patch_input(monkeypatch, ["/list", "q"])

    code = _run_interactive()
    assert code == 0
    assert listed == [True]
    assert started == []


def test_interactive_resume_dispatch(monkeypatch) -> None:
    """/resume <id> 应调用 _resume_session，不启动新工作流。"""
    resumed: list[str] = []
    started: list[bool] = []

    async def fake_resume(args, config):
        resumed.append(args.resume)
        return 0

    async def fake_start(args, config):
        started.append(True)
        return 0

    monkeypatch.setattr("backend.cli._resume_session", fake_resume)
    monkeypatch.setattr("backend.cli._start_new_workflow", fake_start)
    _patch_input(monkeypatch, ["/resume cli-1722345678", "q"])

    code = _run_interactive()
    assert code == 0
    assert resumed == ["cli-1722345678"]
    assert started == []
