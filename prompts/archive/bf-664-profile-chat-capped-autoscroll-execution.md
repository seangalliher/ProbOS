# BF-664 Builder Execution — ProfileChatTab capped-transcript auto-scroll

**GitHub issue:** #1030
**Base HEAD:** `c0418a8a91ba186453e382446ce44ceed136e9f7`
**Scope:** Execute only `prompts/bf-664-profile-chat-capped-autoscroll.md`. This is a frontend-only bug fix, BF-664, with no AD.

## Pre-flight

1. Read `.github/copilot-instructions.md`.
2. Read the complete BF-664 build prompt.
3. Confirm `git rev-parse HEAD` is `c0418a8a91ba186453e382446ce44ceed136e9f7` or stop for re-verification.
4. Confirm no tracked source/test changes pre-exist. Do not overwrite unrelated work.
5. Read the exact live files listed below before editing; do not implement from this summary alone.

Current numbering was verified at prompt authoring: highest `PROGRESS.md` entries are AD-1121 and BF-663. Use BF-664 only; do not create an AD or edit trackers.

## Read first

- `.github/copilot-instructions.md`
- `prompts/bf-664-profile-chat-capped-autoscroll.md`
- `ui/package.json`
- `ui/src/chat/scrollAnchor.ts`
- `ui/src/components/profile/ProfileChatTab.tsx`
- `ui/src/components/profile/profileTranscript.ts`
- `ui/src/components/sidebar/threadApi.ts`
- `ui/src/store/useStore.ts`
- `ui/src/store/types.ts`
- `ui/src/chat/__tests__/scrollAnchor.test.ts`
- `ui/src/components/profile/__tests__/ProfileChatTab.ad984b.test.tsx`
- `ui/src/components/profile/__tests__/ProfileChatTab.threadTranscript.test.tsx`
- `ui/src/components/profile/__tests__/ProfileChatTab.ad1075.test.tsx`
- `ui/src/__tests__/ProfileChatTab.bf293.test.tsx`
- `ui/src/store/__tests__/threadMessages.test.ts`
- `ui/src/components/profile/__tests__/ProfileChatTab.ad1062.test.tsx`

## Exact files

**Modify production — exactly these two:**

- `ui/src/chat/scrollAnchor.ts`
- `ui/src/components/profile/ProfileChatTab.tsx`

**Modify tests:**

- `ui/src/chat/__tests__/scrollAnchor.test.ts`
- `ui/src/__tests__/ProfileChatTab.bf293.test.tsx`

**Add test — explicitly authorized:**

- `ui/src/components/profile/__tests__/ProfileChatTab.bf664.test.tsx`

**Reference/run only:**

- `ui/src/components/profile/__tests__/ProfileChatTab.ad984b.test.tsx`
- `ui/src/components/profile/__tests__/ProfileChatTab.threadTranscript.test.tsx`
- `ui/src/components/profile/__tests__/ProfileChatTab.ad1075.test.tsx`
- `ui/src/store/__tests__/threadMessages.test.ts`
- `ui/src/components/profile/__tests__/ProfileChatTab.ad1062.test.tsx`

Do not modify store/API/backend/config/tracker/decision files. If an existing source guard truly contradicts the implementation, stop and report the exact contradiction before broadening the test-file list.

## Highest-risk invariants — redundant standing order

1. **Tail revision, not count-only.** The effect must run when a new required message ID becomes the tail even if count remains 200 or 100.
2. **No full-array trigger.** Do not add `messages` to dependencies merely to force execution. Depend on count, current tail ID, context key inputs, and transcript visibility.
3. **Continuity must be strong.** A capped append is incremental only when the old tail is the new immediate predecessor. “Old tail appears somewhere” is too weak for replacement/load races.
4. **One pure policy.** Extend `decideScrollOnUpdate()`; do not create a global revision service/map or a second scroll-policy abstraction.
5. **Safe replacement.** Equal count + changed tail + no immediate-predecessor continuity is a bulk replacement and jumps instantly; it is never unconditional smooth follow.
6. **Initial/load behavior.** No prior tail, multi-message load, context switch, and transcript remount jump directly. A first message after empty may jump; do not misclassify it as proven append continuity.
7. **Pinned policy.** Pinned agent append follows; unpinned agent append does nothing; Captain/user append always follows. This applies to ordinary, 200-cap, and 100-cap appends.
8. **Visibility lifecycle.** While a meeting transcript is hidden, update observed count/tail/visibility but do not touch DOM or queue a frame. Hidden-to-visible is a remount: direct jump and restore pinned state.
9. **State update order.** Read old ref -> compute switch/remount/tails/continuity -> publish new observed state -> decide/scroll. Do not overwrite the old tail before continuity is computed.
10. **Post-layout measurement.** Smooth follow remains in `requestAnimationFrame()` and reads `scrollContainerRef.current.scrollHeight` inside the callback after markdown/artifact layout.
11. **Frame cleanup.** Store the scheduled frame ID and cancel it in the effect cleanup. Hide, context switch, replacement, and unmount must not leave a stale callback that can scroll another transcript.
12. **No stale closure.** The frame callback may use refs/current DOM only; the transition decision is made from the effect’s current render. Do not read an old captured container or precomputed height.
13. **BF-293 shares the revision.** Its reset effect must key from current tail identity/context and reset only for an agent tail. A capped user/Captain append must not reset.
14. **Append producers stay untouched.** Do not edit Captain send, group progressive reveal, meeting voice completion, 1:1 reply, conversation-controller reply, call greeting, error/system, ID, or role paths.
15. **No StrictMode assumption.** The production root is not StrictMode-wrapped, but cleanup must remain correct if effects are replayed in tests/development.

## Required implementation sequence

### Step 1 — Pure helper first

Extend `decideScrollOnUpdate()` and its tests before wiring the component.

The helper input must carry switch/remount, previous/current count, previous/current tail IDs, immediate-predecessor continuity, pinned state, and Captain/self role. Implement and test every transition in the main prompt’s decision table.

Hard gate: same-count changed-tail append continuity produces the same incremental policy as a normal append; same-count changed-tail without continuity produces an instant bulk jump.

### Step 2 — Component revision/visibility wiring

In `ProfileChatTab`:

- derive current tail ID/role once;
- extend the local observed scroll state with tail ID and visibility;
- compute immediate-predecessor continuity before state replacement;
- add tail ID and `showTranscript` to dependencies without adding the array;
- advance observed state while hidden;
- pass exact transition metadata to the helper;
- preserve direct and smooth DOM paths;
- add frame cleanup;
- key BF-293 from the same tail revision.

Do not edit any append/store/load function.

### Step 3 — Mounted integration, not source inspection

Create `ProfileChatTab.bf664.test.tsx` by adapting the proven real-mount mock header in `ProfileChatTab.ad984b.test.tsx`. Mount the actual component and use the real Zustand store.

The suite must behaviorally prove:

- active thread at exactly 200: pinned agent, unpinned agent, unpinned Captain;
- cold fallback at exactly 100: capped append(s), including Captain always-follow;
- queued frame reads a height changed after scheduling;
- `scrollTo` path and jsdom `scrollTop` fallback;
- initial 200-message load direct jump;
- context switch direct jump and stale-frame cancellation;
- hidden meeting append performs no scroll, show/remount jumps latest;
- same-count unrelated replacement is bulk, not capped append;
- unmount cancels a pending frame.

The test must assert real store length/tail continuity as well as DOM calls. Source-string assertions alone are not accepted.

### Step 4 — BF-293 capped regression

Use the existing PTT callback seam in `ProfileChatTab.bf293.test.tsx`:

- force cold/no-thread state;
- seed exactly 100 through the real `addAgentMessage()`;
- accumulate two empty browser recognitions;
- append one agent reply at the cap;
- prove the third press calls browser SR and not Whisper.

Keep/prove the user-tail negative behavior. Do not expose the counter.

### Step 5 — Gates and diff audit

Run focused tests after the helper, after mounted integration, and after BF-293. Then run the complete UI suite and production build. Inspect the final diff for scope and accidental generated output.

## Exact commands

Run all commands from `D:\ProbOS\ui`.

Focused BF-664 gate:

    npm exec vitest -- run src/chat/__tests__/scrollAnchor.test.ts src/components/profile/__tests__/ProfileChatTab.bf664.test.tsx src/__tests__/ProfileChatTab.bf293.test.tsx src/components/profile/__tests__/ProfileChatTab.ad1075.test.tsx

Relevant compatibility gate:

    npm exec vitest -- run src/store/__tests__/threadMessages.test.ts src/components/profile/__tests__/ProfileChatTab.ad984b.test.tsx src/components/profile/__tests__/ProfileChatTab.threadTranscript.test.tsx src/components/profile/__tests__/ProfileChatTab.ad1062.test.tsx

Complete supported Vitest suite:

    npm run test

Complete supported production build:

    npm run build

Final repository audit from `D:\ProbOS`:

    git diff --check
    git status --short
    git diff -- ui/src/chat/scrollAnchor.ts ui/src/components/profile/ProfileChatTab.tsx ui/src/chat/__tests__/scrollAnchor.test.ts ui/src/components/profile/__tests__/ProfileChatTab.bf664.test.tsx ui/src/__tests__/ProfileChatTab.bf293.test.tsx

Do not use `npm test -- --watch`, do not substitute Playwright for the required mounted Vitest suite, and do not skip `npm run build` after green tests.

## Test harness constraints

- Use unique deterministic IDs in seeded messages.
- Reset `threadIdByAgent` and `activeProfileThreadId` so cold tests cannot accidentally resolve a warm thread from shared Zustand state.
- Route `GET /api/threads/{id}/messages?limit=200` deterministically or hold/resolve it explicitly; an uncontrolled load must not race seeded messages.
- Reset `meetingChatVisible`, `callAudioEnabled`, `typingAgent`, agents, chat threads, thread messages, conversations, and local storage each test.
- Queue frames rather than executing them eagerly. Expose a test-local flush that ignores cancelled IDs.
- Change the mocked height after the frame is queued and before flush.
- Drive unpinned state through the actual transcript `scroll` handler with controlled metrics.
- Cleanup queued frames and restore global RAF/cancel/scroll mocks after every case.
- Do not use fake timers unless required by a specific path; rAF should be controlled independently.
- Avoid async load races: wait for a controlled load to publish before asserting initial jump or append behavior.

## Do Not Build

- Do not remove or raise the 100/200 caps.
- Do not change store actions, thread API, backend persistence, message loading, or render cap.
- Do not add pagination, virtualization, polling, WebSocket delivery, or a new-message affordance.
- Do not add a Zustand revision map/counter or full-array effect dependency.
- Do not change routing, message roles, IDs, progressive reveal, meeting voice, call greeting, audio, artifact, or profile architecture.
- Do not extract a test-only hook or expose a private ref.
- Do not replace post-layout rAF measurement with eager measurement.
- Do not edit `PROGRESS.md`, `DECISIONS.md`, roadmap/config/backend files, or GitHub issue metadata.
- Do not create an AD.
- Do not commit or push unless the Captain separately authorizes it after review.

## Hard stops

Stop and return to the Architect if:

- production changes expand beyond the two authorized frontend files;
- caps/store/API/routing must change;
- message IDs are absent on a selected source;
- replacement safety requires depending on the full array or global revision state;
- hidden updates require scrolling an unmounted node;
- stale rAF cleanup cannot be proved behaviorally;
- the component can be tested only through a mirror/source string/private hook;
- focused behavior passes but complete Vitest/build fails for a reproducible BF-664 change;
- or base HEAD/tracked tree differs before work begins.

## Acceptance criteria

1. The full transition matrix is implemented in the existing pure helper and covered by pure tests.
2. Real mounted tests compose the real 200/100 store bounds with actual effect triggering and DOM scroll behavior.
3. Initial load/context switch/remount jump; pinned agent follows; unpinned agent stays; Captain always follows.
4. Equal-count capped append is incremental only with immediate-predecessor continuity; unrelated same-count replacement is bulk.
5. Hidden meetings do not scroll and show/remount lands at the latest message.
6. Final post-layout `scrollHeight` is read inside rAF; stale frames are cancelled on hide/context switch/unmount.
7. BF-293 resets on a capped agent tail and not on a capped user tail.
8. Focused gate, compatibility gate, complete `npm run test`, and `npm run build` pass with exact counts reported.
9. Final diff contains only the four authorized modified paths plus the one authorized new test path and no generated output.
10. Verify all changes comply with the Engineering Principles in .github/copilot-instructions.md.

## Builder report

Return:

- verdict and concise implementation summary;
- exact files changed/added;
- focused, compatibility, complete Vitest, and build results with counts;
- confirmation that 200 active-thread and 100 cold capped cases were mounted behaviorally;
- confirmation that hidden remount, replacement safety, post-layout height, and rAF cancellation passed;
- `git status --short` and scope deviations, if any;
- unresolved questions or hard stops.

Do not commit, push, close #1030, or edit trackers during this execution unless separately instructed.
