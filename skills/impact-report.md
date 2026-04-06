---
name: impact-report
description: Generate a full impact report before a refactoring — identifies all code that must be updated
aliases: [ir, impactreport]
allowedTools: [graph_impact, graph_refs, graph_search, graph_explain, read_file]
context: inline
---

Generate a complete impact report for changing: {{{args}}}

Steps:
1. Use `graph_search` to find all symbols related to the change
2. For each key symbol, run `graph_impact` to get the full dependency blast radius
3. Use `graph_refs` to find all line-level references
4. Read affected files to understand the scope of required changes
5. Produce a structured report:

## Impact Report: {{{args}}}

### Risk Level
[low | medium | high]

### Symbols to Change
- List of functions/classes/methods that must be modified

### Affected Files
- Complete list of files that reference the changed symbols

### Required Updates
- For each affected file: what specifically needs to change

### Safe Order of Changes
- Recommended sequence to avoid breaking the build

### Test Coverage
- Which tests cover the affected code
- Tests that may need updating
