"""Tests for src/tools/web — WebFetchTool, WebSearchTool."""
from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools import PermissionMode, ToolContext
from src.tools.web import WebFetchTool, WebSearchTool, _html_to_markdown


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def ctx(tmp_path) -> ToolContext:
    return ToolContext(cwd=str(tmp_path), permission_mode=PermissionMode.AUTO)


def _make_httpx_mock(text: str, content_type: str = "text/html"):
    """Build a mock httpx.AsyncClient whose .get() returns a fake response."""
    mock_resp = MagicMock()
    mock_resp.text = text
    mock_resp.headers = {"content-type": content_type}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)
    return mock_client


# ── _html_to_markdown ─────────────────────────────────────────────────────────

class TestHtmlToMarkdown:
    def test_strips_simple_tags(self):
        result = _html_to_markdown("<p>Hello</p>")
        assert "Hello" in result
        assert "<p>" not in result

    def test_handles_empty_string(self):
        result = _html_to_markdown("")
        assert isinstance(result, str)


# ── WebFetchTool ──────────────────────────────────────────────────────────────

class TestWebFetchTool:
    @property
    def tool(self):
        return WebFetchTool()

    def test_name(self):
        assert self.tool.name == "web_fetch"

    def test_is_read_only(self):
        assert self.tool.is_read_only is True

    def test_input_schema_requires_url(self):
        schema = self.tool.input_schema()
        assert "url" in schema["required"]

    @pytest.mark.asyncio
    async def test_returns_error_if_httpx_missing(self, ctx):
        with patch.dict(sys.modules, {"httpx": None}):
            result = await self.tool.execute(ctx, url="http://example.com")
        assert result.is_error
        assert "httpx" in result.content.lower() or "install" in result.content.lower()

    @pytest.mark.asyncio
    async def test_returns_content_on_success(self, ctx):
        mock_client = _make_httpx_mock("<html><body><p>Hello world</p></body></html>", "text/html")
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await self.tool.execute(ctx, url="http://example.com")
        assert not result.is_error
        assert "Hello world" in result.content

    @pytest.mark.asyncio
    async def test_returns_json_pretty_printed(self, ctx):
        mock_client = _make_httpx_mock('{"key": "value"}', "application/json")
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await self.tool.execute(ctx, url="http://example.com", format="json")
        assert not result.is_error
        assert '"key"' in result.content

    @pytest.mark.asyncio
    async def test_raw_format_returns_text_as_is(self, ctx):
        mock_client = _make_httpx_mock("plain content here", "text/plain")
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await self.tool.execute(ctx, url="http://example.com", format="raw")
        assert not result.is_error
        assert "plain content here" in result.content

    @pytest.mark.asyncio
    async def test_truncates_long_content(self, ctx):
        long_body = "x" * 60_000
        mock_client = _make_httpx_mock(long_body, "text/plain")
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await self.tool.execute(ctx, url="http://example.com", format="raw")
        assert not result.is_error
        assert "truncated" in result.content

    @pytest.mark.asyncio
    async def test_http_status_error_returns_error_output(self, ctx):
        import httpx

        mock_req = MagicMock()
        mock_resp_obj = MagicMock()
        mock_resp_obj.status_code = 404

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(
            side_effect=httpx.HTTPStatusError("404", request=mock_req, response=mock_resp_obj)
        )

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await self.tool.execute(ctx, url="http://example.com")
        assert result.is_error
        assert "404" in result.content

    @pytest.mark.asyncio
    async def test_request_error_returns_error_output(self, ctx):
        import httpx

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(
            side_effect=httpx.RequestError("connection refused", request=MagicMock())
        )

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await self.tool.execute(ctx, url="http://example.com")
        assert result.is_error
        assert "Request failed" in result.content


# ── WebSearchTool ─────────────────────────────────────────────────────────────

class TestWebSearchTool:
    @property
    def tool(self):
        return WebSearchTool()

    def test_name(self):
        assert self.tool.name == "web_search"

    def test_is_read_only(self):
        assert self.tool.is_read_only is True

    def test_input_schema_requires_query(self):
        schema = self.tool.input_schema()
        assert "query" in schema["required"]

    @pytest.mark.asyncio
    async def test_returns_error_if_ddgs_missing(self, ctx):
        with patch.dict(sys.modules, {"ddgs": None}):
            result = await self.tool.execute(ctx, query="python asyncio")
        assert result.is_error
        assert "install" in result.content.lower() or "ddgs" in result.content.lower()

    @pytest.mark.asyncio
    async def test_returns_formatted_results(self, ctx):
        fake_results = [
            {"title": "Result One", "href": "http://one.com", "body": "First result snippet"},
            {"title": "Result Two", "href": "http://two.com", "body": "Second result snippet"},
        ]
        mock_ddgs = MagicMock()
        with patch.dict(sys.modules, {"ddgs": mock_ddgs}):
            with patch("src.tools.web._ddg_search", return_value=fake_results):
                result = await self.tool.execute(ctx, query="test query")
        assert not result.is_error
        assert "Result One" in result.content
        assert "Result Two" in result.content
        assert "http://one.com" in result.content

    @pytest.mark.asyncio
    async def test_no_results_returns_success_message(self, ctx):
        mock_ddgs = MagicMock()
        with patch.dict(sys.modules, {"ddgs": mock_ddgs}):
            with patch("src.tools.web._ddg_search", return_value=[]):
                result = await self.tool.execute(ctx, query="zzz no results")
        assert not result.is_error
        assert "No results" in result.content

    @pytest.mark.asyncio
    async def test_max_results_capped_at_20(self, ctx):
        captured_args = {}

        def fake_search(query, max_results):
            captured_args["max_results"] = max_results
            return []

        mock_ddgs = MagicMock()
        with patch.dict(sys.modules, {"ddgs": mock_ddgs}):
            with patch("src.tools.web._ddg_search", side_effect=fake_search):
                await self.tool.execute(ctx, query="q", max_results=999)
        assert captured_args["max_results"] == 20

    @pytest.mark.asyncio
    async def test_search_exception_returns_error(self, ctx):
        mock_ddgs = MagicMock()
        with patch.dict(sys.modules, {"ddgs": mock_ddgs}):
            with patch("src.tools.web._ddg_search", side_effect=RuntimeError("network down")):
                result = await self.tool.execute(ctx, query="test")
        assert result.is_error
        assert "network down" in result.content or "Search failed" in result.content
