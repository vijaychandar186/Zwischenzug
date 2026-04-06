"""Auxiliary tools — TodoWrite and AskUserQuestion."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from . import Tool, ToolContext, ToolOutput

# ---------------------------------------------------------------------------
# Session-scoped todo storage (in-memory, keyed by session_id)
# ---------------------------------------------------------------------------
_TODO_STORE: dict[str, list[dict]] = {}

_VALID_STATUSES = {"pending", "in_progress", "completed"}
_VALID_PRIORITIES = {"high", "medium", "low"}


class TodoWriteTool(Tool):
    """Manage a structured todo list for the current session."""

    @property
    def name(self) -> str:
        return "todo_write"

    @property
    def description(self) -> str:
        return (
            "Create or update the session's todo list. Pass a JSON array of todo items. "
            "Each item: {id, content, status ('pending'|'in_progress'|'completed'), "
            "priority ('high'|'medium'|'low')}. Writing replaces the entire list. "
            "Use to track multi-step tasks and communicate progress to the user."
        )

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "string",
                    "description": (
                        "JSON array of todo items. Each item must have: "
                        "id (string), content (string), "
                        "status ('pending'|'in_progress'|'completed'), "
                        "priority ('high'|'medium'|'low')."
                    ),
                },
            },
            "required": ["todos"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        raw: str = kwargs["todos"]

        try:
            items = json.loads(raw)
        except json.JSONDecodeError as exc:
            return ToolOutput.error(f"Invalid JSON for todos: {exc}")

        if not isinstance(items, list):
            return ToolOutput.error("todos must be a JSON array.")

        validated: list[dict] = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                return ToolOutput.error(f"Item {i} is not an object.")
            for required in ("id", "content", "status"):
                if required not in item:
                    return ToolOutput.error(f"Item {i} missing required field: {required!r}")
            status = item.get("status", "pending")
            if status not in _VALID_STATUSES:
                return ToolOutput.error(
                    f"Item {i} has invalid status {status!r}. "
                    f"Must be one of: {', '.join(sorted(_VALID_STATUSES))}"
                )
            priority = item.get("priority", "medium")
            if priority not in _VALID_PRIORITIES:
                return ToolOutput.error(
                    f"Item {i} has invalid priority {priority!r}. "
                    f"Must be one of: {', '.join(sorted(_VALID_PRIORITIES))}"
                )
            validated.append({
                "id": str(item["id"]),
                "content": str(item["content"]),
                "status": status,
                "priority": priority,
            })

        _TODO_STORE[ctx.session_id] = validated
        return ToolOutput.success(_render_todos(validated))


def get_session_todos(session_id: str) -> list[dict]:
    """Return the current todo list for a session (used by REPL display)."""
    return _TODO_STORE.get(session_id, [])


def _render_todos(todos: list[dict]) -> str:
    if not todos:
        return "Todo list is empty."

    status_icon = {
        "pending":     "○",
        "in_progress": "◑",
        "completed":   "●",
    }
    priority_icon = {
        "high":   "!",
        "medium": " ",
        "low":    "↓",
    }

    lines = [f"Todo list ({len(todos)} items):"]
    for t in todos:
        si = status_icon.get(t["status"], "?")
        pi = priority_icon.get(t.get("priority", "medium"), " ")
        lines.append(f"  {si} [{pi}] {t['content']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# AskUserQuestion
# ---------------------------------------------------------------------------

class AskUserQuestionTool(Tool):
    """Pause and ask the user a question, waiting for their typed response."""

    @property
    def name(self) -> str:
        return "ask_user"

    @property
    def description(self) -> str:
        return (
            "Pause execution to ask the user a clarifying question. "
            "Use when multiple valid approaches exist, when destructive actions need "
            "confirmation, or when missing information would significantly change the approach. "
            "Returns the user's typed answer."
        )

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to display to the user.",
                },
            },
            "required": ["question"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        question: str = kwargs["question"].strip()

        try:
            answer = await asyncio.to_thread(_prompt_user, question)
        except (EOFError, KeyboardInterrupt):
            return ToolOutput.error("User cancelled the question.")
        except Exception as exc:  # noqa: BLE001
            return ToolOutput.error(f"Failed to read user input: {exc}")

        return ToolOutput.success(answer.strip() or "(no answer provided)")


def _prompt_user(question: str) -> str:
    """Synchronous stdin prompt — runs in a thread."""
    print(f"\n[Question] {question}")
    return input("Your answer: ")
