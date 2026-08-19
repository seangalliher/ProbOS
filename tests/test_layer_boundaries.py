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
# ``dm_reply`` (AD-1248 / BF-801): the DM reply VALUE is a contract about
# ``IntentResult``, which lives here in ``types.py`` — so it belongs at the same
# tier, not in cognitive. Two layers wanted it and neither could have it
# (channels for the adapter disclosure, federation for BF-799 carriage), which
# is the module being misplaced rather than two independent judgement calls.
FOUNDATION_MODULES = {
    "types", "config", "crew_profile", "service_profile", "dm_reply",
}

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
    # AD-979d: cross-agent recall reads the trust network (TYPE_CHECKING-only;
    # DI via constructor) to weight cross-agent verifier evidence — same
    # Ship's-Computer-service precedent as the AD-399 entries above.
    ("cognitive/cross_agent_recall.py", "probos.consensus.trust"),
    # AD-399: substrate → mesh — TYPE_CHECKING + DI
    ("substrate/heartbeat.py", "probos.mesh.gossip"),
    ("substrate/scaler.py", "probos.mesh.intent"),
    # AD-700a: experience → agents.medical.diagnostic_levels — pure enum +
    # parse_level helper for the /diagnostic slash command. No behavioral
    # coupling (the agent invocation goes through the canonical pool lookup +
    # agent.handle_intent path).
    ("experience/commands/commands_diagnostic.py", "probos.agents.medical.diagnostic_levels"),
    # BF-085: cognitive → consensus.escalation — TYPE_CHECKING-only type annotation
    ("cognitive/decomposer.py", "probos.consensus.escalation"),
    # AD-451: cognitive → agents.red_team — TYPE_CHECKING-only type annotation
    # for TwoStageVerifier wrapper; runtime dependency injected via constructor.
    ("cognitive/validation_framework.py", "probos.agents.red_team"),
    # AD-528: cognitive → workforce — TYPE_CHECKING-only type annotation for
    # BookingJournal; runtime read goes through `runtime.work_item_store` public
    # attribute injection. Mirrors BF-085 / AD-451 precedent.
    ("cognitive/ground_truth.py", "probos.workforce"),
    # AD-583: knowledge → cognitive.social_verification — pure function import for independence scoring
    ("knowledge/records_store.py", "probos.cognitive.social_verification"),
    # AD-689: knowledge → mesh.routing — REL_INTENT relation-type constant
    # for filtering Hebbian weights during edge backfill. Pure constant, no
    # behavioral coupling.
    ("knowledge/backfill.py", "probos.mesh.routing"),
    # AD-482 (Wave 83): cognitive.self_improvement.qa_pool → consensus.shapley
    # — pure function import for Shapley aggregation across QA agents.
    ("cognitive/self_improvement/qa_pool.py", "probos.consensus.shapley"),
    # AD-482 (Wave 83): cognitive.self_improvement.qa_pool → agents.system_qa
    # — TYPE_CHECKING-only import for SystemQAAgent type annotations; runtime
    # access via injected pool.
    ("cognitive/self_improvement/qa_pool.py", "probos.agents.system_qa"),
    # AD-863..868 (Wave 215): chain-of-command-aware crew collaboration.
    # trust + shapley are Ship's Computer consensus services consumed by the
    # crew modules (same precedent as AD-399 cognitive→consensus.trust and
    # AD-482 cognitive→consensus.shapley). All TrustNetwork imports are
    # TYPE_CHECKING-only (DI via constructor); compute_shapley_values is a
    # pure function used for cross-verifier Shapley attribution.
    ("cognitive/crew_assignment.py", "probos.consensus.trust"),
    ("cognitive/crew_synth.py", "probos.consensus.shapley"),
    ("cognitive/crew_synth.py", "probos.consensus.trust"),
    ("cognitive/crew_verifier.py", "probos.consensus.trust"),
    # AD-1130: outcome-only CrewSession trust. The cognitive derivation module
    # consumes the pure Shapley function and the consensus-owned immutable
    # effect contract. CrewSession validates that same contract at its durable
    # boundary; neither import reaches into mutable consensus implementation.
    ("cognitive/crew_trust.py", "probos.consensus.shapley"),
    ("cognitive/crew_trust.py", "probos.consensus.crew_trust_effect"),
    ("cognitive/crew_session.py", "probos.consensus.crew_trust_effect"),
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


def test_no_stale_allowed_exceptions():
    """Every ALLOWED_EXCEPTIONS entry must correspond to an import that exists.

    Added after AD-1248 slice B committed an exception for an import that had
    already been reverted in the same change. A stale exemption is worse than a
    missing one: it silently pre-authorises a future violation nobody decided
    to allow, and it reads as though someone weighed it.
    """
    stale: list[str] = []
    for rel, module_name in sorted(ALLOWED_EXCEPTIONS):
        path = PROBOS_SRC / rel
        if not path.exists():
            stale.append(f"{rel} (file gone) -> {module_name}")
            continue
        imported = {m for _, m in _extract_probos_imports(path)}
        if module_name not in imported:
            stale.append(f"{rel} no longer imports {module_name}")

    assert not stale, (
        "stale cross-layer exceptions — delete them:\n  " + "\n  ".join(stale)
    )


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
