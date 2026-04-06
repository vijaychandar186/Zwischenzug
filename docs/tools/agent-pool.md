# Enhanced Subagent Pool

## Overview

The agent pool system (`src/tools/agent_pool.py`) provides concurrent child agent management with full lifecycle control. It extends the basic `SubagentTool` with the ability to spawn multiple agents in parallel, send follow-up messages, wait for results, and interrupt running agents.

---

## Tools

### `spawn_agent`

Launch a child agent to handle a subtask in the background.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `task` | string | Yes | — | Self-contained description of the subtask |
| `max_turns` | integer | No | 15 | Maximum turns (capped at 50) |
| `system_prompt` | string | No | — | Optional system prompt override |

Returns an `agent_id` for use with other pool tools.

### `message_agent`

Send a follow-up message to a running child agent.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `agent_id` | string | Yes | — | ID of the agent to message |
| `message` | string | Yes | — | Follow-up instruction |

### `wait_agent`

Wait for a child agent to complete and retrieve its output. Read-only.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `agent_id` | string | Yes | — | ID of the agent to wait for |
| `timeout` | number | No | 120 | Max seconds to wait |

### `list_agents`

List all spawned agents and their current status. Read-only. No parameters.

### `interrupt_agent`

Cancel a running child agent.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `agent_id` | string | Yes | — | ID of the agent to interrupt |

---

## Agent Lifecycle

Agents progress through these states:

```
RUNNING → COMPLETED   (normal completion)
RUNNING → FAILED      (exception during execution)
RUNNING → INTERRUPTED (cancelled via interrupt_agent)
```

---

## Concurrency

Multiple agents can run in parallel. The pool is session-scoped — each session has its own isolated set of agents. Child agents inherit the parent's provider, model, cwd, and permission mode, but get their own tool registry (without `spawn_agent`/`subagent` to prevent recursion).

---

## Example Usage

```
1. spawn_agent(task="Search for all TODO comments in src/")  → agent-abc12345
2. spawn_agent(task="Run the test suite and report failures") → agent-def67890
3. list_agents()  → shows both running
4. wait_agent(agent_id="agent-abc12345")  → returns search results
5. wait_agent(agent_id="agent-def67890")  → returns test results
```
