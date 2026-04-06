"""Tests for the browser agent tool."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools import PermissionMode, ToolContext
from src.tools.browser_agent import BrowserAgentTool, _build_llm


@pytest.fixture
def ctx(tmp_path) -> ToolContext:
    return ToolContext(
        cwd=str(tmp_path),
        permission_mode=PermissionMode.AUTO,
        session_id="test-browser-agent",
    )


@pytest.fixture
def tool() -> BrowserAgentTool:
    return BrowserAgentTool()


class TestBrowserAgentMetadata:
    def test_name(self, tool):
        assert tool.name == "browser_agent"

    def test_not_read_only(self, tool):
        assert not tool.is_read_only

    def test_schema_requires_task(self, tool):
        assert "task" in tool.input_schema()["required"]

    def test_description_mentions_autonomous(self, tool):
        assert "autonomous" in tool.description.lower() or "task" in tool.description.lower()


class TestBrowserAgentValidation:
    @pytest.mark.asyncio
    async def test_empty_task_returns_error(self, tool, ctx):
        with patch("src.tools.browser_agent._browser_use_available", return_value=True):
            result = await tool.execute(ctx, task="")
        assert result.is_error
        assert "task" in result.content.lower()

    @pytest.mark.asyncio
    async def test_not_installed_returns_error(self, tool, ctx):
        with patch("src.tools.browser_agent._browser_use_available", return_value=False):
            result = await tool.execute(ctx, task="search for openai")
        assert result.is_error
        assert "browser-use" in result.content.lower()


class TestBuildLlm:
    def test_gemini_provider(self):
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"}):
            llm = _build_llm("gemini", "gemini/gemini-2.0-flash")
            assert llm is not None

    def test_unsupported_provider_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            _build_llm("unsupported_provider", "some-model")

    def test_no_model_raises(self):
        with patch.dict("os.environ", {"ZWISCHENZUG_MODEL": "", "BROWSER_AGENT_MODEL": ""}):
            with pytest.raises(ValueError, match="No LLM configured"):
                _build_llm(None, None)


class TestRegistryIntegration:
    def test_in_default_registry(self):
        from src.tools import default_registry
        assert default_registry().get("browser_agent") is not None
