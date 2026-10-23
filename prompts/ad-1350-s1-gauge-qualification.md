# AD-1350 S1: qualify the gauge before it drives a decision (EVALUATE recommendation)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22
**Status:** Filed as #1637, 2026-10-22 (PAUSED under the new-capability pause). Related defects: BF-921 (#1636). **Dependencies:** none. **Estimated tests:** about 22 in one new file, plus one snapshot-dict update.
**Slice:** S1 of AD-1350. S1 adds a measurement only. It changes no verdict, threshold, trust weight or gate.

## Summary

Manufacturing qualifies a gauge (Measurement System Analysis, Gage R&R) before its readings may accept or reject a part. ProbOS's chain EVALUATE step is such a gauge: its `recommendation` decides whether a crew member's post is suppressed, and a suppressed proactive post forfeits its trust reward. Nobody has measured whether EVALUATE gives the same reading twice for the same input. This slice adds (1) an opt-in capture of each real EVALUATE reading with its exact request, (2) a pure statistics core (attribute agreement with Fleiss kappa, ANOVA Gage R&R with %GRR and ndc), and (3) an offline replay script that re-reads captured inputs N times through the same LLM path and writes a study report. The first baseline is an operator run after capture has collected data. That run is not a test.

## Problem

1. **EVALUATE is a decision gauge that affects trust.** It calls the LLM at `temperature=0.0` (`src/probos/cognitive/sub_tasks/evaluate.py:636-645`). A `"suppress"` recommendation makes the chain return `[NO_RESPONSE]` (`src/probos/cognitive/cognitive_agent.py:5941-5969`). On the proactive path, `[NO_RESPONSE]` skips the `proactive_think` trust success (`src/probos/proactive.py:1361-1375` with `trust_no_response_weight: float = 0.0` at `src/probos/config.py:3215`, versus the reward at `proactive.py:1592-1604`, `config.py:3214,3216`). Suppression also emits `CONFABULATION_SUPPRESSED` (`cognitive_agent.py:5952`), which the Counselor turns into a `success=False, weight=0.5` trust outcome on the second suppression within an hour (`src/probos/cognitive/counselor.py:1740-1750`).
2. **The gauge has never been qualified.** No code or document measures the repeatability of any ProbOS LLM judge (see Absence Verified). Temperature 0 does not make it repeatable. External studies measured run-to-run variation at temperature 0, with "limited or inconsistent" temperature effects for Anthropic models (Prior Art).
3. **Live readings show a gauge that has not been characterized.** The study used 6,140 LLM verdict lines in the live logs (`%LOCALAPPDATA%\ProbOS\data\logs\probos.log*`, 2026-07 to 2026-10-22):
   - recommendation: approve 3,075 (50.1%), revise 2,116 (34.5%), suppress 949 (15.5%);
   - in 603 readings (9.8%), one reading contradicts itself: `pass=True` with `revise` 576 times, `pass=True` with `suppress` 24 times, `pass=False` with `approve` 3 times;
   - 175 more calls returned output that could not be parsed. These were recorded as approve with score 1.0 (`evaluate.py:683-701`), so 2.8% of the 6,315 LLM calls produced no reading at all;
   - the 0-1 score clusters on a few values: 0.82 (16.4%), 0.00 (14.4%), 0.78, 0.88 and 0.91 together cover 55.5%.
   None of this measures repeatability. The live data contains no repeated reading of the same input: chain-step journal rows carry no `prompt_hash` (3,505 EVALUATE rows, 0 hashed, `cognitive_journal.db`), and EVALUATE inputs embed each fresh draft, so an exact repeat never happens naturally. Measuring repeatability therefore needs a captured input and a deliberate re-read. That is what this slice builds.
4. **Upcoming consumers need the number.** AD-1186 Ship Trials (#1123) requires that the "statistical policy [be] settled before any score blocks main — a single noisy judge delta must not fail a build". Without a repeatability figure that policy cannot be set. AD-522's SPC store (`src/probos/cognitive/spc/`) runs control charts, and in manufacturing a control chart is valid only on a qualified gauge. The Captain's local-models goal means a tier swap, which is reproducibility (appraiser variation) in MSA terms.

## Solution

Treat each captured EVALUATE input as a **part**, each re-read as a **trial**, and each model as an **appraiser**.

- **Attribute gauge (primary):** `recommendation` in {approve, revise, suppress}, plus an `unreadable` outcome for parse failures. Report within-part agreement, Fleiss kappa within each appraiser, between-appraiser kappa when two or more appraisers are run, and the **decision flip rate**: the share of parts whose trials disagree on suppress versus not-suppress, which is the boundary that touches trust.
- **Variable gauge (secondary):** `score`. Report ANOVA Gage R&R (AIAG crossed design): variance components, %GRR of total variation, and ndc = floor(1.41 x sigma_part / sigma_GRR). The score has no programmatic consumer today; REFLECT receives it only as prompt text (`src/probos/cognitive/sub_tasks/reflect.py:168-174`). Report it so that any future consumer, and #1123, start from a measured figure.
- **Classify against AIAG rules of thumb**, stated in the report: %GRR < 10 acceptable, 10-30 marginal, > 30 unacceptable; ndc >= 5 required; kappa >= 0.75 good, 0.40-0.75 marginal, < 0.40 poor.
- **Readings that are not measurements are excluded:** a client cache replay (`LLMResponse.cached`, `src/probos/cognitive/llm_client.py:1996-2010`) is a copy of an earlier answer, and an LLM error has no reading. Both are counted and excluded. Unreadable output is a reading (`unreadable`) and is not coerced to approve.

### Section 0: Event types

None. This slice adds no `EventType`.

### Section 1: Config (opt-in capture)

`src/probos/config_models/knowledge.py`, `SubTaskConfig`:

SEARCH:
```python
    max_concurrent_chains: int = 4             # AD-636: Cap simultaneous chain executions
    nats_publish_enabled: bool = False         # AD-641g: opt-in chain step publish to NATS
    nats_payload_max_bytes: int = 16384        # AD-641g: cap on result-dict serialized size
```
REPLACE:
```python
    max_concurrent_chains: int = 4             # AD-636: Cap simultaneous chain executions
    nats_publish_enabled: bool = False         # AD-641g: opt-in chain step publish to NATS
    nats_payload_max_bytes: int = 16384        # AD-641g: cap on result-dict serialized size
    # AD-1350: record each LLM-judged EVALUATE reading (exact request + what it read) to
    # <data_dir>/gauge_readings/evaluate.jsonl for gauge qualification. Off by default: the
    # file holds crew prompt text. Capture stops (it does not rotate) at the record cap.
    gauge_capture_enabled: bool = False
    gauge_capture_max_records: int = Field(default=1000, ge=1)
```

`Field` is already imported in that file (`knowledge.py:10`).

Update the defaults snapshot in `tests/test_ad1270e2f_knowledge_models.py:293-300`: add `'gauge_capture_enabled': False, 'gauge_capture_max_records': 1000` to the `'SubTaskConfig'` dict. This dict pins defaults; it is not a `?raw` scan. Add an inline comment `# AD-1350: opt-in gauge capture`. Regenerate `docs/development/config-reference.md` with `python scripts/gen_config_reference.py` (enforced by `tests/test_config_reference_current.py`).

**Do not edit `config/system.yaml`.** It carries an unstaged Captain change. The defaults are enough for this slice. If any test demands that `system.yaml` list the new keys, hard-stop and report.

### Section 2: New module `src/probos/cognitive/gauge_capture.py`

Full new file. Its contents:

- `GAUGE_CAPTURE_SCHEMA = 1`.
- `@dataclass(frozen=True) class CapturedReading` with these fields, in order: `gauge: str`, `mode: str`, `agent_type: str`, `tier: str`, `temperature: float`, `max_tokens: int`, `system_prompt: str`, `user_prompt: str`, `input_sha256: str`, `model: str`, `cached: bool`, `readable: bool`, `recommendation: str | None`, `passed: bool | None`, `score: float | None`, `captured_at: str` (ISO-8601 UTC).
  - `input_sha256(system_prompt: str, user_prompt: str) -> str`: a module function returning `sha256(system + "\x00" + user)` hex digest. The part identity is the exact request text.
  - `to_json(self) -> str` emits one line with `"schema": GAUGE_CAPTURE_SCHEMA`.
  - `@classmethod from_json(cls, line: str) -> CapturedReading` raises `ValueError` on a wrong schema, a missing field or a wrong type. It also recomputes `input_sha256` and rejects a mismatch, so a hand-edited line cannot pose as another part.
- `def reading_from_llm_output(*, gauge, mode, agent_type, tier, temperature, max_tokens, system_prompt, user_prompt, content: str, model: str, cached: bool) -> CapturedReading` parses `content` with `probos.utils.json_extract.extract_json` (`ValueError`/`TypeError` mean unreadable). It is readable only when the parse returns a `dict` whose `recommendation` is one of `"approve"`, `"revise"` or `"suppress"`. It records the raw `pass` (bool or None) and `score` (float or None when absent or not a number) as the LLM gave them, **without** the defaults and post-fill that `EvaluateHandler` applies (`evaluate.py:704-733`). The gauge record holds what was read, not what production substituted. The replay script and the handler both call this function, so a reading is parsed one way only (DRY).
- `class GaugeReadingSink(Protocol)`: `async def record(self, reading: CapturedReading) -> None`.
- `class GaugeReadingRecorder` implements the sink.
  - Constructor: `__init__(self, path: Path, *, max_records: int) -> None`.
  - `record` appends one `to_json()` line through `asyncio.to_thread`, under a `threading.Lock`. On first use it counts the existing lines. Once `max_records` lines exist it stops writing and logs one INFO line, `"AD-1350: gauge capture at cap (%d records) at %s; capture stopped"`, then stays silent. It creates the parent directory.
  - It never raises to the caller. It follows the log-and-degrade tier: on `OSError`, log one WARNING with the path and the error, disable itself, and return.
  - `@property records_written -> int`.
- `def load_captures(path: Path) -> tuple[list[CapturedReading], int]` returns the parsed readings and a count of lines rejected by `from_json`. A rejected line is skipped, never fatal.

### Section 3: `EvaluateHandler` records one reading per LLM call

`src/probos/cognitive/sub_tasks/evaluate.py`.

3a. Constructor (`evaluate.py:369-371`):

SEARCH:
```python
    def __init__(self, *, llm_client: Any = None, runtime: Any = None) -> None:
        self._llm_client = llm_client
        self._runtime = runtime
```
REPLACE:
```python
    def __init__(
        self,
        *,
        llm_client: Any = None,
        runtime: Any = None,
        reading_sink: GaugeReadingSink | None = None,  # AD-1350: opt-in gauge capture
    ) -> None:
        self._llm_client = llm_client
        self._runtime = runtime
        self._reading_sink = reading_sink
```
Add `from probos.cognitive.gauge_capture import GaugeReadingSink, reading_from_llm_output` to the imports (`evaluate.py:18-25`).

3b. Record the reading after parsing and before the branch (`evaluate.py:676-683`):

SEARCH:
```python
        # Parse structured verdict
        content = getattr(response, "content", "") or ""
        try:
            parsed = extract_json(content)
        except (ValueError, TypeError):
            parsed = None
```
REPLACE:
```python
        # Parse structured verdict
        content = getattr(response, "content", "") or ""
        try:
            parsed = extract_json(content)
        except (ValueError, TypeError):
            parsed = None

        # AD-1350: one gauge reading -- the exact request and what the LLM read. Diagnostic
        # only: it is taken after the call and never changes the verdict built below.
        if self._reading_sink is not None:
            await self._record_reading(
                mode_key=mode_key,
                context=context,
                spec=spec,
                request=request,
                content=content,
                model=answered,
                cached=replayed,
            )
```

3c. Add the private method `async def _record_reading(self, *, mode_key: str, context: dict, spec: SubTaskSpec, request: LLMRequest, content: str, model: str, cached: bool) -> None`. It builds the reading with `reading_from_llm_output(gauge="evaluate", mode=mode_key, agent_type=context.get("_agent_type", ""), tier=request.tier, temperature=request.temperature, max_tokens=request.max_tokens, system_prompt=request.system_prompt or "", user_prompt=request.prompt, ...)` and awaits `self._reading_sink.record(reading)`. Wrap the call in `except Exception: logger.warning("AD-1350: gauge reading not recorded for %s", <agent_type>, exc_info=True)`. A capture fault must not cost a crew member their post.

Rules:
- Record only the LLM path. The deterministic suppressions (`raw_json_output` at `evaluate.py:478-481`, `confabulation_detected` at `evaluate.py:519-542`), the social-obligation and boot-camp auto-approvals (`evaluate.py:560-603`), the low-trust skip (`evaluate.py:605-626`) and the LLM-error return (`evaluate.py:646-661`) are not gauge readings and record nothing.
- Add no new `complete()` call to this file (`tests/test_bf688_chain_priority_inheritance.py:51` scans the handlers' LLM calls).

### Section 4: Wiring (`src/probos/startup/finalize.py:5749-5753`)

SEARCH:
```python
        evaluate_handler = EvaluateHandler(
            llm_client=runtime.llm_client,
            runtime=runtime,
        )
        executor.register_handler(SubTaskType.EVALUATE, evaluate_handler)
```
REPLACE:
```python
        # AD-1350: opt-in gauge capture of EVALUATE readings (default off).
        _gauge_sink = None
        if sub_task_config.gauge_capture_enabled:
            from probos.cognitive.gauge_capture import GaugeReadingRecorder

            _gauge_path = runtime.data_dir / "gauge_readings" / "evaluate.jsonl"
            _gauge_sink = GaugeReadingRecorder(
                _gauge_path, max_records=sub_task_config.gauge_capture_max_records,
            )
            logger.info(
                "AD-1350: EVALUATE gauge capture on -> %s (cap %d)",
                _gauge_path, sub_task_config.gauge_capture_max_records,
            )
        evaluate_handler = EvaluateHandler(
            llm_client=runtime.llm_client,
            runtime=runtime,
            reading_sink=_gauge_sink,
        )
        executor.register_handler(SubTaskType.EVALUATE, evaluate_handler)
```
`runtime.data_dir` is the public accessor (`src/probos/runtime.py:2169-2172`).

### Section 5: New module `src/probos/cognitive/gauge_study.py` (statistics and replay, no file I/O)

Full new file containing:

- `fleiss_kappa(counts: Sequence[Sequence[int]]) -> float | None`. Rows are parts, columns are categories, and every row has the same rater count n >= 2. Formula: p_j = sum_i n_ij / (N n); P_i = (sum_j n_ij^2 - n) / (n (n - 1)); kappa = (mean P_i - sum_j p_j^2) / (1 - sum_j p_j^2). Return `None` when sum_j p_j^2 == 1, meaning every reading fell in one category; kappa is undefined there and must not read as perfect. Raise `ValueError` on unequal row totals or n < 2.
- `@dataclass(frozen=True) class AttributeStudy`: `appraiser`, `parts`, `trials`, `within_part_agreement` (share of parts whose trials all agree), `kappa: float | None`, `suppress_flip_rate` (share of parts whose trials disagree on suppress versus not), `unreadable_rate`, `category_counts: dict[str, int]`, `kappa_class: str` ("good" / "marginal" / "poor" / "undefined").
- `attribute_study(appraiser: str, trials_by_part: Mapping[str, Sequence[str]]) -> AttributeStudy` uses the categories `("approve", "revise", "suppress", "unreadable")`. It drops parts with fewer than 2 trials and counts the dropped parts in the report.
- `between_appraiser_kappa(modal_by_appraiser: Mapping[str, Mapping[str, str]]) -> float | None` computes Fleiss kappa over each appraiser's modal reading per shared part. Ties for the mode are broken toward the more severe category (`suppress > revise > unreadable > approve`), and this rule is documented in the docstring.
- `@dataclass(frozen=True) class VariableStudy`: `var_repeatability`, `var_reproducibility`, `var_interaction`, `var_part`, `pct_grr: float | None`, `ndc: int | None`, `grr_class: str`, `parts`, `appraisers`, `trials`.
- `variable_grr(y: Sequence[Sequence[Sequence[float]]]) -> VariableStudy` takes `y[part][appraiser][trial]` as a balanced crossed design. AIAG ANOVA method:
  - SS_P = o r sum_i (ybar_i - ybar)^2; SS_O = p r sum_j (ybar_j - ybar)^2; SS_PO = r sum_ij (ybar_ij - ybar_i - ybar_j + ybar)^2; SS_E = sum_ijk (y_ijk - ybar_ij)^2.
  - df: p-1, o-1, (p-1)(o-1), p o (r-1). Mean squares are SS/df.
  - var_E = MS_E. When o > 1: var_PO = max(0, (MS_PO - MS_E)/r), var_O = max(0, (MS_O - MS_PO)/(p r)), var_P = max(0, (MS_P - MS_PO)/(o r)). When o == 1: var_O = var_PO = 0 and var_P = max(0, (MS_P - MS_E)/r).
  - var_GRR = var_E + var_O + var_PO. pct_grr = 100 sqrt(var_GRR / (var_GRR + var_P)), or `None` when the total is 0. ndc = floor(1.41 sqrt(var_P) / sqrt(var_GRR)), or `None` when var_GRR == 0, with `grr_class="no_measurement_variation"`.
  - Raise `ValueError` on an unbalanced design, p < 2 or r < 2.
- `classify_grr(pct: float | None, ndc: int | None) -> str` returns "acceptable" only when pct < 10 and ndc >= 5, "unacceptable" when pct > 30 or ndc < 2, and "marginal" otherwise.
- `select_parts(readings: Sequence[CapturedReading], *, parts: int, seed: int) -> list[CapturedReading]` deduplicates by `input_sha256` and drops cached readings. It stratifies by the captured `recommendation` (approve, revise, suppress, unreadable as stratum `None`) and draws `parts // strata` from each with `random.Random(seed)`, filling any shortfall from the remaining pool. The output order is deterministic for a given seed. **Why stratify:** a sample of only approve parts has no part variation, so kappa is undefined and %GRR is inflated. AIAG requires parts that span the process range.
- `async def replay(parts: Sequence[CapturedReading], *, client: Any, trials: int, appraiser: str, priority: Priority = Priority.LOW) -> dict[str, list[CapturedReading]]` sends `LLMRequest(prompt=p.user_prompt, system_prompt=p.system_prompt, tier=p.tier, temperature=p.temperature, max_tokens=p.max_tokens)` `trials` times per part, sequentially. It converts each response with `reading_from_llm_output`. A response with `error` set, or with `cached=True`, is counted in `replay.excluded` (return a small dataclass `ReplayResult(readings_by_part, errors, cached_excluded)` instead of a bare dict if that is cleaner; name it in the docstring) and is not a trial.
- `study_report(...) -> dict` is a JSON-serialisable report. It includes the inputs (capture file sha256, parts, trials, seed, appraisers with their configured model names), the attribute studies, the between-appraiser kappa, the variable study for `score` (only over parts whose every trial is readable with a numeric score, and it states how many parts that left), the exclusions, and the thresholds used.

### Section 6: Operator script `scripts/gauge_study.py`

A thin CLI over Section 5. It follows `scripts/diagnose_llm.py:8-19` (`sys.path.insert(0, "src")`, `load_config`, `OpenAICompatibleClient(config=config.cognitive)`).

```
python scripts/gauge_study.py --captures <path to evaluate.jsonl> \
    [--config config/system.yaml] [--parts 20] [--trials 5] [--seed 0] \
    [--appraiser-model MODEL ...] --out <report.json>
```

- With no `--appraiser-model`, there is one appraiser: the configured client as is (the vessel's own path). Each `--appraiser-model M` adds an appraiser whose client is built from `config.cognitive.model_copy(update={"llm_model_standard": M, "llm_model_fast": M, "llm_model_deep": M})`.
- Preflight: send one call for the first selected part. If that call returns `error`, print the error and exit 2 without writing a report. This catches an unreachable endpoint.
- Abort with exit 3, and write a partial report marked `"complete": false`, when more than 20% of calls error.
- Close each client (`OpenAICompatibleClient.close`, `llm_client.py:261`).
- Print a short summary: kappa, flip rate, unreadable rate, %GRR, ndc and their classes.
- The script never touches the running vessel or its databases. It only reads the capture file it is given.

### Section 7: Tests — `tests/test_ad1350_gauge_study.py`

Statistics, pinned to independently computed values (architect reference computation, 2026-10-22):

1. `test_fleiss_kappa_matches_the_published_worked_example`: the 10 x 5 table with 14 raters (Fleiss 1971 as reproduced on Wikipedia: rows `[0,0,0,0,14],[0,2,6,4,2],[0,0,3,5,6],[0,3,9,2,0],[2,2,8,1,1],[7,7,0,0,0],[3,2,6,3,0],[2,5,3,2,2],[6,5,2,1,0],[0,2,2,3,7]`). kappa = 0.2099 +/- 1e-4.
2. `test_fleiss_kappa_is_undefined_when_every_reading_is_one_category`: returns `None`, not 1.0.
3. `test_fleiss_kappa_rejects_unequal_rater_counts`.
4. `test_one_appraiser_grr`: `y = [[[1.0, 1.2]], [[3.0, 3.2]]]` gives var_E = 0.02, var_P = 1.99, %GRR = 9.975 +/- 1e-3, ndc = 14.
5. `test_crossed_grr_separates_reproducibility`: `y = [[[1.0,1.1],[1.2,1.3]], [[2.0,2.2],[2.1,2.4]], [[3.0,2.9],[3.3,3.1]]]` gives var_E = 0.016667, var_O = 0.019583, var_PO = 0, var_P = 0.927083, %GRR = 19.398 +/- 1e-3, ndc = 7.
6. `test_perfect_repeatability_reports_no_measurement_variation`: `ndc is None` and the class is `"no_measurement_variation"`, with no division error.
7. `test_grr_rejects_unbalanced_design`.
8. `test_classify_grr_boundaries`: (9.9, 5) is acceptable, (9.9, 4) marginal, (30.1, 9) unacceptable.
9. `test_attribute_study_flip_rate_counts_only_the_suppress_boundary`: a part read approve/revise has flip 0 and agreement 0; a part read approve/suppress has flip 1.
10. `test_unreadable_is_a_category_not_an_approve`.
11. `test_modal_tie_breaks_toward_severity`.

Capture:

12. `test_reading_from_llm_output_records_raw_values_not_production_defaults`: content `{"recommendation":"approve"}` with no pass and no score gives `passed is None` and `score is None`. The handler would have substituted True and 1.0.
13. `test_reading_from_llm_output_unreadable_on_bad_json_and_on_unknown_recommendation`.
14. `test_captured_reading_round_trips_and_rejects_a_tampered_hash`.
15. `test_recorder_stops_at_cap_and_counts_existing_lines` (`tmp_path`).
16. `test_recorder_disables_itself_on_oserror_and_never_raises`.
17. `test_load_captures_skips_bad_lines_and_counts_them`.

Handler (fake LLM client returning an `LLMResponse` with JSON content; fake sink collecting readings):

18. `test_evaluate_records_the_exact_request_it_sent`: the captured `system_prompt`, `user_prompt`, `tier`, `temperature`, `max_tokens` equal the `LLMRequest` the fake client received.
19. `test_evaluate_verdict_is_identical_with_and_without_a_sink`: compare the whole `SubTaskResult.result` for the parsed case and for the parse-failure case. Do **not** assert what the parse-failure verdict is. Assert only that capture does not change it.
20. `test_evaluate_records_nothing_on_bypass_paths`, parametrized over social obligation, boot camp, low trust band and the deterministic `confabulation_detected` path. Reuse the context setup patterns from `tests/test_bf184_evaluate_social_bypass.py`, `tests/test_ad639_chain_tuning.py` and `tests/test_bf204_grounding.py`.
21. `test_a_failing_sink_does_not_cost_the_post`: the sink raises, and the verdict is unchanged.

Seam (one test that crosses capture -> load -> select -> replay -> report):

22. `test_capture_to_report_chain`: run the real `EvaluateHandler` with a real `GaugeReadingRecorder` (`tmp_path`) over 6 inputs whose fake LLM returns approve, revise or suppress. `load_captures` the file, `select_parts(parts=6, seed=0)`, `replay` with a fake client scripted to flip one part between approve and suppress across 5 trials, then `study_report`. Assert parts == 6, `suppress_flip_rate == 1/6`, the client's `cached=True` responses are excluded and counted, and the report is `json.dumps`-able.

Plus the snapshot update in Section 1 and the regenerated config reference.

**Focused gate** (Builder, after each section): `pytest tests/test_ad1350_gauge_study.py tests/test_ad632e_evaluate_reflect.py tests/test_ad645b_evaluate_brief_alignment.py tests/test_bf184_evaluate_social_bypass.py tests/test_ad639_chain_tuning.py tests/test_bf204_grounding.py tests/test_bf688_chain_priority_inheritance.py tests/test_bf901_s2_journal_token_provenance.py tests/test_ad1270e2f_knowledge_models.py tests/test_config_reference_current.py -v -n 0`.
**Broad gate:** once, by the orchestrator, after review repairs: `scripts/run_test_gate.py --label ad-1350-s1 --receipt logs/gates/ad-1350-s1.receipt.json`.

## What This Does NOT Change

- No verdict, recommendation, threshold, trust weight, Counselor rule or chain gate. Gating trust on gauge quality is deferred until the baseline exists. Only evidence decides it.
- The parse-failure pass-by-default (`evaluate.py:683-701`) stays as it is. It is reported, not changed.
- REFLECT, ANALYZE, COMPOSE, ProcedureJudge (AD-1326), the crew verifier judge (AD-1327), the confab probe (AD-1121) and the qualification harness are not instrumented in S1. The same harness can take them in a later slice.
- No `EventType`, no database, no REST route, no HXI surface.
- `config/system.yaml` is not edited.
- The baseline run itself is an operator step (see Tracking) and is not part of the build.

## Tracking

- `PROGRESS.md`: AD-1350 S1 entry, with a one-line summary and the open item "baseline: enable capture, collect >= 200 readings including >= 20 suppress, run `scripts/gauge_study.py --parts 20 --trials 5`, post the report to the issue".
- `DECISIONS.md`: AD-1350, "An LLM judgment that drives a decision is qualified as a gauge (repeatability, and reproducibility across models) before its readings set thresholds or trust policy. MSA precedes SPC."
- `docs/research/reference-projects.md`, Research lines: add the row `LLM-judge reliability at temperature 0 (arXiv 2502.20747; 2603.04417; 2606.13685)`, Last reviewed 2026-10-22, Depth checked, recorded in `prompts/ad-1350-s1-gauge-qualification.md`.
- The roadmap Bug Tracker gets nothing from this slice. The BF candidates below are filed separately by the orchestrator.

## Acceptance Criteria

- [ ] With `gauge_capture_enabled` false (the default), `EvaluateHandler` behaves exactly as before and no file is created.
- [ ] With it on, every LLM-judged EVALUATE call appends one schema-1 line holding the exact request, and no bypass path appends one. Capture stops at the cap.
- [ ] A capture fault never changes a verdict or raises into the chain.
- [ ] The statistics match the pinned reference values (tests 1, 4, 5), and kappa is `None` (never 1.0) when there is no category variation.
- [ ] Cached replays and LLM errors are excluded and counted. Unreadable output is its own category.
- [ ] `scripts/gauge_study.py` exits 2 without a report when the endpoint is unreachable.
- [ ] The seam test (22) passes.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-10-22)

```
grep -n "temperature=0.0" src/probos/cognitive/sub_tasks/evaluate.py
  640:                temperature=0.0,
grep -n "def __init__(self, \*, llm_client" src/probos/cognitive/sub_tasks/evaluate.py
  369:    def __init__(self, *, llm_client: Any = None, runtime: Any = None) -> None:
grep -n "mode_key = spec.prompt_template" src/probos/cognitive/sub_tasks/evaluate.py
  394:        mode_key = spec.prompt_template or _DEFAULT_MODE
grep -n "replayed = \|answered = answered_model_name" src/probos/cognitive/sub_tasks/evaluate.py
  673:        answered = answered_model_name(response)
  674:        replayed = getattr(response, "cached", False) is True  # BF-901: a client cache replay
grep -n "Evaluate JSON parse failed, passing by default" src/probos/cognitive/sub_tasks/evaluate.py
  685:                "AD-632e: Evaluate JSON parse failed, passing by default: %s",
grep -n '"rejection_reason": "confabulation_detected"' src/probos/cognitive/sub_tasks/evaluate.py
  542:                    "rejection_reason": "confabulation_detected",
grep -n 'get("recommendation") == "suppress"' src/probos/cognitive/cognitive_agent.py
  5942:            if eval_r.result.get("recommendation") == "suppress":
grep -n "EventType.CONFABULATION_SUPPRESSED" src/probos/cognitive/cognitive_agent.py
  5952:                _rt.emit_event(EventType.CONFABULATION_SUPPRESSED, {
grep -n "trust_no_response_weight\|trust_reward_weight\|trust_duty_bonus" src/probos/config.py
  3214:    trust_reward_weight: float = 0.1
  3215:    trust_no_response_weight: float = 0.0
  3216:    trust_duty_bonus: float = 0.1
grep -n 'intent_type="proactive_think"' src/probos/proactive.py
  1603:                        intent_type="proactive_think",
grep -n 'intent_type="confabulation_suppressed"' src/probos/cognitive/counselor.py
  1748:                    intent_type="confabulation_suppressed",
grep -n "eval_result" src/probos/cognitive/sub_tasks/reflect.py
  168:    eval_result = _get_evaluate_result(prior_results)
grep -n "class SubTaskConfig\|nats_payload_max_bytes" src/probos/config_models/knowledge.py
  13:class SubTaskConfig(BaseModel):
  23:    nats_payload_max_bytes: int = 16384
grep -n "'SubTaskConfig'" tests/test_ad1270e2f_knowledge_models.py
  293:    'SubTaskConfig': {   'enabled': True,
grep -n "evaluate_handler = EvaluateHandler(" src/probos/startup/finalize.py
  5749:        evaluate_handler = EvaluateHandler(
grep -n "sub_task_config = config.sub_task" src/probos/startup/finalize.py
  5713:        sub_task_config = config.sub_task
grep -n "def data_dir" src/probos/runtime.py
  2170:    def data_dir(self) -> Path:
grep -n "cache_key = self._cache_key\|cached=True" src/probos/cognitive/llm_client.py
  1997:            cache_key = self._cache_key(tier, request.prompt, request.system_prompt)
  2008:                    cached=True,
grep -n "class OpenAICompatibleClient\|async def close" src/probos/cognitive/llm_client.py
  261:    async def close(self) -> None:
  265:class OpenAICompatibleClient(BaseLLMClient):
grep -n "OpenAICompatibleClient(config=config.cognitive)" scripts/diagnose_llm.py
  19:    client = OpenAICompatibleClient(config=config.cognitive)
grep -n "llm_model_standard" src/probos/config.py
  323:    llm_model_standard: str = "claude-sonnet-4-6"
grep -n "LOW = " src/probos/types.py
  150:    LOW = "low"
grep -n "_LLM_HANDLERS" tests/test_bf688_chain_priority_inheritance.py
  51:_LLM_HANDLERS = ("analyze.py", "compose.py", "evaluate.py", "reflect.py")
```

## Absence Verified (2026-10-22)

```
CLAIM: nothing measures repeatability or consistency of ProbOS's own LLM judges
RUN:   rg -n -i "(repeatab|test-retest|inter-rater|self-consisten|judge.{0,20}(agreement|consisten|calibrat))" src/probos
FOUND: config_models/agentic.py:1555,1578 and cognitive/confab_probe.py:5 (AD-1121, self-consistency of AGENT claims);
       cognitive/repair_candidate.py:193 (unrelated)
HOLDS: yes. Closest prior art: AD-1326 swap check (procedure_judge.py:18-22) controls position bias, not
       repeatability; #1123 names judge noise but has not measured it.

CLAIM: no natural repeated EVALUATE reading exists in live data
RUN:   cognitive_journal.db: select count(*), sum(prompt_hash!='') from journal where dag_node_id like '%evaluate%'
FOUND: 3505, 0  (journal-wide: 55 repeated prompt_hash groups, none on chain steps)
HOLDS: yes

CLAIM: the EVALUATE score has no programmatic consumer
RUN:   rg -n '\.result\.get\("score"|result\["score"\]|eval\w*\.get\("score"|\["criteria"\]|\.get\("criteria"' src/probos
FOUND: only evaluate.py:707,716,733,739 (its own construction and log) plus unrelated behavioral_metrics/crew_verdict/
       crew_orchestrator/introspective_telemetry hits; reflect.py:171-174 embeds the whole verdict as prompt text
HOLDS: yes (it reaches REFLECT only as text)

CLAIM: AD-522's SPC store is fed by nothing
RUN:   rg -n "record_observation\(" src/probos
FOUND: spc/store.py:38 and spc/calibration_profile.py:29 (definitions); other hits are working memory / evidence collector
HOLDS: yes
```

## Prior Art and Blind Spots

**Internal.**
- AD-1121 `confab_probe.py`: SelfCheckGPT-style self-consistency on agent claims. Adapted: the same "re-ask and compare" idea, pointed at the judge instead of the crew member.
- AD-1326 `procedure_judge.py:18-22`: two-order swap check (MT-Bench). Absorbed as precedent; S1 does not change it. A later slice can measure that judge with this harness.
- AD-522 SPC (`cognitive/spc/`): built and wired, with no caller of `record_observation`. Considered and deferred: S1 supplies the gauge study SPC presupposes and does not feed SPC.
- #1123 (AD-1186): this report is an input to its statistical policy. S1 does not set that policy.
- `docs/development/nooplex-readiness.md:149` (inter-rater reliability for human panels): consistent with this design, nothing to reuse.

**External** (date used for the review rules: 2026-10-22; no `reference-projects.md` row is overdue and relevant).
- Klishevich et al., *Measuring Determinism in LLMs for Software Code Review* ([arXiv 2502.20747](https://arxiv.org/abs/2502.20747)): Claude 3.5 Sonnet among four models at temperature 0, 70 inputs x 5 identical repeats, still varied. Adopted: the 20 x 5 default and the "temperature 0 is not repeatability" premise.
- Lau, *Same Input, Different Scores* ([arXiv 2603.04417](https://arxiv.org/abs/2603.04417)): judge scores unstable at temperature 0, and lower temperature had "limited or inconsistent effects for Anthropic models". Adopted: measure, do not assume.
- *The Coin Flip Judge?* ([arXiv 2606.13685](https://arxiv.org/pdf/2606.13685)): flip rates fell 43-79% from T=1 to T=0, not to zero. The authors recommend multi-trial voting. Considered, deferred: voting multiplies EVALUATE cost; decide after the baseline.
- ICC-based judge reliability ([arXiv 2512.06710](https://arxiv.org/abs/2512.06710v1); [arXiv 2308.02575](https://arxiv.org/pdf/2308.02575)): the same variance decomposition under another name. Rejected as the primary metric: AIAG %GRR and ndc carry decision thresholds, and the decision variable is categorical, where kappa applies.

**Blind spots.**
1. **Range restriction.** Live verdicts are 50% approve. An unstratified sample makes kappa undefined or low for the wrong reason, so `select_parts` stratifies.
2. **Cache masquerade.** A client cache replay would read as perfect repeatability. Such replays are excluded.
3. **Prompt drift.** Captured prompts embed recall and standing orders as they were at capture. The part is the exact request, so drift does not contaminate repeatability, but a baseline ages. Rerun it after prompt changes.
4. **Endpoint opacity.** Whether the Copilot proxy honours `temperature` is unverified. The study measures the path as it is, which is the point.
5. **Privacy.** The capture holds crew prompt text (including DM content), so it is off by default, stored under the data dir and capped.
6. **Repeatability is not validity.** A gauge can agree with itself and still be wrong. Bias against human or ground-truth labels is out of scope for S1. Note it as the follow-on question once repeatability is known.

## BF candidates found while drafting (not drafted; for the orchestrator to file)

1. **The Counselor never receives `CONFABULATION_SUPPRESSED` in the live vessel.** The live logs hold 1,258 `BF-206: Chain output suppressed` lines (949 `quality_gate`, 309 `confabulation_detected`) and **zero** of the Counselor handler's first log line, `BF-206: Confabulation suppressed for` (`counselor.py:1720-1723`), although Counselor INFO lines appear in the same files. The root cause is unconfirmed. Candidate: the emit is guarded by `_rt = getattr(self, '_runtime', None)` (`cognitive_agent.py:5949-5950`). `tests/test_bf206_confab_feedback.py` exists, so this looks like a half-chain.
2. **(Sequencing — important.)** A fix for 1 must not simply re-enable the chain. The LLM `quality_gate` suppressions (75% of all suppressions) arrive as `CONFABULATION_SUPPRESSED`. The Counselor then tells the agent its post "contained details that couldn't be verified" and applies a weight-0.5 trust penalty (`counselor.py:1742-1775`). That is a category error, a quality judgment from an unqualified gauge billed as confabulation. Recommend that the BF restrict the penalty to the deterministic `confabulation_detected` reason (`evaluate.py:519-542`) until AD-1350's baseline exists.
3. **`CONDUCT_VIOLATION` is subscribed (`counselor.py:709,1060`) but never emitted anywhere in `src/`.** The trust penalty at `counselor.py:1461` cannot fire.
4. **AD-522 SPC is built, wired (`finalize.py:3468-3481`) and fed by nothing** (see Absence Verified).
