# Browser Tools

Zwischenzug provides two browser tools with different levels of autonomy, both powered by the [browser-use](https://browser-use.com/) library.

| Tool | Module | Description |
|------|--------|-------------|
| `browser` | `src/tools/browser.py` | **Low-level** — individual actions (open, click, type, etc.) controlled step-by-step by the LLM |
| `browser_agent` | `src/tools/browser_agent.py` | **Autonomous** — give it a plain-English task and it plans and executes browser actions on its own |

---

## Installation

browser-use is an optional dependency:

```bash
pip install browser-use
```

Or install with the browser extra:

```bash
pip install zwischenzug[browser]
```

Chromium and its system libraries are also required. In GitHub Codespaces or Docker, the devcontainer handles this automatically. Otherwise:

```bash
python -m playwright install chromium
python -m playwright install-deps chromium
```

---

## Tool: `browser_agent` (Autonomous)

Give the agent a high-level task in plain English. It autonomously navigates websites, clicks buttons, fills forms, scrolls, takes screenshots, and extracts information using its own internal LLM.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `task` | string | Yes | — | Plain-English task for the browser agent |
| `max_steps` | int | No | 25 | Maximum number of browser actions |
| `headless` | bool | No | `false` | Run headless (no visible browser) |

### How It Works

1. A browser-use `Agent` is created with its own LLM (uses the same provider/model from your `.env`, or override with `BROWSER_AGENT_MODEL`)
2. The agent plans a sequence of browser actions to accomplish the task
3. Each step is logged with the action taken and the agent's reasoning
4. The browser runs non-headless by default so you can watch it work via VNC
5. Results include extracted content, visited URLs, action log, and final summary

### Examples

```
browser_agent(task="Go to google.com and search for OpenAI")
browser_agent(task="Go to github.com/anthropics and list the top repositories")
browser_agent(task="Fill out the contact form at example.com with test data")
browser_agent(task="Find the current price of Bitcoin on coinmarketcap.com", max_steps=10)
```

### Watching the Browser Live (VNC)

In GitHub Codespaces, you can watch the browser agent work in real time:

1. Start the VNC server:
   ```bash
   bash scripts/start-vnc.sh
   ```
2. Open port **6080** from the Codespaces Ports tab — this opens a noVNC web viewer
3. Run the browser agent — Chrome will open visibly and you can watch it navigate, click, type, etc.

The devcontainer is pre-configured with `desktop-lite` for VNC support and auto-forwards port 6080.

### Configuration

| Environment Variable | Description |
|---------------------|-------------|
| `BROWSER_AGENT_MODEL` | Override the LLM model used by the browser agent (e.g. `gemini-2.5-flash`) |
| `GOOGLE_API_KEY` / `GEMINI_API_KEY` | Required for Gemini models |

If `BROWSER_AGENT_MODEL` is not set, the browser agent uses your main `ZWISCHENZUG_MODEL`.

---

## Tool: `browser` (Low-Level)

The low-level browser tool exposes individual browser actions. The LLM decides what to do step by step — open a page, click a button, type text, etc. Use this when you need precise manual control.

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | Yes | Browser action (see below) |
| `url` | string | No | URL for `open` |
| `selector` | string | No | CSS selector or text for `click`/`type` |
| `text` | string | No | Text to type for `type` |
| `script` | string | No | JavaScript for `evaluate` |
| `direction` | string | No | `up` or `down` for `scroll` |
| `format` | string | No | `text` or `html` for `content` |

### Actions

| Action | Description |
|--------|-------------|
| `open` | Navigate to a URL |
| `click` | Click an element (CSS selector or text match) |
| `type` | Type text into an input field |
| `content` | Extract page content as text or HTML |
| `screenshot` | Save a screenshot to `.zwis/screenshots/` |
| `evaluate` | Run JavaScript on the page |
| `scroll` | Scroll the page up or down |
| `close` | Close the browser session |

### Session Management

Browser sessions are scoped to the agent session. A browser is created automatically on first use and persists until explicitly closed or the session ends. Pages maintain state between actions (cookies, local storage, etc.).

### Example

```
1. browser(action="open", url="https://example.com")
2. browser(action="type", selector="#search", text="zwischenzug")
3. browser(action="click", selector="button[type=submit]")
4. browser(action="content")  → returns page text
5. browser(action="screenshot")  → saves to .zwis/screenshots/
6. browser(action="close")
```

---

## When to Use Which

| Scenario | Tool |
|----------|------|
| "Search Google for X and summarize the results" | `browser_agent` |
| "Fill out this form and submit it" | `browser_agent` |
| "Click the third link on this specific page" | `browser` |
| "Run this JavaScript snippet on a page" | `browser` |
| Complex multi-page autonomous workflows | `browser_agent` |
| Precise, repeatable automation scripts | `browser` |

---

## Container / Codespace Notes

Both tools pass `--no-sandbox`, `--disable-dev-shm-usage`, and `--disable-gpu` flags to Chromium automatically. This is required for running inside Docker containers, GitHub Codespaces, and CI environments.
