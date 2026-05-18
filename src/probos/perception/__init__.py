"""AD-733: Visual perception subsystem — frame ingestion + episode anchoring.

v1 ships the wire shape only. A `vision_observation` :class:`IntentDescriptor`
is registered so the decomposer prompt knows about it, but no agent consumes
the intent — AD-733a adds the LLM consumer + tick batcher.

AD-731 invariant: frame bytes flow through ``AttachmentStore.write(sha, blob,
"image/jpeg")``. The :class:`IntentMessage.params` carries only the SHA ref —
NEVER inline base64.
"""
from __future__ import annotations

from probos.settings.section_registry import (
    FieldDescriptor,
    SectionDescriptor,
    insert_section,
)
from probos.types import IntentDescriptor

VISION_OBSERVATION_DESCRIPTOR = IntentDescriptor(
    name="vision_observation",
    params={
        "attachment_ref": "<sha256>",
        "mime": "image/jpeg",
        "captured_at": "<unix_timestamp>",
        "source": "camera",
        "session_id": "<opaque>",
    },
    description=(
        "A visual frame captured from an operator-side camera. "
        "AD-731 invariant: bytes are stored in AttachmentStore by SHA-256 "
        "— params['attachment_ref'] holds the SHA. No agent consumes this "
        "in v1 (see AD-733a forward marker)."
    ),
    requires_consensus=False,
    tier="domain",
)


_PERCEPTION_SECTION = SectionDescriptor(
    section_id="perception",
    label="Perception",
    glyph="▣",
    domain="Perception & Voice",
    description=(
        "Visual sensor input from operator-side capture devices "
        "(camera, screen). Default-OFF on both subsystem enable and the "
        "per-source camera enable — privacy-first posture. Captain holds "
        "explicit kill switch in the persistent CAMERA LIVE indicator."
    ),
    fields=(
        FieldDescriptor(
            "perception.enabled",
            "Perception subsystem",
            "bool",
            hot_reload=True,
        ),
        FieldDescriptor(
            "perception.camera.enabled",
            "Camera streaming",
            "bool",
            hot_reload=True,
        ),
        FieldDescriptor(
            "perception.camera.default_fps",
            "Frames per second",
            "int",
            description="1 = safe default. 4 max — vision tier inference cadence is the bottleneck.",
        ),
        FieldDescriptor(
            "perception.camera_max_fps_server",
            "Server fps cap",
            "int",
            description="Server-side hard cap regardless of client-side fps choice.",
        ),
        FieldDescriptor(
            "perception.frame_max_size_bytes",
            "Max frame size (bytes)",
            "int",
        ),
        FieldDescriptor(
            "perception.vision_novelty_threshold",
            "Novelty threshold",
            "float",
            description="0.00–1.00. Lower = more sensitive (more LLM calls). 0.08 default after BF-307 empirical evidence. Above this aHash diff, a frame is described.",
            hot_reload=True,
        ),
        FieldDescriptor(
            "perception.vision_min_interval_seconds",
            "Min seconds between describes",
            "float",
            description="Cost-discipline floor. 3s default. Lower = more responsive, higher LLM cost.",
            hot_reload=True,
        ),
    ),
)

# AD-733 inserts the perception section into the AD-741 registry, after
# "voice" (the existing Perception & Voice section). Idempotent on reimport.
insert_section(_PERCEPTION_SECTION, before="avatars")

__all__ = ["VISION_OBSERVATION_DESCRIPTOR"]
