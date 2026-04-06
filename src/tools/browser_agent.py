"""
Browser Agent tool — autonomous browser automation via browser-use Agent.

Unlike the low-level `browser` tool (where the LLM manually issues open/click/type),
this tool gives a high-level *task* to browser-use's Agent, which autonomously plans
and executes browser actions (navigation, clicks, typing, scrolling, screenshots, etc.)
using its own internal LLM.

The browser runs non-headless by default so the user can watch it live via VNC/noVNC
in environments like GitHub Codespaces.

A single persistent Chromium process is launched on first use and kept alive forever
(until explicit "close" command). browser-use attaches to it via CDP each run, so the
browser window is always visible in VNC before and after tasks complete.
"""
from __future__ import annotations

import asyncio
import glob
import logging
import os
import subprocess
import time
import urllib.request
from typing import Any

from . import Tool, ToolContext, ToolOutput

logger = logging.getLogger("zwischenzug.tools.browser_agent")

# The single persistent Chromium subprocess (module-level singleton).
_CHROMIUM_PROC: subprocess.Popen | None = None
_CDP_PORT = 9222
_CDP_URL = f"http://localhost:{_CDP_PORT}"


def _browser_use_available() -> bool:
    try:
        import browser_use  # noqa: F401
        return True
    except ImportError:
        return False


def _chromium_binary() -> str:
    """Find the Playwright-installed Chromium binary."""
    import shutil
    for candidate in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        path = shutil.which(candidate)
        if path:
            return path
    # Check PLAYWRIGHT_BROWSERS_PATH env var first (e.g. Docker image sets /ms-playwright)
    pw_root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    search_roots = []
    if pw_root:
        search_roots.append(pw_root)
    search_roots.append(os.path.expanduser("~/.cache/ms-playwright"))
    for root in search_roots:
        matches = glob.glob(os.path.join(root, "chromium-*/chrome-linux*/chrome"))
        if matches:
            return matches[0]
    raise FileNotFoundError("Could not find a Chromium binary.")


def _ensure_playwright_browser() -> None:
    """Raise with a helpful message if the Playwright Chromium binary is missing."""
    try:
        _chromium_binary()
    except FileNotFoundError:
        raise RuntimeError(
            "Playwright Chromium binary not found.\n\n"
            "Run once to set everything up:\n"
            "  zwis setup-browser\n\n"
            "Or manually:\n"
            "  playwright install chromium"
        )


def _ensure_chromium_running(display: str | None) -> None:
    """Start the persistent Chromium process if it is not already running.

    When *display* is None no X display is available; Chromium is launched with
    ``--headless=new`` so it still serves the CDP port without needing a display.
    """
    global _CHROMIUM_PROC

    # Check if existing process is still alive
    if _CHROMIUM_PROC is not None and _CHROMIUM_PROC.poll() is None:
        return  # already running

    # Check if a Chromium is already listening on the CDP port
    try:
        urllib.request.urlopen(f"{_CDP_URL}/json/version", timeout=1)
        logger.info("Chromium already running at %s — reusing it", _CDP_URL)
        return
    except Exception:
        pass

    binary = _chromium_binary()
    env = {**os.environ}
    if display:
        env["DISPLAY"] = display

    cmd = [
        binary,
        f"--remote-debugging-port={_CDP_PORT}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-extensions",
        "--no-sandbox",
        "--disable-infobars",
        "--window-size=1280,800",
        "--window-position=0,0",
        "about:blank",
    ]
    if not display:
        cmd.insert(1, "--headless=new")
        logger.info("No display available — launching Chromium in headless mode")

    logger.info("Launching persistent Chromium: %s", " ".join(cmd))
    _CHROMIUM_PROC = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    # Give Chromium a moment to start up and open the debugging port
    for _ in range(20):
        time.sleep(0.3)
        try:
            urllib.request.urlopen(f"{_CDP_URL}/json/version", timeout=1)
            logger.info("Chromium CDP ready at %s", _CDP_URL)
            return
        except Exception:
            pass
    raise RuntimeError("Chromium did not start in time — CDP port not responding")


def _auto_start_chromium() -> None:
    """Launch Chromium at import time so VNC always shows a browser window."""
    display = os.environ.get("DISPLAY", "")
    if not display:
        for proc in ("Xtigervnc", "Xvfb"):
            try:
                ps = subprocess.check_output(["pgrep", "-a", proc], text=True, stderr=subprocess.DEVNULL)
                for line in ps.strip().splitlines():
                    for token in line.split():
                        if token.startswith(":"):
                            display = token
                            os.environ["DISPLAY"] = display
                            break
                if display:
                    break
            except Exception:
                pass
    if not display:
        return
    try:
        _chromium_binary()
    except FileNotFoundError:
        return
    _ensure_chromium_running(display)


# Auto-start on import so the browser is visible in VNC from the moment zwis launches.
try:
    _auto_start_chromium()
except Exception as _e:
    logger.debug("Auto-start Chromium skipped: %s", _e)


def _build_llm(provider: str | None = None, model: str | None = None) -> Any:
    """Build a browser-use native LLM from env/config.

    browser-use 0.11+ has its own LLM abstraction (BaseChatModel) with its own
    message types and ainvoke protocol — LangChain LLMs are not compatible.
    We instantiate browser-use's own provider classes directly.

    Supported providers: gemini/google, openai, anthropic, groq, ollama,
                         azure, openrouter, deepseek, mistral, cerebras.
    """
    # Determine provider + model from env overrides or passed args.
    ba_model = os.getenv("BROWSER_AGENT_MODEL", "").strip()
    if ba_model:
        # BROWSER_AGENT_MODEL can be "provider/model" or just "model"
        if "/" in ba_model and not provider:
            provider, model = ba_model.split("/", 1)
        else:
            model = ba_model

    if not provider or not model:
        provider = provider or os.getenv("ZWISCHENZUG_PROVIDER", "").strip().lower()
        model = model or os.getenv("ZWISCHENZUG_MODEL", "").strip()

    if not model:
        raise ValueError(
            "No LLM configured for browser agent. Set BROWSER_AGENT_MODEL or "
            "ZWISCHENZUG_MODEL in your .env."
        )

    # Strip provider prefix from model string (e.g. "gemini/gemini-2.0-flash" → "gemini-2.0-flash")
    if provider and model.startswith(f"{provider}/"):
        model = model[len(provider) + 1:]
    elif "/" in model and not provider:
        provider, model = model.split("/", 1)

    provider = (provider or "").lower()

    # Resolve API key using Zwischenzug convention: <PROVIDER>_API_KEY
    api_key = os.getenv(f"{provider.upper()}_API_KEY") or None

    if provider in ("gemini", "google"):
        from browser_use.llm.google.chat import ChatGoogle
        return ChatGoogle(
            model=model,
            api_key=api_key or os.getenv("GOOGLE_API_KEY") or None,
        )
    elif provider == "openai":
        from browser_use.llm.openai.chat import ChatOpenAI
        return ChatOpenAI(model=model, api_key=api_key)
    elif provider == "anthropic":
        from browser_use.llm.anthropic.chat import ChatAnthropic
        return ChatAnthropic(model=model, api_key=api_key)
    elif provider == "groq":
        from browser_use.llm.groq.chat import ChatGroq
        return ChatGroq(model=model, api_key=api_key)
    elif provider == "ollama":
        from browser_use.llm.ollama.chat import ChatOllama
        return ChatOllama(model=model)
    elif provider in ("azure", "azure_openai"):
        from browser_use.llm.azure.chat import ChatAzureOpenAI
        return ChatAzureOpenAI(model=model, api_key=api_key)
    elif provider == "openrouter":
        from browser_use.llm.openrouter.chat import ChatOpenRouter
        return ChatOpenRouter(model=model, api_key=api_key)
    elif provider == "deepseek":
        from browser_use.llm.deepseek.chat import ChatDeepSeek
        return ChatDeepSeek(model=model, api_key=api_key)
    elif provider == "mistral":
        from browser_use.llm.mistral.chat import ChatMistral
        return ChatMistral(model=model, api_key=api_key)
    elif provider == "cerebras":
        from browser_use.llm.cerebras.chat import ChatCerebras
        return ChatCerebras(model=model, api_key=api_key)
    else:
        raise ValueError(
            f"Unsupported provider '{provider}' for browser agent. "
            "Supported: gemini, openai, anthropic, groq, ollama, azure, "
            "openrouter, deepseek, mistral, cerebras."
        )


class BrowserAgentTool(Tool):
    """Give a high-level task to an autonomous browser agent."""

    @property
    def name(self) -> str:
        return "browser_agent"

    @property
    def description(self) -> str:
        return (
            "Autonomous browser agent. Give it a task in plain English and it will "
            "navigate websites, click buttons, fill forms, scroll, take screenshots, "
            "and extract information — all on its own.\n"
            "Examples:\n"
            "- 'Go to google.com and search for OpenAI'\n"
            "- 'Go to github.com/anthropics and list the top repositories'\n"
            "- 'Fill out the contact form at example.com with test data'\n"
            "The browser is visible via VNC (port 6080) so you can watch it work.\n"
            "Requires: pip install browser-use"
        )

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": (
                        "The task for the browser agent to accomplish, in plain English. "
                        "Be specific about what you want it to do and what information to extract. "
                        "Use 'close' to close the browser when done inspecting."
                    ),
                },
                "max_steps": {
                    "type": "integer",
                    "description": "Maximum number of browser actions (default 25).",
                },
                "headless": {
                    "type": "boolean",
                    "description": "Run headless (no visible browser). Default false — browser is visible via VNC.",
                },
                "keep_open": {
                    "type": "boolean",
                    "description": (
                        "Keep the browser open after the task finishes so you can inspect "
                        "the page via VNC. Default true. Set false to close immediately."
                    ),
                },
            },
            "required": ["task"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        task = kwargs.get("task", "").strip()

        if task.lower() == "close":
            return await self._close_browser(ctx)

        if not task:
            return ToolOutput.error("'browser_agent' requires a 'task'.")

        if not _browser_use_available():
            return ToolOutput.error(
                "browser-use is not installed. Install it with:\n"
                "  pip install browser-use\n"
                "See https://browser-use.com/ for setup instructions."
            )

        max_steps = int(kwargs.get("max_steps", 25))
        headless = kwargs.get("headless", False)
        keep_open = kwargs.get("keep_open", True)

        try:
            return await self._run_agent(ctx, task, max_steps, headless, keep_open)
        except Exception as exc:
            logger.exception("Browser agent failed")
            return ToolOutput.error(f"Browser agent failed: {exc}")

    async def _close_browser(self, ctx: ToolContext) -> ToolOutput:
        """Kill the persistent Chromium process."""
        global _CHROMIUM_PROC
        if _CHROMIUM_PROC is None or _CHROMIUM_PROC.poll() is not None:
            return ToolOutput.success("No browser running.")
        _CHROMIUM_PROC.terminate()
        try:
            _CHROMIUM_PROC.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _CHROMIUM_PROC.kill()
        _CHROMIUM_PROC = None
        return ToolOutput.success("Browser closed.")

    def _ensure_display(self) -> str | None:
        """Return a DISPLAY value, or None if no display is available.

        Priority:
          1. Xtigervnc / tigervncserver — this is what desktop-lite noVNC shows
          2. Existing DISPLAY env var (may be an Xvfb set by Docker CMD)
          3. Xvfb scan
          4. Start a new Xvfb as last resort
          5. None — caller should launch Chromium headless
        """
        # Always prefer tigervnc: it's the display connected to noVNC (port 6080).
        for proc in ("Xtigervnc", "tigervncserver"):
            try:
                ps = subprocess.check_output(
                    ["pgrep", "-a", proc], text=True, stderr=subprocess.DEVNULL
                )
                for line in ps.strip().splitlines():
                    for token in line.split():
                        if token.startswith(":"):
                            os.environ["DISPLAY"] = token
                            logger.info(
                                "Using DISPLAY=%s from %s (visible in noVNC)", token, proc
                            )
                            return token
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass

        # Fall back to whatever DISPLAY the process was started with.
        if os.environ.get("DISPLAY"):
            return os.environ["DISPLAY"]

        # Scan for any Xvfb.
        try:
            ps = subprocess.check_output(
                ["pgrep", "-a", "Xvfb"], text=True, stderr=subprocess.DEVNULL
            )
            for line in ps.strip().splitlines():
                for token in line.split():
                    if token.startswith(":"):
                        os.environ["DISPLAY"] = token
                        logger.info("Auto-detected DISPLAY=%s from Xvfb", token)
                        return token
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        # No display found — Chromium will run headless.
        # Install VNC packages with: zwis setup-browser
        logger.info("No display available — Chromium will run headless (no VNC)")
        return None

    async def _create_session(self) -> Any:
        """Attach to our persistent Chromium via CDP.

        Always uses CDP so we control exactly how Chromium was launched
        (headless=new when no display, headed when VNC is available).
        """
        from browser_use import BrowserSession
        return BrowserSession(cdp_url=_CDP_URL, highlight_elements=True)

    async def _run_agent(
        self, ctx: ToolContext, task: str, max_steps: int, headless: bool, keep_open: bool
    ) -> ToolOutput:
        from browser_use import Agent

        # Ensure Chromium binary exists before trying to launch it.
        try:
            _ensure_playwright_browser()
        except RuntimeError as exc:
            return ToolOutput.error(str(exc))

        # Find a display. None means no X server → launch Chromium with --headless=new.
        # Either way we use our own subprocess launcher so we control the flags.
        display = self._ensure_display()
        _ensure_chromium_running(display)

        # Disable browser-use telemetry to avoid LLM introspection issues.
        os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")

        # Build LLM for the browser agent.
        provider = os.getenv("ZWISCHENZUG_PROVIDER", "").strip().lower()
        model = os.getenv("ZWISCHENZUG_MODEL", "").strip()
        llm = _build_llm(provider, model)

        session = await self._create_session()

        steps_log: list[str] = []

        def on_step(state, output, step_num):
            action_names = []
            if hasattr(output, 'action') and output.action:
                for action in output.action if isinstance(output.action, list) else [output.action]:
                    name = getattr(action, 'name', None) or type(action).__name__
                    action_names.append(name)
            thought = ""
            if hasattr(output, 'current_state') and output.current_state:
                thought = getattr(output.current_state, 'thought', '') or ''
            summary = f"Step {step_num}: {', '.join(action_names) or 'thinking'}"
            if thought:
                summary += f" — {thought[:120]}"
            steps_log.append(summary)
            logger.info(summary)

        try:
            agent = Agent(
                task=task,
                llm=llm,
                browser_session=session,
                register_new_step_callback=on_step,
                max_actions_per_step=3,
                use_vision=True,
            )

            history = await agent.run(max_steps=max_steps)

            parts: list[str] = []
            parts.append(f"Task: {task}")
            parts.append(f"Steps: {history.number_of_steps()}")
            parts.append(f"Done: {history.is_done()}")

            if history.is_done() and history.final_result():
                parts.append(f"\nResult:\n{history.final_result()}")

            extracted = history.extracted_content()
            if extracted:
                content = "\n".join(str(e) for e in extracted)
                if content.strip():
                    parts.append(f"\nExtracted content:\n{content[:5000]}")

            if history.has_errors():
                errors = history.errors()
                parts.append(f"\nErrors: {errors[:500]}")

            if steps_log:
                parts.append("\nAction log:\n" + "\n".join(steps_log[-15:]))

            urls = history.urls()
            if urls:
                parts.append(f"\nVisited URLs: {', '.join(urls[:10])}")

            parts.append("\nBrowser remains open — check it via VNC (port 6080). "
                         "Use browser_agent(task='close') to shut it down.")
            return ToolOutput.success("\n".join(parts))

        finally:
            try:
                await session.stop()
            except Exception:
                pass
