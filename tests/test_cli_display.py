"""cli_display 单元测试——ANSI 彩色输出、进度条、阶段横幅。"""

from __future__ import annotations

import pytest

from backend.cli_display import (
    Timer,
    banner,
    bold,
    colorize,
    dim,
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
