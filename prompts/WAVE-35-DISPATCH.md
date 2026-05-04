# Wave 35 Dispatch — AD-635 v1 Medical Diagnostic Data Access (Clinical Telemetry Query Facade)

**Status:** Pending
**Issue:** #231 (closes on merge)
**Prompt:** [`prompts/ad-635-medical-diagnostic-v1.md`](ad-635-medical-diagnostic-v1.md)
**Wave plan slot:** id="35" (already populated, status=pending)
**Predecessor:** Wave 34 (AD-647 v1 Process-Oriented Cognitive Chains, commit `7f9bff6`, gate 10957)
**Expected gate after build:** 10965 (+8)

---

## v1 Scope (one line)

A clearance-gated read-only `ClinicalTelemetryService` exposing **two** of the four data domains in #231 — **dream cycle history** and **cross-agent cognitive journal chain traces** — gated on FULL+ recall tier AND clinical agent_type, with bounded in-memory query audit.

**Deferred to AD-635b–f:** anomaly audit trail, circuit breaker history, REST endpoints, shell command, proactive injection, audit log persistence.

## Dependencies — Verify-First Findings (HEAD `7f9bff6`)

| Dep | Status | Used in v1? |
|---|---|---|
| AD-588 (introspective telemetry) | Shipped (`introspective_telemetry.py`); pattern reference only | NO direct consumption |
| AD-620 (RecallTier + billet clearance) | Shipped (`earned_agency.py:55-59`, `:131`) | YES — `effective_recall_tier`, `resolve_billet_clearance` |
| AD-621 (channel membership) | Shipped | NO — clearance-gating only |
| AD-622 (ClearanceGrant) | Shipped (`earned_agency.py:73`, `clearance_grants.py`) | YES — `resolve_active_grants` |
| AD-658 (chain_traces table + `get_recent_chain_traces`) | Shipped (`journal.py:335`) | YES — cross-agent query already supports `agent_id=` filter |
| `EmergentDetector._dream_history` | Shipped (`emergent_detector.py:196`, private) | YES — surfaced via new public `recent_dreams()` accessor |
| `runtime._emergent_detector` | Private (`runtime.py:1496`); no public property | YES — `getattr` fallback (Demeter follow-up tracked AD-635-cleanup) |

Zero `ClinicalTelemetry*` symbols in src today — fully greenfield.

## Decision: Clearance Gate

**FULL+ AND clinical role.** Implementation reuses the existing helper trio (`effective_recall_tier`, `resolve_billet_clearance`, `resolve_active_grants` — same pattern as `cognitive_agent.py:4958`):

- `agent_type ∈ CLINICAL_ROLES = {"diagnostician", "counselor"}` (module-level frozenset).
- Effective tier ∈ `QUALIFYING_TIERS = {RecallTier.FULL, RecallTier.ORACLE}` (module-level frozenset).

Verified against live ontology (`config/ontology/organization.yaml`):
- `agent_type: diagnostician` (line 350) → post `chief_medical` (line 227) → clearance `FULL` (line 233). Chapel ✓
- `agent_type: counselor` (line 334) → post `counselor` (line 53) → clearance `ORACLE` (line 59). Echo ✓

Both billets satisfy the gate without rank/grant boost. Rank lookup via `runtime.acm.get(agent_id)` is included with graceful None fallback so the service still authorizes correctly when `acm` is unset (test stub uses `acm=None`).

## Public Accessor on the Owner

`EmergentDetector.recent_dreams(limit: int = 20) -> list[dict]` is added on the OWNER (Open/Closed). Consumers (here: `ClinicalTelemetryService`) do not reach into the private `_dream_history` deque. Returns a fresh list each call (mutation isolation).

## Phantom-API Pre-Check

Ran `scripts/phantom-api-precheck.ps1` against the prompt:

```
=== prompts/ad-635-medical-diagnostic-v1.md ===
  1 phantom symbol(s):
    - [<Class>(...)] class:SimpleNamespace
  Skipped (unresolved class):
    ~ [pattern_b_reassignment] det.recent_dreams(...) (obj=det)
```

**Both are documented false positives:**
- `class:SimpleNamespace` — stdlib `types.SimpleNamespace`, used in test fixtures. Same FP class as Waves 28/30/31/32/33/34.
- `det.recent_dreams(...)` skipped — introduced BY this prompt in Section 2. Correctly identified by the script as intra-prompt-introduced.

**0 NEW phantoms.** Same intro-not-in-index + stdlib FP class as Waves 27-34.

## Test Plan (8 over 7 floor by 1)

1. `test_service_shape_and_module_constants` — service exposes the two query methods + `audit_log` snapshot; `CLINICAL_ROLES` and `QUALIFYING_TIERS` frozensets are correct; audit deque is bounded.
2. `test_authorized_dream_query_returns_results` — counselor (ORACLE) gets dream rows; audit `granted=True`, `query_type="dream_history"`.
3. `test_unauthorized_dream_query_returns_empty` — non-clinical agent_type returns `[]`; warning logged with `AD-635` tag; audit `granted=False`.
4. `test_authorized_chain_traces_passes_target_agent_id` — diagnostician (FULL) cross-agent query: journal called with `agent_id=target`; audit includes `target_agent_id`.
5. `test_unauthorized_chain_traces_returns_empty` — unknown registry entry: `[]`; journal NOT awaited; audit `granted=False`.
6. `test_chain_traces_journal_failure_log_and_degrade` — journal raises `RuntimeError`: `[]` returned; warning logged; audit `granted=True, result_count=0`.
7. `test_audit_ring_is_bounded` — `audit_max_entries=3` + 5 calls → ring evicts oldest, `len(audit_log) == 3`.
8. `test_emergent_detector_recent_dreams_accessor` — accessor returns most-recent N (FIFO); `limit=99` returns full snapshot; `limit=0` returns `[]`; mutation isolation.

Plus `test_wirer_creates_runtime_attribute_when_enabled_and_no_op_when_disabled` — paired wirer test in same file (effective 9 tests, but the brief calls for ≥7; if Builder finds count drift, the wirer test is the natural drop candidate).

Test count baseline 10957 (Wave 34) → expected 10965 (+8 exact).

## Build Quality Reminders

- **Property collision (Wave 32 retrospective).** `ClinicalTelemetryService` is NOT a `CognitiveAgent` subclass — the `cognitive_journal` property trap does not apply. Documented in Section 0 of the prompt for future consumers.
- **Default-False per Wave 10 transitional-flag convention.** `ClinicalTelemetryConfig.enabled = False` — service is invisible until Captain opts in via YAML.
- **`runtime._emergent_detector` is private.** Wirer reads via `getattr(runtime, "_emergent_detector", None)` exactly like `dream_adapter.py:65`. Public `runtime.emergent_detector` property is OUT OF SCOPE — track as `AD-635-cleanup` follow-up nit.
- **Authorization helper is internal-only.** `_authorize_clinical_query` does not raise — every failure path returns `False` and the calling query method records `granted=False` in audit before returning `[]`.
- **Test stub uses `acm=None`.** Authorization succeeds via billet alone; rank fallback is exercised but not the primary path.

## Out of Scope (Hard Limits)

| Out | Where it lives next |
|---|---|
| Consolidation anomaly audit trail (no shipped substrate) | AD-635b |
| Circuit breaker state history (no trip-history persistence today) | AD-635c |
| REST endpoints `/api/clinical/*` | AD-635d |
| Shell command `/clinical` or `/medbay` | AD-635e |
| Proactive context injection for clinical agents (AD-630 parallel) | AD-635f |
| Audit log persistence to SQLite | AD-635b |
| Public `runtime.emergent_detector` property | AD-635-cleanup |
| New EventType on query | future |
| Counselor / Diagnostician auto-invocation hooks | AD-635f |
| HXI surface for clinical telemetry | future |

## Success Criteria

1. Full parallel gate green at `pytest tests/ -q -n 8 --dist=loadfile`.
2. Test-count delta exactly +8 vs baseline 10957 → 10965.
3. `runtime.clinical_telemetry` is `None`/absent in default config (out-of-box no-op); `ClinicalTelemetryService` instance present when `clinical_telemetry.enabled=True`.
4. PROGRESS.md flipped from `AD-635 SCOPED` to `AD-635 v1 CLOSED`.
5. `docs/development/roadmap.md` AD-635 entry status flipped.
6. DECISIONS.md AD-635 entry appended with v1 closure line (no rewrite).
7. Issue #231 closed on merge.
