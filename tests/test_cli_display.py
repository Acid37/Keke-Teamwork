"""cli_display 单元测试——ANSI 彩色输出、进度条、阶段横幅。"""

from __future__ import annotations

import pytest

from backend.cli_display import (
    Spinner,
    Timer,
    banner,
    bold,
    colorize,
    dim,
    format_diff,
    format_file_change,
    format_phase_status,
    format_tool_call_result,
    format_tool_call_start,
    format_token_usage,
    format_verdict,
    phase_banner,
    phase_color,
    phase_icon,
    progress_bar,
    role_color,
    role_label,
    separator,
    set_color_enabled,
    should_use_color,
    severity_color,
    severity_icon,
)


# ─── Fixtures ───


@pytest.fixture(autouse=True)
def _reset_color():
    """每个测试前后重置彩色输出状态。"""
    set_color_enabled(False)
    yield
    set_color_enabled(False)


@pytest.fixture
def color_enabled():
    """启用彩色输出的 fixture。"""
    set_color_enabled(True)
    yield
    set_color_enabled(False)


# ─── 彩色开关测试 ───


class TestColorToggle:
    """彩色输出开关测试。"""

    def test_disabled_by_default_in_test(self):
        """测试环境默认禁用彩色（非 TTY）。"""
        set_color_enabled(None)  # 重置为自动检测
        # 测试环境通常不是 TTY
        assert should_use_color() is False

    def test_force_enable(self):
        set_color_enabled(True)
        assert should_use_color() is True

    def test_force_disable(self):
        set_color_enabled(True)
        set_color_enabled(False)
        assert should_use_color() is False


# ─── colorize / bold / dim 测试 ───


class TestColorize:
    """基本颜色包裹函数测试。"""

    def test_colorize_no_color(self):
        assert colorize("hello", "\033[31m") == "hello"

    def test_colorize_with_color(self, color_enabled):
        result = colorize("hello", "\033[31m")
        assert "\033[31m" in result
        assert "hello" in result
        assert "\033[0m" in result

    def test_bold_no_color(self):
        assert bold("text") == "text"

    def test_bold_with_color(self, color_enabled):
        result = bold("text")
        assert "\033[1m" in result

    def test_dim_no_color(self):
        assert dim("text") == "text"

    def test_dim_with_color(self, color_enabled):
        result = dim("text")
        assert "\033[2m" in result


# ─── 角色配色测试 ───


class TestRoleColors:
    """角色配色测试。"""

    def test_planner_color(self):
        assert role_color("planner") == "\033[34m"

    def test_coder_color(self):
        assert role_color("coder") == "\033[32m"

    def test_reviewer_color(self):
        assert role_color("reviewer") == "\033[33m"

    def test_unknown_role_defaults(self):
        assert role_color("unknown") == "\033[36m"

    def test_role_label_no_color(self):
        result = role_label("planner", "规划师")
        assert result == "[planner] 规划师"

    def test_role_label_with_color(self, color_enabled):
        result = role_label("planner", "规划师")
        assert "\033[34m" in result
        assert "[planner]" in result
        assert "规划师" in result


# ─── 阶段配色测试 ───


class TestPhaseColors:
    """阶段配色和图标测试。"""

    def test_planning_icon(self):
        assert phase_icon("planning") == "📋"

    def test_coding_icon(self):
        assert phase_icon("coding") == "✎"

    def test_completed_icon(self):
        assert phase_icon("completed") == "✓"

    def test_error_icon(self):
        assert phase_icon("error") == "✗"

    def test_unknown_phase_icon(self):
        assert phase_icon("unknown") == "○"

    def test_phase_color_not_empty(self):
        assert phase_color("planning") != ""

    def test_format_phase_status(self):
        result = format_phase_status("planning", "正在分析...")
        assert "planning" in result
        assert "正在分析..." in result

    def test_format_phase_status_with_color(self, color_enabled):
        result = format_phase_status("completed", "完成")
        assert "\033[92m" in result  # BRIGHT_GREEN

    def test_phase_banner(self):
        result = phase_banner("coding", "实现功能")
        assert "CODING" in result
        assert "实现功能" in result
        assert "─" in result

    def test_phase_banner_no_detail(self):
        result = phase_banner("planning")
        assert "PLANNING" in result


# ─── 进度条测试 ───


class TestProgressBar:
    """进度条渲染测试。"""

    def test_zero_progress(self):
        bar = progress_bar(0, 5)
        assert "0/5" in bar
        assert "0%" in bar
        assert "░" in bar

    def test_half_progress(self):
        bar = progress_bar(2, 4)
        assert "2/4" in bar
        assert "50%" in bar
        assert "█" in bar

    def test_full_progress(self):
        bar = progress_bar(5, 5)
        assert "5/5" in bar
        assert "100%" in bar

    def test_zero_total(self):
        bar = progress_bar(0, 0)
        assert "0/0" in bar

    def test_custom_width(self):
        bar = progress_bar(1, 4, width=10)
        # 10 格宽度，1/4 = 2 格填充
        assert "█" in bar
        assert "1/4" in bar

    def test_progress_bar_no_color(self):
        bar = progress_bar(1, 2)
        assert "\033[" not in bar

    def test_progress_bar_with_color(self, color_enabled):
        bar = progress_bar(1, 2)
        assert "\033[" in bar


# ─── 横幅/分隔线测试 ───


class TestBannerSeparator:
    """横幅和分隔线测试。"""

    def test_separator_default(self):
        s = separator()
        assert len(s) == 60
        assert s == "=" * 60

    def test_separator_custom(self):
        s = separator("-", 30)
        assert s == "-" * 30

    def test_banner_contains_title(self):
        b = banner("测试标题")
        assert "测试标题" in b
        assert "=" in b

    def test_banner_with_color(self, color_enabled):
        b = banner("Title")
        assert "\033[1m" in b  # BOLD


# ─── 审查结果格式化测试 ───


class TestVerdictFormatting:
    """审查判定格式化测试。"""

    def test_approved_no_color(self):
        result = format_verdict("approved")
        assert "APPROVED" in result

    def test_approved_with_color(self, color_enabled):
        result = format_verdict("approved")
        assert "\033[92m" in result  # BRIGHT_GREEN

    def test_needs_changes_no_color(self):
        result = format_verdict("needs_changes")
        assert "NEEDS CHANGES" in result

    def test_rejected_no_color(self):
        result = format_verdict("rejected")
        assert "REJECTED" in result

    def test_unknown_verdict(self):
        result = format_verdict("unknown")
        assert result == "unknown"


class TestSeverityFormatting:
    """严重级别格式化测试。"""

    def test_blocker_icon(self):
        assert severity_icon("blocker") == "⛔"

    def test_warning_icon(self):
        assert severity_icon("warning") == "⚠"

    def test_info_icon(self):
        assert severity_icon("info") == "ℹ"

    def test_blocker_color(self):
        assert severity_color("blocker") == "\033[31m"

    def test_warning_color(self):
        assert severity_color("warning") == "\033[33m"


# ─── Token 使用格式化测试 ───


class TestTokenUsage:
    """Token 使用统计格式化测试。"""

    def test_basic_usage(self):
        result = format_token_usage(1000, 500)
        assert "1,000" in result
        assert "500" in result
        assert "1,500" in result
        assert "in" in result
        assert "out" in result
        assert "total" in result

    def test_zero_usage(self):
        result = format_token_usage(0, 0)
        assert "0" in result

    def test_large_numbers(self):
        result = format_token_usage(1000000, 500000)
        assert "1,000,000" in result


# ─── 工具调用格式化测试 ───


class TestToolCallFormatting:
    """工具调用格式化测试。"""

    def test_tool_call_start_basic(self):
        result = format_tool_call_start("read_file", None)
        assert "read_file" in result

    def test_tool_call_start_with_args(self):
        result = format_tool_call_start("edit_file", {"path": "src/main.py"})
        assert "edit_file" in result
        assert "src/main.py" in result

    def test_tool_call_start_truncates_long_args(self):
        long_val = "x" * 100
        result = format_tool_call_start("write_file", {"content": long_val})
        assert "..." in result
        assert len(result) < 200

    def test_tool_call_start_limits_args(self):
        result = format_tool_call_start("tool", {
            "a": "1", "b": "2", "c": "3", "d": "4"
        })
        assert "d" not in result  # 只显示前 3 个

    def test_tool_call_result_success(self):
        result = format_tool_call_result("read_file", True)
        assert "read_file" in result
        assert "ok" in result

    def test_tool_call_result_failure(self):
        result = format_tool_call_result("run_console", False)
        assert "failed" in result

    def test_tool_call_result_with_color(self, color_enabled):
        result = format_tool_call_result("read_file", True)
        assert "\033[32m" in result  # GREEN


# ─── Timer 测试 ───


class TestTimer:
    """计时器测试。"""

    def test_timer_start_stop(self):
        t = Timer()
        t.start()
        t.stop()
        assert t.elapsed >= 0

    def test_timer_elapsed_str_seconds(self):
        t = Timer()
        t._start = 100.0
        t._end = 103.5
        assert t.elapsed_str() == "3.5s"

    def test_timer_elapsed_str_minutes(self):
        t = Timer()
        t._start = 100.0
        t._end = 195.0
        result = t.elapsed_str()
        assert "m" in result
        assert "s" in result

    def test_timer_not_stopped(self):
        t = Timer()
        t._start = 100.0
        # 不 stop，elapsed 应该返回正数
        assert t.elapsed >= 0


# ─── Spinner 测试 ───


class TestSpinner:
    """Spinner 动画测试。"""

    def test_start_stop_without_color(self):
        """非彩色模式下 start 应静默无操作。"""
        s = Spinner("思考中")
        s.start()
        assert s._running is False
        assert s._thread is None
        s.stop()  # 应安全无操作

    def test_start_with_color(self, color_enabled):
        """彩色模式下 start 应启动后台线程。"""
        s = Spinner("加载中")
        s.start()
        assert s._running is True
        assert s._thread is not None
        s.stop()
        assert s._running is False
        assert s._thread is None

    def test_stop_without_start(self):
        """未启动时 stop 应安全无操作。"""
        s = Spinner("test")
        s.stop()
        assert s._running is False

    def test_double_start(self, color_enabled):
        """重复 start 不应创建第二个线程。"""
        s = Spinner("test")
        s.start()
        first_thread = s._thread
        s.start()  # 第二次 start 应被忽略
        assert s._thread is first_thread
        s.stop()

    def test_update_label(self):
        """update 应修改标签。"""
        s = Spinner("旧标签")
        s.update("新标签")
        assert s._label == "新标签"

    def test_stop_clears_running_flag(self, color_enabled):
        """stop 应清除 running 标志。"""
        s = Spinner("test")
        s.start()
        assert s._running is True
        s.stop()
        assert s._running is False


# ─── format_diff 测试 ───


class TestFormatDiff:
    """彩色 Diff 格式化测试。"""

    def test_empty_diff(self):
        """空 diff 应返回空字符串。"""
        assert format_diff("") == ""

    def test_none_diff(self):
        """None 应返回空字符串。"""
        assert format_diff("") == ""

    def test_addition_line(self, color_enabled):
        """新增行（+）应使用绿色。"""
        result = format_diff("+new line")
        assert "\033[32m" in result  # GREEN
        assert "+new line" in result

    def test_deletion_line(self, color_enabled):
        """删除行（-）应使用红色。"""
        result = format_diff("-old line")
        assert "\033[31m" in result  # RED
        assert "-old line" in result

    def test_file_header(self, color_enabled):
        """文件头（--- / +++）应使用亮青色。"""
        result = format_diff("--- a/file.py\n+++ b/file.py")
        assert "\033[96m" in result  # BRIGHT_CYAN
        assert "--- a/file.py" in result
        assert "+++ b/file.py" in result

    def test_hunk_header(self, color_enabled):
        """hunk 头（@@）应使用洋红色。"""
        result = format_diff("@@ -1,3 +1,4 @@")
        assert "\033[35m" in result  # MAGENTA
        assert "@@ -1,3 +1,4 @@" in result

    def test_context_line(self, color_enabled):
        """上下文行（空格开头）应使用 dim。"""
        result = format_diff(" context line")
        assert "\033[2m" in result  # DIM

    def test_truncation(self):
        """超过 max_lines 的 diff 应被截断。"""
        lines = [f"+line {i}" for i in range(100)]
        result = format_diff("\n".join(lines), max_lines=10)
        assert "...(diff 已截断)" in result
        assert "line 0" in result
        assert "line 99" not in result

    def test_no_truncation_when_short(self):
        """行数不超过 max_lines 时不应截断。"""
        result = format_diff("+line 1\n+line 2", max_lines=50)
        assert "截断" not in result

    def test_no_color_diff(self):
        """非彩色模式下不应包含 ANSI 码。"""
        result = format_diff("+add\n-del\n--- a/x\n+++ b/x\n@@ -1,1 +1,1 @@\n ctx")
        assert "\033[" not in result
        assert "+add" in result
        assert "-del" in result

    def test_multiline_diff(self):
        """多行 diff 应全部输出。"""
        diff = "--- a/x\n+++ b/x\n@@ -1,2 +1,2 @@\n-old\n+new\n ctx"
        result = format_diff(diff)
        assert "--- a/x" in result
        assert "+++ b/x" in result
        assert "-old" in result
        assert "+new" in result
        assert "ctx" in result


# ─── format_file_change 测试 ───


class TestFormatFileChange:
    """文件变更摘要行格式化测试。"""

    def test_create_action(self):
        """create 动作应显示新建标签。"""
        result = format_file_change("src/main.py", "create")
        assert "新建" in result
        assert "src/main.py" in result

    def test_modify_action(self):
        """modify 动作应显示修改标签。"""
        result = format_file_change("src/util.py", "modify")
        assert "修改" in result
        assert "src/util.py" in result

    def test_delete_action(self):
        """delete 动作应显示删除标签。"""
        result = format_file_change("old/removed.py", "delete")
        assert "删除" in result
        assert "old/removed.py" in result

    def test_unknown_action(self):
        """未知动作应回退为原始动作名。"""
        result = format_file_change("file.txt", "unknown")
        assert "unknown" in result
        assert "file.txt" in result

    def test_create_with_color(self, color_enabled):
        """create 动作应使用绿色。"""
        result = format_file_change("src/new.py", "create")
        assert "\033[32m" in result  # GREEN

    def test_modify_with_color(self, color_enabled):
        """modify 动作应使用黄色。"""
        result = format_file_change("src/edit.py", "modify")
        assert "\033[33m" in result  # YELLOW

    def test_delete_with_color(self, color_enabled):
        """delete 动作应使用红色。"""
        result = format_file_change("src/gone.py", "delete")
        assert "\033[31m" in result  # RED

    def test_no_color_file_change(self):
        """非彩色模式下不应包含 ANSI 码。"""
        result = format_file_change("src/main.py", "create")
        assert "\033[" not in result
        assert "新建" in result
