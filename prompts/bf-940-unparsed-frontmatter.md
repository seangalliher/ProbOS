# BF-940 (#1686): A document whose frontmatter does not load is private to the owner of its notebook directory: the readers and the keyword search withhold it from every other reader, the semantic backfill leaves it out and `publish` refuses it (slice 4 of the issue, its last box)

**Drafted by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge was logged out), 2026-11-11
**Revised by:** the orchestrator, 2026-11-11: P3-1 re-anchored to the title line now that slice 3 has merged (its label paragraph, SEARCH and REPLACE; the REPLACE no longer re-emits slice 2's heading line, which the new SEARCH does not remove); no other block, test or number changed.
**Amended by:** `Architect` (GitHub Copilot fallback), 2026-11-11, amendment A1 of slice 4, after Diff Reviewer round 1. F1: the verdict loaded the block through a helper, one frame deeper than `_parse_document`, so a document that nests deep and then ends in a YAML error was read by the base and raised `RecursionError` for its owner (a 503 on the read route, the document gone from the listing); `_frontmatter_unparsed` now loads the block itself (P2-2), and S10 and T12 pin it at both parities of the stack depth. F2: the search's first pass has libyaml's reading of a note libyaml reads and PyYAML refuses, so an owner whom that reading excludes can miss a note `read_entry` gives her; the claims that said the two readers agree are corrected, the miss is recorded as L11 and pinned (T13), and D5 decides it. Every count below is the post-A1 one (46 cases: 20 guards and 26 class cases; 27 mutation rows); the Oracle paragraph that follows records what the pre-A1 oracle ran (40 cases, 25 mutants) and is not rewritten.
**Status:** ready to build on slice 2's merge; it does not depend on slice 3. **Reading tree:** `D:\ProbOS-worktrees\bf940s3-base`, detached at `origin/main` `708fa60c` (slice 2's merge; clean). Every SEARCH below is in the slice-2 state of its file. Slice 3 (`routers/records.py`, its own test file, `PROGRESS.md`, `DECISIONS.md`) is in review in another tree and is not in this one: no pair here edits a text slice 3 edits (P3-1 and P3-2 name their anchors). **Oracle:** a read-only consult: no pytest, no timing or benchmark script, nothing written in a repository, `%LOCALAPPDATA%\ProbOS` or `d:\ProbOS\data`. In-memory scripts, in the OS temp folder with `HOME`, `USERPROFILE`, `LOCALAPPDATA` and `APPDATA` moved: (a) a matrix of every caller of a document whose frontmatter does not load (a YAML error, a `!!python/tuple`, `updated: 2026-13-05`, and healthy, empty, plain and unclosed controls) on the base, on four emulated candidates and on M2's head; (b) the real apply tool (`apply_search_replace_blocks_bare.py`) on two throwaway roots holding copies of the files: with `--newfile` on N1-1's heading it wrote the new file and applied 22 pairs, N2-1 alone failing because the tool writes a new file only after it has applied the pairs; on a root that already held the new file it applied all 20 + 3 pairs with 0 failures; (c) a hand driver (a stand-in for the few pytest features the files use: not the runner) called the 40 cases of N1-1: on the reading tree 16 pass and 24 fail, each at the `assert` section 6 names; on M2's head all 40 pass; (d) the 25 mutants of section 9; (e) 94 existing test files that touch the store, driven the same way on the base and on M2's head (section 11, M-5); (f) the census of 7.4 on synthetic trees. **Not run:** G1 to G3, pytest, xfail semantics, `-n`, the broad gate, the architecture check, the ledger generator, a timing run, the census on a real tree, the orchestrator's slicer.
**Base blobs** (git blob ids of the working copy, equal to `git rev-parse HEAD:<path>` in the reading tree; they must equal slice 2's merge): `src/probos/knowledge/records_store.py` `1d492e9b29236ac7402fb5e9ab104c3c0ee4314f`, `src/probos/knowledge/semantic.py` `6191dcad00234898c2b198a7c17ab50859957920`, `docs/development/deterministic-ship.md` `00ab7e536f8fec97a0b47b2cc18defd37361d56b`, `PROGRESS.md` `da466972f78120767dc6646e3bb57e1b91d34405`, `DECISIONS.md` `29cddd81ee018a0ea87da588005372a690547d70`, `tests/test_bf952_records_keyword_search.py` `d15e6a99ca25906b15d326c921d83e26d6c125fa`; a test this slice relies on and does not edit: `tests/test_bf940_frontmatter_framing.py` `d6f5a85d7520c87fcc48e7a698f06eddc3565625`.
**Dependencies:** slice 2 merged. **Tier:** M1 STANDARD (tests); M2 HIGH (the access rules of every Ship's Records reader); M3 STANDARD. **Estimated tests:** one new file, 46 cases (20 pass and 26 xfail at M1), and one existing test edited (P2-19). **BF number:** BF-940, held by #1686 (open, `bug`); nothing new is allocated. **License posture:** no dependency is added or changed (PyYAML, `pyproject.toml:26`, is already imported by `records_store.py`; the standard library does the rest); `THIRD_PARTY_LICENSES.md` is untouched.
**What this contract closes of #1686:** L19, the last open box of the hand-off checklist (with slice 3's F7-1, in review). The pull request says `Refs #1686`; the orchestrator closes the issue on its verified-closure step, once every box is built and merged.

**Which text describes the head.** Before building: slice 2 is merged, `git rev-parse HEAD:<path>` for the six edited paths prints the blobs above, `git diff --stat 708fa60c HEAD -- src/probos/knowledge src/probos/utils tests/test_bf952_records_keyword_search.py docs/development/deterministic-ship.md` shows nothing (`708fa60c` is slice 2's merge), and the new test file does not exist. If a blob differs, every SEARCH must still occur exactly once, else it is a hard stop for the Architect. Working copies are CRLF and SEARCH text is LF. Where prose and a block differ, the block wins. Apply the pairs with the `edit` tool one at a time, whole block, in label order. ASCII only in every line you add.

## 1. Problem

1. **The defect.** A document whose frontmatter block YAML refuses (broken YAML, or a tag `safe_load` refuses: the `!!python/tuple` an older `write_entry` wrote) reads as `{}`: `RecordsStore._parse_document` (`records_store.py:1742-1765`) catches the `YAMLError` (`:1755-1756`), and the search's reader loads the block the same way (`_search_load_frontmatter`, `:298-312`). `{}` names no classification, so the document is `ship` for every reader, whatever its text says (a private note of its author's, here). Measured, base, on a notebook path and on a report path, for a YAML error and for a tuple (identical):

| Caller | Today |
|---|---|
| `read_entry` as alice, bob, captain, `""`, `system` | all five get `{"frontmatter": {}, "content": ..., "path": ...}` (`:1418-1447`) |
| keyword search as alice, bob, captain, `None`, `""` (`_search_records`, `:393-505`) | all five find it |
| `list_entries` (`:1449-1523`) | lists it with `{}`; the `author=` and `classification=` filters leave it out |
| similarity scan, exact topic (`check_notebook_similarity`, layer 2, `:1086-1149`) | answers `update` ("stale entry, refreshing", `revision` 1, `created_iso` `None`) |
| similarity scan across topics (`:1151-1197`) and convergence scan (`:1201-1323`) | skip it: it has no `updated`, so it is stale (measured against a positive control: a healthy note with the same words suppresses and converges) |
| update-in-place (`write_entry`, `:744-764`, through `write_notebook`) | succeeds; `created` restarts and `revision` is 2 (the healthy control keeps its `created` and goes 4 to 5) |
| `publish` (`:1555-1575`) | the Captain: rewrites the file with `status` and `updated` only (author, classification, `created` and `revision` gone), so it reads `ship`; its author: `PermissionError` |
| semantic backfill (`semantic.py:666-760`) | indexes it as `('ship', '')`, so Oracle's semantic tier hands it to every reader |
| `seed_manuals` (`:852-881`) over a hand-broken manual | overwrites it: the manual is re-seeded |
| a constructor error (`updated: 2026-13-05`) | `read_entry` raises `ValueError` for every reader; the search withholds it from every reader, the Captain included; `list_entries` does not list it, the backfill does not index it; `publish` raises; update-in-place overwrites it |

2. **Who is affected today.** Slice 1 fixed the framing and slice 2 the writers, so the store no longer writes such a document. What remains is documents written before slice 2 and hand-made ones. How many a vessel holds is what 7.4 counts on a read-only copy of its records; the result is not recorded in this repository.
3. **The box lists callers that need no change.** The similarity scan across topics and the convergence scan already skip such a document (table above), and the skill catalog already treats it as invalid (`skill_catalog.py:113-116` returns `None` on a `YAMLError`; `:782-792` returns without rewriting).
4. **Tests that pin what must not move.** BF-952's A6: `_parse_document` is called from the same frame as the base's, so the depth at which it raises `RecursionError` is the base's (`test_bf952_records_keyword_search.py:786`), and `read_entry` reads with `self._parse_document(raw)` (`:796`); T22 pins `_parse_document`'s and the search reader's reading of 1,359 shapes (`:508`); `test_every_reader_frames_and_loads_a_document_alike` pins it for a malformed block (`:307`). One test pins the old reading of this slice's subject: `:740-754` asserts that `read_entry` shows bob a note whose block PyYAML refuses (a tab after a key) as `{}`, and its docstring hands that to BF-940. The unedited test fails on M2's head with `TypeError` at `:750` (M-4): P2-19 edits it.
5. **The writers cannot simply refuse.** `seed_manuals` overwrites shipyard manuals by design on every boot (`:852-881`), and `startup/cognitive_services.py:600-619` calls it inside a `try` whose `except Exception` logs "Ship's Records failed to start" and sets `records_store = None`. A refusal in update-in-place makes `seed_manuals` raise on a hand-broken manual (measured, M-3).
6. **Consumers of the read route.** The HXI reads documents with `?reader=captain` (`ui/src/store/useStore.ts:2046, 2213`) and the search route reads as the Captain (`routers/records.py:187`); the route returns the store's mapping (`:102`) and promises that, without `format`, "the response body is byte-identical to what this endpoint has always returned" (AD-1145 DD-7, `:68-70`).

## 2. Solution

A document whose frontmatter did not load is read, by the access rules, as the private document of its path's owner: `{"classification": "private", "author": <callsign of notebooks/<callsign>/... or None>}` (`_unparsed_gate`). `None` equals no reader id, so only the owner is its author, and the anonymous `""` is refused. `read_entry` (non-Captain readers), the search's first pass (which is why a withheld document cannot move another reader's scores) and its second reading (`_base_reading_admits`) read that stand-in; the Captain and a reader that named no identity pass as for any private note. The first pass reads it where the search's own reading is empty: a note libyaml reads and PyYAML refuses (a tab after a key) has libyaml's reading there, so the search never shows such a note to a reader `read_entry` withholds it from, but an owner whom libyaml's reading excludes can miss a note `read_entry` gives her (L11, D5). Whether a document did not load is derived from the reading a reader already has (`_frontmatter_unparsed(raw, frontmatter)`: an empty reading, a block, and PyYAML refusing it with a `YAMLError`): `_parse_document`, `_search_read_document` and `read_entry`'s return are unchanged. `list_entries` marks the entry of such a document with `frontmatter_unparsed: True` (no other entry has the key) and the semantic backfill leaves it out of its pass and logs how many and the first five paths. `publish` raises `ValueError` naming the path, for the Captain too. Update-in-place proceeds as before and logs a WARNING naming the path. No config, event, dependency, persisted field or index metadata changes.

## 3. Decisions

Ranked by correctness, safety, compatibility, architectural fit, reversibility and validation cost; Delegated AD Execution Mode: the top is taken. Cells and sentences marked (read) are from source, not run; every other measurement is from my hand driver on the reading tree or on M2's head.

**D0. Who decides.** Slice 2's D3 recommended this policy as "a Captain decision" because it "withholds from a reader what the base showed him". That was written before the delegated-authority test. **Decided by the Architect: none of the six conditions under which the Captain decides in Delegated AD Execution Mode is met.**

| Condition | Met | Why |
|---|---|---|
| 1. An irreversible or destructive production-data operation | no | The change stops one: today the Captain's `publish` of such a note destroys its frontmatter lines (measured). Nothing is migrated or deleted, no file, git object or index row is written by the new code, and `RecordsStore.publish` has no production caller (Absence Verified, 1). Rows an earlier backfill wrote as `ship` stay (L3): purging them would be a condition-1 call and is not in this slice. Rollback: revert the commits; `auto_commit` defaults to True (`config_models/knowledge.py:322`), so a rewritten document's old text is in git. |
| 2. Weakening a security, privacy, consensus, authorization, audit or safety control | no | It strengthens one and gains nobody access. Base, for the YAML-error and tuple notes, notebook and report paths: `read_entry` and the keyword search hand the note to alice, bob, the Captain, `""` and `system`, and the backfill indexes it `ship`. After: the Captain, the owner of the notebook path, and (search) a reader that named no identity, as for any private note; every reader set is a strict subset of the base's (M-1). The cost is the availability of a document that is already broken, with the Captain's read and a one-line fix as the remedy. `deterministic-ship.md` invariant 6 (line 54): "Unknown is reported as unknown, never as a default or a success". Audit: git is the trail (`records_store.py:616-620`) and is untouched; update-in-place gains a WARNING. |
| 3. Breaking a public API, a persisted schema, a federation protocol or a compatibility promise | no | No signature, return shape or persisted field changes (`read_entry`'s mapping, the route body and `_parse_document` are as before; a denied read is the existing `None`, and the route's existing 404). The one new key is on a listing entry of such a document. The only statement of the old reading is `deterministic-ship.md:49`, which lists it as a gap (#1686), not a promise (Absence Verified, 2). The HXI reads as the Captain. One test pins the old reading and is edited (P2-19). |
| 4. New spending, a paid or incompatible dependency, a secret or credential, access to a live production system | no | None added (License posture). The census is a read-only copy. |
| 5. Moving information or implementation across the OSS/commercial boundary | no | OSS `knowledge/`. |
| 6. Accepting unresolved Critical/High risk, or changing the product objective beyond the issue | no | The box asks for "the policy for each caller". Residue (L3 to L6) is pre-existing or narrower than the base and is recorded. |

**Overrule option (ranked 2): the policy without the reader gate.** The listing marker, the backfill's skip, `publish`'s refusal and update-in-place's log stay; `read_entry` and the keyword search keep reading such a note as `{}` for everyone. Effect: a legacy private note stays readable by every crew reader through `read_entry`, the keyword search, dreaming (`dreaming.py:951, 1067`, reader `system`) and the diagnostic context (`diagnostic_context.py:414`), which is the box's premise left standing. Switching drops P2-3 to P2-6, P2-9 to P2-10 and P2-15 (7 of the 20 M2 pairs, with the stand-in's use in them) and 17 of the 26 class cases (T1 to T3, T8 to T11 and T13 of section 6); the other 9 class cases (T4 to T7: marker, backfill, publish, log; and T12, the verdict's nesting) stay, and so do the guards, S10 included.

**D1. What a reader gets** (rows: the three readers; measured, M-1).

| # | Option | `read_entry` | Keyword search | Notes |
|---|---|---|---|---|
| **1** | **The stand-in: private, author = the owner of `notebooks/<callsign>/...`, nobody elsewhere (chosen)** | Captain and the owner; `bob`, `""`, `system` get `None` | Captain, the owner and `None`; not `bob`, not `""` | a report's author cannot read it (L4); one rule for all readers (`record_is_readable` and `read_entry`'s gate run it unchanged) |
| 2 | Captain only | Captain | Captain, `None` | takes a note from its owner: BF-952's withdrawn RK10 (`DECISIONS.md:1360`) |
| 3 | Keep `{}` (slice 2's option 3) | everyone | everyone | the base; the box's premise left standing |
| 4 | Fail closed with an author of `""` | the anonymous `""` equals it and reads (slice 2's measurement) | same | here the author is `None`, which equals no reader id |
| 5 | Quarantine: move the file | the note vanishes | | a read with a side effect on the repository and on git |
| 6 | Recover the author by matching the `author:` line | | | a guess at what YAML refused |

Rank 1 > 2 > 3 > 4 > 5 > 6. The owner is taken from the **resolved** path (`file_path.relative_to(self._repo_path.resolve())`), never from the spelling the caller used: `notebooks/alice/../bob/x.md` is bob's (T10).

**D2. The writers** (rows: `publish`; update-in-place).

| # | Option | `publish` | Update-in-place |
|---|---|---|---|
| **1** | **`publish` refuses with `ValueError`, before the author check; update-in-place proceeds and logs a WARNING (chosen)** | the Captain and the author both get `ValueError` naming the path; nothing is written (base: the Captain's call destroys the lines; its author's raises `PermissionError`) | identical to the base for the writer, `seed_manuals` heals a hand-broken manual, `write_notebook` by the owner replaces her own note; the loss of `created` and `revision` is said, not hidden |
| 2 | Both refuse (slice 2's D3) | same | `seed_manuals` raises on a hand-broken manual, which startup turns into "Ship's Records failed to start"; `write_notebook` raises for the owner, so her note is stuck (measured, M-3) |
| 3 | `publish` edits the two lines as text | | a textual edit of a block YAML refused |
| 4 | Recover `created` and `revision` by a line match, or from git | | a guess; a git child per write |

Rank 1 > 3 > 2 > 4 for `publish` (nothing calls it in production, so it carries no availability cost) and 1 > 2 > 4 for update-in-place (a refusal has the boot hazard of Problem 5).

**D3. How the backfill learns it** (rows: where the failure travels; measured by reading `semantic.py:666-760`, (read)).

| # | Option | `read_entry` and the route body | Backfill | Pins |
|---|---|---|---|---|
| **1** | **A key on the `list_entries` entry, set only for such a document (chosen)** | unchanged | the entry is dropped before `pending[:limit]`: no read and no budget slot is spent on it, and it is indexed on the first pass after its frontmatter loads | `read_entry`'s mapping and AD-1145 DD-7 hold |
| 2 | A key on `read_entry`'s mapping (the box's wording) | the route returns it: the body of such a document changes | one read and one slot per such document per boot | the body promise `:68-70` |
| 3 | A new store method the backfill calls per path | unchanged | a second read per pending path | a duck-typed store in the backfill's tests gains a required method |
| 4 | `_parse_document` returns a typed result | | | BF-952 A6 pins its frame depth and 2-tuple shape (`:786`, `:796`, `:307`, `:508`) |
| 5 | Index it as private to the owner | | the row is stale after a hand repair (the backfill skips a held path) | |

Rank 1 > 2 > 3 > 5 > 4.

**D4. Where the verdict comes from, and what is not a parse failure.** `_frontmatter_unparsed(raw, frontmatter)` is called with the reading the caller already has (`_parse_document`'s, or the search's), so nothing in `_parse_document`, `_search_read_document` or `_search_load_frontmatter` moves. It loads the block itself, in its own frame, and never through a helper (round 1, F1). PyYAML's composer recurses about two Python frames for each level a block nests, so a frame between a caller and `yaml.safe_load` costs a nesting level at every other stack depth: a verdict one frame deeper than the reading it judges raised `RecursionError` on a document the base reads as `{}` (one that nests deep and then ends in a YAML error), the owner's read became a 503 and the listing lost the document. From the frame that called `_parse_document`, the load stops where the parse stops, for `read_entry`, `list_entries`, `publish` and update-in-place (S10 measures each against the same reader with the verdict neutralised; update-in-place swallows a verdict failure in its `try` and would lose its `revision` and its WARNING silently, so its case watches the `revision`) and for `_parse_document` itself (T12), each at both parities of the caller's stack depth, because whether one frame costs a level depends on that parity and on the interpreter: no case names a depth. The search's first pass loads two frames shallower than the search's own PyYAML reading (`_search_read_document`, `_search_load_frontmatter`, `_load_frontmatter`), so it cannot raise where that reading read, and it is called outside the search's `try`; `_base_reading_admits` loads through `_block_unparsed`, one frame in as its own reading is, inside a `try` that withholds. A reading that holds something is not a failure (a block the base's cut reads is read as the base read it: A1 of slice 1). A document with no frontmatter block (no opener, or no closing line: L18), an empty block, a falsy value (`[]`) and a comment-only block load to nothing without error and are not failures (S2, S3). A constructor error (`updated: 2026-13-05`), a recursion failure and a non-mapping frontmatter (slice 2's L11 and L13) are not touched: the readers already raise or withhold (S4). The search's second reading (`_base_reading_admits`) applies the same rule to the base's reading, so a note libyaml reads and PyYAML refuses (RK8) is never shown to a reader `read_entry` withholds it from (T11); its first pass applies it to the search's own reading, so a withheld document does not count toward the rarity of a term for another reader (T3; BF-952 A4). The converse does not hold: the first pass has libyaml's reading of such a note, so an owner whom that reading excludes does not find a note `read_entry` gives her (L11, D5, T13).

**D5. The owner's search under libyaml (round 1, F2).** A note libyaml reads and PyYAML refuses (a tab after each key) whose libyaml reading names another author (`author: bob`, `classification: private`, in alice's notebook): `read_entry` reads `{}` and gives it to alice and the Captain; the search's first pass has libyaml's reading, which excludes alice, and the second reading cannot add her. Measured: with libyaml, alice `[]`, bob `[]`, the Captain finds it; with the `SafeLoader` fallback that a host without libyaml runs, alice and the Captain find it and bob `[]`; base, with libyaml, alice `[]`, bob and the Captain find it. **Decided by the Architect: none of the six conditions in D0 is met** (nothing is weakened, no key or contract moves, nothing is spent or crosses a boundary; alice's miss is the base's own, and bob is narrowed as D0 decided). The ranked **overrule option is 2**.

| # | Option | The owner finds the note under libyaml | Cost and effect |
|---|---|---|---|
| **1** | **Keep the first pass; correct the claims; record L11 and pin it (T13) (chosen)** | no, where libyaml's reading names another author or a classification that excludes her; yes under PyYAML's loader | the base's miss, narrowed for bob; no new access, no new cost; every reader set stays a subset of the base's (D0, condition 2) |
| 2 | Admit the owner in the first pass where PyYAML refuses the block: for each record under `notebooks/<reader>/` that libyaml's reading refuses her, one `_block_unparsed` call | yes | adds the owner to the search's set for that note, so D0's subset claim becomes "of `read_entry`'s" for the search; a new branch in P2-5 with its own rows; her scores count it; one PyYAML load for each such record; T13's first loop assertion flips |
| 3 | Judge every record by PyYAML in the first pass (no libyaml there) | yes, and the readings agree | undoes BF-952's libyaml, about a third of the search's cost |
| 4 | Leave the claims as written | no | the text says what is false |

Rank 1 > 2 > 3 > 4. The claims that said the two readers agree are corrected in section 2, D4, L7, section 12, section 13, `PROGRESS.md`, `DECISIONS.md`, the `search` docstring, the first-pass comment and the BF-952 test's docstring; `deterministic-ship.md` says "no reader but that owner and the Captain" (an upper bound).

## 4. Milestones and gates

| M | Blocks | Gate |
|---|---|---|
| M1 | N1-1 | G1 |
| M2 | P2-1 to P2-19, then N2-1 (the marker) | G2 |
| M3 | P3-1 to P3-3, ledger | G3 |

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. **M0:** on the head, record the collected count (`--collect-only -q`) of every existing file G2 names, and the four counts of `PY -P scripts/check_architecture_principles.py --check`.

- **G1.** `PY -m pytest tests/test_bf940_s4_unparsed_frontmatter.py -q -n 0 -p no:randomly`. **Expected:** 46 cases, **20 passed, 26 xfailed**. The marker carries `raises=AssertionError, strict=True`: any other exception, or an XPASS, is a FAIL. Then once with `--runxfail`: each failure must stop at the `assert` section 6 names, never at a premise line (T12 stops at its first line, which asks whether the module has the verdict).
- **G2.** (1) `$f = git grep -l -E 'RecordsStore|records_store|_records_store|\.read_entry\(|\.list_entries\(|reindex_records|check_notebook_similarity|check_cross_agent_convergence|write_notebook|seed_manuals' -- 'tests/test_*.py'` (94 files on the reading tree; M0 records the count of the full list); then `PY -m pytest $f tests/test_bf940_s4_unparsed_frontmatter.py tests/test_layer_boundaries.py -q -n 0 -p no:randomly`. (2) `PY -P scripts/check_architecture_principles.py --check`. **Expected:** the new file's 46 passed; every other file 0 failed with collected counts equal to M0 (`tests/test_bf952_records_keyword_search.py` passes with P2-19 applied and fails at its `:750` without it); the check clean with its four counts equal to M0's.
- **G3.** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- **Census (not a Builder step).** Run 7.4 on a read-only copy of the vessel's `ship-records` before the pull request merges; a flagged document goes back to the Architect, and the repair or removal of a document is the Captain's.
- **Harness rule.** No source change made to pass a test, no skip, no loosened assertion. A failing case of the new file at G2, or any existing test failing, goes back to the Architect. The broad gate runs once, in the main session, with `--receipt`.

## 5. Commit messages

- **M1:** `BF-940 M1 (slice 4): tests for a document whose frontmatter does not load being private to its owner, xfail until built (#1686)`
- **M2:** `BF-940 M2 (slice 4): a document whose frontmatter does not load is private to the owner of its notebook directory: readers and search withhold it, the backfill leaves it out, publish refuses it (#1686)`
- **M3:** `BF-940 M3 (slice 4): trackers, ledger and the invariants document (#1686)`; its body ends with the line `Refs #1686.`

## 6. Tests

`tests/test_bf940_s4_unparsed_frontmatter.py` (M1; the functions pass on both trees, the class is strict xfail until M2). A case asserts its premise first (YAML refuses the block; the Captain reads the document as `{}` with its body; a healthy private note is refused to bob and read by alice), so a failure cannot mean the store was broken. Only T12 names a helper this slice adds, and it asks whether the module has it before it calls it, so each class case fails at an `assert`, not at an `AttributeError`; no class case uses `pytest.raises` for the behaviour under test (`Failed` is not an `AssertionError`), only in a premise line that shows PyYAML refusing the block, which holds on both trees. Platform: no case depends on the writer's depth limit, a case-folding file system, a name holding a lone surrogate or a nesting depth (the frontier cases, S10 and T12, find where PyYAML's composer overflows by bisection under the interpreter's recursion limit, at both parities of the caller's stack depth, and name no number); every carrier is YAML PyYAML refuses on every platform; each case that needs `~` moves `HOME` and `USERPROFILE` (the `store` fixture).

| Id | Cases | Covers | xfail until |
|---|---|---|---|
| S1 | 1 | Guard: a document that loads is read, found, listed (`{"path", "frontmatter"}` only) and published as before (`test_a_document_that_loads_is_read_listed_and_published_as_before`) | none |
| S2 | 5 | Guard: no frontmatter, an empty block, `[]`, a comment-only block and an opener with no closing line (L18) are not parse failures: bob reads and finds each, and no entry has the key (`test_a_document_with_nothing_to_load_is_not_a_parse_failure`) | none |
| S3 | 2 | Guard: a frontmatter the base's cut reads (a tag after a `---` in the topic), private or `ship`, is read as before, listed without the key and found by exactly the readers its classification admits (`test_a_frontmatter_that_loads_through_the_base_cut_is_not_a_parse_failure`) | none |
| S4 | 1 | Guard: a constructor error is refused to every reader as before (`test_a_constructor_error_is_refused_to_every_reader_as_before`) | none |
| S5 | 1 | Guard: the similarity and convergence scans skip such a document, against a positive control (`test_the_scans_skip_a_document_whose_frontmatter_does_not_load`) | none |
| S6 | 1 | Guard: update-in-place of such a note proceeds and `seed_manuals` re-seeds a hand-broken manual (`test_an_update_in_place_of_such_a_note_proceeds_and_seed_manuals_re_seeds_a_broken_manual`) | none |
| S7 | 2 | Guard: `_parse_document` of such a document is `({}, body)` (`test_the_parse_of_such_a_document_is_what_it_always_was`) | none |
| S8 | 2 | Guard: the Captain's `read_entry` mapping is `{"frontmatter": {}, "content", "path"}` with no new key (`test_read_entry_returns_the_mapping_it_always_returned_to_the_captain`) | none |
| S9 | 1 | Guard: the owner of a notebook directory reads and finds such a document at any depth (`test_the_owner_of_a_notebook_directory_reads_such_a_document_at_any_depth`) | none |
| S10 | 4 | Guard (`read_entry` as the owner, `list_entries`, `publish`, update-in-place): the reader parses a document that nests deep and then ends in a YAML error as deeply as it did before the verdict: the deepest nesting it reads, by bisection at both parities of the stack, equals the deepest with the verdict neutralised (`test_a_reader_parses_a_document_as_deeply_nested_as_it_did_before_the_verdict`) | none |
| T1 | 4 | Class: `read_entry` gives it to the Captain and the owner only, on a notebook and on a report path, for a YAML error and for a tuple (`test_read_entry_gives_it_to_the_captain_and_the_owner_only`) | M2 |
| T2 | 4 | Class: the keyword search finds it for the Captain, the owner and `None` only (`test_the_keyword_search_finds_it_for_the_captain_the_owner_and_an_identity_less_search_only`) | M2 |
| T3 | 1 | Class: a document withheld from a reader does not move the scores that reader is shown (`test_a_document_withheld_from_a_reader_does_not_move_the_scores_that_reader_is_shown`) | M2 |
| T4 | 3 | Class: the listing marks the entry of such a document (a YAML error, a tuple, a tab after a key) and no other (`test_the_listing_marks_the_entry_of_such_a_document_and_no_other`) | M2 |
| T5 | 1 | Class: the backfill leaves seven such documents out, indexes the two that load, and logs one WARNING with the count and the first five paths and no value (`test_the_semantic_backfill_leaves_such_a_document_out_and_names_it`) | M2 |
| T6 | 3 | Class: `publish` raises `ValueError` naming the path for the Captain, the author and another reader and writes nothing (`test_publish_refuses_such_a_document_for_everyone_and_writes_nothing`) | M2 |
| T7 | 1 | Class: update-in-place logs one WARNING naming the path and no value, and proceeds (`test_an_update_in_place_of_such_a_note_logs_its_path_and_proceeds`) | M2 |
| T8 | 1 | Class, across the seams: file, readers, backfill, the owner's repair, readers, backfill again (`test_a_legacy_private_note_stays_private_through_the_readers_the_index_and_its_owners_repair`) | M2 |
| T9 | 4 | Class: nobody else is the owner (a callsign that is a prefix, a file straight under `notebooks/`, a callsign under `reports/`, another callsign) (`test_nobody_else_is_the_owner_of_such_a_document`) | M2 |
| T10 | 1 | Class: the owner is taken from the resolved path, not the spelling (`test_the_owner_is_taken_from_the_resolved_path_not_from_its_spelling`) | M2 |
| T11 | 1 | Class: a note only libyaml reads (a tab after a key, `ship`) is withheld by the search where `read_entry` withholds it (`test_a_note_only_libyaml_reads_is_withheld_by_the_search_where_read_entry_withholds_it`) | M2 |
| T12 | 1 | Class: the verdict loads such a block as deeply nested as `_parse_document` does when both are called from one frame, at both parities of the stack (`test_the_verdict_loads_the_block_as_deeply_nested_as_the_parse_the_caller_has_just_run`) | M2 |
| T13 | 1 | Class: a note libyaml reads and PyYAML refuses whose libyaml reading names another author (a tab after each key, `author: bob`, `private`, in alice's notebook) is withheld from bob by `read_entry` and by the search under either loader, given to alice by `read_entry`, and found by her search only under PyYAML's loader: L11, a recorded limit and not a promise (`test_a_note_libyaml_reads_with_another_author_is_found_by_its_owner_only_where_the_search_loads_with_pyyaml`) | M2 |

**How each xfail case fails on the unfixed tree** (hand driver, reading tree): T1 and T2 at `assert (entry is not None) == shown, reader` (`bob` for a notebook path, `alice` for a report path); T3 at `assert await scores(store, "bob") == expected`, after its two premises; T4 at `assert entries[path] == {"path": path, "frontmatter": {}, _KEY: True}`; T5 at `assert indexed == 2 and ...` (it indexes nine); T6 at `assert kind is ValueError and path in message` (the Captain's call returns, the others raise `PermissionError`); T7 at `assert len(warned) == 1 and ...` (no WARNING); T8 at `assert await store.read_entry(legacy, reader_id="bob") is None`; T9 at `assert await store.read_entry(path, reader_id=reader) is None`; T10 and T11 at their `read_entry(..., "alice")` and `read_entry(..., "bob")` asserts; T12 at its first line, `assert hasattr(records_store_module, "_frontmatter_unparsed")`, because the base has no verdict; T13 at `assert await store.read_entry(path, reader_id="bob") is None`. **Guards that pass on both trees:** S1 to S10 (S10 neutralises a verdict the base does not have; on a tree whose verdict loads one frame deeper than its reading, the candidate as built and rows 26 and 27, it fails, at one parity of the stack or the other). A source-scan caveat: no test here scans source; the BF-952 A6 pins (`:786`, `:796`) are existing tests and run in G2.

## 7. The contract

### 7.1 M1

**N1-1.** New file `tests/test_bf940_s4_unparsed_frontmatter.py`:
```python
"""BF-940 slice 4 (#1686, L19): a document whose frontmatter does not load is private to the owner of its notebook directory.

YAML refused the frontmatter of such a document (broken YAML, or the ``!!python/tuple`` tag an older ``write_entry`` wrote), so every
reader read it as ``{}``, the default ``ship`` classification: ``read_entry`` and the keyword search handed it to every reader, the
semantic backfill indexed it as ``ship`` and a Captain's ``publish`` rewrote it with a status and a time only. Real ``RecordsStore``
over ``tmp_path`` with ``~`` moved and hand-made documents; the backfill runs against the one collection method it uses, not ChromaDB.

The class is strict xfail until M2 (each case fails at an ``assert`` of its own body on the unfixed tree, after its premise); the
module's functions are guards and pass on both trees: they hold what this slice must not change (a document with no frontmatter, an
empty one or an unclosed opener; a frontmatter the base's cut reads; a constructor error; the scans; the parse and the mapping
``read_entry`` returns; an update-in-place, which ``seed_manuals`` runs at every boot; how deeply nested a document each reader
parses before ``RecursionError``, which the verdict must not lower: S10). A case asserts its premise first (YAML refuses
the block, the Captain reads the document, a healthy private note is refused to bob), so "bob is refused" cannot mean the store was
broken.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from probos.config import RecordsConfig
from probos.knowledge import records_store as records_store_module
from probos.knowledge.records_store import RecordsStore
from probos.knowledge.semantic import SemanticKnowledgeLayer

_KEY = "frontmatter_unparsed"
_BODY = "private warp body"
_BROKEN = "author: alice\nclassification: private\nstatus: draft\nbroken: [unclosed\n"
_TAGGED = "author: alice\nclassification: private\nstatus: draft\nmetrics:\n  sample: !!python/tuple\n  - 1\n  - 2\n"
_TABBED = "author:\talice\nclassification:\tprivate\n"
_REFUSED = [
    pytest.param(_BROKEN, id="broken-yaml"),
    pytest.param(_TAGGED, id="python-tag"),
]
_PLACES = [
    pytest.param("notebooks/alice/note.md", True, id="alices-notebook"),
    pytest.param("reports/note.md", False, id="a-report"),
]
_NOT_A_PARSE_FAILURE = [
    pytest.param("warp plain body\n", id="no-frontmatter"),
    pytest.param("---\n---\n\nwarp empty body\n", id="an-empty-frontmatter"),
    pytest.param("---\n[]\n---\n\nwarp falsy body\n", id="a-falsy-frontmatter"),
    pytest.param("---\n# a comment only\n---\n\nwarp comment body\n", id="a-comment-only-frontmatter"),
    pytest.param("---\nauthor: alice\nclassification: private\nwarp never closed body\n", id="an-opener-with-no-closing-line"),
]


class _Collection:
    """The one method the records index uses of a ChromaDB collection, and the lookup the backfill makes."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, dict[str, Any]]] = {}

    def upsert(self, ids: list[str], documents: list[str], metadatas: list[dict[str, Any]]) -> None:
        self.rows[ids[0]] = (documents[0], metadatas[0])

    def get(self, ids: list[str], include: Any = None) -> dict[str, list[str]]:
        return {"ids": [i for i in ids if i in self.rows]}


def _make_store(root: Path) -> RecordsStore:
    root.mkdir(parents=True, exist_ok=True)
    return RecordsStore(RecordsConfig(repo_path=str(root), auto_commit=False))


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RecordsStore:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert Path.home() == home, "premise: ~ is the temporary home"
    return _make_store(tmp_path / "ship-records")


def _raw(block: str, body: str = _BODY) -> str:
    return f"---\n{block}---\n\n{body}\n"


def _hand_made(store: RecordsStore, path: str, text: str) -> None:
    target = store.repo_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _healthy(store: RecordsStore, path: str, body: str, **frontmatter: Any) -> None:
    values = {"author": "captain", "classification": "ship", "status": "published", **frontmatter}
    _hand_made(store, path, f"---\n{yaml.safe_dump(values, sort_keys=False)}---\n\n{body}\n")


async def _found(store: RecordsStore, reader_id: str | None, query: str = "warp") -> list[str]:
    return [hit["path"] for hit in await store.search(query, scope="ship", reader_id=reader_id)]


async def _attempt(call: Any) -> tuple[type | None, str]:
    try:
        await call
    except Exception as exc:  # noqa: BLE001 -- the case asserts on the type and the text
        return type(exc), str(exc)
    return None, ""


async def _premise(store: RecordsStore, path: str, block: str) -> None:
    """YAML refuses the block; the Captain reads the document as ``{}`` with its body; a healthy private note is refused to bob."""
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(block)
    _hand_made(store, path, _raw(block))
    control = "notebooks/alice/control.md"
    _healthy(store, control, "control body", author="alice", classification="private")
    assert await store.read_entry(control, reader_id="bob") is None, "premise: the gate refuses a private note"
    assert await store.read_entry(control, reader_id="alice") is not None, "premise: its author reads it"
    assert await store.read_entry(path, reader_id="captain") == {"frontmatter": {}, "content": _BODY, "path": path}, "premise: {}"


async def test_a_document_that_loads_is_read_listed_and_published_as_before(store):
    private, shared = "notebooks/alice/private.md", "reports/open.md"
    _healthy(store, private, "private warp", author="alice", classification="private")
    _healthy(store, shared, "open warp")
    assert await store.read_entry(private, reader_id="bob") is None
    own = await store.read_entry(private, reader_id="alice")
    assert own is not None and set(own) == {"frontmatter", "content", "path"}
    assert sorted(await _found(store, "alice")) == [private, shared] and await _found(store, "bob") == [shared]
    assert all(set(entry) == {"path", "frontmatter"} for entry in await store.list_entries())
    await store.publish(private, "alice")
    published = await store.read_entry(private, reader_id="alice")
    assert published is not None and published["frontmatter"]["status"] == "published" and published["frontmatter"]["author"] == "alice"


@pytest.mark.parametrize("text", _NOT_A_PARSE_FAILURE)
async def test_a_document_with_nothing_to_load_is_not_a_parse_failure(store, text):
    path = "notebooks/alice/note.md"
    _hand_made(store, path, text)
    assert await store.read_entry(path, reader_id="captain") is not None, "premise: the Captain reads it"
    assert await store.read_entry(path, reader_id="bob") is not None
    assert path in await _found(store, "bob")
    listed = [entry for entry in await store.list_entries() if entry["path"] == path]
    assert len(listed) == 1 and _KEY not in listed[0]


@pytest.mark.parametrize("classification", ["private", "ship"])
async def test_a_frontmatter_that_loads_through_the_base_cut_is_not_a_parse_failure(store, classification):
    path = "notebooks/alice/review---nominal.md"
    block = f"author: alice\nclassification: {classification}\nstatus: draft\ntopic: review---nominal\nmetrics:\n  sample: !!python/tuple\n  - 1\n  - 2\n"
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(block)
    _hand_made(store, path, _raw(block, "coolant private body"))
    own = await store.read_entry(path, reader_id="alice")
    assert own is not None and own["frontmatter"]["classification"] == classification, "premise: the cut reads it as alice's note"
    shown = classification == "ship"
    assert (await store.read_entry(path, reader_id="bob") is not None) == shown
    assert (path in await _found(store, "bob", "coolant")) == shown
    assert [e for e in await store.list_entries() if e["path"] == path] == [{"path": path, "frontmatter": own["frontmatter"]}]


async def test_a_constructor_error_is_refused_to_every_reader_as_before(store):
    path = "notebooks/alice/dated.md"
    with pytest.raises(ValueError):
        yaml.safe_load("updated: 2026-13-05\n")  # premise: a constructor error, which is not a YAMLError
    _hand_made(store, path, _raw("author: alice\nclassification: private\nupdated: 2026-13-05\n"))
    for reader in ("alice", "bob", "captain"):
        assert (await _attempt(store.read_entry(path, reader_id=reader)))[0] is ValueError, reader
        assert await _found(store, reader) == [], reader
    assert await store.list_entries() == []
    assert (await _attempt(store.publish(path, "captain")))[0] is ValueError


async def test_the_scans_skip_a_document_whose_frontmatter_does_not_load(store):
    words = "warp core coolant alpha beta gamma delta epsilon zeta eta theta"
    await store.write_notebook("alice", "other", words, department="dept_a")
    await store.write_notebook("carol", "n2", words, department="dept_c")
    assert (await store.check_notebook_similarity("alice", "newslug", words))["action"] == "suppress", "premise: a healthy note answers"
    matches = (await store.check_cross_agent_convergence("bob", "dept_b", "warp", words))["convergence_matches"]
    assert sorted(m["callsign"] for m in matches) == ["alice", "carol"], "premise: healthy notes converge"
    _hand_made(store, "notebooks/alice/other.md", _raw(_BROKEN, words))
    assert (await store.check_notebook_similarity("alice", "newslug", words))["action"] == "write"
    matches = (await store.check_cross_agent_convergence("bob", "dept_b", "warp", words))["convergence_matches"]
    assert sorted(m["callsign"] for m in matches) == ["carol"]


async def test_an_update_in_place_of_such_a_note_proceeds_and_seed_manuals_re_seeds_a_broken_manual(store, tmp_path):
    path = "notebooks/alice/nb.md"
    _hand_made(store, path, _raw(_TAGGED))
    assert await store.write_notebook("alice", "nb", "replacement body") == path
    again = await store.read_entry(path, reader_id="alice")
    assert again is not None and again["content"] == "replacement body"
    assert again["frontmatter"]["author"] == "alice" and again["frontmatter"]["classification"] == "private"
    source = tmp_path / "manuals"
    source.mkdir()
    (source / "m.md").write_text("# Manual\n\nmanual warp body\n", encoding="utf-8")
    _hand_made(store, "manuals/m.md", _raw(_BROKEN, "old"))
    assert await store.seed_manuals(source) == 1
    seeded = await store.read_entry("manuals/m.md", reader_id="bob")
    assert seeded is not None and seeded["frontmatter"]["author"] == "shipyard" and "manual warp body" in seeded["content"]


@pytest.mark.parametrize("block", _REFUSED)
def test_the_parse_of_such_a_document_is_what_it_always_was(store, block):
    assert store._parse_document(_raw(block)) == ({}, _BODY)


@pytest.mark.parametrize("block", _REFUSED)
async def test_read_entry_returns_the_mapping_it_always_returned_to_the_captain(store, block):
    path = "notebooks/alice/note.md"
    _hand_made(store, path, _raw(block))
    assert await store.read_entry(path, reader_id="captain") == {"frontmatter": {}, "content": _BODY, "path": path}


async def test_the_owner_of_a_notebook_directory_reads_such_a_document_at_any_depth(store):
    for path in ("notebooks/alice/note.md", "notebooks/alice/sub/deeper/note.md"):
        _hand_made(store, path, _raw(_BROKEN))
        assert await store.read_entry(path, reader_id="alice") is not None, path
        assert path in await _found(store, "alice"), path


def _frontier_block(depth: int) -> str:
    """A frontmatter block nesting ``depth`` block sequences and then ending in a YAML error (an unclosed flow sequence)."""
    return f"nested:\n{'- ' * depth}deep\nbroken: [unclosed\n"


def _frontier_document(depth: int) -> str:
    """PyYAML's composer recurses while it builds the nest and refuses the block only after it, so a reader that survives the nest
    reads this document as ``{}``: a document whose frontmatter did not load, nested ``depth`` deep."""
    return _raw(_frontier_block(depth))


async def _padded(pad: int, call: Any) -> Any:
    """``await call()`` with ``pad`` more coroutine frames beneath it."""
    if pad:
        return await _padded(pad - 1, call)
    return await call()


async def _frontier(read: Any, pad: int) -> int:
    """The deepest ``depth`` for which ``await read(depth)`` is true, by bisection, with ``pad`` frames beneath the call (F1).

    PyYAML's composer recurses about two Python frames for each level a block nests, so whether one frame more beneath a call costs
    it a nesting level depends on the parity of the stack it is called from, which no case controls. Every reader compared is
    therefore measured at both parities (``pad`` 0 and 1), and the depth is never a number in this file. The premises fail loudly where
    the probe finds nothing: the shallow document must read and the one as deep as the recursion limit must not. A ``RecursionError``
    is "does not read".
    """

    async def reads(depth: int) -> bool:
        try:
            return bool(await _padded(pad, lambda: read(depth)))
        except RecursionError:
            return False

    low, high = 2, sys.getrecursionlimit()
    assert await reads(low), "premise: a shallow document reads"
    assert not await reads(high), "premise: a document as deep as the recursion limit does not"
    while high - low > 1:
        middle = (low + high) // 2
        if await reads(middle):
            low = middle
        else:
            high = middle
    return low


async def _read_entry_reads(store: RecordsStore, path: str) -> bool:
    await store.read_entry(path, reader_id="alice")
    return True


async def _list_entries_reads(store: RecordsStore, path: str) -> bool:
    return path in [entry["path"] for entry in await store.list_entries()]  # the listing leaves out a document it could not read


async def _publish_reads(store: RecordsStore, path: str) -> bool:
    try:
        await store.publish(path, "captain")
    except ValueError:  # the refusal of such a document: the parse and the verdict were both reached
        pass
    return True


async def _update_in_place_reads(store: RecordsStore, path: str) -> bool:
    await store.write_entry("alice", path, "replacement body", "frontier", classification="private")
    entry = await store.read_entry(path, reader_id="captain")
    return entry is not None and entry["frontmatter"].get("revision") == 2  # a RecursionError on the old text is logged and dropped: no revision


def _never(raw: str, frontmatter: Any) -> bool:
    return False


@pytest.mark.parametrize("reader", [
    pytest.param(_read_entry_reads, id="read-entry"),
    pytest.param(_list_entries_reads, id="list-entries"),
    pytest.param(_publish_reads, id="publish"),
    pytest.param(_update_in_place_reads, id="update-in-place"),
])
async def test_a_reader_parses_a_document_as_deeply_nested_as_it_did_before_the_verdict(store, monkeypatch, reader):
    """F1: the verdict must not make a reader stop at a shallower nesting than its own parse. The reference is the same reader with the
    verdict neutralised (``raising=False``: the base has none, so this guard passes there too); the document nests deep and then ends
    in a YAML error, so the parse reads it as ``{}`` and the verdict is reached."""
    path = "notebooks/alice/n.md"
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(_frontier_block(2))
    assert store._parse_document(_frontier_document(2)) == ({}, _BODY), "premise: a shallow document of this shape reads as {}"

    async def read_at(depth: int) -> bool:
        _hand_made(store, path, _frontier_document(depth))
        return await reader(store, path)

    for pad in (0, 1):
        with monkeypatch.context() as patch:
            patch.setattr(records_store_module, "_frontmatter_unparsed", _never, raising=False)
            before = await _frontier(read_at, pad)
        assert await _frontier(read_at, pad) == before, f"the verdict lowered the nesting this reader reads (pad {pad})"


@pytest.mark.xfail(reason="BF-940 slice 4 M2: not built", raises=AssertionError, strict=True)
class TestADocumentWhoseFrontmatterDoesNotLoadIsPrivateToItsOwner:
    @pytest.mark.parametrize("block", _REFUSED)
    @pytest.mark.parametrize(("path", "owned"), _PLACES)
    async def test_read_entry_gives_it_to_the_captain_and_the_owner_only(self, store, block, path, owned):
        await _premise(store, path, block)
        for reader, shown in {"alice": owned, "bob": False, "captain": True, "": False, "system": False}.items():
            entry = await store.read_entry(path, reader_id=reader)
            assert (entry is not None) == shown, reader
            assert entry is None or entry == {"frontmatter": {}, "content": _BODY, "path": path}, reader

    @pytest.mark.parametrize("block", _REFUSED)
    @pytest.mark.parametrize(("path", "owned"), _PLACES)
    async def test_the_keyword_search_finds_it_for_the_captain_the_owner_and_an_identity_less_search_only(
        self, store, block, path, owned,
    ):
        await _premise(store, path, block)
        for reader, shown in {"alice": owned, "bob": False, "captain": True, None: True, "": False}.items():
            assert (path in await _found(store, reader)) == shown, reader

    async def test_a_document_withheld_from_a_reader_does_not_move_the_scores_that_reader_is_shown(self, store, tmp_path):
        plain = _make_store(tmp_path / "plain")
        for target in (store, plain):
            _healthy(target, "reports/h1.md", "warp")
            _healthy(target, "reports/h2.md", "coolant")
        _hand_made(store, "notebooks/alice/u.md", _raw(_BROKEN, "warp"))

        async def scores(target: RecordsStore, reader: str) -> dict[str, float]:
            return {hit["path"]: hit["score"] for hit in await target.search("warp coolant", scope="ship", reader_id=reader)}

        expected = await scores(plain, "bob")
        assert set(expected) == {"reports/h1.md", "reports/h2.md"}, "premise: the healthy documents are found"
        assert await scores(store, "captain") != await scores(plain, "captain"), "premise: a document a reader may read moves the scores"
        assert await scores(store, "bob") == expected

    @pytest.mark.parametrize("block", [
        pytest.param(_BROKEN, id="broken-yaml"),
        pytest.param(_TAGGED, id="python-tag"),
        pytest.param(_TABBED, id="tab-after-key"),
    ])
    async def test_the_listing_marks_the_entry_of_such_a_document_and_no_other(self, store, block):
        path = "notebooks/alice/note.md"
        with pytest.raises(yaml.YAMLError):
            yaml.safe_load(block)
        _hand_made(store, path, _raw(block))
        _healthy(store, "reports/ok.md", "healthy body")
        entries = {entry["path"]: entry for entry in await store.list_entries()}
        assert set(entries) == {path, "reports/ok.md"}, "premise: the listing holds both"
        assert _KEY not in entries["reports/ok.md"], "premise: a document that loads has no key"
        assert entries[path] == {"path": path, "frontmatter": {}, _KEY: True}

    async def test_the_semantic_backfill_leaves_such_a_document_out_and_names_it(self, store, tmp_path, caplog):
        column = _Collection()
        layer = SemanticKnowledgeLayer(tmp_path / "semantic")
        layer._collections = {"records": column}
        _healthy(store, "reports/open.md", "open warp")
        _healthy(store, "notebooks/alice/private.md", "private warp", author="alice", classification="private")
        legacy = [f"notebooks/alice/legacy-{n}.md" for n in range(7)]
        for path in legacy:
            _hand_made(store, path, _raw(_TAGGED, "legacy warp body"))
        with caplog.at_level(logging.WARNING, logger="probos.knowledge.semantic"):
            indexed = await layer.reindex_records(store)
        assert indexed == 2 and sorted(column.rows) == ["record_notebooks/alice/private.md", "record_reports/open.md"]
        assert column.rows["record_notebooks/alice/private.md"][1]["classification"] == "private"
        logged = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert len(logged) == 1 and "7 record(s)" in logged[0] and "legacy warp body" not in logged[0]
        assert all(path in logged[0] for path in legacy[:5]) and not any(path in logged[0] for path in legacy[5:])

    @pytest.mark.parametrize("who", ["captain", "alice", "bob"])
    async def test_publish_refuses_such_a_document_for_everyone_and_writes_nothing(self, store, who):
        path = "notebooks/alice/note.md"
        _hand_made(store, path, _raw(_TAGGED))
        before = (store.repo_path / path).read_bytes()
        kind, message = await _attempt(store.publish(path, who))
        assert kind is ValueError and path in message, (kind, message)
        assert _BODY not in message
        assert (store.repo_path / path).read_bytes() == before

    async def test_an_update_in_place_of_such_a_note_logs_its_path_and_proceeds(self, store, caplog):
        path = "notebooks/alice/nb.md"
        _hand_made(store, path, _raw(_TAGGED))
        with caplog.at_level(logging.WARNING, logger="probos.knowledge.records_store"):
            assert await store.write_notebook("alice", "nb", "replacement body") == path
        warned = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warned) == 1 and path in warned[0] and "replacement body" not in warned[0] and _BODY not in warned[0]
        own = await store.read_entry(path, reader_id="alice")
        assert own is not None and own["content"] == "replacement body"

    async def test_a_legacy_private_note_stays_private_through_the_readers_the_index_and_its_owners_repair(self, store, tmp_path):
        column = _Collection()
        layer = SemanticKnowledgeLayer(tmp_path / "semantic")
        layer._collections = {"records": column}
        legacy, shared = "notebooks/alice/legacy.md", "reports/open.md"
        _healthy(store, shared, "open warp")
        _hand_made(store, legacy, _raw(_TAGGED, "legacy warp body"))
        assert legacy in await _found(store, "alice") and legacy in await _found(store, "captain"), "premise: its owner and the Captain find it"
        assert await store.read_entry(legacy, reader_id="bob") is None
        assert await _found(store, "bob") == [shared]
        assert await layer.reindex_records(store) == 1 and sorted(column.rows) == [f"record_{shared}"]
        assert await store.write_notebook("alice", "legacy", "repaired warp body") == legacy
        assert await store.read_entry(legacy, reader_id="bob") is None and await _found(store, "bob") == [shared]
        mine = await store.read_entry(legacy, reader_id="alice")
        assert mine is not None and mine["frontmatter"]["classification"] == "private" and legacy in await _found(store, "alice")
        assert await layer.reindex_records(store) == 1
        metadata = column.rows[f"record_{legacy}"][1]
        assert metadata["classification"] == "private" and metadata["author"] == "alice"

    @pytest.mark.parametrize(("path", "reader"), [
        pytest.param("notebooks/alice2/note.md", "alice", id="a-callsign-that-is-a-prefix-is-not-the-owner"),
        pytest.param("notebooks/loose.md", "loose.md", id="a-file-straight-under-notebooks-has-no-owner"),
        pytest.param("reports/alice/note.md", "alice", id="only-a-notebook-directory-names-an-owner"),
        pytest.param("notebooks/bob/note.md", "alice", id="another-callsigns-notebook"),
    ])
    async def test_nobody_else_is_the_owner_of_such_a_document(self, store, path, reader):
        _hand_made(store, path, _raw(_BROKEN))
        assert await store.read_entry(path, reader_id="captain") is not None, "premise: the Captain reads it"
        assert await store.read_entry(path, reader_id=reader) is None
        assert path not in await _found(store, reader)

    async def test_the_owner_is_taken_from_the_resolved_path_not_from_its_spelling(self, store):
        (store.repo_path / "notebooks" / "alice").mkdir(parents=True)
        _hand_made(store, "notebooks/bob/note.md", _raw(_BROKEN))
        spelled = "notebooks/alice/../bob/note.md"
        assert await store.read_entry(spelled, reader_id="captain") is not None, "premise: the spelling reaches the document"
        assert await store.read_entry(spelled, reader_id="bob") is not None
        assert await store.read_entry(spelled, reader_id="alice") is None

    async def test_a_note_only_libyaml_reads_is_withheld_by_the_search_where_read_entry_withholds_it(self, store):
        path = "notebooks/alice/tabbed.md"
        block = "author:\talice\nclassification:\tship\n"
        with pytest.raises(yaml.YAMLError):
            yaml.safe_load(block)
        _hand_made(store, path, _raw(block))
        assert await store.read_entry(path, reader_id="bob") is None
        assert path not in await _found(store, "bob")
        assert path in await _found(store, "alice") and path in await _found(store, "captain")

    async def test_the_verdict_loads_the_block_as_deeply_nested_as_the_parse_the_caller_has_just_run(self, store):
        """F1: called from one frame, ``_parse_document`` and the verdict stop at the same nesting, at both parities of the stack: the
        verdict is the one reading a caller makes after the parse, from the same frame."""
        assert hasattr(records_store_module, "_frontmatter_unparsed"), "premise: the verdict is a function of the module"
        verdict = records_store_module._frontmatter_unparsed
        with pytest.raises(yaml.YAMLError):
            yaml.safe_load(_frontier_block(2))
        assert store._parse_document(_frontier_document(2)) == ({}, _BODY), "premise: a shallow document of this shape reads as {}"

        async def parsed(depth: int) -> bool:
            store._parse_document(_frontier_document(depth))
            return True

        async def judged(depth: int) -> bool:
            return verdict(_frontier_document(depth), {}) is True

        for pad in (0, 1):
            assert await _frontier(judged, pad) == await _frontier(parsed, pad), f"the verdict stops sooner than the parse (pad {pad})"

    async def test_a_note_libyaml_reads_with_another_author_is_found_by_its_owner_only_where_the_search_loads_with_pyyaml(
        self, store, monkeypatch,
    ):
        """L11, a recorded limit and not a promise: the search's first pass has libyaml's reading of a note PyYAML refuses (a tab after
        each key). Where that reading names another author, it excludes the owner of the directory though ``read_entry`` gives her the
        note, and the second reading cannot add her; bob is withheld by both readings and the Captain finds it. A change that lets her
        find it under libyaml changes the first assertion of the loop on purpose."""
        path = "notebooks/alice/tabbed.md"
        block = "author:\tbob\nclassification:\tprivate\n"
        with pytest.raises(yaml.YAMLError):
            yaml.safe_load(block)
        _hand_made(store, path, _raw(block))
        assert await store.read_entry(path, reader_id="bob") is None
        own = await store.read_entry(path, reader_id="alice")
        assert own is not None and own["frontmatter"] == {}, "premise: read_entry gives her the note"
        assert await store.read_entry(path, reader_id="captain") is not None
        for loader in (yaml.SafeLoader, records_store_module._RECORDS_YAML_LOADER):  # a host without libyaml, then this host's own
            monkeypatch.setattr(records_store_module, "_RECORDS_YAML_LOADER", loader)
            assert (path in await _found(store, "alice")) == (loader is yaml.SafeLoader), loader
            assert path not in await _found(store, "bob"), loader
            assert path in await _found(store, "captain"), loader
```

### 7.2 M2

**P2-1.** `src/probos/knowledge/records_store.py`, the key and the stand-in the access rules read (after `_UNRESTRICTED_READER`; the SEARCH occurs once):
SEARCH:
```
# BF-679: the one reader id with unrestricted read access (``read_entry``'s rule).
_UNRESTRICTED_READER = "captain"
```
REPLACE:
```
# BF-679: the one reader id with unrestricted read access (``read_entry``'s rule).
_UNRESTRICTED_READER = "captain"

#: BF-940 slice 4 (L19): the key an entry of ``RecordsStore.list_entries`` carries, set to ``True`` and only then, for a document whose
#: frontmatter did not load, so that a caller which acts on the document (the semantic backfill) can tell that it reads as ``{}``
#: because YAML refused its frontmatter and not because it holds none. Owned here; ``knowledge.semantic`` imports it, as it imports
#: ``_UNRESTRICTED_READER``.
FRONTMATTER_UNPARSED_KEY = "frontmatter_unparsed"


def _unparsed_gate(rel_path: str) -> dict[str, Any]:
    """BF-940 slice 4 (L19): the frontmatter the access rules read for a document whose own did not load.

    Its classification and its author are unknown, so it is private, and its author is nobody, except under
    ``notebooks/<callsign>/``, where the notebook's owner is the author. ``None`` equals no reader id (the anonymous ``""``
    included), so only the owner is its author; the Captain and a reader that named no identity pass the rules as they do for any
    private document (:func:`record_is_readable`, :meth:`RecordsStore.read_entry`). ``rel_path`` is the document's path in the
    repository, as the walk of the search names it and as ``read_entry`` resolves it.
    """
    parts = rel_path.split("/")
    owner = parts[1] if len(parts) >= 3 and parts[0] == "notebooks" else None
    return {"classification": "private", "author": owner}
```

**P2-2.** `src/probos/knowledge/records_store.py`, the two predicates (after `_load_frontmatter`; the SEARCH occurs once):
SEARCH:
```
    try:
        return yaml.safe_load(block) or {}
    except yaml.YAMLError:  # A5: the base's own catch; a constructor error or a RecursionError propagates
        return {}
```
REPLACE:
```
    try:
        return yaml.safe_load(block) or {}
    except yaml.YAMLError:  # A5: the base's own catch; a constructor error or a RecursionError propagates
        return {}


def _block_unparsed(block: str) -> bool:
    """BF-940 slice 4 (L19): whether ``yaml.safe_load``, the base's call, refuses a frontmatter block with a ``YAMLError``.

    That is the one way a block reads as ``{}`` without holding nothing: broken YAML, or a tag ``safe_load`` refuses (the
    ``!!python/tuple`` an older ``write_entry`` wrote). A block that loads to nothing (blank, ``[]``) is not refused. Any other error
    (a constructor's ``ValueError``, a ``RecursionError``) is not caught here: ``read_entry`` raises on it and the search withholds it.
    """
    try:
        yaml.safe_load(block)
    except yaml.YAMLError:
        return True
    return False


def _frontmatter_unparsed(raw: str, frontmatter: Any) -> bool:
    """BF-940 slice 4 (L19): whether the document ``raw``, which a reader read as ``frontmatter``, has a frontmatter that did not load.

    ``frontmatter`` is ``_parse_document``'s reading or the search's. A reading that holds something loaded. A document with no
    frontmatter block (no opener, or no closing line: L18) has none to refuse. What is left reads as ``{}``, and only the block
    says why: it loads to nothing, or YAML refused it (the ``YAMLError`` caught below). The block is the one the readers load
    (:func:`probos.utils.frontmatter.split_frontmatter`); where it reads as nothing and the base's cut of the text reads as
    something, the reading holds something and this is ``False`` (A1).

    BF-940 slice 4, round 1 (F1): the block is loaded here, in this frame, and not through :func:`_block_unparsed`. PyYAML's composer
    recurses about two Python frames for each level a block nests, so a frame between a caller and ``yaml.safe_load`` costs a nesting
    level at every other stack depth: a document that nests deep and then ends in a YAML error was read by ``_parse_document``, which
    the caller runs in its own frame, and raised ``RecursionError`` here one level sooner. Loaded from the caller's frame, this call
    stops at the nesting ``_parse_document``'s does for ``read_entry``, ``list_entries``, ``publish`` and update-in-place, and has two
    frames to spare below the search's own PyYAML reading (:func:`_search_read_document`, :func:`_search_load_frontmatter`,
    :func:`_load_frontmatter`). :func:`_block_unparsed` is for :func:`_base_reading_admits`, whose own reading is one frame in too.
    """
    if frontmatter:
        return False
    block, _ = split_frontmatter(raw)
    if block is None:  # no frontmatter block (L18): there is none to refuse
        return False
    try:
        yaml.safe_load(block)  # F1: loaded here, in this frame, not through a helper (see the docstring)
    except yaml.YAMLError:
        return True
    return False
```

**P2-3.** `src/probos/knowledge/records_store.py`, `_base_reading_admits` takes the document's path (the SEARCH occurs once):
SEARCH:
```
def _base_reading_admits(
    block: str, *, scope: str, reader_id: str | None, reader_department: str,
) -> bool:
```
REPLACE:
```
def _base_reading_admits(
    block: str, *, scope: str, reader_id: str | None, reader_department: str, path: str,
) -> bool:
```

**P2-4.** `src/probos/knowledge/records_store.py`, `_base_reading_admits` reads the stand-in where YAML refuses the block (the SEARCH occurs once):
SEARCH:
```
    up to its first ``---`` (:func:`base_split_frontmatter`; U4 pins it).
    """
    try:
        frontmatter = _load_frontmatter(block)
        if not frontmatter:
            frontmatter = _load_frontmatter(block.partition("---")[0]) or frontmatter
    except Exception:  # A5: read_entry raises on this block (a constructor error, a RecursionError)
```
REPLACE:
```
    up to its first ``---`` (:func:`base_split_frontmatter`; U4 pins it). BF-940 slice 4 (L19): where that reading is ``{}`` because
    YAML refuses the block, the rules read the document's stand-in (:func:`_unparsed_gate` of ``path``, the document's path in the
    repository), as ``read_entry`` does.
    """
    try:
        frontmatter = _load_frontmatter(block)
        if not frontmatter:
            frontmatter = _load_frontmatter(block.partition("---")[0]) or frontmatter
            if not frontmatter and _block_unparsed(block):  # BF-940 slice 4 (L19): the same document read_entry withholds
                frontmatter = _unparsed_gate(path)
    except Exception:  # A5: read_entry raises on this block (a constructor error, a RecursionError)
```

**P2-5.** `src/probos/knowledge/records_store.py`, the search's first pass reads the stand-in for a document whose frontmatter did not load (the SEARCH occurs once):
SEARCH:
```
        # Classification scope + reader-identity check (BF-679)
        if not record_is_readable(
            frontmatter,
            scope=scope,
            reader_id=reader_id,
            reader_department=reader_department,
        ):
            continue
```
REPLACE:
```
        # Classification scope + reader-identity check (BF-679). BF-940 slice 4 (L19): a document whose frontmatter did not load is
        # private to the owner of its notebook directory, so a record only the Captain may read is not found for another reader and
        # cannot move the scores that reader is shown (A4). A note only libyaml reads (a tab after a key) has libyaml's reading here, so
        # its owner can be excluded by it where read_entry gives her the note: the second reading withholds more and never gives more (L11).
        if not record_is_readable(
            _unparsed_gate(rel_path) if _frontmatter_unparsed(raw, frontmatter) else frontmatter,
            scope=scope,
            reader_id=reader_id,
            reader_department=reader_department,
        ):
            continue
```

**P2-6.** `src/probos/knowledge/records_store.py`, the search's second reading is told the document's path (the SEARCH occurs once):
SEARCH:
```
        if block is not None and not _base_reading_admits(
            block, scope=scope, reader_id=reader_id, reader_department=reader_department,
        ):
```
REPLACE:
```
        if block is not None and not _base_reading_admits(
            block, scope=scope, reader_id=reader_id, reader_department=reader_department, path=result["path"],
        ):
```

**P2-7.** `src/probos/knowledge/records_store.py`, `write_entry`'s docstring (the SEARCH occurs once):
SEARCH:
```
        Ignored on create, where there is nothing to preserve.
        """
```
REPLACE:
```
        Ignored on create, where there is nothing to preserve.

        BF-940 slice 4 (L19): an update-in-place of a document whose frontmatter did not load (YAML refused it) proceeds as before and
        replaces it, since the store's own writers and ``seed_manuals`` overwrite by design; its ``created`` time and ``revision``
        cannot be carried and restart, so a WARNING names the path (the replaced version stays in git history).
        """
```

**P2-8.** `src/probos/knowledge/records_store.py`, `write_entry` says so (the SEARCH occurs once):
SEARCH:
```
                existing_fm, _ = self._parse_document(existing_raw)
                if "created" in existing_fm:
```
REPLACE:
```
                existing_fm, _ = self._parse_document(existing_raw)
                if _frontmatter_unparsed(existing_raw, existing_fm):  # BF-940 slice 4 (L19): said, not refused (seed_manuals overwrites)
                    logger.warning(
                        "BF-940 slice 4 (L19): %s is rewritten in place and its frontmatter did not load: its created time and revision "
                        "are not carried, and the replaced version stays in git history", path,
                    )
                if "created" in existing_fm:
```

**P2-9.** `src/probos/knowledge/records_store.py`, `read_entry`'s docstring (the SEARCH occurs once):
SEARCH:
```
        Returns {"frontmatter": {...}, "content": "..."} or None if denied.
        """
```
REPLACE:
```
        Returns {"frontmatter": {...}, "content": "..."} or None if denied.

        BF-940 slice 4 (L19): a document whose frontmatter did not load (YAML refused it) reads as ``{}`` and is private to the owner of
        its ``notebooks/<callsign>/`` directory: it is returned to that owner and to the Captain, and denied to every other reader, the
        anonymous ``""`` included. ``RecordsStore.list_entries`` marks its entry (:data:`FRONTMATTER_UNPARSED_KEY`); this mapping is
        unchanged.
        """
```

**P2-10.** `src/probos/knowledge/records_store.py`, `read_entry` gates on the stand-in (the SEARCH occurs once):
SEARCH:
```
        if reader_id != "captain":
            doc_class = frontmatter.get("classification", "ship")
            doc_author = frontmatter.get("author", "")
            doc_dept = frontmatter.get("department", "")
```
REPLACE:
```
        if reader_id != "captain":
            # BF-940 slice 4 (L19): a frontmatter that did not load names no classification, so the document is private to its owner
            gate = (
                _unparsed_gate(file_path.relative_to(self._repo_path.resolve()).as_posix())
                if _frontmatter_unparsed(raw, frontmatter) else frontmatter
            )
            doc_class = gate.get("classification", "ship")
            doc_author = gate.get("author", "")
            doc_dept = gate.get("department", "")
```

**P2-11.** `src/probos/knowledge/records_store.py`, `list_entries`' docstring (the SEARCH occurs once):
SEARCH:
```
        holds and never aborts the listing.
        """
```
REPLACE:
```
        holds and never aborts the listing.

        BF-940 slice 4 (L19): the entry of a document whose frontmatter did not load (YAML refused it) reads ``{}`` as before and carries
        :data:`FRONTMATTER_UNPARSED_KEY` set to ``True``; no other entry has the key. The listing is not reader-scoped, so it lists such
        a document for every caller, as it lists a private one.
        """
```

**P2-12.** `src/probos/knowledge/records_store.py`, `list_entries` asks whether the frontmatter loaded (the SEARCH occurs once):
SEARCH:
```
                raw = md_file.read_text(encoding="utf-8")
                fm, _ = self._parse_document(raw)
            except OSError:
```
REPLACE:
```
                raw = md_file.read_text(encoding="utf-8")
                fm, _ = self._parse_document(raw)
                unparsed = _frontmatter_unparsed(raw, fm)  # BF-940 slice 4 (L19)
            except OSError:
```

**P2-13.** `src/probos/knowledge/records_store.py`, `list_entries` marks the entry (the SEARCH occurs once):
SEARCH:
```
            results.append({"path": rel_path, "frontmatter": fm})
```
REPLACE:
```
            entry: dict[str, Any] = {"path": rel_path, "frontmatter": fm}
            if unparsed:
                entry[FRONTMATTER_UNPARSED_KEY] = True  # BF-940 slice 4 (L19): the one entry that has the key
            results.append(entry)
```

**P2-14.** `src/probos/knowledge/records_store.py`, `publish` refuses (the SEARCH occurs once):
SEARCH:
```
    async def publish(self, path: str, author: str) -> None:
        """Promote a document from draft to published status."""
        file_path = self._safe_path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Record not found: {path}")

        raw = file_path.read_text(encoding="utf-8")
        fm, content = self._parse_document(raw)

        if fm.get("author") != author and author != "captain":
            raise PermissionError("Only the author or Captain can publish")
```
REPLACE:
```
    async def publish(self, path: str, author: str) -> None:
        """Promote a document from draft to published status.

        BF-940 slice 4 (L19): a document whose frontmatter did not load (YAML refused it) is not published. ``publish`` writes back what
        it read, which for such a document is ``{}``, so it would replace the author, the classification and the times with a status
        and the note would read ``ship``. It raises ``ValueError`` naming the path, for the Captain too, and writes nothing.
        """
        file_path = self._safe_path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Record not found: {path}")

        raw = file_path.read_text(encoding="utf-8")
        fm, content = self._parse_document(raw)

        if _frontmatter_unparsed(raw, fm):
            raise ValueError(f"The frontmatter of {path} does not load, so it is not published: fix the file first")

        if fm.get("author") != author and author != "captain":
            raise PermissionError("Only the author or Captain can publish")
```

**P2-15.** `src/probos/knowledge/records_store.py`, `search`'s docstring (the SEARCH occurs once):
SEARCH:
```
        build (``updated: 2026-13-05``), is skipped; one whose frontmatter does not
        parse reads as ``{}``, as every reader reads it, unless the base's earlier
        cut of it parses and it reads as that (A3; BF-940 A1, #1686). A
```
REPLACE:
```
        build (``updated: 2026-13-05``), is skipped; one whose frontmatter does not
        parse reads as ``{}`` (unless the base's earlier cut of it parses and it
        reads as that: A3; BF-940 A1, #1686) and is private to the owner of its
        ``notebooks/<callsign>/`` directory: only that owner, the Captain and a
        reader that named no identity find it (BF-940 slice 4, L19), the owner
        only where the search's own reading admits her: it loads with libyaml, so a
        note only libyaml reads (a tab after a key) has libyaml's reading in the
        first pass, and an owner whom that reading excludes does not find a note
        that ``read_entry`` gives her (L11). A
```

**P2-16.** `src/probos/knowledge/semantic.py`, the key is imported from the store (the SEARCH occurs once):
SEARCH:
```
from probos.knowledge.records_store import (
    _CLASSIFICATION_LEVELS,
```
REPLACE:
```
from probos.knowledge.records_store import (
    FRONTMATTER_UNPARSED_KEY,  # BF-940 slice 4 (L19): owned by the store
    _CLASSIFICATION_LEVELS,
```

**P2-17.** `src/probos/knowledge/semantic.py`, `reindex_records`' docstring (the SEARCH occurs once):
SEARCH:
```
        Bounded by ``limit`` so a large repository cannot stall startup, and
        honest-degrades per entry: one unreadable record does not abort the
        pass.
```
REPLACE:
```
        Bounded by ``limit`` so a large repository cannot stall startup, and
        honest-degrades per entry: one unreadable record does not abort the
        pass.

        BF-940 slice 4 (L19): a record whose frontmatter did not load (its listing entry carries ``FRONTMATTER_UNPARSED_KEY``) is
        left out, so a note that is private on disk is never indexed as ``ship``. It stays pending: the next pass indexes it once its
        frontmatter loads, and the boot logs how many were left out and the first five paths, never a value.
```

**P2-18.** `src/probos/knowledge/semantic.py`, the backfill leaves such a record out (the SEARCH occurs once):
SEARCH:
```
        paths = [e.get("path", "") for e in entries if e.get("path", "")]
        already = self._indexed_record_paths(paths)
```
REPLACE:
```
        # BF-940 slice 4 (L19): a record whose frontmatter did not load reads as {}, so it would be indexed as ``ship`` whatever its text
        # says. It is left out and the boot says so, by path and never by value; the next pass indexes it once its frontmatter loads.
        unparsed = [e["path"] for e in entries if e.get("path", "") and e.get(FRONTMATTER_UNPARSED_KEY)]
        if unparsed:
            logger.warning(
                "BF-940 slice 4 (L19): %d record(s) are not indexed because their frontmatter does not load, so their classification "
                "is unknown; the next pass indexes each once it loads: %s", len(unparsed), ", ".join(unparsed[:5]),
            )
        paths = [e.get("path", "") for e in entries if e.get("path", "") and not e.get(FRONTMATTER_UNPARSED_KEY)]
        already = self._indexed_record_paths(paths)
```

**P2-19.** `tests/test_bf952_records_keyword_search.py`, the one test that pinned this slice's subject: a tab after a key reads as ``{}`` for ``read_entry`` because PyYAML refuses it, which is now a document whose frontmatter did not load (the SEARCH occurs once):
SEARCH:
```
    """A5 (RK8, L28): PyYAML's scanner refuses a tab after a key and libyaml reads it, so ``read_entry`` reads
    alice's private note as ``{}`` (``ship``) for every reader, as on the base, while the search reads it as
    private. The search shows it only where both readings admit the reader: to alice and the Captain, not to bob.
    What ``read_entry`` shows bob is the base's and BF-940's (#1686)."""
    store = await _store(tmp_path)
    path = "notebooks/alice/tabbed-private.md"
    target = store.repo_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("---\nauthor:\talice\nclassification:\tprivate\n---\n\nwarp core notes\n", encoding="utf-8")
    assert (await store.read_entry(path, reader_id="bob"))["frontmatter"] == {}  # the base's reading
    assert await _paths(store, "warp", reader_id="alice") == [path]
    assert await _paths(store, "warp", reader_id="captain") == [path]
    assert await _paths(store, "warp", reader_id="bob") == ([] if _LIBYAML else [path])
```
REPLACE:
```
    """A5 (RK8, L28): PyYAML's scanner refuses a tab after a key and libyaml reads it, so ``read_entry`` reads
    alice's private note as ``{}`` while the search reads it as private. BF-940 slice 4 (L19): a document whose
    frontmatter PyYAML refuses is private to the owner of its notebook directory, so ``read_entry`` withholds it
    from bob and shows it to alice and the Captain, and the search, with or without libyaml, finds it for the
    same two and not for bob: the two readers agree on this note, whose author is the owner of its directory (where
    libyaml's reading names another author the search can miss it for its owner: BF-940 slice 4, L11). (It was the
    base's reading, ``ship`` for every reader, which
    this test pinned and BF-940 owned.)"""
    store = await _store(tmp_path)
    path = "notebooks/alice/tabbed-private.md"
    target = store.repo_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("---\nauthor:\talice\nclassification:\tprivate\n---\n\nwarp core notes\n", encoding="utf-8")
    assert await store.read_entry(path, reader_id="bob") is None
    own = await store.read_entry(path, reader_id="alice")
    assert own is not None and own["frontmatter"] == {}  # PyYAML's reading, which read_entry keeps
    assert await _paths(store, "warp", reader_id="alice") == [path]
    assert await _paths(store, "warp", reader_id="captain") == [path]
    assert await _paths(store, "warp", reader_id="bob") == []
```

**N2-1.** `tests/test_bf940_s4_unparsed_frontmatter.py`, remove the marker of N1-1 (the SEARCH occurs once; the class line stays):
SEARCH:
```
@pytest.mark.xfail(reason="BF-940 slice 4 M2: not built", raises=AssertionError, strict=True)
class TestADocumentWhoseFrontmatterDoesNotLoadIsPrivateToItsOwner:
```
REPLACE:
```
class TestADocumentWhoseFrontmatterDoesNotLoadIsPrivateToItsOwner:
```

### 7.3 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once), as slice 3's own pair uses: slice 3 has merged, so its block sits right after the title, and this block lands first, above it. Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-940 (DATE), #1686 -- a document whose frontmatter does not load is private to the owner of its notebook directory: the readers and the keyword search withhold it from every other reader, the semantic backfill leaves it out and `publish` refuses it (slice 4 of the issue).**
- **Base.** A document whose frontmatter YAML refuses (broken YAML, or a `!!python/` tag an older `write_entry` wrote) read as `{}` for every reader, so at the default `ship` classification: `read_entry` and the keyword search handed it to every reader, the semantic backfill indexed it as `ship` (and Oracle's semantic tier handed it on), and a Captain's `publish` rewrote it with a status and a time only, losing its author, classification and times.
- **Fix.** The access rules read such a document as private to the owner of its `notebooks/<callsign>/` directory (nobody, elsewhere): `read_entry` gives it to that owner and the Captain, and the keyword search to those two and (search) a reader that named no identity; neither gives it to any other reader, and a withheld document does not move another reader's search scores. The search loads with libyaml, so for a note only libyaml reads (a tab after a key) whose libyaml reading names another author it can miss the note for its owner where `read_entry` gives it to her, as it did before (L11). The verdict loads the block in its caller's own frame, so no reader stops at a shallower nesting than its own parse. `list_entries` marks its entry (`frontmatter_unparsed`), the backfill leaves it out and logs its path, and `publish` raises. An update-in-place proceeds as before and logs a WARNING, because `seed_manuals` overwrites shipyard manuals at every boot. A constructor error, a recursion failure and a non-mapping frontmatter are unchanged. Contract `prompts/bf-940-unparsed-frontmatter.md`. Refs #1686: this closes its L19 box, the last open one with slice 3's F7-1; the orchestrator closes the issue when every box is built and merged.

```

**P3-2.** `DECISIONS.md`. The anchor is the heading of the entry that follows slice 2's (once). Slice 3 appends its entry after slice 2's last bullet, above that heading, so this pair needs no re-anchoring and its entry lands after slice 3's whichever merges first. Replace `DATE` with M3's date.
SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### BF-940 -- A document whose frontmatter does not load is private to the owner of its notebook directory (slice 4; DATE, #1686)

- *Scope.* `knowledge/records_store.py` (the stand-in the access rules read, `read_entry`, the keyword search, `list_entries`' marker, `publish`, `write_entry`'s log), `knowledge/semantic.py` (the backfill), one clause of `docs/development/deterministic-ship.md`, tests. Contract `prompts/bf-940-unparsed-frontmatter.md`. Slice 4 of #1686, its L19 box.
- *G0 (who decides).* Decided by the Architect: none of the six conditions under which the Captain decides in Delegated AD Execution Mode is met. Slice 2's G3 had called this a Captain decision because it withholds a document from a reader the base showed it to; that is a loss of access, not a weakened control: every reader set after is a subset of the base's (measured), nothing is migrated or deleted, no key, schema or route body changes, and the documents list the base's reading as a gap (`deterministic-ship.md`, invariant 6: unknown is reported as unknown, never as a default). Ranked overrule option: the policy without the reader gate.
- *G1 (the policy).* A frontmatter YAML refuses is private to the owner of `notebooks/<callsign>/` and to the Captain (a reader that named no identity passes as for any private note); the owner is read from the resolved path. Rejected: the Captain alone (it takes a note from its owner, BF-952's RK10); keeping `{}`; an unknown author of `""` (the anonymous reader equals it); moving the file; recovering the author by a line match.
- *G2 (the writers).* `publish` refuses with `ValueError`, for the Captain too; update-in-place proceeds and logs a WARNING. Rejected: refusing update-in-place, which slice 2's G3 chose: `seed_manuals` overwrites shipyard manuals by design and its failure at boot sets `records_store = None` (`startup/cognitive_services.py`), and the owner could not rewrite her own note (measured).
- *G3 (the seam).* The verdict is derived from the reading a reader already has (`_frontmatter_unparsed(raw, frontmatter)`), so `_parse_document`'s frame depth and shape, which BF-952 A6 pins, do not move, and it loads the block in its caller's own frame, one frame in as `_parse_document` does, so no caller stops at a shallower nesting than its own parse (a helper between them cost one level: round 1, F1). It reaches the backfill as a key on the `list_entries` entry, not on `read_entry`'s mapping, which is the read route's body (AD-1145 DD-7), and the backfill drops the entry before its budget is spent.
- *G4 (the owner's search under libyaml; round 1, F2).* The search loads a block with libyaml where it can, so a note libyaml reads and PyYAML refuses (a tab after a key) has libyaml's reading in the first pass, and the second reading applies the stand-in to the base's reading: the search never shows a reader a note `read_entry` withholds from her, but an owner whom libyaml's reading excludes can miss a note `read_entry` gives her (L11). That miss is the base's (measured: alice found nothing, bob and the Captain found the note), narrowed for bob. Decided by the Architect: none of the six conditions is met. Ranked: keep the first pass, correct the claims and pin the limit (chosen); admit the owner at the first pass by a PyYAML load of each record under `notebooks/<reader>/` that libyaml's reading refuses her (the ranked overrule option: it adds the owner to the search's set for that note, which G0's subset claim says no reader set gains); a PyYAML load of every record in the first pass (undoes BF-952's libyaml); leave the claims (false).
- *Residual.* L1 to L11 of the contract. *Reversal.* Revert the BF-940 slice 4 commits.

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

**P3-3.** `docs/development/deterministic-ship.md` (the clause occurs once, in the Persistence row):
SEARCH:
```
does not parse as one with none (`{}`, so at the default classification), unless the base's earlier cut of it parses and it reads as that (#1686); the store's own writers no longer produce one (a tuple is written as a list and a value no reader loads is refused, BF-940 slice 2). |
```
REPLACE:
```
does not parse as one with none (`{}`), unless the base's earlier cut of it parses and it reads as that (#1686), and treats it as private to the owner of its notebook directory: no reader but that owner and the Captain reads or finds it, the semantic backfill does not index it and `publish` refuses it (BF-940 slice 4); the store's own writers no longer produce one (a tuple is written as a list and a value no reader loads is refused, BF-940 slice 2). A rewrite of one still restarts its created time and revision (it is logged), and an index row written before slice 4 stays until the record is next written. |
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited.

### 7.4 The census (an orchestrator step; no repository file)

I have no live system. Run on a read-only copy of the vessel's `ship-records` (the path from the live process, `%LOCALAPPDATA%\ProbOS\data`, never `d:\ProbOS\data`), with the build tree first on `PYTHONPATH`: `$env:PYTHONPATH = '<build tree>\src'; PY -B -P census_bf940_s4.py <copy>`. It lists documents as the readers do (`RecordsStore.list_entries`, which marks the entry of a document whose frontmatter does not load) and reports, for each marked document, where it stands (`NOTEBOOK`: its owner and the Captain read it; `OTHER`: only the Captain does) and whether a `classification:` line of its text names `private` or `department` (a line scan of the file; the line is never printed), which means the document was shown to every reader as `ship` until this slice. It also counts the markdown files outside `_archived/` that the listing does not list (a constructor error, bytes that are not UTF-8, a link). It prints paths, flag names and counts, **never a value**; the constructor of the store writes nothing and `initialize()` is never called. Exit 0: nothing flagged. 1: flags (read each; a `NAMES_PRIVATE` or `NAMES_DEPARTMENT` document goes back to the Architect and the Captain for repair). 2: the positive control was not flagged as named, or bad arguments, or the tree on `PYTHONPATH` does not mark such a document (a tree without this slice: do not trust the run). The positive control is five documents and two plain texts in a temporary folder walked by the same `census` function: a broken-YAML private note, a tuple department note, a tab-after-key private report and a broken report with no classification line, which must be flagged as named, and a healthy note, an empty frontmatter and a plain text, which must not. Run on synthetic trees here: a clean tree exits 0; a tree holding a legacy tuple note, a hand-made department report, a nameless broken report and a constructor-error report exits 1, flags the first three as named and counts the fourth as not listed; a missing folder exits 2; each tree is left as found (the SHA-256 of every file is equal before and after). The results of a run on a vessel's data are not recorded in this repository. The census reads the records copy only: the rows the semantic index already holds for a flagged path (L3) are counted by a second read-only step on a copy of the vessel's semantic store, and purging them is the Captain's (condition 1 of D0).

```python
"""BF-940 slice 4 census (an orchestrator step; not a repository file). Read-only: it opens the records for reading and never writes (its positive control uses its own temporary folder).

usage:  $env:PYTHONPATH = "<build tree>/src"; python -B -P census_bf940_s4.py <read-only copy of ship-records>
exit 0 nothing flagged; 1 flags (read each); 2 the positive control was not flagged as named, or bad arguments (do not trust the run).
Prints paths, flag names and counts; never a value. The constructor of the store writes nothing and ``initialize()`` is never called.
Flags (one line per document whose frontmatter does not load, as ``RecordsStore.list_entries`` marks it): NOTEBOOK (its owner and the Captain
read it) or OTHER (only the Captain reads it); NAMES_PRIVATE / NAMES_DEPARTMENT (a ``classification:`` line of its text names that level, so it
was shown to every reader as ``ship`` until this slice); NO_CLASSIFICATION_LINE.
"""
from __future__ import annotations

import asyncio
import collections
import pathlib
import re
import sys
import tempfile

from probos.config import RecordsConfig
from probos.knowledge.records_store import RecordsStore

KEY = "frontmatter_unparsed"
NAMED = re.compile(r"^[ \t]*classification[ \t]*:[ \t]*['\"]?(private|department)\b", re.MULTILINE)


async def census(root: pathlib.Path) -> tuple[int, int, list[tuple[str, list[str]]], collections.Counter]:
    store = RecordsStore(RecordsConfig(repo_path=str(root), auto_commit=False))  # the constructor writes nothing; initialize() is never called
    listed = await store.list_entries()
    on_disk = [p for p in root.rglob("*.md") if ".git" not in p.parts and p.relative_to(root).parts[0] != "_archived"]
    rows: list[tuple[str, list[str]]] = []
    stats: collections.Counter = collections.Counter()
    for entry in listed:
        if not entry.get(KEY):
            stats["listed, frontmatter loads or the document has none"] += 1
            continue
        path = entry["path"]
        parts = path.split("/")
        flags = ["NOTEBOOK" if len(parts) >= 3 and parts[0] == "notebooks" else "OTHER"]
        try:
            text = (root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        levels = {m.group(1).upper() for m in NAMED.finditer(text)}
        flags += [f"NAMES_{level}" for level in sorted(levels)] or ["NO_CLASSIFICATION_LINE"]
        stats["listed, frontmatter does not load: " + ("names a private or department level" if levels else "names none")] += 1
        rows.append((path, flags))
    return len(listed), len(on_disk), rows, stats


CONTROL = {
    "notebooks/alice/broken.md": ("author: alice\nclassification: private\nbroken: [unclosed\n", {"NOTEBOOK", "NAMES_PRIVATE"}),
    "notebooks/alice/tagged.md": ("author: alice\nclassification: department\nm: !!python/tuple\n- 1\n", {"NOTEBOOK", "NAMES_DEPARTMENT"}),
    "reports/tabbed.md": ("author:\tbob\nclassification:\tprivate\n", {"OTHER", "NAMES_PRIVATE"}),
    "reports/plain.md": ("author: bob\nclassification: ship\nbroken: [unclosed\n", {"OTHER", "NO_CLASSIFICATION_LINE"}),
    "notebooks/alice/clean.md": ("author: alice\nclassification: private\n", set()),
}
CONTROL_PLAIN = {"notebooks/alice/empty.md": "---\n---\n\nbody\n", "notebooks/alice/nothing.md": "just text\n"}


def control() -> bool:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        for rel, (block, _) in CONTROL.items():
            target = pathlib.Path(tmp) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"---\n{block}---\n\nbody\n", encoding="utf-8")
        for rel, text in CONTROL_PLAIN.items():
            (pathlib.Path(tmp) / rel).write_text(text, encoding="utf-8")
        listed, on_disk, rows, _ = asyncio.run(census(pathlib.Path(tmp)))
    got = {path: set(flags) for path, flags in rows}
    expected = {rel: flags for rel, (_, flags) in CONTROL.items() if flags}
    return listed == on_disk == len(CONTROL) + len(CONTROL_PLAIN) and got == expected


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not pathlib.Path(argv[0]).is_dir():
        print("usage: python census_bf940_s4.py <read-only copy of ship-records>")
        return 2
    if not control():
        print("CONTROL NOT FLAGGED AS NAMED: the comparison cannot be trusted")
        return 2
    print("control: four documents whose frontmatter does not load flagged as named; a healthy one, an empty frontmatter and a plain text not")
    listed, on_disk, rows, stats = asyncio.run(census(pathlib.Path(argv[0])))
    print(f"markdown files outside _archived/: {on_disk}; listed by list_entries: {listed}; not listed (a constructor error, bytes that are not UTF-8, a link): {on_disk - listed}")
    for line in sorted(stats):
        print(f"  {stats[line]:6}  {line}")
    for path, flags in rows:
        print(f"FLAG {path} | {','.join(flags)}")
    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

## 8. What this does NOT change

`_parse_document` (its reading and the frame depth BF-952's A6 pins), `_search_read_document`, `_search_load_frontmatter`, `_load_frontmatter`, `record_is_readable` and `build_records_scope_filter`; `read_entry`'s return mapping and the read route's body (AD-1145 DD-7); `list_entries` for every document whose frontmatter loads, its filters, `strict` mode, containment and walk rules; `check_notebook_similarity` and `check_cross_agent_convergence` (they already skip such a document; layer 2's `update` answer is the call the proceeding writer then makes); update-in-place's result and `seed_manuals` (a WARNING is added); `dump_frontmatter` and the skill catalog's three parsers (they already leave an unparsable block alone); a constructor error, a recursion failure and a non-mapping frontmatter (slice 2's L13 and L11: they already raise or withhold); a document with no frontmatter, an empty one, a falsy one or an unclosed opener (L18); `routers/records.py` (slice 3's file) and every other router, the HXI, config, dependencies, the semantic index's metadata and the rows it holds, and every document on disk.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

Rows 1 to 22, 26 and 27 are in `src/probos/knowledge/records_store.py`, rows 23 to 25 in `src/probos/knowledge/semantic.py` (rows 1 and 5 are re-anchored by slice 4's A1, because the verdict now loads the block itself; row 2 now mutates `_block_unparsed`'s own line; rows 26 and 27 are new). Case ids are section 6's; `(n)` is the number of parametrized cases of that function that fail.

| # | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|
| 1 | `yaml.safe_load(block)  # F1: loaded here, in this frame, not through a helper (see the docstring)` | `pass` | T1 (4), T3, T4 (3), T5, T6 (3), T7, T8, T9 (4), T10, T11, T12, T13: 22 of 26; T2 stands because the search's second reading withholds the document on its own |
| 2 | `yaml.safe_load(block)` | `pass` | T11, T13: `_block_unparsed`, now called only by the second reading, no longer withholds a note libyaml reads |
| 3 | `if frontmatter:` | `if False:` | S3 (2), T13: a block the base's cut reads is marked, and with a truthy libyaml reading judged too the first pass applies the stand-in and the owner finds the note |
| 4 | `block, _ = split_frontmatter(raw)` | `block = raw` | S2 (4): a text with no frontmatter is read as one |
| 5 | `if block is None:  # no frontmatter block (L18): there is none to refuse` | `if False:` | S2 (2): `safe_load(None)` raises for a text with no frontmatter |
| 6 | `owner = parts[1] if len(parts) >= 3 and parts[0] == "notebooks" else None` | `len(parts) >= 3` to `len(parts) >= 2` | T9 (1): a file straight under `notebooks/` has an owner |
| 7 | the same line | `parts[0] == "notebooks"` to `True` | T9 (1): a callsign under `reports/` is an owner |
| 8 | the same line | `parts[1]` to `parts[-1]` | T1 (2), T2 (2), T8, T10, T11, T13, S9: the owner is the file name |
| 9 | `return {"classification": "private", "author": owner}` | `"private"` to `"ship"` | T1 (4), T2 (4), T3, T8, T9 (4), T10, T11, T13: 17 |
| 10 | the same line | `"author": owner` to `"author": owner or ""` | T1 (2), T2 (2): the anonymous reader reads |
| 11 | `if _frontmatter_unparsed(raw, frontmatter) else frontmatter` | `if False else frontmatter` | T1 (4), T8, T9 (4), T10, T11, T13: 12 |
| 12 | `_unparsed_gate(file_path.relative_to(self._repo_path.resolve()).as_posix())` | `_unparsed_gate(path)` | T10: the owner is taken from the spelling |
| 13 | `_unparsed_gate(rel_path) if _frontmatter_unparsed(raw, frontmatter) else frontmatter,` | `frontmatter,` | T3: the first pass is what keeps a withheld document out of another reader's scores |
| 14 | `frontmatter = _unparsed_gate(path)` | `pass` | T11, T13: the second reading admits what `read_entry` withholds |
| 15 | `block, scope=scope, reader_id=reader_id, reader_department=reader_department, path=result["path"],` | `path=""` | T2 (2), T8, T11, T13, S9 and BF-952's RK8 test: the owner is lost in the second reading |
| 16 | `if not frontmatter and _block_unparsed(block):  # BF-940 slice 4 (L19): the same document read_entry withholds` | `if _block_unparsed(block):  # mutant` | S3 (1): a `ship` block the base's cut reads is withheld |
| 17 | `if _frontmatter_unparsed(raw, fm):` | `if _frontmatter_unparsed(raw, fm) and author != "captain":` | T6 (1): the Captain's `publish` still rewrites it |
| 18 | `raise ValueError(f"The frontmatter of {path} does not load, so it is not published: fix the file first")` | `pass` | T6 (3) |
| 19 | `if _frontmatter_unparsed(existing_raw, existing_fm):  # BF-940 slice 4 (L19): said, not refused (seed_manuals overwrites)` | `if False:` | T7 |
| 20 | `unparsed = _frontmatter_unparsed(raw, fm)  # BF-940 slice 4 (L19)` | `unparsed = False` | T4 (3), T5, T8 |
| 21 | `entry[FRONTMATTER_UNPARSED_KEY] = True  # BF-940 slice 4 (L19): the one entry that has the key` | `= False` | T4 (3), T5, T8 |
| 22 | `FRONTMATTER_UNPARSED_KEY = "frontmatter_unparsed"` | `"frontmatter_unparsed_x"` | T4 (3): the key's name is the contract |
| 23 | `paths = [e.get("path", "") for e in entries if e.get("path", "") and not e.get(FRONTMATTER_UNPARSED_KEY)]` | drop `and not e.get(FRONTMATTER_UNPARSED_KEY)` | T5, T8 |
| 24 | `"is unknown; the next pass indexes each once it loads: %s", len(unparsed), ", ".join(unparsed[:5]),` | `unparsed[:5]` to `unparsed[:50]` | T5 (seven documents, five paths named) |
| 25 | `if unparsed:` (in `semantic.py`) | `if False:` | T5 (no WARNING) |
| 26 | `yaml.safe_load(block)  # F1: loaded here, in this frame, not through a helper (see the docstring)` | `return _block_unparsed(block)` | S10 (4), T12: the verdict loads one frame deeper than the reading it judges (the candidate as built) |
| 27 | the same line | `(lambda: yaml.safe_load(block))()` | S10 (4), T12: any frame between the caller and the load, helper or not |

**Campaign of record** (my hand driver, in memory, one mutant at a time over the exact files below; not the orchestrator's tool run, and the orchestrator's campaign of record, if it runs one, replaces it): baseline 46 cases pass (slice 4's A1 reran the table over the amended files below; the pre-A1 table ran 40 cases and 25 rows); each mutant fails exactly the cases its row lists (failing counts 22, 2, 3, 4, 2, 1, 1, 9, 17, 4, 12, 1, 1, 2, 7, 1, 1, 3, 1, 5, 5, 3, 2, 1, 1, 5, 5 for rows 1 to 27; every row also ran BF-952's RK8 test, which rows 1, 8, 9, 11 and 15 fail too, and only row 15's count includes it, as before), none outside them; no mutant survived. Files (sha256 of the LF text): `records_store.py` at M2's head (the 15 pairs applied to the base blob, then A1-1 to A1-3) `1280806f76d52d88fc93fd2980da5db7750baa6ff7a5977219060b7ce354124c`; `semantic.py` at M2's head `2a894380a0b57ec0dd00b071fd76f0349d63b0397585c6d553943dc51231ef3e`; `tests/test_bf940_s4_unparsed_frontmatter.py` as N1-1 gives it (A1-26 to A1-29 applied) `fd2049fb49527856bf960bf8f9e9e0945d1e2c5c4904fa7b93aef4c2e76d33f4` and at M2's head, N2-1 applied, `5c8730f84762aa22f153242effba2fde6a53b44eccdcb52d5e88851095f8a8fb` (my driver ignores the marker, so the campaign ran with it present: the cases are the same); `tests/test_bf952_records_keyword_search.py` at M2's head, P2-19 applied, `dabcf50f19a5f98ea1928256be61414f842c07dee0ca1c1758c817f9d465d6cf`. A Builder whose files match does not repeat the campaign; if `records_store.py` or `semantic.py` differs, rerun every row; if a test file differs, rerun the rows whose function changed. Not tabulated, for the cap: `.as_posix()` to `str(...)` in row 12's line (an equivalent mutant on POSIX, killed on Windows by every owner case: the path would hold backslashes), `parts[0] == "notebooks"` to `!=` (killed by the same cases as rows 7 and 8), and the texts of the log lines and docstrings beyond what T5 and T7 assert (the path, the count of seven, no value).

## 10. Recorded limits

- **L1.** Nothing here is a live-system claim: I have no vessel and read no real `ship-records`. 7.4 is the census to run; its results are not recorded in this repository, and a document written after a run is not covered by it.
- **L2.** Every measurement is on Python 3.12.13 and PyYAML 6.0.3 with libyaml (only T11, T13 and mutants 2 and 14 depend on libyaml being installed: without it the first pass reads the tab-after-key note as PyYAML does, so T11 and T13 still pass (T13's loop then runs the fallback loader twice) and mutants 2 and 14 survive (slice 4's A1 ran the table with the fallback loader forced: the survivors are rows 2 and 14 only, and row 3 keeps S3's two kills without T13's); whether CI's PyYAML build has libyaml was not checked). Every count of mine is from my hand driver, a stand-in for the pytest features the files use: it reads no `conftest.py`, patches `RecordsStore.initialize` to skip git, and ignores xfail marks. **Not run:** pytest, xfail semantics, `-n 16`, G1 to G3, the broad gate, the architecture check, the ledger generator, a timing run, a Windows junction run, the census on a real tree.
- **L3.** Rows the semantic index already holds for such a document (written as `ship` by an earlier backfill) stay: the backfill skips a held path and index-on-write upserts only when the record is next written. Purging them is a production-data operation (D0, condition 1) and is the Captain's; the census's second step counts them.
- **L4.** A document outside `notebooks/<callsign>/` (a report, a manual, a Captain's log, an `_archived/` document) whose frontmatter does not load is read by the Captain only: its author cannot read it, because nothing in its text can be trusted to name one. This is narrower than the base, and the remedy is the Captain's repair of the file.
- **L5.** An update-in-place of such a document restarts its `created` and `revision` (as the base did); the WARNING names the path. The replaced text is in git only while `auto_commit` is on (it defaults to True).
- **L6.** A `department` or `fleet` document whose frontmatter does not load becomes private to its owner: department colleagues lose it until the file is repaired.
- **L7.** The search's first pass has only libyaml's reading, so a note libyaml reads and PyYAML refuses (RK8) still counts toward a term's rarity for the readers libyaml's reading admits, as before; its second reading withholds it from every reader `read_entry` withholds it from (T11), so the search never shows a reader a note `read_entry` refuses her. The converse is L11.
- **L8.** A reader that named no identity (`reader_id=None`) finds such a document, as it finds any private note. No production caller passes `None`: `tests/test_bf949_notebook_reader_identity.py:368` asserts that every `.search(` caller in `src` passes a reader.
- **L9.** Slice 2's L11 (a non-mapping frontmatter aborts a filtered listing) and L13 (a constructor error or a recursion failure) are not touched: they already withhold from every reader, the Captain included.
- **L10.** The owner is the exact string of the directory name (`notebooks/Alice/` is not `alice`'s), as `read_entry` compares `author`. The new key reaches the HTTP listing bodies, for such a document only (an additive key: the HXI reads named keys and its browse validator reads `count` and `documents`, `useStore.ts:116-118`, read, not run).
- **L11.** (Slice 4's A1, round 1, F2.) The search's first pass has libyaml's reading of a note libyaml reads and PyYAML refuses (a tab after a key), and the second reading cannot add a reader the first pass excluded. Where libyaml's reading names another author, or a classification that excludes the owner of the notebook directory (`author: bob`, `classification: private` in alice's notebook), `read_entry` gives the owner the note and her search does not find it under libyaml; under the `SafeLoader` fallback she finds it. This is the base's own miss (base, libyaml: alice `[]`, bob and the Captain found the note), narrowed for bob, recorded and not fixed (D5, option 2 is the overrule). T13 pins it as a limit and not a promise: a change that lets her find it changes T13's first loop assertion on purpose.

## 11. Verified Against Codebase (2026-11-11, reading tree `D:\ProbOS-worktrees\bf940s3-base` at `708fa60c`)

Hand-driver results (Python 3.12.13, PyYAML 6.0.3 with libyaml, pytest 9.0.2 imported for its marks only; a throwaway store per case under the OS temp folder, `~` moved, no `initialize()`, no git child):

- **M-1 (the matrix).** Premises asserted: PyYAML alone raises `YAMLError` for the YAML-error note and the tuple note and `ValueError` for `updated: 2026-13-05`; a healthy private note is refused to bob and read by alice and the Captain; a healthy note with the same words suppresses and converges (the scans' positive control). Callers: `read_entry` (alice, bob, captain, `""`, `system`), the keyword search (alice, bob, captain, `None`, `""`), `list_entries` (plain, `author=`, `classification=`), `check_notebook_similarity` (exact topic, across topics), `check_cross_agent_convergence`, `write_notebook` over the note, `publish` (alice, captain, bob), `reindex_records` (a stand-in collection), `seed_manuals`; documents: a YAML error, a tuple, a constructor error, a healthy note, an empty frontmatter, a plain text, an unclosed opener, each at a notebook path and at a report path. Base: Problem 1's table. M2's head gives, for the YAML-error and tuple notes: `read_entry` alice (notebook path only) and the Captain, `None` for bob, `""` and `system`; the search alice (notebook path only), the Captain and `None`; the listing entry marked; the backfill indexes nothing for them; `publish` raises for all three; update-in-place and `seed_manuals` as the base; every other document and the constructor error as the base.
- **M-2 (the candidates the reframing check asked for; emulations by subclass over the same matrix).** (a) writers only, `publish` and update-in-place refuse: the Captain's rewrite is refused; every read, the search and the backfill are as the base. (b) (a) plus the backfill leaving the document out: the backfill's rows are empty; `read_entry` and the search still hand the note to every reader. (c) slice 2's D3 option 1 (readers gated, both writers refusing). The chosen policy is (c) with update-in-place proceeding; its matrix equals M2's head on every cell except the count the emulation returned for the backfill (it counted the skipped document).
- **M-3 (update-in-place refused).** Under (a), (b) and (c): `write_notebook("alice", ...)` over the note raises `ValueError`; `seed_manuals` over a hand-broken manual (a YAML error or a tuple) raises `ValueError` where the base overwrote it. Startup catches that as "Ship's Records failed to start" and sets `records_store = None` (`startup/cognitive_services.py:599-619`, read).
- **M-4 (the pinned test).** The unedited `tests/test_bf952_records_keyword_search.py` on M2's head: 75 of 76 pass; `test_a_record_only_libyaml_reads_is_found_only_where_both_readings_admit_it` fails with `TypeError: 'NoneType' object is not subscriptable` at `:750` (`read_entry` answers `None` to bob). With P2-19 applied: 76 of 76.
- **M-5 (existing tests).** The 94 files `git grep -l -E 'RecordsStore|records_store|_records_store|\.read_entry\(|\.list_entries\(|reindex_records|check_notebook_similarity|check_cross_agent_convergence|write_notebook|seed_manuals' -- 'tests/test_*.py'` finds on the reading tree, driven on a copy of it and on M2's head (the BF-952 file with P2-19): 3,392 cases on each, 3,164 passed, 227 failed and 1 skipped on each, and **the per-file results are equal**, with no timeout. The 227 are the driver's limits and are the same on both trees (no `conftest.py`, git not initialised, fixtures that are not plain fixture functions); `test_ad722d_records_auto_write.py` does not import on either (a UI manifest outside the copy). The files G2 names that deal most with records were also driven alone, equal on both trees: `test_bf952_records_keyword_search.py` 76, `test_bf940_frontmatter_framing.py` 40, `test_bf940_s2_dump_frontmatter.py` 21, `test_bf940_s2_writer_policy.py` 55, `test_records_store.py` 27 passed and 4 failed (its git asserts), `test_bf679_oracle_records_reader_identity.py` 88, `test_bf949_notebook_reader_identity.py` 27, `test_ad550_notebook_dedup.py` 26, `test_ad1138_records_semantic_index.py` 55 and `test_bf684_records_index_coverage.py` 15 (these two with a real ChromaDB collection).
- **M-6 (the census).** The positive control, a clean tree, a mixed tree and a missing folder, as 7.4 states; the script's SHA-256 (LF text) is `37ebd91ab02494a62e7687c7551833c8c6d477c15bf7841ed145ccf5221a1a5d`.
- **M-7 (the search's two readings).** Mutant 1 leaves T2 standing, so the second reading alone withholds a document from bob; mutant 13 (no first-pass gate) fails only T3, the case on scores. A note whose block only libyaml reads (a tab after a key) and whose classification is `ship` is found by bob in the first pass and withheld by the second (T11 and T13, mutant 14).
- **M-8 (slice 4's A1, F1: the nesting at which a reader stops).** Hand driver, Python 3.12.13, recursion limit 1000, documents of the tests' shape (a block sequence nested N deep, then `broken: [unclosed`); the figure is the deepest N that reads. From one frame, with 0, 1, 2 and 3 more frames beneath the call: `_parse_document` 484, 484, 483, 483; the candidate as built (the verdict through `_block_unparsed`) 484, 483, 483, 482; the inline verdict 484, 484, 483, 483. Through the real readers (a coroutine each), `read_entry`, `list_entries`, `publish` and update-in-place all stop at 483, 482, 482, 481 as built against 483, 483, 482, 482 with the verdict neutralised, and at 483, 483, 482, 482 amended: one level sooner at every second stack depth, for all four from one stack (the parity is the caller's stack, not the method's: the orchestrator's probe called update-in-place from a stack one frame shallower than the other three, which is why it showed no shift there, so S10 scans both parities and no case names a depth). The keyword search stops at 487 as built, amended and with the verdict neutralised. The Captain's `read_entry` (it never reaches the verdict), the owner's with the verdict neutralised and the owner's with the amended verdict stop at the same nesting at each of four stack depths (484, 483, 483, 482 in the harness that measured it), so S10's neutralised reference is the Captain's quantity for `read_entry` and is available for the callers that have no Captain variant. The candidate as built passes S10 with its inner loop on one parity at half the outer depths (inner pad 0: passes at outer pads 0 and 2, fails at 1 and 3; inner pad 1: the opposite) and fails with both parities at every outer pad from 0 to 3; the amended files pass at every outer pad. The orchestrator's probe (`probe_f1_f2_s4.py`, flow style), run against the amended module, reads alice, the Captain, `list_entries` and `publish` to the same N, as the base does.
- **M-9 (slice 4's A1, F2: the owner's search under libyaml).** `author:` TAB `bob`, `classification:` TAB `private` at `notebooks/alice/note.md`: `read_entry` reads alice and the Captain, `None` for bob; the search with libyaml finds it for the Captain only (alice `[]`, bob `[]`); with the `SafeLoader` fallback for alice and the Captain (bob `[]`); on the base with libyaml alice `[]`, bob and the Captain found it. T13 on the three trees: the base fails at its first assertion (`read_entry` shows bob the note), the candidate as built and the amended files pass.

Grep evidence (reading tree; line numbers are the slice-2 state):

```
knowledge/records_store.py: _UNRESTRICTED_READER :104; record_is_readable :107; _load_frontmatter :265 (YAMLError caught :274); _nests_below :278; _search_load_frontmatter :298; _search_read_document :315;
  _base_reading_admits :336 (one caller, :489); _search_records :393 (_search_read_document :429; first-pass gate :443-451; final loop :489-493); write_entry :664 (update-in-place :744-764; the debug log :764);
  seed_manuals :852; write_notebook :918; check_notebook_similarity :1048 (exact topic :1086, across topics :1151); check_cross_agent_convergence :1201 (scan :1247, evaluation :1325);
  read_entry :1418 (_parse_document :1433; the gate :1436-1443); list_entries :1449 (parse :1502; append :1522); publish :1555; search :1577; _parse_document :1742 (YAMLError caught :1755; fallback :1757-1763)
knowledge/semantic.py: records_store import :20-24; index_record :364; reindex_records :666 (list_entries :708; paths :717; read_entry :738; index_record call :743)
startup/cognitive_services.py: records_store = None :599; if config.records.enabled :600; seed_manuals :613; except Exception ... records_store = None :617-619
routers/records.py: read_record :58 (docstring AD-1145 DD-7 :68-70; read_entry :88; 404 :97; return entry :102); search reads as the Captain :187
ui/src/store/useStore.ts: ?reader=captain :2046, :2213; search :2075; browse validator :116-118
cognitive/skill_catalog.py: parse_skill_file YAMLError -> None :113-116; get_skill_body :170-182; _rewrite_frontmatter YAMLError -> return :782-792
cognitive/dreaming.py: read_entry as "system" :951, :1067; cognitive/diagnostic_context.py: synthetic reader :414; knowledge/archive_promotion.py: ARCHIVE_READER = "" :68
proactive.py: write_notebook :3366, :4430 (failure caught and logged :3508, :4449); check_notebook_similarity :3245, :4403
config_models/knowledge.py: RecordsConfig :317, auto_commit :322 (True); pyproject.toml: pyyaml>=6.0 :26
tests: test_bf952_records_keyword_search.py :307, :508, :740-754, :786, :796; test_bf949_notebook_reader_identity.py :368; test_bf940_frontmatter_framing.py :109 (_search_read_document[:2])
docs/development/deterministic-ship.md: the clause :49, invariant 6 :54; DECISIONS.md: RK10 :1360, slice 2's last bullet :1620, the heading P3-2 anchors :1622; PROGRESS.md: title :1, slice 2's header :3
```

Callers, enumerated (2026-11-11; each command run on the reading tree):

```
git grep -n -E '\.read_entry\(' -- src
  14 call sites: knowledge/semantic.py:738 (the backfill, as the Captain); knowledge/backlinks.py:273 (the Captain); knowledge/archive_promotion.py:315, :372 (reader "");
  cognitive/diagnostic_context.py:414 (a synthetic reader); cognitive/dreaming.py:951, :1067 (reader "system"); recreation/history.py:198 (the agent); proactive.py:2840, :2922
  (the agent) and :3957 ("system"); experience/commands/commands_gap.py:60 and routers/gaps.py:30 ("system"); routers/records.py:88 (the route: ?reader=, default captain).
  Every non-Captain site tests the result (if doc, if entry, is None, if not doc): read. archive_promotion reads only a document whose listed frontmatter names an author and a status
  (source_kind_for), which a document whose frontmatter did not load never does.
git grep -n -E '\.list_entries\(' -- src
  29 sites, 18 of them RecordsStore's: __main__.py:3575; knowledge/semantic.py:708; notebook_quality.py:217; backlinks.py:263; knowledge_linter.py:58; archive_promotion.py:310, :368;
  cognitive/diagnostic_context.py:375; cognitive/dreaming.py:932; routers/records.py:50, :123, :134, :228; stand_down.py:281; recreation/history.py:184; proactive.py:2791; routers/gaps.py:23;
  experience/commands/commands_gap.py:51 (the other 11 are the skill catalog's own list_entries). A listing is not reader-scoped; the one change in it is the key on the entry of such a document.
git grep -n -E '_parse_document\(' -- src
  records_store.py:749 (update-in-place), :1092 (similarity, exact topic), :1165 and :1183 (similarity, across topics), :1273 and :1294 (convergence), :1433 (read_entry),
  :1502 (list_entries), :1562 (publish); the definition :1742. Tests: direct calls, and the recorder at test_bf952_records_keyword_search.py:796.
git grep -n -E 'reindex_records\(' -- src
  runtime.py:3929 (the boot backfill); knowledge/semantic.py:666 (the definition).
git grep -n -E '\.write_entry\(|\.write_notebook\(|\.seed_manuals\(' -- src
  write_notebook: proactive.py:3366, :4430; tools/publish_finding_tool.py:693; routers/records.py:151. write_entry (16 sites): after_action.py:372; avatars/records_writer.py:168;
  avatars/peer_perception.py:350; creative/output_writer.py:105; recreation/service.py:377; routers/gaps.py:186; commands_gap.py:244; stand_down.py:328; proactive.py:3977;
  cognitive/dreaming.py:1012, :1145, :1372; cognitive/procedure_store.py:719, :1729; records_store.py:867 (seed_manuals) and :959 (write_notebook). seed_manuals: startup/cognitive_services.py:613.
git grep -n -E 'check_notebook_similarity\(|check_cross_agent_convergence\(' -- src
  proactive.py:3245, :4403 (similarity) and :3396 (convergence); tools/publish_finding_tool.py:765 (similarity).
```

## Absence Verified (2026-11-11)

```
1. CLAIM: nothing in the repository's production code calls RecordsStore.publish.
   RUN:   git grep -n -E '\.publish\(' -- 'src/*.py'   (7 of its sites are the NATS bus, mesh/nats_bus.py);   git grep -n -E 'records?[_a-z]*\.publish\(|RecordsStore.*publish|\.publish\(path' -- src scripts ui/src
   FOUND: src/probos/__main__.py:3612 prepared.publish() (a snapshot); execution/workspace_result_store.py:1093 self._artifacts.publish(...) (the artifact store); federation/envelope.py:386 self.publish() (a callable); the second command finds nothing. Callers of RecordsStore.publish: five test files (test_bf940_frontmatter_framing.py, test_bf940_s2_writer_policy.py, test_bf952_records_keyword_search.py, test_path_traversal.py, test_records_store.py).
   HOLDS: yes for src, scripts and ui/src; a client outside the repository cannot be enumerated.

2. CLAIM: no document, config or UI file promises that a document with an unparsable frontmatter is readable or reads empty.
   RUN:   git grep -n -i -E '(does not|doesn.t|cannot|fails? to|failed to|will not|never) (parse|load)[^|]{0,60}front ?matter|front ?matter[^|]{0,60}(does not|doesn.t|cannot|fails? to|failed to) (parse|load|read)|(unparsable|unparseable|malformed|invalid) (yaml )?front ?matter' -- docs README.md config ui/src
   FOUND: docs/development/deterministic-ship.md:49 only: it lists the reading as a gap (with #1686), in the column of what is not yet guaranteed.
   HOLDS: for the phrasings the pattern matches; the HXI reads with ?reader=captain (useStore.ts:2046, :2213) and the search route as the Captain (records.py:187).

3. CLAIM: no existing test other than the RK8 test asserts that such a document is read, found, listed, indexed or published as before.
   RUN:   the 94 test files that touch the store, driven on the base and on M2's head (M-5); the unedited BF-952 file on M2's head (M-4)
   FOUND: per-file results equal with P2-19 applied; without it exactly one case differs (test_bf952_records_keyword_search.py:750).
   HOLDS: for those 94 files and the driver's limits (L2); the other 227 failures are the same on both trees.

4. CLAIM: no reader of Ship's Records frontmatter loads YAML outside _parse_document and the search's reader.
   RUN:   git grep -n -E 'yaml\.(safe_load|load)\(' -- 'src/probos/knowledge/*.py' 'src/probos/routers/records.py' 'src/probos/cognitive/skill_catalog.py' 'src/probos/utils/frontmatter.py'
   FOUND: skill_catalog.py:113, :790; records_store.py:273 (_load_frontmatter), :309 (the search's libyaml load), :1754 and :1760 (_parse_document); utils/frontmatter.py:61 (dump_frontmatter's read-back).
   HOLDS: yes.

5. CLAIM: _base_reading_admits and _search_read_document have one production caller each, and no test calls either but through the search or by slicing its result.
   RUN:   git grep -n -E '_base_reading_admits|_search_read_document' -- src tests
   FOUND: src: the definitions :315, :336 and the calls :429, :489 (both in _search_records); tests: [:2] slices (test_bf940_frontmatter_framing.py:109, test_bf952_records_keyword_search.py:317, :541) and wrappers that pass every argument through (:341, :344).
   HOLDS: yes: P2-3's new keyword reaches the one caller, and the wrapper forwards *args and **kwargs.

6. CLAIM: no call this slice adds puts a Python frame between a caller and a recursive PyYAML load that the reading it judges does not also have, and the one caller outside a try (the search's first pass) has two frames to spare. (Slice 4's A1, F1; line numbers are the candidate's before A1.)
   RUN:   git diff -U0 ad67e493 172120fb -- src | rg '^\+' | rg 'yaml|safe_load|\.load\(' ;  rg -n '_frontmatter_unparsed\(|_block_unparsed\(' src ;  rg -n 'yaml\.(safe_load|load|full_load|unsafe_load|compose|parse|scan)\(' src/probos/knowledge   (the last on the base and on the candidate)
   FOUND: the diff adds one recursive load, `yaml.safe_load(block)` in `_block_unparsed` (:306); A1 puts the same call in `_frontmatter_unparsed` and leaves `_block_unparsed` to its one caller. The verdict is called from `_search_records` (:500, the first pass, outside the try that wraps `_search_read_document`), `write_entry` (:809, inside `try/except Exception`), `read_entry` (:1509, no try), `list_entries` (:1581, inside `try/except Exception`) and `publish` (:1651, no try); `_block_unparsed` from `_frontmatter_unparsed` (:324) and `_base_reading_admits` (:402, inside `try/except Exception` returning False). `semantic.py` loads no YAML. The base's loads in `knowledge/`: `_load_frontmatter` (:273, `safe_load`), `_nests_below` (:286, `yaml.parse`, which does not recurse), `_search_load_frontmatter` (:309, `yaml.load` with libyaml), `_parse_document` (:1754, :1760); the candidate adds only :306.
   HOLDS: yes. From the frame that called `_parse_document` the amended verdict and the parse are one call deep (S10, T12); `_base_reading_admits`' two loads are one call deep; the search's reading loads from four frames in (`_search_records`, `_search_read_document`, `_search_load_frontmatter`, `_load_frontmatter`) and the verdict from two (the search stops at the same nesting with and without it: M-8). A client outside the repository cannot be enumerated.
```

## 12. Prior Art and Blind Spots

- **Internal: adopted.** Slice 2's D3 (the policy: readers withhold from all but the Captain and the path's owner; `publish` refuses) and its reasoning against the anonymous reader; BF-952's A4 (rarity over what this reader may read), A5 (the second reading), A6 (the frame depth that makes the verdict a derived predicate, not a new return of `_parse_document`) and RK10 (why the owner is admitted); BF-679's tri-state reader (why the stand-in's author is `None`, not `""`); the records ontology's `private` default for a notebook (`config/ontology/records.yaml:68`); AD-1140's fail-fast tier (`publish`'s `ValueError`); the skill catalog's own policy for an unparsable block (`:113-116`, `:782-792`: leave it alone); `deterministic-ship.md` invariant 6. **Rejected:** a typed result from `_parse_document` (D3, option 4); a key on `read_entry`'s mapping (the route body); refusing update-in-place (D2: the boot hazard); the Captain alone (RK10); recovering the author or `created` by a line match; a read-side loader for the tag (slice 2's G1).
- **Blind spots handled.** A document that loads judged unparsed (S2, S3: no frontmatter, an empty block, `[]`, a comment-only block, an opener never closed, a block the base's cut reads); the owner refused her own note (S9; T9's nesting and prefix cases); the owner read from the spelling (T10); the anonymous reader (T1, T2); a withheld document counted in another reader's scores (T3); the search's two readings disagreeing (T11; the owner's miss, which stays: L11, T13); the verdict reading one level less deep than the reading it judges, for any caller and any stack depth (S10, T12); the backfill spending budget on a document or indexing it as `ship` (T5, T8); a repaired document indexed late (T8: indexed on the next pass at its own classification); the Captain's `publish` destroying a document (T6); the boot path (S6); a new key on a body clients receive (S8, T4, L10); `_parse_document` moving (S7, and BF-952's A6 pins in G2).
- **What discards a correct result.** A document that loads and is read as private: `_frontmatter_unparsed` answers False for any reading that holds something and for a text with no frontmatter block (S2, S3; mutants 3 to 5). The owner refused: the stand-in's author is the directory's callsign at any depth (S9, mutants 6 to 8). A document indexed late: a marked entry leaves `pending` before the budget is sliced, so it spends no slot, and the pass after its frontmatter loads indexes it (T8, mutant 23). A reader refused a document the base's reading admits: the second reading applies the stand-in only where the base's cut reads nothing (S3, mutant 16). A document the reading read and the verdict raised on: the verdict loads the block in its caller's own frame (S10, T12, mutants 26 and 27; update-in-place swallows such a failure, so its case watches the `revision`).

## 13. Diff Reviewer: properties to verify

1. `_frontmatter_unparsed(raw, frontmatter)` is False for a reading that holds something and for a text with no frontmatter block, and True only where the reading is empty, a block exists and `yaml.safe_load` of it raises `YAMLError`. `_parse_document`, `_search_read_document`, `_search_load_frontmatter` and `_load_frontmatter` are byte-identical, and `read_entry` still calls `self._parse_document(raw)` once, from the same frame (BF-952 A6, `:786`, `:796`). `_frontmatter_unparsed` calls `yaml.safe_load` itself, not through `_block_unparsed` or any helper: from the frame that called `_parse_document` it stops at the nesting the parse does, for each caller, at both parities of the stack (S10, T12; rows 26 and 27).
2. `_unparsed_gate` returns a private stand-in whose author is `parts[1]` under `notebooks/<callsign>/...` (three or more path parts) and `None` elsewhere; `read_entry` takes the path from `file_path.relative_to(self._repo_path.resolve())`, never from `path`; the Captain never reaches the gate; `""` never equals the author.
3. The search reads the same stand-in in its first pass (so rarity counts only what the reader may read) and in `_base_reading_admits` (so the search never shows a reader a note libyaml reads and PyYAML refuses that `read_entry` withholds from her; the converse, an owner whom libyaml's reading excludes, is L11 and T13); `_base_reading_admits` has one caller and receives the document's path.
4. `list_entries` adds `frontmatter_unparsed: True` to the entry of such a document and changes nothing else in an entry, a filter, `strict` mode or a skip rule; `read_entry`'s mapping and the read route's body are unchanged.
5. `reindex_records` drops marked entries before `pending[:limit]` is sliced and logs one WARNING per pass with the count and at most five paths and no value; every other entry is indexed as before; a fake store without the key behaves as before.
6. `publish` raises `ValueError` before the author check and writes nothing; update-in-place proceeds and logs one WARNING naming the path and no value; `seed_manuals` is unchanged.
7. No log line holds a frontmatter or body value; every line added is ASCII; no dependency is added; no private name crosses a module (the key is public); the three tiers of exception handling hold (`publish`: propagate; the rest: log-and-degrade or unchanged).
8. The new file's 20 guards pass on the reading tree and its 26 class cases fail there at an `assert` of their own body (T12 at its first line, which asks whether the module has the verdict); the edited BF-952 test keeps its premise lines and says in its docstring what it pinned and why it moved.

## 14. Acceptance criteria

1. M1 is committed first: G1 gives 20 passed and 26 xfailed, and with `--runxfail` each failure stops at the `assert` section 6 names.
2. M2 applies P2-1 to P2-19 and N2-1 verbatim (one `edit` call per pair; each SEARCH occurs once); G2: the new file 46 passed, every other file 0 failed with collected counts equal to M0, the architecture check clean with its four counts equal to M0's.
3. M3 applies P3-1 to P3-3 and runs the ledger (G3). The orchestrator re-anchors P3-1 once slice 3 has merged (its label says how); P3-2 needs no re-anchoring.
4. The census (7.4) is run on a read-only copy before the pull request merges; its flagged documents are recorded on #1686 by count only, and nothing from the vessel is written into the repository.
5. The pull request says `Refs #1686`; the orchestrator closes the issue on its verified-closure step.
6. No existing test is edited but P2-19, and no source file is edited but `records_store.py` and `semantic.py`.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. For the Captain

- **Nothing in this slice needs the Captain's decision.** D0 classifies it as the Architect's under Delegated AD Execution Mode: none of the six conditions is met, and slice 2's "a Captain decision" (its D3) was written before that test. The Captain can overrule after the fact with the ranked option in D0 (the policy without the reader gate) and with D5's (the owner admitted at the search's first pass); the effects are stated there.
- **Two actions only the Captain can take.** (1) Repair or remove each document the census flags: its text is its author's, and the Architect does not edit records. (2) Decide whether the rows the semantic index already holds, as `ship`, for those paths are purged (L3): a production-data operation, outside this slice; the census's second step counts them.
