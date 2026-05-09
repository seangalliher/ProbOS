"""AD-715 / OpenCode magic-context — compression-ratio measurement harness.

Skipped by default. Opt-in via ``PROBOS_RESEARCH_BENCH=1``. Ingests a small
fixture conversation, recalls each turn through ``EpisodicMemory.recall``,
computes ``compression_ratio = compressed_chars / original_chars``, and
prints a single JSON line. The number is directional only — see
docs/research/opencode-magic-context-absorption.md section 6.

Pre-check (R2/R3): the harness uses ``EpisodicMemory.__init__(db_path=...)``
(verified at ``src/probos/cognitive/episodic.py:681``; the kwarg is
``db_path``, not ``persist_directory``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PROBOS_RESEARCH_BENCH") != "1",
    reason="Set PROBOS_RESEARCH_BENCH=1 to run the compression-ratio harness",
)

FIXTURE_PATH = Path(__file__).parent / "data" / "sample_session.json"


@pytest.mark.asyncio
async def test_compression_ratio_baseline(tmp_path: Path) -> None:
    from probos.cognitive.episodic import EpisodicMemory
    from probos.types import Episode

    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    turns = fixture["turns"]
    original_chars = sum(len(t["content"]) for t in turns)

    em = EpisodicMemory(db_path=str(tmp_path / "compress.db"))
    await em.start()
    try:
        # Ingest each turn as an Episode (user_input is the only required field).
        for t in turns:
            await em.store(Episode(user_input=t["content"]))

        # Compressed proxy: recall the user-prompt content of each user turn
        # and sum the lengths of the recalled episodes' user_input. This is
        # the rough measure of "what comes back from the memory layer for a
        # given prompt." A deeper API (dream-cycle summary) is the next rung
        # — pinned in absorption doc section 6 as out of scope for v1.
        compressed_chars = 0
        for t in turns:
            if t["role"] != "user":
                continue
            results = await em.recall(query=t["content"], k=1)
            if results:
                compressed_chars += len(results[0].user_input)

        ratio = compressed_chars / original_chars if original_chars else 0.0
        print(json.dumps({
            "benchmark": "compression_ratio_v1",
            "original_chars": original_chars,
            "compressed_chars": compressed_chars,
            "ratio": ratio,
            "method": "probos_recall_proxy",
        }))
        # R4: loosened from (0.0, 1.0] to > 0.0 — expansion is rare but legal
        # when ProbOS recall surfaces a longer related episode than the query.
        assert ratio > 0.0
    finally:
        await em.stop()
