# Project Graph Codex Skill

Reusable Codex skill for generating compact project graph artifacts from a source repository. The goal is simple: spend tokens once to map a repo, then answer architecture and impact questions from small cached artifacts.

## Contents

- `SKILL.md`: Codex skill instructions
- `scripts/build_project_graph.py`: graph generator and query CLI
- `references/config-schema.md`: optional scan configuration
- `references/prompt-patterns.md`: compact prompts for graph-based analysis
- `agents/openai.yaml`: agent metadata
- `tests/`: standard-library regression tests

## Install

Use directly from the skill folder:

```powershell
python scripts/build_project_graph.py --root <repo> --output <repo>/.project-graph
```

Or install the local package in editable mode:

```powershell
python -m pip install -e .
project-graph --root <repo> --output <repo>/.project-graph
```

To use as a Codex skill, copy or symlink this folder into a Codex skills directory so `SKILL.md` is at the skill root.

## Build Artifacts

The generator writes these files into `.project-graph/`:

- `manifest.json`: scan metadata and freshness inputs
- `nodes.json`: compact file and folder nodes
- `edges.json`: containment and import edges
- `summary.md`: low-token repo overview
- `viewer.html`: self-contained local graph viewer

## Query Examples

Use query modes to avoid opening full JSON artifacts:

```powershell
project-graph --root <repo> --output <repo>/.project-graph --around scripts/build_project_graph.py --depth 2
project-graph --root <repo> --output <repo>/.project-graph --impacted app/models.py
project-graph --root <repo> --output <repo>/.project-graph --central --limit 10
project-graph --root <repo> --output <repo>/.project-graph --orphans
project-graph --root <repo> --output <repo>/.project-graph --read-next app/models.py
project-graph --root <repo> --output <repo>/.project-graph --why app/models.py
project-graph --root <repo> --output <repo>/.project-graph --entrypoints
project-graph --root <repo> --output <repo>/.project-graph --missing-tests
project-graph --root <repo> --output <repo>/.project-graph --docs-for app/models.py
project-graph --root <repo> --output <repo>/.project-graph --owners
project-graph --root <repo> --output <repo>/.project-graph --confidence
project-graph --root <repo> --output <repo>/.project-graph --export-bundle handoff --bundle-for app/models.py
```

Query modes refresh stale artifacts first, then print compact Markdown rows.

## Query Modes

- `--around <path>`: show a local neighborhood around one node.
- `--impacted <path>`: show importers likely affected by changing one node.
- `--read-next <path>`: suggest the next files Codex should inspect.
- `--why <path>`: explain why a node appears in graph results.
- `--entrypoints`: detect likely application or CLI entrypoints.
- `--missing-tests`: list source files without an obvious nearby/named test.
- `--docs-for <path>`: find README or docs files likely relevant to a node.
- `--owners`: summarize matching `CODEOWNERS` hints.
- `--confidence`: report graph coverage and confidence signals.
- `--export-bundle <dir-or.zip>`: write a small handoff bundle.

## Roadmap

Future larger upgrades include generated architecture docs, CI comments, semantic summaries, local embedding search, graph-backed Codex memory, boundary linting, and multi-agent task routing.

## Test

```powershell
python -m unittest
```
