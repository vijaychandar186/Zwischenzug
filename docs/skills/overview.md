# Skills System

## Overview

Zwischenzug skills are Markdown files with YAML frontmatter that extend the agent's capabilities. Each skill becomes a slash command in the REPL — no code changes needed.

---

## Skill Format

A skill is a `.md` file with YAML frontmatter:

```markdown
---
name: deploy
description: Deploy the application to staging
aliases: [d]
allowedTools: [bash, read_file]
context: inline
---
Deploy the application. Run the deploy script and confirm it succeeded.

{{{args}}}
```

### Frontmatter Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique skill name (becomes the slash command) |
| `description` | Yes | One-line description shown in `/help` and `/skills` |
| `aliases` | No | Alternative names for the slash command |
| `allowedTools` | No | Restrict which tools the skill can use |
| `context` | No | How the skill is injected (`inline` or `system`) |

### Body

The body is a prompt template. `{{{args}}}` is replaced with any arguments the user passes after the slash command.

---

## Skill Discovery and Precedence

Skills are discovered from multiple locations. Later sources override earlier ones for the same skill name:

1. `src/skills/builtin/` — Bundled with the package (lowest precedence)
2. `~/.zwis/skills/` — User-level personal skills
3. `.zwis/skills/` — Project-internal skills
4. `skills/` — **Workspace root (highest precedence)**

---

## Built-in Skills

| Command | Description |
|---------|-------------|
| `/commit` | Generate and create a git commit from staged changes |
| `/review` | Code review of recent changes |
| `/init` | Initialize/update ZWISCHENZUG.md project instructions |
| `/security-review` | OWASP Top 10 security review |
| `/dream` | Consolidate and clean up memory files |
| `/advisor` | Switch to read-only advisory mode |

---

## Graph-Aware Skills (workspace `skills/`)

| Command | Description |
|---------|-------------|
| `/graph-review` | Review code using the knowledge graph — deps, impact, risks |
| `/safe-edit` | Impact analysis first, then safe edit with verification |
| `/trace-flow` | Trace and explain a complete execution flow |
| `/impact-report` | Full blast-radius report before a refactoring |
| `/learn-repo` | Trigger a repository learning pass from the REPL |

---

## Auto-Registration

At REPL startup, all discovered skills are registered as slash commands. The SkillRegistry (`src/skills/__init__.py`) handles:

1. Scanning all skill source directories
2. Parsing YAML frontmatter
3. Registering each skill as a slash command
4. Handling name conflicts (higher-precedence source wins)

---

## Creating Custom Skills

Drop a `.md` file in `skills/` at the workspace root:

```markdown
---
name: my-analysis
description: Analyse a module with the knowledge graph
allowedTools: [graph_search, graph_explain, graph_impact, read_file]
---
Use graph_search to find {{{args}}}, then graph_explain to understand it,
then graph_impact to assess change risk.
```

Then use it: `/my-analysis UserModel`
