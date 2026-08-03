"""CLI 显示工具——ANSI 彩色输出、进度条、阶段横幅。

支持 Windows 10+（自动启用 VT 处理）和 Unix 终端。
非 TTY 输出时自动降级为纯文本（无 ANSI 转义码）。
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
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
        # 切换控制台输出代码页为 UTF-8，避免 emoji/箱线字符在 GBK 下崩溃
        kernel32.SetConsoleOutputCP(65001)
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass
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
    pad = (length - display_width(center)) // 2
    if pad < 0:
        pad = 0
    center_line = " " * pad + center
    return f"{line}\n{colorize(center_line, _BOLD)}\n{line}"


def phase_banner(phase: str, detail: str = "") -> str:
    """生成阶段切换横幅。"""
    icon = phase_icon(phase)
    color = phase_color(phase)
    title = f"{icon} {phase}"
    if detail:
        title += f" · {detail}"
    line = f"  ── {title} ──"
    return colorize(line, color)


# ─── 面板 / 对齐 ───


def display_width(text: str) -> int:
    """估算文本在终端中的显示宽度。

    CJK 全角字符按 2 列计算，ANSI 转义序列不计入宽度。
    """
    plain = re.sub(r"\033\[[0-9;]*m", "", text)
    width = 0
    for ch in plain:
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def pad_text(text: str, width: int) -> str:
    """按显示宽度补齐空格（支持 CJK 与 ANSI 混排）。"""
    return text + " " * max(0, width - display_width(text))


_ANSI_CODE_RE = re.compile(r"\033\[[0-9;]*m")


def _split_ansi(text: str) -> list[tuple[str, bool]]:
    """将文本拆分为 (片段, 是否为 ANSI 码) 的令牌序列。"""
    tokens: list[tuple[str, bool]] = []
    pos = 0
    for m in _ANSI_CODE_RE.finditer(text):
        if m.start() > pos:
            tokens.append((text[pos:m.start()], False))
        tokens.append((m.group(0), True))
        pos = m.end()
    if pos < len(text):
        tokens.append((text[pos:], False))
    return tokens


def wrap_text(text: str, width: int) -> list[str]:
    """按显示宽度折行，尽量在空格处断行。

    支持 ANSI 颜色码混排：折行处自动闭合颜色并在下一行恢复，
    避免长内容把面板边框撑破或颜色串行。
    """
    if display_width(text) <= width:
        return [text]

    lines: list[str] = []
    current: list[str] = []
    current_w = 0
    open_codes: list[str] = []
    prev_plain: str = ""
    current_ansi = False

    def _break_line() -> None:
        nonlocal current, current_w, prev_plain, current_ansi
        if current:
            # 闭合行尾未关闭的颜色码，避免颜色串到下一行
            lines.append("".join(current) + (_RESET if current_ansi else ""))
        # 下一行恢复本行行尾仍打开的颜色
        current = list(open_codes)
        current_w = 0
        prev_plain = ""
        current_ansi = bool(open_codes)

    for chunk, is_ansi in _split_ansi(text):
        if is_ansi:
            current.append(chunk)
            current_ansi = True
            if chunk == _RESET:
                open_codes.clear()
            else:
                open_codes.append(chunk)
            continue
        for ch in chunk:
            w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
            if ch == " ":
                # 行首或连续空格省略，保持原有“空格分词”语义
                if current_w == 0 or prev_plain == " ":
                    continue
                if current_w + 1 > width:
                    _break_line()
                    continue
                current.append(ch)
                current_w += 1
                prev_plain = ch
                continue
            if current_w + w > width and current_w > 0:
                _break_line()
            current.append(ch)
            current_w += w
            prev_plain = ch

    if current_w > 0:
        lines.append("".join(current) + (_RESET if current_ansi else ""))
    return lines or [""]


def _hard_break(text: str, width: int) -> list[str]:
    """对超长单词/CJK 连续文本按显示宽度硬折行。"""
    if display_width(text) <= width:
        return [text]
    lines: list[str] = []
    current = ""
    current_w = 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if current and current_w + w > width:
            lines.append(current)
            current = ""
            current_w = 0
        current += ch
        current_w += w
    if current:
        lines.append(current)
    return lines


def panel(title: str = "", lines: list[str] | None = None, width: int = 66) -> str:
    """生成圆角卡片式面板。

    Args:
        title: 面板标题（居中显示在顶边框）
        lines: 面板内容行（自动按显示宽度折行）
        width: 面板总宽度（列数）
    """
    lines = lines or []
    if title:
        title_str = f" {title} "
        fill = max(2, width - 3 - display_width(title_str))
        top = "╭─" + title_str + "─" * fill + "╮"
    else:
        top = "╭" + "─" * (width - 2) + "╮"
    content_w = width - 4
    body = []
    for raw in lines:
        for line in wrap_text(raw, content_w):
            body.append("│ " + pad_text(line, content_w) + " │")
    bottom = "╰" + "─" * (width - 2) + "╯"
    return "\n".join([top, *body, bottom])


def format_agent_header(role: str, name: str) -> str:
    """Agent 启动行：● role name。"""
    dot = colorize("●", role_color(role))
    tag = colorize(role, role_color(role))
    return f"  {dot} {tag}  {bold(name)}"


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


def format_elapsed(seconds: float) -> str:
    """格式化耗时（秒 → 人类可读）。"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    sec = seconds % 60
    return f"{minutes}m{sec:.0f}s"


# ─── 工具调用格式化 ───


_TOOL_ARG_PRIORITY = (
    "path", "file", "command", "pattern", "query",
    "dir", "url", "name", "agent_id", "task", "work_dir",
)


def _shorten_arg(value, limit: int = 40) -> str:
    text = str(value)
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _summarize_tool_args(args: dict | None) -> str:
    """提取工具调用最关键的参数摘要，如 path=src/main.py。"""
    if not args:
        return ""
    short = {k: v for k, v in args.items() if k != "result"}
    if not short:
        return ""
    parts: list[str] = []
    for key in _TOOL_ARG_PRIORITY:
        if key in short:
            parts.append(f"{key}={_shorten_arg(short[key])}")
            if len(parts) >= 2:
                break
    if not parts:
        for key, value in list(short.items())[:2]:
            parts.append(f"{key}={_shorten_arg(value)}")
    return " ".join(parts)


def format_tool_call_start(name: str, args: dict | None = None, num: int = 0) -> str:
    """格式化工具调用开始。"""
    parts = [f"  {colorize('⏺', _GRAY)}", colorize(name, _BRIGHT_CYAN)]
    if num > 0:
        parts.append(dim(f"#{num}"))
    detail = _summarize_tool_args(args)
    if detail:
        parts.append(dim(detail))
    return " ".join(parts)


def format_tool_call_result(
    name: str,
    success: bool,
    elapsed: str | None = None,
    summary: str | None = None,
) -> str:
    """格式化工具调用结果。"""
    if success:
        head = f"{colorize('✓', _GREEN)} {colorize(name, _BRIGHT_CYAN)} {dim('ok')}"
    else:
        head = f"{colorize('✗', _RED)} {colorize(name, _RED)} {colorize('failed', _RED)}"
    parts = [f"  {head}"]
    if summary:
        parts.append(dim(_shorten_arg(summary, limit=60)))
    if elapsed:
        parts.append(dim(elapsed))
    return " · ".join(parts)


def truncate_ansi(text: str, width: int) -> str:
    """按显示宽度截断文本（支持 ANSI 颜色码），超出部分省略并闭合颜色。

    用于保证工具行等动态刷新的行始终只占一行，避免换行后覆盖错乱。
    """
    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text

    out: list[str] = []
    out_w = 0
    open_codes: list[str] = []
    i, n = 0, len(text)
    while i < n and out_w < width:
        if text[i] == "\033":
            j = text.find("m", i)
            if j == -1:
                break
            code = text[i:j + 1]
            out.append(code)
            if code == _RESET:
                open_codes.clear()
            else:
                open_codes.append(code)
            i = j + 1
            continue
        ch = text[i]
        chw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if out_w + chw > width:
            break
        out.append(ch)
        out_w += chw
        i += 1

    result = "".join(out)
    if open_codes:
        result += _RESET
    if i < n and display_width(result) + 1 <= width:
        result += "…"
    return result


def summarize_tool_result(result: str, max_chars: int = 48) -> str:
    """从工具结果中提取一行紧凑摘要。

    多行结果显示首行 + 总行数，避免把整个文件列表/树贴到工具结果行里。
    """
    if not result or not result.strip():
        return ""
    lines = [ln.strip() for ln in result.splitlines() if ln.strip()]
    first = lines[0]
    if len(lines) > 1:
        tail = f"（共 {len(lines)} 行）"
        budget = max(12, max_chars - len(tail))
        snippet = first if len(first) <= budget else first[:budget] + "…"
        return snippet + tail
    return first if len(first) <= max_chars else first[:max_chars] + "…"


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
        return format_elapsed(self.elapsed)


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


# ─── Markdown 流式渲染 ───

_MD_CODE_FENCE_RE = re.compile(r"^```([\w+-]*)\s*$")
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_MD_HR_RE = re.compile(r"^\s*(---|\*\*\*|___)\s*$")
_MD_QUOTE_RE = re.compile(r"^>\s?(.*)$")
_MD_LIST_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")


def _render_inline(text: str) -> str:
    """渲染行内 Markdown：`code` 与 **bold**。"""
    text = _INLINE_CODE_RE.sub(lambda m: colorize(m.group(1), _CYAN), text)
    text = _BOLD_RE.sub(lambda m: colorize(m.group(1), _BOLD), text)
    return text


def _render_md_line(line: str) -> str:
    """渲染单行 Markdown 文本。"""
    if not line.strip():
        return ""
    if _MD_HR_RE.match(line):
        return dim("─" * 40) + "\n"
    m = _MD_HEADING_RE.match(line)
    if m:
        level = len(m.group(1))
        color = _BRIGHT_CYAN if level <= 2 else _CYAN
        return colorize(f"{'#' * level} {_render_inline(m.group(2))}", color) + "\n"
    m = _MD_QUOTE_RE.match(line)
    if m:
        return dim("│ ") + _render_inline(m.group(1)) + "\n"
    m = _MD_LIST_RE.match(line)
    if m:
        indent = m.group(1)
        return indent + colorize("•", _GRAY) + " " + _render_inline(m.group(2)) + "\n"
    return _render_inline(line) + "\n"


def _code_block_open(lang: str) -> str:
    return dim(f"```{lang}") + "\n"


def _code_block_line(line: str) -> str:
    if should_use_color():
        return colorize("│", _GRAY) + " " + line + "\n"
    return "  " + line + "\n"


def _code_block_close() -> str:
    return dim("```") + "\n"


class StreamingMarkdownRenderer:
    """增量渲染 Markdown 文本（面向流式 chunk 输出）。

    以行为单位渲染：完整行立即输出；未完成的行缓冲到 flush()。
    支持代码块、标题、引用、列表、行内 code 与 **bold**。
    """

    def __init__(self) -> None:
        self._buf = ""
        self._in_code = False

    def feed(self, chunk: str) -> str:
        """接收一段文本，返回可打印的已渲染部分。"""
        if not chunk:
            return ""
        self._buf += chunk
        out: list[str] = []
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            out.append(self._render_line(line))
        return "".join(out)

    def flush(self) -> str:
        """输出缓冲中未完成的行。"""
        if not self._buf:
            return ""
        line, self._buf = self._buf, ""
        return self._render_line(line)

    def _render_line(self, line: str) -> str:
        stripped = line.strip()
        if self._in_code:
            if _MD_CODE_FENCE_RE.match(stripped):
                self._in_code = False
                return _code_block_close()
            return _code_block_line(line)
        m = _MD_CODE_FENCE_RE.match(stripped)
        if m:
            self._in_code = True
            return _code_block_open(m.group(1))
        return _render_md_line(line)


def render_markdown(text: str) -> str:
    """渲染完整 Markdown 文本（非流式场景使用）。"""
    renderer = StreamingMarkdownRenderer()
    return renderer.feed(text) + renderer.flush()


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
            styled = colorize(line, _BRIGHT_CYAN)
        elif line.startswith("@@"):
            styled = colorize(line, _MAGENTA)
        elif line.startswith("-"):
            styled = colorize(line, _RED)
        elif line.startswith("+"):
            styled = colorize(line, _GREEN)
        else:
            styled = dim(line)
        if should_use_color():
            formatted.append(colorize("│", _GRAY) + " " + styled)
        else:
            formatted.append("  " + styled)

    result = "\n".join(formatted)
    if truncated:
        marker = dim("...(diff 已截断)")
        result += f"\n{colorize('│', _GRAY) + ' ' + marker if should_use_color() else '  ' + marker}"
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
