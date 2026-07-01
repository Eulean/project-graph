from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from project_graph.config import Config, iter_files, relative_id
from project_graph.imports import TsConfig, extract_imports, resolve_import
from project_graph.viewer import viewer_html

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
    ts_config: TsConfig,
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
            resolved = resolve_import(importer, target, file_lookup, folder_lookup, go_module_name, ts_config)
            if not resolved or resolved == importer:
                continue
            edge = (importer, resolved, "imports")
            if edge in seen:
                continue
            seen.add(edge)
            edges.append({"source": importer, "target": resolved, "type": "imports"})
    return edges


def graph_is_fresh(output_dir: Path, latest_mtime: int, current_inventory_hash: str) -> bool:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists():
        return False
    try:
        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return False
    stored_hash = manifest.get("source_inventory_hash")
    if stored_hash:
        return stored_hash == current_inventory_hash
    return int(manifest.get("source_latest_mtime", 0)) >= latest_mtime


def read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_graph(output_dir: Path) -> tuple[list[dict], list[dict]]:
    return read_json(output_dir / "nodes.json"), read_json(output_dir / "edges.json")  # type: ignore[return-value]


def build_graph(root: Path, config: Config, go_module_name: str | None, ts_config: TsConfig) -> tuple[list[dict], list[dict], list[dict]]:
    file_nodes, raw_imports = collect_file_nodes(root, config)
    folder_nodes = build_folder_nodes(root, file_nodes)
    nodes = folder_nodes + sorted(file_nodes, key=lambda item: item["id"])
    edges = build_edges(file_nodes, raw_imports, folder_nodes, go_module_name, ts_config)
    return file_nodes, nodes, edges


def write_graph(
    root: Path,
    output_dir: Path,
    config: Config,
    file_nodes: list[dict],
    nodes: list[dict],
    edges: list[dict],
    latest_mtime: int,
    current_inventory_hash: str,
) -> None:
    write_json(output_dir / "nodes.json", nodes)
    write_json(output_dir / "edges.json", edges)
    write_json(output_dir / "manifest.json", build_manifest(root, output_dir, config, file_nodes, edges, latest_mtime, current_inventory_hash))
    (output_dir / "summary.md").write_text(compute_summary(root, nodes, edges), encoding="utf-8")
    (output_dir / "viewer.html").write_text(viewer_html(nodes, edges, f"{root.name} Graph"), encoding="utf-8")

def read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_graph(output_dir: Path) -> tuple[list[dict], list[dict]]:
    return read_json(output_dir / "nodes.json"), read_json(output_dir / "edges.json")  # type: ignore[return-value]


def build_graph(root: Path, config: Config, go_module_name: str | None, ts_config: TsConfig) -> tuple[list[dict], list[dict], list[dict]]:
    file_nodes, raw_imports = collect_file_nodes(root, config)
    folder_nodes = build_folder_nodes(root, file_nodes)
    nodes = folder_nodes + sorted(file_nodes, key=lambda item: item["id"])
    edges = build_edges(file_nodes, raw_imports, folder_nodes, go_module_name, ts_config)
    return file_nodes, nodes, edges

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


def build_manifest(
    root: Path,
    output_dir: Path,
    config: Config,
    files: list[dict],
    edges: list[dict],
    latest_mtime: int,
    current_inventory_hash: str,
) -> dict:
    return {
        "root": str(root),
        "output": str(output_dir),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_latest_mtime": latest_mtime,
        "source_inventory_hash": current_inventory_hash,
        "file_count": len(files),
        "edge_count": len(edges),
        "include_extensions": sorted(config.include_extensions),
        "exclude_dirs": sorted(config.exclude_dirs),
        "exclude_path_prefixes": sorted(config.exclude_path_prefixes),
        "exclude_globs": sorted(config.exclude_globs),
        "max_file_bytes": config.max_file_bytes,
    }

def write_json(path: Path, payload: object) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
