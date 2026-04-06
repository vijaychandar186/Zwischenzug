"""Tests for the browser automation tool."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools import PermissionMode, ToolContext
from src.tools.browser import BrowserTool, _BROWSER_SESSIONS


@pytest.fixture
def ctx(tmp_path) -> ToolContext:
    return ToolContext(
        cwd=str(tmp_path),
        permission_mode=PermissionMode.AUTO,
        session_id="test-browser",
    )


@pytest.fixture
def tool() -> BrowserTool:
    return BrowserTool()


@pytest.fixture(autouse=True)
def _clear_sessions():
    _BROWSER_SESSIONS.clear()
    yield
    _BROWSER_SESSIONS.clear()


class TestBrowserMetadata:
    def test_name(self, tool):
        assert tool.name == "browser"

    def test_not_read_only(self, tool):
        assert not tool.is_read_only

    def test_schema_requires_action(self, tool):
        assert "action" in tool.input_schema()["required"]


class TestBrowserWithoutBrowserUse:
    """Tests when browser-use is not installed."""

    @pytest.mark.asyncio
    async def test_not_installed_returns_error(self, tool, ctx):
        with patch("src.tools.browser._browser_use_available", return_value=False):
            result = await tool.execute(ctx, action="open", url="http://example.com")
        assert result.is_error
        assert "browser-use" in result.content.lower()
        assert "pip install" in result.content


class TestBrowserActions:
    """Test action dispatching and validation."""

    @pytest.mark.asyncio
    async def test_unknown_action(self, tool, ctx):
        with patch("src.tools.browser._browser_use_available", return_value=True):
            # Mock the browser import so it doesn't fail
            result = await tool.execute(ctx, action="explode")
        assert result.is_error
        assert "unknown" in result.content.lower()

    @pytest.mark.asyncio
    async def test_open_no_url(self, tool, ctx):
        with patch("src.tools.browser._browser_use_available", return_value=True):
            with patch.object(tool, "_open", new_callable=AsyncMock) as mock_open:
                mock_open.return_value = __import__("src.tools", fromlist=["ToolOutput"]).ToolOutput.error("'open' requires a 'url'.")
                result = await tool.execute(ctx, action="open")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_click_no_selector(self, tool, ctx):
        with patch("src.tools.browser._browser_use_available", return_value=True):
            with patch.object(tool, "_click", new_callable=AsyncMock) as mock_click:
                mock_click.return_value = __import__("src.tools", fromlist=["ToolOutput"]).ToolOutput.error("'click' requires a 'selector'.")
                result = await tool.execute(ctx, action="click")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_close_no_session(self, tool, ctx):
        with patch("src.tools.browser._browser_use_available", return_value=True):
            result = await tool.execute(ctx, action="close")
        assert not result.is_error
        assert "no browser" in result.content.lower()


class TestBrowserImplementation:
    @pytest.fixture
    def state(self):
        session = AsyncMock()
        page = AsyncMock()
        session.get_current_page.return_value = page
        return {"session": session, "page": page}

    @pytest.mark.asyncio
    async def test_open_uses_browser_use_page_title(self, tool, ctx, state):
        state["session"].navigate_to = AsyncMock()
        state["page"].get_title = AsyncMock(return_value="OpenAI")

        with patch.object(tool, "_get_or_create_browser", AsyncMock(return_value={"session": state["session"]})):
            result = await tool.execute(ctx, action="open", url="https://openai.com")

        assert not result.is_error
        assert "Title: OpenAI" in result.content
        state["session"].navigate_to.assert_awaited_once_with("https://openai.com")
        state["page"].get_title.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_click_uses_css_element_click(self, tool, ctx, state):
        element = AsyncMock()
        state["page"].get_elements_by_css_selector = AsyncMock(return_value=[element])

        with patch.object(tool, "_get_or_create_browser", AsyncMock(return_value={"session": state["session"]})):
            result = await tool.execute(ctx, action="click", selector="button[type=submit]")

        assert not result.is_error
        element.click.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_click_falls_back_to_text_lookup(self, tool, ctx, state):
        state["page"].get_elements_by_css_selector = AsyncMock(side_effect=Exception("bad selector"))
        state["page"].evaluate = AsyncMock(return_value="true")

        with patch.object(tool, "_get_or_create_browser", AsyncMock(return_value={"session": state["session"]})):
            result = await tool.execute(ctx, action="click", selector="Search")

        assert not result.is_error
        state["page"].evaluate.assert_awaited_once()
        args = state["page"].evaluate.await_args.args
        assert "match.click()" in args[0]
        assert args[1] == "Search"

    @pytest.mark.asyncio
    async def test_type_uses_css_element_fill(self, tool, ctx, state):
        element = AsyncMock()
        state["page"].get_elements_by_css_selector = AsyncMock(return_value=[element])

        with patch.object(tool, "_get_or_create_browser", AsyncMock(return_value={"session": state["session"]})):
            result = await tool.execute(ctx, action="type", selector="textarea", text="hello")

        assert not result.is_error
        element.fill.assert_awaited_once_with("hello")

    @pytest.mark.asyncio
    async def test_content_wraps_text_extraction_in_arrow_function(self, tool, ctx, state):
        state["page"].evaluate = AsyncMock(return_value="Page body")

        with patch.object(tool, "_get_or_create_browser", AsyncMock(return_value={"session": state["session"]})):
            result = await tool.execute(ctx, action="content")

        assert not result.is_error
        state["page"].evaluate.assert_awaited_once_with(
            "() => document.body ? document.body.innerText : document.documentElement.innerText"
        )

    @pytest.mark.asyncio
    async def test_evaluate_wraps_plain_expression(self, tool, ctx, state):
        state["page"].evaluate = AsyncMock(return_value="3")

        with patch.object(tool, "_get_or_create_browser", AsyncMock(return_value={"session": state["session"]})):
            result = await tool.execute(ctx, action="evaluate", script="1 + 2")

        assert not result.is_error
        state["page"].evaluate.assert_awaited_once_with("() => (1 + 2)")

    @pytest.mark.asyncio
    async def test_scroll_uses_arrow_function(self, tool, ctx, state):
        state["page"].evaluate = AsyncMock(return_value="1200")

        with patch.object(tool, "_get_or_create_browser", AsyncMock(return_value={"session": state["session"]})):
            result = await tool.execute(ctx, action="scroll", direction="down")

        assert not result.is_error
        state["page"].evaluate.assert_awaited_once_with(
            "() => { window.scrollBy(0, window.innerHeight); return window.scrollY; }"
        )


class TestRegistryIntegration:
    def test_in_default_registry(self):
        from src.tools import default_registry
        assert default_registry().get("browser") is not None
