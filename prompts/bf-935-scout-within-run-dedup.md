# BF-935 (#1674): A Scout run lists each repository once, however many of its six topic searches return it

**Drafted by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge was logged out), 2026-11-11
**Revised by:** `Architect` (the same fallback), 2026-11-11, r2: after the orchestrator's oracle found that G2 as r1 wrote it fails (consult `consult-bf935-a1`; the decision is in `answer-bf935-a1.txt`).
**What changed in r2.** One defect, found by the oracle, and not BF-935's own: `tests/test_bf214_scout_seen_deferral.py` replaces `ScoutAgent._data_dir` on the class in three tests (`type(agent)._data_dir = property(...)`; lines 79, 112 and 138 of the base) and nothing restores it, so every `ScoutAgent` built later in the same process reads the last test's `tmp_path`. Measured by the orchestrator: G2 as r1 wrote it fails 3 existing cases (`tests/test_quality_hardening.py::TestScoutDataDirectory`; the same 3 fail on the base without BF-935), and the new file fails 6 of its 16 cases when it runs after bf214, as it does in suite order (r1's G2 listed it first, which hid that). r2: (1) M1 also carries **P1-1 to P1-3**: the three tests install the property with `monkeypatch.setattr`, which restores it at teardown (test-only; no assertion and no product line changes; measured: bf214 then the new file 26 passed, G2 306 passed with the new file first or last); (2) G2 lists the new file last, states its total (306 = 290 + 16) and gains a third command, the leak's reproduction; (3) D6 records the choice, and sections 2, 5, 7.3 (the tracker text), 8, 9 (the prose under the table), 10 (L8), 11, 12, 13 and 14 name the fix; (4) the base is now `fe488971`. N1-1, P2-1 to P2-7, N2-1 and the tables of sections 6 and 9 are as in r1.
**Amended by:** `Architect` (the same fallback), 2026-11-11, A1: after review round 1 of the candidate (NOT READY: one code finding, F1, and two errors in this text, F2 and F3).
**What changed in A1.** (1) F1, which predates BF-935 and destroys the record it adds: the intent `scout_report` (`/scout report`, and the agent's intent descriptor, which natural-language routing reads) asked the model about the saved report and ran its answer through the classify, store and notify chain, so showing a report rewrote or replaced the day's file, notified again and marked as seen the names an earlier search had left pending (D7, section 15). A1 adds `ScoutAgent.decide`, which answers that intent from the saved report with no model call, a guard at the head of `act`, which returns that text without the chain, and a second new test file of 8 cases (`tests/test_bf935_scout_report_display.py`); G2 now totals 314 and section 15.3 adds the gate GA1. (2) F2: L6 said the file's `duplicate_listings` is the last run's; it is that of the last run that wrote the file. (3) F3: L8 said whole files go to workers in collection order; they do not. M0, G2, L6, L8 and the first acceptance bullet are corrected in place; section 15 records A1 and enumerates by command the other sentences checked.
**Amended by:** `Architect` (the same fallback), 2026-11-11, A2: after review round 2 of the candidate (NOT READY: one code finding, F4, and one error in this text, F5).
**What changed in A2.** (1) F4, which the search path had before BF-935 and A1 made reach the report path: `cmd_scout` printed the agent's result and its failure message through a Rich console with markup on, so an unmatched closing tag in a summary raised `MarkupError` and the score tag of every finding was dropped (D8, section 16). A2 prints both with markup off; 8 more cases in `tests/test_bf935_scout_report_display.py` (16 in all) run the real command over a real Rich console. From A2 the totals of A1's paragraph above are 16 cases in that file, GA1 16 and G2 322. (2) F5: the `decide` override census of section 15.7 gave counts that no revision reproduces and called two mixin classes subclasses; it now names the revision and the commands and gives the measured counts (15.7 and 16.7). Estimated tests, M0, G2, GA1, 15.3, 15.4 and the first acceptance bullets are corrected in place; L11 is recorded.
**Amended by:** `Architect` (the same fallback), 2026-11-11, A3: after review round 3 of the candidate (NOT READY: one finding, F6, in the test helper A2 added) and the round-three brake (decision: continue).
**What changed in A3.** (1) F6, a false sentence of A2's test helper: `_console` said that nothing wraps and that the colour codes are a terminal's whatever the environment sets, but under `TERM=dumb` the colour console was 80 columns wide, because `Console.size` takes its dumb-terminal fallback unless both dimensions are given. A3 gives `Console` all eight settings that Rich reads from the environment or the platform (two dimensions, the terminal, the notebook, the interactive flag, `NO_COLOR`, the colour system, the Windows console), which also closes a second hole of the same sentence (in a notebook kernel all output went to the notebook, not to the buffer), and adds one parametrized case of 8 that defines its surroundings in full and runs the real command in each (D9, section 17). Test-only: no `src` line changes. From A3 the totals of A2's paragraph above are 24 cases in that file, GA1 24 and G2 330; Tier, Estimated tests, M0, G2, GA1, 15.3, 15.4, the acceptance bullets and the sentence of 16.4 that described the console are corrected in place, rows 18 and 19 of 16.5 are corrected (the new case kills them too), and L12 is recorded.
**Status:** ready to build on `origin/main` `fe488971` (the merge of BF-940 slice 4, PR #1783, merged 2026-11-12T00:12:22Z). **Oracle:** r1 was checked by an in-memory script without pytest (section 11). The orchestrator then built it by tool on `8a24dfba` (that PR's head; the four files below have the same blobs on `fe488971`) and ran pytest: G1 6 passed and 10 xfailed at M1, `--runxfail` fails the 10 at the asserts section 6 names, the 8 mutants of section 9 fail the cases it lists (4, 1, 6, 6, 1, 1, 4, 1), the architecture check is clean, M0 is 290. G2 as r1 wrote it failed 3 existing tests: the defect r2 repairs.
**Base blobs (`fe488971`; read from GitHub on 2026-11-11, equal to those of `8a24dfba`):** `src/probos/cognitive/scout.py` `9b2cc9bcd0d8d334cb33c0228516abd70e3c97d6`, `tests/test_bf214_scout_seen_deferral.py` `8c3b29dbb44308d5f39aefddec33cb2e22fe8469`, `PROGRESS.md` `a10956172ac3cacc83b7ccf1dc5260aa08781705`, `DECISIONS.md` `a07c172b512ce69dc88f5819575b56de3a5c1689`.
**Dependencies:** none in code; before AD-1354 (#1672) and any Scout baseline, as the crew asked on #1674. **Tier:** STANDARD for M1 to M3, A1, A2 and A3. **Estimated tests:** two new files: 16 cases (6 pass, 10 xfail at M1) and, from A1, A2 and A3, 24 cases (A1's 8: 6 fail without A1's code, 2 pass either way; A2's 8: all fail without A2's change to `cmd_scout`; A3's 8: all fail with the console as A2 left it); three existing tests edited (P1-1 to P1-3), none added. **BF number:** BF-935, held by #1674 (section 11); the bf214 fix carries no number of its own (D6), nor does the `scout_report` repair of A1 (D7), nor the console repair of A2 (D8), nor the display-test repair of A3 (D9). To be committed as `prompts/bf-935-scout-within-run-dedup.md`.

**Which text describes the head.** Before building: `git rev-parse HEAD:<path>` prints the four blobs above for `scout.py`, the bf214 test, `PROGRESS.md` and `DECISIONS.md` (the last two already hold BF-940 slice 4's entries, which P3-2 anchors on), and the new test file does not exist. Every SEARCH must occur exactly once and starts at the start of a line (leading spaces included), else a hard stop for the Architect. Working copies are CRLF, SEARCH text is LF. Where prose and a block differ, the block wins. Apply the pairs with the `edit` tool one at a time, whole block, in label order.

## 1. Problem

1. **The loop.** `ScoutAgent.perceive` (`scout.py:432`) runs six searches (`:461-468`), loads `seen` from earlier runs (`:470`; `_load_seen` `:206`) and appends each result to `new_repos` unless its name is in `seen` (`:473-489`). `new_repos` is not read inside the loop (`grep -n new_repos scout.py`: `:471` creates it, `:479` appends, the first read is `:493`), so a repository that k searches return is appended k times. `_pending_seen_repos` (`:493`), the prompt `Classify these {len(new_repos)} repositories` with one `REPO:` block per entry (`:499-514`) and `_repo_metadata` (`:516`; a dict comprehension, the last listing wins) follow from it.
2. **How it came about.** Before BF-214 the loop wrote `seen[full_name] = now` ahead of the append, so a second listing in a run was a `seen` hit (`git log -S'seen[full_name] = datetime.now(timezone.utc).isoformat()' -- scout.py` lists two commits: `333f1a2b`, 2026-03-22, adds the line and `f10369d0` removes it; the six searches were there from `0c6da601`, 2026-03-22). BF-214 (`f10369d0`, 2026-04-20) deferred the marking to `act` and deleted that line; the loop at HEAD has no in-run check (`:473-489`).
3. **What each consumer does with a repository listed k times:**

| Consumer | Today | After M2 |
|---|---|---|
| Prompt (`:499-514`) | k `REPO:` blocks; N counts them | one block; N counts repositories; a repository listed once: the same bytes |
| `_pending_seen_repos`, `_scout_step_parse_and_mark_seen` (`:233`) | k names; the log counts k | one name |
| `_repo_metadata`, `_scout_step_enrich_and_filter` (`:261`) | the last listing's `language`, `license`, `topics` | the first listing's, plus `matched_topics` |
| Findings, `total_classified` (`:274`), report JSON (`:277`), digest, Discord, `/scout` | one per block the model answers (its answer to a repeated block is not specified) | one per repository; the report gains `duplicate_listings` and, per finding, `matched_topics` |
| Notifications (`:296`) | one per finding with composite >= 4 | one |
| `_load_latest_report` (`:587`) | `ScoutFinding(**f)` | accepts the new key (a field is added); an older file loads as before |

4. **How far back.** The in-run repeat was possible from `f10369d0` (2026-04-20) until this fix, not before. The orchestrator's probe (outside the repository; quoted as theirs, not run by the Architect) read the vessel's persisted report files (2026-04-16 to 2026-11-04): no repository listed twice in any file (its selftest finds a planted repeat; the counts it printed are the vessel's data and are not recorded in this repository). **It shows** that no persisted finding is a repeat. **It does not show** what the prompt held (not persisted), a repeat skipped or scored below 3 (only composite >= 3 is persisted), or whether a repeated block moved a score. So: runs since 2026-04-20 could have been fed repeats, no persisted score is a repeat, and whether any was influenced is not recoverable. After M2 each report carries `duplicate_listings` (0 included); a baseline should start at the first report that has it. **What else could be measured, and by whom** (not the crew: nothing below the report layer is theirs): the Captain or the orchestrator, the Scout channel's digests and the notification queue for the days in question; the free text of the persisted report files for a repeat note ("listed twice", the phrase #1672 quotes), a proxy for runs where the model saw one; the overlap rate of the six searches (a read-only replay against the public search API; I ran it once for shape and give no figure).

## 2. Solution

`perceive` keeps one entry per `full_name` in a local mapping filled after the `seen` check (first listing kept, first-listed order), each with `matched_topics`, the topics of the searches that returned it in search order. `new_repos` is the mapping's values, so the pending names, the prompt and `_repo_metadata` follow. The six searches become `(topic, min_stars)` pairs; the query strings are unchanged. `listings` (the results not skipped as seen) minus `len(new_repos)` is set on the agent as `_duplicate_listings`, logged once per run and written by `_scout_step_persist_report` as `duplicate_listings`. `ScoutFinding` gains `matched_topics`, which `_scout_step_enrich_and_filter` fills from the entry. The prompt text, `seen` and BF-214's deferral are untouched. The three tests of `tests/test_bf214_scout_seen_deferral.py` that replace `ScoutAgent._data_dir` on the class now restore it (D6).

## 3. Decisions

**D1. The deduplication** (correctness, compatibility, fit).

| # | Option | Judgement |
|---|---|---|
| 1 | A local mapping keyed by the exact `full_name`, filled after the `seen` check: first listing kept, first-listed order (chosen) | The key `seen`, the pending names, `_repo_metadata` and the model's `REPO:` echo already use. In my one run of the six searches a repository returned by several carried the identical string each time; `full_name` was a non-empty string, never ended `.git`, and no two ids differed only by case (section 11) |
| 2 | Lower-cased, `.git` stripped (#1672's suggestion) | A second rule beside an exact-name `seen`, for a variance the run did not show |
| 3 | The numeric `id` | Survives a rename; `seen`, the pending names and `_repo_metadata` are keyed by name, not by it (L3) |

**D2. An item with an empty or missing `full_name`.**

| # | Option | Judgement |
|---|---|---|
| 1 | Not special-cased: the empty name is one key, so such items merge into one entry (chosen; L2) | Today each is listed, and the empty name is marked seen after classification, as it still is. Every item I read carried a name, so no case is expected; a test would pin an accident |
| 2 | Skip them with a WARNING | Right if the API ever sent one; a changed model input for a case not observed |
| 3 | List each as today | A branch for an input no run showed |

**D3. The matching-topic record.**

| # | Option | Judgement |
|---|---|---|
| 1 | On the entry as `matched_topics` (topic names, search order, once each), copied by `enrich_and_filter` onto a new `ScoutFinding.matched_topics` so each persisted finding carries it; never in the prompt (chosen) | The crew's "keep the topic list" needs a trace that outlives the run (`_repo_metadata` is replaced every run); the finding is Sage's unit and AD-1354's (#1672 adds its field the same way). Distinct from `topics`, the repository's own list: a repository can carry a queried topic and not be returned by that search (the 30-result page, the star floor; seen in my run). The topic is the first item of each `(topic, min_stars)` pair, not parsed out of the query. First consumer: outside the merge in `perceive`, only the copy in `enrich_and_filter`; its readers are the report file (Sage's per-repository analysis) and AD-1354 when built |
| 2 | On the entry and `_repo_metadata` only | Nothing persists, and nothing reads it |
| 3 | A top-level report mapping `{name: [topics]}` | Old loaders ignore it, but it is a second place to join; option 1's revert exposure is bounded (L4) |
| 4 | In the prompt | Hands the model the "matched k searches" signal the crew warned reads as corroboration, and changes the input of every multi-match repository once a baseline exists |

**D4. The recorded duplicate count.** "Classify these N repositories" counts unique repositories by construction (the line is unchanged; N is `len(new_repos)`).

| # | Option | Judgement |
|---|---|---|
| 1 | The agent attribute `_duplicate_listings` (set each search run, before the nothing-new return), one INFO line per run (listings, repositories, searches, repeats), and `duplicate_listings` in the day's report, always written (chosen) | The count reaches a durable file; a report without the key predates the fix; `_load_latest_report` reads only `date` and `findings` |
| 2 | The INFO line only | Not durable; nothing for the chain to write |
| 3 | Listings, repositories and repeats all in the report | The identity checkable from the file alone, at three keys for a check T1 makes and the INFO line shows |

**D5. The tests.** Chosen: the real `ScoutAgent` with `_search_github` and `CognitiveAgent.perceive` replaced, data under `tmp_path`, plus one seam case through `act` and the real chain (one test crosses search, prompt, model text, chain, report, notifications and seen file; the guards pass on both trees). Rejected: extracting the loop into a function (a new surface, no seam); a source-text test of `perceive` (it cannot tell a required line from the shipped one).

**D6. The leak in `tests/test_bf214_scout_seen_deferral.py`** (correctness, scope, fit). Found by the oracle (see "What changed in r2"): three tests replace `ScoutAgent._data_dir` on the class and nothing restores it.

| # | Option | Judgement |
|---|---|---|
| 1 | Fix the leaker: the three tests take the `monkeypatch` fixture and install the property with `monkeypatch.setattr(type(agent), "_data_dir", property(lambda self: tmp_path))`, which pytest restores at teardown; in M1 (chosen) | The cause is in the leaking tests, and this is the idiom the new file already uses for `_search_github` and `CognitiveAgent.perceive`. It makes G2 hold as stated and closes the 3 `TestScoutDataDirectory` failures and the new file's 6 (measured by the orchestrator: bf214 then the new file 26 passed; G2 306 passed with the new file first or last). Tied to this BF: its own tests fail without it in suite order, and G2 cannot pass. Test-only: no product line and no assertion; the other seven tests of the file never read `_data_dir`, `_seen_file` or `_reports_dir` and never call `act` (section 11) |
| 2 | Restore the real property inside the new file's `_Scene` only | Hides the leak from the new file but leaves `TestScoutDataDirectory` and every later Scout test exposed, so G2 still fails 3. Not measured |
| 3 | Both | Option 2's code is then dead weight, and it would hide a future leak from the new file's guard cases without closing it for the others |
| 4 | Neither: list the new file first in G2, as r1 did by accident | The gate's order stops showing it, but the exposure of the new file and of `TestScoutDataDirectory` stays under `--dist=loadfile` (a worker that ran bf214 may receive either file later). Not an option |

No BF number of its own: one defect of one test file, found by this BF's gate and fixed in the commit that adds the tests that need it; the commit subject and the trackers name it. A suite-wide guard against a future leak is not added (L8).

## 4. Milestones and gates

| M | Blocks | Gate |
|---|---|---|
| M1 | N1-1, then P1-1 to P1-3 (the bf214 fix) | G1 |
| M2 | P2-1 to P2-7, then N2-1 (removing the marker) | G2 |
| M3 | P3-1, P3-2, ledger | G3 |

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. **M0:** on the head, record the collected count (`--collect-only -q`) of every existing file named in G2. Measured on `8a24dfba` (the same files on `fe488971`): 290 in all; per file `test_ad1346_admission_effect_census` 10, `test_ad1346_admission_file_write_census` 9, `test_ad1346_admission_service` 16, `test_ad398_crew_identity` 33, `test_ad632f_activation_triggers` 34, `test_ad647_process_chains` 8, `test_ad647b_chain_registry` 12, `test_ad648_post_capability_profiles` 14, `test_bf208_scout_duty_perceive` 5, `test_bf209_scout_chain_bypass` 4, `test_bf214_scout_seen_deferral` 10, `test_bf892_spawn_env_guard` 82, `test_bf925_guard_names` 14, `test_commands_knowledge` 7, `test_layer_boundaries` 3, `test_quality_hardening` 13, `test_scout` 16. The recorded M0 is binding; if it differs from this list the head moved: say so in the report, and expect G2's total to be M0's sum plus 40 (16 for the first new file and, from A1, A2 and A3, 24 for the second).

- **G1.** `PY -m pytest tests/test_bf935_scout_within_run_dedup.py -q -n 0 -p no:randomly`. **Expected: 6 passed** (the functions), **10 xfailed** (the class). The marker carries `raises=AssertionError, strict=True`: any other exception, or an XPASS, is a FAIL; any other count is a hard stop. Then once with `--runxfail`: each of the 10 must fail at the `assert` section 6 names, never at a premise line. P1-1 to P1-3 do not change G1 (it runs the new file alone).
- **G2.** (1) `PY -m pytest tests/test_scout.py tests/test_bf208_scout_duty_perceive.py tests/test_bf209_scout_chain_bypass.py tests/test_bf214_scout_seen_deferral.py tests/test_ad647_process_chains.py tests/test_ad647b_chain_registry.py tests/test_quality_hardening.py tests/test_ad398_crew_identity.py tests/test_ad632f_activation_triggers.py tests/test_ad648_post_capability_profiles.py tests/test_commands_knowledge.py tests/test_bf892_spawn_env_guard.py tests/test_ad1346_admission_service.py tests/test_ad1346_admission_effect_census.py tests/test_ad1346_admission_file_write_census.py tests/test_bf925_guard_names.py tests/test_layer_boundaries.py tests/test_bf935_scout_within_run_dedup.py tests/test_bf935_scout_report_display.py -q -n 0 -p no:randomly` (the 11 files that `git grep -l -E "_pending_seen_repos|_repo_metadata|ScoutAgent|scout_search|_search_github|SCOUT_REPORT_CHAIN" -- tests` finds on the base; `/scout`; the scans that read `scout.py` by syntax and the layer test: section 11; and the two new files LAST, so that in this serial run (`-n 0`: files run in command-line order) they run after bf214, the order in which the leak of L8 showed; under xdist the order is the scheduler's, not the command line's: L8). (2) `PY -P scripts/check_architecture_principles.py --check`. (3) The leak's reproduction: `PY -m pytest tests/test_bf214_scout_seen_deferral.py tests/test_bf935_scout_within_run_dedup.py -q -n 0 -p no:randomly`. **Expected:** (1) **330 passed**, 0 failed, 0 skipped, 0 xfailed (314 at A1, 322 at A2): the new files 16 and 24 and the 17 existing files 290, their collected counts equal to M0; (2) clean; (3) **26 passed** (10 + 16; without P1-1 to P1-3 it prints `6 failed, 20 passed`).
- **G3.** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- **Harness rule.** No source change made to pass a test, no skip, no loosened assertion. P1-1 to P1-3 are the one edit of an existing test and change how three tests install a property, not what they assert. A failing case of the new file at G2 (any line), or any existing test failing, goes back to the Architect. The broad gate runs once, in the main session, with `--receipt`.

## 5. Commit messages

- **M1:** `BF-935 M1: tests for a Scout run listing each repository once, xfail until built; BF-214 act tests restore _data_dir (#1674)`; its body: `Three tests of tests/test_bf214_scout_seen_deferral.py replaced ScoutAgent._data_dir on the class and never restored it; they now use monkeypatch.setattr. Test-only; no assertion changed.`
- **M2:** `BF-935 M2: a Scout run lists each repository once, with the topic searches that returned it and a recorded repeat count (#1674)`
- **M3:** `BF-935 M3: trackers and ledger (#1674)`; its body ends with the line `Closes #1674.`

## 6. Tests (`tests/test_bf935_scout_within_run_dedup.py`)

| Id | Cases | Covers | xfail until |
|---|---|---|---|
| G | 6 | Functions that pass on both trees: the six query strings, star floors and one prompt block as before; no repeat: prompt, pending names, entries as before; a seen repository skipped and nothing marked seen by `perceive` (BF-214); nothing new (2); an older report loads | none |
| T1 | 5 | Class: each repository once with its topics, repeats counted: overlap across two searches, three searches, no overlap, twice in one search, a seen repository not counted | M2 |
| T2 | 1 | The first listing is kept; the prompt is one block of the old text | M2 |
| T3 | 1 | The count belongs to the last search, a nothing-new run included | M2 |
| T4 | 1 | One INFO line per run carries the counts | M2 |
| T5 | 1 | Seam: `perceive`, a model text with one report per block shown, `act`, the real chain: report, digest, notifications, seen file | M2 |
| T6 | 1 | `_load_latest_report` reads a report with the new keys | M2 |

**How each xfail case fails on the base.** T1 at `assert getattr(scene.agent, "_duplicate_listings", None) == repeats` (None); the table's own arithmetic before it passes on both trees. T2 at the first `assert` (two blocks). T3 at `== 1` (None). T4 at the list comparison (no record). T5 at the first `assert` (a repeated repository in the findings). T6 at `assert digest is not None and Y in digest` (the loader raises, answers None).

## 7. The contract

### 7.1 M1

**N1-1.** New file `tests/test_bf935_scout_within_run_dedup.py`:

```python
"""BF-935 (#1674): a Scout run lists each repository once, however many of its topic searches return it.

The real ScoutAgent runs ``perceive`` with ``_search_github`` and ``CognitiveAgent.perceive`` replaced (canned results per topic; no
network) and a runtime double whose data directory is under ``tmp_path``. The seam case runs ``act`` over a classification text built
as a model builds it (one report per REPO block it was shown) through the real SCOUT_REPORT_CHAIN. The class holds the cases the
unfixed tree fails; the functions before it pass on both. No BF-935 name is imported.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.process_chains import ProcessChainRegistry
from probos.cognitive.scout import SCOUT_REPORT_CHAIN, ScoutAgent

TOPICS = {"ai-agents": 50, "llm-agents": 50, "multi-agent": 50, "agent-framework": 50, "ai-coding": 100, "code-generation": 100}
X, Y, Z = "a/x", "b/y", "c/z"
FINDING = {"repo_full_name": X, "stars": 1, "url": "u", "classification": "absorb", "relevance": 5, "credibility": 4,
           "reliability": 4, "summary": "s", "insight": "i"}
CASES = {  # what each search returns | already seen | listed once, first-listed order | repeat listings | topics that returned each
    "overlap": ({"ai-agents": [X, Y], "llm-agents": [Y, Z]}, [], [X, Y, Z], 1,
                {X: ["ai-agents"], Y: ["ai-agents", "llm-agents"], Z: ["llm-agents"]}),
    "three-searches": ({"ai-agents": [Y], "ai-coding": [Y, X], "code-generation": [Y]}, [], [Y, X], 2,
                       {Y: ["ai-agents", "ai-coding", "code-generation"], X: ["ai-coding"]}),
    "no-overlap": ({"ai-agents": [X], "llm-agents": [Y]}, [], [X, Y], 0, {X: ["ai-agents"], Y: ["llm-agents"]}),
    "twice-in-one-search": ({"ai-agents": [X, X]}, [], [X], 1, {X: ["ai-agents"]}),
    "seen-is-not-counted": ({"ai-agents": [X, Y], "llm-agents": [Y, Z]}, [Y], [X, Z], 0, {X: ["ai-agents"], Z: ["llm-agents"]}),
}


def _item(name: str, **over: object) -> dict:
    """One search result as the search API shapes it."""
    return {"full_name": name, "description": f"about {name}", "stargazers_count": 100, "language": "Python",
            "license": {"spdx_id": "MIT"}, "topics": ["ai-agents", "rag"], "html_url": f"https://github.com/{name}", **over}


def _block(name: str, description: str = "") -> str:
    """The prompt block of ``_item(name)``, written out here and not taken from the code."""
    return (f"REPO: {name}\nDESC: {description or 'about ' + name}\nSTARS: 100\nLANG: Python\nLICENSE: MIT\n"
            f"TOPICS: ai-agents, rag\nURL: https://github.com/{name}\n")


def _repos(context: str) -> list[str]:
    return [line[6:] for line in context.splitlines() if line.startswith("REPO: ")]


def _answer(context: str) -> str:
    """What a model that classifies every block it is shown answers: one absorb report (composite 4.5) per REPO block."""
    return "".join(f"===SCOUT_REPORT===\nREPO: {n}\nSTARS: 100\nURL: https://github.com/{n}\nCLASS: absorb\nRELEVANCE: 5\n"
                   "CREDIBILITY: 4\nRELIABILITY: 4\nSUMMARY: s\nINSIGHT: i\n===END===\n" for n in _repos(context))


class _Scene:
    """A real ScoutAgent over a temporary data directory; ``found`` maps a topic to the items its search returns."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.data = tmp_path / "data"
        self.data.mkdir()
        self.found: dict[str, list[dict]] = {}
        self.calls: list[tuple[str, int]] = []
        self.notified: list[str] = []
        registry = ProcessChainRegistry()
        registry.register_chain(SCOUT_REPORT_CHAIN)
        queue = SimpleNamespace(notify=lambda **kw: self.notified.append(kw["title"]))
        runtime = SimpleNamespace(_data_dir=self.data, process_chain_registry=registry, notification_queue=queue)
        self.agent = ScoutAgent(agent_id="scout-935", runtime=runtime)

        async def search(_agent: ScoutAgent, query: str, min_stars: int) -> list[dict]:
            self.calls.append((query, min_stars))
            return self.found.get(query.split(" ", 1)[0].removeprefix("topic:"), [])

        monkeypatch.setattr(ScoutAgent, "_search_github", search)
        monkeypatch.setattr(CognitiveAgent, "perceive",
                            AsyncMock(side_effect=lambda _i: {"intent": "scout_search", "params": {}, "context": ""}))

    def seen(self, *names: str) -> None:
        stamp = datetime.now(timezone.utc).isoformat()
        (self.data / "scout_seen.json").write_text(json.dumps({n: stamp for n in names}), encoding="utf-8")

    def report(self, day: str, finding: dict, **top: object) -> None:
        (self.data / "scout_reports").mkdir(exist_ok=True)
        body = {"date": day, "total_classified": 1, "total_relevant": 1, **top, "findings": [finding]}
        (self.data / "scout_reports" / f"{day}.json").write_text(json.dumps(body), encoding="utf-8")

    async def perceive(self) -> dict:
        return await self.agent.perceive({"intent": "scout_search"})


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Scene:
    return _Scene(tmp_path, monkeypatch)


async def test_the_searches_and_one_prompt_block_are_as_before(scene):
    scene.found = {"ai-agents": [_item(X)]}
    result = await scene.perceive()
    queries = [(re.sub(r"\d{4}-\d{2}-\d{2}$", "DATE", q), stars) for q, stars in scene.calls]
    assert queries == [(f"topic:{t} pushed:>DATE", stars) for t, stars in TOPICS.items()]
    assert result["context"] == "Classify these 1 repositories:\n\n" + _block(X)


async def test_without_a_repeat_the_prompt_the_pending_names_and_the_entries_are_as_before(scene):
    scene.found = {"ai-agents": [_item(X)], "llm-agents": [_item(Y)], "multi-agent": [_item(Z)]}
    result = await scene.perceive()
    assert result["context"] == "Classify these 3 repositories:\n\n" + "\n---\n".join(_block(n) for n in (X, Y, Z))
    assert scene.agent._pending_seen_repos == [X, Y, Z]
    old = {n: {"full_name": n, "description": f"about {n}", "stars": 100, "created_at": "", "updated_at": "", "language": "Python",
               "license": "MIT", "topics": ["ai-agents", "rag"], "url": f"https://github.com/{n}"} for n in (X, Y, Z)}
    assert {n: {k: v for k, v in m.items() if k != "matched_topics"} for n, m in scene.agent._repo_metadata.items()} == old


async def test_a_seen_repository_is_skipped_and_perceive_marks_nothing_seen(scene):
    scene.found = {"ai-agents": [_item(X), _item(Y)], "llm-agents": [_item(Z)]}
    scene.seen(Y)
    before = (scene.data / "scout_seen.json").read_bytes()
    result = await scene.perceive()
    assert _repos(result["context"]) == [X, Z] and scene.agent._pending_seen_repos == [X, Z]
    assert (scene.data / "scout_seen.json").read_bytes() == before


@pytest.mark.parametrize("seen", [[], [X]])
async def test_when_nothing_is_new_the_answer_is_as_before(scene, seen):
    scene.found = {"ai-agents": [_item(X)], "llm-agents": [_item(X)]} if seen else {}
    scene.seen(*seen)
    result = await scene.perceive()
    assert result["context"] == "No new repositories found since last scan." and scene.agent._pending_seen_repos == []


def test_an_older_report_still_loads(scene):
    scene.report("2026-01-01", FINDING)
    assert X in (scene.agent._load_latest_report() or "")


class TestARepeatIsMerged:
    # BF-935 M1: xfail until M2 builds it (M2 removes this line and the next).
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-935 M2 builds it")

    @pytest.mark.parametrize("case", CASES)
    async def test_each_repository_is_listed_once_with_its_topics_and_the_repeats_are_counted(self, scene, case):
        found, seen, listed, repeats, topics = CASES[case]
        assert sum(n not in seen for names in found.values() for n in names) - len(listed) == repeats, "premise: the table"
        scene.found = {t: [_item(n) for n in names] for t, names in found.items()}
        scene.seen(*seen)
        result = await scene.perceive()
        assert getattr(scene.agent, "_duplicate_listings", None) == repeats
        assert result["context"].startswith(f"Classify these {len(listed)} repositories:\n\n")
        assert _repos(result["context"]) == listed and scene.agent._pending_seen_repos == listed
        assert {n: m.get("matched_topics") for n, m in scene.agent._repo_metadata.items()} == topics

    async def test_the_first_listing_is_kept_and_the_prompt_is_one_block_of_the_old_text(self, scene):
        scene.found = {"ai-agents": [_item(Y, description="first listing")],
                       "llm-agents": [_item(Y, description="later listing", stargazers_count=900, topics=["other"])]}
        result = await scene.perceive()
        assert result["context"] == "Classify these 1 repositories:\n\n" + _block(Y, "first listing")
        assert scene.agent._repo_metadata[Y]["description"] == "first listing" and scene.agent._repo_metadata[Y]["stars"] == 100

    async def test_the_count_belongs_to_the_last_search_alone(self, scene):
        scene.found = {"ai-agents": [_item(X)], "llm-agents": [_item(X)]}
        await scene.perceive()
        assert getattr(scene.agent, "_duplicate_listings", None) == 1
        scene.seen(X)  # the next search finds nothing new, so perceive returns early
        result = await scene.perceive()
        assert result["context"] == "No new repositories found since last scan." and scene.agent._duplicate_listings == 0

    async def test_one_line_per_search_run_records_the_counts(self, scene, caplog):
        scene.found = {"ai-agents": [_item(X), _item(Y)], "llm-agents": [_item(Y), _item(Z)]}
        with caplog.at_level(logging.INFO, logger="probos.cognitive.scout"):
            await scene.perceive()
        assert [(r.levelno, r.args) for r in caplog.records if r.name == "probos.cognitive.scout"] == [(logging.INFO, (4, 3, 6, 1))]

    async def test_the_chain_scores_and_notifies_each_repository_once_and_records_the_repeats(self, scene):
        scene.found = {"ai-agents": [_item(X), _item(Y)], "llm-agents": [_item(Y), _item(Z)], "ai-coding": [_item(Y)]}
        context = (await scene.perceive())["context"]
        decision = {"intent": "scout_search", "duty": {"duty_id": "scout_report"}, "llm_output": _answer(context)}
        out = await scene.agent.act(decision)
        report = json.loads(next((scene.data / "scout_reports").glob("*.json")).read_text(encoding="utf-8"))
        assert sorted(f["repo_full_name"] for f in report["findings"]) == [X, Y, Z] and report["total_classified"] == 3
        assert report.get("duplicate_listings") == 2
        assert {f["repo_full_name"]: f.get("matched_topics") for f in report["findings"]} == {
            X: ["ai-agents"], Y: ["ai-agents", "llm-agents", "ai-coding"], Z: ["llm-agents"]}
        assert sorted(scene.notified) == [f"Scout: {n}" for n in (X, Y, Z)]
        assert out["success"] is True and out["result"].count(f"- **{Y}**") == 1 and "3 findings" in out["result"]
        assert sorted(json.loads((scene.data / "scout_seen.json").read_text(encoding="utf-8"))) == [X, Y, Z]

    def test_a_report_with_the_new_keys_loads(self, scene):
        scene.report("2026-01-02", {**FINDING, "repo_full_name": Y, "matched_topics": ["ai-agents", "llm-agents"]}, duplicate_listings=1)
        digest = scene.agent._load_latest_report()
        assert digest is not None and Y in digest
```

**P1-1.** `tests/test_bf214_scout_seen_deferral.py` (M1; the leak of L8: this test replaces `ScoutAgent._data_dir` on the class and nothing restores it. Each of the three pairs is the head of one test through its `_data_dir` line; the REPLACE adds the `monkeypatch` parameter and installs the same property through it, which pytest restores at teardown. After P1-1 to P1-3 the file's blob is `7902760692b1a5a48a6b11b71605914cf1ea4d8a` and its numstat is 6 added, 6 removed)
SEARCH:
```
    def test_act_marks_seen_on_success(self, tmp_path):
        """act() marks repos as seen when classification produces valid blocks."""
        agent = ScoutAgent.__new__(ScoutAgent)
        agent._pending_seen_repos = ["cool/project", "another/repo"]
        agent._repo_metadata = {}
        agent._last_findings = []
        agent._runtime = None

        # Override _data_dir so _seen_file and _reports_dir derive from tmp_path
        type(agent)._data_dir = property(lambda self: tmp_path)
```
REPLACE:
```
    def test_act_marks_seen_on_success(self, tmp_path, monkeypatch):
        """act() marks repos as seen when classification produces valid blocks."""
        agent = ScoutAgent.__new__(ScoutAgent)
        agent._pending_seen_repos = ["cool/project", "another/repo"]
        agent._repo_metadata = {}
        agent._last_findings = []
        agent._runtime = None

        # Override _data_dir so _seen_file and _reports_dir derive from tmp_path
        monkeypatch.setattr(type(agent), "_data_dir", property(lambda self: tmp_path))
```

**P1-2.** `tests/test_bf214_scout_seen_deferral.py` (the second test of the same change)
SEARCH:
```
    def test_act_does_not_mark_seen_on_failure(self, tmp_path):
        """act() does NOT mark repos as seen when LLM output is garbage."""
        agent = ScoutAgent.__new__(ScoutAgent)
        agent._pending_seen_repos = ["cool/project", "another/repo"]
        agent._repo_metadata = {}
        agent._last_findings = []
        agent._runtime = None
        type(agent)._data_dir = property(lambda self: tmp_path)
```
REPLACE:
```
    def test_act_does_not_mark_seen_on_failure(self, tmp_path, monkeypatch):
        """act() does NOT mark repos as seen when LLM output is garbage."""
        agent = ScoutAgent.__new__(ScoutAgent)
        agent._pending_seen_repos = ["cool/project", "another/repo"]
        agent._repo_metadata = {}
        agent._last_findings = []
        agent._runtime = None
        monkeypatch.setattr(type(agent), "_data_dir", property(lambda self: tmp_path))
```

**P1-3.** `tests/test_bf214_scout_seen_deferral.py` (the third test of the same change)
SEARCH:
```
    def test_act_marks_seen_when_all_skip(self, tmp_path):
        """act() marks repos as seen when all are classified SKIP (valid response)."""
        agent = ScoutAgent.__new__(ScoutAgent)
        agent._pending_seen_repos = ["boring/project"]
        agent._repo_metadata = {}
        agent._last_findings = []
        agent._runtime = None
        type(agent)._data_dir = property(lambda self: tmp_path)
```
REPLACE:
```
    def test_act_marks_seen_when_all_skip(self, tmp_path, monkeypatch):
        """act() marks repos as seen when all are classified SKIP (valid response)."""
        agent = ScoutAgent.__new__(ScoutAgent)
        agent._pending_seen_repos = ["boring/project"]
        agent._repo_metadata = {}
        agent._last_findings = []
        agent._runtime = None
        monkeypatch.setattr(type(agent), "_data_dir", property(lambda self: tmp_path))
```

### 7.2 M2

**P2-1.** `src/probos/cognitive/scout.py`
SEARCH:
```
    topics: list[str] = field(default_factory=list)

    @property
    def composite_score(self) -> float:
```
REPLACE:
```
    topics: list[str] = field(default_factory=list)
    matched_topics: list[str] = field(default_factory=list)  # BF-935: the topic searches that returned this repository, in search order

    @property
    def composite_score(self) -> float:
```

**P2-2.** `src/probos/cognitive/scout.py`
SEARCH:
```
        f.license = meta.get("license", f.license)
        f.topics = meta.get("topics", f.topics)
```
REPLACE:
```
        f.license = meta.get("license", f.license)
        f.topics = meta.get("topics", f.topics)
        f.matched_topics = list(meta.get("matched_topics", f.matched_topics))
```

**P2-3.** `src/probos/cognitive/scout.py` (`getattr` with a default, as the module's other step readers do at `:241` and `:265`: the agents built with `__new__` in `test_ad647_process_chains.py:147-160` and `test_bf214_scout_seen_deferral.py` have no such attribute)
SEARCH:
```
        "total_relevant": len(filtered),
        "findings": [asdict(f) for f in filtered],
```
REPLACE:
```
        "total_relevant": len(filtered),
        # BF-935: always written; a report without this key predates the fix
        "duplicate_listings": getattr(agent, "_duplicate_listings", 0),
        "findings": [asdict(f) for f in filtered],
```

**P2-4.** `src/probos/cognitive/scout.py`
SEARCH:
```
        self._pending_seen_repos: list[str] = []  # BF-214: deferred seen marking
```
REPLACE:
```
        self._pending_seen_repos: list[str] = []  # BF-214: deferred seen marking
        self._duplicate_listings: int = 0  # BF-935: repeat listings merged in the last search
```

**P2-5.** `src/probos/cognitive/scout.py`
SEARCH:
```
        queries = [
            (f"topic:ai-agents pushed:>{seven_days_ago}", 50),
            (f"topic:llm-agents pushed:>{seven_days_ago}", 50),
            (f"topic:multi-agent pushed:>{seven_days_ago}", 50),
            (f"topic:agent-framework pushed:>{seven_days_ago}", 50),
            (f"topic:ai-coding pushed:>{seven_days_ago}", 100),
            (f"topic:code-generation pushed:>{seven_days_ago}", 100),
        ]
```
REPLACE:
```
        searches = (  # (GitHub topic, minimum stars)
            ("ai-agents", 50),
            ("llm-agents", 50),
            ("multi-agent", 50),
            ("agent-framework", 50),
            ("ai-coding", 100),
            ("code-generation", 100),
        )
```

**P2-6.** `src/probos/cognitive/scout.py` (the head of the loop; the dict lines that follow stay as they are)
SEARCH:
```
        new_repos: list[dict[str, Any]] = []

        for query, min_stars in queries:
            items = await self._search_github(query, min_stars)
            for item in items:
                full_name = item.get("full_name", "")
                if full_name in seen:
                    continue
                new_repos.append({
```
REPLACE:
```
        # BF-935: one entry per repository for the whole run: the first listing is kept, in the order first listed,
        # with the topics of the searches that returned it. A name in `seen` (an earlier run) is skipped as before.
        entries: dict[str, dict[str, Any]] = {}
        listings = 0

        for topic, min_stars in searches:
            items = await self._search_github(f"topic:{topic} pushed:>{seven_days_ago}", min_stars)
            for item in items:
                full_name = item.get("full_name", "")
                if full_name in seen:
                    continue
                listings += 1
                entry = {
```

**P2-7.** `src/probos/cognitive/scout.py` (the tail of the loop)
SEARCH:
```
                    "url": item.get("html_url", ""),
                })
```
REPLACE:
```
                    "url": item.get("html_url", ""),
                    "matched_topics": [],
                }
                kept = entries.setdefault(full_name, entry)
                if topic not in kept["matched_topics"]:
                    kept["matched_topics"].append(topic)

        new_repos = list(entries.values())
        self._duplicate_listings = listings - len(new_repos)
        logger.info(
            "Scout: %d listings of %d new repositories from %d searches; %d repeat listings merged",
            listings, len(new_repos), len(searches), self._duplicate_listings,
        )
```

**N2-1.** `tests/test_bf935_scout_within_run_dedup.py`
SEARCH:
```
    # BF-935 M1: xfail until M2 builds it (M2 removes this line and the next).
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-935 M2 builds it")

    @pytest.mark.parametrize("case", CASES)
```
REPLACE:
```
    @pytest.mark.parametrize("case", CASES)
```

### 7.3 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once); slice 4's entry is already under the title, so this entry lands newest. Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-935 (DATE), #1674 -- a Scout run lists each repository once, however many of its six topic searches return it.**
- **Base.** `ScoutAgent.perceive` skipped a search result only when an earlier run had seen it, so a repository that several of the six searches returned was listed once per search: one `REPO:` block each in the prompt and, as the model answered each block, one finding and one Captain notification (composite 4 or more) each. BF-214 (`f10369d0`, 2026-04-20) deferred the seen marking and removed the in-loop mark that had merged repeats.
- **Fix.** One entry per `full_name` for the run (first listing, first-listed order), with `matched_topics`, the searches that returned it; `ScoutFinding.matched_topics` carries it into the report, whose new `duplicate_listings` (always written, so a report without it predates the fix) records the repeats merged, also logged once per run. The prompt text, the cross-run `seen` and BF-214's deferral are unchanged. Contract `prompts/bf-935-scout-within-run-dedup.md`. Closes #1674.
- **Test isolation.** Three tests of `tests/test_bf214_scout_seen_deferral.py` replaced `ScoutAgent._data_dir` on the class and never restored it, so a `ScoutAgent` built later in the same process read a leftover temporary directory (in one process three `TestScoutDataDirectory` cases failed after them, as did six of this fix's new cases). They now use `monkeypatch.setattr`, which restores the property at teardown. Test-only; no assertion changed.

```

**P3-2.** `DECISIONS.md`. The anchor is the last bullet of BF-940 slice 4's entry (merged in PR #1783), the last entry of the landing-order run (once). Re-anchored by the orchestrator on 2026-11-11, as this contract instructs (the Architect could not read slice 4's entry): the pair as first written anchored on slice 3's last bullet; SEARCH is now the last line of slice 4's entry and the REPLACE keeps that line plus the entry below, so the file stays in landing order.
SEARCH:
```
- *Residual.* L1 to L12 of the contract. *Reversal.* Revert the BF-940 slice 4 commits.
```
REPLACE:
```
- *Residual.* L1 to L12 of the contract. *Reversal.* Revert the BF-940 slice 4 commits.

### BF-935 -- A Scout run lists each repository once, however many of its topic searches return it (DATE, #1674)

- *Scope.* `cognitive/scout.py` (`perceive`, `ScoutFinding.matched_topics`, `_scout_step_enrich_and_filter`, `_scout_step_persist_report`), tests: the new file and three tests of `tests/test_bf214_scout_seen_deferral.py`. Contract `prompts/bf-935-scout-within-run-dedup.md`.
- *G1 (the merge).* A local mapping keyed by the exact `full_name`, filled after the cross-run `seen` check: the first listing is kept, in first-listed order; BF-214's deferred marking is unchanged. Rejected: a lower-cased key with `.git` stripped (a second rule beside the exact-name `seen`, for a variance a run of the search API did not show); the numeric `id` (nothing else is keyed by it); marking seen in the loop (BF-214).
- *G2 (the record).* `matched_topics` on the entry, copied onto the finding and so into the report; never in the prompt (a repeated match must not read to the model as corroboration). `duplicate_listings` in the day's report, always written; one INFO line per search run. Rejected: the entry only (nothing persists); a top-level mapping (a second place to join); the topics in the prompt.
- *G3 (test isolation).* The three BF-214 act tests that replaced `ScoutAgent._data_dir` on the class now install it with `monkeypatch.setattr`, which restores it at teardown; no assertion changed. Rejected: restoring the property inside the new test file only (the leak would stay for `TestScoutDataDirectory` and every later Scout test); a suite-wide guard against a future leak (outside this defect; L8).
- *Residual.* L1 to L8 of the contract. *Reversal.* Revert the BF-935 commits; a report written with the new field then fails `ScoutFinding(**f)` in `_load_latest_report` until a newer report is written (L4).
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited (`git grep BF-935` over `ad67e493` finds nothing). `docs/development/roadmap-era-5-completed.md:229` ("Deduplication -- seen repos tracked in `data/scout_seen.json` with 90-day TTL") does not change: it describes the cross-run set, which stays true and is untouched.

## 8. What this does NOT change

Besides the new file it edits one existing test file, `tests/test_bf214_scout_seen_deferral.py`, in three places (P1-1 to P1-3: how three tests install `_data_dir`): no assertion, no other test of that file and no other test file changes. Unchanged: `ScoutAgent._data_dir`, `_seen_file` and `_reports_dir` (`scout.py:382`, `:389`, `:393` on the base; product code); `TestScoutDataDirectory` (`tests/test_quality_hardening.py`), which passes unchanged once the leak is closed; `_search_github` and the GitHub search; the six topics, star floors and `pushed:` window; `_INSTRUCTIONS` and the prompt text; the cross-run `seen` and BF-214's deferral (`_scout_step_parse_and_mark_seen`); `parse_scout_reports`, `filter_findings`, `format_digest`, the notification and Discord steps; `_load_latest_report`; report files already on disk; the day's-report overwrite on a second run; BF-934 (#1673); AD-1354 (#1672) and its tiers; AD-1346's rows (`ad1346_effect_census.py:118` pins `_search_github`); `config.py`; every document but the trackers. OSS only; no dependency.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| 1 | M2 | src/probos/cognitive/scout.py | `kept = entries.setdefault(full_name, entry)` | `kept = entries[full_name] = entry` | T1[overlap, three-searches], T2, T5 (4) |
| 2 | M2 | src/probos/cognitive/scout.py | `if topic not in kept["matched_topics"]:` | `if True:` | T1[twice-in-one-search] (1) |
| 3 | M2 | src/probos/cognitive/scout.py | `self._duplicate_listings = listings - len(new_repos)` | `self._duplicate_listings = 0` | T1[overlap, three-searches, twice-in-one-search], T3, T4, T5 (6) |
| 4 | M2 | src/probos/cognitive/scout.py | `new_repos = list(entries.values())` | `new_repos = list(entries.values())[::-1]` | T1[overlap, three-searches, no-overlap, seen-is-not-counted], G (no repeat; seen) (6) |
| 5 | M2 | src/probos/cognitive/scout.py | `f.matched_topics = list(meta.get("matched_topics", f.matched_topics))` | `pass` | T5 (1) |
| 6 | M2 | src/probos/cognitive/scout.py | `"duplicate_listings": getattr(agent, "_duplicate_listings", 0),` | `"duplicate_listings": 0,` | T5 (1) |
| 7 | M2 | src/probos/cognitive/scout.py | `if full_name in seen:` | `if False:` | G (seen; nothing new[seen1]), T1[seen-is-not-counted], T3 (4) |
| 8 | M2 | src/probos/cognitive/scout.py | `listings, len(new_repos), len(searches), self._duplicate_listings,` | `len(new_repos), listings, len(searches), self._duplicate_listings,` | T4 (1) |

Run by hand against the patched module (no pytest) in r1, and under pytest by the orchestrator (`mutants_bf935.py`, 2026-11-11): each mutant fails exactly the cases it names, in the numbers of the last column (4, 1, 6, 6, 1, 1, 4, 1), the new file alone. **Campaign of record:** the orchestrator's run on the oracle built from base `8a24dfba`, with `src/probos/cognitive/scout.py` blob `2cab3621569baa7f5b5e08eff644f54a6b7d6ca4` (sha256 `ae01a8cd3780bc8a2e0c6926aa93776ea686e8d76864dd477d7dd4c0d7f59593`, LF, 26205 bytes) and `tests/test_bf935_scout_within_run_dedup.py` blob `b59efcbf3e7d2eecf0cb7ac1c445859db6c98df2` (sha256 `09aaea14b22756e8d2550532b36791726d639d0e40eec393faee205e0843915e`, LF, 11445 bytes), the two files as M2 leaves them. A tree whose two blobs equal these does not repeat it (P1-1 to P1-3 touch neither file; the vector was unchanged with them: measured). If either differs, rerun all 8 rows: every Line is in `scout.py` and every Killed-by case is in the new file. Not tabulated, for the cap: `listings += 1` (T1 and T4 read the count it feeds) and the `getattr` default of row 6 (older tests build agents with `__new__`).

## 10. Recorded limits

- **L1 (history).** Section 1.4. The prompts of past runs were not persisted, so the effect of a repeated listing on a past score cannot be recovered; the probe's figures are the orchestrator's, over the vessel's files.
- **L2 (nameless items).** An item whose `full_name` is empty or missing (`item.get("full_name", "")` gives the empty string) is not rejected: such items merge into one entry under the empty name (before, each was listed); a JSON null name is a second key, `None`. Every item I read carried a non-empty string name; the API's schema was not read. Not pinned by a test (it would pin an accident). If it ever occurs, rank: skip with a WARNING; list each as before.
- **L3 (identity).** Names compare exactly: a result naming one repository in another case or with a suffix would not merge (not seen in my one run). A fork is a separate repository: the GitHub documentation says repository search leaves forks out unless `fork:true` is added, which Scout's queries do not add; the items of the one search I read had `fork` false and no `parent` key, so merging a fork into its parent would need a second call per fork. A rename between runs is re-listed once under the new name (the cross-run `seen` is exact-name; BF-214, unchanged). Not done: Wesley's fork and rename questions in #1672.
- **L4 (revert).** A report written with `matched_topics` fails `ScoutFinding(**f)` in code without the field: after a revert `_load_latest_report` logs a WARNING and `/scout report` answers `No scout reports found yet...` until a newer day's report is written or that file is edited. The loader is not changed here (not part of the defect); if wanted, a tolerant loader that drops unknown keys, as `counselor.py:69` and `identity.py:250` do, is the follow-up, and it would serve AD-1354's fields too; the top-level `duplicate_listings` is ignored by the loader either way.
- **L5 (first listing, and the model).** An entry's description, stars, language and topics come from its first listing; a later listing in the run (seconds apart) is dropped, where the last won in `_repo_metadata` and the prompt showed every listing. After M2 the model sees each repository once; no claim is made about the scores before it.
- **L6 (the report).** `total_classified` counts findings answered absorb or visiting_officer, not repositories listed; the report holds the repeat count but not the listings or repository counts (the INFO line has them). A later run on the same day whose answer reaches the chain overwrites the day's file (unchanged), so the file's `duplicate_listings` is that of the last run that wrote it, not of the last search. A run that finds nothing new resets the agent's counter, and `act` returns before the chain, writing nothing, only when the model's answer is empty or contains `No new repositories` (`scout.py:552` before A1: a case-sensitive test of the model's words, not of what `perceive` found); any other answer goes through the chain and writes the day's file with no findings and `duplicate_listings` 0 (measured with a stub model: section 15.7; not changed here: L9). `/scout report` writes nothing from A1 (D7).
- **L7.** Nothing here is a live-system claim except the probe's figures, quoted as the orchestrator's; my one read of the public search API is a shape check, with no figure.
- **L8 (class-level state left by another test).** `tests/test_bf214_scout_seen_deferral.py` replaced `ScoutAgent._data_dir` on the class in three tests and never restored it; P1-1 to P1-3 close it. What it needed: one process (or one xdist worker) running bf214 and then a test that reads a `ScoutAgent`'s directory: `TestScoutDataDirectory` (3 cases) and, from this BF, the new file (6 of its 16). `pyproject.toml:196` sets `-n 16 --dist=loadfile`, `scripts/run_test_gate.py:1765` defaults `--dist` to `loadfile`, and CI runs `-n auto` on top of that `addopts` (`.github/workflows/ci.yml:71`; read, not run), so whole files go to whichever worker is free, and not in collection order: xdist 3.8.0's `LoadFileScheduling` extends `LoadScopeScheduling`, which queues the files by test count, most first, while `--loadscope-reorder` is on (its default; `xdist/scheduler/loadscope.py`, read), and where its conditions hold the repository's duration scheduler (`tests/fixtures/duration_scheduler.py`, docstring and `:319-345`, installed by `tests/conftest.py:324-326`; read, not run here) moves the K heaviest files, K the workers xdist kept, to the front of that queue. Which files meet on one worker is therefore set by test counts, recorded durations and which worker is free, not by file names or by their order on a command line, and whether bf214 met the new file or `TestScoutDataDirectory` on one worker was not measured. What shows the rest is clean: section 11's scans of `tests/` (the only rebinding of a Scout or CognitiveAgent class attribute is bf214's three lines) and the new file run after each of the 17 files of G2, one process each (only bf214 broke it). What is not covered: no guard against a future leak (the detectors are the three `TestScoutDataDirectory` cases and the new file's guard cases, which fail only when a leaking file runs before them on the same worker), and the 5 other `type(x).attr =` sites and the 3 `__class__.__name__ =` sites in `tests/` were not read (none names a Scout class). A suite-wide autouse check that `ScoutAgent.__dict__` is unchanged after each test would close it; not done (suite-wide, outside this defect); file it if a second leak shows.

## 11. Verified Against Codebase (2026-11-11, reading tree `D:\ProbOS-worktrees\bf940s4-base` at `ad67e493`)

**Run by the Architect, read-only (CPython 3.12, win32; scripts in memory with `-B`, `HOME` and the data directory moved to a temporary folder that was removed afterwards; no pytest and no test function of the repository):**

```
git rev-parse HEAD, origin/main -> both ad67e493bdaaa9b6d134ae58581d59691140d42c; git status --short empty; the scout.py blob has no CR; line numbers of section 1 re-derived on it (the issue's :467-486 is from 5e3cc991)
the 7 code pairs, the marker pair and the two tracker pairs applied in label order to the LF blobs: each SEARCH once in the blob and once at its turn; every block is ASCII; the patched scout.py compiles; the PROGRESS and DECISIONS results join cleanly
the patched module exec'd over the real tree and the test file's 16 cases driven by hand with a small runner (parametrize, tmp_path, monkeypatch and caplog stand-ins, asyncio.run): base 6 pass and 10 fail, each at an assert of its own body (T1 at its getattr line); M2 16 pass; each mutant of section 9 fails exactly the cases listed
tests/fixtures/ad1346_file_write_census.py file_write_scan over the base and the patched source: the same (scope, name) points, two write_text calls
the older tests' paths driven by hand on the patched module (not their test functions): test_bf208's shape (one repository from all six searches: one block, 6 searches, 5 repeats, 6 matched topics); act() through the chain on a __new__ agent (test_ad647_process_chains.py:147-201): report written, duplicate_listings 0; enrich_and_filter on the stub of test_ad647b_chain_registry.py:149; ScoutFinding with nine positional arguments (test_scout.py:144); no _save_seen in perceive's source (test_bf214_scout_seen_deferral.py:57)
the six searches as Scout builds them, once against the public search API with gh (read-only, no figure kept): all six answered; every item had a non-empty string full_name that equalled the path of its html_url and never ended .git, and an integer id; a repository returned by more than one search carried identical strings; no two ids differed only by case; a repository carried a queried topic yet was not returned by that search; every item's own topics held the queried topic; items had fork (false) and no parent key
git show f10369d0^, f10369d0, 0c6da601 (scout.py) and git log -S on the in-loop line: added by 333f1a2b, removed by f10369d0 (which adds _pending_seen_repos); 0c6da601 holds the six searches and the in-loop mark
docs.github.com "Searching for repositories" (fetched): "To include forks in the search results, you will need to add fork:true or fork:only to your query."
```

**Absence Verified (2026-11-11)**

```
CLAIM: no other open or merged work claims BF-935; #1674 holds it
RUN:   git log --all subjects and --grep; prompts/bf-935* in each of the 131 worktrees; branches '*935*'; gh issue list --state all --search "BF-935 in:title"; gh pr list --state all --search "BF-935 in:title,body"; the bodies of #1672, #1677 and PR #1470 for the literal; git grep -n BF-935 HEAD (every file, docs/development/roadmap*.md included)
FOUND: 0 subjects, 0 files, 0 branches; #1674 only (OPEN, bug); PR #1470 matches on tokens, not the literal; #1672 names BF-935 as #1674; #1677 quotes it as the highest number when filed; 0 lines in HEAD
HOLDS: yes

CLAIM: only ScoutAgent._load_latest_report (scout.py:596) reads a day's report file; no UI, router, script or config does
RUN:   git grep -n -E "scout_reports|_reports_dir|ScoutFinding\(|total_classified|total_relevant|_last_findings|_load_latest_report" -- src ui/src scripts config; git grep -n -i scout -- ui/src src/probos/routers src/probos/api.py; git grep -n -E "ScoutFinding|scout_seen|SCOUT_REPORT_CHAIN|ScoutAgent|scout_report\b|_scout_step_" -- src ui/src, minus scout.py
FOUND: scout.py and __main__.py:2691, :2792 (the reset's directory list and label); UI hits are fixtures naming the callsign; the rest are comments, the duty id, the `/scout` intent names, the spawner and the chain's registration (startup/finalize.py:1950-1953: the same module-level object, so the patched handlers are the ones that run); in tests, test_ad647_process_chains.py:195-201 reads `total_classified`, `total_relevant` and `findings[0]` from the file, and test_distribution.py:1095, :1178 and test_quality_hardening.py:111 name the directory only
HOLDS: yes

CLAIM: these are the only tests or scans that read scout.py's source or pin one of its functions by qualified name: test_bf214_scout_seen_deferral.py:57 (perceive's source, for "_save_seen": the new comments hold none); ad1346_file_write_census.py:196 (a file row; its test ignores lines, :135, :170, :232); ad1346_effect_census.py:118 and test_bf892_spawn_env_guard.py:94, :512 (the name ScoutAgent._search_github, untouched); guard_name_allowlist.txt:21; test_ad1346_admission_service.py:585, :651, :664; test_layer_boundaries.py:151 (a comment); ad1343_seam_registry.py:173 names cmd_scout in commands_knowledge.py, not scout.py
RUN:   git grep -n -E "cognitive[/.]scout|scout\.py" -- tests scripts config src; git grep -n -E "getsource|read_text\(" -- tests, filtered for scout; test_bf925_guard_names.py read (guards rooted at self, cls, rt or runtime; `agent` is none)
FOUND: as listed; the patch adds no import, sink call or file write
HOLDS: yes

CLAIM: the new names are free; `queries` is local; the tests that run the changed code are in G2; nothing keeps a record of probos.cognitive.scout from reaching caplog (T4)
RUN:   git grep -n -E "matched_topics|duplicate_listings|_duplicate_listings" -- src tests scripts docs ui/src prompts config; git grep -n -E "\bqueries\b" -- src/probos/cognitive/scout.py; git grep -l -E "_pending_seen_repos|_repo_metadata|ScoutAgent|scout_search|_search_github|SCOUT_REPORT_CHAIN" -- tests src scripts docs ui/src config; grep for `.propagate =` and `propagate=False` in src; grep for `caplog.at_level(logging.INFO, logger="probos.cognitive` in tests
FOUND: 0 hits; :461 and :473 only; 11 test files (test_ad398_crew_identity, test_ad632f_activation_triggers, test_ad647_process_chains, test_ad647b_chain_registry, test_ad648_post_capability_profiles, test_bf208_scout_duty_perceive, test_bf209_scout_chain_bypass, test_bf214_scout_seen_deferral, test_bf892_spawn_env_guard, test_quality_hardening, test_scout) and the fixture ad1346_effect_census.py; only test_bf208 (two search cases), test_bf214, test_ad647 and test_ad647b (act or the steps) run the changed code; test_scout.py runs neither perceive nor act; test_commands_knowledge.py:74 is the no-pool path of /scout; no propagate setting in src, and the same caplog idiom is used for other probos.cognitive loggers (24 matches in 11 files)
HOLDS: yes
```

**r2 additions (2026-11-11; oracle `D:\ProbOS-worktrees\bf935-o1` on base `8a24dfba`, scratch commits contract `3d8e88a5`, M1 `9d4dffdb`, M2 `964627d4`, M3 `a2442700`; `origin/main` `fe488971`).**

**Run by the orchestrator, as reported in the consult request (outputs in the orchestrator's `files\bf935\`; Windows, CPython 3.12, `-n 0 -p no:randomly`):**

```
G1 at M1: 6 passed, 10 xfailed (g1-m1.txt); with --runxfail the 10 fail at the asserts section 6 names, never at a premise line (g1-m1-runxfail.txt)
the 8 mutants of section 9, new file alone: failing 4, 1, 6, 6, 1, 1, 4, 1 = the table (mutants-oracle-run1.txt); the architecture check clean (srp-size=92, layer-import=0, db-connect=30, unowned-task=13); M0: 290 collected over the 17 existing files of G2 (m0-collect-tally.txt)
G2 as r1 wrote it: 3 failed, 303 passed (g2-oracle.txt): test_quality_hardening.py::TestScoutDataDirectory::test_scout_uses_runtime_data_dir, ::test_scout_falls_back_to_default, ::test_reports_dir_uses_data_dir. The same 17 files in the same order without the new file, on the base scout.py: the same 3 fail, 287 passed (g2-17files-base.txt); each of the 3 passes alone, and test_quality_hardening.py passes alone
cause: test_bf214_scout_seen_deferral.py:79, :112, :138, type(agent)._data_dir = property(lambda self: tmp_path), never restored; the failing assertions show .../test_act_marks_seen_when_all_s0, the last such test
the new file after bf214 (suite order): 6 failed, 20 passed (order-bf214-then-bf935.txt): the guards test_a_seen_repository_is_skipped_and_perceive_marks_nothing_seen, test_when_nothing_is_new_the_answer_is_as_before[seen1] and test_an_older_report_still_loads, and the class cases T1[seen-is-not-counted], T3 and T5; the new file after each of the 17 files in turn, one process each: only bf214 breaks it (polluter-scan.txt)
with the three monkeypatch pairs, in the scratch tree D:\ProbOS-worktrees\bf935-m (bf214 blob 7902760692b1a5a48a6b11b71605914cf1ea4d8a): bf214 then the new file 26 passed; G2 306 passed (g2-oracle-fixleak.txt); G2 with the new file last 306 passed; the mutant vector unchanged
```

**Run by the Architect for r2, read-only (no pytest, no test, no file written; scripts in memory):**

```
the four base blobs: git rev-parse 8a24dfba:<path> in the oracle, and gh api on main (fe488971, PR #1783 merged 2026-11-12T00:12:22Z): scout.py 9b2cc9bc, the bf214 test 8c3b29db, PROGRESS.md a1095617, DECISIONS.md a07c172b: the same four
pyproject.toml:196 addopts "-n 16 --dist=loadfile"; .github/workflows/ci.yml:71 "pytest tests/ -n auto --maxfail=10 ..."; scripts/run_test_gate.py:1763 --workers default 16, :1765 --dist default loadfile
D:\ProbOS\.venv pytest 9.0.2, _pytest/monkeypatch.py:250-253 and :412-416: for a class target setattr records target.__dict__.get(name) and undo() restores it at teardown
tests/test_bf214_scout_seen_deferral.py: 10 tests; rg "_data_dir|_seen_file|_reports_dir|\.act\(|_runtime" hits only lines 76-155, the three act tests; the three SEARCH spans (lines 70-79, 105-112, 131-138) are ASCII (the file's non-ASCII lines, 115, 141 and 157, lie outside them), no trailing space, no tab
docs/development/roadmap.md: rg "BF-9[34][0-9]" finds no line, so no BF-93x or BF-94x row exists in the Bug Tracker; the Ledger paragraph stands
an in-memory script that follows apply_search_replace_blocks_bare.py (candidate files named on the label line, each SEARCH once in exactly one candidate, LF text, DATE replaced inside P3) applied N1-1, P1-1 to P1-3, P2-1 to P2-7, N2-1, P3-1 and P3-2 to the base blobs: 13 pairs, 0 failures; every SEARCH starts and ends at a line boundary; no non-ASCII character in any block; blobs: the new file after N1-1 f89e1e4a, scout.py 2cab3621, the new file after N2-1 b59efcbf, the bf214 test 79027606; numstat: bf214 +6 -6, scout.py +33 -13, the new file (N2-1) +0 -3, PROGRESS.md +5 -0, DECISIONS.md +8 -0. The same script on r1 gave the oracle's blobs and numstat for scout.py and the new file
```

**Absence Verified (2026-11-11, r2)**

```
CLAIM: no test other than test_bf214_scout_seen_deferral.py rebinds a class attribute of ScoutAgent, CognitiveAgent or BaseAgent without restoring it
RUN:   in tests/ of the oracle tree (base 8a24dfba): rg -n "type\(\w+\)\.\w+\s*=[^=]"; rg -n -P "(?<!monkeypatch\.)\b(setattr|delattr)\(\s*(type\(|ScoutAgent|CognitiveAgent|self\.__class__|\w+\.__class__)"; rg -n "\b(ScoutAgent|CognitiveAgent|BaseAgent)\.\w+\s*=[^=]"; rg -n "__class__\.\w+\s*=[^=]"; rg -U -n 'patch(\.object)?\(\s*(ScoutAgent|CognitiveAgent|"probos\.cognitive\.(scout|cognitive_agent)\.)' tests (multiline); rg -n '=\s*(mock\.)?patch(\.object|\.dict|\.multiple)?\(|patch(\.object|\.dict|\.multiple)?\(.*\)\.start\(\)|addCleanup\(\w*patch|\.start\(\)' tests, minus the awaited starts; rg -n "property\(" tests -g "*scout*" -g test_quality_hardening.py; the contexts of the patch hits read
FOUND: type(x).attr = : 8 lines, test_bf214_scout_seen_deferral.py:79, :112, :138 (ScoutAgent._data_dir) and 5 on other classes (test_ad628_crew_skill_readiness.py:325 on a MagicMock(), test_ad635e_clinical_shell_command.py:274, test_bf844_visiting_builder_cleanup.py:91, test_bf896_executor_identity_and_blocks.py:1042, test_bf904b_dispatch_and_visiting.py:121); raw setattr or delattr on a class: 0; Class.attr = on the three classes: 0; __class__.attr = : 3, test_escalation.py:182, :204, :230 (__name__ of a double's class); patch( on those targets: 16 lines, all in test_bf208_scout_duty_perceive.py (:50-56, :80-81, :104-105, :131-137, :164-165) and test_scout.py (:262, :275), every one inside a with (read: test_bf208_scout_duty_perceive.py :46-60, :77-82, :102-106, :126-142, :160-176 and test_scout.py :258-264, :272-277); patchers held in a variable or started without await: 188 lines in tests/, none naming scout or CognitiveAgent (the held patchers are _CREW_PATCH on probos.routers.agents.is_crew_agent in 7 files and close_patcher at test_procedure_store.py:836); property( beside _data_dir: bf214 only
HOLDS: yes for the Scout classes; the 5 other sites and the 3 __name__ sites name no Scout class and were not read further (L8)

CLAIM: BF-935 is still held by #1674 alone, so the bf214 fix needs no number of its own
RUN:   gh issue list --state all --search "BF-935 in:title"; gh pr list --state all --search "BF-935 in:title"
FOUND: #1674 only (OPEN); no pull request
HOLDS: yes (no AD or BF number is allocated by r2)
```

## 12. Prior Art and Blind Spots

- **Internal: adopted.** BF-214's deferral (kept) and the in-loop mark it replaced (not restored: it marked before classification succeeded); the module's `getattr(agent, "_x", default)` reads in step handlers (`:241`, `:265`); AD-1354's plan to add a defaulted field to `ScoutFinding` and a `schema_version` later; pytest's `monkeypatch.setattr` on a class, which the new file already uses (D6). **Rejected:** a normalised key; marking in the loop; the topics in the prompt; restoring the property inside the new file only (D6). **External:** the GitHub documentation on forks only.
- **Blind spots handled.** A repeat inside one search (T1); a repeated repository already in `seen` (T1, G); a run with nothing new after a run with repeats (T3); an older and a newer report file (G, T6); agents built with `__new__` (the `getattr` default); the census, guard and layer scans (section 11); a revert (L4); a class-level property left by an earlier test in the same process (D6, P1-1 to P1-3, G2's order, L8).
- **What discards a correct result.** The `seen` skip comes before the merge; the first listing's fields replace later ones (L5); a name that differs in case or suffix is not merged (L3); nameless items merge (L2); the model may merge or drop blocks as before. Nothing in the patch discards a finding the model returned. **Recorded:** L1 to L8.

## 13. Diff Reviewer: properties to verify

1. In `perceive`, a name enters `entries` at most once, only after the `seen` check, and its first listing is kept (`setdefault`); `listings` counts each listing not skipped as seen; `new_repos` is `list(entries.values())`, so `_pending_seen_repos`, the prompt blocks, the N in `Classify these N` and `_repo_metadata` are one-to-one with it. For a run with no repeat the prompt, the pending names and the entries (but for `matched_topics`) are byte-identical (G).
2. BF-214: `perceive` still neither calls `_save_seen` nor writes the seen file; the new comments hold no `_save_seen`; `_scout_step_parse_and_mark_seen` is unchanged.
3. `_duplicate_listings` is assigned on every search run before the nothing-new return; `_scout_step_persist_report` writes it with the `getattr` default the module's other step readers use, and writes the key even when it is 0.
4. `ScoutFinding.matched_topics` is the last field and has a default: positional constructions and `asdict` change only by the key; `_load_latest_report` loads an older and a newer file; trace the TypeError of L4.
5. Nothing new reaches the prompt: `repo_text` is untouched; the six query strings and star floors are byte-identical (G); the INFO line's arguments are in the order T4 pins.
6. M1: the file collects on the unfixed tree, imports no BF-935 name, and the 10 class cases fail at their own `assert`, never at a premise line; N2-1 removes the marker only.
7. The census, guard-name and layer files of G2 pass unchanged: the patch adds no import, sink call or file write.
8. P1-1 to P1-3: `git diff` of `tests/test_bf214_scout_seen_deferral.py` is 6 lines added and 6 removed: the three `def` lines gain `, monkeypatch`, and the three `type(agent)._data_dir = property(lambda self: tmp_path)` lines become `monkeypatch.setattr(type(agent), "_data_dir", property(lambda self: tmp_path))`; no assertion and no other line changes; the file's blob afterwards is `7902760692b1a5a48a6b11b71605914cf1ea4d8a`. After each of the three tests `ScoutAgent.__dict__["_data_dir"]` is the property defined in `scout.py` again (pytest restores a class attribute from the class's own `__dict__`). No other test file changes.
9. G2 holds with the new file first or last, and bf214 then the new file prints 26 passed: the leak is closed at its source and not by the order of the gate. Flag any test that rebinds a class attribute without `monkeypatch` or a context manager.

## 14. Acceptance criteria

- G1, G2 and G3 pass as stated (G2: 330 passed, and 26 passed for the leak's reproduction), GA1 passes (24 passed; sections 15.3, 16.3 and 17.3), and the batch's broad gate is green with a receipt.
- **The crew's count check:** for N listings across M searches the output has one prompt block, one pending name and one finding per unique `full_name`, and `duplicate_listings` equals listings minus unique repositories (T1, T5). The issue's "one entry and one classification call" is read as one `REPO:` block in the single prompt `perceive` builds (`:511-514`); T5's model text answers one report per block shown.
- **The topic list is kept** on the entry and on each persisted finding, and is not in the prompt (T1, T5, G).
- **The cross-run `seen` and BF-214's deferral are unchanged** (G, the existing BF-214 tests); for a run with no repeat the prompt text and the pending names are the same as before (G).
- **How far back** is stated (section 1.4, L1, L5).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Amendment A1 (review round 1, 2026-11-11)

Review round 1 of the candidate (head `27ee8593`) returned NOT READY: F1 (P2, a defect with ordinary reach that predates BF-935) and F2 and F3 (P3, two sentences of this contract). A1 is one more commit on the branch, after M3. It adds two hunks to `scout.py`, one new test file and tracker text, edits no existing test, and corrects L6 and L8 in place (and M0, G2 and the first acceptance bullet, whose totals it changes). Its blocks are the commit's diff: this section lists them and holds no fenced code, because it is itself added by a SEARCH/REPLACE pair, whose fence cannot carry one.

### 15.1 The blocks

1. `src/probos/cognitive/scout.py`: `ScoutAgent.decide` is added between `perceive` and `act`. For an observation whose intent is `scout_report` it returns `{"action": "scout_report", "report_text": <the observation's context>}` and makes no call to the base; for every other intent it returns `await super().decide(observation)`.
2. `src/probos/cognitive/scout.py`: at the head of `act`, before the conversational pass-through, the duty test and the chain, a decision whose intent is `scout_report` returns `{"success": True, "result": decision.get("report_text", "")}`.
3. New file `tests/test_bf935_scout_report_display.py` (15.4).
4. PROGRESS.md (a bullet), DECISIONS.md (the scope line, G4, the residual line), the regenerated ledger (G3), and this contract's own edits.
5. The commit message: `BF-935 A1: /scout report shows the saved report and no longer rewrites it, notifies again or marks a failed search seen; two sentences of the contract corrected (#1674)`.

### 15.2 D7. The intent `scout_report` (correctness, safety, compatibility, fit, reversibility, validation cost)

**What it did.** `/scout report` and the agent's intent descriptor (`scout.py:372` at the head: "Show the latest scout intelligence report"; the decomposer reads it) send the intent `scout_report` through the whole lifecycle. `perceive` loaded the saved report's digest into the context (`:442`); the model was then asked about it; `act` ran any non-empty answer that lacks the nothing-new phrase through the classify, store and notify chain, and a fresh agent has no search metadata. So a report was rewritten with the model's wording and without language, license, topics, `matched_topics` and `duplicate_listings`; a file for today was added when the saved report was older, and became the newest; an answer with no block wrote a report with no findings (on a fresh install too); the Captain was notified again and, where Discord is set up, the digest posted again; and the names an earlier search had left pending (its model answer was empty, so `act` returned before marking or clearing them) were marked seen by the next `/scout report` answer that held a block, though nothing had classified them (BF-214's deferral, defeated). It has done so since AD-394 (`333f1a2b`: `perceive` loads the report for `scout_report`; `act` stores and notifies whatever is answered but the empty answer and the nothing-new phrase); the seen marking since BF-214. It destroys the record this fix adds, so A1 repairs it here and does not file it apart.

| # | Option | Judgement |
|---|---|---|
| 1 | `decide` answers `scout_report` from the saved report with no model call, and `act` returns that text before the chain (chosen) | Fixes every case above, the cost included, and shows the stored digest, as the descriptor and `docs/getting-started/shell.md:70` say. It stays inside the lifecycle: the stop check and admission ticket of `handle_intent`, the concurrency slot, `perceive`, `act`, `report`, the working-memory record, the action episode, the confidence update and the completion event all still run. Precedent for a `decide` that skips the model on what `perceive` or an earlier step produced: `WebSearchAgent.decide` (BF-769, `web_agents.py:616-627`: it returns its own `action` and key, which its `act` consumes, the shape used here), `_FetchGatedMixin.decide` (BF-772), `UnreadableListGuard.decide` (BF-961), `SoftwareEngineerAgent.decide`. The text travels as `report_text`, not `llm_output`, so the faithfulness checks (AD-568e, AD-589, AD-607d), the conclusion record (AD-669) and the fallback event do not treat a stored report as a model response |
| 2 | `act` alone returns the model's text for `scout_report` | Stops the writes and the notification, keeps a model call whose answer is the model's wording or raw classification blocks, not the report; cost kept |
| 3 | `_scout_step_persist_report` keeps the saved `topics`, `matched_topics` and `duplicate_listings` when the run did not search | Leaves the empty report, the notification, the Discord post, the model call and the seen marking, and gives the storage step a branch for a caller that should not reach it |
| 4 | A separate BF and a recorded limit | The review policy fixes what has ordinary reach inside the item, and the item's own record is what is lost |

**What it changes.** `/scout report` prints the stored digest as `_load_latest_report` formats it (the header carries the saved report's date), or `No scout reports found yet. Run /scout to generate one.`; it asks no model (so it works with no model configured), writes nothing, notifies nothing and leaves `_pending_seen_repos` alone. The natural-language route is the same lifecycle with the same result. `/scout` (`scout_search`) and the duty's search are decided and acted as before: `decide` defers for every observation whose intent is not `scout_report`, and the duty's observation intent is `scout_search` (BF-225). `act`'s guard keys on `decision["intent"]`, which the lifecycle sets from the message: `proactive_think` for the duty.

### 15.3 Gates

- **GA1.** `PY -m pytest tests/test_bf935_scout_report_display.py -q -n 0 -p no:randomly`. **Expected: 24 passed** (A1's 8 and, from A2 and A3, 16 more: 16.3 and 17.3). With the file as A1 left it (8 cases) laid over the head `27ee8593` (no A1 hunk in `scout.py`): 6 failed and 2 passed, the failures at the asserts 15.4 names.
- **Focused additions:** `PY -m pytest tests/test_ad1343_stop_seam_inventory.py tests/test_ad1343_seam_registry.py -q -n 0 -p no:randomly`: the counts unchanged (`tests/fixtures/ad1343_seam_census.py:154` skips a receiver that starts with `super(`; `SoftwareEngineerAgent.decide` has the same line).
- **G2** (section 4) totals 314 after A1, 322 after A2 and 330 after A3. **G3** is run again after the tracker pairs: PROGRESS.md gains a line at A1, another at A2 and another at A3 and each commit adds a subject, so the snapshot and the report change; no AD or BF token does.

### 15.4 Tests (`tests/test_bf935_scout_report_display.py`, 8 cases at A1, 16 from A2 (16.4) and 24 from A3 (17.4); no xfail: the file arrives with the code it tests)

The real `cmd_scout`, `handle_intent` and lifecycle on a real `ScoutAgent` over `tmp_path`; the model's `decide` and the GitHub search replaced through `monkeypatch` (restored exactly: both are defined in those classes' own `__dict__`); a stub console, notification queue and pool; no network.

| Case | Covers | Without A1's code |
|---|---|---|
| `test_the_report_command_shows_the_saved_report_and_changes_nothing[blocks, prose, empty]` | A saved report dated today, `/scout report`, for each answer a model could give: the reports directory is byte-identical, nobody is notified, the model is not asked, the console shows the saved digest | `[blocks]` and `[prose]` fail at the directory comparison (the file is rewritten); `[empty]` at the model-not-asked assert |
| `test_the_natural_language_route_gets_the_saved_report_and_changes_nothing` | `handle_intent` with the intent `scout_report` and a sentence as context, over a saved report of an earlier day: no file for today appears, `success` is True, the result is the saved digest | fails at its first assert (a file for today is added) |
| `test_with_no_saved_report_it_says_so_and_writes_nothing` | No saved report: the line saying so, and the reports directory is not created | fails at "a report with no findings was written" |
| `test_a_report_after_a_failed_search_leaves_that_search_unmarked` | A search whose model call yields nothing leaves two names pending and nothing marked (premise, true on both trees); a `/scout report` after it leaves them pending and the seen file absent | fails at "the repositories of the failed search were marked seen without being classified" |
| `test_the_search_command_still_classifies_stores_and_notifies` | `/scout` through the real lifecycle: the model is asked once about a `scout_search`; both reports are stored and notified | passes on both trees |
| `test_the_duty_search_still_classifies_stores_and_notifies` | The duty's `proactive_think` through the real lifecycle: the model is asked once about a `scout_search` (BF-225), both reports are stored and notified | passes on both trees |

### 15.5 Mutation rows 9 to 15 (each Line occurs once, stripped, in `scout.py` after A1)

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| 9 | A1 | src/probos/cognitive/scout.py | `if observation.get("intent") == "scout_report":` | `if False:` | the 3 report-command cases, the natural-language case, the no-report case, the failed-search case (6), and from A2 the 3 report-as-text cases (9) |
| 10 | A1 | src/probos/cognitive/scout.py | `if observation.get("intent") == "scout_report":` | `if True:` | the failed-search case, the search-command case, the duty case (3), and from A2 the 3 search-as-text cases (6) |
| 11 | A1 | src/probos/cognitive/scout.py | `return {"action": "scout_report", "report_text": observation.get("context", "")}` | `return {"action": "scout_report", "report_text": ""}` | the 3 report-command cases, the natural-language case, the no-report case (5), and from A2 the 3 report-as-text cases (8) |
| 12 | A1 | src/probos/cognitive/scout.py | `if decision.get("intent") == "scout_report":` | `if False:` | the same five (5), and from A2 the 3 report-as-text cases (8) |
| 13 | A1 | src/probos/cognitive/scout.py | `return {"success": True, "result": decision.get("report_text", "")}` | `return {"success": False, "result": decision.get("report_text", "")}` | the natural-language case (1) |
| 14 | A1 | src/probos/cognitive/scout.py | `return {"success": True, "result": decision.get("report_text", "")}` | `return {"success": True, "result": decision.get("llm_output", "")}` | the same five (5), and from A2 the 3 report-as-text cases (8) |
| 15 | A1 | src/probos/cognitive/scout.py | `return await super().decide(observation)` | `return {"action": "error", "reason": "x"}` | the failed-search case, the search-command case, the duty case (3), and from A2 the 3 search-as-text cases (6) |

The Architect ran each row in memory with a stand-in runner over A1's 8 cases (the vector 6, 3, 5, 5, 1, 5, 3, which the orchestrator also measured under pytest at A1). The counts in the table are those over the file as A2 leaves it: A2 appends 8 cases to the same file, and the same mutants also fail A2's report cases (rows 9, 11, 12 and 14) and its search cases (rows 10 and 15), so the vector over the 16 cases is 9, 6, 8, 8, 1, 8, 6 (measured under pytest by the orchestrator on the A2 tree), and it is the same over the 24 cases of A3, whose cases do not reach `scout.py` (the Architect's stand-in runner, 17.5). The orchestrator's run on the files as A3 leaves them is the campaign of record for these rows (mark the base tree and each file's sha256; rerun all seven if either differs). Rows 1 to 8 (section 9) must be rerun on A1's `scout.py` blob: no row mutates a line A1 touches or adds, so the vector is expected unchanged (4, 1, 6, 6, 1, 1, 4, 1) with the first new file alone, whose blob none of A1, A2 and A3 changes.

### 15.6 Recorded limits L9 and L10

- **L9 (a nothing-new run: the model's words decide).** `act` returns before the chain on a nothing-new run only when the answer is empty or contains `No new repositories` (a case-sensitive test of the model's words, not of what `perceive` found). Any other answer (measured with a stub model: `There are no new repositories to classify right now.` on the head and on the base, and the phrase in lower case on the head) goes through the chain, which writes the day's file with no findings and `duplicate_listings` 0 over the earlier run's report and, where Discord is set up, posts the digest of no findings (read, not run). Pre-existing and not changed here: it is a second defect of the same kind, in the path the duty runs daily, and fixing it changes what the Scout does on every nothing-new run. A report with no findings cannot be told from such an overwrite, so a baseline that reads `duplicate_listings` (AD-1354) should not trust a report with `total_classified` 0. The follow-up to file: decide a nothing-new run from `perceive`'s own result, as D7 does for `scout_report`, not from the model's words.
- **L10 (the display).** `/scout report` and the natural-language route show the stored digest: the findings persisted (composite 3 or more), the saved report's date in the header, or the line `No scout reports found yet. Run /scout to generate one.` when there is no report or the newest file does not load (L4: so L4's sentence about `/scout report` is true as written from A1; before A1 the command answered with the model's wording and rewrote the file). The model is no longer asked. The ontology's text for the post's capability `scout_report` (`config/ontology/organization.yaml:179-181`: "Classify GitHub repositories ... and generate structured findings report") describes the duty, not this intent, and is left as it is (outside this item).

### 15.7 Verified (2026-11-11, the Architect; read-only, scripts in memory over temporary directories removed afterwards; no pytest and no repository test)

- **The sentences (F2, F3).** `Select-String` over this contract at `27ee8593` for `collection order|scheduling|xdist|loadfile|whichever|worker|last run|the last|last search|last report|overwrit|suite order|in order|luck|first or last|file first|file last|LAST|new file last|run after|runs after|ran bf214|before it` (case-insensitive, so every `last` hits) found 33 lines: 5, 10, 14, 22, 74, 77, 92, 109, 114, 128, 257, 288, 294, 330, 343, 358, 369, 382, 393, 452, 564, 586, 601, 609, 610, 612, 638, 661, 662, 663, 670, 702 and 707. Read one by one: only 610 (L6) and 612 (L8) say that the file's count is the last run's or that files run in collection order; 92 (G2) is true of the serial run and says so now; 5, 74, 662, 663 and 707 describe serial runs they measured; 77 says a worker may receive either file later; 109, 288 and 452 say the agent's counter belongs to the last search (true of the attribute); 586 lists the day's-report overwrite as unchanged; the rest use `last` or `before it` of other things. The same scan over PROGRESS.md lines 1 to 8 and DECISIONS.md lines 1643 to 1649 has no hit.
- **F1 reproduced.** The orchestrator's probe on the head, run again: blocks, file rewritten, 2 notifications, `duplicate_listings` 5 to 0, summary, language, license, topics and `matched_topics` replaced or emptied; prose, file rewritten with 0 findings (2 to 0); empty, untouched. Through the real `cmd_scout("report")`, `handle_intent` and lifecycle with a fresh agent and a stub model, on the head: the same, with the model asked once in every case and `No new findings to report.` printed for the empty one; with A1 applied in memory: nothing changes, the model is not asked, the digest is printed.
- **The seen marking.** On the head, a `/scout` that found two repositories whose model call yielded nothing, then a `/scout report` with a model answering one block: the seen file then held the two names no one had classified. With A1 it does not exist.
- **L6.** A nothing-new `/scout` against a saved report, stub model, on the head: the answers `No new repositories found since last scan.` and the empty one left the file untouched; `There are no new repositories to classify right now.` and `no new repositories found since last scan.` rewrote it with 0 findings and `duplicate_listings` 0. On the base tree `D:\ProbOS-worktrees\bf934-base` (`scout.py` blob `9b2cc9bc`, equal to `fe488971`): `There are no new repositories to classify right now.` rewrote the file with 0 findings and the exact phrase left it untouched (the other two answers were not run there); and `/scout report` with a prose answer replaced a 2-finding report with none.
- **L8.** `LoadFileScheduling.__mro__` is `LoadFileScheduling, LoadScopeScheduling, object` (xdist 3.8.0); `LoadScopeScheduling.schedule` orders scopes by test count, most first, when `loadscopereorder` is on, and the option defaults to True (`xdist/plugin.py`); `tests/fixtures/duration_scheduler.py:319-345` and its docstring (lines 1-80); `tests/conftest.py:324-326`.
- **History.** `git show 333f1a2b`: `perceive` loads the report for `scout_report` (lines 233-237) and `act` stores and notifies any answer but the empty one and the nothing-new phrase (317-360). `git show 0c6da601^` and `0c6da601`: the six separate searches and the in-loop mark first together at `0c6da601`; `git log -S` finds the mark added by `333f1a2b` and removed by `f10369d0`. The base line numbers of section 1.1 hold on `fe488971`.
- **The lifecycle** (`cognitive_agent.py` at the head): `decide` is called at `:7595`; `decision["intent"]` is set at `:7596`; the AD-568e, AD-589 and AD-607d checks (`:7602`, `:7632`, `:7660`) return without a result for a decision with no `llm_output`, `response`, `answer` or `text`; `act` at `:7758`; the action episode at `:7851`; `update_confidence` at `:7955`; the `IntentResult` at `:8008`. `rg 'decision\["llm_output"\]' src/probos` finds one assignment (`:7751`).
- **`decide` overrides** (corrected in A2, F5: A1 wrote "42 matches in 35 files", which no revision reproduces, and called two mixin classes `CognitiveAgent` subclasses). `git grep -n -E 'async def decide\(' <revision> -- src/probos` finds 37 matches in 31 files at `fe488971` and at `27ee8593` and 38 in 32 at `a6c19818` (the 38th is `ScoutAgent.decide`, `scout.py:539`); `rg -n "async def decide\(" src/probos` over the tree at `a6c19818` finds the same 38 in 32, and `rg -n "def decide\(" src/probos` finds 43 in 36 (five more, synchronous methods of the admission, attention-faculty, economic-judgment and organ classes). An AST pass over the 38 at `a6c19818` (each `async def decide` and the bases of its class) found 2 base definitions (`CognitiveAgent`, `cognitive_agent.py:3736`, and the abstract `BaseAgent`, `substrate/agent.py:66`), 8 on `CognitiveAgent` subclasses (`WebSearchAgent`, `web_agents.py:616-627`, BF-769; `SoftwareEngineerAgent`, `builder.py:2603-2609`; `ScoutAgent`; and the five M365 agents, `m365_connector.py:263`, `:363`, `:527`, `:626`, `:725`), 2 on plain mixin classes that have no base and that agents list among their bases, `_FetchGatedMixin` (`web_agents.py:367-377`, BF-772; `class _FetchGatedMixin:` at `:288`) and `UnreadableListGuard` (`stored_list.py:92-97`, BF-961; `class UnreadableListGuard:` at `:80`), 21 on other `BaseAgent` subclasses and 5 on other classes. This is a census of the command's matches, not a list of precedents. The four the contract cites (`WebSearchAgent`, `_FetchGatedMixin`, `UnreadableListGuard`, `SoftwareEngineerAgent`) return without the model for a result an earlier step produced (`fetch_failed`, `search_failed`, the unreadable-list key, the Transporter's result) and otherwise call `super().decide`; the five M365 methods contain neither `super().decide` nor `_decide_via_llm`, return the observation or the error dict `NotAuthorizedError` (no token) and call only `logger.warning` and `self._token_manager.get_token`.
- **Absence Verified.** CLAIM: no existing test pins the model round trip of the intent `scout_report`. RUN: ripgrep over `tests` for `intent["']?\s*[:=]\s*["']scout_report|["']scout_report["']\s*[:,)]?\s*,?\s*(params|context)|intent_name\s*==\s*["']scout_report`; then `handle_intent|\.decide\(|\.act\(|_run_cognitive_lifecycle` over the 11 files that name `ScoutAgent`. FOUND: two lines, `test_bf208_scout_duty_perceive.py:171` and `:176` (`perceive` only); `act` drivers in `test_ad398_crew_identity.py` (conversational intents), `test_ad647_process_chains.py:190` (intent `scout_search` with the duty) and `test_bf214_scout_seen_deferral.py:98, :124, :155` (intent `proactive_think` with the duty); `.decide(` only in `test_ad632f_activation_triggers.py:208-323` (no Scout agent). HOLDS: yes. CLAIM: no other code sends the intent `scout_report`. RUN: `rg -n scout_report` over `src`, `ui/src`, `scripts`, `docs`, `config`. FOUND: `commands_knowledge.py:136` (`cmd_scout`), the descriptor and `_handled_intents` (`scout.py:372`, `:376`); the rest are the chain name, the duty id, the work-item template (`workforce.py:767`), the ontology capability (`organization.yaml:179`, `:181`) and a research note. HOLDS: yes.
- **Scans.** `ad1343_seam_census.py:153-159` (a receiver that starts with `super(` is not an agent-work call), `test_ad1343_stop_seam_inventory.py:87-94` (reads the `CognitiveAgent` class body only), `check_architecture_principles.py:187-188` (500 body lines, 15 direct methods; `ScoutAgent` has 10 and 269 lines, AST at the head). Expected unchanged, not run.
- **The new tests** (the real text of the new file, driven by a stand-in runner for `parametrize`, `tmp_path` and `monkeypatch`): on the head 6 fail at the asserts of 15.4 and 2 pass; with A1 applied in memory 8 pass; the class attributes the cases replace were restored in both runs.

### 15.8 Diff Reviewer: properties to verify for A1

1. `ScoutAgent.decide` returns for an observation whose intent is `scout_report` before any call to the base, so the decision cache, the qualification refresh, the procedural-memory check, the chain gate and `_decide_via_llm` are skipped; `report_text` is the observation's context; for every other intent it is `await super().decide(observation)`. The duty's observation intent is `scout_search` (BF-225), so it defers.
2. `act` returns `{"success": True, "result": decision.get("report_text", "")}` for a decision whose intent is `scout_report`, before the conversational pass-through, the duty test and the chain, and nothing else in `act` changed.
3. The decision has no `llm_output`, `response`, `answer` or `text`, so the AD-568e, AD-589 and AD-607d checks return without a result and the AD-669 conclusion is empty.
4. No existing test file changed; the six report cases fail on the head at the asserts of 15.4 and pass after; the two search cases pass on both; each row of 15.5 is killed as tabulated.
5. A1 adds no import, no file write and no sink call; the effect and file-write censuses, the AD-1343 seam tests and the layer test pass unchanged.
6. `perceive`'s `scout_report` branch and its test (BF-208's cache path), `cmd_scout`, `_load_latest_report`, the intent descriptors and `_handled_intents` are unchanged.

### 15.9 Acceptance for A1

- GA1 passes (8 passed at A1, 16 at A2, 24 from A3; 6 failed and 2 passed on the head `27ee8593` with the file as A1 left it), G2 passes (314 passed at A1, 322 at A2, 330 from A3), G3 is regenerated and green, rows 1 to 8 of section 9 are rerun on A1's `scout.py` (expected unchanged) and rows 9 to 15 are killed as tabulated.
- `/scout report` and the natural-language route show the saved report and write nothing, notify nobody, mark nothing seen and ask no model (15.4); `/scout` and the duty's search are as before.
- L6 and L8 say only what was read or run; L9 and L10 are recorded.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Amendment A2 (review round 2, 2026-11-11)

### 16.1 The blocks

1. `src/probos/experience/commands/commands_knowledge.py`: in `cmd_scout`, `console.print(output)` becomes `console.print(output, markup=False)` and `console.print(f"[red]Scout error: {e}[/red]")` becomes `console.print(f"Scout error: {e}", style="red", markup=False)`; one comment line says why. No import and no other line.
2. `tests/test_bf935_scout_report_display.py` (A1's file): the imports (`io`, `re`, `Console`), a `summary` argument (its default is what the helper wrote before) on `_block`, `_classify` and `_World.save`, one docstring sentence, and 8 cases at the end (16.4).
3. PROGRESS.md (a bullet), DECISIONS.md (G5 and the residual line), the regenerated ledger (G3) and this contract's own edits.
4. The commit message: `BF-935 A2: /scout prints what the Scout returns as text, not as Rich markup, and the contract's decide-override census is corrected (#1674)`.

### 16.2 D8. The Scout command prints text as text (correctness, safety, compatibility, fit, reversibility, validation cost)

**What it did.** `cmd_scout` printed `result.result` with `console.print(output)` and a failure with `console.print(f"[red]Scout error: {e}[/red]")`, both with Rich markup on. Text that Rich reads as markup was changed or raised: the score tag `[score: 4.5]` that `format_digest` writes after every finding (`scout.py:179`, `:193`) was dropped from every digest the command printed; an unmatched closing tag in a summary (`[/b]`, in a note about BBCode, say) raised `MarkupError`, and the error line then raised the same error again (the message of a `MarkupError` holds the closing tag), so nothing after the status line was printed; a matched tag such as `[bold red]x[/bold red]` was applied and dropped. The search path, `/scout`, had the defect before BF-935. A1 made the report path print the saved text verbatim every time (before A1 it printed the model's wording, so the saved text reached the console only through what the model repeated), so one saved summary the model wrote once could make `/scout report` fail until the next day's report replaced the file. The shell's own error lines (`shell.py:216`, `:350`, `:364`) print the exception as markup too and re-raise the same `MarkupError` (measured on their f-strings), so on the interactive shell the exception would end `run()` (read; not run).

| # | Option | Judgement |
|---|---|---|
| 1 | `markup=False` on the result print and on the failure print; the failure keeps its red as `style="red"` (chosen) | Prints the text as it is (measured over a real console: `[/b]`, `[score: 4.5]`, `[bold red]Rich[/bold red]` and a trailing backslash unchanged; a non-string result prints as before). No import, no parse, any result type (`IntentResult.result` is `Any`, `types.py:84`). `rich>=13.0` has the keyword; no class of `src/probos` defines its own `print`. Two lines |
| 2 | `rich.markup.escape` on both | `escape(None)` raises `TypeError` (measured) and a text ending in a backslash prints with it doubled (measured); needs an import. Same display otherwise |
| 3 | The digest made Rich-safe at its source | The same text goes to the notifications, Discord, the MCP and A2A handlers and the stored-report display, none of them a Rich console; presentation in the data. Rejected |
| 4 | A recorded limit and a follow-up | The report path regressed with A1 and the search path has it, with the REPL consequence above: the review policy fixes what has ordinary reach inside the item. Rejected |
| 5 | Render the digest as Markdown | A renderer change; the digest is Discord-flavoured Markdown that the shell has always shown as text. Not made (L11) |

**What it changes.** `/scout` and `/scout report` print the digest, or the line `No scout reports found yet. Run /scout to generate one.`, exactly as the agent returned it: `[score: 4.5]`, `**bold**` and `*Insight:*` print literally, as does any bracket in a summary. Emoji codes still convert and numbers and URLs are still highlighted on a terminal (the console's own settings are untouched: measured). A failure prints `Scout error: <message>` in red, literally. The status line, a non-string result and every other consumer of the text (notifications, Discord, MCP, A2A, the stored report) are unchanged.

### 16.3 Gates

- **GA1.** `PY -m pytest tests/test_bf935_scout_report_display.py -q -n 0 -p no:randomly`. **Expected: 16 passed at A2, 24 from A3 (17.3).** With the file as A2 left it laid over `a6c19818` and `commands_knowledge.py` as it is there (no A2 hunk): 8 failed (A2's cases, at the asserts 16.4 names) and 8 passed (A1's).
- **G2** (section 4) totals 322 at A2 (290 + 16 + 16) and 330 from A3 (290 + 16 + 24). **G3** is run again after the tracker pairs.
- No gate is added. A2 adds no import, call, write or class, so the architecture check, the layer test, the effect and file-write censuses and the AD-1343 tests are expected unchanged, not run. `tests/test_commands_knowledge.py` (a G2 file) is unchanged: `test_cmd_scout_no_pool` returns before the changed lines.

### 16.4 Tests (8 cases at the end of `tests/test_bf935_scout_report_display.py`)

The real `cmd_scout`, `handle_intent` and lifecycle on a real `ScoutAgent` over `tmp_path` (A1's world), with a real `rich.console.Console` over an `io.StringIO` in place of the world's `print` lambda, which parses no markup and so hid the defect. As A2 wrote it the console was built with `width=400`, `force_terminal`, `no_color`, `color_system` and `legacy_windows`, and this sentence and the helper's comment said that no environment variable changed what the cases compare; round 3 (F6) showed that under `TERM=dumb` the colour console was 80 columns wide, and the sweep of 17.2 that in a notebook kernel nothing reached the buffer. A3 gives the console all eight settings that Rich reads from the environment or the platform and holds it to that with a case (17.2 to 17.4); the longest line any case of this section prints is 61 columns, far below 400, and the text they print is ASCII. No network; everything the cases replace is restored (the two class attributes of A1, and the instance's `handle_intent` through `monkeypatch`).

| Case | Covers | Without A2's change (on `a6c19818`) |
|---|---|---|
| `test_the_report_command_prints_the_saved_report_as_text[plain, closing-tag, style-tag]` | A saved report whose first summary is plain, holds `[/b]`, or holds a matched style tag; `/scout report` prints the status line and then the digest, equal to what `_load_latest_report` returns, scores included | `[plain]` and `[style-tag]` fail at the equality assert (the score tags, and the style tags, are gone); `[closing-tag]` raises `MarkupError` out of `cmd_scout` |
| `test_the_search_command_prints_what_the_model_wrote_as_text[plain, closing-tag, style-tag]` | `/scout` over a model answer of two classification blocks with that summary: both are classified, stored and notified (premise), and the printed digest holds the summary once per finding and both score tags | `[plain]` and `[style-tag]` fail at the count assert; `[closing-tag]` raises `MarkupError` |
| `test_a_failure_whose_message_holds_markup_prints_as_text[closing-tag, style-tag]` | `handle_intent` stubbed to raise a `RuntimeError` whose message holds `[/b]` or a matched tag: the line `Scout error: <message>` prints literally and starts red (`\x1b[31m`, on a forced terminal) | `[closing-tag]` raises `MarkupError` out of the handler; `[style-tag]` fails at its first assert (the tag text is dropped) |

A1's 8 cases pass on both trees (their console takes `**kw`).

### 16.5 Mutation rows 16 to 19 (each Line occurs once, stripped, in `commands_knowledge.py` after A2)

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| 16 | A2 | src/probos/experience/commands/commands_knowledge.py | `console.print(output, markup=False)` | `console.print(output)` | the 3 report cases and the 3 search cases (6) |
| 17 | A2 | src/probos/experience/commands/commands_knowledge.py | `console.print(f"Scout error: {e}", style="red", markup=False)` | `console.print(f"Scout error: {e}", style="red")` | the 2 failure cases (2) |
| 18 | A2 | src/probos/experience/commands/commands_knowledge.py | `console.print(f"Scout error: {e}", style="red", markup=False)` | `console.print(f"Scout error: {e}", markup=False)` | the same 2, at the red-start assert, and A3's 8 (10) |
| 19 | A2 | src/probos/experience/commands/commands_knowledge.py | `console.print(f"Scout error: {e}", style="red", markup=False)` | `console.print(f"Scout error: {type(e).__name__}", style="red", markup=False)` | the same 2 and A3's 8 (10) |

The Architect ran each row in memory with a stand-in runner (the vector 6, 2, 2, 2); under pytest it is expected, and the orchestrator's run on the two files as A2 leaves them is the campaign of record for rows 16 to 19 (mark the base tree and each file's sha256; rerun all four if either differs). Rows 1 to 8 mutate no line A2 touches or adds and run through the first new file, which A2 does not change, so their vector is unchanged. Rows 9 to 15 mutate lines of `scout.py` that A2 does not touch, but they run through A1's file, which A2 extends: A2's cases fail on the same mutants, so over the 16 cases their vector is 9, 6, 8, 8, 1, 8, 6, as the table of 15.5 now says.

### 16.6 Recorded limit L11

- **L11 (the same text through another renderer).** The natural-language route and `/plan` print a node's result through `render_dag_result` (`panels.py:704-767`; printed at `renderer.py:512`, `:615` and `commands_plan.py:182`), whose `_format_result` (`panels.py:597-638`, called at `:741`) puts the first 500 characters of a string result into a markup string and so into a `Panel` with markup on. Measured (Rich 15.0.0, a real console, a Scout digest as the node's result): the `[score: 4.5]` tag is dropped, and an unmatched closing tag within the first 500 characters raises `MarkupError`; a node's `error` and the `reflection` (`panels.py:736`, `:752`) have the same shape (read, not run). The shell's error lines (`shell.py:216`, `:350`, `:364`) print the exception as markup and so re-raise a `MarkupError` (measured on their exact f-strings), which would end `run()` (read; the REPL was not run), and `dag.response` is printed as markup at `renderer.py:130`, `:135` and `commands_plan.py:73`, `:78`. It predates BF-935 and A1, it concerns every agent's text and not the Scout's, and a renderer shared by every agent needs its own contract, so A2 does not change it. What A1 changed for it: `scout_report` over natural language now returns the saved text verbatim (before, a digest rebuilt from the model's answer), so the saved text reaches this renderer whenever the Captain asks for the report in words, within its first 500 characters. `/scout` and `/scout report`, in the shell and in the HXI chat route (`api.py:100` runs the same command over a real console), are fixed by A2. Notification, Discord, Ward Room, MCP and A2A text is not printed through Rich (`rg -n "notification_queue|NotificationQueue|\.notifications\b|get_unread|drain_notif" src/probos/experience` finds nothing; other packages not enumerated). The digest is Discord-flavoured Markdown and the shell prints it as text, as it always has; rendering it as Markdown is a display choice, not a defect (L10). Follow-ups recommended, not filed here (run the three-source BF enumeration at filing time): escape what `_format_result`, `render_dag_result` and the shell's error lines interpolate into markup, with a real-console test beside each; and, apart, the Markdown rendering of the digest.

### 16.7 Verified (2026-11-11, the Architect; read-only, scripts in memory over temporary directories removed afterwards; no pytest and no repository test)

- **F4 reproduced and fixed.** The A1 world with the real `cmd_scout` over a real `Console(file=StringIO())`, run on `a6c19818` with the A2 cases: 8 of A2's 8 fail (the plain, style-tag and `[closing-tag]` rows as 16.4 says: `MarkupError: closing tag '[/b]' at position 31 doesn't match any open tag` for the report and the search, `... at position 39 ...` for the failure line); with the A2 hunk applied in memory: 16 of 16 pass (A1's 8 and A2's 8); the A2 hunk with A1's file as it was: 8 of 8 pass. The class attributes the cases replace were identical before and after every run.
- **Rich (15.0.0).** Over a real console with markup on, `markup=False` and `escape`: `[/b]` raises with markup on and prints with the other two; `[bold red]Rich[/bold red]` and `[score: 4.5]` and `[x]` are dropped with markup on and printed with the other two; `:rocket:` and `:+1:` convert in all three; `C:\tmp\[draft]` loses a backslash with markup on and prints as written with `markup=False`; a text ending in a backslash prints doubled with `escape`; `None`, a dict and a list print as before with `markup=False`; `escape(None)` raises `TypeError`; on a forced terminal `style="red", markup=False` starts the line with `\x1b[31m` and the highlighter colours numbers and URLs; the four wrappers `[red]Scout error: {}[/red]`, `Command error`, `Error` and `Processing error` each raise `MarkupError` for the message `closing tag '[/b]' at position 31 doesn't match any open tag`.
- **The sentences (F5).** The commands and findings of 15.7 (corrected) and this list: A case-sensitive regular-expression scan (the grep tool; re-run in Python over the blob) of the contract at `a6c19818` for `overrid|42 match|35 files|async def decide|subclass|mixin|Mixin|UnreadableListGuard|_FetchGatedMixin` found lines 738 and 792 only; for `decide` 12 lines (7, 726, 738, 743, 748, 753, 774, 780, 791, 792, 793, 799), of which only 738 and 792 name another class's `decide` (793 is A1's absence claim about the tests that call `.decide(`); 738 states no count and does not say "subclass", and its classification holds against the four methods (read), so it stays; `git grep -n -E "42 matches in 35|35 files" a6c19818 -- prompts/bf-935-scout-within-run-dedup.md DECISIONS.md PROGRESS.md` found line 792 and an unrelated entry of DECISIONS.md (line 12777); a line-window scan of DECISIONS.md 1640 to 1670 and PROGRESS.md 1 to 20 for `decide|overrid|<n> matches in <n> files` found only `ScoutAgent.decide`. The orchestrator's PR body draft and the A1 commit message state no census.
- **Absence Verified.** CLAIM: no existing test pins the `Scout error` line or the markup of the status line. RUN: `rg -n "cmd_scout|Scout error|Running scout" tests`. FOUND: the A1 file (a `print` lambda that takes `**kw`), `tests/test_commands_knowledge.py:74-75` (no pool: returns before the changed lines) and `tests/fixtures/ad1343_seam_registry.py:173`. HOLDS: yes. CLAIM: no class of `src/probos` defines a `print` that would reject `markup=`. RUN: `rg -n "def print\(|class \w*Console\w*\(" src/probos`. FOUND: nothing. HOLDS: yes. CLAIM: `cmd_scout` has no caller but the shell's handler table, `_cmd_scout` and, through the shell, the HXI route. RUN: `rg -n "cmd_scout|commands_knowledge" src`. FOUND: `shell.py:20`, `:311-315`, `:550-562` and the module itself. HOLDS: yes (`api.py:100` constructs a `ProbOSShell`).

### 16.8 Diff Reviewer: properties to verify for A2

1. In `cmd_scout`, the result print and the failure print are the only changed lines of `src`, they print with `markup=False`, and the failure line keeps `style="red"`; no import is added; `Running scout ...` and every other line are unchanged. A1's property 6 said `cmd_scout` was unchanged by A1: it was; A2 changes these two prints.
2. The 8 new cases fail on `a6c19818` where 16.4 says and pass after; A1's 8 pass on both; each row of 16.5 is killed as tabulated. Run them, with the real console, before and after.
3. The new cases build their world with `tmp_path` semantics, restore what they replace (the two class attributes of A1 and the instance's `handle_intent`) and pass in one process after each existing G2 file and before it.
4. No existing test changes except A1's helpers gaining a defaulted `summary` argument and the imports; no `src` file other than `commands_knowledge.py`.
5. L11 is recorded with its measured reach; a finding on the natural-language renderer that goes beyond 16.6 (an effect on Scout text that A2's lines cause, or an ordinary-reach case 16.6 does not name) is new; the renderer's behaviour for every agent is not A2's.
6. The corrected census sentence is reproducible by the commands it names, at the revisions it names, and states nothing it did not run.

### 16.9 Acceptance for A2

- GA1 passes (16 passed at A2, 24 from A3; 8 failed and 8 passed on `a6c19818` with the file as A2 left it), G2 passes (322 passed at A2, 330 from A3), G3 is regenerated and green, rows 1 to 8 are rerun (expected unchanged), rows 9 to 15 are rerun (9, 6, 8, 8, 1, 8, 6 over the 16 cases of A2 and over the 24 of A3, as 15.5 and 17.5 say) and rows 16 to 19 are killed as tabulated (rows 18 and 19: over the 24 cases of A3, 17.5).
- `/scout` and `/scout report` print the Scout's text and a failure message as text over a real Rich console: no `MarkupError`, no dropped score tag, the failure line red.
- The census sentence of 15.7 states only what was run; L11 is recorded.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 17. Amendment A3 (review round 3, 2026-11-11)

### 17.1 The blocks

1. `tests/test_bf935_scout_report_display.py` (A1's file): `import builtins`; the helper `_console` gives `Console` all eight settings that Rich reads from the environment or the platform when it is not given them, and its docstring and comment say only what that does; one docstring sentence; the constants `RICH_READS`, `ENVIRONMENTS` and `LONG_FAILURE` and one parametrized case of 8 at the end (17.4). No other line.
2. PROGRESS.md (a bullet), DECISIONS.md (G6 and the residual line), the regenerated ledger (G3) and this contract's own edits: the counts A3 moves (the header, M0, G2, GA1, 15.3, 15.4, 15.9, 16.3, 16.9 and the general acceptance bullet), the sentence of 16.4 that described the console, and rows 18 and 19 of 16.5.
3. No `src` line and no other test file: the blobs of `scout.py`, `commands_knowledge.py` and `tests/test_bf935_scout_within_run_dedup.py` are A2's.
4. The commit message: `BF-935 A3: the display test console reads nothing from the environment or the platform, and a case holds it to that (#1674)`.

### 17.2 D9. The display test console reads nothing from its surroundings (correctness, safety, compatibility, fit, reversibility, validation cost)

**What it was.** A2's `_console` gave `Console` `width=400`, `force_terminal`, `no_color`, `color_system` and `legacy_windows`, and its comment said that nothing wraps and that the colour codes are a terminal's whatever the environment sets. `Console.size` returns the pinned size only when both `width` and `height` are given; otherwise a dumb terminal (`TERM` dumb or unknown) answers 80 x 25 (`console.py:1015`), so under `TERM=dumb` the colour console was 80 columns wide and a failure line of 150 characters printed on 3 lines (round 3, F6, reproduced; so did mine). The helper also left `force_jupyter` open: in a notebook kernel (builtins `get_ipython` defined, `_is_jupyter` at `console.py:505-521`) both consoles sent their render to the notebook and the buffer stayed empty. The 16 cases passed in every environment tried because none prints a line over 80 columns through the colour console and none ran in a kernel; the sentence was false, not the cases.

**The reads.** By command (17.7): the environment names and platform probes `Console` makes in Rich 15.0.0, when each is reached, what it can change in what the cases compare, and what closes it.

| Read | Reached when it is not given | What it can change in what the cases compare | Closed by | Ids that fail without it |
|---|---|---|---|---|
| `COLUMNS` (`:685`, `:1030`), `LINES` (`:689`, `:1033`), `TERM` dumb or unknown (`:986`, used by `size` at `:1015`), `os.get_terminal_size` on the standard streams (`:1024`), `JUPYTER_COLUMNS` and `JUPYTER_LINES` (`:660`, `:666`, notebook only) | `__init__` and `size`, unless BOTH dimensions are given | where a line wraps (F6) | `width=400` and `height=25` | `width`: every id; `height`: `dumb-terminal`, `narrow-terminal` |
| builtins `get_ipython` (`:657`), `DATABRICKS_RUNTIME_VERSION` (`:515`, reached only when `get_ipython` is defined) | `__init__`, unless `force_jupyter` is given | the render goes to the notebook's display and the buffer stays empty | `force_jupyter=False` | `notebook` |
| `FORCE_COLOR` (`:964`), `TTY_COMPATIBLE` (`:955`), `file.isatty()` (`:969`), an IDLE check on `sys.stdin` | `is_terminal`, unless `force_terminal` is given | whether the console is a terminal, which decides the dumb-terminal fallbacks above | `force_terminal=colour` | every id |
| `NO_COLOR` (`:728`) | `no_color`, unless given | the codes are stripped from the colour console | `no_color=False` | `no-colour` |
| `COLORTERM` (`:805`), `TERM` (`:808`), `get_windows_console_features` (`:798`) | `color_system="auto"` | which colour system, and none under a dumb terminal | `color_system="standard"` for colour, `None` for plain | `dumb-terminal`, `forced-colour`, and every id on a Windows host |
| `WINDOWS` and `get_windows_console_features().vt`, through `detect_legacy_windows` (`:576-578`, called at `:679`) | `legacy_windows`, unless given | the width less one (`size`), hyperlinks, the legacy renderer; on a Windows host with output that is not a console the real answer is True | `legacy_windows=False` | `old-windows-console` |
| `TTY_INTERACTIVE` (`:731`), `TERM` (through `is_dumb_terminal`, `:739`) | `is_interactive`, unless `force_interactive` is given | nothing a case compares: `is_interactive` is read only by `Live` (`live.py:283`) and `Progress` (`progress.py:1177`), and `is_dumb_terminal` by `Console.control` (`console.py:1616`); `Console.print` reaches neither | `force_interactive=False`, so that the console reads nothing | every id but `dumb-terminal` |
| `UNICODE_VERSION` (Rich 14.3.3 only: absent from 13.0.0, 13.9.4 and 15.0.0) | the width of non-ASCII characters | nothing the cases compare: what they print is ASCII and the longest line is far below 400 columns | none; the case clears it | none |
| `Console.encoding` of an `io.StringIO` | `encoding` | nothing: a `StringIO` has no encoding and Rich takes `utf-8` | `file=buffer` | none |

**Options.**

| # | Option | Judgement |
|---|---|---|
| 1 | The eight settings given, and one parametrized case that defines its surroundings in full (chosen) | The console reads nothing (recording environment, 17.7); the case fails without any one argument (17.5); documented arguments only, accepted by Rich 13.0.0 to 15.0.0 |
| 2 | `Console(..., _environ={})` | A private parameter; it reaches no `get_ipython`, `WINDOWS`, `os.get_terminal_size` or `os.getenv` probe, and a Rich without it would fail every case at construction |
| 3 | Only `height=25` (the reviewer's smallest fix) | Closes the dumb-terminal hole; leaves the notebook hole and two reads (A2's helper differs from the baseline in 4 of 38 single settings on the colour console and 1 on the plain one) |
| 4 | A fixture that sets a hostile environment for every case | Hides which setting a failure came from and changes cases that print nothing through Rich |
| 5 | A weaker sentence and no change to the helper | Leaves two measured holes for the next long message |

**What it changes.** The helper's arguments and comment, and one case. The cases of A1 and A2 are not edited; their console is the same object in every environment, which the new case checks, so what they compare cannot depend on the environment.

### 17.3 Gates

- **GA1.** `PY -m pytest tests/test_bf935_scout_report_display.py -q -n 0 -p no:randomly`. **Expected: 24 passed.** With the file as A3 leaves it and the helper's `Console(...)` call as A2 left it (the five arguments of 16.4): the 8 cases of A3 fail (each at its first settings assert: the dimension assert, or the one for a notebook, a session, an old Windows console or `NO_COLOR`; measured) and the 16 others pass.
- **G2** (section 4) totals 330 (290 + 16 + 24). **G3** is run again after the tracker pairs.
- No gate is added. A3 adds no import of `probos`, call into `src`, write or class, so the architecture check, the layer test, the effect and file-write censuses and the AD-1343 tests are expected unchanged, not run.
- Run the file also under a hostile outer environment (for example `TERM=dumb COLUMNS=20 LINES=5 NO_COLOR=1 FORCE_COLOR=1 TTY_COMPATIBLE=0`): 24 passed, as in every environment the Architect tried (17.7).

### 17.4 Tests (one parametrized case of 8 at the end of `tests/test_bf935_scout_report_display.py`)

`test_the_display_console_reads_nothing_from_its_surroundings[<id>]`: the case clears the twelve variables Rich 13 to 15 reads (`RICH_READS`), sets only its own, deletes `get_ipython` from builtins (or defines a notebook kernel's), and replaces `rich.console.detect_legacy_windows` (a module function present in Rich 13.0.0 to 15.0.0) by a constant, so the outer environment and the host's platform cannot change it. For the plain and the colour console it asserts the settings (`size`, `is_terminal`, `color_system`, `is_jupyter`, `is_interactive`, `legacy_windows`, `no_color`) and that a literal line of 151 characters prints as one line; then it runs the real `cmd_scout` with a failing `handle_intent` through the colour console and asserts that the status line and the failure line are written whole, the failure line red. The seam it crosses is the one F6 reproduced.

| Id | The surroundings | What Rich would otherwise do |
|---|---|---|
| `unset` | none of the twelve variables | read the real terminal (none, when captured); on a Windows host the real console probe |
| `dumb-terminal` | `TERM=dumb` | 80 x 25 and no colour (F6) |
| `narrow-terminal` | `COLUMNS=20`, `LINES=5` | a 20-column console, a 5-line height |
| `no-colour` | `NO_COLOR=1` | strip the codes |
| `forced-colour` | `FORCE_COLOR=1`, `TTY_INTERACTIVE=1`, `TERM=xterm-256color`, `COLORTERM=truecolor` | a terminal on a buffer, an interactive session, 24-bit colour |
| `not-a-terminal` | `TTY_COMPATIBLE=0` | not a terminal |
| `notebook` | a kernel's `get_ipython`, `JUPYTER_COLUMNS=20`, `JUPYTER_LINES=5` | send the render to the notebook |
| `old-windows-console` | `detect_legacy_windows()` answers True | width less one, no hyperlinks |

### 17.5 Mutation rows 20 to 27 (each Line occurs once, stripped, in the helper of `tests/test_bf935_scout_report_display.py` after A3; each mutant is the same argument given its default, which is the argument removed)

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| 20 | A3 | tests/test_bf935_scout_report_display.py | `width=400,` | `width=None,` | all 8 ids, at the size assert (8) |
| 21 | A3 | tests/test_bf935_scout_report_display.py | `height=25,` | `height=None,` | `dumb-terminal` and `narrow-terminal`, at the size assert (2) |
| 22 | A3 | tests/test_bf935_scout_report_display.py | `force_terminal=colour,` | `force_terminal=None,` | all 8 ids, at the terminal assert (8) |
| 23 | A3 | tests/test_bf935_scout_report_display.py | `force_jupyter=False,` | `force_jupyter=None,` | `notebook`, at the notebook assert (1) |
| 24 | A3 | tests/test_bf935_scout_report_display.py | `force_interactive=False,` | `force_interactive=None,` | every id but `dumb-terminal`, at the interactive assert (7) |
| 25 | A3 | tests/test_bf935_scout_report_display.py | `no_color=False,` | `no_color=None,` | `no-colour`, at the `NO_COLOR` assert (1) |
| 26 | A3 | tests/test_bf935_scout_report_display.py | `color_system="standard" if colour else None,` | `color_system="auto",` | all 8 ids on a Windows host, at the colour assert (8) |
| 27 | A3 | tests/test_bf935_scout_report_display.py | `legacy_windows=False,` | `legacy_windows=None,` | `old-windows-console`, at the legacy assert (1) |

The vector for rows 20 to 27 is 8, 2, 8, 1, 7, 1, 8, 1 (the Architect's stand-in runner over the whole 24-case file: no case of A1 or A2 fails on any of them, so each count is A3's ids alone). Two counts depend on how the suite runs: row 21's 2 is for a captured run, where Rich's size fallback is 80 x 25 (in a terminal run the real height also fails the ids that set no `LINES`), and row 26's 8 is for a Windows host, where the real console probe answers 8-bit colour for output that is not a console; on a POSIX host the probe is not reached and row 26 is expected to be killed by `dumb-terminal` and `forced-colour` alone (2; not run, this host is Windows; the sweep with `rich.console.WINDOWS` set False found the helper unchanged, 17.7). Rows 9 to 15 over the 24 cases: 9, 6, 8, 8, 1, 8, 6 (unchanged: A3's case does not reach `scout.py`); rows 16 to 19: 6, 2, 10, 10 (the case's failure seam also fails on rows 18 and 19, which change the failure line's colour and its text). The Architect ran each row in memory; under pytest it is expected, and the orchestrator's run on the files as A3 leaves them is the campaign of record for the three tables (mark the base tree and each file's sha256; rerun all rows of a table if a file differs). Rows 1 to 8 run through the first new file, which A3 does not change.

### 17.6 Recorded limit L12

- **L12 (the display test console: what is simulated and what is only pinned).** The surroundings the case defines are the twelve variables Rich 13 to 15 reads, a notebook kernel (`get_ipython` in builtins) and a Windows console without VT support (`rich.console.detect_legacy_windows`, a module function present in Rich 13.0.0 to 15.0.0). Pinned by the arguments and held only by the settings asserts, not simulated: the size of the real terminal (`os.get_terminal_size`; patching it would change every library's answer during the case), the Win32 console probe (`get_windows_console_features`, reached only when `color_system` or `legacy_windows` is not given, and never on a POSIX host), the IDLE check on `sys.stdin` and `file.isatty()` (reached only when `force_terminal` is not given). Versions: the helper and the case pass on Rich 13.0.0, 13.9.4, 14.3.3 and 15.0.0 (wheels executed in memory); the versions between and any later one were not run, `pyproject.toml` has no upper bound, a Rich that renames one of the eight arguments fails every case that builds a console, loudly, at construction, and a Rich that reads a new variable is caught only if it changes what the case prints (a 151-character line, the status line and the failure line, on both consoles). Counts: rows 21 and 26 of 17.5 depend on the host and on a captured run, as stated there. The case does not use `Console._environ` (private; it would not reach `get_ipython`, `WINDOWS` or the terminal probes).

### 17.7 Verified (2026-11-11, the Architect; read-only, scripts in memory; no pytest and no repository test)

- **The reads and the matrix (Rich 15.0.0).** Static: scans of `rich/*.py` for `os.environ|getenv|_environ|sys.platform|os.name|get_terminal_size|WINDOWS` (`console.py` reads at `:515`, `:660`, `:666`, `:685`, `:689`, `:728`, `:731`, `:805`, `:808`, `:955`, `:964`, `:986`, `:1030`, `:1033` and probes at `:657`, `:679`, `:798`, `:969`, `:1024`; other modules mention `WINDOWS` or `sys.platform` for their own rendering) and for `UNICODE_VERSION|from os import|environ.get|environ[` (only `console.py`). Dynamic: a recording `Console._environ` (a dict subclass), patched `os.get_terminal_size`, `os.getenv`, `get_windows_console_features` and `detect_legacy_windows`, and a recording `isatty`, over the construction, the three print shapes of `cmd_scout`, `size`, `width`, `options` and `encoding`: the unpinned `Console(file=buffer)` read `COLUMNS`, `FORCE_COLOR`, `LINES`, `NO_COLOR`, `TERM`, `TTY_COMPATIBLE`, `TTY_INTERACTIVE` and probed `detect_legacy_windows`, `isatty`, `get_windows_console_features` and `os.get_terminal_size`; A2's helper read `COLUMNS`, `LINES`, `TERM`, `TTY_INTERACTIVE` and `os.get_terminal_size`; A3's helper (the eight arguments of 17.2) read nothing; without `force_interactive=False` it read `TTY_INTERACTIVE` (and `TERM` for the colour console). The matrix: 38 single settings (33 values of the 11 variables and 5 platform modes: the native Windows host, POSIX with `rich.console.WINDOWS` set False, a notebook kernel, an old and a modern Windows console) and 4000 random combinations x 2 consoles, output compared with A3's own baseline: the unpinned console differs in 37 of 38 settings (plain) and 38 of 38 (colour); A2's helper in 1 (a notebook kernel; plain) and 4 (`TERM` dumb, unknown, `DUMB` and a notebook kernel; colour); A3's helper in 0 of 38 and in 0 of the 4000 x 2.
- **Rich 13.0.0, 13.9.4 and 14.3.3.** Each wheel fetched from PyPI into memory and imported by a path hook in a child process (`rich.console.__file__` printed `zip:rich/console.py`). The names a regex scan of each wheel finds for `.get` and `getenv` reads: 13.0.0 and 13.9.4 `COLORTERM`, `COLUMNS`, `DATABRICKS_RUNTIME_VERSION`, `FORCE_COLOR`, `JUPYTER_COLUMNS`, `JUPYTER_LINES`, `LINES`, `TERM`; 14.3.3 those with `NO_COLOR`, `TTY_COMPATIBLE`, `TTY_INTERACTIVE` and `UNICODE_VERSION` (the scan matches `.get` and `getenv` forms only, so for 13.x it is a lower bound; the matrix, which sets `NO_COLOR`, is the evidence for it). The sweep (31 settings, 600 random combinations x 2 consoles) on each wheel: the unpinned console differs in 31 of 31 settings on both consoles, A2's helper in 1 (plain) and 4 (colour), A3's helper in 0 and 0. The 24 cases: 24 passed on each, under the default environment and under `TERM=dumb COLUMNS=20 LINES=5 NO_COLOR=1 FORCE_COLOR=1 TTY_COMPATIBLE=0 UNICODE_VERSION=4.1.0`.
- **The A3 file** (the pairs applied in memory to the LF blobs of `7244c643`, run by a stand-in runner): 24 passed on Rich 15.0.0, and under each of 12 outer environments (the default; `TERM=dumb`; `TERM=unknown`; `NO_COLOR=1`; `FORCE_COLOR=1`; `COLUMNS=20`; `LINES=5`; `TERM=dumb COLUMNS=20 LINES=5 NO_COLOR=1 FORCE_COLOR=1 TTY_COMPATIBLE=0`; `TTY_COMPATIBLE=1`; `FORCE_COLOR=3 COLORTERM=truecolor TERM=xterm-256color`; `JUPYTER_COLUMNS=20 JUPYTER_LINES=5`; `TTY_INTERACTIVE=1 UNICODE_VERSION=4.1.0`). With `_console` as A2 left it and the case laid over it: 16 passed, 8 failed (all 8 ids, each at its first settings assert). The 8 cases of A2 print at most 61 columns on a line and no non-ASCII character; the case's longest line is 164 columns (the red failure line).
- **Mutants** (the same runner, over the whole 24-case file): rows 20 to 27: 8, 2, 8, 1, 7, 1, 8, 1 failing cases, none of them a case of A1 or A2; rows 9 to 15: 9, 6, 8, 8, 1, 8, 6; rows 16 to 19: 6, 2, 10, 10; every count equals the one the tables state after the pairs.
- **The anchors of 16.6.** The 13 line citations of L11 (`panels.py:704`, `:597`, `:741`; `renderer.py:512`, `:615`, `:130`, `:135`; `commands_plan.py:182`, `:73`, `:78`; `shell.py:216`, `:350`, `:364`) read at the head: all 13 hold.
- **Absence Verified.** CLAIM: the sentence that the console does not depend on the environment is made in two places only. RUN: `git grep -n -E "width=400|width 400|400 columns|whatever the environment|environment cannot change" 7244c643 -- . ':!*.json'`. FOUND: the contract line 846, `tests/test_bf935_scout_report_display.py` lines 201 and 203, and two docstrings about Python's int-conversion cap (`tests/test_ad1270f_duration_scheduler.py:811`, `tests/test_ad1270f_gen_file_durations.py:671`). HOLDS: yes. CLAIM: no other test file of the BF-935 delta builds a Rich console or reads the environment. RUN: `git grep -n -E "Console\(" 7244c643 -- tests/test_bf935_scout_within_run_dedup.py tests/test_bf935_scout_report_display.py tests/test_bf214_scout_seen_deferral.py` and an in-memory scan of the two others for `Console(|environ|TERM|isatty|getenv|print(`. FOUND: `tests/test_bf935_scout_report_display.py:203` only; no hit in the two others. HOLDS: yes. CLAIM: `Console.print` does not read `is_interactive`. RUN: an in-memory scan of `rich/*.py` (15.0.0) for `is_interactive` and `is_dumb_terminal`. FOUND: `is_interactive`: `console.py:738` (the assignment), `live.py:283`, `progress.py:1177`; `is_dumb_terminal`: `console.py:739`, `:793`, `:979`, `:1015`, `:1616` (`Console.control`) and `live.py:269`. HOLDS: yes. CLAIM: Rich 15.0.0 does not read `UNICODE_VERSION`. RUN: a search of `rich/*.py` for `UNICODE_VERSION|from os import|import environ|environ\.get|environ\[`. FOUND: the `environ.get` reads of `console.py` (the eleven names) and `from os import PathLike` (`console.py:10`, `progress.py:14`). HOLDS: yes (14.3.3 does read it: the scan of that wheel).

### 17.8 Diff Reviewer: properties to verify for A3

1. In `tests/test_bf935_scout_report_display.py` only the imports (`builtins`), one docstring sentence, `_console` and the end of the file change; no `src` file and no other test file; the A1 and A2 cases are byte-identical.
2. `_console` gives all eight settings of `Console.__init__` whose default Rich reads (17.2); run, with a recording `Console._environ`, `os.get_terminal_size`, `os.getenv`, `get_windows_console_features`, `detect_legacy_windows` and `isatty`, it reads nothing; find a read the table of 17.2 lacks, or a `Console` argument whose default reads the environment that `_console` does not give.
3. The 8 new cases pass in the default environment and under a hostile outer one (17.3), and fail with the helper as A2 left it; each row of 17.5 is killed as tabulated by cases that run in the default environment, not only when the shell exports `TERM=dumb`.
4. The case restores everything it changes (`monkeypatch` only: twelve variables, builtins `get_ipython`, `rich.console.detect_legacy_windows`, the instance's `handle_intent`) and passes in one process after each existing G2 file and before it.
5. The counts the pairs change (24, 330, plus 40; rows 18 and 19: 10) are those a run prints; no sentence of the contract still says the console is configured as A2 left it.
6. L12 says only what was run; a claim of 17.2 to 17.6 that no command in 17.7 supports is a finding.

### 17.9 Acceptance for A3

- GA1 passes (24 passed; the 8 new cases fail with the helper as A2 left it), G2 passes (330 passed), G3 is regenerated and green, rows 1 to 8 and 9 to 15 are rerun (expected unchanged), rows 16 to 19 and 20 to 27 are killed as tabulated.
- `_console` reads nothing from the environment or the platform that could change what a case compares; a case fails when any of its eight arguments is removed.
- L12 is recorded; no `src` file changed.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
