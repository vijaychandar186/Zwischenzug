---
name: graph-review
description: Review a file using the knowledge graph — analyse dependencies, impact, and risks before editing
aliases: [gr, greview]
allowedTools: [graph_search, graph_explain, graph_impact, graph_refs, read_file, glob]
context: inline
---

Perform a thorough graph-driven review of the following code: {{{args}}}

Steps:
1. Use `graph_search` to locate the file/symbol in the knowledge graph
2. Use `graph_explain` to understand the module's structure and purpose
3. Use `graph_impact` to identify what would break if this module changes
4. Use `graph_refs` to find all call sites for the key symbols
5. Use `read_file` to review the actual source
6. Report:
   - What the code does
   - Its dependencies (what it calls)
   - Its dependents (what calls it)
   - Risk level for modifications
   - Any architecture concerns or suggestions
