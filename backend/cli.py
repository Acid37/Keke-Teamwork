"""CLI 入口——常规任务单 agent 直答，复杂任务由 main 内部委派。

用法::

    # 常规任务：main agent 直答，复杂任务内部委派给专业 agent
    python -m backend.cli "统计目录下的图片数量" --work-dir /path/to/project
    python -m backend.cli "修复 bug" --work-dir . --yolo

    # 列出会话
    python -m backend.cli --list-sessions

    # 交互模式：任意目录输入 keke 唤起，连续任务
    keke

会话状态会在每次交互后自动持久化。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import sys
import threading
import time
from pathlib import Path

from backend.agent_store import AgentStore
from backend.cli_display import (
    StreamingMarkdownRenderer,
    Timer,
    Spinner,
    bold,
    colorize,
    dim,
    display_width,
    format_diff,
    format_agent_header,
    format_elapsed,
    format_file_change,
    format_tool_call_result,
    format_tool_call_start,
    format_token_usage,
    format_verdict,
    panel,
    phase_banner,
    phase_color,
    phase_icon,
    progress_bar,
    render_markdown,
    role_color,
    set_color_enabled,
    should_use_color,
    severity_color,
    severity_icon,
    summarize_tool_result,
    truncate_ansi,
)
from backend.config import AppConfig
from backend.llm.client import LLMClient, LLMClientFactory
from backend.orchestrator import AgentOrchestrator
from backend.safety.permission import PermissionManager
from backend.session import SessionStore
from backend.types import Phase, Session

logger = logging.getLogger(__name__)


# Cache initialized components so interactive mode reuses them across tasks.
_INIT_CACHE: tuple | None = None


# ─── 广播闭包 ───


def _make_console_broadcast():
    """创建一个将工作流事件打印到终端的彩色广播闭包。"""

    # 追踪当前阶段，用于检测阶段切换
    state = {
        "current_phase": "",
        "agent_active": False,
        "tool_call_count": 0,
        "total_tool_calls": 0,
        "timer": Timer(),
        "total_timer": Timer(),
        "spinner": None,
        "renderer": StreamingMarkdownRenderer(),
        "text_rendered": False,
        "last_line_is_tool": False,
        "tool_started_at": 0.0,
        "tool_timer": None,
        "at_line_start": True,
        "agent_name": "",
        "agent_role": "",
    }
    state["total_timer"].start()

    def _stop_tool_timer() -> None:
        """Stop the tool-line elapsed-time refresh thread."""
        timer = state.get("tool_timer")
        if timer is None:
            return
        timer["stop"]()
        thread = timer.get("thread")
        if thread:
            thread.join(timeout=0.2)
        state["tool_timer"] = None

    def _stop_spinner() -> None:
        _stop_tool_timer()
        if state["spinner"]:
            state["spinner"].stop()
            state["spinner"] = None

    def _stream_print(text: str) -> None:
        """流式输出（不换行），并重置工具行覆盖标记。"""
        if not text:
            return
        state["last_line_is_tool"] = False
        sys.stdout.write(text)
        sys.stdout.flush()
        state["at_line_start"] = text.endswith("\n")

    def _block_print(text: str = "") -> None:
        state["last_line_is_tool"] = False
        print(text, flush=True)
        state["at_line_start"] = True

    def _finish_tool_line(text: str) -> None:
        """输出工具调用完成行；若工具行仍是最后一行则原位覆盖。"""
        _stop_tool_timer()
        if state["last_line_is_tool"] and should_use_color():
            sys.stdout.write("\r\033[2K")
        state["last_line_is_tool"] = False
        print(text, flush=True)
        state["at_line_start"] = True

    async def broadcast(event_type: str, payload: dict) -> None:
        if event_type == "agent.status":
            phase = payload.get("phase", "")
            detail = payload.get("detail", "")

            # 只在阶段切换时输出，避免重复状态行刷屏
            if phase and phase != state["current_phase"]:
                _stop_spinner()
                if state["current_phase"] and state["agent_active"]:
                    state["timer"].stop()
                    _block_print(f"  {dim(f'⏱ 阶段耗时 {state['timer'].elapsed_str()}')}")
                state["current_phase"] = phase
                state["timer"] = Timer()
                state["timer"].start()
                _block_print(phase_banner(phase, detail or ""))

        elif event_type == "agent.started":
            name = payload.get("agent_name", "")
            role = payload.get("role", "")
            state["agent_active"] = True
            state["tool_call_count"] = 0
            state["renderer"] = StreamingMarkdownRenderer()
            state["text_rendered"] = False
            state["agent_name"] = name
            state["agent_role"] = role
            _block_print("")
            _block_print(format_agent_header(role, name))
            state["spinner"] = Spinner(f"{name} 思考中...")
            state["spinner"].start()

        elif event_type == "agent.completed":
            name = payload.get("agent_name", "")
            role = payload.get("role", "")
            summary = payload.get("summary", "")
            usage = payload.get("usage", {})
            in_tok = usage.get("input_tokens", 0)
            out_tok = usage.get("output_tokens", 0)
            _stop_spinner()
            _stream_print(state["renderer"].flush())
            state["agent_active"] = False
            state["timer"].stop()

            elapsed = state["timer"].elapsed_str()
            tokens = format_token_usage(in_tok, out_tok)
            tool_count = state["tool_call_count"]
            parts = [
                colorize("✓", role_color(role)),
                bold(name),
                dim(elapsed),
                dim(tokens),
            ]
            tool_info = dim(f"🔧 {tool_count} 次") if tool_count > 0 else ""
            if tool_info:
                parts.append(tool_info)
            _block_print("  " + " · ".join(parts))
            if summary and not state["text_rendered"]:
                _block_print(dim("  摘要:"))
                _block_print(render_markdown(summary).rstrip("\n"))

        elif event_type == "agent.text":
            text = payload.get("text", "")
            is_final = payload.get("is_final", False)
            _stop_spinner()
            if text:
                state["text_rendered"] = True
                if is_final:
                    _stream_print(state["renderer"].feed(text) + state["renderer"].flush())
                else:
                    _stream_print(state["renderer"].feed(text))

        elif event_type == "agent.thinking":
            text = payload.get("text", "")
            if text:
                _stop_spinner()
                _stream_print(dim(text))

        elif event_type == "error":
            msg = payload.get("message", "")
            _stop_spinner()
            _block_print(
                f"\n  {colorize('✗ ERROR', phase_color('error'))} {msg}")

        elif event_type == "tool.call":
            name = payload.get("name", "")
            stage = payload.get("stage", "")
            if stage == "running":
                _stop_spinner()
                state["tool_call_count"] += 1
                state["total_tool_calls"] += 1
                args = payload.get("args", {})
                if isinstance(args, dict):
                    # 过滤掉 result 键
                    args = {k: v for k, v in args.items() if k != "result"}
                args_dict = args if isinstance(args, dict) else None
                num = state["tool_call_count"]
                width = shutil.get_terminal_size((80, 24)).columns
                line = truncate_ansi(
                    format_tool_call_start(name, args_dict, num),
                    max(20, width - 12))
                if should_use_color():
                    # 不换行打印，便于执行期间在同一行原地刷新耗时
                    if not state["at_line_start"]:
                        sys.stdout.write("\n")
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    state["at_line_start"] = False
                else:
                    print(line, flush=True)
                state["last_line_is_tool"] = True
                state["tool_started_at"] = time.time()
                if should_use_color():
                    started_at = state["tool_started_at"]
                    stop = {"stop": False}

                    def _tick() -> None:
                        try:
                            while not stop["stop"]:
                                elapsed = format_elapsed(
                                    time.time() - started_at)
                                tick_line = truncate_ansi(
                                    line + dim(f" {elapsed}"),
                                    max(20, width - 1))
                                sys.stdout.write("\r\033[2K" + tick_line)
                                sys.stdout.flush()
                                time.sleep(0.1)
                        except Exception:
                            pass

                    thread = threading.Thread(target=_tick, daemon=True)
                    thread.start()
                    state["tool_timer"] = {
                        "stop": lambda: stop.__setitem__("stop", True),
                        "thread": thread,
                    }
            elif stage == "completed":
                success = payload.get("success", False)
                elapsed = ""
                if state["tool_started_at"]:
                    elapsed = format_elapsed(time.time() - state["tool_started_at"])
                    state["tool_started_at"] = 0.0
                args = payload.get("args", {})
                result = args.get("result", "") if isinstance(args, dict) else ""
                summary = summarize_tool_result(result) if isinstance(result, str) else ""
                width = shutil.get_terminal_size((80, 24)).columns
                result_line = truncate_ansi(
                    format_tool_call_result(
                        name, bool(success), elapsed=elapsed, summary=summary),
                    max(20, width - 1))
                _finish_tool_line(result_line)

        elif event_type == "files.changed":
            _stop_spinner()
            files = payload.get("files", [])
            combined_diff = payload.get("combined_diff", "")
            if files:
                _block_print("")
                _block_print(
                    f"  {bold('文件变更')} {dim(f'· {len(files)} 个文件')}")
                for f in files:
                    path = f.get("path", "")
                    action = f.get("action", "modify")
                    _block_print(format_file_change(str(path), action))
                _block_print("")
            if combined_diff:
                _block_print(format_diff(combined_diff))
                _block_print("")

    return broadcast


# ─── 工作流交互 ───


def _list_sessions(config: AppConfig) -> int:
    """列出所有会话（面板，按最近活跃排序）。"""
    session_store = SessionStore(config.data_dir)
    sessions = session_store.list_sessions()

    if not sessions:
        print(f"  {dim('还没有会话。')}")
        return 0

    # 按最近活跃时间降序排列
    sessions.sort(key=lambda s: s.get("last_active_at", 0), reverse=True)

    lines: list[str] = []

    for i, s in enumerate(sessions, 1):
        sid = s["session_id"]
        title = s.get("title", "(未命名)")
        phase = s.get("phase", "unknown")
        ts = s.get("last_active_at", 0)
        ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "未知"

        lines.append(
            f"{colorize(f'{i:>2}.', phase_color('planning'))} {bold(title)}")
        lines.append(
            f"      {dim('会话')} {colorize(sid, phase_color('planning'))}"
            f" · {dim('阶段')} {colorize(phase, phase_color(phase))}"
            f" · {dim(ts_str)}")
        lines.append("")

    lines.append(dim(f"共 {len(sessions)} 个会话"))
    print("\n" + panel("会话列表", lines))
    print()

    return 0


# ─── 核心组件初始化 ───


def _init_components(config: AppConfig):
    """初始化单 agent 运行所需的核心组件，返回 (orchestrator, session_store)。"""
    global _INIT_CACHE
    if _INIT_CACHE is not None:
        return _INIT_CACHE

    def _step(msg: str) -> None:
        print(f"  {dim(msg)}", flush=True)

    _step("正在初始化会话与角色配置...")
    llm_factory = LLMClientFactory(config)
    session_store = SessionStore(config.data_dir)
    agent_store = AgentStore(config.data_dir)
    permission_managers: dict[str, PermissionManager] = {}

    _step("正在连接模型服务（首次需要几秒）...")
    llm = _create_llm(config)

    orchestrator = AgentOrchestrator(
        config=config,
        llm=llm,
        agent_store=agent_store,
        permission_managers=permission_managers,
        session_store=session_store,
        llm_factory=llm_factory,
    )

    _INIT_CACHE = (orchestrator, session_store)
    return _INIT_CACHE


def _create_llm(config: AppConfig) -> LLMClient:
    """根据配置创建 LLM 客户端。"""
    model_info = config.get_main_model()
    if model_info is None:
        return LLMClient(
            provider=config.provider,
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.main_model,
        )
    provider = config.get_provider(model_info.provider_name)
    if provider is None:
        return LLMClient(
            provider=config.provider,
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.main_model,
        )
    return LLMClient(
        provider=provider.client_type,
        api_key=provider.api_key,
        base_url=provider.base_url,
        model=model_info.model_id,
    )


# ─── 主逻辑 ───


async def _run_cli(args: argparse.Namespace) -> int:
    """CLI 主逻辑。"""
    config = AppConfig.load()

    if not config.api_key:
        print(
            f"  {colorize('✗ ERROR', phase_color('error'))} API key 未配置。"
            f"请通过 Web UI 配置或设置 CT_API_KEY 环境变量。",
            file=sys.stderr,
        )
        return 1

    # ── --list-sessions 模式 ──
    if args.list_sessions:
        return _list_sessions(config)

    # ── 交互模式 ──
    if not args.task:
        return await _run_interactive_cli(config)

    return await _run_single_agent_once(args, config)


async def _run_single_agent_message(
    config: AppConfig,
    task_text: str,
    work_dir: Path,
    yolo: bool,
    session: Session | None,
) -> Session:
    """用 main agent 直接处理一条消息（常规任务默认路径）。

    main agent 遇到复杂任务时通过 delegate_agent 在内部委派给
    researcher（只读调研）/ coder（实现）等专业 agent，而不是强制
    走 规划→编码→审查 流水线。
    """
    first_time = session is None
    if first_time:
        print(f"  {dim('正在准备运行环境...')}")
    orchestrator, session_store = _init_components(config)

    if session is None:
        session = Session(
            id=f"cli-{int(time.time() * 1000)}",
            work_dir=work_dir,
            phase=Phase.INIT,
            yolo_mode=yolo,
            auto_review=True,
            solo_mode=True,
            title="",
        )

    broadcast = _make_console_broadcast()
    try:
        await orchestrator.run_user_message(
            session=session, text=task_text, agent_id="main", broadcast=broadcast)
    finally:
        try:
            session_store.save(session)
        except Exception:
            logger.debug("Failed to persist session %s", session.id, exc_info=True)
    return session


async def _run_single_agent_once(
    args: argparse.Namespace, config: AppConfig,
) -> int:
    """单 agent 一次性任务（CLI 默认路径）。"""
    work_dir = Path(args.work_dir).resolve()
    if not work_dir.exists():
        print(
            f"  {colorize('✗', phase_color('error'))} 工作目录不存在: {work_dir}",
            file=sys.stderr,
        )
        return 1

    session = await _run_single_agent_message(
        config, args.task, work_dir, args.yolo, None)
    return 0 if session.phase in (Phase.READY, Phase.COMPLETED) else 1


# ─── 交互模式 ───

INTERACTIVE_HELP = """\
命令:
  <任务描述>         常规任务：main agent 直答，复杂任务自动内部委派
  /workdir <路径>    切换工作目录（默认当前目录，支持 ~）
  /yolo              切换 YOLO 模式（跳过命令审批）
  /list              列出会话
  /help              显示本帮助
  exit / quit / q   退出交互模式
"""


async def _run_interactive_cli(config: AppConfig) -> int:
    """交互式 REPL——`keke` 不带参数时进入，支持连续任务。

    在任意目录运行 `keke` 即可唤起，直接输入任务描述由 main agent
    处理（常规任务直答，复杂任务内部委派）。
    """
    work_dir = Path.cwd()
    yolo = False
    session: Session | None = None

    lines = [
        f"在任意目录输入 {colorize('keke', phase_color('planning'))} 唤起；"
        f"直接输入任务描述即可。",
        f"输入 {colorize('/help', phase_color('planning'))} 查看命令，"
        f"{colorize('exit', phase_color('planning'))} 退出。",
        "",
        f"{bold('工作目录')}  {work_dir}",
    ]
    print("\n" + panel("Keke Teamwork 交互模式", lines))
    print()

    while True:
        try:
            line = input(f"\n{colorize('❯', phase_color('planning'))} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n  {dim('再见！')}")
            return 0
        if not line:
            continue

        cmd, _, rest = line.partition(" ")

        if cmd in ("exit", "quit", "q"):
            print(f"  {dim('再见！')}")
            return 0
        elif cmd in ("/help", "help", "h", "?"):
            print(INTERACTIVE_HELP)
        elif cmd == "/workdir":
            new_dir = rest.strip().strip('"').strip("'")
            if not new_dir:
                print(f"  当前工作目录: {work_dir}")
                continue
            target = Path(new_dir).expanduser().resolve()
            if target.is_dir():
                work_dir = target
                session = None  # 切换目录后从新会话开始
                print(f"  {dim('工作目录:')} {bold(str(work_dir))}")
            else:
                print(f"  {colorize('✗', phase_color('error'))} 目录不存在: {target}")
        elif cmd == "/yolo":
            yolo = not yolo
            if session is not None:
                session.yolo_mode = yolo
            print(f"  YOLO 模式: {colorize('开', phase_color('reviewing')) if yolo else '关'}")
        elif cmd == "/list":
            _list_sessions(config)
        else:
            try:
                session = await _run_single_agent_message(
                    config, line, work_dir, yolo, session)
            except KeyboardInterrupt:
                print(f"\n  {colorize('✗', phase_color('error'))} 已中断任务")

    return 0


def main() -> None:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        description="Keke Teamwork CLI——常规任务单 agent 直答 + 内部委派",
        epilog=(
            "示例:\n"
            "  # 常规任务（单 agent 直答，复杂任务内部委派）\n"
            "  python -m backend.cli \"实现用户登录功能\" --work-dir /path/to/project\n"
            "  python -m backend.cli \"修复 bug\" --work-dir . --yolo\n"
            "  python -m backend.cli \"重构模块\" --work-dir .\n\n"
            "  # 列出会话\n"
            "  python -m backend.cli --list-sessions\n\n"
            "  # 交互模式（任意目录输入 keke 唤起）\n"
            "  keke\n\n"
            "  # 调试模式\n"
            "  python -m backend.cli \"任务\" -v\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "task",
        nargs="?",
        default=None,
        help="任务描述，如 '实现用户登录功能'",
    )
    parser.add_argument(
        "--work-dir", "-w",
        default=".",
        help="工作目录（默认当前目录）",
    )
    parser.add_argument(
        "--yolo",
        action="store_true",
        help="YOLO 模式——跳过命令审批",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="列出所有会话",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="禁用彩色输出（非 TTY 时自动禁用）",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="启用 DEBUG 级别日志（显示运行内部状态）",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="Keke Teamwork CLI v0.4",
    )

    args = parser.parse_args()

    # 禁用彩色输出
    if args.no_color:
        set_color_enabled(False)

    # 日志配置
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        exit_code = asyncio.run(_run_cli(args))
    except KeyboardInterrupt:
        print(f"\n\n  {colorize('✗', phase_color('error'))} {bold('用户中断（Ctrl+C）')}")
        print(f"  {dim('会话状态已自动保存。')}")
        print()
        exit_code = 130  # 标准 Ctrl+C 退出码

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
