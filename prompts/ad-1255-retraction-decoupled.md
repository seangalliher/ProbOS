# AD-1255: retraction, decoupled from self-modification

**Issue:** #1200 (BF-741) · **Repo:** OSS, branch `main`, base `b4acdbfe`

## The policy, decided

**An agent's own prior claim stays recallable — a claim that has been *contradicted* must not be.**

Direction 2 from the issue ("do not recall an agent's own capability claims as evidence") is
rejected as the primary fix: capability claims are not reliably separable from observations at
write time — *"I fetched that and got a 403"* is both — and suppressing a class of statement would
violate this issue's own constraint that no true statement becomes less recallable. The problem in
both compounding cases (BF-728, BF-739) was not that the agent recalled a claim; it was that it
recalled a claim already known to be **false**.

**Exclusion, not demotion.** A claim the Captain has explicitly corrected is not weak evidence, it
is wrong evidence. BF-739 established that competing against an unbounded, self-replenishing
population of episodes is unwinnable, so reweighting cannot work.

## AD-871's machinery is complete and inert at both ends

Enumerated across `src/probos/**` (2026-08-22), not recalled:

| Piece | State |
|---|---|
| `Episode.contradicted_by: list[str]` — `types.py:634` | exists |
| `mark_contradicted(episode, id)` — `types.py:692` | **zero callers.** `rg -n 'mark_contradicted' src/` returns the definition and nothing else |
| `contradicted_by_json` persisted — `episodic.py:3456` | works |
| loaded back on read — `episodic.py:3571-3620` | works |
| recall consults it | **never** |

Represented, stored, retrieved — and no path writes one or reads one. The field's existence makes
the system look as though it already handles contradiction, which is why the defect survived.

## The four blockers the first attempt hit — all reproduced by execution

`.git/BF741_REJECTED.patch` (26,307 bytes) implemented the obvious three-piece build. Review blocked
it with four findings. **Three of them change what this build has to do**, and one invalidates the
plan's premise entirely.

### 1. The producer does not fire for the case this issue measured — decisive

```
rg -n 'apply_correction_feedback' src/
  cognitive/feedback.py:168     def apply_correction_feedback(   <- definition
  self_mod_manager.py:170       await self._feedback_engine.apply_correction_feedback(
```

**Exactly one production caller**, reached only after a *successful self-mod patch*. `/correct`
rejects any agent without a designed-agent record (`experience/commands/commands_plan.py:253-260`),
and no DM or router code calls correction feedback at all. #1200's original case was a normal crew
DM, so retraction could never trigger for it even with the identity wiring repaired.

**This is the first piece and it was not in the original plan.** A Captain saying *"actually you did
send it"* is the signal; whether an agent's source got patched is unrelated.

### 2. The identity transport can retract the WRONG episode

`_last_episode_id` was set only on the runtime DAG path (`runtime.py:5116`). The shell renderer
stores an episode at `experience/renderer.py:424` and records only `_last_execution`; the DM
pipeline discards the new id at `reply_pipeline.py:1694`. Nothing clears the field between turns.

Measured: a real DM store produced episode `ae7a…` while `runtime._last_episode_id` still held
`stale-dag-id`. An unrelated store does not overwrite it — **it leaves the prior id armed**, which
is worse than overwriting. Retracting an unrelated episode makes a **true** statement unrecallable,
breaking the one constraint this issue sets.

### 3. The filter boundary was wrong — six recall paths, one filtered

Measured against a real `EpisodicMemory` holding one contradicted episode:

```
sovereign          = []                  <- filtered
recent             = [contradicted-id]
anchor             = [contradicted-id]
anchor_scored      = [contradicted-id]
global recall()    = [contradicted-id]
hybrid (fts on)    = [contradicted-id]
```

These are not browsing surfaces. `cognitive_agent.py:10143` falls back to unfiltered recency,
`:10722` merges unfiltered anchor recall, `:10330` renders both into `recent_memories`, and global
`recall()` is rendered as `## PAST EXPERIENCE` by `decomposer.py:350`. The sovereign filter also
sits *before* hybrid fusion (`episodic.py:3203-3268`), which can rehydrate the same hit afterwards,
and the confidence band is computed **before** filtering — so an emptied result still reports
`strong` and suppresses cross-agent recovery.

### 4. Both persistence contracts were ignored

`EpisodicMemory.store()` returns `STORED` / `DUPLICATE` / `SKIPPED` (`episodic.py:1681`); the
attempt treated any non-throwing call as stored. Measured: forcing `SKIPPED` still marked the target
and attributed it to an episode id that does not exist. `mark_episode_contradicted`'s `False` return
was ignored too, so a failed retraction was silent. **The hand-written fake returned `None` from
`store` and always `True` from the marker, so it could not have caught either.**

## Required change, in dependency order

All four land together. A consumer alone is a filter with no producer — the trap this repo keeps
falling into.

### 1. A correction signal that does not require self-mod

Retraction triggers on the Captain correcting a claim, independent of whether any agent source was
patched. `apply_correction_feedback` may remain the self-mod path; the retraction signal must have
its own producer reachable from a normal crew DM. Name that producer in the design before writing
the consumer.

### 2. An immutable last-turn record, passed as an argument

Not `runtime._last_episode_id`. One `{execution, text, episode_id}` value, **set only after
`EpisodeStoreOutcome.STORED`**, cleared on every new or failed turn, and **passed as an argument
rather than by mutating a private field on another object** (Law of Demeter, and finding 2 is what
happens without it).

### 3. `EpisodicMemory.mark_episode_contradicted(episode_id, contradicting_id)`

Mirroring `update_episode_validity` (`episodic.py:2230`): load, apply `types.mark_contradicted`,
re-persist metadata. Honour both contracts from finding 4 — check the store outcome before marking,
and surface a `False` return as a warning.

### 4. One shared `_episode_is_contradicted` predicate at the FINAL evidence boundary

**After every fusion/merge, before confidence and rendering.** Not per-method — paths drift. History
stays reachable through an explicit `include_contradicted=True` parameter rather than by leaving
dual-purpose recall methods unfiltered.

The confidence band must be computed **after** exclusion, or an emptied result reports `strong`.

## Do not build

- **Do not filter per recall method.** Six methods, one boundary. Finding 3 is what per-method
  filtering produced.
- **Do not demote or reweight.** Exclusion. BF-739's reasoning is the whole argument.
- **Do not teach agents to hedge or distrust their memory.** AD-1204's lesson stands: it treats the
  symptom and degrades true statements too.
- **Do not attempt claim-level retraction.** `contradicted_by` is **episode**-granular and a DAG
  episode aggregates several nodes and agents (`dream_adapter.py:351-410`), so retracting a whole
  turn because one claim in it was wrong does make true statements unrecallable. That is a data-model
  change and a separate issue — **file it, do not build it.**
- **Do not filter dreaming.** `dreaming.py:217` and `:436` consume unfiltered `recent()` and
  `recall_by_intent()`, so a corrected episode keeps influencing trust, routing and procedure
  seeding. Real, and **out of scope** — file it separately so the boundary of this AD stays honest.
- **Do not attempt BF-728's shape** — a claim contradicted by the system's own subsequent evidence
  ("no network access", against sixteen successful fetches). That needs a decision about what counts
  as contradiction and should be taken once the explicit-correction path exists and can be observed.
- **Do not rejoin on `correlation_id`.** It is not persisted (#1199 / BF-740). Thread the episode id
  explicitly.

## Tests

Against a **real** `EpisodicMemory`, not a hand-written fake. Finding 4 exists because the fake was
more permissive than production.

1. **The headline:** store a false claim → Captain corrects it **through a normal crew DM path, not
   through self-mod** → the claim is no longer the top hit for the question that produced it. Fails
   before the fix, and fails for the right reason (the producer, not the filter).
2. Survives a store reload — the mark is durable, not in-memory.
3. **All six paths** from finding 3 exclude it: sovereign, recent, anchor, anchor_scored, global
   `recall()`, and hybrid-with-FTS-on. One test enumerating all six; a subset is how finding 3
   happened.
4. Confidence band reflects the **post**-exclusion result set — an emptied result does not report
   `strong`.
5. `include_contradicted=True` returns it, so history is not destroyed.
6. A `SKIPPED` store outcome marks **nothing** — force the real store to return `SKIPPED` and assert
   no mark and no attribution to a nonexistent id.
7. A `False` return from `mark_episode_contradicted` produces a warning and does not report success.
8. **No true statement becomes less recallable:** an uncorrected episode from the same turn is still
   returned at the same rank. This is the constraint the issue sets and the one a careless fix breaks.
9. A stale last-turn record cannot retract an unrelated episode — reproduce finding 2's measured
   case (DM stores `ae7a…` while the field holds `stale-dag-id`) and assert the correct episode is
   marked, or none.

Mutation-check every fix.

## Tracking

- **#1200** closes when all four pieces land.
- File two new issues before closing: **claim-level retraction** (data-model change) and
  **dreaming consumes unfiltered recall**. Both are real; both are out of scope.
- `DECISIONS.md` — record the policy (exclusion, not demotion; contradicted-not-capability-claims)
  with its reasoning.

## Report back

- The producer chosen for the non-self-mod correction signal, and its call site.
- The six-path exclusion result, run.
- **Anything in this prompt that turned out to be untrue.**

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
