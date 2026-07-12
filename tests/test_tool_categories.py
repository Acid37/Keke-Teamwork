"""工具分类注册和分流辅助函数的测试。"""

import unittest

from backend.tools.base import Tool, ToolCategory
from backend.tools import (
    ALL_TOOLS,
    TOOL_REGISTRY,
    CATEGORY_TOOLS,
    WRITE_CATEGORIES,
    resolve_tools,
    tools_in_category,
    is_read_only_tool_set,
    has_write_tool,
)


class ToolCategoryTests(unittest.TestCase):
    """验证每个工具都有分类，且分流辅助函数正常工作。"""

    def test_every_tool_has_category(self) -> None:
        """所有已注册工具必须声明 ToolCategory。"""
        for cls in ALL_TOOLS:
            self.assertIsInstance(
                cls.category,
                ToolCategory,
                f"{cls.__name__}.category must be a ToolCategory, got {cls.category!r}",
            )

    def test_category_tools_mapping_covers_all_tools(self) -> None:
        """TOOL_REGISTRY 中的每个工具名都应出现在 CATEGORY_TOOLS 中。"""
        all_categorized = set()
        for names in CATEGORY_TOOLS.values():
            all_categorized |= set(names)
        self.assertEqual(all_categorized, set(TOOL_REGISTRY.keys()))

    def test_search_category_contains_read_only_tools(self) -> None:
        """search 分类应包含 read_file、grep_search、find_files、list_directory。"""
        search_tools = tools_in_category(ToolCategory.search)
        for name in ("read_file", "grep_search", "find_files", "list_directory"):
            self.assertIn(name, search_tools)

    def test_file_category_contains_write_tools(self) -> None:
        """file 分类应包含 write_file 和 edit_file。"""
        file_tools = tools_in_category(ToolCategory.file)
        self.assertIn("write_file", file_tools)
        self.assertIn("edit_file", file_tools)

    def test_shell_category_contains_console(self) -> None:
        """shell 分类应包含 run_console。"""
        self.assertIn("run_console", tools_in_category(ToolCategory.shell))

    def test_coding_category_contains_delegate(self) -> None:
        """coding 分类应包含 delegate_agent。"""
        self.assertIn("delegate_agent", tools_in_category(ToolCategory.coding))

    def test_mcp_category_is_empty_for_now(self) -> None:
        """mcp 分类为保留分类，目前应无任何工具。"""
        self.assertEqual(len(tools_in_category(ToolCategory.mcp)), 0)

    def test_write_categories_are_file_and_shell(self) -> None:
        """只有 file 和 shell 分类被视为可写。"""
        self.assertEqual(WRITE_CATEGORIES, frozenset({ToolCategory.file, ToolCategory.shell}))

    def test_is_read_only_tool_set_with_search_tools(self) -> None:
        """仅包含 search 分类工具的工具集为只读。"""
        self.assertTrue(is_read_only_tool_set(["read_file", "grep_search", "find_files"]))

    def test_is_read_only_tool_set_with_write_tool(self) -> None:
        """包含 file 工具的工具集不是只读。"""
        self.assertFalse(is_read_only_tool_set(["read_file", "write_file"]))

    def test_is_read_only_tool_set_with_shell_tool(self) -> None:
        """包含 shell 工具的工具集不是只读。"""
        self.assertFalse(is_read_only_tool_set(["read_file", "run_console"]))

    def test_is_read_only_tool_set_with_coding_tool(self) -> None:
        """仅 delegate_agent（coding 分类）为只读（无副作用）。"""
        self.assertTrue(is_read_only_tool_set(["delegate_agent"]))

    def test_is_read_only_tool_set_empty(self) -> None:
        """空工具集显然为只读。"""
        self.assertTrue(is_read_only_tool_set([]))

    def test_has_write_tool_with_file(self) -> None:
        self.assertTrue(has_write_tool(["read_file", "edit_file"]))

    def test_has_write_tool_with_shell(self) -> None:
        self.assertTrue(has_write_tool(["run_console"]))

    def test_has_write_tool_without_write(self) -> None:
        self.assertFalse(has_write_tool(["read_file", "grep_search", "delegate_agent"]))

    def test_resolve_tools_returns_classes(self) -> None:
        """resolve_tools 应对已知名称返回 Tool 子类。"""
        classes = resolve_tools(["read_file", "grep_search"])
        self.assertEqual(len(classes), 2)
        self.assertTrue(all(issubclass(c, Tool) for c in classes))

    def test_resolve_tools_skips_unknown(self) -> None:
        """resolve_tools 应静默跳过未知的工具名。"""
        classes = resolve_tools(["read_file", "nonexistent_tool"])
        self.assertEqual(len(classes), 1)


if __name__ == "__main__":
    unittest.main()