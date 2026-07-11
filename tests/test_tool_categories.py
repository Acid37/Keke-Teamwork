"""Tests for tool category registration and classification helpers."""

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
    """Verify every tool has a category and the classification helpers work."""

    def test_every_tool_has_category(self) -> None:
        """All registered tools must declare a ToolCategory."""
        for cls in ALL_TOOLS:
            self.assertIsInstance(
                cls.category,
                ToolCategory,
                f"{cls.__name__}.category must be a ToolCategory, got {cls.category!r}",
            )

    def test_category_tools_mapping_covers_all_tools(self) -> None:
        """Every tool name in TOOL_REGISTRY should appear in CATEGORY_TOOLS."""
        all_categorized = set()
        for names in CATEGORY_TOOLS.values():
            all_categorized |= set(names)
        self.assertEqual(all_categorized, set(TOOL_REGISTRY.keys()))

    def test_search_category_contains_read_only_tools(self) -> None:
        """search category should include read_file, grep_search, find_files, list_directory."""
        search_tools = tools_in_category(ToolCategory.search)
        for name in ("read_file", "grep_search", "find_files", "list_directory"):
            self.assertIn(name, search_tools)

    def test_file_category_contains_write_tools(self) -> None:
        """file category should include write_file and edit_file."""
        file_tools = tools_in_category(ToolCategory.file)
        self.assertIn("write_file", file_tools)
        self.assertIn("edit_file", file_tools)

    def test_shell_category_contains_console(self) -> None:
        """shell category should include run_console."""
        self.assertIn("run_console", tools_in_category(ToolCategory.shell))

    def test_coding_category_contains_delegate(self) -> None:
        """coding category should include delegate_agent."""
        self.assertIn("delegate_agent", tools_in_category(ToolCategory.coding))

    def test_mcp_category_is_empty_for_now(self) -> None:
        """mcp category is reserved and should have no tools yet."""
        self.assertEqual(len(tools_in_category(ToolCategory.mcp)), 0)

    def test_write_categories_are_file_and_shell(self) -> None:
        """Only file and shell categories are considered write-capable."""
        self.assertEqual(WRITE_CATEGORIES, frozenset({ToolCategory.file, ToolCategory.shell}))

    def test_is_read_only_tool_set_with_search_tools(self) -> None:
        """A tool set with only search-category tools is read-only."""
        self.assertTrue(is_read_only_tool_set(["read_file", "grep_search", "find_files"]))

    def test_is_read_only_tool_set_with_write_tool(self) -> None:
        """A tool set containing a file tool is NOT read-only."""
        self.assertFalse(is_read_only_tool_set(["read_file", "write_file"]))

    def test_is_read_only_tool_set_with_shell_tool(self) -> None:
        """A tool set containing a shell tool is NOT read-only."""
        self.assertFalse(is_read_only_tool_set(["read_file", "run_console"]))

    def test_is_read_only_tool_set_with_coding_tool(self) -> None:
        """delegate_agent (coding category) alone is read-only (no side effects)."""
        self.assertTrue(is_read_only_tool_set(["delegate_agent"]))

    def test_is_read_only_tool_set_empty(self) -> None:
        """An empty tool set is trivially read-only."""
        self.assertTrue(is_read_only_tool_set([]))

    def test_has_write_tool_with_file(self) -> None:
        self.assertTrue(has_write_tool(["read_file", "edit_file"]))

    def test_has_write_tool_with_shell(self) -> None:
        self.assertTrue(has_write_tool(["run_console"]))

    def test_has_write_tool_without_write(self) -> None:
        self.assertFalse(has_write_tool(["read_file", "grep_search", "delegate_agent"]))

    def test_resolve_tools_returns_classes(self) -> None:
        """resolve_tools should return Tool subclasses for known names."""
        classes = resolve_tools(["read_file", "grep_search"])
        self.assertEqual(len(classes), 2)
        self.assertTrue(all(issubclass(c, Tool) for c in classes))

    def test_resolve_tools_skips_unknown(self) -> None:
        """resolve_tools should silently skip unknown tool names."""
        classes = resolve_tools(["read_file", "nonexistent_tool"])
        self.assertEqual(len(classes), 1)


if __name__ == "__main__":
    unittest.main()