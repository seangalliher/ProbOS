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
