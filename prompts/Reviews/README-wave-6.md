# Wave 6 Prompt Review Sweep — 2026-05-01

**Reviewer:** Architect (verify-first review of own drafts)
**Scope:** 5 prompts drafted in commit `8221856` for AD-491, AD-451, AD-458, AD-457, AD-459.
**Review file path pattern:** `prompts/Reviews/ad-NNN-*-review.md`.

---

## Verdicts at a Glance

| AD | Title | Verdict | Required | Recommended | Nits | Build Readiness |
|---|---|---|---|---|---|---|
| AD-491 | Infodynamic Telemetry | ⚠️ Conditional | 1 | 4 | 4 | After 1-line fix (~5min) |
| AD-458 | Pre-Flight Validation | ❌ Not Ready | 4 | 4 | 4 | After rework (~15min) |
| AD-457 | Engineering Crew | ⚠️ Conditional | 4 | 5 | 4 | After Section 7 rewrite (~25min) |
| AD-451 | Validation Framework | ⚠️ Conditional | 5 | 5 | 4 | After scope decision (~30min) |
| AD-459 | Saucer Separation | ⚠️ Conditional | 4 | 5 | 4 | After seed-list fix (~25min) |
| **Totals** | | **0 ✅ / 4 ⚠️ / 1 ❌** | **18** | **23** | **20** | |

No Wave 6 prompt is currently ✅ Approved on first pass. Four are surgical fixes (~5–30 min each); one (AD-458) requires architectural rework on the LLM-tier check.

Wave 5 averaged 22 Required findings across 5 prompts (4.4/prompt). Wave 6 averages 3.6/prompt (18 across 5) — converging trend: the post-Wave 5 conventions are taking hold but verify-first slips remain the recurring failure mode.

---

## Aggregate Themes (recurring findings across the wave)

### 1. Phantom APIs in "v1 reads existing health surface" sketches

Three prompts assume LLM/runtime probe surfaces that don't exist:

- **AD-458** asserts `client.operational_status.deep` — verified phantom (actual surface is `_tier_status: dict[str, bool]` private + `start_health_probe()`).
- **AD-491** asserts `event_log.query(since=...)` — verified phantom (`query()` accepts `category, agent_id, limit` only; no time filter).
- **AD-459** seed list claims "names match runtime attribute names where possible" — three of 13 seeds don't match (`dreaming`, `cognitive_agent`, `introspection_agent`).

Pattern: when a prompt's body says "use the existing health/probe/lookup surface," verify-first must include a literal grep of the surface, not a docstring claim. Wave 5's recurring "phantom API in hand-waved Section" theme is recurring in Wave 6 with the same shape, just relocated to "phantom API in defensive-read Section."

### 2. Theater patterns where v1 is documented as deferring real work

Three prompts ship `passed=True` defaults that mask the absence of real implementation:

- **AD-458** `LLMTierReachableCheck` returns `passed=True` with "no operational_status — assuming reachable" when the surface doesn't exist (always).
- **AD-458** `TokenBudgetCheck` returns `passed=True, blocking=False` unconditionally.
- **AD-451** `TwoStageVerifier` exposed as a class but no production wiring constructs an instance — dead in v1.

The Wave 5 retrospective convention #3 (coordinator-then-dispatch) is being misapplied. The retrospective said: "deliver the coordinator first, defer the dispatch mechanism." That assumes the coordinator does real work. In Wave 6, three checks/wrappers have NO real work — they're documentation in code form. Either remove from v1 (drop the dead code) or wire to a real surface.

### 3. Section 6 / Section 7 anchor chains incomplete for out-of-order builds

Wave 6 prompts chain SEARCH anchors on each other (AD-457 anchors on AD-451, AD-458 on AD-457, AD-459 on AD-458, AD-491 on AD-459). Each prompt has a Builder note for "if predecessor hasn't landed, anchor on N-2." But the chain doesn't go far enough:

- **AD-459 Section 6** missing AD-440 (`orders: OrdersConfig`) fallback for the all-Wave-6-out-of-order case.
- **AD-457 Section 6** missing same fallback.

Wave 5 (commit `f76d8a5`) added the AD-440 anchor at config.py:1593; that's the always-available fallback. Wave 6 prompts should chain to it explicitly.

### 4. Pre-flagged drafting decisions all confirmed as real issues

The dispatch flagged 4 drafting decisions for explicit review:

- **AD-457 Section 7 deferral** — VERIFIED OVERCAUTIOUS. Pool-spawning pattern fully exists at `agent_fleet.py:154-198`. Section 7 must be concrete.
- **AD-451 `_MetadataCheck` nested dataclass** — VERIFIED unusual. ProbOS convention is module-level; flatten.
- **AD-458 BuildResult field names** — VERIFIED phantom. `BuildResult(success=False, error=...)` will TypeError because `spec` is required.
- **AD-491 cognitive/ vs telemetry/ placement** — VERIFIED sound. `substrate/telemetry.py` already exists; `cognitive/` is correct.

3 of 4 pre-flags converted to Required findings. The 4th (AD-491 placement) was a false positive — the placement is sound.

### 5. Section 0 EventTypes are clean across the batch

No naming collisions between the 9 new EventTypes:

```
AD-451: VALIDATION_RECONCILIATION_REQUESTED, VALIDATION_OUTCOME_VERIFIED
AD-457: DAMAGE_CONTROL_ACTIVATED, MAINTENANCE_SCHEDULED, PERFORMANCE_THRESHOLD_BREACHED
AD-458: PREFLIGHT_FAILED
AD-459: SERVICE_TIER_DEGRADED, SERVICE_TIER_RESTORED
AD-491: INFODYNAMIC_REPORT
```

All 9 verified absent from `events.py` today. Insertion-order chain (AD-451 → AD-457 → AD-459 → AD-491) is documented in each prompt. ✅ Section 0 discipline holds across the batch.

---

## Cross-Prompt Concerns

### Source-file overlap

All 5 prompts modify `events.py`, `config.py`, and `startup/finalize.py`. SEARCH anchors are at distinct line neighborhoods, so merge conflicts are unlikely if Builder commits one prompt at a time. The chained-anchor design (each prompt anchors on its predecessor's output) means out-of-order builds need fallback anchors — see Theme #3.

### `cognitive/` layer vs `telemetry/` layer placement

AD-491 placed in `cognitive/infodynamic.py` (verified sound). Future "system-wide observability" ADs should follow the same precedent: if it reads runtime cognitive state, it lives in `cognitive/`; if it's a substrate primitive, it lives in `substrate/telemetry.py`. Worth recording in DECISIONS.md.

### `degradation/` vs `cognitive/` for AD-459

AD-459 creates `src/probos/degradation/` as a new top-level package (sibling of `cognitive/`, `substrate/`, `consensus/`, `experience/`, `mesh/`). This is consistent with the `governance/` (AD-676) and `security/` (AD-455) precedent for cross-cutting concerns that span multiple layers.

### Pool-naming collision risk in AD-457

AD-457's `pool="engineering"` overlaps semantically with the existing `engineering_officer` pool. Recommended fix: `engineering_<role>` per the `medical_<role>` convention.

### `red_team_agents` (post-AD-455 public) — used by both AD-451 and AD-459

AD-451 reads `runtime.red_team_agents` for `_invoke_third`. AD-459's seed list classifies `red_team_lead` as NON_ESSENTIAL. Different services — `red_team_agents` (the pool) vs `red_team_lead` (the coordinator AD-455 introduced). No conflict, but the proximity is worth flagging for the Builder.

---

## Pre-Flagged Drafting Decisions — Resolution

| Decision | Pre-flag | Verification | Outcome |
|---|---|---|---|
| AD-457 Section 7 pool wiring deferral | "Pattern exists OR overcautious?" | Pattern exists fully at `agent_fleet.py:154-198` | Required: rewrite Section 7 with concrete SEARCH/REPLACE |
| AD-451 `_MetadataCheck` nested dataclass | "Unusual or matches pattern?" | No nested dataclasses in `src/probos` (verified) | Required: flatten to module-level |
| AD-458 `BuildResult` field names | "Match live code?" | `BuildResult` requires `spec`; phantom field signature | Required: rewrite Section 4 to match create-then-mutate pattern |
| AD-491 cognitive/ vs telemetry/ placement | "Reads enough state to justify cognitive/?" | `substrate/telemetry.py` already exists; AD-491 reads cognitive state | Sound — no change |

3 of 4 pre-flags converted to Required findings. The 4th confirms a sound design decision worth memorializing in DECISIONS.md.

---

## Hard-Stops Triggered

The dispatch enumerated 4 hard-stop conditions for the review pass:

1. **Phantom API not introduced by the prompt itself** — TRIGGERED but mechanical fix:
   - AD-458 `client.operational_status.deep` — phantom; pick (a) add public accessor / (b) defer / (c) real probe.
   - AD-491 `event_log.query(since=)` — phantom kwarg; drop or post-filter.
   - AD-457 register_template missing — phantom (pattern exists; Section 7 hand-waved).
   - AD-458 `BuildResult(success=False, error=...)` — phantom signature.

   Surface to dispatching architect: **all 4 are mechanical fixes, no scope expansion needed**. Required findings have concrete resolution paths.

2. **Two prompts conflict on same source file in unidentified ways** — NOT TRIGGERED. All 5 prompts have non-overlapping SEARCH anchors at config.py:1593+ neighborhood, events.py:190+ neighborhood, finalize.py end-of-file neighborhood.

3. **Section 0 EventType collision** — NOT TRIGGERED. All 9 new EventTypes unique and free.

4. **Inter-prompt SEARCH-anchor chaining dependency-order error** — NOT TRIGGERED but partially incomplete. Section 6/7 fallback chains stop at "predecessor missing"; need to chain to AD-440's `orders: OrdersConfig` as the always-available fallback.

---

## Recommended Build Readiness Order (after fixes)

After all required fixes land, dispatch order should be:

1. **AD-491** — smallest blast radius (1 Required, 1-line fix). Establishes the cognitive/ vs telemetry/ placement precedent.
2. **AD-451** — establishes the `runtime.reconciliation_escalator` public attribute; reads existing AD-455 `red_team_agents`.
3. **AD-458** — establishes the `runtime.pre_flight_runner` public attribute; reads AD-451 surfaces in Section 6 anchor.
4. **AD-457** — establishes the `engineering/` package and three engineering agents. Anchors on AD-451 in Section 6.
5. **AD-459** — highest blast radius. Consumes the events fired by AD-457 in operator-facing context. Read-only v1 means no risk to other Wave 6 deliverables.

Out-of-order alternative: AD-491 can ship in parallel (no dependencies). AD-457 and AD-459 must come AFTER AD-451 (anchor dependency in Section 6/7). AD-458 can be parallel with AD-457 (both anchor on AD-451 in Section 5/6).

---

## Architect Disposition

The 5 Wave 6 drafts are **actionable but require revision** before Builder dispatch. Convergence rate: 0/5 ✅ on first pass; expected 4-5/5 ✅ on second pass. Total architect rework: **~100 minutes** (1.5 hours) across the batch.

The recurring themes (phantom APIs in defensive-read sections, theater patterns in v1 deferrals, incomplete fallback chains) are easy to fix with a focused second pass. None of the Required findings require architectural decisions beyond the dispatching architect's authority.

**Recommended next step:** dispatch a single revision subagent that handles all 5 prompts in one pass — same pattern as Wave 5. Reasoning:

- All 5 need revisions; sequential reviews are independent but revisions share patterns (especially the phantom-API discipline across AD-458/491/457).
- Revision wall time is ~1.5h architect, comparable to the original drafting wall time.
- The reviews are explicit enough that a revision subagent can apply Required + Recommended deterministically without architect coordination per prompt.
- Recommended build order (AD-491 → AD-451 → AD-458 → AD-457 → AD-459) is preserved for the Builder.

After revision, expect a second-pass review to confirm convergence (target 5 ✅, tolerance 1 ⚠️ on AD-451 — highest semantic risk).
