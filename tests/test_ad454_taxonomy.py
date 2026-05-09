"""AD-454: Tests for the emergence behavior taxonomy."""

from __future__ import annotations

from typing import cast

import pytest

from probos.cognitive.emergence_taxonomy import (
    TAXONOMY,
    BehaviorCode,
    TaxonomyEntry,
    all_codes,
    anti_pattern_codes,
    as_classifier_prompt,
    get_entry,
)


def test_all_22_codes_present() -> None:
    """Enum has exactly 22 members and every member resolves through TAXONOMY."""
    assert len(BehaviorCode) == 22
    assert len(TAXONOMY) == 22
    for code in BehaviorCode:
        assert code in TAXONOMY


def test_every_entry_populates_required_fields() -> None:
    """Each TaxonomyEntry has non-empty category/description/example and matches its key."""
    for code, entry in TAXONOMY.items():
        assert isinstance(entry, TaxonomyEntry)
        assert entry.code is code, f"key/code mismatch for {code}"
        assert entry.category, f"empty category for {code}"
        assert entry.description, f"empty description for {code}"
        assert entry.example, f"empty example for {code}"


def test_anti_pattern_flag_only_on_known_anti_patterns() -> None:
    """The only anti-pattern code in v1 is CASCADE_CONFAB."""
    assert anti_pattern_codes() == (BehaviorCode.CASCADE_CONFAB,)
    assert TAXONOMY[BehaviorCode.CASCADE_CONFAB].is_anti_pattern is True
    for code, entry in TAXONOMY.items():
        if code is not BehaviorCode.CASCADE_CONFAB:
            assert entry.is_anti_pattern is False, (
                f"{code} should not be flagged anti-pattern"
            )


def test_classifier_prompt_includes_every_code() -> None:
    """as_classifier_prompt() substring-contains every code's string value."""
    prompt = as_classifier_prompt()
    for code in BehaviorCode:
        assert code.value in prompt, f"prompt missing code {code.value}"


def test_classifier_prompt_includes_every_description() -> None:
    """as_classifier_prompt() substring-contains every entry's description."""
    prompt = as_classifier_prompt()
    for entry in TAXONOMY.values():
        assert entry.description in prompt, (
            f"prompt missing description for {entry.code.value}"
        )


def test_classifier_prompt_marks_anti_patterns() -> None:
    """The rendered prompt mentions 'anti-pattern' explicitly."""
    prompt = as_classifier_prompt().lower()
    assert "anti-pattern" in prompt
    # Ensure the anti-pattern flag appears at least once in the rendered list.
    assert "anti-pattern: yes" in prompt


def test_classifier_prompt_is_deterministic() -> None:
    """Two calls produce identical output (consumer tests pin against this)."""
    assert as_classifier_prompt() == as_classifier_prompt()


def test_get_entry_raises_keyerror_on_unknown_value() -> None:
    """Boundary test: passing a non-member raises KeyError on dict lookup."""
    with pytest.raises(KeyError):
        # Bypass the enum to drive the dict-miss path of get_entry.
        get_entry(cast(BehaviorCode, "NOT-A-REAL-CODE"))  # type: ignore[arg-type]


def test_taxonomy_dict_iteration_matches_enum_declaration_order() -> None:
    """Guards against accidental reordering, which would change classifier prompt output."""
    assert tuple(TAXONOMY.keys()) == tuple(BehaviorCode)
    assert all_codes() == tuple(BehaviorCode)


def test_classifier_prompt_emits_strict_json_contract() -> None:
    """The JSON output contract must be present so the collector can pin against it."""
    prompt = as_classifier_prompt()
    assert '"codes"' in prompt
    assert '"confidence"' in prompt
    assert '"reasoning"' in prompt
