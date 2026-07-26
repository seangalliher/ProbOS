"""AD-1143 DD-3 — blind LLM-as-judge scoring for the Σ ablation.

Modelled on ``src/probos/cognitive/communication_benchmarks.py`` (the
``_SCORING_PROMPT`` template with a ``{rubric}`` slot, ``LLMRequest`` at
``temperature=0.0``, ``extract_json`` parsing) but **copied into tests**:
production is not imported for behaviour and is not modified.

Two deliberate departures from AD-642:

- **The composite is the unweighted mean** of the four dimensions. Weighting is
  a research decision this AD is not equipped to make; equal weights are the
  honest default. ``_DIMENSION_WEIGHTS`` in ``communication_benchmarks.py`` is
  weighted, for a different construct — those weights are not reused.
- **A judge failure is never a 0.0 score.** AD-642 honest-degrades to zeros.
  Here a zero is indistinguishable from a genuinely terrible artifact and would
  silently bias whichever arm's judge call happened to fail, so any exception,
  transport error, unparseable JSON, missing dimension, or out-of-range value
  marks the trial ``judge_failed`` and excludes it from the aggregate.

**The validity threat, named.** Every tier routes through the same proxy, so
judge and system under test are the same model family. That cannot be
eliminated at this budget — an independent judge means a second vendor, key and
cost centre. The three affordable mitigations are all mandatory and all
implemented here: blind prompts with a seeded, recorded presentation order;
``temperature=0.0`` with a fixed ``max_tokens``; and the judge model *and* tier
recorded on **every** row, so a mid-run tier fallback is visible rather than
invisible.
"""

from __future__ import annotations

import hashlib
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from probos.types import LLMRequest
from probos.utils.json_extract import extract_json

from tests.ablation.sigma_flags import ARM_NAMES

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data"
RUBRIC_V1_PATH = DATA_DIR / "rubric_v1.md"

#: Human-readable rubric version. The *hash* is what the DD-7 comparison guard
#: enforces — a string version can be forgotten during an edit, a hash cannot.
RUBRIC_VERSION = "sigma-ablation-v1"

#: Nooplex §8.1 dimensions. Composite is their unweighted mean.
DIMENSIONS: tuple[str, ...] = (
    "coordination_quality",
    "reasoning_depth",
    "knowledge_retention",
    "artifact_correctness",
)

#: Judging happens at or above the tier of the system under test. Crew children
#: run on whatever their agent config specifies — typically standard/fast.
JUDGE_TIER = "deep"
JUDGE_TEMPERATURE = 0.0
JUDGE_MAX_TOKENS = 900

#: Generous cap. Truncation is recorded per row because systematically longer
#: artifacts in one arm being clipped would bias that arm.
ARTIFACT_MAX_CHARS = 24_000

#: Fixed seed for the per-goal presentation order (DD-3 mitigation 1).
BLIND_SEED = 1143

#: Terms that would unblind the judge. Checked against the harness-controlled
#: parts of the prompt (template, rubric, goal text) — not against the artifact,
#: which is model output and cannot be sanitised without corrupting the thing
#: being judged.
BLINDNESS_FORBIDDEN_TERMS: tuple[str, ...] = (
    "sigma",
    "shared memory",
    "ablation",
    "control",
    "treatment",
)

_JUDGE_PROMPT = """\
You are scoring one artifact produced by a crew of collaborating agents.

## Goal handed to the crew
{goal}

## Artifact
{artifact}

## Rubric
{rubric}

Score every dimension on the 0.0-1.0 scale defined above. Respond with JSON \
only, no preamble and no code fence:
{{"coordination_quality": 0.0, "reasoning_depth": 0.0, \
"knowledge_retention": 0.0, "artifact_correctness": 0.0, \
"justifications": {{"coordination_quality": "...", "reasoning_depth": "...", \
"knowledge_retention": "...", "artifact_correctness": "..."}}}}"""


@dataclass(frozen=True)
class Rubric:
    """A loaded, content-hashed rubric."""

    version: str
    text: str
    sha256: str
    path: Path


@dataclass(frozen=True)
class JudgeOutcome:
    """One judge call's result.

    ``scores`` and ``composite`` are ``None`` exactly when ``judge_failed`` is
    ``True`` — there is no path that produces a numeric score for a failed
    call.
    """

    judge_failed: bool
    judge_model: str
    judge_tier: str
    scores: dict[str, float] | None = None
    composite: float | None = None
    justifications: dict[str, str] = field(default_factory=dict)
    failure_reason: str | None = None
    artifact_truncated: bool = False


def blindness_violations(text: str) -> tuple[str, ...]:
    """Forbidden terms present in ``text`` (case-insensitive substring)."""
    lowered = text.lower()
    return tuple(term for term in BLINDNESS_FORBIDDEN_TERMS if term in lowered)


def load_rubric(path: Path = RUBRIC_V1_PATH) -> Rubric:
    """Load and hash the rubric, refusing one that would unblind the judge."""
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    violations = blindness_violations(text)
    if violations:
        raise ValueError(
            f"rubric {path.name} would unblind the judge; it contains "
            f"{list(violations)}"
        )
    return Rubric(
        version=RUBRIC_VERSION,
        text=text,
        sha256=hashlib.sha256(raw).hexdigest(),
        path=path,
    )


def render_judge_prompt(
    *,
    goal_text: str,
    artifact: str,
    rubric: Rubric,
) -> tuple[str, bool]:
    """Render the blind judge prompt. Returns ``(prompt, artifact_truncated)``.

    Raises ``ValueError`` when the goal text would unblind the judge. Goal text
    is a fixture under harness control, so a leak there is a build error, not a
    runtime condition to degrade around.
    """
    violations = blindness_violations(goal_text)
    if violations:
        raise ValueError(
            f"goal text would unblind the judge; it contains {list(violations)}"
        )
    truncated = len(artifact) > ARTIFACT_MAX_CHARS
    body = artifact[:ARTIFACT_MAX_CHARS] if truncated else artifact
    prompt = _JUDGE_PROMPT.format(
        goal=goal_text,
        artifact=body,
        rubric=rubric.text,
    )
    return prompt, truncated


def blind_order(
    goal_id: str,
    *,
    seed: int = BLIND_SEED,
    arms: tuple[str, ...] = ARM_NAMES,
) -> tuple[str, ...]:
    """Per-goal randomised arm presentation order, from a fixed seed.

    Deterministic and reproducible: the same goal id always yields the same
    order, so the arm↔position mapping recorded in the artifact can be audited
    after the fact.
    """
    ordered = list(arms)
    random.Random(f"{seed}:{goal_id}").shuffle(ordered)
    return tuple(ordered)


def blind_position(goal_id: str, arm: str, **kwargs: Any) -> int:
    """1-based presentation slot of ``arm`` for ``goal_id``."""
    order = blind_order(goal_id, **kwargs)
    if arm not in order:
        raise ValueError(f"unknown arm {arm!r}; expected one of {list(order)}")
    return order.index(arm) + 1


def _failure(
    reason: str,
    *,
    model: str = "",
    tier: str = JUDGE_TIER,
    truncated: bool = False,
) -> JudgeOutcome:
    return JudgeOutcome(
        judge_failed=True,
        judge_model=model,
        judge_tier=tier,
        failure_reason=reason,
        artifact_truncated=truncated,
    )


def parse_judge_payload(parsed: Any) -> tuple[dict[str, float], dict[str, str]] | str:
    """Validate a parsed judge payload.

    Returns ``(scores, justifications)`` or a failure-reason string. Scores are
    **not** clamped: an out-of-range value means the judge did not follow the
    rubric, which is a failure, not a number to squash into range.
    """
    if not isinstance(parsed, dict):
        return "json_not_an_object"
    scores: dict[str, float] = {}
    for dimension in DIMENSIONS:
        if dimension not in parsed:
            return f"missing_dimension:{dimension}"
        raw = parsed[dimension]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return f"non_numeric_score:{dimension}"
        value = float(raw)
        if value != value or value < 0.0 or value > 1.0:
            return f"score_out_of_range:{dimension}"
        scores[dimension] = value
    raw_justifications = parsed.get("justifications")
    justifications: dict[str, str] = {}
    if isinstance(raw_justifications, dict):
        justifications = {
            str(key): str(value)
            for key, value in raw_justifications.items()
            if key in DIMENSIONS
        }
    return scores, justifications


def composite_of(scores: dict[str, float]) -> float:
    """Unweighted mean of the four dimensions."""
    return sum(scores[dimension] for dimension in DIMENSIONS) / len(DIMENSIONS)


async def score_artifact(
    llm_client: Any,
    *,
    goal_text: str,
    artifact: str,
    rubric: Rubric,
    tier: str = JUDGE_TIER,
    max_tokens: int = JUDGE_MAX_TOKENS,
) -> JudgeOutcome:
    """Score one artifact blind. Never raises for a judge-side problem."""
    if llm_client is None:
        return _failure("no_llm_client", tier=tier)

    prompt, truncated = render_judge_prompt(
        goal_text=goal_text,
        artifact=artifact,
        rubric=rubric,
    )

    try:
        response = await llm_client.complete(LLMRequest(
            prompt=prompt,
            tier=tier,
            max_tokens=max_tokens,
            temperature=JUDGE_TEMPERATURE,
        ))
    except Exception:
        logger.warning(
            "AD-1143: judge call raised; the trial is recorded as judge_failed "
            "and excluded from the aggregate rather than scored 0.0",
            exc_info=True,
        )
        return _failure("llm_exception", tier=tier, truncated=truncated)

    # A tier fallback can change the model mid-run; record what actually
    # answered rather than what was requested.
    model = str(getattr(response, "model", "") or "")
    answered_tier = str(getattr(response, "tier", "") or tier)

    error = getattr(response, "error", None)
    if error:
        logger.warning(
            "AD-1143: judge call returned transport error %s; trial excluded",
            error,
        )
        return _failure(
            "llm_error", model=model, tier=answered_tier, truncated=truncated,
        )

    content = str(getattr(response, "content", "") or "")
    if not content.strip():
        return _failure(
            "empty_content", model=model, tier=answered_tier, truncated=truncated,
        )

    try:
        parsed = extract_json(content)
    except (ValueError, TypeError):
        parsed = None
    if parsed is None:
        logger.warning(
            "AD-1143: judge JSON parse failed (%s...); trial excluded",
            content[:200],
        )
        return _failure(
            "json_parse_failed",
            model=model,
            tier=answered_tier,
            truncated=truncated,
        )

    validated = parse_judge_payload(parsed)
    if isinstance(validated, str):
        logger.warning(
            "AD-1143: judge payload rejected (%s); trial excluded", validated,
        )
        return _failure(
            validated, model=model, tier=answered_tier, truncated=truncated,
        )

    scores, justifications = validated
    return JudgeOutcome(
        judge_failed=False,
        judge_model=model,
        judge_tier=answered_tier,
        scores=scores,
        composite=composite_of(scores),
        justifications=justifications,
        artifact_truncated=truncated,
    )
