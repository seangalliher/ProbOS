# BF-830: a rejected consensus re-runs the side effect twice more

**Issue:** file as new · **Parent:** #1242 (BF-779, finding 1's consequence) · **Repo:** OSS, branch `main`, base `b4acdbfe`

## This is the live, buildable half of BF-779

BF-779's own "smallest independently valuable step" (finding 3, the descriptor floor) was
attempted and **proven unsafe** — see the analysis in the closing section. This prompt builds the
part that is a genuine defect with a genuine fix, and it is independent of every architectural
question in that issue.

## The defect, verified end to end (2026-08-22)

`submit_intent_with_consensus` broadcasts **before** it evaluates quorum, so agents execute during
step 1 and the vote happens in step 2 with no rollback:

```
runtime.py:3923   async def submit_intent_with_consensus(
                      results = await self.intent_bus.broadcast(msg, timeout=timeout)   # agents RUN
                      consensus = self.quorum_engine.evaluate(results, policy=policy)   # then vote
```

A rejection then enters the escalation ladder, **which calls the same method again**:

```
decomposer.py:1031-1039   _handle_rejection -> self.escalation_manager.escalate(node, ...)
escalation.py:109         tier1_result = await self._tier1_retry(node, error, context)
escalation.py:160         for attempt in range(1, self.max_retries + 1):        # max_retries = 2 (escalation.py:62)
escalation.py:170-174         result = await self.runtime.submit_intent_with_consensus(...)
escalation.py:186             # Consensus rejected/insufficient — continue retrying
```

`ShellCommandAgent.act` executes the command on the broadcast (`agents/shell_command.py:132-153`).
So **one promoted `run_command` whose quorum rejects performs the command three times**: the
initial broadcast plus two Tier-1 retries. Measured by executed probe with quorum always
rejecting — 3 consensus broadcasts (recorded on #1242).

### It is live, not latent

The decomposer prompt instructs the model to promote every one of these:

```
decomposer.py:123   6. All run_command intents MUST have "use_consensus": true.
decomposer.py:176   {"intent": "run_command", ..., "use_consensus": true}
decomposer.py:185   {"intent": "run_command", ..., "use_consensus": true}
```

So the ordinary path for a shell command is the promoted one, and the ordinary consequence of a
rejected vote is triple execution. There is no flag to turn this off.

### `write_file` is unaffected, and shows why

`escalation.py:162-168` special-cases `write_file` to `submit_write_with_consensus`, which
proposes and only commits after the vote (`runtime.py:4127`, `:4156`). Retrying a *proposal* is
harmless. The `else` at `:169` is every other intent, and for those the retry re-runs the act.

## Required change

**A consensus rejection must not be retried by re-executing.** Tier 1's premise — "retry with a
different agent" — is sound for a *transport or agent* failure. It is wrong for a *governance*
outcome: the crew considered the act and declined it. Retrying is not recovery, it is
disobedience with extra side effects.

1. **`_tier1_retry` must not re-invoke a consensus path for a node whose failure was a consensus
   rejection.** Distinguish the two entry reasons. `_handle_rejection` (`decomposer.py:1022`) is
   the consensus-rejection door and is the only caller that needs the new behaviour; ordinary
   execution errors keep the existing ladder unchanged.
2. **For a consensus rejection, skip Tier 1 entirely and enter at Tier 2 (LLM arbitration).**
   Tier 2 does not execute the intent, so it is safe. Tier 3 (`escalation.py:384-411`) already
   deliberately bypasses consensus *after explicit user approval*, which is the correct and only
   place a declined act may proceed.
3. **Record the skip.** The `EscalationResult.tiers_attempted` list must show that RETRY was
   deliberately not attempted, with a reason. An observer must be able to tell "we skipped it" from
   "it was tried and failed".

Choose the mechanism that keeps `EscalationManager` unaware of *why* consensus rejected — it
should be told the failure category, not asked to infer it. `_handle_rejection` already emits
`"category": "consensus"` at `decomposer.py:1035`; that value is the natural carrier.

## Do not build

- **Do not add a commit phase to `CodeRunnerAgent` or `ShellCommandAgent`.** That is BF-779
  finding 2 and it is a Captain decision (below). This prompt makes the existing behaviour stop
  multiplying; it does not change what consensus means.
- **Do not enforce `IntentDescriptor.requires_consensus` as a floor.** Proven unsafe — for the
  generic path, promotion converts one execution into three, which is what this prompt fixes and
  is strictly worse than the omission. See #1242's comment.
- **Do not change `max_retries`.** Lowering it to 0 would suppress the symptom for consensus and
  break genuine transport retries at the same time.
- **Do not touch `submit_write_with_consensus` or `FileWriterAgent`.** They are the one path that
  is already correct.
- **Do not change the decomposer prompt text at `:113-209`.** Whether the model should promote
  `run_command` at all is the Captain call below; changing the prompt pre-empts it.

## Tests

1. **The headline, and it must fail before the fix:** a node with `use_consensus=True` and intent
   `run_command`, quorum rejecting, with a recording agent. Assert the side effect happens
   **exactly once**. Today it happens three times.
2. `write_file` under the same conditions: still zero commits, and the existing proposal/commit
   behaviour is byte-identical.
3. A **non**-consensus execution error still gets its full Tier-1 ladder — `max_retries` attempts,
   unchanged. This is the regression that a careless fix causes.
4. `tiers_attempted` distinguishes skipped-RETRY from attempted-and-failed RETRY.
5. Tier 3's post-approval bypass (`escalation.py:384-411`) is unchanged: after explicit user
   approval the act runs, once.
6. Mutation-check every fix: revert production, confirm the test fails, restore.

## Closing BF-779 (#1242) with this

Once this ships, recommend closing #1242 with all three findings resolved:

- **Finding 1** (executes before it votes) — the *harm* is fixed here. The ordering itself is
  inherent to a post-hoc vote and is honest once it stops being multiplied.
- **Finding 2** (generalise propose-then-commit) — **the Captain has already ruled**, on BF-763
  (#1221): a foreground coding agent does not vote before each command, and the replacement control
  for `run_python` is the per-execution audit record. No intent other than `write_file` currently
  wants a gate. Reopen only if a new destructive intent arrives that does.
- **Finding 3** (descriptor floor) — **won't fix**, proven unsafe by execution. Record the four
  measured reasons: triple execution; a fail-open lookup that returns `False` when the descriptor
  source raises; `NODE_START` emitting the pre-promotion flag so the Captain is shown
  "non-consensus" for a consensus run; and durable promotion through `workflow_cache.py:32-45` and
  `checkpoint.py:224-230` that a later downgrade cannot lower.
- **Finding 3's honest residue is item 3 of the issue** — *do not describe consensus as
  authorization anywhere*. Grep for surviving instances and correct them in this commit.

## Report back

- The execution count for a rejected `run_command`, before and after.
- Confirmation that non-consensus retries are unchanged, with the count.
- **Anything in this prompt that turned out to be untrue.**

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
