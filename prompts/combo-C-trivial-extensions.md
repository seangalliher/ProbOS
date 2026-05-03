# Combo C: 7 trivial extensions across 4 partial-completion umbrellas

**Status:** Drafted (Wave 13)
**Scope:** 7 child ADs grouped into a single Builder commit per Wave 8 Combo A precedent
**Total estimated tests:** ~28-35 (4-5 per child)
**Risk:** Low — each child is read-consumer / additive helper / dataclass field
**Closes:** GH issues #101 (AD-526), #109 (AD-572), #8 (AD-573), #7 (AD-575)

---

## Why Combo

Per Wave 5-7 retrospective convention #14 (aggressive pre-deferral) and Wave 8 Combo A precedent: 7 trivial extensions to already-partial-closed parent ADs. Each is one-file additive, low-risk. Per-prompt overhead × 7 would multiply Builder commit cost ~5×; combo is cleaner.

Wave 8 Combo A shipped 7 children clean on first try with 26 focused tests. Combo C follows the same template.

## Combo Discipline

- Each child AD is a separate H2 section (`## AD-NNN: Title`).
- Each child has its own Verify-First grep evidence + implementation + test plan.
- Single Section 0 (EventTypes) at top covers all 7 children's new events.
- Single Tracker section at bottom updates PROGRESS.md / DECISIONS.md / roadmap.md for all 7.
- Single commit closes all 7 ADs with message `Combo C: AD-526d/572c/572d/573c/573e/573f/575c trivial extensions`.

## Section 0 — Combined EventTypes

| EventType | Child | Purpose |
|---|---|---|
| `GAME_PREFERENCE_RECORDED` | AD-526d | Per-agent per-game-type play frequency tick |
| `CAPTAIN_DM_PRIORITY_DISPATCHED` | AD-572d | Immediate proactive trigger fired on Captain DM |
| `WORKING_MEMORY_NOTE_RECORDED` | AD-573c | Agent-written scratchpad NOTE persisted |
| `COMMITMENT_RECORDED` | AD-573f | Agent commitment tracked |

(572c, 573e, 575c are read-side/additive only — no new EventTypes.)

Verify no collision with events.py post-Wave-12.

## Inter-Child File Conflict Sequencing

- AD-572c, AD-572d, AD-575c all touch `proactive.py` — apply sequentially per Combo A precedent (572c → 572d → 575c).
- AD-573c, AD-573e, AD-573f all touch `working_memory.py` — apply sequentially (573c → 573e → 573f).
- AD-526d touches `recreation/metadata.py` (extends Combo A's AD-526c file) — independent.

## AD-526d: Game Preference Tracking

**File:** `src/probos/recreation/preferences.py` (NEW; ~50 lines)

Personality-correlated play style analysis. Per-agent per-game-type play frequency. Big Five signal extraction.

```python
class GamePreferenceTracker:
    """Tracks per-agent per-game-type play frequency. AD-526d."""

    def __init__(self) -> None:
        self._frequencies: dict[str, dict[str, int]] = {}  # agent_id -> game_type -> count
        self._emit_event_fn: Callable[..., None] | None = None

    def record_game(self, agent_id: str, game_type: str) -> None:
        """Increment play count + emit GAME_PREFERENCE_RECORDED."""

    def get_preferences(self, agent_id: str) -> dict[str, int]:
        """Return frozen copy of agent's game frequencies."""

    def top_game_for(self, agent_id: str) -> str | None:
        """Most-played game type for agent."""
```

Wire into `runtime.recreation_preference_tracker` (Wave 5 convention #1: public attribute).

**Verify-first:** `src/probos/recreation/metadata.py` exists from Combo A (commit 16c4ea4). Extend.

**Test plan:** 4 tests — record_game increments + emits; get_preferences frozen copy; top_game_for returns max; record_game on unknown agent creates entry.

## AD-572c: Ward Room Activity in Captain DM Context

**File:** `src/probos/proactive.py`

Extend `CaptainEngagementProvider` (Combo A AD-572b, commit 16c4ea4) to include Ward Room activity summary in proactive context for Captain DMs.

Add field `wardroom_activity_summary: dict[str, Any]` to engagement context. Populated from `runtime.ward_room.list_threads()` (verified at AD-477 dispatch — `channel_id` positional `str`).

**Verify-first:** Combo A shipped `cognitive/captain_engagement.py`. Extend with new field + helper.

**Test plan:** 3 tests — context includes wardroom_activity_summary key; populated when ward_room available; empty dict when ward_room missing.

## AD-572d: Captain Priority Queue (Immediate Proactive Trigger)

**File:** `src/probos/proactive.py`

Currently Captain DMs go through normal proactive cycle. AD-572d makes them trigger an immediate proactive cycle (skip the wait-for-next-tick). Per BF-188 Captain ordering precedent.

Implementation: in `_check_unread_dms` or DM intake path, if author is Captain, set `runtime.proactive_loop._immediate_trigger.set()` (or equivalent asyncio.Event). The proactive loop's main wait-loop awakens.

**Verify-first:** confirm proactive loop has an interruptible wait pattern OR add one. Check `proactive.py` for existing event-driven wakeup patterns.

**Test plan:** 4 tests — captain DM sets immediate trigger; non-captain DM does not; CAPTAIN_DM_PRIORITY_DISPATCHED emits; trigger respects existing dedup.

**Hard-stop:** if proactive loop has no interruptible-wait pattern AND adding one requires architectural surgery → defer to AD-572d-i (need separate runtime infrastructure).

## AD-573c: Agent-Writable Scratchpad `[NOTE]` Action Tag

**File:** `src/probos/working_memory.py`

Combo A AD-573b added the `scratchpad: list[ScratchpadEntry]` field on `WorkingMemorySnapshot` and `add_scratchpad()` helper. AD-573c wires it into the action-tag pipeline: agents emit `[NOTE] thought text` action tags, and the post-action handler parses and calls `add_scratchpad()`.

**Verify-first:** find action-tag parsing site (likely `cognitive/cognitive_agent.py` or post-act hook). Read existing tags (e.g., `[ACT]`, `[REPLY]`) to mirror pattern.

**Test plan:** 4 tests — `[NOTE] foo` emits WORKING_MEMORY_NOTE_RECORDED; multi-line NOTE captured; NOTE without text ignored; multiple NOTEs in one action all captured.

## AD-573e: CognitiveJournal as Working Memory Source

**File:** `src/probos/working_memory.py`

Read-side only. Add a method `WorkingMemoryManager.recent_journal_entries(agent_id, k=5)` that pulls from `runtime.cognitive_journal.recent_for_agent(agent_id, k)` (verified at AD-460 — read-only consumer).

**Verify-first:** confirm `cognitive_journal.recent_for_agent` signature exists. Wave 8 AD-469 already verified `cognitive_journal.get_token_usage_by` at journal.py:299.

**Test plan:** 3 tests — recent_journal_entries returns up to k entries; respects agent_id filter; empty when journal absent.

## AD-573f: Commitment Tracker

**File:** `src/probos/working_memory.py`

Combo A AD-573b added `commitments: list[Commitment]` field + `add_commitment()` helper. AD-573f adds the lifecycle: `mark_commitment_complete(commitment_id)`, `pending_commitments(agent_id)`, `expired_commitments(agent_id)`. Bounded ring; auto-expiry by `due_at` timestamp.

**Verify-first:** confirm `Commitment` dataclass shape from Combo A (likely has `id`, `agent_id`, `description`, `due_at`, `status` fields).

**Test plan:** 5 tests — mark_complete updates status + emits COMMITMENT_RECORDED; pending filters by status; expired filters by due_at < now; bounded ring evicts oldest; mark_complete on unknown id is no-op.

## AD-575c: Self-Mention in DM Forwarded Content

**File:** `src/probos/proactive.py`

Combo A AD-575b was wholesale-deferred (theater — `runtime.self_summary_provider` didn't exist). AD-575c is the smaller, edge-case sibling: when an agent's DM contains forwarded Ward Room content that mentions the agent itself (e.g., "Captain said about you: ..."), the DM intake path should preserve the self-reference flag.

Implementation: in the DM forwarding path, scan body for `@<agent_callsign>` patterns; set `dm["self_referenced"] = True` if found. Read-only check; no mutation of upstream content.

**Verify-first:** find DM forwarding path (likely in `proactive.py` `_check_unread_dms` body or `cognitive_agent.py` DM handler).

**Test plan:** 3 tests — self-mention sets flag; no mention leaves flag False/missing; case-insensitive match; multiple mentions still set flag once.

## What This Combo Does NOT Change

- **AD-526e/f/g/h** (spectator commentary, holodeck integration, creative content, chess engine) — deferred; each is substantial enough to warrant standalone treatment. AD-526d is the read-side analytics that exposes the data-collection surface they'll all share.
- **AD-572e** (task awareness in DM) — deferred; needs WorkItemStore deeper integration.
- **AD-573d** (dream-to-WM pipeline) — deferred; depends on `runtime.dream_scheduler` exposing summaries (same blocker as AD-477g).
- **AD-575b** — already wholesale-deferred in Combo A; not revisited.

## Combo Test Plan

Total: ~26 tests across 7 children (4+3+4+4+3+5+3 = 26).

Single test file per child at `tests/test_combo_c_<short-id>.py` OR consolidated `tests/test_combo_c.py` — Builder discretion. Wave 8 Combo A used per-child files.

Run focused gates per child during build (Wave 8 Combo A pattern).

## Combo Tracker Updates

**PROGRESS.md:** prepend single Combo C entry summarizing all 7 children + total test count.

**DECISIONS.md:** single entry under Era V titled `### Combo C: 7 trivial extensions (526d/572c/572d/573c/573e/573f/575c) (2026-05-03)`. Brief problem/decision per child.

**docs/development/roadmap.md:** flip 7 status flags:
- AD-526d → Closed
- AD-572c, AD-572d → Closed (572e remains Deferred)
- AD-573c, AD-573e, AD-573f → Closed (573d remains Deferred)
- AD-575c → Closed

**GH issues to close (in dispatch):**
- #101 (AD-526 — partial; 526c+526d done, 526e-h still partial; **leave open** with comment update)
- #109 (AD-572 — partial; 572b+c+d done, 572e remains; **leave open** with comment update)
- #8 (AD-573 — partial; 573b+c+e+f done, 573d remains; **leave open** with comment update)
- #7 (AD-575 — partial; 575b dropped, 575c done; **CLOSE** since both surface children resolved)

So Combo C closes 1 issue (#7) and updates partial-completion comments on 3 others (#101, #109, #8).

## Verified Against Codebase (2026-05-03)

```
grep -n "class GamePreferenceTracker\|register_engine" src/probos/recreation/
  recreation/metadata.py:* GameMetadata exists (Combo A AD-526c, commit 16c4ea4)

grep -n "class CaptainEngagementProvider" src/probos/cognitive/
  cognitive/captain_engagement.py:* exists (Combo A AD-572b, commit 16c4ea4)

grep -n "scratchpad\|add_scratchpad\|commitments\|add_commitment" src/probos/working_memory.py
  (Combo A AD-573b shipped these; verify Builder reads current state)

grep -n "_check_unread_dms\|class ProactiveCognitiveLoop" src/probos/proactive.py
  proactive.py:146 class ProactiveCognitiveLoop
  proactive.py:584 async def _check_unread_dms (BF-257 verified)

grep -n "recent_for_agent" src/probos/cognitive/journal.py
  (AD-573e: verify recent_for_agent exists; if not, surface and possibly defer)

grep -n "ward_room.list_threads" src/probos/
  (AD-572c: AD-477 build verified channel_id positional str)
```

## Acceptance Criteria

- 7 child ADs implemented as documented.
- 4 new EventTypes in events.py (verified collision-free).
- 3 new public attributes on runtime (`recreation_preference_tracker` and any others) per Wave 5 convention #1.
- ~26 tests pass.
- Single commit `Combo C: AD-526d/572c/572d/573c/573e/573f/575c trivial extensions`.
- DECISIONS.md combined entry under Era V.
- roadmap.md 7 status flags flipped.
- GH issue #7 closed; #101, #109, #8 partial-completion comments updated.

## Hard-Stops (per child)

- **AD-526d:** None expected; pure new file.
- **AD-572c:** `ward_room.list_threads(channel_id=None)` doesn't degrade gracefully — surface; may need different consumer pattern.
- **AD-572d:** Proactive loop has no interruptible-wait pattern — surface; defer to AD-572d-i (separate infrastructure ask).
- **AD-573c:** Action-tag parsing site can't be located cleanly — surface; may need scope reframe.
- **AD-573e:** `cognitive_journal.recent_for_agent` doesn't exist — surface; defer to AD-573e-i.
- **AD-573f:** Commitment dataclass shape from Combo A doesn't match assumptions — surface for verification.
- **AD-575c:** DM forwarding path doesn't expose body for inspection — surface.

Per Wave 8 AD-575b precedent: any single child hitting a hard-stop should be wholesale-dropped from the combo, not blocking the wave. Document the drop in DECISIONS.md.
