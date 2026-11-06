# BF-952 (#1751): Ship's Records keyword search matches whole words and ranks rare ones first

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-05
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-05: cost amendment, after the orchestrator measured the draft at about 2.7 s per call that blocked the event loop. It adds RK7 and RK8, rewrites the search internals inside P1-2 and P1-3, adds tests T13 and T14 and one T4 case, re-anchors RKS-4, RKS-7 to RKS-13, RKS-16 and RKS-18, adds rows RKS-19 to RKS-22, adds bounds B1 and B2 (§4, §16), and revises L1 and adds L13 to L16.
**Revised by:** the orchestrator (Copilot), 2026-11-06: P1-3's SEARCH, which the cost amendment wrote as a reference to the first draft, is the verbatim 68-line block of `records_store.py:1109-1176` (the script that restored it asserts that it equals the base file's text); and the base is the AD-1346 M3e4d6 to M3e4d8 batch's merge, so the batch's own `PROGRESS.md` and `DECISIONS.md` text is on it (P3-1's SEARCH is the title line and P3-2's the BF-950 heading, and both still occur once); the Status line names the batch's merge (`a745e447`) instead of its branch; no other change.
**Status:** ready to build. **Base:** drafted on `1c01a5ee` (`origin/main`, the BF-950 merge). The AD-1346 M3e4d6–d8 batch merged first (`a745e447`, PR #1756) and changed none of the M1 or M2 files: `git diff --stat 1c01a5ee a745e447 -- src/probos/knowledge/records_store.py tests/test_bf949_notebook_reader_identity.py tests/test_layer_boundaries.py` is empty. **M3's SEARCH text was written against `1c01a5ee` and still occurs once on `a745e447`, so §8 needed no re-anchoring.** **Dependencies:** none. **Tier:** M1 STANDARD with a shared contract (the `search` result list, read by four production callers and the HXI); M2 STANDARD, test only; M3 STANDARD, trackers. **Estimated tests:** one new file, `tests/test_bf952_records_keyword_search.py`, with 14 functions and 42 cases (counted by reading). Edits: `tests/test_bf949_notebook_reader_identity.py` (one assertion) and `tests/test_layer_boundaries.py` (one allowlist entry).
**BF number:** BF-952, held by the title of #1751 (OPEN). Nothing is allocated, and no AD number is needed.

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
- Return shape, cap, scope and reader rules are unchanged, and no caller changes.

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

**RK5, non-mapping frontmatter.** A YAML list or scalar made `record_is_readable` raise on the base. It is now skipped with a debug log. It names no classification, so withholding it is the fail-closed choice.

**RK6, where `record_write_time` lives.** It is imported from `probos.cognitive.provenance`, which imports only the standard library (`provenance.py:13-21`), with one `test_layer_boundaries` allowlist entry (AD-583 precedent, `:87-88`). Rejected: a local copy (DRY); moving the parser into `knowledge/` (that refactors BF-950's merged code, L5).

**RK7, cost (ranked; 1 to 3 are chosen together).**
1. **Chosen: count only what can match.**
   - Per record, lower-case the scored texts and measure the length with one C-level `findall` per text.
   - If no query term is a substring of any scored text, stop there: the record counts toward N, df = 0 and the average length only.
   - Otherwise, count terms with `Counter` over the `findall` results (compounds only when the query has a compound term).
   - The check runs on the **parsed** text, not the raw file, so a YAML-escaped value (`"Caf\xE9"`) is still found. A term counted as a word is always a substring of its lowered text, so the check loses nothing.
2. **Chosen:** parse frontmatter inside `search` with `yaml.CSafeLoader` when `yaml.__with_libyaml__`, else `yaml.SafeLoader`, with a `safe_load` retry on a libyaml error (RK8).
3. **Chosen:** run the synchronous walk in `asyncio.to_thread` through a module function that touches no store state and writes nothing.
4. Rejected for this BF: an in-memory cache keyed by path, `mtime_ns` and size.
   - It is shared mutable state read from worker threads.
   - It needs invalidation for deletes and for same-size rewrites within one mtime tick.
   - It holds roughly the corpus text in memory.
   - It still costs a stat per file per call.
   - It is the index; see N1.
5. Deferred: the index as its own item (N1, under #1754).
- Measured by B1 and B2 (§4). The first is the base's worst case; the second, the loop.

**RK8, the search parse.**
- `_search_document(raw)` repeats `_parse_document`'s split and result. Only the loader differs.
- `_parse_document` is untouched: `read_entry` and the other readers keep PyYAML.
- T13 holds the two equal over the store's shape, a YAML date, an escaped value, a list, empty, malformed and absent frontmatter.

## 4. Milestones and gates

| M | Tier | Shared contract? | Pairs | Gate |
|---|---|---|---|---|
| M1 | STANDARD | **yes**: the `search` result list and its `score` | P1-1 to P1-5 (5) | G1 |
| M2 | STANDARD | test only | N2-1 (1, full file) | G2, then B1 and B2 |
| M3 | STANDARD | trackers | P3-1, P3-2 (2), ledger | G3 |

- **M0:** on the base, record the collected count of every existing file named in G1.
- **G1:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_records_store.py tests/test_bf949_notebook_reader_identity.py tests/test_bf679_oracle_records_reader_identity.py tests/test_bf684_records_index_coverage.py tests/test_ad1138_records_semantic_index.py tests/test_ad725_dm_targeted_lookup.py tests/test_ad1139_oracle_query_tool.py tests/test_ad1140_publish_finding.py tests/test_ad1141_crew_loop_sigma.py tests/test_bf950_oracle_result_age.py tests/test_self_monitoring.py tests/test_proactive_quality.py tests/test_path_traversal.py tests/test_layer_boundaries.py tests/test_ad1346_admission_file_write_census.py tests/test_ad1346_admission_effect_census.py tests/test_ad1346_admission_store_family_census.py tests/test_ad1341_s6_records_snapshot.py -q -n 0`, then `... -P scripts/check_architecture_principles.py --check`.
  - Expected: 0 failed; counts equal to M0.
  - **Hard stop:** any failure of `test_bf949…::test_the_agents_own_entry_is_found_behind_twenty_readable_matches`. Its premise rests on V-BF949 (§12). Return to the Architect.
- **G2:** `... -m pytest tests/test_bf952_records_keyword_search.py <the 18 G1 files> -q -n 0`. Expected in the new file: **42 passed**. Others: 0 failed.
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
| T13 | `test_search_reads_a_document_as_the_store_reads_it` | 7 | RK8 | n/a (new helper) |
| T14 | `test_a_search_runs_off_the_event_loop` | 1 | RK7 option 3 | yes |

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

**BF-952 (2026-11-05), #1751 -- Ship's Records keyword search matches whole words and ranks rare ones first.** On the base `RecordsStore.search` scored a record by the fraction of query words found as substrings anywhere in the raw file, YAML keys included, and broke ties by path. So `i` matched "ship", `status` matched every record, and the Captain's question to Ezri matched all 2,768 live records at one score, with the three tic-tac-toe records last. Now the query and each record are split into whole words (an identifier such as `bf-952` whole and by its parts). The query's stopwords are dropped, and all its words are kept when nothing else is left. The body and the `title`, `topic`, `tags`, `department` and `author` values are scored, never a key. Records rank by how much of the query's rarity they hold, then by BM25 with title, topic and tag hits above body hits, then by the newer `updated`, then by path. `score` stays between 0 and 1 and never rises down the list. Rarity is counted only over records the reader may read. A record whose frontmatter is not a mapping is skipped instead of raising. The walk runs in a worker thread, parses frontmatter with libyaml when installed and counts terms only in records that hold one, so a search no longer blocks the event loop and is no slower than the base's slowest search on a 2,801-record corpus. The return shape, the 20-result cap, BF-679 and BF-949 are unchanged, and so is the Oracle's division of the keyword score by ten. No config field. The contract is `prompts/bf-952-records-keyword-search.md`.

```

**P3-2** `DECISIONS.md`

SEARCH:
```
### BF-950 -- An oracle_query result is aged by its own write time, not by its retrieval (2026-11-05, #1742)
```
REPLACE:
```
### BF-952 -- Ship's Records keyword search matches whole words and ranks rare ones first (2026-11-05, #1751)

- *Scope.* `knowledge/records_store.py` (`RecordsStore.search`; module functions `_search_query_terms`, `_search_field_text`, `_search_document`, `_search_record_counts`, `_search_records`; the `_SEARCH_*` constants), `tests/test_layer_boundaries.py` (one allowlist entry), `tests/test_bf949_notebook_reader_identity.py` (one order assertion), tests. Contract `prompts/bf-952-records-keyword-search.md`.
- *RK1 (matching).* Whole words of the body and of the `title`, `topic`, `tags`, `department` and `author` values; compounds whole and by part; query stopwords dropped, all words kept when nothing else is left. Rejected: substring matching; scoring every frontmatter value.
- *RK2 (rank and score).* IDF-weighted coverage, then BM25 with field weights, then the newer `updated` (else `created`, by BF-950's `record_write_time`), then path. `score` is the coverage, 0 to 1, non-increasing. Rejected: BM25 over the top score; BM25 order with a coverage score.
- *RK3 (privacy).* Term rarity is counted only over records the reader may read; `_archived/` is excluded.
- *RK4 (compatibility).* Return shape, cap, scope and reader rules unchanged; the Oracle's `/10` unchanged, so AD-1141's 0.35 floor still admits no keyword-only record.
- *RK5.* A record whose frontmatter is not a mapping is withheld; it raised on the base.
- *RK7 (cost).* A worker thread (`asyncio.to_thread`), libyaml for the search parse, and term counting only in records that hold a query term as a substring of their parsed text. Bound: no slower than the base's match-all search, and the event loop is not blocked for more than 100 ms. Rejected for this BF: an in-memory cache (shared state across threads, invalidation, memory); an index is its own item.
- *RK8.* The search parse equals `_parse_document` for every input (a test); `_parse_document` is unchanged.
- *Not changed.* `oracle_service.py`, `proactive.py`, `routers/records.py`, `dm_targeted_lookup.py`, the HXI, the other six stoplists.
- *Residual.* Recorded limits L1 to L16 of the contract.
- *Reversal.* Revert the BF-952 commits.

### BF-950 -- An oracle_query result is aged by its own write time, not by its retrieval (2026-11-05, #1742)
```

Then regenerate the ledger (`python -P scripts/gen_ad_ledger.py`) on the real base and stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` as written. Never merge them by hand. **Not updated:** `docs/development/roadmap.md`.

## 9. What this does NOT change, and what is not built

Not changed: `oracle_service.py` (the `/10`, fusion, `query`, `query_formatted`), `proactive.py`, `routers/records.py`, `dm_targeted_lookup.py`, `ui/`, `semantic.py`, `record_is_readable`, `_parse_document`, the cap of 20, config, `EventType`, persisted shapes, the default executor. No method is added to `RecordsStore`; its SRP row (`architecture-baseline.yaml:751-757`) is keyed by trigger.

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
- Every "Line" text occurs exactly once in `records_store.py` on M2's head.
- Equivalent mutants, not rowed (B1 and B2 cover the cost):
  - deleting `if not terms: return []`;
  - `written is None` → `False`;
  - the RKS-20 line → `if False:` (the check only saves work);
  - `_SEARCH_YAML_LOADER` → `yaml.SafeLoader`;
  - deleting the `safe_load` retry in `_search_document` (no known input separates the two loaders, L16).

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
| RKS-21 | records_store.py | `            return frontmatter, parts[2].strip()` | `            return frontmatter, parts[2]` | the search parse departs from the store's | `test_search_reads_a_document_as_the_store_reads_it` |
| RKS-22 | records_store.py | `                frontmatter = yaml.load(parts[1], Loader=_SEARCH_YAML_LOADER) or {}` | `                frontmatter = yaml.load(parts[1], Loader=_SEARCH_YAML_LOADER)` | empty frontmatter reads as `None` and the record is withheld | `test_search_reads_a_document_as_the_store_reads_it` |

## 11. Recorded limits

- **L1.** Each call still reads and parses every file under the walk (RK3). The cost is bounded by B1, not removed. An index or cache is N1.
- **L2.** A seventh stoplist, English only (N2).
- **L3.** A record found only by keyword still reaches the Oracle at ≤ 0.1 (N3; AD-1358).
- **L4.** `\w` is Unicode, but there is no non-English stoplist.
- **L5.** `record_write_time` lives in `cognitive/provenance.py`, so it needs one allowlist entry (RK6). Moving it is deferred.
- **L6.** BM25 length normalisation (`_SEARCH_BM25_B`) is not pinned by a mutant.
- **L7.** The date decides only after coverage and relevance tie exactly.
- **L8.** The path is not scored, as on the base.
- **L9.** A file with non-mapping frontmatter is invisible to search. On the base it made every matching search raise.
- **L10.** Repeated query words add no weight.
- **L11.** Negations are stopwords.
- **L12.** `test_bf949…:161`'s premise rests on V-BF949. A change to the field set, the weights or the length measure must recheck it.
- **L13.** A cancelled caller cannot stop its worker thread. The walk finishes and its result is dropped.
- **L14.** Searches share the loop's default executor with the other `to_thread` users (21 `src` files). If contention is observed, a dedicated executor is the fallback design, following the precedent at `audio/tts/resident.py:20`.
- **L15.** Without libyaml, the search parse falls back to PyYAML. A call is then slower than B1 but still off the loop.
- **L16.** The `safe_load` retry for a frontmatter that only PyYAML accepts is not pinned by a test. No such input is known.

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
6. Nothing raises on hand-edited frontmatter: a list or scalar frontmatter; a list or numeric `topic` or `tags`; a `date`, `datetime`, unparsable or missing `updated`.
7. Ties after coverage and relevance go to the newer `record_write_time`, undated records last, then path.
8. `_search_records` reads files only: no `self`, no shared mutable state, no write. `search` awaits it through `asyncio.to_thread` (T14).
9. `_search_document` equals `_parse_document` for every T13 input, and `_parse_document` is byte-identical to the base.
10. No caller file changes; `oracle_service.py:1074` and AD-1141's floor are unchanged.
11. The bf949 edit keeps the test's purpose and carries an inline BF-952 reason. `:161` is untouched and holds (V-BF949).
12. The allowlist entry is exactly `("knowledge/records_store.py", "probos.cognitive.provenance")`, with a justification.
13. Every new docstring, comment and test docstring is true of the head, and each "on the base" claim matches §6.

## 15. Acceptance criteria

1. A conversational query made mostly of stopwords does not match every record, and the record holding its rare terms leads (T1).
2. `i`, `a` and `to` never match as substrings (T2).
3. Equal scores are ordered by the newer `updated` (T3).
4. `tests/test_records_store.py` and `tests/test_ad725_dm_targeted_lookup.py` pass unchanged; `test_bf949…:245` is updated with its reason.
5. The game record leads through the real Oracle (T9), and the live copy (§16) puts the game records in the top 3 for `tictactoe Captain Ezri` and `can you check our tictactoe games`.
6. B1 and B2 hold on the synthetic corpus, and a search runs off the event loop (T14).
7. Every §10 mutant is killed; G1 to G3 and the §13 checks pass; the broad gate's receipt is green.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Orchestrator steps after the build (never a Builder step)

The Builder must not read `%LOCALAPPDATA%\ProbOS` or `d:\ProbOS\data`.

1. **B1 and B2** on the synthetic corpus, on M2's head, before the Diff Reviewer (§4). Report the six medians (base and candidate × three queries), the maximum ticker overshoot and `yaml.__with_libyaml__`. Failure is a hard stop that comes back to the Architect.
2. **Live copy, after the broad gate.**
   - `git clone` the live records repository into a new, empty temporary directory. It is read-only toward the source, never written back, and deleted afterwards.
   - Open `RecordsStore(RecordsConfig(repo_path=<clone>, auto_commit=False))` and call `search(q, scope="ship", reader_id="captain")` three times each for `Hello Ezri`, the Captain's question, `good game`, `tictactoe Captain Ezri` and `can you check our tictactoe games`. Run the same B2 ticker during one call.
   - Report only: results returned (cap 20); the rank of each `recreation/games/tictactoe/` record, or "not in top 20"; the median per call; the maximum overshoot; the record count. No record text, other paths or frontmatter.
   - Record the result on #1751. If a game record misses the top 3 for either named query, or B2 fails on the live copy, return to the Architect before closing.

## For the Captain

None. The change is reversible, keeps every caller's contract, strengthens privacy (RK3), and makes the loop more responsive than the base. The live-copy read in §16 is the step #1751's own acceptance names, done read-only on a clone.
