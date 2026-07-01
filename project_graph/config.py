from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from dataclasses import dataclass
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

CONFIG_KEYS = {
    "include_extensions",
    "exclude_dirs",
    "exclude_path_prefixes",
    "exclude_globs",
    "max_file_bytes",
}

@dataclass
class Config:
    include_extensions: set[str]
    exclude_dirs: set[str]
    exclude_path_prefixes: set[str]
    exclude_globs: set[str]
    max_file_bytes: int

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
    validate_config(raw, config_path)

    return Config(
        include_extensions=set(raw.get("include_extensions", DEFAULT_INCLUDE_EXTENSIONS)),
        exclude_dirs=set(raw.get("exclude_dirs", DEFAULT_EXCLUDE_DIRS)),
        exclude_path_prefixes=set(raw.get("exclude_path_prefixes", [])),
        exclude_globs=set(raw.get("exclude_globs", DEFAULT_EXCLUDE_GLOBS)),
        max_file_bytes=int(raw.get("max_file_bytes", DEFAULT_MAX_FILE_BYTES)),
    )


def validate_config(raw: object, config_path: Path) -> None:
    if not isinstance(raw, dict):
        raise ValueError(f"{config_path} must contain a JSON object")
    unknown = sorted(set(raw) - CONFIG_KEYS)
    if unknown:
        raise ValueError(f"{config_path} has unsupported key(s): {', '.join(unknown)}")
    for key in ("include_extensions", "exclude_dirs", "exclude_path_prefixes", "exclude_globs"):
        if key in raw and (not isinstance(raw[key], list) or not all(isinstance(item, str) for item in raw[key])):
            raise ValueError(f"{config_path} key `{key}` must be a list of strings")
    if "max_file_bytes" in raw and (not isinstance(raw["max_file_bytes"], int) or raw["max_file_bytes"] <= 0):
        raise ValueError(f"{config_path} key `max_file_bytes` must be a positive integer")


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


def source_inventory(root: Path, config: Config) -> list[dict]:
    inventory = []
    for file_path in iter_files(root, config):
        try:
            stat = file_path.stat()
        except OSError:
            continue
        inventory.append(
            {
                "path": relative_id(root, file_path),
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
            }
        )
    config_path = root / ".project-graph" / "config.json"
    if config_path.exists():
        try:
            stat = config_path.stat()
            inventory.append(
                {
                    "path": ".project-graph/config.json",
                    "size": stat.st_size,
                    "mtime": int(stat.st_mtime),
                }
            )
        except OSError:
            pass
    return sorted(inventory, key=lambda item: item["path"])


def inventory_hash(inventory: list[dict]) -> str:
    payload = json.dumps(inventory, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


