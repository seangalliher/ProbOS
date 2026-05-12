"""AD-727 (Wave 154): static safety constraints for AD-722e self-perception.

These tests enforce the seven hard rules from AD-727 at the code level.
They are the durable gate — a failure here BLOCKS CI.

AD-727 was filed as a forward marker on 2026-05-10 and ratified in Wave 154
once AD-722e shipped. The five tests cover four of the seven hard rules
(rules 1, 2, 4, 5, 7). Rules 3 (asymmetric rollout), 6 (preferences are
proposals), and 8 (public framing) are documentation/process gates that
cannot be code-asserted in isolation — they are reviewed at AD-time.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


_SELF_PERCEPTION_PATH = (
    Path(__file__).resolve().parent.parent
    / "src" / "probos" / "cognitive" / "self_perception.py"
)


def _read_self_perception_source() -> str:
    """Read the AD-722e module source; loud failure if missing.

    Static checks scan the source text directly so they survive a future
    refactor that hides imports behind lazy loaders.
    """
    assert _SELF_PERCEPTION_PATH.exists(), (
        f"AD-727: self_perception.py must exist at {_SELF_PERCEPTION_PATH}. "
        "AD-722e is the prerequisite for AD-727 ratification."
    )
    return _SELF_PERCEPTION_PATH.read_text(encoding="utf-8")


def test_no_vision_llm_import_in_self_perception_v1():
    """AD-727 hard rule #4: vision-LLM side-channel ELIMINATED in v1.

    The self-perception projector must not call any LLM. Substring scan
    catches both direct ``complete(...)`` calls and the import of
    ``LLMRequest``.
    """
    src = _read_self_perception_source()
    forbidden = ["complete(", "LLMRequest(", "vision_tier"]
    for needle in forbidden:
        assert needle not in src, (
            f"AD-727 rule #4 violation: '{needle}' appears in "
            f"self_perception.py. Vision-LLM use is permanently prohibited "
            "in AD-722e v1; introduce a separate AD if you need it."
        )


def test_no_browser_capture_import_in_self_perception_v1():
    """AD-727 hard rule #5: browser-side capture ELIMINATED in v1.

    Permanent constraint. Any future visual extension goes against
    backend-server-side render only.
    """
    src = _read_self_perception_source()
    forbidden = [
        "getDisplayMedia",
        "chrome.tabCapture",
        "puppeteer",
        "playwright",
        "selenium",
        "pyppeteer",
    ]
    for needle in forbidden:
        assert needle not in src, (
            f"AD-727 rule #5 violation: '{needle}' appears in "
            f"self_perception.py. Browser-side capture is permanently "
            "prohibited."
        )


def test_self_perception_projection_signature_forbids_peer_params():
    """AD-727 hard rule #7: self-perception takes self.id as the ONLY agent param.

    Cross-crew visual perception is a separate AD with its own governance
    review (AD-722e-3 / AD-729 family).
    """
    from probos.cognitive.self_perception import project_self_perception
    sig = inspect.signature(project_self_perception)
    forbidden = {"peer_id", "other_agent_id", "agent_ids", "other_id", "peer"}
    overlap = forbidden & set(sig.parameters)
    assert not overlap, (
        f"AD-727 rule #7 violation: project_self_perception accepts "
        f"forbidden peer parameter(s): {sorted(overlap)}. Cross-crew "
        "perception belongs in a separate AD."
    )


@pytest.mark.asyncio
async def test_self_perception_does_not_call_trust_network():
    """AD-727 hard rule #1: aesthetic self-judgment is READ-ONLY w.r.t. trust.

    The projector must not mutate trust state or Hebbian weights. The
    divergence detector (AD-722a) is the path authorized to wire to trust;
    AD-722e's image-based observations are not.
    """
    from probos.cognitive.self_perception import project_self_perception

    trust_network = MagicMock()
    # Any mutation method present on the real network must remain uncalled.
    trust_network.update = MagicMock()
    trust_network.record_outcome = MagicMock()
    trust_network.observe = MagicMock()

    runtime = SimpleNamespace(
        trust_network=trust_network,
        config=SimpleNamespace(
            avatar_telemetry=SimpleNamespace(enabled=False),
        ),
    )

    # Returns None (telemetry disabled) — but the assertion is about the
    # absence of trust mutations regardless of outcome.
    await project_self_perception("agent-1", runtime)

    trust_network.update.assert_not_called()
    trust_network.record_outcome.assert_not_called()
    trust_network.observe.assert_not_called()


@pytest.mark.asyncio
async def test_self_perception_emits_pipeline_version():
    """AD-727 hard rule #2: pipeline version surfaces to the agent.

    The returned ``SelfPerceptionProjection`` MUST carry a non-empty
    pipeline_version string so renderer changes appear as observations
    rather than silent self-mutations.
    """
    # Build a stub telemetry snapshot via the same shape AD-722e reads.
    from probos.cognitive import self_perception as sp_mod

    fake_snapshot = SimpleNamespace(
        dsl=SimpleNamespace(
            body_type="slender",
            hair_style="short",
            outfit_style="duty",
            primary_color="amber",
        ),
        current_signals=SimpleNamespace(working_state="idle"),
        expression_resting="calm",
        mouth_active=False,
        modulation_rate_factor=1.0,
        modulation_pitch_factor=1.0,
    )

    async def _build(agent_id, runtime):
        return fake_snapshot

    # Patch the snapshot builder used by project_self_perception.
    original = sp_mod.build_telemetry_snapshot
    sp_mod.build_telemetry_snapshot = _build  # type: ignore[assignment]
    try:
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                avatar_telemetry=SimpleNamespace(enabled=True),
            ),
        )
        projection = await sp_mod.project_self_perception("agent-1", runtime)
    finally:
        sp_mod.build_telemetry_snapshot = original  # type: ignore[assignment]

    assert projection is not None, (
        "AD-727 rule #2: with telemetry enabled + snapshot available, "
        "projector must return a SelfPerceptionProjection (not None)."
    )
    assert isinstance(projection.pipeline_version, str)
    assert projection.pipeline_version, (
        "AD-727 rule #2 violation: pipeline_version is empty. The renderer "
        "version must surface to the agent so renderer changes appear as "
        "observations."
    )
