# Wave 6 Second-Pass Review Sweep — 2026-05-01

**Reviewer:** Architect (second-pass against revised prompts in commit `7a1b2f7`)
**Pass-1 sweep:** `prompts/Reviews/README-wave-6.md`
**Pass-2 review files:** `prompts/Reviews/ad-NNN-*-review.md` — `## Second-Pass Review (2026-05-01)` sections appended.

---

## Verdicts at a Glance

| AD | Title | Pass-1 | Pass-2 Verdict | New Required | New Nits | Build Ready? |
|---|---|---|---|---|---|---|
| AD-491 | Infodynamic Telemetry | ⚠️ | **✅ Approved** | 0 | 0 | Yes |
| AD-458 | Pre-Flight Validation | ❌ | **✅ Approved** | 0 | 1 (Builder discretion) | Yes |
| AD-457 | Engineering Crew | ⚠️ | **✅ Approved** | 0 | 2 (impl-detail checks) | Yes |
| AD-451 | Validation Framework | ⚠️ | **✅ Approved** | 0 | 0 | Yes |
| AD-459 | Saucer Separation | ⚠️ | **✅ Approved** | 0 | 0 | Yes |
| **Totals** | | **0 ✅ / 4 ⚠️ / 1 ❌** | **5 ✅ / 0 ⚠️ / 0 ❌** | **0** | **3** | |

**Convergence rate:** 5 of 5 prompts moved from ⚠️/❌ to ✅ in a single revision pass (100%). The dispatch's tolerance budget (1 ⚠️ on AD-451) was not consumed.

Wave 5 history: 4/5 ✅ + 1 ⚠️ on second pass (80% convergence; required a 5-minute architect fix on AD-499). Wave 6 ran cleaner — all 5 converged without needing the safety-margin ⚠️.

---

## Pass-1 → Pass-2 Resolution Statistics

| | Pass-1 Required | Pass-2 Resolved | Pass-1 Recommended | Pass-2 Applied |
|---|---|---|---|---|
| AD-491 | 1 | 1 | 4 | 2 (rec#3, rec#4) — 2 deferred (cosmetic) |
| AD-458 | 4 | 4 | 4 | 3 (rec#1, rec#2, rec#4) — 1 deferred (rec#3 immutability) |
| AD-457 | 4 | 4 | 5 | 5 |
| AD-451 | 5 | 5 | 5 | 5 |
| AD-459 | 4 | 4 | 5 | 5 |
| **Totals** | **18** | **18** (100%) | **23** | **20** (87%) |

3 Recommended findings deferred (all cosmetic per architect judgment): AD-491 rec#1 (line range cosmetic), AD-491 rec#2 (already correct), AD-458 rec#3 (frozen-tuple form would break existing pattern).

---

## High-Priority Verification Outcomes

### ✅ AD-451 TwoStageVerifier consumer wiring — REAL, not theater

The dispatch's primary high-priority check: "TwoStageVerifier should produce a real verdict that `_invoke_third` consumes, not just be invoked-and-discarded."

Verified clean. Section 3 line 388-398:

```python
verifier = TwoStageVerifier(
    red_team=third,
    emit_event=self._emit_event,
    metadata_threshold=self._metadata_threshold,
)
return await verifier.verify(...)
```

The returned `TwoStageOutcome` is consumed at line 356 in the majority vote:

```python
votes = sum([primary.verified, secondary.verified, third.verified])
majority = votes >= 2
```

Not invoked-and-discarded. `third.verified` (a real `TwoStageOutcome.verified` boolean) drives the verdict. No theater.

The flat-dataclass refactor landed cleanly: `_MetadataCheck` is now module-level at lines 80-89, no longer nested.

### ✅ AD-458 deferred-to-AD-458b scope — substantive v1 remains

The dispatch's hard-stop check: "If AD-458 v1 is now too thin to be buildable (gutted by the deferral to AD-458b), surface."

Not triggered. v1 ships:
- `PreFlightCheck` Protocol (`@runtime_checkable`)
- `PreFlightResult`, `PreFlightReport` dataclasses
- 2 real-work checks: `TargetFilesExistCheck`, `TargetFilesWritableCheck`
- `PreFlightRunner` with short-circuit + emit
- Builder integration in `execute_approved_build()` with failure isolation
- 10 tests covering happy/error/edge paths

Real value-add: catches read-only build targets, missing dependency files, Windows ACL issues before LLM calls fire. The phantom `client.operational_status.deep` is fully gone (only mentioned in verify-first comment + Revision section, which document what was wrong).

The `BuildResult(success=False, spec=spec); result.error = ...` create-then-mutate pattern matches `cognitive/builder.py:2504, 2511-2515` exactly. SEARCH/REPLACE block anchors verified verbatim.

### ✅ AD-457 Section 7 concrete pool wiring

Two SEARCH/REPLACE blocks:
- 7a registers 3 templates in `runtime.py:622` (mirrors medical templates at `runtime.py:601-605`)
- 7b spawns 3 pools in `agent_fleet.py` after the engineering_officer block at line 146 (mirrors medical pool block at lines 154-198)

Pattern matches established medical/security/governance pool registration. No deferral language remains. Pool naming `engineering_<role>` follows the `medical_<role>` convention.

### ✅ Anchor-chain fallback completeness across AD-457/458/459

All three Section 6 chains terminate at `orders: OrdersConfig = OrdersConfig()  # AD-440` (config.py:1593):

- **AD-457:** `validation_framework` (AD-451) → `orders: OrdersConfig` (AD-440 terminal). 2 levels.
- **AD-458:** `engineering` (AD-457) → `validation_framework` (AD-451) → `orders: OrdersConfig` (AD-440 terminal). 3 levels.
- **AD-459:** `pre_flight` (AD-458) → `engineering` (AD-457) → `validation_framework` (AD-451) → `orders: OrdersConfig` (AD-440 terminal). 4 levels.

Builder running prompts in any order can find a valid SEARCH target. The terminal anchor is verified at `config.py:1593` in each prompt's footer.

### ✅ AD-491 phantom-kwarg removal

`event_log.query(since=...)` is fully gone from the Section 1 code. Replaced with:

```python
events = await log.query(limit=10_000)
cutoff = time.time() - self._event_window
windowed = [e for e in events if float(e.get("timestamp", 0) or 0) >= cutoff]
```

Real query signature documented at `event_log.py:132` in the footer. Inline comment at lines 155-157 explains why post-filter is used.

---

## New Findings Audit

The dispatch's hard-stops:
- **"If 2+ prompts fail second-pass with new Required findings, surface."** — 0 new Required findings across all 5 prompts. **Not triggered.**
- **"Public-attribute collision introduced during revision."** — None. The 4 public attributes are non-overlapping: `runtime.{infodynamic_probe, reconciliation_escalator, pre_flight_runner, degradation_manager}`.
- **"AD-458 v1 gutted by deferral."** — Not triggered. v1 has 2 real-work checks, full Protocol + Runner + Builder integration.

3 new Nit-class findings (none block):

| AD | Finding | Severity |
|---|---|---|
| AD-458 | `runtime_checkable(PreFlightCheck)` post-assignment instead of `@runtime_checkable` decorator. Both work; standard form is cleaner. | Nit — Builder discretion. |
| AD-457 | `interval=interval` kwarg flow through `create_pool_fn` → `ResourcePool` → agent `__init__`. Verified via `runtime.py:1086-1109` accepts `**spawn_kwargs`. | Implementation-detail check; verified clean. |
| AD-457 | Test count 12 → 14 in revision; acceptance criterion line says "All 14 tests pass". Internally consistent. | Cosmetic; verified clean. |

All 3 are documented in the relevant pass-2 review files. None require revision.

---

## Hard-Stop Disposition

| Hard-stop condition | Status |
|---|---|
| 2+ prompts fail second-pass with new Required | **Not triggered** — 0 new Required across 5 prompts. |
| Public-attribute collision during revision | **Not triggered** — 4 distinct public attributes verified non-overlapping. |
| AD-458 v1 gutted by AD-458b deferral | **Not triggered** — v1 has substantive scope (Protocol, Runner, 2 real checks, Builder integration). |
| Architect-tolerance ⚠️ on AD-451 only | **Not consumed** — AD-451 hit ✅ on first revision. |

---

## Recommended Build Readiness Order

All 5 ✅ — original dispatch order holds without modification:

1. **AD-491** — Infodynamic Telemetry. Smallest blast radius. No dependencies.
2. **AD-451** — Validation Framework Hardening. Establishes `runtime.reconciliation_escalator` public attribute. Reads existing AD-455 `red_team_agents`.
3. **AD-458** — Pre-Flight Validation. Establishes `runtime.pre_flight_runner` public attribute. Anchors on AD-451 in Section 5.
4. **AD-457** — Engineering Crew. Owns `agents/engineering/` directory creation. Anchors on AD-451 in Section 6.
5. **AD-459** — Saucer Separation. Highest blast radius. Read-only v1 benefits from observing AD-457/451/491 events first.

Out-of-order alternative: AD-491 can ship in parallel (no dependencies). Anchor-chain fallback (terminating at AD-440) means any out-of-order subset has a valid SEARCH target.

---

## Architect Disposition

**Verdict:** 5 ✅ Approved. Wave 6 is **100% Builder-ready** by line count.

Wave 5 history: 4 ✅ + 1 ⚠️ on second pass (80% convergence). Wave 6: 5 ✅ on second pass (100% convergence). The Wave 5 retrospective conventions are taking hold:

- Public-attribute wiring established: 4 new public attributes, 0 leading-underscore Demeter slips.
- Coordinator-then-dispatch applied: AD-451 (SelfVerificationHook deferred), AD-458 (LLMTier+Token deferred), AD-459 (active-shedding deferred), AD-457 (event-only v1, handlers deferred).
- Verify-first applied wholesale: 0 phantom APIs in any post-revision prompt body.
- Anchor-chain fallback to AD-440 terminal: applied across AD-457/458/459.
- No-theater discipline: every v1 component has a real consumer or is wholesale-deferred to a sub-AD.

**Recommended next step:** Builder dispatch. The 5 prompts are ready for Builder execution in the order recommended above. No architect rework required.

Wave 6 is closed for review at this commit.
