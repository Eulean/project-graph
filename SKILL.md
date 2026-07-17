---
name: project-graph
description: Build and reuse a semantic, Git-aware project graph for repository navigation, architecture mapping, dependency and change-impact analysis, test planning, boundary enforcement, and token-efficient code understanding. Use when Codex needs to understand a codebase across many files, inspect dependencies or dependents, explain paths and impact, analyze a Git diff, find cycles, hotspots, untested or orphaned files, inspect routes/config/scripts/symbols, enforce configured layers, or open an interactive graph viewer.
---

# Project Graph

## Overview

Build compact graph artifacts for a repository, then answer from those artifacts before reading raw source files. Prefer cached graph context for architecture questions, dependency exploration, Git-aware impact analysis, and discovery of symbols, config, tests, scripts, routes, and rendered components.

## Workflow

1. Check whether the repository already contains `.project-graph/manifest.json` and `.project-graph/summary.md`.
2. If the graph is missing or stale, run `scripts/build_project_graph.py --root <repo> --output <repo>/.project-graph`.
3. Run the smallest relevant query before opening JSON. Use dependency/path queries for code questions, Git queries for changes, and architecture queries for structural risks.
4. Read the generated summary and only open `nodes.json` or `edges.json` when the summary or query output is insufficient.
5. Answer from graph artifacts first. Read source files only for nodes directly relevant to the user's request.
6. Use enriched edge types when they fit the question: `imports`, `tests`, `configures`, `runs`, `declares-route`, and `renders`.
7. Keep responses concise and scoped. Prefer returning changed nodes, important neighbors, and likely impact rather than broad repo narration.

## Use The Graph Efficiently

- Start with `summary.md` for a global picture.
- Use `nodes.json` to inspect metadata for specific files or directories.
- Use `edges.json` to trace containment and import relationships.
- Use `--around <path> --depth 2` for a compact local neighborhood.
- Use `--impacted <path>` to list importers likely affected by a change.
- Use `--dependencies <path>`, `--dependents <path>`, or `--path <from> <to>` to explain relationships.
- Use `--cycles`, `--untested`, `--violations`, `--entrypoints`, or `--routes` for architecture checks.
- Use `--changed`, `--diff <ref>`, `--impact-diff <ref>`, or `--hotspots` for Git-aware analysis.
- Use `--ignored` to explain default, configured, and Git-ignored paths.
- Use `--central` or `--orphans` for small prioritized lists.
- Open `viewer.html` in a browser when visual navigation is useful.
- Prefer a local graph around one path or module before discussing the entire repository.
- For frontend repos, inspect `declares-route` and `renders` edges before reading router/component files.
- For test planning, inspect `tests` edges and nearby test nodes before inventing new test locations.
- For build or tooling questions, inspect `configures` and `runs` edges first.

## Default Outputs

Prefer one of these compact outputs unless the user asks for more:

- A 3-7 line architecture summary
- A local graph around one file or folder
- The top impacted nodes for a planned change
- A short list of orphaned or highly referenced files

## Staleness Rules

- Treat the graph as fresh only when its source fingerprint, parser version, graph format, and configuration still match.
- Rebuild with `--force` after large refactors, dependency renames, or changes to ignore patterns.
- If only a small area changed, rebuild the graph first, then keep the analysis scoped to the changed paths.

## Graph Artifacts

The bundled script writes these files into `.project-graph/`:

- `manifest.json`: scan metadata and freshness details
- `nodes.json`: compact node list
- `edges.json`: compact edge list
- `scan-cache.json`: per-file parser cache for incremental refreshes
- `summary.md`: human-readable repo overview
- `viewer.html`: self-contained local graph viewer

Enriched graphs may include these relationship types:

- `contains`: folder/file containment
- `imports`: resolved source import relationships
- `tests`: test files linked to likely source files by naming convention
- `configures`: config or manifest files connected to the repository root
- `runs`: package scripts linked to local entrypoint files when detectable
- `declares-route`: frontend route declarations linked to route nodes
- `renders`: React-style component usage linked to imported component files

File nodes may include detected `symbols`, `calls`, configured architecture `layer`, size, lines, role, and modification metadata. Import resolution understands Python packages and relative imports, Go modules, TypeScript/JavaScript aliases, workspace packages, and common Rust, Java, and C# forms.

Read [references/config-schema.md](references/config-schema.md) when the repository needs custom include or exclude behavior. Read [references/prompt-patterns.md](references/prompt-patterns.md) when you need low-token prompt templates for repeated graph work.

## Execution Notes

- Run the script from any working directory by passing `--root` and `--output`.
- Query modes refresh fingerprint-stale artifacts first, then print compact Markdown.
- Reuse unchanged per-file parser results during refreshes; use `--force` to rebuild graph outputs while still permitting safe cache reuse.
- Respect `.gitignore` by default inside Git repositories; disable it only through repository configuration when ignored source must be scanned.
- Keep the scan broad enough to capture architecture. Rely on the built-in exclusions for common dependency, vendor, build, generated, cache, virtual-environment, IDE, and version-control directories; add repository-specific patterns in `.project-graph/config.json` when needed.
- Do not paste large JSON outputs into the conversation. Summarize them.
- If a request needs semantic detail the graph cannot provide, identify the exact files to read next instead of scanning the whole repo.
- Run `scripts/benchmark_project_graph.py --root <repo>` when scan or incremental-refresh performance needs measurement.
