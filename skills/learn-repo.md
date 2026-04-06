---
name: learn-repo
description: Trigger a full repository learning pass and report what was discovered
aliases: [lr, learnrepo]
allowedTools: [bash, read_file, glob]
context: inline
---

Run a full repository learning pass: {{{args}}}

Execute:
```
zwis learn --fetch-docs
```

Then:
1. Read `.zwis/knowledge/INDEX.md` to see what was generated
2. Read `.zwis/knowledge/architecture.md` for the overall structure
3. Summarise the key findings:
   - Frameworks and libraries detected
   - Number of modules, classes, functions
   - Key architectural components
   - Any interesting patterns observed
