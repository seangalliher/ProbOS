# Review: Combo C — 7 Trivial Extensions (Wave 13, Pass 1)

**Verdict:** ⚠️ Conditional
**Headline:** 3 of 7 children require revision (2 wholesale-defer per AD-575b precedent, 1 dataclass-shape mismatch per Convention #20). 4 children clean. Total findings: 5 Required, 3 Recommended, 2 Nits.

---

## Required (must fix before building)

### R1. AD-572d — Wholesale-defer (no interruptible-wait pattern in proactive loop)

The combo prompt's own hard-stop section anticipated this. Architect verifies NOW per dispatch instruction #2:

```
grep -n "_immediate_trigger|asyncio\.Event|wait_for|asyncio\.sleep" src/probos/proactive.py
  475: await asyncio.sleep(self._interval)
  482: await asyncio.sleep(self._interval)
  584: await asyncio.sleep(stagger_delay)
  782: await asyncio.sleep(_backoff)
```

Zero `asyncio.Event`, zero `wait_for`. The `_think_loop` (line 470-484) is bare `await asyncio.sleep(self._interval)`. Implementing the "Captain DM sets immediate trigger" semantics requires refactoring the loop to `await asyncio.wait_for(self._immediate_trigger.wait(), timeout=self._interval)` plus a clear-on-wake reset. That is architectural surgery on a hot, BF-211-hardened loop, not a "trivial extension."

**Fix:** Wholesale-defer AD-572d to AD-572d-i in revision pass. Document the drop in DECISIONS.md per AD-575b precedent. AD-572d-i becomes a standalone Wave 14+ candidate that ships the interruptible-wait infrastructure first, then layers the Captain priority on top. Drop `CAPTAIN_DM_PRIORITY_DISPATCHED` from Section 0.

### R2. AD-573e — Wholesale-defer (`recent_for_agent` does not exist on CognitiveJournal)

```
grep -n "    def |    async def " src/probos/cognitive/journal.py
  59: def __init__
  67: async def start
  94: async def stop
  99: async def wipe
  109: async def prune
  148: async def record
  200: async def get_reasoning_chain
  235: async def get_token_usage
  275: async def get_token_usage_since
  299: async def get_token_usage_by
  346: async def get_decision_points
  385: async def get_stats
```

No `recent_for_agent`. Closest substitute is `get_decision_points(agent_id=...)` but that filters for high-latency / failures-only, not "recent k entries." Combo prompt's verify-first section flagged the risk; pre-check confirms.

**Fix:** Two options:
- (a) **Wholesale-defer AD-573e to AD-573e-i** (preferred — matches AD-575b precedent; keeps Combo C clean).
- (b) Remap to `get_decision_points(agent_id=agent_id, limit=k)` if the architect accepts that "decision points" ≠ "recent entries" semantically. Not recommended; AD-573e's spec assumes recency-ordered recall, not latency-ordered.

Recommend (a). Drop the AD-573e mini-section from the combo. Document in DECISIONS.md.

### R3. AD-573f — Commitment dataclass shape mismatch (Convention #20 violation)

Combo prompt assumes `Commitment` dataclass with `id`, `agent_id`, `description`, `due_at`, `status` fields shipped by Combo A AD-573b. **Read shipped code (Convention #20), not the prompt:**

```python
# src/probos/cognitive/working_memory.py:35
commitments: list[dict[str, Any]] = field(default_factory=list)
```

```python
# src/probos/cognitive/working_memory.py:138-154
def add_commitment(
    self, commitment_id: str, summary: str, due_at: float | None = None,
) -> None:
    ...
    entry: dict[str, Any] = {
        "id": commitment_id,
        "summary": summary,
    }
    if due_at is not None:
        entry["due"] = due_at
```

Actual shape is `list[dict]` with keys `{id, summary, due?}` — no `agent_id`, no `description`, no `status`. AD-573f's lifecycle methods (`mark_commitment_complete`, `pending_commitments(agent_id)`, `expired_commitments(agent_id)`) are built on a dataclass that doesn't exist.

**Fix:** Revision must do ONE of:
- (a) Rewrite AD-573f to operate on the actual dict shape. `pending_commitments` becomes a no-status filter (everything pending unless explicitly removed). `mark_commitment_complete` adds a `"status": "done"` key in-place. No `agent_id` filter (working memory is per-agent at the manager scope already).
- (b) Promote dicts to a `Commitment` dataclass as a Section 1 prep step inside AD-573f, with the existing `add_commitment` re-bound to construct dataclass instances. Higher risk — touches Combo A's tested surface.

Recommend (a). Lower risk, preserves Combo A's working code, fits "trivial extension" framing.

### R4. File path error in AD-573c / AD-573e / AD-573f

Combo prompt repeatedly says `src/probos/working_memory.py`. Actual path:

```
file_search **/working_memory.py
  d:\ProbOS\src\probos\cognitive\working_memory.py
```

Mechanical fix: replace all three occurrences with `src/probos/cognitive/working_memory.py` in revision.

### R5. AD-573c — Action-tag site verified, but parse pattern under-specified

Combo prompt's verify-first defers the lookup ("likely cognitive/cognitive_agent.py or post-act hook"). Pre-check confirms the site exists:

```
grep -n "action_tag|\[REPLY\]|\[NOTEBOOK\]" src/probos/cognitive/cognitive_agent.py
  1755: for action_tag, pattern in markers.items():
  1756:     if action_tag not in declared and pattern.search(compose_output):
  1757:         undeclared.append(action_tag)
```

There is a `markers: dict[action_tag, regex]` in `cognitive_agent.py` around line 1755. AD-573c needs to (a) add `"NOTE"` to that markers dict, (b) parse the matched body, (c) call `runtime.working_memory.add_scratchpad(text)`. The combo prompt does not specify the SEARCH/REPLACE for the markers dict.

**Fix:** Revision must add explicit SEARCH anchor for the `markers` dict (around line 1755) and a SEARCH/REPLACE that adds the `NOTE` regex + post-parse hook calling `add_scratchpad`. Without this, Builder will guess and likely create a parallel parse path.

---

## Recommended

### Rec1. AD-572c — Spell out the iterate-channels pattern

`ward_room.list_threads(channel_id, limit=N)` requires `channel_id` positional (verified `routers/wardroom.py:31-37`). To get a global "Ward Room activity summary," the consumer must first call `await ward_room.list_channels()` and aggregate. Combo prompt's verify-first acknowledges the issue but doesn't show the iteration pattern in the SEARCH/REPLACE outline. Revision should provide the snippet so Builder doesn't reinvent it.

### Rec2. AD-526d — `Callable` import

`GamePreferenceTracker.__init__` uses `Callable[..., None]` but the prompt's snippet doesn't show the `from typing import Callable` import. Mechanical, but worth calling out so the new file lands clean.

### Rec3. Combo Tracker — DECISIONS.md entry must reflect the wholesale-drops

If R1 + R2 land as recommended, the Combo C DECISIONS.md entry shrinks from 7 to 5 children. The dispatch's GH issue closure plan (#7 closed; #101/#109/#8 partial-comments) needs updating: #109 (AD-572) loses 572d (only 572c ships); #8 (AD-573) loses 573e (only 573c + 573f ship). Update Section "Combo Tracker Updates" + dispatch Stage-13 commands accordingly.

---

## Nits

### N1. Section 0 EventTypes count drops to 2

If R1 + R2 land: `CAPTAIN_DM_PRIORITY_DISPATCHED` (572d) drops; `WORKING_MEMORY_NOTE_RECORDED` (573c) and `COMMITMENT_RECORDED` (573f, if it still emits per dict-shape revision) survive. `GAME_PREFERENCE_RECORDED` (526d) survives. Section 0 anchor table needs trimming.

### N2. "What This Combo Does NOT Change" — minor restate

After deferrals, AD-572d and AD-573e join the list of deferred children (alongside 526e/f/g/h, 572e, 573d). Trivial copy-edit.

---

## Verified

- **EventTypes — no collisions.** `grep events.py` for all 4 (`GAME_PREFERENCE_RECORDED`, `CAPTAIN_DM_PRIORITY_DISPATCHED`, `WORKING_MEMORY_NOTE_RECORDED`, `COMMITMENT_RECORDED`) returned zero matches. Section 0 is collision-free.
- **AD-526d — clean.** `recreation/metadata.py` exists from Combo A (`grep` confirms `class GameMetadata` at line 15). Adding sibling `recreation/preferences.py` is independent. `runtime.recreation_preference_tracker` is a NEW public attribute introduced by AD-526d itself per Wave 5 convention #1 — pre-check FP is legitimate as documented.
- **AD-572c — site exists, pattern verified.** `runtime.ward_room.list_threads(channel_id, limit=...)` confirmed in `routers/wardroom.py:31, 35, 59`. `class CaptainEngagementProvider` confirmed at `cognitive/captain_engagement.py:23`.
- **AD-573c — extension target verified.** `add_scratchpad` lives at `working_memory.py:128`. AD-573b shipped `scratchpad: list[str]` (NOT `list[ScratchpadEntry]` — combo prompt's prose is slightly off but the helper takes plain `text: str`, so the AD-573c parse-and-call still works).
- **AD-575c — DM forwarding path verified.** `_check_unread_dms` at `proactive.py:584+` builds `event_data` dict including `body` field (line ~640 in the read). Self-mention scan can hook there cleanly.
- **runtime.self_summary_provider** — confirmed not present, FP per dispatch (negative framing in AD-575b retrospective prose).
- **Inter-child file conflict sequencing.** Combo prompt explicitly documents the order (proactive.py: 572c → 572d → 575c; working_memory.py: 573c → 573e → 573f). Sequential application is workable; SEARCH/REPLACE patterns operate on different anchors per child (no overlapping line ranges in pre-check). After R1+R2 wholesale-defer, the chains shrink to (proactive.py: 572c → 575c) and (working_memory.py: 573c → 573f) — even cleaner.
- **Convention #20 (read shipped code, not prompts) — applied.** R3 (Commitment dataclass mismatch) is exactly the failure mode Convention #20 anticipates. Combo A's prompt may have promised a dataclass; what shipped was `list[dict]`. Architect read `working_memory.py` directly to surface the gap.
- **Convention #14 (aggressive pre-deferral) — honored.** Architect surfaces the AD-572d / AD-573e wholesale-defers at review time, not Builder time. Wave 13 stays clean per the Wave 8 AD-575b precedent.

---

## Architect-Discretion Sweep on the Combo Prompt's Six Hard-Stops

| Combo prompt hard-stop | Pre-check verdict |
|---|---|
| AD-526d — None expected | ✅ Confirmed clean |
| AD-572c — `list_threads(channel_id=None)` doesn't degrade | ⚠️ Real but minor (Rec1) — iterate channels first |
| AD-572d — proactive loop has no interruptible-wait | ❌ **CONFIRMED hard-stop** (R1) — wholesale-defer |
| AD-573c — action-tag parsing site can't be located | ✅ Located (`cognitive_agent.py:1755`) — Rec spec the SEARCH/REPLACE (R5) |
| AD-573e — `cognitive_journal.recent_for_agent` doesn't exist | ❌ **CONFIRMED hard-stop** (R2) — wholesale-defer |
| AD-573f — Commitment dataclass shape doesn't match | ❌ **CONFIRMED partial hard-stop** (R3) — revise to dict-shape |
| AD-575c — DM forwarding path doesn't expose body | ✅ Body exposed at `proactive.py` `event_data["body"]` |

3 of 6 prompt-acknowledged hard-stops confirmed real; 1 elevated to spec gap (R5); 2 cleared.

---

## Convergence Posture

- 5 Required / 3 Recommended / 2 Nits. Wave 9B = 5 Required (comparable shape).
- Per Wave 5 retrospective convention #15 (relaxed tolerance): 1 ⚠️ allowed; this review fits.
- Recommended single revision pass to: drop AD-572d + AD-573e (R1+R2), reshape AD-573f (R3), fix file paths (R4), add markers SEARCH/REPLACE (R5), tracker updates (Rec3). Combo C ships as 5-child combo.

---

## Re-review

(reserved for pass 2)
