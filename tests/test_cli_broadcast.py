"""CLI 控制台广播闭包测试——阶段横幅、Agent 生命周期、工具调用、文件变更。"""

from __future__ import annotations

import asyncio

from backend.cli import _make_console_broadcast
from backend.cli_display import set_color_enabled


def _run(coro):
    """运行异步广播闭包。"""
    return asyncio.run(coro)


def _reset_color():
    set_color_enabled(False)


def test_agent_started_completed(capsys):
    """agent.started + agent.completed 应输出头部与完成摘要。"""
    _reset_color()
    broadcast = _make_console_broadcast()
    _run(broadcast("agent.started", {
        "agent_name": "方案规划师", "role": "planner", "agent_id": "planner",
    }))
    _run(broadcast("agent.completed", {
        "agent_name": "方案规划师", "role": "planner",
        "summary": "已产出计划",
        "usage": {"input_tokens": 1000, "output_tokens": 500},
    }))
    out = capsys.readouterr().out
    assert "planner" in out
    assert "方案规划师" in out
    assert "1,000 in" in out


def test_agent_text_streaming_markdown(capsys):
    """agent.text 应按 Markdown 流式渲染。"""
    _reset_color()
    broadcast = _make_console_broadcast()
    _run(broadcast("agent.started", {
        "agent_name": "编码专家", "role": "coder", "agent_id": "coder",
    }))
    _run(broadcast("agent.text", {"text": "**完成** ", "is_final": False}))
    _run(broadcast("agent.text", {"text": "`calc.py` 已更新\n", "is_final": False}))
    out = capsys.readouterr().out
    assert "完成" in out
    assert "**" not in out
    assert "`" not in out
    assert "calc.py" in out


def test_phase_banner_only_on_change(capsys):
    """同一阶段的状态事件不应重复打印横幅。"""
    _reset_color()
    broadcast = _make_console_broadcast()
    _run(broadcast("agent.status", {"phase": "planning", "detail": "开始"}))
    _run(broadcast("agent.status", {"phase": "planning", "detail": "继续"}))
    _run(broadcast("agent.status", {"phase": "completed", "detail": "完成"}))
    out = capsys.readouterr().out
    assert out.count("planning") == 1
    assert out.count("completed") == 1


def test_tool_call_lifecycle(capsys):
    """工具调用开始/完成应输出单行状态。"""
    _reset_color()
    broadcast = _make_console_broadcast()
    _run(broadcast("agent.started", {
        "agent_name": "编码专家", "role": "coder", "agent_id": "coder",
    }))
    _run(broadcast("tool.call", {
        "name": "edit_file", "stage": "running",
        "args": {"path": "src/calc.py"}, "call_id": "1",
    }))
    _run(broadcast("tool.call", {
        "name": "edit_file", "stage": "completed",
        "args": {"result": ""}, "call_id": "1", "success": True,
    }))
    out = capsys.readouterr().out
    assert "edit_file" in out
    assert "src/calc.py" in out
    assert "ok" in out


def test_tool_call_completed_overwrites_running(monkeypatch, capsys):
    """彩色模式下完成行应原位覆盖运行行，不产生换行残影。"""
    import shutil

    class _Term:
        columns = 60
        lines = 24

    monkeypatch.setattr(shutil, "get_terminal_size", lambda *a, **k: _Term())
    set_color_enabled(True)
    broadcast = _make_console_broadcast()
    _run(broadcast("tool.call", {
        "name": "find_files", "stage": "running",
        "args": {"path": r"C:\very\long\path", "pattern": "*.png"},
        "call_id": "1",
    }))
    _run(broadcast("tool.call", {
        "name": "find_files", "stage": "completed",
        "args": {"result": "a.png\nb.png\nc.png"},
        "call_id": "1", "success": True,
    }))
    out = capsys.readouterr().out
    # 运行行不换行，完成行用 \r\033[2K 覆盖后独占一行
    assert out.count("\n") == 1
    assert "\n\r" not in out
    assert "（共 3 行）" in out


def test_files_changed(capsys):
    """files.changed 应输出文件摘要与彩色 diff。"""
    _reset_color()
    broadcast = _make_console_broadcast()
    _run(broadcast("files.changed", {
        "files": [{"path": "src/calc.py", "action": "modify"}],
        "combined_diff": "+def mul(a, b):\n+    return a * b",
    }))
    out = capsys.readouterr().out
    assert "文件变更" in out
    assert "src/calc.py" in out
    assert "def mul" in out


def test_error_event(capsys):
    """error 事件应输出错误行。"""
    _reset_color()
    broadcast = _make_console_broadcast()
    _run(broadcast("error", {"message": "LLM 调用失败", "recoverable": True}))
    out = capsys.readouterr().out
    assert "ERROR" in out
    assert "LLM 调用失败" in out
