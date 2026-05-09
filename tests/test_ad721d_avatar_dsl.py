"""AD-721d D10: AvatarDSL Pydantic model boundary tests."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from probos.avatars.dsl import AppearanceProposalError, AvatarDSL


def test_default_construction_succeeds() -> None:
    dsl = AvatarDSL()
    assert dsl.body.type == "average"
    assert dsl.body.height_cm == 170
    assert dsl.hair.style == "medium"
    assert dsl.face.warmth == 0.5
    assert dsl.outfit.style == "uniform"
    assert dsl.outfit.primary_color == "#2a4a6a"
    assert dsl.outfit.accents == []
    assert dsl.expression_resting == "neutral"
    assert dsl.notes == ""


def test_height_cm_lower_bound_rejected() -> None:
    with pytest.raises(ValidationError):
        AvatarDSL.model_validate({"body": {"type": "average", "height_cm": 139}})


def test_height_cm_upper_bound_rejected() -> None:
    with pytest.raises(ValidationError):
        AvatarDSL.model_validate({"body": {"type": "average", "height_cm": 211}})


def test_outfit_color_regex_rejects_non_hex() -> None:
    with pytest.raises(ValidationError):
        AvatarDSL.model_validate({"outfit": {"primary_color": "red"}})


def test_outfit_accents_max_4() -> None:
    five = ["#aabbcc", "#112233", "#445566", "#778899", "#aabbcd"]
    with pytest.raises(ValidationError):
        AvatarDSL.model_validate({"outfit": {"accents": five}})


def test_notes_length_bound() -> None:
    with pytest.raises(ValidationError):
        AvatarDSL.model_validate({"notes": "x" * 281})


def test_round_trip_dict() -> None:
    dsl = AvatarDSL(notes="hello", outfit={"style": "robe", "primary_color": "#112233", "accents": ["#aabbcc"]})
    again = AvatarDSL.model_validate(dsl.model_dump())
    assert again == dsl
    assert again.outfit.primary_color == "#112233"
    assert again.outfit.accents == ["#aabbcc"]


def test_face_warmth_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        AvatarDSL.model_validate({"face": {"warmth": 1.5, "jaw": "neutral", "eyes": "almond"}})


def test_hair_hsl_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        AvatarDSL.model_validate({"hair": {"style": "medium", "color_hsl": [400, 50, 50]}})


def test_unknown_extra_field_rejected() -> None:
    """``model_config = ConfigDict(extra="forbid")`` blocks unknown fields."""
    with pytest.raises(ValidationError):
        AvatarDSL.model_validate({"body": {"type": "average", "height_cm": 170, "unknown_field": "x"}})


def test_invalid_enum_string_rejected() -> None:
    with pytest.raises(ValidationError):
        AvatarDSL.model_validate({"body": {"type": "alien", "height_cm": 170}})


def test_appearance_proposal_error_carries_reason_and_detail() -> None:
    err = AppearanceProposalError("schema_violation", detail="bad enum")
    assert err.reason == "schema_violation"
    assert err.detail == "bad enum"
    assert "schema_violation" in str(err)
    assert "bad enum" in str(err)


def test_no_eval_or_exec_in_dsl_module() -> None:
    """Defense-in-depth: AST scan of avatars/dsl.py asserts no eval/exec/compile.

    Hard-stop §3 from WAVE-134-DISPATCH: ``exec``/``eval``/``compile`` on DSL
    content is forbidden. This test pins that contract for the schema module.
    """
    src = Path(__file__).resolve().parents[1] / "src" / "probos" / "avatars" / "dsl.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    forbidden = {"eval", "exec", "compile", "__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in forbidden, (
                f"Forbidden function call {node.func.id!r} in avatars/dsl.py"
            )
