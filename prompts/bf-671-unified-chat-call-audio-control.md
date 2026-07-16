# BF-671 — Unified chat/call output-audio control

**Verdict:** APPROVED FOR BUILDER HANDOFF — R3 FINAL LIFECYCLE AND TEST-EVIDENCE REVISION
**One-line:** Make the composer speaker the single visible output-audio control, switch every output decision by live call context and authoritative target agent, and preserve ownership from the React arm caller through the singleton controller and arbiter.

**Status:** R3 final-review requirements incorporated; ready to resume only from the pinned R3 worktree contract
**Prompt revision:** R3 — 2026-07-15; preserves every R2 Option A ownership rule and adds caller-bound disposal, arbiter-order reentrancy, and causal warning-free evidence
**Type:** Bug fix — **BF-671**; no new AD and no `DECISIONS.md` entry
**GitHub issue:** seangalliher/ProbOS#1038 — https://github.com/seangalliher/ProbOS/issues/1038
**Exact base HEAD:** `14d831cf4d2b4e56e149b8a72979bde5b6802d1d`
**Base commit:** `AD-1122: make sensorium budget telemetry truthful and debounced (closes #1036)`
**Numbering verified:** highest shipped entries at this base are **AD-1122** and **BF-669**; issue #1037 already reserves BF-670; issue #1038 reserves BF-671
**Dependencies:** AD-718, AD-917, AD-920, AD-921, AD-949, AD-952, AD-976/BF-618/BF-621, AD-985, AD-1058, AD-1062, BF-290, BF-623, BF-655
**License disposition:** none — no dependency and no absorbed external code
**Test accounting:** no projected post-change count; implement every named behavioral case below and report the exact observed file/test/pass/fail/skip counts from each gate

## Scope

Repair one frontend state-ownership defect without changing either underlying state contract:

1. The speaker button beside the composer is the **only visible output-audio control** in ordinary chat, an active 1:1 call, and an active group call.
2. Outside an active call, that button reads and writes the existing per-agent `ttsEnabled` preference persisted at `hxi_chat_tts_${agentId}`.
3. While `meetingActive` is true for the active thread — whether a 1:1 call or group call — the same button reads and writes the existing session-scoped Zustand `callAudioEnabled` state.
4. `GroupChatHeader` no longer selects, writes, renders, labels, or owns call audio. Its call start/end, participant, title, add/remove, and chat-visibility controls remain intact.
5. Every 1:1 call-open greeting and every 1:1 reply produced through `sendText` uses **live** `callAudioEnabled` while the call is active and per-agent `ttsEnabled` otherwise.
6. The 1:1 conversation-controller `onAgentReply` uses the same context-aware live rule. Meeting conversation mode continues to route through `sendText` and therefore does not duplicate speech policy.
7. Ordinary non-meeting `onAgentReply` remains per-agent. Group non-meeting replies remain timer-revealed text only; BF-671 must not make them speak.
8. Group meeting voice and muted progressive reveal continue to use the existing live `callAudioEnabled` behavior.
9. Entering or leaving a call never copies, resets, or persists one scope into the other. Leaving reveals the untouched per-agent preference.
10. Preserve the current AD-985 coupling: muting call audio disarms meeting conversation-mode open mic. Input/output separation is not part of BF-671.
11. Toggling affects future utterances/batches only. Do not cancel active server/browser speech or alter the audio engine/sequencer.
12. A deferred greeting or typed/PTT reply remains attributed to the agent that originated the request even if the mounted profile switches from agent A to agent B before completion. A controller reply is delivered only while its arm operation still owns the controller; once B replaces/disarms A, A is dropped before component delivery. Any current controller callback still uses its captured arm agent. The current mounted agent may use `ttsEnabledRef`; a different delivered target must read that target's existing localStorage key with the live global fallback and must not write or copy preference state.
13. The real singleton `ConversationController` uses one private monotonic ownership generation plus captured options identity and agent ID. Every transcript, VAD/barge-in, acquisition, preemption, async response, group submit, error recovery, callback, state mutation, and silence timer may act only while that exact ownership triple remains current.
14. A non-empty current-owner 1:1 reply enters `agent_speaking` before `onAgentReply`. A callback that synchronously calls the unchanged public `markAgentReplyComplete()` must leave the controller in `silence_pending`; an empty reply returns to `listening`.
15. The controller reply parser accepts the live API shape in precedence order `response`, then `reply`, then `message`. A stale owner resolving at fetch, JSON, group-submit, or error boundaries produces no browser callback/state/timer mutation and cannot disturb replacement owner B.
16. Every accepted `ProfileChatTab` arm branch captures and returns the owner-bound disposer returned by `armConversationMode`. It never substitutes global `disarmConversationMode` for an accepted arm. Explicit global disarm remains only in the two no-arm branches: mode off and active-meeting call audio off.
17. Preemption respects the live arbiter's callback-before-grant ordering. Controller teardown becomes inactive immediately, but inactive observers cannot reentrantly acquire the arbiter's transiently empty slot ahead of the higher-priority requester; a synchronous observer re-arm of B remains controller/lease coherent and leaks no lease.

No backend, store field, persistence migration, audio engine, meeting sequencer, microphone-state split, dependency, public controller API, abort policy, or controller state enum change is authorized. The private Option A ownership generation in DD-9 is the only controller-lifecycle expansion.

---

## Problem and verified root cause

At the exact base, two independent output-audio controls are rendered during a live 1:1 call:

- `ProfileChatTab` always renders a composer speaker bound to local `ttsEnabled` (`ProfileChatTab.tsx` around lines 1706–1740).
- Any warm thread mounts `GroupChatHeader`; when its `metadata.meeting_active` is true, that header renders a second `call-audio-toggle` bound to Zustand `callAudioEnabled` (`GroupChatHeader.tsx` around lines 267–302).

AD-1058 made 1:1 calls use the same persisted `meeting_active` thread flag as group calls, but the older AD-949 header control remained mounted for every active thread. The two controls therefore coexist and can disagree.

The disagreement is behavioral, not just visual:

- `triggerCallGreeting` speaks from captured `ttsEnabled` (`ProfileChatTab.tsx` around lines 627–660).
- The normal 1:1 `sendText` reply branch speaks from captured `ttsEnabled` (`ProfileChatTab.tsx` around lines 1166–1174).
- The conversation-controller `onAgentReply` rereads only `hxi_chat_tts_${agentId}` / global fallback (`ProfileChatTab.tsx` around lines 1268–1290).
- The group meeting branch already rereads `useStore.getState().callAudioEnabled` at reply time and either drives `speakMeetingReplies` or the timer-progressive reveal (`ProfileChatTab.tsx` around lines 1054–1081).
- `useMeetingVoice.speakReplies` independently rereads live `callAudioEnabled`, so the group sequencer itself already has the correct call-scoped gate.

The result is a split-brain UI: the header can say the call is muted while a 1:1 greeting/reply still speaks because the per-agent preference is on, or the header can say the call is audible while 1:1 speech stays silent because the per-agent preference is off.

Implementation review exposed two additional correctness defects in the first attempted implementation:

- A target-thread-only live reader can still read the mounted profile's `ttsEnabledRef`. If an agent-A request resolves after the component switches to agent B and A's call is no longer active, B's preference can decide whether A speaks. The reader therefore needs both authoritative target agent ID and target thread ID; target identity is not derivable from the current render after an async boundary.
- At the clean base, `ConversationController._onTranscript` invoked `onAgentReply` while state was still `submitted`, then unconditionally set `agent_speaking`. The muted ProfileChat callback synchronously called `markAgentReplyComplete()`, whose guard accepts only `agent_speaking`; that completion was discarded and the later transition stranded the controller. R1 corrected this ordering and empty-reply behavior; R2 retains that correction while adding ownership safety.

R2 review found that the R1 ordering repair is necessary but not sufficient. The controller is a module singleton whose `_opts`, `_agentId`, state, lease, subscriptions, and timer can be replaced while `_onTranscript` is awaiting `fetch`, `resp.json()`, or `submitTranscript`. The current async continuation then resumes through mutable globals and can deliver A's stale reply through B's callback, overwrite B's state from A's success/error path, or start an A-owned silence timer against B. The disposer returned by `armConversationMode` is also the global disarm function, so an old component cleanup can disarm a replacement owner. Agent-ID comparison cannot solve this because a same-agent re-arm with new options is a distinct owner. Option A fixes ownership privately inside the controller; capturing and invoking A's old callback is explicitly rejected because that would start detached speech whose no-argument completion can corrupt B.

R3 final review found four remaining evidence/lifecycle gaps in the R2 worktree. `ProfileChatTab` still discarded the controller's owner-bound disposer and returned global disarm from both accepted arm branches. The mounted active-call tests invoked the first arm callback after a same-agent re-arm instead of the current callback. The test named as stale-A preemption actually armed B and then caused the real arbiter to preempt B. The queued-acquisition supersession test could mask an orphan holder by preempting and releasing it before the final assertion. R3 corrects those contracts without weakening any R2 generation, ownership, async-boundary, or timer gate.

### Verified behavior boundary: group non-meeting replies are not spoken

There are exactly three direct `speakResponse(...)` calls in `ProfileChatTab` at this base:

1. 1:1 call-open greeting;
2. ordinary/1:1 `sendText` reply;
3. 1:1 conversation-controller `onAgentReply`.

The group branch calls `speakMeetingReplies` only when `_meetingLive && _callAudioOn`; otherwise it calls `revealRepliesProgressively`. Consequently, **group non-meeting text replies are currently not spoken**, even if per-agent TTS is on. Preserve that behavior. Do not expand per-agent TTS into group text chat.

---

## Pinned design decisions

### DD-1 — One context-aware composer control; two unchanged state owners

The existing composer speaker remains the sole visible output-audio control. Compute its render state from the active context:

- `meetingActive === false` → enabled state is `ttsEnabled`; click toggles `setTtsEnabled` and the existing effect persists `hxi_chat_tts_${agentId}`;
- `meetingActive === true` → enabled state is live `callAudioEnabled`; click invokes the existing `setCallAudioEnabled(!callAudioEnabled)` and writes no localStorage.

Use clear local names such as `outputAudioEnabled` and `toggleOutputAudio`; do not overload `ttsEnabled` to hold call state. Keep both backing states alive and independent.

The exact active/inactive presentation contract is:

| State | `aria-label` | `title` | `aria-pressed` | color | background | glow |
|---|---|---|---|---|---|---|
| audible/enabled | `Mute call audio` | `Mute call audio` | `true` | `#f0b060` | `rgba(240, 176, 96, 0.15)` | `drop-shadow(0 0 4px #f0b060)` |
| muted/disabled | `Unmute call audio` | `Unmute call audio` | `false` | `#666680` | `transparent` | `drop-shadow(0 0 2px rgba(102, 102, 128, 0.3))` |

Use those same labels in ordinary chat. The control describes the action and output state, not the implementation scope; do not retain `Mute agent voice` / `Enable agent voice` or `Mute this agent` wording.

The inline speaker SVG remains local to `ProfileChatTab`, with `fill="none"`, `stroke="currentColor"`, `strokeWidth="1.5"`, `strokeLinecap="round"`, and `strokeLinejoin="round"`. The icon must contain no emoji. Preserve the audible waves; use a clear mute slash/cross for muted state. Add a stable `data-testid="output-audio-toggle"` for mounted and Playwright assertions.

### DD-2 — Remove the header control completely, not just its JSX visibility

In `GroupChatHeader.tsx`, remove all call-audio ownership:

- remove the `callAudioEnabled` selector;
- remove the `setCallAudioEnabled` selector;
- remove the `call-audio-toggle` button;
- remove its complete call-audio comment block;
- remove its local speaker SVG and all audio labels.

Do not replace it with hidden markup, a prop, a disabled button, or a delegated callback. `GroupChatHeader` retains `meetingActive` only for call start/end and chat visibility.

### DD-3 — One live speech-policy decision keyed by authoritative agent and thread

Within `ProfileChatTab`, centralize the small context rule rather than scattering ternaries. Pin the implementation shape:

- a small pure module-local helper is permitted **inside `ProfileChatTab.tsx` only**, for example `isOutputAudioEnabled(meetingActive, callAudioEnabled, ttsEnabled): boolean`;
- add a `ttsEnabledRef` initialized from `ttsEnabled`, keep it synchronized, and update it in the ordinary-chat toggle before/with `setTtsEnabled` so a just-clicked preference is immediately available to async completions;
- add one component-owned `isOutputAudioEnabledNow(targetAgentId: string, targetThreadId?: string): boolean` callback. Both arguments describe the output being decided, not whichever profile happens to be mounted when an async request resolves. At invocation it must read `useStore.getState()`;
- when `targetThreadId` is supplied, use that exact authoritative thread. When it is absent and `targetAgentId` is still the mounted agent, resolve the displayed thread through the existing `resolveProfileThreadId(...)` seam. When the target differs from the mounted agent, do **not** use the mounted profile's prop or `activeProfileThreadId`; resolve only that target's existing `threadIdByAgent` mapping. This prevents agent B's active group override from capturing a late agent-A controller reply;
- read the resolved target thread's live `metadata.meeting_active`, then return live `state.callAudioEnabled` when that target thread is active;
- outside an active target call, use `ttsEnabledRef.current` only when `targetAgentId` equals the currently mounted agent, preserving immediate same-turn click behavior. For a different target, read `localStorage.getItem(`hxi_chat_tts_${targetAgentId}`)` at the decision boundary and use live `state.voiceEnabled` only when that key is absent. This is a read-only fallback: do not create, update, delete, or copy either agent's key;
- keep this callback dependent only on stable identity inputs (`agentId` / `threadId` and refs/store snapshots), not reactive call-audio/meeting values that would merely manufacture a new closure;
- do not create a production file, hook, service, Zustand field, or context provider.

Every 1:1 speech producer must make the final decision at output time:

1. **Call greeting:** capture `requestAgentId = agentId` before the request. After the async greeting response returns and passes the yield/placeholder guards, call the reader with that captured agent and greeting thread. If the call ended before resolution, that target agent's live per-agent preference governs; a later mounted agent's opposite preference must not leak in. If call audio changed while the request was in flight, the latest value wins.
2. **`sendText` 1:1 reply:** capture the request agent before the async request and call the reader with that agent plus the response/request's authoritative thread ID. A first-send thread assignment, call toggle, or A→B profile switch during the request must not select B's call or preference. Continue appending/attributing the response to the captured request agent.
3. **Conversation-controller `onAgentReply`:** for a callback delivered by the current arm owner, call the reader with the agent captured by that arm operation. When that target's 1:1 call is active, `callAudioEnabled` overrides opposite per-agent state in both directions. Outside a call, preserve the target's per-agent localStorage/live-global-fallback behavior. A stale arm never reaches this component callback.

Do not add `meetingActive`/`callAudioEnabled` merely to `sendText` dependencies and call that sufficient: a request already in flight can resolve after a toggle. Read at the actual speech boundary.

### DD-4 — Meeting conversation mode routes through `sendText`; ordinary `onAgentReply` stays per-agent

Preserve the existing AD-985 branch:

- when `meetingActive`, `armConversationMode` uses `submitTranscript` → `sendTextRef.current`;
- the group route stays governed by its existing `sendText` fan-out branch and `useMeetingVoice`;
- the 1:1 call route also passes through `sendText` and uses DD-3's live 1:1 speech gate;
- the ordinary non-meeting controller branch retains `onAgentReply` and per-agent behavior.

Do not make the meeting branch supply `onAgentReply`, call `speakResponse` itself, or create a second call-reply path.

### DD-5 — Scope transitions are selection only

Entering/leaving a call changes only which existing state the composer projects:

- do not set `callAudioEnabled` from `ttsEnabled` on entry;
- do not set `ttsEnabled` from `callAudioEnabled` on entry or exit;
- do not reset either state on start/end;
- do not write `callAudioEnabled` to localStorage;
- do not delete or rename `hxi_chat_tts_${agentId}`;
- agent switches continue to use the existing per-agent preference semantics.

Required matrix:

| Context | per-agent `ttsEnabled` | `callAudioEnabled` | composer pressed | future 1:1 speech |
|---|---:|---:|---:|---:|
| ordinary | false | true | false | silent |
| ordinary | true | false | true | speaks |
| active call | false | true | true | speaks |
| active call | true | false | false | silent |

After ending either active-call row, the ordinary row immediately reflects the unchanged per-agent value.

### DD-6 — Preserve group call voice/reveal and non-meeting silence

Do not edit `useMeetingVoice.ts`, `meetingVoice.ts`, or `staggerReplies.ts`.

The existing group send decision remains:

- active meeting + live call audio ON → voice-driven hear-then-see sequence;
- active meeting + live call audio OFF → timer-progressive reveal of every non-empty reply, with no meeting voice call;
- no meeting → timer-progressive text reveal, with no meeting voice call.

Tests must prove the muted branch reveals **all** replies and does not invoke voice. A source scan is not enough for this behavior.

### DD-7 — Preserve current call-audio/open-mic coupling

The AD-985 arm effect must continue to depend on `meetingActive` and `callAudioEnabled`, and must continue to disarm meeting conversation mode when call audio is false. This is intentionally semantically coupled for BF-671. Do not introduce `callMicEnabled`, separate input state, or a microphone UI change.

### DD-8 — Future utterances only; no cancellation

Clicking the composer output-audio toggle changes the gate for future greetings/replies/batches. It does not call `stopSpeaking`, `speechSynthesis.cancel`, `_activeAudio.pause`, `disarmConversationMode` directly, or mutate a meeting batch generation. The existing arm effect may disarm/re-arm open mic as a consequence of the preserved DD-7 state dependency.

### DD-9 — Option A: one private ownership generation for the singleton controller

Implement ownership inside `conversationController.ts`; do not expose a token and do not add a second generation, mutable module-level owner registry, `AbortController`, store field, or public parameter. Add one private monotonic integer such as `_ownershipGeneration`. A private immutable tuple/record may carry the captured triple through helpers. An owner is valid only when all three values match: captured generation equals the current private generation, captured `ArmOptions` is the current `_opts` by identity, and captured agent ID equals `_agentId`. Centralize that predicate in one private helper and use it consistently.

#### Exact generation and invalidation rules

| Event | Binding rule |
|---|---|
| Empty-agent arm | Rejected no-op; do not advance the generation and return a no-op disposer. |
| Every accepted non-empty arm | Advance exactly once before installing the new owner, including a re-arm for the **same agent**. That advance invalidates any prior owner; clean up the invalidated owner's resources without a second advance, then install the new `(generation, opts identity, agent)` triple. Remove the same-agent idempotent short-circuit. |
| Returned disposer | Capture its arm's complete ownership triple. Disarm only if that triple still owns the controller. A stale A disposer invoked after B arms is a no-op and must not advance the generation, release B's lease, clear B's subscriptions, or change B's state. |
| Public `disarmConversationMode()` | Preserve its no-argument API. If a real current owner/attempt exists, advance once **before** teardown; if already inactive/unowned, remain a no-op. |
| Current-owner preemption | The captured preemption closure first proves ownership, then advances once before teardown. The arbiter has already invalidated the old lease before invoking this callback, so controller teardown clears its local lease/subscriptions without releasing that stale lease into the arbiter. State/resource teardown is immediate; enqueue exactly one private inactive-notification job for the preempted owner and deliver it only after the live arbiter's callback-before-higher-priority-grant stack has unwound, so a synchronous inactive observer cannot steal the transiently empty slot. The job is one-shot and reset-safe; after each external callback it checks whether reentrancy installed a newer owner and stops A's remaining notifications if so. A stale preemption closure is a no-op. |
| Null acquisition | `_arbiterAcquire` returning `null` means a request was queued, not rejected. Advance once to invalidate the attempt's **current controller activation**, clear `_opts`/`_agentId`, and remain inactive, but retain a private pending-acquisition record for that exact queued request (captured old generation/opts/agent plus its invalidated marker). If its `onAcquired(lease)` later fires and the pending record still matches, consume the record, wire nothing, mutate no controller state, and immediately release that granted stale lease so the arbiter is not orphaned. Any accepted later arm, public disarm, current preemption, or test reset clears/supersedes the pending record; a callback that no longer matches is still stale but must release its supplied lease. The pending record is bookkeeping for the one queued callback, not a second generation or active owner. |
| Test reset | Advance unconditionally before clearing module state so every deferred test closure/timer becomes stale even when the visible state is already inactive. |
| Stale callback/timer/error | No advance and no controller mutation; simply drop it. A stale `onAcquired(lease)` additionally releases the supplied lease. A generation-bound timer that still owns may invoke the owned disarm path, which performs the real disarm advance above. |

An accepted same-agent arm is therefore a replacement, not idempotence: old generation A and new generation B can share an agent ID but never share ownership. Do not use agent equality as a shortcut.

#### Every asynchronous and event closure captures the owner

Capture `(generation, exact opts object, agentId)` in the acquisition and preemption callbacks, the installed transcript callback, the VAD callbacks, and the barge-in callback routed through VAD. Pass that owner explicitly into private wiring/transcript/VAD/silence helpers rather than rereading whichever `_opts` happens to be current. The acquisition callback also receives/captures its granted lease so a stale queued grant can release itself safely.

`_arbiterAcquire` may invoke `onAcquired(lease)` synchronously before returning. The **current** acquisition callback must therefore adopt `_lease = lease` only after proving ownership and **before** wiring subscriptions or entering `listening`, so an `onStateChange('listening')` callback that synchronously disarms/re-arms can release the real lease. The outer arm function must not blindly assign the returned lease after `onAcquired` returns; ownership may already have changed. The acquisition callback is the sole adoption point. A stale acquisition callback releases its supplied lease and does nothing else.

Make state transitions owner-aware (for example, a private owner-bound `_setState` wrapper). It validates before mutation, uses the captured opts for owner callbacks, and re-validates after `onStateChange` and after each external state listener before any further attach/detach/notification work. If one callback synchronously installs B, the remainder of A's transition stops; it must not emit stale A notifications or overwrite B. Teardown after an explicit generation invalidation may use a narrow internal inactive transition that cleans old resources and preserves the existing global-listener teardown behavior without treating the invalidated owner as current.

Preserve `getConversationState()` and `onConversationState(...)` APIs and current-owner notification semantics. A real disarm/preemption still publishes `inactive` exactly once through the existing option callback/global listeners. Ownership checks suppress only the stale remainder of a superseded transition; they must not suppress the replacement owner's subsequent notifications or leak listeners across reset.

At `_onTranscript` entry, reject a stale owner before trimming, callbacks, or state. Re-check ownership immediately before every callback, state mutation, timer operation, and after every boundary that can yield or replace ownership. At minimum, checks are mandatory:

1. before `canListen`, `onTranscript`, `historyProvider`, each `_setState`, `onAgentReply`, `_enterSilencePending`, `_refreshSilenceTimer`, stop-speaking/barge mutation, and error fallback;
2. immediately after `await submitTranscript(...)` on resolve and in its rejection path;
3. immediately after `await fetch(...)`, before inspecting/acting on the response;
4. immediately after `await resp.json(...)`, before parsing/delivery;
5. in every `catch` before returning to `listening`; a stale A error must not move B;
6. after any external synchronous callback if controller code would otherwise perform another mutation, because that callback may re-arm/disarm synchronously.

External work already sent to the server is not cancelled. Ownership loss only drops stale browser delivery and controller mutation. Required outcomes are exact:

- deferred A fetch resolves or rejects after B arms → no A reply callback, no A state/error recovery, B remains coherent;
- A fetch resolves while current, then A JSON resolves/rejects after B arms → same drop;
- deferred A group submit resolves or rejects after B arms → no A `silence_pending`, timer, or fallback state; B remains coherent;
- disarm without replacement while A awaits → A completion is dropped and state remains inactive;
- same-agent re-arm while A awaits → A is stale despite matching agent ID; only the new options may receive later work;
- a current-owner callback that throws still honest-degrades to `listening`; if that callback re-arms B before throwing, A's catch is stale and must leave B untouched.

#### Reply sequencing, parser, and timer ownership

For a current successful 1:1 response, parse `String(json?.response ?? json?.reply ?? json?.message ?? '')`. `response` is the canonical first choice and must win when multiple keys are present. Empty output returns the still-current owner to `listening` with no reply callback.

For non-empty current output, transition to `agent_speaking` **before** invoking `onAgentReply`, with no unconditional state write after the callback. A muted callback may synchronously call the unchanged public `markAgentReplyComplete()` and leave `silence_pending`; an audible callback remains `agent_speaking` until completion.

Keep `markAgentReplyComplete(): void` public and argument-free. It applies only to the owner that is current when called. Make `_enterSilencePending` receive/capture the current ownership triple; its timeout callback must re-check that triple and use the generation-bound disarm path, never blindly disarm the then-current owner. `_refreshSilenceTimer` must likewise operate only for its captured current owner.

One race remains explicitly outside BF-671: an utterance that **already began while A legitimately owned the controller** may emit its speech-end callback after B has armed, and the no-argument `markAgentReplyComplete()` cannot attribute that completion to A. Do not change the public API, tokenize TTS callbacks, or cancel active speech in this BF. Option A prevents stale async work from starting a new utterance after ownership loss; ownership of already-started utterance completion requires a separate design.

### DD-10 — R3 caller-bound disposal and preemption reentrancy

`armConversationMode` now returns an owner-bound disposer, but that safety is lost if its React caller discards it. In the `ProfileChatTab` arm effect, both accepted branches must retain the exact returned function and return it as the effect cleanup:

- active meeting + call audio on: `const disposeConversation = armConversationMode({...}); return disposeConversation;`
- ordinary 1:1 conversation mode: `const disposeConversation = armConversationMode(armOpts); return disposeConversation;`

Do not wrap either accepted cleanup in `() => disarmConversationMode()`. Preserve direct global `disarmConversationMode()` only where no owner is armed by that effect invocation: `mode !== 'conversation'`, and `meetingActive && !callAudioEnabled`. The returned controller disposer remains the authority even if React cleanup is delayed until after B replaces A; invoking disposer A then is a no-op by DD-9, while disposer B still tears down B.

The live arbiter order is load-bearing: `acquire()` calls `_preemptActive(...)`, `_preemptActive` clears the active lease and invokes A's `onPreempted`, and only after that callback returns does the outer `acquire()` call `_grantSync(...)` for the higher-priority requester. Therefore, notifying an inactive observer synchronously from inside A's preemption closure can let that observer arm B into the temporarily empty slot; the outer grant can then overwrite B without invoking B's preemption closure. Prevent that race inside the already-authorized controller only:

1. invalidate A's generation and clear A's controller state/resources synchronously, without releasing A's already-invalidated lease;
2. enqueue A's one `inactive` option/global-listener notification and deliver it after the current arbiter call stack has unwound, using a private one-shot microtask or equivalent scheduling. Capture A's options plus the invalidation/reset epoch needed to reject duplicate, cancelled, or test-reset work; do not require A to become the current owner again;
3. before the first deferred callback, reject only a cancelled/reset/duplicate job. After each external callback, stop A's remaining notifications if reentrancy installed a newer owner. This preserves one real preemption `inactive` notification while preventing stale continuation into B;
4. when the higher-priority holder is active, B's reentrant arm follows the existing null/queued rule: B is inactive with exact pending callback bookkeeping, its later stale grant wires nothing and releases itself, and no holder remains after the higher-priority lease is released.

The expected real-arbiter result is pinned: after preemption and the deferred inactive observer turn, `getConversationState()` is `inactive` and `currentHolder()` is the higher-priority holder; after that holder is released and B's queued callback self-releases, controller state remains `inactive` and `currentHolder()` is `null`. B must never report `listening` while the arbiter reports the higher-priority holder. This is an ownership-order correction, not a second generation or an arbiter API change.

---

## Exact file allowlist

### Production files the Builder may modify

- `ui/src/components/profile/ProfileChatTab.tsx` — context-aware composer control, live 1:1 speech gating, and returning the exact owner-bound disposer from each accepted arm effect branch only.
- `ui/src/components/profile/GroupChatHeader.tsx` — remove call-audio selectors/button/SVG only.
- `ui/src/audio/conversationController.ts` — DD-9 Option A private ownership generation, generation-bound lifecycle/timer, response-first parser, current-owner reply ordering, and empty-reply recovery only.

### Test files the Builder may add/modify

- `ui/src/components/profile/__tests__/ProfileChatTab.audioControl.test.tsx` **(NEW)** — mounted real-component/store matrix, current-owner callback behavior, owner-bound React cleanup lifecycle, and causal `act` coverage.
- `ui/src/components/profile/__tests__/GroupChatHeader.meeting.test.tsx` — replace obsolete header-audio expectations with absence/retained-controls assertions and wrap reactive store mutation/rerender in `act`.
- `ui/src/components/profile/__tests__/ProfileChatTab.ad1062.test.tsx` — update the faithful greeting mirror for the injected live output-policy decision and retain once/yield/source guards; the new mounted suite remains the production behavior proof.
- `ui/src/audio/__tests__/conversationController.test.ts` — real-controller ownership, deferred fetch/JSON/group/error, same-agent/disarm/preemption/acquisition, actual captured-A preemption evidence, arbiter-order reentrancy, direct no-holder queue assertions, stale disposer/timer, response-shape, completion, callback-error, and barge parity tests.
- `ui/e2e/audio-output-control.spec.ts` **(NEW)** — real-browser one-control/scope-switch interaction.

### Reference/run only — do not modify

- `ui/src/audio/useMeetingVoice.ts`
- `ui/src/audio/meetingVoice.ts`
- `ui/src/chat/staggerReplies.ts`
- `ui/src/store/useStore.ts`
- `ui/src/store/types.ts`
- `ui/src/components/profile/CallMenu.tsx`
- `ui/src/components/profile/MeetingView.tsx`
- `ui/src/components/profile/__tests__/ProfileChatTab.bf664.test.tsx`
- `ui/src/components/profile/__tests__/ProfileChatTab.threadTranscript.test.tsx`
- `ui/src/__tests__/ProfileChatTabVoice.test.tsx`
- `ui/src/__tests__/ProfileChatTab.bf290.test.tsx`
- `ui/src/components/profile/__tests__/ProfileChatTab.ad976.test.tsx`
- `ui/src/components/profile/__tests__/ProfileChatTab.voicewave.test.tsx`
- `ui/src/audio/__tests__/useMeetingVoice.test.tsx`
- `ui/src/components/profile/__tests__/CallMenu.test.tsx`
- `ui/e2e/_helpers.ts`
- `ui/e2e/meeting-avatars.spec.ts`
- `ui/e2e/group-chat-open.spec.ts`
- `ui/vitest.config.ts`
- `ui/playwright.config.ts`
- `ui/package.json`

### Conditional closeout only, after green gates and Architect review

- `PROGRESS.md`

The two BF-671 prompt documents are Architect-owned and must remain byte-for-byte unchanged during the build.

No other source, test, config, dependency/lockfile, generated `dist`, tracker, roadmap, decision, era, data/log, Git, or GitHub path is authorized. A needed edit outside this allowlist is a hard stop.

Expected pre-closeout changed/added implementation paths are exactly the three production files, the three modified existing test files, the new mounted Vitest file, and the new Playwright spec listed above. Together with the two untracked Architect docs, those ten paths are the complete expected Builder status. `PROGRESS.md` is not expected until the later Architect-controlled closeout.

---

## Ordered implementation

### Section 1 — Add fail-before behavioral tests

Before production edits, create/update tests that fail for the current split-brain behavior:

1. mounted composer control in ordinary chat reads/toggles persisted per-agent state;
2. mounted composer in an active 1:1 call projects/toggles `callAudioEnabled` despite opposite per-agent state;
3. active-call opposite matrices drive current conversation-reply policy; component deferred A→B matrices cover greeting/typed ownership, while real-controller replacement tests prove stale A is dropped;
4. leaving the call restores untouched per-agent state;
5. `GroupChatHeader` no longer owns a second audio button;
6. muted group meeting reveals all replies without voice;
7. the real controller invalidates stale A across deferred fetch/JSON/group/error/disposer/timer paths, keeps B coherent, permits synchronous muted completion, preserves audible waiting, parses `response` first, sends empty replies back to listening, and preserves arbiter/controller coherence under preemption reentrancy;
8. one visible output-audio control in Playwright.

Record failing node/spec names and reasons. Do not accept source-only tests as the headline evidence.

`ProfileChatTab.audioControl.test.tsx` is the consolidated BF-671 component-policy owner. It must adapt the proven real-mount mock/store pattern and behaviorally cover the composer matrix, deferred greeting, deferred typed `sendText`, **current** conversation-controller callback policy, owner-bound effect cleanup, group audible/muted/non-meeting reveal, and meeting open-mic arm/disarm. It must not invoke an old captured A `onAgentReply` after rerendering B and claim that as controller-ownership proof: Option A requires the real controller to drop that stale callback before the component ever sees it. Deferred A→B ownership belongs in `conversationController.test.ts`; preserve component A→B coverage for greeting and `sendText`. The older BF-290/AD-976/voicewave/useMeetingVoice suites stay reference-only parity gates; do not edit them merely to distribute BF-671 assertions.

### Section 2 — Remove `GroupChatHeader` audio ownership

Perform DD-2 exactly. Update `GroupChatHeader.meeting.test.tsx` to assert:

- no `call-audio-toggle` exists even when `meeting_active=true`;
- no button with `Mute call audio` or `Unmute call audio` exists in the header;
- Start/End call, chat visibility, title, participants, and add control remain present/working;
- no emoji remains.

Do not edit call/chat visibility behavior.

### Section 3 — Make the composer context-aware

In `ProfileChatTab.tsx`:

1. select the existing `setCallAudioEnabled` action;
2. derive the projected enabled state from DD-1;
3. route click to the correct setter without copying scopes;
4. add `data-testid="output-audio-toggle"`;
5. apply the exact labels, `aria-pressed`, amber/dim colors, background/glow, and SVG contract;
6. retain existing per-agent localStorage persistence only for `ttsEnabled`.

Mounted tests must use the real Zustand store and real localStorage, not a pure mirror.

### Section 4 — Centralize and wire live target-agent speech gating

Implement DD-3/4 with the smallest local helper/ref arrangement inside `ProfileChatTab.tsx`:

1. greeting captures and passes its request agent plus authoritative thread after its await and before `speakResponse`;
2. 1:1 `sendText` captures and passes its request agent plus authoritative response/request thread after its await and before `speakResponse`;
3. `onAgentReply` passes its arm operation's captured agent and uses live context at callback invocation;
4. muted output still appends text and immediately calls `markAgentReplyComplete` where required;
5. audible output still subscribes before `speakResponse` and completes on matching end;
6. meeting `submitTranscript` remains routed through `sendTextRef.current`;
7. ordinary non-meeting controller behavior stays per-target-agent for any callback delivered while its arm is current; existing-key/live-global fallback remains correct if the mounted view differs, while stale arms are dropped by the controller;
8. no reader or switch path writes/copies either agent's localStorage preference or call state.
9. both accepted arm branches capture `armConversationMode(...)`'s return value and return that exact disposer from the effect; only no-arm branches invoke global disarm.

Do not alter response persistence/routing, greeting once/yield guards, or speech lifecycle.

### Section 4a — Implement Option A controller ownership

Implement DD-9 completely in `conversationController.ts`; R1's reply ordering alone is not sufficient. Add real-module tests in `conversationController.test.ts` for every required case:

1. **Fetch boundary:** deferred A fetch resolve and reject after B arms are dropped; B's state/callback/lease remain coherent.
2. **JSON boundary:** A fetch resolves while current, then deferred JSON resolve and reject after B arms are dropped.
3. **Same-agent replacement:** deferred A is invalid after re-arming the same agent with a different options object; only B callbacks/state remain current.
4. **Disarm-only:** A fetch/JSON resolve or reject after public disarm produces no delivery and remains inactive.
5. **Group submit:** deferred A `submitTranscript` resolve and reject after B arms produce no A timer/state/error mutation.
6. **Stale disposer:** calling A's returned disposer after B arms cannot release or disarm B; B's disposer still works.
7. **Null acquisition:** use a real higher-priority arbiter holder to force `acquire()` to return `null`; the queued attempt invalidates current controller ownership but retains exact pending callback bookkeeping. Release the blocker so the real arbiter promotes the queued lease: `onAcquired` must wire nothing, release that stale grant, and leave no conversation holder. Repeat with a later arm/disarm/reset superseding the pending record before promotion. Assert `currentHolder()` is `null` directly after promotion; do not preempt/release a surviving holder as test cleanup before the assertion, because that masks a leak.
8. **Preemption/acquisition closures:** current synchronous acquisition adopts the lease before the `listening` callback, so callback-triggered disarm leaves no orphan; current preemption invalidates and tears down exactly once. Prove stale-A preemption with actual captured A evidence: capture A's installed preemption path through the existing real arbiter behavior, replace A with B, then trigger or observe A's captured callback rather than preempting B and relabeling the result. No production-for-test export/API is permitted; prefer a real-arbiter reentrant observer sequence that causes the stale A closure to run naturally.
9. **Current muted/audible:** callback observes `agent_speaking`; synchronous real completion leaves `silence_pending`; audible reply waits in `agent_speaking` until real completion.
10. **Callback errors:** current callback throw returns its owner to `listening`; callback re-arm-then-throw cannot make stale A's catch move B.
11. **Timer isolation:** A's captured silence timer cannot disarm B; a current owner's timer still disarms on expiry; refresh remains current-owner-only.
12. **Barge parity:** current-owner barge enabled still stops speech and returns to `listening`; disabled still does neither; stale VAD/barge callbacks cannot mutate B.
13. **Response shape:** `response` is accepted, wins over conflicting `reply`/`message`, each fallback remains accepted, and an empty result invokes no callback and returns the current owner to `listening`.
14. **Transcript hooks/history:** stale installed transcript callbacks do nothing; current `onTranscript` and `historyProvider` preserve ordering/payload behavior.
15. **Test reset:** deferred work and timer callbacks captured before `_resetConversationControllerForTests()` are stale afterward.
16. **State-callback reentrancy:** `onStateChange` that re-arms/disarms during `listening` or `agent_speaking` cannot let the superseded transition continue into B or orphan the acquired lease.
17. **Observer parity:** current owner state listeners still receive transitions once, and real teardown still publishes one `inactive`; stale A emits no post-replacement transition.
18. **Preemption reentrancy:** an inactive option/global observer synchronously arms B while current A is preempted by a real higher-priority holder. Pin the live arbiter order from DD-10: the higher-priority holder wins; B never becomes a coherent active controller on a lease the arbiter overwrites, B's queued grant later self-releases, and no lease remains after the higher-priority holder releases.

Use controllable deferred promises and the real exported public API. Do not expose the generation, options, private callbacks, or test-only controller hooks. Where the live arbiter mock/real seam needs queued acquisition behavior, use the already-imported arbiter public API and its test reset; do not edit `speechRecognitionArbiter.ts` or its tests.

The mounted suite's mocked controller is policy evidence only. Remove the test that directly invokes a captured old A callback after B rerender as an ownership proof; real-controller tests own deferred A→B. Keep the mounted greeting and `sendText` A→B tests because those prove component request ownership rather than controller ownership.

For active-call mounted callback policy, same-agent call-state changes re-run the arm effect and replace its options object. The test must identify and invoke the **current** arm callback after that re-arm (normally the latest accepted `armConversationMode` call), not the first callback captured before the call transition. A test-local typed arm-record helper may attach monotonically increasing mock call indices/owner labels and expose each returned disposer; it must not weaken production behavior or export a production seam.

Add a mounted lifecycle test for DD-10 using returned mock disposers, not global-disarm call counts alone: mount accepted owner A, force a same-agent/context replacement that accepts owner B, capture both disposer functions, invoke stale cleanup/disposer A after B exists, and assert B remains current/usable. Then invoke B's disposer and assert B alone is released. The mock must identify current ownership explicitly so the assertion cannot pass when both disposers merely call the same global function. Cover both accepted production branches (ordinary 1:1 and meeting) if one shared parameterized harness can do so without duplicating the component mount; at minimum, exercise the branch changed by the lifecycle regression and source/behaviorally prove the other returns its disposer.

### Section 5 — Preserve group and open-mic behavior

Use existing tests plus minimal additions to prove DD-6/7:

- muted active group call: all replies append via the timer-progressive path; voice is never invoked;
- audible active group call: sequencer path remains selected;
- non-meeting group: timer-progressive path and no voice, irrespective of `callAudioEnabled`;
- meeting audio false still disarms conversation mode;
- toggling does not invoke active-speech cancellation.
- active-group composer click toggles only `callAudioEnabled` and leaves the host's per-agent localStorage preference unchanged.

Make warning-free Vitest an explicit gate, not a best-effort note. Add a small **test-local async render helper** in `ProfileChatTab.audioControl.test.tsx` that performs `render(...)` inside `await act(async () => { ...; await Promise.resolve(); })` (or an equivalent Testing Library-supported shape) so mount-time effects settle under `act`. Wrap every causative Zustand mutation, rerender, deferred resolve/reject, callback invocation that updates React, and fake-timer advancement in synchronous/async `act` as appropriate; use `waitFor` only for observable postconditions, not as a substitute for wrapping the state-producing operation. Specifically:

- in `GroupChatHeader.meeting.test.tsx`, wrap the reactive `setChatThread(...)` mutation **and** the ensuing `rerender(...)` in `act` before asserting the End-call state;
- in the PTT mounted test, invoke the captured transcript callback and await every resulting `sendText`/fetch/React update inside `await act(async () => { ... })`; wrapping only the later timer flush is insufficient;
- invoke current controller reply callbacks and speech-event callbacks that append messages or complete state inside `act`, using the latest current-owner callback after re-arm.

Await async component helpers such as call start/end transitions. Do not mock/filter/suppress `console.error`, `console.warn`, stderr, or diagnostic text. Verify cleanliness by capturing and inspecting the direct process stderr/output for **both** the focused BF-671 command and the complete Vitest command. Exact requirement: zero `Warning: An update to`, zero `not wrapped in act`, zero unexpected React act diagnostics, zero unhandled rejection, and no other unexpected stderr. Report the inspection result explicitly; do not infer cleanliness solely from exit code, and do not add console spies, output filters, or suppression to manufacture it.

Do not edit production group voice/reveal code unless a minimal read-at-boundary correction inside the already-authorized `ProfileChatTab.tsx` is required. Any need to edit audio hooks/sequencer is a hard stop.

### Section 6 — Add deterministic Playwright integration

Add `ui/e2e/audio-output-control.spec.ts` using the existing DEV store seam and API-abort harness. It must behaviorally cover:

1. preseed an ordinary canonical 1:1 thread (not active), map it through `threadIdByAgent`, then open that agent profile; per-agent TTS off + call audio on yields exactly one `output-audio-toggle`, pressed false, label/title `Unmute call audio`;
2. click it; persisted `hxi_chat_tts_<agent>` becomes `1`, call audio remains true;
3. force call audio false, then start the 1:1 audio call through the real `CallMenu`; the same sole button becomes pressed false and no header audio control appears;
4. click it; `callAudioEnabled` becomes true while localStorage remains `1`;
5. end the call through the real control; the sole composer button restores the untouched per-agent pressed true state;
6. open a preseeded group and start its call through the real header call toggle; exactly one `output-audio-toggle` is visible on the composer and the header contains no audio toggle.

Mock greeting/chat responses as empty/system where necessary so the spec validates controls without invoking real audio. Abort unmatched APIs per the established harness. Do not assert implementation internals in place of DOM/store transitions.

### Section 7 — Run gates, three-pass review, and hand back

Run the exact gates below. Perform the self-review and deletion/scope audit. Do not edit trackers, stage, commit, push, or mutate GitHub. Hand the uncommitted implementation to the Architect for review.

The Builder report must include the deferred A→B send/greeting matrix (including missing-key live-global fallback and no writes/copies), every Option A controller matrix above, ProfileChatTab owner-bound cleanup A→B lifecycle, actual captured-A preemption evidence, direct no-holder queued-acquisition assertions, preemption-reentrant observer behavior, current-arm callback identity after same-agent re-arm, callback-observed/final states for muted and audible replies, response-first parsing, empty-reply recovery, exact focused/full stderr inspection, active-group click ownership, the complete ten-path status, and exact observed gate results.

### Section 8 — Architect-controlled closeout after review

Only after the Architect approves the implementation and all gates:

1. prepend one concise BF-671 closeout to `PROGRESS.md` with #1038, exact focused/full/build/Playwright results, no new AD, and BF-671 as the BF ceiling;
2. include the two unchanged prompt docs and allowlisted implementation/test files;
3. stage explicit allowlisted paths only;
4. commit exactly:

`BF-671: unify chat and call audio control (closes #1038)`

The Builder is **not** authorized to perform Section 8. No push or GitHub mutation is authorized by this handoff.

---

## Required behavioral tests

### A. Composer control and scope matrix — mounted real component/store

1. Ordinary chat, per-agent false/call true → one composer toggle, pressed false, exact unmute label/title, dim `#666680`.
2. Ordinary chat, per-agent true/call false → pressed true, exact mute label/title, amber `#f0b060`.
3. Ordinary click false→true updates local React state and `hxi_chat_tts_${agentId}` to `1`; `callAudioEnabled` is unchanged.
4. Ordinary click true→false persists `0`; call state is unchanged.
5. Active 1:1, per-agent false/call true → pressed true; click toggles only call state.
6. Active 1:1, per-agent true/call false → pressed false; click toggles only call state.
7. Active group, same opposite matrices → composer projects call state exactly like 1:1.
8. Enter call does not copy/reset either state; end call immediately restores the untouched per-agent pressed state.
9. Exact `aria-pressed` Boolean semantics, labels/titles, colors, background/glow, SVG `strokeWidth=1.5`, round caps/joins, and no emoji.

### B. Duplicate control removal

10. Active 1:1 renders exactly one `output-audio-toggle` and zero `call-audio-toggle`.
11. Active group renders exactly one `output-audio-toggle` and zero header audio buttons/labels.
12. Ordinary chat renders exactly one `output-audio-toggle`.
13. `GroupChatHeader` no longer selects or invokes `setCallAudioEnabled`, but call toggle/chat visibility/title/participants/add controls remain.

### C. 1:1 call greeting — both opposite matrices and live toggles

14. Active 1:1, per-agent false/call true → accepted greeting is appended and spoken.
15. Active 1:1, per-agent true/call false → accepted greeting is appended but not spoken.
16. Toggle call audio while greeting fetch/json is pending; the state at response/speech time wins.
17. End call while greeting is pending; after resolution, ordinary per-agent state governs.
18. Existing once-per-call, reopen, yield-if-Captain-speaks, empty/placeholder/system/error honest-degrade behavior remains.

A faithful greeting mirror may supplement the heavy mounted suite, but at least one mounted/store or injected callback test must prove the real production live-state seam. Source assertions alone are insufficient.

### D. `sendText` typed/PTT/conversation replies

19. Active 1:1 typed send, per-agent false/call true → future reply speaks.
20. Active 1:1 typed send, per-agent true/call false → reply appends but does not speak.
21. Toggle call audio while the chat request is pending; response-time live state wins.
22. PTT continues to invoke the same `sendText` path; no separate PTT audio rule is introduced.
23. Active 1:1 conversation-controller `onAgentReply`, per-agent false/call true → speaks and completes on matching speech end.
24. Active 1:1 conversation-controller `onAgentReply`, per-agent true/call false → no speech subscription/call and completion is immediate.
25. Ordinary non-meeting `onAgentReply` remains per-agent in both enabled/disabled cases.
26. Meeting conversation mode continues `submitTranscript` → `sendTextRef.current`; it does not install the ordinary `onAgentReply` speech path.
27. After a same-agent/context re-arm, mounted active-call policy invokes the latest current-owner callback, not the stale first callback. Mock ownership labels/call indices make that identity explicit.
28. React cleanup/disposer A captured from an accepted arm cannot disarm accepted replacement B; B's own disposer still releases B. Both production accepted-arm branches return the exact disposer; no accepted branch returns global disarm.

### D2. Deferred target-agent ownership and controller completion

29. Deferred ordinary agent-A `sendText`, then rerender/switch to B: A key `1`, B key `0` → A reply speaks; both keys and call state remain unchanged, and the reply remains attributed/appended to A.
30. Same A→B flow with A key `0`, B key `1` → A reply appends silently; B's `ttsEnabledRef` cannot decide A's output.
31. When A's key is absent after the switch, the reader uses the **live** global `voiceEnabled` fallback without creating A's key; test both enabled and disabled outcomes or an equivalent two-row parameterized matrix.
32. Deferred agent-A call greeting, then end A's call and switch to B before resolution: A's per-agent state controls the late greeting in both opposite A/B rows. The ended call does not continue using `callAudioEnabled`.
33. Deferred A fetch resolve/reject after B arms is dropped; B's callbacks, lease, state, and timer remain coherent.
34. Deferred A JSON resolve/reject after B arms is dropped, including when fetch completed while A still owned.
35. Same-agent re-arm invalidates A; a public disarm invalidates A without replacement.
36. Deferred A group-submit resolve/reject after B arms produces no A state/timer/error mutation.
37. A stale disposer cannot disarm B; stale queued acquisition/preemption/VAD closures cannot wire or mutate B; a stale granted lease is released.
38. Stale-preemption proof captures A's actual installed callback/path and demonstrates that A—not current B—is the preempted closure under test. A test that simply preempts B is invalid evidence.
39. Every queued-acquisition promotion case asserts `currentHolder() === null` directly before any cleanup/preemption helper can alter the result.
40. If an inactive observer synchronously arms B during A preemption, the higher-priority holder wins per the live callback-before-grant order; B never enters a lease-incoherent listening state, B's queued grant self-releases, and final holder is null after release.
41. The real controller sets `agent_speaking` before current `onAgentReply`; synchronous real completion leaves `silence_pending`, while audible output waits until real completion.
42. Current callback throw honest-degrades; re-arm-then-throw leaves replacement B untouched.
43. A generation-bound A silence timer cannot disarm B; the current timer and refresh behavior still work.
44. Barge enabled/disabled parity remains for the current owner and stale barge/VAD input is dropped.
45. `response` is parsed first and wins; `reply` and `message` remain fallbacks; empty output invokes no callback and returns current ownership to `listening`.
46. Reset invalidates deferred closures/timers. Existing non-OK/network, arbiter, teardown/preemption, transcript/history, and AD-985 group-submit behavior remains green.

### E. Group voice/reveal and microphone regression

47. Active group + call audio true uses meeting voice and reveals in sequencer order.
48. Active group + call audio false invokes no meeting voice and progressively appends every non-empty reply.
49. Non-meeting group invokes no meeting voice and progressively appends every non-empty reply even if call audio is true.
50. Active-group composer click mutates only call state and leaves the host per-agent key byte-for-byte unchanged.
51. Audio false during a meeting still disarms conversation mode; audio true permits existing arm behavior.
52. No new mic state/control, no input/output split, and no active-speech cancellation call appears.
53. Focused and complete Vitest stderr contain no React `act(...)` warning (`Warning: An update to` / `not wrapped in act`), unhandled rejection, or other unexpected stderr; fix the GroupChatHeader mutation/rerender and PTT transcript/update causes with `act`, with no suppression.

### F. Real-browser integration

54. Playwright proves one visible control across ordinary 1:1 → active 1:1 → ended 1:1 → active group transitions.
55. Playwright proves independent state restoration and zero header audio control.
56. Existing Playwright coverage plus the new spec remains green; report the exact observed count without predicting it here.

---

## Exact test gates and count reporting

Run from `D:\ProbOS\ui`.

Historical exact-base baselines are evidence only: focused compatibility was 8 files / 66 passed, complete Vitest was 301 files / 2,044 passed / 1 skipped, the production build transformed 2,615 modules, and complete Playwright was 6 passed. **Do not derive or claim any R3 post-change total from those numbers.** After implementation, report only the exact observed files/tests/pass/fail/skip counts, durations, stderr/warning status, and transformed-module count emitted by each command.

### Focused BF-671 + parity

```text
npm exec vitest -- run src/components/profile/__tests__/ProfileChatTab.audioControl.test.tsx src/components/profile/__tests__/GroupChatHeader.meeting.test.tsx src/__tests__/ProfileChatTabVoice.test.tsx src/__tests__/ProfileChatTab.bf290.test.tsx src/components/profile/__tests__/ProfileChatTab.ad1062.test.tsx src/components/profile/__tests__/ProfileChatTab.ad976.test.tsx src/components/profile/__tests__/ProfileChatTab.voicewave.test.tsx src/audio/__tests__/useMeetingVoice.test.tsx src/components/profile/__tests__/ProfileChatTab.bf664.test.tsx src/audio/__tests__/conversationController.test.ts src/audio/__tests__/conversationController.group.test.ts
```

### Complete Vitest

```text
npm run test
```

### Mandatory production TypeScript/Vite build

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

Do not run a Python/pytest gate. Do not substitute a source scan for mounted Vitest or Playwright behavior. Do not skip the production build after green tests.

---

## Acceptance criteria

1. The composer speaker is the sole visible output-audio control in ordinary chat, active 1:1 calls, and active group calls.
2. Ordinary chat reads/writes only persisted per-agent `ttsEnabled`; active calls read/write only session-scoped `callAudioEnabled`.
3. Active call state overrides opposite per-agent state in both directions for UI, greetings, typed/PTT replies, and conversation-controller replies.
4. Entering/leaving a call copies/resets neither scope; leaving restores the untouched per-agent preference.
5. `GroupChatHeader` contains no call-audio selector, setter, button, label, testid, or speaker SVG; all non-audio header behavior remains.
6. Call greeting and 1:1 `sendText` speech gates read live state after async response boundaries; a toggle during an in-flight request cannot leave a stale closure decision.
7. Every delivered deferred 1:1 output decision is keyed by its captured request/current-arm agent and authoritative thread. A mounted A→B switch cannot substitute B's ref, thread override, or preference for A; different-target fallback reads only A's existing key plus live global fallback and performs no write/copy. If B has replaced A's controller ownership, A is not delivered.
8. Active 1:1 current-owner `onAgentReply` reads live call state; ordinary current-owner `onAgentReply` remains per-target-agent and preserves immediate-vs-speech-end completion semantics.
9. The real controller has exactly one private ownership generation. Every accepted non-empty arm, including same-agent re-arm, creates a distinct owner; real disarm, current preemption, null-acquisition deactivation, and test reset invalidate as specified; empty arm and stale callbacks/disposers do not advance it. Null acquisition retains only exact pending callback bookkeeping so a later stale grant can be released.
10. Transcript/VAD/acquisition/preemption/timer closures capture generation, exact opts identity, and agent ID. Entry and every post-await/pre-callback/pre-state/pre-timer boundary validate ownership; owner-aware state callbacks revalidate on reentrancy; stale fetch/JSON/group/error work is dropped and B remains coherent.
11. Both accepted `ProfileChatTab` arm branches return the exact owner-bound disposer from `armConversationMode`; only no-arm branches call global disarm. Stale React cleanup/disposer A after replacement B is a no-op, and B's disposer still releases B.
12. A stale disposer cannot disarm the current owner. A stale queued acquisition wires nothing and releases any stale granted lease. Current synchronous acquisition adopts the lease before wiring/state callbacks and leaves no orphan if those callbacks disarm/re-arm. A generation-bound silence timer cannot disarm a replacement owner.
13. Stale-preemption evidence proves the actual captured A closure/path; it does not preempt B and relabel that result. Queued-acquisition tests assert no holder directly before cleanup. Under an inactive-observer re-arm during A preemption, the live arbiter's callback-before-grant order is preserved: the higher-priority holder wins, B remains controller/lease coherent, and no lease leaks after release.
14. The real controller parses `response` first, then `reply`, then `message`; enters `agent_speaking` before a current non-empty reply callback; preserves synchronous `silence_pending`; retains audible `agent_speaking` until real completion; and returns empty replies to `listening`.
15. `markAgentReplyComplete(): void` remains unchanged. The already-started-utterance completion race is explicitly outside BF-671; no public completion token, TTS cancellation, or speech-end API redesign is introduced.
16. Meeting conversation mode still routes through `sendTextRef.current`; no duplicate speech path exists.
17. Group audible hear-then-see sequencing remains; muted group calls reveal every reply progressively without invoking meeting voice; group non-meeting replies remain unspoken; active-group click owns only call state.
18. Current call-audio→meeting-open-mic coupling remains; no microphone split/control/state is added.
19. Toggling affects future utterances only; no active playback cancellation or sequencer/audio-engine change is added.
20. Exact label/title values are `Mute call audio` / `Unmute call audio`; `aria-pressed=true` means output audible; active/dim colors are exactly `#f0b060` / `#666680`.
21. The speaker icon is inline stroke SVG with `strokeWidth=1.5`, round caps/joins, no fill, and no emoji.
22. Focused mounted tests exercise real component/store behavior. Deferred controller A→B ownership is proven only through the real controller; active-call mounted policy invokes the latest current-owner callback after same-agent re-arm, not the stale first callback.
23. Focused and complete Vitest are warning-free by exact process stderr inspection: no `Warning: An update to`, no `not wrapped in act`, no unexpected React act diagnostic, no unhandled rejection, and no other unexpected stderr. GroupChatHeader mutation/rerender and PTT transcript/async updates are causally wrapped in `act`; no diagnostic suppression is added.
24. Focused Vitest (including both controller suites), complete Vitest, mandatory production build, focused Playwright, and complete Playwright pass with exact observed results reported; no post-change count is preclaimed.
25. Only allowlisted files change; no deletion, broad reformat, generated output, store/backend/config/dependency/tracker/Git/GitHub mutation occurs during Builder execution.
26. After Architect approval only, `PROGRESS.md` records BF-671/#1038 and the exact commit is `BF-671: unify chat and call audio control (closes #1038)`.
27. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Do NOT build

- No backend/Python/API/router change.
- No new Zustand field/action, store migration, localStorage key, persistence layer, or copy/reset synchronization between `ttsEnabled` and `callAudioEnabled`.
- No global `voiceEnabled` semantic change.
- No `callMicEnabled`, input/output split, microphone UI, PTT rewrite, wake-word change, public controller API/state enum, or controller redesign beyond DD-9's exact private Option A ownership generation.
- No prohibition on the required private controller ownership generation. Conversely, no public generation token, second generation counter, owner ID API, completion argument, store token, `AbortController`, TTS queue, or generation outside `conversationController.ts`.
- No active playback cancellation, `stopSpeaking` policy change, `speechSynthesis.cancel`, audio pause, `voice.ts`, `meetingVoice.ts`, `useMeetingVoice.ts`, or sequencer change.
- No group non-meeting TTS, per-agent group filtering, group audio preference, or group fan-out change.
- No call start/end, camera, transcript visibility, participant, title, add/remove, routing, message persistence, greeting prompt, or response parsing change beyond DD-9's exact controller `response`→`reply`→`message` precedence.
- No new production helper file/hook/context/provider. Small pure/local helpers belong in `ProfileChatTab.tsx` only.
- No emoji, icon library, npm dependency, lockfile, CSS framework, or broad visual redesign.
- No source-only headline regression suite and no faithful mirror presented as proof of component/store behavior.
- No test-only production branch, exposed private ref, or source export solely for tests.
- No AD, `DECISIONS.md`, roadmap, era, config, workflow, standing order, data/log, commercial, pricing, or competitive material.
- No Builder tracker edit, staging, commit, push, issue close/comment/label/edit, or other Git/GitHub mutation before Architect review.

---

## Hard stops

Stop and return to the Architect if:

1. HEAD differs from `14d831cf4d2b4e56e149b8a72979bde5b6802d1d` or R3 resume status differs from the exact ten paths listed in the execution document.
2. A required behavior needs a production/test path outside the allowlist.
3. Correctness appears to require a new store field/action, localStorage key, backend/API, dependency, audio-engine/sequencer, cancellation, or microphone-state change.
4. 1:1 greeting or `sendText` cannot read current call/per-agent state at the speech boundary without changing public audio/controller APIs.
5. Authoritative A→B output ownership cannot be implemented with the existing target agent/thread, refs, localStorage, and store snapshot without adding persistence/store state or writing another agent's key.
6. DD-9 appears to require a second/public token, changed `markAgentReplyComplete` signature, new state enum, abort policy, or path outside the two authorized controller files; do not weaken Option A ownership checks.
7. Group non-meeting replies are found to speak through another live path not documented here; do not silently expand or suppress behavior — report the exact path.
8. Muted group replies cannot all reveal without editing `useMeetingVoice`, `meetingVoice`, or `staggerReplies`.
9. The mounted suite can pass only through a source scan, faithful mirror, private production hook, replacing the real Zustand store, or suppressing React warnings.
10. Exact accessibility/color/SVG semantics conflict with an existing shared HXI contract.
11. A focused/full/build/Playwright failure reproduces and needs unallowlisted edits, weakened assertions, skips, generated-file changes, or a Python gate.
12. Either Architect document changes, a deletion appears, or any tracker/Git/GitHub mutation occurs before review.
13. Correct preemption reentrancy appears to require changing `speechRecognitionArbiter.ts`, exposing a private controller callback, or adding a production-for-test API. Stop with the observed live order; do not weaken the real-arbiter requirement.

Do not guess around a hard stop.

---

## Three-pass Builder self-review

### Pass 1 — Behavior/spec

- Map every DD, required test, and acceptance criterion to code/test evidence.
- Exercise all four ordinary/call opposite-state matrix rows.
- Exercise component deferred A→B matrices for greeting/send A-key/B-key opposites and missing-A-key live global fallback. Do not directly invoke a stale old controller callback in the mounted suite.
- Verify greeting, typed send, PTT-through-send, ordinary `onAgentReply`, active-call `onAgentReply`, group audible, group muted, and group non-meeting paths.
- Verify enter/exit and agent-switch restoration with no copying/reset.
- Verify the full real-controller Option A matrix: fetch, JSON, same-agent, disarm-only, group-submit resolve/reject, stale disposer, synchronous/stale acquisition, actual captured-A preemption evidence, direct no-holder queue assertions, preemption-observer reentrancy, VAD staleness, state-callback reentrancy, current muted/audible, callback errors, timer isolation, barge parity, response precedence/fallback, and reset invalidation.
- Verify both accepted ProfileChatTab arms return their exact disposer and stale React cleanup A cannot disarm replacement B. Verify active-call policy uses the latest current-arm callback after same-agent re-arm.

### Pass 2 — Verify-first/code

- Re-grep every relevant `speakResponse`, `speakMeetingReplies`, `callAudioEnabled`, `ttsEnabled`, `setCallAudioEnabled`, `meetingActive`, `_ownershipGeneration`, ownership predicate, `_setState`, `onAgentReply`, `markAgentReplyComplete`, `_enterSilencePending`, acquisition, preemption, VAD, and timer use across all three allowlisted production files.
- Inspect every async boundary and prove the final 1:1 gate reads current state.
- Prove every greeting/send/controller call passes the captured target agent; prove a different target never reads the mounted agent's ref/prop/group override and never writes localStorage.
- Inspect every real-controller await/callback/timer boundary and prove stale ownership cannot deliver, mutate, release, wire, refresh, or disarm. Prove response-first parsing and no post-callback `agent_speaking` overwrite.
- Confirm meeting `submitTranscript` still routes through `sendTextRef.current` and ordinary `onAgentReply` remains the non-meeting branch.
- Confirm accepted arm branches retain/return the exact disposer; grep global `disarmConversationMode()` and prove each remaining direct call is a no-arm branch.
- Confirm `GroupChatHeader` has no audio ownership and no duplicate button/label/testid/SVG.
- Confirm no direct group non-meeting `speakResponse` was introduced.

### Pass 3 — Scope/safety/a11y/license

- Verify exact allowlist, no deletion/broad reformat/generated output, and prompt docs unchanged.
- Verify no store/backend/config/dependency/audio-engine/mic/tracker/Git/GitHub drift.
- Verify labels, title, `aria-pressed`, colors, SVG attributes, focusability, and no emoji.
- Verify focused and complete Vitest stderr have zero `Warning: An update to`, zero `not wrapped in act`, zero unexpected React act diagnostics, zero unhandled rejections, and no other unexpected stderr without console suppression; inspect the GroupChatHeader mutation/rerender and PTT transcript/async `act` boundaries; verify active-group clicks mutate only call state.
- Verify compliance with `.github/copilot-instructions.md` and license disposition `none`.

---

## Historical R0/R1 Verified Against Codebase (2026-07-15, clean HEAD `14d831cf4d2b4e56e149b8a72979bde5b6802d1d`)

This block records the clean-base investigation and R1 audit only. It does not describe the later worktree; the active R3 evidence is in the final re-review.

```text
git rev-parse HEAD
  14d831cf4d2b4e56e149b8a72979bde5b6802d1d

git status --short
  <empty before Architect documents>

PROGRESS.md:3
  AD-1122 is the new top-level; BF ceiling remains BF-669.

ProfileChatTab.tsx
  385: const callAudioEnabled = useStore((s) => s.callAudioEnabled);
  389: const [ttsEnabled, setTtsEnabled] = useState<boolean>(() => {
  394: localStorage.setItem(ttsKey, ttsEnabled ? '1' : '0');
  584: const meetingActive = useStore((s) => ...metadata.meeting_active...);
  627: const triggerCallGreeting = useCallback(async (tid: string) => {
  654: if (ttsEnabled) {
  655: speakResponse(... greeting ...);
  900: const sendText = useCallback(async (textArg: string) => {
  1054-1057: _meetingLive and live useStore.getState().callAudioEnabled
  1062: speakMeetingReplies(...) for meeting+audio
  1075: revealRepliesProgressively(...) otherwise
  1166: if (ttsEnabled && reply ...)
  1174: speakResponse(... 1:1 send reply ...)
  1185: sendTextRef.current = sendText;
  1206-1207: meetingActive branch disarms when !callAudioEnabled
  1226-1232: meeting submitTranscript routes through sendTextRef.current
  1268: onAgentReply: (replyText: string) => {
  1276-1278: currentTtsEnabled reads only per-agent localStorage/global fallback
  1290: speakResponse(... conversation reply ...)
  1706: Per-agent speaker toggle comment
  1711: aria-label uses Mute agent voice / Enable agent voice
  1727: composer speaker SVG uses strokeWidth="2"

GroupChatHeader.tsx
  29: const callAudioEnabled = useStore((s) => s.callAudioEnabled);
  30: const setCallAudioEnabled = useStore((s) => s.setCallAudioEnabled);
  267-302: active-meeting call-audio-toggle button + local speaker SVG
  280: onClick={() => setCallAudioEnabled(!callAudioEnabled)}

conversationController.ts
  333-341: successful 1:1 response extracts reply; current order invokes onAgentReply while submitted, then unconditionally sets agent_speaking.
  351-353: markAgentReplyComplete returns unless current state is agent_speaking, then enters silence_pending.
  307-321: AD-985 submitTranscript branch is separate and must remain unchanged.

conversationController.test.ts (historical exact-base evidence; not an R2 result)
  137-145: existing audible reply test proves eventual agent_speaking only; it does not assert callback-observed state or synchronous completion.
  186-201: existing completion test calls markAgentReplyComplete only after the response has fully settled.
  Existing exact-base suite: 13 passed in focused review run.

useStore.ts
  469: callAudioEnabled: boolean;
  623: setCallAudioEnabled: (v: boolean) => void;
  981: callAudioEnabled: true;
  1713: setCallAudioEnabled implementation (session-only, no localStorage)

Direct group/1:1 speech audit
  ProfileChatTab.tsx direct speakResponse calls: lines 655, 1174, 1290 only
  Group speech goes through speakMeetingReplies at line 1062 only under meeting+audio;
  non-meeting/muted group falls through revealRepliesProgressively at line 1075.

Existing test seams
  GroupChatHeader.meeting.test.tsx:163/173/185 pins the obsolete header audio toggle.
  ProfileChatTab.bf290.test.tsx:170/213 behaviorally exercises onAgentReply enabled/disabled.
  ProfileChatTab.ad1062.test.tsx:19-149 carries the greeting mirror; 155+ pins production wiring.
  ProfileChatTab.ad976.test.tsx:107 proves muted meeting progressive reveal; 130 proves text-chat progressive reveal.
  ProfileChatTab.voicewave.test.tsx:43-68 pins meeting audio/open-mic and dependency wiring.
  useMeetingVoice.test.tsx behaviorally proves meeting active/audio enabled and disabled gates.
  ProfileChatTab.bf664.test.tsx is a proven real ProfileChatTab + real Zustand mount harness.
  e2e/_helpers.ts provides API aborts, DEV store seeding, ordinary/group open helpers.
  meeting-avatars.spec.ts starts a real group meeting through the header.

Gate scripts
  ui/package.json:8  "build": "tsc -b && vite build"
  ui/package.json:10 "test": "vitest run"
  ui/package.json:12 "test:e2e": "playwright test"

Architect historical baselines at exact HEAD (do not project R3 counts)
  Original focused compatibility: 8 files passed, 66 tests passed.
  Existing controller suite later entered R1 scope; do not use historical arithmetic to predict an R2 result.
  Full Vitest: 301 files passed, 2,044 passed / 1 skipped.
  Production build: 2,615 modules transformed.
  Playwright: 6 passed.
```

## Pre-dispatch checklist

**Numbering and boundary**
- [x] Exact base, issue #1038, AD-1122 ceiling, BF-669 ceiling, BF-670 reservation, and BF-671 reservation verified.
- [x] Correct repository: OSS HXI behavior only; no commercial material.

**Verify-first**
- [x] Every asserted source/test/store/script path exists at exact HEAD.
- [x] All three direct `speakResponse` sites, the group sequencer/reveal branch, header duplicate control, and current store contracts were read.
- [x] Group non-meeting no-speech behavior was verified from the complete direct-speech call inventory.

**Completeness**
- [x] Every implementation item maps to behavioral tests and acceptance criteria.
- [x] Opposite-state matrices, async live-state changes, restoration, duplicate removal, group muted reveal, open-mic coupling, a11y, build, and Playwright are explicit.
- [x] No unsettled design question remains for the Builder.

**R2 Option A revision**
- [x] Target-agent identity remains explicit at every component async output boundary; A→B fallback and no-write/no-copy semantics are pinned.
- [x] The controller has one exact private ownership-generation design, including same-agent replacement, disarm/preemption/null-acquisition/reset invalidation, stale disposer, post-await checks, and generation-bound timers.
- [x] Production/test allowlists, focused gate, hard stops, acceptance, and Builder report include the complete real-controller matrix and both controller suites.
- [x] Mounted stale-callback pseudo-proof is removed; greeting/send A→B remain component-owned and real-controller deferred A→B owns lifecycle proof.
- [x] Warning-free focused/full Vitest and async render/act mechanics are mandatory without diagnostic suppression.

**Discipline**
- [x] Exact allowlist and hard stops are narrow.
- [x] Do-not-build names microphone split, cancellation, group non-meeting TTS, store/backend/dependency/tracker/Git/GitHub scope.
- [x] Compliance sentence is present.

---

## Re-review (2026-07-15) — implementation-review revision R1

**Verdict:** ✅ APPROVED FOR BUILDER — all REQUIRED findings incorporated; no unresolved prompt blocker.

### Required (resolved)

1. **Controller completion ordering:** DD-9 now requires `agent_speaking` before callback, forbids post-callback overwrite, returns empty reply to `listening`, and preserves all other controller/group/error semantics.
2. **Authoritative target identity:** DD-3 now requires `(targetAgentId, targetThreadId?)`, captured request/arm agent at greeting/send/controller boundaries, mounted-agent ref only for immediate local clicks, and different-target existing-key/live-global read-only fallback.
3. **Behavioral proof:** the exact allowlist and focused gate now include `conversationController.test.ts`; real synchronous completion and audible parity are mandatory, alongside deferred A→B and post-call greeting matrices.
4. **Scope/report consistency:** expected paths, hard stops, acceptance criteria, self-review, and Builder report all include the two minimally expanded controller paths.

### Recommended (promoted within existing scope)

1. React `act(...)` warning cleanup is required in the already-authorized mounted suite; suppression is forbidden.
2. Active-group composer click ownership is required: mutate call state only, leave the host preference untouched.

### Nits

- None.

### Three-pass spec self-review

- **Pass 1 — behavior/spec:** PASS. Every implementation-review failure maps to a named real or mounted behavioral test, including both opposite target-agent rows and controller state observations.
- **Pass 2 — verify-first/code:** PASS. Live signatures/order were re-read at exact base; the prompt distinguishes pre-build code from entities introduced by the revision and preserves AD-985's separate group branch.
- **Pass 3 — scope/safety/a11y/license:** PASS. Only two production/test paths were added to the allowlist; no backend/store/dependency/tracker/Git/GitHub/commercial scope was introduced; license remains none.

**Prompt revision marker:** R1 is preserved as audit history but superseded by R2 below wherever they conflict.

---

## Re-review (2026-07-15) — Option A ownership revision R2

**Verdict:** ✅ APPROVED FOR BUILDER — R2 is internally consistent, verify-first grounded, and executable at the pinned worktree.

### Required (resolved)

1. **Private controller ownership:** DD-9 now specifies exactly one private monotonic generation and the complete accepted-arm/disarm/current-preemption/null-acquisition/test-reset invalidation rules. Same-agent re-arm replaces ownership; empty arm and stale disposer/callback do not advance it; a null acquire retains only exact pending callback bookkeeping so a later stale grant can be released.
2. **Stale async containment:** transcript/VAD/acquisition/preemption closures capture generation, exact options identity, and agent; ownership is checked at entry and every post-await/pre-callback/pre-state/pre-timer boundary. Owner-aware state transitions revalidate after external callbacks. Deferred A fetch/JSON/group/error work is dropped while B remains coherent.
3. **Lifecycle safety:** stale disposer cannot disarm B; acquisition adopts its supplied lease before synchronous wiring/state callbacks; stale queued acquisition wires nothing and releases its stale grant; `_enterSilencePending` and refresh are owner-bound; timer A cannot disarm B.
4. **Public boundary:** `markAgentReplyComplete(): void` remains unchanged. The already-started-utterance completion race is explicitly outside BF-671; no completion token or playback cancellation is authorized.
5. **Parser:** controller response precedence is `response`, then `reply`, then `message`.
6. **Test ownership:** real-controller tests own deferred A→B. Mounted tests retain greeting/send A→B and current callback policy but remove direct invocation of a stale old callback as ownership proof.
7. **Diagnostics:** focused and complete Vitest must be warning-free through test-local async render/act mechanics, never suppression.
8. **Counts:** gates are exact and both controller suites are focused; post-change counts are not predicted and must be reported from observed output only.

### Recommended

1. Keep the ownership predicate and owned-disarm path narrowly private and named around ownership rather than generic cancellation.
2. Use deferred-promise helpers in the existing controller test file to make each replacement boundary deterministic without exporting internals.

### Nits

- None.

### Three-pass spec self-review

- **Pass 1 — behavior/spec:** PASS. Fetch resolve/reject, JSON resolve/reject, same-agent replacement, disarm-only, group submit resolve/reject, stale disposer, synchronous/null/stale acquisition, preemption/VAD staleness, state-callback reentrancy, current muted/audible, callback errors, timer isolation, barge parity, response precedence/fallback, and reset invalidation each have an explicit real-controller test requirement.
- **Pass 2 — verify-first/code:** PASS. Live controller module state, same-agent short-circuit, global disposer, acquisition/preemption closures, transcript/VAD wiring, fetch→JSON and group awaits, reply parser, no-argument completion API, silence timer, test reset, and arbiter stale-lease identity semantics were re-read at pinned HEAD/worktree. R2 distinguishes required migration from existing code.
- **Pass 3 — scope/safety/a11y/license:** PASS. Production/test scope remains exactly the existing ten paths; controller expansion is private and limited to the already-authorized controller/test files; no backend/store/dependency/tracker/Git/GitHub/commercial change; license remains none; warning suppression is forbidden.

### R2 verify-first evidence

```text
conversationController.ts (pinned R1 worktree before R2 build)
  119-130: singleton globals include _state, _agentId, _lease, subscriptions, timer, _opts, and barge disarm; no ownership generation exists yet.
  204: armConversationMode(opts) returns a disposer.
  210-213: same-agent + non-inactive currently returns global disarm, so new opts do not replace ownership.
  222-230: acquisition/preemption callbacks close over mutable globals and do not validate an owner.
  234-237: null acquisition clears mutable owner fields without invalidating queued callbacks.
  242-257: transcript and VAD callbacks do not carry owner identity.
  274-350: _onTranscript rereads _opts/_agentId across submitTranscript, fetch, and JSON awaits and uses mutable globals in success/error paths.
  333: current parser is reply ?? message; response is absent.
  356: markAgentReplyComplete(): void is public and argument-free.
  365-374: silence timer calls global disarm based only on current visible state.
  393-397: public disarm is global; returned old disposer can therefore target a replacement owner.
  429-443: test reset clears globals but has no invalidation generation.

speechRecognitionArbiter.ts
  53-58: Lease has stable readonly id/holder/priority.
  117-121: release compares active lease id, so releasing a stale queued grant is safe and cannot release a different current lease.
  165-175: queued promotion invokes the captured onAcquired callback with its preallocated lease.

conversationController.test.ts (pinned R1 worktree)
  Existing R1 cases cover callback ordering, synchronous completion, audible completion, empty reply, non-OK/network/callback error, barge parity, timer expiry, preemption, transcript hook, and empty transcript.
  Missing R2 proof: deferred fetch/JSON replacement, same-agent replacement, disarm-only, group-submit replacement, stale disposer, stale/null acquisition, stale timer/VAD, response precedence, and reset invalidation.

ProfileChatTab.audioControl.test.tsx (pinned R1 worktree)
  786-812: mounted test rerenders B then directly invokes A's captured mocked onAgentReply; R2 removes this as controller-ownership proof.
  8: render/act/waitFor are imported; R2 requires a test-local async render helper and act-wrapped causative async/store/timer transitions.

git rev-parse HEAD
  14d831cf4d2b4e56e149b8a72979bde5b6802d1d

git status --short before R2 document edits
  exactly 8 implementation/test paths plus the 2 untracked Architect docs; no tracker, stage, deletion, generated output, Git, or GitHub mutation.
```

**R2 marker:** this section supersedes R1 wherever they conflict. The exact Option A rules in DD-9 are binding. Resume only from exact base `14d831cf4d2b4e56e149b8a72979bde5b6802d1d`, the exact R2 worktree contract, and issue #1038.

---

## Re-review (2026-07-15) — final lifecycle/evidence revision R3

**Verdict:** ✅ APPROVED FOR BUILDER — R3 closes every final-review blocker without widening the ten-path implementation scope.

### Required (resolved)

1. **React ownership reaches the controller boundary:** DD-10 requires both accepted `ProfileChatTab` arm branches to capture and return the exact owner-bound disposer. Global disarm remains only in mode-off and meeting-audio-off no-arm branches. The mounted lifecycle test proves stale cleanup A cannot disarm B.
2. **Causal warning cleanup:** the exact GroupChatHeader store mutation/rerender and PTT transcript/async update causes are named and wrapped in `act`; focused and full process stderr must be inspected for exact zero-warning signatures without suppression.
3. **True stale-preemption evidence:** the prior test that actually preempted current B is rejected. R3 requires evidence from A's captured installed preemption path through the real arbiter, with no exposed private/test-only production API.
4. **Unmasked queued acquisition:** every null/queued promotion assertion checks `currentHolder() === null` directly before any cleanup preemption can change the result; the masking release helper is forbidden.
5. **Current mounted callback identity:** same-agent/context re-arm tests select the latest current arm callback, with explicit mock owner/call identity rather than invoking stale arm zero.
6. **Preemption reentrancy:** DD-10 pins the live callback-before-grant order and requires an inactive observer that synchronously arms B during A preemption. The higher-priority holder wins, B remains controller/lease coherent, and B's later queued grant self-releases with no leak.
7. **R2 retained:** one private generation, exact opts identity, agent identity, all async/callback/timer gates, parser order, current reply ordering, public completion API, and every R2 scope restriction remain binding.

### Recommended (included)

1. Use a test-local owner-recording `armConversationMode` mock that returns a distinct disposer per call; this proves React lifecycle behavior without weakening production.
2. Keep deferred preemption notification private and generation-guarded; do not alter the arbiter or add a second controller generation.

### Nits

- None.

### Three-pass spec self-review

- **Pass 1 — behavior/spec:** PASS. Every final-review item maps to an implementation instruction, named behavioral test, report field, and acceptance criterion. R3 distinguishes current callback policy, stale React cleanup, true stale preemption, direct queue proof, and preemption-order reentrancy.
- **Pass 2 — verify-first/code:** PASS. Live `ProfileChatTab` accepted arms discard the returned disposer and return global disarm; active-call mounted tests capture `armCalls[0]`; the PTT callback is invoked outside async `act`; GroupChatHeader mutates/rerenders outside `act`; the stale-preemption test replaces A with B then preempts B; the queue supersession test can preempt/release a surviving holder. Live arbiter order is clear-then-callback-then-grant.
- **Pass 3 — scope/safety/a11y/license:** PASS. Exact production/test allowlist and ten-path status are unchanged. No production, test, tracker, Git, or GitHub file was edited by this Architect revision; no arbiter edit/public test seam/second generation/diagnostic suppression is authorized; license remains none.

### R3 Verified Against Codebase (2026-07-15)

```text
git rev-parse HEAD
  14d831cf4d2b4e56e149b8a72979bde5b6802d1d

git status --short before R3 document edits
  M ui/src/audio/__tests__/conversationController.test.ts
  M ui/src/audio/conversationController.ts
  M ui/src/components/profile/GroupChatHeader.tsx
  M ui/src/components/profile/ProfileChatTab.tsx
  M ui/src/components/profile/__tests__/GroupChatHeader.meeting.test.tsx
  M ui/src/components/profile/__tests__/ProfileChatTab.ad1062.test.tsx
  ?? prompts/bf-671-unified-chat-call-audio-control-execution.md
  ?? prompts/bf-671-unified-chat-call-audio-control.md
  ?? ui/e2e/audio-output-control.spec.ts
  ?? ui/src/components/profile/__tests__/ProfileChatTab.audioControl.test.tsx

ProfileChatTab.tsx (R2 worktree inspected for R3)
  1295-1297: mode-off branch calls global disarm and returns without arming.
  1305-1307: meeting-audio-off branch calls global disarm and returns without arming.
  1310: accepted meeting branch invokes armConversationMode but discards its disposer.
  1336-1338: accepted meeting cleanup calls global disarm.
  1394: accepted 1:1 branch invokes armConversationMode but discards its disposer.
  1395-1397: accepted 1:1 cleanup calls global disarm.

ProfileChatTab.audioControl.test.tsx (R2 worktree inspected for R3)
  24/342: mocked arm returns an anonymous disposer but does not record owner identity.
  666-677: PTT transcript callback is invoked before the later async-act timer flush.
  762-767: captureOrdinaryReply selects armCalls[0], the first arm callback.
  805-828: call-state mutation causes same-agent re-arm, but both active-call tests still invoke that stale first callback.

GroupChatHeader.meeting.test.tsx (R2 worktree inspected for R3)
  117-120: reactive setChatThread plus rerender are not wrapped in act.

conversationController.test.ts (R2 worktree inspected for R3)
  508-518: controller-level stale disposer behavior exists, but no mounted React cleanup/disposer lifecycle proof exists.
  540-562: queued supersession may acquire/release release-stale-queue before asserting null, masking a surviving holder.
  595-602: test named stale preemption arms A then B and the real higher-priority acquire preempts current B; it does not execute captured A's preemption closure.

conversationController.ts (R2 worktree inspected for R3)
  126: exactly one private _ownershipGeneration exists.
  281-292: current preemption invalidates and synchronously tears down/notifies inactive inside the arbiter callback.
  295-308: null acquisition retains pending bookkeeping and becomes inactive.
  310-312: returned disposer is owner-bound through _owns(owner).

speechRecognitionArbiter.ts (read-only)
  88-91: higher-priority acquire invokes _preemptActive before _grantSync.
  157-161: _preemptActive clears active state, then synchronously invokes preempted.onPreempted.
  142-152: _grantSync commits the higher-priority lease only after the preemption callback returns.
  105-109: stale lease release is identity-safe.
  177-185: queued promotion installs the pending lease, then invokes its captured onAcquired.
```

**R3 marker:** this section supersedes R2 wherever they conflict. DD-9 remains binding in full; DD-10 and the R3 test/diagnostic requirements add the final caller/arbiter lifecycle constraints. Resume only from exact base `14d831cf4d2b4e56e149b8a72979bde5b6802d1d`, the exact ten-path R3 worktree contract, and issue #1038.
