"""Tests for src/permissions — PermissionRule, PermissionManager."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.permissions import PermissionManager, PermissionRule, ToolPermissionContext
from src.tools import PermissionMode


# ── ToolPermissionContext ─────────────────────────────────────────────────────

class TestToolPermissionContext:
    def test_blocks_exact_match(self):
        ctx = ToolPermissionContext.from_iterables(denied_tools=["bash"], denied_prefixes=[])
        assert ctx.blocks("bash")

    def test_blocks_prefix(self):
        ctx = ToolPermissionContext.from_iterables(denied_tools=[], denied_prefixes=["sys_"])
        assert ctx.blocks("sys_call")

    def test_case_insensitive(self):
        ctx = ToolPermissionContext.from_iterables(denied_tools=["Bash"], denied_prefixes=[])
        assert ctx.blocks("bash")

    def test_does_not_block_unrelated(self):
        ctx = ToolPermissionContext.from_iterables(denied_tools=["bash"], denied_prefixes=[])
        assert not ctx.blocks("grep")


# ── PermissionRule.parse ──────────────────────────────────────────────────────

class TestPermissionRuleParse:
    def test_parses_tool_with_pattern(self):
        rule = PermissionRule.parse("Bash(npm run *)", allow=True)
        assert rule is not None
        assert rule.tool == "Bash"
        assert rule.pattern == "npm run *"
        assert rule.allow is True

    def test_parses_wildcard(self):
        rule = PermissionRule.parse("*", allow=False)
        assert rule is not None
        assert rule.tool == "*"
        assert rule.pattern == "*"

    def test_parses_plain_tool_name(self):
        rule = PermissionRule.parse("Read", allow=True)
        assert rule is not None
        assert rule.tool == "Read"
        assert rule.pattern == "*"

    def test_empty_string_returns_none(self):
        assert PermissionRule.parse("", allow=True) is None

    def test_whitespace_only_returns_none(self):
        assert PermissionRule.parse("   ", allow=True) is None

    def test_deny_rule(self):
        rule = PermissionRule.parse("Bash(rm -rf *)", allow=False)
        assert rule is not None
        assert rule.allow is False

    def test_nested_parens_in_pattern(self):
        rule = PermissionRule.parse("Bash(git commit -m *)", allow=True)
        assert rule is not None
        assert "git commit" in rule.pattern


# ── PermissionRule.matches ────────────────────────────────────────────────────

class TestPermissionRuleMatches:
    def test_matches_tool_and_pattern(self):
        rule = PermissionRule(tool="Bash", pattern="npm run *", allow=True)
        assert rule.matches("Bash", "npm run test")

    def test_does_not_match_wrong_tool(self):
        rule = PermissionRule(tool="Bash", pattern="*", allow=True)
        assert not rule.matches("Read", "anything")

    def test_wildcard_tool_matches_all_tools(self):
        rule = PermissionRule(tool="*", pattern="*", allow=True)
        assert rule.matches("Bash", "echo hi")
        assert rule.matches("Read", "/etc/passwd")

    def test_pattern_glob_matching(self):
        rule = PermissionRule(tool="Read", pattern="src/**", allow=True)
        assert rule.matches("Read", "src/main.py")
        assert not rule.matches("Read", "tests/test.py")

    def test_case_insensitive_tool(self):
        rule = PermissionRule(tool="bash", pattern="*", allow=True)
        assert rule.matches("Bash", "echo hi")
        assert rule.matches("BASH", "echo hi")

    def test_case_insensitive_pattern(self):
        rule = PermissionRule(tool="Read", pattern="*.PY", allow=True)
        assert rule.matches("Read", "main.py")


# ── PermissionManager.check ───────────────────────────────────────────────────

class TestPermissionManagerCheck:
    def test_bypass_allows_everything(self):
        mgr = PermissionManager(
            mode=PermissionMode.DENY,
            bypass=True,
        )
        assert mgr.check("Bash", "rm -rf /", is_read_only=False) == "allow"

    def test_deny_mode_blocks_write_tools(self):
        mgr = PermissionManager(mode=PermissionMode.DENY)
        assert mgr.check("Bash", "echo hi", is_read_only=False) == "deny"

    def test_deny_mode_allows_read_only_tools(self):
        mgr = PermissionManager(mode=PermissionMode.DENY)
        assert mgr.check("Read", "/etc/hosts", is_read_only=True) == "allow"

    def test_read_only_tool_always_allowed_in_auto_mode(self):
        mgr = PermissionManager(mode=PermissionMode.AUTO)
        assert mgr.check("Grep", "pattern", is_read_only=True) == "allow"

    def test_deny_rule_blocks_matching_tool(self):
        rule = PermissionRule.parse("Bash(rm -rf *)", allow=False)
        mgr = PermissionManager(mode=PermissionMode.AUTO, deny_rules=[rule])
        assert mgr.check("Bash", "rm -rf /tmp", is_read_only=False) == "deny"

    def test_deny_rule_does_not_block_non_matching(self):
        rule = PermissionRule.parse("Bash(rm -rf *)", allow=False)
        mgr = PermissionManager(mode=PermissionMode.AUTO, deny_rules=[rule])
        assert mgr.check("Bash", "echo hello", is_read_only=False) != "deny"

    def test_allow_rule_allows_matching_tool(self):
        rule = PermissionRule.parse("Bash(npm run *)", allow=True)
        mgr = PermissionManager(
            mode=PermissionMode.INTERACTIVE,
            allow_rules=[rule],
        )
        assert mgr.check("Bash", "npm run test", is_read_only=False) == "allow"

    def test_deny_wins_over_allow(self):
        allow_rule = PermissionRule.parse("Bash(*)", allow=True)
        deny_rule = PermissionRule.parse("Bash(rm *)", allow=False)
        mgr = PermissionManager(
            mode=PermissionMode.AUTO,
            allow_rules=[allow_rule],
            deny_rules=[deny_rule],
        )
        assert mgr.check("Bash", "rm file.txt", is_read_only=False) == "deny"

    def test_interactive_mode_default_asks(self):
        mgr = PermissionManager(mode=PermissionMode.INTERACTIVE)
        assert mgr.check("Bash", "echo hi", is_read_only=False) == "ask"

    def test_auto_mode_default_allows(self):
        mgr = PermissionManager(mode=PermissionMode.AUTO)
        assert mgr.check("Bash", "echo hi", is_read_only=False) == "allow"


# ── PermissionManager.from_settings ──────────────────────────────────────────

class TestPermissionManagerFromSettings:
    def test_loads_allow_rules(self, tmp_path):
        settings = tmp_path / ".zwis" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({
            "permissions": {
                "allow": ["Bash(npm run *)"],
                "deny": [],
            }
        }))
        with patch("src.app_paths.app_home", return_value=tmp_path / ".zwis"):
            mgr = PermissionManager.from_settings(cwd=str(tmp_path))
        assert len(mgr.allow_rules) >= 1

    def test_loads_deny_rules(self, tmp_path):
        settings = tmp_path / ".zwis" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({
            "permissions": {
                "allow": [],
                "deny": ["Bash(rm -rf *)"],
            }
        }))
        with patch("src.app_paths.app_home", return_value=tmp_path / ".zwis"):
            mgr = PermissionManager.from_settings(cwd=str(tmp_path))
        assert len(mgr.deny_rules) >= 1

    def test_missing_settings_gives_no_rules(self, tmp_path):
        mgr = PermissionManager.from_settings(cwd=str(tmp_path))
        assert mgr.allow_rules == []
        assert mgr.deny_rules == []

    def test_invalid_json_file_is_skipped(self, tmp_path):
        settings = tmp_path / ".zwis" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text("INVALID JSON {{{")
        with patch("src.app_paths.app_home", return_value=tmp_path / ".zwis"):
            mgr = PermissionManager.from_settings(cwd=str(tmp_path))
        assert mgr.allow_rules == []
