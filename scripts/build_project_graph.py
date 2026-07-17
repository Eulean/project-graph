#!/usr/bin/env python3
"""
Build compact repository graph artifacts plus a lightweight HTML viewer.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
import os
import posixpath
import re
import subprocess
import sys
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


GRAPH_FORMAT_VERSION = 2
PARSER_VERSION = "2.0"


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
    ".angular",
    ".cache",
    ".eggs",
    ".git",
    ".gradle",
    ".hg",
    ".idea",
    ".mypy_cache",
    ".next",
    ".nox",
    ".nuxt",
    ".parcel-cache",
    ".pnpm-store",
    ".project-graph",
    ".pytest_cache",
    ".ruff_cache",
    ".svelte-kit",
    ".svn",
    ".tox",
    ".turbo",
    ".venv",
    ".vscode",
    ".yarn",
    "__pycache__",
    "bin",
    "bower_components",
    "build",
    "coverage",
    "dist",
    "env",
    "generated",
    "jspm_packages",
    "node_modules",
    "obj",
    "out",
    "site-packages",
    "target",
    "temp",
    "tmp",
    "vendor",
    "venv",
}

DEFAULT_EXCLUDE_DIR_GLOBS = {
    "*.egg-info",
}

DEFAULT_EXCLUDE_GLOBS = {
    "*.generated.*",
    "*.min.js",
    "*.min.mjs",
    "*.pyc",
    "*.snap",
    "package-lock.json",
}

DEFAULT_MAX_FILE_BYTES = 262_144

IMPORT_PATTERNS = {
    ".py": [
        re.compile(r"^\s*import\s+([a-zA-Z0-9_\.]+)", re.MULTILINE),
        re.compile(r"^\s*from\s+([a-zA-Z0-9_\.]+)\s+import\s+", re.MULTILINE),
    ],
    ".js": [
        re.compile(r'import\s+.*?\s+from\s+[\'"]([^\'"]+)[\'"]'),
        re.compile(r'export\s+(?:\*|\{[^}]*\})\s+from\s+[\'"]([^\'"]+)[\'"]'),
        re.compile(r'import\s*[\'"]([^\'"]+)[\'"]'),
        re.compile(r'import\([\'"]([^\'"]+)[\'"]\)'),
        re.compile(r'require\([\'"]([^\'"]+)[\'"]\)'),
    ],
    ".jsx": [
        re.compile(r'import\s+.*?\s+from\s+[\'"]([^\'"]+)[\'"]'),
        re.compile(r'export\s+(?:\*|\{[^}]*\})\s+from\s+[\'"]([^\'"]+)[\'"]'),
        re.compile(r'import\s*[\'"]([^\'"]+)[\'"]'),
        re.compile(r'import\([\'"]([^\'"]+)[\'"]\)'),
        re.compile(r'require\([\'"]([^\'"]+)[\'"]\)'),
    ],
    ".ts": [
        re.compile(r'import\s+.*?\s+from\s+[\'"]([^\'"]+)[\'"]'),
        re.compile(r'export\s+(?:\*|\{[^}]*\})\s+from\s+[\'"]([^\'"]+)[\'"]'),
        re.compile(r'import\s*[\'"]([^\'"]+)[\'"]'),
        re.compile(r'import\([\'"]([^\'"]+)[\'"]\)'),
        re.compile(r'require\([\'"]([^\'"]+)[\'"]\)'),
    ],
    ".tsx": [
        re.compile(r'import\s+.*?\s+from\s+[\'"]([^\'"]+)[\'"]'),
        re.compile(r'export\s+(?:\*|\{[^}]*\})\s+from\s+[\'"]([^\'"]+)[\'"]'),
        re.compile(r'import\s*[\'"]([^\'"]+)[\'"]'),
        re.compile(r'import\([\'"]([^\'"]+)[\'"]\)'),
        re.compile(r'require\([\'"]([^\'"]+)[\'"]\)'),
    ],
    ".go": [
        re.compile(r'^\s*import\s+"([^"]+)"', re.MULTILINE),
        re.compile(r'^\s*"([^"]+)"\s*$', re.MULTILINE),
    ],
    ".java": [re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)(?:\.\*)?\s*;", re.MULTILINE)],
    ".cs": [re.compile(r"^\s*using\s+([\w.]+)\s*;", re.MULTILINE)],
    ".rs": [
        re.compile(r"^\s*mod\s+([A-Za-z_][A-Za-z0-9_]*)\s*;", re.MULTILINE),
        re.compile(r"^\s*use\s+(crate(?:::[A-Za-z_][A-Za-z0-9_]*)+)", re.MULTILINE),
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

CONFIG_FILES = {
    ".babelrc",
    ".eslintrc",
    ".prettierrc",
    "Dockerfile",
    "Makefile",
    "biome.json",
    "docker-compose.yml",
    "eslint.config.js",
    "jest.config.js",
    "next.config.js",
    "package.json",
    "playwright.config.ts",
    "pyproject.toml",
    "pytest.ini",
    "ruff.toml",
    "tsconfig.json",
    "vite.config.js",
    "vite.config.ts",
}

TEST_MARKERS = (
    ".spec.",
    ".test.",
    "_spec.",
    "_test.",
)

ROUTE_ELEMENT_RE = re.compile(
    r"<Route\b[^>]*\bpath\s*=\s*[\"']([^\"']+)[\"'][^>]*\belement\s*=\s*\{\s*<([A-Z][A-Za-z0-9_]*)",
    re.DOTALL,
)
IMPORT_NAME_RE = re.compile(r"import\s+(?:\{\s*([^}]+)\s*\}|([A-Z][A-Za-z0-9_]*))\s+from\s+[\"']([^\"']+)[\"']")
JSX_TAG_RE = re.compile(r"<([A-Z][A-Za-z0-9_]*)\b")


@dataclass
class Config:
    include_extensions: set[str]
    exclude_dirs: set[str]
    exclude_dir_globs: set[str]
    exclude_path_prefixes: set[str]
    exclude_globs: set[str]
    max_file_bytes: int
    respect_gitignore: bool
    layers: list[dict]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build repository graph artifacts.")
    parser.add_argument("--root", required=True, help="Repository root to scan")
    parser.add_argument("--output", required=True, help="Directory for graph artifacts")
    parser.add_argument("--force", action="store_true", help="Rebuild even if graph looks fresh")
    parser.add_argument("--around", help="Print a compact local graph around this node id")
    parser.add_argument("--impacted", help="Print importers likely affected by changes to this node id")
    parser.add_argument("--orphans", action="store_true", help="Print files with no import edges")
    parser.add_argument("--central", action="store_true", help="Print highly connected files")
    parser.add_argument("--cycles", action="store_true", help="Print circular import dependencies")
    parser.add_argument("--untested", action="store_true", help="Print referenced source files without linked tests")
    parser.add_argument("--dependencies", help="Print direct dependencies of this node id")
    parser.add_argument("--dependents", help="Print direct dependents of this node id")
    parser.add_argument("--path", nargs=2, metavar=("FROM", "TO"), help="Explain the shortest relationship path")
    parser.add_argument("--why-connected", nargs=2, metavar=("FROM", "TO"), help="Alias for --path")
    parser.add_argument("--changed", action="store_true", help="Print files changed in the Git working tree")
    parser.add_argument("--diff", metavar="REF", help="Print files changed from a Git reference")
    parser.add_argument("--impact-diff", metavar="REF", help="Explain likely impact from files changed since a Git reference")
    parser.add_argument("--hotspots", action="store_true", help="Rank central files by Git change frequency")
    parser.add_argument("--ignored", action="store_true", help="Explain ignored files and directories")
    parser.add_argument("--entrypoints", action="store_true", help="Print likely application and script entrypoints")
    parser.add_argument("--routes", action="store_true", help="Print detected route declarations")
    parser.add_argument("--violations", action="store_true", help="Print configured architecture-layer violations")
    parser.add_argument("--depth", type=int, default=2, help="Traversal depth for --around or --impacted")
    parser.add_argument("--limit", type=int, default=12, help="Maximum query rows to print")
    return parser.parse_args()


def load_config(root: Path) -> Config:
    config_path = root / ".project-graph" / "config.json"
    if not config_path.exists():
        return Config(
            include_extensions=set(DEFAULT_INCLUDE_EXTENSIONS),
            exclude_dirs=set(DEFAULT_EXCLUDE_DIRS),
            exclude_dir_globs=set(DEFAULT_EXCLUDE_DIR_GLOBS),
            exclude_path_prefixes=set(),
            exclude_globs=set(DEFAULT_EXCLUDE_GLOBS),
            max_file_bytes=DEFAULT_MAX_FILE_BYTES,
            respect_gitignore=True,
            layers=[],
        )

    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    use_default_excludes = bool(raw.get("use_default_excludes", True))
    exclude_dirs = set(raw.get("exclude_dirs", []))
    exclude_dir_globs = set(raw.get("exclude_dir_globs", []))
    exclude_globs = set(raw.get("exclude_globs", []))
    if use_default_excludes:
        exclude_dirs.update(DEFAULT_EXCLUDE_DIRS)
        exclude_dir_globs.update(DEFAULT_EXCLUDE_DIR_GLOBS)
        exclude_globs.update(DEFAULT_EXCLUDE_GLOBS)

    return Config(
        include_extensions=set(raw.get("include_extensions", DEFAULT_INCLUDE_EXTENSIONS)),
        exclude_dirs=exclude_dirs,
        exclude_dir_globs=exclude_dir_globs,
        exclude_path_prefixes=set(raw.get("exclude_path_prefixes", [])),
        exclude_globs=exclude_globs,
        max_file_bytes=int(raw.get("max_file_bytes", DEFAULT_MAX_FILE_BYTES)),
        respect_gitignore=bool(raw.get("respect_gitignore", True)),
        layers=list(raw.get("layers", [])),
    )


def should_skip_dir(root: Path, path: Path, config: Config) -> bool:
    if path.name in config.exclude_dirs or any(fnmatch.fnmatch(path.name, pattern) for pattern in config.exclude_dir_globs):
        return True
    rel = path.relative_to(root).as_posix()
    return any(rel == prefix or rel.startswith(f"{prefix}/") for prefix in config.exclude_path_prefixes)


def should_include_file(path: Path, config: Config) -> bool:
    if path.suffix.lower() not in config.include_extensions:
        if path.name not in CONFIG_FILES and not path.name.endswith((".config.js", ".config.ts", ".config.mjs")):
            return False
    for pattern in config.exclude_globs:
        if fnmatch.fnmatch(path.name, pattern):
            return False
    try:
        return path.stat().st_size <= config.max_file_bytes
    except OSError:
        return False


def git_paths(root: Path, *args: str) -> list[str] | None:
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return [item.decode("utf-8", errors="replace") for item in result.stdout.split(b"\0") if item]


def path_has_excluded_parent(root: Path, path: Path, config: Config) -> bool:
    for parent in path.parents:
        if parent == root:
            return False
        if should_skip_dir(root, parent, config):
            return True
    return False


def iter_files(root: Path, config: Config) -> Iterable[Path]:
    if config.respect_gitignore:
        candidates = git_paths(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        if candidates is not None:
            for item in candidates:
                file_path = root / item
                if file_path.is_file() and not path_has_excluded_parent(root, file_path, config) and should_include_file(file_path, config):
                    yield file_path
            return
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


def configured_layer(node_id: str, config: Config) -> str | None:
    for layer in config.layers:
        name = layer.get("name")
        patterns = layer.get("patterns", [])
        if isinstance(name, str) and any(fnmatch.fnmatch(node_id, str(pattern)) for pattern in patterns):
            return name
    return None


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


def python_semantics(text: str) -> tuple[list[str], list[str], list[str]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [], [], []
    imports: list[str] = []
    symbols: list[str] = []
    calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            imports.append(base)
            imports.extend(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(node.name)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.append(node.func.attr)
    return sorted(set(imports)), sorted(set(symbols)), sorted(set(calls))


def extract_symbols(path: Path, text: str) -> tuple[list[str], list[str]]:
    if path.suffix.lower() == ".py":
        _, symbols, calls = python_semantics(text)
        return symbols, calls
    patterns = [
        r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)",
        r"(?:export\s+)?class\s+([A-Za-z_$][\w$]*)",
        r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(",
        r"\b(?:class|interface|enum|struct|trait|func|fn)\s+([A-Za-z_][A-Za-z0-9_]*)",
    ]
    symbols = {match for pattern in patterns for match in re.findall(pattern, text)}
    return sorted(symbols), []


def extract_imports(path: Path, text: str) -> list[str]:
    if path.suffix.lower() == ".py":
        imports, _, _ = python_semantics(text)
        if imports:
            return imports
    patterns = IMPORT_PATTERNS.get(path.suffix.lower(), [])
    imports = []
    for pattern in patterns:
        imports.extend(pattern.findall(text))
    return imports


def add_edge(edges: list[dict], seen: set[tuple[str, str, str]], source: str, target: str, edge_type: str) -> None:
    edge = (source, target, edge_type)
    if edge in seen or source == target:
        return
    seen.add(edge)
    edges.append({"source": source, "target": target, "type": edge_type})


def resolve_relative_import(importer: str, target: str, file_lookup: set[str]) -> str | None:
    importer_parent = Path(importer).parent.as_posix()
    normalized_target = target
    if target.startswith("."):
        normalized_target = posixpath.normpath(posixpath.join(importer_parent, target))
    else:
        normalized_target = posixpath.normpath(posixpath.join(importer_parent, target))
    for suffix in IMPORTABLE_SUFFIXES:
        candidate = f"{normalized_target}{suffix}"
        if candidate in file_lookup:
            return candidate
    return None


def resolve_python_import(importer: str, target: str, file_lookup: set[str]) -> str | None:
    if target.startswith("."):
        level = len(target) - len(target.lstrip("."))
        module = target[level:].replace(".", "/")
        base_parts = list(Path(importer).parent.parts)
        if level > 1:
            base_parts = base_parts[: max(0, len(base_parts) - (level - 1))]
        base = Path(*base_parts).as_posix() if base_parts else ""
        normalized = posixpath.normpath(posixpath.join(base, module))
        for suffix in (".py", "/__init__.py"):
            candidate = f"{normalized}{suffix}"
            if candidate in file_lookup:
                return candidate
        return None
    normalized = target.replace(".", "/")
    for prefix in ("", "src/"):
        for suffix in (".py", "/__init__.py"):
            candidate = f"{prefix}{normalized}{suffix}"
            if candidate in file_lookup:
                return candidate
    return None


def resolve_language_import(importer: str, target: str, file_lookup: set[str]) -> str | None:
    ext = Path(importer).suffix.lower()
    if ext == ".rs":
        if target.startswith("crate::"):
            base = "src/" + target[len("crate::") :].replace("::", "/")
        else:
            base = (Path(importer).parent / target).as_posix()
        for suffix in (".rs", "/mod.rs"):
            if f"{base}{suffix}" in file_lookup:
                return f"{base}{suffix}"
    if ext in {".java", ".cs"}:
        base = target.replace(".", "/")
        leaf = base.rsplit("/", 1)[-1]
        candidates = [item for item in file_lookup if item.endswith(f"/{leaf}{ext}") or item == f"{leaf}{ext}"]
        if len(candidates) == 1:
            return candidates[0]
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


def load_ts_aliases(root: Path) -> list[tuple[str, list[str]]]:
    for name in ("tsconfig.json", "jsconfig.json"):
        path = root / name
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
            text = re.sub(r"/\*.*?\*/|//[^\r\n]*", "", text, flags=re.DOTALL)
            text = re.sub(r",\s*([}\]])", r"\1", text)
            data = json.loads(text)
        except (OSError, json.JSONDecodeError):
            continue
        options = data.get("compilerOptions", {})
        base_url = str(options.get("baseUrl", ".")).strip("./")
        aliases = []
        for pattern, targets in options.get("paths", {}).items():
            if not isinstance(targets, list):
                continue
            normalized = [posixpath.normpath(posixpath.join(base_url, str(item))) for item in targets]
            aliases.append((str(pattern), normalized))
        return aliases
    return []


def resolve_root_candidate(target: str, file_lookup: set[str]) -> str | None:
    normalized = posixpath.normpath(target).lstrip("./")
    for suffix in IMPORTABLE_SUFFIXES:
        candidate = f"{normalized}{suffix}"
        if candidate in file_lookup:
            return candidate
    return None


def resolve_ts_alias(target: str, aliases: list[tuple[str, list[str]]], file_lookup: set[str]) -> str | None:
    for pattern, replacements in aliases:
        if "*" in pattern:
            prefix, suffix = pattern.split("*", 1)
            if not target.startswith(prefix) or (suffix and not target.endswith(suffix)):
                continue
            captured = target[len(prefix) : len(target) - len(suffix) if suffix else None]
        elif target == pattern:
            captured = ""
        else:
            continue
        for replacement in replacements:
            resolved = resolve_root_candidate(replacement.replace("*", captured), file_lookup)
            if resolved:
                return resolved
    return None


def load_workspace_packages(root: Path, file_lookup: set[str], folder_lookup: set[str]) -> dict[str, str]:
    packages: dict[str, str] = {}
    for package_id in sorted(item for item in file_lookup if Path(item).name == "package.json"):
        try:
            data = json.loads((root / package_id).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        name = data.get("name")
        if not isinstance(name, str) or not name:
            continue
        parent = Path(package_id).parent.as_posix()
        entry_values = [data.get(key) for key in ("source", "module", "main", "types")]
        exports = data.get("exports")
        if isinstance(exports, str):
            entry_values.insert(0, exports)
        elif isinstance(exports, dict):
            root_export = exports.get(".")
            if isinstance(root_export, str):
                entry_values.insert(0, root_export)
            elif isinstance(root_export, dict):
                entry_values = list(root_export.values()) + entry_values
        for entry in entry_values:
            if not isinstance(entry, str):
                continue
            candidate = posixpath.normpath(posixpath.join(parent, entry))
            resolved = resolve_root_candidate(candidate, file_lookup)
            if resolved:
                packages[name] = resolved
                break
        else:
            packages[name] = "." if parent == "." else parent if parent in folder_lookup else package_id
    return packages


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
    ts_aliases: list[tuple[str, list[str]]] | None = None,
    workspace_packages: dict[str, str] | None = None,
) -> str | None:
    if target.startswith("."):
        if Path(importer).suffix.lower() == ".py":
            return resolve_python_import(importer, target, file_lookup)
        return resolve_relative_import(importer, target, file_lookup)
    if target.startswith("/"):
        return None
    if target.startswith(("http://", "https://")):
        return None

    alias_target = resolve_ts_alias(target, ts_aliases or [], file_lookup)
    if alias_target:
        return alias_target

    for package_name, package_target in sorted((workspace_packages or {}).items(), key=lambda item: -len(item[0])):
        if target == package_name:
            return package_target
        if target.startswith(f"{package_name}/"):
            subpath = target[len(package_name) + 1 :]
            package_root = Path(package_target).parent.as_posix() if package_target in file_lookup else package_target
            resolved = resolve_root_candidate(posixpath.join(package_root, subpath), file_lookup)
            if resolved:
                return resolved

    if "/" in target or target.endswith((".js", ".jsx", ".ts", ".tsx", ".py", ".go")):
        relative = resolve_relative_import(importer, target, file_lookup)
        if relative:
            return relative

    go_target = resolve_go_import(target, go_module_name, folder_lookup)
    if go_target:
        return go_target

    language_target = resolve_language_import(importer, target, file_lookup)
    if language_target:
        return language_target

    return resolve_python_import(importer, target, file_lookup)


def imported_symbol_targets(
    importer: str,
    text: str,
    file_lookup: set[str],
    folder_lookup: set[str],
    go_module_name: str | None,
    ts_aliases: list[tuple[str, list[str]]],
    workspace_packages: dict[str, str],
) -> dict[str, str]:
    symbols: dict[str, str] = {}
    for named_group, default_group, target in IMPORT_NAME_RE.findall(text):
        resolved = resolve_import(importer, target, file_lookup, folder_lookup, go_module_name, ts_aliases, workspace_packages)
        if not resolved:
            continue
        if default_group:
            symbols[default_group] = resolved
        for raw_name in named_group.split(","):
            name = raw_name.strip().split(" as ")[-1].strip()
            if name:
                symbols[name] = resolved
    return symbols


def is_test_file(node_id: str) -> bool:
    name = Path(node_id).name
    return name.startswith("test_") or name.endswith("_test.py") or any(marker in name for marker in TEST_MARKERS)


def source_candidates_for_test(node_id: str, file_lookup: set[str]) -> list[str]:
    path = Path(node_id)
    name = path.name
    candidates = []
    stems = {path.stem}
    for marker in TEST_MARKERS:
        if marker in name:
            stems.add(name.split(marker, 1)[0])
    if path.stem.startswith("test_"):
        stems.add(path.stem[5:])
    if path.stem.endswith("_test"):
        stems.add(path.stem[:-5])

    suffixes = [".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".cs", ".cpp", ".c"]
    parents = [path.parent, Path("src"), Path("app"), Path("lib"), Path(".")]
    for stem in sorted(stems):
        if not stem or stem == path.stem:
            continue
        for parent in parents:
            for suffix in suffixes:
                candidate = (parent / f"{stem}{suffix}").as_posix()
                if candidate in file_lookup and candidate != node_id:
                    candidates.append(candidate)
    return sorted(set(candidates))


def package_script_targets(root: Path, package_id: str, file_lookup: set[str]) -> list[str]:
    path = root / package_id
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return []
    targets = []
    for command in scripts.values():
        if not isinstance(command, str):
            continue
        for token in re.findall(r"[\w./-]+\.(?:js|jsx|ts|tsx|py|go|rs|sh|ps1)", command):
            normalized = token.lstrip("./")
            if normalized in file_lookup:
                targets.append(normalized)
    return sorted(set(targets))


def route_node(route_path: str) -> dict:
    return {"id": f"route:{route_path}", "type": "route", "label": route_path}


def enrich_graph(
    root: Path,
    nodes: list[dict],
    edges: list[dict],
    seen: set[tuple[str, str, str]],
    go_module_name: str | None,
    ts_aliases: list[tuple[str, list[str]]],
    workspace_packages: dict[str, str],
) -> None:
    file_nodes = [node for node in nodes if node["type"] == "file"]
    file_lookup = {node["id"] for node in file_nodes}
    folder_lookup = {node["id"] for node in nodes if node["type"] == "folder"}
    node_lookup = {node["id"]: node for node in nodes}

    for node in file_nodes:
        node_id = node["id"]
        file_path = root / node_id
        text = ""
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            pass

        if Path(node_id).name in CONFIG_FILES or node_id.endswith((".config.js", ".config.ts", ".config.mjs")):
            node["role"] = "config"
            add_edge(edges, seen, node_id, ".", "configures")

        if is_test_file(node_id):
            node["role"] = "test"
            for candidate in source_candidates_for_test(node_id, file_lookup):
                add_edge(edges, seen, node_id, candidate, "tests")

        if Path(node_id).name == "package.json":
            node["role"] = "manifest"
            for target in package_script_targets(root, node_id, file_lookup):
                add_edge(edges, seen, node_id, target, "runs")

        if node["ext"] not in {".js", ".jsx", ".ts", ".tsx"} or not text:
            continue

        symbol_targets = imported_symbol_targets(
            node_id, text, file_lookup, folder_lookup, go_module_name, ts_aliases, workspace_packages
        )
        for component_name in sorted(set(JSX_TAG_RE.findall(text))):
            target = symbol_targets.get(component_name)
            if target:
                add_edge(edges, seen, node_id, target, "renders")

        for route_path, component_name in ROUTE_ELEMENT_RE.findall(text):
            route_id = f"route:{route_path}"
            if route_id not in node_lookup:
                route = route_node(route_path)
                node_lookup[route_id] = route
                nodes.append(route)
            add_edge(edges, seen, node_id, route_id, "declares-route")
            target = symbol_targets.get(component_name)
            if target:
                add_edge(edges, seen, route_id, target, "renders")


def collect_file_nodes(
    root: Path,
    config: Config,
    previous_cache: dict[str, dict] | None = None,
) -> tuple[list[dict], dict[str, list[str]], dict[str, dict], dict[str, int]]:
    file_nodes = []
    raw_imports: dict[str, list[str]] = {}
    scan_cache: dict[str, dict] = {}
    stats = {"parsed": 0, "reused": 0}
    previous_cache = previous_cache or {}
    cache_context = hashlib.sha256(json.dumps(config.layers, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    for file_path in iter_files(root, config):
        rel_id = relative_id(root, file_path)
        stat = file_path.stat()
        signature = f"{stat.st_size}:{stat.st_mtime_ns}:{PARSER_VERSION}:{cache_context}"
        cached = previous_cache.get(rel_id)
        if cached and cached.get("signature") == signature and isinstance(cached.get("node"), dict):
            node = dict(cached["node"])
            imports = list(cached.get("imports", []))
            file_nodes.append(node)
            raw_imports[rel_id] = imports
            scan_cache[rel_id] = {"signature": signature, "node": node, "imports": imports}
            stats["reused"] += 1
            continue
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
        symbols, calls = extract_symbols(file_path, text)
        node = {
            "id": rel_id,
            "type": "file",
            "label": file_path.name,
            "ext": file_path.suffix.lower(),
            "bytes": stat.st_size,
            "lines": line_count,
            "mtime": int(stat.st_mtime),
            "symbols": symbols,
            "calls": calls,
            "layer": configured_layer(rel_id, config),
        }
        imports = extract_imports(file_path, text)
        file_nodes.append(node)
        raw_imports[rel_id] = imports
        scan_cache[rel_id] = {"signature": signature, "node": node, "imports": imports}
        stats["parsed"] += 1
    return file_nodes, raw_imports, scan_cache, stats


def build_edges(
    root: Path,
    file_nodes: list[dict],
    raw_imports: dict[str, list[str]],
    folder_nodes: list[dict],
    go_module_name: str | None,
    ts_aliases: list[tuple[str, list[str]]],
    workspace_packages: dict[str, str],
) -> list[dict]:
    edges = []
    file_lookup = {node["id"] for node in file_nodes}
    folder_lookup = {node["id"] for node in folder_nodes}
    seen = set()

    for node in file_nodes:
        path = Path(node["id"])
        parent_id = "." if str(path.parent) == "." else path.parent.as_posix()
        add_edge(edges, seen, parent_id, node["id"], "contains")

        while str(path.parent) != ".":
            child = path.parent.as_posix()
            parent = "." if str(path.parent.parent) == "." else path.parent.parent.as_posix()
            add_edge(edges, seen, parent, child, "contains")
            path = path.parent

    for importer, imports in raw_imports.items():
        for target in imports:
            resolved = resolve_import(
                importer, target, file_lookup, folder_lookup, go_module_name, ts_aliases, workspace_packages
            )
            if not resolved or resolved == importer:
                continue
            add_edge(edges, seen, importer, resolved, "imports")

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


def source_fingerprint(root: Path, config: Config) -> str:
    digest = hashlib.sha256()
    digest.update(f"graph={GRAPH_FORMAT_VERSION};parser={PARSER_VERSION}\n".encode())
    config_path = root / ".project-graph" / "config.json"
    if config_path.exists():
        try:
            digest.update(config_path.read_bytes())
        except OSError:
            pass
    for file_path in sorted(iter_files(root, config), key=lambda item: relative_id(root, item)):
        try:
            stat = file_path.stat()
        except OSError:
            continue
        record = f"{relative_id(root, file_path)}\0{stat.st_size}\0{stat.st_mtime_ns}\n"
        digest.update(record.encode("utf-8", errors="surrogatepass"))
    return digest.hexdigest()


def graph_is_fresh(output_dir: Path, fingerprint: str) -> bool:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists():
        return False
    try:
        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return False
    return (
        manifest.get("format_version") == GRAPH_FORMAT_VERSION
        and manifest.get("parser_version") == PARSER_VERSION
        and manifest.get("source_fingerprint") == fingerprint
    )


def read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_graph(output_dir: Path) -> tuple[list[dict], list[dict]]:
    return read_json(output_dir / "nodes.json"), read_json(output_dir / "edges.json")  # type: ignore[return-value]


def load_scan_cache(output_dir: Path) -> dict[str, dict]:
    path = output_dir / "scan-cache.json"
    if not path.exists():
        return {}
    try:
        data = read_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def build_graph(
    root: Path,
    config: Config,
    go_module_name: str | None,
    ts_aliases: list[tuple[str, list[str]]],
    previous_cache: dict[str, dict] | None = None,
) -> tuple[list[dict], list[dict], list[dict], dict[str, dict], dict[str, int]]:
    file_nodes, raw_imports, scan_cache, scan_stats = collect_file_nodes(root, config, previous_cache)
    folder_nodes = build_folder_nodes(root, file_nodes)
    nodes = folder_nodes + sorted(file_nodes, key=lambda item: item["id"])
    file_lookup = {node["id"] for node in file_nodes}
    folder_lookup = {node["id"] for node in folder_nodes}
    workspace_packages = load_workspace_packages(root, file_lookup, folder_lookup)
    edges = build_edges(root, file_nodes, raw_imports, folder_nodes, go_module_name, ts_aliases, workspace_packages)
    seen = {(edge["source"], edge["target"], edge["type"]) for edge in edges}
    enrich_graph(root, nodes, edges, seen, go_module_name, ts_aliases, workspace_packages)
    return file_nodes, nodes, edges, scan_cache, scan_stats


def write_graph(
    root: Path,
    output_dir: Path,
    config: Config,
    file_nodes: list[dict],
    nodes: list[dict],
    edges: list[dict],
    latest_mtime: int,
    fingerprint: str,
    scan_cache: dict[str, dict],
    scan_stats: dict[str, int],
) -> None:
    write_json(output_dir / "nodes.json", nodes)
    write_json(output_dir / "edges.json", edges)
    write_json(output_dir / "scan-cache.json", scan_cache)
    write_json(
        output_dir / "manifest.json",
        build_manifest(root, output_dir, config, file_nodes, edges, latest_mtime, fingerprint, scan_stats),
    )
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
            distance = current_depth + 1
            confidence = "high" if distance == 1 else "medium" if distance == 2 else "low"
            rows.append(f"`{importer}` imports `{current}` (distance {distance}, confidence {confidence})")
            queue.append((importer, current_depth + 1))
            if len(rows) >= limit:
                break

    print_rows(f"Likely Impact From `{start}`", rows or ["No import dependents detected"])
    return 0


def query_direction(nodes: list[dict], edges: list[dict], start: str, reverse: bool, limit: int) -> int:
    if start not in {node["id"] for node in nodes}:
        print(f"Node not found: {start}", file=sys.stderr)
        return 1
    rows = []
    for edge in edges:
        if edge["type"] != "imports":
            continue
        if reverse and edge["target"] == start:
            rows.append(f"`{edge['source']}` imports `{start}`")
        elif not reverse and edge["source"] == start:
            rows.append(f"`{start}` imports `{edge['target']}`")
    title = "Dependents Of" if reverse else "Dependencies Of"
    print_rows(f"{title} `{start}`", sorted(rows)[:limit] or ["None detected"])
    return 0


def query_path(nodes: list[dict], edges: list[dict], start: str, end: str, limit: int) -> int:
    node_ids = {node["id"] for node in nodes}
    missing = [item for item in (start, end) if item not in node_ids]
    if missing:
        print(f"Node not found: {', '.join(missing)}", file=sys.stderr)
        return 1
    adjacency: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for edge in edges:
        if edge["type"] == "contains":
            continue
        adjacency[edge["source"]].append((edge["target"], edge))
        adjacency[edge["target"]].append((edge["source"], edge))
    queue = deque([start])
    previous: dict[str, tuple[str, dict] | None] = {start: None}
    while queue and end not in previous:
        current = queue.popleft()
        for neighbor, edge in adjacency[current]:
            if neighbor not in previous:
                previous[neighbor] = (current, edge)
                queue.append(neighbor)
    if end not in previous:
        print_rows(f"Path `{start}` → `{end}`", ["No relationship path detected"])
        return 0
    steps = []
    current = end
    while previous[current] is not None:
        prior, edge = previous[current]  # type: ignore[misc]
        arrow = f"--{edge['type']}-->" if edge["source"] == prior else f"<--{edge['type']}--"
        steps.append(f"`{prior}` {arrow} `{current}`")
        current = prior
    print_rows(f"Path `{start}` → `{end}`", list(reversed(steps))[:limit])
    return 0


def import_cycles(edges: list[dict]) -> list[list[str]]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge["type"] == "imports":
            adjacency[edge["source"]].append(edge["target"])
    index = 0
    stack: list[str] = []
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for neighbor in adjacency[node]:
            if neighbor not in indices:
                visit(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[neighbor])
        if lowlinks[node] == indices[node]:
            component = []
            while stack:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node:
                    break
            if len(component) > 1 or node in adjacency[node]:
                components.append(sorted(component))

    all_nodes = set(adjacency) | {target for values in adjacency.values() for target in values}
    for node in sorted(all_nodes):
        if node not in indices:
            visit(node)
    return sorted(components, key=lambda item: (-len(item), item))


def query_cycles(edges: list[dict], limit: int) -> None:
    cycles = import_cycles(edges)
    rows = [" → ".join(f"`{node}`" for node in component + [component[0]]) for component in cycles[:limit]]
    print_rows("Circular Import Components", rows or ["None detected"])


def query_untested(nodes: list[dict], edges: list[dict], limit: int) -> None:
    tested = {edge["target"] for edge in edges if edge["type"] == "tests"}
    referenced = Counter(edge["target"] for edge in edges if edge["type"] == "imports")
    roles = {node["id"]: node.get("role") for node in nodes if node["type"] == "file"}
    candidates = [(node, count) for node, count in referenced.items() if node not in tested and roles.get(node) != "test"]
    candidates.sort(key=lambda item: (-item[1], item[0]))
    rows = [f"`{node}` ({count} importer{'s' if count != 1 else ''})" for node, count in candidates[:limit]]
    print_rows("Referenced Source Without Linked Tests", rows or ["None detected"])


def changed_files(root: Path, reference: str | None = None) -> list[str] | None:
    if reference:
        changed = git_paths(root, "diff", "--name-only", "-z", f"{reference}...HEAD")
        return None if changed is None else [item for item in changed if not item.startswith(".project-graph/")]
    unstaged = git_paths(root, "diff", "--name-only", "-z")
    staged = git_paths(root, "diff", "--cached", "--name-only", "-z")
    untracked = git_paths(root, "ls-files", "--others", "--exclude-standard", "-z")
    if unstaged is None or staged is None or untracked is None:
        return None
    return sorted(item for item in set(unstaged + staged + untracked) if not item.startswith(".project-graph/"))


def query_changed(root: Path, reference: str | None, limit: int) -> int:
    changed = changed_files(root, reference)
    if changed is None:
        print("Git repository or Git executable not available", file=sys.stderr)
        return 1
    title = f"Changed Files Since `{reference}`" if reference else "Changed Working-Tree Files"
    print_rows(title, [f"`{item}`" for item in changed[:limit]] or ["None detected"])
    return 0


def query_impact_diff(root: Path, nodes: list[dict], edges: list[dict], reference: str, depth: int, limit: int) -> int:
    changed = changed_files(root, reference)
    if changed is None:
        print("Git repository or Git executable not available", file=sys.stderr)
        return 1
    node_ids = {node["id"] for node in nodes}
    reverse: dict[str, list[str]] = defaultdict(list)
    tests: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge["type"] == "imports":
            reverse[edge["target"]].append(edge["source"])
        elif edge["type"] == "tests":
            tests[edge["target"]].append(edge["source"])
    rows = []
    for source in changed:
        if source not in node_ids:
            continue
        queue = deque([(source, 0)])
        seen = {source}
        impacted = []
        while queue:
            current, distance = queue.popleft()
            if distance >= depth:
                continue
            for importer in sorted(reverse[current]):
                if importer not in seen:
                    seen.add(importer)
                    impacted.append(importer)
                    queue.append((importer, distance + 1))
        related_tests = sorted({test for item in seen for test in tests[item]})
        detail = f"{len(impacted)} dependent(s)"
        if related_tests:
            detail += f"; tests: {', '.join(related_tests[:3])}"
        rows.append(f"`{source}` → {detail}")
    print_rows(f"Impact Since `{reference}`", rows[:limit] or ["No graph-connected changes detected"])
    return 0


def git_change_counts(root: Path) -> Counter | None:
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "log", "--format=", "--name-only", "--no-renames", "-n", "500"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return Counter(line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip())


def query_hotspots(root: Path, nodes: list[dict], edges: list[dict], limit: int) -> int:
    changes = git_change_counts(root)
    if changes is None:
        print("Git repository or Git executable not available", file=sys.stderr)
        return 1
    degrees = import_degrees(nodes, edges)
    ranked = []
    for node, count in changes.items():
        if node in degrees:
            connectivity = degrees[node]["in"] + degrees[node]["out"]
            ranked.append((count * max(connectivity, 1), node, count, connectivity))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    rows = [f"`{node}` — score {score}, {count} changes, {connectivity} import links" for score, node, count, connectivity in ranked[:limit]]
    print_rows("Git × Dependency Hotspots", rows or ["None detected"])
    return 0


def ignored_paths(root: Path, config: Config, limit: int) -> list[str]:
    rows = []
    for current_root, dirnames, filenames in os.walk(root):
        current = Path(current_root)
        kept = []
        for name in dirnames:
            path = current / name
            if should_skip_dir(root, path, config):
                rows.append(f"`{relative_id(root, path)}/` — excluded directory")
            else:
                kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            path = current / name
            if any(fnmatch.fnmatch(name, pattern) for pattern in config.exclude_globs):
                rows.append(f"`{relative_id(root, path)}` — excluded file pattern")
        if len(rows) >= limit:
            break
    if config.respect_gitignore:
        for item in git_paths(root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z") or []:
            rows.append(f"`{item}` — Git ignore rule")
            if len(rows) >= limit:
                break
    return rows[:limit]


def query_entrypoints(nodes: list[dict], edges: list[dict], limit: int) -> None:
    run_targets = {edge["target"] for edge in edges if edge["type"] == "runs"}
    entry_names = {"__main__.py", "main.py", "main.go", "main.rs", "index.js", "index.ts", "app.py", "server.py", "Program.cs"}
    candidates = {
        node["id"]
        for node in nodes
        if node["type"] == "file" and (node["id"] in run_targets or node["label"] in entry_names)
    }
    print_rows("Likely Entrypoints", [f"`{item}`" for item in sorted(candidates)[:limit]] or ["None detected"])


def query_routes(edges: list[dict], limit: int) -> None:
    rows = [f"`{edge['source']}` declares `{edge['target']}`" for edge in edges if edge["type"] == "declares-route"]
    print_rows("Detected Routes", rows[:limit] or ["None detected"])


def query_violations(config: Config, nodes: list[dict], edges: list[dict], limit: int) -> None:
    if not config.layers:
        print_rows("Architecture Layer Violations", ["No layers configured"])
        return
    layer_rules = {str(layer.get("name")): layer for layer in config.layers if layer.get("name")}
    node_layers = {node["id"]: node.get("layer") for node in nodes if node["type"] == "file"}
    rows = []
    for edge in edges:
        if edge["type"] != "imports":
            continue
        source_layer = node_layers.get(edge["source"])
        target_layer = node_layers.get(edge["target"])
        if not source_layer or not target_layer or source_layer == target_layer:
            continue
        rule = layer_rules.get(source_layer, {})
        if "may_import" not in rule:
            continue
        allowed = {str(item) for item in rule.get("may_import", [])}
        if target_layer not in allowed:
            rows.append(
                f"`{edge['source']}` ({source_layer}) imports `{edge['target']}` ({target_layer}); allowed: {', '.join(sorted(allowed)) or 'none'}"
            )
    print_rows("Architecture Layer Violations", rows[:limit] or ["None detected"])


def run_query(root: Path, config: Config, args: argparse.Namespace, nodes: list[dict], edges: list[dict]) -> int:
    limit = max(args.limit, 1)
    if args.around:
        return query_around(nodes, edges, args.around, max(args.depth, 0), limit)
    if args.impacted:
        return query_impacted(nodes, edges, args.impacted, max(args.depth, 0), limit)
    if args.dependencies:
        return query_direction(nodes, edges, args.dependencies, False, limit)
    if args.dependents:
        return query_direction(nodes, edges, args.dependents, True, limit)
    path_args = args.path or args.why_connected
    if path_args:
        return query_path(nodes, edges, path_args[0], path_args[1], limit)
    if args.cycles:
        query_cycles(edges, limit)
        return 0
    if args.untested:
        query_untested(nodes, edges, limit)
        return 0
    if args.changed:
        return query_changed(root, None, limit)
    if args.diff:
        return query_changed(root, args.diff, limit)
    if args.impact_diff:
        return query_impact_diff(root, nodes, edges, args.impact_diff, max(args.depth, 0), limit)
    if args.hotspots:
        return query_hotspots(root, nodes, edges, limit)
    if args.ignored:
        print_rows("Ignored Paths", ignored_paths(root, config, limit) or ["None detected"])
        return 0
    if args.entrypoints:
        query_entrypoints(nodes, edges, limit)
        return 0
    if args.routes:
        query_routes(edges, limit)
        return 0
    if args.violations:
        query_violations(config, nodes, edges, limit)
        return 0
    if args.orphans:
        query_orphans(nodes, edges, limit)
        return 0
    if args.central:
        query_central(nodes, edges, limit)
        return 0
    return 0


def compute_summary(root: Path, nodes: list[dict], edges: list[dict]) -> str:
    files = [node for node in nodes if node["type"] == "file"]
    folders = [node for node in nodes if node["type"] == "folder"]
    routes = [node for node in nodes if node["type"] == "route"]
    imports_in = Counter()
    imports_out = Counter()
    edge_types = Counter(edge["type"] for edge in edges)
    folder_counts = Counter()
    orphan_files = []
    test_edges = []
    config_files = []
    route_edges = []
    symbol_count = sum(len(node.get("symbols", [])) for node in files)

    for edge in edges:
        if edge["type"] == "imports":
            imports_out[edge["source"]] += 1
            imports_in[edge["target"]] += 1
        elif edge["type"] == "tests":
            test_edges.append(edge)
        elif edge["type"] == "declares-route":
            route_edges.append(edge)

    for file_node in files:
        parent = Path(file_node["id"]).parent.as_posix()
        folder_counts[parent or "."] += 1
        if imports_in[file_node["id"]] == 0 and imports_out[file_node["id"]] == 0:
            orphan_files.append(file_node["id"])
        if file_node.get("role") in {"config", "manifest"}:
            config_files.append(file_node["id"])

    top_in = [node for node, _ in imports_in.most_common(5)]
    top_out = [node for node, _ in imports_out.most_common(5)]
    biggest_folders = [folder for folder, _ in folder_counts.most_common(5)]
    cycles = import_cycles(edges)
    tested = {edge["target"] for edge in test_edges}
    untested_referenced = [node for node, _ in imports_in.most_common() if node not in tested]
    run_targets = {edge["target"] for edge in edges if edge["type"] == "runs"}
    entry_names = {"__main__.py", "main.py", "main.go", "main.rs", "index.js", "index.ts", "app.py", "server.py", "Program.cs"}
    entrypoints = sorted({node["id"] for node in files if node["id"] in run_targets or node["label"] in entry_names})

    lines = [
        f"# Project Graph Summary for {root.name}",
        "",
        f"- Files scanned: {len(files)}",
        f"- Folders captured: {max(len(folders) - 1, 0)}",
        f"- Route nodes: {len(routes)}",
        f"- Total edges: {len(edges)}",
        f"- Import edges: {sum(1 for edge in edges if edge['type'] == 'imports')}",
        f"- Symbols detected: {symbol_count}",
        f"- Circular import components: {len(cycles)}",
        "",
        "## Edge Types",
    ]
    lines.extend(f"- `{edge_type}`: {count}" for edge_type, count in edge_types.most_common() or [("none", 0)])
    lines.extend([
        "",
        "## Largest Folders",
    ])
    lines.extend(f"- `{folder}`" for folder in biggest_folders or ["."])
    lines.extend(["", "## Most Referenced Files"])
    lines.extend(f"- `{item}`" for item in top_in or ["None detected"])
    lines.extend(["", "## Most Connected Importers"])
    lines.extend(f"- `{item}`" for item in top_out or ["None detected"])
    lines.extend(["", "## Config And Manifest Files"])
    lines.extend(f"- `{item}`" for item in config_files[:10] or ["None detected"])
    lines.extend(["", "## Test Links"])
    lines.extend(f"- `{edge['source']}` tests `{edge['target']}`" for edge in test_edges[:10] or [])
    if not test_edges:
        lines.append("- None detected")
    lines.extend(["", "## Route Declarations"])
    lines.extend(f"- `{edge['source']}` declares `{edge['target']}`" for edge in route_edges[:10] or [])
    if not route_edges:
        lines.append("- None detected")
    lines.extend(["", "## Orphan Candidates"])
    lines.extend(f"- `{item}`" for item in orphan_files[:10] or ["None detected"])
    lines.extend(["", "## Likely Entrypoints"])
    lines.extend(f"- `{item}`" for item in entrypoints[:10] or ["None detected"])
    lines.extend(["", "## Circular Import Components"])
    lines.extend("- " + " → ".join(f"`{item}`" for item in component) for component in cycles[:10])
    if not cycles:
        lines.append("- None detected")
    lines.extend(["", "## Referenced Source Without Linked Tests"])
    lines.extend(f"- `{item}`" for item in untested_referenced[:10] or ["None detected"])
    return "\n".join(lines) + "\n"


def build_manifest(
    root: Path,
    output_dir: Path,
    config: Config,
    files: list[dict],
    edges: list[dict],
    latest_mtime: int,
    fingerprint: str,
    scan_stats: dict[str, int],
) -> dict:
    return {
        "format_version": GRAPH_FORMAT_VERSION,
        "parser_version": PARSER_VERSION,
        "root": str(root),
        "output": str(output_dir),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_latest_mtime": latest_mtime,
        "source_fingerprint": fingerprint,
        "parsed_file_count": scan_stats.get("parsed", 0),
        "reused_file_count": scan_stats.get("reused", 0),
        "file_count": len(files),
        "route_count": sum(1 for edge in edges if edge["type"] == "declares-route"),
        "edge_count": len(edges),
        "edge_types": dict(sorted(Counter(edge["type"] for edge in edges).items())),
        "include_extensions": sorted(config.include_extensions),
        "exclude_dirs": sorted(config.exclude_dirs),
        "exclude_dir_globs": sorted(config.exclude_dir_globs),
        "exclude_path_prefixes": sorted(config.exclude_path_prefixes),
        "exclude_globs": sorted(config.exclude_globs),
        "max_file_bytes": config.max_file_bytes,
        "respect_gitignore": config.respect_gitignore,
        "layers": config.layers,
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
      --route: #7c3aed;
      --accent: #1b4332;
    }}
    body.dark {{
      --bg: #111827;
      --panel: rgba(17,24,39,0.94);
      --text: #f3f4f6;
      --muted: #a7b0c0;
      --line: rgba(148,163,184,0.28);
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
    button {{
      width: 100%;
      padding: 9px 12px;
      margin: 0 0 14px;
      border: 1px solid rgba(0,0,0,0.12);
      border-radius: 10px;
      cursor: pointer;
      color: var(--text);
      background: rgba(127,127,127,0.12);
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
        <option value="route">Routes</option>
      </select>
      <label for="edge-kind">Relationship type</label>
      <select id="edge-kind">
        <option value="all">All relationships</option>
        <option value="imports">Imports</option>
        <option value="tests">Tests</option>
        <option value="configures">Configures</option>
        <option value="runs">Runs</option>
        <option value="declares-route">Routes</option>
        <option value="renders">Renders</option>
      </select>
      <button id="theme" type="button">Toggle dark mode</button>
      <div class="legend">
        <span><span class="swatch" style="background: var(--folder)"></span>Folder</span>
        <span><span class="swatch" style="background: var(--file)"></span>File</span>
        <span><span class="swatch" style="background: var(--route)"></span>Route</span>
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
    const edgeKind = document.getElementById("edge-kind");
    const theme = document.getElementById("theme");
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

    function visibleEdge(edge) {{
      return edgeKind.value === "all" || edge.type === edgeKind.value;
    }}

    function draw() {{
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      ctx.clearRect(0, 0, width, height);
      ctx.save();
      ctx.translate(width / 2, height / 2);

      for (const edge of edges) {{
        if (!visibleEdge(edge) || !visible(edge.sourceNode) || !visible(edge.targetNode)) continue;
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
        const radius = node.type === "folder" ? 6 : (node.type === "route" ? 5 : 4);
        ctx.beginPath();
        ctx.fillStyle = node.type === "folder" ? "#c97a44" : (node.type === "route" ? "#7c3aed" : "#215a6d");
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
        const radius = node.type === "folder" ? 8 : (node.type === "route" ? 7 : 6);
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
      if (node.role) lines.push("role: " + node.role);
      if (node.symbols && node.symbols.length) lines.push("symbols: " + node.symbols.slice(0, 12).join(", "));
      if (node.calls && node.calls.length) lines.push("calls: " + node.calls.slice(0, 12).join(", "));
      lines.push("");
      lines.push("relationships:");
      const related = edges
        .filter(edge => visibleEdge(edge) && (edge.source === node.id || edge.target === node.id))
        .slice(0, 16)
        .map(edge => "- " + edge.source + " --" + edge.type + "--> " + edge.target);
      lines.push(...(related.length ? related : ["- none"]));
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
    edgeKind.addEventListener("change", () => {{
      if (selected) renderDetails(selected);
    }});
    theme.addEventListener("click", () => document.body.classList.toggle("dark"));

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
    ts_aliases = load_ts_aliases(root)
    latest_mtime = latest_source_mtime(root, config)
    fingerprint = source_fingerprint(root, config)
    fresh = not args.force and graph_is_fresh(output_dir, fingerprint)
    if fresh:
        nodes, edges = load_graph(output_dir)
        print(f"Graph is already fresh at {output_dir}")
    else:
        previous_cache = load_scan_cache(output_dir)
        file_nodes, nodes, edges, scan_cache, scan_stats = build_graph(
            root, config, go_module_name, ts_aliases, previous_cache
        )
        write_graph(
            root,
            output_dir,
            config,
            file_nodes,
            nodes,
            edges,
            latest_mtime,
            fingerprint,
            scan_cache,
            scan_stats,
        )
        print(f"Wrote graph artifacts to {output_dir}")

    return run_query(root, config, args, nodes, edges)


if __name__ == "__main__":
    sys.exit(main())
