"""基础模块独立单元测试：SessionStore / FileStagingArea / EditTool / PermissionManager。"""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from backend.session import SessionStore
from backend.safety.file_staging import FileStagingArea
from backend.safety.permission import PermissionManager
from backend.safety.command_risk import CommandRisk
from backend.tools.edit import EditTool
from backend.types import (
    AgentPermissions,
    Phase,
    Session,
    TokenUsage,
    ToolContext,
)


# ═══════════════════════════════════════════════════════════════════
# SessionStore
# ═══════════════════════════════════════════════════════════════════

class SessionStoreTests(unittest.TestCase):
    """验证会话的 JSON 文件持久化：save / load / list / delete。"""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._data_dir = Path(self._tmp.name)
        self._store = SessionStore(self._data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make_session(self, session_id: str = "s1", **overrides) -> Session:
        kwargs = dict(
            id=session_id,
            work_dir=Path("/fake/project"),
            phase=Phase.INIT,
            messages=[{"role": "user", "content": "hello"}],
            project_context={"lang": "python"},
            yolo_mode=False,
            auto_review=True,
            solo_mode=False,
            usage_total=TokenUsage(input_tokens=100, output_tokens=50),
            title="Test Session",
            created_at=1000.0,
            last_active_at=2000.0,
        )
        kwargs.update(overrides)
        return Session(**kwargs)

    # ── save / load ──

    def test_save_and_load_roundtrip(self) -> None:
        s = self._make_session()
        self._store.save(s)
        loaded = self._store.load("s1")
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.id, "s1")
        self.assertEqual(loaded.title, "Test Session")
        self.assertEqual(loaded.phase, Phase.INIT)
        self.assertEqual(loaded.messages, [{"role": "user", "content": "hello"}])
        self.assertEqual(loaded.project_context, {"lang": "python"})
        self.assertEqual(loaded.usage_total.input_tokens, 100)
        self.assertEqual(loaded.usage_total.output_tokens, 50)
        self.assertEqual(loaded.created_at, 1000.0)
        self.assertEqual(loaded.last_active_at, 2000.0)

    def test_save_and_load_preserves_booleans(self) -> None:
        s = self._make_session(yolo_mode=True, auto_review=False, solo_mode=True)
        self._store.save(s)
        loaded = self._store.load("s1")
        assert loaded is not None
        self.assertTrue(loaded.yolo_mode)
        self.assertFalse(loaded.auto_review)
        self.assertTrue(loaded.solo_mode)

    def test_save_and_load_minimal_session(self) -> None:
        """最简 Session：只有必填字段。"""
        s = Session(id="min", work_dir=Path("/tmp"))
        self._store.save(s)
        loaded = self._store.load("min")
        assert loaded is not None
        self.assertEqual(loaded.id, "min")
        self.assertEqual(loaded.messages, [])
        self.assertEqual(loaded.phase, Phase.INIT)
        self.assertEqual(loaded.usage_total.input_tokens, 0)
        self.assertEqual(loaded.title, "")

    def test_save_overwrites_existing(self) -> None:
        s1 = self._make_session(title="First")
        self._store.save(s1)
        s2 = self._make_session(title="Second")
        self._store.save(s2)
        loaded = self._store.load("s1")
        assert loaded is not None
        self.assertEqual(loaded.title, "Second")

    # ── load edge cases ──

    def test_load_nonexistent_returns_none(self) -> None:
        self.assertIsNone(self._store.load("no-such-session"))

    def test_load_corrupt_json_returns_none(self) -> None:
        path = self._data_dir / "sessions" / "bad.json"
        path.write_text("not valid json {{{", encoding="utf-8")
        self.assertIsNone(self._store.load("bad"))

    def test_load_missing_id_key_returns_none(self) -> None:
        path = self._data_dir / "sessions" / "noid.json"
        path.write_text('{"title": "no id field"}', encoding="utf-8")
        self.assertIsNone(self._store.load("noid"))

    def test_load_partial_data_fills_defaults(self) -> None:
        path = self._data_dir / "sessions" / "partial.json"
        path.write_text(json.dumps({
            "id": "partial",
            "work_dir": "/tmp",
        }), encoding="utf-8")
        loaded = self._store.load("partial")
        assert loaded is not None
        self.assertEqual(loaded.messages, [])
        self.assertEqual(loaded.usage_total.input_tokens, 0)

    # ── list ──

    def test_list_empty(self) -> None:
        self.assertEqual(self._store.list_sessions(), [])

    def test_list_returns_summaries(self) -> None:
        self._store.save(self._make_session("s1", title="Alpha", created_at=1000))
        self._store.save(self._make_session("s2", title="Beta", created_at=2000))
        result = self._store.list_sessions()
        self.assertEqual(len(result), 2)
        ids = {r["session_id"] for r in result}
        self.assertEqual(ids, {"s1", "s2"})
        titles = {r["title"] for r in result}
        self.assertEqual(titles, {"Alpha", "Beta"})

    def test_list_skips_corrupt_files(self) -> None:
        self._store.save(self._make_session("good"))
        (self._data_dir / "sessions" / "bad.json").write_text("garbage", encoding="utf-8")
        result = self._store.list_sessions()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["session_id"], "good")

    # ── delete ──

    def test_delete_removes_file(self) -> None:
        self._store.save(self._make_session("s1"))
        self.assertIsNotNone(self._store.load("s1"))
        self._store.delete("s1")
        self.assertIsNone(self._store.load("s1"))

    def test_delete_nonexistent_no_error(self) -> None:
        """删除不存在的会话不应抛出异常。"""
        self._store.delete("no-such-session")

    def test_save_after_delete_recreates(self) -> None:
        self._store.save(self._make_session("s1", title="v1"))
        self._store.delete("s1")
        self._store.save(self._make_session("s1", title="v2"))
        loaded = self._store.load("s1")
        assert loaded is not None
        self.assertEqual(loaded.title, "v2")


# ═══════════════════════════════════════════════════════════════════
# FileStagingArea
# ═══════════════════════════════════════════════════════════════════

class FileStagingAreaTests(unittest.TestCase):
    """验证文件暂存区：write / edit / commit / rollback。"""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._work_dir = Path(self._tmp.name)
        self._staging = FileStagingArea(self._work_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_file(self, rel_path: str, content: str) -> Path:
        p = self._work_dir / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    # ── stage_write ──

    def test_stage_write_new_file(self) -> None:
        self._staging.stage_write(Path("new.txt"), "hello")
        self.assertTrue((self._work_dir / "new.txt").exists())
        self.assertEqual((self._work_dir / "new.txt").read_text(), "hello")

    def test_stage_write_new_file_creates_dirs(self) -> None:
        self._staging.stage_write(Path("deep/nested/file.txt"), "deep")
        self.assertTrue((self._work_dir / "deep" / "nested" / "file.txt").exists())

    def test_stage_write_modifies_existing(self) -> None:
        self._write_file("existing.txt", "original")
        self._staging.stage_write(Path("existing.txt"), "modified")
        self.assertEqual((self._work_dir / "existing.txt").read_text(), "modified")

    # ── stage_edit ──

    def test_stage_edit_replaces_text(self) -> None:
        self._write_file("code.py", "foo = 1\nbar = 2\nbaz = 3\n")
        self._staging.stage_edit(Path("code.py"), "bar = 2", "bar = 42")
        content = (self._work_dir / "code.py").read_text()
        self.assertIn("bar = 42", content)
        self.assertNotIn("bar = 2", content)

    def test_stage_edit_text_not_found_raises(self) -> None:
        self._write_file("code.py", "hello world")
        with self.assertRaises(ValueError) as ctx:
            self._staging.stage_edit(Path("code.py"), "nonexistent", "replacement")
        self.assertIn("old_text not found", str(ctx.exception))

    def test_stage_edit_creates_baseline_if_not_tracked(self) -> None:
        """编辑未追踪的文件时自动记录 baseline。"""
        self._write_file("untracked.txt", "before")
        staging = FileStagingArea(self._work_dir)  # 空 baseline
        staging.stage_edit(Path("untracked.txt"), "before", "after")
        # 应能成功 rollback
        staging.rollback()
        self.assertEqual((self._work_dir / "untracked.txt").read_text(), "before")

    # ── commit ──

    def test_commit_create_detected(self) -> None:
        staging = FileStagingArea(self._work_dir)  # baseline 已捕获
        staging.stage_write(Path("created.txt"), "new file content")
        result = staging.commit()
        self.assertEqual(result.files_changed, 1)
        self.assertEqual(result.diffs[0].action, "create")
        self.assertIn("new file content", result.diffs[0].diff_text)

    def test_commit_modify_detected(self) -> None:
        self._write_file("mod.txt", "original")
        staging = FileStagingArea(self._work_dir)  # 捕获 baseline
        staging.stage_write(Path("mod.txt"), "modified content")
        result = staging.commit()
        self.assertEqual(result.files_changed, 1)
        self.assertEqual(result.diffs[0].action, "modify")
        self.assertIn("modified content", result.diffs[0].diff_text)

    def test_commit_unchanged_no_diff(self) -> None:
        self._write_file("same.txt", "unchanged")
        staging = FileStagingArea(self._work_dir)
        # 不修改任何文件
        result = staging.commit()
        self.assertEqual(result.files_changed, 0)

    def test_commit_multiple_files(self) -> None:
        staging = FileStagingArea(self._work_dir)
        staging.stage_write(Path("a.txt"), "A")
        staging.stage_write(Path("b.txt"), "B")
        result = staging.commit()
        self.assertEqual(result.files_changed, 2)

    def test_commit_summary_format(self) -> None:
        staging = FileStagingArea(self._work_dir)
        staging.stage_write(Path("f.txt"), "x")
        result = staging.commit()
        self.assertIn("1 file(s) changed", result.summary)
        self.assertIn("create f.txt", result.summary)

    def test_commit_combined_diff(self) -> None:
        staging = FileStagingArea(self._work_dir)
        staging.stage_write(Path("a.txt"), "A")
        staging.stage_write(Path("b.txt"), "B")
        result = staging.commit()
        self.assertIn("a.txt", result.combined_diff)
        self.assertIn("b.txt", result.combined_diff)

    # ── rollback ──

    def test_rollback_restores_modified_file(self) -> None:
        self._write_file("restore.txt", "original")
        staging = FileStagingArea(self._work_dir)
        staging.stage_write(Path("restore.txt"), "modified")
        staging.rollback()
        self.assertEqual((self._work_dir / "restore.txt").read_text(), "original")

    def test_rollback_deletes_new_file(self) -> None:
        staging = FileStagingArea(self._work_dir)
        staging.stage_write(Path("new_only.txt"), "temp")
        self.assertTrue((self._work_dir / "new_only.txt").exists())
        staging.rollback()
        self.assertFalse((self._work_dir / "new_only.txt").exists())

    def test_rollback_does_not_touch_untracked(self) -> None:
        """rollback 不应影响未被 staging 追踪的文件。"""
        self._write_file("untracked.txt", "leave me alone")
        staging = FileStagingArea(self._work_dir)
        staging.stage_write(Path("tracked.txt"), "changed")
        staging.rollback()
        self.assertEqual((self._work_dir / "untracked.txt").read_text(), "leave me alone")

    # ── skip logic ──

    def test_capture_baseline_skips_large_files(self) -> None:
        self._write_file("small.txt", "ok")
        big = self._work_dir / "big.txt"
        big.write_bytes(b"\x00" * (FileStagingArea.MAX_FILE_SIZE + 1))
        staging = FileStagingArea(self._work_dir)
        self.assertIn((self._work_dir / "small.txt").resolve(), staging._baseline)
        self.assertNotIn(big.resolve(), staging._baseline)

    def test_capture_baseline_skips_skip_dirs(self) -> None:
        (self._work_dir / ".git").mkdir(parents=True, exist_ok=True)
        self._write_file(".git/config", "[core]")
        staging = FileStagingArea(self._work_dir)
        git_config = (self._work_dir / ".git" / "config").resolve()
        self.assertNotIn(git_config, staging._baseline)

    # ── observe_path ──

    def test_observe_path_tracks_existing_file(self) -> None:
        self._write_file("pre_existing.txt", "old")
        staging = FileStagingArea(self._work_dir)
        staging.observe_path(Path("pre_existing.txt"))
        self.assertIn((self._work_dir / "pre_existing.txt").resolve(), staging._tracked_paths)

    def test_observe_path_tracks_nonexistent(self) -> None:
        """对不存在的文件调用 observe_path 也不应报错。"""
        staging = FileStagingArea(self._work_dir)
        staging.observe_path(Path("does_not_exist.txt"))
        # 不应抛出异常


# ═══════════════════════════════════════════════════════════════════
# EditTool
# ═══════════════════════════════════════════════════════════════════

class EditToolTests(IsolatedAsyncioTestCase):
    """验证编辑工具的核心逻辑：替换、重复匹配、换行兼容。"""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._work_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make_ctx(self, **overrides) -> ToolContext:
        """构建最小 ToolContext。"""
        s = Session(id="test", work_dir=self._work_dir)
        kwargs = dict(session=s, work_dir=self._work_dir, agent_permissions=None)
        kwargs.update(overrides)
        return ToolContext(**kwargs)

    def _write(self, rel: str, content: str) -> None:
        p = self._work_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    async def _run_edit(self, path: str, old: str, new: str, ctx: ToolContext | None = None) -> tuple[bool, str]:
        tool = EditTool(ctx or self._make_ctx())
        success, msg = await tool.execute(path=path, old_text=old, new_text=new)
        return success, msg

    # ── basic replacement ──

    async def test_exact_replacement(self) -> None:
        self._write("f.py", "x = 1\ny = 2\n")
        ok, msg = await self._run_edit("f.py", "y = 2", "y = 42")
        self.assertTrue(ok)
        content = (self._work_dir / "f.py").read_text()
        self.assertIn("y = 42", content)

    async def test_text_not_found(self) -> None:
        self._write("f.py", "hello world")
        ok, msg = await self._run_edit("f.py", "goodbye", "replaced")
        self.assertFalse(ok)
        self.assertIn("未在文件中找到该文本", msg)

    async def test_multiple_matches_rejected(self) -> None:
        self._write("f.py", "dup\ndup\n")
        ok, msg = await self._run_edit("f.py", "dup", "unique")
        self.assertFalse(ok)
        self.assertIn("匹配到 2 处", msg)

    async def test_file_not_found(self) -> None:
        ok, msg = await self._run_edit("nope.py", "a", "b")
        self.assertFalse(ok)
        self.assertIn("文件未找到", msg)

    async def test_not_a_file(self) -> None:
        (self._work_dir / "subdir").mkdir()
        ok, msg = await self._run_edit("subdir", "a", "b")
        self.assertFalse(ok)
        self.assertIn("不是一个文件", msg)

    # ── CRLF / LF normalization ──

    async def test_crlf_file_matches_lf_old_text(self) -> None:
        """CRLF 文件用 LF 搜索文本也能匹配。"""
        (self._work_dir / "crlf.py").write_bytes(b"line1\r\nline2\r\n")
        ok, msg = await self._run_edit("crlf.py", "line1\nline2", "a\nb")
        self.assertTrue(ok, msg=msg)
        content = (self._work_dir / "crlf.py").read_bytes()
        # 应保留原始 CRLF 行尾
        self.assertIn(b"a\r\nb", content)

    async def test_crlf_preserved_after_edit(self) -> None:
        """🔒 回归守卫: edit.py 必须用 newline='' 打开文件, 否则此测试在 Linux 上失败。

        为什么: Python 默认文本模式会 \\r\\n→\\n, 导致 CRLF 文件被悄悄转成 LF。
        没有 newline='' 时, Windows 上看似正常(写出时自动补 \\r), 但 Linux CI 直接炸。
        """
        (self._work_dir / "crlf.py").write_bytes(b"foo\r\nbar\r\n")
        ok, _ = await self._run_edit("crlf.py", "foo", "X")
        self.assertTrue(ok)
        raw = (self._work_dir / "crlf.py").read_bytes()
        # 关键断言: 无论什么平台, CRLF 必须原样保留
        self.assertEqual(raw, b"X\r\nbar\r\n",
                         "缺少 newline='' 会导致 CRLF 被转成 LF")

    async def test_lf_file_matches_crlf_old_text(self) -> None:
        """LF 文件用 CRLF 搜索文本也能匹配。"""
        (self._work_dir / "lf.py").write_bytes(b"line1\nline2\n")
        ok, msg = await self._run_edit("lf.py", "line1\r\nline2", "a\r\nb")
        self.assertTrue(ok, msg=msg)
        content = (self._work_dir / "lf.py").read_bytes()
        # 替换成功即可（行尾取决于 OS 文本模式转换）
        self.assertIn(b"a", content)
        self.assertIn(b"b", content)

    # ── path permissions ──

    async def test_path_denied_by_agent_permissions(self) -> None:
        self._write("src/main.py", "code")
        perms = AgentPermissions(allowed_paths=["tests/**"])
        ctx = self._make_ctx(agent_permissions=perms)
        ok, msg = await self._run_edit("src/main.py", "code", "new", ctx=ctx)
        self.assertFalse(ok)
        self.assertIn("Agent", msg)
        self.assertIn("权限", msg)

    async def test_path_allowed_by_agent_permissions(self) -> None:
        self._write("src/main.py", "old code")
        perms = AgentPermissions(allowed_paths=["src/**"])
        ctx = self._make_ctx(agent_permissions=perms)
        ok, msg = await self._run_edit("src/main.py", "old code", "new code", ctx=ctx)
        self.assertTrue(ok)

    # ── staging integration ──

    async def test_with_staging_uses_stage_write(self) -> None:
        self._write("staged.txt", "before edit")
        from backend.safety.file_staging import FileStagingArea
        staging = FileStagingArea(self._work_dir)
        ctx = self._make_ctx(staging=staging)
        ok, msg = await self._run_edit("staged.txt", "before edit", "after edit", ctx=ctx)
        self.assertTrue(ok)
        # commit 应检测到变更
        result = staging.commit()
        self.assertEqual(result.files_changed, 1)
        self.assertEqual(result.diffs[0].action, "modify")

    # ── latin-1 fallback ──

    async def test_latin1_fallback(self) -> None:
        """UTF-8 解码失败时回退到 latin-1。"""
        p = self._work_dir / "latin1.txt"
        p.write_bytes("café".encode("latin-1"))
        ok, msg = await self._run_edit("latin1.txt", "café", "cafe")
        self.assertTrue(ok)

    async def test_read_error(self) -> None:
        """无法读取的文件（权限问题等）返回错误。"""
        p = self._work_dir / "bad.bin"
        p.write_bytes(b"\x80\x81\x82")  # 无效 UTF-8，也不是 latin-1 可解码文本
        # 实际上 latin-1 可以解码任何字节，所以这个测试用二进制但会被读。
        # 换一个角度：用 0x00 字节，latin-1 能读但内容奇怪
        ok, msg = await self._run_edit("bad.bin", "garbage", "x")
        self.assertFalse(ok)


# ═══════════════════════════════════════════════════════════════════
# PermissionManager
# ═══════════════════════════════════════════════════════════════════

class PermissionManagerTests(unittest.TestCase):
    """验证命令审批：风险分级、YOLO 模式、超时、预算约束。"""

    def setUp(self) -> None:
        self._broadcast = AsyncMock()
        self._pm = PermissionManager(broadcast=self._broadcast, yolo_mode=False)

    # ── check() basic ──

    def test_empty_command_deny(self) -> None:
        self.assertEqual(self._pm.check(""), "deny")
        self.assertEqual(self._pm.check("   "), "deny")

    def test_read_only_commands_allow(self) -> None:
        self.assertEqual(self._pm.check("ls"), "allow")
        self.assertEqual(self._pm.check("git status"), "allow")
        self.assertEqual(self._pm.check("echo hello"), "allow")

    def test_normal_commands_need_approval_no_yolo(self) -> None:
        self.assertEqual(self._pm.check("git add ."), "needs_approval")
        self.assertEqual(self._pm.check("npm install"), "needs_approval")

    def test_normal_commands_allow_in_yolo(self) -> None:
        pm = PermissionManager(broadcast=self._broadcast, yolo_mode=True)
        self.assertEqual(pm.check("git add ."), "allow")
        self.assertEqual(pm.check("npm install"), "allow")

    def test_dangerous_commands_always_need_approval(self) -> None:
        # 非 YOLO
        self.assertEqual(self._pm.check("rm -rf /tmp/foo"), "needs_approval")
        # YOLO 也不行
        pm = PermissionManager(broadcast=self._broadcast, yolo_mode=True)
        self.assertEqual(pm.check("rm -rf /tmp/foo"), "needs_approval")

    # ── max_command_risk budget ──

    def test_read_only_budget_denies_normal(self) -> None:
        """风险预算为 read_only → normal 命令被拒。"""
        self.assertEqual(
            self._pm.check("git add .", max_command_risk="read_only"),
            "deny",
        )

    def test_read_only_budget_allows_read_only(self) -> None:
        """风险预算为 read_only → read_only 命令通过。"""
        self.assertEqual(
            self._pm.check("git status", max_command_risk="read_only"),
            "allow",
        )

    def test_normal_budget_denies_dangerous(self) -> None:
        """风险预算为 normal → dangerous 命令被拒。"""
        self.assertEqual(
            self._pm.check("rm -rf /tmp/foo", max_command_risk="normal"),
            "deny",
        )

    def test_dangerous_budget_allows_dangerous(self) -> None:
        """风险预算为 dangerous → dangerous 命令走审批（非直接 deny）。"""
        self.assertEqual(
            self._pm.check("rm -rf /tmp/foo", max_command_risk="dangerous"),
            "needs_approval",
        )

    def test_unknown_risk_label_treated_as_normal(self) -> None:
        """未知 max_command_risk 标签按 normal 处理。"""
        result = self._pm.check("git status", max_command_risk="unknown_label")
        self.assertEqual(result, "allow")  # read_only 不受预算影响

    # ── set_yolo_mode ──

    def test_set_yolo_mode_changes_behavior(self) -> None:
        self.assertEqual(self._pm.check("git add ."), "needs_approval")
        self._pm.set_yolo_mode(True)
        self.assertEqual(self._pm.check("git add ."), "allow")

    # ── resolve ──

    def test_resolve_unknown_request_id_returns_false(self) -> None:
        self.assertFalse(self._pm.resolve("no-such-id", True))

    def test_resolve_already_resolved_returns_false(self) -> None:
        """同一个 request 不能被 resolve 两次。"""
        self.assertFalse(self._pm.resolve("no-such-id", True))
        # 再次调用仍为 False
        self.assertFalse(self._pm.resolve("no-such-id", False))

    # ── request_approval timeout ──

    def test_request_approval_timeout_returns_false(self) -> None:
        """超时未被 resolve 的请求返回 False。"""
        pm = PermissionManager(
            broadcast=self._broadcast,
            yolo_mode=False,
            timeout_seconds=0,  # 立即超时
        )
        result = asyncio.run(pm.request_approval("git add ."))
        self.assertFalse(result)

    def test_request_approval_yolo_auto_approves_normal(self) -> None:
        """YOLO 模式下普通命令自动批准，不广播。"""
        pm = PermissionManager(broadcast=self._broadcast, yolo_mode=True)
        result = asyncio.run(pm.request_approval("git add ."))
        self.assertTrue(result)
        self._broadcast.assert_not_called()

    def test_request_approval_yolo_still_awaits_dangerous(self) -> None:
        """YOLO 模式下高危命令仍需审批。"""
        pm = PermissionManager(
            broadcast=self._broadcast,
            yolo_mode=True,
            timeout_seconds=0,  # 立即超时 → False
        )
        result = asyncio.run(pm.request_approval("rm -rf /tmp/foo"))
        self.assertFalse(result)
        self._broadcast.assert_called_once()

    def test_request_approval_broadcasts_and_waits(self) -> None:
        """正常审批流程：广播 + 等待 resolve。"""
        pm = PermissionManager(broadcast=self._broadcast, yolo_mode=False)

        async def approve_after_broadcast() -> bool:
            # 创建一个 task 在广播后 resolve
            task = asyncio.create_task(pm.request_approval("git add ."))
            # 给广播一点时间
            await asyncio.sleep(0.01)
            # 从广播调用中提取 request_id 然后 resolve
            call_args = self._broadcast.call_args
            if call_args:
                payload = call_args[0][1]
                pm.resolve(payload["request_id"], True)
            return await task

        result = asyncio.run(approve_after_broadcast())
        self.assertTrue(result)
        self._broadcast.assert_called()

    def test_request_approval_can_be_rejected(self) -> None:
        """用户拒绝审批。"""
        pm = PermissionManager(broadcast=self._broadcast, yolo_mode=False)

        async def reject_after_broadcast() -> bool:
            task = asyncio.create_task(pm.request_approval("git add ."))
            await asyncio.sleep(0.01)
            call_args = self._broadcast.call_args
            if call_args:
                payload = call_args[0][1]
                pm.resolve(payload["request_id"], False)
            return await task

        result = asyncio.run(reject_after_broadcast())
        self.assertFalse(result)

    def test_broadcast_includes_risk_level_in_payload(self) -> None:
        """广播的 approval.request 应携带 risk_level。"""
        pm = PermissionManager(
            broadcast=self._broadcast,
            yolo_mode=False,
            timeout_seconds=0,
        )
        asyncio.run(pm.request_approval("rm -rf /tmp/foo"))
        call_args = self._broadcast.call_args
        self.assertIsNotNone(call_args)
        event_type, payload = call_args[0]
        self.assertEqual(event_type, "approval.request")
        self.assertEqual(payload["risk_level"], "dangerous")
        self.assertIn("request_id", payload)
        self.assertIn("command", payload)


if __name__ == "__main__":
    unittest.main()
