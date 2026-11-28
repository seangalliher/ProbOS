# AD-1346 M3e4d11 (#1604): part (c) of the pending `workforce.py` scopes, six work item field scopes classified as the ship's, in shadow

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-05
**Revised by:** the orchestrator (Copilot), 2026-11-06: §11's two `src` Grep records count 30 and 14 lines (they said 32 and 13; the listed lines are unchanged, re-run on `63fbc874`), and Absence Verified 3 says "the other 13 lines" (it said 12); no other change.
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-05: Amendment A1 (review round 1): `compare_and_set_work_item_assignment`'s reason describes its compare-and-set; R165's cost counts step writes per intent; D351's rejection cites D341. No classification or count changes.
**Revised by:** the orchestrator (Copilot), 2026-11-06: round 2 of the review found that A1's wording of R165's cost bullet still counted `update_step`'s confirm and reject loops and `set_steps` as unconditional; they run only when the agent may validate and may seed. The bullet says so; no other change.
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-06: Amendment A3 (round-three brake): R165's cost bullet gives the step routes' helper calls as an upper bound. No classification or count changes.
**Status:** build-ready. **Issue:** #1604 (AD-1346 M3, epic #1601). The eleventh part of M3e4d (register R113) and part (c1) of register R160. No new AD or BF number (`scripts/ad_ceiling.py`: CEILING AD-1358, as reported by the request). **Tier:** test (M1: the census rows and the guards that pin them; no `src` file), docs (M2). Nothing parked.
**Dependencies:** AD-1346 M3e4d6 to M3e4d10. The build's base is the merge of the batch that carries M3e4d6 to M3e4d8 into `origin/main`, with M3e4d9 and M3e4d10 built on it. The Architect sends an amendment for any SEARCH that differs there.
**Anchors:** every SEARCH text in §7 was read on the scratch commit `63fbc874` (tree `cc9d5e9b`), which is `8ecf968d` plus M3e4d9's and M3e4d10's M1 pairs, applied by tool. The SEARCH of M2-02 is the last bullet of M3e4d10's `DECISIONS.md` entry as M3e4d10's contract writes it; it is not in that tree. The block count is in §12. No new file. Two files are regenerated (M2).
**Contract file:** `prompts/ad-1346-m3e4d11-workforce-field-rows.md`.

**Identifiers.**
- Register rows: earlier slices' rows are written "register R<n>". This contract adds R164 and R165.
- Tests: WC1 and WC3 (`tests/test_ad1346_admission_store_census.py`) are edited. No test is new.
- Mutation rows are WN-<n>. Decisions D350 to D354 follow M3e4d10's D345 to D349.

**Which text describes the head.**
- **Records of the read commit `63fbc874`:** the Status and Anchors paragraphs, §1, §11 (Verified Against Codebase, Absence Verified), every line number cited in any section, and every SEARCH text in §7 except M2-02's.
- **Files whose SEARCH text the M3e4d6 to M3e4d10 work wrote, and that this contract edits** (`git diff --name-only 8ecf968d..63fbc874` lists the two test files):
  - `tests/fixtures/ad1346_store_census.py`: M1-01 `:234-242`, whose name lines M3e4d8's M1-14 wrote and whose closing `)` under `"WorkItemStore.transition_crew_session_terminal_with_trust",` M3e4d10's M1-01 wrote; M1-02 `:244-247`, written by M3e4d10's M1-02; M1-03 `:371-374`, whose first line M3e4d10's M1-03 wrote.
  - `tests/test_ad1346_admission_store_census.py`: M1-04 `:11-12`, M1-05 `:18`, M1-06 `:99-104`, M1-07 `:116`, M1-08 `:135-137` and M1-09 `:142-144`, written by M3e4d10's M1-04 to M1-09.
  - `PROGRESS.md`: M2-01, the title line and the empty line under it, `:1-2`.
  - `DECISIONS.md`: M2-02, M3e4d10's last bullet `- *Reversal.* Revert the M3e4d10 commits.`, which M3e4d10's M2-02 adds.
  - Both tracker SEARCH texts match whether or not BF-952's tracker pairs land first.
- **Edited, and no M3e4d6 to M3e4d10 commit writes its SEARCH text:** none.
- **Cited, not edited:**
  - `src/probos/workforce.py` (M3e4d8 edited it; the cited lines are those of §1, read on `63fbc874`, whose `workforce.py` is `8ecf968d`'s);
  - `src/probos/cognitive/crew_session.py`, `src/probos/cognitive/crew_finalizer.py`, `src/probos/cognitive/crew_executor.py`, `src/probos/cognitive/crew_synth.py`, `src/probos/cognitive/turn_promotion.py`, `src/probos/cognitive/dm/reply_pipeline.py`, `src/probos/routers/workforce.py` and `src/probos/agents/quartermaster.py` (the lines of §1);
  - `tests/fixtures/ad1346_file_write_census.py:204` (the attachment store's row);
  - `DECISIONS.md:1167` (D218) and `:1197` (D239);
  - `logs/ad1346/measure-workforce-scopes.txt`;
  - the M3e4d10 contract (`prompts/ad-1346-m3e4d10-workforce-outbox-rows.md`), whose R160 and R163 rows this one advances or follows.
- Re-read each SEARCH and each cited line on the build's base. If one differs, the Architect sends an amendment; the Builder does not adapt it.
- **Parts that describe the candidate's head and name no commit:** the Milestones and Tests lists, §2 to §6, §8's tracker text, §9, §10, §12, §14 and §15.
- **Text inside each REPLACE** (comments, row reasons, docstrings) is head text.
- Where a record and the candidate differ, re-measure; the record does not bind.

**Milestones:**
- **M1 (test):** the six `System` rows; their names leave `_WORKFORCE_PENDING`; WC1's and WC3's counts and docstrings.
- **M2 (docs):** `PROGRESS.md`, `DECISIONS.md`, and the AD ledger regenerated by its tool.

**Process:**
- Each milestone is one Builder delegation and one local commit. Stage by explicit path, never `git add -A`.
- Commit subjects take the form `AD-1346 M3e4d11, M<n>: ... (#1604)`.
- One cross-family review (`gpt-6.1-sol`) of M1 against §14.
- One mutation campaign of record on the M1 tree (§10), after an unmutated baseline passes.
- The broad gate runs once for the batch that carries this slice: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1346-m3e4d11 --receipt logs/gates/ad1346-m3e4d11.receipt.json`, or the batch's own label if this slice is batched with M3e4d9 and M3e4d10.

**Tests:** no `def test_` function is added or removed. Each edited test file's count is unchanged (`tests/test_ad1346_admission_store_census.py`: 5).

## 1. Problem

- After M3e4d10, `workforce.py` holds 27 `Pending` scopes (`_WORKFORCE_PENDING`, `tests/fixtures/ad1346_store_census.py:214-242` on `63fbc874`), one `StoreCheck` row and 20 `System` rows. Register R160's part (c) is the work item fields.
- **Part (c) by measure.** It is 7 scopes and 10 points. These are the seven rows of `logs/ad1346/measure-workforce-scopes.txt:25-31`, measured by `sql_write_points` on the M3e4d7 tree; the total is a hand sum of those rows. On `63fbc874`, a Grep for `"UPDATE work_items SET` lists exactly these 10 lines inside the seven scopes, each 5 above its line in the measure file. A Grep for `INSERT`, `DELETE FROM` and `REPLACE INTO` finds none between `:8646` and `:10172` (§11):

  | Scope (`WorkItemStore.`) | def | Points | What the statements write | Production callers (`src`) |
  |---|---|---|---|---|
  | `compare_and_set_work_item_assignment` | `:8646` | `:8733` | `assigned_to`, `metadata`, `updated_at` | none (Absence 3) |
  | `update_work_item` | `:8763` | `:8837` | every non-immutable key of `**updates` (`created_by` is in `_IMMUTABLE_FIELDS`, `:1623`, skipped at `:8822-8823`), the value context columns, `updated_at` | `routers/workforce.py:300` (`**body`); `set_steps` (`:9060`) and `update_step` (`:9097`); `quartermaster.py:342`, `:385`, `:413`; `cognitive_agent.py:2316`; `reply_pipeline.py:1927`; and others (§11) |
  | `confirm_value_context` | `:8904` | `:8981` | the provenance columns of pending declarations (`with_value_confirmation`, `:562-578`: `confirmed_by`, `confirmed_at`, `confirmation_kind`), `updated_at` | `crew_session.py:3911` (`CrewSessionService.confirm_value_context`, `:3864`) |
  | `merge_work_item_metadata` | `:9132` | `:9379`, `:9392`, `:9399`, `:9405` | `metadata`, with `status` and `actual_tokens` when they change, `updated_at` | `crew_executor.py:2407`, `:2946`, `:3064`; `crew_session.py:3249`; `crew_synth.py:1152`; `routers/workforce.py:901`; `turn_promotion.py:715`, `:835`, `:1061` |
  | `compare_and_set_work_item_verification` | `:9650` | `:9779` | `verification`, `metadata`, `actual_tokens`, `updated_at` | `crew_finalizer.py:1771`, `:2800` |
  | `publish_work_item_metadata_with_child_barrier` | `:9805` | `:10008` | `metadata`, `status`, `updated_at` | `crew_session.py:6364` |
  | `transition_crew_session_terminal_with_trust` | `:10044` | `:10141` | `metadata`, `status`, `updated_at` | `crew_session.py:6600` |

- **No scope takes an author id.** None of the seven signatures has a `created_by`, an `author_id` or an equivalent parameter (`:8646-8658`, `:8763`, `:8904-8911`, `:9132-9162`, `:9650-9669`, `:9805-9822`, `:10044-10056`). The `expected_assigned_to` keywords are compare-and-set predicates on the item's current assignee. `merge_work_item_metadata`'s `source` is not written by its statements (`:9378-9407`); `turn_promotion.py:725` and `:842` pass an agent id there.
- **What the payloads carry.**
  - `crew_executor.py:2905-2938`: the patch at `:2946` is `{"crew_execution": evidence, ...}`. `_build_execution_evidence` (`:1019-1080`) records the child's `assigned_to` and `output_summary`, which `_output_summary` (`:916-923`) takes from the agent's output. The full output is written to the attachment store with `origin="agent_artifact"` (`:2921-2926`); that store's row is `System` (`tests/fixtures/ad1346_file_write_census.py:204`).
  - `crew_session.py`: every patch is a contract or a marker that `CrewSessionService` validates and dumps: `:3414`, `:4425`, `:4687`, `:5045-5056`, `:5234`, `:5391`, `:5653`, `:6079-6085`, `:6309-6315`, `:6596`. The published contract carries `last_result_summary` and `result_artifact_id` (`:6290-6301`).
  - `crew_synth.py:1152-1165`: counts, a reference and a fixed caveat string.
  - `turn_promotion.py:715-726`, `:835-843` and `:1061-1072`: a lease marker, a stranded reason and time, and a run id.
  - `routers/workforce.py:886-903`: the refs of the Captain's uploaded inputs.
  - `crew_finalizer.py:1647`, `:1732` and `:2740`: each verification passed to the store is `_verification_document` (`:3347-3391`). It records `producer_agent_id` and rounds (`:3397-3418`), each with the producer's `result_summary` and a verdict document carrying `critique` (`:3421-3427`).
- **`confirm_value_context`'s confirmer.** The Captain or an agent with chain-of-command authority over the declaration's source confirms (`crew_session.py:3869-3903`). The store writes no text.
- **Why `update_work_item` is different.** The DM reply pipeline hands it an agent's own text with that agent's id:
  - `set_steps(task_id, parsed.plan, gate_completion=True, facilitator=actor)` (`reply_pipeline.py:1945`; `:1859` for the prose fallback), with `actor = self.ctx.agent_id or "agent"` (`:1939`). `set_steps` writes the plan's labels as `steps`, and `facilitator` into `metadata` (`workforce.py:9032-9060`).
  - `update_step(task_id, idx, status="rejected", actor=actor, note=reason)` (`reply_pipeline.py:1953-1955`). `update_step` writes `confirmed_by = actor` and `note` into the step (`workforce.py:9087-9097`).
  - The route passes `actor=body.get("actor")` and `note=body.get("note")` (`routers/workforce.py:800-803`).
  - D239's three conditions hold for the step write (§3, D352). The id enters through `set_steps` and `update_step`, not through `update_work_item`'s signature.
- **The rule.**
  - D239 (`DECISIONS.md:1197`): agent-attributed when "a write statement records text or a work product with the id of its author, creator or requester, the writing function takes that id from a caller, and a production caller passes an agent's id or an HTTP request's value there". The same entry says: "Rows whose agent id names the agent they are about, ... decisions whose decider is not the text's author, ... rows with no text or no author column, and copies of an agent's state are the ship's".
  - D218 (`:1167`): "a copy a ship's service makes of an agent's content, with or without the author's id" is the ship's.
- **Hidden pins this slice meets.** WC1 counts `STORE_WRITE_SCOPES` by type (`tests/test_ad1346_admission_store_census.py:116`) and requires its keys to be the scanned scopes (`:113-115`). WC3 pins the pending scopes as 27 (`:142-144`). No other test counts `System` or `Pending` values (Absence 4). Outside the fixture's tuple, tests name three of the seven scopes only through code objects or prose, which no edit here touches (Absence 2).

## 2. Solution

- Six scope names leave `_WORKFORCE_PENDING`. Each becomes a `System(SHIP, ...)` row whose reason names what its scope's statements write, including what a production caller's payload carries (D351).
- `WorkItemStore.update_work_item` stays in `_WORKFORCE_PENDING` (D352; register R165).
- No `src` file changes. No check is added, so nothing is presented, refused or charged.
- Counts (hand arithmetic from WC1's pinned 20, 69 and 27):
  - `STORE_WRITE_SCOPES` holds 20 `StoreCheck`, 75 `System` and 21 `Pending` rows in 12 files;
  - `_WORKFORCE_PENDING` holds 21 names;
  - `STORE_WRITE_FILES` is unchanged (67 rows).

## 3. Decisions (numbered after M3e4d10's D345 to D349)

- **D350 The cut** (question 1).
  - This slice: register R160's part (c1), 6 scopes and 9 points, all the ship's (D351), with no `src` change. Part (c2), `update_work_item`, 1 scope and 1 point, is its own slice with a `src` change (D352).
  - Ranked:
    1. this;
    2. all seven, with a check in `update_work_item`. This brings a `src` change, a hand-off test, a tally test and a keyword that the route's `**body` would bind (`routers/workforce.py:300`) into a slice that is otherwise rows. Its design questions are open (register R165);
    3. all seven as `System`, on the precedent of `ChatThreadStore.update_thread` and `ProjectStore.update_project`. Rejected: those take no author id from any caller, while `update_work_item`'s step write does, through `set_steps` and `update_step` (§1);
    4. all seven kept pending: no later part gives these six a new fact.
- **D351 The rows** (question 2; D218's and D239's rule).
  - **`compare_and_set_work_item_assignment`.** It writes `assigned_to`, which names the agent the row is about (D239), and a caller's `metadata`; no `src` module calls it (Absence 3).
  - **`confirm_value_context`.** It writes a pending declaration's confirmation fields and `updated_at`, with no text. The confirmer is the Captain, or an agent with authority over the declaration's source (`crew_session.py:3869-3903`): "decisions whose decider is not the text's author" and "rows with no text" are the ship's (D239).
  - **`merge_work_item_metadata`.** It takes no author id, and its statements write no `created_by`. Each production caller's patch is a record a ship's service composes (§1). The crew executor's record holds its assignee's id and a summary of the agent's output: a copy a ship's service makes of an agent's content, which D218 makes the ship's.
  - **`compare_and_set_work_item_verification`.** The crew finalizer composes the record, with the producer's id, the producer's result summaries and the verdicts' critiques (§1): D218.
  - **`publish_work_item_metadata_with_child_barrier` and `transition_crew_session_terminal_with_trust`.** `CrewSessionService` composes the contract, synthesis and recovery records that each patch carries (§1): D218. Their trust outcomes and delivery records are written by `_insert_crew_trust_effects` and `_insert_crew_session_delivery`, whose rows are already `System`.
  - **Threads, start-up, shutdown.** No call is added, so the admission service's lifetime does not apply.
  - Ranked, for the rows that a check could also have taken:
    1. `System` for all six;
    2. `confirm_value_context` as a `StoreCheck` presenting `confirmed_by`, on `MessageStore.endorse`'s precedent (`voter_id`, no text). Rejected: that row is D231's Ward Room entry, settled before D239, whose later rule makes a decision on another's text the ship's (register R164);
    3. `merge_work_item_metadata`, `compare_and_set_work_item_verification` and `publish_work_item_metadata_with_child_barrier` as checks presenting the item's assignee or the producer. Rejected: each id is in a payload a ship's service composes, and D218 rejects counting such a copy as the author's;
    4. kept pending: no later part gives them a new fact.
- **D352 `update_work_item` stays pending** (question 1).
  - D239 holds for its step write. Text: the plan's labels and a rejection note. The id of its author: `facilitator` and `confirmed_by`. Taken from a caller: `set_steps(facilitator=)` and `update_step(actor=)`. Passed by a production caller: the replying agent's id (`reply_pipeline.py:1939`, `:1945-1955`) and an HTTP request's `actor` (`routers/workforce.py:800-803`).
  - Its check needs a design this slice does not settle (register R165): where the id enters, how the route's `**body` is kept from binding it, and how the other callers count.
  - Ranked:
    1. pending, with its own slice;
    2. `System`. Rejected (D350 option 3);
    3. a check that reads the step's actor out of the `steps` payload. Rejected: the store would parse a payload to find its author, and `metadata`'s `facilitator` would still be unread.
- **D353 Guards and pins** (question 3).
  - WC1's type counter becomes 20, 75 and 21. WC3's pending pin becomes 21. Their docstrings and the module docstring follow.
  - WC1's key equality fails on a renamed or dropped row, or on a renamed pending name (WN-1, WN-5). Its counter fails on a row put back to pending, on a name left in `_WORKFORCE_PENDING` (the dict spread comes last and overrides the `System` row), or on a row made a check (WN-2 to WN-4).
  - Not moved: WM1 (20 checks), WM2, WM5, T16, SK7, WC2, WC4, WC5, the effect census's `store_write` string and the seam census's `check_at` note. No check is added, and neither string lists a slice that adds only rows.
  - Ranked:
    1. this;
    2. a test that the crew finalizer's verification document and the crew executor's evidence carry the ids that D351 names. Rejected: it pins a payload's shape, not a check, and no check is added;
    3. a WC3 pin listing the six names. Rejected: WC1 already fails on each mutation in §10.
- **D354 Cost and register rows** (questions 4 and 5).
  - No call is added, so there is no hot-path cost and `admission.shadow_enabled` is not involved. No `SystemConfig` field is added. Sizing a future `update_work_item` check is register R165's.
  - R113 and R160 are advanced. New: R164 (what this slice does not see) and R165 (part (c2)'s facts and options).

## 4. Milestones and focused gates

| Milestone | Files | Focused gate |
|---|---|---|
| M1 | `tests/fixtures/ad1346_store_census.py`, `tests/test_ad1346_admission_store_census.py` | `pytest tests/test_ad1346_admission_store_census.py tests/test_ad1346_admission_store_writes.py tests/test_ad1346_admission_store_family_census.py tests/test_ad1346_admission_ticket_sinks.py -n 0`; `pytest tests/test_ad1346_admission_store_census.py --collect-only -q -p no:cacheprovider -n 0` (record the count: 5) |
| M2 | `PROGRESS.md`, `DECISIONS.md`; regenerated `docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json` | `python -P scripts/gen_ad_ledger.py`, then `python -P scripts/gen_ad_ledger.py --check`, then `pytest tests/test_ad1184_ad_ledger.py -n 0` |

## 5. Consumers of every value this changes

- **`STORE_WRITE_SCOPES`:**
  - WC1 and WC3 count its `System` and `Pending` values.
  - `store_write_check_functions` (the fixture's `:377-379`), WM1 (`tests/test_ad1346_admission_store_writes.py:313`) and the via rows (`:341`) filter on `StoreCheck`.
  - WK3 reads one key (`tests/test_ad1346_admission_store_family_census.py:170`) (Absence 4).
- **`_WORKFORCE_PENDING`:** only the fixture's spread (`:373`) reads it.
- No `src` value changes.

## 6. Tests

| File | M | Cases | What |
|---|---|---|---|
| `tests/test_ad1346_admission_store_census.py` | M1 | unchanged (5) | the module docstring's WC1 and WC3 counts; WC1's docstring and counter; WC3's docstring and pending pin |

## 7. The contract

### 7.1 M1

**M1-01** (`tests/fixtures/ad1346_store_census.py`)

SEARCH:
```
    "WorkItemStore.adopt_child_plan_with_parent_metadata",
    "WorkItemStore.compare_and_set_work_item_assignment",
    "WorkItemStore.update_work_item",
    "WorkItemStore.confirm_value_context",
    "WorkItemStore.merge_work_item_metadata",
    "WorkItemStore.compare_and_set_work_item_verification",
    "WorkItemStore.publish_work_item_metadata_with_child_barrier",
    "WorkItemStore.transition_crew_session_terminal_with_trust",
)
```
REPLACE:
```
    "WorkItemStore.adopt_child_plan_with_parent_metadata",
    "WorkItemStore.update_work_item",
)
```

**M1-02** (`tests/fixtures/ad1346_store_census.py`)

SEARCH:
```
#: AD-1346 M3e4b (D229), M3e4d1 (D284), M3e4d2 (D291), M3e4d3 (D298), M3e4d4 (D306), M3e4d5 (D313), M3e4d6 (D320),
#: M3e4d7 (D327), M3e4d8 (D334), M3e4d9 (D341) and M3e4d10 (D346): each (file, enclosing scope) of these twelve files
#: that holds a SQL write statement -> its coverage.
STORE_WRITE_SCOPES: Final[dict[tuple[str, str], StoreCheck | System | Pending]] = {
```
REPLACE:
```
#: AD-1346 M3e4b (D229), M3e4d1 (D284), M3e4d2 (D291), M3e4d3 (D298), M3e4d4 (D306), M3e4d5 (D313), M3e4d6 (D320),
#: M3e4d7 (D327), M3e4d8 (D334), M3e4d9 (D341), M3e4d10 (D346) and M3e4d11 (D351): each (file, enclosing scope) of
#: these twelve files that holds a SQL write statement -> its coverage.
STORE_WRITE_SCOPES: Final[dict[tuple[str, str], StoreCheck | System | Pending]] = {
```

**M1-03** (`tests/fixtures/ad1346_store_census.py`)

SEARCH:
```
    (_WORKFORCE, "WorkItemStore.mark_crew_trust_outcome_delivered"): System(SHIP, "a trust outcome's delivered and delivered_at in crew_trust_outbox, which has no author column"),
    # Pending (D334): a later part of M3e4d classifies each.
    **{(_WORKFORCE, scope): _SCOPE_PENDING for scope in _WORKFORCE_PENDING},
}
```
REPLACE:
```
    (_WORKFORCE, "WorkItemStore.mark_crew_trust_outcome_delivered"): System(SHIP, "a trust outcome's delivered and delivered_at in crew_trust_outbox, which has no author column"),
    # AD-1346 M3e4d11 (D351). System (D239, D218): no statement of these six scopes writes created_by and none takes an
    # author id; a confirmation has no text, and each patch or record a production caller passes is one a ship's
    # service composes, some with copies of agents' text under their ids (register R164). update_work_item stays
    # pending: set_steps and update_step can pass it an agent's plan or rejection note with the agent's id (R165).
    (_WORKFORCE, "WorkItemStore.compare_and_set_work_item_assignment"): System(SHIP, "a child's assigned_to, metadata and updated_at, written only when the row still has the caller's expected parent, status, assignee, dependencies and metadata; assigned_to names the agent it is about (D239), and no src module calls it"),
    (_WORKFORCE, "WorkItemStore.confirm_value_context"): System(SHIP, "a pending value declaration's confirmed_by, confirmation_kind and confirmed_at in its provenance, and updated_at: a confirmation, with no text (D239)"),
    (_WORKFORCE, "WorkItemStore.merge_work_item_metadata"): System(SHIP, "a work item's merged metadata and updated_at, with its status and actual_tokens when they change; each production caller's patch is a ship's service's record, the crew executor's with its assignee's id and a summary of its output (D218)"),
    (_WORKFORCE, "WorkItemStore.compare_and_set_work_item_verification"): System(SHIP, "a child's verification record, merged metadata, actual_tokens and updated_at; the crew finalizer composes the record, with the producer's id, its result summaries and the verdicts' critiques (D218)"),
    (_WORKFORCE, "WorkItemStore.publish_work_item_metadata_with_child_barrier"): System(SHIP, "a CrewSession's metadata, its contract, synthesis and recovery records, with status and updated_at; CrewSessionService composes them, the contract with its last_result_summary (D218)"),
    (_WORKFORCE, "WorkItemStore.transition_crew_session_terminal_with_trust"): System(SHIP, "a failed CrewSession's contract in its metadata, with status and updated_at; CrewSessionService composes the contract (D218)"),
    # Pending (D334): a later part of M3e4d classifies each.
    **{(_WORKFORCE, scope): _SCOPE_PENDING for scope in _WORKFORCE_PENDING},
}
```

**M1-04** (`tests/test_ad1346_admission_store_census.py`)

SEARCH:
```
       files the scopes the scan finds are the rows of ``STORE_WRITE_SCOPES``: 20 check rows, 69 system rows under
       ``system:ship_computer`` and 27 rows pending for AD-1346 M3e4d.
```
REPLACE:
```
       files the scopes the scan finds are the rows of ``STORE_WRITE_SCOPES``: 20 check rows, 75 system rows under
       ``system:ship_computer`` and 21 rows pending for AD-1346 M3e4d.
```

**M1-05** (`tests/test_ad1346_admission_store_census.py`)

SEARCH:
```
- WC3  no file's row is pending and ``AGENT_ATTRIBUTED_SCOPES`` is empty; the pending scopes are 27 scopes of
```
REPLACE:
```
- WC3  no file's row is pending and ``AGENT_ATTRIBUTED_SCOPES`` is empty; the pending scopes are 21 scopes of
```

**M1-06** (`tests/test_ad1346_admission_store_census.py`)

SEARCH:
```
    """WC1 (D219, D220, D221; AD-1346 M3e4b: D229; AD-1346 M3e4c: D240; AD-1346 M3e4d1: D284; AD-1346 M3e4d2: D291;
    AD-1346 M3e4d3: D298; AD-1346 M3e4d4: D306; AD-1346 M3e4d5: D313; AD-1346 M3e4d6: D320; AD-1346 M3e4d7: D327;
    AD-1346 M3e4d8: D334; AD-1346 M3e4d9: D341; AD-1346 M3e4d10: D346; kills EV-9, EA-2, EA-6, ED-9, EY-5, EY-7,
    EU-7, EU-9, EO-6, EO-8, ET-8, ET-10, RQ-9, RQ-10, AV-9, AV-10, WF-5, WF-6, WF-7, WG-1, WG-2, WG-3, WG-4, WH-1,
    WH-2, WH-3, WH-4): a file that gains its first SQL write statement, or a scope of a scoped file that gains its
    first, fails here until it is classified or listed as pending."""
```
REPLACE:
```
    """WC1 (D219, D220, D221; AD-1346 M3e4b: D229; AD-1346 M3e4c: D240; AD-1346 M3e4d1: D284; AD-1346 M3e4d2: D291;
    AD-1346 M3e4d3: D298; AD-1346 M3e4d4: D306; AD-1346 M3e4d5: D313; AD-1346 M3e4d6: D320; AD-1346 M3e4d7: D327;
    AD-1346 M3e4d8: D334; AD-1346 M3e4d9: D341; AD-1346 M3e4d10: D346; AD-1346 M3e4d11: D351; kills EV-9, EA-2, EA-6,
    ED-9, EY-5, EY-7, EU-7, EU-9, EO-6, EO-8, ET-8, ET-10, RQ-9, RQ-10, AV-9, AV-10, WF-5, WF-6, WF-7, WG-1, WG-2,
    WG-3, WG-4, WH-1, WH-2, WH-3, WH-4, WN-1, WN-2, WN-3, WN-4, WN-5): a file that gains its first SQL write statement,
    or a scope of a scoped file that gains its first, fails here until it is classified or listed as pending."""
```

**M1-07** (`tests/test_ad1346_admission_store_census.py`)

SEARCH:
```
    assert Counter(type(cover).__name__ for cover in STORE_WRITE_SCOPES.values()) == {"StoreCheck": 20, "System": 69, "Pending": 27}
```
REPLACE:
```
    assert Counter(type(cover).__name__ for cover in STORE_WRITE_SCOPES.values()) == {"StoreCheck": 20, "System": 75, "Pending": 21}
```

**M1-08** (`tests/test_ad1346_admission_store_census.py`)

SEARCH:
```
    """WC3 (D218, D221; AD-1346 M3e4b: D229; AD-1346 M3e4c: D239, D240; AD-1346 M3e4d1: D284; AD-1346 M3e4d2: D291;
    AD-1346 M3e4d3: D298; AD-1346 M3e4d4: D306; AD-1346 M3e4d5: D313; AD-1346 M3e4d6: D320; AD-1346 M3e4d7: D327;
    AD-1346 M3e4d8: D334; AD-1346 M3e4d9: D341; AD-1346 M3e4d10: D346; kills EW-8, EA-1, EA-7, WF-8)."""
```
REPLACE:
```
    """WC3 (D218, D221; AD-1346 M3e4b: D229; AD-1346 M3e4c: D239, D240; AD-1346 M3e4d1: D284; AD-1346 M3e4d2: D291;
    AD-1346 M3e4d3: D298; AD-1346 M3e4d4: D306; AD-1346 M3e4d5: D313; AD-1346 M3e4d6: D320; AD-1346 M3e4d7: D327;
    AD-1346 M3e4d8: D334; AD-1346 M3e4d9: D341; AD-1346 M3e4d10: D346; AD-1346 M3e4d11: D351; kills EW-8, EA-1, EA-7,
    WF-8)."""
```

**M1-09** (`tests/test_ad1346_admission_store_census.py`)

SEARCH:
```
    assert Counter((path, cover.owner) for (path, _scope), cover in STORE_WRITE_SCOPES.items() if isinstance(cover, Pending)) == {
        ("src/probos/workforce.py", "M3e4d"): 27,  # AD-1346 M3e4d9 (D341) and M3e4d10 (D346): parts (a) and (b) are system rows
    }
```
REPLACE:
```
    assert Counter((path, cover.owner) for (path, _scope), cover in STORE_WRITE_SCOPES.items() if isinstance(cover, Pending)) == {
        ("src/probos/workforce.py", "M3e4d"): 21,  # AD-1346 M3e4d9 to M3e4d11 (D341, D346, D351): 24 scopes are system rows
    }
```

## 8. Tracking (M2's commit)

**Date rule.** If M2 is committed on a local date other than 2026-11-05, the Builder puts the committing machine's local date in place of `2026-11-05` in exactly two strings, both new:
- the paragraph head `**AD-1346 (2026-11-05), #1604 M3e4d11 -- ` in M2-01's REPLACE;
- the heading `### AD-1346 M3e4d11 -- part (c) of the pending workforce scopes, six classified (2026-11-05, #1604)` in M2-02's REPLACE.

Make the substitution before committing. No other deviation is permitted. Then regenerate the ledger with `python -P scripts/gen_ad_ledger.py` (write mode), and commit both files as the tool writes them.

**Where the entries land.**
- **M2-01.** Its SEARCH is two lines: the title `# ProbOS Progress` (`PROGRESS.md:1`) and the empty line under it. Its REPLACE is four lines: the title, an empty line, the new paragraph and an empty line. The paragraph lands directly under the title, above whichever paragraph is first there (M3e4d10's, or BF-952's if that lands after it).
- **M2-02.** Its SEARCH is M3e4d10's last bullet, `- *Reversal.* Revert the M3e4d10 commits.`. M3e4d10's M2-02 adds it once, after M3e4d9's entry and above `### BF-946 -- ...`. The new entry follows M3e4d10's entry. BF-952's entry goes above `### BF-950 --` (`DECISIONS.md:1349` on `63fbc874`) and does not touch these lines.
- Neither new head carries a status keyword of `scripts/gen_ad_ledger.py:126-132` in its first 120 characters (`:139`).

**M2-01** (`PROGRESS.md`)

SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**AD-1346 (2026-11-05), #1604 M3e4d11 -- part (c) of `workforce.py`'s pending scopes, six classified as the ship's.** Six `WorkItemStore` scopes leave `_WORKFORCE_PENDING` and become `System` rows, each with a reason naming what its statements write. None of them takes an author id or writes `created_by`. `compare_and_set_work_item_assignment` writes an assignee and has no `src` caller. `confirm_value_context` writes a confirmation with no text. `merge_work_item_metadata`, `compare_and_set_work_item_verification`, `publish_work_item_metadata_with_child_barrier` and `transition_crew_session_terminal_with_trust` write records that the ship's services compose, some with copies of agents' text under their ids, which D218 makes the ship's. `update_work_item` stays pending: `set_steps` and `update_step` can pass it an agent's plan or rejection note with that agent's id, and its check is designed in its own slice. No `src` file changes and no check is added. `STORE_WRITE_SCOPES` holds 20 `StoreCheck` rows, 75 rows of the ship's and 21 pending rows; 2 JetStream scopes and 3 file-write rows stay pending for M3e4d. Nothing is refused or charged. The contract is `prompts/ad-1346-m3e4d11-workforce-field-rows.md`.

```

**M2-02** (`DECISIONS.md`)

SEARCH:
```
- *Reversal.* Revert the M3e4d10 commits.
```
REPLACE:
```
- *Reversal.* Revert the M3e4d10 commits.

### AD-1346 M3e4d11 -- part (c) of the pending workforce scopes, six classified (2026-11-05, #1604)

AD-1346 M3e4d11 is the eleventh part of M3e4d and part (c1) of register R160. Six `WorkItemStore` scopes of the work item fields leave `_WORKFORCE_PENDING` and become `System` rows; `update_work_item` stays pending. No `src` file changes and no check is added. `STORE_WRITE_SCOPES` holds 20 `StoreCheck`, 75 `System` and 21 `Pending` rows. The contract is `prompts/ad-1346-m3e4d11-workforce-field-rows.md`.

- *D350 (the cut).* Six scopes as rows of the ship's; `update_work_item` in its own slice. Rejected: a check in `update_work_item` now; all seven as the ship's; all seven kept pending.
- *D351 (the rows).* No scope takes an author id or writes `created_by`. An assignee names the agent it is about, and a confirmation has no text (D239). The metadata, verification and contract records are composed by the crew executor, the crew finalizer and `CrewSessionService`, with copies of agents' text under their ids, which D218 makes the ship's. Rejected: a check presenting `confirmed_by` on `MessageStore.endorse`'s precedent; checks presenting the assignee or producer from a payload, which names the agent a record is about or the producer of a copy, not the record's author (D341).
- *D352 (`update_work_item`).* D239 holds for its step write: the plan's labels and a rejection note, with `facilitator` and `confirmed_by` taken from `set_steps` and `update_step`, to which the DM reply pipeline passes the agent's id. Its check is designed in its own slice (register R165). Rejected: a row of the ship's; reading the author out of the `steps` payload.
- *D353 (the guards).* WC1's and WC3's counts move; no new test.
- *D354 (cost).* No call is added.
- *Residual, accepted.* Registers R164 and R165 of the contract.
- *Reversal.* Revert the M3e4d11 commits.
```

## 9. What this does NOT change

- No file under `src/` is edited.
- Not edited: `config.py`, `config_models/`, `config/system.yaml`, the AD-1152 golden, `docs/development/architecture-baseline.yaml`.
- Not edited in the census fixture: its module docstring, `_SCOPE_PENDING` and its reason, `AGENT_ATTRIBUTED_SCOPES`, `STORE_WRITE_FILES`, `_WORKFORCE_PENDING`'s comment, every earlier row, and the other 21 pending names, `WorkItemStore.update_work_item` among them.
- Not edited: `tests/test_ad1346_admission_store_writes.py`, `tests/test_ad1346_admission_service.py`, `tests/fixtures/ad1346_effect_census.py`, `tests/fixtures/ad1343_seam_census.py`, `tests/fixtures/ad1346_store_family_census.py`, `tests/fixtures/ad1346_file_write_census.py` and their tests; WC2, WC4 and WC5.
- Not built here: part (c2) (`update_work_item`'s check, register R165), parts (d) and (e) of register R160, the file-write and JetStream rows, and M3e5. Not built (the epic's list): enforcement, a store rekey to the sovereign id, domain SQL, storage registration.

## 10. Mutation rows (one campaign of record on the M1 tree, after an unmutated baseline passes)

- `--tests`: every row runs against `tests/test_ad1346_admission_store_census.py` and `tests/test_ad1346_admission_store_writes.py`.
- Each Line is a stripped line that occurs once in its file on M1's tree. Builder: confirm with `grep -c -F`; a count other than 1 is a hard stop for the Architect. WN-3 and WN-5 share a Line; each row is applied alone.
- No row mutates `src`. Restore the fixture after each row; `git status --porcelain -- tests` prints nothing after the campaign.

| # | M | File | Line | Mutate to | Killed by |
|---|---|---|---|---|---|
| WN-1 | M1 | `tests/fixtures/ad1346_store_census.py` | `(_WORKFORCE, "WorkItemStore.merge_work_item_metadata"): System(SHIP, "a work item's merged metadata and updated_at, with its status and actual_tokens when they change; each production caller's patch is a ship's service's record, the crew executor's with its assignee's id and a summary of its output (D218)"),` | `(_WORKFORCE, "WorkItemStore.merge_work_item_metadatas"): System(SHIP, "a work item's merged metadata and updated_at, with its status and actual_tokens when they change; each production caller's patch is a ship's service's record, the crew executor's with its assignee's id and a summary of its output (D218)"),` | `test_every_file_with_a_sql_write_statement_is_a_row_and_every_row_is_one` |
| WN-2 | M1 | `tests/fixtures/ad1346_store_census.py` | `(_WORKFORCE, "WorkItemStore.confirm_value_context"): System(SHIP, "a pending value declaration's confirmed_by, confirmation_kind and confirmed_at in its provenance, and updated_at: a confirmation, with no text (D239)"),` | `(_WORKFORCE, "WorkItemStore.confirm_value_context"): _SCOPE_PENDING,` | `test_every_file_with_a_sql_write_statement_is_a_row_and_every_row_is_one` |
| WN-3 | M1 | `tests/fixtures/ad1346_store_census.py` | `"WorkItemStore.update_work_item",` | `"WorkItemStore.update_work_item", "WorkItemStore.compare_and_set_work_item_verification",` | `test_every_file_with_a_sql_write_statement_is_a_row_and_every_row_is_one` |
| WN-4 | M1 | `tests/fixtures/ad1346_store_census.py` | `(_WORKFORCE, "WorkItemStore.publish_work_item_metadata_with_child_barrier"): System(SHIP, "a CrewSession's metadata, its contract, synthesis and recovery records, with status and updated_at; CrewSessionService composes them, the contract with its last_result_summary (D218)"),` | `(_WORKFORCE, "WorkItemStore.publish_work_item_metadata_with_child_barrier"): StoreCheck((_WORKFORCE, "WorkItemStore.publish_work_item_metadata_with_child_barrier"), "expected_assigned_to"),` | `test_every_file_with_a_sql_write_statement_is_a_row_and_every_row_is_one` |
| WN-5 | M1 | `tests/fixtures/ad1346_store_census.py` | `"WorkItemStore.update_work_item",` | `"WorkItemStore.update_work_items",` | `test_every_file_with_a_sql_write_statement_is_a_row_and_every_row_is_one` |

- WN-1: the scanned scope `WorkItemStore.merge_work_item_metadata` has no row and the mutated key has no point, so WC1's key equality fails.
- WN-2 and WN-3: WC1's counter reads 74 `System` and 22 `Pending` (hand count). In WN-3, the spread comes after the `System` row in the dict literal and overrides it. WC3's pin also fails on both.
- WN-4: WC1's counter reads 21 `StoreCheck` and 74 `System`. WC3's list of checked scopes and WM1's count of 20 also fail.
- WN-5: the scanned scope `WorkItemStore.update_work_item` has no row and the key `WorkItemStore.update_work_items` has no point, so WC1's key equality fails. This pins that `update_work_item` stays a row (D352).
- The campaign re-runs no earlier row. M1 removes no earlier row's Line except WH-3's `"WorkItemStore.transition_crew_session_terminal_with_trust",`, which leaves the tuple with M1-01; WN-3 covers its class.

## 11. Verified Against Codebase (2026-11-05, read on `63fbc874`)

```
git rev-parse HEAD HEAD^{tree}   (63fbc8740c57622f11a96664bcb4934cd1d0c9a4, cc9d5e9bb94c3c49c4ef93097b258c27a75dd0a0)
git log --oneline -6   (63fbc874, 55f60873, 8ecf968d, 5cd64c7a, 072619d5, 95fe3e2c)
git status --porcelain   (empty)
git diff --name-only 8ecf968d..HEAD   (tests/fixtures/ad1346_store_census.py, tests/test_ad1346_admission_store_census.py)
wc -l logs/ad1346/contract-ad1346-m3e4d9-raw.md logs/ad1346/contract-ad1346-m3e4d10-raw.md logs/ad1346/answer-ad1346-m3e4d10.txt logs/ad1346/request-ad1346-m3e4d10.md logs/ad1346/request-ad1346-m3e4d11.md logs/ad1346/measure-workforce-scopes.txt   (509, 495, 555, 26, 26, 49)
wc -l tests/fixtures/ad1346_store_census.py tests/test_ad1346_admission_store_census.py src/probos/workforce.py src/probos/cognitive/crew_session.py src/probos/cognitive/crew_finalizer.py src/probos/cognitive/crew_executor.py src/probos/cognitive/dm/reply_pipeline.py src/probos/routers/workforce.py   (379, 212, 12155, 7119, 4088, 3308, 2733, 988)
Read config/standing_orders/architect.md :1-53
Read logs/ad1346/contract-ad1346-m3e4d10-raw.md :1-495
Read logs/ad1346/measure-workforce-scopes.txt :1-49
Read src/probos/workforce.py :7662-7731, :8646-9131, :9132-9421, :9650-10198
Read src/probos/cognitive/crew_synth.py :1125-1169
Read src/probos/cognitive/turn_promotion.py :1040-1088
Read src/probos/cognitive/crew_executor.py :1019-1093, :2880-2945
Read src/probos/cognitive/crew_session.py :2186-2215, :3236-3250, :3864-3919, :6270-6313, :6320-6379, :6560-6615
Read src/probos/cognitive/crew_finalizer.py :1730-1789, :2770-2801
Read src/probos/cognitive/dm/reply_pipeline.py :1835-1864, :1900-1946
Read src/probos/routers/workforce.py :285-334, :870-909
Read src/probos/agents/quartermaster.py :330-417
Read tests/fixtures/ad1346_store_census.py :1-60, :205-379
Read tests/test_ad1346_admission_store_census.py :1-30, :96-150
Read tests/test_ad1346_admission_store_writes.py :296-365
Read scripts/gen_ad_ledger.py :122-143
Read PROGRESS.md :1-2
Grep 'def (compare_and_set_work_item_assignment|update_work_item|confirm_value_context|merge_work_item_metadata|compare_and_set_work_item_verification|publish_work_item_metadata_with_child_barrier|transition_crew_session_terminal_with_trust|_insert_work_item|create_work_item)\b' src/probos/workforce.py -> :7662 :7708 :8646 :8763 :8904 :9132 :9650 :9805 :10044
Grep '"UPDATE work_items SET|f"UPDATE work_items SET' src/probos/workforce.py -> 38 lines; between :8646 and :10172 exactly :8733 :8837 :8981 :9379 :9392 :9399 :9405 :9779 :10008 :10141
Grep '"\s*(INSERT|DELETE FROM|REPLACE INTO)' src/probos/workforce.py -> 26 lines: :1930 :2023 :3892 :4578 :4653 :5543 :5593 :5684 :7563 :7717 :7755 :8177 :8181 :8421 :8457 :10517 :10876 :10880 :10884 :10888 :10892 :11223 :11250 :11333 :11813 :12152 (none between :8646 and :10172)
Grep '\.(compare_and_set_work_item_assignment|update_work_item|confirm_value_context|merge_work_item_metadata|compare_and_set_work_item_verification|publish_work_item_metadata_with_child_barrier|transition_crew_session_terminal_with_trust)\b|"(compare_and_set_work_item_assignment|update_work_item|confirm_value_context|merge_work_item_metadata|compare_and_set_work_item_verification|publish_work_item_metadata_with_child_barrier|transition_crew_session_terminal_with_trust)"' src -> 30 lines: agents/quartermaster.py:342 :385 :413; consultation/dispatch.py:742; cognitive/capability_gap_driver.py:413; cognitive/cognitive_agent.py:2316; cognitive/crew_executor.py:2407 :2946 :3064; workforce.py:9060 :9097; cognitive/crew_finalizer.py:1771 :2800; cognitive/crew_orchestrator.py:4188 :4253; cognitive/crew_session.py:3249 :3911 :6364 :6600; cognitive/crew_synth.py:1152; cognitive/dm/reply_pipeline.py:1926 :1927; routers/workforce.py:300 :325 :901; cognitive/ground_truth.py:288 :411; cognitive/turn_promotion.py:676 :829 :1054
Grep 'compare_and_set_work_item_assignment|compare_and_set_work_item_verification|publish_work_item_metadata_with_child_barrier|transition_crew_session_terminal_with_trust|confirm_value_context' src -> 14 lines: workforce.py:8646 :8904 :9650 :9805 :10044; cognitive/crew_session.py:2193 :2211 :3864 :3911 :6364 :6600; cognitive/crew_finalizer.py:1771 :2800; routers/workforce.py:325
Grep '\.(update_step|set_steps)\(' src -> cognitive/dm/reply_pipeline.py:1859 :1945 :1948 :1951 :1953; routers/workforce.py:781 :800
Grep '^_IMMUTABLE_FIELDS|^_JSON_FIELDS' src/probos/workforce.py -> :1601 :1623
Grep 'def with_value_confirmation' src/probos -> workforce.py:562
Grep 'def _output_summary' src/probos/cognitive/crew_executor.py -> :916
Grep 'metadata_patch\b.*=|"crew_execution_output"|CREW_EXECUTION_OUTPUT' src/probos/cognitive/crew_executor.py -> :1130 :1624 :2413 :2905 :2907 :2933 :2969 :2988
Grep 'merge_work_item_metadata\(' src/probos/cognitive/crew_executor.py -> :2407 :2946 :3064
Grep 'self\._merge\(|await merge\(' src/probos/cognitive/turn_promotion.py -> :715 :835 :1061
Grep '_merge_owned_metadata\(' src/probos/cognitive/crew_session.py -> :3240 :3414 :4425 :4687 :5074 :5234 :5391 :5653 :6105
Grep '^\s+patch(: dict\[str, Any\])? = |^\s+patch\["' src/probos/cognitive/crew_session.py -> :5045 :5053 :6079 :6085 :6596
Grep 'publication_patch' src/probos/cognitive/crew_session.py -> :6309 :6315 :6346 :6366
Grep 'def _verification_document' src/probos/cognitive/crew_finalizer.py -> :3347
Grep 'def _round_document' src/probos/cognitive/crew_finalizer.py -> :3397
Grep 'verification = self\._verification_document\(|verification = ' src/probos/cognitive/crew_finalizer.py -> :1647 :1732 :2740
Grep 'attachment|Pending\(' (-i) tests/fixtures/ad1346_file_write_census.py -> :18 :141 :143 :148 :168 :181 :204 :205
Grep 'STORE_WRITE_SCOPES|_WORKFORCE_PENDING|_SCOPE_PENDING' tests -> 28 lines (Absence 4)
Grep 'class StoreCheck' (-A 12) tests/fixtures/ad1346_store_census.py -> :188 (check, presented, via at :194-:196)
grep -n -o "D239 (the rule).\{0,1600\}" DECISIONS.md   (:1197)
grep -n -o "\*D218.\{0,400\}" DECISIONS.md   (:1167)
grep -n -E "^### (AD-1346 M3e4d8|BF-946|BF-950)|Revert the M3e4d8 commits" DECISIONS.md   (:1349 :1432 :1442 :1444)
grep -c "def test_" tests/test_ad1346_admission_store_census.py tests/test_ad1346_admission_store_writes.py tests/test_ad1346_admission_store_family_census.py tests/test_ad1346_admission_ticket_sinks.py   (5, 21, 5, 10)
d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py   (CEILING: AD-1358, reported by the request; not re-run in this session)
```

## Absence Verified (2026-11-05, run on `63fbc874`)

```
1.
CLAIM: WN-<n>, D350 to D354, R164, R165 and M3e4d11 are not used, except in the request for this contract
RUN:   Grep '\bWN-[0-9]|\bD35[0-4]\b|\bR16[45]\b|M3e4d11|m3e4d11' over . (rg's default ignore rules, which skip logs/)
FOUND: nothing
RUN:   the same Grep over logs/ad1346
FOUND: logs/ad1346/request-ad1346-m3e4d11.md (the request)
HOLDS: yes

2.
CLAIM: in tests, the seven part (c) names written WorkItemStore.<name> occur in tests/fixtures/ad1346_store_census.py only at :235-:241; elsewhere only as a code object or prose, in three tests that no edit here touches; WorkItemStore.adopt_child_plan_with_parent_metadata (M1-01's first line) and "WorkItemStore.update_work_item" (WN-3's and WN-5's Line) occur only at the fixture's :234 and :236
RUN:   Grep 'WorkItemStore\.(compare_and_set_work_item_assignment|update_work_item|confirm_value_context|merge_work_item_metadata|compare_and_set_work_item_verification|publish_work_item_metadata_with_child_barrier|transition_crew_session_terminal_with_trust)' tests
FOUND: tests/fixtures/ad1346_store_census.py:235 :236 :237 :238 :239 :240 :241; tests/test_ad1124_crew_session_contract.py:2055 (inspect.getsource); tests/test_ad1126_verified_finalization.py:6150 (a dict key); tests/test_ad528b_active_rejection.py:6 (a docstring)
RUN:   Grep 'WorkItemStore\.adopt_child_plan_with_parent_metadata|"WorkItemStore\.update_work_item"' tests
FOUND: tests/fixtures/ad1346_store_census.py:234, :236
HOLDS: yes

3.
CLAIM: in src, compare_and_set_work_item_assignment is named only at its definition, workforce.py:8646 (no call, no string literal)
RUN:   Grep 'compare_and_set_work_item_assignment|compare_and_set_work_item_verification|publish_work_item_metadata_with_child_barrier|transition_crew_session_terminal_with_trust|confirm_value_context' src
FOUND: compare_and_set_work_item_assignment only at src/probos/workforce.py:8646; the other 13 lines name the other four methods (§11)
HOLDS: yes

4.
CLAIM: in tests, the System and Pending values of STORE_WRITE_SCOPES are counted only by WC1 and WC3; every other reader filters on StoreCheck, reads one key, or is a comment or description string
RUN:   Grep 'STORE_WRITE_SCOPES|_WORKFORCE_PENDING|_SCOPE_PENDING' tests
FOUND: tests/fixtures/ad1346_effect_census.py:66 (a description string); tests/fixtures/ad1346_store_family_census.py:132 (a comment); tests/fixtures/ad1346_store_census.py:6, :112, :213 (docstring and comments), :47, :214, :247, :373 (the definitions and the spread), :379 (store_write_check_functions, StoreCheck); tests/test_ad1346_admission_store_census.py:4, :9, :11 (docstring), :44 (import), :106, :114, :115, :116, :117 (WC1), :142, :147 (WC3); tests/test_ad1346_admission_store_family_census.py:14 (docstring), :34 (import), :170 (WK3, one key); tests/test_ad1346_admission_store_writes.py:35 (docstring), :162 (import), :313 (WM1, StoreCheck), :341 (StoreCheck with via)
HOLDS: yes

5.
CLAIM: none of the seven part (c) scopes holds an INSERT, DELETE or REPLACE statement; their only SQL write statements are the ten UPDATEs of §1
RUN:   Grep '"\s*(INSERT|DELETE FROM|REPLACE INTO)' src/probos/workforce.py; Grep '"UPDATE work_items SET|f"UPDATE work_items SET' src/probos/workforce.py
FOUND: no INSERT, DELETE or REPLACE line between :8646 and :10172 (26 lines, §11); UPDATE lines in that range: :8733 :8837 :8981 :9379 :9392 :9399 :9405 :9779 :10008 :10141. The scopes' ranges were read in full (§11); an UPDATE whose text does not start in a constant would not be found by this Grep or by the scan (register R111)
HOLDS: yes
```

## 12. Deterministic gate checks, resolved up front

- M1 and M2 change no `src` file: `git diff --stat <base>..HEAD -- src` prints nothing after each.
- `grep -c "def test_" tests/test_ad1346_admission_store_census.py` prints 5 after M1, and the collect-only count is 5.
- For each §10 Line, `grep -c -F` on M1's tree prints 1. A Line that contains both `'` and `"` is matched with `grep -c -F -f <file holding the line>`.
- `python -P -c "from tests.fixtures.ad1346_store_census import _WORKFORCE_PENDING as p; print(len(p), len(set(p)))"` prints `21 21` after M1 (hand count).
- `python -P -c "from collections import Counter; from tests.fixtures.ad1346_store_census import STORE_WRITE_SCOPES as s; print(sorted(Counter(type(c).__name__ for c in s.values()).items()))"` prints `[('Pending', 21), ('StoreCheck', 20), ('System', 75)]` after M1 (hand count).
- The blocks, counted by their labels in §7 and §8: M1-01 to M1-09 (M1-01 to M1-03 in the census fixture, M1-04 to M1-09 in its test) and M2-01 to M2-02.
- `python -P scripts/gen_ad_ledger.py --check` exits 0 after M2.

## 13. Prior Art and Blind Spots

- **Internal.**
  - Adopted: D218's copy rule and D239's rule. The precedent rows: `EpisodicMemory._write_restore_sidecars` and `WorkItemStore.enqueue_promoted_report` (a ship's copy that keeps its agent); `WorkItemStore._assign_work_item` and `WorkItemStore.add_work_watcher` (an id the row is about); `WorkItemStore.transition_work_item` (status and a metadata patch).
  - Considered: `MessageStore.endorse`, a check with no text (D351 option 2; register R164).
  - Adopted unchanged: D334's pending-scope rows, from which a part removes its names.
- **External.** None. This classifies scopes under rules this repo settled (D218, D239), and the problem has no outside analogue. No reference-projects row was examined. Date used: 2026-11-05.
- **Blind spots, decided:** registers R164 and R165.
- **Considered, deferred:** `update_work_item`'s check (register R165); a test that the composed records carry the ids D351 names (D353 option 2); retiring `AGENT_ATTRIBUTED_SCOPES` and WC5 (the last part of R160).

## 14. Diff Reviewer: properties to verify

1. No file under `src/` changes.
2. `_WORKFORCE_PENDING` loses exactly the 6 names of D351 and gains none. It keeps `WorkItemStore.update_work_item`. It holds 21 names: the `WorkItemStore` scopes of `logs/ad1346/measure-workforce-scopes.txt` other than `_insert_work_item`, M3e4d9's 13, M3e4d10's 5 and these 6.
3. `STORE_WRITE_SCOPES` gains exactly M1-03's 6 `System(SHIP, ...)` rows, each keyed `(_WORKFORCE, "WorkItemStore.<name>")` and placed before the pending spread. No other key or value of the three tables changes.
4. Each new reason agrees with its scope's statements and its production callers' payloads on `63fbc874` (§1). In particular:
   - no scope's statements write `created_by`, and no scope takes an author id;
   - `compare_and_set_work_item_assignment` has no caller in `src`;
   - `confirm_value_context` writes only the provenance columns and `updated_at`;
   - the crew executor's evidence carries `assigned_to` and `output_summary`;
   - the finalizer's verification record carries `producer_agent_id`, `result_summary` and the verdict's `critique`;
   - the published contract carries `last_result_summary`.
5. WC1's counts (20, 75, 21), WC3's pin (21), the module docstring's counts (20, 75, 21 and 21) and the tracker counts agree with the tables after M1.
6. M1-03's comment, D351's and D352's text and the trackers claim no more than §1 shows. In particular, no sentence says that an agent's text in a patch has been checked, or will be; R164 says where it is not. No sentence says that `update_work_item` is checked.
7. Each §10 mutant fails its named test on the M1 tree, and the fixture is restored after the campaign.

## 15. Acceptance criteria

- The M1 and M2 focused gates pass as written in §4.
- The §12 checks hold.
- The §10 campaign of record kills WN-1 to WN-5, each by its named test, after an unmutated baseline passes.
- The broad gate passes once for the batch that carries this slice, with its receipt.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## For the register (#1604)

- **R113:** advanced. Part (c1)'s 6 scopes are system rows (D351). Pending for M3e4d: 21 scopes of `workforce.py`, 2 JetStream scopes and 3 file-write rows.
- **R160:** advanced. Part (c) is split: (c1) is delivered. What remains, with scope and point counts summed by hand from the rows of `logs/ad1346/measure-workforce-scopes.txt` (its line numbers are of the M3e4d7 tree):
  - (c2) `update_work_item`: 1 scope, 1 point, with a check (register R165).
  - (d) crew session provisioning and child plans: 5 scopes, 8 points.
  - (e) owned steps and legacy execution: 15 scopes, 32 points.
  - Then the file-write rows and the JetStream rows, as R160 items 2 and 3 say. The last part of item 1 removes `_SCOPE_PENDING` and WC1's `Pending` key, and may retire `AGENT_ATTRIBUTED_SCOPES` and WC5.
- **R164:** what this slice does not see:
  - **Copies under an agent's id, unchecked.**
    - The crew executor's evidence holds a summary of the agent's output with its assignee's id (`crew_executor.py:1065-1080`). The full output goes to the attachment store, whose row is `System` (`tests/fixtures/ad1346_file_write_census.py:204`).
    - The finalizer's verification record holds the producer's result summaries and the verdicts' critiques (`crew_finalizer.py:3397-3427`).
    - The published contract holds `last_result_summary` (`crew_session.py:6297`).
    - None of these writes is checked. The agent's work product is checked only where it is posted or versioned under its own id (for example `ArtifactStore.add_version`, `ChatThreadStore.append_message_once`).
  - **Payloads are not re-read.** The rows rest on the patches that today's production callers build (§1). A new caller that passes an agent's own text in a `merge_work_item_metadata` patch would make its reason false without failing a test (register R121's limit for a system row).
  - **A confirmation is not a check.** `confirm_value_context` records an agent confirmer's id with no check, unlike `MessageStore.endorse`, which checks a vote with no text (D231). D351 settles it under D239. A later rule that treats an agent's act with no text as its work product would move both rows.
  - **Static census.** A statement whose text does not start in a constant is not seen (register R111).
  - **What is left.** 21 scopes of `workforce.py` remain pending and write unchecked.
- **R165:** part (c2), `update_work_item`'s check: facts and options for its own contract.
  - **Facts (on `63fbc874`).**
    - `update_work_item(self, work_item_id, **updates)` (`workforce.py:8763`) rejects a key that is not a `WorkItem` field (`:8767-8768`) and skips `_IMMUTABLE_FIELDS` (`:8822-8823`).
    - Before its one statement (`:8836-8839`) it can raise or return: `:8765-8766`, `:8767-8768`, `:8769-8770` (`if not self._db: return None`), `:8771-8772`, `:8774`; inside its transaction at `:8777-8778`, `:8783-8789` and `:8791` (`_prepare_value_context_update` raises `ValueError`), and `return item` at `:8831-8832` when nothing is set.
    - `set_steps` (`:9017-9060`) takes `facilitator: str | None = None` and calls it with `steps` and, when `facilitator` is truthy or `gate_completion` is set, a `metadata` that carries it. `update_step` (`:9062-9097`) takes `actor: str | None = None` and `note`, returns `None` on a bad index (`:9075-9076`) or an invalid transition (`:9080-9086`), and calls it with `steps`.
    - Production callers: the DM reply pipeline passes `self.ctx.agent_id or "agent"` (`reply_pipeline.py:1859`, `:1939-1955`). The route passes no `facilitator` to `set_steps` (`routers/workforce.py:781-784`), and `actor=body.get("actor")` to `update_step` (`:800-803`), so an absent key is an explicit `None`, not an omitted keyword.
    - The route's `update_work_item(work_item_id, **body)` (`:300`) would bind any new keyword parameter from an HTTP body key.
    - The owned-steps path (`reply_pipeline.py:1936-1938`) writes through part (e)'s scopes, not through `update_work_item`.
  - **Options, ranked (for that contract to decide):**
    1. A keyword-only presented id on `update_work_item`, with the check as the first statement of its body (WM1's second branch: check equals scope, call before the first point). `set_steps` passes `facilitator` and `update_step` passes `actor`; the route strips the key from its body, with a test for that. The check counts a write that a later guard refuses, and an omitted keyword must differ from an explicit `None` (R161's shape). A hand-off test over a real store and a real admission service follows WM20 and WM21.
    2. A new scope for the step write, with its own statement and check, leaving `update_work_item` a `System` row. It splits one statement into two and changes the event and cache path.
    3. Checks in `set_steps` and `update_step` with a census type that holds two check sites per row. It needs a new `StoreCheck` shape and a WM1 branch.
  - **Cost.** When a reply has no owned-steps view (`reply_pipeline.py:1936-1938`), `set_steps` runs at most once per reply, when the reply carries a plan and the agent may seed one (`:1944-1945`; the prose fallback is `:1856-1859`), and `update_step` runs up to once per index the reply carries: once per submit index (`:1947-1948`), and once per confirm or reject index only when the agent may validate (`can_validate`, `:1943`, `:1949-1955`), so one reply can run it several times or not at all. Each route invokes its step helper at most once per call (`routers/workforce.py:778-781`, `:797-800`). That contract sizes them by command.
