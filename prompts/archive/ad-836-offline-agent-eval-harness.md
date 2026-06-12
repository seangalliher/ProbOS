# AD-836 — Offline Agent-Behavior Evaluation Harness (ProbOS-Bench v1)

**Status:** Ready
**Dependencies:** AD-716 (micro-LoCoMo benchmark scaffold), AD-545 (`AgenticLoop`), decomposer eval fixtures
**Estimated tests:** 5 pytest (harness self-tests) + 1 opt-in benchmark runner

## Problem

The VS Code "Coding Harness" blog (2026-05-15) attributes the harness's reliability to a
**rigorous offline evaluation loop** (their VSC-Bench): every harness change is scored
against a fixed task set measuring solution correctness, agent effort, and token
efficiency *before* it ships. ProbOS has no equivalent gate. Today a change to
[`AgenticLoop`](../src/probos/cognitive/swe_harness/agentic_loop.py) or
[`decomposer.py`](../src/probos/cognitive/decomposer.py) is validated only by unit tests
that assert structure, never by an aggregate behavioral score against a held task set.

We DO have the raw materials, unused as a gated harness:

- [`tests/benchmarks/test_locomo_episodic.py`](../tests/benchmarks/test_locomo_episodic.py)
  — the opt-in (`PROBOS_BENCHMARK_LOCOMO=1`) JSON-scoreline pattern to copy.
- [`tests/fixtures/eval/decomposer_cases.json`](../tests/fixtures/eval/decomposer_cases.json)
  — hand-authored cases with `input`, `expected_intents`, `min_intents`, `criteria`.
- [`tests/fixtures/eval/code_review_cases.json`](../tests/fixtures/eval/code_review_cases.json).

There is no runner that loads these, exercises the decomposer/loop, and emits an
aggregate scorecard.

## Solution

Add an **opt-in offline behavioral benchmark runner** ("ProbOS-Bench v1") that scores the
decomposer against `decomposer_cases.json` and emits a single JSON scoreline, mirroring
the AD-716 LoCoMo pattern. v1 deliberately scopes to the **decomposer** (deterministic to
score: intent-set match) and provides the extension seam for a full `AgenticLoop`
trajectory scorer in **AD-836b**.

Metrics (v1):
- **resolution_rate** — fraction of cases whose produced intents satisfy the case
  expectation (exact `expected_intents` match where given; `len(intents) >= min_intents`
  where `min_intents` given; conversational cases where `expected_intents == []`).
- **intent_precision** — produced intents that appear in the expected set / produced.
- **mean_intents** — agent-effort proxy (avg intents per task).
- **total_tokens** — token-efficiency proxy (summed from decomposer LLM usage when
  available; `0` when the mock client reports none).

Output: one `PROBOS_BENCH {json}` line, directional not publishable (same disclaimer as
LoCoMo).

### Section 1 — Scoring module

New file: `tests/benchmarks/probos_bench.py`

Pure functions, no I/O at import:
- `load_cases(path: Path) -> list[dict]`
- `score_case(case: dict, produced_intents: list[dict]) -> dict` — returns
  `{resolved: bool, precision: float, n_intents: int}` honoring the three case shapes
  (`expected_intents`, `min_intents`, conversational `[]`).
- `aggregate(results: list[dict], total_tokens: int) -> dict` — returns the v1 metric
  dict above.

Full type annotations on all public functions. Boundary tests required (happy/empty/None).

### Section 2 — Opt-in runner test

New file: `tests/benchmarks/test_probos_bench_decomposer.py`

- `pytest.mark.skipif(os.environ.get("PROBOS_BENCHMARK") != "1", ...)` — copy the AD-716
  opt-in guard exactly.
- Builds a real `Decomposer` with a deterministic/mock LLM client (reuse whatever the
  existing decomposer tests use — do NOT call a live model), runs every case through
  `decompose(...)`, scores via `probos_bench.score_case`, prints the `PROBOS_BENCH {json}`
  line, and asserts the scoreline is well-formed (so CI exercises the path even though the
  benchmark body is opt-in).

### Section 3 — Self-tests for the scorer (always-on)

New file: `tests/test_ad836_probos_bench.py` (NOT under `benchmarks/`, so it runs in the
normal gate)

Unit tests for `probos_bench.py` pure functions — these are the always-green guardrails:

1. `score_case` exact-match happy path → `resolved=True, precision=1.0`.
2. `score_case` `min_intents` satisfied / unsatisfied.
3. `score_case` conversational (`expected_intents == []`) with empty vs non-empty produced.
4. `score_case` empty produced intents (edge).
5. `aggregate` over a mixed result list → correct `resolution_rate`, `mean_intents`.

Run: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad836_probos_bench.py -v -n 0`
Opt-in run: `PROBOS_BENCHMARK=1 pytest tests/benchmarks/test_probos_bench_decomposer.py -s -n 0`

## What This Does NOT Change

- No change to the decomposer, `AgenticLoop`, or any production code path.
- No live-model calls — the runner uses the existing mock/deterministic LLM client.
- No full agent-trajectory (tool-call) scoring — deferred to AD-836b (seam: a
  `score_trajectory(AgenticResult)` function mirroring `score_case`).
- No CI wiring / merge-gate enforcement yet — the harness exists and is callable; making it
  a required pre-merge gate is a follow-on (AD-836c).
- No new dependencies.

## Tracking

- `PROGRESS.md` — add AD-836 CLOSED entry.
- `decisions-era-5-unification.md` — append AD-836: opt-in offline behavioral benchmark
  (ProbOS-Bench v1, decomposer scope). VSC-Bench analog motivated by the VS Code harness
  blog. Seams: AD-836b (trajectory scoring), AD-836c (pre-merge gate).
- `docs/research/` — optional one-paragraph note linking the benchmark to the harness-eval
  rationale (mirror `locomo-benchmark-absorption.md` style).

## Acceptance Criteria

1. `tests/benchmarks/probos_bench.py` exposes `load_cases` / `score_case` / `aggregate`
   with full type annotations.
2. `PROBOS_BENCHMARK=1 pytest tests/benchmarks/test_probos_bench_decomposer.py -s` prints a
   well-formed `PROBOS_BENCH {json}` line and passes; default (no env var) skips.
3. `tests/test_ad836_probos_bench.py` passes (5 tests) in the normal gate.
4. Zero production-code changes; no live-model calls.
5. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-31)

```
tests/benchmarks/test_locomo_episodic.py:26   pytest.mark.skipif(env != "1") opt-in pattern to copy
tests/benchmarks/test_locomo_episodic.py:1    "prints a JSON score line. Skipped by default" precedent
tests/fixtures/eval/decomposer_cases.json:1   cases: id/input/expected_intents/min_intents/criteria
tests/fixtures/eval/code_review_cases.json    second fixture set (out of v1 scope, available for AD-836b)
src/probos/cognitive/decomposer.py            Decomposer.decompose(...) -> TaskDAG (target under test)
src/probos/cognitive/swe_harness/agentic_loop.py  AgenticResult (deferred trajectory-scoring target, AD-836b)
```
