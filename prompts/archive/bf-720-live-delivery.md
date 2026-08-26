# BF-720: a promoted turn's report is persisted but not delivered live

**Issue:** #1159 · **Repo:** OSS `d:\ProbOS`, branch `main`

---

## The measured defect

```
21:56:59  message written to chat_thread_messages
          meta: {"source":"dm_agentic_promotion","work_item_id":"6419f0e144a4"}
22:14:33  Captain sends a message
   ~then  the 21:56:59 result finally renders
```

**17.5 minutes invisible.** The Captain learned the work had finished only by asking whether it
was still running — and that question cost a second full execution (AD-1209 #1160).

## Read this first: BF-703 already guessed at this and it came back

`useStore.ts` carries a BF-703 comment describing the identical symptom, and
`ui/src/store/__tests__/bf703LiveRefreshShells.test.ts` pins the fix. That fix widened ONE gate.
The symptom recurred, which means the gate BF-703 widened is probably not the one dropping it now.

**Do not widen a gate on inspection. Reproduce first.**

## There are FIVE silent drop points, not two

All of them `return` with no log, no counter, no dev warning. This is why the same defect has now
had to be found twice by a human noticing an absence.

In `useStore.ts` `handleEvent`:

| # | Gate | Drops when |
|---|---|---|
| 1 | `parseLiveFrame(event) === null` | frame shape unrecognised |
| 2 | `authority.liveGeneration === null \|\| !== generation` | **WS reconnected and no `state_snapshot` re-established the generation** |
| 3 | `sequence <= authority.liveSequence` | replay or out-of-order |
| 4 | `isOpen` false — `message.thread_id === profileThread \|\| shellThread` | neither shell claims the thread (BF-703's gate) |

In `components/profile/ProfileChatTab.tsx`:

| # | Gate | Drops when |
|---|---|---|
| 5 | `command.threadId === activeThreadId` | the component's thread differs from the store's |

**Leading hypothesis — gate 2.** The session ran from 21:10; the event was at 21:56. A reconnect
in that window changes the generation, and if no `state_snapshot` follows, EVERY later event is
silently discarded. That matches the symptom precisely: nothing arrived until the Captain sent a
message, which refetches directly rather than via the socket.

**It is a hypothesis. Prove or disprove it — do not build on it.**

## What to build, in this order

**Step 1 — instrument every drop. This ships regardless of what you find.**

Each of the five gates must record why it dropped a frame: the gate, the event type, and enough
context to identify the thread. Cheap and dev-visible — a `console.debug` behind
`import.meta.env.DEV`, plus a small counter in the store so a test can assert it.

This is the durable half of the fix. BF-703 and BF-720 were both diagnosed by a human noticing
an absence, twice, because a frame can vanish at five places without leaving a trace.

**Step 2 — reproduce.**

Write a failing test that reproduces a promoted report never reaching the transcript. Start with
gate 2: install a snapshot, deliver an append with a DIFFERENT generation, assert no
`liveThreadRefresh`. If that reproduces the shape, that is the defect. If it does not, work
through gates 1, 3, 5 and report what you find.

**Step 3 — fix the gate you actually identified**, with the failing test from step 2 as the proof.

## Constraints

- **Do not widen a gate you have not proven is the one dropping the message.** That is what
  BF-703 did.
- **Do not fix by polling.** A timer hides the delivery defect and costs a request per interval
  per open chat.
- **Keep the safety properties.** Generation and sequence gating exist to stop replayed or stale
  frames corrupting live state. If the fix is "recover from a generation change", recovery must
  mean *re-establishing authority* (request a snapshot / refetch), not *ignoring the mismatch*.
- Do not change the server side. The message is persisted, emitted and delivered — verified.
- Do not touch `_post_report`, the promotion path, or BF-717's message text.
- **str-replace end-anchor trap:** `handleEvent`'s gates are consecutive near-identical
  `if (...) return;` lines. Whatever appears at either END of `oldString` must reappear in
  `newString`. Verify neighbours survived.

## Tests

- The reproduction from step 2, failing before the fix.
- Each of the five gates records a drop reason when it drops.
- **Regression:** BF-703's two shells still refresh — `bf703LiveRefreshShells.test.ts` must stay
  green and must not be edited to accommodate this fix.
- A frame that SHOULD be dropped (genuine replay, wrong generation with no recovery path) is
  still dropped. Do not trade a delivery bug for a state-corruption bug.

## Gates

`cd ui && npx vitest run` then `npm run build`. **Both** — Vitest does not type-check and `tsc`
has caught missing props in this exact area before.

A full Python gate is **not required** if zero `.py` files change; confirm with
`git diff --cached --name-only`.

## Do not commit

Leave staged. Report:

1. Which gate actually dropped the message, and the test that proves it.
2. Why the other four did not (or that you could not rule them out, honestly).
3. How the drop instrumentation works and what it costs in production.
4. Confirmation that `bf703LiveRefreshShells.test.ts` is unmodified and green.
5. Vitest + build numbers.
6. Anything in this spec you found to be wrong — three of my premises were wrong today, so check
   rather than trust.
