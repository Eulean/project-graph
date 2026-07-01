# Low-Token Prompt Patterns

Use these patterns to make the graph pay off.

## Refresh Then Answer

```text
Use $project-graph.
Check the cached graph first.
Refresh it only if stale.
Then answer using the summary and only the nodes relevant to <topic>.
Return a concise result.
```

## Local Graph Question

```text
Use $project-graph.
Run the local graph query around <path> within 2 hops.
List the direct neighbors, likely impact points, and any orphaned related files.
Do not rescan unrelated folders.
```

## Change Impact

```text
Use $project-graph.
Refresh the graph if needed.
For changes in <paths>, identify the most affected files and folders from graph edges first.
Read raw source only if the graph cannot explain a dependency.
Return a short impact summary.
```

## Query First

```text
Use $project-graph.
Before reading source, run the smallest graph query for <question>.
Use --around, --impacted, --central, or --orphans when one fits.
Only open raw files named by the query output.
Return the result in 3-7 lines.
```

## Diff Review

```text
Use $project-graph.
Run --changed-since <base-ref> before reading source.
Use the changed files, graph impact, and risk lines to choose what to inspect.
Return review focus areas and likely tests in a compact list.
```

## Risk Check

```text
Use $project-graph.
Run --risk for <path>.
If risk is medium or high, run --read-next for the same path.
Open only the files needed to explain the risk.
```

## Mermaid Sketch

```text
Use $project-graph.
Run --around <path> --format mermaid --depth 2.
Return the diagram only if the user benefits from a visual map.
```

## Read Next

```text
Use $project-graph.
Run --read-next for <path>.
Open only the top files that are needed to answer the user.
Explain why each file matters in one short phrase.
```

## Review Entry

```text
Use $project-graph.
Run --entrypoints, --missing-tests, and --confidence before reading source.
Use the result to pick the smallest useful source set.
Return risks and next reads, not broad narration.
```

## Repo Overview

```text
Use $project-graph.
Build or refresh the graph for this repository.
Give me a compact overview: major folders, central files, orphan candidates, and the best entry points for onboarding.
```
