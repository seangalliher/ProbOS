# AD-719a — Persistent multi-agent chat threads under WardRoom

**Status:** Draft for Wave 163
**Dependencies:** AD-719 ✅ (Wave 135, transient @-mention fan-out), AD-722b-4 ✅ (Wave 160, fleet WS endpoint), existing WardRoom thread storage.
**Closes:** #546
**Estimated tests:** 6 pytest, 4 Vitest.
**Build order:** Independent of the peer-observation cluster.

## Problem

AD-719 (Wave 135) shipped transient @-mention multi-agent chat fan-out: Captain types `@maya @ezri ...` and both agents reply in the same intent surface, but the conversation evaporates after the response cycle. AD-719a makes those multi-agent conversations PERSISTENT under WardRoom thread storage so crew can see each other's prior turns and chime in.

## Architectural decision (from issue body)

Issue #546 explicitly calls for an architectural decision: "whether agents observe other agents' messages mid-thread." Wave 163 ruling:

- **YES, agents observe other agents' messages mid-thread when they have already been @-mentioned in the thread.** Once an agent has been pulled into a thread, subsequent turns from other agents in that thread are visible context.
- **NO, agents do NOT observe messages in threads they were never @-mentioned in.** Cross-thread observation is out of scope for v1.
- **Captain messages are always the seed.** Agent-to-agent messages without a Captain prompt are not generated in v1 (deferred).

This keeps v1 Captain-centric while making the multi-party context observable to participating agents.

## Section 0: Storage shape

The existing WardRoom thread storage at `src/probos/ward_room/service.py:29` (class `WardRoomService`, verified by Architect grep) already supports threads with multiple participants. AD-719a's storage delta is small:

- New thread type marker: `thread_type: Literal["dm", "wr_channel", "multi_agent"]` (or whatever the existing field is — verify before edit).
- Thread participants list: tracks ALL agents that have been @-mentioned across the thread's lifetime, NOT just those replying to the latest turn.

NO new RecordsStore artifact type. The existing thread table is the source of truth.

## Section 1: AD-719 wire-up

`src/probos/cognitive/multi_agent_chat.py` (or wherever AD-719 lives — verify) currently builds an ephemeral fan-out. AD-719a changes:

1. On first `@agent1 @agent2 ...` message, create a new WardRoom thread of type `multi_agent` with all mentioned agents as participants. The Captain is the originator.
2. On subsequent Captain messages in the same conversation, append to the same thread. Detect "same conversation" via the existing IntentSurface session continuity signal (verify — likely a session ID or correlated channel ID).
3. Each agent's reply is appended to the thread as a post.
4. Before generating each agent's reply, INJECT the thread history (last N turns) into the agent's prompt context as the standard WardRoom thread-history injection (reuse existing injection — verify shape).

## Section 2: Cross-agent visibility rules

Built directly on top of the storage: an agent participating in a multi-agent thread reads the entire thread history when generating its reply. Implementation point — in the existing WardRoom thread-history injection function, no special-case needed; the storage already represents the participants correctly, the injection function already reads them.

Source-scan regression test required: the multi_agent thread code path must NOT inject thread context across threads the agent was not @-mentioned in.

## Section 3: UI surface

UI delta is small — multi-agent threads appear in the existing `WardRoomThreadList.tsx` with a small "multi-agent" badge (inline SVG, NOT emoji — HXI Design Principle #3). `WardRoomThreadDetail.tsx` renders the thread as it would any WardRoom thread. The existing thread-rendering logic handles mixed participant identities.

Verify: the existing `WardRoomThreadDetail.tsx` post rendering correctly distinguishes Captain posts vs agent posts. If not, a small visual differentiation MAY be needed — confirm before assuming the existing rendering suffices.

## Section 4: Backwards compatibility

The Wave-135 AD-719 transient flow MUST continue to work for one-shot @-mentions that don't continue. Define "continuation" as: a subsequent Captain message in the same IntentSurface session referencing the same set of agents (or a subset). The first @-mention spawns a thread; if no follow-up arrives within a session timeout (e.g., 30 minutes — confirm existing session-timeout config), the thread persists but receives no further posts. Captain can later resume by clicking the thread in `WardRoomThreadList`.

## Section 5: Tests (≥6 pytest + ≥4 Vitest)

### Pytest — `tests/test_ad719a_multi_agent_threads.py`

1. First `@a1 @a2` message → new WardRoom thread of type `multi_agent` created, both agents in participants.
2. Subsequent Captain message in same session → appended to same thread.
3. Each agent's reply visible to the OTHER agent's prompt context on subsequent turn.
4. Agent NOT participating in the thread does NOT receive thread-history injection.
5. Thread persists across runtime restart (existing storage already handles this; this verifies the new `thread_type` field is persisted).
6. AD-731 invariant: any attachments referenced in multi-agent thread posts use SHA-256 refs through AttachmentStore, never inline bytes.

### Vitest — `ui/src/wardroom/MultiAgentThread.test.tsx`

1. `WardRoomThreadList` renders multi-agent thread badge.
2. `WardRoomThreadDetail` renders posts from multiple agents distinguished correctly.
3. Captain can post into a resumed multi-agent thread.
4. Multi-agent thread shows participants list.

Use **real `SystemConfig()` fixtures** + **real WardRoom thread store** (in-memory variant if needed). NO MagicMock at storage boundary — BF-287.

## Section 6: Builder Standing Rules

- BF-274: single replace for adjacent edits.
- BF-280: no `asyncio.create_subprocess_*` in runtime paths.
- BF-282: n/a.
- BF-286: test scaffolding mirrors production.
- BF-287: real WardRoom thread store fixture; real registry.
- **AD-738b: REQUIRED `npm run build` GATE** — this AD touches `ui/src/`. Per-commit gate runs BOTH `npx vitest run` AND `npm run build`.
- AD-731 invariant: verified by pytest Test 6.
- AD-722c-3: forward markers use TECHNICAL triggers.

## What this does NOT change

- The Wave-135 AD-719 transient fan-out for single-shot @-mentions.
- The WardRoom thread storage schema beyond the small `thread_type` marker (if not already present).
- Agent-to-agent messages without a Captain seed (deferred).
- Cross-thread observation (out of scope).

## Tracking

- `PROGRESS.md`: CLOSED entry referencing #546.
- `docs/development/roadmap.md`: move AD-719a from forward markers to shipped.
- `DECISIONS.md`: append AD-719a entry — multi-agent thread persistence + cross-agent visibility rules.

## Forward markers (TECHNICAL triggers per AD-722c-3)

- **AD-719a-2 — Agent-to-agent messages without Captain seed.** Trigger: when AD-719a has shipped AND ≥10 multi-agent threads exist with cross-agent visibility working. Issue filed.
- **AD-719a-3 — Cross-thread observation gated by AD-729 peer-perception.** Trigger: when AD-729 capability is default-ON for crew. Issue filed.

## Acceptance Criteria

1. All Section 0-4 deliverables landed.
2. ≥6 pytest tests + ≥4 Vitest tests pass.
3. **`cd ui ; npm run build` green** (BF-279 / AD-738b).
4. Source-scan regression: multi-agent thread code does NOT cross-inject thread history to non-participants.
5. AD-719 single-shot @-mention path still works (pytest regression coverage).
6. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-15)

```
ls ui/src/wardroom/
  WardRoomThreadList.tsx, WardRoomThreadDetail.tsx, WardRoomPostItem.tsx
  (existing thread UI — extended, not rewritten)
```

**Builder verify-first flags:**
- WardRoom thread storage module path — VERIFIED: `src/probos/ward_room/service.py` (`WardRoomService`).
- AD-719 transient fan-out code location — VERIFY before Section 1 wire-up.
- `thread_type` field existence vs need-to-add — VERIFY before Section 0.
- IntentSurface session continuity signal — VERIFY before Section 4 timeout logic.
