"""AD-754: OSS desktop data-classification baseline policy."""

from __future__ import annotations

from enum import Enum


class DataClassification(Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class ClassificationPolicy:
    """OSS baseline policy. Commercial DLP/compliance remains extension-only."""

    @staticmethod
    def classify(content: str, source: str = "unknown") -> DataClassification:
        """Infer classification from content and source context."""
        normalized_source = source.lower()
        normalized_content = content.lower()

        if "email" in normalized_source or "outlook" in normalized_source:
            return DataClassification.CONFIDENTIAL
        if "password" in normalized_content or "secret" in normalized_content:
            return DataClassification.RESTRICTED
        return DataClassification.INTERNAL
