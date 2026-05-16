"""AD-729b: peer-observation conduct training module — mechanical gate.

Wave 163 ships the deterministic rubric grading + capability gate. LLM-graded
variant is filed as forward marker AD-729b-2.

Module structure (per ``config/manuals/peer_observation_conduct.yaml``):
  module:
    id: peer_observation_conduct
    version: int
    required_for_ranks: list[str]
    pass_threshold: float
    sections: list[{id, ...}]

Grade input shape (``responses`` arg to ``grade_module``):
  {section_id: float_score_in_[0.0, 1.0]}

A score for each weighted section is taken from ``responses``; missing
sections contribute zero. The weighted sum is compared against the module's
``final_assessment.pass_threshold`` (default 0.8).

Honest-degrade: file missing / parse error / schema mismatch → grade returns
False. Never raises.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_THRESHOLD = 0.8


def load_module(path: str | Path) -> dict[str, Any] | None:
    """Load + minimally validate the AD-729b YAML module.

    Returns the inner ``module`` dict on success, None on any failure.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
        parsed = yaml.safe_load(text) or {}
    except (OSError, yaml.YAMLError):
        logger.warning(
            "AD-729b: failed to load training module from %s; degrading",
            path, exc_info=True,
        )
        return None

    module = parsed.get("module") if isinstance(parsed, Mapping) else None
    if not isinstance(module, Mapping):
        logger.warning(
            "AD-729b: training module YAML missing top-level 'module' key at %s",
            path,
        )
        return None

    if module.get("id") != "peer_observation_conduct":
        logger.warning(
            "AD-729b: training module ID mismatch in %s (got %r)",
            path, module.get("id"),
        )
        return None

    return dict(module)


def grade_module(
    *,
    module: dict[str, Any] | None,
    responses: dict[str, float],
) -> bool:
    """Apply the deterministic weighted-rubric grade.

    Tier-2 throughout. Returns False on any failure mode (module None,
    malformed rubric, missing responses).
    """
    if module is None or not isinstance(module, Mapping):
        return False

    threshold = _DEFAULT_THRESHOLD
    rubric: Mapping[str, float] | None = None
    for section in module.get("sections", []) or []:
        if not isinstance(section, Mapping):
            continue
        if section.get("id") == "final_assessment":
            try:
                threshold = float(section.get("pass_threshold", _DEFAULT_THRESHOLD))
            except (TypeError, ValueError):
                threshold = _DEFAULT_THRESHOLD
            inner_rubric = section.get("rubric")
            if isinstance(inner_rubric, Mapping):
                rubric = inner_rubric
            break

    # Fall back to module-level pass_threshold if the section did not carry one.
    if "pass_threshold" in module and threshold == _DEFAULT_THRESHOLD:
        try:
            threshold = float(module["pass_threshold"])
        except (TypeError, ValueError):
            threshold = _DEFAULT_THRESHOLD

    if rubric is None:
        # Equal weighting across all sections with an id (excluding theory + final).
        weighted_sections = [
            str(s.get("id"))
            for s in (module.get("sections") or [])
            if isinstance(s, Mapping)
            and s.get("id") not in {"theory", "final_assessment"}
        ]
        if not weighted_sections:
            return False
        weight_each = 1.0 / len(weighted_sections)
        rubric = {section_id: weight_each for section_id in weighted_sections}

    try:
        score = 0.0
        for section_id, weight in rubric.items():
            response = float(responses.get(section_id, 0.0))
            response = max(0.0, min(1.0, response))
            score += response * float(weight)
    except (TypeError, ValueError):
        return False

    return score >= threshold


def peer_observation_graduation_gate(
    *,
    profile: Any,
    qualification_config: Any,
) -> tuple[bool, str | None]:
    """Boot-Camp / Qualification graduation gate.

    Returns ``(allowed, reason_when_blocked)``. When the gate is OFF
    (``peer_observation_certification_required=False``), always allows. When
    ON, blocks unless ``profile.peer_perception.certified`` is True.
    """
    if qualification_config is None:
        return True, None
    required = bool(getattr(qualification_config, "peer_observation_certification_required", False))
    if not required:
        return True, None
    peer_perception = getattr(profile, "peer_perception", None)
    if peer_perception is None:
        return False, "peer_observation_certification_required"
    if not bool(getattr(peer_perception, "certified", False)):
        return False, "peer_observation_certification_required"
    return True, None


async def set_peer_observation_certified(
    *,
    runtime: Any,
    agent_id: str,
    value: bool,
    reason: str = "",
) -> bool:
    """Atomically flip ``CrewProfile.peer_perception.certified`` for the
    target agent and emit the AD-729b certification event.

    Tier-2: returns False on any failure (registry miss, profile missing).
    """
    from probos.events import EventType

    registry = getattr(runtime, "registry", None)
    if registry is None:
        return False
    try:
        agent = registry.get(agent_id)
    except Exception:
        return False
    if agent is None:
        return False
    profile = getattr(agent, "profile", None) or getattr(agent, "crew_profile", None)
    if profile is None:
        return False
    peer_perception = getattr(profile, "peer_perception", None)
    if peer_perception is None:
        return False

    try:
        peer_perception.certified = bool(value)
    except Exception:
        logger.warning(
            "AD-729b: failed to set certified flag for agent_id=%s; degrading",
            agent_id, exc_info=True,
        )
        return False

    event_type = (
        EventType.PEER_OBSERVATION_CERTIFIED
        if value
        else EventType.PEER_OBSERVATION_CERTIFICATION_REVOKED
    )
    emit = getattr(runtime, "emit_event", None)
    if emit is not None:
        try:
            result = emit(event_type, {
                "agent_id": agent_id,
                "value": bool(value),
                "reason": reason,
            })
            if hasattr(result, "__await__"):
                await result
        except Exception:
            logger.warning(
                "AD-729b: emit_event failed for agent_id=%s; flag persisted",
                agent_id, exc_info=True,
            )
    return True


__all__ = [
    "grade_module",
    "load_module",
    "peer_observation_graduation_gate",
    "set_peer_observation_certified",
]
