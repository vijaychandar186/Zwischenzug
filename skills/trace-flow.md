---
name: trace-flow
description: Trace and explain a complete execution flow or request path through the codebase
aliases: [tf, traceflow]
allowedTools: [graph_trace, graph_explain, graph_search, read_file]
context: inline
---

Trace and explain the complete execution flow for: {{{args}}}

Steps:
1. Use `graph_search` to find the entry point
2. Use `graph_trace` to get the call chain
3. For each major step in the chain, use `graph_explain` to understand what it does
4. Read key files with `read_file` for critical implementation details
5. Produce a clear narrative explaining:
   - The flow from start to finish
   - Each major component's role
   - Where data is transformed
   - Where errors could occur
   - Any notable architectural patterns
