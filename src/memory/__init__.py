"""
Zwischenzug memory system — persistent context across sessions.

Memory files are stored in ~/.zwis/memory/ as Markdown documents with YAML frontmatter.
An index file MEMORY.md is maintained listing all entries.

Memory file format:
    ---
    name: Memory title
    description: One-line description
    type: user | feedback | project | reference
    ---

    Memory content in markdown...

MEMORY.md index format (one line per entry):
    - [Title](file.md) — one-line hook

Usage:
    mgr = MemoryManager.default()
    index = mgr.load_index()    # inject into system prompt
    mgr.save(entry)             # write a new memory
    mgr.list_memories()         # enumerate all memories
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger("zwischenzug.memory")

MAX_INDEX_LINES = 200


class MemoryType(str, Enum):
    USER      = "user"
    FEEDBACK  = "feedback"
    PROJECT   = "project"
    REFERENCE = "reference"


@dataclass
class MemoryEntry:
    name: str
    description: str
    type: MemoryType
    content: str
    file_path: Path

    @property
    def filename(self) -> str:
        """Derived safe filename (no spaces, lowercase)."""
        return re.sub(r"[^\w-]", "_", self.name.lower()).strip("_") + ".md"


class MemoryManager:
    """
    Read, write, and manage memory files in the memory directory.
    """

    def __init__(self, memory_dir: Path) -> None:
        self.memory_dir = memory_dir

    @classmethod
    def default(cls) -> "MemoryManager":
        from ..app_paths import memory_dir
        return cls(memory_dir())

    # ----------------------------------------------------------------
    # Index
    # ----------------------------------------------------------------

    def load_index(self) -> str:
        """
        Return the MEMORY.md index content (up to MAX_INDEX_LINES lines).
        Returns empty string if no memories exist.
        """
        idx = self.memory_dir / "MEMORY.md"
        if not idx.exists():
            return ""
        text = idx.read_text(encoding="utf-8")
        lines = text.splitlines()
        if len(lines) > MAX_INDEX_LINES:
            lines = lines[:MAX_INDEX_LINES]
        return "\n".join(lines)

    def _rebuild_index(self, entries: list[MemoryEntry]) -> None:
        """Rewrite MEMORY.md from a list of entries."""
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        lines = ["# Memory Index", ""]
        for e in sorted(entries, key=lambda x: (x.type.value, x.name)):
            rel = e.file_path.name
            lines.append(f"- [{e.name}]({rel}) — {e.description}")
        idx = self.memory_dir / "MEMORY.md"
        idx.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ----------------------------------------------------------------
    # CRUD
    # ----------------------------------------------------------------

    def list_memories(self) -> list[MemoryEntry]:
        """Parse all .md files with frontmatter (excluding MEMORY.md index)."""
        if not self.memory_dir.is_dir():
            return []
        entries: list[MemoryEntry] = []
        for md_file in sorted(self.memory_dir.glob("*.md")):
            if md_file.name == "MEMORY.md":
                continue
            try:
                entry = _parse_memory_file(md_file)
                entries.append(entry)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Skipping unreadable memory file %s: %s", md_file, exc)
        return entries

    def get(self, name: str) -> MemoryEntry | None:
        """Find a memory by name (case-insensitive)."""
        needle = name.lower()
        for entry in self.list_memories():
            if entry.name.lower() == needle:
                return entry
        return None

    def save(self, entry: MemoryEntry) -> None:
        """Write a memory file and rebuild the MEMORY.md index."""
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        target = entry.file_path
        if not target.is_absolute() or target.parent != self.memory_dir:
            target = self.memory_dir / entry.filename
        entry = MemoryEntry(
            name=entry.name,
            description=entry.description,
            type=entry.type,
            content=entry.content,
            file_path=target,
        )

        body = _render_memory_file(entry)
        target.write_text(body, encoding="utf-8")
        logger.debug("Saved memory: %s → %s", entry.name, target)

        # Rebuild index
        entries = self.list_memories()
        self._rebuild_index(entries)

    def delete(self, name: str) -> bool:
        """Remove a memory file by name and rebuild the index. Returns True if found."""
        entry = self.get(name)
        if entry is None:
            return False
        try:
            entry.file_path.unlink()
        except FileNotFoundError:
            pass
        entries = [e for e in self.list_memories() if e.name.lower() != name.lower()]
        self._rebuild_index(entries)
        return True

    # ----------------------------------------------------------------
    # Display
    # ----------------------------------------------------------------

    def render_list(self) -> str:
        """Return a Rich-compatible table string of all memories."""
        entries = self.list_memories()
        if not entries:
            return "No memories saved yet.\nUse the memory system to persist important context across sessions."

        type_icon = {
            MemoryType.USER:      "👤",
            MemoryType.FEEDBACK:  "💬",
            MemoryType.PROJECT:   "📋",
            MemoryType.REFERENCE: "🔗",
        }

        lines = [f"Memory entries: {len(entries)}", ""]
        by_type: dict[MemoryType, list[MemoryEntry]] = {}
        for e in entries:
            by_type.setdefault(e.type, []).append(e)

        for mtype in MemoryType:
            group = by_type.get(mtype, [])
            if not group:
                continue
            icon = type_icon.get(mtype, "•")
            lines.append(f"{icon} **{mtype.value.title()}**")
            for e in group:
                lines.append(f"  • {e.name} — {e.description}")
            lines.append("")

        return "\n".join(lines).rstrip()

    def render_entry(self, name: str) -> str:
        """Return formatted content for a single memory entry."""
        entry = self.get(name)
        if entry is None:
            return f"Memory not found: {name!r}"
        return (
            f"**{entry.name}** ({entry.type.value})\n"
            f"{entry.description}\n\n"
            f"{entry.content}"
        )


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def _parse_memory_file(path: Path) -> MemoryEntry:
    """Parse a memory .md file with YAML frontmatter."""
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
                frontmatter = _simple_frontmatter(parts[1])
            body = parts[2].strip()

    name = str(frontmatter.get("name", path.stem)).strip()
    description = str(frontmatter.get("description", "")).strip()
    type_str = str(frontmatter.get("type", "project")).strip().lower()

    try:
        mem_type = MemoryType(type_str)
    except ValueError:
        mem_type = MemoryType.PROJECT

    return MemoryEntry(
        name=name,
        description=description,
        type=mem_type,
        content=body,
        file_path=path,
    )


def _render_memory_file(entry: MemoryEntry) -> str:
    """Serialize a MemoryEntry back to frontmatter + body."""
    return (
        f"---\n"
        f"name: {entry.name}\n"
        f"description: {entry.description}\n"
        f"type: {entry.type.value}\n"
        f"---\n\n"
        f"{entry.content}\n"
    )


def _simple_frontmatter(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if ":" not in line or line.startswith("#"):
            continue
        key, _, value = line.partition(":")
        result[key.strip()] = value.strip().strip("'\"")
    return result
