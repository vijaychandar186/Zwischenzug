---
name: safe-edit
description: Edit code safely — run impact analysis first, then make the change and verify no dependents are broken
aliases: [se, safeedit]
allowedTools: [graph_search, graph_impact, graph_refs, read_file, edit_file, write_file, bash, glob, grep]
context: inline
---

Safely implement the following change: {{{args}}}

Protocol:
1. **Locate** the target symbol with `graph_search`
2. **Analyse impact** with `graph_impact` — if risk is HIGH, summarise what else needs updating
3. **Read** the relevant files with `read_file`
4. **Plan** the changes (show diff intention before editing)
5. **Edit** the files with `edit_file`
6. **Update dependents** — if the signature or behaviour changed, update all call sites found by `graph_refs`
7. **Verify** with `bash` (run tests if available: `python -m pytest -x -q`)
8. Report what was changed and what was intentionally left unchanged
