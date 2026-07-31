"""CLI 显示工具——ANSI 彩色输出、进度条、阶段横幅。

支持 Windows 10+（自动启用 VT 处理）和 Unix 终端。
非 TTY 输出时自动降级为纯文本（无 ANSI 转义码）。
"""

from __future__ import annotations

import os
import sys
from typing import IO

# ─── ANSI 颜色码 ───

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"

# 前景色
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"
_MAGENTA = "\033[35m"
_CYAN = "\033[36m"
_GRAY = "\033[90m"
_BRIGHT_GREEN = "\033[92m"
_BRIGHT_YELLOW = "\033[93m"
_BRIGHT_CYAN = "\033[96m"

# ─── Windows VT 支持 ───

_vt_enabled = False


def _enable_windows_vt() -> None:
    """在 Windows 10+ 上启用 ANSI VT 处理。"""
    global _vt_enabled
    if _vt_enabled or os.name != "nt":
        _vt_enabled = True
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        for handle_fd in (-12, -11):  # stderr, stdout
            handle = kernel32.GetStdHandle(handle_fd)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        _vt_enabled = True
    except Exception:
        _vt_enabled = False


# ─── TTY 检测 ───

def _is_tty(stream: IO[str] | None = None) -> bool:
    """检测输出流是否为 TTY（终端）。"""
    stream = stream or sys.stdout
    return hasattr(stream, "isatty") and stream.isatty()


# 是否使用彩色输出
_use_color: bool | None = None


def should_use_color(stream: IO[str] | None = None) -> bool:
    """判断是否应该使用彩色输出。

    首次调用时检测：TTY 且 VT 已启用（或非 Windows）。
    可通过 set_color_enabled() 强制覆盖。
    """
    global _use_color
    if _use_color is not None:
        return _use_color
    if not _is_tty(stream):
        _use_color = False
        return False
    _enable_windows_vt()
    _use_color = _vt_enabled
    return _use_color


def set_color_enabled(enabled: bool) -> None:
    """强制设置彩色输出开关（用于测试或 --no-color 参数）。"""
    global _use_color
    _use_color = enabled


def colorize(text: str, color: str) -> str:
    """用 ANSI 颜色包裹文本。非彩色模式返回原文。"""
    if not should_use_color():
        return text
    return f"{color}{text}{_RESET}"


def bold(text: str) -> str:
    return colorize(text, _BOLD)


def dim(text: str) -> str:
    return colorize(text, _DIM)


# ─── 角色配色 ───

_ROLE_COLORS: dict[str, str] = {
    "planner": _BLUE,
    "coder": _GREEN,
    "reviewer": _YELLOW,
    "researcher": _MAGENTA,
    "assistant": _CYAN,
}


def role_color(role: str) -> str:
    """获取角色对应的 ANSI 颜色码。"""
    return _ROLE_COLORS.get(role, _CYAN)


def role_label(role: str, name: str) -> str:
    """格式化角色标签，如 [蓝色]planner[/蓝色]。"""
    return colorize(f"[{role}]", role_color(role)) + f" {name}"


# ─── 阶段配色 ───

_PHASE_CONFIG: dict[str, tuple[str, str]] = {
    # (颜色, 图标)
    "init": (_GRAY, "○"),
    "planning": (_BLUE, "📋"),
    "plan_review": (_CYAN, "⏸"),
    "coding": (_GREEN, "✎"),
    "code_review": (_YELLOW, "⏸"),
    "reviewing": (_YELLOW, "🔍"),
    "feedback": (_MAGENTA, "↻"),
    "completed": (_BRIGHT_GREEN, "✓"),
    "error": (_RED, "✗"),
    "ready": (_GRAY, "○"),
    "thinking": (_CYAN, "…"),
}


def phase_icon(phase: str) -> str:
    """获取阶段对应的图标。"""
    return _PHASE_CONFIG.get(phase, (_GRAY, "○"))[1]


def phase_color(phase: str) -> str:
    """获取阶段对应的颜色码。"""
    return _PHASE_CONFIG.get(phase, (_GRAY, "○"))[0]


def format_phase_status(phase: str, detail: str) -> str:
    """格式化阶段状态行。"""
    icon = phase_icon(phase)
    color = phase_color(phase)
    colored_phase = colorize(f"{icon} {phase}", color)
    return f"  {colored_phase} {detail}"


# ─── 进度条 ───

def progress_bar(completed: int, total: int, width: int = 20) -> str:
    """渲染文本进度条。

    示例: [████████░░░░░░░░░░░░] 2/5
    """
    if total <= 0:
        return f"[{'?' * width}] 0/0"
    filled = int(width * completed / total)
    bar = "█" * filled + "░" * (width - filled)
    pct = int(100 * completed / total)
    if should_use_color():
        colored_bar = colorize(bar[:filled], _GREEN) + colorize(bar[filled:], _GRAY)
    else:
        colored_bar = bar
    return f"[{colored_bar}] {completed}/{total} ({pct}%)"


# ─── 分隔线 ───

def separator(char: str = "=", length: int = 60) -> str:
    """生成分隔线。"""
    return char * length


def banner(title: str, char: str = "=", length: int = 60) -> str:
    """生成标题横幅。"""
    line = char * length
    center = f"  {title}  "
    pad = (length - len(center)) // 2
    if pad < 0:
        pad = 0
    center_line = " " * pad + center
    return f"{line}\n{colorize(center_line, _BOLD)}\n{line}"


def phase_banner(phase: str, detail: str = "") -> str:
    """生成阶段切换横幅。"""
    icon = phase_icon(phase)
    color = phase_color(phase)
    line = "─" * 50
    title = f"  {icon} {phase.upper()}"
    if detail:
        title += f" — {detail}"
    return colorize(line, color) + "\n" + colorize(title, color) + "\n" + colorize(line, color)


# ─── 审查结果格式化 ───

_SEVERITY_CONFIG: dict[str, tuple[str, str]] = {
    "blocker": (_RED, "⛔"),
    "warning": (_YELLOW, "⚠"),
    "info": (_GRAY, "ℹ"),
}


def severity_icon(severity: str) -> str:
    return _SEVERITY_CONFIG.get(severity, (_GRAY, "ℹ"))[1]


def severity_color(severity: str) -> str:
    return _SEVERITY_CONFIG.get(severity, _GRAY)[0]


def format_verdict(verdict: str) -> str:
    """格式化审查判定结果。"""
    if verdict == "approved":
        return colorize("✓ APPROVED", _BRIGHT_GREEN)
    elif verdict == "needs_changes":
        return colorize("⚠ NEEDS CHANGES", _YELLOW)
    elif verdict == "rejected":
        return colorize("✗ REJECTED", _RED)
    return verdict


# ─── Token 使用 ───

def format_token_usage(input_tokens: int, output_tokens: int) -> str:
    """格式化 token 使用统计。"""
    total = input_tokens + output_tokens
    parts = [
        f"{input_tokens:,} in",
        f"{output_tokens:,} out",
        f"{total:,} total",
    ]
    return " / ".join(parts)


# ─── 工具调用格式化 ───

def format_tool_call_start(name: str, args: dict | None = None, num: int = 0) -> str:
    """格式化工具调用开始。"""
    icon = colorize("🔧", _GRAY)
    tool_name = colorize(name, _BRIGHT_CYAN)
    num_str = dim(f"#{num}") if num > 0 else ""
    detail = ""
    if args:
        # 只显示关键参数，截断过长的值
        short_args = {}
        for k, v in list(args.items())[:3]:
            sv = str(v)
            if len(sv) > 50:
                sv = sv[:50] + "..."
            short_args[k] = sv
        detail = dim(f"({short_args})") if short_args else ""
    parts = [f"  {icon}", num_str, tool_name, detail]
    return " ".join(p for p in parts if p)


def format_tool_call_result(name: str, success: bool) -> str:
    """格式化工具调用结果。"""
    if success:
        return f"  {colorize('✓', _GREEN)} {dim(name)} ok"
    else:
        return f"  {colorize('✗', _RED)} {colorize(name, _RED)} failed"


# ─── 计时器 ───

class Timer:
    """简单计时器，用于显示阶段耗时。"""

    def __init__(self) -> None:
        self._start: float = 0.0
        self._end: float = 0.0

    def start(self) -> None:
        import time
        self._start = time.time()

    def stop(self) -> None:
        import time
        self._end = time.time()

    @property
    def elapsed(self) -> float:
        """已用时间（秒）。"""
        import time
        end = self._end or time.time()
        return end - self._start

    def elapsed_str(self) -> str:
        """格式化耗时。"""
        sec = self.elapsed
        if sec < 60:
            return f"{sec:.1f}s"
        minutes = int(sec // 60)
        seconds = sec % 60
        return f"{minutes}m{seconds:.0f}s"


# ─── Spinner 动画 ───

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class Spinner:
    """终端旋转动画，用于 agent 思考时的视觉反馈。

    使用方式::

        spinner = Spinner("思考中")
        spinner.start()
        # ... 异步操作 ...
        spinner.stop()

    在非 TTY 环境下静默无操作。
    """

    def __init__(self, label: str = "") -> None:
        self._label = label
        self._frame_idx = 0
        self._running = False
        self._thread = None

    def start(self) -> None:
        """启动 spinner 后台线程。"""
        if not should_use_color() or self._running:
            return
        self._running = True
        import threading
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def _spin(self) -> None:
        import time
        while self._running:
            frame = _SPINNER_FRAMES[self._frame_idx % len(_SPINNER_FRAMES)]
            sys.stdout.write(f"\r  {colorize(frame, _CYAN)} {dim(self._label)}")
            sys.stdout.flush()
            self._frame_idx += 1
            time.sleep(0.08)

    def stop(self) -> None:
        """停止 spinner，清除行。"""
        if not self._running:
            return
        self._running = False
        if self._thread:
            self._thread.join(timeout=0.2)
            self._thread = None
        # 清除 spinner 行
        sys.stdout.write("\r" + " " * (len(self._label) + 6) + "\r")
        sys.stdout.flush()

    def update(self, label: str) -> None:
        """更新 spinner 标签。"""
        self._label = label


# ─── 彩色 Diff 格式化 ───

def format_diff(diff_text: str, max_lines: int = 50) -> str:
    """将 unified diff 文本格式化为彩色输出。

    红色表示删除行（-），绿色表示新增行（+），灰色表示上下文行（空格）。
    文件头（--- / +++）用青色高亮。

    Args:
        diff_text: unified diff 格式文本
        max_lines: 最多显示的行数（防止输出过长）

    Returns:
        彩色格式化后的 diff 字符串
    """
    if not diff_text:
        return ""

    lines = diff_text.split("\n")
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True
    else:
        truncated = False

    formatted = []
    for line in lines:
        if line.startswith("---") or line.startswith("+++"):
            formatted.append(colorize(line, _BRIGHT_CYAN))
        elif line.startswith("@@"):
            formatted.append(colorize(line, _MAGENTA))
        elif line.startswith("-"):
            formatted.append(colorize(line, _RED))
        elif line.startswith("+"):
            formatted.append(colorize(line, _GREEN))
        else:
            formatted.append(dim(line))

    result = "\n".join(formatted)
    if truncated:
        result += f"\n{dim('...(diff 已截断)')}"
    return result


def format_file_change(file_path: str, action: str) -> str:
    """格式化单文件变更摘要行。

    Args:
        file_path: 文件路径
        action: "create" | "modify" | "delete"

    Returns:
        彩色格式化的变更摘要
    """
    action_config = {
        "create": (_GREEN, "✦ 新建"),
        "modify": (_YELLOW, "✎ 修改"),
        "delete": (_RED, "✗ 删除"),
    }
    color, label = action_config.get(action, (_GRAY, action))
    return f"  {colorize(label, color)} {colorize(file_path, color)}"
