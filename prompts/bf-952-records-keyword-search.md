# BF-952 (#1751): Ship's Records keyword search matches whole words and ranks rare ones first

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-05
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-05: cost amendment, after the orchestrator measured the draft at about 2.7 s per call that blocked the event loop. It adds RK7 and RK8, rewrites the search internals inside P1-2 and P1-3, adds tests T13 and T14 and one T4 case, re-anchors RKS-4, RKS-7 to RKS-13, RKS-16 and RKS-18, adds rows RKS-19 to RKS-22, adds bounds B1 and B2 (§4, §16), and revises L1 and adds L13 to L16.
**Revised by:** the orchestrator (Copilot), 2026-11-06: P1-3's SEARCH, which the cost amendment wrote as a reference to the first draft, is the verbatim 68-line block of `records_store.py:1109-1176` (the script that restored it asserts that it equals the base file's text); and the base is the AD-1346 M3e4d6 to M3e4d8 batch's merge, so the batch's own `PROGRESS.md` and `DECISIONS.md` text is on it (P3-1's SEARCH is the title line and P3-2's the BF-950 heading, and both still occur once); the Status line names the batch's merge (`a745e447`) instead of its branch; no other change.
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-05: Amendment A1, the repair of review round 1 (GPT-6.1 Sol, NOT READY). It adds one framing and load for every Ship's Records reader (BF-940, #1686), fail-closed reads of an unparseable frontmatter, the search's per-record parse boundary, numeric field values, the route's `directory` and the HXI request. T13 and T14 are rewritten and T15 to T19 added. Rows RKS-21 and RKS-22 are retired and RKS-23 to RKS-34 added. L9 and L16 are revised and L17 to L23 added.
**Status:** ready to build. **Base:** drafted on `1c01a5ee` (`origin/main`, the BF-950 merge). The AD-1346 M3e4d6–d8 batch merged first (`a745e447`, PR #1756) and changed none of the M1 or M2 files: `git diff --stat 1c01a5ee a745e447 -- src/probos/knowledge/records_store.py tests/test_bf949_notebook_reader_identity.py tests/test_layer_boundaries.py` is empty. **M3's SEARCH text was written against `1c01a5ee` and still occurs once on `a745e447`, so §8 needed no re-anchoring.** **Dependencies:** none. **Tier:** M1 STANDARD with a shared contract (the `search` result list, read by four production callers and the HXI); M2 STANDARD, test only; M3 STANDARD, trackers. **Estimated tests:** one new file, `tests/test_bf952_records_keyword_search.py`, with 14 functions and 42 cases (counted by reading); after Amendment A1, 19 functions and 58 cases (counted by reading); after Amendment A2, 21 functions and 68 cases (counted by reading); after Amendment A3, 20 functions and 63 cases (counted by reading). Edits: `tests/test_bf949_notebook_reader_identity.py` (one assertion) and `tests/test_layer_boundaries.py` (one allowlist entry).
**BF number:** BF-952, held by the title of #1751 (OPEN). Nothing is allocated, and no AD number is needed.
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-05: Amendment A2, the repair of review round 2 (GPT-6.1 Sol, NOT READY). The line framing is read only where it keeps the classification the base read (RK13), and a rewrite that keeps a note's classification is indexed at it (RK14). T13 gains three cases; T20 and T21 are added. RKS-23 to RKS-26 are re-anchored and RKS-35 to RKS-40 added. L18 and L19 are revised and L24 added.
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-06: Amendment A3, the round-three brake after review round 3 (GPT-6.1 Sol, NOT READY). **Split:** every reader reads with the base's framing again (RK15); RK9, RK10 and RK13 are withdrawn to BF-940 (#1686). T16 and T17 are retired, T13 loses two cases, T20 gains one and T22 is added. RKS-23 to RKS-25, RKS-31, RKS-32, RKS-35 to RKS-38 and RKS-40 are retired and RKS-41 to RKS-44 added. L18, L19 and L24 are revised, L21 is withdrawn and L25 is added.

**Which text describes the head.** Line numbers are those of `1c01a5ee`. Before building, run `git diff --stat 1c01a5ee HEAD -- src/probos/knowledge/records_store.py tests/test_bf949_notebook_reader_identity.py tests/test_layer_boundaries.py`. If it is not empty, or any M1 or M2 SEARCH no longer matches, return to the Architect. Where prose and a block differ, the block wins. Files are LF in the index; SEARCH text is LF.

**Which section carries what, for a one-slice BF.**
- §1–§3: premise and decisions.
- §4–§7: the build. M1 is production code plus the two test edits it makes necessary; M2 is the new test file; M3 is the trackers.
- §8: trackers and ledger. Both AD-ledger files and `tests/test_ad1184_ad_ledger.py` **apply**, because `gen_ad_ledger.py` reads BF heads (`:1`, `:113`). `docs/development/roadmap.md` is **not** updated: it has no BF-948 to BF-953 rows.
- §9: what is not built. §10: mutation rows. §11: limits. §12: evidence. §13: gate checks and prior art. §14: the reviewer's properties. §15: acceptance criteria. §16: the orchestrator's measurements.

## 1. Problem

1. `RecordsStore.search` (`records_store.py:1109-1176`):
   - builds `query_words = set(query.lower().split())` (`:1143`);
   - counts `w in raw_lower` over the **raw file, frontmatter keys included** (`:1156-1157`);
   - scores `matches / len(query_words)` (`:1171`);
   - sorts stably over `sorted(rglob)`, so ties fall to path order (`:1145`, `:1175`);
   - cuts the list to 20 (`:1176`).
2. Consequences: punctuation stays on words; `i`, `a` and `to` are substrings of nearly every file; `status` matches every record's YAML. The Captain's question matched all 2,768 live records at one score (#1751, Evidence).
3. Consumers:

| Consumer | Where | What it takes |
|---|---|---|
| Oracle keyword axis | `oracle_service.py:1058-1085` | `raw[:k]`; `score / 10.0` (`:1074`); fused by rank (`:154-226`) |
| Proactive notebook pull | `proactive.py:2895-2914` | `search_results[0]` for the query `dept`, confined to `notebooks/{callsign}` |
| HXI records search | `routers/records.py:166-182` → `ui/src/store/useStore.ts:2073-2086` | top 20, filtered client-side to `notebooks/*` |
| DM targeted lookup (AD-725) | `dm_targeted_lookup.py:255-270` | each dict turned into prompt text (`:279-290`) |

4. **The score scale is a contract.** Keyword scores reach the Oracle at ≤ 0.1, under AD-1141's 0.35 floor (`config_models/agentic.py:1082`; `crew_executor.py:779`). `query()` re-sorts by score (`oracle_service.py:710`), and so does `crew_executor.py:785`.
5. **Cost.** Measured by the orchestrator on a 2,801-file synthetic corpus (11.5 MB, about 4 KB each):

| Tree | Query | Median per call |
|---|---|---|
| Base | selective | 371 ms |
| Base | the Captain's match-all question | 1,530 ms |
| First draft | any query | about 2,700 ms |

   - The profile: about 47% in Python-level tokenising (2.55 million part `findall` calls and a full weights dict per record), about 30% in PyYAML's pure-Python scanner. libyaml is installed.
   - `search` has no `await` inside, and `_query_records_keyword` awaits it directly (`:1066`), so every call blocks the event loop for its whole duration: the passive Oracle on a DM turn, `oracle_query`, the proactive pull and the HXI.

## 2. Solution

- `search` tokenises the query and each record on whole words, drops query stopwords (keeping all words when nothing else is left), and scores the body and five meaningful frontmatter values, never a key.
- Rank: IDF-weighted coverage, then BM25 with field weights, then the newer `updated` (else `created`), then path. `score` is the coverage, in 0..1 and non-increasing.
- Term rarity is counted only over records the reader may read.
- The walk, parse and ranking run in a worker thread (`asyncio.to_thread`). Frontmatter is parsed with libyaml when installed. Only records whose scored text contains a query term as a substring are counted term by term; every other record is only measured.
- Return shape, cap, scope and reader rules are unchanged.
- Amendment A1: every Ship's Records reader frames and loads a document with one function, `_read_document`. The frontmatter ends at the first `---` that begins a line (BF-940, #1686); libyaml loads it when installed, and PyYAML when libyaml refuses. A frontmatter that does not parse is shown by `read_entry` and search to the Captain alone. Search withholds a record whose frontmatter YAML cannot construct, and scores a number in a scored field as text. The records route forwards `directory`, which the HXI's notebook search sets to `notebooks`. No other caller changes.

## 3. Decisions

**RK1, matching.**
- Query terms are the distinct compound tokens (`\w+(?:[-.]\w+)*`, lower-cased) of the query, in order, minus `_SEARCH_STOPWORDS`. All of them are kept if none remain.
- A plain term matches each `\w+` word equal to it, so `952` is found inside `bf-952`. A term containing `-` or `.` matches each whole compound equal to it.
- Scored text is the body plus the values of `title`, `topic`, `tags`, `department` and `author`. `department` is required by the proactive pull (`proactive.py:2898`; written at `records_store.py:336-337`).
- Never scored: YAML keys, `classification`, `status`, timestamps, `revision`, `metrics`, extra keys.
- Rejected: substring matching; scoring every frontmatter value.

**RK2, ranking and score.** The key is `(-coverage, -relevance, written is None, -(written or 0.0), path)`.
- `coverage` = Σ IDF of the matched terms / Σ IDF of all terms, with IDF `ln(1 + (N - df + 0.5)/(df + 0.5))`, which is always > 0.
- `relevance` = BM25 with k1 = 1.5 and b = 0.75 (BF-625's constants, `transcript_grounding.py:47-48`). tf is the weighted count: body 1; title, topic and tags 3; department and author 2. Length is the number of `\w+` words in the scored texts.
- `written` = `cognitive.provenance.record_write_time` (BF-950's total parser).
- `score` = coverage.
- Rejected: BM25 divided by the top score (a lone weak hit reads 1.0); BM25 order with a coverage score (the downstream re-sorts by score would undo it).

**RK3, privacy (A4).** Only records that pass `record_is_readable` for this reader, outside `_archived/`, count toward N, df and average length.

**RK4, compatibility.**
- Return shape `{"path", "frontmatter", "score", "snippet"}`, `snippet = content[:200]`, the cap of 20, the scope `ValueError`, `directory` and the reader tri-state are unchanged.
- The scope and directory are still validated on the caller's loop before the hand-off, so their errors raise exactly as before.
- `/10` at `oracle_service.py:1074` is unchanged, so AD-1141's floor is unchanged.
- An empty or wordless query returns `[]`.

**RK5, non-mapping frontmatter.** A non-empty YAML list or a truthy scalar made `record_is_readable` raise on the base. It is now skipped with a debug log. It names no classification, so withholding it is the fail-closed choice. A falsy one (`[]`, `false`, `0`, `0.0`, `''`) reads as `{}`, as every reader has always read it, so it is shown at the default level (L9; A1, finding V3).

**RK6, where `record_write_time` lives.** It is imported from `probos.cognitive.provenance`, which imports only the standard library (`provenance.py:13-21`), with one `test_layer_boundaries` allowlist entry (AD-583 precedent, `:87-88`). Rejected: a local copy (DRY); moving the parser into `knowledge/` (that refactors BF-950's merged code, L5).

**RK7, cost (ranked; 1 to 3 are chosen together).**
1. **Chosen: count only what can match.**
   - Per record, lower-case the scored texts and measure the length with one C-level `findall` per text.
   - If no query term is a substring of any scored text, stop there: the record counts toward N, df = 0 and the average length only.
   - Otherwise, count terms with `Counter` over the `findall` results (compounds only when the query has a compound term).
   - The check runs on the **parsed** text, not the raw file, so a YAML-escaped value (`"Caf\xE9"`) is still found. A term counted as a word is always a substring of its lowered text, so the check loses nothing.
2. **Chosen:** parse frontmatter with `yaml.CSafeLoader` when `yaml.__with_libyaml__`, else `yaml.SafeLoader`, with a `safe_load` retry on a libyaml error. After A1 this is every reader's parse, not the search's alone (RK8).
3. **Chosen:** run the synchronous walk in `asyncio.to_thread` through a module function that touches no store state and writes nothing.
4. Rejected for this BF: an in-memory cache keyed by path, `mtime_ns` and size.
   - It is shared mutable state read from worker threads.
   - It needs invalidation for deletes and for same-size rewrites within one mtime tick.
   - It holds roughly the corpus text in memory.
   - It still costs a stat per file per call.
   - It is the index; see N1.
5. Deferred: the index as its own item (N1, under #1754).
- Measured by B1 and B2 (§4). The first is the base's worst case; the second, the loop.

**RK8, one parse (A1, finding 6).**
- `_read_document(raw)` is the only framing and load. `_parse_document`, `read_entry` and search call it, so no input parses differently between readers.
- libyaml when installed; `yaml.safe_load` on a `YAMLError`; `None` when both refuse. No record that parses today stops parsing (PyYAML is the fallback). A frontmatter only libyaml accepts (a tab after a key) now parses for every reader. No input is known that both loaders accept with different values.
- Rejected: `safe_load` in search (B1); parsing with both loaders.

**RK9, framing (A1, finding 1; BF-940, #1686).**
- The frontmatter ends at the first `---` that begins a line. This differs from the base only where the base cut a value mid-line.
- On the base, `author: Ezri---Prime` read as `{author: Ezri}`, and a quoted topic holding `--- x: y` did not parse. Each read as `ship`, so another reader was shown a private record.
- Rejected: BF-940 first as its own slice; fail-closed alone; the exact-line rule (L18). The skill catalog's splits stay on #1686 (L20).

**RK10, fail closed (A1).**
- A frontmatter that does not parse is the Captain's alone in `read_entry` and search. `_parse_document` still returns `{}` for it (L19).
- Search withholds, with a debug log naming the path, a record whose frontmatter YAML's constructor cannot build (finding 5). `read_entry` still raises for it (L22).

**RK11, the route (A1, finding 3).** `search_records` forwards `directory` (validated by `_safe_path`, HTTP 400 on traversal). The HXI's notebook search sends `directory=notebooks` and keeps its client filter as a guard.

**RK12, the DM lookup (A1, finding 4).** Unchanged; recorded as L17. The base met no deadline: it blocked the loop past it. Rejected: raising `timeout_ms` (every lookup type, no validated value); a knowledge-only bound; awaiting past the abort.

**RK13, which framing is read (A2, round 2 finding 1).**
- The base's framing (the first later `---` anywhere) is the reading. A1's line framing replaces it only where a `---` inside a line comes before the first later line beginning `---`, and only if it loads as a mapping that, where the base's framing names a classification, names the same one (`_line_framing_is_kept`). A frontmatter that a hand-made or legacy file closed inside a line reads as on the base, at the level the base read. Every store-written value holding `---` still reads whole (T16).
- Rejected: failing closed when no line begins `---` (the owner loses the record, and a Captain's `publish` or an update-in-place, which read `{}` for it, would rewrite it without its classification); failing closed only for an inline close (the same); the line framing alone (A1: such a record read with no classification, or took its body as YAML; T20).

**RK14, the indexed classification (A2, round 2 finding 2; AD-1157a).** `write_entry` hands the semantic index the classification it writes, not the call's argument, so a notebook rewrite that keeps a note's classification indexes it at that level. A base defect with ordinary reach, fixed here because the convergence rule fixes ordinary-reach findings in the item.

## 4. Milestones and gates

| M | Tier | Shared contract? | Pairs | Gate |
|---|---|---|---|---|
| M1 | STANDARD | **yes**: the `search` result list and its `score` | P1-1 to P1-5 (5) | G1 |
| M2 | STANDARD | test only | N2-1 (1, full file) | G2, then B1 and B2 |
| M3 | STANDARD | trackers | P3-1, P3-2 (2), ledger | G3 |
| A1-M1 | STANDARD, security-relevant (access control) | **yes**: every Ship's Records reader's parse, `read_entry`'s admission, the search route, the HXI request | A1-01 to A1-18 (18) | GA1, then B1 and B2, then the §10 campaign |
| A1-M2 | STANDARD | trackers | A1-19 to A1-21 (3), ledger | G3 |
| A2-M0 | STANDARD | contract text | A2-08 to A2-16 (9) | none |
| A2-M1 | STANDARD, security-relevant (access control) | **yes**: every Ship's Records reader's framing; the classification the semantic index receives | A2-01 to A2-07 (7) | GA2 (§A2.3), then the §10 campaign |
| A2-M2 | STANDARD | trackers | A2-17 to A2-22 (6), ledger | G3 |

- **M0:** on the base, record the collected count of every existing file named in G1.
- **G1:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_records_store.py tests/test_bf949_notebook_reader_identity.py tests/test_bf679_oracle_records_reader_identity.py tests/test_bf684_records_index_coverage.py tests/test_ad1138_records_semantic_index.py tests/test_ad725_dm_targeted_lookup.py tests/test_ad1139_oracle_query_tool.py tests/test_ad1140_publish_finding.py tests/test_ad1141_crew_loop_sigma.py tests/test_bf950_oracle_result_age.py tests/test_self_monitoring.py tests/test_proactive_quality.py tests/test_path_traversal.py tests/test_layer_boundaries.py tests/test_ad1346_admission_file_write_census.py tests/test_ad1346_admission_effect_census.py tests/test_ad1346_admission_store_family_census.py tests/test_ad1341_s6_records_snapshot.py -q -n 0`, then `... -P scripts/check_architecture_principles.py --check`.
  - Expected: 0 failed; counts equal to M0.
  - **Hard stop:** any failure of `test_bf949…::test_the_agents_own_entry_is_found_behind_twenty_readable_matches`. Its premise rests on V-BF949 (§12). Return to the Architect.
- **G2:** `... -m pytest tests/test_bf952_records_keyword_search.py <the 18 G1 files> -q -n 0`. Expected in the new file: **42 passed** (M2's head). Others: 0 failed.
- **GA1 (A1-M1's head):** see §A1.3. Expected in the new file: **58 passed** (counted by reading).
- **B1 and B2 (the orchestrator, on M2's head, before the Diff Reviewer).** Corpus and method as in §1 item 5: 2,801 files, about 4 KB bodies, YAML frontmatter; one process; three runs per query; median. Report `yaml.__with_libyaml__`.
  - **B1:** for each of `Hello Ezri`, `tictactoe Captain` and the Captain's question (§7.2 `_QUESTION`), the candidate's median per call is **no slower than the base's median for the Captain's question**, measured in the same session (1,530 ms on the reference run). A target of 1,000 ms is reported, not gated.
  - **B2:** during one candidate search on that corpus, a coroutine on the same loop that repeats `await asyncio.sleep(0.010)` records how much later than 10 ms each tick resumes. The maximum overshoot is **≤ 100 ms**. On the base it is about the whole call.
  - **Failure of either is a hard stop for the item** before review and the broad gate. It goes back to the Architect. The Builder does not tune for it.
- **G3:** `... -P scripts/gen_ad_ledger.py`; `... -P scripts/gen_ad_ledger.py --check`; `... -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- The broad gate runs once, in the main session with `--receipt`, after the review repairs.

## 5. Commit messages

- M1: `BF-952 M1: Ship's Records keyword search matches whole words, ranks rare ones first and runs off the event loop`
- M2: `BF-952 M2: tests for whole-word matching, term rarity, the date tie-break, the reader's statistics and the worker thread`
- M3: `BF-952 M3: trackers and ledger`

## 6. Tests (`tests/test_bf952_records_keyword_search.py`)

| Id | Function | Cases | Covers | Fails on the base? |
|---|---|---|---|---|
| T1 | `test_a_question_made_mostly_of_stopwords_finds_the_record_holding_its_rare_terms` | 1 | acceptance 1 | yes |
| T2 | `test_words_match_whole_never_as_substrings` | 4 | acceptance 2; stopword-only fallback | 3 of 4 |
| T3 | `test_equal_scores_put_the_newer_record_first` | 5 | acceptance 3; RK2 date shapes | yes |
| T4 | `test_frontmatter_keys_are_not_scored_and_its_meaningful_values_are` | 10 | RK1; RK7 check on parsed text | 5 of 10 |
| T5 | `test_a_term_in_a_tag_outranks_the_same_term_in_the_body` | 1 | RK2 field weight | yes |
| T6 | `test_an_identifier_matches_whole_and_by_its_parts` | 3 | RK1 compounds | no (guard) |
| T7 | `test_scores_are_between_zero_and_one_and_never_rise_down_the_list` | 1 | RK2 | no (guard) |
| T8 | `test_a_record_the_reader_cannot_read_does_not_move_the_scores_it_is_shown` | 2 | RK3 | yes (control) |
| T9 | `test_the_oracle_puts_the_game_record_first_for_a_question_naming_the_game` | 1 | seam: real Oracle; RK4 scale | yes |
| T10 | `test_the_notebook_pull_finds_a_note_whose_department_is_only_in_its_frontmatter` | 1 | seam: proactive pull | no (guard) |
| T11 | `test_a_record_whose_frontmatter_is_not_a_mapping_is_skipped_not_raised` | 2 | RK5 | yes |
| T12 | `test_a_query_with_no_words_finds_nothing` | 3 | RK4 | 1 of 3 |
| T13 | `test_every_reader_frames_and_loads_a_document_alike` (A1; was `test_search_reads_a_document_as_the_store_reads_it`, 7 cases; A2 adds 3) | 14 | RK8, RK9, RK13; findings 1 and 6; round 2 finding 1 | n/a (new helper) |
| T14 | `test_a_search_runs_off_the_event_loop` (A1: the walk, reads, parse and ranking) | 1 | RK7 option 3; V1 | yes (setup) |
| T15 | `test_a_numeric_frontmatter_value_is_scored_and_a_boolean_is_not` | 3 | finding 2 | 1 of 3 (the boolean) |
| T16 | `test_a_frontmatter_value_holding_three_hyphens_is_read_whole_and_stays_private` | 4 | RK9; finding 1; #1686 | yes |
| T17 | `test_a_record_whose_frontmatter_does_not_parse_is_shown_to_the_captain_alone` | 1 | RK10 | yes |
| T18 | `test_a_record_whose_frontmatter_cannot_be_constructed_is_withheld_not_raised` | 3 | RK10; finding 5 | yes |
| T19 | `test_the_records_search_route_confines_a_search_to_a_directory` | 1 | RK11; finding 3 | yes |
| T20 | `test_a_frontmatter_closed_inside_a_line_keeps_the_classification_the_base_read` (A2) | 6 | RK13; round 2 finding 1 | no: a regression guard (4 of 6 fail on A1-M1's head) |
| T21 | `test_a_rewritten_note_is_indexed_at_the_classification_it_keeps` (A2) | 1 | RK14; round 2 finding 2 (real Chroma) | yes |

Nothing is marked xfail. The new file is created at M2.

## 7. The contract

### 7.1 M1

**P1-1** `src/probos/knowledge/records_store.py`

SEARCH:
```python
import asyncio
import fnmatch
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from probos.execution.command_env import trusted_command_env
```
REPLACE:
```python
import asyncio
import fnmatch
import logging
import math
import os
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from probos.cognitive.provenance import record_write_time
from probos.execution.command_env import trusted_command_env
```

**P1-2** `src/probos/knowledge/records_store.py`

SEARCH:
```python
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def _markdown_files_or_raise(search_path: Path) -> list[Path]:
```
REPLACE:
```python
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


# BF-952: the keyword axis of Ship's Records search (``RecordsStore.search``).
#
# The base scored a record by the fraction of query words found as substrings of the raw file,
# YAML keys included, and broke ties by path: ``i`` matched "ship", ``status`` matched every
# record, and a conversational question matched the whole repository at one score, so the paths
# that sort first won. A record is now matched on whole words of its body and of the frontmatter
# values in ``_SEARCH_FIELD_WEIGHTS``, and ranked by term rarity: BM25 with field weights, the
# shape BF-625 uses in ``cognitive/transcript_grounding.py``.
_SEARCH_TOKEN_RE = re.compile(r"\w+(?:[-.]\w+)*")
_SEARCH_PART_RE = re.compile(r"\w+")
_SEARCH_STOPWORDS: frozenset[str] = frozenset(
    (
        "a about above after again against all also am an and any are as at be because been before being "
        "below between both but by can could did do does doing down during each few for from further had has "
        "have having he her here hers herself him himself his how i if in into is it its itself just me may "
        "might more most must my myself no nor not now of off on once only or other our ours ourselves out "
        "over own same shall she should so some such than that the their theirs them themselves then there "
        "these they this those through to too under until up us very was we were what when where which while "
        "who whom why will with would you your yours yourself yourselves "
        # what the tokeniser leaves of a contraction: I'd, we'll, I'm, they're, it's, don't, I've
        "d ll m re s t ve"
    ).split()
)
#: Frontmatter fields whose *values* are scored, each weighted against one body occurrence (1.0).
#: Keys, ``classification``, ``status``, the timestamps and ``revision`` are never scored.
#: ``department`` is here because the self-monitoring pull searches by department name.
_SEARCH_FIELD_WEIGHTS: dict[str, float] = {
    "title": 3.0,
    "topic": 3.0,
    "tags": 3.0,
    "department": 2.0,
    "author": 2.0,
}
_SEARCH_BM25_K1 = 1.5
_SEARCH_BM25_B = 0.75
_SEARCH_LIMIT = 20
#: BF-952: search parses every record's frontmatter on each call, and PyYAML's pure-Python scanner
#: was about a third of that cost. libyaml, when installed, parses with the same safe constructor.
_SEARCH_YAML_LOADER: Any = yaml.CSafeLoader if getattr(yaml, "__with_libyaml__", False) else yaml.SafeLoader


def _search_query_terms(query: str) -> list[str]:
    """BF-952: the distinct compound tokens of ``query``, in order, without stopwords.

    A query made only of stopwords keeps them all rather than finding nothing.
    """
    terms = list(dict.fromkeys(match.group() for match in _SEARCH_TOKEN_RE.finditer(query.lower())))
    kept = [term for term in terms if term not in _SEARCH_STOPWORDS]
    return kept or terms


def _search_field_text(value: Any) -> str:
    """BF-952: a frontmatter value as the text to score: a string, or the strings and numbers of a list."""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " ".join(
            str(item) for item in value
            if isinstance(item, (str, int, float)) and type(item) is not bool
        )
    return ""


def _search_document(raw: str) -> tuple[Any, str]:
    """BF-952: ``RecordsStore._parse_document``'s split and result, parsed with libyaml when installed.

    A frontmatter libyaml refuses is parsed again by ``yaml.safe_load``, so a document
    reads here as ``_parse_document`` reads it; a BF-952 test holds the two together.
    """
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.load(parts[1], Loader=_SEARCH_YAML_LOADER) or {}
            except yaml.YAMLError:
                try:
                    frontmatter = yaml.safe_load(parts[1]) or {}
                except yaml.YAMLError:
                    frontmatter = {}
            return frontmatter, parts[2].strip()
    return {}, raw


def _search_record_counts(
    frontmatter: dict[str, Any], body: str, terms: list[str],
) -> tuple[dict[str, float], int]:
    """BF-952: each query term's weighted count in a record, and the record's length in words.

    A body occurrence counts 1 and a field of ``_SEARCH_FIELD_WEIGHTS`` its weight. A plain
    term counts each word (``\\w+``) equal to it, so ``952`` is found inside ``bf-952``; a term
    holding ``-`` or ``.`` counts each whole compound equal to it. The length counts words,
    whatever their weight. A record whose scored text holds no term even as a substring is
    only measured: a term counted as a word is always such a substring, so nothing is lost.
    """
    scored = [(body.lower(), 1.0)]
    scored.extend(
        (_search_field_text(frontmatter.get(name)).lower(), weight)
        for name, weight in _SEARCH_FIELD_WEIGHTS.items()
    )
    words = [_SEARCH_PART_RE.findall(text) for text, _ in scored]
    length = sum(len(found) for found in words)
    weights: dict[str, float] = {}
    if not any(term in text for text, _ in scored for term in terms):
        return weights, length
    compound_terms = [term for term in terms if "-" in term or "." in term]
    for (text, weight), found in zip(scored, words):
        if not found:
            continue
        word_counts = Counter(found)
        compound_counts = Counter(_SEARCH_TOKEN_RE.findall(text)) if compound_terms else word_counts
        for term in terms:
            count = compound_counts[term] if term in compound_terms else word_counts[term]
            if count:
                weights[term] = weights.get(term, 0.0) + weight * count
    return weights, length


def _search_records(
    search_path: Path,
    root: Path,
    terms: list[str],
    *,
    scope: str,
    reader_id: str | None,
    reader_department: str,
) -> list[dict]:
    """BF-952: the walk, parse and ranking of :meth:`RecordsStore.search`, run in a worker thread.

    It reads files under ``search_path`` and touches no store state, so it is safe off the
    event loop. Every record is parsed, not only those that match, because a term's rarity
    is counted over what this reader may read and over nothing else (A4).
    """
    readable: list[tuple[str, dict[str, Any], str, dict[str, float], int]] = []
    for md_file in sorted(search_path.rglob("*.md")):
        rel_path = str(md_file.relative_to(root)).replace("\\", "/")
        if rel_path.startswith("_archived/"):
            continue
        try:
            raw = md_file.read_text(encoding="utf-8")
        except Exception:
            logger.debug("Skipping unreadable file", exc_info=True)
            continue
        frontmatter, content_text = _search_document(raw)
        if type(frontmatter) is not dict:
            # A YAML list or scalar names no classification; the record is withheld
            # rather than read at a default level (it raised on the base).
            logger.debug("BF-952: skipping %s, whose frontmatter is not a mapping", rel_path)
            continue
        # Classification scope + reader-identity check (BF-679)
        if not record_is_readable(
            frontmatter,
            scope=scope,
            reader_id=reader_id,
            reader_department=reader_department,
        ):
            continue
        weights, length = _search_record_counts(frontmatter, content_text, terms)
        readable.append((rel_path, frontmatter, content_text, weights, length))
    if not readable:
        return []

    count = len(readable)
    average_length = sum(entry[4] for entry in readable) / count
    rarity: dict[str, float] = {}
    for term in terms:
        holders = sum(1 for entry in readable if term in entry[3])
        rarity[term] = math.log(1.0 + (count - holders + 0.5) / (holders + 0.5))
    total_rarity = sum(rarity[term] for term in terms)

    ranked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for rel_path, frontmatter, content_text, weights, length in readable:
        matched = [term for term in terms if term in weights]
        if not matched:
            continue
        coverage = min(1.0, sum(rarity[term] for term in matched) / total_rarity)
        norm = 1.0 - _SEARCH_BM25_B + _SEARCH_BM25_B * (length / average_length if average_length else 0.0)
        relevance = sum(
            rarity[term] * weights[term] * (_SEARCH_BM25_K1 + 1.0)
            / (weights[term] + _SEARCH_BM25_K1 * norm)
            for term in matched
        )
        written = record_write_time(frontmatter)
        key = (-coverage, -relevance, written is None, -(written or 0.0), rel_path)
        ranked.append((key, {
            "path": rel_path,
            "frontmatter": frontmatter,
            "score": coverage,
            "snippet": content_text[:200],
        }))
    ranked.sort(key=lambda pair: pair[0])
    return [result for _, result in ranked[:_SEARCH_LIMIT]]


def _markdown_files_or_raise(search_path: Path) -> list[Path]:
```

**P1-3** `src/probos/knowledge/records_store.py`

SEARCH:
```python
    async def search(
        self,
        query: str,
        scope: str = "ship",
        *,
        reader_id: str | None = None,
        reader_department: str = "",
        directory: str = "",
    ) -> list[dict]:
        """Keyword search across records.

        Simple word-matching against frontmatter fields and content.

        BF-679: ``reader_id`` / ``reader_department`` add the identity layer
        :meth:`read_entry` applies, so a caller that knows who is asking no
        longer receives another crew member's ``private`` or out-of-department
        records. The default ``reader_id=None`` means *identity not specified*
        and applies the scope level only; see :func:`record_is_readable` for the
        full tri-state contract.

        BF-949: ``scope`` is one of the four classification labels; any other
        value raises ``ValueError``. ``directory`` confines the walk to that
        directory of the repository, validated as :meth:`list_entries` validates
        it (a path that leaves the repository raises ``ValueError``); ``""`` walks
        the whole repository.
        """
        if type(scope) is not str or scope not in _CLASSIFICATION_LEVELS:
            raise ValueError(
                "Unknown records scope; expected one of: "
                + ", ".join(_CLASSIFICATION_LEVELS)
            )
        search_path = self._safe_path(directory) if directory else self._repo_path
        # BF-949 R1: _safe_path resolves, so a directory's paths are taken against the resolved root
        root = self._repo_path.resolve() if directory else self._repo_path
        query_words = set(query.lower().split())
        results = []
        for md_file in sorted(search_path.rglob("*.md")):
            rel_path = str(md_file.relative_to(root)).replace("\\", "/")
            if rel_path.startswith("_archived/"):
                continue
            try:
                raw = md_file.read_text(encoding="utf-8")
            except Exception:
                logger.debug("Skipping unreadable file", exc_info=True)
                continue

            # Simple keyword match
            raw_lower = raw.lower()
            matches = sum(1 for w in query_words if w in raw_lower)
            if matches > 0:
                fm, content_text = self._parse_document(raw)
                # Classification scope + reader-identity check (BF-679)
                if not record_is_readable(
                    fm,
                    scope=scope,
                    reader_id=reader_id,
                    reader_department=reader_department,
                ):
                    continue
                results.append({
                    "path": rel_path,
                    "frontmatter": fm,
                    "score": matches / len(query_words) if query_words else 0,
                    "snippet": content_text[:200],
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:20]
```

REPLACE:
```python
    async def search(
        self,
        query: str,
        scope: str = "ship",
        *,
        reader_id: str | None = None,
        reader_department: str = "",
        directory: str = "",
    ) -> list[dict]:
        """Keyword search across records.

        BF-952: a record matches on whole words of its body and of the values of
        its ``title``, ``topic``, ``tags``, ``department`` and ``author``
        frontmatter, never on a YAML key or on part of a word. The query's
        stopwords are dropped; a query made only of stopwords keeps them all, and
        a query with no words finds nothing. Records rank by how much of the
        query's rarity they hold, then by BM25 relevance with title, topic and tag
        hits weighted above body hits, then by the newer ``updated`` (else
        ``created``), then by path. ``score`` is the first of these: the summed
        rarity (IDF) of the query terms the record holds over that of all of them,
        between 0 and 1, and it never rises down the list. Rarity is counted only
        over the records this reader may read, so a record withheld from the
        reader cannot move the scores it is shown. A record whose frontmatter is
        not a mapping is skipped. At most 20 results. The walk, parse and ranking
        (:func:`_search_records`) run in a worker thread, so a search does not
        block the event loop; ``scope`` and ``directory`` are checked first, here.

        BF-679: ``reader_id`` / ``reader_department`` add the identity layer
        :meth:`read_entry` applies, so a caller that knows who is asking no
        longer receives another crew member's ``private`` or out-of-department
        records. The default ``reader_id=None`` means *identity not specified*
        and applies the scope level only; see :func:`record_is_readable` for the
        full tri-state contract.

        BF-949: ``scope`` is one of the four classification labels; any other
        value raises ``ValueError``. ``directory`` confines the walk to that
        directory of the repository, validated as :meth:`list_entries` validates
        it (a path that leaves the repository raises ``ValueError``); ``""`` walks
        the whole repository.
        """
        if type(scope) is not str or scope not in _CLASSIFICATION_LEVELS:
            raise ValueError(
                "Unknown records scope; expected one of: "
                + ", ".join(_CLASSIFICATION_LEVELS)
            )
        search_path = self._safe_path(directory) if directory else self._repo_path
        # BF-949 R1: _safe_path resolves, so a directory's paths are taken against the resolved root
        root = self._repo_path.resolve() if directory else self._repo_path
        terms = _search_query_terms(query)
        if not terms:
            return []
        # BF-952: the walk parses every readable record (A4), most of a second on a ship's
        # corpus, so it runs in a worker thread and the event loop stays free meanwhile.
        return await asyncio.to_thread(
            _search_records,
            search_path,
            root,
            terms,
            scope=scope,
            reader_id=reader_id,
            reader_department=reader_department,
        )
```

**P1-4** `tests/test_bf949_notebook_reader_identity.py`

SEARCH:
```python
    hits = await store.search("engineering", scope="ship", reader_id="captain")
    assert [hit["path"] for hit in hits] == [_BRAVO, _ZEPHYR]
```
REPLACE:
```python
    hits = await store.search("engineering", scope="ship", reader_id="captain")
    # BF-952: search ranks by relevance, then by the newer ``updated``, not by path (Zephyr's shorter note now
    # leads). This test is about the walk, so it compares the paths found; the directory walk below must still
    # return the same list in the same order.
    assert {hit["path"] for hit in hits} == {_BRAVO, _ZEPHYR}
```

**P1-5** `tests/test_layer_boundaries.py`

SEARCH:
```python
    # AD-583: knowledge → cognitive.social_verification — pure function import for independence scoring
    ("knowledge/records_store.py", "probos.cognitive.social_verification"),
```
REPLACE:
```python
    # AD-583: knowledge → cognitive.social_verification — pure function import for independence scoring
    ("knowledge/records_store.py", "probos.cognitive.social_verification"),
    # BF-952: knowledge → cognitive.provenance — ``record_write_time``, BF-950's total parser of a record's
    # ``updated``/``created``, breaks search ties by date. A pure function over a dict; provenance.py imports
    # only the standard library, so there is no cycle and no behavioural coupling (AD-583 precedent above).
    ("knowledge/records_store.py", "probos.cognitive.provenance"),
```

### 7.2 M2

**N2-1** `tests/test_bf952_records_keyword_search.py` (new)

```python
"""BF-952 (#1751): Ship's Records keyword search matches whole words and ranks rare ones first.

On the base ``RecordsStore.search`` scored a record by the fraction of query words found as substrings
of the raw file, YAML keys included, and broke ties by path: ``i`` matched "ship", ``status`` matched
every record, and a conversational question matched every record at one score, so the paths that sort
first won. It also ran its whole walk on the event loop. Real fixtures throughout: a real
``RecordsStore`` on ``tmp_path`` with records written to disk as a person or the store writes them,
the real ``OracleService`` (T9) and the real self-monitoring pull (T10). Nothing here replaces
``RecordsStore.search``; T14 wraps its parse function only to observe the thread it runs on.
"""

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from probos.cognitive.oracle_service import OracleService
from probos.config import RecordsConfig
from probos.knowledge import records_store as records_store_module
from probos.knowledge.records_store import RecordsStore
from tests.test_bf949_notebook_reader_identity import _self_monitoring

_QUESTION = (
    "I may have beaten you twice, can you check your memory to verify? "
    "I'm wondering if that memory was pruned."
)
_TARGET = "notebooks/Ezri/pruning.md"
_GAME = "recreation/games/tictactoe/game-1.md"
_EARLY = "2026-01-01T00:00:00+00:00"
_LATE = "2026-06-01T00:00:00+00:00"


async def _store(root: Path) -> RecordsStore:
    store = RecordsStore(RecordsConfig(repo_path=str(root / "ship-records"), auto_commit=False))
    await store.initialize()
    return store


def _write(store: RecordsStore, path: str, body: str, **frontmatter: Any) -> None:
    """A record written straight to disk, so the test sets every frontmatter value (``updated`` included)."""
    values = {"author": "captain", "classification": "ship", "status": "published", **frontmatter}
    target = store.repo_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"---\n{yaml.safe_dump(values, sort_keys=False)}---\n\n{body}\n", encoding="utf-8")


async def _paths(store: RecordsStore, query: str, **reader: Any) -> list[str]:
    return [hit["path"] for hit in await store.search(query, scope="ship", **reader)]


async def _scores(store: RecordsStore, query: str, **reader: Any) -> dict[str, float]:
    return {hit["path"]: hit["score"] for hit in await store.search(query, scope="ship", **reader)}


@pytest.mark.asyncio
async def test_a_question_made_mostly_of_stopwords_finds_the_record_holding_its_rare_terms(tmp_path: Path) -> None:
    """#1751 acceptance 1: the Captain's question no longer matches every record, and the record holding its
    rare terms leads. On the base its ``i``, ``to`` and ``if`` were substrings of every file."""
    store = await _store(tmp_path)
    for index in range(6):
        _write(store, f"reports/filler-{index}.md", "I think that if you can, it is to be done. Was it a good watch?")
    for index in range(3):
        _write(store, f"notebooks/Alpha/memory-{index}.md", "Memory drills went well today.")
    _write(store, _TARGET, "Records show the Captain has beaten me twice; my memory of it was pruned.")
    paths = await _paths(store, _QUESTION, reader_id="captain")
    assert not any(path.startswith("reports/filler-") for path in paths)
    assert len(paths) == 4
    assert paths[0] == _TARGET


@pytest.mark.asyncio
@pytest.mark.parametrize(("body", "query", "found"), [
    pytest.param("ship status nominal", "i", False, id="i-is-not-found-inside-ship"),
    pytest.param("ship status nominal", "a to", False, id="a-and-to-are-not-substrings"),
    pytest.param("The starship docked.", "ship", False, id="ship-is-not-found-inside-starship"),
    pytest.param("Ready when I am.", "i", True, id="a-query-of-stopwords-only-still-matches-the-whole-word"),
])
async def test_words_match_whole_never_as_substrings(tmp_path: Path, body: str, query: str, found: bool) -> None:
    store = await _store(tmp_path)
    _write(store, "reports/entry.md", body)
    assert await _paths(store, query, reader_id="captain") == (["reports/entry.md"] if found else [])


@pytest.mark.asyncio
@pytest.mark.parametrize(("first_written", "last_written"), [
    pytest.param({"updated": _EARLY}, {"updated": _LATE}, id="iso-text"),
    pytest.param({"updated": _EARLY}, {"updated": date(2026, 6, 1)}, id="a-yaml-date"),
    pytest.param({"updated": _EARLY}, {"created": _LATE}, id="created-when-there-is-no-updated"),
    pytest.param({}, {"updated": _EARLY}, id="an-undated-record-goes-last"),
    pytest.param({"updated": "not-a-date"}, {"updated": _EARLY}, id="an-unparsable-date-goes-last"),
])
async def test_equal_scores_put_the_newer_record_first(
    tmp_path: Path, first_written: dict[str, Any], last_written: dict[str, Any],
) -> None:
    """#1751 acceptance 3: ``a-first.md`` sorts first by path, and ``z-last.md`` is the newer or the only dated
    record, so it must lead. On the base the path decided."""
    store = await _store(tmp_path)
    _write(store, "reports/a-first.md", "reactor coolant log", **first_written)
    _write(store, "reports/z-last.md", "reactor coolant log", **last_written)
    hits = await store.search("reactor", scope="ship", reader_id="captain")
    assert hits[0]["score"] == hits[1]["score"]  # premise: a tie on score
    assert [hit["path"] for hit in hits] == ["reports/z-last.md", "reports/a-first.md"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("query", "found"), [
    pytest.param("status", False, id="a-yaml-key"),
    pytest.param("classification", False, id="another-yaml-key"),
    pytest.param("published", False, id="the-status-value"),
    pytest.param("ship", False, id="the-classification-value"),
    pytest.param("survey", True, id="the-title"),
    pytest.param("café", True, id="an-escaped-title-value"),
    pytest.param("reactor", True, id="the-topic"),
    pytest.param("manual", True, id="a-tag"),
    pytest.param("engineering", True, id="the-department"),
    pytest.param("captain", True, id="the-author"),
])
async def test_frontmatter_keys_are_not_scored_and_its_meaningful_values_are(
    tmp_path: Path, query: str, found: bool,
) -> None:
    """``yaml.safe_dump`` writes the title's ``é`` as an escape, so ``café`` is found only in the parsed value,
    never in the raw file: the substring check runs on parsed text (RK7)."""
    store = await _store(tmp_path)
    _write(
        store, "reports/review.md", "Coolant pressure holds.",
        title="Quarterly Warp Survey, Café", topic="reactor-review", tags=["manual"], department="engineering",
    )
    assert await _paths(store, query, reader_id="captain") == (["reports/review.md"] if found else [])


@pytest.mark.asyncio
async def test_a_term_in_a_tag_outranks_the_same_term_in_the_body(tmp_path: Path) -> None:
    """Equal coverage, equal length and equal dates: the tag hit weighs more. On the base the path put the
    body hit first."""
    store = await _store(tmp_path)
    _write(store, "reports/z-tagged.md", "core report", tags=["warp"], updated=_EARLY)
    _write(store, "reports/a-body.md", "warp core report", updated=_EARLY)
    hits = await store.search("warp", scope="ship", reader_id="captain")
    assert hits[0]["score"] == hits[1]["score"] == 1.0  # premise: both hold the only query term
    assert [hit["path"] for hit in hits] == ["reports/z-tagged.md", "reports/a-body.md"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("query", "expected"), [
    pytest.param("bf-952", {"reports/filed.md"}, id="the-whole-identifier"),
    pytest.param("BF-952", {"reports/filed.md"}, id="in-capitals"),
    pytest.param("952", {"reports/filed.md", "reports/apart.md"}, id="one-part"),
])
async def test_an_identifier_matches_whole_and_by_its_parts(tmp_path: Path, query: str, expected: set[str]) -> None:
    store = await _store(tmp_path)
    _write(store, "reports/filed.md", "Filed as BF-952 today.")
    _write(store, "reports/apart.md", "The bf team logged 952 hours.")
    assert set(await _paths(store, query, reader_id="captain")) == expected


@pytest.mark.asyncio
async def test_scores_are_between_zero_and_one_and_never_rise_down_the_list(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    _write(store, "reports/all.md", "reactor coolant pressure nominal")
    _write(store, "reports/two.md", "reactor coolant flush")
    _write(store, "reports/one.md", "reactor inspection")
    _write(store, "reports/none.md", "warp field survey")
    hits = await store.search("reactor coolant pressure", scope="ship", reader_id="captain")
    scores = [hit["score"] for hit in hits]
    assert [hit["path"] for hit in hits] == ["reports/all.md", "reports/two.md", "reports/one.md"]
    assert scores[0] == 1.0 and all(0.0 < score <= 1.0 for score in scores)
    assert scores == sorted(scores, reverse=True) and scores[-1] < 1.0


@pytest.mark.asyncio
@pytest.mark.parametrize(("hidden_path", "hidden_frontmatter", "reader"), [
    pytest.param(
        "notebooks/Bravo/coolant.md", {"author": "Bravo", "classification": "private"}, "alice",
        id="another-crew-members-private-note",
    ),
    pytest.param("_archived/coolant.md", {}, "captain", id="an-archived-record"),
])
async def test_a_record_the_reader_cannot_read_does_not_move_the_scores_it_is_shown(
    tmp_path: Path, hidden_path: str, hidden_frontmatter: dict[str, Any], reader: str,
) -> None:
    """A4: term rarity is counted over what the reader may read. A withheld record that holds a query term
    leaves every score the reader is shown unchanged; the same text where the reader can read it moves it."""
    store = await _store(tmp_path)
    _write(store, "reports/reactor.md", "reactor log")
    _write(store, "reports/warp.md", "warp log")
    before = await _scores(store, "reactor coolant", reader_id=reader)
    assert 0.0 < before["reports/reactor.md"] < 1.0  # control: a partial match, so its score depends on rarity
    _write(store, hidden_path, "coolant coolant coolant", **hidden_frontmatter)
    assert await _scores(store, "reactor coolant", reader_id=reader) == before
    _write(store, "reports/coolant.md", "coolant")
    visible = await _scores(store, "reactor coolant", reader_id=reader)
    assert visible["reports/reactor.md"] != before["reports/reactor.md"]  # control: a readable record does


@pytest.mark.asyncio
async def test_the_oracle_puts_the_game_record_first_for_a_question_naming_the_game(tmp_path: Path) -> None:
    """#1751 acceptance 5 on a fixture, through the real Oracle. On the base the roster notes, which hold the
    question's ``can``, ``you``, ``check``, ``our`` and ``games``, outranked the game record."""
    store = await _store(tmp_path)
    for index in range(4):
        _write(store, f"notebooks/Able/roster-{index}.md", "Can you check the duty roster? Our games night is on hold.")
    _write(store, _GAME, "Tictactoe games: Captain against Ezri. Result: Captain wins.", topic="tictactoe")
    oracle = OracleService(records_store=store)
    results = await oracle.query(
        "can you check our tictactoe games", agent_id="captain", k_per_tier=3, tiers=["records"],
    )
    assert results[0].metadata["path"] == _GAME
    # BF-952 keeps ``score`` in 0..1, and the Oracle still divides the keyword score by ten (RK4).
    assert 0.0 < results[0].score <= 0.1


@pytest.mark.asyncio
async def test_the_notebook_pull_finds_a_note_whose_department_is_only_in_its_frontmatter(tmp_path: Path) -> None:
    """RK1: the self-monitoring pull searches by department name, and the ``department`` value is scored."""
    store = await _store(tmp_path)
    await store.write_notebook("Zephyr", "calibration", "my own calibration log", department="engineering")
    result = await _self_monitoring(store, "Zephyr")
    assert result["notebook_content"]["topic"] == "calibration"


@pytest.mark.asyncio
@pytest.mark.parametrize("frontmatter_text", [
    pytest.param("- a\n- b\n", id="a-yaml-list"),
    pytest.param("just text\n", id="a-yaml-scalar"),
])
async def test_a_record_whose_frontmatter_is_not_a_mapping_is_skipped_not_raised(
    tmp_path: Path, frontmatter_text: str,
) -> None:
    """RK5: on the base such a record raised ``AttributeError`` out of every search that matched it."""
    store = await _store(tmp_path)
    _write(store, "reports/good.md", "warp core report")
    (store.repo_path / "reports" / "bad.md").write_text(
        f"---\n{frontmatter_text}---\n\nwarp core report\n", encoding="utf-8",
    )
    assert await _paths(store, "warp", reader_id="captain") == ["reports/good.md"]


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    pytest.param("", id="empty"),
    pytest.param("   ", id="blank"),
    pytest.param("?!", id="punctuation"),
])
async def test_a_query_with_no_words_finds_nothing(tmp_path: Path, query: str) -> None:
    store = await _store(tmp_path)
    _write(store, "reports/entry.md", "Ready?! Yes.")
    assert await store.search(query, scope="ship", reader_id="captain") == []


@pytest.mark.parametrize("raw", [
    pytest.param("---\nauthor: bones\nclassification: ship\n---\n\nWarp report.\n", id="the-store-shape"),
    pytest.param("---\nupdated: 2026-06-01\n---\nbody", id="a-yaml-date"),
    pytest.param('---\ntitle: "Caf\\xE9"\n---\nbody', id="an-escaped-value"),
    pytest.param("---\n- a\n- b\n---\nbody", id="a-yaml-list"),
    pytest.param("---\n---\nbody", id="empty-frontmatter"),
    pytest.param("---\nkey: [unclosed\n---\nbody", id="malformed-yaml"),
    pytest.param("no frontmatter at all", id="no-frontmatter"),
])
def test_search_reads_a_document_as_the_store_reads_it(tmp_path: Path, raw: str) -> None:
    """RK8: the search parse (libyaml when installed) returns exactly what ``_parse_document`` returns."""
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    assert records_store_module._search_document(raw) == store._parse_document(raw)


@pytest.mark.asyncio
async def test_a_search_runs_off_the_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RK7: the walk, parse and ranking run in a worker thread, so a search never blocks the event loop.
    On the base the whole walk ran on the loop's thread."""
    store = await _store(tmp_path)
    _write(store, "reports/entry.md", "warp core report")
    threads: list[int] = []
    parse = records_store_module._search_document

    def _recording_parse(raw: str) -> tuple[Any, str]:
        threads.append(threading.get_ident())
        return parse(raw)

    monkeypatch.setattr(records_store_module, "_search_document", _recording_parse)
    assert await _paths(store, "warp", reader_id="captain") == ["reports/entry.md"]
    assert threads and threading.get_ident() not in threads
```

## 8. Tracking (M3's commit)

**Head constraint:** neither head may carry a `_STATUS_PATTERNS` keyword (`gen_ad_ledger.py:126-132`) in its first 120 characters.
**Date rule:** both heads carry 2026-11-05. If M3 is committed on another local date (`git log -1 --format=%cs`), use that date.
**Staging:** explicit paths only.
**Re-anchoring (the orchestrator, at build time):** the anchors are those of `1c01a5ee`. The AD-1346 M3e4d6–d8 batch will have added its own PROGRESS head paragraph and DECISIONS entries first.
- BF-952's PROGRESS paragraph goes directly under `# ProbOS Progress`.
- Its DECISIONS entry goes directly above `### BF-950 --`.
- The orchestrator re-checks that each SEARCH matches once on the real base. That is the only re-anchoring allowed.

**P3-1** `PROGRESS.md`

SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-952 (2026-11-05), #1751 -- Ship's Records keyword search matches whole words and ranks rare ones first.** On the base `RecordsStore.search` scored a record by the fraction of query words found as substrings anywhere in the raw file, YAML keys included, and broke ties by path. So `i` matched "ship", `status` matched every record, and the Captain's question to Ezri matched all 2,768 live records at one score, with the three tic-tac-toe records last. Now the query and each record are split into whole words (an identifier such as `bf-952` whole and by its parts). The query's stopwords are dropped, and all its words are kept when nothing else is left. The body and the `title`, `topic`, `tags`, `department` and `author` values are scored, never a key. Records rank by how much of the query's rarity they hold, then by BM25 with title, topic and tag hits above body hits, then by the newer `updated`, then by path. `score` stays between 0 and 1 and never rises down the list. Rarity is counted only over records the reader may read. A record whose frontmatter is a non-empty list or a truthy scalar is skipped instead of raising. Amendment A1 (review round 1): every Ship's Records reader now frames a document the same way, ending the frontmatter only at a `---` that begins a line, so a value holding `---` is no longer cut (BF-940, #1686: on the base such a cut could drop a record's `classification` and show a private record to every reader). Every reader loads frontmatter with libyaml when it is installed and with PyYAML when libyaml refuses it. A frontmatter that does not parse is shown by `read_entry` and search to the Captain alone. Search withholds a record whose timestamp YAML cannot build instead of failing, and scores a number in a scored field. `GET /api/records/search` takes `directory`, which the HXI's notebook search sets to `notebooks`. The walk runs in a worker thread, parses frontmatter with libyaml when installed and counts terms only in records that hold one, so a search no longer blocks the event loop and is no slower than the base's slowest search on a 2,801-record corpus. The return shape, the 20-result cap, BF-679 and BF-949 are unchanged, and so is the Oracle's division of the keyword score by ten. No config field. The contract is `prompts/bf-952-records-keyword-search.md`.

```

**P3-2** `DECISIONS.md`

SEARCH:
```
### BF-950 -- An oracle_query result is aged by its own write time, not by its retrieval (2026-11-05, #1742)
```
REPLACE:
```
### BF-952 -- Ship's Records keyword search matches whole words and ranks rare ones first (2026-11-05, #1751)

- *Scope.* `knowledge/records_store.py` (`RecordsStore.search`, `RecordsStore.read_entry`, `RecordsStore._parse_document`; module functions `_search_query_terms`, `_search_field_text`, `_read_document`, `_search_record_counts`, `_search_records`; `_RECORDS_YAML_LOADER` and the `_SEARCH_*` constants), `routers/records.py` (`search_records` takes `directory`), `ui/src/store/useStore.ts` (the notebook search asks for `notebooks`), a comment in `knowledge/lessons.py`, `tests/test_layer_boundaries.py` (one allowlist entry), `tests/test_bf949_notebook_reader_identity.py` (one order assertion), tests. Contract `prompts/bf-952-records-keyword-search.md`, with Amendment A1 (review round 1).
- *RK1 (matching).* Whole words of the body and of the `title`, `topic`, `tags`, `department` and `author` values; compounds whole and by part; query stopwords dropped, all words kept when nothing else is left. Rejected: substring matching; scoring every frontmatter value.
- *RK2 (rank and score).* IDF-weighted coverage, then BM25 with field weights, then the newer `updated` (else `created`, by BF-950's `record_write_time`), then path. `score` is the coverage, 0 to 1, non-increasing. Rejected: BM25 over the top score; BM25 order with a coverage score.
- *RK3 (privacy).* Term rarity is counted only over records the reader may read; `_archived/` is excluded.
- *RK4 (compatibility).* Return shape, cap, scope and reader rules unchanged; the Oracle's `/10` unchanged, so AD-1141's 0.35 floor still admits no keyword-only record.
- *RK5.* A record whose frontmatter is a non-empty YAML list or a truthy scalar is withheld from search; it raised on the base. A falsy one reads as `{}`, as every reader has read it.
- *RK7 (cost).* A worker thread (`asyncio.to_thread`), libyaml for every reader's parse (A1), and term counting only in records that hold a query term as a substring of their parsed text. Bound: no slower than the base's match-all search, and the event loop is not blocked for more than 100 ms. Rejected for this BF: an in-memory cache (shared state across threads, invalidation, memory); an index is its own item.
- *RK8 (A1).* One parse, `_read_document`, for `_parse_document`, `read_entry` and search: libyaml when installed, `yaml.safe_load` when libyaml refuses, so every reader reads a frontmatter alike. Rejected: `safe_load` in search (about 0.8 s more per call by the first draft's profile, so B1 would fail); parsing with both loaders and preferring PyYAML (both costs).
- *RK9 (A1; BF-940, #1686).* A frontmatter ends at the first `---` that begins a line, not at the first `---` anywhere. On the base a store-written value holding `---` was cut, and a cut that lost `classification` or broke the YAML showed a private record to every reader. Rejected: BF-940 as its own slice first (the same change and a whole extra cycle); fail-closed alone (an `author` holding `---` still parsed, without its classification); the exact-line rule (it would unframe a `---body` closing line the base framed). The skill catalog's splits stay on #1686.
- *RK10 (A1).* A frontmatter that does not parse names no classification, so `read_entry` and search show it to the Captain alone. Search withholds a record whose frontmatter YAML's constructor cannot build (`updated: 2026-13-05`) instead of failing; `read_entry` still raises for it, as on the base. `_parse_document`'s other callers still read an unparseable frontmatter as `{}` (L19).
- *RK11 (A1).* `GET /api/records/search` takes `directory`, checked by the store; the HXI's notebook search asks for `notebooks`, so a note is not cut by the cap of 20 before the client's filter.
- *RK12 (A1).* AD-725's DM knowledge lookup (off by default) now meets its 500 ms abort instead of blocking the loop past it, so on a corpus whose search takes longer it degrades to no recall block (L17). The deadline is unchanged; an index or cache (#1754, N1) is the remedy.
- *Not changed.* `oracle_service.py`, `proactive.py`, `dm_targeted_lookup.py`, `semantic.py`, `record_is_readable`, the skill catalog's parser, the other six stoplists, config.
- *Residual.* Recorded limits L1 to L23 of the contract.
- *Reversal.* Revert the BF-952 commits.

### BF-950 -- An oracle_query result is aged by its own write time, not by its retrieval (2026-11-05, #1742)
```

Then regenerate the ledger (`python -P scripts/gen_ad_ledger.py`) on the real base and stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` as written. Never merge them by hand. **Not updated:** `docs/development/roadmap.md`.

## 9. What this does NOT change, and what is not built

Not changed: `oracle_service.py` (the `/10`, fusion, `query`, `query_formatted`), `proactive.py`, `dm_targeted_lookup.py`, `semantic.py`, `record_is_readable`, the skill catalog's parser (`skill_catalog.py:105`, `:179`, `:790`), the cap of 20, config, `EventType`, persisted shapes, the default executor. Changed by Amendment A1 beyond `search`: `_parse_document` (it delegates to `_read_document`), `read_entry` (an unparseable frontmatter is the Captain's alone), `routers/records.py` (`directory`), `ui/src/store/useStore.ts` (the notebook search's request) and a comment in `knowledge/lessons.py`; §A1.2 lists the effect on each caller. No method is added to `RecordsStore`; its SRP row (`architecture-baseline.yaml:751-757`) is keyed by trigger. Changed by Amendment A2: `_read_document` reads the base's framing wherever A1's line framing would change the classification the base read, through two module functions (`_load_frontmatter`, `_line_framing_is_kept`); `write_entry` hands the semantic index the classification it writes, and its AD-1140 docstring's round-trip sentence is qualified (L24). `semantic.py` is still unchanged.

Not built. Each item is ready for #1754, without redoing the search:

| Item | Why it is not in BF-952 | Evidence |
|---|---|---|
| N1. An index or cache for records search: FTS5, reuse of the semantic backfill corpus, or a `(path, mtime_ns, size)` cache | Each call still reads and parses every file under the walk (RK3), bounded by B1. An index is persisted or shared state with invalidation, and is its own design. #1751 marks it out of scope. §16 reports the live figure. | `records_store.py:1145` walk; #1751 "Also noted"; RK7 option 4 |
| N2. One shared stoplist | Six exist: `codebase_index.py:32`, `knowledge/embeddings.py:39`, `episodic_mock.py:24`, `gap_predictor.py:160`, `oracle_service.py:228`, `referent_gate.py:70` (and `memory_probes.py:34`, derived). Merging them changes five consumers. BF-952 adds a seventh. | `rg "STOPWORDS\|_STOP_WORDS\|stopwords\s*=" src/probos` |
| N3. The passive Oracle drop point (A8) | Keyword records reach `query()` at ≤ 0.1, sort last across tiers (`oracle_service.py:710`) and are cut first by `max_chars` (`:774-775`; 2000 on the DM path, `cognitive_agent.py:11730-11735`). Changing `/10` moves AD-1141's floor and every tier's order. AD-1358 (#1750) option C carries it. | `oracle_service.py:710`, `:774-775`, `:1074` |

## 10. Mutation rows (campaign of record on M2's head)

- Prefix `RKS`. `rg -l "\bRKS-\d" prompts DECISIONS.md PROGRESS.md` finds nothing; the control `rg -l "\bOAM-\d" prompts` finds `prompts/bf-950-oracle-result-age.md`.
- Run an unmutated baseline of the new file and `tests/test_bf949_notebook_reader_identity.py` first, then each row.
- Record the base tree and the sha256 of `records_store.py`, `test_bf952_records_keyword_search.py` and `test_bf949_notebook_reader_identity.py`. A Builder whose files match these hashes does not repeat the campaign. If `records_store.py` differs, rerun every row.
- Every "Line" text occurs exactly once in its file on M2's head; after A1, on A1-M1's head.
- **A1: the campaign of record moves to A1-M1's head.** `records_store.py` changed, so rerun every active row: RKS-1 to RKS-20 and RKS-23 to RKS-34 (32 rows). RKS-21 and RKS-22 are retired. Also record the sha256 of `routers/records.py`.
- Equivalent mutants, not rowed (B1 and B2 cover the cost):
  - deleting `if not terms: return []`;
  - `written is None` → `False`;
  - the RKS-20 line → `if False:` (the check only saves work);
  - in `_read_document`, `frontmatter = yaml.safe_load(block)` → `return None, body` (no input is known that libyaml refuses and PyYAML accepts, L16);
  - RKS-27 where libyaml is not installed (report `yaml.__with_libyaml__`).

| Id | File | Line | Mutate to | What it would break | Killed by |
|---|---|---|---|---|---|
| RKS-1 | records_store.py | `    kept = [term for term in terms if term not in _SEARCH_STOPWORDS]` | `    kept = terms` | stopwords count again | `test_a_question_made_mostly_of_stopwords_finds_the_record_holding_its_rare_terms` |
| RKS-2 | records_store.py | `    return kept or terms` | `    return kept` | a stopword-only query finds nothing | `test_words_match_whole_never_as_substrings` |
| RKS-3 | records_store.py | `_SEARCH_TOKEN_RE = re.compile(r"\w+(?:[-.]\w+)*")` | `_SEARCH_TOKEN_RE = re.compile(r"\w+")` | an identifier matches its scattered parts | `test_an_identifier_matches_whole_and_by_its_parts` |
| RKS-4 | records_store.py | `            count = compound_counts[term] if term in compound_terms else word_counts[term]` | `            count = word_counts[term]` | a whole identifier is never counted | `test_an_identifier_matches_whole_and_by_its_parts` |
| RKS-5 | records_store.py | `    "department": 2.0,` | delete the line | the notebook pull loses notes whose department is only in frontmatter | `test_the_notebook_pull_finds_a_note_whose_department_is_only_in_its_frontmatter` |
| RKS-6 | records_store.py | `    "tags": 3.0,` | `    "tags": 1.0,` | tag hits no longer outrank body hits | `test_a_term_in_a_tag_outranks_the_same_term_in_the_body` |
| RKS-7 | records_store.py | `        rarity[term] = math.log(1.0 + (count - holders + 0.5) / (holders + 0.5))` | `        rarity[term] = 1.0` | rare terms weigh as common ones | `test_a_record_the_reader_cannot_read_does_not_move_the_scores_it_is_shown` |
| RKS-8 | records_store.py | `        if not record_is_readable(` | `        if False and not record_is_readable(` | withheld records enter the statistics and the results | `test_a_record_the_reader_cannot_read_does_not_move_the_scores_it_is_shown` |
| RKS-9 | records_store.py | `        key = (-coverage, -relevance, written is None, -(written or 0.0), rel_path)` | `        key = (-coverage, -relevance, rel_path)` | ties fall to path order | `test_equal_scores_put_the_newer_record_first` |
| RKS-10 | records_store.py | the same line | `        key = (-coverage, -relevance, written is None, (written or 0.0), rel_path)` | the older record leads | `test_equal_scores_put_the_newer_record_first` |
| RKS-11 | records_store.py | `        coverage = min(1.0, sum(rarity[term] for term in matched) / total_rarity)` | `        coverage = len(matched) / len(terms)` | the score ignores rarity | `test_a_record_the_reader_cannot_read_does_not_move_the_scores_it_is_shown` |
| RKS-12 | records_store.py | `        weights, length = _search_record_counts(frontmatter, content_text, terms)` | `        weights, length = _search_record_counts(frontmatter, raw, terms)` | YAML keys are scored again | `test_frontmatter_keys_are_not_scored_and_its_meaningful_values_are` |
| RKS-13 | records_store.py | `        if type(frontmatter) is not dict:` | `        if False:` | a non-mapping frontmatter raises out of search | `test_a_record_whose_frontmatter_is_not_a_mapping_is_skipped_not_raised` |
| RKS-14 | records_store.py | `    if isinstance(value, (list, tuple)):` | `    if False:` | tags are not scored | `test_a_term_in_a_tag_outranks_the_same_term_in_the_body` |
| RKS-15 | records_store.py | `_SEARCH_LIMIT = 20` | `_SEARCH_LIMIT = 21` | the cap changes | `test_the_agents_own_entry_is_found_behind_twenty_readable_matches` (test_bf949) |
| RKS-16 | records_store.py | the RKS-9 line | `        key = (-coverage, 0.0, written is None, -(written or 0.0), rel_path)` | field weights stop deciding the order | `test_a_term_in_a_tag_outranks_the_same_term_in_the_body` |
| RKS-17 | records_store.py | `    "title": 3.0,` | delete the line | titles are not scored | `test_frontmatter_keys_are_not_scored_and_its_meaningful_values_are` |
| RKS-18 | records_store.py | `            "score": coverage,` | `            "score": relevance,` | `score` leaves 0..1 and is no longer the rank key | `test_scores_are_between_zero_and_one_and_never_rise_down_the_list` |
| RKS-19 | records_store.py | `        return await asyncio.to_thread(` | `        return (lambda function, *args, **kwargs: function(*args, **kwargs))(` | the walk runs on the event loop | `test_a_search_runs_off_the_event_loop` |
| RKS-20 | records_store.py | `    if not any(term in text for text, _ in scored for term in terms):` | `    if True:` | no record is ever counted | `test_scores_are_between_zero_and_one_and_never_rise_down_the_list` |
| RKS-21 | (retired by A1: the line is gone; see RKS-24) | | | | |
| RKS-22 | (retired by A1: the line is gone; see RKS-26) | | | | |
| RKS-23 | records_store.py | `        close = raw.find("\n---", 3)` | `        close = raw.find("---", 3) - 1` | the base's framing: a value holding `---` is cut, and a private record reads as `ship` | `test_a_frontmatter_value_holding_three_hyphens_is_read_whole_and_stays_private` |
| RKS-24 | records_store.py | `            body = raw[close + 4:].strip()` | `            body = raw[close + 4:]` | the body keeps the blank line after the frontmatter | `test_every_reader_frames_and_loads_a_document_alike` |
| RKS-25 | records_store.py | `                    return None, body` | `                    return {}, body` | a frontmatter that does not parse reads as `ship` for every reader (the base) | `test_a_record_whose_frontmatter_does_not_parse_is_shown_to_the_captain_alone` |
| RKS-26 | records_store.py | `            return frontmatter or {}, body` | `            return frontmatter, body` | an empty frontmatter reads as unparseable | `test_every_reader_frames_and_loads_a_document_alike` |
| RKS-27 | records_store.py | `_RECORDS_YAML_LOADER: Any = yaml.CSafeLoader if getattr(yaml, "__with_libyaml__", False) else yaml.SafeLoader` | `_RECORDS_YAML_LOADER: Any = yaml.SafeLoader` | a frontmatter only libyaml accepts reads as unparseable again (killed only with libyaml installed) | `test_every_reader_frames_and_loads_a_document_alike` |
| RKS-28 | records_store.py | `    if isinstance(value, (int, float)) and type(value) is not bool:` | `    if False:` | a numeric topic is unsearchable | `test_a_numeric_frontmatter_value_is_scored_and_a_boolean_is_not` |
| RKS-29 | records_store.py | the RKS-28 line | `    if isinstance(value, (int, float)):` | a boolean is scored as `True` | `test_a_numeric_frontmatter_value_is_scored_and_a_boolean_is_not` |
| RKS-30 | records_store.py | `            logger.debug("BF-952: skipping %s, whose frontmatter cannot be constructed", rel_path, exc_info=True)` | `            raise` | one record YAML cannot construct ends every search | `test_a_record_whose_frontmatter_cannot_be_constructed_is_withheld_not_raised` |
| RKS-31 | records_store.py | `            if reader_id != _UNRESTRICTED_READER:` | `            if False:` | search shows an unparseable record to every reader | `test_a_record_whose_frontmatter_does_not_parse_is_shown_to_the_captain_alone` |
| RKS-32 | records_store.py | `            if reader_id != "captain":` (12 spaces; the 8-space line at `:1185` is a different line) | `            if False:` | `read_entry` shows an unparseable record to every reader | `test_a_record_whose_frontmatter_does_not_parse_is_shown_to_the_captain_alone` |
| RKS-33 | records_store.py | `        terms = _search_query_terms(query)` | `        terms = _search_query_terms(query); [path.read_text(encoding="utf-8") for path in search_path.rglob("*.md")]` | a synchronous walk and read run on the event loop | `test_a_search_runs_off_the_event_loop` |
| RKS-34 | routers/records.py | `        results = await runtime._records_store.search(q, scope=scope, reader_id="captain", directory=directory)` | `        results = await runtime._records_store.search(q, scope=scope, reader_id="captain")` | the route ignores `directory`, and the cap cuts the HXI's note again | `test_the_records_search_route_confines_a_search_to_a_directory` |
| RKS-35 | records_store.py | `    if close + 1 > cut:` | `    if close + 1 != cut:` | a frontmatter closed inside a line with no later line beginning `---` loses its keys | `test_every_reader_frames_and_loads_a_document_alike` |
| RKS-36 | records_store.py | `        return framed.get("classification") == legacy["classification"]` | `        return True` | the line framing's unknown or repeated classification is read, and another reader is shown a private record | `test_a_frontmatter_closed_inside_a_line_keeps_the_classification_the_base_read` |
| RKS-37 | records_store.py | `    if type(framed) is not dict:` | `    if False:` | a line framing no loader accepts is not set aside, and the read raises | `test_a_frontmatter_closed_inside_a_line_keeps_the_classification_the_base_read` |
| RKS-38 | records_store.py | `            return framed, raw[close + 4:].strip()` | `            return framed, raw[cut + 3:].strip()` | a record read through the line framing starts its body inside its frontmatter | `test_a_frontmatter_value_holding_three_hyphens_is_read_whole_and_stays_private` |
| RKS-39 | records_store.py | `                    classification=frontmatter["classification"],` | `                    classification=classification,` | a rewrite that keeps a note's classification is indexed at the caller's default | `test_a_rewritten_note_is_indexed_at_the_classification_it_keeps` |
| RKS-40 | records_store.py | `    if cut < 0:` | `    if False:` | a document with no later `---` is framed inside its body | `test_every_reader_frames_and_loads_a_document_alike` |

**A2 re-anchors.** These rows replace the Line and Mutate-to of the rows above with the same id.

| Row | File | Line | Mutate to | Expected effect | Killing test |
|---|---|---|---|---|---|
| RKS-23 | records_store.py | `    close = raw.find("\n---", 3)` | `    close = raw.find("---", 3) - 1` | the line framing is never read; a store-written author holding `---` reads as `ship` | `test_a_frontmatter_value_holding_three_hyphens_is_read_whole_and_stays_private` |
| RKS-24 | records_store.py | `    legacy = _load_frontmatter(raw[3:cut]), raw[cut + 3:].strip()` | `    legacy = _load_frontmatter(raw[3:cut]), raw[cut + 3:]` | the body keeps the blank line after the frontmatter | `test_every_reader_frames_and_loads_a_document_alike` |
| RKS-25 | records_store.py | `            return None  # A1: neither loader accepts the block` | `            return {}  # A1: neither loader accepts the block` | a frontmatter that does not parse reads as `ship` for every reader | `test_a_record_whose_frontmatter_does_not_parse_is_shown_to_the_captain_alone` |
| RKS-26 | records_store.py | `    return frontmatter or {}` | `    return frontmatter` | an empty frontmatter reads as unparseable | `test_every_reader_frames_and_loads_a_document_alike` |

- **A2: the campaign of record moves to A2-M1's head.** `records_store.py` changed, so rerun every active row: RKS-1 to RKS-20 and RKS-23 to RKS-40 (38 rows), with RKS-23 to RKS-26 at their A2 lines. Record the sha256 of `records_store.py`, `routers/records.py` and the new test file.

## 11. Recorded limits

- **L1.** Each call still reads and parses every file under the walk (RK3). The cost is bounded by B1, not removed. An index or cache is N1.
- **L2.** A seventh stoplist, English only (N2).
- **L3.** A record found only by keyword still reaches the Oracle at ≤ 0.1 (N3; AD-1358).
- **L4.** `\w` is Unicode, but there is no non-English stoplist.
- **L5.** `record_write_time` lives in `cognitive/provenance.py`, so it needs one allowlist entry (RK6). Moving it is deferred.
- **L6.** BM25 length normalisation (`_SEARCH_BM25_B`) is not pinned by a mutant.
- **L7.** The date decides only after coverage and relevance tie exactly.
- **L8.** The path is not scored, as on the base.
- **L9.** A file whose frontmatter is a non-empty YAML list or a truthy scalar is invisible to search. On the base it made every matching search raise. A falsy one (`[]`, `false`, `0`, `0.0`, `''`) reads as `{}` for every reader, as on the base, so it is shown at the default level `ship`. Changing that is a policy for the L19 follow-up.
- **L10.** Repeated query words add no weight.
- **L11.** Negations are stopwords.
- **L12.** `test_bf949…:161`'s premise rests on V-BF949. A change to the field set, the weights or the length measure must recheck it.
- **L13.** A cancelled caller cannot stop its worker thread. The walk finishes and its result is dropped.
- **L14.** Searches share the loop's default executor with the other `to_thread` users (21 `src` files). If contention is observed, a dedicated executor is the fallback design, following the precedent at `audio/tts/resident.py:20`.
- **L15.** Without libyaml, the search parse falls back to PyYAML. A call is then slower than B1 but still off the loop.
- **L16.** The `safe_load` fallback for a frontmatter that libyaml refuses and PyYAML accepts is not pinned by a test. No such input is known; the reverse (a tab after a key) is T13's case.
- **L17 (A1, finding 4).** AD-725's DM knowledge lookup (`dm_targeted_lookup.py:159-161`; `timeout_ms` 500, `config_models/agentic.py:178`; `enabled: false` in `config/system.yaml:1669`) now aborts at its deadline while the search's worker runs on. The reviewer measured `None` at 511 ms, with the worker finishing at 1,126 ms on 302 records. The base returned its result at 1,342 ms only because it blocked the loop past the deadline. With the lookup enabled, a knowledge lookup on such a corpus degrades to no recall block, AD-725's own degrade. The deadline is unchanged. The remedy is N1 (an index, or a parsed-record cache keyed by path, `mtime_ns` and size), recommended as #1754's next item.
- **L18 (A1, A2, A3).** A document that starts with `---` and has no later `---` at all has no frontmatter (`{}`, so the default level), as on the base. Every document is framed as the base framed it (RK15). The store's writer always closes with `---` on its own line, so only a hand-made, legacy or truncated file reaches this. Whether an opener with no closing marker should be the Captain's alone is #1686's question: doing so would also hide a raw `.md` written by `write_workspace_file` that opens with a rule.
- **L19 (A1, A2, A3).** Every reader reads a frontmatter that does not parse as `{}`, as on the base: `read_entry`, search, `list_entries`, the similarity and convergence scans, update-in-place (which loses `created` and restarts `revision`), a Captain's `publish` (which rewrites it with only `status` and `updated`) and the semantic backfill. A3 withdraws RK10: under the base's framing a store-written quoted value holding `---` and `: ` does not parse, and RK10 would take the record from its owner. The keyword and semantic paths agree again (BF-679). The policy for each caller, and carrying a parse failure across `read_entry` to the backfill, are #1686's; BF-956 is not filed.
- **L20 (A1).** The skill catalog's own three splits (`cognitive/skill_catalog.py:105`, `:179`, `:790`) keep the base framing. #1686 stays open for them.
- **L21 (A1; withdrawn by A3).** Every reader frames as on the base, so the semantic index holds what the backfill read before BF-952.
- **L22 (A1).** An error of YAML's constructor (`updated: 2026-13-05`) still raises from `_parse_document` and `read_entry`, as on the base, and `list_entries` skips such a record through its `except Exception`. Only search withholds it.
- **L23 (A1).** The route's `directory` is any directory inside the records repository (`_safe_path`). The route reads as the Captain, so a confined search shows nothing a whole-repository search could not.
- **L24 (A2, A3).** `write_entry` writes frontmatter with `yaml.dump`, which tags a tuple or another Python object `!!python/`. No reader loads that tag, so the record reads as `{}` for every reader (L19). Normalizing or rejecting such a value before writing (AD-1140's fail-fast tier) is #1686's.
- **L25 (A3).** The base's framing cuts a value holding `---`, for every reader, as on the base (BF-940, #1686). A store-written `author` holding `---` loses the keys after it (round 1, finding 1). A quoted value holding `---` and `: ` does not parse (L19). A value whose cut prefix is a bad timestamp (`2026-13-05---nominal`) raises from `read_entry`, while search withholds it (round 3, finding 3). A value whose prefix parses reads as that prefix (round 3, finding 1). None of these differs from the base. #1686's acceptance receives T16 and T17 as they stand at `cf61c683`, the round-3 reviewer's corpus and T22, rewritten to its rule.

## 12. Verified Against Codebase (2026-11-05, on `1c01a5ee`)

```
git rev-parse HEAD -> 1c01a5ee9c0375782cfbe7d92206ff970ec40d64 ; git ls-files --eol (touched files) -> i/lf w/crlf
git diff --stat 1c01a5ee feat/ad1346-m3e4d6-d8-store-write-checks-20261105-1c01a5ee -- (the M1/M2 files) -> (empty)
records_store.py:3-14 imports (asyncio present; no math, re, Counter); :48-53 levels; :84-153 record_is_readable
records_store.py:156-164 _jaccard_similarity (only `return len(intersection) / len(union)`); :167 _markdown_files_or_raise
records_store.py:226-244 initialize (no .md written); :305-341 write_entry frontmatter; :488-545 write_notebook
records_store.py:1109-1176 search (sync body, no await); :1161 the only `if not record_is_readable(`
records_store.py:1265-1275 _parse_document: split("---", 2), yaml.safe_load(...) or {}, YAMLError -> {}, strip
provenance.py:13-21 stdlib imports only; :81-90 record_write_time
oracle_service.py:1058-1085 (:1066 awaits search; :1074 /10); :154-226 fusion; :361 semantic default False
oracle_service.py:463-486 "captain" unrestricted; :568-578 query signature; :601-603, :636-648 records tier; :710 sort; :774-775 budget; :1497-1499 graph None -> []
crew_executor.py:779, :785; config_models/agentic.py:1079, :1082
proactive.py:2895-2914; routers/records.py:166-182; dm_targeted_lookup.py:255-270, :279-290; ui useStore.ts:2073-2086
cognitive_agent.py:11722-11735 passive Oracle (k_per_tier=3, max_chars=2000)
transcript_grounding.py:42-48, :182-210 BM25; audio/tts/resident.py:20 "Not loop.set_default_executor"
rg "asyncio\.to_thread\(" src/probos -> 59 hits in 21 files, none in knowledge/ ; rg "yaml\.load\(|CSafeLoader" src/probos -> none
tests/test_ad1346_admission_{file_write,store_family}_census.py: to_thread handoffs are scanned for write callables only
tests/test_layer_boundaries.py:49, :60, :87-88, :181-183; check_architecture_principles.py:80-82, :187-188; baseline.yaml:751-757
tests/test_bf949_notebook_reader_identity.py:23-29, :48-51, :76-91, :150-163, :244-246; gen_ad_ledger.py:1, :126-132
PROGRESS.md:1-3; DECISIONS.md:1349 `### BF-950 -- ...` (unique)
```

**V-BF949.** Length is now the count of `\w+` words in the scored texts. For `engineering` read as Zephyr: every hit has coverage 1.0 and weighted tf 3. An `Able` entry is 8 words (body 5, topic 1, department 1, author 1); Zephyr's is 9 (`own-topic` is two words). So Zephyr ranks 22nd, and `:161` holds. At `:245`, Bravo's entry is 14 words, so Zephyr leads; hence P1-4 compares as a set. T5's two records are 4 words each.

## Absence Verified (2026-11-05, on `1c01a5ee`)

```
A1 CLAIM: four production callers of RecordsStore.search, plus the HXI
   RUN:   rg "\.search\(" src/probos ; rg "records/search" ui/src
   FOUND: oracle_service.py:1066, proactive.py:2898, routers/records.py:179, dm_targeted_lookup.py:265 (work.py:88 is the work store);
          useStore.ts:2073. Matches test_bf949:38-43 _RECORDS_SEARCH_CALLERS.   HOLDS: yes
A2 CLAIM: no test pins a keyword score or path order except test_bf949:245
   RUN:   rg "\[\"score\"\]\s*(==|>|<)" tests (records/oracle files) ; rg "await \w*(store|records|rs)\w*\.search\(" tests
   FOUND: score pins only on mocked OracleResults (ad686:131,:199; bf684:212,:268); real-store assertions are sets or
          single results; only bf949:245 pins order.   HOLDS: yes
A3 CLAIM: no source-scan test reads search's lines
   RUN:   rg "query\.lower\(\)\.split|raw_lower|getsource\(RecordsStore" tests
   FOUND: test_ad582_memory_probes.py:104 (its own fake)   HOLDS: yes
A4 CLAIM: no allowlist entry for records_store -> cognitive.provenance yet
   RUN:   read test_layer_boundaries.py:60-130 ; rg "from probos\.cognitive" src/probos/knowledge
   FOUND: only social_verification (:88; records_store.py:912)   HOLDS: yes, so P1-5 is required
A5 CLAIM: no roadmap row for recent BFs   RUN: rg -c "BF-95[0-3]|BF-94[89]" docs/development/roadmap.md   FOUND: 0   HOLDS: yes
A6 CLAIM: prefix RKS is free   RUN: rg -l "\bRKS-\d" prompts DECISIONS.md PROGRESS.md ; control OAM   FOUND: none ; bf-950 prompt   HOLDS: yes
A7 CLAIM: no repository guard forbids yaml.load with an explicit safe loader
   RUN:   rg -l "yaml\\?\.load\b|unsafe_load" tests ; rg "yaml\.load|B506|bandit" pyproject.toml .pre-commit-config.yaml setup.cfg
   FOUND: none   HOLDS: yes
```

## Absence Verified, Amendment A1 (2026-11-05, on `ac8f7676`)

```
A8  CLAIM: records_store.py holds the only frontmatter loads in knowledge/
    RUN:   Grep 'yaml\.(safe_load|load)\(' src/probos/knowledge
    FOUND: records_store.py:244, :247, :1462 (3 lines)   HOLDS: yes, so A1-03 and A1-07 replace every one
A9  CLAIM: the "---" split occurs in records_store.py twice and in the skill catalog three times, nowhere else in src
    RUN:   Grep 'split\("---"' src/probos
    FOUND: records_store.py:241, :1459; skill_catalog.py:105, :179, :790 (5 lines)   HOLDS: yes
A10 CLAIM: nothing outside the BF-952 files names _search_document or _SEARCH_YAML_LOADER
    RUN:   Grep '_SEARCH_YAML_LOADER|_search_document|CSafeLoader|yaml\.load\(' (repository, excluding logs/)
    FOUND: DECISIONS.md:1351; records_store.py:209, :234, :244, :313; tests/test_bf952…:267, :277, :283;
           prompts/bf-952…:89, :101, :249, :274, :284, :353, :851, :861, :867, :907, :946, :947, :972, :1010, :1051, :1067
           (24 lines: 1 + 4 + 3 + 16)   HOLDS: yes; A1 rewrites each production and test line, and the prompt lines are history
A11 CLAIM: RKS-31's line is new, and RKS-32's 12-space line is new
    RUN:   Grep 'reader_id != _UNRESTRICTED_READER|if reader_id != "captain":' (repository, excluding logs/)
    FOUND: records_store.py:1185 only (8 spaces)   HOLDS: yes
A12 CLAIM: no test reads a cut value back from _parse_document
    RUN:   Grep '_parse_document' tests
    FOUND: test_ad550_notebook_dedup.py:108, :119, :131, :140, :151, :160, :172; test_bf952…:265, :267; test_records_store.py:402, :412 (11 lines)
    HOLDS: yes, by reading their inputs (no "---" inside a value); GA1 runs both files
A13 CLAIM: row ids RKS-23 and up are free
    RUN:   Grep 'RKS-(2[3-9]|[3-9]\d)' (repository, excluding logs/)   FOUND: none   HOLDS: yes
A14 CLAIM: the HXI's notebook search is the only UI caller of /api/records/search
    RUN:   Grep 'runNotebookSearch|records/search' ui/src
    FOUND: useStore.ts:806, :2065, :2073; NotebooksPanel.tsx:9, :37; NotebooksPanel.test.tsx:145, :156 (7 lines)   HOLDS: yes
A15 CLAIM: the Oracle service sets no deadline on its records tier (this file only)
    RUN:   Grep 'wait_for|timeout' src/probos/cognitive/oracle_service.py   FOUND: none   HOLDS: yes, for that file
A16 CLAIM: no AD or BF number is allocated by A1
    RUN:   scripts/ad_ceiling.py -> CEILING AD-1358   HOLDS: yes (the L19 follow-up BF is allocated by the orchestrator)
```

## 13. Deterministic gate checks and prior art

- **`check_architecture_principles.py --check`:** `knowledge` is unranked (`:80-82`). `RecordsStore` gains no method. `to_thread` is awaited, so it is not an unowned task.
- **`test_layer_boundaries.py`:** P1-5 adds the entry.
- **AD-1346 censuses:** `_search_records` holds no write call and no subprocess call. A `to_thread` hand-off is scanned for write callables only.
- **Config:** none. **EventType:** none.
- **Prior art.**
  - Internal: BF-625's BM25 (constants mirrored); BF-950's `record_write_time` (reused); BF-684's rank fusion (unchanged); `asyncio.to_thread` as used in 21 `src` files.
  - External: BM25 and BM25F (Robertson & Zaragoza, 2009); Lucene's non-negative IDF; libyaml's `CSafeLoader`, which uses PyYAML's own safe constructor. All are standard, so no search was spent.
  - Considered and rejected: `rank_bm25` and FTS5 (a dependency, or an index: N1).
  - Blind spots found: the department value; the statistics side channel; non-mapping frontmatter; a non-monotone score; the layer allowlist; the HXI and AD-725 consumers; N3; the event-loop block; YAML-escaped values defeating a raw-text check.

## 14. Diff Reviewer: properties to verify

M1 is a shared contract: review the whole of `search` and its module functions, not only the delta.

1. Each result is a dict with exactly `path`, `frontmatter`, `score`, `snippet`, with at most 20 results and `snippet == content[:200]`. The scope `ValueError`, `directory` validation and `_archived/` exclusion are unchanged, and both errors still raise in the caller before any thread starts.
2. `score` is in (0, 1] and non-increasing down the list; the first sort key is `-score`.
3. A plain term counts `\w+` words equal to it, and a term containing `-` or `.` counts whole compounds equal to it. No substring test decides a match: the substring check (RKS-20 line) only skips records that cannot match, and it runs on the lowered parsed text, never the raw file.
4. Only the body and the `title`, `topic`, `tags`, `department` and `author` values are scored.
5. N, df and average length come only from records that pass `record_is_readable` and lie outside `_archived/` (T8). The BF-679 tri-state is unchanged.
6. Nothing raises out of search on hand-edited frontmatter: a list or scalar frontmatter; a list or numeric `topic` or `tags`; a `date`, `datetime`, unparsable or missing `updated`; a timestamp YAML's constructor refuses (`2026-13-05`, T18). An `Exception` from the parse is contained per record; a `BaseException` is not.
7. Ties after coverage and relevance go to the newer `record_write_time`, undated records last, then path.
8. `_search_records` reads files only: no `self`, no store state, no write. It shares only read-only references (the terms list and module constants). `search` awaits it through `asyncio.to_thread` (T14).
9. (A1) `_read_document` is the one framing and load; `_parse_document`, `read_entry` and search call it. A frontmatter ends at the first `---` that begins a line (T13, T16). libyaml runs first, `yaml.safe_load` on a `YAMLError`, and the result is `None` when both refuse.
10. No caller file changes except `routers/records.py` (`directory`) and the HXI's request; `oracle_service.py:1074` and AD-1141's floor are unchanged.
11. The bf949 edit keeps the test's purpose and carries an inline BF-952 reason. `:161` is untouched and holds (V-BF949).
12. The allowlist entry is exactly `("knowledge/records_store.py", "probos.cognitive.provenance")`, with a justification.
13. Every new docstring, comment and test docstring is true of the head, and each "on the base" claim matches §6.
14. (A1) A frontmatter that does not parse is shown to the Captain alone by `read_entry` and by search (T17). `_parse_document`'s other callers read it as `{}`, as on the base (L19).
15. (A1) A scalar int or float in a scored field is scored as text; a boolean is not (T15).
16. (A1) `GET /api/records/search` forwards `directory` (validated by `RecordsStore.search`; HTTP 400 on traversal). The HXI's notebook search sends `directory=notebooks` and keeps its client filter (T19; `NotebooksPanel.test.tsx`).
17. (A1) T14 records the thread of `rglob`, `read_text`, `_read_document`, `_search_record_counts` and `record_write_time`, and none runs on the loop; RKS-33 fails it.

## 15. Acceptance criteria

1. A conversational query made mostly of stopwords does not match every record, and the record holding its rare terms leads (T1).
2. `i`, `a` and `to` never match as substrings (T2).
3. Equal scores are ordered by the newer `updated` (T3).
4. `tests/test_records_store.py` and `tests/test_ad725_dm_targeted_lookup.py` pass unchanged; `test_bf949…:245` is updated with its reason.
5. The game record leads through the real Oracle (T9), and the live copy (§16) puts the game records in the top 3 for `tictactoe Captain Ezri` and `can you check our tictactoe games`.
6. B1 and B2 hold on the synthetic corpus, and a search runs off the event loop (T14).
7. Every §10 mutant is killed; G1 to G3, GA1 and the §13 checks pass; the broad gate's receipt is green.
8. (A1) A store-written value holding `---` reads back whole and a private record stays private (T16). A frontmatter that does not parse is the Captain's alone (T17).
9. (A1) A numeric topic is searchable (T15). A timestamp YAML cannot build withholds only its record (T18). The route confines a search to a directory, and the HXI asks for notebooks (T19, vitest).
10. (A1) §16 step 2 reports the census counts.
11. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Orchestrator steps after the build (never a Builder step)

The Builder must not read `%LOCALAPPDATA%\ProbOS` or `d:\ProbOS\data`.

1. **B1 and B2** on the synthetic corpus, on M2's head, before the Diff Reviewer (§4); after Amendment A1, again on A1-M1's head, before review round 2 (the parse changed). Report the six medians (base and candidate × three queries), the maximum ticker overshoot and `yaml.__with_libyaml__`. Failure is a hard stop that comes back to the Architect.
2. **Live copy, after the broad gate.**
   - `git clone` the live records repository into a new, empty temporary directory. It is read-only toward the source, never written back, and deleted afterwards.
   - Open `RecordsStore(RecordsConfig(repo_path=<clone>, auto_commit=False))` and call `search(q, scope="ship", reader_id="captain")` three times each for `Hello Ezri`, the Captain's question, `good game`, `tictactoe Captain Ezri` and `can you check our tictactoe games`. Run the same B2 ticker during one call.
   - Report only: results returned (cap 20); the rank of each `recreation/games/tictactoe/` record, or "not in top 20"; the median per call; the maximum overshoot; the record count. No record text, other paths or frontmatter.
   - Record the result on #1751. If a game record misses the top 3 for either named query, or B2 fails on the live copy, return to the Architect before closing.
   - **Census (A1; BF-940, #1686), on the same clone, adding no access.** For every `*.md` outside `_archived/`, compare the base parse (`_parse_document` of `a745e447`'s `records_store.py`, imported from a base checkout) with the head's `_read_document`. Report counts only: files; equal; differing; differing in `classification`; head `None` (does not parse); head constructor error. If any record's `classification` differs, or any record does not parse, report it to the Captain before closing: a private record may have been readable on the vessel, and its semantic index entry needs re-indexing (L21).

## Amendment A1 (2026-11-05): review round 1 (GPT-6.1 Sol, NOT READY)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-05. **Anchors:** candidate head `ac8f7676` (tree `ebee3ef9`). Line numbers are those of `ac8f7676`. SEARCH text written by M1: A1-01 to A1-05. Written by M2: A1-12 to A1-16. Written by M3: A1-19 to A1-21. Every other SEARCH is base text, unchanged on `ac8f7676`.

### A1.1 Findings and decisions

| # | Finding | Decision |
|---|---|---|
| 1 | `raw.split("---", 2)` cuts a value holding `---`. A cut that loses `classification` or breaks the YAML reads as `ship`, so a private record is shown to every reader (on the base; #1686) | **RK9:** one framing for every reader. The frontmatter ends at the first `---` that begins a line. **RK10:** a frontmatter that does not parse is the Captain's alone in `read_entry` and search. The skill catalog stays on #1686. |
| 2 | A scalar number in a scored field is dropped | Scored as text; a boolean is not (A1-02) |
| 3 | The HXI filters after the cap of 20 | **RK11:** the route forwards `directory`; the HXI sends `notebooks` |
| 4 | The DM lookup's 500 ms abort now fires | **RK12:** unchanged; recorded as L17; N1 (#1754) is the remedy |
| 5 | A constructor `ValueError` ends the whole search | A per-record boundary in the worker withholds the record (A1-04) |
| 6 | libyaml and PyYAML disagree | **RK8:** one load, libyaml then PyYAML, for every reader (A1-03) |
| V1 to V3 | T14 too narrow; T1 docstring; non-mapping wording | T14 rewritten; docstring; RK5, L9, §14 |

### A1.2 What changes for each caller

| Caller | Framing (RK9) | Loader (RK8) | Frontmatter that does not parse | Constructor error |
|---|---|---|---|---|
| `write_entry` update-in-place (`:516`) | Whole: `created` and `revision` carry forward for a value holding `---` | A tab-only frontmatter now parses | `{}` (base) | Its `except Exception` (base) |
| `check_notebook_similarity` (`:857`, `:926`, `:944`), `check_cross_agent_convergence` (`:1022`, `:1043`) | Whole | As above | `{}` (base) | As on the base |
| `read_entry` (`:1182`) | Whole | As above | **Non-Captain readers: `None`. The Captain: `{}`** | Raises (base) |
| `list_entries` (`:1236`) | Whole | As above | `{}`, listed (base; L19) | Skipped (base) |
| `publish` (`:1291`) | Whole: a Captain's publish no longer rewrites a cut frontmatter | As above | `{}` (base; L19) | Raises (base) |
| `search`: Oracle keyword axis, notebook pull, DM lookup (agent readers) | Whole | As above | **Withheld** | **Withheld** (on the base it raised when the record matched) |
| `search`: HXI route (the Captain) | Whole; `directory` | As above | Shown with `{}` | Withheld |
| Semantic indexer (`semantic.py:738`, `read_entry` as the Captain) | Whole (correct classification on its next index) | As above | `{}` (base; L19, L21) | Raises (base) |
| A document with `---` lines in its body | Unchanged: the closing line is still the first `---` that begins a line | n/a | n/a | n/a |

The premise behind RK9 is that a frontmatter written by `yaml.dump` starts no line of a value with `---`. PyYAML's emitter indents continuation lines and quotes a key that starts with `---`. That was checked by reading the emitter, not by running it. T16's multi-line case checks it, and GA1 makes that case a hard stop.

### A1.3 Gates

- **GA1 (A1-M1's head):**
  - Run `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf952_records_keyword_search.py <the 18 G1 files> tests/test_ad1341_s4_lessons.py tests/test_ad550_notebook_dedup.py -q -n 0`.
  - Expected in the new file: **58 passed** (19 functions, counted by reading). Every other file: 0 failed, with counts equal to M0. Record M0 for the two added files on `ac8f7676`.
  - Then run `... -P scripts/check_architecture_principles.py --check`.
  - Then, in `ui/`, run `npx vitest run src/__tests__/NotebooksPanel.test.tsx`. Expected: 0 failed and an unchanged count.
  - **Hard stop:** any T16 case fails, or T13's `a-tab-only-libyaml-accepts` case fails with `yaml.__with_libyaml__` true.
- **Then B1 and B2** (§4) and the **§10 campaign** (32 active rows), both on A1-M1's head. Report `yaml.__with_libyaml__`.
- **G3** after A1-M2.

### A1.4 Pairs: A1-M1

**A1-01** `src/probos/knowledge/records_store.py` (M1 text)

SEARCH:
```python
_SEARCH_LIMIT = 20
#: BF-952: search parses every record's frontmatter on each call, and PyYAML's pure-Python scanner
#: was about a third of that cost. libyaml, when installed, parses with the same safe constructor.
_SEARCH_YAML_LOADER: Any = yaml.CSafeLoader if getattr(yaml, "__with_libyaml__", False) else yaml.SafeLoader
```
REPLACE:
```python
_SEARCH_LIMIT = 20
#: BF-952: every Ship's Records reader loads frontmatter with libyaml when it is installed (search
#: parses every record on each call, and PyYAML's pure-Python scanner was about a third of that
#: cost). libyaml uses PyYAML's own safe constructor; ``_read_document`` falls back to
#: ``yaml.safe_load`` for a frontmatter libyaml refuses.
_RECORDS_YAML_LOADER: Any = yaml.CSafeLoader if getattr(yaml, "__with_libyaml__", False) else yaml.SafeLoader
```

**A1-02** `src/probos/knowledge/records_store.py` (M1 text)

SEARCH:
```python
def _search_field_text(value: Any) -> str:
    """BF-952: a frontmatter value as the text to score: a string, or the strings and numbers of a list."""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
```
REPLACE:
```python
def _search_field_text(value: Any) -> str:
    """BF-952: a frontmatter value as the text to score: a string, a number, or the strings and numbers of a list.

    A boolean is not text, alone or in a list (A1, finding 2).
    """
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and type(value) is not bool:
        return str(value)
    if isinstance(value, (list, tuple)):
```

**A1-03** `src/probos/knowledge/records_store.py` (M1 text)

SEARCH:
```python
def _search_document(raw: str) -> tuple[Any, str]:
    """BF-952: ``RecordsStore._parse_document``'s split and result, parsed with libyaml when installed.

    A frontmatter libyaml refuses is parsed again by ``yaml.safe_load``, so a document
    reads here as ``_parse_document`` reads it; a BF-952 test holds the two together.
    """
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.load(parts[1], Loader=_SEARCH_YAML_LOADER) or {}
            except yaml.YAMLError:
                try:
                    frontmatter = yaml.safe_load(parts[1]) or {}
                except yaml.YAMLError:
                    frontmatter = {}
            return frontmatter, parts[2].strip()
    return {}, raw
```
REPLACE:
```python
def _read_document(raw: str) -> tuple[Any, str]:
    """BF-952 A1: a Ship's Records document's frontmatter and body, the one parse every reader uses.

    ``RecordsStore._parse_document``, ``RecordsStore.read_entry`` and the search all call it.

    Framing (BF-940, #1686): a document that starts with ``---`` has frontmatter up to the
    first later ``---`` that begins a line, and its body is what follows that ``---``,
    stripped. The base ended the frontmatter at the first ``---`` anywhere, so a value
    holding one inside a line (``topic: Inspection --- nominal``) was cut, the keys after
    it were lost or the YAML stopped parsing, and the record read with no classification.
    A store-written value holding ``---`` now stays whole (T16 writes four through
    ``write_entry``). A document whose frontmatter is not closed by a line beginning
    ``---`` has no frontmatter here.

    Loading: libyaml (``_RECORDS_YAML_LOADER``) when installed, then ``yaml.safe_load``
    when libyaml refuses the text, so a frontmatter either loader accepts is read, and
    every reader reads it alike. An empty or falsy frontmatter is ``{}``. ``None`` means a
    frontmatter block is there and neither loader accepts it. An error of YAML's
    constructor (``updated: 2026-13-05`` raises ``ValueError``) propagates, as it did from
    ``_parse_document`` on the base.
    """
    if raw.startswith("---"):
        close = raw.find("\n---", 3)
        if close >= 0:
            block = raw[3:close + 1]
            body = raw[close + 4:].strip()
            try:
                frontmatter = yaml.load(block, Loader=_RECORDS_YAML_LOADER)
            except yaml.YAMLError:
                try:
                    frontmatter = yaml.safe_load(block)
                except yaml.YAMLError:
                    return None, body
            return frontmatter or {}, body
    return {}, raw
```

**A1-04** `src/probos/knowledge/records_store.py` (M1 text)

SEARCH:
```python
            logger.debug("Skipping unreadable file", exc_info=True)
            continue
        frontmatter, content_text = _search_document(raw)
        if type(frontmatter) is not dict:
            # A YAML list or scalar names no classification; the record is withheld
            # rather than read at a default level (it raised on the base).
            logger.debug("BF-952: skipping %s, whose frontmatter is not a mapping", rel_path)
            continue
```
REPLACE:
```python
            logger.debug("Skipping unreadable file", exc_info=True)
            continue
        try:
            frontmatter, content_text = _read_document(raw)
        except Exception:
            # A1: YAML accepted the frontmatter and its constructor raised (``updated: 2026-13-05``
            # is a ``ValueError``, not a ``YAMLError``). ``read_entry`` raises for such a record;
            # the search withholds it rather than end every search or read it as ``{}``.
            logger.debug("BF-952: skipping %s, whose frontmatter cannot be constructed", rel_path, exc_info=True)
            continue
        if frontmatter is None:
            # A1: a frontmatter block no loader accepts names no classification, so the record
            # is shown to the Captain alone, as ``read_entry`` rules.
            if reader_id != _UNRESTRICTED_READER:
                logger.debug("BF-952: withholding %s, whose frontmatter does not parse", rel_path)
                continue
            frontmatter = {}
        if type(frontmatter) is not dict:
            # A non-empty YAML list or a truthy scalar names no classification; the record is
            # withheld rather than read at a default level (it raised on the base). A falsy one
            # (``[]``, ``false``, ``0``, ``''``) is ``{}``, as every reader has read it.
            logger.debug("BF-952: skipping %s, whose frontmatter is not a mapping", rel_path)
            continue
```

**A1-05** `src/probos/knowledge/records_store.py` (M1 text: the `search` docstring)

SEARCH:
```python
        reader cannot move the scores it is shown. A record whose frontmatter is
        not a mapping is skipped. At most 20 results. The walk, parse and ranking
        (:func:`_search_records`) run in a worker thread, so a search does not
        block the event loop; ``scope`` and ``directory`` are checked first, here.
```
REPLACE:
```python
        reader cannot move the scores it is shown. A record whose frontmatter is
        a non-empty YAML list or a truthy scalar, or one YAML's constructor cannot
        build (``updated: 2026-13-05``), is skipped; one whose frontmatter does not
        parse is shown to the Captain alone, as :meth:`read_entry` rules (A1). A
        number in ``title``, ``topic``, ``tags``, ``department`` or ``author`` is
        scored as text; a boolean is not. At most 20 results. The walk, parse and
        ranking (:func:`_search_records`) run in a worker thread, so a search does
        not block the event loop; ``scope`` and ``directory`` are checked first, here.
```

**A1-06** `src/probos/knowledge/records_store.py` (base text: `read_entry`)

SEARCH:
```python
        raw = file_path.read_text(encoding="utf-8")
        frontmatter, content = self._parse_document(raw)

        # Classification check — Captain has unrestricted read access
```
REPLACE:
```python
        raw = file_path.read_text(encoding="utf-8")
        frontmatter, content = _read_document(raw)
        if frontmatter is None:
            # BF-952 A1: a frontmatter block that no loader accepts names no classification.
            # The base read it as ``{}``, so as ``ship``, and showed it to every reader; now
            # only the Captain, who reads every record, is shown it.
            if reader_id != "captain":
                return None
            frontmatter = {}

        # Classification check — Captain has unrestricted read access
```

**A1-07** `src/probos/knowledge/records_store.py` (base text)

SEARCH:
```python
    def _parse_document(self, raw: str) -> tuple[dict, str]:
        """Parse YAML frontmatter + content from a markdown document."""
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                try:
                    fm = yaml.safe_load(parts[1]) or {}
                except yaml.YAMLError:
                    fm = {}
                return fm, parts[2].strip()
        return {}, raw
```
REPLACE:
```python
    def _parse_document(self, raw: str) -> tuple[dict, str]:
        """Parse YAML frontmatter + content from a markdown document.

        BF-952 A1: :func:`_read_document` frames and loads it, as it does for ``read_entry``
        and the search. A frontmatter block that no loader accepts reads as ``{}`` here, as
        on the base; ``read_entry`` and the search show such a record to the Captain alone.
        """
        frontmatter, content = _read_document(raw)
        return ({} if frontmatter is None else frontmatter), content
```

**A1-08** `src/probos/routers/records.py` (base text)

SEARCH:
```python
@router.get("/search")
async def search_records(q: str = "", scope: str = "ship", runtime: Any = Depends(get_runtime)) -> Any:
    """Search Ship's Records by keyword.

    BF-949: the search reads as the Captain, the reader ``GET /documents/{path}``
    defaults to, so the scope level alone bounds the results. A ``scope`` that is
    not a classification label is HTTP 400.
    """
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    if not q:
        return JSONResponse({"error": "query parameter 'q' required"}, status_code=400)
    try:
        results = await runtime._records_store.search(q, scope=scope, reader_id="captain")
```
REPLACE:
```python
@router.get("/search")
async def search_records(
    q: str = "", scope: str = "ship", directory: str = "", runtime: Any = Depends(get_runtime),
) -> Any:
    """Search Ship's Records by keyword.

    BF-949: the search reads as the Captain, the reader ``GET /documents/{path}``
    defaults to, so the scope level alone bounds the results. A ``scope`` that is
    not a classification label is HTTP 400.

    BF-952 A1: ``directory`` confines the walk to that directory of the repository
    before the cap of 20, as ``RecordsStore.search`` confines it (a path that leaves
    the repository is HTTP 400); ``""`` searches the whole repository. The HXI's
    notebook search asks for ``notebooks``, so a note is not cut by twenty better
    matches elsewhere.
    """
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    if not q:
        return JSONResponse({"error": "query parameter 'q' required"}, status_code=400)
    try:
        results = await runtime._records_store.search(q, scope=scope, reader_id="captain", directory=directory)
```

**A1-09** `ui/src/store/useStore.ts` (base text)

SEARCH:
```ts
    set({ notebooksLoading: true });
    try {
      const res = await fetch(`/api/records/search?q=${encodeURIComponent(q)}&scope=ship`);
```
REPLACE:
```ts
    set({ notebooksLoading: true });
    try {
      // BF-952 A1: the server confines the walk to notebooks/ before its cap of 20, so a note
      // is not cut by twenty better matches elsewhere; the filter below stays as a guard.
      const res = await fetch(`/api/records/search?q=${encodeURIComponent(q)}&scope=ship&directory=notebooks`);
```

**A1-10** `ui/src/store/useStore.ts` (base text)

SEARCH:
```ts
      // Filter to notebooks/* only — search runs over all records
```
REPLACE:
```ts
      // Filter to notebooks/* only — a guard; the server already confined the walk (BF-952 A1)
```

**A1-11** `src/probos/knowledge/lessons.py` (base text)

SEARCH:
```python
# A4 (R2-F3): Ship's Records splits a document's frontmatter at the first two "---" it finds, inside a value too
# (records_store._parse_document, register R25), so an envelope value holding one would come back cut short.
_FRONTMATTER_DELIMITER = "---"
```
REPLACE:
```python
# A4 (R2-F3): Ship's Records split a document's frontmatter at the first two "---" it found, inside a value too
# (records_store._parse_document, register R25), so an envelope value holding one came back cut short. BF-952 A1
# ends the frontmatter only at a "---" that begins a line; this rule still refuses "---" and is unchanged.
_FRONTMATTER_DELIMITER = "---"
```

**A1-12** `tests/test_bf952_records_keyword_search.py` (M2 text)

SEARCH:
```python
the real ``OracleService`` (T9) and the real self-monitoring pull (T10). Nothing here replaces
``RecordsStore.search``; T14 wraps its parse function only to observe the thread it runs on.
```
REPLACE:
```python
the real ``OracleService`` (T9), the real self-monitoring pull (T10) and the real ``search_records``
route function (T19). Nothing here replaces ``RecordsStore.search``; T14 wraps the path methods and
module functions the walk calls only to observe the thread each runs on.
```

**A1-13** `tests/test_bf952_records_keyword_search.py` (M2 text)

SEARCH:
```python
import threading
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from probos.cognitive.oracle_service import OracleService
from probos.config import RecordsConfig
from probos.knowledge import records_store as records_store_module
from probos.knowledge.records_store import RecordsStore
from tests.test_bf949_notebook_reader_identity import _self_monitoring
```
REPLACE:
```python
import threading
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from fastapi.responses import JSONResponse

from probos.cognitive.oracle_service import OracleService
from probos.config import RecordsConfig
from probos.knowledge import records_store as records_store_module
from probos.knowledge.records_store import RecordsStore
from probos.routers.records import search_records
from tests.test_bf949_notebook_reader_identity import _self_monitoring
```

**A1-14** `tests/test_bf952_records_keyword_search.py` (M2 text)

SEARCH:
```python
    """#1751 acceptance 1: the Captain's question no longer matches every record, and the record holding its
    rare terms leads. On the base its ``i``, ``to`` and ``if`` were substrings of every file."""
```
REPLACE:
```python
    """#1751 acceptance 1: the Captain's question no longer matches every record, and the record holding its
    rare terms leads. On the base its ``i`` and ``if`` were substrings of every file here (both are inside the
    ``classification`` key), so every file matched it."""
```

**A1-15** `tests/test_bf952_records_keyword_search.py` (M2 text)

SEARCH:
```python
@pytest.mark.parametrize("raw", [
    pytest.param("---\nauthor: bones\nclassification: ship\n---\n\nWarp report.\n", id="the-store-shape"),
    pytest.param("---\nupdated: 2026-06-01\n---\nbody", id="a-yaml-date"),
    pytest.param('---\ntitle: "Caf\\xE9"\n---\nbody', id="an-escaped-value"),
    pytest.param("---\n- a\n- b\n---\nbody", id="a-yaml-list"),
    pytest.param("---\n---\nbody", id="empty-frontmatter"),
    pytest.param("---\nkey: [unclosed\n---\nbody", id="malformed-yaml"),
    pytest.param("no frontmatter at all", id="no-frontmatter"),
])
def test_search_reads_a_document_as_the_store_reads_it(tmp_path: Path, raw: str) -> None:
    """RK8: the search parse (libyaml when installed) returns exactly what ``_parse_document`` returns."""
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    assert records_store_module._search_document(raw) == store._parse_document(raw)
```
REPLACE:
```python
_LIBYAML = bool(getattr(yaml, "__with_libyaml__", False))


@pytest.mark.parametrize(("raw", "frontmatter", "body"), [
    pytest.param(
        "---\nauthor: bones\nclassification: ship\n---\n\nWarp report.\n",
        {"author": "bones", "classification": "ship"}, "Warp report.", id="the-store-shape",
    ),
    pytest.param(
        "---\ntopic: Inspection --- nominal\nclassification: private\n---\nbody",
        {"topic": "Inspection --- nominal", "classification": "private"}, "body", id="a-value-holding-three-hyphens",
    ),
    pytest.param(
        "---\ntopic: 'Inspection --- status: nominal'\nclassification: private\n---\nbody",
        {"topic": "Inspection --- status: nominal", "classification": "private"}, "body",
        id="a-quoted-value-holding-a-key",
    ),
    pytest.param(
        "---\nauthor: bones\n---\nabove\n---\nbelow", {"author": "bones"}, "above\n---\nbelow",
        id="a-body-holding-a-rule",
    ),
    pytest.param("---\nupdated: 2026-06-01\n---\nbody", {"updated": date(2026, 6, 1)}, "body", id="a-yaml-date"),
    pytest.param('---\ntitle: "Caf\\xE9"\n---\nbody', {"title": "Café"}, "body", id="an-escaped-value"),
    pytest.param("---\n---\nbody", {}, "body", id="empty-frontmatter"),
    pytest.param("---\n[]\n---\nbody", {}, "body", id="a-falsy-frontmatter-reads-as-empty"),
    pytest.param("---\nkey: [unclosed\n---\nbody", None, "body", id="malformed-yaml"),
    pytest.param(
        "---\nclassification:\tprivate\n---\nbody", {"classification": "private"} if _LIBYAML else None, "body",
        id="a-tab-only-libyaml-accepts",
    ),
    pytest.param("no frontmatter at all", {}, "no frontmatter at all", id="no-frontmatter"),
])
def test_every_reader_frames_and_loads_a_document_alike(
    tmp_path: Path, raw: str, frontmatter: dict[str, Any] | None, body: str,
) -> None:
    """A1 (BF-940, #1686; finding 6): ``_read_document`` is the one parse. ``_parse_document`` reads ``None`` (a
    frontmatter block no loader accepts) as ``{}``, as on the base. The base cut the second and third cases at the
    ``---`` inside the topic, and the third then did not parse. A tab after a key is refused by PyYAML's scanner
    and accepted by libyaml, so with libyaml installed every reader now reads it."""
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    assert records_store_module._read_document(raw) == (frontmatter, body)
    assert store._parse_document(raw) == ({} if frontmatter is None else frontmatter, body)
```

**A1-16** `tests/test_bf952_records_keyword_search.py` (M2 text: T14 rewritten; T15 to T19 appended)

SEARCH:
```python
@pytest.mark.asyncio
async def test_a_search_runs_off_the_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RK7: the walk, parse and ranking run in a worker thread, so a search never blocks the event loop.
    On the base the whole walk ran on the loop's thread."""
    store = await _store(tmp_path)
    _write(store, "reports/entry.md", "warp core report")
    threads: list[int] = []
    parse = records_store_module._search_document

    def _recording_parse(raw: str) -> tuple[Any, str]:
        threads.append(threading.get_ident())
        return parse(raw)

    monkeypatch.setattr(records_store_module, "_search_document", _recording_parse)
    assert await _paths(store, "warp", reader_id="captain") == ["reports/entry.md"]
    assert threads and threading.get_ident() not in threads
```
REPLACE:
```python
@pytest.mark.asyncio
async def test_a_search_runs_off_the_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RK7: the walk, the reads, the parse and the ranking all run in a worker thread, so a search never blocks
    the event loop. The test records the thread of each step: ``rglob`` and ``read_text`` on the store's own path
    class, and the module functions the walk calls. On the base the whole walk ran on the loop's thread (and
    ``_read_document`` does not exist there, so the test fails at setup)."""
    store = await _store(tmp_path)
    _write(store, "reports/entry.md", "warp core report")
    seen: dict[str, list[int]] = {"rglob": [], "read_text": [], "parse": [], "count": [], "rank": []}
    path_type = type(store.repo_path)

    def _recording(step: str, function: Any) -> Any:
        def record(*args: Any, **kwargs: Any) -> Any:
            seen[step].append(threading.get_ident())
            return function(*args, **kwargs)
        return record

    monkeypatch.setattr(path_type, "rglob", _recording("rglob", path_type.rglob))
    monkeypatch.setattr(path_type, "read_text", _recording("read_text", path_type.read_text))
    monkeypatch.setattr(records_store_module, "_read_document", _recording("parse", records_store_module._read_document))
    monkeypatch.setattr(
        records_store_module, "_search_record_counts", _recording("count", records_store_module._search_record_counts),
    )
    monkeypatch.setattr(
        records_store_module, "record_write_time", _recording("rank", records_store_module.record_write_time),
    )
    assert await _paths(store, "warp", reader_id="captain") == ["reports/entry.md"]
    loop_thread = threading.get_ident()
    assert all(seen.values()), seen  # premise: every step ran
    assert not any(loop_thread in threads for threads in seen.values()), seen


@pytest.mark.asyncio
@pytest.mark.parametrize(("topic", "query", "found"), [
    pytest.param(314159, "314159", True, id="an-integer-topic"),
    pytest.param(2.5, "2.5", True, id="a-float-topic"),
    pytest.param(True, "true", False, id="a-boolean-topic-is-not-text"),
])
async def test_a_numeric_frontmatter_value_is_scored_and_a_boolean_is_not(
    tmp_path: Path, topic: Any, query: str, found: bool,
) -> None:
    """Finding 2: ``POST /api/records/notebooks/{callsign}`` hands its JSON ``topic`` to ``write_notebook`` as it
    came (``routers/records.py:146``, ``:151-160``), so a number is stored as a number. The base found it as a
    substring of the raw file, and the candidate before A1 dropped it; a list's numbers were already scored. A
    boolean is not text, alone or in a list."""
    store = await _store(tmp_path)
    path = await store.write_notebook("Ezri", topic, "coolant log")
    assert await _paths(store, query, reader_id="captain") == ([path] if found else [])


@pytest.mark.asyncio
@pytest.mark.parametrize(("author", "values"), [
    pytest.param("Ezri---Prime", {}, id="an-author-holding-three-hyphens"),
    pytest.param("Ezri", {"topic": "Inspection --- status: nominal"}, id="a-quoted-topic-holding-a-key"),
    pytest.param("Ezri", {"topic": "first line\n---\nlast line"}, id="a-multi-line-topic-holding-a-rule"),
    pytest.param("Ezri", {"tags": ["warp --- core"]}, id="a-tag-holding-three-hyphens"),
])
async def test_a_frontmatter_value_holding_three_hyphens_is_read_whole_and_stays_private(
    tmp_path: Path, author: str, values: dict[str, Any],
) -> None:
    """Finding 1 and BF-940 (#1686), through ``write_entry``, ``read_entry``, ``search`` and update-in-place. The
    base ended the frontmatter at the first ``---`` anywhere. The author's case kept only ``author``, and neither
    topic case parsed, so each read as ``ship`` and another reader was shown the private record; the tag's case
    kept its classification, and its body began with the rest of the tag. The multi-line case checks that
    ``yaml.dump`` starts no line of a value with ``---``."""
    store = await _store(tmp_path)
    path = "notebooks/Ezri/inspection.md"
    write: dict[str, Any] = {
        "author": author, "path": path, "content": "PRIVATE_BODY_PROOF the coolant", "message": "probe",
        "classification": "private", **values,
    }
    await store.write_entry(**write)
    own = await store.read_entry(path, reader_id=author)
    assert own is not None and own["frontmatter"]["classification"] == "private"
    assert {key: own["frontmatter"][key] for key in values} == values
    assert own["content"] == "PRIVATE_BODY_PROOF the coolant"
    assert await store.read_entry(path, reader_id="alice") is None
    assert await _paths(store, "coolant", reader_id="alice") == []
    assert await _paths(store, "coolant", reader_id=author) == [path]
    await store.write_entry(**write)  # update-in-place carries ``created`` forward and counts the revision
    again = await store.read_entry(path, reader_id=author)
    assert again is not None and again["frontmatter"]["revision"] == 2
    assert again["frontmatter"]["created"] == own["frontmatter"]["created"]


@pytest.mark.asyncio
async def test_a_record_whose_frontmatter_does_not_parse_is_shown_to_the_captain_alone(tmp_path: Path) -> None:
    """RK10 (finding 1's injected reach): such a record names no classification. The base read it as ``{}``, so as
    ``ship``, and every reader was shown it. Now ``read_entry`` and ``search`` show it to the Captain alone; its
    author is unknown, so the author is not shown it either."""
    store = await _store(tmp_path)
    _write(store, "reports/open.md", "warp core report")
    (store.repo_path / "notebooks" / "Bravo").mkdir(parents=True, exist_ok=True)
    (store.repo_path / "notebooks" / "Bravo" / "secret.md").write_text(
        "---\nauthor: Bravo\nclassification: private\ntitle: [unclosed\n---\n\nwarp core secret\n", encoding="utf-8",
    )
    assert await store.read_entry("notebooks/Bravo/secret.md", reader_id="alice") is None
    assert await store.read_entry("notebooks/Bravo/secret.md", reader_id="Bravo") is None
    captain = await store.read_entry("notebooks/Bravo/secret.md", reader_id="captain")
    assert captain is not None and captain["frontmatter"] == {} and captain["content"] == "warp core secret"
    assert await _paths(store, "warp", reader_id="alice") == ["reports/open.md"]
    assert set(await _paths(store, "warp", reader_id="captain")) == {"reports/open.md", "notebooks/Bravo/secret.md"}


@pytest.mark.asyncio
@pytest.mark.parametrize("updated", [
    pytest.param("2026-13-05", id="month-13"),
    pytest.param("2026-02-30", id="february-30"),
    pytest.param("2026-01-01 25:00:00", id="hour-25"),
])
async def test_a_record_whose_frontmatter_cannot_be_constructed_is_withheld_not_raised(
    tmp_path: Path, updated: str,
) -> None:
    """Finding 5: YAML reads each of these as a timestamp and its constructor raises ``ValueError``, which is not a
    ``YAMLError``. On the base a search that matched such a record raised; before A1 every search raised."""
    store = await _store(tmp_path)
    _write(store, "reports/good.md", "warp core report")
    (store.repo_path / "reports" / "bad.md").write_text(
        f"---\nauthor: captain\nclassification: ship\nupdated: {updated}\n---\n\nwarp core report\n", encoding="utf-8",
    )
    for reader in ("captain", "alice"):
        assert await _paths(store, "warp", reader_id=reader) == ["reports/good.md"]


@pytest.mark.asyncio
async def test_the_records_search_route_confines_a_search_to_a_directory(tmp_path: Path) -> None:
    """RK11 (finding 3): the HXI's notebook search filters the route's results to ``notebooks/`` after the cap of
    20, so twenty better matches elsewhere cut the note. ``directory=notebooks`` confines the walk instead, and a
    directory outside the repository is HTTP 400. On the base the route took no ``directory``."""
    store = await _store(tmp_path)
    for index in range(20):
        _write(store, f"reports/reactor-{index}.md", "reactor reactor coolant", tags=["reactor"])
    _write(store, "notebooks/Ezri/reactor-note.md", "reactor note")
    runtime = SimpleNamespace(_records_store=store)
    everywhere = await search_records(q="reactor", scope="ship", runtime=runtime)
    assert "notebooks/Ezri/reactor-note.md" not in [hit["path"] for hit in everywhere["results"]]  # premise: cut
    confined = await search_records(q="reactor", scope="ship", directory="notebooks", runtime=runtime)
    assert [hit["path"] for hit in confined["results"]] == ["notebooks/Ezri/reactor-note.md"]
    outside = await search_records(q="reactor", scope="ship", directory="../outside", runtime=runtime)
    assert isinstance(outside, JSONResponse) and outside.status_code == 400
```

**A1-17** `ui/src/__tests__/NotebooksPanel.test.tsx` (base text)

SEARCH:
```tsx
  it('search runs against /api/records/search and filters to notebooks/* paths', async () => {
    useStore.setState({ notebooksOpen: true, notebooksSearchQuery: 'reactor' });
    vi.spyOn(global, 'fetch').mockResolvedValue(jsonResp({
      results: [
        { path: 'notebooks/atlas/reactor-a.md', frontmatter: { topic: 'Reactor A', author: 'atlas' }, score: 0.95, snippet: 'reactor coolant' },
        { path: 'notebooks/sage/reactor-b.md', frontmatter: { topic: 'Reactor B', author: 'sage' }, score: 0.81, snippet: 'reactor flux' },
        { path: 'captains-log/2026-05-01.md', frontmatter: { topic: 'Daily log' }, score: 0.6, snippet: 'reactor offline' },
      ],
    }));
    render(<NotebooksPanel />);
    await act(async () => {
      await useStore.getState().runNotebookSearch();
    });
    const entriesCol = screen.getByTestId('notebooks-entries');
    expect(entriesCol.textContent).toContain('2 results');
    expect(screen.getByTestId('notebooks-search-result-notebooks/atlas/reactor-a.md')).toBeTruthy();
    expect(screen.getByTestId('notebooks-search-result-notebooks/sage/reactor-b.md')).toBeTruthy();
    expect(screen.queryByTestId('notebooks-search-result-captains-log/2026-05-01.md')).toBeNull();
  });
```
REPLACE:
```tsx
  it('search asks /api/records/search for notebooks/ only and filters to notebooks/* paths', async () => {
    useStore.setState({ notebooksOpen: true, notebooksSearchQuery: 'reactor' });
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(jsonResp({
      results: [
        { path: 'notebooks/atlas/reactor-a.md', frontmatter: { topic: 'Reactor A', author: 'atlas' }, score: 0.95, snippet: 'reactor coolant' },
        { path: 'notebooks/sage/reactor-b.md', frontmatter: { topic: 'Reactor B', author: 'sage' }, score: 0.81, snippet: 'reactor flux' },
        { path: 'captains-log/2026-05-01.md', frontmatter: { topic: 'Daily log' }, score: 0.6, snippet: 'reactor offline' },
      ],
    }));
    render(<NotebooksPanel />);
    await act(async () => {
      await useStore.getState().runNotebookSearch();
    });
    // BF-952 A1: the server confines the walk before its cap of 20; the client filter stays as a guard.
    expect(fetchSpy).toHaveBeenCalledWith('/api/records/search?q=reactor&scope=ship&directory=notebooks');
    const entriesCol = screen.getByTestId('notebooks-entries');
    expect(entriesCol.textContent).toContain('2 results');
    expect(screen.getByTestId('notebooks-search-result-notebooks/atlas/reactor-a.md')).toBeTruthy();
    expect(screen.getByTestId('notebooks-search-result-notebooks/sage/reactor-b.md')).toBeTruthy();
    expect(screen.queryByTestId('notebooks-search-result-captains-log/2026-05-01.md')).toBeNull();
  });
```

**A1-18** `tests/test_ad1341_s4_lessons.py` (base text: the docstring was a claim about the parser; the assertions are unchanged)

SEARCH:
```python
    """A4 (R2-F3): Ship's Records cuts a document's frontmatter at the first two ``---`` it finds, wherever they stand
    (register R25), so a callsign such as ``normal---value`` came back as ``normal``: the stand-down reported the
```
REPLACE:
```python
    """A4 (R2-F3): Ship's Records cut a document's frontmatter at the first two ``---`` it found, wherever they stood
    (register R25; BF-952 A1 now ends it only at a ``---`` that begins a line), so a callsign such as
    ``normal---value`` came back as ``normal``: the stand-down reported the
```

### A1.5 Pairs: A1-M2 (trackers; M3 text)

**A1-19** `PROGRESS.md`

SEARCH:
```
A record whose frontmatter is not a mapping is skipped instead of raising.
```
REPLACE:
```
A record whose frontmatter is a non-empty list or a truthy scalar is skipped instead of raising. Amendment A1 (review round 1): every Ship's Records reader now frames a document the same way, ending the frontmatter only at a `---` that begins a line, so a value holding `---` is no longer cut (BF-940, #1686: on the base such a cut could drop a record's `classification` and show a private record to every reader). Every reader loads frontmatter with libyaml when it is installed and with PyYAML when libyaml refuses it. A frontmatter that does not parse is shown by `read_entry` and search to the Captain alone. Search withholds a record whose timestamp YAML cannot build instead of failing, and scores a number in a scored field. `GET /api/records/search` takes `directory`, which the HXI's notebook search sets to `notebooks`.
```

**A1-20** `DECISIONS.md`

SEARCH:
```
- *Scope.* `knowledge/records_store.py` (`RecordsStore.search`; module functions `_search_query_terms`, `_search_field_text`, `_search_document`, `_search_record_counts`, `_search_records`; the `_SEARCH_*` constants), `tests/test_layer_boundaries.py` (one allowlist entry), `tests/test_bf949_notebook_reader_identity.py` (one order assertion), tests. Contract `prompts/bf-952-records-keyword-search.md`.
```
REPLACE:
```
- *Scope.* `knowledge/records_store.py` (`RecordsStore.search`, `RecordsStore.read_entry`, `RecordsStore._parse_document`; module functions `_search_query_terms`, `_search_field_text`, `_read_document`, `_search_record_counts`, `_search_records`; `_RECORDS_YAML_LOADER` and the `_SEARCH_*` constants), `routers/records.py` (`search_records` takes `directory`), `ui/src/store/useStore.ts` (the notebook search asks for `notebooks`), a comment in `knowledge/lessons.py`, `tests/test_layer_boundaries.py` (one allowlist entry), `tests/test_bf949_notebook_reader_identity.py` (one order assertion), tests. Contract `prompts/bf-952-records-keyword-search.md`, with Amendment A1 (review round 1).
```

**A1-21** `DECISIONS.md`

SEARCH:
```
- *RK5.* A record whose frontmatter is not a mapping is withheld; it raised on the base.
- *RK7 (cost).* A worker thread (`asyncio.to_thread`), libyaml for the search parse, and term counting only in records that hold a query term as a substring of their parsed text. Bound: no slower than the base's match-all search, and the event loop is not blocked for more than 100 ms. Rejected for this BF: an in-memory cache (shared state across threads, invalidation, memory); an index is its own item.
- *RK8.* The search parse equals `_parse_document` for every input (a test); `_parse_document` is unchanged.
- *Not changed.* `oracle_service.py`, `proactive.py`, `routers/records.py`, `dm_targeted_lookup.py`, the HXI, the other six stoplists.
- *Residual.* Recorded limits L1 to L16 of the contract.
```
REPLACE:
```
- *RK5.* A record whose frontmatter is a non-empty YAML list or a truthy scalar is withheld from search; it raised on the base. A falsy one reads as `{}`, as every reader has read it.
- *RK7 (cost).* A worker thread (`asyncio.to_thread`), libyaml for every reader's parse (A1), and term counting only in records that hold a query term as a substring of their parsed text. Bound: no slower than the base's match-all search, and the event loop is not blocked for more than 100 ms. Rejected for this BF: an in-memory cache (shared state across threads, invalidation, memory); an index is its own item.
- *RK8 (A1).* One parse, `_read_document`, for `_parse_document`, `read_entry` and search: libyaml when installed, `yaml.safe_load` when libyaml refuses, so every reader reads a frontmatter alike. Rejected: `safe_load` in search (about 0.8 s more per call by the first draft's profile, so B1 would fail); parsing with both loaders and preferring PyYAML (both costs).
- *RK9 (A1; BF-940, #1686).* A frontmatter ends at the first `---` that begins a line, not at the first `---` anywhere. On the base a store-written value holding `---` was cut, and a cut that lost `classification` or broke the YAML showed a private record to every reader. Rejected: BF-940 as its own slice first (the same change and a whole extra cycle); fail-closed alone (an `author` holding `---` still parsed, without its classification); the exact-line rule (it would unframe a `---body` closing line the base framed). The skill catalog's splits stay on #1686.
- *RK10 (A1).* A frontmatter that does not parse names no classification, so `read_entry` and search show it to the Captain alone. Search withholds a record whose frontmatter YAML's constructor cannot build (`updated: 2026-13-05`) instead of failing; `read_entry` still raises for it, as on the base. `_parse_document`'s other callers still read an unparseable frontmatter as `{}` (L19).
- *RK11 (A1).* `GET /api/records/search` takes `directory`, checked by the store; the HXI's notebook search asks for `notebooks`, so a note is not cut by the cap of 20 before the client's filter.
- *RK12 (A1).* AD-725's DM knowledge lookup (off by default) now meets its 500 ms abort instead of blocking the loop past it, so on a corpus whose search takes longer it degrades to no recall block (L17). The deadline is unchanged; an index or cache (#1754, N1) is the remedy.
- *Not changed.* `oracle_service.py`, `proactive.py`, `dm_targeted_lookup.py`, `semantic.py`, `record_is_readable`, the skill catalog's parser, the other six stoplists, config.
- *Residual.* Recorded limits L1 to L23 of the contract.
```

Then regenerate the ledger, run G3 and stage only what it writes.

### A1.6 Verified Against Codebase (2026-11-05, on `ac8f7676`)

```
git log --oneline -6 -> ac8f7676 M3, 965e543b M2, c6bb3434 M1, e87f025f contract, a745e447 base
git diff --stat a745e447 ac8f7676 -> 9 files (records_store.py +261 -45 in diff stat lines; the two M1 test edits; the new test file; trackers; ledger; prompt)
records_store.py:52-57 levels (ship 2); :85 _UNRESTRICTED_READER = "captain"; :135 frontmatter.get("classification", "ship")
records_store.py:209 _SEARCH_YAML_LOADER; :222-231 _search_field_text; :234-251 _search_document (split("---", 2) at :241); :313 worker parse
records_store.py:503-509 write_entry keys author, classification, status, created, updated (author first); :516 update-in-place parse; :551-552 dump + "---\n{fm_yaml}---\n\n"
records_store.py:724 notebook path; :739 topic=topic_slug; :1182 read_entry parse; :1185 `if reader_id != "captain":`
records_store.py:1234-1244 list_entries try/except; :1291 publish parse; :1299-1300 publish rewrite; :1351 _safe_path before :1354 terms; :1359 to_thread
records_store.py:1456-1466 _parse_document; :1468-1479 _safe_path (ValueError on traversal)
routers/records.py:146 topic = body.get("topic", "untitled"); :151-160 write_notebook(topic_slug=topic); :166-182 search route; :180-181 ValueError -> 400
ui/src/store/useStore.ts:2073 fetch; :2085-2086 client filter; ui/src/__tests__/NotebooksPanel.test.tsx:145-163; .github/workflows/ci.yml:122 ui-tests, :159 npm run test
dm_targeted_lookup.py:156-168 wait_for(timeout=timeout_ms/1000) -> None; :255-270 knowledge search; config_models/agentic.py:176-178; config/system.yaml:1668-1671 enabled: false, timeout_ms: 500
semantic.py:738 read_entry(path, reader_id=_UNRESTRICTED_READER); lessons.py:85-87; tests/test_ad1341_s4_lessons.py:646-650
skill_catalog.py:105, :179, :790 content.split("---", 2)
tests/test_bf949_notebook_reader_identity.py:28 imports search_records; :306, :314 call it by keyword; :358-365 caller census (reader_id kept by A1-08)
scripts/ad_ceiling.py -> CEILING AD-1358 (GitHub issue titles); no AD or BF is allocated by A1
gh issue view 1686 -> OPEN, BF-940, label bug; body: options (a) to (c), census 2026-10-26 (2,736 files, none affected); no access-control consequence stated
```

### A1.7 Contract text edits (against `prompts/bf-952-records-keyword-search.md`)

**C-01**
SEARCH:
```
**Status:** ready to build.
```
REPLACE:
```
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-05: Amendment A1, the repair of review round 1 (GPT-6.1 Sol, NOT READY). It adds one framing and load for every Ship's Records reader (BF-940, #1686), fail-closed reads of an unparseable frontmatter, the search's per-record parse boundary, numeric field values, the route's `directory` and the HXI request. T13 and T14 are rewritten and T15 to T19 added. Rows RKS-21 and RKS-22 are retired and RKS-23 to RKS-34 added. L9 and L16 are revised and L17 to L23 added.
**Status:** ready to build.
```

**C-02**
SEARCH:
```
with 14 functions and 42 cases (counted by reading).
```
REPLACE:
```
with 14 functions and 42 cases (counted by reading); after Amendment A1, 19 functions and 58 cases (counted by reading).
```

**C-03** (§2)
SEARCH:
```
- Return shape, cap, scope and reader rules are unchanged, and no caller changes.
```
REPLACE:
```
- Return shape, cap, scope and reader rules are unchanged.
- Amendment A1: every Ship's Records reader frames and loads a document with one function, `_read_document`. The frontmatter ends at the first `---` that begins a line (BF-940, #1686); libyaml loads it when installed, and PyYAML when libyaml refuses. A frontmatter that does not parse is shown by `read_entry` and search to the Captain alone. Search withholds a record whose frontmatter YAML cannot construct, and scores a number in a scored field as text. The records route forwards `directory`, which the HXI's notebook search sets to `notebooks`. No other caller changes.
```

**C-04** (§3 RK5)
SEARCH:
```
**RK5, non-mapping frontmatter.** A YAML list or scalar made `record_is_readable` raise on the base. It is now skipped with a debug log. It names no classification, so withholding it is the fail-closed choice.
```
REPLACE:
```
**RK5, non-mapping frontmatter.** A non-empty YAML list or a truthy scalar made `record_is_readable` raise on the base. It is now skipped with a debug log. It names no classification, so withholding it is the fail-closed choice. A falsy one (`[]`, `false`, `0`, `0.0`, `''`) reads as `{}`, as every reader has always read it, so it is shown at the default level (L9; A1, finding V3).
```

**C-05** (§3 RK7)
SEARCH:
```
2. **Chosen:** parse frontmatter inside `search` with `yaml.CSafeLoader` when `yaml.__with_libyaml__`, else `yaml.SafeLoader`, with a `safe_load` retry on a libyaml error (RK8).
```
REPLACE:
```
2. **Chosen:** parse frontmatter with `yaml.CSafeLoader` when `yaml.__with_libyaml__`, else `yaml.SafeLoader`, with a `safe_load` retry on a libyaml error. After A1 this is every reader's parse, not the search's alone (RK8).
```

**C-06** (§3 RK8 to RK12)
SEARCH:
```
**RK8, the search parse.**
- `_search_document(raw)` repeats `_parse_document`'s split and result. Only the loader differs.
- `_parse_document` is untouched: `read_entry` and the other readers keep PyYAML.
- T13 holds the two equal over the store's shape, a YAML date, an escaped value, a list, empty, malformed and absent frontmatter.
```
REPLACE:
```
**RK8, one parse (A1, finding 6).**
- `_read_document(raw)` is the only framing and load. `_parse_document`, `read_entry` and search call it, so no input parses differently between readers.
- libyaml when installed; `yaml.safe_load` on a `YAMLError`; `None` when both refuse. No record that parses today stops parsing (PyYAML is the fallback). A frontmatter only libyaml accepts (a tab after a key) now parses for every reader. No input is known that both loaders accept with different values.
- Rejected: `safe_load` in search (B1); parsing with both loaders.

**RK9, framing (A1, finding 1; BF-940, #1686).**
- The frontmatter ends at the first `---` that begins a line. This differs from the base only where the base cut a value mid-line.
- On the base, `author: Ezri---Prime` read as `{author: Ezri}`, and a quoted topic holding `--- x: y` did not parse. Each read as `ship`, so another reader was shown a private record.
- Rejected: BF-940 first as its own slice; fail-closed alone; the exact-line rule (L18). The skill catalog's splits stay on #1686 (L20).

**RK10, fail closed (A1).**
- A frontmatter that does not parse is the Captain's alone in `read_entry` and search. `_parse_document` still returns `{}` for it (L19).
- Search withholds, with a debug log naming the path, a record whose frontmatter YAML's constructor cannot build (finding 5). `read_entry` still raises for it (L22).

**RK11, the route (A1, finding 3).** `search_records` forwards `directory` (validated by `_safe_path`, HTTP 400 on traversal). The HXI's notebook search sends `directory=notebooks` and keeps its client filter as a guard.

**RK12, the DM lookup (A1, finding 4).** Unchanged; recorded as L17. The base met no deadline: it blocked the loop past it. Rejected: raising `timeout_ms` (every lookup type, no validated value); a knowledge-only bound; awaiting past the abort.
```

**C-07** (§4 table)
SEARCH:
```
| M3 | STANDARD | trackers | P3-1, P3-2 (2), ledger | G3 |
```
REPLACE:
```
| M3 | STANDARD | trackers | P3-1, P3-2 (2), ledger | G3 |
| A1-M1 | STANDARD, security-relevant (access control) | **yes**: every Ship's Records reader's parse, `read_entry`'s admission, the search route, the HXI request | A1-01 to A1-18 (18) | GA1, then B1 and B2, then the §10 campaign |
| A1-M2 | STANDARD | trackers | A1-19 to A1-21 (3), ledger | G3 |
```

**C-08** (§4 G2)
SEARCH:
```
Expected in the new file: **42 passed**. Others: 0 failed.
```
REPLACE:
```
Expected in the new file: **42 passed** (M2's head). Others: 0 failed.
- **GA1 (A1-M1's head):** see §A1.3. Expected in the new file: **58 passed** (counted by reading).
```

**C-09** (§6)
SEARCH:
```
| T13 | `test_search_reads_a_document_as_the_store_reads_it` | 7 | RK8 | n/a (new helper) |
| T14 | `test_a_search_runs_off_the_event_loop` | 1 | RK7 option 3 | yes |
```
REPLACE:
```
| T13 | `test_every_reader_frames_and_loads_a_document_alike` (A1; was `test_search_reads_a_document_as_the_store_reads_it`, 7 cases) | 11 | RK8, RK9; findings 1 and 6 | n/a (new helper) |
| T14 | `test_a_search_runs_off_the_event_loop` (A1: the walk, reads, parse and ranking) | 1 | RK7 option 3; V1 | yes (setup) |
| T15 | `test_a_numeric_frontmatter_value_is_scored_and_a_boolean_is_not` | 3 | finding 2 | 1 of 3 (the boolean) |
| T16 | `test_a_frontmatter_value_holding_three_hyphens_is_read_whole_and_stays_private` | 4 | RK9; finding 1; #1686 | yes |
| T17 | `test_a_record_whose_frontmatter_does_not_parse_is_shown_to_the_captain_alone` | 1 | RK10 | yes |
| T18 | `test_a_record_whose_frontmatter_cannot_be_constructed_is_withheld_not_raised` | 3 | RK10; finding 5 | yes |
| T19 | `test_the_records_search_route_confines_a_search_to_a_directory` | 1 | RK11; finding 3 | yes |
```

**C-10** (§9)
SEARCH:
```
Not changed: `oracle_service.py` (the `/10`, fusion, `query`, `query_formatted`), `proactive.py`, `routers/records.py`, `dm_targeted_lookup.py`, `ui/`, `semantic.py`, `record_is_readable`, `_parse_document`, the cap of 20, config, `EventType`, persisted shapes, the default executor. No method is added to `RecordsStore`; its SRP row (`architecture-baseline.yaml:751-757`) is keyed by trigger.
```
REPLACE:
```
Not changed: `oracle_service.py` (the `/10`, fusion, `query`, `query_formatted`), `proactive.py`, `dm_targeted_lookup.py`, `semantic.py`, `record_is_readable`, the skill catalog's parser (`skill_catalog.py:105`, `:179`, `:790`), the cap of 20, config, `EventType`, persisted shapes, the default executor. Changed by Amendment A1 beyond `search`: `_parse_document` (it delegates to `_read_document`), `read_entry` (an unparseable frontmatter is the Captain's alone), `routers/records.py` (`directory`), `ui/src/store/useStore.ts` (the notebook search's request) and a comment in `knowledge/lessons.py`; §A1.2 lists the effect on each caller. No method is added to `RecordsStore`; its SRP row (`architecture-baseline.yaml:751-757`) is keyed by trigger.
```

**C-11** (§10 bullets)
SEARCH:
```
- Every "Line" text occurs exactly once in `records_store.py` on M2's head.
- Equivalent mutants, not rowed (B1 and B2 cover the cost):
  - deleting `if not terms: return []`;
  - `written is None` → `False`;
  - the RKS-20 line → `if False:` (the check only saves work);
  - `_SEARCH_YAML_LOADER` → `yaml.SafeLoader`;
  - deleting the `safe_load` retry in `_search_document` (no known input separates the two loaders, L16).
```
REPLACE:
```
- Every "Line" text occurs exactly once in its file on M2's head; after A1, on A1-M1's head.
- **A1: the campaign of record moves to A1-M1's head.** `records_store.py` changed, so rerun every active row: RKS-1 to RKS-20 and RKS-23 to RKS-34 (32 rows). RKS-21 and RKS-22 are retired. Also record the sha256 of `routers/records.py`.
- Equivalent mutants, not rowed (B1 and B2 cover the cost):
  - deleting `if not terms: return []`;
  - `written is None` → `False`;
  - the RKS-20 line → `if False:` (the check only saves work);
  - in `_read_document`, `frontmatter = yaml.safe_load(block)` → `return None, body` (no input is known that libyaml refuses and PyYAML accepts, L16);
  - RKS-27 where libyaml is not installed (report `yaml.__with_libyaml__`).
```

**C-12** (§10 rows)
SEARCH:
```
| RKS-21 | records_store.py | `            return frontmatter, parts[2].strip()` | `            return frontmatter, parts[2]` | the search parse departs from the store's | `test_search_reads_a_document_as_the_store_reads_it` |
| RKS-22 | records_store.py | `                frontmatter = yaml.load(parts[1], Loader=_SEARCH_YAML_LOADER) or {}` | `                frontmatter = yaml.load(parts[1], Loader=_SEARCH_YAML_LOADER)` | empty frontmatter reads as `None` and the record is withheld | `test_search_reads_a_document_as_the_store_reads_it` |
```
REPLACE:
```
| RKS-21 | (retired by A1: the line is gone; see RKS-24) | | | | |
| RKS-22 | (retired by A1: the line is gone; see RKS-26) | | | | |
| RKS-23 | records_store.py | `        close = raw.find("\n---", 3)` | `        close = raw.find("---", 3) - 1` | the base's framing: a value holding `---` is cut, and a private record reads as `ship` | `test_a_frontmatter_value_holding_three_hyphens_is_read_whole_and_stays_private` |
| RKS-24 | records_store.py | `            body = raw[close + 4:].strip()` | `            body = raw[close + 4:]` | the body keeps the blank line after the frontmatter | `test_every_reader_frames_and_loads_a_document_alike` |
| RKS-25 | records_store.py | `                    return None, body` | `                    return {}, body` | a frontmatter that does not parse reads as `ship` for every reader (the base) | `test_a_record_whose_frontmatter_does_not_parse_is_shown_to_the_captain_alone` |
| RKS-26 | records_store.py | `            return frontmatter or {}, body` | `            return frontmatter, body` | an empty frontmatter reads as unparseable | `test_every_reader_frames_and_loads_a_document_alike` |
| RKS-27 | records_store.py | `_RECORDS_YAML_LOADER: Any = yaml.CSafeLoader if getattr(yaml, "__with_libyaml__", False) else yaml.SafeLoader` | `_RECORDS_YAML_LOADER: Any = yaml.SafeLoader` | a frontmatter only libyaml accepts reads as unparseable again (killed only with libyaml installed) | `test_every_reader_frames_and_loads_a_document_alike` |
| RKS-28 | records_store.py | `    if isinstance(value, (int, float)) and type(value) is not bool:` | `    if False:` | a numeric topic is unsearchable | `test_a_numeric_frontmatter_value_is_scored_and_a_boolean_is_not` |
| RKS-29 | records_store.py | the RKS-28 line | `    if isinstance(value, (int, float)):` | a boolean is scored as `True` | `test_a_numeric_frontmatter_value_is_scored_and_a_boolean_is_not` |
| RKS-30 | records_store.py | `            logger.debug("BF-952: skipping %s, whose frontmatter cannot be constructed", rel_path, exc_info=True)` | `            raise` | one record YAML cannot construct ends every search | `test_a_record_whose_frontmatter_cannot_be_constructed_is_withheld_not_raised` |
| RKS-31 | records_store.py | `            if reader_id != _UNRESTRICTED_READER:` | `            if False:` | search shows an unparseable record to every reader | `test_a_record_whose_frontmatter_does_not_parse_is_shown_to_the_captain_alone` |
| RKS-32 | records_store.py | `            if reader_id != "captain":` (12 spaces; the 8-space line at `:1185` is a different line) | `            if False:` | `read_entry` shows an unparseable record to every reader | `test_a_record_whose_frontmatter_does_not_parse_is_shown_to_the_captain_alone` |
| RKS-33 | records_store.py | `        terms = _search_query_terms(query)` | `        terms = _search_query_terms(query); [path.read_text(encoding="utf-8") for path in search_path.rglob("*.md")]` | a synchronous walk and read run on the event loop | `test_a_search_runs_off_the_event_loop` |
| RKS-34 | routers/records.py | `        results = await runtime._records_store.search(q, scope=scope, reader_id="captain", directory=directory)` | `        results = await runtime._records_store.search(q, scope=scope, reader_id="captain")` | the route ignores `directory`, and the cap cuts the HXI's note again | `test_the_records_search_route_confines_a_search_to_a_directory` |
```

**C-13** (§11 L9)
SEARCH:
```
- **L9.** A file with non-mapping frontmatter is invisible to search. On the base it made every matching search raise.
```
REPLACE:
```
- **L9.** A file whose frontmatter is a non-empty YAML list or a truthy scalar is invisible to search. On the base it made every matching search raise. A falsy one (`[]`, `false`, `0`, `0.0`, `''`) reads as `{}` for every reader, as on the base, so it is shown at the default level `ship`. Changing that is a policy for the L19 follow-up.
```

**C-14** (§11 L16 to L23)
SEARCH:
```
- **L16.** The `safe_load` retry for a frontmatter that only PyYAML accepts is not pinned by a test. No such input is known.
```
REPLACE:
```
- **L16.** The `safe_load` fallback for a frontmatter that libyaml refuses and PyYAML accepts is not pinned by a test. No such input is known; the reverse (a tab after a key) is T13's case.
- **L17 (A1, finding 4).** AD-725's DM knowledge lookup (`dm_targeted_lookup.py:159-161`; `timeout_ms` 500, `config_models/agentic.py:178`; `enabled: false` in `config/system.yaml:1669`) now aborts at its deadline while the search's worker runs on. The reviewer measured `None` at 511 ms, with the worker finishing at 1,126 ms on 302 records. The base returned its result at 1,342 ms only because it blocked the loop past the deadline. With the lookup enabled, a knowledge lookup on such a corpus degrades to no recall block, AD-725's own degrade. The deadline is unchanged. The remedy is N1 (an index, or a parsed-record cache keyed by path, `mtime_ns` and size), recommended as #1754's next item.
- **L18 (A1).** A document whose frontmatter has no closing line beginning `---` has no frontmatter (`{}`, so the default level), where the base closed it at a `---` inside a line. The store never writes one: `write_entry` (`:551-552`) and `publish` (`:1299-1300`) close with `---` on its own line. Hand edits only.
- **L19 (A1).** `_parse_document`'s other callers still read a frontmatter that does not parse as `{}`, as on the base. `list_entries` lists it, the similarity and convergence scans read it, `write_entry`'s update-in-place loses `created` and restarts `revision`, and a Captain's `publish` rewrites it with only `status` and `updated`. The semantic indexer reads through `read_entry` as the Captain (`semantic.py:738`), so it indexes such a record with `{}`. After A1's framing this is reachable by hand edits only. It is a follow-up BF.
- **L20 (A1).** The skill catalog's own three splits (`cognitive/skill_catalog.py:105`, `:179`, `:790`) keep the base framing. #1686 stays open for them.
- **L21 (A1).** A record the semantic backfill indexed before A1 keeps the metadata of the base parse until it is indexed again. The 2026-10-26 census found no live record the base framing cuts; §16 step 2 counts them again on the clone.
- **L22 (A1).** An error of YAML's constructor (`updated: 2026-13-05`) still raises from `_parse_document` and `read_entry`, as on the base, and `list_entries` skips such a record through its `except Exception`. Only search withholds it.
- **L23 (A1).** The route's `directory` is any directory inside the records repository (`_safe_path`). The route reads as the Captain, so a confined search shows nothing a whole-repository search could not.
```

**C-15** (Absence Verified, A1)
SEARCH:
```
## 13. Deterministic gate checks and prior art
```
REPLACE:
````
## Absence Verified, Amendment A1 (2026-11-05, on `ac8f7676`)

```
A8  CLAIM: records_store.py holds the only frontmatter loads in knowledge/
    RUN:   Grep 'yaml\.(safe_load|load)\(' src/probos/knowledge
    FOUND: records_store.py:244, :247, :1462 (3 lines)   HOLDS: yes, so A1-03 and A1-07 replace every one
A9  CLAIM: the "---" split occurs in records_store.py twice and in the skill catalog three times, nowhere else in src
    RUN:   Grep 'split\("---"' src/probos
    FOUND: records_store.py:241, :1459; skill_catalog.py:105, :179, :790 (5 lines)   HOLDS: yes
A10 CLAIM: nothing outside the BF-952 files names _search_document or _SEARCH_YAML_LOADER
    RUN:   Grep '_SEARCH_YAML_LOADER|_search_document|CSafeLoader|yaml\.load\(' (repository, excluding logs/)
    FOUND: DECISIONS.md:1351; records_store.py:209, :234, :244, :313; tests/test_bf952…:267, :277, :283;
           prompts/bf-952…:89, :101, :249, :274, :284, :353, :851, :861, :867, :907, :946, :947, :972, :1010, :1051, :1067
           (24 lines: 1 + 4 + 3 + 16)   HOLDS: yes; A1 rewrites each production and test line, and the prompt lines are history
A11 CLAIM: RKS-31's line is new, and RKS-32's 12-space line is new
    RUN:   Grep 'reader_id != _UNRESTRICTED_READER|if reader_id != "captain":' (repository, excluding logs/)
    FOUND: records_store.py:1185 only (8 spaces)   HOLDS: yes
A12 CLAIM: no test reads a cut value back from _parse_document
    RUN:   Grep '_parse_document' tests
    FOUND: test_ad550_notebook_dedup.py:108, :119, :131, :140, :151, :160, :172; test_bf952…:265, :267; test_records_store.py:402, :412 (11 lines)
    HOLDS: yes, by reading their inputs (no "---" inside a value); GA1 runs both files
A13 CLAIM: row ids RKS-23 and up are free
    RUN:   Grep 'RKS-(2[3-9]|[3-9]\d)' (repository, excluding logs/)   FOUND: none   HOLDS: yes
A14 CLAIM: the HXI's notebook search is the only UI caller of /api/records/search
    RUN:   Grep 'runNotebookSearch|records/search' ui/src
    FOUND: useStore.ts:806, :2065, :2073; NotebooksPanel.tsx:9, :37; NotebooksPanel.test.tsx:145, :156 (7 lines)   HOLDS: yes
A15 CLAIM: the Oracle service sets no deadline on its records tier (this file only)
    RUN:   Grep 'wait_for|timeout' src/probos/cognitive/oracle_service.py   FOUND: none   HOLDS: yes, for that file
A16 CLAIM: no AD or BF number is allocated by A1
    RUN:   scripts/ad_ceiling.py -> CEILING AD-1358   HOLDS: yes (the L19 follow-up BF is allocated by the orchestrator)
```

## 13. Deterministic gate checks and prior art
````

**C-16** (§14 property 6)
SEARCH:
```
6. Nothing raises on hand-edited frontmatter: a list or scalar frontmatter; a list or numeric `topic` or `tags`; a `date`, `datetime`, unparsable or missing `updated`.
```
REPLACE:
```
6. Nothing raises out of search on hand-edited frontmatter: a list or scalar frontmatter; a list or numeric `topic` or `tags`; a `date`, `datetime`, unparsable or missing `updated`; a timestamp YAML's constructor refuses (`2026-13-05`, T18). An `Exception` from the parse is contained per record; a `BaseException` is not.
```

**C-17** (§14 properties 8 to 10)
SEARCH:
```
8. `_search_records` reads files only: no `self`, no shared mutable state, no write. `search` awaits it through `asyncio.to_thread` (T14).
9. `_search_document` equals `_parse_document` for every T13 input, and `_parse_document` is byte-identical to the base.
10. No caller file changes; `oracle_service.py:1074` and AD-1141's floor are unchanged.
```
REPLACE:
```
8. `_search_records` reads files only: no `self`, no store state, no write. It shares only read-only references (the terms list and module constants). `search` awaits it through `asyncio.to_thread` (T14).
9. (A1) `_read_document` is the one framing and load; `_parse_document`, `read_entry` and search call it. A frontmatter ends at the first `---` that begins a line (T13, T16). libyaml runs first, `yaml.safe_load` on a `YAMLError`, and the result is `None` when both refuse.
10. No caller file changes except `routers/records.py` (`directory`) and the HXI's request; `oracle_service.py:1074` and AD-1141's floor are unchanged.
```

**C-18** (§14 properties 14 to 17)
SEARCH:
```
13. Every new docstring, comment and test docstring is true of the head, and each "on the base" claim matches §6.
```
REPLACE:
```
13. Every new docstring, comment and test docstring is true of the head, and each "on the base" claim matches §6.
14. (A1) A frontmatter that does not parse is shown to the Captain alone by `read_entry` and by search (T17). `_parse_document`'s other callers read it as `{}`, as on the base (L19).
15. (A1) A scalar int or float in a scored field is scored as text; a boolean is not (T15).
16. (A1) `GET /api/records/search` forwards `directory` (validated by `RecordsStore.search`; HTTP 400 on traversal). The HXI's notebook search sends `directory=notebooks` and keeps its client filter (T19; `NotebooksPanel.test.tsx`).
17. (A1) T14 records the thread of `rglob`, `read_text`, `_read_document`, `_search_record_counts` and `record_write_time`, and none runs on the loop; RKS-33 fails it.
```

**C-19** (§15)
SEARCH:
```
7. Every §10 mutant is killed; G1 to G3 and the §13 checks pass; the broad gate's receipt is green.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
```
REPLACE:
```
7. Every §10 mutant is killed; G1 to G3, GA1 and the §13 checks pass; the broad gate's receipt is green.
8. (A1) A store-written value holding `---` reads back whole and a private record stays private (T16). A frontmatter that does not parse is the Captain's alone (T17).
9. (A1) A numeric topic is searchable (T15). A timestamp YAML cannot build withholds only its record (T18). The route confines a search to a directory, and the HXI asks for notebooks (T19, vitest).
10. (A1) §16 step 2 reports the census counts.
11. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
```

**C-20** (§16 step 1)
SEARCH:
```
1. **B1 and B2** on the synthetic corpus, on M2's head, before the Diff Reviewer (§4).
```
REPLACE:
```
1. **B1 and B2** on the synthetic corpus, on M2's head, before the Diff Reviewer (§4); after Amendment A1, again on A1-M1's head, before review round 2 (the parse changed).
```

**C-21** (§16 step 2: census)
SEARCH:
```
   - Record the result on #1751. If a game record misses the top 3 for either named query, or B2 fails on the live copy, return to the Architect before closing.
```
REPLACE:
```
   - Record the result on #1751. If a game record misses the top 3 for either named query, or B2 fails on the live copy, return to the Architect before closing.
   - **Census (A1; BF-940, #1686), on the same clone, adding no access.** For every `*.md` outside `_archived/`, compare the base parse (`_parse_document` of `a745e447`'s `records_store.py`, imported from a base checkout) with the head's `_read_document`. Report counts only: files; equal; differing; differing in `classification`; head `None` (does not parse); head constructor error. If any record's `classification` differs, or any record does not parse, report it to the Captain before closing: a private record may have been readable on the vessel, and its semantic index entry needs re-indexing (L21).
```

**C-22** (For the Captain)
SEARCH:
```
None. The change is reversible, keeps every caller's contract, strengthens privacy (RK3), and makes the loop more responsive than the base. The live-copy read in §16 is the step #1751's own acceptance names, done read-only on a clone.
```
REPLACE:
```
None to decide. The change is reversible, keeps every caller's contract, strengthens privacy (RK3, and A1's RK9 and RK10), and makes the loop more responsive than the base. The live-copy read in §16 is the step #1751's own acceptance names, done read-only on a clone; A1 adds the BF-940 census counts to it. For the Captain's information: #1686 is a P1, security-class defect (a private record readable by every reader), on the base since the store's first parser, with ordinary reach through the notebook write API. A1 closes it for Ship's Records; #1686 stays open for the skill catalog.
```

**C-23** (§8 P3-1: same text as A1-19)
SEARCH:
```
A record whose frontmatter is not a mapping is skipped instead of raising.
```
REPLACE:
```
A record whose frontmatter is a non-empty list or a truthy scalar is skipped instead of raising. Amendment A1 (review round 1): every Ship's Records reader now frames a document the same way, ending the frontmatter only at a `---` that begins a line, so a value holding `---` is no longer cut (BF-940, #1686: on the base such a cut could drop a record's `classification` and show a private record to every reader). Every reader loads frontmatter with libyaml when it is installed and with PyYAML when libyaml refuses it. A frontmatter that does not parse is shown by `read_entry` and search to the Captain alone. Search withholds a record whose timestamp YAML cannot build instead of failing, and scores a number in a scored field. `GET /api/records/search` takes `directory`, which the HXI's notebook search sets to `notebooks`.
```

**C-24** (§8 P3-2 Scope: same text as A1-20)
SEARCH:
```
- *Scope.* `knowledge/records_store.py` (`RecordsStore.search`; module functions `_search_query_terms`, `_search_field_text`, `_search_document`, `_search_record_counts`, `_search_records`; the `_SEARCH_*` constants), `tests/test_layer_boundaries.py` (one allowlist entry), `tests/test_bf949_notebook_reader_identity.py` (one order assertion), tests. Contract `prompts/bf-952-records-keyword-search.md`.
```
REPLACE:
```
- *Scope.* `knowledge/records_store.py` (`RecordsStore.search`, `RecordsStore.read_entry`, `RecordsStore._parse_document`; module functions `_search_query_terms`, `_search_field_text`, `_read_document`, `_search_record_counts`, `_search_records`; `_RECORDS_YAML_LOADER` and the `_SEARCH_*` constants), `routers/records.py` (`search_records` takes `directory`), `ui/src/store/useStore.ts` (the notebook search asks for `notebooks`), a comment in `knowledge/lessons.py`, `tests/test_layer_boundaries.py` (one allowlist entry), `tests/test_bf949_notebook_reader_identity.py` (one order assertion), tests. Contract `prompts/bf-952-records-keyword-search.md`, with Amendment A1 (review round 1).
```

**C-25** (§8 P3-2 RK5 to Residual: same text as A1-21)
SEARCH:
```
- *RK5.* A record whose frontmatter is not a mapping is withheld; it raised on the base.
- *RK7 (cost).* A worker thread (`asyncio.to_thread`), libyaml for the search parse, and term counting only in records that hold a query term as a substring of their parsed text. Bound: no slower than the base's match-all search, and the event loop is not blocked for more than 100 ms. Rejected for this BF: an in-memory cache (shared state across threads, invalidation, memory); an index is its own item.
- *RK8.* The search parse equals `_parse_document` for every input (a test); `_parse_document` is unchanged.
- *Not changed.* `oracle_service.py`, `proactive.py`, `routers/records.py`, `dm_targeted_lookup.py`, the HXI, the other six stoplists.
- *Residual.* Recorded limits L1 to L16 of the contract.
```
REPLACE:
```
- *RK5.* A record whose frontmatter is a non-empty YAML list or a truthy scalar is withheld from search; it raised on the base. A falsy one reads as `{}`, as every reader has read it.
- *RK7 (cost).* A worker thread (`asyncio.to_thread`), libyaml for every reader's parse (A1), and term counting only in records that hold a query term as a substring of their parsed text. Bound: no slower than the base's match-all search, and the event loop is not blocked for more than 100 ms. Rejected for this BF: an in-memory cache (shared state across threads, invalidation, memory); an index is its own item.
- *RK8 (A1).* One parse, `_read_document`, for `_parse_document`, `read_entry` and search: libyaml when installed, `yaml.safe_load` when libyaml refuses, so every reader reads a frontmatter alike. Rejected: `safe_load` in search (about 0.8 s more per call by the first draft's profile, so B1 would fail); parsing with both loaders and preferring PyYAML (both costs).
- *RK9 (A1; BF-940, #1686).* A frontmatter ends at the first `---` that begins a line, not at the first `---` anywhere. On the base a store-written value holding `---` was cut, and a cut that lost `classification` or broke the YAML showed a private record to every reader. Rejected: BF-940 as its own slice first (the same change and a whole extra cycle); fail-closed alone (an `author` holding `---` still parsed, without its classification); the exact-line rule (it would unframe a `---body` closing line the base framed). The skill catalog's splits stay on #1686.
- *RK10 (A1).* A frontmatter that does not parse names no classification, so `read_entry` and search show it to the Captain alone. Search withholds a record whose frontmatter YAML's constructor cannot build (`updated: 2026-13-05`) instead of failing; `read_entry` still raises for it, as on the base. `_parse_document`'s other callers still read an unparseable frontmatter as `{}` (L19).
- *RK11 (A1).* `GET /api/records/search` takes `directory`, checked by the store; the HXI's notebook search asks for `notebooks`, so a note is not cut by the cap of 20 before the client's filter.
- *RK12 (A1).* AD-725's DM knowledge lookup (off by default) now meets its 500 ms abort instead of blocking the loop past it, so on a corpus whose search takes longer it degrades to no recall block (L17). The deadline is unchanged; an index or cache (#1754, N1) is the remedy.
- *Not changed.* `oracle_service.py`, `proactive.py`, `dm_targeted_lookup.py`, `semantic.py`, `record_is_readable`, the skill catalog's parser, the other six stoplists, config.
- *Residual.* Recorded limits L1 to L23 of the contract.
```

### A1.8 Prior art and blind spots

- **Absorbed and adapted:** python-frontmatter's delimiter rule (#1686 option (a)). We close at any line beginning `---` rather than an exact line, so A1 differs from the base only where the base cut a value (L18).
- **YAML's own rule:** a column-0 `---` followed by whitespace ends a document. That is why a valid frontmatter cannot hold one at the start of a line.
- **No web search was spent.** This is ProbOS plumbing, the prior art is already cited on #1686, and no `reference-projects.md` row was examined.
- **Blind spots found:**
  - The semantic index keeps the base parse's metadata until a record is re-indexed (L21).
  - A Captain's `publish` of an unparseable record rewrites its frontmatter (L19).
  - A record's own author loses it when its frontmatter does not parse (T17).
  - A docstring in another contract described the defect (A1-18) and needed correcting.

## Amendment A2 (2026-11-05): review round 2 (GPT-6.1 Sol, NOT READY)

### A2.1 Findings and decisions

| # | Verdict (lines read) | Decision |
|---|---|---|
| 1 (P1, A1 regression) | **Confirmed.** `records_store.py:262-275` returns `{}, raw` when no line begins `---`. The guards at `:345` and `:1222` test only for `None`. The base (`a745e447:1265-1275`) used `raw.split("---", 2)`, which honoured row 1. | **Option (b+), "base framing unless the line framing provably agrees".** The base framing is the default reading. A1's line framing replaces it only when a `---` inside a line comes before the first line that begins `---`, **and** the line-framed block loads as a mapping, **and**, if the base framing names a `classification`, the line framing names the same one (`_line_framing_is_kept`). A document with no later `---` at all reads `{}`, as on the base (L18). |
| 2 (P2, ordinary, base) | **Confirmed.** `:568` keeps the stored class, but `:614` passes the call's own argument. The only caller that sets `preserve_classification_on_update` is `write_notebook:775`, and its default is `private` (`:770-775`). So the index always holds `private` on a preserved rewrite: stricter than the disk, never looser. | **Fold, as RK14.** `:614` and the log at `:628` use `frontmatter["classification"]`. T21 tests it through real Chroma and `build_records_scope_filter`. |
| 3 (P2, base) | **Confirmed.** `semantic.py:738` reads as `_UNRESTRICTED_READER`. `records_store.py:1226-1228` turns `None` into `{}` for the Captain, and `semantic.py:746` then defaults the level to `ship`. Not a regression: the base read `{}` for every reader. | **Record, not fix.** L19 is revised to name `semantic.py:738-752`. BF-956's scope is in L19 (A2-15). |
| 4 (P2, base, injected) | **Confirmed by reading.** `:590` uses `yaml.dump` with the default Dumper, which tags a tuple `!!python/tuple`; the safe loaders refuse that tag, so `_load_frontmatter` returns `None`. The reviewer ran this; I did not. | **Correct the claims now.** Wrong today: the AD-1140 docstring at `:506-508` ("round-trip through `_parse_document`", unqualified), L19's "After A1's framing this is reachable by hand edits only", and L18's "Hand edits only". No test name or docstring makes the claim (grep: no hit for "round" or "hand" except `:345`). The codec repair is recorded in **BF-956** (new L24), not #1754: it is the same "frontmatter no reader loads" seam, and #1754 is about search cost. |
| 5 (test discrimination) | **Partly.** T14's "yes (setup)" is already disclosed in §6 and in its docstring. T13 is marked "n/a (new helper)". T15's boolean case is in the table as the one case that fails on the base, which it does; it passes on round 1 because round 1 dropped every non-string value. | **Accepted, no rename.** For a new function, discrimination is judged by mutants (RKS-23 to RKS-40), not by failing on the base. The black-box guards are T16 to T21. |
| 6 (round 3) | — | **Whole candidate.** A2 changes `_read_document`'s return for one shape, so it changes what every reader sees (§A1.2 already lists this as a shared contract). It also changes what the semantic index receives, which Oracle Tier 2 and BF-679 parity consume. This is round 3; a fourth round needs a new decision from me. |

Why not the other options for decision 1:
- **(a) Fail closed when no line begins `---`.** Row 1's owner would lose the record. Worse, `_parse_document` maps `None` to `{}`, so a Captain's `publish` (`:1337-1346`) or an update-in-place (`:555-568`) would rewrite the file **without its `private`**. The base honours `private` there.
- **(c) Fail closed only for an inline close.** Same problem.
- **Fail closed for row 2 (no marker at all).** Rejected here because it would also hide raw `.md` files written by `write_workspace_file` (`:1455`, `consultation/workspace.py:164,176`) that open with a horizontal rule. The privacy gain is injected-only (a truncated or hand-made file), so the change belongs to BF-956.

**What A2 does to each consumer.** Only documents with a `---` inside a frontmatter line are affected.
- **`list_entries`, `publish`, update-in-place, similarity and the semantic indexer** read row 1 and the hidden-regression shapes as the base did. A Captain's `publish` keeps `private`, update-in-place keeps `created`, `revision` and `classification`, and the backfill indexes the record at `private`.
- **T16 (all four cases), T13's A1 cases, T17, T18 and T14** are unchanged. I traced each against the new code; T16's tag case keeps the line framing because both framings name `private`.
- **RKS-23 to RKS-26** are re-anchored. **RKS-27 to RKS-34** are unchanged.

### A2.2 Pairs: A2-M1 (code and tests)

**A2-01** `src/probos/knowledge/records_store.py`
SEARCH:
```python
def _read_document(raw: str) -> tuple[Any, str]:
    """BF-952 A1: a Ship's Records document's frontmatter and body, the one parse every reader uses.

    ``RecordsStore._parse_document``, ``RecordsStore.read_entry`` and the search all call it.

    Framing (BF-940, #1686): a document that starts with ``---`` has frontmatter up to the
    first later ``---`` that begins a line, and its body is what follows that ``---``,
    stripped. The base ended the frontmatter at the first ``---`` anywhere, so a value
    holding one inside a line (``topic: Inspection --- nominal``) was cut, the keys after
    it were lost or the YAML stopped parsing, and the record read with no classification.
    A store-written value holding ``---`` now stays whole (T16 writes four through
    ``write_entry``). A document whose frontmatter is not closed by a line beginning
    ``---`` has no frontmatter here.

    Loading: libyaml (``_RECORDS_YAML_LOADER``) when installed, then ``yaml.safe_load``
    when libyaml refuses the text, so a frontmatter either loader accepts is read, and
    every reader reads it alike. An empty or falsy frontmatter is ``{}``. ``None`` means a
    frontmatter block is there and neither loader accepts it. An error of YAML's
    constructor (``updated: 2026-13-05`` raises ``ValueError``) propagates, as it did from
    ``_parse_document`` on the base.
    """
    if raw.startswith("---"):
        close = raw.find("\n---", 3)
        if close >= 0:
            block = raw[3:close + 1]
            body = raw[close + 4:].strip()
            try:
                frontmatter = yaml.load(block, Loader=_RECORDS_YAML_LOADER)
            except yaml.YAMLError:
                try:
                    frontmatter = yaml.safe_load(block)
                except yaml.YAMLError:
                    return None, body
            return frontmatter or {}, body
    return {}, raw
```
REPLACE:
```python
def _load_frontmatter(block: str) -> Any:
    """BF-952 A1: a frontmatter block loaded by libyaml (``_RECORDS_YAML_LOADER``), then ``yaml.safe_load``.

    ``None`` when neither loader accepts it; ``{}`` for an empty or falsy one. An error of YAML's
    constructor (``updated: 2026-13-05`` raises ``ValueError``) propagates.
    """
    try:
        frontmatter = yaml.load(block, Loader=_RECORDS_YAML_LOADER)
    except yaml.YAMLError:
        try:
            frontmatter = yaml.safe_load(block)
        except yaml.YAMLError:
            return None  # A1: neither loader accepts the block
    return frontmatter or {}


def _line_framing_is_kept(framed: Any, legacy: Any) -> bool:
    """BF-952 A2: whether A1's line framing replaces the base's framing of a document.

    It does when it loads as a mapping and, where the base's framing names a ``classification``,
    names the same one. A frontmatter that a hand-made or legacy file closed inside a line would
    otherwise take the body as YAML: the body may not load, or may give ``classification`` an
    unknown or a repeated value, and the record would lose the level the base read for it.
    """
    if type(framed) is not dict:
        return False
    if type(legacy) is dict and "classification" in legacy:
        return framed.get("classification") == legacy["classification"]
    return True


def _read_document(raw: str) -> tuple[Any, str]:
    """BF-952 A1, A2: a Ship's Records document's frontmatter and body, the one parse every reader uses.

    ``RecordsStore._parse_document``, ``RecordsStore.read_entry`` and the search all call it.

    Framing. A document that starts with ``---`` has frontmatter up to the next ``---``, as the
    base framed it (``raw.split("---", 2)``), and its body is what follows, stripped. When that
    ``---`` is inside a line and a later line begins ``---``, the frontmatter may hold a
    store-written value with ``---`` in it (BF-940, #1686: ``author: Ezri---Prime``,
    ``topic: Inspection --- nominal``), which the base cut. It then runs to that line instead,
    when ``_line_framing_is_kept`` accepts it (A1). It does not when that framing does not load
    as a mapping or names a classification other than the base framing's (A2), so a hand-made
    or legacy file whose frontmatter is closed inside a line reads as on the base, at the level
    the base read. A document with no later ``---`` has no frontmatter, as on the base (L18).

    Loading: ``_load_frontmatter``, so a frontmatter either loader accepts is read, and every
    reader reads it alike. ``None`` means a frontmatter block is there and neither loader
    accepts it. An error of YAML's constructor propagates, as it did from ``_parse_document``
    on the base.
    """
    if not raw.startswith("---"):
        return {}, raw
    cut = raw.find("---", 3)
    if cut < 0:
        return {}, raw
    legacy = _load_frontmatter(raw[3:cut]), raw[cut + 3:].strip()
    close = raw.find("\n---", 3)
    if close + 1 > cut:
        framed = _load_frontmatter(raw[3:close + 1])
        if _line_framing_is_kept(framed, legacy[0]):
            return framed, raw[close + 4:].strip()
    return legacy
```

**A2-02** `src/probos/knowledge/records_store.py`
SEARCH:
```python
                await self._semantic_indexer.index_record(
                    path=path,
                    content=content,
                    classification=classification,
                    author=author,
```
REPLACE:
```python
                await self._semantic_indexer.index_record(
                    path=path,
                    content=content,
                    classification=frontmatter["classification"],
                    author=author,
```

**A2-03** `src/probos/knowledge/records_store.py`
SEARCH:
```python
        logger.info("Record written: %s by %s (%s)", path, author, classification)
```
REPLACE:
```python
        logger.info("Record written: %s by %s (%s)", path, author, frontmatter["classification"])
```

**A2-04** `src/probos/knowledge/records_store.py`
SEARCH:
```text
        the frontmatter **before** ``yaml.dump``, so they round-trip through
        ``_parse_document`` and land whole in the AD-1138 ``frontmatter_json``
        sidecar. Any key in :data:`_RESERVED_FRONTMATTER_KEYS` raises
```
REPLACE:
```text
        the frontmatter **before** ``yaml.dump``, so they round-trip through
        ``_parse_document`` and land whole in the AD-1138 ``frontmatter_json``
        sidecar, when every value is one YAML's safe loader builds (a string,
        number, boolean, date, or a list or mapping of them). BF-952 A2:
        ``yaml.dump`` writes a tuple or another Python object with a
        ``!!python/`` tag, which no reader loads (BF-952 L24). Any key in
        :data:`_RESERVED_FRONTMATTER_KEYS` raises
```

**A2-05** `tests/test_bf952_records_keyword_search.py`
SEARCH:
```python
from probos.knowledge.records_store import RecordsStore
from probos.routers.records import search_records
```
REPLACE:
```python
from probos.knowledge.records_store import RecordsStore
from probos.knowledge.semantic import SemanticKnowledgeLayer
from probos.routers.records import search_records
```

**A2-06** `tests/test_bf952_records_keyword_search.py` (T13: 11 → 14 cases)
SEARCH:
```python
    pytest.param("no frontmatter at all", {}, "no frontmatter at all", id="no-frontmatter"),
])
```
REPLACE:
```python
    pytest.param("no frontmatter at all", {}, "no frontmatter at all", id="no-frontmatter"),
    pytest.param(
        "---\nauthor: alice\nclassification: private --- the closing marker is inline\nbody",
        {"author": "alice", "classification": "private"}, "the closing marker is inline\nbody",
        id="closed-inside-a-line-as-the-base-framed-it",
    ),
    pytest.param(
        "---\nauthor: bones --- warp notes\n", {"author": "bones"}, "warp notes",
        id="closed-inside-a-line-naming-no-classification",
    ),
    pytest.param(
        "---\nauthor: alice\nclassification: private\nbody", {}, "---\nauthor: alice\nclassification: private\nbody",
        id="never-closed-has-no-frontmatter-L18",
    ),
])
```

**A2-07** `tests/test_bf952_records_keyword_search.py` (adds T20 with 6 cases and T21 with 1)
SEARCH:
```python
    outside = await search_records(q="reactor", scope="ship", directory="../outside", runtime=runtime)
    assert isinstance(outside, JSONResponse) and outside.status_code == 400
```
REPLACE:
```python
    outside = await search_records(q="reactor", scope="ship", directory="../outside", runtime=runtime)
    assert isinstance(outside, JSONResponse) and outside.status_code == 400


_INLINE_CLOSE = "---\nauthor: alice\nclassification: private --- the closing marker is inline\n"


@pytest.mark.asyncio
@pytest.mark.parametrize(("raw", "kept"), [
    pytest.param(_INLINE_CLOSE + "warp core notes\n", True, id="closed-inside-a-line"),
    pytest.param(
        _INLINE_CLOSE + "status: nominal\n---\nwarp core notes\n", True, id="closed-inside-a-line-then-a-key-and-a-rule",
    ),
    pytest.param(
        _INLINE_CLOSE + "Warp core notes, in prose.\n---\nmore warp notes\n", True,
        id="closed-inside-a-line-then-prose-and-a-rule",
    ),
    pytest.param(
        _INLINE_CLOSE + "classification: ship\n---\nwarp core notes\n", True,
        id="closed-inside-a-line-then-a-repeated-key-and-a-rule",
    ),
    pytest.param("---\nauthor: alice\nclassification: private\n---\nwarp core notes\n", True, id="closed-on-its-own-line"),
    pytest.param("---\nauthor: alice\nclassification: private\nwarp core notes\n", False, id="never-closed-L18"),
])
async def test_a_frontmatter_closed_inside_a_line_keeps_the_classification_the_base_read(
    tmp_path: Path, raw: str, kept: bool,
) -> None:
    """A2 (round 2, finding 1), through ``read_entry`` and ``search``. A1 ended a frontmatter only at a line
    beginning ``---``, so a hand-made or legacy file closed inside a line read as ``{}`` (the first case) or took
    its body as YAML: the second case then read an unknown classification, the third did not parse (its author
    lost it) and the fourth read the repeated ``ship``. Each read as ``private`` on the base, and does again. The
    fifth is the store's own shape. The last has no closing marker and reads as on the base, with no frontmatter
    (L18); BF-956 owns any change to it and updates this case."""
    store = await _store(tmp_path)
    path = "notebooks/alice/framing.md"
    target = store.repo_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(raw, encoding="utf-8")
    own = await store.read_entry(path, reader_id="alice")
    assert own is not None and "warp" in own["content"].lower()
    assert await _paths(store, "warp", reader_id="alice") == [path]
    other = await store.read_entry(path, reader_id="bob")
    if kept:
        assert own["frontmatter"]["classification"] == "private"
        assert other is None
        assert await _paths(store, "warp", reader_id="bob") == []
    else:
        assert own["frontmatter"] == {} and other is not None
        assert await _paths(store, "warp", reader_id="bob") == [path]


@pytest.mark.asyncio
async def test_a_rewritten_note_is_indexed_at_the_classification_it_keeps(tmp_path: Path) -> None:
    """A2 (round 2, finding 2; AD-1157a): a notebook rewrite that names no classification keeps the note's own, and
    ``write_entry`` handed the semantic index the caller's default (``private``) instead, so a note that reads as
    ``ship`` on disk was missing from another reader's semantic results (on the base too). Real
    ``SemanticKnowledgeLayer`` and Chroma, as in ``test_ad1138_records_semantic_index.py``."""
    store = await _store(tmp_path)
    layer = SemanticKnowledgeLayer(db_path=tmp_path / "semantic", episodic_memory=None)
    await layer.start()
    try:
        store.set_semantic_indexer(layer)
        path = await store.write_notebook("Ezri", "coolant", "reactor coolant log", classification="ship")
        await store.write_notebook("Ezri", "coolant", "reactor coolant log, revised")
        on_disk = await store.read_entry(path, reader_id="alice")
        assert on_disk is not None and on_disk["frontmatter"]["classification"] == "ship"  # premise: AD-1157a kept it
        rows = await layer.search(
            "reactor coolant", types=["records"], limit=20, records_scope="ship", reader_id="alice",
        )
        indexed = [row.get("metadata") or {} for row in rows]
        assert [meta.get("classification") for meta in indexed if meta.get("path") == path] == ["ship"]
    finally:
        await layer.stop()
```

### A2.3 Gates

- **GA2 (A2-M1's head):** GA1's command (§A1.3), unchanged.
  - Expected in the new file: **68 passed (21 functions)**, counted by reading. Every other file: 0 failed, with counts equal to GA1's.
  - Then `scripts/check_architecture_principles.py --check`.
- **Hard stop, back to me:**
  - any T16 case fails (it tests the premise that every store-written value holding `---` keeps the line framing);
  - T21 skips or errors on Chroma;
  - any T20 case fails.
- **B1 and B2 are not rerun.** A record with no `---` inside its frontmatter does one more `str.find` and the same single load. Rerun B1 only if the synthetic corpus generator writes `---` inside a frontmatter value.
- **Mutation campaign:** 38 rows, on A2-M1's head.

### A2.4 Orchestrator steps (§16, read-only clone, counts only)

Add three counts to the census:
1. Records whose frontmatter is closed inside a line, with no later line beginning `---`.
2. Records where `_line_framing_is_kept` returns False with a later line beginning `---` (they fall back to the base framing).
3. Frontmatters containing `!!python/` (L24's reach).

If count 3 is greater than 0, stop and bring it back to me. RK10 then makes such records the Captain's alone at ordinary reach, which needs a decision before landing.

### A2.5 Verified Against Codebase (2026-11-05, on `ed86ae83`)

```
Read records_store.py:241-275    A1 _read_document; :275 "return {}, raw" when no "\n---"
Read :337-357                    search: None withheld for non-Captain (:345-351)
Read :1206-1242                  read_entry: None -> Captain only (:1222-1228); only private/department restrict (:1236-1239)
Read :135-157                    record_is_readable: unlabelled class -> level 0, not gated (:147)
Read :1506-1514                  _parse_document maps None -> {}
git show a745e447:…records_store.py  _parse_document :1265-1275 raw.split("---", 2); read_entry :970-999
Read :552-568, :590-591, :611-628   preserve at :565-568; yaml.dump :590; index_record classification=classification :614; log :628
Read :765-775                    write_notebook: default NOTEBOOK_DEFAULT_CLASSIFICATION, preserve=(classification is None)
Read :1330-1346                  publish: {} -> only the Captain; rewrites with the parsed fm
Read semantic.py:736-752         backfill read_entry(_UNRESTRICTED_READER); classification default "ship" :746
Read tests/test_ad1138_records_semantic_index.py:42-60, :273-289   real SemanticKnowledgeLayer fixture; layer.search(..., reader_id=)
git ls-files --eol               i/lf w/crlf for all five edited files
```

```
### Absence Verified, Amendment A2 (2026-11-05, on `ed86ae83`)
CLAIM: write_notebook is the only caller that sets preserve_classification_on_update
RUN:   Grep "preserve_classification_on_update" src
FOUND: records_store.py:499, :514, :565 (definition, docstring, use), :775 (the one caller)   HOLDS: yes
CLAIM: new mutation lines are unique (substring)
RUN:   Grep "^ {12,}return None\s*$|if cut < 0|close \+ 1 > cut|return framed" records_store.py
FOUND: 12-space "return None" at :1218, :1485 (so RKS-25's line carries a comment); the others absent   HOLDS: yes
CLAIM: no test name or docstring claims an unrestricted round trip
RUN:   Grep "(?i)round|hand" tests/test_bf952_records_keyword_search.py
FOUND: :345 only ("hands its JSON")   HOLDS: yes
CLAIM: each SEARCH occurs once
RUN:   grep -c / grep -n on each anchor
FOUND: records_store.py :507, :614, :628 once each; DECISIONS.md scope :1351, RK12 :1362, Residual :1364 once each;
       tests: "outside.status_code == 400", "no frontmatter at all" param, the RecordsStore import, once each;
       PROGRESS.md framing phrase once; contract: "## 4. Milestones" :120, "- **M0:**" :130, "Not built. Each item" :955,
       "## 11. Recorded limits" :1014, "## 12. Verified" :1040, "**BF number:** BF-952" :8, "## For the Captain" :2349, once each.
       Duplicates avoided by the headings: the RK12, A1-M2, T19, L18-L23 and "Status" lines also occur in §A1.7.   HOLDS: yes
```

Not checked by execution (read-only bridge): the behaviour of YAML on T20's prose case (a column-0 line without `:` after a mapping raises "could not find expected ':'"), and duplicate-key last-wins in `CSafeLoader`. If either does not hold, GA2 fails at T20, which is a hard stop.

### A2.6 Prior art

No web search. This is ProbOS plumbing, python-frontmatter's delimiter rule is already cited in §A1.8, and no `reference-projects.md` row was examined.

## For the Captain

None to decide. The change is reversible, keeps every caller's contract, strengthens privacy (RK3), and makes the loop more responsive than the base. For the Captain's information: #1686 is a P1, security-class defect on the base since the store's first parser, with ordinary reach through the notebook write API. A1 and A2 tried to close it for Ship's Records inside this BF; A3 withdraws that (§A3), and #1686 stays open for Ship's Records and the skill catalog with BF-952's findings attached.

## Amendment A3 (2026-11-06): round-three brake after review round 3 (GPT-6.1 Sol, NOT READY)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-06. **Anchors:** head `cf61c683`.

### A3.1 Decision: split
| Finding | Disposition |
|---|---|
| R3-F1 (P1, A2) | Base-equal under RK15; moved to #1686 (L25) |
| R3-F2 (P1, A1 regression) | Gone: the base reads the record as alice's (T20's new case) |
| R3-F3 (P2, ordinary, A2) | Base-equal for `read_entry`, withheld by search; moved to #1686 (L25) |
| R3-F3b (P2) | Gone: one frame |
| R3-F4 (P3) | Fixed: the AD-1140 docstring names the 4,000-character cap |
| Round 1 F1, round 2 F3/F4 (base) | Moved to #1686 (L19, L24, L25) |

- **RK15 (A3).** Every reader reads every document as `a745e447`'s `_parse_document` did, constructor errors included, with two exceptions: a frontmatter only libyaml accepts (RK8), and search's withholding of a record whose parse raises or is not a mapping.
- **RK9, RK10 and RK13 are withdrawn.**
- **Rejected:** a third reconciliation in this BF. Requiring every authorization field to agree makes the owner of `author: Ezri---Prime` lose her note. A fail-closed sentinel is rewritten as `{}` by `publish` and update-in-place (§A2.1).
- **#1751's acceptance needs no framing change.**

### A3.2 Gates
- **GA3 (A3-M1's head):** GA1's command (§A1.3).
  - Expected in the new file: **63 passed (20 functions)**.
  - Expected in total: **834 passed, 1 skipped** (GA2's 839 less 5).
  - Then `scripts/check_architecture_principles.py --check`.
  - No UI change.
- **Hard stops:**
  - T22 fails: report `len(differ)` and the first five shapes, and do not tune;
  - any T20 or T13 case fails;
  - T21 skips.
- **B1/B2 not rerun:** one split and one load per record, never more work than A2.
- **Mutation:** rerun RKS-13, 26, 27, 30 and 41–44 (8 rows) on A3-M1's head. The other 24 active rows carry forward from A2's campaign: neither their Line nor their claimed test changed.

### A3.3 Mutation rows
| # | File | Line | Mutate to | Claimed failing test |
|---|---|---|---|---|
| RKS-41 | records_store.py | `        parts = raw.split("---", 2)` | `        parts = [""] + raw[3:].split("\n---", 1)` | `test_every_document_reads_as_on_the_base` |
| RKS-42 | records_store.py | `            return ({} if frontmatter is None else frontmatter), parts[2].strip()` | `            return frontmatter, parts[2].strip()` | `test_every_reader_frames_and_loads_a_document_alike` (malformed-yaml) |
| RKS-43 | records_store.py | the RKS-42 line | `            return ({} if frontmatter is None else frontmatter), parts[2]` | same test (the-store-shape) |
| RKS-44 | records_store.py | `        if len(parts) >= 3:` | `        if len(parts) >= 2:` | same test (never-closed-L18) |

Retired: RKS-23, 24, 25 (now an equivalent mutant), 31, 32, 35, 36, 37, 38 and 40. **32 rows are active.**

### A3.4 Orchestrator steps (§16 census, read-only clone, counts only)
- Replace §A2.4 with these counts: files; base `_parse_document` equal to head `_read_document`; differing; differing where the base's `safe_load` raised `YAMLError` (RK8 only); frontmatters holding `---` before their closing line (#1686's live reach); `!!python/` count.
- **Stop and return to the Architect** if any differing record is not an RK8 case.
- Post the counts on #1686 too.

### A3.5 Pairs
**A3-01 — `src/probos/knowledge/records_store.py`** (`:257-303`; `def _line_framing_is_kept` occurs once)
SEARCH:
```python
def _line_framing_is_kept(framed: Any, legacy: Any) -> bool:
    """BF-952 A2: whether A1's line framing replaces the base's framing of a document.

    It does when it loads as a mapping and, where the base's framing names a ``classification``,
    names the same one. A frontmatter that a hand-made or legacy file closed inside a line would
    otherwise take the body as YAML: the body may not load, or may give ``classification`` an
    unknown or a repeated value, and the record would lose the level the base read for it.
    """
    if type(framed) is not dict:
        return False
    if type(legacy) is dict and "classification" in legacy:
        return framed.get("classification") == legacy["classification"]
    return True


def _read_document(raw: str) -> tuple[Any, str]:
    """BF-952 A1, A2: a Ship's Records document's frontmatter and body, the one parse every reader uses.

    ``RecordsStore._parse_document``, ``RecordsStore.read_entry`` and the search all call it.

    Framing. A document that starts with ``---`` has frontmatter up to the next ``---``, as the
    base framed it (``raw.split("---", 2)``), and its body is what follows, stripped. When that
    ``---`` is inside a line and a later line begins ``---``, the frontmatter may hold a
    store-written value with ``---`` in it (BF-940, #1686: ``author: Ezri---Prime``,
    ``topic: Inspection --- nominal``), which the base cut. It then runs to that line instead,
    when ``_line_framing_is_kept`` accepts it (A1). It does not when that framing does not load
    as a mapping or names a classification other than the base framing's (A2), so a hand-made
    or legacy file whose frontmatter is closed inside a line reads as on the base, at the level
    the base read. A document with no later ``---`` has no frontmatter, as on the base (L18).

    Loading: ``_load_frontmatter``, so a frontmatter either loader accepts is read, and every
    reader reads it alike. ``None`` means a frontmatter block is there and neither loader
    accepts it. An error of YAML's constructor propagates, as it did from ``_parse_document``
    on the base.
    """
    if not raw.startswith("---"):
        return {}, raw
    cut = raw.find("---", 3)
    if cut < 0:
        return {}, raw
    legacy = _load_frontmatter(raw[3:cut]), raw[cut + 3:].strip()
    close = raw.find("\n---", 3)
    if close + 1 > cut:
        framed = _load_frontmatter(raw[3:close + 1])
        if _line_framing_is_kept(framed, legacy[0]):
            return framed, raw[close + 4:].strip()
    return legacy
```
REPLACE:
```python
def _read_document(raw: str) -> tuple[Any, str]:
    """BF-952 A1, A3: a Ship's Records document's frontmatter and body, the one parse every reader uses.

    ``RecordsStore._parse_document``, ``RecordsStore.read_entry`` and the search all call it.

    Framing (A3): exactly the base's. A document that starts with ``---`` has frontmatter up to
    the next ``---`` wherever it stands, inside a value too, and its body is what follows,
    stripped; one with no later ``---`` has no frontmatter (L18). That framing cuts a value
    holding ``---``; BF-940 (#1686) owns changing it, for every reader at once (L25).

    Loading (RK8): ``_load_frontmatter``, libyaml then ``yaml.safe_load``, so every reader reads a
    frontmatter alike. A frontmatter neither loader accepts reads as ``{}``, as on the base. An
    error of YAML's constructor (``updated: 2026-13-05``) propagates, as it did from
    ``_parse_document`` on the base; the search withholds such a record.
    """
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            frontmatter = _load_frontmatter(parts[1])
            return ({} if frontmatter is None else frontmatter), parts[2].strip()
    return {}, raw
```

**A3-02 — `src/probos/knowledge/records_store.py`** (`:373-380`; unique by its `# A1: a frontmatter block no loader accepts` line)
SEARCH:
```python
        if frontmatter is None:
            # A1: a frontmatter block no loader accepts names no classification, so the record
            # is shown to the Captain alone, as ``read_entry`` rules.
            if reader_id != _UNRESTRICTED_READER:
                logger.debug("BF-952: withholding %s, whose frontmatter does not parse", rel_path)
                continue
            frontmatter = {}
        if type(frontmatter) is not dict:
```
REPLACE:
```python
        if type(frontmatter) is not dict:
```
(`_UNRESTRICTED_READER` is still used at `:85` and `:145`, so there is no unused-name lint.)

**A3-03 — `src/probos/knowledge/records_store.py`** (`:1408-1409`)
SEARCH:
```
        build (``updated: 2026-13-05``), is skipped; one whose frontmatter does not
        parse is shown to the Captain alone, as :meth:`read_entry` rules (A1). A
```
REPLACE:
```
        build (``updated: 2026-13-05``), is skipped; one whose frontmatter does not
        parse reads as ``{}``, as every reader reads it (A3; BF-940, #1686). A
```

**A3-04 — `src/probos/knowledge/records_store.py`** (`:534-541`, R3-F4)
SEARCH:
```
        AD-1140: ``extra_frontmatter`` merges caller-owned envelope fields into
        the frontmatter **before** ``yaml.dump``, so they round-trip through
        ``_parse_document`` and land whole in the AD-1138 ``frontmatter_json``
        sidecar, when every value is one YAML's safe loader builds (a string,
        number, boolean, date, or a list or mapping of them). BF-952 A2:
        ``yaml.dump`` writes a tuple or another Python object with a
        ``!!python/`` tag, which no reader loads (BF-952 L24). Any key in
```
REPLACE:
```
        AD-1140: ``extra_frontmatter`` merges caller-owned envelope fields into
        the frontmatter **before** ``yaml.dump``. They round-trip through
        ``_parse_document`` when every value is one YAML's safe loader builds
        (a string, number, boolean, date, or a list or mapping of them) and
        holds no ``---``, which the reader's framing cuts (BF-940, #1686).
        ``yaml.dump`` writes a tuple or another Python object with a
        ``!!python/`` tag, which no reader loads (BF-952 L24). The AD-1138
        ``frontmatter_json`` sidecar holds them whole only within
        ``semantic.py``'s 4,000-character cap (``_RECORD_FRONTMATTER_CHARS``);
        past it the index stores ``{}``. Any key in
```

**A3-05 — `src/probos/knowledge/records_store.py`** (`:1253-1262`)
SEARCH:
```python
        frontmatter, content = _read_document(raw)
        if frontmatter is None:
            # BF-952 A1: a frontmatter block that no loader accepts names no classification.
            # The base read it as ``{}``, so as ``ship``, and showed it to every reader; now
            # only the Captain, who reads every record, is shown it.
            if reader_id != "captain":
                return None
            frontmatter = {}

        # Classification check — Captain has unrestricted read access
```
REPLACE:
```python
        frontmatter, content = _read_document(raw)

        # Classification check — Captain has unrestricted read access
```

**A3-06 — `src/probos/knowledge/records_store.py`** (`:1539-1546`)
SEARCH:
```python
        """Parse YAML frontmatter + content from a markdown document.

        BF-952 A1: :func:`_read_document` frames and loads it, as it does for ``read_entry``
        and the search. A frontmatter block that no loader accepts reads as ``{}`` here, as
        on the base; ``read_entry`` and the search show such a record to the Captain alone.
        """
        frontmatter, content = _read_document(raw)
        return ({} if frontmatter is None else frontmatter), content
```
REPLACE:
```python
        """Parse YAML frontmatter + content from a markdown document.

        BF-952 A1, A3: :func:`_read_document` frames and loads it with the base's framing,
        as it does for ``read_entry`` and the search.
        """
        return _read_document(raw)
```

**A3-07 — `src/probos/knowledge/lessons.py`** (`:85-87`; this restores `a745e447:85-86` exactly, so the file leaves the diff)
SEARCH:
```
# A4 (R2-F3): Ship's Records split a document's frontmatter at the first two "---" it found, inside a value too
# (records_store._parse_document, register R25), so an envelope value holding one came back cut short. BF-952 A1
# ends the frontmatter only at a "---" that begins a line; this rule still refuses "---" and is unchanged.
```
REPLACE:
```
# A4 (R2-F3): Ship's Records splits a document's frontmatter at the first two "---" it finds, inside a value too
# (records_store._parse_document, register R25), so an envelope value holding one would come back cut short.
```

**A3-08 — `tests/test_ad1341_s4_lessons.py`** (`:646-648`; this restores the base text, so the file leaves the diff)
SEARCH:
```
    """A4 (R2-F3): Ship's Records cut a document's frontmatter at the first two ``---`` it found, wherever they stood
    (register R25; BF-952 A1 now ends it only at a ``---`` that begins a line), so a callsign such as
    ``normal---value`` came back as ``normal``: the stand-down reported the
```
REPLACE:
```
    """A4 (R2-F3): Ship's Records cuts a document's frontmatter at the first two ``---`` it finds, wherever they stand
    (register R25), so a callsign such as ``normal---value`` came back as ``normal``: the stand-down reported the
```

**A3-09 — `tests/test_bf952_records_keyword_search.py`** (`:13-15`)
SEARCH:
```
from __future__ import annotations

import threading
```
REPLACE:
```
from __future__ import annotations

import itertools
import threading
```

**A3-10 — `tests/test_bf952_records_keyword_search.py`** (`:269-279`; `id="a-value-holding-three-hyphens"` occurs once)
SEARCH:
```
    pytest.param(
        "---\ntopic: Inspection --- nominal\nclassification: private\n---\nbody",
        {"topic": "Inspection --- nominal", "classification": "private"}, "body", id="a-value-holding-three-hyphens",
    ),
    pytest.param(
        "---\ntopic: 'Inspection --- status: nominal'\nclassification: private\n---\nbody",
        {"topic": "Inspection --- status: nominal", "classification": "private"}, "body",
        id="a-quoted-value-holding-a-key",
    ),
    pytest.param(
        "---\nauthor: bones\n---\nabove\n---\nbelow", {"author": "bones"}, "above\n---\nbelow",
```
REPLACE:
```
    pytest.param(
        "---\nauthor: bones\n---\nabove\n---\nbelow", {"author": "bones"}, "above\n---\nbelow",
```

**A3-11 — `tests/test_bf952_records_keyword_search.py`** (`:286-290`)
SEARCH:
```
    pytest.param("---\nkey: [unclosed\n---\nbody", None, "body", id="malformed-yaml"),
    pytest.param(
        "---\nclassification:\tprivate\n---\nbody", {"classification": "private"} if _LIBYAML else None, "body",
        id="a-tab-only-libyaml-accepts",
    ),
```
REPLACE:
```
    pytest.param("---\nkey: [unclosed\n---\nbody", {}, "body", id="malformed-yaml"),
    pytest.param(
        "---\nclassification:\tprivate\n---\nbody", {"classification": "private"} if _LIBYAML else {}, "body",
        id="a-tab-only-libyaml-accepts",
    ),
```

**A3-12 — `tests/test_bf952_records_keyword_search.py`** (`:306-315`)
SEARCH:
```python
def test_every_reader_frames_and_loads_a_document_alike(
    tmp_path: Path, raw: str, frontmatter: dict[str, Any] | None, body: str,
) -> None:
    """A1 (BF-940, #1686; finding 6): ``_read_document`` is the one parse. ``_parse_document`` reads ``None`` (a
    frontmatter block no loader accepts) as ``{}``, as on the base. The base cut the second and third cases at the
    ``---`` inside the topic, and the third then did not parse. A tab after a key is refused by PyYAML's scanner
    and accepted by libyaml, so with libyaml installed every reader now reads it."""
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    assert records_store_module._read_document(raw) == (frontmatter, body)
    assert store._parse_document(raw) == ({} if frontmatter is None else frontmatter, body)
```
REPLACE:
```python
def test_every_reader_frames_and_loads_a_document_alike(
    tmp_path: Path, raw: str, frontmatter: dict[str, Any], body: str,
) -> None:
    """A1 (finding 6), A3: ``_read_document`` is the one parse, with the base's framing. A frontmatter block no
    loader accepts reads as ``{}``, as on the base. A tab after a key is refused by PyYAML's scanner and accepted by
    libyaml, so with libyaml installed every reader now reads it (RK8). A value holding ``---`` is BF-940's
    (#1686), not this file's."""
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    assert records_store_module._read_document(raw) == (frontmatter, body)
    assert store._parse_document(raw) == (frontmatter, body)
```

**A3-13 — `tests/test_bf952_records_keyword_search.py`** (`:368-423`: retires T16 and T17; T-labels are not reused)
SEARCH:
```python
@pytest.mark.asyncio
@pytest.mark.parametrize(("author", "values"), [
    pytest.param("Ezri---Prime", {}, id="an-author-holding-three-hyphens"),
    pytest.param("Ezri", {"topic": "Inspection --- status: nominal"}, id="a-quoted-topic-holding-a-key"),
    pytest.param("Ezri", {"topic": "first line\n---\nlast line"}, id="a-multi-line-topic-holding-a-rule"),
    pytest.param("Ezri", {"tags": ["warp --- core"]}, id="a-tag-holding-three-hyphens"),
])
async def test_a_frontmatter_value_holding_three_hyphens_is_read_whole_and_stays_private(
    tmp_path: Path, author: str, values: dict[str, Any],
) -> None:
    """Finding 1 and BF-940 (#1686), through ``write_entry``, ``read_entry``, ``search`` and update-in-place. The
    base ended the frontmatter at the first ``---`` anywhere. The author's case kept only ``author``, and neither
    topic case parsed, so each read as ``ship`` and another reader was shown the private record; the tag's case
    kept its classification, and its body began with the rest of the tag. The multi-line case checks that
    ``yaml.dump`` starts no line of a value with ``---``."""
    store = await _store(tmp_path)
    path = "notebooks/Ezri/inspection.md"
    write: dict[str, Any] = {
        "author": author, "path": path, "content": "PRIVATE_BODY_PROOF the coolant", "message": "probe",
        "classification": "private", **values,
    }
    await store.write_entry(**write)
    own = await store.read_entry(path, reader_id=author)
    assert own is not None and own["frontmatter"]["classification"] == "private"
    assert {key: own["frontmatter"][key] for key in values} == values
    assert own["content"] == "PRIVATE_BODY_PROOF the coolant"
    assert await store.read_entry(path, reader_id="alice") is None
    assert await _paths(store, "coolant", reader_id="alice") == []
    assert await _paths(store, "coolant", reader_id=author) == [path]
    await store.write_entry(**write)  # update-in-place carries ``created`` forward and counts the revision
    again = await store.read_entry(path, reader_id=author)
    assert again is not None and again["frontmatter"]["revision"] == 2
    assert again["frontmatter"]["created"] == own["frontmatter"]["created"]


@pytest.mark.asyncio
async def test_a_record_whose_frontmatter_does_not_parse_is_shown_to_the_captain_alone(tmp_path: Path) -> None:
    """RK10 (finding 1's injected reach): such a record names no classification. The base read it as ``{}``, so as
    ``ship``, and every reader was shown it. Now ``read_entry`` and ``search`` show it to the Captain alone; its
    author is unknown, so the author is not shown it either."""
    store = await _store(tmp_path)
    _write(store, "reports/open.md", "warp core report")
    (store.repo_path / "notebooks" / "Bravo").mkdir(parents=True, exist_ok=True)
    (store.repo_path / "notebooks" / "Bravo" / "secret.md").write_text(
        "---\nauthor: Bravo\nclassification: private\ntitle: [unclosed\n---\n\nwarp core secret\n", encoding="utf-8",
    )
    assert await store.read_entry("notebooks/Bravo/secret.md", reader_id="alice") is None
    assert await store.read_entry("notebooks/Bravo/secret.md", reader_id="Bravo") is None
    captain = await store.read_entry("notebooks/Bravo/secret.md", reader_id="captain")
    assert captain is not None and captain["frontmatter"] == {} and captain["content"] == "warp core secret"
    assert await _paths(store, "warp", reader_id="alice") == ["reports/open.md"]
    assert set(await _paths(store, "warp", reader_id="captain")) == {"reports/open.md", "notebooks/Bravo/secret.md"}


@pytest.mark.asyncio
@pytest.mark.parametrize("updated", [
```
REPLACE:
```python
@pytest.mark.asyncio
@pytest.mark.parametrize("updated", [
```

**A3-14 — `tests/test_bf952_records_keyword_search.py`** (`:477`; `id="closed-on-its-own-line"` occurs once)
SEARCH:
```
    pytest.param("---\nauthor: alice\nclassification: private\n---\nwarp core notes\n", True, id="closed-on-its-own-line"),
```
REPLACE:
```
    pytest.param(
        "---\nauthor: alice\nclassification: private --- legacy\nclassification: private\nauthor: bob\n---\n"
        "warp core notes\n",
        True, id="closed-inside-a-line-then-keys-naming-another-author-and-a-rule",
    ),
    pytest.param("---\nauthor: alice\nclassification: private\n---\nwarp core notes\n", True, id="closed-on-its-own-line"),
```

**A3-15 — `tests/test_bf952_records_keyword_search.py`** (`:486-488`)
SEARCH:
```
    lost it) and the fourth read the repeated ``ship``. Each read as ``private`` on the base, and does again. The
    fifth is the store's own shape. The last has no closing marker and reads as on the base, with no frontmatter
    (L18); BF-956 owns any change to it and updates this case."""
```
REPLACE:
```
    lost it) and the fourth read the repeated ``ship``. Each read as ``private`` on the base, and does again. In the
    fifth (round 3, finding 2) A1 and A2 read the repeated keys and gave the record to ``bob``; it is ``alice``'s, as
    on the base (A3: the base's framing for every reader). The sixth is the store's own shape. The last has no
    closing marker and reads as on the base, with no frontmatter (L18); BF-940 (#1686) owns any change to it and
    updates this case."""
```

**A3-16 — `tests/test_bf952_records_keyword_search.py`** (`:526-528`; `await layer.stop()` occurs once). This appends T22.
SEARCH:
```python
        assert [meta.get("classification") for meta in indexed if meta.get("path") == path] == ["ship"]
    finally:
        await layer.stop()
```
REPLACE:
```python
        assert [meta.get("classification") for meta in indexed if meta.get("path") == path] == ["ship"]
    finally:
        await layer.stop()


def _base_read(raw: str) -> tuple[Any, str]:
    """``RecordsStore._parse_document`` of the base (``a745e447``, ``records_store.py:1265-1275``), verbatim but for
    ``self``: T22's oracle. It is a reference, not a statement that the base frames correctly: BF-940 (#1686) owns
    the framing, replaces this oracle with its own rule and rewrites T22."""
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                fm = {}
            return fm, parts[2].strip()
    return {}, raw


def _read_or_error(read: Any, raw: str) -> Any:
    """``read(raw)``, or the name of the exception it raised: a constructor error must be the same error."""
    try:
        return read(raw)
    except Exception as exc:  # noqa: BLE001 -- compared, never swallowed: the test asserts on it
        return type(exc).__name__


_GRID_LINES = (
    "author: alice", "author: alice --- legacy", "author: Ezri---Prime",
    "classification: private", "classification: private --- legacy", "classification: ship",
    "department: medical", "topic: Review --- nominal", "topic: 2026-13-05---nominal",
    "topic: 'Inspection --- status: nominal'", "broken: [unclosed", "updated: 2026-13-05",
)
_GRID_CLOSES = ("---\n", "----\n", "")
_GRID_BODIES = ("", "warp notes\n", "classification: ship\nauthor: bob\n", "---\nmore notes\n")


def test_every_document_reads_as_on_the_base(tmp_path: Path) -> None:
    """A3 (round 3, findings 1 to 3): BF-952 changes no reader's reading of a document. Each reconciliation of the
    base's framing with a line framing (A1, A2) misread some shape: as ``{}``, as an unclassified prefix, as another
    author's, or as a constructor error for a valid store-written value. Every shape here, over the three rounds'
    lines, closing markers, bodies and both line endings, reads under ``_read_document`` and ``_parse_document``
    exactly as the base read it, a constructor error included. No line holds a tab, so libyaml and PyYAML read each
    alike; RK8's one difference is T13's tab case."""
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    shapes = [
        "---\n" + "".join(f"{line}\n" for line in lines) + close + body
        for count in (1, 2)
        for lines in itertools.product(_GRID_LINES, repeat=count)
        for close in _GRID_CLOSES
        for body in _GRID_BODIES
    ]
    shapes += [shape.replace("\n", "\r\n") for shape in shapes]
    shapes += ["no frontmatter", "-- two hyphens\n---\nbody", "\n---\nauthor: alice\n---\nbody"]
    assert len(shapes) == 3747  # premise: (12 + 144) line sequences x 3 closes x 4 bodies x 2 line endings, + 3
    differ = []
    for shape in shapes:
        expected = _read_or_error(_base_read, shape)
        if (
            _read_or_error(records_store_module._read_document, shape) != expected
            or _read_or_error(store._parse_document, shape) != expected
        ):
            differ.append(shape)
    assert differ == [], (len(differ), differ[:5])
```

### A3.6 #1686 hand-off (one comment; no new issue)
- The findings in A3.1.
- RK10's design constraint: the sentinel must survive `_parse_document` (`publish` and update-in-place), and must not take a store-written record from its owner.
- T16 and T17 at `cf61c683`, and the reviewer's corpus, as acceptance.
- L19 and L24.
- **BF-956 is not filed.**

### A3.7 Prior art
No web search: A3 is a revert to the base. The framing rule's prior art (§A1.8) belongs to #1686.
