"""AD-716: micro-LoCoMo harness.

Runs ProbOS's ``EpisodicMemory.recall`` against a hand-authored 3-session
× 5-question fixture and prints a JSON score line. Skipped by default;
set ``PROBOS_BENCHMARK_LOCOMO=1`` to opt in.

The score is intentionally directional, not publishable. See
``docs/research/locomo-benchmark-absorption.md`` section 5.

Pre-check: harness uses ``EpisodicMemory.__init__(db_path=...)`` and
``EpisodicMemory.recall(query, k)`` — verified at ``episodic.py:681``
and ``:1648``. ``recall_weighted`` was rejected for v1 because its live
signature requires a positional ``agent_id`` argument that the micro
benchmark has no scaffolding to supply (deferred to AD-716-3).
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
async def test_micro_locomo_recall_score(tmp_path: Path) -> None:
    from probos.cognitive.episodic import EpisodicMemory
    from probos.types import Episode

    fixture = _load_fixture()

    # Pre-check: every question's expected_substring MUST appear in its
    # session's turns. Otherwise LoCoMo precision is incoherent.
    for q in fixture["questions"]:
        session_id = q.get("session_id", fixture["sessions"][0]["session_id"])
        session = next(
            s for s in fixture["sessions"] if s["session_id"] == session_id
        )
        joined = " ".join(t["text"] for t in session["turns"]).lower()
        assert q["expected_substring"].lower() in joined, (
            f"fixture self-consistency: {q['question']!r} expects "
            f"{q['expected_substring']!r} which is not in session {session_id}"
        )

    em = EpisodicMemory(db_path=str(tmp_path / "locomo.db"))
    await em.start()
    try:
        for sess in fixture["sessions"]:
            for turn in sess["turns"]:
                await em.store(Episode(user_input=turn["text"]))

        correct = 0
        total = len(fixture["questions"])
        per_q: list[dict] = []
        started = time.perf_counter()
        for q in fixture["questions"]:
            results = await em.recall(query=q["question"], k=3)
            top_text = " ".join(r.user_input for r in results).lower()
            hit = q["expected_substring"].lower() in top_text
            correct += int(hit)
            per_q.append({"q": q["question"], "hit": hit})
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        ratio = correct / total if total else 0.0
        print(
            json.dumps(
                {
                    "benchmark": "micro_locomo_v1",
                    "method": "recall",
                    "correct": correct,
                    "total": total,
                    "ratio": ratio,
                    "elapsed_ms": elapsed_ms,
                    "per_question": per_q,
                }
            )
        )
        assert 0.0 <= ratio <= 1.0
    finally:
        await em.stop()
