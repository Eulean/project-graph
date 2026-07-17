#!/usr/bin/env python3
"""Benchmark cold and incremental project-graph builds for a repository."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def timed_run(command: list[str]) -> float:
    started = time.perf_counter()
    subprocess.run(command, check=True, capture_output=True, text=True)
    return time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark project-graph build performance.")
    parser.add_argument("--root", required=True, help="Repository root to benchmark")
    parser.add_argument("--iterations", type=int, default=3, help="Number of warm rebuilds")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    builder = Path(__file__).with_name("build_project_graph.py")
    with tempfile.TemporaryDirectory(prefix="project-graph-benchmark-") as temp_dir:
        output = Path(temp_dir) / ".project-graph"
        command = [sys.executable, str(builder), "--root", str(root), "--output", str(output), "--force"]
        cold_seconds = timed_run(command)
        warm_seconds = [timed_run(command) for _ in range(max(args.iterations, 1))]
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))

    result = {
        "root": str(root),
        "files": manifest.get("file_count", 0),
        "edges": manifest.get("edge_count", 0),
        "cold_build_seconds": round(cold_seconds, 4),
        "warm_rebuild_seconds": [round(value, 4) for value in warm_seconds],
        "warm_average_seconds": round(sum(warm_seconds) / len(warm_seconds), 4),
        "warm_reused_files": manifest.get("reused_file_count", 0),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
