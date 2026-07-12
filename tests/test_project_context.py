"""项目上下文构建测试。

验证 build_project_context 能正确识别语言、框架和目录结构。
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.context_builder import build_project_context


class ProjectContextTests(unittest.TestCase):
    def test_detects_python_project(self):
        """应识别 pyproject.toml 为 Python 项目。"""
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "pyproject.toml").write_text(
                '[project]\nname = "test"\ndependencies = ["fastapi", "pydantic"]\n',
                encoding="utf-8",
            )
            ctx = build_project_context(Path(tmp))
            self.assertIn("python", ctx["languages"])
            self.assertIn("fastapi", ctx["frameworks"])
            self.assertIn("pydantic", ctx["frameworks"])

    def test_detects_typescript_project(self):
        """应识别 package.json + tsconfig.json 为 TypeScript 项目。"""
        with TemporaryDirectory() as tmp:
            import json
            (Path(tmp) / "package.json").write_text(json.dumps({
                "dependencies": {"react": "^18.0.0", "vite": "^5.0.0"},
            }), encoding="utf-8")
            (Path(tmp) / "tsconfig.json").write_text("{}", encoding="utf-8")
            ctx = build_project_context(Path(tmp))
            self.assertIn("javascript", ctx["languages"])
            self.assertIn("typescript", ctx["languages"])
            self.assertIn("react", ctx["frameworks"])
            self.assertIn("vite", ctx["frameworks"])

    def test_detects_go_project(self):
        """应识别 go.mod 为 Go 项目。"""
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "go.mod").write_text("module example.com/test\n\ngo 1.21\n", encoding="utf-8")
            ctx = build_project_context(Path(tmp))
            self.assertIn("go", ctx["languages"])

    def test_structure_contains_files(self):
        """目录结构摘要应包含项目文件。"""
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "main.py").write_text("# entry", encoding="utf-8")
            (Path(tmp) / "README.md").write_text("# test", encoding="utf-8")
            ctx = build_project_context(Path(tmp))
            self.assertIn("main.py", ctx["structure"])
            self.assertIn("README.md", ctx["structure"])

    def test_skips_ignored_dirs(self):
        """应跳过 node_modules、__pycache__ 等目录。"""
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "main.py").write_text("", encoding="utf-8")
            (Path(tmp) / "node_modules").mkdir()
            (Path(tmp) / "node_modules" / "lib.js").write_text("", encoding="utf-8")
            ctx = build_project_context(Path(tmp))
            self.assertNotIn("node_modules", ctx["structure"])

    def test_summary_contains_language_info(self):
        """摘要文本应包含语言信息。"""
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "pyproject.toml").write_text(
                '[project]\nname = "test"\n', encoding="utf-8")
            ctx = build_project_context(Path(tmp))
            self.assertIn("python", ctx["summary"])

    def test_empty_dir_returns_empty_languages(self):
        """空目录应返回空语言列表。"""
        with TemporaryDirectory() as tmp:
            ctx = build_project_context(Path(tmp))
            self.assertEqual(ctx["languages"], [])

    def test_mixed_project_detects_both(self):
        """Python + TypeScript 混合项目应同时识别两种语言。"""
        with TemporaryDirectory() as tmp:
            import json
            (Path(tmp) / "pyproject.toml").write_text(
                '[project]\nname = "test"\ndependencies = ["fastapi"]\n', encoding="utf-8")
            (Path(tmp) / "package.json").write_text(json.dumps({
                "dependencies": {"react": "^18.0.0"},
            }), encoding="utf-8")
            ctx = build_project_context(Path(tmp))
            self.assertIn("python", ctx["languages"])
            self.assertIn("javascript", ctx["languages"])
            self.assertIn("fastapi", ctx["frameworks"])
            self.assertIn("react", ctx["frameworks"])


if __name__ == "__main__":
    unittest.main()