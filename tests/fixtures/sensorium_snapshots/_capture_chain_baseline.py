"""AD-723 snapshot capture utility — chain baseline path.

Used ONCE pre-refactor to capture the byte-shape of `_build_cognitive_baseline`
under a deterministic canned observation + runtime. The resulting fixture file
``chain_baseline.txt`` is the byte-equality contract for the AD-723 refactor.

Run as a module from the repository root:

    d:/ProbOS/.venv/Scripts/python.exe -m tests.fixtures.sensorium_snapshots._capture_chain_baseline

Default config (avatar flags OFF, divergence_detection OFF) means the avatar
+ intent-self-tag entries return empty string and contribute no keys. This
keeps the producer-side AD-723 v1 byte-identical on the chain path.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from probos.cognitive.cognitive_agent import CognitiveAgent


def _make_runtime(trust_score: float = 0.75) -> MagicMock:
    rt = MagicMock()
    rt.trust_network.get_score.return_value = trust_score
    rt.ontology.get_crew_context.return_value = {
        "identity": {"callsign": "Echo", "post": "Counselor"},
        "department": {"name": "Medical"},
        "reports_to": "Captain",
        "direct_reports": ["Nurse Chapel"],
        "peers": ["Bones"],
        "vessel": {"name": "ProbOS", "version": "0.4", "alert_condition": "GREEN"},
        "capabilities": [],
        "does_not_have": [],
    }
    rt.is_cold_start = False
    rt.config = MagicMock()
    rt.config.earned_agency.initiative_trust_thresholds = None
    rt.config.avatar_telemetry = MagicMock()
    rt.config.avatar_telemetry.inject_into_agent_context = False
    rt.config.avatar_telemetry.divergence_detection = False
    return rt


def _make_agent() -> CognitiveAgent:
    agent = CognitiveAgent(agent_id="snapshot-agent", instructions="snapshot")
    agent.callsign = "SnapshotAgent"
    agent.agent_type = "snapshot_agent"
    agent._runtime = _make_runtime()
    return agent


def _canned_observation() -> dict:
    return {
        "recent_memories": [
            {"content": "Observed latency spike at 14:00", "timestamp": 1713500000},
            {"content": "Reviewed comm logs with Bones", "timestamp": 1713600000},
        ],
        "context": "Captain, please review.",
    }


def _render(state: dict) -> str:
    # Stable key order: insertion order from the dispatcher / pre-refactor
    # baseline path. Each entry serialized as "key\n<value>\n---\n".
    return "".join(f"{k}\n{v}\n---\n" for k, v in state.items())


def main() -> None:
    agent = _make_agent()
    observation = _canned_observation()
    # Pin temporal to a deterministic string so wall-clock drift cannot
    # invalidate the snapshot. Same trick as test_ad646_cognitive_baseline.
    agent._build_temporal_context = lambda: "Current time: 2026-05-10 12:00 UTC"
    state = agent._build_cognitive_baseline(observation)
    rendered = _render(state)
    out_path = Path(__file__).parent / "chain_baseline.txt"
    out_path.write_text(rendered, encoding="utf-8")
    print(f"Captured {len(state)} keys, {len(rendered)} chars to {out_path}")
    for key in state:
        print(f"  - {key}: {len(state[key])} chars")


if __name__ == "__main__":
    main()
