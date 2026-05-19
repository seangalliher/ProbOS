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
        # AD-733-2: source is "camera" (default) or "screen". Sensor-input
        # only — VisionConsumer fan-out is source-agnostic in v1; forward
        # marker AD-733-2-1 covers per-source novelty thresholds.
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
        # AD-733-2: per-source screen toggle. Hot-reload so Captain can
        # flip without restart; default-OFF preserves privacy posture.
        FieldDescriptor(
            "perception.screen.enabled",
            "Screen streaming",
            "bool",
            description=(
                "AD-733-2: when ON, ambient screen-share frames are accepted "
                "via getDisplayMedia. Default-OFF — Captain opt-in."
            ),
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
        # AD-733-2: independent server-side cap for screen frames.
        FieldDescriptor(
            "perception.screen_max_fps_server",
            "Screen server fps cap",
            "int",
            description=(
                "AD-733-2: server-side hard cap on screen-frame ingest, "
                "independent of camera cap. Default 2."
            ),
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
        FieldDescriptor(
            "perception.vision_baseline_max_age_seconds",
            "Baseline refresh window (s)",
            "float",
            description="BF-309: after this many seconds with no admit, re-baseline on the next frame. Prevents static-scene lock-up. 30s default. 0 = disable.",
            hot_reload=True,
        ),
        FieldDescriptor(
            "perception.wm_persistence_enabled",
            "Persist vision working memory",
            "bool",
            description="AD-742f: load + write the per-agent vision working-memory ring to data/perception_wm.db so Captain's recent-frame recall survives restart. Disable for in-memory-only operation.",
            hot_reload=True,
        ),
        FieldDescriptor(
            "perception.vision_supervisor_strategy",
            "Supervisor strategy",
            "str",
            description="AD-742d: 'ahash' (default), 'motion', 'scene_change', 'never', 'always'. Restart required to swap.",
        ),
        FieldDescriptor(
            "perception.engaged_budget_enforcement",
            "Engaged budget enforcement",
            "bool",
            description="AD-733c-6: auto-drop ENGAGED→AMBIENT when cap reached. Hot-reload.",
            hot_reload=True,
        ),
        FieldDescriptor(
            "perception.engaged_call_cap_per_session",
            "Engaged calls/session cap",
            "int",
            description="AD-733c-6: vision LLM calls per session in ENGAGED before auto-drop. Default 200.",
            hot_reload=True,
        ),
        FieldDescriptor(
            "perception.engaged_call_cap_per_day",
            "Engaged calls/day cap",
            "int",
            description="AD-733c-6: vision LLM calls per UTC day before auto-drop. Default 2000.",
            hot_reload=True,
        ),
    ),
)

# AD-733 inserts the perception section into the AD-741 registry, after
# "voice" (the existing Perception & Voice section). Idempotent on reimport.
insert_section(_PERCEPTION_SECTION, before="avatars")

__all__ = ["VISION_OBSERVATION_DESCRIPTOR"]
