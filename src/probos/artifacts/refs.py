"""Public validation of the seven-field run_python artifact reference."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

ARTIFACT_REF_KEYS = frozenset(
    {"artifact_id", "content_hash", "thread_id", "name", "mime", "size_bytes", "version"}
)
MAX_ARTIFACT_SIZE_BYTES = 26_214_400
MAX_ARTIFACT_VERSION = 2_147_483_647


class ArtifactRef(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    artifact_id: str
    content_hash: str
    thread_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=255)
    mime: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1, le=MAX_ARTIFACT_SIZE_BYTES)
    version: int = Field(ge=1, le=MAX_ARTIFACT_VERSION)

    # Keep the legacy Python-string domain; UTF-8 evidence is a separate boundary.
    @field_validator("*", mode="plain")
    @classmethod
    def validate_legacy_field(cls, value: Any, info: ValidationInfo) -> Any:
        expected = int if info.field_name in {"size_bytes", "version"} else str
        if type(value) is not expected:
            raise ValueError("artifact reference field has the wrong type")
        if info.field_name == "artifact_id":
            valid = re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value)
        elif info.field_name == "content_hash":
            valid = re.fullmatch(r"[0-9a-f]{64}", value)
        elif info.field_name == "thread_id":
            valid = bool(value)
        elif info.field_name == "name":
            valid = 1 <= len(value) <= 255 and not any(
                character in value for character in ("/", "\\", "\x00")
            )
        elif info.field_name == "mime":
            valid = 1 <= len(value) <= 255
        elif info.field_name == "size_bytes":
            valid = 1 <= value <= MAX_ARTIFACT_SIZE_BYTES
        else:
            valid = 1 <= value <= MAX_ARTIFACT_VERSION
        if not valid:
            raise ValueError("artifact reference field violates its producer contract")
        return value


def validate_artifact_ref(value: object, *, thread_id: str) -> ArtifactRef:
    """Validate the existing producer shape, including current-thread ownership."""
    if (
        type(value) is not dict
        or any(type(key) is not str for key in value)
        or set(value) != ARTIFACT_REF_KEYS
    ):
        raise ValueError("artifact reference must have exactly the seven producer fields")
    ref = ArtifactRef.model_validate(value)
    if ref.thread_id != thread_id:
        raise ValueError("artifact reference belongs to a different thread")
    return ref
