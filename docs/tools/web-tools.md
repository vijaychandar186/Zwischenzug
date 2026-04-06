# Web Tools

## Overview

Web tools (`src/tools/web.py`) provide HTTP fetching and web search capabilities.

---

## WebFetch

Fetches a URL and returns the content as markdown, JSON, or raw text.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | Yes | — | The URL to fetch |
| `format` | string | No | `markdown` | Output format: `markdown`, `json`, or `raw` |

**Read-only**: Yes

### Behavior

1. Makes an HTTP GET request using `httpx`
2. Follows redirects
3. For HTML responses: converts to markdown using `html2text`
4. For JSON responses: returns formatted JSON
5. For other content types: returns raw text
6. Respects timeout limits

### Error Handling

- Connection errors return a descriptive error message
- HTTP error status codes are reported with the status code
- Timeout errors indicate the request exceeded the time limit

---

## WebSearch

Performs a web search using DuckDuckGo via the `ddgs` package — no API key required.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | — | The search query |
| `max_results` | int | No | 5 | Maximum number of results |

**Read-only**: Yes

### Behavior

1. Queries DuckDuckGo via the `ddgs` library
2. Returns a list of results with title, URL, and snippet
3. No API key or authentication required
4. Runs the blocking search call inside `asyncio.to_thread()`

### Dependencies

- `httpx` — HTTP client
- `html2text` — HTML to markdown conversion
- `ddgs` — Web search without API keys

---

## Relationship to Browser Tools

Web tools are **API-based** — they make direct HTTP requests and parse responses. No browser is involved.

For browser-based automation (navigating pages, clicking buttons, filling forms, running JavaScript), see [browser-tool.md](browser-tool.md) which covers:
- `browser` — low-level, step-by-step browser control
- `browser_agent` — autonomous browser agent that plans and executes tasks on its own
