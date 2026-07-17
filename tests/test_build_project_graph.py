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

    def test_common_dependency_build_and_cache_directories_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            for dirname in ("node_modules", "vendor", "dist", ".next", ".pytest_cache", "obj", "sample.egg-info"):
                directory = root / dirname
                directory.mkdir()
                (directory / "ignored.py").write_text("VALUE = 2\n", encoding="utf-8")

            code, _ = self.run_cli(root, root / ".project-graph")

            self.assertEqual(code, 0)
            nodes = json.loads((root / ".project-graph" / "nodes.json").read_text(encoding="utf-8"))
            node_ids = {node["id"] for node in nodes}
            self.assertIn("main.py", node_ids)
            self.assertFalse(any(node_id.endswith("ignored.py") for node_id in node_ids))

    def test_default_excludes_can_be_replaced_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".project-graph").mkdir()
            (root / ".project-graph" / "config.json").write_text(
                json.dumps({"use_default_excludes": False, "exclude_dirs": []}),
                encoding="utf-8",
            )
            (root / "node_modules").mkdir()
            (root / "node_modules" / "included.py").write_text("VALUE = 1\n", encoding="utf-8")

            code, _ = self.run_cli(root, root / ".project-graph")

            self.assertEqual(code, 0)
            nodes = json.loads((root / ".project-graph" / "nodes.json").read_text(encoding="utf-8"))
            self.assertIn("node_modules/included.py", {node["id"] for node in nodes})

    def test_custom_excludes_extend_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".project-graph").mkdir()
            (root / ".project-graph" / "config.json").write_text(
                json.dumps({"exclude_dirs": ["fixtures"]}),
                encoding="utf-8",
            )
            for dirname in ("node_modules", "fixtures"):
                directory = root / dirname
                directory.mkdir()
                (directory / "ignored.py").write_text("VALUE = 2\n", encoding="utf-8")
            (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")

            code, _ = self.run_cli(root, root / ".project-graph")

            self.assertEqual(code, 0)
            nodes = json.loads((root / ".project-graph" / "nodes.json").read_text(encoding="utf-8"))
            node_ids = {node["id"] for node in nodes}
            self.assertIn("main.py", node_ids)
            self.assertFalse(any(node_id.endswith("ignored.py") for node_id in node_ids))

    def test_adds_test_and_config_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "src" / "math.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            (root / "tests" / "test_math.py").write_text("from src.math import add\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")

            code, _ = self.run_cli(root, root / ".project-graph")

            self.assertEqual(code, 0)
            nodes = json.loads((root / ".project-graph" / "nodes.json").read_text(encoding="utf-8"))
            edges = json.loads((root / ".project-graph" / "edges.json").read_text(encoding="utf-8"))
            self.assertIn(
                {"source": "tests/test_math.py", "target": "src/math.py", "type": "tests"},
                edges,
            )
            self.assertIn(
                {"source": "pyproject.toml", "target": ".", "type": "configures"},
                edges,
            )
            roles = {node["id"]: node.get("role") for node in nodes}
            self.assertEqual(roles["tests/test_math.py"], "test")
            self.assertEqual(roles["pyproject.toml"], "config")

    def test_adds_frontend_route_and_render_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            (root / "src" / "App.tsx").write_text(
                "import Home from './Home'\n"
                "export function App() {\n"
                "  return <Route path=\"/\" element={<Home />} />\n"
                "}\n",
                encoding="utf-8",
            )
            (root / "src" / "Home.tsx").write_text("export default function Home() { return <main /> }\n", encoding="utf-8")

            code, _ = self.run_cli(root, root / ".project-graph")

            self.assertEqual(code, 0)
            nodes = json.loads((root / ".project-graph" / "nodes.json").read_text(encoding="utf-8"))
            edges = json.loads((root / ".project-graph" / "edges.json").read_text(encoding="utf-8"))
            self.assertIn({"id": "route:/", "type": "route", "label": "/"}, nodes)
            self.assertIn(
                {"source": "src/App.tsx", "target": "route:/", "type": "declares-route"},
                edges,
            )
            self.assertIn(
                {"source": "route:/", "target": "src/Home.tsx", "type": "renders"},
                edges,
            )

    def test_package_scripts_link_to_local_entrypoints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "scripts").mkdir()
            (root / "scripts" / "seed.ts").write_text("console.log('seed')\n", encoding="utf-8")
            (root / "package.json").write_text(
                json.dumps({"scripts": {"seed": "tsx scripts/seed.ts"}}),
                encoding="utf-8",
            )

            code, _ = self.run_cli(root, root / ".project-graph")

            self.assertEqual(code, 0)
            edges = json.loads((root / ".project-graph" / "edges.json").read_text(encoding="utf-8"))
            self.assertIn(
                {"source": "package.json", "target": "scripts/seed.ts", "type": "runs"},
                edges,
            )

    def test_fingerprint_detects_deleted_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / ".project-graph"
            (root / "main.py").write_text("import util\n", encoding="utf-8")
            (root / "util.py").write_text("VALUE = 1\n", encoding="utf-8")
            self.run_cli(root, output)
            (root / "util.py").unlink()

            code, console = self.run_cli(root, output)

            self.assertEqual(code, 0)
            self.assertIn("Wrote graph artifacts", console)
            nodes = json.loads((output / "nodes.json").read_text(encoding="utf-8"))
            self.assertNotIn("util.py", {node["id"] for node in nodes})

    def test_incremental_refresh_reuses_unchanged_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / ".project-graph"
            (root / "main.py").write_text("import util\n", encoding="utf-8")
            (root / "util.py").write_text("VALUE = 1\n", encoding="utf-8")
            self.run_cli(root, output)
            (root / "util.py").write_text("VALUE = 200\n", encoding="utf-8")

            code, _ = self.run_cli(root, output)

            self.assertEqual(code, 0)
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["parsed_file_count"], 1)
            self.assertEqual(manifest["reused_file_count"], 1)

    def test_python_ast_extracts_relative_imports_symbols_and_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "pkg").mkdir()
            (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
            (root / "pkg" / "util.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
            (root / "pkg" / "service.py").write_text(
                "from .util import helper\nclass Service:\n    def run(self):\n        return helper()\n",
                encoding="utf-8",
            )

            code, _ = self.run_cli(root, root / ".project-graph")

            self.assertEqual(code, 0)
            nodes = json.loads((root / ".project-graph" / "nodes.json").read_text(encoding="utf-8"))
            edges = json.loads((root / ".project-graph" / "edges.json").read_text(encoding="utf-8"))
            service = next(node for node in nodes if node["id"] == "pkg/service.py")
            self.assertIn("Service", service["symbols"])
            self.assertIn("run", service["symbols"])
            self.assertIn("helper", service["calls"])
            self.assertIn({"source": "pkg/service.py", "target": "pkg/util.py", "type": "imports"}, edges)

    def test_resolves_tsconfig_alias_and_workspace_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src" / "lib").mkdir(parents=True)
            (root / "packages" / "core" / "src").mkdir(parents=True)
            (root / "tsconfig.json").write_text(
                json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}}),
                encoding="utf-8",
            )
            (root / "src" / "lib" / "tool.ts").write_text("export const tool = () => 1\n", encoding="utf-8")
            (root / "packages" / "core" / "package.json").write_text(
                json.dumps({"name": "@scope/core", "source": "src/index.ts"}),
                encoding="utf-8",
            )
            (root / "packages" / "core" / "src" / "index.ts").write_text("export const core = 1\n", encoding="utf-8")
            (root / "src" / "main.ts").write_text(
                "import { tool } from '@/lib/tool'\nimport { core } from '@scope/core'\n",
                encoding="utf-8",
            )

            code, _ = self.run_cli(root, root / ".project-graph")

            self.assertEqual(code, 0)
            edges = json.loads((root / ".project-graph" / "edges.json").read_text(encoding="utf-8"))
            self.assertIn({"source": "src/main.ts", "target": "src/lib/tool.ts", "type": "imports"}, edges)
            self.assertIn(
                {"source": "src/main.ts", "target": "packages/core/src/index.ts", "type": "imports"},
                edges,
            )

    def test_cycle_path_and_layer_violation_queries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".project-graph").mkdir()
            (root / "ui").mkdir()
            (root / "domain").mkdir()
            (root / ".project-graph" / "config.json").write_text(
                json.dumps(
                    {
                        "layers": [
                            {"name": "ui", "patterns": ["ui/**"], "may_import": []},
                            {"name": "domain", "patterns": ["domain/**"], "may_import": []},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (root / "ui" / "view.py").write_text("import domain.model\n", encoding="utf-8")
            (root / "domain" / "__init__.py").write_text("", encoding="utf-8")
            (root / "domain" / "model.py").write_text("import ui.view\n", encoding="utf-8")

            cycle_code, cycle_output = self.run_cli(root, root / ".project-graph", "--cycles")
            violation_code, violation_output = self.run_cli(root, root / ".project-graph", "--violations")
            path_code, path_output = self.run_cli(
                root, root / ".project-graph", "--path", "ui/view.py", "domain/model.py"
            )

            self.assertEqual((cycle_code, violation_code, path_code), (0, 0, 0))
            self.assertIn("Circular Import Components", cycle_output)
            self.assertIn("ui/view.py", cycle_output)
            self.assertIn("Architecture Layer Violations", violation_output)
            self.assertIn("allowed: none", violation_output)
            self.assertIn("imports", path_output)

    def test_respects_gitignore_when_git_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            try:
                subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
            except (OSError, subprocess.SubprocessError):
                self.skipTest("Git is unavailable")
            (root / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
            (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "ignored.py").write_text("VALUE = 2\n", encoding="utf-8")

            code, _ = self.run_cli(root, root / ".project-graph")

            self.assertEqual(code, 0)
            nodes = json.loads((root / ".project-graph" / "nodes.json").read_text(encoding="utf-8"))
            node_ids = {node["id"] for node in nodes}
            self.assertIn("main.py", node_ids)
            self.assertNotIn("ignored.py", node_ids)

    def test_git_diff_impact_and_hotspot_queries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            try:
                subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(root), "config", "user.email", "tests@example.com"], check=True)
                subprocess.run(["git", "-C", str(root), "config", "user.name", "Tests"], check=True)
            except (OSError, subprocess.SubprocessError):
                self.skipTest("Git is unavailable")
            (root / ".gitignore").write_text(".project-graph/\n", encoding="utf-8")
            (root / "main.py").write_text("import util\n", encoding="utf-8")
            (root / "util.py").write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "initial"], check=True)
            (root / "util.py").write_text("VALUE = 2\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "util.py"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "change util"], check=True)

            impact_code, impact_output = self.run_cli(
                root, root / ".project-graph", "--impact-diff", "HEAD~1"
            )
            hotspot_code, hotspot_output = self.run_cli(root, root / ".project-graph", "--hotspots")

            self.assertEqual((impact_code, hotspot_code), (0, 0))
            self.assertIn("util.py", impact_output)
            self.assertIn("1 dependent", impact_output)
            self.assertIn("Git × Dependency Hotspots", hotspot_output)
            self.assertIn("util.py", hotspot_output)


if __name__ == "__main__":
    unittest.main()
