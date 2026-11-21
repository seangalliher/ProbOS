# AD-1302 S1: the currency of borrowed Ship's Records claims in an agent's working context, observed at the tool sink in shadow

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-02
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-02 (fresh-read review: the config field's three frozen consumers, four test specs that could not kill their mutants, two unenrolled populations, the I11 carrier census; see §15)

**Status:** build-ready draft. This is slice 1 of AD-1302 (#1355). It does not close the issue. **Tier HIGH**, because it adds a statement to `ToolRegistry.check_and_invoke`, the one tool sink, and to `CognitiveAgent.handle_intent`, the intent entry. No new AD or BF number. **Base:** `main` `632f2c87`, tree `c4a3c09f028413b00b593fe3c2ebfc92f85acb4e`. **Captain:** this slice needs no Captain decision (D12). The later switch from observing to telling the agent, and then to refusing, does (§13, "What comes after S1").

**Milestones:** M1 is the code and tests in §7. M2 is the trackers in §8. Each milestone is one Builder delegation and one local commit. The broad gate is the orchestrator's single canonical run, once, after M2: `scripts/run_test_gate.py --label ad1302-s1 --receipt logs/gates/ad1302-s1.receipt.json`. The Builder runs only the focused gates in §6.

**Tests:** one new file, `tests/test_ad1302_s1_claim_currency.py`, with 14 functions (T1 to T14). One existing frozen table changes by one key, `EXPECTED_DUMPS["RecordsConfig"]` in `tests/test_ad1270e2f_knowledge_models.py`, and two generated artifacts are regenerated, `docs/development/config-facade-baseline.yaml` and `docs/development/config-reference.md` (§7.1, §5 row 10). No other existing test changes (§5, row 9).

**Line endings:** the working copies are CRLF (`core.autocrlf=true`). The SEARCH blocks are LF, so match and write using each file's own line endings. Write new files with LF.

**Worktree:** `config/system.yaml` carries the Captain's uncommitted local edits. Do not stage it, and do not add the new config field to it. Stage files only by explicit path. Never use `git add -A`.

---

## 0. Premise: what is present on this tree

| # | Fact | Evidence |
|---|---|---|
| P1 | `compute_claim_id` hashes `(title, claim, basis)`, so it identifies content. A corrected finding has a different id. | `src/probos/knowledge/claims.py:23-31` |
| P2 | `publish_finding` writes each finding to `notebooks/<callsign>/<slug>-<claim_id[:8]>.md`. A corrected finding therefore lands at a **new path**, and nothing links it to the old one. | `src/probos/tools/publish_finding_tool.py:654-657`, `:691-699` |
| P3 | A rewrite of the **same path** through `write_entry` increments `revision`. The first write has no key, which means revision 1. | `src/probos/knowledge/records_store.py:316-325`; `src/probos/knowledge/provo.py:253-270` |
| P4 | ProbOS already names a record's stable identity as `record:{path}@{revision}`. | `src/probos/knowledge/provo.py:126-137` |
| P5 | `RecordsStore.publish` rewrites `status` and `updated` but does not change `revision`. | `records_store.py:1085-1105` |
| P6 | AD-550 deduplication suppresses a write whose word-level Jaccard similarity to a recent entry (72 h by default) is 0.8 or higher. It applies on the same topic (Layer 2) and across the author's other notebooks (Layer 3). `publish_finding` calls it explicitly. | `records_store.py:616-763`, `:158-166`; `publish_finding_tool.py:660-680` |
| P7 | Borrowed Records text reaches an agent's context through `OracleService.query_formatted`, which the passive recall and the AD-696 lookup call, and through the `oracle_query` tool, which uses `query_with_provenance` and `_render`. Each Records result's metadata carries `path` and `frontmatter`. | `cognitive_agent.py:11716-11723`; `sub_tasks/query.py:274-280`; `oracle_query_tool.py:132-161`, `:260-261`, `:319-325`; `oracle_service.py:1075-1084`, `:1123-1134` |
| P8 | When both retrieval paths return the same record, the semantic path's payload wins. Its frontmatter comes from the index sidecar, which can lag the file on disk when a reindex failed. | `oracle_service.py:205-207`; `records_store.py:375-392` |
| P9 | The only existing "inherited" label covers the Ship's Archive (AD-1341 S2), not live Records. Records results are tagged `[ship's records]` and carry a byline. | `archive_store.py:402-439`; `oracle_service.py:745-760`, `:1083` |
| P10 | AD-1346 holds a work ticket in `CURRENT_TICKET` at three entries and checks it in shadow at the tool sink (`check_at`, `registry.py:398`). Test I10 pins each entry's last statement as a `Try` whose `finally` is exactly `<hold>.end()`. | `admission/carrier.py:24`; `cognitive_agent.py:7986-7992`; `tests/test_ad1346_admission_ticket_issue.py:551-578` |
| P11 | At invocation, `required` defaults to `READ` and almost no caller passes it, so the tool sink cannot tell a consequential call from a read today. | `tools/context.py:112`; `registry.py:368`; Absence AV5 |
| P12 | AD-1300 (#1353) is planned and not implemented. It has no code pattern to reuse, only a stated principle. | `DECISIONS.md:10886-10888`; `gh issue view 1353`: OPEN |

## 1. Problem

AD-1302 plans reassessment for **stored** derivations. Nothing covers a claim already assembled into an active agent's context. Suppose an agent reads a crewmate's Records entry at revision 1 and the author then corrects it to revision 2. Mid-task, the agent still holds revision 1 and can act on it. Nothing records which revisions entered the context (Absence AV2), so nothing can notice. Asking the model to re-check does not work. In arXiv 2608.25553, agents checked provenance in about one episode in five and made stale-consistent decisions in 74.7% to 77.3% of superseded episodes. This matches the LLM Independence principle: the check has to be infrastructure.

## 2. Solution overview

1. **Ledger.** `handle_intent` opens a per-intent `ContextClaimLedger` in a context variable for the duration of the intent's work.
2. **Note at render.** Wherever a Records result becomes text the agent reads, the ledger records `(path, revision, updated, author, reader, via, noted_at)`. That covers `query_formatted`'s emitted lines and the `oracle_query` tool's rendered entries. Only results actually shown are noted.
3. **Check at the tool sink, in shadow.** `ToolRegistry.check_and_invoke` asks a `ClaimCurrencyMonitor` to compare every noted revision with the store's current revision **on disk, for the same reader**. The monitor counts each disposition and logs the first non-fresh finding for each ledger and claim. **Nothing is refused, no text changes, no event is emitted, and no episode is touched.**
4. **Population census.** A test freezes the list of Oracle consumers in `src` and which of them are enrolled. Every other consumer is declared unknown.

S1 measures how often an agent reaches an effect point holding a claim that has since changed. That figure decides whether the later slices are worth building.

## 3. Decisions

- **D1 (identity).** The stable identity is the Records path plus the store's revision, the same identity as P4. `claim_id` is rejected as the identity because it changes with every correction (P1). A correction that lands at a **new path** (P2) is not linked by S1, and is reported unknown in §9. S2 owns the authorized supersession link.
- **D2 (the ledger's carrier).** The ledger has its own `ContextVar`, `CURRENT_CLAIM_LEDGER`, and holds one **mutable** ledger object. Tasks created inside the scope copy the context, so they share the object: notes made in a child task are visible at the parent's sink. The ledger is not keyed on the AD-1346 ticket, for three reasons. The ticket is None when its issue is refused or `admission.shadow_enabled` is false. AD-1346 M4 may replace the carrier (`carrier.py:11`). And the ledger is not an admission decision. Rejected: setting the variable lazily at the first note. A set made inside an awaited coroutine persists in the agent's long-lived task, so it would leak one intent's claims into the next. **No new or changed `src` file may contain the text `CURRENT_TICKET`, not even in a comment or docstring:** AD-1346 I11 (`tests/test_ad1346_admission_ticket_issue.py:581-598`) freezes the set of files that name it to `admission/carrier.py` and `admission/service.py`.
- **D3 (the scope's place).** The scope is `with claim_ledger_scope():` inside `handle_intent`'s existing `try` body, wrapping the one `return await self._handle_admitted_intent(intent)`. This keeps I10's invariants: the last statement stays the `Try`, its `finalbody` stays `_intent_hold.end()`, it has no handlers, and `_intent_hold` is read once. Only the intent entry is enrolled. Consultation and standalone agent runs are unknown (§9). A run awaited inline from an intent inherits the intent's ledger.
- **D4 (noting).** `OracleService.note_shown_records(items, *, agent_id, via)` resolves the reader with the same `_resolve_records_reader` that `query` used, then calls `probos.knowledge.claim_currency.note_shown_records`. Only `source_tier == "records"` is noted. Archive, operational, semantic, graph and health are not. `query_formatted` passes only the results it appended before its `max_chars` break. The tool passes `envelopes[:rendered]`. Outside a scope, noting returns 0 and does nothing. The output text of both renderers is byte-identical with and without a scope (T6, T7).
- **D5 (what counts as known).** The shown revision is known only when `frontmatter` is a non-empty `dict` with a non-empty `updated`. The revision is then `frontmatter.get("revision", 1)` under P3's rule, where `bool` is excluded and the range is 1 to 2^31-1. Anything else is noted with `revision=None` and checks as `unknown_identity`. This is necessary because an empty semantic sidecar would otherwise be read as revision 1.
- **D6 (the current revision).** The current revision comes from the new synchronous `RecordsStore.current_revision(path, *, reader_id, reader_department, scope="ship")`, which reads the file on disk and **never** the semantic index (P8). It re-applies `record_is_readable` for the reader recorded at noting time. A record the reader may no longer read returns `withheld` with no revision, so a reclassified record discloses nothing. It is synchronous because it does only the local file read that `read_entry` already does, so the sink statement awaits nothing. Its default `scope="ship"` is the scope Tier 2 retrieves at (`_RECORDS_QUERY_SCOPE = "ship"`, `oracle_service.py:69`), so a record the Oracle could show is never `withheld` by scope alone.
- **D7 (dispositions).** `fresh`: same revision and same `updated`. `stale`: the current revision is higher. `regressed`: the current revision is lower, as after `write_entry`'s exception path at `records_store.py:335-336`. `changed_same_revision`: same revision but a different `updated`, as after `publish` (P5). `missing`: no file, or a path under `_archived/`. `withheld`: no longer readable by the reader. `unknown`: unreadable, malformed or traversal. `unknown_identity`: D5. At the sink level there are also `no_ledger`, `empty_ledger` and `unchecked`, which counts the claims beyond the per-sink cap of 16. Only `stale` is the correction signal. `regressed` and `changed_same_revision` are counted separately and never reported as stale.
- **D8 (the sink).** `currency_at(monitor, *, effect, tool_id, agent_id)` is one statement in `check_and_invoke`. It sits **after** the stop refusal and the tool-existence check, so neither a refused call nor a call to a tool that does not exist is an effect point, and before the permission check. It applies to every call that reaches it through the ship's registry (a correction session's projected registry is not wired: §9). S1 does not classify which calls are consequential, because `required` cannot tell them apart (P11). Classifying them is the enforcement slice's job. The statement follows `check_at`'s contract: it calls only an exact `ClaimCurrencyMonitor`, returns None, awaits nothing and lets no `Exception` out.
- **D9 (observability).** The monitor keeps an in-memory tally of `(effect, disposition)` under a `threading.Lock`, plus a `failures` count. It logs one INFO line, marked `AD-1302 S1 claim currency`, the first time each ledger finds a given `(path, shown revision, disposition)` that is not fresh. That line is greppable in `probos.log`, which supports the producer-versus-consumer marker count. S1 persists nothing and emits no `EventType`. A Records path in an operator log is the same exposure as the existing `Record written:` INFO line (`records_store.py:394`).
- **D10 (switch).** `RecordsConfig.claim_currency_shadow_enabled: bool = True`. When it is false, the runtime builds no monitor, so the sink checks nothing, and the ledger still records in memory at negligible cost. The default is on for the same reason AD-1346's shadow is on: it changes nothing an agent sees.
- **D11 (memory).** S1 has no write path to episodic memory, notebooks or Records. The agent's memory of having read revision N is never rewritten, under Memory: optimize, never delete. T13 checks this by source scan.
- **D12 (Captain).** S1 needs no Captain decision. It weakens no control, changes no schema or public API, and changes nothing an agent sees or does. It extends the product objective only within the slice the Captain chose ("slice of AD-1302", Option A).

## 4. Milestones and focused gates

- **M1:** §7.1 to §7.7 and the new test file. Focused gate: `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1302_s1_claim_currency.py tests/test_ad1346_admission_ticket_issue.py tests/test_ad1346_admission_ticket_sinks.py tests/test_ad1346_admission_shadow_seams.py tests/test_ad1139_oracle_query_tool.py tests/test_bf679_oracle_records_reader_identity.py tests/test_ad1294_read_provenance_rendering.py tests/test_ad696_agentic_oracle_retrieval.py tests/test_ad1341_s2_inherited_label.py tests/test_ad1270e2f_knowledge_models.py tests/test_ad1270e1_config_facade.py tests/test_config_reference_current.py tests/test_ad1343_stop_seam_inventory.py -q -n 0`, then `d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_profiles.py --check` (a default-True boolean should not touch the profile manifest; confirm it).
- **M2:** §8 only. No test run is needed: a docs-only commit.

## 5. Consumers of every value this changes

| # | Changed | Consumer | Accepts because |
|---|---|---|---|
| 1 | `handle_intent` try body | I10 (`test_ad1346_admission_ticket_issue.py:551-578`) | It pins only the last `Try`, its `finalbody` and handlers, and the one read of the hold. The `with` sits inside `body`. |
| 2 | `handle_intent` try body | tests that monkeypatch `_handle_admitted_intent` (`:480`, `:502`, `:515`) | The `with` still awaits that attribute, and the cancel and raise paths run its `finally`. |
| 3 | `check_and_invoke` gains one statement | AD-1346 census of `shadow_at`, `hold_at` and `check_at` | The new callee is `currency_at`, which no census names. Before writing, grep `tests/test_ad1346_*` for any count of statements in `check_and_invoke`. |
| 4 | `query_formatted` | its output | No byte changes (T6). |
| 5 | `OracleQueryTool.invoke` | its output and metadata | No byte changes (T7). Test doubles without `note_shown_records` fall to the log-and-degrade branch. |
| 6 | `RecordsConfig` | `ProbOSConfig` load and the zero-config boot | It has a default. Do not add it to `config/system.yaml`. |
| 10 | `RecordsConfig` gains a field | three frozen consumers: `EXPECTED_DUMPS["RecordsConfig"]` (`tests/test_ad1270e2f_knowledge_models.py:212-239`, read by `:424-428` and `:446-448`); `docs/development/config-facade-baseline.yaml:3054` (`scripts/check_config_facade.py --check`, run by `tests/test_ad1270e1_config_facade.py:1800`); `docs/development/config-reference.md:673` (`scripts/gen_config_reference.py --check`, run by `tests/test_config_reference_current.py:41-59`) | Updated in §7.1 by one key, one baseline line and one table row. Each diff must be exactly that; any other drift is a stop-and-report. |
| 7 | `RecordsStore` new method and dataclass | nothing else in `src` | Additive. |
| 8 | `runtime.claim_currency` | the tool registry | It is assigned before `set_claim_currency`. |
| 9 | Existing `?raw` source scans | `tests/test_ad1294_*`, `tests/test_ad696_*`, `tests/test_ad1341_s2_*` | Before editing, grep each for the exact lines §7.4 and §7.5 change. If one pins a changed line, stop and report it. Do not change the test. |

## 6. Tests (`tests/test_ad1302_s1_claim_currency.py`)

Use a real `RecordsStore` on `tmp_path`, with `auto_commit` off when the config allows it, and a real `OracleService` on its keyword path. For T11 and T12, boot a real runtime as `tests/test_ad1346_admission_ticket_issue.py` does (`_boot`). Do not use mocks for the store, the Oracle or the registry.

- **T1** `claim_ledger_scope`: it sets a fresh ledger and restores the outer one when nested. After exit it closes the ledger and the variable is None. Outside a scope, `note_shown_records` returns 0.
- **T2** A task created inside the scope notes into the same ledger, and the parent sees the note. A task that outlives the scope cannot note after close: `note` returns False.
- **T3** Identity rules (D5): revision absent → 1; `True`, `0`, `-1`, `"2"` and `2**31` → None; `{}` and a frontmatter without `updated` → None; a non-records tier, an empty or non-`str` path, and an archive-tier item are not noted. The non-records and archive items must carry a valid `str` `path` and a frontmatter with `updated`, so only the tier filter keeps them out (otherwise CC-4 survives). Duplicates under the same `(path, revision, reader)` are noted once. The cap of 64 counts the overflow in `dropped`.
- **T4** `current_revision`: present at revision 1, then 2 after `write_entry`; missing; `_archived/x.md` → missing; `../x` → unknown, never raising; malformed YAML → unknown. An entry reclassified to `private` returns `withheld` with revision None for another reader and present for its author. `captain` is unrestricted.
- **T5** `classify` table, one case per disposition, with `changed_same_revision` produced by a real `RecordsStore.publish`.
- **T6** `query_formatted` inside a scope, with two Records hits and a `max_chars` that admits exactly one: one note, for the emitted path, with `via="oracle.query_formatted"`. The output is byte-identical inside and outside a scope.
- **T7** The `oracle_query` tool notes exactly `envelopes[:rendered]`. Use a real `OracleService` subclass that overrides only `query` to return ten Records-tier `OracleResult`s with distinct paths and full frontmatter, so `_render` stops at `_MAX_RESULTS = 8` (`oracle_query_tool.py:70`). Assert the premise `metadata["returned_count"] < metadata["candidate_count"]`, then that the ledger holds exactly the first `returned_count` paths (otherwise CC-6 survives). A fake oracle lacking `note_shown_records` returns the same `output` and `metadata` inside a scope as outside one, and logs at DEBUG.
- **T8** Monitor: with no ledger, it counts `no_ledger` and calls `current_revision` zero times. Monkeypatch `current_revision` with a call recorder and assert zero calls and `failures == 0`. Do not make the patch raise: `check` swallows any `Exception`, so a raising patch would pass. With an empty ledger, it counts `empty_ledger`. With 20 distinct refs, it checks 16 and counts `unchecked` as 4.
- **T9** If the store raises, `check` raises nothing: `failures == 1`, WARNING the first time and DEBUG after. `currency_at` with None, or with a duck-typed double that has `check`, does nothing.
- **T10** Three sink calls on one stale claim: the tally counts `stale` 3 times, and there is exactly one INFO line carrying `path=`, `shown_revision=1` and `current_revision=2`.
- **T11** **The crossing, the golden test.** Boot a real runtime with a real crew agent and seed a `ship`-classified record by another author. Monkeypatch `crew._handle_admitted_intent` to: (a) call the runtime's real `OracleService.query_formatted` for that crew agent; (b) `write_entry` a correction to the same path, so it is at revision 2; (c) call `rt.tool_registry.check_and_invoke(crew.id, <a stub READ tool registered on the real registry>, {})`. Then call `crew.handle_intent(...)` and assert four things: the **delta** of `rt.claim_currency.tally()` across this run has `(SEAM_TOOL, "stale") == 1` (take a snapshot before each run; the control and reclassification runs share the runtime); the INFO line is present and names `agent=<crew.id>`; the tool result's `output`, `error` and `metadata` equal those of a control run without step (b), so nothing was refused (do not compare `duration_ms`); and `CURRENT_CLAIM_LEDGER.get() is None` after return. Repeat with step (b) reclassifying the record to `private`, and expect `withheld`.
- **T12** With the switch off (`records.claim_currency_shadow_enabled=False`), `rt.claim_currency is None` and T11's flow gives the same tool result while counting nothing.
- **T13** Source scans, by AST, never by raw text (the module docstring says "no event is emitted", which a substring scan for `emit` would flag). `claim_currency.py` imports nothing from `probos.cognitive`, and no `ast.Name`, `ast.Attribute` or imported name in it is or contains `episodic`, `write_entry` or `emit`. The sink statement in `check_and_invoke` comes after the `self._tools.get(tool_id) is None` check. `handle_intent`'s last `Try` body holds the `with claim_ledger_scope()`.
- **T14** **Oracle consumer census.** Regex `oracle\w*\.(query|query_formatted|query_refs)\(|query_with_provenance\(` over `src/probos/**/*.py`, frozen per file (§9). A new consumer fails the test with a message naming it, and the developer must classify it as enrolled or unknown.

**Mutation table** (whole-line edits, each restored before the next; the named killer must fail):

| Row | File | Mutation | Killer |
|---|---|---|---|
| CC-1 | `claim_currency.py` | `>` → `>=` in `classify`'s stale test | T5 |
| CC-2 | `claim_currency.py` | drop the `ref.revision is None` branch | T3/T5 |
| CC-3 | `records_store.py` | drop the `record_is_readable` check in `current_revision` | T4, T11 (withheld) |
| CC-4 | `claim_currency.py` | drop the `tier != "records"` filter | T3 |
| CC-5 | `oracle_service.py` | note `results` in place of `shown` | T6 |
| CC-6 | `oracle_query_tool.py` | note `envelopes` in place of `envelopes[:rendered]` | T7 |
| CC-7 | `claim_currency.py` | remove the `reset(token)` | T1 |
| CC-8 | `cognitive_agent.py` | remove the `with claim_ledger_scope():` line, de-indenting the return | T11, T13 |
| CC-9 | `registry.py` | delete the `currency_at(...)` line | T11 |
| CC-10 | `claim_currency.py` | `currency_at` calls any object with `check` | T9 |
| CC-11 | `claim_currency.py` | remove `check`'s `except Exception` | T9 |
| CC-12 | `claim_currency.py` | remove the 64-ref cap | T3 |
| CC-13 | `claim_currency.py` | `first_report` always returns True | T10 |
| CC-14 | `runtime.py` | build the monitor regardless of the switch | T12 |

Record the campaign of record in the DECISIONS bullet in the AD-1346 form: tree, sha256 of each mutated file, and killers.

## 7. The contract

### 7.1 `src/probos/config_models/knowledge.py`

SEARCH:
```python
    # AD-1138: index records into SemanticKnowledgeLayer and serve Oracle
    # Tier 2 from it. Default-OFF — when False, Tier 2 uses the keyword path.
    semantic_index_enabled: bool = False
```
REPLACE:
```python
    # AD-1138: index records into SemanticKnowledgeLayer and serve Oracle
    # Tier 2 from it. Default-OFF — when False, Tier 2 uses the keyword path.
    semantic_index_enabled: bool = False
    # AD-1302 S1: compare the Records revisions an agent's context holds with the
    # store's current ones at the tool sink, in shadow (counted and logged, nothing
    # refused). False builds no monitor; the in-memory ledger still records.
    claim_currency_shadow_enabled: bool = True
```

Then update the field's three frozen consumers (§5 row 10), each by exactly one entry:

1. `tests/test_ad1270e2f_knowledge_models.py`, `EXPECTED_DUMPS["RecordsConfig"]` (`:212-239`): after `'semantic_index_enabled': False` add `'claim_currency_shadow_enabled': True`. The dump follows field order, so it goes last. Keep the file's existing formatting.
2. `d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --update-baseline`. The diff to `docs/development/config-facade-baseline.yaml` must be the one line `- {default: 'True', name: claim_currency_shadow_enabled}` after `:3054`.
3. `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py`. The diff to `docs/development/config-reference.md` must be the one table row after `:673`.

If either script's diff holds anything else, stop and report it; do not commit unrelated drift.

### 7.2 `src/probos/knowledge/records_store.py`

**Pair 1, imports.** SEARCH:
```python
from datetime import datetime, timezone
from pathlib import Path
```
REPLACE:
```python
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
```

**Pair 2, after `record_is_readable`.** SEARCH:
```python
    doc_author = frontmatter.get("author", "")
    if reader_id == doc_author:
        return True
    if doc_class == "department":
        return bool(reader_department) and reader_department == frontmatter.get(
            "department", "",
        )
    return False


def _jaccard_similarity(text_a: str, text_b: str) -> float:
```
REPLACE:
```python
    doc_author = frontmatter.get("author", "")
    if reader_id == doc_author:
        return True
    if doc_class == "department":
        return bool(reader_department) and reader_department == frontmatter.get(
            "department", "",
        )
    return False


#: AD-1302 S1: the states of ``RecordsStore.current_revision``.
REVISION_PRESENT = "present"
REVISION_MISSING = "missing"
REVISION_WITHHELD = "withheld"
REVISION_UNREADABLE = "unreadable"
_MAX_RECORD_REVISION = 2**31 - 1  # the bound probos.knowledge.provo applies


@dataclass(frozen=True, slots=True)
class RecordRevision:
    """AD-1302 S1: a record's current revision for one reader. ``withheld`` carries no revision (it discloses nothing)."""

    state: str
    revision: int | None = None
    updated: str = ""


def parse_record_revision(frontmatter: dict[str, Any]) -> int | None:
    """AD-1302 S1: the store's revision rule (P3): absent means 1; a non-int, a bool or an out-of-range value is unknown."""
    value = frontmatter.get("revision", 1)
    if type(value) is not int or not 1 <= value <= _MAX_RECORD_REVISION:
        return None
    return value


def record_updated_text(value: Any) -> str:
    """AD-1302 S1: ``updated`` as text, so a YAML-parsed timestamp and the JSON sidecar's string compare equal."""
    if type(value) is str:
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return ""


def _jaccard_similarity(text_a: str, text_b: str) -> float:
```

**Pair 3, after `read_entry`.** SEARCH:
```python
        return {"frontmatter": frontmatter, "content": content, "path": path}

    async def list_entries(
```
REPLACE:
```python
        return {"frontmatter": frontmatter, "content": content, "path": path}

    def current_revision(
        self,
        path: str,
        *,
        reader_id: str,
        reader_department: str = "",
        scope: str = "ship",
    ) -> RecordRevision:
        """AD-1302 S1: the revision on disk of the record at ``path``, for this reader.

        Synchronous: it does only the local file read ``read_entry`` does, so the tool sink awaits nothing. It reads
        the file, never the semantic index, whose sidecar can lag a failed reindex. It re-applies
        :func:`record_is_readable`, so a record reclassified past this reader is ``withheld`` with no revision.
        It never raises: traversal, an unreadable file or unparseable frontmatter is ``unreadable``.
        """
        if type(path) is not str or not path:
            return RecordRevision(REVISION_UNREADABLE)
        if path.startswith("_archived/"):
            return RecordRevision(REVISION_MISSING)
        try:
            file_path = self._safe_path(path)
            if not file_path.is_file():
                return RecordRevision(REVISION_MISSING)
            raw = file_path.read_text(encoding="utf-8")
            frontmatter, _ = self._parse_document(raw)
        except Exception:  # ValueError (traversal), OSError, UnicodeDecodeError: unknown, never raised to the sink
            return RecordRevision(REVISION_UNREADABLE)
        if type(frontmatter) is not dict or not frontmatter:
            return RecordRevision(REVISION_UNREADABLE)
        if not record_is_readable(
            frontmatter, scope=scope, reader_id=reader_id, reader_department=reader_department,
        ):
            return RecordRevision(REVISION_WITHHELD)
        return RecordRevision(
            REVISION_PRESENT,
            parse_record_revision(frontmatter),
            record_updated_text(frontmatter.get("updated")),
        )

    async def list_entries(
```

### 7.3 New file `src/probos/knowledge/claim_currency.py`

```python
"""AD-1302 S1 (#1355): the currency of borrowed Ship's Records claims in an agent's working context, in shadow.

A claim enters an agent's context when a Ship's Records result is rendered into text the agent reads. The ledger
records the record's stable identity, its path and the exact store revision shown (``record:{path}@{revision}``, as
``probos.knowledge.provo`` names it), with the reader it was retrieved for. At the tool sink the monitor compares each
noted revision with the store's current one on disk for that reader. In S1 it counts and logs, and changes nothing:
no call is refused, no text changes, no event is emitted, and no episode is touched. Only a claim's currency is
observed, never the agent's memory of having read it (Memory: optimize, never delete).

The ledger is a mutable object in ``CURRENT_CLAIM_LEDGER``, opened by ``claim_ledger_scope`` at the intent entry.
Tasks created inside the scope copy the context and so share the object: a note made in a child task is seen at
the parent's sink.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Final

from probos.knowledge.records_store import (
    REVISION_MISSING,
    REVISION_PRESENT,
    REVISION_WITHHELD,
    RecordRevision,
    RecordsStore,
    parse_record_revision,
    record_updated_text,
)

logger = logging.getLogger(__name__)

MAX_LEDGER_REFS: Final = 64
MAX_CHECKS_PER_SINK: Final = 16
_MAX_PATH_CHARS: Final = 4096

VIA_QUERY_FORMATTED: Final = "oracle.query_formatted"
VIA_ORACLE_QUERY_TOOL: Final = "oracle_query_tool"

FRESH: Final = "fresh"
STALE: Final = "stale"
REGRESSED: Final = "regressed"
CHANGED_SAME_REVISION: Final = "changed_same_revision"
MISSING: Final = "missing"
WITHHELD: Final = "withheld"
UNKNOWN: Final = "unknown"
UNKNOWN_IDENTITY: Final = "unknown_identity"
NO_LEDGER: Final = "no_ledger"
EMPTY_LEDGER: Final = "empty_ledger"
UNCHECKED: Final = "unchecked"


@dataclass(frozen=True, slots=True)
class ClaimRef:
    """One Records claim as it was shown: identity (path, revision), ``updated``, author, reader, and where."""

    path: str
    revision: int | None
    updated: str
    author: str
    reader_id: str
    reader_department: str
    via: str
    noted_at: float


class ContextClaimLedger:
    """The claims one intent's context was shown; bounded, deduplicated on (path, revision, reader)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._refs: dict[tuple[str, int | None, str, str], ClaimRef] = {}
        self._reported: set[tuple[str, int | None, str]] = set()
        self._dropped = 0
        self._closed = False

    def note(self, ref: ClaimRef) -> bool:
        """Record ``ref`` unless closed, already held or over the cap (counted in ``dropped``); True when recorded."""
        key = (ref.path, ref.revision, ref.reader_id, ref.reader_department)
        with self._lock:
            if self._closed or key in self._refs:
                return False
            if len(self._refs) >= MAX_LEDGER_REFS:
                self._dropped += 1
                return False
            self._refs[key] = ref
            return True

    def entries(self) -> tuple[ClaimRef, ...]:
        with self._lock:
            return tuple(self._refs.values())

    def first_report(self, ref: ClaimRef, disposition: str) -> bool:
        """True the first time this ledger reports ``disposition`` for this claim, so one finding logs once."""
        key = (ref.path, ref.revision, disposition)
        with self._lock:
            if key in self._reported:
                return False
            self._reported.add(key)
            return True

    def close(self) -> None:
        with self._lock:
            self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def dropped(self) -> int:
        return self._dropped


#: Created at module level, as the ``contextvars`` documentation asks.
CURRENT_CLAIM_LEDGER: Final[ContextVar[ContextClaimLedger | None]] = ContextVar("probos_claim_ledger", default=None)


@contextmanager
def claim_ledger_scope() -> Iterator[ContextClaimLedger]:
    """Open a fresh ledger for one unit of work; on exit close it and put back what the variable held before."""
    ledger = ContextClaimLedger()
    token = CURRENT_CLAIM_LEDGER.set(ledger)
    try:
        yield ledger
    finally:
        ledger.close()
        try:
            CURRENT_CLAIM_LEDGER.reset(token)
        except (RuntimeError, ValueError):  # PEP 567: a token already used, or one set in another context
            pass


def claim_ref_from_record(
    path: object, frontmatter: object, *, reader_id: str, reader_department: str, via: str,
) -> ClaimRef | None:
    """The ``ClaimRef`` of one shown Records result, or None for an unusable path. D5: the revision is known only
    when ``frontmatter`` is a non-empty dict with a non-empty ``updated``."""
    if type(path) is not str or not path or len(path) > _MAX_PATH_CHARS:
        return None
    revision: int | None = None
    updated = ""
    author = ""
    if type(frontmatter) is dict and frontmatter:
        updated = record_updated_text(frontmatter.get("updated"))
        if updated:
            revision = parse_record_revision(frontmatter)
        raw_author = frontmatter.get("author")
        author = raw_author if type(raw_author) is str else ""
    return ClaimRef(
        path=path, revision=revision, updated=updated, author=author,
        reader_id=reader_id, reader_department=reader_department, via=via, noted_at=time.time(),
    )


def note_shown_records(
    items: Iterable[tuple[object, object]], *, reader_id: str, reader_department: str, via: str,
) -> int:
    """Note each ``(source_tier, metadata)`` of tier ``records`` into the open ledger; the count noted (0 with none)."""
    ledger = CURRENT_CLAIM_LEDGER.get()
    if ledger is None or ledger.closed:
        return 0
    noted = 0
    for tier, metadata in items:
        if tier != "records" or type(metadata) is not dict:
            continue
        ref = claim_ref_from_record(
            metadata.get("path"), metadata.get("frontmatter"),
            reader_id=reader_id, reader_department=reader_department, via=via,
        )
        if ref is not None and ledger.note(ref):
            noted += 1
    return noted


def classify(ref: ClaimRef, current: RecordRevision) -> str:
    """D7: the disposition of one noted claim against the store's current revision for its reader."""
    if ref.revision is None:
        return UNKNOWN_IDENTITY
    if current.state == REVISION_MISSING:
        return MISSING
    if current.state == REVISION_WITHHELD:
        return WITHHELD
    if current.state != REVISION_PRESENT or current.revision is None:
        return UNKNOWN
    if current.revision > ref.revision:
        return STALE
    if current.revision < ref.revision:
        return REGRESSED
    if current.updated != ref.updated:
        return CHANGED_SAME_REVISION
    return FRESH


class ClaimCurrencyMonitor:
    """Ship's Computer observer: at an effect point, the currency of the claims the caller's context holds (shadow)."""

    def __init__(self, records: RecordsStore) -> None:
        if not isinstance(records, RecordsStore):
            raise TypeError("AD-1302 S1: ClaimCurrencyMonitor needs the RecordsStore")
        self._records = records
        self._lock = threading.Lock()
        self._tally: dict[tuple[str, str], int] = {}
        self._failures = 0

    def check(self, *, effect: str, tool_id: str, agent_id: str) -> None:
        """Count each held claim's disposition and log the first non-fresh finding per ledger; refuse nothing.

        It reads ``CURRENT_CLAIM_LEDGER`` in the caller's context. No ``Exception`` leaves it: one is counted in
        ``failures`` and logged (WARNING the first time, DEBUG after); a ``BaseException`` that is not an
        ``Exception`` propagates.
        """
        try:
            ledger = CURRENT_CLAIM_LEDGER.get()
            if ledger is None:
                self._count(effect, NO_LEDGER)
                return None
            refs = ledger.entries()
            if not refs:
                self._count(effect, EMPTY_LEDGER)
                return None
            for ref in refs[:MAX_CHECKS_PER_SINK]:
                current = (
                    RecordRevision(REVISION_PRESENT) if ref.revision is None
                    else self._records.current_revision(
                        ref.path, reader_id=ref.reader_id, reader_department=ref.reader_department,
                    )
                )
                disposition = classify(ref, current)
                self._count(effect, disposition)
                if disposition != FRESH and ledger.first_report(ref, disposition):
                    logger.info(
                        "AD-1302 S1 claim currency (shadow; nothing refused): agent=%s tool=%s path=%s "
                        "shown_revision=%s current_revision=%s disposition=%s via=%s",
                        agent_id, tool_id, ref.path, ref.revision, current.revision, disposition, ref.via,
                    )
            if len(refs) > MAX_CHECKS_PER_SINK:
                self._count(effect, UNCHECKED, len(refs) - MAX_CHECKS_PER_SINK)
        except Exception:
            self._failures += 1
            try:
                logger.log(
                    logging.WARNING if self._failures == 1 else logging.DEBUG,
                    "AD-1302 S1: a claim currency check raised (%d so far); the sink was given None",
                    self._failures, exc_info=True,
                )
            except Exception:  # noqa: BLE001 -- a logging handler that raised must not reach the sink
                pass
        return None

    def _count(self, effect: str, disposition: str, n: int = 1) -> None:
        with self._lock:
            key = (effect, disposition)
            self._tally[key] = self._tally.get(key, 0) + n

    def tally(self) -> dict[tuple[str, str], int]:
        """Dispositions by (effect, disposition) since this monitor was built; a copy."""
        with self._lock:
            return dict(self._tally)

    @property
    def failures(self) -> int:
        return self._failures


def currency_at(monitor: object, *, effect: str, tool_id: str, agent_id: object) -> None:
    """The claim currency check of one effect point, in shadow: ``check`` for an exact monitor, else nothing."""
    if type(monitor) is ClaimCurrencyMonitor:
        monitor.check(effect=effect, tool_id=tool_id, agent_id=agent_id if type(agent_id) is str else "")
    return None
```

The Builder verifies that importing `probos.knowledge.records_store` from `probos.tools.registry` adds no cycle. Run `python -c "import probos.tools.registry"` in a fresh interpreter. If it does add one, move the `RecordsStore` import under `TYPE_CHECKING` and replace the constructor's `isinstance` with a check for the `current_revision` attribute, then report the change.

### 7.4 `src/probos/cognitive/oracle_service.py`

**Pair 1, import.** SEARCH:
```python
from probos.knowledge.archive_store import LABEL_THIS_CREW, inheritance_label  # AD-1341 S2
```
REPLACE:
```python
from probos.knowledge import claim_currency  # AD-1302 S1
from probos.knowledge.archive_store import LABEL_THIS_CREW, inheritance_label  # AD-1341 S2
```

**Pair 2, `query_formatted` notes what it emitted.** SEARCH:
```python
        lines = ["=== ORACLE QUERY RESULTS ==="]
        char_count = len(lines[0])

        for r in results:
```
REPLACE:
```python
        lines = ["=== ORACLE QUERY RESULTS ==="]
        char_count = len(lines[0])
        shown: list[OracleResult] = []  # AD-1302 S1: only what reaches the agent is noted

        for r in results:
```
SEARCH:
```python
            if char_count + len(line) + 1 > max_chars:
                break
            lines.append(line)
            char_count += len(line) + 1

        lines.append("=== END ORACLE RESULTS ===")
        return "\n".join(lines)
```
REPLACE:
```python
            if char_count + len(line) + 1 > max_chars:
                break
            lines.append(line)
            shown.append(r)
            char_count += len(line) + 1

        self.note_shown_records(
            [(r.source_tier, r.metadata) for r in shown],
            agent_id=agent_id, via=claim_currency.VIA_QUERY_FORMATTED,
        )
        lines.append("=== END ORACLE RESULTS ===")
        return "\n".join(lines)

    def note_shown_records(self, items: list[tuple[object, object]], *, agent_id: str, via: str) -> int:
        """AD-1302 S1: note the Ship's Records results in ``items`` into the open claim ledger, with the reader Tier 2
        retrieved them for (``_resolve_records_reader``, as ``query`` resolves it). Returns the count noted; 0 outside
        a ledger scope. Never raises: a failure is logged at DEBUG and notes nothing."""
        if claim_currency.CURRENT_CLAIM_LEDGER.get() is None:
            return 0
        try:
            reader_id, reader_department = self._resolve_records_reader(agent_id)
            return claim_currency.note_shown_records(
                items, reader_id=reader_id, reader_department=reader_department, via=via,
            )
        except Exception:
            logger.debug("AD-1302 S1: noting shown records failed; nothing noted", exc_info=True)
            return 0
```

### 7.5 `src/probos/tools/oracle_query_tool.py`

SEARCH:
```python
        envelopes = await self._commons_envelopes(query, tiers, actor)
        text, rendered = _render(envelopes)
```
REPLACE:
```python
        envelopes = await self._commons_envelopes(query, tiers, actor)
        text, rendered = _render(envelopes)
        self._note_shown(envelopes[:rendered], actor)  # AD-1302 S1: the rendered prefix only
```
Add this method right before `_bounded`, keeping its `@staticmethod` decorator on `_bounded`:
```python
    def _note_shown(self, envelopes: list[Any], actor: str) -> None:
        """AD-1302 S1: note the rendered Ship's Records entries into the caller's claim ledger. Log-and-degrade: an
        Oracle without ``note_shown_records`` (a test double) or one that raises notes nothing and changes no output."""
        try:
            from probos.knowledge.claim_currency import VIA_ORACLE_QUERY_TOOL

            items = [
                (getattr(getattr(e, "tag", None), "source_tier", ""), getattr(getattr(e, "tag", None), "metadata", None))
                for e in envelopes
            ]
            self._oracle.note_shown_records(items, agent_id=actor, via=VIA_ORACLE_QUERY_TOOL)
        except Exception:
            logger.debug("AD-1302 S1: the oracle_query tool noted nothing for agent %s", actor or "<unknown>", exc_info=True)
```
The `getattr` chain follows the same file's existing envelope access at `:338`. It is not a guard on an API this prompt defines.

### 7.6 `src/probos/tools/registry.py`

**Pair 1.** SEARCH:
```python
from probos.admission.seam import check_at, shadow_at
```
REPLACE:
```python
from probos.admission.seam import check_at, shadow_at
from probos.knowledge.claim_currency import currency_at  # AD-1302 S1
```
**Pair 2.** SEARCH:
```python
    _admission: "AdmissionService | None" = None  # AD-1346 M3c (set_admission): None shadows nothing
```
REPLACE:
```python
    _admission: "AdmissionService | None" = None  # AD-1346 M3c (set_admission): None shadows nothing
    _claim_currency: "ClaimCurrencyMonitor | None" = None  # AD-1302 S1 (set_claim_currency): None checks nothing
```
Add `ClaimCurrencyMonitor` to the module's existing `TYPE_CHECKING` imports. If the module has none, add `if TYPE_CHECKING: from probos.knowledge.claim_currency import ClaimCurrencyMonitor`.

**Pair 3.** SEARCH:
```python
    def set_admission(self, service: "AdmissionService | None") -> None:
        """AD-1346 M3c: late-bind the shadow admission decision check_and_invoke reports to; it blocks nothing."""
        self._admission = service
```
REPLACE:
```python
    def set_admission(self, service: "AdmissionService | None") -> None:
        """AD-1346 M3c: late-bind the shadow admission decision check_and_invoke reports to; it blocks nothing."""
        self._admission = service

    def set_claim_currency(self, monitor: "ClaimCurrencyMonitor | None") -> None:
        """AD-1302 S1: late-bind the claim currency monitor check_and_invoke reports to, in shadow; it blocks nothing."""
        self._claim_currency = monitor
```
**Pair 4.** SEARCH:
```python
        if self._tools.get(tool_id) is None:
            return ToolResult(error=f"Tool '{tool_id}' not found")

        # Permission check
```
REPLACE:
```python
        if self._tools.get(tool_id) is None:
            return ToolResult(error=f"Tool '{tool_id}' not found")
        currency_at(self._claim_currency, effect=SEAM_TOOL, tool_id=tool_id, agent_id=agent_id)  # AD-1302 S1: shadow; it blocks nothing

        # Permission check
```

### 7.7 `src/probos/cognitive/cognitive_agent.py` and `src/probos/runtime.py`

**cognitive_agent, pair 1.** SEARCH:
```python
from probos.admission.seam import hold_at, shadow_at  # AD-1346 M3c; hold_at: AD-1346 M3d2
```
REPLACE:
```python
from probos.admission.seam import hold_at, shadow_at  # AD-1346 M3c; hold_at: AD-1346 M3d2
from probos.knowledge.claim_currency import claim_ledger_scope  # AD-1302 S1
```
**cognitive_agent, pair 2.** SEARCH:
```python
        _intent_hold = hold_at(getattr(getattr(self, "_runtime", None), "admission_service", None), presented_id=self.id, work_kind="intent", seam=SEAM_INTENT, child=False)
        try:
            return await self._handle_admitted_intent(intent)
        finally:
            _intent_hold.end()
```
REPLACE:
```python
        _intent_hold = hold_at(getattr(getattr(self, "_runtime", None), "admission_service", None), presented_id=self.id, work_kind="intent", seam=SEAM_INTENT, child=False)
        try:
            with claim_ledger_scope():  # AD-1302 S1: the Records claims this intent's context is shown, for the tool sink
                return await self._handle_admitted_intent(intent)
        finally:
            _intent_hold.end()
```

**runtime, pair 1.** SEARCH:
```python
        self.admission_service: AdmissionService | None = None  # AD-1346 M3a: set after identity_service in start()
```
REPLACE:
```python
        self.admission_service: AdmissionService | None = None  # AD-1346 M3a: set after identity_service in start()
        self.claim_currency: ClaimCurrencyMonitor | None = None  # AD-1302 S1: set in start() when the switch is on
```
Add `ClaimCurrencyMonitor` to the same `TYPE_CHECKING` block from which `AdmissionService` is imported for that annotation (`runtime.py:158-165`). Also add the class-level declaration beside `admission_service`'s (`runtime.py:549`): `claim_currency: ClaimCurrencyMonitor | None  # AD-1302 S1: set in start() when records.claim_currency_shadow_enabled is true`.

**runtime, pair 2.** SEARCH:
```python
        self.tool_registry = comm.tool_registry
        if self.tool_registry is not None:  # AD-1343: every tool path ends in check_and_invoke
            self.tool_registry.set_stop_gate(self.agent_stops)
            self.tool_registry.set_admission(self.admission_service)  # AD-1346 M3c: its shadow statement; None shadows nothing
```
REPLACE:
```python
        self.tool_registry = comm.tool_registry
        # AD-1302 S1: the claim currency monitor, over the Records store, while records.claim_currency_shadow_enabled
        # is true. A constructor that raises leaves it None; the boot continues.
        self.claim_currency = None  # a second start() with the switch off must not keep the first start's monitor
        if self.config.records.claim_currency_shadow_enabled and self._records_store is not None:
            try:
                from probos.knowledge.claim_currency import ClaimCurrencyMonitor

                self.claim_currency = ClaimCurrencyMonitor(self._records_store)
            except Exception:
                logger.warning("AD-1302 S1: the claim currency monitor was not built; runtime.claim_currency stays None", exc_info=True)
        if self.tool_registry is not None:  # AD-1343: every tool path ends in check_and_invoke
            self.tool_registry.set_stop_gate(self.agent_stops)
            self.tool_registry.set_admission(self.admission_service)  # AD-1346 M3c: its shadow statement; None shadows nothing
            self.tool_registry.set_claim_currency(self.claim_currency)  # AD-1302 S1: in shadow; None checks nothing
```
Confirm that `self.config.records` is the `RecordsConfig` instance: grep `records: RecordsConfig` in `config.py`. If the attribute name differs, use the real one and report it.

## 8. Tracking (M2; re-anchor on the newest head entries at build time and change no wording)

**`PROGRESS.md`**, a new head entry after `# ProbOS Progress`:

> **AD-1302 S1 (YYYY-MM-DD), #1355 slice 1 -- the currency of borrowed Ship's Records claims in an agent's context, observed at the tool sink in shadow.** `handle_intent` opens a per-intent claim ledger (`probos.knowledge.claim_currency`). `OracleService.query_formatted` and the `oracle_query` tool note each Ship's Records result they actually show, by path and exact store revision (`record:{path}@{revision}`) with the reader it was retrieved for. At every tool call `ToolRegistry.check_and_invoke` compares the noted revisions with `RecordsStore.current_revision` on disk for that reader, then counts and logs `stale`, `regressed`, `changed_same_revision`, `missing`, `withheld` and `unknown`. Nothing is refused, no text changes, no event is emitted and no episode is touched. The switch is `records.claim_currency_shadow_enabled` (default on). Not covered, and reported unknown: corrections published at a new path (every `publish_finding` correction), corrections AD-550 deduplication suppresses, the consultation and standalone run entries, the crew commons consult, the DM lookup, memory refs, the introspect and organizer agents, direct Records reads outside the Oracle (the proactive notebook reads and the diagnostic context), a correction session's projected-registry tools, the archive tier, and effects other than tool calls (Ward Room posts among them). New: `tests/test_ad1302_s1_claim_currency.py`. The contract is `prompts/ad-1302-s1-context-claim-currency.md`.

**`DECISIONS.md`**: a new entry `### AD-1302 S1 -- the currency of borrowed Records claims in an agent's context, observed in shadow (YYYY-MM-DD, #1355)`, appended after the newest slice entry. Write one paragraph with the intro, one bullet each for D1 to D11 (a line each, taken from §3), an *Enrolled population* bullet taken from §9, the *Mutation campaign of record* bullet, and *Reversal: revert the S1 commits; nothing is persisted.* Do not edit the planning entry at `DECISIONS.md:10912`.

**`docs/development/roadmap.md`**: if it holds an AD-1302 row, add "S1 (in-context currency, shadow) built". Otherwise make no change.

## 9. What this does NOT change, and the enrolled population

**Enrolled:** the intent entry (`handle_intent`) × the `query_formatted` and `oracle_query` tool renderers × the Records tier × the tool sink. **Oracle consumer census (T14, frozen):** `agents/introspect.py` 1 (unknown), `agents/utility/organizer_agents.py` 1 (unknown), `cognitive/crew_executor.py` 1 (unknown: the AD-1141 commons consult), `cognitive/dm_targeted_lookup.py` 1 (unknown), `cognitive/cognitive_agent.py` 2 (enrolled through `query_formatted`; the graph-only call shows no Records), `experience/commands/commands_knowledge.py` 1 (the Captain's shell, not an agent context), `tools/oracle_query_tool.py` 1 (enrolled), `cognitive/provenance.py` 2 (the definition and its call: the tool's path), `routers/system.py` 1 (API, not an agent context), `cognitive/sub_tasks/query.py` 2 (`query_formatted` enrolled; `query_refs` unknown). The Builder re-runs the regex on the build tree and freezes the counts it finds (13 hits on `632f2c87`, re-run in this review). The census covers Oracle method calls only. It does not cover:

- **Direct Records reads into agent context outside the Oracle**, unknown: the proactive notebook reads (`proactive.py`) and the diagnostic context's `RecordsStore.read_entry` (`cognitive/diagnostic_context.py:414`). Other `read_entry`/`search` callers (`routers/records.py`, `routers/gaps.py`, `commands_gap.py`, `dreaming.py`, `archive_promotion.py`, `backlinks.py`, `semantic.py`) are not agent-context renderers or are not classified in S1.
- **A correction session's projected registry** (`cognitive/crew_verifier.py:464`, `_SessionProjectedToolRegistry`), unknown for its own (mesh) tools. It receives `set_admission` (`:1249`) but S1 does not give it `set_claim_currency`, so its `super().check_and_invoke` path (`:609`) checks nothing. Its source-backed tools delegate to the source registry (`:599`) and are checked there when that is the ship's registry.
- **Tool calls outside an intent's extent** (a crew work item's loop that runs in a task not created inside `handle_intent`) count `no_ledger`. That count is the visible measure of this gap; it is not a defect.

**Not changed:** the stored-derivation reassessment, which is the rest of AD-1302; supersession links between findings (S2); AD-550 deduplication; the content and rendering of any context; tool permissions and refusal; the AD-1346 admission service, tickets, census and store; `EventType`; episodic memory; the Ship's Archive; federation (AD-1303); AD-1300's goal revisions; `config/system.yaml`.

## 10. Diff Reviewer: properties to verify

1. Every agent-visible output (`query_formatted`, the `oracle_query` tool result, any tool result) is byte-identical with the monitor on, off and absent.
2. No `Exception` from the ledger, the monitor or the store reaches `check_and_invoke`, `query_formatted` or the tool.
3. A note is made only for a Records result that was rendered, and only for the reader that retrieved it. `withheld` discloses no revision of a record the reader may no longer read.
4. The ledger is reset on the return, raise and cancel paths of `handle_intent`. No intent's claims are visible to the next intent on the same task.
5. The I10 invariants of `handle_intent` hold (`tests/test_ad1346_admission_ticket_issue.py:551-578`).
6. The sink statement awaits nothing and, with an empty ledger, reads no file.
7. The runtime builds no monitor when the switch is off, and the boot survives a constructor that raises.

## 11. Verified Against Codebase (2026-11-02, HEAD `632f2c87`, tree `c4a3c09f`)

```
grep -n "def compute_claim_id" src/probos/knowledge/claims.py
  23: def compute_claim_id(title: str, claim: str, basis: str) -> str:
grep -n "claim_id\[:8\]\|write_notebook(" src/probos/tools/publish_finding_tool.py
  657: slug = f"{_slugify(fields['title'])}-{claim_id[:8]}"
  691: path = await self._records.write_notebook(
grep -n "existing_rev\|frontmatter\[\"revision\"\]" src/probos/knowledge/records_store.py
  324: existing_rev = existing_fm.get("revision", 1)
  325: frontmatter["revision"] = existing_rev + 1
grep -n "def _record_entity_iri\|record:{path}@{revision}\|_MAX_REVISION =" src/probos/knowledge/provo.py
  94: _MAX_REVISION = 2**31 - 1
  126: def _record_entity_iri(path: str, revision: int) -> str:
  136: identity = f"record:{path}@{revision}"
grep -n "async def publish\|fm\[\"status\"\] = \"published\"" src/probos/knowledge/records_store.py
  1085: async def publish(self, path: str, author: str) -> None:
  1097: fm["status"] = "published"
grep -n "\"suppress\"\|def _jaccard_similarity" src/probos/knowledge/records_store.py
  158: def _jaccard_similarity(text_a: str, text_b: str) -> float:
  680: "action": "suppress",
  752: "action": "suppress",
grep -n "def record_is_readable\|def read_entry\|async def list_entries\|def _parse_document\|def _safe_path" src/probos/knowledge/records_store.py
  84: def record_is_readable(
  970: async def read_entry(
  1001: async def list_entries(
  1248: def _parse_document(self, raw: str) -> tuple[dict, str]:
  1260: def _safe_path(self, user_path: str) -> Path:
grep -n "^from datetime\|^from probos" src/probos/knowledge/records_store.py
  8: from datetime import datetime, timezone
  14: from probos.execution.command_env import trusted_command_env
grep -n "semantic_index_enabled" src/probos/config_models/knowledge.py
  355: semantic_index_enabled: bool = False
grep -n "query_formatted(\|_oracle_context\"\] = oracle_text" src/probos/cognitive/cognitive_agent.py
  11716: oracle_text = await oracle.query_formatted(
  11723: observation["_oracle_context"] = oracle_text
grep -n "def query_formatted\|lines = \[\"=== ORACLE QUERY RESULTS\|END ORACLE RESULTS\|def _resolve_records_reader\|^from probos.knowledge.archive_store" src/probos/cognitive/oracle_service.py
  22: from probos.knowledge.archive_store import LABEL_THIS_CREW, inheritance_label  # AD-1341 S2
  463: def _resolve_records_reader(self, agent_id: str) -> tuple[str, str]:
  721: async def query_formatted(
  742: lines = ["=== ORACLE QUERY RESULTS ==="]
  779: lines.append("=== END ORACLE RESULTS ===")
grep -n "\"frontmatter\": r.get(\"frontmatter\"\|\"frontmatter\": _decode_record_frontmatter\|by_path.setdefault" src/probos/cognitive/oracle_service.py
  207: by_path.setdefault(path, result)
  1081: "frontmatter": r.get("frontmatter", {}),
  1129: "frontmatter": _decode_record_frontmatter(
grep -n "text, rendered = _render\|query_with_provenance(\|getattr(getattr(envelope" src/probos/tools/oracle_query_tool.py
  261: text, rendered = _render(envelopes)
  319: envelopes = await query_with_provenance(
  338: tier = getattr(getattr(envelope, "tag", None), "source_tier", "")
grep -n "metadata=result.metadata" src/probos/cognitive/provenance.py
  92: metadata=result.metadata,
grep -n "^from probos.admission.seam\|_admission: \"AdmissionService\|def set_admission\|check_at(self._admission\|Tool '{tool_id}' not found" src/probos/tools/registry.py
  16: from probos.admission.seam import check_at, shadow_at
  109: _admission: "AdmissionService | None" = None  # AD-1346 M3c (set_admission): None shadows nothing
  143: def set_admission(self, service: "AdmissionService | None") -> None:
  398: check_at(self._admission, effect=SEAM_TOOL, presented_id=agent_id)
  416: return ToolResult(error=f"Tool '{tool_id}' not found")
grep -n "_intent_hold = hold_at\|return await self._handle_admitted_intent\|_intent_hold.end()\|^from probos.admission.seam" src/probos/cognitive/cognitive_agent.py
  24: from probos.admission.seam import hold_at, shadow_at  # AD-1346 M3c; hold_at: AD-1346 M3d2
  7988: _intent_hold = hold_at(...)
  7990: return await self._handle_admitted_intent(intent)
  7992: _intent_hold.end()
grep -n "CURRENT_TICKET: Final" src/probos/admission/carrier.py
  24: CURRENT_TICKET: Final[ContextVar[WorkTicket | None]] = ContextVar("probos_admission_ticket", default=None)
grep -n "last.finalbody\|isinstance(last, ast.Try)" tests/test_ad1346_admission_ticket_issue.py
  574: assert isinstance(last, ast.Try) and last.lineno > hold.lineno, qualname
  575: assert [ast.unparse(stmt) for stmt in last.finalbody] == [f"{name}.end()"], qualname
grep -n "self.admission_service: AdmissionService | None = None\|self._records_store = cog.records_store\|self.tool_registry.set_admission" src/probos/runtime.py
  1243: self.admission_service: AdmissionService | None = None
  3063: self._records_store = cog.records_store
  3437: self.tool_registry.set_admission(self.admission_service)
grep -n "required: ToolPermission = ToolPermission.READ" src/probos/tools/context.py src/probos/tools/registry.py
  context.py:112, registry.py:368
grep -n "def effect_coverage_report" src/probos/execution/effect_broker.py
  110: def effect_coverage_report() -> EffectCoverageReport:   (the honest-population precedent)
```

## Absence Verified (2026-11-02)

| # | Claim | Run | Found | Holds |
|---|---|---|---|---|
| AV1 | No supersession or correction link exists between Records entries | Grep `-i "contest_state\|supersed\|retract"` over `src/probos/{knowledge,tools}` | `confidence_tracker.py:71-75` (confidence below a threshold), `records_store.py:1282` (`"until_superseded"`, a retention string), `publish_finding_tool.py:825` (`"contest_state": "uncontested"`, a constant nobody sets) | yes |
| AV2 | Nothing records which Records revisions entered an agent's context | Grep `revision` in `oracle_service.py`, `oracle_query_tool.py`, `provenance.py` | none | yes |
| AV3 | No AD-1300 to AD-1304 prompt is in flight | Glob `prompts/ad-130[0-4]*` | none | yes |
| AV4 | AD-1300 has no implementation to reuse | `DECISIONS.md:10888`; `gh issue view 1353` | "planned, not implemented"; OPEN | yes |
| AV5 | Invocation callers do not pass `required` | Grep `required=(ToolPermission\.\w+\|required\|_required\|perm\w*)` over `src/probos` | `agent_work_runner.py:338` (`WRITE`, claim), `crew_verifier.py:603,613` and `context.py:135` (pass-through), `registry.py:433,456` (internal) | yes |
| AV6 | No Records "borrowed" label exists outside the archive | Grep `-i "borrowed\|inherited"` over `src/probos` | the archive labels (`archive_store.py:402-439`), the Oracle's archive tier (`oracle_service.py:387,457,1189`), and unrelated matches | yes |
| AV7 | Internal research has no prior in-context supersession study | Grep `-i "supersession\|in-context\|stale claim\|retraction"` over `docs/research` | `dynamic-communication-register-research.md` only (unrelated) | yes |

## 12. Not verified (the Builder verifies by running)

- No import cycle from `tools/registry.py` → `knowledge/claim_currency.py` → `knowledge/records_store.py` (§7.3).
- The real stub-tool registration signature for T11 (`ToolRegistry.register`).
- The `TYPE_CHECKING` import blocks in `registry.py` and `runtime.py`, and `config.records`'s attribute name.
- That no `?raw` test pins a line §7.4 or §7.5 changes (§5, row 9).
- Hot-path cost: a ContextVar read and a dict increment with no ledger. The Builder reports a 20,000-call median of `currency_at` with no ledger and with 8 fresh refs, timed with `time.perf_counter_ns`, as a disclosed figure. No threshold is set.

## 13. Prior Art and Blind Spots

**Internal.** P4's `record:{path}@{revision}` identity is adopted as is. The honest-population pattern is adopted from `effect_coverage_report` (`effect_broker.py:110-134`), as a test census rather than a runtime function, to avoid a built-but-never-called report. AD-677's `ProvenanceTag.is_stale` (`provenance.py:37-40`) measures **age** (five minutes), not currency, and S1 does not reuse or rename it. AD-1300 is aligned in vocabulary only (AV4). The Ship's Archive label (AD-1341 S2) is a different population. `docs/research` holds nothing on the topic (AV7).

**External (2026-11-02; `docs/research/reference-projects.md` checked):** no relevant memory row is overdue. RAGFlow and LoCoMo were reviewed on 2026-05-08 at a 180-day interval, so they are due on 2026-11-04, not yet. AG-UI has never been reviewed and is not relevant here.
- arXiv [2608.25553](https://arxiv.org/pdf/2608.25553) (verified): agents checked provenance in about one episode in five, with 77.3%, 74.7% and 74.7% stale-consistent decisions after supersession, and the authors call for freshness or supersession signals separate from relevance. **Absorbed:** this is the rationale for an infrastructure check, and the currency check is kept separate from the relevance score.
- arXiv [2607.23929](https://arxiv.org/pdf/2607.23929) MemTX (abstract only): it gates irreversible tool calls on in-flight belief and runs typed cascading repair after a retraction. **Adapted:** the effect-point check, in shadow first. The brief's "zero downstream harm" was **not** confirmed: the abstract reports beating every baseline on four of five backbones and tying on the fifth. Cascading repair belongs to AD-1302's stored-derivation slices.
- arXiv [2605.06527](https://arxiv.org/html/2605.06527) STALE (verified): the best model scores about 55.2%, and premise resistance is the weakest dimension. **Absorbed** as rationale.
- arXiv [2606.24535](https://arxiv.org/pdf/2606.24535) Governed Shared Memory (abstract and summaries): supersession filtering at retrieval time. It also reports that **a synchronous near-duplicate gate rejected contradictory writes before the contradiction detector saw them**. That is ProbOS's AD-550 shape (P6), and it is recorded as blind spot B1.
- arXiv [2609.02127](https://arxiv.org/pdf/2609.02127) "Stored Is Not Supported" (search summary): supersession is a lifecycle transition that keeps the historical trace. **Absorbed:** D11.
- Atomix, arXiv [2602.14849](https://arxiv.org/pdf/2602.14849) (search summary): irreversible effects are held until they settle. **Considered, deferred** to AD-1301's ownership of effect reconciliation.
- Graphiti and Zep `invalid_at`, and nanopublication retraction: taken from the brief and **not re-fetched**. They are the store-side analogue of S2. The brief reports no source on push revocation of facts already in context, and S1 does not depend on push.

**Blind spots.**
- **B1.** AD-550 deduplication suppresses small corrections. A one-number fix to a finding or notebook entry inside 72 hours scores a Jaccard similarity of 0.8 or more. It is suppressed with "the existing entry stands", so it produces no revision and no new path, and S1 cannot see it. This is a precondition for every AD-1302 correction path, and S2 owns the fix: an authorized correction must bypass similarity suppression against its own target.
- **B2.** `publish_finding` corrections land at a new path (P2). S1 detects them only when the author rewrites the same path.
- **B3.** Index lag (P8). The ledger notes the revision actually shown, and the check reads the disk. A result the semantic index served at an older revision therefore checks `stale` even with no write after assembly. That is correct, because the context holds old text.
- **B4.** A revision can regress (`records_store.py:335-336`), and `publish` changes `updated` without a revision (P5). These are counted separately and never reported as `stale`.
- **B5.** Concurrent `write_entry` calls can both write N+1, because there is no lock around the read-modify-write. S1 inherits this. The duplicate and out-of-order acceptance line of AD-1302 owns it.
- **B6.** The most common effect is not a tool call. A Ward Room post or DM reply that repeats a stale claim is an effect S1 does not reach (§9). The enforcement slice must name it.
- **B7.** Reclassification. A record narrowed to `private` after it was shown is `withheld`, and no revision or content is disclosed (D6).
- **B8.** The check cannot judge relevance. A stale claim can sit in context without having influenced the call. In shadow this inflates the count, so S1's figures are an upper bound and are reported as such. A re-read does not clear the older note either: after reading revision 2, the ledger holds both `@1` and `@2`, and `@1` keeps checking `stale`. That is correct for S1 (the context still holds the revision 1 text), but S3's notice must not tell an agent to re-read what it already re-read.

**What comes after S1 (ranked; each is its own slice):**
1. **S2: authorized supersession.** A `supersedes: <path>` link written by the original author or the Captain, validated (the target exists, the author matches, no cycle), that bypasses AD-550 against its target (B1, B2). The monitor then names the successor path, readable by the reader, in its finding. Within the envelope.
2. **S3: agent-visible notice (advisory).** Append to the tool result at the sink: "A Ship's Records entry you read (`<path>`, revision N) has changed since (now revision M). Re-read it before relying on it; your memory of reading revision N stays as it was." A withheld entry gets "is no longer available to you" and nothing more. This changes what agents see, so it builds only after S1's shadow figures show a non-trivial stale rate. It is a design decision within the envelope, but the orchestrator reports it to the Captain before enabling it on the live crew.
3. **Enforcement** through AD-1346's admission decision, as one more effect-point check AD-1346 owns, refusing **consequential** calls on a `stale` claim until it is re-read. It needs a consequential-tool classification (P11) and AD-1346 out of shadow. **Captain:** the switch from shadow to refusal, together with AD-1346's own.
4. **Freshness lease.** `noted_at` is already recorded, so a later slice can bound reasoning that never reaches an effect point. Deferred until S1's figures exist.
5. **Push supersession notice** on the event bus to agents holding a claim. Lowest rank: best-effort, never the guarantee, and it needs a holder index S1 does not keep.

## 14. Acceptance criteria

- [ ] T1 to T14 pass in a clean checkout and in a worktree where `config/system.yaml` is modified (no hash of it is frozen).
- [ ] The crossing (T11) goes intent entry → real Oracle render → real Records correction → real tool sink → `stale` counted and logged, with the tool result unchanged.
- [ ] The focused gate in §4 is green. The mutation campaign of record kills all 14 rows and is recorded.
- [ ] The Diff Reviewer's properties in §10 are verified, and its findings are repaired before commit.
- [ ] The trackers in §8 are written, and the broad gate is run once with a receipt by the orchestrator.
- [ ] The orchestrator adds a comment to #1355 recording the in-context slice and its population (§9).
- [ ] The three frozen config consumers (§7.1) each changed by exactly one entry.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Review (2026-11-02, `claude-architect`, fresh read as the Builder)

**Verdict:** ready after these edits. Spot-checked on `632f2c87` (tree `c4a3c09f`): every SEARCH block in §7.2, §7.4, §7.5, §7.6 and §7.7 matches the live text (`records_store.py:8-9`, `:148-158`, `:999-1001`; `oracle_service.py:22`, `:742-745`, `:774-780`; `oracle_query_tool.py:260-261`; `registry.py:16`, `:109`, `:143-145`, `:415-418`; `cognitive_agent.py:24`, `:7988-7992`; `runtime.py:1243`, `:3434-3437`); `config_models/knowledge.py:353-355` is `RecordsConfig` (`:317`), reached as `config.records` (`config.py:3935`). I10 (`:551-578`) and SK7 (`test_ad1346_admission_ticket_sinks.py:507-526`) still hold, since SK7 pins only the statements beside `check_at`. AD-1343's sink-order test (`test_ad1343_stop_seam_inventory.py:110-123`) also holds. The 13-hit Oracle census reproduces.

**Changes made in this revision:**
1. **Required.** The new `RecordsConfig` field broke three frozen consumers the draft did not name. The draft said "no existing test changes". Added §7.1's update steps, §5 row 10, the focused-gate files and an acceptance line.
2. **Required.** T8 told the Builder to make `current_revision` raise `AssertionError` to prove it is not called. `check` swallows every `Exception`, so that test could not fail. It now uses a call recorder and asserts `failures == 0`.
3. **Required.** T13's text scan for `emit` would have failed on the module's own docstring ("no event is emitted"). It now scans by AST.
4. **Required.** With a real Oracle's `k_per_tier=3`, T7 could not make `rendered < len(envelopes)` for Records results, so CC-6 would survive. T7 now uses ten Records results against `_MAX_RESULTS = 8` and asserts the premise. T3 now requires non-records items to carry a valid path, so CC-4 is killable.
5. **Required.** T11 compared whole `ToolResult`s, which include `duration_ms`, and read cumulative tallies across three runs on one runtime. It now compares `output`, `error` and `metadata`, and reads tally deltas.
6. **Required (honest population).** §9 and the PROGRESS text now name two unenrolled populations: direct Records reads outside the Oracle (`diagnostic_context.py:414`, proactive notebook reads) and the correction session's projected registry (`crew_verifier.py:464`, `:1249`, `:609`).
7. **Required.** AD-1346 I11 freezes which `src` files contain the text `CURRENT_TICKET`. D2 now forbids naming it in any new file.
8. **Recommended, applied.** D8 now says the check also comes after the stop refusal. D6 now names the shared `"ship"` scope. The runtime now resets `claim_currency` to None before building it and declares it at class level. B8 now records that a re-read does not clear the older note.

**Checked, no change needed:** shadow mode changes no agent-visible byte (the note happens after the render loop, inside a log-and-degrade wrapper, and the sink returns None). Nothing is refused, persisted or emitted. No conflict with AD-1346 (a separate carrier, outside its censuses), AD-1300 (vocabulary only), AD-1341 (archive tier excluded) or the BF-947 pause (S1 enables no agent work; `agent_work_runner.py:338`'s `check_and_invoke` would only be observed).

**Not verified in this review:** the Captain's "Option A" choice in D12. #1355 has no comments. Even without it, S1 sits inside the delegated envelope, because it is shadow-only and weakens no control.
