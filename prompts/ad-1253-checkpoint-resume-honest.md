# AD-1253: checkpoint resume — stop the data loss now, and put the resume-vs-replan choice to the Captain

**Issue:** #1281 (BF-817) · **Repo:** OSS, branch `main`, base `b4acdbfe`

## Structure of this prompt

**Section A is unconditional** — it is correct under every one of the three positions below, and it
fixes real data loss on a recovery path. Build it now.

**Section B is a Captain decision.** Three positions with their costs. Do not build Section B until
the Captain has ruled; if the ruling arrives with this prompt, build the chosen arm and delete the
other two from the file.

Splitting it this way is deliberate: the two consequences in Section A are true today regardless of
which way the design goes, so holding them hostage to the design question means a recovery path
keeps destroying evidence while the decision waits.

## The chain is live — verified end to end (2026-08-22)

**Producer fires:**

```
decomposer.py:745-746   if self._checkpoint_dir: write_checkpoint(self._checkpoint_dir, dag, results)
decomposer.py:960-961   (same)
decomposer.py:1019-1020 (same)
runtime.py:517          self._checkpoint_dir = self._data_dir / "checkpoints"   # unconditional
```

**Real checkpoints exist.** From the running vessel's data directory —
`%LOCALAPPDATA%\ProbOS\data\checkpoints`, **not** the repo's stale `d:\ProbOS\data`:

```json
{ "checkpoint_id": "b04654a4a06e47c1b160748dea11f0fb", "source_text": "/scout",
  "created_at": "2026-05-18T09:30:30.651479-06:00",
  "node_states": { "c1_a0d2e0": { "status": "pending", "result": null } },
  "dag_json": { "nodes": [ { "id": "c1_a0d2e0", "intent": "scout_report",
                             "depends_on": [], "use_consensus": false, "background": false } ] } }
```

**Consumer is reachable:** `routers/scheduled_tasks.py:108-112` → `resume_dag`. Enumerated
repository-wide; every other reference is a test or an archived prompt.

**The discard, at `persistent_tasks.py:336`:**

```python
checkpoint = load_checkpoint(checkpoint_path)
dag, results = restore_dag(checkpoint)      # <- neither name is read again
...
result = await self._process_fn(checkpoint.source_text, channel_id=None)   # :346-349
delete_checkpoint(Path(self._checkpoint_dir), dag_id)                      # :351
```

---

## Section A — unconditional, build now

### A1. Stop deleting the checkpoint after a run that may not be the checkpointed plan

`persistent_tasks.py:351` deletes on success. Decomposition is an LLM call, so the re-run can
produce a **different** DAG — and the record of what was actually in flight is then destroyed. That
is data loss on a recovery path, and it is unambiguously wrong under all three positions.

Retain the checkpoint. Bound the retention so this does not become an unbounded directory: reuse
`scan_checkpoints` (`cognitive/checkpoint.py:112`), already used by `persistent_tasks.py:498` and
`startup/communication.py:254`, and give resumed checkpoints an explicit terminal state rather than
an unlink. A resumed-and-superseded checkpoint must be distinguishable from a stale one that has
never been resumed, or the startup scan will keep re-offering it.

### A2. The event must say which thing happened

`SCHEDULED_TASK_DAG_RESUMED` (`persistent_tasks.py:352-356`) reports a `result` for something that
was **re-planned**, not resumed. An observer cannot tell the two apart. Add an explicit field
recording which path ran. Under Section B position 1 this field is how a staleness fallback becomes
observable; under position 2 it is the honest label. Either way it is needed.

Do not rename the event type in Section A — a rename is a position-2 choice and pre-empts the
Captain.

### A3. Two small correctness items in the same function

- `resume_dag` returns bare `{"error": ...}` dicts on five paths (`:328`, `:333`, `:339`, `:341`,
  `:360`) that the route at `scheduled_tasks.py:112` returns to the caller as-is. Give them a
  consistent shape so the route can distinguish "no such checkpoint" from "restore failed".
- `except Exception` at `:338` swallows a corrupt checkpoint into a string. Per the three-tier rule
  this is correctly log-and-degrade, but it must **log** — today it does not.

---

## Section B — Captain decision, do not build until ruled

The machinery favours position 1: `restore_dag` (`cognitive/checkpoint.py:133`) already
reconstructs node statuses so `get_ready_nodes()` resumes correctly, and `checkpoint.py:224-230`
faithfully serialises `use_consensus` per node. **But that is an argument from the code's shape,
which is exactly the thing this issue says must not be trusted to imply a guarantee.** State the
argument; do not let it decide.

| | Position 1 — **resume the plan** | Position 2 — **re-plan, and say so** | Position 3 — **staleness gate** |
|---|---|---|---|
| **What runs** | The checkpointed DAG, from `get_ready_nodes()` | Fresh decomposition from `source_text` | Plan if fresh, re-plan if stale |
| **Completed nodes** | Honoured — `results` merged, not redone | Redone, including side effects | Honoured when resuming |
| **Cost** | `PersistentTaskStore.__init__` (`persistent_tasks.py:103-124`) takes `db_path`, `emit_event`, `process_fn`, `tick_interval`, `checkpoint_dir`, `connection_factory` — **no `DAGExecutor` and no runtime handle**. Needs a new injected collaborator plus a second execution mode with results-merging semantics. Layer note: inject a narrow `typing.Protocol`, not `DAGExecutor` itself — `persistent_tasks.py` is top-level and `DAGExecutor` is cognitive | Small. Stop binding `dag, results`; reduce the serialised shape to what is consumed; rename path and event | Position 1 plus a freshness policy and a fallback arm |
| **Risk it accepts** | Executing a plan that has gone stale against changed ship state | Repeating side effects; the plan after resume differs from the plan before it, so a checkpoint pins nothing | Two paths to test; the staleness predicate becomes a thing that can be wrong |
| **What it costs to reverse** | Low — the executor stays injected | **High** — position 2 deletes the serialised DAG, so choosing 1 later means rebuilding the format | Low |

**Architect's note, not a decision:** position 2 is the only one that is hard to reverse, because it
discards the stored shape. If the Captain is undecided, position 2 is the option that forecloses the
others, and that asymmetry is worth knowing before choosing the cheap one.

## Do not build

- **Do not label the path honestly while leaving the behaviour.** Calling it "re-plan" without
  reducing the stored shape is the same "shape implies a guarantee the path does not deliver"
  defect, one level up. Section A2 adds a field describing what ran; it does not rename the feature.
- **Do not delete the `dag, results` binding in Section A.** Under position 1 those names are the
  fix. Leave them bound, with one line naming the open decision.
- **Do not inject `DAGExecutor` in Section A.** No new collaborator until Section B is ruled.
- **Do not change `write_checkpoint`, `restore_dag`, or the serialised format** in Section A.
- **Do not touch the startup stale-checkpoint scan** (`startup/communication.py:252-254`) beyond
  what A1's terminal state requires.

## Tests

**Section A:**

1. A successful resume leaves the checkpoint recoverable, and it is distinguishable from a
   never-resumed one. Fails before the fix.
2. The emitted event carries the field naming which path ran.
3. Each of the five error paths returns its distinct shape; the route surfaces them distinctly.
4. A corrupt checkpoint logs, degrades, and does not raise.
5. Retention is bounded — resumed checkpoints do not accumulate without limit, and the startup
   scan does not re-offer one that has been resumed.

**Section B, position 1 (only if ruled):**

6. A checkpoint with one `completed` and one `pending` node resumes and executes **only** the
   pending node. The completed node's side effect happens **once across both runs** — this is the
   test that proves the whole point, and it must fail before the fix.
7. `results` from the checkpoint appear in the resumed run's output.
8. A checkpoint whose DAG cannot be restored falls back observably, and the fallback is the event
   field from A2.

## Tracking

- **#1281** stays open until Section B is ruled and built. Section A closes no issue on its own —
  say so in the commit rather than closing it early.
- Record the Captain's ruling in `DECISIONS.md` with the reasoning, not just the outcome.

## Report back

- Which Section A items landed, and the retention mechanism chosen.
- The Captain's ruling if given, or an explicit "Section B not built, awaiting decision".
- **Anything in this prompt that turned out to be untrue.**

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
