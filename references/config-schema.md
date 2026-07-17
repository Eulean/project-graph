# Project Graph Config

Use an optional `.project-graph/config.json` file in a repository root when the default scan rules are too broad or too narrow.

## Supported Keys

```json
{
  "include_extensions": [".go", ".py", ".ts", ".tsx", ".js", ".jsx", ".md"],
  "exclude_dirs": ["internal-fixtures"],
  "exclude_dir_globs": ["*-generated", "*.egg-info"],
  "exclude_path_prefixes": ["tools/zig", "vendor/generated"],
  "exclude_globs": ["*.fixture.json"],
  "use_default_excludes": true,
  "respect_gitignore": true,
  "max_file_bytes": 262144,
  "layers": [
    {"name": "ui", "patterns": ["src/ui/**"], "may_import": ["application", "shared"]},
    {"name": "application", "patterns": ["src/application/**"], "may_import": ["domain", "shared"]},
    {"name": "domain", "patterns": ["src/domain/**"], "may_import": ["shared"]},
    {"name": "shared", "patterns": ["src/shared/**"], "may_import": []}
  ]
}
```

## Notes

- Omit the file entirely if defaults are good enough.
- Default exclusions cover common dependency, vendor, build, generated, cache, virtual-environment, IDE, and version-control directories. Examples include `node_modules`, `vendor`, `dist`, `build`, `target`, `bin`, `obj`, `.next`, `.venv`, and cache directories.
- Use `include_extensions` to limit the scan to source and note files that matter.
- Known config filenames such as `package.json`, `pyproject.toml`, `tsconfig.json`, `Dockerfile`, and `Makefile` are included even when their extensions are not listed.
- Use `exclude_dirs` to add repository-specific folder names. These entries extend the defaults.
- Use `exclude_dir_globs` to add folder-name patterns such as `*-generated`. These entries extend the defaults.
- Use `exclude_path_prefixes` for noisy nested paths that are not named consistently enough for `exclude_dirs`.
- Use `exclude_globs` to add generated-file patterns inside otherwise useful folders. These entries extend the defaults.
- Set `use_default_excludes` to `false` only when the repository intentionally needs to scan normally ignored directories. In that mode, `exclude_dirs`, `exclude_dir_globs`, and `exclude_globs` replace the defaults.
- Use `max_file_bytes` to skip oversized files that add little graph value.
- Keep `respect_gitignore` enabled to use Git's tracked/untracked file view and nested ignore rules. Set it to `false` when ignored source must be graphed.
- Use `layers` to assign files by glob and enforce allowed cross-layer imports with `--violations`. Imports within the same layer are always allowed. Omitting `may_import` leaves that layer unrestricted; an empty list permits no cross-layer imports.
