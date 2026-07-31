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
    """创建一个将工作流事件打印到终端的广播闭包。"""

    async def broadcast(event_type: str, payload: dict) -> None:
        if event_type == "agent.status":
            phase = payload.get("phase", "")
            detail = payload.get("detail", "")
            print(f"  [{phase}] {detail}")

        elif event_type == "agent.started":
            name = payload.get("agent_name", "")
            role = payload.get("role", "")
            print(f"\n>>> {name} ({role}) 启动")

        elif event_type == "agent.completed":
            name = payload.get("agent_name", "")
            summary = payload.get("summary", "")
            usage = payload.get("usage", {})
            in_tok = usage.get("input_tokens", 0)
            out_tok = usage.get("output_tokens", 0)
            print(f"<<< {name} 完成 (tokens: {in_tok} in / {out_tok} out)")
            if summary:
                print(f"    摘要: {summary}")

        elif event_type == "agent.text":
            text = payload.get("text", "")
            is_final = payload.get("is_final", False)
            if not is_final:
                print(text, end="", flush=True)

        elif event_type == "error":
            msg = payload.get("message", "")
            print(f"\n[ERROR] {msg}", file=sys.stderr)

        elif event_type == "tool.call":
            name = payload.get("name", "")
            stage = payload.get("stage", "")
            if stage == "running":
                print(f"\n  [tool] {name} ...")
            elif stage == "completed":
                success = payload.get("success", False)
                status = "OK" if success else "FAIL"
                print(f"  [tool] {name} -> {status}")

    return broadcast


# ─── 工作流交互 ───


def _print_task_list(task_list) -> None:
    """打印任务计划。"""
    print("\n" + "=" * 60)
    print("  任务规划完成")
    print("=" * 60)

    if task_list.overview:
        print(f"\n  方案概述：{task_list.overview}")

    print(f"\n  共 {task_list.total_count} 个子任务：\n")
    for i, task in enumerate(task_list.tasks, 1):
        status_mark = {
            "pending": " ",
            "in_progress": "→",
            "done": "✓",
            "skipped": "-",
        }.get(task.status, " ")
        print(f"  {status_mark} {i}. {task.title}")
        if task.description:
            print(f"     {task.description}")
        if task.files_involved:
            print(f"     涉及文件: {', '.join(task.files_involved)}")
        if task.acceptance_criteria:
            print(f"     验收标准: {task.acceptance_criteria}")
        print()

    if task_list.risks:
        print("  风险提示：")
        for risk in task_list.risks:
            print(f"    - {risk}")
        print()

    if task_list.estimated_effort:
        print(f"  预估工时: {task_list.estimated_effort}")

    print("\n" + "=" * 60)


def _print_review_report(report) -> None:
    """打印审查报告。"""
    print("\n" + "-" * 40)
    print(f"  审查结果: {report.overall_verdict}")
    if report.summary:
        print(f"  摘要: {report.summary}")

    for fr in report.file_reviews:
        print(f"\n  [{fr.file_path}] ({fr.severity})")
        for issue in fr.issues:
            print(f"    问题: {issue}")
        for sug in fr.suggestions:
            print(f"    建议: {sug}")

    if report.should_retry:
        print("\n  ⚠ 需要修改后重新审查")
    print("-" * 40)


def _print_workflow_progress(session: Session) -> None:
    """打印当前工作流进度（恢复时展示已有状态）。"""
    ws = session.workflow_state
    if ws is None or ws.task_list is None:
        return

    tl = ws.task_list
    print(f"\n  会话进度: {tl.completed_count}/{tl.total_count} 个子任务已完成")
    print(f"  当前阶段: {session.phase.value}")

    if tl.current_task:
        print(f"  当前任务: {tl.current_task.title}")

    if ws.completed_tasks:
        print(f"  已完成: {', '.join(ws.completed_tasks)}")


def _list_sessions(config: AppConfig) -> int:
    """列出所有可恢复的会话。"""
    session_store = SessionStore(config.data_dir)
    sessions = session_store.list_sessions()

    if not sessions:
        print("  没有可恢复的会话。")
        return 0

    print("\n" + "=" * 60)
    print("  可恢复的会话")
    print("=" * 60)

    for s in sessions:
        sid = s["session_id"]
        title = s.get("title", "(未命名)")
        phase = s.get("phase", "unknown")
        ts = s.get("last_active_at", 0)
        ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "未知"

        print(f"\n  ID:    {sid}")
        print(f"  标题:  {title}")
        print(f"  阶段:  {phase}")
        print(f"  时间:  {ts_str}")

    print("\n" + "=" * 60)
    print("  使用 --resume <session-id> 恢复指定会话")
    print("=" * 60 + "\n")

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
            "ERROR: API key 未配置。请通过 Web UI 配置或设置 CT_API_KEY 环境变量。",
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
        print("ERROR: 请提供任务描述，或使用 --resume / --list-sessions", file=sys.stderr)
        return 1

    return await _start_new_workflow(args, config)


async def _start_new_workflow(args: argparse.Namespace, config: AppConfig) -> int:
    """启动新的工作流会话。"""
    work_dir = Path(args.work_dir).resolve()
    if not work_dir.exists():
        print(f"ERROR: 工作目录不存在: {work_dir}", file=sys.stderr)
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

    print(f"\n工作目录: {work_dir}")
    print(f"模型: {config.main_model}")
    print(f"自动审查: {'是' if session.auto_review else '否'}")
    print(f"YOLO 模式: {'是' if session.yolo_mode else '否'}")
    print(f"会话 ID: {session.id}")
    print(f"\n任务: {args.task}")
    print("\n" + "=" * 60 + "\n")

    return await _run_workflow_loop(session, runner, args.task, broadcast)


async def _resume_session(args: argparse.Namespace, config: AppConfig) -> int:
    """恢复之前的工作流会话。"""
    orchestrator, runner, session_store = _init_components(config)

    session = session_store.load(args.resume)
    if session is None:
        print(f"ERROR: 未找到会话 {args.resume}", file=sys.stderr)
        return 1

    # 恢复时使用 session.title 作为任务描述
    task_text = session.title or ""

    broadcast = _make_console_broadcast()

    print(f"\n恢复会话: {session.id}")
    print(f"工作目录: {session.work_dir}")
    print(f"模型: {config.main_model}")
    print(f"当前阶段: {session.phase.value}")

    _print_workflow_progress(session)

    print("\n" + "=" * 60 + "\n")

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
            print(f"\nFATAL: {e}", file=sys.stderr)
            return 1

    # PLAN_REVIEW 阶段暂停：等待用户确认/拒绝
    while session.phase == Phase.PLAN_REVIEW:
        ws = session.workflow_state
        if ws and ws.task_list:
            _print_task_list(ws.task_list)

        choice = input("\n确认计划？(y=继续 / n=取消 / e=修改): ").strip().lower()
        if choice in ("y", "yes", "确认"):
            await runner.handle_user_command(session, "approve_plan", broadcast)
            try:
                await runner.execute(session, task_text, broadcast)
            except Exception as e:
                print(f"\nFATAL: {e}", file=sys.stderr)
                return 1
        elif choice in ("n", "no", "取消"):
            await runner.handle_user_command(session, "abort", broadcast)
            print("已取消。")
            return 0
        elif choice in ("e", "edit", "修改"):
            new_req = input("请输入修改后的需求: ").strip()
            if new_req:
                await runner.handle_user_command(
                    session, "reject_plan", broadcast, user_text=new_req)
                task_text = new_req
                session.title = new_req
                try:
                    await runner.execute(session, task_text, broadcast)
                except Exception as e:
                    print(f"\nFATAL: {e}", file=sys.stderr)
                    return 1
            else:
                print("未输入新需求，继续等待确认。")

    # CODE_REVIEW 阶段暂停（非自动审查模式）
    while session.phase == Phase.CODE_REVIEW:
        print("\n  编码完成，等待审查决策...")
        choice = input("(r=审查 / s=跳过审查 / n=取消): ").strip().lower()
        if choice in ("r", "review", "审查"):
            await runner.handle_user_command(session, "start_review", broadcast)
            try:
                await runner.execute(session, task_text, broadcast)
            except Exception as e:
                print(f"\nFATAL: {e}", file=sys.stderr)
                return 1
        elif choice in ("s", "skip", "跳过"):
            await runner.handle_user_command(session, "skip_review", broadcast)
            try:
                await runner.execute(session, task_text, broadcast)
            except Exception as e:
                print(f"\nFATAL: {e}", file=sys.stderr)
                return 1
        else:
            await runner.handle_user_command(session, "abort", broadcast)
            print("已取消。")
            return 0

    # FEEDBACK 阶段暂停：审查不通过
    while session.phase == Phase.FEEDBACK:
        ws = session.workflow_state
        if ws and ws.last_review_report:
            _print_review_report(ws.last_review_report)

        choice = input("\n审查不通过，是否重新编码？(y=重试 / s=跳过 / n=取消): ").strip().lower()
        if choice in ("y", "yes", "重试"):
            await runner.handle_user_command(session, "retry", broadcast)
            try:
                await runner.execute(session, task_text, broadcast)
            except Exception as e:
                print(f"\nFATAL: {e}", file=sys.stderr)
                return 1
        elif choice in ("s", "skip", "跳过"):
            await runner.handle_user_command(session, "skip_task", broadcast)
            if session.phase != Phase.COMPLETED:
                try:
                    await runner.execute(session, task_text, broadcast)
                except Exception as e:
                    print(f"\nFATAL: {e}", file=sys.stderr)
                    return 1
        else:
            await runner.handle_user_command(session, "abort", broadcast)
            print("已取消。")
            return 0

    # ERROR 阶段：询问恢复
    while session.phase == Phase.ERROR:
        choice = input("\n工作流出错，是否恢复？(y=重新规划 / n=退出): ").strip().lower()
        if choice in ("y", "yes", "恢复"):
            await runner.handle_user_command(session, "resume", broadcast)
            try:
                await runner.execute(session, task_text, broadcast)
            except Exception as e:
                print(f"\nFATAL: {e}", file=sys.stderr)
                return 1
        else:
            print("已退出。")
            break

    # 最终状态
    print("\n" + "=" * 60)
    if session.phase == Phase.COMPLETED:
        ws = session.workflow_state
        total = ws.task_list.total_count if ws and ws.task_list else 0
        completed = ws.task_list.completed_count if ws and ws.task_list else 0
        print(f"  工作流完成！{completed}/{total} 个子任务已完成")
    elif session.phase == Phase.ERROR:
        print("  工作流执行出错。")
    else:
        print(f"  工作流暂停于阶段: {session.phase.value}")

    # 打印会话 ID（供恢复使用）
    print(f"  会话 ID: {session.id}")
    print(f"  恢复命令: python -m backend.cli --resume {session.id}")

    # 打印 token 使用
    usage = session.usage_total
    print(f"\n  Token 使用: {usage.input_tokens} input / {usage.output_tokens} output")
    print("=" * 60 + "\n")

    return 0 if session.phase == Phase.COMPLETED else 1


def main() -> None:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        description="Keke Teamwork 工作流 CLI——Plan → Code → Review 自动闭环",
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

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    exit_code = asyncio.run(_run_workflow_cli(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
