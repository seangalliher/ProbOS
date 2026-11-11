# BF-940 (#1686): A frontmatter the store writes is one the store reads: one writer function refuses what no reader loads, a tags value that is not a list is refused, and a numeric tag reaches the semantic index (slice 2 of the issue)

**Drafted by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge is logged out), 2026-11-09
**Status:** ready to build on slice 1's merge. **Reading tree:** `D:\ProbOS-worktrees\bf940-build`, `HEAD` `7a094b28` (slice 1's frozen candidate, tree `24fe0901cda15dc03cf35a103a4e6b64bff8c472`; `origin/main` `b82f96d9` has not moved). Every SEARCH below is in the slice-1 state of its file. **Oracle:** a read-only consult: no pytest, no timing script, no child process. An in-memory script applied the 17 SEARCH/REPLACE pairs of N1-2, M2 and M3 to the LF blobs (each SEARCH once; every Python result parses), wrote the two new files, installed the four patched source modules in `sys.modules` (nothing on disk) and drove the test functions by hand with a driver that calls each function with `tmp_path`, a minimal `monkeypatch` and a stand-in `pytest` (decorators and `raises` only), **not the pytest runner**: collection, xfail semantics, `-n` and the other 47 test files were not exercised (section 10, L9). On the reading tree the writer-policy file's 11 guards pass and its 29 class cases fail, each at an `assert` of its own body after its premise (section 6); on M2's head with N2-2 applied all 40 pass and the unit file's 19 pass (with A1: 55 and 21); slice 1's T12 fails its premise on M2's head unedited and passes edited (N1-2); the ten mutants of section 9 and the five of A1 (R-1 to R-5) fail the cases listed there. The census script of 7.4 was run on synthetic trees. **Not run:** G1 to G3, pytest, the broad gate, the ledger generator, a real ChromaDB collection (driven afterwards by the orchestrator and the diff reviewer: L9), a timing run (the diff reviewer's serializer microbenchmark: L7), the census on a real tree.
**Base blobs** (sha1 of the LF-normalised working copy of the reading tree, computed by script, not `git rev-parse`; they must equal slice 1's merge): `records_store.py` `390d2bf7775415a03b13a955740d1b05baa0c3b4`, `semantic.py` `14d7dc6c5417772bf29cfe53163974ee0f4251a8`, `utils/frontmatter.py` `1d82253cc908d660113cdee2a5ab732a4945c5f2`, `skill_catalog.py` `9d0c414472a051924daaeffd6f3e3fc8eec031a4`, `tests/test_bf940_frontmatter_framing.py` `feaf2ac45fa78ddae03f4498d0881ae2ba6f7b4c`, `deterministic-ship.md` `1959c08d5d975ffa92885764f624ea7cd3771d7f`, `PROGRESS.md` `98b6d7ac10696a55137f864c72bd01e45ee13bc0`, `DECISIONS.md` `e8cffd5774be3f532f2498ef6956d79a5617b482`.
**Dependencies:** slice 1 merged. **Tier:** M1 STANDARD (tests); M2 HIGH (the one function every Ship's Records writer now calls, and a new refusal at `write_entry`); M3 STANDARD. **Estimated tests:** two new files (40 cases in `test_bf940_s2_writer_policy.py`: 11 pass and 29 xfail at M1; 19 in `test_bf940_s2_dump_frontmatter.py`) and one edit of an existing test (N1-2); A1 adds 15 plain cases to the first file (55) and 2 to the second (21). **BF number:** BF-940, held by #1686 (open, `bug`); nothing new is allocated.
**What this contract closes of #1686:** L24 (the writers) and L27 (the numeric tag). **The issue keeps** L19 (a frontmatter that does not parse) and F7-1 (the records route), and stays open: the pull request says `Refs #1686`, not `Closes`. Slice 2 starts with L24 (D1).

**Which text describes the head.** Before building: slice 1 is merged, `git rev-parse HEAD:<path>` for the eight paths prints the blobs above, `git diff --stat <slice 1's candidate> HEAD -- src/probos/knowledge src/probos/utils src/probos/cognitive/skill_catalog.py src/probos/routers tests/test_bf940_frontmatter_framing.py docs/development/deterministic-ship.md PROGRESS.md DECISIONS.md` is empty, and neither new test file exists. If one fails, every SEARCH must still occur exactly once, else it is a hard stop for the Architect. Working copies are CRLF and SEARCH text is LF. Where prose and a block differ, the block wins. Apply the pairs with the `edit` tool one at a time, whole block, in label order.

## 1. Problem

1. **L24 (privacy, P1).** `yaml.dump` writes a tuple, an `OrderedDict`, a `frozenset`, a namedtuple, a `str` subclass, an `Enum`, a `Decimal` or any other object with a `!!python/` tag; `yaml.safe_load` refuses every one (`ConstructorError`). The document then reads as `{}` for every reader (`_parse_document` catches `yaml.YAMLError`), so at the default `ship` classification, and its author's own `publish` raises `PermissionError`. Run through the real store, a fresh store per case, `~` moved, with the premise that the author's own search finds the note (a hand driver, not pytest): `write_notebook("alice", "review-nominal", "coolant private body", metrics={"sample": (1, 2)})`: python tag on disk; `read_entry` as bob returns the note; bob's search finds it; alice's `publish` raises `PermissionError`. The same with an object, an `OrderedDict` or a tuple key in `metrics`, or a tuple in `extra_frontmatter`. A list, a set (`yaml.dump` writes `!!set`, which loads) or `nan` in `metrics` stays private (section 11, M-1). Slice 1's A1 fallback keeps a note private only where a `---` precedes the tag (case A).
2. **L27.** `tags: [717]` is accepted, written and found by keyword search, but `semantic.py:406` joins the tags as strings: `TypeError` on write (`write_entry` catches it, logs, and the record is never indexed) and per record on every backfill (`reindex_records` catches it per record and logs). `tags=717` (a scalar, from `POST /api/records/notebooks/{callsign}`, which hands `body.get("tags", [])` to `write_notebook`, `routers/records.py:156`) is written as `tags: 717`; `list_entries(tags=[...])` then raises `TypeError` out of the whole listing (the filter at `records_store.py:1493` is outside the per-file `try`): measured (M-3).
3. **What the writers are.** By command (section 11): four writers call `yaml.dump` into a frontmatter: `write_entry` (`records_store.py:762`), `append_captains_log` (`:885`), `publish` (`:1544`) and the skill catalog's `_rewrite_frontmatter` (`skill_catalog.py:808`). `publish` and `_rewrite_frontmatter` re-dump what `safe_load` returned, and `safe_load` returns a tuple for `!!omap` (measured; `!!pairs` not measured): a hand-made note holding one is rewritten with a `!!python/tuple` tag by `publish` (measured, M-1). The other `yaml.dump` calls in `src` write a record's body (`dreaming.py:1371`, `procedure_store.py:714` and `:1728`, `commands_gap.py:243`, `routers/gaps.py:185`) or the store's own config (`records_store.py:1769`), not a frontmatter.
4. **Reach by production payload.** No production caller passes a tuple, a set or an object by what was read (section 11, the callers table): every payload is a `str`, `int`, `float`, a list of `str` or a mapping of them. L24 is latent in production and open to any caller of `extra_frontmatter`, which accepts any dict (AD-1140), and to tests. L27 has two live inputs: the HTTP route (any JSON `tags`) and `Procedure.from_dict` (`procedures.py:144` and `:158`, `data.get("intent_types", [])` and `data.get("tags", [])`, not validated, and `procedure_store.py:726` passes `procedure.intent_types + procedure.tags`).
5. **On disk.** A document already written with a tag stays as it is: it reads `{}` and the writer change does not touch it (measured, M-4). How many a vessel holds is what 7.4 counts on a read-only copy of its records; the result of a run on a vessel's data is not recorded in this repository. They are L19's (D3).

## 2. Solution

New `dump_frontmatter(mapping) -> str` in `utils/frontmatter.py`: `yaml.safe_dump` with the arguments the writers used, then a `yaml.safe_load` of the text it wrote, which must be a mapping. A tuple becomes a list; an object `safe_dump` refuses (`RepresenterError`) and a text `safe_load` refuses (a tuple as a mapping key) raise `ValueError` naming the top-level keys at fault, never a value, before the caller touches a file (AD-1140's fail-fast tier). For every value `yaml.dump` wrote without a `!!python/` tag, which is every value `safe_load` builds that holds no tuple, it is byte-identical to `yaml.dump` (M-2); `safe_load` builds a tuple for exactly two tags, `!!omap` and `!!pairs` (a list of tuples), and a mapping holding one is written as a list of lists (A1, F2; V7). `write_entry`, `append_captains_log`, `publish` and the skill catalog call it. `write_entry` refuses a `tags` that is neither a list nor a tuple (a falsy one is ignored, as before); `semantic.py` joins `str(tag)`; `list_entries` matches a document's `tags` by equality, so a tag that is not text cannot abort a filtered listing (A1, D6). L19 and F7-1 are decided here (D3, D4) and built in later slices.

## 3. Decisions

**D0. Scope** (ranked by correctness, safety, compatibility, architectural fit, reversibility and validation cost; Delegated AD Execution Mode: the top is taken; L24 is first in every option).

| # | Option | Judgement |
|---|---|---|
| 1 | **L24 + L27 here; L19 and F7-1 later slices (chosen)** | One boundary, one test file: `write_entry`'s value policy (what the writer accepts, normalises or refuses before the dump). L27's guard is one more line there and its join is one line in `semantic.py`; a later slice for L27 would re-open the same function and the same tests. Nothing here changes a read, but for one after review round 1: `list_entries` matches a document's `tags` by equality (A1, D6) |
| 2 | L24 alone | The smallest review, but L27 would reopen `write_entry`, the fixtures and the route test for one guard and one join |
| 3 | L24 + L19 | The privacy pair, but two risk classes: L19 is a read-side visibility decision for nine callers and the backfill, with BF-952's history (seven review rounds; a rule that withholds unparseable records took a record from its owner, RK10, withdrawn in A3), and it **is a Captain's decision** (D3). The writer fix makes L19 smaller (the writer can no longer produce its largest source), so L24 first helps it |
| 4 | All four | F7-1 shares no code or test with the writer policy (`routers/records.py`, a serialisation boundary); L19 needs the Captain. Four risk classes in one review |

| Box | Shares code or tests with another? | This contract |
|---|---|---|
| L24 | `write_entry`'s dump and `publish`'s; shares the function, the file and the refusal tests with L27 | **built** (M2) |
| L27 | `write_entry`'s guard (same boundary) and `semantic.py:406`; the route's 400 | **built** (M2) |
| L19 | `_parse_document` and the search's reader (read side); needs the Captain; legacy tagged documents (D1.5) | **kept**, decided in D3 for the next slice |
| F7-1 | `routers/records.py` only; no shared code | **kept**, decided in D4; small, can precede L19 |

#1686 closes only when every box is built or shown invalid with evidence. Slice 1 closed L25, L18 and L20; this slice closes L24 and L27; L19 and F7-1 stay. The pull request says `Refs #1686`, M3's commit body ends `Refs #1686.`, and nothing is moved to another issue.

**D1. L24: how a frontmatter is written.** The effect of each option on each writer and each reader or caller. "Boundary" asks whether it weakens a privacy or audit control, or breaks a persisted format or compatibility promise (a Captain-only decision); none of the four does except option 4.

| # | Option | Writers | Readers and callers | Boundary |
|---|---|---|---|---|
| 1 | **`dump_frontmatter`: `safe_dump` + a read-back check, in one function the four writers call (chosen)** | `write_entry`: a tuple is a list, a set stays `!!set`, an object or a tuple key raises `ValueError` naming the key before `mkdir`, the write, the git add, the confidence tracker and the index (a refused update leaves the existing note byte-identical: measured). `append_captains_log`: unchanged text. `publish`: an `!!omap` note is re-written as a list and stays readable. `_rewrite_frontmatter`: the same, and the `ValueError` is unreachable for a `safe_load` product short of nesting beyond the recursion limit (a plain script's `safe_dump` wrote 300 levels and raised `RecursionError` at 450) | `read_entry`, `list_entries`, the search, the backfill and `publish` read a note that was written as a tuple as they read the list control: private for bob, found by alice, alice's `publish` succeeds, the backfill indexes its real classification (M-1). Callers that `except Exception` (most do) drop a refused write: none passes such a value today (section 11) | none: stricter than before, no reader ever loaded the tag |
| 2 | A normalising function (tuple and set to list; anything else not YAML-native refused) before `yaml.dump` | the same for a tuple; a set becomes a list (read back as a list, not a set); a tuple key and `publish`'s `!!omap` need their own cases in a type walk | the same; more code (a type walk) for a result `safe_dump` already gives | none |
| 3 | A refusal at `write_entry`'s boundary for anything not JSON-native | refuses a tuple, and also a date, a datetime, a set and bytes that load today and that `publish` re-dumps | `publish` and `_rewrite_frontmatter` still re-dump what `safe_load` built (dates, `!!omap`): the boundary does not cover them | none, but a narrower accept set than any reader |
| 4 | A read-side loader that builds `!!python/tuple` | none (the writer keeps writing the tag) | six load sites would change (`records_store.py:273`, `:309` and `:231`, `:1728`, `:1734`; `skill_catalog.py:113`, `:790`) and the tag stays in the file: `publish` re-dumps it with `yaml.dump` (measured: the tag comes back). `yaml.UnsafeLoader`, the only loader that reads every `!!python/` tag, calls any importable callable named in the document (measured on `builtins.len`: `{'x': 3}`): a hand-made note could run code | **yes**: a persisted-format extension and a code-execution path; not taken |

Rank: 1 > 2 > 3 > 4. The refusal set of option 1 is the set the readers already cannot read (a document holding one reads as `{}`), so it removes no working write. Of the 27 values of the matrix (M-1), `yaml.dump` tagged 16 (a tuple alone, in a list and holding a list, a tuple key, and 12 objects); `safe_dump` writes the three tuple shapes as lists, refuses the 12 objects (`RepresenterError`) and writes the tuple key, which `safe_load` refuses: the read-back catches it. The other 11 values load as they are and V1 and T2 pin the bytes of the tuple-free shapes against `yaml.dump`, and V7 pins what the two tags that make `safe_load` build tuples (`!!omap`, `!!pairs`) become: lists (A1, F2).

**D1.5. A document already on disk with a Python tag.** Options: leave it (chosen: nothing in a reader or the writer changes it); a read-side loader (option 4, no); a repair tool. After the writer change it still reads `{}`, so `ship`, and `publish` by its author raises `PermissionError`; the Captain's `publish` rewrites it with `status` and `updated` only and **the original frontmatter text is gone from the file**; a same-slug `write_notebook` replaces it and loses `created` and `revision` (all measured, M-4). That is L19's reading of a frontmatter that does not parse, so L19's slice owns it; 7.4 counts them on a vessel's copy.

**D2. L27: a numeric tag.** Effect on `read_entry`, `list_entries`, the search, the sidecar and the backfill, measured (M-3):

| # | Option | Effect |
|---|---|---|
| 1 | **Refuse a `tags` that is not a list or tuple at `write_entry` (the `extra_frontmatter must be a dict` precedent, `records_store.py:700`); the index joins `str(tag)` (chosen)** | `tags=[717]`: written as given, `read_entry` and `list_entries` return `[717]`, keyword search finds `717`, the record is indexed on write (header `[717]`) and on backfill (the sidecar row is written; its `tags` element not inspected). `[1.5]`, `[True]` (header `True`), `[None]` (header `None`) index too. `tags=717`, `"abc"`, `{"a": 1}` or a set raise `ValueError("tags must be a list")` before any file: the route answers 400 (it already maps `ValueError` to 400, `routers/records.py:161`); `tags=("a", "b")` is written as a list. Fixes a hand-made note on disk (the backfill reads from disk), which option 2 does not |
| 2 | Normalise `int` and `float` tags to `str` at write | The file holds `'717'`; `read_entry` returns `['717']`, which is not what the caller wrote; a note already on disk is unchanged and its backfill still raises |
| 3 | Refuse any non-`str` tag | Refuses what is written, found by keyword search and read back today, and loses the record for the callers that catch and drop; no gain over 1 |
| 4 | The join alone | A scalar `tags: 717` still raises at `', '.join(717)`, and `list_entries(tags=...)` still raises `TypeError` for it |

Rank 1 > 4 > 2 > 3. Crosses no Captain boundary; the route's 400 is a compatibility change for an HTTP client that sent a scalar `tags`, which wrote a record `list_entries(tags=...)` could not list (measured), so it is in the Architect's envelope.

**D3. L19 (decided here; built in a later slice; a Captain decision, see the end).** Measured on the real store (M-4), a frontmatter that does not parse, an `!!python/` tag and a constructor error (`updated: 2026-13-05`) for each caller:

| Caller | Today |
|---|---|
| `read_entry`, search | unparsable and tagged: read `{}`, so alice, bob and the Captain all read and find it; constructor error: `ValueError` for all three, the search withholds it |
| `list_entries`; the backfill | `{}` listed; indexed as `ship`. Constructor error: not listed; not indexed |
| `publish` | alice: `PermissionError`; the Captain: **rewrites the file with `status` and `updated` only; the original frontmatter lines are gone**; constructor error: `ValueError` |
| update-in-place (`write_notebook`, same slug) | succeeds; `created` lost, `revision` restarts (at 2; absent after a constructor error), the old block is replaced |

| # | Option | The author | Others | Writers of an existing note |
|---|---|---|---|---|
| 1 | **A typed parse result; readers withhold from everyone but the Captain and the path's owner (`notebooks/<callsign>/…`); `publish` and update-in-place refuse; the backfill and the scans skip (recommended)** | reads (owner by path, not by the frontmatter that did not load) | withheld | refuse with an error naming the path: nothing is rewritten that cannot be read |
| 2 | Fail closed with an unknown author | **withheld** (BF-952 RK10's defect) and, measured, **the anonymous reader `""` is admitted**: `record_is_readable` with author `""` returns `{'alice': False, 'bob': False, 'captain': True, '': True}` | withheld | not addressed |
| 3 | Keep `{}` | reads | read it too (the privacy hole of L24, for what is already on disk) | the Captain's `publish` still destroys the block |
| 4 | Quarantine (move the file) | the note vanishes | | a read with a side effect on the repository and on git |

Rank 1 > 3 > 2 > 4. Option 1 withholds from a reader what the base showed him (a reader of a ship-wide report whose frontmatter does not load): a change of who may read records already on disk, so the Captain decides it before that slice. L13 (a constructor error after a `---`): the trigger does **not** widen for A1's fallback (it stays `yaml.YAMLError`: widening would turn a record that is withheld today into one read through its cut); under option 1 a constructor error and a recursion failure are parse failures like any other, which is what they already are for the reads (measured: they raise or withhold) and what they are not yet for update-in-place (it overwrites).

**D4. F7-1 (decided here; built in a later slice).** Measured through the real route over a real store (`GET /api/records/documents/{path}`, M-5): a hand-made record nested 50 and 90 levels returns 200; 100 and 450 return **500**; 600 returns the controlled 503 (the reader's own `RecursionError`); a record holding `!!binary //4=` (bytes that are not UTF-8) returns **500**; `GET /api/records/documents` (the listing) returns **500** while any such record exists. The threshold on this host (FastAPI 0.136.1, pydantic_core 2.41.5) is 100 levels, not the issue's 450: the failure is FastAPI serialising the returned mapping after `read_record`'s `try`.

| # | Option | Effect |
|---|---|---|
| 1 | **`TypeAdapter(Any).dump_python(body, mode="json")` inside the route's boundary; on failure the existing `records.read_failed` 503 (chosen)** | its output equals FastAPI's own for 4 shapes (ordinary; datetime, date, set and bytes; unicode with an int key and `nan`; 90 levels); depth 100, 450, 600 and non-UTF-8 bytes become the 503 envelope. Repo precedent for `TypeAdapter` (`routers/workforce.py:95`); I did not read FastAPI's source, so "the adapter FastAPI uses" is not claimed |
| 2 | `jsonable_encoder(body)` then `JSONResponse` | **not byte-identical** (a UTC datetime goes from `…Z` to `…+00:00`: measured); `nan` becomes a 503 where it was a 200 |
| 3 | An application-wide handler for `PydanticSerializationError` | broader than the box; every route's failure changes |
| 4 | Limit the depth `read_entry` returns | changes the reader (slice 1's frontier), not the boundary |

Rank 1 > 2 > 3 > 4. Where: `routers/records.py`, `read_record`, around the `return` at the end (`:98-102`); also for the three listings that return `frontmatter` (`list_records`, `list_notebook`, `get_captains_log`), which have the same defect (the listing 500, measured) and are not in the box: the later slice should take them with one helper. The test: a real `RecordsStore` with hand-made records at 450 levels and with `!!binary //4=`, through the real router, expects 503 with `availability.code == "records.read_failed"`; an ordinary record and a datetime record stay 200 with the same body; 600 levels stays 503.

**D5. One function, one place.** `probos.utils.frontmatter`, next to `split_frontmatter` (slice 1's D2: pure helpers any layer may import; `records_store.py` and `skill_catalog.py` already import it). It adds `import yaml` to a module whose docstring said it loads nothing: that sentence now says the framing functions load nothing, and `dump_frontmatter` loads only the text it has just written, to check it. Rejected: a method on `RecordsStore` (the skill catalog is a fourth writer in another layer) and a copy in each writer (the L24 defect was one copy of a policy that three writers repeated by habit).

**D6. Review round 1 (A1).** The diff reviewer found F1 (P2, a regression, reach injected-only), F2 (P3, a claim that was false) and four documentation points (the order in section 13's property 2, L3, L7, L9). Delegated AD Execution Mode: the options are ranked by correctness, safety, compatibility, architectural fit, reversibility and validation cost and the top is taken. None crosses a Captain-only boundary: no privacy or audit control, persisted format or compatibility promise is weakened (`record_is_readable`, `read_entry`'s gate and the search's scope are unchanged, and `list_entries` applies no reader scope).

*F1: a nested element in `tags` aborted a filtered listing.* `list_entries` tested `set(tags).issubset(set(fm.get("tags", [])))` outside its per-file `try`, which hashes every stored element. Slice 2 makes a note holding a nested tuple readable (the tuple is written as a list), so a note the base wrote unreadably, and skipped, aborted the listing, and `read_head_to_head` (AD-1358) dropped its whole tally: base (1, 0, 0), candidate no tally (16.1, M-6). The defect is older for other shapes: a nested list, mapping or set (`write_entry` accepts them; a JSON client of the notebook route can send a list or a mapping, not a set) already dropped the tally on the base, and so did a number, a date or `null` in a document on disk (16.1, M-6). Only three calls in `src` pass a `tags` filter to `list_entries` (`recreation/history.py:184`, `commands_gap.py:51`, `routers/gaps.py:23`), each a list of strings (16.2).

| # | Option | Writers and the 20 callers | The route | A document already on disk | Search, index, backlinks, slice 1's readers |
|---|---|---|---|---|---|
| 1 | **Read side: `list_entries` matches tags by equality over the stored value (chosen)** | none is edited; every call of `write_entry` and `write_notebook` behaves as at the candidate | 200 for a nested list element, as on the base (T19) | reached: a nested element, a number, a date or `null` no longer aborts (M-7) | unchanged (M-8); `list_entries`, a consumer of `_parse_document`, changes its own tag test only |
| 2 | Write side: `write_entry` refuses a list, tuple, set, frozenset, mapping or bytes element (str, int, float, bool, None, date and datetime stay) | the route (`routers/records.py:151`) and `write_notebook`'s passthrough raise `ValueError`; `procedure_store.py:719` for a nested element in `intent_types + tags` (debug log, the projection dropped; injected-only); the other 17 calls pass lists of strings (one passes none): unchanged; `publish` and the skill rewrite re-dump what they loaded and are not covered | 400 where it was 200 | not reached | a nested element never gets there |
| 3 | Both | as 2 | 400 | reached | as 1 |
| 4 | A normalising write: a nested element becomes its `str` | none visible | 200, but the stored tag is not what was sent | not reached | the index joins a string |

Options 2 to 4 are not built: their cells are readings of the code, not runs. Rank: 1 > 3 > 2 > 4. Option 1 reaches the documents already on disk, which only a read-side change can, leaves every writer and the route's answer alone, and is one helper and one call to reverse. Option 3 adds a route-visible refusal F1 does not need; option 2 alone leaves what the route already wrote; option 4 rewrites what a caller sent (the family slice 1's A3 withdrew). The helper iterates the stored value, so wherever `set(wanted).issubset(set(stored))` could be computed it gives the same answer (a string is read by character and a mapping by key, as before) and a value that is no collection holds no tag: the stricter reading, in which anything but a list holds no tag, would change those two results for no consumer's benefit and is a later cleanup with L19 (L11). Option 1 departs from D0 and section 8, which listed `list_entries` as unchanged (A1-17, A1-23), and it is not a shared-contract change by the repair-round rule: no signature, return shape, persisted format, config field, event, wire shape, relied-on test or gate changes (16.2), the result differs only where the base raised (M-7), and it is what F1 asked for. The delta is reviewed with the consumers of the changed names (the three calls that pass a `tags` filter, the one call of `_holds_every_tag`).

*F2: the equivalence claim was false.* The `dump_frontmatter` docstring, sections 2, 13 and 14 and the PROGRESS entry said the text is byte-identical to `yaml.dump`'s for every value `safe_load` builds. `safe_load` builds a tuple for exactly two tags, `!!omap` and `!!pairs` (a list of tuples); `yaml.dump` tagged them `!!python/tuple`, and the function, by design, writes lists, which is what `publish` and the skill rewrite re-dump. The claim is now: byte-identical for every value `yaml.dump` wrote without a `!!python/` tag (every value `safe_load` builds that holds no tuple); a tuple is a list; an object is a `ValueError`; a re-dumped `!!omap` or `!!pairs` is a list of lists, which the readers load and which no longer equals what `safe_load` built (L13). Taken: qualify the claim, add V7, change no writer. Rejected: writing the tuples back (`!!omap` and `!!pairs` share one Python shape, so no writer can tell which tag a list of tuples came from, and the only tag it could write back is the unsafe `!!python/tuple`, D1 option 4) and refusing the re-dump (`publish` of such a note would fail where it succeeds). The places changed were found by a scan of the staged files and this contract (16.2): A1-1, A1-8, A1-9, A1-15, A1-18, A1-31, A1-33, A1-36 and A1-39; the T2 and V1 to V6 rows say "native values" and stay.

*What A1 does not change:* a writer, a caller, the route, the persisted format, config, a reader other than `list_entries`' tag test, `deterministic-ship.md`; a document on disk is never rewritten by it.

## 4. Milestones and gates

| M | Blocks | Gate |
|---|---|---|
| M1 | N1-1, N1-2 | G1 |
| M2 | P2-1 to P2-9, then N2-1 and N2-2 (the markers) | G2 |
| M3 | P3-1 to P3-3, ledger | G3 |

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. **M0:** on the head, record the collected count (`--collect-only -q`) of every existing file named in G2.

- **G1.** `PY -m pytest tests/test_bf940_s2_writer_policy.py tests/test_bf940_frontmatter_framing.py -q -n 0 -p no:randomly`. **Expected:** the new file 40 cases: **11 passed, 29 xfailed**; the framing file's collected count equals M0's, 0 failed (N1-2 changes one test and keeps it a guard). The markers carry `raises=AssertionError, strict=True`: any other exception, or an XPASS, is a FAIL. Then once with `--runxfail`: each failure must stop at the `assert` section 6 names, never at a premise line.
- **G2.** (1) `$f = git grep -l -E '\.write_entry\(|\.write_notebook\(|append_captains_log|extra_frontmatter|\.publish\(|reindex_records|index_record|_rewrite_frontmatter|enrich_skill|routers\.records' -- 'tests/test_*.py'` (47 files for the first five patterns on the reading tree; M0 records the count of the full list); then `PY -m pytest $f tests/test_bf940_s2_writer_policy.py tests/test_bf940_s2_dump_frontmatter.py tests/test_layer_boundaries.py -q -n 0 -p no:randomly`. (2) `PY -P scripts/check_architecture_principles.py --check`. **Expected:** the new files' cases all passed (55 and 21 passed with A1; 40 and 19 before it); every other file 0 failed with collected counts equal to M0; the check clean (slice 1's reading: `srp-size=92, layer-import=0, db-connect=30, unowned-task=13`; unchanged).
- **G3.** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- **Census (not a Builder step).** Run 7.4 on the vessel's copy before the pull request merges; an `EXPOSED` line or a `PYTHON_TAG` goes back to the Architect.
- **Harness rule.** No source change made to pass a test, no skip, no loosened assertion. A failing case of the new files at G2, or any existing test failing, goes back to the Architect. The broad gate runs once, in the main session, with `--receipt`.

## 5. Commit messages

- **M1:** `BF-940 M1 (slice 2): tests for a frontmatter the store writes being one it reads, and for a numeric tag reaching the index, xfail until built (#1686)`
- **M2:** `BF-940 M2 (slice 2): one writer function writes every frontmatter (a tuple is a list, an unreadable value is refused), a non-list tags is refused and a numeric tag is indexed (#1686)`
- **M3:** `BF-940 M3 (slice 2): trackers, ledger and the invariants document (#1686)`; its body ends with the line `Refs #1686.`

## 6. Tests

`tests/test_bf940_s2_writer_policy.py` (M1; the functions pass on both trees, the two classes are strict xfail until M2) and `tests/test_bf940_s2_dump_frontmatter.py` (M2). Every privacy case is one note in a fresh store and asserts its premise first (the author's own search finds it). Names are in 7.1 and 7.2.

| Id | Cases | Covers | xfail until |
|---|---|---|---|
| T1 | 3 | Guard: a list, a set and `nan` in `metrics` keep a private note private through `read_entry`, the search and `publish` (`test_a_value_the_readers_load_keeps_a_private_note_private`) | none |
| T2 | 1 | Guard: the bytes of a note holding native values equal what `yaml.dump` of the loaded block gives (`test_the_bytes_written_for_values_the_readers_load_are_what_yaml_dump_wrote`) | none |
| T3 | 1 | Guard: the Captain's log is written and read as before | none |
| T4 | 1 | Guard: `publish` of a hand-made note holding `!!set`, `!!binary` and a date keeps it readable and private | none |
| T5 | 4 | Guard: `tags` of `None`, `[]`, `""` write no `tags` key, a list of text writes it | none |
| T6 | 1 | Guard: the notebook route writes `["a"]` as before | none |
| T7 | 5 | Class: a tuple in `metrics` (case B), with `---` in the topic (case A), in `extra_frontmatter`, a list of tuples, tuples nested in mappings: no `!!python` in the file, private for bob, alice reads and publishes | M2 |
| T8 | 12 | Class: six values no reader loads (an object, an `OrderedDict`, a `frozenset`, a namedtuple, a `str` subclass, a tuple key) as `metrics` and as `extra_frontmatter`: both an update and a create raise `ValueError` naming the key; the existing note is byte-identical and nothing else is created | M2 |
| T9 | 1 | Class: `publish` of a hand-made `!!omap` note writes no tag | M2 |
| T10 | 1 | Class: a SKILL.md holding `!!omap` stays parseable after `_rewrite_frontmatter` | M2 |
| T11 | 4 | Class: tags `[717]`, `[717, "x"]`, `[1.5]`, `[True]` are read back as given, indexed on write and on backfill | M2 |
| T12 | 4 | Class: `tags` of `717`, `"abc"`, `{"a": 1}`, a set raise `ValueError("tags must be a list")`; nothing is written | M2 |
| T13 | 1 | Class: `tags=("a", "b")` is written as a list | M2 |
| T14 | 1 | Class: the notebook route answers 400 for `tags: 717` | M2 |
| V1 to V6 | 19 | The function, in the M2 file: native values equal `yaml.dump`; a tuple as a list; 8 unreadable values refused naming the top-level key; a tuple key refused although `safe_dump` writes it; no value in the message; depth 100 written and 600 a `ValueError`; an empty mapping | none (M2 file) |
| T15 | 4 | A1: a nested tuple, list, mapping or set in `tags`: the writer accepts it, the note reads, and `list_entries(tags=[...], strict=True)` lists it with the healthy note and not a note holding only one of the two tags (`test_a_nested_element_in_tags_does_not_abort_a_filtered_listing`) | none (plain) |
| T16 | 4 | A1: the same through `read_head_to_head` (AD-1358): the tally over the healthy record and the record holding the element is two games, not `None` (`test_the_head_to_head_tally_survives_a_game_record_whose_tags_hold_a_nested_element`) | none |
| T17 | 5 | A1: a hand-made `tags` of `717`, `1.5`, `true`, a date or no value, on disk, matches no filter and the listing returns the healthy note (`test_a_stored_tags_value_that_is_no_collection_holds_no_tag_and_does_not_abort_the_listing`) | none |
| T18 | 1 | A1, guard (passes on every tree): every tag is required, a `!!set` is read, a note with no `tags` key matches nothing (`test_the_tag_filter_still_requires_every_tag_and_reads_a_set_and_a_missing_key_as_before`) | none |
| T19 | 1 | A1, guard (passes on every tree): the notebook route answers 200 for a nested list element and writes it (`test_the_notebook_route_still_accepts_a_nested_element_in_tags`) | none |
| V7 | 2 | A1: the products of `!!omap` and `!!pairs` (a list of tuples) are written as lists, read back as lists, equal to `yaml.dump` of the same mapping with lists, and stable under a second rewrite (`test_a_mapping_that_safe_load_builds_with_tuples_is_written_as_lists`) | none |

**How each xfail case fails on the unfixed tree** (measured by a hand driver on the reading tree with the file's functions called directly): T7 at `assert "!!python" not in raw`, after its premise; T8 at `assert len(refused) == 2` (nothing is refused); T9 at `assert "!!python" not in …` after `publish`; T10 at `assert "!!python" not in path.read_text(...)` (the rewrite wrote a tag; the `parse_skill_file` assert after it is not reached); T11 at `assert f"record_{path}" in column.rows`; T12 at `assert message is not None`; T13 at `assert "!!python" not in raw`; T14 at `assert response.status_code == 400`. **Guards that pass on both trees:** T1 to T6, and N1-2's edited slice-1 test.

**A1's cases** (plain tests added after M2: the opening sentence of this section, that the functions pass on both trees, is M1's state; hand driver, 16.1, M-10): on the staged candidate 13 of the 15 new writer-policy cases fail: T15 and T17 at the listing (`TypeError: unhashable type` or `'int' object is not iterable`), T16 at `assert tally is not None`; T18, T19 and V7 pass. On the base 13 fail too (T15's tuple case at its premise, because the base writes that note unreadable) and T18 and T19 pass. With A1 all 17 pass.

## 7. The contract

### 7.1 M1

**N1-1.** New file `tests/test_bf940_s2_writer_policy.py`:

```python
"""BF-940 slice 2 (#1686): a frontmatter the store writes is one the store reads (L24), and a numeric tag reaches the index (L27).

Real ``RecordsStore`` over ``tmp_path`` with ``~`` moved, no network. The two classes are strict xfail until M2 (each case fails
at an ``assert`` of its own body on the unfixed tree, after its premise); the module's functions are guards and pass on both
trees. A privacy case is one note in a fresh store and asserts first that the author's own search finds it, so "bob does not
find it" cannot mean the search found nothing at all.
"""

from __future__ import annotations

import collections
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NamedTuple

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.cognitive.skill_catalog import CognitiveSkillCatalog, parse_skill_file
from probos.config import RecordsConfig, SystemConfig
from probos.knowledge.records_store import RecordsStore
from probos.knowledge.semantic import SemanticKnowledgeLayer
from probos.routers.records import router


class _Plain:
    pass


class _Text(str):
    pass


class _Pair(NamedTuple):
    a: int
    b: int


class _Collection:
    """The one method the records index uses of a ChromaDB collection, and the lookup the backfill makes."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, dict[str, Any]]] = {}

    def upsert(self, ids: list[str], documents: list[str], metadatas: list[dict[str, Any]]) -> None:
        self.rows[ids[0]] = (documents[0], metadatas[0])

    def get(self, ids: list[str], include: Any = None) -> dict[str, list[str]]:
        return {"ids": [i for i in ids if i in self.rows]}


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RecordsStore:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert Path.home() == home, "premise: ~ is the temporary home"
    (tmp_path / "ship-records").mkdir()
    return RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))


async def _hits(store: RecordsStore, reader: str) -> list[str]:
    return [hit.get("path", "") for hit in await store.search("coolant", reader_id=reader)]


def _hand_made(store: RecordsStore, path: str, text: str) -> None:
    (store.repo_path / path).parent.mkdir(parents=True, exist_ok=True)
    (store.repo_path / path).write_text(text, encoding="utf-8")


def _app(store: RecordsStore) -> FastAPI:
    app = FastAPI()
    app.state.runtime = SimpleNamespace(config=SystemConfig(), records_store=store, _records_store=store)
    app.include_router(router)
    return app


@pytest.mark.parametrize("sample", [
    pytest.param([1, 2], id="a-list"),
    pytest.param({1, 2}, id="a-set"),
    pytest.param(float("nan"), id="nan"),
])
async def test_a_value_the_readers_load_keeps_a_private_note_private(store, sample):
    """Guard: the list control of case B, and the two values ``yaml.dump`` writes without a tag."""
    path = await store.write_notebook("alice", "review-nominal", "coolant private body", metrics={"sample": sample})
    assert path in await _hits(store, "alice"), "premise: the author finds her own note"
    assert "!!python" not in (store.repo_path / path).read_text(encoding="utf-8")
    assert await store.read_entry(path, reader_id="bob") is None and path not in await _hits(store, "bob")
    await store.publish(path, "alice")
    assert await store.read_entry(path, reader_id="bob") is None


async def test_the_bytes_written_for_values_the_readers_load_are_what_yaml_dump_wrote(store):
    """Guard: the writer's text for native values is ``yaml.dump``'s, byte for byte (a ``safe_dump`` must not change a file)."""
    path = await store.write_notebook(
        "alice", "native", "body", department="science", tags=["a", "717", "x --- y"],
        metrics={"trust_mean": 0.512, "n": 3, "ok": True, "none": None, "nested": {"k": [1, {"j": "v"}]}},
        extra_frontmatter={"env": {"note": "caf\u00e9 \u2014 line1\nline2", "when": "2026-11-09"}},
    )
    raw = (store.repo_path / path).read_text(encoding="utf-8")
    block = raw[4:raw.index("\n---\n\n") + 1]
    loaded = yaml.safe_load(block)
    assert loaded["tags"] == ["a", "717", "x --- y"] and loaded["metrics"]["nested"] == {"k": [1, {"j": "v"}]}
    assert block == yaml.dump(loaded, default_flow_style=False, sort_keys=False)


async def test_the_captains_log_is_written_and_read_as_before(store):
    path = await store.append_captains_log("log body", "m")
    entry = await store.read_entry(path, reader_id="bob")
    assert entry is not None and entry["frontmatter"]["author"] == "captain"
    assert entry["frontmatter"]["classification"] == "ship"


async def test_a_publish_of_a_note_holding_a_set_bytes_and_a_date_keeps_it_readable(store):
    """Guard: values ``safe_load`` builds and ``yaml.dump`` writes without a tag stay as they were through ``publish``."""
    path = "notebooks/alice/typed.md"
    _hand_made(store, path, "---\nauthor: alice\nclassification: private\nkinds: !!set {p, q}\nraw: !!binary aGk=\nwhen: 2026-01-01\n---\n\ncoolant private body\n")
    assert path in await _hits(store, "alice"), "premise: the author finds her own note"
    await store.publish(path, "alice")
    assert "!!python" not in (store.repo_path / path).read_text(encoding="utf-8")
    own = await store.read_entry(path, reader_id="alice")
    assert own is not None and own["frontmatter"]["kinds"] == {"p", "q"} and own["frontmatter"]["raw"] == b"hi"
    assert await store.read_entry(path, reader_id="bob") is None


@pytest.mark.parametrize(("tags", "written"), [
    pytest.param(None, False, id="none"),
    pytest.param([], False, id="an-empty-list"),
    pytest.param("", False, id="an-empty-string"),
    pytest.param(["a", "b"], True, id="a-list-of-text"),
])
async def test_tags_that_are_absent_empty_or_text_are_written_as_before(store, tags, written):
    path = await store.write_notebook("alice", "tagged", "coolant body", tags=tags)
    entry = await store.read_entry(path, reader_id="alice")
    assert entry is not None and ("tags" in entry["frontmatter"]) is written


def test_the_notebook_route_writes_a_list_of_tags_as_before(store):
    with TestClient(_app(store)) as client:
        response = client.post("/api/records/notebooks/alice", json={"topic": "t", "content": "c", "tags": ["a"]})
    assert response.status_code == 200
    assert "tags:\n- a\n" in (store.repo_path / "notebooks" / "alice" / "t.md").read_text(encoding="utf-8")


@pytest.mark.xfail(reason="BF-940 slice 2 M2: not built", raises=AssertionError, strict=True)
class TestAFrontmatterTheStoreWritesIsOneTheStoreReads:
    @pytest.mark.parametrize(("slug", "kwargs"), [
        pytest.param("review-nominal", {"metrics": {"sample": (1, 2)}}, id="a-tuple-in-metrics-case-B"),
        pytest.param("review---nominal", {"metrics": {"sample": (1, 2)}}, id="a-tuple-in-metrics-and-three-hyphens-in-the-topic-case-A"),
        pytest.param("review-extra", {"extra_frontmatter": {"env": (1, 2)}}, id="a-tuple-in-an-envelope"),
        pytest.param("review-pairs", {"metrics": {"sample": [(1, 2), (3, 4)]}}, id="a-list-of-tuples"),
        pytest.param("review-deep", {"metrics": {"a": {"b": ({"c": (1,)},)}}}, id="tuples-nested-in-mappings"),
    ])
    async def test_a_tuple_is_written_as_a_list_and_the_note_stays_private(self, store, slug, kwargs):
        path = await store.write_notebook("alice", slug, "coolant private body", **kwargs)
        assert path in await _hits(store, "alice"), "premise: the author finds her own note"
        assert "!!python" not in (store.repo_path / path).read_text(encoding="utf-8")
        assert await store.read_entry(path, reader_id="bob") is None
        assert path not in await _hits(store, "bob")
        own = await store.read_entry(path, reader_id="alice")
        assert own is not None and own["frontmatter"]["classification"] == "private"
        await store.publish(path, "alice")
        assert await store.read_entry(path, reader_id="bob") is None

    @pytest.mark.parametrize("where", ["metrics", "extra_frontmatter"])
    @pytest.mark.parametrize("value", [
        pytest.param(_Plain(), id="an-object"),
        pytest.param(collections.OrderedDict(a=1), id="an-ordered-dict"),
        pytest.param(frozenset({1}), id="a-frozenset"),
        pytest.param(_Pair(1, 2), id="a-named-tuple"),
        pytest.param(_Text("x"), id="a-str-subclass"),
        pytest.param({(1, 2): "x"}, id="a-tuple-as-a-key"),
    ])
    async def test_a_value_no_reader_loads_is_refused_before_a_file_is_touched(self, store, where, value):
        first = await store.write_notebook("alice", "keep", "coolant first body", metrics={"m": [1]})
        before = (store.repo_path / first).read_bytes()
        kwargs = {"metrics": {"sample": value}} if where == "metrics" else {"extra_frontmatter": {"env": value}}
        key = "metrics" if where == "metrics" else "env"
        refused = []
        for callsign, slug in (("alice", "keep"), ("zed", "fresh")):
            try:
                await store.write_notebook(callsign, slug, "coolant other body", **kwargs)
            except ValueError as exc:
                refused.append(str(exc))
        assert len(refused) == 2, "an update and a create are both refused with ValueError"
        assert all(key in message for message in refused)
        assert (store.repo_path / first).read_bytes() == before
        assert [p.name for p in store.repo_path.rglob("*.md")] == ["keep.md"] and not (store.repo_path / "notebooks" / "zed").exists()

    async def test_a_publish_of_a_hand_made_note_holding_an_ordered_mapping_writes_no_python_tag(self, store):
        """``safe_load`` builds a list of tuples for ``!!omap``; ``publish`` re-dumps what it loaded."""
        path = "notebooks/alice/omap.md"
        _hand_made(store, path, "---\nauthor: alice\nclassification: private\nsteps: !!omap [a: 1, b: 2]\n---\n\ncoolant private body\n")
        assert path in await _hits(store, "alice"), "premise: the author finds her own note"
        await store.publish(path, "alice")
        assert "!!python" not in (store.repo_path / path).read_text(encoding="utf-8")
        assert await store.read_entry(path, reader_id="bob") is None

    def test_a_skill_rewrite_of_a_file_holding_an_ordered_mapping_stays_readable(self, tmp_path):
        path = tmp_path / "demo-skill" / "SKILL.md"
        path.parent.mkdir()
        path.write_text("---\nname: demo-skill\ndescription: Use when needed\nsteps: !!omap [a: 1, b: 2]\n---\n\n# Demo\n", encoding="utf-8")
        entry = parse_skill_file(path)
        assert entry is not None, "premise: it parses before the rewrite"
        entry.department = "operations"
        CognitiveSkillCatalog._rewrite_frontmatter(path, entry)
        assert "!!python" not in path.read_text(encoding="utf-8")
        assert parse_skill_file(path) is not None


@pytest.mark.xfail(reason="BF-940 slice 2 M2: not built", raises=AssertionError, strict=True)
class TestANumericTagReachesTheIndexAndANonListIsRefused:
    @pytest.mark.parametrize("tags", [
        pytest.param([717], id="an-integer"),
        pytest.param([717, "x"], id="an-integer-and-text"),
        pytest.param([1.5], id="a-float"),
        pytest.param([True], id="a-boolean"),
    ])
    async def test_a_tag_that_is_not_text_reaches_the_index_on_write_and_on_backfill(self, store, tags):
        layer = SemanticKnowledgeLayer(store.repo_path.parent / "semantic")
        column = _Collection()
        layer._collections = {"records": column}
        store.set_semantic_indexer(layer)
        path = await store.write_notebook("alice", "tagged", "coolant body", tags=tags, classification="ship")
        own = await store.read_entry(path, reader_id="alice")
        assert own is not None and own["frontmatter"]["tags"] == tags, "premise: the tags are kept as given"
        assert f"record_{path}" in column.rows, "the write indexed the record"
        assert str(tags[0]) in column.rows[f"record_{path}"][0].split("\n")[0]
        column.rows.clear()
        assert await layer.reindex_records(store) == 1 and f"record_{path}" in column.rows

    @pytest.mark.parametrize("tags", [
        pytest.param(717, id="an-integer"),
        pytest.param("abc", id="a-string"),
        pytest.param({"a": 1}, id="a-mapping"),
        pytest.param({"x"}, id="a-set"),
    ])
    async def test_a_tags_value_that_is_not_a_list_is_refused(self, store, tags):
        try:
            await store.write_notebook("alice", "scalar", "coolant body", tags=tags)
        except ValueError as exc:
            message = str(exc)
        else:
            message = None
        assert message is not None and "tags must be a list" in message
        assert list(store.repo_path.rglob("*.md")) == []

    async def test_a_tuple_of_tags_is_written_as_a_list(self, store):
        path = await store.write_notebook("alice", "tupled", "coolant body", tags=("a", "b"))
        assert "!!python" not in (store.repo_path / path).read_text(encoding="utf-8")
        own = await store.read_entry(path, reader_id="alice")
        assert own is not None and own["frontmatter"]["tags"] == ["a", "b"]

    def test_the_notebook_route_answers_400_for_a_tags_value_that_is_not_a_list(self, store):
        with TestClient(_app(store)) as client:
            response = client.post("/api/records/notebooks/alice", json={"topic": "t", "content": "c", "tags": 717})
        assert response.status_code == 400 and "tags must be a list" in response.json()["error"]
```

**N1-2.** `tests/test_bf940_frontmatter_framing.py` (slice 1's T12, `test_a_private_note_with_three_hyphens_in_its_topic_stays_private_when_its_metrics_cannot_load`). It writes case A through `write_notebook` and asserts the writer wrote `!!python/tuple`; after M2 the writer does not, so the document is hand-made (the shape an older writer or a hand edit leaves, which A1's fallback still reads). It is the only existing test that passes a tuple to a writer (section 11). It stays a guard that passes on both trees. SEARCH occurs once:
SEARCH:
```
    store = await _store(tmp_path, monkeypatch)
    path = await store.write_notebook("alice", "review---nominal", "coolant private body", metrics={"sample": (1, 2)})
    raw = (store.repo_path / path).read_text(encoding="utf-8")
    assert "topic: review---nominal" in raw and "!!python/tuple" in raw, "premise: a tag safe_load refuses, after a ---"
```
REPLACE:
```
    store = await _store(tmp_path, monkeypatch)
    path = "notebooks/alice/review---nominal.md"  # BF-940 slice 2: the writer no longer writes the tag, so the document is hand-made
    raw = "---\nauthor: alice\nclassification: private\nstatus: draft\ntopic: review---nominal\nmetrics:\n  sample: !!python/tuple\n  - 1\n  - 2\n---\n\ncoolant private body\n"
    (store.repo_path / "notebooks" / "alice").mkdir(parents=True)
    (store.repo_path / path).write_text(raw, encoding="utf-8")
    assert "topic: review---nominal" in raw and "!!python/tuple" in raw, "premise: a tag safe_load refuses, after a ---"
```

### 7.2 M2

**P2-1.** `src/probos/utils/frontmatter.py`, the docstring and the imports (once):
SEARCH:
```
it left the frontmatter. This module only frames a document; it loads nothing. Each caller loads the block in its own frame,
so PyYAML's recursion frontier stays where it was (BF-952 A6, L30). It imports nothing of ProbOS (``utils`` holds pure
helpers any layer may import).
"""

from __future__ import annotations

import re
```
REPLACE:
```
it left the frontmatter. This module frames a document (``split_frontmatter`` and ``base_split_frontmatter`` load nothing); each
caller loads the block in its own frame, so PyYAML's recursion frontier stays where it was (BF-952 A6, L30). It imports nothing of
ProbOS (``utils`` holds pure helpers any layer may import). BF-940 slice 2 adds ``dump_frontmatter``, the writers' half: the one
place a frontmatter mapping becomes YAML text, so that a document the store writes is a document the store reads (L24).
"""

from __future__ import annotations

import re
from typing import Any

import yaml
```

**P2-2.** `src/probos/utils/frontmatter.py`, the end of the file (the `return parts[1], parts[2]` line occurs once):
SEARCH:
```
    parts = text.split("---", 2) if text.startswith("---") else []
    if len(parts) >= 3:
        return parts[1], parts[2]
    return None, text
```
REPLACE:
```
    parts = text.split("---", 2) if text.startswith("---") else []
    if len(parts) >= 3:
        return parts[1], parts[2]
    return None, text


_UNWRITABLE = (yaml.YAMLError, RecursionError)


def _dump(mapping: dict[Any, Any]) -> str:
    text = yaml.safe_dump(mapping, default_flow_style=False, sort_keys=False)
    if type(yaml.safe_load(text)) is not dict:
        raise yaml.YAMLError("frontmatter did not read back as a mapping")
    return text


def dump_frontmatter(mapping: dict[Any, Any]) -> str:
    """Write ``mapping`` as the YAML a document's frontmatter holds, or raise ``ValueError`` (BF-940 slice 2, L24).

    A document the store writes is a document the store reads. ``yaml.dump`` wrote a tuple, an ``OrderedDict``, a ``frozenset``
    or any other object with a ``!!python/`` tag, which no reader loads: the document read as ``{}``, at the default ``ship``
    classification, whoever its author. The text here is ``yaml.safe_dump``'s with the arguments the writers used, so it is
    byte-identical to ``yaml.dump``'s for every value ``safe_load`` builds, a tuple is a list, and an object ``safe_dump``
    refuses is a ``ValueError``. The text is then loaded once more, because ``safe_dump`` writes what ``safe_load`` refuses (a
    tuple as a mapping key). A value nested beyond the recursion limit is a ``ValueError`` too. The message names the top-level
    keys at fault and the error's type, never a value (AD-1140's fail-fast tier); the caller has touched no file yet.
    """
    try:
        return _dump(mapping)
    except _UNWRITABLE as exc:
        keys = []
        for key, value in mapping.items():
            try:
                _dump({key: value})
            except _UNWRITABLE:
                keys.append(str(key))
        raise ValueError(
            "frontmatter key(s) %s hold a value that cannot be written so that it reads back (%s); use strings, numbers, "
            "booleans, None, dates, and lists or mappings of them" % (", ".join(keys) or "(none singly)", type(exc).__name__)
        ) from exc
```

**P2-3.** `src/probos/knowledge/records_store.py`, the import (once):
SEARCH:
```
from probos.utils.frontmatter import base_split_frontmatter, split_frontmatter
```
REPLACE:
```
from probos.utils.frontmatter import base_split_frontmatter, dump_frontmatter, split_frontmatter
```

**P2-4.** `src/probos/knowledge/records_store.py`, `write_entry`'s docstring (once; it said the writer tags a tuple and the document reads `{}`):
SEARCH:
```
        the frontmatter **before** ``yaml.dump``. They round-trip through
        ``_parse_document`` when every value is one YAML's safe loader builds
        (a string, number, boolean, date, or a list or mapping of them), a
        value holding ``---`` included: the frontmatter ends at a line of its
        own (BF-940, #1686). ``yaml.dump`` writes a tuple or another Python
        object with a
        ``!!python/`` tag, which no reader loads (BF-952 L24): a document
        holding one reads as ``{}``, so at the default ``ship`` classification
        for every reader, unless a ``---`` before the tag lets the base's
        earlier cut read (BF-940 A1; L10 of its contract). The AD-1138
```
REPLACE:
```
        the frontmatter **before** the dump. They round-trip through
        ``_parse_document`` when every value is one YAML's safe loader builds
        (a string, number, boolean, date, or a list or mapping of them), a
        value holding ``---`` included: the frontmatter ends at a line of its
        own (BF-940, #1686). The text is written by
        :func:`probos.utils.frontmatter.dump_frontmatter` (BF-940 slice 2,
        L24): a tuple is written as a list, and a value no reader loads (any
        other Python object: ``yaml.dump`` wrote it with a ``!!python/`` tag,
        so the document read as ``{}``, at the default ``ship`` classification,
        whoever its author) raises ``ValueError`` naming the key, before any
        file is touched. ``tags`` must be a list or a tuple (L27). The AD-1138
```

**P2-5.** `src/probos/knowledge/records_store.py`, the tags guard, after the extra-frontmatter check (once):
SEARCH:
```
                raise ValueError(
                    "extra_frontmatter may not set store-owned keys: "
                    + ", ".join(collisions)
                )

        # Build frontmatter
```
REPLACE:
```
                raise ValueError(
                    "extra_frontmatter may not set store-owned keys: "
                    + ", ".join(collisions)
                )
        if tags and not isinstance(tags, (list, tuple)):  # BF-940 slice 2 (L27): the readers iterate tags and the index joins them
            raise ValueError("tags must be a list")

        # Build frontmatter
```

**P2-6.** `src/probos/knowledge/records_store.py`, `write_entry`'s dump (the two lines occur once):
SEARCH:
```
        fm_yaml = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
        full_content = f"---\n{fm_yaml}---\n\n{content}"
```
REPLACE:
```
        fm_yaml = dump_frontmatter(frontmatter)  # BF-940 slice 2 (L24): a tuple is a list; an unreadable value raises
        full_content = f"---\n{fm_yaml}---\n\n{content}"
```

**P2-7.** `src/probos/knowledge/records_store.py`, `append_captains_log` and `publish` (each SEARCH once):
SEARCH:
```
            fm_yaml = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
            file_path.parent.mkdir(parents=True, exist_ok=True)
```
REPLACE:
```
            fm_yaml = dump_frontmatter(frontmatter)  # BF-940 slice 2 (L24): the one writer function
            file_path.parent.mkdir(parents=True, exist_ok=True)
```
SEARCH:
```
        fm_yaml = yaml.dump(fm, default_flow_style=False, sort_keys=False)
```
REPLACE:
```
        fm_yaml = dump_frontmatter(fm)  # BF-940 slice 2 (L24): what safe_load built (an !!omap is a list of tuples) is written readably
```

**P2-8.** `src/probos/knowledge/semantic.py:406`, the join (once):
SEARCH:
```
            header += f" [{', '.join(tags)}]"
```
REPLACE:
```
            header += f" [{', '.join(str(tag) for tag in tags)}]"  # BF-940 slice 2 (L27): a tag may be a number
```

**P2-9.** `src/probos/cognitive/skill_catalog.py` (each SEARCH once):
SEARCH:
```
from probos.utils.frontmatter import split_frontmatter
```
REPLACE:
```
from probos.utils.frontmatter import dump_frontmatter, split_frontmatter
```
SEARCH:
```
        new_yaml = yaml.dump(fm, default_flow_style=False, sort_keys=False)
```
REPLACE:
```
        new_yaml = dump_frontmatter(fm)  # BF-940 slice 2 (L24): one writer function for every frontmatter
```

**N2-1.** New file `tests/test_bf940_s2_dump_frontmatter.py`:

```python
"""BF-940 slice 2 (#1686): ``dump_frontmatter``, the one place a frontmatter mapping becomes YAML text. Pure; no store."""

from __future__ import annotations

import collections
import datetime
import decimal
from typing import Any, NamedTuple

import pytest
import yaml

from probos.utils.frontmatter import dump_frontmatter

_SECRET = "SECRET_VALUE_NEVER_IN_A_MESSAGE"


class _Plain:
    pass


class _Text(str):
    pass


class _Pair(NamedTuple):
    a: int
    b: int


def _nested(depth: int) -> Any:
    value: Any = "leaf"
    for _ in range(depth):
        value = {"k": value}
    return value


@pytest.mark.parametrize("mapping", [
    pytest.param({"author": "alice", "classification": "private", "created": "2026-11-09T10:00:00+00:00", "tags": ["a", "717"], "metrics": {"trust_mean": 0.512, "active_agents": 54}}, id="a-store-envelope"),
    pytest.param({"topic": "x --- y: z", "note": "caf\u00e9 \u2014 line1\nline2\n", "long": "word " * 80}, id="dashes-unicode-multiline-and-a-long-value"),
    pytest.param({"none": None, "yes": True, "f": 1.5e-7, "big": 10**30, "empty": [], "nothing": {}}, id="none-bool-float-big-int-and-empty-containers"),
    pytest.param({"when": datetime.date(2026, 1, 1), "at": datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc), "raw": b"hi", "kinds": {1, 2}}, id="a-date-a-datetime-bytes-and-a-set"),
    pytest.param({"a": {"b": {"c": [1, [2, 3], {"d": "e"}]}}}, id="nested-lists-and-mappings"),
    pytest.param({1: "int key", None: "none key"}, id="keys-that-are-not-text"),
])
def test_a_mapping_the_readers_load_is_written_as_yaml_dump_wrote_it(mapping):
    assert dump_frontmatter(mapping) == yaml.dump(mapping, default_flow_style=False, sort_keys=False)


def test_a_tuple_is_written_as_a_list_and_nothing_python_is_tagged():
    text = dump_frontmatter({"t": (1, 2), "n": [(3, 4)], "m": {"k": ({"j": (5,)},)}})
    assert "!!python" not in text
    assert yaml.safe_load(text) == {"t": [1, 2], "n": [[3, 4]], "m": {"k": [{"j": [5]}]}}


@pytest.mark.parametrize("value", [
    pytest.param(_Plain(), id="an-object"),
    pytest.param(collections.OrderedDict(a=1), id="an-ordered-dict"),
    pytest.param(collections.defaultdict(int, a=1), id="a-default-dict"),
    pytest.param(frozenset({1}), id="a-frozenset"),
    pytest.param(_Pair(1, 2), id="a-named-tuple"),
    pytest.param(_Text("x"), id="a-str-subclass"),
    pytest.param(decimal.Decimal("1.5"), id="a-decimal"),
    pytest.param(1 + 2j, id="a-complex"),
])
def test_a_value_no_reader_loads_is_refused_naming_its_top_level_key(value):
    with pytest.raises(ValueError) as info:
        dump_frontmatter({"k_good": 1, "k_bad": {"deep": [value]}, "k_fine": "x"})
    message = str(info.value)
    assert "k_bad" in message and "k_good" not in message and "k_fine" not in message


def test_a_tuple_used_as_a_key_is_refused_though_safe_dump_writes_it():
    text = yaml.safe_dump({"k": {(1, 2): "x"}})
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(text)  # premise: safe_dump wrote what safe_load refuses
    with pytest.raises(ValueError) as info:
        dump_frontmatter({"k_good": 1, "k_bad": {(1, 2): "x"}})
    assert "k_bad" in str(info.value) and "k_good" not in str(info.value)


def test_a_value_is_never_in_the_message():
    with pytest.raises(ValueError) as info:
        dump_frontmatter({"k_bad": _Text(_SECRET)})
    assert _SECRET not in str(info.value)


def test_a_mapping_nested_too_deeply_is_a_value_error_not_a_recursion_error():
    assert yaml.safe_load(dump_frontmatter({"k": _nested(100)}))["k"]["k"]
    with pytest.raises(ValueError) as info:
        dump_frontmatter({"k_good": 1, "k_bad": _nested(600)})
    assert "k_bad" in str(info.value) and "k_good" not in str(info.value)


def test_an_empty_mapping_is_written_and_read_back():
    assert dump_frontmatter({}) == "{}\n" and yaml.safe_load("{}\n") == {}
```

**N2-2.** Remove the two markers of N1-1 (each SEARCH once; the class lines stay):
SEARCH:
```
@pytest.mark.xfail(reason="BF-940 slice 2 M2: not built", raises=AssertionError, strict=True)
class TestAFrontmatterTheStoreWritesIsOneTheStoreReads:
```
REPLACE:
```
class TestAFrontmatterTheStoreWritesIsOneTheStoreReads:
```
SEARCH:
```
@pytest.mark.xfail(reason="BF-940 slice 2 M2: not built", raises=AssertionError, strict=True)
class TestANumericTagReachesTheIndexAndANonListIsRefused:
```
REPLACE:
```
class TestANumericTagReachesTheIndexAndANonListIsRefused:
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

**BF-940 (DATE), #1686 -- a frontmatter the store writes is one the store reads: one writer function refuses what no reader loads, a tags value that is not a list is refused and a numeric tag reaches the semantic index (slice 2 of the issue).**
- **Base.** `yaml.dump` wrote a tuple, an `OrderedDict` or any other object in `metrics`, `extra_frontmatter` or a re-dumped `!!omap` with a `!!python/` tag that no reader loads: the note read as `{}`, so at the default `ship` classification for every reader, and its author's `publish` raised `PermissionError` (a privacy defect, P1; case B). `tags: [717]` was written and found by keyword search but never reached the semantic index (`TypeError` at `semantic.py:406`, on write and on every backfill), and a scalar `tags` from the notebook route made `list_entries(tags=...)` raise.
- **Fix.** New `dump_frontmatter` in `utils/frontmatter.py` (`yaml.safe_dump` with a read-back check) is the one function `write_entry`, `append_captains_log`, `publish` and the skill catalog's rewrite call: a tuple is written as a list, an unreadable value raises `ValueError` naming the key before any file is touched, and the bytes of every readable value are unchanged. `write_entry` refuses a `tags` that is not a list or tuple (the route answers 400); the index joins `str(tag)`. Contract `prompts/bf-940-frontmatter-writer-policy.md`. Refs #1686: this closes its L24 and L27 boxes; the issue stays open for L19 (decided: a typed parse result, the Captain's call) and F7-1 (decided: serialise inside the route's boundary).

```

**P3-2.** `DECISIONS.md`. Append after slice 1's entry. Its last bullet occurs once. Replace `DATE` with M3's date.
SEARCH:
```
- *Residual.* L1 to L17 of the contract. *Reversal.* Revert the BF-940 commits.
```
REPLACE:
```
- *Residual.* L1 to L17 of the contract. *Reversal.* Revert the BF-940 commits.

### BF-940 -- A frontmatter the store writes is one the store reads (slice 2; DATE, #1686)

- *Scope.* `utils/frontmatter.py` (`dump_frontmatter`), the three writers of `RecordsStore` and the skill catalog's rewrite, `write_entry`'s `tags` guard, `semantic.py`'s join, tests. Contract `prompts/bf-940-frontmatter-writer-policy.md`. Slice 2 of #1686.
- *G0 (scope).* L24 and L27 together (one boundary, one test file); L19 and F7-1 stay in #1686, which stays open (`Refs`). Rejected: L24 alone; L24 with L19 (a read-side visibility decision for the Captain); all four.
- *G1 (the writer).* `safe_dump` with a read-back check, one function for every writer; a tuple is a list; an object is a `ValueError`. Rejected: a type-walking normaliser; a JSON-native refusal; a read-side loader for `!!python/tuple` (a persisted-format extension and, with `UnsafeLoader`, a code-execution path).
- *G2 (tags).* A non-list `tags` is refused at `write_entry`; elements are written as given and joined as text by the index. Rejected: converting numbers to text at write; refusing non-text elements.
- *G3 (decided, not built).* L19: a typed parse result, readers withhold from all but the Captain and the path's owner, writers of an existing note refuse (a Captain decision); F7-1: `TypeAdapter(Any).dump_python(mode="json")` inside the route's boundary.
- *Residual.* L1 to L10 of the contract. *Reversal.* Revert the BF-940 slice 2 commits.
```

**P3-3.** `docs/development/deterministic-ship.md` (the clause occurs once, in the Persistence row):
SEARCH:
```
unless the base's earlier cut of it parses and it reads as that (#1686). |
```
REPLACE:
```
unless the base's earlier cut of it parses and it reads as that (#1686); the store's own writers no longer produce one (a tuple is written as a list and a value no reader loads is refused, BF-940 slice 2). |
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited.

### 7.4 The census (an orchestrator step; no repository file)

I have no live system. Run on a read-only copy of the vessel's `ship-records` (the path from the live process, `%LOCALAPPDATA%\ProbOS\data`, never `d:\ProbOS\data`), with M2's tree first on `PYTHONPATH` (it imports `probos.utils.frontmatter` from slice 1): `$env:PYTHONPATH = '<build tree>\src'; PY -B -P census_bf940_s2.py <copy>`. It reads each file as the store does (`read_text`: CRLF and CR become LF), frames it with `split_frontmatter`, loads it with `yaml.safe_load`, and prints paths, key names, type names, counts and a label from the four-label vocabulary, **never a value**. Exit 0: nothing flagged. 1: flags (read each). 2: the positive control was not flagged, or bad arguments (do not trust the run). Flags: `PYTHON_TAG` (the block holds `!!python/`), `NOT_LOADING` (`YAMLError`), `LOAD_RECURSION`, `LOAD_ERROR` (a constructor error such as `2026-13-05`), `NOT_MAPPING`, `TAGS_NOT_LIST`, `TAGS_NON_TEXT` (a tag element that is not a `str`), `BYTES_NOT_UTF8` and `DEEP` (80 levels or more: F7-1; a route stub failed from 100) and `UNREADABLE`. A `NOT_LOADING` document whose written `classification:` line says `private` or `department` is printed `READ AS ship (EXPOSED)`: it is read as `{}` by `read_entry` today (unless slice 1's A1 fallback reads the base's cut of it). It also prints, per key, the count of each value type, the type of each `tags` element and of each `metrics` value, the extra (not store-owned) keys, and the values that are not JSON-native. The positive control is four documents in a temporary folder walked by the same `census` function: a tuple tag, a numeric tag and an unparsable block, which must be flagged as named, and a clean one, which must not.

```python
"""BF-940 slice 2 census (an orchestrator step; not a repository file). Read-only: it opens files for reading and never writes.

usage:  $env:PYTHONPATH = "<build tree>/src"; python -B -P census_bf940_s2.py <read-only copy of ship-records>
exit 0 nothing flagged; 1 flags (read each); 2 the positive control was not flagged, or bad arguments.
Prints paths, key names, type names, counts and a classification label of the four-label vocabulary; never a value.
"""
from __future__ import annotations

import collections
import pathlib
import sys
import tempfile

import yaml

from probos.utils.frontmatter import split_frontmatter

LABELS = ("private", "department", "ship", "fleet")
GATED = ("private", "department")
STORE_KEYS = frozenset({"author", "classification", "status", "created", "updated", "revision", "department", "topic", "tags", "metrics"})
DEEP = 80  # a stub of the records route returned 500 from 100 levels (F7-1); flag well before it
JSON_NATIVE = (str, int, float, bool, type(None), dict, list)


def walk(value):
    stack = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        yield node, depth
        if isinstance(node, dict):
            stack.extend((child, depth + 1) for child in list(node.keys()) + list(node.values()))
        elif isinstance(node, (list, tuple, set, frozenset)):
            stack.extend((child, depth + 1) for child in node)


def written_label(block):
    for line in block.splitlines():
        if line.startswith("classification:"):
            word = line.split(":", 1)[1].strip().strip("'\"")
            return word if word in LABELS else "other"
    return "absent"


def examine(text, stats):
    if not text.startswith("---"):
        return None
    block, _ = split_frontmatter(text)
    if block is None:
        stats["opener with no closing line"] += 1
        return {"flags": [], "label": "n/a"}
    flags = []
    if "!!python/" in block:
        flags.append("PYTHON_TAG")
    loaded = None
    try:
        loaded = yaml.safe_load(block)
    except yaml.YAMLError:
        flags.append("NOT_LOADING")
    except RecursionError:
        flags.append("LOAD_RECURSION")
    except Exception:
        flags.append("LOAD_ERROR")
    if loaded is not None and type(loaded) is not dict:
        flags.append("NOT_MAPPING")
    if type(loaded) is dict:
        stats["loaded as a mapping"] += 1
        for key, value in loaded.items():
            stats["key:%s -> %s" % (key, type(value).__name__)] += 1
            if key not in STORE_KEYS:
                stats["extra key (not store-owned): %s" % key] += 1
        tags = loaded.get("tags")
        if "tags" in loaded and type(tags) is not list:
            flags.append("TAGS_NOT_LIST")
        elif type(tags) is list:
            for tag in tags:
                stats["tag element type: %s" % type(tag).__name__] += 1
            if any(type(tag) is not str for tag in tags):
                flags.append("TAGS_NON_TEXT")
        metrics = loaded.get("metrics")
        if type(metrics) is dict:
            for value in metrics.values():
                stats["metrics value type: %s" % type(value).__name__] += 1
        deepest = 0
        for node, depth in walk(loaded):
            deepest = max(deepest, depth)
            if not isinstance(node, JSON_NATIVE):
                stats["value not JSON-native: %s" % type(node).__name__] += 1
            if type(node) is bytes:
                try:
                    node.decode("utf-8")
                except UnicodeDecodeError:
                    flags.append("BYTES_NOT_UTF8")
        if deepest >= DEEP:
            flags.append("DEEP")
    return {"flags": sorted(set(flags)), "label": written_label(block)}


def census(root):
    stats = collections.Counter()
    rows = []
    files = documents = 0
    for path in sorted(pathlib.Path(root).rglob("*")):
        if not path.is_file() or ".git" in path.relative_to(root).parts:
            continue
        files += 1
        try:
            text = path.read_text(encoding="utf-8")  # as the store reads it: CRLF and CR become LF
        except (OSError, UnicodeDecodeError):
            rows.append((path.relative_to(root).as_posix(), ["UNREADABLE"], "n/a"))
            continue
        result = examine(text, stats)
        if result is None:
            continue
        documents += 1
        if result["flags"]:
            rows.append((path.relative_to(root).as_posix(), result["flags"], result["label"]))
    return files, documents, rows, stats


CONTROL = {
    "tuple.md": ("---\nauthor: alice\nclassification: private\nmetrics:\n  sample: !!python/tuple\n  - 1\n  - 2\n---\n\nbody\n", {"PYTHON_TAG", "NOT_LOADING"}),
    "numeric-tag.md": ("---\nauthor: alice\nclassification: private\ntags:\n- 717\n---\n\nbody\n", {"TAGS_NON_TEXT"}),
    "unparsable.md": ("---\nauthor: alice\nclassification: department\ntopic: [unclosed\n---\n\nbody\n", {"NOT_LOADING"}),
    "clean.md": ("---\nauthor: alice\nclassification: private\ntags:\n- a\n---\n\nbody\n", set()),
}


def control():
    with tempfile.TemporaryDirectory() as tmp:
        for name, (text, _) in CONTROL.items():
            (pathlib.Path(tmp) / name).write_text(text, encoding="utf-8", newline="")
        _, _, rows, _ = census(tmp)
    got = {path: set(flags) for path, flags, _ in rows}
    return all(got.get(name, set()) == expected for name, (_, expected) in CONTROL.items())


def main(argv):
    if len(argv) != 1:
        print("usage: python census_bf940_s2.py <read-only copy of ship-records>")
        return 2
    if not control():
        print("CONTROL NOT FLAGGED: the comparison cannot be trusted")
        return 2
    print("control: tuple tag, numeric tag and unparsable frontmatter flagged, the clean document not")
    files, documents, rows, stats = census(argv[0])
    print("files: %d; documents opening with ---: %d; flagged: %d" % (files, documents, len(rows)))
    for line in sorted(stats):
        print("  %6d  %s" % (stats[line], line))
    exposed = 0
    for path, flags, label in rows:
        gated_read_as_ship = "NOT_LOADING" in flags and label in GATED
        exposed += gated_read_as_ship
        print("FLAG %s | %s | written classification: %s%s" % (path, ",".join(flags), label, " | READ AS ship (EXPOSED)" if gated_read_as_ship else ""))
    print("exposed (written private or department, reads as ship): %d" % exposed)
    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

Measured by hand driver on synthetic trees (never on a vessel; the code above extracted from this text and run): a tree of four files (an ordinary note, a numeric-tag note, an unparsable private note, a `!!python/tuple` department note): exit 1, three flags, `exposed: 2`, the control line printed; no arguments: exit 2. An earlier run of the same logic, without the docstring, over nine files (adding a tuple in an envelope, a 90-level value, a `!!binary` value, an opener with no closing line and a raw bill): exit 1 with five flags and `exposed: 1`; a tree of one ordinary note: exit 0. What a difference means: a `PYTHON_TAG` or `NOT_LOADING` document is an L24 survivor (a Captain's repair or L19's slice, D1.5); an `EXPOSED` one is a note written private and read as `ship` today, which goes to the Captain; `TAGS_NON_TEXT` documents are indexed after M2 (D2); `DEEP` and `BYTES_NOT_UTF8` are F7-1's.

## 8. What this does NOT change

`_parse_document`, the search's reader and A1's fallback, `record_is_readable`, `read_entry`'s gate, `list_entries` (but for its `tags` test, A1, D6), the keyword search's ranking, slice 1's framing; `_write_config` (a constant mapping, not a frontmatter); the body writers (`dreaming.py:1371`, `procedure_store.py`, `commands_gap.py`, `routers/gaps.py`); the AD-1138 sidecar and its 4,000-character cap; `routers/records.py` (F7-1 is a later slice; the notebook route is untouched, only its `ValueError` handler now sees a new message); the readers of `tags` outside the index (`backlinks.py:73` and `:182`, `routers/records.py:247`); `is_exit_note_text`; the AD-1344, AD-1346 and BF-892 inventories (no write site is added or moved); config; dependencies (PyYAML is already one). A document on disk is never rewritten by this slice.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| 1 | M2 | src/probos/utils/frontmatter.py | `text = yaml.safe_dump(mapping, default_flow_style=False, sort_keys=False)` | `text = yaml.dump(mapping, default_flow_style=False, sort_keys=False)` | test_a_tuple_is_written_as_a_list_and_nothing_python_is_tagged, TestAFrontmatterTheStoreWritesIsOneTheStoreReads::test_a_tuple_is_written_as_a_list_and_the_note_stays_private (5 cases), ::test_a_publish_of_a_hand_made_note_holding_an_ordered_mapping_writes_no_python_tag, ::test_a_skill_rewrite_of_a_file_holding_an_ordered_mapping_stays_readable, TestANumericTagReachesTheIndexAndANonListIsRefused::test_a_tuple_of_tags_is_written_as_a_list (9 cases; the read-back alone refuses a tag, so a tuple is refused instead of written as a list) |
| 2 | M2 | src/probos/utils/frontmatter.py | `if type(yaml.safe_load(text)) is not dict:` | `if False:` | test_a_tuple_used_as_a_key_is_refused_though_safe_dump_writes_it, TestAFrontmatterTheStoreWritesIsOneTheStoreReads::test_a_value_no_reader_loads_is_refused_before_a_file_is_touched[a-tuple-as-a-key-metrics, a-tuple-as-a-key-extra_frontmatter] |
| 3 | M2 | src/probos/utils/frontmatter.py | `_UNWRITABLE = (yaml.YAMLError, RecursionError)` | `_UNWRITABLE = (yaml.YAMLError,)` | test_a_mapping_nested_too_deeply_is_a_value_error_not_a_recursion_error |
| 4 | M2 | src/probos/utils/frontmatter.py | `keys.append(str(key))` | `keys.append("?")` | test_a_value_no_reader_loads_is_refused_naming_its_top_level_key (8 cases), TestAFrontmatterTheStoreWritesIsOneTheStoreReads::test_a_value_no_reader_loads_is_refused_before_a_file_is_touched (12 cases), test_a_tuple_used_as_a_key_is_refused_though_safe_dump_writes_it, test_a_mapping_nested_too_deeply_is_a_value_error_not_a_recursion_error (22 cases) |
| 5 | M2 | src/probos/knowledge/records_store.py | `fm_yaml = dump_frontmatter(frontmatter)  # BF-940 slice 2 (L24): a tuple is a list; an unreadable value raises` | `fm_yaml = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)` | TestAFrontmatterTheStoreWritesIsOneTheStoreReads::test_a_tuple_is_written_as_a_list_and_the_note_stays_private (5 cases), ::test_a_value_no_reader_loads_is_refused_before_a_file_is_touched (12 cases), TestANumericTagReachesTheIndexAndANonListIsRefused::test_a_tuple_of_tags_is_written_as_a_list (18 cases) |
| 6 | M2 | src/probos/knowledge/records_store.py | `fm_yaml = dump_frontmatter(fm)  # BF-940 slice 2 (L24): what safe_load built (an !!omap is a list of tuples) is written readably` | `fm_yaml = yaml.dump(fm, default_flow_style=False, sort_keys=False)` | TestAFrontmatterTheStoreWritesIsOneTheStoreReads::test_a_publish_of_a_hand_made_note_holding_an_ordered_mapping_writes_no_python_tag |
| 7 | M2 | src/probos/knowledge/records_store.py | `if tags and not isinstance(tags, (list, tuple)):  # BF-940 slice 2 (L27): the readers iterate tags and the index joins them` | `if False:` | TestANumericTagReachesTheIndexAndANonListIsRefused::test_a_tags_value_that_is_not_a_list_is_refused (4 cases), test_the_notebook_route_answers_400_for_a_tags_value_that_is_not_a_list |
| 8 | M2 | src/probos/knowledge/records_store.py | `if tags and not isinstance(tags, (list, tuple)):  # BF-940 slice 2 (L27): the readers iterate tags and the index joins them` | `if tags and not isinstance(tags, list):  # BF-940 slice 2 (L27): the readers iterate tags and the index joins them` | TestANumericTagReachesTheIndexAndANonListIsRefused::test_a_tuple_of_tags_is_written_as_a_list |
| 9 | M2 | src/probos/knowledge/semantic.py | `header += f" [{', '.join(str(tag) for tag in tags)}]"  # BF-940 slice 2 (L27): a tag may be a number` | `header += f" [{', '.join(tag for tag in tags)}]"` | TestANumericTagReachesTheIndexAndANonListIsRefused::test_a_tag_that_is_not_text_reaches_the_index_on_write_and_on_backfill (4 cases) |
| 10 | M2 | src/probos/cognitive/skill_catalog.py | `new_yaml = dump_frontmatter(fm)  # BF-940 slice 2 (L24): one writer function for every frontmatter` | `new_yaml = yaml.dump(fm, default_flow_style=False, sort_keys=False)` | TestAFrontmatterTheStoreWritesIsOneTheStoreReads::test_a_skill_rewrite_of_a_file_holding_an_ordered_mapping_stays_readable |
| R-1 | M2 | src/probos/knowledge/records_store.py | `if tags and not _holds_every_tag(fm.get("tags"), tags):  # BF-940 A1 (F1): by equality, so no stored element is hashed` | `if tags and not set(tags).issubset(set(fm.get("tags", []))):` | `test_a_nested_element_in_tags_does_not_abort_a_filtered_listing` (4 cases), `test_the_head_to_head_tally_survives_a_game_record_whose_tags_hold_a_nested_element` (4 cases), `test_a_stored_tags_value_that_is_no_collection_holds_no_tag_and_does_not_abort_the_listing` (5 cases) |
| R-2 | M2 | src/probos/knowledge/records_store.py | `held = list(stored)` | `held = set(stored)` | `test_a_nested_element_in_tags_does_not_abort_a_filtered_listing` (4 cases), `test_the_head_to_head_tally_survives_a_game_record_whose_tags_hold_a_nested_element` (4 cases) |
| R-3 | M2 | src/probos/knowledge/records_store.py | `except TypeError:  # a number, a date or nothing is no collection: it holds no tag` | `except KeyError:  # a number, a date or nothing is no collection: it holds no tag` | `test_a_stored_tags_value_that_is_no_collection_holds_no_tag_and_does_not_abort_the_listing` (5 cases), `test_the_tag_filter_still_requires_every_tag_and_reads_a_set_and_a_missing_key_as_before` (1 case: the note with no `tags` key) |
| R-4 | M2 | src/probos/knowledge/records_store.py | `return all(tag in held for tag in wanted)` | `return any(tag in held for tag in wanted)` | `test_a_nested_element_in_tags_does_not_abort_a_filtered_listing` (4 cases), `test_the_tag_filter_still_requires_every_tag_and_reads_a_set_and_a_missing_key_as_before` (1 case) |
| R-5 | M2 | src/probos/knowledge/records_store.py | `if tags and not isinstance(tags, (list, tuple)):  # BF-940 slice 2 (L27): the readers iterate tags and the index joins them` | `if tags and (not isinstance(tags, (list, tuple)) or any(isinstance(tag, (list, tuple, set, dict)) for tag in tags)):  # BF-940 slice 2 (L27): the readers iterate tags and the index joins them` | `test_a_nested_element_in_tags_does_not_abort_a_filtered_listing` (4 cases), `test_the_head_to_head_tally_survives_a_game_record_whose_tags_hold_a_nested_element` (4 cases), `test_the_notebook_route_still_accepts_a_nested_element_in_tags` (1 case: the write-side refusal D6 ranked below the read side) |

Campaign of record (my hand driver, in memory, one mutant at a time over M2's head with both new files, baseline 59 cases pass; it is not the orchestrator's tool run, and the orchestrator's campaign of record, if it runs one, replaces it): each mutant fails exactly the cases its row lists (counts: 9, 3, 1, 22, 18, 1, 5, 1, 4, 1 for rows 1 to 10), none outside them. Rows 7 and 8 mutate the same line, so they are alternatives, not two edits of one tree. Not tabulated, for the cap: the `append_captains_log` call (`# BF-940 slice 2 (L24): the one writer function`): reverting it to `yaml.dump` changes no byte for the four `str` values it writes, so no test can tell (an equivalent mutant; L5); the unreachable branch for a combination that fails when no key does (`(none singly)`).

**A1 campaign of record.** My hand driver (not pytest, not the orchestrator's tool run), in memory, one mutant at a time over an overlay of the exact files: the staged candidate (index tree `e51530ff`, base `origin/main` `a66e272f`) with A1-1 to A1-10 applied; the sha256 of the four amended files are in 16.1 (M-10). Baseline 76 cases (55 and 21) pass. Each mutant fails exactly the cases its row lists (counts 13, 8, 6, 5, 9 for R-1 to R-5), none outside them. R-5 is a third alternative on the line rows 7 and 8 mutate. Row 1 is also failed by V7 (2 cases) and by the tuple cases of T15 and T16. Not tabulated: `held = list(stored or [])` survives (an equivalent mutant: the helper is called only with a non-empty `wanted`, so `stored or []` changes no answer). A Builder whose four files have these sha256 does not repeat the campaign; if `records_store.py` or the writer-policy file differs, rerun R-1 to R-5; if `frontmatter.py` or the dump file differs, rerun row 1 and V7.

## 10. Recorded limits

- **L1.** Nothing here is a live-system claim: I have no vessel, and no real `ship-records` was read. 7.4 is the census to run for this slice (it adds the unparsable, non-mapping, deep and non-UTF-8 documents and the type of every value); the results of a run on a vessel's data are not recorded in this repository, and a document written after a run is not covered by it.
- **L2.** A document already on disk with a Python tag or an unparsable frontmatter is not changed or made readable (D1.5). Until L19's slice, its author still cannot `publish` it, the Captain's `publish` still replaces its frontmatter with `status` and `updated` (measured, M-4), and update-in-place still loses `created` and `revision`.
- **L3.** A refused write is dropped by a caller that catches `Exception` and moves on (`commands_gap.py:253`, `routers/gaps.py:195`, `dreaming.py:1381`, `procedure_store.py:728` logs at debug). No production caller passes a refusable value by what I read (section 11), but the reading is of source, not of a run, and two origins are not traced: `Procedure.from_dict`'s `tags` and `intent_types` (`procedures.py:144`, `:158`) and `gap.gap_type` (annotated `str`, `gap_predictor.py:192`). The diff reviewer ran the real `ProcedureStore` for the first: `procedure_store.py:719` passes `procedure.intent_types + procedure.tags`; with both strings (a shape `Procedure.from_dict` does not validate) the concatenation is a string, which the base wrote readably (`tags: ab`) and the guard now refuses, so the caller (a debug log) drops the records projection: a readable projection lost, injected-only; scalar strings or numbers behave the same; a set fails the concatenation before the writer; lists, including lists of non-text, remain writable and tuples are written as lists.
- **L4.** The `tags` guard: a scalar, mapping or set `tags` is refused where it was written (the route answers 400 where it answered 200). A list or tuple whose elements are not text is accepted as before, written as given and joined by `str` in the index (a nested list or mapping becomes its `str`); `[None]` indexes as `None` and `[True]` as `True`. `backlinks.py:73` and `:182`, `routers/records.py:247` and `diagnostic_context.py:400` iterate `tags`; for a scalar already on disk they were run in A1 (L14). A nested list, mapping or set element no longer aborts `list_entries(tags=...)` (A1, D6; L11, L12).
- **L5.** `append_captains_log` calls the function but no test can tell it from `yaml.dump` (an equivalent mutant: four `str` values). `_write_config` keeps `yaml.dump` (a constant mapping, not a frontmatter).
- **L6.** The function refuses a value nested beyond the recursion limit, which depends on the stack at the call (a plain script: 300 levels written, 450 refused; the unit test uses 100 and 600). A hand-made deep note is not writable by the store; `publish` of one raises `ValueError` where it raised `RecursionError`.
- **L7.** Each write loads the text it dumped, once. I ran no timing (a request rule). The diff reviewer measured one successful serialization (one `dump_frontmatter` call, with its read-back) at a median of 2.417 ms against 1.042 ms for one `yaml.dump` call on a 40-metric envelope (five runs of 300 iterations): a serializer microbenchmark, the reviewer's measurement and not mine; it holds no file write, git add or other step of a `write_entry` call. A write is rare next to a read.
- **L8.** The read-back uses PyYAML's `safe_load`; the search's first reading uses libyaml where installed (BF-952 RK8, slice 1's L17). A text the two read differently is not covered. Measured on PyYAML 6.0.3 with libyaml, Python 3.12.13.
- **L9.** Not measured by me: pytest, xfail semantics and `-n 16`; the 47 existing test files; G1 to G3; the broad gate. Every count of mine is from my hand driver, not pytest; `setup_class` tests cannot be driven by it. A real ChromaDB (`PROBOS_EMBEDDINGS=local`, `chromadb.PersistentClient`, a temporary directory) was driven after the build by the orchestrator and by the diff reviewer: integer, float and boolean tags (the reviewer's run also `None`) are indexed on write and on backfill, the sidecar keeps the tags as given, and on the base they are not indexed at all (the probe outputs are kept outside the repository). The test file's `_Collection` double omits ChromaDB's validation and embedding: it proves the seam, not the engine.
- **L10.** L19 and F7-1 are decided and not built. Until they are: a frontmatter that does not parse still reads `{}` (D3); the route returns 500 for a record nested from 100 levels on this host (FastAPI 0.136.1, pydantic_core 2.41.5; the issue says 450) or holding non-UTF-8 `!!binary`, and so do the listing routes, which the issue's box does not name (D4). I did not read FastAPI's source.
- **L11.** A1 (F1): `list_entries(tags=...)` iterates the stored `tags` value and tests each wanted tag by equality, so no stored element is hashed. Where `set(wanted).issubset(set(stored))` could be computed the answer is unchanged, so a string is still read by character and a mapping by key (`write_entry` refuses both now); a number, a date or no value holds no tag and no longer aborts the listing. **Not changed:** a document whose frontmatter loads as a list, a string or a number (not a mapping) still aborts any filtered listing (a `tags` or an `author` filter) with `AttributeError`, on the base, the candidate and A1 alike (hand driver, 16.1): that is L19's family and its slice's.
- **L12.** A nested list, mapping, set or tuple element in `tags` is still accepted by `write_entry`, written as given (a tuple as a list) and joined as its `str` by the index (`[game, [1, 2]]`). The notebook route takes its tags from a JSON body, which holds a list or a mapping but no set or tuple, and answers 200 for a nested list element (T19). D6 ranked refusing non-scalar elements at the writer (options 2 and 3) below the read-side repair: it changes the route's answer for an HTTP client and reaches no document on disk. If a later slice takes it, the accepted elements are str, int, float, bool, None, date and datetime, and it is a decision of its own.
- **L13.** An `!!omap` or `!!pairs` value loses its tag and its tuples on any rewrite: `publish` and the skill rewrite re-dump what `safe_load` built, a list of tuples, as a list of lists. The readers load the result, nothing reads the tag back, and a second rewrite changes nothing (V7). Before slice 2 the same rewrite wrote a `!!python/tuple` tag no reader loaded (D1).
- **L14.** The other readers of `tags`, for a scalar already on disk (`tags: 717`), were run in A1: `extract_references` logs and returns no references, `suggest_cross_references` raises `TypeError`, the browse route answers 500, and the expression `list(fm.get("tags") or [])` of `diagnostic_context.py:400` raises `TypeError` (the expression was run, not the method); for a `tags:` with no value all four answer. They are older than slice 2, reach documents on disk only (the writer refuses a new scalar, L4) and A1 changes none of them.

## 11. Verified Against Codebase (2026-11-09, reading tree `D:\ProbOS-worktrees\bf940-build` at `7a094b28`)

Hand-driver results (Python 3.12.13, PyYAML 6.0.3 with libyaml, FastAPI 0.136.1, pydantic 2.12.5, pydantic_core 2.41.5), each one in-memory script, a fresh store per case, `~` moved, no `initialize()` (no git child), the author's own search asserted to find her note:

- **M-1 (L24).** `yaml.dump` over 27 values: tagged `!!python/` for tuple, frozenset, `OrderedDict`, `defaultdict`, `str` subclass, `Enum`, `str`-`Enum`, `Decimal`, `PurePosixPath`, namedtuple, object, complex, range, a tuple key, a list of tuples and a tuple of lists (16); `safe_load` refuses every tagged text (`ConstructorError`). `safe_dump`: tuple, list of tuples and tuple of lists written as lists; the 12 objects `RepresenterError`; a tuple key written and refused by `safe_load`; set `!!set` and loads; bytes, date, datetime, `nan`, `inf`, int and `None` keys, unicode, multi-line and `x --- y` load. Through the real store (base; `safe_dump` alone; `safe_dump` + read-back), `write_notebook("alice", …)` then bob's `read_entry`, bob's search, alice's `publish`: tuple in `metrics`: base class `None`, bob reads and finds it, `publish` `PermissionError`; `safe_dump` and the read-back: private, bob nothing, `publish` ok. Tuple + `---` topic (case A): private on all three (slice 1's A1). Object, `OrderedDict` in `extra_frontmatter`, tuple key: base exposed; `safe_dump` alone: object and `OrderedDict` `RepresenterError`, the tuple key still exposed (written, unreadable); read-back: `ValueError`, no file left. Set and `nan`: private on all three. A refused update: `ValueError`, the existing note byte-identical, `files: ['keep.md']`. `safe_load` of `!!omap` gives a tuple as the first item; `yaml.dump` of it is tagged and refused, `safe_dump` of it loads.
- **M-2 (bytes).** `yaml.dump` equals `yaml.safe_dump` for four realistic mappings (a store envelope with metrics, a publish-finding envelope, unicode and `---` values with a date, a nested mapping with empty containers and quoting cases) and for one object shared by two keys (`&id001` anchor, same on both); V1's six mappings (incl. date, datetime, bytes, set, int and `None` keys) pass by hand driver. Tuple-free mappings only: `safe_load` builds tuples for `!!omap` and `!!pairs`, which `yaml.dump` tags and `safe_dump` writes as lists (A1, F2; V7; 16.1, M-9).
- **M-3 (L27).** Baseline (fake collection, `reindex_records` over the real store): `['alpha']` indexed on write and backfill; `[717]`, `[717, "x"]`, `[True]`, `[None]`, `[1.5]`: written, `read_entry` and `list_entries` return them as given, not indexed on write, `reindex_records` returns 0; keyword `717` finds `[717]`; `tags=717`: not indexed on write (`TypeError`), the backfill indexes it without tags, `list_entries(tags=["x"])` raises `TypeError`; `"abc"` and `{"a": 1}`: indexed (`"abc"` joined as `a, b, c` on write, no tags on backfill). With `str()` at the join: `[717]`, `[717, "x"]`, `[True]`, `[None]` indexed on write and backfill (headers `[717]`, `[717, x]`, `[True]`, `[None]`); `717` still not indexed on write and `list_entries(tags=…)` still raises. Writing the string `'717'` indexes and is found.
- **M-4 (L19 and the legacy document).** Hand-made notes under `notebooks/alice/` (an open flow list; a `!!python/tuple`; `updated: 2026-13-05`), on the slice-1 tree. First two: alice, bob and the Captain all read and find them; `list_entries` shows `{}`; the backfill indexes them as `ship`; `publish` by alice `PermissionError`; by the Captain: the file now starts `---\nstatus: published\nupdated: …\n---` and `revision: 3` and `created` are gone; update-in-place: `created` lost, `revision: 2`. The third: `read_entry` `ValueError` for all three, search withholds, not listed, not indexed, `publish` `ValueError` for both, update-in-place succeeds with no `revision`. `record_is_readable` for the three readings: keep `{}` `{'alice': True, 'bob': True, 'captain': True, '': True}`; fail closed, author `""`: `{'alice': False, 'bob': False, 'captain': True, '': True}`; author the path's owner: `{'alice': True, 'bob': False, 'captain': True, '': False}`. A loader with a `!!python/tuple` constructor reads the tagged note (`{'sample': (1, 2)}`) and `yaml.dump` of it is tagged again; `yaml.UnsafeLoader` on `!!python/object/apply:builtins.len [[1,2,3]]` returns `{'x': 3}`.
- **M-5 (F7-1).** A stub route with `-> Any` over single-key nests: 200 at 90 levels, 500 from 100; the real router over a real store with hand-made records: 50 and 90 levels 200, 100 and 450 500, 600 503 (`read_entry` `RecursionError`), `!!binary //4=` 500, the listing 500. `TypeAdapter(Any).dump_python(mode="json")` inside a `try`: 503 for 100, 450, 600 and non-UTF-8 bytes; response bytes equal to the plain route's for the ordinary, datetime/date/set/bytes, unicode/int-key/`nan` and 90-level shapes. `jsonable_encoder` + `JSONResponse`: a UTC datetime changes from `…Z` to `…+00:00` and `nan` becomes a 503.

Grep evidence (reading tree; line numbers are the slice-1 state):

```
grep -n -E "yaml\.(safe_)?dump\(" src (excluding the safe_dump callers that write other files)
  knowledge/records_store.py:762, :885, :1544 (frontmatter), :1769 (_write_config)   cognitive/skill_catalog.py:808
  cognitive/dreaming.py:1371   cognitive/procedure_store.py:714, :1728   experience/commands/commands_gap.py:243   routers/gaps.py:185  (a body: content=…)
grep -n -E "f\"---\\n|\{fm_yaml\}|\{new_yaml\}" src
  knowledge/records_store.py:763, :887, :1545   cognitive/skill_catalog.py:809
grep -n "_semantic_indexer\s*=|def set_semantic_indexer|def repo_path" records_store.py  ->  :812, :803, :620
grep -n "extra_frontmatter must be a dict" records_store.py  ->  :701   (type check :700)
grep -n "', '.join(tags)" semantic.py  ->  :406   (the only join of tags in semantic.py)
grep -n "tags = frontmatter.get(\"tags\")" semantic.py  ->  :742   (backfill: tags if isinstance(tags, list) else None)
grep -n "set(tags).issubset" records_store.py  ->  :1493  (outside the per-file try of the walk, viewed at :1470-1493)
routers/records.py: read_record :59; 503 :95; format branch :98; notebook route :146-161 (tags :156, ValueError :161); entry_tags :247
pyproject.toml: pydantic>=2.0 :25, pyyaml>=6.0 :26, fastapi>=0.115 :50, asyncio_mode = "auto" :181, addopts -n 16 :196
tests: git grep equivalent (the five writer patterns) -> 47 files; metrics=\{[^}]*\( -> tests/test_bf940_frontmatter_framing.py:228 only
tests/test_ad1140_publish_finding.py:1002  expected = yaml.dump({...plain str values...}) ; raw == f"---\n{expected}---\n\nbody text"  (unchanged by safe_dump: M-2)
docs/development/deterministic-ship.md:49 holds the clause P3-3 extends; PROGRESS.md:3 and DECISIONS.md:1602-1610 are slice 1's entries
```

**Production callers of a writer, each payload read** (`file:line`; frontmatter values passed): `after_action.py:372` (tags 2 `str`; `extra_frontmatter` envelope: `str`, `int`, `list[str]`, a list of `dict[str, str]` from `ReviewResult.as_envelope`, `:110-116`, `:353-381`); `stand_down.py:328` (tags 2 `str`; envelope `str`, `list[str]`, `:390-397`); `tools/publish_finding_tool.py:693` (tags: `type(tag) is str` enforced, `:480-499`; envelope `str`, `int`, `float`, `:794-826`); `proactive.py:3366` (tags `[topic_slug]`; `metrics=_nb_metrics`: `collect_notebook_metrics` `:332-394` rounds to `float`, `int`, and one `str` (`llm_health.overall`); `metrics_delta` floats and `"a → b"` strings, `:396-420`; vitals values are `float` or `int` from sums and divisions, `vitals_monitor.py:129`, `:155`, `:164`), `:3977`, `:4430` (tags `[topic_slug]`); `peer_perception.py:350` (tags `str` and `ObservationRegister(str, Enum).value`, `:44`), `avatars/records_writer.py:168`, `creative/output_writer.py:105` (`tags=["creative", medium, skill_id]`, both annotated `str`, `metrics=None`), `commands_gap.py:244`, `routers/gaps.py:186`, `recreation/service.py:377` (`game_type` annotated `str`), `dreaming.py:1012` (no frontmatter argument but `author`, a value read from a frontmatter), `:1145`, `:1372` (`tags=["ad-539", gap.gap_type, gap.priority]`, both annotated `str`, `gap_predictor.py:192`, `:202`), `procedure_store.py:719`, `:1729`, `records_store.py:845` (`seed_manuals`, `tags=["manual"]`), `routers/records.py:151` (the HTTP body: any JSON `tags`, `topic`, `department`). None passes a tuple, a set or an object. `records_store.py:937` is `write_notebook` passing through.

## Absence Verified (2026-11-09)

```
CLAIM: no frontmatter is written by a function other than the four.
RUN:   grep -n -E "yaml\.(safe_)?dump\(" src ; grep -n -E "f\"---\\n|\{fm_yaml\}|\{new_yaml\}" src
FOUND: the dump calls and the four "---\n{yaml}---" writes listed above; every other dump writes a body or another file.
HOLDS: yes for the writes that build "---\n" by string; a writer that composes a frontmatter in another way (a template) would not match: none found by these patterns.

CLAIM: no production caller passes a tuple, set or object.
RUN:   grep -n -E "\.write_entry\(|\.write_notebook\(|\.write_bill\(|\.append_captains_log\(|extra_frontmatter\s*=" src ; read each payload
FOUND: the callers above (25 call lines in 14 files).
HOLDS: for the payloads read; not traced to origin: Procedure.from_dict tags, gap.gap_type (L3).

CLAIM: no existing test other than slice 1's T12 passes a tuple to a writer.
RUN:   grep -n -E "metrics=\{[^}]*\(|extra_frontmatter=\{[^}]*\(\d|metrics=\{[^}]*\bset\(" tests
FOUND: tests/test_bf940_frontmatter_framing.py:228
HOLDS: for a payload written inline in the call; one built in a variable is not seen (G2 runs every such file).

CLAIM: no test passes a scalar `tags` to a writer.
RUN:   grep -n -E "tags=(\(|\{|\d|True|None\))" tests
FOUND: test_ad1347_s3_execution.py:633 (a work item) and test_ad562_records_browse_endpoint.py:47 (a browse endpoint, not a writer)
HOLDS: for the inline forms the pattern matches.
```

## 12. Prior Art and Blind Spots

- **Internal: adopted.** AD-1140's fail-fast tier for a value the writer cannot keep (`extra_frontmatter must be a dict`, `records_store.py:700-701`, is the precedent for the `tags` guard); BF-952's L24 and L27 limits and slice 1's L10 and L16 (the cases and the enumeration this contract completes); BF-952's RK10 and A3 (L19 may not take a record from its owner: D3 option 2 measured doing it); slice 1's D2 (`utils` holds the pure helper); slice 1's A1 (kept; its test is hand-made now, N1-2). **Rejected:** a type-walking normaliser (option 2 of D1: more code for what `safe_dump` gives); a read-side loader (a persisted-format extension and a code-execution path).
- **Blind spots handled.** A tuple at every depth of `metrics` and `extra_frontmatter`; a tuple key (`safe_dump` writes it, `safe_load` refuses: the read-back); `publish` and the skill rewrite re-dumping what `safe_load` built (`!!omap`, `!!pairs`); a set (`!!set` loads; kept); `nan`; unicode, multi-line and long values (byte-identical); the update that is refused leaving the existing file untouched; a refusal before `mkdir`, the write, the git add, the confidence tracker and the index; a scalar `tags` and the listing that raised for it; `tags` read back as written; the sidecar; the backfill reading from disk.
- **What discards a correct result.** A caller that catches `Exception` and drops a refused write (most do): no production caller passes a refusable value (section 11), but a future one would lose the record where it used to write an unreadable one (L3). The index drops a record whose tags it could not join: no longer. The route's 400 for a scalar `tags` loses a write the route used to accept and `list_entries` could not list (D2). A filtered listing that aborted for a note it could have listed: no longer (A1, D6). **Recorded:** L1 to L14.

## 13. Diff Reviewer: properties to verify

1. `dump_frontmatter(mapping)` returns `yaml.safe_dump(mapping, default_flow_style=False, sort_keys=False)` after a `safe_load` of it that is a mapping, and otherwise raises `ValueError` (from `yaml.YAMLError` or `RecursionError`) whose message holds the top-level key names that fail alone and the error's type, never a value; for every value `yaml.dump` wrote without a `!!python/` tag (every value `safe_load` builds that holds no tuple) the text equals `yaml.dump`'s (V1, T2), and a mapping holding the tuples `safe_load` builds for `!!omap` and `!!pairs` is written as lists (V7). `split_frontmatter` and `base_split_frontmatter` are unchanged.
2. The three writers of `RecordsStore` and `_rewrite_frontmatter` call it and no `yaml.dump` of a frontmatter is left in `src` (`git grep -n "yaml.dump(" -- src/probos/knowledge src/probos/cognitive/skill_catalog.py` leaves only `_write_config`); the `dump_frontmatter` call in `write_entry` stays after the update-in-place read and **before** `mkdir`, the write, the git add, the confidence tracker and the index (T8 asserts a refused update leaves the file byte-identical and creates nothing); the `tags` guard (property 3) stands earlier still, after the `extra_frontmatter` check and before that read (in `write_entry`, in this order: the `tags` guard, the update-in-place read, `dump_frontmatter`, `mkdir`, the write).
3. The `tags` guard is `if tags and not isinstance(tags, (list, tuple))`, placed before any side effect; a falsy `tags` is ignored as before (T5); elements are untouched; the index joins `str(tag)` and nothing else in `semantic.py` changes.
4. N1-2 changes one slice-1 test to a hand-made document and keeps every assertion after the premise; no other existing test is edited.
5. M1: the file collects on the unfixed tree, imports no BF-940 slice-2 name (`dump_frontmatter` appears only in N2-1), the 29 class cases fail at their own `assert` and never at a premise line, the 11 guards pass; N2-2 removes the two markers only.
6. M3: the PROGRESS and DECISIONS entries say `Refs #1686` and name what the issue keeps; P3-3 changes one clause.
7. **Half-chain evidence:** T7, T9 and T11 each cross the seam in one test (write → read → search → publish; backfill from disk), not a producer test and a consumer test.
8. A1: `_holds_every_tag(stored, wanted)` is `all(tag in held for tag in wanted)` for `held = list(stored)` and `False` where `list(stored)` raises `TypeError`; `list_entries` calls it as its only `tags` test and `set(tags).issubset` no longer occurs in `records_store.py`; wherever `set(wanted).issubset(set(stored))` could be computed it gives the same answer (16.1, M-7: 140,014 of 140,014 random pairs; no changed cell in 126).
9. A1: no writer, caller, route, config, format or reader other than `list_entries`' tag test is edited (the pairs change `utils/frontmatter.py` in a docstring, `records_store.py` in a helper, one call and two docstrings, and the two new test files); no existing test is edited; the route still answers 200 for a nested list element (T19).
10. A1: T15 crosses the writer and the filtered listing in one test and T16 crosses the writer, the filtered listing and `read_head_to_head` in one test, not a producer test and a consumer test; T17 covers the documents on disk that only the read side reaches; V7 pins the `!!omap` and `!!pairs` products.

## 14. Acceptance criteria

- G1, G2 and G3 pass as stated, the census of 7.4 is run on the vessel's copy, and the batch's broad gate is green with a receipt.
- **L24:** a tuple in `metrics`, in `extra_frontmatter` or nested is written as a list and the note stays private through `read_entry`, the search and `publish` (T7); a value no reader loads is refused with `ValueError` naming the key, an update leaves the note byte-identical and a create leaves no file (T8, V3); `publish` and the skill rewrite write no tag (T9, T10); the bytes of every value `yaml.dump` wrote without a `!!python/` tag are unchanged (T2, V1) and an `!!omap` or `!!pairs` product is written as lists (V7).
- **L27:** a numeric tag is read back as given, indexed on write and on backfill (T11); a non-list `tags` is refused and the route answers 400 (T12, T14); a tuple of tags is written as a list (T13).
- **F1 and F2 (A1):** a note whose `tags` hold a nested tuple, list, mapping or set is listed by `list_entries(tags=...)` (T15) and counted by `read_head_to_head` (T16); a scalar or empty `tags` on disk matches no filter and aborts nothing (T17); the filter still requires every tag (T18); the route still answers 200 for a nested list element (T19); the byte claim is for the values `yaml.dump` wrote without a tag and an `!!omap` or `!!pairs` product is written as lists (V7).
- **The issue:** the pull request says `Refs #1686`; its checklist shows L25, L18, L20, L24 and L27 done and L19 and F7-1 open; the issue is not closed.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. For the Captain

- **L19's policy (D3), before its slice.** Option 1 changes who may read records already on disk whose frontmatter does not load (they read as `ship` today): the Captain and the path's owner read them, everyone else is withheld, and `publish` and update-in-place refuse. Recommendation: option 1. It is the only option that does not take a note from its author (RK10) or admit the anonymous reader (measured), and it stops the Captain's `publish` destroying a block it cannot read.
- Nothing else in this slice crosses a Captain-only boundary, and A1 crosses none (D6).

## 16. Amendment A1 (review round 1: F1 and F2)

The diff reviewer's round 1 on the staged candidate (index tree `e51530ff`) was NOT READY: F1 (P2, reach injected-only, a regression), F2 (P3, a claim that was false) and four documentation points. A1 is a set of pairs (A1-1 to A1-42; A1-42 is the orchestrator's one-sentence correction of section 13's property 2, which A1-34 had given by line number) applied to the staged candidate, to this contract and to the two trackers: the decision is D6, the limits are L11 to L14 (L3, L4, L7 and L9 are amended), the cases are T15 to T19 and V7, the mutation rows are R-1 to R-5. Section 7 keeps the as-built text of M1 to M3 and is not edited: where one of its blocks and a pair differ (the `dump_frontmatter` docstring, M3's PROGRESS sentence) the pair wins.

| Finding | Disposition | Where |
|---|---|---|
| F1 (P2, regression): a nested tuple in `tags` is newly readable and aborts `list_entries(tags=...)`, which drops `read_head_to_head`'s whole tally | Repaired on the read side: the filter matches by equality over the stored value | D6; `_holds_every_tag`; T15 to T19; R-1 to R-5 |
| F2 (P3): "byte-identical for every value `safe_load` builds" is false for `!!omap` and `!!pairs` | The claim covers the values `yaml.dump` wrote without a `!!python/` tag; the two tags are written as lists | D6; the docstring; sections 2, 3 (D1), 11 (M-2), 13, 14; PROGRESS; V7; L13 |
| Property 2: the order of the `tags` guard | Stated exactly: the guard is before the update-in-place read and the dump after it | section 13, property 2 |
| L7, L3, L9 | The reviewer's serializer timing, the reviewer's `ProcedureStore` run and the real ChromaDB runs are recorded as theirs | L7, L3, L9 |
| Non-scalar elements are still accepted by the writer | Not changed here; recorded | D6; L12 |
| A document with a non-mapping frontmatter still aborts a filtered listing | Not changed here; L19's family | L11 |

### 16.1 Verified (A1; a hand driver that calls each test function itself, not pytest; Python 3.12.13, PyYAML 6.0.3 with libyaml; a fresh store per case in a temporary directory, `~` moved, no `initialize()`)

- **M-6 (F1).** With the healthy note `a.md` (`tags=["game", "chess"]`) alone, `list_entries(tags=["game"])` returns exactly it on every tree (the premise). A second note written with `tags=["game", "chess", (1, 2)]`: on the base it is written unreadable (no `tags` key) and skipped, so the listing returns `a.md`; on the candidate it is written as a list and readable and the listing raises `TypeError: unhashable type: 'list'`; with A1 both are listed. A nested list, mapping or set element: written and readable on all three trees, the listing raises on the base and the candidate and lists both with A1. Through `read_head_to_head` (a second game record whose tags hold the element): tuple, base (1, 0, 0) (the record is unreadable, so not counted), candidate no tally, A1 (1, 1, 0); list, mapping and set, base and candidate no tally, A1 (1, 1, 0). The same with a record whose `tags` is an integer, a date or no value on disk (hand-made): base and candidate no tally, A1 (1, 0, 0), the record matching no filter and so not counted. The route answers 200 for a nested list element on the three trees (T19 passes on all three).
- **M-7 (the differential).** 21 stored `tags` shapes (lists of text, a `!!set`, an `!!omap`, a string, a mapping, `!!binary`, an integer, a float, a boolean, no value, a date, a nested list, mapping and set, a list holding only a list) by 6 filters = 126 cells through `list_entries`: the staged candidate equals the base in all 126; A1 equals the base in 72 and returns in the 54 where the base raised `TypeError` (9 shapes by 6 filters); no cell where the base returned a result changed. Pure, on `_holds_every_tag`: 200,000 random (stored, wanted) pairs over lists, tuples, sets, frozensets, strings, mappings, bytes, scalars and `None`: the base's expression is computable for 140,014 and the helper agrees on all 140,014; the helper never raised. A self-referential `tags` (`&a [game, *a]`, a YAML anchor that contains itself): the base raises `TypeError`; A1 lists it for `game`, not for an absent tag, and terminates.
- **M-8 (readers, A1).** For each of a nested tuple, list, mapping and set element written by `write_entry`: `read_entry` reads the note; alice's search finds it and bob's does not (a private notebook); `publish` keeps the tags; the backfill indexes it (header `[game, [1, 2]]`); `extract_references` returns the one text tag; `suggest_cross_references` runs; `GET /api/records/browse?tags=game` answers 200 with the note counted; the expression `list(fm.get("tags") or [])` of `diagnostic_context.py:400` runs. The staged candidate answers the same in every row but `list_entries(tags=...)` (`TypeError`). For `tags: 717` on disk: `list_entries` returns (no tag held), `extract_references` logs and returns nothing, `suggest_cross_references` and that expression raise `TypeError` and the browse route answers 500 (L14); for `tags:` with no value all answer. A hand-made document whose frontmatter loads as a list (`- a`), a string or a number: `list_entries` with no filter returns it and with a `tags` or an `author` filter raises `AttributeError`, on the base, the candidate and A1 alike (L11).
- **M-9 (F2).** `SafeConstructor.yaml_constructors` has 13 entries; only `omap` and `pairs` build a tuple (read from PyYAML's source and measured on a sample of each tag). `safe_load` of `metrics: !!omap [{a: 1}, {b: 2}]` and of the `!!pairs` twin gives `[('a', 1), ('b', 2)]`; `yaml.dump` tags it `!!python/tuple`; `dump_frontmatter` writes `metrics:\n- - a\n  - 1\n- - b\n  - 2\n`, which reads back as `[['a', 1], ['b', 2]]`, equal to `yaml.dump` of the same mapping with lists and not equal to what `safe_load` built; a second rewrite changes nothing. A corpus of 20,000 mappings (seed 940) of strings, numbers, dates, bytes, sets, lists, mappings, tuples, `OrderedDict`s, frozensets and tuple keys: where `yaml.dump` wrote no `!!python/` tag (11,662 mappings) the text is equal in all 11,662; where it did (8,338) the function wrote lists for 2,688 and refused 5,650, and never wrote a tag.
- **M-10 (counts, hand driver; sha256 of the amended files).** With A1: the writer-policy file 55 of 55, the dump file 21 of 21, slice 1's framing file 40 of 40, `TestMetaIntegrity` (no duplicate `def` names in `records_store.py`) 1 of 1. The staged candidate with the amended test files: 42 of 55 (the 13 that fail are T15 x4 and T17 x5 at the listing, T16 x4 at `assert tally is not None`) and 21 of 21. The base: 13 of 55 (the 11 guards, T18 and T19; T15's tuple case fails at its premise because the base writes that note unreadable). Mutation (A1-25): baseline 76 of 76; R-1 fails 13, R-2 8, R-3 6, R-4 5, R-5 9, none outside the cases its row lists; row 1 also fails V7 (2) and the tuple cases of T15 and T16. sha256 of the amended files as A1-1 to A1-10 leave them (section 17: A2-1 then edits one docstring of `records_store.py`): `src/probos/knowledge/records_store.py` f9a5f27859e9a3b76cd5b0a65d060a4f9ee90f88b779e640cc477484473343e0; `src/probos/utils/frontmatter.py` 15e09a6330afb87b0fd4e60fba9b24cc412bca243a18d62c440cc54a77e96d85; `tests/test_bf940_s2_writer_policy.py` 076c6b2dafb5ba7534748456b6b934eea9a6e1a06014eb63f181c84bab34c4ab; `tests/test_bf940_s2_dump_frontmatter.py` 32c209df76611e2037a3f480cc3a1f3f469c4d68f0b6f8e2e17faa3404a198b5 (of the LF bytes).

### 16.2 Absence Verified (A1)

- CLAIM: no reader of a record's `tags` other than the filter in `list_entries` hashes its elements. RUN: `rg -n "\.get\(.tags.|\[.tags.\]" src` (24 hits in 17 files). FOUND: the record readers are `records_store.py` (the filter, and the writer's `frontmatter["tags"] = tags`), `backlinks.py:73` and `:182` (an `isinstance(tag, str)` per element), `semantic.py:742` (`isinstance(tags, list)`), `routers/records.py:247` (`str(t).lower()`) and `diagnostic_context.py:400` (`list(...)`); the other 17 hits read a work item, a procedure, a database row, an idea, an agent-card skill, an endpoint, an ARD entry, a tool input or the notebook route's request body (`routers/records.py:156`) (by receiver name; `idea_store.py:78` read). HOLDS: yes, none hashes an element.
- CLAIM: only three calls in `src` pass a `tags` filter to `list_entries`. RUN: `rg -n -U "list_entries\([^)]{0,400}tags\s*=" src`. FOUND: `experience/commands/commands_gap.py:51`, `recreation/history.py:184`, `routers/gaps.py:23`, each a list of strings. HOLDS: yes.
- CLAIM: no existing test pins the old raise or scans the filter's line. RUN: `rg -n -U "list_entries\([^)]{0,400}tags" tests`; `rg -n "getsource\(.*(RecordsStore|records_store)|issubset\(set\(fm" tests`. FOUND: `test_records_store.py:259` (a one-tag list-of-text filter) and `test_records_store.py:425` (`inspect.getsource(records_store)`, a scan for duplicate `def` names, which passes with A1: M-10). HOLDS: yes.
- CLAIM: the production writers' payloads (the 20 calls of `write_entry` and `write_notebook`, an AST enumeration) pass a list of strings or no `tags`, except `procedure_store.py:719` (`procedure.intent_types + procedure.tags`, unvalidated shapes: L3), the route (`body.get('tags', [])`) and `write_notebook`'s passthrough (the route's value). RUN: the orchestrator's AST walk of `src` for the two calls (20 found by AST and by regex); I read each `tags` expression in its output. HOLDS: yes for the payloads read; the gap and creative payloads are strings by annotation (L3).
- CLAIM: no other sentence in the staged files or this contract says the text equals `yaml.dump`'s for every value `safe_load` builds. RUN: a scan of the staged blobs and this contract for `byte-identical`, `byte for byte`, `bytes of every`, `every value`, `safe_load builds`, `yaml.dump's`, `the bytes`, `readable shapes`, `readable value`. FOUND: the docstring (A1-1), section 2 (A1-15), D1's rank paragraph (A1-18), M-2 (A1-31), property 1 (A1-33), section 14 (A1-36), PROGRESS (A1-39); the T2 and V1 to V6 rows and T2's docstring say "native values" (true); DECISIONS holds none; section 7's blocks hold the as-built copies (not edited). HOLDS: yes.
- CLAIM: `safe_load` builds a tuple for exactly two tags. RUN: `SafeConstructor.yaml_constructors` (13 entries) read for constructors that build a tuple, and a sample document loaded per tag. FOUND: `omap` and `pairs`. HOLDS: yes.

### 16.3 After applying

Apply A1-1 to A1-42 to the staged LF blobs (each SEARCH once, in label order); run G2's focused command (counts in A1-20) and `gen_ad_ledger.py` then `--check` (G3); commit the reviewed tree; then the broad gate once with a receipt. Round 2 of the diff reviewer takes the delta: the files and lines the pairs change, the consumers of `list_entries(tags=...)` (the three calls) and of `_holds_every_tag` (one), the differential of M-7, and what round 1 said it did not check (the broad gate, ledger generation, the vessel census, Linux, the full runtime startup).

## 17. Amendment A2 (review round 2: F3 to F5)

The diff reviewer's round 2 took the delta from index tree `e51530ff` to `becd1d76`. It found the runtime repair sound and was NOT READY on three claims that A1 had introduced, each P3 and none a defect of the code. **F3** (injected-only reach): a Python set cannot cross the notebook route's JSON boundary, so the sentences that said the route takes a nested set (the docstring of `_holds_every_tag`, D6 and L12) now say that a JSON client can send a list or a mapping, and that a tuple or a set reaches `write_entry` from Python only. **F4**: T15 crosses the writer and the filtered listing and T16 alone crosses `read_head_to_head`; section 13's property 10 and the section 14 bullet now say so. **F5**: L7's 2.417 ms against 1.042 ms is a serializer microbenchmark, one `dump_frontmatter` call against one `yaml.dump` call, with no file write, git add or other step of a `write_entry` call; L7, the status line and the table of section 16 now say so.

A2 is a set of pairs (A2-1 to A2-17) in one docstring of `records_store.py` and in this contract: no test, no other source line and no tracker changes, so a comment-only change to the source. The sha256 values of M-10 are those of A1's files before A2-1. R-1 to R-5 were run again by tool on the tree with A2 applied: the baseline of 76 cases passes, and R-1 fails 13 cases, R-2 8, R-3 6, R-4 5 and R-5 9.
