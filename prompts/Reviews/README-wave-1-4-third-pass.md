# Wave 1-4 Re-review (Third Pass) — 2026-04-29

**Reviewer:** Architect (parallel Explore subagents)
**Scope:** 6 prompts revised in commit `d7b9587` ("Prompts: second-pass review fixes (AD-674, AD-470, hasattr sweep)")
**Prior passes:**
- [README-wave-1-4.md](README-wave-1-4.md) (first pass)
- [README-wave-1-4-second-pass.md](README-wave-1-4-second-pass.md) (second pass)

---

## Verdict Summary (this pass)

| AD | Pass 1 | Pass 2 | Pass 3 | Notes |
|---|---|---|---|---|
| 445 | ⚠️ | ⚠️ | ✅ **Approved** | `hasattr` guard removed; wires `runtime.emit_event` directly. |
| 446 | ⚠️ | ⚠️ | ⚠️ Conditional | AD-445 dependency documented + governance/ fallback added. `EventType.COMPENSATION_TRIGGERED` still not in [events.py](src/probos/events.py). |
| 448 | ⚠️ | ⚠️ | ⚠️ Conditional | `EventType.TOOL_INVOKED` still not added. Otherwise clean. |
| 461 | ✅ | ✅ | ✅ Approved | Revised to drop `hasattr` guard. No regressions. |
| 470 | ⚠️ | ⚠️ | ⚠️ Conditional | `send()` timing now has concrete SEARCH/REPLACE (was Required). Defaultdict reassignment nit unresolved (Recommended). |
| 674 | ⚠️ | ❌ | ✅ **Approved** | Config thresholds NOW wired through to `resolve_initiative_level()`. Field is live, not dead code. Unblocks AD-675. |

---

## Updated Wave Readiness Tracker

| AD | Status | Action Required |
|---|---|---|
| 438 | ✅ | None |
| 445 | ✅ | None |
| 446 | ⚠️ | Add `EventType.COMPENSATION_TRIGGERED` to events.py |
| 447 | ✅ | None |
| 448 | ⚠️ | Add `EventType.TOOL_INVOKED` to events.py |
| 461 | ✅ | None |
| 465 | ✅* | Switch `model_validator` → `field_validator` |
| 470 | ⚠️ | Optional: replace `defaultdict[list]` reassignment with `deque(maxlen=200)`, OR comment the trade-off. Not a blocker. |
| 489 | ✅ | None |
| 490 | ✅ | None |
| 524 | ⚠️ | Decide on `OracleService.archive_store` parameter (add or defer) |
| 561 | ⚠️ | Add `Enum` import + `EventType.COUNSELOR_INTERVENTION` |
| 566f | ⚠️ | Fix class name `AgentSkillService`; add `ProficiencyLevel` import |
| 566i | ✅ | None |
| 674 | ✅ | None — unblocks AD-675 |
| 675 | ✅** | Now buildable once AD-674 lands |
| 676 | ✅ | None |
| 677 | ✅ | None |
| 678 | ⚠️ | Hold for AD-677 |
| 679 | ✅ | None |

\* AD-465 has one trivial Required (validator decorator). \*\* AD-675 dependency is now satisfiable.

**Tally:** 11 ✅ Approved · 7 ⚠️ Conditional · 0 ❌ Not Ready · 1 dependency hold (678 on 677).

---

## Cross-Cutting Observations

### 1. AD-674 unblocks the Northstar chain

The critical config-wiring fix at `cognitive_agent.py:3625` is now in the prompt. AD-674 → AD-675 → (calibrated initiative + risk tiers via AD-676) is the longest dependency chain in this wave; with AD-674 buildable, the entire Northstar substrate can land.

### 2. The "missing EventType" pattern persists

AD-446 (`COMPENSATION_TRIGGERED`) and AD-448 (`TOOL_INVOKED`) still need enum entries. Author's revision pass touched both prompts without adding the enums. **Strong recommendation:** make a "Section 0: Event Types" subsection mandatory in the prompt template, OR batch all wave-introduced `EventType` additions into a single enum-edit prompt that ships first.

### 3. AD-680 cleanup is partial

Revised prompts (AD-445, AD-461) correctly drop their `hasattr(runtime, 'emit_event')` guards. **However:** 13 pre-existing sites in `cognitive_agent.py`, `proactive.py`, and `dreaming.py` still carry the same dead-code pattern (now permanently true after AD-680 landed). These were not introduced by wave 1-4 prompts and aren't this wave's responsibility — but worth filing as a small follow-up cleanup AD (AD-681 candidate).

### 4. Defaultdict reassignment in AD-470

The list-slicing pattern `self.type_durations_ms[intent_type] = durations[-200:]` is correctness-safe because `defaultdict.__getitem__` still creates a list on the next missing-key access. Subsequent `.append()` calls on the existing key work fine — they're operating on a plain list, but the contract is preserved. The original Nit was overstated; mark as Won't Fix unless the author prefers `deque(maxlen=200)` for explicitness.

---

## Recommended Build Order (updated)

**Wave 1A — ship now (ready):**
- AD-438, AD-445, AD-447, AD-461, AD-489, AD-490, AD-566i, AD-679

**Wave 1B — ship after one enum-edit batch:**
- Single enum-edit commit adds `COMPENSATION_TRIGGERED`, `TOOL_INVOKED`, `COUNSELOR_INTERVENTION` (and any others identified). Then build:
- AD-446, AD-448, AD-561

**Wave 1C — fixable nits, parallel safe:**
- AD-465 (validator pattern fix)
- AD-470 (defaultdict comment OR deque migration; otherwise ship as-is)
- AD-566f (class name + import fix)
- AD-524 (OracleService.archive_store decision)

**Wave 2 — Northstar substrate (sequenced):**
- AD-676 → owns `governance/__init__.py` creation
- AD-674 → unlocks AD-675
- AD-675 → calibrated initiative
- AD-677 → context provenance
- AD-678 → memory transparency (post-677)

---

## Notes for the Author

- The bigger `hasattr` cleanup across `cognitive_agent.py`/`proactive.py`/`dreaming.py` deserves its own AD (a one-shot codebase sweep). Suggest **AD-681: AD-680 follow-up — drop dead `hasattr(runtime, 'emit_event')` guards.** Two-line fix in 13 sites, one regression test (analogous to AD-680's Test 4).
- Two enum entries (AD-446 + AD-448) are still the only remaining Required blockers in the wave. A single events.py-only commit closes both.
