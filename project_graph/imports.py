from __future__ import annotations

import ast
import json
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path

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
class TsConfig:
    base_url: str | None
    paths: list[tuple[str, list[str]]]
def extract_imports(path: Path, text: str) -> list[str]:
    if path.suffix.lower() == ".py":
        return extract_python_imports(text)
    patterns = IMPORT_PATTERNS.get(path.suffix.lower(), [])
    imports = []
    for pattern in patterns:
        imports.extend(pattern.findall(text))
    return imports


def extract_python_imports(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        patterns = IMPORT_PATTERNS[".py"]
        imports = []
        for pattern in patterns:
            imports.extend(pattern.findall(text))
        return imports

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            if node.module:
                imports.append(f"{prefix}{node.module}")
            elif node.level:
                imports.extend(f"{prefix}{alias.name}" for alias in node.names)
    return imports


def resolve_relative_import(importer: str, target: str, file_lookup: set[str]) -> str | None:
    importer_parent = Path(importer).parent.as_posix()
    if target.startswith(("./", "../")):
        base_target = posixpath.normpath(posixpath.join(importer_parent, target))
    elif target.startswith("."):
        match = re.match(r"^(\.+)(.*)$", target)
        if not match:
            return None
        dots, module_tail = match.groups()
        base_target = importer_parent
        for _ in range(max(len(dots) - 1, 0)):
            base_target = posixpath.dirname(base_target)
        module_tail = module_tail.lstrip(".").replace(".", "/")
        if module_tail:
            base_target = posixpath.join(base_target, module_tail)
    else:
        base_target = posixpath.normpath(posixpath.join(importer_parent, target))
    for suffix in IMPORTABLE_SUFFIXES:
        candidate = f"{base_target}{suffix}"
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


def load_ts_config(root: Path) -> TsConfig:
    tsconfig_path = root / "tsconfig.json"
    if not tsconfig_path.exists():
        return TsConfig(base_url=None, paths=[])
    try:
        raw = json.loads(tsconfig_path.read_text(encoding="utf-8", errors="ignore"))
    except json.JSONDecodeError:
        return TsConfig(base_url=None, paths=[])
    compiler_options = raw.get("compilerOptions", {}) if isinstance(raw, dict) else {}
    if not isinstance(compiler_options, dict):
        return TsConfig(base_url=None, paths=[])
    base_url = compiler_options.get("baseUrl")
    if not isinstance(base_url, str):
        base_url = None
    raw_paths = compiler_options.get("paths", {})
    paths = []
    if isinstance(raw_paths, dict):
        for pattern, replacements in raw_paths.items():
            if isinstance(pattern, str) and isinstance(replacements, list):
                valid_replacements = [item for item in replacements if isinstance(item, str)]
                if valid_replacements:
                    paths.append((pattern, valid_replacements))
    return TsConfig(base_url=base_url, paths=paths)


def resolve_go_import(target: str, go_module_name: str | None, folder_lookup: set[str]) -> str | None:
    if not go_module_name:
        return None
    if target == go_module_name:
        return "."
    if not target.startswith(f"{go_module_name}/"):
        return None
    folder_id = target[len(go_module_name) + 1 :]
    return folder_id if folder_id in folder_lookup else None


def resolve_ts_alias_import(target: str, ts_config: TsConfig, file_lookup: set[str]) -> str | None:
    candidates = []
    for pattern, replacements in ts_config.paths:
        if "*" in pattern:
            prefix, suffix = pattern.split("*", 1)
            if not target.startswith(prefix) or not target.endswith(suffix):
                continue
            wildcard = target[len(prefix) : len(target) - len(suffix) if suffix else len(target)]
            candidates.extend(replacement.replace("*", wildcard) for replacement in replacements)
        elif target == pattern:
            candidates.extend(replacements)

    if ts_config.base_url:
        candidates.append(posixpath.join(ts_config.base_url, target))

    for candidate in candidates:
        normalized = posixpath.normpath(candidate.lstrip("./"))
        for suffix in IMPORTABLE_SUFFIXES:
            resolved = f"{normalized}{suffix}"
            if resolved in file_lookup:
                return resolved
    return None


def resolve_import(
    importer: str,
    target: str,
    file_lookup: set[str],
    folder_lookup: set[str],
    go_module_name: str | None,
    ts_config: TsConfig,
) -> str | None:
    if target.startswith("."):
        return resolve_relative_import(importer, target, file_lookup)
    if target.startswith("/"):
        return None
    if target.startswith(("http://", "https://")):
        return None

    if "/" in target or target.endswith((".js", ".jsx", ".ts", ".tsx", ".py", ".go")):
        relative = resolve_relative_import(importer, target, file_lookup)
        if relative:
            return relative

    if Path(importer).suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}:
        alias_target = resolve_ts_alias_import(target, ts_config, file_lookup)
        if alias_target:
            return alias_target

    go_target = resolve_go_import(target, go_module_name, folder_lookup)
    if go_target:
        return go_target

    return resolve_python_import(target, file_lookup)
