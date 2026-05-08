# AD-700c v1 — Diagnostician per-call LLM tier override from `level_llm_tier`

**Issue:** [#509](https://github.com/seangalliher/ProbOS/issues/509)
**Type:** Architecture Decision (cognitive routing — narrow)
**Depends on:** AD-700 (DiagnosticLevel + `level_llm_tier` in `perceive_result`); CognitiveAgent `_decide_via_llm` LLM tier resolution at HEAD.
**Wave:** 129

## Goal

`DiagnosticianAgent.perceive()` already populates `result["level_llm_tier"]` (`"deep"` for L1, `"fast"` for L2/L3, `None` for L4/L5). Today this value is dropped on the floor — `_decide_via_llm()` uses `self._resolve_tier()` which returns the agent's static default `"standard"`. AD-700c routes the per-call tier override through to the `LLMRequest.tier` field so L1 actually uses the deep tier and L4/L5 short-circuit to no-LLM execution.

## Verified Against Codebase (2026-05-08)

- ✅ `src/probos/agents/medical/diagnostician.py:73–141` `perceive()` populates `result["level_llm_tier"]` via `level.llm_tier` (returns `"deep"` / `"fast"` / `None` per `diagnostic_levels.py:53–61`).
- ✅ `src/probos/agents/medical/diagnostic_levels.py:53–61` `DiagnosticLevel.llm_tier` mapping: `L1 -> "deep"`, `L2 -> "fast"`, `L3 -> "fast"`, `L4 -> None`, `L5 -> None`.
- ✅ `src/probos/cognitive/cognitive_agent.py:6055–6060` `_resolve_tier()` returns `"standard"` by default. **No subclass override exists on DiagnosticianAgent** — verified by reading `diagnostician.py` (no `_resolve_tier` method).
- ✅ `src/probos/cognitive/cognitive_agent.py:1716-1720` defines the canonical `_decide_via_llm` return-dict shape (after the LLM call returns):

  ```python
  decision = {
      "action": "execute",
      "llm_output": response.content,
      "tier_used": response.tier,
  }
  ```

  Three required keys: `action: str`, `llm_output: str`, `tier_used: str`. Extra keys are tolerated by downstream `act()` consumers (verified by reading the existing `applied_strategy_ids` extension at `cognitive_agent.py:1751-1753` which appends `_applied_strategy_ids` to the same dict). The AD-700c short-circuit returns a **valid superset** of this shape: `{"action": "execute", "llm_output": "", "tier_used": "none"}` plus three extras (`level`, `level_rank`, `short_circuit_reason`). The required-key contract is preserved; the journal-record block at `:1722-1748` is skipped entirely because the short-circuit `return`s before reaching it (no `response` object is constructed, so no journal-write attempt). Safe.
- ✅ `src/probos/cognitive/cognitive_agent.py:1701` `request = LLMRequest(prompt=user_message, system_prompt=composed, tier=self._resolve_tier())` — this is the single call site where tier is wired into the LLM request.
- ✅ `src/probos/types.py:227` `class LLMRequest` is a dataclass with a `tier: str` field; per-call tier is the canonical, stable mechanism for routing through the tiered LLM client (no client-side hack required). **The dispatch's "if not, surface as blocking sub-AD" hard-stop is NOT triggered** — per-call tier override is already supported via the dataclass field.
- ✅ `_decide_via_llm()` at `cognitive_agent.py:1411` accepts an `observation: dict`. The `level_llm_tier` value is in `observation` (since DiagnosticianAgent's `perceive()` returns it on the result dict).
- ✅ AD-700 short-circuit for L4/L5 (no LLM) is partially implemented: `perceive()` skips the VitalsMonitor scan for L5 only (line 87 `if self._runtime and level is not DiagnosticLevel.L5:`). **L4/L5 still call `_decide_via_llm` and burn an LLM call.** AD-700c closes this by returning a deterministic short-circuit decision dict before the LLM call when `level_llm_tier is None`.

## Scope

A narrow three-point change: (1) honor `observation["level_llm_tier"]` in `_decide_via_llm`, (2) short-circuit L4/L5 to a deterministic decision before any LLM call, (3) preserve existing behavior for all non-diagnostic intents and all CognitiveAgent subclasses that don't set `level_llm_tier`. Do NOT modify the LLM client, the tier registry, the journal, or any other agent.

## Deliverables

### D1. Helper on CognitiveAgent: `_resolve_tier_for_observation`

Add a new method (do NOT modify `_resolve_tier()` itself — it's the static fallback):

```python
def _resolve_tier_for_observation(self, observation: dict) -> str:
    """AD-700c: Per-call tier override.

    If ``observation`` carries ``level_llm_tier`` (set by an agent's
    ``perceive()`` — currently DiagnosticianAgent for ``diagnose_system``
    intents), use that as the LLM tier for this single call. Otherwise
    fall back to ``self._resolve_tier()`` (the static per-agent default).

    Returns ``""`` (empty string) iff the observation explicitly requests
    no LLM call (level_llm_tier is None). Callers must check for the
    empty return and short-circuit before constructing an ``LLMRequest``.
    """
    override = observation.get("level_llm_tier")
    if override is None and "level_llm_tier" in observation:
        # Explicit None -> no LLM
        return ""
    if isinstance(override, str) and override:
        return override
    return self._resolve_tier()
```

### D2. Honor the override in `_decide_via_llm`

Replace the line at `cognitive_agent.py:1701`:

```python
# BEFORE
tier=self._resolve_tier(),

# AFTER
tier=self._resolve_tier_for_observation(observation),
```

Immediately above the `LLMRequest(...)` construction, add a short-circuit guard for the L4/L5 path. If the resolved tier is empty (explicit `None` from `level_llm_tier`), return a deterministic decision dict without invoking the LLM:

```python
_per_call_tier = self._resolve_tier_for_observation(observation)
if _per_call_tier == "" and observation.get("intent") == "diagnose_system":
    # AD-700c: L4/L5 are deterministic depth bands -- no LLM call.
    # Return a structured short-circuit so the act() phase still
    # produces a panel-renderable diagnosis from the perceive context.
    return {
        "action": "execute",
        "llm_output": "",
        "tier_used": "none",
        "level": observation.get("level", ""),
        "level_rank": int(observation.get("level_rank", 0)),
        "short_circuit_reason": "ad-700c-no-llm-tier",
    }
```

The short-circuit ONLY fires for `diagnose_system` — non-diagnostic intents continue through the LLM path even if a hypothetical future caller sets `level_llm_tier=None` on a non-diagnostic observation (defensive scoping).

### D3. Tests in `tests/test_ad700c_diagnostician_tier_routing.py`

Minimum 7 tests. Use `pytest-asyncio` and a fake LLM client that records the `LLMRequest.tier` it sees:

1. `test_l1_uses_deep_tier` — observation `{"intent": "diagnose_system", "level_llm_tier": "deep", ...}` -> `LLMRequest.tier == "deep"`.
2. `test_l2_uses_fast_tier` — `level_llm_tier="fast"` -> `tier == "fast"`.
3. `test_l3_uses_fast_tier` — `level_llm_tier="fast"` -> `tier == "fast"`.
4. `test_l4_short_circuits_no_llm` — `level_llm_tier=None`, intent `diagnose_system` -> fake LLM client is NOT called; result dict has `"tier_used": "none"` and `"short_circuit_reason": "ad-700c-no-llm-tier"`.
5. `test_l5_short_circuits_no_llm` — same as L4.
6. `test_non_diagnose_intent_uses_static_resolve_tier` — observation lacks `level_llm_tier` -> falls back to `self._resolve_tier()` (default `"standard"`). LLM IS called.
7. `test_non_diagnose_intent_with_none_tier_still_uses_llm` — observation has `level_llm_tier=None` AND `intent="medical_alert"` -> short-circuit does NOT fire (defensive scoping); LLM IS called with the static fallback tier.

Use the existing `_FakeLLMClient` test stub pattern from `tests/test_cognitive_journal.py` or the closest sibling — Builder picks the canonical fake.

## Non-Goals

- Do NOT modify `_resolve_tier()` itself (it's the static fallback for non-overriding callers).
- Do NOT subclass `_resolve_tier` on DiagnosticianAgent — the per-call override is the right seam.
- Do NOT modify `DiagnosticianAgent.perceive()` — `level_llm_tier` is already populated.
- Do NOT change `LLMRequest`, the LLM client tier registry, or the Copilot proxy config.
- Do NOT change `BaseAgent`, `IntentMessage`, `RuntimeProtocol`.
- Do NOT add a config flag to disable the override — the override is on by definition for any agent that sets `level_llm_tier` on its perceive result.

## Acceptance

- Focused: `pytest tests/test_ad700c_diagnostician_tier_routing.py -v -n 0` — 7/7 pass.
- Full gate: `pytest tests/ -q -n 16 --dist=loadfile` — green or only environmental flakes. Existing CognitiveAgent tests must continue to pass — verify by spot-checking that `_resolve_tier()` is still called for any agent that does not set `level_llm_tier`.
- `git diff` shows changes only in: `src/probos/cognitive/cognitive_agent.py` (two small additions: new helper + two-line change in `_decide_via_llm`) and the new test file.
- Comply with engineering principles in `.github/copilot-instructions.md`.

## Tracking

- Closes [#509](https://github.com/seangalliher/ProbOS/issues/509).
- DECISIONS.md entry stub: AD-700c — per-observation LLM tier override on CognitiveAgent; honors AD-700 `level_llm_tier`; L4/L5 short-circuit for `diagnose_system`.

## Revision (2026-05-08)

- **Recommended #1 applied**: Documented the canonical `_decide_via_llm` return-dict shape (`{action, llm_output, tier_used}` at `cognitive_agent.py:1716-1720`) in Verified-Against-Codebase. Confirmed the L4/L5 short-circuit dict is a valid superset (all three required keys present; extras tolerated by `act()` consumers). Confirmed the short-circuit `return` skips the journal-record block at `:1722-1748` entirely — no `response` object means no journal-write attempt; safe.
- **Recommended #2 applied**: Removed the contradictory "Do NOT remove the AD-700b journal `tier_used` write" line from Non-Goals. AD-700b adds `level` and `level_rank` columns (not `tier_used`); the journal already has a `tier` column from AD-431 populated from `response.tier`; for short-circuit rows there is no journal write because no `response` exists. The Non-Goals line was dead and is struck per the pass-1 review's Option (b).
