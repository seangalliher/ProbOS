# Wave 13 Review Sweep — Pass 1 (2026-05-03)

**Scope:** Combo C — 7 trivial extensions across 4 partial-completion umbrella ADs.
**Reviewer:** Architect
**Pre-check:** 2 documented false positives (`runtime.recreation_preference_tracker` introduced by AD-526d; `runtime.self_summary_provider` in AD-575b retrospective prose). Both legitimate.

## Verdict per Prompt

| Prompt | Verdict | Required | Recommended | Nits | Wholesale-Defer Recommended |
|---|---|---|---|---|---|
| Combo C | ⚠️ Conditional | 5 | 3 | 2 | AD-572d, AD-573e |

## Per-Child Wholesale-Defer Recommendations

| Child | Status | Reason | Defer-To |
|---|---|---|---|
| AD-526d | ✅ Ship | clean; new file | — |
| AD-572c | ✅ Ship (with Rec1) | site verified; iterate-channels pattern needed in SEARCH/REPLACE | — |
| **AD-572d** | ❌ **Defer** | proactive loop has no interruptible-wait pattern; only `asyncio.sleep()` calls; adding one is architectural surgery on BF-211-hardened loop | AD-572d-i (Wave 14+) |
| AD-573c | ✅ Ship (with R5) | site located at `cognitive_agent.py:1755`; needs explicit `markers` SEARCH/REPLACE | — |
| **AD-573e** | ❌ **Defer** | `cognitive_journal.recent_for_agent` does not exist; closest substitute (`get_decision_points`) is wrong semantics | AD-573e-i (Wave 14+) |
| AD-573f | ⚠️ Reshape | Combo A shipped `list[dict]`, not `Commitment` dataclass (Convention #20 violation in spec); revise lifecycle to operate on dicts | — |
| AD-575c | ✅ Ship | DM forwarding path exposes body at `proactive.py` `event_data["body"]` | — |

**Net effect:** Combo C ships as **5-child combo** (526d / 572c / 573c / 573f / 575c) instead of 7.

## Inter-Child File Conflict Assessment

- **proactive.py:** 572c → 572d → 575c → after R1 defer becomes **572c → 575c** (cleaner; no conflict).
- **cognitive/working_memory.py:** 573c → 573e → 573f → after R2 defer becomes **573c → 573f** (cleaner; no conflict).
- Pre-check confirmed SEARCH/REPLACE anchors operate on disjoint line ranges per child.
- ✅ No re-bundling required.

## Section 0 EventType Collision Check

```
grep -n "GAME_PREFERENCE_RECORDED|CAPTAIN_DM_PRIORITY_DISPATCHED|WORKING_MEMORY_NOTE_RECORDED|COMMITMENT_RECORDED" src/probos/events.py
  (no matches)
```

✅ Zero collisions. After R1 defer, `CAPTAIN_DM_PRIORITY_DISPATCHED` drops from Section 0 — only 3 new EventTypes ship.

## AD-572d Interruptible-Wait Pattern Verification

```
grep -n "_immediate_trigger|asyncio\.Event|wait_for|asyncio\.sleep" src/probos/proactive.py
  475: await asyncio.sleep(self._interval)
  482: await asyncio.sleep(self._interval)
  584: await asyncio.sleep(stagger_delay)
  782: await asyncio.sleep(_backoff)
```

**Result:** ❌ No interruptible-wait pattern. Zero `asyncio.Event`, zero `wait_for`. AD-572d defer confirmed.

## AD-573e API Existence Verification

```
grep -n "    def |    async def " src/probos/cognitive/journal.py
  148: async def record
  200: async def get_reasoning_chain
  235: async def get_token_usage
  275: async def get_token_usage_since
  299: async def get_token_usage_by
  346: async def get_decision_points
  385: async def get_stats
```

**Result:** ❌ `recent_for_agent` does not exist. Closest is `get_decision_points(agent_id=..., limit=...)` but it filters for high-latency / failures-only — wrong semantics for "recent k entries." AD-573e defer confirmed.

## Top Failure Modes (if revisions not applied)

1. **Builder time-loss on AD-572d** (~30-60 min before recognizing the pattern gap; then either bad architectural surgery or revert). Per AD-575b precedent, surfacing now saves the cycle.
2. **Builder time-loss on AD-573e** (~15 min before realizing API doesn't exist; remap-or-defer decision belongs to architect, not builder).
3. **AD-573f false-pass** — Builder writes `Commitment` dataclass against the prompt spec, lands "working" code that then breaks Combo A's existing `list[dict]` consumers. Convention #20 violation surfaces only at integration test time.
4. **R5 (action-tag SEARCH/REPLACE underspec)** — Builder creates parallel parse path instead of extending the existing `markers` dict; technical debt in `cognitive_agent.py`.

## Convergence Posture

- Pass-1 Required: 5. Comparable to Wave 9B (5) and Wave 8 (19) in baseline range.
- Per Wave 5 convention #15 (relaxed tolerance): 1 ⚠️ allowed at final pass; this Conditional verdict fits.
- Recommendation: single revision pass with R1-R5 + Rec1-3 + N1-2; expect ✅ at Pass 2.

## Standing Conventions Audit (23 conventions)

| Convention | Status |
|---|---|
| #1 public attribute (no underscore) for runtime wiring | ✅ AD-526d wires `runtime.recreation_preference_tracker` (no underscore) |
| #2 atomic write for persisted state | N/A — no new persistence in Combo C |
| #3 coordinator-then-dispatch for high-risk migrations | N/A — no high-risk migration |
| #4 forcing-function-ready before close | ⚠️ AD-573f's "Commitment lifecycle" needs forcing function — captain must read commitments daily; otherwise drift like AD-477g |
| #5 narrow constructor injection | ✅ AD-526d `GamePreferenceTracker.__init__` takes only `_emit_event_fn` (post-construction setter) |
| #6 TYPE_CHECKING guard for circular import risk | N/A |
| #7 theater check (does the feature do real work?) | ⚠️ AD-575c — self-mention flag is a passive marker; depends on downstream consumer reading it. Recommend tracking in Combo C tests that consumer reads it. |
| #8 verify-first grep evidence per claim | ⚠️ Combo prompt has footer-only evidence; per-child evidence missing for several |
| #9 enum vs string constant typing | ✅ EventTypes are enums, used as enum constants |
| #10 line numbers approximate | ✅ Combo prompt uses `proactive.py:584` (BF-257 verified) — ok |
| #11 SEARCH 3-line context minimum | ⚠️ Combo prompt mostly conceptual snippets, not full SEARCH/REPLACE blocks. Builder will rely on conceptual descriptions; risk of drift. R5 surfaces one instance. |
| #12 single-responsibility per child | ✅ Each child is one feature |
| #13 boundary tests required | ✅ Each child has 3-5 tests including edge cases |
| #14 aggressive pre-deferral | ✅ R1+R2 apply this convention |
| #15 relaxed tolerance (1 ⚠️ allowed at final pass) | ✅ |
| #16 phantom-API pre-check | ✅ Pre-check ran; 2 FPs documented |
| #17 default False on transitional flags | N/A — no transitional flags |
| #18 wave-level test count delta tracked | Not asserted in combo (will be verified post-build) |
| #19 GH issue closure plan documented | ✅ Dispatch documents #7 close + #101/#109/#8 comments; needs update post-defers (Rec3) |
| #20 read shipped code, not prompts | ❌ R3 = exactly this failure (Combo A AD-573b prompt promised `Commitment` dataclass; shipped `list[dict]`) — caught at review |
| #21 cross-wave dependency verification | ✅ R3 is the catch |
| #22 no architectural surgery in "trivial extensions" combos | ❌ R1 = exactly this (AD-572d would require loop refactor) |
| #23 wholesale-defer single child rather than block wave (AD-575b precedent) | ✅ R1+R2 invoke this |

**Findings:** 4 conventions flagged (#4, #7, #8, #11) at warning; 2 conventions invoked at REQUIRED-defer (#20, #22); 1 convention invoked at recommended-defer (#23 — recommended action).

## Builder Hand-Back

After revision pass, Combo C should ship as:
- 5 children: AD-526d, AD-572c, AD-573c, AD-573f (dict-shape), AD-575c
- 3 new EventTypes: `GAME_PREFERENCE_RECORDED`, `WORKING_MEMORY_NOTE_RECORDED`, `COMMITMENT_RECORDED`
- ~20 tests (vs original 26 target)
- Single commit: `Combo C: AD-526d/572c/573c/573f/575c trivial extensions`
- 2 wholesale-defer entries in DECISIONS.md (AD-572d → AD-572d-i; AD-573e → AD-573e-i)
- GH issue plan updated: #109 partial-comment notes 572d deferred; #8 partial-comment notes 573e deferred
