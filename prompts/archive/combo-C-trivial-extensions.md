# Combo C: 5 trivial extensions across 4 partial-completion umbrellas

**Status:** Drafted (Wave 13) — Revised (2026-05-03) per pass-1 review
**Scope:** 5 child ADs grouped into a single Builder commit per Wave 8 Combo A precedent. Originally 7; AD-572d + AD-573e wholesale-deferred during the revision pass (verify-first non-existence per convention #14 — see `## Revision (2026-05-03)` at the bottom).
**Total estimated tests:** ~19 (4+3+4+5+3 = 19; was ~26 with 572d+573e)
**Risk:** Low — each surviving child is read-consumer / additive helper / dict-field extension
**Closes:** GH issues #101 (AD-526 — partial), #109 (AD-572 — partial), #8 (AD-573 — partial), #7 (AD-575 — fully)

---

## Why Combo

Per Wave 5-7 retrospective convention #14 (aggressive pre-deferral) and Wave 8 Combo A precedent: 5 trivial extensions to already-partial-closed parent ADs. Each is one-file additive, low-risk. Per-prompt overhead × 5 would multiply Builder commit cost ~4×; combo is cleaner.

Wave 8 Combo A shipped 7 children clean on first try with 26 focused tests after dropping AD-575b in revision. Combo C follows the same drop-on-revision template (now drops 2 of 7).

## Combo Discipline

- Each child AD is a separate H2 section (`## AD-NNN: Title`).
- Each child has its own Verify-First grep evidence + implementation + test plan.
- Single Section 0 (EventTypes) at top covers all surviving children's new events.
- Single Tracker section at bottom updates PROGRESS.md / DECISIONS.md / roadmap.md for all 5.
- Single commit closes all 5 ADs with message `Combo C: AD-526d/572c/573c/573f/575c trivial extensions (572d + 573e wholesale-deferred)`.

## Section 0 — Combined EventTypes

| EventType | Child | Purpose |
|---|---|---|
| `GAME_PREFERENCE_RECORDED` | AD-526d | Per-agent per-game-type play frequency tick |
| `WORKING_MEMORY_NOTE_RECORDED` | AD-573c | Agent-written scratchpad NOTE persisted |
| `COMMITMENT_RECORDED` | AD-573f | Agent commitment lifecycle event (record / complete / expire) |

(572c and 575c are read-side/additive only — no new EventTypes. CAPTAIN_DM_PRIORITY_DISPATCHED was originally proposed for AD-572d but is dropped with the wholesale-defer.)

Verify no collision with events.py post-Wave-12.

## Inter-Child File Conflict Sequencing

After the wholesale-defers, the conflict chains shrink to:

- AD-572c, AD-575c both touch `proactive.py` — apply sequentially (572c → 575c).
- AD-573c, AD-573f both touch `src/probos/cognitive/working_memory.py` — apply sequentially (573c → 573f).
- AD-526d touches `recreation/preferences.py` (NEW) — independent.
- AD-573c additionally touches `src/probos/cognitive/cognitive_agent.py` (markers dict) — no conflict with the working_memory chain.

## AD-526d: Game Preference Tracking

**File:** `src/probos/recreation/preferences.py` (NEW; ~50 lines)

Personality-correlated play style analysis. Per-agent per-game-type play frequency. Big Five signal extraction.

```python
# src/probos/recreation/preferences.py — NEW
from __future__ import annotations

import logging
from typing import Any, Callable  # AD-526d Rec2: explicit Callable import

logger = logging.getLogger(__name__)


class GamePreferenceTracker:
    """Tracks per-agent per-game-type play frequency. AD-526d."""

    def __init__(self) -> None:
        self._frequencies: dict[str, dict[str, int]] = {}  # agent_id -> game_type -> count
        self._emit_event_fn: Callable[..., None] | None = None

    def record_game(self, agent_id: str, game_type: str) -> None:
        """Increment play count + emit GAME_PREFERENCE_RECORDED."""
        # body per spec

    def get_preferences(self, agent_id: str) -> dict[str, int]:
        """Return frozen copy of agent's game frequencies."""

    def top_game_for(self, agent_id: str) -> str | None:
        """Most-played game type for agent."""
```

Wire into `runtime.recreation_preference_tracker` (Wave 5 convention #1: public attribute). Late-bind `_emit_event_fn` from runtime startup (mirror AD-526c GameMetadata wiring pattern).

**Verify-first:** `src/probos/recreation/metadata.py` exists from Combo A (commit 16c4ea4). Extend the package by adding sibling `preferences.py`. `runtime.recreation_preference_tracker` is a NEW attribute — phantom-API pre-check FP is documented and legitimate.

**Test plan:** 4 tests — record_game increments + emits; get_preferences frozen copy; top_game_for returns max; record_game on unknown agent creates entry.

## AD-572c: Ward Room Activity in Captain DM Context

**File:** `src/probos/cognitive/captain_engagement.py` (extend existing)

Extend `CaptainEngagementProvider` (Combo A AD-572b, commit 16c4ea4) to include Ward Room activity summary in proactive context for Captain DMs.

Add field `wardroom_activity_summary: dict[str, Any]` to engagement context. **Iterate-channels pattern** (Rec1 — `list_threads` requires `channel_id` positional, so a global summary needs aggregation):

```python
# Pattern Builder must follow (paste into _build_wardroom_summary helper):
async def _build_wardroom_summary(self) -> dict[str, Any]:
    """AD-572c: aggregate per-channel thread counts into a single context blob.

    list_threads(channel_id) is per-channel; iterate channels first.
    """
    ward_room = getattr(self._runtime, "ward_room", None)
    if ward_room is None:
        return {}
    try:
        channels = await ward_room.list_channels()
    except Exception:
        logger.warning("AD-572c: ward_room.list_channels failed", exc_info=True)
        return {}
    summary: dict[str, Any] = {"channels": {}, "total_threads": 0}
    for channel in channels:
        channel_id = getattr(channel, "id", None) or getattr(channel, "channel_id", None)
        if not channel_id:
            continue
        try:
            threads = await ward_room.list_threads(channel_id, limit=10)
        except Exception:
            logger.warning("AD-572c: list_threads(%s) failed", channel_id, exc_info=True)
            continue
        summary["channels"][channel_id] = len(threads)
        summary["total_threads"] += len(threads)
    return summary
```

Verified: `WardRoomService.list_channels(agent_id=None)` exists at `src/probos/ward_room/service.py:241` (async). `list_threads(channel_id, limit=N)` is the per-channel API per AD-477 verification.

**Test plan:** 3 tests — context includes wardroom_activity_summary key; populated when ward_room available (per-channel counts + total); empty dict when ward_room missing.

## AD-573c: Agent-Writable Scratchpad `[NOTE]` Action Tag

**Files:**
- `src/probos/cognitive/cognitive_agent.py` (markers dict — gap-detection)
- `src/probos/proactive.py` (action-tag extraction + dispatch)
- `src/probos/cognitive/working_memory.py` (no edit — `add_scratchpad` already shipped in Combo A AD-573b at line 128)

Combo A AD-573b added the `scratchpad: list[str]` field on `WorkingMemorySnapshot` and `add_scratchpad(text)` helper. AD-573c wires it into the action-tag pipeline: agents emit `[NOTE] thought text` action tags, the proactive extractor parses them, and the post-action handler calls `add_scratchpad()` and emits `WORKING_MEMORY_NOTE_RECORDED`.

### Section 1 — Add NOTE to gap-detection markers (R5 explicit SEARCH/REPLACE)

Builder must apply this exact edit to `src/probos/cognitive/cognitive_agent.py` (markers dict located at lines ~1747-1753 inside the `_detect_undeclared_actions` helper):

```
===MODIFY: src/probos/cognitive/cognitive_agent.py===
===SEARCH===
        markers = {
            "notebook": re.compile(r'\[NOTEBOOK\s', re.IGNORECASE),
            "endorse": re.compile(r'\[ENDORSE\s', re.IGNORECASE),
            "proposal": re.compile(r'\[PROPOSAL\]', re.IGNORECASE),
            "dm": re.compile(r'\[DM\s', re.IGNORECASE),
            "ward_room_reply": re.compile(r'\[REPLY\s', re.IGNORECASE),
        }
===REPLACE===
        markers = {
            "notebook": re.compile(r'\[NOTEBOOK\s', re.IGNORECASE),
            "endorse": re.compile(r'\[ENDORSE\s', re.IGNORECASE),
            "proposal": re.compile(r'\[PROPOSAL\]', re.IGNORECASE),
            "dm": re.compile(r'\[DM\s', re.IGNORECASE),
            "ward_room_reply": re.compile(r'\[REPLY\s', re.IGNORECASE),
            "note": re.compile(r'\[NOTE\s', re.IGNORECASE),  # AD-573c
        }
===END REPLACE===
```

### Section 2 — Add `_extract_notes` extractor + dispatch in proactive.py

Mirror the existing `notebook_pattern` extractor pattern at `proactive.py:2339`:

```python
# AD-573c: NOTE extraction — mirror notebook_pattern shape
note_pattern = r'\[NOTE\s+(.*?)\](.*?)\[/NOTE\]'  # body inside; tag-name capture optional
# OR simpler if no tag-name body: r'\[NOTE\]\s*(.*?)\s*\[/NOTE\]'
```

Builder picks the shape that matches the inline `[NOTE ...]` examples in agent personality docs (verify with `grep -r "\[NOTE" config/standing_orders/ config/manuals/`). After extraction, call:

```python
runtime.working_memory.add_scratchpad(text)  # AD-573b helper, already shipped
runtime.emit_event(EventType.WORKING_MEMORY_NOTE_RECORDED, {"agent_id": agent_id, "text_len": len(text)})
```

Wire as a separate handler method (e.g., `_extract_notes`) called from the same post-act hook chain that runs `_extract_notebook` / `_extract_replies`.

**Verify-first:** `add_scratchpad(text: str)` confirmed at `src/probos/cognitive/working_memory.py:128`. `markers` dict confirmed at `src/probos/cognitive/cognitive_agent.py:1747`. Action extractors (`notebook_pattern` etc.) confirmed at `src/probos/proactive.py:2339, 2645, 3074, 3325`.

**Test plan:** 4 tests — `[NOTE foo]bar[/NOTE]` calls add_scratchpad("bar") + emits WORKING_MEMORY_NOTE_RECORDED; multi-line NOTE captured; NOTE without text ignored; multiple NOTEs in one action all captured.

## AD-573f: Commitment Tracker (lifecycle helpers on existing dict-list shape)

**File:** `src/probos/cognitive/working_memory.py`

Combo A AD-573b shipped `commitments: list[dict[str, Any]]` (NOT a `Commitment` dataclass — Convention #20 reality-check applied during revision). Existing dict shape per `working_memory.py:138-154`:

```python
entry: dict[str, Any] = {
    "id": commitment_id,
    "summary": summary,
}
if due_at is not None:
    entry["due"] = due_at
```

Bounded ring already enforced: `_max_commitments = 8` at `working_memory.py:108`.

AD-573f adds the lifecycle methods on the existing dict-list shape (no schema migration; Combo A's tested surface untouched):

```python
# AD-573f additions to WorkingMemorySnapshot (read-side filters):
def pending_commitments(self) -> list[dict[str, Any]]:
    """Commitments without status='done' or status='expired'."""
    return [c for c in self.commitments if c.get("status") not in ("done", "expired")]

def expired_commitments(self, now: float) -> list[dict[str, Any]]:
    """Commitments with due < now and not yet completed."""
    return [
        c for c in self.commitments
        if c.get("due") is not None
        and c["due"] < now
        and c.get("status") != "done"
    ]
```

```python
# AD-573f additions to WorkingMemoryManager (write-side):
def mark_commitment_complete(self, commitment_id: str) -> None:
    """Mutate matching dict's status key in-place; emit COMMITMENT_RECORDED.

    No-op if commitment_id not found (best-effort per Wave-5 tier-2).
    """
    try:
        for entry in self._commitments:
            if entry.get("id") == commitment_id:
                entry["status"] = "done"
                if self._emit_event_fn is not None:
                    self._emit_event_fn(
                        EventType.COMMITMENT_RECORDED,
                        {"commitment_id": commitment_id, "action": "complete"},
                    )
                return
        # not found — no-op
    except Exception:
        logger.warning("AD-573f: mark_commitment_complete failed", exc_info=True)

def pending_commitments(self) -> list[dict[str, Any]]:
    """Filter self._commitments for entries without terminal status."""
    return [c for c in self._commitments if c.get("status") not in ("done", "expired")]

def expired_commitments(self, now: float) -> list[dict[str, Any]]:
    """Filter self._commitments for entries with due < now and not yet done."""
    return [
        c for c in self._commitments
        if c.get("due") is not None
        and c["due"] < now
        and c.get("status") != "done"
    ]
```

Also extend `add_commitment` to emit `COMMITMENT_RECORDED` with `action="record"` on add (single-line addition near `working_memory.py:148`; bounded ring already enforced — no change needed there).

**Note on signature:** the original prompt drafted `pending_commitments(agent_id)` and `expired_commitments(agent_id)`. The actual `WorkingMemoryManager` is per-runtime (one shared list, no per-agent partition); there is no `agent_id` field on the dict shape Combo A shipped. Drop the `agent_id` parameter — filter operates on the manager-scoped list.

**Verify-first:** `commitments: list[dict[str, Any]]` confirmed at `src/probos/cognitive/working_memory.py:35`. `add_commitment(commitment_id, summary, due_at)` confirmed at `working_memory.py:138-154`. `_max_commitments = 8` ring confirmed at `working_memory.py:108`. No `Commitment` dataclass exists — was a prompt-drafting drift Convention #20 caught in revision.

**Test plan:** 5 tests — `mark_commitment_complete` updates dict's `status="done"` + emits COMMITMENT_RECORDED with `action="complete"`; `pending_commitments` excludes entries with `status="done"`; `expired_commitments(now)` filters by `due < now` and excludes done; `mark_commitment_complete` on unknown id is a clean no-op (no exception, no emit); `add_commitment` emits COMMITMENT_RECORDED with `action="record"`.

## AD-575c: Self-Mention in DM Forwarded Content

**File:** `src/probos/proactive.py`

Combo A AD-575b was wholesale-deferred (theater — `runtime.self_summary_provider` didn't exist). AD-575c is the smaller, edge-case sibling: when an agent's DM contains forwarded Ward Room content that mentions the agent itself (e.g., "Captain said about you: ..."), the DM intake path should preserve the self-reference flag.

Implementation: in `_check_unread_dms` (verified at `proactive.py:584+`, BF-257 hardened), the existing `event_data` dict already exposes `body` per review verification. Scan body for `@<agent_callsign>` patterns; set `dm["self_referenced"] = True` if found. Read-only check; no mutation of upstream content.

**Verify-first:** `_check_unread_dms` confirmed at `src/probos/proactive.py:584`. `event_data["body"]` exposure confirmed in pass-1 review (the DM forwarding path builds the body field; safe to inspect).

**Test plan:** 3 tests — self-mention sets flag (`@<agent_callsign>` present); no mention leaves flag False/missing; case-insensitive match; multiple mentions still set flag once (idempotent).

## What This Combo Does NOT Change

- **AD-572d wholesale-deferred to AD-572d-i** — proactive loop has no interruptible-wait pattern (verified: `proactive.py` uses bare `await asyncio.sleep(self._interval)` at lines 475, 482, 584, 782; zero `asyncio.Event` / `wait_for`). Adding interruptible-wait is architectural surgery on the BF-211-hardened `_think_loop`. **Forcing function:** AD-572d-i ships ONLY when a separate AD introduces the interruptible-wait infrastructure on `_think_loop` (e.g., `await asyncio.wait_for(self._immediate_trigger.wait(), timeout=self._interval)` plus clear-on-wake semantics). Once that lands, AD-572d-i becomes a meaningful 5-line edit setting the trigger from the Captain DM intake path.
- **AD-573e wholesale-deferred to AD-573e-i** — `cognitive_journal.recent_for_agent` does not exist (verified: `journal.py` exposes only `record / get_reasoning_chain / get_token_usage[_since|_by] / get_decision_points / get_stats / start / stop / wipe / prune` per `grep "    def \|    async def " src/probos/cognitive/journal.py`). Closest substitute `get_decision_points(agent_id=...)` filters for high-latency / failures-only — wrong semantics for "recent k entries." **Forcing function:** AD-573e-i ships ONLY when `cognitive_journal` exposes a recency-ordered per-agent recall API (separate AD; the architect did not identify a clean alternative existing API). At that point AD-573e-i becomes a one-method consumer addition on `WorkingMemoryManager`.
- **AD-526e/f/g/h** (spectator commentary, holodeck integration, creative content, chess engine) — deferred; each is substantial enough to warrant standalone treatment. AD-526d is the read-side analytics that exposes the data-collection surface they'll all share.
- **AD-572e** (task awareness in DM) — deferred; needs WorkItemStore deeper integration.
- **AD-573d** (dream-to-WM pipeline) — deferred; depends on `runtime.dream_scheduler` exposing summaries (same blocker as AD-477g).
- **AD-575b** — already wholesale-deferred in Combo A; not revisited.

## Combo Test Plan

Total: ~19 tests across 5 children (4 + 3 + 4 + 5 + 3 = 19). Was ~26 across 7 children pre-revision; drops 4 (AD-572d) + 3 (AD-573e) = 7.

Single test file per child at `tests/test_combo_c_<short-id>.py` OR consolidated `tests/test_combo_c.py` — Builder discretion. Wave 8 Combo A used per-child files.

Run focused gates per child during build (Wave 8 Combo A pattern).

## Combo Tracker Updates

**PROGRESS.md:** prepend single Combo C entry summarizing all 5 surviving children + total test count + 2 wholesale-defers (572d-i / 573e-i with forcing-function notes).

**DECISIONS.md:** single entry under Era V titled `### Combo C: 5 trivial extensions (526d/572c/573c/573f/575c) + 2 wholesale-defers (572d-i / 573e-i) (2026-05-03)`. Brief problem/decision per shipping child + brief deferral rationale per dropped child citing AD-575b precedent and the verify-first non-existence proofs.

**docs/development/roadmap.md:** flip 5 status flags + add 2 deferred entries:
- AD-526d → Closed
- AD-572c → Closed (572d → Deferred to 572d-i; 572e remains Deferred)
- AD-573c, AD-573f → Closed (573d remains Deferred; 573e → Deferred to 573e-i)
- AD-575c → Closed
- New entries: AD-572d-i (Deferred — needs interruptible-wait infrastructure), AD-573e-i (Deferred — needs cognitive_journal recency API)

**GH issues to close (in dispatch):**
- #101 (AD-526 — partial; 526c+526d done, 526e-h still partial; **leave open** with comment update)
- #109 (AD-572 — partial; 572b+c done, 572d→572d-i deferred, 572e remains; **leave open** with comment update reflecting both done-children AND the new 572d-i deferral)
- #8 (AD-573 — partial; 573b+c+f done, 573e→573e-i deferred, 573d remains; **leave open** with comment update reflecting both done-children AND the new 573e-i deferral)
- #7 (AD-575 — partial; 575b dropped in Combo A, 575c done; **CLOSE** since both surface children resolved)

So Combo C closes 1 issue (#7) and updates partial-completion comments on 3 others (#101, #109, #8). The #109 and #8 comments must explicitly cite the new -i sub-children so future work has a hook.

## Verified Against Codebase (2026-05-03 — revision pass)

```
# AD-526d — recreation extension surface
file_search **/recreation/metadata.py
  src/probos/recreation/metadata.py (Combo A AD-526c, commit 16c4ea4 — extend with sibling preferences.py)

grep -n "recreation_preference_tracker" src/probos/
  (zero matches — NEW attribute, documented FP per Wave 5 convention #1)

# AD-572c — Ward Room iteration pattern
grep -n "async def list_channels" src/probos/ward_room/service.py
  241: async def list_channels(self, agent_id: str | None = None) -> list[WardRoomChannel]:

grep -n "class CaptainEngagementProvider" src/probos/cognitive/captain_engagement.py
  23: class CaptainEngagementProvider (Combo A AD-572b)

# AD-572d — wholesale-defer evidence (NON-EXISTENCE proof)
grep -n "_immediate_trigger|asyncio\.Event|wait_for|asyncio\.sleep" src/probos/proactive.py
  475: await asyncio.sleep(self._interval)
  482: await asyncio.sleep(self._interval)
  584: await asyncio.sleep(stagger_delay)
  782: await asyncio.sleep(_backoff)
  (zero asyncio.Event, zero wait_for — interruptible-wait pattern absent; defer to AD-572d-i)

# AD-573c — gap-detection markers + working-memory helper
grep -n "markers = {" src/probos/cognitive/cognitive_agent.py
  1747: markers = {
  1748:     "notebook": re.compile(r'\[NOTEBOOK\s', re.IGNORECASE),
  1749:     "endorse": re.compile(r'\[ENDORSE\s', re.IGNORECASE),
  1750:     "proposal": re.compile(r'\[PROPOSAL\]', re.IGNORECASE),
  1751:     "dm": re.compile(r'\[DM\s', re.IGNORECASE),
  1752:     "ward_room_reply": re.compile(r'\[REPLY\s', re.IGNORECASE),
  1753: }

grep -n "def add_scratchpad" src/probos/cognitive/working_memory.py
  128: def add_scratchpad(self, text: str) -> None:

grep -n "notebook_pattern\|proposal_pattern\|reply.*pattern\|DM.*pattern" src/probos/proactive.py
  2339: notebook_pattern = r'\[NOTEBOOK\s+([\w-]+)\](.*?)\[/NOTEBOOK\]'
  2645: proposal_pattern = r'\[PROPOSAL\]\s*\n(.*?)\n\s*\[/PROPOSAL\]'
  3074: r'\[REPLY\s+(?:thread:?\s*)?(\S+)\]\s*(.*?)\s*\[/REPLY\]'
  3325: AD-453: Extract [DM @callsign]...[/DM] blocks
  (NOTE extractor mirrors notebook_pattern shape)

# AD-573e — wholesale-defer evidence (NON-EXISTENCE proof)
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
  (zero recent_for_agent — recency-ordered per-agent recall API absent; defer to AD-573e-i)

# AD-573f — Convention #20 reality check (LIST-OF-DICT, not dataclass)
grep -n "commitments\|_commitments\|add_commitment" src/probos/cognitive/working_memory.py
   35: commitments: list[dict[str, Any]] = field(default_factory=list)
  108: self._max_commitments = 8
  138: def add_commitment(
  140:     self, commitment_id: str, summary: str, due_at: float | None = None,
  141: ) -> None:
  148:     entry: dict[str, Any] = {
  149:         "id": commitment_id,
  150:         "summary": summary,
  151:     }
  152:     if due_at is not None:
  153:         entry["due"] = due_at
  (Combo A shipped LIST-OF-DICT with keys {id, summary, due?}; NO Commitment dataclass; NO agent_id; NO status field — AD-573f extends this shape)

grep -n "class Commitment" src/probos/
  (zero matches — confirms Combo A did not ship a dataclass)

# AD-575c — DM forwarding body exposure
grep -n "_check_unread_dms\|class ProactiveCognitiveLoop" src/probos/proactive.py
  146: class ProactiveCognitiveLoop
  584: async def _check_unread_dms (BF-257 verified; event_data['body'] exposed per review)

# Combo file paths (R4 fix)
file_search **/working_memory.py
  src/probos/cognitive/working_memory.py  (NOT src/probos/working_memory.py)
```

## Acceptance Criteria

- 5 child ADs implemented as documented (AD-526d, AD-572c, AD-573c, AD-573f, AD-575c).
- 3 new EventTypes in events.py (verified collision-free — `GAME_PREFERENCE_RECORDED`, `WORKING_MEMORY_NOTE_RECORDED`, `COMMITMENT_RECORDED`).
- 1 new public attribute on runtime (`recreation_preference_tracker`) per Wave 5 convention #1.
- ~19 tests pass.
- Single commit `Combo C: AD-526d/572c/573c/573f/575c trivial extensions (572d + 573e wholesale-deferred)`.
- DECISIONS.md combined entry under Era V citing both shipping children and the 2 wholesale-defers (with AD-575b precedent reference).
- roadmap.md 5 status flags flipped + 2 new Deferred entries (AD-572d-i, AD-573e-i) with explicit forcing-function language.
- GH issue #7 closed; #101, #109, #8 partial-completion comments updated; #109 and #8 comments cite the new -i sub-children.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Hard-Stops (per surviving child)

- **AD-526d:** None expected; pure new file.
- **AD-572c:** `ward_room.list_channels` raises unexpectedly — surface; the iterate-channels pattern degrades to empty dict on Exception per the snippet, so runtime impact is bounded. Real hard-stop only if `list_channels` doesn't exist on a deployment topology Builder hits.
- **AD-573c:** `_extract_notes` cannot be wired into the same post-act hook chain as `_extract_notebook` without architectural surgery — surface; may need scope reframe.
- **AD-573f:** None expected after revision (now extends actual dict shape; phantom-API risk eliminated).
- **AD-575c:** `event_data["body"]` field naming differs from review verification (e.g., renamed to `dm_body` mid-flight) — surface; mechanical key fix.

Per Wave 8 AD-575b precedent: any single child hitting a hard-stop should be wholesale-dropped from the combo, not blocking the wave. Document the drop in DECISIONS.md.

---

## Revision (2026-05-03)

Applied review findings from `prompts/Reviews/combo-C-trivial-extensions-review.md` (verdict: ⚠️ Conditional; 5 Required + 3 Recommended + 2 Nits). Combo C trims from 7 to 5 children; AD-573f reshape is the largest in-scope change.

### Required (all addressed)

| ID | Finding | Resolution |
|---|---|---|
| R1 | AD-572d — proactive loop has no interruptible-wait pattern | **Wholesale-deferred to AD-572d-i.** Removed mini-section. Forcing function added to "What This Combo Does NOT Change." Dropped `CAPTAIN_DM_PRIORITY_DISPATCHED` from Section 0. Removed from sequencing chain (proactive.py: 572c → 575c). Updated Combo Discipline / commit message / acceptance criteria / hard-stops. Per AD-575b precedent. |
| R2 | AD-573e — `cognitive_journal.recent_for_agent` does not exist | **Wholesale-deferred to AD-573e-i.** Removed mini-section. Forcing function added (cognitive_journal needs recency-ordered per-agent API). Architect could not identify a clean alternative existing API (`get_decision_points` has wrong latency/failure-filter semantics). Removed from sequencing chain (working_memory.py: 573c → 573f). Updated combo metadata. |
| R3 | AD-573f — Commitment dataclass shape mismatch (Convention #20) | **Reshaped to operate on actual `list[dict[str, Any]]` shape Combo A shipped.** Verified against `working_memory.py:35,108,138-154`. Dropped `Commitment` dataclass references; lifecycle methods now mutate dict's `status` key in-place; dropped `agent_id` parameter (manager is per-runtime, no per-agent partition exists). Test plan reshaped to operate on dicts. Bounded ring already exists; no schema migration needed. |
| R4 | File path error — `src/probos/working_memory.py` is wrong | **Fixed throughout.** Real path: `src/probos/cognitive/working_memory.py`. AD-573c and AD-573f sections now cite correct path. |
| R5 | AD-573c — markers dict needs explicit SEARCH/REPLACE | **Section 1 added** with exact `===MODIFY===` / `===SEARCH===` / `===REPLACE===` block targeting the markers dict at `cognitive_agent.py:1747`. Section 2 covers the proactive.py extractor + dispatch site (mirrors `notebook_pattern` shape at `proactive.py:2339`). |

### Recommended (all addressed)

| ID | Finding | Resolution |
|---|---|---|
| Rec1 | AD-572c iterate-channels pattern under-specified | **Pattern specified inline** as a paste-ready `_build_wardroom_summary` helper. Builder no longer reinvents iteration. |
| Rec2 | AD-526d Callable import missing | **Explicit `from typing import Callable` added** to the AD-526d code skeleton. Mechanical, but ensures the new file lands clean. |
| Rec3 | DECISIONS.md entry must reflect wholesale-drops | **Combo Tracker section updated.** DECISIONS.md title now reads `5 trivial extensions ... + 2 wholesale-defers`. roadmap.md adds 2 new Deferred entries (AD-572d-i, AD-573e-i) with forcing-function language. GH issue comment plan for #109 and #8 explicitly cites the new -i sub-children. |

### Nits (both addressed)

| ID | Finding | Resolution |
|---|---|---|
| N1 | Section 0 EventTypes count drops to 3 | **Done.** Section 0 table now lists 3 events (`GAME_PREFERENCE_RECORDED`, `WORKING_MEMORY_NOTE_RECORDED`, `COMMITMENT_RECORDED`). Explanatory note added that `CAPTAIN_DM_PRIORITY_DISPATCHED` is dropped with the AD-572d wholesale-defer. |
| N2 | "Combo Does NOT Change" needs the new deferrals | **Done.** AD-572d-i and AD-573e-i added at the top of the deferral list with explicit forcing functions, alongside the pre-existing 526e/f/g/h, 572e, 573d, 575b entries. |

### Audit notes

- Phantom-API pre-check expected output unchanged: 2 documented FPs (`recreation_preference_tracker` introduced by 526d per Wave-5 convention #1; `self_summary_provider` retrospective prose in AD-575b deferred entry — historical audit reference, not a live API claim).
- Convention #14 (aggressive pre-deferral): honored. Both wholesale-defers surfaced at architect-review time, not Builder-build time.
- Convention #20 (read shipped code, not prompts): honored on AD-573f — read `working_memory.py` to discover the actual `list[dict]` shape rather than trusting the original prompt's `Commitment`-dataclass assumption.
- AD-575b precedent: applied identically. 7 → 5 children matches Combo A's 8 → 7 drop pattern (single revision pass, single combo, deferred children get -i sub-IDs).
