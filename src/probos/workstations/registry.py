"""AD-1022: Workstation-type registry — tiered OSS-baseline / commercial-overlay seam.

This is the keystone that makes the OSS↔commercial mode toggle *visibly* change
the Captain's experience: a workstation *type* can have an OSS baseline render
**and** an optional commercial-overlay render, resolved at read time by the
``is_commercial_loaded()`` flag (AD-697). OSS registers the baseline types; the
private commercial overlay registers premium types/variants through the existing
AD-697 finalize-hook seam. Flipping modes (and restarting) changes what
``GET /api/workstations/types`` reports — with zero commercial code in the OSS
bundle.

Glossary — settling the overloaded "workspace/workstation" term:
    * **Workstation** — an Experience-layer interactive surface *type* the Captain
      opens (a code editor, a browser, a chat). THIS module's concept.
    * **Workspace** — the future multi-pane *container* that hosts workstations
      (AD-1023). NOT built here.
    * **execution work folder** — the AD-997 on-disk per-agent persistent working
      directory under ``data/execution/workspaces``. A *Substrate* concept reached
      only through the runtime execution API; unrelated to the Experience-layer
      Workstation/Workspace above. Do NOT conflate the two.

Design:
    * Plain in-memory, boot-built plumbing (like the tool registry — NOT a SQLite
      store). Constructed at finalize; populated with baselines when the feature
      is enabled.
    * Keyed by ``(id, tier)`` — last registration wins per key. A type *id* may be
      registered twice: an OSS baseline (``tier="oss"``) and a commercial overlay
      (``tier="commercial"``). ``resolve`` returns the commercial variant when the
      overlay is loaded, else the OSS baseline (which ALWAYS exists, so OSS-only
      mode is fully functional).
    * Log-and-degrade: a duplicate/invalid registration is rejected with a warning
      and never aborts boot.

Layer discipline: this module is Experience/runtime plumbing. It MUST NOT import
``execution.workspace`` or any commercial symbol. The render strategy keeps
commercial React out of the OSS bundle — a commercial workstation renders through
the sandboxed iframe seam (``McpAppFrame``, AD-597a), never an imported component.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

OSS_TIER = "oss"
COMMERCIAL_TIER = "commercial"
_VALID_TIERS = frozenset({OSS_TIER, COMMERCIAL_TIER})

NATIVE_KIND = "native"
IFRAME_KIND = "iframe"
_VALID_KINDS = frozenset({NATIVE_KIND, IFRAME_KIND})


@dataclass(frozen=True)
class WorkstationRender:
    """Tagged-union render strategy for a workstation type.

    ``kind == "native"``  → an OSS-shipped React component keyed by
        ``component_key`` (monaco/browser/chat). NEVER a commercial import.
    ``kind == "iframe"``  → a sandboxed iframe (``McpAppFrame``, AD-597a). The
        target is ``resource_uri`` (an MCP resource URI) or ``url`` (an
        overlay-served stub). The OSS HXI renders these without importing any
        commercial code.

    The render *target* (``component_key``/``resource_uri``/``url``) is internal:
    the public API (DD-4) emits only ``kind`` so a commercial ``url`` can never
    leak to an OSS-mode client.
    """

    kind: str
    component_key: str = ""
    resource_uri: str = ""
    url: str = ""


@dataclass(frozen=True)
class WorkstationType:
    """A registrable workstation-type descriptor (frozen).

    ``tier`` is ``"oss"`` (baseline — always available) or ``"commercial"``
    (available only when the commercial overlay is loaded). ``min_provider`` is
    an optional overlay-provider hint (empty for OSS baselines).
    """

    id: str
    label: str
    tier: str
    render: WorkstationRender
    min_provider: str = ""


class WorkstationTypeRegistry:
    """In-memory registry of workstation types with tiered resolution.

    Keyed by ``(id, tier)`` — last registration wins per key. ``resolve`` prefers
    the commercial variant when the overlay is loaded; ``list_available`` returns
    the resolved variant per id, gated by the commercial flag.
    """

    def __init__(self) -> None:
        self._types: dict[tuple[str, str], WorkstationType] = {}

    def register(self, descriptor: WorkstationType) -> bool:
        """Register a workstation type (last-wins per ``(id, tier)``).

        Log-and-degrade: an invalid descriptor is rejected with a warning and
        ``False`` — a bad registration NEVER aborts boot. Returns ``True`` when
        the descriptor was accepted.
        """
        if not isinstance(descriptor, WorkstationType):
            logger.warning(
                "AD-1022: register() ignored non-WorkstationType value of type %s",
                type(descriptor).__name__,
            )
            return False
        if not descriptor.id or not descriptor.tier:
            logger.warning(
                "AD-1022: workstation type rejected (empty id/tier): id=%r tier=%r",
                descriptor.id, descriptor.tier,
            )
            return False
        if descriptor.tier not in _VALID_TIERS:
            logger.warning(
                "AD-1022: workstation type %r rejected (bad tier %r; expected oss|commercial)",
                descriptor.id, descriptor.tier,
            )
            return False
        if descriptor.render.kind not in _VALID_KINDS:
            logger.warning(
                "AD-1022: workstation type %r rejected (bad render kind %r; expected native|iframe)",
                descriptor.id, descriptor.render.kind,
            )
            return False
        key = (descriptor.id, descriptor.tier)
        if key in self._types:
            logger.info(
                "AD-1022: workstation type %r (tier=%s) re-registered; last wins",
                descriptor.id, descriptor.tier,
            )
        self._types[key] = descriptor
        return True

    def resolve(
        self, type_id: str, *, commercial_loaded: bool
    ) -> WorkstationType | None:
        """Resolve a type id to its active variant.

        Returns the commercial variant when ``commercial_loaded`` and one is
        registered, else the OSS baseline, else ``None`` (the id is unknown, or
        commercial-only while the overlay is not loaded).
        """
        if commercial_loaded:
            commercial = self._types.get((type_id, COMMERCIAL_TIER))
            if commercial is not None:
                return commercial
        return self._types.get((type_id, OSS_TIER))

    def list_available(self, *, commercial_loaded: bool) -> list[WorkstationType]:
        """Available types (the resolved variant per id), sorted by id.

        A type id is included iff it has at least one available variant: the OSS
        baseline (always available) or a commercial variant (available only when
        ``commercial_loaded``). Same-id OSS/commercial pairs are deduped to the
        resolved variant so the catalog never lists an id twice; a commercial-only
        id is excluded entirely in OSS mode.
        """
        out: list[WorkstationType] = []
        for type_id in sorted({tid for (tid, _tier) in self._types}):
            resolved = self.resolve(type_id, commercial_loaded=commercial_loaded)
            if resolved is not None:
                out.append(resolved)
        return out

    def all_type_ids(self) -> tuple[str, ...]:
        """All distinct registered type ids (sorted) — diagnostics only."""
        return tuple(sorted({tid for (tid, _tier) in self._types}))
