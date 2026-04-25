# BF-204: Add Grounding Criterion to Evaluate Handler

**Priority:** High (confabulation is actively degrading crew quality)  
**Related:** AD-639 (Chain Personality Tuning), AD-540/541 (Memory Anchoring Protocol), BF-184/187 (Social Obligation Bypass), BF-191 (JSON Rejection)

## Bug Description

Agents confabulate — they fabricate thread IDs, timestamps, metrics, and entire investigations. The Federation Constitution (AD-540/541) has comprehensive anti-confabulation standing orders (Memory Anchoring Protocol, Knowledge Source Attribution), injected into COMPOSE and ANALYZE via `compose_instructions()`. However, EVALUATE's criteria don't check whether claims are grounded in real data.

**Current EVALUATE criteria (ward_room mode):**
1. Novelty
2. Opening quality
3. Non-redundancy
4. Relevance

A beautifully fabricated investigation passes all four. EVALUATE actively rewards confabulation as long as it's *interesting*.

**Compounding factor — defense ordering gap:** The social obligation bypass (BF-184/187) in evaluate.py returns at line 302, BEFORE both BF-191 JSON rejection (line 328) and the proposed grounding check. Ward Room DMs set `_is_dm = True`, triggering social obligation. So DM confabulation — the exact vector observed — bypasses ALL quality gates including BF-191.

**Observed behavior (2026-04-17):** Wesley fabricated thread `f8a9e2b7`, a "15:42 synchronization event", and specific timing metrics (50ms baseline, 200-400ms spikes). Took this to Reed via Ward Room DM. Reed accepted the premise and built an elaborate analytical framework on top of it. Two agents reinforcing each other's hallucinations in DMs. When challenged by the Captain, Wesley correctly self-diagnosed using AD-541 Memory Anchoring Protocol — proving the standing orders work when invoked, they just aren't enforced at the EVALUATE gate.

**Security dimension:** Security standing orders (Threat #6) explicitly name "Cascading Hallucination" — one agent's confabulation accepted by others as fact. This is exactly what happened. AD-554 (convergence detection) and AD-583f (observable state verification) exist but are observational (post-hoc), not preventive.

## Root Cause

Two problems:

1. **EVALUATE checks quality but not truthfulness.** No grounding criterion exists. Standing orders in COMPOSE that prevent confabulation have no enforcement downstream.

2. **Defense ordering is wrong.** Safety checks (BF-191 format validation, BF-204 grounding) run AFTER social obligation bypass. Social obligation means "you must respond" — not "you must respond with fabricated data unchecked." Format and truthfulness checks should run before social obligation because they're safety gates, not quality gates.

## Fix: Two Changes

### Change 1: Reorder Defense-in-Depth — Safety Before Obligation

**Current ordering in evaluate.py `__call__()` (lines 246-455):**
1. No LLM client guard (line 249)
2. Social obligation bypass — BF-184/187 (line 276) ← returns before safety checks
3. Boot camp bypass — AD-638 (line 305)
4. BF-191 JSON rejection (line 328) ← never runs for DMs
5. AD-639 low trust bypass (line 353)
6. LLM evaluation (line 388)

**New ordering:**
1. No LLM client guard (unchanged)
2. **BF-191 JSON rejection** (moved up — safety check, always runs)
3. **BF-204 grounding pre-check** (NEW — safety check, always runs)
4. Social obligation bypass — BF-184/187 (moved down — obligation, not safety)
5. Boot camp bypass — AD-638 (unchanged relative position)
6. AD-639 low trust bypass (unchanged)
7. LLM evaluation with grounding criterion (unchanged)

**Rationale:** BF-191 and BF-204 are deterministic, 0-token safety checks. They should run unconditionally — same as how a fire suppression system doesn't check who's in the room before activating. Social obligation says "respond" but doesn't say "respond with raw JSON" or "respond with fabricated data."

**Implementation:** Move the `compose_output` extraction (currently line 328) and BF-191 block (lines 328-350) above the social obligation block (lines 276-302). Insert BF-204 deterministic check between BF-191 and social obligation.

**Reordered `__call__()` structure:**

```python
async def __call__(self, spec, context, prior_results):
    start = time.monotonic()

    # Guard: no LLM client
    if self._llm_client is None:
        ...  # unchanged

    # Mode dispatch (needed for prompt building later)
    mode_key = spec.prompt_template or _DEFAULT_MODE
    builder = _EVALUATION_MODES.get(mode_key)
    ...  # unchanged

    callsign = context.get("_callsign", "agent")
    department = context.get("_department", "")

    # === SAFETY CHECKS (always run, 0 tokens) ===

    # BF-191: Deterministic JSON rejection — compose output must be natural language
    compose_output = _get_compose_output(prior_results)
    stripped = compose_output.strip()
    if stripped.startswith("{") and ('"intents"' in stripped[:200] or '"intent"' in stripped[:200]):
        ...  # unchanged BF-191 return

    # BF-204: Deterministic grounding pre-check — catch fabricated identifiers
    ...  # NEW — see section below

    # === OBLIGATION/TRUST BYPASSES ===

    # BF-184/187: Social obligation bypass
    if context.get("_from_captain") or context.get("_was_mentioned") or context.get("_is_dm"):
        ...  # unchanged, but now runs AFTER safety checks

    # AD-638: Boot camp quality gate relaxation
    if context.get("_boot_camp_active"):
        ...  # unchanged

    # AD-639: Low trust band — skip evaluation
    if context.get("_chain_trust_band") == "low":
        ...  # unchanged

    # === LLM EVALUATION ===
    system_prompt, user_prompt = builder(...)
    ...  # unchanged
```

**Same reorder in reflect.py:** Move the suppress short-circuit check (line 408, `_should_suppress()`) above social obligation (line 335). Currently suppress runs after social obligation, meaning a DM that EVALUATE recommended suppressing still goes through. After reorder:

```python
# reflect.py __call__() new ordering:
# 1. No LLM client guard
# 2. Suppress short-circuit (EVALUATE said suppress) ← moved up
# 3. Social obligation bypass (BF-185/187) ← moved down
# 4. Boot camp bypass (AD-638)
# 5. AD-639 low trust bypass
# 6. LLM reflection
```

**Why move suppress above social obligation in reflect:** If EVALUATE's deterministic safety check (BF-191 or BF-204) recommended "suppress", that should be honored even for socially-obligated responses. A DM that contains raw JSON or fabricated data should be suppressed, not delivered to the recipient. The agent can regenerate a clean response via the one-shot fallback path.

**However:** The BF-204 grounding check uses `recommendation: "revise"`, not "suppress". So the suppress short-circuit won't catch it. For BF-204 grounding failures in DMs, the flow is: BF-204 catches it → returns `pass=False, recommendation="revise"` → REFLECT receives the verdict → but REFLECT's social obligation bypass returns compose output unchanged.

**Resolution:** BF-204 grounding failures should use `recommendation: "suppress"` for the deterministic pre-check (not "revise"). The compose output contains fabricated data — delivering it unchanged violates grounding rules. The chain will produce `[NO_RESPONSE]`, and the agent will remain silent rather than confabulate. This is the correct behavior: silence > fabrication, even for socially-obligated responses. The agent's standing orders already say "Unable to comply over hallucination" (Bridge standing orders).

### Change 2: Add Grounding Criterion to Evaluate Prompt Builders

For mid and high trust (where the LLM evaluator runs), add a **Grounding** criterion that catches subtler confabulation the deterministic check misses.

#### Ward Room Evaluate (`_build_ward_room_eval_prompt`, line 51)

**Current criteria (lines 60-68):**
```python
criteria = (
    "1. **Novelty** — Contains at least one fact, metric, or conclusion "
    "not already present in the thread.\n"
    "2. **Opening quality** — First sentence states a conclusion, not a "
    "process description. No 'Looking at...', 'I notice...', "
    "'I can confirm...' openers.\n"
    "3. **Non-redundancy** — More than confirming what someone already said.\n"
    "4. **Relevance** — Addresses the thread topic from the agent's "
    "departmental perspective.\n"
)
```

**New criteria:**
```python
criteria = (
    "1. **Novelty** — Contains at least one fact, metric, or conclusion "
    "not already present in the thread.\n"
    "2. **Opening quality** — First sentence states a conclusion, not a "
    "process description. No 'Looking at...', 'I notice...', "
    "'I can confirm...' openers.\n"
    "3. **Non-redundancy** — More than confirming what someone already said.\n"
    "4. **Relevance** — Addresses the thread topic from the agent's "
    "departmental perspective.\n"
    "5. **Grounding** — Claims reference observable data (events, logs, "
    "metrics, thread content) or are clearly marked as inference. "
    "Specific IDs, timestamps, or measurements that cannot be verified "
    "from the provided context are fabrication. Fail this criterion if "
    "the response presents unverifiable specifics as fact.\n"
)
```

Update the JSON response format to include `"grounding"`:
```python
'"criteria": {"novelty": {"pass": true/false, "reason": "..."}, '
'"opening_quality": {"pass": true/false, "reason": "..."}, '
'"non_redundancy": {"pass": true/false, "reason": "..."}, '
'"relevance": {"pass": true/false, "reason": "..."}, '
'"grounding": {"pass": true/false, "reason": "..."}'
```

**AD-639 voice criterion for mid trust becomes #6 (was #5):**
```python
if trust_band == "mid":
    criteria += (
        "6. **Voice** — Response has a distinct voice consistent with the "
        "agent's personality, not generic or clinical.\n"
    )
```

#### Proactive Evaluate (`_build_proactive_eval_prompt`, line 111)

Add the same grounding criterion as #5 after existing criterion 4 (Silence appropriateness). Update JSON format. AD-639 voice becomes #6.

#### Notebook Evaluate (`_build_notebook_eval_prompt`, line 169)

Add grounding criterion as #4 after existing criterion 3 (Differentiation):
```python
"4. **Grounding** — Claims reference observable data or are clearly "
"marked as inference. No fabricated specifics.\n"
```

Update JSON format to include `"grounding"` key.

### Change 3: Deterministic Grounding Pre-Check

Insert after BF-191 and BEFORE social obligation bypass. This is the 0-token safety gate.

```python
# BF-204: Deterministic grounding pre-check — catch fabricated identifiers
# Runs at ALL trust bands, even social obligation. Safety > obligation.
import re
_grounding_source = (context.get("context", "") + " "
                      + json.dumps(_get_analysis_result(prior_results)))
# Hex IDs (6+ chars) in compose output that don't appear in source material
_hex_ids = re.findall(r'\b[0-9a-f]{6,}\b', compose_output.lower())
_ungrounded_ids = [h for h in _hex_ids if h not in _grounding_source.lower()]
if len(_ungrounded_ids) >= 2:
    logger.warning(
        "BF-204: Grounding check failed for %s — %d ungrounded hex IDs: %s",
        context.get("_agent_type", "unknown"),
        len(_ungrounded_ids),
        _ungrounded_ids[:3],
    )
    return SubTaskResult(
        sub_task_type=SubTaskType.EVALUATE,
        name=spec.name,
        result={
            "pass": False,
            "score": 0.0,
            "criteria": {
                "grounding": {
                    "pass": False,
                    "reason": f"Ungrounded identifiers: {_ungrounded_ids[:3]}",
                },
            },
            "recommendation": "suppress",
            "rejection_reason": "confabulation_detected",
        },
        tokens_used=0,
        duration_ms=int((time.monotonic() - start) * 1000),
        success=True,
        tier_used="",
    )
```

**Why `recommendation: "suppress"` not "revise":** The compose output contains fabricated data. Delivering it unchanged (which is what happens if reflect bypasses via social obligation or low trust) would propagate confabulation. Suppress → REFLECT produces `[NO_RESPONSE]` → agent stays silent rather than confabulating. Standing orders: "Unable to comply over hallucination." Silence > fabrication.

**Why threshold of 2+:** A single hex string could be a legitimate reference (e.g., a commit hash mentioned in context). Two or more ungrounded hex IDs strongly suggest fabrication (Wesley's `f8a9e2b7` plus fabricated metrics).

**Why case-insensitive:** Hex IDs may appear in mixed case. Normalize both sides.

**`re` import:** Move `import re` to the module level (top of file, line 13 area) rather than inline.

### Change 4: Reflect — Grounding Reminder for Mid Trust

In reflect.py, for the mid-trust personality-reinforced prompts (AD-639), add grounding awareness to self-critique criteria. Belt-and-suspenders — EVALUATE should catch confabulation, but REFLECT reinforces.

In `_build_ward_room_reflect_prompt` (line 63), in the mid-trust branch (after the "Voice consistency" criterion), add:

```python
"- **Grounding**: Are your claims based on data you actually have? "
"If you cited specific IDs, timestamps, or metrics, can you trace "
"them to your episodic memory or the thread content? Remove or "
"qualify any unverifiable specifics.\n\n"
```

Apply to all three reflect prompt builders (`_build_ward_room_reflect_prompt`, `_build_proactive_reflect_prompt`, `_build_general_reflect_prompt`) in their mid-trust branches.

**No change for high trust:** High trust agents have proven track records.

**No change for low trust:** Low trust skips reflect entirely (AD-639). The BF-204 deterministic check in evaluate handles grounding.

### Change 5: Reflect — Move Suppress Above Social Obligation

**Current reflect.py ordering:**
1. No LLM client guard (line 322)
2. Social obligation bypass — BF-185/187 (line 335) ← returns before suppress
3. Boot camp bypass — AD-638 (line 364)
4. AD-639 low trust bypass (line 386)
5. Suppress short-circuit (line 408) ← never runs for DMs
6. LLM reflection

**New ordering:**
1. No LLM client guard
2. **Suppress short-circuit** (moved up — if EVALUATE said suppress, honor it)
3. Social obligation bypass — BF-185/187 (moved down)
4. Boot camp bypass — AD-638
5. AD-639 low trust bypass
6. LLM reflection

**Rationale:** If EVALUATE's deterministic safety check detected confabulation and recommended "suppress", REFLECT should honor that verdict even for socially-obligated responses. Delivering fabricated data to the Captain is worse than silence.

## Defense-in-Depth Summary (After BF-204)

### Evaluate ordering:
1. No LLM client guard
2. **BF-191 JSON rejection** (deterministic, 0 tokens) — SAFETY
3. **BF-204 grounding pre-check** (deterministic, 0 tokens) — SAFETY
4. Social obligation bypass (BF-184/187) — OBLIGATION
5. Boot camp bypass (AD-638) — TRUST
6. AD-639 low trust bypass — TRUST
7. LLM evaluation with grounding criterion — QUALITY

### Reflect ordering:
1. No LLM client guard
2. **Suppress short-circuit** (honors EVALUATE safety verdicts) — SAFETY
3. Social obligation bypass (BF-185/187) — OBLIGATION
4. Boot camp bypass (AD-638) — TRUST
5. AD-639 low trust bypass — TRUST
6. LLM reflection with grounding reminder (mid trust) — QUALITY

**Principle: SAFETY > OBLIGATION > TRUST > QUALITY**

## Files Modified

| File | Change | Scope |
|------|--------|-------|
| `src/probos/cognitive/sub_tasks/evaluate.py` | Reorder: BF-191 + BF-204 above social obligation. Add grounding criterion to 3 prompt builders. Add deterministic pre-check. Move `import re` to module level. | ~lines 50-375 |
| `src/probos/cognitive/sub_tasks/reflect.py` | Reorder: suppress above social obligation. Add grounding reminder to 3 mid-trust reflect builders. | ~lines 63-420 |

**No new files.** 2 modified files.

## Tests

### New test file: `tests/test_bf204_grounding.py`

**Deterministic grounding check tests (8):**
1. Compose output with 2+ hex IDs not in source → `recommendation: "suppress"`, `rejection_reason: "confabulation_detected"`
2. Compose output with hex IDs that ARE in source → passes (no false positive)
3. Compose output with 1 hex ID not in source → passes (threshold is 2+)
4. Compose output with no hex IDs → passes
5. Case-insensitive matching — `F8A9E2B7` in compose, `f8a9e2b7` in source → passes
6. Grounding check runs BEFORE social obligation (DM with fabricated IDs → caught)
7. Grounding check runs BEFORE AD-639 low trust bypass
8. Grounding check runs AFTER BF-191 JSON rejection

**Defense ordering tests (4):**
9. BF-191 runs before social obligation (DM with raw JSON → caught)
10. BF-204 runs before social obligation (DM with fabricated IDs → caught)
11. Suppress in EVALUATE → REFLECT honors suppress even for DMs
12. Social obligation still approves clean DM responses (no false blocking)

**LLM grounding criterion tests (4):**
13. Ward room eval prompt includes "Grounding" criterion text
14. Proactive eval prompt includes "Grounding" criterion text
15. Notebook eval prompt includes "Grounding" criterion text
16. JSON response format includes `"grounding"` key

**AD-639 integration (voice criterion renumbering) (2):**
17. Mid trust ward room: voice criterion is #6 (not #5)
18. Mid trust proactive: voice criterion is #6 (not #5)

**Reflect grounding tests (3):**
19. Mid trust ward room reflect includes grounding self-check text
20. Mid trust proactive reflect includes grounding self-check text
21. High trust reflect does NOT include grounding self-check (unchanged)

**Integration tests (3):**
22. Full chain with fabricated hex IDs at low trust → grounding suppression before low trust bypass
23. Full chain with fabricated hex IDs in DM → grounding suppression before social obligation
24. Full chain with clean content in DM → social obligation approves normally

**Total: 24 new tests.**

### Existing test updates

**`tests/test_ad639_chain_tuning.py`** — may need minor updates if the defense ordering change affects test assumptions:
- Tests that check social obligation bypasses evaluate may now need to account for BF-191/BF-204 running first
- Tests that check boot camp bypasses may need adjustment if they assume boot camp runs before BF-191
- Run full AD-639 test suite after implementation to catch any breakage

## Verification

1. `pytest tests/test_bf204_grounding.py -v` — all 24 new tests pass
2. `pytest tests/test_ad639_chain_tuning.py -v` — no regressions
3. `pytest -x -n auto` — full suite green

## Engineering Principles Compliance

- **Defense in Depth**: Three layers — deterministic pre-check (always runs, 0 tokens), LLM criterion (mid/high trust), reflect reminder (mid trust). Safety checks run before obligation bypasses.
- **Fail Fast**: Deterministic check catches fabricated hex IDs before spending tokens. `recommendation: "suppress"` prevents fabricated data from reaching recipients.
- **SOLID (S)**: Grounding is a criterion concern — lives in the prompt builders and the pre-check block. No new classes, no new files (except tests).
- **SOLID (O)**: Extended evaluate criteria without modifying handler logic. Same flow, additional criterion, reordered early returns.
- **DRY**: Grounding criterion text is inline in each prompt builder (3 copies, slightly different wording per mode). Acceptable — not worth extracting for 3 variants.

## Rollback

Remove the grounding criterion text from the 3 prompt builders, delete the deterministic pre-check block, and restore the original defense ordering. No config flag — this is a safety fix, not a feature toggle.

## Prior Work Absorbed

- **AD-540/541 (Memory Anchoring Protocol)**: Standing orders exist but aren't enforced in EVALUATE. BF-204 adds enforcement.
- **AD-583f (Observable State Verification)**: Exists but is observational (post-hoc). BF-204 is preventive (pre-delivery).
- **AD-554 (Convergence Detection)**: Runs after notebook write. BF-204 catches confabulation before it reaches the channel.
- **AD-506b (Peer Repetition)**: Ward Room channels only, not DMs. BF-204 covers DMs via the reordered defense chain.
- **BF-191 (JSON Rejection)**: Pattern replicated for BF-204. Also fixed the ordering gap — BF-191 now also runs before social obligation.

## Deferred

- **Extended deterministic heuristics**: Fabricated timestamps (e.g., "15:42" with no source), fabricated metrics ("200-400ms" with no source). More complex to implement without false positives. Measure first.
- **DM peer repetition detection**: Extend AD-506b to cover Ward Room DM channels. Separate concern — AD-506b follow-up.
- **Trust penalty for confabulation**: Grounding failure should feed into trust network as a negative signal. Connects to Counselor monitoring. Separate AD.
- **AD-583f integration**: Connect BF-204 grounding failures to the ObservableStateVerifier for richer verification. Future enhancement.
