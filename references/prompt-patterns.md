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

## Repo Overview

```text
Use $project-graph.
Build or refresh the graph for this repository.
Give me a compact overview: major folders, central files, orphan candidates, and the best entry points for onboarding.
```
