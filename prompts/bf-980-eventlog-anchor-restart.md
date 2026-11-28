# BF-980 (#1811): After a prune empties the event table, the next row chains from the truncation anchor, and `verify_chain` accepts no genesis restart after an anchor

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-18
**Status:** ready to build on `origin/main` `9f43697f`, or on the tree after #1680 (BF-938) merges. #1680 touches neither code file in this contract (premise M0-1). **Oracle:** none. This is a read-only consult: no test was run and no block was applied by tool. The Builder runs the base check (M0-2) and the mutation campaign (section 9), and that run is the campaign of record.
**Base blobs (`9f43697f`):** `src/probos/substrate/event_log.py` `e142a3c333367be7fbf3bc7fd0fab1c24a0438d4`, `tests/test_bf942_eventlog_truncation_anchor.py` `e509199d1eda9dde6913a67d3ce9b44022668ab7`, `PROGRESS.md` `c4dbda8a11176a15bd8838ea5fb3a20919577b0b`, `DECISIONS.md` `02f99b21526771fc4794609d4941543859da7fe7`. After #1680 merges, only the two tracker blobs may differ. Their SEARCH text is chosen so that it survives that change (section 7.3).
**Tier:** M1 HIGH (it changes an audit control: the event log's hash-chain append and its verifier). M2 STANDARD. **Estimated tests:** one new file with 9 cases, plus one BF-942 case rewritten in place (that file stays at 22 cases). **BF number:** BF-980 is held by #1811 (open; `bug`, `latent`). No new number is allocated. Ceilings for the record: AD-1360 per `scripts/ad_ceiling.py` (issue titles), next AD-1361.

**Which text describes the head.** Before building, `git rev-parse HEAD:<path>` must print the first two blobs above, and `tests/test_bf980_eventlog_anchor_restart.py` must not exist. Any SEARCH that does not occur exactly once is a hard stop for the Architect. Working copies are CRLF and the SEARCH text is LF. Where the prose and a block differ, the block wins. Every block is ASCII.

## 0. Event types and new names

No EventType, config field, table, column or public name is added. The new names are a local variable `has_tail` in `_insert_chained_row` and a test module. Neither occurs in `src/` or `tests/` today (section 12, Absence).

## 1. Problem

1. **The append restarts at genesis on an empty table.** `EventLog._insert_chained_row` (`event_log.py:772-806`) opens `BEGIN IMMEDIATE` (`:784`) and sets `prev_hash = self.GENESIS_HASH` (`:785`). It replaces that value only with the `row_hash` of a tail row (`:786-793`). After a prune that left no row, the next event is therefore linked to genesis, even though `events_truncation_anchor` (`:97-101`) holds the `row_hash` of the last row deleted (`_delete_head`, `:1401-1404`).
2. **The walk accepts that restart.** `verify_chain` (`:1251-1312`) starts at the anchor's hash (`:1273`). For the first row, when `stored_prev != expected_prev` and an anchor exists, `elif stored_prev == self.GENESIS_HASH: expected_prev = stored_prev` (`:1300-1301`) accepts a genesis link. The docstring records this as intended (`:1255-1259`), and BF-942 chose it as D4 (`DECISIONS.md:1595`). The result is that an anchored chain carries an acceptance rule it would not need if the append chained from the anchor. Any genesis-linked first row after an anchor reads `truncated`, `ok` True, including one written by a writer of the file (BF942-F5 on #1754).
3. **The defect is pinned as the contract.** `tests/test_bf942_eventlog_truncation_anchor.py:265` asserts `first[:2] == (old[2] + 1, EventLog.GENESIS_HASH), "premise: the append restarts at genesis"`. That line is rewritten here (P1-5), with the reason inline.
4. **How a store reaches the state.** All of these must hold:
   - (a) The code is BF-942's or later (merged `bab8413e`, 2026-11-09) and earlier than this fix.
   - (b) A prune leaves zero rows. Only the age stage can do that: its boundary query takes every row when `NOT EXISTS (SELECT 1 FROM events WHERE timestamp >= ?)` (`:1355-1358`). The cap stage keeps `max_rows` >= 1 rows (`OFFSET excess - 1`, `:1371-1372`).
   - (c) An append follows, in the same process or a later one.

   The runtime's only prune caller is `_event_log_prune_loop` (`runtime.py:4078-4097`; the only `.prune(` on an `EventLog` in `src`). It sleeps one interval before its first prune (`:4087`; 3600 s in `config/system.yaml:1856` and in `config_models/core.py:150`). Boot logs `system/started` (`startup/finalize.py:6367`). A running vessel therefore holds a recent row at every prune. With the defaults (`retention_days: 7`, `max_rows: 100000`), the table empties only in two cases:
   - the vessel logs no event for `retention_days` while it runs, or
   - the wall clock steps forward by more than `retention_days`.

   It can also be emptied by a writer other than `prune`. `wipe()` is excluded: it deletes the anchor too (`:1415`), and it has no production caller. `probos reset` is excluded: it removes the whole file (`__main__.py:2663`).
5. **Measured reach (R3, authorised by the Captain on 2026-11-18; `.adq/replays/r3-events.txt`).** The vessel's `events.db` copy has 1,796 rows (ids 415101..416896) and **no** `events_truncation_anchor` table, so BF-942 never ran on it. Its first row links to another row, and base `verify_chain` gives `unanchored`, `(False, 415101)`. In the compatibility state: **0 of 1**. Three synthetic controls run through the real `EventLog` discriminate: pruned to empty then appended is in the state; unpruned is not; capped with rows kept is not. On this vessel's next start on any code from BF-942 on, `start()` creates an empty anchor table (`:549`). The first prune comes one interval later, after `system/started` is logged, so it anchors at the last old row and keeps the boot rows, which link to it. That vessel cannot enter the state on that first prune.

## 2. Solution

- **The append.** In `_insert_chained_row`, record whether a tail row was read. With no tail row, read the anchor (`_read_truncation_anchor`, `:1314-1322`) inside the same `BEGIN IMMEDIATE` transaction, on the same connection under the same `_write_lock`. If an anchor exists, chain from its `row_hash` verbatim. Otherwise keep `GENESIS_HASH`.
- **The walk.** In `verify_chain`, delete the `elif` exception. After an anchor, the first row must link to the anchor's hash. Anything else, genesis included, is `broken` at that row through the existing check at `:1302-1303`. Rewrite the docstring to match.
- **The BF-942 case.** The case that pinned the restart now pins the link to the anchor.
- **What does not change.** `_compute_row_hash`, `prune`, `_delete_head`, `wipe`, `_SCHEMA`, `ChainVerdict` and the unanchored path (`detached_at`, `unanchored`) keep every byte.

**Heavier designs rejected.**
- A marker table that exempts a store already holding the restart: D3, option 2.
- Re-anchoring at open: D3, option 3.
- A public anchor accessor: the one private reader serves both the append and the walk.
- `prune` never deleting the newest row: it changes retention, as BF-942 D4 option 2 found.

## 3. Decisions

Options are ranked by correctness, security, compatibility, reversibility and validation cost. The top option is taken in each case.

**D1. The append on an empty table.**

| # | Option | Judgement |
|---|---|---|
| 1 | With no tail row, read the anchor in the same `BEGIN IMMEDIATE` transaction and chain from its `row_hash` verbatim. A tail row decides exactly as today, even one whose hash is `''` (chosen). | This is the AD-1278 `AuditLog.append` rule: `self.entries[-1].entry_hash if self.entries else self._anchor_hash()` (`security/audit.py:169-171`). Both reads sit under one RESERVED lock, so no second connection can commit between them (BF-873). In-process, `prune` holds `_write_lock` (`:1346`) and so does `log()` (`:689`), so a prune and an append never interleave on one connection. |
| 2 | Chain from the anchor only when its hash is non-empty, mirroring the tail's `if prior:` | The walk expects the anchor's value verbatim (`:1273`). An empty anchor hash would make the append and the walk disagree, and the next row would read `broken`. |
| 3 | Read the anchor on every append | It adds a read to the hot path for nothing: a tail row always wins. |

**D2. The walk's verdict on a genesis-linked first row after an anchor.** The verdict is `broken`, `(False, that row's id)`, with `anchor_id` set, as the issue asks. The exception is deleted, and the existing check (`:1302-1303`) produces the verdict. Rejected: a distinct `restarted` state. A forged restart and one written by the old append are byte-identical, so a separate label would claim knowledge the walk does not have.

**D3. A store that already holds an anchor and a genesis-linked first row (the compatibility question).**

| # | Option | Correctness | Security (a forged restart reads `broken` on every store that did not hold one at the change) | Compatibility | Reversibility | Validation cost |
|---|---|---|---|---|---|---|
| 1 | **No exception and no migration (chosen).** Such a store reads `broken` at the restart row until its next prune that deletes a row. That prune deletes the head run, which starts at the restart row, and re-anchors at a real row, so the store reads `truncated` from then on. | True under the new rule: the store cannot show that its first row follows the anchor. | Holds everywhere, with no window. | One store type changes verdict (`truncated` -> `broken`) for at most `retention_days` plus one prune interval after its restart row was written (age stage on), or until the table passes `max_rows`. Measured: 0 of 1 vessel (section 1, item 5). Reach needs section 1 item 4 (a) to (c). No production code reads the verdict (section 4). | Revert. | Lowest: two code hunks, no schema. Test A7 proves the heal. |
| 2 | A marker written once at open: a new table naming the restart row's id, plus a "checked" flag so that later opens never add one. The walk accepts genesis only at that id. | It keeps a second acceptance rule forever, for a state that heals itself. | Holds only with the once-flag. Without it, every open would bless a later forgery. A writer of the file can write the marker as easily as a row (BF942-F5), so the rule protects nothing a writer cannot forge. | Additive (`CREATE TABLE IF NOT EXISTS`, idempotent). | A table left behind. | A schema addition, a `docs/development/store-baseline.yaml` row (BF-942 A2), a migration, a new walk branch and its tests, all for 0 measured stores. |
| 3 | Re-anchor once at open: set the anchor's `row_hash` to genesis for such a store. | It discards the recorded hash of the last pruned row, which is audit metadata. | It blesses whatever head exists at that open: the trust-on-first-use pattern BF-942 D6 rejected. It also needs the once-flag. | It rewrites the anchor in place. | Not reversible: the old hash is gone. | Medium. |
| 4 | Keep the exception (status quo) | It fails the issue's acceptance. | The forgery window stays. | n/a | n/a | n/a |

**Why option 1 is inside the envelope.** "Breaking a ... persisted schema ... or compatibility promise without a backward-compatible migration path" (`.github/agents/orchestrator.agent.md:122`) does not apply, for three reasons:
- No schema changes.
- The only consumers of the verdict are tests (section 4). BF-942 L10 left the meaning of a non-`ok` verdict for a future production caller to decide.
- The store migrates itself at its next deleting prune, and no row or hash is rewritten.

The change tightens the audit control. It weakens none.

**Two adjacent states, kept as they are.**
- **Anchor present, zero rows, at open** (for example, a store closed straight after a prune to empty). The append chains from the anchor (D1; test A4). The walk returns `truncated` with no rows, unchanged.
- **Anchor newer than every row.** The walk reports `broken` at the first row (`:1294-1295`; BF-942 `test_the_first_retained_row_must_follow_the_anchor`). The append chains from the tail, unchanged. This state is kept.

**D4. Tests.** The tests use real `EventLog` files under `tmp_path`, with rows written by `log()`. A restart at genesis is written the way the old append wrote it: the row is relinked to `GENESIS_HASH`, with its hash recomputed by `_compute_row_hash` (imported by tests already: `tests/test_ad490_eventlog_hash_chain.py:7`). Every case asserts the state it depends on before it asserts the effect: an anchor beside an empty table, or a genesis-linked first row. Rejected: a source-text test, because it cannot tell a required line from the shipped one.

## 4. Every consumer (each command and what it found is in section 12)

| Consumer | Where | Reached? | How it is tested |
|---|---|---|---|
| `EventLog.verify_chain` production callers | none. In `src`, `verify_chain` occurs only in `event_log.py` and in the identity ledger's and `AuditLog`'s own methods (`identity.py:1122`, `routers/identity.py:58`, `security/audit.py:236`, `startup/finalize.py:4769`). `scripts/` and `ui/src` have none. | no | n/a |
| `verify_chain` test sites | 24 sites in 5 files: `test_ad490_eventlog_hash_chain.py:55,65,80,94`, `test_ad1129_eventlog_query_tool.py:1985`, `test_ad1195_durable_event_seam.py:383,453,477,689`, `test_ad1224_durable_tool_start.py:1744,1851,1852,1858,2189,2294,3076,3233`, `test_bf873_event_log_chain_concurrency.py:187,198,225,310,340,444,513`. Plus the BF-942 file. | Only by a prune to empty followed by an append. None of the 24 does that: their prunes are `test_bf873:262` (a cap that keeps 3 rows) and `:304` (deletes nothing). | G2, unchanged |
| Anchor readers | `_read_truncation_anchor` (`:1314`), called by `verify_chain` (`:1266`) and now by `_insert_chained_row` | yes | A1 to A9, the BF-942 file |
| Anchor writers and clearers | `_delete_head` (`:1401-1404`), `wipe` (`:1415`), `_SCHEMA` (`:97`) | no (unchanged) | A5 (a wipe still restarts at genesis), the BF-942 file |
| Appenders to `events` | `_insert_chained_row` only (`INSERT INTO events`: `:796`, the one hit in `src`), reached from `log()` (`:624`) | yes | A1, A3, A4, A6, A8, A9 |
| Pruners | `runtime.py:4089` only. `EventLog.wipe` has no caller in `src`. | Reached through the append that follows a prune | A1, A7, A9 |
| The tail-read tracer in a test child process | `test_bf873_event_log_chain_concurrency.py:89` matches `"SELECT row_hash FROM events"`. The anchor read's SQL, `SELECT event_id, row_hash FROM events_truncation_anchor ...`, does not contain that substring, and the tail SQL text is unchanged. | no | G2 (that file) |
| `AuditLog` (AD-1278) | `security/audit.py:169-171`, `:236-257` | no; it is the pattern adopted | n/a |
| API routes and Bridge checks | none for the EventLog verdict (same grep as row 1) | no | n/a |
| `probos reset` | `__main__.py:2663` removes `events.db` | no | n/a |
| AD-1346 census | `tests/fixtures/ad1346_store_census.py:178`: one file-level row, `System(SHIP, "the event log")`, with no count. The change adds a read and no write. | no | G2 (`check_architecture_principles.py --check`) |

## 5. Milestones and gates

| M | Blocks | Gate |
|---|---|---|
| M1 | N1-1 (new test file), then P1-1 to P1-5 | G0 (base), then G1 and G2 |
| M2 | P2-1, P2-2, then the ledger pair | G3 |

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`.

**M0 -- premises to verify first-hand, each with its probe.** Each probe asserts its own premise: a command that finds nothing where something is expected is a FAIL, not a pass.

1. **The two code blobs are the base.** Run `git rev-parse HEAD:src/probos/substrate/event_log.py HEAD:tests/test_bf942_eventlog_truncation_anchor.py`. Expected: the two blobs in the header. If #1680 has merged, `git diff --stat 9f43697f HEAD -- src/probos/substrate/event_log.py tests/test_bf942_eventlog_truncation_anchor.py` must also be empty.
2. **The base shows the defect.** Write N1-1 only, then run `PY -m pytest tests/test_bf980_eventlog_anchor_restart.py tests/test_bf942_eventlog_truncation_anchor.py -q -n 0 -p no:randomly`.
   - Expected: the new file has 3 passed (A3, A5, A6) and 6 failed (A1, A2, A4, A7, A8, A9); the BF-942 file has 22 passed.
   - Then apply P1-5 alone: the BF-942 file has 21 passed and 1 failed (the rewritten case).
   - Each failure must stop at the effect line section 8 names. If a failure stops at a line whose message starts `premise:`, that is a hard stop for the Architect.
   - A9 depends on asyncio admitting the prune first. If A9 passes on the base, record it and go on: its purpose is the order-free property.
3. **No production caller of `EventLog.verify_chain`.** Run `git grep -n -w verify_chain -- src scripts ui/src config`. Expected: hits only in `substrate/event_log.py`, `identity.py`, `routers/identity.py`, `security/audit.py`, `startup/finalize.py` and the `verify_chain_*` helpers of `identity_keys.py` and `federation/continuity.py`. The premise is that the `event_log.py` definition is found.
4. **One appender.** Run `git grep -n -E "INSERT (OR [A-Z]+ )?INTO events\b" -- src`. Expected: `substrate/event_log.py:796` only.
5. **One pruner.** Run `git grep -n -E "event_log\.(prune|wipe)\(" -- src scripts`. Expected: `runtime.py:4089` only.
6. **The tracer is not tripped.** Run `PY -c "a='SELECT row_hash FROM events'; print(a in 'SELECT row_hash FROM events ORDER BY id DESC LIMIT 1', a in 'SELECT event_id, row_hash FROM events_truncation_anchor WHERE singleton = 1')"`. Expected: `True False`.
7. **The number.** Run `gh issue list --state all --search "BF-980 in:title"`. Expected: #1811 only.
8. **M0 counts.** Record the collected count (`--collect-only -q`) of every file in G2.

**Gates.**
- **G0.** M0-2 as stated.
- **G1** (after P1-1 to P1-5): `PY -m pytest tests/test_bf980_eventlog_anchor_restart.py tests/test_bf942_eventlog_truncation_anchor.py tests/test_ad490_eventlog_hash_chain.py tests/test_bf873_event_log_chain_concurrency.py tests/test_database_retention.py tests/test_event_log.py -q -n 0 -p no:randomly`. **Expected:** the new file 9 passed, the BF-942 file 22 passed, and every other file 0 failed with its M0 count.
- **G2.** Three parts:
  1. `PY -m pytest` over these 36 files, `-q -n 0 -p no:randomly`: the new file, plus the 31 test files that import `probos.substrate.event_log`, plus the 4 that use it through `tests/bf934_world.py`. The 31: `test_ad1129_eventlog_query_tool.py test_ad1152_agentic_correlation.py test_ad1195_durable_event_seam.py test_ad1195_durable_producers.py test_ad1224_durable_tool_start.py test_ad1240_tool_result_delivery.py test_ad1324_audit_terminal.py test_ad1324_terminal_context.py test_ad1328_s2a_run_command_tool.py test_ad1328_s2b_tool_router_shell.py test_ad1343_agent_stop.py test_ad1343_agent_stop_lift.py test_ad1343_agent_stop_settle.py test_ad1347_s3_execution.py test_ad1356_s1_input_errors.py test_ad490_eventlog_hash_chain.py test_ad664_eventlog_diagnostic.py test_bf873_event_log_chain_concurrency.py test_bf907_trust_identity.py test_bf925_event_log_window.py test_bf942_eventlog_truncation_anchor.py test_bridge_alerts.py test_correction_runtime.py test_database_abstraction.py test_database_retention.py test_event_log.py test_feedback_engine.py test_onboarding.py test_orientation.py test_proactive.py test_self_mod_deps.py`. The 4: `test_bf934_s1_decision_routing.py test_bf934_s2_secondary_gates.py test_bf934_s3_intended_actions_ledger.py test_bf976_withdrawal_ledger.py`. All paths are under `tests/`.
  2. `PY -P scripts/check_architecture_principles.py --check`.
  3. `PY -P scripts/check_store_registry.py --check`: no table is added, so it must stay clean.

  **Expected:** the new file 9 passed; 0 failed elsewhere, with counts equal to M0.

  **How the list was derived.** `rg -l "probos\.substrate\.event_log|probos\.substrate import event_log" tests/` gave 33 paths (`conftest.py` and `bf934_world.py` are helpers). `rg -l bf934_world tests/` gave the 4. The test files that hit `\.verify_chain\(\)|truncation_anchor|ChainVerdict` (14) are either in this list or call the `AuditLog`'s or identity ledger's `verify_chain`, which this change does not reach: `test_ad1196`, `test_ad1213`, `test_ad1214`, `test_ad1278`, `test_ad456`, `test_ad456d`, `test_agent_identity`, `test_bf885`. A plain `event_log` grep hits 192 files, mostly the `runtime.event_log` attribute. The broad gate covers those.
- **G3** (M2): `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`. Commit the ledger pair it writes, `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`, with M2.
- **Harness rule.** No source change made to pass a test, no skip, no loosened assertion. A failing case goes back to the Architect. The broad gate runs once, in the main session, with `--receipt`. Stage explicit paths only; never `git add -A`.

## 6. Commit messages

- **M1:** `BF-980 M1: after a prune empties the event table the next row chains from the truncation anchor, and verify_chain accepts no genesis restart after an anchor (#1811)`
- **M2:** `BF-980 M2: trackers and ledger (#1811)`. The body ends with the line `Closes #1811.`

## 7. The contract

### 7.1 M1: code

**P1-1.** `src/probos/substrate/event_log.py`, the docstring of `_insert_chained_row`.
SEARCH:
```
    async def _insert_chained_row(self, payload: dict[str, Any]) -> int | None:
        """Read the chain tail and append one row in a single write transaction.

        SQLite-specific by design; this module already speaks SQLite throughout.
        """
```
REPLACE:
```
    async def _insert_chained_row(self, payload: dict[str, Any]) -> int | None:
        """Read the chain tail and append one row in a single write transaction.

        With no tail row the new row chains from the truncation anchor a prune recorded, read in the
        same transaction, and from genesis only when there is no anchor either (BF-980).

        SQLite-specific by design; this module already speaks SQLite throughout.
        """
```

**P1-2.** The same file, the tail read.
SEARCH:
```
        try:
            await self._db.execute("BEGIN IMMEDIATE")
            prev_hash = self.GENESIS_HASH
            async with self._db.execute(
                "SELECT row_hash FROM events ORDER BY id DESC LIMIT 1"
            ) as cursor:
                async for row in cursor:
                    prior = row[0]
                    if prior:
                        prev_hash = prior
                    break
            row_hash = _compute_row_hash(prev_hash=prev_hash, payload=payload)
```
REPLACE:
```
        try:
            await self._db.execute("BEGIN IMMEDIATE")
            prev_hash = self.GENESIS_HASH
            has_tail = False
            async with self._db.execute(
                "SELECT row_hash FROM events ORDER BY id DESC LIMIT 1"
            ) as cursor:
                async for row in cursor:
                    has_tail = True
                    prior = row[0]
                    if prior:
                        prev_hash = prior
                    break
            if not has_tail:
                # BF-980: an emptied table goes on from the anchor the prune recorded, read inside
                # this BEGIN IMMEDIATE so no other connection can move it between the two reads.
                # wipe() deletes the anchor with the rows, so a wiped log still starts at genesis.
                anchor = await self._read_truncation_anchor()
                if anchor is not None:
                    prev_hash = anchor[1]
            row_hash = _compute_row_hash(prev_hash=prev_hash, payload=payload)
```

**P1-3.** The same file, the `verify_chain` docstring.
SEARCH:
```
        be the row before it. The walk starts at genesis or, once a prune has recorded a truncation anchor (BF-942),
        at the anchor's ``row_hash``: the first retained row must come after the anchor's id and link to its hash, or
        to genesis when the prune left no row and the next append restarted the chain. Without an anchor, a first row
        that does not link to genesis is a cut head: the walk goes on from its own link and ends ``(False, first_id)``,
        ``unanchored``, if the rest verify, so an edit behind the cut is still found.
```
REPLACE:
```
        be the row before it. The walk starts at genesis or, once a prune has recorded a truncation anchor (BF-942),
        at the anchor's ``row_hash``: the first retained row must come after the anchor's id and link to its hash,
        and to nothing else. A first row that links to genesis after an anchor is ``broken`` (BF-980: the append
        chains an emptied table from the anchor, so no routine path writes one). Without an anchor, a first row
        that does not link to genesis is a cut head: the walk goes on from its own link and ends ``(False, first_id)``,
        ``unanchored``, if the rest verify, so an edit behind the cut is still found.
```

**P1-4.** The same file, the first-row block of `verify_chain`.
SEARCH:
```
                    if stored_prev != expected_prev:
                        if anchor is None:
                            detached_at = row[0]
                            expected_prev = stored_prev
                        elif stored_prev == self.GENESIS_HASH:
                            expected_prev = stored_prev
                if stored_prev != expected_prev:
```
REPLACE:
```
                    if stored_prev != expected_prev:
                        if anchor is None:
                            detached_at = row[0]
                            expected_prev = stored_prev
                        # BF-980: after an anchor there is no exception. A first row that links to
                        # genesis, or to anything but the anchor's hash, is broken just below.
                if stored_prev != expected_prev:
```

**P1-5.** `tests/test_bf942_eventlog_truncation_anchor.py`, the case that pinned the restart. It is updated in place with the reason inline, not deleted.
SEARCH:
```
    async def test_a_prune_that_empties_the_table_restarts_the_chain_and_it_still_verifies(self, tmp_path, monkeypatch):
        at = _clock(monkeypatch)
        async with _opened(tmp_path) as log:
            at(10)
            old = await _fill(log, 3)
            before = await _rows(log)
            at(0)
            assert await log.prune(retention_days=7, max_rows=0) == 3
            assert await _rows(log) == []
            assert await _anchors(log) == [(old[2], before[2][2])]
            assert _seen(await log.verify_chain()) == ((True, None), "truncated", old[2])
            await _fill(log, 2)
            first = (await _rows(log))[0]
            assert first[:2] == (old[2] + 1, EventLog.GENESIS_HASH), "premise: the append restarts at genesis"
            assert _seen(await log.verify_chain()) == ((True, None), "truncated", old[2])
```
REPLACE:
```
    async def test_after_a_prune_empties_the_table_the_next_row_links_to_the_anchor(self, tmp_path, monkeypatch):
        at = _clock(monkeypatch)
        async with _opened(tmp_path) as log:
            at(10)
            old = await _fill(log, 3)
            before = await _rows(log)
            at(0)
            assert await log.prune(retention_days=7, max_rows=0) == 3
            assert await _rows(log) == []
            assert await _anchors(log) == [(old[2], before[2][2])]
            assert _seen(await log.verify_chain()) == ((True, None), "truncated", old[2])
            await _fill(log, 2)
            first = (await _rows(log))[0]
            # BF-980 (#1811): this case pinned BF-942's D4, a restart at genesis that verify_chain accepted after
            # an anchor. The append now chains an emptied table from the anchor, and the walk accepts nothing else.
            assert first[:2] == (old[2] + 1, before[2][2])
            assert _seen(await log.verify_chain()) == ((True, None), "truncated", old[2])
```

### 7.2 New file: `tests/test_bf980_eventlog_anchor_restart.py` (M1)

**N1-1.**
```python
"""BF-980 (#1811): after a prune empties the event table, the next row chains from the truncation anchor.

Real ``EventLog`` files under ``tmp_path``, ``~`` moved, no network. Rows come from ``log()`` (real hashes); the age
cases move the module's clock as BF-942's tests do. A row "restarted at genesis" is written the way the append before
BF-980 wrote it: linked to ``GENESIS_HASH`` with its hash recomputed by ``_compute_row_hash`` (AD-490), so the walk's
hash check passes and only the link decides the verdict. Every case asserts the state it needs (an anchor beside an
empty table, a genesis-linked first row) before it asserts the effect.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

from probos.substrate import event_log as event_log_module
from probos.substrate.event_log import EventLog, _compute_row_hash

_NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
_PAYLOAD_COLUMNS = (
    "timestamp", "category", "event", "agent_id", "agent_type", "pool", "detail",
    "correlation_id", "parent_event_id", "data",
)


class _Clock(datetime):
    """The module's ``datetime`` with a settable ``now()``: ``log()`` stamps rows and ``prune()`` takes its cutoff from ``at``."""

    at = _NOW

    @classmethod
    def now(cls, tz=None):
        return cls.at.astimezone(tz)


@pytest.fixture(autouse=True)
def _moved_home(tmp_path, monkeypatch):
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(tmp_path / "home"))


def _clock(monkeypatch):
    """Install the clock; the function it returns sets the time to ``days_ago`` days before ``_NOW``."""
    monkeypatch.setattr(event_log_module, "datetime", _Clock)

    def at(days_ago: float = 0) -> None:
        monkeypatch.setattr(_Clock, "at", _NOW - timedelta(days=days_ago))

    at(0)
    return at


@asynccontextmanager
async def _opened(tmp_path, name: str = "events.db"):
    log = EventLog(db_path=tmp_path / name)
    await log.start()
    try:
        yield log
    finally:
        await log.stop()


async def _fill(log, count: int) -> list[int]:
    return [await log.log(category="c", event=f"e{i}", data={"i": i}) for i in range(count)]


async def _rows(log) -> list[tuple]:
    async with log._db.execute("SELECT id, prev_hash, row_hash FROM events ORDER BY id") as cursor:
        return [tuple(row) async for row in cursor]


async def _anchors(log) -> list[tuple]:
    async with log._db.execute("SELECT event_id, row_hash FROM events_truncation_anchor") as cursor:
        return [tuple(row) async for row in cursor]


async def _sql(log, sql: str, *params) -> None:
    await log._db.execute(sql, params)
    await log._db.commit()


def _seen(verdict):
    """``(the pair, state, anchor_id)`` of a ``ChainVerdict``."""
    return (tuple(verdict), verdict.state, verdict.anchor_id)


async def _relink_to_genesis(log, row_id: int) -> None:
    """Rewrite one row as the append before BF-980 wrote it on an emptied table: linked to genesis, hash recomputed."""
    async with log._db.execute(
        f"SELECT {', '.join(_PAYLOAD_COLUMNS)} FROM events WHERE id = ?", (row_id,)
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None, "premise: the row to relink exists"
    row_hash = _compute_row_hash(prev_hash=EventLog.GENESIS_HASH, payload=dict(zip(_PAYLOAD_COLUMNS, row)))
    await _sql(
        log, "UPDATE events SET prev_hash = ?, row_hash = ? WHERE id = ?", EventLog.GENESIS_HASH, row_hash, row_id
    )


async def _emptied(log, at) -> tuple[int, str]:
    """Log three rows ten days ago, prune them all by age, and prove the state BF-980 is about was reached."""
    at(10)
    old = await _fill(log, 3)
    before = await _rows(log)
    at(0)
    assert await log.prune(retention_days=7, max_rows=0) == 3, "premise: the age prune deletes every row"
    assert await _rows(log) == [], "premise: the table is empty"
    assert await _anchors(log) == [(old[2], before[2][2])], "premise: the anchor names the last row deleted"
    return old[2], before[2][2]


# A1 (the issue's first acceptance line)
async def test_a_prune_to_empty_then_one_event_chains_from_the_anchor(tmp_path, monkeypatch):
    at = _clock(monkeypatch)
    async with _opened(tmp_path) as log:
        anchor_id, anchor_hash = await _emptied(log, at)
        new_id = await log.log(category="c", event="after")
        rows = await _rows(log)
        assert [row[0] for row in rows] == [new_id] and new_id > anchor_id, "premise: one row, after the anchor"
        assert rows[0][1] == anchor_hash
        assert _seen(await log.verify_chain()) == ((True, None), "truncated", anchor_id)


# A2 (the issue's second acceptance line)
async def test_a_first_row_forged_from_genesis_after_an_anchor_is_broken(tmp_path, monkeypatch):
    at = _clock(monkeypatch)
    async with _opened(tmp_path) as log:
        anchor_id, _ = await _emptied(log, at)
        forged = await log.log(category="c", event="forged")
        await _relink_to_genesis(log, forged)
        assert (await _rows(log))[0][:2] == (forged, EventLog.GENESIS_HASH), (
            "premise: the first row after the anchor links to genesis"
        )
        assert _seen(await log.verify_chain()) == ((False, forged), "broken", anchor_id)
        await _sql(log, "DELETE FROM events_truncation_anchor")
        assert _seen(await log.verify_chain()) == ((True, None), "intact", None), (
            "control: the forged row is a well-formed genesis row; only the anchor rule rejects it"
        )


# A3
async def test_after_a_prune_that_keeps_rows_the_append_chains_from_the_tail_not_the_anchor(tmp_path):
    async with _opened(tmp_path) as log:
        ids = await _fill(log, 10)
        before = await _rows(log)
        assert await log.prune(retention_days=0, max_rows=6) == 4
        assert await _anchors(log) == [(ids[3], before[3][2])], "premise: an anchor beside kept rows"
        new_id = await log.log(category="c", event="after")
        assert (await _rows(log))[-1][:2] == (new_id, before[9][2])
        assert _seen(await log.verify_chain()) == ((True, None), "truncated", ids[3])


# A4
async def test_a_store_holding_an_anchor_and_no_rows_when_reopened_chains_its_next_row_from_the_anchor(
    tmp_path, monkeypatch
):
    at = _clock(monkeypatch)
    async with _opened(tmp_path) as log:
        anchor_id, anchor_hash = await _emptied(log, at)
    async with _opened(tmp_path) as reopened:
        assert (await _rows(reopened), await _anchors(reopened)) == ([], [(anchor_id, anchor_hash)]), (
            "premise: the reopened store holds the anchor and no row"
        )
        new_id = await reopened.log(category="c", event="after")
        assert (await _rows(reopened))[0][:2] == (new_id, anchor_hash)
        assert _seen(await reopened.verify_chain()) == ((True, None), "truncated", anchor_id)


# A5
async def test_wipe_after_an_anchor_still_starts_the_chain_at_genesis(tmp_path):
    async with _opened(tmp_path) as log:
        await _fill(log, 10)
        assert await log.prune(retention_days=0, max_rows=6) == 4
        assert await _anchors(log) != [], "premise: an anchor exists before the wipe"
        await log.wipe()
        assert (await _rows(log), await _anchors(log)) == ([], []), "premise: the wipe removed the rows and the anchor"
        new_id = await log.log(category="c", event="after")
        assert (await _rows(log))[0][:2] == (new_id, EventLog.GENESIS_HASH)
        assert _seen(await log.verify_chain()) == ((True, None), "intact", None)


# A6
async def test_an_empty_log_that_was_never_pruned_starts_at_genesis(tmp_path):
    async with _opened(tmp_path) as log:
        assert (await _rows(log), await _anchors(log)) == ([], []), "premise: no rows and no anchor"
        ids = await _fill(log, 2)
        rows = await _rows(log)
        assert [row[:2] for row in rows] == [(ids[0], EventLog.GENESIS_HASH), (ids[1], rows[0][2])]
        assert _seen(await log.verify_chain()) == ((True, None), "intact", None)


# A7 (D3: the compatibility decision)
async def test_a_store_that_held_a_genesis_restart_reads_broken_until_its_next_prune_moves_the_anchor(
    tmp_path, monkeypatch
):
    at = _clock(monkeypatch)
    async with _opened(tmp_path) as log:
        anchor_id, _ = await _emptied(log, at)
        restart = await log.log(category="c", event="restart")
        await _relink_to_genesis(log, restart)  # what the append before BF-980 wrote here
        second = await log.log(category="c", event="next")
        held = await _rows(log)
        assert held[0][:2] == (restart, EventLog.GENESIS_HASH) and held[1][:2] == (second, held[0][2]), (
            "premise: the store holds an anchor, a row chained from genesis and a row chained from it"
        )
    async with _opened(tmp_path) as reopened:
        assert await _rows(reopened) == held, "premise: opening the store rewrites no row"
        assert _seen(await reopened.verify_chain()) == ((False, restart), "broken", anchor_id)
        newest = await reopened.log(category="c", event="newest")
        assert await reopened.prune(retention_days=0, max_rows=1) == 2, "premise: the next prune deletes the restart rows"
        assert [row[0] for row in await _rows(reopened)] == [newest]
        assert await _anchors(reopened) == [(second, held[1][2])]
        assert _seen(await reopened.verify_chain()) == ((True, None), "truncated", second)


# A8 (D1: the anchor's hash is taken verbatim)
async def test_the_append_and_the_walk_take_the_anchor_hash_verbatim_even_when_it_is_empty(tmp_path, monkeypatch):
    at = _clock(monkeypatch)
    async with _opened(tmp_path) as log:
        anchor_id, _ = await _emptied(log, at)
        # A row written before AD-490 carries row_hash '' (BF-942 L4); an anchor naming one holds ''.
        await _sql(log, "UPDATE events_truncation_anchor SET row_hash = '' WHERE singleton = 1")
        assert await _anchors(log) == [(anchor_id, "")], "premise: the anchor holds an empty hash"
        new_id = await log.log(category="c", event="after")
        assert (await _rows(log))[0][:2] == (new_id, "")
        assert _seen(await log.verify_chain()) == ((True, None), "truncated", anchor_id)


# A9
async def test_a_prune_that_empties_the_table_and_a_concurrent_append_leave_a_chain_that_verifies(
    tmp_path, monkeypatch
):
    at = _clock(monkeypatch)
    async with _opened(tmp_path) as log:
        at(10)
        old = await _fill(log, 3)
        before = await _rows(log)
        at(0)
        results = await asyncio.gather(
            log.prune(retention_days=7, max_rows=0),
            log.log(category="c", event="concurrent"),
            return_exceptions=True,
        )
        assert [r for r in results if isinstance(r, BaseException)] == []
        assert results[0] == 3, "premise: the prune deleted every old row"
        rows = await _rows(log)
        assert [row[0] for row in rows] == [results[1]], "premise: only the concurrent row remains"
        # Whichever order the write lock admits them in, the row follows the last old row's hash:
        # appended first it chains from the tail, appended after the prune from the anchor.
        assert rows[0][1] == before[2][2]
        assert _seen(await log.verify_chain()) == ((True, None), "truncated", old[2])
```

### 7.3 M2: tracking

**P2-1.** `PROGRESS.md`. The SEARCH is the title line alone, so that it still matches after #1680 adds an entry on top (the title occurs once). Replace `DATE` with M2's date.
SEARCH:
```
# ProbOS Progress
```
REPLACE:
```
# ProbOS Progress

**BF-980 (DATE), #1811 -- after a prune empties the event table, the next event chains from the truncation anchor, and a first row that links to genesis after an anchor is broken.**
- **Base.** `EventLog._insert_chained_row` started at `GENESIS_HASH` and replaced it only with a tail row's hash, so the first event after a prune that left no row restarted the AD-490 chain at genesis, and `verify_chain` accepted a genesis-linked first row after a BF-942 anchor (BF-942 D4).
- **Fix.** With no tail row the append reads the anchor in the same `BEGIN IMMEDIATE` transaction and chains from its `row_hash`; `verify_chain` drops the genesis exception, so after an anchor the first row must link to the anchor's hash and to nothing else. Unanchored chains, `wipe()` (it deletes the anchor, so the chain starts at genesis), `_compute_row_hash` and the schema are unchanged. A store that already held a genesis restart after an anchor reads `broken` at that row until its next prune that deletes a row moves the anchor; none was measured (0 of 1 vessel). `tests/test_bf980_eventlog_anchor_restart.py` adds 9 cases; the BF-942 case that pinned the restart now pins the anchor link. Contract `prompts/bf-980-eventlog-anchor-restart.md`.
- **Limits.** Narrows BF942-F5 (#1754): a genesis restart after an anchor is no longer accepted. Kept: a writer of `events.db` who deletes every row after the anchor, or the newest rows, is not seen (the next append chains from the anchor as after a prune), and the anchor sits in the file it describes (BF-942 L1, L2).
```

**P2-2.** `DECISIONS.md`. BF-942's D4 gets a pointer, and the BF-980 entry goes straight after BF-942's.
SEARCH:
```
- *D4 (an emptied table).* After an anchor, a first retained row that links to genesis verifies: the append restarts the chain there. Rejected: keeping the newest row; chaining the append to the anchor.
- *D5 (the result).* A two-item tuple subclass with `state` and `anchor_id`: the 24 call sites that unpack two items or compare with `(True, None)` are unchanged. Rejected: a three-item tuple; a second method beside it (the AuditLog's `chain_state`).
- *D6, D7 (no anchor; wipe).* A store pruned before this change reports `unanchored`, `(False, first_id)` as before, and the walk goes on from that row's own link so an edit behind it is found. Rejected: reporting `intact`; an anchor written at upgrade (it would bless today's head). `wipe` clears the anchor in its transaction.
- *Residual.* L1 to L10 of the contract. *Reversal.* Revert the BF-942 commits (the table stays and is ignored).

### BF-943 -- Agents cannot rewrite the Captain's governance, instruction and manifest files in the running checkout (2026-11-09, #1707)
```
REPLACE:
```
- *D4 (an emptied table).* After an anchor, a first retained row that links to genesis verifies: the append restarts the chain there. Rejected: keeping the newest row; chaining the append to the anchor. *Replaced by BF-980 (#1811): the append chains an emptied table from the anchor and the walk has no genesis exception.*
- *D5 (the result).* A two-item tuple subclass with `state` and `anchor_id`: the 24 call sites that unpack two items or compare with `(True, None)` are unchanged. Rejected: a three-item tuple; a second method beside it (the AuditLog's `chain_state`).
- *D6, D7 (no anchor; wipe).* A store pruned before this change reports `unanchored`, `(False, first_id)` as before, and the walk goes on from that row's own link so an edit behind it is found. Rejected: reporting `intact`; an anchor written at upgrade (it would bless today's head). `wipe` clears the anchor in its transaction.
- *Residual.* L1 to L10 of the contract. *Reversal.* Revert the BF-942 commits (the table stays and is ignored).

### BF-980 -- After a prune empties the event table, the next row chains from the truncation anchor; no genesis exception after an anchor (DATE, #1811)

- *Scope.* `substrate/event_log.py` (`_insert_chained_row`; `verify_chain` and its docstring), tests (`tests/test_bf980_eventlog_anchor_restart.py`; one BF-942 case rewritten in place). Contract `prompts/bf-980-eventlog-anchor-restart.md`. Replaces BF-942's D4.
- *D1 (the append).* With no tail row the append reads the anchor inside its `BEGIN IMMEDIATE` transaction and chains from its `row_hash` verbatim, as the AD-1278 `AuditLog.append` chains from its anchor when no entry is held; a tail row decides exactly as before. Rejected: a prune that never deletes the newest row (it changes retention); reading the anchor on every append.
- *D2 (the walk).* After an anchor the first row must link to the anchor's hash; a first row that links to genesis is `broken`, `(False, its id)`. Without an anchor nothing changes (`intact`; `unanchored` with the walk going on from the first row's own link). Rejected: a separate `restarted` state (a forged restart and one written by the old append are byte-identical).
- *D3 (a store that already holds a genesis restart after an anchor).* No exception and no migration: it reads `broken` at that row until its next prune that deletes a row, which deletes that head row and re-anchors at a real one. Reach: the code from BF-942's merge (2026-11-09) to this one, an age prune that left no row (no event logged for `retention_days` while running, or a clock stepped forward by more than that) and then an append; the Captain's vessel held none (no anchor table; 0 of 1, 2026-11-18); no production code reads the verdict. Rejected: a marker written once at start-up that exempts the held row (a schema addition and a second acceptance rule kept for a state that heals itself, for no measured store); re-anchoring once at start-up (it rewrites the anchor and blesses whatever head exists, the trust on first use BF-942 D6 rejected).
- *Residual.* Narrows BF942-F5 (#1754) and keeps the rest of it: a writer of `events.db` who deletes every row after the anchor, or the newest rows, is not seen (the next append chains from the anchor as after a prune); one who forges the anchor or rewrites rows and later hashes is not either (BF-942 L1, L2). L1 to L6 of the contract. *Reversal.* Revert the BF-980 commits; a row written meanwhile links to the anchor, which BF-942's walk also accepts.

### BF-943 -- Agents cannot rewrite the Captain's governance, instruction and manifest files in the running checkout (2026-11-09, #1707)
```

**Ledger.** Run G3. Neither heading contains a status word that `gen_ad_ledger.py` reads (`scripts/gen_ad_ledger.py:127-131`: retired, withdrawn, superseded, deferred, closed, shipped, staged, landed, open). The DECISIONS heading therefore records `shipped`, and the PROGRESS head records `mentioned`, as BF-942's did. Do not edit the roadmap Bug Tracker; it lags (BF-942 did not edit it either).

## 8. Tests (`tests/test_bf980_eventlog_anchor_restart.py`, 9 cases; plus the rewritten BF-942 case)

| Id | Case | Proves | On the base, first failing line |
|---|---|---|---|
| A1 | prune to empty, then one event | Acceptance 1: `prev_hash` is the anchor's `row_hash`; `truncated`, `ok` True | `assert rows[0][1] == anchor_hash` (genesis) |
| A2 | a first row forged from genesis after an anchor | Acceptance 2: `broken` at that row, with `anchor_id`. Control: without the anchor the same row is `intact`. | `assert _seen(...) == ((False, forged), "broken", anchor_id)` (the base says `truncated`) |
| A3 | a cap prune that keeps rows, then an append | The tail still wins over the anchor | passes (guard) |
| A4 | anchor and no rows, reopened, then an append | The anchor persists, and the append on a fresh connection chains from it | `assert (await _rows(reopened))[0][:2] == (new_id, anchor_hash)` |
| A5 | an anchor, then `wipe`, then an append | A wiped log restarts at genesis and reads `intact` | passes (guard) |
| A6 | a fresh log | Unanchored chains are unchanged: genesis, `intact` | passes (guard) |
| A7 | a store holding the old restart, reopened, then a prune | D3: no rewrite at open; `broken` at the restart row; the next deleting prune heals it to `truncated` | `assert _seen(await reopened.verify_chain()) == ((False, restart), "broken", anchor_id)` |
| A8 | an anchor whose hash is `''` | D1: the append and the walk take the anchor verbatim | `assert (await _rows(log))[0][:2] == (new_id, "")` |
| A9 | an emptying prune alongside an append (`gather`) | Either order verifies; with the prune first, the row chains from the anchor | `assert rows[0][1] == before[2][2]` (prune first gives genesis) |
| T3 (BF-942, rewritten) | `test_after_a_prune_empties_the_table_the_next_row_links_to_the_anchor` | The pin moves from genesis to the anchor | `assert first[:2] == (old[2] + 1, before[2][2])` |

Every case asserts its state before the effect (`_emptied`, and the `premise:` lines). None can pass by finding nothing, because each premise asserts an exact row set or anchor row. The unanchored cases (BF-942 T6) and the `wipe` cases (BF-942 T4[wipe]; `test_database_retention.py` `TestEventLogWipe`; `test_bf873` `test_wipe_rolls_back_before_suppressing_commit_failure`) are not edited, and must pass unchanged in G1 and G2.

## 9. Mutation rows (each Line occurs once, stripped, in `src/probos/substrate/event_log.py` on M1's head)

| # | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|
| 1 | `prev_hash = anchor[1]` | `prev_hash = self.GENESIS_HASH` | **A1** (the issue's: restoring GENESIS_HASH in the append), A4, A8, A9, BF-942 T3 (rewritten) |
| 2 | `first = False` | `first = False; expected_prev = self.GENESIS_HASH if (anchor is not None and stored_prev == self.GENESIS_HASH) else expected_prev` (exactly the deleted exception's effect) | **A2** (the issue's: restoring the exception in verify_chain), A7 |
| 3 | `if not has_tail:` | `if True:` | A3 (designed killer); also A7 at a premise line |
| 4 | `if anchor is not None:` | `if True:` | A6 (`TypeError` on the first append to a never-pruned log), A5, and most cases that log |
| 5 | `await self._db.execute("DELETE FROM events_truncation_anchor")` | `await self._db.execute("SELECT 1")` | A5, BF-942 T4[wipe] |
| 6 | `if anchor is None:` (carried over from BF-942 row 6; this is the unanchored path the edit surrounds) | `if False:` | BF-942 T6[pruned before], T6[edit behind] |

**Campaign.** The Builder runs this campaign on M1's head with the new file and the BF-942 file (baseline: 9 + 22 passed). It records the base tree, the LF sha256 of `event_log.py` and of both test files, and the cases each mutant fails. Every mutant must be killed by at least the cases named in bold or listed first. A survivor is a hard stop for the Architect. That run is the campaign of record, and a later Builder whose three files match those hashes does not repeat it.

## 10. What this does NOT change

These are untouched: `_compute_row_hash`, `GENESIS_HASH`, `log()`, `_rollback_quietly`, `prune`, `_delete_head`, `wipe`, `_read_truncation_anchor`, `_SCHEMA` (so `docs/development/store-baseline.yaml` is too), `ChainVerdict`, the unanchored path, every existing row, hash, id and column, the retry and budget logic of BF-873, `runtime.py`, `startup/`, `config_models/core.py`, `config/system.yaml`, `__main__.py`, the security `AuditLog` and the identity ledger, `docs/development/deterministic-ship.md` (`git grep -n genesis -- docs/development/deterministic-ship.md` finds nothing), and the roadmap. No production caller of `verify_chain` is added. OSS only; no dependency.

## 11. Recorded limits

- **L1 (kept from BF942-F5).** A writer of `events.db` who deletes every row after the anchor, or the newest rows, is not seen: the next append chains from the anchor exactly as it would after a prune. The same holds for forging the anchor, or rewriting rows and every later hash (BF-942 L1, L2). Considered and deferred: AUTOINCREMENT ids could show a gap between the anchor's id and the first row's id after such a deletion, but a writer can reset `sqlite_sequence` too, and BF-942 treats the ids as not dense.
- **L2.** A store that held a genesis restart after an anchor reads `broken` at that row until its next prune that deletes a row (D3). None was measured, and no production code reads the verdict (BF-942 L10 still governs a future caller).
- **L3.** The append now reads the anchor when the table is empty: one primary-key SELECT inside the write transaction, only on an empty table. If an outside writer dropped `events_truncation_anchor` after `start()`, that append raises (propagate tier: data integrity). The event is then not recorded and the transaction is rolled back by BF-873's path. `verify_chain` raises in the same case, and the next `start()` recreates the table.
- **L4.** An anchor hash of `''` is taken verbatim (A8), while a tail hash of `''` still yields genesis (`:791-792`, unchanged). The tail case is already `broken` at that pre-AD-490 row (BF-942 L4). The anchor case would otherwise turn a verifiable chain into a `broken` one.
- **L5.** `verify_chain` still takes no lock (BF-942 L3).
- **L6.** `wipe()` restarts the chain at genesis and records nothing about the reset. It has no production caller (BF-942 L7). Recording the reset in the chain (prior art, section 13) is considered and deferred.

## 12. Verified Against Codebase (2026-11-18, the scratch tree at `9f43697f`)

```
git log -1 -> 9f43697fd8433071dd0f0afc394fba06de905a0c 2026-11-17 14:53:29 -0700
git rev-parse HEAD:<path> -> event_log.py e142a3c3..., test_bf942 e509199d..., PROGRESS.md c4dbda8a..., DECISIONS.md 02f99b21...
event_log.py:79      id              INTEGER PRIMARY KEY AUTOINCREMENT,
event_log.py:97      CREATE TABLE IF NOT EXISTS events_truncation_anchor (
event_log.py:105     def _compute_row_hash(*, prev_hash: str, payload: dict[str, Any]) -> str:
event_log.py:483     class ChainVerdict(tuple[bool, int | None]):
event_log.py:524     GENESIS_HASH: str = "0" * 64
event_log.py:532     self._write_lock = asyncio.Lock()
event_log.py:549     await self._db.executescript(_SCHEMA)
event_log.py:689     async with self._write_lock:
event_log.py:772     async def _insert_chained_row(self, payload: dict[str, Any]) -> int | None:
event_log.py:784-793 BEGIN IMMEDIATE; prev_hash = self.GENESIS_HASH; SELECT row_hash FROM events ORDER BY id DESC LIMIT 1; if prior: prev_hash = prior
event_log.py:796     "INSERT INTO events "
event_log.py:1251    async def verify_chain(self) -> ChainVerdict:
event_log.py:1255-1259 the docstring "... or to genesis when the prune left no row and the next append restarted the chain."
event_log.py:1266    anchor = await self._read_truncation_anchor()
event_log.py:1273    expected_prev = anchor[1] if anchor is not None else self.GENESIS_HASH
event_log.py:1293    first = False
event_log.py:1294    if anchor_id is not None and row[0] <= anchor_id:
event_log.py:1297    if anchor is None:
event_log.py:1300    elif stored_prev == self.GENESIS_HASH:
event_log.py:1302    if stored_prev != expected_prev:
event_log.py:1314    async def _read_truncation_anchor(self) -> tuple[int, str] | None:
event_log.py:1346    async with self._write_lock:            (prune)
event_log.py:1355-1358 age boundary "... OR NOT EXISTS (SELECT 1 FROM events WHERE timestamp >= ?) ..."
event_log.py:1371    cap boundary "SELECT id, row_hash FROM events ORDER BY id ASC LIMIT 1 OFFSET ?"
event_log.py:1402    "INSERT OR REPLACE INTO events_truncation_anchor (singleton, event_id, row_hash) VALUES (1, ?, ?)",
event_log.py:1415    await self._db.execute("DELETE FROM events_truncation_anchor")
runtime.py:730       self.event_log = EventLog(db_path=self._data_dir / "events.db")
runtime.py:4087      await asyncio.sleep(cfg.prune_interval_seconds)
runtime.py:4089      await self.event_log.prune(
startup/infrastructure.py:80   await event_log.start()
startup/infrastructure.py:112  event_prune_task = asyncio.create_task(
startup/finalize.py:6367       await runtime.event_log.log(category="system", event="started")
config_models/core.py:148-150  retention_days: int = 7; max_rows: int = 100_000; prune_interval_seconds: float = 3600.0
config/system.yaml:1854-1856   retention_days: 7; max_rows: 100000; prune_interval_seconds: 3600.0
__main__.py:2663     "files": ["scheduled_tasks.db", "events.db"],
security/audit.py:169-171  prior_hash = (self.entries[-1].entry_hash if self.entries else self._anchor_hash())
security/audit.py:244      prior = self._anchor_hash()   (verify_chain: no genesis exception)
tests/test_bf942_eventlog_truncation_anchor.py:252  async def test_a_prune_that_empties_the_table_restarts_the_chain_and_it_still_verifies(
tests/test_bf942_eventlog_truncation_anchor.py:265  assert first[:2] == (old[2] + 1, EventLog.GENESIS_HASH), "premise: the append restarts at genesis"
tests/test_ad490_eventlog_hash_chain.py:7    from probos.substrate.event_log import EventLog, _compute_row_hash
tests/test_bf873_event_log_chain_concurrency.py:89  if "SELECT row_hash FROM events" in str(sql):
DECISIONS.md:1590    ### BF-942 -- Routine EventLog pruning leaves the hash chain verifiable ... (2026-11-09, #1706)
DECISIONS.md:1595    - *D4 (an emptied table).* ...
DECISIONS.md:1600    ### BF-943 -- ...
PROGRESS.md:1        # ProbOS Progress   (one occurrence)
scripts/gen_ad_ledger.py:127-131  the status words a head line is read for
git log: bab8413e 2026-11-09 Merge pull request #1778 (BF-942)
scripts/ad_ceiling.py -> CEILING AD-1360 (issue titles), NEXT AD-1361
```

**Absence Verified (2026-11-18).**
```
CLAIM: no production caller of EventLog.verify_chain
RUN:   Grep "verify_chain" over src/probos; Grep over scripts/ and ui/src
FOUND: src: event_log.py (def + docstrings), identity.py, routers/identity.py:58 (identity registry), security/audit.py, startup/finalize.py:4769 (AuditLog), identity_keys.py and federation/continuity.py (verify_chain_signatures/_structure); scripts: none; ui/src: none
HOLDS: yes

CLAIM: one appender and one pruner of events; wipe has no production caller
RUN:   Grep "INSERT INTO events\b|INSERT OR [A-Z]+ INTO events\b" src; Grep "verify_chain\(|\.prune\(|\.wipe\(" src; Grep "event_log\.wipe|wipe\(" src/probos
FOUND: event_log.py:796; runtime.py:4089 is the only EventLog prune (the others are admission/recorder.py:348, infrastructure/backup.py:364, runtime.py:4109 cognitive_journal); wipe defs only (event_log.py:1408, cognitive/journal.py:286)
HOLDS: yes

CLAIM: the new names are free; no test pins the genesis restart other than test_bf942:265
RUN:   Grep "has_tail|tail_found|if anchor is not None:|if not has_tail|prev_hash = anchor" event_log.py; Grep "GENESIS_HASH|\"0\" \* 64" tests/
FOUND: 0 in event_log.py; in tests the EventLog hits are test_bf942:265 (the restart pin) and test_ad490:26 (first event of a fresh log uses genesis; unanchored, unchanged); the rest are other subsystems' digests
HOLDS: yes

CLAIM: no prompt or commit already uses BF-980
RUN:   Glob prompts/bf-980*; git log --all -i --grep=BF-980; gh issue list --state all --search "BF-980 in:title"
FOUND: none; none; #1811 only (OPEN)
HOLDS: yes
```

**Read, not run.** I ran no test, applied no block by tool, and computed no sha256 of a patched file. The base-failure lines in section 8 and the killers in section 9 come from reading the code, and M0-2 and the campaign confirm them. I did not read the vessel's live `events.db` (R3 is the orchestrator's replay).

## 13. Prior Art and Blind Spots

- **Internal: adopted.** The AD-1278 `AuditLog` chains a new entry from its anchor when no entry is held (`security/audit.py:169-171`), and its `verify_chain` starts at the anchor with no genesis exception (`:244-256`). BF-980 brings the EventLog to that rule. BF-942's contract made the opposite choice (D4, option 3 rejected only as "out of scope"), and this replaces it.
- **External** (5 searches budgeted, 1 used; the problem is narrow).
  - **Rejected for chaining: rotation that starts a fresh chain** (Acra's audit logger, per [Cossack Labs](https://www.cossacklabs.com/blog/audit-logs-security/)). A segment that does not link to the one before cannot show that segment was deleted.
  - **Considered, deferred (L6): record a legitimate reset inside the chain** ([NR Vault audit evidence](https://docs.typo3.org/p/netresearch/nr-vault/0.15/en-us/Security/AuditEvidence.html)). `wipe` has no production caller.
  - **Considered, deferred (BF-942 L1): external checkpoints of the chain head and length** ([quipu-core checkpoints](https://docs.rs/crate/quipu-core/0.1.0/source/src/checkpoint.rs)). These are the external witness BF-942 left for its own decision.
  - `docs/research/reference-projects.md` lists no tamper-evident-log project, so none was examined (date used: 2026-11-18).
- **Blind spots handled:**
  - an anchor with no rows at reopen (A4);
  - a tail beside an anchor (A3);
  - `wipe` (A5);
  - a never-pruned log (A6);
  - a store holding the old restart (A7);
  - an empty anchor hash (A8);
  - a prune and an append together (A9);
  - an anchor newer than every row: unchanged, BF-942 `test_the_first_retained_row_must_follow_the_anchor`;
  - a missing anchor table at append (L3);
  - the test tracer's substring (M0-6).
- **What discards a correct result.** After a wipe, a correct genesis start: A5 keeps it. A correct event whose anchor read fails is lost (L3; only an outside drop of the table reaches this). After a prune with rows kept, a correct tail link: A3 keeps it.

## 14. Diff Reviewer: properties to verify

1. **The append.** The anchor is read only when the tail SELECT returned no row. Both reads run after `BEGIN IMMEDIATE` and before the INSERT, on `self._db`, inside the existing `try`/`except BaseException` that rolls back. The INSERT and commit are byte-identical. With a tail row (any hash, `''` included) the code path is the old one.
2. **The value.** The append uses `anchor[1]`, the same value the walk sets as `expected_prev` (`:1273`). `_compute_row_hash` is called exactly as before.
3. **The walk.** Only the two `elif` lines are removed. For an anchored first row whose `prev_hash` is not the anchor's hash, the verdict is `ChainVerdict(False, row id, state="broken", anchor_id=...)` through the existing check. The unanchored branch (`detached_at`, `unanchored`) is unchanged byte for byte. The id check at `:1294` still runs first.
4. **No other hunk** appears in `prune`, `_delete_head`, `wipe`, `_SCHEMA`, `ChainVerdict`, `log()` or the BF-873 retry and budget code. No schema, store-baseline or config change.
5. **The docstrings** (P1-1, P1-3) say what the code does. No text in `src/` still says that a genesis restart after an anchor verifies (`git grep -n -i "restart" -- src/probos/substrate/event_log.py`).
6. **The tests.** Each new case asserts its state before its effect. The BF-942 case is rewritten in place with its reason inline, and the file still has 22 cases. No unanchored or `wipe` test is edited. The tracer substring at `test_bf873:89` is not matched by the new SQL.
7. **The trackers.** The two headings carry no ledger status word. `gen_ad_ledger.py --check` is clean, and the ledger pair is committed with M2.

## 15. Acceptance criteria

- G0 to G3 pass as stated, and the batch's broad gate is green with a receipt.
- **The issue's list:**
  - prune to empty, then one event: its `prev_hash` is the anchor's `row_hash`, and `verify_chain` answers `truncated` with `ok` True (A1);
  - a first row forged from genesis after an anchor is `broken` (A2);
  - mutation: restoring the exception fails A2 (row 2), and restoring `GENESIS_HASH` in the append fails A1 (row 1);
  - the tests for unanchored chains and for `wipe()` pass unchanged (BF-942 T6, T4[wipe]; `test_database_retention.py`; `test_bf873`; `test_ad490`).
- **Compatibility (D3):** a store holding the old restart reads `broken` and heals at its next deleting prune, with no row rewritten (A7).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## For the register (#1754)

- **BF942-F5:** narrowed by BF-980. "Empty the table (the next append restarts at genesis, which `verify_chain` accepts after an anchor)" is closed: a genesis restart after an anchor now reads `broken`, and the append never writes one. The rest stays open as filed: a writer of `events.db` can forge an anchor and a matching cut, rewrite rows and every later hash, or delete the newest rows or every row after the anchor. After that deletion, the next append chains from the anchor exactly as after a prune (L1).
