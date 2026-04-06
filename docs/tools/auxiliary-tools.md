# Auxiliary Tools

## Overview

Auxiliary tools (`src/tools/auxiliary.py`) provide session management and user interaction capabilities.

---

## TodoWrite

Tracks multi-step tasks within a session.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `todos` | list | Yes | List of todo items with content and status |

Each todo item has:
- `content`: Description of the task
- `status`: `pending`, `in_progress`, or `completed`

**Read-only**: No

The LLM uses this tool to break down complex tasks and track progress. Todo state is displayed to the user and persists within the session.

---

## AskUserQuestion

Pauses execution and asks the user a clarifying question.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `question` | string | Yes | The question to ask the user |

**Read-only**: No

When the LLM needs information it cannot determine from the codebase or conversation, it uses this tool to ask the user directly. The agent loop pauses until the user responds, then continues with the answer.
