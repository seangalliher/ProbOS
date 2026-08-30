# AD-1293 — the turn's act-record must reach the episode, and a contradicted claim must not be recalled as evidence

**Status:** ready to build (UNBLOCKED)
**Closes:** #1200 (BF-741) — the write-claim subset. Advances #1087.
**Depends on:** AD-1285 (`133ceb2f`, `e25a1b1f`) — shipped.
**Estimated tests:** 22–26 new.
**Files:** `src/probos/types.py`, `src/probos/cognitive/dm/reply_pipeline.py`, `src/probos/cognitive/episodic.py`, `src/probos/config.py`. All four verified **clean** at `c75428bb`.

---

## Problem

Three defects were triaged as one cluster (#1087, #1090, #1200). Two of them —
#1087 and #1200 — share a single mechanism, and this AD builds it. #1090 does
**not** share it and is handled separately in AD-1294; do not touch it here.

The shared mechanism is stated as a hypothesis in #1338 and is **confirmed by
execution below**: the system has no name-addressable record of what a turn
actually did that survives to the places which need it. AD-1285 built the first
instance of such a record (`WriteLedger`) and consumed it in exactly one place
(the reply). It is discarded one step later, at the moment the episode that will
be recalled as evidence is constructed.

### 1. The verdict is computed and then thrown away, one step before it is needed

`_full_steps()` places the guard immediately before the episodic store:

```
reply_pipeline.py:216      self.step_4m_write_claim_guard,   # AD-1285 (#1087)
reply_pipeline.py:217      self.step_5_episodic_store,
```

`step_4m` computes `verdict = assess_write_claim(self.ctx.write_ledger)`
(`:1766`). `step_5_episodic_store` (`:1790`) then builds an `Episode` and never
reads `self.ctx.write_ledger` — the field is declared on the same context object
at `:150` and is in scope throughout.

### 2. The stored DM episode asserts success unconditionally

`reply_pipeline.py:1804-1805`:

```python
                    outcomes=[{
                        "intent": "direct_message",
                        "success": True,
```

`True` is a literal. #1200 says `outcomes[].success` "records whether the
*intent executed*, not whether the *claim was accurate*". On this path it
records neither — it is a constant.

**Measured on the live vessel** (`%LOCALAPPDATA%\ProbOS\data\chroma.sqlite3`,
1507 episodes, collection `episodes`):

| outcome set | `success=True` | `success=False` |
|---|---|---|
| all outcomes | 850 | **741** |
| `intent="direct_message"` | **20** | **0** |

The probe asserts its own premise: `success=False` occurs 741 times across the
store, so the field is capable of holding `False` and is written as `False` by
other paths. "20/20 True on the DM path" therefore means *this path never writes
it*, and cannot be confused with "everything genuinely succeeded".

### 3. AD-871's contradiction machinery is inert at both ends, in production

Enumerated in source with a control (the term appears 8 times in
`episodic.py`, so the probe can discriminate):

| line | function | role |
|---|---|---|
| 3456 | `_episode_to_metadata` | persists `contradicted_by_json` |
| 3580–3586, 3623 | `_metadata_to_episode` | loads it back |
| 1817 | `store` | comment only |

Zero filter sites. `contradicted` does not appear anywhere inside
`recall_for_agent`. `mark_contradicted` (`types.py:704`) has no production
caller.

**Measured on the live vessel:** `contradicted_by_json` is present on **1342 of
1507** episodes and its value is `[]` on **every one**. The key being written on
1342 records is what makes the all-empty result meaningful — it distinguishes
*never marked* from *never persisted*.

So the representation exists, round-trips, and nothing writes or reads it. This
is the repo's dominant defect shape (built, tested, inert), named in #1172 and
#1282.

### 4. Why the previous attempt at #1200 failed, and why this one is different

A three-piece build was implemented and reverted at `a16c6c53` (patch preserved
at `.git/BF741_REJECTED.patch`). Its decisive finding:

> `apply_correction_feedback` has **exactly one** production caller —
> `self_mod_manager.py:171` — reached only after a successful self-mod patch.
> … So if #1200's original case was a normal crew DM, **retraction can never be
> triggered for it**.

That attempt used *a Captain correction on a later turn* as the producer. This
AD uses **the turn's own write ledger, on the turn itself**. That change removes
three of the four blocking findings by construction:

- **Finding 1 (producer never fires):** the verdict is computed on every 1:1
  turn already, at `:1766`. No self-mod, no `/correct`, no Captain action.
- **Finding 2 (`_last_episode_id` retracts the wrong episode):** nothing is
  retracted. The episode is marked **before** it is stored, so no id transport
  exists to go stale.
- **Finding 4 (`store()` return contract ignored):** nothing is marked *after*
  a store, so `STORED`/`DUPLICATE`/`SKIPPED` cannot desynchronise a marker from
  its target.

**Finding 3 survives and is the hard part of this AD.** Exclusion must sit at
the final evidence boundary; the previous attempt filtered two paths and
measured contradicted episodes still reaching prompts through `recent`,
`anchor`, `anchor_scored`, global `recall()` and hybrid fusion. Section 4 below
addresses it directly and requires an enumeration, not a judgement call.

### What is deliberately NOT fixed here

The ledger sees **marker** channels only. A tool-loop write (`publish_finding`)
is still anonymous — that is AD-1295, and it is blocked. This AD therefore
closes the **write-claim subset** of #1200. #1200's own measured case is a
*capability denial* ("I don't have visibility into the actual output"), which no
write ledger can see; **69 first-person denial episodes** exist in the live store
today (`"I don't have"` ×42, `"I can't"` ×21, `"I cannot"` ×6, control probe
passed). Closing that subset needs a deterministic register per question and is
out of scope. **Do not attempt it. Do not add text matching.**

---

## Solution

Carry the turn's act-record into the episode, and stop offering a
self-contradicted episode as evidence.

Four sections. They must land together: a marker with no consumer is the exact
defect this AD exists to remove.

---

### Section 1 — `Episode` gains an explicit self-contradiction field

`contradicted_by` is documented as *"episode ids that contradict this record"*.
Contradiction by the turn's **own act-record** is a different relation and must
not be smuggled into a list whose elements are ids — a sentinel string there
would break every consumer that treats the entries as ids.

In `src/probos/types.py`, add one field to `Episode` (frozen dataclass; place it
with the AD-871 provenance block, after `contradicted_by`):

```python
    # AD-1293 (#1200): channels whose durable write this turn CLAIMED-adjacent
    # activity for and which produced nothing, recorded at encode time from the
    # turn's own WriteLedger. Distinct from ``contradicted_by`` (episode ids):
    # this is contradiction by the turn's own act-record, known before the
    # episode is ever stored, so no retraction transport exists to go stale.
    # Empty = "no write channel ran, or every channel that ran also wrote" —
    # never "unassessed", which is why the ledger's ABSTAIN maps to empty here
    # only after ``evaluated`` is checked (AD-1269).
    self_contradicted_channels: list[str] = field(default_factory=list)
```

Add a module-level predicate beside `mark_contradicted`:

```python
def episode_is_self_contradicted(episode: Episode) -> bool:
    """AD-1293: whether this episode's own act-record contradicts it.

    One shared predicate so recall surfaces cannot drift apart — the failure
    mode that reverted the first #1200 attempt at ``a16c6c53``.
    """
    return bool(episode.self_contradicted_channels)
```

Export it from `types.py`'s public surface if one is declared there.

**Do not** add a `mark_*` mutator. Nothing marks after the fact by design.

---

### Section 2 — persist and round-trip the field

In `src/probos/cognitive/episodic.py`:

**2a.** `_episode_to_metadata` (`:3456` area) — persist beside the existing key:

```python
            "self_contradicted_json": json.dumps(ep.self_contradicted_channels or []),
```

**2b.** `_metadata_to_episode` (`:3562`, decode block at `:3580-3586`, construction
at `:3623`) — decode with the same defensive shape already used for
`contradicted_by_json`: a non-list or unparseable value degrades to `[]`, never
raises. Pass it into the `Episode(...)` construction.

Chroma metadata values must be scalars; a JSON string matches the existing
convention exactly. Follow it.

**2c.** Legacy episodes carry no such key. The decode must yield `[]` for them.
Assert this with a test that materialises an `Episode` from a metadata dict with
the key absent.

---

### Section 3 — the producer: mark at encode time in `step_5_episodic_store`

In `src/probos/cognitive/dm/reply_pipeline.py`, `step_5_episodic_store`
(`:1790`).

Read `self.ctx.write_ledger` and derive the value **before** constructing the
`Episode`:

```python
                ledger = self.ctx.write_ledger
                # AD-1293 (#1200): the AD-1285 verdict is computed one step
                # earlier (step_4m, :1766) and was previously discarded here.
                # An unevaluated ledger yields [] — "no channel ran" and "a
                # channel ran and wrote nothing" stay distinct (AD-1269).
                self_contradicted = (
                    sorted(ledger.wrote_nothing) if ledger.evaluated else []
                )
```

Pass `self_contradicted_channels=self_contradicted` to the `Episode(...)` call.

**Also replace the hardcoded literal at `:1805`.** `"success": True` must become
the honest value:

```python
                        "success": not self_contradicted,
```

This is a behaviour change on a measured-constant field, so state it explicitly
in the commit message. A turn where a durable-write channel ran and wrote
nothing is not a successful `direct_message` outcome, and 741 outcomes elsewhere
in the live store already carry `False`, so no consumer can be assuming the
field is always `True` on this path — **verify that assumption before relying on
it**: enumerate consumers of `outcomes[].success` where `intent ==
"direct_message"` and report what you find. If a consumer would break, keep
`success` as-is, record why in the prompt's build report, and rely on the new
field alone.

Do not read `self.ctx.response_text` for this. The verdict remains structural.

---

### Section 4 — the consumer: exclude from evidence recall, keep reachable as history

This is the section that reverted the previous attempt. Its finding, reproduced
against a real `EpisodicMemory` with one contradicted episode:

```
sovereign          = []                  <- filtered
recent             = [contradicted-id]
anchor             = [contradicted-id]
anchor_scored      = [contradicted-id]
global recall()    = [contradicted-id]
hybrid (fts on)    = [contradicted-id]
```

**Do not repeat that.** The method is enumeration, not judgement.

**4a. Enumerate.** `episodic.py` has 18 public `recall`/`recent`/`get_*` surfaces
and 16 `_metadata_to_episode` call sites. Produce a table classifying **every
one** as:

- **EVIDENCE** — its result can reach an LLM prompt. Must filter.
- **HISTORY** — id lookup, dedup, maintenance, stats, embeddings. Must **not**
  filter (a suppressed record must stay auditable — this repo supersedes, it
  does not rewrite).

Known surfaces, for your table (line numbers at `c75428bb`; re-verify):
`recall` 2552 · `recall_with_confidence` 2567 · `recall_with_control` 2730 ·
`recall_by_anchor_scored` 2829 · `recall_for_agent` 2974 ·
`recall_for_agent_with_confidence` 2988 · `recent_for_agent` 3197 ·
`recall_by_intent` 3242 · `recent` 3282 · `recall_for_agent_scored` 3666 ·
`recall_weighted` 3834 · `recall_valid_at` 4055 · `recall_by_anchor` 4072 ·
`get_episode_metadata` 1927 · `get_by_ids` 1981 · `get_embeddings` 3307 ·
`get_stats` 3357 · `get_episode_ids_older_than` 2430.

Paste the table into the build report. A surface you cannot classify is a
blocker, not a coin flip.

**4b. Filter with the single shared predicate** from Section 1. Every EVIDENCE
surface calls `episode_is_self_contradicted` — no surface reimplements the test.

**4c. Placement.** Filter **after** every fusion/merge and **before** any
confidence-band computation. The previous attempt placed the sovereign filter
*before* hybrid fusion, which re-hydrated the excluded hit afterwards, and
computed the confidence band before filtering — so an emptied result still
reported `strong` and suppressed cross-agent recovery. Verify by test that:
- a hybrid/FTS-fused path cannot return an excluded episode; and
- a result set emptied by exclusion does not report a `strong` confidence band.

**4d. History stays reachable.** Every EVIDENCE surface takes
`include_self_contradicted: bool = False`. `get_by_ids` and the HISTORY surfaces
are unfiltered and unchanged. This is the "supersede, not delete" requirement:
the episode is never removed, never rewritten, and is always retrievable by id.

**4e. Out of scope, record only.** Dreaming consumes unfiltered `recent()` and
`recall_by_intent()` (`dreaming.py:217`, `:436`), so a marked episode keeps
influencing trust, routing and procedure seeding. If your Section 4a
classification makes those two EVIDENCE surfaces, dreaming inherits the filter —
say so explicitly in the build report and confirm no dream test regresses. Do
**not** add separate dreaming logic here.

---

### Section 5 — config

Add to `src/probos/config.py`, beside `WriteClaimGuardConfig` (`:6493`):

```python
class SelfContradictionRecallConfig(BaseModel):  # AD-1293 (#1200)
    enabled: bool = Field(default=True, description=...)
```

Default **ON**, for the reason `WriteClaimGuardConfig` already records: this is
a safety control, not a capability, and a default-OFF control defends nothing
(#13(a), AD-1157 failure mode). It is safe on because the marker is empty unless
a write channel ran and wrote nothing — so a ship with no durable-write channel
wired is byte-identical. Wire the flag at the filter, so turning it off restores
pre-AD-1293 recall exactly.

---

## Tests

New file `tests/test_ad1293_turn_record_reaches_episode.py`.

**Representation (Section 1–2)**
1. `Episode` defaults `self_contradicted_channels` to `[]`.
2. Round-trip: `_episode_to_metadata` → `_metadata_to_episode` preserves a
   populated list.
3. Legacy metadata **without** the key materialises `[]`, not an error.
4. Malformed value (`"not-json"`, `'{"a":1}'`) degrades to `[]`.
5. `episode_is_self_contradicted` — true for non-empty, false for empty.

**Producer (Section 3)**
6. Ledger unevaluated → episode marker `[]`.
7. Ledger evaluated, channel wrote → `[]`.
8. Ledger evaluated, notebook ran and wrote nothing → `["notebook"]`.
9. Two channels, one wrote and one did not → only the failing channel, sorted.
10. `outcomes[0]["success"]` is `False` exactly when the marker is non-empty
    (or, if Section 3's consumer audit blocked that change, a test asserting the
    audit's recorded reason).
11. The guard's disclosure text and the marker agree on the same turn — one test
    crossing step_4m → step_5, not two tests each stopping at the boundary.

**Consumer (Section 4)**
12. Store → recall: a marked episode is absent from `recall_for_agent`.
13. …absent from `recent`.
14. …absent from `recall_by_intent`.
15. …absent from global `recall()`.
16. …absent from the anchor path.
17. …absent after hybrid/FTS fusion (4c).
18. A result emptied by exclusion does **not** report a `strong` confidence band.
19. `get_by_ids` **returns** it — history is preserved.
20. `include_self_contradicted=True` returns it on an EVIDENCE surface.
21. An unmarked episode is returned by every EVIDENCE surface — no true
    statement becomes less recallable (#1200's binding constraint).
22. Config off → recall is byte-identical to pre-AD-1293 for a marked episode.

**Persistence**
23. Store → reload the collection → the marker survives.

Use a **real** `EpisodicMemory` against a temp directory for 12–23. The previous
attempt's hand-written fake returned `None` from `store` and `True` from the
marker, and therefore could not have caught two of the four blocking findings.
A fake that cannot fail is not a test.

**Assert the probe reached the branch.** For each exclusion test, first assert
the episode IS returned with `include_self_contradicted=True`. A test that finds
nothing must be distinguishable from one whose fixture never stored anything.

---

## What this does NOT change

- `agentic_dispatch.py`, `cognitive_agent.py` — foreign-modified, off-limits.
  The tool half is AD-1295.
- `oracle_service.py`, `crew_executor.py` — AD-1294.
- No text matching, ever. The verdict stays structural (AD-1285's finding: a
  text-reading branch was built and deleted because `publish_finding` is a tool,
  not a marker, so a genuine save reached the guard with an empty ledger and the
  branch contradicted **truthful** replies).
- No retroactive marking, no `/correct` wiring, no `apply_correction_feedback`
  changes, no `_last_episode_id` transport.
- No ranking or weight tuning. BF-739 established that competing against a
  self-replenishing episode population is unwinnable; this removes a record from
  the evidence set rather than reweighting it.
- No change to `contradicted_by` or `mark_contradicted`.
- Do not touch `README.md`, `docs/architecture/federation.md`,
  `docs/development/roadmap.md`.

---

## Test gate — read this before running anything

**The tree cannot run the full Python suite at `c75428bb`.**
`src/probos/tools/browser/session.py` imports `RedirectEscalation`, which
in-flight foreign work removed; roughly **423 tests fail** on collection for
reasons unrelated to this AD.

Gate in a **linked worktree**:

```powershell
git worktree add d:\probos-gate1293 HEAD
# apply your staged patch into the worktree, then:
cd d:\probos-gate1293
$env:PYTHONPATH='d:\probos-gate1293\src'
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q
```

`PYTHONPATH` shadows the editable install — without it you are gating the main
tree. Prove the shadow took: `python -c "import probos; print(probos.__file__)"`
must print the worktree path.

Known worktree artefact: **3 `test_phantom_api_precheck_*` tests fail in a
linked worktree and pass in the main tree** (they shell out to repo-relative
scripts). Verify, then count them as passes.

Focused gate while iterating:

```powershell
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1293_turn_record_reaches_episode.py tests/test_ad1285_write_claim_guard.py -q -p no:randomly
```

Reconcile test arithmetic: `before + new == after`. A green suite at the wrong
count has hidden a swallowed test before in this repo.

---

## Acceptance criteria

- `Episode.self_contradicted_channels` round-trips through Chroma metadata and
  defaults to `[]` for legacy records.
- The AD-1285 verdict reaches the stored episode on the same turn; one test
  crosses step_4m → step_5.
- The Section 4a classification table is in the build report, covering all 18
  surfaces and all 16 materialisation sites.
- A self-contradicted episode is absent from **every** EVIDENCE surface,
  including after hybrid fusion, and present via `get_by_ids`.
- No unmarked episode becomes less recallable.
- Config off ⇒ byte-identical recall.
- Run the `Diff Reviewer` subagent on the staged diff **with a different model
  than the one that wrote the code**, and repair Critical/High findings before
  committing.
- Verify all changes comply with the Engineering Principles in
  `.github/copilot-instructions.md`.

---

## Tracking

- `PROGRESS.md` — AD-1293 entry.
- `DECISIONS.md` — record the storage decision explicitly: *a self-contradicted
  claim is stored, marked at encode time, excluded from evidence recall, and
  kept reachable as history.* Record the rejected alternatives (block at write;
  down-weight at recall) and why.
- Close **#1200** only for the write-claim subset; leave a comment naming the
  capability-denial subset as still open, with the 69-episode live measurement.
- Comment on **#1087** and **#1338** that item 1 remains blocked pending AD-1295.

---

## Verified Against Codebase (2026-08-29, `c75428bb`)

```
reply_pipeline.py:150    write_ledger: WriteLedger = field(default_factory=WriteLedger)
reply_pipeline.py:216            self.step_4m_write_claim_guard,  # AD-1285 (#1087)
reply_pipeline.py:217            self.step_5_episodic_store,
reply_pipeline.py:1766           verdict = assess_write_claim(self.ctx.write_ledger)
reply_pipeline.py:1804                       "intent": "direct_message",
reply_pipeline.py:1805                       "success": True,
reply_pipeline.py:1832           await self.ctx.runtime.episodic_memory.store(episode)
types.py:646             contradicted_by: list[str] = field(default_factory=list)
types.py:704             def mark_contradicted(episode: Episode, contradicting_id: str) -> Episode:
episodic.py:3456                 "contradicted_by_json": json.dumps(ep.contradicted_by or []),
episodic.py:3562         def _metadata_to_episode(
episodic.py:3580                 contradicted_raw = metadata.get("contradicted_by_json", "")
episodic.py:3623                 contradicted_by=contradicted_by,
config.py:6493           class WriteClaimGuardConfig(BaseModel):  # AD-1285 (#1087 / BF-687)
```

### Absence verified (enumerations run, with controls)

```
CLAIM: no recall path filters on contradicted_by
RUN:   grep 'contradicted' src/probos/cognitive/episodic.py   -> 8 hits (control: term present, probe discriminates)
FOUND: 3 functions only — store (comment), _episode_to_metadata (persist), _metadata_to_episode (load)
       'contradicted' inside recall_for_agent: False
HOLDS: yes

CLAIM: mark_contradicted has no production caller
RUN:   grep 'mark_contradicted|contradicted_by' src/probos/**
FOUND: types.py (definition + its own replace()), episodic.py (persist/load only)
HOLDS: yes

CLAIM: step_5 never reads ctx.write_ledger
RUN:   grep 'write_ledger|consulted_with|assess_write_claim' src/probos/**  -> 26 hits, 4 files
FOUND: reply_pipeline.py sites are 150, 975, 991, 1334, 1350, 1743, 1766, 1780 — none in 1790-1836
HOLDS: yes
```

### Live-vessel measurements (`%LOCALAPPDATA%\ProbOS\data\chroma.sqlite3`)

```
collection 'episodes': 1507 embeddings

contradicted_by_json  present on 1342 episodes; distinct values = [('[]', 1342)]
  PREMISE ASSERTION: key IS written on 1342 records, so all-empty means NOT MARKED,
  not "not persisted".

outcomes[].success    True=850  False=741        <- False is REACHABLE
  intent='direct_message'  True=20  False=0      <- this path never writes False

source_type           reflection=679  observation=663   (no class for capability claims)

correlation_id        1131 rows, 539 NON-EMPTY, 538 distinct, only 1 id on >1 episode
  NOTE: #1200 cites BF-740 (#1199) as "correlation_id is not persisted". That is
  REFUTED — it is persisted. But it is effectively unique-per-episode, so pairing a
  claim episode with a later contradiction episode by correlation_id remains
  unusable. The conclusion stands; the stated reason does not. Do not design on it.

first-person denials in live docs (control probe returned 3 hits on a known substring):
  "I don't have" ×42   "I can't" ×21   "I cannot" ×6   |   "I wrote"/"I saved"/"I published" ×0
  -> the DENIAL shape is live and common; the WRITE-CLAIM shape is not currently in
     the store. This AD closes the write-claim subset only.
```
