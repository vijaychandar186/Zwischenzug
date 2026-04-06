"""
Tests for src/modes — connection mode stubs.
"""
from __future__ import annotations

import pytest

from src.modes import (
    run_deep_link,
    run_direct_connect,
    run_remote_mode,
    run_ssh_mode,
    run_teleport_mode,
)


@pytest.mark.parametrize("fn,expected_prefix", [
    (run_remote_mode, "mode=remote"),
    (run_ssh_mode, "mode=ssh"),
    (run_teleport_mode, "mode=teleport"),
    (run_direct_connect, "mode=direct-connect"),
    (run_deep_link, "mode=deep-link"),
])
def test_mode_returns_expected_prefix(fn, expected_prefix):
    result = fn("workspace-1")
    assert result.startswith(expected_prefix)


@pytest.mark.parametrize("fn", [
    run_remote_mode, run_ssh_mode, run_teleport_mode,
    run_direct_connect, run_deep_link,
])
def test_mode_includes_target(fn):
    target = "my-target-host"
    result = fn(target)
    assert target in result


@pytest.mark.parametrize("fn", [
    run_remote_mode, run_ssh_mode, run_teleport_mode,
    run_direct_connect, run_deep_link,
])
def test_mode_returns_string(fn):
    assert isinstance(fn("host"), str)
