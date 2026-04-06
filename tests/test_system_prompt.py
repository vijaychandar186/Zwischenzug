"""Tests for src/core/system_prompt — build_system_prompt, load_project_instructions."""
from __future__ import annotations

import pytest

from src.core.system_prompt import (
    DEFAULT_SYSTEM_PROMPT,
    build_system_prompt,
    load_project_instructions,
)


# ── build_system_prompt ───────────────────────────────────────────────────────

class TestBuildSystemPrompt:
    def test_default_prompt_used_when_base_empty(self):
        result = build_system_prompt(base="")
        assert DEFAULT_SYSTEM_PROMPT.strip()[:20] in result

    def test_custom_base_replaces_default(self):
        result = build_system_prompt(base="My custom base.")
        assert "My custom base." in result
        assert DEFAULT_SYSTEM_PROMPT not in result

    def test_zwischenzug_md_included_when_provided(self):
        result = build_system_prompt(base="Base.", zwischenzug_md="# Project Rules\nAlways test.")
        assert "Project Rules" in result
        assert "Always test." in result

    def test_zwischenzug_md_omitted_when_none(self):
        result = build_system_prompt(base="Base.", zwischenzug_md=None)
        assert "Project Instructions" not in result

    def test_zwischenzug_md_omitted_when_whitespace(self):
        result = build_system_prompt(base="Base.", zwischenzug_md="   \n  ")
        assert "Project Instructions" not in result

    def test_memory_index_included_when_provided(self):
        result = build_system_prompt(base="Base.", memory_index="- [Rule A](rule_a.md) — Some rule")
        assert "Persistent Memory" in result
        assert "Rule A" in result

    def test_memory_index_omitted_when_none(self):
        result = build_system_prompt(base="Base.", memory_index=None)
        assert "Persistent Memory" not in result

    def test_skill_context_included(self):
        result = build_system_prompt(base="Base.", skill_context="Skill: Do the commit.")
        assert "Skill: Do the commit." in result

    def test_skill_context_omitted_when_none(self):
        result = build_system_prompt(base="Base.", skill_context=None)
        assert "skill" not in result.lower()

    def test_all_sections_included(self):
        result = build_system_prompt(
            base="Base prompt.",
            zwischenzug_md="Project rules.",
            memory_index="Memory index.",
            skill_context="Skill context.",
        )
        assert "Base prompt." in result
        assert "Project rules." in result
        assert "Memory index." in result
        assert "Skill context." in result

    def test_sections_separated_by_divider(self):
        result = build_system_prompt(
            base="Base.",
            zwischenzug_md="Project.",
            memory_index="Memory.",
        )
        assert "---" in result

    def test_base_stripped_before_comparison(self):
        result = build_system_prompt(base="   \n  ")
        # Whitespace-only base should use default
        assert DEFAULT_SYSTEM_PROMPT.strip()[:20] in result

    def test_returns_string(self):
        result = build_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 0


# ── load_project_instructions ─────────────────────────────────────────────────

class TestLoadProjectInstructions:
    def test_loads_zwischenzug_md(self, tmp_path):
        (tmp_path / "ZWISCHENZUG.md").write_text("# Project rules")
        result = load_project_instructions(str(tmp_path))
        assert result == "# Project rules"

    def test_loads_dot_zwischenzug_as_fallback(self, tmp_path):
        (tmp_path / ".zwischenzug").write_text("Project memory")
        result = load_project_instructions(str(tmp_path))
        assert result == "Project memory"

    def test_prefers_zwischenzug_md_over_dot_zwischenzug(self, tmp_path):
        (tmp_path / "ZWISCHENZUG.md").write_text("main content")
        (tmp_path / ".zwischenzug").write_text("fallback content")
        result = load_project_instructions(str(tmp_path))
        assert result == "main content"

    def test_returns_none_when_no_files(self, tmp_path):
        assert load_project_instructions(str(tmp_path)) is None

    def test_returns_none_for_empty_file(self, tmp_path):
        (tmp_path / "ZWISCHENZUG.md").write_text("   \n  ")
        assert load_project_instructions(str(tmp_path)) is None

    def test_strips_surrounding_whitespace(self, tmp_path):
        (tmp_path / "ZWISCHENZUG.md").write_text("  content  \n")
        result = load_project_instructions(str(tmp_path))
        assert result == "content"
