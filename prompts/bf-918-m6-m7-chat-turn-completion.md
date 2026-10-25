# BF-918 slices M6 and M7 (#1626): a conversation turn ends on its own reply's last sentence, and the PTT gate stays closed between sentences

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-24

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-25 (Amendment A1, after review round 1: §3 decisions 8 to 10)

**Status:** ready for the Builder. **Base:** `origin/main` `026a682f` (BF-918 M4 and M5 merged, PR #1647). **Issue:** #1626 (BF-918). No new AD or BF number: both are slices of BF-918.

| Milestone | Slices | Finding | Tier | Files | Test files |
|---|---|---|---|---|---|
| M6+M7 (one milestone) | M6: an older reply's `end` no longer completes a newer reply's turn in the same arm. M7: with pipelining on, a reply's turn completes on its last sentence's `end`, and the BF-300 PTT gate stays closed between its sentences (R25's ordinary-reach half) | M4/M5 contract decisions 1 and 2; BF-918 §18 R25 | **HIGH** | `ui/src/components/profile/ProfileChatTab.tsx`, `ui/src/audio/meetingVoice.ts`, `ui/src/components/profile/__tests__/ProfileChatTab.bf918.test.tsx`, `ui/src/components/profile/__tests__/ProfileChatTab.bf767.test.tsx`, `ui/src/audio/__tests__/meetingVoice.test.ts`, `PROGRESS.md`, `DECISIONS.md` | `ProfileChatTab.bf918.test.tsx` (14 cases appended: C13 to C24, C16 and C22 twice), `ProfileChatTab.bf767.test.tsx` (2 tests updated), `meetingVoice.test.ts` (2 cases appended) |

**Tier.** HIGH, the parent's tier (BF-918 is HIGH; a slice is never lowered without the Captain). On its own merits too: the change decides when the conversation controller leaves `agent_speaking`, which turns barge-in off and starts the 30 s release timer, and it changes the echo guard of the composer mic.

**One milestone** (decision 1): one Builder milestone, one consolidated focused check, one Diff Reviewer pass, one local commit. The broad gate is the Python gate only, run once by the main session (§4).

## 1. Problem

**M6.** `ProfileChatTab`'s 1:1 conversation arm sets up one completion listener per reply (`onAgentReply`, `ProfileChatTab.tsx:2106`). Its `end` branch (`:2196-2205`) checks only the event's `agent_id` and, when it won the speech claim, the reply's own `utterance_id`, then calls `complete()` → `markAgentReplyComplete()`. `markAgentReplyComplete` completes whichever turn the controller holds (`conversationController.ts:450-454`). So when a newer reply of the same arm has taken the turn (`replyTurn` was incremented, `:2108`) while the older one still plays, the older reply's own `end` completes the newer reply's turn: the controller goes to `silence_pending` before the newer reply has spoken, barge-in detaches (`_setState`, `:215-216`) and the silence timer starts. The `dropped` branch already has this guard (`:2192`, `if (replyTurn !== ourTurn) { retire(); return; }`); the `end` branch does not.

Reach (by reading): `_onTranscript` accepts a transcript in any state but `inactive` (`conversationController.ts:373`) and the 1:1 arm passes no `canListen` (`ProfileChatTab.tsx:2088-2226`). A transcript that arrives during `agent_speaking` without a VAD `speech_start` in that state (the Captain began talking while the reply was being fetched: `speech_start` in `submitted` is informational, `:366`; the transcript closes later) starts a newer turn while the older reply plays. AD-1291 queues the newer reply behind the older one (`voice.ts:353-392`), so the older reply's `end` always lands inside the newer turn. M7 lengthens the window: the older listener now lives to its reply's last sentence.

**M7.** Under AD-1071 pipelining every sentence fires its own `end` with the reply's `utterance_id` (BF-767). The listener completes on the first one. The controller enters `silence_pending` (`conversationController.ts:460-472`) while sentences 2 to n still play: barge-in works only in `agent_speaking` (`:350`), so the Captain can no longer talk over the rest of the reply, and the 30 s release timer starts early. M5 gave the signal: an AD-1071 sentence's `end` carries `final` (`false` while more of the reply will play, `voice.ts:85`, `:278-280`, `:591`, `:758`).

**R25 (the same family).** The BF-300 PTT gate (`ProfileChatTab.tsx:563-590`) clears on every `end`, so it opens in each gap between two sentences of one reply. The MicIndicator drops its `muted` ring (`:3005`) and a mic press in the gap is accepted (`:2785`); the capture it starts records the next sentence, which is the echo loop BF-300 exists to prevent (#774). The BF-718 in-flight key clear (`:1385-1393`) also acts on every sentence's `end` (decision 4: registered, not fixed).

**Review round 1 (A1).** Two defects of the same family, found through the production parents:

- **An agent change.** The gate's effect (`ProfileChatTab.tsx:571-625`, deps `[agentId]`) clears its timer in the cleanup but leaves `ttsActiveRef` and `ttsActive` as they were. `AgentProfilePanel` (`:740`) and `CompactApp` (`:229`) re-point the same composer at another agent without a remount, and the new subscription ignores the old agent's events (`:573`), so a gate held at the change stays closed with no timer: the new agent's MicIndicator shows `muted` and its mic press is refused (`:2828`) until that agent speaks. M7 made it ordinary (every gap of a pipelined reply holds the gate); during a sentence the base already did it.
- **The meeting's echo gate.** `meetingVoice.ts` `_speakAndWait` (`:105-154`) ends its wait on the first attributed `end`, which under pipelining is the first sentence's (`final: false`). `speakRepliesSequentially` (`:177-190`) then clears the speaking id and `useMeetingVoice` (`:164-168`) publishes `speakingAgentId = null`, which is the meeting arm's `canListen` (`ProfileChatTab.tsx:1117`, `:2071`): the open mic accepts and submits what it hears while sentences 2 to n play, and the speaking label and the BF-621 reveal advance early. Pre-existing since M5 gave `final` (reproduced on base and candidate alike); M5's consumer enumeration named `ProfileChatTab` only, and §9 listed the meeting path as unchanged.

## 2. Solution

**M6.** In the reply listener's `end` branch, first: if a newer reply of this arm has taken the turn (`replyTurn !== ourTurn`), retire the listener and return without completing. It comes before the identity checks: a superseded listener has nothing left to complete, so any `end` may retire it.

**M7.** After the identity checks, an `end` with `final === false` returns without completing. The last sentence's `end` (`final: true`), and every non-pipelined `end` (no `final`), still completes. A stop while a sentence plays fires that sentence's `end` with `final: true` (`_finalField` reads `_activeUtteranceId`, which `stopSpeaking` clears first, `voice.ts:942`). A stop between two sentences fires no further `end`; its only production cause is the controller's own barge-in (§12), which moves the controller to `listening` itself.

**PTT gate (R25's ordinary-reach half).** An `end` with `final === false` keeps the gate closed and replaces the sentence's BF-655 ceiling with a gap ceiling, `PTT_SENTENCE_GAP_MS = 5000`. The next sentence's `start` re-arms the 45 s ceiling as now. With no next `start` within 5 s (a stop between two sentences, or a gap longer than that) the gate opens, as every gap did before M7. The last sentence's `end` clears it as now.

**A1.** The gate's effect cleanup also opens the gate (`ttsActiveRef` and `ttsActive` to `false`) after clearing its timer: the gate ends with its agent's subscription. `_speakAndWait` ignores an `end` with `final === false` after its attribution check, as the arbiter (`voice.ts:471`) and the reply listener do; `dropped`, the safety timeout and the attribution rules are unchanged.

## 3. Decisions (for #1626; ranked where there were options)

1. **One milestone for both slices** (option a). (a) One milestone (chosen): M6 and M7 change the same twelve-line branch, are tested in the same harness, and C14 crosses both (a pipelined older reply behind a newer turn). (b) Two milestones: rejected, two review rounds for one branch and the M4/M5 contract already coupled them (its decision 1).
2. **M6: retire on any `end` once superseded, before the identity checks** (option a). (a) A turn check in the `end` branch, as the `dropped` branch has (chosen): one condition, the reviewed precedent at `:2192`. (b) Retire every earlier listener when a newer reply arrives (`retirePendingReplies()` at the top of `onAgentReply`): rejected; equivalent in effect, but it turns the reviewed `dropped` guard into dead code and changes the retirement contract that review rounds 3 to 5 settled (listeners end with their own terminal event or their arm). (c) Pass a turn token to `markAgentReplyComplete`: rejected; it changes the controller's public signature, which at least 8 test files mock (audioControl, issue1340.groupUnmount, ad1291.e2e, groupReplyIdentity, bf764, bf718, bf767, bf290). Placement before the agent and id checks (not after, as in the `dropped` branch): a superseded listener can only retire, so retiring early is always safe, and a listener whose own utterance was stopped between two sentences (no further `end` of its id) or that lost the claim would otherwise live to its arm's end.
3. **M7: ignore `final === false`, nothing more** (option a). (a) Chosen: the additive contract of M5, so every producer without `final` is unchanged, including the test files that mock `voice.ts` (M5's contract counted about 50; not recounted here). (b) Complete only on `final === true`: rejected, every non-pipelined `end` carries no `final`. (c) Also bound the turn's wait by a gap timer: rejected; a slow synthesis would complete the turn mid-reply, which is M7's defect. The one stop it would cover that barge-in does not (GUARD 2's newer dispatch after 45 s of silence) is registered as R32.
4. **R25's family under the convergence rule.** The PTT gate is fixed here: its reach is ordinary (every gap of every pipelined multi-sentence reply), and a Captain trying to interject presses at sentence boundaries, which are exactly the gaps (blind spot 1, §13). The in-flight key clear is registered (R33): its reader (`:2150`) is reached only when an identical reply loses its claim after the in-flight one's first sentence ended, and keeping the key until `final` errs toward waiting on an `end` that a stop between two sentences never emits, the stranded controller BF-718's comment (`:1373-1374`) chose to avoid. `wakeWord.ts:187-193` is the same shape in another file, with no audio playing during the gap: registered (R34).
5. **The gap ceiling** (option a). (a) `PTT_SENTENCE_GAP_MS = 5000` on the gate's existing watchdog ref (chosen): a stop between two sentences reopens the gate within 5 s, and a gap longer than 5 s degrades to the base behaviour, never worse. (b) Keep the gate closed under BF-655's 45 s ceiling only: rejected; a barge-in between two sentences (likely, blind spot 1) would show `muted` and refuse the composer mic for up to 45 s while the conversation mic listens. (c) Clear the gate on the controller's barge-in transition: rejected; it couples the PTT gate to the conversation arm and misses GUARD 2's path. The value is from reading, not from a measured gap: the next sentence is synthesized while the current one plays (`runPrefetchQueue`, lookahead 1), so an ordinary gap is the play-start latency. Revisit against the live `bf918:sentence-gap` values (BF-918 §16) if they approach 5 s. A module constant like `PTT_TTS_WATCHDOG_MS`, not config.
6. **The two `ProfileChatTab.bf767.test.tsx` tests that pinned M6's defect are updated, not deleted.** `does not complete the new turn on the cancelled utterance's end` expected exactly one completion, "turn 1's", after turn 2 had arrived: in the controller that completion ends turn 2's turn. They now expect none, with the reason inline. BF-767's own property (turn 2 does not complete on turn 1's `end`) still kills its mutant (§10, M6-1 note).
7. **Tier HIGH** (the parent's). **Pipelining stays default-off.** No config change.
8. **A1, the agent change: the gate resets with its subscription** (option a). (a) The effect's cleanup sets `ttsActiveRef.current = false` and `setTtsActive(false)` after clearing the timer (chosen): one place for every parent (`AgentProfilePanel`, `CompactApp`, `MobileShell`, an unmount), the lifetime the timer already has, and it also fixes the base's mid-sentence case. It does not run for a newer `start` of the same agent or for a re-render that keeps `agentId` (the effect's deps are `[agentId]`; C23 pins it). (b) Keep the gate for the agent that closed it and let the next subscription follow that agent's events too: rejected; a redesign of BF-300's per-agent subscription, and an old agent's `end` while another is shown would still be missed, so a return after the reply had finished would hold the mic for BF-655's 45 s. (c) Seed the gate on each subscription from the arbiter (`speechQueueState()`): rejected here; a new cross-module read and behaviour no finding asked for. What (a) gives up: a return to an agent while one of its sentences still plays now shows the gate open until its next `start`, as a first mount always has; on the base that return happened to find the gate closed, from the same stale state that strands the other agent. The more common return, after the reply has finished, was stranded on the base and is now right. Registered as R36, with (c) as its design.
9. **A1, the meeting wait: fixed inside #1626** (option a). (a) `_speakAndWait` ignores `final === false` (chosen): one condition in an existing file, the second consumer of M5's `final`, same tier, and C24 crosses the whole chain (real `voice.ts`, `useMeetingVoice`, the controller and the production predicate). The wait keeps its whole-reply safety timeout (`computeUtteranceTimeout`, BF-615; a non-pipelined reply's single `end` already came after the whole reply). In a meeting a stop between two sentences has no ordinary cause: the meeting arm submits through `submitTranscript` and never enters `agent_speaking` (`conversationController.ts:399-410`; `:433` is the only entry), so barge-in (`:350`) and with it `stopSpeaking` (its only production caller, §12) cannot run there. The causes left are GUARD 2 and a 1:1 barge-in on another surface, and the timeout ends that wait (R32, extended). (b) Its own slice or issue: rejected; one line, and the review asked that it not become another residual. (c) Also a gap timer on the meeting wait, like the PTT gate's: rejected; more code and a `start` rule in its listener for a stop with no ordinary cause.
10. **A1, review finding 3: registered (R35), not folded in.** Injected-only reach, and the base fails the same property. Its fix (gate ownership by the `start`'s `utterance_id`, in the `start` and `end` branches) is not the code decision 8 touches (the cleanup), and it would add an ownership rule to every pipelined reply's hot path and a new property to the round-2 review.

## 4. Milestones, focused checks and tests-first expectations

**M6+M7** (TypeScript). Apply §7.1 to §7.5 and §8's pairs, then, from `ui/`:

```
npx vitest run src/components/profile src/audio src/__tests__/ProfileChatTab
npx tsc -b
```

Tests first, on the base `ProfileChatTab.tsx` with §7.2 and §7.3 applied:

| Test | On the base | First failing assertion |
|---|---|---|
| C13 | fails | `expect(getConversationState()).toBe('agent_speaking')` after `endAudio(audios[0])` (received `'silence_pending'`) |
| C14 | fails | the same assertion after the first sentence's `endAudio(audios[0])` |
| C15 | fails | the same assertion after the first sentence's `endAudio(audios[0])` |
| C16 `[inside pause()]`, `[after pause() returns]` | fail | `expect(getConversationState()).toBe('listening')` after `bargeIn()` (received `'silence_pending'`: barge-in does nothing there) |
| C17 | passes | (control) |
| C18 | fails | `expect(getConversationState()).toBe('listening')` after `bargeIn()` (received `'silence_pending'`) |
| C19 | fails | `expect(muted()).toBe(true)` after the first sentence's `endAudio(audios[0])` (received `false`) |
| C20 | fails | the same assertion |
| C21 | fails | the same assertion |
| bf767 `does not complete the new turn on the cancelled utterance's end` | fails | `toHaveBeenCalledTimes(0)` (received 1) |
| bf767 `completes the turn on its own utterance end` | fails | its first `toHaveBeenCalledTimes(0)` (received 1) |

C1 to C12 pass. These predictions come from reading; none was executed (§17). If one is wrong, report the observed assertion; do not edit the test to match the prediction.

**A1 tests first.** On the base with §7.2 to §7.5's test pairs applied (what the oracle builds), and on the candidate `ebaf69b9` with A1's test pairs applied but not its two source pairs:

| Test | On the base | On the candidate | First failing assertion |
|---|---|---|---|
| C22 `[between two sentences]` | fails | fails | base: `expect(muted()).toBe(true)` before the change of agent (received `false`: the base opens every gap); candidate: `expect(muted()).toBe(false)` after `openAgentProfile('a2')` (received `true`) |
| C22 `[while a sentence plays]` | fails | fails | `expect(muted()).toBe(false)` after `openAgentProfile('a2')` (received `true`) |
| C23 | fails | passes | base: `expect(muted()).toBe(true)` after `endAudio(audios[0])` (received `false`); candidate: control |
| C24 | fails | fails | `expect(meeting.result.current.speakingAgentId).toBe('a1')` after `endAudio(audios[0])` (received `null`) |
| `test_bf918_m7_non_final_end_does_not_advance_or_clear_speaking` | fails | fails | `expect(fake.speakCalls.map((c) => c.agentId)).toEqual(['alpha'])` (received `['alpha', 'bravo']`) |
| `test_bf918_m7_safety_timeout_still_ends_a_wait_whose_last_sentence_never_ends` | fails | fails | `expect(fake.speakCalls).toHaveLength(1)` after 59 999 ms (received 2) |

On the base the 11 failures of the table above become 17 (these 6 added); every other case of the four test files passes. On the candidate with A1's test pairs only, exactly the 5 marked above fail. After A1 the focused set is 92 files and 1003 tests (997 + 6; no new file). From reading, not executed (§17). C22 needs no fake clock: the gate opens at the change of agent itself. The two `meetingVoice.test.ts` cases use that file's idiom (`tick()`, and plain `vi.useFakeTimers()` as `test_bf862_dropped_advances_promptly_without_waiting_the_safety_timeout` does, restored by its `afterEach`).

**Harness rules.** `flush()` is 60 microtask turns; the new cases wait with `waitFor` wherever a count of turns would be a guess. Never add a wall-clock sleep. C20 and C21 use `vi.useFakeTimers({ shouldAdvanceTime: true })`, as `ProfileChatTab.bf764.test.tsx:384` does with this component: Testing Library's `waitFor` waits on a `setTimeout(0)` that a clock without `shouldAdvanceTime` never fires. If C20 or C21 is flaky, report it; the margins are 1 to 2 s against a test that takes milliseconds.

**The broad gate** is run once by the main session, not by the Builder. It is the Python gate (`scripts/run_test_gate.py`); it does not run vitest. The UI evidence is the focused vitest run, `tsc -b`, and CI `ui-tests`.

## 7. The contract

### 7.1 `ui/src/components/profile/ProfileChatTab.tsx`

Pair 1 (the gap ceiling):

SEARCH:
```tsx
// re-armed on every fresh 'start' is the minimal robust choice.
const PTT_TTS_WATCHDOG_MS = 45000;
```
REPLACE:
```tsx
// re-armed on every fresh 'start' is the minimal robust choice.
const PTT_TTS_WATCHDOG_MS = 45000;

// BF-918 M7 (#1626, R25): under AD-1071 pipelining the PTT gate stays closed between
// two sentences of one reply, for at most this long after a sentence's 'end' with
// `final: false`. A stop between two sentences emits no further event, so without a
// bound the gate would stay closed until BF-655's ceiling. Longer than an ordinary
// gap (the next sentence is synthesized while this one plays); a gap that outlasts
// it opens the gate, as every gap did before M7.
const PTT_SENTENCE_GAP_MS = 5000;
```

Pair 2 (the PTT gate):

SEARCH:
```tsx
      } else if (event.type === 'end') {
        ttsActiveRef.current = false;
        setTtsActive(false);
        // BF-655: the utterance ended normally — cancel the watchdog.
```
REPLACE:
```tsx
      } else if (event.type === 'end' && event.final === false) {
        // BF-918 M7 (#1626, R25): an AD-1071 sentence has ended and more of the same
        // reply will play (M5's `final`). Keep the gate closed across the gap: a press
        // here used to start a capture that heard the next sentence. The gap is
        // bounded, because a stop between two sentences emits no further event: with
        // no next 'start' within PTT_SENTENCE_GAP_MS the gate opens. This replaces
        // the sentence's BF-655 ceiling; the next 'start' re-arms that one.
        clearTimeout(ttsWatchdogRef.current ?? undefined);
        ttsWatchdogRef.current = setTimeout(() => {
          ttsWatchdogRef.current = null;
          ttsActiveRef.current = false;
          setTtsActive(false);
          console.info(
            `[ProfileChatTab] BF-918 M7: no next sentence for agent ${agentId} within ` +
            `${PTT_SENTENCE_GAP_MS}ms; PTT gate reopened.`,
          );
        }, PTT_SENTENCE_GAP_MS);
      } else if (event.type === 'end') {
        ttsActiveRef.current = false;
        setTtsActive(false);
        // BF-655: the utterance ended normally — cancel the watchdog.
```

Pair 3 (the reply listener's `end` branch: M6 and M7):

SEARCH:
```tsx
          if (event.type !== 'end') return;
          // BF-767: strict equality. An 'end' with NO agent_id used to match
          // every agent, so an unattributed utterance elsewhere in the app
          // could close this turn.
          if (event.agent_id !== armAgentId) return;
          // Lost the claim: a different caller owns the in-flight utterance and
          // we cannot know its id, so that path stays agent-scoped (BF-718 —
          // requiring an id we can never learn would strand the controller).
          if (claimed && event.utterance_id !== ourUtteranceId) return;
          complete();
        });
```
REPLACE:
```tsx
          if (event.type !== 'end') return;
          // BF-918 M6 (#1626): a newer reply of this arm has taken the turn since this
          // one was set up, so this reply's turn is over. Completing now would end the
          // newer turn: `markAgentReplyComplete` completes whichever turn the controller
          // holds. A superseded listener has nothing left to complete, so any 'end'
          // retires it (the 'dropped' branch above does the same for its own drop).
          if (replyTurn !== ourTurn) {
            retire();
            return;
          }
          // BF-767: strict equality. An 'end' with NO agent_id used to match
          // every agent, so an unattributed utterance elsewhere in the app
          // could close this turn.
          if (event.agent_id !== armAgentId) return;
          // Lost the claim: a different caller owns the in-flight utterance and
          // we cannot know its id, so that path stays agent-scoped (BF-718 —
          // requiring an id we can never learn would strand the controller).
          if (claimed && event.utterance_id !== ourUtteranceId) return;
          // BF-918 M7 (#1626): under AD-1071 pipelining every sentence fires an 'end'
          // with the reply's id, and `final: false` says more of it will play (M5).
          // Completing on it moved the controller to `silence_pending` mid-reply, so
          // barge-in stopped working and the silence timer started early. The last
          // sentence, or a stop while one plays, carries `final: true`; every other
          // 'end' carries no `final` and completes as before. A stop between two
          // sentences emits no further 'end': barge-in, its one production cause, moves
          // the controller itself (GUARD 2's later dispatch is BF-918's R32).
          if (event.final === false) return;
          complete();
        });
```

Pair 4 (A1, review round 1: the gate resets with its agent's subscription):

SEARCH:
```tsx
    return () => {
      try { unsub(); } catch { /* Tier-2 */ }
      // BF-655: never leave a dangling watchdog timer on unmount.
      if (ttsWatchdogRef.current !== null) {
        clearTimeout(ttsWatchdogRef.current);
        ttsWatchdogRef.current = null;
      }
    };
  }, [agentId]);
```
REPLACE:
```tsx
    return () => {
      try { unsub(); } catch { /* Tier-2 */ }
      // BF-655: never leave a dangling watchdog timer on unmount.
      if (ttsWatchdogRef.current !== null) {
        clearTimeout(ttsWatchdogRef.current);
        ttsWatchdogRef.current = null;
      }
      // BF-918 M7 (#1626, review round 1): the gate ends with its agent's
      // subscription. A change of `agentId` keeps the composer (AgentProfilePanel and
      // CompactApp re-point it without a remount), and the next subscription ignores
      // this agent's events, so a gate left closed here, inside a reply or between
      // two of its sentences, had no 'end' and no timer left to open it. On unmount
      // both writes are harmless.
      ttsActiveRef.current = false; // the composer mic's click guard reads this
      setTtsActive(false); // the MicIndicator's 'muted' ring reads this
    };
  }, [agentId]);
```

### 7.2 `ui/src/components/profile/__tests__/ProfileChatTab.bf918.test.tsx`

Pair 1 (a harness flag for the order of the media element's `pause` event):

SEARCH:
```tsx
let events: Array<[string, string | undefined]> = [];
let off: () => void = () => {};
```
REPLACE:
```tsx
let events: Array<[string, string | undefined]> = [];
let off: () => void = () => {};
/** BF-918 M7: when true, the media double delivers 'pause' after `pause()` returns. */
let deferPause = false;
```

Pair 2 (reset it per test):

SEARCH:
```tsx
  events = [];
  vi.stubGlobal('Audio', MediaDouble);
```
REPLACE:
```tsx
  events = [];
  deferPause = false;
  vi.stubGlobal('Audio', MediaDouble);
```

Pair 3 (the media double):

SEARCH:
```tsx
  pause(): void { this.emit('pause'); }
```
REPLACE:
```tsx
  /** By default 'pause' fires inside `pause()`. BF-918 M7: `deferPause` delivers it a
   *  microtask later, after the caller has returned (a browser queues the event). C16
   *  runs both orders, so no case depends on either. */
  pause(): void {
    if (deferPause) {
      void Promise.resolve().then(() => this.emit('pause'));
      return;
    }
    this.emit('pause');
  }
```

Pair 4 (the new cases, appended after C12):

SEARCH:
```tsx
    await oldEndLands(old);
    expect(getConversationState()).toBe('agent_speaking');
    await replacementPlaysAndEnds();
  });
});
```
REPLACE:
```tsx
    await oldEndLands(old);
    expect(getConversationState()).toBe('agent_speaking');
    await replacementPlaysAndEnds();
  });
});

/** BF-918 (#1626) slices M6 and M7. M6: an older reply's 'end' must not complete a
 *  newer reply's turn in the same arm. M7: with AD-1071 pipelining on, a reply's turn
 *  completes on its last sentence's 'end' (M5's `final` is not `false`), not its
 *  first, and the BF-300 PTT gate stays closed between two sentences of one reply.
 *
 *  Same doubles as above. `/tts/status` answers `sentence_pipelining_enabled:
 *  pipelining`. Every TTS POST is held until the test answers it, oldest first, and
 *  the queue prepares one sentence ahead, so the next sentence's POST is made while
 *  the current one plays. Assertions are on the controller's state and on the
 *  rendered mic indicator, never on which branch ran. */
describe('BF-918 M6 and M7: a reply completes its turn on its own last sentence', () => {
  let pipelining = true;
  const GAP_MS = 5000; // ProfileChatTab's PTT_SENTENCE_GAP_MS (not exported)
  const TWO = 'First sentence. Second sentence.';
  const pauseOrders: Array<[string, boolean]> = [['inside pause()', false], ['after pause() returns', true]];

  beforeEach(() => {
    pipelining = true;
    const outer = globalThis.fetch;
    vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL, options?: RequestInit) => {
      if (String(url).endsWith('/tts/status')) {
        return respond({ enabled: true, backend: 'piper', sentence_pipelining_enabled: pipelining });
      }
      return outer(url, options);
    }));
  });

  const muted = (): boolean => screen.queryByTestId('mic-indicator-ring-muted') !== null;

  async function plays(index: number): Promise<void> {
    await waitFor(() => expect(audios[index]?.played).toBe(true));
  }

  /** The reply's first sentence is synthesized and plays; the second's POST is made. */
  async function firstSentencePlays(): Promise<void> {
    await waitFor(() => expect(ttsPosts).toEqual(['First sentence.']));
    await answerSynthesis();
    await plays(0);
    await waitFor(() => expect(ttsPosts).toEqual(['First sentence.', 'Second sentence.']));
  }

  it('C13 (M6): an older reply\'s end does not complete the newer reply\'s turn, pipelining off', async () => {
    pipelining = false;
    answers = ['First answer.', 'Second answer.'];
    await arm();
    await captainSays('First question.');
    await waitFor(() => expect(ttsPosts).toEqual(['First answer.']));
    await answerSynthesis();
    await plays(0);
    // A transcript while the reply plays, with no barge-in (the Captain began talking
    // before the reply arrived): a newer reply takes the turn and queues behind it.
    await captainSays('Second question.');
    expect(chats).toBe(2);
    expect(getConversationState()).toBe('agent_speaking');
    expect(ttsPosts).toEqual(['First answer.']);
    await endAudio(audios[0]);
    // Before M6: `silence_pending`, the newer turn ended by the older reply's 'end'.
    expect(getConversationState()).toBe('agent_speaking');
    await waitFor(() => expect(ttsPosts).toEqual(['First answer.', 'Second answer.']));
    await answerSynthesis();
    await plays(1);
    expect(getConversationState()).toBe('agent_speaking');
    await endAudio(audios[1]);
    expect(getConversationState()).toBe('silence_pending');
  });

  it('C14 (M6 with M7): an older pipelined reply\'s sentences do not complete the newer reply\'s turn', async () => {
    answers = [TWO, 'Second answer.'];
    await arm();
    await captainSays('First question.');
    await firstSentencePlays();
    await captainSays('Second question.');
    expect(chats).toBe(2);
    expect(getConversationState()).toBe('agent_speaking');
    await endAudio(audios[0]);
    // Before M6 and M7: `silence_pending`, ended by the older reply's first sentence.
    expect(getConversationState()).toBe('agent_speaking');
    await answerSynthesis();
    await plays(1);
    await endAudio(audios[1]); // the older reply's last sentence: `final: true`
    expect(getConversationState()).toBe('agent_speaking');
    await waitFor(() => expect(ttsPosts).toEqual(['First sentence.', 'Second sentence.', 'Second answer.']));
    await answerSynthesis();
    await plays(2);
    expect(getConversationState()).toBe('agent_speaking');
    await endAudio(audios[2]);
    expect(getConversationState()).toBe('silence_pending');
  });

  it('C15 (M7): a pipelined reply keeps its turn until its last sentence ends', async () => {
    answers = [TWO];
    await arm();
    await captainSays('Question.');
    expect(getConversationState()).toBe('agent_speaking');
    await firstSentencePlays();
    await endAudio(audios[0]);
    // Before M7: `silence_pending`, with the second sentence still to play.
    expect(getConversationState()).toBe('agent_speaking');
    await answerSynthesis();
    await plays(1);
    expect(getConversationState()).toBe('agent_speaking');
    await endAudio(audios[1]);
    expect(events.map(([type]) => type)).toEqual(['start', 'end', 'start', 'end']);
    expect(getConversationState()).toBe('silence_pending');
  });

  it.each(pauseOrders)('C16 (M7, pause %s): barge-in still stops a pipelined reply after its first sentence', async (_order, deferred) => {
    deferPause = deferred;
    answers = [TWO];
    await arm();
    await captainSays('Question.');
    await firstSentencePlays();
    await endAudio(audios[0]);
    await answerSynthesis();
    await plays(1);
    await bargeIn();
    // Before M7: `silence_pending` (the first sentence completed the turn), where barge-in does nothing.
    expect(getConversationState()).toBe('listening');
    // The second sentence was stopped, and its 'end' (`final: true`) delivered.
    expect(events.map(([type]) => type)).toEqual(['start', 'end', 'start', 'end']);
  });

  it('C17 control: with pipelining on, a one-sentence reply completes on its only end', async () => {
    answers = ['Only sentence.'];
    await arm();
    await captainSays('Question.');
    await waitFor(() => expect(ttsPosts).toEqual(['Only sentence.']));
    await answerSynthesis();
    await plays(0);
    expect(getConversationState()).toBe('agent_speaking');
    await endAudio(audios[0]);
    expect(getConversationState()).toBe('silence_pending');
  });

  it('C18 (M7): a barge-in between two sentences leaves nothing that completes the next turn', async () => {
    answers = [TWO, 'Next answer.'];
    await arm();
    await captainSays('Question.');
    await firstSentencePlays();
    await endAudio(audios[0]);
    await bargeIn(); // between the sentences: nothing plays, so no further 'end' comes
    // Before M7: `silence_pending`, where barge-in does nothing.
    expect(getConversationState()).toBe('listening');
    await answerSynthesis(); // the second sentence's synthesis answers late and is discarded
    await waitFor(() => expect(audios).toHaveLength(2));
    expect(audios[1].played).toBe(false);
    await captainSays('Next question.');
    expect(chats).toBe(2);
    expect(getConversationState()).toBe('agent_speaking');
    await waitFor(() => expect(ttsPosts).toEqual(['First sentence.', 'Second sentence.', 'Next answer.']));
    await answerSynthesis();
    await plays(2);
    expect(getConversationState()).toBe('agent_speaking');
    await endAudio(audios[2]);
    expect(events.map(([type]) => type)).toEqual(['start', 'end', 'start', 'end']);
    expect(getConversationState()).toBe('silence_pending');
  });

  it('C19 (M7, R25): the PTT gate stays closed between two sentences of one reply', async () => {
    answers = [TWO];
    await arm();
    expect(muted()).toBe(false);
    await captainSays('Question.');
    await firstSentencePlays();
    expect(muted()).toBe(true);
    await endAudio(audios[0]);
    // Before M7: false, and a mic press here started a capture that heard the next sentence.
    expect(muted()).toBe(true);
    await answerSynthesis();
    await plays(1);
    expect(muted()).toBe(true);
    await endAudio(audios[1]);
    expect(muted()).toBe(false);
  });

  it('C20 (M7, R25): a stop between two sentences reopens the PTT gate within the gap ceiling', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      answers = [TWO];
      await arm();
      await captainSays('Question.');
      await firstSentencePlays();
      await endAudio(audios[0]);
      // Before M7: false (every gap opened the gate).
      expect(muted()).toBe(true);
      await bargeIn();
      expect(getConversationState()).toBe('listening');
      await answerSynthesis(); // discarded: nothing more of this reply will play
      expect(muted()).toBe(true);
      await act(async () => { await vi.advanceTimersByTimeAsync(GAP_MS - 2000); });
      expect(muted()).toBe(true);
      await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
      // BF-655's 45 s ceiling alone would still hold it closed here.
      expect(muted()).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it('C21 (M7, R25): the gate\'s ceiling follows the sentence that is playing', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      answers = [TWO];
      await arm();
      await captainSays('Question.');
      await firstSentencePlays(); // the first sentence's 'start' arms BF-655's 45 s ceiling
      await endAudio(audios[0]);
      expect(muted()).toBe(true);
      await act(async () => { await vi.advanceTimersByTimeAsync(4000); }); // inside the gap ceiling
      expect(muted()).toBe(true);
      await answerSynthesis();
      await plays(1); // the second sentence's 'start' re-arms the 45 s ceiling from here
      // 45.5 s after the first sentence's start, 41.5 s after the second's.
      await act(async () => { await vi.advanceTimersByTimeAsync(41500); });
      expect(muted()).toBe(true);
      await endAudio(audios[1]);
      expect(muted()).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it.each([['between two sentences', true], ['while a sentence plays', false]] as Array<[string, boolean]>)(
    'C22 (M7, review round 1): opening another crew member\'s profile %s leaves the new agent\'s mic ungated',
    async (_phase, inGap) => {
      const first: Agent = {
        id: 'a1', agentType: 'scout', callsign: 'First', displayName: 'First', pool: 'scout',
        state: 'active', confidence: 0.8, trust: 0.7, tier: 'domain', isCrew: true, position: [0, 0, 0],
      };
      useStore.setState({
        agents: new Map([['a1', first], ['a2', { ...first, id: 'a2', callsign: 'Second', displayName: 'Second' }]]),
        activeProfileAgent: 'a1',
        activeProfileThreadId: null,
        activeThreadId: null,
        chatThreads: new Map(),
        threadIdByAgent: new Map(),
      });
      try {
        answers = [TWO];
        render(<AgentProfilePanel />);
        await waitFor(() => expect(getConversationState()).toBe('listening'));
        const composer = screen.getByPlaceholderText('Message...');
        await captainSays('Question.');
        await firstSentencePlays();
        if (inGap) await endAudio(audios[0]);
        expect(muted()).toBe(true);
        act(() => { useStore.getState().openAgentProfile('a2'); });
        await act(async () => { await flush(); });
        // The panel re-points the same composer at a2; it does not remount it.
        expect(screen.getByPlaceholderText('Message...')).toBe(composer);
        // Before A1: still `muted`, with no timer left to open it, because a2's
        // subscription ignores a1's later events. Between two sentences that was M7's
        // regression; during a sentence the base already did it.
        expect(muted()).toBe(false);
        const info = vi.spyOn(console, 'info');
        fireEvent.click(screen.getByTestId('mic-indicator').closest('button')!);
        expect(info.mock.calls.some((args) => String(args[0]).includes('mic press ignored for agent a2'))).toBe(false);
      } finally {
        useStore.setState({ activeProfileAgent: null, agents: new Map() });
      }
    },
  );

  it('C23 control (M7, review round 1): a re-render that keeps the agent keeps the gate closed between two sentences', async () => {
    answers = [TWO];
    const surface = render(<ProfileChatTab agentId="a1" />);
    await waitFor(() => expect(getConversationState()).toBe('listening'));
    await captainSays('Question.');
    await firstSentencePlays();
    await endAudio(audios[0]);
    expect(muted()).toBe(true);
    surface.rerender(<ProfileChatTab agentId="a1" threadId="another-thread" />);
    await act(async () => { await flush(); });
    // The gate's effect depends on `agentId` only, so its cleanup did not run.
    expect(muted()).toBe(true);
    await answerSynthesis();
    await plays(1);
    expect(muted()).toBe(true);
    await endAudio(audios[1]);
    expect(muted()).toBe(false);
  });

  it('C24 (M7, review round 1): in a meeting the open mic stays refused until the reply\'s last sentence ends', async () => {
    let submits = 0;
    const meeting = renderHook(() => useMeetingVoice({ meetingActive: true, scopeKey: 'c24', owner: 'c24' }));
    // ProfileChatTab's meeting arm passes this predicate (AD-922's echo gate).
    const dispose = armConversationMode({
      agentId: 'a1',
      canListen: () => meeting.result.current.speakingAgentId == null,
      submitTranscript: async () => { submits += 1; },
    });
    try {
      await waitFor(() => expect(getConversationState()).toBe('listening'));
      expect(hardware.transcripts.size).toBe(1);
      act(() => { meeting.result.current.speakReplies([{ agent_id: 'a1', text: TWO }]); });
      await firstSentencePlays();
      expect(meeting.result.current.speakingAgentId).toBe('a1');
      await captainSays('Heard during the first sentence.');
      expect(submits).toBe(0);
      await endAudio(audios[0]);
      // Before A1: null (the first sentence's 'end' ended the wait), and the
      // transcript below was submitted while the second sentence played.
      expect(meeting.result.current.speakingAgentId).toBe('a1');
      await answerSynthesis();
      await plays(1);
      await captainSays('Heard during the second sentence.');
      expect(submits).toBe(0);
      await endAudio(audios[1]);
      await waitFor(() => expect(meeting.result.current.speakingAgentId).toBe(null));
      // Control: once the reply is over, the open mic submits.
      await captainSays('The Captain, after the reply.');
      expect(submits).toBe(1);
    } finally {
      dispose();
    }
  });
});
```

Pair 5 (A1: `renderHook` for C24):

SEARCH:
```tsx
import { act, cleanup, fireEvent, render, screen, waitFor, type RenderResult } from '@testing-library/react';
```
REPLACE:
```tsx
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, type RenderResult } from '@testing-library/react';
```

Pair 6 (A1: the modules C22 and C24 use):

SEARCH:
```tsx
import { ProfileChatTab } from '../ProfileChatTab';
import { useStore } from '../../../store/useStore';
import * as voice from '../../../audio/voice';
import {
  getConversationState,
```
REPLACE:
```tsx
import { ProfileChatTab } from '../ProfileChatTab';
import { AgentProfilePanel } from '../AgentProfilePanel';
import { useStore } from '../../../store/useStore';
import type { Agent } from '../../../store/types';
import * as voice from '../../../audio/voice';
import { useMeetingVoice } from '../../../audio/useMeetingVoice';
import {
  armConversationMode,
  getConversationState,
```

### 7.3 `ui/src/components/profile/__tests__/ProfileChatTab.bf767.test.tsx` (the two tests that pinned M6's defect)

Pair 1:

SEARCH:
```tsx
    // HEADLINE: exactly ONE completion — turn 1's, for the utterance that
    // genuinely ended. Turn 2 has not been spoken yet, so it must still be
    // waiting. Pre-fix this is 2: turn 2 completed on turn 1's death rattle.
    expect(mocks.markAgentReplyCompleteMock).toHaveBeenCalledTimes(1);
```
REPLACE:
```tsx
    // HEADLINE: NO completion. Turn 2 has not been spoken yet, so it must still be
    // waiting. Before BF-767 this was 2: turn 2 completed on turn 1's death rattle.
    // BF-918 M6 (#1626): this used to expect 1, "turn 1's", for the utterance that
    // genuinely ended. But turn 2 already holds the controller's turn when turn 1's
    // 'end' lands, and `markAgentReplyComplete` completes whichever turn the
    // controller holds, so that 1 was turn 2's turn ending on turn 1's audio (the
    // M6 defect, pinned as the contract). Turn 1's listener now retires instead.
    expect(mocks.markAgentReplyCompleteMock).toHaveBeenCalledTimes(0);
```

Pair 2:

SEARCH:
```tsx
    act(() => { onAgentReply('First reply.'); });
    act(() => { onAgentReply('Second reply.'); });
    expect(mocks.markAgentReplyCompleteMock).toHaveBeenCalledTimes(1);

    // Turn 2's OWN utterance finishes.
    const secondId = mocks.speakResponseMock.mock.results[1].value as number;
    act(() => {
      fireToAll({ type: 'end', agent_id: AGENT_ID, utterance: {}, utterance_id: secondId });
    });
    expect(mocks.markAgentReplyCompleteMock).toHaveBeenCalledTimes(2);
```
REPLACE:
```tsx
    act(() => { onAgentReply('First reply.'); });
    act(() => { onAgentReply('Second reply.'); });
    // BF-918 M6 (#1626): 0, not 1. Turn 1's 'end' lands after turn 2 took the turn,
    // so completing on it would end turn 2's turn (see the test above).
    expect(mocks.markAgentReplyCompleteMock).toHaveBeenCalledTimes(0);

    // Turn 2's OWN utterance finishes.
    const secondId = mocks.speakResponseMock.mock.results[1].value as number;
    act(() => {
      fireToAll({ type: 'end', agent_id: AGENT_ID, utterance: {}, utterance_id: secondId });
    });
    expect(mocks.markAgentReplyCompleteMock).toHaveBeenCalledTimes(1);
```

### 7.4 `ui/src/audio/meetingVoice.ts` (A1: the meeting wait, the second consumer of M5's `final`)

Pair 1:

SEARCH:
```ts
      if (utteranceId !== undefined
        ? e.utterance_id !== utteranceId
        : e.agent_id !== reply.agent_id) return;
      finish();
```
REPLACE:
```ts
      if (utteranceId !== undefined
        ? e.utterance_id !== utteranceId
        : e.agent_id !== reply.agent_id) return;
      // BF-918 M7 (#1626, review round 1): under AD-1071 pipelining every sentence
      // fires an 'end' with the reply's id, and `final: false` says more of the reply
      // will play (M5). Finishing on it cleared the speaking id, which is the
      // meeting's echo gate (ProfileChatTab's `canListen`), while the rest of the
      // reply played, and moved the label and the reveal on early. The last sentence,
      // or a stop while one plays, carries `final: true`; every other 'end' carries no
      // `final`. A stop between two sentences emits no further event: the safety
      // timeout, sized for the whole reply, ends the wait (BF-918's R32).
      if (e.type === 'end' && e.final === false) return;
      finish();
```

### 7.5 `ui/src/audio/__tests__/meetingVoice.test.ts` (A1)

Pair 1 (the fake's `fire` carries `final`):

SEARCH:
```ts
  const fire = (e: { type: SpeechEventType; agent_id?: string; utterance_id?: number; reason?: string }): void => {
```
REPLACE:
```ts
  const fire = (e: { type: SpeechEventType; agent_id?: string; utterance_id?: number; reason?: string; final?: boolean }): void => {
```

Pair 2 (two cases, before `createVoiceProfileResolver`):

SEARCH:
```ts
describe('createVoiceProfileResolver', () => {
```
REPLACE:
```ts
/** BF-918 M7 (#1626, review round 1): under AD-1071 pipelining every sentence of a
 *  reply fires an 'end' with the reply's id, and `final: false` says more of it will
 *  play (M5). The wait for a reply ends on its last sentence, so the speaking id (the
 *  meeting's echo gate), the label and the reveal hold until then. */
describe('BF-918 M7: a pipelined reply holds the speaking slot until its last sentence', () => {
  it('test_bf918_m7_non_final_end_does_not_advance_or_clear_speaking', async () => {
    const fake = makeFake({ mintIds: true });
    const p = speakRepliesSequentially([r('alpha'), r('bravo')], fake.deps);
    await tick();
    const id = fake.speakCalls[0].utteranceId;
    fake.fire({ type: 'start', agent_id: 'alpha', utterance_id: id });
    fake.fire({ type: 'end', agent_id: 'alpha', utterance_id: id, final: false });
    await tick();
    await tick();
    // Before the fix: ['alpha', 'bravo'], with alpha's second sentence still to play.
    expect(fake.speakCalls.map((c) => c.agentId)).toEqual(['alpha']);
    expect(fake.speakingChanges).toEqual(['alpha']);
    expect(fake.utteranceEnds).toEqual([]);
    fake.fire({ type: 'start', agent_id: 'alpha', utterance_id: id });
    fake.fire({ type: 'end', agent_id: 'alpha', utterance_id: id, final: true });
    await tick();
    expect(fake.speakCalls.map((c) => c.agentId)).toEqual(['alpha', 'bravo']);
    expect(fake.speakingChanges).toEqual(['alpha', null, 'bravo']);
    expect(fake.utteranceEnds).toEqual(['alpha']);
    // A single-call reply's 'end' carries no `final` and still ends its wait.
    fake.fire({ type: 'end', agent_id: 'bravo', utterance_id: fake.speakCalls[1].utteranceId });
    await p;
    expect(fake.utteranceEnds).toEqual(['alpha', 'bravo']);
  });

  it('test_bf918_m7_safety_timeout_still_ends_a_wait_whose_last_sentence_never_ends', async () => {
    // A stop between two sentences emits no further event (BF-918 R32).
    vi.useFakeTimers();
    const fake = makeFake({ mintIds: true, utteranceTimeoutMs: 60000 });
    const p = speakRepliesSequentially([r('a'), r('b')], fake.deps);
    await vi.advanceTimersByTimeAsync(0);
    expect(fake.speakCalls).toHaveLength(1);
    fake.fire({ type: 'end', agent_id: 'a', utterance_id: fake.speakCalls[0].utteranceId, final: false });
    await vi.advanceTimersByTimeAsync(59999);
    // Before the fix: 2 (the first sentence's 'end' ended the wait).
    expect(fake.speakCalls).toHaveLength(1);
    expect(fake.speakingChanges).toEqual(['a']);
    await vi.advanceTimersByTimeAsync(1);
    await vi.advanceTimersByTimeAsync(0);
    expect(fake.speakCalls).toHaveLength(2);
    expect(fake.utteranceEnds).toEqual(['a']);
    fake.fire({ type: 'end', agent_id: 'b', utterance_id: fake.speakCalls[1].utteranceId });
    await vi.advanceTimersByTimeAsync(0);
    await p;
  });
});

describe('createVoiceProfileResolver', () => {
```

## 8. Tracking

The `PROGRESS.md` pairs are substrings of its one-line BF-918 entry (line 5); the `DECISIONS.md` pair is a substring of its BF-918 entry (line 694). None contains a line break, and each occurs once at the base (§11). A tool that matches only whole lines must be told to match the substring. Set the date to the commit date.

**`PROGRESS.md`** (pair 1):

SEARCH:
```markdown
its join timeout bounds the silence between two sentences rather than the reply's length, and a stop between two sentences frees it at once.
```
REPLACE:
```markdown
its join timeout bounds the silence between two sentences rather than the reply's length, and a stop between two sentences frees it at once. M6 and M7 (2026-10-24): an older reply's `end` no longer completes a newer reply's turn in the same conversation arm, and in conversation mode with pipelining on a reply's turn completes on its last sentence's `end` (`final`), not its first, so barge-in works for the whole reply and the silence timer starts after it. The BF-300 PTT gate also stays closed between two sentences of one reply, for at most 5 s after a sentence's `end` (`PTT_SENTENCE_GAP_MS`), so a stop between two sentences reopens it; `ProfileChatTab.bf918.test.tsx` C13 to C21. Review round 1: opening another crew member's profile mid-reply no longer leaves the new agent's PTT gate closed (it resets with its agent's subscription), and in a meeting the speaking id, which gates the open mic, now holds until a reply's last sentence (`meetingVoice.ts` ignores an `end` with `final: false`, the second consumer of M5's field); C22 to C24 and two `meetingVoice.test.ts` cases.
```

**`PROGRESS.md`** (pair 2):

SEARCH:
```markdown
#1626 stays open for slices M6 (an older reply's `end` no longer completes a newer reply's turn in the same conversation arm) and M7 (in conversation mode, a pipelined reply's turn completes on its last sentence's `end`, not its first), and for
```
REPLACE:
```markdown
#1626 stays open for
```
(The text then reads "#1626 stays open for the Captain's live measurement, which runs once after M4 and M5 have merged; ...".)

**`DECISIONS.md`:**

SEARCH:
```markdown
it would cut a last sentence spoken by the browser fallback), and a new event type.
```
REPLACE:
```markdown
it would cut a last sentence spoken by the browser fallback), and a new event type. M6 and M7 (2026-10-24): `ProfileChatTab`'s reply listener retires without completing on any `end` once a newer reply of its arm has taken the turn (its `dropped` branch already did), and ignores an `end` whose `final` is `false`. The BF-300 PTT gate stays closed on `final: false`, bounded by `PTT_SENTENCE_GAP_MS` (5 s, a constant like BF-655's ceiling), because a stop between two sentences emits no further event. Rejected: retiring older listeners when a newer reply arrives (it turns the reviewed `dropped` guard into dead code), a turn token on `markAgentReplyComplete` (a public signature change), a gap bound on the turn itself (a slow synthesis would complete it mid-reply), and keeping the BF-718 in-flight key until the last sentence (it errs toward waiting on an `end` that nothing emits; registered as R33). Review round 1: the PTT gate also resets with its agent's subscription (an agent change re-points the composer without a remount, and the next subscription ignores the old agent's events), and the meeting sequencer's wait (`meetingVoice.ts`) ignores `final: false` too. Rejected: per-agent gate state across an agent change (a BF-300 redesign; the return-mid-sentence case is registered as R36) and a gap timer on the meeting wait (a meeting has no ordinary stop between two sentences, and its whole-reply safety timeout bounds one).
```

No `docs/development/roadmap.md` change (no new BF).

**#1626's acceptance checklist** (the orchestrator edits the issue):

- `[x] M6: an older reply's end no longer completes a newer reply's turn in the same conversation arm (does not gate the live acceptance; built with M7).` Tick it at the merge.
- `[x] M7: in conversation mode with pipelining on, a reply's turn completes on its last sentence's end (final), not its first (found while drafting M5; built with M6; until it lands, the live acceptance's replies are typed in the chat).` Tick it at the merge; from then on the live acceptance's replies may also be spoken in conversation mode.
- In #1626's register: mark R25 closed for the PTT gate (M7) with the in-flight key half moved to R33, and record R32 to R36 from §18 (R32 as extended by A1; R35 and R36 from A1).

## 9. What this does NOT change

- `voice.ts`, `voiceChunking.ts`, `speechQueueStore.ts`, `conversationController.ts` and their events: no new field, event or export. `final` is read, never produced, here.
- The reply listener's `dropped` branch, `retire`, `pendingReplies`, the arm's cleanup and `onStateChange` retirement (BF-918 review rounds 2 to 5).
- The BF-718 in-flight key clear (`ProfileChatTab.tsx:1385-1393`, R33), BF-655's 45 s ceiling and its re-arm on `start`, the effect's cleanup of `ttsWatchdogRef`.
- The other `onSpeechEvent` consumers, which still act on every sentence's `end`: `wakeWord.ts` (R34), `useLipSyncCapture.ts`, `CrewVRM.tsx`, `ParametricAvatar.tsx`, `ModulationIndicator.tsx` (per-sentence mouth and modulation are correct per sentence). A1 takes the meeting sequencer (`meetingVoice.ts`) out of this list.
- `useMeetingVoice.ts`, the conversation controller and the meeting arm's predicate: no code change. Through A1's `meetingVoice.ts` condition, `speakingAgentId`, the speaking label and the BF-621 reveal advance on a reply's last `end`; the AD-915 order, the batch supersession (`shouldContinue`), the owner-scoped flush, the safety timeout and the next reply's hold by M5's arbiter are unchanged.
- The meeting branch of the arm effect (`:2030-2060`): it has no `onAgentReply`.
- Pipelining stays default-off. No config, no generated file, no Python.

## 10. Mutation rows (10 TypeScript; whole stripped lines, each occurring once in its file after §7)

Tier HIGH. Run each row on the applied tree after an unmutated baseline run passes, and restore the file before the next row. From `ui/`:

```
npx vitest run src/components/profile/__tests__/ProfileChatTab.bf918.test.tsx src/components/profile/__tests__/ProfileChatTab.bf767.test.tsx src/audio/__tests__/meetingVoice.test.ts
```

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| M6-1 | `ui/src/components/profile/ProfileChatTab.tsx` | `if (replyTurn !== ourTurn) {` | `if (false) {` | C13, C14, bf767 `does not complete the new turn on the cancelled utterance's end`, bf767 `completes the turn on its own utterance end` |
| M7-1 | `ui/src/components/profile/ProfileChatTab.tsx` | `if (event.final === false) return;` | `if (false) return;` | C15, C16 (both orders), C18 |
| M7-2 | `ui/src/components/profile/ProfileChatTab.tsx` | `if (event.final === false) return;` | `if (event.final !== true) return;` | C17, C13 (their single-call `end`s carry no `final`, so the turn never completes), C1, C11 |
| M7-3 | `ui/src/components/profile/ProfileChatTab.tsx` | `} else if (event.type === 'end' && event.final === false) {` | `} else if (false) {` | C19, C20, C21 |
| M7-4 | `ui/src/components/profile/ProfileChatTab.tsx` | `}, PTT_SENTENCE_GAP_MS);` | `}, PTT_TTS_WATCHDOG_MS);` | C20 (the gate is still closed after 5 s) |
| M7-5 | `ui/src/components/profile/ProfileChatTab.tsx` | `clearTimeout(ttsWatchdogRef.current ?? undefined);` | `void 0;` | C21 (the first sentence's orphaned 45 s ceiling opens the gate during the second sentence) |
| M7-6 | `ui/src/components/profile/ProfileChatTab.tsx` | `ttsActiveRef.current = false; // the composer mic's click guard reads this` | `void 0;` | C22 `[between two sentences]`, C22 `[while a sentence plays]` (a2's press is refused) |
| M7-7 | `ui/src/components/profile/ProfileChatTab.tsx` | `setTtsActive(false); // the MicIndicator's 'muted' ring reads this` | `void 0;` | C22 `[between two sentences]`, C22 `[while a sentence plays]` (`muted` stays) |
| M7-8 | `ui/src/audio/meetingVoice.ts` | `if (e.type === 'end' && e.final === false) return;` | `if (false) return;` | C24, `test_bf918_m7_non_final_end_does_not_advance_or_clear_speaking`, `test_bf918_m7_safety_timeout_still_ends_a_wait_whose_last_sentence_never_ends` |
| M7-9 | `ui/src/audio/meetingVoice.ts` | `if (e.type === 'end' && e.final === false) return;` | `if (e.type === 'end' && e.final !== true) return;` | `test_waits_for_previous_end_before_next`, `test_bf621_utterance_start_fires_before_speak` (their `end`s carry no `final`) |

M7-1 and M7-2 mutate the same line in two ways; run them as two rows. M7-8 and M7-9 likewise. The cleanup's two writes (M7-6, M7-7) carry trailing comments so that each is a unique whole line; no row for A1's comment lines or the tests' `Agent` literal. Under M7-9 several other `meetingVoice.test.ts` cases wait on `await p` until vitest's per-test timeout; the named killers fail by assertion first.

No row for: `retire();` and `return;` in M6's block (the guard's line is M6-1), the gap timer's body (`ttsWatchdogRef.current = null;`, `ttsActiveRef.current = false;`, `setTtsActive(false);` each occur more than once in the file; C20's final assertion covers the body), `const PTT_SENTENCE_GAP_MS = 5000;` (M7-4 covers the ceiling's use), and the test file's `deferPause` double (test-only). BF-767's mutant (drop `if (claimed && event.utterance_id !== ourUtteranceId) return;`) stays killed by bf767 `does not complete the new turn on the cancelled utterance's end` under the new expectation: turn 2's listener would then complete on turn 1's `end` (1, not 0). That line is not a row of this campaign, because this change does not touch it.

## 11. Verified Against Codebase (2026-10-24, worktree `m67-consult`, detached at `origin/main` `026a682f`, clean)

```
git log --oneline -3
  026a682f Merge pull request #1647 from seangalliher/fix/bf918-m4m5-20261024-88447c7e
wc -l ProfileChatTab.tsx 3176; ProfileChatTab.bf918.test.tsx 505; conversationController.ts 624; voice.ts 1024
ProfileChatTab.tsx:34     import { onSpeechEvent } from '../../audio/voice';
ProfileChatTab.tsx:241-246  BF-655 comment; const PTT_TTS_WATCHDOG_MS = 45000;
ProfileChatTab.tsx:330-342  ttsActiveRef, ttsActive, ttsWatchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null)
ProfileChatTab.tsx:563-600  BF-300 gate: 565 agent filter; 566-581 'start' (571 clear, 572 arm 45 s); 582-590 'end' clears; 592-599 cleanup; deps [agentId]
ProfileChatTab.tsx:763    const speechInFlightRef = useRef(new Set<string>());
ProfileChatTab.tsx:1385-1393  in-flight key clear on every 'end' or 'dropped' of the agent
ProfileChatTab.tsx:2083-2087  pendingReplies, retirePendingReplies, let replyTurn = 0
ProfileChatTab.tsx:2088-2226  armOpts: agentId, historyProvider, onTranscript, onAgentReply, onStateChange (no canListen, no bargeInEnabled)
ProfileChatTab.tsx:2108   const ourTurn = ++replyTurn;
ProfileChatTab.tsx:2140-2153  audio off and lost-claim-not-in-flight: markAgentReplyComplete() at once
ProfileChatTab.tsx:2170-2181  ourUtteranceId, completed, retire, complete
ProfileChatTab.tsx:2190-2195  'dropped' branch; 2192 if (replyTurn !== ourTurn) { retire(); return; }
ProfileChatTab.tsx:2196-2206  'end' branch (§7.1 pair 3's SEARCH)
ProfileChatTab.tsx:2209-2217  pendingReplies.add(retire); speakResponse(...); undefined -> complete()
ProfileChatTab.tsx:2219-2225  onStateChange: 'inactive' -> retirePendingReplies()
ProfileChatTab.tsx:2785   if (ttsActiveRef.current) { ... mic press ignored ... }
ProfileChatTab.tsx:3001-3009  MicIndicator state: processing ? 'processing' : ttsActive ? 'muted' : ...
MicIndicator.tsx:115      data-testid="mic-indicator-ring-muted"
conversationController.ts:205-219  _setState: agent_speaking attaches barge-in, leaving it detaches; no transition table
conversationController.ts:339  onSpeechStart: () => _onVadSpeechStart(owner)
conversationController.ts:348-367  barge-in only in agent_speaking: _stopSpeaking(); _cancelSilenceTimer; _setState('listening')
conversationController.ts:369-373  _onTranscript returns only when not owned or 'inactive'
conversationController.ts:433-435  _setState('agent_speaking') then onAgentReply(replyText)
conversationController.ts:450-454  markAgentReplyComplete: no-op unless 'agent_speaking'
conversationController.ts:460-472  _enterSilencePending: 30 s timer
voice.ts:59, 85           SpeechEventType; final?: boolean on SpeechEvent
voice.ts:92-102           onSpeechEvent adds the listener; _fire passes the same event object to every listener
voice.ts:261              const TTS_PREFETCH_LOOKAHEAD = 1;
voice.ts:278-280          _finalField: {} when last undefined, else { final: last || _activeUtteranceId !== utterance_id }
voice.ts:353-392          speakResponse enqueues; interactive pre-empts only unstarted narration
voice.ts:437-486          _awaitEntry: ignores final === false (471), GUARD 2 (484)
voice.ts:579-603          pipelined branch; 585 _endSentenceQueueWait = endWait; 591 index === last; 601 played === 0 -> dropped
voice.ts:607              single-call path (no `last`, so no final)
voice.ts:725-775          _playPreparedSpeech: 761 'play' -> 'start'; 758 'end' with _finalField; 775 'pause' -> _finish(true)
voice.ts:883-890, 915     browser paths' 'end' carry _finalField(last, ...)
voice.ts:937-962          stopSpeaking: 938 flush, 942 _activeUtteranceId = null, 950-953 pause, 959-961 endWait
voiceChunking.ts:84-124   runPrefetchQueue: prepare k+1 before play(k) (109), play(k+1) after play(k) resolves (111)
ProfileChatTab.bf918.test.tsx:61-187  harness (MediaDouble 86-101, pause 97; flush 60 turns 107-109; arm, captainSays, bargeIn, answerSynthesis, endAudio; fetch stub 157-175 with sentence_pipelining_enabled: false)
ProfileChatTab.bf918.test.tsx:489-505  C12, the file's last case
ProfileChatTab.bf767.test.tsx:121-132  speakResponse mock fires the previous utterance's 'end' first
ProfileChatTab.bf767.test.tsx:159-191  the two tests §7.3 updates
ProfileChatTab.bf764.test.tsx:383-384  vi.useFakeTimers({ shouldAdvanceTime: true }) with the real component ("without it the harness starves")
PROGRESS.md:5             "its join timeout bounds the silence ... frees it at once." (1 line); "#1626 stays open for slices M6 (...) and M7 (...), and for" (1 line)
DECISIONS.md:694          "it would cut a last sentence spoken by the browser fallback), and a new event type." (1 line)
```

### 11.1 A1 (2026-10-25, worktree `m67-consult`, detached at the candidate `ebaf69b9`, tree `0e41717a`; parent `3860842d`)

```
git diff --stat 3860842d ebaf69b9   ProfileChatTab.tsx 43+; bf767 test 18; bf918 test 237; meetingVoice.ts and its test untouched (base = candidate there)
wc -l ProfileChatTab.tsx 3219; ProfileChatTab.bf918.test.tsx 740; meetingVoice.ts 225; meetingVoice.test.ts 478
ProfileChatTab.tsx:571-625   BF-300 gate effect: 573 agent filter; 590-606 gap branch; 617-625 cleanup (clears ttsWatchdogRef only); deps [agentId]
ProfileChatTab.tsx:619       "// BF-655: never leave a dangling watchdog timer on unmount." (1 hit in ui/src)
ProfileChatTab.tsx:343-344   ttsActiveRef, [ttsActive, setTtsActive]; writes only at 575-609 (8); readers 2828 (click guard), 3048 (MicIndicator state)
ProfileChatTab.tsx:2828-2832 if (ttsActiveRef.current) { console.info(`BF-300: mic press ignored for agent ${agentId} ...`); return; }
ProfileChatTab.tsx:3044      the only <MicIndicator in ui/src outside tests; MicIndicator.tsx:62 "mic-indicator", :115 "mic-indicator-ring-muted"
ProfileChatTab.tsx:1107-1118 useMeetingVoice({ meetingActive, participantAgentIds, owner: speechOwner, scopeKey: activeThreadId }); speakingAgentIdRef.current = speakingAgentId
ProfileChatTab.tsx:2052-2085 meeting arm: canListen: () => speakingAgentIdRef.current == null (2071); submitTranscript; no onAgentReply
AgentProfilePanel.tsx:68, 740  export function AgentProfilePanel(); <ProfileChatTab agentId={agentId} ... /> (no key)
CompactApp.tsx:229            <ProfileChatTab agentId={derivedAgentId} ... /> (no key); MobileShell.tsx:175 <ProfileChatTab agentId={yeoId} ... />
useStore.ts:1616, 1664, 1820, 1904  agents: new Map(); activeProfileAgent: null; callAudioEnabled: true; openAgentProfile
types.ts:75-94                interface Agent (the C22 literal's fields)
package.json:27-28            react, react-dom ^19.0.0
meetingVoice.ts:105-154       _speakAndWait: 127 terminal filter; 138-141 attribution then finish(); 143-144 safety timeout from computeUtteranceTimeout(reply.text)
meetingVoice.ts:158-192       speakRepliesSequentially: 177 onSpeakingChange(id); 181 await _speakAndWait; 184 onSpeakingChange(null); 190 onUtteranceEnd
useMeetingVoice.ts:17-32, 155-175  options (meetingActive, participantAgentIds, owner, scopeKey); speak = speakResponse(..., 'narration', owner); subscribe: onSpeechEvent; onSpeakingChange -> setSpeakingAgentId
conversationController.ts:90-101, 399-410, 433, 350  submitTranscript and canListen options; the submit path ends in _enterSilencePending; the only _setState(owner, 'agent_speaking'); barge-in only there
voice.ts:464-475              the arbiter's wait ignores an 'end' with final === false (471)
meetingVoice.test.ts:37-89, 97, 99-101, 363-388, 427  makeFake and fire (81); tick; afterEach useRealTimers; the fake-timer idiom; describe('createVoiceProfileResolver'
ProfileChatTab.bf918.test.tsx:20, 51-58, 122-144, 163-164, 718-740  the imports Pairs 5 and 6 edit; arm..endAudio; mic mode stored for a1 only; C21 and the describe's close
gh issue view 1626 --comments | grep -o -E "\bR(3[0-9]|4[0-9])\b"   R30, R31 only (R32 to R34 are this contract's; R35, R36 are A1's)
```

## 12. Absence Verified (2026-10-24)

```
CLAIM: the controller's barge-in is the only production caller of stopSpeaking
RUN:   Grep "stopSpeaking" ui/src (excluding __tests__)
FOUND: conversationController.ts:58 (import as _stopSpeaking), :356 (the call, in _onVadSpeechStart); voice.ts:937 (definition); the rest are comments
HOLDS: yes; a stop between two sentences in production is a barge-in, which moves the controller itself

CLAIM: `final` is read nowhere but the arbiter before this change
RUN:   Grep "\.final\b" ui/src (excluding __tests__)
FOUND: voice.ts:471; transformersStt.ts:389-390 (an STT job's own field)
HOLDS: yes

CLAIM: the in-flight key set has one reader
RUN:   Grep "speechInFlightRef|speechKeyFor" ProfileChatTab.tsx
FOUND: :763 (declaration), adds :1146, :1487, :1983, :2211; delete :1390; has :2150
HOLDS: yes (R33's reach is :2150 only)

CLAIM: no `?raw` source scan pins a line this change edits, and none forbids text it adds
RUN:   Grep "ProfileChatTab(\.tsx)?\?raw" ui/src; then the assertions of each hit
FOUND: voice.balancedEnd.test.tsx:393-401 (PTT_TTS_WATCHDOG_MS = 45000, ttsWatchdogRef, setTimeout(...PTT_TTS_WATCHDOG_MS), clearTimeout(ttsWatchdogRef.current): all kept);
       audioControl.test.tsx:1063-1064 (forbids speechSynthesis.cancel, _activeAudio.pause, callMicEnabled, toggleOutputAudio...stopSpeaking within 500 chars: none added; toggleOutputAudio is at :915 and :2693);
       voicewave.test.tsx (arm effect strings and deps array, unchanged; an emoji guard over the file: none added); a2ui, ad1062, ad1075, threadTranscript (other regions)
HOLDS: yes

CLAIM: no ProfileChatTab test drives a pipelined reply today
RUN:   Grep "sentence_pipelining_enabled: true|mic-indicator-ring-muted|final: false" ui/src
FOUND: voice.pipelining.test.tsx:184, 226 (voice only); MicIndicator.tsx:115; transformersStt.ts:277
HOLDS: yes

CLAIM: only the two bf767 tests expect an older reply's 'end' to complete after a newer onAgentReply
RUN:   Grep "onAgentReply\(" ui/src/**/__tests__ (13 hits, 4 files), then read each multi-reply test
FOUND: bf767.test.tsx:163/169, 181/182 (the two, updated in §7.3), 196 (one reply); bf290.test.tsx:189, 213 (the first reply's 'end' lands before the second reply), 232 (audio off);
       bf718.test.tsx:482, 515, 532 (one reply each); audioControl.test.tsx:824, 862 (one reply each)
HOLDS: yes

CLAIM: the reply listener and the PTT gate are the only consumers whose behaviour changes, and their own consumers are the controller and the composer mic
RUN:   Grep "onSpeechEvent\(" and "onSpeechEvent[^(]" ui/src (excluding __tests__); Grep "ttsActiveRef|ttsActive\b" ProfileChatTab.tsx
FOUND: listeners in useLipSyncCapture.ts:62, wakeWord.ts:187, voice.ts:459, CrewVRM.tsx:502, ModulationIndicator.tsx:28, ParametricAvatar.tsx:49, ProfileChatTab.tsx:564, 1385, 2182; useMeetingVoice.ts:161 passes it to meetingVoice.ts;
       ttsActiveRef read at :2785 only; ttsActive read at :3005 only
HOLDS: yes (§9 lists the unchanged ones)

CLAIM: the new names are free
RUN:   Grep "PTT_SENTENCE_GAP_MS|final === false|replyTurn !== ourTurn" ui/src
FOUND: voice.ts:471 (`event.final === false`, another file); ProfileChatTab.tsx:2192 (`if (replyTurn !== ourTurn) { retire(); return; }`, a different whole line from M6-1's)
HOLDS: yes; every §10 row is a unique whole stripped line after §7

CLAIM: #1626's register ends at R31
RUN:   gh issue view 1626 --comments | grep -o -E "\bR(3[0-9]|4[0-9])\b"
FOUND: R30, R31 only
HOLDS: yes; §18 uses R32 to R34
```

### 12.1 A1 (2026-10-25)

```
CLAIM: the speech-event `final` has no other non-test reader (meetingVoice.ts consumed the same 'end's but read no `final`)
RUN:   Grep "\.final\b" ui/src (excluding __tests__)
FOUND: transformersStt.ts:389, 390 (an STT job's own field); voice.ts:471; ProfileChatTab.tsx:590, 2247
HOLDS: yes; A1 makes meetingVoice.ts the fourth

CLAIM: speakRepliesSequentially has one production caller, and useMeetingVoice one production use
RUN:   Grep "speakRepliesSequentially|useMeetingVoice\(" ui/src
FOUND: useMeetingVoice.ts:155; ProfileChatTab.tsx:1107; the rest are tests (meetingVoice.test.ts; useMeetingVoice.test.tsx mocks the sequencer) and comments (staggerReplies.ts:14, ProfileChatTab.ad976.test.tsx:59)
HOLDS: yes

CLAIM: no existing test feeds `final: false` to the meeting wait, so A1's meetingVoice.ts line changes no existing test's outcome
RUN:   Grep "sentence_pipelining_enabled: true|final: false" ui/src
FOUND: voice.pipelining.test.tsx:184, 226 (voice only); transformersStt.ts:277 (STT); ProfileChatTab.tsx:250, 2240 (comments)
HOLDS: yes (bf918's stub uses a variable; its meeting case is the new C24)

CLAIM: in a meeting nothing ordinary stops a started reply between two sentences
RUN:   Grep "flushSpeechQueue|stopSpeaking\(|disarmConversationMode|armConversationMode\(" ui/src (excluding __tests__); Grep "agent_speaking'\)" conversationController.ts
FOUND: stopSpeaking: voice.ts:937 (definition), conversationController.ts:356 (barge-in, in agent_speaking only, :350); agent_speaking set at :433 only (the 1:1 path); flushSpeechQueue (voice.ts:502-511) drops unstarted entries only: useMeetingVoice.ts:90, ProfileChatTab.tsx:1469, voice.ts:938
HOLDS: yes; the causes left are GUARD 2 and a 1:1 barge-in on another surface (R32)

CLAIM: the gate's ref and state are written only inside the gate effect, so its cleanup is the one place an agent change can leave them
RUN:   Grep "ttsActiveRef|ttsActive\b|setTtsActive" ProfileChatTab.tsx
FOUND: declarations 343-344; writes 575-576, 582-583, 600-601, 608-609; reads 2828, 3048
HOLDS: yes

CLAIM: no `?raw` scan reads meetingVoice.ts beyond the emoji guard, and none pins the ProfileChatTab cleanup lines
RUN:   Grep "meetingVoice(\.ts)?\?raw" ui/src; Grep "ttsActive|ttsWatchdogRef|BF-655" ui/src/**/__tests__
FOUND: meetingVoice.test.ts:18 (emoji guard, 447-451); voice.balancedEnd.test.tsx:391-401 (ttsWatchdogRef, clearTimeout(ttsWatchdogRef.current): kept); the rest are a local mirror (304-343) and docs
HOLDS: yes

CLAIM: A1's new mutation lines are unique whole lines
RUN:   Grep "the composer mic's click guard reads this|the MicIndicator's 'muted' ring reads this" ui/src; Grep "final" meetingVoice.ts
FOUND: none before A1; meetingVoice.ts has 1 "final" (the word `finally`, :183)
HOLDS: yes
```

## 13. Prior Art and Blind Spots

A bug-fix slice inside BF-918, so the bounded external search was skipped except for one lookup behind blind spot 1, and the overdue reviews in `docs/research/reference-projects.md` were considered and deferred. Internal prior art used: BF-767 (correlate on the utterance), BF-718 (the claim and the in-flight key), BF-655 (the gate's watchdog), BF-918 review rounds 2 and 3 (the `dropped` branch's turn guard, retirement with the arm), M5's `final` (decision 7 of the M4/M5 contract named M7 as its second consumer).

Blind spots found and settled:

1. **People take the floor at sentence ends.** Conversation analysis places speaker change at transition-relevance places, the possible completion points of a turn unit, where other speakers may self-select ([Sacks, Schegloff and Jefferson 1974, summarised on the EMCA wiki](https://emcawiki.net/Turn-taking); [turn construction unit](https://en.wikipedia.org/wiki/Turn_construction_unit)). For a pipelined reply those are the gaps between sentences. So a Captain's PTT press or barge-in is likeliest exactly in a gap, which raises R25's reach (decision 4) and is why the gate's gap needs a short bound (decision 5). Adopted.
2. **A stop between two sentences emits no further event.** M7's turn would wait for an `end` that never comes. In production that stop is barge-in, which moves the controller itself (§12); GUARD 2's later dispatch is R32. The PTT gate gets its bound (decision 5).
3. **Both orders of a stopped sentence's `end`.** The double fires `pause` inside `pause()`; a browser queues it. In the synchronous order the turn completes first and barge-in then cancels the silence timer and enters `listening`; in the deferred order `markAgentReplyComplete` finds `listening` and does nothing. C16 runs both, so no claim depends on the order (§17 has the optional browser probe).
4. **A superseded listener that never sees its own id again** (stopped between sentences, or one that lost the claim) would live to its arm's end; M6 retires it on any `end` (decision 2).
5. **The tests that pinned the defect** (bf767): updated with the reason inline (decision 6).

6. **The parent decides the lifetime, not the component** (A1, finding 1). A composer re-pointed at another agent without a remount (`AgentProfilePanel`, `CompactApp`) ends a subscription but not the component, so state that belongs to the subscription must end with it. All three parents checked (§11.1).
7. **A field added for one consumer has others** (A1, finding 2). M5 enumerated the readers of `final`; `meetingVoice.ts` read no `final` but consumed the same `end`s through an injected `subscribe`. The enumeration that finds it is every listener of the event, including injected subscriptions, not every reader of the field.
8. **A return to an agent while it speaks, and BF-300's per-agent scope.** The return is R36. While another agent is shown, the shown composer's gate ignores the speaking agent's audio: BF-300's design, the limit AD-922 names for meetings. Considered, not changed.
9. No external search for A1: ProfileChatTab and sequencer plumbing with no outside analogue; the reference-project reviews stay deferred as above.

## 14. Diff Reviewer: properties to verify

Consumers: the conversation controller (`markAgentReplyComplete`, barge-in, the silence timer), the composer mic's click handler and the MicIndicator, every parent that mounts or re-points the composer (`AgentProfilePanel`, `CompactApp`, `MobileShell`), the meeting sequencer's consumers (`useMeetingVoice`'s `speakingAgentId`, the meeting arm's `canListen` at `ProfileChatTab.tsx:2071`, the speaking label and the BF-621 reveal), and every test that drives `ProfileChatTab`'s reply listener (bf290, bf718, bf767, audioControl, bf918) or the sequencer (meetingVoice, useMeetingVoice, ad976).

1. A reply's completion listener completes the controller's turn only while its reply is the newest of its arm; once a newer reply has taken the turn, its next `end` of any kind retires it without completing. Its `dropped` branch is unchanged.
2. With pipelining on, no `end` with `final: false` completes a turn or opens the PTT gate. Every `end` without `final` (pipelining off, single-sentence replies, browser and no-engine paths, mocks) behaves exactly as before, for both.
3. A conversation turn completes on exactly one of: its reply's last sentence's `end`; the `end` of a sentence stopped while it played; its own `dropped` while it is newest; the audio-off, lost-claim-not-in-flight or no-engine paths (unchanged). A barge-in at any point of a pipelined reply ends in `listening` with no silence timer running, whatever the order of the stopped sentence's `end` relative to the state change.
4. The PTT gate is closed from a sentence's `start` until its reply's last `end`, except: no next `start` within `PTT_SENTENCE_GAP_MS` of a `final: false` `end` opens it (logged at info with the agent id); BF-655's 45 s ceiling still runs from each `start`. Exactly one gate timer is pending at a time (the gap timer replaces the sentence's ceiling, and the next `start` replaces the gap timer); the effect's cleanup clears whichever is pending.
5. No new export from `ProfileChatTab.tsx` or `voice.ts`; no change to `voice.ts`, the controller or any event.
6. The bf767 tests keep BF-767's property (turn 2 never completes on turn 1's `end`) and say why their counts changed; no test was deleted or skipped.
7. New tests synchronise with `waitFor`, `act` and microtask flushes, never wall-clock sleeps; C20 and C21 restore real timers in `finally`.
8. No added text matches the `?raw` scans of §12 (no `speechSynthesis.cancel`, `_activeAudio.pause`, `callMicEnabled`, emoji).
9. A1: a change of `agentId` with the gate held, during a sentence or between two, leaves the new agent's gate open at once (no `muted` ring; a press is not refused), through the real `AgentProfilePanel` navigation (C22). A re-render that keeps `agentId` (C23) and a newer `start` of the same agent do not open it. The cleanup still leaves no gate timer pending (property 4).
10. A1: in a meeting no `end` with `final: false` ends a reply's wait: `speakingAgentId`, the label and the reveal hold until the reply's last `end`, so the open mic refuses transcripts while any sentence of the reply plays and accepts one after it (C24). An `end` without `final`, `dropped`, the attribution rules and the safety timeout behave as before; after a non-final `end` with no further event the timeout still ends the wait. The AD-915 order and the next reply's audio, held by the arbiter, are unchanged.
11. A1 adds no export, signature, event or config, and changes no test outside the four test files named in the header.

## 15. Acceptance criteria

- [ ] `npx vitest run src/components/profile src/audio src/__tests__/ProfileChatTab` and `npx tsc -b` pass from `ui/`; CI `ui-tests` passes.
- [ ] The tests-first table of §4 holds on the base, or each difference is reported with the observed assertion.
- [ ] The 10 rows of §10 are killed.
- [ ] M6: an older reply's `end` does not complete a newer reply's turn, with pipelining off (C13) and on (C14).
- [ ] M7: a pipelined reply's turn ends on its last sentence (C15); barge-in works during its second sentence in both event orders (C16); a one-sentence reply is unchanged (C17); a barge-in between sentences leaves the next turn unaffected (C18).
- [ ] R25: the PTT gate stays closed between sentences (C19), reopens within 5 s after a stop between them (C20), and follows the playing sentence's ceiling (C21).
- [ ] A1: an agent change between two sentences or during one leaves the new agent's mic ungated (C22, both phases); a re-render for the same agent keeps the gate (C23); in a meeting the speaking id holds until a reply's last sentence and the open mic refuses transcripts until then (C24 and the two `meetingVoice.test.ts` cases).
- [ ] The live acceptance (BF-918 §16) may speak its replies in conversation mode once this merges.
- [ ] All changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Live-vessel premise checks

None is needed to build. One optional read after the live acceptance: the `bf918:sentence-gap` values it already collects (BF-918 §16). If any is near 5000 ms, revisit `PTT_SENTENCE_GAP_MS` (decision 5). A1 adds none: in a live meeting with pipelining on, the speaking label should now last to each reply's last sentence, an observation for the live acceptance, not a precondition.

## 17. Not verified

- No vitest, `tsc` or Playwright run was made in drafting. Every tests-first claim in §4 comes from reading; the orchestrator's tests-first run is the execution check.
- **Probe, not run (optional, Playwright, Chromium):** whether a real `HTMLMediaElement` delivers `pause` after `pause()` returns. In a page: make an `<audio>` from a short WAV data URI, `await a.play()`, add a `pause` listener that sets a flag, call `a.pause()`, and read the flag on the next line (expected `false`; the HTML spec queues the event as a media element task). No claim of this contract depends on the answer: C16 runs both orders, and §13 blind spot 3 shows both end in `listening`.
- **Order-independent by construction, not probed:** a sentence's `start` comes after the previous sentence's `end`, because `runPrefetchQueue` awaits `play(k)` before calling `play(k+1)` (`voiceChunking.ts:111`) and `_finish` fires `end` before it resolves (`voice.ts:758-759`). The gate's `final: false` branch relies on this.
- M6's production reach (a transcript accepted in `agent_speaking` with no barge-in) is from reading the controller; no live conversation was observed.
- `PTT_SENTENCE_GAP_MS = 5000` is a judgement, not a measurement (decision 5, §16).
- C20 and C21's fake-timer use follows `ProfileChatTab.bf764.test.tsx` but was not run in this harness; their margins assume the steps between two clock advances take well under 1 s of real time.
- Possible phantom-precheck false positives, all introduced here: `PTT_SENTENCE_GAP_MS`, `deferPause`, `pauseOrders`, `firstSentencePlays`, `plays`, `muted`, `GAP_MS`, `TWO`; from A1, `final?` on the meeting fake's `fire`, the two `test_bf918_m7_*` names, and the bf918 test's new imports (`renderHook`, `AgentProfilePanel`, `Agent`, `useMeetingVoice`, `armConversationMode`), all of which exist at the paths given (§11.1).
- A1 was drafted read-only, with no vitest or `tsc` run (`ui/node_modules` absent in the drafting worktree); its tests-first table is from reading. C22 renders `AgentProfilePanel` in this harness as the round-1 reviewer's executed probe did, with the same store fields. Its mic click after the gate opens runs the real capture path against the harness's mocked `startListening`; if that throws, report it and do not drop the click (it is the one observable of `ttsActiveRef`).
- C24 follows the reviewer's executed meeting probe (real `useMeetingVoice`, `armConversationMode` with the production predicate); its closing control (a transcript after the reply submits once) is new and was not executed.

## 18. For the register (found here, not fixed by this change)

- **R25 (closed for the PTT gate by M7).** The in-flight key half moves to R33.
- **R32 (Low, M7's residual).** A pipelined reply that loses the device between two sentences by GUARD 2 (no event of the entry for 45 s, then the next entry's dispatch takes the device; `voice.ts:472`, `:484`, `:543`) emits no further event. Its conversation turn stays `agent_speaking`: barge-in and transcripts still work, so the Captain's next words recover it, but the 30 s release timer does not run until then or the arm ends. Before M7 the first sentence's `end` completed it. Reach: a sentence synthesis that neither returns nor fails for 45 s. Design if needed: `voice.ts` emits a terminal event for a sentence queue that stops after `played > 0` without a `final` `end` (check every `dropped` consumer and BF-655's pairing first), and the PTT gate, the reply listener and the meeting wait act on it. A1 adds the meeting wait (`meetingVoice.ts` `_speakAndWait`) as a second consumer: after such a stop, or a 1:1 barge-in on another surface between two of a meeting reply's sentences, the wait ends on its whole-reply safety timeout (`computeUtteranceTimeout`, at least 20 s), holding the speaking label and the next speaker until then; no audio plays, and an armed meeting mic refuses transcripts until then. Before A1 the first sentence's `end` ended it.
- **R33 (Low, R20's family).** The BF-718 in-flight key clear (`ProfileChatTab.tsx:1385-1393`) still runs on every sentence's `end`. An identical reply whose claim is lost after the in-flight one's first sentence has ended completes its turn at once while the rest plays (M7's symptom, for that reply). Reach: identical reply text arriving later than the in-flight reply's first sentence. Not fixed: keeping the key until `final` waits, after a stop between two sentences, on an `end` that nothing emits (decision 4).
- **R34 (Low).** `wakeWord.ts:187-193` clears its barge-in suppression flag on every `end`, so between two sentences of a reply the wake word is not suppressed. No audio plays during the gap, so the reach is a recognition result that lands in the gap for speech captured during the previous sentence. Design: the same `final === false` check.
- **R35 (Low, review round 1 finding 3; the base fails it too).** The PTT gate's `end` branches do not check which utterance closed the gate: after a newer `start`, an older utterance id's `end` opens it while the newer utterance plays (non-final: it replaces the 45 s ceiling with the 5 s gap timer; on the base any `end` opens it at once). Reach: injected only; the review did not establish a production ordering, and one candidate (a browser `speechSynthesis.cancel()` whose old `onend` lands after the next utterance's `start`) was not probed. Design if needed: keep the `start`'s `utterance_id` in a ref, ignore an `end` whose id is defined and differs (id-less producers unchanged), and reset the ref with the gate (decision 8).
- **R36 (Low, pre-existing class; A1 changes one sequence).** The PTT gate knows only utterances that start while its subscription is live. A composer whose agent is already speaking when its subscription begins (a first mount, or since A1 a return to that agent mid-sentence: `AgentProfilePanel` a1, a2, a1) shows the gate open until that agent's next `start`, so a press in that window captures the rest of the sentence (without pipelining, the rest of the reply). Before A1 that return found the gate still closed, from the same stale state that stranded the other agent; a return after the reply had finished was stranded and is now right (decision 8). Reach: navigating back to a crew member while it speaks, then pressing its mic before its next sentence. Design if needed: seed the gate on each subscription from the arbiter (`speechQueueState()`, `speechQueueStore.ts:72`: a `started` entry with this `agent_id`), arming BF-655's ceiling with it; check that `started` means dispatched, not audible (`speechQueueStore.ts:45-52`).
