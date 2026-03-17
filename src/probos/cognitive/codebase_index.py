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
}


class CodebaseIndex:
    """Read-only structural map of the ProbOS source tree."""

    def __init__(self, source_root: Path) -> None:
        self._source_root = Path(source_root)
        self._file_tree: dict[str, dict[str, Any]] = {}  # rel_path → metadata
        self._agent_map: list[dict[str, Any]] = []
        self._layer_map: dict[str, list[str]] = {}
        self._config_schema: dict[str, Any] = {}
        self._api_surface: dict[str, list[dict[str, str]]] = {}  # class_name → methods
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

        py_files = sorted(src.rglob("*.py"))
        for py in py_files:
            rel = str(py.relative_to(src)).replace("\\", "/")
            meta = self._analyze_file(py, rel)
            self._file_tree[rel] = meta

        self._build_layer_map()
        self._extract_config_schema()
        self._built = True
        logger.info(
            "CodebaseIndex built: %d files, %d agents, %d layers",
            len(self._file_tree),
            len(self._agent_map),
            len(self._layer_map),
        )

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    def query(self, concept: str) -> dict[str, Any]:
        """Keyword-based lookup across files, agents, methods, and layers."""
        concept_lower = concept.lower()

        matching_files: list[dict[str, Any]] = []
        for rel, meta in self._file_tree.items():
            relevance = 0
            if concept_lower in rel.lower():
                relevance += 3
            if concept_lower in (meta.get("docstring") or "").lower():
                relevance += 2
            for cls in meta.get("classes", []):
                if concept_lower in cls.lower():
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
            if concept_lower in a.get("type", "").lower()
            or concept_lower in (a.get("module") or "").lower()
        ]

        matching_methods: list[dict[str, str]] = []
        for cls_name, methods in self._api_surface.items():
            for m in methods:
                if (
                    concept_lower in m["method"].lower()
                    or concept_lower in cls_name.lower()
                ):
                    matching_methods.append({**m, "class": cls_name})

        layer: str | None = None
        for layer_name, files in self._layer_map.items():
            if concept_lower in layer_name:
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
        """Read source file contents.  Bounded to source_root only."""
        # Normalize separators
        file_path = file_path.replace("\\", "/")

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

        return meta

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
