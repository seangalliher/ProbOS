# WAVE 64 DISPATCH — AD-635d v1 Clinical Telemetry: REST Endpoints

**Wave id:** 64
**Single AD:** AD-635d
**Closes:** #393
**Baseline test count:** 11351 (HEAD `27fd14f`, post-Wave-63) → expected **11365** (+14 net), ceiling **+18**
**HEAD at draft:** `27fd14f`, working tree clean
**Builder:** required

## Summary

AD-635 v1 (Wave 60) shipped `ClinicalTelemetryService` as an in-process query facade with two data domains (dream history + agent chain traces), a clearance gate, and an in-memory audit ring. AD-635b (Wave 62) added optional SQLite persistence of the audit ring. AD-635c (Wave 63, just landed) added circuit-breaker state-and-zone history as a third data domain with its own SQLite store. **All three data domains are reachable today only via direct in-process calls** — no HTTP surface, no external operator interface, no HXI integration path.

The roadmap entry at `docs/development/roadmap.md:5962` defines the AD-635d scope precisely:

> *"REST API routes for clinical telemetry queries gated by clearance resolution. Endpoints: `GET /api/clinical/dreams`, `GET /api/clinical/chain-traces/{agent_id}`, `GET /api/clinical/circuit-breakers/{agent_id}`, `GET /api/clinical/audit`. Depends on: AD-635 v1 (COMPLETE). Related: AD-456 (audit layer)."*

Verified at HEAD `27fd14f`:

```
src/probos/cognitive/clinical_telemetry.py:65    class ClinicalTelemetryService
src/probos/cognitive/clinical_telemetry.py:93    async def query_dream_history(*, requester_agent_id, limit=20) -> list[dict]
src/probos/cognitive/clinical_telemetry.py:139   async def query_agent_chain_traces(*, requester_agent_id, target_agent_id, limit=20) -> list[dict]
src/probos/cognitive/clinical_telemetry.py:206   @property def audit_log(self) -> list[dict]   (snapshot list copy)
src/probos/cognitive/clinical_telemetry.py:211   async def query_circuit_breaker_history(*, requester_agent_id, target_agent_id=None, limit=50) -> list[dict]
src/probos/cognitive/clinical_telemetry.py:284   def _authorize_clinical_query(self, agent_id) -> bool   (already deny-by-default)
src/probos/startup/finalize.py:598               runtime.clinical_telemetry = service   (only assigned when cfg.enabled)
src/probos/api.py:191                            from probos.routers import (..., counselor, procedures, gaps, ...)
src/probos/api.py:208                            app.include_router(r.router)
src/probos/routers/deps.py:13                    def get_runtime(request) -> ProbOSRuntime
src/probos/routers/diagnostic_context.py         class-shape reference (small async router with HTTPException 503 fallback)
src/probos/routers/chain_traces.py               class-shape reference (read-only journal pass-through)
src/probos/routers/counselor.py                  class-shape reference (multi-route router with TestClient harness)
tests/test_ad561_intervention_classification.py:240+   FastAPI TestClient + dependency_overrides[get_runtime] reference harness
DECISIONS.md (highest AD)                         AD-695 — AD-635d is unique
PROGRESS.md baseline                              11351 tests collected (post-Wave-63)
docs/development/roadmap.md:5962                 AD-635d *(Scoped, OSS, Issue #393)*
```

**The gap closed by AD-635d:** the three clinical data domains exist but are reachable only by Python code holding a `ClinicalTelemetryService` reference. Operators cannot inspect dream history, chain traces, breaker history, or the audit trail from outside the runtime process. The HXI cannot render clinical views. AD-635e (the `/clinical` shell command) and AD-635f (proactive context injection) are blocked on this surface.

AD-635d v1 ships **one new router** with **four GET endpoints** that are thin pass-throughs over the existing `ClinicalTelemetryService` public surface:

1. `GET /api/clinical/dreams?requester_agent_id=...&limit=20` → `query_dream_history(...)`
2. `GET /api/clinical/chain-traces/{agent_id}?requester_agent_id=...&limit=20` → `query_agent_chain_traces(target_agent_id=agent_id, ...)`
3. `GET /api/clinical/circuit-breakers/{agent_id}?requester_agent_id=...&limit=50` → `query_circuit_breaker_history(target_agent_id=agent_id, ...)`
4. `GET /api/clinical/audit?limit=200` → `audit_log` property snapshot, sliced server-side to the last `limit` entries.

No new EventTypes. No mutation of `ClinicalTelemetryService`, `CircuitBreakerHistoryStore`, `ClinicalAuditStore`, `CognitiveCircuitBreaker`, `ClinicalTelemetryConfig`, `ProactiveCognitiveLoop`, or `_authorize_clinical_query`. No new wiring in `startup/finalize.py` (the router is registered statically at app construction in `api.py`). No HXI / TypeScript edits in this AD — the HXI consumer for these endpoints lands in a follow-up AD when the panel work is scheduled.

Source-edit files: `src/probos/routers/clinical.py` (NEW, ~120 lines), `src/probos/api.py` (additive — extend the existing router-import tuple and include-router loop, two SEARCH/REPLACE blocks of ≤8 lines each).

**Deferred at the prompt level:**
- AD-635d-1 — REST authentication / impersonation guard. v1 trusts the `requester_agent_id` query parameter at face value (ProbOS REST is currently unauthenticated end-to-end across every router; same threat model as `/api/counselor/profiles`, `/api/journal`, etc.). Hardening clinical specifically is its own AD; ships when the broader REST auth story (deferred from AD-516) lands.
- AD-635d-2 — fleet-wide breaker-history endpoint. The underlying `query_circuit_breaker_history(target_agent_id=None)` branch is reachable in-process; the REST surface in v1 follows the roadmap line literally and exposes only the per-agent path. v2 adds `GET /api/clinical/circuit-breakers` (no path param).
- AD-635d-3 — `since` lower-bound query parameter on dreams / chain-traces / breaker / audit. v1 uses `limit` only; matches the underlying service surface.
- AD-635d-4 — pagination cursors for the audit endpoint. v1 returns the last `limit` entries from the in-memory ring (max 1000 by default).
- AD-635d-5 — *(Commercial)* tenant-scoped routing (per-mesh clinical routers behind a tenant header). The OSS router is the seam; commercial overlay swaps the runtime resolver.

## Architect calls (Decision Log)

- **DLog #1 — `requester_agent_id` is a REQUIRED query parameter, NOT a header, NOT impersonated, NOT defaulted.** FastAPI auto-422s when a non-default `str` query parameter is missing — that's the contract we want. A header (`X-Requester-Agent-Id`) would silently default-to-None and yield a 200 with an empty body for every unauthenticated caller (denial-of-service-by-confusion smell). A query parameter is grep-able in HTTP logs for audit. The clearance gate inside `_authorize_clinical_query` is the actual security control; the REST layer is a thin shape-converter. Tests #2 / #6 / #10 lock the 422-on-missing contract.

- **DLog #2 — Service-unavailable maps to HTTP 503, NOT 404.** When `runtime.clinical_telemetry` is missing or None (the default config — `cfg.enabled=False`), every endpoint returns 503 with `{"error": "Clinical telemetry not available"}`. Mirrors `/api/counselor/profiles` precedent (`routers/counselor.py:23` returns 503 when the profile store is missing). 404 is reserved for "valid endpoint, no row matched" semantics, which we don't have here. Tests #3 / #7 / #11 / #14 lock the 503 path.

- **DLog #3 — Clearance denial returns 200 with `[]`, NOT 401/403.** The underlying `query_*` methods already return `[]` on denial AND log the audit-ring entry with `granted=False`. Mapping this to a 4xx would (a) leak whether the requester exists, (b) require duplicating the clearance gate at the REST layer (DRY violation), and (c) drop the audit-ring write (since the gate's `_record_audit(..., granted=False)` already fires inside the service). The REST endpoint is a thin shape-converter; the service IS the gate. Tests #4 / #8 / #12 lock the 200-with-`[]` path AND assert the audit ring captured the `granted=False` entry.

- **DLog #4 — `audit_log` endpoint is NOT clearance-gated at the REST layer.** The `audit_log` property has no clearance gate today (it's a public snapshot accessor — see `clinical_telemetry.py:206`). Adding one purely at the REST boundary would diverge from the in-process contract. The AD-635d-1 deferral covers REST-layer authentication for the entire clinical surface uniformly; per-endpoint policy divergence belongs there, not here. Test #15 locks the unauthenticated-success path.

- **DLog #5 — The `audit` endpoint applies `limit` server-side as `audit_log[-limit:]`.** The in-memory ring is bounded by `audit_max_entries` (default 1000). The endpoint's `limit` parameter slices the most-recent `limit` entries (the ring is append-most-recent-last, mirroring `clinical_telemetry.py:362` ordering). Hard-cap at 1000 (matching the default audit ring size) to prevent unbounded slice on tuned configs. Test #16 locks the slice direction; test #17 locks the hard-cap clamp.

- **DLog #6 — Path-param-only `{agent_id}` on chain-traces and circuit-breakers, matching the roadmap line literally.** The roadmap explicitly says `/api/clinical/chain-traces/{agent_id}` and `/api/clinical/circuit-breakers/{agent_id}` — both treat `agent_id` as a required path component. The underlying `query_agent_chain_traces` requires a non-None `target_agent_id`; the underlying `query_circuit_breaker_history` accepts None for fleet-wide queries, but exposing that on the REST surface in v1 would diverge from the roadmap line. AD-635d-2 covers the fleet-wide breaker endpoint as a follow-up. Single-source-of-truth: the roadmap entry is the spec.

- **DLog #7 — `limit` query parameter clamping mirrors AD-658 / AD-661 precedent.** `chain_traces.py:30` uses `min(max(limit, 1), 500)` — that's the established shape. AD-635d uses the same `min(max(limit, 1), <cap>)` idiom: dreams cap 100, chain-traces cap 500, breakers cap 500, audit cap 1000. Caps are conservative and follow the underlying service's natural ceiling (audit ring default = 1000; breaker / chain-trace stores are paginated by limit alone). Tests #5 / #9 / #13 / #17 lock the clamp.

- **DLog #8 — Static route registration in `api.py`, not dynamic.** The router is imported and registered at app-construction time via the existing tuple at `api.py:191-208`. No conditional include — the router itself returns 503 when the service is missing (per DLog #2), which is the right shape for FastAPI: callers always discover the route in the schema; whether it serves data is a runtime concern. Mirrors every other clinical-adjacent router (`counselor`, `chain_traces`, `diagnostic_context`).

- **DLog #9 — Router is `prefix="/api/clinical"`, `tags=["clinical"]`.** Mirrors `routers/counselor.py:15` (`prefix="/api/counselor"`, `tags=["counselor"]`). The four endpoints live on relative paths: `""`, `"/dreams"`, `"/chain-traces/{agent_id}"`, `"/circuit-breakers/{agent_id}"`, `"/audit"`. Wait — five paths but four endpoints: there is no root `""` endpoint in v1; only the four roadmap-named paths. (AD-635d-6 deferral: index endpoint listing available domains. Not in v1.)

- **DLog #10 — Test harness uses `FastAPI` + `TestClient` + `dependency_overrides[get_runtime]`.** Identical pattern to `tests/test_ad561_intervention_classification.py:60-64`. A `_FakeClinicalTelemetryService` stub class implements the four needed methods (`query_dream_history`, `query_agent_chain_traces`, `query_circuit_breaker_history`, `audit_log`). A `_FakeRuntime` exposes `clinical_telemetry` as either the stub or `None`. No `runtime` fixture, no startup wiring, no real `ProbOSRuntime` boot. Tests #1-#18 all use this harness.

- **DLog #11 — No EventType additions.** REST is a transport concern. The `_record_audit` write inside the underlying service already covers observability of clinical queries. Adding an EventType for "REST endpoint hit" would double-count (the service-side audit fires on every call regardless of caller). DLog mirrors AD-635c #6.

- **DLog #12 — Audit-endpoint return shape is `{"audit": [...]}`, NOT a bare list.** Mirrors `chain_traces.py:38` (`{"traces": [...]}`) and `counselor.py:69-77` (envelope-wrapped). Bare-list responses are a JSON-hijacking anti-pattern from the OWASP top-10 era. Test #15 locks the envelope key.

- **DLog #13 — Three of four endpoints return bare lists today via the wrapped query methods, BUT the REST envelopes them.** `query_dream_history` returns `list[dict]`; the REST endpoint wraps as `{"dreams": [...]}`. `query_agent_chain_traces` returns `list[dict]`; the REST endpoint wraps as `{"traces": [...]}` (matching `chain_traces.py:38`). `query_circuit_breaker_history` returns `list[dict]`; the REST endpoint wraps as `{"transitions": [...]}`. Each endpoint also returns the requester / target agent for echo-back debugging — same shape as `counselor.py:46-48`. Tests #1 / #5 / #9 lock the envelope keys.

- **DLog #14 — Wave-10 reframe NOT triggered.** The router is one new file, two SEARCH/REPLACE additions in `api.py`, and one new test file. No producer-consumer split is needed because there is no producer side — the producers (`ClinicalTelemetryService` query methods) shipped in AD-635 / AD-635b / AD-635c. AD-635d is pure consumer-surface. Builder cycle is tractable in one pass.

- **DLog #15 — Phantom-API pre-check status.** Same recurring blocker as Waves 52-63 — `scripts/phantom-api-precheck.ps1` has a pre-existing PowerShell parser error. Manual verify-first pass performed at draft (12 verifying greps in this dispatch + the prompt's "Verified Against Codebase" table — all confirmed against HEAD `27fd14f`). Net-new symbols are intra-prompt-introduction (`src/probos/routers/clinical.py` whole module; the four endpoint functions; the `clinical` import in `api.py`). Same FP class as Waves 27-63.

- **DLog #16 — Test count target +17 (within [+14, +18] window).** Three clearance-gated endpoints × (happy + missing-422 + 503 + clearance-denied) = 12; one non-gated audit endpoint × (happy + 503 + slice-direction) = 3; plus 2 limit-clamp locks (dreams, circuit-breakers) = 17. The +14 floor is the no-coverage-loss minimum; the +18 ceiling absorbs one more boundary test if the Builder discovers a corner. If post-build delta is <+14 or >+18, hard-stop and triage before commit.

- **DLog #17 — Commercial-leak audit: clean.** AD-635d is OSS plumbing — one new router module, four read-only HTTP endpoints, two additive lines in `api.py`'s router-import tuple, fourteen tests. The AD-635d-5 *(Commercial)* deferral names tenant-scoped routing; the OSS router itself remains tenant-agnostic. The dispatch contains zero pricing, revenue model, customer counts, professional-services positioning, competitive analysis, or GTM language. Commercial-leak audit: **clean.**

## Builder workflow (standard)

1. Pre-flight gate: `pytest tests/ -q -n 4 --dist=loadfile` → confirm 11351 collected at HEAD `27fd14f`.
2. Apply Section 0 (NEW router file).
3. Apply Section 1 (SEARCH/REPLACE in `api.py`).
4. After Section 1, run `python -c "from probos.routers import clinical; print(clinical.router.prefix)"` to confirm the import path and prefix register cleanly.
5. After Section 1, run `pytest tests/test_ad635_*.py tests/test_ad635b_*.py tests/test_ad635c_*.py -n 0` to confirm AD-635 / AD-635b / AD-635c in-process tests still pass (additive REST surface MUST NOT break them).
6. Apply Section 2 (NEW test file).
7. Add the 14 tests one at a time — confirm each passes before adding the next. Test order: 1-4 dreams, 5-8 chain-traces, 9-13 circuit-breakers (one extra for the per-agent filter), 14 audit unavailable, 15-18 audit shape + slice + clamp.
8. Final gate: `pytest tests/ -q -n 4 --dist=loadfile` → expect 11368 (+17 net target; window [+14, +18] = [11365, 11369]).
9. Update tracking: `PROGRESS.md` (append CLOSED entry), `docs/development/roadmap.md:5962` (flip `Scoped` → `complete`), `prompts/wave-plan.yaml` (id 64 → status: done).

## Hard-stop conditions

1. Test count delta lands outside [+14, +18]. → Triage which endpoint(s) over- or under-shot.
2. Existing AD-635 / AD-635b / AD-635c / AD-561 router tests fail. → Did Section 1 mutate the router-import tuple in a way that re-orders the tests? Re-check verbatim SEARCH blocks.
3. `runtime.clinical_telemetry` is referenced anywhere in the new code as `runtime.clinical_telemetry.X` without a `getattr(runtime, "clinical_telemetry", None)` guard upstream. → Service is `None` / missing when `cfg.enabled=False` (default). Hard-stop and re-read DLog #2.
4. Real working-tree changes appear in source files NOT named in this dispatch (`src/probos/routers/clinical.py`, `src/probos/api.py`, `tests/test_ad635d_clinical_rest_endpoints.py`, plus tracking files). → Hard stop, surface to Captain.
5. Any test introduces an authenticated-call shape (`Authorization` header, bearer token, JWT decode). → That belongs to AD-635d-1; hard-stop.
6. Any test inserts a `runtime` fixture that boots a real `ProbOSRuntime`. → DLog #10 mandates the in-test stub; full-runtime fixtures explode wave-gate runtime budget. Hard-stop.

## Tracking

| Tracker | Update |
|---|---|
| `PROGRESS.md` | Append `AD-635d v1 CLOSED.` paragraph (one-paragraph CLOSED entry mirroring AD-635c). |
| `docs/development/roadmap.md:5962` | Flip `*(Scoped, OSS, Issue #393)*` to `*(complete)*`. |
| `DECISIONS.md` | NOT modified (textbook router-extension sibling pattern; `routers/clinical.py` mirrors `routers/counselor.py` shape). |
| `prompts/wave-plan.yaml` (id: 64) | Set `status: done` post-archive. |
| GH issue #393 | Closed by Captain post-merge with commit hash. |
