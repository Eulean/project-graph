from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from project_graph.config import inventory_hash, load_config, latest_source_mtime, source_inventory
from project_graph.graph import build_graph, graph_is_fresh, load_graph, write_graph
from project_graph.imports import load_go_module_name, load_ts_config
from project_graph.queries import run_query

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build repository graph artifacts.")
    parser.add_argument("--root", required=True, help="Repository root to scan")
    parser.add_argument("--output", required=True, help="Directory for graph artifacts")
    parser.add_argument("--force", action="store_true", help="Rebuild even if graph looks fresh")
    parser.add_argument("--around", help="Print a compact local graph around this node id")
    parser.add_argument("--impacted", help="Print importers likely affected by changes to this node id")
    parser.add_argument("--risk", help="Print a graph-based change risk estimate for this node id")
    parser.add_argument("--changed-since", help="Print graph impact for files changed since this Git ref")
    parser.add_argument("--read-next", help="Print the next files Codex should read after this node id")
    parser.add_argument("--why", help="Explain why this node appears in local impact/navigation results")
    parser.add_argument("--docs-for", help="Print docs likely relevant to this node id")
    parser.add_argument("--orphans", action="store_true", help="Print files with no import edges")
    parser.add_argument("--central", action="store_true", help="Print highly connected files")
    parser.add_argument("--entrypoints", action="store_true", help="Print likely project entrypoints")
    parser.add_argument("--missing-tests", action="store_true", help="Print source files with no likely test file")
    parser.add_argument("--owners", action="store_true", help="Print CODEOWNERS-derived ownership hints")
    parser.add_argument("--confidence", action="store_true", help="Print graph confidence signals")
    parser.add_argument("--export-bundle", help="Write a small handoff bundle directory or .zip file")
    parser.add_argument("--bundle-for", help="Optional node id to focus --export-bundle output")
    parser.add_argument("--format", choices=("markdown", "mermaid"), default="markdown", help="Output format for supported query modes")
    parser.add_argument("--depth", type=int, default=2, help="Traversal depth for --around or --impacted")
    parser.add_argument("--limit", type=int, default=12, help="Maximum query rows to print")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        config = load_config(root)
    except (json.JSONDecodeError, ValueError) as error:
        print(f"Config error: {error}", file=sys.stderr)
        return 2
    go_module_name = load_go_module_name(root)
    ts_config = load_ts_config(root)
    latest_mtime = latest_source_mtime(root, config)
    inventory = source_inventory(root, config)
    current_inventory_hash = inventory_hash(inventory)
    fresh = not args.force and graph_is_fresh(output_dir, latest_mtime, current_inventory_hash)
    if fresh:
        nodes, edges = load_graph(output_dir)
        print(f"Graph is already fresh at {output_dir}")
    else:
        file_nodes, nodes, edges = build_graph(root, config, go_module_name, ts_config)
        write_graph(root, output_dir, config, file_nodes, nodes, edges, latest_mtime, current_inventory_hash)
        print(f"Wrote graph artifacts to {output_dir}")

    return run_query(args, root, output_dir, nodes, edges)
