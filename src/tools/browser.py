"""
Browser automation tool — using the browser-use library.

Provides web browsing capabilities: navigate, click, type, screenshot,
extract content. Uses https://browser-use.com/ as the backend.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from . import Tool, ToolContext, ToolOutput

logger = logging.getLogger("zwischenzug.tools.browser")

MAX_CONTENT = 50_000
POST_ACTION_DELAY = 0.5


def _browser_use_available() -> bool:
    """Check if browser-use is installed."""
    try:
        import browser_use  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Session-scoped browser instances
# ---------------------------------------------------------------------------

_BROWSER_SESSIONS: dict[str, Any] = {}


class BrowserTool(Tool):
    """Automate browser interactions using browser-use."""

    @property
    def name(self) -> str:
        return "browser"

    @property
    def description(self) -> str:
        return (
            "Control a headless browser for web automation. Actions:\n"
            "- 'open': Open a URL in the browser\n"
            "- 'click': Click an element by CSS selector or text\n"
            "- 'type': Type text into an input field\n"
            "- 'content': Extract page content as text/markdown\n"
            "- 'screenshot': Take a screenshot (returns path)\n"
            "- 'evaluate': Run JavaScript on the page\n"
            "- 'scroll': Scroll the page (up/down)\n"
            "- 'close': Close the browser session\n"
            "Requires: pip install browser-use"
        )

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": (
                        "Browser action: 'open', 'click', 'type', "
                        "'content', 'screenshot', 'evaluate', 'scroll', 'close'."
                    ),
                },
                "url": {
                    "type": "string",
                    "description": "URL for 'open' action.",
                },
                "selector": {
                    "type": "string",
                    "description": (
                        "CSS selector for 'click'/'type' actions. "
                        "Or text content to find the element."
                    ),
                },
                "text": {
                    "type": "string",
                    "description": "Text to type for 'type' action.",
                },
                "script": {
                    "type": "string",
                    "description": "JavaScript code for 'evaluate' action.",
                },
                "direction": {
                    "type": "string",
                    "description": "'up' or 'down' for 'scroll' action.",
                },
                "format": {
                    "type": "string",
                    "description": "Output format for 'content': 'text' or 'html' (default 'text').",
                },
            },
            "required": ["action"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        action = kwargs.get("action", "").strip().lower()

        if not _browser_use_available():
            return ToolOutput.error(
                "browser-use is not installed. Install it with:\n"
                "  pip install browser-use\n"
                "See https://browser-use.com/ for setup instructions."
            )

        if action == "open":
            return await self._open(ctx, kwargs)
        elif action == "click":
            return await self._click(ctx, kwargs)
        elif action == "type":
            return await self._type(ctx, kwargs)
        elif action == "content":
            return await self._content(ctx, kwargs)
        elif action == "screenshot":
            return await self._screenshot(ctx, kwargs)
        elif action == "evaluate":
            return await self._evaluate(ctx, kwargs)
        elif action == "scroll":
            return await self._scroll(ctx, kwargs)
        elif action == "close":
            return await self._close(ctx)
        else:
            return ToolOutput.error(
                f"Unknown browser action: {action!r}. "
                "Use: open, click, type, content, screenshot, evaluate, scroll, close."
            )

    async def _get_or_create_browser(self, ctx: ToolContext) -> Any:
        """Get or create a browser session (browser-use >= 0.12)."""
        import glob as _glob
        from browser_use import BrowserSession

        if ctx.session_id not in _BROWSER_SESSIONS:
            # Check for Playwright Chromium binary before attempting to launch.
            pw_root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
            roots = [pw_root] if pw_root else []
            roots.append(os.path.expanduser("~/.cache/ms-playwright"))
            found = any(
                _glob.glob(os.path.join(r, "chromium-*/chrome-linux*/chrome"))
                for r in roots if r
            )
            if not found:
                raise RuntimeError(
                    "Playwright Chromium binary not found.\n\n"
                    "Run once to set everything up:\n"
                    "  zwis setup-browser"
                )
            session = BrowserSession(
                headless=True,
                # Required for running inside containers (Docker, Codespaces, CI).
                chromium_sandbox=False,
                args=[
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-first-run",
                ],
            )
            await session.start()
            _BROWSER_SESSIONS[ctx.session_id] = {"session": session}

        return _BROWSER_SESSIONS[ctx.session_id]

    async def _get_current_page(self, session: Any) -> Any:
        page = await session.get_current_page()
        if page is None:
            raise RuntimeError("No active page in browser session.")
        return page

    def _normalize_script(self, script: str) -> str:
        script = script.strip()
        if script.startswith("(") and "=>" in script:
            return script
        if "\n" in script or ";" in script or script.startswith("return "):
            return f"() => {{ {script} }}"
        return f"() => ({script})"

    async def _find_element_by_css(self, page: Any, selector: str) -> Any | None:
        try:
            elements = await page.get_elements_by_css_selector(selector)
        except Exception:
            return None
        return elements[0] if elements else None

    async def _click_by_text(self, page: Any, text: str) -> bool:
        result = await page.evaluate(
            """
            (targetText) => {
                const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const wanted = normalize(targetText);
                if (!wanted) return false;

                const candidates = Array.from(
                    document.querySelectorAll(
                        'button, a, input[type="button"], input[type="submit"], [role="button"], [onclick]'
                    )
                );

                const score = (element) => {
                    const values = [
                        element.innerText,
                        element.textContent,
                        element.getAttribute('aria-label'),
                        element.getAttribute('title'),
                        element.getAttribute('value'),
                    ].map(normalize).filter(Boolean);

                    let best = 0;
                    for (const value of values) {
                        if (value === wanted) best = Math.max(best, 3);
                        else if (value.includes(wanted)) best = Math.max(best, 2);
                        else if (wanted.includes(value)) best = Math.max(best, 1);
                    }
                    return best;
                };

                let match = null;
                let best = 0;
                for (const element of candidates) {
                    const current = score(element);
                    if (current > best) {
                        best = current;
                        match = element;
                    }
                }

                if (!match) return false;
                match.scrollIntoView({ block: 'center', inline: 'center' });
                match.click();
                return true;
            }
            """,
            text,
        )
        return str(result).strip().lower() == "true"

    async def _fill_by_text(self, page: Any, selector: str, text: str) -> bool:
        result = await page.evaluate(
            """
            (targetText, value) => {
                const normalize = (input) => (input || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const wanted = normalize(targetText);
                if (!wanted) return false;

                const controls = Array.from(
                    document.querySelectorAll('input, textarea, [contenteditable="true"], [contenteditable=""]')
                );

                const labels = new Map();
                for (const label of Array.from(document.querySelectorAll('label'))) {
                    const labelText = normalize(label.innerText || label.textContent);
                    if (!labelText) continue;
                    const htmlFor = label.getAttribute('for');
                    if (htmlFor) {
                        const linked = document.getElementById(htmlFor);
                        if (linked) labels.set(linked, labelText);
                    }
                    const nested = label.querySelector('input, textarea, [contenteditable="true"], [contenteditable=""]');
                    if (nested) labels.set(nested, labelText);
                }

                const score = (element) => {
                    const values = [
                        labels.get(element),
                        element.getAttribute('placeholder'),
                        element.getAttribute('aria-label'),
                        element.getAttribute('name'),
                        element.id,
                    ].map(normalize).filter(Boolean);

                    let best = 0;
                    for (const candidate of values) {
                        if (candidate === wanted) best = Math.max(best, 3);
                        else if (candidate.includes(wanted)) best = Math.max(best, 2);
                        else if (wanted.includes(candidate)) best = Math.max(best, 1);
                    }
                    return best;
                };

                let match = null;
                let best = 0;
                for (const element of controls) {
                    const current = score(element);
                    if (current > best) {
                        best = current;
                        match = element;
                    }
                }

                if (!match) return false;
                match.scrollIntoView({ block: 'center', inline: 'center' });
                match.focus();

                if (match.isContentEditable) {
                    match.textContent = value;
                } else {
                    match.value = value;
                }

                match.dispatchEvent(new Event('input', { bubbles: true }));
                match.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            }
            """,
            selector,
            text,
        )
        return str(result).strip().lower() == "true"

    async def _open(self, ctx: ToolContext, kwargs: dict) -> ToolOutput:
        url = kwargs.get("url", "").strip()
        if not url:
            return ToolOutput.error("'open' requires a 'url'.")

        try:
            state = await self._get_or_create_browser(ctx)
            session = state["session"]
            await session.navigate_to(url)
            await asyncio.sleep(POST_ACTION_DELAY)
            page = await self._get_current_page(session)
            title = await page.get_title()
            return ToolOutput.success(f"Opened: {url}\nTitle: {title}")
        except Exception as exc:
            return ToolOutput.error(f"Failed to open {url}: {exc}")

    async def _click(self, ctx: ToolContext, kwargs: dict) -> ToolOutput:
        selector = kwargs.get("selector", "").strip()
        if not selector:
            return ToolOutput.error("'click' requires a 'selector'.")

        try:
            state = await self._get_or_create_browser(ctx)
            page = await self._get_current_page(state["session"])

            element = await self._find_element_by_css(page, selector)
            if element is not None:
                await element.click()
            elif not await self._click_by_text(page, selector):
                return ToolOutput.error(f"Click failed for '{selector}': no matching element found.")

            await asyncio.sleep(POST_ACTION_DELAY)
            return ToolOutput.success(f"Clicked: {selector}")
        except Exception as exc:
            return ToolOutput.error(f"Click failed for '{selector}': {exc}")

    async def _type(self, ctx: ToolContext, kwargs: dict) -> ToolOutput:
        selector = kwargs.get("selector", "").strip()
        text = kwargs.get("text", "")
        if not selector:
            return ToolOutput.error("'type' requires a 'selector'.")

        try:
            state = await self._get_or_create_browser(ctx)
            page = await self._get_current_page(state["session"])

            element = await self._find_element_by_css(page, selector)
            if element is not None:
                await element.fill(text)
            elif not await self._fill_by_text(page, selector, text):
                return ToolOutput.error(f"Type failed for '{selector}': no matching input found.")
            return ToolOutput.success(f"Typed into {selector}: {text[:50]}...")
        except Exception as exc:
            return ToolOutput.error(f"Type failed for '{selector}': {exc}")

    async def _content(self, ctx: ToolContext, kwargs: dict) -> ToolOutput:
        fmt = kwargs.get("format", "text").strip().lower()

        try:
            state = await self._get_or_create_browser(ctx)
            page = await self._get_current_page(state["session"])

            if fmt == "html":
                content = await page.evaluate(
                    "() => document.documentElement ? document.documentElement.outerHTML : ''"
                )
            else:
                content = await page.evaluate(
                    "() => document.body ? document.body.innerText : document.documentElement.innerText"
                )

            if len(content) > MAX_CONTENT:
                content = content[:MAX_CONTENT] + "\n\n[content truncated]"

            return ToolOutput.success(content)
        except Exception as exc:
            return ToolOutput.error(f"Failed to extract content: {exc}")

    async def _screenshot(self, ctx: ToolContext, kwargs: dict) -> ToolOutput:
        import os

        try:
            state = await self._get_or_create_browser(ctx)
            session = state["session"]

            path = os.path.join(ctx.cwd, ".zwis", "screenshots")
            os.makedirs(path, exist_ok=True)
            filepath = os.path.join(path, f"screenshot_{id(session)}.png")

            await session.take_screenshot(path=filepath, full_page=True)
            return ToolOutput.success(f"Screenshot saved: {filepath}")
        except Exception as exc:
            return ToolOutput.error(f"Screenshot failed: {exc}")

    async def _evaluate(self, ctx: ToolContext, kwargs: dict) -> ToolOutput:
        script = kwargs.get("script", "").strip()
        if not script:
            return ToolOutput.error("'evaluate' requires a 'script'.")

        try:
            state = await self._get_or_create_browser(ctx)
            page = await self._get_current_page(state["session"])
            result = await page.evaluate(self._normalize_script(script))

            if isinstance(result, (dict, list)):
                output = json.dumps(result, indent=2, default=str)
            else:
                output = str(result)

            if len(output) > MAX_CONTENT:
                output = output[:MAX_CONTENT] + "\n\n[output truncated]"

            return ToolOutput.success(output)
        except Exception as exc:
            return ToolOutput.error(f"Evaluate failed: {exc}")

    async def _scroll(self, ctx: ToolContext, kwargs: dict) -> ToolOutput:
        direction = kwargs.get("direction", "down").strip().lower()

        try:
            state = await self._get_or_create_browser(ctx)
            page = await self._get_current_page(state["session"])

            if direction == "up":
                await page.evaluate("() => { window.scrollBy(0, -window.innerHeight); return window.scrollY; }")
            else:
                await page.evaluate("() => { window.scrollBy(0, window.innerHeight); return window.scrollY; }")

            return ToolOutput.success(f"Scrolled {direction}.")
        except Exception as exc:
            return ToolOutput.error(f"Scroll failed: {exc}")

    async def _close(self, ctx: ToolContext) -> ToolOutput:
        state = _BROWSER_SESSIONS.pop(ctx.session_id, None)
        if state is None:
            return ToolOutput.success("No browser session to close.")

        try:
            await state["session"].stop()
        except Exception:
            pass

        return ToolOutput.success("Browser session closed.")