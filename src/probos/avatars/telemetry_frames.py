"""Pure avatar telemetry frame selection and semantic validation."""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from probos.avatars.snapshot_diff import compute_diff

if TYPE_CHECKING:
    from probos.avatars.telemetry import AvatarTelemetrySnapshot

logger = logging.getLogger(__name__)

MAX_AVATAR_SEQUENCE = 9_007_199_254_740_991
MAX_AVATAR_SAMPLING_RATE_MS = 2_147_483_647

SNAPSHOT_DATA_FIELDS = frozenset({
    "expression_resting",
    "current_signals",
    "mouth_active",
    "applied_modulation",
    "dsl_summary",
    "last_observed_at",
    "degraded_reasons",
    "sampling_rate_ms",
    "sampling_tier",
})
DIFF_DATA_FIELDS = SNAPSHOT_DATA_FIELDS - {"last_observed_at"}
EXPRESSION_VALUES = frozenset({
    "neutral",
    "gentle_smile",
    "focused",
    "alert",
})
WORKING_STATE_VALUES = frozenset({"idle", "responding", "blocked"})
SAMPLING_TIER_VALUES = frozenset({"high", "normal", "low"})
BODY_TYPE_VALUES = frozenset({"slim", "average", "stocky"})
HAIR_STYLE_VALUES = frozenset({
    "short",
    "medium",
    "long",
    "ponytail",
    "bun",
    "shaved",
})
OUTFIT_STYLE_VALUES = frozenset({
    "uniform",
    "casual",
    "formal",
    "robe",
    "tactical",
})
DEGRADED_REASON_VALUES = frozenset({
    "agent_not_found",
    "avatar_sampling_state_unavailable",
    "crew_profile_seeded",
    "crew_profile_default",
    "appearance_profile_missing",
    "dsl_not_persisted",
    "dsl_invalid",
    "insufficient_trust_history",
    "trust_history_malformed",
    "bridge_alerts_unavailable",
    "voice_profile_missing",
    "voice_modulation_failed",
})
FIRED_RULE_VALUES = frozenset({
    "responding_rate",
    "blocked_rate_pitch",
    "high_trust_pitch",
    "low_trust_pitch",
    "tier3_rate_volume",
    "intent_warm",
    "intent_concerned",
    "intent_excited",
    "intent_apologetic",
    "intent_formal",
    "intent_playful",
    "intent_reassuring",
    "intent_neutral",
})

_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_PRIMARY_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_PALETTE_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
_PALETTE_HEX_RE = re.compile(
    r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$"
)
_CUSTOM_RULE_RE = re.compile(r"^custom_[a-z][a-z_]{0,29}$")


class _SnapshotProtocol(Protocol):
    agent_id: str

    def to_dict(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class AvatarTelemetryFrame:
    agent_id: str
    frame_type: Literal["snapshot", "diff"]
    data: dict[str, Any]


def is_safe_avatar_agent_id(value: Any) -> bool:
    """Return whether *value* is an exact bounded avatar agent ID."""
    return type(value) is str and _AGENT_ID_RE.fullmatch(value) is not None


def _has_exact_keys(value: Any, expected: frozenset[str]) -> bool:
    if type(value) is not dict or dict.__len__(value) != len(expected):
        return False
    seen: set[str] = set()
    for key in dict.keys(value):
        if type(key) is not str or key not in expected:
            return False
        seen.add(key)
    return seen == expected


def _finite_float(value: Any, minimum: float, maximum: float) -> bool:
    return (
        type(value) is float
        and math.isfinite(value)
        and minimum <= value <= maximum
    )


def _exact_enum(value: Any, allowed: frozenset[str]) -> bool:
    return type(value) is str and value in allowed


def _validate_string_list(
    value: Any,
    *,
    maximum: int,
    allowed: frozenset[str] | None = None,
    allow_custom_rule: bool = False,
) -> list[str] | None:
    if type(value) is not list or list.__len__(value) > maximum:
        return None
    detached: list[str] = []
    seen: set[str] = set()
    for index in range(list.__len__(value)):
        item = list.__getitem__(value, index)
        if type(item) is not str or item in seen:
            return None
        if allowed is not None and item not in allowed:
            if not allow_custom_rule or _CUSTOM_RULE_RE.fullmatch(item) is None:
                return None
        seen.add(item)
        detached.append(item)
    return detached


def _validate_current_signals(value: Any) -> dict[str, Any] | None:
    keys = frozenset({"trust_delta", "load", "working_state", "tier3_alert"})
    if not _has_exact_keys(value, keys):
        return None
    trust_delta = dict.__getitem__(value, "trust_delta")
    load = dict.__getitem__(value, "load")
    working_state = dict.__getitem__(value, "working_state")
    tier3_alert = dict.__getitem__(value, "tier3_alert")
    if (
        not _finite_float(trust_delta, -1.0, 1.0)
        or not _finite_float(load, 0.0, 1.0)
        or not _exact_enum(working_state, WORKING_STATE_VALUES)
        or type(tier3_alert) is not bool
    ):
        return None
    return {
        "trust_delta": trust_delta,
        "load": load,
        "working_state": working_state,
        "tier3_alert": tier3_alert,
    }


def _validate_modulation(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    keys = frozenset({
        "pitch_factor",
        "rate_factor",
        "volume_factor",
        "fired_rules",
    })
    if not _has_exact_keys(value, keys):
        return None
    pitch = dict.__getitem__(value, "pitch_factor")
    rate = dict.__getitem__(value, "rate_factor")
    volume = dict.__getitem__(value, "volume_factor")
    fired = _validate_string_list(
        dict.__getitem__(value, "fired_rules"),
        maximum=16,
        allowed=FIRED_RULE_VALUES,
        allow_custom_rule=True,
    )
    if (
        not _finite_float(pitch, 0.0, 2.0)
        or not _finite_float(rate, 0.1, 10.0)
        or not _finite_float(volume, 0.0, 1.0)
        or fired is None
    ):
        return None
    return {
        "pitch_factor": pitch,
        "rate_factor": rate,
        "volume_factor": volume,
        "fired_rules": fired,
    }


def _is_safe_palette_hint(value: Any) -> bool:
    return (
        type(value) is str
        and (
            value == ""
            or _PALETTE_IDENTIFIER_RE.fullmatch(value) is not None
            or _PALETTE_HEX_RE.fullmatch(value) is not None
        )
    )


def _validate_dsl_summary(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    keys = frozenset({
        "body_type",
        "hair_style",
        "primary_color",
        "outfit_style",
        "color_palette_hint",
    })
    if not _has_exact_keys(value, keys):
        return None
    body_type = dict.__getitem__(value, "body_type")
    hair_style = dict.__getitem__(value, "hair_style")
    primary_color = dict.__getitem__(value, "primary_color")
    outfit_style = dict.__getitem__(value, "outfit_style")
    palette = dict.__getitem__(value, "color_palette_hint")
    if (
        not _exact_enum(body_type, BODY_TYPE_VALUES)
        or not _exact_enum(hair_style, HAIR_STYLE_VALUES)
        or type(primary_color) is not str
        or _PRIMARY_COLOR_RE.fullmatch(primary_color) is None
        or not _exact_enum(outfit_style, OUTFIT_STYLE_VALUES)
        or not _is_safe_palette_hint(palette)
    ):
        return None
    return {
        "body_type": body_type,
        "hair_style": hair_style,
        "primary_color": primary_color,
        "outfit_style": outfit_style,
        "color_palette_hint": palette,
    }


def _validate_field(name: str, value: Any) -> tuple[bool, Any]:
    if name == "expression_resting":
        if value is None:
            return True, None
        return _exact_enum(value, EXPRESSION_VALUES), value
    if name == "current_signals":
        detached = _validate_current_signals(value)
        return detached is not None, detached
    if name == "mouth_active":
        return type(value) is bool, value
    if name == "applied_modulation":
        if value is None:
            return True, None
        detached = _validate_modulation(value)
        return detached is not None, detached
    if name == "dsl_summary":
        if value is None:
            return True, None
        detached = _validate_dsl_summary(value)
        return detached is not None, detached
    if name == "last_observed_at":
        return _finite_float(value, 0.0, float(MAX_AVATAR_SEQUENCE)), value
    if name == "degraded_reasons":
        detached = _validate_string_list(
            value,
            maximum=12,
            allowed=DEGRADED_REASON_VALUES,
        )
        return detached is not None, detached
    if name == "sampling_rate_ms":
        valid = (
            type(value) is int
            and 250 <= value <= MAX_AVATAR_SAMPLING_RATE_MS
        )
        return valid, value
    if name == "sampling_tier":
        return _exact_enum(value, SAMPLING_TIER_VALUES), value
    return False, None


def validate_avatar_telemetry_data(
    data: Any,
    frame_type: Any,
) -> dict[str, Any] | None:
    """Validate and detach one snapshot/diff semantic data object."""
    if type(frame_type) is not str or frame_type not in {"snapshot", "diff"}:
        return None
    if type(data) is not dict:
        return None
    allowed = SNAPSHOT_DATA_FIELDS if frame_type == "snapshot" else DIFF_DATA_FIELDS
    length = dict.__len__(data)
    if frame_type == "snapshot":
        if length != len(SNAPSHOT_DATA_FIELDS):
            return None
    elif length == 0 or length > len(DIFF_DATA_FIELDS):
        return None
    detached: dict[str, Any] = {}
    for key in dict.keys(data):
        if type(key) is not str or key not in allowed:
            return None
        valid, field = _validate_field(key, dict.__getitem__(data, key))
        if not valid:
            return None
        detached[key] = field
    if frame_type == "snapshot" and frozenset(detached) != SNAPSHOT_DATA_FIELDS:
        return None
    return detached


def project_avatar_telemetry_data_for_federation(
    data: dict[str, Any],
) -> dict[str, Any]:
    """Return a federation-only top-level/DSL copy under palette policy B."""
    if type(data) is not dict:
        return data
    projected = dict.copy(data)
    if not dict.__contains__(data, "dsl_summary"):
        return projected
    dsl_summary = dict.__getitem__(data, "dsl_summary")
    if type(dsl_summary) is not dict:
        return projected
    projected_dsl = dict.copy(dsl_summary)
    projected["dsl_summary"] = projected_dsl
    if not dict.__contains__(dsl_summary, "color_palette_hint"):
        return projected
    palette = dict.__getitem__(dsl_summary, "color_palette_hint")
    if type(palette) is str and not _is_safe_palette_hint(palette):
        projected_dsl["color_palette_hint"] = ""
    return projected


def select_avatar_telemetry_frame(
    snapshot: AvatarTelemetrySnapshot | _SnapshotProtocol,
    *,
    previous_snapshot: dict[str, Any] | None,
    tick_count: int,
    diff_enabled: bool,
    diff_threshold: float,
    full_every_n: int,
    force_full: bool = False,
) -> tuple[AvatarTelemetryFrame | None, dict[str, Any] | None]:
    """Select a full/diff frame while preserving the existing WS policy."""
    snapshot_dict = snapshot.to_dict()
    agent_id = dict.__getitem__(snapshot_dict, "agent_id")
    current = {
        key: value
        for key, value in dict.items(snapshot_dict)
        if key != "agent_id"
    }
    send_full = (
        force_full
        or previous_snapshot is None
        or not diff_enabled
        or tick_count % full_every_n == 0
    )
    if send_full:
        return AvatarTelemetryFrame(agent_id, "snapshot", current), current
    try:
        changed = compute_diff(
            previous_snapshot,
            current,
            threshold=diff_threshold,
        )
    except Exception as exc:
        logger.warning(
            "Avatar telemetry diff selection failed agent=%s exception_type=%s; "
            "falling back to full snapshot",
            agent_id,
            type(exc).__name__,
        )
        return AvatarTelemetryFrame(agent_id, "snapshot", current), current
    if not changed:
        return None, previous_snapshot
    cursor = {**previous_snapshot, **changed}
    return AvatarTelemetryFrame(agent_id, "diff", changed), cursor


def avatar_telemetry_frame_to_ws(
    frame: AvatarTelemetryFrame,
) -> dict[str, Any]:
    """Render a selected frame in the unchanged local WebSocket shape."""
    if frame.frame_type == "snapshot":
        return {
            "type": "snapshot",
            "agent_id": frame.agent_id,
            **frame.data,
        }
    return {
        "type": "diff",
        "agent_id": frame.agent_id,
        "changed": frame.data,
    }