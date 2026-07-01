---
name: project-graph
description: Build and reuse an Obsidian-style project graph for repository navigation, architecture mapping, impact analysis, and token-efficient code understanding. Use when Codex needs to understand a codebase across many files, answer questions from cached repo structure instead of rereading everything, generate a local or global graph view, detect central or orphaned files, or refresh graph artifacts after source changes.
---

# Project Graph

## Overview

Build compact graph artifacts for a repository, then answer from those artifacts before reading raw source files. Prefer cached graph context for low-token architecture questions, dependency exploration, and change-impact analysis.

## Workflow

1. Check whether the repository already contains `.project-graph/manifest.json` and `.project-graph/summary.md`.
2. If the graph is missing or stale, run `scripts/build_project_graph.py --root <repo> --output <repo>/.project-graph`.
3. For scoped questions, prefer a query command before opening JSON: `--around`, `--impacted`, `--risk`, `--changed-since`, `--read-next`, `--why`, `--entrypoints`, `--missing-tests`, `--docs-for`, `--owners`, `--confidence`, `--central`, or `--orphans`.
4. Read the generated summary and only open `nodes.json` or `edges.json` when the summary or query output is insufficient.
5. Answer from graph artifacts first. Read source files only for nodes directly relevant to the user's request.
6. Keep responses concise and scoped. Prefer returning changed nodes, important neighbors, and likely impact rather than broad repo narration.

## Use The Graph Efficiently

- Start with `summary.md` for a global picture.
- Use `nodes.json` to inspect metadata for specific files or directories.
- Use `edges.json` to trace containment and import relationships.
- Use `--around <path> --depth 2` for a compact local neighborhood.
- Use `--around <path> --format mermaid` when a small diagram is useful in chat.
- Use `--impacted <path>` to list importers likely affected by a change.
- Use `--risk <path>` to estimate change risk from imports, size, entrypoints, and nearby tests.
- Use `--changed-since <ref>` before PR/review work to summarize changed files, impact, and risk.
- Use `--read-next <path>` to choose the next source files to inspect.
- Use `--why <path>` when you need to justify why a node is relevant.
- Use `--entrypoints`, `--missing-tests`, `--docs-for <path>`, `--owners`, or `--confidence` to answer targeted repo-navigation questions.
- Use `--central` or `--orphans` for small prioritized lists.
- Open `viewer.html` in a browser when visual navigation is useful.
- Prefer a local graph around one path or module before discussing the entire repository.

## Default Outputs

Prefer one of these compact outputs unless the user asks for more:

- A 3-7 line architecture summary
- A local graph around one file or folder
- The top impacted nodes for a planned change
- A diff impact/risk report for changed files
- A short list of orphaned or highly referenced files
- The next 3-7 files to read and why
- A confidence note when graph coverage looks weak

## Staleness Rules

- Treat the graph as fresh when `manifest.json` exists and the source inventory hash still matches the scanned files.
- Older manifests without an inventory hash fall back to source modification times.
- Rebuild with `--force` after large refactors, dependency renames, or changes to ignore patterns.
- If only a small area changed, rebuild the graph first, then keep the analysis scoped to the changed paths.

## Graph Artifacts

The bundled script writes these files into `.project-graph/`:

- `manifest.json`: scan metadata and freshness details
- `nodes.json`: compact node list
- `edges.json`: compact edge list
- `summary.md`: human-readable repo overview
- `viewer.html`: self-contained local graph viewer

Read [references/config-schema.md](references/config-schema.md) when the repository needs custom include or exclude behavior. Read [references/prompt-patterns.md](references/prompt-patterns.md) when you need low-token prompt templates for repeated graph work.

## Execution Notes

- Run the script from any working directory by passing `--root` and `--output`.
- Query modes refresh stale artifacts first, then print compact Markdown.
- Config files are validated; fix reported config errors before trusting graph output.
- Import resolution supports Python package-relative imports and basic TypeScript `paths` aliases.
- Keep the scan broad enough to capture architecture, but avoid vendored, generated, or cache directories.
- Do not paste large JSON outputs into the conversation. Summarize them.
- If a request needs semantic detail the graph cannot provide, identify the exact files to read next instead of scanning the whole repo.
