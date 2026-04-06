# Permission System

## Overview

The permission system controls whether tool operations are automatically executed, presented to the user for approval, or blocked entirely. It operates on every tool invocation.

---

## Permission Modes

The system operates globally in one of four permission modes. The mode is set at session start via `--permission` flag or toggled via `/plan` and `/auto` commands.

### `auto` Mode

Default mode. Read-only tools are auto-approved. Write tools and bash commands are allowed if they match an allow rule, otherwise the user is prompted.

### `interactive` Mode

Every tool invocation requires explicit user approval. Most restrictive interactive mode.

### `deny` Mode

All write operations are blocked. Equivalent to read-only mode. Useful for safe browsing.

### `plan` Mode

Zero write operations permitted. The agent can only read and analyze. Activated via `/plan` or `--plan` flag.

---

## Allow/Deny Rules

Rules are configured in `.zwis/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Bash(npm run *)",
      "Bash(git *)",
      "Bash(python -m pytest*)"
    ],
    "deny": [
      "Bash(rm -rf *)",
      "Bash(sudo *)",
      "Bash(curl * | bash)"
    ]
  }
}
```

### Pattern Syntax

`ToolName(glob)` where the glob is matched against the tool's primary input.

### Precedence

Deny rules always take precedence over allow rules. If both match, the operation is denied.

---

## Evaluation Order

For each tool invocation:

1. Check if the tool is allowed by the current permission mode
2. Check against deny rules (if any match → blocked)
3. Check against allow rules (if any match → auto-approved)
4. If no rules match → prompt user (in interactive/auto mode) or block (in deny/plan mode)
5. Fire `PreToolUse` hooks (can block even if permission allows)

---

## Key Invariants

1. **Deny always wins**: A deny rule overrides any allow rule
2. **Plan mode is absolute**: No write operations in plan mode, regardless of rules
3. **Permission escalation is impossible**: A tool cannot grant itself higher permissions
4. **Layers are independent**: Each check is independent; any can deny
