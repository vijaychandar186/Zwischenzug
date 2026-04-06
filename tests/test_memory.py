"""Tests for src/memory — MemoryManager, MemoryEntry, MemoryType."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.memory import (
    MemoryEntry,
    MemoryManager,
    MemoryType,
    _parse_memory_file,
    _render_memory_file,
    _simple_frontmatter,
)


# ── _simple_frontmatter ───────────────────────────────────────────────────────

class TestSimpleFrontmatter:
    def test_parses_basic_keys(self):
        text = "name: test\ndescription: desc\ntype: user\n"
        result = _simple_frontmatter(text)
        assert result["name"] == "test"
        assert result["description"] == "desc"

    def test_strips_quotes(self):
        result = _simple_frontmatter("name: 'quoted'\n")
        assert result["name"] == "quoted"

    def test_skips_comment_lines(self):
        result = _simple_frontmatter("# comment\nname: val\n")
        assert "name" in result
        assert "#" not in result

    def test_empty_text(self):
        assert _simple_frontmatter("") == {}


# ── _parse_memory_file ────────────────────────────────────────────────────────

class TestParseMemoryFile:
    def _write(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "test_memory.md"
        p.write_text(content)
        return p

    def test_parses_name(self, tmp_path):
        p = self._write(tmp_path, "---\nname: My Memory\ndescription: desc\ntype: user\n---\n\nContent here.\n")
        entry = _parse_memory_file(p)
        assert entry.name == "My Memory"

    def test_parses_description(self, tmp_path):
        p = self._write(tmp_path, "---\nname: M\ndescription: my desc\ntype: feedback\n---\n\nbody\n")
        entry = _parse_memory_file(p)
        assert entry.description == "my desc"

    def test_parses_type(self, tmp_path):
        p = self._write(tmp_path, "---\nname: M\ndescription: d\ntype: feedback\n---\n\nbody\n")
        entry = _parse_memory_file(p)
        assert entry.type == MemoryType.FEEDBACK

    def test_unknown_type_defaults_to_project(self, tmp_path):
        p = self._write(tmp_path, "---\nname: M\ndescription: d\ntype: unknown\n---\n\nbody\n")
        entry = _parse_memory_file(p)
        assert entry.type == MemoryType.PROJECT

    def test_body_is_content(self, tmp_path):
        p = self._write(tmp_path, "---\nname: M\ndescription: d\ntype: user\n---\n\nMy actual content.\n")
        entry = _parse_memory_file(p)
        assert "My actual content." in entry.content

    def test_fallback_name_is_stem(self, tmp_path):
        p = tmp_path / "my_memory.md"
        p.write_text("no frontmatter here")
        entry = _parse_memory_file(p)
        assert entry.name == "my_memory"


# ── _render_memory_file ───────────────────────────────────────────────────────

class TestRenderMemoryFile:
    def test_renders_frontmatter_and_body(self, tmp_path):
        entry = MemoryEntry(
            name="Test Memory",
            description="A test",
            type=MemoryType.USER,
            content="The actual content.",
            file_path=tmp_path / "test.md",
        )
        rendered = _render_memory_file(entry)
        assert "name: Test Memory" in rendered
        assert "type: user" in rendered
        assert "The actual content." in rendered

    def test_round_trip(self, tmp_path):
        entry = MemoryEntry(
            name="Round Trip",
            description="Testing round trip",
            type=MemoryType.FEEDBACK,
            content="Some feedback.",
            file_path=tmp_path / "round_trip.md",
        )
        rendered = _render_memory_file(entry)
        path = tmp_path / "round_trip.md"
        path.write_text(rendered)
        parsed = _parse_memory_file(path)
        assert parsed.name == entry.name
        assert parsed.type == entry.type
        assert "Some feedback." in parsed.content


# ── MemoryEntry ───────────────────────────────────────────────────────────────

class TestMemoryEntry:
    def test_filename_derived_from_name(self, tmp_path):
        entry = MemoryEntry(
            name="User Role",
            description="",
            type=MemoryType.USER,
            content="",
            file_path=tmp_path / "placeholder.md",
        )
        assert entry.filename == "user_role.md"

    def test_filename_removes_special_chars(self, tmp_path):
        entry = MemoryEntry(
            name="A-B C!D",
            description="",
            type=MemoryType.USER,
            content="",
            file_path=tmp_path / "placeholder.md",
        )
        assert entry.filename.endswith(".md")
        assert " " not in entry.filename


# ── MemoryManager ─────────────────────────────────────────────────────────────

class TestMemoryManager:
    def _mgr(self, tmp_path: Path) -> MemoryManager:
        return MemoryManager(tmp_path / "memory")

    def _entry(self, name: str, tmp_path: Path, mem_type: MemoryType = MemoryType.USER) -> MemoryEntry:
        # Use a path outside the memory dir so save() derives the filename from the name.
        return MemoryEntry(
            name=name,
            description=f"Description of {name}",
            type=mem_type,
            content=f"Content for {name}.",
            file_path=tmp_path / "placeholder.md",
        )

    def test_list_memories_empty_when_no_dir(self, tmp_path):
        mgr = self._mgr(tmp_path)
        assert mgr.list_memories() == []

    def test_save_creates_file(self, tmp_path):
        mgr = self._mgr(tmp_path)
        entry = self._entry("test-memory", tmp_path)
        mgr.save(entry)
        mem_dir = tmp_path / "memory"
        assert any(mem_dir.glob("*.md"))

    def test_save_updates_index(self, tmp_path):
        mgr = self._mgr(tmp_path)
        mgr.save(self._entry("alpha", tmp_path))
        index = mgr.load_index()
        assert "alpha" in index

    def test_list_memories_returns_saved(self, tmp_path):
        mgr = self._mgr(tmp_path)
        mgr.save(self._entry("mem-one", tmp_path))
        mgr.save(self._entry("mem-two", tmp_path, MemoryType.FEEDBACK))
        memories = mgr.list_memories()
        names = {m.name for m in memories}
        assert "mem-one" in names
        assert "mem-two" in names

    def test_list_memories_excludes_memory_md(self, tmp_path):
        mgr = self._mgr(tmp_path)
        mgr.save(self._entry("x", tmp_path))
        memories = mgr.list_memories()
        assert all(m.name != "MEMORY" for m in memories)

    def test_get_by_name(self, tmp_path):
        mgr = self._mgr(tmp_path)
        mgr.save(self._entry("find-me", tmp_path))
        found = mgr.get("find-me")
        assert found is not None
        assert found.name == "find-me"

    def test_get_case_insensitive(self, tmp_path):
        mgr = self._mgr(tmp_path)
        mgr.save(self._entry("CamelCase", tmp_path))
        assert mgr.get("camelcase") is not None

    def test_get_unknown_returns_none(self, tmp_path):
        mgr = self._mgr(tmp_path)
        assert mgr.get("does-not-exist") is None

    def test_delete_removes_file(self, tmp_path):
        mgr = self._mgr(tmp_path)
        mgr.save(self._entry("remove-me", tmp_path))
        result = mgr.delete("remove-me")
        assert result is True
        assert mgr.get("remove-me") is None

    def test_delete_returns_false_when_not_found(self, tmp_path):
        mgr = self._mgr(tmp_path)
        assert mgr.delete("phantom") is False

    def test_delete_updates_index(self, tmp_path):
        mgr = self._mgr(tmp_path)
        mgr.save(self._entry("keep", tmp_path))
        mgr.save(self._entry("remove", tmp_path, MemoryType.FEEDBACK))
        mgr.delete("remove")
        index = mgr.load_index()
        assert "remove" not in index
        assert "keep" in index

    def test_load_index_empty_string_when_no_file(self, tmp_path):
        mgr = self._mgr(tmp_path)
        assert mgr.load_index() == ""

    def test_load_index_caps_at_200_lines(self, tmp_path):
        mgr = self._mgr(tmp_path)
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        idx = mem_dir / "MEMORY.md"
        idx.write_text("\n".join(f"line {i}" for i in range(300)))
        result = mgr.load_index()
        assert len(result.splitlines()) == 200

    def test_render_list_no_memories(self, tmp_path):
        mgr = self._mgr(tmp_path)
        output = mgr.render_list()
        assert "No memories" in output

    def test_render_list_shows_entries(self, tmp_path):
        mgr = self._mgr(tmp_path)
        mgr.save(self._entry("alpha", tmp_path))
        output = mgr.render_list()
        assert "alpha" in output

    def test_render_entry_not_found(self, tmp_path):
        mgr = self._mgr(tmp_path)
        output = mgr.render_entry("ghost")
        assert "not found" in output.lower()

    def test_render_entry_found(self, tmp_path):
        mgr = self._mgr(tmp_path)
        mgr.save(self._entry("my-note", tmp_path))
        output = mgr.render_entry("my-note")
        assert "my-note" in output
