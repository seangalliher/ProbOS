# Review: BF-257 — DM Receive Rate Limiter

**Reviewer:** Architect
**Date:** 2026-05-02
**Verdict:** ⚠️ **Conditional** — diagnosis is correct, design is sound, two phantom-API findings need mechanical fixes plus three significant cross-prompt concerns about default-tuning that affect existing tests outside the prompt's anticipated scope.

The verify-first slip is exactly the Wave 8-shape failure mode (phantom class name + line-number drift). The design itself — bidirectional pair key, sliding window with lazy pruning, captain exemption, deferred-not-dropped semantics — is correct and matches the no-theater + coordinator-then-dispatch + superset-filter conventions cleanly.

---

## Required (must fix before building)

### 1. Class name is `ProactiveCognitiveLoop`, not `ProactiveCognitive`

[`src/probos/proactive.py:146`](src/probos/proactive.py#L146): `class ProactiveCognitiveLoop:`

The prompt body and tests reference `ProactiveCognitive`. Three fixes:

- **Section 2 heading:** "Add Receive Tracking State to `ProactiveCognitive.__init__`" → `ProactiveCognitiveLoop.__init__`.
- **Test class `TestDmResponseBudget._make_proactive`:** `from probos.proactive import ProactiveCognitive` → `from probos.proactive import ProactiveCognitiveLoop`. Same for the `types.MethodType(ProactiveCognitive._dm_response_budget_exceeded, obj)` line.
- **DECISIONS.md draft entry:** mentions "ProactiveCognitive" — should be "ProactiveCognitiveLoop" or "the proactive loop."

This is exactly the phantom-API failure mode the Wave 5-7 retrospective addendum convention #6 covers. A scripted dispatch-time pre-check (the Wave 8 retrospective candidate) would have caught it.

### 2. Line numbers don't match live source

The prompt asserts:

- "Around line 188, after the `_last_dm_body` tracker" — actual position of `_last_dm_body` is line 187, and `_notified_dm_threads_reset` is line 188. Insertion should be around line 189-190 (after `_notified_dm_threads_reset`), not after `_last_dm_body`.
- "Section 4: Around line 604, inside the `for dm in unread_dms:` loop" — actual `for dm in unread_dms:` is line 604, but the matching SEARCH content in the prompt cites lines 604-621. The live code's body is at lines 605-622 (one-off; the `for` line is 604, body starts 605). The SEARCH/REPLACE block as quoted in the prompt is correct content-wise but Builder will need to anchor by content, not line numbers.
- "Section 3: after line 632" — `_check_unread_dms` ends well before line 632 in the live source (it ends ~line 632 in the prompt's view, but actual end is around line 626-629 depending on exception handler). Need to anchor on a content marker, not line number.

**Fix:** Replace all line-number anchors with content-anchored SEARCH targets. State the rough line range as approximate ("around line 188-190; verify by SEARCH on `self._notified_dm_threads_reset = time.monotonic()  # hourly reset`"). This is convention #6 verify-first applied to anchor stability.

### 3. SEARCH text in Section 4 missing the `# BF-164` comment

Live code at line 596 has: `# BF-164: pass exchange limit so query excludes capped threads`. The prompt's quoted "current code" block at the start of Section 4 includes only `for dm in unread_dms:`. The actual SEARCH literal Builder will paste needs to match the `for dm in unread_dms:` line exactly (which it does); but the larger surrounding context the Builder reads should include the BF-164 comment for orientation. Recommend adding the `# BF-164` line as the first line of the SEARCH block context, even though the replacement starts at `for dm in unread_dms:`.

This is convention #9 (ASCII-only + character-faithful SEARCH literals) applied to context lines.

---

## Recommended

### R1. Default tuning needs more justification

Lowering `dm_exchange_limit` from 40 → 15 affects 5 existing tests (per the prompt's own list at "Existing Test Impact"). Two of those tests are not just assertion updates:

- `tests/test_bf200_thread_cap_awareness.py:46` — `test_dm_exchange_limit_default_40`. The test name and class assertion are tied to "40." Renaming the test method (`test_dm_exchange_limit_default_15`) and updating the assertion is the obvious fix, but it loses the audit trail of "why was 40 chosen in BF-200?" Recommend keeping the rename but adding a docstring referencing both BF-200 and BF-257.
- `tests/test_unread_dms.py:147` — sets `dm_exchange_limit = 40` in test fixture. The prompt's note "verify the test's intent" is correct — the test may be specifically testing the high-cap case. Recommend reading this test and either (a) leaving the explicit override in place (since the test wants 40 specifically) or (b) reducing it to match the new default if the test wasn't asserting on the value itself.

### R2. Window choice (10 minutes, 6 responses) lacks production-data grounding

The diagnosis cites a single observed incident with three Science agents. The 6/10min and 8/pair budgets are reasonable starting points, but there's no telemetry-backed reasoning. Recommend either:

- Adding a sentence in the Design Notes section explaining the budget reasoning ("6 responses = ~1 every 100 seconds, allowing real conversation cadence; 10 minutes covers a typical multi-turn thread"), OR
- Citing the original incident's exchange rate (e.g., "Atlas ↔ Sage exchanged N messages in M seconds; 6/10min would have throttled at the 4th response"). 

Either grounds the values in evidence rather than guess.

### R3. No telemetry / observability hook

When BF-257 throttles a DM, it logs at INFO level. That's correct, but there's no event emission. Recommend adding a `DM_THROTTLED` EventType (Section 0) so:

- Counselor can observe throttling patterns (suggests agent overload)
- HXI can surface "agent throttled" state to Captain
- Future telemetry can aggregate throttle rates

This would be a 1-line addition to `events.py` and 1-line addition to the throttle branch. Low cost, high observability value. If you don't want it for v1, defer it to BF-257b explicitly.

### R4. The `_dm_response_counts` dict has no eviction policy beyond per-call pruning

If an agent never sends a DM again, its entry in `_dm_response_counts` never gets pruned (the lazy pruning is per-call; agents that stop sending don't trigger it). Memory leak risk is small (~bounded by agent count × 8 timestamps), but worth a periodic sweep. Either:

- Add a comment explicitly noting the bounded memory and accepting it (`# Bounded by num_agents × budget; ~K records max`)
- Add a periodic full-prune in the proactive loop's existing hourly reset (line 590-592 already has the dedup-set reset — pair the BF-257 prune with it)

R4 is a Nit if the v1 ship is small-scale; Required-class only at scale (>100 agents).

### R5. AD-643b reference in "What This Does NOT Change" is correct but worth strengthening

The prompt notes AD-643b undeclared action detection is unchanged. That's right, but the relationship is more important than "separate concern." The two interact: BF-257 prevents the loop from starting; AD-643b would catch the LLM proposing undeclared DM action AFTER the loop is already underway. Recommend rephrasing to: "AD-643b operates on the cognitive chain output (after the LLM responds); BF-257 operates at the routing entry (before the LLM is consulted). They are complementary defenses."

### R6. Captain exemption uses callsign string match — fragile

Line 605 of the new code: `if author_callsign.lower() != "captain":`. Two issues:

- **Hardcoded string:** "captain" is a callsign convention, not an identity. If the Captain's callsign is changed via AD-499 ShipNamingPolicy or the Captain DID is rotated, this check breaks silently.
- **Case sensitivity:** `.lower()` handles "Captain"/"CAPTAIN" but not e.g., "Captain Picard" or full-name forms.

Recommend: check the author's identity layer instead. Either:
- `dm["author_id"] == rt.captain_did` if a captain DID exists at runtime
- A `is_captain(rt, author_id)` helper (preferred; abstracts the check)

If neither is available today, the callsign check is acceptable v1 with an explicit comment: "# v1: callsign string match. AD-XXX may refactor to identity-based check once captain DID is canonical."

---

## Nits

- **Section 2's `dict[str, list[float]]` type hint** is correct for current Python (3.9+). No change needed; just noting it follows convention.
- **Test counts are 12, prompt says "Total: 12 tests"** — verified.
- **`_check_unread_dms` is async but `_dm_response_budget_exceeded` is synchronous.** Correct — no I/O in the budget check. Worth a one-line comment in the method docstring confirming the design intent ("Synchronous: pure in-memory check").
- **Pair-key sort:** `":".join(sorted([a, b]))` — works correctly. Alphabetical sort over agent IDs is deterministic. Worth noting in a comment that the sort is for canonicalization, not ordering ("# canonical pair key — A→B and B→A share the same counter").
- **The `setdefault` pattern** in Section 4 is correct: `self._dm_response_counts.setdefault(agent.id, []).append(now)`. No issue.

---

## Verified Against Codebase (2026-05-02)

```
grep -n "class ProactiveCognitive" src/probos/proactive.py
  146: class ProactiveCognitiveLoop:    ← class name is ProactiveCognitiveLoop, NOT ProactiveCognitive

grep -n "_last_dm_body\|_notified_dm_threads\|async def _check_unread_dms" src/probos/proactive.py
  184: self._notified_dm_threads: set[str] = set()  # BF-082: dedup guard
  187: self._last_dm_body: dict[str, str] = {}  # AD-614: self-similarity gate
  188: self._notified_dm_threads_reset: float = time.monotonic()  # hourly reset
  584: async def _check_unread_dms(self, agent: Any, rt: Any) -> None:
  590-592: hourly reset block
  604: for dm in unread_dms:
  606: if tid in self._notified_dm_threads: continue
  608: self._notified_dm_threads.add(tid)
  3312: last_body = self._last_dm_body.get(dm_pair_key, "")    ← AD-614 send-side
  3326: self._last_dm_body[dm_pair_key] = dm_body              ← AD-614 send-side

grep -n "dm_exchange_limit\|class WardRoomConfig\|event_coalesce_ms" src/probos/config.py
  1228: class WardRoomConfig(BaseModel):
  1242: dm_exchange_limit: int = 40     # BF-200: raised from 5
  1245: event_coalesce_ms: int = 200    # AD-616

grep -rn "dm_exchange_limit" tests/    (5 affected files confirmed)
  test_ad614_dm_conversation_termination.py:106, 116
  test_ad623_dm_convergence.py:75
  test_bf164_stale_unread_dm.py:71, 76, 77
  test_bf193_parallel_captain_dispatch.py:22
  test_bf200_thread_cap_awareness.py:46-48, 70, 74, 118
  test_bf201_thread_post_cap.py:202
  test_proactive.py:158
  test_unread_dms.py:147
```

The prompt's "Existing Test Impact" list misses 4 of these:

- `test_ad623_dm_convergence.py:75` (sets to 6, may not need change)
- `test_bf164_stale_unread_dm.py:71-77` (asserts SOURCE contains the string `dm_exchange_limit`, not the value — no change needed but the prompt should acknowledge)
- `test_bf193_parallel_captain_dispatch.py:22` (sets to 6, may not need change)
- `test_bf201_thread_post_cap.py:202` (mentions it in a comment, no value assertion)
- `test_proactive.py:158` (sets to 6, may not need change)

Recommend the Builder grep `dm_exchange_limit` themselves before committing and update the test-impact list in the prompt accordingly.

---

## Disposition

**⚠️ Conditional.** Three Required findings (mechanical fixes), six Recommended (architectural concerns worth resolving before ship). After the architect/author applies the Required + at least R1 + R6, the prompt is ready for builder. R2/R3/R4/R5 are quality-of-output improvements that can be folded into the build commit at code-review time.

**Recommended next steps:**

1. Architect applies the 3 Required findings (~10 min) — class name, line-number anchors, SEARCH context.
2. Architect makes a call on R6 (captain exemption) — strongest of the Recommended; the others are softer.
3. Re-grep `dm_exchange_limit` in `tests/` to update the test-impact list comprehensively (~5 min).
4. Submit for second-pass review or, if you want to skip review, dispatch directly to Builder with the three fixes applied.

The diagnosis ("send cooldowns are unidirectional; receive layer needs its own gate") is sound. The design (sliding window + bidirectional pair key + captain exemption + deferred-not-dropped) is sound. The implementation issues are all draft-time verify-first slips, not architectural.
