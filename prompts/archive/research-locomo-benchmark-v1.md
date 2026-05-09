# RESEARCH — LoCoMo benchmark absorption + harness stub

**Issue:** [#497](https://github.com/seangalliher/ProbOS/issues/497) (also subsumes closed-as-duplicate [#494](https://github.com/seangalliher/ProbOS/issues/494))
**Type:** Research AD (no production code; doc + runnable harness stub)
**Upstream:** https://github.com/NirDiamant/Agent_Memory_Techniques (Apache-2.0, 214★, technique 29 = LoCoMo)
**Depends on:** Episodic memory, Working Memory, Think-in-Memory composite scoring (AD-606), Ebbinghaus decay (AD-538).
**Wave:** 130

## Goal

LoCoMo (Long Conversation Memory) is the de-facto open benchmark for agent memory architectures. Both Mem0 and MemOS quote LoCoMo numbers as their headline metric. ProbOS does NOT have a LoCoMo number today, which makes it impossible to make data-driven memory-architecture decisions ("does the magic-context absorption move the needle? we don't know"). AD-712 produces (a) a research doc that captures the LoCoMo methodology so the team has a shared mental model, and (b) a runnable harness stub at `tests/benchmarks/test_locomo_episodic.py` that — under an explicit env-var opt-in — runs ProbOS's recall pipeline against a small LoCoMo subset and prints a score.

## Architect-fetched upstream summary (2026-05-08)

From `NirDiamant/Agent_Memory_Techniques` `README.md` (https://github.com/NirDiamant/Agent_Memory_Techniques) and the technique-29 notebook at `all_techniques/29_memory_benchmarks/` (Apache-2.0):

- **Repository.** 30 runnable Jupyter notebooks across 6 families (short-term, long-term, cognitive architectures, retrieval, frameworks, evaluation+production). Technique 29 specifically covers LoCoMo and LongMemEval.
- **LoCoMo.** "Long Conversation Memory benchmark." Multi-session conversations between two personas; questions are asked at the end and require recalling facts, preferences, and events from earlier sessions. Each question has a ground-truth answer; scoring is exact-match or LLM-judge graded.
- **LongMemEval.** Companion benchmark — same shape, different scope. Architect groups them under one umbrella for ProbOS purposes.
- **MemOS** (one of the competing systems referenced in the README). Quotes LoCoMo numbers; the benchmark methodology is the same as the LoCoMo notebook's.
- **Methodology** (per the README's Technique 28 ("Memory Evaluation") + Technique 29 alignment): retrieval **precision** (was the right episode recalled?), **recall** (did all relevant episodes surface?), **staleness** (did stale facts override new ones?), **contradiction** (does the system surface contradictions or pick a side?), and end-task **answer correctness**.

The dispatch directs Architect to "pull the MemOS benchmark methodology too." Both MemOS and Mem0 publish the same benchmark *protocol*: feed N sessions, ask M questions, score against ground truth. The implementation differences live in the system under test, not the benchmark. So the absorption study captures **one** methodology and produces **one** harness.

For v1, we do **not** download the full LoCoMo dataset (multi-GB, many sessions). The harness operates on a **micro-LoCoMo**: 3 sessions × 5 questions, hand-authored from the notebook's example excerpts. Future ADs can wire to the real dataset.

## Verified Against Codebase (2026-05-08)

- ✅ `src/probos/cognitive/episodic.py:1648` `async def recall(query, k)` — semantic recall.
- ✅ `src/probos/cognitive/episodic.py:2509` `async def recall_weighted(...)` — composite-scored recall (the most LoCoMo-relevant entry point).
- ✅ `src/probos/cognitive/episodic.py:2747` `async def recall_by_anchor(...)` — structured.
- ✅ `src/probos/types.py:445` `class Episode` — the unit a LoCoMo turn maps to.
- ✅ No `tests/benchmarks/` directory yet — Builder creates it with an `__init__.py`.
- ✅ No existing `locomo`, `longmemeval`, or `benchmark_score` symbols in `src/probos/` (grep-confirmed).

## Scope

- Architect's research summary above is the spec.
- Builder writes the doc and the harness. Builder does **not** download the real LoCoMo dataset; Builder authors the micro-LoCoMo fixture by hand.

## Deliverables

### D1. `docs/research/locomo-benchmark-absorption.md`

Required section structure:

1. **What LoCoMo Measures** — paraphrase the methodology. State the five metrics (precision, recall, staleness, contradiction, answer correctness).
2. **Why It Matters For ProbOS** — name the decisions this score will inform (memory-architecture absorption priority, dream-pipeline tuning, recall threshold tuning).
3. **What ProbOS Has** — citation-backed mapping of LoCoMo metrics to ProbOS recall surfaces. `recall_weighted` → answer correctness, `recall_by_anchor` → precision-on-structured, etc.
4. **Harness Design** — describe the micro-LoCoMo fixture (3 sessions × 5 questions); the scoring function (exact-match per question, summed; ratio = correct / total); skip semantics.
5. **Limitations Of v1** — micro-LoCoMo is hand-authored; no LLM-judge; exact-match only. The number is **directional**, not publishable.
6. **Recommended Follow-ups** — at most 3.

### D2. Harness stub at `tests/benchmarks/test_locomo_episodic.py`

Skipped by default. Opt-in via `PROBOS_BENCHMARK_LOCOMO=1`.

```python
"""AD-712: micro-LoCoMo harness.

Runs ProbOS's recall_weighted against a hand-authored 3-session × 5-question
fixture and prints a JSON score line. Skipped by default; set
PROBOS_BENCHMARK_LOCOMO=1 to opt in.

The score is intentionally directional, not publishable. See
docs/research/locomo-benchmark-absorption.md section 5.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PROBOS_BENCHMARK_LOCOMO") != "1",
    reason="Set PROBOS_BENCHMARK_LOCOMO=1 to run the micro-LoCoMo benchmark",
)

FIXTURE_PATH = Path(__file__).parent / "data" / "micro_locomo.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_micro_locomo_recall_weighted_score(tmp_path: Path) -> None:
    from probos.cognitive.episodic import EpisodicMemory
    from probos.types import Episode

    fixture = _load_fixture()
    # Builder pre-check: confirm the live EpisodicMemory constructor kwarg
    # (likely ``persist_directory``; verify-first against the class
    # signature in src/probos/cognitive/episodic.py before authoring).
    em = EpisodicMemory(persist_directory=str(tmp_path))
    await em.start()
    try:
        # Builder pre-check: validate the fixture before scoring against it.
        # Every question's expected_substring MUST appear verbatim somewhere
        # in its session's turns; otherwise LoCoMo precision is incoherent.
        for q in fixture["questions"]:
            session_id = q.get("session_id", fixture["sessions"][0]["session_id"])
            session = next(s for s in fixture["sessions"] if s["session_id"] == session_id)
            joined = " ".join(t["text"] for t in session["turns"]).lower()
            assert q["expected_substring"].lower() in joined, (
                f"fixture self-consistency failure: {q['question']!r} expects "
                f"{q['expected_substring']!r} which is not present in session {session_id}"
            )
        # Ingest sessions as episodes. ``EpisodicMemory.store`` takes a single
        # ``Episode`` argument (verified at episodic.py:1056). Episode required
        # fields: ``user_input``; all other fields have defaults. The Builder
        # may set additional fields (e.g. ``timestamp``, ``correlation_id``)
        # for richer scoring; the harness only needs ``user_input`` for v1.
        for sess in fixture["sessions"]:
            for turn in sess["turns"]:
                await em.store(Episode(user_input=turn["text"]))
        # Score questions. ``recall_weighted`` returns ``list[RecallScore]``
        # (verified at episodic.py:2509). Each ``RecallScore`` exposes
        # ``.episode: Episode`` directly — no ``getattr`` fallback needed.
        correct = 0
        total = len(fixture["questions"])
        per_q: list[dict] = []
        started = time.perf_counter()
        for q in fixture["questions"]:
            results = await em.recall_weighted(query=q["question"], k=3)
            top_text = " ".join(r.episode.user_input for r in results).lower()
            hit = q["expected_substring"].lower() in top_text
            correct += int(hit)
            per_q.append({"q": q["question"], "hit": hit})
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        ratio = correct / total if total else 0.0
        print(json.dumps({
            "benchmark": "micro_locomo_v1",
            "method": "recall_weighted",
            "correct": correct,
            "total": total,
            "ratio": ratio,
            "elapsed_ms": elapsed_ms,
            "per_question": per_q,
        }))
        assert 0.0 <= ratio <= 1.0
    finally:
        await em.stop()
```

Fixture schema additions:
- Each `question` SHOULD include a `session_id` field naming which session it draws from. If absent, the harness defaults to the first session for fixture-self-consistency checking.

### D3. Fixture at `tests/benchmarks/data/micro_locomo.json`

Hand-authored. Schema:

```json
{
  "sessions": [
    {
      "session_id": "s1",
      "turns": [
        {"role": "user", "text": "I work at Acme as a backend engineer."},
        {"role": "assistant", "text": "Got it — Acme, backend."}
      ]
    }
  ],
  "questions": [
    {"question": "Where does the user work?", "expected_substring": "Acme"}
  ]
}
```

3 sessions × 5+ turns; 5 questions total. Each question's `expected_substring` MUST appear verbatim somewhere in the corresponding session's turns (or LoCoMo precision-checks become incoherent). Builder authors realistic-but-synthetic content (no real conversation data).

## Hard constraints (do NOT do)

- Do **not** download the real LoCoMo dataset — license + size both prohibit casual inclusion.
- Do **not** add an LLM-judge in v1. Exact-substring scoring is the rung-1 metric.
- Do **not** add the harness to the default test gate — opt-in only.
- Do **not** call out to any external network endpoint from the harness.
- Do **not** publish the printed ratio externally — it is directional, not publishable.
- Do **not** assert ProbOS coverage without a grep-verified file:line citation.

## Acceptance criteria

- **Pre-flight (Wave 129 convention #20):** run `git diff --numstat | sort -k2nr | head -5`; >200 deletions on any tracked file = STOP and surface to the Architect before reading source.
- `docs/research/locomo-benchmark-absorption.md` exists with all six required sections.
- `tests/benchmarks/__init__.py` and `tests/benchmarks/test_locomo_episodic.py` exist.
- `tests/benchmarks/data/micro_locomo.json` exists with at least 3 sessions and 5 questions.
- Default `pytest tests/` skips the benchmark (no test failure due to missing env var).
- Opt-in run: `PROBOS_BENCHMARK_LOCOMO=1 d:/ProbOS/.venv/Scripts/pytest.exe tests/benchmarks/ -v -n 0` runs the harness, prints the JSON line, and asserts the ratio is in `[0.0, 1.0]`.
- Full gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile` — benchmark skipped, no slowdown.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Forward markers

- **AD-712-1**: real LoCoMo dataset wired in (subject to license review).
- **AD-712-2**: LLM-judge scoring for fuzzy answer correctness.
- **AD-712-3**: per-metric breakdown (precision / recall / staleness / contradiction / answer-correctness as five separate ratios, not one).

## Revision (2026-05-08)

- **Required #1 (Episode signature):** Replaced the phantom `em.store(user_input=..., dag_summary={}, outcomes=[])` kwargs call with `em.store(Episode(user_input=turn["text"]))`, importing `Episode` from `probos.types`. Verified at `episodic.py:1056` that `store` takes a single `Episode` argument. Documented Episode's required fields (`user_input`; all others default).
- **Recommended R2 (`.episode` attribute):** Dropped the `getattr(r, "episode", r)` fallback; `recall_weighted` returns `list[RecallScore]` (verified at `episodic.py:2509`) which exposes `.episode` directly.
- **Recommended R3 (constructor signature):** Added pre-check note instructing Builder to verify the live `EpisodicMemory.__init__` kwarg name before authoring (same pattern as opencode-magic-context).
- **Recommended R4 (fixture self-consistency):** Added a fixture-self-consistency block at the top of the harness body that asserts every question's `expected_substring` is present verbatim in its declared session. Added optional `session_id` field on the question schema.
- **Cross-cutting:** Added pre-flight working-tree integrity reminder. No config.py edits — no Build Ordering Note required.
