"""
Python AST parser — extracts symbols, relationships, and references from .py files.

Uses the stdlib `ast` module (no external dependencies).  Produces a
ParsedFile that the LearningEngine converts into graph nodes + edges.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("zwischenzug.learning.ast_parser")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ImportInfo:
    module: str          # e.g. "os.path", "langchain"
    names: list[str]     # specific names imported (empty = "import module")
    alias: str | None    # "import X as Y"
    line: int
    is_from: bool        # True for "from X import Y"


@dataclass
class CallInfo:
    name: str            # e.g. "run_agent", "subprocess.run", "self.execute"
    line: int
    enclosing: str       # e.g. "BashTool.execute" or "<module>"


@dataclass
class FunctionInfo:
    name: str
    qualname: str        # e.g. "BashTool.execute"
    class_name: str | None
    start_line: int
    end_line: int
    decorators: list[str]
    calls: list[CallInfo]
    is_async: bool
    is_method: bool
    docstring: str


@dataclass
class ClassInfo:
    name: str
    bases: list[str]
    start_line: int
    end_line: int
    decorators: list[str]
    methods: list[str]
    docstring: str


@dataclass
class ParsedFile:
    file_path: str
    imports: list[ImportInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    module_calls: list[CallInfo] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    docstring: str = ""


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _get_name(node: ast.AST) -> str:
    """Flatten a dotted Name / Attribute to a string."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _get_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Subscript):
        return _get_name(node.value)
    return ""


def _get_decorator_name(dec: ast.AST) -> str:
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Attribute):
        return _get_name(dec)
    if isinstance(dec, ast.Call):
        return _get_decorator_name(dec.func)
    return ""


def _collect_calls(node: ast.AST, enclosing: str) -> list[CallInfo]:
    """Walk node and collect all ast.Call occurrences."""
    calls: list[CallInfo] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = _get_name(child.func)
            if name:
                line = getattr(child, "lineno", 0)
                calls.append(CallInfo(name=name, line=line, enclosing=enclosing))
    return calls


def _docstring_of(node: ast.AST) -> str:
    """Extract the first string literal from a body (docstring)."""
    body = getattr(node, "body", [])
    if body and isinstance(body[0], ast.Expr):
        val = body[0].value
        if isinstance(val, ast.Constant) and isinstance(val.value, str):
            return val.value.strip()
    return ""


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class PythonASTParser:
    """
    Parse a single Python source file and extract all symbols.

    Usage::

        parser = PythonASTParser()
        result = parser.parse_file("src/tools/bash.py")
    """

    def parse_file(self, file_path: str) -> ParsedFile:
        path = Path(file_path)
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ParsedFile(
                file_path=file_path,
                errors=[f"Cannot read file: {exc}"],
            )
        return self.parse_source(source, file_path)

    def parse_source(self, source: str, file_path: str = "<string>") -> ParsedFile:
        result = ParsedFile(file_path=file_path)

        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError as exc:
            result.errors.append(f"SyntaxError: {exc}")
            return result

        result.docstring = _docstring_of(tree)

        # ---- imports ----
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    result.imports.append(ImportInfo(
                        module=alias.name,
                        names=[],
                        alias=alias.asname,
                        line=node.lineno,
                        is_from=False,
                    ))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = [a.name for a in node.names]
                result.imports.append(ImportInfo(
                    module=module,
                    names=names,
                    alias=None,
                    line=node.lineno,
                    is_from=True,
                ))

        # ---- classes and their methods ----
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                cls_info = self._parse_class(node, file_path)
                result.classes.append(cls_info)

        # ---- top-level functions ----
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_info = self._parse_function(node, class_name=None)
                result.functions.append(fn_info)

        # ---- module-level calls (outside any function/class) ----
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call_name = _get_name(node.value.func)
                if call_name:
                    result.module_calls.append(
                        CallInfo(name=call_name, line=node.lineno, enclosing="<module>")
                    )

        return result

    # ------------------------------------------------------------------
    # Class parsing
    # ------------------------------------------------------------------

    def _parse_class(self, node: ast.ClassDef, file_path: str) -> ClassInfo:
        bases = [_get_name(b) for b in node.bases if _get_name(b)]
        decorators = [_get_decorator_name(d) for d in node.decorator_list]
        methods: list[str] = []

        # Parse methods and add them as FunctionInfo embedded in class
        # (returned separately via _parse_function)
        for item in ast.iter_child_nodes(node):
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(item.name)

        return ClassInfo(
            name=node.name,
            bases=bases,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            decorators=decorators,
            methods=methods,
            docstring=_docstring_of(node),
        )

    # ------------------------------------------------------------------
    # Function / method parsing
    # ------------------------------------------------------------------

    def _parse_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        class_name: str | None,
    ) -> FunctionInfo:
        qualname = f"{class_name}.{node.name}" if class_name else node.name
        is_method = class_name is not None
        decorators = [_get_decorator_name(d) for d in node.decorator_list]
        calls = _collect_calls(node, enclosing=qualname)

        return FunctionInfo(
            name=node.name,
            qualname=qualname,
            class_name=class_name,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            decorators=decorators,
            calls=calls,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            is_method=is_method,
            docstring=_docstring_of(node),
        )

    def parse_class_methods(
        self,
        class_node: ast.ClassDef,
        class_name: str,
    ) -> list[FunctionInfo]:
        """Parse all method definitions inside a ClassDef."""
        methods: list[FunctionInfo] = []
        for item in ast.iter_child_nodes(class_node):
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(self._parse_function(item, class_name=class_name))
        return methods

    def parse_all_methods(self, source: str, file_path: str = "<string>") -> list[FunctionInfo]:
        """
        Parse source and return ALL functions and methods (including class methods).
        Useful for reference tracking.
        """
        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            return []

        result: list[FunctionInfo] = []

        # Top-level functions
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                result.append(self._parse_function(node, class_name=None))
            elif isinstance(node, ast.ClassDef):
                result.extend(self.parse_class_methods(node, node.name))

        return result
