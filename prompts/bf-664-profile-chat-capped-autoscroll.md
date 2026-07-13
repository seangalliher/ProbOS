# BF-664 — ProfileChatTab capped-transcript auto-scroll

**One-line:** Make `ProfileChatTab` react to transcript tail continuity instead of count alone, so bounded 200/100-message appends preserve Captain/agent follow policy, meeting remounts, post-layout measurement, and BF-293 reset behavior.

**Status:** Ready to build
**Type:** Bug fix — **BF-664**; no new AD
**GitHub issue:** #1030
**Base HEAD:** `c0418a8a91ba186453e382446ce44ceed136e9f7`
**Numbering verified:** highest in `PROGRESS.md` is AD-1121 / BF-663; BF-664 is the next BF
**Dependencies:** AD-938, AD-984a/984c, AD-1056, AD-1075, BF-293
**Estimated tests:** 12–18 pure/component regression cases, primarily in one new mounted integration file

## Problem

`ProfileChatTab` currently keys both scrolling and BF-293 reply detection to `messages.length`. That signal stops changing after either displayed source saturates:

- a loaded active thread requests the newest 200 messages, `appendThreadMessage()` keeps only `existing.slice(-199)` plus the new message, and rendering is independently capped at 200;
- a cold/no-thread 1:1 uses `addAgentMessage()`, which keeps `existing.messages.slice(-99)` plus the new message.

At saturation, the oldest ID is removed and a new tail ID is appended while count remains 200 or 100. The component rerenders because Zustand publishes a new `Map`, but the scroll effect and BF-293 effect do not execute because their dependencies remain count-only.

The live defect therefore bypasses all existing policy inside `decideScrollOnUpdate()`:

- a pinned agent reply no longer follows;
- an unpinned Captain send no longer invokes Captain-always-follow;
- BF-293 no longer clears the stale empty-transcript counter on a capped agent reply;
- meeting transcript hide/show is not an effect trigger, even though the transcript DOM node is conditionally unmounted;
- merely adding the tail ID to the dependency list would be unsafe because the current helper treats every equal-count update as a bulk jump, yanking an unpinned reader to the bottom.

This is a frontend viewport-state bug. Persisted messages are intact.

## Verified live data paths

### Display source and bounds

1. `messages` is selected from `threadMessages[activeThreadId]` for a warm 1:1/group/meeting, otherwise from `agentConversations[agentId].messages` for a cold 1:1.
2. `listMessages(threadId, limit = 200)` loads the newest page because the backend endpoint calls `list_messages(..., newest=True)`; `appendThreadMessage()` then preserves the newest 200 with `[...existing.slice(-199), msg]`.
3. `buildTranscriptItems()` has a separate `TRANSCRIPT_RENDER_CAP = 200` safeguard.
4. `addAgentMessage()` generates a new required `AgentProfileMessage.id` and preserves the newest 100 with `[...existing.messages.slice(-99), msg]`.
5. `setThreadMessages()` itself is a replacement action and intentionally does not impose a cap. Do not misstate or change that contract: the normal loader requests 200, while replacement/load races must be classified safely by the scroll transition logic.

### Message identity and append producers

`AgentProfileMessage.id` is required and `role` is exactly `'user' | 'agent' | 'system'`.

- Persisted thread DTO IDs are preserved; backend `captain` roles map to UI `user`.
- Cold-buffer messages receive `${Date.now()}-${random}` IDs in `addAgentMessage()`.
- Optimistic Captain thread messages receive a new ID before the network request.
- Group replies, 1:1 replies, and call-open greetings each receive a new thread-message ID.
- Group meeting replies use the shared `appendReply()` path whether reveal is timer-paced or voice-completion-paced.
- Conversation-mode `onAgentReply` appends to the per-agent buffer. That is relevant to the cold fallback and must not be rerouted in this BF.
- System/error placeholders currently append only to the per-agent buffer on their existing paths. Do not change their routing.

The scroll fix must be producer-agnostic: it reacts to the selected transcript’s stable tail identity, so Captain, normal agent, group, meeting, call-greeting, and conversation-controller appends all inherit the fix without editing those append paths.

### Current scroll and visibility state

- `scrollStateRef` stores only `{ key, count }`.
- The effect depends on `[messages.length, agentId, activeThreadId]`.
- `decideScrollOnUpdate()` recognizes only `count === prevCount + 1` as incremental and otherwise jumps.
- `showTranscript` is false only while a meeting is active and `meetingChatVisible` is false.
- `{showTranscript && <div ref={scrollContainerRef}>...}` unmounts the transcript while hidden.
- Smooth follow already measures `scrollHeight` inside `requestAnimationFrame()` and uses `scrollTo()` with a `scrollTop` fallback.
- The scheduled frame has no cleanup, so an old-context frame can survive a hide, context switch, or unmount.
- `ui/src/main.tsx` does not wrap the app in `StrictMode`; nevertheless, the effect must remain safe under setup/cleanup replay and test remounts.

### Existing tests

- `scrollAnchor.test.ts` proves the old count policy only.
- `threadMessages.test.ts` proves the 200-item store cap in isolation.
- `ProfileChatTab.threadTranscript.test.tsx` proves source selection, DTO identity/role mapping, render cap, load behavior, and mirrored group reconciliation.
- `ProfileChatTab.ad1075.test.tsx` contains source-string wiring guards, not mounted scroll behavior.
- `ProfileChatTab.ad984b.test.tsx` proves the real component is mountable with the real Zustand store when voice/speech and `MeetingView` are mocked.
- `ProfileChatTab.bf293.test.tsx` behaviorally reaches the private counter through the legitimate PTT callbacks, but its reply-reset case is not saturated.
- The verified baseline command passed **71 tests in 7 files** at the base HEAD.

## Design decisions

### DD-1 — Tail identity plus immediate predecessor continuity is the revision signal

Do not add a global store revision map and do not depend on the entire `messages` array merely to force the effect.

In `ProfileChatTab`, derive once per render:

- `currentTailId`: final selected message ID, or `null`;
- `currentTailRole`: final selected message role, if any.

Extend the local scroll ref to retain:

- context key (`agentId::activeThreadId`),
- observed count,
- observed tail ID,
- whether the transcript DOM was visible on that observation.

Before replacing the prior ref value, compute append continuity from the old tail and the current selected transcript. The strongest minimal O(1) signal is:

- current tail changed, and
- the prior tail ID is now the current penultimate message ID.

Name this boolean clearly, for example `previousTailContinues` or `previousTailIsPredecessor`. It is stronger than “the old tail occurs somewhere in the array”: a same-size load/replacement that happens to overlap an old message must not masquerade as a one-message capped append.

This signal is true for both live shapes:

- ordinary append: `[...old, new]` (`count = prevCount + 1`);
- bounded append: `[...oldWithoutOldest, oldTail, new]` (`count = prevCount`).

It is false for an unrelated equal-size replacement and for an initial load with no prior tail.

### DD-2 — Extend the existing pure decision; do not add a second policy abstraction

Keep `decideScrollOnUpdate()` as the single pure policy function. Extend its required input with the minimal transition metadata:

- `switched`;
- `remounted` (strictly hidden-to-visible; the first visible mount remains an initial load/context-switch case);
- `prevCount` and `count`;
- `prevTailId` and `tailId`;
- `previousTailContinues` (the immediate-predecessor condition from DD-1);
- `pinned`;
- `lastFromSelf`.

The decision table is load-bearing:

| Transition | Decision |
|---|---|
| Empty transcript | no action |
| Context switch | instant jump |
| Hidden-to-visible transcript remount | instant jump |
| Same count and same tail | no action |
| Tail changed, `count = prevCount + 1`, prior tail is immediate predecessor | incremental append |
| Tail changed, `count = prevCount`, prior tail is immediate predecessor | capped incremental append |
| Initial load with no prior tail, multi-message load, count decrease, count increase without continuity, or same-size replacement without continuity | safe bulk/replacement jump |

For either incremental class:

- follow smoothly when pinned;
- do not follow an unpinned agent append;
- always follow a Captain append (`lastFromSelf`).

Treating the first message after an empty observation as a direct jump is correct and protects the “initial history loads instantly” invariant; there is no earlier scrollable content to animate through.

### DD-3 — Visibility is observed state, not just a render conditional

Add `showTranscript` to the scroll effect dependencies.

Effect order must be:

1. read prior ref state;
2. compute context switch, hidden-to-visible remount, prior tail, current tail, and continuity;
3. publish the new observed `{ key, count, tailId, visible }` state even when hidden or empty;
4. if hidden, perform no DOM lookup and schedule no frame;
5. if visible, ask the pure helper for the action.

While hidden, message revisions therefore advance without scrolling. On show, `remounted` forces one instant jump on the newly mounted container and restores `pinnedToBottomRef.current = true`.

Do not preserve a stale pre-hide “unpinned” state onto a newly mounted DOM node.

### DD-4 — Keep post-layout follow and cancel stale frames

Preserve direct `scrollTop = scrollHeight` for instant jumps and the existing `scrollIntoView({ behavior: 'auto' })` fallback when no container exists.

Preserve smooth incremental follow inside `requestAnimationFrame()`:

- do not capture `scrollHeight` before scheduling;
- read `scrollContainerRef.current` and its final `scrollHeight` inside the callback;
- preserve `scrollTo({ top: c.scrollHeight, behavior: 'smooth' })` and the jsdom-compatible `scrollTop` fallback.

Capture the returned frame ID and return an effect cleanup that cancels it. A dependency change (tail/count/context/visibility), context switch, hide, or unmount must cancel the prior scheduled frame before the next effect can act on a different DOM node. Do not let a stale closure scroll a replacement transcript.

The production entry is not currently in React `StrictMode`, but this cleanup also makes effect replay safe: a replay cancels the first scheduled frame before scheduling the surviving one.

### DD-5 — Reuse the tail revision for BF-293

Change the BF-293 reset effect to react to the same tail revision (`currentTailId`, plus context identity where needed), not only count.

It must still inspect the current tail role and reset only when the tail is an agent message. A capped Captain/user append must not reset the counter. Do not expose the private ref or add a test-only API.

## Implementation

### Section 1 — Pure transition policy

**Modify:** `ui/src/chat/scrollAnchor.ts`

1. Extend `decideScrollOnUpdate()` with the DD-2 required metadata.
2. Implement the decision table exactly.
3. Update the docstring: bounded equal-count continuity is incremental; unrelated replacement is bulk; remount is instant.
4. Keep `isPinnedToBottom()` and `PIN_THRESHOLD_PX` unchanged.
5. Keep full TypeScript annotations on the exported function and interfaces.

### Section 2 — ProfileChatTab effect wiring

**Modify:** `ui/src/components/profile/ProfileChatTab.tsx`

1. Derive current tail identity/role once from the selected `messages` source.
2. Extend `scrollStateRef` to context/count/tail/visibility.
3. Compute immediate-predecessor continuity before replacing the ref.
4. Add tail ID and `showTranscript` to the effect dependency list; keep count and context dependencies. Do not add the whole array.
5. Advance observed state while hidden, but do not scroll while hidden.
6. Pass the full transition metadata to `decideScrollOnUpdate()`.
7. Preserve direct jump and pinned reset for context/load/remount.
8. Preserve post-layout smooth follow, add frame-ID cleanup, and cancel on dependency change/unmount.
9. Change BF-293 to use the same tail revision instead of count-only dependency.
10. Do not touch any send, group, meeting voice, call greeting, message ID, role, load, or store action path.

### Section 3 — Pure regression matrix

**Modify:** `ui/src/chat/__tests__/scrollAnchor.test.ts`

Update all existing calls for the new required input and add explicit cases for:

1. empty transcript -> no action;
2. context switch -> instant jump;
3. transcript remount -> instant jump;
4. initial/bulk load without prior-tail continuity -> instant jump;
5. unchanged count and unchanged tail -> no action;
6. ordinary pinned agent append -> smooth follow;
7. ordinary unpinned agent append -> no scroll;
8. ordinary unpinned Captain append -> smooth follow;
9. equal-count capped pinned agent append -> smooth follow;
10. equal-count capped unpinned agent append -> no scroll;
11. equal-count capped unpinned Captain append -> smooth follow;
12. same-count changed-tail replacement without immediate-predecessor continuity -> instant bulk jump;
13. `count = prevCount + 1` without continuity -> instant bulk jump (replacement/load race, not append);
14. multi-message load -> instant jump.

Do not weaken existing `isPinnedToBottom()` coverage.

### Section 4 — Real mounted behavioral integration

**Add (explicitly authorized):** `ui/src/components/profile/__tests__/ProfileChatTab.bf664.test.tsx`

A new file is cleaner than converting the AD-1075 source-guard file. Mount the real `ProfileChatTab` with the real Zustand `useStore`; adapt the verified mocks from `ProfileChatTab.ad984b.test.tsx` (voice, speech input, and `MeetingView`). Do not mirror the component logic and do not extract a hook for testability.

Harness requirements:

- reset all relevant Zustand slices for every test: agents, conversations, thread mappings, chat threads, thread messages, profile-thread override, meeting visibility/audio, and typing state;
- route/mock history, profile, voice-health, and thread-message fetches deterministically so `loadThreadMessages()` cannot overwrite seeded state unexpectedly;
- when testing the loader, control its resolution explicitly;
- use required, unique message IDs and real roles;
- install a deterministic queued `requestAnimationFrame`/`cancelAnimationFrame` harness;
- make `scrollHeight`, `clientHeight`, and `scrollTop` controllable on the actual `data-testid="chat-transcript"` node;
- use the real store actions `setThreadMessages()`, `appendThreadMessage()`, and `addAgentMessage()`;
- clean up DOM, globals, local storage, queued frames, and store state after every test.

Required mounted behaviors:

1. Seed exactly 200 active-thread messages, append the 201st agent message through `appendThreadMessage()`, assert the store remains at 200 with old tail as the new penultimate ID, assert pinned follow queues exactly one frame, mutate mocked `scrollHeight` before flushing, then assert smooth follow uses the final height.
2. Repeat at 200 while unpinned (drive the real `onScroll` path); an agent append must queue no frame and make no scroll call.
3. At 200 while unpinned, append a Captain/user message; it must queue and smoothly follow.
4. Seed exactly 100 cold 1:1 messages through the real per-agent buffer, prove the 101st append keeps 100, and behaviorally cover capped agent follow plus Captain-always-follow. At least one cold-path case must exercise the `scrollTop` fallback when `scrollTo` is absent.
5. Resolve an initial active-thread load with 200 messages after the empty mount; it must set `scrollTop` directly with no smooth frame.
6. Switch between two thread contexts; the new context must jump directly. If a smooth frame was queued for the old context, the switch must cancel it and flushing the queue must not perform the stale smooth scroll.
7. In an active meeting, hide the transcript, append at the 200 cap, assert no scroll/frame while hidden, show it, then assert the newly mounted transcript jumps directly to the latest height and is pinned.
8. Replace a same-count active transcript with unrelated IDs/tail and no immediate-predecessor continuity; mounted wiring must take the safe instant-jump path, not capped smooth follow.
9. Unmount with a smooth frame pending and assert it is cancelled; flushing after unmount must not scroll.

Retain `ProfileChatTab.ad1075.test.tsx` source guards as a lightweight wiring tripwire, but they are not evidence for BF-664 behavior. The new mounted suite is mandatory.

### Section 5 — BF-293 saturated reply reset

**Modify:** `ui/src/__tests__/ProfileChatTab.bf293.test.tsx`

Add one behavioral regression using the existing legitimate seam:

1. force the no-thread cold fallback and seed exactly 100 messages through `addAgentMessage()`;
2. mount the real component;
3. drive two empty browser-SR presses through the captured `startListening` error callbacks so the private counter reaches 2;
4. append an agent reply through `addAgentMessage()` and assert the list stays at 100 with a changed tail;
5. press a third time and prove browser SR is called a third time while the Whisper fallback is not armed.

Also keep the existing user-message negative test: a capped user/Captain append must not reset the counter. Do not expose `emptyTranscriptCountRef` and do not add a production test hook.

## Exact files

**Modify production:**

- `ui/src/chat/scrollAnchor.ts`
- `ui/src/components/profile/ProfileChatTab.tsx`

**Modify tests:**

- `ui/src/chat/__tests__/scrollAnchor.test.ts`
- `ui/src/__tests__/ProfileChatTab.bf293.test.tsx`

**Add test (authorized):**

- `ui/src/components/profile/__tests__/ProfileChatTab.bf664.test.tsx`

**Reference/run only — do not modify unless a directly contradicted guard requires a minimal update:**

- `ui/src/components/profile/__tests__/ProfileChatTab.ad984b.test.tsx`
- `ui/src/components/profile/__tests__/ProfileChatTab.threadTranscript.test.tsx`
- `ui/src/components/profile/__tests__/ProfileChatTab.ad1075.test.tsx`
- `ui/src/store/__tests__/threadMessages.test.ts`
- `ui/src/components/profile/__tests__/ProfileChatTab.ad1062.test.tsx`
- `ui/src/components/profile/profileTranscript.ts`
- `ui/src/components/sidebar/threadApi.ts`
- `ui/src/store/useStore.ts`
- `ui/src/store/types.ts`
- `ui/src/main.tsx`

No backend, store, API, persistence, config, tracker, or decision-log file is in scope.

## Test commands

Run from `D:\ProbOS\ui`.

Focused BF-664 gate:

    npm exec vitest -- run src/chat/__tests__/scrollAnchor.test.ts src/components/profile/__tests__/ProfileChatTab.bf664.test.tsx src/__tests__/ProfileChatTab.bf293.test.tsx src/components/profile/__tests__/ProfileChatTab.ad1075.test.tsx

Relevant compatibility gate:

    npm exec vitest -- run src/store/__tests__/threadMessages.test.ts src/components/profile/__tests__/ProfileChatTab.ad984b.test.tsx src/components/profile/__tests__/ProfileChatTab.threadTranscript.test.tsx src/components/profile/__tests__/ProfileChatTab.ad1062.test.tsx

Complete UI suite (the supported `package.json` script is `vitest run`):

    npm run test

Production TypeScript/Vite build (the supported script is `tsc -b && vite build`):

    npm run build

## Acceptance criteria

1. Initial history, multi-message loads, context switches, and hidden-to-visible transcript remounts jump directly to the final bottom.
2. Ordinary and equal-count capped appends are classified by tail identity plus immediate-predecessor continuity, not count alone.
3. A pinned agent append follows smoothly at both active-thread and cold-buffer caps.
4. An unpinned agent append never scrolls at either cap.
5. A Captain append always follows, including at the 200- and 100-message caps.
6. Unchanged count/tail causes no action; same-count changed-tail replacement without continuity takes the safe bulk-jump path.
7. Hidden meeting appends perform no DOM scroll; showing the remounted transcript restores the latest position and pinned state.
8. Smooth follow reads `scrollHeight` inside the scheduled animation frame after markdown/artifact layout and preserves the `scrollTo`/`scrollTop` fallback behavior.
9. Pending frames are cancelled on hide, context switch, dependency replacement, and unmount; no stale frame scrolls a new or dead transcript.
10. BF-293 resets on a capped agent reply and does not reset on a capped Captain/user append.
11. Both selected transcript sources, all existing append producers, IDs, roles, routing, caps, and initial-load reconciliation remain unchanged.
12. Pure tests, real mounted integration tests, the complete Vitest suite, and `npm run build` pass.
13. Verify all changes comply with the Engineering Principles in .github/copilot-instructions.md.

## Do Not Build

- Do not remove or increase the 100/200-message bounds.
- Do not modify `addAgentMessage()`, `setThreadMessages()`, `appendThreadMessage()`, `listMessages()`, `buildTranscriptItems()`, or backend thread persistence/API behavior.
- Do not add pagination, virtualization, polling, WebSocket delivery, or a new-messages affordance.
- Do not add a global transcript revision map/counter to Zustand.
- Do not depend on the full `messages` array merely to force effect execution.
- Do not change Captain/group/1:1 routing, progressive reveal, meeting voice, call greeting, message roles, or ID generation.
- Do not refactor wider audio, meeting, artifact, profile, or store architecture.
- Do not extract a hook solely to avoid mounting `ProfileChatTab`.
- Do not replace post-layout animation-frame scrolling with eager pre-layout measurement.
- Do not expose private refs or add production-only-for-tests branches.
- Do not edit backend source/tests, config, `PROGRESS.md`, `DECISIONS.md`, roadmap files, or issue metadata.
- Do not introduce an AD; this is BF-664 only.

## Stop conditions

Stop and return to the Architect if:

- required behavior appears to need a store/API/cap/routing change;
- unique message IDs are not available on one of the live selected transcript paths;
- the implementation requires a full-array dependency or a global revision registry;
- a same-count replacement cannot be distinguished from append continuity;
- hidden updates would scroll an unmounted node;
- a pending animation frame cannot be cancelled before context replacement/unmount;
- or the mounted suite can pass only by mirroring the component or exposing private production state.

## Verified Against Codebase (2026-07-13, HEAD c0418a8a91ba186453e382446ce44ceed136e9f7)

```text
git grep -n "selectTranscriptMessages" -- ui/src/components/profile/ProfileChatTab.tsx
  573: const messages = selectTranscriptMessages(activeThreadId, threadMsgs, conversation?.messages)

git grep -n -E "limit = 200|slice\(-199\)|slice\(-99\)|TRANSCRIPT_RENDER_CAP = 200|newest=True" -- ui/src src/probos/routers/threads.py
  ui/src/components/sidebar/threadApi.ts:291: listMessages(threadId, limit = 200)
  ui/src/store/useStore.ts:1375: messages: [...existing.messages.slice(-99), msg]
  ui/src/store/useStore.ts:1416: [...existing.slice(-199), msg]
  ui/src/components/profile/profileTranscript.ts:51: TRANSCRIPT_RENDER_CAP = 200
  src/probos/routers/threads.py:335: newest=True

git grep -n -E "scrollStateRef|decideScrollOnUpdate|messages.length, agentId|BF-293|\[messages.length\]" -- ui/src/components/profile/ProfileChatTab.tsx ui/src/chat/scrollAnchor.ts
  ui/src/components/profile/ProfileChatTab.tsx:719: scrollStateRef stores { key, count }
  ui/src/components/profile/ProfileChatTab.tsx:736: decideScrollOnUpdate call
  ui/src/components/profile/ProfileChatTab.tsx:758: [messages.length, agentId, activeThreadId]
  ui/src/components/profile/ProfileChatTab.tsx:788: BF-293 reset comment
  ui/src/components/profile/ProfileChatTab.tsx:799: [messages.length]
  ui/src/chat/scrollAnchor.ts:65: count === prevCount + 1 is the only incremental class

git grep -n -E "showTranscript|requestAnimationFrame|scrollTop = .*scrollHeight|scrollTo" -- ui/src/components/profile/ProfileChatTab.tsx
  701: showTranscript derives from meeting state/visibility
  743: direct scrollTop jump
  749: requestAnimationFrame smooth follow
  754: scrollTo reads c.scrollHeight inside the callback
  755: scrollTop fallback
  1431: conditional transcript mount

git grep -n -E "addAgentMessage\(|appendThreadMessage\(" -- ui/src/components/profile/ProfileChatTab.tsx
  640/641: call-open greeting -> buffer + thread
  905/910: Captain send -> buffer + active thread
  993/998: group reply -> buffer + active thread
  1128/1133: 1:1 reply -> buffer + active thread
  1247: conversation-controller reply -> buffer

git grep -n -E "export interface AgentProfileMessage|role: 'user'.*'agent'.*'system'|Date.now" -- ui/src/store/types.ts ui/src/store/useStore.ts ui/src/components/profile/ProfileChatTab.tsx
  ui/src/store/types.ts:369-374: required id and three-state role
  ui/src/store/useStore.ts:1363: generated cold-buffer ID
  ui/src/components/profile/ProfileChatTab.tsx:642,911,999,1134: generated thread append IDs

git grep -n "render(<ProfileChatTab" -- ui/src/components/profile/__tests__/ProfileChatTab.ad984b.test.tsx ui/src/__tests__/ProfileChatTab.bf293.test.tsx
  AD-984b mounts the real component at 111/119/132/141
  BF-293 mounts the real component at 92/113/136

git grep -n "source-level\|appendThreadMessage caps\|buildTranscriptItems" -- ui/src/components/profile/__tests__/ProfileChatTab.ad1075.test.tsx ui/src/store/__tests__/threadMessages.test.ts ui/src/components/profile/__tests__/ProfileChatTab.threadTranscript.test.tsx
  AD-1075 declares source-level guards at line 1
  threadMessages proves the cap at line 46
  threadTranscript exercises buildTranscriptItems from line 130

git grep -n "StrictMode" -- ui/src/main.tsx
  no matches; production root is not StrictMode-wrapped

Baseline:
  npm exec vitest -- run <7 verified relevant files>
  7 files passed, 71 tests passed
```
