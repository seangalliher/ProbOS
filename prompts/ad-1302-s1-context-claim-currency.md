# AD-1302 S1: the currency of borrowed Ship's Records claims in an agent's working context, observed at the tool sink in shadow

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-02
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-02 (fresh-read review: the config field's three frozen consumers, four test specs that could not kill their mutants, two unenrolled populations, the I11 carrier census; see §15)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-28 (full re-verification against `main` `1d9ba205`: every anchor, SEARCH block, test pin, census and absence re-run; four SEARCH blocks re-cut for BF-969, BF-932 and AD-1357; three more frozen consumers named (the facade field count, the AD-1152 default-config pop, the ToolRegistry SRP row); BF-932's `entry_fingerprint` and AD-1357's `sources_out` decided as not reused; see §15)

**Status:** build-ready draft. This is slice 1 of AD-1302 (#1355). It does not close the issue. **Tier HIGH**, because it adds a statement to `ToolRegistry.check_and_invoke`, the one tool sink, and to `CognitiveAgent.handle_intent`, the intent entry. No new AD or BF number. **Base:** `main` `1d9ba205`, tree `6ee55ee196f6858356352218fb549b8d16a6781c` (the prompt branch head `b8968837`, tree `89e966a1`, differs from it only by this file). **Captain:** this slice needs no Captain decision (D12). The later switch from observing to telling the agent, and then to refusing, does (§13, "What comes after S1").

**Milestones:** M1 is the code and tests in §7. M2 is the trackers in §8. Each milestone is one Builder delegation and one local commit. The broad gate is the orchestrator's single canonical run, once, after M2: `scripts/run_test_gate.py --label ad1302-s1 --receipt logs/gates/ad1302-s1.receipt.json`. The Builder runs only the focused gates in §4.

**Tests:** one new file, `tests/test_ad1302_s1_claim_currency.py`, with 14 functions (T1 to T14). Three existing frozen tests change by one entry each: `EXPECTED_DUMPS["RecordsConfig"]` in `tests/test_ad1270e2f_knowledge_models.py`, the `field_definitions` count in `tests/test_ad1270e1_config_facade.py`, and one `pop` line in `tests/test_ad1152_agentic_correlation.py`. Two generated artifacts are regenerated, `docs/development/config-facade-baseline.yaml` and `docs/development/config-reference.md`, and one reviewed row of `docs/development/architecture-baseline.yaml` changes its triggers (§7.1, §7.6, §5 rows 10 and 11). No other existing test changes (§5, row 9).

**Line endings:** the working copies are CRLF and the index LF (`git ls-files --eol`: `i/lf w/crlf`). The SEARCH blocks are LF, so match and write using each file's own line endings. Write new files with LF.

**Worktree:** if `config/system.yaml` carries the Captain's uncommitted local edits in the build worktree, do not stage it, and do not add the new config field to it. Stage files only by explicit path. Never use `git add -A`.

---

## 0. Premise: what is present on this tree

| # | Fact | Evidence |
|---|---|---|
| P1 | `compute_claim_id` hashes `(title, claim, basis)`, so it identifies content. A corrected finding has a different id. | `src/probos/knowledge/claims.py:23-31` |
| P2 | `publish_finding` writes each finding to `notebooks/<callsign>/<slug>-<claim_id[:8]>.md`. A corrected finding therefore lands at a **new path**, and nothing links it to the old one. | `src/probos/tools/publish_finding_tool.py:656-659`, `:692-701` |
| P3 | A rewrite of the **same path** through `write_entry` increments `revision`. The first write has no key, which means revision 1. | `src/probos/knowledge/records_store.py:811-825`; `src/probos/knowledge/provo.py:253-270` |
| P4 | ProbOS already names a record's stable identity as `record:{path}@{revision}`. | `src/probos/knowledge/provo.py:126-137` |
| P5 | `RecordsStore.publish` rewrites `status` and `updated` but does not change `revision`. | `records_store.py:1667-1691` |
| P6 | AD-550 deduplication suppresses a write whose word-level Jaccard similarity to a recent entry (72 h by default) is 0.8 or higher. It applies on the same topic (Layer 2) and across the author's other notebooks (Layer 3). `publish_finding` calls it explicitly. | `records_store.py:1120-1271` (Layer 2 `:1158`, Layer 3 `:1223`), `:228-236`; `publish_finding_tool.py:662-682` |
| P7 | Borrowed Records text reaches an agent's context through `OracleService.query_formatted`, which the passive recall and the AD-696 lookup call, and through the `oracle_query` tool, which uses `query_with_provenance` and `_render`. Each Records result's metadata carries `path` and `frontmatter`. | `cognitive_agent.py:12034-12044`; `sub_tasks/query.py:274-280`; `oracle_query_tool.py:138-162`, `:267-268`, `:326-332`; `oracle_service.py:1105-1114`, `:1153-1164` |
| P8 | When both retrieval paths return the same record, the semantic path's payload wins. Its frontmatter comes from the index sidecar, which can lag the file on disk when a reindex failed. | `oracle_service.py:228-230`; `records_store.py:871-892` |
| P9 | The only existing "inherited" label covers the Ship's Archive (AD-1341 S2), not live Records. Records results are tagged `[ship's records]` and carry a byline. | `archive_store.py:400-427`; `oracle_service.py:777-786`, `:1113`, `:1163` |
| P10 | AD-1346 holds a work ticket in `CURRENT_TICKET` at three entries and checks it in shadow at the tool sink (`check_at`, `registry.py:398`). Test I10 pins each entry's last statement as a `Try` whose `finally` is exactly `<hold>.end()`. | `admission/carrier.py:24`; `cognitive_agent.py:8227-8231`; `tests/test_ad1346_admission_ticket_issue.py:551-578` |
| P11 | At invocation, `required` defaults to `READ` and almost no caller passes it, so the tool sink cannot tell a consequential call from a read today. | `tools/context.py:112`; `registry.py:368`; Absence AV5 |
| P12 | AD-1300 (#1353) is planned and not implemented. It has no code pattern to reuse, only a stated principle. | `DECISIONS.md:12133-12135`; `gh issue view 1353`: OPEN |
| P13 | AD-1357 (#1749): `query_formatted(sources_out=...)` appends the `(source_tier, path)` of each rendered result, in rendered order, and the passive lookup hands that list to `context_manifest.note_oracle`, which keeps the **paths** (no revision, no `updated`) of the Records results in the crew chat reply's manifest. It is per observation, stored beside the reply, and not readable at the tool sink. | `oracle_service.py:753`, `:759-761`, `:806-807`; `cognitive_agent.py:12034-12042`; `cognitive/context_manifest.py:1-26`, `:266-294` |
| P14 | BF-932 (#1670): `RecordsStore.entry_fingerprint(path)` is `async def` with no internal await, returns the sha256 of the file's bytes or None, applies **no** classification gate, and raises what `_safe_path` and the read raise. `list_entries` now yields to the loop every 16 files in its default mode. | `records_store.py:1533-1546`, `:22` (`LoopYield`) |
| P15 | BF-970 (#1801): `_parse_document` reads a frontmatter that does not load (or nests 64 deep) as `{}`; `read_entry` uses `_load_document` and makes such a document private to its notebook owner. BF-966/BF-969: `record_is_readable` reads a non-label classification as `private` and an empty or non-`str` author as nobody. | `records_store.py:1874-1885`, `:1505-1531`; `:204-225` |

## 1. Problem

AD-1302 plans reassessment for **stored** derivations. Nothing covers a claim already assembled into an active agent's context. Suppose an agent reads a crewmate's Records entry at revision 1 and the author then corrects it to revision 2. Mid-task, the agent still holds revision 1 and can act on it. Nothing records which revisions entered the context (Absence AV2; AD-1357 records paths only, P13), so nothing can notice. Asking the model to re-check does not work. In arXiv 2608.25553, agents checked provenance in about one episode in five and made stale-consistent decisions in 74.7% to 77.3% of superseded episodes. This matches the LLM Independence principle: the check has to be infrastructure.

## 2. Solution overview

1. **Ledger.** `handle_intent` opens a per-intent `ContextClaimLedger` in a context variable for the duration of the intent's work.
2. **Note at render.** Wherever a Records result becomes text the agent reads, the ledger records `(path, revision, updated, author, reader, via, noted_at)`. That covers `query_formatted`'s emitted lines and the `oracle_query` tool's rendered entries. Only results actually shown are noted.
3. **Check at the tool sink, in shadow.** `ToolRegistry.check_and_invoke` asks a `ClaimCurrencyMonitor` to compare every noted revision with the store's current revision **on disk, for the same reader**. The monitor counts each disposition and logs the first non-fresh finding for each ledger and claim. **Nothing is refused, no text changes, no event is emitted, and no episode is touched.**
4. **Population census.** A test freezes the list of Oracle consumers in `src` and which of them are enrolled. Every other consumer is declared unknown.

S1 measures how often an agent reaches an effect point holding a claim that has since changed. That figure decides whether the later slices are worth building.

## 3. Decisions

- **D1 (identity).** The stable identity is the Records path plus the store's revision, the same identity as P4. `claim_id` is rejected as the identity because it changes with every correction (P1). A byte digest (`entry_fingerprint`, P14) is rejected as the identity too (D6). A correction that lands at a **new path** (P2) is not linked by S1, and is reported unknown in §9. S2 owns the authorized supersession link.
- **D2 (the ledger's carrier).** The ledger has its own `ContextVar`, `CURRENT_CLAIM_LEDGER`, and holds one **mutable** ledger object. Tasks created inside the scope copy the context, so they share the object: notes made in a child task are visible at the parent's sink. The ledger is not keyed on the AD-1346 ticket, for three reasons. The ticket is None when its issue is refused or `admission.shadow_enabled` (`config.py:3583`) is false. AD-1346 M4 may replace the carrier (`carrier.py:11`). And the ledger is not an admission decision. Rejected: setting the variable lazily at the first note. A set made inside an awaited coroutine persists in the agent's long-lived task, so it would leak one intent's claims into the next. **No new or changed `src` file may contain the text `CURRENT_TICKET`, not even in a comment or docstring:** AD-1346 I11 (`tests/test_ad1346_admission_ticket_issue.py:581-598`) freezes the set of files that name it to `admission/carrier.py` and `admission/service.py`. **Nor may a new file contain the text `admission_service` or import `probos.admission`:** `tests/test_ad1346_admission_service.py:628-656` freezes both sets of files.
- **D3 (the scope's place).** The scope is `with claim_ledger_scope():` inside `handle_intent`'s existing `try` body, wrapping the one `return await self._handle_admitted_intent(intent)`. This keeps I10's invariants: the last statement stays the `Try`, its `finalbody` stays `_intent_hold.end()`, it has no handlers, and `_intent_hold` is read once. Only the intent entry is enrolled. Consultation and standalone agent runs are unknown (§9). A run awaited inline from an intent inherits the intent's ledger.
- **D4 (noting).** `OracleService.note_shown_records(items, *, agent_id, via)` resolves the reader with the same `_resolve_records_reader` that `query` used, then calls `probos.knowledge.claim_currency.note_shown_records`. Only `source_tier == "records"` is noted. Archive, operational, semantic, graph and health are not. `query_formatted` passes only the results it appended before its `max_chars` break. The tool passes `envelopes[:rendered]`. Outside a scope, noting returns 0 and does nothing. The output text of both renderers is byte-identical with and without a scope (T6, T7). **AD-1357's `sources_out` (P13) is not reused:** it carries `(tier, path)` only, so neither the revision nor `updated` can be recovered from it, and it is optional and caller-owned (the tool path never passes it). The new `shown` list sits beside it in the same loop iteration, so both are the rendered prefix; T6 asserts that their Records paths agree.
- **D5 (what counts as known).** The shown revision is known only when `frontmatter` is a non-empty `dict` with a non-empty `updated`. The revision is then `frontmatter.get("revision", 1)` under P3's rule, where `bool` is excluded and the range is 1 to 2^31-1. Anything else is noted with `revision=None` and checks as `unknown_identity`. This is necessary because an empty semantic sidecar would otherwise be read as revision 1.
- **D6 (the current revision).** The current revision comes from the new synchronous `RecordsStore.current_revision(path, *, reader_id, reader_department, scope="ship")`, which reads the file on disk and **never** the semantic index (P8). It re-applies `record_is_readable` (with BF-966/BF-969's rules, P15) for the reader recorded at noting time. A record the reader may no longer read returns `withheld` with no revision, so a reclassified record discloses nothing. A frontmatter that does not load reads as `{}` (P15) and returns `unreadable`, so it discloses nothing either. It is synchronous because it does only the local file read that `read_entry` already does, so the sink statement awaits nothing. Its default `scope="ship"` is the scope Tier 2 retrieves at (`_RECORDS_QUERY_SCOPE = "ship"`, `oracle_service.py:69`), so a record the Oracle could show is never `withheld` by scope alone. **`entry_fingerprint` (P14) is not reused**, for four reasons: (1) it is `async def`, so calling it from the sink means an await, against D8's awaits-nothing contract; (2) it has no classification gate, so it cannot produce `withheld` (B7); (3) it raises on traversal, and the sink path must never raise; (4) it identifies bytes, not the shown claim: at noting time the ledger holds the rendered result's frontmatter, not the bytes the agent read, so a digest taken then would hash the disk at that moment and turn B3's correct `stale` (index lag) into `fresh`. A same-revision byte change is already counted through `updated` as `changed_same_revision`.
- **D7 (dispositions).** `fresh`: same revision and same `updated`. `stale`: the current revision is higher. `regressed`: the current revision is lower, as after `write_entry`'s exception path at `records_store.py:835-836`. `changed_same_revision`: same revision but a different `updated`, as after `publish` (P5). `missing`: no file, or a path under `_archived/`. `withheld`: no longer readable by the reader. `unknown`: unreadable, malformed or traversal. `unknown_identity`: D5. At the sink level there are also `no_ledger`, `empty_ledger` and `unchecked`, which counts the claims beyond the per-sink cap of 16. Only `stale` is the correction signal. `regressed` and `changed_same_revision` are counted separately and never reported as stale.
- **D8 (the sink).** `currency_at(monitor, *, effect, tool_id, agent_id)` is one statement in `check_and_invoke`. It sits **after** the stop refusal and the tool-existence check, so neither a refused call nor a call to a tool that does not exist is an effect point, and before the permission check. It applies to every call that reaches it through the ship's registry (a correction session's projected registry is not wired: §9). S1 does not classify which calls are consequential, because `required` cannot tell them apart (P11). Classifying them is the enforcement slice's job. The statement follows `check_at`'s contract: it calls only an exact `ClaimCurrencyMonitor`, returns None, awaits nothing and lets no `Exception` out.
- **D9 (observability).** The monitor keeps an in-memory tally of `(effect, disposition)` under a `threading.Lock`, plus a `failures` count. It logs one INFO line, marked `AD-1302 S1 claim currency`, the first time each ledger finds a given `(path, shown revision, disposition)` that is not fresh. That line is greppable in `probos.log`, which supports the producer-versus-consumer marker count. S1 persists nothing and emits no `EventType`. A Records path in an operator log is the same exposure as the existing `Record written:` INFO line (`records_store.py:894`).
- **D10 (switch).** `RecordsConfig.claim_currency_shadow_enabled: bool = True`. When it is false, the runtime builds no monitor, so the sink checks nothing, and the ledger still records in memory at negligible cost. The default is on for the same reason AD-1346's shadow is on: it changes nothing an agent sees.
- **D11 (memory).** S1 has no write path to episodic memory, notebooks or Records. The agent's memory of having read revision N is never rewritten, under Memory: optimize, never delete. T13 checks this by source scan.
- **D12 (Captain).** S1 needs no Captain decision. It weakens no control, changes no schema or public API, and changes nothing an agent sees or does. It extends the product objective only within the slice the Captain chose: the Captain's decision of 2026-11-02 is recorded on #1355 ("extend AD-1302 with a slice for claims already assembled into an active agent's context ... Chosen as a slice of AD-1302, not a new AD").

## 4. Milestones and focused gates

- **M1:** §7.1 to §7.7 and the new test file. Focused gate: `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1302_s1_claim_currency.py tests/test_ad1346_admission_ticket_issue.py tests/test_ad1346_admission_ticket_sinks.py tests/test_ad1346_admission_shadow_seams.py tests/test_ad1346_admission_service.py tests/test_ad1139_oracle_query_tool.py tests/test_bf679_oracle_records_reader_identity.py tests/test_ad1294_read_provenance_rendering.py tests/test_ad696_agentic_oracle_retrieval.py tests/test_ad1341_s2_inherited_label.py tests/test_ad1357_context_manifest.py tests/test_ad1270e2f_knowledge_models.py tests/test_ad1270e1_config_facade.py tests/test_config_reference_current.py tests/test_ad1152_agentic_correlation.py tests/test_ad1270b_architecture_fitness.py tests/test_ad1343_stop_seam_inventory.py tests/test_layer_boundaries.py -q -n 0`, then `d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_profiles.py --check` (a default-True boolean is outside `default_false_flags`, `scripts/check_config_profiles.py:148-170`, so the profile manifest should not change; confirm it) and `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check` (§7.6, Pair 5).
- **M2:** §8 only. No test run is needed: a docs-only commit.

## 5. Consumers of every value this changes

| # | Changed | Consumer | Accepts because |
|---|---|---|---|
| 1 | `handle_intent` try body | I10 (`test_ad1346_admission_ticket_issue.py:551-578`) | It pins only the last `Try`, its `finalbody` and handlers, no await between the last `shadow_at` and the hold, and the one read of the hold. The `with` sits inside `body`. |
| 2 | `handle_intent` try body | tests that monkeypatch `_handle_admitted_intent` (`:480`, `:502`, `:515`) | The `with` still awaits that attribute, and the cancel and raise paths run its `finally`. |
| 3 | `check_and_invoke` gains one statement | AD-1346 census of `shadow_at`, `hold_at` and `check_at`; SK7 (`test_ad1346_admission_ticket_sinks.py:510-529`) | The new callee is `currency_at`, which no census names. SK7 pins only the statements on either side of `check_at` (`shadow_at` before, `if stopped is not None` after); the new statement sits after the not-found return. No `tests/test_ad134[36]_*` file counts the statements of `check_and_invoke` (searched: only call sites and SK7). |
| 4 | `query_formatted` | its output | No byte changes (T6). |
| 5 | `OracleQueryTool.invoke` | its output and metadata | No byte changes (T7). Test doubles without `note_shown_records` fall to the log-and-degrade branch. |
| 6 | `RecordsConfig` | `ProbOSConfig` load and the zero-config boot | It has a default. Do not add it to `config/system.yaml`. |
| 10 | `RecordsConfig` gains a field | five frozen consumers: (a) `EXPECTED_DUMPS["RecordsConfig"]` (`tests/test_ad1270e2f_knowledge_models.py:212-243`, read by `:427-432` and `:449-452`); (b) `docs/development/config-facade-baseline.yaml` (`scripts/check_config_facade.py --check`, run by `tests/test_ad1270e1_config_facade.py:1809-1812`); (c) `counts["field_definitions"] == 1878` (`tests/test_ad1270e1_config_facade.py:1579`, in `:1515`); (d) `docs/development/config-reference.md:677` (`scripts/gen_config_reference.py --check`, run by `tests/test_config_reference_current.py:41-59`); (e) the default-config golden of `tests/test_ad1152_agentic_correlation.py` (`_off_observation` pops each added field, `:343-353`, under `_DEFAULT_CONFIG_RULE`, `:54-57`) | Updated in §7.1, each by exactly the entries named there. Any other drift is a stop-and-report. Not consumers: `EXPECTED_BOUND_COUNTS["RecordsConfig"]` (`:477`; a `bool` carries no bound), `tests/test_ad1270e2_config_models.py` (it has no `records` section), and `docs/development/config-profiles.yaml` (default-False flags only; its `census` counts at `:21-23` are a dated measurement that no script or test reads, so they are not edited). |
| 7 | `RecordsStore` new method and dataclass | nothing else in `src` | Additive. The `srp-size` row of `RecordsStore` already carries both triggers (`architecture-baseline.yaml:734-742`). |
| 8 | `runtime.claim_currency` | the tool registry | It is assigned before `set_claim_currency`. |
| 9 | Existing `?raw` source scans | `tests/test_ad1294_*`, `tests/test_ad696_*`, `tests/test_ad1341_s2_*`, `tests/test_ad1357_*`, `tests/test_ad590_composite_score_floor.py:291-299` | Searched on `1d9ba205`: the only source reads in the first four are `test_ad1341_s2_inherited_label.py:395` (it looks for `attach_current_timeline`), and `test_ad590` scans `oracle_service.py` only for `composite_score_floor`. None pins a line §7.4 or §7.5 changes. Re-check before editing; if one does, stop and report it. Do not change the test. |
| 11 | `ToolRegistry` grows by 6 lines | the `srp-size` row of `probos.tools.registry::ToolRegistry` (`docs/development/architecture-baseline.yaml:977-984`, triggers `[methods]`), checked by `scripts/check_architecture_principles.py --check` (`:937-945`, TRIGGER DRIFT), which the gate preflight runs (`scripts/run_test_gate.py:1120`) | The class spans `registry.py:85-582`, 498 lines; `SRP_MAX_BODY_LINES = 500` and a span `> 500` adds the `lines` trigger (`check_architecture_principles.py:187`, `:559-567`). §7.6 adds 6 lines (the attribute, the setter with its blank line, the sink statement), so the span becomes 504. §7.6 Pair 5 updates the row's triggers to `[lines, methods]` in the same commit. |
| 12 | `query_formatted`'s loop | AD-1357's `sources_out` and its test (`tests/test_ad1357_context_manifest.py:931-932`) | The `sources_out` lines are kept unchanged and in place; `shown.append(r)` is added beside them, so the order and content of `sources_out` do not change. |
| 13 | new imports of `probos.knowledge` from `cognitive` and from `tools` | AD-400 layer boundaries (`tests/test_layer_boundaries.py:45-57`) | `cognitive` may import `knowledge` (`:51`); `tools` is not a mapped layer; `claim_currency` imports only `probos.knowledge.records_store`, whose `probos.cognitive.provenance` import is an existing allowed exception (`:89-92`). |

## 6. Tests (`tests/test_ad1302_s1_claim_currency.py`)

Use a real `RecordsStore` on `tmp_path`, built as `RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))` and then `await store.initialize()` (the pattern of `tests/test_bf949_notebook_reader_identity.py:48-51`), and a real `OracleService` on its keyword path. For T11 and T12, boot a real runtime as `tests/test_ad1346_admission_ticket_issue.py` does (`_boot`, `:192`). Do not use mocks for the store, the Oracle or the registry.

- **T1** `claim_ledger_scope`: it sets a fresh ledger and restores the outer one when nested. After exit it closes the ledger and the variable is None. Outside a scope, `note_shown_records` returns 0.
- **T2** A task created inside the scope notes into the same ledger, and the parent sees the note. A task that outlives the scope cannot note after close: `note` returns False.
- **T3** Identity rules (D5): revision absent -> 1; `True`, `0`, `-1`, `"2"` and `2**31` -> None; `{}` and a frontmatter without `updated` -> None; a non-records tier, an empty or non-`str` path, and an archive-tier item are not noted. The non-records and archive items must carry a valid `str` `path` and a frontmatter with `updated`, so only the tier filter keeps them out (otherwise CC-4 survives). Duplicates under the same `(path, revision, reader)` are noted once. The cap of 64 counts the overflow in `dropped`.
- **T4** `current_revision`: present at revision 1, then 2 after `write_entry`; missing; `_archived/x.md` -> missing; `../x` -> unknown, never raising; a frontmatter YAML refuses (read as `{}`, P15) -> unknown. An entry reclassified to `private` returns `withheld` with revision None for another reader and present for its author. `captain` is unrestricted.
- **T5** `classify` table, one case per disposition, with `changed_same_revision` produced by a real `RecordsStore.publish`.
- **T6** `query_formatted` inside a scope, with two Records hits and a `max_chars` that admits exactly one: one note, for the emitted path, with `via="oracle.query_formatted"`. The output is byte-identical inside and outside a scope. Pass a `sources_out` list in the scoped call and assert that its Records-tier paths equal the ledger's paths (P13, D4).
- **T7** The `oracle_query` tool notes exactly `envelopes[:rendered]`. Use a real `OracleService` subclass that overrides only `query` to return ten Records-tier `OracleResult`s with distinct paths and full frontmatter, so `_render` stops at `_MAX_RESULTS = 8` (`oracle_query_tool.py:71`; a real Oracle returns at most `_K_PER_TIER = 3` per tier, `:79`). Assert the premise `metadata["returned_count"] < metadata["candidate_count"]`, then that the ledger holds exactly the first `returned_count` paths (otherwise CC-6 survives). A fake oracle lacking `note_shown_records` returns the same `output` and `metadata` inside a scope as outside one, and logs at DEBUG.
- **T8** Monitor: with no ledger, it counts `no_ledger` and calls `current_revision` zero times. Monkeypatch `current_revision` with a call recorder and assert zero calls and `failures == 0`. Do not make the patch raise: `check` swallows any `Exception`, so a raising patch would pass. With an empty ledger, it counts `empty_ledger`. With 20 distinct refs, it checks 16 and counts `unchecked` as 4.
- **T9** If the store raises, `check` raises nothing: `failures == 1`, WARNING the first time and DEBUG after. `currency_at` with None, or with a duck-typed double that has `check`, does nothing.
- **T10** Three sink calls on one stale claim: the tally counts `stale` 3 times, and there is exactly one INFO line carrying `path=`, `shown_revision=1` and `current_revision=2`.
- **T11** **The crossing, the golden test.** Boot a real runtime with a real crew agent and seed a `ship`-classified record by another author. Monkeypatch `crew._handle_admitted_intent` to: (a) call the runtime's real `OracleService.query_formatted` for that crew agent; (b) `write_entry` a correction to the same path, so it is at revision 2; (c) call `rt.tool_registry.check_and_invoke(crew.id, <a stub READ tool registered on the real registry with ToolRegistry.register, registry.py:158>, {})`. Then call `crew.handle_intent(...)` and assert four things: the **delta** of `rt.claim_currency.tally()` across this run has `(SEAM_TOOL, "stale") == 1` (take a snapshot before each run; the control and reclassification runs share the runtime); the INFO line is present and names `agent=<crew.id>`; the tool result's `output`, `error` and `metadata` equal those of a control run without step (b), so nothing was refused (do not compare `duration_ms`); and `CURRENT_CLAIM_LEDGER.get() is None` after return. Repeat with step (b) reclassifying the record to `private`, and expect `withheld`.
- **T12** With the switch off (`records.claim_currency_shadow_enabled=False`), `rt.claim_currency is None` and T11's flow gives the same tool result while counting nothing.
- **T13** Source scans, by AST, never by raw text (the module docstring says "no event is emitted", which a substring scan for `emit` would flag). `claim_currency.py` imports nothing from `probos.cognitive`, and no `ast.Name`, `ast.Attribute` or imported name in it is or contains `episodic`, `write_entry` or `emit`. The sink statement in `check_and_invoke` comes after the `self._tools.get(tool_id) is None` check. `handle_intent`'s last `Try` body holds the `with claim_ledger_scope()`.
- **T14** **Oracle consumer census.** Regex `oracle\w*\.(query|query_formatted|query_refs)\(|query_with_provenance\(` over `src/probos/**/*.py`, frozen per file (§9). A new consumer fails the test with a message naming it, and the developer must classify it as enrolled or unknown.

**Mutation table** (whole-line edits, each restored before the next; the named killer must fail):

| Row | File | Mutation | Killer |
|---|---|---|---|
| CC-1 | `claim_currency.py` | `>` -> `>=` in `classify`'s stale test | T5 |
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
(The field lands between `semantic_index_enabled`, `:355`, and BF-957's `git_lock_stale_minutes`, `:356-357`, so every field-ordered consumer gets it in that place.)

Then update the field's five frozen consumers (§5 row 10), each by exactly the entries named:

1. `tests/test_ad1270e2f_knowledge_models.py`, `EXPECTED_DUMPS["RecordsConfig"]` (`:212-243`): after `'semantic_index_enabled': False,` (`:239`) and before the comment `# BF-957 appended three fields after the move; the move changed none.` (`:240`) add `'claim_currency_shadow_enabled': True,`. The dump follows declaration order. Keep the file's existing formatting.
2. `d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --update-baseline`. The diff to `docs/development/config-facade-baseline.yaml` must be exactly: the line `- {default: 'True', name: claim_currency_shadow_enabled}` after `:3042`; `canonical_dump_leaves` 1885 -> 1886 (`:50`); `field_definitions` 1878 -> 1879 (`:51`); `canonical_dump_sha256` (`:56`); `schema_sha256` of `RecordsConfig` (`:3013`) and of `SystemConfig` (`:3415`). That is the shape BF-932's one-field commit `3fb44fe8` produced (there the second digest was `SystemInfo`'s, the field's own model).
3. `tests/test_ad1270e1_config_facade.py:1578-1579`: after `# BF-932 (#1670) adds system.loop_stall_warn_seconds (1877 -> 1878).` add `# AD-1302 S1 (#1355) adds records.claim_currency_shadow_enabled (1878 -> 1879).` and change `== 1878` to `== 1879`.
4. `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py`. The diff to `docs/development/config-reference.md` must be the one table row after `:677`: `` | `claim_currency_shadow_enabled` | `bool` | `True` | — |  | ``.
5. `tests/test_ad1152_agentic_correlation.py`, in `_off_observation` after `:347` (BF-957's last `pop`), following `_DEFAULT_CONFIG_RULE` (`:54-57`: an added field is popped with its default asserted; the golden stays):
   ```python
    # AD-1302 S1's claim-currency switch was added after this capture too. It defaults on and is read in
    # ProbOSRuntime.start, which this observation never calls; its tool calls go to a recorder, not the registry.
    assert config["records"].pop("claim_currency_shadow_enabled") is True
   ```
   Do not touch `tests/fixtures/ad1152_agentic_off_golden.json`.

If a count named above has moved by build time because another field landed first, use the current value plus one and report it. If either script's diff holds anything else, stop and report it; do not commit unrelated drift.

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
(`records_store.py:13-14`. The file has no `dataclasses` import and uses `date` only in comments.)

**Pair 2, after `record_is_readable`.** SEARCH:
```python
    # BF-969 (#1800): an empty or non-str author is nobody, so it admits no reader, "" included.
    doc_author = _author_identity(frontmatter.get("author"))
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
    # BF-969 (#1800): an empty or non-str author is nobody, so it admits no reader, "" included.
    doc_author = _author_identity(frontmatter.get("author"))
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

**Pair 3, after `entry_fingerprint`.** SEARCH:
```python
        return hashlib.sha256(file_path.read_bytes()).hexdigest()

    async def list_entries(
```
REPLACE:
```python
        return hashlib.sha256(file_path.read_bytes()).hexdigest()

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
        It never raises: traversal, an unreadable file or a frontmatter that does not load (``{}``, BF-970) is
        ``unreadable``. Not ``entry_fingerprint``: that is async, ungated and identifies bytes, not the revision.
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

The Builder verifies that importing `probos.knowledge.records_store` from `probos.tools.registry` adds no cycle. `records_store` imports `probos.cognitive.provenance` (stdlib only, `tests/test_layer_boundaries.py:89-92`), `probos.execution.command_env` and `probos.utils.*` (`records_store.py:19-22`), and importing `probos.knowledge` runs its package `__init__` (`knowledge/__init__.py:3-22`). Run `python -c "import probos.tools.registry"` in a fresh interpreter. If it does add a cycle, move the `RecordsStore` import under `TYPE_CHECKING` and replace the constructor's `isinstance` with a check for the `current_revision` attribute, then report the change.

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
SEARCH (it keeps AD-1357's `sources_out` lines exactly as they are, `oracle_service.py:802-810`):
```python
            if char_count + len(line) + 1 > max_chars:
                break
            lines.append(line)
            char_count += len(line) + 1
            if sources_out is not None:
                sources_out.append((r.source_tier, str(r.metadata.get("path") or "")))

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
            if sources_out is not None:
                sources_out.append((r.source_tier, str(r.metadata.get("path") or "")))

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
Add this method right before `_bounded` (`:359-360`), keeping its `@staticmethod` decorator on `_bounded`:
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
The `getattr` chain follows the same file's existing envelope access at `:345`. It is not a guard on an API this prompt defines.

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
Add `from probos.knowledge.claim_currency import ClaimCurrencyMonitor` to the module's existing `if TYPE_CHECKING:` block (`registry.py:31-37`, beside `from probos.admission import AdmissionService`).

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
**Pair 4.** SEARCH (`registry.py:415-418`; the other not-found return at `:485` has different neighbours):
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
(`SEAM_TOOL` is already imported, `registry.py:17`.)

**Pair 5, `docs/development/architecture-baseline.yaml`** (§5 row 11). Pairs 2 to 4 take `ToolRegistry` from 498 to 504 lines, past `SRP_MAX_BODY_LINES = 500`. In the reviewed row at `:977-984`, SEARCH:
```yaml
  key: probos.tools.registry::ToolRegistry
  triggers:
  - methods
```
REPLACE:
```yaml
  key: probos.tools.registry::ToolRegistry
  triggers:
  - lines
  - methods
```
Change nothing else in the row (its owner, AD-1270h, and rationale stand). Do not run `--update-baseline`. Run `scripts/check_architecture_principles.py --check`: it must pass, and before Pair 5 it must report exactly one `TRIGGER DRIFT [srp-size] probos.tools.registry::ToolRegistry`. If it reports anything else, or if `ToolRegistry` no longer crosses 500 lines on the build tree, stop and report it.

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
**cognitive_agent, pair 2.** SEARCH (`cognitive_agent.py:8227-8231`):
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

**runtime, pair 1.** SEARCH (`runtime.py:1256`):
```python
        self.admission_service: AdmissionService | None = None  # AD-1346 M3a: set after identity_service in start()
```
REPLACE:
```python
        self.admission_service: AdmissionService | None = None  # AD-1346 M3a: set after identity_service in start()
        self.claim_currency: ClaimCurrencyMonitor | None = None  # AD-1302 S1: set in start() when the switch is on
```
Add `from probos.knowledge.claim_currency import ClaimCurrencyMonitor  # AD-1302 S1` to the `TYPE_CHECKING` block from which `AdmissionService` is imported for that annotation (`runtime.py:159-170`, `:166`). Also add the class-level declaration beside `admission_service`'s (`runtime.py:551`): `claim_currency: ClaimCurrencyMonitor | None  # AD-1302 S1: set in start() when records.claim_currency_shadow_enabled is true`.

**runtime, pair 2.** SEARCH (`runtime.py:3454-3457`, inside `start()`, `:2804`, after `self._records_store = cog.records_store` at `:3082`):
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
`self.config.records` is the `RecordsConfig` instance: `records: RecordsConfig = RecordsConfig()` (`config.py:3937`). BF-932's loop-stall sampler, started later in `start()` (`runtime.py:3833-3846`), is unaffected.

## 8. Tracking (M2; re-anchor on the newest head entries at build time and change no wording)

The anchors on `1d9ba205` are named below; at build time use whatever is newest then.

**`PROGRESS.md`**, a new head entry after `# ProbOS Progress` (`:1`), above the newest entry (on `1d9ba205`: `**BF-932 (2026-11-27), #1670 batch 1 -- ...` at `:3`):

> **AD-1302 S1 (YYYY-MM-DD), #1355 slice 1 -- the currency of borrowed Ship's Records claims in an agent's context, observed at the tool sink in shadow.** `handle_intent` opens a per-intent claim ledger (`probos.knowledge.claim_currency`). `OracleService.query_formatted` and the `oracle_query` tool note each Ship's Records result they actually show, by path and exact store revision (`record:{path}@{revision}`) with the reader it was retrieved for. At every tool call `ToolRegistry.check_and_invoke` compares the noted revisions with `RecordsStore.current_revision` on disk for that reader, then counts and logs `stale`, `regressed`, `changed_same_revision`, `missing`, `withheld` and `unknown`. Nothing is refused, no text changes, no event is emitted and no episode is touched. The switch is `records.claim_currency_shadow_enabled` (default on). Not covered, and reported unknown: corrections published at a new path (every `publish_finding` correction), corrections AD-550 deduplication suppresses, the consultation and standalone run entries, the crew commons consult, the DM lookup, memory refs, the introspect and organizer agents, direct Records reads outside the Oracle (the proactive notebook reads, the DM lookup's and self-monitoring context's searches, the diagnostic context and the head-to-head game tally), a correction session's projected-registry tools, the archive tier, and effects other than tool calls (Ward Room posts among them). New: `tests/test_ad1302_s1_claim_currency.py`. The contract is `prompts/ad-1302-s1-context-claim-currency.md`.

**`DECISIONS.md`**: a new entry `### AD-1302 S1 -- the currency of borrowed Records claims in an agent's context, observed in shadow (YYYY-MM-DD, #1355)`, inserted as the newest entry: under `## Era V — Civilization (Phases 31-36)` (`:11`), directly above the newest entry (on `1d9ba205`: `### BF-932 -- ...` at `:13`). Write one paragraph with the intro, one bullet each for D1 to D11 (a line each, taken from §3), an *Enrolled population* bullet taken from §9, the *Mutation campaign of record* bullet, and *Reversal: revert the S1 commits; nothing is persisted.* Do not edit the planning entry `### AD-1302 (2026-09-07) - Dependency-aware knowledge reassessment` (`DECISIONS.md:12159` on `1d9ba205`).

**`docs/development/roadmap.md`**: the AD-1302 row exists (`:473`). Append `; S1 (in-context currency, shadow) built` to its last cell. Change nothing else.

## 9. What this does NOT change, and the enrolled population

**Enrolled:** the intent entry (`handle_intent`) x the `query_formatted` and `oracle_query` tool renderers x the Records tier x the tool sink. **Oracle consumer census (T14, frozen):** `agents/introspect.py` 1 (`:846`, unknown), `agents/utility/organizer_agents.py` 1 (`:200`, unknown), `cognitive/crew_executor.py` 1 (`:1812`, unknown: the AD-1141 commons consult), `cognitive/dm_targeted_lookup.py` 1 (`:214`, unknown), `cognitive/cognitive_agent.py` 2 (`:12035`, enrolled through `query_formatted`; `:12067`, the BF-265 graph-only call, shows no Records), `experience/commands/commands_knowledge.py` 1 (`:91`, the Captain's shell, not an agent context), `tools/oracle_query_tool.py` 1 (`:326`, enrolled), `cognitive/provenance.py` 2 (`:222` the definition and `:233` its call: the tool's path), `routers/system.py` 1 (`:724`, API, not an agent context), `cognitive/sub_tasks/query.py` 2 (`:274` `query_formatted` enrolled; `:346` `query_refs` unknown). The Builder re-runs the regex on the build tree and freezes the counts it finds (13 hits with these per-file counts on `632f2c87` and again on `1d9ba205`, re-run 2026-11-28). The census covers Oracle method calls only. It does not cover:

- **Direct Records reads into agent context outside the Oracle**, unknown: the proactive notebook reads (`proactive.py:2929`, `:3011`, `:4029`), the `RecordsStore.search` calls of the DM lookup (`dm_targeted_lookup.py`, `_dispatch`) and of the self-monitoring context (`proactive.py`, `_build_self_monitoring_context`), both frozen by `tests/test_bf949_notebook_reader_identity.py:38-43`, the diagnostic context's `RecordsStore.read_entry` (`cognitive/diagnostic_context.py:414`), and AD-1358's head-to-head game tally (`recreation/history.py:198`). Other `read_entry`/`search` callers (`routers/records.py`, `routers/gaps.py`, `commands_gap.py`, `dreaming.py`, `archive_promotion.py`, `backlinks.py`, `semantic.py`) are not agent-context renderers or are not classified in S1.
- **A correction session's projected registry** (`cognitive/crew_verifier.py:465`, `_SessionProjectedToolRegistry`), unknown for its own (mesh) tools. It receives `set_admission` (`:1254`) but S1 does not give it `set_claim_currency`, so its `super().check_and_invoke` path (`:610`) checks nothing. Its source-backed tools delegate to the source registry (`:600`) and are checked there when that is the ship's registry.
- **Tool calls outside an intent's extent** (a crew work item's loop that runs in a task not created inside `handle_intent`) count `no_ledger`. That count is the visible measure of this gap; it is not a defect.

**Not changed:** the stored-derivation reassessment, which is the rest of AD-1302; supersession links between findings (S2); AD-550 deduplication; the content and rendering of any context; AD-1357's context manifest; tool permissions and refusal; the AD-1346 admission service, tickets, census and store; `EventType`; episodic memory; the Ship's Archive; federation (AD-1303); AD-1300's goal revisions; `config/system.yaml`; `entry_fingerprint` and Dream Step 7g.

## 10. Diff Reviewer: properties to verify

1. Every agent-visible output (`query_formatted`, the `oracle_query` tool result, any tool result) is byte-identical with the monitor on, off and absent, and `query_formatted`'s `sources_out` list is unchanged.
2. No `Exception` from the ledger, the monitor or the store reaches `check_and_invoke`, `query_formatted` or the tool.
3. A note is made only for a Records result that was rendered, and only for the reader that retrieved it. `withheld` discloses no revision of a record the reader may no longer read.
4. The ledger is reset on the return, raise and cancel paths of `handle_intent`. No intent's claims are visible to the next intent on the same task.
5. The I10 invariants of `handle_intent` hold (`tests/test_ad1346_admission_ticket_issue.py:551-578`).
6. The sink statement awaits nothing and, with an empty ledger, reads no file.
7. The runtime builds no monitor when the switch is off, and the boot survives a constructor that raises.
8. The only change to `docs/development/architecture-baseline.yaml` is the `lines` trigger of the `ToolRegistry` row, and the five config consumers of §7.1 change by exactly the entries named there.

## 11. Verified Against Codebase (2026-11-28, HEAD `1d9ba205`, tree `6ee55ee1`)

Run in the worktree at `b8968837` (`git diff --stat 1d9ba205 HEAD`: only this file), so every `src`, `tests` and `docs` line below is `1d9ba205`'s. `git rev-parse 1d9ba205^{tree}`: `6ee55ee196f6858356352218fb549b8d16a6781c`.

```
grep -n "def compute_claim_id" src/probos/knowledge/claims.py
  23: def compute_claim_id(title: str, claim: str, basis: str) -> str:
  31: return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
grep -n "claim_id\[:8\]\|write_notebook(\|_check_similarity(\|contest_state" src/probos/tools/publish_finding_tool.py
  659: slug = f"{_slugify(fields['title'])}-{claim_id[:8]}"
  662: dedup = await self._check_similarity(callsign, slug, body)
  693: path = await self._records.write_notebook(
  829: "contest_state": "uncontested",
grep -n "^from datetime\|^from probos\|LoopYield" src/probos/knowledge/records_store.py
  13: from datetime import datetime, timezone
  19: from probos.cognitive.provenance import record_write_time
  20: from probos.execution.command_env import trusted_command_env
  22: from probos.utils.loop_yield import LoopYield  # BF-932
grep -n "def record_is_readable\|BF-969 (#1800): an empty\|def _jaccard_similarity\|def _load_document" src/probos/knowledge/records_store.py
  153: def record_is_readable(
  217: # BF-969 (#1800): an empty or non-str author is nobody, so it admits no reader, "" included.
  228: def _jaccard_similarity(text_a: str, text_b: str) -> float:
  314: def _load_document(raw: str) -> tuple[Any, str, bool]:
grep -n "existing_rev\|Could not read existing frontmatter\|semantic indexing failed\|Record written:" src/probos/knowledge/records_store.py
  824: existing_rev = existing_fm.get("revision", 1)
  825: frontmatter["revision"] = existing_rev + 1
  836: logger.debug("AD-550: Could not read existing frontmatter for update-in-place", exc_info=True)
  889: "AD-1138: semantic indexing failed for %s; ...
  894: logger.info("Record written: %s by %s (%s)", path, author, frontmatter["classification"])
grep -n "async def check_notebook_similarity\|Layer 2\|Layer 3\|\"action\": \"suppress\"" src/probos/knowledge/records_store.py
  1120: async def check_notebook_similarity(
  1158: # --- Layer 2: Exact topic match ---
  1184: "action": "suppress",
  1223: # --- Layer 3: Cross-topic scan ---
  1260: "action": "suppress",
grep -n "async def read_entry\|async def entry_fingerprint\|hexdigest()\|async def list_entries\|async def publish\|fm\[\"status\"\]\|def _parse_document\|def _safe_path\|until_superseded" src/probos/knowledge/records_store.py
  1490: async def read_entry(
  1533: async def entry_fingerprint(self, path: str) -> str | None:
  1546: return hashlib.sha256(file_path.read_bytes()).hexdigest()
  1548: async def list_entries(
  1667: async def publish(self, path: str, author: str) -> None:
  1687: fm["status"] = "published"
  1874: def _parse_document(self, raw: str) -> tuple[dict, str]:
  1887: def _safe_path(self, user_path: str) -> Path:
  1909: "operations": "until_superseded",
grep -n "_MAX_REVISION =\|def _record_entity_iri\|record:{path}@{revision}\|revision = frontmatter.get" src/probos/knowledge/provo.py
  94: _MAX_REVISION = 2**31 - 1
  126: def _record_entity_iri(path: str, revision: int) -> str:
  136: identity = f"record:{path}@{revision}"
  267: revision = frontmatter.get("revision", 1)
grep -n "^class RecordsConfig\|semantic_index_enabled\|git_lock_stale_minutes" src/probos/config_models/knowledge.py
  317: class RecordsConfig(BaseModel):
  355: semantic_index_enabled: bool = False
  357: git_lock_stale_minutes: float = Field(
grep -n "records: RecordsConfig\|shadow_enabled: bool" src/probos/config.py
  3583: shadow_enabled: bool = True
  3937: records: RecordsConfig = RecordsConfig()
grep -n "oracle.query_formatted(\|sources_out=_oracle_sources\|_oracle_context\"\] = oracle_text\|_intent_hold\|^from probos.admission.seam\|async def handle_intent" src/probos/cognitive/cognitive_agent.py
  24: from probos.admission.seam import hold_at, shadow_at  # AD-1346 M3c; hold_at: AD-1346 M3d2
  8207: async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
  8227: _intent_hold = hold_at(...)
  8229: return await self._handle_admitted_intent(intent)
  8231: _intent_hold.end()
  12035: oracle_text = await oracle.query_formatted(
  12040: sources_out=_oracle_sources,
  12044: observation["_oracle_context"] = oracle_text
  12067: graph_text = await oracle.query_formatted(
grep -n "^from probos.knowledge.archive_store\|_RECORDS_QUERY_SCOPE =\|by_path.setdefault\|def _resolve_records_reader\|async def query_formatted\|sources_out\|ORACLE QUERY RESULTS\|END ORACLE RESULTS\|\"frontmatter\": \|\[ship's records\]" src/probos/cognitive/oracle_service.py
  22: from probos.knowledge.archive_store import LABEL_THIS_CREW, inheritance_label  # AD-1341 S2
  69: _RECORDS_QUERY_SCOPE = "ship"
  230: by_path.setdefault(path, result)
  486: def _resolve_records_reader(self, agent_id: str) -> tuple[str, str]:
  744: async def query_formatted(
  753: sources_out: list[tuple[str, str]] | None = None,
  770: lines = ["=== ORACLE QUERY RESULTS ==="]
  806: if sources_out is not None:
  807: sources_out.append((r.source_tier, str(r.metadata.get("path") or "")))
  809: lines.append("=== END ORACLE RESULTS ===")
  1111: "frontmatter": r.get("frontmatter", {}),
  1113: provenance="[ship's records]",
  1159: "frontmatter": _decode_record_frontmatter(
  1163: provenance="[ship's records]",
grep -n "def note_oracle\|record_paths" src/probos/cognitive/context_manifest.py
  266: def note_oracle(observation: Any, scope: str, sources: Iterable[tuple[str, str]] | None) -> None:
  293: "by_tier": by_tier, "record_paths": paths,
grep -n "_MAX_RESULTS =\|_K_PER_TIER =\|def _render\|text, rendered = _render\|query_with_provenance(\|getattr(getattr(envelope\|def _bounded" src/probos/tools/oracle_query_tool.py
  71: _MAX_RESULTS = 8
  79: _K_PER_TIER = 3
  138: def _render(envelopes: list[Any]) -> tuple[str, int]:
  268: text, rendered = _render(envelopes)
  326: envelopes = await query_with_provenance(
  345: tier = getattr(getattr(envelope, "tag", None), "source_tier", "")
  360: def _bounded(text: str) -> str:
grep -n "metadata=result.metadata\|async def query_with_provenance\|STALE_AFTER_SECONDS:\|def is_stale" src/probos/cognitive/provenance.py
  31: STALE_AFTER_SECONDS: Final = 30 * 86400.0
  162: def is_stale(self) -> bool:
  216: metadata=result.metadata,
  222: async def query_with_provenance(
grep -n "^from probos.admission.seam\|^from probos.agent_stop\|^if TYPE_CHECKING\|^class ToolRegistry\|_admission: \"AdmissionService\|def set_admission\|def register(\|required: ToolPermission = ToolPermission.READ\|check_at(self._admission\|self._tools.get(tool_id) is None\|not found\")" src/probos/tools/registry.py
  16: from probos.admission.seam import check_at, shadow_at
  17: from probos.agent_stop import SEAM_TOOL, STOP_REASON_CODE, tool_refusal
  31: if TYPE_CHECKING:
  85: class ToolRegistry:
  109: _admission: "AdmissionService | None" = None  # AD-1346 M3c (set_admission): None shadows nothing
  143: def set_admission(self, service: "AdmissionService | None") -> None:
  158: def register(
  368: required: ToolPermission = ToolPermission.READ,
  398: check_at(self._admission, effect=SEAM_TOOL, presented_id=agent_id)
  415: if self._tools.get(tool_id) is None:
  416: return ToolResult(error=f"Tool '{tool_id}' not found")
  485: return ToolResult(error=f"Tool '{tool_id}' not found")
wc -l src/probos/tools/registry.py
  582   (the class is the module's last top-level statement: span 85-582 = 498)
grep -n "SRP_MAX_BODY_LINES =\|if span > SRP_MAX_BODY_LINES\|TRIGGER DRIFT" scripts/check_architecture_principles.py
  187: SRP_MAX_BODY_LINES = 500
  566: if span > SRP_MAX_BODY_LINES:
  941: f"TRIGGER DRIFT [{category}] {key}: baseline records "
grep -n "key: probos.tools.registry::ToolRegistry" docs/development/architecture-baseline.yaml
  978: key: probos.tools.registry::ToolRegistry   (triggers: [methods], :979-980)
grep -n "check_architecture_principles" scripts/run_test_gate.py
  1120: [python, "-P", "scripts/check_architecture_principles.py", "--check"],
grep -n "CURRENT_TICKET: Final\|M4" src/probos/admission/carrier.py
  11: AD-1346 M4 decides whether a ticket is threaded explicitly instead.
  24: CURRENT_TICKET: Final[ContextVar[WorkTicket | None]] = ContextVar("probos_admission_ticket", default=None)
grep -n "isinstance(last, ast.Try)\|last.finalbody\|named == {\"probos/admission" tests/test_ad1346_admission_ticket_issue.py
  574: assert isinstance(last, ast.Try) and last.lineno > hold.lineno, qualname
  575: assert [ast.unparse(stmt) for stmt in last.finalbody] == [f"{name}.end()"], qualname
  592: assert named == {"probos/admission/carrier.py", "probos/admission/service.py"}, sorted(named)
grep -n "def test_the_sink_check_is_called_once\|before, after = fn.body" tests/test_ad1346_admission_ticket_sinks.py
  510: def test_the_sink_check_is_called_once_in_each_of_the_two_sinks_in_its_place() -> None:
  524: before, after = fn.body[index - 1], fn.body[index + 1]
grep -n "if \"admission_service\" in text\|assert named == {" tests/test_ad1346_admission_service.py
  635: if "admission_service" in text:
  644: assert named == {
grep -n "def test_each_sink_consults_the_stop_first" tests/test_ad1343_stop_seam_inventory.py
  110: def test_each_sink_consults_the_stop_first() -> None:
grep -n "self.admission_service: AdmissionService\|^    admission_service:\|from probos.admission import AdmissionService  # AD-1346 M3a\|self._records_store = cog.records_store\|self.tool_registry = comm.tool_registry\|self.tool_registry.set_admission\|async def start(\|loop_stall_warn_seconds" src/probos/runtime.py
  166: from probos.admission import AdmissionService  # AD-1346 M3a
  551: admission_service: AdmissionService | None  # AD-1346 M3a: ...
  1256: self.admission_service: AdmissionService | None = None
  2804: async def start(self) -> None:
  3082: self._records_store = cog.records_store
  3454: self.tool_registry = comm.tool_registry
  3457: self.tool_registry.set_admission(self.admission_service)
  3836: _loop_stall_s = self.config.system.loop_stall_warn_seconds
grep -n "'semantic_index_enabled': False\|BF-957 appended\|\"RecordsConfig\": 3" tests/test_ad1270e2f_knowledge_models.py
  239: 'semantic_index_enabled': False,
  240: # BF-957 appended three fields after the move; the move changed none.
  477: "RecordsConfig": 3,  # BF-957: the three git_* doctor thresholds (gt, ge, gt)
grep -n "field_definitions\|BF-932 (#1670) adds" tests/test_ad1270e1_config_facade.py
  1578: # BF-932 (#1670) adds system.loop_stall_warn_seconds (1877 -> 1878).
  1579: assert counts["field_definitions"] == 1878  # AD-1206 intentionally adds github_repository.
grep -n "canonical_dump_leaves\|field_definitions\|canonical_dump_sha256\|semantic_index_enabled" docs/development/config-facade-baseline.yaml
  50: canonical_dump_leaves: 1885
  51: field_definitions: 1878
  56: canonical_dump_sha256: e9100cc1...
  3042: - {default: 'False', name: semantic_index_enabled}
  (RecordsConfig schema_sha256 :3013; SystemConfig schema_sha256 :3415)
git show 3fb44fe8 -- docs/development/config-facade-baseline.yaml
  one field added: canonical_dump_leaves, field_definitions, canonical_dump_sha256, two schema_sha256, one field line
grep -n "semantic_index_enabled" docs/development/config-reference.md
  677: | `semantic_index_enabled` | `bool` | `False` | — |  |
grep -n "_DEFAULT_CONFIG_RULE = \|pop(\"git_last_commit_warn_hours\")\|pop(\"loop_stall_warn_seconds\")" tests/test_ad1152_agentic_correlation.py
  54: _DEFAULT_CONFIG_RULE = (
  347: assert config["records"].pop("git_last_commit_warn_hours") == 24.0
  353: assert config["system"].pop("loop_stall_warn_seconds") == 1.0
grep -n "def default_false_flags\|if default is False" scripts/check_config_profiles.py
  148: def default_false_flags() -> list[str]:
  170: if default is False:
grep -rn "boolean_fields_reachable\|default_true" scripts/check_config_profiles.py tests/
  (none outside unrelated test names: the config-profiles.yaml census is not read)
grep -n "class _SessionProjectedToolRegistry\|_source_registry.check_and_invoke\|super().check_and_invoke\|registry.set_admission(" src/probos/cognitive/crew_verifier.py
  465: class _SessionProjectedToolRegistry(ToolRegistry):
  600: return await self._source_registry.check_and_invoke(
  610: return await super().check_and_invoke(
  1254: registry.set_admission(getattr(runtime, "admission_service", None))
grep -rn "read_entry(" src/probos  (agent-context readers named in §9)
  cognitive/diagnostic_context.py:414, proactive.py:2929, :3011, :4029, recreation/history.py:198
grep -n "def effect_coverage_report" src/probos/execution/effect_broker.py
  110: def effect_coverage_report() -> EffectCoverageReport:   (the honest-population precedent, :110-134)
grep -n "\"cognitive\": {\|records_store.py\", \"probos.cognitive.provenance\"" tests/test_layer_boundaries.py
  51: "cognitive": {"knowledge", "substrate", "mesh"},
  92: ("knowledge/records_store.py", "probos.cognitive.provenance"),
grep -n "AD-1302" docs/development/roadmap.md
  473: | AD-1302 | Dependency-aware reassessment of derived knowledge | [#1355](...) | Local contract first; AD-1303 owns the federation crossing |
grep -n "### AD-1300 (2026-09-07)\|### AD-1302 (2026-09-07)\|^## Era V\|^### BF-932" DECISIONS.md
  11: ## Era V — Civilization (Phases 31-36)
  13: ### BF-932 -- the dream cycle gives the event loop turns and a loop-stall sampler names any blocker (2026-11-27, #1670)
  12133: ### AD-1300 (2026-09-07) - Goal validity and supersession
  12159: ### AD-1302 (2026-09-07) - Dependency-aware knowledge reassessment
gh issue view 1353 / 1355
  #1353 OPEN; #1355 OPEN, one comment (2026-11-02, the Captain's slice decision, D12)
git ls-files --eol src/probos/tools/registry.py src/probos/knowledge/records_store.py
  i/lf w/crlf (both)
```

## Absence Verified (2026-11-28)

| # | Claim | Run | Found | Holds |
|---|---|---|---|---|
| AV1 | No supersession or correction link exists between Records entries | Grep `-i "contest_state\|supersed\|retract"` over `src/probos/knowledge` and `src/probos/tools` | `confidence_tracker.py:71-75` (confidence below a threshold), `records_store.py:1909` (`"until_superseded"`, a retention string), `publish_finding_tool.py:829` (`"contest_state": "uncontested"`, a constant; grep over `src`: its only occurrence), `work_permits.py:41` (a permit superseded by a later request; unrelated) | yes |
| AV2 | Nothing records which Records **revisions** entered an agent's context | Grep `revision` in `oracle_service.py`, `oracle_query_tool.py`, `provenance.py`, `context_manifest.py` | none (AD-1357's manifest keeps paths only, P13) | yes |
| AV3 | No other AD-1300 to AD-1304 prompt is in flight | Glob `prompts/ad-130[0-4]*` | this file only | yes |
| AV4 | AD-1300 has no implementation to reuse | `DECISIONS.md:12135`; `gh issue view 1353` | "planned, not implemented"; OPEN | yes |
| AV5 | Invocation callers do not pass `required` | Grep `required=(ToolPermission\.\w+\|required\|_required\|perm\w*)` over `src/probos` | `agent_work_runner.py:492` (`WRITE`, claim), `crew_verifier.py:604,614` and `context.py:135` (pass-through), `registry.py:433,456` (internal) | yes |
| AV6 | No Records "borrowed" label exists outside the archive | Grep `-i "borrowed"` and `-i "inherited"` over `src/probos` | the archive labels (`archive_store.py:400-427`), the Oracle's archive tier (`oracle_service.py:410,480,1219`), and unrelated matches (`config.py:3808`, `runtime.py:1976,2170`, `cognitive_agent.py:1656,6416` and others) | yes |
| AV7 | Internal research has no prior in-context supersession study | Grep `-i "supersession\|in-context\|stale claim\|retraction"` over `docs/research` | `dynamic-communication-register-research.md` only (unrelated) | yes |
| AV8 | No S1 name already exists in `src` | Grep `claim_currency\|ClaimCurrency\|claim_ledger\|ContextClaimLedger\|current_revision` and `RecordRevision\|REVISION_(PRESENT\|MISSING\|WITHHELD\|UNREADABLE)\|parse_record_revision\|record_updated_text\|_MAX_RECORD_REVISION` over `src` | none | yes |

## 12. Not verified (the Builder verifies by running)

- No import cycle from `tools/registry.py` -> `knowledge/claim_currency.py` -> `knowledge/records_store.py` (§7.3).
- The regenerated artifacts' exact diffs (§7.1 steps 2 and 4) and the architecture check's single `TRIGGER DRIFT` (§7.6, Pair 5); this review predicts them from the code and from BF-932's commit `3fb44fe8`, but ran no Python.
- That no other source-scan census in `tests/` counts the new statements or names; the ones the change could reach were searched (§5 rows 1, 3, 9, 11, 13; D2), and the broad gate is the backstop.
- Hot-path cost: a ContextVar read and a dict increment with no ledger. The Builder reports a 20,000-call median of `currency_at` with no ledger and with 8 fresh refs, timed with `time.perf_counter_ns`, as a disclosed figure, plus one timing of a 16-ref check against real files (the per-sink worst case, B9). No threshold is set.

## 13. Prior Art and Blind Spots

**Internal.** P4's `record:{path}@{revision}` identity is adopted as is. The honest-population pattern is adopted from `effect_coverage_report` (`effect_broker.py:110-134`), as a test census rather than a runtime function, to avoid a built-but-never-called report. BF-950's `ProvenanceTag.is_stale` (`provenance.py:31`, `:118-119`, `:161-164`) measures the **age** of the content (written more than 30 days ago), not its currency against a later revision, and S1 does not reuse or rename it. AD-1357's context manifest (P13) records which Records **paths** a chat reply was given; S1 records the revision shown and checks it at the sink, and the two agree on the rendered set (T6). BF-932's `entry_fingerprint` (P14) answers "did the bytes change between two reads I made", for Dream Step 7g; S1's question is "has the claim I was shown been revised", so it is not reused (D6). AD-1300 is aligned in vocabulary only (AV4). The Ship's Archive label (AD-1341 S2) is a different population. `docs/research` holds nothing on the topic (AV7).

**External (2026-11-02; not re-run on 2026-11-28, a re-verification with no design change).** `docs/research/reference-projects.md` checked on 2026-11-28 against the date 2026-11-28: RAGFlow was last reviewed 2026-11-20 and the LoCoMo benchmark 2026-11-26, so neither is overdue. AG-UI has never been reviewed and is not relevant here.
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
- **B4.** A revision can regress (`records_store.py:835-836`), and `publish` changes `updated` without a revision (P5). These are counted separately and never reported as `stale`.
- **B5.** Concurrent `write_entry` calls can both write N+1, because there is no lock around the read-modify-write. S1 inherits this. The duplicate and out-of-order acceptance line of AD-1302 owns it.
- **B6.** The most common effect is not a tool call. A Ward Room post or DM reply that repeats a stale claim is an effect S1 does not reach (§9). The enforcement slice must name it.
- **B7.** Reclassification. A record narrowed to `private` after it was shown is `withheld`, and no revision or content is disclosed (D6).
- **B8.** The check cannot judge relevance. A stale claim can sit in context without having influenced the call. In shadow this inflates the count, so S1's figures are an upper bound and are reported as such. A re-read does not clear the older note either: after reading revision 2, the ledger holds both `@1` and `@2`, and `@1` keeps checking `stale`. That is correct for S1 (the context still holds the revision 1 text), but S3's notice must not tell an agent to re-read what it already re-read.
- **B9.** The sink's reads run on the event loop thread, the concern BF-932 just instrumented. They are bounded by `MAX_CHECKS_PER_SINK = 16` small local files per tool call (the same batch size `list_entries` now yields after), and none happens with an empty ledger. If they ever hold the loop past `system.loop_stall_warn_seconds` (default 1.0 s, `config_models/core.py:160-161`), the loop-stall sampler (`runtime.py:3833-3846`) names `current_revision`; that is the measurement, and moving the check off the loop is the remedy, not an S1 change.

**What comes after S1 (ranked; each is its own slice):**
1. **S2: authorized supersession.** A `supersedes: <path>` link written by the original author or the Captain, validated (the target exists, the author matches, no cycle), that bypasses AD-550 against its target (B1, B2). The monitor then names the successor path, readable by the reader, in its finding. Within the envelope.
2. **S3: agent-visible notice (advisory).** Append to the tool result at the sink: "A Ship's Records entry you read (`<path>`, revision N) has changed since (now revision M). Re-read it before relying on it; your memory of reading revision N stays as it was." A withheld entry gets "is no longer available to you" and nothing more. This changes what agents see, so it builds only after S1's shadow figures show a non-trivial stale rate. It is a design decision within the envelope, but the orchestrator reports it to the Captain before enabling it on the live crew.
3. **Enforcement** through AD-1346's admission decision, as one more effect-point check AD-1346 owns, refusing **consequential** calls on a `stale` claim until it is re-read. It needs a consequential-tool classification (P11) and AD-1346 out of shadow. **Captain:** the switch from shadow to refusal, together with AD-1346's own.
4. **Freshness lease.** `noted_at` is already recorded, so a later slice can bound reasoning that never reaches an effect point. Deferred until S1's figures exist.
5. **Push supersession notice** on the event bus to agents holding a claim. Lowest rank: best-effort, never the guarantee, and it needs a holder index S1 does not keep.

## 14. Acceptance criteria

- [ ] T1 to T14 pass in a clean checkout and in a worktree where `config/system.yaml` is modified (no hash of it is frozen).
- [ ] The crossing (T11) goes intent entry -> real Oracle render -> real Records correction -> real tool sink -> `stale` counted and logged, with the tool result unchanged.
- [ ] The focused gate in §4 is green, with `check_config_profiles.py --check` and `check_architecture_principles.py --check`. The mutation campaign of record kills all 14 rows and is recorded.
- [ ] The Diff Reviewer's properties in §10 are verified, and its findings are repaired before commit.
- [ ] The trackers in §8 are written, and the broad gate is run once with a receipt by the orchestrator.
- [ ] The orchestrator adds a comment to #1355 recording the in-context slice and its population (§9).
- [ ] The five frozen config consumers (§7.1) each changed by exactly the entries named, and the `ToolRegistry` row of the architecture baseline gained only the `lines` trigger (§7.6, Pair 5).
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

**Re-verification (2026-11-28, `claude-architect`, base `1d9ba205`, tree `6ee55ee1`):** every anchor, SEARCH block, test pin, the 13-hit census and AV1 to AV8 re-run (§11); records_store Pairs 2 and 3 re-cut for BF-969's `record_is_readable` tail and BF-932's `entry_fingerprint`, and `query_formatted`'s second SEARCH for AD-1357's `sources_out` lines; three frozen consumers the 2026-11-02 review also missed (`field_definitions` at `test_ad1270e1_config_facade.py:1579`, the AD-1152 default-config `pop` rule, and the `ToolRegistry` SRP row, 498 -> 504 lines, already 498 on `632f2c87`) and the facade baseline's real diff shape (six entries, not one) added in §5 and §7; `entry_fingerprint` and `sources_out` decided as not reused (D4, D6); the Captain's slice decision of D12 now verified on #1355 (comment of 2026-11-02); no §3 design decision changed.
