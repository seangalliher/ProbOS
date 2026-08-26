# BF-833: a result must belong to the broadcast that launched it

**Issue:** #1298 (already filed, OPEN) · **Repo:** OSS `d:\ProbOS`, branch `main`
**Number:** BF-833 — already allocated, do not mint a new one.
**Surfaced by:** review of BF-829 (#1293, shipped `367becd6`). **Not introduced by it.**

---

## The defect, verified at HEAD (2026-08-22)

`IntentBus._invoke_handler` decides whether to record a result by testing whether the intent ID is
**present** in `_pending_results` — presence, not which broadcast the entry belongs to. Both append
branches carry the identical guard:

```
src/probos/mesh/intent.py:1440      if intent.id in self._pending_results:
                    :1441          self._pending_results[intent.id].append(result)          # returned a result
                    :1460      if intent.id in self._pending_results:
                    :1461          self._pending_results[intent.id].append(                 # raised
                                       IntentResult(..., success=False, error=str(e), ...))
```

`broadcast()` **recreates that key on every call**:

```
src/probos/mesh/intent.py:1074      self._pending_results[intent.id] = []      # inside the try
                    :1129      results = list(self._pending_results.get(intent.id, ()))
                    :1153      self._pending_results.pop(intent.id, None)     # in the finally
```

So a straggler from round 1 that suppresses its `CancelledError` and finishes during round 2 of the
**same intent ID** finds the key present again — belonging to a different round — and appends into it.

The Captain measured it on both trees:

```
first=0  second=[('stale-first','STALE'), ('fresh','FRESH')]   CONTAMINATED=True
```

identical with `HEAD:src/probos/mesh/intent.py` restored in place. **Pre-existing. Do not re-litigate.**

### Why it is a learning defect, not a return-value defect

Verified — every result from a broadcast is fed to Hebbian routing before the caller ever sees it,
on **both** submission paths:

```
runtime.py:3741   results = await self.intent_bus.broadcast(msg, timeout=timeout)      # submit_intent
        :3743-3749    self.hebbian_router.record_interaction(source=intent, target=result.agent_id,
                                                             success=result.success)
        :3959   results = await self.intent_bus.broadcast(msg, timeout=timeout)      # ...with_consensus
        :3961-3967    self.hebbian_router.record_interaction(...)
        :3982   consensus = self.quorum_engine.evaluate(results, policy=policy)
```

A misattributed result therefore reinforces the wrong intent→agent edge **and** casts a vote in a
quorum it was never part of. It is well-formed, so nothing logs, nothing fails, and it is silent.

### Reachability

`IntentMessage` permits caller-supplied IDs and inbound federation preserves them, so ID reuse is
not exotic. A handler that suppresses cancellation is ordinary defensive code. Neither half needs
to be deliberate.

---

## The design decision

Presence is the wrong test. Two shapes were named on the issue. **Build option A** unless the
review below changes your mind; record the reasoning either way.

### Option A — pass the round's buffer in (recommended)

`broadcast` already creates the list at `:1074`. Hand **that same object** to each handler task and
have `_invoke_handler` append to it directly:

```python
# broadcast, at the fan-out (currently :1116-1122)
sink = self._pending_results[intent.id]          # the object created at :1074
...
    self._invoke_handler(intent, agent_id, handler, latency_class, sink)
```

`_invoke_handler` then takes `sink: list[IntentResult]` and appends unconditionally — **no presence
test at either branch**. A round-1 straggler appends into round 1's list, which `broadcast` has
already read (`:1129`) and dropped (`:1153`). The list is unreachable, the append is inert, and the
straggler never touches the dict at all.

Why this shape:

- **The capture must happen in `broadcast`, synchronously.** Capturing inside `_invoke_handler`'s
  own body is not equivalent: `create_task` only schedules it, so its first line can execute after a
  later broadcast already replaced the key. The whole defect is a scheduling window; do not close it
  with a read that sits inside the same window.
- **It keeps `_pending_results` as a real registry.** BF-829's leak assertions (`bus._pending_results
  == {}`) stay meaningful. Deleting the dict entirely would leave twelve assertions that pass
  forever and prove nothing — a vacuous test is worse than a missing one.
- **BF-829's guarantee becomes structural rather than guarded.** The `finally` comment at `:1136-1152`
  currently explains that the presence test stops a re-leak but not a cross-round append. Under
  option A a straggler cannot reach the dict on either count. **Rewrite that comment to say what the
  code then actually guarantees** — do not leave prose describing a guard that no longer exists.

### Option B — a generation token beside the list

`_pending_results[intent.id] = (generation, [])`, captured at launch, compared before appending.
Equivalent correctness, one more concept, and it changes the dict's value type — which breaks the
same fourteen test references as option A while buying nothing option A does not already have.
Recorded so the choice is visible, not because it is close.

### Handed back to the Captain (one question, does not block the build)

**Should a stale straggler's result be observable?** Under option A the append is silently inert.
Given the failure this BF exists to remove is *silent* misattribution, an operator may reasonably
want to know a handler completed after its round closed. Recommendation: **one `logger.debug` at the
append site when the sink is no longer the registered one**, and no metric — cheap, honest, and it
costs a `dict.get` per completion. Build the fix without it if the Captain does not answer; adding
it later is additive.

---

## Required tests

New file: `tests/test_bf833_result_belongs_to_its_broadcast.py`.

Copy the bounded autouse drain fixture from `tests/test_bf829_cancelled_broadcast_cleanup.py:72`
(`_leave_no_stranded_tasks`) — it is file-local, and these tests create handlers that outlive their
timeouts exactly as BF-829's do. **The drain must stay bounded** (`asyncio.wait(live, timeout=1.0)`);
an unbounded `gather` deadlocks on a handler that blocks inside its own cancellation handler.

### The cancellation shape is load-bearing — read this before writing a line

A handler that **re-raises** `CancelledError` reaches **neither** append branch. The Captain traced
it: `executed=[(1423, False), (1443, False)]`. A test written that way passes with both guards
deleted and pins nothing. The straggler must **suppress** cancellation and then complete.

`tests/test_intent.py:920-952`
(`test_cancelled_invoke_propagates_without_sample_warning_or_result`) is the existing test for the
re-raise case. **Keep it** — it is the negative control that makes the new tests meaningful. Repoint
its hand-seeded `_pending_results[intent.id] = []` (`:934`, `:950`) to the new signature.

### Required cases

1. **Cross-round contamination, return branch.** One `IntentMessage`, two sequential broadcasts.
   Round-1 handler swallows `CancelledError` and returns a result during round 2. Assert round 2's
   results contain only the round-2 agent.
2. **Cross-round contamination, exception branch.** Same rig; the round-1 straggler **raises** after
   suppressing cancellation. Assert round 2 is uncontaminated. This branch is separate because
   `_invoke_handler` has two independent append sites and one fix can miss one.
3. **Positive premise beside every negative** — a standing rule in this repo, and three tests passed
   vacuously in BF-830 for want of it. Each test above must also assert the straggler **actually
   ran and actually produced its value** (e.g. an `asyncio.Event` it sets, or a recorded call
   count), so "round 2 is clean" cannot pass because nothing happened.
4. **Round 1 still collects its own result** when it is not cancelled — the ordinary path is
   unchanged.
5. **A straggler appending after its round closed does not raise and does not resurrect the key**:
   `bus._pending_results == {}` after both broadcasts return.

### Mutation check (required before the commit)

Revert **each** guard change independently and confirm a named test reddens for each. Two redundant
guards can cover each other and both survive individually — run the combined mutant too, and record
which mutants died and why. A survivor is not automatically a test gap; a survivor you did not
investigate is.

---

## Test blast radius — enumerated, not estimated

`_invoke_handler`'s signature and `_pending_results`' value type are both touched. Every coupling:

| File | Refs | What breaks |
|---|---|---|
| `tests/test_bf829_cancelled_broadcast_cleanup.py` | 12 | `bus._pending_results == {}` / `not in` assertions. Option A keeps these **valid and meaningful** — verify each still means what its docstring says rather than assuming. |
| `tests/test_intent.py:934, :950` | 2 | Calls `_invoke_handler` **directly** with a hand-seeded buffer. Must pass the sink explicitly. |

That is the complete set: `_pending_results` appears in exactly two test files and nowhere else in
`src/` outside `mesh/intent.py`. `tests/test_bf747_durable_consumer_name.py:121,138` does scan
`inspect.getsource(intent)` but counts `_durable_consumer_name` literals only — unaffected.

**Do not delete or weaken a BF-829 assertion to make a new test pass.** If one becomes untrue, that
is the signal the fix is wrong, not the test.

---

## Do not build

Named because each is adjacent and tempting:

- **Do not await stragglers.** BF-829 deliberately does not, and measured why: 2.2s versus 0.2s when
  one handler has slow cancellation cleanup. That decision stands.
- **Do not reject or rewrite duplicate intent IDs.** Caller-supplied IDs are a contract and inbound
  federation preserves them. Making the bus refuse a reused ID "fixes" this by removing a capability.
- **Do not touch `send`, `dispatch_async`, `publish`, or the NATS/JetStream callbacks.** None of them
  uses `_pending_results` — verified, the only references in `src/` are `intent.py:259, 1074, 1129,
  1153, 1440-1441, 1460-1461`.
- **Do not add a generation counter to `IntentMessage`** or change ID semantics anywhere in `types.py`.
- **Do not touch the federation merge** at `intent.py:1163` or the metrics call at `:1156`.
- **Do not widen this into BF-771's authorization work** or into the consumer-side gaps it names.
- **Do not "simplify" `_pending_results` out of existence.** See option A's rationale.

---

## Acceptance criteria

- Both append branches record a result **only** for the broadcast that launched the handler,
  proven by a test in which cancellation is suppressed and the straggler completes during a later
  round of the same intent ID.
- Both branches are covered separately, each with a positive premise assertion proving the straggler
  ran.
- The re-raise case (`test_intent.py:920-952`) still passes and still proves it reaches neither branch.
- All 12 `_pending_results` assertions in `tests/test_bf829_cancelled_broadcast_cleanup.py` still
  pass and still mean what they say.
- The `finally` comment at `intent.py:1136-1152` describes what the code now guarantees; the BF-833
  caveat paragraph is removed rather than left standing as a false open item.
- Mutation matrix run per guard **and** combined, with results recorded in the commit body.
- Focused gate green: `pytest tests/test_bf833_*.py tests/test_bf829_*.py tests/test_intent.py -q -n 0`
- Then one consolidated gate: `pytest tests/ -q -n 16 --dist=loadfile`
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
- Run the `Diff Reviewer` subagent on the staged diff with a different model than wrote the code,
  and address blockers before committing.

---

## Verified Against Codebase (2026-08-22)

```
grep -n "_pending_results" src/probos/mesh/intent.py
  259:  self._pending_results: dict[str, list[IntentResult]] = {}  # intent_id -> results
  1074: self._pending_results[intent.id] = []
  1129: results = list(self._pending_results.get(intent.id, ()))
  1153: self._pending_results.pop(intent.id, None)
  1440: if intent.id in self._pending_results:
  1441:     self._pending_results[intent.id].append(result)
  1460: if intent.id in self._pending_results:
  1461:     self._pending_results[intent.id].append(

grep -n "_invoke_handler" src/probos/**            # exactly one call site + the def
  intent.py:1118: self._invoke_handler(intent, agent_id, handler, latency_class),
  intent.py:1403: async def _invoke_handler(

runtime.py:3741 / :3743-3749   broadcast -> hebbian_router.record_interaction   (submit_intent)
runtime.py:3959 / :3961-3967   broadcast -> hebbian_router.record_interaction   (with_consensus)
runtime.py:3982                consensus = self.quorum_engine.evaluate(results, policy=policy)

grep -c "_pending_results" tests/*.py
  tests/test_bf829_cancelled_broadcast_cleanup.py: 12
  tests/test_intent.py: 2                          # :934 seeds, :950 asserts, calls _invoke_handler direct

tests/test_bf829_cancelled_broadcast_cleanup.py:72   @pytest.fixture(autouse=True) _leave_no_stranded_tasks
                                              :100   await asyncio.wait(live, timeout=1.0)   # bounded
```
