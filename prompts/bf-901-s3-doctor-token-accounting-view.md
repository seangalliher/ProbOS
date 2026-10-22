# BF-901 S3: the doctor shows what the journal says was spent, measured and estimated apart

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-21

**Status:** build-ready on the merged main. **Closes #1575** (slice S3 of S1 to S3). **Tier HIGH** (a field added to the doctor's public `CheckResult`, and the runner's rendering of every check; it is also the evidence #1575 closes on). It changes no code a cost-aware budget runs (AD-1208, AD-1323 to AD-1325). **Base:** `origin/main` after the BF-900 / BF-901 S1 / BF-901 S2 batch merges (drafted on its delivery tree, HEAD `96c0c730`, tree `305993682393802571dd9f83dc31923508bcac9a`). **Source:** the Architect's read-only consult of 2026-10-21.

**Tests:** one new file, `tests/test_bf901_s3_token_accounting_view.py`: **13 test cases in 11 test functions** (section 6). No existing test changes.

**Line endings:** every edited file's working copy is CRLF (`core.autocrlf=true`). The SEARCH blocks are written with LF; match and write with the file's own line endings.

---

## 0. What this slice anchors on in S2

| S2 text or symbol | Where | How S3 uses it |
|---|---|---|
| `journal.token_source TEXT NOT NULL DEFAULT ''` | `src/probos/cognitive/journal.py:46` (schema), `:215` (the warm-boot `ALTER`) | The reader's source column; a journal without it is read with an empty literal instead |
| `CognitiveJournal.record(..., token_source=...)` | `journal.py:375-402`, one commit per row `:426` | The tests write every row through it |
| `model="unknown"` at the attempt row, `or "unknown"` at the step row | `sub_task.py:595`, `:669` | Why a row with an empty model recorded after token sources began is a regression |
| The `st:` prefix of a chain step's `dag_node_id` | `sub_task.py:587`, `:659` | The "chain steps" split of the rows with no model |
| The PROGRESS head `**BF-901 S2 (2026-10-21), part of #1575 -- the journal records what each call cost, where the count came from, and the model that answered.**` | `PROGRESS.md:3` | S3's PROGRESS SEARCH |
| S2's DECISIONS line `- *Reversal.* Revert the BF-901 S2 commit. The added columns stay ...` | `DECISIONS.md:529`, followed by a blank line and `### Explicit delegation models, ...` (`:531`) | S3's DECISIONS SEARCH. The docs-only commit after S2's code commit inserts a *Validation of record* bullet **before** this line, so the block (this line, the blank, the next heading) is unchanged by it |

## 1. Problem

After S2 every journal row says where its count came from, but nothing shows it. #1575's acceptance asks that "the doctor or SIF shows tokens per tier, per intent and per day, measured and estimated reported separately", and that the live confirmation of the empty-model rows (1,272 on the vessel, 2026-10-16) be possible. Today:

- The only readers of spend are `CognitiveJournal.get_token_usage`, `get_token_usage_since` and `get_token_usage_by` (`journal.py:835-944`). They are methods of a started journal, whose `start()` creates the directory, migrates and creates tables (`:197-227`), so the doctor cannot use them. Their allowlist has no day and no source (`:909`). They sum measured and estimated together.
- The doctor (`src/probos/doctor/`) has no journal check, and its runner prints one line for an OK result, with remediation only on WARN or FAIL (`runner.py:144-152`). A breakdown cannot be shown on a healthy vessel.
- The rows with an empty `model` can only be counted by a hand query on a copy of the journal (S2 section 13).

## 2. Solution overview

- **Reader** (`src/probos/cognitive/journal_token_report.py`, new): `read_journal_token_report(conn)` runs on a connection its caller opened. It runs the journal's column list, one grouped scan and, when needed, one indexed count. It returns a report with one bucket per row (replayed, mock, measured, estimated, uncharged, other) per tier, per intent and per UTC day, the totals, and the rows that name no model. It writes, creates and migrates nothing.
- **Check** (`src/probos/doctor/checks/token_accounting_check.py`, new): opens `ctx.data_dir / "cognitive_journal.db"` through the ConnectionFactory's `read_only` open (BF-906's pattern). It returns OK with a one-line summary and the breakdown in `detail`, or WARN (see D3).
- **Doctor protocol and runner**: `CheckResult` gains `detail: str = ""` (last, defaulted). `_render` prints each `detail` line under the result on every outcome, after any remediation. An OK result still shows no remediation.
- **Registration**: after `crew_enrollment_check` in `doctor/checks/__init__.py`.

Live use, at the Captain's next restart: `probos doctor` prints, under `token_accounting`, the line `Rows naming no model: N (K chain steps), the last on YYYY-MM-DD; M since token sources began on YYYY-MM-DD.` That is S2's section 13 confirmation in one command. `M` must be 0.

## 3. Decisions

| # | Decision | Rejected alternatives, and why |
|---|---|---|
| D1 | **Surface:** a doctor check, plus `CheckResult.detail` (defaulted, last; the positional order is unchanged) printed under every outcome | One line only: cannot show the breakdown. A route on a new `CognitiveJournal` method: needs the running vessel and is not a one-line check at restart (considered, deferred; the reader can serve it later). A SIF check: SIF checks are synchronous invariants over in-memory structures (`sif.py:207-472`), not a place for a disk scan |
| D2 | **Read:** a new read-only reader on the caller's connection; the doctor opens it with `read_only=True` (SQLite `mode=ro`, `sqlite_factory.py:36`). The journal runs in rollback mode (`journal.py:204` sets only `foreign_keys`), so the read creates no side file and each statement holds a shared lock only while it runs. The doctor sets a 2 s busy timeout, as BF-906 does | Reuse `get_token_usage_by`: needs a started journal (it migrates and creates) and has no day or source. Copy the file first: up to 152 MB per run (`storage_declarations.py:82`); the read-only open is BF-906's precedent and the consult's read-only requirement |
| D3 | **Outcomes:** OK, or WARN when the journal cannot be read (`sqlite3.Error`) or when a row recorded at or after the earliest row that carries a token source names no model. Never FAIL. A missing file, no `journal` table, an empty table or a journal from before S2 all give OK | WARN on a share of `''` rows: a bypassed chain step records `''` with `unknown` on a healthy vessel (`sub_task.py:658-680`). WARN on estimated-only days: permanent on the proxy, which reports zeros (BF-680). FAIL: this is an account, not a component that breaks; FAIL would change `probos doctor`'s exit code |
| D4 | **Buckets**, tested in order: `replayed` (`cached <> 0`), `mock` (`model = 'mock'`), `measured`, `estimated`, `uncharged` (`token_source = ''`), `other`. Spend = measured + estimated | Count mock rows as measured: they are the mock client's fixed 32-token rows (#1575's evidence) and would distort a real vessel's measured share. Fold unknown labels into `uncharged`: a new label would vanish |
| D5 | **Dimensions:** `tier`, `intent`, UTC day via `strftime('%Y-%m-%d', timestamp, 'unixepoch')` (`timestamp` is Unix epoch REAL, `journal.py:24`). Three one-dimensional groupings from one scan; exact integer sums, thousands separators, no rounding; every tier, the top 8 intents by spend, the newest 7 days, with a count of the rest | A tier x intent x day cube: unreadable on a terminal. Local time: the day boundary moves with the host |
| D6 | **The journal's `''` is not `crew_execution_usage`'s vocabulary.** Nothing in S3 passes a journal label to its validators (`crew_execution_usage.py:27-35`, which raise on `''`) | Map `''` to `mixed` or `estimated`: it means neither |
| D7 | **#1575's budget bullet (reclassification R-A):** met for AD-1208 by S1's test; the AD-1323 approval card's missing provenance is filed as its own follow-up issue before #1575 closes, and linked in the closing comment | R-B (fix the card in S3): a governance-path change through the AD-1322 hook (`economic_judgment_organ.py:146`, `:869-876`), the loop's calls (`agentic_loop.py:1833`, `:1947`), `CostedCase` and the card, outside the doctor view. R-C (keep #1575 open): the view waits on a wording change. R-A weakens no control: the card behaves exactly as today |
| D8 | **Coverage stated in the view:** "journaled calls only (one-shot decisions and sub-task chain steps); the agentic loop writes no journal row" | Silent: the Captain would read the total as all spend. Journaling the loop: S2 section 9 and the consult's decision 4 keep it out; register item |

**#1575's acceptance, settled.**

| Bullet (quoted) | Settled by | Evidence |
|---|---|---|
| "The journal and chain traces carry the token source, and the doctor or SIF shows tokens per tier, per intent and per day, measured and estimated reported separately." | S2 (the columns), S3 (the view) | S2: `journal.py:46`, `:77`; U7, U10. S3: T1, T2, T10 |
| "AD-1208's `TurnCostBudget` and AD-1323 to AD-1325 read the same counts." | S1 | None reads the journal. AD-1208: `TurnCostBudget.record` reads the loop's result total and source (`turn_cost.py:245-252`). AD-1323: the organ's `note_charge` gets the loop's `result.total_tokens` (`agentic_loop.py:1833`, `:1947`), and `costed_case` builds `spent` from it (`economic_judgment_organ.py:878-899`). AD-1325: each completion spend records the loop's charged total and source (`agentic_loop.py:1229-1251`; `economic_calibration.py:36`). AD-1324: a pre-call prompt estimate, not spend (`tier_policy.py:385`, `:428`). The loop's estimator is S1's single owner (`test_the_loop_calls_the_shared_functions`, `test_the_moved_functions_return_the_base_integers`) |
| "A test proves that a budget decision made on estimated tokens says so." | S1 for AD-1208; D7 for AD-1323 | `tests/test_bf901_s1_token_accounting.py:359-373` (a real `AgenticLoop` reaches `token_budget` on an estimate; a real `TurnCostBudget` renders `" (usage estimated, not measured)"`, `turn_cost.py:79`, `:263-271`). The reply of a turn that files an AD-1323 ask carries that statement (`cognitive_agent.py:5039`, then `:5063-5066`); the card's rationale (`costed_continue_ask.py:33-37`, `:123-142`) and `CostedCase` (`economic_judgment_organ.py:709-721`) carry no source: the follow-up. AD-1325 stores the source per spend (`economic_calibration.py:36`, validated `:873-874`) |
| "Every journal row names the model that answered, or an explicit `unknown`, never an empty string. The degraded and failure paths behind the 1,272 empty rows are identified and fixed." | S2 (fixed, identified), S3 (live check) | S2: U3, U5, U6, U8; mutants C1, C5, C6, S1, S2; S2 section 1 (the chain-step sites). S3: T3 (a regression warns), T4 (rows before BF-901 are counted, split by chain step, not warned) |
| Tests: "a fake provider with usage, without usage, with a streamed reply and with a tool-call reply, plus one real-object test through `journal.record`" | S1, S2 | With usage: `test_openai_reply_with_usage_is_reported_and_measured`, `test_ollama_reply_with_counts_is_reported_and_measured`. Without: `test_openai_reply_without_a_usage_block_is_not_reported_and_is_estimated`, `test_ollama_reply_missing_prompt_eval_count_is_not_reported_and_is_estimated`. Tool call: `test_openai_tool_call_only_reply_with_zeros_is_charged_as_an_estimate`. Streamed: not applicable, ProbOS never streams (S1 section 2; re-verified, Absence Verified). Real object through `journal.record`: S2 U1 (the real `decide`), U7, U11. S3 adds the seam from the writer to the view (T1, T10) |

## 4. Milestones (about 30 Builder tool calls in all)

| M | Work | Focused check (`-n 0`; the orchestrator's worktree environment: `PYTHONPATH=<tree>/src`) |
|---|---|---|
| M1 (about 6 calls) | Sections 7.1 (`doctor/protocol.py`) and 7.2 (`doctor/runner.py`) | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad801_doctor.py tests/test_ad1137_doctor.py tests/test_ad484_ux_adoption.py -n 0 -q` |
| M2 (about 6 calls) | Sections 7.3 (the reader), 7.4 (the check), 7.5 (registration) | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf906_doctor_check.py tests/test_ad1328_s2a_startup_and_doctor.py tests/test_ad1327_verifier_independence.py tests/test_bf908_crew_scope_token.py tests/test_layer_boundaries.py -n 0 -q` |
| M3 (about 8 calls) | Section 7.6 (the new test file) | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf901_s3_token_accounting_view.py tests/test_bf901_s2_journal_token_provenance.py tests/test_cognitive_journal.py -n 0 -q`, then M1 and M2 again, then `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1343_seam_registry.py -n 0 -q` |
| M4 (about 6 calls) | Section 8: `PROGRESS.md`, `DECISIONS.md`, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` | `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1184_ad_ledger.py -n 0 -q` |
| M5 (about 4 calls) | Section audit; stage by explicit path: `src/probos/doctor/protocol.py`, `src/probos/doctor/runner.py`, `src/probos/cognitive/journal_token_report.py`, `src/probos/doctor/checks/token_accounting_check.py`, `src/probos/doctor/checks/__init__.py`, `tests/test_bf901_s3_token_accounting_view.py`, `PROGRESS.md`, `DECISIONS.md`, `docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json` (never `git add -A`) | `git diff --cached --stat` |

Then the orchestrator: the scratch-tree dry run, the mutation rows (section 10), review, the local commit, the receipted broad gate, and the AD-1323 follow-up issue (D7) before #1575 is closed.

## 5. Consumers of every value this changes

Greps: `Grep "CheckResult|\.remediation\b|run_doctor|iter_checks" src/probos/`; `Grep "def run\(self, ctx" tests/`; `Grep "fields\(CheckResult|CheckResult\.__dataclass_fields__" tests/`; `Grep "iter_checks" tests/`; `Grep "journal\.record\(|\.record_chain_trace\(" src/probos/`; `Grep "from probos\.doctor|import probos\.doctor" src/probos/`.

| Value | Consumer | What it does with it | Base or added |
|---|---|---|---|
| `CheckResult.detail` (new field, last, default `""`) | The 23 built-in checks (`doctor/checks/*.py`), which build results with 2 or 3 arguments, positional or keyword (e.g. `crew_enrollment_check.py:74-99`) | Nothing: the default applies | Unchanged |
| | Test checks: `test_ad801_doctor.py:47`, `test_ad1137_doctor.py:174`, `:1218`, `test_ad484_ux_adoption.py:202` | Same: 2 or 3 arguments | Unchanged |
| | `runner._render` (`runner.py:138-152`), called once per result (`:196`) | Prints each `detail` line, indented 4, after any remediation, on every outcome | Added |
| | `probos.doctor.__all__` (`doctor/__init__.py:26-34`) exports `CheckResult` | An overlay's check may construct it; the new field is defaulted, so it stands | Additive |
| `run_doctor` return code and closing line | `__main__._cmd_doctor` -> `sys.exit` (`__main__.py:1853-1879`, `:3405-3408`) | Unchanged: WARN never counts (`runner.py:197-200`); the closing line reads "No check failed; N warning(s) above." when this check warns (`:205-206`) | Unchanged contract |
| The `token_accounting` registration | Registry order tests: `test_bf906_doctor_check.py:349-350`, `test_ad1328_s2a_startup_and_doctor.py:704-705`, `test_ad1327_verifier_independence.py:911-912` (`extras` then `verifier_independence`); `test_bf908_crew_scope_token.py:1092`; `test_ad484_ux_adoption.py:229-234` | Inserted after `crew_enrollment`, after the `extras`/`verifier_independence` pair, so every pin holds | Added |
| A read of `cognitive_journal.db` | The vessel's journal writer (`journal.py:405-428`), which holds the file open in rollback mode | Each of the reader's statements holds a shared lock while it runs; the writer's commit waits for it under its connection's default busy timeout (the factory passes none, `sqlite_factory.py:37`). The doctor's own busy timeout is 2 s | Added (read only) |
| The journal's rows | No writer changes; the six write sites are S2's (`cognitive_agent.py:3698`, `:3736`, `:4529`; `sub_task.py:589`, `:661`, `:727`) | Read only | Unchanged |

## 6. Tests

All in `tests/test_bf901_s3_token_accounting_view.py`: **13 test cases in 11 test functions**. Every journal test writes rows through a real `CognitiveJournal.record` on `tmp_path` and reads them through the real check or the real reader over the real read-only open. T9 and T10 drive the real `run_doctor`.

| ID | Test | What it proves |
|---|---|---|
| T1 | `test_the_view_splits_spend_by_source_per_tier_intent_and_day` | Five rows, one per bucket, over two tiers, two intents and two UTC days: OK; the exact summary; the tier lines in spend order with measured and estimated always shown and the other buckets when they hold a row; the intents; the newest day first; "Rows naming no model: none."; the file's bytes and the directory listing are unchanged |
| T2 | `test_the_reader_puts_each_row_in_exactly_one_bucket` | The reader's totals per bucket (calls and tokens), tier and day order, first and last day, `labelled_since` |
| T3 | `test_a_row_without_a_model_after_token_sources_began_warns` | A row with an empty model recorded after the earliest labelled row (labelled rows in two groups) gives WARN, the exact message, the remediation and the no-model line |
| T4 | `test_rows_without_a_model_from_before_token_sources_are_reported_not_warned` | Rows with an empty model recorded before the first labelled row: OK, counted, split by chain step, with their last day |
| T5 | `test_a_journal_from_before_bf901_is_read_as_it_is_without_a_fail` | A journal without `token_source` (S2's pre-migration shape, built with raw `aiosqlite`): OK, every row uncharged or mock, the summary says it predates BF-901, the no-model line says none can be dated; the file is unchanged and still has no `token_source` |
| T6 | `test_a_missing_or_empty_journal_is_ok_and_left_as_it_was[missing|no_journal_table|empty_journal]` (3) | OK with the exact message, no detail, and the read-only open creates no file |
| T7 | `test_an_unreadable_journal_warns_and_does_not_fail` | A file that is not a database gives WARN with the BF-906 remediation, not FAIL, and nothing raises |
| T8 | `test_the_check_opens_the_journal_read_only` | Through a recording factory (BF-906's recorder, `test_bf906_doctor_check.py:442-462`): one open, `read_only=True` |
| T9 | `test_detail_shows_on_every_outcome_and_remediation_only_on_warn_or_fail` | `run_doctor` with three stub checks: an OK's detail lines are printed and its remediation is not; a WARN's remediation, then its detail; a result without detail prints nothing more |
| T10 | `test_the_real_check_renders_its_breakdown_through_run_doctor` | The full chain: `record` -> file -> the check -> the runner -> the console shows the summary and the breakdown lines |
| T11 | `test_the_check_is_registered_once_after_crew_enrollment` | A fresh interpreter: registered once, as `_TokenAccountingCheck`, directly after `crew_enrollment`; `extras` is still followed by `verifier_independence` |

Consumer tests run unchanged (M1 to M3): `test_ad801_doctor.py`, `test_ad1137_doctor.py`, `test_ad484_ux_adoption.py`, `test_bf906_doctor_check.py`, `test_ad1328_s2a_startup_and_doctor.py`, `test_ad1327_verifier_independence.py`, `test_bf908_crew_scope_token.py`, `test_layer_boundaries.py`, `test_bf901_s2_journal_token_provenance.py`, `test_cognitive_journal.py`, `test_ad1343_seam_registry.py`.

**Platform.** SQLite files in `tmp_path`, fixed UTC timestamps built with `datetime(..., tzinfo=timezone.utc)`, Rich's recording console. T11 spawns `sys.executable` with `PYTHONPATH` (BF-906's probe). Nothing depends on the host's time zone or OS.

## 7. The contract

### 7.1 `src/probos/doctor/protocol.py`

SEARCH:
```python
    `outcome` drives glyph + exit code (FAIL count). `message` is the
    one-line summary always printed. `remediation` is shown on WARN/FAIL
    only; if empty, no remediation line is rendered.
    """

    outcome: CheckOutcome
    message: str
    remediation: str = ""
```
REPLACE:
```python
    `outcome` drives glyph + exit code (FAIL count). `message` is the
    one-line summary always printed. `remediation` is shown on WARN/FAIL
    only; if empty, no remediation line is rendered.

    BF-901 S3: `detail` is printed under the result on every outcome, one
    line per line and after any remediation; if empty, nothing is rendered.
    It is the last field and defaulted, so every existing construction stands.
    """

    outcome: CheckOutcome
    message: str
    remediation: str = ""
    detail: str = ""  # BF-901 S3: further lines, shown under the result on every outcome
```

### 7.2 `src/probos/doctor/runner.py`

SEARCH:
```python
def _render(console: Console, name: str, outcome: CheckOutcome, message: str, remediation: str) -> None:
    """Render a single check's result with the appropriate glyph + style.

    AD-1137: check text is printed literally (a provider's or a path's "[" is not Rich markup),
    and each line of a multi-line remediation is indented under the result.
    """
    if outcome is CheckOutcome.OK:
        console.print(f"  [green]\u2713[/green] {escape(message)}")
        return
    if outcome is CheckOutcome.WARN:
        console.print(f"  [yellow]\u26a0[/yellow] {escape(message)}")
    else:  # FAIL
        console.print(f"  [red]\u2717[/red] {escape(message)}")
    for line in remediation.splitlines():
        console.print(f"    [dim]{escape(line)}[/dim]")
```
REPLACE:
```python
def _render(
    console: Console, name: str, outcome: CheckOutcome, message: str, remediation: str, detail: str = "",
) -> None:
    """Render a single check's result with the appropriate glyph + style.

    AD-1137: check text is printed literally (a provider's or a path's "[" is not Rich markup),
    and each line of a multi-line remediation is indented under the result.
    BF-901 S3: each line of ``detail`` follows, on every outcome; an OK result still shows no remediation.
    """
    if outcome is CheckOutcome.OK:
        console.print(f"  [green]\u2713[/green] {escape(message)}")
    elif outcome is CheckOutcome.WARN:
        console.print(f"  [yellow]\u26a0[/yellow] {escape(message)}")
    else:  # FAIL
        console.print(f"  [red]\u2717[/red] {escape(message)}")
    if outcome is not CheckOutcome.OK:
        for line in remediation.splitlines():
            console.print(f"    [dim]{escape(line)}[/dim]")
    for line in detail.splitlines():
        console.print(f"    {escape(line)}")
```

The `\u2713`, `\u26a0` and `\u2717` sequences are the file's own escape sequences: keep them as written, do not substitute the characters.

SEARCH:
```python
        _render(console, check.name, result.outcome, result.message, result.remediation)
        if result.outcome is CheckOutcome.FAIL:
            fail_count += 1
```
REPLACE:
```python
        _render(console, check.name, result.outcome, result.message, result.remediation, result.detail)
        if result.outcome is CheckOutcome.FAIL:
            fail_count += 1
```

The FAIL branch for a check that raised (`runner.py:187-193`) passes no detail and keeps the default.

### 7.3 New file: `src/probos/cognitive/journal_token_report.py`

```python
"""BF-901 S3 (#1575): what the cognitive journal says was spent, per tier, per intent and per UTC day.

Read-only. ``read_journal_token_report`` takes a connection its caller opened (the doctor's
``token_accounting`` check opens ``cognitive_journal.db`` through the ConnectionFactory's ``read_only`` open,
as BF-906's check does) and runs at most three statements: the journal's column list, one grouped scan and,
once a row carries a token source, one count of the rows since then that name no model. It never writes,
creates or migrates anything, so a journal that predates BF-901 is read as it is.

Each row falls in exactly one bucket, tested in this order:

* ``replayed``: ``cached`` is set (a client cache replay, a decision-cache hit, a procedural replay). Never
  spend: the journal's own spend readers filter ``cached = 0``.
* ``mock``: ``model = 'mock'``, the mock client's fixed counts, which BF-901 S2 records as measured.
* ``measured`` and ``estimated``: the row's ``token_source``, as BF-901 S1's ``charge_completion`` set it.
* ``uncharged``: an empty ``token_source``: no model call (a bypassed step, a timed-out attempt), a failed
  call, or a row recorded before BF-901, which all read empty.
* ``other``: any other label. None is written today; it is counted apart so that a new label is never
  folded into another bucket.

Spend is measured plus estimated. The journal's empty source is not in ``crew_execution_usage``'s vocabulary
(measured, estimated, mixed), and nothing here passes a journal label to that module.

Only journaled calls are covered: one-shot decisions and sub-task chain steps. The agentic loop and the
other model calls that write no journal row (BF-901 S2, section 9) are not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from probos.cognitive.token_accounting import TOKEN_SOURCE_NONE
from probos.crew_execution_usage import TOKEN_SOURCE_ESTIMATED, TOKEN_SOURCE_MEASURED

if TYPE_CHECKING:
    from probos.protocols import DatabaseConnection

BUCKET_MEASURED = TOKEN_SOURCE_MEASURED
BUCKET_ESTIMATED = TOKEN_SOURCE_ESTIMATED
BUCKET_UNCHARGED = "uncharged"
BUCKET_REPLAYED = "replayed"
BUCKET_MOCK = "mock"
BUCKET_OTHER = "other"
BUCKETS: tuple[str, ...] = (
    BUCKET_MEASURED, BUCKET_ESTIMATED, BUCKET_UNCHARGED, BUCKET_REPLAYED, BUCKET_MOCK, BUCKET_OTHER,
)
#: The key shown for a row whose tier or intent is empty.
NO_KEY = "(none)"

_COLUMNS_SQL = "PRAGMA table_info(journal)"
# The source expression is one of two fixed strings: the column, or an empty literal for a journal that
# predates BF-901. 'mock' is the mock client's model name (llm_client.py). 'st:' prefixes a chain step's
# dag_node_id (sub_task.py). Columns, in order: tier, intent, UTC day, source, replayed, mock, no model,
# chain step, calls, tokens, the earliest labelled timestamp in the group.
_SOURCE_COLUMN = "token_source"
_SOURCE_ABSENT = "''"
_GROUPED_SQL = (
    "SELECT tier, intent, strftime('%Y-%m-%d', timestamp, 'unixepoch'), {source}, cached <> 0, "
    "model = 'mock', model = '', dag_node_id LIKE 'st:%', COUNT(*), COALESCE(SUM(total_tokens), 0), "
    "MIN(CASE WHEN {source} <> '' THEN timestamp END) "
    "FROM journal GROUP BY 1, 2, 3, 4, 5, 6, 7, 8"
)
_NO_MODEL_SINCE_SQL = "SELECT COUNT(*) FROM journal WHERE model = '' AND timestamp >= ?"


@dataclass
class GroupUsage:
    """One tier, intent or UTC day, or the whole journal: calls and tokens per bucket."""

    key: str
    calls: dict[str, int] = field(default_factory=lambda: dict.fromkeys(BUCKETS, 0))
    tokens: dict[str, int] = field(default_factory=lambda: dict.fromkeys(BUCKETS, 0))

    def add(self, bucket: str, calls: int, tokens: int) -> None:
        self.calls[bucket] += calls
        self.tokens[bucket] += tokens

    @property
    def rows(self) -> int:
        return sum(self.calls.values())

    @property
    def spend_tokens(self) -> int:
        """Measured plus estimated: what the journal says was spent."""
        return self.tokens[BUCKET_MEASURED] + self.tokens[BUCKET_ESTIMATED]

    @property
    def spend_calls(self) -> int:
        return self.calls[BUCKET_MEASURED] + self.calls[BUCKET_ESTIMATED]


@dataclass(frozen=True)
class JournalTokenReport:
    """What one read of the journal found. Days are UTC ``YYYY-MM-DD``; groups are in display order."""

    has_token_source: bool
    total: GroupUsage
    by_tier: tuple[GroupUsage, ...] = ()
    by_intent: tuple[GroupUsage, ...] = ()
    by_day: tuple[GroupUsage, ...] = ()
    first_day: str = ""
    last_day: str = ""
    #: The timestamp of the earliest row that carries a token source; ``None`` when none does.
    labelled_since: float | None = None
    no_model_rows: int = 0
    no_model_chain_steps: int = 0
    no_model_last_day: str = ""
    #: Rows naming no model recorded at or after ``labelled_since``: BF-901 requires a model or ``unknown``.
    no_model_since_labelled: int = 0

    @property
    def rows(self) -> int:
        return self.total.rows


def _bucket(source: object, replayed: object, mock: object) -> str:
    if replayed:
        return BUCKET_REPLAYED
    if mock:
        return BUCKET_MOCK
    if source == TOKEN_SOURCE_MEASURED:
        return BUCKET_MEASURED
    if source == TOKEN_SOURCE_ESTIMATED:
        return BUCKET_ESTIMATED
    if source == TOKEN_SOURCE_NONE:
        return BUCKET_UNCHARGED
    return BUCKET_OTHER


def _by_spend(group: GroupUsage) -> tuple[int, int, str]:
    return (-group.spend_tokens, -group.rows, group.key)


async def read_journal_token_report(conn: DatabaseConnection) -> JournalTokenReport | None:
    """Read the journal's spend by bucket; ``None`` when the database has no ``journal`` table.

    Errors propagate (``sqlite3.Error`` from SQLite): the caller decides how an unreadable store degrades.
    """
    cursor = await conn.execute(_COLUMNS_SQL)
    columns = {str(row[1]) for row in await cursor.fetchall()}
    if not columns:
        return None
    has_source = _SOURCE_COLUMN in columns
    sql = _GROUPED_SQL.format(source=_SOURCE_COLUMN if has_source else _SOURCE_ABSENT)
    cursor = await conn.execute(sql)
    grouped = await cursor.fetchall()

    total = GroupUsage("all")
    tiers: dict[str, GroupUsage] = {}
    intents: dict[str, GroupUsage] = {}
    days: dict[str, GroupUsage] = {}
    labelled_since: float | None = None
    no_model_rows = 0
    no_model_chain_steps = 0
    no_model_last_day = ""
    for tier, intent, day, source, replayed, mock, no_model, chain_step, calls, tokens, first_labelled in grouped:
        bucket = _bucket(source, replayed, mock)
        count = int(calls)
        spent = int(tokens)
        day_key = str(day or "")
        total.add(bucket, count, spent)
        for groups, key in ((tiers, tier), (intents, intent), (days, day_key)):
            name = str(key or "") or NO_KEY
            groups.setdefault(name, GroupUsage(name)).add(bucket, count, spent)
        if first_labelled is not None and (labelled_since is None or first_labelled < labelled_since):
            labelled_since = float(first_labelled)
        if no_model:
            no_model_rows += count
            if chain_step:
                no_model_chain_steps += count
            no_model_last_day = max(no_model_last_day, day_key)

    no_model_since_labelled = 0
    if labelled_since is not None and no_model_rows:
        cursor = await conn.execute(_NO_MODEL_SINCE_SQL, (labelled_since,))
        row = await cursor.fetchone()
        no_model_since_labelled = int(row[0]) if row else 0

    day_keys = sorted(key for key in days if key != NO_KEY)
    return JournalTokenReport(
        has_token_source=has_source,
        total=total,
        by_tier=tuple(sorted(tiers.values(), key=_by_spend)),
        by_intent=tuple(sorted(intents.values(), key=_by_spend)),
        by_day=tuple(sorted(days.values(), key=lambda group: group.key, reverse=True)),
        first_day=day_keys[0] if day_keys else "",
        last_day=day_keys[-1] if day_keys else "",
        labelled_since=labelled_since,
        no_model_rows=no_model_rows,
        no_model_chain_steps=no_model_chain_steps,
        no_model_last_day=no_model_last_day,
        no_model_since_labelled=no_model_since_labelled,
    )
```

### 7.4 New file: `src/probos/doctor/checks/token_accounting_check.py`

```python
"""BF-901 S3 (#1575): the journal's token spend per tier, per intent and per UTC day, measured and estimated apart.

Reads cognitive_journal.db through the approved ConnectionFactory adapter's ``read_only`` open (SQLite
``mode=ro``), as BF-906's crew_enrollment check reads its stores: it never creates the file, never writes and
never migrates, so a journal that predates BF-901 is read as it is. The journal runs in SQLite's default
rollback mode (the journal's ``start`` sets no journal mode), so each read statement holds a shared lock
while it runs; the vessel's writer waits for it under its connection's default busy timeout.

The outcome is OK or WARN, never FAIL: this is an account, not a component that can be broken. WARN means the
journal could not be read, or a row recorded since the first row with a token source names no model (BF-901
requires the answering model or ``unknown``). The breakdown is the result's ``detail``, shown on every
outcome.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from probos.cognitive.journal_token_report import (
    BUCKET_ESTIMATED,
    BUCKET_MEASURED,
    BUCKET_MOCK,
    BUCKET_OTHER,
    BUCKET_REPLAYED,
    BUCKET_UNCHARGED,
    GroupUsage,
    JournalTokenReport,
    read_journal_token_report,
)
from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check
from probos.storage.sqlite_factory import default_factory

#: The file ``startup/communication.py`` opens under the data directory.
JOURNAL_FILE = "cognitive_journal.db"
#: Shown per dimension; the rest are counted in one line.
MAX_INTENTS = 8
MAX_DAYS = 7
_BUSY_TIMEOUT_S = 2.0
_LEGEND = (
    "Spend is measured plus estimated. Replayed rows (cached) and the mock client are not spend; "
    "uncharged rows made no model call, failed, or were recorded before BF-901."
)
_COVERAGE = (
    "Journaled calls only (one-shot decisions and sub-task chain steps); the agentic loop writes no journal row."
)


def _plural(count: int, noun: str) -> str:
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def _utc_day(timestamp: float | None) -> str:
    if timestamp is None:
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")


def _amount(group: GroupUsage, bucket: str) -> str:
    return f"{bucket} {group.tokens[bucket]:,} tokens over {_plural(group.calls[bucket], 'call')}"


def _describe(group: GroupUsage) -> str:
    """One group's line: measured and estimated always, the other buckets when they hold a row."""
    parts = [_amount(group, BUCKET_MEASURED), _amount(group, BUCKET_ESTIMATED)]
    for bucket in (BUCKET_UNCHARGED, BUCKET_REPLAYED, BUCKET_MOCK, BUCKET_OTHER):
        if group.calls[bucket]:
            parts.append(_amount(group, bucket))
    return f"{group.key}: " + "; ".join(parts)


def _summary(report: JournalTokenReport) -> str:
    total = report.total
    text = (
        f"Token accounting: {total.spend_tokens:,} tokens spent over {_plural(total.spend_calls, 'call')} "
        f"({total.tokens[BUCKET_MEASURED]:,} measured, {total.tokens[BUCKET_ESTIMATED]:,} estimated), "
        f"{report.first_day} to {report.last_day} UTC"
    )
    if not report.has_token_source:
        text += (
            "; this journal predates BF-901: no row carries a token source until ProbOS restarts on BF-901, "
            "which adds the column"
        )
    return text


def _no_model_line(report: JournalTokenReport) -> str:
    if not report.no_model_rows:
        return "Rows naming no model: none."
    head = (
        f"Rows naming no model: {report.no_model_rows:,} ({_plural(report.no_model_chain_steps, 'chain step')}), "
        f"the last on {report.no_model_last_day}"
    )
    if report.labelled_since is None:
        return head + "; no row carries a token source yet, so none can be dated after BF-901."
    return (
        head + f"; {report.no_model_since_labelled:,} since token sources began on "
        f"{_utc_day(report.labelled_since)}."
    )


def _detail_lines(report: JournalTokenReport) -> list[str]:
    lines = [_LEGEND, _COVERAGE, "By tier:"]
    lines.extend(f"  {_describe(group)}" for group in report.by_tier)
    lines.append("By intent:")
    lines.extend(f"  {_describe(group)}" for group in report.by_intent[:MAX_INTENTS])
    if len(report.by_intent) > MAX_INTENTS:
        lines.append(f"  ({_plural(len(report.by_intent) - MAX_INTENTS, 'more intent')})")
    lines.append("By UTC day, newest first:")
    lines.extend(f"  {_describe(group)}" for group in report.by_day[:MAX_DAYS])
    if len(report.by_day) > MAX_DAYS:
        lines.append(f"  ({_plural(len(report.by_day) - MAX_DAYS, 'earlier day')})")
    lines.append(_no_model_line(report))
    return lines


async def _read(path: Path) -> JournalTokenReport | None:
    """The report from the journal at ``path``, opened read-only and closed again."""
    conn = await default_factory.connect(str(path), read_only=True)
    try:
        await conn.execute(f"PRAGMA busy_timeout = {int(_BUSY_TIMEOUT_S * 1000)}")
        return await read_journal_token_report(conn)
    finally:
        await conn.close()


@dataclass(frozen=True)
class _TokenAccountingCheck:
    name: str = "token_accounting"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        path = ctx.data_dir / JOURNAL_FILE
        if not path.exists():
            return CheckResult(CheckOutcome.OK, "Token accounting: no cognitive journal yet")
        try:
            report = await _read(path)
        except sqlite3.Error as exc:
            return CheckResult(
                CheckOutcome.WARN,
                f"Token accounting: could not read {JOURNAL_FILE}: {exc}",
                "The running vessel may be writing to it; rerun `probos doctor`.",
            )
        if report is None or not report.rows:
            return CheckResult(CheckOutcome.OK, "Token accounting: no model calls recorded yet")
        detail = "\n".join(_detail_lines(report))
        if report.no_model_since_labelled:
            return CheckResult(
                CheckOutcome.WARN,
                f"Token accounting: {_plural(report.no_model_since_labelled, 'journal row')} with no model "
                f"since token sources began on {_utc_day(report.labelled_since)}",
                "BF-901 requires every journal row to name the model that answered, or 'unknown'. Find the "
                "writer from these rows' dag_node_id and intent, on a copy of cognitive_journal.db.",
                detail,
            )
        return CheckResult(CheckOutcome.OK, _summary(report), "", detail)


register_check(_TokenAccountingCheck())
```

The results that carry a detail pass it **positionally** (the fourth argument). This is deliberate: the phantom-API precheck runs on the pre-build tree, where `CheckResult` has no `detail` field, and its field check reads keyword arguments (section 12). Do not rewrite them as `detail=`.

### 7.5 `src/probos/doctor/checks/__init__.py`

SEARCH:
```python
    chroma_check,
    crew_enrollment_check,
    security_check,
```
REPLACE:
```python
    chroma_check,
    crew_enrollment_check,
    token_accounting_check,
    security_check,
```

### 7.6 New file: `tests/test_bf901_s3_token_accounting_view.py`

```python
"""BF-901 S3 (#1575): the doctor's ``token_accounting`` view of the cognitive journal.

The contract is ``prompts/bf-901-s3-doctor-token-accounting-view.md``. Rows are written through the real
``CognitiveJournal.record`` (BF-901 S2's writer) into ``tmp_path`` and read back by the real check, or the real
reader, through the real read-only open, so each journal test crosses the seam the view depends on: what the
journal writes is what the doctor reports. The runner tests drive the real ``run_doctor``. Third-party and
standard-library classes are imported under underscore aliases (the phantom-API precheck reads the contract's
code). The contract's section 10 names the test that kills each mutant.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from argparse import Namespace as _Namespace  # a standard-library class, aliased (see the docstring)
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from rich.console import Console as _Console  # a third-party class, aliased (see the docstring)

from probos.cognitive.journal import CognitiveJournal
from probos.cognitive.journal_token_report import (
    BUCKET_ESTIMATED,
    BUCKET_MEASURED,
    BUCKET_MOCK,
    BUCKET_OTHER,
    BUCKET_REPLAYED,
    BUCKET_UNCHARGED,
    read_journal_token_report,
)
from probos.doctor import registry as registry_module
from probos.doctor.checks import token_accounting_check
from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check
from probos.doctor.runner import run_doctor
from probos.storage.sqlite_factory import default_factory

DAY1 = datetime(2026, 10, 20, 12, tzinfo=timezone.utc).timestamp()
DAY2 = datetime(2026, 10, 21, 12, tzinfo=timezone.utc).timestamp()
HOUR = 3600.0

# One row per bucket across two tiers, two intents and two UTC days (T1, T2, T8, T10).
SPREAD_ROWS: list[dict[str, Any]] = [
    {"timestamp": DAY1, "tier": "standard", "intent": "proactive_think", "model": "claude-sonnet-5.5",
     "prompt_tokens": 60, "completion_tokens": 40, "total_tokens": 100, "token_source": "measured"},
    {"timestamp": DAY2, "tier": "deep", "intent": "ward_room_notification", "model": "claude-opus-4-6",
     "total_tokens": 40, "token_source": "estimated", "dag_node_id": "st:c1:0:compose"},
    {"timestamp": DAY2 + HOUR, "tier": "standard", "intent": "ward_room_notification", "model": "unknown",
     "dag_node_id": "st:c1:1:evaluate"},
    {"timestamp": DAY2 + 2 * HOUR, "tier": "deep", "intent": "ward_room_notification",
     "model": "claude-opus-4-6", "total_tokens": 30, "token_source": "estimated", "cached": True},
    {"timestamp": DAY1 + HOUR, "tier": "standard", "intent": "proactive_think", "model": "mock",
     "total_tokens": 32, "token_source": "measured"},
]
SPREAD_SUMMARY = (
    "Token accounting: 140 tokens spent over 2 calls (100 measured, 40 estimated), 2026-10-20 to 2026-10-21 UTC"
)
STANDARD_TIER = (
    "  standard: measured 100 tokens over 1 call; estimated 0 tokens over 0 calls; "
    "uncharged 0 tokens over 1 call; mock 32 tokens over 1 call"
)
DEEP_TIER = (
    "  deep: measured 0 tokens over 0 calls; estimated 40 tokens over 1 call; replayed 30 tokens over 1 call"
)
NEWEST_DAY = (
    "  2026-10-21: measured 0 tokens over 0 calls; estimated 40 tokens over 1 call; "
    "uncharged 0 tokens over 1 call; replayed 30 tokens over 1 call"
)
_PRE_BF901_JOURNAL = (
    "CREATE TABLE journal (id TEXT PRIMARY KEY, timestamp REAL NOT NULL, agent_id TEXT NOT NULL, "
    "tier TEXT NOT NULL DEFAULT 'standard', model TEXT NOT NULL DEFAULT '', "
    "total_tokens INTEGER NOT NULL DEFAULT 0, intent TEXT NOT NULL DEFAULT '', "
    "cached INTEGER NOT NULL DEFAULT 0, dag_node_id TEXT NOT NULL DEFAULT '')"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(data_dir: Path) -> DoctorContext:
    return DoctorContext(config=None, home_dir=data_dir, data_dir=data_dir, config_path=None)


def _check() -> Any:
    return token_accounting_check._TokenAccountingCheck()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _listing(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


async def _journal(data_dir: Path, rows: list[dict[str, Any]]) -> Path:
    """Write ``rows`` through the real journal (BF-901 S2's writer), then close it."""
    path = data_dir / "cognitive_journal.db"
    journal = CognitiveJournal(db_path=str(path))
    await journal.start()
    try:
        for index, row in enumerate(rows):
            await journal.record(entry_id=f"e{index}", agent_id="a1", **row)
    finally:
        await journal.stop()
    return path


async def _report(path: Path) -> Any:
    conn = await default_factory.connect(str(path), read_only=True)
    try:
        return await read_journal_token_report(conn)
    finally:
        await conn.close()


@pytest.fixture
def fresh_registry():
    """Swap the module-level registry for an empty one (tests/test_ad801_doctor.py's fixture, copied)."""
    saved_checks = list(registry_module._CHECKS)
    saved_names = set(registry_module._NAMES)
    registry_module._CHECKS.clear()
    registry_module._NAMES.clear()
    yield
    registry_module._CHECKS.clear()
    registry_module._NAMES.clear()
    registry_module._CHECKS.extend(saved_checks)
    registry_module._NAMES.update(saved_names)


@dataclass(frozen=True)
class _Stub:
    name: str
    result: CheckResult

    async def run(self, ctx: DoctorContext) -> CheckResult:
        return self.result


class _RecordingFactory:
    """Delegates to the real factory and records how each store was opened (BF-906's recorder)."""

    def __init__(self) -> None:
        self.read_only: list[bool] = []

    async def connect(self, db_path: str, *, read_only: bool = False) -> Any:
        self.read_only.append(read_only)
        return await default_factory.connect(db_path, read_only=read_only)


async def _doctor_lines(ctx: DoctorContext) -> tuple[int, list[str]]:
    console = _Console(record=True, width=240, soft_wrap=True)
    code = await run_doctor(_Namespace(), console, ctx=ctx)
    return code, console.export_text().splitlines()


# ---------------------------------------------------------------------------
# 1. The breakdown (T1, T2)
# ---------------------------------------------------------------------------


async def test_the_view_splits_spend_by_source_per_tier_intent_and_day(tmp_path: Path) -> None:
    path = await _journal(tmp_path, SPREAD_ROWS)
    before = (_sha256(path), _listing(tmp_path))

    result = await _check().run(_ctx(tmp_path))

    assert result.outcome is CheckOutcome.OK
    assert result.message == SPREAD_SUMMARY
    lines = result.detail.splitlines()
    tiers = lines.index("By tier:")
    assert lines[tiers + 1 : tiers + 3] == [STANDARD_TIER, DEEP_TIER]
    intents = lines.index("By intent:")
    assert lines[intents + 1].startswith("  proactive_think: measured 100 tokens over 1 call;")
    assert lines[intents + 2].startswith("  ward_room_notification: measured 0 tokens over 0 calls;")
    assert lines[lines.index("By UTC day, newest first:") + 1] == NEWEST_DAY
    assert lines[-1] == "Rows naming no model: none."
    assert (_sha256(path), _listing(tmp_path)) == before  # nothing written, no side file


async def test_the_reader_puts_each_row_in_exactly_one_bucket(tmp_path: Path) -> None:
    report = await _report(await _journal(tmp_path, SPREAD_ROWS))

    assert report.has_token_source is True
    assert report.total.tokens == {
        BUCKET_MEASURED: 100, BUCKET_ESTIMATED: 40, BUCKET_UNCHARGED: 0,
        BUCKET_REPLAYED: 30, BUCKET_MOCK: 32, BUCKET_OTHER: 0,
    }
    assert report.total.calls == {
        BUCKET_MEASURED: 1, BUCKET_ESTIMATED: 1, BUCKET_UNCHARGED: 1,
        BUCKET_REPLAYED: 1, BUCKET_MOCK: 1, BUCKET_OTHER: 0,
    }
    assert [group.key for group in report.by_tier] == ["standard", "deep"]
    assert [group.key for group in report.by_day] == ["2026-10-21", "2026-10-20"]
    assert (report.first_day, report.last_day) == ("2026-10-20", "2026-10-21")
    assert report.labelled_since == DAY1


# ---------------------------------------------------------------------------
# 2. Rows that name no model (T3, T4)
# ---------------------------------------------------------------------------


async def test_a_row_without_a_model_after_token_sources_began_warns(tmp_path: Path) -> None:
    await _journal(tmp_path, [
        {"timestamp": DAY1, "tier": "standard", "intent": "proactive_think", "model": "m1",
         "total_tokens": 10, "token_source": "measured"},
        {"timestamp": DAY1 + 6 * HOUR, "tier": "standard", "intent": "proactive_think", "model": "",
         "dag_node_id": "st:c9:0:compose"},
        {"timestamp": DAY2, "tier": "deep", "intent": "proactive_think", "model": "m2",
         "total_tokens": 20, "token_source": "estimated"},
    ])

    result = await _check().run(_ctx(tmp_path))

    assert result.outcome is CheckOutcome.WARN
    assert result.message == (
        "Token accounting: 1 journal row with no model since token sources began on 2026-10-20"
    )
    assert result.remediation.startswith("BF-901 requires every journal row to name the model that answered")
    assert result.detail.splitlines()[-1] == (
        "Rows naming no model: 1 (1 chain step), the last on 2026-10-20; "
        "1 since token sources began on 2026-10-20."
    )


async def test_rows_without_a_model_from_before_token_sources_are_reported_not_warned(tmp_path: Path) -> None:
    await _journal(tmp_path, [
        {"timestamp": DAY1, "intent": "ward_room_notification", "model": "", "dag_node_id": "st:c1:0:compose"},
        {"timestamp": DAY1 + HOUR, "intent": "proactive_think", "model": ""},
        {"timestamp": DAY2, "intent": "proactive_think", "model": "m1", "total_tokens": 10,
         "token_source": "measured"},
    ])

    result = await _check().run(_ctx(tmp_path))

    assert result.outcome is CheckOutcome.OK
    assert result.detail.splitlines()[-1] == (
        "Rows naming no model: 2 (1 chain step), the last on 2026-10-20; "
        "0 since token sources began on 2026-10-21."
    )


# ---------------------------------------------------------------------------
# 3. Journals that are old, absent, empty or unreadable (T5, T6, T7)
# ---------------------------------------------------------------------------


async def test_a_journal_from_before_bf901_is_read_as_it_is_without_a_fail(tmp_path: Path) -> None:
    path = tmp_path / "cognitive_journal.db"
    async with aiosqlite.connect(str(path)) as db:
        await db.execute(_PRE_BF901_JOURNAL)
        await db.executemany(
            "INSERT INTO journal (id, timestamp, agent_id, tier, model, total_tokens, intent, dag_node_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("r1", DAY1, "a1", "standard", "", 0, "ward_room_notification", "st:c1:0:compose"),
                ("r2", DAY1 + HOUR, "a1", "deep", "mock", 32, "proactive_think", ""),
                ("r3", DAY1 + 2 * HOUR, "a1", "standard", "claude-sonnet-5.5", 0, "proactive_think", ""),
            ],
        )
        await db.commit()
    before = (_sha256(path), _listing(tmp_path))

    result = await _check().run(_ctx(tmp_path))

    assert result.outcome is CheckOutcome.OK
    assert result.message == (
        "Token accounting: 0 tokens spent over 0 calls (0 measured, 0 estimated), 2026-10-20 to 2026-10-20 UTC; "
        "this journal predates BF-901: no row carries a token source until ProbOS restarts on BF-901, "
        "which adds the column"
    )
    assert result.detail.splitlines()[-1] == (
        "Rows naming no model: 1 (1 chain step), the last on 2026-10-20; "
        "no row carries a token source yet, so none can be dated after BF-901."
    )
    assert (_sha256(path), _listing(tmp_path)) == before  # never migrated
    report = await _report(path)
    assert report.has_token_source is False
    assert (report.total.calls[BUCKET_UNCHARGED], report.total.calls[BUCKET_MOCK]) == (2, 1)


@pytest.mark.parametrize("state", ["missing", "no_journal_table", "empty_journal"])
async def test_a_missing_or_empty_journal_is_ok_and_left_as_it_was(tmp_path: Path, state: str) -> None:
    path = tmp_path / "cognitive_journal.db"
    if state == "no_journal_table":
        async with aiosqlite.connect(str(path)) as db:
            await db.execute("CREATE TABLE unrelated (x INTEGER)")
            await db.commit()
    elif state == "empty_journal":
        await _journal(tmp_path, [])
    before = _listing(tmp_path)

    result = await _check().run(_ctx(tmp_path))

    assert result.outcome is CheckOutcome.OK
    expected = "no cognitive journal yet" if state == "missing" else "no model calls recorded yet"
    assert result.message == f"Token accounting: {expected}"
    assert result.detail == ""
    assert _listing(tmp_path) == before  # the read-only open creates nothing


async def test_an_unreadable_journal_warns_and_does_not_fail(tmp_path: Path) -> None:
    (tmp_path / "cognitive_journal.db").write_bytes(b"this is not a SQLite database. " * 64)

    result = await _check().run(_ctx(tmp_path))

    assert result.outcome is CheckOutcome.WARN
    assert result.message.startswith("Token accounting: could not read cognitive_journal.db: ")
    assert result.remediation == "The running vessel may be writing to it; rerun `probos doctor`."


async def test_the_check_opens_the_journal_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    await _journal(tmp_path, SPREAD_ROWS[:1])
    recorder = _RecordingFactory()
    monkeypatch.setattr(token_accounting_check, "default_factory", recorder)

    result = await _check().run(_ctx(tmp_path))

    assert result.outcome is CheckOutcome.OK  # premise: the read went through the recorder
    assert recorder.read_only == [True]


# ---------------------------------------------------------------------------
# 4. The runner and the registration (T9, T10, T11)
# ---------------------------------------------------------------------------


async def test_detail_shows_on_every_outcome_and_remediation_only_on_warn_or_fail(
    fresh_registry: None, tmp_path: Path,
) -> None:
    register_check(_Stub("ok_stub", CheckResult(
        CheckOutcome.OK, "ok-summary", "ok-hidden-remediation", "ok-detail-1\nok-detail-2",
    )))
    register_check(_Stub("warn_stub", CheckResult(CheckOutcome.WARN, "warn-summary", "warn-remediation", "warn-detail")))
    register_check(_Stub("plain_stub", CheckResult(CheckOutcome.OK, "plain-summary")))

    code, lines = await _doctor_lines(_ctx(tmp_path))

    assert code == 0  # WARN does not count (runner.py's contract, unchanged)
    ok = next(i for i, line in enumerate(lines) if "ok-summary" in line)
    assert lines[ok + 1 : ok + 3] == ["    ok-detail-1", "    ok-detail-2"]
    assert not any("ok-hidden-remediation" in line for line in lines)
    warn = next(i for i, line in enumerate(lines) if "warn-summary" in line)
    assert lines[warn + 1 : warn + 3] == ["    warn-remediation", "    warn-detail"]
    plain = next(i for i, line in enumerate(lines) if "plain-summary" in line)
    assert lines[plain + 1] == ""  # no detail, nothing rendered: the runner's closing blank line follows


async def test_the_real_check_renders_its_breakdown_through_run_doctor(
    fresh_registry: None, tmp_path: Path,
) -> None:
    await _journal(tmp_path, SPREAD_ROWS)
    register_check(_check())

    code, lines = await _doctor_lines(_ctx(tmp_path))

    assert code == 0
    assert any(line.endswith(SPREAD_SUMMARY) for line in lines)
    assert "    " + STANDARD_TIER in lines
    assert "    " + NEWEST_DAY in lines


def test_the_check_is_registered_once_after_crew_enrollment() -> None:
    """A fresh interpreter, so that this file's own import of the check module cannot stand in for the
    registration line in ``probos/doctor/checks/__init__.py`` (tests/test_bf906_doctor_check.py's probe)."""
    import probos

    src_dir = Path(probos.__file__).resolve().parents[1]
    probe = (
        "import json; from probos.doctor import checks; from probos.doctor.registry import iter_checks; "
        "print(json.dumps([[c.name, type(c).__qualname__] for c in iter_checks()]))"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=120, check=False,
        env={**os.environ, "PYTHONPATH": str(src_dir)},
    )
    assert done.returncode == 0, done.stderr
    registered = json.loads(done.stdout.strip().splitlines()[-1])
    names = [name for name, _ in registered]

    assert [kind for name, kind in registered if name == "token_accounting"] == ["_TokenAccountingCheck"]
    assert names[names.index("crew_enrollment") + 1] == "token_accounting"
    assert names[names.index("extras") + 1] == "verifier_independence"
```

## 8. Tracking (tracker pairs)

**`PROGRESS.md`** (anchored on the first line, the blank line after it and the bold lead of S2's head entry):

SEARCH:
```markdown
# ProbOS Progress

**BF-901 S2 (2026-10-21), part of #1575 -- the journal records what each call cost, where the count came from, and the model that answered.**
```
REPLACE:
```markdown
# ProbOS Progress

**BF-901 S3 (2026-10-21), closes #1575 -- the doctor shows what the journal says was spent, measured and estimated apart.** A new `token_accounting` doctor check reads `cognitive_journal.db` through the ConnectionFactory's read-only open (never creating, writing or migrating it) and shows spend per tier, per intent and per UTC day, with measured and estimated counted apart and three buckets that are not spend beside them: replayed rows (`cached`), the mock client's rows, and uncharged rows (no model call, a failed call, or recorded before BF-901). It warns, never fails: when the journal cannot be read, or when a row recorded since the first row with a token source names no model. Otherwise it reports the rows with no model, how many are chain steps and the day of the last one, which confirms S2's diagnosis on the vessel at the next restart. The reader is `cognitive/journal_token_report.py`; the doctor's `CheckResult` gains a defaulted `detail` field that the runner prints under every outcome (an OK result still shows no remediation). The view covers journaled calls only: the agentic loop writes no journal row. #1575's acceptance is settled in DECISIONS.md (BF-901 S3): the budget clause is met for AD-1208 by S1's test, and the AD-1323 approval card's missing token source is a linked follow-up. New: `tests/test_bf901_s3_token_accounting_view.py` (rows written through the real journal and read by the real check through the real read-only open; the real `run_doctor`; the registration in a fresh interpreter). The contract is `prompts/bf-901-s3-doctor-token-accounting-view.md`.

**BF-901 S2 (2026-10-21), part of #1575 -- the journal records what each call cost, where the count came from, and the model that answered.**
```

**`DECISIONS.md`** (after S2's entry, before the heading that follows it; the docs-only commit's *Validation of record* bullet sits above S2's *Reversal* line and does not change this block):

SEARCH:
```markdown
- *Reversal.* Revert the BF-901 S2 commit. The added columns stay in any database that started under it (SQLite keeps them) and are harmless, though not invisible: the reverted code's named `INSERT`s leave them at their default `''`, and its `SELECT *` readers still return them, so the routes and the diagnostic context still serialize `token_source` on rows written while S2 ran. The aggregate readers do not read it.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
- *Reversal.* Revert the BF-901 S2 commit. The added columns stay in any database that started under it (SQLite keeps them) and are harmless, though not invisible: the reverted code's named `INSERT`s leave them at their default `''`, and its `SELECT *` readers still return them, so the routes and the diagnostic context still serialize `token_source` on rows written while S2 ran. The aggregate readers do not read it.

### BF-901 S3 -- The doctor shows what the journal says was spent, measured and estimated apart (2026-10-21, closes #1575)

- *Scope.* `cognitive/journal_token_report.py` (new, the read-only reader), `doctor/checks/token_accounting_check.py` (new), `doctor/protocol.py` (`CheckResult` gains `detail`), `doctor/runner.py` (prints it), `doctor/checks/__init__.py` (registration) and tests. Contract: `prompts/bf-901-s3-doctor-token-accounting-view.md`.
- *D1 (surface).* A doctor check, plus a defaulted `detail` field on `CheckResult` (last, so every existing construction stands) that the runner prints under every outcome, after any remediation; an OK result still shows no remediation. A one-line check could not show the breakdown on a healthy vessel; a route needs the vessel running (considered, deferred); SIF checks are in-memory invariants.
- *D2 (read).* A new reader on a connection opened with the ConnectionFactory's `read_only` open (BF-906's pattern): it never creates, writes or migrates, so a journal from before BF-901 is read with an empty source. The journal's own readers need a started journal, whose `start()` migrates and creates tables, and they have no day or source grouping.
- *D3 (outcomes).* OK or WARN, never FAIL. WARN when the journal cannot be read, or when a row recorded since the earliest row with a token source names no model (BF-901 requires a model or `unknown`, so only a regression writes one). No WARN on `''` rows (a bypassed step records `''` legitimately) or on estimated-only spend (permanent on the proxy).
- *D4-D6 (aggregation).* Buckets in order: replayed (`cached`), mock (`model = 'mock'`), measured, estimated, uncharged (`''`), other; spend is measured plus estimated. Per tier, per intent and per UTC day from one grouped scan; exact integer sums; every tier, the top 8 intents, the newest 7 days. The journal's `''` is never passed to `crew_execution_usage`, whose validators reject it.
- *D7 (#1575's budget bullet, reclassification R-A).* None of the cost-aware features reads the journal; all read the agentic loop's charge, whose estimator S1 made the single owner. AD-1208's stop says "(usage estimated, not measured)" on an estimate, proven on a real loop and a real `TurnCostBudget` by S1's `test_an_estimated_loop_outcome_reaches_the_cost_stop_wording`; AD-1325 stores the source on every spend record; AD-1324 reads a pre-call prompt estimate, not spend. The AD-1323 approval card's rationale and its costed case carry no source (the turn's reply, which carries AD-1208's statement, does): filed as its own follow-up issue, linked in #1575's closing comment. Rejected: fixing the card in S3 (a governance-path change through the AD-1322 hook and the loop's calls), and keeping #1575 open for it. No control is weakened: the card behaves as before.
- *D8 (coverage).* The view says it covers journaled calls only; the agentic loop and the other calls that write no journal row are not in it (S2, consult decision 4).
- *Recorded, not repaired.* Each read statement holds a shared lock on the rollback-mode journal while it runs; the vessel's writer waits under its default busy timeout. A hot rollback journal left by a crash makes the read-only open fail until the vessel starts, which the check reports as WARN.
- *Reversal.* Revert the BF-901 S3 commit. Nothing persisted changes; the doctor loses the check and the `detail` field, which no other check sets.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`; both belong to the commit. Verify with `--check` and `tests/test_ad1184_ad_ledger.py` (M4), never by byte comparison (the snapshot pins volatile fields).

**Records the orchestrator adds before the commit:** a *Validation of record* bullet in this entry, before its *Reversal* line (the mutation campaign, base tree and the sha256 of each file in section 10 and of the new test file), then the ledger regeneration again.

**`docs/development/roadmap.md`:** no row (BF-900's contract, section 8, gives the grep).

## 9. What this does NOT change

- The cost-aware features' code, policies and defaults: AD-1208 (`turn_cost.py`), AD-1323 (`costed_continue_ask.py`, `economic_judgment_organ.py`), AD-1324 (`tier_policy.py`), AD-1325 (`economic_calibration.py`), and the agentic loop.
- The journal: no writer, reader, schema, migration or route changes (`journal.py`, `routers/journal.py`). The aggregate readers still sum measured and estimated together.
- `MockLLMClient` (its rows are still labelled measured; the view sets them apart by model name), the transport, the Copilot proxy, price tables, configuration (no field; `config/system.yaml` untouched).
- The doctor's exit code contract (WARN never counts), the other 23 checks, `build_context`, `__main__._cmd_doctor`.
- SIF.

## 10. Mutation rows (28 rows; whole stripped lines; each occurs once in its file after section 7)

Tier HIGH: every changed source file has rows. Run against `tests/test_bf901_s3_token_accounting_view.py` on the contract-applied tree, after an unmutated baseline run of that file that passes. The runner mutates each file in place and restores it before the next row.

| # | File | Line (stripped) | Mutate to | Killed by (the failing assertion) |
|---|---|---|---|---|
| Q1 | `src/probos/cognitive/journal_token_report.py` | `if replayed:` | `if False:` | T2: `assert report.total.tokens == {...}` (the replay lands in estimated) |
| Q2 | same | `if mock:` | `if False:` | T2: `assert report.total.tokens == {...}` (measured reads 132) |
| Q3 | same | `if source == TOKEN_SOURCE_ESTIMATED:` | `if False:` | T2: `assert report.total.tokens == {...}` (estimated lands in other) |
| Q4 | same | `if source == TOKEN_SOURCE_NONE:` | `if False:` | T2: `assert report.total.calls == {...}` (uncharged lands in other) |
| Q5 | same | `sql = _GROUPED_SQL.format(source=_SOURCE_COLUMN if has_source else _SOURCE_ABSENT)` | `sql = _GROUPED_SQL.format(source=_SOURCE_ABSENT)` | T1: `assert result.message == SPREAD_SUMMARY`; T2 |
| Q6 | same | `if not columns:` | `if False:` | T6[no_journal_table]: `assert result.outcome is CheckOutcome.OK` (the scan fails, WARN) |
| Q7 | same | `has_source = _SOURCE_COLUMN in columns` | `has_source = True` | T5: `assert result.outcome is CheckOutcome.OK` (no such column, WARN) |
| Q8 | same | `if first_labelled is not None and (labelled_since is None or first_labelled < labelled_since):` | `if first_labelled is not None and (labelled_since is None or first_labelled > labelled_since):` | T3: `assert result.outcome is CheckOutcome.WARN` (the boundary becomes day 2) |
| Q9 | same | `_NO_MODEL_SINCE_SQL = "SELECT COUNT(*) FROM journal WHERE model = '' AND timestamp >= ?"` | `_NO_MODEL_SINCE_SQL = "SELECT COUNT(*) FROM journal WHERE model = '' AND timestamp < ?"` | T4: `assert result.outcome is CheckOutcome.OK` (two earlier rows counted, WARN) |
| Q10 | same | `if chain_step:` | `if True:` | T4: the detail's last line (`2 (2 chain steps)`) |
| Q11 | same | `by_day=tuple(sorted(days.values(), key=lambda group: group.key, reverse=True)),` | `by_day=tuple(sorted(days.values(), key=lambda group: group.key, reverse=False)),` | T2: `assert [group.key for group in report.by_day] == ["2026-10-21", "2026-10-20"]` |
| Q12 | same | `return (-group.spend_tokens, -group.rows, group.key)` | `return (group.spend_tokens, -group.rows, group.key)` | T2: `assert [group.key for group in report.by_tier] == ["standard", "deep"]`; T1 |
| Q13 | same | `if labelled_since is not None and no_model_rows:` | `if False:` | T3: `assert result.outcome is CheckOutcome.WARN` |
| Q14 | same | `no_model_rows += count` | `no_model_rows += 0` | T4: the detail's last line ("none.") |
| K1 | `src/probos/doctor/checks/token_accounting_check.py` | `if not path.exists():` | `if False:` | T6[missing]: `assert result.outcome is CheckOutcome.OK` (the read-only open of a missing file raises, WARN) |
| K2 | same | `conn = await default_factory.connect(str(path), read_only=True)` | `conn = await default_factory.connect(str(path), read_only=False)` | T8: `assert recorder.read_only == [True]` |
| K3 | same | `except sqlite3.Error as exc:` | `except ValueError as exc:` | T7: the run raises `sqlite3.DatabaseError` |
| K4 | same | `if report is None or not report.rows:` | `if report is None:` | T6[empty_journal]: `assert result.message == ...` and `assert result.detail == ""` |
| K5 | same | `if report.no_model_since_labelled:` | `if False:` | T3: `assert result.outcome is CheckOutcome.WARN` |
| K6 | same | `return CheckResult(CheckOutcome.OK, _summary(report), "", detail)` | `return CheckResult(CheckOutcome.OK, _summary(report))` | T1: `lines.index("By tier:")` raises; T10 |
| K7 | same | `for bucket in (BUCKET_UNCHARGED, BUCKET_REPLAYED, BUCKET_MOCK, BUCKET_OTHER):` | `for bucket in ():` | T1: the tier lines `== [STANDARD_TIER, DEEP_TIER]` |
| K8 | same | `if not report.has_token_source:` | `if False:` | T5: `assert result.message == ...` (the "predates BF-901" clause) |
| K9 | same | `lines.extend(f"  {_describe(group)}" for group in report.by_tier)` | `pass` | T1: the tier lines; T10: `assert "    " + STANDARD_TIER in lines` |
| K10 | same | `register_check(_TokenAccountingCheck())` | `pass` | T11: `assert [kind for name, kind in registered if name == "token_accounting"] == ["_TokenAccountingCheck"]` |
| N1 | `src/probos/doctor/runner.py` | `if outcome is not CheckOutcome.OK:` | `if True:` | T9: `assert not any("ok-hidden-remediation" in line for line in lines)` |
| N2 | same | `for line in detail.splitlines():` | `for line in []:` | T9: `assert lines[ok + 1 : ok + 3] == [...]`; T10 |
| N3 | same | `_render(console, check.name, result.outcome, result.message, result.remediation, result.detail)` | `_render(console, check.name, result.outcome, result.message, result.remediation)` | T9; T10 |
| I1 | `src/probos/doctor/checks/__init__.py` | `token_accounting_check,` | `# removed` | T11 (the fresh interpreter imports only the package) |

No row for `detail: str = ""` in `protocol.py`: it is a field declaration, and removing it makes every four-argument construction raise `TypeError`. No row for `no_model_last_day = max(no_model_last_day, day_key)`: replacing `max` with the last group's day is observable only if SQLite returns the groups out of day order, which the tests do not control. It is presentation, and T3 to T5 pin the value on single-day sets.

Campaign of record: name the base tree and the sha256 of each mutated file and of the new test file; a later run whose hashes match does not repeat it.

## 11. Verified Against Codebase (2026-10-21, tree `305993682393802571dd9f83dc31923508bcac9a`, HEAD `96c0c730`)

| Claim | Evidence |
|---|---|
| `CheckResult` is frozen with `outcome`, `message`, `remediation=""`; docstring lines | `src/probos/doctor/protocol.py:22-33` (docstring `:26-28`) |
| `DoctorContext` fields | `protocol.py:36-55` (`config`, `home_dir`, `data_dir`, `config_path`, ...) |
| `_render` signature and body; OK returns early; remediation only on WARN/FAIL | `runner.py:138-152` |
| The call site and the WARN-does-not-count contract | `runner.py:196`, `:197-208`; the raised-check branch `:180-195` |
| `register_check` raises on a duplicate name | `registry.py:21-33` |
| The registration list | `doctor/checks/__init__.py:9-33`; `crew_enrollment_check` `:18`, `security_check` `:19` |
| BF-906's read-only pattern | `crew_enrollment_check.py:38-55` (`:43` `default_factory.connect(str(path), read_only=True)`, `:47` busy timeout), the WARN remediation text `:74-77`, `:102` registration |
| The read-only open | `storage/sqlite_factory.py:18-38` (`:36` `mode=ro`, `:37` no timeout passed) |
| `DatabaseConnection.execute`, `fetchall`, `fetchone` | `protocols.py:325-350` |
| The journal file name and directory | `startup/communication.py:669-672` |
| The journal schema | `cognitive/journal.py:22-47` (`timestamp REAL` `:24`, `tier` `:27`, `model` default `''` `:28`, `total_tokens` `:31`, `intent` `:33`, `cached` `:35`, `dag_node_id` `:40`, `token_source` `:46`) |
| `start()` migrates and creates; only `foreign_keys` is set | `journal.py:197-227`, `:204`; the `token_source` `ALTER` `:215` |
| `record()` keywords; one commit per row | `journal.py:375-402`, `:426` |
| The spend readers and their filter | `journal.py:835-944` (`cached = 0` at `:849`, `:859`, `:890`, `:913`; allowlist `:909`) |
| The `st:` prefix and `unknown` | `sub_task.py:587`, `:595`, `:659`, `:669`, `:678-679` |
| `TOKEN_SOURCE_NONE`; `charge_completion`; `answered_model_name` | `cognitive/token_accounting.py:26`, `:161-205`, `:228-236` |
| `TokenSource` and the validator that rejects `''` | `crew_execution_usage.py:11-14`, `:27-35` |
| The mock client's model name | `cognitive/llm_client.py:2918` (and ten more `model="mock"` sites to `:3065`) |
| AD-1208 reads the outcome's total and source; the estimated wording | `cognitive/turn_cost.py:245-252`, `:79`, `:263-271`, `:289-293` |
| S1's cross-seam test | `tests/test_bf901_s1_token_accounting.py:359-373`; the provider tests `:115`, `:123`, `:133`, `:144`, `:165`, `:175`; `:251`, `:273` |
| AD-1323: the case, the hook, the card | `economic_judgment_organ.py:709-721` (`CostedCase`, no source field), `:146` (protocol `note_charge`), `:869-876`, `:878-899`; `costed_continue_ask.py:33-37`, `:89-120`, `:123-142`, `:248-257`; the loop's calls `agentic_loop.py:1833`, `:1947` |
| The AD-1323 turn reply carries AD-1208's stop | `cognitive_agent.py:5038-5066` |
| AD-1325's spend records carry the source | `agentic_loop.py:1229-1251`; `economic_calibration.py:26-46` (`token_source` `:36`), `:873-874` |
| AD-1324 reads a prompt estimate | `tier_policy.py:385`, `:428` |
| The journal's size | `cognitive/storage_declarations.py:79-85` (152.3 MB, 350,567 rows at AD-1265's measurement) |
| Doctor tests' constructions and fixtures | `test_ad801_doctor.py:28-38` (fixture), `:47`, `:50-55`; `test_ad1137_doctor.py:174`, `:1218`; `test_ad484_ux_adoption.py:202`, `:229-234` |
| Registry order pins | `test_bf906_doctor_check.py:328-350` (probe), `:442-462` (recorder); `test_ad1328_s2a_startup_and_doctor.py:701-705`; `test_ad1327_verifier_independence.py:911-912`; `test_bf908_crew_scope_token.py:1092` |
| Async tests need no marker | `pyproject.toml:181` (`asyncio_mode = "auto"`) |
| The doctor may import cognitive modules at module scope | `doctor/checks/llm_check.py:34`, `verifier_check.py:17` |
| The tracker anchors | `PROGRESS.md:1-3`; `DECISIONS.md:519` (S2 heading), `:529` (S2 *Reversal*), `:531` (next heading) |

## Absence Verified (2026-10-21)

```
CLAIM: ProbOS never streams (the streamed test clause is not applicable)
RUN:   Grep "\"stream\":\s*True|stream\s*=\s*True|stream_options" src/probos/
FOUND: nothing
HOLDS: yes

CLAIM: the six journal write sites are S2's; nothing else writes journal rows
RUN:   Grep "journal\.record\(|\.record_chain_trace\(" src/probos/
FOUND: cognitive_agent.py:3698, :3736, :4529; sub_task.py:589, :661, :727
RUN:   Grep "INTO journal\b" src/probos/
FOUND: cognitive/journal.py:408 only
HOLDS: yes -- the agentic loop writes no journal row (the view's coverage line)

CLAIM: the journal sets no journal mode (rollback mode; a reader creates no side file)
RUN:   Grep "PRAGMA" src/probos/cognitive/journal.py
FOUND: :204 (foreign_keys), :259 (table_info)
HOLDS: yes

CLAIM: nothing outside the doctor package consumes CheckResult or renders a doctor result
RUN:   Grep "CheckResult|\.remediation\b|run_doctor|iter_checks" src/probos/
FOUND: doctor/*, doctor/checks/*; crew_token_cli.py:107-108 and security/crew_scope.py:329 (a posture's own
       remediation, not a CheckResult); __main__.py:1856-1879 (calls run_doctor); sif.py (SIFCheckResult)
HOLDS: yes

CLAIM: every test check returns a CheckResult, with at most three arguments
RUN:   Grep "def run\(self, ctx" tests/
FOUND: test_ad1137_doctor.py:172, :1220; test_ad484_ux_adoption.py:201; test_ad801_doctor.py:46, :120 (raises)
HOLDS: yes

CLAIM: no test pins CheckResult's field set
RUN:   Grep "fields\(CheckResult|CheckResult\.__dataclass_fields__|asdict\(result" tests/
FOUND: asdict(result) in five files, none on a doctor result (agentic, crew-token, fault, tool-delivery, social)
HOLDS: yes

CLAIM: no test pins the full list of registered doctor checks
RUN:   Grep "iter_checks" tests/
FOUND: test_ad1327...:911, test_ad1328_s2a...:636, :702, test_ad484...:229, test_ad801...:75,
       test_bf906_doctor_check.py:338, test_bf908...:1092 -- counts, one name, and the extras/verifier adjacency
HOLDS: yes

CLAIM: importing the reader from the doctor adds no import cycle
RUN:   Grep "from probos\.doctor|import probos\.doctor" src/probos/
FOUND: the doctor package itself, and __main__.py:1871-1872 (call-site imports)
HOLDS: yes -- nothing the reader imports reaches the doctor

CLAIM: the new names are free
RUN:   Grep "journal_token_report|JournalTokenReport|SpendBuckets|token_accounting_check|_TokenAccountingCheck|GroupSpend|\"token_accounting\"" --glob "*.py"
FOUND: nothing
HOLDS: yes (GroupUsage is introduced here; the doctor check name token_accounting is free:
       Grep "name: str = \"" src/probos/doctor/checks/ lists 23 other names)

CLAIM: AD-1323's costed case carries no token source
RUN:   Read economic_judgment_organ.py:709-721
FOUND: spent, budget, value_band, stakes, verified, signals, recent_step_deltas, value_provenance, stakes_provenance
HOLDS: yes -- the D7 follow-up
```

## 12. Deterministic gate checks, resolved up front

| Check | Result |
|---|---|
| Phantom-API precheck, pattern 3 (`Name(`) | Every capitalised call in this contract is a ProbOS symbol (`CheckResult`, `DoctorContext`, `CognitiveJournal`) or is defined here (`GroupUsage`, `JournalTokenReport`, `_TokenAccountingCheck`, `_Stub`, `_RecordingFactory`). The third-party Rich `Console` and the standard-library argparse `Namespace` are imported as `_Console` and `_Namespace`: a leading underscore leaves no word boundary before the capital letter, so the pattern does not match. `Path` is on the precheck's standard-library list (`phantom-api-precheck.ps1:59-71`); `datetime(` is lower case. `COALESCE` is not a ProbOS class: it is the SQL function in the reader's grouped query, which the pattern reads as a constructor call and the symbol check cannot find (the orchestrator's dry run flagged it on 2026-10-22; this sentence is the comment-only repair, and no code in this contract changes) |
| Phantom-API precheck, pattern 2 (`Name.attr`) | Prose names only existing members (`CognitiveJournal.record`, `start`, `get_token_usage_by`; `TurnCostBudget.render_stop`; `EconomicTurnHandle.note_charge`, `costed_case`). `sqlite3.Error`, `datetime.fromtimestamp`, `timezone.utc` and `pytest.MonkeyPatch` are lower-case receivers, or ones the precheck already skips |
| Phantom-API field check (`phantom_api_ast_helper.py:883-950`) | It indexes the tree it runs on, where `CheckResult` has no `detail`. Every construction that passes a detail does so **positionally** (sections 7.4 and 7.6), so no `detail=` keyword appears. Prose never writes the class name followed by `.detail`; `result.detail` reads go through an unresolved local. `GroupUsage` and `JournalTokenReport` are not in the index (unknown classes are skipped, `:931-933`) |
| Layer import | `doctor` -> `cognitive` at module scope has a precedent (`llm_check.py:34`, `verifier_check.py:17`); `cognitive/journal_token_report.py` imports `cognitive.token_accounting` and `crew_execution_usage`, as `token_accounting.py:22` does. Run `tests/test_layer_boundaries.py` (M2) |
| db-connect | No raw `connect` in `src/`: the check uses the approved factory's `read_only` open (BF-906). The tests use `aiosqlite.connect` on `tmp_path`, as `test_ad658a_chain_trace_token_split.py:129` does |
| srp-size | New classes are small (the reader module about 170 lines, the check about 160); `_render` gains 5 lines; no class near 500 lines |
| unowned-task | None |
| config reference and facade | No config field; `config/system.yaml` untouched |
| store registry | No store added; the journal's declaration (`cognitive/storage_declarations.py:68-91`) lists no readers |
| AD-1343 seam census | No `.complete(` call added; run `tests/test_ad1343_seam_registry.py` (M3) |
| Hidden pins | The registry order tests (section 5); `test_ad801_doctor.py`'s runner semantics (exit code, WARN does not count), which T9 re-asserts |
| Ledger | M4 |

## 13. What I could not verify here, and Prior Art

- **Not run:** no test, no precheck, no mutation run (a read-only consult). The expected strings in section 7.6 were derived by hand from the code in sections 7.3 and 7.4; the Builder's M3 run is their first check.
- **Rich:** `Console(record=True)` with `export_text()` returns the printed text without markup, and `soft_wrap=True` at width 240 does not wrap these lines. That is the documented behaviour, not run here.
- **SQLite:** a non-database file raises `sqlite3.DatabaseError` at the first schema read (`PRAGMA table_info`). The standard library's default connection timeout is 5 s, which bounds how long the vessel's writer waits on the doctor's shared lock. Both are documented behaviour, not run here.
- **The live journal** (152 MB, 350k rows): the grouped scan's run time is unmeasured. One scan plus at most one indexed count (`idx_journal_timestamp`, `journal.py:50`) is expected to take under a second; running `probos doctor` on the Captain's machine is the measurement.
- **Prior art.** Langfuse records provider-reported ("ingested") usage, falls back to tokenizer-inferred usage when it is missing, gives ingested values precedence, and does not infer usage for reasoning models because the inference undercounts (https://langfuse.com/docs/model-usage-and-cost). Absorbed: the same measured-over-estimated precedence (S1) and showing the two apart (this view). The reasoning-model limit is noted under For the register. OpenTelemetry's GenAI conventions record `gen_ai.usage.input_tokens` beside `gen_ai.response.model` (https://opentelemetry.io/docs/specs/semconv/gen-ai/openai). They are a span-attribute standard with no measured/estimated distinction; not adopted, since ProbOS exports no GenAI spans (considered, deferred). `docs/research/reference-projects.md` lists no usage-accounting project, so no overdue row applied (date used 2026-10-21; none examined, none updated).
- **Blind spots named:** the view covers journaled calls only (D8); a hot rollback journal left by a crash makes the read-only open fail (WARN) until the vessel starts and rolls it back; a clock set backwards could date a row after the boundary wrongly (the view would under-report, never false-warn, unless an old build runs again, which is itself a true WARN).

## 14. Diff Reviewer: properties to verify

1. Nothing in the change can write to, create or migrate `cognitive_journal.db`: the only open is `default_factory.connect(..., read_only=True)`, and every statement the reader runs is a `SELECT` or a read-only `PRAGMA`.
2. A missing file, a database with no `journal` table, an empty `journal`, and a `journal` without `token_source` each give OK; an unreadable file gives WARN; no path gives FAIL or raises out of `run`.
3. Each row is counted in exactly one bucket, in the stated order (replayed, mock, measured, estimated, uncharged, other); spend is measured plus estimated only.
4. WARN for a missing model fires only for rows with `model = ''` recorded at or after the earliest timestamp of a row with a non-empty `token_source`, across all groups.
5. `CheckResult.detail` is the last field and defaulted; every existing construction (positional and keyword) is unaffected; the runner prints `detail` on every outcome and remediation only on WARN or FAIL, as before.
6. `run_doctor`'s return value and closing line are unchanged in meaning (WARN never counts).
7. The check is registered once, after `crew_enrollment`, and the `extras` -> `verifier_independence` adjacency holds.
8. No journal label is passed to `crew_execution_usage`; no cost-aware feature's code is touched.
9. The tracker texts describe the reclassification (D7) and the coverage limit (D8) and do not claim the view shows all spend.

## 15. Acceptance criteria

1. The doctor shows tokens per tier, per intent and per UTC day, with measured and estimated reported separately and replayed, mock and uncharged rows apart (T1, T2, T10; Q1 to Q5, Q11, Q12, K6, K7, K9).
2. The read is read-only and degrades without a FAIL on a missing, empty, unreadable or pre-BF-901 journal (T5 to T8; Q6, Q7, K1 to K4, K8).
3. A row recorded since token sources began that names no model warns; earlier ones are counted with their chain-step split and last day (T3, T4; Q8 to Q10, Q13, Q14, K5).
4. The runner prints `detail` under every outcome without showing an OK result's remediation (T9; N1 to N3).
5. The check is registered once, in order (T11; K10, I1).
6. #1575's acceptance is settled bullet by bullet in DECISIONS.md, with the AD-1323 card's missing source filed as a linked follow-up issue before #1575 is closed (D7).
7. Every mutation row in section 10 is killed by the named assertion.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
