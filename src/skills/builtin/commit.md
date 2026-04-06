---
name: commit
description: Generate and create a git commit for staged changes
aliases: [c]
allowedTools: [bash, glob, grep, read_file]
context: inline
---
Create a git commit for the current changes.

Steps:
1. Run `git diff --cached` to see what is staged. If nothing is staged, run `git status` and stage appropriate files with `git add`.
2. Run `git log --oneline -5` to understand the commit message style used in this repo.
3. Write a concise commit message: imperative mood, present tense, under 72 chars for the subject line. Use conventional commits format if the repo uses it (feat:, fix:, docs:, refactor:, test:, chore:).
4. Create the commit with `git commit -m "message"`. Do NOT use --no-verify or bypass hooks.
5. Confirm the commit was created successfully.

{{{args}}}
