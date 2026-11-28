# BF-970 (#1801): Every Ship's Records reader reads a frontmatter block one way, with one nesting check at 64, and a block that does not load is never read through its cut

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-19
**Revised by:** the orchestrator (A1, 2026-11-19), as BF-986's contract section 8.3 orders and as the Architect decided (read-only consult `a8c5e319`, 2026-11-19, on #1801 `issuecomment-7025346116`): the guard `gc_quiet_at_recursion_limit` goes on every test function that still records a row in the census of this tree (section 16, M3), and item bf-986 F3 of #1820 rides in this batch as its own last slice (section 17, M4). The commit messages of section 6 are replaced by those of section 16.5. Nothing else of a0 is changed except the two tracker blocks P3-2 and P3-5 (one sentence each).
**Status:** ready to build on the tree after BF-987 (PR #1836) merges: tree `718b0b0f88d0936e1d16bb1dc32bd3730fdf1684`, whose B5 files carry the base blobs below unchanged (premise M0-1, verified 2026-11-19: `git diff --stat 7ca49126 ebaa9729 -- <the nine files>` is empty; PROGRESS.md and DECISIONS.md differ by the BF-985, BF-986 and BF-987 entries, and the SEARCH text of M2 does not touch them). **Oracle:** `ob970c` (detached at `ebaa9729`, tree `718b0b0f`): the 53 pairs of M1 and the five of M2 apply with 0 failures, and all ten code, test and doc blobs equal those of the first oracle `ob970` (built on `7ca49126`).
**Base blobs (`7ca49126`):**

| File | Blob |
|---|---|
| `src/probos/knowledge/records_store.py` | `3e692042a8165bc74a57e74def2e0ad2b15af760` |
| `src/probos/utils/frontmatter.py` | `3d2dcbb3b86f49dbdc90b5b76230184ef969695c` |
| `tests/test_bf940_frontmatter_framing.py` | `7d2170f774850394be9380fbc0f4e5c27e327748` |
| `tests/test_bf940_s4_unparsed_frontmatter.py` | `b83923b6defcdba6153f825f63315de5cb760820` |
| `tests/test_bf952_records_keyword_search.py` | `9992a5fd50f787a9b503e98e7271177e1b873479` |
| `tests/test_bf940_s2_dump_frontmatter.py` | `c6109972a41838978ed04009000c62c4276006f4` |
| `tests/test_bf940_s3_route_serialisation.py` | `7fe4d7e4aa6bc18099b85fca102a1bfe39c61b50` |
| `tests/test_bf940_split_frontmatter.py` | `391eaf27cd9214523b28750b654dddafd410558e` |
| `docs/development/deterministic-ship.md` | `3b2dc74262035f08fbddb6373e7fe36ff567e36a` |
| `PROGRESS.md` | `ef35f28edc2fa0fd0cc1b1d700cf8fe553cf96cf` |
| `DECISIONS.md` | `4ab50810d3b946e23750d19a087639e60153363a` |

After F2 merges, only the last two may differ. Their SEARCH text is chosen to survive that.

**Tier:** M1 HIGH (it changes who may read a stored document, and the one reading every records consumer depends on). M2 STANDARD.
**Estimated tests (expected, not measured):**
- one new file with 12 cases (11 without libyaml);
- six existing files edited in place: `test_bf952` +2 cases, `test_bf940_s3` -15 cases; the counts of the other four do not change.

**BF number:** BF-970 is held by #1801 (open, `bug`). No new number is allocated. Ceiling for the record: AD-1361 by `scripts/ad_ceiling.py` (`prompts/ad-*.md`), next AD-1362.

**Which text describes the head.**
- Before building, `git rev-parse HEAD:<path>` must print the first nine blobs above, and `tests/test_bf970_frontmatter_reading.py` must not exist.
- Any SEARCH that does not occur exactly once is a hard stop for the Architect.
- Working copies are CRLF and the SEARCH text is LF.
- Where the prose and a block differ, the block wins.
- Every block is ASCII.

## 0. Event types and new names

No EventType, config field, table, column or route is added.

| New name | Where | Visibility |
|---|---|---|
| `FRONTMATTER_DEPTH_LIMIT`, `frontmatter_nests_too_deep`, `load_frontmatter` | `probos.utils.frontmatter` | public |
| `_NestsTooDeep` | `probos.utils.frontmatter` | private |
| `_load_document`, `_search_read_frontmatter` | `records_store.py` | private |
| `tests/test_bf970_frontmatter_reading.py` | new test module | n/a |

None of these occurs in `src/` or `tests/` today (section 12, Absence). Note: `_read_document` was BF-952 A1's helper, which A6 deleted. The new name `_load_document` is chosen so the two cannot be confused.

**Removed from `records_store.py`:** `_load_frontmatter`, `_block_unparsed`, `_frontmatter_unparsed`, `_nests_below`, `_search_load_frontmatter`, `_SEARCH_LIBYAML_DEPTH_LIMIT`, and the import of `base_split_frontmatter`. `base_split_frontmatter` itself stays in `utils` (L18).

## 1. Problem (re-derived on `7ca49126`)

The request's anchors were from `5275d008` and some of them name the wrong code. Corrected:

| Request said | Actual on `7ca49126` |
|---|---|
| in-frame load `:312-322` | `_load_frontmatter`, `:311-321`. F1's in-frame load is `:360-364`, inside `_frontmatter_unparsed` |
| `_frontmatter_unparsed` `:325-365` | `:338-364`. `:324-335` is `_block_unparsed`, which the request omitted |
| write path `:1694-1703` | that is `publish` |
| `seed_manuals` `:851` | `:851` is `write_entry`'s update-in-place verdict; `seed_manuals` is `:958` and calls `write_entry` |

1. **A1, three readers.** Where the rule's block does not load, three readers read the base's cut instead: the part of the block up to its first `---`.
   - `_parse_document`, `records_store.py:1902-1909`;
   - the search's first pass, `_search_read_document` `:417-421`;
   - the search's second reading, `_base_reading_admits` `:441`.

   When the cut loads, the reading is truthy, so `_frontmatter_unparsed` (`:355-356`) says False and the stand-in `_unparsed_gate` (`:136-147`) is skipped. A `classification:` key after the cut is lost, and a missing classification reads as `ship` (`record_is_readable` `:205`; `read_entry` `:1554`). Example: `a: x --- y` / `classification: private` / a `!!python/tuple` tag. The cut `a: x` loads as `{"a": "x"}`, so the note is `ship` and every reader is shown it.
2. **Nesting.**
   - Deep nesting is refused only by PyYAML's `RecursionError`, so whether it is refused depends on how many frames sit above `yaml.safe_load`.
   - `_frontmatter_unparsed` loads in its caller's frame to keep that count (F1, `:347-353`, `:360-364`).
   - The search's walk calls it outside its `try` (`:541-542`; the `try` is `:521-529`), so a `RecursionError` there would end the whole search.
   - The search alone checks nesting, against a separate limit of 100 (`_SEARCH_LIBYAML_DEPTH_LIMIT` `:281`, `_nests_below` `:367-384`, used at `:395`).
3. **The writer** (`utils/frontmatter.py:66-93`) writes any depth up to Python's recursion limit. A record written at 64 to about 330 levels is one a fixed limit would refuse to read.
4. **Measured reach** (R4, the Captain-authorised copy of the live records repository, 2026-11-18; `.adq/b5/r4-records.txt`):
   - 7,650 files, of which 2,776 are markdown. All 2,776 have a frontmatter block that loads, and all carry `classification:`.
   - A1-affected (block refused or empty, cut loads): **0**; refused by YAML: 0; key after the cut: 0.
   - Nesting 64 or more: **0**; libyaml unable to parse for depth: 0.
   - Controls pass in memory and as files (2 A1, 1 after-cut and 1 deep planted documents found exactly).

## 2. Solution

- **`probos.utils.frontmatter`** gains:
  - `FRONTMATTER_DEPTH_LIMIT = 64`;
  - `frontmatter_nests_too_deep(text, loader=yaml.SafeLoader)`, which counts collections open at once on `yaml.parse(text, Loader=loader)`. It stops at the 64th and returns False on a parse error;
  - `load_frontmatter(block, loader=yaml.SafeLoader) -> (frontmatter, unparsed)`, which runs the check, then `yaml.load(block, Loader=loader) or {}`. A `YAMLError` gives `({}, True)`.
- **`dump_frontmatter`** checks the text it wrote with the same function before its read-back load, and refuses 64 levels or more with `ValueError`, naming the keys and the limit.
- **`records_store`.**
  - `_load_document(raw) -> (frontmatter, body, unparsed)` frames with `split_frontmatter` and reads with `load_frontmatter`. `read_entry`, `list_entries`, `publish` and update-in-place call it, and `_parse_document` becomes a two-tuple wrapper of it (for the scans and the tests).
  - The search keeps its two readings (RK15). The first pass is `_search_read_frontmatter`: libyaml's reading stands where it holds something; otherwise PyYAML's reading is taken through the same function (A4).
  - The second pass is `_base_reading_admits`: `load_frontmatter(block)` plus the stand-in.
  - The walk takes the verdict from the first pass's own reading, inside its `try`.
  - The three A1 clauses are deleted.
- **What does not change:** the scoring, the libyaml reading of a block that libyaml reads as a mapping below 64 levels, `record_is_readable`, `_unparsed_gate`, `FRONTMATTER_UNPARSED_KEY`, `semantic.py`, the routes and the skill catalog's readers.

**Heavier designs rejected (one line each).**
- A depth-limited loader subclass, i.e. a composer that counts: it is impossible for libyaml (C composer), and two mechanisms would read two ways.
- A post-load depth walk (AD-718a `voice/proposal.py:52-62`): it runs after the recursive load, and it recurses itself.
- Catching `RecursionError` per reader: it depends on the stack, which is the issue's second problem.
- A cap on events or bytes: it would refuse long flat blocks, a behaviour change for ordinary records.
- libyaml's event stream to check PyYAML's readers: a block only PyYAML parses would reach the recursive composer unchecked.
- Moving the skill catalog's readers onto `load_frontmatter`: out of the issue (register R1).

## 3. Decisions

Each decision is ranked on correctness, security, compatibility, reversibility and validation cost; the top option is taken.

**D1. One reading, two loaders.**
- Every reader calls `load_frontmatter`.
- PyYAML's `SafeLoader` for every reader but the search's first pass. `yaml.load(b, Loader=yaml.SafeLoader)` is `yaml.safe_load(b)` (premise M0-3), so blocks under 64 levels read as before (BF-952 A5, A6: every reader but the search reads as `yaml.safe_load` does).
- `_RECORDS_YAML_LOADER` for the first pass, with the same check on the same loader, as the issue requires.

**D2. What counts as a level, and the boundary.**
- Each `CollectionStartEvent` (a mapping or a sequence, flow or block) opens one level and each `CollectionEndEvent` closes one. The top-level mapping counts. Siblings add nothing.
- An alias (`AliasEvent`) opens nothing, and is neither followed by the check nor expanded by the composer. The value an alias builds can be deeper than the text: AD-1341 S5's 5,000-link chain still loads, as today (L8).
- The block is unparsed at `depth >= 64`, so 63 loads and 64 does not.
- The check stops at the event that reaches 64. Its work is bounded by the length of the text, and it holds one integer.
- A parse error before 64 returns False. The load that follows uses the same parser class, so it meets the same error at a depth below 64 and reads it as `YAMLError` -> `({}, True)`.

**D3. Caller-depth independence.**
- PyYAML's `Parser` is a state machine (its `states` list), and libyaml's parser keeps its own C stack. So the check uses a fixed number of Python frames: about 12 for `SafeLoader`, about 3 for `CSafeLoader`.
- The load runs only below 64 levels, so PyYAML's composer (about 2 frames a level) needs at most about 200 frames above the caller.
- No reader's answer depends on the stack above it unless the caller has fewer than about 200 frames left. That is a property of any code, not of nesting (L2).
- The search runs in a worker thread (`asyncio.to_thread`, `:1780`), so the caller's frames never reach it.
- T6 proves the check from 40 frames below the limit, where a 63-level load raises `RecursionError`. T4 calls every reader from 50 extra frames.

**D4. Exception contract (kept per reader).**

`RecursionError` can no longer come from nesting. A constructor `ValueError` (`updated: 2026-13-05`) keeps today's behaviour in every reader, because `load_frontmatter` lets every non-`YAMLError` exception of the load propagate, and the check (a parse) cannot raise one:

| Reader | Today, and after BF-970 | Pinned by |
|---|---|---|
| `read_entry` | raises `ValueError`, Captain included | s4 `:162`, `:168` |
| `list_entries` | skips the document | `:170` |
| Search, first pass | withholds it (walk `:523-529`) | `:169`; bf952 `:382` |
| `_base_reading_admits` | `False` (`:444-446`) | |
| `publish` | raises `ValueError` | `:171` |
| Update-in-place | `except Exception` at `:869`; proceeds without `created` or `revision` | |
| Similarity and convergence scans | their per-file `except` (`:1254`, `:1302`, `:1427`) | |
| Semantic backfill | not indexed: the listing skipped it | |

Two shapes change, both with 0 measured:
- an A1 shape whose cut raised a constructor error: it raised, and is now unparsed;
- a block of 64 levels or more holding a constructor error: it raised, and is now unparsed (the load does not run).

**D5. What replaces `_SEARCH_LIBYAML_DEPTH_LIMIT`, and libyaml's fast path.**
- `FRONTMATTER_DEPTH_LIMIT` (64) replaces it, for every reader, with each reader's own loader.
- For an ordinary block the search's cost is unchanged: today it ran one libyaml parse (`_nests_below`) and one libyaml load; it does the same after.
- A block 64 to 99 deep that libyaml read is now unparsed (R4: 0).
- Where libyaml reads a block as nothing or cannot build it, PyYAML's reading through `load_frontmatter` decides, and supplies the verdict. Today the verdict also came from PyYAML (`_frontmatter_unparsed`). The one difference is a block libyaml reads as falsy and PyYAML as truthy: none is known, and it now reads as `read_entry` reads it.

**D6. A1 goes.**
- The three clauses are deleted. `base_split_frontmatter` stays, as `split_frontmatter`'s answer for a text with no closing line (L18, `utils/frontmatter.py:39`). Its other users are tests only (section 12).
- Behaviour change, for the closure comment:
  - a document whose block YAML refuses and whose base cut loads is now private to the owner of its `notebooks/<callsign>/` directory, and Captain-only elsewhere (BF-940 slice 4 L4);
  - `read_entry`, the search and `list_entries` (marked) answer accordingly, `publish` refuses it, and the backfill leaves it out.
- Reach: 0 on the live copy (R4).

**D7. The writer.**
- `dump_frontmatter` is shared by:
  - `write_entry` `:890`;
  - `append_captains_log` `:1013` (a fixed flat mapping);
  - `publish` `:1703`;
  - the skill catalog's `_rewrite_frontmatter` `skill_catalog.py:808`.
- It refuses a text of 64 levels or more before the read-back load, with the message `frontmatter key(s) <keys> nest 64 or more collections deep, which no reader loads; flatten them`. A `RecursionError` from `safe_dump` takes the same message. The message never holds a value (AD-1140).
- The callers' handling is today's for any `ValueError` of the writer: raise before any file is touched.
  - `write_entry` raises to its caller. The notebook route answers HTTP 400 (`routers/records.py:215-216`).
  - `publish` raises, and the file is untouched.
  - `enrich_skill` raises, and SKILL.md is untouched.
- **No agent text is lost silently.**
  - The proactive notebook writers pass system-collected flat metrics (`proactive.py:3442`, `:3460`) and `tags=[topic_slug]` (`:3458`, `:4514`), so no agent text can reach 64 levels.
  - The "note-taker save path" does not call `dump_frontmatter`: the only callers are the four above (section 12, Absence).
  - A failed proactive write is logged by topic and agent (`proactive.py:4526-4531`), as for any `ValueError`.
- The check measures the dumped text, so a self-referential mapping, which `safe_dump` writes with an alias (depth 1), is still written (T7).

**D8. Who decides.** The Architect decides; none of the Captain conditions is met.
- Nothing is migrated or deleted.
- No schema, key, route body or config changes.
- The change withholds documents and weakens no control. This is BF-940 slice 4 G0's reasoning: a loss of access is not a weakened control, and the search never shows a reader a note `read_entry` withholds from her.
- The writer refuses only what no reader would load.
- Measured reach: 0.

## 4. Every consumer (each command and its result is in section 12)

| Consumer | Where | Reached? | Tested by |
|---|---|---|---|
| `read_entry` | `records_store.py:1524` | yes: `_load_document` | T1, T4, T5, s4 class |
| `list_entries` (marker) | `:1566`, `:1646` | yes | T1, T4, T5, s4 listing |
| `publish` | `:1680` | yes | T1, T4, s4 publish |
| Update-in-place, and `seed_manuals` through it | `:849-851`, `:958` | yes | T4, s4 `:187`, `:401` |
| Search, first pass and walk | `:404`, `:521-547` | yes | T1-T5, bf952, s4 |
| Search, second reading | `:425`, `:586-589` | yes | T1, T3, T4, bf952 `:717` |
| `_parse_document` (scans: `check_notebook_similarity` `:1198`, `:1271`, `:1289`; `check_cross_agent_convergence` `:1379`, `:1400`) | `:1887` | yes: the wrapper | s4 `:174`, framing T9 |
| Semantic backfill | `semantic.py:729-746`: `list_entries` + `read_entry` as the Captain; no parse of its own | transitively | s4 `:374`, `:411`; bf679 `TestPathParity`; bf684 |
| Routes | `routers/records.py`: `read_entry`, `list_entries`, `search` | transitively | `test_bf940_s3_route_serialisation.py` (edited) |
| Gap routes | `routers/gaps.py:23-34`, `commands_gap.py:64`: their `safe_load` reads the document's **content**, not its frontmatter | no (body) | n/a |
| Archive promotion, snapshot, lessons, linter, backlinks, knowledge browser, oracle, DM lookup | via store APIs; none calls `split_frontmatter`, `yaml.safe_load` or `yaml.load` (section 12) | transitively | G2 |
| Skill catalog readers | `skill_catalog.py:107-116`, `:785-792`: own `yaml.safe_load` of SKILL.md | **no** (not migrated: register R1) | G2 |
| Skill catalog writer | `skill_catalog.py:808` `dump_frontmatter` | yes (refuses 64 levels or more) | framing skill cases, `test_cognitive_skill_catalog.py` (G2) |
| Ward Room, knowledge store, dream cycle | no `split_frontmatter` call (section 12, Absence) | no | n/a |

## 5. Milestones and gates

| M | Blocks | Gate |
|---|---|---|
| M1 | N1-1 (new test file) first for G0, then P1-1..P1-4 (utils), P2-1..P2-18 (`records_store`), T-blocks (test edits) | G0, G1, G2 |
| M3 (A1) | the guard blocks of section 16 (six marker lines, `_GUARDED` and its ids), after M1 | G4 |
| M4 (A1) | the F3 blocks of section 17 (one marker line, one `_GUARDED` entry and id), after M3 | G5 |
| M2 | P3-1 (`deterministic-ship.md`), P3-2 (`PROGRESS.md`), P3-3..P3-5 (`DECISIONS.md`), then the ledger | G3 |

The commit order is M1, M3, M4, M2: every code and test change first, the trackers and the ledger last, so that the trackers describe the final tree. One broad gate covers the batch.

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`.

**M0: premises to verify first-hand, each with its probe.** A probe that finds nothing where something is expected is a FAIL.

1. **Base blobs.** Run `git rev-parse HEAD:<path>` for the nine code, test and doc files. Expected: the header's blobs. If F2 has merged, `git diff --stat 7ca49126 HEAD -- src/probos/knowledge/records_store.py src/probos/utils/frontmatter.py tests/test_bf940_*.py tests/test_bf952_records_keyword_search.py docs/development/deterministic-ship.md` must be empty.
2. **The base shows the defect.** Write N1-1 only, then run `PY -m pytest tests/test_bf970_frontmatter_reading.py -q -n 0 -p no:randomly`.
   - **Expected:** 2 passed (T9 x2, guards) and 10 failed (9 without libyaml).
   - Each failure must stop at the line section 8 names. If one stops at a `premise:` line, that is a hard stop for the Architect.
3. **`safe_load` is `load(stream, SafeLoader)`.** Run `PY -c "import inspect, yaml; print(inspect.getsource(yaml.safe_load))"`. Expected: the body is `return load(stream, SafeLoader)`.
4. **PyYAML and libyaml.** Run `PY -c "import yaml, sys; print(yaml.__version__, yaml.__with_libyaml__, sys.version_info[:3], sys.getrecursionlimit())"`. Expected: `6.0.x True (3, 12, x) 1000`.
   - If libyaml is absent: T3 and mutation row R14 do not discriminate; record it (L10).
   - If the limit is not 1000, T5 and T6 still derive their depths from it. Record it.
5. **PyYAML's parser does not recurse.** Run `PY -c "import sys, yaml; sys.setrecursionlimit(150); print(sum(1 for e in yaml.parse('k: ' + '[' * 5000 + ']' * 5000, Loader=yaml.SafeLoader)))"`. Expected: `10007`, with no `RecursionError`.
6. **Reader enumeration (positive control).** Run `rg -n "split_frontmatter\(|dump_frontmatter\(|\byaml\.(safe_load|load)\(" src/probos/knowledge src/probos/utils src/probos/cognitive/skill_catalog.py`.
   - Expected on the base: `records_store.py` `:319`, `:332`, `:357`, `:361`, `:398`, `:413`, `:890`, `:1013`, `:1703`, `:1895`, `:1899`, `:1905`; `utils/frontmatter.py` `:23`, `:61`, `:66`; `skill_catalog.py` `:107`, `:113`, `:177`, `:785`, `:790`, `:808`.
   - After M1, `records_store.py` holds no `yaml.safe_load(`, and its `split_frontmatter(` calls are in `_load_document` and `_search_read_document` only.
7. **Writer callers.** Run `rg -n "dump_frontmatter\(" src`. Expected: `records_store.py:890`, `:1013`, `:1703`, `skill_catalog.py:808`, and the definition.
8. **The number.** Run `gh issue list --state all --search "BF-970 in:title"`. Expected: #1801 only.
9. **M0 counts.** Record `--collect-only -q` counts for every G1 file.

**Gates.**
- **G0:** M0-2 as stated.
- **G1** (after M1): `PY -m pytest tests/test_bf970_frontmatter_reading.py tests/test_bf940_frontmatter_framing.py tests/test_bf940_s4_unparsed_frontmatter.py tests/test_bf952_records_keyword_search.py tests/test_bf940_s2_dump_frontmatter.py tests/test_bf940_s3_route_serialisation.py tests/test_bf940_split_frontmatter.py tests/test_bf940_s2_writer_policy.py tests/test_bf679_oracle_records_reader_identity.py tests/test_bf966_unrecognised_classification.py tests/test_records_store.py tests/test_ad1341_s5_after_action_format.py tests/test_cognitive_skill_catalog.py -q -n 0 -p no:randomly`.
  - **Expected:** the new file 12 passed; `test_bf952` M0 count + 2; `test_bf940_s3` M0 count - 15; every other file at its M0 count; 0 failed.
- **G2:**
  1. `PY -m pytest` over the 78 files below, `-q -n 0 -p no:randomly`. Expected: 0 failed; counts are M0 counts plus the deltas above.
  2. `PY -P scripts/check_architecture_principles.py --check`.

  **How the list was derived:**
  - `rg -l "probos\.knowledge\.records_store|probos\.knowledge import records_store|probos\.utils\.frontmatter|probos\.utils import frontmatter" tests/` gave 48 paths. Two are helpers (`bf934_world.py`, `ablation/sigma_rig.py`).
  - `rg -l "skill_catalog import|from probos\.cognitive import skill_catalog|plan_promotion" tests/` gave 31, 4 of them already counted.
  - `rg -l bf934_world tests/` gave 4.
  - Plus the new file.

  **The 46:** `test_records_store test_proactive_quality test_path_traversal test_circuit_breaker test_bf966_unrecognised_classification test_bf957_records_git_signal test_bf958_records_link_containment test_bf959_records_readers_containment test_bf950_oracle_result_age test_bf952_records_keyword_search test_bf949_notebook_reader_identity test_bf940_s4_unparsed_frontmatter test_bf940_split_frontmatter test_bf940_s2_dump_frontmatter test_bf940_s2_writer_policy test_bf940_s3_route_serialisation test_bf940_frontmatter_framing test_bf923_episodic_recall_callers test_bf866_artifact_channel_seams test_bf684_records_index_coverage test_bf679_oracle_records_reader_identity test_bf084_truncation_and_manuals test_ad912_crew_notebook_generalization test_ad911_yeoman_notebook test_ad594c_parallel_dispatch test_ad594d_delivery_pipeline test_ad594a_consultation_workspace test_ad583_wrong_convergence test_ad576_llm_unavailability test_ad554_realtime_convergence test_ad553_quantitative_baseline test_ad550_notebook_dedup test_ad444_confidence_scoring test_ad437_action_space test_ad1358_s1_head_to_head test_ad1357_context_manifest test_ad1341_s6_records_snapshot test_ad1341_s5_continuous_promotion test_ad1341_s4_lessons test_ad1341_s1_promotion test_ad1341_s1_reset_and_erase test_ad1179_vocabulary_constants test_ad1157_notebook_classification test_ad1141_crew_loop_sigma test_ad1140_publish_finding test_ad1138_records_semantic_index`.

  **The 27:** `test_trigger_learning test_skill_loaded_command test_cognitive_skill_catalog test_cognitive_skill_596b test_ad983b_capability_enablement test_ad887_skill_library_unification test_ad885_acm_unified_lens test_ad728d_self_image_awareness_skill test_ad643a_intent_routing test_ad634_notebook_quality test_ad630_leadership_feedback test_ad625_comm_discipline test_ad626_skill_activation test_ad596d_external_skill_import test_ad596e_skill_validation test_ad596c_skill_bridge test_ad1341_s4_stand_down test_ad1341_s5_after_action_format test_ad1341_s5_after_action test_ad1341_s4_exit_note_erasure test_ad1287_slot_qualification test_ad1287_s2a_profile_currency test_ad1069_skill_forge test_ad1072_agentic_tools test_ad1068_use_skill_tool test_ad1013_pack_skills_loader test_ad1001_ships_locker`.

  **The 4:** `test_bf934_s1_decision_routing test_bf934_s2_secondary_gates test_bf934_s3_intended_actions_ledger test_bf976_withdrawal_ledger`.

  All paths are `tests/<name>.py`.
- **G3** (M2): `PY -P scripts/gen_ad_ledger.py`, then `PY -P scripts/gen_ad_ledger.py --check`, then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`. Commit the ledger pair (`docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json`) with M2.
- **G4** (M3, A1): `PY -m pytest tests/test_bf986_recursion_limit_gc_guard.py tests/test_bf940_s2_dump_frontmatter.py tests/test_bf952_records_keyword_search.py tests/test_bf970_frontmatter_reading.py -q -n 0 -p no:randomly`. Expected: 0 failed; T8 (`test_every_test_that_overflows_the_python_stack_asks_for_the_guard`) runs 9 cases (3 before). Then the census of section 16.1 over the BF-940, BF-952 and BF-970 test files: every row is a guarded function, and no guarded function is without a row.
- **G5** (M4, A1): `PY -m pytest tests/test_bf986_recursion_limit_gc_guard.py "tests/test_ad1127_crew_session_lifecycle_recovery.py::test_install_recovery_plan_rejects_hostile_metadata_before_await" -q -n 0 -p no:randomly`. Expected: 0 failed; T8 runs 10 cases; the AD-1127 function runs its 3 cases.
- **Recorded measurement, not a gate** (L5). Write a corpus of 3,000 store-shaped notes under `tmp_path`, then time `list_entries()` and one `search("warp")` on the base and on M1's head, 3 runs each, and put the medians in the PR.
- **Harness rule.**
  - No source change made to pass a test, no skip, no loosened assertion. A failing case goes back to the Architect.
  - The broad gate runs once, in the main session, with `--receipt`.
  - Stage explicit paths; never `git add -A`.

## 6. Commit messages

- **A1 replaces the two messages of a0** (`BF-970 M1: ...` and `BF-970 M2: ...` with `Closes #1801.`): a commit subject carries no `AD-` or `BF-` token and a message holds none of the words the repository's close, fix and resolve scans match; the issue is closed by hand after the merge. Subjects (the orchestrator writes the bodies; each body ends with its `Refs` line and the Copilot trailer):
  - **C0** (this prompt): `Add the build prompt for one reading of a frontmatter block in every Ship's Records reader` (`Refs #1801.`)
  - **M1:** `Read a frontmatter block one way in every Ship's Records reader, with one nesting check at 64` (`Refs #1801.`)
  - **M3:** `Ask for the recursion-limit guard in the tests that still run to the limit` (`Refs #1801.`)
  - **M4:** `Ask for the recursion-limit guard in the cyclic-metadata recovery test` (`Refs #1820.`)
  - **M2:** `Record the one frontmatter reading in the trackers and the deterministic-ship clause` (`Refs #1801.`)

## 7. The contract

### 7.1 M1: `src/probos/utils/frontmatter.py`

**P1-1.** The module docstring.
SEARCH:
```
it left the frontmatter. This module frames a document (``split_frontmatter`` and ``base_split_frontmatter`` load nothing); each
caller loads the block in its own frame, so PyYAML's recursion frontier stays where it was (BF-952 A6, L30). It imports nothing of
ProbOS (``utils`` holds pure helpers any layer may import). BF-940 slice 2 adds ``dump_frontmatter``, the writers' half: the one
place a frontmatter mapping becomes YAML text, so that a document the store writes is a document the store reads (L24).
```
REPLACE:
```
it left the frontmatter. This module frames a document (``split_frontmatter`` and ``base_split_frontmatter`` load nothing).
BF-970 (#1801) adds ``load_frontmatter``, the one reading of a Ship's Records frontmatter block: it checks the nesting with a
parse that does not recurse (``frontmatter_nests_too_deep``) and loads only below ``FRONTMATTER_DEPTH_LIMIT``, so no reader's
answer depends on the frames above it (this replaces BF-952 A6's frame arrangement). It imports nothing of ProbOS (``utils``
holds pure helpers any layer may import). BF-940 slice 2 adds ``dump_frontmatter``, the writers' half: the one place a
frontmatter mapping becomes YAML text, so that a document the store writes is a document the store reads (L24); it refuses
what ``load_frontmatter`` would not load (BF-970).
```

**P1-2.** `base_split_frontmatter`'s docstring.
SEARCH:
```
    text with no closing line (L18), and the cut a reader reads where the rule's block does not load but this one does (A1, F1).
```
REPLACE:
```
    text with no closing line (L18). BF-940 A1 read this cut where the rule's block did not load; BF-970 (#1801) removed that.
```

**P1-3.** The depth check, the reading, and the writer's private half.
SEARCH:
```
_UNWRITABLE = (yaml.YAMLError, RecursionError)


def _dump(mapping: dict[Any, Any]) -> str:
    text = yaml.safe_dump(mapping, default_flow_style=False, sort_keys=False)
    if type(yaml.safe_load(text)) is not dict:
        raise yaml.YAMLError("frontmatter did not read back as a mapping")
    return text
```
REPLACE:
```
#: BF-970 (#1801): a frontmatter whose YAML holds this many collections open at once, or more, is not loaded by any reader and is
#: not written by ``dump_frontmatter``. The top-level mapping counts as one; a mapping or a sequence, flow or block, opens one more;
#: an alias opens none (the value it names was built where its anchor stands). PyYAML's composer recurses about two Python frames a
#: level, so a load below this depth needs a fixed number of frames whatever the caller's stack.
FRONTMATTER_DEPTH_LIMIT = 64


def frontmatter_nests_too_deep(text: str, loader: Any = yaml.SafeLoader) -> bool:
    """BF-970 (#1801): whether ``text``, parsed with ``loader``, holds ``FRONTMATTER_DEPTH_LIMIT`` collections open at once.

    It reads the parser's event stream, which neither PyYAML's parser nor libyaml's builds by recursion, and stops at the event
    that reaches the limit, so its answer does not depend on the caller's stack and its work is bounded by the length of ``text``:
    no node is built and no alias is followed. Siblings add no depth. A parse error before the limit is ``False``: the load that
    follows, with the same ``loader``, meets the same error below the limit and reads it as YAML's refusal.
    """
    depth = 0
    try:
        for event in yaml.parse(text, Loader=loader):
            if isinstance(event, yaml.CollectionStartEvent):
                depth += 1
                if depth >= FRONTMATTER_DEPTH_LIMIT:
                    return True
            elif isinstance(event, yaml.CollectionEndEvent):
                depth -= 1
    except yaml.YAMLError:
        return False  # a parse error before the limit: the load reads YAML's refusal
    return False


def load_frontmatter(block: str, loader: Any = yaml.SafeLoader) -> tuple[Any, bool]:
    """BF-970 (#1801): a frontmatter block as every Ship's Records reader reads it: ``(frontmatter, unparsed)``.

    ``unparsed`` is True, and ``frontmatter`` ``{}``, for a block YAML refuses (a ``YAMLError``) or one that holds
    ``FRONTMATTER_DEPTH_LIMIT`` collections open at once or more (:func:`frontmatter_nests_too_deep`, checked first with the
    same ``loader``). Otherwise ``frontmatter`` is the load's value, ``{}`` for a falsy one, and ``unparsed`` is False; with the
    default loader that value is ``yaml.safe_load``'s. Any other error of the load propagates, as from ``yaml.safe_load``: a
    constructor's ``ValueError`` (``updated: 2026-13-05``) included. No ``RecursionError`` comes from the nesting: the load
    runs only below the limit.
    """
    if frontmatter_nests_too_deep(block, loader):
        return {}, True
    try:
        return yaml.load(block, Loader=loader) or {}, False
    except yaml.YAMLError:
        return {}, True


class _NestsTooDeep(yaml.YAMLError):
    """BF-970: the text ``safe_dump`` wrote holds ``FRONTMATTER_DEPTH_LIMIT`` collections open at once, which no reader loads."""


_UNWRITABLE = (yaml.YAMLError, RecursionError)


def _dump(mapping: dict[Any, Any]) -> str:
    text = yaml.safe_dump(mapping, default_flow_style=False, sort_keys=False)
    if frontmatter_nests_too_deep(text):  # BF-970: checked before the read-back load, which recurses
        raise _NestsTooDeep("frontmatter nests too deep")
    if type(yaml.safe_load(text)) is not dict:
        raise yaml.YAMLError("frontmatter did not read back as a mapping")
    return text
```

**P1-4.** `dump_frontmatter`'s docstring tail and its refusal.
SEARCH:
```
    refuses (a tuple as a mapping key). A value nested beyond the recursion limit is a ``ValueError`` too. The message names
    the top-level keys at fault and the error's type, never a value (AD-1140's fail-fast tier); the caller has touched no file
    yet.
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
```
REPLACE:
```
    refuses (a tuple as a mapping key). BF-970 (#1801): a mapping whose text holds ``FRONTMATTER_DEPTH_LIMIT`` (64)
    collections open at once or more is a ``ValueError`` (no reader loads it: :func:`load_frontmatter`), checked before the
    read-back load, and so is one nested beyond the recursion limit. The message names the top-level keys at fault and the
    error's type, or the limit, never a value (AD-1140's fail-fast tier); the caller has touched no file yet.
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
        if isinstance(exc, (_NestsTooDeep, RecursionError)):  # BF-970: what no reader loads is not written
            raise ValueError(
                "frontmatter key(s) %s nest %d or more collections deep, which no reader loads; flatten them"
                % (", ".join(keys) or "(none singly)", FRONTMATTER_DEPTH_LIMIT)
            ) from exc
        raise ValueError(
```

### 7.2 M1: `src/probos/knowledge/records_store.py` (blocks in file order)

**P2-1.** The import.
SEARCH:
```
from probos.utils.frontmatter import base_split_frontmatter, dump_frontmatter, split_frontmatter
```
REPLACE:
```
from probos.utils.frontmatter import dump_frontmatter, load_frontmatter, split_frontmatter
```

**P2-2.** The loader comment and the retired limit.
SEARCH:
```
#: loads as the base did, with ``yaml.safe_load`` (A5, round 5). ``_search_load_frontmatter`` reads as
#: the base did a frontmatter libyaml cannot load, for any reason (A4), and one nesting
#: ``_SEARCH_LIBYAML_DEPTH_LIMIT`` collections deep or more (A5).
_RECORDS_YAML_LOADER: Any = yaml.CSafeLoader if getattr(yaml, "__with_libyaml__", False) else yaml.SafeLoader
#: BF-952 A5: the search hands libyaml only a block nesting fewer than this many collections deep. Below
#: it PyYAML's pure-Python composer builds the block too; from about 330 levels it raises
#: ``RecursionError`` (the base's reading), and a block that deep is read with the base's call.
_SEARCH_LIBYAML_DEPTH_LIMIT = 100
```
REPLACE:
```
#: loads as the base did, with ``yaml.SafeLoader`` (A5, round 5). BF-970 (#1801): every reader loads through
#: :func:`probos.utils.frontmatter.load_frontmatter`, which reads a block holding ``FRONTMATTER_DEPTH_LIMIT`` (64)
#: collections open at once or more as unparsed, with either loader; the search reads with PyYAML a block libyaml
#: cannot build or reads as nothing (A4). This replaces A5's separate search limit of 100.
_RECORDS_YAML_LOADER: Any = yaml.CSafeLoader if getattr(yaml, "__with_libyaml__", False) else yaml.SafeLoader
```

**P2-3.** `_load_frontmatter`, `_block_unparsed` and `_frontmatter_unparsed` become `_load_document`.
SEARCH:
```
def _load_frontmatter(block: str) -> Any:
    """BF-952 A5: a frontmatter block loaded exactly as the base loaded it, with ``yaml.safe_load``.

    A falsy value or a ``YAMLError`` is ``{}``. Any other error propagates, as on the base: a constructor's
    (``updated: 2026-13-05`` raises ``ValueError``) and PyYAML's ``RecursionError`` for a block nesting about 330
    collections deep.
    """
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
REPLACE:
```
def _load_document(raw: str) -> tuple[Any, str, bool]:
    """BF-970 (#1801): a document as every reader but the search's first pass reads it: ``(frontmatter, body, unparsed)``.

    The framing every reader shares (:func:`probos.utils.frontmatter.split_frontmatter`) and the one load
    (:func:`probos.utils.frontmatter.load_frontmatter` with ``yaml.SafeLoader``: ``yaml.safe_load``'s reading below the
    nesting limit). A document with no frontmatter block (no opener, or no closing line: L18) is ``({}, raw, False)``. A block
    YAML refuses, or one holding ``FRONTMATTER_DEPTH_LIMIT`` collections open at once or more, is ``({}, body, True)``, and the
    access rules read :func:`_unparsed_gate` for it. BF-940 A1 is gone: the base's cut of the text is never read in the block's
    place. A constructor's error (``updated: 2026-13-05``) propagates, as from ``yaml.safe_load``.
    """
    block, rest = split_frontmatter(raw)
    if block is None:  # no frontmatter block (L18): there is none to refuse
        return {}, raw, False
    frontmatter, unparsed = load_frontmatter(block)
    return frontmatter, rest.strip(), unparsed
```

**P2-4.** `_nests_below`, `_search_load_frontmatter` and `_search_read_document`.
SEARCH:
```
def _nests_below(block: str, limit: int) -> bool:
    """BF-952 A5: whether libyaml parses ``block`` and its collections nest fewer than ``limit`` deep.

    It reads the loader's event stream, which the parser produces without recursing, and stops at ``limit``, so it
    is safe however deep the block. Siblings add no depth. A block that does not parse is not below the limit.
    """
    depth = 0
    try:
        for event in yaml.parse(block, Loader=_RECORDS_YAML_LOADER):
            if isinstance(event, yaml.CollectionStartEvent):
                depth += 1
                if depth >= limit:
                    return False
            elif isinstance(event, yaml.CollectionEndEvent):
                depth -= 1
    except Exception:  # A5: not a swallow; the base's call then reads it: its value, {} or its error (A6)
        return False
    return True


def _search_load_frontmatter(block: str) -> Any:
    """BF-952 A1, A4, A5: a frontmatter block as the search loads it: libyaml where it is safe, else as the base did.

    With libyaml installed and the block nesting fewer than ``_SEARCH_LIBYAML_DEPTH_LIMIT`` collections deep, the
    block is libyaml's value, ``{}`` for a falsy one. That differs from the base where PyYAML's scanner refuses the
    block (RK8: a tab after a key). A block libyaml cannot load, for any reason (A4), and one nesting deeper (A5),
    is read by :func:`_load_frontmatter`, the base's call: its value, ``{}`` for a ``YAMLError``, or its error (A6).
    """
    if _RECORDS_YAML_LOADER is yaml.SafeLoader or not _nests_below(block, _SEARCH_LIBYAML_DEPTH_LIMIT):
        return _load_frontmatter(block)
    try:
        frontmatter = yaml.load(block, Loader=_RECORDS_YAML_LOADER)
    except Exception:  # A4 (round 4): libyaml cannot load the block, so it is read as the base read it
        return _load_frontmatter(block)
    return frontmatter or {}


def _search_read_document(raw: str) -> tuple[Any, str, str | None]:
    """BF-952 A5: a document's frontmatter and body as the search reads them, and its frontmatter block.

    The framing every reader shares (BF-940: :func:`probos.utils.frontmatter.split_frontmatter`) and the search's load
    (:func:`_search_load_frontmatter`). The block (``None`` for a document with no frontmatter) lets the search check
    a record it would return against the base's reading (:func:`_base_reading_admits`). BF-940 A1: where the block reads as
    nothing (it does not load) and the base's cut of the text (:func:`base_split_frontmatter`) reads as something, the
    document reads as the base read it, as ``RecordsStore._parse_document`` reads it; the block returned stays the rule's.
    """
    block, rest = split_frontmatter(raw)
    if block is None:
        return {}, raw, None
    frontmatter = _search_load_frontmatter(block)
    if not frontmatter:
        base_block, base_rest = base_split_frontmatter(raw)
        base_frontmatter = _search_load_frontmatter(base_block)
        if base_frontmatter:
            return base_frontmatter, base_rest.strip(), block
    return frontmatter, rest.strip(), block
```
REPLACE:
```
def _search_read_frontmatter(block: str) -> tuple[Any, bool]:
    """BF-952 A4, A5; BF-970 (#1801): a frontmatter block as the search's first pass reads it: ``(frontmatter, unparsed)``.

    With libyaml installed, libyaml's reading (:func:`probos.utils.frontmatter.load_frontmatter` with ``_RECORDS_YAML_LOADER``)
    stands where it holds something: RK8's one admitted difference (BF-940 slice 4, L11). A block libyaml cannot build, for any
    reason (A4), reads as nothing, or holds ``FRONTMATTER_DEPTH_LIMIT`` collections open at once or more is read as ``read_entry``
    reads it: PyYAML's value, ``({}, True)`` for a block it refuses or one that deep, or its constructor's error (A6).
    """
    if _RECORDS_YAML_LOADER is not yaml.SafeLoader:
        try:
            frontmatter, _ = load_frontmatter(block, _RECORDS_YAML_LOADER)
        except Exception:  # A4: libyaml cannot build the block, for any reason, so PyYAML's reading decides
            frontmatter = None
        if frontmatter:
            return frontmatter, False
    return load_frontmatter(block)


def _search_read_document(raw: str) -> tuple[Any, str, str | None, bool]:
    """BF-952 A5; BF-970 (#1801): a document as the search's first pass reads it: ``(frontmatter, body, block, unparsed)``.

    The framing every reader shares (BF-940: :func:`probos.utils.frontmatter.split_frontmatter`) and the search's load
    (:func:`_search_read_frontmatter`). The block (``None`` for a document with no frontmatter) lets the search check a record
    it would return against ``read_entry``'s reading (:func:`_base_reading_admits`). ``unparsed`` is True where the reading is
    ``{}`` because YAML refused the block or it nests too deep; the walk then applies :func:`_unparsed_gate`. BF-940 A1 is gone:
    the base's cut of the text is never read in the block's place.
    """
    block, rest = split_frontmatter(raw)
    if block is None:
        return {}, raw, None, False
    frontmatter, unparsed = _search_read_frontmatter(block)
    return frontmatter, rest.strip(), block, unparsed
```

**P2-5.** `_base_reading_admits`.
SEARCH:
```
    """BF-952 A5: whether the base's reading of a frontmatter block admits this reader at ``scope``.

    That reading is ``read_entry``'s and the semantic index's (:func:`_load_frontmatter`). The search returns a
    record only where it admits the reader too, so no difference between libyaml's reading and the base's, known
    (RK8) or not, can show a reader a record the base's reading withholds (RK15; BF-679). BF-940 A1: ``read_entry`` reads the
    base's cut where the block reads as nothing and the cut reads as something, so this reading does too; the cut is the block
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
        logger.debug("BF-952: withholding a record the base's reading cannot build", exc_info=True)
        return False  # A5: the search withholds what read_entry raises on
```
REPLACE:
```
    """BF-952 A5: whether ``read_entry``'s reading of a frontmatter block admits this reader at ``scope``.

    That reading is :func:`probos.utils.frontmatter.load_frontmatter` with ``yaml.SafeLoader``, ``read_entry``'s and the
    semantic index's. The search returns a record only where it admits the reader too, so no difference between libyaml's
    reading and PyYAML's, known (RK8) or not, can show a reader a record ``read_entry`` withholds (RK15; BF-679). BF-940 slice 4
    (L19), BF-970 (#1801): where the block is unparsed (YAML refuses it, or it holds ``FRONTMATTER_DEPTH_LIMIT`` collections open
    at once or more) the rules read the document's stand-in (:func:`_unparsed_gate` of ``path``, the document's path in the
    repository), as ``read_entry`` does. BF-940 A1 is gone: the base's cut is never read.
    """
    try:
        frontmatter, unparsed = load_frontmatter(block)  # read_entry's reading (yaml.SafeLoader)
    except Exception:  # A5: read_entry raises on this block (a constructor error)
        logger.debug("BF-952: withholding a record the base's reading cannot build", exc_info=True)
        return False  # A5: the search withholds what read_entry raises on
    if unparsed:  # BF-940 slice 4 (L19), BF-970: the same document read_entry withholds
        frontmatter = _unparsed_gate(path)
```

**P2-6.** The walk's read.
SEARCH:
```
            frontmatter, content_text, block = _search_read_document(raw)
        except Exception:
            # A1, A5: YAML accepted the frontmatter and its constructor raised (``updated: 2026-13-05``
            # is a ``ValueError``, not a ``YAMLError``), or it nests too deep for PyYAML's composer
            # (``RecursionError``). ``read_entry`` raises for such a record; the search withholds it
            # rather than end every search or read it as ``{}``.
```
REPLACE:
```
            frontmatter, content_text, block, unparsed = _search_read_document(raw)
        except Exception:
            # A1, A5: YAML accepted the frontmatter and its constructor raised (``updated: 2026-13-05``
            # is a ``ValueError``, not a ``YAMLError``). ``read_entry`` raises for such a record; the search
            # withholds it rather than end every search or read it as ``{}``. BF-970: a block nesting too deep
            # is unparsed, so no ``RecursionError`` comes from the nesting.
```

**P2-7.** The walk's verdict.
SEARCH:
```
        # withholds more and never gives more (L11).
        if not record_is_readable(
            _unparsed_gate(rel_path) if _frontmatter_unparsed(raw, frontmatter) else frontmatter,
```
REPLACE:
```
        # withholds more and never gives more (L11). BF-970: the verdict is the first pass's own, from inside the try above.
        if not record_is_readable(
            _unparsed_gate(rel_path) if unparsed else frontmatter,
```

**P2-8.** `write_entry`'s docstring.
SEARCH:
```
        BF-940 slice 4 (L19): an update-in-place of a document whose frontmatter did not load (YAML refused it) proceeds as before and
```
REPLACE:
```
        BF-940 slice 4 (L19), BF-970: an update-in-place of a document whose frontmatter did not load (YAML refused it, or it nests 64 collections deep or more) proceeds as before and
```

**P2-9.** Update-in-place.
SEARCH:
```
                existing_raw = file_path.read_text(encoding="utf-8")
                existing_fm, _ = self._parse_document(existing_raw)
                if _frontmatter_unparsed(existing_raw, existing_fm):  # BF-940 slice 4 (L19): said, not refused (seed_manuals overwrites)
```
REPLACE:
```
                existing_raw = file_path.read_text(encoding="utf-8")
                existing_fm, _, existing_unparsed = _load_document(existing_raw)  # BF-970: the reading and its verdict, one load
                if existing_unparsed:  # BF-940 slice 4 (L19): said, not refused (seed_manuals overwrites)
```

**P2-10.** `read_entry`'s docstring.
SEARCH:
```
        BF-940 slice 4 (L19): a document whose frontmatter did not load (YAML refused it) reads as ``{}`` and is private to the owner of
```
REPLACE:
```
        BF-940 slice 4 (L19), BF-970: a document whose frontmatter did not load (YAML refused it, or it nests 64 collections deep or more) reads as ``{}`` and is private to the owner of
```

**P2-11.** `read_entry`'s reading.
SEARCH:
```
            return None

        raw = file_path.read_text(encoding="utf-8")
        frontmatter, content = self._parse_document(raw)
```
REPLACE:
```
            return None

        raw = file_path.read_text(encoding="utf-8")
        frontmatter, content, unparsed = _load_document(raw)  # BF-970: the reading and its verdict, one load
```

**P2-12.** `read_entry`'s gate.
SEARCH:
```
            # BF-940 slice 4 (L19): a frontmatter that did not load names no classification, so the document is private to its owner
            gate = (
                _unparsed_gate(file_path.relative_to(self._repo_path.resolve()).as_posix())
                if _frontmatter_unparsed(raw, frontmatter) else frontmatter
            )
```
REPLACE:
```
            # BF-940 slice 4 (L19), BF-970: a frontmatter that did not load, or nests too deep, names no classification, so the
            # document is private to its owner
            gate = (
                _unparsed_gate(file_path.relative_to(self._repo_path.resolve()).as_posix())
                if unparsed else frontmatter
            )
```

**P2-13.** `list_entries`' docstring.
SEARCH:
```
        BF-940 slice 4 (L19): the entry of a document whose frontmatter did not load (YAML refused it) reads ``{}`` as before and carries
```
REPLACE:
```
        BF-940 slice 4 (L19), BF-970: the entry of a document whose frontmatter did not load (YAML refused it, or it nests 64 collections deep or more) reads ``{}`` and carries
```

**P2-14.** `list_entries`' reading.
SEARCH:
```
                raw = md_file.read_text(encoding="utf-8")
                fm, _ = self._parse_document(raw)
                unparsed = _frontmatter_unparsed(raw, fm)  # BF-940 slice 4 (L19)
```
REPLACE:
```
                raw = md_file.read_text(encoding="utf-8")
                fm, _, unparsed = _load_document(raw)  # BF-940 slice 4 (L19), BF-970: the reading and its verdict, one load
```

**P2-15.** `publish`'s docstring.
SEARCH:
```
        BF-940 slice 4 (L19): a document whose frontmatter did not load (YAML refused it) is not published. ``publish`` writes back what
```
REPLACE:
```
        BF-940 slice 4 (L19), BF-970: a document whose frontmatter did not load (YAML refused it, or it nests 64 collections deep or more) is not published. ``publish`` writes back what
```

**P2-16.** `publish`'s reading.
SEARCH:
```
        raw = file_path.read_text(encoding="utf-8")
        fm, content = self._parse_document(raw)

        if _frontmatter_unparsed(raw, fm):
```
REPLACE:
```
        raw = file_path.read_text(encoding="utf-8")
        fm, content, unparsed = _load_document(raw)  # BF-970: the reading and its verdict, one load

        if unparsed:
```

**P2-17.** `search`'s docstring.
SEARCH:
```
        is skipped; one whose frontmatter does not parse (``read_entry`` reads it
        as ``{}``, unless the base's earlier cut of it parses and it reads as that:
        A3; BF-940 A1, #1686) is private to the owner of its
```
REPLACE:
```
        is skipped; one whose frontmatter does not parse, or nests 64 collections
        deep or more (``read_entry`` reads it as ``{}``; the base's cut is never
        read: BF-970, #1801), is private to the owner of its
```

**P2-18.** `_parse_document`.
SEARCH:
```
        BF-940 (#1686): the frontmatter ends at the first later line of only hyphens, so a value holding ``---``
        stays whole (:func:`probos.utils.frontmatter.split_frontmatter`). The YAML is loaded here, in this frame,
        so PyYAML's recursion frontier is the one the base had (BF-952 A6, L30). BF-940 A1: where the block reads as nothing
        (it does not load) and the base's cut of the text reads as something, the document reads as the base read it.
        """
        block, rest = split_frontmatter(raw)
        if block is None:
            return {}, raw
        try:
            fm = yaml.safe_load(block) or {}
        except yaml.YAMLError:
            fm = {}
        if not fm:  # A1: the base's cut may read where the whole block does not (a tag safe_load refuses, after a ---)
            base_block, base_rest = base_split_frontmatter(raw)
            try:
                base_fm = yaml.safe_load(base_block) or {}
            except yaml.YAMLError:
                base_fm = {}
            if base_fm:
                return base_fm, base_rest.strip()
        return fm, rest.strip()
```
REPLACE:
```
        BF-940 (#1686): the frontmatter ends at the first later line of only hyphens, so a value holding ``---``
        stays whole (:func:`probos.utils.frontmatter.split_frontmatter`). BF-970 (#1801): the document is read by
        :func:`_load_document`, every reader's one reading; a block YAML refuses, or one nesting 64 collections deep or
        more, reads as ``{}``, and the base's cut of the text is never read in its place (BF-940 A1 is gone). The callers
        that must know whether ``{}`` means unparsed (``read_entry``, ``list_entries``, ``publish``, update-in-place) call
        :func:`_load_document` itself; the scans call this.
        """
        frontmatter, body, _ = _load_document(raw)
        return frontmatter, body
```

### 7.3 M1: test edits (file order within each file; each carries its reason inline)

**T-F (`tests/test_bf940_frontmatter_framing.py`)**

T-F1.
SEARCH:
```
    """The rule as a loop over the lines, not a pattern, and A1's fallback: what every reader's reading is compared with."""
```
REPLACE:
```
    """The rule as a loop over the lines, not a pattern: what every reader's reading is compared with. BF-970 (#1801) removed A1's
    fallback, so a block that does not load reads as nothing whatever the base's cut of the text reads."""
```

T-F2.
SEARCH:
```
        frontmatter = {}
    if not frontmatter:  # A1: a block that reads as nothing reads as the base read the text, where the base read something
        earlier = _base_read(raw)
        if earlier[0]:
            return earlier
    return frontmatter, rest.strip()
```
REPLACE:
```
        frontmatter = {}
    return frontmatter, rest.strip()
```

T-F3.
SEARCH:
```
async def test_a_private_note_with_three_hyphens_in_its_topic_stays_private_when_its_metrics_cannot_load(tmp_path, monkeypatch):
    """A1 (round 1, F1): ``yaml.dump`` writes a tuple as ``!!python/tuple``, which ``safe_load`` refuses. The base cut this note's
    block at the ``---`` in the topic, before ``metrics``, so the tag was never loaded and the note stayed alice's; the rule read
    the whole block, got ``{}`` and so ``ship``: every reader was shown it and alice's own ``publish`` raised ``PermissionError``.
    A block that reads as nothing now reads as the base read the text, where the base's cut reads. A tuple with no ``---`` before
    it reads ``{}`` on both trees (L10): not asserted here."""
```
REPLACE:
```
async def test_a_note_with_three_hyphens_in_its_topic_whose_metrics_cannot_load_is_private_to_its_owner(tmp_path, monkeypatch):
    """BF-970 (#1801) removed A1 (round 1, F1), which read this note's base cut, the block up to the ``---`` in its topic, where
    ``safe_load`` refused the ``!!python/tuple`` in its metrics. The cut named alice and ``private`` here, but a cut that names no
    classification read as ``ship`` (#1801's first problem). The block does not load, so the note is unparsed: private to the owner
    of ``notebooks/alice/`` (BF-940 slice 4, L19), read as ``{}``, and refused by ``publish``, whatever its cut says."""
```

T-F4.
SEARCH:
```
    own = await store.read_entry(path, reader_id="alice")
    assert own is not None and own["frontmatter"].get("classification") == "private" and own["frontmatter"].get("author") == "alice"
    assert [hit["path"] for hit in await store.search("coolant", reader_id="alice")] == [path]
    await store.publish(path, "alice")
    assert await store.read_entry(path, reader_id="bob") is None
```
REPLACE:
```
    own = await store.read_entry(path, reader_id="alice")
    assert own is not None and own["frontmatter"] == {}  # BF-970: unparsed; A1 read the cut here
    assert [hit["path"] for hit in await store.search("coolant", reader_id="alice")] == [path]
    with pytest.raises(ValueError):
        await store.publish(path, "alice")  # BF-970: publish refuses an unparsed note (BF-940 slice 4, G2); A1 published the cut
    assert await store.read_entry(path, reader_id="bob") is None
```

T-F5.
SEARCH:
```
    own = await store.read_entry(path, reader_id="alice")
    assert own is not None and own["frontmatter"].get("classification") == "private"
    assert [hit["path"] for hit in await store.search("warp", reader_id="alice")] == [path]
```
REPLACE:
```
    own = await store.read_entry(path, reader_id="alice")
    assert own is not None and own["frontmatter"] == {}  # BF-970 (#1801): PyYAML refuses the block, so it is unparsed; A1 read the cut
    assert [hit["path"] for hit in await store.search("warp", reader_id="alice")] == [path]
```

T-F6.
SEARCH:
```
            {"author": "alice", "classification": "private"}, "inline\nWarp notes, in prose.\n---\nmore warp notes", {"alice"},
            id="then-prose-and-a-rule-reads-as-the-base-read-it",
```
REPLACE:
```
            {}, "more warp notes", {"alice"},  # BF-970 (#1801): A1 is gone, so the block that does not load is unparsed (owner: alice)
            id="then-prose-and-a-rule-is-unparsed",
```

T-F7.
SEARCH:
```
        its closing line, as here (L3); where it does not (the 2nd, prose after a key) the shape reads as the base read it (A1).
```
REPLACE:
```
        its closing line, as here (L3); where it does not (the 2nd, prose after a key) it is unparsed (BF-970 removed A1).
```

T-F8.
SEARCH:
```
        """BF-952's T22 over its 3,747 shapes, rewritten: both readers read each as ``_oracle`` does (the rule, then A1's fallback),
        a constructor error included. Premise: ``reframed`` names 2,388 of them (the rule frames them otherwise than the base). The
        number the contract claims, asserted last: 2,110 of them, and no other, are returned otherwise than ``_base_read`` returns
        them, by either reader, an error compared by its name. The other 278 read as the base reads them: A1's fallback gives 90 of
        the 2,200 that M2 changed back, and the rest raise the same error or read alike."""
```
REPLACE:
```
        """BF-952's T22 over its 3,747 shapes, rewritten: both readers read each as ``_oracle`` does (the rule; BF-970, #1801,
        removed A1's fallback), a constructor error included. Premise: ``reframed`` names 2,388 of them (the rule frames them
        otherwise than the base). The number the contract claims, asserted last: 2,200 of them, and no other, are returned otherwise
        than ``_base_read`` returns them, by either reader, an error compared by its name: BF-940's 2,110 and the 90 that A1's fallback
        gave back to the base's reading (BF-940 contract, D7). The other 188 raise the same error or read alike."""
```

T-F9.
SEARCH:
```
        assert len(moved) == 2110 and all(map(reframed, moved)), "claim: 2,110 shapes read otherwise than on the base, all of them reframed"
```
REPLACE:
```
        assert len(moved) == 2200 and all(map(reframed, moved)), "claim: 2,200 shapes read otherwise than on the base, all of them reframed"
```

T-F10.
SEARCH:
```
            ({"author": "alice", "classification": "private", "topic": "review"}, "nominal\nmetrics:\n  sample: !!python/tuple\n  - 1\n  - 2\n---\n\ncoolant body"),
            id="a-tag-safe-load-refuses-after-three-hyphens-reads-as-the-base-read-it",
        ),
        pytest.param("---\n- a\n- b---c\nfoo: bar\n---\nbody", (["a", "b"], "c\nfoo: bar\n---\nbody"), id="a-cut-that-is-a-list-is-taken-as-the-base-took-it"),
        pytest.param("---\nkey: [unclosed\ntopic: a---b\n---\nbody", ({}, "body"), id="a-cut-that-does-not-load-either-reads-as-the-rule-reads-it"),
```
REPLACE:
```
            ({}, "coolant body"),  # BF-970 (#1801): unparsed; A1 read the cut
            id="a-tag-safe-load-refuses-after-three-hyphens-is-unparsed",
        ),
        pytest.param("---\n- a\n- b---c\nfoo: bar\n---\nbody", ({}, "body"), id="a-block-that-does-not-load-whose-cut-is-a-list-is-unparsed"),
        pytest.param("---\nkey: [unclosed\ntopic: a---b\n---\nbody", ({}, "body"), id="a-cut-that-does-not-load-either-is-unparsed"),
```

T-F11.
SEARCH:
```
    def test_a_block_that_does_not_load_reads_as_the_base_read_the_text_where_the_cut_loads(self, tmp_path, raw, read):
        """A1 (F1), through both readers. The first row is F1's note as a document. The second has a cut that is a list, taken as
        the base took it (the search then withholds it: a mapping is required). The third has a cut that does not load either, so
        the rule's reading stands, its body included. The last pins the trigger: a constructor error is not a parse failure, so it
        raises, as the base raised for the same YAML (L13)."""
```
REPLACE:
```
    def test_a_block_that_does_not_load_reads_as_nothing_whatever_its_cut_reads(self, tmp_path, raw, read):
        """BF-970 (#1801) removed A1 (F1), through both readers: a block YAML refuses reads as ``{}`` with the rule's body, whatever
        the base's cut of the text reads. The first row is F1's note as a document (its cut named alice and ``private``); the
        second's cut is a list; the third's does not load either. The last pins the trigger: a constructor error is not a parse
        failure, so it raises, as the base raised for the same YAML (L13)."""
```

**T-S (`tests/test_bf940_split_frontmatter.py`)**

T-S1.
SEARCH:
```
    """A1: the search's second reading holds only the rule's block and reads the base's cut as ``block.partition("---")[0]``.
    Wherever the rule frames a text with a block, the base frames it with one, and that block is this."""
```
REPLACE:
```
    """Wherever the rule frames a text with a block, the base frames it with one, and that block is the rule's up to its first
    ``---``. BF-970 (#1801) removed A1, the search's reading of that cut; the property stays, because ``base_split_frontmatter`` is
    still the rule's answer for a text with no closing line (L18)."""
```

**T-D (`tests/test_bf940_s2_dump_frontmatter.py`)**

T-D1.
SEARCH:
```
def test_a_mapping_nested_too_deeply_is_a_value_error_not_a_recursion_error():
    assert yaml.safe_load(dump_frontmatter({"k": _nested(100)}))["k"]["k"]
```
REPLACE:
```
def test_a_mapping_nested_too_deeply_is_a_value_error_not_a_recursion_error():
    # BF-970 (#1801): a mapping holding 64 collections open at once or more is refused (no reader loads it), so the written case is
    # 63 deep (the outer mapping and 62 more), where it was 101 (_nested(100)) before the limit.
    assert yaml.safe_load(dump_frontmatter({"k": _nested(62)}))["k"]["k"]
```

**T-R (`tests/test_bf940_s3_route_serialisation.py`)**

T-R1.
SEARCH:
```
stop, and derives every depth below from the answer. The reader's own stop (``RecursionError`` at about 490 levels on Windows and on Linux, Python 3.12) is
that of pure-Python PyYAML and does not depend on the writer. A lone surrogate reaches a record as an ASCII escape, ``\\ud800``, in the JSON a notebook
```
REPLACE:
```
stop, and derives every depth below from the answer. BF-970 (#1801): the reader now stops first. A frontmatter holding ``FRONTMATTER_DEPTH_LIMIT`` (64)
collections open at once, or more, is unparsed (read as ``{}``), below the writer's stop on every platform, so no record the reader parses is too deep for
a route; the nesting rows left ``_UNWRITABLE`` and the cases that drove them now pin that. A lone surrogate reaches a record as an ASCII escape, ``\\ud800``, in the JSON a notebook
```

T-R2.
SEARCH:
```
from probos.knowledge.records_store import RecordsStore
from probos.routers.records import router
```
REPLACE:
```
from probos.knowledge.records_store import RecordsStore
from probos.routers.records import router
from probos.utils import frontmatter as frontmatter_module
```

T-R3.
SEARCH:
```
_FAR_OVER = _READ_LIMIT + 50  # refused likewise, and far inside the reader's reach: the reader raised RecursionError at about 490 levels
```
REPLACE:
```
_FAR_OVER = _READ_LIMIT + 50  # refused likewise (BF-970: the reader reads a frontmatter this deep as unparsed; only the premise below uses it)
```

T-R4.
SEARCH:
```
# (the YAML value of one key, a text that must never reach a log line). ``nested-over-limit`` is five levels over a listing's limit, so over the read
# route's too; ``nested-far-over-limit`` is fifty levels over the read route's, a record the reader still parses with room to spare. Each case asserts
# that the reader parsed its record, so a reader that stops sooner fails at a premise line, not at a status. ``lone-surrogate`` is the ASCII YAML
# escape, never a literal one.
_UNWRITABLE = [
    pytest.param("{a: " * _JUST_OVER + _MARKER + "}" * _JUST_OVER, _MARKER, id="nested-over-limit"),
    pytest.param("{a: " * _FAR_OVER + _MARKER + "}" * _FAR_OVER, _MARKER, id="nested-far-over-limit"),
    pytest.param("!!binary //4=", "xff", id="bytes-not-utf-8"),
```
REPLACE:
```
# (the YAML value of one key, a text that must never reach a log line). BF-970 (#1801): the two nesting rows (five levels over a listing's limit,
# fifty over the read route's) left this list: the reader reads a frontmatter that deep as unparsed, ``{}``, which every route writes
# (``test_a_record_nested_past_the_readers_limit_is_answered_as_unparsed``). Each case asserts that the reader parsed its record, so a reader that
# stops sooner fails at a premise line, not at a status. ``lone-surrogate`` is the ASCII YAML escape, never a literal one.
_UNWRITABLE = [
    pytest.param("!!binary //4=", "xff", id="bytes-not-utf-8"),
```

T-R5.
SEARCH:
```
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
```
REPLACE:
```
@pytest.mark.parametrize("url", [pytest.param(_READ, id="read"), *_LISTINGS])
async def test_the_deepest_record_the_reader_parses_is_answered_by_every_route(tmp_path, url):
    """Guard. BF-970 (#1801): this stood five levels below the writer's listing limit; the reader now stops first, so the deepest
    record it parses, 63 collections open at once (the record's mapping and 62 nested ones), is answered on the read route and in
    every listing, on any platform."""
    depth = frontmatter_module.FRONTMATTER_DEPTH_LIMIT - 2
    assert depth < _LISTING_LIMIT, "premise: the reader's deepest record is within the writer's listing limit"
    store = _make_store(tmp_path, {_NOTE: _HEALTHY, _LOG: _HEALTHY, _BAD_NOTE: _record("meta", _nested(depth)), _BAD_LOG: _record("meta", _nested(depth))})
    entry = await store.read_entry(_BAD_NOTE, reader_id="captain")
    assert entry is not None and entry["frontmatter"]["meta"] == _mapping(depth), "premise: the reader parsed the record"
    response = _get(store, url)
    assert response.status_code == 200 and "case.md" in response.text


async def test_a_record_nested_past_the_readers_limit_is_answered_as_unparsed(tmp_path):
    """BF-970 (#1801): this pinned the reader's ``RecursionError`` for 600 levels (the read route's 503, the record left out of a
    listing). The reader now reads a frontmatter that deep, or 64 levels and more, as unparsed: the Captain reads ``{}``, the read
    route answers it, and a listing lists it with the key ``list_entries`` sets."""
    store = _make_store(tmp_path, {_NOTE: _HEALTHY, _BAD_NOTE: _record("meta", _nested(600))})
    assert await store.read_entry(_BAD_NOTE, reader_id="captain") == {"frontmatter": {}, "content": "coolant case body", "path": _BAD_NOTE}
    read = _get(store, _READ)
    assert read.status_code == 200 and read.json()["frontmatter"] == {}
    listing = _get(store, "/api/records/documents")
    assert listing.status_code == 200 and [item["path"] for item in _items(listing)] == [_BAD_NOTE, _NOTE]
```

T-R6.
SEARCH:
```
    store = _make_store(tmp_path, {_NOTE: _HEALTHY, _BAD_NOTE: _record("topic", _nested(_FAR_OVER))})
```
REPLACE:
```
    store = _make_store(tmp_path, {_NOTE: _HEALTHY, _BAD_NOTE: _record("topic", "!!binary //4=")})  # BF-970: bytes; that nesting is now read as {}
```

T-R7.
SEARCH:
```
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
```
REPLACE:
```
    async def test_no_record_the_reader_parses_is_too_deep_for_a_listing(self, tmp_path):
        """BF-970 (#1801): this case scanned a window around the listing's limit through the real store for the first depth a
        listing refused. The reader now reads a frontmatter holding 64 collections open or more as unparsed, so no depth it parses
        reaches that limit: 63 levels are parsed and listed, 64 are read as ``{}`` and listed with the key, on any platform."""
        limit = frontmatter_module.FRONTMATTER_DEPTH_LIMIT
        assert limit - 2 < _LISTING_LIMIT, "premise: the deepest record the reader parses is within the listing's limit"
        store = _make_store(tmp_path, {_NOTE: _HEALTHY})
        for depth, parsed in ((limit - 2, True), (limit - 1, False)):
            (store.repo_path / _BAD_NOTE).write_text(_record("meta", _nested(depth)), encoding="utf-8")
            entry = await store.read_entry(_BAD_NOTE, reader_id="captain")
            assert ("meta" in entry["frontmatter"]) is parsed, depth
            response = _get(store, "/api/records/documents")
            assert response.status_code == 200
            assert [item["path"] for item in _items(response)] == [_BAD_NOTE, _NOTE], depth
```

T-R8.
SEARCH:
```
            "captains-log/c.md": entry("2026-03-01", f"meta: {_nested(_FAR_OVER)}\n"),
```
REPLACE:
```
            "captains-log/c.md": entry("2026-03-01", "meta: !!binary //4=\n"),  # BF-970: bytes the writer refuses; that nesting now reads as {}
```

T-R9.
SEARCH:
```
    @pytest.mark.parametrize(("value", "marker"), [_UNWRITABLE[1], _UNWRITABLE[2], _UNWRITABLE[4]])
```
REPLACE:
```
    @pytest.mark.parametrize(("value", "marker"), [_UNWRITABLE[0], _UNWRITABLE[2]])  # BF-970: the nesting row left _UNWRITABLE; bytes and the lone surrogate stay
```

**T-4 (`tests/test_bf940_s4_unparsed_frontmatter.py`)**

T-4-1.
SEARCH:
```
module's functions are guards and pass on both trees: they hold what this slice must not change (a document with no frontmatter, an
empty one or an unclosed opener; a frontmatter the base's cut reads; a constructor error; the scans; the parse and the mapping
``read_entry`` returns; an update-in-place, which ``seed_manuals`` runs at every boot; how deeply nested a document each reader
parses before ``RecursionError``, which the verdict must not lower: S10). A case asserts its premise first (YAML refuses
```
REPLACE:
```
module's functions are guards and pass on both trees: they hold what this slice must not change (a document with no frontmatter, an
empty one or an unclosed opener; a constructor error; the scans; the parse and the mapping ``read_entry`` returns; an update-in-place,
which ``seed_manuals`` runs at every boot). BF-970 (#1801) removed A1 (a frontmatter only the base's cut reads is now unparsed) and the
frame arrangement S10 pinned (every reader reads a block nesting 64 collections deep or more as unparsed, from any stack); the cases
that pinned them are rewritten in place. A case asserts its premise first (YAML refuses
```

T-4-2.
SEARCH:
```
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
```
REPLACE:
```
@pytest.mark.parametrize("classification", ["private", "ship"])
async def test_a_frontmatter_that_loads_only_through_the_base_cut_is_a_parse_failure(store, classification):
    """BF-970 (#1801) removed A1: the block YAML refuses is unparsed whatever its cut names, so the note is alice's alone (her notebook
    directory's), read as ``{}`` and listed with the key, where A1 read the cut's classification (and showed bob the ``ship`` one)."""
    path = "notebooks/alice/review---nominal.md"
    block = f"author: alice\nclassification: {classification}\nstatus: draft\ntopic: review---nominal\nmetrics:\n  sample: !!python/tuple\n  - 1\n  - 2\n"
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(block)
    assert yaml.safe_load(block.partition("---")[0])["classification"] == classification, "premise: the cut alone names the classification"
    _hand_made(store, path, _raw(block, "coolant private body"))
    own = await store.read_entry(path, reader_id="alice")
    assert own is not None and own["frontmatter"] == {}
    assert await store.read_entry(path, reader_id="bob") is None
    assert path not in await _found(store, "bob", "coolant")
    assert [e for e in await store.list_entries() if e["path"] == path] == [{"path": path, "frontmatter": {}, _KEY: True}]
```

T-4-3. This block replaces `_frontier`, the reader probes, `_never` and the F1 frontier case.
SEARCH:
```
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
```
REPLACE:
```
async def _read_entry_unparsed(store: RecordsStore, path: str) -> bool:
    entry = await store.read_entry(path, reader_id="captain")
    return await store.read_entry(path, reader_id="bob") is None and entry is not None and entry["frontmatter"] == {}


async def _list_entries_unparsed(store: RecordsStore, path: str) -> bool:
    return [entry for entry in await store.list_entries() if entry["path"] == path] == [{"path": path, "frontmatter": {}, _KEY: True}]


async def _publish_unparsed(store: RecordsStore, path: str) -> bool:
    kind, message = await _attempt(store.publish(path, "captain"))
    return kind is ValueError and path in message


class _Recorder(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


async def _update_in_place_unparsed(store: RecordsStore, path: str) -> bool:
    recorder = _Recorder()
    records_logger = logging.getLogger("probos.knowledge.records_store")
    records_logger.addHandler(recorder)
    try:
        await store.write_entry("alice", path, "replacement body", "frontier", classification="private")
    finally:
        records_logger.removeHandler(recorder)
    return any(path in message for message in recorder.messages)


@pytest.mark.parametrize("reader", [
    pytest.param(_read_entry_unparsed, id="read-entry"),
    pytest.param(_list_entries_unparsed, id="list-entries"),
    pytest.param(_publish_unparsed, id="publish"),
    pytest.param(_update_in_place_unparsed, id="update-in-place"),
])
async def test_a_reader_reads_a_deeply_nested_document_as_unparsed_from_any_stack(store, reader):
    """BF-970 (#1801) replaces F1's frame arrangement, which this case pinned (the verdict had to load in its caller's frame so that it
    stopped at the nesting the reader's own parse stopped at). Every reader checks the nesting with a parse that does not recurse, so a
    document that nests and then ends in a YAML error is unparsed at every depth: 63 collections open (it loads to the error) and 64 or
    more (it is not loaded), from no extra frames or 50. On the base a reader raised ``RecursionError`` at the deepest rows."""
    path = "notebooks/alice/n.md"
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(_frontier_block(2))
    for depth in (2, 62, 63, sys.getrecursionlimit()):  # _frontier_block(depth) holds depth + 1 collections open at once
        for pad in (0, 50):
            _hand_made(store, path, _frontier_document(depth))
            assert await _padded(pad, lambda: reader(store, path)), (depth, pad)
```

T-4-4.
SEARCH:
```
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
```
REPLACE:
```
    async def test_the_reading_and_its_verdict_are_one_load(self, store, monkeypatch):
        """BF-970 (#1801): the verdict is the reading's own (``_load_document`` returns it), where F1 loaded the block a second time in
        the caller's frame and A1 a third time (its cut): ``read_entry`` of a note YAML refuses loads its block once."""
        path = "notebooks/alice/note.md"
        _hand_made(store, path, _raw(_BROKEN))
        loaders: list[Any] = []
        real = yaml.load

        def counting(stream: Any, *args: Any, **kwargs: Any) -> Any:
            loaders.append(args[0] if args else kwargs.get("Loader"))
            return real(stream, *args, **kwargs)

        monkeypatch.setattr(yaml, "load", counting)
        assert await store.read_entry(path, reader_id="bob") is None, "premise: the stand-in refuses bob"
        assert loaders == [yaml.SafeLoader]
```

**T-K (`tests/test_bf952_records_keyword_search.py`)**

T-K1.
SEARCH:
```
@pytest.mark.parametrize(("depth", "style"), [
    pytest.param(99, "flow", id="flow-just-below-the-search-limit"),
    pytest.param(100, "flow", id="flow-at-the-search-limit"),
    pytest.param(150, "flow", id="flow-below-the-base-limit"),
    pytest.param(600, "flow", id="flow-past-the-base-limit"),
    pytest.param(150, "block", id="block-below-the-base-limit"),
    pytest.param(600, "block", id="block-past-the-base-limit"),
])
def test_a_deeply_nested_frontmatter_reads_as_on_the_base(tmp_path: Path, depth: int, style: str) -> None:
    """A5 (round 5, finding 1): libyaml loads a frontmatter nesting about 330 collections deep or more, where the
    base's ``yaml.safe_load`` raised ``RecursionError``, which is not a ``YAMLError``; through A4 every reader read
    what the base raised on. Every reader but the search now reads with the base's call, and the search hands
    libyaml only a block nesting fewer than 100 deep. Each shape reads under ``_parse_document`` (the base's own
    text, A6) and the search as on the base, the ``RecursionError`` included."""
    raw = _nested(depth, style)
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    expected = _read_or_error(_base_read, raw)
    if depth >= 600:  # premise: the shape is the class round 5 found
        assert expected == "RecursionError"
        if _LIBYAML:
            assert type(yaml.load(raw.split("---", 2)[1], Loader=yaml.CSafeLoader)) is dict
    else:  # premise: PyYAML reads it
        assert type(expected[0]) is dict and expected[0]["classification"] == "ship"
    assert _read_or_error(store._parse_document, raw) == expected
    assert _read_or_error(_search_read, raw) == expected
```
REPLACE:
```
@pytest.mark.parametrize(("depth", "style"), [
    pytest.param(63, "flow", id="flow-just-below-the-limit"),
    pytest.param(64, "flow", id="flow-at-the-limit"),
    pytest.param(100, "flow", id="flow-at-the-old-search-limit"),
    pytest.param(150, "flow", id="flow-below-the-base-recursion"),
    pytest.param(600, "flow", id="flow-past-the-base-recursion"),
    pytest.param(63, "block", id="block-just-below-the-limit"),
    pytest.param(64, "block", id="block-at-the-limit"),
    pytest.param(600, "block", id="block-past-the-base-recursion"),
])
def test_a_frontmatter_nesting_64_collections_or_more_is_unparsed_in_both_readings(tmp_path: Path, depth: int, style: str) -> None:
    """BF-970 (#1801) replaces A5's depth arrangement, which this case pinned (libyaml for a block below 100 levels, the base's
    call above, its ``RecursionError`` included): every reader reads a block holding 64 collections open at once, or more, as
    unparsed, ``({}, body)``, with either loader, and one of 63 as before. The base raised ``RecursionError`` for 600 levels."""
    raw = _nested(depth, style)
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    if depth >= 600:  # premise: the base's reading of this class raised
        assert _read_or_error(_base_read, raw) == "RecursionError"
    if depth < 64:
        expected = _base_read(raw)
        assert type(expected[0]) is dict and expected[0]["classification"] == "ship"  # premise: PyYAML reads it
    else:
        expected = ({}, "warp core notes")
    assert _read_or_error(store._parse_document, raw) == expected
    assert _read_or_error(_search_read, raw) == expected
    assert records_store_module._search_read_document(raw)[3] is (depth >= 64)
```

T-K2.
SEARCH:
```
@pytest.mark.asyncio
@pytest.mark.parametrize("depth", [
    pytest.param(150, id="below-the-base-limit"),
    pytest.param(600, id="past-the-base-limit"),
])
async def test_a_deeply_nested_record_is_read_listed_published_and_found_as_on_the_base(
    tmp_path: Path, depth: int,
) -> None:
    """A5 (round 5, finding 1), through the real readers. Through A4 libyaml read a 600-level frontmatter for every
    reader: ``read_entry`` returned it, ``list_entries`` listed it and update-in-place kept its ``created``. On the
    base ``read_entry`` and ``publish`` raised ``RecursionError`` and ``list_entries`` skipped the record, and they
    do again; the search withholds it. Below the base's limit every reader reads it, as on the base."""
    raw = _nested(depth, "flow")
    store = await _store(tmp_path)
    path = "notebooks/alice/nested.md"
    target = store.repo_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(raw, encoding="utf-8")
    base = _read_or_error(_base_read, raw)
    if depth >= 600:
        assert base == "RecursionError"  # premise
        with pytest.raises(RecursionError):
            await store.read_entry(path, reader_id="captain")
        with pytest.raises(RecursionError):
            await store.publish(path, author="captain")
        assert await store.list_entries("notebooks") == []
        assert await _paths(store, "warp", reader_id="captain") == []
    else:
        frontmatter, body = base
        assert await store.read_entry(path, reader_id="bob") == {
            "frontmatter": frontmatter, "content": body, "path": path,
        }
        listed = [(entry["path"], entry["frontmatter"]) for entry in await store.list_entries("notebooks")]
        assert listed == [(path, frontmatter)]
        assert await _paths(store, "warp", reader_id="bob") == [path]
```
REPLACE:
```
@pytest.mark.asyncio
@pytest.mark.parametrize("depth", [
    pytest.param(150, id="below-the-base-recursion"),
    pytest.param(600, id="past-the-base-recursion"),
])
async def test_a_deeply_nested_record_is_unparsed_in_every_reader(
    tmp_path: Path, depth: int,
) -> None:
    """BF-970 (#1801), through the real readers; it replaces A5's case, which pinned the base's ``RecursionError`` (600) and the
    base's reading (150). A record whose frontmatter holds 64 collections open or more is unparsed: private to the owner of its
    notebook directory (BF-940 slice 4, L19), read as ``{}`` by the Captain, listed with the key, refused by ``publish``, and found
    by the search for the Captain and its owner only."""
    raw = _nested(depth, "flow")
    store = await _store(tmp_path)
    path = "notebooks/alice/nested.md"
    target = store.repo_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(raw, encoding="utf-8")
    if depth >= 600:
        assert _read_or_error(_base_read, raw) == "RecursionError"  # premise: the base raised for this class
    assert await store.read_entry(path, reader_id="captain") == {"frontmatter": {}, "content": "warp core notes", "path": path}
    assert await store.read_entry(path, reader_id="bob") is None
    with pytest.raises(ValueError):
        await store.publish(path, author="captain")
    key = records_store_module.FRONTMATTER_UNPARSED_KEY
    assert [(entry["path"], entry["frontmatter"], entry.get(key)) for entry in await store.list_entries("notebooks")] == [(path, {}, True)]
    assert await _paths(store, "warp", reader_id="captain") == [path]
    assert await _paths(store, "warp", reader_id="alice") == [path]
    assert await _paths(store, "warp", reader_id="bob") == []
```

T-K3.
SEARCH:
```
    monkeypatch.setattr(
        records_store_module, "_search_load_frontmatter", lambda block: {"author": "alice", "classification": "ship"},
    )
```
REPLACE:
```
    monkeypatch.setattr(  # BF-970 (#1801): the search's first-pass reading returns (frontmatter, unparsed)
        records_store_module, "_search_read_frontmatter", lambda block: ({"author": "alice", "classification": "ship"}, False),
    )
```

T-K4. This block replaces `_nests_below`'s case, `_frontier` and the A6 frontier case.
SEARCH:
```
def test_libyaml_is_given_only_a_block_nesting_fewer_than_the_limit_deep() -> None:
    """A5: ``_nests_below`` counts open collections in the parser's event stream, so siblings add no depth, and a
    block that does not parse is not below the limit (the base's call reads it)."""
    limit = records_store_module._SEARCH_LIBYAML_DEPTH_LIMIT
    assert limit == 100
    nests_below = records_store_module._nests_below
    assert nests_below("nest: " + "[" * 98 + "]" * 98, limit)  # 99 deep, the mapping included
    assert not nests_below("nest: " + "[" * 99 + "]" * 99, limit)  # 100 deep
    assert nests_below("tags: [" + ", ".join(["[warp]"] * 150) + "]", limit)  # 3 deep, 152 collections
    assert not nests_below("broken: [unclosed", limit)


def _frontier(read: Any) -> int:
    """A6 (round 6, finding 1): the deepest flow nesting ``read`` reads when called from here, by bisection.

    PyYAML's composer recurses about two Python frames a nesting level, so where a reader raises ``RecursionError``
    depends on the frames between its caller and ``yaml.safe_load``. Every reader compared is called from this frame.
    """
    low, high = 2, sys.getrecursionlimit()
    assert _read_or_error(read, _nested(low, "flow")) != "RecursionError"  # premise: the low end reads
    assert _read_or_error(read, _nested(high, "flow")) == "RecursionError"  # premise: the high end raises
    while high - low > 1:
        middle = (low + high) // 2
        if _read_or_error(read, _nested(middle, "flow")) == "RecursionError":
            high = middle
        else:
            low = middle
    return low


def test_parse_document_raises_at_the_base_recursion_frontier(tmp_path: Path) -> None:
    """A6 (round 6, finding 1): A5 sent ``_parse_document`` through two more frames before ``yaml.safe_load``, so a
    document nesting one level below the base's limit raised ``RecursionError`` where the base read it, and
    update-in-place reset its ``created``, ``revision`` and classification. ``_parse_document`` is the base's own
    text again: called from the same frame as the base's (``_base_read``), it reads to the same depth."""
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    assert _frontier(store._parse_document) == _frontier(_base_read)
```
REPLACE:
```
def test_the_nesting_check_counts_open_collections_and_leaves_a_parse_error_to_the_load() -> None:
    """BF-970 (#1801) replaces ``_nests_below`` and ``_SEARCH_LIBYAML_DEPTH_LIMIT`` (100, the search's alone) with one check for
    every reader, ``frontmatter_nests_too_deep``, at ``FRONTMATTER_DEPTH_LIMIT`` (64), with the loader the load uses. It counts
    open collections in the parser's event stream, so siblings add no depth, and a block that does not parse is left to the
    load, which reads YAML's refusal."""
    from probos.utils import frontmatter as frontmatter_module

    assert frontmatter_module.FRONTMATTER_DEPTH_LIMIT == 64
    too_deep = frontmatter_module.frontmatter_nests_too_deep
    for loader in [yaml.SafeLoader, *([yaml.CSafeLoader] if _LIBYAML else [])]:
        assert not too_deep("nest: " + "[" * 62 + "]" * 62, loader), loader  # 63 deep, the mapping included
        assert too_deep("nest: " + "[" * 63 + "]" * 63, loader), loader  # 64 deep
        assert not too_deep("tags: [" + ", ".join(["[warp]"] * 150) + "]", loader), loader  # 3 deep, 152 collections
        assert not too_deep("broken: [unclosed", loader), loader
        assert frontmatter_module.load_frontmatter("broken: [unclosed", loader) == ({}, True), loader


def test_parse_document_never_raises_recursion_error_for_nesting(tmp_path: Path) -> None:
    """BF-970 (#1801) replaces A6's frontier case, which pinned ``_parse_document`` to the base's ``RecursionError`` depth (it had
    to stay the base's own text, called from the base's frame). A block nesting 64 collections deep or more is unparsed before any
    load, so ``_parse_document`` reads ``({}, body)`` however deep the block and whatever the stack."""
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    limit = sys.getrecursionlimit()
    assert _read_or_error(_base_read, _nested(limit, "flow")) == "RecursionError"  # premise: the base's reading raised at this depth
    for depth in (64, limit, 10 * limit):
        assert _read_or_error(store._parse_document, _nested(depth, "flow")) == ({}, "warp core notes"), depth
```

T-K5.
SEARCH:
```
async def test_read_entry_reads_with_parse_document_as_on_the_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A6 (round 6, finding 1): ``read_entry`` reads a document with ``self._parse_document(raw)``, the base's own
    call, so its reading and the depth at which it raises ``RecursionError`` are the base's from every caller. A5
    called a module function two frames deeper instead."""
    store = await _store(tmp_path)
    path = "notebooks/alice/warp.md"
    _write(store, path, "warp core notes", author="alice")
    parsed: list[str] = []
    parse = store._parse_document

    def _recording(raw: str) -> tuple[dict, str]:
        parsed.append(raw)
        return parse(raw)

    monkeypatch.setattr(store, "_parse_document", _recording)
```
REPLACE:
```
async def test_read_entry_reads_with_the_one_document_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BF-970 (#1801) replaces A6's delegation case (``read_entry`` had to call ``self._parse_document(raw)``, the base's own text,
    for the base's recursion frontier). ``read_entry`` reads a document once, with ``_load_document``, the reading every reader
    but the search's first pass shares; it returns the verdict too."""
    store = await _store(tmp_path)
    path = "notebooks/alice/warp.md"
    _write(store, path, "warp core notes", author="alice")
    parsed: list[str] = []
    load = records_store_module._load_document

    def _recording(raw: str) -> tuple[Any, str, bool]:
        parsed.append(raw)
        return load(raw)

    monkeypatch.setattr(records_store_module, "_load_document", _recording)
```

### 7.4 New file: `tests/test_bf970_frontmatter_reading.py` (M1)

```python
"""BF-970 (#1801): Ship's Records read a frontmatter block one way, with a fixed nesting limit, and fail closed.

Every reader reads a block through ``probos.utils.frontmatter.load_frontmatter``. A block YAML refuses, or one holding
``FRONTMATTER_DEPTH_LIMIT`` (64) collections open at once or more, is unparsed, and the access rules read the stand-in
(``_unparsed_gate``: private to the owner of its ``notebooks/<callsign>/`` directory). BF-940 A1 (reading the base's cut of the
text where the block did not load) is gone, and ``dump_frontmatter`` refuses what no reader would load. Real ``RecordsStore`` over
``tmp_path`` with ``~`` moved and hand-made documents; no network. Each case asserts its premise first; the new module names are
read as attributes, so on the base a case fails at its own line, not at import.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

from probos.config import RecordsConfig
from probos.knowledge import records_store as records_store_module
from probos.knowledge.records_store import FRONTMATTER_UNPARSED_KEY, RecordsStore
from probos.utils import frontmatter as frontmatter_module
from probos.utils.frontmatter import base_split_frontmatter, dump_frontmatter

_LIMIT = 64  # the issue's limit: a block holding 64 collections open at once is unparsed, and one holding 63 loads
_BODY = "warp private body"
_LIBYAML = bool(getattr(yaml, "__with_libyaml__", False))
_LOADERS = [yaml.SafeLoader, *([yaml.CSafeLoader] if _LIBYAML else [])]
#: The issue's first acceptance shape: a ``---`` inside a value, then ``classification: private``, then a tag ``safe_load``
#: refuses. The base's cut (``a: x``) loads and names no classification, so A1 read the note as ``ship``.
_A1_BLOCK = "a: x --- y\nclassification: private\nauthor: alice\nsample: !!python/tuple [1, 2]\n"
#: A block PyYAML refuses (a tab after a key) and libyaml reads, whose base cut (``a: x``) loads and names no classification.
_TAB_BLOCK = "a: x --- y\nnote:\tabc\n"


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


def _healthy(store: RecordsStore, path: str, body: str) -> None:
    values = {"author": "captain", "classification": "ship", "status": "published"}
    _hand_made(store, path, f"---\n{yaml.safe_dump(values, sort_keys=False)}---\n\n{body}\n")


async def _found(store: RecordsStore, reader_id: str | None, query: str = "warp") -> list[str]:
    return [hit["path"] for hit in await store.search(query, scope="ship", reader_id=reader_id)]


async def _scores(store: RecordsStore, reader_id: str) -> dict[str, float]:
    return {hit["path"]: hit["score"] for hit in await store.search("warp coolant", scope="ship", reader_id=reader_id)}


async def _attempt(call: Any) -> tuple[type | None, str]:
    try:
        await call
    except Exception as exc:  # noqa: BLE001 -- the case asserts on the type and the text
        return type(exc), str(exc)
    return None, ""


def _nest(depth: int, style: str = "flow") -> str:
    """A block holding ``depth`` collections open at once, its top-level mapping included, in flow or block style."""
    inner = depth - 1
    nest = "[" * inner + "x" + "]" * inner if style == "flow" else "\n" + "- " * inner + "x"
    return f"author: alice\nclassification: ship\nnest: {nest}\n"


def _open_at_once(text: str) -> int:
    """The most collections open at once in ``text``, counted from PyYAML's own event stream (each depth's premise)."""
    depth = deepest = 0
    for event in yaml.parse(text, Loader=yaml.SafeLoader):
        if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
            depth += 1
            deepest = max(deepest, depth)
        elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
            depth -= 1
    return deepest


def _mapping(depth: int) -> Any:
    """``depth`` nested single-key mappings around a leaf."""
    value: Any = "leaf"
    for _ in range(depth):
        value = {"k": value}
    return value


async def _padded(pad: int, call: Any) -> Any:
    """``await call()`` with ``pad`` more coroutine frames beneath it."""
    if pad:
        return await _padded(pad - 1, call)
    return await call()


def _deep(pad: int, call: Any) -> Any:
    """``call()`` with ``pad`` more frames beneath it."""
    if pad:
        return _deep(pad - 1, call)
    return call()


def _stack_depth() -> int:
    count, frame = 0, sys._getframe()
    while frame is not None:
        count, frame = count + 1, frame.f_back
    return count


def _with_frames_left(left: int, call: Any) -> Any:
    """``call()`` from a stack about ``left`` frames below the recursion limit."""
    if _stack_depth() < sys.getrecursionlimit() - left:
        return _with_frames_left(left, call)
    return call()


def _alias_block(shape: str) -> str:
    """AD-1341 S5's alias graphs (register F-661): a 5,000-link chain, or a 22-level doubling graph (a billion laughs)."""
    if shape == "chain":
        anchors = ["n0: &n0 [x]", *(f"n{i}: &n{i} [*n{i - 1}]" for i in range(1, 5000))]
        top = 4999
    else:
        anchors = ["n0: &n0 [x]", *(f"n{i}: &n{i} [*n{i - 1}, *n{i - 1}]" for i in range(1, 23))]
        top = 22
    return "author: alice\nclassification: ship\n" + "\n".join(anchors) + f"\ngraph: *n{top}\n"


async def test_a_document_only_its_cut_reads_is_unparsed_in_every_reader(store):
    """T1, acceptance 1. ``safe_load`` refuses the block (a ``!!python/tuple`` after ``classification: private``), and the base's
    cut, the block up to the ``---`` inside the first value, loads as ``{"a": "x"}``, which names no classification: A1 read it as
    ``ship`` and showed it to every reader. The block is unparsed now: ``read_entry``, the search and ``list_entries`` apply the
    stand-in (private to the owner of ``notebooks/alice/``), and ``publish`` refuses it. The last three lines are the seams each A1
    clause stood in (mutation rows R1 to R3)."""
    raw = _raw(_A1_BLOCK)
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(_A1_BLOCK)
    cut, _ = base_split_frontmatter(raw)
    assert yaml.safe_load(cut) == {"a": "x"}, "premise: the base's cut loads and names no classification (it read as ship)"
    path = "notebooks/alice/a1.md"
    _hand_made(store, path, raw)
    _healthy(store, "reports/open.md", "warp open body")
    assert await store.read_entry(path, reader_id="bob") is None
    assert await store.read_entry(path, reader_id="alice") == {"frontmatter": {}, "content": _BODY, "path": path}
    assert (await store.read_entry(path, reader_id="captain"))["frontmatter"] == {}
    assert await _found(store, "bob") == ["reports/open.md"]
    assert path in await _found(store, "alice") and path in await _found(store, "captain")
    listed = {entry["path"]: entry for entry in await store.list_entries()}
    assert listed[path] == {"path": path, "frontmatter": {}, FRONTMATTER_UNPARSED_KEY: True}
    kind, message = await _attempt(store.publish(path, "alice"))
    assert kind is ValueError and path in message
    assert records_store_module._load_document(raw) == ({}, _BODY, True)
    frontmatter, _, block, unparsed = records_store_module._search_read_document(raw)
    assert (frontmatter, unparsed) == ({}, True)
    assert records_store_module._base_reading_admits(block, scope="ship", reader_id="bob", reader_department="", path=path) is False


async def test_a_document_only_its_cut_reads_moves_no_score_of_a_reader_it_is_withheld_from(store, tmp_path):
    """T2, acceptance 1, the search's first pass (mutation row R2): A1's first pass read the cut, admitted bob, and so counted the
    note toward the rarity of the terms bob searches (BF-952 A4). Unparsed, it counts only for the readers the stand-in admits."""
    plain = _make_store(tmp_path / "plain")
    for target in (store, plain):
        _healthy(target, "reports/h1.md", "warp")
        _healthy(target, "reports/h2.md", "coolant")
    _hand_made(store, "notebooks/alice/a1.md", _raw(_A1_BLOCK, "warp"))
    expected = await _scores(plain, "bob")
    assert set(expected) == {"reports/h1.md", "reports/h2.md"}, "premise: the healthy records are found"
    assert await _scores(store, "captain") != await _scores(plain, "captain"), "premise: a note a reader may read moves her scores"
    assert await _scores(store, "bob") == expected


async def test_a_block_only_libyaml_reads_whose_cut_loads_is_withheld_from_another_reader(store, monkeypatch):
    """T3, acceptance 1, the search's second reading (mutation row R3). PyYAML refuses the block (a tab after a key) and libyaml
    reads it as a mapping that names no classification, so under libyaml the first pass admits bob; A1's second reading read the
    cut (``a: x``: no classification, ``ship``) and admitted him too. The second reading now applies the stand-in. Under PyYAML's
    loader the first pass reads the block as unparsed, so only a host with libyaml kills R3 here (T1 kills it on any host)."""
    path = "notebooks/alice/tab.md"
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(_TAB_BLOCK)
    if _LIBYAML:
        assert yaml.load(_TAB_BLOCK, Loader=yaml.CSafeLoader) == {"a": "x --- y", "note": "abc"}, "premise: libyaml reads it"
    _hand_made(store, path, _raw(_TAB_BLOCK))
    _healthy(store, "reports/open.md", "warp open body")
    for loader in _LOADERS:
        monkeypatch.setattr(records_store_module, "_RECORDS_YAML_LOADER", loader)
        assert await _found(store, "bob") == ["reports/open.md"], loader
        assert path in await _found(store, "alice") and path in await _found(store, "captain"), loader


@pytest.mark.parametrize("style", ["flow", "block"])
async def test_a_block_holding_64_collections_open_is_unparsed_in_every_reader_from_50_frames_and_63_loads(
    store, monkeypatch, caplog, style,
):
    """T4, acceptance 2. The nesting is checked with a parse that does not recurse, so the answer does not depend on the frames
    above the reader: each reader is called from 50 extra frames. The base loaded both blocks from here (PyYAML raises only past
    about 330 levels), so a 64-level note named ``ship`` was shown to bob (mutation rows R4 to R6)."""
    shallow, deep = _nest(_LIMIT - 1, style), _nest(_LIMIT, style)
    assert (_open_at_once(shallow), _open_at_once(deep)) == (_LIMIT - 1, _LIMIT), "premise: the depths, from PyYAML's events"
    assert yaml.safe_load(deep)["classification"] == "ship", "premise: the base's call loads 64 levels from here"
    loaded, refused = "notebooks/alice/shallow.md", "notebooks/alice/deep.md"
    _hand_made(store, loaded, _raw(shallow))
    _hand_made(store, refused, _raw(deep))
    assert await _padded(50, lambda: store.read_entry(refused, reader_id="bob")) is None
    assert (await _padded(50, lambda: store.read_entry(refused, reader_id="captain")))["frontmatter"] == {}
    near = await _padded(50, lambda: store.read_entry(loaded, reader_id="bob"))
    assert near is not None and near["frontmatter"]["classification"] == "ship"
    listed = {entry["path"]: entry for entry in await _padded(50, store.list_entries)}
    assert listed[refused] == {"path": refused, "frontmatter": {}, FRONTMATTER_UNPARSED_KEY: True}
    assert FRONTMATTER_UNPARSED_KEY not in listed[loaded] and listed[loaded]["frontmatter"]["classification"] == "ship"
    for loader in _LOADERS:
        monkeypatch.setattr(records_store_module, "_RECORDS_YAML_LOADER", loader)
        seen = await _padded(50, lambda: _found(store, "bob"))
        assert loaded in seen and refused not in seen, loader
        assert refused in await _padded(50, lambda: _found(store, "captain")), loader
        assert _deep(50, lambda chosen=loader: frontmatter_module.load_frontmatter(deep, chosen)) == ({}, True), loader
        assert _deep(50, lambda chosen=loader: frontmatter_module.load_frontmatter(shallow, chosen))[1] is False, loader
    admits = records_store_module._base_reading_admits
    assert _deep(50, lambda: admits(deep, scope="ship", reader_id="bob", reader_department="", path=refused)) is False
    assert _deep(50, lambda: admits(shallow, scope="ship", reader_id="bob", reader_department="", path=loaded)) is True
    kind, message = await _attempt(_padded(50, lambda: store.publish(refused, "captain")))
    assert kind is ValueError and refused in message
    with caplog.at_level(logging.WARNING, logger="probos.knowledge.records_store"):
        await _padded(50, lambda: store.write_entry("alice", refused, "replacement body", "probe", classification="private"))
    assert any(refused in record.getMessage() for record in caplog.records if record.levelno == logging.WARNING)


async def test_a_search_over_a_corpus_holding_a_block_nested_400_deep_returns_the_other_records(store, monkeypatch):
    """T5, acceptance 3. A block nesting 400 collections deep, and one as deep as the recursion limit (past what PyYAML loads), are
    unparsed: the search returns the other records to every reader and finds those two for the Captain and their owner only, and
    ``read_entry`` and ``list_entries`` read them as ``{}``. The base either loaded the 400-level note (named ``ship``, shown to bob)
    or raised ``RecursionError`` for it and withheld it from the Captain too; it withheld the deeper one from everyone."""
    limit = sys.getrecursionlimit()
    deep, deeper = _nest(400), _nest(limit)
    assert (_open_at_once(deep), _open_at_once(deeper)) == (400, limit), "premise: the depths, from PyYAML's events"
    with pytest.raises(RecursionError):
        yaml.safe_load(deeper)  # premise: past what PyYAML's composer loads
    others = ["reports/a.md", "reports/b.md"]
    for path in others:
        _healthy(store, path, "warp report")
    nested = ["notebooks/alice/deep.md", "notebooks/alice/deeper.md"]
    _hand_made(store, nested[0], _raw(deep))
    _hand_made(store, nested[1], _raw(deeper))
    for loader in _LOADERS:
        monkeypatch.setattr(records_store_module, "_RECORDS_YAML_LOADER", loader)
        assert sorted(await _found(store, "bob")) == others, loader
        assert sorted(await _found(store, "captain")) == sorted(others + nested), loader
        assert sorted(await _found(store, "alice")) == sorted(others + nested), loader
    for path in nested:
        assert (await store.read_entry(path, reader_id="captain"))["frontmatter"] == {}, path
    listed = {entry["path"]: entry for entry in await store.list_entries()}
    assert all(listed[path].get(FRONTMATTER_UNPARSED_KEY) is True for path in nested)


@pytest.mark.parametrize("loader", _LOADERS, ids=lambda loader: loader.__name__)
def test_the_nesting_check_answers_from_a_nearly_exhausted_stack_and_stops_at_the_limit(loader):
    """T6. The check reads the parser's event stream and builds no node, so it needs a few frames whatever the depth: from a stack
    40 frames below the recursion limit, where PyYAML cannot load a 63-level block, it answers for 63, 64 and ten times the limit.
    Siblings add no depth; a parse error is the load's to read (YAML's refusal); a block that loads to nothing is not unparsed."""
    assert frontmatter_module.FRONTMATTER_DEPTH_LIMIT == _LIMIT
    check = frontmatter_module.frontmatter_nests_too_deep
    huge = _nest(10 * sys.getrecursionlimit())
    with pytest.raises(RecursionError):
        _with_frames_left(40, lambda: yaml.load(_nest(_LIMIT - 1), Loader=yaml.SafeLoader))  # premise: no room for a 63-level load
    answers = _with_frames_left(40, lambda: (check(_nest(_LIMIT - 1), loader), check(_nest(_LIMIT), loader), check(huge, loader)))
    assert answers == (False, True, True)
    assert check("tags: [" + ", ".join(["[warp]"] * 150) + "]", loader) is False  # 3 deep, 152 collections
    assert check("broken: [unclosed", loader) is False
    assert frontmatter_module.load_frontmatter("broken: [unclosed", loader) == ({}, True)
    assert frontmatter_module.load_frontmatter("[]", loader) == ({}, False)


def test_dump_frontmatter_refuses_a_mapping_holding_64_collections_open_and_writes_63():
    """T7. ``dump_frontmatter`` refuses (``ValueError``) what no reader loads, naming the key and the limit, never a value; 63 levels
    are written and read back (mutation rows R8, R9). A mapping that holds itself is written with an alias, which opens no
    collection, and still reads back: the check measures the text the readers read, not the Python object."""
    fits = {"k_good": 1, "k_fine": _mapping(_LIMIT - 2)}
    too_deep = {"k_good": 1, "k_bad": _mapping(_LIMIT - 1)}
    assert (_open_at_once(yaml.safe_dump(fits)), _open_at_once(yaml.safe_dump(too_deep))) == (_LIMIT - 1, _LIMIT), "premise: the depths"
    assert yaml.safe_load(dump_frontmatter(fits)) == fits
    with pytest.raises(ValueError) as info:
        dump_frontmatter(too_deep)
    message = str(info.value)
    assert "k_bad" in message and "k_good" not in message and str(_LIMIT) in message and "leaf" not in message
    looped: dict[str, Any] = {"author": "alice"}
    looped["self"] = looped
    text = dump_frontmatter(looped)
    assert _open_at_once(text) == 1 and "*" in text


async def test_write_entry_refuses_a_64_level_value_before_touching_the_file_and_round_trips_63(store):
    """T8. The store never writes what it would refuse to read: ``write_entry`` raises before any file is touched (the notebook
    route answers that ``ValueError`` with HTTP 400), and the deepest value it writes reads back whole."""
    path = "notebooks/alice/deep.md"
    with pytest.raises(ValueError) as info:
        await store.write_entry("alice", path, "warp body", "probe", classification="private", metrics=_mapping(_LIMIT - 1))
    assert "metrics" in str(info.value) and not (store.repo_path / path).exists()
    await store.write_entry("alice", path, "warp body", "probe", classification="private", metrics=_mapping(_LIMIT - 2))
    own = await store.read_entry(path, reader_id="alice")
    assert own is not None and own["frontmatter"]["metrics"] == _mapping(_LIMIT - 2)
    assert await store.read_entry(path, reader_id="bob") is None


@pytest.mark.parametrize("shape", ["chain", "doubling"])
async def test_an_alias_graph_opens_no_collection_and_reads_as_before_in_bounded_time(store, shape):
    """T9, guard (passes on the base). An alias adds no depth to the check, which follows none, and the load builds each anchored
    node once, so a 5,000-link chain and a doubling graph read as before, quickly: the note is ``ship``, shown to bob and found."""
    block = _alias_block(shape)
    assert _open_at_once(block) == 2, "premise: every collection is a sequence under the mapping"
    path = "notebooks/alice/alias.md"
    _hand_made(store, path, _raw(block))
    started = time.perf_counter()
    entry = await store.read_entry(path, reader_id="bob")
    found = await _found(store, "bob")
    assert time.perf_counter() - started < 30.0  # a hang guard, as AD-1341 S5's
    assert entry is not None and entry["frontmatter"]["classification"] == "ship"
    assert found == [path]
```

### 7.5 M2: tracking and docs

**P3-1.** `docs/development/deterministic-ship.md`. Line 49 is the SEARCH, whole.
SEARCH:
```
| **1. Persistence** | What was committed is still there after a restart, on any storage backend. | Every durable store opens through the `ConnectionFactory` protocol (`src/probos/protocols.py:362`), e.g. `EventLog` (`substrate/event_log.py:486-503`) and `ArchiveStore` (`knowledge/archive_store.py:481`). Ship's Records makes every write a git commit (`knowledge/records_store.py:207-212`). | No verified snapshot or point-in-time restore yet (AD-1265, AD-1266, Wave 4 of #1324). Ship's Records reads a document whose frontmatter does not parse as one with none (`{}`), unless the base's earlier cut of it parses and it reads as that (#1686), and treats it as private to the owner of its notebook directory: no reader but that owner and the Captain reads or finds it, the semantic backfill does not index it and `publish` refuses it (BF-940 slice 4); the store's own writers no longer produce one (a tuple is written as a list and a value no reader loads is refused, BF-940 slice 2). A rewrite of one still restarts its created time and revision (it is logged), and an index row written before slice 4 stays until the record is next written. |
```
REPLACE:
```
| **1. Persistence** | What was committed is still there after a restart, on any storage backend. | Every durable store opens through the `ConnectionFactory` protocol (`src/probos/protocols.py:362`), e.g. `EventLog` (`substrate/event_log.py:486-503`) and `ArchiveStore` (`knowledge/archive_store.py:481`). Ship's Records makes every write a git commit (`knowledge/records_store.py:207-212`). | No verified snapshot or point-in-time restore yet (AD-1265, AD-1266, Wave 4 of #1324). Ship's Records reads a document whose frontmatter does not parse, or nests 64 collections deep or more, as one with none (`{}`), whatever an earlier cut of its text reads (BF-970, #1801), and treats it as private to the owner of its notebook directory: no reader but that owner and the Captain reads or finds it, the semantic backfill does not index it and `publish` refuses it (BF-940 slice 4); the store's own writers no longer produce one (a tuple is written as a list, and a value no reader loads, 64 levels deep included, is refused: BF-940 slice 2, BF-970). A rewrite of one still restarts its created time and revision (it is logged), and an index row written before slice 4 stays until the record is next written. |
```

**P3-2.** `PROGRESS.md`. The SEARCH is the title line alone, which survives F2's entry. Replace `DATE` with M2's date.
SEARCH:
```
# ProbOS Progress
```
REPLACE:
```
# ProbOS Progress

**BF-970 (DATE), #1801 -- every Ship's Records reader reads a frontmatter block one way: a block that nests 64 collections deep, or does not load, is unparsed in every reader, and no reader reads the base's cut in its place.**
- **Base.** Where a block did not load, `_parse_document`, the search's first pass and its second reading read the base's cut instead (BF-940 A1), so a `classification:` after a `---` inside a value was lost and the note read as `ship`. Deep nesting was refused only by PyYAML's `RecursionError`, so the answer depended on the frames above the load (BF-940 slice 4's F1 arrangement; BF-952 A6), the search alone had a limit (100), and the writer wrote any depth.
- **Fix.** `probos.utils.frontmatter.load_frontmatter` is the one reading: `frontmatter_nests_too_deep` counts collections open at once on the parser's events with the load's own loader (no recursion) and a block of 64 or more, or one YAML refuses, is unparsed. `read_entry`, `list_entries`, `publish`, update-in-place and the search's two readings use it; A1's three clauses are removed; the search's verdict comes from its own reading inside its `try`. `dump_frontmatter` refuses a mapping whose text holds 64 levels or more. The libyaml reading of ordinary blocks and the scoring are unchanged. Reach on the live copy (R4, 2026-11-18): 2,776 of 2,776 markdown documents load and carry `classification:`; A1-affected 0, nesting 64 or more 0. `tests/test_bf970_frontmatter_reading.py` adds 12 cases; BF-940, BF-952 and the route tests that pinned A1, the frame arrangement or the reader's `RecursionError` are rewritten in place. Six test functions that drive PyYAML's loader or representer to the recursion limit by design (the S2 write, three of BF-952's cases and two of the new file's) ask for BF-986's guard `gc_quiet_at_recursion_limit`, as the census of this tree decided (#1754), and so does the AD-1127 cyclic-metadata case (item bf-986 F3 of #1820). Contract `prompts/bf-970-frontmatter-one-reading.md`.
- **Limits.** The skill catalog still reads SKILL.md with its own `yaml.safe_load` (follow-up in #1820). Index rows written before for a document that is now unparsed stay (BF-940 slice 4 L3; none measured).
```

**P3-3.** `DECISIONS.md`, BF-952's residual pointer.
SEARCH:
```
- *Residual.* Recorded limits L1 to L30 of the contract.
```
REPLACE:
```
- *Residual.* Recorded limits L1 to L30 of the contract. *RK8's depth limit (`_SEARCH_LIBYAML_DEPTH_LIMIT`, 100) and RK15's frame clause (A6) are replaced by BF-970 (#1801): one nesting check at 64 for every reader.*
```

**P3-4.** `DECISIONS.md`, BF-940 slice 1's residual pointer.
SEARCH:
```
- *Residual.* L1 to L17 of the contract. *Reversal.* Revert the BF-940 commits.
```
REPLACE:
```
- *Residual.* L1 to L17 of the contract. *Reversal.* Revert the BF-940 commits. *G4 (A1) is replaced by BF-970 (#1801): a block that does not load is unparsed whatever its cut reads.*
```

**P3-5.** `DECISIONS.md`, slice 4's pointer and the BF-970 entry, which goes straight after slice 4's.
SEARCH:
```
- *Residual.* L1 to L12 of the contract. *Reversal.* Revert the BF-940 slice 4 commits.

### BF-935 -- A Scout run lists each repository once, however many of its topic searches return it (2026-11-11, #1674)
```
REPLACE:
```
- *Residual.* L1 to L12 of the contract. *Reversal.* Revert the BF-940 slice 4 commits. *G3's frame arrangement (F1) is replaced by BF-970 (#1801): the verdict is the reading's own.*

### BF-970 -- Every Ship's Records reader reads a frontmatter block one way: one nesting check at 64, and no reader reads the base's cut (DATE, #1801)

- *Scope.* `utils/frontmatter.py` (`FRONTMATTER_DEPTH_LIMIT`, `frontmatter_nests_too_deep`, `load_frontmatter`; `dump_frontmatter` refuses 64 levels), `knowledge/records_store.py` (`_load_document` for `read_entry`, `list_entries`, `publish`, update-in-place and `_parse_document`; the search's `_search_read_frontmatter`, `_search_read_document`, `_base_reading_admits` and walk; six names removed), one clause of `docs/development/deterministic-ship.md`, tests. Contract `prompts/bf-970-frontmatter-one-reading.md`. Replaces BF-940's G4 (A1), slice 4's G3 frame arrangement, BF-952's RK8 depth limit and RK15's frame clause.
- *D1 (one reading).* One function reads a block for every reader, PyYAML's `SafeLoader` everywhere but the search's first pass, which keeps libyaml where libyaml reads a mapping (RK8, L11) and PyYAML's reading otherwise (A4). Rejected: a depth-counting loader subclass (libyaml's composer is C); catching `RecursionError` (stack-dependent).
- *D2 (the limit).* 64 collections open at once, the top-level mapping included, counted on the parser's events with the load's own loader; an alias opens none; a parse error is the load's to read. 63 loads, 64 does not. Rejected: a post-load depth walk (AD-718a's: after the recursive load, and recursive itself); a cap on events or bytes (it would refuse long flat blocks); libyaml's events to check PyYAML's readers (a block only PyYAML parses would reach the composer unchecked).
- *D3 (A1 goes).* A block YAML refuses is unparsed whatever its cut reads: private to the owner of its notebook directory, Captain-only elsewhere. Reach: 0 of 2,776 documents on the live copy (R4, 2026-11-18). Decided by the Architect: a loss of access, not a weakened control (slice 4 G0); nothing migrated.
- *D4 (the writer).* `dump_frontmatter` checks its own text before the read-back load and refuses 64 levels or more with `ValueError`, naming keys and the limit; the callers' handling is unchanged (raise before any file is touched; the notebook route's 400). The check measures the text, so a self-referential mapping, written with an alias, is still written.
- *D5 (the guard).* The tests that run PyYAML's loader or representer to the recursion limit by design (six functions on this tree, from the census of section 16; the AD-1127 cyclic-metadata case with them, item bf-986 F3 of #1820) ask for BF-986's `gc_quiet_at_recursion_limit`: a collection in the last frames below the limit finalises a worker's pending event loop and fails the test (#1754, GATE-F1). The BF-940 slice 3 and slice 4 tests no longer reach the limit and are not guarded. Rejected: guarding every test that did on the base (a pin for a claim that no longer holds).
- *Residual.* L1 to L11 of the contract. *Reversal.* Revert the BF-970 commits.

### BF-935 -- A Scout run lists each repository once, however many of its topic searches return it (2026-11-11, #1674)
```

**Ledger.** Run G3.
- Neither heading holds a word `gen_ad_ledger.py` reads (`scripts/gen_ad_ledger.py:126-132`: retired, abandoned, withdrawn, superseded, deferred, postponed, closed, shipped, staged, landed, open). The DECISIONS heading therefore records `shipped` and the PROGRESS head records `mentioned`, as BF-980's did.
- Do not edit the roadmap Bug Tracker: it holds no BF-9xx row.

## 8. Tests (`tests/test_bf970_frontmatter_reading.py`, 12 cases with libyaml)

| Id | Case | Proves | On the base, first failing line |
|---|---|---|---|
| T1 | the A1 document through every reader and the three seams | Acceptance 1 | `assert await store.read_entry(path, reader_id="bob") is None` (the base returns it as `ship`) |
| T2 | bob's scores with and without the A1 note | the first pass does not read the cut (R2) | `assert await _scores(store, "bob") == expected` |
| T3 | a tab block whose cut loads, both loaders | the second reading does not read the cut (R3) | `assert await _found(store, "bob") == ["reports/open.md"]` (SafeLoader loop) |
| T4 x2 | 63 and 64 levels, flow and block, every reader from 50 frames | Acceptance 2 | `assert await _padded(50, lambda: store.read_entry(refused, reader_id="bob")) is None` |
| T5 | a corpus with 400-level and limit-level blocks, both loaders | Acceptance 3 | the bob line (400 loads) or the Captain line (`RecursionError` withheld) |
| T6 x2 | the check from 40 frames left, siblings, parse error, `[]` | D2, D3 | line 1: `AttributeError` (the new name) |
| T7 | `dump_frontmatter` at 63 and 64, a self-reference | Acceptance 4, D7 | `with pytest.raises(ValueError)`: DID NOT RAISE |
| T8 | `write_entry` 64 refused before the file, 63 round-trips | D7 | `with pytest.raises(ValueError)`: DID NOT RAISE |
| T9 x2 | alias chain and doubling graph | D2: aliases open nothing; bounded time | passes (guard) |

**Rewritten in place**, each with its reason inline:
- framing: T-F1..T-F11 (`_oracle`, F1's note, the tab note, T8 row 2, T9's count 2,200, the A1 rows);
- s4: T-4-2 (cut-only note), T-4-3 (the readers from any stack: on the base, `RecursionError` at the limit row), T-4-4 (one load: on the base 3 loads);
- bf952: T-K1..T-K5;
- s2 dump: T-D1;
- s3: T-R1..T-R9;
- split: T-S1 (docstring only).

**Parity tests that must pass unchanged in G1:**
- BF-679: `test_bf679_oracle_records_reader_identity.py::TestPathParity` (`:234`; 5 cases from `:237`).
- BF-952:
  - `test_every_document_reads_as_on_the_base` (`:508`, the 1,359 non-reframed shapes);
  - `test_every_reader_frames_and_loads_a_document_alike` (`:307`);
  - `test_a_frontmatter_libyaml_cannot_load_reads_as_on_the_base` (`:568`).
- BF-940:
  - `test_every_document_of_the_grid_reads_by_the_rule` (rewritten count);
  - s4's class (`:321`);
  - s4 `test_a_constructor_error_is_refused_to_every_reader_as_before` (`:162`);
  - BF-952 `test_a_record_whose_frontmatter_cannot_be_constructed_is_withheld_not_raised` (`:382`).

**The 2,200 is derived, not measured.** The BF-940 contract's D7 says A1 "moves 90 back and no other" (`prompts/bf-940-frontmatter-closing-line.md:130`), and T9's docstring calls them "90 of the 2,200 that M2 changed". A different measured count is a hard stop for the Architect.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M1's head)

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| R1 | records_store | `frontmatter, unparsed = load_frontmatter(block)` (in `_load_document`) | append `; cut, cut_rest = base_split_frontmatter(raw); cut_fm = load_frontmatter(cut)[0] if unparsed and cut is not None else None; (frontmatter, rest, unparsed) = (cut_fm, cut_rest, False) if cut_fm else (frontmatter, rest, unparsed)`, the A1 clause `_parse_document` held, with the import restored | **T1** (the issue's: restoring A1), framing T-F4/T-F10/T9, s4 T-4-2 |
| R2 | records_store | `frontmatter, unparsed = _search_read_frontmatter(block)` | the same A1 clause, with `_search_read_frontmatter(cut)` | **T1** (`_search_read_document` line), **T2**, framing T9 |
| R3 | records_store | `frontmatter, unparsed = load_frontmatter(block)  # read_entry's reading (yaml.SafeLoader)` | append `; frontmatter, unparsed = (load_frontmatter(block.partition("---")[0])[0], False) if unparsed and load_frontmatter(block.partition("---")[0])[0] else (frontmatter, unparsed)` | **T1** (`_base_reading_admits` line), T3 (libyaml) |
| R4 | utils | `if frontmatter_nests_too_deep(block, loader):` | `if False:` | **T4** (the issue's: removing the check), T5, T-K1, T-K2, T-K4, T-4-3 (limit row) |
| R5 | utils | `if depth >= FRONTMATTER_DEPTH_LIMIT:` | `if depth > FRONTMATTER_DEPTH_LIMIT:` | T4, T6, T7, T-K4 |
| R6 | utils | `FRONTMATTER_DEPTH_LIMIT = 64` | `FRONTMATTER_DEPTH_LIMIT = 100` | T6, T-K4, T4, T7 |
| R7 | utils | `return False  # a parse error before the limit: the load reads YAML's refusal` | `raise` | T6, T-K4, s4 class (`_BROKEN`) |
| R8 | utils | `if frontmatter_nests_too_deep(text):  # BF-970: checked before the read-back load, which recurses` | `if False:` | T7, T8 |
| R9 | utils | `if isinstance(exc, (_NestsTooDeep, RecursionError)):  # BF-970: what no reader loads is not written` | `if False:` | T7 (the limit in the message) |
| R10 | records_store | `_unparsed_gate(rel_path) if unparsed else frontmatter,` | `frontmatter,` | T2, s4 `:340` |
| R11 | records_store | `if unparsed else frontmatter` | `if False else frontmatter` | T1, T4, s4 class |
| R12 | records_store | `fm, _, unparsed = _load_document(raw)  # BF-940 slice 4 (L19), BF-970: the reading and its verdict, one load` | `fm, _, unparsed = _load_document(raw)[0], None, False` | T1, T4, s4 `:363`, `:374` |
| R13 | records_store | `if unparsed:` (in `publish`) | `if False:` | T1, T4, s4 `:392` |
| R14 | records_store | `if frontmatter:` (in `_search_read_frontmatter`) | `if True:` | T1, T4 (libyaml hosts; equivalent without libyaml: L10) |
| R15 | records_store | `if existing_unparsed:  # BF-940 slice 4 (L19): said, not refused (seed_manuals overwrites)` | `if False:` | T4, s4 `:401` |

**Guard rows (A1; script `mutants_b5guard.py`, run on the built candidate: M1, M3 and M4 applied).** Each row replaces the one `@pytest.mark.usefixtures("gc_quiet_at_recursion_limit")` line that sits directly above the named function with a comment line, and runs `tests/test_bf986_recursion_limit_gc_guard.py -k test_every_test_that_overflows` (10 cases unmutated, all passing). A row is killed only if exactly its own T8 case fails.

| # | File | Function | Killed by (T8 case id) |
|---|---|---|---|
| GR1 | `tests/test_bf940_s2_dump_frontmatter.py` | `test_a_mapping_nested_too_deeply_is_a_value_error_not_a_recursion_error` | `bf940-s2-dump-too-deep` |
| GR2 | `tests/test_bf952_records_keyword_search.py` | `test_a_frontmatter_nesting_64_collections_or_more_is_unparsed_in_both_readings` | `bf952-both-readings` |
| GR3 | `tests/test_bf952_records_keyword_search.py` | `test_a_deeply_nested_record_is_unparsed_in_every_reader` | `bf952-every-reader` |
| GR4 | `tests/test_bf952_records_keyword_search.py` | `test_parse_document_never_raises_recursion_error_for_nesting` | `bf952-parse-document` |
| GR5 | `tests/test_bf970_frontmatter_reading.py` | `test_a_search_over_a_corpus_holding_a_block_nested_400_deep_returns_the_other_records` | `bf970-search-400-deep` |
| GR6 | `tests/test_bf970_frontmatter_reading.py` | `test_the_nesting_check_answers_from_a_nearly_exhausted_stack_and_stops_at_the_limit` | `bf970-exhausted-stack` |
| GR7 | `tests/test_ad1127_crew_session_lifecycle_recovery.py` | `test_install_recovery_plan_rejects_hostile_metadata_before_await` | `ad1127-cyclic-metadata` |

Measured on the oracle (2026-11-19): all seven killed, each by exactly its own case. No row exists for the `_GUARDED` entry itself: deleting an entry leaves T8 green, which is BF-986's register entry R-1 (the pin protects the listed functions only).

**Campaign.**
- The R rows ran (orchestrator, `mutants_bf970.py`, on the first oracle, M1's head, with the new file, framing, s4, bf952, s2 dump and s3): killed 14, differs 1, survived 0, invalid 0. Every named killer failed in 14 rows. R14 was killed by 17 cases, T1 among them, and its second-listed case T4 did not fail (the table over-names it; there is no survivor). The M1 blobs of this build equal those of that run, so the campaign of record stands and a build whose files match its LF sha256 does not repeat it.
- It records the base tree, the LF sha256 of `records_store.py`, `utils/frontmatter.py` and the six test files, and the cases each mutant fails.
- Every mutant must be killed by at least its bold or first-listed case. A survivor is a hard stop for the Architect, except R14 without libyaml (record it).
- That run is the campaign of record. A later Builder whose files match those hashes does not repeat it.

## 10. What this does NOT change

These are untouched:
- `record_is_readable`, `effective_classification`, `_author_identity`, `_unparsed_gate`, `FRONTMATTER_UNPARSED_KEY`, `_CLASSIFICATION_LEVELS`;
- the scoring (`_search_record_counts`, BM25, ranking), `_markdown_files`, the BF-958/959 containment;
- `split_frontmatter`, `base_split_frontmatter`;
- `semantic.py` (backfill and filter), `routers/records.py`, the skill catalog's readers (`parse_skill_file`, `_rewrite_frontmatter`'s load);
- config, schema, events, the Ward Room, dreaming, `knowledge/store.py`, the roadmap.

No document on disk is rewritten. No dependency is added. OSS only.

## 11. Recorded limits

- **L1.** A document nesting 64 to about 330 levels, which PyYAML read, is now unparsed; one nesting 64 to 99 levels, which libyaml read for the search, likewise. Measured: 0 (R4).
- **L2.** A load below 64 levels needs about 200 frames above its caller. A caller with fewer left still raises `RecursionError`, from this or any code. That is not a nesting property.
- **L3 (kept from BF-940 slice 4).** Semantic index rows written earlier for a document that BF-970 makes unparsed stay until the record is next written (an A1 shape, or one 64 to 99 deep). Measured: 0 such documents on the live copy.
- **L4 (kept: slice 4 L11, L7).** The search's first pass keeps libyaml, so a block only libyaml reads (a tab after a key) can be read differently by the two readings.
- **L5.** A PyYAML reader now parses each block twice: the check, then the load (`read_entry`, `list_entries`, `publish`, update-in-place, `_base_reading_admits` per returned record, and the search on a host without libyaml). Not measured; the recorded measurement (section 5) goes in the PR. The libyaml first pass costs what it did.
- **L6.** The skill catalog reads SKILL.md with its own `yaml.safe_load` (no depth check; `parse_skill_file` catches only `YAMLError`). Its rewrite now refuses 64 levels or more while its read accepts more (register R1).
- **L7.** The scans (`check_notebook_similarity`, `check_cross_agent_convergence`) read through `_parse_document` and see `{}` for an unparsed note, as before.
- **L8.** An alias builds a value deeper than its text: AD-1341 S5's 5,000-link chain loads as before. Walkers of the loaded value keep their own guards (the routes' JSON check, BF-940 slice 3; archive promotion, F-661).
- **L9.** Two shapes move from a raise to unparsed: an A1 shape whose cut raised a constructor error, and a 64-level block holding a constructor error. Measured: 0.
- **L10.** Without libyaml, T3 and R14 do not discriminate. The libyaml check was not run here (M0-4).
- **L11.** A vessel that differs from R4 (non-zero A1 or deep counts) gets the same behaviour: those documents become private to their notebook owner, or Captain-only outside `notebooks/`. Nothing is migrated. The counts by top-level directory and the paths, never values, go in the PR and on #1820 for the Captain's repair. A non-zero count is not a stop.

## 12. Verified Against Codebase (2026-11-19, scratch tree at `7ca49126`)

```
git log -1 -> 7ca49126 Merge pull request #1833 (AD-1361)
git rev-parse HEAD:<path> -> section header blobs
records_store.py:20    from probos.utils.frontmatter import base_split_frontmatter, dump_frontmatter, split_frontmatter
records_store.py:110   FRONTMATTER_UNPARSED_KEY = "frontmatter_unparsed"
records_store.py:136   def _unparsed_gate(rel_path: str) -> dict[str, Any]:
records_store.py:205   doc_class = effective_classification(frontmatter.get("classification", "ship"))
records_store.py:277   _RECORDS_YAML_LOADER: Any = yaml.CSafeLoader if ... else yaml.SafeLoader
records_store.py:281   _SEARCH_LIBYAML_DEPTH_LIMIT = 100
records_store.py:311   def _load_frontmatter(block: str) -> Any:
records_store.py:324   def _block_unparsed(block: str) -> bool:
records_store.py:338   def _frontmatter_unparsed(raw: str, frontmatter: Any) -> bool:
records_store.py:361   yaml.safe_load(block)  # F1: loaded here, in this frame, ...
records_store.py:367   def _nests_below(block: str, limit: int) -> bool:
records_store.py:387   def _search_load_frontmatter(block: str) -> Any:
records_store.py:395   if _RECORDS_YAML_LOADER is yaml.SafeLoader or not _nests_below(block, _SEARCH_LIBYAML_DEPTH_LIMIT):
records_store.py:404   def _search_read_document(raw: str) -> tuple[Any, str, str | None]:
records_store.py:417-421 A1 in the search's first pass (base_split_frontmatter)
records_store.py:425   def _base_reading_admits(
records_store.py:441   frontmatter = _load_frontmatter(block.partition("---")[0]) or frontmatter   (A1)
records_store.py:521-529 the walk's try around _search_read_document
records_store.py:541-542 record_is_readable(_unparsed_gate(rel_path) if _frontmatter_unparsed(raw, frontmatter) else frontmatter,   (outside the try)
records_store.py:586   if block is not None and not _base_reading_admits(
records_store.py:850-851 existing_fm, _ = self._parse_document(existing_raw); if _frontmatter_unparsed(...)
records_store.py:869   except Exception:  (update-in-place)
records_store.py:890   fm_yaml = dump_frontmatter(frontmatter)
records_store.py:958   async def seed_manuals(self, source_dir: Path) -> int:   (calls write_entry :973)
records_store.py:1013  fm_yaml = dump_frontmatter(frontmatter)   (captain's log)
records_store.py:1198, 1271, 1289, 1379, 1400  self._parse_document(raw)   (scans)
records_store.py:1544  frontmatter, content = self._parse_document(raw)   (read_entry)
records_store.py:1551  if _frontmatter_unparsed(raw, frontmatter) else frontmatter
records_store.py:1623-1624 fm, _ = self._parse_document(raw); unparsed = _frontmatter_unparsed(raw, fm)
records_store.py:1646  entry[FRONTMATTER_UNPARSED_KEY] = True
records_store.py:1692-1695 publish: _parse_document; if _frontmatter_unparsed(raw, fm): raise ValueError
records_store.py:1703  fm_yaml = dump_frontmatter(fm)   (publish)
records_store.py:1780  return await asyncio.to_thread(_search_records, ...)
records_store.py:1887  def _parse_document(self, raw: str) -> tuple[dict, str]:
records_store.py:1902-1909 A1 in _parse_document
utils/frontmatter.py:23  def split_frontmatter; :39 return base_split_frontmatter(text) (L18); :42 def base_split_frontmatter
utils/frontmatter.py:56  _UNWRITABLE = (yaml.YAMLError, RecursionError); :59 def _dump; :66 def dump_frontmatter
semantic.py:21, 729, 740, 746  FRONTMATTER_UNPARSED_KEY import; records_store.list_entries(); the unparsed filter
semantic.py:767        records_store.read_entry(path, reader_id=_UNRESTRICTED_READER)
skill_catalog.py:107, 113, 177, 785, 790, 808  split_frontmatter / yaml.safe_load / dump_frontmatter
proactive.py:3453-3461 write_notebook(..., tags=[topic_slug], metrics=_nb_metrics ...); :4509-4516; :4526-4531 except: logger.warning
routers/records.py:205-216 write_notebook ... except ValueError: 400
voice/proposal.py:52-62 _max_depth (post-load, recursive)
tests: test_bf940_s4:316, :463-464 (_frontmatter_unparsed); :495-496, :536-537 (_RECORDS_YAML_LOADER)
tests: test_bf952:317, :341, :344, :541 (_search_read_document, _base_reading_admits); :732 (_search_load_frontmatter); :765-767 (_SEARCH_LIBYAML_DEPTH_LIMIT, _nests_below); :792-798 (frontier); :802-821 (delegation)
tests: test_bf940_frontmatter_framing:79-98 (_oracle A1), :221-239, :242-257, :296-300, :329-340 (2,110), :342-361
tests: test_bf940_split_frontmatter:9, :67, :70-78 (base_split_frontmatter, U4)
tests: test_bf940_s2_dump_frontmatter:89-93 (_nested(100) written)
tests: test_bf940_s3_route_serialisation:100-110 (derived limits), :116-122 (_UNWRITABLE), :220-236, :251, :292-306, :314, :323
tests: test_ad1341_s5_after_action_format:288-301 (alias chain 5,000, doubling 22)
tests: test_bf679_oracle_records_reader_identity:234 class TestPathParity
docs/development/deterministic-ship.md:49 "... unless the base's earlier cut of it parses and it reads as that (#1686) ..."
DECISIONS.md:1377, :1628, :1659 (residual lines, each unique); :1661 ### BF-935
PROGRESS.md:1 # ProbOS Progress (one occurrence)
scripts/gen_ad_ledger.py:126-132 status words
scripts/ad_ceiling.py -> CEILING AD-1361 (prompts/ad-*.md), NEXT AD-1362
gh issue list "BF-970 in:title" -> #1801 OPEN only
```

**Absence Verified (2026-11-19).**
```
CLAIM: no reader of a document's frontmatter outside records_store and the skill catalog frames or loads it itself
RUN:   Grep "split_frontmatter|dump_frontmatter|_parse_document|FRONTMATTER_UNPARSED_KEY|_unparsed_gate|..." src (excluding records_store.py);
       Grep "yaml\.safe_load|yaml\.load\(|yaml\.parse\(" src/probos
FOUND: semantic.py (the key only), utils/frontmatter.py (definitions), skill_catalog.py:22,107,177,785,808, publish_finding_tool.py:32 (a docstring);
       safe_load elsewhere reads config, profiles, SOPs, voice and doctor files; routers/gaps.py:34 and commands_gap.py:64 read a gap report's *body*
POSITIVE CONTROL: records_store.py:319,332,361,375,398,1899,1905 are found by the same patterns
HOLDS: yes -- the Ward Room, knowledge/store.py and dreaming call no split_frontmatter and load no record frontmatter

CLAIM: dump_frontmatter has four callers and the note-taker is not one
RUN:   Grep "dump_frontmatter" src; Grep "records|write_entry|write_notebook|ValueError" src/probos/agents/utility/organizer_agents.py
FOUND: records_store.py:890, 1013, 1703; skill_catalog.py:808; organizer_agents.py: no match
HOLDS: yes

CLAIM: the new names are free
RUN:   Grep "\bload_frontmatter\b|frontmatter_nests_too_deep|FRONTMATTER_DEPTH_LIMIT|_search_read_frontmatter|_NestsTooDeep|test_bf970" repo; Grep "_load_document" repo
FOUND: none in src or tests (`_read_document` appears only in prompts/bf-952-*.md, the name A6 deleted, so it is not reused)
HOLDS: yes

CLAIM: no docs file pins a moved symbol; no test pins deterministic-ship.md's text
RUN:   Grep the six removed names and base_split_frontmatter in docs/; Grep "earlier cut|deterministic-ship" tests/
FOUND: 0; 0
HOLDS: yes

CLAIM: the roadmap Bug Tracker holds no BF-9xx row for this family
RUN:   Grep "\| BF-9(66|69|80|83|40|52) " docs/development/roadmap.md
FOUND: none
HOLDS: yes
```

**Read, not run.**
- No test was run, no block applied and no hash of a patched file computed.
- The base-failure lines (section 8), the killers (section 9) and the 2,200 are from reading the code; M0-2, G1 and the campaign confirm them.
- I did not read the live records (R4 is the orchestrator's replay).

**A1 re-verification (the orchestrator, 2026-11-19 and 2026-11-20, scratch tree `ob970c` at `ebaa9729`, whose tree `718b0b0f88d0936e1d16bb1dc32bd3730fdf1684` is the tree of `origin/main` `3137575a` after BF-987).** This is what was run, not read.
- M0-1: `git diff --stat 7ca49126 ebaa9729 -- <the nine files>` is empty (control: the same diff over `PROGRESS.md` is 9 lines).
- The slices apply by tool with 0 failures: M1 53 pairs and the new file, M3 8 pairs, M4 3 pairs, M2 5 pairs. The ten code, test and doc blobs of M1 equal those of the first oracle (`ob970`, built on `7ca49126`): `records_store.py` `e47a406f`, `frontmatter.py` `8bb0e85e`, framing `acdc25c3`, s2 `5ffd1018`, s3 `8bd6d56d`, s4 `e11f3765`, split `0bf984c9`, bf952 `6739ccbf`, the new file `6ec30c54`, `deterministic-ship.md` `ccead2d4`.
- The census of section 16.1 (314 passed, 8 rows) and gates G4 and G5 on the built tree (131 passed, T8 with 10 cases); the guard rows GR1 to GR7 (section 9): 7 of 7 killed, each by exactly its own case.
- G0 on a scratch tree of the base plus the M1 text of the new file alone (`ob970r`): 10 failed, 2 passed (the two T9 guards), each failure at the line section 8 names. G1 on the built tree (`ob970c`): **565 passed** in 243.84 s.

## 13. Prior Art and Blind Spots

- **Internal.**
  - Adopted: BF-952's `_nests_below` (event-stream counting, generalised to every reader with its own loader) and BF-940 slice 4's stand-in.
  - Rejected for reuse: AD-718a's `_max_depth` (`voice/proposal.py:52-62`), because it runs after the recursive load and recurses itself.
  - Kept as a guard: AD-1341 S5's alias graphs (T9).
- **External** (2 of 5 searches used).
  - **Adopted: a nesting limit on collections, counted before composition, as a loader option.** SnakeYAML added `nestingDepthLimit` (default 50) for CVE-2022-25857 ([NVD](https://nvd.nist.gov/vuln/detail/CVE-2022-25857), [Snyk](https://snyk.io/vuln/SNYK-JAVA-ORGYAML-2806360)). Same shape, applied at 64, the limit the issue sets.
  - **Considered, not usable:** libyaml's `yaml_set_max_nest_level` (default 1000; [Yams PR 431](https://github.fontlos.workers.dev/jpsim/Yams/pull/431)). PyYAML does not expose it, it is far above 64, and it may postdate 0.2.5 ([libyaml Changes](https://kernelsources.org/source/download/freebsd/contrib/libyaml/Changes)).
  - `docs/research/reference-projects.md` lists no YAML or markdown project, so none was examined (date used: 2026-11-19).
- **Blind spots handled:**
  - the route tests that read beyond the JSON writer's limit (s3: rewritten);
  - alias graphs (T9);
  - a self-referential dump (T7);
  - the search's worker thread (D3);
  - stale index rows (L3);
  - the skill catalog asymmetry (L6, register R1);
  - the A1 shapes whose cut raised (L9);
  - libyaml's own nest limit.
- **What discards a correct result?**
  - A legitimate frontmatter 64 levels or deeper, which no writer can now produce, is unparsed and withheld (L1, measured 0).
  - A legitimate `publish` of a 63-level note writes back at 63 and passes (T4 shallow path).
  - A correct libyaml reading of an ordinary block is kept (D5).

## 14. Diff Reviewer: properties to verify

1. **One reading.**
   - In `records_store.py` no reader loads YAML itself: no `yaml.safe_load(` or `yaml.load(` remains; every load is `load_frontmatter`.
   - `read_entry`, `list_entries`, `publish` and update-in-place take `unparsed` from `_load_document`, and `_parse_document` delegates to it.
   - `base_split_frontmatter` is not imported in `records_store.py`.
2. **The check.**
   - `frontmatter_nests_too_deep` counts only `CollectionStartEvent`/`CollectionEndEvent`, returns True at `depth >= 64`, and catches only `yaml.YAMLError` (returning False).
   - It builds no node and follows no alias.
   - `load_frontmatter` runs it with the same `loader` it loads with, before the load.
3. **The exception contract.**
   - `load_frontmatter` catches only `yaml.YAMLError` around the load, so a constructor `ValueError` propagates.
   - The walk's verdict uses the first pass's `unparsed`, inside the existing `try`.
   - `_base_reading_admits` keeps its `except Exception` -> `False`.
4. **The search.**
   - libyaml's reading stands only where it is truthy; otherwise `load_frontmatter(block)` (PyYAML) decides.
   - The second reading uses `load_frontmatter(block)` with `SafeLoader` and the stand-in.
   - Scoring, ranking and `_SEARCH_LIMIT` are byte-identical.
5. **The writer.**
   - `_dump` checks its own text before the read-back `safe_load`.
   - The new message names keys and `FRONTMATTER_DEPTH_LIMIT`, never a value.
   - The old message path is unchanged for every other error.
6. **Docstrings** say what the code does. No text in `src/` still says a reader reads the base's cut, that a load must stay in its caller's frame, or that the search's limit is 100. Check: `rg -n "A1|in this frame|_SEARCH_LIBYAML" src/probos/knowledge/records_store.py src/probos/utils/frontmatter.py` finds only the BF-952 and slice 2 A1s (different amendments) and the BF-970 "is gone" notes.
7. **Tests.**
   - Each rewritten case keeps its slot and states its reason inline.
   - Each new case asserts its premise before its effect.
   - `_UNWRITABLE` indices in s3 match the rows left (bytes 0, holds-itself 1, surrogate 2).
   - No test was deleted except the helpers its rewrite made unused (s4 `_frontier`, `_never`; bf952 `_frontier`).
8. **Trackers.** Neither heading holds a ledger status word, `gen_ad_ledger.py --check` is clean, and the ledger pair is committed with M2.
9. **The guard (A1, M3 and M4).**
   - Each of the seven functions of sections 16 and 17 carries `@pytest.mark.usefixtures("gc_quiet_at_recursion_limit")` directly above its `def`, no other decorator changed, and `_GUARDED` and the ids list of T8 name those seven after BF-986's three, in the same order.
   - With an AST walk of your own over `tests/test_bf940_*.py`, `tests/test_bf952_*.py`, `tests/test_bf970_frontmatter_reading.py` and `tests/test_ad1127_crew_session_lifecycle_recovery.py` (positive control: BF-986's three functions in their two files), list every test function that carries the marker and compare it with `_GUARDED`. Section 16.1 is the evidence that no other function in the BF-940, BF-952 and BF-970 files reaches the limit on the built tree.
   - M4 changes only the AD-1127 test file and the two `_GUARDED` lines; the function's other two cases (`subclass`, `scalar`) run guarded and no assertion of the test changed.

## 15. Acceptance criteria

- G0 to G5 pass as stated (A1 adds G4 and G5), and the batch's broad gate is green with a receipt.
- **The issue's list:**
  - the A1 document is unparsed in `read_entry`, the search and `list_entries` (T1, T2, T3); restoring A1 in `_parse_document`'s reading fails T1 (R1);
  - a 64-level block is unparsed in every reader from 50 extra frames, and a 63-level block loads (T4); removing the check fails T4 (R4);
  - a search over a corpus holding a 400-level block returns the other records (T5);
  - `dump_frontmatter` refuses a 64-level mapping (T7, T8);
  - the BF-940, BF-952 and BF-679 parity tests pass (section 8).
- **The PR states R4:** 7,650 files, 2,776 markdown; all 2,776 have a block that loads and carry `classification:`; A1-affected 0 (refused by YAML 0; key after the cut 0); nesting 64 or more 0; libyaml depth-unparseable 0; controls pass. It also states the behaviour change (section 3, D6) and the L5 timing.
- **A1 (the guard):** the census of section 16.1, rerun on the built tree, shows every row in a guarded function and every guarded function with a row; T8 runs 10 cases; the PR body names item bf-986 F3 of #1820 and says that M4 touches `tests/test_ad1127_crew_session_lifecycle_recovery.py`, and why (BF-986's census, the Architect's decision of 2026-11-19).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Amendment A1, M3: the guard on the tests that still run to the limit (BF-986's section 8.3)

BF-986 (PR #1835) added the fixture `gc_quiet_at_recursion_limit` (`tests/fixtures/recursion_limit_gc.py`, offered to every test by `tests/conftest.py`) and ordered its census (#1754, `issuecomment-7023353069`). Its section 8.3 says what this prompt does: guard the S2 test and every test function the census still records on the built tree, append each to `_GUARDED` in `tests/test_bf986_recursion_limit_gc_guard.py` with an id, and update the T8 pins. The Architect confirmed the rule (consult `a8c5e319`): only the functions that still reach the limit, the S2 test unconditionally.

### 16.1 The census of this tree (measured 2026-11-19, oracle `ob970c`, M1 and M2 applied)

The BF-986 census plugins (`census_plugin`, `raise_census2`; a `sys.monitoring` RAISE callback that records the deepest Python stack of the first `RecursionError`) ran over the eight files `tests/test_bf940_*.py`, `tests/test_bf952_*.py` and `tests/test_bf970_frontmatter_reading.py`: 314 passed, all five processes ended normally, 8 rows (a row is a first `RecursionError` within 50 frames of the limit; every one was 1,000 of 1,000), no shallow node, no loop record.

| Function (rows) | Why it reaches the limit |
|---|---|
| `test_bf940_s2_dump_frontmatter.py::test_a_mapping_nested_too_deeply_is_a_value_error_not_a_recursion_error` (1) | `dump_frontmatter` calls `safe_dump` on the 600-level mapping before its own depth check, and PyYAML's representer recurses to the limit |
| `test_bf952_records_keyword_search.py::test_a_frontmatter_nesting_64_collections_or_more_is_unparsed_in_both_readings` (2: `block-past-the-base-recursion`, `flow-past-the-base-recursion`) | its premise reads the 600-level block the base's way, with `yaml.safe_load` |
| `test_bf952_records_keyword_search.py::test_a_deeply_nested_record_is_unparsed_in_every_reader` (1: `past-the-base-recursion`) | the same premise |
| `test_bf952_records_keyword_search.py::test_parse_document_never_raises_recursion_error_for_nesting` (1) | its premise reads a block as deep as the limit the base's way |
| `test_bf970_frontmatter_reading.py::test_a_search_over_a_corpus_holding_a_block_nested_400_deep_returns_the_other_records` (1) | its premise loads a block as deep as the limit with `yaml.safe_load` (T5) |
| `test_bf970_frontmatter_reading.py::test_the_nesting_check_answers_from_a_nearly_exhausted_stack_and_stops_at_the_limit` (2: `CSafeLoader`, `SafeLoader`) | its premise loads a 63-level block from 40 frames below the limit (T6) |

On the base the same census had 11 rows in the BF-940 and BF-952 files. The five BF-940 slice 3 and slice 4 nodes (`test_bf940_s3_route_serialisation.py::test_a_record_beyond_the_readers_own_limit_keeps_its_answers`; `test_bf940_s4_unparsed_frontmatter.py`: the four cases of `test_a_reader_parses_a_document_as_deeply_nested_as_it_did_before_the_verdict` and `TestADocumentWhoseFrontmatterDoesNotLoadIsPrivateToItsOwner::test_the_verdict_loads_the_block_as_deeply_nested_as_the_parse_the_caller_has_just_run`) no longer reach it, because the readers no longer lean on PyYAML's `RecursionError`. They are not guarded: a guard on them would pin a claim that is false. The S2 test still reaches it, as the Architect's section 8.3 predicts, and is guarded unconditionally.

The Builder does not rerun the census. After M1 and M3 the orchestrator reruns it on the built tree (G4): every row must be a guarded function, and every guarded function must show a row.

### 16.2 Blocks (apply after M1; one SEARCH once in its file)

**G-1.** `tests/test_bf940_s2_dump_frontmatter.py`. The S2 test, above its `def`.
SEARCH:
```
def test_a_mapping_nested_too_deeply_is_a_value_error_not_a_recursion_error():
```
REPLACE:
```
@pytest.mark.usefixtures("gc_quiet_at_recursion_limit")  # BF-970 (#1801): the 600-level write overflows PyYAML's representer before the depth check
def test_a_mapping_nested_too_deeply_is_a_value_error_not_a_recursion_error():
```

**G-2.** `tests/test_bf952_records_keyword_search.py`. The case that follows the `depth, style` parametrize list.
SEARCH:
```
def test_a_frontmatter_nesting_64_collections_or_more_is_unparsed_in_both_readings(tmp_path: Path, depth: int, style: str) -> None:
```
REPLACE:
```
@pytest.mark.usefixtures("gc_quiet_at_recursion_limit")  # BF-970 (#1801): its 600-level premise reads the base's way and overflows PyYAML's loader
def test_a_frontmatter_nesting_64_collections_or_more_is_unparsed_in_both_readings(tmp_path: Path, depth: int, style: str) -> None:
```

**G-3.** `tests/test_bf952_records_keyword_search.py`.
SEARCH:
```
async def test_a_deeply_nested_record_is_unparsed_in_every_reader(
```
REPLACE:
```
@pytest.mark.usefixtures("gc_quiet_at_recursion_limit")  # BF-970 (#1801): its 600-level premise reads the base's way and overflows PyYAML's loader
async def test_a_deeply_nested_record_is_unparsed_in_every_reader(
```

**G-4.** `tests/test_bf952_records_keyword_search.py`.
SEARCH:
```
def test_parse_document_never_raises_recursion_error_for_nesting(tmp_path: Path) -> None:
```
REPLACE:
```
@pytest.mark.usefixtures("gc_quiet_at_recursion_limit")  # BF-970 (#1801): its premise reads a block as deep as the limit the base's way and overflows PyYAML's loader
def test_parse_document_never_raises_recursion_error_for_nesting(tmp_path: Path) -> None:
```

**G-5.** `tests/test_bf970_frontmatter_reading.py`. T5.
SEARCH:
```
async def test_a_search_over_a_corpus_holding_a_block_nested_400_deep_returns_the_other_records(store, monkeypatch):
```
REPLACE:
```
@pytest.mark.usefixtures("gc_quiet_at_recursion_limit")  # BF-970 (#1801): its premise loads a block as deep as the limit with PyYAML and overflows its loader
async def test_a_search_over_a_corpus_holding_a_block_nested_400_deep_returns_the_other_records(store, monkeypatch):
```

**G-6.** `tests/test_bf970_frontmatter_reading.py`. T6, below its `loader` parametrize line.
SEARCH:
```
def test_the_nesting_check_answers_from_a_nearly_exhausted_stack_and_stops_at_the_limit(loader):
```
REPLACE:
```
@pytest.mark.usefixtures("gc_quiet_at_recursion_limit")  # BF-970 (#1801): its premise loads a 63-level block from 40 frames below the limit, and the check runs there
def test_the_nesting_check_answers_from_a_nearly_exhausted_stack_and_stops_at_the_limit(loader):
```

**G-7.** `tests/test_bf986_recursion_limit_gc_guard.py`. The list T8 reads: six entries after BF-986's three.
SEARCH:
```
    ("tests.test_bf904b_sealed_core_observation", "test_a_policy_that_cannot_be_read_observes_nothing_and_the_build_commits"),
)
```
REPLACE:
```
    ("tests.test_bf904b_sealed_core_observation", "test_a_policy_that_cannot_be_read_observes_nothing_and_the_build_commits"),
    ("tests.test_bf940_s2_dump_frontmatter", "test_a_mapping_nested_too_deeply_is_a_value_error_not_a_recursion_error"),
    ("tests.test_bf952_records_keyword_search", "test_a_frontmatter_nesting_64_collections_or_more_is_unparsed_in_both_readings"),
    ("tests.test_bf952_records_keyword_search", "test_a_deeply_nested_record_is_unparsed_in_every_reader"),
    ("tests.test_bf952_records_keyword_search", "test_parse_document_never_raises_recursion_error_for_nesting"),
    ("tests.test_bf970_frontmatter_reading", "test_a_search_over_a_corpus_holding_a_block_nested_400_deep_returns_the_other_records"),
    ("tests.test_bf970_frontmatter_reading", "test_the_nesting_check_answers_from_a_nearly_exhausted_stack_and_stops_at_the_limit"),
)
```

**G-8.** `tests/test_bf986_recursion_limit_gc_guard.py`. The ids of the T8 cases, one per entry of `_GUARDED`, in its order.
SEARCH:
```
@pytest.mark.parametrize(
    ("module", "name"), _GUARDED, ids=["ad1197-outbound", "ad1197-inbound", "bf904b-unreadable-policy"],
)
```
REPLACE:
```
@pytest.mark.parametrize(
    ("module", "name"),
    _GUARDED,
    ids=[
        "ad1197-outbound", "ad1197-inbound", "bf904b-unreadable-policy",
        "bf940-s2-dump-too-deep", "bf952-both-readings", "bf952-every-reader", "bf952-parse-document",
        "bf970-search-400-deep", "bf970-exhausted-stack",
    ],
)
```

### 16.3 What M3 does not change

- The fixture, `tests/conftest.py`, the nested-pytest doubles and T1 to T7 of `tests/test_bf986_recursion_limit_gc_guard.py`; the bodies of the guarded tests; the BF-940 slice 3 and slice 4 tests.
- The count in BF-986's own tracker entries ("11 nodes") stays as BF-986 wrote it. With M3 and M4 the guard covers ten functions: BF-986's three (11 nodes), these six (15 nodes: 1, 8, 2, 1, 1 and 2) and the AD-1127 function of section 17 (3 nodes).

## 17. Amendment A1, M4: item bf-986 F3 of #1820 (the AD-1127 cyclic-metadata test)

The census of BF-986 (#1754, `issuecomment-7023353069`) found one row outside the BF-940 and BF-952 files: `tests/test_ad1127_crew_session_lifecycle_recovery.py::test_install_recovery_plan_rejects_hostile_metadata_before_await[cycle]`, 1,000 of 1,000 frames. Its dict contains itself, so the recursion runs to the limit, and `_detach_plan_inserts` (`src/probos/cognitive/crew_session.py:1274-1300`) maps the `RecursionError` to the error the test asserts. BF-986's section 8.4 sends such a row to a follow-up item, and #1754's body is full, so it is item bf-986 F3 in #1820. The Architect decided that it rides in this batch as its own last code slice: the same `_GUARDED` list and T8 pins as M3, one broad gate, and the PR body names it. The guard goes on the whole function (T8 reads the function's `pytestmark`), so its other two cases (`subclass`, `scalar`) run guarded too, which costs one collection each.

**F-1.** `tests/test_ad1127_crew_session_lifecycle_recovery.py`. The marker goes between the parametrize line and the `def`.
SEARCH:
```
@pytest.mark.parametrize("malformed_kind", ["subclass", "cycle", "scalar"])
async def test_install_recovery_plan_rejects_hostile_metadata_before_await(
```
REPLACE:
```
@pytest.mark.parametrize("malformed_kind", ["subclass", "cycle", "scalar"])
@pytest.mark.usefixtures("gc_quiet_at_recursion_limit")  # BF-986 census (#1754), item bf-986 F3 of #1820: the cycle case recurses to the Python stack limit
async def test_install_recovery_plan_rejects_hostile_metadata_before_await(
```

**F-2.** `tests/test_bf986_recursion_limit_gc_guard.py`. One more entry, after M3's last.
SEARCH:
```
    ("tests.test_bf970_frontmatter_reading", "test_the_nesting_check_answers_from_a_nearly_exhausted_stack_and_stops_at_the_limit"),
)
```
REPLACE:
```
    ("tests.test_bf970_frontmatter_reading", "test_the_nesting_check_answers_from_a_nearly_exhausted_stack_and_stops_at_the_limit"),
    ("tests.test_ad1127_crew_session_lifecycle_recovery", "test_install_recovery_plan_rejects_hostile_metadata_before_await"),
)
```

**F-3.** `tests/test_bf986_recursion_limit_gc_guard.py`. Its id.
SEARCH:
```
        "bf970-search-400-deep", "bf970-exhausted-stack",
    ],
```
REPLACE:
```
        "bf970-search-400-deep", "bf970-exhausted-stack", "ad1127-cyclic-metadata",
    ],
```

After M4, `item bf-986 F3` of #1820 is ticked by the orchestrator after the merge (section 15), and only that item: #1820 stays open.

## 18. Amendment A2: review round 1 (gpt-6.1-sol), five findings repaired

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-20

Base: committed head `3ac41487` (tree `7daf8475`). Apply in the order given. Each SEARCH occurs exactly once in its file at its turn. LF line endings, ASCII only.

### 18.1 Decisions

- **A2-D1 (F1).** The search's stand-in for an unparsed document names its owner from the path the file resolves to. That is `read_entry`'s path (`_safe_path`, `:1482`), not the walk's lexical `rel_path`.
  - The first pass resolves only where `unparsed` is true. The second reading resolves each candidate it checks: it already runs a pure-Python PyYAML check and load per candidate, so one `Path.resolve` is small beside it.
  - `_resolved_rel_path` returns `None` on `OSError`, `RuntimeError` (a link loop) or `ValueError` (outside the repository). `None` withholds an unparsed record from every reader, the Captain included. This matches BF-952 A5: the search withholds what `read_entry` cannot answer.
  - The result's `"path"` and the ranking key stay lexical.
  - The seam already existed (BF-940 slice 4) for blocks YAML refuses. BF-970 widened it to blocks nesting 64 levels or more and to A1 shapes, so it is closed here.
- **A2-D2 (F2).** `enrich_skill` applies the update to a copy (`dataclasses.replace`) and rewrites SKILL.md from the copy. Only then does the cached entry (the same object) take the five fields. A rewrite `dump_frontmatter` refuses, or a value that fails to convert, leaves the cache, SKILL.md and SQLite unchanged.
  - Rejected: putting the catalog's readers on `load_frontmatter` (register R1; it changes what an import accepts).
- **A2-D3 (F3).** The listing window stays pinned by an alias chain. The reader's limit counts collections open in the text and an alias opens none, so a record the reader parses can load to a value the read route's body can hold and a listing's body, two levels deeper, cannot. The chain length is derived at import from the writer that runs.
- **A2-D4 (F4, F5).** Two docstrings are narrowed to `YAMLError`, and the catch is not widened. `_MARKER` is deleted.

### 18.2 Contract corrections (supersessions; the text above is not edited)

An appended amendment cannot carry SEARCH blocks against its own contract: each SEARCH text would then occur twice in the file. These statements therefore supersede the text above.

- **D4, first paragraph:** "and the check (a parse) cannot raise one" is replaced by:
  > and the check (a parse) raises one only where PyYAML's scanner does while the events are read: a double-quoted escape past U+10FFFF (`"\U00110000"`) raises `ValueError` from `chr()`. The check does not catch it, so it propagates from `load_frontmatter`, and each reader handles it as the table's constructor error, as the base did (L12).
- **D7, `enrich_skill` bullet:** "`enrich_skill` raises, and SKILL.md is untouched" is replaced by:
  > `enrich_skill` raises, and SKILL.md, its cached entry and SQLite are untouched (A2-D2).
- **Section 9:**
  - R10 is retired: its line no longer exists, and A2-M2 is its equivalent.
  - The campaign of record stands for R4-R9 only under the condition in 18.6.
  - R1-R3 and R11-R15 rerun on the A2 head, with A2-M1 to A2-M10.
- **Section 10:**
  - `_unparsed_gate` changes in its docstring only.
  - `enrich_skill` changes (A2-D2); `_rewrite_frontmatter` and the catalog's readers do not.
  - `routers/records.py` is unchanged; A2-M10 mutates it only to prove A2-T4.
- **Header and section 8 counts:** the new file holds 18 cases with libyaml (17 without). The s3 file gains one case and renames one.
- **New limits:**
  - **L12 (A2, F4).** An exception of PyYAML's parser that is not a `YAMLError` (the scanner's `ValueError` for `"\U00110000"`) propagates from `frontmatter_nests_too_deep` and `load_frontmatter`. `read_entry` and `publish` raise; `list_entries` and the search skip the document; `_base_reading_admits` returns False; update-in-place replaces it. This is the same on the base (measured in round 1). The catch is not widened, because a broad catch would read an unexplained parser fault as unparsed.
  - **L13 (A2, F1).** The search calls `Path.resolve` once per unparsed record in the first pass and once per candidate the second reading checks (at most the matched records; it stops at 20 returned). Not measured: retake the PR's cost measurement (listing, search, 120 records) on the A2 head.

### 18.3 Blocks: `src/probos/knowledge/records_store.py` (file order)

**A2-1.** `src/probos/knowledge/records_store.py`. `_unparsed_gate`'s docstring.
SEARCH:
```
    private document (:func:`record_is_readable`, :meth:`RecordsStore.read_entry`). ``rel_path`` is the document's path in the
    repository, as the walk of the search names it and as ``read_entry`` resolves it.
    """
```
REPLACE:
```
    private document (:func:`record_is_readable`, :meth:`RecordsStore.read_entry`). ``rel_path`` is the path the document resolves
    to in the repository, as ``read_entry`` resolves it, so a contained link takes its target's owner; BF-970 A2 (round 1 F1): the
    search names it so too (:func:`_resolved_rel_path`), not by the lexical path of its walk.
    """
```

**A2-2.** `src/probos/knowledge/records_store.py`. `_base_reading_admits`'s signature.
SEARCH:
```
def _base_reading_admits(
    block: str, *, scope: str, reader_id: str | None, reader_department: str, path: str,
) -> bool:
```
REPLACE:
```
def _base_reading_admits(
    block: str, *, scope: str, reader_id: str | None, reader_department: str, path: str | None,
) -> bool:
```

**A2-3.** `src/probos/knowledge/records_store.py`. Its docstring.
SEARCH:
```
    at once or more) the rules read the document's stand-in (:func:`_unparsed_gate` of ``path``, the document's path in the
    repository), as ``read_entry`` does. BF-940 A1 is gone: the base's cut is never read.
    """
```
REPLACE:
```
    at once or more) the rules read the document's stand-in (:func:`_unparsed_gate` of ``path``, the path the document resolves
    to in the repository), as ``read_entry`` does. BF-940 A1 is gone: the base's cut is never read. BF-970 A2 (round 1 F1): a
    ``path`` of ``None`` (the search could not resolve it) names no owner, so an unparsed block is withheld (fail closed); a
    parsed one does not read ``path``.
    """
```

**A2-4.** `src/probos/knowledge/records_store.py`. Its body.
SEARCH:
```
    if unparsed:  # BF-940 slice 4 (L19), BF-970: the same document read_entry withholds
        frontmatter = _unparsed_gate(path)
```
REPLACE:
```
    if unparsed:  # BF-940 slice 4 (L19), BF-970: the same document read_entry withholds
        if path is None:  # BF-970 A2 (round 1 F1): no owner can be named, so the document is withheld (fail closed)
            return False
        frontmatter = _unparsed_gate(path)
```

**A2-5.** `src/probos/knowledge/records_store.py`. `_search_records`: the readable list carries the file.
SEARCH:
```
    readable: list[tuple[str, dict[str, Any], str, dict[str, float], int, str | None]] = []
```
REPLACE:
```
    # BF-970 A2 (round 1 F1): each entry carries its file, so the second reading names an unparsed document's owner by the path
    # it resolves to; ``rel_path``, the walk's lexical path, stays the result's ``path`` and the ranking's last key.
    readable: list[tuple[str, dict[str, Any], str, dict[str, float], int, str | None, Path]] = []
```

**A2-6.** `src/probos/knowledge/records_store.py`. The first pass's gate.
SEARCH:
```
        # withholds more and never gives more (L11). BF-970: the verdict is the first pass's own, from inside the try above.
        if not record_is_readable(
            _unparsed_gate(rel_path) if unparsed else frontmatter,
            scope=scope,
            reader_id=reader_id,
            reader_department=reader_department,
        ):
            continue
        weights, length = _search_record_counts(frontmatter, content_text, terms)
        readable.append((rel_path, frontmatter, content_text, weights, length, block))
```
REPLACE:
```
        # withholds more and never gives more (L11). BF-970: the verdict is the first pass's own, from inside the try above.
        # BF-970 A2 (round 1 F1): the stand-in's owner comes from the path the document resolves to, as read_entry's does, so a
        # contained link under notebooks/bob/ to alice's unparsed note is alice's here too; resolved only where an owner is needed.
        gate = frontmatter
        if unparsed:  # BF-970 A2 (round 1 F1): only an unparsed document needs an owner
            resolved = _resolved_rel_path(md_file, repo)
            if resolved is None:  # BF-970 A2 (round 1 F1): no owner can be named, so the document is withheld (fail closed)
                continue
            gate = _unparsed_gate(resolved)
        if not record_is_readable(
            gate,
            scope=scope,
            reader_id=reader_id,
            reader_department=reader_department,
        ):
            continue
        weights, length = _search_record_counts(frontmatter, content_text, terms)
        readable.append((rel_path, frontmatter, content_text, weights, length, block, md_file))
```

**A2-7.** `src/probos/knowledge/records_store.py`. The ranking loop.
SEARCH:
```
    ranked: list[tuple[tuple[Any, ...], dict[str, Any], str | None]] = []
    for rel_path, frontmatter, content_text, weights, length, block in readable:
```
REPLACE:
```
    ranked: list[tuple[tuple[Any, ...], dict[str, Any], str | None, Path]] = []
    for rel_path, frontmatter, content_text, weights, length, block, md_file in readable:
```

**A2-8.** `src/probos/knowledge/records_store.py`. The second reading.
SEARCH:
```
            "snippet": content_text[:200],
        }, block))
    ranked.sort(key=lambda pair: pair[0])
    results: list[dict] = []
    for _, result, block in ranked:
        # A5 (round 5): a record is returned only where the base's reading of it, read_entry's and the
        # semantic index's, admits this reader too. A record with no frontmatter reads as {} for both.
        if block is not None and not _base_reading_admits(
            block, scope=scope, reader_id=reader_id, reader_department=reader_department, path=result["path"],
        ):
            continue
```
REPLACE:
```
            "snippet": content_text[:200],
        }, block, md_file))
    ranked.sort(key=lambda pair: pair[0])
    results: list[dict] = []
    for _, result, block, md_file in ranked:
        # A5 (round 5): a record is returned only where the base's reading of it, read_entry's and the
        # semantic index's, admits this reader too. A record with no frontmatter reads as {} for both.
        # BF-970 A2 (round 1 F1): its stand-in's owner comes from the path it resolves to (None: withheld if unparsed).
        if block is not None and not _base_reading_admits(
            block, scope=scope, reader_id=reader_id, reader_department=reader_department,
            path=_resolved_rel_path(md_file, repo),
        ):
            continue
```

**A2-9.** `src/probos/knowledge/records_store.py`. The new helper, after `_resolves_inside`.
SEARCH:
```
    try:
        return path.resolve().is_relative_to(repo)
    except RuntimeError:
        return False  # Path.resolve raised RuntimeError: a link loop resolves nowhere, so it is outside
```
REPLACE:
```
    try:
        return path.resolve().is_relative_to(repo)
    except RuntimeError:
        return False  # Path.resolve raised RuntimeError: a link loop resolves nowhere, so it is outside


def _resolved_rel_path(md_file: Path, repo: Path) -> str | None:
    """BF-970 A2 (round 1 F1): the path ``md_file`` resolves to, relative to ``repo`` (the resolved repository) with ``/``:
    the path ``read_entry`` names a document by (:meth:`RecordsStore._safe_path`), so the search's stand-in for an unparsed
    document (:func:`_unparsed_gate`) names the owner ``read_entry``'s does, and a contained link under ``notebooks/bob/`` to
    alice's note is alice's. ``None`` where it does not resolve inside ``repo`` now (a link loop, an ``OSError``, or a link moved
    outside since the walk checked it); the caller withholds an unparsed document then. Never raises."""
    try:
        return md_file.resolve().relative_to(repo).as_posix()
    except (OSError, RuntimeError, ValueError):  # fail closed: no owner can be named
        logger.debug("BF-970: the search cannot resolve %s inside the records repository", md_file, exc_info=True)
        return None
```

### 18.4 Blocks: `src/probos/utils/frontmatter.py`, `src/probos/cognitive/skill_catalog.py`

**A2-10.** `src/probos/utils/frontmatter.py`. `frontmatter_nests_too_deep`'s docstring (F4).
SEARCH:
```
    no node is built and no alias is followed. Siblings add no depth. A parse error before the limit is ``False``: the load that
    follows, with the same ``loader``, meets the same error below the limit and reads it as YAML's refusal.
    """
```
REPLACE:
```
    no node is built and no alias is followed. Siblings add no depth. A parse error before the limit, a ``YAMLError``, is
    ``False``: the load that follows, with the same ``loader``, meets the same error below the limit and reads it as YAML's
    refusal. BF-970 A2 (round 1 F4): any other exception of the parser propagates, as it does from the load: PyYAML's scanner
    raises ``ValueError`` for an escape past U+10FFFF (``"\\U00110000"``), and each reader handles it as a constructor's error
    (contract D4, L12).
    """
```

**A2-11.** `src/probos/utils/frontmatter.py`. `load_frontmatter`'s docstring (F4).
SEARCH:
```
    default loader that value is ``yaml.safe_load``'s. Any other error of the load propagates, as from ``yaml.safe_load``: a
```
REPLACE:
```
    default loader that value is ``yaml.safe_load``'s. Any other error of the check or the load propagates, as from ``yaml.safe_load``: a
```

**A2-12.** `src/probos/cognitive/skill_catalog.py`. The import.
SEARCH:
```
from dataclasses import dataclass, field
```
REPLACE:
```
from dataclasses import dataclass, field, replace
```

**A2-13.** `src/probos/cognitive/skill_catalog.py`. `enrich_skill` (F2).
SEARCH:
```
        # Apply metadata updates
        if "department" in metadata:
            entry.department = str(metadata["department"])
        if "skill_id" in metadata:
            entry.skill_id = str(metadata["skill_id"])
        if "min_proficiency" in metadata:
            entry.min_proficiency = int(metadata["min_proficiency"])
        if "min_rank" in metadata:
            entry.min_rank = str(metadata["min_rank"])
        if "intents" in metadata:
            entry.intents = list(metadata["intents"])

        # Rewrite SKILL.md frontmatter to include metadata block
        skill_md = entry.skill_dir / "SKILL.md"
        if skill_md.exists():
            self._rewrite_frontmatter(skill_md, entry)

        await self.register(entry)
```
REPLACE:
```
        # Apply metadata updates. BF-970 A2 (round 1 F2): to a copy, which SKILL.md is rewritten from; the cached entry, the same
        # object, takes them only after the rewrite succeeded, so a rewrite dump_frontmatter refuses (64 levels or more, a
        # ValueError) or a value that does not convert leaves the cache, SKILL.md and SQLite as they were.
        updated = replace(entry)  # BF-970 A2 (round 1 F2): the cache changes only after the rewrite
        if "department" in metadata:
            updated.department = str(metadata["department"])
        if "skill_id" in metadata:
            updated.skill_id = str(metadata["skill_id"])
        if "min_proficiency" in metadata:
            updated.min_proficiency = int(metadata["min_proficiency"])
        if "min_rank" in metadata:
            updated.min_rank = str(metadata["min_rank"])
        if "intents" in metadata:
            updated.intents = list(metadata["intents"])

        # Rewrite SKILL.md frontmatter to include metadata block
        skill_md = updated.skill_dir / "SKILL.md"
        if skill_md.exists():
            self._rewrite_frontmatter(skill_md, updated)

        for attribute in ("department", "skill_id", "min_proficiency", "min_rank", "intents"):
            setattr(entry, attribute, getattr(updated, attribute))  # BF-970 A2 (round 1 F2): the rewrite succeeded
        await self.register(entry)
```

### 18.5 Blocks: tests

**A2-14.** `tests/test_bf970_frontmatter_reading.py`. The catalog import.
SEARCH:
```
from probos.config import RecordsConfig
```
REPLACE:
```
from probos.cognitive.skill_catalog import CognitiveSkillCatalog
from probos.config import RecordsConfig
```

**A2-15.** `tests/test_bf970_frontmatter_reading.py`. A block YAML refuses whose text holds no `---`.
SEARCH:
```
_TAB_BLOCK = "a: x --- y\nnote:\tabc\n"
```
REPLACE:
```
_TAB_BLOCK = "a: x --- y\nnote:\tabc\n"
#: BF-970 A2 (round 1 F1): a block both loaders refuse (an unclosed flow list), with no ``---`` in it: unparsed since BF-940 slice 4.
_REFUSED_BLOCK = "author: alice\nclassification: ship\nbad: [unclosed\n"
```

**A2-16.** `tests/test_bf970_frontmatter_reading.py`. The alias helper, after `_alias_block`.
SEARCH:
```
    return "author: alice\nclassification: ship\n" + "\n".join(anchors) + f"\ngraph: *n{top}\n"
```
REPLACE:
```
    return "author: alice\nclassification: ship\n" + "\n".join(anchors) + f"\ngraph: *n{top}\n"


def _alias(monkeypatch: pytest.MonkeyPatch, link: Path, target: Path) -> None:
    """BF-970 A2 (round 1 F1): a contained alias, ``link`` resolving to ``target`` inside the repository (BF-958 lists and reads
    one). A real file link where the host can make one; where it cannot (WinError 1314, as in BF-958's tests), a stand-in: a copy
    of the target's bytes, which a link would read, and ``Path.resolve`` mapping ``link`` to ``target``, which a link would resolve
    to. The premise line holds for either."""
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target)
    except OSError as exc:
        if getattr(exc, "winerror", None) != 1314:  # ERROR_PRIVILEGE_NOT_HELD; anything else is the fixture's
            raise
        link.write_bytes(target.read_bytes())
        real_resolve = Path.resolve
        aliased = real_resolve(link)

        def resolve(self: Path, strict: bool = False) -> Path:
            resolved = real_resolve(self, strict)
            return real_resolve(target, strict) if resolved == aliased else resolved

        monkeypatch.setattr(Path, "resolve", resolve)
    assert link.resolve() == target.resolve(), "premise: the alias resolves to its target, inside the repository"
```

**A2-17.** `tests/test_bf970_frontmatter_reading.py`. Four new functions (six cases) at the end of the file.
SEARCH:
```
    assert time.perf_counter() - started < 30.0  # a hang guard, as AD-1341 S5's
    assert entry is not None and entry["frontmatter"]["classification"] == "ship"
    assert found == [path]
```
REPLACE:
```
    assert time.perf_counter() - started < 30.0  # a hang guard, as AD-1341 S5's
    assert entry is not None and entry["frontmatter"]["classification"] == "ship"
    assert found == [path]


@pytest.mark.parametrize("shape", ["deep", "refused", "tab"])
async def test_a_contained_alias_of_an_unparsed_note_is_its_targets_in_the_search_as_in_read_entry(store, monkeypatch, shape):
    """A2-T1, BF-970 A2 (round 1 F1; BF-679 parity). ``read_entry`` names an unparsed note's owner from the path the note resolves
    to; the search named it from its walk's lexical path. So a contained link ``notebooks/bob/alias.md`` to alice's unparsed note
    was withheld from bob by ``read_entry`` and shown to him by the search: since BF-940 slice 4 for a block YAML refuses
    (``refused``), and since BF-970 for one nesting 64 collections deep (``deep``), which the base read. Both readings of the search
    now name the owner from the resolved path. ``tab`` is read by libyaml and refused by PyYAML, so under libyaml only the second
    reading applies the stand-in (mutation row A2-M4). The owner and the Captain still find the note and its alias."""
    block = {"deep": _nest(_LIMIT), "refused": _REFUSED_BLOCK, "tab": _TAB_BLOCK}[shape]
    assert records_store_module._load_document(_raw(block))[2] is True, "premise: read_entry's reading is unparsed"
    note, alias = "notebooks/alice/note.md", "notebooks/bob/alias.md"
    _hand_made(store, note, _raw(block))
    _alias(monkeypatch, store.repo_path / alias, store.repo_path / note)
    _healthy(store, "reports/open.md", "warp open body")
    assert await store.read_entry(alias, reader_id="bob") is None
    assert (await store.read_entry(alias, reader_id="alice"))["frontmatter"] == {}
    for loader in _LOADERS:
        monkeypatch.setattr(records_store_module, "_RECORDS_YAML_LOADER", loader)
        assert await _found(store, "bob") == ["reports/open.md"], loader
        assert set(await _found(store, "alice")) == {note, alias, "reports/open.md"}, loader
        assert set(await _found(store, "captain")) == {note, alias, "reports/open.md"}, loader


async def test_an_unparsed_note_whose_resolved_path_cannot_be_named_is_withheld_by_the_search(store, monkeypatch):
    """A2-T2, BF-970 A2 (round 1 F1). Where the search cannot name the path an unparsed note resolves to now (a link moved outside,
    a loop or an ``OSError`` since its walk checked it), it cannot name the owner ``read_entry`` would, so it withholds the note
    from every reader, the owner and the Captain included, as it withholds what ``read_entry`` cannot answer (BF-952 A5). A parsed
    record does not read the path and is still found."""
    note = "notebooks/alice/deep.md"
    _hand_made(store, note, _raw(_nest(_LIMIT)))
    _healthy(store, "reports/open.md", "warp open body")
    assert note in await _found(store, "alice") and note in await _found(store, "captain"), "premise: the owner and the Captain find it"
    repo = store.repo_path.resolve()
    assert records_store_module._resolved_rel_path(store.repo_path.parent / "outside.md", repo) is None
    assert records_store_module._resolved_rel_path(store.repo_path / note, repo) == note
    monkeypatch.setattr(records_store_module, "_resolved_rel_path", lambda md_file, repo: None)
    for reader in ("alice", "captain"):
        assert await _found(store, reader) == ["reports/open.md"], reader
    admits = records_store_module._base_reading_admits
    assert admits(_nest(_LIMIT), scope="ship", reader_id="captain", reader_department="", path=None) is False
    assert admits(_nest(_LIMIT - 1), scope="ship", reader_id="bob", reader_department="", path=None) is True


@pytest.mark.parametrize("depth", [_LIMIT - 1, _LIMIT])
async def test_enrich_skill_changes_its_cached_entry_only_after_the_rewrite_succeeds(tmp_path, depth):
    """A2-T3, BF-970 A2 (round 1 F2). The catalog reads SKILL.md with its own ``yaml.safe_load`` (no nesting check: register R1), so
    it imports a skill whose frontmatter holds 64 collections open at once, and ``dump_frontmatter`` refuses the rewrite an
    enrichment makes of it (the base wrote it). ``enrich_skill`` updated its cached entry before that rewrite, so the cache named the
    new department while SKILL.md and SQLite kept the old one until a restart. The updates now go to a copy, and the cached entry,
    the same object, takes them only after the rewrite: at 64 the call raises and nothing changes; at 63 the skill is enriched."""
    skills_dir = tmp_path / "config" / "skills"
    skills_dir.mkdir(parents=True)
    catalog = CognitiveSkillCatalog(skills_dir=skills_dir)
    source = tmp_path / "sources" / "deep_skill"
    source.mkdir(parents=True)
    block = f"name: deep_skill\ndescription: A skill whose frontmatter nests deep\n{_nest(depth)}"
    assert frontmatter_module.frontmatter_nests_too_deep(block) is (depth >= _LIMIT), "premise: the depth, from PyYAML's events"
    (source / "SKILL.md").write_text(f"---\n{block}---\n\nDo the deep thing.\n", encoding="utf-8")
    entry = await catalog.import_skill(source)
    assert entry.department == "*" and catalog.get_entry("deep_skill") is entry, "premise: the catalog imported the skill"
    skill_md = skills_dir / "deep_skill" / "SKILL.md"
    before = skill_md.read_bytes()
    update = catalog.enrich_skill("deep_skill", {"department": "engineering", "intents": ["probe"]})
    if depth >= _LIMIT:
        with pytest.raises(ValueError, match=f"nest {_LIMIT} or more collections deep"):
            await update
        assert skill_md.read_bytes() == before
        assert (entry.department, entry.intents) == ("*", [])
    else:
        assert await update is entry
        assert (entry.department, entry.intents) == ("engineering", ["probe"])
        assert "probos-department: engineering" in skill_md.read_text(encoding="utf-8")
    assert catalog.get_entry("deep_skill") is entry
```

**A2-18.** `tests/test_bf940_s3_route_serialisation.py`. The module docstring (F3).
SEARCH:
```
and derives every depth below from the answer. BF-970 (#1801): the reader now stops first. A frontmatter holding ``FRONTMATTER_DEPTH_LIMIT`` (64)
collections open at once, or more, is unparsed (read as ``{}``), below the writer's stop on every platform, so no record the reader parses is too deep for
a route; the nesting rows left ``_UNWRITABLE`` and the cases that drove them now pin that. A lone surrogate reaches a record as an ASCII escape, ``\\ud800``, in the JSON a notebook
```
REPLACE:
```
and derives every depth below from the answer. BF-970 (#1801): the reader now stops first. A frontmatter whose text holds ``FRONTMATTER_DEPTH_LIMIT`` (64)
collections open at once, or more, is unparsed (read as ``{}``), below the writer's stop on every platform, so no record nested that deep in its text is too
deep for a route; the nesting rows left ``_UNWRITABLE`` and the cases that drove them now pin that. BF-970 A2 (round 1 F3): an alias opens no collection in
the text and builds a loaded value deeper than it, so a record the reader parses can still be too deep for a listing's body and not for the read route's
(``_ALIAS_LINKS``); the class keeps that window. A lone surrogate reaches a record as an ASCII escape, ``\\ud800``, in the JSON a notebook
```

**A2-19.** `tests/test_bf940_s3_route_serialisation.py`. Delete the unused `_MARKER` (F5).
SEARCH:
```
_BAD_LOG = "captains-log/case.md"
_MARKER = "VALUE-MARKER-917"
```
REPLACE:
```
_BAD_LOG = "captains-log/case.md"
```

**A2-20.** `tests/test_bf940_s3_route_serialisation.py`. The alias chain and its window, derived at import (F3).
SEARCH:
```
), "premise: each depth the cases use is on the side of the writer's limit that its case needs"
```
REPLACE:
```
), "premise: each depth the cases use is on the side of the writer's limit that its case needs"


def _chain(links: int) -> str:
    """A flow list of ``links`` anchored lists, each holding the one before it by an alias. As text it holds three collections
    open at once (the record's mapping, this list, one anchored list), whatever ``links`` is: an alias opens none."""
    return "[" + ", ".join(["&n0 [x]", *(f"&n{i} [*n{i - 1}]" for i in range(1, links))]) + "]"


def _chain_value(links: int) -> list[Any]:
    """What ``_chain(links)`` loads to: its last list nests ``links`` lists deep, each holding the one before it."""
    value: list[Any] = ["x"]
    chain = [value]
    for _ in range(1, links):
        value = [value]
        chain.append(value)
    return chain


def _first_alias_window() -> int:
    """The least chain whose record the read route's body can hold and a listing's cannot, asked of the writer that runs."""
    start = max(2, _LISTING_LIMIT - 10)
    assert _writes(_listing_body({"meta": _chain_value(start)})), "premise: the scan starts below a listing's limit"
    for links in range(start, _READ_LIMIT + 10):
        frontmatter = {"meta": _chain_value(links)}
        if _writes(_read_body(frontmatter)) and not _writes(_listing_body(frontmatter)):
            return links
    raise AssertionError("premise: no chain falls between a listing's limit and the read route's")


# BF-970 A2 (round 1 F3): the reader's limit counts collections open at once in the TEXT, and an alias opens none (L8), so a record
# the reader parses can load to a value as deep as the writer's limit. This chain is the first whose record the read route writes and
# a listing's body, two levels deeper, does not; the writer's stop is platform-dependent, so it is derived like the depths above.
_ALIAS_LINKS = _first_alias_window()
```

**A2-21.** `tests/test_bf940_s3_route_serialisation.py`. Rename and qualify the rewritten case, and add the alias window case (F3).
SEARCH:
```
    async def test_no_record_the_reader_parses_is_too_deep_for_a_listing(self, tmp_path):
        """BF-970 (#1801): this case scanned a window around the listing's limit through the real store for the first depth a
        listing refused. The reader now reads a frontmatter holding 64 collections open or more as unparsed, so no depth it parses
        reaches that limit: 63 levels are parsed and listed, 64 are read as ``{}`` and listed with the key, on any platform."""
        limit = frontmatter_module.FRONTMATTER_DEPTH_LIMIT
        assert limit - 2 < _LISTING_LIMIT, "premise: the deepest record the reader parses is within the listing's limit"
        store = _make_store(tmp_path, {_NOTE: _HEALTHY})
        for depth, parsed in ((limit - 2, True), (limit - 1, False)):
            (store.repo_path / _BAD_NOTE).write_text(_record("meta", _nested(depth)), encoding="utf-8")
            entry = await store.read_entry(_BAD_NOTE, reader_id="captain")
            assert ("meta" in entry["frontmatter"]) is parsed, depth
            response = _get(store, "/api/records/documents")
            assert response.status_code == 200
            assert [item["path"] for item in _items(response)] == [_BAD_NOTE, _NOTE], depth

    async def test_the_captains_log_limit_counts_the_records_it_returns(self, tmp_path):
```
REPLACE:
```
    async def test_no_record_whose_text_the_reader_parses_nests_too_deep_for_a_listing(self, tmp_path):
        """BF-970 (#1801): this case scanned a window around the listing's limit through the real store for the first depth a
        listing refused. The reader now reads a frontmatter whose text holds 64 collections open or more as unparsed, so no text
        nesting it parses reaches that limit: 63 levels are parsed and listed, 64 are read as ``{}`` and listed with the key, on any
        platform. BF-970 A2 (round 1 F3): a loaded value can still be deeper than its text (an alias); the next case keeps the window."""
        limit = frontmatter_module.FRONTMATTER_DEPTH_LIMIT
        assert limit - 2 < _LISTING_LIMIT, "premise: the deepest record the reader parses is within the listing's limit"
        store = _make_store(tmp_path, {_NOTE: _HEALTHY})
        for depth, parsed in ((limit - 2, True), (limit - 1, False)):
            (store.repo_path / _BAD_NOTE).write_text(_record("meta", _nested(depth)), encoding="utf-8")
            entry = await store.read_entry(_BAD_NOTE, reader_id="captain")
            assert ("meta" in entry["frontmatter"]) is parsed, depth
            response = _get(store, "/api/records/documents")
            assert response.status_code == 200
            assert [item["path"] for item in _items(response)] == [_BAD_NOTE, _NOTE], depth

    async def test_a_record_whose_aliases_load_too_deep_for_a_listing_is_left_out_and_read_by_the_read_route(self, tmp_path, caplog):
        """A2-T4, BF-970 A2 (round 1 F3). The window the case above scanned is still reachable by a record the reader parses: the
        reader's limit counts collections open at once in the text, and an alias opens none, so a chain of ``_ALIAS_LINKS``
        anchored lists, three levels deep as text, loads as deep as the read route's body allows. The read route writes it; a
        listing, whose body holds the record two levels deeper, leaves it out (``_writable``) and lists the rest. A check of each
        record alone, not inside the listing's body, would keep it, and the listing would be the unhandled 500."""
        value = _chain(_ALIAS_LINKS)
        block = f"author: alice\nclassification: ship\nmeta: {value}\ntags: [coolant]\n"
        assert _record("meta", value) == f"---\n{block}---\n\ncoolant case body\n", "premise: the block is the record's"
        assert not frontmatter_module.frontmatter_nests_too_deep(block), "premise: the text is within the reader's limit"
        assert _ALIAS_LINKS > frontmatter_module.FRONTMATTER_DEPTH_LIMIT, "premise: the loaded value is deeper than any text the reader parses"
        store = _make_store(tmp_path, {_NOTE: _HEALTHY, _BAD_NOTE: _record("meta", value)})
        entry = await store.read_entry(_BAD_NOTE, reader_id="captain")
        assert entry is not None and entry["frontmatter"]["meta"] == _chain_value(_ALIAS_LINKS), "premise: the reader parsed the record"
        assert _writes(_read_body(entry["frontmatter"])) and not _writes(_listing_body(entry["frontmatter"])), "premise: the window"
        read = _get(store, _READ)
        assert read.status_code == 200 and read.json()["frontmatter"]["meta"] == _chain_value(_ALIAS_LINKS)
        with caplog.at_level(logging.WARNING, logger="probos.routers.records"):
            listing = _get(store, "/api/records/documents")
        assert listing.status_code == 200 and [item["path"] for item in _items(listing)] == [_NOTE]
        assert "left out of the listing" in caplog.text and "case.md" in caplog.text

    async def test_the_captains_log_limit_counts_the_records_it_returns(self, tmp_path):
```

### 18.6 Blocks: trackers

**A2-22.** `PROGRESS.md`. A substring of line 5 (the BF-970 Fix bullet).
SEARCH:
```
`tests/test_bf970_frontmatter_reading.py` adds 12 cases;
```
REPLACE:
```
Review round 1 (Amendment A2): the search names an unparsed document's owner from the path it resolves to, as `read_entry` does, so a contained link under one notebook to another's unparsed note is not shown to the link's directory owner (a gap since BF-940 slice 4 for a block YAML refuses; withheld where the path cannot be resolved), and `enrich_skill` changes its cached entry only after SKILL.md is rewritten, so the writer's refusal leaves the cache, the file and SQLite alike. `tests/test_bf970_frontmatter_reading.py` adds 18 cases (17 without libyaml), and the route tests keep the listing window with an alias chain;
```

**A2-23.** `DECISIONS.md`. The BF-970 entry.
SEARCH:
```
- *Residual.* L1 to L11 of the contract. *Reversal.* Revert the BF-970 commits.
```
REPLACE:
```
- *D6 (review round 1, A2).* The search's stand-in for an unparsed document names its owner from the path the document resolves to, `read_entry`'s, not the walk's lexical path; it is resolved only where an owner is needed, and the document is withheld where it cannot be (fail closed). `enrich_skill` applies an enrichment to a copy and to its cached entry only after the rewrite succeeds. Rejected: moving the catalog's readers onto `load_frontmatter` (register R1: it changes what an import accepts).
- *Residual.* L1 to L13 of the contract. *Reversal.* Revert the BF-970 commits.
```

### 18.7 Tests added by A2

| Id | File | Cases | Proves | On head `3ac41487` |
|---|---|---|---|---|
| A2-T1 | test_bf970 | 3 (`deep`, `refused`, `tab`) | F1 parity in both readings; owner and Captain still admitted | fails at the bob search line (all three) |
| A2-T2 | test_bf970 | 1 | F1 fail closed; a parsed record is unaffected | fails at `_resolved_rel_path` (missing attribute) |
| A2-T3 | test_bf970 | 2 (63, 64) | F2: the cache changes only after the rewrite | 64 fails at the department line; 63 passes (control) |
| A2-T4 | s3 | 1 | F3: the listing window through an alias | passes (guard); kills A2-M10 |

None reaches the recursion limit: the deepest Python recursion is a 64-level PyYAML load or dump, which T7 and T8 already run unguarded. None carries `gc_quiet_at_recursion_limit`, so the guard's 10 entries are unchanged. Focused gate: `pytest tests/test_bf970_frontmatter_reading.py tests/test_bf940_s3_route_serialisation.py tests/test_ad596d_external_skill_import.py tests/test_ad596e_skill_validation.py tests/test_bf952_records_keyword_search.py tests/test_bf679_oracle_records_reader_identity.py tests/test_bf958_records_link_containment.py tests/test_bf940_s4_*.py -q -n 0`.

### 18.8 Mutation rows (each Line occurs once, stripped, in its file on the A2 head)

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| A2-M1 | records_store | `gate = _unparsed_gate(resolved)` | `gate = _unparsed_gate(rel_path)` | **A2-T1** (deep, refused, tab) |
| A2-M2 | records_store | `gate = _unparsed_gate(resolved)` | `gate = frontmatter` (R10's equivalent) | **T2**, A2-T1, s4 `:340` |
| A2-M3 | records_store | `if resolved is None:  # BF-970 A2 (round 1 F1): no owner can be named, so the document is withheld (fail closed)` | `if False:` | **A2-T2** (`AttributeError` out of the search) |
| A2-M4 | records_store | `path=_resolved_rel_path(md_file, repo),` | `path=result["path"],` | **A2-T1[tab]** under `CSafeLoader` (libyaml hosts; equivalent without libyaml, as R14) |
| A2-M5 | records_store | `if path is None:  # BF-970 A2 (round 1 F1): no owner can be named, so the document is withheld (fail closed)` | `if False:` | **A2-T2** (the Captain line of the direct call) |
| A2-M6 | records_store | `return md_file.resolve().relative_to(repo).as_posix()` | `return md_file.relative_to(repo).as_posix()` | **A2-T1** |
| A2-M7 | records_store | `except (OSError, RuntimeError, ValueError):  # fail closed: no owner can be named` | `except (OSError, RuntimeError):` | **A2-T2** (the `outside.md` line) |
| A2-M8 | skill_catalog | `updated = replace(entry)  # BF-970 A2 (round 1 F2): the cache changes only after the rewrite` | `updated = entry` | **A2-T3[64]** |
| A2-M9 | skill_catalog | `setattr(entry, attribute, getattr(updated, attribute))  # BF-970 A2 (round 1 F2): the rewrite succeeded` | `pass` | **A2-T3[63]**, ad596d `test_enrich_adds_metadata` |
| A2-M10 | routers/records.py | `if _writes({key: [record]}):` | `if _writes(record):` | **A2-T4** (HTTP 500) |

**Campaign.**
- The new bare `if unparsed:` in the first pass carries a comment, so R13's stripped `if unparsed:` (in `publish`) stays unique.
- R10 is retired.
- On the A2 head, rerun R1-R3, R11-R15 and A2-M1 to A2-M10 against the six R-campaign test files plus `test_ad596d_external_skill_import.py`.
- R4-R9 stand if `ast.dump(ast.parse(src))` of `utils/frontmatter.py` with every docstring `Expr` removed is equal for the campaign blob and the A2 blob (A2-10 and A2-11 change docstrings only). Otherwise rerun them.
- Every row must be killed by at least its bold case. A survivor is a hard stop for the Architect, except A2-M4 without libyaml (record it).

### 18.9 Review scope

The next round is a **delta review** of A2. No public signature, persisted format, config field, event type, route body or test another component relies on changes:
- `_base_reading_admits` is private, and `str | None` widens its parameter compatibly.
- `enrich_skill` keeps its signature, its return value (the same object) and its success behaviour.

Properties for the reviewer to verify:
1. The 7-tuple and 4-tuple unpacking in both passes, and the reuse of `md_file` as the second loop's variable.
2. The search's result `"path"` and its ranking key are still the lexical `rel_path`.
3. An unparsed record whose resolution fails is withheld from every reader. A parsed record never depends on resolution, except for one `Path.resolve` in the second reading.
4. `enrich_skill` mutates nothing the caller can see before `_rewrite_frontmatter` returns.
5. A2-T4's window is derived, not hard-coded, and asserts its premises.

### 18.10 Verified Against Codebase (2026-11-20, head `3ac41487`)

```
records_store.py:136   def _unparsed_gate(rel_path: str) -> dict[str, Any]:
records_store.py:142-143  "``rel_path`` is the document's path in the / repository, as the walk of the search names it and as ``read_entry`` resolves it."
records_store.py:359-360  def _base_reading_admits( ... path: str,
records_store.py:376-377  if unparsed: ... frontmatter = _unparsed_gate(path)
records_store.py:434   repo = root.resolve()
records_store.py:435   readable: list[tuple[str, dict[str, Any], str, dict[str, float], int, str | None]] = []
records_store.py:437   rel_path = str(md_file.relative_to(root)).replace("\\", "/")   (lexical)
records_store.py:441   if not _resolves_inside(md_file, repo):
records_store.py:473   _unparsed_gate(rel_path) if unparsed else frontmatter,
records_store.py:492-493  ranked: list[...]; for rel_path, ..., block in readable:
records_store.py:514-518  for _, result, block in ranked: ... path=result["path"],
records_store.py:531-534  _resolves_inside body
records_store.py:1470  file_path = self._safe_path(path)
records_store.py:1482  _unparsed_gate(file_path.relative_to(self._repo_path.resolve()).as_posix())
records_store.py:1711-1712  asyncio.to_thread(_search_records, ...)
records_store.py:1836  resolved = (self._repo_path / user_path).resolve()
tests/test_bf970_frontmatter_reading.py:177, :240-241  direct _base_reading_admits(..., path=<str>) calls (still valid)
tests/test_bf952_records_keyword_search.py:344  wraps _base_reading_admits for thread recording only (no argument assertions)
tests/test_bf958_records_link_containment.py:65-75  _file_link: WinError 1314 skip pattern
utils/frontmatter.py:66-85  frontmatter_nests_too_deep; :83 except yaml.YAMLError only
utils/frontmatter.py:94  "Any other error of the load propagates"
utils/frontmatter.py:149  "frontmatter key(s) %s nest %d or more collections deep, ..."
skill_catalog.py:16    from dataclasses import dataclass, field   (no other `replace` in the file)
skill_catalog.py:55-73  @dataclass CognitiveSkillEntry (all fields init)
skill_catalog.py:747-764  enrich_skill mutates the cached entry, then _rewrite_frontmatter, then register
skill_catalog.py:307-309  register: self._cache[entry.name] = entry
routers/records.py:48-67  _writable; :59 if _writes({key: [record]}):
tests/test_bf940_s3_route_serialisation.py:12-14 (docstring), :51 _MARKER (no other use), :92-112 (_first_refused, limits, premise), :298-311 (rewritten case)
PROGRESS.md:5  "`tests/test_bf970_frontmatter_reading.py` adds 12 cases;" (only count of the new file in the trackers)
DECISIONS.md:1669  "- *Residual.* L1 to L11 of the contract. *Reversal.* Revert the BF-970 commits."
```

**Absence verified.** Claim: `_base_reading_admits` and `_unparsed_gate` have no callers beyond the store and the tests listed. Run: Grep `_base_reading_admits|_unparsed_gate|_search_records\(` over `*.py`. Found: records_store `:136/:359/:377/:417/:473/:517/:1482`, test_bf940_framing `:243` (docstring), test_bf952 `:344`, test_bf970 `:5/:177/:239`. Holds: yes.

**Prior art.** None reviewed: this is a bug-fix amendment with no outside analogue. The design follows the repository's own rule, BF-958 `_safe_path` resolution parity.

## For the register (#1820; filing policy: consolidated there, not new issues)

- **R1 (new, P3; injected-only: an operator-installed or imported SKILL.md).**
  - The skill catalog reads SKILL.md with its own `yaml.safe_load` (`skill_catalog.py:113`, `:790`), with no nesting check.
  - `parse_skill_file` catches only `YAMLError`, so a SKILL.md nesting past PyYAML's recursion raises `RecursionError` out of the scan.
  - Since BF-970 its rewrite (`dump_frontmatter`) refuses 64 levels or more while its read accepts more.
  - Remedy: read through `load_frontmatter`. Considered and deferred: outside #1801's records scope.
- **#1754 BF-940 items:** none is settled outright.
  - BF940S4-F4 is narrowed: the first pass no longer reads a cut, but libyaml's divergence stays (L4).
  - BF940S4-F1's class gains the newly unparsed documents (0 measured).
  - Record both on #1820.

**Closure comment for #1801 (post after merge):**
> BF-970 merged in #<PR>. Every Ship's Records reader now reads a frontmatter block through `probos.utils.frontmatter.load_frontmatter`. A block that holds 64 collections open at once, or that YAML refuses, is unparsed in `read_entry`, `list_entries`, `publish`, update-in-place and both readings of the search, from any stack; one of 63 loads. BF-940 A1 is gone: no reader reads the base's cut of the text. `dump_frontmatter` refuses 64 levels or more.
>
> Behaviour change: a document whose block does not load but whose cut did is now private to the owner of its notebook directory (Captain-only elsewhere), and so is one nesting 64 levels or more. Measured on the live copy (2026-11-18): 0 of 2,776 documents affected.
>
> Guard: the six test functions of this change that run PyYAML to the recursion limit by design now ask for BF-986's `gc_quiet_at_recursion_limit` (the census of that change, #1754); the AD-1127 cyclic-metadata test is guarded with them (item bf-986 F3 of #1820, ticked there).
>
> What stays open, on #1820: the skill catalog's own SKILL.md readers (R1); the libyaml first-pass divergence (BF-940 slice 4 L11) and stale index rows (L3), unchanged.
