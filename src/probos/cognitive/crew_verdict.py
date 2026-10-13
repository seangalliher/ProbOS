"""Immutable criterion evidence shared by crew verdict boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)


def _criterion_text(value: object) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise ValueError("criterion_text_invalid")
    return value.strip()


class _Criterion(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, revalidate_instances="always",
    )

    name: str

    @model_validator(mode="before")
    @classmethod
    def _validate_passed(cls, value: Any) -> Any:
        # Literal[True/False] accepts 1/0 even under Pydantic strict mode.
        if type(value) is not dict or type(value.get("passed")) is not bool:
            raise ValueError("criterion_passed_invalid")
        return value

    @field_validator("name", mode="before")
    @classmethod
    def _validate_name(cls, value: object) -> str:
        return _criterion_text(value)


class CriterionPass(_Criterion):
    passed: Literal[True]


class CriterionFail(_Criterion):
    passed: Literal[False]
    gap: str

    @field_validator("gap", mode="before")
    @classmethod
    def _validate_gap(cls, value: object) -> str:
        return _criterion_text(value)


CriterionVerdict = Annotated[
    CriterionPass | CriterionFail, Field(discriminator="passed"),
]
_CRITERIA = TypeAdapter(list[CriterionVerdict])


def parse_criteria(value: object) -> tuple[CriterionVerdict, ...]:
    """Validate an explicit JSON criteria array, including an empty array."""
    if type(value) is not list:
        raise ValueError("verdict_criteria_invalid")
    return tuple(_CRITERIA.validate_python(value, strict=True))


def validate_criteria(
    accepted: bool,
    critique: object,
    criteria: tuple[CriterionVerdict, ...] | None,
) -> None:
    """Check summary consistency and require an actionable refusal gap."""
    if type(accepted) is not bool:
        raise ValueError("verdict_accepted_invalid")
    has_failure = any(not item.passed for item in criteria or ())
    if accepted and has_failure or not accepted and criteria and not has_failure:
        raise ValueError("verdict_criteria_inconsistent")
    if not accepted and not has_failure:
        _criterion_text(critique)


def parse_verdict_criteria(
    payload: Mapping[str, Any],
) -> tuple[CriterionVerdict, ...] | None:
    """Distinguish an absent extension from an explicit, validated array."""
    criteria = parse_criteria(payload["criteria"]) if "criteria" in payload else None
    validate_criteria(payload.get("accepted"), payload.get("critique"), criteria)
    return criteria


def criteria_to_json(
    criteria: tuple[CriterionVerdict, ...],
) -> list[dict[str, Any]]:
    return [criterion.model_dump(mode="json") for criterion in criteria]


# AD-1327: how independent the model that judged a verdict is of the crew's models.
# "unknown" is degraded like the two "same" outcomes and is never reported as
# "independent" (cognitive/verifier_independence.py decides it).
JudgeIndependence = Literal["same_model", "same_family", "unknown", "independent"]
MAX_JUDGE_MODEL_CHARS = 256


def is_persistable_judge_model(value: str) -> bool:
    """AD-1327: whether the text ``value`` can be a judge record's ``model``.

    No NUL, at most ``MAX_JUDGE_MODEL_CHARS`` characters, and strict UTF-8:
    a lone surrogate (what a JSON ``\\ud800`` escape decodes to) is refused, because the
    strict encoders the record passes through (the finalizer checkpoint, owned steps,
    trust evidence) cannot write it. The one bound for a persisted record
    (``JudgeProvenance``) and for a provider's reply (``VerifierJudgePolicy.provenance``).
    """
    if "\x00" in value or len(value) > MAX_JUDGE_MODEL_CHARS:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


class JudgeProvenance(BaseModel):
    """AD-1327: the model that judged one verdict, and how independent it is of the crew.

    ``tier`` is the tier the verifier requested: ``verifier`` when
    ``cognitive.llm_model_verifier`` is set, else ``standard``. ``model`` is the
    model id the provider's reply named (``LLMResponse.answered_model``), ``""``
    when it named none usable. ``fallback`` is True when the requested tier is not
    shown to have answered (``LLMResponse.answered_tier``): another tier of the
    fallback chain answered, or the response does not say which tier did.
    Persisted beside ``criteria`` and, like it, omitted when absent, so a verdict
    written before AD-1327 keeps its bytes.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    tier: Literal["verifier", "standard"]
    model: str
    independence: JudgeIndependence
    fallback: bool

    @field_validator("model", mode="before")
    @classmethod
    def _validate_model(cls, value: object) -> str:
        if type(value) is not str or not is_persistable_judge_model(value):
            raise ValueError("judge_provenance_invalid")
        return value

    @model_validator(mode="after")
    def _validate_consistency(self) -> JudgeProvenance:
        if self.fallback and self.independence == "independent":
            raise ValueError("judge_provenance_invalid")
        if not self.model and self.independence != "unknown":
            raise ValueError("judge_provenance_invalid")
        return self


def parse_judge(value: object) -> JudgeProvenance:
    """AD-1327: validate a persisted judge record (a JSON object); anything else is refused."""
    if type(value) is not dict:
        raise ValueError("judge_provenance_invalid")
    return JudgeProvenance.model_validate(value, strict=True)


def judge_to_json(judge: JudgeProvenance) -> dict[str, Any]:
    return judge.model_dump(mode="json")


def render_critique(
    critique: str,
    criteria: tuple[CriterionVerdict, ...] | None,
) -> str:
    """Append named gaps once at judgement time, never during rehydration."""
    gaps = [
        f"- {criterion.name}: {criterion.gap}"
        for criterion in criteria or ()
        if isinstance(criterion, CriterionFail)
    ]
    if not gaps:
        return critique
    feedback = "Criteria gaps:\n" + "\n".join(gaps)
    return f"{critique}\n\n{feedback}" if critique else feedback
