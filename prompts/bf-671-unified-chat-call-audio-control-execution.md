# BF-671 Builder Execution — Unified chat/call output-audio control

**Verdict:** APPROVED HANDOFF — R3 FINAL LIFECYCLE AND TEST-EVIDENCE REVISION EXECUTABLE AT THE PINNED BASE
**GitHub issue:** seangalliher/ProbOS#1038 — https://github.com/seangalliher/ProbOS/issues/1038
**Exact base:** `14d831cf4d2b4e56e149b8a72979bde5b6802d1d`
**Exact base commit:** `AD-1122: make sensorium budget telemetry truthful and debounced (closes #1036)`
**Scope:** Execute only `prompts/bf-671-unified-chat-call-audio-control.md`. BF-671 is an OSS frontend bug fix; no AD, backend, store field, dependency, Python gate, or Builder tracker/Git/GitHub mutation.
**License disposition:** none.
**Prompt revision:** R3 — 2026-07-15; preserves every R2 Option A rule and adds owner-bound React cleanup, arbiter-order reentrancy, and causal warning-free evidence.

## Pre-flight — exact base and R3-resume tree contract

Before implementation, test edits, staging, commit, or any other mutation:

1. Read `.github/copilot-instructions.md`, `prompts/_TEMPLATE.md`, `prompts/review-criteria.md`, and the complete main BF-671 prompt.
2. `git rev-parse HEAD` must equal exactly `14d831cf4d2b4e56e149b8a72979bde5b6802d1d`.
3. Do not fetch, pull, rebase, merge, cherry-pick, reset, checkout, stash, clean, or move to a replacement base.
4. The original two-doc-only, R1 six-path, and R2 ten-path states are historical audit evidence. On **R3 resume**, `git status --short` must show exactly these eight implementation/test paths plus the two untracked Architect documents, and nothing else:
   - `ui/src/audio/__tests__/conversationController.test.ts`
   - `ui/src/audio/conversationController.ts`
   - `ui/src/components/profile/GroupChatHeader.tsx`
   - `ui/src/components/profile/ProfileChatTab.tsx`
   - `ui/src/components/profile/__tests__/GroupChatHeader.meeting.test.tsx`
   - `ui/src/components/profile/__tests__/ProfileChatTab.ad1062.test.tsx`
   - `ui/src/components/profile/__tests__/ProfileChatTab.audioControl.test.tsx`
   - `ui/e2e/audio-output-control.spec.ts`
   - `prompts/bf-671-unified-chat-call-audio-control-execution.md`
   - `prompts/bf-671-unified-chat-call-audio-control.md`
   There must be no staged path, deletion, tracker, generated output, or path outside this exact ten-path scope.
6. Read issue #1038 read-only if needed. Do not comment, close, label, assign, or edit it.
7. If the base/tree differs from the R3-resume contract, stop for Architect re-verification. Do not repair the tree.
8. Do not stage, commit, push, edit `PROGRESS.md`, or mutate Git/GitHub during Builder execution.

Current numbering at this base is **AD-1122 / BF-669**; BF-670 is reserved by #1037 and BF-671 by #1038. Use BF-671 only. Do not create an AD or edit `DECISIONS.md`.

## Read first

- `.github/copilot-instructions.md`
- `prompts/_TEMPLATE.md`
- `prompts/review-criteria.md`
- `prompts/bf-671-unified-chat-call-audio-control.md` — **binding; read fully**
- `ui/package.json`
- `ui/vitest.config.ts`
- `ui/playwright.config.ts`
- `ui/src/components/profile/ProfileChatTab.tsx` — including exact owner-bound disposer return from both accepted arm effect branches
- `ui/src/components/profile/GroupChatHeader.tsx`
- `ui/src/audio/useMeetingVoice.ts`
- `ui/src/audio/meetingVoice.ts`
- `ui/src/audio/conversationController.ts`
- `ui/src/chat/staggerReplies.ts`
- `ui/src/store/useStore.ts`
- `ui/src/components/profile/CallMenu.tsx`
- every test/e2e file in the exact allowlist and gate commands

Do not implement from this execution summary alone. Main-prompt DD-1 through DD-10, test matrix, acceptance criteria, do-not-build list, hard stops, and verified evidence are binding.

---

## Exact allowlist

### Builder may modify production — exactly three files

- `ui/src/components/profile/ProfileChatTab.tsx`
- `ui/src/components/profile/GroupChatHeader.tsx`
- `ui/src/audio/conversationController.ts` — only DD-9's private Option A ownership generation/lifecycle, generation-bound timer, response-first parser, current-owner reply ordering, and empty-reply recovery

### Builder may add/modify tests — exactly these files

- `ui/src/components/profile/__tests__/ProfileChatTab.audioControl.test.tsx` **(NEW)** — including explicit current-arm identity, stale React cleanup lifecycle, and causal PTT `act`
- `ui/src/components/profile/__tests__/GroupChatHeader.meeting.test.tsx` — including causal store-mutation/rerender `act`
- `ui/src/components/profile/__tests__/ProfileChatTab.ad1062.test.tsx`
- `ui/src/audio/__tests__/conversationController.test.ts` — all R2 controller ownership/parity plus actual captured-A preemption, direct queued no-holder proof, and preemption-reentrant observer cases
- `ui/e2e/audio-output-control.spec.ts` **(NEW)**

### Architect documents already present — retain byte-for-byte

- `prompts/bf-671-unified-chat-call-audio-control.md`
- `prompts/bf-671-unified-chat-call-audio-control-execution.md`

### Reference/run only — never modify

- `ui/src/__tests__/ProfileChatTabVoice.test.tsx`
- `ui/src/__tests__/ProfileChatTab.bf290.test.tsx`
- `ui/src/components/profile/__tests__/ProfileChatTab.ad976.test.tsx`
- `ui/src/components/profile/__tests__/ProfileChatTab.voicewave.test.tsx`
- `ui/src/audio/__tests__/useMeetingVoice.test.tsx`
- `ui/src/components/profile/__tests__/ProfileChatTab.bf664.test.tsx`
- `ui/src/components/profile/__tests__/ProfileChatTab.threadTranscript.test.tsx`
- `ui/src/components/profile/__tests__/CallMenu.test.tsx`
- `ui/e2e/_helpers.ts`
- `ui/e2e/meeting-avatars.spec.ts`
- `ui/e2e/group-chat-open.spec.ts`
- `ui/src/audio/useMeetingVoice.ts`
- `ui/src/audio/meetingVoice.ts`
- `ui/src/chat/staggerReplies.ts`
- `ui/src/store/useStore.ts`
- `ui/src/store/types.ts`
- `ui/src/components/profile/CallMenu.tsx`
- `ui/src/components/profile/MeetingView.tsx`
- `ui/package.json`
- `ui/vitest.config.ts`
- `ui/playwright.config.ts`

### Architect-controlled closeout after review — Builder must not edit

- `PROGRESS.md`

No other source, test, e2e helper, backend, config, dependency/lockfile, generated `ui/dist`, tracker, roadmap, decision, era, archive, data/log, prompt, Git, or GitHub file is authorized. A needed edit outside this allowlist is a hard stop.

---

## Highest-risk invariants — redundant standing order

1. **One control.** `ProfileChatTab` composer speaker is the sole visible output-audio control in ordinary, active 1:1, and active group contexts.
2. **Two state owners remain.** Ordinary → persisted per-agent `ttsEnabled`; active call → session `callAudioEnabled`.
3. **No synchronization.** Never copy/reset either state on call entry/exit or agent switch.
4. **Header owns no audio.** Remove selectors, setter, JSX, comments, testid, labels, and local speaker SVG from `GroupChatHeader`.
5. **Exact UI contract.** `Mute call audio` / `Unmute call audio`; `aria-pressed=true` means audible; amber `#f0b060`, dim `#666680`; inline no-fill stroke SVG, width 1.5, round caps/joins, no emoji.
6. **Live final gate.** Greeting, 1:1 `sendText`, and 1:1 `onAgentReply` decide at the speech boundary, not from stale render/request-start closure state.
7. **Pinned live reader.** Use the main prompt's `ttsEnabledRef` plus one `isOutputAudioEnabledNow(targetAgentId, targetThreadId?)` reading the live Zustand snapshot and existing thread resolver. Both target identities belong to the output/request, not the current render. Do not invent a second store.
8. **Authoritative response owner.** Greeting, send, and controller callbacks pass their captured request/arm agent. A first-send assigned thread or A→B profile/group switch must not make A's reply inspect B's active thread, ref, or preference.
9. **Different-target fallback is read-only.** Mounted target uses `ttsEnabledRef` for an immediate click; a different target reads its existing `hxi_chat_tts_${targetAgentId}` key with live `voiceEnabled` fallback when absent. Never create/copy/delete either key or preference during the decision.
10. **Exactly one private ownership generation.** It lives only in `conversationController.ts`; no public token, second generation, owner API, store state, or completion argument.
11. **Exact invalidation.** Every accepted non-empty arm advances once, including same-agent re-arm. Real public disarm, current preemption, null-acquisition deactivation, and test reset invalidate as pinned. Empty arm and stale callbacks/disposers do not advance. Same-agent equality never proves ownership. A null acquisition retains only exact pending callback bookkeeping so a later grant can be released without wiring.
12. **Owner triple.** Transcript/VAD/acquisition/preemption/barge/timer closures capture generation, exact opts identity, and agent ID, optionally through a private immutable tuple/record. No second mutable owner registry exists. Check ownership at entry and every post-await/pre-callback/pre-state/pre-timer boundary.
13. **Stale A disappears.** A fetch/JSON/group-submit resolve or reject after B arms delivers no callback and mutates no state/timer; B remains coherent. Disarm-only and same-agent replacement follow the same rule.
14. **Lifecycle isolation.** A stale disposer cannot disarm B. A queued/null attempt's exact pending callback record lets its later grant wire nothing and release its stale lease; later owner changes supersede the record. A's silence timer cannot disarm B.
15. **Caller-bound cleanup.** Both accepted `ProfileChatTab` arms capture and return the exact disposer returned by `armConversationMode`. Never replace accepted-arm cleanup with global disarm. Global disarm remains only in mode-off and meeting-audio-off no-arm branches.
16. **Live arbiter order.** Higher-priority `acquire()` clears A and invokes A's preemption callback before granting the higher-priority holder. Controller teardown is immediate, but inactive observer notification must not let a reentrant B steal that transient gap; after higher-priority release B's queued stale grant self-releases and no lease leaks.
17. **Current reply contract.** Parse `response`, then `reply`, then `message`; set `agent_speaking` before callback; preserve synchronous muted completion and audible waiting; empty output returns to `listening`.
18. **Public API unchanged.** `markAgentReplyComplete(): void` remains argument-free. Already-started utterance completion after replacement is explicitly outside BF-671; do not tokenize or cancel speech.
19. **Meeting route stays DRY.** Meeting conversation `submitTranscript` continues through `sendTextRef.current`, but its resolve/reject is ownership-checked before controller state/timer/error mutation.
20. **Ordinary controller parity.** Non-meeting `onAgentReply` remains per-target-agent and preserves immediate-vs-speech-end completion semantics.
21. **Current mounted callback only.** After same-agent/context re-arm, tests invoke the latest current arm callback, never arm call zero. Mock owner/call identity must be explicit.
22. **Group text silence.** Non-meeting group replies remain unspoken; no per-agent group TTS.
23. **Group meeting parity.** Audio on uses the sequencer; audio off reveals every reply progressively with no voice.
24. **Active-group click ownership.** The composer click changes call state only and leaves the host's per-agent key untouched.
25. **Open-mic coupling retained.** `meetingActive && !callAudioEnabled` still disarms meeting conversation mode.
26. **Future output only.** Toggle performs no active speech cancellation/pause. The required controller ownership generation is lifecycle safety, not TTS cancellation.
27. **No new production module.** Any small component helper belongs in `ProfileChatTab.tsx`; controller ownership helpers remain private in `conversationController.ts`.
28. **Behavior tests first.** Real component + real Zustand/localStorage and real-controller tests are mandatory; mirrors/source guards are supplemental.
29. **Test ownership.** Remove mounted direct invocation of stale A's old mocked callback as ownership proof. Real controller owns deferred A→B; mounted greeting/send A→B remain required.
30. **Unmasked evidence.** A stale-preemption test must execute/observe A's captured path, not preempt B. A queued-acquisition test asserts `currentHolder() === null` before any cleanup preemption/release helper.
31. **Warning-clean tests.** Causally wrap GroupChatHeader store mutation/rerender and PTT transcript plus ensuing async updates in `act`. Inspect focused/full process stderr for zero `Warning: An update to`, zero `not wrapped in act`, zero unhandled rejection, and no unexpected stderr. Never suppress diagnostics.
32. **No e2e helper edit.** The existing helper API is sufficient; define any tiny test-local browser helper in the new spec.
33. **No Python gate.** This is UI-only.
34. **Production build mandatory.** Green Vitest does not replace `tsc -b && vite build`.
35. **No Builder closeout.** Builder stops with an uncommitted reviewed diff; Architect controls `PROGRESS.md` and commit.

---

## Ordered Builder checklist

### Step 1 — Fail-before behavior

Add the new mounted Vitest and update the two existing authorized suites before production edits. Prove at least these current failures:

- active 1:1 renders two audio controls;
- composer projects per-agent state during a call instead of call state;
- greeting and typed reply use opposite stale per-agent state;
- changing call state while a request is pending does not control final speech;
- switching from agent A to B while A's greeting/send output is pending lets B's ref/preference decide A's output;
- deferred controller A fetch/JSON/group/error work can resume through B's mutable globals;
- same-agent re-arm does not replace options because of the idempotent short-circuit;
- a stale A disposer is the global disarm function and can disarm B;
- A's silence timer can disarm B because it is bound only to global state;
- the parser ignores canonical `response` payloads;
- synchronous muted `markAgentReplyComplete()` is discarded because the real controller invokes the callback while still `submitted`;
- an empty successful controller reply strands the state in `agent_speaking`;
- header still owns `call-audio-toggle`.

Add the new Playwright spec early enough to prove the duplicate-control/scope-transition failure. Record failing node/spec names and concise reasons for the Builder report.

The new `ProfileChatTab.audioControl.test.tsx` is the consolidated BF-671 component-policy owner: mount the real component with the real Zustand store/localStorage and the proven narrow audio/network mocks. It owns composer scope, deferred greeting/send across A→B switches, **current** controller callback policy, owner-bound React cleanup lifecycle, group reveal/voice, active-group click ownership, and meeting arm/disarm behavior. Remove its direct invocation of A's captured old callback after B rerender; that cannot prove Option A because a real controller would drop A before component delivery. Existing BF-290/AD-976/voicewave/useMeetingVoice files are parity gates only and stay unchanged. `conversationController.test.ts` owns deferred controller A→B through the real module.

### Step 2 — Remove header audio ownership

In `GroupChatHeader.tsx`, remove only:

- `callAudioEnabled` selector;
- `setCallAudioEnabled` selector;
- complete AD-949 call-audio comment/button/SVG block.

Update `GroupChatHeader.meeting.test.tsx` so an active call has no header audio testid/label but retains Start/End call, chat visibility, title, participant/add controls, and no-emoji behavior.

Hard gate: no new prop/delegated callback/hidden audio markup.

### Step 3 — Context-aware composer

In `ProfileChatTab.tsx`:

- select existing `setCallAudioEnabled`;
- add/synchronize `ttsEnabledRef` and update it synchronously in the ordinary toggle path;
- derive the render projection (`meetingActive ? callAudioEnabled : ttsEnabled`);
- route clicks to the active scope only;
- add `data-testid="output-audio-toggle"`;
- apply exact label/title/pressed/color/background/glow/SVG contract;
- keep localStorage persistence scoped only to per-agent `ttsEnabled`.

Mounted cases must cover both opposite matrices for ordinary, 1:1 call, and group call plus call exit restoration.

### Step 4 — Live target-agent speech boundary

Add the single component-owned live reader pinned by main DD-3:

- captured target agent ID plus current Zustand snapshot;
- exact target/response thread when supplied; otherwise displayed resolver only for the still-mounted target, and only that target's `threadIdByAgent` mapping when it differs from the mounted agent;
- current thread `metadata.meeting_active`;
- current `callAudioEnabled`; otherwise mounted-target `ttsEnabledRef.current`, or different-target existing localStorage key with live global fallback and no write.

Wire it at:

1. post-await call greeting with captured request agent + greeting thread;
2. post-await 1:1 `sendText` response with captured request agent + authoritative response/request thread;
3. conversation-controller `onAgentReply` invocation with its arm operation's captured agent.

Preserve greeting once/yield/error behavior, reply appends, emotion forwarding, speech subscription-before-speak, matching-end completion, and muted immediate completion.

Hard gate: dependency-array churn alone is not accepted as live-state correctness.

For both accepted arm branches in the existing effect, capture `armConversationMode(...)`'s exact returned disposer and return it directly. Keep direct `disarmConversationMode()` only in the two branches that intentionally do not arm: mode off and active meeting with call audio off. Add a mounted owner-recording mock that returns a distinct disposer for each arm. Replace A with B, then invoke stale React cleanup/disposer A and prove B remains current; invoke B's disposer and prove B alone is released. No accepted branch may return a global-disarm wrapper.

When a call-state change causes a same-agent re-arm, retrieve the latest accepted arm record/callback after the transition. Do not reuse the first callback captured before the transition. A test-local typed record may include call index, agent ID, options identity, current flag, and returned disposer; do not expose production state.

### Step 4a — Option A private controller ownership

In `conversationController.ts`, implement main-prompt DD-9 exactly:

1. Add one private monotonic ownership generation and one private owner predicate over `(generation, exact opts identity, agent ID)`.
2. Every accepted non-empty arm advances once and replaces prior ownership, including same-agent re-arm. Empty-agent arm remains a no-op. Clean invalidated resources without double-advancing.
3. Return an owner-bound disposer. Keep public `disarmConversationMode()` and `markAgentReplyComplete(): void` signatures unchanged.
4. Current real disarm, current preemption, null-acquisition deactivation, and test reset invalidate as specified. Normal owned disarm releases its live lease; preemption teardown does not release the lease the arbiter already invalidated. Empty/stale disposer callbacks do not advance. During preemption, clear controller state/resources immediately but enqueue one private, one-shot, reset-safe `inactive` option/global-listener notification for delivery after the current arbiter acquire stack has granted the higher-priority holder. The job may notify invalidated A once; after each external callback it stops if reentrancy installs a newer owner.
5. Capture the owner triple in acquisition/preemption/transcript/VAD/barge/timer closures. For a null/queued acquire, retain an exact private pending-acquisition record after invalidating active ownership. A later `onAcquired(lease)` consumes/matches or detects supersession, wires nothing, and immediately releases that stale grant. Clear/supersede the pending record on any later accepted arm, public disarm, current preemption, or test reset.
6. Make the acquisition callback the sole lease-adoption point: after ownership validation, set `_lease = lease` before wiring/`listening`; never blindly assign the returned lease after synchronous `onAcquired` has run. Pass ownership into private transcript/VAD/state/timer helpers. Check at entry; before every callback/state/timer/barge mutation; after each `submitTranscript`, fetch, and JSON await; and inside every error path. Re-check after external synchronous callbacks before any further mutation, including inside owner-aware state transitions.
7. Drop stale fetch/JSON/group resolve/reject browser delivery and state. Do not cancel the already-sent server operation.
8. Parse `response ?? reply ?? message ?? ''`. For current non-empty output, enter `agent_speaking` before callback and do not overwrite post-callback state. Current empty output returns to `listening`.
9. Bind `_enterSilencePending`, refresh, and timeout to the owner. Timer expiry may disarm only that owner.
10. Do not solve the explicitly out-of-scope already-started utterance completion race. No public token, completion argument, speech cancellation, or audio-module change.

In `conversationController.test.ts`, use deferred promises and real exports to cover every required decision case:

- fetch resolve after A→B; fetch reject after A→B;
- fetch current then JSON resolve after A→B; JSON reject after A→B;
- same-agent A→B replacement;
- disarm-only while fetch/JSON is pending;
- group `submitTranscript` resolve after A→B; reject after A→B;
- stale A disposer cannot disarm B; B disposer still disarms B;
- real higher-priority arbiter holder forces null/queue; releasing it promotes the stale conversation grant, which wires nothing, releases itself, and leaves no holder; later arm/disarm/reset supersession has the same no-orphan result. Assert `currentHolder()` is null directly after promotion, before any cleanup preemption/release can mask a leak;
- current synchronous acquisition + callback-triggered disarm leaves no orphan; current preemption invalidates once; stale acquisition/preemption closures are guarded. For stale preemption, capture/observe A's actual installed callback path through the existing real arbiter, replace A with B, and prove A's closure cannot affect B. The existing shape that arms B then asks a higher-priority requester to preempt current B is not stale-A evidence and must be replaced;
- current muted synchronous completion; current audible waiting/real completion;
- current callback throw; callback re-arm-then-throw leaves B untouched;
- A timer cannot disarm B; current timer expiry and refresh still work;
- barge enabled/disabled parity plus stale VAD/barge drop;
- `response` accepted and wins over conflicting fallbacks; `reply` and `message` fallback; empty output;
- stale transcript callback, current transcript/history payload, and test-reset invalidation.
- state-callback reentrancy during `listening`/`agent_speaking` cannot continue A's transition into B.
- state-listener parity: current transitions and one real-teardown `inactive` still publish; stale A emits no post-replacement transition.
- preemption reentrancy: A's inactive option/global observer synchronously arms B while A is preempted. Under the live arbiter's clear-A → callback-A → grant-higher-priority order, the higher-priority holder must remain authoritative; B must not become `listening` against that holder. After higher-priority release, B's queued stale grant self-releases and `currentHolder()` is null. Assert no lease leak and no second generation/API.

Do not export private state/generation or add test-only production hooks. Run the existing group controller suite in the focused gate because group submit ownership is now directly affected even though that test file remains reference-only.

### Step 5 — Preserve meeting/group/mic contracts

Do not edit group sequencer/reveal production code. Through the new mounted suite and existing reference tests, prove:

- active group/audio on → voice path;
- active group/audio off → every reply via progressive reveal, zero voice;
- non-meeting group → progressive text only, zero voice;
- active-group composer click → only call state changes; host key unchanged;
- meeting audio false still disarms open mic;
- no cancellation call or new mic state/control exists.

Add a test-local async render helper in the mounted suite that calls `render` within `await act(async () => { ...; await Promise.resolve(); })`, or an equivalent Testing Library-supported mechanism. Await that helper in every case. Wrap Zustand mutations, rerenders, deferred resolve/reject, callback-driven React updates, call start/end helpers, and fake-timer advances in appropriate sync/async `act`; use `waitFor` for assertions only. In `GroupChatHeader.meeting.test.tsx`, wrap the reactive `setChatThread(...)` mutation and ensuing `rerender(...)` in `act`. In the PTT test, invoke the captured transcript callback and await the resulting `sendText`/fetch/React updates together inside `await act(async () => { ... })`; a later timer-only `act` is not causal. Current reply and speech-event callbacks that append/complete React state also stay inside `act` and use the latest owner after re-arm.

Focused and complete Vitest must have no unexpected React `act(...)` warning, unhandled rejection, or unexpected stderr. Capture and inspect direct process stderr/output for exact absence of `Warning: An update to` and `not wrapped in act`, plus zero unhandled rejection or other unexpected stderr. Do not infer this from exit code. Do not add console spies solely to police diagnostics, stub/suppress `console.error`/`console.warn`, filter output, or weaken assertions.

### Step 6 — Real-browser flow

Create `ui/e2e/audio-output-control.spec.ts`. Use existing helpers and test-local `page.evaluate` logic; do not modify `_helpers.ts`.

Behaviorally transition:

- preseeded canonical ordinary 1:1 mapped through `threadIdByAgent`, with per-agent off/call on;
- click ordinary control and observe localStorage only;
- force opposite call state, then start real 1:1 audio call;
- observe same sole composer control and no header audio;
- click call control and observe Zustand only;
- end call and observe untouched per-agent restoration;
- open a preseeded group, start its call through the real header toggle, and observe one composer control, zero header audio controls.

Route any additional exact call/greeting endpoint in the new spec itself before navigation; abort unmatched APIs. Do not invoke real audio.

### Step 7 — Exact gates

Run the focused Vitest gate, full Vitest, mandatory production build, focused Playwright, then complete Playwright. Do not run pytest/Python.

### Step 8 — Three-pass self-review and deletion/scope audit

Perform all three passes from the main prompt. Keep both revised R3 Architect docs byte-for-byte from the Builder's start. Do not stage or edit `PROGRESS.md`.

### Step 9 — Stop and hand back

Return the uncommitted diff and complete report to the Architect. Do not stage, commit, push, or mutate issue #1038.

After Architect approval, the Architect/orchestrator alone may update `PROGRESS.md` and commit exactly:

`BF-671: unify chat and call audio control (closes #1038)`

---

## Exact gates

Run from `D:\ProbOS\ui`.

Historical exact-base Architect baselines (evidence only; do not derive R3 totals):

| Gate | Baseline |
|---|---:|
| original focused compatibility (without new file/controller suite) | 8 files / 66 passed |
| full Vitest | 301 files / 2,044 passed / 1 skipped |
| production build | 2,615 modules transformed |
| complete Playwright | 6 passed |

### Focused BF-671 + parity

The focused command names **11 files**, including both real-controller suites. Do not claim a post-change test total before it runs.

```text
npm exec vitest -- run src/components/profile/__tests__/ProfileChatTab.audioControl.test.tsx src/components/profile/__tests__/GroupChatHeader.meeting.test.tsx src/__tests__/ProfileChatTabVoice.test.tsx src/__tests__/ProfileChatTab.bf290.test.tsx src/components/profile/__tests__/ProfileChatTab.ad1062.test.tsx src/components/profile/__tests__/ProfileChatTab.ad976.test.tsx src/components/profile/__tests__/ProfileChatTab.voicewave.test.tsx src/audio/__tests__/useMeetingVoice.test.tsx src/components/profile/__tests__/ProfileChatTab.bf664.test.tsx src/audio/__tests__/conversationController.test.ts src/audio/__tests__/conversationController.group.test.ts
```

### Complete Vitest

```text
npm run test
```

### Mandatory UI production build

```text
npm run build
```

### Focused Playwright

```text
npm exec playwright -- test e2e/audio-output-control.spec.ts
```

### Complete Playwright

```text
npm run test:e2e
```

Report exact **observed** file/test/pass/fail/skip counts, durations, warning/unhandled-rejection/unexpected-stderr status, and transformed-module count. For focused/full Vitest, explicitly inspect and report process stderr: zero `Warning: An update to`, zero `not wrapped in act`, zero unhandled rejection, and no other unexpected stderr. Do not present arithmetic projections as results. No Python gate. Do not use watch/UI mode or skip build.

---

## Deletion and scope audit

Run from `D:\ProbOS` without staging:

```text
git status --short
git diff --check
git diff --name-only --diff-filter=D 14d831cf4d2b4e56e149b8a72979bde5b6802d1d --
git diff --stat
git diff --numstat
git diff --no-index --check -- NUL prompts/bf-671-unified-chat-call-audio-control.md
git diff --no-index --check -- NUL prompts/bf-671-unified-chat-call-audio-control-execution.md
```

For each no-index command, exit code `1` is expected because the untracked file differs from empty; any emitted whitespace diagnostic is a failure.

Expected final status paths are exactly:

- the two untracked Architect prompt docs;
- three modified production files, including `ui/src/audio/conversationController.ts`;
- three modified existing test files, including `ui/src/audio/__tests__/conversationController.test.ts`;
- one new mounted Vitest file;
- one new Playwright spec.

There must be no deletion, staged path, `PROGRESS.md`, generated `ui/dist`, lockfile, helper, reference-test, backend, config, dependency, tracker, Git, or GitHub mutation. Do not run any staged-diff audit because staging is forbidden.

---

## Required Builder report

Return a concise table containing:

- exact base SHA and exact R3-resume ten-path status;
- fail-before Vitest/Playwright nodes and reasons;
- exact files changed/added;
- ordinary/active-1:1/active-group opposite-state matrix results;
- live greeting and `sendText` toggle-during-await results;
- deferred component A→B send and post-call greeting matrices, including opposite A/B preferences, missing-A-key live-global fallback, unchanged keys/call state, and target-A attribution;
- ordinary vs active-call `onAgentReply` results plus the captured target agent used by the callback;
- explicit current-arm callback identity after same-agent/context re-arm; no active-call assertion uses the stale first callback;
- owner-bound React cleanup lifecycle: disposer A after B replacement cannot disarm B, while disposer B releases B; both accepted branches return their exact disposer and no accepted branch returns global disarm;
- real-controller fetch resolve/reject, JSON resolve/reject, same-agent replacement, disarm-only, group-submit resolve/reject, stale disposer, synchronous/null/stale acquisition, preemption/VAD staleness, state-callback reentrancy, callback-error, timer isolation, reset invalidation, and B-coherence results;
- actual captured-A preemption evidence, direct no-holder queued-promotion assertions before cleanup, and inactive-observer reentrant B behavior pinned to the live arbiter order with final no-leak holder state;
- real-controller callback-observed/final state for synchronous muted completion, audible waiting/real completion, response-first/fallback parsing, and empty reply;
- group audible/muted/non-meeting voice/reveal results;
- active-group click ownership and unchanged host preference;
- one-control/header-removal and exact a11y/color/SVG/no-emoji results;
- focused and complete Vitest exact stderr inspection: zero `Warning: An update to`, zero `not wrapped in act`, zero unexpected React `act(...)` diagnostics, zero unhandled rejections, and no other unexpected stderr; GroupChatHeader mutation/rerender and PTT transcript/ensuing async updates causally wrapped; no diagnostic suppression added;
- focused/full Vitest, build, focused/full Playwright counts/durations/modules;
- confirmation of unchanged open-mic coupling and no active cancellation;
- three-pass self-review verdict;
- deletion/whitespace/scope audit results;
- license `none`;
- confirmation that the revised R3 prompt-doc hashes stayed byte-for-byte during resumed Builder work and no tracker/stage/commit/push/GitHub mutation occurred;
- unresolved hard stops, if any.

---

## Stop conditions

Stop and report to the Architect if:

- exact base or R3-resume ten-path tree contract fails;
- any needed path is outside the allowlist;
- correctness needs a store/backend/API/config/dependency/audio-engine/sequencer/cancellation/microphone-state change;
- live 1:1 speech cannot use the existing resolver + state/ref seam without changing a public controller/audio API;
- A→B ownership cannot use captured target agent/thread plus read-only existing-key/live-global fallback without new store/persistence state or writing another agent's key;
- the controller correction appears to require a second/public token, changed `markAgentReplyComplete` signature, new state enum, abort policy, or path outside the authorized controller pair;
- group non-meeting speech exists through another live path not in the main prompt;
- muted group full reveal needs an audio/reveal module edit;
- mounted behavior can be proved only by source scan/mirror/private hook/fake store or warning suppression;
- exact a11y/color/SVG contract conflicts with live HXI requirements;
- any gate reproduces a BF-671 regression needing unallowlisted edits, skip, weakened assertion, generated output, or Python work;
- either prompt changes, a deletion appears, or any tracker/staging/commit/push/GitHub mutation occurs.
- correct preemption reentrancy appears to require editing `speechRecognitionArbiter.ts`, exposing a private controller callback, or adding a production-for-test API.

Do not guess around a hard stop.

## Do NOT build

- Do not add a backend, store field/action, localStorage key, persistence migration, dependency, production file/hook/context, or global voice semantic.
- Do not split microphone state, rewrite PTT/wake-word, add a controller state enum, or change call start/end/camera/chat visibility beyond DD-9's exact private ownership design and DD-10's caller/preemption-order correction.
- Do not prohibit or omit the required single private controller ownership generation. Do not add a public/second generation, owner token API, completion argument, store token, `AbortController`, or generation outside `conversationController.ts`.
- Do not change `voice.ts`, `useMeetingVoice.ts`, `meetingVoice.ts`, `staggerReplies.ts`, active playback, cancellation, or pause behavior.
- Do not make group non-meeting replies speak or add per-agent group audio.
- Do not retain/relocate a header audio button.
- Do not expose private refs or add production-for-test branches.
- Do not return global `disarmConversationMode` from an accepted `ProfileChatTab` arm branch; do not keep a mock whose distinct disposer ownership cannot be asserted.
- Do not present preemption of current B as stale-A evidence or use a cleanup preemption/release helper before asserting a queued promotion left no holder.
- Do not edit reference-only tests/helpers to manufacture green gates.
- Do not edit `PROGRESS.md`, `DECISIONS.md`, roadmap, era, config, workflows, standing orders, data/logs, commercial files, Git, or GitHub.
- Do not stage, commit, or push.

## Acceptance

The Builder handoff is complete only when every main-prompt acceptance criterion is behaviorally proven, the complete Option A real-controller matrix and component target-agent matrices pass, both accepted React arm branches preserve owner-bound disposal, actual captured-A preemption/direct queued-no-holder/preemption-reentrancy evidence passes, focused and complete Vitest are warning/stderr clean by exact inspection, all five UI gates pass with exact observed counts, the exact ten-path scope/deletion/whitespace audits pass, and the uncommitted implementation is returned for Architect review.

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Re-review (2026-07-15) — execution revision R1

**Verdict:** ✅ APPROVED / EXECUTABLE — all implementation-review REQUIRED findings are represented in the executable handoff.

### Required (resolved)

1. Production/test allowlists now minimally include `conversationController.ts` and `conversationController.test.ts`.
2. Highest-risk invariants and ordered steps pin authoritative target agent + thread, different-target read-only fallback, and real-controller pre-callback state ordering.
3. Exact focused gate, expected final ten-path status, hard stops, acceptance, and Builder report include controller and deferred A→B evidence.
4. Original-start versus R1-resume preflight was explicit in the R1 audit history; the active R2 contract is the exact ten-path resume state above at base `14d831cf4d2b4e56e149b8a72979bde5b6802d1d` and issue #1038, with no Git/GitHub mutation authorized.

### Recommended (included)

1. React `act(...)` warning cleanup is mandatory without suppression.
2. Active-group click ownership is a named behavioral requirement.

### Nits

- None.

### Three-pass spec self-review

- **Pass 1 — behavior/spec:** PASS. The handoff includes target-switch, call-end greeting, real muted/audible completion, empty reply, group ownership, and unchanged parity evidence.
- **Pass 2 — verify-first/code:** PASS. Live controller branch/order and test seams were read; DD-9 is explicitly isolated from the AD-985 group branch and all public APIs.
- **Pass 3 — scope/safety/a11y/license:** PASS. Final scope is exactly ten paths including the two Architect docs; no tracker/Git/GitHub/backend/store/dependency expansion; license none.

**Prompt revision marker:** R1 is audit history and is superseded by R2 below wherever they conflict.

---

## Re-review (2026-07-15) — execution revision R2

**Verdict:** ✅ APPROVED / EXECUTABLE — the handoff now implements the pinned Option A controller ownership decision without expanding file scope.

### Required (resolved)

1. The R2 resume contract is the live exact ten-path worktree at pinned HEAD; no source/test/tracker/Git/GitHub path was added.
2. `conversationController.ts` and its existing test file are authorized for one private ownership generation, exact invalidation, null-acquire pending callback bookkeeping, owner-captured closures/checks, stale disposer/queued grant/timer isolation, response-first parsing, and unchanged public completion API.
3. The required controller tests explicitly cover fetch, JSON, same-agent, disarm-only, group submit resolve/reject, stale disposer, synchronous/null/stale acquisition, preemption/VAD, state-callback reentrancy, muted/audible, callback errors, timer isolation, barge parity, response shape, transcript/history, and reset.
4. Mounted direct stale-callback invocation is removed as ownership proof; real-controller tests own deferred A→B, while component greeting/send A→B remain.
5. Warning-free focused/full Vitest is explicit and uses async render/act mechanics without diagnostic suppression.
6. The focused command includes both controller suites. All post-change counts must be observed and reported, never predicted.

### Recommended

1. Keep deferred promise helpers and ownership assertions local to `conversationController.test.ts`.
2. Report each A→B boundary as a small state/callback/timer table rather than a prose aggregate.

### Nits

- None.

### Three-pass spec self-review

- **Pass 1 — behavior/spec:** PASS. Each Option A ownership rule maps to an ordered Builder step, named test, report field, acceptance criterion, and hard stop.
- **Pass 2 — verify-first/code:** PASS. The live same-agent short-circuit, global returned disposer, mutable-global async flow, reply parser, no-argument completion API, timer, reset, and arbiter stale-lease semantics were verified before R2 drafting.
- **Pass 3 — scope/safety/a11y/license:** PASS. Exactly the pre-existing ten paths remain in scope; no backend/store/dependency/helper/tracker/Git/GitHub mutation; no public token or speech cancellation; license none.

**R2 marker:** the binding main prompt's DD-9 and this execution revision supersede all conflicting R1 wording. Builder must not edit either Architect document.

---

## Re-review (2026-07-15) — execution revision R3

**Verdict:** ✅ APPROVED / EXECUTABLE — R3 converts every final-review finding into a binding Builder step, test, report field, and acceptance condition without changing the ten-path scope.

### Required (resolved)

1. Both accepted `ProfileChatTab` arm branches return the exact owner-bound disposer; explicit global disarm is retained only in mode-off and meeting-audio-off no-arm branches. The mounted suite records distinct owners/disposers and proves stale cleanup A cannot disarm B.
2. GroupChatHeader's reactive store mutation/rerender and PTT's transcript plus ensuing async component updates are causally wrapped in `act`. Focused/full process stderr inspection—not exit code alone—must prove zero React act warnings without suppression.
3. Stale-preemption evidence must execute/observe A's captured installed path through the existing real arbiter. Preempting B after replacement is explicitly invalid evidence.
4. Queued acquisition asserts no holder directly before cleanup. The prior helper that preempted/released a survivor is forbidden because it can mask a lease leak.
5. Mounted active-call tests identify and invoke the latest current arm callback after same-agent re-arm, with explicit test-local owner identity.
6. A real preemption-reentrancy test synchronously arms B from A's inactive observer. The live clear-A → callback-A → grant-higher-priority order is pinned: the higher-priority holder wins; B never becomes lease-incoherent; B's queued grant self-releases; final holder is null.
7. Every R2 generation/owner/async/timer gate remains binding. No arbiter edit, private callback export, second generation, or production-for-test API is authorized.

### Recommended

1. Keep the owner-recording arm mock and deferred-promise helpers test-local and typed.
2. Report the preemption reentrancy sequence as controller state + arbiter holder at each turn.

### Nits

- None.

### Three-pass spec self-review

- **Pass 1 — behavior/spec:** PASS. Caller-bound cleanup, current callback identity, actual stale-A preemption, direct queue proof, preemption reentrancy, and exact warning inspection are each represented in ordered work, tests, report, stop conditions, and acceptance.
- **Pass 2 — verify-first/code:** PASS. Live R2 worktree lines and arbiter ordering were inspected before drafting; required entities already exist or are introduced by the R3 migration. No false missing-API flag is present.
- **Pass 3 — scope/safety/a11y/license:** PASS. Exactly the existing eight implementation/test paths plus two Architect docs remain the complete status. No production/test/tracker/Git/GitHub mutation was made by this revision; no dependency/config/helper/arbiter/public-API expansion; license none.

### R3 verified evidence

```text
ProfileChatTab.tsx
   1295-1307: only the two no-arm branches call global disarm appropriately.
   1310 + 1336-1338: accepted meeting arm discards its returned disposer and returns global disarm (R3 migration).
   1394-1397: accepted 1:1 arm discards its returned disposer and returns global disarm (R3 migration).

ProfileChatTab.audioControl.test.tsx
   24/342: arm mock returns indistinguishable anonymous disposers; no current-owner lifecycle record.
   666-677: PTT transcript callback runs outside the later async act.
   762-767: helper selects armCalls[0].
   805-828: same-agent call transition re-arms, but tests invoke the stale first callback.

GroupChatHeader.meeting.test.tsx
   117-120: setChatThread and rerender are outside act.

conversationController.test.ts
   508-518: controller disposer isolation exists; mounted React cleanup proof is absent.
   540-562: cleanup preemption/release can mask a queued holder before null assertion.
   595-602: named stale-preemption test actually preempts current B.

conversationController.ts
   126: one private generation (preserve).
   281-292: preemption teardown/notification is synchronous inside the arbiter callback (R3 reentrancy seam).
   295-308: queued/null pending bookkeeping (preserve).
   310-312: owner-bound disposer (must be propagated by ProfileChatTab).

speechRecognitionArbiter.ts (read-only)
   88-91: preempt callback completes before higher-priority grant.
   157-161: active holder cleared before preempted callback.
   142-152: grant committed after callback returns.
   105-109: stale release is identity-safe.
   177-185: queued grant invokes captured onAcquired.

git rev-parse HEAD
   14d831cf4d2b4e56e149b8a72979bde5b6802d1d

git status --short before R3 document edits
   exactly eight implementation/test paths plus these two Architect docs; no stage, deletion, tracker, generated output, Git, or GitHub mutation.
```

**R3 marker:** the binding main prompt's DD-9 remains intact; DD-10 and this R3 execution revision supersede conflicting R2 wording. Builder must hash both R3 Architect docs at start/end and must not edit them.
