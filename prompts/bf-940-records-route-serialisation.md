# BF-940 (#1686): A record the reader parsed is a record the records routes can answer: the read route and every route that returns a frontmatter ask the JSON writer before they return (slice 3 of the issue)

**Drafted by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge was logged out), 2026-11-11
**Status:** ready to build on slice 2's merge. **Reading tree:** `D:\ProbOS-worktrees\bf940s2-build`, `HEAD` `e327d26e` (slice 2's frozen head, tree `ca85ef7047a8e19bd502ad4e1f6c21868a94b62e`; `origin/main` `a66e272f` had not moved). Every SEARCH below is in the slice-2 state of its file (`routers/records.py` is untouched by slice 2). **Oracle:** a read-only consult: no pytest, no timing or benchmark script, no script that spawns a child process (git read commands were run from the shell). In-memory scripts applied the 10 SEARCH/REPLACE pairs of M2 to the LF blob of `routers/records.py` (each SEARCH once; the result compiles), exec'd it as `probos.routers.records` and drove the real router through `TestClient` over a real `RecordsStore` of hand-made records (no `initialize()`, `~` moved, a fresh temporary directory per case). A hand driver (a stand-in for the few pytest features the file uses; not the runner) called the 43 functions of N1-1: on the reading tree 15 pass and 28 fail, each at the `assert` section 6 names; on M2's head all 43 pass; the 12 mutants of section 9 fail exactly the cases listed. The route tests of nine existing files and the BF-949 source-scan tests were driven the same way (section 11, M-5). The census of 7.4 was run on synthetic trees. **Not run:** G1 to G3, pytest, xfail semantics, `-n`, the broad gate, the architecture check, the ledger generator, vitest, a timing run (L4), the census on a real tree, the orchestrator's slicer. After the text was written, the real apply tool (`apply_search_replace_blocks_bare.py`, run in-process on a throwaway root holding copies of the three files) wrote the new file and applied the 10 + 1 + 2 pairs with 0 failures, and the files it produced have the hashes of section 9.
**Base blobs** (git blob ids of the LF-normalised working copy of the reading tree, computed by script; each equals `git rev-parse HEAD:<path>`; they must equal slice 2's merge): `src/probos/routers/records.py` `1b95965effea0a7d666830413bef677ae463f06a`, `PROGRESS.md` `da466972f78120767dc6646e3bb57e1b91d34405`, `DECISIONS.md` `29cddd81ee018a0ea87da588005372a690547d70`; tests this slice relies on and does not edit: `tests/test_ad1145_provo_projection.py` `a3507fb93fad854475068f0d0e597c79c817f54f`, `tests/test_bf949_notebook_reader_identity.py` `8a7a524225ccfd4bbe78f6411a9c82e9ec8b7477`, `tests/test_issue1368_readiness.py` `3ffdf90fd54f2480c8710d9cca80cd71d0096909`.
**Dependencies:** slice 2 merged. **Tier:** M1 STANDARD (tests); M2 HIGH (the boundary of every route that returns a record); M3 STANDARD. **Estimated tests:** one new file, 43 cases (15 pass and 28 xfail at M1), and no existing test edited. **BF number:** BF-940, held by #1686 (open, `bug`); nothing new is allocated.
**What this contract closes of #1686:** F7-1 (the records route returns 500 for a record the reader parsed). **The issue keeps** L19, the last box, which follows in a later slice, and stays open: the pull request says `Refs #1686`, not `Closes`.

**Which text describes the head.** Before building: slice 2 is merged, `git rev-parse HEAD:<path>` for the three edited paths prints the blobs above, `git diff --stat e327d26e HEAD -- src/probos/routers tests PROGRESS.md DECISIONS.md` shows nothing that is not slice 2's merge, and the new test file does not exist. If a blob differs, every SEARCH must still occur exactly once, else it is a hard stop for the Architect. Working copies are CRLF and SEARCH text is LF. Where prose and a block differ, the block wins. Apply the pairs with the `edit` tool one at a time, whole block, in label order.

## 1. Problem

1. **The defect.** `read_record` (`routers/records.py:58-102`) catches the failures of `read_entry` (`:86-96`) and then returns its mapping. FastAPI 0.136.1 writes a `-> Any` handler's return after the handler has returned, with `TypeAdapter.dump_json` over `Any` (`fastapi/routing.py:689-715`, `fastapi/_compat/v2.py:215-237`), outside that `try`. A record the reader parsed and the writer cannot write therefore answers an unhandled HTTP 500 (the framework's plain-text body, no `availability`), where a record the reader cannot parse answers the controlled 503 `records.read_failed`.
2. **What the writer refuses** (hand driver; 16 shapes `yaml.safe_load` builds, plus depth and self-reference; section 11, M-2). A mapping nested too deeply: for n single-key mappings under one frontmatter key the read route's body fails from n = 97 and a listing's body from n = 95, two levels sooner because a listing holds a record two levels below its top. Bytes that are not UTF-8, as a value or as a key. A container that holds itself (`&a [*a]`). Every other shape tried is written: a UTC datetime as `...Z`, a date, a set as a list, UTF-8 bytes as text, an int key as text, `nan` and `inf` as `null`, a big int, an `!!omap` product. The records need not be hand-made: `write_notebook("alice", ..., metrics={"k": b"\xff\xfe"})` and a 150-level `metrics` mapping both write and read, and both read 500 on the base (M-6); no production caller passes either (slice 2's callers table).
3. **Which handlers share it** (a run: 10 GET routes x 8 records on the base and on M2's head, M-1; the module's 13 store and service calls, `records.py:35, 50, 88, 114, 123, 134, 151, 187, 199, 228, 280, 309, 340`):

| Handler (route) | Its body holds | Base, for a record at 100 or 450 levels, with non-UTF-8 bytes, or holding itself |
|---|---|---|
| `read_record` (`GET /documents/{path}`) | `read_entry`'s `{frontmatter, content, path}` | 500 |
| `list_records`, `get_captains_log`, `list_notebook`, `browse_records` | `list_entries`' `{path, frontmatter}` items (`records_store.py:1522`) | 500, for every record in the listing |
| `search_records` | a hit's `frontmatter` and `snippet` (`records_store.py:479-482`) | 500 |
| `get_records_graph` | a node's `label`, `fm.get("topic_slug") or fm.get("topic") or <file stem>` (`backlinks.py:380`) | 500 when the value is the topic; 200 under another key |
| `read_record?format=prov-jsonld` | strings only (`provo.py:240-295`) | 200 |
| `get_backlinks`, `get_records_timeline` | paths, text, counts | 200 |
| stats, history, the two POSTs | counts, git text, a path (read, `records.py:30-35, 105-115, 140-163, 193-202`; two need a git child) | not run |

4. **The reader's own limit.** A record nested 600 levels makes `read_entry` raise `RecursionError`: the read route answers 503 `records.read_failed` and `list_entries` skips it (`records_store.py:1508-1509`). Both are unchanged and are guards (T3).
5. **Consumers of the routes.** The HXI's Notebooks panel (the documents listing, an entry, the search) and Knowledge Browser (browse, graph, timeline, entry, backlinks), `ui/src/store/useStore.ts:1963, 2022, 2046, 2075, 2209-2214`; `git grep -l -F "/api/records"` outside tests, docs and prompts finds nothing else but `routers/records.py`, the trackers and the UI's own files. In `src`, no Python file calls the route: `read_head_to_head` (`recreation/history.py:184`) and the other callers of `list_entries` (`grep -rn "\.list_entries(" src`) call the store directly.
6. **Tests that rely on this module's shape.** `test_ad1145_provo_projection.py:583, :595` assert `result is entry` (the handler returns the store's own object); four AD-562 files and the BF-949 and BF-952 files call handlers as functions; `test_bf949_notebook_reader_identity.py:333-373` scans the source of every `.search(` caller; `test_issue1368_readiness.py:165, :189, :276` assert a secret is in neither the response nor the log.

## 2. Solution

`routers/records.py` gains `_JSON_WRITER = TypeAdapter(Any)`, `_writes(body) -> bool` and `_writable(records, key, route) -> list`. The read route, after its `?format=prov-jsonld` branch, answers `_read_failure("Record document unavailable", "records.read_failed", 503)` when `_writes(entry)` is false, and otherwise returns `entry` itself. The four listings, the browse and the search build their body from `_writable(...)`, which returns the same list when the whole body writes and otherwise the records that write, each tried inside `{key: [record]}` (the depth the record has in the body), logging the left-out paths (never a value). The graph answers its own `graph_failed` envelope when its body does not write. Nothing the writer produces is kept: a handler returns its own body, so every answered response is byte-identical to the one it sent before. No config, event, dependency or shared contract changes.

## 3. Decisions

Ranked by correctness, safety, compatibility, architectural fit, reversibility and validation cost; Delegated AD Execution Mode: the top is taken. "Boundary" asks whether an option weakens a privacy or audit control or breaks a compatibility promise (a Captain-only decision). Cells and sentences marked (read) are from source, not run; every other measurement is from my hand driver on the reading tree.

**D0. Scope.** The status of each route for a record at 100 or 450 levels, non-UTF-8 bytes or holding itself (graph: when the value is the topic); the same for a record at 90 levels and for the six-shape record (a UTC datetime, a date, a set, UTF-8 bytes, a unicode value under an int key, `nan`): status and response bytes equal the base's on nine routes under every option (the graph by status: its body holds `generated_at`, `backlinks.py:449`) (run, M-1, M-3).

| # | Option | Read route | Documents, notebook, captain's log | Browse, search | Graph | Boundary |
|---|---|---|---|---|---|---|
| A | The read route only (the box) | 503 `records.read_failed` | 500 | 500 | 500 | none |
| B | The read route and the three listings, one helper (slice 2's D4 suggestion) | 503 | 200, record left out | 500 | 500 | none |
| **C** | **Every handler whose body holds a record value (seven), one check (chosen)** | 503 | 200, record left out | 200, record left out | 500 `knowledge_browser.graph_failed` (the route's own envelope) | none |
| D | An application-level handler for `PydanticSerializationError` (slice 2's D4 option 3) | 503 with a generic code, not `records.read_failed` | 503, whole listing | 503, whole | 503 | breaks no promise in this module, but turns the failure of every route of the application into one 503 (by construction; not run beyond this router) |

Rank C > B > A > D. Correctness: only C leaves no route of the module at an unhandled 500 for such a record (slice 2's D4 named three listings; the browse and the search carry a frontmatter too, so B leaves the Knowledge Browser's main view and the Notebooks search at 500). Safety: all four fail closed and fabricate nothing; D also changes failures outside the module. Compatibility: A to C change only a status that was an unhandled 500; D changes other routers'. Architectural fit: C keeps each route's own envelope, which D cannot name. Reversibility: A to C one file; D a hook on the application. Validation cost: C the most (seven routes, 43 cases), A the least. The HXI (read): the Notebooks panel treats any non-OK response as empty (`useStore.ts:1964-1967, 2023-2026, 2047-2050, 2076-2079`), so under A it shows nothing while one such record exists; Knowledge Browser turns a body holding `availability` into that state (a 503 is `unavailable`, a plain-text 500 is `failed`, `ui/src/utils/resourceState.ts:62-79`) and retries at 10 s and 30 s, then stops (`:22-26`).

**D1. The mechanism** (slice 2's D4 chose `TypeAdapter(Any).dump_python(mode="json")` and returning its result; re-measured here). FastAPI 0.136.1 writes these handlers with `TypeAdapter.dump_json` (`fastapi/_compat/v2.py:215-237`); the first failing depth is the same 97 (the read body) and 95 (a listing body) for `dump_json`, `dump_python(mode="json")` and `to_jsonable_python`, so a check with either fails exactly where the later write would (run, M-2). Rows: the six-shape record and a 90-level record on the read route (bytes against the base), a record the writer cannot write, and the AD-1145 tests that call `read_record` as a function (7; hand driver).

| # | Option | Ordinary shapes | A record the writer cannot write | AD-1145's 7 tests | Boundary |
|---|---|---|---|---|---|
| **1** | **Ask `TypeAdapter(Any).dump_json`, discard what it writes, return the handler's own body (chosen)** | bytes equal | 503 (a listing: left out) | 7 pass: the same object is returned | none |
| 2 | `dump_python(mode="json")`, return the converted object (slice 2's D4) | bytes equal | 503 | 5 pass, 2 fail (`assert result is entry`, `:583` and `:595`); the returned mapping holds `str` for a datetime and `None` for `nan`; a relied-on test would have to change | none, but a shared test changes |
| 3 | `Response(content=dump_json(entry))`, one pass | bytes equal | 503 | 5 pass, 2 fail (the same two); a `Response` is not the mapping the handler tests index (read) | none, but a shared test changes |
| 4 | `JSONResponse(jsonable_encoder(entry))` (slice 2's D4 option 2) | the shapes record answers 503 (`nan` is refused: Starlette's `JSONResponse` renders with `json.dumps(allow_nan=False)`, `starlette/responses.py:198`); a UTC datetime is `...+00:00`, not `...Z` | answers 200 at 100 and 450 levels and fails with `RecursionError` near 991 levels, not monotone within four depths of it | 5 pass, 2 fail | **breaks AD-1145 DD-7's promise** (`records.py:60-70`: the body "is byte-identical to what this endpoint has always returned") |

Rank 1 > 2 > 3 > 4. Option 1 is the smallest change to what a client or a test sees: its only visible effects are the status of a record that was an unhandled 500. Slice 2's D4 said "repo precedent for `TypeAdapter`" (`routers/workforce.py:95`): that call is `validate_json`; nothing in `src` dumps through a `TypeAdapter`, so the precedent is for the import only. The writer refuses, among the 16 YAML-built shapes tried: bytes that are not UTF-8 (value or key); with depth and self-reference these are the three shapes that become the 503 envelope or a left-out record. The check catches `(ValueError, RecursionError)`: `PydanticSerializationError` is a `ValueError` and `RecursionError` is not (run, M-7); any other exception propagates as the 500 it was.

**D2. A listing that holds one record the writer cannot write** (rows: the five listing routes; the HXI; Python consumers; `count`; reach of one bad record).

| # | Option | The five routes | HXI (read) | Python consumers | `count` and ranking | One bad record |
|---|---|---|---|---|---|---|
| **1** | **Leave the record out and log its path, never a value; list the rest (chosen)** | 200; the body equals that of a store without the record (the search: the same paths and `count`; its scores are the search's) (run) | the panel lists the rest, the author's count one lower; Knowledge Browser lists the rest | none: they call `list_entries`; no route | `count` is the records returned; the search can return 19 | the record is missing from the listing, logged at WARNING on every request; its read answers 503 |
| 2 | Fail the whole listing with `records.read_failed` 503 (run, M-1; **the ranked overrule option**) | 503 on all five | any non-OK is empty, so every author vanishes; Knowledge Browser shows `unavailable`, retries twice, stops | none | none | every record is hidden behind one, and a note any client can write through `POST /api/records/notebooks/{callsign}` (`tags` nested 100 levels: the route answers 200 and writes it) keeps the documents, notebook, browse and search listings at 503 for every reader (run, M-9) |
| 3 | List the record without its frontmatter | not built, not run | `d.frontmatter \|\| {}` (`useStore.ts:1971`) copes; unknown clients are not known to | none | `count` includes it | visible, but a new item shape for every client |

Rank 1 > 2 > 3. `list_entries` already skips a record it cannot read (`records_store.py:1463`, `:1508-1509`), so option 1 extends the listing's own rule to one more reason, and slice 2's D6 took the same side (one bad record must not abort a listing). **Decided by the Architect: none of the six conditions under which the Captain decides in Delegated AD Execution Mode is met.** The routes below are the five listings and the graph; the read route returns one record and leaves nothing out. Cells marked (read) are from source, not run; the others are from the hand driver (M-1, M-3, M-9).

| Condition | Met | Why |
|---|---|---|
| 1. An irreversible or destructive production-data operation | no | The change is on the read path: no file, git object or index is written, and reverting `routers/records.py` undoes it. |
| 2. Weakening a security, privacy, consensus, authorization, audit or safety control | no | The read route's classification gate runs before the check; the listings are not reader-scoped and the search reads as the Captain (`records.py:187`), so an omission only removes and discloses nothing. The audit trail here is git (`records_store.py:616-619`; `GET /history/{path}` is `git log --follow -- path`, `:1526-1541`) and the store's own callers (`stand_down.py:281` and `archive_promotion.py:310` read `list_entries(..., strict=True)`) (read); the router touches none of them, and after a note written through `POST /api/records/notebooks/{callsign}` with `tags` nested 100 levels `list_entries()` and `list_entries("notebooks", strict=True)` still hold it. Per route: documents, browse and notebook are views; the search is a ranked sample capped at 20 that already withholds records it cannot read (read); the captain's log can only be made unwritable by a hand edit (`append_captains_log` writes four `str` frontmatter values and appends body text, `:883-916`) (read); the graph leaves nothing out (a node label the writer cannot write fails the whole graph with its own envelope). The base already omits a record the reader cannot parse, with no signal in the body (the 600-level row of M-1; T3), and a WARNING that names a path is the module's own practice for a listing that skips a record (`:1496`) (read). Against the base the policy removes a weakness: that note (the route answers 200) makes the documents, notebook, browse and search listings answer 500 to every reader on the base and 503 under option 2, and 200 without that one note under option 1, whose read of the note answers 503 `records.read_failed` (M-9). |
| 3. Breaking a public API, a persisted schema, a federation protocol or a compatibility promise | no | No key is added, removed or retyped. `count` is the number of items returned: the HXI's browse validator requires `count === documents.length` (`useStore.ts:116-118`) (read) and T8 compares whole bodies. Every ordinary body is byte-identical (M-3). The one status that changes is a listing that was an unhandled 500, which is now 200 without the record; no document promises a complete listing (section 11, Absence Verified) and `list_entries` documents the skip (`:1463`); AD-1145 DD-7's byte-identity is for the read route's body and holds. |
| 4. New spending, a paid or incompatible dependency, a secret or credential, access to a live production system | no | `pydantic` is already a dependency (`pyproject.toml:25`); the census is a separate step on a copy. |
| 5. Moving information or implementation across the OSS/commercial boundary | no | One OSS router module. |
| 6. Accepting unresolved Critical/High risk, or changing the product objective beyond the issue | no | The risk is Low: no production caller passes such a value (slice 2's callers table), the omission is logged by path and answered by the record's own 503, and the census counts the records. The objective is F7-1's own: a record the reader parsed answers 500. |

**Overrule option (ranked 2): fail the whole listing.** Effect (M-1, M-9): every listing that holds such a record answers `records.read_failed` 503 and so hides all its records (all five in M-1; four of the five for a note under `notebooks/` in M-9), the Notebooks panel shows nothing and Knowledge Browser `unavailable`, and any client that can write a note keeps them down; nothing is left out silently. Switching is the body of `_writable` (a whole-body check that answers the 503) and, in the new test file, the expected answers of 22 cases (T8's 20, T9 and T10: 21 of 43 pass against the fail-whole variant) and mutation rows 4 to 10 and 12.

**D3. The failure envelope and its log.** Rows: (1) the existing 503 `records.read_failed`, message "Record document unavailable" (chosen); (2) a new code with a 500 `failed`; (3) a log line that carries the exception. (1): the same envelope the reader's own `RecursionError` already gets (run: the 600-level row), so one family of record has one answer at 100, 450 and 600 levels; Knowledge Browser reads its `state` (`unavailable`), not its `code`. `retryable` is true for a defect that does not heal; it is true for the 600-level record already (`routers/readiness.py:57-63`). (2) is truer and splits one family across two answers that no client reads. (3) is rejected: the exception's text was not examined for whether it can echo a value. The read route's log line is static, ends `returning HTTP 503` as its neighbours do and names no path (a client supplied it) and no exception (`exc_info` is absent from its siblings; `test_issue1368_readiness.py:165, :189, :276` assert a secret is not in the log). A listing's log line names the paths the store's walk produced (at most five, with `%r`) and a count; the graph's names neither. Never a value: AD-1140's rule for a refused value (`utils/frontmatter.py:78`).

## 4. Milestones and gates

| M | Blocks | Gate |
|---|---|---|
| M1 | N1-1 | G1 |
| M2 | P2-1 to P2-10, then N2-1 (the marker) | G2 |
| M3 | P3-1, P3-2, ledger | G3 |

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. **M0:** on the head, record the collected count (`--collect-only -q`) of every existing file G2 names, and the four counts of `PY -P scripts/check_architecture_principles.py --check`.

- **G1.** `PY -m pytest tests/test_bf940_s3_route_serialisation.py -q -n 0 -p no:randomly`. **Expected:** 43 cases, **15 passed, 28 xfailed**. The marker carries `raises=AssertionError, strict=True`: any other exception, or an XPASS, is a FAIL. Then once with `--runxfail`: each failure must stop at the `assert` section 6 names, never at a premise line.
- **G2.** (1) `$f = git grep -l -E 'routers\.records|/api/records|\bread_record\b|\bsearch_records\b|\bbrowse_records\b|get_records_graph|get_records_timeline|\bget_backlinks\b|\blist_records\b|\bget_captains_log\b|\blist_notebook\b' -- 'tests/test_*.py'` (9 files on the reading tree; M0 records the count of the full list); then `PY -m pytest $f tests/test_bf940_s3_route_serialisation.py tests/test_layer_boundaries.py -q -n 0 -p no:randomly`. (2) `PY -P scripts/check_architecture_principles.py --check`. **Expected:** the new file's 43 passed; every other file 0 failed with collected counts equal to M0; the check clean with its four counts equal to M0's.
- **G3.** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- **Census (not a Builder step).** Run 7.4 on the vessel's copy before the pull request merges; a flagged document goes back to the Architect.
- **Harness rule.** No source change made to pass a test, no skip, no loosened assertion. A failing case of the new file at G2, or any existing test failing, goes back to the Architect. The broad gate runs once, in the main session, with `--receipt`.

## 5. Commit messages

- **M1:** `BF-940 M1 (slice 3): tests for a record the reader parsed being answered by every records route, xfail until built (#1686)`
- **M2:** `BF-940 M2 (slice 3): the records routes ask the JSON writer before they return; a record it cannot write is a 503, is left out of a listing, or is the graph's own envelope (#1686)`
- **M3:** `BF-940 M3 (slice 3): trackers and ledger (#1686)`; its body ends with the line `Refs #1686.`

## 6. Tests

`tests/test_bf940_s3_route_serialisation.py` (M1; the functions pass on both trees, the class is strict xfail until M2). A case asserts its premise first (the healthy records alone are answered; the reader's own `read_entry` returned the record), so a failure cannot mean the record was never read. `TestClient(raise_server_exceptions=False)` makes the unfixed 500 a response, so each case fails at an `assert`, not at an exception out of `get`.

| Id | Cases | Covers | xfail until |
|---|---|---|---|
| T1 | 1 | Guard: a UTC datetime, a date, a set, UTF-8 bytes, a unicode value under an int key and `nan` are written as before, on the read route and in a listing (`test_a_record_holding_every_shape_the_reader_builds_is_answered_as_it_always_was`) | none |
| T2 | 6 | Guard: 90 levels on the read route and in each listing (`test_a_record_nested_ninety_levels_is_answered_by_every_route`) | none |
| T3 | 1 | Guard: 600 levels: the reader's `RecursionError`, the read route's 503, a listing without the record (`test_a_record_beyond_the_readers_own_limit_keeps_its_answers`) | none |
| T4 | 4 | Guard: `?format=prov-jsonld` of a record the writer cannot write is 200 (`test_the_provenance_projection_of_a_record_the_writer_cannot_write_is_still_answered`) | none |
| T5 | 2 | Guard: the backlinks and the timeline are 200 while such a record exists (`test_a_route_that_holds_no_record_value_answers_while_such_a_record_exists`) | none |
| T6 | 1 | Guard: every route of the module is classified, and the routes that hold a record value are the seven the class drives (`test_every_route_of_the_module_is_classified`) | none |
| T7 | 4 | Class: the read route answers the controlled 503 envelope for a record at 100 levels, at 450, with bytes that are not UTF-8 and holding itself; the log ends `returning HTTP 503` and holds no value (`test_the_read_route_answers_a_record_the_writer_cannot_write_with_the_controlled_503`) | M2 |
| T8 | 20 | Class: each of the five listings with each of the four values: 200, the body equal to that of a store without the record, the left-out path logged, no value logged (`test_a_listing_leaves_out_a_record_the_writer_cannot_write_and_keeps_the_rest`) | M2 |
| T9 | 1 | Class: a record the read route answers and a listing cannot carry (found by scanning depths, never pinned) is left out of the listing only (`test_a_record_the_read_route_can_write_is_left_out_of_a_listing_two_levels_deeper`) | M2 |
| T10 | 1 | Class: the captain's log's limit counts the records it returns (`test_the_captains_log_limit_counts_the_records_it_returns`) | M2 |
| T11 | 2 | Class: a graph whose node label cannot be written answers its own 500 envelope, as JSON (`test_the_graph_answers_a_record_whose_topic_the_writer_cannot_write_with_its_own_envelope`) | M2 |

**How each xfail case fails on the unfixed tree** (hand driver, reading tree): T7 at `assert response.status_code == 503` (it is 500); T8 at `assert response.status_code == 200`; T9 at the same assert on the listing, after the premise that the read route answers the record; T10 at `assert response.status_code == 200`; T11 at `assert response.headers["content-type"].startswith("application/json")` (a plain-text 500). **Guards that pass on both trees:** T1 to T6. A source-scan caveat: the only scan here is T6, which reads `router.routes`, a runtime object; it cannot see a handler a route table does not hold.

## 7. The contract

### 7.1 M1

**N1-1.** New file `tests/test_bf940_s3_route_serialisation.py`:
```python
"""BF-940 slice 3 (#1686, F7-1): a record the reader parsed is a record the Ship's Records routes can answer.

FastAPI writes what a handler returns as JSON after the handler has returned, outside the handler's own error boundary. A record the
reader parsed but the JSON writer cannot write (a mapping nested about 100 levels deep, bytes that are not UTF-8, a value that holds
itself) was therefore an unhandled HTTP 500 on the read route and on every route that returns a frontmatter. Real ``RecordsStore``
over ``tmp_path`` with ``~`` moved, hand-made records, the real router through ``TestClient(raise_server_exceptions=False)`` (so the
500 is a response a test can assert on, not an exception out of ``get``), no network.

The class is strict xfail until M2 (each case fails at an ``assert`` of its own body on the unfixed tree, after its premise); the
module's functions are guards and pass on both trees. A case asserts its premise first: the healthy records alone are answered, and
the reader itself parsed the record (``read_entry`` returns it), so a failure cannot mean the record was never read. The inventory
test reads the router object, not its source.
"""

from __future__ import annotations

import datetime
import logging
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from probos.config import RecordsConfig, SystemConfig
from probos.knowledge.backlinks import KnowledgeBrowserService
from probos.knowledge.records_store import RecordsStore
from probos.routers.records import router

_HEALTHY = "---\nauthor: alice\nclassification: ship\ntopic: healthy\ntags: [coolant]\n---\n\ncoolant healthy body\n"
_NOTE = "notebooks/alice/ok.md"
_LOG = "captains-log/ok.md"
_BAD_NOTE = "notebooks/alice/case.md"
_BAD_LOG = "captains-log/case.md"
_MARKER = "VALUE-MARKER-917"
_READ = f"/api/records/documents/{_BAD_NOTE}"
_LISTINGS = [
    pytest.param("/api/records/documents", id="documents"),
    pytest.param("/api/records/notebooks/alice", id="notebook"),
    pytest.param("/api/records/captains-log", id="captains-log"),
    pytest.param("/api/records/browse", id="browse"),
    pytest.param("/api/records/search?q=coolant", id="search"),
]
# (the YAML value of one key, a text that must never reach a log line)
_UNWRITABLE = [
    pytest.param("{a: " * 100 + _MARKER + "}" * 100, _MARKER, id="nested-100"),
    pytest.param("{a: " * 450 + _MARKER + "}" * 450, _MARKER, id="nested-450"),
    pytest.param("!!binary //4=", "xff", id="bytes-not-utf-8"),
    pytest.param("&a [*a]", "[...]", id="holds-itself"),
]
_SHAPES = (
    "---\nauthor: alice\nclassification: ship\nwhen: 2026-11-09T01:02:03Z\nday: 2026-11-09\nkinds: !!set {p: null}\nraw: !!binary aGk=\n"
    "1: \u00e9\nnot_a_number: .nan\ntags: [coolant]\n---\n\ncoolant shapes body\n"
)
_SHAPES_JSON = {
    "author": "alice", "classification": "ship", "when": "2026-11-09T01:02:03Z", "day": "2026-11-09", "kinds": ["p"], "raw": "hi",
    "1": "\u00e9", "not_a_number": None, "tags": ["coolant"],
}
_ROUTES = {
    ("GET", "/api/records/stats"): "holds no record value",
    ("GET", "/api/records/documents"): "holds a record value",
    ("GET", "/api/records/documents/{path:path}"): "holds a record value",
    ("POST", "/api/records/captains-log"): "holds no record value",
    ("GET", "/api/records/captains-log"): "holds a record value",
    ("GET", "/api/records/notebooks/{callsign}"): "holds a record value",
    ("POST", "/api/records/notebooks/{callsign}"): "holds no record value",
    ("GET", "/api/records/search"): "holds a record value",
    ("GET", "/api/records/history/{path:path}"): "holds no record value",
    ("GET", "/api/records/browse"): "holds a record value",
    ("GET", "/api/records/backlinks/{path:path}"): "holds no record value",
    ("GET", "/api/records/graph"): "holds a record value",
    ("GET", "/api/records/timeline"): "holds no record value",
}
_DRIVEN = {
    ("GET", "/api/records/documents"), ("GET", "/api/records/documents/{path:path}"), ("GET", "/api/records/captains-log"),
    ("GET", "/api/records/notebooks/{callsign}"), ("GET", "/api/records/search"), ("GET", "/api/records/browse"),
    ("GET", "/api/records/graph"),
}


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert Path.home() == home, "premise: ~ is the temporary home"


def _nested(depth: int) -> str:
    return "{a: " * depth + "1" + "}" * depth


def _record(key: str, value: str) -> str:
    return f"---\nauthor: alice\nclassification: ship\n{key}: {value}\ntags: [coolant]\n---\n\ncoolant case body\n"


def _make_store(root: Path, files: dict[str, str]) -> RecordsStore:
    repo = root / "ship-records"
    repo.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    return RecordsStore(RecordsConfig(repo_path=str(repo), auto_commit=False))


def _get(store: RecordsStore, url: str) -> Any:
    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        config=SystemConfig(), records_store=store, _records_store=store, knowledge_browser=KnowledgeBrowserService(store),
    )
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        return client.get(url)


def _items(response: Any) -> list[dict[str, Any]]:
    body = response.json()
    return next(body[key] for key in ("documents", "entries", "results") if key in body)


def _shape(url: str, body: dict[str, Any]) -> Any:
    """What must not change when a record is left out of a listing: all of the body, but for the search's scores, which count the whole corpus."""
    if url.startswith("/api/records/search"):
        return {"paths": [hit["path"] for hit in body["results"]], "count": body["count"]}
    return body


async def test_a_record_holding_every_shape_the_reader_builds_is_answered_as_it_always_was(tmp_path):
    """Guard (passes on every tree): a UTC datetime, a date, a set, UTF-8 bytes, a unicode value under an int key and ``nan`` are written as they were."""
    path = "notebooks/alice/shapes.md"
    store = _make_store(tmp_path, {path: _SHAPES})
    frontmatter = (await store.read_entry(path, reader_id="captain"))["frontmatter"]
    assert type(frontmatter["when"]) is datetime.datetime and frontmatter["when"].tzinfo is not None
    assert type(frontmatter["day"]) is datetime.date and frontmatter["kinds"] == {"p"} and frontmatter["raw"] == b"hi"
    assert frontmatter[1] == "\u00e9" and math.isnan(frontmatter["not_a_number"]), "premise: the reader builds each shape"
    read = _get(store, f"/api/records/documents/{path}")
    assert read.status_code == 200 and read.json()["frontmatter"] == _SHAPES_JSON
    listing = _get(store, "/api/records/documents")
    assert listing.status_code == 200 and listing.json()["documents"][0]["frontmatter"] == _SHAPES_JSON


@pytest.mark.parametrize("url", [pytest.param(_READ, id="read"), *_LISTINGS])
async def test_a_record_nested_ninety_levels_is_answered_by_every_route(tmp_path, url):
    """Guard: ninety levels is below the depth at which the writer stops, on the read route and in a listing."""
    store = _make_store(tmp_path, {_NOTE: _HEALTHY, _LOG: _HEALTHY, _BAD_NOTE: _record("meta", _nested(90)), _BAD_LOG: _record("meta", _nested(90))})
    assert await store.read_entry(_BAD_NOTE, reader_id="captain") is not None, "premise: the reader parsed the record"
    response = _get(store, url)
    assert response.status_code == 200 and "case.md" in response.text


async def test_a_record_beyond_the_readers_own_limit_keeps_its_answers(tmp_path):
    """Guard: the reader raises ``RecursionError`` for 600 levels, the read route answers its 503 and a listing leaves the record out, as before."""
    store = _make_store(tmp_path, {_NOTE: _HEALTHY, _BAD_NOTE: _record("meta", _nested(600))})
    with pytest.raises(RecursionError):
        await store.read_entry(_BAD_NOTE, reader_id="captain")
    read = _get(store, _READ)
    assert read.status_code == 503 and read.json()["availability"]["code"] == "records.read_failed"
    listing = _get(store, "/api/records/documents")
    assert listing.status_code == 200 and [item["path"] for item in _items(listing)] == [_NOTE]


@pytest.mark.parametrize(("value", "marker"), _UNWRITABLE)
async def test_the_provenance_projection_of_a_record_the_writer_cannot_write_is_still_answered(tmp_path, value, marker):
    """Guard: ``?format=prov-jsonld`` holds no value of the record, so it is answered where the record itself is not."""
    store = _make_store(tmp_path, {_BAD_NOTE: _record("meta", value)})
    assert await store.read_entry(_BAD_NOTE, reader_id="captain") is not None, "premise: the reader parsed the record"
    response = _get(store, f"{_READ}?format=prov-jsonld")
    assert response.status_code == 200 and set(response.json()) == {"@context", "@graph"}


@pytest.mark.parametrize("url", ["/api/records/backlinks/notebooks/alice/case.md", "/api/records/timeline"])
async def test_a_route_that_holds_no_record_value_answers_while_such_a_record_exists(tmp_path, url):
    """Guard: the backlinks and the timeline hold only text and counts, so a record the writer cannot write does not reach their bodies."""
    store = _make_store(tmp_path, {_NOTE: _HEALTHY, _BAD_NOTE: _record("topic", _nested(450))})
    assert await store.read_entry(_BAD_NOTE, reader_id="captain") is not None, "premise: the reader parsed the record"
    assert _get(store, url).status_code == 200


def test_every_route_of_the_module_is_classified():
    """Guard: a route added to ``routers/records.py`` fails here until it is classified, and a route that holds a record value must be driven by the class below."""
    found = {(method, route.path) for route in router.routes for method in route.methods}
    assert found == set(_ROUTES), "a route was added, moved or renamed: classify it in _ROUTES (does its body hold a record value?)"
    assert {key for key, kind in _ROUTES.items() if kind == "holds a record value"} == _DRIVEN, "a route that holds a record value is not driven by the class below"


@pytest.mark.xfail(reason="BF-940 slice 3 M2: not built", raises=AssertionError, strict=True)
class TestARecordTheReaderParsedIsAnsweredByEveryRoute:
    @pytest.mark.parametrize(("value", "marker"), _UNWRITABLE)
    async def test_the_read_route_answers_a_record_the_writer_cannot_write_with_the_controlled_503(self, tmp_path, caplog, value, marker):
        store = _make_store(tmp_path, {_NOTE: _HEALTHY, _BAD_NOTE: _record("meta", value)})
        assert await store.read_entry(_BAD_NOTE, reader_id="captain") is not None, "premise: the reader parsed the record"
        assert _get(store, f"/api/records/documents/{_NOTE}").status_code == 200, "premise: a healthy record is answered"
        with caplog.at_level(logging.WARNING, logger="probos.routers.records"):
            response = _get(store, _READ)
        assert response.status_code == 503
        assert response.json() == {
            "error": "Record document unavailable",
            "availability": {"state": "unavailable", "code": "records.read_failed", "message": "Record document unavailable", "retryable": True},
        }
        assert "returning HTTP 503" in caplog.text and marker not in caplog.text and marker not in response.text

    @pytest.mark.parametrize("url", _LISTINGS)
    @pytest.mark.parametrize(("value", "marker"), _UNWRITABLE)
    async def test_a_listing_leaves_out_a_record_the_writer_cannot_write_and_keeps_the_rest(self, tmp_path, caplog, url, value, marker):
        healthy = {_NOTE: _HEALTHY, _LOG: _HEALTHY}
        reference = _get(_make_store(tmp_path / "healthy", healthy), url)
        assert reference.status_code == 200 and _items(reference), "premise: the healthy records alone are listed"
        store = _make_store(tmp_path / "both", {**healthy, _BAD_NOTE: _record("meta", value), _BAD_LOG: _record("meta", value)})
        assert await store.read_entry(_BAD_NOTE, reader_id="captain") is not None, "premise: the reader parsed the record"
        with caplog.at_level(logging.WARNING, logger="probos.routers.records"):
            response = _get(store, url)
        assert response.status_code == 200
        assert _shape(url, response.json()) == _shape(url, reference.json())
        assert "left out of the listing" in caplog.text and "case.md" in caplog.text and marker not in caplog.text

    async def test_a_record_the_read_route_can_write_is_left_out_of_a_listing_two_levels_deeper(self, tmp_path):
        """A listing nests a record two levels below the body's top, so the writer stops two levels sooner there than on the read route."""
        adapter = TypeAdapter(Any)

        def writes(body: Any) -> bool:
            try:
                adapter.dump_json(body)
            except ValueError:  # PydanticSerializationError is a ValueError
                return False
            return True

        store = _make_store(tmp_path, {_NOTE: _HEALTHY})
        found = None
        for depth in range(60, 140):
            (store.repo_path / _BAD_NOTE).write_text(_record("meta", _nested(depth)), encoding="utf-8")
            entry = await store.read_entry(_BAD_NOTE, reader_id="captain")
            if not writes({"documents": [{"path": _BAD_NOTE, "frontmatter": entry["frontmatter"]}]}):
                found = depth
                break
        assert found is not None and writes(entry), "premise: a depth at which the read route's body still writes and a listing's does not"
        assert _get(store, _READ).status_code == 200, "premise: the read route answers the record"
        response = _get(store, "/api/records/documents")
        assert response.status_code == 200
        assert [item["path"] for item in _items(response)] == [_NOTE]

    async def test_the_captains_log_limit_counts_the_records_it_returns(self, tmp_path):
        def entry(created: str, extra: str = "") -> str:
            return f"---\nauthor: captain\nclassification: ship\ncreated: '{created}'\n{extra}---\n\nentry body\n"

        store = _make_store(tmp_path, {
            "captains-log/a.md": entry("2026-01-01"), "captains-log/b.md": entry("2026-02-01"),
            "captains-log/c.md": entry("2026-03-01", f"meta: {_nested(450)}\n"),
        })
        healthy = _make_store(tmp_path / "healthy", {"captains-log/a.md": entry("2026-01-01"), "captains-log/b.md": entry("2026-02-01")})
        assert [item["path"] for item in _items(_get(healthy, "/api/records/captains-log?limit=1"))] == ["captains-log/b.md"], "premise: b is the newest healthy entry"
        assert await store.read_entry("captains-log/c.md", reader_id="captain") is not None, "premise: the reader parsed the newest entry"
        response = _get(store, "/api/records/captains-log?limit=1")
        assert response.status_code == 200
        assert [item["path"] for item in _items(response)] == ["captains-log/b.md"]

    @pytest.mark.parametrize(("value", "marker"), [_UNWRITABLE[1], _UNWRITABLE[2]])
    async def test_the_graph_answers_a_record_whose_topic_the_writer_cannot_write_with_its_own_envelope(self, tmp_path, caplog, value, marker):
        assert _get(_make_store(tmp_path / "healthy", {_NOTE: _HEALTHY}), "/api/records/graph").status_code == 200, "premise: the healthy graph is answered"
        store = _make_store(tmp_path / "both", {_NOTE: _HEALTHY, _BAD_NOTE: _record("topic", value)})
        entry = await store.read_entry(_BAD_NOTE, reader_id="captain")
        assert entry is not None and "topic" in entry["frontmatter"], "premise: the reader parsed the record"
        with caplog.at_level(logging.WARNING, logger="probos.routers.records"):
            response = _get(store, "/api/records/graph")
        assert response.headers["content-type"].startswith("application/json")
        assert response.status_code == 500
        assert response.json() == {
            "error": "graph assembly failed",
            "availability": {"state": "failed", "code": "knowledge_browser.graph_failed", "message": "graph assembly failed", "retryable": True},
        }
        assert "returning HTTP 500" in caplog.text and marker not in caplog.text
```

### 7.2 M2

**P2-1.** `src/probos/routers/records.py`, the imports (once):
SEARCH:
```
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from probos.knowledge.provo import project_record_frontmatter
```
REPLACE:
```
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter

from probos.knowledge.provo import project_record_frontmatter
```

**P2-2.** `src/probos/routers/records.py`, the check and the listing filter, after `_read_failure` (once):
SEARCH:
```
def _read_failure(message: str, code: str, status_code: int = 500) -> JSONResponse:
    return JSONResponse(
        {"error": message, "availability": failed_read(message, code, status_code)},
        status_code=status_code,
    )
```
REPLACE:
```
def _read_failure(message: str, code: str, status_code: int = 500) -> JSONResponse:
    return JSONResponse(
        {"error": message, "availability": failed_read(message, code, status_code)},
        status_code=status_code,
    )


# BF-940 slice 3 (#1686, F7-1): FastAPI writes what a handler returns as JSON after the handler has returned, outside the handler's
# own error boundary, so a record the reader parsed but the writer cannot write (a mapping nested too deeply, bytes that are not
# UTF-8, a value that holds itself) was an unhandled HTTP 500. ``TypeAdapter(Any).dump_json`` is the call FastAPI 0.136.1 makes for a
# handler annotated ``-> Any``; asking it here, before the handler returns, says whether the response can be written. What it writes
# is discarded: a handler still returns its own body, so a body the writer could write is sent exactly as it was sent before.
_JSON_WRITER = TypeAdapter(Any)


def _writes(body: Any) -> bool:
    """Whether the JSON writer can write ``body``; ``PydanticSerializationError`` is a ``ValueError``."""
    try:
        _JSON_WRITER.dump_json(body)
    except (ValueError, RecursionError):
        return False
    return True


def _writable(records: list[Any], key: str, route: str) -> list[Any]:
    """The records of a listing that the JSON writer can write, in order; the others are left out and logged by path, never by value.

    A listing's body holds a record two levels below its top (``{key: [record]}``), so each record is tried at that depth: the writer
    stops at a depth, and a record the read route can write is left out here when the body around it is two levels deeper.
    """
    if _writes({key: records}):
        return records
    kept: list[Any] = []
    left_out: list[Any] = []
    for record in records:
        if _writes({key: [record]}):
            kept.append(record)
        else:
            left_out.append(record)
    logger.warning(
        "%s: %d record(s) the JSON writer cannot write are left out of the listing; paths=%r; returning the rest",
        route, len(left_out), [record.get("path") for record in left_out[:5]],
    )
    return kept
```

**P2-3.** `src/probos/routers/records.py`, `read_record`'s docstring (once):
SEARCH:
```
    Read failures retain ``error`` and add ``availability`` with state, code,
    controlled message and retryable. Missing documents remain HTTP 404;
    absent storage is HTTP 503, with disabled reserved for typed config-off.
    """
```
REPLACE:
```
    Read failures retain ``error`` and add ``availability`` with state, code,
    controlled message and retryable. Missing documents remain HTTP 404;
    absent storage is HTTP 503, with disabled reserved for typed config-off.

    BF-940 slice 3 (#1686, F7-1): FastAPI writes the returned document after this
    function has returned, so a record the reader parsed but the JSON writer cannot
    write is answered here, as HTTP 503 ``records.read_failed``, not as an unhandled
    500. The projection holds no value of the record and is not affected.
    """
```

**P2-4.** `src/probos/routers/records.py`, the end of `read_record` (once):
SEARCH:
```
    if format == _PROV_JSONLD_FORMAT:
        return project_record_frontmatter(
            entry.get("path") or path, entry.get("frontmatter") or {}
        )
    return entry
```
REPLACE:
```
    if format == _PROV_JSONLD_FORMAT:
        return project_record_frontmatter(
            entry.get("path") or path, entry.get("frontmatter") or {}
        )
    if not _writes(entry):  # BF-940 slice 3 (F7-1): the body is written after this returns; a record the writer cannot write is answered here
        logger.warning("Records document serialisation failed; document unavailable; returning HTTP 503")
        return _read_failure("Record document unavailable", "records.read_failed", 503)
    return entry
```

**P2-5.** `src/probos/routers/records.py`, `list_records` (once):
SEARCH:
```
    return {"documents": entries, "count": len(entries)}
```
REPLACE:
```
    entries = _writable(entries, "documents", "Records listing")  # BF-940 slice 3 (F7-1)
    return {"documents": entries, "count": len(entries)}
```

**P2-6.** `src/probos/routers/records.py`, `get_captains_log` (once):
SEARCH:
```
    entries = await runtime._records_store.list_entries("captains-log")
    entries.sort(key=lambda e: e.get("frontmatter", {}).get("created", ""), reverse=True)
```
REPLACE:
```
    entries = await runtime._records_store.list_entries("captains-log")
    entries = _writable(entries, "entries", "Captain's log")  # BF-940 slice 3 (F7-1): before the limit, so the limit counts records it returns
    entries.sort(key=lambda e: e.get("frontmatter", {}).get("created", ""), reverse=True)
```

**P2-7.** `src/probos/routers/records.py`, `list_notebook` (once):
SEARCH:
```
    return {"callsign": callsign, "entries": entries}
```
REPLACE:
```
    entries = _writable(entries, "entries", "Notebook listing")  # BF-940 slice 3 (F7-1)
    return {"callsign": callsign, "entries": entries}
```

**P2-8.** `src/probos/routers/records.py`, `search_records` (once):
SEARCH:
```
    return {"query": q, "results": results, "count": len(results)}
```
REPLACE:
```
    results = _writable(results, "results", "Records search")  # BF-940 slice 3 (F7-1)
    return {"query": q, "results": results, "count": len(results)}
```

**P2-9.** `src/probos/routers/records.py`, `browse_records` (once):
SEARCH:
```
        filtered.append(e)
    return {
        "documents": filtered,
```
REPLACE:
```
        filtered.append(e)
    filtered = _writable(filtered, "documents", "Records browse")  # BF-940 slice 3 (F7-1)
    return {
        "documents": filtered,
```

**P2-10.** `src/probos/routers/records.py`, `get_records_graph` (the three lines occur once; the other two `return result` blocks name other failures):
SEARCH:
```
    if result is None:
        return _read_failure("graph assembly failed", "knowledge_browser.graph_failed")
    return result
```
REPLACE:
```
    if result is None:
        return _read_failure("graph assembly failed", "knowledge_browser.graph_failed")
    if not _writes(result):  # BF-940 slice 3 (F7-1): a node's label is a frontmatter value, written after this returns
        logger.warning("Knowledge Browser graph cannot be written as JSON; results unavailable; returning HTTP 500")
        return _read_failure("graph assembly failed", "knowledge_browser.graph_failed")
    return result
```

**N2-1.** `tests/test_bf940_s3_route_serialisation.py`, remove the marker of N1-1 (the SEARCH occurs once; the class line stays):
SEARCH:
```
@pytest.mark.xfail(reason="BF-940 slice 3 M2: not built", raises=AssertionError, strict=True)
class TestARecordTheReaderParsedIsAnsweredByEveryRoute:
```
REPLACE:
```
class TestARecordTheReaderParsedIsAnsweredByEveryRoute:
```

### 7.3 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once). Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-940 (DATE), #1686 -- a record the reader parsed is a record the Ship's Records routes can answer: the read route and every route that returns a frontmatter ask the JSON writer before they return (slice 3 of the issue).**
- **Base.** FastAPI writes what a handler returns as JSON after the handler has returned, outside its `try`, so a record the reader parsed but the writer cannot write (a mapping nested 97 or more levels deep on the locked FastAPI and pydantic, bytes that are not UTF-8, a value that holds itself) was an unhandled HTTP 500 on `GET /api/records/documents/{path}` and on every route that returns a frontmatter: the documents, notebook and captain's-log listings, the browse, the search (a listing fails two levels sooner, from 95) and the graph, through a node's label. One such record, made by hand or by `write_notebook(metrics=...)`, took every listing down.
- **Fix.** `routers/records.py` asks the writer FastAPI itself calls (`TypeAdapter(Any).dump_json`) whether it can write the body, before the handler returns, and returns its own body when it can: every answered body is byte-identical to before. The read route answers a record it cannot write with the existing 503 `records.read_failed`; a listing leaves that record out, logs its path (never a value) and lists the rest; the graph answers its own `graph_failed` envelope. `?format=prov-jsonld`, the backlinks and the timeline hold no record value and are unchanged. Contract `prompts/bf-940-records-route-serialisation.md`. Refs #1686: this closes its F7-1 box; the issue stays open for L19, the last box.

```

**P3-2.** `DECISIONS.md`. Append after slice 2's entry. Its last bullet occurs once. Replace `DATE` with M3's date.
SEARCH:
```
- *Residual.* L1 to L14 of the contract. *Reversal.* Revert the BF-940 slice 2 commits.
```
REPLACE:
```
- *Residual.* L1 to L14 of the contract. *Reversal.* Revert the BF-940 slice 2 commits.

### BF-940 -- A record the reader parsed is a record the routes can answer (slice 3; DATE, #1686)

- *Scope.* `routers/records.py` (one check of the JSON writer, used by the seven handlers whose body holds a record value), tests. Contract `prompts/bf-940-records-route-serialisation.md`. Slice 3 of #1686.
- *G0 (scope).* The read route and every other handler of the module whose body holds a frontmatter (found by a run: the documents, notebook and captain's-log listings, the browse, the search and the graph); L19, the last box, stays in #1686, which stays open (`Refs`). Rejected: the read route alone; the read route and three listings (the browse, the search and the graph share the defect); an application-wide handler (it changes the failure of every route and cannot name a route's own envelope).
- *G1 (the mechanism).* Ask `TypeAdapter(Any).dump_json`, the call FastAPI 0.136.1 makes for a `-> Any` handler, before the handler returns, and return the handler's own body. This replaces slice 2's G3 (`dump_python(mode="json")`, returning its result): returning a converted object fails two AD-1145 tests, which assert the handler returns the store's entry itself, and `jsonable_encoder` writes a UTC datetime as `+00:00` and refuses `nan`.
- *G2 (a listing).* A record the writer cannot write is left out and logged by path, never by value; the rest is listed, as `list_entries` already skips a record it cannot read. Decided by the Architect: none of the six conditions under which the Captain decides is met (nothing stored changes, no control is weakened, no key or client contract changes, nothing is spent or moved, the risk is Low). Ranked below: failing the whole listing with the 503 (one record hides every other, and a note any client can write keeps the listings down), the ranked overrule option; listing the record without its frontmatter (a new item shape). Considered and not taken: an additive `skipped` field.
- *G3 (the envelope).* The existing `records.read_failed` 503 and its message, no new code; the graph keeps `knowledge_browser.graph_failed`.
- *Residual.* L1 to L12 of the contract. *Reversal.* Revert the BF-940 slice 3 commits.
```

**Ledger.** Run G3. The roadmap Bug Tracker and the documents are not edited (no document states these routes' failure behaviour: `git grep -n -F "records.read_failed" -- docs` finds nothing).

### 7.4 The census (an orchestrator step; no repository file)

I have no live system. Run on a read-only copy of the vessel's `ship-records` (the path from the live process, `%LOCALAPPDATA%\ProbOS\data`, never `d:\ProbOS\data`), with the build tree first on `PYTHONPATH`: `$env:PYTHONPATH = '<build tree>\src'; PY -B -P census_bf940_s3.py <copy>`. It lists documents as the routes do (`RecordsStore.list_entries`), reads each as the read route does (`read_entry` as the Captain), asks the JSON writer FastAPI uses (`TypeAdapter(Any).dump_json`) whether it can write the read route's body and a listing's body, and also counts the structural reasons (more than 90 levels with the frontmatter as level 1, bytes that are not UTF-8, a container that holds itself) so the two comparisons can be read against each other. A document the reader could not parse is not listed and not counted. It prints paths, flag names, counts and the FastAPI and pydantic versions, **never a value**; the constructor of the store writes nothing and `initialize()` is never called. Exit 0: nothing flagged. 1: flags (read each; `READ_500` is a record the read route answered with an unhandled 500 before this slice, `LISTING_500` one that took every listing down). 2: the positive control was not flagged, or bad arguments (do not trust the run). The positive control is five documents in a temporary folder walked by the same `census` function: a 120-level nesting, non-UTF-8 bytes and a self-referencing list, which must be flagged as named, and a 60-level nesting and a plain document, which must not. Run on synthetic trees here: a clean tree exits 0; a tree holding a 120-level, a bytes, a 96-level and a 92-level record exits 1 and flags the first two with both writer flags, the 96-level one with `LISTING_500` only and the 92-level one by `DEEP` alone (a structural proxy the writer does not confirm); a missing folder exits 2; the tree is left as found. The results of a run on a vessel's data are not recorded in this repository.

```python
"""BF-940 slice 3 census (an orchestrator step; not a repository file). Read-only: it opens the records for reading and never writes (its positive control uses its own temporary folder).

usage:  $env:PYTHONPATH = "<build tree>/src"; python -B -P census_bf940_s3.py <read-only copy of ship-records>
exit 0 nothing flagged; 1 flags (read each); 2 the positive control was not flagged, or bad arguments. Prints paths, flag names and counts; never a value.
Flags: READ_500 / LISTING_500 (the JSON writer FastAPI uses cannot write the read route's body / a listing's body), DEEP (more than 90 levels, the frontmatter counting as 1), BYTES_NOT_UTF8, SELF_REFERENCE.
"""
from __future__ import annotations

import asyncio
import collections
import pathlib
import sys
import tempfile
from typing import Any

import fastapi
import pydantic
from pydantic import TypeAdapter

from probos.config import RecordsConfig
from probos.knowledge.records_store import RecordsStore

WRITER = TypeAdapter(Any)
DEEP = 90
CONTAINERS = (dict, list, tuple, set, frozenset)


def writes(body: Any) -> bool:
    try:
        WRITER.dump_json(body)
    except (ValueError, RecursionError):
        return False
    return True


def shape(value: Any) -> tuple[int, bool, bool]:
    """(deepest nesting, a bytes value that does not decode, a container that holds itself): one iterative walk, each container entered once."""
    deepest, bad_bytes, cyclic = 0, False, False
    on_path: set[int] = set()
    done: set[int] = set()
    stack: list[tuple[Any, int, bool]] = [(value, 1, False)]
    while stack:
        node, depth, leaving = stack.pop()
        if leaving:
            on_path.discard(id(node))
            done.add(id(node))
            continue
        deepest = max(deepest, depth)
        if isinstance(node, bytes):
            try:
                node.decode("utf-8")
            except UnicodeDecodeError:
                bad_bytes = True
        if isinstance(node, CONTAINERS):
            if id(node) in on_path:
                cyclic = True
                continue
            if id(node) in done:
                continue
            on_path.add(id(node))
            stack.append((node, depth, True))
            children = [*node.keys(), *node.values()] if isinstance(node, dict) else list(node)
            stack.extend((child, depth + 1, False) for child in children)
    return deepest, bad_bytes, cyclic


async def census(root: pathlib.Path) -> tuple[int, list[tuple[str, list[str]]], collections.Counter]:
    store = RecordsStore(RecordsConfig(repo_path=str(root), auto_commit=False))  # the constructor writes nothing; initialize() is never called
    stats: collections.Counter = collections.Counter()
    rows: list[tuple[str, list[str]]] = []
    listed = await store.list_entries()
    for item in listed:
        path = item["path"]
        try:
            entry = await store.read_entry(path, reader_id="captain")
        except Exception:  # noqa: BLE001 -- counted, not hidden
            stats["listed, but read_entry raised"] += 1
            continue
        if entry is None:
            stats["listed, but read_entry returned nothing"] += 1
            continue
        frontmatter = entry["frontmatter"]
        flags: list[str] = []
        if not writes(entry):
            flags.append("READ_500")
        if not writes({"documents": [{"path": path, "frontmatter": frontmatter}]}):
            flags.append("LISTING_500")
        deepest, bad_bytes, cyclic = shape(frontmatter)
        if deepest > DEEP:
            flags.append("DEEP")
        if bad_bytes:
            flags.append("BYTES_NOT_UTF8")
        if cyclic:
            flags.append("SELF_REFERENCE")
        structural = bool({"DEEP", "BYTES_NOT_UTF8", "SELF_REFERENCE"} & set(flags))
        written = bool({"READ_500", "LISTING_500"} & set(flags))
        stats["flagged by the writer and by a structural flag" if written and structural else
              "flagged by the writer only" if written else
              "flagged by a structural flag only" if structural else "not flagged"] += 1
        if flags:
            rows.append((path, flags))
    return len(listed), rows, stats


CONTROL = {
    "notebooks/alice/deep.md": ("meta: " + "{a: " * 120 + "1" + "}" * 120, {"READ_500", "LISTING_500", "DEEP"}),
    "notebooks/alice/bytes.md": ("meta: !!binary //4=", {"READ_500", "LISTING_500", "BYTES_NOT_UTF8"}),
    "notebooks/alice/selfref.md": ("meta: &a [*a]", {"READ_500", "LISTING_500", "SELF_REFERENCE"}),
    "notebooks/alice/shallow.md": ("meta: " + "{a: " * 60 + "1" + "}" * 60, set()),
    "notebooks/alice/clean.md": ("tags: [a]", set()),
}


def control() -> bool:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        for rel, (line, _) in CONTROL.items():
            target = pathlib.Path(tmp) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"---\nauthor: alice\nclassification: ship\n{line}\n---\n\nbody\n", encoding="utf-8")
        listed, rows, _ = asyncio.run(census(pathlib.Path(tmp)))
    got = {path: set(flags) for path, flags in rows}
    return listed == len(CONTROL) and all(got.get(rel, set()) == expected for rel, (_, expected) in CONTROL.items())


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not pathlib.Path(argv[0]).is_dir():
        print("usage: python census_bf940_s3.py <read-only copy of ship-records>")
        return 2
    if not control():
        print("CONTROL NOT FLAGGED: the comparison cannot be trusted")
        return 2
    print("control: a 120-level nesting, non-UTF-8 bytes and a self-referencing list flagged, a 60-level nesting and a plain document not")
    print(f"fastapi {fastapi.__version__}, pydantic {pydantic.VERSION}")
    listed, rows, stats = asyncio.run(census(pathlib.Path(argv[0])))
    print(f"documents listed by list_entries: {listed}; flagged: {len(rows)}")
    for line in sorted(stats):
        print(f"  {stats[line]:6}  {line}")
    for path, flags in rows:
        print(f"FLAG {path} | {','.join(flags)}")
    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

## 8. What this does NOT change

`read_entry`, `list_entries`, `RecordsStore.search`, `_parse_document`, the classification gate of `read_entry` (it runs before the check), the AD-1145 projection and the `?format=prov-jsonld` branch (the check follows it), every other failure envelope of the module, the two POST routes, stats, history, the backlinks and the timeline, `knowledge/backlinks.py` (the graph's label stays whatever the frontmatter holds), `routers/gaps.py` (L8), the sort in `get_captains_log` (L9), the HXI, config, dependencies (`pydantic` is one: `pyproject.toml:25`), the AD-1344, AD-1346 and BF-892 inventories (no write site is added or moved), and every document on disk.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

All rows are in `src/probos/routers/records.py`. Cases are in `TestARecordTheReaderParsedIsAnsweredByEveryRoute`; ids are as my hand driver forms them (the nearest decorator's id first, as pytest does). `LISTING` = `test_a_listing_leaves_out_a_record_the_writer_cannot_write_and_keeps_the_rest` (20 cases: `<value>-<route>`, values `nested-100`, `nested-450`, `bytes-not-utf-8`, `holds-itself`, routes `documents`, `notebook`, `captains-log`, `browse`, `search`), `READ` = `test_the_read_route_answers_a_record_the_writer_cannot_write_with_the_controlled_503` (4 cases: the four values), `WINDOW` = `test_a_record_the_read_route_can_write_is_left_out_of_a_listing_two_levels_deeper`, `LIMIT` = `test_the_captains_log_limit_counts_the_records_it_returns`, `GRAPH` = `test_the_graph_answers_a_record_whose_topic_the_writer_cannot_write_with_its_own_envelope` (2 cases: `nested-450`, `bytes-not-utf-8`).

| # | M | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| 1 | M2 | `return False` | `return True` | READ (4), LISTING (20), WINDOW, LIMIT, GRAPH (2): the check is inert |
| 2 | M2 | `except (ValueError, RecursionError):` | `except RecursionError:` | READ (4), LISTING (20), WINDOW, LIMIT, GRAPH (2): the writer's `ValueError` escapes the handler |
| 3 | M2 | `if not _writes(entry):  # BF-940 slice 3 (F7-1): the body is written after this returns; a record the writer cannot write is answered here` | `if False:  # BF-940 slice 3 (F7-1): the body is written after this returns; a record the writer cannot write is answered here` | READ (4) |
| 4 | M2 | `if _writes({key: records}):` | `if True:` | LISTING (20), WINDOW, LIMIT |
| 5 | M2 | `if _writes({key: [record]}):` | `if _writes(record):` | WINDOW (the record tried outside the depth it has in the body) |
| 6 | M2 | `entries = _writable(entries, "documents", "Records listing")  # BF-940 slice 3 (F7-1)` | `pass  # BF-940 slice 3 (F7-1)` | LISTING[nested-100-documents, nested-450-documents, bytes-not-utf-8-documents, holds-itself-documents], WINDOW |
| 7 | M2 | `entries = _writable(entries, "entries", "Notebook listing")  # BF-940 slice 3 (F7-1)` | `pass  # BF-940 slice 3 (F7-1)` | LISTING[nested-100-notebook, nested-450-notebook, bytes-not-utf-8-notebook, holds-itself-notebook] |
| 8 | M2 | `entries = _writable(entries, "entries", "Captain's log")  # BF-940 slice 3 (F7-1): before the limit, so the limit counts records it returns` | `pass  # BF-940 slice 3 (F7-1)` | LISTING[nested-100-captains-log, nested-450-captains-log, bytes-not-utf-8-captains-log, holds-itself-captains-log], LIMIT |
| 9 | M2 | `results = _writable(results, "results", "Records search")  # BF-940 slice 3 (F7-1)` | `pass  # BF-940 slice 3 (F7-1)` | LISTING[nested-100-search, nested-450-search, bytes-not-utf-8-search, holds-itself-search] |
| 10 | M2 | `filtered = _writable(filtered, "documents", "Records browse")  # BF-940 slice 3 (F7-1)` | `pass  # BF-940 slice 3 (F7-1)` | LISTING[nested-100-browse, nested-450-browse, bytes-not-utf-8-browse, holds-itself-browse] |
| 11 | M2 | `if not _writes(result):  # BF-940 slice 3 (F7-1): a node's label is a frontmatter value, written after this returns` | `if False:  # BF-940 slice 3 (F7-1): a node's label is a frontmatter value, written after this returns` | GRAPH (2) |
| 12 | M2 | `route, len(left_out), [record.get("path") for record in left_out[:5]],` | `route, len(left_out), left_out[:5],` | LISTING (20): a record's value reaches the log (the marker of each value is in its `repr`) |

**Campaign of record** (my hand driver, in memory, one mutant at a time over the exact files below; not the orchestrator's tool run, and the orchestrator's campaign of record, if it runs one, replaces it): baseline 43 cases pass; each mutant fails exactly the cases its row lists (counts 28, 28, 4, 22, 1, 5, 4, 5, 4, 4, 2, 20 for rows 1 to 12), none outside them; no mutant survived. Files (sha256 of the LF text): `routers/records.py` at M2's head (the ten pairs applied to the base blob) `ef39caed9a1cef0fe5902379fba1a3fca72cdb1750e09041230ef139cf1ef158`; `tests/test_bf940_s3_route_serialisation.py` as N1-1 gives it `8db87db1b3eacdcda0ff6b5d1c13025f0c2784692ef6d18a7600087dda62e6c4` and at M2's head, N2-1 applied, `45e51a4012c1599468dc72dbd7e4251d2fbc1145351a609af84802c44f6e6a8f` (my driver ignores the marker, so the campaign ran with it present: the cases are the same). A Builder whose files match does not repeat the campaign; if `routers/records.py` differs, rerun every row; if the test file differs, rerun the rows whose function changed. Rows 1 and 2 kill the same cases through different lines (the return value and the exception class). Not tabulated, for the cap: `[:5]` to `[:50]` (an equivalent mutant: the tests leave out at most two records) and `return records` to `return list(records)` (equivalent: no test asserts identity of the list).

## 10. Recorded limits

- **L1.** Nothing here is a live-system claim: I have no vessel and read no real `ship-records`. 7.4 is the census to run; its results are not recorded in this repository, and a record written after a run is not covered by it.
- **L2.** Every measurement is on Python 3.12.13, FastAPI 0.136.1, Starlette 1.0.0, pydantic 2.12.5, pydantic_core 2.41.5 and PyYAML 6.0.3 with libyaml; the lock pins FastAPI, pydantic and pydantic-core to these (`uv.lock:904-905, 3099-3100, 3114-3115`), while `pyproject.toml:50` allows `fastapi>=0.115`. The first failing depths (97 and 95) are for these versions; the tests find the window by scanning and pin no number.
- **L3.** The check is the call FastAPI 0.136.1 makes. On a FastAPI that writes another way the check and the later write can differ at the margin (not measured): a failure the check misses stays an unhandled 500 as before, and a body the check refuses that FastAPI would write becomes a 503 or is left out.
- **L4.** Cost: one more pass of the writer over each answered body (a listing: one pass over the whole body, and one more per record only when that pass fails). I ran no timing (a rule of this consult); the diff reviewer may time it, as slice 2's L7 did for its writer.
- **L5.** A record left out of a listing is not reported to the client: the body does not say so, `count` is the number of items returned, and the signal is the log line (WARNING, the count and at most five paths), repeated on every request while the record exists (Knowledge Browser polls); a monitor that counts 5xx responses no longer sees the record, a log-based alert does. The record's own read answers 503 `records.read_failed`, `RecordsStore.list_entries` (the Python side, the `strict=True` callers included) still lists it (M-9), and it stays on disk and in git; the base already left out a record the reader cannot parse with no signal at all. Decided by the Architect, not a Captain decision (D2: none of the six conditions is met). Considered and not taken: an additive `skipped` field on the five listings, present only when a record is left out, as a count and paths or as a count only. Run (M-9): it keeps every existing key and every ordinary body byte-identical, the existing route tests pass as on the base, and the new file passes 27 of 43 (the 16 whole-body comparisons of T8 would have to ignore the field); the HXI reads named keys and its browse validator ignores unknown ones (`useStore.ts:116-118`), so it would see nothing; the graph is unchanged (it fails whole). It adds a public key no client reads and a body with two shapes, and it must not be named `availability` (`classifyResourceResponse` treats a body holding a valid one as a failure before it reads the status, `resourceState.ts:76-78`). It is the available narrowing if a later reader judges the silent omission to need a signal.
- **L6.** The search scores a record before the route leaves it out, so its rarity counts that record; the others' scores are the search's own, not recomputed, and the search can return 19. The listings and the browse are not ranked.
- **L7.** One record whose `topic` or `topic_slug` the writer cannot write fails the whole graph with `graph_failed` (500) rather than leaving a node out (an edge would dangle). The alternative, a text label in `KnowledgeBrowserService.get_graph` (`backlinks.py:380`), changes a knowledge-layer payload for a non-text label and is not taken. The graph's other node fields are text or numbers by reading, not run.
- **L8.** Outside this module, `routers/gaps.py` `list_gaps` copies frontmatter values into its body (`gaps.py:35-39`; read, not run): it meets the same step for a hand-made gap report. Not in the box.
- **L9.** A different 500 of the same family, older and untouched: `get_captains_log` sorts by `created` (`records.py:124`) and raises `TypeError` for a `created` that is a YAML date beside one that is text; measured on the base and on M2's head, an unhandled 500 either way.
- **L10.** Not examined: an alias expansion whose JSON is very large. The reader and the route had no bound before; the check adds a second pass over it. This slice bounds neither.
- **L11.** Not measured by me: pytest, xfail semantics, `-n 16`, G1 to G3, the broad gate, the architecture check, vitest. Every count of mine is from my hand driver, a stand-in for the pytest features the files use, which ignores `conftest.py`. `test_issue1368_readiness.py`: 122 cases, 119 pass and 3 (`test_integration_nats_requires_current_connection`) stop at a fixture the driver does not provide, on the base and on M2's head alike. The BF-949 source-scan tests were run on a temporary copy of `src/probos` holding M2's router. Only the AD-1145 file was run under the rejected mechanisms.
- **L12.** The listings are not reader-scoped (`list_entries`; slice 2's D6) and the read route's classification gate runs before the check, so leaving a record out or answering its 503 changes no privacy or audit control. The statements about the HXI are from reading `useStore.ts` and `resourceState.ts`, not from running it.

## 11. Verified Against Codebase (2026-11-11, reading tree `D:\ProbOS-worktrees\bf940s2-build` at `e327d26e`)

Hand-driver results (Python 3.12.13, FastAPI 0.136.1, Starlette 1.0.0, pydantic 2.12.5, pydantic_core 2.41.5, PyYAML 6.0.3 with libyaml), each one in-memory script, a fresh temporary store per case, `~` moved, no `initialize()`, `TestClient(raise_server_exceptions=False)`; `n` is the number of single-key flow mappings `{a: {a: ... 1}}` under one frontmatter key:

- **M-1 (the matrix).** Premises asserted: the healthy records alone answer 200 on every listing, the listings hold exactly them and the graph has two nodes; the reader's own `read_entry` parsed each case's value except n = 600. Base: n = 90 is 200 on all ten GET routes. n = 100, n = 450, `!!binary //4=` (as `meta`) and `&a [*a]`: read 500; documents, notebook, captain's log, search, browse 500; `?format=prov-jsonld`, backlinks, timeline 200; graph 200 (the value is not a label). As `topic` (n = 450 and the bytes): the same, and the graph 500. n = 600: read 503 and prov 503 (the reader's `RecursionError`), the listings 200 without the record, backlinks 404. Variant C (the ten pairs): the read route 503 `records.read_failed` and each of the five listings 200 without the record for every row above, the graph 500 `knowledge_browser.graph_failed` as JSON for the two `topic` rows, everything else as the base. A (the read route only), B (the read route and three listings) and a fail-whole variant (each listing 503) and an application-level handler variant were driven the same way: the cells of D0 and D2.
- **M-2 (the writer).** `dump_json`, `dump_python(mode="json")` and `to_jsonable_python`: first failing n = 97 for the read route's body and 95 for a listing's, exception `PydanticSerializationError` for `dump_json` and `ValueError` for the others; non-UTF-8 bytes: `PydanticSerializationError` and `UnicodeDecodeError`. `jsonable_encoder`: `RecursionError` near n = 991 to 993, not monotone within four depths. `json.dumps(allow_nan=False)`: no failure to n = 2560. Through the real route the first failing n is 97 (read) and 95 (listing): n = 95 and 96 are the window. Shapes (`dump_json` / `dump_python` / `jsonable_encoder`): a UTC datetime `...Z` / `...Z` / `...+00:00`; a set a list in all three; UTF-8 bytes text; an int key `"1"` / `"1"` / `1`; `nan` and `inf` `null` / `None` / `nan`; an arbitrary object refused. 16 shapes built by `yaml.safe_load` (bytes UTF-8 and not, as value and as key; `None`, bool, float, `nan`, date and datetime keys; an int beyond 64 bits as value and key; an `!!omap` product; a set of ints; `inf`; an alias used twice): only non-UTF-8 bytes (value or key) refused; a self-referencing list refused (`PydanticSerializationError`).
- **M-3 (bytes).** Status and the first ten hex digits of the SHA-256 of the response body for the six-shape record and a 90-level record on `read`, `read90`, `list`, `notebook`, `captlog`, `browse`, `search`, `backlinks`, `timeline` (the graph by status): equal to the base's for C, for A, B and the fail-whole and application-handler variants, and for the read-route-only `convert` and `Response` variants; the base is stable across two runs. `jenc` answers the shapes record 503.
- **M-4 (mechanisms, read route).** AD-1145's seven `read_record` tests: 7 pass on the base and on C; 5 pass and 2 fail (`assert result is entry`, `tests/test_ad1145_provo_projection.py:583` and `:595`) under `dump_python` returned as the body, under `Response(dump_json(entry))` and under `JSONResponse(jsonable_encoder(entry))`.
- **M-5 (existing tests, hand driver, base against C).** The four AD-562 endpoint files 15 of 15 pass on both; `test_ad1145_provo_projection.py` `read_record` tests 7 of 7; `test_issue1368_readiness.py` 119 of 122 on both (L11); `test_bf949_notebook_reader_identity.py` route tests 2 of 2; `test_bf952_records_keyword_search.py` `test_the_records_search_route_confines_a_search_to_a_directory` 1 of 1; `test_bf940_s2_writer_policy.py` notebook-route tests 3 of 3. BF-949's two source-scan tests (`test_the_census_finds_the_four_records_search_callers`, `test_every_records_search_caller_in_src_passes_a_reader`) pass on the reading tree and on a temporary copy of `src/probos` whose `routers/records.py` is C.
- **M-6 (a writer-made record).** `write_notebook("alice", ..., metrics={"k": b"\xff\xfe"})` and `metrics={"k": <150-level mapping>}` write and read; base: read 500 for each, the listing 500 (it holds them) and a healthy note's read 200; C: read 503 for each, the listing 200 with them left out, the healthy note 200.
- **M-7 (classes).** `issubclass(pydantic_core.PydanticSerializationError, ValueError)` is `True`; `issubclass(RecursionError, ValueError)` is `False`. `get_captains_log` with a YAML date and a text `created`: the handler raises `TypeError` on the base and on C (L9). `router.routes` holds 13 routes, methods `GET` and `POST`, on both.
- **M-8 (the census).** The positive control, a clean tree, a mixed tree (7.4) and a missing folder, as 7.4 states; the script's SHA-256 (LF text) is `d297bb3e58b091f9899237f9b17cde5bbe68b4af5bef48e692eaf1265aa8f1b8`.
- **M-9 (the D2 follow-up; hand driver, Python 3.12.13, FastAPI 0.136.1; a fresh temporary store per case, `~` moved, no `initialize()`).** A note written through the product's own route, `POST /api/records/notebooks/alice` with `tags` nested 100 levels (the route answered 200 `written` on every tree and the reader parsed the note): on the base the documents, notebook, browse and search listings answer 500 and the read of the note 500 (`GET /captains-log` is 200: the note is not under `captains-log/`); on C (leave the record out) the four listings answer 200 without the note and its read 503 `records.read_failed`; under the fail-whole variant the four listings and the read answer 503; on all three `RecordsStore.list_entries()` and `list_entries("notebooks", strict=True)` still hold the note. The additive-field candidate (`skipped`, as `{"count", "paths"}` or as a count, only when a record is left out), built in memory over C: the read route and the five listings for the six-shape record and a 90-level record have the base's status and bytes; with a record left out each listing keeps its keys and gains `skipped` (browse keeps `filters_applied`, notebook `callsign`, search `query`, `count` where it had one); the existing route tests pass as on the base (readiness 119 of 122, AD-562 browse 4 of 4 and graph 5 of 5, BF-949 route 2 of 2, BF-952 route 1 of 1); the new file passes 27 of 43 under either form (16 of T8's cases, the whole-body comparisons of documents, notebook, captain's log and browse, fail). The fail-whole variant against the new file: 21 of 43 pass (T8's 20 cases, T9 and T10 fail).

Grep evidence (reading tree; line numbers are the slice-2 state):

```
routers/records.py: _read_failure :23-27; list_records :38-55; read_record :58-102 (read_entry try :86-96; prov branch :98; return entry :102); get_captains_log :118-125 (sort :124);
  list_notebook :128-137; search_records :166-190; browse_records :208-264 (filtered.append :255); get_records_graph :289-322 (return result :322); every handler is annotated -> Any
fastapi/routing.py:689-715 (use_dump_json when no response class is set and a response field exists; Response(content, media_type="application/json")); fastapi/_compat/v2.py:215-237 (serialize_json = TypeAdapter.dump_json)
knowledge/records_store.py: list_entries :1449-1522 (per-file except :1508-1509; {"path", "frontmatter"} :1522); read_entry :1418-1447; search hit {"path","frontmatter","score","snippet"} :479-482
knowledge/backlinks.py: node label :380; generated_at :449; routers/readiness.py:57-63 failed_read (503 -> state unavailable, retryable)
api.py:349-350 registration (for r in (..., records, ...): app.include_router(r.router)); no src file calls a handler by name
utils/frontmatter.py:78 "never a value (AD-1140's fail-fast tier)"; routers/workforce.py:9, :95 (TypeAdapter import; validate_json); pyproject.toml:25 pydantic>=2.0, :50 fastapi>=0.115; uv.lock:904-905, 3099-3100, 3114-3115
tests: test_ad1145_provo_projection.py:576-595 (identity); test_bf949_notebook_reader_identity.py:38-42, :333-373 (the scan); test_issue1368_readiness.py:149-189, :264-276
ui: useStore.ts:1963-1967, 2022-2026, 2046-2050, 2075-2079, 2209-2214 (fetches and their `!res.ok` branches), :1971 (`d.frontmatter || {}`); utils/resourceState.ts:22-26, :50-60, :62-79, :126-127; no setrecursionlimit in src or tests
```

## Absence Verified (2026-11-11)

```
CLAIM: no handler of routers/records.py other than the seven holds a record value.
RUN:   grep -n -E "\.(list_entries|read_entry|search|get_graph|get_backlinks|get_timeline|get_history|get_stats|write_notebook|append_captains_log)\(" src/probos/routers/records.py ; the M-1 matrix
FOUND: 13 calls (lines in section 11); list_entries x4, read_entry, search and get_graph feed the seven; get_stats, get_history, the two writers, get_backlinks and get_timeline do not
HOLDS: yes. Backlinks and timeline were driven (200 with such a record present); stats, history and the POSTs are by reading (two need a git child).

CLAIM: nothing in the repository outside tests, docs and prompts calls the records routes but the HXI.
RUN:   git grep -l -F "/api/records" -- . ':!tests' ':!docs' ':!prompts' ':!ui/node_modules' ':!node_modules' ':!site'
FOUND: routers/records.py, DECISIONS.md, PROGRESS.md, decisions-era-4-evolution.md, ui/src/store/useStore.ts, ui/src/components/NotebooksPanel.tsx, two UI test files
HOLDS: yes for the repository; a client outside it cannot be enumerated.

CLAIM: no other router returns a record's frontmatter.
RUN:   grep -l -E "records_store|\.read_entry\(|\.list_entries\(|get_graph\(|RecordsStore" src/probos/routers/*.py
FOUND: gaps.py (copies frontmatter values, L8), records.py, system.py (a readiness table), security.py (the erasure's store; it returns erasure results), skills.py and tools.py (the skill catalog)
HOLDS: yes by reading; gaps.py was not run.

CLAIM: no production code calls a handler function by name.
RUN:   grep -n -E "routers\.records|routers import records|from \.records import|include_router\(records|records\.router|records_router" src ; then api.py:295-350 read
FOUND: nothing by name; the router is registered at api.py:349-350 (for r in (..., records, ...): app.include_router(r.router)).
HOLDS: yes. Of the 9 existing test files that touch the routes, 7 import a handler by name; only the AD-1145 file was driven under the rejected mechanisms (2 of its 7 tests fail there); the other eight were driven on the base and on C only (L11).

CLAIM: nothing in src or tests raises the recursion limit, so the 600-level guard's premise holds under pytest.
RUN:   grep -rn setrecursionlimit src tests
FOUND: nothing
HOLDS: yes; the guard asserts its own premise (pytest.raises(RecursionError)) all the same.

CLAIM: no document or client promises a complete listing from the five listing routes.
RUN:   grep -rn -i -E "(lists?|listing|returns?|shows?) (all|every|the complete|a complete|the full) (documents?|records?|notebook entries|entries|ship's records)|complete (listing|list) of (documents|records|entries)|never (omit|hide|drop)s? (a )?(record|document|entry)" docs README.md src/probos/routers/records.py ui/src   (files *.md, *.py, *.ts, *.tsx)
FOUND: nothing
HOLDS: for the phrasings the pattern matches. The route docstrings say "List documents", "List a crew member's notebook entries" and "Get recent Captain's Log entries", and list_entries documents the skip (records_store.py:1463).

CLAIM: no document presents a records listing as an audit surface.
RUN:   grep -rn -i -E "(ship's records|records store|captain's log|knowledge browser|notebooks? browser)[^\n]{0,120}\baudit|\baudit[^\n]{0,120}(ship's records|records store|captain's log|knowledge browser|notebooks? browser)" docs README.md
FOUND: docs/architecture/memory.md:161 (the memory-tier table names a "Security audit report" as an example document of Ship's Records; it does not call a listing an audit surface)
HOLDS: for the phrasings the pattern matches. The store's own docstring names git as the audit trail (records_store.py:616-619).
```

## 12. Prior Art and Blind Spots

- **Internal: adopted.** Slice 2's D4 (serialise inside the route's boundary, the existing 503) and its D6 (one record must not abort a listing); AD-1145 DD-7 (the body is byte-identical; its tests assert the object); AD-1140's rule that a refusal names no value; BF-949's census of `.search` callers (no call is added); the module's own log-and-degrade tier (`except` then `logger.warning(...)` then an envelope) and its message style, which `test_issue1368_readiness.py` pins. **Rejected:** slice 2's `dump_python(mode="json")` returned as the body (two relied-on tests assert the object); `jsonable_encoder` (D1); an application-level handler (D0).
- **Blind spots handled.** The depth a record has in a listing (two levels deeper than on the read route: T9); the identity of the returned object (AD-1145); the `?format=prov-jsonld` branch, which the check must not reach (T4); the reader's own 600-level failure (T3); a record the store's writer makes (M-6); a self-referencing value (the writer refuses it; T7, T8); the graph's one raw value; the limit of the captain's log counted after the filter (T10); a value in a log line (markers in T7, T8, T11; mutation row 12); a new route that holds a record value (T6).
- **What discards a correct result.** A writable record left out: each record is tried at the depth it has in its body, and the whole body is tried first, so a record FastAPI would write is kept; after a per-record pass the filtered body is not tried again (no global limit is known; L3). A 503 for a record FastAPI would write: the check is the call FastAPI makes on the locked version (M-2: the same first failing depth), not on another (L3). A listing's `count` that disagrees with its items: it is taken after the filter (T8 compares whole bodies). **Recorded:** L1 to L12.

## 13. Diff Reviewer: properties to verify

1. `_writes(body)` is `TypeAdapter(Any).dump_json(body)` in a `try` that answers `False` for `ValueError` (which `PydanticSerializationError` is) and `RecursionError`, and nothing it writes is kept or returned; any other exception propagates.
2. When `_writes` is true a handler returns what it returned before: `read_record` returns `entry` itself (AD-1145 `:583`, `:595`), `_writable` returns the very list it was given, and the response bytes are unchanged (M-3).
3. `read_record`: the check follows the `?format=prov-jsonld` branch and precedes `return entry`; the `try`, its three `except` clauses and the 404 are untouched; the 503 is the existing envelope; the log line names no path and no exception.
4. `_writable` tries `{key: [record]}` (the depth of a record in a listing's body), tries the whole body first, logs a count and at most five `%r` paths and never a value; each listing route filters before it counts, and `get_captains_log` filters before its sort and its limit.
5. The graph check follows the `None` check and answers the envelope the route's `except` branch answers.
6. No other handler, no store method and no other file of `src` is edited; the backlinks, the timeline, stats, history and the POSTs are as before; no existing test is edited (N2-1 removes the new file's own marker).
7. **Half-chain evidence:** each of T7 to T11 is one test from a record on disk through the real store and the real router to the status and the body, not a producer test and a consumer test.
8. The marker carries `raises=AssertionError, strict=True`; the 28 class cases fail at their own `assert`, never at a premise line (G1 with `--runxfail`); the 15 guards pass on both trees.
9. T9 finds its depth by scanning with the writer FastAPI uses and pins no number; if the writer's limit stops being a depth the premise fails loudly.
10. The log lines carry no record value and match the neighbours' `returning HTTP 50x` pattern (`test_issue1368_readiness.py:164, :188`); the census of 7.4 is run before the pull request merges.

## 14. Acceptance criteria

- G1, G2 and G3 pass as stated, the census of 7.4 is run on the vessel's copy, and the batch's broad gate is green with a receipt.
- **F7-1:** a record the reader parsed and the JSON writer cannot write is answered by the read route with the existing 503 `records.read_failed` envelope (T7), is left out of each of the five listings that hold a frontmatter, with the rest listed and the path logged (T8, T9, T10), and fails the graph with its own envelope (T11); the body of every record that was answered before is byte-identical (T1, T2, M-3), `?format=prov-jsonld`, the backlinks and the timeline are unchanged (T4, T5), the 600-level record answers as before (T3), and a new route fails T6 until it is classified.
- **The issue:** the pull request says `Refs #1686`; the trackers (PROGRESS.md, DECISIONS.md) say that F7-1 closes and that L19, the last box, keeps the issue open.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. For the Captain

1. **Nothing in this slice needs your decision.** D2 (a listing leaves out a record the writer cannot write, and logs its path) was checked against the six conditions under which the Captain decides in Delegated AD Execution Mode and meets none (D2's table): nothing stored changes, no control is weakened, no response shape or client contract changes, nothing is spent or moved, and the risk is Low. It is decided by the Architect and recorded in D2, L5 and DECISIONS. The price is that the omission is reported in the log, not to the client (L5). The ranked overrule option, if you prefer it, is to fail the whole listing: every listing that holds such a record then answers 503 while it exists (D2, M-1, M-9), at the cost of 22 cases of the new test file and mutation rows 4 to 10 and 12.
2. Run the census (7.4) on a read-only copy before the pull request merges; a flagged record is one you may want to repair or archive.
3. L19 follows in the last slice; nothing in this one decides it.
