"""
Zwischenzug permissions — permission modes, rules, and policy enforcement.

Permission layers (evaluated in order):
  1. Mode check: plan/deny → block writes; bypass → allow all
  2. Deny rules from settings.json (deny wins over allow)
  3. Allow rules from settings.json
  4. Default by mode: INTERACTIVE → ask; AUTO → allow reads, ask writes; DENY → deny writes

Rules format in .zwis/settings.json:
    {
      "permissions": {
        "allow": ["Bash(npm run *)", "Bash(git *)", "Read(*)"],
        "deny":  ["Bash(rm -rf *)", "Bash(sudo *)"]
      }
    }

Pattern syntax: ToolName(glob) where glob is matched against the primary input.
  - Bash(npm run *)  — matches any bash command starting with "npm run "
  - Read(src/**)     — matches any read of files under src/
  - *                — matches any tool + any input
"""
from __future__ import annotations

import fnmatch
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from ..tools import PermissionMode

logger = logging.getLogger("zwischenzug.permissions")

__all__ = ["PermissionMode", "ToolPermissionContext", "PermissionRule", "PermissionManager"]

# ---------------------------------------------------------------------------
# Catalog-level deny-list (used by tool listing, not execution)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolPermissionContext:
    """Catalog-level permission context (deny-list for tool filtering)."""
    denied_tools: frozenset[str]
    denied_prefixes: tuple[str, ...]

    @classmethod
    def from_iterables(
        cls, denied_tools: list[str], denied_prefixes: list[str]
    ) -> "ToolPermissionContext":
        return cls(
            denied_tools=frozenset(name.lower() for name in denied_tools),
            denied_prefixes=tuple(prefix.lower() for prefix in denied_prefixes),
        )

    def blocks(self, tool_name: str) -> bool:
        normalized = tool_name.lower()
        if normalized in self.denied_tools:
            return True
        return any(normalized.startswith(p) for p in self.denied_prefixes)


# ---------------------------------------------------------------------------
# Execution-time permission rules
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PermissionRule:
    """
    A single allow or deny rule.

    tool:    Tool name to match (e.g. "Bash", "Read", "*" for any).
    pattern: Glob matched against the primary input (command, path, URL, etc.).
    allow:   True → allow; False → deny.
    """
    tool: str
    pattern: str
    allow: bool

    @classmethod
    def parse(cls, spec: str, allow: bool) -> "PermissionRule | None":
        """
        Parse a rule spec like "Bash(npm run *)" or "Read(src/**)".
        Returns None if the spec cannot be parsed.
        """
        spec = spec.strip()
        if not spec:
            return None

        # "ToolName(pattern)"
        m = re.match(r'^(\w+)\((.+)\)$', spec)
        if m:
            return cls(tool=m.group(1), pattern=m.group(2), allow=allow)

        # Plain "*" — matches any tool and input
        if spec == "*":
            return cls(tool="*", pattern="*", allow=allow)

        # Plain tool name without pattern — match all inputs for that tool
        return cls(tool=spec, pattern="*", allow=allow)

    def matches(self, tool_name: str, primary_input: str) -> bool:
        tool_ok = (
            self.tool == "*"
            or self.tool.lower() == tool_name.lower()
        )
        if not tool_ok:
            return False
        return fnmatch.fnmatch(primary_input.lower(), self.pattern.lower())


@dataclass
class PermissionManager:
    """
    Evaluates permission decisions for tool invocations.

    Decision order:
      1. If mode == DENY (plan mode) and tool is not read-only → "deny"
      2. If mode == AUTO with "bypassPermissions" flag → "allow"
      3. Deny rules (deny wins over allow if both match)
      4. Allow rules
      5. Default by mode
    """
    mode: PermissionMode = PermissionMode.AUTO
    allow_rules: list[PermissionRule] = field(default_factory=list)
    deny_rules: list[PermissionRule] = field(default_factory=list)
    bypass: bool = False  # True = bypassPermissions

    @classmethod
    def from_settings(
        cls,
        cwd: str | None = None,
        mode: PermissionMode = PermissionMode.INTERACTIVE,
    ) -> "PermissionManager":
        """
        Build a PermissionManager by reading settings.json files.
        Project settings win over user settings.
        """
        from ..app_paths import settings_files

        allow_rules: list[PermissionRule] = []
        deny_rules: list[PermissionRule] = []

        for path in settings_files(cwd):
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to parse %s: %s", path, exc)
                continue

            perms = data.get("permissions", {})
            if not isinstance(perms, dict):
                continue

            for spec in perms.get("allow", []):
                rule = PermissionRule.parse(str(spec), allow=True)
                if rule:
                    allow_rules.append(rule)

            for spec in perms.get("deny", []):
                rule = PermissionRule.parse(str(spec), allow=False)
                if rule:
                    deny_rules.append(rule)

        return cls(mode=mode, allow_rules=allow_rules, deny_rules=deny_rules)

    def check(
        self,
        tool_name: str,
        primary_input: str,
        is_read_only: bool = False,
    ) -> Literal["allow", "deny", "ask"]:
        """
        Return a permission decision for a tool invocation.

        Args:
            tool_name:     Name of the tool being invoked.
            primary_input: The main input parameter (command, path, URL, query…).
            is_read_only:  Whether the tool is marked read-only.

        Returns:
            "allow" — proceed without prompting
            "deny"  — block execution entirely
            "ask"   — prompt the user for approval
        """
        # bypass all checks
        if self.bypass:
            return "allow"

        # plan/deny mode: write ops are unconditionally blocked
        if self.mode == PermissionMode.DENY and not is_read_only:
            return "deny"

        # read-only tools in any mode are always allowed
        if is_read_only:
            return "allow"

        # check deny rules first (deny takes precedence)
        for rule in self.deny_rules:
            if rule.matches(tool_name, primary_input):
                logger.debug("Deny rule matched: %s(%s)", tool_name, primary_input[:80])
                return "deny"

        # check allow rules
        for rule in self.allow_rules:
            if rule.matches(tool_name, primary_input):
                logger.debug("Allow rule matched: %s(%s)", tool_name, primary_input[:80])
                return "allow"

        # default by mode
        if self.mode == PermissionMode.AUTO:
            return "allow"   # auto mode: trust by default
        if self.mode == PermissionMode.INTERACTIVE:
            return "ask"     # interactive: always confirm writes

        return "ask"
