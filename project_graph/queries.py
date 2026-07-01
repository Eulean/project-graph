from __future__ import annotations

import fnmatch
import hashlib
import json
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict, deque
from pathlib import Path

from project_graph.imports import IMPORT_PATTERNS

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


def file_nodes(nodes: list[dict]) -> list[dict]:
    return [node for node in nodes if node["type"] == "file"]


def node_exists(nodes: list[dict], node_id: str) -> bool:
    return node_id in {node["id"] for node in nodes}


def import_neighbors(edges: list[dict]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    outgoing: dict[str, set[str]] = defaultdict(set)
    incoming: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if edge["type"] != "imports":
            continue
        outgoing[edge["source"]].add(edge["target"])
        incoming[edge["target"]].add(edge["source"])
    return outgoing, incoming


def contains_neighbors(edges: list[dict]) -> tuple[dict[str, set[str]], dict[str, str]]:
    children: dict[str, set[str]] = defaultdict(set)
    parents: dict[str, str] = {}
    for edge in edges:
        if edge["type"] != "contains":
            continue
        children[edge["source"]].add(edge["target"])
        parents[edge["target"]] = edge["source"]
    return children, parents


def likely_entrypoint_score(node_id: str) -> int:
    path = Path(node_id)
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    score = 0
    if name in {"main.py", "app.py", "server.py", "manage.py", "program.cs"}:
        score += 8
    if name in {"main.go", "main.rs", "index.js", "index.ts", "index.jsx", "index.tsx"}:
        score += 7
    if name in {"cli.py", "__main__.py"}:
        score += 6
    if "cmd" in parts or "bin" in parts:
        score += 3
    if "test" in name or "tests" in parts or "__tests__" in parts:
        score -= 8
    return score


def test_stems_for(node_id: str) -> set[str]:
    path = Path(node_id)
    stem = path.stem
    return {
        f"test_{stem}",
        f"{stem}_test",
        f"{stem}.test",
        f"{stem}.spec",
        f"{stem}Test",
        f"{stem}Tests",
    }


def is_test_node(node_id: str) -> bool:
    path = Path(node_id)
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    return (
        "test" in name
        or "tests" in parts
        or "__tests__" in parts
        or name.endswith(("_test.go", "test.cs"))
    )


def likely_test_for(node_id: str, test_ids: set[str]) -> str | None:
    path = Path(node_id)
    candidates = test_stems_for(node_id)
    for test_id in sorted(test_ids):
        test_path = Path(test_id)
        if test_path.stem in candidates and (test_path.parent == path.parent or path.stem.lower() in test_id.lower()):
            return test_id
    for test_id in sorted(test_ids):
        if path.stem.lower() in Path(test_id).stem.lower():
            return test_id
    return None


def docs_for_node(nodes: list[dict], node_id: str, limit: int) -> list[str]:
    docs = []
    doc_names = {"readme.md", "architecture.md", "module-map.md", "testing-map.md"}
    node_path = Path(node_id)
    for node in file_nodes(nodes):
        candidate = node["id"]
        candidate_path = Path(candidate)
        if candidate_path.suffix.lower() != ".md":
            continue
        name = candidate_path.name.lower()
        same_area = candidate_path.parent == node_path.parent or str(node_path).startswith(candidate_path.parent.as_posix())
        if name in doc_names or same_area:
            docs.append(candidate)
    docs.sort(key=lambda item: (0 if Path(item).name.lower() == "readme.md" else 1, len(Path(item).parts), item))
    return docs[:limit]


def parse_codeowners(root: Path) -> list[tuple[str, list[str]]]:
    candidates = [
        root / "CODEOWNERS",
        root / ".github" / "CODEOWNERS",
        root / "docs" / "CODEOWNERS",
    ]
    for path in candidates:
        if not path.exists():
            continue
        rows = []
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if len(parts) >= 2:
                rows.append((parts[0], parts[1:]))
        return rows
    return []


def owners_for_path(codeowners: list[tuple[str, list[str]]], node_id: str) -> list[str]:
    matched: list[str] = []
    normalized = node_id.lstrip("/")
    for pattern, owners in codeowners:
        glob = pattern.lstrip("/")
        if glob.endswith("/"):
            glob = f"{glob}*"
        if fnmatch.fnmatch(normalized, glob) or normalized.startswith(glob.rstrip("*")):
            matched = owners
    return matched


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


def risk_details(nodes: list[dict], edges: list[dict], target: str) -> tuple[int, list[str]]:
    node_lookup = {node["id"]: node for node in nodes}
    outgoing, incoming = import_neighbors(edges)
    score = 0
    reasons = []
    inbound = len(incoming[target])
    outbound = len(outgoing[target])
    if inbound:
        score += inbound * 3
        reasons.append(f"{inbound} importer(s)")
    if outbound:
        score += outbound * 2
        reasons.append(f"{outbound} imported dependency/dependencies")
    node = node_lookup.get(target, {})
    lines = int(node.get("lines", 0) or 0)
    if lines >= 300:
        score += 4
        reasons.append(f"{lines} lines")
    elif lines >= 100:
        score += 2
        reasons.append(f"{lines} lines")
    if likely_entrypoint_score(target) > 0:
        score += 4
        reasons.append("likely entrypoint")
    files = file_nodes(nodes)
    test_ids = {item["id"] for item in files if is_test_node(item["id"])}
    if node.get("type") == "file" and not is_test_node(target) and not likely_test_for(target, test_ids):
        score += 2
        reasons.append("no obvious matching test")
    return score, reasons or ["isolated or low-signal node"]


def risk_level(score: int) -> str:
    if score >= 10:
        return "high"
    if score >= 5:
        return "medium"
    return "low"


def query_risk(nodes: list[dict], edges: list[dict], target: str) -> int:
    if not node_exists(nodes, target):
        print(f"Node not found: {target}", file=sys.stderr)
        return 1
    score, reasons = risk_details(nodes, edges, target)
    print_rows(f"Change Risk For `{target}`", [f"{risk_level(score)} risk (score {score})", *reasons])
    return 0


def git_changed_files(root: Path, base_ref: str) -> tuple[list[str], str | None]:
    commands = [["git", "diff", "--name-only", f"{base_ref}...HEAD"], ["git", "diff", "--name-only", base_ref]]
    empty_success = False
    for command in commands:
        result = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
        if result.returncode == 0:
            paths = [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]
            if paths:
                return paths, None
            empty_success = True
    if empty_success:
        return [], None
    return [], result.stderr.strip() or f"Could not diff against {base_ref}"


def query_changed_since(root: Path, nodes: list[dict], edges: list[dict], base_ref: str, limit: int) -> int:
    changed, error = git_changed_files(root, base_ref)
    if error:
        print(error, file=sys.stderr)
        return 1
    node_ids = {node["id"] for node in nodes}
    scanned = [path for path in changed if path in node_ids]
    rows = [f"`{path}` changed" for path in scanned[:limit]]
    if not rows:
        rows.append("No changed scanned files detected")
    outgoing, incoming = import_neighbors(edges)
    impacted = []
    for path in scanned:
        for importer in sorted(incoming[path]):
            impacted.append(f"`{importer}` imports changed `{path}`")
    rows.extend(impacted[: max(limit - len(rows), 0)])
    for path in scanned[:limit]:
        score, _ = risk_details(nodes, edges, path)
        rows.append(f"`{path}` risk: {risk_level(score)} (score {score})")
    print_rows(f"Changed Since `{base_ref}`", rows[:limit] or ["No changes detected"])
    return 0


def mermaid_local_graph(nodes: list[dict], edges: list[dict], start: str, depth: int, limit: int) -> int:
    if not node_exists(nodes, start):
        print(f"Node not found: {start}", file=sys.stderr)
        return 1
    neighbors: dict[str, set[str]] = defaultdict(set)
    edge_lookup: dict[tuple[str, str], str] = {}
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        edge_lookup[(edge["source"], edge["target"])] = edge["type"]
        edge_lookup[(edge["target"], edge["source"])] = edge["type"]

    seen = {start}
    queue = deque([(start, 0)])
    selected_edges = []
    while queue and len(selected_edges) < limit:
        current, current_depth = queue.popleft()
        if current_depth >= depth:
            continue
        for neighbor in sorted(neighbors[current]):
            edge_type = edge_lookup[(current, neighbor)]
            selected_edges.append((current, neighbor, edge_type))
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append((neighbor, current_depth + 1))
            if len(selected_edges) >= limit:
                break

    print("```mermaid")
    print("graph LR")
    if not selected_edges:
        print(f'  {mermaid_id(start)}["{start}"]')
    for source, target, edge_type in selected_edges:
        print(f'  {mermaid_id(source)}["{source}"] -->|{edge_type}| {mermaid_id(target)}["{target}"]')
    print("```")
    return 0


def mermaid_id(value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return f"N{digest}"


def query_entrypoints(nodes: list[dict], limit: int) -> None:
    rows = []
    for node in file_nodes(nodes):
        score = likely_entrypoint_score(node["id"])
        if score > 0:
            rows.append((score, node["id"]))
    rows.sort(key=lambda item: (-item[0], item[1]))
    print_rows("Likely Entrypoints", [f"`{node_id}` (score {score})" for score, node_id in rows[:limit]] or ["None detected"])


def query_missing_tests(nodes: list[dict], limit: int) -> None:
    files = file_nodes(nodes)
    test_ids = {node["id"] for node in files if is_test_node(node["id"])}
    rows = []
    for node in files:
        node_id = node["id"]
        if is_test_node(node_id) or Path(node_id).suffix.lower() not in {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".cs", ".rs"}:
            continue
        if not likely_test_for(node_id, test_ids):
            rows.append(f"`{node_id}`")
    print_rows("Missing Likely Tests", rows[:limit] or ["None detected"])


def query_docs_for(nodes: list[dict], target: str, limit: int) -> int:
    if not node_exists(nodes, target):
        print(f"Node not found: {target}", file=sys.stderr)
        return 1
    print_rows(f"Docs For `{target}`", [f"`{doc}`" for doc in docs_for_node(nodes, target, limit)] or ["None detected"])
    return 0


def query_owners(root: Path, nodes: list[dict], limit: int) -> None:
    codeowners = parse_codeowners(root)
    if not codeowners:
        print_rows("Ownership Hints", ["No CODEOWNERS file detected"])
        return
    rows = []
    for node in file_nodes(nodes):
        owners = owners_for_path(codeowners, node["id"])
        if owners:
            rows.append(f"`{node['id']}` -> {', '.join(owners)}")
    print_rows("Ownership Hints", rows[:limit] or ["No owned files matched scanned nodes"])


def query_confidence(nodes: list[dict], edges: list[dict]) -> None:
    files = file_nodes(nodes)
    import_edges = [edge for edge in edges if edge["type"] == "imports"]
    supported_import_files = [node for node in files if node.get("ext") in IMPORT_PATTERNS]
    files_with_import_edges = {edge["source"] for edge in import_edges} | {edge["target"] for edge in import_edges}
    coverage = 0 if not supported_import_files else round(len(files_with_import_edges) / len(supported_import_files) * 100)
    level = "high" if coverage >= 60 else "medium" if coverage >= 25 else "low"
    rows = [
        f"Import confidence: {level} ({coverage}% of supported-language files connected by imports)",
        f"Files scanned: {len(files)}",
        f"Import edges: {len(import_edges)}",
        f"Supported import scanners: {', '.join(sorted(IMPORT_PATTERNS))}",
    ]
    print_rows("Graph Confidence", rows)


def query_read_next(nodes: list[dict], edges: list[dict], target: str, limit: int) -> int:
    if not node_exists(nodes, target):
        print(f"Node not found: {target}", file=sys.stderr)
        return 1
    outgoing, incoming = import_neighbors(edges)
    _, parents = contains_neighbors(edges)
    candidates: list[tuple[int, str, str]] = []
    for node_id in outgoing[target]:
        candidates.append((100, node_id, "imported by target"))
    for node_id in incoming[target]:
        candidates.append((90, node_id, "imports target"))
    parent = parents.get(target)
    if parent:
        for edge in edges:
            if edge["type"] == "contains" and edge["source"] == parent and edge["target"] != target:
                candidates.append((50, edge["target"], f"same folder `{parent}`"))
    for doc in docs_for_node(nodes, target, limit):
        candidates.append((80, doc, "nearby documentation"))

    seen = set()
    rows = []
    for score, node_id, reason in sorted(candidates, key=lambda item: (-item[0], item[1])):
        if node_id in seen:
            continue
        seen.add(node_id)
        rows.append(f"`{node_id}` - {reason}")
        if len(rows) >= limit:
            break
    print_rows(f"Read Next After `{target}`", rows or ["No strong next reads detected"])
    return 0


def query_why(nodes: list[dict], edges: list[dict], target: str, limit: int) -> int:
    if not node_exists(nodes, target):
        print(f"Node not found: {target}", file=sys.stderr)
        return 1
    outgoing, incoming = import_neighbors(edges)
    _, parents = contains_neighbors(edges)
    rows = []
    rows.extend(f"`{target}` imports `{node_id}`" for node_id in sorted(outgoing[target])[:limit])
    rows.extend(f"`{node_id}` imports `{target}`" for node_id in sorted(incoming[target])[:limit])
    if parents.get(target):
        rows.append(f"`{target}` is contained by `{parents[target]}`")
    if not rows:
        rows.append("No import or containment reason detected")
    print_rows(f"Why `{target}` Matters", rows[:limit])
    return 0


def export_bundle(root: Path, output_dir: Path, nodes: list[dict], edges: list[dict], destination: str, focus: str | None, limit: int) -> None:
    bundle_files: dict[str, str] = {}
    summary_path = output_dir / "summary.md"
    if summary_path.exists():
        bundle_files["summary.md"] = summary_path.read_text(encoding="utf-8", errors="ignore")
    bundle_files["nodes.json"] = json.dumps(nodes[:limit], indent=2) + "\n"
    bundle_files["edges.json"] = json.dumps(edges[:limit], indent=2) + "\n"
    prompt_lines = [
        "Use this Project Graph bundle before reading source.",
        "Start with summary.md, then inspect nodes.json and edges.json only as needed.",
    ]
    if focus:
        prompt_lines.append(f"Focus node: {focus}")
        prompt_lines.append("Suggested next command: project-graph --read-next " + focus)
    bundle_files["prompt.md"] = "\n".join(prompt_lines) + "\n"

    dest_path = Path(destination)
    if dest_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(dest_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in bundle_files.items():
                archive.writestr(name, content)
    else:
        dest_path.mkdir(parents=True, exist_ok=True)
        for name, content in bundle_files.items():
            (dest_path / name).write_text(content, encoding="utf-8")
    print_rows("Export Bundle", [f"Wrote `{dest_path}` from `{root}`"])


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


def run_query(args: argparse.Namespace, root: Path, output_dir: Path, nodes: list[dict], edges: list[dict]) -> int:
    if args.around:
        if args.format == "mermaid":
            return mermaid_local_graph(nodes, edges, args.around, max(args.depth, 0), max(args.limit, 1))
        return query_around(nodes, edges, args.around, max(args.depth, 0), max(args.limit, 1))
    if args.impacted:
        return query_impacted(nodes, edges, args.impacted, max(args.depth, 0), max(args.limit, 1))
    if args.risk:
        return query_risk(nodes, edges, args.risk)
    if args.changed_since:
        return query_changed_since(root, nodes, edges, args.changed_since, max(args.limit, 1))
    if args.read_next:
        return query_read_next(nodes, edges, args.read_next, max(args.limit, 1))
    if args.why:
        return query_why(nodes, edges, args.why, max(args.limit, 1))
    if args.docs_for:
        return query_docs_for(nodes, args.docs_for, max(args.limit, 1))
    if args.orphans:
        query_orphans(nodes, edges, max(args.limit, 1))
        return 0
    if args.central:
        query_central(nodes, edges, max(args.limit, 1))
        return 0
    if args.entrypoints:
        query_entrypoints(nodes, max(args.limit, 1))
        return 0
    if args.missing_tests:
        query_missing_tests(nodes, max(args.limit, 1))
        return 0
    if args.owners:
        query_owners(root, nodes, max(args.limit, 1))
        return 0
    if args.confidence:
        query_confidence(nodes, edges)
        return 0
    if args.export_bundle:
        export_bundle(root, output_dir, nodes, edges, args.export_bundle, args.bundle_for, max(args.limit, 1))
        return 0
    return 0
