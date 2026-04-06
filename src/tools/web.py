"""Web tools — HTTP fetch and web search."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from . import Tool, ToolContext, ToolOutput

MAX_OUTPUT = 50_000  # chars — same cap as BashTool
_USER_AGENT = "Zwischenzug/1.0 (AI coding agent; +https://github.com/zwischenzug)"


class WebFetchTool(Tool):
    """Fetch a URL and return its content as markdown, JSON, or raw text."""

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetch the content of a URL and return it as markdown (default), "
            "pretty-printed JSON, or raw text. Useful for reading documentation, "
            "APIs, and web pages. HTML is converted to markdown automatically."
        )

    @property
    def is_read_only(self) -> bool:
        return True

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch.",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'markdown' (default), 'json', or 'raw'.",
                },
            },
            "required": ["url"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        url: str = kwargs["url"].strip()
        fmt: str = (kwargs.get("format") or "markdown").lower()

        try:
            import httpx
        except ImportError:
            return ToolOutput.error(
                "httpx is not installed. Run: pip install httpx"
            )

        try:
            import certifi

            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=30.0,
                headers={"User-Agent": _USER_AGENT},
                verify=certifi.where(),
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return ToolOutput.error(f"HTTP {exc.response.status_code}: {url}")
        except httpx.RequestError as exc:
            return ToolOutput.error(f"Request failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            return ToolOutput.error(f"Fetch error: {exc}")

        content_type = resp.headers.get("content-type", "").lower()
        body = resp.text

        if fmt == "json" or "application/json" in content_type:
            try:
                parsed = json.loads(body)
                body = json.dumps(parsed, indent=2, ensure_ascii=False)
            except json.JSONDecodeError:
                pass  # return raw if not valid JSON
        elif fmt == "markdown" and "text/html" in content_type:
            body = _html_to_markdown(body)

        if len(body) > MAX_OUTPUT:
            body = body[:MAX_OUTPUT] + f"\n...[truncated — {len(body)} chars total]"

        return ToolOutput.success(body or "(empty response)")


def _html_to_markdown(html: str) -> str:
    """Convert HTML to markdown. Falls back to plain-text strip if html2text missing."""
    try:
        import html2text
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        h.body_width = 0  # no wrapping
        return h.handle(html).strip()
    except ImportError:
        # Fallback: strip tags naively
        import re
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        return text.strip()


class WebSearchTool(Tool):
    """Search the web using DuckDuckGo and return ranked results."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web using DuckDuckGo. Returns a ranked list of results "
            "with title, URL, and a short snippet. No API key required."
        )

    @property
    def is_read_only(self) -> bool:
        return True

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 5, max 20).",
                },
            },
            "required": ["query"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        query: str = kwargs["query"].strip()
        max_results: int = min(int(kwargs.get("max_results") or 5), 20)

        try:
            from ddgs import DDGS
        except ImportError:
            return ToolOutput.error(
                "ddgs is not installed.\n"
                "Run: pip install ddgs"
            )

        try:
            results = await asyncio.to_thread(
                _ddg_search, query, max_results
            )
        except Exception as exc:  # noqa: BLE001
            return ToolOutput.error(f"Search failed: {exc}")

        if not results:
            return ToolOutput.success(f"No results found for: {query!r}")

        lines: list[str] = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "(no title)")
            href = r.get("href", "")
            body = r.get("body", "").replace("\n", " ").strip()
            lines.append(f"{i}. [{title}]({href})")
            if body:
                lines.append(f"   {body[:200]}")
            lines.append("")

        return ToolOutput.success("\n".join(lines).strip())


def _ddg_search(query: str, max_results: int) -> list[dict]:
    """Synchronous DuckDuckGo search — called via asyncio.to_thread."""
    from ddgs import DDGS
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))
