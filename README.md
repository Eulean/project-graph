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
- `edges.json`: containment, import, test, config, package-script, route, and render edges
- `summary.md`: low-token repo overview
- `viewer.html`: self-contained local graph viewer

## Query Examples

Use query modes to avoid opening full JSON artifacts:

```powershell
project-graph --root <repo> --output <repo>/.project-graph --around scripts/build_project_graph.py --depth 2
project-graph --root <repo> --output <repo>/.project-graph --impacted app/models.py
project-graph --root <repo> --output <repo>/.project-graph --central --limit 10
project-graph --root <repo> --output <repo>/.project-graph --orphans
project-graph --root <repo> --output <repo>/.project-graph --cycles
project-graph --root <repo> --output <repo>/.project-graph --path src/a.ts src/b.ts
project-graph --root <repo> --output <repo>/.project-graph --impact-diff main
project-graph --root <repo> --output <repo>/.project-graph --hotspots
project-graph --root <repo> --output <repo>/.project-graph --violations
```

Query modes refresh stale artifacts first, then print compact Markdown rows.

## Enriched Relationships

Beyond `contains` and `imports`, the graph can detect:

- `tests`: likely test-to-source links by naming convention
- `configures`: known config and manifest files connected to the repo root
- `runs`: package scripts linked to local entrypoint files
- `declares-route`: React Router-style route declarations
- `renders`: React-style component usage through imported components

Version 0.2 adds source fingerprints, Git-ignore-aware discovery, Python AST metadata, TypeScript aliases, workspace packages, broader language resolution, dependency paths, cycles, untested-source checks, architecture layers, Git diff impact, hotspots, ignored-path diagnostics, and relationship filters in the viewer.

## မြန်မာအသုံးပြုနည်း

Project Graph က repository တစ်ခုအတွင်းရှိ files, imports, tests, routes, scripts နဲ့ Git changes တွေကို graph အဖြစ်တည်ဆောက်ပေးပါတယ်။ Codex မှာ အလွယ်ဆုံးအသုံးပြုရန်—

```text
$project-graph ကိုသုံးပြီး ဒီ repository ရဲ့ architecture ကိုရှင်းပြပါ။
```

```text
$project-graph ကိုသုံးပြီး ဒီ file ကိုပြောင်းရင် ဘယ် files တွေထိခိုက်နိုင်လဲ စစ်ပါ။
```

### Graph တည်ဆောက်ခြင်း

```powershell
python scripts/build_project_graph.py --root <repo> --output <repo>/.project-graph
```

တည်ဆောက်ပြီးလျှင် `.project-graph/` အောက်မှာ အောက်ပါ artifacts တွေရရှိပါမယ်—

- `summary.md` — project architecture အကျဉ်းချုပ်
- `nodes.json` — files, folders, symbols နဲ့ metadata
- `edges.json` — imports, tests, routes နဲ့ အခြားဆက်နွယ်မှုများ
- `scan-cache.json` — နောက်တစ်ကြိမ် refresh ကိုမြန်စေသော cache
- `manifest.json` — graph version နဲ့ freshness information
- `viewer.html` — browser ဖြင့်ဖွင့်ကြည့်နိုင်သော visual graph

### အသုံးများသော Commands

| လုပ်ဆောင်ချက် | Option |
| --- | --- |
| File တစ်ခုအနီးက ဆက်နွယ်မှုများ | `--around <path> --depth 2` |
| File ပြောင်းလဲမှုကြောင့် ထိခိုက်နိုင်သည့်နေရာများ | `--impacted <path>` |
| File အသုံးပြုထားသော dependencies | `--dependencies <path>` |
| File ကိုအသုံးပြုနေသော dependents | `--dependents <path>` |
| Files နှစ်ခုကြား ဆက်နွယ်ပုံ | `--path <from> <to>` |
| Circular dependencies | `--cycles` |
| Test မချိတ်ထားသော source files | `--untested` |
| အရေးကြီးဆုံး central files | `--central` |
| ဆက်နွယ်မှုမရှိသော orphan files | `--orphans` |
| Application entrypoints | `--entrypoints` |
| Frontend routes | `--routes` |
| Architecture layer violations | `--violations` |
| Ignore လုပ်ထားသော paths | `--ignored` |
| Git working-tree changes | `--changed` |
| Git reference တစ်ခုနောက်ပိုင်း changes | `--diff <ref>` |
| Git changes ရဲ့ dependency impact | `--impact-diff <ref>` |
| မကြာခဏပြောင်းပြီး dependency များသော files | `--hotspots` |

ဥပမာ—

```powershell
python scripts/build_project_graph.py --root . --output .project-graph --cycles
python scripts/build_project_graph.py --root . --output .project-graph --impacted src/auth.ts
python scripts/build_project_graph.py --root . --output .project-graph --impact-diff main
```

### Ignore စနစ်

`node_modules`, `vendor`, `dist`, `build`, `.next`, `.venv`, cache, generated နဲ့ version-control folders တွေကို default အနေဖြင့် scan မလုပ်ပါ။ Git repository ဖြစ်လျှင် `.gitignore` ကိုလည်း အလိုအလျောက်လိုက်နာပါတယ်။ Repository-specific rules နဲ့ architecture layers တွေကို `.project-graph/config.json` မှာ သတ်မှတ်နိုင်ပြီး အသေးစိတ်ကို [`references/config-schema.md`](references/config-schema.md) မှာကြည့်နိုင်ပါတယ်။

### Visual Viewer

Graph တည်ဆောက်ပြီးနောက် `.project-graph/viewer.html` ကို browser ဖြင့်ဖွင့်ပါ။ Node search, node/relationship filters, symbols, calls, direct relationships နဲ့ dark mode တို့ကိုအသုံးပြုနိုင်ပါတယ်။

## Test

```powershell
python -m unittest
```

Benchmark cold and cached rebuilds with:

```powershell
python scripts/benchmark_project_graph.py --root <repo>
```
