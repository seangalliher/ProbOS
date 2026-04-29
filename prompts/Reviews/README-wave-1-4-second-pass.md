# Wave 1-4 Re-review (Second Pass) — 2026-04-29

**Reviewer:** Architect (parallel Explore subagents)
**Scope:** 6 prompts revised in commit `f46f7b0` ("Prompts: revise wave specs after architect review")
**Prior pass:** [README-wave-1-4.md](README-wave-1-4.md) (first pass, same date)

The other 14 prompts from the original wave have not been touched since the first review and retain their original verdicts.

---

## Verdict Summary (revised prompts only)

| AD | First Pass | Second Pass | Notes |
|---|---|---|---|
| 438 | ⚠️ Conditional | ✅ **Approved** | `EventType.TASK_ROUTED` added; SEARCH/REPLACE matches live code. |
| 445 | ⚠️ Conditional | ⚠️ Conditional* | Both Required items fixed. Only remaining issue is a defensive `hasattr(runtime, 'emit_event')` guard that's now dead code (AD-680 has landed). Trivial cleanup. |
| 461 | ✅ Approved | ✅ Approved | Revisions clean. Same `hasattr` dead-code nit as AD-445; ignorable. |
| 470 | ⚠️ Conditional | ⚠️ Conditional | `defaultdict` import + `broadcast()` timing fixed. `send()` timing still described in prose only — needs a concrete SEARCH/REPLACE pair. |
| 674 | ⚠️ Conditional | ❌ **Not Ready** | Critical Required item not addressed: config thresholds still not threaded to the call site. `EarnedAgencyConfig.initiative_trust_thresholds` is dead code as written. |
| 679 | ✅ Approved | ✅ Approved | Revisions clean. Added a proactive event-collision note. |

\* AD-445 effectively becomes ✅ once the `hasattr` guard is dropped (AD-680 is now on main, so the guard is harmless but redundant).

---

## Updated Wave Readiness Tracker

| AD | First Pass | Current | Action Required |
|---|---|---|---|
| 438 | ⚠️ | ✅ | None |
| 445 | ⚠️ | ⚠️ | Drop `hasattr(runtime, 'emit_event')` guard (AD-680 landed) |
| 446 | ⚠️ | ⚠️ | (Unchanged) Add `EventType.COMPENSATION_TRIGGERED`; document AD-445 dependency |
| 447 | ✅ | ✅ | None |
| 448 | ⚠️ | ⚠️ | (Unchanged) Add `EventType.TOOL_INVOKED` |
| 461 | ✅ | ✅ | None |
| 465 | ✅* | ✅* | (Unchanged) Switch `model_validator` → `field_validator` |
| 470 | ⚠️ | ⚠️ | Provide concrete SEARCH/REPLACE for `send()` timing |
| 489 | ✅ | ✅ | None |
| 490 | ✅ | ✅ | None |
| 524 | ⚠️ | ⚠️ | (Unchanged) Decide on `OracleService.archive_store` parameter |
| 561 | ⚠️ | ⚠️ | (Unchanged) Add `Enum` import + `EventType.COUNSELOR_INTERVENTION` |
| 566f | ⚠️ | ⚠️ | (Unchanged) Fix class name `AgentSkillService`; add `ProficiencyLevel` import |
| 566i | ✅ | ✅ | None |
| 674 | ⚠️ | ❌ | **Wire `initiative_trust_thresholds` config to call site** |
| 675 | ❌ | ❌ | (Unchanged) Hold for AD-674 |
| 676 | ✅ | ✅ | None |
| 677 | ✅ | ✅ | None |
| 678 | ⚠️ | ⚠️ | (Unchanged) Hold for AD-677 |
| 679 | ✅ | ✅ | None |

**Tally:** 9 ✅ Approved · 9 ⚠️ Conditional · 2 ❌ Not Ready (AD-674 and AD-675 — note AD-675 was already blocked on AD-674, and now AD-674 itself slipped to Not Ready, so the chain is fully blocked).

---

## Cross-Cutting Observations (this pass)

### 1. The "missing event type" pattern is real and recurring

Three of the six revised prompts (438, 445, plus 470's import) needed Section-0-style enum additions. Standing recommendation from the first-pass review is even stronger now: **add a mandatory "Section 0: Event Types" subsection to the prompt template.**

### 2. AD-680 has landed — defensive `hasattr(runtime, 'emit_event')` is now dead code

Several prompts (445, 461, and likely others not in this batch) still wrap `runtime.emit_event` in `hasattr` guards. The user-memory anti-pattern flagged this in the original ProbOS review notes. With AD-680 on `main` (commit `73945d0`), `runtime.emit_event` is a stable public method — the guard is permanently true. Sweep the remaining wave 1-4 prompts and drop these guards before each prompt builds.

### 3. AD-674 is the wave's critical-path blocker

AD-675 cannot build until AD-674 lands `InitiativeLevel` and `resolve_initiative_level()`, AND the threshold config must actually be wired through. Without the wiring, operators get no runtime tunability and the config field is misleading. The fix is a ~6-line block at the cognitive_agent.py call site (full code provided in the AD-674 review file). One revision pass should do it.

### 4. AD-470's `send()` timing gap is a spec-completeness issue

The author wrote a clean `broadcast()` SEARCH/REPLACE block but punted on `send()` with prose. The Builder will need to infer the try/finally boundary lines, which invites variation between attempts. Symmetric SEARCH/REPLACE blocks for both methods are the standard.

---

## Recommended Next Steps for the Author

1. **AD-674 (highest priority).** Insert the threshold-extraction block at the call site (review file has the exact code). This unblocks AD-675.
2. **AD-470.** Provide a concrete SEARCH/REPLACE pair for `send()` timing.
3. **AD-445 + sweep.** Drop `hasattr(runtime, 'emit_event')` guards across wave 1-4 prompts.
4. **The 8 remaining first-pass Conditionals** (446, 448, 524, 561, 566f, 465 validator, plus the others that didn't see revisions): one batch revision pass to clear them.

After those four steps, the wave should reach 19 ✅ + 1 hold (AD-678 on AD-677), with all top-of-DAG dependencies unblocked.
