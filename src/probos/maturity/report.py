"""AD-1270a: resolve declarations against the live authorities, and render them.

The three observable axes deliberately come from three *different* authorities,
because a single authority cannot express the case this AD exists to surface —
a capability that is present and enabled and nevertheless advertised nowhere:

===============  ==========================================================
``present``      the Python import system over the live source tree
``configured``   ``probos.config.SystemConfig`` loaded from a YAML path
``advertised``   ``probos.routers.tools.list_capability_catalog(runtime)``
===============  ==========================================================

**An unresolvable input is ``UNKNOWN``, never ``FALSE``.** A ``configured_when``
naming a path that does not exist on ``SystemConfig`` is a broken declaration,
not a disabled capability, and reporting it as disabled would be the same lie
this ledger is built to stop telling.

Every axis resolves behind its own ``try``/``except``: one failure degrades one
field and never aborts the run, mirroring ``list_capability_catalog``'s own
per-axis honest-degrade contract.
"""

from __future__ import annotations

import importlib.util
import logging
from collections.abc import Callable, Sequence
from importlib import import_module
from typing import Any

from probos.maturity.model import (
    ALWAYS_CONFIGURED,
    CapabilityDeclaration,
    CapabilityRow,
    ExerciseRecord,
    HealthRecord,
    LiveState,
    ReceiptSource,
    TriState,
)
from probos.maturity.registry import MaturityRegistry

logger = logging.getLogger(__name__)

__all__ = ["build_rows", "render_json", "render_markdown"]

_NO_RUNTIME = "advertised: no runtime attached (offline projection)"
_NO_BINDING = "advertised: no catalog binding declared"


def _missing_name_is_owner(exc: ModuleNotFoundError, owner_module: str) -> bool:
    """Is the module Python could not find the owner itself, or a parent of it?

    ``find_spec`` imports the parent package of a dotted name, so a
    ``ModuleNotFoundError`` can name an unrelated optional dependency the parent
    tried to import. That is a failed lookup, not evidence the owner is absent.
    """
    missing = exc.name
    if not missing:
        return False
    parts = owner_module.split(".")
    return any(missing == ".".join(parts[: i + 1]) for i in range(len(parts)))


def _resolve_present(
    declaration: CapabilityDeclaration, errors: list[str]
) -> TriState:
    """Does the owning module exist, and does it export the owning symbol?

    ``find_spec`` runs first so a *missing* module never triggers an import of
    the module itself — though it does import the owner's parent package. The
    import is guarded because an owner module can be heavy or can raise, and a
    generator that dies on one owner reports nothing about the other seven.
    """
    try:
        spec = importlib.util.find_spec(declaration.owner_module)
    except ModuleNotFoundError as exc:
        if _missing_name_is_owner(exc, declaration.owner_module):
            return TriState.FALSE
        errors.append(
            f"present: looking up {declaration.owner_module} failed on an "
            f"unrelated missing module {exc.name!r}; this is a failed lookup, "
            "not evidence the owner is absent"
        )
        return TriState.UNKNOWN
    except Exception as exc:
        errors.append(
            f"present: could not look up {declaration.owner_module} "
            f"({type(exc).__name__}: {exc})"
        )
        return TriState.UNKNOWN
    if spec is None:
        return TriState.FALSE
    try:
        module = import_module(declaration.owner_module)
    except Exception as exc:
        errors.append(
            f"present: {declaration.owner_module} failed to import "
            f"({type(exc).__name__}: {exc})"
        )
        return TriState.UNKNOWN
    return TriState.TRUE if hasattr(module, declaration.owner_symbol) else TriState.FALSE


def _resolve_configured(
    declaration: CapabilityDeclaration, config: Any, errors: list[str]
) -> TriState:
    """Walk the declaration's dotted ``configured_when`` path over the config."""
    predicate = declaration.configured_when
    if not predicate:
        errors.append("configured: declaration names no configured_when predicate")
        return TriState.UNKNOWN
    if predicate == ALWAYS_CONFIGURED:
        return TriState.TRUE
    current = config
    for part in predicate.split("."):
        if current is None or not hasattr(current, part):
            errors.append(
                f"configured: {predicate} does not resolve on the loaded config "
                f"(stopped at {part!r}); this is a broken declaration, not a "
                "disabled capability"
            )
            return TriState.UNKNOWN
        current = getattr(current, part)
    return TriState.TRUE if bool(current) else TriState.FALSE


def _resolve_advertised(
    declaration: CapabilityDeclaration,
    runtime: Any | None,
    catalog: dict[str, Any] | None,
    catalog_error: str | None,
    errors: list[str],
) -> TriState:
    """Is this capability's id present on its declared catalog axis?

    **Only membership proves anything.** ``list_capability_catalog`` degrades a
    failed axis by keeping whatever it appended before the failure and returning
    it with no completeness or error metadata, so a truncated axis and a
    complete one are byte-indistinguishable from here. Absence therefore cannot
    be a positive denial: this axis answers ``TRUE`` or ``UNKNOWN`` and never
    ``FALSE``. Deriving an authoritative ``FALSE`` needs per-axis completeness
    metadata from the catalog, which this slice may not change.
    """
    if runtime is None:
        errors.append(_NO_RUNTIME)
        return TriState.UNKNOWN
    if declaration.catalog_axis is None or declaration.catalog_id is None:
        errors.append(_NO_BINDING)
        return TriState.UNKNOWN
    if catalog is None:
        errors.append(catalog_error or "advertised: capability catalog unavailable")
        return TriState.UNKNOWN
    axis = catalog.get(declaration.catalog_axis)
    if not isinstance(axis, list):
        errors.append(
            f"advertised: catalog carries no {declaration.catalog_axis!r} axis"
        )
        return TriState.UNKNOWN
    ids = {entry.get("id") for entry in axis if isinstance(entry, dict)}
    if declaration.catalog_id in ids:
        return TriState.TRUE
    errors.append(
        f"advertised: {declaration.catalog_id!r} is not on the "
        f"{declaration.catalog_axis!r} axis, but the catalog reports no "
        "completeness metadata, so absence cannot be distinguished from a "
        "partially or wholly failed axis"
    )
    return TriState.UNKNOWN


def _resolve_receipts(
    declaration: CapabilityDeclaration,
    receipts: ReceiptSource | None,
    errors: list[str],
) -> tuple[TriState, ExerciseRecord, HealthRecord]:
    """Activation, exercise and health — all ``unknown`` until a source supplies them."""
    if receipts is None:
        return TriState.UNKNOWN, ExerciseRecord(), HealthRecord()

    try:
        activated = receipts.activation_for(declaration.id)
    except Exception as exc:
        errors.append(
            f"activated: receipt source failed ({type(exc).__name__}: {exc})"
        )
        activated = TriState.UNKNOWN
    try:
        exercise = receipts.exercise_for(declaration.id)
    except Exception as exc:
        errors.append(f"exercise: receipt source failed ({type(exc).__name__}: {exc})")
        exercise = ExerciseRecord()
    try:
        health = receipts.health_for(declaration.id)
    except Exception as exc:
        errors.append(f"health: receipt source failed ({type(exc).__name__}: {exc})")
        health = HealthRecord()
    return activated, exercise, health


def _safe_axis(
    axis: str, resolver: Callable[[], TriState], errors: list[str]
) -> TriState:
    """Run one axis resolver behind a final boundary.

    Each resolver already handles the failures it expects; this catches the ones
    it does not, so a malformed authority costs one field rather than the whole
    inventory. Degrades to ``UNKNOWN`` — a resolver that blew up looked at
    nothing, which is not evidence of absence.
    """
    try:
        return resolver()
    except Exception as exc:
        errors.append(f"{axis}: resolution failed ({type(exc).__name__}: {exc})")
        logger.warning(
            "AD-1270a: the %s axis raised during resolution; reporting unknown "
            "for this capability and continuing with the rest of the inventory",
            axis,
            exc_info=True,
        )
        return TriState.UNKNOWN


async def build_rows(
    registry: MaturityRegistry,
    *,
    config: Any,
    runtime: Any | None = None,
    receipts: ReceiptSource | None = None,
) -> tuple[CapabilityRow, ...]:
    """Resolve every declaration against the authorities available right now.

    A failure on any axis degrades that field to ``UNKNOWN`` with a
    ``resolution_errors`` entry rather than aborting the run. Cancellation and
    ``KeyboardInterrupt`` still propagate — those are control flow, not a failed
    authority. Rows come back sorted by declaration id.
    """
    catalog: dict[str, Any] | None = None
    catalog_error: str | None = None
    if runtime is not None:
        try:
            # Function-local so probos.maturity never pulls FastAPI at import
            # time, matching the two established in-process call sites. Inside
            # the guard because the import itself can fail.
            from probos.routers.tools import list_capability_catalog

            catalog = await list_capability_catalog(runtime)
        except Exception as exc:
            catalog_error = (
                "advertised: capability catalog unavailable "
                f"({type(exc).__name__}: {exc})"
            )
            logger.warning(
                "AD-1270a: list_capability_catalog failed; the advertised axis is "
                "unknown for every catalog-bound capability in this run",
                exc_info=True,
            )

    rows: list[CapabilityRow] = []
    for declaration in registry.declarations():
        errors: list[str] = []
        activated, exercise, health = _resolve_receipts(declaration, receipts, errors)
        rows.append(
            CapabilityRow(
                declaration=declaration,
                present=_safe_axis(
                    "present", lambda d=declaration: _resolve_present(d, errors), errors
                ),
                configured=_safe_axis(
                    "configured",
                    lambda d=declaration: _resolve_configured(d, config, errors),
                    errors,
                ),
                advertised=_safe_axis(
                    "advertised",
                    lambda d=declaration: _resolve_advertised(
                        d, runtime, catalog, catalog_error, errors
                    ),
                    errors,
                ),
                activated=activated,
                exercise=exercise,
                health=health,
                resolution_errors=tuple(errors),
            )
        )
    return tuple(rows)


def render_json(rows: Sequence[CapabilityRow]) -> dict[str, Any]:
    """The machine-readable row set."""
    return {
        "schema": "probos.capability-truth.v1",
        "rows": [row.to_dict() for row in rows],
        "counts": {
            "capabilities": len(rows),
            "live": sum(1 for row in rows if row.live is LiveState.LIVE),
            "inert": sum(1 for row in rows if row.live is LiveState.INERT),
            "unknown": sum(1 for row in rows if row.live is LiveState.UNKNOWN),
            "degraded": sum(1 for row in rows if row.live is LiveState.DEGRADED),
        },
    }


_HEADER = """# Capability Truth Inventory

**Generated file — do not edit by hand.**
Regenerate with `python scripts/gen_capability_truth.py`.

This is an **observation-only** inventory (AD-1270a, migration step 1). Nothing
reads a row to make a decision: it changes no routing, permission, trust or
startup behaviour. It exists so that *shipped* and *working* stop looking alike.

Each capability is resolved against three **different** authorities, so the
facts cannot collapse into one another:

| Axis | Authority |
|---|---|
| `present` | the Python import system over the source tree |
| `configured` | `SystemConfig` loaded from the config file |
| `advertised` | `routers.tools.list_capability_catalog(runtime)` |

`unknown` means *not observed*, never *absent*. A declaration whose
`configured_when` does not resolve is reported `unknown` with a note, because a
broken declaration is not a disabled capability.

**Why so much of this page says `unknown`, and why that is the finding.**
`activated`, `exercise` and `health` have no producer yet — emitting activation
receipts is migration step 2 and recording exercise receipts is migration step 3.
The generator also runs offline and constructs no runtime, which keeps `--check`
hermetic and is why `advertised` is `unknown` here even though the axis is
genuinely wired and covered by tests. `live` is **derived, never stored**, and no
row can read `live` without both an activation fact and at least one exercise
attempt — so in this slice no capability is provably live, and the page says so
rather than defaulting to optimism.
"""

_TRISTATE_LABEL = {
    TriState.TRUE: "yes",
    TriState.FALSE: "no",
    TriState.UNKNOWN: "unknown",
}


def _predicate_label(declaration: CapabilityDeclaration) -> str:
    if declaration.configured_when == ALWAYS_CONFIGURED:
        return "always (unconditional in the profile)"
    return f"`{declaration.configured_when}`"


def render_markdown(rows: Sequence[CapabilityRow]) -> str:
    """Render the committed inventory document.

    Emits **no clock value, no absolute path and no ``Path`` repr**. A timestamp
    makes ``--check`` fail on every run; a path repr makes the document current
    on exactly one operating system. Both mistakes have already cost this
    repository red CI.
    """
    ordered = sorted(rows, key=lambda row: row.declaration.id)
    lines = [_HEADER, "## Inventory", ""]
    lines.append(
        "| Capability | Present | Configured | Advertised | Activated | Exercise attempts | Health | Live |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for row in ordered:
        lines.append(
            f"| `{row.declaration.id}` "
            f"| {_TRISTATE_LABEL[row.present]} "
            f"| {_TRISTATE_LABEL[row.configured]} "
            f"| {_TRISTATE_LABEL[row.advertised]} "
            f"| {_TRISTATE_LABEL[row.activated]} "
            f"| {row.exercise.attempts} "
            f"| {row.health.state.value} "
            f"| {row.live.value} |"
        )
    lines.append("")

    lines.append("## Detail")
    lines.append("")
    for row in ordered:
        decl = row.declaration
        lines.append(f"### `{decl.id}` — {decl.title}")
        lines.append("")
        lines.append(f"- **Owner:** `{decl.owner_module}.{decl.owner_symbol}`")
        lines.append(f"- **Configured when:** {_predicate_label(decl)}")
        if decl.catalog_axis and decl.catalog_id:
            lines.append(
                f"- **Catalog binding:** `{decl.catalog_id}` on the "
                f"`{decl.catalog_axis}` axis"
            )
        else:
            lines.append("- **Catalog binding:** none declared")
        if decl.seam_ids:
            joined = ", ".join(f"`{seam}`" for seam in decl.seam_ids)
            lines.append(f"- **Related seams:** {joined}")
        if decl.notes:
            lines.append(f"- **Notes:** {decl.notes}")
        if row.resolution_errors:
            lines.append("- **Resolution notes:**")
            for note in row.resolution_errors:
                lines.append(f"  - {note}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
