"""
Zwischenzug skills — Markdown-based prompt commands.

Skills are .md files with YAML frontmatter that define slash commands.
They are discovered from directories in this priority order (lowest → highest):
  1. src/skills/builtin/     (bundled with the application)
  2. ~/.zwis/skills/         (user-level, overrides bundled)
  3. .zwis/skills/           (project-level, overrides user)
  4. skills/                 (workspace root, overrides project)

Skill file format:
    ---
    name: my-skill
    description: What this skill does
    aliases: [ms, myskill]
    allowedTools: [read_file, bash]
    model: openai/gpt-4o-mini
    context: inline
    ---

    Prompt template here. Use {{{args}}} for command arguments.

Built-in skills: commit, review, init, security-review, dream
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger("zwischenzug.skills")


@dataclass
class Skill:
    name: str
    description: str
    aliases: list[str] = field(default_factory=list)
    allowed_tools: list[str] | None = None   # None = all tools allowed
    model: str | None = None                 # None = inherit session model
    context: Literal["inline", "fork"] = "inline"
    prompt_template: str = ""
    source_path: Path = field(default_factory=lambda: Path("."))

    def matches(self, query: str) -> bool:
        """Return True if query matches this skill's name or any alias."""
        q = query.lower().lstrip("/")
        if q == self.name.lower():
            return True
        return q in (a.lower() for a in self.aliases)

    def expand(self, args: str = "") -> str:
        """Substitute {{{args}}} in the template and strip the result."""
        return self.prompt_template.replace("{{{args}}}", args).strip()


class SkillRegistry:
    """Discovers and provides access to all available skills."""

    def __init__(self, skills: list[Skill]) -> None:
        # Build a name → skill map (last writer wins — project overrides bundled)
        self._map: dict[str, Skill] = {}
        for skill in skills:
            self._map[skill.name.lower()] = skill
            for alias in skill.aliases:
                self._map[alias.lower()] = skill

    # ----------------------------------------------------------------
    # Construction
    # ----------------------------------------------------------------

    @classmethod
    def discover(cls, cwd: str | None = None) -> "SkillRegistry":
        """
        Discover skills from all configured directories.
        Later directories override earlier ones
        (workspace > project > user > bundled).
        """
        from ..app_paths import skills_dirs
        # Track by canonical name only; SkillRegistry.__init__ handles aliases.
        by_name: dict[str, Skill] = {}

        for directory in skills_dirs(cwd):
            if not directory.is_dir():
                continue
            for md_file in sorted(directory.glob("*.md")):
                try:
                    skill = _parse_skill_file(md_file)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to parse skill %s: %s", md_file, exc)
                    continue
                # Later dirs override: project > user > bundled
                by_name[skill.name.lower()] = skill

        return cls(list(by_name.values()))

    # ----------------------------------------------------------------
    # Lookup
    # ----------------------------------------------------------------

    def get(self, name: str) -> Skill | None:
        """Look up a skill by name or alias (case-insensitive, strips leading /)."""
        key = name.lower().lstrip("/")
        return self._map.get(key)

    def all(self) -> list[Skill]:
        """Return all unique skills (no duplicates for aliased skills)."""
        seen: set[int] = set()
        result: list[Skill] = []
        for skill in self._map.values():
            if id(skill) not in seen:
                seen.add(id(skill))
                result.append(skill)
        return sorted(result, key=lambda s: s.name)

    def names(self) -> list[str]:
        """Return all registered names and aliases."""
        return list(self._map.keys())

    def expand(self, skill: Skill, args: str = "") -> str:
        return skill.expand(args)

    def __len__(self) -> int:
        return len(self.all())


# ---------------------------------------------------------------------------
# Skill file parser
# ---------------------------------------------------------------------------

def _parse_skill_file(path: Path) -> Skill:
    """
    Parse a skill Markdown file with YAML frontmatter.

    Raises ValueError if the file cannot be parsed.
    """
    text = path.read_text(encoding="utf-8")

    frontmatter: dict[str, Any] = {}
    body = text

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                import yaml
                frontmatter = yaml.safe_load(parts[1]) or {}
            except ImportError:
                # PyYAML not installed — parse manually (basic key: value only)
                frontmatter = _parse_simple_frontmatter(parts[1])
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"YAML parse error in {path}: {exc}") from exc
            body = parts[2].strip()

    name = str(frontmatter.get("name", path.stem)).strip()
    if not name:
        raise ValueError(f"Skill file {path} has no 'name' field.")

    description = str(frontmatter.get("description", "")).strip()
    aliases_raw = frontmatter.get("aliases", [])
    aliases = [str(a) for a in aliases_raw] if isinstance(aliases_raw, list) else []

    tools_raw = frontmatter.get("allowedTools", None)
    allowed_tools: list[str] | None = None
    if tools_raw is not None:
        allowed_tools = [str(t) for t in tools_raw] if isinstance(tools_raw, list) else [str(tools_raw)]

    model = str(frontmatter.get("model", "")).strip() or None
    context_raw = str(frontmatter.get("context", "inline")).strip().lower()
    context: Literal["inline", "fork"] = "fork" if context_raw == "fork" else "inline"

    return Skill(
        name=name,
        description=description,
        aliases=aliases,
        allowed_tools=allowed_tools,
        model=model,
        context=context,
        prompt_template=body,
        source_path=path,
    )


def _parse_simple_frontmatter(text: str) -> dict[str, Any]:
    """
    Minimal YAML-like parser for when PyYAML is not available.
    Handles: key: value, key: [item1, item2]
    """
    result: dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if ":" not in line or line.startswith("#"):
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        key = key.strip()
        if not key:
            continue
        # Detect list: [a, b, c]
        if value.startswith("[") and value.endswith("]"):
            items = [i.strip().strip("'\"") for i in value[1:-1].split(",") if i.strip()]
            result[key] = items
        else:
            result[key] = value.strip("'\"")
    return result
