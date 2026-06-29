#!/usr/bin/env python3
"""
Build compact repository graph artifacts plus a lightweight HTML viewer.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


DEFAULT_INCLUDE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".rs",
    ".sql",
    ".ts",
    ".tsx",
    ".txt",
}

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".hg",
    ".idea",
    ".next",
    ".project-graph",
    ".svn",
    ".venv",
    ".vscode",
    "__pycache__",
    "bin",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "out",
    "target",
    "venv",
}

DEFAULT_EXCLUDE_GLOBS = {
    "*.generated.*",
    "*.min.js",
    "*.pyc",
    "*.snap",
}

DEFAULT_MAX_FILE_BYTES = 262_144

IMPORT_PATTERNS = {
    ".py": [
        re.compile(r"^\s*import\s+([a-zA-Z0-9_\.]+)", re.MULTILINE),
        re.compile(r"^\s*from\s+([a-zA-Z0-9_\.]+)\s+import\s+", re.MULTILINE),
    ],
    ".js": [
        re.compile(r'import\s+.*?\s+from\s+[\'"]([^\'"]+)[\'"]'),
        re.compile(r'require\([\'"]([^\'"]+)[\'"]\)'),
    ],
    ".jsx": [
        re.compile(r'import\s+.*?\s+from\s+[\'"]([^\'"]+)[\'"]'),
        re.compile(r'require\([\'"]([^\'"]+)[\'"]\)'),
    ],
    ".ts": [
        re.compile(r'import\s+.*?\s+from\s+[\'"]([^\'"]+)[\'"]'),
        re.compile(r'import\([\'"]([^\'"]+)[\'"]\)'),
        re.compile(r'require\([\'"]([^\'"]+)[\'"]\)'),
    ],
    ".tsx": [
        re.compile(r'import\s+.*?\s+from\s+[\'"]([^\'"]+)[\'"]'),
        re.compile(r'import\([\'"]([^\'"]+)[\'"]\)'),
        re.compile(r'require\([\'"]([^\'"]+)[\'"]\)'),
    ],
    ".go": [
        re.compile(r'^\s*"([^"]+)"\s*$', re.MULTILINE),
    ],
}

IMPORTABLE_SUFFIXES = {
    "",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    "/__init__.py",
    "/index.js",
    "/index.jsx",
    "/index.ts",
    "/index.tsx",
}


@dataclass
class Config:
    include_extensions: set[str]
    exclude_dirs: set[str]
    exclude_path_prefixes: set[str]
    exclude_globs: set[str]
    max_file_bytes: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build repository graph artifacts.")
    parser.add_argument("--root", required=True, help="Repository root to scan")
    parser.add_argument("--output", required=True, help="Directory for graph artifacts")
    parser.add_argument("--force", action="store_true", help="Rebuild even if graph looks fresh")
    parser.add_argument("--around", help="Print a compact local graph around this node id")
    parser.add_argument("--impacted", help="Print importers likely affected by changes to this node id")
    parser.add_argument("--orphans", action="store_true", help="Print files with no import edges")
    parser.add_argument("--central", action="store_true", help="Print highly connected files")
    parser.add_argument("--depth", type=int, default=2, help="Traversal depth for --around or --impacted")
    parser.add_argument("--limit", type=int, default=12, help="Maximum query rows to print")
    return parser.parse_args()


def load_config(root: Path) -> Config:
    config_path = root / ".project-graph" / "config.json"
    if not config_path.exists():
        return Config(
            include_extensions=set(DEFAULT_INCLUDE_EXTENSIONS),
            exclude_dirs=set(DEFAULT_EXCLUDE_DIRS),
            exclude_path_prefixes=set(),
            exclude_globs=set(DEFAULT_EXCLUDE_GLOBS),
            max_file_bytes=DEFAULT_MAX_FILE_BYTES,
        )

    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    return Config(
        include_extensions=set(raw.get("include_extensions", DEFAULT_INCLUDE_EXTENSIONS)),
        exclude_dirs=set(raw.get("exclude_dirs", DEFAULT_EXCLUDE_DIRS)),
        exclude_path_prefixes=set(raw.get("exclude_path_prefixes", [])),
        exclude_globs=set(raw.get("exclude_globs", DEFAULT_EXCLUDE_GLOBS)),
        max_file_bytes=int(raw.get("max_file_bytes", DEFAULT_MAX_FILE_BYTES)),
    )


def should_skip_dir(root: Path, path: Path, config: Config) -> bool:
    if path.name in config.exclude_dirs:
        return True
    rel = path.relative_to(root).as_posix()
    return any(rel == prefix or rel.startswith(f"{prefix}/") for prefix in config.exclude_path_prefixes)


def should_include_file(path: Path, config: Config) -> bool:
    if path.suffix.lower() not in config.include_extensions:
        return False
    for pattern in config.exclude_globs:
        if fnmatch.fnmatch(path.name, pattern):
            return False
    try:
        return path.stat().st_size <= config.max_file_bytes
    except OSError:
        return False


def iter_files(root: Path, config: Config) -> Iterable[Path]:
    for current_root, dirnames, filenames in os.walk(root):
        current_path = Path(current_root)
        dirnames[:] = [name for name in dirnames if not should_skip_dir(root, current_path / name, config)]
        for filename in filenames:
            file_path = current_path / filename
            if should_include_file(file_path, config):
                yield file_path


def relative_id(root: Path, path: Path) -> str:
    value = path.relative_to(root).as_posix()
    return value or "."


def build_folder_nodes(root: Path, file_nodes: list[dict]) -> list[dict]:
    folder_ids = {""}
    for node in file_nodes:
        rel = Path(node["id"])
        parent = rel.parent
        while str(parent) != ".":
            folder_ids.add(parent.as_posix())
            parent = parent.parent
        if rel.parent.as_posix() not in ("", "."):
            folder_ids.add(rel.parent.as_posix())

    folders = []
    for folder_id in sorted(folder_ids):
        label = root.name if folder_id == "" else Path(folder_id).name
        folders.append({"id": folder_id or ".", "type": "folder", "label": label})
    return folders


def extract_imports(path: Path, text: str) -> list[str]:
    patterns = IMPORT_PATTERNS.get(path.suffix.lower(), [])
    imports = []
    for pattern in patterns:
        imports.extend(pattern.findall(text))
    return imports


def resolve_relative_import(importer: str, target: str, file_lookup: set[str]) -> str | None:
    importer_parent = Path(importer).parent
    for suffix in IMPORTABLE_SUFFIXES:
        candidate = (importer_parent / f"{target}{suffix}").as_posix()
        if candidate in file_lookup:
            return candidate
    return None


def resolve_python_import(target: str, file_lookup: set[str]) -> str | None:
    normalized = target.replace(".", "/")
    for suffix in (".py", "/__init__.py"):
        candidate = f"{normalized}{suffix}"
        if candidate in file_lookup:
            return candidate
    return None


def load_go_module_name(root: Path) -> str | None:
    go_mod_path = root / "go.mod"
    if not go_mod_path.exists():
        return None
    try:
        text = go_mod_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = re.search(r"^\s*module\s+(\S+)\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


def resolve_go_import(target: str, go_module_name: str | None, folder_lookup: set[str]) -> str | None:
    if not go_module_name:
        return None
    if target == go_module_name:
        return "."
    if not target.startswith(f"{go_module_name}/"):
        return None
    folder_id = target[len(go_module_name) + 1 :]
    return folder_id if folder_id in folder_lookup else None


def resolve_import(
    importer: str,
    target: str,
    file_lookup: set[str],
    folder_lookup: set[str],
    go_module_name: str | None,
) -> str | None:
    if target.startswith("."):
        trimmed = target.lstrip("./")
        if not trimmed:
            return None
        return resolve_relative_import(importer, trimmed, file_lookup)
    if target.startswith("/"):
        return None
    if target.startswith(("http://", "https://")):
        return None

    if "/" in target or target.endswith((".js", ".jsx", ".ts", ".tsx", ".py", ".go")):
        relative = resolve_relative_import(importer, target, file_lookup)
        if relative:
            return relative

    go_target = resolve_go_import(target, go_module_name, folder_lookup)
    if go_target:
        return go_target

    return resolve_python_import(target, file_lookup)


def collect_file_nodes(root: Path, config: Config) -> tuple[list[dict], dict[str, list[str]]]:
    file_nodes = []
    raw_imports: dict[str, list[str]] = {}
    for file_path in iter_files(root, config):
        rel_id = relative_id(root, file_path)
        stat = file_path.stat()
        text = ""
        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                text = ""
        except OSError:
            text = ""

        line_count = text.count("\n") + (1 if text else 0)
        file_nodes.append(
            {
                "id": rel_id,
                "type": "file",
                "label": file_path.name,
                "ext": file_path.suffix.lower(),
                "bytes": stat.st_size,
                "lines": line_count,
                "mtime": int(stat.st_mtime),
            }
        )
        raw_imports[rel_id] = extract_imports(file_path, text)
    return file_nodes, raw_imports


def build_edges(
    file_nodes: list[dict],
    raw_imports: dict[str, list[str]],
    folder_nodes: list[dict],
    go_module_name: str | None,
) -> list[dict]:
    edges = []
    file_lookup = {node["id"] for node in file_nodes}
    folder_lookup = {node["id"] for node in folder_nodes}
    seen = set()

    for node in file_nodes:
        path = Path(node["id"])
        parent_id = "." if str(path.parent) == "." else path.parent.as_posix()
        edge = (parent_id, node["id"], "contains")
        if edge not in seen:
            seen.add(edge)
            edges.append({"source": parent_id, "target": node["id"], "type": "contains"})

        while str(path.parent) != ".":
            child = path.parent.as_posix()
            parent = "." if str(path.parent.parent) == "." else path.parent.parent.as_posix()
            folder_edge = (parent, child, "contains")
            if folder_edge not in seen:
                seen.add(folder_edge)
                edges.append({"source": parent, "target": child, "type": "contains"})
            path = path.parent

    for importer, imports in raw_imports.items():
        for target in imports:
            resolved = resolve_import(importer, target, file_lookup, folder_lookup, go_module_name)
            if not resolved or resolved == importer:
                continue
            edge = (importer, resolved, "imports")
            if edge in seen:
                continue
            seen.add(edge)
            edges.append({"source": importer, "target": resolved, "type": "imports"})

    return edges


def latest_source_mtime(root: Path, config: Config) -> int:
    latest = 0
    for file_path in iter_files(root, config):
        try:
            latest = max(latest, int(file_path.stat().st_mtime))
        except OSError:
            continue
    config_path = root / ".project-graph" / "config.json"
    if config_path.exists():
        latest = max(latest, int(config_path.stat().st_mtime))
    return latest


def graph_is_fresh(output_dir: Path, latest_mtime: int) -> bool:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists():
        return False
    try:
        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return False
    return int(manifest.get("source_latest_mtime", 0)) >= latest_mtime


def read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_graph(output_dir: Path) -> tuple[list[dict], list[dict]]:
    return read_json(output_dir / "nodes.json"), read_json(output_dir / "edges.json")  # type: ignore[return-value]


def build_graph(root: Path, config: Config, go_module_name: str | None) -> tuple[list[dict], list[dict], list[dict]]:
    file_nodes, raw_imports = collect_file_nodes(root, config)
    folder_nodes = build_folder_nodes(root, file_nodes)
    nodes = folder_nodes + sorted(file_nodes, key=lambda item: item["id"])
    edges = build_edges(file_nodes, raw_imports, folder_nodes, go_module_name)
    return file_nodes, nodes, edges


def write_graph(
    root: Path,
    output_dir: Path,
    config: Config,
    file_nodes: list[dict],
    nodes: list[dict],
    edges: list[dict],
    latest_mtime: int,
) -> None:
    write_json(output_dir / "nodes.json", nodes)
    write_json(output_dir / "edges.json", edges)
    write_json(output_dir / "manifest.json", build_manifest(root, output_dir, config, file_nodes, edges, latest_mtime))
    (output_dir / "summary.md").write_text(compute_summary(root, nodes, edges), encoding="utf-8")
    (output_dir / "viewer.html").write_text(viewer_html(nodes, edges, f"{root.name} Graph"), encoding="utf-8")


def import_degrees(nodes: list[dict], edges: list[dict]) -> dict[str, Counter]:
    degrees: dict[str, Counter] = defaultdict(Counter)
    for node in nodes:
        degrees[node["id"]]
    for edge in edges:
        if edge["type"] != "imports":
            continue
        degrees[edge["source"]]["out"] += 1
        degrees[edge["target"]]["in"] += 1
    return degrees


def print_rows(title: str, rows: list[str]) -> None:
    print(f"## {title}")
    for row in rows:
        print(f"- {row}")


def query_orphans(nodes: list[dict], edges: list[dict], limit: int) -> None:
    degrees = import_degrees(nodes, edges)
    rows = [
        f"`{node['id']}`"
        for node in nodes
        if node["type"] == "file" and degrees[node["id"]]["in"] == 0 and degrees[node["id"]]["out"] == 0
    ]
    print_rows("Orphan Candidates", rows[:limit] or ["None detected"])


def query_central(nodes: list[dict], edges: list[dict], limit: int) -> None:
    degrees = import_degrees(nodes, edges)
    rows = []
    for node in nodes:
        if node["type"] != "file":
            continue
        counts = degrees[node["id"]]
        total = counts["in"] + counts["out"]
        if total:
            rows.append((total, counts["in"], counts["out"], node["id"]))
    rows.sort(reverse=True)
    print_rows(
        "Central Files",
        [f"`{node_id}` ({total} import edges, in {in_count}, out {out_count})" for total, in_count, out_count, node_id in rows[:limit]]
        or ["None detected"],
    )


def query_around(nodes: list[dict], edges: list[dict], start: str, depth: int, limit: int) -> int:
    node_ids = {node["id"] for node in nodes}
    if start not in node_ids:
        print(f"Node not found: {start}", file=sys.stderr)
        return 1

    neighbors: dict[str, list[tuple[str, str]]] = defaultdict(list)
    edge_labels: dict[tuple[str, str], str] = {}
    for edge in edges:
        neighbors[edge["source"]].append((edge["target"], edge["type"]))
        neighbors[edge["target"]].append((edge["source"], edge["type"]))
        edge_labels[(edge["source"], edge["target"])] = f"`{edge['source']}` --{edge['type']}--> `{edge['target']}`"
        edge_labels[(edge["target"], edge["source"])] = f"`{edge['source']}` --{edge['type']}--> `{edge['target']}`"

    seen = {start}
    queue = deque([(start, 0)])
    rows = []
    while queue and len(rows) < limit:
        current, current_depth = queue.popleft()
        if current_depth >= depth:
            continue
        for neighbor, edge_type in sorted(neighbors[current]):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            rows.append(edge_labels.get((current, neighbor), f"`{current}` --{edge_type}-- `{neighbor}`"))
            queue.append((neighbor, current_depth + 1))
            if len(rows) >= limit:
                break

    print_rows(f"Local Graph Around `{start}`", rows or ["No neighbors detected"])
    return 0


def query_impacted(nodes: list[dict], edges: list[dict], start: str, depth: int, limit: int) -> int:
    node_ids = {node["id"] for node in nodes}
    if start not in node_ids:
        print(f"Node not found: {start}", file=sys.stderr)
        return 1

    reverse_imports: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge["type"] == "imports":
            reverse_imports[edge["target"]].append(edge["source"])

    seen = {start}
    queue = deque([(start, 0)])
    rows = []
    while queue and len(rows) < limit:
        current, current_depth = queue.popleft()
        if current_depth >= depth:
            continue
        for importer in sorted(reverse_imports[current]):
            if importer in seen:
                continue
            seen.add(importer)
            rows.append(f"`{importer}` imports `{current}`")
            queue.append((importer, current_depth + 1))
            if len(rows) >= limit:
                break

    print_rows(f"Likely Impact From `{start}`", rows or ["No import dependents detected"])
    return 0


def run_query(args: argparse.Namespace, nodes: list[dict], edges: list[dict]) -> int:
    if args.around:
        return query_around(nodes, edges, args.around, max(args.depth, 0), max(args.limit, 1))
    if args.impacted:
        return query_impacted(nodes, edges, args.impacted, max(args.depth, 0), max(args.limit, 1))
    if args.orphans:
        query_orphans(nodes, edges, max(args.limit, 1))
        return 0
    if args.central:
        query_central(nodes, edges, max(args.limit, 1))
        return 0
    return 0


def compute_summary(root: Path, nodes: list[dict], edges: list[dict]) -> str:
    files = [node for node in nodes if node["type"] == "file"]
    folders = [node for node in nodes if node["type"] == "folder"]
    imports_in = Counter()
    imports_out = Counter()
    folder_counts = Counter()
    orphan_files = []

    for edge in edges:
        if edge["type"] == "imports":
            imports_out[edge["source"]] += 1
            imports_in[edge["target"]] += 1

    for file_node in files:
        parent = Path(file_node["id"]).parent.as_posix()
        folder_counts[parent or "."] += 1
        if imports_in[file_node["id"]] == 0 and imports_out[file_node["id"]] == 0:
            orphan_files.append(file_node["id"])

    top_in = [node for node, _ in imports_in.most_common(5)]
    top_out = [node for node, _ in imports_out.most_common(5)]
    biggest_folders = [folder for folder, _ in folder_counts.most_common(5)]

    lines = [
        f"# Project Graph Summary for {root.name}",
        "",
        f"- Files scanned: {len(files)}",
        f"- Folders captured: {max(len(folders) - 1, 0)}",
        f"- Total edges: {len(edges)}",
        f"- Import edges: {sum(1 for edge in edges if edge['type'] == 'imports')}",
        "",
        "## Largest Folders",
    ]
    lines.extend(f"- `{folder}`" for folder in biggest_folders or ["."])
    lines.extend(["", "## Most Referenced Files"])
    lines.extend(f"- `{item}`" for item in top_in or ["None detected"])
    lines.extend(["", "## Most Connected Importers"])
    lines.extend(f"- `{item}`" for item in top_out or ["None detected"])
    lines.extend(["", "## Orphan Candidates"])
    lines.extend(f"- `{item}`" for item in orphan_files[:10] or ["None detected"])
    return "\n".join(lines) + "\n"


def build_manifest(root: Path, output_dir: Path, config: Config, files: list[dict], edges: list[dict], latest_mtime: int) -> dict:
    return {
        "root": str(root),
        "output": str(output_dir),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_latest_mtime": latest_mtime,
        "file_count": len(files),
        "edge_count": len(edges),
        "include_extensions": sorted(config.include_extensions),
        "exclude_dirs": sorted(config.exclude_dirs),
        "exclude_path_prefixes": sorted(config.exclude_path_prefixes),
        "exclude_globs": sorted(config.exclude_globs),
        "max_file_bytes": config.max_file_bytes,
    }


def viewer_html(nodes: list[dict], edges: list[dict], title: str) -> str:
    payload = json.dumps({"nodes": nodes, "edges": edges}, separators=(",", ":"))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4efe4;
      --panel: rgba(255,255,255,0.82);
      --text: #1f2933;
      --muted: #667085;
      --line: rgba(27, 67, 50, 0.22);
      --folder: #c97a44;
      --file: #215a6d;
      --accent: #1b4332;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(201,122,68,0.20), transparent 30%),
        radial-gradient(circle at bottom right, rgba(33,90,109,0.18), transparent 28%),
        var(--bg);
    }}
    .shell {{
      display: grid;
      grid-template-columns: 320px 1fr;
      min-height: 100vh;
    }}
    .panel {{
      padding: 18px;
      background: var(--panel);
      backdrop-filter: blur(14px);
      border-right: 1px solid rgba(0,0,0,0.06);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 1.3rem;
    }}
    p, label, input, button, select {{
      font: inherit;
    }}
    .muted {{
      color: var(--muted);
      font-size: 0.92rem;
    }}
    input, select {{
      width: 100%;
      padding: 10px 12px;
      margin: 8px 0 14px;
      border-radius: 10px;
      border: 1px solid rgba(0,0,0,0.12);
      background: rgba(255,255,255,0.9);
    }}
    .details {{
      margin-top: 14px;
      padding-top: 14px;
      border-top: 1px solid rgba(0,0,0,0.08);
      font-size: 0.92rem;
      line-height: 1.5;
      white-space: pre-wrap;
    }}
    canvas {{
      width: 100%;
      height: 100vh;
      display: block;
    }}
    .legend {{
      display: flex;
      gap: 10px;
      margin-top: 14px;
      font-size: 0.86rem;
      color: var(--muted);
    }}
    .swatch {{
      width: 12px;
      height: 12px;
      border-radius: 999px;
      display: inline-block;
      margin-right: 6px;
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside class="panel">
      <h1>{title}</h1>
      <p class="muted">Local graph viewer for cached project structure. Filter by node name, then click a node to inspect its neighborhood.</p>
      <label for="search">Filter nodes</label>
      <input id="search" type="text" placeholder="folder, file, module">
      <label for="kind">Node type</label>
      <select id="kind">
        <option value="all">All</option>
        <option value="folder">Folders</option>
        <option value="file">Files</option>
      </select>
      <div class="legend">
        <span><span class="swatch" style="background: var(--folder)"></span>Folder</span>
        <span><span class="swatch" style="background: var(--file)"></span>File</span>
      </div>
      <div id="details" class="details">Select a node to inspect it.</div>
    </aside>
    <main>
      <canvas id="graph"></canvas>
    </main>
  </div>
  <script>
    const payload = {payload};
    const nodes = payload.nodes.map((node, index) => ({{
      ...node,
      x: Math.cos(index * 0.6) * (160 + (index % 9) * 20),
      y: Math.sin(index * 0.6) * (160 + (index % 7) * 16),
      vx: 0,
      vy: 0
    }}));
    const nodeMap = new Map(nodes.map(node => [node.id, node]));
    const edges = payload.edges
      .map(edge => ({{
        ...edge,
        sourceNode: nodeMap.get(edge.source),
        targetNode: nodeMap.get(edge.target)
      }}))
      .filter(edge => edge.sourceNode && edge.targetNode);
    const neighbors = new Map(nodes.map(node => [node.id, new Set()]));
    for (const edge of edges) {{
      neighbors.get(edge.source).add(edge.target);
      neighbors.get(edge.target).add(edge.source);
    }}

    const canvas = document.getElementById("graph");
    const ctx = canvas.getContext("2d");
    const details = document.getElementById("details");
    const search = document.getElementById("search");
    const kind = document.getElementById("kind");
    let selected = null;
    let hovered = null;

    function resize() {{
      const ratio = window.devicePixelRatio || 1;
      canvas.width = canvas.clientWidth * ratio;
      canvas.height = canvas.clientHeight * ratio;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    }}

    function visible(node) {{
      const term = search.value.trim().toLowerCase();
      const kindValue = kind.value;
      if (kindValue !== "all" && node.type !== kindValue) return false;
      if (!term) return true;
      return node.id.toLowerCase().includes(term) || node.label.toLowerCase().includes(term);
    }}

    function draw() {{
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      ctx.clearRect(0, 0, width, height);
      ctx.save();
      ctx.translate(width / 2, height / 2);

      for (const edge of edges) {{
        if (!visible(edge.sourceNode) || !visible(edge.targetNode)) continue;
        const focus = selected && (edge.source === selected.id || edge.target === selected.id);
        ctx.strokeStyle = focus ? "rgba(27,67,50,0.55)" : "rgba(27,67,50,0.18)";
        ctx.lineWidth = focus ? 1.5 : 1;
        ctx.beginPath();
        ctx.moveTo(edge.sourceNode.x, edge.sourceNode.y);
        ctx.lineTo(edge.targetNode.x, edge.targetNode.y);
        ctx.stroke();
      }}

      for (const node of nodes) {{
        if (!visible(node)) continue;
        const focus = selected && (node.id === selected.id || neighbors.get(selected.id).has(node.id));
        const radius = node.type === "folder" ? 6 : 4;
        ctx.beginPath();
        ctx.fillStyle = node.type === "folder" ? "#c97a44" : "#215a6d";
        ctx.globalAlpha = selected ? (focus ? 1 : 0.18) : 0.88;
        ctx.arc(node.x, node.y, radius + (hovered === node ? 2 : 0), 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1;
      }}

      ctx.restore();
      requestAnimationFrame(tick);
    }}

    function tick() {{
      for (let i = 0; i < nodes.length; i += 1) {{
        const a = nodes[i];
        for (let j = i + 1; j < nodes.length; j += 1) {{
          const b = nodes[j];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const distSq = Math.max(dx * dx + dy * dy, 0.01);
          const force = 1200 / distSq;
          const fx = dx * force * 0.0006;
          const fy = dy * force * 0.0006;
          a.vx -= fx;
          a.vy -= fy;
          b.vx += fx;
          b.vy += fy;
        }}
      }}
      for (const edge of edges) {{
        const dx = edge.targetNode.x - edge.sourceNode.x;
        const dy = edge.targetNode.y - edge.sourceNode.y;
        const distance = Math.max(Math.hypot(dx, dy), 0.01);
        const spring = (distance - 54) * 0.0009;
        const fx = (dx / distance) * spring;
        const fy = (dy / distance) * spring;
        edge.sourceNode.vx += fx;
        edge.sourceNode.vy += fy;
        edge.targetNode.vx -= fx;
        edge.targetNode.vy -= fy;
      }}
      for (const node of nodes) {{
        node.vx *= 0.92;
        node.vy *= 0.92;
        node.x += node.vx;
        node.y += node.vy;
      }}
      draw();
    }}

    function pickNode(event) {{
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left - canvas.clientWidth / 2;
      const y = event.clientY - rect.top - canvas.clientHeight / 2;
      hovered = null;
      for (const node of nodes) {{
        if (!visible(node)) continue;
        const radius = node.type === "folder" ? 8 : 6;
        if (Math.hypot(node.x - x, node.y - y) <= radius) {{
          hovered = node;
        }}
      }}
      canvas.style.cursor = hovered ? "pointer" : "default";
    }}

    function renderDetails(node) {{
      const direct = [...neighbors.get(node.id)].slice(0, 12);
      const lines = [
        node.id,
        "",
        "type: " + node.type,
      ];
      if (node.ext) lines.push("ext: " + node.ext);
      if (node.lines) lines.push("lines: " + node.lines);
      lines.push("");
      lines.push("neighbors:");
      lines.push(...(direct.length ? direct.map(item => "- " + item) : ["- none"]));
      details.textContent = lines.join("\\n");
    }}

    canvas.addEventListener("mousemove", pickNode);
    canvas.addEventListener("click", () => {{
      selected = hovered;
      if (selected) renderDetails(selected);
      else details.textContent = "Select a node to inspect it.";
    }});
    window.addEventListener("resize", resize);
    search.addEventListener("input", () => {{
      selected = null;
      details.textContent = "Select a node to inspect it.";
    }});
    kind.addEventListener("change", () => {{
      selected = null;
      details.textContent = "Select a node to inspect it.";
    }});

    resize();
    tick();
  </script>
</body>
</html>
"""


def write_json(path: Path, payload: object) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    config = load_config(root)
    go_module_name = load_go_module_name(root)
    latest_mtime = latest_source_mtime(root, config)
    fresh = not args.force and graph_is_fresh(output_dir, latest_mtime)
    if fresh:
        nodes, edges = load_graph(output_dir)
        print(f"Graph is already fresh at {output_dir}")
    else:
        file_nodes, nodes, edges = build_graph(root, config, go_module_name)
        write_graph(root, output_dir, config, file_nodes, nodes, edges, latest_mtime)
        print(f"Wrote graph artifacts to {output_dir}")

    return run_query(args, nodes, edges)


if __name__ == "__main__":
    sys.exit(main())
