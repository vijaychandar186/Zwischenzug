# Sandboxing

## Overview

Sandboxing is the isolation layer that allows Zwischenzug to execute tool operations with reduced risk relative to running directly in the host environment. It sits inside the broader permission system and is evaluated per operation.

The sandbox is not the same thing as approval. Approval decides whether an operation is authorized to run at all. Sandboxing decides whether the operation, once allowed, should run in an isolated environment with restricted capabilities.

---

## Role in the Safety Model

Zwischenzug uses multiple independent safety layers. Sandboxing is one of those layers, not the only one:

- **Permission rules** determine whether the action is allowed, denied, or requires approval
- **Sandboxing** determines whether the action runs with reduced privileges
- Both apply independently

Sandboxing does not replace permission modes, allow/deny rules, or hook-based checks. It complements them.

---

## Position in the Execution Pipeline

1. Validate the tool input
2. Evaluate permission mode constraints
3. Apply allow/deny rules
4. Apply tool-specific safety checks
5. Decide whether sandbox execution is required
6. Execute the operation either directly or through the sandbox wrapper

---

## What the Sandbox Restricts

When sandbox execution is active, the isolated environment restricts:

### Filesystem Isolation

- Commands can only access approved project directories
- Traversal outside trusted paths is blocked

### Network Isolation

- Outbound network access can be restricted
- Prevents unauthorized API calls, downloads, or data exfiltration

### Process Restrictions

- Limits child-process spawning
- Prevents background service startup
- Restricts command chains that try to escape the task boundary

---

## Bash Tool Integration

The bash tool is the primary sandbox integration surface. For bash execution:

1. Parse the command
2. Check permission rules
3. Make a sandbox decision
4. Execute either directly or in the sandboxed environment

### Command Outcomes

A shell command may have four outcomes:

- Allowed and executed directly on host
- Allowed and executed in sandbox
- Denied before execution
- Approved but failing because the sandbox blocks a capability it needs

The last case is expected behavior, not an error.

---

## Key Invariants

1. Sandboxing is per-operation, not session-wide
2. Sandboxing cannot authorize an action that permission layers denied
3. Sandboxing narrows execution capabilities; it never broadens them
4. Shell execution is the primary sandbox integration surface
5. Sandboxed commands may legitimately fail due to restricted capabilities
