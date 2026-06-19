"""AD-1028 golden snapshot capture — DM + WR ``_build_user_message`` byte contract.

Run ONCE pre-refactor against the unmodified push-style prepend chain to
capture the byte-shape of ``CognitiveAgent._build_user_message`` for a
representative DM and Ward-Room observation. The resulting ``dm_golden.txt`` /
``wr_golden.txt`` are the byte-equality contract for the AD-1028
ContextAssembler refactor: with ``attention.enabled=False`` (default), the
refactored method must reproduce them EXACTLY.

The agent/observation builders here are imported by
``tests/test_ad1028_context_assembler.py`` so the capture and the regression
oracle use identical setup (no drift).

Determinism levers (same trick as ``_capture_chain_baseline.py`` /
``test_ad646_cognitive_baseline``):
- ``_build_temporal_context`` is pinned to a frozen string so wall-clock drift
  cannot invalidate the snapshot.
- ``_dispatch_sensorium_async`` is replaced with a deterministic empty no-op so
  environment-coupled sensorium entries contribute nothing.
- ``_runtime`` / ``_working_memory`` are ``None`` so the runtime/WM-coupled
  blocks (telemetry, cold-start, active game, cognitive zone) deterministically
  skip.

Run as a module from the repository root::

    d:/ProbOS/.venv/Scripts/python.exe -m tests.fixtures.ad1028_golden._capture_golden
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from probos.cognitive.cognitive_agent import CognitiveAgent

# Frozen temporal header — deterministic stand-in for _build_temporal_context().
_FROZEN_TEMPORAL = "Current time: 2026-06-18 12:00:00 UTC (Thursday)"


async def _empty_sensorium(path: object, observation: dict) -> dict[str, str]:
    """Deterministic no-op replacement for ``_dispatch_sensorium_async``."""
    del path, observation
    return {}


def make_dm_agent() -> CognitiveAgent:
    """Build a minimal real CognitiveAgent for the DM golden snapshot."""
    agent = CognitiveAgent(agent_id="ad1028-dm", instructions="test")
    agent.callsign = "Tester"
    agent.agent_type = "tester"
    agent._runtime = None
    agent._working_memory = None
    agent._build_temporal_context = lambda: _FROZEN_TEMPORAL  # type: ignore[method-assign]
    agent._dispatch_sensorium_async = _empty_sensorium  # type: ignore[method-assign]
    return agent


def dm_observation() -> dict:
    """A representative ``direct_message`` observation.

    Triggers (in order): temporal, episodic (recent_memories), oracle
    (_oracle_context), session history, Captain message.
    """
    return {
        "intent": "direct_message",
        "params": {
            "text": "What did we discuss about the warp core?",
            "session_history": [
                {"role": "captain", "text": "Status report?"},
                {"role": "assistant", "text": "All systems nominal."},
            ],
        },
        "recent_memories": [
            {
                "source": "direct",
                "verified": True,
                "input": "We discussed the warp core alignment.",
                "age": "2 hours",
            },
            {
                "source": "secondhand",
                "verified": False,
                "reflection": "Heard about a coolant variance.",
                "anchor_channel": "engineering",
            },
        ],
        "_oracle_context": "Ship's records: warp core operating at 92% efficiency.",
    }


def make_wr_agent() -> CognitiveAgent:
    """Build a minimal real CognitiveAgent for the WR golden snapshot."""
    agent = CognitiveAgent(agent_id="ad1028-wr", instructions="test")
    agent.callsign = "Tester"
    agent.agent_type = "tester"
    agent._runtime = None
    agent._working_memory = None
    agent._build_temporal_context = lambda: _FROZEN_TEMPORAL  # type: ignore[method-assign]
    agent._dispatch_sensorium_async = _empty_sensorium  # type: ignore[method-assign]
    return agent


def wr_observation() -> dict:
    """A representative ``ward_room_notification`` observation.

    Triggers (in order): channel/thread header, temporal, episodic, oracle,
    thread context, author attribution, response guidance. Uses a non-``dm-``
    channel (skips DM self-monitoring) and a context that does not name the
    agent (skips self-recognition).
    """
    return {
        "intent": "ward_room_notification",
        "params": {
            "channel_name": "bridge",
            "author_callsign": "Bones",
            "title": "Coolant variance in section 3",
            "text": "We have a coolant variance in section 3.",
            "author_id": "bones",
            "was_mentioned": False,
        },
        "context": "Bones: We have a coolant variance.\nScotty: Investigating now.",
        "recent_memories": [
            {
                "source": "direct",
                "verified": True,
                "input": "Prior variance in section 2 last week.",
                "age": "1 day",
            },
        ],
        "_oracle_context": "Ship's records: section 3 maintenance is overdue.",
    }


def main() -> None:
    """Capture both golden snapshots to disk."""
    out = Path(__file__).parent
    dm = asyncio.run(make_dm_agent()._build_user_message(dm_observation()))
    wr = asyncio.run(make_wr_agent()._build_user_message(wr_observation()))
    (out / "dm_golden.txt").write_text(dm, encoding="utf-8")
    (out / "wr_golden.txt").write_text(wr, encoding="utf-8")
    print(f"DM golden: {len(dm)} chars -> dm_golden.txt")
    print(f"WR golden: {len(wr)} chars -> wr_golden.txt")


if __name__ == "__main__":
    main()
