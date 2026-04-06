"""
Structured planning tool — create, update, and manage implementation plans.

Goes beyond TodoWriteTool by supporting phases, steps with dependencies,
and plan-mode enforcement (read-only when planning).
"""
from __future__ import annotations

import json
import time
from enum import Enum
from typing import Any

from . import Tool, ToolContext, ToolOutput

# ---------------------------------------------------------------------------
# Plan data model
# ---------------------------------------------------------------------------

class PlanStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


# Session-scoped plan storage
_PLAN_STORE: dict[str, dict] = {}


def get_session_plan(session_id: str) -> dict | None:
    """Return the current plan for a session (used by REPL display)."""
    return _PLAN_STORE.get(session_id)


# ---------------------------------------------------------------------------
# PlanTool
# ---------------------------------------------------------------------------

class PlanTool(Tool):
    """Create and manage structured implementation plans."""

    @property
    def name(self) -> str:
        return "plan"

    @property
    def description(self) -> str:
        return (
            "Create or update a structured implementation plan. "
            "Plans have phases, each with ordered steps. Steps can have dependencies "
            "on other steps. Use actions: 'create' (new plan), 'update' (modify steps), "
            "'status' (view current plan), 'complete' (mark plan done), "
            "'abandon' (cancel plan). "
            "When creating, pass a JSON plan structure. When updating, pass the step_id "
            "and new status."
        )

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": (
                        "Action to perform: 'create', 'update', 'status', "
                        "'complete', 'abandon'."
                    ),
                },
                "plan": {
                    "type": "string",
                    "description": (
                        "JSON plan structure for 'create' action. Format: "
                        '{"title": "...", "phases": [{"name": "...", "steps": '
                        '[{"id": "s1", "content": "...", "depends_on": []}]}]}'
                    ),
                },
                "step_id": {
                    "type": "string",
                    "description": "Step ID for 'update' action.",
                },
                "step_status": {
                    "type": "string",
                    "description": (
                        "New status for 'update' action: "
                        "'pending', 'in_progress', 'completed', 'blocked', 'skipped'."
                    ),
                },
                "note": {
                    "type": "string",
                    "description": "Optional note to attach to the step update.",
                },
            },
            "required": ["action"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        action = kwargs.get("action", "").strip().lower()

        if action == "create":
            return self._create(ctx, kwargs)
        elif action == "update":
            return self._update(ctx, kwargs)
        elif action == "status":
            return self._status(ctx)
        elif action == "complete":
            return self._set_plan_status(ctx, PlanStatus.COMPLETED)
        elif action == "abandon":
            return self._set_plan_status(ctx, PlanStatus.ABANDONED)
        else:
            return ToolOutput.error(
                f"Unknown action: {action!r}. "
                "Use: create, update, status, complete, abandon."
            )

    def _create(self, ctx: ToolContext, kwargs: dict) -> ToolOutput:
        raw = kwargs.get("plan", "")
        if not raw:
            return ToolOutput.error("'create' requires a 'plan' JSON string.")

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return ToolOutput.error(f"Invalid plan JSON: {exc}")

        if not isinstance(data, dict) or "title" not in data:
            return ToolOutput.error("Plan must have a 'title' field.")

        phases = data.get("phases", [])
        if not isinstance(phases, list) or not phases:
            return ToolOutput.error("Plan must have at least one phase.")

        # Validate structure
        all_step_ids: set[str] = set()
        for pi, phase in enumerate(phases):
            if not isinstance(phase, dict) or "name" not in phase:
                return ToolOutput.error(f"Phase {pi} must have a 'name' field.")
            steps = phase.get("steps", [])
            if not isinstance(steps, list):
                return ToolOutput.error(f"Phase {pi} 'steps' must be an array.")
            for si, step in enumerate(steps):
                if not isinstance(step, dict):
                    return ToolOutput.error(f"Phase {pi}, step {si} must be an object.")
                if "id" not in step or "content" not in step:
                    return ToolOutput.error(
                        f"Phase {pi}, step {si} must have 'id' and 'content'."
                    )
                if step["id"] in all_step_ids:
                    return ToolOutput.error(f"Duplicate step ID: {step['id']}")
                all_step_ids.add(step["id"])
                # Ensure defaults
                step.setdefault("status", "pending")
                step.setdefault("depends_on", [])
                step.setdefault("notes", [])

        # Validate dependencies reference existing steps
        for phase in phases:
            for step in phase.get("steps", []):
                for dep in step.get("depends_on", []):
                    if dep not in all_step_ids:
                        return ToolOutput.error(
                            f"Step {step['id']} depends on unknown step: {dep}"
                        )

        plan = {
            "title": data["title"],
            "status": PlanStatus.ACTIVE.value,
            "phases": phases,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        _PLAN_STORE[ctx.session_id] = plan
        return ToolOutput.success(_render_plan(plan))

    def _update(self, ctx: ToolContext, kwargs: dict) -> ToolOutput:
        plan = _PLAN_STORE.get(ctx.session_id)
        if plan is None:
            return ToolOutput.error("No active plan. Use action='create' first.")

        step_id = kwargs.get("step_id", "").strip()
        new_status = kwargs.get("step_status", "").strip()
        note = kwargs.get("note", "").strip()

        if not step_id:
            return ToolOutput.error("'update' requires a 'step_id'.")

        valid_statuses = {s.value for s in StepStatus}
        if new_status and new_status not in valid_statuses:
            return ToolOutput.error(
                f"Invalid step_status: {new_status!r}. "
                f"Valid: {', '.join(sorted(valid_statuses))}"
            )

        # Find and update the step
        for phase in plan["phases"]:
            for step in phase.get("steps", []):
                if step["id"] == step_id:
                    # Check dependency constraints
                    if new_status == "in_progress":
                        for dep_id in step.get("depends_on", []):
                            dep_step = _find_step(plan, dep_id)
                            if dep_step and dep_step.get("status") != "completed":
                                return ToolOutput.error(
                                    f"Cannot start {step_id}: dependency "
                                    f"{dep_id} is {dep_step.get('status', 'unknown')}."
                                )
                    if new_status:
                        step["status"] = new_status
                    if note:
                        step.setdefault("notes", []).append(note)
                    plan["updated_at"] = time.time()
                    return ToolOutput.success(_render_plan(plan))

        return ToolOutput.error(f"Step not found: {step_id}")

    def _status(self, ctx: ToolContext) -> ToolOutput:
        plan = _PLAN_STORE.get(ctx.session_id)
        if plan is None:
            return ToolOutput.success("No active plan.")
        return ToolOutput.success(_render_plan(plan))

    def _set_plan_status(self, ctx: ToolContext, status: PlanStatus) -> ToolOutput:
        plan = _PLAN_STORE.get(ctx.session_id)
        if plan is None:
            return ToolOutput.error("No active plan.")
        plan["status"] = status.value
        plan["updated_at"] = time.time()
        return ToolOutput.success(f"Plan marked as {status.value}.\n\n{_render_plan(plan)}")


# ---------------------------------------------------------------------------
# PlanModeTool
# ---------------------------------------------------------------------------

class PlanModeTool(Tool):
    """Programmatically enter or exit plan mode."""

    @property
    def name(self) -> str:
        return "plan_mode"

    @property
    def description(self) -> str:
        return (
            "Toggle plan mode. In plan mode, all write tools are blocked — "
            "you can only read files and search. Use this when you want to "
            "analyze and plan before making changes. "
            "Pass mode='on' to enter, mode='off' to exit."
        )

    @property
    def is_read_only(self) -> bool:
        return True  # The tool itself is read-only; it changes orchestrator behavior

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "description": "'on' to enter plan mode, 'off' to exit.",
                },
            },
            "required": ["mode"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        mode = kwargs.get("mode", "").strip().lower()
        if mode not in ("on", "off"):
            return ToolOutput.error("mode must be 'on' or 'off'.")

        # Plan mode is signaled by updating the shared plan store with a flag
        plan = _PLAN_STORE.get(ctx.session_id, {})
        plan["plan_mode_active"] = mode == "on"
        _PLAN_STORE[ctx.session_id] = plan

        if mode == "on":
            return ToolOutput.success(
                "Plan mode ON. Write tools are now blocked. "
                "Use read_file, glob, grep to analyze the codebase. "
                "Call plan_mode(mode='off') when ready to make changes."
            )
        else:
            return ToolOutput.success(
                "Plan mode OFF. Write tools are now available."
            )


def is_plan_mode_active(session_id: str) -> bool:
    """Check if plan mode is active for a session."""
    plan = _PLAN_STORE.get(session_id, {})
    return bool(plan.get("plan_mode_active", False))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_step(plan: dict, step_id: str) -> dict | None:
    for phase in plan.get("phases", []):
        for step in phase.get("steps", []):
            if step["id"] == step_id:
                return step
    return None


def _render_plan(plan: dict) -> str:
    status_icon = {
        "pending": "○",
        "in_progress": "◑",
        "completed": "●",
        "blocked": "⊘",
        "skipped": "—",
    }

    lines = [
        f"Plan: {plan.get('title', 'Untitled')}",
        f"Status: {plan.get('status', 'unknown')}",
        "",
    ]

    total_steps = 0
    completed_steps = 0

    for phase in plan.get("phases", []):
        lines.append(f"## {phase['name']}")
        for step in phase.get("steps", []):
            total_steps += 1
            if step.get("status") == "completed":
                completed_steps += 1

            icon = status_icon.get(step.get("status", "pending"), "?")
            deps = ""
            if step.get("depends_on"):
                deps = f" (after: {', '.join(step['depends_on'])})"
            lines.append(f"  {icon} [{step['id']}] {step['content']}{deps}")

            for note in step.get("notes", []):
                lines.append(f"      ↳ {note}")
        lines.append("")

    if total_steps > 0:
        pct = int(100 * completed_steps / total_steps)
        lines.append(f"Progress: {completed_steps}/{total_steps} ({pct}%)")

    return "\n".join(lines)
