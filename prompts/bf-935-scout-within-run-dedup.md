# BF-935 (#1674): A Scout run lists each repository once, however many of its six topic searches return it

**Drafted by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge was logged out), 2026-11-11
**Revised by:** `Architect` (the same fallback), 2026-11-11, r2: after the orchestrator's oracle found that G2 as r1 wrote it fails (consult `consult-bf935-a1`; the decision is in `answer-bf935-a1.txt`).
**What changed in r2.** One defect, found by the oracle, and not BF-935's own: `tests/test_bf214_scout_seen_deferral.py` replaces `ScoutAgent._data_dir` on the class in three tests (`type(agent)._data_dir = property(...)`; lines 79, 112 and 138 of the base) and nothing restores it, so every `ScoutAgent` built later in the same process reads the last test's `tmp_path`. Measured by the orchestrator: G2 as r1 wrote it fails 3 existing cases (`tests/test_quality_hardening.py::TestScoutDataDirectory`; the same 3 fail on the base without BF-935), and the new file fails 6 of its 16 cases when it runs after bf214, as it does in suite order (r1's G2 listed it first, which hid that). r2: (1) M1 also carries **P1-1 to P1-3**: the three tests install the property with `monkeypatch.setattr`, which restores it at teardown (test-only; no assertion and no product line changes; measured: bf214 then the new file 26 passed, G2 306 passed with the new file first or last); (2) G2 lists the new file last, states its total (306 = 290 + 16) and gains a third command, the leak's reproduction; (3) D6 records the choice, and sections 2, 5, 7.3 (the tracker text), 8, 9 (the prose under the table), 10 (L8), 11, 12, 13 and 14 name the fix; (4) the base is now `fe488971`. N1-1, P2-1 to P2-7, N2-1 and the tables of sections 6 and 9 are as in r1.
**Status:** ready to build on `origin/main` `fe488971` (the merge of BF-940 slice 4, PR #1783, merged 2026-11-12T00:12:22Z). **Oracle:** r1 was checked by an in-memory script without pytest (section 11). The orchestrator then built it by tool on `8a24dfba` (that PR's head; the four files below have the same blobs on `fe488971`) and ran pytest: G1 6 passed and 10 xfailed at M1, `--runxfail` fails the 10 at the asserts section 6 names, the 8 mutants of section 9 fail the cases it lists (4, 1, 6, 6, 1, 1, 4, 1), the architecture check is clean, M0 is 290. G2 as r1 wrote it failed 3 existing tests: the defect r2 repairs.
**Base blobs (`fe488971`; read from GitHub on 2026-11-11, equal to those of `8a24dfba`):** `src/probos/cognitive/scout.py` `9b2cc9bcd0d8d334cb33c0228516abd70e3c97d6`, `tests/test_bf214_scout_seen_deferral.py` `8c3b29dbb44308d5f39aefddec33cb2e22fe8469`, `PROGRESS.md` `a10956172ac3cacc83b7ccf1dc5260aa08781705`, `DECISIONS.md` `a07c172b512ce69dc88f5819575b56de3a5c1689`.
**Dependencies:** none in code; before AD-1354 (#1672) and any Scout baseline, as the crew asked on #1674. **Tier:** STANDARD for M1 to M3. **Estimated tests:** one new file, 16 cases (6 pass, 10 xfail at M1); three existing tests edited (P1-1 to P1-3), none added. **BF number:** BF-935, held by #1674 (section 11); the bf214 fix carries no number of its own (D6). To be committed as `prompts/bf-935-scout-within-run-dedup.md`.

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

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. **M0:** on the head, record the collected count (`--collect-only -q`) of every existing file named in G2. Measured on `8a24dfba` (the same files on `fe488971`): 290 in all; per file `test_ad1346_admission_effect_census` 10, `test_ad1346_admission_file_write_census` 9, `test_ad1346_admission_service` 16, `test_ad398_crew_identity` 33, `test_ad632f_activation_triggers` 34, `test_ad647_process_chains` 8, `test_ad647b_chain_registry` 12, `test_ad648_post_capability_profiles` 14, `test_bf208_scout_duty_perceive` 5, `test_bf209_scout_chain_bypass` 4, `test_bf214_scout_seen_deferral` 10, `test_bf892_spawn_env_guard` 82, `test_bf925_guard_names` 14, `test_commands_knowledge` 7, `test_layer_boundaries` 3, `test_quality_hardening` 13, `test_scout` 16. The recorded M0 is binding; if it differs from this list the head moved: say so in the report, and expect G2's total to be M0's sum plus 16.

- **G1.** `PY -m pytest tests/test_bf935_scout_within_run_dedup.py -q -n 0 -p no:randomly`. **Expected: 6 passed** (the functions), **10 xfailed** (the class). The marker carries `raises=AssertionError, strict=True`: any other exception, or an XPASS, is a FAIL; any other count is a hard stop. Then once with `--runxfail`: each of the 10 must fail at the `assert` section 6 names, never at a premise line. P1-1 to P1-3 do not change G1 (it runs the new file alone).
- **G2.** (1) `PY -m pytest tests/test_scout.py tests/test_bf208_scout_duty_perceive.py tests/test_bf209_scout_chain_bypass.py tests/test_bf214_scout_seen_deferral.py tests/test_ad647_process_chains.py tests/test_ad647b_chain_registry.py tests/test_quality_hardening.py tests/test_ad398_crew_identity.py tests/test_ad632f_activation_triggers.py tests/test_ad648_post_capability_profiles.py tests/test_commands_knowledge.py tests/test_bf892_spawn_env_guard.py tests/test_ad1346_admission_service.py tests/test_ad1346_admission_effect_census.py tests/test_ad1346_admission_file_write_census.py tests/test_bf925_guard_names.py tests/test_layer_boundaries.py tests/test_bf935_scout_within_run_dedup.py -q -n 0 -p no:randomly` (the 11 files that `git grep -l -E "_pending_seen_repos|_repo_metadata|ScoutAgent|scout_search|_search_github|SCOUT_REPORT_CHAIN" -- tests` finds; `/scout`; the scans that read `scout.py` by syntax and the layer test: section 11; and the new file LAST, so that it runs after bf214, the order in which the leak of L8 showed). (2) `PY -P scripts/check_architecture_principles.py --check`. (3) The leak's reproduction: `PY -m pytest tests/test_bf214_scout_seen_deferral.py tests/test_bf935_scout_within_run_dedup.py -q -n 0 -p no:randomly`. **Expected:** (1) **306 passed**, 0 failed, 0 skipped, 0 xfailed: the new file 16 and the 17 existing files 290, their collected counts equal to M0; (2) clean; (3) **26 passed** (10 + 16; without P1-1 to P1-3 it prints `6 failed, 20 passed`).
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
- **L6 (the report).** `total_classified` counts findings answered absorb or visiting_officer, not repositories listed; the report holds the repeat count but not the listings or repository counts (the INFO line has them). A second run on the same day overwrites the day's file (unchanged), so `duplicate_listings` is the last run's.
- **L7.** Nothing here is a live-system claim except the probe's figures, quoted as the orchestrator's; my one read of the public search API is a shape check, with no figure.
- **L8 (class-level state left by another test).** `tests/test_bf214_scout_seen_deferral.py` replaced `ScoutAgent._data_dir` on the class in three tests and never restored it; P1-1 to P1-3 close it. What it needed: one process (or one xdist worker) running bf214 and then a test that reads a `ScoutAgent`'s directory: `TestScoutDataDirectory` (3 cases) and, from this BF, the new file (6 of its 16). `pyproject.toml:196` sets `-n 16 --dist=loadfile`, `scripts/run_test_gate.py:1765` defaults `--dist` to `loadfile`, and CI runs `-n auto` on top of that `addopts` (`.github/workflows/ci.yml:71`; read, not run), so whole files go to whichever worker is free, in collection order, and whether the two met on one worker was scheduling luck: the probability was not measured. What shows the rest is clean: section 11's scans of `tests/` (the only rebinding of a Scout or CognitiveAgent class attribute is bf214's three lines) and the new file run after each of the 17 files of G2, one process each (only bf214 broke it). What is not covered: no guard against a future leak (the detectors are the three `TestScoutDataDirectory` cases and the new file's guard cases, which fail only when a leaking file runs before them on the same worker), and the 5 other `type(x).attr =` sites and the 3 `__class__.__name__ =` sites in `tests/` were not read (none names a Scout class). A suite-wide autouse check that `ScoutAgent.__dict__` is unchanged after each test would close it; not done (suite-wide, outside this defect); file it if a second leak shows.

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

- G1, G2 and G3 pass as stated (G2: 306 passed, and 26 passed for the leak's reproduction), and the batch's broad gate is green with a receipt.
- **The crew's count check:** for N listings across M searches the output has one prompt block, one pending name and one finding per unique `full_name`, and `duplicate_listings` equals listings minus unique repositories (T1, T5). The issue's "one entry and one classification call" is read as one `REPO:` block in the single prompt `perceive` builds (`:511-514`); T5's model text answers one report per block shown.
- **The topic list is kept** on the entry and on each persisted finding, and is not in the prompt (T1, T5, G).
- **The cross-run `seen` and BF-214's deferral are unchanged** (G, the existing BF-214 tests); for a run with no repeat the prompt text and the pending names are the same as before (G).
- **How far back** is stated (section 1.4, L1, L5).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
