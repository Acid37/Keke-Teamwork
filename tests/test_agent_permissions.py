"""per-agent 细粒度权限测试。

覆盖：AgentPermissions 序列化、路径权限检查、
命令风险预算、委派/ handoff 控制。
"""

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.types import AgentDefinition, AgentPermissions
from backend.safety.path_guard import (
    check_agent_path_permissions,
    AgentPathDeniedError,
    resolve_path,
)
from backend.safety.permission import PermissionManager


# ─── AgentPermissions 序列化 ───


class AgentPermissionsSerializationTests(unittest.TestCase):
    """AgentPermissions 和 AgentDefinition 的序列化往返。"""

    def test_permissions_to_dict_and_back(self) -> None:
        perms = AgentPermissions(
            allowed_paths=["src/**"],
            denied_paths=["**/*.secret.*"],
            max_command_risk="read_only",
            allow_delegation=False,
            allow_handoff=True,
        )
        d = perms.to_dict()
        restored = AgentPermissions.from_dict(d)
        self.assertEqual(restored.allowed_paths, ["src/**"])
        self.assertEqual(restored.denied_paths, ["**/*.secret.*"])
        self.assertEqual(restored.max_command_risk, "read_only")
        self.assertFalse(restored.allow_delegation)
        self.assertTrue(restored.allow_handoff)

    def test_permissions_from_dict_none(self) -> None:
        self.assertIsNone(AgentPermissions.from_dict(None))

    def test_agent_definition_roundtrip_with_permissions(self) -> None:
        agent = AgentDefinition(
            agent_id="test",
            name="测试",
            role="tester",
            tools=["read_file", "grep_search"],
            permissions=AgentPermissions(
                max_command_risk="read_only",
                allow_delegation=False,
            ),
        )
        d = agent.to_dict()
        restored = AgentDefinition.from_dict(d)
        self.assertEqual(restored.permissions.max_command_risk, "read_only")
        self.assertFalse(restored.permissions.allow_delegation)

    def test_agent_definition_roundtrip_without_permissions(self) -> None:
        agent = AgentDefinition(
            agent_id="test",
            name="测试",
            role="tester",
            tools=["read_file"],
            permissions=None,
        )
        d = agent.to_dict()
        self.assertIsNone(d.get("permissions"))
        restored = AgentDefinition.from_dict(d)
        self.assertIsNone(restored.permissions)

    def test_agent_definition_from_dict_without_permissions_key(self) -> None:
        """旧格式 agents.json 没有 permissions 字段，解析后应为 None。"""
        restored = AgentDefinition.from_dict({
            "agent_id": "old",
            "name": "旧Agent",
            "role": "legacy",
            "tools": ["read_file"],
        })
        self.assertIsNone(restored.permissions)

    def test_default_permissions_values(self) -> None:
        """默认 AgentPermissions 无任何限制。"""
        perms = AgentPermissions()
        self.assertIsNone(perms.allowed_paths)
        self.assertIsNone(perms.denied_paths)
        self.assertEqual(perms.max_command_risk, "dangerous")
        self.assertTrue(perms.allow_delegation)
        self.assertTrue(perms.allow_handoff)


# ─── 路径权限检查 ───


class AgentPathPermissionTests(unittest.TestCase):
    """check_agent_path_permissions 的各种场景。"""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.work_dir = Path(self.tmp.name).resolve()
        (self.work_dir / "src").mkdir()
        (self.work_dir / "tests").mkdir()
        (self.work_dir / "config").mkdir()
        (self.work_dir / "src" / "app.py").write_text("# app")
        (self.work_dir / "config" / "secret.env").write_text("KEY=xxx")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # ── None permissions = no restriction ──

    def test_none_permissions_always_allows(self) -> None:
        """permissions=None 时任何路径都应放行（向后兼容）。"""
        for p in ["src/app.py", "config/secret.env", "tests/"]:
            resolved = resolve_path(p, self.work_dir)
            check_agent_path_permissions(resolved, self.work_dir, None)  # 不抛异常 = 通过

    # ── allowed_paths ──

    def test_allowed_paths_permits_matching(self) -> None:
        perms = AgentPermissions(allowed_paths=["src/**"])
        resolved = resolve_path("src/app.py", self.work_dir)
        check_agent_path_permissions(resolved, self.work_dir, perms)

    def test_allowed_paths_denies_non_matching(self) -> None:
        perms = AgentPermissions(allowed_paths=["src/**"])
        resolved = resolve_path("config/secret.env", self.work_dir)
        with self.assertRaises(AgentPathDeniedError):
            check_agent_path_permissions(resolved, self.work_dir, perms)

    def test_allowed_paths_multiple_patterns(self) -> None:
        perms = AgentPermissions(allowed_paths=["src/**", "tests/**"])
        for p in ["src/app.py", "tests/test_x.py"]:
            resolved = resolve_path(p, self.work_dir)
            check_agent_path_permissions(resolved, self.work_dir, perms)
        resolved = resolve_path("config/secret.env", self.work_dir)
        with self.assertRaises(AgentPathDeniedError):
            check_agent_path_permissions(resolved, self.work_dir, perms)

    # ── denied_paths ──

    def test_denied_paths_blocks_matching(self) -> None:
        perms = AgentPermissions(denied_paths=["config/*"])
        resolved = resolve_path("config/secret.env", self.work_dir)
        with self.assertRaises(AgentPathDeniedError):
            check_agent_path_permissions(resolved, self.work_dir, perms)

    def test_denied_paths_allows_non_matching(self) -> None:
        perms = AgentPermissions(denied_paths=["config/*"])
        resolved = resolve_path("src/app.py", self.work_dir)
        check_agent_path_permissions(resolved, self.work_dir, perms)

    def test_denied_overrides_allowed(self) -> None:
        """denied_paths 优先于 allowed_paths。"""
        perms = AgentPermissions(
            allowed_paths=["src/**"],
            denied_paths=["src/internal/**"],
        )
        # 创建 internal 子目录
        (self.work_dir / "src" / "internal").mkdir()
        (self.work_dir / "src" / "internal" / "private.py").write_text("# secret")
        (self.work_dir / "src" / "public.py").write_text("# public")

        resolved_pub = resolve_path("src/public.py", self.work_dir)
        check_agent_path_permissions(resolved_pub, self.work_dir, perms)

        resolved_priv = resolve_path("src/internal/private.py", self.work_dir)
        with self.assertRaises(AgentPathDeniedError):
            check_agent_path_permissions(resolved_priv, self.work_dir, perms)

    # ── glob patterns ──

    def test_glob_recursive_pattern(self) -> None:
        """** 应递归匹配所有子目录。"""
        perms = AgentPermissions(allowed_paths=["src/**/*.py"])
        (self.work_dir / "src" / "sub").mkdir()
        (self.work_dir / "src" / "sub" / "deep.py").write_text("# deep")

        resolved = resolve_path("src/sub/deep.py", self.work_dir)
        check_agent_path_permissions(resolved, self.work_dir, perms)

    def test_glob_extension_pattern(self) -> None:
        """*.py 应匹配目录内所有 .py 文件。"""
        perms = AgentPermissions(allowed_paths=["src/*.py"])
        resolved = resolve_path("src/app.py", self.work_dir)
        check_agent_path_permissions(resolved, self.work_dir, perms)

        # src/sub/deep.py 不应匹配 src/*.py
        (self.work_dir / "src" / "sub").mkdir()
        (self.work_dir / "src" / "sub" / "deep.py").write_text("# deep")
        resolved2 = resolve_path("src/sub/deep.py", self.work_dir)
        with self.assertRaises(AgentPathDeniedError):
            check_agent_path_permissions(resolved2, self.work_dir, perms)


# ─── 命令风险预算 ───


class PermissionManagerBudgetTests(unittest.TestCase):
    """PermissionManager.check() 的 max_command_risk 预算参数。"""

    def setUp(self) -> None:
        self.pm = PermissionManager(
            broadcast=lambda e, d: None,  # type: ignore[arg-type]
        )

    def test_default_budget_allows_normal(self) -> None:
        """默认 max_command_risk=dangerous，允许 normal 命令。"""
        self.assertEqual(self.pm.check("npm install"), "needs_approval")

    def test_read_only_budget_allows_read_only(self) -> None:
        """max_command_risk=read_only 应允许 read_only 命令。"""
        self.assertEqual(
            self.pm.check("ls", max_command_risk="read_only"), "allow"
        )

    def test_read_only_budget_denies_normal(self) -> None:
        """max_command_risk=read_only 应拒绝 normal 命令。"""
        self.assertEqual(
            self.pm.check("git add .", max_command_risk="read_only"), "deny"
        )

    def test_read_only_budget_denies_dangerous(self) -> None:
        """max_command_risk=read_only 应拒绝 dangerous 命令。"""
        self.assertEqual(
            self.pm.check("rm -rf /", max_command_risk="read_only"), "deny"
        )

    def test_normal_budget_denies_dangerous(self) -> None:
        """max_command_risk=normal 应拒绝 dangerous 命令。"""
        self.assertEqual(
            self.pm.check("rm -rf /", max_command_risk="normal"), "deny"
        )

    def test_dangerous_budget_needs_approval_for_dangerous(self) -> None:
        """max_command_risk=dangerous 应允许 dangerous 命令走审批。"""
        self.assertEqual(
            self.pm.check("rm -rf /", max_command_risk="dangerous"),
            "needs_approval",
        )


# ─── 异步审批流程不受影响 ───


class PermissionManagerAsyncTests(unittest.TestCase):
    """审批相关的异步方法不受风险预算影响。"""

    def setUp(self) -> None:
        self.pm = PermissionManager(
            broadcast=lambda e, d: None,  # type: ignore[arg-type]
            yolo_mode=False,
        )

    def test_yolo_allows_normal(self) -> None:
        pm = PermissionManager(
            broadcast=lambda e, d: None,  # type: ignore[arg-type]
            yolo_mode=True,
        )
        self.assertEqual(pm.check("npm install"), "allow")

    def test_dangerous_always_needs_approval(self) -> None:
        """危险命令即使在 YOLO 模式下也需要审批。"""
        pm = PermissionManager(
            broadcast=lambda e, d: None,  # type: ignore[arg-type]
            yolo_mode=True,
        )
        self.assertEqual(pm.check("rm -rf /"), "needs_approval")


# ─── 内置 Agent 权限预设 ───


class BuiltinAgentPermissionsTests(unittest.TestCase):
    """验证 agents.json 预设角色的权限配置。"""

    def _make_default_store(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from backend.agent_store import AgentStore

        self._tmp = TemporaryDirectory()
        return AgentStore(Path(self._tmp.name))

    def tearDown(self) -> None:
        if hasattr(self, "_tmp"):
            self._tmp.cleanup()

    def test_main_has_no_permissions(self) -> None:
        """main Agent 无权限限制（向后兼容）。"""
        store = self._make_default_store()
        agent = store.get_agent("main")
        self.assertIsNotNone(agent)
        self.assertIsNone(agent.permissions)

    def test_planner_is_read_only_and_can_delegate(self) -> None:
        """planner 只读、可委派、不可被 handoff。"""
        store = self._make_default_store()
        agent = store.get_agent("planner")
        self.assertIsNotNone(agent)
        self.assertEqual(agent.permissions.max_command_risk, "read_only")
        self.assertTrue(agent.permissions.allow_delegation)
        self.assertFalse(agent.permissions.allow_handoff)
        # 工具集应包含 delegate_agent 但不包含 write_file/edit_file/run_console
        self.assertIn("delegate_agent", agent.tools)
        self.assertNotIn("write_file", agent.tools)
        self.assertNotIn("run_console", agent.tools)

    def test_coder_has_write_tools_but_cannot_delegate(self) -> None:
        """coder 有写工具、不可委派、可被 handoff。"""
        store = self._make_default_store()
        agent = store.get_agent("coder")
        self.assertIsNotNone(agent)
        self.assertEqual(agent.permissions.max_command_risk, "normal")
        self.assertFalse(agent.permissions.allow_delegation)
        self.assertTrue(agent.permissions.allow_handoff)
        self.assertNotIn("delegate_agent", agent.tools)

    def test_reviewer_is_read_only_with_console(self) -> None:
        """reviewer 只读（有 run_console 但仅限只读命令）、不可委派、可被 handoff。"""
        store = self._make_default_store()
        agent = store.get_agent("reviewer")
        self.assertIsNotNone(agent)
        self.assertEqual(agent.permissions.max_command_risk, "read_only")
        self.assertFalse(agent.permissions.allow_delegation)
        self.assertTrue(agent.permissions.allow_handoff)
        # run_console 存在但受限为只读命令
        self.assertIn("run_console", agent.tools)
        self.assertNotIn("write_file", agent.tools)
