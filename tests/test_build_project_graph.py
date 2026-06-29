from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import build_project_graph


class BuildProjectGraphTests(unittest.TestCase):
    def run_cli(self, root: Path, output: Path, *extra_args: str) -> tuple[int, str]:
        args = ["build_project_graph.py", "--root", str(root), "--output", str(output), *extra_args]
        stdout = io.StringIO()
        with patch("sys.argv", args), redirect_stdout(stdout):
            code = build_project_graph.main()
        return code, stdout.getvalue()

    def test_builds_python_import_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "app").mkdir()
            (root / "app" / "__init__.py").write_text("", encoding="utf-8")
            (root / "app" / "main.py").write_text("from app.util import answer\n", encoding="utf-8")
            (root / "app" / "util.py").write_text("answer = 42\n", encoding="utf-8")

            code, _ = self.run_cli(root, root / ".project-graph")

            self.assertEqual(code, 0)
            edges = json.loads((root / ".project-graph" / "edges.json").read_text(encoding="utf-8"))
            self.assertIn(
                {"source": "app/main.py", "target": "app/util.py", "type": "imports"},
                edges,
            )

    def test_query_around_prints_compact_neighbors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "main.py").write_text("import util\n", encoding="utf-8")
            (root / "util.py").write_text("VALUE = 1\n", encoding="utf-8")

            code, output = self.run_cli(root, root / ".project-graph", "--around", "main.py", "--depth", "1")

            self.assertEqual(code, 0)
            self.assertIn("Local Graph Around `main.py`", output)
            self.assertIn("`main.py` --imports--> `util.py`", output)

    def test_query_impacted_follows_reverse_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "main.py").write_text("import util\n", encoding="utf-8")
            (root / "util.py").write_text("VALUE = 1\n", encoding="utf-8")

            code, output = self.run_cli(root, root / ".project-graph", "--impacted", "util.py")

            self.assertEqual(code, 0)
            self.assertIn("Likely Impact From `util.py`", output)
            self.assertIn("`main.py` imports `util.py`", output)

    def test_orphans_respects_excluded_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "node_modules").mkdir()
            (root / "lonely.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "node_modules" / "ignored.py").write_text("VALUE = 2\n", encoding="utf-8")

            code, output = self.run_cli(root, root / ".project-graph", "--orphans")

            self.assertEqual(code, 0)
            self.assertIn("`lonely.py`", output)
            self.assertNotIn("ignored.py", output)


if __name__ == "__main__":
    unittest.main()
