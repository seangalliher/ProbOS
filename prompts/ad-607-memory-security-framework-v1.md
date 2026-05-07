# AD-607 v1: Memory Security Framework — Extraction & Poisoning Defense (retrieval / response / privacy layers)

**Status:** Drafting (Wave 92)
**Dependencies:** AD-568a Source Governance (`source_governance.py`); AD-462c Oracle (`oracle_service.py`); AD-441 Sovereign Identity; AD-589 IntrospectiveFaithfulness (`cognitive_agent.py`); AD-479 Federation Hardening (`federation_recall_agent.py` — Wave 91); AD-610 storage-gate slot precedent; AD-530 ClassificationGate.
**Estimated tests:** ~75 across 10 classes (TestRecallAnomalyValidation, TestProvenanceIntegrity, TestAnchorMismatch, TestMemoryLeakageGuard, TestOracleAccessPolicy, TestFederationInboundSanitization, TestFederationOutboundPrivacy, TestPromptInjectionStoreGate, TestDifferentialPrivacyAggregation, TestSecurityMemorySlashCommand) plus ~3 wiring tests.
**Issue closed:** `#183 — AD-607: Memory Security Framework — Extraction & Poisoning Defense`.
**Baseline → target pytest:** 11963 → ≥ 12035 (+72 floor).

## Problem

ProbOS has source governance (`source_governance.py:60` retrieval strategy classification), qualification probes (`memory_probes.py` reliability testing), and classification disclosure (`security/classification.py:64` ClassificationGate) — but no explicit defense against adversarial memory operations. As ProbOS moves toward multi-instance federation (Wave 91 shipped AD-479 federation hardening including `recall_federated` IntentDescriptor and `FederationRecallAgent`), episodes can now cross trust boundaries. A compromised peer can:

1. **Extraction attacks** — craft `recall_federated` queries that surface another ship's sovereign-shard episodes that the requester has no business reading.
2. **Poisoning attacks** — store malicious episodes locally with embedded prompt-injection content, or share crafted episodes via federation that contaminate a peer's recall.
3. **Provenance gaps** — episodes stored without proper sovereign-id attribution can't be policy-enforced.
4. **Cross-shard leakage** — agent responses can inadvertently surface content from episodes belonging to other agents' sovereign shards.

The "AI Meets Brain" survey Section 8 (memory security) catalogs three defense layers — retrieval-based, response-based, privacy-based. ProbOS has none of them. AD-607 v1 ships all three layers in observational mode by default with opt-in enforcement.

## Solution

Three-layer defense framework:

- **Layer 1 (Retrieval):** Anomaly gate (`validate_recall_result`) called from every recall path. Provenance integrity check. Content-anchor mismatch detection. Emits anomaly events; opt-in dropping.
- **Layer 2 (Response):** Leakage guard slotted alongside the existing AD-589 IntrospectiveFaithfulness post-decision block. Detects responses that reference episode content outside the caller's sovereign shard. Emits `MEMORY_LEAK_SUSPECTED`; observational v1.
- **Layer 3 (Privacy):** Cross-shard access control on Oracle (`MemoryAccessPolicy` enum). Federated-recall inbound sanitization. Federated-recall outbound privacy filter. Differential-privacy aggregation when broadcasting to `public` access policy. Store-time prompt-injection detection mirroring AD-610 storage gate.
- **Operator surface:** `/security memory` slash subcommand surfacing the seven new EventType counters over a 24h window.

All seven new EventTypes (`MEMORY_RECALL_ANOMALY`, `MEMORY_PROVENANCE_GAP`, `MEMORY_ANCHOR_MISMATCH`, `MEMORY_LEAK_SUSPECTED`, `MEMORY_INJECTION_SUSPECTED`, `FEDERATION_EPISODE_REJECTED`, `FEDERATION_RECALL_DP_REDACTED`) follow the AD-527 typed-events pattern.

## Section 0: Event Types

Add seven new EventType values to `src/probos/events.py` (appended, no reordering of existing values; alphabetical placement within domain groups per existing style):

**Memory-domain (placement near `MEMORY_REFS_DISPATCHED` at events.py:243):**
- `MEMORY_RECALL_ANOMALY = "memory_recall_anomaly"`  # AD-607a
- `MEMORY_PROVENANCE_GAP = "memory_provenance_gap"`  # AD-607b
- `MEMORY_ANCHOR_MISMATCH = "memory_anchor_mismatch"`  # AD-607c
- `MEMORY_LEAK_SUSPECTED = "memory_leak_suspected"`  # AD-607d
- `MEMORY_INJECTION_SUSPECTED = "memory_injection_suspected"`  # AD-607h

**Federation-domain (placement near W91's `FEDERATION_PEER_DISCOVERED`):**
- `FEDERATION_EPISODE_REJECTED = "federation_episode_rejected"`  # AD-607f
- `FEDERATION_RECALL_DP_REDACTED = "federation_recall_dp_redacted"`  # AD-607i

Verify-first: `Select-String -Path src/probos/events.py -Pattern 'MEMORY_RECALL_ANOMALY|MEMORY_PROVENANCE_GAP|MEMORY_ANCHOR_MISMATCH|MEMORY_LEAK_SUSPECTED|MEMORY_INJECTION_SUSPECTED|FEDERATION_EPISODE_REJECTED|FEDERATION_RECALL_DP_REDACTED'` returns zero matches at HEAD `255c52a` — collision-free.

## Section 1: AD-607a — Recall anomaly validator + MemorySecurityConfig + module skeleton

Create new module `src/probos/cognitive/memory_security.py`:

```python
"""AD-607: Memory Security Framework — extraction & poisoning defense.

Three defense layers per "AI Meets Brain" survey Section 8:
  - Retrieval-based: validate_recall_result anomaly gate
  - Response-based: check_memory_leakage guard (consumed by cognitive_agent.py
    AD-589 post-decision block)
  - Privacy-based: MemoryAccessPolicy enum + DP aggregation

v1 is OBSERVATIONAL by default. Opt-in enforcement via MemorySecurityConfig
flags (enforce_recall / enforce_provenance / enforce_store / enforce_leak) —
all default-False per the AD-695 + W82 + W88 + W91 default-False precedent.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from probos.events import EventType
from probos.types import Episode

logger = logging.getLogger(__name__)


class MemoryAccessPolicy(str, Enum):
    """Cross-shard memory access policy. AD-607e."""
    PERMISSIVE = "permissive"           # default: preserve AD-462c cross-shard recall
    OWN_SHARD_ONLY = "own_shard_only"   # filter to caller's sovereign_id
    OWN_SHARD_PLUS_PUBLIC = "own_shard_plus_public"  # caller's shard + ship/fleet classification


@dataclass(frozen=True)
class RecallValidationResult:
    """Result of a recall-time anomaly check. AD-607a."""
    allowed: bool
    anomalies: tuple[str, ...]   # anomaly NAMES that fired
    score: float                 # composite anomaly score, [0.0, 1.0], higher = more anomalous


# Pattern set scoped tightly to known prompt-injection shapes. Default-set
# revisit is AD-607h-1. Callers extend via MemorySecurityGate.register_pattern.
_PROMPT_INJECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("ignore_previous", r"(?i)\bignore\s+(all\s+)?previous\s+instructions\b"),
    ("role_swap", r"(?i)\byou\s+are\s+now\s+a\s+different\s+(agent|assistant|model)\b"),
    ("tool_spoof", r"(?i)\b(call|invoke)\s+tool\s*[:=]\s*[a-z_][a-z0-9_]*"),
    ("system_prompt_leak", r"(?i)\bwhat\s+is\s+your\s+(system\s+)?(prompt|instructions)\b"),
)


def validate_recall_result(
    episode: Episode,
    *,
    query: str = "",
    anchor_query: Any = None,  # source_governance.AnchorQuery | None
    config: Any = None,        # MemorySecurityConfig | None
) -> RecallValidationResult:
    """AD-607a: anomaly gate for a single recalled episode.

    Aggregates AD-607b provenance + AD-607c anchor-mismatch checks plus
    content-entropy anomaly. Returns RecallValidationResult.allowed=True
    when no anomaly fires; observational by default. Caller decides whether
    to drop the episode based on config.enforce_recall.
    """
    # Implementation calls validate_provenance + score_anchor_mismatch + entropy check;
    # aggregates anomaly names + composite score.
    ...


def validate_provenance(episode: Episode) -> tuple[bool, str]:
    """AD-607b: provenance integrity check. Returns (ok, reason)."""
    if not episode.agent_ids:
        return False, "missing_agent_ids"
    # source must be in known MemorySource enum values
    KNOWN_SOURCES = {"direct", "introspection", "designed", "federated", "imported", "consolidated_thought", "seeded"}
    if episode.source not in KNOWN_SOURCES:
        return False, f"unknown_source:{episode.source}"
    if episode.source == "direct" and not episode.correlation_id:
        return False, "direct_source_missing_correlation_id"
    return True, ""


def score_anchor_mismatch(episode: Episode, anchor_query: Any) -> float:
    """AD-607c: how badly does the episode's anchor frame mismatch the query's?

    Returns a score in [0.0, 1.0]; higher = more mismatched. Reuses the
    AD-567c anchor_dimension_weights config inverted as anomaly signal.
    Returns 0.0 when anchor_query is None or episode has no AnchorFrame.
    """
    ...


def check_memory_leakage(
    response_text: str,
    recalled_episodes: list[Episode],
    *,
    caller_sovereign_id: str = "",
) -> tuple[bool, list[str]]:
    """AD-607d: detect responses that reference episodes outside the caller's
    sovereign shard. Returns (leakage_suspected, leaked_episode_ids).

    Heuristic v1: if response_text contains substring overlap (>=20 chars
    contiguous) with episode.user_input AND episode.agent_ids does not
    contain caller_sovereign_id, flag as leakage.
    """
    ...


def aggregate_with_dp(
    episodes: list[Episode],
    *,
    min_cohort_size: int = 3,
) -> list[Episode]:
    """AD-607i: differential-privacy aggregator. When fewer than
    min_cohort_size unique sovereign_ids contributed across the episode set,
    blank Episode.user_input + Episode.dag_summary on returned episodes;
    Episode.id, timestamp, agent_ids retained.
    """
    ...
```

Wire `MemorySecurityConfig` into `src/probos/config.py` SecurityConfig at `:1687`:

```python
class MemorySecurityConfig(BaseModel):
    """AD-607: Memory security framework configuration."""

    enforce_recall: bool = False        # AD-607a opt-in: drop anomalous episodes from recall
    enforce_provenance: bool = False    # AD-607b opt-in: reject provenance-gap episodes from recall
    enforce_leak_guard: bool = False    # AD-607d opt-in: redact response when leak suspected
    enforce_store: bool = False         # AD-607h opt-in: reject prompt-injection at store time
    anchor_mismatch_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    dp_min_cohort_size: int = Field(default=3, ge=1)


# In SecurityConfig (existing class at config.py:1687):
class SecurityConfig(BaseModel):
    # ... existing fields ...
    memory: MemorySecurityConfig = Field(default_factory=MemorySecurityConfig)
```

Wire `MemoryAccessPolicy` field onto `MemoryConfig` (config.py:601):

```python
# In MemoryConfig:
access_policy: str = "permissive"   # AD-607e: PERMISSIVE | OWN_SHARD_ONLY | OWN_SHARD_PLUS_PUBLIC
```

Wire `memory_access_policy` + `shared_trust_min_score` + `dp_min_cohort_size` onto `FederationConfig` (config.py:872), placed below the W91 `min_peer_trust_score` field at `:911`:

```python
# In FederationConfig (after min_peer_trust_score):
# AD-607g federation outbound privacy filter (default-shared_trust honors
# the AD-479b peer-trust ranking surface that W91 shipped).
memory_access_policy: str = "shared_trust"   # public | shared_trust | private
shared_trust_min_score: float = Field(default=0.5, ge=0.0, le=1.0)
dp_min_cohort_size: int = Field(default=3, ge=1)

@field_validator("memory_access_policy")
@classmethod
def _validate_memory_access_policy(cls, v: str) -> str:
    valid = {"public", "shared_trust", "private"}
    if v not in valid:
        raise ValueError(f"memory_access_policy must be one of {sorted(valid)}; got {v!r}")
    return v
```

**Tests** in new file `tests/test_ad607_memory_security.py` — class `TestRecallAnomalyValidation` (~8 tests):

1. `test_validate_recall_result_clean_episode_allows` — episode with valid agent_ids + source returns allowed=True, anomalies=().
2. `test_validate_recall_result_aggregates_provenance_anomaly` — episode with empty agent_ids surfaces "missing_agent_ids" in anomalies tuple.
3. `test_validate_recall_result_aggregates_anchor_mismatch` — episode with anchor_query mismatch above threshold surfaces "anchor_mismatch".
4. `test_validate_recall_result_score_monotonic` — composite score rises as more anomalies fire.
5. `test_validate_recall_result_no_query_no_anchor_clean` — calling without query/anchor still validates provenance.
6. `test_validate_recall_result_emits_event_when_anomalous` — `MEMORY_RECALL_ANOMALY` emitted via injected emit_event hook (test fake).
7. `test_memory_security_config_defaults_observational` — all enforce_* default to False.
8. `test_memory_access_policy_field_validator_rejects_invalid` — `FederationConfig(memory_access_policy="bogus")` raises ValueError.

## Section 2: AD-607b — Provenance integrity check + recall hook

Wire `validate_recall_result` into `EpisodicMemory.recall()` at `episodic.py:1508` — append the anomaly gate at the bottom of the result-collection loop, AFTER the existing relevance-threshold filter:

```python
# In recall(), after the existing similarity-threshold filter:
async def recall(self, query: str, k: int = 5) -> list[Episode]:
    ...
    episodes: list[Episode] = []
    for i, doc_id in enumerate(result["ids"][0]):
        # ... existing similarity filter ...
        ep = self._metadata_to_episode(doc_id, document, metadata)

        # AD-607a: recall-time anomaly gate (observational by default)
        if self._security_config is not None:
            from probos.cognitive.memory_security import validate_recall_result
            validation = validate_recall_result(
                ep,
                query=query,
                anchor_query=None,   # plain semantic recall has no anchor query
                config=self._security_config,
            )
            if validation.anomalies:
                self._emit_security_event(EventType.MEMORY_RECALL_ANOMALY, {
                    "episode_id": ep.id,
                    "anomalies": list(validation.anomalies),
                    "score": validation.score,
                })
                if self._security_config.enforce_recall:
                    continue  # drop the anomalous episode

        episodes.append(ep)
        if len(episodes) >= k:
            break

    return episodes
```

Add `EpisodicMemory.set_security_config(config)` setter mirroring the existing `set_storage_gate(gate)` at `episodic.py:692`:

```python
def set_security_config(self, config: Any) -> None:
    """AD-607: Wire memory security config (validates recall + emits anomaly events)."""
    self._security_config = config

def _emit_security_event(self, event_type: Any, payload: dict) -> None:
    """AD-607: emit security events through the existing emit_event hook if wired."""
    emit = getattr(self, "_emit_event", None)
    if emit is not None:
        try:
            emit(event_type, payload)
        except Exception:
            logger.debug("AD-607: security event emit failed", exc_info=True)
```

Initialize `self._security_config = None` in `__init__` at the same site as `self._storage_gate = None` (around line 685).

**Tests** — class `TestProvenanceIntegrity` (~7 tests):

1. `test_validate_provenance_clean_passes` — Episode with agent_ids=[id], source="direct", correlation_id=cid → (True, "").
2. `test_validate_provenance_missing_agent_ids_fails` — empty agent_ids → (False, "missing_agent_ids").
3. `test_validate_provenance_unknown_source_fails` — source="unknown" → (False, "unknown_source:unknown").
4. `test_validate_provenance_direct_no_correlation_fails` — source="direct" + empty correlation_id → (False, "direct_source_missing_correlation_id").
5. `test_validate_provenance_federated_source_no_correlation_passes` — source="federated" + empty correlation_id is allowed (federated origin doesn't require local correlation).
6. `test_recall_emits_provenance_gap_event_observational` — broken-provenance episode flagged but still returned when `enforce_provenance=False`.
7. `test_recall_drops_provenance_gap_when_enforced` — `enforce_provenance=True` removes the episode from the result list.

## Section 3: AD-607c — Anchor mismatch + recall_by_anchor_scored hook

Implement `score_anchor_mismatch` reusing `MemoryConfig.anchor_dimension_weights` at `config.py:642`. For each non-empty dimension in `anchor_query` that doesn't match `episode.anchors`, accumulate the dimension's weight; final score = sum / total weight.

Wire into `EpisodicMemory.recall_by_anchor_scored()` at `episodic.py:1610` AND `recall_by_anchor()` at `episodic.py:2584` mirroring the Section 2 hook — anomaly gate after the score filter, emits `MEMORY_ANCHOR_MISMATCH` when `score >= anchor_mismatch_threshold`.

Also wire into `OracleService._query_episodic()` at `oracle_service.py:541` so cross-tier Oracle queries see the same gate.

**Tests** — class `TestAnchorMismatch` (~6 tests):

1. `test_score_anchor_mismatch_no_anchor_query_zero` — anchor_query=None → 0.0.
2. `test_score_anchor_mismatch_full_match_zero` — query.department=engineering matches episode.anchors.department=engineering → 0.0.
3. `test_score_anchor_mismatch_full_mismatch_high` — every dimension mismatches → score >= 0.9.
4. `test_score_anchor_mismatch_partial_weighted` — 1 of 5 dimensions mismatches → score equals that dimension's weight / total.
5. `test_recall_by_anchor_emits_mismatch_event_above_threshold` — episode with mismatched anchors emits `MEMORY_ANCHOR_MISMATCH`.
6. `test_recall_by_anchor_does_not_emit_below_threshold` — minor mismatch (score < 0.7 default) does not emit.

## Section 4: AD-607d — Response-based leakage guard

Implement `check_memory_leakage(response_text, recalled_episodes, *, caller_sovereign_id) -> (leakage_suspected, leaked_episode_ids)` per the Section 1 module signature.

Wire into `cognitive_agent.py` post-decision block alongside the existing AD-589 `_check_introspective_faithfulness` invocation — this is a sibling check, NOT a replacement:

```python
# In CognitiveAgent's post-decision pipeline (search for "_check_introspective_faithfulness"):
async def _check_memory_leakage(self, response_text: str, recalled: list[Episode]) -> None:
    """AD-607d: detect responses that leak episode content outside caller's shard."""
    if not response_text or not recalled:
        return
    from probos.cognitive.memory_security import check_memory_leakage
    caller_id = getattr(self, "sovereign_id", "") or self.id
    suspected, leaked_ids = check_memory_leakage(
        response_text, recalled, caller_sovereign_id=caller_id,
    )
    if suspected:
        self._emit_event(EventType.MEMORY_LEAK_SUSPECTED, {
            "agent_id": caller_id,
            "leaked_episode_ids": leaked_ids,
        })
        # v1 observational — log + event only, no response mutation
```

Use `asyncio.iscoroutinefunction()` for any conditional async wiring per BF-254.

**Tests** — class `TestMemoryLeakageGuard` (~8 tests):

1. `test_check_memory_leakage_clean_response_no_leak` — response references nothing from recalled episodes → (False, []).
2. `test_check_memory_leakage_caller_owns_shard_no_leak` — response quotes content from episodes whose agent_ids includes caller → (False, []).
3. `test_check_memory_leakage_cross_shard_substring_flagged` — response contains 25-char substring from foreign-shard episode → (True, [ep.id]).
4. `test_check_memory_leakage_short_overlap_below_threshold` — response shares <20-char overlap → (False, []).
5. `test_check_memory_leakage_multiple_leaks_returns_all` — response leaks from two foreign shards → returns both ids.
6. `test_check_memory_leakage_empty_caller_treated_as_unknown` — caller_sovereign_id="" with foreign episodes still flags.
7. `test_cognitive_agent_post_decision_emits_leak_event` — integration: CognitiveAgent fires `MEMORY_LEAK_SUSPECTED` through injected emit hook.
8. `test_cognitive_agent_observational_does_not_mutate_response` — leakage detected but response_text returned verbatim.

## Section 5: AD-607e — Cross-shard access control on Oracle

Extend `OracleService.query()` at `oracle_service.py:268` with two new optional kwargs `caller_sovereign_id: str = ""` and `access_policy: MemoryAccessPolicy = MemoryAccessPolicy.PERMISSIVE`.

```python
# At oracle_service.py:268, signature change:
async def query(
    self,
    query_text: str,
    *,
    agent_id: str = "",
    intent_type: str = "",
    k_per_tier: int = 5,
    tiers: list[str] | None = None,
    caller_sovereign_id: str = "",                              # AD-607e
    access_policy: Any = None,                                   # AD-607e: MemoryAccessPolicy | None
) -> list[OracleResult]:
    ...
    # After per-tier aggregation, before returning all_results:
    from probos.cognitive.memory_security import MemoryAccessPolicy
    policy = access_policy or MemoryAccessPolicy.PERMISSIVE
    if policy != MemoryAccessPolicy.PERMISSIVE and caller_sovereign_id:
        all_results = self._apply_access_policy(all_results, caller_sovereign_id, policy)
    ...

def _apply_access_policy(self, results: list[OracleResult], caller: str, policy: Any) -> list[OracleResult]:
    """AD-607e: filter results to caller's shard per MemoryAccessPolicy."""
    from probos.cognitive.memory_security import MemoryAccessPolicy
    filtered: list[OracleResult] = []
    for r in results:
        ep = getattr(r, "episode", None)
        if ep is None:
            filtered.append(r)  # non-episode results (records, semantic) unaffected
            continue
        owns = caller in (ep.agent_ids or [])
        if policy == MemoryAccessPolicy.OWN_SHARD_ONLY:
            if owns:
                filtered.append(r)
        elif policy == MemoryAccessPolicy.OWN_SHARD_PLUS_PUBLIC:
            classification = (ep.dag_summary or {}).get("classification", "private")
            if owns or classification in {"ship", "fleet"}:
                filtered.append(r)
    return filtered
```

Default remains `PERMISSIVE` → preserves AD-462c cross-shard recall verbatim.

**Tests** — class `TestOracleAccessPolicy` (~10 tests):

1. `test_query_default_permissive_unchanged_results` — no caller_sovereign_id, no access_policy → identical behavior to HEAD.
2. `test_query_own_shard_only_filters_to_caller` — episodes whose agent_ids excludes caller dropped.
3. `test_query_own_shard_only_keeps_caller_episodes` — caller's own episodes retained.
4. `test_query_own_shard_plus_public_keeps_ship_classified` — classification=ship preserved.
5. `test_query_own_shard_plus_public_drops_private_foreign` — foreign + private dropped.
6. `test_query_records_results_not_filtered` — Tier 2 records (no Episode) untouched.
7. `test_query_empty_caller_falls_through_permissive` — caller="" + OWN_SHARD_ONLY treated as permissive (defensive — no caller to filter against).
8. `test_query_invalid_policy_treated_as_permissive` — None policy = PERMISSIVE.
9. `test_memory_config_access_policy_field_default` — MemoryConfig.access_policy="permissive".
10. `test_oracle_query_threads_caller_through` — runtime wiring test: caller_sovereign_id propagates from CognitiveAgent context.

## Section 6: AD-607f — Federated-recall inbound sanitization

Extend `FederationRecallAgent.act()` at `federation_recall_agent.py:60` — the path that aggregates incoming peer responses (currently lines that call local `EpisodicMemory.recall()` and dedupe by `episode_id`) — to validate every inbound episode through `validate_recall_result` + `validate_provenance` + a new `validate_inbound_classification`:

```python
def validate_inbound_classification(episode: Episode) -> tuple[bool, str]:
    """AD-607f: filter federated-inbound episodes that should never cross trust boundaries."""
    classification = (episode.dag_summary or {}).get("classification", "private")
    if classification == "private":
        return False, "private_classification"
    # Reuse ClassificationGate sensitive-pattern set via direct check
    from probos.security.classification import _DEFAULT_SENSITIVE_PATTERNS
    import re as _re
    for name, pat in _DEFAULT_SENSITIVE_PATTERNS:
        if _re.search(pat, episode.user_input or ""):
            return False, f"sensitive_pattern:{name}"
    return True, ""
```

Sanitization runs unconditionally — receiver always owns its boundary, no opt-out. Rejected episodes emit `FEDERATION_EPISODE_REJECTED` with `{episode_id, reason, peer_node_id}` payload.

**Tests** — class `TestFederationInboundSanitization` (~8 tests):

1. `test_inbound_clean_episode_accepted` — well-formed episode passes all three gates.
2. `test_inbound_private_classification_rejected` — classification=private dropped.
3. `test_inbound_sensitive_pattern_rejected` — episode.user_input matches `secret_format` pattern dropped.
4. `test_inbound_provenance_gap_rejected` — empty agent_ids dropped.
5. `test_inbound_anomalous_anchor_rejected` — high anchor mismatch dropped.
6. `test_inbound_emits_federation_episode_rejected_event` — rejection emits event with reason.
7. `test_inbound_sanitization_unconditional_no_opt_out` — no config flag disables sanitization.
8. `test_inbound_aggregator_dedupe_preserves_security` — when two peers return the same ep.id, the surviving copy still passes sanitization.

## Section 7: AD-607g — Federated-recall outbound privacy filter + AD-607i DP aggregation

Extend `FederationRecallAgent.act()` outbound path — after local `EpisodicMemory.recall()`, BEFORE returning to the requesting peer — to filter through `MemoryAccessPolicy` + apply DP aggregation:

```python
async def act(self, plan: dict[str, Any]) -> IntentResult:
    ...
    local_eps = await self._runtime.episodic_memory.recall(query, k=k)

    # AD-607g: outbound privacy filter
    fed_config = self._runtime.config.federation
    policy_str = fed_config.memory_access_policy
    if policy_str == "private":
        local_eps = []
    elif policy_str == "public":
        # public: ship/fleet classification only
        local_eps = [
            ep for ep in local_eps
            if (ep.dag_summary or {}).get("classification", "private") in {"ship", "fleet"}
        ]
        # AD-607i: DP redaction on public outbound
        from probos.cognitive.memory_security import aggregate_with_dp
        dp_min = fed_config.dp_min_cohort_size
        before_count = len(local_eps)
        local_eps = aggregate_with_dp(local_eps, min_cohort_size=dp_min)
        if local_eps and before_count > 0:
            self._emit_event(EventType.FEDERATION_RECALL_DP_REDACTED, {
                "before_count": before_count,
                "after_count": len(local_eps),
                "min_cohort_size": dp_min,
            })
    elif policy_str == "shared_trust":
        # shared_trust: only return to peers above min trust score
        # The peer trust check happens at the bridge layer; here we
        # filter classified content only (drop private regardless).
        local_eps = [
            ep for ep in local_eps
            if (ep.dag_summary or {}).get("classification", "private") != "private"
        ]
    return IntentResult(..., result={"episodes": local_eps}, ...)
```

`aggregate_with_dp` blanks `user_input` + `dag_summary` on returned Episodes when fewer than `min_cohort_size` distinct sovereign_ids contributed (computed by counting unique values across `[ep.agent_ids[0] for ep in episodes if ep.agent_ids]`).

**Tests** — class `TestFederationOutboundPrivacy` (~8 tests) + `TestDifferentialPrivacyAggregation` (~6 tests):

`TestFederationOutboundPrivacy`:
1. `test_outbound_default_shared_trust_drops_private` — config default + private episode dropped.
2. `test_outbound_default_shared_trust_keeps_ship` — ship-classified retained.
3. `test_outbound_public_drops_private` — public mode drops private.
4. `test_outbound_public_drops_department` — public requires ship/fleet.
5. `test_outbound_public_applies_dp` — single-sovereign batch returned with blanked user_input.
6. `test_outbound_public_emits_dp_redacted_event` — emits event with before/after counts.
7. `test_outbound_private_returns_empty` — private mode returns no episodes.
8. `test_outbound_field_validator_rejects_invalid_policy` — config validation rejects bogus policy strings.

`TestDifferentialPrivacyAggregation`:
1. `test_aggregate_with_dp_above_cohort_unchanged` — 4 unique sovereigns, min=3 → episodes returned verbatim.
2. `test_aggregate_with_dp_below_cohort_blanks_content` — 2 unique sovereigns, min=3 → user_input + dag_summary blanked.
3. `test_aggregate_with_dp_preserves_id_timestamp_agent_ids` — id, timestamp, agent_ids retained in blanked path.
4. `test_aggregate_with_dp_min_cohort_one_no_redaction` — min=1 always passes through.
5. `test_aggregate_with_dp_empty_input_empty_output` — [].
6. `test_aggregate_with_dp_no_agent_ids_treated_conservatively` — episodes without agent_ids treated as zero-cohort.

## Section 8: AD-607h — Store-time prompt-injection detection

Implement `MemorySecurityGate` class in `memory_security.py` mirroring the AD-610 storage-gate pattern:

```python
@dataclass
class StoreSecurityDecision:
    """AD-607h: store-time security decision."""
    action: str  # "ALLOW" | "REJECT"
    reason: str
    matched_pattern: str = ""


class MemorySecurityGate:
    """AD-607h: store-time prompt-injection detection. Mirrors the AD-610
    storage-gate slot pattern at episodic.py:949 — same evaluate() contract,
    different concern (security vs utility)."""

    def __init__(self, config: Any) -> None:
        self._config = config
        self._patterns = [(name, re.compile(pat)) for name, pat in _PROMPT_INJECTION_PATTERNS]

    def evaluate_store(self, episode: Episode) -> StoreSecurityDecision:
        text = episode.user_input or ""
        for name, pat in self._patterns:
            if pat.search(text):
                return StoreSecurityDecision(
                    action="REJECT" if self._config.enforce_store else "ALLOW",
                    reason="prompt_injection_pattern",
                    matched_pattern=name,
                )
        return StoreSecurityDecision(action="ALLOW", reason="ok")

    def register_pattern(self, name: str, pattern: str) -> None:
        """Extend the default pattern set (test + caller use)."""
        self._patterns.append((name, re.compile(pattern)))
```

Wire into `EpisodicMemory.store()` at `episodic.py:942` — append the security check after the existing AD-610 storage_gate block at `:948`–`:973`:

```python
# In store(), after the existing _storage_gate block:

# AD-607h: store-time prompt-injection detection
_security_gate = getattr(self, "_security_gate", None)
if _security_gate is not None:
    decision = _security_gate.evaluate_store(episode)
    if decision.matched_pattern:
        self._emit_security_event(EventType.MEMORY_INJECTION_SUSPECTED, {
            "episode_id": episode.id,
            "pattern": decision.matched_pattern,
            "reason": decision.reason,
        })
        if decision.action == "REJECT":
            logger.warning(
                "AD-607h: Episode %s rejected by memory security gate: %s",
                episode.id, decision.matched_pattern,
            )
            return
```

Add `EpisodicMemory.set_security_gate(gate)` setter mirroring `set_storage_gate()`. Initialize `self._security_gate = None` in `__init__` next to `self._storage_gate = None`.

**Tests** — class `TestPromptInjectionStoreGate` (~8 tests):

1. `test_store_clean_episode_passes` — normal user_input stored.
2. `test_store_ignore_previous_observational` — pattern matches, event emitted, episode still stored when `enforce_store=False`.
3. `test_store_ignore_previous_enforced_rejected` — `enforce_store=True` rejects the episode.
4. `test_store_role_swap_pattern_matches` — "you are now a different agent" detected.
5. `test_store_tool_spoof_pattern_matches` — "call tool: malicious_action" detected.
6. `test_store_system_prompt_leak_pattern_matches` — "what is your system prompt" detected.
7. `test_register_pattern_extends_default_set` — caller can add custom pattern.
8. `test_store_security_event_emitted_with_pattern_name` — event payload contains matched pattern name (NOT matched substring) per the AD-530 v1 audit-pattern convention.

## Section 9: AD-607j — `/security memory` slash subcommand

Implement `MemorySecurityRegistry` aggregator in `memory_security.py`:

```python
class MemorySecurityRegistry:
    """AD-607j: 24h sliding-window counter for the seven memory-security EventTypes."""

    def __init__(self, window_seconds: float = 86400.0) -> None:
        self._window = window_seconds
        self._events: list[tuple[float, str]] = []  # (timestamp, event_name)

    def record(self, event_name: str) -> None:
        import time as _time
        self._events.append((_time.time(), event_name))
        self._evict_old()

    def counts(self) -> dict[str, int]:
        self._evict_old()
        out: dict[str, int] = {}
        for _ts, name in self._events:
            out[name] = out.get(name, 0) + 1
        return out

    def _evict_old(self) -> None:
        import time as _time
        cutoff = _time.time() - self._window
        self._events = [(ts, name) for ts, name in self._events if ts >= cutoff]
```

Wire `runtime.memory_security_registry = MemorySecurityRegistry()` in startup; subscribe it to `EventBus` events for the seven new EventTypes via the existing event-subscription pattern.

Extend `cmd_security` at `src/probos/experience/commands/commands_status.py` with a `memory` subcommand (search for existing `cmd_security` in that file and append the dispatch branch — the AD-479i `/federation routing` precedent in `cmd_federation` is the structural template):

```python
# In cmd_security:
async def cmd_security(args: list[str], runtime: Any, ...) -> str:
    if args and args[0] == "memory":
        return await _render_security_memory(runtime)
    # ... existing /security subcommands preserved verbatim ...

async def _render_security_memory(runtime: Any) -> str:
    """AD-607j: /security memory subcommand — surfaces memory-security counters."""
    registry = getattr(runtime, "memory_security_registry", None)
    if registry is None:
        return "Memory security registry not available."
    counts = registry.counts()
    # render via existing panel pattern (panels.render_security_memory_panel — new)
    ...
```

**Tests** — class `TestSecurityMemorySlashCommand` (~6 tests):

1. `test_registry_record_increments_counter` — `record("memory_recall_anomaly")` shows count=1.
2. `test_registry_evicts_outside_window` — events older than `window_seconds` removed by `counts()`.
3. `test_registry_multiple_event_types_distinct_counters` — different event names tracked separately.
4. `test_security_memory_subcommand_returns_counts` — `/security memory` returns formatted output with the 7 counters.
5. `test_security_memory_subcommand_no_registry_graceful` — runtime without registry returns explanation, no crash.
6. `test_existing_security_subcommands_preserved` — `/security` (no arg) + any prior `/security <subcmd>` calls untouched.

## Section 10: Tracker updates (Builder must complete before commit)

**A. `PROGRESS.md`** — line 2 test count flips from 11963 to whatever Builder ships at ≥ 12035.

**B. `docs/development/roadmap.md:5266`–`:5278` AD-607 entry** — flip from `*(planned, OSS)*` to `*(complete, OSS)*` and append:

```
**AD-607: Memory Security Framework — Extraction & Poisoning Defense** *(complete, OSS, depends: AD-568a Source Governance, AD-589 IntrospectiveFaithfulness, AD-462c Oracle, AD-441 DID identity, AD-479 Federation Hardening, AD-610 storage-gate slot)* — Three-layer defense framework (retrieval / response / privacy) shipped in Wave 92 across ten sub-AD letters. AD-607a `validate_recall_result` anomaly gate at `EpisodicMemory.recall()` + `recall_by_anchor_scored()` + `OracleService._query_episodic()`; AD-607b `validate_provenance` integrity check; AD-607c `score_anchor_mismatch` content-anchor mismatch detection; AD-607d `check_memory_leakage` response-based guard alongside AD-589 IntrospectiveFaithfulness; AD-607e `MemoryAccessPolicy` enum + cross-shard access control on `OracleService.query`; AD-607f federated-recall inbound sanitization on `FederationRecallAgent`; AD-607g federated-recall outbound privacy filter via `FederationConfig.memory_access_policy`; AD-607h store-time prompt-injection detection mirroring AD-610 storage-gate slot; AD-607i `aggregate_with_dp` differential-privacy aggregator; AD-607j `/security memory` slash subcommand. Seven new EventTypes. Three future sub-AD letters parked with forcing functions (607k ML-classifier, 607l TEE attestation, 607m cross-fleet privacy budget). All enforcement opt-in via `MemorySecurityConfig.enforce_*` flags (default-False).

**Issues:** #183 (AD-607).
```

**C. `decisions-era-4-evolution.md`** — append a new `### AD-607` section before AD-636 with the standard rationale (cite the survey Section 8 + roadmap.md:5266–:5278 source) + the ten-letter sub-AD breakdown + the three forcing-function future-AD letters + the three commercial carve-outs + verify-first footer.

**D. `prompts/wave-plan.yaml`** — append the W92 entry per the W91 precedent (id "92" + depends_on `["91"]` + dispatch_prompt + prompt_paths + issues_to_close [183] + status pending → done after build + the 600-word `notes:` block).

**E. `gh issue close 183`** with this canonical paragraph:

```
Closed by Wave 92 (AD-607 Memory Security Framework v1, +72 tests). 10 OSS sub-AD letters: validate_recall_result anomaly gate, provenance integrity check, anchor mismatch detection, response-based leakage guard, MemoryAccessPolicy on Oracle, federated-recall inbound sanitization, federated-recall outbound privacy filter, store-time prompt-injection detection, differential-privacy aggregator, /security memory slash subcommand. 7 new EventTypes. Three future sub-AD letters parked with forcing functions (607k ML-classifier on adversarial corpus, 607l TEE attestation on hosted platform, 607m cross-fleet privacy budget on cross-fleet ops). All enforcement opt-in (default-False) per the AD-695 default-False precedent.
```

## What this v1 does NOT change

- **AD-462c Oracle cross-shard recall default behavior** — `MemoryAccessPolicy.PERMISSIVE` is the default; existing callers see no change.
- **AD-589 IntrospectiveFaithfulness pipeline** — AD-607d slots alongside it as a sibling, not a replacement; the existing post-decision block continues unchanged.
- **AD-610 storage gate** — AD-607h adds a SEPARATE gate slot (`_security_gate` distinct from `_storage_gate`); no coupling between the two.
- **AD-530 ClassificationGate** — AD-607f reuses the existing `_DEFAULT_SENSITIVE_PATTERNS` read-only; no pattern-set mutation.
- **AD-541 MemorySource enum** — AD-607b validates against the existing enum values; no new sources added.
- **AD-479 federation transport (NATS / ZMQ / Mock)** — AD-607f/g extend the FederationRecallAgent surface, NOT the transport layer.
- **HXI / dashboard / canvas** — AD-607j slash command is the only operator surface; no canvas changes.
- **Existing test fixtures** — Builder does NOT modify existing test fixtures except where W92-3 hard-stop conditions force a fixture-quality fix on `test_ad479_federation_hardening.py` (provenance-complete fixture episodes).

## Acceptance Criteria

1. New module `src/probos/cognitive/memory_security.py` exists with all eight public functions/classes (validate_recall_result, validate_provenance, score_anchor_mismatch, check_memory_leakage, aggregate_with_dp, MemoryAccessPolicy, MemorySecurityGate, MemorySecurityRegistry).
2. `tests/test_ad607_memory_security.py` contains all ten test classes per Sections 1–9; each class has the listed test count (±1).
3. Seven new EventTypes added to `events.py` per Section 0; collision check passes.
4. `MemorySecurityConfig` Pydantic model wired into `SecurityConfig` at `config.py:1687`; all four `enforce_*` defaults are False.
5. `MemoryConfig.access_policy` field default = "permissive"; `FederationConfig.memory_access_policy` default = "shared_trust"; both have field_validators rejecting invalid values.
6. `EpisodicMemory.set_security_config()` + `set_security_gate()` setters added; `_security_config` + `_security_gate` slots initialized to `None` in `__init__`.
7. `OracleService.query()` accepts `caller_sovereign_id` + `access_policy` kwargs; default behavior preserved for callers that don't pass them.
8. `FederationRecallAgent.act()` runs inbound sanitization unconditionally + outbound privacy filter per `FederationConfig.memory_access_policy`.
9. `cmd_security` extended with `memory` subcommand surfacing 7-counter output; existing subcommands preserved.
10. Pytest count ≥ 12035 (+72 floor over baseline 11963).
11. Full parallel gate `pytest tests/ -q -n 4 --dist=loadfile` passes with zero new failures.
12. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
13. `gh issue close 183` with the canonical paragraph in Section 10E.
14. Pre-commit-hook simulation `Select-String -Path src/probos/cognitive/memory_security.py, src/probos/config.py, src/probos/agents/federation_recall_agent.py, src/probos/cognitive/oracle_service.py, src/probos/cognitive/episodic.py, src/probos/cognitive/cognitive_agent.py, src/probos/events.py, src/probos/experience/commands/commands_status.py, tests/test_ad607_memory_security.py -Pattern <pattern> -SimpleMatch` returns zero hits per banned pattern.

## Verified Against Codebase (2026-05-07, HEAD `255c52a`)

```
grep -n "async def recall" src/probos/cognitive/episodic.py
  1508: async def recall(self, query: str, k: int = 5) -> list[Episode]:

grep -n "async def store" src/probos/cognitive/episodic.py
  942: async def store(self, episode: Episode) -> None:

grep -n "_storage_gate = getattr" src/probos/cognitive/episodic.py
  948: _storage_gate = getattr(self, "_storage_gate", None)

grep -n "async def recall_by_anchor" src/probos/cognitive/episodic.py
  1610: async def recall_by_anchor_scored(
  2584: async def recall_by_anchor(

grep -n "async def query" src/probos/cognitive/oracle_service.py
  268: async def query(

grep -n "async def _query_episodic" src/probos/cognitive/oracle_service.py
  541: async def _query_episodic(

grep -n "class FederationRecallAgent" src/probos/agents/federation_recall_agent.py
  23: class FederationRecallAgent(BaseAgent):

grep -n "async def act" src/probos/agents/federation_recall_agent.py
  60: async def act(self, plan: dict[str, Any]) -> IntentResult:

grep -n "def classify_retrieval_strategy" src/probos/cognitive/source_governance.py
  60: def classify_retrieval_strategy(

grep -n "def check_faithfulness" src/probos/cognitive/source_governance.py
  419: def check_faithfulness(

grep -n "class ClassificationGate" src/probos/security/classification.py
  64: class ClassificationGate:

grep -n "_DEFAULT_SENSITIVE_PATTERNS" src/probos/security/classification.py
  56: _DEFAULT_SENSITIVE_PATTERNS: tuple[tuple[str, str], ...] = (

grep -n "class Episode" src/probos/types.py
  439: class Episode:

grep -n "class MemoryConfig" src/probos/config.py
  601: class MemoryConfig(BaseModel):

grep -n "class FederationConfig" src/probos/config.py
  872: class FederationConfig(BaseModel):

grep -n "class SecurityConfig" src/probos/config.py
  1687: class SecurityConfig(BaseModel):

grep -n "MEMORY_REFS_DISPATCHED" src/probos/events.py
  243: MEMORY_REFS_DISPATCHED = "memory_refs_dispatched"  # AD-462f

grep -n "MEMORY_RECALL_ANOMALY|MEMORY_PROVENANCE_GAP|MEMORY_ANCHOR_MISMATCH|MEMORY_LEAK_SUSPECTED|MEMORY_INJECTION_SUSPECTED|FEDERATION_EPISODE_REJECTED|FEDERATION_RECALL_DP_REDACTED" src/probos/events.py
  (no matches — collision-free)

grep -n "async def recall_for_agent" src/probos/cognitive/episodic.py
  1755: async def recall_for_agent(self, agent_id: str, query: str, k: int = 5) -> list[Episode]:

grep -n "anchor_dimension_weights" src/probos/config.py
  642: anchor_dimension_weights: dict[str, float] = {
```

All 16+ grep-anchored claims confirmed at HEAD `255c52a`. Substrate exists; AD-607 v1 is "ship the security overlay above the existing memory + federation surfaces", not "ship the surfaces themselves".
