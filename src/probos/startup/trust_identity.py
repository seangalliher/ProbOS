"""BF-907: trust records keyed by a sovereign identity are merged into the slot record.

Trust is keyed by slot id. Before BF-907, writers holding the sovereign UUID that
episodes carry (dream consolidation first among them) created separate records,
and AD-280's startup reconcile deleted them at the next start. At startup this
module binds trust to the identity registry, merges every record still keyed by a
sovereign identity into its slot, then runs AD-280 with unmerged identity keys
kept. ``verify_crew_trust_identity`` checks every crew member after startup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from probos.config import format_trust
from probos.identity import is_sovereign_identity_key

if TYPE_CHECKING:
    from probos.cognitive.introspective_telemetry import IntrospectiveTelemetryService
    from probos.consensus.trust import TrustKeyMerge, TrustNetwork
    from probos.identity import AgentIdentityRegistry
    from probos.substrate.event_log import EventLog
    from probos.substrate.registry import AgentRegistry

logger = logging.getLogger(__name__)

# BF-907 (D13): the merge event's name. A module constant, so AD-1195's census
# resolves ('trust', 'trust_identity_merge') and freezes it as a resolved pair.
MERGE_EVENT = "trust_identity_merge"


@dataclass(frozen=True, slots=True)
class TrustStoreReconciliation:
    """What the startup trust reconcile did."""

    merged: tuple[TrustKeyMerge, ...]
    kept: dict[str, str]  # identity key -> reason it was not merged
    removed: int  # AD-280 stale entries removed


async def reconcile_trust_identities(
    *,
    trust_network: TrustNetwork,
    identity_registry: AgentIdentityRegistry,
    active_ids: set[str],
    event_log: EventLog,
) -> TrustStoreReconciliation:
    """Bind, merge identity-keyed records by key, then remove stale entries (AD-280)."""
    trust_network.set_identity_resolver(identity_registry.resolve_slot_id)
    pairs: dict[str, str] = {}
    kept: dict[str, str] = {}
    for key in trust_network.raw_scores():
        if key in active_ids or not is_sovereign_identity_key(key):
            continue
        slot_id = identity_registry.resolve_slot_id(key)
        if slot_id is None:
            kept[key] = "unresolved"
        elif slot_id not in active_ids:
            kept[key] = "slot_inactive"
        else:
            pairs[key] = slot_id
    merged: tuple[TrustKeyMerge, ...] = ()
    if pairs:
        try:
            merged, refused = await trust_network.merge_identity_records(pairs)
        except Exception:
            logger.error(
                "BF-907: trust identity merge failed and was rolled back; %d records keyed "
                "by a sovereign identity are kept unmerged for the next start",
                len(pairs), exc_info=True,
            )
            kept.update(dict.fromkeys(pairs, "merge_failed"))
        else:
            kept.update(refused)
            for merge in merged:
                await _record_merge_event(event_log, merge)
    for key, reason in sorted(kept.items()):
        logger.warning("BF-907: trust record %s kept unmerged (%s)", key, reason)
    logger.info("BF-907 trust identity merge: merged=%d kept=%d", len(merged), len(kept))
    removed = trust_network.reconcile(active_ids | frozenset(kept))
    return TrustStoreReconciliation(merged=merged, kept=kept, removed=removed)


async def _record_merge_event(event_log: EventLog, merge: TrustKeyMerge) -> None:
    """One event per merge, so trend analyses can mark the step (log-and-degrade)."""
    try:
        await event_log.log(
            category="trust",
            event=MERGE_EVENT,
            agent_id=merge.target_key,
            detail=f"BF-907: {merge.source_key} merged into {merge.target_key}",
            data={
                "source_key": merge.source_key,
                "target_key": merge.target_key,
                "delta_alpha": merge.alpha_after - merge.target_alpha_before,
                "delta_beta": merge.beta_after - merge.target_beta_before,
                "alpha_before": merge.target_alpha_before,
                "beta_before": merge.target_beta_before,
                "alpha_after": merge.alpha_after,
                "beta_after": merge.beta_after,
                "merged_at": merge.merged_at,
                "snapshot_id": merge.snapshot_id,
            },
        )
    except Exception:
        logger.warning(
            "BF-907: merge event for %s was not written; trust.db trust_key_merges "
            "holds the record (snapshot %s)", merge.source_key, merge.snapshot_id, exc_info=True,
        )


async def verify_crew_trust_identity(
    *,
    trust_network: TrustNetwork,
    identity_registry: AgentIdentityRegistry,
    registry: AgentRegistry,
    telemetry: IntrospectiveTelemetryService | None,
) -> tuple[int, tuple[str, ...]]:
    """BF-907: every crew member's telemetry trust equals its header trust.

    Crew are the registered agents whose slot holds a birth certificate. A
    missing or mismatched sovereign_id is reported here, not repaired.
    Returns (crew count, problems).
    """
    keys = set(trust_network.raw_scores())
    crew = 0
    inconsistent = 0
    problems: list[str] = []
    for agent in registry.all():
        cert = identity_registry.get_by_slot(agent.id)
        if cert is None:
            continue
        crew += 1
        name = cert.callsign or agent.id
        found: list[str] = []
        if agent.sovereign_id != cert.agent_uuid:
            found.append(f"{name}: sovereign_id {agent.sovereign_id!r} is not its certificate {cert.agent_uuid}")
        if cert.agent_uuid in keys or cert.did in keys:
            found.append(f"{name}: a trust record is still keyed by its sovereign identity")
        header = format_trust(trust_network.get_score(agent.id))
        state = await telemetry.get_trust_state(agent.id) if telemetry is not None else {}
        if state.get("score") != header or "observations" not in state:
            found.append(f"{name}: telemetry trust {state.get('score', 'no record')} is not header {header}")
        if found:
            inconsistent += 1
            problems.extend(found)
    if problems:
        logger.warning(
            "BF-907 trust identity check: crew=%d consistent=%d; %s",
            crew, crew - inconsistent, "; ".join(problems),
        )
    else:
        logger.info("BF-907 trust identity check: crew=%d consistent=%d", crew, crew)
    return crew, tuple(problems)
