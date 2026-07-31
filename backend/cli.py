"""CLI 入口——命令行触发工作流。

用法::

    # 新建工作流
    python -m backend.cli "实现用户登录功能" --work-dir /path/to/project
    python -m backend.cli "修复 bug" --work-dir . --yolo
    python -m backend.cli "重构模块" --work-dir . --no-auto-review

    # 列出可恢复的会话
    python -m backend.cli --list-sessions

    # 恢复之前的会话
    python -m backend.cli --resume cli-1722345678

工作流会在 PLAN_REVIEW 阶段暂停，等待用户确认后继续。
每次阶段转换后自动持久化会话状态，支持通过 --resume 恢复。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

from backend.agent_store import AgentStore
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
from backend.config import AppConfig
from backend.llm.client import LLMClient, LLMClientFactory
from backend.orchestrator import AgentOrchestrator
from backend.safety.permission import PermissionManager
from backend.session import SessionStore
from backend.types import Phase, Session
from backend.workflow.engine import WorkflowRunner

logger = logging.getLogger(__name__)


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
    }
    state["total_timer"].start()

    async def broadcast(event_type: str, payload: dict) -> None:
        if event_type == "agent.status":
            phase = payload.get("phase", "")
            detail = payload.get("detail", "")

            # 检测阶段切换，打印横幅
            if phase != state["current_phase"]:
                # 如果上一个阶段有计时，显示耗时
                if state["current_phase"] and state["agent_active"]:
                    state["timer"].stop()
                    elapsed = state["timer"].elapsed_str()
                    print(f"  {dim(f'⏱ 耗时 {elapsed}')}")
                state["current_phase"] = phase
                state["timer"] = Timer()  # 新计时器
                state["timer"].start()
                print(phase_banner(phase, detail))

            print(format_phase_status(phase, detail))

        elif event_type == "agent.started":
            name = payload.get("agent_name", "")
            role = payload.get("role", "")
            state["agent_active"] = True
            state["tool_call_count"] = 0  # 重置当前 agent 的工具调用计数
            print(f"\n{role_label(role, name)} {dim('启动...')}")

        elif event_type == "agent.completed":
            name = payload.get("agent_name", "")
            role = payload.get("role", "")
            summary = payload.get("summary", "")
            usage = payload.get("usage", {})
            in_tok = usage.get("input_tokens", 0)
            out_tok = usage.get("output_tokens", 0)
            state["agent_active"] = False
            state["timer"].stop()

            label = role_label(role, name)
            tokens = dim(format_token_usage(in_tok, out_tok))
            elapsed = dim(f"⏱ {state['timer'].elapsed_str()}")
            tool_count = state["tool_call_count"]
            tool_info = dim(f"🔧 {tool_count} 次工具调用") if tool_count > 0 else ""
            parts = [f"\n{label} {colorize('完成', phase_color('completed'))} ({tokens}) ({elapsed})"]
            if tool_info:
                parts.append(tool_info)
            print(" · ".join(parts))
            if summary:
                print(f"  {dim('摘要:')} {summary}")

        elif event_type == "agent.text":
            text = payload.get("text", "")
            is_final = payload.get("is_final", False)
            if not is_final:
                print(text, end="", flush=True)

        elif event_type == "agent.thinking":
            text = payload.get("text", "")
            if text:
                print(dim(text), end="", flush=True)

        elif event_type == "error":
            msg = payload.get("message", "")
            print(f"\n  {colorize('✗ ERROR', phase_color('error'))} {msg}", file=sys.stderr)

        elif event_type == "tool.call":
            name = payload.get("name", "")
            stage = payload.get("stage", "")
            if stage == "running":
                state["tool_call_count"] += 1
                state["total_tool_calls"] += 1
                args = payload.get("args", {})
                if isinstance(args, dict):
                    # 过滤掉 result 键
                    args = {k: v for k, v in args.items() if k != "result"}
                num = state["tool_call_count"]
                print(format_tool_call_start(name, args if isinstance(args, dict) else None, num))
            elif stage == "completed":
                success = payload.get("success", False)
                print(format_tool_call_result(name, success))

    return broadcast


# ─── 工作流交互 ───


def _print_task_list(task_list) -> None:
    """打印任务计划（彩色 + 进度条）。"""
    print("\n" + banner("任务规划完成"))

    if task_list.overview:
        print(f"\n  {bold('方案概述：')}{task_list.overview}")

    completed = task_list.completed_count
    total = task_list.total_count
    print(f"\n  {bold('进度：')} {progress_bar(completed, total)}")

    print(f"\n  {bold(f'共 {total} 个子任务：')}\n")
    for i, task in enumerate(task_list.tasks, 1):
        status_config = {
            "pending": ("○", phase_color("init")),
            "in_progress": ("→", phase_color("coding")),
            "done": ("✓", phase_color("completed")),
            "skipped": ("-", phase_color("error")),
        }
        mark, color = status_config.get(task.status, ("○", phase_color("init")))
        task_num = colorize(f"  {mark} {i}.", color)
        print(f"{task_num} {bold(task.title)}")
        if task.description:
            print(f"     {dim(task.description)}")
        if task.files_involved:
            print(f"     {dim('涉及文件:')} {', '.join(task.files_involved)}")
        if task.acceptance_criteria:
            print(f"     {dim('验收标准:')} {task.acceptance_criteria}")
        print()

    if task_list.risks:
        print(f"  {colorize('⚠ 风险提示', phase_color('reviewing'))}")
        for risk in task_list.risks:
            print(f"    {colorize('-', phase_color('reviewing'))} {risk}")
        print()

    if task_list.estimated_effort:
        print(f"  {dim('预估工时:')} {task_list.estimated_effort}")

    print("\n" + separator())


def _print_review_report(report) -> None:
    """打印审查报告（彩色）。"""
    print("\n" + separator("-", 50))
    print(f"  {bold('审查结果:')} {format_verdict(report.overall_verdict)}")
    if report.summary:
        print(f"  {dim('摘要:')} {report.summary}")

    for fr in report.file_reviews:
        icon = severity_icon(fr.severity)
        color = severity_color(fr.severity)
        print(f"\n  {colorize(f'{icon} [{fr.file_path}]', color)} {dim(f'({fr.severity})')}")
        for issue in fr.issues:
            print(f"    {colorize('问题:', phase_color('error'))} {issue}")
        for sug in fr.suggestions:
            print(f"    {colorize('建议:', phase_color('reviewing'))} {sug}")

    if report.should_retry:
        print(f"\n  {colorize('⚠ 需要修改后重新审查', phase_color('reviewing'))}")
    print(separator("-", 50))


def _print_workflow_progress(session: Session) -> None:
    """打印当前工作流进度（恢复时展示已有状态，含进度条）。"""
    ws = session.workflow_state
    if ws is None or ws.task_list is None:
        return

    tl = ws.task_list
    completed = tl.completed_count
    total = tl.total_count

    print(f"\n  {bold('会话进度:')} {progress_bar(completed, total)}")
    print(f"  {bold('当前阶段:')} {colorize(session.phase.value, phase_color(session.phase.value))}")

    if tl.current_task:
        print(f"  {bold('当前任务:')} {tl.current_task.title}")

    if ws.completed_tasks:
        print(f"  {dim('已完成:')} {', '.join(ws.completed_tasks)}")


def _list_sessions(config: AppConfig) -> int:
    """列出所有可恢复的会话（彩色，按最近活跃排序）。"""
    session_store = SessionStore(config.data_dir)
    sessions = session_store.list_sessions()

    if not sessions:
        print(f"  {dim('没有可恢复的会话。')}")
        return 0

    # 按最近活跃时间降序排列
    sessions.sort(key=lambda s: s.get("last_active_at", 0), reverse=True)

    print(f"\n{banner('可恢复的会话')}")
    print(f"  {dim(f'共 {len(sessions)} 个会话')}\n")

    for i, s in enumerate(sessions, 1):
        sid = s["session_id"]
        title = s.get("title", "(未命名)")
        phase = s.get("phase", "unknown")
        ts = s.get("last_active_at", 0)
        ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "未知"

        print(f"  {colorize(f'{i}.', phase_color('planning'))} {bold('ID:')}    {colorize(sid, phase_color('planning'))}")
        print(f"     {bold('标题:')}  {title}")
        print(f"     {bold('阶段:')}  {colorize(phase, phase_color(phase))}")
        print(f"     {dim('时间:')}  {ts_str}")
        print()

    print(separator())
    print(f"  {dim('使用 --resume <session-id> 恢复指定会话')}")
    print(separator() + "\n")

    return 0


# ─── 核心组件初始化 ───


def _init_components(config: AppConfig):
    """初始化工作流所需的核心组件，返回元组。"""
    llm = _create_llm(config)
    llm_factory = LLMClientFactory(config)
    session_store = SessionStore(config.data_dir)
    agent_store = AgentStore(config.data_dir)
    permission_managers: dict[str, PermissionManager] = {}

    orchestrator = AgentOrchestrator(
        config=config,
        llm=llm,
        agent_store=agent_store,
        permission_managers=permission_managers,
        session_store=session_store,
        llm_factory=llm_factory,
    )

    runner = WorkflowRunner(orchestrator, agent_store, session_store)

    return orchestrator, runner, session_store


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


async def _run_workflow_cli(args: argparse.Namespace) -> int:
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

    # ── --resume 模式 ──
    if args.resume:
        return await _resume_session(args, config)

    # ── 正常新建工作流模式 ──
    if not args.task:
        print(
            f"  {colorize('✗', phase_color('error'))} 请提供任务描述，或使用 --resume / --list-sessions",
            file=sys.stderr,
        )
        return 1

    return await _start_new_workflow(args, config)


async def _start_new_workflow(args: argparse.Namespace, config: AppConfig) -> int:
    """启动新的工作流会话。"""
    work_dir = Path(args.work_dir).resolve()
    if not work_dir.exists():
        print(f"  {colorize('✗', phase_color('error'))} 工作目录不存在: {work_dir}", file=sys.stderr)
        return 1

    orchestrator, runner, session_store = _init_components(config)

    # 创建会话
    session = Session(
        id=f"cli-{int(time.time())}",
        work_dir=work_dir,
        phase=Phase.INIT,
        yolo_mode=args.yolo,
        auto_review=True,
        solo_mode=True,
        title=args.task,  # 存储任务描述，供恢复使用
    )
    session.auto_review = not args.no_auto_review

    broadcast = _make_console_broadcast()

    print(f"\n{banner('Keke Teamwork 工作流')}")
    print(f"\n  {bold('工作目录:')} {work_dir}")
    print(f"  {bold('模型:')}     {config.main_model}")
    print(f"  {bold('自动审查:')} {colorize('是', phase_color('completed')) if session.auto_review else colorize('否', phase_color('error'))}")
    print(f"  {bold('YOLO 模式:')} {colorize('是', phase_color('reviewing')) if session.yolo_mode else '否'}")
    print(f"  {bold('会话 ID:')}  {colorize(session.id, phase_color('planning'))}")
    print(f"\n  {bold('任务:')} {args.task}")
    print("\n" + separator() + "\n")

    return await _run_workflow_loop(session, runner, args.task, broadcast)


async def _resume_session(args: argparse.Namespace, config: AppConfig) -> int:
    """恢复之前的工作流会话。"""
    orchestrator, runner, session_store = _init_components(config)

    session = session_store.load(args.resume)
    if session is None:
        print(f"  {colorize('✗', phase_color('error'))} 未找到会话 {args.resume}", file=sys.stderr)
        return 1

    # 恢复时使用 session.title 作为任务描述
    task_text = session.title or ""

    broadcast = _make_console_broadcast()

    print(f"\n{banner('恢复工作流会话')}")
    print(f"\n  {bold('会话 ID:')}  {colorize(session.id, phase_color('planning'))}")
    print(f"  {bold('工作目录:')} {session.work_dir}")
    print(f"  {bold('模型:')}     {config.main_model}")
    print(f"  {bold('当前阶段:')} {colorize(session.phase.value, phase_color(session.phase.value))}")

    _print_workflow_progress(session)

    print("\n" + separator() + "\n")

    return await _run_workflow_loop(session, runner, task_text, broadcast)


async def _run_workflow_loop(
    session: Session,
    runner: WorkflowRunner,
    task_text: str,
    broadcast,
) -> int:
    """工作流主交互循环——处理各阶段的用户输入。

    被 _start_new_workflow 和 _resume_session 共用。
    """
    # 如果当前阶段需要执行（如 INIT、CODING 等），先跑一轮
    if session.phase not in (
        Phase.PLAN_REVIEW, Phase.CODE_REVIEW,
        Phase.FEEDBACK, Phase.ERROR, Phase.COMPLETED,
    ):
        try:
            await runner.execute(session, task_text, broadcast)
        except Exception as e:
            print(f"\n  {colorize('✗ FATAL', phase_color('error'))} {e}", file=sys.stderr)
            return 1

    # PLAN_REVIEW 阶段暂停：等待用户确认/拒绝
    while session.phase == Phase.PLAN_REVIEW:
        ws = session.workflow_state
        if ws and ws.task_list:
            _print_task_list(ws.task_list)

        choice = input(f"\n{bold('确认计划？')}(y=继续 / n=取消 / e=修改): ").strip().lower()
        if choice in ("y", "yes", "确认"):
            await runner.handle_user_command(session, "approve_plan", broadcast)
            try:
                await runner.execute(session, task_text, broadcast)
            except Exception as e:
                print(f"\n  {colorize('✗ FATAL', phase_color('error'))} {e}", file=sys.stderr)
                return 1
        elif choice in ("n", "no", "取消"):
            await runner.handle_user_command(session, "abort", broadcast)
            print(f"  {dim('已取消。')}")
            return 0
        elif choice in ("e", "edit", "修改"):
            new_req = input(f"{bold('请输入修改后的需求:')} ").strip()
            if new_req:
                await runner.handle_user_command(
                    session, "reject_plan", broadcast, user_text=new_req)
                task_text = new_req
                session.title = new_req
                try:
                    await runner.execute(session, task_text, broadcast)
                except Exception as e:
                    print(f"\n  {colorize('✗ FATAL', phase_color('error'))} {e}", file=sys.stderr)
                    return 1
            else:
                print(f"  {dim('未输入新需求，继续等待确认。')}")

    # CODE_REVIEW 阶段暂停（非自动审查模式）
    while session.phase == Phase.CODE_REVIEW:
        print(f"\n  {colorize('⏸ 编码完成，等待审查决策...', phase_color('code_review'))}")
        choice = input(f"({bold('r')}=审查 / {bold('s')}=跳过审查 / {bold('n')}=取消): ").strip().lower()
        if choice in ("r", "review", "审查"):
            await runner.handle_user_command(session, "start_review", broadcast)
            try:
                await runner.execute(session, task_text, broadcast)
            except Exception as e:
                print(f"\n  {colorize('✗ FATAL', phase_color('error'))} {e}", file=sys.stderr)
                return 1
        elif choice in ("s", "skip", "跳过"):
            await runner.handle_user_command(session, "skip_review", broadcast)
            try:
                await runner.execute(session, task_text, broadcast)
            except Exception as e:
                print(f"\n  {colorize('✗ FATAL', phase_color('error'))} {e}", file=sys.stderr)
                return 1
        else:
            await runner.handle_user_command(session, "abort", broadcast)
            print(f"  {dim('已取消。')}")
            return 0

    # FEEDBACK 阶段暂停：审查不通过
    while session.phase == Phase.FEEDBACK:
        ws = session.workflow_state
        if ws and ws.last_review_report:
            _print_review_report(ws.last_review_report)

        retry_count = ws.retry_count if ws else 0
        retry_info = f" {colorize(f'(第 {retry_count} 次重试)', phase_color('reviewing'))}" if retry_count > 0 else ""
        choice = input(f"\n{colorize('审查不通过', phase_color('reviewing'))}{retry_info}，是否重新编码？({bold('y')}=重试 / {bold('s')}=跳过 / {bold('n')}=取消): ").strip().lower()
        if choice in ("y", "yes", "重试"):
            await runner.handle_user_command(session, "retry", broadcast)
            try:
                await runner.execute(session, task_text, broadcast)
            except Exception as e:
                print(f"\n  {colorize('✗ FATAL', phase_color('error'))} {e}", file=sys.stderr)
                return 1
        elif choice in ("s", "skip", "跳过"):
            await runner.handle_user_command(session, "skip_task", broadcast)
            if session.phase != Phase.COMPLETED:
                try:
                    await runner.execute(session, task_text, broadcast)
                except Exception as e:
                    print(f"\n  {colorize('✗ FATAL', phase_color('error'))} {e}", file=sys.stderr)
                    return 1
        else:
            await runner.handle_user_command(session, "abort", broadcast)
            print(f"  {dim('已取消。')}")
            return 0

    # ERROR 阶段：询问恢复
    while session.phase == Phase.ERROR:
        choice = input(f"\n  {colorize('✗ 工作流出错', phase_color('error'))}，是否恢复？({bold('y')}=重新规划 / {bold('n')}=退出): ").strip().lower()
        if choice in ("y", "yes", "恢复"):
            await runner.handle_user_command(session, "resume", broadcast)
            try:
                await runner.execute(session, task_text, broadcast)
            except Exception as e:
                print(f"\n  {colorize('✗ FATAL', phase_color('error'))} {e}", file=sys.stderr)
                return 1
        else:
            print(f"  {dim('已退出。')}")
            break

    # 最终状态
    print("\n" + separator())
    if session.phase == Phase.COMPLETED:
        ws = session.workflow_state
        total = ws.task_list.total_count if ws and ws.task_list else 0
        completed = ws.task_list.completed_count if ws and ws.task_list else 0
        files_changed = ws.total_files_changed if ws else 0
        skipped = sum(1 for t in ws.task_list.tasks if t.status == "skipped") if ws and ws.task_list else 0

        print(f"  {colorize(phase_icon('completed'), phase_color('completed'))} {bold('工作流完成！')}")
        print(f"  {bold('进度：')} {progress_bar(completed, total)}")
        if files_changed > 0:
            print(f"  {bold('文件变更：')} {colorize(str(files_changed), phase_color('coding'))} 个文件")
        if skipped > 0:
            print(f"  {bold('跳过任务：')} {colorize(str(skipped), phase_color('error'))} 个")
        # 逐任务状态摘要
        if ws and ws.task_list:
            print(f"\n  {bold('任务明细：')}")
            for i, task in enumerate(ws.task_list.tasks, 1):
                status_map = {
                    "done": ("✓", phase_color("completed")),
                    "skipped": ("-", phase_color("error")),
                    "pending": ("○", phase_color("init")),
                    "in_progress": ("→", phase_color("coding")),
                }
                mark, color = status_map.get(task.status, ("○", phase_color("init")))
                print(f"    {colorize(f'{mark} {i}.', color)} {task.title}")
    elif session.phase == Phase.ERROR:
        print(f"  {colorize(phase_icon('error'), phase_color('error'))} {bold('工作流执行出错。')}")
    else:
        print(f"  {colorize(phase_icon(session.phase.value), phase_color(session.phase.value))} 工作流暂停于阶段: {colorize(session.phase.value, phase_color(session.phase.value))}")

    # 打印会话 ID（供恢复使用）
    print(f"\n  {bold('会话 ID:')} {colorize(session.id, phase_color('planning'))}")
    print(f"  {dim('恢复命令:')} python -m backend.cli --resume {session.id}")

    # 打印 token 使用
    usage = session.usage_total
    print(f"\n  {bold('Token 使用:')} {format_token_usage(usage.input_tokens, usage.output_tokens)}")
    print(separator() + "\n")

    return 0 if session.phase == Phase.COMPLETED else 1


def main() -> None:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        description="Keke Teamwork 工作流 CLI——Plan → Code → Review 自动闭环",
        epilog=(
            "示例:\n"
            "  # 新建工作流\n"
            "  python -m backend.cli \"实现用户登录功能\" --work-dir /path/to/project\n"
            "  python -m backend.cli \"修复 bug\" --work-dir . --yolo\n"
            "  python -m backend.cli \"重构模块\" --work-dir . --no-auto-review\n\n"
            "  # 列出可恢复的会话\n"
            "  python -m backend.cli --list-sessions\n\n"
            "  # 恢复之前的会话\n"
            "  python -m backend.cli --resume cli-1722345678\n\n"
            "  # 调试模式\n"
            "  python -m backend.cli \"任务\" -v\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "task",
        nargs="?",
        default=None,
        help="任务描述，如 '实现用户登录功能'（与 --resume 互斥）",
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
        "--no-auto-review",
        action="store_true",
        help="禁用自动审查（编码后暂停等待手动触发）",
    )
    parser.add_argument(
        "--resume",
        metavar="SESSION_ID",
        default=None,
        help="恢复之前的工作流会话",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="列出所有可恢复的会话",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="禁用彩色输出（非 TTY 时自动禁用）",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="启用 DEBUG 级别日志（显示工作流内部状态）",
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
        exit_code = asyncio.run(_run_workflow_cli(args))
    except KeyboardInterrupt:
        print(f"\n\n  {colorize('✗', phase_color('error'))} {bold('用户中断（Ctrl+C）')}")
        print(f"  {dim('会话状态已自动保存，可通过 --resume 恢复。')}")
        print()
        exit_code = 130  # 标准 Ctrl+C 退出码

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
