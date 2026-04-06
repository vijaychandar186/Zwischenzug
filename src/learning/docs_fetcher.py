"""
Framework documentation fetcher.

Fetches the most relevant doc pages for detected frameworks and saves
them as compressed Markdown summaries to .zwis/docs/.

These files give the LLM accurate, up-to-date API knowledge when working
with libraries present in the repository.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from .frameworks import FrameworkInfo

logger = logging.getLogger("zwischenzug.learning.docs_fetcher")

# Max characters to store per doc page (to keep context manageable)
_MAX_DOC_CHARS = 8_000


class DocsFetcher:
    """Fetch and cache framework documentation."""

    def __init__(self, cwd: str) -> None:
        self._cwd = Path(cwd)
        self._docs_dir = self._cwd / ".zwis" / "docs"

    def fetch_all(
        self,
        frameworks: list[FrameworkInfo],
        force: bool = False,
    ) -> list[str]:
        """
        Fetch docs for each framework and write to .zwis/docs/<name>.md.

        Returns a list of created/updated file paths.
        Skips frameworks whose doc file already exists (unless force=True).
        """
        self._docs_dir.mkdir(parents=True, exist_ok=True)
        created: list[str] = []

        for fw in frameworks:
            out_path = self._docs_dir / f"{fw.name}.md"
            if out_path.exists() and not force:
                logger.debug("Skipping %s docs (already cached)", fw.name)
                continue

            logger.info("Fetching docs for %s …", fw.display)
            content = self._fetch_framework(fw)
            if content:
                out_path.write_text(content, encoding="utf-8")
                created.append(str(out_path))
                logger.info("  Saved %s (%d chars)", out_path.name, len(content))
            else:
                logger.warning("  Could not fetch docs for %s", fw.display)

        return created

    # ------------------------------------------------------------------
    # Per-framework fetch
    # ------------------------------------------------------------------

    def _fetch_framework(self, fw: FrameworkInfo) -> str:
        """Fetch main doc page for a framework and return compressed markdown."""
        try:
            import httpx
        except ImportError:
            logger.warning("httpx not available — cannot fetch docs")
            return ""

        # Build a short, compressed summary from the main page
        summary_parts: list[str] = [
            f"# {fw.display} Documentation Summary\n",
            f"Source: {fw.doc_url}\n",
        ]

        url = fw.doc_url
        text = self._fetch_url(url)
        if text:
            compressed = _compress_to_markdown(text, fw.display)
            summary_parts.append(compressed)

        return "\n".join(summary_parts)

    def _fetch_url(self, url: str) -> str:
        """Fetch URL and return text content, or empty string on failure."""
        try:
            import httpx
            headers = {"User-Agent": "zwischenzug-agent/1.0"}
            resp = httpx.get(url, follow_redirects=True, timeout=10.0, headers=headers)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            logger.debug("Fetch failed for %s: %s", url, exc)
            return ""


# ---------------------------------------------------------------------------
# Compression helpers
# ---------------------------------------------------------------------------

def _compress_to_markdown(html_or_text: str, framework_name: str) -> str:
    """
    Convert HTML or plain text to a compressed Markdown summary.

    Tries html2text if available, otherwise applies light regex stripping.
    Caps output at _MAX_DOC_CHARS.
    """
    text = _html_to_text(html_or_text)

    # Remove excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Remove navigation/footer boilerplate patterns
    text = re.sub(r"(?im)^(skip to|navigation|table of contents|on this page).*$", "", text)
    text = re.sub(r"(?im)^\s*(previous|next|edit this page|view source)\s*$", "", text)

    # Cap length
    if len(text) > _MAX_DOC_CHARS:
        text = text[:_MAX_DOC_CHARS] + "\n\n… [truncated for context efficiency]"

    return text.strip()


def _html_to_text(html: str) -> str:
    """Convert HTML to plain text using html2text if available."""
    try:
        import html2text
        h = html2text.HTML2Text()
        h.ignore_links = True
        h.ignore_images = True
        h.body_width = 0  # no line wrapping
        return h.handle(html)
    except ImportError:
        pass

    # Fallback: simple regex stripping
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&#?\w+;", "", text)
    return text
