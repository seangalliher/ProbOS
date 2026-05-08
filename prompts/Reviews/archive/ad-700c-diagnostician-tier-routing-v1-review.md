# Review: AD-700c v1 — Diagnostician per-call LLM tier override from `level_llm_tier`
**Verdict:** ✅ Approved
**Narrow, well-scoped per-observation tier override. Two Recommended sharpenings around the short-circuit return shape and a non-goals contradiction.**

## Required (must fix before building)
_None._

## Recommended
1. **The L4/L5 short-circuit return shape is unverified against the actual `_decide_via_llm` return contract.** The prompt's D2 snippet returns `{"action": "execute", "llm_output": "", "tier_used": "none", "level": ..., "level_rank": ..., "short_circuit_reason": ...}` — but the existing `_decide_via_llm` return shape (what the rest of the agent's `decide()` -> `act()` path consumes) is not cited. If the consumer expects keys like `intent_results`, `chain`, or `parsed_decision`, this short-circuit will produce a NoneType error in `act()`. Architect must read 30 lines after `cognitive_agent.py:1701` and document the canonical return-dict shape, then craft the short-circuit to be a *valid instance* of that shape (with empty/sentinel values where appropriate). Otherwise: L4/L5 tests pass against the new `tier_used == "none"` assertion but the agent's downstream `act()` quietly fails.
2. **Non-Goals contradicts AD-700b.** The line "Do NOT remove the AD-700b journal `tier_used` write" implies AD-700b adds a `tier_used` column. AD-700b's prompt adds `level` and `level_rank` only — there is no `tier_used` field anywhere in AD-700b. Either (a) AD-700c is silently introducing a new journal field without specifying the migration (a Required gap), or (b) the Non-Goals line is dead — strike it. Most likely (b); confirm by re-reading AD-700b.

## Nits
1. The `_resolve_tier_for_observation` semantics for explicit-`None`-vs-missing-key are subtle: `observation.get("level_llm_tier") is None` matches both. The implementation correctly disambiguates via `"level_llm_tier" in observation`, but a one-line comment in the helper explaining the three cases (key absent / key present and None / key present and string) would prevent regressions.
2. Test #7 covers the defensive scoping — good. Consider adding test #8: a non-string `level_llm_tier` (e.g. integer or empty string) falls back to static — the helper already handles this via `isinstance(override, str) and override`, but the boundary deserves a test.

## Verified
- ✅ `_resolve_tier` at `cognitive_agent.py:6055`, `LLMRequest(...)` at `:1698-1701` with `tier=self._resolve_tier()` at `:1701` — exact match for the replacement cited in D2.
- ✅ DiagnosticianAgent `perceive()` populates `result["level_llm_tier"]` from `level.llm_tier` — verified at `diagnostic_levels.py:43-61` and `diagnostician.py:73-141`.
- ✅ `LLMRequest.tier: str` is the canonical per-call mechanism — no LLM client change required.
- ✅ Defensive scoping (only `diagnose_system` short-circuits) is sound.
- ✅ Scope is narrow: 2 small additions in cognitive_agent.py + 1 new test file.

## Risk
LOW (in the helper) + MEDIUM (in the short-circuit return shape — see Recommended #1). With Recommended #1 resolved, this is a clean ✅.

## Pass 2 Review (2026-05-08)

**Verdict:** ✅ Approved — dead `tier_used` Non-Goals line struck; return-dict shape contract documented.

### Required / Recommended / Nits
None.

### Verified
- **Recommended #1 landed**: Canonical `_decide_via_llm` return-dict shape `{action, llm_output, tier_used}` documented at `cognitive_agent.py:1716-1720`. Verified at HEAD (matches inlined snippet). L4/L5 short-circuit dict is a valid superset (3 required keys + 3 extras tolerated by `act()` consumers — pattern matches existing `_applied_strategy_ids` extension at `:1751-1753`).
- **Recommended #2 landed**: Contradictory "Do NOT remove the AD-700b journal `tier_used` write" line struck. Revision note clarifies AD-700b/c boundary cleanly.
- `cognitive_agent.py:1701` is `tier=self._resolve_tier()` — D2 replacement target exact.
- `DiagnosticLevel.llm_tier` at `diagnostic_levels.py:43` returns `str | None`; `LLMRequest.tier: str` at `types.py:227` confirmed.
- 7 tests cover all 5 levels + 2 defensive scoping cases.
- Phantom-API sweep: clean.
