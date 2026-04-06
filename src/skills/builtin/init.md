---
name: init
description: Initialize or update ZWISCHENZUG.md with project-specific AI agent instructions
allowedTools: [bash, glob, grep, read_file, write_file]
context: inline
---
Create or update ZWISCHENZUG.md in the current directory.

ZWISCHENZUG.md is the project-level instruction file for this AI coding agent. It is automatically loaded into the system prompt at the start of each session.

Steps:
1. Explore the project structure: read pyproject.toml / package.json / Makefile / README.md.
2. Identify: language, framework, build system, test runner, linting tools.
3. Look at existing ZWISCHENZUG.md if it exists.
4. Write or update ZWISCHENZUG.md with:
   - Project overview (1–2 sentences)
   - Build/run commands (how to install, test, run the app)
   - Code conventions (naming, style, important patterns)
   - Architecture notes (key modules, data flow)
   - Anything important that isn't obvious from reading the code

Keep it concise — aim for under 200 lines. It will be injected into every session's system prompt.

{{{args}}}
