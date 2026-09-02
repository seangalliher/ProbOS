"""AD-1270a — the capability-truth shadow inventory.

Covers the model's derived ``live`` verdict, the declaration registry, the three
independent resolution authorities, the generated artifact's currency, the
slice-1 honesty invariants, and the layering rules that keep the package a leaf.

Hermetic: no runtime boot, no network, no clock, no writes outside ``tmp_path``.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from probos.config import SystemConfig
from probos.maturity.model import (
    ALWAYS_CONFIGURED,
    CapabilityDeclaration,
    CapabilityRow,
    ExerciseRecord,
    HealthRecord,
    HealthState,
    LiveState,
    TriState,
)
from probos.maturity.registry import (
    DECLARATION_MODULES,
    MaturityRegistry,
    load_default_registry,
)
from probos.maturity.report import build_rows, render_json, render_markdown

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "gen_capability_truth.py"
_DOC = _REPO_ROOT / "docs" / "development" / "capability-truth-inventory.md"
_SYSTEM_YAML = _REPO_ROOT / "config" / "system.yaml"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _declaration(**overrides: Any) -> CapabilityDeclaration:
    """A minimal valid declaration, overridable per test."""
    base: dict[str, Any] = {
        "id": "test.capability",
        "title": "Test capability",
        "owner_module": "probos.maturity.model",
        "owner_symbol": "TriState",
        "configured_when": ALWAYS_CONFIGURED,
    }
    base.update(overrides)
    return CapabilityDeclaration(**base)


def _row(**overrides: Any) -> CapabilityRow:
    """A row with every axis affirmed, overridable per test."""
    base: dict[str, Any] = {
        "declaration": _declaration(),
        "present": TriState.TRUE,
        "configured": TriState.TRUE,
        "advertised": TriState.TRUE,
        "activated": TriState.TRUE,
        "exercise": ExerciseRecord(attempts=1, last_success="2026-01-01T00:00:00Z"),
        "health": HealthRecord(state=HealthState.AVAILABLE),
    }
    base.update(overrides)
    return CapabilityRow(**base)


def _registry_of(*declarations: CapabilityDeclaration) -> MaturityRegistry:
    registry = MaturityRegistry()
    for declaration in declarations:
        registry.register(declaration)
    return registry


class _FakeToolRegistration:
    """Stands in for a ToolRegistration row in the tool catalog."""

    def __init__(self, tool_id: str) -> None:
        self._tool_id = tool_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self._tool_id,
            "name": self._tool_id,
            "description": "",
            "tool_type": "native",
            "provider": "builtin",
            "domain": "*",
            "department": None,
        }


class _FakeToolRegistry:
    def __init__(self, tool_ids: tuple[str, ...]) -> None:
        self._tools = [_FakeToolRegistration(tid) for tid in tool_ids]

    def list_tools(self) -> list[_FakeToolRegistration]:
        return list(self._tools)


class _FakeIntentDescriptor:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = ""
        self.usage_hint = ""
        self.requires_consensus = False
        self.tier = "core"


class _FakeAgent:
    def __init__(self, agent_id: str, intents: tuple[str, ...]) -> None:
        self.id = agent_id
        self.intent_descriptors = [_FakeIntentDescriptor(n) for n in intents]


class _FakeAgentRegistry:
    def __init__(self, agents: tuple[_FakeAgent, ...]) -> None:
        self._agents = list(agents)

    def all(self) -> list[_FakeAgent]:
        return list(self._agents)


class _FakeRuntime:
    """A runtime shaped only as much as ``list_capability_catalog`` reads it.

    Deliberately *not* a patched ``list_capability_catalog``: the point of the
    advertised test is that the real function is the authority. Patching it
    would prove the test double works and nothing about production.
    """

    def __init__(
        self,
        *,
        tool_ids: tuple[str, ...] = (),
        mesh_intents: tuple[str, ...] = (),
    ) -> None:
        self.tool_registry = _FakeToolRegistry(tool_ids)
        self.registry = _FakeAgentRegistry((_FakeAgent("agent-1", mesh_intents),))
        self.cognitive_skill_catalog = None
        self.tool_permission_store = None
        self.skill_grant_store = None
        self.config = None


class _FakeReceipts:
    """A ``ReceiptSource`` supplying all three unobservable axes."""

    def activation_for(self, capability_id: str) -> TriState:
        return TriState.TRUE

    def exercise_for(self, capability_id: str) -> ExerciseRecord:
        return ExerciseRecord(attempts=3, last_success="2026-01-01T00:00:00Z")

    def health_for(self, capability_id: str) -> HealthRecord:
        return HealthRecord(state=HealthState.AVAILABLE, source="fake")


class _RaisingReceipts:
    def activation_for(self, capability_id: str) -> TriState:
        raise RuntimeError("activation store unreachable")

    def exercise_for(self, capability_id: str) -> ExerciseRecord:
        raise RuntimeError("exercise store unreachable")

    def health_for(self, capability_id: str) -> HealthRecord:
        raise RuntimeError("health store unreachable")


# --------------------------------------------------------------------------
# 6.1 model and `live` derivation
# --------------------------------------------------------------------------


@pytest.mark.parametrize("axis", ["present", "configured", "advertised"])
def test_live_denied_axis_returns_inert(axis: str) -> None:
    """A positive denial on any observable axis beats every other signal."""
    # Arrange: an otherwise perfectly live row with one axis denied.
    row = _row(**{axis: TriState.FALSE})

    # Act / Assert
    assert row.live is LiveState.INERT


def test_live_all_axes_true_but_activation_unknown_returns_unknown() -> None:
    """Present, configured and advertised is not evidence anything activated it."""
    row = _row(activated=TriState.UNKNOWN)

    assert row.live is LiveState.UNKNOWN


def test_live_activated_without_exercise_returns_unknown() -> None:
    """The AD's headline rule: activation alone never yields LIVE."""
    row = _row(activated=TriState.TRUE, exercise=ExerciseRecord(attempts=0))

    assert row.live is LiveState.UNKNOWN


def test_live_activated_and_exercised_and_available_returns_live() -> None:
    """LIVE requires every axis, an activation fact, an attempt, and health."""
    row = _row()

    assert row.live is LiveState.LIVE


def test_live_failing_health_returns_degraded() -> None:
    row = _row(health=HealthRecord(state=HealthState.FAILING))

    assert row.live is LiveState.DEGRADED


def test_live_failure_without_success_returns_degraded() -> None:
    """A capability that has only ever failed is degraded, not merely unknown."""
    row = _row(
        exercise=ExerciseRecord(attempts=2, last_failure="2026-01-01T00:00:00Z"),
    )

    assert row.live is LiveState.DEGRADED


def test_live_exercised_without_health_observation_returns_unknown() -> None:
    """An attempt is not a health observation; the fallthrough stays honest."""
    row = _row(health=HealthRecord(state=HealthState.UNKNOWN))

    assert row.live is LiveState.UNKNOWN


def test_live_has_no_backing_storage_and_cannot_be_assigned() -> None:
    """``live`` is derived, so storing it must be structurally impossible.

    ``__slots__`` is the strongest available proof: it holds exactly the
    declared fields, so there is nowhere for a ``live`` value to live even if
    the frozen guard were removed.

    On the exception type — CPython 3.12's ``frozen=True, slots=True``
    combination raises ``FrozenInstanceError`` (an ``AttributeError``) for a
    declared field but ``TypeError`` for any other name, because the generated
    ``__setattr__`` closes over the pre-slots class object. The refusal is what
    this test pins; the type is an interpreter detail, so both are accepted
    rather than encoding one interpreter's quirk as a requirement.
    """
    row = _row()
    field_names = {f.name for f in dataclasses.fields(CapabilityRow)}

    assert "live" not in field_names
    assert "live" not in set(CapabilityRow.__slots__)
    assert set(CapabilityRow.__slots__) == field_names
    with pytest.raises((AttributeError, TypeError)):
        row.live = LiveState.LIVE  # type: ignore[misc]


def test_to_dict_includes_the_derived_live_verdict() -> None:
    row = _row(activated=TriState.UNKNOWN)

    payload = row.to_dict()

    assert payload["live"] == row.live.value == "unknown"
    assert payload["id"] == "test.capability"
    assert payload["exercise"]["attempts"] == 1
    assert payload["declaration"]["owner_symbol"] == "TriState"


# --------------------------------------------------------------------------
# 6.2 registry
# --------------------------------------------------------------------------


def test_load_default_registry_returns_sorted_unique_declarations() -> None:
    registry = load_default_registry()

    ids = [d.id for d in registry.declarations()]

    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))
    assert ids  # a registry that loads nothing would pass the two above


def test_load_default_registry_ships_exactly_the_declared_inventory() -> None:
    """Pin the inventory itself.

    Sorted-and-unique stays green if declarations are silently dropped and the
    document regenerated to match, so the denominator needs its own assertion.
    """
    expected = {
        "agents.http-fetch",
        "cognitive.crew-session",
        "cognitive.episodic-memory",
        "cognitive.intent-decomposition",
        "cognitive.self-modification",
        "infrastructure.snapshot-manifest",
        "tools.code-execution",
        "tools.governed-invocation",
    }

    assert {d.id for d in load_default_registry().declarations()} == expected


@pytest.mark.asyncio
async def test_every_shipped_declaration_resolves_present_true() -> None:
    """Every declared owner_module/owner_symbol pair must exist in this tree."""
    rows = await build_rows(load_default_registry(), config=SystemConfig())

    unresolved = {r.declaration.id: r.present for r in rows if r.present is not TriState.TRUE}

    assert unresolved == {}


def test_register_duplicate_id_raises_value_error() -> None:
    """A collided id would silently merge two capabilities' evidence."""
    registry = MaturityRegistry()
    registry.register(_declaration(owner_module="probos.maturity.model"))

    with pytest.raises(ValueError, match="duplicate maturity declaration id"):
        registry.register(_declaration(owner_module="probos.maturity.report"))


def test_load_default_registry_skips_a_broken_declaration_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One broken module must not blank the whole inventory."""
    import probos.maturity.registry as registry_module

    monkeypatch.setattr(
        registry_module,
        "DECLARATION_MODULES",
        ("probos.maturity.does_not_exist", "probos.tools.maturity_declarations"),
    )

    registry = registry_module.load_default_registry()

    assert [d.id for d in registry.declarations()] == [
        "tools.code-execution",
        "tools.governed-invocation",
    ]


def test_load_default_registry_returns_independent_objects() -> None:
    """No module-level singleton — a shared mutable global is what the AD forbids."""
    first = load_default_registry()
    second = load_default_registry()

    assert first is not second
    first.register(_declaration(id="zzz.only-in-first"))

    assert second.get("zzz.only-in-first") is None


def test_get_returns_the_declaration_for_a_known_id() -> None:
    registry = load_default_registry()

    declaration = registry.get("tools.code-execution")

    assert declaration is not None
    assert declaration.owner_symbol == "CodeExecutionTool"


def test_get_returns_none_for_an_unknown_id() -> None:
    assert load_default_registry().get("nothing.declares.this") is None


# --------------------------------------------------------------------------
# 6.3 resolution — the three authorities
# --------------------------------------------------------------------------


async def test_build_rows_present_true_for_a_real_module_and_symbol() -> None:
    registry = _registry_of(_declaration())

    rows = await build_rows(registry, config=SystemConfig())

    assert rows[0].present is TriState.TRUE


async def test_build_rows_present_false_for_a_missing_module() -> None:
    registry = _registry_of(_declaration(owner_module="probos.does_not_exist"))

    rows = await build_rows(registry, config=SystemConfig())

    assert rows[0].present is TriState.FALSE


async def test_build_rows_present_false_for_a_bogus_symbol() -> None:
    """The module existing is not evidence the capability does."""
    registry = _registry_of(_declaration(owner_symbol="NoSuchSymbol"))

    rows = await build_rows(registry, config=SystemConfig())

    assert rows[0].present is TriState.FALSE


async def test_build_rows_configured_true_for_always_configured() -> None:
    registry = _registry_of(_declaration(configured_when=ALWAYS_CONFIGURED))

    rows = await build_rows(registry, config=SystemConfig())

    assert rows[0].configured is TriState.TRUE
    assert rows[0].resolution_errors == (
        "advertised: no runtime attached (offline projection)",
    )


async def test_build_rows_configured_false_for_a_disabled_flag() -> None:
    """``self_mod.enabled`` defaults to False, so this row is genuinely disabled."""
    registry = _registry_of(_declaration(configured_when="self_mod.enabled"))

    rows = await build_rows(registry, config=SystemConfig())

    assert rows[0].configured is TriState.FALSE


async def test_build_rows_configured_unknown_for_an_unresolvable_path() -> None:
    """A broken declaration is UNKNOWN, never FALSE — that is the whole rule."""
    registry = _registry_of(_declaration(configured_when="memory.enabled"))

    rows = await build_rows(registry, config=SystemConfig())

    assert rows[0].configured is TriState.UNKNOWN
    assert any(
        "memory.enabled" in err and "does not resolve" in err
        for err in rows[0].resolution_errors
    )


async def test_build_rows_configured_unknown_for_an_empty_predicate() -> None:
    """A missing ``configured_when`` is a declaration error, not an implicit always."""
    registry = _registry_of(_declaration(configured_when=""))

    rows = await build_rows(registry, config=SystemConfig())

    assert rows[0].configured is TriState.UNKNOWN
    assert any("configured_when" in err for err in rows[0].resolution_errors)


async def test_build_rows_advertised_unknown_without_a_runtime() -> None:
    registry = _registry_of(
        _declaration(catalog_axis="tools", catalog_id="run_python")
    )

    rows = await build_rows(registry, config=SystemConfig(), runtime=None)

    assert rows[0].advertised is TriState.UNKNOWN
    assert (
        "advertised: no runtime attached (offline projection)"
        in rows[0].resolution_errors
    )


async def test_build_rows_advertised_unknown_when_no_catalog_binding_declared() -> None:
    """No binding means nothing was asked, which is not the same as absent."""
    registry = _registry_of(_declaration(catalog_axis=None, catalog_id=None))

    rows = await build_rows(
        registry, config=SystemConfig(), runtime=_FakeRuntime(tool_ids=("run_python",))
    )

    assert rows[0].advertised is TriState.UNKNOWN
    assert "advertised: no catalog binding declared" in rows[0].resolution_errors


async def test_build_rows_advertised_resolves_against_the_real_catalog() -> None:
    """The authority is the real ``list_capability_catalog``, not a stub of it.

    One catalog-bound declaration is present in the fake runtime's catalog and
    one is absent, so a resolver that returned a constant fails here.
    """
    registry = _registry_of(
        _declaration(id="a.present", catalog_axis="tools", catalog_id="run_python"),
        _declaration(id="b.absent", catalog_axis="tools", catalog_id="not_offered"),
    )
    runtime = _FakeRuntime(tool_ids=("run_python",))

    rows = await build_rows(registry, config=SystemConfig(), runtime=runtime)

    by_id = {row.declaration.id: row for row in rows}
    assert by_id["a.present"].advertised is TriState.TRUE
    # Was FALSE until adversarial review measured that the real catalog keeps
    # rows appended before a failure and reports no completeness metadata, so a
    # truncated axis is indistinguishable from a complete one. Absence is now
    # UNKNOWN; membership is still the discriminator this test exists for.
    assert by_id["b.absent"].advertised is TriState.UNKNOWN


async def test_build_rows_advertised_resolves_the_mesh_intent_axis() -> None:
    """The two catalog axes are separate; a tool row must not satisfy an intent row."""
    registry = _registry_of(
        _declaration(
            id="a.fetch", catalog_axis="mesh_intents", catalog_id="http_fetch"
        ),
        _declaration(
            id="b.other", catalog_axis="mesh_intents", catalog_id="never_served"
        ),
    )
    runtime = _FakeRuntime(mesh_intents=("http_fetch",))

    rows = await build_rows(registry, config=SystemConfig(), runtime=runtime)

    by_id = {row.declaration.id: row for row in rows}
    assert by_id["a.fetch"].advertised is TriState.TRUE
    # See the note above: absence on this axis is UNKNOWN, not FALSE.
    assert by_id["b.other"].advertised is TriState.UNKNOWN


async def test_build_rows_advertised_unknown_for_an_axis_the_catalog_omits() -> None:
    registry = _registry_of(
        _declaration(catalog_axis="not_an_axis", catalog_id="anything")
    )

    rows = await build_rows(
        registry, config=SystemConfig(), runtime=_FakeRuntime(tool_ids=("run_python",))
    )

    assert rows[0].advertised is TriState.UNKNOWN
    assert any("not_an_axis" in err for err in rows[0].resolution_errors)


async def test_build_rows_degrades_when_the_receipt_source_raises() -> None:
    """One failing axis degrades that field and never aborts the run."""
    registry = _registry_of(_declaration())

    rows = await build_rows(
        registry, config=SystemConfig(), receipts=_RaisingReceipts()
    )

    row = rows[0]
    assert row.activated is TriState.UNKNOWN
    assert row.exercise == ExerciseRecord()
    assert row.health == HealthRecord()
    assert sum("receipt source failed" in err for err in row.resolution_errors) == 3


async def test_build_rows_returns_empty_for_an_empty_registry() -> None:
    assert await build_rows(MaturityRegistry(), config=SystemConfig()) == ()


# --------------------------------------------------------------------------
# 6.4 generator and artifact currency
# --------------------------------------------------------------------------


def test_the_generator_script_exists() -> None:
    assert _SCRIPT.is_file(), (
        "scripts/gen_capability_truth.py is missing; the inventory cannot be "
        "regenerated without it"
    )


def test_the_inventory_doc_is_committed() -> None:
    assert _DOC.is_file(), (
        "docs/development/capability-truth-inventory.md is missing; run "
        "python scripts/gen_capability_truth.py"
    )


def test_the_inventory_matches_the_declarations() -> None:
    """The committed doc is byte-identical to a fresh generation.

    Runs the real script in ``--check`` mode so the test exercises exactly the
    command a developer is told to run, rather than a reimplementation of it
    that could itself drift.
    """
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=180,
    )

    assert result.returncode == 0, (
        "capability-truth-inventory.md is stale.\n"
        "Regenerate with: python scripts/gen_capability_truth.py\n\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_the_doc_is_marked_generated() -> None:
    text = _DOC.read_text(encoding="utf-8")

    assert "do not edit by hand" in text.lower()
    assert "gen_capability_truth.py" in text


def test_the_doc_contains_no_platform_or_time_dependent_tokens() -> None:
    """The doc must be byte-identical on Windows and Linux, and across runs.

    A generation timestamp makes ``--check`` fail on every run; a ``Path`` repr
    makes the doc current on exactly one operating system. Both mistakes have
    already cost this repository red CI (see the equivalent guard in
    ``tests/test_config_reference_current.py``).
    """
    text = _DOC.read_text(encoding="utf-8")

    offenders = [
        token
        for token in ("WindowsPath", "PosixPath", "\\Users\\", "/home/runner", "C:\\")
        if token in text
    ]
    assert not offenders, (
        f"platform-dependent value(s) in the generated inventory: {offenders}"
    )
    dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)
    assert not dates, (
        f"date-like token(s) in the generated inventory: {dates}. Rendering any "
        "clock value makes --check fail on every subsequent run."
    )


def test_the_json_projection_carries_every_row_and_its_counts() -> None:
    rows = _registry_of(_declaration(), _declaration(id="b.other"))
    payload = render_json(
        [
            _row(declaration=d, activated=TriState.UNKNOWN)
            for d in rows.declarations()
        ]
    )

    assert payload["schema"] == "probos.capability-truth.v1"
    assert payload["counts"] == {
        "capabilities": 2,
        "live": 0,
        "inert": 0,
        "unknown": 2,
        "degraded": 0,
    }
    assert [r["id"] for r in payload["rows"]] == ["b.other", "test.capability"]


def test_render_markdown_of_no_rows_still_renders_the_header() -> None:
    text = render_markdown([])

    assert "do not edit by hand" in text.lower()
    assert "## Inventory" in text


# --------------------------------------------------------------------------
# 6.5 slice-1 honesty invariants
# --------------------------------------------------------------------------


async def test_no_capability_in_the_shipped_inventory_is_live() -> None:
    """Slice 1 cannot prove any capability live, and must not pretend otherwise.

    This test is expected to change in migration step 3, when exercise receipts
    make a LIVE verdict reachable. Until then a LIVE row would mean the resolver
    is inventing evidence.
    """
    from probos.config import load_config

    rows = await build_rows(
        load_default_registry(), config=load_config(_SYSTEM_YAML), runtime=None
    )

    assert rows
    assert all(row.live is not LiveState.LIVE for row in rows)
    assert "| live |" not in _DOC.read_text(encoding="utf-8")


async def test_the_configured_axis_discriminates_across_the_shipped_declarations() -> None:
    """The ``configured`` axis must answer per-capability, not return a constant.

    NOTE — a correction to the build prompt's premise. § 4 Section 3 asserted
    that the *shipped* inventory would contain a ``configured=false`` row
    because ``self_mod.enabled`` defaults to ``False``. The default is indeed
    ``False``, but the committed ``config/system.yaml`` — which the generator
    reads — sets ``self_mod.enabled`` and ``workforce.enabled`` to ``True``, so
    all eight shipped rows resolve ``true``. Discrimination is therefore proven
    where it is actually observable: the same real declarations resolved against
    a default ``SystemConfig()`` yield both answers.
    """
    rows = await build_rows(load_default_registry(), config=SystemConfig())

    answers = {row.declaration.id: row.configured for row in rows}
    assert answers["cognitive.self-modification"] is TriState.FALSE
    assert answers["cognitive.crew-session"] is TriState.FALSE
    assert answers["tools.governed-invocation"] is TriState.TRUE
    assert TriState.UNKNOWN not in answers.values()


# --------------------------------------------------------------------------
# 6.6 layering and forward compatibility
# --------------------------------------------------------------------------


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_model_imports_nothing_from_probos() -> None:
    """``model.py`` must be a true leaf, or a declaration module in any layer
    importing it would invert the layer order."""
    spec = importlib.util.find_spec("probos.maturity.model")
    assert spec is not None and spec.origin is not None

    offenders = [
        name
        for name in _imported_modules(Path(spec.origin))
        if name == "probos" or name.startswith("probos.")
    ]

    assert not offenders, f"probos.maturity.model must import no probos module: {offenders}"


@pytest.mark.parametrize("module_name", DECLARATION_MODULES)
def test_declaration_modules_import_only_the_maturity_model(module_name: str) -> None:
    """A declaration is data about an owner, never a use of one."""
    spec = importlib.util.find_spec(module_name)
    assert spec is not None and spec.origin is not None

    offenders = sorted(
        _imported_modules(Path(spec.origin)) - {"__future__", "probos.maturity.model"}
    )

    assert not offenders, (
        f"{module_name} may import only probos.maturity.model; found {offenders}. "
        "Importing the declared subsystem makes reading the inventory expensive "
        "and side-effecting."
    )


async def test_a_receipt_source_fills_activation_exercise_and_health() -> None:
    """The ``ReceiptSource`` seam is exercised, not merely declared.

    Migration steps 2 and 3 must be able to attach receipts by supplying this
    argument, with no change to ``model.py``. Without this test the protocol
    would itself be a built-tested-inert artifact.
    """
    registry = _registry_of(
        _declaration(catalog_axis="tools", catalog_id="run_python")
    )
    runtime = _FakeRuntime(tool_ids=("run_python",))

    rows = await build_rows(
        registry, config=SystemConfig(), runtime=runtime, receipts=_FakeReceipts()
    )

    row = rows[0]
    assert row.activated is TriState.TRUE
    assert row.exercise.attempts == 3
    assert row.exercise.last_success == "2026-01-01T00:00:00Z"
    assert row.health.state is HealthState.AVAILABLE
    assert row.health.source == "fake"
    assert row.live is LiveState.LIVE
    assert row.resolution_errors == ()


# --------------------------------------------------------------------------
# 6.7 adversarial-review regressions (2026-09-01)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("axis", ["present", "configured", "advertised", "activated"])
def test_live_is_unknown_when_any_axis_is_unresolved(axis: str) -> None:
    """An unresolved axis blocks LIVE exactly as a denial does.

    UNKNOWN is not a weaker yes. Review measured 15 combinations reaching LIVE
    with an axis never resolved, which would let receipts promote a capability
    whose implementation or advertisement was never confirmed.
    """
    row = _row(**{axis: TriState.UNKNOWN})

    assert row.live is LiveState.UNKNOWN


def test_live_is_unknown_when_attempt_count_is_negative() -> None:
    """A corrupt negative counter is not proof of exercise."""
    row = _row(exercise=ExerciseRecord(attempts=-1, last_success="2026-01-01T00:00:00Z"))

    assert row.live is LiveState.UNKNOWN


@pytest.mark.parametrize(
    "attempts", [float("nan"), float("inf"), 1.5, "3", None, True]
)
def test_live_is_unknown_when_attempt_count_is_not_a_plain_int(attempts: Any) -> None:
    """Fail closed on a count that is not a trustworthy integer.

    ``ExerciseRecord`` does not enforce its annotation at runtime and a receipt
    source is external to this package, so ``float("nan")`` would pass an
    ordinary ``>= 1`` test — every comparison against NaN is false — and promote
    an unexercised capability to LIVE.
    """
    row = _row(
        exercise=ExerciseRecord(attempts=attempts, last_success="2026-01-01T00:00:00Z")
    )

    assert row.live is LiveState.UNKNOWN


@pytest.mark.asyncio
async def test_advertised_is_never_false_because_absence_cannot_be_proven() -> None:
    """Only membership proves anything on this axis.

    ``list_capability_catalog`` keeps whatever it appended before a failure and
    returns it with no completeness metadata, so a truncated axis and a complete
    one are indistinguishable here. Absence is therefore UNKNOWN, never FALSE.
    """
    registry = _registry_of(_declaration(catalog_axis="tools", catalog_id="absent_tool"))

    rows = await build_rows(
        registry, config=SystemConfig(), runtime=_FakeRuntime(tool_ids=("run_python",))
    )

    assert rows[0].advertised is TriState.UNKNOWN
    assert any("completeness metadata" in e for e in rows[0].resolution_errors)
    assert rows[0].live is not LiveState.INERT


@pytest.mark.asyncio
async def test_advertised_is_unknown_when_the_axis_is_truncated_by_a_failure() -> None:
    """A partially failed axis is nonempty yet incomplete.

    The real catalog appends rows until one raises, then swallows the error, so
    a nonempty axis is not proof that the axis is complete.
    """

    class _ExplodingRegistration:
        def to_dict(self) -> dict[str, Any]:
            raise RuntimeError("tool row unavailable")

    runtime = _FakeRuntime(tool_ids=("first",))
    runtime.tool_registry._tools.append(_ExplodingRegistration())  # type: ignore[arg-type]
    runtime.tool_registry._tools.append(_FakeToolRegistration("run_python"))
    registry = _registry_of(_declaration(catalog_axis="tools", catalog_id="run_python"))

    rows = await build_rows(registry, config=SystemConfig(), runtime=runtime)

    assert rows[0].advertised is TriState.UNKNOWN
    assert rows[0].live is not LiveState.INERT


@pytest.mark.asyncio
async def test_advertised_is_true_on_genuine_membership() -> None:
    """Membership is the one thing this axis can assert."""
    registry = _registry_of(_declaration(catalog_axis="tools", catalog_id="run_python"))

    rows = await build_rows(
        registry, config=SystemConfig(), runtime=_FakeRuntime(tool_ids=("run_python",))
    )

    assert rows[0].advertised is TriState.TRUE


@pytest.mark.asyncio
async def test_advertised_is_unknown_when_the_catalog_axis_is_empty() -> None:
    """An empty axis cannot prove absence either."""
    registry = _registry_of(_declaration(catalog_axis="tools", catalog_id="run_python"))

    rows = await build_rows(
        registry, config=SystemConfig(), runtime=_FakeRuntime(tool_ids=())
    )

    assert rows[0].advertised is TriState.UNKNOWN
    assert rows[0].live is not LiveState.INERT


@pytest.mark.parametrize(
    ("missing", "owner", "expected"),
    [
        ("probos.cognitive.decomposer", "probos.cognitive.decomposer", True),
        ("probos.cognitive", "probos.cognitive.decomposer", True),
        ("probos", "probos.cognitive.decomposer", True),
        ("toplevel", "toplevel", True),
        ("optional_dependency", "probos.cognitive.decomposer", False),
        ("probos.cognitive.decomposer.child", "probos.cognitive.decomposer", False),
        (None, "probos.cognitive.decomposer", False),
    ],
)
def test_missing_name_is_owner_distinguishes_owner_from_unrelated(
    missing: str | None, owner: str, expected: bool
) -> None:
    """Pin the helper directly.

    The presence tests drive it only through ``find_spec`` returning ``None``,
    so replacing this helper with ``return False`` would leave them green.
    """
    from probos.maturity.report import _missing_name_is_owner

    exc = ModuleNotFoundError(f"No module named {missing!r}", name=missing)

    assert _missing_name_is_owner(exc, owner) is expected


@pytest.mark.asyncio
async def test_present_is_unknown_when_an_unrelated_parent_import_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``find_spec`` imports the parent package, which can miss its own deps.

    That is a failed lookup, not evidence the owner is absent.
    """
    import probos.maturity.report as report_module

    def _raise_unrelated(name: str) -> Any:
        raise ModuleNotFoundError(
            "No module named 'optional_dependency'", name="optional_dependency"
        )

    monkeypatch.setattr(report_module.importlib.util, "find_spec", _raise_unrelated)
    registry = _registry_of(_declaration(owner_module="probos.cognitive.decomposer"))

    rows = await build_rows(registry, config=SystemConfig())

    assert rows[0].present is TriState.UNKNOWN
    assert any("optional_dependency" in e for e in rows[0].resolution_errors)


@pytest.mark.asyncio
async def test_present_is_false_when_the_owner_module_itself_is_missing() -> None:
    """The genuine-absence case must still read FALSE, not UNKNOWN."""
    registry = _registry_of(_declaration(owner_module="probos.does_not_exist"))

    rows = await build_rows(registry, config=SystemConfig())

    assert rows[0].present is TriState.FALSE


@pytest.mark.asyncio
async def test_build_rows_does_not_raise_when_an_authority_blows_up() -> None:
    """One malformed authority costs one field, never the whole inventory."""

    class _ExplodingConfig:
        @property
        def self_mod(self) -> Any:
            raise RuntimeError("config lookup unavailable")

    registry = _registry_of(
        _declaration(id="a.first", configured_when="self_mod.enabled"),
        _declaration(id="b.second", configured_when=ALWAYS_CONFIGURED),
    )

    rows = await build_rows(registry, config=_ExplodingConfig())

    assert len(rows) == 2
    assert rows[0].configured is TriState.UNKNOWN
    assert any("config lookup unavailable" in e for e in rows[0].resolution_errors)
    # the later row still resolves — the failure did not abort the run
    assert rows[1].configured is TriState.TRUE
    # and the later row does not inherit the earlier row's error
    assert not any("config lookup unavailable" in e for e in rows[1].resolution_errors)


@pytest.mark.asyncio
async def test_build_rows_degrades_when_the_catalog_import_itself_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The function-local import was moved inside the guard; prove it."""
    import builtins

    real_import = builtins.__import__

    def _fail_on_routers(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "probos.routers.tools":
            raise ImportError("fastapi unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fail_on_routers)
    registry = _registry_of(_declaration(catalog_axis="tools", catalog_id="run_python"))

    rows = await build_rows(
        registry, config=SystemConfig(), runtime=_FakeRuntime(tool_ids=("run_python",))
    )

    assert rows[0].advertised is TriState.UNKNOWN
    assert any("catalog unavailable" in e for e in rows[0].resolution_errors)
