"""
Shared fixtures and helpers for the Zwischenzug test suite.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.compact import TokenBudget, TruncateStrategy
from src.core.session import SessionConfig, SessionState
from src.tools import PermissionMode, ToolContext, ToolOrchestrator, ToolRegistry


# ── session helpers ──────────────────────────────────────────────────────────

@pytest.fixture
def minimal_config() -> SessionConfig:
    return SessionConfig(
        model="test-model",
        system_prompt="",
        max_turns=10,
        permission_mode="auto",
    )


@pytest.fixture
def session(minimal_config, tmp_path) -> SessionState:
    return SessionState.new(minimal_config, cwd=str(tmp_path))


@pytest.fixture
def auto_ctx(tmp_path) -> ToolContext:
    return ToolContext(cwd=str(tmp_path), permission_mode=PermissionMode.AUTO)


@pytest.fixture
def deny_ctx(tmp_path) -> ToolContext:
    return ToolContext(cwd=str(tmp_path), permission_mode=PermissionMode.DENY)


@pytest.fixture
def registry() -> ToolRegistry:
    from src.tools import default_registry
    return default_registry()


@pytest.fixture
def orchestrator(registry) -> ToolOrchestrator:
    return ToolOrchestrator(registry)


# ── mock LLM helpers ─────────────────────────────────────────────────────────

def _make_astream(responses):
    """Create an async generator factory from a list of responses or a single response."""
    if not isinstance(responses, list):
        responses = [responses]
    call_count = 0

    async def _astream(messages):
        nonlocal call_count
        resp = responses[call_count % len(responses)]
        call_count += 1
        yield resp

    return _astream


def make_text_llm(text: str = "All done.") -> MagicMock:
    """LLM that always returns a plain text response (no tool calls)."""
    response = AIMessage(content=text)
    response.tool_calls = []
    response.usage_metadata = {"input_tokens": 10, "output_tokens": 5}

    llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=llm)
    llm.ainvoke = AsyncMock(return_value=response)
    llm.astream = _make_astream(response)
    return llm


def make_tool_then_text_llm(tool_name: str, tool_args: dict, final_text: str = "Done.") -> MagicMock:
    """LLM that calls one tool on turn 1, then finishes with text on turn 2."""
    tool_response = AIMessage(content="")
    tool_response.tool_calls = [{"id": "call-1", "name": tool_name, "args": tool_args}]
    tool_response.usage_metadata = {"input_tokens": 15, "output_tokens": 3}

    final_response = AIMessage(content=final_text)
    final_response.tool_calls = []
    final_response.usage_metadata = {"input_tokens": 20, "output_tokens": 8}

    llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=llm)
    llm.ainvoke = AsyncMock(side_effect=[tool_response, final_response])
    llm.astream = _make_astream([tool_response, final_response])
    return llm
