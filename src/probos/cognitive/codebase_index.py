"""CodebaseIndex — structural self-awareness of ProbOS source code (AD-290).

A runtime-level service (not an agent) that builds a static map of the
ProbOS source tree using AST inspection.  Built once at startup, read-only
during the session.  No LLM calls — pure static analysis.
"""

from __future__ import annotations

import ast
import inspect
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Directories → architectural layer names
_DIR_TO_LAYER: dict[str, str] = {
    "substrate": "substrate",
    "mesh": "mesh",
    "consensus": "consensus",
    "cognitive": "cognitive",
    "federation": "federation",
    "agents": "agents",
    "channels": "channels",
    "knowledge": "knowledge",
}

# Common words to ignore in keyword matching
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "about", "between",
    "through", "during", "before", "after", "above", "below", "and", "but",
    "or", "not", "no", "if", "then", "than", "so", "up", "out", "it",
    "its", "this", "that", "these", "those", "my", "your", "our", "their",
    "i", "you", "we", "they", "he", "she", "me", "him", "her", "us",
    "them", "what", "which", "who", "whom", "how", "when", "where", "why",
    "own", "very", "just", "also", "any", "each", "all", "both", "more",
})

# Key classes whose public API we extract
_KEY_CLASSES = {
    "ProbOSRuntime",
    "TrustNetwork",
    "IntentBus",
    "HebbianRouter",
    "DreamingEngine",
    "ResourcePool",
    "PoolScaler",
    "AgentRegistry",
    "EscalationManager",
    "AttentionManager",
    "CodebaseIndex",
    "PoolGroupRegistry",
    "Shell",
}

# Project documents to index alongside source code (AD-299)
_PROJECT_DOCS = [
    "DECISIONS.md",
    "PROGRESS.md",
    "progress-era-1-genesis.md",
    "progress-era-2-emergence.md",
    "progress-era-3-product.md",
    "progress-era-4-evolution.md",
    "docs/development/roadmap.md",
    "docs/development/contributing.md",
]


class CodebaseIndex:
    """Read-only structural map of the ProbOS source tree."""

    def __init__(self, source_root: Path) -> None:
        self._source_root = Path(source_root)
        self._project_root = self._source_root.parent.parent  # src/probos/ → project root (AD-299)
        self._file_tree: dict[str, dict[str, Any]] = {}  # rel_path → metadata
        self._agent_map: list[dict[str, Any]] = []
        self._layer_map: dict[str, list[str]] = {}
        self._config_schema: dict[str, Any] = {}
        self._api_surface: dict[str, list[dict[str, str]]] = {}  # class_name → methods
        self._caller_cache: dict[str, list[dict[str, Any]]] = {}  # AD-312
        self._import_graph: dict[str, list[str]] = {}  # AD-315: file → files it imports
        self._reverse_import_graph: dict[str, list[str]] = {}  # AD-315: file → files that import it
        self._built = False

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> None:
        """Scan source tree and populate all indexes."""
        src = self._source_root
        if not src.is_dir():
            logger.warning("CodebaseIndex: source root %s not found", src)
            self._built = True
            return

        # Scan Python source files
        py_files = sorted(src.rglob("*.py"))
        for py in py_files:
            rel = str(py.relative_to(src)).replace("\\", "/")
            meta = self._analyze_file(py, rel)
            self._file_tree[rel] = meta

        # Scan project documents (AD-299)
        for doc_rel in _PROJECT_DOCS:
            doc_path = self._project_root / doc_rel
            if doc_path.is_file():
                meta = self._analyze_doc(doc_path, doc_rel)
                # Prefix with "docs:" to distinguish from source files
                self._file_tree[f"docs:{doc_rel}"] = meta

        # Build import graph (AD-315a)
        for rel, meta in self._file_tree.items():
            if rel.startswith("docs:"):
                continue
            imported_paths: list[str] = []
            for imp in meta.get("imports", []):
                module = imp["module"]
                if not module.startswith("probos."):
                    continue
                rel_parts = module.split(".")[1:]  # strip "probos" prefix
                candidate = "/".join(rel_parts) + ".py"
                if candidate in self._file_tree:
                    imported_paths.append(candidate)
                else:
                    candidate_init = "/".join(rel_parts) + "/__init__.py"
                    if candidate_init in self._file_tree:
                        imported_paths.append(candidate_init)
            self._import_graph[rel] = imported_paths

        # Build reverse import graph
        for rel, imports in self._import_graph.items():
            for imp in imports:
                if imp not in self._reverse_import_graph:
                    self._reverse_import_graph[imp] = []
                self._reverse_import_graph[imp].append(rel)

        self._build_layer_map()
        self._extract_config_schema()
        self._built = True
        logger.info(
            "CodebaseIndex built: %d files, %d agents, %d layers, %d docs",
            len([k for k in self._file_tree if not k.startswith("docs:")]),
            len(self._agent_map),
            len(self._layer_map),
            len([k for k in self._file_tree if k.startswith("docs:")]),
        )

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    def query(self, concept: str) -> dict[str, Any]:
        """Keyword-based lookup across files, agents, methods, and layers."""
        # Split concept into meaningful keywords (AD-298)
        keywords = [
            w for w in concept.lower().split()
            if w not in _STOP_WORDS and len(w) > 1
        ]
        if not keywords:
            # Fallback: use the whole concept if all words were stop words
            keywords = [concept.lower().strip()]

        matching_files: list[dict[str, Any]] = []
        for rel, meta in self._file_tree.items():
            relevance = 0
            rel_lower = rel.lower()
            doc_lower = (meta.get("docstring") or "").lower()
            cls_names_lower = [c.lower() for c in meta.get("classes", [])]

            for kw in keywords:
                if kw in rel_lower:
                    relevance += 3
                if kw in doc_lower:
                    relevance += 2
                for cls in cls_names_lower:
                    if kw in cls:
                        relevance += 2

            if relevance > 0:
                matching_files.append({
                    "path": rel,
                    "docstring": meta.get("docstring"),
                    "relevance": relevance,
                })
        matching_files.sort(key=lambda m: -m["relevance"])

        matching_agents = [
            a for a in self._agent_map
            if any(
                kw in a.get("type", "").lower()
                or kw in (a.get("module") or "").lower()
                for kw in keywords
            )
        ]

        matching_methods: list[dict[str, str]] = []
        for cls_name, methods in self._api_surface.items():
            cls_lower = cls_name.lower()
            for m in methods:
                method_lower = m["method"].lower()
                if any(kw in method_lower or kw in cls_lower for kw in keywords):
                    matching_methods.append({**m, "class": cls_name})

        layer: str | None = None
        for layer_name, files in self._layer_map.items():
            if any(kw in layer_name for kw in keywords):
                layer = layer_name
                break

        return {
            "matching_files": matching_files[:20],
            "matching_agents": matching_agents[:20],
            "matching_methods": matching_methods[:20],
            "layer": layer,
        }

    def get_file_tree(self) -> dict[str, list[str]]:
        """Layer-organized file listing."""
        return dict(self._layer_map)

    def get_agent_map(self) -> list[dict[str, Any]]:
        """All detected agent types with metadata."""
        return list(self._agent_map)

    def get_layer_map(self) -> dict[str, list[str]]:
        """Files organized by architectural layer."""
        return dict(self._layer_map)

    def get_config_schema(self) -> dict[str, Any]:
        """All config fields with types and defaults."""
        return dict(self._config_schema)

    def get_api_surface(self, class_name: str) -> list[dict[str, str]]:
        """Public methods for a given class with signatures."""
        return list(self._api_surface.get(class_name, []))

    def read_source(
        self,
        file_path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> str:
        """Read source or doc file contents.  Bounded to source_root / project_root only."""
        # Normalize separators
        file_path = file_path.replace("\\", "/")

        # Resolve against the correct root (AD-299)
        if file_path.startswith("docs:"):
            actual_path = file_path[5:]  # strip "docs:" prefix
            target = (self._project_root / actual_path).resolve()
            try:
                target.relative_to(self._project_root.resolve())
            except ValueError:
                return ""
        else:
            # Resolve the absolute path and ensure it stays within source root
            target = (self._source_root / file_path).resolve()
            try:
                target.relative_to(self._source_root.resolve())
            except ValueError:
                return ""

        if not target.is_file():
            return ""

        text = target.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)

        if start_line is not None or end_line is not None:
            s = (start_line or 1) - 1
            e = end_line or len(lines)
            lines = lines[s:e]

        return "".join(lines)

    def read_doc_sections(
        self,
        file_path: str,
        keywords: list[str],
        max_lines: int = 200,
    ) -> str:
        """Read sections of a doc file that match the given keywords.

        Returns concatenated text of matching sections, up to max_lines total.
        Falls back to reading the first max_lines if no sections match.
        """
        meta = self._file_tree.get(file_path)
        if meta is None or meta.get("type") != "doc":
            return self.read_source(file_path, end_line=max_lines)

        sections = meta.get("sections", [])
        if not sections:
            return self.read_source(file_path, end_line=max_lines)

        # Score each section by keyword matches
        scored: list[tuple[int, dict[str, Any]]] = []
        for sec in sections:
            name_lower = sec["name"].lower()
            score = sum(1 for kw in keywords if kw in name_lower)
            if score > 0:
                scored.append((score, sec))
        scored.sort(key=lambda t: -t[0])

        # If no sections matched keywords, read the full doc from the top
        if not scored:
            return self.read_source(file_path, end_line=max_lines)

        # Build section line ranges: each section runs from its start to the next section's start
        all_lines = sorted(s["line"] for s in sections)

        # Read the full file to slice sections
        full_text = self.read_source(file_path)
        if not full_text:
            return ""
        file_lines = full_text.splitlines(keepends=True)

        result_lines: list[str] = []
        for _score, sec in scored:
            start = sec["line"] - 1  # 0-indexed
            # Find the next section start after this one
            idx = all_lines.index(sec["line"])
            end = all_lines[idx + 1] - 1 if idx + 1 < len(all_lines) else len(file_lines)

            section_lines = file_lines[start:end]
            result_lines.extend(section_lines)

            if len(result_lines) >= max_lines:
                result_lines = result_lines[:max_lines]
                break

        return "".join(result_lines)

    def find_callers(self, method_name: str, max_results: int = 10) -> list[dict[str, Any]]:
        """Find files that reference a method name (text search across indexed sources).

        AD-312: Searches all indexed source files for references to a method
        name.  Returns up to *max_results* matches sorted by reference count.
        Results are cached in ``_caller_cache`` to avoid re-scanning.
        """
        if method_name in self._caller_cache:
            return self._caller_cache[method_name][:max_results]

        results: list[dict[str, Any]] = []
        for rel in self._file_tree:
            if rel.startswith("docs:"):
                continue
            source = self.read_source(rel)
            if not source:
                continue
            line_numbers = [
                i + 1
                for i, line in enumerate(source.splitlines())
                if method_name in line
            ]
            if line_numbers:
                results.append({"path": rel, "lines": line_numbers})

        results.sort(key=lambda r: -len(r["lines"]))
        self._caller_cache[method_name] = results
        return results[:max_results]

    def find_tests_for(self, file_path: str) -> list[str]:
        """Find test files for a given source file using naming conventions.

        AD-312: Extracts the module name from *file_path* and searches the
        file tree for test files matching ``test_{module}`` patterns.
        """
        # Extract module name: "experience/panels.py" → "panels"
        parts = file_path.replace("\\", "/").split("/")
        filename = parts[-1] if parts else file_path
        module = filename.replace(".py", "")

        matches: list[str] = []
        for rel in self._file_tree:
            if rel.startswith("docs:"):
                continue
            rel_lower = rel.lower()
            if f"test_{module}" in rel_lower or (
                "test" in rel_lower and module in rel_lower
            ):
                matches.append(rel)
        return sorted(matches)

    def get_full_api_surface(self) -> dict[str, list[dict[str, str]]]:
        """Return public API surface for all key classes.

        AD-312: Exposes the complete ``_api_surface`` dict built at startup.
        """
        return dict(self._api_surface)

    def get_imports(self, file_path: str) -> list[str]:
        """Return list of internal (probos.*) files that this file imports.

        AD-315b: Looks up *file_path* in the forward import graph built at
        startup.  Only includes resolved probos-internal imports.
        """
        file_path = file_path.replace("\\", "/")
        return list(self._import_graph.get(file_path, []))

    def find_importers(self, file_path: str) -> list[str]:
        """Return list of files that import this file (reverse import graph).

        AD-315b: Looks up *file_path* in the reverse import graph built at
        startup.
        """
        file_path = file_path.replace("\\", "/")
        return list(self._reverse_import_graph.get(file_path, []))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _analyze_file(self, path: Path, rel: str) -> dict[str, Any]:
        """Parse a single Python file with AST and extract metadata."""
        meta: dict[str, Any] = {"path": rel, "docstring": None, "classes": []}

        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            return meta

        # Module docstring
        if (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)
        ):
            meta["docstring"] = tree.body[0].value.value.strip().split("\n")[0]

        # Walk top-level class definitions
        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            meta["classes"].append(node.name)

            # Check for agent subclass
            base_names = self._base_class_names(node)
            is_agent = any(
                b in ("BaseAgent", "HeartbeatAgent", "CognitiveAgent", "SkillBasedAgent")
                for b in base_names
            )
            if is_agent:
                agent_info = self._extract_agent_info(node, rel)
                self._agent_map.append(agent_info)

            # Extract API surface for key classes
            if node.name in _KEY_CLASSES:
                self._api_surface[node.name] = self._extract_methods(node)

        # Extract top-level import statements (AD-315a)
        imports: list[dict[str, str]] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append({"module": alias.name, "name": alias.asname or alias.name})
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for alias in node.names:
                        imports.append({"module": node.module, "name": alias.name})
        meta["imports"] = imports

        return meta

    def _analyze_doc(self, path: Path, rel: str) -> dict[str, Any]:
        """Extract metadata from a Markdown document (AD-299)."""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return {"docstring": None, "classes": [], "sections": [], "type": "doc"}

        lines = text.splitlines()

        # First # heading is the title (equivalent to docstring)
        title: str | None = None
        sections: list[dict[str, Any]] = []  # AD-300: section name + line number
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("# ") and title is None:
                title = stripped[2:].strip()
            elif stripped.startswith("## ") or stripped.startswith("### "):
                sections.append({
                    "name": stripped.lstrip("#").strip(),
                    "line": i + 1,  # 1-indexed
                })

        return {
            "docstring": title,
            "classes": [s["name"] for s in sections],  # keep for backward compat with query()
            "sections": sections,  # AD-300: structured section data
            "type": "doc",
        }

    def _base_class_names(self, node: ast.ClassDef) -> list[str]:
        """Extract base class name strings from a ClassDef."""
        names: list[str] = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                names.append(base.id)
            elif isinstance(base, ast.Attribute):
                names.append(base.attr)
        return names

    def _extract_agent_info(self, node: ast.ClassDef, module: str) -> dict[str, Any]:
        """Extract agent metadata from a ClassDef AST node."""
        info: dict[str, Any] = {
            "class": node.name,
            "type": node.name,
            "tier": "domain",
            "module": module,
            "bases": self._base_class_names(node),
            "capabilities": [],
            "intents": [],
        }
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    tname = getattr(target, "id", None)
                    if tname == "agent_type" and isinstance(item.value, ast.Constant):
                        info["type"] = item.value.value
                    elif tname == "tier" and isinstance(item.value, ast.Constant):
                        info["tier"] = item.value.value
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                tname = item.target.id
                if tname == "agent_type" and item.value and isinstance(item.value, ast.Constant):
                    info["type"] = item.value.value
                elif tname == "tier" and item.value and isinstance(item.value, ast.Constant):
                    info["tier"] = item.value.value
        return info

    def _extract_methods(self, node: ast.ClassDef) -> list[dict[str, str]]:
        """Extract public method signatures from a class."""
        methods: list[dict[str, str]] = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name.startswith("_"):
                    continue
                sig = self._format_signature(item)
                methods.append({"method": item.name, "signature": sig})
        return methods

    def _format_signature(self, func: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        """Format a function node into a readable signature string."""
        args = func.args
        parts: list[str] = []
        # Skip 'self' for methods — it's always the first positional arg
        all_args = args.args[1:] if args.args and args.args[0].arg == "self" else args.args
        for a in all_args:
            ann = ""
            if a.annotation:
                ann = f": {ast.unparse(a.annotation)}"
            parts.append(f"{a.arg}{ann}")
        ret = ""
        if func.returns:
            ret = f" -> {ast.unparse(func.returns)}"
        prefix = "async " if isinstance(func, ast.AsyncFunctionDef) else ""
        return f"{prefix}def {func.name}({', '.join(parts)}){ret}"

    def _build_layer_map(self) -> None:
        """Organize files into architectural layers by directory."""
        self._layer_map = {}
        for rel in self._file_tree:
            parts = rel.split("/")
            layer = _DIR_TO_LAYER.get(parts[0], "root") if parts else "root"
            if layer not in self._layer_map:
                self._layer_map[layer] = []
            self._layer_map[layer].append(rel)

    def _extract_config_schema(self) -> None:
        """Parse config.py to extract all config model fields and defaults."""
        config_path = self._source_root / "config.py"
        if not config_path.is_file():
            return

        try:
            source = config_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except SyntaxError:
            return

        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            # Look for Pydantic BaseModel subclasses
            base_names = self._base_class_names(node)
            if "BaseModel" not in base_names:
                continue
            fields: dict[str, str] = {}
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    field_name = item.target.id
                    type_str = ast.unparse(item.annotation) if item.annotation else "Any"
                    default_str = ast.unparse(item.value) if item.value else "required"
                    fields[field_name] = f"{type_str} = {default_str}"
            if fields:
                self._config_schema[node.name] = fields
