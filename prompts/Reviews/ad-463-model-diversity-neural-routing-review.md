# Review: AD-463 — Model Diversity & Neural Routing (Foundation v1)

**Reviewer:** Architect (verify-first review of own draft)
**Date:** 2026-05-01
**Verdict:** ⚠️ **Conditional** — `LLMRequest` has no `agent_id` field; `getattr(request, "agent_id", "")` always returns "" so HebbianRouter integration is dead code in v1. Section 3's call-site SEARCH/REPLACE is hand-waved ("Builder must grep `complete()` body"). Two mechanical fixes; otherwise the foundation design is sound.

The dispatch reserved 1 ⚠️ tolerance for AD-463 (highest-risk foundation work). This review consumes that tolerance.

---

## Required (must fix before building)

### 1. `LLMRequest` has no `agent_id` field — HebbianRouter integration is dead

Section 3:

```python
override = self._resolve_model_for_tier(tier, getattr(request, "agent_id", ""))
```

And Section 2's `ModelRouter.choose()` consults HebbianRouter only when `agent_id` is non-empty:

```python
if self._hebbian is not None and agent_id:
    try:
        weighted = [
            (d, self._hebbian.get_weight(agent_id, d.name))
            for d in candidates
        ]
        positive = [(d, w) for d, w in weighted if w > 0.0]
        if positive:
            chosen = max(positive, key=lambda pair: pair[1])[0]
            reason = "hebbian-weight"
```

Verified — `LLMRequest` has NO `agent_id` field:

```
view src/probos/types.py:227-237

@dataclass
class LLMRequest:
    """A request to the LLM client."""

    prompt: str
    system_prompt: str = ""
    tier: str = "standard"
    temperature: float = 0.0
    top_p: float | None = None
    max_tokens: int = 2048
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
```

`getattr(request, "agent_id", "")` returns `""` always. The HebbianRouter integration code is dead — `if self._hebbian is not None and agent_id:` is always False because `agent_id == ""`.

The prompt's no-theater discipline section claims:
> Cost-aware selection ... v1's `ModelDescriptor` carries `cost_per_million_input_tokens` and `cost_per_million_output_tokens` fields ...

The cost-aware selection works (cost is a property of `ModelDescriptor`, not `request`). But the **HebbianRouter integration is theater** — the entire `if self._hebbian is not None and agent_id:` branch is unreachable.

This is exactly the AD-455 v1-vs-AD-455b precedent the prompt cites. The prompt promises a real consumer hook but the consumer can never be triggered.

**Action:** Pick one resolution:

- **(a)** Add `agent_id: str = ""` to `LLMRequest`. Substantive change to a foundation type — needs an audit of all `LLMRequest()` construction sites to ensure `agent_id` is populated. Estimated 20+ call sites; this is a real refactor.

- **(b) Drop HebbianRouter integration from v1; defer wholesale to AD-463d.** ModelRouter v1 chooses by cost/availability only. The `hebbian_router=None` parameter to `ModelRouter.__init__` becomes the only valid value in v1; remove the integration code. Section 6 finalize wiring drops the `hebbian_router=...` kwarg.

- **(c)** Add a separate routing API that takes `agent_id` explicitly: `route_for_agent(tier: str, agent_id: str) -> RoutingDecision`. Keep `choose(tier)` as the agent-agnostic API. The hook in `_complete_inner` passes empty string; AD-463d adds the agent-aware caller.

**Recommended (b)** — cleanest no-theater fix. v1 ModelRouter does cost-aware + availability-aware selection only. HebbianRouter integration moves wholesale to AD-463d with the existing AD-463d deferral note already in the prompt body. Drop ~30 lines of dead integration code.

This is the single biggest finding in Wave 7. The dispatch's pre-flagged drafting decision (HebbianRouter integration) was indeed the highest-risk surface.

### 2. Section 3 SEARCH/REPLACE for `complete()` is hand-waved

Section 3 says:

> Specifically: in the request-construction block of `complete()`, find where the model name is set (typically `tc["model"]` or similar). Before that line, call `override = self._resolve_model_for_tier(tier, getattr(request, "agent_id", ""))`; use `override or tc["model"]` for the request's model name.

This is "Builder will figure out the anchor" hand-waving — exactly the pattern Wave 5 retrospective convention #6 forbids.

Verified — the actual call path is `complete()` (line 385) → `_complete_inner()` (line 411) → model resolution at line 445:

```
view src/probos/cognitive/llm_client.py:441-447
  441: last_error = ""
  442: for attempt_tier in fallback_tiers:
  443:     tc = self._tier_configs.get(attempt_tier, self._tier_configs["standard"])
  444:     client = self._clients[self._client_key(attempt_tier)]
  445:     model = tc["model"]
  446:     api_format = tc.get("api_format", "openai")
  447:     tier_timeout = tc["timeout"]
```

The call site is in `_complete_inner`, NOT `complete`. The variable is `attempt_tier` (the fallback chain may try multiple tiers). The model name is set at line 445.

**Action:** Section 3 must specify a concrete SEARCH/REPLACE block:

```python
SEARCH:
        for attempt_tier in fallback_tiers:
            tc = self._tier_configs.get(attempt_tier, self._tier_configs["standard"])
            client = self._clients[self._client_key(attempt_tier)]
            model = tc["model"]
            api_format = tc.get("api_format", "openai")
            tier_timeout = tc["timeout"]

REPLACE:
        for attempt_tier in fallback_tiers:
            tc = self._tier_configs.get(attempt_tier, self._tier_configs["standard"])
            client = self._clients[self._client_key(attempt_tier)]
            # AD-463: ModelRouter override (caller-optional; absent = existing path)
            _override = self._resolve_model_for_tier(attempt_tier)
            model = _override or tc["model"]
            api_format = tc.get("api_format", "openai")
            tier_timeout = tc["timeout"]
```

After Required #1 (b) resolves to "drop HebbianRouter from v1", `_resolve_model_for_tier` no longer needs `agent_id`. Simplifies the helper signature.

### 3. `_resolve_model_for_tier` returns `decision.chosen_model or None` — empty-string handling

```python
return decision.chosen_model or None
```

ModelRouter's `RoutingDecision.chosen_model` may be `""` (empty string in the no-models-anywhere fallback). The `or None` correctly converts `""` to `None` so the existing `tc["model"]` path runs. ✅ Correct semantics.

But: if the `ModelRouter.choose()` raises an exception, the helper logs and returns `None` (line 80+). The defensive guard there is correct. Verified.

This is acceptable as-is. Flagging only because the `or None` semantic is non-obvious; the docstring should say "returns `None` if router is absent OR if router returns empty model name."

**Action:** add docstring clarification to `_resolve_model_for_tier` Section 3.

---

## Recommended

### 1. `ModelRegistry.mark_unavailable` / `mark_available` are operator-side; no consumer in v1

```python
def mark_unavailable(self, name: str) -> bool:
    ...
def mark_available(self, name: str) -> bool:
    ...
```

These methods are defined for "a future AD-463b health probe" but no v1 consumer calls them. They're not theater (operator can manually mark via REPL/admin endpoint), but they're dead in v1.

Document explicitly in "What This Does NOT Change":
- Health probe (auto-mark unavailable on consecutive failures) deferred to AD-463b.
- v1 includes the `mark_*` methods so AD-463b doesn't need to touch the registry; it only adds the consumer.

### 2. `ModelDescriptor` `cost_per_million_input_tokens=0.0` for unknown is ambiguous

```python
cost_per_million_input_tokens: float = 0.0   # USD; 0 => unknown / free
```

Sentinel value 0 means "unknown OR free." A free model genuinely has cost=0; an unknown-cost model is operationally distinct (don't route by cost when cost is unknown).

Recommend `Optional[float]` with `None = unknown, 0.0 = explicitly free, > 0.0 = priced`. AD-467d Cost Tracker will need this distinction.

For v1 the ambiguity is acceptable (default seeded values are all >0). Document in the docstring; AD-463b may refine.

### 3. ModelRouter cost-ceiling filter applies BEFORE HebbianRouter weight check

The Required #1 (b) resolution drops the HebbianRouter check. If Required #1 (a) or (c) is chosen, the order matters:

```python
candidates = self._registry.by_tier(tier)
if cost_ceiling is not None:
    candidates = [d for d in candidates if d.cost_per_million_output_tokens <= cost_ceiling]
```

Cost filter eliminates expensive models. Then HebbianRouter (if used) picks among cheapest survivors. This is the right order — cost is a hard gate, weight is a soft preference.

✅ Order is correct. Flagging for review-trail completeness.

### 4. Section 6 LLM client wiring uses private attribute assignment

```python
llm_client._model_router = runtime.model_router
```

This sets a private attribute (`_model_router`) on the LLM client AFTER construction. The prompt acknowledges this as "wiring an architect-defined public attribute directly to an architect-defined private slot in the LLM client; not a Demeter violation because both ends are AD-463-introduced surface."

Acceptable, but cleaner: pass `model_router` to `OpenAICompatibleClient.__init__` at the call site where the client is constructed (typically `runtime.py` LLM client setup at line 347). That way the parameter flows through the constructor as designed in Section 3.

But: Section 6's post-construction assignment is needed because `runtime.model_router` is wired in `finalize.py` (after the LLM client is already constructed). Finalize.py can't go back and re-construct the LLM client.

**Action (cosmetic):** rename the slot to be public-leading (`self.model_router = None`) instead of `self._model_router = None`. Then the finalize.py assignment isn't poking through privacy. This matches the public-attribute Wave 5 convention #1 — private slots should be reserved for runtime-internal state, not externally-wired services.

### 5. Test 13 (`test_router_hebbian_weight_overrides_cost`) becomes irrelevant under Required #1 (b)

If Required #1 resolves toward (b), Tests 13 and 14 (Hebbian-related) are dropped. Test count goes from 15 to 13.

---

## Nits

### 1. Footer line drift on `runtime.emit_event`

Footer says line 775; actual is 785. Off by 10. Update.

### 2. `ModelRegistry.__post_init__` mutation order

```python
def __post_init__(self) -> None:
    for d in _DEFAULT_DESCRIPTORS:
        self._descriptors[d.name] = d
```

Iteration order matters only if descriptors share names — they don't (verified by inspection of `_DEFAULT_DESCRIPTORS`). Cosmetic: dict-comprehension would be one line.

### 3. `OpenAICompatibleClient.__init__` parameter ordering

Adding `model_router: Any = None` as the new last parameter — keyword-only via `*` would be safer. Position-7 in a 9-parameter signature is fragile if a caller later adds a new positional param.

Cosmetic refinement: `*, model_router: Any = None` (keyword-only).

### 4. `RoutingDecision.fallback: bool = False` — explicit field

Mirror of AD-451's `ReconciliationOutcome.third_invoked`. Good documentation surface for downstream consumers.

---

## Verified

### Public-attribute wiring (Wave-5 convention #1) — ⚠️ Mostly applied; Recommended #4

`runtime.model_registry`, `runtime.model_router` — both public. ✅

`llm_client._model_router` is private; Recommended #4 says rename to public.

### stdlib-only persistence (Wave-5 convention #2) — ✅ Applied

No new pyproject deps. v1 ships in-memory registry and router only.

### Coordinator-then-dispatch (Wave-5 convention #3) — ✅ Applied (aggressively)

6 of 10 capabilities deferred to AD-463b/c/d/e/f and AD-467d. v1 ships only the foundation primitives. ✅ This is the canonical no-theater foundation example.

### Superset-filter discipline (Wave-5 convention #4) — ✅ Applied

`_resolve_model_for_tier` returns `None` when router is absent → existing tier→model path runs. Existing call sites that don't pass `model_router` are unaffected. ✅

### `init_<phase>` startup signatures (Wave-5 convention #5) — ✅ Applied

Section 6 wires from `startup/finalize.py` (receives `runtime` directly). ✅

### Verify-first for anchors (Wave-5 convention #6) — ⚠️ Required #1 + #2

The footer is missing the critical greps:

```
grep -n "agent_id\|class LLMRequest" src/probos/types.py    # Required #1
grep -n "model = tc..model" src/probos/cognitive/llm_client.py    # Required #2
```

Both would have caught the issues. ✅ Fixable with concrete SEARCH/REPLACE in Section 3 (Required #2) and Required #1 (b) drop.

### No-theater discipline (Wave-5 convention #7) — ⚠️ Required #1

Before Required #1 fix: HebbianRouter integration is dead code (theater). After Required #1 (b): v1 ships cost-aware + availability-aware routing with one real consumer hook in `_complete_inner`. Real work, no theater.

### TYPE_CHECKING cross-layer imports (Wave-6 note) — ✅ Applied

Section 1 `from probos.cognitive.model_registry import ...` under `TYPE_CHECKING`. No layer violation (cognitive→cognitive). ✅

### ASCII-only source comments (Wave-6 note) — ✅ Applied

Verified — no unicode arrows / em-dashes in source code blocks. Uses `--`, `<-`, `->`. ✅

### Anchor-chain fallback (Wave-6 note) — ✅ Applied

Section 5 anchor chain terminates at `orders: OrdersConfig = OrdersConfig()  # AD-440`. ✅

### Section 0 EventTypes — ✅ Clean

`MODEL_ROUTED`, `MODEL_FALLBACK` — verified absent. No collision with other Wave 7 prompts.

### Distinct from existing `BaseLLMClient` ABC — ✅ Verified

```
grep -n "class BaseLLMClient\|class OpenAICompatibleClient\|class MockLLMClient" src/probos/cognitive/llm_client.py
  22: class BaseLLMClient(ABC):
  44: class OpenAICompatibleClient(BaseLLMClient):
  823: class MockLLMClient(BaseLLMClient):
```

AD-463 EXTENDS this hierarchy via the optional `model_router` parameter; does NOT replace it. ✅

### Distinct from existing `HebbianRouter` — ✅ Verified

`mesh/routing.py:39 HebbianRouter` with public `get_weight()` at `routing.py:142`. AD-463's read is via the existing public API only. ✅

### v1 scope realism — ✅ Reasonable

4 of 10 capabilities ship v1; 6 deferred. This is aggressive but aligned with the no-theater discipline. The "real consumer hook" in `_complete_inner` is the critical piece that makes v1 non-theater.

After Required #1 (b) drops HebbianRouter, v1 is even tighter: ModelRegistry + ModelRouter (cost-aware) + one real consumer hook = 3 capabilities.

### `BaseLLMClient`, `MockLLMClient`, `HebbianRouter`, `CognitiveJournal` unchanged — ✅ Documented

The "What This Does NOT Change" section is comprehensive. ✅

### Foundation-hook scope — ✅ within `OpenAICompatibleClient` only

The dispatch's hard-stop check ("if AD-463's foundation hook turns out to require BaseLLMClient ABC changes (not just an OpenAICompatibleClient patch), surface — that's a much bigger blast radius") — verified clean. The hook is on `OpenAICompatibleClient` only; `BaseLLMClient` ABC is not touched. The `_resolve_model_for_tier` is a private method on the concrete class. ✅

### Test plan — ⚠️ 15 tests; 2 (Tests 13, 14) drop under Required #1 (b)

After Required #1 (b), test count is 13. Tests 13 and 14 (Hebbian) become tests for AD-463d. ✅

---

## Verdict Summary

**Three blocking issues:**
1. `LLMRequest.agent_id` is phantom — HebbianRouter integration is dead. Drop Hebbian from v1 (Recommended (b)) or restructure.
2. Section 3 SEARCH/REPLACE for `complete()` is hand-waved — provide concrete block at `_complete_inner` line 442-447.
3. `_resolve_model_for_tier` empty-string semantics need docstring clarification.

**5 Recommended findings:** dead methods, sentinel ambiguity, filter ordering, post-construction wiring, test count adjustment.

**4 Nits:** cosmetic.

**Wave-5/6 conventions:** all applied except #6 (verify-first) and #7 (no-theater) — Required #1 + #2 resolution restores both.

**Build-readiness after fix:** ~30 minutes architect time. Required #1 (b) is the substantial decision — drops HebbianRouter from v1, simplifies code, eliminates theater. Required #2 is a concrete SEARCH/REPLACE block.

**This is the highest-risk Wave 7 prompt.** The dispatch reserved 1 ⚠️ tolerance for AD-463; this review consumes that tolerance.

**Recommended build order:** AD-463 last in Wave 7 (after AD-466, AD-456, AD-528, AD-467). Foundation hook touches `OpenAICompatibleClient.complete()` — best to land last so the LLM client surface is stable across the rest of the wave.

---

## Second-Pass Review (2026-05-01)

**Verdict:** ⚠️ **Conditional** — all 3 Required findings resolved in code (Sections 1-6) and Revision section, BUT the original Solution Overview (lines 22-49) was not updated and still describes HebbianRouter integration as v1 work. This contradicts the Revision section's wholesale defer. Mechanical 4-line fix.

The dispatch's tolerance criterion ("Verdicts target: 5 ✅. Tolerance: none") means this surfaces back per the standing rule.

### Resolution Audit

| Pass-1 Required | Status | Evidence in revised prompt |
|---|---|---|
| R#1: LLMRequest.agent_id phantom; HebbianRouter dead code | ✅ Resolved in code, ⚠️ stale in overview | Section 2 (lines 191-368): `ModelRouter.choose()` no longer accepts `agent_id`; `__init__` drops `hebbian_router`; `RoutingDecision.agent_id` field dropped. Section 6 (line 547+) drops `hebbian_router=...` ctor kwarg. Section 7 / "What This Does NOT Change" (line 600) explicitly defers HebbianRouter to AD-463d. **BUT:** Solution Overview lines 27, 28, 45 still describe HebbianRouter integration as v1 work. See New Finding #1 below. |
| R#2: Section 3 SEARCH/REPLACE hand-waved | ✅ Resolved | Section 3 split into 3a/3b/3c (lines 370-473). Section 3c has verbatim SEARCH/REPLACE block at `cognitive/llm_client.py:441-447` (verified). |
| R#3: _resolve_model_for_tier empty-string semantics | ✅ Resolved | Section 3b docstring (lines 416-431) covers all three return paths. |

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| rec#1: dead mark_unavailable methods | 📦 Deferred | Kept in v1 as deferred-consumer seam for AD-463b. Acceptable. |
| rec#2: cost sentinel ambiguity | 📦 Deferred | Documentation-only refinement; AD-463b. Acceptable. |
| rec#3: filter ordering (HebbianRouter) | ✅ N/A | HebbianRouter dropped per R#1. |
| rec#4: post-construction wiring → public attribute | ✅ Applied | `OpenAICompatibleClient.model_router` is now public (no underscore); Section 3a line 408. Section 6 wiring (line 553) writes to public attribute. |
| rec#5: test count update | ✅ Applied | Test count 15 → 13; tests 13-14 (Hebbian) deferred to AD-463d. |

| Pass-1 Nits | Status | Notes |
|---|---|---|
| nit#1: footer line drift | ✅ Applied | `runtime.emit_event` line corrected to 785. |
| nit#2, #3, #4 | ✅ Applied or preserved | Cosmetic. |

### New Findings (introduced during revision)

1. **Solution Overview (lines 4, 27, 28, 45) still describes HebbianRouter integration as v1 work.** The Revision section explicitly says HebbianRouter is wholesale deferred to AD-463d, but the Solution Overview at the top of the prompt was not updated. Specific contradictions:

   - **Line 4** (Dependencies header): `Reads HebbianRouter.get_weight() (mesh/routing.py:142) for routing-bias.` — this dependency claim is now false; v1 does NOT read HebbianRouter.
   - **Line 27** (Solution Overview module list): `ModelRouter consults the registry + (optionally) HebbianRouter.get_weight() to pick a model for a given (tier, agent_id) request. Stateless. Read-only over both inputs.` — both the HebbianRouter integration and the `agent_id` parameter are dropped per R#1.
   - **Line 28** (Real consumer hook description): `complete() consults runtime.model_router.choose(tier, agent_id)` — this misstates two things post-revision: the call site is `_complete_inner` (not `complete`), and `agent_id` is dropped.
   - **Line 45** (Six deferred list): `Brain diversity / per-agent model preference -- AD-463d. v1 reads HebbianRouter for routing-bias hint only.` — the second sentence ("v1 reads HebbianRouter") is now false; v1 does NOT read HebbianRouter.

   **Severity:** Required-class. A Builder reading the prompt top-to-bottom encounters contradictions before reaching the Revision section. The implementation sections (1-7) and Tests are correct; "What This Does NOT Change" is correct; the Revision section is correct. But the Solution Overview header is misleading.

   **Action:** mechanical 4-line fix:
   - Line 4: change `Reads HebbianRouter.get_weight() ... for routing-bias.` to `**HebbianRouter integration deferred to AD-463d** (LLMRequest does not carry agent context today; see Revision section).`
   - Line 27: change `ModelRouter consults the registry + (optionally) HebbianRouter.get_weight() to pick a model for a given (tier, agent_id) request.` to `ModelRouter consults the registry to pick a model for a given tier (cost-aware + availability-aware + cost-ceiling). Per-agent routing bias deferred to AD-463d.`
   - Line 28: change `complete() consults runtime.model_router.choose(tier, agent_id)` to `_complete_inner() consults runtime.model_router.choose(tier=...)`.
   - Line 45: change `v1 reads HebbianRouter for routing-bias hint only.` to `v1 routes by tier+cost only; HebbianRouter integration deferred to AD-463d once LLMRequest.agent_id (or equivalent) is established.`

   **Time to fix:** ~5 minutes architect time. After this fix, AD-463 lands at ✅ Approved.

### Verified Against Revised Codebase Claims

- Section 3c SEARCH block matches `cognitive/llm_client.py:441-447` verbatim — confirmed.
- `_complete_inner` exists at `cognitive/llm_client.py:411` (verified pass-1).
- `LLMRequest` at `types.py:227` has NO `agent_id` field — confirmed (proves the wholesale defer is correct).
- `OpenAICompatibleClient.__init__` keyword-only `model_router` parameter via `*` separator — confirmed in Section 3a line 406-408.
- `self.model_router` (public, no underscore) at line 408 — confirmed.
- Section 6 finalize wires `llm_client.model_router = runtime.model_router` to a public attribute — confirmed.
- Test count 15 → 13 with rationale documented — confirmed.

### Cross-Cutting Convention Audit

| Cross-cutting fix | Applied? | Evidence |
|---|---|---|
| Phantom-API fix: AD-463 HebbianRouter | ✅ Applied in code | But ⚠️ Solution Overview text not updated — see New Finding #1. |
| AD-463 SEARCH/REPLACE concretization | ✅ Applied | Section 3c verbatim block. |

### Hard-Stop Audit

The dispatch flagged: "If AD-463 wholesale-defer-HebbianRouter would gut the prompt's Section title or scope claims — surface to architect; v1 should re-frame to focus on ModelRegistry + Router + consumer hook only."

The Revision section correctly reframes v1 scope. But the Solution Overview header was not reframed in the same pass. The Builder may execute the prompt correctly (Sections 1-7 are clean) but the prompt's stated scope is contradictory across sections. New Finding #1 captures this; ⚠️ Conditional verdict reflects it.

### Verdict

**⚠️ Conditional.** All 3 Required findings resolved in implementation code; Recommended findings applied. **One new Required-class finding** introduced during revision: Solution Overview lines 4, 27, 28, 45 contradict the Revision section. Mechanical 4-line edit fixes it. After fix, AD-463 verdict is ✅ Approved.

Surface back to dispatching architect per the standing tolerance rule. Recommended remediation: 5-minute architect edit of the 4 lines, then re-pass review on AD-463 only.
