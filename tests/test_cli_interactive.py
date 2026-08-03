"""CLI 交互模式（REPL）单元测试。

覆盖：
- INTERACTIVE_HELP 包含全部命令
- 输入 exit / q 直接退出
- 输入任务描述 → 分发到 _run_single_agent_message（单 agent 默认路径）
- /list 分发到会话列表
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from backend.cli import INTERACTIVE_HELP, _run_interactive_cli


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


def test_interactive_help_contains_commands() -> None:
    assert "/workdir" in INTERACTIVE_HELP
    assert "/list" in INTERACTIVE_HELP
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
    """输入任务描述 → 调用 _run_single_agent_message（单 agent 默认路径）。"""
    calls: list[tuple] = []

    async def fake_single(config, task_text, work_dir, yolo, session):
        calls.append((task_text, str(work_dir), yolo, session is None))
        return None

    monkeypatch.setattr("backend.cli._run_single_agent_message", fake_single)
    _patch_input(monkeypatch, ["实现登录功能", "q"])

    code = _run_interactive()
    assert code == 0
    assert calls == [("实现登录功能", str(Path.cwd()), False, True)]


def test_interactive_list_dispatch(monkeypatch) -> None:
    """/list 应调用 _list_sessions。"""
    listed: list[bool] = []

    def fake_list(config):
        listed.append(True)
        return 0

    monkeypatch.setattr("backend.cli._list_sessions", fake_list)
    _patch_input(monkeypatch, ["/list", "q"])

    code = _run_interactive()
    assert code == 0
    assert listed == [True]
