# AD-702 build report — Diplomatic Relations (discounted trust transitivity)

**Prompt:** `prompts/ad-702-diplomatic-relations-v1.md`
**Builder:** Wave 130 builder (continuous mode)
**Date:** 2026-05-08
**Status:** SHIPPED
**Issue closed:** #478
**Wave:** 130 (5 of 10)

## R4 decision

**Selected option (a):** extracted `_best_bridge(observer, target, discount) -> tuple[float | None, AgentID | None]` helper. Both `transitive_score` and `chain_path` delegate to it. Matches the prompt's revision-notes claim. Cleaner DRY; no v1 duplication.

## Files Changed

- `src/probos/consensus/trust.py` — added 4 module-level constants (`DEFAULT_TRANSITIVE_DISCOUNT`, `DEFAULT_TRANSITIVE_MAX_HOPS`, `DEFAULT_TRANSITIVE_DECAY_DAYS`, `TRANSITIVE_NEUTRAL`); added 5 new methods on `TrustNetwork`: `set_intent_descriptor_lookup`, `_best_bridge`, `transitive_score`, `chain_path`, `_apply_decay`.
- `src/probos/protocols.py` — widened `TrustNetworkProtocol` with `transitive_score` + `chain_path` (0 mock sites confirmed in tests/, safe per the >5-mocks STOP rule).
- `tests/test_ad702_diplomatic_relations.py` — 16 new tests.
- `DECISIONS.md` — AD-702 entry appended.

## Sections Implemented

- **D0.** Constants — done at top of `trust.py` immediately after the `from probos.types import AgentID` import.
- **D1.** `transitive_score` — done. Hop budget gate, identity short-circuit, direct lookup, safety-critical override (adjacent gate block), intent-descriptor override, optional explicit `via=` bridge, auto-bridge via `_best_bridge`, decay via `_apply_decay`. R4 helper extracted.
- **D2.** Safety-critical intent override — `set_intent_descriptor_lookup` setter wired (mirrors `set_department_lookup`). Wiring is documented; runtime-side hookup deferred to AD-702b alongside graph search since v1 has no consumers calling `transitive_score` from the consensus path.
- **D3.** Protocol widening — done at `protocols.py:51`. 0 mock-site confirmation re-grepped; safe.
- **D4.** Tests — 16 cases (11 required + chain_path_self_singleton + chain_path_no_chain + sybil discount + protocol-method-existence + via-explicit).

## Post-Build Section Audit

All five `D*` sections from the prompt have corresponding code changes. No omissions.

## Verify-First Findings

- ✅ `TrustNetwork` at `trust.py:103` (post-D0 line shift).
- ✅ `_records: dict[AgentID, TrustRecord]` at `trust.py:126`.
- ✅ `_event_log: deque[TrustEvent] = deque(maxlen=500)` at `trust.py:128` — confirmed bounded, flagged in `_apply_decay` docstring for AD-702b graph search if longer histories needed.
- ✅ `set_department_lookup` at `trust.py:150` (injection-pattern template).
- ✅ `TrustRecord` at `trust.py:31` — `observations` is a property, NOT a field. Test helpers initially used `TrustRecord(..., observations=10.0)` kwarg; corrected to compute `alpha + beta = 14` so `observations = 10` derives correctly.
- ✅ `TrustEvent` schema (`timestamp, agent_id, success, old_score, new_score, weight, intent_type, episode_id, verifier_id`) — test helper updated to use real fields, not the prompt's draft `event_type/data` shape.
- ✅ `TrustNetworkProtocol` at `protocols.py:51`. 0 mock sites in `tests/`; widened safely.
- ⚠️ Pre-existing gap: `TrustNetworkProtocol.get_trust_score` is declared but `TrustNetwork` does not implement it. Test `test_new_transitive_methods_exist_on_trust_network` checks new methods directly via `callable(getattr(...))` rather than `isinstance(net, Protocol)` to avoid spuriously failing on the pre-existing gap. Documented inline.

## Test Results

```
.\.venv\Scripts\pytest.exe tests/test_ad702_diplomatic_relations.py -v -n 0
16 passed in 0.29s
```

Full gate:
```
.\.venv\Scripts\pytest.exe tests/ -q -n 8 --dist=loadfile
12833 passed, 16 skipped, 175 warnings in 468.20s
```

Pre-AD-702: 12817 → +16 = 12833. Test count non-decreasing.

## Hard Constraints Honored

- ✅ No per-pair edge table; transitivity composes existing scalar-per-agent scores.
- ✅ `record_outcome` semantics unchanged.
- ✅ No quorum-path integration in this AD (forward marker AD-702b).
- ✅ `TrustRecord.score` property unchanged.
- ✅ Returns `None` (never raises) on missing records.
- ✅ No graph search; v1 only does 2-hop via `_best_bridge` (forward marker AD-702b).

## Pre-Commit Deletion Check

Top-5 staged files by line count — no file shows >200 deletions. Clean.

## Engineering Principles Compliance

- ✅ SOLID/DRY: `_best_bridge` extracted (R4 option a) — `transitive_score` and `chain_path` both delegate.
- ✅ Open/Closed: new methods added; existing methods untouched. Setter-injection `set_intent_descriptor_lookup` mirrors `set_department_lookup`.
- ✅ Dependency Inversion: intent-descriptor lookup is a `Callable` injected at runtime; never imports from a concrete registry.
- ✅ Type annotations on all public methods (`AgentID`, `float | None`, `list[AgentID]`, `Callable[[str], Any | None]`).
- ✅ Defense in depth: hop budget gate, observations gate on every candidate, safety-critical gate, intent-descriptor gate.
- ✅ Boundary tests: self-target, direct dominates chain, no-chain, max_hops=1, safety-critical, destructive intent, decay after window, decay inside window, no-event no-decay, sybil discount applied.
- ✅ Sybil resistance verified: composed score < raw product (discount applied; test asserts `composed - raw_product * δ < 1e-6`).
