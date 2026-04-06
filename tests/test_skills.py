"""Tests for src/skills — SkillRegistry, Skill, and file parsing."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.skills import Skill, SkillRegistry, _parse_skill_file, _parse_simple_frontmatter


# ── _parse_simple_frontmatter ─────────────────────────────────────────────────

class TestParseSimpleFrontmatter:
    def test_basic_key_value(self):
        text = "name: my-skill\ndescription: Does things\n"
        result = _parse_simple_frontmatter(text)
        assert result["name"] == "my-skill"
        assert result["description"] == "Does things"

    def test_list_value(self):
        text = "aliases: [a, b, c]\n"
        result = _parse_simple_frontmatter(text)
        assert result["aliases"] == ["a", "b", "c"]

    def test_ignores_comment_lines(self):
        text = "# comment\nname: test\n"
        result = _parse_simple_frontmatter(text)
        assert "name" in result
        assert "#" not in result

    def test_strips_quotes(self):
        text = "name: 'quoted'\n"
        result = _parse_simple_frontmatter(text)
        assert result["name"] == "quoted"

    def test_empty_string(self):
        assert _parse_simple_frontmatter("") == {}


# ── _parse_skill_file ─────────────────────────────────────────────────────────

class TestParseSkillFile:
    def _write_skill(self, tmp_path: Path, content: str, name: str = "test.md") -> Path:
        p = tmp_path / name
        p.write_text(content)
        return p

    def test_parses_name_and_description(self, tmp_path):
        p = self._write_skill(tmp_path, "---\nname: my-skill\ndescription: My skill\n---\nDo something.\n")
        skill = _parse_skill_file(p)
        assert skill.name == "my-skill"
        assert skill.description == "My skill"

    def test_parses_aliases(self, tmp_path):
        p = self._write_skill(tmp_path, "---\nname: commit\naliases: [c, ci]\n---\nCommit.\n")
        skill = _parse_skill_file(p)
        assert "c" in skill.aliases
        assert "ci" in skill.aliases

    def test_parses_allowed_tools(self, tmp_path):
        p = self._write_skill(tmp_path, "---\nname: s\nallowedTools: [bash, read_file]\n---\nbody\n")
        skill = _parse_skill_file(p)
        assert skill.allowed_tools == ["bash", "read_file"]

    def test_allowed_tools_none_when_absent(self, tmp_path):
        p = self._write_skill(tmp_path, "---\nname: s\n---\nbody\n")
        skill = _parse_skill_file(p)
        assert skill.allowed_tools is None

    def test_body_is_prompt_template(self, tmp_path):
        p = self._write_skill(tmp_path, "---\nname: s\n---\nDo {{{args}}} now.\n")
        skill = _parse_skill_file(p)
        assert "{{{args}}}" in skill.prompt_template

    def test_fallback_name_is_stem(self, tmp_path):
        p = self._write_skill(tmp_path, "just a body, no frontmatter", name="myscill.md")
        skill = _parse_skill_file(p)
        assert skill.name == "myscill"

    def test_context_defaults_to_inline(self, tmp_path):
        p = self._write_skill(tmp_path, "---\nname: s\n---\nbody\n")
        skill = _parse_skill_file(p)
        assert skill.context == "inline"

    def test_context_fork(self, tmp_path):
        p = self._write_skill(tmp_path, "---\nname: s\ncontext: fork\n---\nbody\n")
        skill = _parse_skill_file(p)
        assert skill.context == "fork"

    def test_model_parsed(self, tmp_path):
        p = self._write_skill(tmp_path, "---\nname: s\nmodel: gemini-2.0-flash\n---\nbody\n")
        skill = _parse_skill_file(p)
        assert skill.model == "gemini-2.0-flash"

    def test_model_none_when_absent(self, tmp_path):
        p = self._write_skill(tmp_path, "---\nname: s\n---\nbody\n")
        skill = _parse_skill_file(p)
        assert skill.model is None

    def test_raises_if_name_empty(self, tmp_path):
        p = self._write_skill(tmp_path, "---\nname: ''\n---\nbody\n")
        with pytest.raises(ValueError, match="no 'name'"):
            _parse_skill_file(p)


# ── Skill ─────────────────────────────────────────────────────────────────────

class TestSkill:
    def test_expand_substitutes_args(self):
        s = Skill(name="s", description="", prompt_template="Do {{{args}}} here.")
        assert s.expand("the thing") == "Do the thing here."

    def test_expand_empty_args(self):
        s = Skill(name="s", description="", prompt_template="Base prompt. {{{args}}}")
        assert s.expand("") == "Base prompt."

    def test_expand_no_placeholder(self):
        s = Skill(name="s", description="", prompt_template="No placeholder.")
        assert s.expand("ignored") == "No placeholder."

    def test_matches_by_name(self):
        s = Skill(name="commit", description="", aliases=["c"])
        assert s.matches("commit")
        assert s.matches("COMMIT")

    def test_matches_by_alias(self):
        s = Skill(name="commit", description="", aliases=["c", "ci"])
        assert s.matches("c")
        assert s.matches("CI")

    def test_matches_strips_slash(self):
        s = Skill(name="commit", description="", aliases=[])
        assert s.matches("/commit")

    def test_not_matches_unknown(self):
        s = Skill(name="commit", description="", aliases=["c"])
        assert not s.matches("push")


# ── SkillRegistry ─────────────────────────────────────────────────────────────

class TestSkillRegistry:
    def _make_registry(self, skills: list[Skill]) -> SkillRegistry:
        return SkillRegistry(skills)

    def test_get_by_name(self):
        reg = self._make_registry([Skill(name="commit", description="", aliases=[])])
        assert reg.get("commit") is not None

    def test_get_by_alias(self):
        reg = self._make_registry([Skill(name="commit", description="", aliases=["c"])])
        assert reg.get("c") is not None

    def test_get_strips_slash(self):
        reg = self._make_registry([Skill(name="commit", description="", aliases=[])])
        assert reg.get("/commit") is not None

    def test_get_unknown_returns_none(self):
        reg = self._make_registry([Skill(name="commit", description="", aliases=[])])
        assert reg.get("ghost") is None

    def test_all_returns_unique_skills(self):
        s = Skill(name="commit", description="", aliases=["c"])
        reg = self._make_registry([s])
        all_skills = reg.all()
        assert len(all_skills) == 1

    def test_all_sorted_by_name(self):
        reg = self._make_registry([
            Skill(name="zebra", description="", aliases=[]),
            Skill(name="apple", description="", aliases=[]),
        ])
        names = [s.name for s in reg.all()]
        assert names == sorted(names)

    def test_len(self):
        reg = self._make_registry([
            Skill(name="a", description="", aliases=[]),
            Skill(name="b", description="", aliases=[]),
        ])
        assert len(reg) == 2

    def test_expand_delegates_to_skill(self):
        s = Skill(name="s", description="", prompt_template="Do {{{args}}}.")
        reg = self._make_registry([s])
        assert reg.expand(s, "this") == "Do this."

    def test_discover_loads_builtin_skills(self, tmp_path):
        reg = SkillRegistry.discover(cwd=str(tmp_path))
        names = reg.names()
        # Built-in skills should be discovered
        assert "commit" in names or len(reg) > 0

    def test_discover_loads_custom_skill_from_project_dir(self, tmp_path):
        skills_dir = tmp_path / ".zwis" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "custom.md").write_text(
            "---\nname: custom-skill\ndescription: Test\n---\nDo something.\n"
        )
        reg = SkillRegistry.discover(cwd=str(tmp_path))
        assert reg.get("custom-skill") is not None

    def test_project_skill_overrides_builtin(self, tmp_path):
        skills_dir = tmp_path / ".zwis" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "commit.md").write_text(
            "---\nname: commit\ndescription: Custom commit\n---\nCustom template.\n"
        )
        reg = SkillRegistry.discover(cwd=str(tmp_path))
        skill = reg.get("commit")
        assert skill is not None
        assert skill.description == "Custom commit"

    def test_discover_ignores_invalid_files(self, tmp_path):
        skills_dir = tmp_path / ".zwis" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "bad.md").write_text("---\nname: ''\n---\nbody\n")
        # Should not raise; just silently skip
        reg = SkillRegistry.discover(cwd=str(tmp_path))
        assert reg.get("") is None
