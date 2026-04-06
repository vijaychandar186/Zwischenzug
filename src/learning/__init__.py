"""
LearningEngine — scans a repository and builds the knowledge graph.

Workflow:
  1. scan_files()         — find all Python files (respects ignore patterns)
  2. parse_files()        — PythonASTParser on each file
  3. build_graph()        — convert ParsedFiles → GraphNodes + GraphEdges
  4. track_references()   — record line-level references in the graph
  5. detect_frameworks()  — check pyproject.toml / requirements.txt
  6. generate_knowledge() — write .zwis/knowledge/*.md files
  7. fetch_docs()         — (optional) fetch framework doc pages
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..graph import GraphEngine
from ..graph.schema import EdgeType, GraphEdge, GraphNode, NodeType, Reference
from .ast_parser import ParsedFile, PythonASTParser
from .frameworks import FrameworkInfo, FrameworkDetector
from .knowledge import KnowledgeGenerator
from .reference import ReferenceTracker

logger = logging.getLogger("zwischenzug.learning")


# ---------------------------------------------------------------------------
# Result / progress
# ---------------------------------------------------------------------------

@dataclass
class LearningResult:
    total_files: int = 0
    parsed_files: int = 0
    skipped_files: int = 0
    total_nodes: int = 0
    total_edges: int = 0
    total_references: int = 0
    frameworks: list[str] = field(default_factory=list)
    knowledge_files: list[str] = field(default_factory=list)
    doc_files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


ProgressCallback = Callable[[str], None]


@dataclass
class _PendingEdge:
    """An edge whose target has not yet been resolved to a node ID.

    Accumulated during pass 1 (node creation) and resolved in pass 2
    once every file's symbols exist in the graph.
    """
    from_id: str
    raw_target: str       # unresolved symbol name (e.g. "run_agent", "self.execute")
    relationship: EdgeType
    source_file: str      # for reference tracking
    source_line: int
    source_symbol: str    # enclosing qualname


# ---------------------------------------------------------------------------
# Ignore patterns (directories/files to skip during scan)
# ---------------------------------------------------------------------------

_SKIP_DIRS = frozenset({
    ".git", ".zwis", ".venv", "venv", "env", ".env",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "node_modules", "dist", "build", ".build", "site-packages",
    ".tox", ".eggs", "*.egg-info",
})

_SKIP_FILE_PATTERNS = frozenset({
    "setup.py",       # usually trivial
    "conftest.py",    # pytest config — will still be scanned
})


# ---------------------------------------------------------------------------
# LearningEngine
# ---------------------------------------------------------------------------

class LearningEngine:
    """
    Orchestrates a full repository learning pass.

    Usage::

        engine = LearningEngine(cwd="/path/to/repo", graph=GraphEngine())
        result = await engine.learn(on_progress=print)
    """

    def __init__(self, cwd: str, graph: GraphEngine) -> None:
        self._cwd = Path(cwd).resolve()
        self._g = graph
        self._parser = PythonASTParser()
        self._tracker = ReferenceTracker(graph)
        self._pending: list[_PendingEdge] = []

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def learn(
        self,
        on_progress: ProgressCallback | None = None,
        fetch_docs: bool = False,
    ) -> LearningResult:
        """
        Full learning pass — scan, parse, build graph, generate knowledge.
        """
        result = LearningResult()
        t0 = time.time()

        def progress(msg: str) -> None:
            logger.info(msg)
            if on_progress:
                on_progress(msg)

        # Step 1 — scan
        progress("Scanning Python files …")
        py_files = self._scan_files()
        result.total_files = len(py_files)
        progress(f"Found {len(py_files)} Python files")

        # Step 2+3+4 — parse, build graph, track refs
        for i, fpath in enumerate(py_files, 1):
            rel = str(fpath.relative_to(self._cwd))
            if i % 10 == 0 or i == len(py_files):
                progress(f"Parsing [{i}/{len(py_files)}] {rel}")
            try:
                self._process_file(fpath)
                result.parsed_files += 1
            except Exception as exc:
                err = f"Error parsing {rel}: {exc}"
                logger.warning(err)
                result.errors.append(err)
                result.skipped_files += 1

        # Pass 2 — resolve cross-file edges now that all nodes exist
        progress("Resolving cross-file dependencies …")
        self._resolve_pending()

        stats = self._g.stats()
        result.total_nodes = stats.get("total_nodes", 0)
        result.total_edges = stats.get("total_edges", 0)
        result.total_references = stats.get("total_references", 0)

        progress(
            f"Graph built: {result.total_nodes} nodes, "
            f"{result.total_edges} edges, "
            f"{result.total_references} references"
        )

        # Step 5 — detect frameworks
        progress("Detecting frameworks …")
        fw_infos = FrameworkDetector(str(self._cwd)).detect()
        result.frameworks = [fw.name for fw in fw_infos]
        if fw_infos:
            progress(f"Detected: {', '.join(fw.display for fw in fw_infos)}")

        # Step 6 — generate knowledge files
        progress("Generating knowledge files …")
        gen = KnowledgeGenerator(str(self._cwd), self._g)
        result.knowledge_files = gen.generate_all(fw_infos)
        progress(f"Created {len(result.knowledge_files)} knowledge files in .zwis/knowledge/")

        # Step 7 — (optional) fetch docs
        if fetch_docs and fw_infos:
            progress("Fetching framework documentation …")
            from .docs_fetcher import DocsFetcher
            fetcher = DocsFetcher(str(self._cwd))
            result.doc_files = fetcher.fetch_all(fw_infos)
            progress(f"Fetched {len(result.doc_files)} doc files to .zwis/docs/")

        result.elapsed_seconds = time.time() - t0
        progress(f"Done in {result.elapsed_seconds:.1f}s")
        return result

    def update_file(self, file_path: str) -> None:
        """
        Incremental update: re-parse one file and refresh its graph nodes.

        Removes all previous data for the file, then re-processes it.
        Immediately resolves pending edges since all other nodes already exist.
        """
        path = Path(file_path)
        rel = str(path.relative_to(self._cwd)) if path.is_absolute() else file_path
        self._g.remove_file(rel)
        self._process_file(path if path.is_absolute() else self._cwd / path)
        self._resolve_pending()
        logger.info("Incremental update: %s", rel)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _scan_files(self) -> list[Path]:
        """Find all Python files in the repo, skipping ignored dirs."""
        results: list[Path] = []
        for path in self._cwd.rglob("*.py"):
            # Check if any parent dir matches skip list
            parts = path.relative_to(self._cwd).parts
            if any(p in _SKIP_DIRS or p.endswith(".egg-info") for p in parts):
                continue
            results.append(path)
        return sorted(results)

    def _file_mtimes(self, files: list[Path]) -> dict[str, float]:
        mtimes: dict[str, float] = {}
        for f in files:
            try:
                rel = str(f.relative_to(self._cwd))
                mtimes[rel] = f.stat().st_mtime
            except OSError:
                pass
        return mtimes

    def _process_file(self, path: Path) -> None:
        """Parse one Python file and add its content to the graph."""
        rel = str(path.relative_to(self._cwd))
        parsed = self._parser.parse_file(str(path))

        # --- File node ---
        file_node = GraphNode(
            id=rel,
            type=NodeType.FILE,
            name=path.name,
            file=rel,
            summary=parsed.docstring[:200] if parsed.docstring else "",
        )
        self._g.add_node(file_node)

        # --- Class nodes ---
        class_node_ids: dict[str, str] = {}  # class_name → node_id
        for cls in parsed.classes:
            node_id = f"{rel}::{cls.name}"
            cls_node = GraphNode(
                id=node_id,
                type=NodeType.CLASS,
                name=cls.name,
                file=rel,
                start_line=cls.start_line,
                end_line=cls.end_line,
                summary=cls.docstring[:200] if cls.docstring else "",
                metadata={"bases": cls.bases, "decorators": cls.decorators},
            )
            self._g.add_node(cls_node)
            class_node_ids[cls.name] = node_id

            # CONTAINS edge: file → class
            self._g.add_edge(GraphEdge(
                from_id=rel,
                to_id=node_id,
                relationship=EdgeType.CONTAINS,
            ))

            # EXTENDS edges for base classes (deferred to pass 2)
            for base in cls.bases:
                if not base or base in ("object", "ABC", "Enum"):
                    continue
                self._pending.append(_PendingEdge(
                    from_id=node_id,
                    raw_target=base,
                    relationship=EdgeType.EXTENDS,
                    source_file=rel,
                    source_line=cls.start_line,
                    source_symbol=cls.name,
                ))

        # --- Function + method nodes ---
        # First collect class methods via parse_all_methods
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return

        all_fns = self._parser.parse_all_methods(source, str(path))

        for fn in all_fns:
            is_method = fn.class_name is not None
            node_type = NodeType.METHOD if is_method else NodeType.FUNCTION

            if is_method:
                node_id = f"{rel}::{fn.class_name}::{fn.name}"
                parent_id = class_node_ids.get(fn.class_name, f"{rel}::{fn.class_name}")
            else:
                node_id = f"{rel}::{fn.name}"
                parent_id = rel

            fn_node = GraphNode(
                id=node_id,
                type=node_type,
                name=fn.name,
                file=rel,
                start_line=fn.start_line,
                end_line=fn.end_line,
                summary=fn.docstring[:200] if fn.docstring else "",
                metadata={
                    "is_async": fn.is_async,
                    "decorators": fn.decorators,
                    "qualname": fn.qualname,
                },
            )
            self._g.add_node(fn_node)

            # CONTAINS edge: parent → function/method
            self._g.add_edge(GraphEdge(
                from_id=parent_id,
                to_id=node_id,
                relationship=EdgeType.CONTAINS,
            ))

            # CALLS edges + line-level references (deferred to pass 2)
            for call in fn.calls:
                self._pending.append(_PendingEdge(
                    from_id=node_id,
                    raw_target=call.name,
                    relationship=EdgeType.CALLS,
                    source_file=rel,
                    source_line=call.line,
                    source_symbol=fn.qualname,
                ))

        # --- Import edges (deferred to pass 2) ---
        for imp in parsed.imports:
            self._pending.append(_PendingEdge(
                from_id=rel,
                raw_target=imp.module,
                relationship=EdgeType.IMPORTS,
                source_file=rel,
                source_line=imp.line,
                source_symbol=rel,
            ))

    def _resolve_pending(self) -> None:
        """Pass 2: resolve all deferred edges now that every node exists."""
        for pe in self._pending:
            target_id = self._resolve_to_id(pe.raw_target, context_file=pe.source_file)

            # Create external node if it doesn't exist yet
            if self._g.get_node(target_id) is None:
                self._g.add_node(GraphNode(
                    id=target_id,
                    type=NodeType.EXTERNAL,
                    name=pe.raw_target,
                ))

            self._g.add_edge(GraphEdge(
                from_id=pe.from_id,
                to_id=target_id,
                relationship=pe.relationship,
            ))

            # Record line-level reference with the resolved ID
            if pe.relationship == EdgeType.CALLS:
                self._tracker.record_call(
                    source_file=pe.source_file,
                    source_line=pe.source_line,
                    caller_qualname=pe.source_symbol,
                    callee_name=target_id,
                )
            elif pe.relationship == EdgeType.IMPORTS:
                self._tracker.record_import(
                    source_file=pe.source_file,
                    source_line=pe.source_line,
                    imported_module=target_id,
                )

        self._pending.clear()

    def _resolve_to_id(self, symbol: str, context_file: str | None = None) -> str:
        """
        Resolve a raw symbol name to a graph node ID.

        Called in pass 2 when all nodes exist.  Resolution order:
          1. Strip self./cls. prefix for method calls
          2. Exact node ID match
          3. Exact name match (prefer same-file, then METHOD > FUNCTION > CLASS > FILE)
          4. ID-suffix match (e.g. "run_agent" → "src/core/agent.py::run_agent")
          5. Fall back to "ext::<symbol>"
        """
        clean = symbol

        # Strip self./cls. prefix for method calls
        if "." in symbol:
            parts = symbol.split(".")
            if parts[0] in ("self", "cls"):
                clean = parts[-1]

        # 1. Exact node ID match
        if self._g.get_node(clean):
            return clean

        # 2. Exact name match
        _PRIORITY = {
            NodeType.METHOD: 0,
            NodeType.FUNCTION: 1,
            NodeType.CLASS: 2,
            NodeType.FILE: 3,
        }
        matches = self._g.find_by_name(clean)
        if matches:
            if context_file:
                same_file = [m for m in matches if m.file == context_file]
                if same_file:
                    return sorted(same_file, key=lambda n: _PRIORITY.get(n.type, 9))[0].id
            return sorted(matches, key=lambda n: _PRIORITY.get(n.type, 9))[0].id

        # 3. ID-suffix match: "run_agent" → "src/core/agent.py::run_agent"
        clean_lower = clean.lower()
        suffix = f"::{clean_lower}"
        candidates = [
            n for n in self._g.iter_nodes()
            if n.id.lower().endswith(suffix)
        ]
        if candidates:
            if context_file:
                same_file = [c for c in candidates if c.file == context_file]
                if same_file:
                    return sorted(same_file, key=lambda n: _PRIORITY.get(n.type, 9))[0].id
            return sorted(candidates, key=lambda n: _PRIORITY.get(n.type, 9))[0].id

        # 4. External
        return f"ext::{symbol}"
