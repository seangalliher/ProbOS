# Review: AD-674 — Graduated Initiative Scale

**Verdict:** ⚠️ Conditional
**Re-review (2026-04-29 second pass): ❌ Not Ready.** The most important Required item — wiring config thresholds to the call site — was not addressed. Function call still passes no thresholds; config is dead code.

**Headline:** Threshold config wired into runtime is missing; minor scope clarifications needed.

## Required

1. **Verify `InitiativeLevel` doesn't already exist.** Grep confirms the enum is new (no matches in codebase). Insertion after `AgencyLevel` at [earned_agency.py:11](src/probos/earned_agency.py#L11) is correct, but pin the line by SEARCH text not number.
2. **`Rank.from_trust()` parameter type.** Prompt calls `Rank.from_trust(float(...))`. Verify the function accepts `float` (it should — already used at `cognitive_agent.py:3626`). Add an explicit verification step.
3. **Threshold config not wired to call site.** Prompt adds `initiative_trust_thresholds` to `EarnedAgencyConfig` but no code reads it and passes it into `resolve_initiative_level()` at the call site in [cognitive_agent.py:3622](src/probos/cognitive/cognitive_agent.py#L3622). Add a wiring step (Section 3 or 4) that loads the config and threads it through.
4. **Import collision risk.** Section 4 adds `resolve_initiative_level` import to cognitive_agent.py near the existing `agency_from_rank` import (line 3620-ish). Verify no circular import or name shadowing.

## Recommended

1. **Test `Rank.from_trust(0.1) == Rank.ENSIGN`** to lock the threshold mapping. If `Rank.from_trust` ever changes, the initiative-level mapping silently breaks.
2. **Configuration timing.** Specify whether thresholds are read at instruction-injection time (recommended, allows hot-reload) or per-call. Don't leave this implicit.

## Nits

- Section 2 says "Rank is already imported at module level (line 8)." Verify it's still line 8; line numbers drift.
- `Rank.from_trust()` is called with a ternary (`isinstance(_trust_val, str) else _trust_val`). Trust values should already be float at this point — enforce typing at the assignment instead.

## Verified

- `AgencyLevel` at [earned_agency.py:11](src/probos/earned_agency.py#L11).
- `Rank` imported at [earned_agency.py:8](src/probos/earned_agency.py#L8).
- `agency_from_rank()` at [earned_agency.py:135](src/probos/earned_agency.py#L135).
- Three gate functions at [earned_agency.py:145, 171, 180](src/probos/earned_agency.py#L145).
- `EarnedAgencyConfig` at [config.py:1099](src/probos/config.py#L1099).
- Integration point in cognitive_agent.py at [lines 3622-3629](src/probos/cognitive/cognitive_agent.py#L3622).
- `InitiativeLevel` does NOT yet exist (zero matches in codebase).

---

## Second-Pass Re-review (2026-04-29)

**Verdict:** ❌ Not Ready.

| Prior Required | Status | Evidence |
|---|---|---|
| Pin `InitiativeLevel` insertion via SEARCH text not line number | ✅ Fixed | Section 1 references the existing `AgencyLevel` enum structure rather than a fixed line. |
| Verify `Rank.from_trust(float)` accepts a float | ✅ Fixed | Confirmed already used at [cognitive_agent.py:3625-3626](src/probos/cognitive/cognitive_agent.py#L3625). |
| **Wire `initiative_trust_thresholds` config to `resolve_initiative_level()` call site** | ❌ **Not addressed** | `resolve_initiative_level()` signature accepts `thresholds: dict[str, float] \| None = None` but Section 4 calls it with no thresholds argument: `resolve_initiative_level(Rank.from_trust(...), _rt.trust_network.get_score(self.id))`. The new `EarnedAgencyConfig.initiative_trust_thresholds` field is dead code. Operators cannot tune thresholds at runtime. |
| Avoid import collisions in cognitive_agent.py | ✅ Fixed | Verified `Rank` already imported at [earned_agency.py:8](src/probos/earned_agency.py#L8). |

### Required for next pass

At the cognitive_agent.py call site (around line 3625), extract the config and pass it explicitly:

```python
_runtime_ref = getattr(self, '_runtime', None)
_thresholds = (
    _runtime_ref.config.earned_agency.initiative_trust_thresholds
    if _runtime_ref is not None and getattr(_runtime_ref, 'config', None) is not None
    else None
)
_initiative_val = resolve_initiative_level(
    Rank.from_trust(_trust_val),
    _trust_val,
    thresholds=_thresholds,
).value
```

Without this, the config addition in Section 3 is a no-op.

---

## Third-Pass Re-review (2026-04-29)

**Verdict:** ✅ Approved.

| Prior Required | Status |
|---|---|
| Wire `initiative_trust_thresholds` config to call site | ✅ Fixed — Section 4 now extracts `_rt.config.earned_agency.initiative_trust_thresholds` (with null-check) and passes it as `thresholds=_initiative_thresholds` to `resolve_initiative_level()`. |

Config is no longer dead code. Operators can tune thresholds at runtime. Ready for builder — unblocks AD-675 once this lands.
