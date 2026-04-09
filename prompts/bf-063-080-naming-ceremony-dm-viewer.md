# BF-063 + BF-080: Naming Ceremony Logging + DM Channel Viewer

**Type:** Bug Fix (combined)
**Scope:** 1 Python file + 3-4 TSX files + tests
**Depends on:** AD-442 (naming ceremony), AD-574 (DM reply notification), AD-523a (DM viewer spec)
**Issue:** #135

---

## Overview

Two independent bug fixes combined into one build prompt. Zero file overlap.

**BF-063 (Backend):** Naming ceremony silently accepts default callsign when the LLM returns an empty response. The log message `"chose callsign 'Bones'"` is indistinguishable from a genuine agent choice. If the LLM proxy is down during boot, all 14 crew agents silently get seed callsigns with no warning.

**BF-080 (Frontend):** Ward Room DM Log tab shows agent-to-agent DM channels with message counts, but clicking an entry only expands/collapses a preview. The Captain can see that agents are DMing each other but cannot read the conversations. The "Open in Ward Room" link calls `selectChannel()` + `setView('channels')`, but `WardRoomChannelList.tsx:32` filters out DM channels (`c.channel_type !== 'dm'`), creating a dead end.

---

## Prior Work Absorption

| Prior Work | What to Reuse | What NOT to Touch |
|---|---|---|
| **AD-442** (naming ceremony) | `run_naming_ceremony()` at `agent_onboarding.py:306`. Three fallback cases exist: empty response (line 377), invalid name (line 400), duplicate (line 411). Only empty response lacks a warning. | Prompt construction, LLM call, validation regex, blocked names list — all correct |
| **AD-574** (DM reply notification) | Backend DM routing is complete. `find_targets()` handles `channel_type == "dm"` at `ward_room_router.py:495`. `get_unread_dms()` rewritten at `messages.py:610`. | No backend changes needed |
| **AD-576** (LLM unavailability) | LLM health state machine exists in proactive loop. Not connected to commissioning path. Do NOT wire naming ceremony into AD-576's infrastructure — it runs before the proactive loop starts. | `_update_llm_status()` in proactive.py |
| **AD-523a** (DM Channel Viewer spec) | Roadmap specification at `roadmap.md:2764`: "Same thread/post rendering as department channels, just filtered to the DM pair." | AD-523b/c are separate features |
| **BF-095** (god object reduction) | Ward Room package structure: `ward_room/channels.py`, `ward_room/threads.py`, `ward_room/messages.py`, `ward_room/service.py`. Current package shape is post-decomposition. | Package structure is stable |
| **AD-506b** (peer repetition) | Not affected — operates on Ward Room posts, not DM UI navigation | |

---

## Phase 1: BF-063 — Naming Ceremony Logging Fix

### Problem

In `agent_onboarding.py`, `run_naming_ceremony()` has three fallback paths that all funnel into the same `logger.info()` at line 416:

```python
logger.info("Naming ceremony: %s chose callsign '%s' (reason: %s)", agent.agent_type, chosen, reason)
```

| Scenario | Current Behavior | Expected Behavior |
|---|---|---|
| LLM returns valid name | `logger.info` — correct | No change |
| LLM returns empty string | `reason = "Default callsign accepted."` → `logger.info` | `logger.warning` with distinct message |
| LLM returns name > 30 chars | `reason = "Default callsign accepted."` → `logger.info` | `logger.warning` with distinct message |
| LLM returns invalid name | `reason = "Chosen name was not a valid callsign."` → `logger.info` | `logger.warning` (name was generated but rejected) |
| LLM returns duplicate name | `reason = f"...already taken."` → `logger.info` | `logger.info` — acceptable (system worked correctly) |
| LLM raises exception | `logger.warning` at line 422 — correct | No change |
| No LLM client | `logger.warning` at line 419 — correct | No change |

### Changes

**File:** `src/probos/agent_onboarding.py`

1. **Line 377-379** — After `if not chosen or len(chosen) > 30:`, add a flag to distinguish LLM failure from valid choice:

```python
if not chosen or len(chosen) > 30:
    chosen = seed_callsign
    reason = "Default callsign accepted."
    _llm_empty = True
else:
    _llm_empty = False
```

2. **Line 400 area** — After `_is_valid_callsign()` rejects a name, set a flag:

```python
if not _is_valid_callsign(chosen):
    _llm_rejected = chosen  # preserve what the LLM tried
    chosen = seed_callsign
    reason = f"Chosen name '{_llm_rejected}' was not a valid callsign."
```

3. **Line 416** — Replace the single `logger.info` with conditional logging:

```python
if _llm_empty:
    logger.warning(
        "Naming ceremony: LLM returned empty/oversized response for %s, "
        "falling back to seed callsign '%s'",
        agent.agent_type, chosen
    )
elif "not a valid callsign" in reason:
    logger.warning(
        "Naming ceremony: LLM suggested invalid name for %s, "
        "falling back to seed callsign '%s' (reason: %s)",
        agent.agent_type, chosen, reason
    )
else:
    logger.info(
        "Naming ceremony: %s chose callsign '%s' (reason: %s)",
        agent.agent_type, chosen, reason
    )
```

### Tests

**File:** `tests/test_onboarding.py`

1. **Update `test_naming_ceremony_fallback_on_empty`** (line 103) — Add log assertion:
   - Assert `logger.warning` was called with "LLM returned empty/oversized"
   - Assert `logger.info` with "chose callsign" was NOT called

2. **Update `test_naming_ceremony_fallback_on_error`** (line 122) — Already asserts return value. Add:
   - Assert `logger.warning` was called with "Naming ceremony failed"

3. **New test: `test_naming_ceremony_invalid_name_logs_warning`** — Mock LLM to return `"Captain\nI choose Captain"`. Assert:
   - Returns seed callsign
   - `logger.warning` called with "invalid name"

4. **New test: `test_naming_ceremony_oversized_name_logs_warning`** — Mock LLM to return a 50-char string. Assert:
   - Returns seed callsign
   - `logger.warning` called with "empty/oversized"

5. **New test: `test_naming_ceremony_valid_name_logs_info`** — Mock LLM to return `"Kira\nI choose Kira"`. Assert:
   - Returns `"Kira"`
   - `logger.info` called with "chose callsign"
   - `logger.warning` NOT called

---

## Phase 2: BF-080 — DM Channel Conversation Viewer

### Problem

Three interrelated gaps prevent DM channel navigation:

1. `WardRoomChannelList.tsx:32` filters out `channel_type === 'dm'` — DM channels never appear in sidebar
2. `wardRoomView` type union is `'channels' | 'dms'` — no state for viewing a specific DM conversation
3. `DmActivityLog` click handler (line 90) only toggles expand/collapse — no navigation

### Approach

Add a `'dm-detail'` view state. When a DM entry is clicked in the DM Log, select that channel (reusing existing `selectWardRoomChannel` store action which fetches threads via `/api/wardroom/channels/{channelId}/threads`) and switch to `'dm-detail'` view. This view renders `WardRoomThreadList` and `WardRoomThreadDetail` — the same components used for department channels. No new backend endpoints needed.

### Changes

**File:** `ui/src/store/types.ts`

1. **Line 247** — Expand view union type:
```ts
wardRoomView: 'channels' | 'dms' | 'dm-detail';
```

**File:** `ui/src/store/useStore.ts`

2. **Add `selectDmChannel` action** (near `selectWardRoomChannel` at line 566):
```ts
selectDmChannel: async (channelId: string) => {
    await get().selectWardRoomChannel(channelId);
    set({ wardRoomView: 'dm-detail' as const });
},
```
This reuses `selectWardRoomChannel` (which fetches threads and sets `wardRoomActiveChannel`) then switches to the DM detail view.

3. **Expose `selectDmChannel` in the store interface** (add to the WardRoom actions section in the store type).

4. **WebSocket handler** — In the `ward_room_thread_created` / `ward_room_post_created` handlers (lines 1605-1631), also call `refreshWardRoomDmChannels()` so the DM Log stays current when new DM activity arrives.

**File:** `ui/src/components/wardroom/WardRoomPanel.tsx`

5. **DmActivityLog click handler** — Replace expand-only behavior with navigation. Modify the entry `onClick` handler at line 90:

```tsx
onClick={() => selectDmChannel(ch.id)}
```

Remove the expand/collapse state entirely — clicking a DM channel navigates into it. The "Open in Ward Room" link (lines 126-134) can be removed since clicking the entry itself now navigates.

6. **Add back-navigation header** — When `wardRoomView === 'dm-detail'`, render a header bar with:
   - Back arrow (`←`) to return to DM Log (`setView('dms')`)
   - Channel description (e.g., "DM: Chapel ↔ Lynx")
   - This should appear above the `WardRoomThreadList` component

7. **View routing in the main Ward Room panel** — In the view switch logic (around line 291), add the `'dm-detail'` case:

```tsx
{view === 'channels' && <WardRoomChannelList ... />}
{view === 'dms' && <DmActivityLog ... />}
{view === 'dm-detail' && (
    <>
        <DmDetailHeader onBack={() => setView('dms')} channel={activeChannelInfo} />
        <WardRoomThreadList />
    </>
)}
```

8. **Thread detail navigation** — `WardRoomThreadList` already uses `selectThread(t.id)` which loads the thread detail view. `WardRoomThreadDetail` has no channel-type checks. Both components work unchanged for DM channels.

**File:** `ui/src/components/wardroom/WardRoomChannelList.tsx`

9. **No changes needed.** The DM filter at line 32 stays — DM channels are accessed through the DM Log tab, not the channel sidebar. This is the correct UX: department channels in the Channels tab, DM conversations in the DM Log tab.

### Tests

**File:** `ui/src/__tests__/WardRoomPanel.test.tsx`

10. **New test: `test_selectDmChannel_sets_view_and_fetches`** — Call `selectDmChannel(channelId)`, assert:
    - `wardRoomActiveChannel` is set to `channelId`
    - `wardRoomView` is `'dm-detail'`
    - Threads are fetched (mock `/api/wardroom/channels/{id}/threads`)

11. **New test: `test_dm_detail_back_returns_to_dms`** — Set view to `'dm-detail'`, call `setWardRoomView('dms')`, assert view is `'dms'`.

12. **New test: `test_dm_websocket_refreshes_dm_channels`** — Trigger a `ward_room_post_created` event, assert `refreshWardRoomDmChannels` is called.

---

## Engineering Principles Compliance

| Principle | How Applied |
|---|---|
| **Single Responsibility** | BF-063: logging logic separated from validation logic via flags. BF-080: `selectDmChannel` is a thin wrapper around existing `selectWardRoomChannel`. |
| **Open/Closed** | BF-080: extends `wardRoomView` union type; existing channel components (`WardRoomThreadList`, `WardRoomThreadDetail`) work unchanged. |
| **DRY** | BF-080: reuses `selectWardRoomChannel` store action, `WardRoomThreadList`, `WardRoomThreadDetail`. No duplicate thread rendering. |
| **Fail Fast / Log-and-Degrade** | BF-063: empty LLM response now logs WARNING (visible degradation) instead of silently accepting. System still functions (seed callsign used). |
| **Law of Demeter** | BF-080: `selectDmChannel` calls store actions, not internal component state. |
| **Defense in Depth** | BF-063: three distinct log paths (info/warning/warning) make failure visible at every level. |

---

## Files Modified Summary

| File | Bug | Changes |
|---|---|---|
| `src/probos/agent_onboarding.py` | BF-063 | Conditional logging in `run_naming_ceremony()` |
| `tests/test_onboarding.py` | BF-063 | 3 new tests + 2 updated tests |
| `ui/src/store/types.ts` | BF-080 | Expand `wardRoomView` union type |
| `ui/src/store/useStore.ts` | BF-080 | `selectDmChannel` action + WebSocket DM refresh |
| `ui/src/components/wardroom/WardRoomPanel.tsx` | BF-080 | DM entry click navigation + `dm-detail` view routing + back header |
| `ui/src/__tests__/WardRoomPanel.test.tsx` | BF-080 | 3 new tests |

**Total: 6 files, ~11 tests (5 BF-063 + 3 BF-080 + 3 existing updated)**

---

## What NOT to Change

- **No backend changes for BF-080.** API endpoints exist and work for DM channels.
- **Do NOT wire BF-063 into AD-576 LLM health infrastructure.** The naming ceremony runs during commissioning, before the proactive loop starts. AD-576's state machine lives in `ProactiveCognitiveLoop`.
- **Do NOT remove the DM filter from `WardRoomChannelList.tsx`.** DM channels belong in the DM Log tab, not the department channel sidebar.
- **Do NOT change the expand/collapse behavior in the DM Log for individual thread previews** — the entry-level click navigates; once inside the DM channel, individual thread clicking uses the existing thread selection pattern.
- **Do NOT add bridge alerts for naming ceremony LLM failure.** The current scope is logging visibility only. Bridge alert integration (if desired) is a separate AD.

---

## Builder Verification Checklist

After implementation, verify:

- [ ] Run `python -m pytest tests/test_onboarding.py -v` — all tests pass including 3 new + 2 updated
- [ ] Run `npx vitest run src/__tests__/WardRoomPanel.test.tsx` — all tests pass including 3 new
- [ ] Grep for `"Default callsign accepted"` — should appear zero times in log output during empty LLM test (replaced by warning message)
- [ ] Grep for `selectDmChannel` — exists in store and WardRoomPanel
- [ ] Grep for `dm-detail` — exists in types.ts, useStore.ts, and WardRoomPanel.tsx
- [ ] Existing tests: `python -m pytest tests/test_onboarding.py tests/test_identity_persistence.py tests/test_new_crew_auto_welcome.py -v` — no regressions
- [ ] Full vitest: `npx vitest run` — no regressions
- [ ] Update tracking: PROGRESS.md (BF-063 CLOSED, BF-080 CLOSED), DECISIONS.md, roadmap.md bug tracker entries
