# Project Graph Config

Use an optional `.project-graph/config.json` file in a repository root when the default scan rules are too broad or too narrow.

## Supported Keys

```json
{
  "include_extensions": [".go", ".py", ".ts", ".tsx", ".js", ".jsx", ".md"],
  "exclude_dirs": [".git", "node_modules", "dist", "build", ".venv", "__pycache__"],
  "exclude_path_prefixes": ["tools/zig", "vendor/generated"],
  "exclude_globs": ["*.min.js", "*.generated.*", "*.snap"],
  "max_file_bytes": 262144
}
```

## Notes

- Omit the file entirely if defaults are good enough.
- Use `include_extensions` to limit the scan to source and note files that matter.
- Use `exclude_dirs` for vendor, build, cache, or generated folders.
- Use `exclude_path_prefixes` for noisy nested paths that are not named consistently enough for `exclude_dirs`.
- Use `exclude_globs` for generated files that live inside otherwise useful folders.
- Use `max_file_bytes` to skip oversized files that add little graph value.
