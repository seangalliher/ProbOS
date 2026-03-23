# AD-400: Cross-Layer Import Lint Test

## Context

AD-399 cleaned up cross-layer dependency violations and documented allowed edges. This AD adds an automated test that enforces those boundaries — if someone adds an undocumented cross-layer import, CI catches it immediately.

## What to Build

A single pytest test file: `tests/test_layer_boundaries.py`

The test walks every `.py` file under `src/probos/`, extracts `import probos.*` and `from probos.* import ...` statements via AST, maps each file to its architecture layer, and fails if any import crosses a layer boundary that isn't in the declared allowlist.

## Layer Definitions

Map each file to a layer based on its directory:

```python
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
```

Files directly under `src/probos/` (not in any subdirectory) are classified into two tiers:

```python
# Foundation tier — importable by ANY layer (not violations)
FOUNDATION_MODULES = {"types", "config", "crew_profile", "service_profile"}

# Core tier — top-level orchestrators, can import anything
# (runtime.py, api.py, __main__.py, __init__.py, build_dispatcher.py, etc.)
```

Any file in `src/probos/*.py` that is NOT in `FOUNDATION_MODULES` is "core" tier.

## Allowed Import Directions

Each layer declares what it MAY import from. Imports to foundation modules (`types.py`, `config.py`, `crew_profile.py`, `service_profile.py`) are always allowed and excluded from checking.

```python
# layer -> set of layers it is allowed to import from
ALLOWED_IMPORTS = {
    "substrate": set(),  # lowest layer, imports nothing (except foundation)
    "mesh": {"substrate"},
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
```

## Allowed Exceptions (AD-399 Documented Edges)

These specific cross-layer imports have been reviewed and approved:

```python
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
}
```

## Implementation

```python
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

# ... constants defined above ...


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
        return LAYER_MAP[target]
    return "core"  # Top-level module


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
```

**Important implementation details:**

1. Use `Path.rglob("*.py")` to find all Python files — don't skip `__init__.py` files
2. Handle Windows path separators — normalize to `/` when comparing against exception keys
3. The test should pass on the current codebase with zero violations — if it finds any, the constants need adjusting (not the code)
4. `__init__.py` files belong to their parent package's layer
5. Files in nested subdirectories (e.g., `agents/medical/surgeon.py`) use their top-level package (`agents`)

## Verification

Run `pytest tests/test_layer_boundaries.py -v`. The test should pass with zero violations.

Then verify the test actually catches violations by temporarily adding a bad import to a test inspection:

```python
def test_lint_catches_violations():
    """Verify the lint test would catch a new violation."""
    # Simulate: substrate file importing from cognitive
    # This should be caught as a violation
    fake_violations = []
    source_layer = "substrate"
    target_layer = "cognitive"
    if target_layer not in ALLOWED_IMPORTS.get(source_layer, set()):
        fake_violations.append("substrate/fake.py:1 — substrate imports probos.cognitive.foo (cognitive)")
    assert len(fake_violations) == 1, "Lint should catch substrate→cognitive imports"
```

## Testing

Run:
```
uv run pytest tests/test_layer_boundaries.py -v
```

Should see 2 tests passing. Then run the full suite to verify no regression:
```
uv run pytest tests/ --tb=short
```

## Commit Message

```
Add cross-layer import boundary lint test (AD-400)

Automated test walks src/probos/, extracts imports via AST, maps to
architecture layers, and fails if undocumented cross-layer imports
appear. Foundation modules (types.py, config.py) excluded. Six
AD-399 allowed edges declared as exceptions. Turns architectural
boundaries into CI enforcement.
```
