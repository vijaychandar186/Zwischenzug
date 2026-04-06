---
name: review
description: Perform a code review of recent changes or a specific file/PR
aliases: [r]
allowedTools: [bash, glob, grep, read_file]
context: inline
---
Perform a thorough code review.

If no specific target is given, review the uncommitted changes (`git diff HEAD`).

Review checklist:
- **Correctness**: Logic errors, off-by-one errors, incorrect assumptions
- **Security**: Command injection, path traversal, hardcoded secrets, unvalidated input
- **Performance**: N+1 queries, unnecessary loops, missing indexes, large allocations
- **Readability**: Confusing naming, missing context, overly complex logic
- **Error handling**: Unhandled exceptions, silent failures, missing validation
- **Tests**: Are the changes covered? Are edge cases tested?
- **Style**: Does the code follow existing conventions?

For each issue found, cite the file and line number and explain why it's a problem and how to fix it.

{{{args}}}
