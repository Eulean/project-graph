from __future__ import annotations

import io
import json
import subprocess
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

    def test_entrypoints_and_missing_tests_queries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "app.py").write_text("print('hello')\n", encoding="utf-8")
            (root / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests" / "test_app.py").write_text("def test_app(): pass\n", encoding="utf-8")

            entry_code, entry_output = self.run_cli(root, root / ".project-graph", "--entrypoints")
            test_code, test_output = self.run_cli(root, root / ".project-graph", "--missing-tests")

            self.assertEqual(entry_code, 0)
            self.assertIn("`app.py`", entry_output)
            self.assertEqual(test_code, 0)
            self.assertIn("`service.py`", test_output)
            self.assertNotIn("`app.py`", test_output)

    def test_docs_for_and_owners_queries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            (root / "CODEOWNERS").write_text("app/* @team/app\n", encoding="utf-8")
            (root / "app").mkdir()
            (root / "app" / "README.md").write_text("# App\n", encoding="utf-8")
            (root / "app" / "service.py").write_text("VALUE = 1\n", encoding="utf-8")

            docs_code, docs_output = self.run_cli(root, root / ".project-graph", "--docs-for", "app/service.py")
            owners_code, owners_output = self.run_cli(root, root / ".project-graph", "--owners")

            self.assertEqual(docs_code, 0)
            self.assertIn("`README.md`", docs_output)
            self.assertIn("`app/README.md`", docs_output)
            self.assertEqual(owners_code, 0)
            self.assertIn("`app/service.py` -> @team/app", owners_output)

    def test_read_next_why_confidence_and_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            (root / "main.py").write_text("import util\n", encoding="utf-8")
            (root / "util.py").write_text("VALUE = 1\n", encoding="utf-8")
            bundle_dir = root / "bundle"

            read_code, read_output = self.run_cli(root, root / ".project-graph", "--read-next", "main.py")
            why_code, why_output = self.run_cli(root, root / ".project-graph", "--why", "util.py")
            confidence_code, confidence_output = self.run_cli(root, root / ".project-graph", "--confidence")
            bundle_code, bundle_output = self.run_cli(root, root / ".project-graph", "--export-bundle", str(bundle_dir), "--bundle-for", "main.py")

            self.assertEqual(read_code, 0)
            self.assertIn("`util.py` - imported by target", read_output)
            self.assertEqual(why_code, 0)
            self.assertIn("`main.py` imports `util.py`", why_output)
            self.assertEqual(confidence_code, 0)
            self.assertIn("Graph Confidence", confidence_output)
            self.assertEqual(bundle_code, 0)
            self.assertIn("Export Bundle", bundle_output)
            self.assertTrue((bundle_dir / "prompt.md").exists())

    def test_inventory_hash_detects_deleted_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            doomed = root / "doomed.py"
            doomed.write_text("VALUE = 1\n", encoding="utf-8")

            first_code, _ = self.run_cli(root, root / ".project-graph")
            doomed.unlink()
            second_code, _ = self.run_cli(root, root / ".project-graph")

            self.assertEqual(first_code, 0)
            self.assertEqual(second_code, 0)
            nodes = json.loads((root / ".project-graph" / "nodes.json").read_text(encoding="utf-8"))
            self.assertNotIn("doomed.py", {node["id"] for node in nodes})
            manifest = json.loads((root / ".project-graph" / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("source_inventory_hash", manifest)

    def test_risk_and_mermaid_queries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "main.py").write_text("import util\n", encoding="utf-8")
            (root / "util.py").write_text("VALUE = 1\n", encoding="utf-8")

            risk_code, risk_output = self.run_cli(root, root / ".project-graph", "--risk", "util.py")
            mermaid_code, mermaid_output = self.run_cli(root, root / ".project-graph", "--around", "main.py", "--format", "mermaid")

            self.assertEqual(risk_code, 0)
            self.assertIn("Change Risk For `util.py`", risk_output)
            self.assertIn("risk (score", risk_output)
            self.assertEqual(mermaid_code, 0)
            self.assertIn("```mermaid", mermaid_output)
            self.assertIn("-->|imports|", mermaid_output)

    def test_changed_since_reports_git_diff_impact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            (root / "main.py").write_text("import util\n", encoding="utf-8")
            (root / "util.py").write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=root, check=True, capture_output=True)
            (root / "util.py").write_text("VALUE = 2\n", encoding="utf-8")

            code, output = self.run_cli(root, root / ".project-graph", "--changed-since", "HEAD", "--limit", "5")

            self.assertEqual(code, 0)
            self.assertIn("Changed Since `HEAD`", output)
            self.assertIn("`util.py` changed", output)
            self.assertIn("`main.py` imports changed `util.py`", output)


if __name__ == "__main__":
    unittest.main()
