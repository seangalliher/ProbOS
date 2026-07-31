# AD-1143 — With/without-Σ ablation harness (Nooplex §8.3)

**Issue: #1064 · parent epic #1057 · epic DD-7 ordering constraint applies.**
**Repo: OSS (`d:\ProbOS`). AD ceiling: highest AD in the trackers is AD-1151; AD-1138–1150 are assigned via #1063–#1075. This AD = **AD-1143** (#1064). Highest BF = BF-677. No new BF.**

Build the Nooplex §8.3 shared-memory ablation as an opt-in, structurally-excluded test harness. **Tests and fixtures only — zero production change.**

---

## ⚠️ READ THIS FIRST — the ordering constraint that makes this AD urgent

**Today's isolated-children behaviour IS the §8.3 control arm, and AD-1141 destroys it permanently.**

Crew children receive exactly one thing — the task text:

```python
# src/probos/cognitive/crew_executor.py:890
task_text = active_child.description or active_child.title or ""
outcome = await self._executor.run(
    agent_id=agent.id,
    instructions=str(getattr(agent, "instructions", "") or ""),
    task_text=task_text,
    ...
    extra_context={
        "_crew_session_id": parent_id,
        "_crew_work_item_id": child_id,
    },
)
```

`extra_context` carries **two ID strings and nothing else**. No sibling output, no room transcript, no prior-session memory. Children run concurrently under `sem = asyncio.Semaphore(self._max_parallel)` (`crew_executor.py:482`) and their results are appended to the room but never read back by a sibling. That is *precisely* §8.3's "communicate only through direct message-passing" control condition — and it exists in the shipped default **right now, for free**.

AD-1141 wires Σ into that loop. The moment it merges, the control arm cannot be reconstructed: it would require reverting a shipped feature to measure it.

> **Therefore: the Σ-off baseline artifact must be captured and committed before AD-1141 merges.** Epic #1057 DD-7 states this verbatim: *"Today's isolated-children behaviour is AD-1143's control arm; once AD-1141 merges it is unrecoverable."*
>
> If you reach the end of this build and the baseline artifact has **not** been generated and committed, **the AD is not done** — say so and stop, do not mark it complete.

---

## Why / context

There is no way to tell whether any of the Σ work improved crew outcomes. Σ shipped this session and is reachable but unmeasured:

| AD | What shipped | Flag | Default |
|---|---|---|---|
| AD-1138 | Semantic index over Ship's Records | `records.semantic_index_enabled` (`config.py:3400`) | `False` |
| AD-1139 | Governed `oracle_query` tool | `agentic_tools.oracle_query_enabled` (`config.py:6057`) | `False` |
| BF-675 | Tier 5 sovereign bypass closed | — | — |
| AD-1140 | `publish_finding` | **not built yet** | — |
| AD-1141 | Σ into the crew loop | **not built yet** | — |

Two reusable patterns exist and must be reused, not reinvented:

- **LLM-as-judge rubric scoring** — `src/probos/cognitive/communication_benchmarks.py:85-140`: a `_SCORING_PROMPT` template with a `{rubric}` slot, `llm_client.complete(LLMRequest(prompt=..., tier=..., max_tokens=..., temperature=0.0))`, `extract_json(content)` from `probos.utils.json_extract`, and a **0-score honest-degrade on any judge failure**. Tests in `tests/test_ad642_communication_benchmarks.py`.
- **Opt-in benchmark** — `tests/benchmarks/probos_bench.py` (pure scoring functions, no I/O at import, no production imports at module scope) with the runner `tests/benchmarks/test_probos_bench_decomposer.py` gated on `PROBOS_BENCHMARK=1`. Same shape in `tests/research/test_compression_ratio_harness.py` (`PROBOS_RESEARCH_BENCH=1`) and `tests/benchmarks/test_locomo_episodic.py` (`PROBOS_BENCHMARK_LOCOMO=1`).

Read all three before writing anything.

### Honest framing — state this in the module docstring, verbatim

> This harness produces a **directional signal, not a publishable effect size.** The shipped goal set is 12 items, not the ≥100 that Nooplex §8.5 asks for, because each item costs a full live crew run. Cohen's *d* and its confidence interval are reported so the direction and rough magnitude of the Σ effect are visible; the harness never claims statistical significance and never prints the word "significant". §8.5 compliance is **not** claimed.

The same paragraph goes in the results artifact and in the DECISIONS.md entry. `probos_bench.py:11` already sets this precedent ("Directional, not publishable — same disclaimer as the AD-716 micro-LoCoMo harness"). Follow it.

---

## Pinned design decisions

### DD-1 — `tests/ablation/`, excluded from collection by a conditional `collect_ignore_glob` — not by `skipif`

New package `tests/ablation/` with `__init__.py`, mirroring `tests/benchmarks/` and `tests/research/`.

Gating is by a **directory-local `tests/ablation/conftest.py`**:

```python
import os

_MODE = os.environ.get("PROBOS_ABLATION", "")
collect_ignore_glob = [] if _MODE in {"structural", "live"} else ["test_*.py"]
```

`tests/conftest.py:18` already establishes `collect_ignore_glob` as the house mechanism (`["**/_blender/**"]`, for a module that imports `bpy`). This is the same tool, applied conditionally.

**Why not `pytestmark = pytest.mark.skipif(...)` like the three existing benches.** `skipif` still *imports* the module during collection. This runner imports `CrewOrchestrator`, `CrewExecutor`, `WorkItemAgenticExecutor` and the store layer; a heavier default-gate import for a module that never runs is a real (if small) cost, and — more importantly — an import-time failure in the harness would then break the default gate for everyone. `collect_ignore_glob` means the file is never opened. That is the structural, not conventional, exclusion the acceptance asks for.

**The cost, stated honestly:** a file that is never collected is a file whose syntax rot is invisible to CI. Pay it down explicitly — the default-gate guard test (below) `compile()`s every `tests/ablation/*.py` source (AST-level, **no import, no execution**), so a syntax error is caught without running anything. That is the whole mitigation; it does not catch import errors or type errors, and the prompt does not pretend otherwise.

**Guard test lives in the DEFAULT gate** — `tests/test_ad1143_ablation_gating.py`:

1. **Structural:** import `tests/ablation/conftest.py` by path with `PROBOS_ABLATION` unset ⇒ `collect_ignore_glob == ["test_*.py"]`; with it set to `structural` and to `live` ⇒ `[]`; with a junk value (`"1"`, `"true"`, `""`) ⇒ ignored (fail closed — only the two named modes open collection).
2. **Behavioural, ONE subprocess:** `subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-o", "addopts=", "-p", "no:cacheprovider", "tests/ablation"], env=<os.environ minus PROBOS_ABLATION>)` ⇒ exit code **5** (`EXIT_NOTESTSCOLLECTED`) and zero collected items. `-o addopts=` is mandatory — `pyproject.toml:166` sets `addopts = "-n 16 --dist=loadfile"` and inheriting it would spawn 16 xdist workers inside a unit test.
3. **Syntax:** every `tests/ablation/**/*.py` is `compile(source, path, "exec")`-clean.

Three tests, ~4s total, in the default gate. That is the price of the exclusion and it is worth it.

### DD-2 — 12 goals, committed, each required to declare *why* it discriminates on shared memory

Fixture: `tests/ablation/data/sigma_goals_v1.json`. Schema per entry:

```json
{
  "id": "g01",
  "goal": "<the parent task text handed to the crew>",
  "children_hint": 3,
  "discriminator": "cross_child",
  "discriminator_note": "Child B must use the schema child A derives; neither can produce it alone.",
  "solo_solvable": false,
  "seed_records": [ { "title": "...", "body": "..." } ]
}
```

**`discriminator` is a closed vocabulary of exactly three values**, and every goal must declare one:

| Value | The goal fails without Σ because… |
|---|---|
| `cross_child` | one child's output is a required input to a sibling running in the same wave |
| `cross_session` | the answer depends on a fact written to Ship's Records in an earlier session (seeded via `seed_records`) |
| `redundancy` | two children would otherwise duplicate the same expensive derivation; Σ lets the second reuse the first |

**This is the fairness criterion and it is the whole point of the AD.** A goal that a single competent agent could solve alone measures general capability, not shared memory — it would dilute the effect toward zero and make the harness measure the wrong thing. A structural test asserts: every entry has a `discriminator` in the vocabulary, `solo_solvable is False`, a non-empty `discriminator_note`, and that `cross_session` entries carry non-empty `seed_records` (otherwise there is nothing for Σ to retrieve and the goal silently degrades to a capability test).

**Why 12 and not 100 — say this plainly in the fixture header and the artifact.** One goal = one full crew run: planner decomposition, `children_hint` children each running a full `AgenticLoop` (multi-turn, tool calls), verification, synthesis. Empirically that is ~15–40 live LLM calls per run. At 2 arms × 3 trials (DD-5) that is **6 runs ≈ 90–240 calls per goal**. Twelve goals ≈ **1.1k–2.9k live calls**. One hundred goals would be **9k–24k calls** — not affordable, and not made affordable by any design choice available here. §8.5's ≥100 is therefore **not met and not claimed**.

Fixture is versioned by filename (`_v1`) and by a `goalset_version` key inside it. A new goal set is a new file and a new version — **never** an edit in place, because an edited fixture silently invalidates every committed baseline.

### DD-3 — Judge on `deep`, blind to arm, rubric versioned by content hash

Rubric: `tests/ablation/data/rubric_v1.md`, four dimensions drawn from Nooplex §8.1, each scored `0.0–1.0`:

| Dimension | §8.1 metric | What it asks the judge |
|---|---|---|
| `coordination_quality` | multi-agent reasoning | Do the parts fit together, or are they stapled? Is there evidence one part used another? |
| `reasoning_depth` | reasoning depth | Does the artifact reason from the material, or restate the prompt? |
| `knowledge_retention` | memory persistence | Does it use facts it was not handed in the goal text? |
| `artifact_correctness` | task success | Does it actually answer the goal? |

Composite is the **unweighted mean** of the four. Weighting is a research decision this AD is not equipped to make; equal weights are the honest default and are stated as such. (Contrast `_DIMENSION_WEIGHTS` in `communication_benchmarks.py:35`, which is weighted — do **not** copy those weights, they are for a different construct.)

`RUBRIC_VERSION = "sigma-ablation-v1"` as a module constant, **plus** a `rubric_sha256` computed from the file bytes at run time and recorded in the artifact. The string version is human-readable; the hash is what the comparison guard actually enforces (DD-6), because a string version can be forgotten during an edit and a hash cannot.

**Judge tier: `deep`.** The `deep` tier exists (`llm_client.py:41`, `_LLM_TIERS`). Crew children run on whatever their agent config specifies — typically `standard`/`fast`. Judging on a tier at or above the system under test is the minimum defensible arrangement.

**The validity threat, named and not papered over.** Every tier routes through the same Copilot proxy, so judge and SUT are the same model family. That is a real threat to validity and **it cannot be eliminated at ProbOS's budget** — an independent judge means a second vendor, a second key, and a second cost centre. The three mitigations that *are* affordable, all mandatory:

1. **Blind judging.** The judge prompt never states which arm produced an artifact and never mentions Σ, shared memory, or the ablation. Both arms' artifacts for a goal are presented in a **per-goal randomised order** driven by a fixed seed, and the arm↔position mapping is recorded in the artifact so the unblinding is auditable after the fact.
2. `temperature=0.0`, `max_tokens` fixed.
3. Judge **model id and tier recorded on every result row**, not once per run — a mid-run tier fallback (`_TIER_ORDER`, `llm_client.py:47`) would otherwise be invisible.

State in the artifact: *"Judge and system under test share a model family. A human-evaluation panel (§8.4) is out of scope for this AD."*

Judge failure follows the AD-642 contract exactly: any exception, unparseable JSON, or out-of-range score ⇒ **the trial is recorded as `judge_failed: true` and excluded from the aggregate**, and the artifact records the exclusion count. Do **not** copy AD-642's "return 0-scores on failure" — a zero here is indistinguishable from a genuinely terrible artifact and would silently bias the arm whose judge call happened to fail.

### DD-4 — Paired design, Cohen's *d_z*, bootstrap CI, and an explicit refusal to claim significance

Both arms run the **same goal**, so the design is **paired**. Use it — a paired design is materially more powerful than two independent samples at this n, and it is free.

`tests/ablation/sigma_stats.py` — pure functions, no I/O, no production imports, **no scipy** (mirroring `probos_bench.py`'s style and dependency posture):

- `mean(xs)`, `stdev(xs)` (sample, n−1)
- `cohens_dz(pairs)` — mean of within-pair differences ÷ SD of those differences
- `bootstrap_ci(pairs, *, iterations=10_000, seed=1143, alpha=0.05)` — resample **pairs**, not individual observations; fixed seed so the CI is reproducible
- `interpret(d, ci)` → one of `"favours_sigma"` / `"favours_control"` / `"inconclusive"`, where `"inconclusive"` is returned whenever the CI spans 0

**The power statement, and it goes in the artifact.** A paired design needs ~15 pairs to detect *d_z* = 0.8 at α = .05 with 80% power. **n = 12 gives roughly 70%.** So:

- The harness reports *d_z*, the 95% CI, and the per-arm means.
- The harness **never** prints "significant", never prints a p-value, and never reports a hypothesis-test verdict. Assert this in a test: the rendered report string contains none of `"significant"`, `"p="`, `"p <"`, `"p-value"`.
- The headline line is `direction=<favours_sigma|favours_control|inconclusive> d_z=<x.xx> ci95=[<lo>, <hi>] n_pairs=<n> power_note="n=12 → ~70% power for d_z=0.8; directional only"`.

### DD-5 — Three trials per arm, a variance floor that can veto the run, and offline safety

**LLM nondeterminism is not fixable here.** Crew agents' own calls are not all temperature-pinned and the harness must not reach into production to pin them (that would be a `src/` change). So measure the noise instead of pretending it is absent:

- **3 trials per goal per arm.** Per-goal score is the mean of its trials.
- Compute `between_trial_sd` (pooled across goals and arms) and `between_arm_delta` (|mean_on − mean_off|).
- If `between_trial_sd >= between_arm_delta`, the report's first line is **`VARIANCE_DOMINATES — this run is not interpretable`**, and `interpret()` is forced to `"inconclusive"` regardless of *d_z*. A run whose noise exceeds its signal must not be readable as a result.

**Offline safety.** `PROBOS_EMBEDDINGS=local` (BF-657) must be set for both modes; `live` mode **skips with a named reason** if it is not, rather than silently reaching for a remote embedding model.

**And the caveat that follows from it, which must be in the artifact.** Under `PROBOS_EMBEDDINGS=local` the embedding function is **lexical**, not semantic — `tests/test_ad1138_records_semantic_index.py:730-732` skips a synonym-matching test for exactly this reason. That makes AD-1138's semantic index measurably *weaker* in the Σ-ON arm than it would be with real embeddings. **This biases against Σ** — i.e. it is the conservative direction, and a positive result under local embeddings is a floor rather than a ceiling. Say that; do not let a reader infer the opposite.

**Config pinning.** `AgenticLoopConfig` (`config.py:4369`) now carries AD-1146/1147/1148/1151 fields — `structured_tool_messages`, `tool_result_max_chars`, `tool_result_head_chars`, `tool_result_tail_chars`, `parallel_tool_calls_enabled`, `max_parallel_tool_calls`, `tool_trace_output_max_chars`, `tool_trace_max_bytes`. The harness **pins every one of them explicitly** (do not inherit defaults) and records `config_fingerprint = sha256(json.dumps(pinned, sort_keys=True))` in the artifact. An unrelated default change then shows up as a fingerprint mismatch at comparison time (DD-6) instead of silently moving the numbers.

### DD-6 — Σ flag set lives in exactly ONE module, validated against a real `SystemConfig`

`tests/ablation/sigma_flags.py`:

```python
SIGMA_OFF: dict[str, Any] = {
    "records.semantic_index_enabled": False,
    "agentic_tools.oracle_query_enabled": False,
}
SIGMA_ON: dict[str, Any] = {
    "records.semantic_index_enabled": True,
    "agentic_tools.oracle_query_enabled": True,
}
```

Dotted paths against `SystemConfig`. Both verified at HEAD: `config.py:6428` `records: RecordsConfig`, `config.py:3400` `semantic_index_enabled: bool = False`; `config.py:6509` `agentic_tools: AgenticToolsConfig`, `config.py:6057` `oracle_query_enabled: bool = False  # AD-1139`.

**AD-1140 and AD-1141 extend this module and nothing else.** The runner reads the dicts; it never names a flag inline. That is the single-source-of-truth requirement.

Two guards in `tests/ablation/` (structural mode, no LLM):

1. `set(SIGMA_ON) == set(SIGMA_OFF)` — the arms must differ in *values*, never in *which knobs exist*. A key present in one dict only is a silent asymmetry.
2. **Every dotted path resolves against a live `SystemConfig()`** by attribute walk, and the resolved attribute is a `bool`. If AD-1141 renames a field, this goes red instead of the flag becoming a no-op that quietly turns the treatment arm into a second control arm. This guard is the reason the module exists.

### DD-7 — Baseline artifact: content-hashed, and a mismatch is a hard error

Committed to `tests/ablation/baselines/`, filename `sigma_off_<goalset_version>_<rubric_version>_<YYYYMMDD>.json`.

```json
{
  "arm": "sigma_off",
  "probos_commit": "<git rev-parse HEAD>",
  "captured_utc": "2026-07-25T00:00:00Z",
  "goalset_version": "v1",
  "goalset_sha256": "<64 hex>",
  "rubric_version": "sigma-ablation-v1",
  "rubric_sha256": "<64 hex>",
  "config_fingerprint": "<64 hex>",
  "flags": { "records.semantic_index_enabled": false, "...": false },
  "judge": { "model": "<id>", "tier": "deep", "temperature": 0.0 },
  "embeddings": "local",
  "trials_per_goal": 3,
  "results": [
    { "goal_id": "g01", "trial": 0, "scores": { "coordination_quality": 0.0, "...": 0.0 },
      "composite": 0.0, "judge_model": "<id>", "judge_tier": "deep",
      "judge_failed": false, "blind_position": 1 }
  ],
  "aggregate": { "mean_composite": 0.0, "between_trial_sd": 0.0, "n_goals": 12, "n_judge_failures": 0 },
  "disclaimer": "Directional signal, not a publishable effect size. ..."
}
```

**Comparison is gated, not best-effort.** `compare_to_baseline(baseline, current)` raises `ValueError` naming the **specific** diverging field when any of `goalset_sha256`, `rubric_sha256`, `config_fingerprint` differ. Never compare across a changed goal set or rubric and never degrade to a warning — a quietly-invalid comparison is worse than no comparison. `probos_commit` and `judge.model` differences are **recorded and reported, not fatal** (the whole point is to compare across commits).

### DD-8 — Two modes; `structural` burns zero LLM calls

`PROBOS_ABLATION` takes exactly two values:

| Value | LLM | Goal set | Purpose |
|---|---|---|---|
| `structural` | **none** — a deterministic scripted client for both SUT and judge | `data/sigma_goals_smoke.json`, 2 goals, 1 trial | **This is how the Builder validates the harness.** Proves: both arms construct, the flags actually differ at runtime, the judge prompt renders and parses, stats compute, the artifact writes and round-trips, and the DD-7 mismatch guard fires. |
| `live` | real client via the Copilot proxy | `data/sigma_goals_v1.json`, 3 trials | Produces the committed baseline. |

`structural` must be **fully deterministic and complete in seconds**. Build the scripted client on the `_ScriptedLLM` pattern from `tests/test_ad1125_room_bound_execution.py:509` (`_tool_response(...)` / `_text_response(...)` sequences); the judge half returns a fixed valid JSON score object. Any other value of `PROBOS_ABLATION` — including `1` and `true` — is **not** a valid mode and leaves the directory uncollected (DD-1, fail closed).

**Builder: `structural` mode is your acceptance gate. Do not run `live` unless the Captain explicitly asks** — it costs real money and real time, and DD-2's arithmetic is an estimate, not a measurement.

---

## Build

1. `tests/ablation/__init__.py`, `tests/ablation/conftest.py` (DD-1 conditional glob).
2. `tests/ablation/sigma_flags.py` — `SIGMA_ON` / `SIGMA_OFF` + a dotted-path applier that returns a **new** `SystemConfig` (never mutates a shared one).
3. `tests/ablation/sigma_stats.py` — pure stats (DD-4). No I/O, no production imports, no scipy.
4. `tests/ablation/sigma_judge.py` — rubric loading + hashing, `_SCORING_PROMPT`-style template, blind presentation, `extract_json` parsing, `judge_failed` handling (DD-3). Modelled on `communication_benchmarks.py:85-140`; **copied into tests, not imported from `src/`, and `src/` is not modified.**
5. `tests/ablation/sigma_report.py` — artifact serialise/deserialise, `config_fingerprint`, `compare_to_baseline` (DD-7), and the report renderer with the DD-4 headline and the DD-5 `VARIANCE_DOMINATES` veto.
6. `tests/ablation/data/` — `rubric_v1.md`, `sigma_goals_v1.json` (12), `sigma_goals_smoke.json` (2).
7. `tests/ablation/test_sigma_ablation.py` — the runner. Drives a crew per goal per arm per trial via `CrewOrchestrator.run_crew_task(parent_id)` (`crew_orchestrator.py:1162`) and judges `SynthesisResult.final_output` (`crew_synth.py:90`). Scaffolding pattern: `tests/test_ad1125_room_bound_execution.py:470-520`.
8. `tests/ablation/test_sigma_harness_structural.py` — the structural-mode self-tests (flag guards, fixture-schema guards, stats, judge parsing, artifact round-trip, comparison-guard firing). Runs in `structural` mode only.
9. `tests/test_ad1143_ablation_gating.py` — **the only file in the default gate** (DD-1, 3 tests).
10. `tests/ablation/baselines/sigma_off_v1_sigma-ablation-v1_<date>.json` — **generated by a `live` run and committed. Without this, the AD is not done.**

---

## Acceptance

**Gating (default gate):**

- `PROBOS_ABLATION` unset ⇒ `collect_ignore_glob == ["test_*.py"]`; `structural` / `live` ⇒ `[]`; junk values ⇒ ignored (fail closed).
- Subprocess `pytest --collect-only -o addopts= tests/ablation` with the var unset ⇒ exit code 5, zero items.
- Every `tests/ablation/**/*.py` compiles.

**Flags:**

- `set(SIGMA_ON) == set(SIGMA_OFF)`.
- Every dotted path resolves on a live `SystemConfig()` **and** the target is a `bool`.
- The applier returns a config where the flag differs from the source, and the source object is unchanged.

**Fixture:**

- All 12 goals: `discriminator` ∈ {`cross_child`, `cross_session`, `redundancy`}, `solo_solvable is False`, non-empty `discriminator_note`.
- Every `cross_session` goal has non-empty `seed_records`.
- Goal ids are unique; `goalset_version` present.

**Judge:**

- The rendered judge prompt contains **neither** arm label **nor** any of `"sigma"`, `"shared memory"`, `"ablation"`, `"control"`, `"treatment"` (case-insensitive) — assert on the actual rendered string.
- Malformed JSON, a raising client, and an out-of-range score each ⇒ `judge_failed is True` and exclusion from the aggregate — **not** a 0.0 score.
- `judge_model` and `judge_tier` present on **every** result row.
- `rubric_sha256` matches `hashlib.sha256(rubric_path.read_bytes()).hexdigest()`.

**Stats and report:**

- `cohens_dz` on a hand-computed pair set matches to 1e-9.
- `bootstrap_ci` with a fixed seed is byte-reproducible across two calls.
- A CI spanning 0 ⇒ `"inconclusive"`.
- `between_trial_sd >= between_arm_delta` ⇒ report starts with `VARIANCE_DOMINATES` **and** `interpret()` is forced to `"inconclusive"` even when *d_z* is large.
- The rendered report contains none of `"significant"`, `"p="`, `"p <"`, `"p-value"`.
- The report contains the DD-4 headline fields and the power note.

**Artifact:**

- Round-trips through JSON with every DD-7 key present.
- `compare_to_baseline` raises `ValueError` naming the field on each of three separate mismatches: `goalset_sha256`, `rubric_sha256`, `config_fingerprint`.
- A differing `probos_commit` or `judge.model` does **not** raise and **is** surfaced in the report.
- The disclaimer string is present in the artifact and in the module docstring.

**Structural mode:**

- The whole structural suite runs green with **zero** live LLM calls (assert the scripted client's call count is the only source of completions) and completes in seconds.
- Both arms construct and the runtime-visible flag values actually differ between them — assert on the config the orchestrator received, not on the dict.

**Live mode / baseline:**

- The Σ-off baseline artifact exists under `tests/ablation/baselines/` and is committed.
- Skips with a clear named reason when `PROBOS_EMBEDDINGS != "local"` or no LLM endpoint is reachable.

**Zero production change:**

- `git diff --stat` touches **no** path under `src/probos/**`. Assert it — and see the hard rule below.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Hard rule — `src/probos/**` is out of scope

This AD is tests and fixtures only. **If you conclude the harness cannot be built without a production change, stop and report it as a spec defect. Do not work around it, and do not make the change.**

The most likely trigger, and the honest answer if you hit it: driving a *live* crew end-to-end may need more runtime wiring than `tests/test_ad1125_room_bound_execution.py`'s fake-store scaffolding provides. Building heavier scaffolding **inside `tests/`** is fine and expected. Reaching into `src/` to add a hook, a parameter, or an export is not — surface it instead.

---

## Validation plan — targeted only

**The full suite takes ~21 minutes and must NOT be run.**

- **Default-gate guard (the only new default-gate file):**
  `tests/test_ad1143_ablation_gating.py -q -n 0`
- **Harness self-tests (structural mode, no LLM):**
  `$env:PROBOS_ABLATION="structural"; $env:PROBOS_EMBEDDINGS="local"; pytest tests/ablation/test_sigma_harness_structural.py -q -n 0`
- **Structural end-to-end runner:**
  `$env:PROBOS_ABLATION="structural"; $env:PROBOS_EMBEDDINGS="local"; pytest tests/ablation/test_sigma_ablation.py -q -n 0`
- **Regression guard that the new conftest changed nothing for the existing opt-in benches, ONCE:**
  `tests/benchmarks/ tests/research/ -q -n 0` (all skip; confirm they still skip, and that no ablation test was collected)
- **Adjacent contract guards, ONCE, only if the runner scaffolding touched their helpers:**
  `tests/test_ad1125_room_bound_execution.py tests/test_ad867_crew_orchestrator.py -q -n 0`

`tests/test_ad1138_records_semantic_index.py` and `tests/test_ad642_communication_benchmarks.py` are **read for pattern, not modified and not re-run** — nothing in this AD touches their subjects.

**Live mode is not part of the Builder gate.** Run it only on explicit instruction from the Captain.

---

## Do NOT build here

❌ TC_N computation. ❌ Longitudinal capability-growth curves. ❌ Novel-coordination detection. ❌ Human-evaluation panels (§8.4). ❌ Comparison against external frameworks (§8.7). ❌ **Any** production code change (`src/probos/**`). ❌ Wiring the harness into the default pytest gate. ❌ Modifying `tests/conftest.py` (the new conftest is directory-local). ❌ Changing `tests/benchmarks/` or `tests/research/`. ❌ A scipy/numpy/pandas dependency. ❌ Editing an existing goal-set or rubric file in place (a change is a new version). ❌ AD-1140's `publish_finding` or AD-1141's crew wiring — this AD measures, it does not build Σ. ❌ A new AD or BF number.

---

## Files (verify each at build)

| Path | Status |
|---|---|
| `tests/ablation/__init__.py` | NEW |
| `tests/ablation/conftest.py` | NEW |
| `tests/ablation/sigma_flags.py` | NEW |
| `tests/ablation/sigma_stats.py` | NEW |
| `tests/ablation/sigma_judge.py` | NEW |
| `tests/ablation/sigma_report.py` | NEW |
| `tests/ablation/data/rubric_v1.md` | NEW |
| `tests/ablation/data/sigma_goals_v1.json` | NEW |
| `tests/ablation/data/sigma_goals_smoke.json` | NEW |
| `tests/ablation/test_sigma_ablation.py` | NEW |
| `tests/ablation/test_sigma_harness_structural.py` | NEW |
| `tests/ablation/baselines/sigma_off_*.json` | NEW — generated by a `live` run |
| `tests/test_ad1143_ablation_gating.py` | NEW — the only default-gate file |
| `src/probos/**` | **UNTOUCHED** |

---

## Tracking

`PROGRESS.md` · `docs/development/roadmap.md` · `DECISIONS.md`.

The AD-1143 entry must record, in this order: the DD-7 ordering constraint and the date the baseline was captured; the 12-goal count with the reason §8.5's ≥100 is not met; the shared-model-family judge threat and the blinding mitigation; the local-embeddings conservative bias; and the directional-not-publishable disclaimer **verbatim**.

---

## Done-when

Acceptance green; the default-gate guard green; structural mode green with zero live LLM calls; the existing opt-in benches still skip and no ablation test is collected by default; **the Σ-off baseline artifact captured and committed while `main` still has isolated children**; `git diff --stat` shows no `src/probos/**` path; **verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-07-25, HEAD `b4e4fc93`)

```
src/probos/cognitive/crew_executor.py
   354:         self._max_parallel = max(1, int(max_parallel_subtasks))
   482:         sem = asyncio.Semaphore(self._max_parallel)          # control-arm isolation
   890:         task_text = active_child.description or active_child.title or ""
   891-901:    self._executor.run(..., extra_context={"_crew_session_id": ..., "_crew_work_item_id": ...})
                                                                    # two IDs only — no sibling state

src/probos/cognitive/crew_orchestrator.py
  1162:     async def run_crew_task(self, parent_id: str) -> SynthesisResult:   # harness entry point

src/probos/cognitive/crew_synth.py
    76: class SynthesisResult:
    90:     final_output: str                                        # the judged artifact

src/probos/config.py
  3362: class RecordsConfig(BaseModel):
  3400:     semantic_index_enabled: bool = False                     # AD-1138
  4369: class AgenticLoopConfig(BaseModel):
  4396/4406/4418/4430/4439/4452/4465/4496: structured_tool_messages, tool_result_max_chars,
        tool_result_head_chars, tool_result_tail_chars, parallel_tool_calls_enabled,
        max_parallel_tool_calls, tool_trace_output_max_chars, tool_trace_max_bytes   # pin all 8
  6036: class AgenticToolsConfig(BaseModel):  # AD-1072
  6057:     oracle_query_enabled: bool = False  # AD-1139
  6428:     records: RecordsConfig = RecordsConfig()
  6451:     agentic_loop: AgenticLoopConfig = Field(...)
  6509:     agentic_tools: AgenticToolsConfig = Field(default_factory=AgenticToolsConfig)

src/probos/cognitive/communication_benchmarks.py                    # judge pattern to copy
    26: from probos.types import IntentMessage, LLMRequest
    27: from probos.utils.json_extract import extract_json
    35: _DIMENSION_WEIGHTS = {...}                                   # do NOT reuse these weights
    86: _SCORING_PROMPT = """... ## Rubric\n{rubric} ..."""
   107: async def _score_response(llm_client, scenario, response, rubric)
   126:             tier="fast",                                     # this AD uses "deep"

src/probos/cognitive/llm_client.py
    41: _LLM_TIERS = ("fast","standard","deep","vision","vision_fast","compute_use","image_gen")
    47: _TIER_ORDER = ("fast", "standard", "deep")                   # silent fallback → record tier per row

pyproject.toml
   150: [tool.pytest.ini_options]
   152: testpaths = ["tests"]                                        # tests/ablation IS in scope by default
   166: addopts = "-n 16 --dist=loadfile"                            # subprocess guard must pass -o addopts=

tests/conftest.py
    18: collect_ignore_glob = ["**/_blender/**"]                     # house mechanism for DD-1

tests/benchmarks/probos_bench.py
    11: "Directional, not publishable — same disclaimer as the AD-716 micro-LoCoMo harness."
tests/benchmarks/test_probos_bench_decomposer.py:24-26   PROBOS_BENCHMARK gate (skipif — superseded by DD-1)
tests/benchmarks/test_locomo_episodic.py:26-28           PROBOS_BENCHMARK_LOCOMO gate
tests/research/test_compression_ratio_harness.py:22      PROBOS_RESEARCH_BENCH gate

tests/test_ad1138_records_semantic_index.py
   730-732: skipif PROBOS_EMBEDDINGS=local — "lexical EF; no synonym matching"   # DD-5 bias caveat

tests/test_ad1125_room_bound_execution.py
   470-520: _ScriptedLLM / _runtime / _crew_executor / CrewOrchestrator scaffolding  # DD-8 pattern
   521:     synthesis = await orchestrator.run_crew_task(parent.id)

github issue #1057 (epic) DD-7:
  "Today's isolated-children behaviour is AD-1143's control arm; once AD-1141 merges
   it is unrecoverable."
```

**Builder checks — could not be verified from static reading:**

- **B-1 (highest risk).** Whether a *live* crew run needs runtime wiring beyond the `tests/test_ad1125_room_bound_execution.py` fake-store scaffolding — real `AttachmentStore`, real `WorkItemStore`, real records repo, a booted `ProbOSRuntime`. Heavier scaffolding inside `tests/` is fine; a `src/` change is a spec defect (see the hard rule). Resolve this **first**, before writing the fixture — it determines how the runner is shaped.
- **B-2.** The per-run LLM call count. DD-2's 15–40 is an estimate from the loop structure, not a measurement. Instrument it during the first `live` goal and record the real number in the artifact; if it is materially higher, reduce trials before reducing goals (goals buy statistical power; trials only buy noise reduction).
- **B-3.** Whether `subprocess` + `pytest --collect-only` is stable on Windows inside the default gate. If it is flaky, keep guard tests 1 and 3 and drop test 2 — but say so in the docstring; do not silently weaken the guarantee.
- **B-4.** Whether `run_crew_task` needs `orchestrator_enabled` set (`tests/test_ad867_crew_orchestrator.py:6` notes the gate). Pin it explicitly in the harness config either way rather than inheriting the default.
