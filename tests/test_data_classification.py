"""AD-754: data classification policy tests."""

from __future__ import annotations

from probos.security.data_classification import ClassificationPolicy, DataClassification


def test_classify_email_source_as_confidential() -> None:
    result = ClassificationPolicy.classify("agenda", source="outlook_email")
    assert result is DataClassification.CONFIDENTIAL


def test_classify_password_content_as_restricted() -> None:
    result = ClassificationPolicy.classify("contains password=abc123", source="notes")
    assert result is DataClassification.RESTRICTED
