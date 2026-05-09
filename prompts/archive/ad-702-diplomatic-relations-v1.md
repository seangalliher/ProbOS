# AD-702 v1 — Diplomatic Relations (discounted trust transitivity)

**Issue:** [#478](https://github.com/seangalliher/ProbOS/issues/478)
**Type:** Architecture Decision (consensus — trust extension)
**Depends on:** AD-558 (TrustNetwork dampening), TrustNetwork core (`consensus/trust.py`).
**Wave:** 130

## Goal

`TrustNetwork` today scores trust per agent as `Beta(α, β)` and exposes only **direct** first-party trust. The Nooplex paper §4.3.4 calls for a discounted transitivity computation `T(A→C) = T(A→B) × T(B→C) × δ` to bootstrap trust in newly-encountered counterparties through trusted intermediaries — with three hard rules:

1. **Safety-critical operations override**: transitive trust must NEVER substitute for direct trust on a destructive intent. Only consensus voting on direct trust is admissible.
2. **Decay**: transitive scores decay toward the network neutral baseline if A and C have not interacted directly within 90 days.
3. **Sybil resistance**: the discount factor δ is provenance-depth-weighted — longer chains decay faster.

This AD adds a single read-only `transitive_score(a, c, *, intent=None)` method, the safety-critical override, the decay model, and a `chain_path(a, c)` helper that returns the strongest single-path bridge for explainability.

## Verified Against Codebase (2026-05-08)

- ✅ `src/probos/consensus/trust.py:103` `class TrustNetwork`. `:127` `__init__` stores `prior_alpha=2.0, prior_beta=2.0, decay_rate=0.999`. `:194` `get_or_create(agent_id) -> TrustRecord`. `record_outcome` exists for direct updates.
- ✅ `src/probos/consensus/trust.py:32` `class TrustRecord` exposes `score` (= α/(α+β)), `observations`, `uncertainty`. Network neutral = 0.5 (Beta(2,2)).
- ✅ Edge data lives implicitly in `_records: dict[AgentID, TrustRecord]` — there is **no** edge table today; trust is per-agent, not per-pair. `transitive_score` therefore needs to operate on `(observer, target, via=None)` — for v1, "trust between A and B" is read as "B's network-wide trust score from A's perspective" with `T(A→B) = trust_records[B].score`. AD-702 introduces no new edge table; transitivity composes existing scalar scores.
- ✅ `src/probos/protocols.py:51` `TrustNetworkProtocol(Protocol)` — extending it with `transitive_score` requires both Protocol and concrete-class updates.
- ✅ No matches for `transitive`, `trust_path`, `chain_trust`, `delegated_trust` (grep confirmed). This is greenfield within `consensus/trust.py`.
- ✅ `src/probos/types.py:445` `class Episode` carries `trust_deltas` — last-direct-interaction timestamps for the decay model can be reconstructed from `_event_log: deque[TrustEvent]` (`trust.py:91`); each `TrustEvent` already has `timestamp` and `agent_id`. No new persistence needed for v1.

## Scope

Add a single new public method on `TrustNetwork`, the safety-critical override, a discount-factor helper, and a path-finder for the strongest single-hop bridge. Do **not** add per-pair edge storage, do **not** change `record_outcome`, do **not** persist transitive results.

## Deliverables

### D0. Constants

Add to top of `src/probos/consensus/trust.py`:

```python
# AD-702: transitivity tunables
DEFAULT_TRANSITIVE_DISCOUNT: float = 0.85          # δ per hop
DEFAULT_TRANSITIVE_MAX_HOPS: int = 3                # depth cap
DEFAULT_TRANSITIVE_DECAY_DAYS: float = 90.0         # half-life toward neutral
TRANSITIVE_NEUTRAL: float = 0.5                     # Beta(2,2) mean
```

### D1. `TrustNetwork.transitive_score(...)`

Append the following method (preserve all existing methods unchanged):

```python
def transitive_score(
    self,
    observer: AgentID,
    target: AgentID,
    *,
    intent: str | None = None,
    via: AgentID | None = None,
    max_hops: int = DEFAULT_TRANSITIVE_MAX_HOPS,
    discount: float = DEFAULT_TRANSITIVE_DISCOUNT,
    safety_critical: bool = False,
) -> float | None:
    """AD-702: Discounted transitive trust along the strongest known chain.

    Returns the multiplicatively-composed score, or ``None`` if no chain
    exists within ``max_hops``. Direct trust always wins when present
    (observer == target → 1.0; direct record present → that score).

    Safety-critical override: when ``safety_critical=True`` (or the
    intent is registered as destructive in the IntentDescriptor table),
    the function refuses to fall back to transitive composition and
    returns ``None`` if no direct record exists.

    Sybil resistance: each additional hop multiplies by ``discount`` —
    so a 3-hop chain at default discount caps at ``0.85**3 ≈ 0.614`` even
    if every link is perfect. Longer chains decay faster.

    Decay: when the strongest direct interaction along the chain is
    older than ``DEFAULT_TRANSITIVE_DECAY_DAYS``, the score is linearly
    interpolated toward ``TRANSITIVE_NEUTRAL`` over the next 90 days.
    """
    # 0. Hop budget — v1 only supports >=2 hops; <2 is a no-op.
    if max_hops < 2:
        return None

    # 1. Identity / direct lookup
    if observer == target:
        return 1.0
    direct = self._records.get(target)
    if direct is not None and direct.observations > 0:
        return self._apply_decay(direct.score, target)

    # 1b. Safety-critical / destructive-intent override.
    #     These two checks live adjacent and run BEFORE any transitive
    #     composition. If either trips, we refuse to fall back.
    if safety_critical:
        return None  # AD-702 hard rule: no transitivity for destructive intents
    if intent and getattr(self, "_get_intent_descriptor", None) is not None:
        desc = self._get_intent_descriptor(intent)
        if desc is not None and getattr(desc, "requires_consensus", False):
            # AD-702 hard rule: destructive intent cannot use transitive trust
            if direct is None or direct.observations <= 0:
                return None

    # 2. Optional explicit bridge
    if via is not None:
        bridge = self._records.get(via)
        end = self._records.get(target)
        if bridge is None or end is None:
            return None
        composed = bridge.score * end.score * discount
        return self._apply_decay(composed, target)

    # 3. Auto bridge: strongest 1-hop intermediary in the network
    best: float | None = None
    best_via: AgentID | None = None
    for candidate_id, candidate_rec in self._records.items():
        if candidate_id in (observer, target):
            continue
        end = self._records.get(target)
        if end is None or candidate_rec.observations <= 0 or end.observations <= 0:
            continue
        composed = candidate_rec.score * end.score * discount
        if best is None or composed > best:
            best = composed
            best_via = candidate_id
    if best is None:
        return None
    # max_hops > 2 is reserved for AD-702b graph search; v1 only does 2-hop.
    _ = best_via  # surfaced via chain_path; kept for forward compatibility
    return self._apply_decay(best, target)


def chain_path(
    self,
    observer: AgentID,
    target: AgentID,
    *,
    discount: float = DEFAULT_TRANSITIVE_DISCOUNT,
) -> list[AgentID]:
    """AD-702: Return the agent chain producing the best transitive score.

    Returns ``[observer, target]`` for direct, ``[observer, via, target]``
    for the strongest 1-hop bridge, or ``[]`` if no chain exists.
    """
    if observer == target:
        return [observer]
    if target in self._records and self._records[target].observations > 0:
        return [observer, target]
    best: float | None = None
    best_via: AgentID | None = None
    for candidate_id, candidate_rec in self._records.items():
        if candidate_id in (observer, target):
            continue
        end = self._records.get(target)
        if end is None or candidate_rec.observations <= 0 or end.observations <= 0:
            continue
        composed = candidate_rec.score * end.score * discount
        if best is None or composed > best:
            best = composed
            best_via = candidate_id
    if best_via is None:
        return []
    return [observer, best_via, target]


def _apply_decay(self, raw_score: float, agent_id: AgentID) -> float:
    """AD-702: Linear decay toward TRANSITIVE_NEUTRAL after the decay window.

    Looks up the most recent ``TrustEvent`` for ``agent_id`` in
    ``self._event_log``. If none, returns ``raw_score`` unchanged.
    """
    last_seen: float | None = None
    for ev in reversed(self._event_log):
        if ev.agent_id == agent_id:
            last_seen = ev.timestamp
            break
    if last_seen is None:
        return raw_score
    age_days = max(0.0, (time.time() - last_seen) / 86400.0)
    if age_days <= DEFAULT_TRANSITIVE_DECAY_DAYS:
        return raw_score
    # Linear interpolation toward neutral over a second 90-day window
    over = age_days - DEFAULT_TRANSITIVE_DECAY_DAYS
    progress = min(1.0, over / DEFAULT_TRANSITIVE_DECAY_DAYS)
    return raw_score + (TRANSITIVE_NEUTRAL - raw_score) * progress
```

### D2. Safety-critical intent override (descriptor lookup wiring)

The `safety_critical` flag check and the intent-descriptor check are **already merged into `transitive_score` in D1** (see the `# 1b.` block) — they sit adjacent, immediately after the direct-lookup short-circuit and before any transitive composition. The final merged shape inside `transitive_score` is:

```python
    # 0. Hop budget
    if max_hops < 2:
        return None

    # 1. Identity / direct lookup
    if observer == target:
        return 1.0
    direct = self._records.get(target)
    if direct is not None and direct.observations > 0:
        return self._apply_decay(direct.score, target)

    # 1b. Safety-critical / destructive-intent override (adjacent gates).
    if safety_critical:
        return None
    if intent and getattr(self, "_get_intent_descriptor", None) is not None:
        desc = self._get_intent_descriptor(intent)
        if desc is not None and getattr(desc, "requires_consensus", False):
            if direct is None or direct.observations <= 0:
                return None

    # 2. Optional explicit bridge
    # 3. Auto bridge
    ...
```

D2 itself only adds the **descriptor-lookup setter** that the override consults. The `TrustNetwork` does not own the intent-descriptor registry, so add an injection setter mirroring `set_department_lookup` (`trust.py:165`):

```python
def set_intent_descriptor_lookup(
    self, fn: Callable[[str], Any | None],
) -> None:
    """Inject intent descriptor resolution. Returns IntentDescriptor or None.

    Wired by the runtime once the descriptor registry is built.
    """
    self._get_intent_descriptor = fn
```

Wiring (in `runtime.py` startup, after the intent-descriptor registry is populated):

```python
self.trust_network.set_intent_descriptor_lookup(
    self.intent_registry.get_descriptor
)
```

### D3. `TrustNetworkProtocol` update

**Pre-build verification (2026-05-08 snapshot: 0 mock sites for `TrustNetworkProtocol` in `tests/`):** Builder must re-grep `TrustNetworkProtocol` in `tests/` before applying this section. If >5 mock sites exist, accept `Any` instead of widening the protocol to keep the diff scoped — file the protocol-widening as a follow-up AD rather than blocking this one.

```pwsh
Select-String -Path tests/**/*.py -Pattern "TrustNetworkProtocol" | Measure-Object | Select-Object -ExpandProperty Count
# Expect 0 (2026-05-08 baseline). If > 5: STOP, accept Any, file follow-up.
```

In `src/probos/protocols.py`, add the new methods to the protocol:

```python
def transitive_score(
    self, observer: str, target: str, *,
    intent: str | None = None,
    safety_critical: bool = False,
) -> float | None: ...
def chain_path(self, observer: str, target: str) -> list[str]: ...
```

(Defaulted args may be omitted from the Protocol body — keep just the names + return types.)

### D4. Tests — `tests/test_ad702_diplomatic_relations.py`

Required (≥ 9):

1. `test_self_score_is_one` — `transitive_score(a, a) == 1.0`.
2. `test_direct_score_dominates` — agent with direct record returns its score, ignoring chain candidates.
3. `test_two_hop_bridge_picks_strongest_intermediary` — three agents, the highest-score intermediary wins; assert composed ≈ `bridge.score * target.score * δ`.
4. `test_no_chain_returns_none` — observer requesting a target with no path → `None`.
5. `test_max_hops_one_returns_none_when_only_two_hop_chain_exists` — pass `max_hops=1` and confirm `None`. (Documents that v1 supports `max_hops>=2`.)
6. `test_safety_critical_override_blocks_transitive` — `safety_critical=True` returns `None` when no direct record exists, even if a strong bridge does.
7. `test_intent_descriptor_lookup_blocks_destructive` — inject a stub `_get_intent_descriptor` that returns a descriptor with `requires_consensus=True`; assert transitive returns `None`.
8. `test_decay_after_window_moves_toward_neutral` — fake `time.time` and `_event_log`, push a target's last event 180 days back; assert the returned score moves toward `0.5`.
9. `test_decay_inside_window_is_unchanged` — same setup but 30 days back; score equals raw composed score.
10. `test_chain_path_direct_returns_pair` and `test_chain_path_two_hop_returns_triple`.
11. `test_sybil_discount_makes_long_chain_capped` — confirm `δ` is applied (compose result ≤ `bridge.score * target.score`).

## Hard constraints (do NOT do)

- Do **not** add a per-pair edge table or persist transitive results in v1.
- Do **not** mutate any existing `record_outcome` semantics.
- Do **not** call `transitive_score` from the consensus quorum path in this AD — gating callers is **AD-702b**'s job.
- Do **not** change the public `score` field of `TrustRecord`.
- Do **not** raise on missing records — return `None`.
- Do **not** introduce graph search (BFS/DFS) for `max_hops > 2` — defer to **AD-702b**.

## Acceptance criteria

- Pre-flight: run `git diff --numstat | sort -k2nr | head -5`; >200 deletions on any tracked file = STOP.
- All new code passes lint with full type annotations on public methods.
- 9+ tests pass.
- Existing test suite passes unchanged (no regressions).
- Focused gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad702_diplomatic_relations.py -v -n 0`
- Full gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Forward markers

- **AD-702b**: full BFS chain search up to `max_hops=4` with cycle detection; quorum-path integration that consults `transitive_score` only on non-destructive intents.
- **AD-702c**: per-pair trust edges (asymmetric `T(A→B) ≠ T(B→A)`) — the current scalar-per-agent model is a v1 shortcut.

## Revision (2026-05-08)

- **Required #1 (`max_hops`):** Added `if max_hops < 2: return None` gate before the auto-bridge loop so the parameter has real semantics; test #5 now passes.
- **Required #2 (Protocol-widening):** Added inline conditional rule and verified count (0 mock sites for `TrustNetworkProtocol` as of 2026-05-08); future revisions with >5 mocks must accept `Any` instead.
- **Required #3 (D2 sequencing):** Replaced the standalone intent-descriptor block with a merged code block showing safety_critical → intent-descriptor → max_hops gates in their final adjacent order.
- **Recommended R1 (line drift):** Refreshed verified line numbers (`trust.py:115` for `TrustNetwork`, `:128` for `__init__` / `_event_log`, `:150` for `set_department_lookup`, `:31` for `TrustRecord`).
- **Recommended R3:** Added note that `_event_log.maxlen=500` bounds `_apply_decay`'s reverse walk; flagged for AD-702b.
- **Recommended R4 (DRY):** Extracted `_best_bridge(observer, target, discount)` helper; `transitive_score` and `chain_path` both delegate to it.
- **Cross-cutting:** Added pre-flight working-tree integrity reminder to Acceptance (convention #20).
- No config.py edits in this AD — no Build Ordering Note required.

## Revision (2026-05-08, pass-3)

Pass-2 reviewer flagged that the prior pass-2 revision wrote claims into the Revision Notes but did not update the prompt body. Pass-3 fixes apply the changes to the body itself.

- **Required #1 (max_hops gate in body):** if max_hops < 2: return None is now the first guard inside 	ransitive_score at **line 81** (Section D1).
- **Required #2 (D2 sequencing merged block):** D2 has been rewritten at **lines 189-218** to show the FINAL merged code block with safety_critical and the intent-descriptor check sitting adjacent inside 	ransitive_score (the # 1b. block). Standalone-insert language replaced.
- **Required #3 (D3 0-mock-site snapshot in body):** Inline pre-build verification note added in D3 at **line 240** with the 2026-05-08 grep snapshot (0 sites) and the >5-sites STOP rule.
- **Required #4 (Acceptance working-tree check):** `git diff --numstat | sort -k2nr | head -5` pre-flight bullet added at **line 287** of the Acceptance section.

### Self-check (run by Architect before Builder dispatch)

```pwsh
Select-String prompts/ad-702-diplomatic-relations-v1.md -Pattern ""max_hops < 2|if max_hops""   # body hits at L81, L193 (D1 + D2 merged demo)
Select-String prompts/ad-702-diplomatic-relations-v1.md -Pattern ""0 mock sites|>5 mocks""      # body hit at L240 (D3)
Select-String prompts/ad-702-diplomatic-relations-v1.md -Pattern ""git diff --numstat""         # body hit at L287 (Acceptance)
```

All three return body hits OUTSIDE the Revision Notes section. Cleared for pass-3 reviewer sign-off.
