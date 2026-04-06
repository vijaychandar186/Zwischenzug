"""
Zwischenzug hooks — lifecycle hook runner.

Hooks are shell commands that execute in response to session lifecycle events.
They are configured in .zwis/settings.json (project) or ~/.zwis/settings.json (user).

Settings format:
    {
      "hooks": {
        "PreToolUse": [
          {
            "matcher": "bash",
            "hooks": [{"type": "command", "command": "echo 'running bash'"}]
          }
        ],
        "PostToolUse": [
          {
            "matcher": "*",
            "hooks": [{"type": "command", "command": "logger -t zwis 'tool done'"}]
          }
        ]
      }
    }

Pre-hooks block execution if they exit non-zero.
Post-hooks never block (exit code is ignored).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger("zwischenzug.hooks")

HOOK_TIMEOUT = 10.0  # seconds


class HookEvent(str, Enum):
    PRE_TOOL_USE  = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    PRE_QUERY     = "PreQuery"
    POST_QUERY    = "PostQuery"
    SESSION_START = "SessionStart"
    SESSION_END   = "SessionEnd"
    STOP          = "Stop"

    # Alias constants for convenience
    PRE_TOOL  = "PreToolUse"
    POST_TOOL = "PostToolUse"


@dataclass
class HookDef:
    command: str
    timeout: float = HOOK_TIMEOUT


@dataclass
class HookEntry:
    matcher: str           # tool name, "*", or pattern
    hooks: list[HookDef]


@dataclass
class HookRunner:
    """
    Executes registered lifecycle hooks.

    Pre-hooks (PreToolUse, PreQuery) return False if any hook exits non-zero,
    signalling the caller to block the associated operation.
    Post-hooks always return True.
    """
    _hooks: dict[str, list[HookEntry]] = field(default_factory=dict)

    # ----------------------------------------------------------------
    # Construction
    # ----------------------------------------------------------------

    @classmethod
    def empty(cls) -> "HookRunner":
        return cls()

    @classmethod
    def from_settings(cls, cwd: str | None = None) -> "HookRunner":
        """
        Load hooks from settings.json files.
        Project settings (.zwis/settings.json) are merged on top of user settings
        (~/.zwis/settings.json).
        """
        from ..app_paths import settings_files
        merged: dict[str, list[HookEntry]] = {}

        for path in settings_files(cwd):
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to load settings from %s: %s", path, exc)
                continue

            hooks_section = data.get("hooks", {})
            if not isinstance(hooks_section, dict):
                continue

            for event_name, entries in hooks_section.items():
                if not isinstance(entries, list):
                    continue
                parsed: list[HookEntry] = []
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    matcher = str(entry.get("matcher", "*"))
                    raw_hooks = entry.get("hooks", [])
                    defs: list[HookDef] = []
                    for h in raw_hooks:
                        if not isinstance(h, dict):
                            continue
                        cmd = h.get("command", "")
                        if cmd:
                            defs.append(HookDef(
                                command=str(cmd),
                                timeout=float(h.get("timeout", HOOK_TIMEOUT)),
                            ))
                    if defs:
                        parsed.append(HookEntry(matcher=matcher, hooks=defs))

                # Merge: project overrides user for same event
                if event_name not in merged:
                    merged[event_name] = parsed
                else:
                    # Project-level replaces user-level entirely for this event
                    merged[event_name] = parsed

        return cls(_hooks=merged)

    # ----------------------------------------------------------------
    # Execution
    # ----------------------------------------------------------------

    async def run(
        self,
        event: HookEvent | str,
        matcher: str = "*",
        env_extra: dict[str, str] | None = None,
        session_id: str = "",
        cwd: str | None = None,
    ) -> bool:
        """
        Execute all hooks registered for *event* whose matcher matches *matcher*.

        Returns:
            True  — all hooks passed (or no hooks registered)
            False — a pre-hook exited non-zero (blocks the operation)
        """
        event_name = event.value if isinstance(event, HookEvent) else str(event)
        entries = self._hooks.get(event_name, [])
        is_pre = event_name.startswith("Pre")

        if not entries:
            return True

        env = {**os.environ}
        env["ZWIS_TOOL_NAME"]      = matcher
        env["ZWIS_SESSION_ID"]     = session_id
        env["ZWIS_CWD"]            = cwd or os.getcwd()
        env["ZWIS_HOOK_EVENT"]     = event_name
        if env_extra:
            env.update(env_extra)

        for entry in entries:
            if not _matches(entry.matcher, matcher):
                continue
            for hook in entry.hooks:
                blocked = await _run_command(
                    hook.command,
                    timeout=hook.timeout,
                    env=env,
                    cwd=cwd or os.getcwd(),
                    is_pre=is_pre,
                )
                if blocked:
                    logger.warning(
                        "Pre-hook blocked operation: event=%s matcher=%s cmd=%r",
                        event_name, matcher, hook.command,
                    )
                    return False

        return True

    def has_hooks(self, event: HookEvent | str) -> bool:
        event_name = event.value if isinstance(event, HookEvent) else str(event)
        return bool(self._hooks.get(event_name))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _matches(pattern: str, value: str) -> bool:
    """Match a hook entry matcher against a tool/event name."""
    if pattern in ("*", ""):
        return True
    return pattern.lower() == value.lower()


async def _run_command(
    command: str,
    timeout: float,
    env: dict[str, str],
    cwd: str,
    is_pre: bool,
) -> bool:
    """
    Run a shell command.
    Returns True only if this is a pre-hook AND the command exited non-zero
    (i.e., the operation should be blocked).
    """
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            logger.warning("Hook timed out after %.1fs: %r", timeout, command)
            return False  # timeout is not a block

        if proc.returncode != 0:
            logger.debug(
                "Hook exited %d: %r\nstdout: %s\nstderr: %s",
                proc.returncode,
                command,
                stdout.decode(errors="replace")[:500],
                stderr.decode(errors="replace")[:500],
            )
            return is_pre  # only block for pre-hooks
    except Exception as exc:  # noqa: BLE001
        logger.warning("Hook execution error: %s", exc)

    return False
