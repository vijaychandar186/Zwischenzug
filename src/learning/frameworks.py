"""
Framework detection — identifies which libraries/frameworks a repository uses.

Strategy (in order):
  1. Parse pyproject.toml / setup.cfg / requirements*.txt for declared deps
  2. Check importlib.metadata for actually-installed packages
  3. Cross-reference against KNOWN_FRAMEWORKS
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FrameworkInfo:
    name: str          # canonical name, e.g. "fastapi"
    display: str       # human-readable, e.g. "FastAPI"
    version: str       # installed version or "" if unknown
    doc_url: str       # primary docs URL
    doc_sections: list[str]   # key doc sections to fetch


# ---------------------------------------------------------------------------
# Framework catalogue
# ---------------------------------------------------------------------------

KNOWN_FRAMEWORKS: dict[str, FrameworkInfo] = {
    "fastapi": FrameworkInfo(
        name="fastapi", display="FastAPI", version="",
        doc_url="https://fastapi.tiangolo.com/",
        doc_sections=["tutorial", "advanced"],
    ),
    "flask": FrameworkInfo(
        name="flask", display="Flask", version="",
        doc_url="https://flask.palletsprojects.com/en/stable/",
        doc_sections=["quickstart", "tutorial"],
    ),
    "django": FrameworkInfo(
        name="django", display="Django", version="",
        doc_url="https://docs.djangoproject.com/en/stable/",
        doc_sections=["intro", "topics"],
    ),
    "sqlalchemy": FrameworkInfo(
        name="sqlalchemy", display="SQLAlchemy", version="",
        doc_url="https://docs.sqlalchemy.org/en/20/",
        doc_sections=["orm", "core"],
    ),
    "alembic": FrameworkInfo(
        name="alembic", display="Alembic", version="",
        doc_url="https://alembic.sqlalchemy.org/en/latest/",
        doc_sections=["tutorial"],
    ),
    "pydantic": FrameworkInfo(
        name="pydantic", display="Pydantic", version="",
        doc_url="https://docs.pydantic.dev/latest/",
        doc_sections=["concepts", "api"],
    ),
    "langchain": FrameworkInfo(
        name="langchain", display="LangChain", version="",
        doc_url="https://python.langchain.com/docs/introduction/",
        doc_sections=["how_to", "concepts"],
    ),
    "langchain-litellm": FrameworkInfo(
        name="langchain-litellm", display="LangChain-LiteLLM", version="",
        doc_url="https://python.langchain.com/docs/integrations/chat/litellm/",
        doc_sections=[],
    ),
    "litellm": FrameworkInfo(
        name="litellm", display="LiteLLM", version="",
        doc_url="https://docs.litellm.ai/",
        doc_sections=[],
    ),
    "httpx": FrameworkInfo(
        name="httpx", display="HTTPX", version="",
        doc_url="https://www.python-httpx.org/",
        doc_sections=["quickstart", "async"],
    ),
    "pytest": FrameworkInfo(
        name="pytest", display="Pytest", version="",
        doc_url="https://docs.pytest.org/en/stable/",
        doc_sections=["how-to", "reference"],
    ),
    "click": FrameworkInfo(
        name="click", display="Click", version="",
        doc_url="https://click.palletsprojects.com/en/stable/",
        doc_sections=["quickstart", "commands"],
    ),
    "typer": FrameworkInfo(
        name="typer", display="Typer", version="",
        doc_url="https://typer.tiangolo.com/",
        doc_sections=["tutorial"],
    ),
    "rich": FrameworkInfo(
        name="rich", display="Rich", version="",
        doc_url="https://rich.readthedocs.io/en/stable/",
        doc_sections=["introduction"],
    ),
    "celery": FrameworkInfo(
        name="celery", display="Celery", version="",
        doc_url="https://docs.celeryq.dev/en/stable/",
        doc_sections=["getting-started"],
    ),
    "redis": FrameworkInfo(
        name="redis", display="Redis-py", version="",
        doc_url="https://redis-py.readthedocs.io/en/stable/",
        doc_sections=[],
    ),
    "pymongo": FrameworkInfo(
        name="pymongo", display="PyMongo", version="",
        doc_url="https://pymongo.readthedocs.io/en/stable/",
        doc_sections=["tutorial"],
    ),
    "aiohttp": FrameworkInfo(
        name="aiohttp", display="aiohttp", version="",
        doc_url="https://docs.aiohttp.org/en/stable/",
        doc_sections=["client"],
    ),
    "anthropic": FrameworkInfo(
        name="anthropic", display="Anthropic SDK", version="",
        doc_url="https://docs.anthropic.com/en/api/getting-started",
        doc_sections=[],
    ),
    "openai": FrameworkInfo(
        name="openai", display="OpenAI SDK", version="",
        doc_url="https://platform.openai.com/docs/overview",
        doc_sections=[],
    ),
}

# Map import module names → canonical package name
_IMPORT_TO_PACKAGE: dict[str, str] = {
    "fastapi": "fastapi",
    "flask": "flask",
    "django": "django",
    "sqlalchemy": "sqlalchemy",
    "alembic": "alembic",
    "pydantic": "pydantic",
    "langchain": "langchain",
    "langchain_litellm": "langchain-litellm",
    "litellm": "litellm",
    "httpx": "httpx",
    "pytest": "pytest",
    "click": "click",
    "typer": "typer",
    "rich": "rich",
    "celery": "celery",
    "redis": "redis",
    "pymongo": "pymongo",
    "aiohttp": "aiohttp",
    "anthropic": "anthropic",
    "openai": "openai",
}


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class FrameworkDetector:
    """Detect frameworks used in a Python repository."""

    def __init__(self, cwd: str) -> None:
        self._cwd = Path(cwd)

    def detect(self) -> list[FrameworkInfo]:
        """
        Return FrameworkInfo objects for all detected frameworks,
        with installed version filled in where available.
        """
        names: set[str] = set()
        names.update(self._from_pyproject())
        names.update(self._from_requirements())

        result: list[FrameworkInfo] = []
        for pkg_name in sorted(names):
            info = KNOWN_FRAMEWORKS.get(pkg_name)
            if info is None:
                continue
            version = self._installed_version(info.name)
            result.append(FrameworkInfo(
                name=info.name,
                display=info.display,
                version=version,
                doc_url=info.doc_url,
                doc_sections=info.doc_sections,
            ))
        return result

    # ------------------------------------------------------------------
    # Source readers
    # ------------------------------------------------------------------

    def _from_pyproject(self) -> set[str]:
        """Parse pyproject.toml for [project] dependencies."""
        found: set[str] = set()
        p = self._cwd / "pyproject.toml"
        if not p.exists():
            return found

        text = p.read_text(encoding="utf-8", errors="replace")
        # Extract dependency names with a simple regex (handles PEP 508 specifiers)
        in_deps = False
        for line in text.splitlines():
            stripped = line.strip()
            if re.match(r"\[project\]", stripped) or re.match(r"dependencies\s*=", stripped):
                in_deps = True
            if in_deps and stripped.startswith('"') or (in_deps and stripped.startswith("'")):
                match = re.match(r"""['"]([\w][\w\-.]*)""", stripped)
                if match:
                    pkg = match.group(1).lower().replace("_", "-")
                    if pkg in KNOWN_FRAMEWORKS:
                        found.add(pkg)
            # Also catch bare package names
            if in_deps:
                match = re.match(r"""([\w][\w\-.]+)\s*[><=!]""", stripped)
                if match:
                    pkg = match.group(1).lower().replace("_", "-")
                    if pkg in KNOWN_FRAMEWORKS:
                        found.add(pkg)
        return found

    def _from_requirements(self) -> set[str]:
        """Scan requirements*.txt files."""
        found: set[str] = set()
        for req_file in self._cwd.glob("requirements*.txt"):
            try:
                for line in req_file.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    match = re.match(r"([\w][\w\-.]+)", line)
                    if match:
                        pkg = match.group(1).lower().replace("_", "-")
                        if pkg in KNOWN_FRAMEWORKS:
                            found.add(pkg)
            except OSError:
                pass
        return found

    # ------------------------------------------------------------------
    # Version query
    # ------------------------------------------------------------------

    @staticmethod
    def _installed_version(package_name: str) -> str:
        """Return the installed version string, or '' if not installed."""
        try:
            from importlib.metadata import version, PackageNotFoundError
            return version(package_name)
        except Exception:
            return ""


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def detect_frameworks(cwd: str) -> list[FrameworkInfo]:
    """One-liner helper."""
    return FrameworkDetector(cwd).detect()
