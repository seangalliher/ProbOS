# BF-723: a decided request can come back, and a stale badge can outlive it

**Issue:** #1168 · **Epic:** #1162 · **Absorbs:** #1161 (AD-1210) · **Repo:** OSS, branch `main`

## Two halves of one fault: async results applied without regard to whether they are still current

### Half A — a decision is only removed locally

`CapabilityRequestPanel.tsx` filters the decided row out of its own state. The shared store is
told nothing except "refresh". `useStore.ts` (`refreshPendingApprovals`) then does:

```ts
const keep = (queue) => previous.filter((a) => a.queue === queue);
const next = [
  ...(capability.status === 'fulfilled' ? capability.value : keep('capability')),
  ...(skill.status === 'fulfilled' ? skill.value : keep('skill')),
];
```

So when the capability GET fails after a successful decision, the store **re-keeps the row the
Captain just decided**. The card is gone from the panel and the Bridge badge still counts it.
An older in-flight GET that lands after the decision resurrects it the same way.

`onDecided` carries no queue and no id — it only triggers another refresh, so nothing downstream
can know what just went away.

### Half B — four surfaces discard a *correct* result (this is #1161)

`ChatsPanel.tsx:156/164`, `CrewCollaborationPanel.tsx:569/592`, `WorkspaceFilesRail.tsx:224/232`
and `:269/278` each capture `authority.liveSequence` before an async fetch and throw the result
away if **any** live frame arrived meanwhile.

BF-720 fixed exactly this in `ProfileChatTab` and the reasoning transfers unchanged: `liveSequence`
advancing means only that *another frame arrived*, which one always does when a work item
finishes. It says nothing about whether the fetched result is stale. Every one of these sites
already has a `requestId` counter plus an in-flight ref that **coalesce rather than race**, so
the sequence check contributes nothing but the discard.

They are the same defect from opposite directions — A applies a result that is too old, B
discards one that is current. Fixing them separately means designing the reconciliation twice.

## Required change

1. **Reconcile centrally by queue + id.** A successful decision records a tombstone `(queue, id)`
   in the store. Any refresh result is filtered through it, so a server still reporting the row
   cannot resurrect it. Drop a tombstone once the server stops reporting that id, so the set
   cannot grow without bound.
2. **Make responses monotonic per queue.** A response may only be applied if it is newer than the
   last applied response for that queue. An older in-flight GET landing late is discarded.
3. **Keep `liveGeneration` as the authority check** — stream identity changing genuinely voids a
   fetch. Do **not** reintroduce a `liveSequence` capture-and-discard anywhere; that is precisely
   the BF-720 defect.
4. **Remove the four `liveSequence` capture sites** listed above.

## Two hard constraints from BF-720

**Each of the four surfaces gets its own reproduction test before its fix.** Do not cover all
four with one shared test. BF-720's value came from a test reproducing the real
burst-of-frames timing on the actual component; a generic test would have passed against the
defect.

**Check every file you touch for a `?raw` source-text assertion pinning a line you are
changing.** `ProfileChatTab.threadTranscript.test.tsx` asserted the source *contained*
`current.liveSequence !== sequence` — holding the defect in place as though it were the contract.
That is five instances this week. Update and explain inline; never delete.

## Out of scope

- No backend changes. Zero `.py` staged. The route already reports `fulfilled` honestly (BF-722).
- Do not change the polling interval or add a websocket path.
- Do not touch `bf703LiveRefreshShells.test.ts` — BF-703's fix is proven and unrelated.

## Tests

1. Approve a card, then 503 on that queue and 200 on the other: the card disappears **and** the
   badge count drops. Both, not either. Fails before the fix.
2. A delayed older GET containing the decided request does not restore it.
3. An out-of-order response for one queue does not clobber a newer one.
4. A tombstone is released once the server stops reporting the id — assert the set does not grow
   unbounded.
5. Four separate reproduction tests, one per `liveSequence` surface, each asserting a fetched
   result survives a live frame arriving mid-flight.
6. `liveGeneration` still invalidates a fetch — the real authority check is intact.

**Mutation-check every fix:** revert production, confirm the test fails, restore.

## Gates

- `cd ui && npx vitest run` — baseline **2,309 tests / 316 files** (post-BF-721).
- `cd ui && npm run build` — **both are required.** Vitest does not type-check and `tsc -b` has
  caught real errors repeatedly, including a lost discriminated-union narrowing in BF-720.
- No `.py` changed ⇒ the Python gate is correctly skipped. If any `.py` is staged, stop — that is
  scope creep.

## Report back

- The reconciliation shape, and how tombstones are released.
- Both UI gate numbers.
- Any test that pinned the old behaviour — expect at least one.
- **Anything in this prompt that turned out to be untrue.** The last three prompts each contained
  a wrong claim and saying so was the most valuable part of the report.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
