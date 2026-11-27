# BF-940 (#1686): A record the reader parsed is a record the records routes can answer: the read route and every route that returns a frontmatter ask the JSON writer before they return (slice 3 of the issue)

**Drafted by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge was logged out), 2026-11-11
**Status:** ready to build on slice 2's merge. **Reading tree:** `D:\ProbOS-worktrees\bf940s2-build`, `HEAD` `e327d26e` (slice 2's frozen head, tree `ca85ef7047a8e19bd502ad4e1f6c21868a94b62e`; `origin/main` `a66e272f` had not moved). Every SEARCH below is in the slice-2 state of its file (`routers/records.py` is untouched by slice 2). **Oracle:** a read-only consult: no pytest, no timing or benchmark script, no script that spawns a child process (git read commands were run from the shell). Before amendment A1, in-memory scripts applied the 10 SEARCH/REPLACE pairs of M2 to the LF blob of `routers/records.py` (each SEARCH once; the result compiles), exec'd it as `probos.routers.records` and drove the real router through `TestClient` over a real `RecordsStore` of hand-made records (no `initialize()`, `~` moved, a fresh temporary directory per case). A hand driver (a stand-in for the few pytest features the file uses; not the runner) called the 43 functions of N1-1: on the reading tree 15 pass and 28 fail, each at the `assert` section 6 names; on M2's head all 43 pass; the 12 mutants of section 9 fail exactly the cases listed. The route tests of nine existing files and the BF-949 source-scan tests were driven the same way (section 11, M-5). The census of 7.4 was run on synthetic trees. **Not run:** G1 to G3, pytest, xfail semantics, `-n`, the broad gate, the architecture check, the ledger generator, vitest, a timing run (L4), the census on a real tree, the orchestrator's slicer. After the text was written, the real apply tool (`apply_search_replace_blocks_bare.py`, run in-process on a throwaway root holding copies of the three files) wrote the new file and applied the 10 + 1 + 2 pairs with 0 failures, and the files it produced had the hashes of section 9 as they stood before A1. **Amendment A1** (2026-11-11) folds in a Linux run and review round 1: (a) the depths of N1-1 were Windows values (the writer's depth stop is a compiled constant of pydantic-core that differs by platform), so N1-1 now derives every depth from the writer at import (M-10); (b) the backlinks and the timeline carry record values (a tag, a topic slug, a department, a day) and the PROV-O projection can carry an unwritable `created`, so they are guarded like the graph and the read route (D0, P2-3, P2-4, P2-11, P2-12; M-11); (c) a lone surrogate joins the values of the class and T12 and T13 are added (54 cases: 16 guards, 38 class cases); (d) the inventory is corrected (section 11, Absence Verified) and the write side's own unhandled 500s are recorded, not fixed (L13). Every statement above about runs and counts is of the contract as first written (43 cases, 10 router pairs). A1 was checked with the real apply tool on throwaway copies (the amended contract rebuilds the router, the test file and the two trackers that A1's pairs make), by compiling and importing the amended test file, and by in-memory runs of route answers on the unfixed base, the candidate, the amended router and 16 mutants of it (M-11): no test, hand driver or campaign was run on the amended files, and the counts of section 9 after A1 are derived from the parametrisation and those answers until a run replaces them.
**Base blobs** (git blob ids of the LF-normalised working copy of the reading tree, computed by script; each equals `git rev-parse HEAD:<path>`; they must equal slice 2's merge): `src/probos/routers/records.py` `1b95965effea0a7d666830413bef677ae463f06a`, `PROGRESS.md` `da466972f78120767dc6646e3bb57e1b91d34405`, `DECISIONS.md` `29cddd81ee018a0ea87da588005372a690547d70`; tests this slice relies on and does not edit: `tests/test_ad1145_provo_projection.py` `a3507fb93fad854475068f0d0e597c79c817f54f`, `tests/test_bf949_notebook_reader_identity.py` `8a7a524225ccfd4bbe78f6411a9c82e9ec8b7477`, `tests/test_issue1368_readiness.py` `3ffdf90fd54f2480c8710d9cca80cd71d0096909`.
**Dependencies:** slice 2 merged. **Tier:** M1 STANDARD (tests); M2 HIGH (the boundary of every route that returns a record); M3 STANDARD. **Estimated tests:** one new file, 54 cases (16 pass and 38 xfail at M1; 43, 15 and 28 before A1), and no existing test edited. **BF number:** BF-940, held by #1686 (open, `bug`); nothing new is allocated.
**What this contract closes of #1686:** F7-1 (the records route returns 500 for a record the reader parsed). **The issue keeps** L19, the last box, which follows in a later slice, and stays open: the pull request says `Refs #1686`, not `Closes`.

**Which text describes the head.** Before building: slice 2 is merged, `git rev-parse HEAD:<path>` for the three edited paths prints the blobs above, `git diff --stat e327d26e HEAD -- src/probos/routers tests PROGRESS.md DECISIONS.md` shows nothing that is not slice 2's merge, and the new test file does not exist. If a blob differs, every SEARCH must still occur exactly once, else it is a hard stop for the Architect. Working copies are CRLF and SEARCH text is LF. Where prose and a block differ, the block wins. Apply the pairs with the `edit` tool one at a time, whole block, in label order.

## 1. Problem

1. **The defect.** `read_record` (`routers/records.py:58-102`) catches the failures of `read_entry` (`:86-96`) and then returns its mapping. FastAPI 0.136.1 writes a `-> Any` handler's return after the handler has returned, with `TypeAdapter.dump_json` over `Any` (`fastapi/routing.py:689-715`, `fastapi/_compat/v2.py:215-237`), outside that `try`. A record the reader parsed and the writer cannot write therefore answers an unhandled HTTP 500 (the framework's plain-text body, no `availability`), where a record the reader cannot parse answers the controlled 503 `records.read_failed`.
2. **What the writer refuses** (hand driver; 16 shapes `yaml.safe_load` builds, plus depth and self-reference; section 11, M-2). A mapping nested too deeply: the writer's depth stop is pydantic-core's recursion guard, a compiled constant (`RECURSION_GUARD_LIMIT` in `src/recursion_guard.rs`, tag v2.41.5: 255, 99 on Windows or PyPy, 49 on wasm or Windows PyPy, 20 less in a debug build), so for n single-key mappings under one frontmatter key the read route's body first fails at n = 97 on Windows and 253 on Linux, and a listing's body two levels sooner (95 and 251), because a listing holds a record two levels below its top (M-10). Bytes that are not UTF-8, as a value or as a key. A container that holds itself (`&a [*a]`). A lone surrogate in a text value, which a JSON client can send to the notebook route as a tag or a department (M-11; none of the 16 shapes tried here was one, which is how the first version of this contract missed it). Every other shape tried is written: a UTC datetime as `...Z`, a date, a set as a list, UTF-8 bytes as text, an int key as text, `nan` and `inf` as `null`, a big int, an `!!omap` product. The records need not be hand-made: `write_notebook("alice", ..., metrics={"k": b"\xff\xfe"})` and a `metrics` mapping nested 150 levels (over the Windows limit only) both write and read, and both read 500 on the base on Windows (M-6); no production caller passes either (slice 2's callers table).
3. **Which handlers share it** (a run: 10 GET routes x 8 records on the base and on M2's head, M-1; the module's 13 store and service calls, `records.py:35, 50, 88, 114, 123, 134, 151, 187, 199, 228, 280, 309, 340`):

| Handler (route) | Its body holds | Base, for a record just over the writer's limit or far over it (M-10), with non-UTF-8 bytes, or holding itself |
|---|---|---|
| `read_record` (`GET /documents/{path}`) | `read_entry`'s `{frontmatter, content, path}` | 500 |
| `list_records`, `get_captains_log`, `list_notebook`, `browse_records` | `list_entries`' `{path, frontmatter}` items (`records_store.py:1522`) | 500, for every record in the listing |
| `search_records` | a hit's `frontmatter` and `snippet` (`records_store.py:479-482`) | 500 |
| `get_records_graph` | a node's `label`, `fm.get("topic_slug") or fm.get("topic") or <file stem>` (`backlinks.py:380`) | 500 when the value is the topic or a department (run, M-11), and by reading a classification or an author; 200 under another key such as `meta` |
| `read_record?format=prov-jsonld` | a document of strings; the one free text is a `created` that parses as ISO-8601 and is copied verbatim (`provo.py:155-164, 286-288`), and `datetime.fromisoformat` takes any one character between the date and the time | 200; 500 for a `created` with a lone surrogate there (M-11) |
| `get_backlinks` | `references`: a record's tags, its topic slug and the text of its wikilinks; `referenced_by` and `suggested`: paths (`backlinks.py:46-88, 313-329`) | 200 for the values of the rows above; 500 for a tag or a topic that is a lone surrogate (M-11) |
| `get_records_timeline` | `buckets`: a day (`created[:10]`) and a `by_department` key per record (`backlinks.py:454-488`) | 200 for the values of the rows above; 500 for a department, or a day, that is a lone surrogate or non-UTF-8 bytes (M-11) |
| stats | counts, a fixed list of directory names and the configured path (`records_store.py:1645-1670`) | not run (it starts git) |
| history | git text decoded with `errors="replace"` (`records_store.py:1526-1550, :1833-1834`) and the request's own path, which a URL decodes to U+FFFD, never a lone surrogate (M-11) | not run (it starts git) |
| the two POSTs | `{path, status}`: the written path, built from the request's callsign and topic (`records.py:105-115, 140-163`): the write side, L13 | 500 for a lone surrogate in some request fields, on the base and after this slice (M-11, L13) |

4. **The reader's own limit.** A record nested 600 levels, over the reader's own stop (about 490 levels on Windows and on Linux, M-10), makes `read_entry` raise `RecursionError`: the read route answers 503 `records.read_failed` and `list_entries` skips it (`records_store.py:1508-1509`). Both are unchanged and are guards (T3).
5. **Consumers of the routes.** The HXI's Notebooks panel (the documents listing, an entry, the search) and Knowledge Browser (browse, graph, timeline, entry, backlinks), `ui/src/store/useStore.ts:1963, 2022, 2046, 2075, 2209-2214`; `git grep -l -F "/api/records"` outside tests, docs and prompts finds nothing else but `routers/records.py`, the trackers and the UI's own files. In `src`, no Python file calls the route: `read_head_to_head` (`recreation/history.py:184`) and the other callers of `list_entries` (`grep -rn "\.list_entries(" src`) call the store directly.
6. **Tests that rely on this module's shape.** `test_ad1145_provo_projection.py:583, :595` assert `result is entry` (the handler returns the store's own object); four AD-562 files and the BF-949 and BF-952 files call handlers as functions; `test_bf949_notebook_reader_identity.py:333-373` scans the source of every `.search(` caller; `test_issue1368_readiness.py:165, :189, :276` assert a secret is in neither the response nor the log.

## 2. Solution

`routers/records.py` gains `_JSON_WRITER = TypeAdapter(Any)`, `_writes(body) -> bool` and `_writable(records, key, route) -> list`. The read route builds its body (the entry, or the PROV-O projection when `?format=prov-jsonld` is asked), answers `_read_failure("Record document unavailable", "records.read_failed", 503)` when `_writes(body)` is false, and otherwise returns that body itself. The four listings, the browse and the search build their body from `_writable(...)`, which returns the same list when the whole body writes and otherwise the records that write, each tried inside `{key: [record]}` (the depth the record has in the body), logging the left-out paths (never a value). The graph, the backlinks and the timeline answer their own existing `graph_failed`, `backlinks_failed` and `timeline_failed` envelopes (500) when their body does not write. Nothing the writer produces is kept: a handler returns its own body, so every answered response is byte-identical to the one it sent before. No config, event, dependency or shared contract changes.

## 3. Decisions

Ranked by correctness, safety, compatibility, architectural fit, reversibility and validation cost; Delegated AD Execution Mode: the top is taken. "Boundary" asks whether an option weakens a privacy or audit control or breaks a compatibility promise (a Captain-only decision). Cells and sentences marked (read) are from source, not run; every other measurement is from my hand driver on the reading tree.

**D0. Scope (amended by A1).** The status of each route for a record just over the writer's limit (100 levels measured on Windows) or far over it (450 there), non-UTF-8 bytes, holding itself or a lone surrogate (graph: when the value is the topic or a department; backlinks: a tag or a topic; timeline: a department); the same for a record just below the limit (90 on Windows) and for the six-shape record (a UTC datetime, a date, a set, UTF-8 bytes, a unicode value under an int key, `nan`): status and response bytes equal the base's on nine routes under every option (the graph by status: its body holds `generated_at`, `backlinks.py:449`) (run, M-1, M-3).

| # | Option | Read route | Documents, notebook, captain's log | Browse, search | Graph, backlinks, timeline | Boundary |
|---|---|---|---|---|---|---|
| A | The read route only (the box) | 503 `records.read_failed` (its projection: 500) | 500 | 500 | 500 | none |
| B | The read route and the three listings, one helper (slice 2's D4 suggestion) | 503 (its projection: 500) | 200, record left out | 500 | 500 | none |
| **C** | **Every handler whose body holds a record value (nine) and the read route's projection, one check (chosen)** | 503, for the record and for its projection | 200, record left out | 200, record left out | 500, each route's own envelope (`graph_failed`, `backlinks_failed`, `timeline_failed`) | none |
| D | An application-level handler for `PydanticSerializationError` (slice 2's D4 option 3) | 503 with a generic code, not `records.read_failed` | 503, whole listing | 503, whole | 503 | breaks no promise in this module, but turns the failure of every route of the application into one 503 (by construction; not run beyond this router) |

Rank C > B > A > D. Correctness: only C leaves no route of the module at an unhandled 500 for such a record (slice 2's D4 named three listings; the browse and the search carry a frontmatter too, so B leaves the Knowledge Browser's main view and the Notebooks search at 500; review round 1 found three more: the backlinks, which carry a tag and a topic slug, the timeline, which carries a department and a day, and the projection, which copies a `created`, so A and B leave all three at 500 for a lone surrogate that the notebook route accepts, M-11). Safety: all four fail closed and fabricate nothing; D also changes failures outside the module. Compatibility: A to C change only a status that was an unhandled 500; D changes other routers'. Architectural fit: C keeps each route's own envelope, which D cannot name. Reversibility: A to C one file; D a hook on the application. Validation cost: C the most (nine routes and the projection, 54 cases), A the least. The HXI (read): the Notebooks panel treats any non-OK response as empty (`useStore.ts:1964-1967, 2023-2026, 2047-2050, 2076-2079`), so under A it shows nothing while one such record exists; Knowledge Browser turns a body holding `availability` into that state (a 503 is `unavailable`, a plain-text 500 is `failed`, `ui/src/utils/resourceState.ts:62-79`) and retries at 10 s and 30 s, then stops (`:22-26`).

**D1. The mechanism** (slice 2's D4 chose `TypeAdapter(Any).dump_python(mode="json")` and returning its result; re-measured here). FastAPI 0.136.1 writes these handlers with `TypeAdapter.dump_json` (`fastapi/_compat/v2.py:215-237`); on Windows the first failing depth is the same 97 (the read body) and 95 (a listing body) for `dump_json`, `dump_python(mode="json")` and `to_jsonable_python`, so a check with either fails exactly where the later write would (run, M-2). Rows: the six-shape record and a record just below the limit (90 levels on Windows) on the read route (bytes against the base), a record the writer cannot write, and the AD-1145 tests that call `read_record` as a function (7; hand driver).

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
| 2 | Fail the whole listing with `records.read_failed` 503 (run, M-1; **the ranked overrule option**) | 503 on all five | any non-OK is empty, so every author vanishes; Knowledge Browser shows `unavailable`, retries twice, stops | none | none | every record is hidden behind one, and a note any client can write through `POST /api/records/notebooks/{callsign}` (`tags` nested over the writer's limit, 100 levels on Windows: the route answers 200 and writes it) keeps the documents, notebook, browse and search listings at 503 for every reader (run, M-9) |
| 3 | List the record without its frontmatter | not built, not run | `d.frontmatter \|\| {}` (`useStore.ts:1971`) copes; unknown clients are not known to | none | `count` includes it | visible, but a new item shape for every client |

Rank 1 > 2 > 3. `list_entries` already skips a record it cannot read (`records_store.py:1463`, `:1508-1509`), so option 1 extends the listing's own rule to one more reason, and slice 2's D6 took the same side (one bad record must not abort a listing). **Decided by the Architect: none of the six conditions under which the Captain decides in Delegated AD Execution Mode is met.** The routes below are the five listings and the graph; the read route returns one record and leaves nothing out. Cells marked (read) are from source, not run; the others are from the hand driver (M-1, M-3, M-9).

| Condition | Met | Why |
|---|---|---|
| 1. An irreversible or destructive production-data operation | no | The change is on the read path: no file, git object or index is written, and reverting `routers/records.py` undoes it. |
| 2. Weakening a security, privacy, consensus, authorization, audit or safety control | no | The read route's classification gate runs before the check; the listings are not reader-scoped and the search reads as the Captain (`records.py:187`), so an omission only removes and discloses nothing. The audit trail here is git (`records_store.py:616-619`; `GET /history/{path}` is `git log --follow -- path`, `:1526-1541`) and the store's own callers (`stand_down.py:281` and `archive_promotion.py:310` read `list_entries(..., strict=True)`) (read); the router touches none of them, and after a note written through `POST /api/records/notebooks/{callsign}` with `tags` nested over the writer's limit (100 levels on Windows) `list_entries()` and `list_entries("notebooks", strict=True)` still hold it. Per route: documents, browse and notebook are views; the search is a ranked sample capped at 20 that already withholds records it cannot read (read); the captain's log can only be made unwritable by a hand edit (`append_captains_log` writes four `str` frontmatter values and appends body text, `:883-916`) (read); the graph leaves nothing out (a node label the writer cannot write fails the whole graph with its own envelope). The base already omits a record the reader cannot parse, with no signal in the body (the 600-level row of M-1; T3), and a WARNING that names a path is the module's own practice for a listing that skips a record (`:1496`) (read). Against the base the policy removes a weakness: that note (the route answers 200) makes the documents, notebook, browse and search listings answer 500 to every reader on the base and 503 under option 2, and 200 without that one note under option 1, whose read of the note answers 503 `records.read_failed` (M-9). |
| 3. Breaking a public API, a persisted schema, a federation protocol or a compatibility promise | no | No key is added, removed or retyped. `count` is the number of items returned: the HXI's browse validator requires `count === documents.length` (`useStore.ts:116-118`) (read) and T8 compares whole bodies. Every ordinary body is byte-identical (M-3). The one status that changes is a listing that was an unhandled 500, which is now 200 without the record; no document promises a complete listing (section 11, Absence Verified) and `list_entries` documents the skip (`:1463`); AD-1145 DD-7's byte-identity is for the read route's body and holds. |
| 4. New spending, a paid or incompatible dependency, a secret or credential, access to a live production system | no | `pydantic` is already a dependency (`pyproject.toml:25`); the census is a separate step on a copy. |
| 5. Moving information or implementation across the OSS/commercial boundary | no | One OSS router module. |
| 6. Accepting unresolved Critical/High risk, or changing the product objective beyond the issue | no | The risk is Low: no production caller passes such a value (slice 2's callers table), the omission is logged by path and answered by the record's own 503, and the census counts the records. The objective is F7-1's own: a record the reader parsed answers 500. |

**Overrule option (ranked 2): fail the whole listing.** Effect (M-1, M-9): every listing that holds such a record answers `records.read_failed` 503 and so hides all its records (all five in M-1; four of the five for a note under `notebooks/` in M-9), the Notebooks panel shows nothing and Knowledge Browser `unavailable`, and any client that can write a note keeps them down; nothing is left out silently. Switching is the body of `_writable` (a whole-body check that answers the 503) and, in the new test file, the expected answers of 27 cases (T8's 25, T9 and T10: 27 of 54 pass against the fail-whole variant, by construction; 21 of 43 passed before A1, run) and mutation rows 4 to 10 and 12.

**D3. The failure envelope and its log.** Rows: (1) the existing 503 `records.read_failed`, message "Record document unavailable" (chosen); (2) a new code with a 500 `failed`; (3) a log line that carries the exception. (1): the same envelope the reader's own `RecursionError` already gets (run: the 600-level row), so one family of record has one answer just over the writer's limit, far over it and at 600 levels (over the reader's own stop); Knowledge Browser reads its `state` (`unavailable`), not its `code`. `retryable` is true for a defect that does not heal; it is true for the 600-level record already (`routers/readiness.py:57-63`). (2) is truer and splits one family across two answers that no client reads. (3) is rejected: the exception's text was not examined for whether it can echo a value. The read route's log line is static, ends `returning HTTP 503` as its neighbours do and names no path (a client supplied it) and no exception (`exc_info` is absent from its siblings; `test_issue1368_readiness.py:165, :189, :276` assert a secret is not in the log). A listing's log line names the paths the store's walk produced (at most five, with `%r`) and a count; the graph's names neither. Never a value: AD-1140's rule for a refused value (`utils/frontmatter.py:78`).

## 4. Milestones and gates

| M | Blocks | Gate |
|---|---|---|
| M1 | N1-1 | G1 |
| M2 | P2-1 to P2-12, then N2-1 (the marker) | G2 |
| M3 | P3-1, P3-2, ledger | G3 |

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. **M0:** on the head, record the collected count (`--collect-only -q`) of every existing file G2 names, and the four counts of `PY -P scripts/check_architecture_principles.py --check`.

- **G1.** `PY -m pytest tests/test_bf940_s3_route_serialisation.py -q -n 0 -p no:randomly`. **Expected:** 54 cases, **16 passed, 38 xfailed**. The marker carries `raises=AssertionError, strict=True`: any other exception, or an XPASS, is a FAIL. Then once with `--runxfail`: each failure must stop at the `assert` section 6 names, never at a premise line.
- **G2.** (1) `$f = git grep -l -E 'routers\.records|/api/records|\bread_record\b|\bsearch_records\b|\bbrowse_records\b|get_records_graph|get_records_timeline|\bget_backlinks\b|\blist_records\b|\bget_captains_log\b|\blist_notebook\b' -- 'tests/test_*.py'` (9 files on the reading tree; M0 records the count of the full list); then `PY -m pytest $f tests/test_bf940_s3_route_serialisation.py tests/test_layer_boundaries.py -q -n 0 -p no:randomly`. (2) `PY -P scripts/check_architecture_principles.py --check`. **Expected:** the new file's 54 passed; every other file 0 failed with collected counts equal to M0; the check clean with its four counts equal to M0's.
- **G3.** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- **Census (not a Builder step).** Run 7.4 on the vessel's copy before the pull request merges; a flagged document goes back to the Architect.
- **Harness rule.** No source change made to pass a test, no skip, no loosened assertion. A failing case of the new file at G2, or any existing test failing, goes back to the Architect. The broad gate runs once, in the main session, with `--receipt`.

## 5. Commit messages

- **M1:** `BF-940 M1 (slice 3): tests for a record the reader parsed being answered by every records route, xfail until built (#1686)`
- **M2:** `BF-940 M2 (slice 3): the records routes ask the JSON writer before they return; a record it cannot write is a 503, is left out of a listing, or is its route's own 500 envelope (#1686)`
- **M3:** `BF-940 M3 (slice 3): trackers and ledger (#1686)`; its body ends with the line `Refs #1686.`

## 6. Tests

`tests/test_bf940_s3_route_serialisation.py` (M1; the functions pass on both trees, the class is strict xfail until M2). A case asserts its premise first (the healthy records alone are answered; the reader's own `read_entry` returned the record), so a failure cannot mean the record was never read. `TestClient(raise_server_exceptions=False)` makes the unfixed 500 a response, so each case fails at an `assert`, not at an exception out of `get`. No test pins a depth (A1): the file asks its own `TypeAdapter(Any)` at import where the read route's body and a listing's stop, and builds `nested-over-limit` (five levels over a listing's limit), `nested-far-over-limit` (fifty over the read route's) and the guard below the limit (five under a listing's) from the answer, so the same file proves the same thing on Windows (97 and 95) and on Linux (253 and 251); a writer that never stops, or stops at once, fails the import at its own premise. A lone surrogate is the ASCII escape `\ud800` in a JSON body or in a YAML value, never a literal one.

| Id | Cases | Covers | xfail until |
|---|---|---|---|
| T1 | 1 | Guard: a UTC datetime, a date, a set, UTF-8 bytes, a unicode value under an int key and `nan` are written as before, on the read route and in a listing (`test_a_record_holding_every_shape_the_reader_builds_is_answered_as_it_always_was`) | none |
| T2 | 6 | Guard: five levels below the depth at which the writer stops a listing's body (90 on Windows, 246 on Linux), on the read route and in each listing (`test_a_record_just_below_the_writers_limit_is_answered_by_every_route`) | none |
| T3 | 1 | Guard: 600 levels, over the reader's own stop (about 490 on Windows and on Linux): the reader's `RecursionError`, the read route's 503, a listing without the record (`test_a_record_beyond_the_readers_own_limit_keeps_its_answers`) | none |
| T4 | 5 | Guard: `?format=prov-jsonld` of a record whose `meta` the writer cannot write is 200, for each of the five values: the projection copies no `meta` (`test_the_provenance_projection_of_a_record_the_writer_cannot_write_is_still_answered`) | none |
| T5 | 2 | Guard: the backlinks and the timeline are 200 while a record whose topic is not text exists: neither carries a topic of that kind (`test_the_backlinks_and_the_timeline_answer_a_record_whose_unwritable_value_they_do_not_carry`) | none |
| T6 | 1 | Guard: every route of the module is classified, and the routes that hold a record value are the nine the class drives (A1: the backlinks and the timeline joined) (`test_every_route_of_the_module_is_classified`) | none |
| T7 | 5 | Class: the read route answers the controlled 503 envelope for a record just over the writer's limit, far over it, with bytes that are not UTF-8, holding itself and holding a lone surrogate; the log ends `returning HTTP 503` and holds no value (`test_the_read_route_answers_a_record_the_writer_cannot_write_with_the_controlled_503`) | M2 |
| T8 | 25 | Class: each of the five listings with each of the five values: 200, the body equal to that of a store without the record, the left-out path logged, no value logged (`test_a_listing_leaves_out_a_record_the_writer_cannot_write_and_keeps_the_rest`) | M2 |
| T9 | 1 | Class: a record the read route answers and a listing cannot carry (the depth is scanned in a window around the limit the file derived from the writer, and must equal it: none is pinned) is left out of the listing only (`test_a_record_the_read_route_can_write_is_left_out_of_a_listing_two_levels_deeper`) | M2 |
| T10 | 1 | Class: the captain's log's limit counts the records it returns (`test_the_captains_log_limit_counts_the_records_it_returns`) | M2 |
| T11 | 3 | Class: a graph whose node label cannot be written (far over the limit, non-UTF-8 bytes, a lone surrogate) answers its own 500 envelope, as JSON (`test_the_graph_answers_a_record_whose_topic_the_writer_cannot_write_with_its_own_envelope`) | M2 |
| T12 | 2 | Class: a note the real notebook route accepts with a tag, or a department, that is a lone surrogate is answered by the backlinks, or the timeline, with its own 500 envelope as JSON; the log ends `returning HTTP 500` and holds no value (`test_a_note_the_notebook_route_accepts_is_answered_by_the_backlinks_and_the_timeline_with_their_own_envelope`: `tags-backlinks`, `department-timeline`) | M2 |
| T13 | 1 | Class: the projection of a record whose `created` has a lone surrogate between the date and the time is answered with the same 503 `records.read_failed` as the read (`test_the_provenance_projection_of_a_created_the_writer_cannot_write_is_answered_with_the_controlled_503`) | M2 |

**How each xfail case fails on the unfixed tree** (hand driver, reading tree): T7 at `assert response.status_code == 503` (it is 500); T8 at `assert response.status_code == 200`; T9 at the same assert on the listing, after the premise that the read route answers the record; T10 at `assert response.status_code == 200`; T11 and T12 at `assert response.headers["content-type"].startswith("application/json")` (a plain-text 500; T12 after its premises: the route answered 200, the reader gave the surrogate back, the writer refuses the body this route builds); T13 at `assert response.status_code == 503` (it is 500). T7 to T11 as run before A1; T11's lone surrogate, T12 and T13 as the answers of the unfixed base (M-11): no test function was run. **Guards that pass on both trees:** T1 to T6. A source-scan caveat: the only scan here is T6, which reads `router.routes`, a runtime object; it cannot see a handler a route table does not hold.

## 7. The contract

### 7.1 M1

**N1-1.** New file `tests/test_bf940_s3_route_serialisation.py`:
```python
"""BF-940 slice 3 (#1686, F7-1): a record the reader parsed is a record the Ship's Records routes can answer.

FastAPI writes what a handler returns as JSON after the handler has returned, outside the handler's own error boundary. A record the
reader parsed but the JSON writer cannot write (a mapping nested deeper than the writer's recursion guard allows, bytes that are not UTF-8, a lone
surrogate, a value that holds itself) was therefore an unhandled HTTP 500 on the read route, on its PROV-O projection and on every route that returns a
frontmatter value. Real ``RecordsStore``
over ``tmp_path`` with ``~`` moved, hand-made records, the real router through ``TestClient(raise_server_exceptions=False)`` (so the
500 is a response a test can assert on, not an exception out of ``get``), no network.

The writer's depth stop is pydantic-core's recursion guard, a compiled constant that differs by platform (the read route's body first fails at nesting 97
on Windows and 253 on Linux), so no test pins a depth: the module asks its own ``TypeAdapter(Any)`` at import where the read route's body and a listing's
stop, and derives every depth below from the answer. The reader's own stop (``RecursionError`` at about 490 levels on Windows and on Linux, Python 3.12) is
that of pure-Python PyYAML and does not depend on the writer. A lone surrogate reaches a record as an ASCII escape, ``\\ud800``, in the JSON a notebook
route is sent or in the YAML of a hand-made record: a literal one cannot be written to a file as UTF-8.

The class is strict xfail until M2 (each case fails at an ``assert`` of its own body on the unfixed tree, after its premise); the
module's functions are guards and pass on both trees. A case asserts its premise first: the healthy records alone are answered, and
the reader itself parsed the record (``read_entry`` returns it), so a failure cannot mean the record was never read. The inventory
test reads the router object, not its source.
"""

from __future__ import annotations

import datetime
import json
import logging
import math
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from probos.config import RecordsConfig, SystemConfig
from probos.knowledge.backlinks import KnowledgeBrowserService
from probos.knowledge.provo import project_record_frontmatter
from probos.knowledge.records_store import RecordsStore
from probos.routers.records import router

_HEALTHY = "---\nauthor: alice\nclassification: ship\ntopic: healthy\ntags: [coolant]\n---\n\ncoolant healthy body\n"
_NOTE = "notebooks/alice/ok.md"
_LOG = "captains-log/ok.md"
_BAD_NOTE = "notebooks/alice/case.md"
_BAD_LOG = "captains-log/case.md"
_MARKER = "VALUE-MARKER-917"
_LONE = "\ud800"  # a lone surrogate: a JSON escape gives one to ``json.loads``, a YAML escape to the reader; never write one to a file
_JSON = {"content-type": "application/json"}
_READ = f"/api/records/documents/{_BAD_NOTE}"
_LISTINGS = [
    pytest.param("/api/records/documents", id="documents"),
    pytest.param("/api/records/notebooks/alice", id="notebook"),
    pytest.param("/api/records/captains-log", id="captains-log"),
    pytest.param("/api/records/browse", id="browse"),
    pytest.param("/api/records/search?q=coolant", id="search"),
]

_WRITER = TypeAdapter(Any)  # the call FastAPI makes for a handler annotated ``-> Any``


def _writes(body: Any) -> bool:
    try:
        _WRITER.dump_json(body)
    except (ValueError, RecursionError):  # PydanticSerializationError is a ValueError
        return False
    return True


def _mapping(depth: int) -> Any:
    """What ``_nested(depth)`` parses to: ``depth`` single-key mappings around a leaf."""
    value: Any = 1
    for _ in range(depth):
        value = {"a": value}
    return value


def _read_body(frontmatter: dict[str, Any]) -> dict[str, Any]:
    """The body of the read route: the record itself."""
    return {"path": _BAD_NOTE, "frontmatter": frontmatter}


def _listing_body(frontmatter: dict[str, Any]) -> dict[str, Any]:
    """The body of a listing: the record two levels below the body's top (``{key: [record]}``)."""
    return {"documents": [_read_body(frontmatter)]}


def _first_refused(body_of: Callable[[dict[str, Any]], dict[str, Any]]) -> int:
    """The least nesting at which the writer refuses the body ``body_of`` builds around it, asked of the writer that runs."""
    for depth in range(1, 300):
        if not _writes(body_of({"meta": _mapping(depth)})):
            return depth
    raise AssertionError("premise: the writer wrote every body up to 299 levels deep, so there is no depth stop to derive the depths of this file from")


# The writer's depth stop is pydantic-core's recursion guard, a compiled constant that differs by platform (255, or 99 on Windows): it is asked of the
# writer here and written nowhere as a number. A listing's body holds a record two levels below its top, so it stops two levels sooner.
_READ_LIMIT = _first_refused(_read_body)
_LISTING_LIMIT = _first_refused(_listing_body)
_JUST_BELOW = _LISTING_LIMIT - 5  # written by the read route and by every listing, on any platform
_JUST_OVER = _LISTING_LIMIT + 5  # refused by the read route and by every listing, on any platform
_FAR_OVER = _READ_LIMIT + 50  # refused likewise, and far inside the reader's reach: the reader raised RecursionError at about 490 levels
assert _READ_LIMIT == _LISTING_LIMIT + 2 and _LISTING_LIMIT > 5, "premise: the writer stops a listing's body two levels before the read route's"
assert (
    _writes(_listing_body({"meta": _mapping(_JUST_BELOW)}))
    and not _writes(_read_body({"meta": _mapping(_JUST_OVER)}))
    and not _writes(_read_body({"meta": _mapping(_FAR_OVER)}))
), "premise: each depth the cases use is on the side of the writer's limit that its case needs"

# (the YAML value of one key, a text that must never reach a log line). ``nested-over-limit`` is five levels over a listing's limit, so over the read
# route's too; ``nested-far-over-limit`` is fifty levels over the read route's, a record the reader still parses with room to spare. Each case asserts
# that the reader parsed its record, so a reader that stops sooner fails at a premise line, not at a status. ``lone-surrogate`` is the ASCII YAML
# escape, never a literal one.
_UNWRITABLE = [
    pytest.param("{a: " * _JUST_OVER + _MARKER + "}" * _JUST_OVER, _MARKER, id="nested-over-limit"),
    pytest.param("{a: " * _FAR_OVER + _MARKER + "}" * _FAR_OVER, _MARKER, id="nested-far-over-limit"),
    pytest.param("!!binary //4=", "xff", id="bytes-not-utf-8"),
    pytest.param("&a [*a]", "[...]", id="holds-itself"),
    pytest.param('"\\ud800"', "ud800", id="lone-surrogate"),
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
    ("GET", "/api/records/backlinks/{path:path}"): "holds a record value",
    ("GET", "/api/records/graph"): "holds a record value",
    ("GET", "/api/records/timeline"): "holds a record value",
}
_DRIVEN = {
    ("GET", "/api/records/documents"), ("GET", "/api/records/documents/{path:path}"), ("GET", "/api/records/captains-log"),
    ("GET", "/api/records/notebooks/{callsign}"), ("GET", "/api/records/search"), ("GET", "/api/records/browse"),
    ("GET", "/api/records/graph"), ("GET", "/api/records/backlinks/{path:path}"), ("GET", "/api/records/timeline"),
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
    return _send(store, "GET", url)


def _send(store: RecordsStore, method: str, url: str, **kwargs: Any) -> Any:
    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        config=SystemConfig(), records_store=store, _records_store=store, knowledge_browser=KnowledgeBrowserService(store),
    )
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        return client.request(method, url, **kwargs)


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
async def test_a_record_just_below_the_writers_limit_is_answered_by_every_route(tmp_path, url):
    """Guard: five levels below the depth at which the writer stops a listing's body, the record is answered on the read route and in every listing."""
    store = _make_store(tmp_path, {_NOTE: _HEALTHY, _LOG: _HEALTHY, _BAD_NOTE: _record("meta", _nested(_JUST_BELOW)), _BAD_LOG: _record("meta", _nested(_JUST_BELOW))})
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
    """Guard: ``?format=prov-jsonld`` copies no ``meta`` value, so it is answered where the record itself is not (the one value it copies, ``created``, is the class below)."""
    store = _make_store(tmp_path, {_BAD_NOTE: _record("meta", value)})
    assert await store.read_entry(_BAD_NOTE, reader_id="captain") is not None, "premise: the reader parsed the record"
    response = _get(store, f"{_READ}?format=prov-jsonld")
    assert response.status_code == 200 and set(response.json()) == {"@context", "@graph"}


@pytest.mark.parametrize("url", ["/api/records/backlinks/notebooks/alice/case.md", "/api/records/timeline"])
async def test_the_backlinks_and_the_timeline_answer_a_record_whose_unwritable_value_they_do_not_carry(tmp_path, url):
    """Guard: the backlinks carry a record's tags and topic slug and the timeline its department and day, so a topic that is not text reaches neither body."""
    store = _make_store(tmp_path, {_NOTE: _HEALTHY, _BAD_NOTE: _record("topic", _nested(_FAR_OVER))})
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
        """A listing nests a record two levels below the body's top, so the writer stops two levels sooner there than on the read route: a window around the listing's limit, derived at import, is scanned through the real store."""
        store = _make_store(tmp_path, {_NOTE: _HEALTHY})
        found = None
        for depth in range(_LISTING_LIMIT - 3, _LISTING_LIMIT + 3):
            (store.repo_path / _BAD_NOTE).write_text(_record("meta", _nested(depth)), encoding="utf-8")
            entry = await store.read_entry(_BAD_NOTE, reader_id="captain")
            if not _writes(_listing_body(entry["frontmatter"])):
                found = depth
                break
        assert found == _LISTING_LIMIT and _writes(entry), "premise: the first depth at which a listing's body is refused is the derived limit, and the read route's body still writes there"
        assert _get(store, _READ).status_code == 200, "premise: the read route answers the record"
        response = _get(store, "/api/records/documents")
        assert response.status_code == 200
        assert [item["path"] for item in _items(response)] == [_NOTE]

    async def test_the_captains_log_limit_counts_the_records_it_returns(self, tmp_path):
        def entry(created: str, extra: str = "") -> str:
            return f"---\nauthor: captain\nclassification: ship\ncreated: '{created}'\n{extra}---\n\nentry body\n"

        store = _make_store(tmp_path, {
            "captains-log/a.md": entry("2026-01-01"), "captains-log/b.md": entry("2026-02-01"),
            "captains-log/c.md": entry("2026-03-01", f"meta: {_nested(_FAR_OVER)}\n"),
        })
        healthy = _make_store(tmp_path / "healthy", {"captains-log/a.md": entry("2026-01-01"), "captains-log/b.md": entry("2026-02-01")})
        assert [item["path"] for item in _items(_get(healthy, "/api/records/captains-log?limit=1"))] == ["captains-log/b.md"], "premise: b is the newest healthy entry"
        assert await store.read_entry("captains-log/c.md", reader_id="captain") is not None, "premise: the reader parsed the newest entry"
        response = _get(store, "/api/records/captains-log?limit=1")
        assert response.status_code == 200
        assert [item["path"] for item in _items(response)] == ["captains-log/b.md"]

    @pytest.mark.parametrize(("value", "marker"), [_UNWRITABLE[1], _UNWRITABLE[2], _UNWRITABLE[4]])
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

    @pytest.mark.parametrize(
        ("field", "url", "message", "code"),
        [
            pytest.param("tags", f"/api/records/backlinks/{_BAD_NOTE}", "backlink lookup failed", "knowledge_browser.backlinks_failed", id="tags-backlinks"),
            pytest.param("department", "/api/records/timeline", "timeline assembly failed", "knowledge_browser.timeline_failed", id="department-timeline"),
        ],
    )
    async def test_a_note_the_notebook_route_accepts_is_answered_by_the_backlinks_and_the_timeline_with_their_own_envelope(self, tmp_path, caplog, field, url, message, code):
        store = _make_store(tmp_path, {})
        write = "/api/records/notebooks/alice"
        healthy = {"topic": "ok", "content": "coolant healthy body", "tags": ["coolant"], "department": "science"}
        assert _send(store, "POST", write, content=json.dumps(healthy), headers=_JSON).status_code == 200, "premise: the notebook route writes a healthy note"
        control = f"/api/records/backlinks/{_NOTE}" if field == "tags" else url
        assert _get(store, control).status_code == 200, "premise: the healthy note alone is answered"
        poisoned = {"topic": "case", "content": "coolant case body", field: [_LONE] if field == "tags" else _LONE}
        posted = _send(store, "POST", write, content=json.dumps(poisoned), headers=_JSON)
        assert posted.status_code == 200 and posted.json() == {"path": _BAD_NOTE, "status": "written"}, "premise: the notebook route accepts the note"
        entry = await store.read_entry(_BAD_NOTE, reader_id="captain")
        assert entry is not None and entry["frontmatter"][field] in (_LONE, [_LONE]), "premise: the reader gives the lone surrogate back"
        service = KnowledgeBrowserService(store)
        body = await (service.get_backlinks(_BAD_NOTE) if field == "tags" else service.get_timeline())
        assert not _writes(body), "premise: the body this route builds is one the writer refuses"
        with caplog.at_level(logging.WARNING, logger="probos.routers.records"):
            response = _get(store, url)
        assert response.headers["content-type"].startswith("application/json")
        assert response.status_code == 500
        assert response.json() == {"error": message, "availability": {"state": "failed", "code": code, "message": message, "retryable": True}}
        assert "returning HTTP 500" in caplog.text and "ud800" not in caplog.text

    async def test_the_provenance_projection_of_a_created_the_writer_cannot_write_is_answered_with_the_controlled_503(self, tmp_path, caplog):
        created = '"2026-11-09\\ud80001:02:03"'  # datetime.fromisoformat takes any one character between the date and the time, a lone surrogate included
        store = _make_store(tmp_path, {_NOTE: _HEALTHY, _BAD_NOTE: _record("created", created)})
        entry = await store.read_entry(_BAD_NOTE, reader_id="captain")
        assert entry is not None and entry["frontmatter"]["created"] == "2026-11-09\ud80001:02:03", "premise: the reader parsed the record"
        assert not _writes(project_record_frontmatter(_BAD_NOTE, entry["frontmatter"])), "premise: the projection of this record is one the writer refuses"
        assert _get(store, f"/api/records/documents/{_NOTE}?format=prov-jsonld").status_code == 200, "premise: a healthy record's projection is answered"
        with caplog.at_level(logging.WARNING, logger="probos.routers.records"):
            response = _get(store, f"{_READ}?format=prov-jsonld")
        assert response.status_code == 503
        assert response.json() == {
            "error": "Record document unavailable",
            "availability": {"state": "unavailable", "code": "records.read_failed", "message": "Record document unavailable", "retryable": True},
        }
        assert "returning HTTP 503" in caplog.text and "ud800" not in caplog.text
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
    500. The check covers both bodies: the PROV-O projection copies a ``created`` that
    parses as ISO-8601 verbatim, and ``datetime.fromisoformat`` accepts any one
    character between the date and the time, a lone surrogate included.
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
    body = entry
    if format == _PROV_JSONLD_FORMAT:
        body = project_record_frontmatter(
            entry.get("path") or path, entry.get("frontmatter") or {}
        )
    if not _writes(body):  # BF-940 slice 3 (F7-1): the body, a record or its projection, is written after this returns; a body the writer cannot write is answered here
        logger.warning("Records document serialisation failed; document unavailable; returning HTTP 503")
        return _read_failure("Record document unavailable", "records.read_failed", 503)
    return body
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

**P2-11.** `src/probos/routers/records.py`, `get_backlinks` (the three lines occur once; the other two `return result` blocks name other failures):
SEARCH:
```
    if result is None:
        return _read_failure("Not found in index", "knowledge_browser.not_found", 404)
    return result
```
REPLACE:
```
    if result is None:
        return _read_failure("Not found in index", "knowledge_browser.not_found", 404)
    if not _writes(result):  # BF-940 slice 3 (F7-1): a reference carries a tag or a topic slug, frontmatter values, written after this returns
        logger.warning("Knowledge Browser backlinks cannot be written as JSON; results unavailable; returning HTTP 500")
        return _read_failure("backlink lookup failed", "knowledge_browser.backlinks_failed")
    return result
```

**P2-12.** `src/probos/routers/records.py`, `get_records_timeline` (the three lines occur once; the other two `return result` blocks name other failures):
SEARCH:
```
    if result is None:
        return _read_failure("timeline assembly failed", "knowledge_browser.timeline_failed")
    return result
```
REPLACE:
```
    if result is None:
        return _read_failure("timeline assembly failed", "knowledge_browser.timeline_failed")
    if not _writes(result):  # BF-940 slice 3 (F7-1): a bucket's day and its department keys are frontmatter values, written after this returns
        logger.warning("Knowledge Browser timeline cannot be written as JSON; results unavailable; returning HTTP 500")
        return _read_failure("timeline assembly failed", "knowledge_browser.timeline_failed")
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
- **Base.** FastAPI writes what a handler returns as JSON after the handler has returned, outside its `try`, so a record the reader parsed but the writer cannot write (a mapping nested past the writer's recursion guard, a compiled constant that differs by platform: 97 or more levels deep on Windows and 253 or more on Linux with the locked FastAPI and pydantic; bytes that are not UTF-8; a lone surrogate, which the notebook route accepts as a tag or a department; a value that holds itself) was an unhandled HTTP 500 on `GET /api/records/documents/{path}`, on its `?format=prov-jsonld` projection (a `created` with a lone surrogate between the date and the time) and on every route that returns a frontmatter value: the documents, notebook and captain's-log listings, the browse, the search (a listing fails two levels sooner: from 95 on Windows, 251 on Linux), the graph, through a node's label or department, the backlinks, through a tag or a topic, and the timeline, through a department. One such record, made by hand, by the notebook route or by `write_notebook(metrics=...)`, took every listing that held it down.
- **Fix.** `routers/records.py` asks the writer FastAPI itself calls (`TypeAdapter(Any).dump_json`) whether it can write the body, before the handler returns, and returns its own body when it can: every answered body is byte-identical to before. The read route answers a record it cannot write, or a projection it cannot write, with the existing 503 `records.read_failed`; a listing leaves that record out, logs its path (never a value) and lists the rest; the graph, the backlinks and the timeline answer their own existing `graph_failed`, `backlinks_failed` and `timeline_failed` envelopes (500, JSON). The two POST routes, stats and history are unchanged; the write side's own unhandled 500s for a lone surrogate are recorded, not fixed (L13 of the contract). Contract `prompts/bf-940-records-route-serialisation.md`. Refs #1686: this closes its F7-1 box; the issue stays open for L19, the last box.

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

- *Scope.* `routers/records.py` (one check of the JSON writer, used by the nine handlers whose body holds a record value and by the projection of the read route), tests. Contract `prompts/bf-940-records-route-serialisation.md`. Slice 3 of #1686.
- *G0 (scope).* The read route and every other handler of the module whose body holds a frontmatter (found by a run and by a review: the documents, notebook and captain's-log listings, the browse, the search, the graph, the backlinks and the timeline; the projection of the read route too); L19, the last box, stays in #1686, which stays open (`Refs`). Rejected: the read route alone; the read route and three listings (the browse, the search and the graph share the defect); an application-wide handler (it changes the failure of every route and cannot name a route's own envelope).
- *G1 (the mechanism).* Ask `TypeAdapter(Any).dump_json`, the call FastAPI 0.136.1 makes for a `-> Any` handler, before the handler returns, and return the handler's own body. This replaces slice 2's G3 (`dump_python(mode="json")`, returning its result): returning a converted object fails two AD-1145 tests, which assert the handler returns the store's entry itself, and `jsonable_encoder` writes a UTC datetime as `+00:00` and refuses `nan`.
- *G2 (a listing).* A record the writer cannot write is left out and logged by path, never by value; the rest is listed, as `list_entries` already skips a record it cannot read. Decided by the Architect: none of the six conditions under which the Captain decides is met (nothing stored changes, no control is weakened, no key or client contract changes, nothing is spent or moved, the risk is Low). Ranked below: failing the whole listing with the 503 (one record hides every other, and a note any client can write keeps the listings down), the ranked overrule option; listing the record without its frontmatter (a new item shape). Considered and not taken: an additive `skipped` field.
- *G3 (the envelope).* The existing `records.read_failed` 503 and its message, no new code; the graph keeps `knowledge_browser.graph_failed`.
- *G4 (the write side).* The notebook and Captain's-log POST routes answer an unhandled 500 for a lone surrogate in some request fields (a classification, a topic on Windows, a content); not a record the reader parsed, recorded for the follow-up issue, not fixed here (L13 of the contract).
- *Residual.* L1 to L13 of the contract. *Reversal.* Revert the BF-940 slice 3 commits.
```

**Ledger.** Run G3. The roadmap Bug Tracker and the documents are not edited (no document states these routes' failure behaviour: `git grep -n -F "records.read_failed" -- docs` finds nothing).

### 7.4 The census (an orchestrator step; no repository file)

I have no live system. Run on a read-only copy of the vessel's `ship-records` (the path from the live process, `%LOCALAPPDATA%\ProbOS\data`, never `d:\ProbOS\data`), with the build tree first on `PYTHONPATH`: `$env:PYTHONPATH = '<build tree>\src'; PY -B -P census_bf940_s3.py <copy>`. It lists documents as the routes do (`RecordsStore.list_entries`), reads each as the read route does (`read_entry` as the Captain), asks the JSON writer FastAPI uses (`TypeAdapter(Any).dump_json`) whether it can write the read route's body and a listing's body, and also counts the structural reasons (more than 90 levels with the frontmatter as level 1, a structural proxy chosen under the lowest limit measured, a listing's 95 on Windows, so it also flags what a higher limit still writes; bytes that are not UTF-8, a container that holds itself) so the two comparisons can be read against each other. A document the reader could not parse is not listed and not counted. It prints paths, flag names, counts and the FastAPI and pydantic versions, **never a value**; the constructor of the store writes nothing and `initialize()` is never called. Exit 0: nothing flagged. 1: flags (read each; `READ_500` is a record the read route answered with an unhandled 500 before this slice, `LISTING_500` one that took every listing down). 2: the positive control was not flagged, or bad arguments (do not trust the run). The positive control is five documents in a temporary folder walked by the same `census` function: a 300-level nesting (over every platform's writer limit and inside the reader's reach), non-UTF-8 bytes and a self-referencing list, which must be flagged as named, and a 60-level nesting and a plain document, which must not. Run on synthetic trees on Windows (A1 moved the control from 120 to 300 levels: with a stand-in writer of the Linux limit the old control exits 2 and the new one passes): a clean tree exits 0; a tree holding a 300-level, a bytes, a 96-level and a 92-level record exits 1 and flags the first two with both writer flags (and `DEEP` or `BYTES_NOT_UTF8`), the 96-level one with `LISTING_500` and `DEEP` and the 92-level one by `DEEP` alone (a structural proxy the writer does not confirm; with the Linux limit the 96-level one is `DEEP` alone too); a missing folder exits 2; the tree is left as found. The results of a run on a vessel's data are not recorded in this repository.

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


# 300 levels: over the writer's limit on any platform (the read route's body stops at 253 at the most) and inside the reader's reach (it stops at about 490)
CONTROL = {
    "notebooks/alice/deep.md": ("meta: " + "{a: " * 300 + "1" + "}" * 300, {"READ_500", "LISTING_500", "DEEP"}),
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
    print("control: a 300-level nesting, non-UTF-8 bytes and a self-referencing list flagged, a 60-level nesting and a plain document not")
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

`read_entry`, `list_entries`, `RecordsStore.search`, `_parse_document`, the classification gate of `read_entry` (it runs before the check), the AD-1145 projection (`knowledge/provo.py` and its handling of `created` are not changed; the check judges its body), every other failure envelope of the module, the two POST routes (L13), stats, history, `knowledge/backlinks.py` (a node's label, a reference's target and a bucket's department stay whatever the frontmatter holds), `routers/gaps.py` (L8), the sort in `get_captains_log` (L9), the HXI, config, dependencies (`pydantic` is one: `pyproject.toml:25`), the AD-1344, AD-1346 and BF-892 inventories (no write site is added or moved), and every document on disk.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

All rows are in `src/probos/routers/records.py`. Cases are in `TestARecordTheReaderParsedIsAnsweredByEveryRoute`; ids are as my hand driver forms them (the nearest decorator's id first, as pytest does). `LISTING` = `test_a_listing_leaves_out_a_record_the_writer_cannot_write_and_keeps_the_rest` (25 cases: `<value>-<route>`, values `nested-over-limit`, `nested-far-over-limit`, `bytes-not-utf-8`, `holds-itself`, `lone-surrogate`, routes `documents`, `notebook`, `captains-log`, `browse`, `search`), `READ` = `test_the_read_route_answers_a_record_the_writer_cannot_write_with_the_controlled_503` (5 cases: the five values), `WINDOW` = `test_a_record_the_read_route_can_write_is_left_out_of_a_listing_two_levels_deeper`, `LIMIT` = `test_the_captains_log_limit_counts_the_records_it_returns`, `GRAPH` = `test_the_graph_answers_a_record_whose_topic_the_writer_cannot_write_with_its_own_envelope` (3 cases: `nested-far-over-limit`, `bytes-not-utf-8`, `lone-surrogate`), `NOTE` = `test_a_note_the_notebook_route_accepts_is_answered_by_the_backlinks_and_the_timeline_with_their_own_envelope` (2 cases: `tags-backlinks`, `department-timeline`), `PROJECTION` = `test_the_provenance_projection_of_a_created_the_writer_cannot_write_is_answered_with_the_controlled_503`, `PROV` = the guard `test_the_provenance_projection_of_a_record_the_writer_cannot_write_is_still_answered` (5 cases, one per value).

| # | M | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| 1 | M2 | `return False` | `return True` | READ (5), LISTING (25), WINDOW, LIMIT, GRAPH (3), NOTE (2), PROJECTION: the check is inert |
| 2 | M2 | `except (ValueError, RecursionError):` | `except RecursionError:` | READ (5), LISTING (25), WINDOW, LIMIT, GRAPH (3), NOTE (2), PROJECTION: the writer's `ValueError` escapes the handler |
| 3 | M2 | `if not _writes(body):  # BF-940 slice 3 (F7-1): the body, a record or its projection, is written after this returns; a body the writer cannot write is answered here` | `if False:  # BF-940 slice 3 (F7-1): the body, a record or its projection, is written after this returns; a body the writer cannot write is answered here` | READ (5), PROJECTION |
| 4 | M2 | `if _writes({key: records}):` | `if True:` | LISTING (25), WINDOW, LIMIT |
| 5 | M2 | `if _writes({key: [record]}):` | `if _writes(record):` | WINDOW (the record tried outside the depth it has in the body) |
| 6 | M2 | `entries = _writable(entries, "documents", "Records listing")  # BF-940 slice 3 (F7-1)` | `pass  # BF-940 slice 3 (F7-1)` | LISTING[nested-over-limit-documents, nested-far-over-limit-documents, bytes-not-utf-8-documents, holds-itself-documents, lone-surrogate-documents], WINDOW |
| 7 | M2 | `entries = _writable(entries, "entries", "Notebook listing")  # BF-940 slice 3 (F7-1)` | `pass  # BF-940 slice 3 (F7-1)` | LISTING[nested-over-limit-notebook, nested-far-over-limit-notebook, bytes-not-utf-8-notebook, holds-itself-notebook, lone-surrogate-notebook] |
| 8 | M2 | `entries = _writable(entries, "entries", "Captain's log")  # BF-940 slice 3 (F7-1): before the limit, so the limit counts records it returns` | `pass  # BF-940 slice 3 (F7-1)` | LISTING[nested-over-limit-captains-log, nested-far-over-limit-captains-log, bytes-not-utf-8-captains-log, holds-itself-captains-log, lone-surrogate-captains-log], LIMIT |
| 9 | M2 | `results = _writable(results, "results", "Records search")  # BF-940 slice 3 (F7-1)` | `pass  # BF-940 slice 3 (F7-1)` | LISTING[nested-over-limit-search, nested-far-over-limit-search, bytes-not-utf-8-search, holds-itself-search, lone-surrogate-search] |
| 10 | M2 | `filtered = _writable(filtered, "documents", "Records browse")  # BF-940 slice 3 (F7-1)` | `pass  # BF-940 slice 3 (F7-1)` | LISTING[nested-over-limit-browse, nested-far-over-limit-browse, bytes-not-utf-8-browse, holds-itself-browse, lone-surrogate-browse] |
| 11 | M2 | `if not _writes(result):  # BF-940 slice 3 (F7-1): a node's label is a frontmatter value, written after this returns` | `if False:  # BF-940 slice 3 (F7-1): a node's label is a frontmatter value, written after this returns` | GRAPH (3) |
| 12 | M2 | `route, len(left_out), [record.get("path") for record in left_out[:5]],` | `route, len(left_out), left_out[:5],` | LISTING (25): a record's value reaches the log (the marker of each value is in its `repr`) |
| 13 | M2 | `if not _writes(result):  # BF-940 slice 3 (F7-1): a reference carries a tag or a topic slug, frontmatter values, written after this returns` | `if False:  # BF-940 slice 3 (F7-1): a reference carries a tag or a topic slug, frontmatter values, written after this returns` | NOTE[tags-backlinks] |
| 14 | M2 | `if not _writes(result):  # BF-940 slice 3 (F7-1): a bucket's day and its department keys are frontmatter values, written after this returns` | `if False:  # BF-940 slice 3 (F7-1): a bucket's day and its department keys are frontmatter values, written after this returns` | NOTE[department-timeline] |
| 15 | M2 | `body = project_record_frontmatter(` | `return project_record_frontmatter(` | PROJECTION: the projection returns before the check |
| 16 | M2 | `if not _writes(body):  # BF-940 slice 3 (F7-1): the body, a record or its projection, is written after this returns; a body the writer cannot write is answered here` | `if not _writes(entry):  # BF-940 slice 3 (F7-1): the body, a record or its projection, is written after this returns; a body the writer cannot write is answered here` | PROV (5): the projection is judged by the record it was made from, so a projection that writes is refused when the record's `meta` is not; the five guards pass on both trees and fail here |

**Campaign** (before A1: my hand driver, in memory, one mutant at a time over the exact files below; not the orchestrator's tool run, and the orchestrator's campaign of record, if it runs one, replaces it): baseline 43 cases pass; each mutant failed exactly the cases its row then listed (counts 28, 28, 4, 22, 1, 5, 4, 5, 4, 4, 2, 20 for rows 1 to 12 of the first version of this table), none outside them; no mutant survived. **After A1 no campaign was run**: the table above has 16 rows over a file of 54 cases, and its counts are those of an in-memory matrix of route answers (M-11) that evaluates, for each case, the answers its asserts compare, on the unfixed base, on the candidate before A1 and on the amended router and each mutant of it: the base fails the 38 class cases and passes the 16 guards; the candidate fails T12 twice and T13; the amended router fails none; the mutants fail the cases of their rows (38, 38, 6, 27, 1, 6, 5, 6, 5, 5, 3, 25, 1, 1, 1 class cases and, for row 16, five guards). A run on the amended files replaces these counts. Files (sha256 of the LF text) before A1: `routers/records.py` at M2's head (the ten pairs applied to the base blob) `ef39caed9a1cef0fe5902379fba1a3fca72cdb1750e09041230ef139cf1ef158`; `tests/test_bf940_s3_route_serialisation.py` as N1-1 gave it `8db87db1b3eacdcda0ff6b5d1c13025f0c2784692ef6d18a7600087dda62e6c4` and at M2's head, N2-1 applied, `45e51a4012c1599468dc72dbd7e4251d2fbc1145351a609af84802c44f6e6a8f` (my driver ignored the marker, so that campaign ran with it present: the cases are the same). After A1 (the real apply tool, in-process, on throwaway copies): `routers/records.py` at M2's head (the twelve pairs applied to the base blob) `7ade640e45d4ebd509f4ae60f2dd5fd6b2d443d6a49d5c2dcd50c684d7771f84`; the test file as N1-1 gives it `8ed8455fd1c85d12709950593090a3f3f4944bfba550725925f05231a18a5f10` and at M2's head, N2-1 applied, `66c4b6508e86a0786b0cbf24c1dc09a6b35da4b2c5af762e241874a22271e1b3`; the census script of 7.4 `378970b63402b30e620074b0470c7876277e23dd1a11218a4b3efe7fa927af9b`. A run of rows 1 to 16 on the post-A1 files becomes the campaign of record when it is marked here with its base tree and these hashes; a Builder whose files match those hashes does not repeat it. Rows 1 and 2 kill the same cases through different lines (the return value and the exception class). Not tabulated, for the cap: `[:5]` to `[:50]` (an equivalent mutant: the tests leave out at most two records) and `return records` to `return list(records)` (equivalent: no test asserts identity of the list).

## 10. Recorded limits

- **L1.** Nothing here is a live-system claim: I have no vessel and read no real `ship-records`. 7.4 is the census to run; its results are not recorded in this repository, and a record written after a run is not covered by it.
- **L2.** Every measurement of mine is on Windows, Python 3.12.13, FastAPI 0.136.1, Starlette 1.0.0, pydantic 2.12.5, pydantic_core 2.41.5 and PyYAML 6.0.3 with libyaml; the lock pins FastAPI, pydantic and pydantic-core to these (`uv.lock:904-905, 3099-3100, 3114-3115`), while `pyproject.toml:50` allows `fastapi>=0.115`. The first failing depths (97 and 95) are for these versions on Windows; on Linux the same versions fail at 253 and 251 (M-10). The writer's depth limit is a compiled constant of pydantic-core that is not ours to pin, so the tests derive it from the writer that runs (an import-time probe in N1-1) and pin no number.
- **L3.** The check is the call FastAPI 0.136.1 makes. On a FastAPI that writes another way the check and the later write can differ at the margin (not measured): a failure the check misses stays an unhandled 500 as before, and a body the check refuses that FastAPI would write becomes a 503 or is left out.
- **L4.** Cost: one more pass of the writer over each answered body (a listing: one pass over the whole body, and one more per record only when that pass fails). I ran no timing (a rule of this consult); the diff reviewer may time it, as slice 2's L7 did for its writer.
- **L5.** A record left out of a listing is not reported to the client: the body does not say so, `count` is the number of items returned, and the signal is the log line (WARNING, the count and at most five paths), repeated on every request while the record exists (Knowledge Browser polls); a monitor that counts 5xx responses no longer sees the record, a log-based alert does. The record's own read answers 503 `records.read_failed`, `RecordsStore.list_entries` (the Python side, the `strict=True` callers included) still lists it (M-9), and it stays on disk and in git; the base already left out a record the reader cannot parse with no signal at all. Decided by the Architect, not a Captain decision (D2: none of the six conditions is met). Considered and not taken: an additive `skipped` field on the five listings, present only when a record is left out, as a count and paths or as a count only. Run (M-9): it keeps every existing key and every ordinary body byte-identical, the existing route tests pass as on the base, and the pre-A1 file passed 27 of 43 (the 16 whole-body comparisons of T8 would have to ignore the field; 34 of 54 after A1, by construction: 20 comparisons, four listings by five values); the HXI reads named keys and its browse validator ignores unknown ones (`useStore.ts:116-118`), so it would see nothing; the graph is unchanged (it fails whole). It adds a public key no client reads and a body with two shapes, and it must not be named `availability` (`classifyResourceResponse` treats a body holding a valid one as a failure before it reads the status, `resourceState.ts:76-78`). It is the available narrowing if a later reader judges the silent omission to need a signal.
- **L6.** The search scores a record before the route leaves it out, so its rarity counts that record; the others' scores are the search's own, not recomputed, and the search can return 19. The listings and the browse are not ranked.
- **L7.** One record whose `topic` or `topic_slug` the writer cannot write fails the whole graph with `graph_failed` (500) rather than leaving a node out (an edge would dangle). The alternative, a text label in `KnowledgeBrowserService.get_graph` (`backlinks.py:380`), changes a knowledge-layer payload for a non-text label and is not taken. The graph's other node fields are text or numbers by reading, not run.
- **L8.** Outside this module, `routers/gaps.py` `list_gaps` copies frontmatter values into its body (`gaps.py:35-39`; read, not run): it meets the same step for a hand-made gap report. Not in the box.
- **L9.** A different 500 of the same family, older and untouched: `get_captains_log` sorts by `created` (`records.py:124`) and raises `TypeError` for a `created` that is a YAML date beside one that is text; measured on the base and on M2's head, an unhandled 500 either way.
- **L10.** Not examined: an alias expansion whose JSON is very large. The reader and the route had no bound before; the check adds a second pass over it. This slice bounds neither.
- **L11.** Not measured by me: pytest, xfail semantics, `-n 16`, G1 to G3, the broad gate, the architecture check, vitest. Every count of mine is from my hand driver, a stand-in for the pytest features the files use, which ignores `conftest.py`. `test_issue1368_readiness.py`: 122 cases, 119 pass and 3 (`test_integration_nats_requires_current_connection`) stop at a fixture the driver does not provide, on the base and on M2's head alike. The BF-949 source-scan tests were run on a temporary copy of `src/probos` holding M2's router. Only the AD-1145 file was run under the rejected mechanisms.
- **L12.** The listings are not reader-scoped (`list_entries`; slice 2's D6) and the read route's classification gate runs before the check, so leaving a record out or answering its 503 changes no privacy or audit control. The statements about the HXI are from reading `useStore.ts` and `resourceState.ts`, not from running it.
- **L13.** The write side is not in this box and answers its own unhandled 500s for a lone surrogate, on the base and after this slice alike (recorded for the follow-up issue, not fixed here; M-11): `POST /api/records/notebooks/{callsign}` with a `classification` that is one (`write_entry` raises `ValueError("Invalid classification: <it>")` and the route's `except ValueError` answers `JSONResponse({"error": str(e)})`, which cannot encode it); the same route with a `topic` that is one (the topic is also the file name: on Windows the file is written and the response's `path` then cannot be written, and the file stays; on Linux the write raises and the route answers 400); and `POST /api/records/captains-log` with a `content` that is one (the append raises `UnicodeEncodeError`, which the route does not catch). A `tags` or a `department` that is one is accepted and written as an escape: that is the ordinary reach this slice closes at the backlinks and the timeline. The file that stays on Windows is a record whose path the writer cannot write: after this slice the listings that reach it leave it out and log its path, and the graph and the backlinks of a note whose answer lists it answer their own 500 envelope until it is removed (M-11). The shape of a fix belongs to the write side: refuse a surrogate in request text before it is echoed or written.

## 11. Verified Against Codebase (2026-11-11, reading tree `D:\ProbOS-worktrees\bf940s2-build` at `e327d26e`)

Hand-driver results (Windows, Python 3.12.13, FastAPI 0.136.1, Starlette 1.0.0, pydantic 2.12.5, pydantic_core 2.41.5, PyYAML 6.0.3 with libyaml), each one in-memory script, a fresh temporary store per case, `~` moved, no `initialize()`, `TestClient(raise_server_exceptions=False)`; `n` is the number of single-key flow mappings `{a: {a: ... 1}}` under one frontmatter key:

- **M-1 (the matrix, Windows).** Premises asserted: the healthy records alone answer 200 on every listing, the listings hold exactly them and the graph has two nodes; the reader's own `read_entry` parsed each case's value except n = 600. Base: n = 90 is 200 on all ten GET routes. n = 100, n = 450, `!!binary //4=` (as `meta`) and `&a [*a]`: read 500; documents, notebook, captain's log, search, browse 500; `?format=prov-jsonld`, backlinks, timeline 200; graph 200 (the value is not a label). As `topic` (n = 450 and the bytes): the same, and the graph 500. n = 600: read 503 and prov 503 (the reader's `RecursionError`), the listings 200 without the record, backlinks 404. Variant C (the ten pairs): the read route 503 `records.read_failed` and each of the five listings 200 without the record for every row above, the graph 500 `knowledge_browser.graph_failed` as JSON for the two `topic` rows, everything else as the base. A (the read route only), B (the read route and three listings) and a fail-whole variant (each listing 503) and an application-level handler variant were driven the same way: the cells of D0 and D2.
- **M-2 (the writer, Windows; the Linux values are M-10).** `dump_json`, `dump_python(mode="json")` and `to_jsonable_python`: first failing n = 97 for the read route's body and 95 for a listing's, exception `PydanticSerializationError` for `dump_json` and `ValueError` for the others; non-UTF-8 bytes: `PydanticSerializationError` and `UnicodeDecodeError`. `jsonable_encoder`: `RecursionError` near n = 991 to 993, not monotone within four depths. `json.dumps(allow_nan=False)`: no failure to n = 2560. Through the real route the first failing n is 97 (read) and 95 (listing): n = 95 and 96 are the window. Shapes (`dump_json` / `dump_python` / `jsonable_encoder`): a UTC datetime `...Z` / `...Z` / `...+00:00`; a set a list in all three; UTF-8 bytes text; an int key `"1"` / `"1"` / `1`; `nan` and `inf` `null` / `None` / `nan`; an arbitrary object refused. 16 shapes built by `yaml.safe_load` (bytes UTF-8 and not, as value and as key; `None`, bool, float, `nan`, date and datetime keys; an int beyond 64 bits as value and key; an `!!omap` product; a set of ints; `inf`; an alias used twice): only non-UTF-8 bytes (value or key) refused; a self-referencing list refused (`PydanticSerializationError`).
- **M-3 (bytes, Windows).** Status and the first ten hex digits of the SHA-256 of the response body for the six-shape record and a 90-level record on `read`, `read90`, `list`, `notebook`, `captlog`, `browse`, `search`, `backlinks`, `timeline` (the graph by status): equal to the base's for C, for A, B and the fail-whole and application-handler variants, and for the read-route-only `convert` and `Response` variants; the base is stable across two runs. `jenc` answers the shapes record 503.
- **M-4 (mechanisms, read route).** AD-1145's seven `read_record` tests: 7 pass on the base and on C; 5 pass and 2 fail (`assert result is entry`, `tests/test_ad1145_provo_projection.py:583` and `:595`) under `dump_python` returned as the body, under `Response(dump_json(entry))` and under `JSONResponse(jsonable_encoder(entry))`.
- **M-5 (existing tests, hand driver, base against C).** The four AD-562 endpoint files 15 of 15 pass on both; `test_ad1145_provo_projection.py` `read_record` tests 7 of 7; `test_issue1368_readiness.py` 119 of 122 on both (L11); `test_bf949_notebook_reader_identity.py` route tests 2 of 2; `test_bf952_records_keyword_search.py` `test_the_records_search_route_confines_a_search_to_a_directory` 1 of 1; `test_bf940_s2_writer_policy.py` notebook-route tests 3 of 3. BF-949's two source-scan tests (`test_the_census_finds_the_four_records_search_callers`, `test_every_records_search_caller_in_src_passes_a_reader`) pass on the reading tree and on a temporary copy of `src/probos` whose `routers/records.py` is C.
- **M-6 (a writer-made record, Windows).** `write_notebook("alice", ..., metrics={"k": b"\xff\xfe"})` and `metrics={"k": <150-level mapping>}` write and read; base: read 500 for each, the listing 500 (it holds them) and a healthy note's read 200; C: read 503 for each, the listing 200 with them left out, the healthy note 200.
- **M-7 (classes).** `issubclass(pydantic_core.PydanticSerializationError, ValueError)` is `True`; `issubclass(RecursionError, ValueError)` is `False`. `get_captains_log` with a YAML date and a text `created`: the handler raises `TypeError` on the base and on C (L9). `router.routes` holds 13 routes, methods `GET` and `POST`, on both.
- **M-8 (the census).** The positive control, a clean tree, a mixed tree (7.4) and a missing folder, as 7.4 states; the script's SHA-256 (LF text) is `378970b63402b30e620074b0470c7876277e23dd1a11218a4b3efe7fa927af9b` after A1 (`d297bb3e58b091f9899237f9b17cde5bbe68b4af5bef48e692eaf1265aa8f1b8` before it: its control was a 120-level record, a Windows value; with a stand-in writer of the Linux limit that control exits 2 and the new one passes).
- **M-9 (the D2 follow-up; hand driver, Windows, Python 3.12.13, FastAPI 0.136.1; a fresh temporary store per case, `~` moved, no `initialize()`).** A note written through the product's own route, `POST /api/records/notebooks/alice` with `tags` nested 100 levels (the route answered 200 `written` on every tree and the reader parsed the note): on the base the documents, notebook, browse and search listings answer 500 and the read of the note 500 (`GET /captains-log` is 200: the note is not under `captains-log/`); on C (leave the record out) the four listings answer 200 without the note and its read 503 `records.read_failed`; under the fail-whole variant the four listings and the read answer 503; on all three `RecordsStore.list_entries()` and `list_entries("notebooks", strict=True)` still hold the note. The additive-field candidate (`skipped`, as `{"count", "paths"}` or as a count, only when a record is left out), built in memory over C: the read route and the five listings for the six-shape record and a 90-level record have the base's status and bytes; with a record left out each listing keeps its keys and gains `skipped` (browse keeps `filters_applied`, notebook `callsign`, search `query`, `count` where it had one); the existing route tests pass as on the base (readiness 119 of 122, AD-562 browse 4 of 4 and graph 5 of 5, BF-949 route 2 of 2, BF-952 route 1 of 1); the pre-A1 file passed 27 of 43 under either form (16 of T8's cases, the whole-body comparisons of documents, notebook, captain's log and browse, failed; 34 of 54 after A1, by construction). The fail-whole variant against the pre-A1 file: 21 of 43 passed (T8's 20 cases, T9 and T10 failed; 27 of 54 after A1, by construction).
- **M-10 (the platform; measured by a probe and a scratch run on ubuntu-latest, run 43002335981, Python 3.12.16, and by my read of pydantic-core's source at tag v2.41.5).** The same locked versions (pydantic 2.12.5, pydantic_core 2.41.5, FastAPI 0.136.1, PyYAML 6.0.3) on two platforms, through a real `RecordsStore` and `TypeAdapter(Any).dump_json`: the read route's body first fails at n = 97 on Windows (Python 3.12.13) and at 253 on Linux, a listing's at 95 and 251, and the reader (pure-Python PyYAML) raises `RecursionError` at n = 491 on both. The writer's stop is `RECURSION_GUARD_LIMIT` in `src/recursion_guard.rs` (read): 255, 99 on Windows or PyPy, 49 on wasm or Windows PyPy, 20 less in a debug build; 253 less 97 is 156, which is 255 less 99, and on both platforms the first failing n is that limit less 2 for the read body and less 4 for a listing's (the leaf counts as a level). Before A1 the new file's fixed depths (100 and 90 levels, and a scan of 60 to 139) were Windows values: a scratch run of the G2 set on ubuntu-latest failed exactly seven cases of the new file (the read-route case and the five listing cases at 100 levels, and the window case) and passed the other 503 tests; the cases at 450 levels passed. After A1 the file asks its own writer at import: 97, 95, 90, 100 and 147 on Windows (the real writer), and 253, 251, 246, 256 and 303 with a stand-in writer of the Linux limit (the stand-in gives 97 and 95 for the Windows limit and 253 and 251 for 255, as measured); a writer that never refuses, or refuses at once, fails the import at its own premise. The reader's room at 450 levels was thin (in a scratch run it parsed 450 levels with up to 72 more frames on the stack than the script's own, and 300 levels with up to 372), so the far-over case is the read route's limit plus fifty.
- **M-11 (A1: review round 1, reproduced; my in-memory runs on Windows, Python 3.12.13; a sweep on Windows and on ubuntu-latest, run 43006764667).** F1: the notebook route accepts a lone surrogate as a tag or a department (a JSON escape in the body; the YAML dump stores an escape; the reader gives back one character); on the candidate `GET /backlinks/<path>` for a tag and `GET /timeline` for a department answer 500 as plain text (the timeline is global: one note takes it down for every reader). The sweep of every field of both POST routes over every GET route found only these two cells unhandled, the same on both platforms; a notebook POST whose topic is a lone surrogate answers 400 on Linux and, on Windows, 500 after it wrote a file named by it (L13). By run on hand-made records (the escape `\ud800` in the YAML, never a literal one): a topic that is one answers 500 as plain text on the backlinks of its note and the graph's 500 envelope; a department of non-UTF-8 bytes, a department that is one, or a `created` that starts with one answers 500 as plain text on the timeline; a department that is a mapping is the existing controlled 500 (`.lower()` raises inside the route's `try`); tags and a department with non-ASCII letters, an emoji and CJK answer 200 on the candidate and on the amended router. After A1 each of those is the route's own 500 JSON envelope. F2: `?format=prov-jsonld` of a record whose `created` is `2026-11-09<U+D800>01:02:03` answers 500 as plain text on the candidate and 503 `records.read_failed` after A1 (the plain read answers 503 on both); a `created` that does not parse is not copied (200). Carriers that cannot hold one: a path segment or a query value (`%ED%A0%80` decodes to three U+FFFD and is answered 200), and a file whose bytes are ED A0 80 (the strict UTF-8 decode refuses it: the read answers 400, the listings skip it, the graph, the timeline and the backlinks answer 200). The write side, called on the store as the POST routes call it: `write_notebook(classification=<one>)` raises `ValueError('Invalid classification: <it>')`, whose text the route's 400 answer cannot encode; `append_captains_log(<one>)` raises `UnicodeEncodeError`; a tag or a department that is one is written. The file a Windows POST with a lone-surrogate topic leaves behind (its name holds the surrogate; in memory, the POST through the router, then each route): on the base the four listings that reach its folder (documents, notebook, browse, search), the graph and the backlinks of a note whose suggestions list it answer 500 as plain text, and the Captain's log and the timeline answer 200; on the candidate the four listings answer 200 without it (the log line carries its path as an escape), the graph answers its own 500 envelope and the backlinks 500 as plain text; on the amended router the backlinks answer their own 500 envelope too, and the rest is as on the candidate (on Linux the same POST with U+D800 is refused with 400, so this state is not reached that way there; a file name with an undecodable byte reads back with a lone surrogate under PEP 383, and the listings judge its path the same way: not measured). The answers matrix over the unfixed base, the candidate, the amended router and 16 mutants of it (no test function was run: each case's asserts were read as the answers they compare): base, 38 class cases fail (READ 5, LISTING 25, GRAPH 3, NOTE 2, PROJECTION 1, WINDOW, LIMIT) and the 16 guards pass; candidate, 3 fail (NOTE 2, PROJECTION); amended, none; the mutants as in section 9. The existing tests that reach the two handlers this amendment guards were enumerated by search (the two AD-562 files call `get_backlinks` and `get_records_timeline` as functions, over a fake service and over the real service on a fake store; `test_issue1368_readiness.py` drives both through the app; the ui test mocks the fetch and never reaches the router) and their conditions were replicated over small fakes on the candidate and on the amended router (13 groups, the knowledge routes' failure, `None`, success and invalid-parameter cases and the read route's success, projection and failure cases included): every payload they hand back is one the writer writes, the check runs after the service call, and the 401, 403 and 503 cases never reach it, so each group holds on both; the files themselves were not run.

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
CLAIM: every handler of routers/records.py whose body can hold a value the JSON writer refuses is guarded, and each other handler cannot hold one. (The first version of this claim, "no handler other than the seven holds a record value", was false: its probe drove the backlinks and the timeline with values they do not carry. A1, M-11.)
RUN:   grep -n -E "^@router\.(get|post)|await (runtime\._records_store|store|service)\.[a-z_]+\(|project_record_frontmatter\(" src/probos/routers/records.py ; then, for each callee, the lines that build what it returns (below)
FOUND: 13 routes and 14 calls to a store, a service or the projection (11 distinct callees; the only other awaits are the two `request.json()` of the POSTs; the module's other functions are `_read_failure`, `_writes` and `_writable`): stats get_stats; documents list_entries; documents/{path} read_entry, then project_record_frontmatter for ?format=prov-jsonld; POST captains-log append_captains_log; captains-log list_entries; notebooks/{callsign} list_entries; POST notebooks write_notebook; search search; history get_history; browse list_entries; backlinks get_backlinks; graph get_graph; timeline get_timeline
HOLDS: by route, what its body can hold and where it is guarded:
  stats: counts, a fixed list of directory names and the configured path (records_store.py:1645-1670); unguarded, no record or file name
  documents, notebook, captain's log, browse, search: {path, frontmatter} items (records_store.py:1522; the search hit :479-482): frontmatter values and file names; _writable
  documents/{path}: the entry {frontmatter, content, path}: frontmatter values; the content is read with a strict UTF-8 decode (records_store.py:1432) and holds no lone surrogate (M-11); _writes(body)
  documents/{path}?format=prov-jsonld: a document of strings; the one free text is a created that parses as ISO-8601, copied verbatim (provo.py:155-164, 286-288); _writes(body) (A1, F2)
  backlinks: references (a tag, a topic slug, a wikilink target and its text), referenced_by and suggested (paths) (backlinks.py:46-88, 313-329); _writes(result) (A1, F1)
  timeline: buckets keyed by a day (created[:10]) and a department (backlinks.py:454-488); _writes(result) (A1, F1)
  graph: a node's id (path), label (topic, topic slug or file stem), department, classification and author (backlinks.py:331-452); _writes(result)
  history: {commit, timestamp, message} from git, decoded with errors="replace" (records_store.py:1526-1550, :1833-1834), and the request's own path, which a URL decodes to U+FFFD (M-11); unguarded
  the two POSTs: {path, status}, the written path, built from the request's callsign and topic: the write side (L13), recorded, not fixed

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

CLAIM: nothing else in the new test file, the router change or the trackers depends on the platform, apart from what A1 handles (the depth numbers, the census control).
RUN:   grep -n -E "os\.|sys\.|platform|subprocess|sleep|time\.|Thread|signal|locale|environ|setenv|HOME|USERPROFILE|expanduser|\.home\(|tempfile|\btz|timezone|now\(|localhost|127\.0\.0\.1|port|chmod|symlink|\\\\|newline|read_text|write_text|open\(|encoding|rglob|glob\(|iterdir|listdir|sorted\(|\.lower\(|casefold|as_posix|\bsep\b|PYTHONHASHSEED|recursionlimit" tests/test_bf940_s3_route_serialisation.py ; the same tokens over the 56 lines the router change adds (git diff 708fa60c HEAD -- src/probos/routers/records.py, added lines) ; grep -n -E "sorted\(|replace\(|as_posix|relative_to" src/probos/knowledge/records_store.py (the listing's order and separators)
FOUND: the test file: setenv HOME and USERPROFILE with a premise that Path.home() is the temporary home; write_text(..., encoding="utf-8") (text mode: CRLF on Windows and LF on Linux, measured; no assertion reads a file's bytes); tzinfo is not None for a Z timestamp (no local zone is read); no process, port, sleep or path separator; every fixture name is lower case. The router change: nothing. list_entries sorts the files (records_store.py:1488) and builds path with .replace("\\", "/") (:1489), so a logged path is a forward-slash path on both.
HOLDS: for the patterns. Where a fixed number was a dependence it is handled: the depth numbers (M-10) and the census control (7.4). The census prints record paths with the console's encoding: not changed.
```

## 12. Prior Art and Blind Spots

- **Internal: adopted.** Slice 2's D4 (serialise inside the route's boundary, the existing 503) and its D6 (one record must not abort a listing); AD-1145 DD-7 (the body is byte-identical; its tests assert the object); AD-1140's rule that a refusal names no value; BF-949's census of `.search` callers (no call is added); the module's own log-and-degrade tier (`except` then `logger.warning(...)` then an envelope) and its message style, which `test_issue1368_readiness.py` pins. **Rejected:** slice 2's `dump_python(mode="json")` returned as the body (two relied-on tests assert the object); `jsonable_encoder` (D1); an application-level handler (D0).
- **Blind spots handled.** The depth a record has in a listing (two levels deeper than on the read route: T9); the identity of the returned object (AD-1145); the `?format=prov-jsonld` branch, whose body the check judges, not the entry it was made from (T4, T13); the backlinks and the timeline, which carry a tag, a topic slug, a department and a day (T12: the first version of this contract said they hold no record value, because its probe never put an unwritable value where they read, A1, M-11); the writer's depth stop, which differs by platform (the file derives it, M-10); the reader's own 600-level failure (T3); a record the store's writer makes (M-6); a self-referencing value (the writer refuses it; T7, T8); the graph's one raw value; the limit of the captain's log counted after the filter (T10); a value in a log line (markers in T7, T8, T11; mutation row 12); a new route that holds a record value (T6).
- **What discards a correct result.** A writable record left out: each record is tried at the depth it has in its body, and the whole body is tried first, so a record FastAPI would write is kept; after a per-record pass the filtered body is not tried again (no global limit is known; L3). A 503 for a record FastAPI would write: the check is the call FastAPI makes on the locked version (M-2: the same first failing depth), not on another (L3). A listing's `count` that disagrees with its items: it is taken after the filter (T8 compares whole bodies). **Recorded:** L1 to L13.

## 13. Diff Reviewer: properties to verify

1. `_writes(body)` is `TypeAdapter(Any).dump_json(body)` in a `try` that answers `False` for `ValueError` (which `PydanticSerializationError` is) and `RecursionError`, and nothing it writes is kept or returned; any other exception propagates.
2. When `_writes` is true a handler returns what it returned before: `read_record` returns `entry` itself (AD-1145 `:583`, `:595`), `_writable` returns the very list it was given, and the response bytes are unchanged (M-3).
3. `read_record`: the body is the entry, or the projection when `?format=prov-jsonld` is asked; one check judges that body and precedes `return body`; the `try`, its three `except` clauses and the 404 are untouched; the 503 is the existing envelope; the log line names no path and no exception.
4. `_writable` tries `{key: [record]}` (the depth of a record in a listing's body), tries the whole body first, logs a count and at most five `%r` paths and never a value; each listing route filters before it counts, and `get_captains_log` filters before its sort and its limit.
5. The graph, backlinks and timeline checks follow the `None` check and answer the envelope the route's `except` branch answers (500, JSON, no value in the log line).
6. No other handler, no store method and no other file of `src` is edited; stats, history and the POSTs are as before; the existing tests that reach the backlinks and the timeline (the two AD-562 files and the readiness file) hand back payloads the writer writes, so the new check passes them through (M-11); no existing test is edited (N2-1 removes the new file's own marker).
7. **Half-chain evidence:** each of T7 to T11 is one test from a record on disk through the real store and the real router to the status and the body, not a producer test and a consumer test.
8. The marker carries `raises=AssertionError, strict=True`; the 38 class cases fail at their own `assert`, never at a premise line (G1 with `--runxfail`); the 16 guards pass on both trees.
9. No test pins a depth: N1-1 asks its own `TypeAdapter(Any)` at import where the read route's body and a listing's stop and derives `nested-over-limit`, `nested-far-over-limit` and the guard below the limit from the answer (the stop is a platform constant, M-10); T9 scans a window around the derived limit and its premise says the first refused depth is that limit; if the writer stops being a depth, the import or that premise fails loudly.
10. The log lines carry no record value and match the neighbours' `returning HTTP 50x` pattern (`test_issue1368_readiness.py:164, :188`); the census of 7.4 is run before the pull request merges.
11. The inventory (section 11, Absence Verified) holds: every route that can hold a value the writer refuses is guarded; a route added later fails T6 until it is classified, and a classified route that holds a record value must be driven by the class. T12 crosses the seam from the real producer (the notebook route) to the consumer; T7 to T11 and T13 start from a hand-made record.

## 14. Acceptance criteria

- G1, G2 and G3 pass as stated, the census of 7.4 is run on the vessel's copy, and the batch's broad gate is green with a receipt.
- **F7-1:** a record the reader parsed and the JSON writer cannot write is answered by the read route with the existing 503 `records.read_failed` envelope (T7), is left out of each of the five listings that hold a frontmatter, with the rest listed and the path logged (T8, T9, T10), and fails the graph, the backlinks and the timeline with their own envelopes (T11, T12); a projection the writer cannot write is the same 503 (T13); the body of every record that was answered before is byte-identical (T1, T2, M-3), a `?format=prov-jsonld` of a record whose `meta` the writer cannot write, and the backlinks and the timeline of a record whose unwritable value they do not carry, are unchanged (T4, T5), the 600-level record answers as before (T3), and a new route fails T6 until it is classified.
- **The issue:** the pull request says `Refs #1686`; the trackers (PROGRESS.md, DECISIONS.md) say that F7-1 closes and that L19, the last box, keeps the issue open.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. For the Captain

1. **Nothing in this slice needs your decision.** D2 (a listing leaves out a record the writer cannot write, and logs its path) was checked against the six conditions under which the Captain decides in Delegated AD Execution Mode and meets none (D2's table): nothing stored changes, no control is weakened, no response shape or client contract changes, nothing is spent or moved, and the risk is Low. It is decided by the Architect and recorded in D2, L5 and DECISIONS. The price is that the omission is reported in the log, not to the client (L5). The ranked overrule option, if you prefer it, is to fail the whole listing: every listing that holds such a record then answers 503 while it exists (D2, M-1, M-9), at the cost of 27 cases of the new test file (T8's 25, T9 and T10) and mutation rows 4 to 10 and 12.
2. Run the census (7.4) on a read-only copy before the pull request merges; a flagged record is one you may want to repair or archive.
3. L19 follows in the last slice; nothing in this one decides it.
