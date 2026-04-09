"""Test cross-layer import boundaries (AD-400).

Walks every .py file under src/probos/, extracts probos.* imports via AST,
and fails if any import crosses a layer boundary that isn't in the declared
allowlist. Foundation modules (types.py, config.py) are excluded — they are
importable by any layer by design.
"""

from __future__ import annotations

import ast
from pathlib import Path

PROBOS_SRC = Path(__file__).resolve().parent.parent / "src" / "probos"

LAYER_MAP = {
    "substrate": "substrate",
    "mesh": "mesh",
    "consensus": "consensus",
    "agents": "agents",
    "cognitive": "cognitive",
    "knowledge": "knowledge",
    "experience": "experience",
    "channels": "channels",
    "federation": "federation",
    "utils": "utils",
}

# Foundation tier — importable by ANY layer (not violations)
FOUNDATION_MODULES = {"types", "config", "crew_profile", "service_profile"}

# Layers that ANY other layer may import from (skip violation checks)
# - "utils" = pure helper functions, no domain logic
# - "core" = top-level orchestrators (runtime.py, api.py) — layers consume their services
UNIVERSALLY_IMPORTABLE_LAYERS = {"utils", "core"}

# layer -> set of layers it is allowed to import from
ALLOWED_IMPORTS = {
    "substrate": set(),  # lowest layer, imports nothing (except foundation)
    "mesh": {"substrate", "knowledge"},
    "consensus": {"mesh", "substrate"},
    "knowledge": {"substrate"},
    "agents": {"substrate", "cognitive"},
    "cognitive": {"knowledge", "substrate", "mesh"},
    "experience": {"cognitive", "consensus", "mesh", "substrate", "knowledge"},
    "channels": {"consensus", "mesh", "substrate"},
    "federation": {"mesh", "substrate"},
    "utils": set(),  # pure utilities, imports nothing
    "core": set(),  # core can import anything — never a violation
}

# (source_file_relative, imported_module) tuples
ALLOWED_EXCEPTIONS = {
    # AD-399: cognitive → consensus.trust — trust is a Ship's Computer service
    ("cognitive/dreaming.py", "probos.consensus.trust"),
    ("cognitive/emergent_detector.py", "probos.consensus.trust"),
    ("cognitive/feedback.py", "probos.consensus.trust"),
    ("cognitive/working_memory.py", "probos.consensus.trust"),
    # AD-399: substrate → mesh — TYPE_CHECKING + DI
    ("substrate/heartbeat.py", "probos.mesh.gossip"),
    ("substrate/scaler.py", "probos.mesh.intent"),
    # experience → agents (QA panel renders agent reports)
    ("experience/qa_panel.py", "probos.agents.system_qa"),
    # BF-085: cognitive → consensus.escalation — TYPE_CHECKING-only type annotation
    ("cognitive/decomposer.py", "probos.consensus.escalation"),
    # AD-583: knowledge → cognitive.social_verification — pure function import for independence scoring
    ("knowledge/records_store.py", "probos.cognitive.social_verification"),
}


def _get_layer(file_path: Path) -> str | None:
    """Map a file path to its architecture layer."""
    relative = file_path.relative_to(PROBOS_SRC)
    parts = relative.parts
    if len(parts) == 1:
        # Top-level module (runtime.py, api.py, types.py, etc.)
        stem = relative.stem
        if stem in FOUNDATION_MODULES:
            return None  # Foundation — skip checking
        return "core"
    # Package module (cognitive/scout.py, mesh/intent.py, etc.)
    package = parts[0]
    return LAYER_MAP.get(package)


def _get_imported_layer(module_name: str) -> str | None:
    """Map 'probos.X.Y' to the layer of X."""
    parts = module_name.split(".")
    if len(parts) < 2 or parts[0] != "probos":
        return None  # Not a probos import
    target = parts[1]
    if target in FOUNDATION_MODULES:
        return None  # Foundation — always allowed
    if target in LAYER_MAP:
        layer = LAYER_MAP[target]
        if layer in UNIVERSALLY_IMPORTABLE_LAYERS:
            return None  # utils/core — always allowed
        return layer
    return None  # Top-level core module — always allowed


def _extract_probos_imports(file_path: Path) -> list[tuple[int, str]]:
    """Extract (line_number, module_name) for all probos.* imports."""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []

    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("probos."):
                    imports.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("probos."):
                imports.append((node.lineno, node.module))
    return imports


def test_no_undocumented_cross_layer_imports():
    """Every probos.* import must follow the declared layer boundaries.

    Foundation modules (types.py, config.py, crew_profile.py, service_profile.py)
    are excluded — they are importable by any layer. Core modules (runtime.py,
    api.py) can import from any layer. All other cross-layer imports must be
    in ALLOWED_IMPORTS or ALLOWED_EXCEPTIONS.
    """
    violations: list[str] = []

    for py_file in sorted(PROBOS_SRC.rglob("*.py")):
        source_layer = _get_layer(py_file)
        if source_layer is None or source_layer == "core":
            continue  # Foundation or core — skip

        relative = str(py_file.relative_to(PROBOS_SRC)).replace("\\", "/")

        for lineno, module_name in _extract_probos_imports(py_file):
            target_layer = _get_imported_layer(module_name)
            if target_layer is None or target_layer == source_layer:
                continue  # Foundation, non-probos, or same layer

            # Check if this cross-layer import is allowed
            if target_layer in ALLOWED_IMPORTS.get(source_layer, set()):
                continue

            # Check if it's a documented exception
            if (relative, module_name) in ALLOWED_EXCEPTIONS:
                continue

            violations.append(
                f"  {relative}:{lineno} — {source_layer} imports "
                f"{module_name} ({target_layer})"
            )

    if violations:
        msg = (
            f"Found {len(violations)} undocumented cross-layer import(s):\n"
            + "\n".join(violations)
            + "\n\nTo fix: either move the import to an allowed layer, "
            "or add it to ALLOWED_EXCEPTIONS with a justification comment."
        )
        raise AssertionError(msg)


def test_lint_catches_violations():
    """Verify the lint test would catch a new violation."""
    # Simulate: substrate file importing from cognitive
    # This should be caught as a violation
    fake_violations = []
    source_layer = "substrate"
    target_layer = "cognitive"
    if target_layer not in ALLOWED_IMPORTS.get(source_layer, set()):
        fake_violations.append(
            "substrate/fake.py:1 — substrate imports probos.cognitive.foo (cognitive)"
        )
    assert len(fake_violations) == 1, "Lint should catch substrate→cognitive imports"
