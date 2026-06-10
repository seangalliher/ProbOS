"""CrewProfile — formal identity, personality, and performance records for every agent (AD-376).

Every ProbOS agent is a crew member with a personnel file. This module provides:
- CrewProfile: identity, rank, department, personality traits, specialization
- PersonalityTraits: Big Five personality dimensions, seeded and evolvable
- Rank enum: Ensign → Lieutenant → Commander → Senior Officer
- PerformanceReview: timestamped performance snapshot
- ProfileStore: persistence and lookup
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.substrate.registry import AgentRegistry

logger = logging.getLogger(__name__)


class Rank(Enum):
    """Crew member rank — earned through sustained performance."""
    ENSIGN = "ensign"           # Trust < 0.5, new or unproven
    LIEUTENANT = "lieutenant"   # Trust 0.5–0.7, reliable performer
    COMMANDER = "commander"     # Trust 0.7–0.85, proven leader
    SENIOR = "senior_officer"   # Trust 0.85+, sustained excellence

    @classmethod
    def from_trust(cls, trust_score: float) -> "Rank":
        """Determine rank tier from current trust score."""
        from probos.config import TRUST_SENIOR, TRUST_COMMANDER, TRUST_LIEUTENANT
        if trust_score >= TRUST_SENIOR:
            return cls.SENIOR
        elif trust_score >= TRUST_COMMANDER:
            return cls.COMMANDER
        elif trust_score >= TRUST_LIEUTENANT:
            return cls.LIEUTENANT
        return cls.ENSIGN


@dataclass
class PersonalityTraits:
    """Big Five personality dimensions — seeded at creation, evolve over time.

    Each dimension is a float 0.0–1.0:
    - openness: curiosity, creativity, willingness to try new approaches
    - conscientiousness: thoroughness, reliability, attention to detail
    - extraversion: proactive communication, collaboration seeking
    - agreeableness: cooperative spirit, deference to consensus
    - neuroticism: sensitivity to failure, risk aversion, stress response

    The initial seed comes from crew_profiles/ YAML. Over time, these evolve
    based on interactions, dream consolidation, and Counselor adjustments.
    The Counselor tracks drift from the baseline snapshot.
    """
    openness: float = 0.5
    conscientiousness: float = 0.5
    extraversion: float = 0.5
    agreeableness: float = 0.5
    neuroticism: float = 0.5

    def __post_init__(self) -> None:
        for attr in ("openness", "conscientiousness", "extraversion",
                     "agreeableness", "neuroticism"):
            val = getattr(self, attr)
            if not 0.0 <= val <= 1.0:
                raise ValueError(f"{attr} must be 0.0–1.0, got {val}")

    def distance_from(self, baseline: "PersonalityTraits") -> float:
        """Euclidean distance from a baseline — used for drift detection."""
        dims = ("openness", "conscientiousness", "extraversion",
                "agreeableness", "neuroticism")
        return sum((getattr(self, d) - getattr(baseline, d)) ** 2
                   for d in dims) ** 0.5

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, float]) -> "PersonalityTraits":
        return cls(**{k: data[k] for k in
                      ("openness", "conscientiousness", "extraversion",
                       "agreeableness", "neuroticism") if k in data})


# AD-718e: BCP 47-shape language tag. Two/three lowercase letters, optional
# region/variant after _ or -. Conservative on purpose; not full BCP 47.
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}([_-][A-Za-z0-9]{2,8})?$")


@dataclass
class VoiceProfile:
    """AD-718: per-agent voice override for browser SpeechSynthesis playback.

    `voice_name` is the exact `SpeechSynthesisVoice.name` to prefer. The browser
    voice catalogue is OS- and browser-specific, so `voice_name` is best-effort:
    if it is empty or not present on the user's machine, the HXI falls back to
    the global default voice (``localStorage("hxi_voice_name")``) and applies
    the pitch/rate/volume below to that voice.
    """
    voice_name: str = ""    # SpeechSynthesisVoice.name; "" = use global default
    pitch: float = 0.9      # 0.0–2.0 (matches voice.ts v0 default)
    rate: float = 0.95      # 0.1–10.0
    volume: float = 0.8     # 0.0–1.0
    # AD-718c: optional per-agent wake phrase. Empty string == no per-agent
    # wake (system-wide "Computer" still routes to the agent via @callsign).
    # Bounds: stripped + length ≤ 50 chars; rejects YAML anchor/alias tokens
    # so the dataclass is also a defense-in-depth boundary on PUT-from-UI
    # (the AD-718a parser already rejects these at the LLM-output surface).
    wake_phrase: str = ""
    # AD-718e: ISO 639-1 language code (or BCP 47 short tag like 'en-US').
    # Used by the HXI voice picker to filter the available voice list, and
    # by browser SpeechSynthesis fallback resolution (prefer voices whose
    # ``lang`` field starts with this prefix before falling back to en).
    # Empty string is normalized to 'en' for backward-compat.
    language: str = "en"

    def __post_init__(self) -> None:
        if not 0.0 <= self.pitch <= 2.0:
            raise ValueError(f"pitch must be 0.0–2.0, got {self.pitch}")
        if not 0.1 <= self.rate <= 10.0:
            raise ValueError(f"rate must be 0.1–10.0, got {self.rate}")
        if not 0.0 <= self.volume <= 1.0:
            raise ValueError(f"volume must be 0.0–1.0, got {self.volume}")
        # AD-718c: wake_phrase normalisation + bounds. Strip whitespace so
        # " Ezri " round-trips as "Ezri". The dataclass is frozen=False, so
        # direct attribute assignment works.
        if not isinstance(self.wake_phrase, str):
            raise ValueError(
                f"wake_phrase must be str, got {type(self.wake_phrase).__name__}"
            )
        self.wake_phrase = self.wake_phrase.strip()
        if len(self.wake_phrase) > 50:
            raise ValueError(
                f"wake_phrase must be ≤ 50 chars, got {len(self.wake_phrase)}"
            )
        if (
            "&" in self.wake_phrase
            or "!!" in self.wake_phrase
            or "*" in self.wake_phrase
        ):
            raise ValueError(
                "wake_phrase must not contain YAML anchor/alias/tag tokens"
            )
        # AD-718e: language normalisation. Strip → empty maps to 'en'
        # BEFORE the regex validation so backward-compat default-empty rows
        # round-trip cleanly.
        if not isinstance(self.language, str):
            raise ValueError(
                f"language must be str, got {type(self.language).__name__}"
            )
        self.language = self.language.strip()
        if not self.language:
            self.language = "en"
        if len(self.language) > 16:
            raise ValueError(
                f"language must be ≤ 16 chars, got {len(self.language)}"
            )
        if not _LANGUAGE_RE.match(self.language):
            raise ValueError(
                f"language must match {_LANGUAGE_RE.pattern!r}, got {self.language!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VoiceProfile":
        return cls(**{
            k: data[k] for k in (
                "voice_name", "pitch", "rate", "volume", "wake_phrase",
                "language",
            ) if k in data
        })


# AD-737: custom emotion key regex (lowercase, leading letter, ≤30 chars, no spaces).
_CUSTOM_EMOTION_NAME_RE = re.compile(r"^[a-z][a-z_]{0,29}$")


@dataclass
class EmotionProfile:
    """AD-737: per-agent custom emotion override.

    A custom emotion is a NAME the LLM may emit in the ``<intent emotion=NAME>``
    self-tag in place of (or in addition to) the v1 fixed eight. Each custom
    emotion ``inherits`` from a v1 emotion — the divergence detector resolves
    through ``inherits`` to compute INTENT_DIRECTION and INTENT_EXPECTED_RULES.

    Voice deltas (``pitch_shift``, ``rate_shift``, ``volume_shift``) are
    ADDITIVE on top of the parent's manifest factor and clamped to ±0.15.
    The parent emotion's rule fires first; the delta composes on top.

    The bound of 8 custom emotions per agent (enforced on ``CrewProfile``)
    keeps the taxonomy small enough that agents stay distinct rather than
    producing a 30-emotion zoo indistinguishable from no taxonomy at all.
    All fields validated in ``__post_init__``.
    """

    inherits: str
    pitch_shift: float = 0.0
    rate_shift: float = 0.0
    volume_shift: float = 0.0

    SHIFT_BOUND: ClassVar[float] = 0.15

    def __post_init__(self) -> None:
        # Defer the EmotionalIntent import to avoid the avatars-pipeline
        # import cycle (crew_profile is imported very early in startup).
        from probos.avatars.divergence_detector import EmotionalIntent
        valid = {e.value for e in EmotionalIntent}
        if self.inherits not in valid:
            raise ValueError(
                f"EmotionProfile.inherits={self.inherits!r} must be one of "
                f"{sorted(valid)}"
            )
        for name in ("pitch_shift", "rate_shift", "volume_shift"):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise ValueError(
                    f"EmotionProfile.{name} must be a number, got "
                    f"{type(v).__name__}"
                )
            if abs(v) > self.SHIFT_BOUND:
                raise ValueError(
                    f"EmotionProfile.{name}={v} exceeds ±{self.SHIFT_BOUND}"
                )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EmotionProfile":
        return cls(**{
            k: data[k] for k in (
                "inherits", "pitch_shift", "rate_shift", "volume_shift",
            ) if k in data
        })


@dataclass
class AppearanceProfile:
    """AD-721: per-agent 3D avatar appearance.

    `vrm_url` is a URL relative to the HXI's static-file root (served by
    ``routers/system.py``'s avatar route, AD-721 D6). Empty `vrm_url` means
    "use the parametric fallback". `expression_overrides` maps VRM blend-shape
    names to scalar offsets so a single VRM model can be re-skinned per agent
    without authoring a new ``.vrm`` file. `color_palette_hint` is consumed
    by the parametric fallback only.

    AD-721d: ``dsl`` is the agent-authored ``AvatarDSL`` artifact (Pydantic
    model serialised as a dict). ``None`` = the agent has not proposed yet
    OR the Captain has not approved. Persisted as a JSON dict on the
    existing ``crew_profiles.data`` JSON-blob column — no new SQLite table.
    """
    vrm_url: str = ""                                    # "" = parametric fallback
    expression_overrides: dict[str, float] = field(default_factory=dict)
    color_palette_hint: str = ""                         # any CSS color; "" = use department color
    dsl: dict[str, Any] | None = None                    # AD-721d: agent-authored AvatarDSL (dict form)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppearanceProfile":
        dsl_value = data.get("dsl")
        return cls(
            vrm_url=data.get("vrm_url", ""),
            expression_overrides=dict(data.get("expression_overrides", {})),
            color_palette_hint=data.get("color_palette_hint", ""),
            dsl=dict(dsl_value) if isinstance(dsl_value, dict) else None,
        )


@dataclass
class PerformanceReview:
    """Timestamped performance snapshot — append-only history."""
    timestamp: float = 0.0
    trust_score: float = 0.0
    hebbian_avg: float = 0.0       # avg Hebbian weight with peers
    success_rate: float = 0.0      # success_count / total_operations
    tasks_completed: int = 0
    rank_at_review: str = "ensign"
    notes: str = ""                # Counselor or Captain notes
    reviewer: str = "system"       # "system", "counselor", "captain"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PerformanceReview":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class PeerPerceptionProfile:
    """AD-729: per-agent governance flags for peer avatar perception.

    ``enabled`` is the OPT-OUT flag. Default True for crew agents; the
    AgentDesigner / spawner flips utility and system tiers to False so they
    do not participate. ``certified`` is the AD-729b training-completion
    flag — ``observe_peer`` requires the OBSERVER to have ``certified=True``
    before it will record any observation.
    """
    enabled: bool = True
    certified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PeerPerceptionProfile":
        return cls(
            enabled=bool(data.get("enabled", True)),
            certified=bool(data.get("certified", False)),
        )


@dataclass
class PerceptionProfile:
    """AD-733c-5 + AD-742c + AD-746: per-agent perception bindings.

    Shared between three ADs:

    - ``engagement_enabled`` and ``initial_mode`` belong to AD-733c-5
      (per-agent ``PerceptionModeController`` registry).
    - ``camera_device_id`` belongs to AD-742c (per-agent camera). Empty
      string means "share the default camera" — current pre-AD-742c
      behavior.
    - ``bound_sources`` belongs to AD-746 Layer 2. Restricts which
      visual sources the agent observes. Defaults to both sources
      (``["camera", "screen"]``) so agents that haven't been bound
      explicitly see everything — pre-AD-746 fan-out behavior.

    Defaults preserve current singleton behavior: when a legacy profile
    JSON omits this block, ``from_dict`` synthesizes the default values
    and the agent participates in engagement with the runtime-wide
    default camera and observes both sources.
    """
    engagement_enabled: bool = True
    initial_mode: str = "ambient"
    camera_device_id: str = ""
    # AD-746 Layer 2 — defaults to both sources for back-compat.
    bound_sources: list[str] = field(
        default_factory=lambda: ["camera", "screen"],
    )

    def __post_init__(self) -> None:
        # AD-746: validate bound_sources is a subset of the known set.
        # Tier-2: invalid entries are dropped silently with a logger
        # warning — operator profile JSON might be hand-edited and
        # tolerant parsing matches the rest of the dataclass.
        _valid = {"camera", "screen"}
        cleaned = [s for s in self.bound_sources if s in _valid]
        # De-duplicate while preserving order.
        seen: set[str] = set()
        deduped: list[str] = []
        for s in cleaned:
            if s not in seen:
                seen.add(s)
                deduped.append(s)
        self.bound_sources = deduped

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PerceptionProfile":
        raw_sources = data.get("bound_sources", ["camera", "screen"])
        if isinstance(raw_sources, (list, tuple)):
            sources_list = [str(s) for s in raw_sources if isinstance(s, str)]
        else:
            sources_list = ["camera", "screen"]
        return cls(
            engagement_enabled=bool(data.get("engagement_enabled", True)),
            initial_mode=str(data.get("initial_mode", "ambient")),
            camera_device_id=str(data.get("camera_device_id", "")),
            bound_sources=sources_list,
        )


@dataclass
class CrewProfile:
    """Formal identity record for a ProbOS agent.

    This is the agent's "personnel file" — everything the Captain and Counselor
    need to know about who this crew member is and how they're performing.
    """
    # Identity
    agent_id: str = ""
    agent_type: str = ""
    display_name: str = ""         # Human-readable name, e.g., "Builder", "Diagnostician"
    callsign: str = ""             # Optional short name, e.g., "Scotty", "Bones"
    department: str = ""           # From standing_orders._AGENT_DEPARTMENTS
    pool: str = ""
    role: str = ""                 # "chief", "officer", "crew"

    # AD-720d-2: per-agent vision capability gate. Default False so a new
    # agent type that has not been ratified for vision attachments routes
    # image-bearing DMs through the text-only fallback (attachment markers
    # + extracted text). Counselor + Architect default to True via seed
    # YAML (config/standing_orders/crew_profiles/*.yaml).
    vision_capable: bool = False

    # Rank
    rank: Rank = Rank.ENSIGN
    rank_since: float = 0.0        # timestamp of last rank change
    promotions: int = 0
    demotions: int = 0

    # Personality
    personality: PersonalityTraits = field(default_factory=PersonalityTraits)
    personality_baseline: PersonalityTraits = field(default_factory=PersonalityTraits)

    # Voice (AD-718)
    voice: VoiceProfile = field(default_factory=VoiceProfile)

    # Appearance (AD-721)
    appearance: AppearanceProfile = field(default_factory=AppearanceProfile)

    # AD-729: peer avatar perception governance. Default-True for crew
    # agents; AgentDesigner/spawner flips utility/system tiers to
    # ``enabled=False``. ``certified=True`` is the AD-729b qualification
    # flag that unlocks the capability for THIS observer.
    peer_perception: PeerPerceptionProfile = field(default_factory=PeerPerceptionProfile)

    # AD-733c-5 + AD-742c: per-agent perception engagement + camera binding.
    perception: PerceptionProfile = field(default_factory=PerceptionProfile)

    # AD-737: per-agent custom emotion taxonomy. Empty dict = use v1 fixed
    # eight only (no behaviour change). Keys must match
    # ``_CUSTOM_EMOTION_NAME_RE`` and must not collide with the v1 names.
    # Max 8 entries per agent.
    custom_emotions: dict[str, EmotionProfile] = field(default_factory=dict)

    # Performance
    reviews: list[PerformanceReview] = field(default_factory=list)

    # Timestamps
    commissioned: float = 0.0      # when profile was created
    last_updated: float = 0.0

    def __post_init__(self) -> None:
        # AD-737: validate custom_emotions
        if len(self.custom_emotions) > 8:
            raise ValueError(
                f"custom_emotions max 8 entries, got "
                f"{len(self.custom_emotions)}"
            )
        if self.custom_emotions:
            from probos.avatars.divergence_detector import EmotionalIntent
            v1_names = {e.value for e in EmotionalIntent}
            for name, profile in self.custom_emotions.items():
                if not _CUSTOM_EMOTION_NAME_RE.match(name):
                    raise ValueError(
                        f"custom_emotions key {name!r} must match "
                        f"{_CUSTOM_EMOTION_NAME_RE.pattern}"
                    )
                if not isinstance(profile, EmotionProfile):
                    raise ValueError(
                        f"custom_emotions[{name!r}] must be EmotionProfile, "
                        f"got {type(profile).__name__}"
                    )
                if name in v1_names:
                    raise ValueError(
                        f"custom emotion name {name!r} collides with v1 "
                        f"taxonomy; use a distinct name (e.g. "
                        f"'professional_concern' not 'concerned')"
                    )

    def personality_drift(self) -> float:
        """How far current personality has drifted from baseline."""
        return self.personality.distance_from(self.personality_baseline)

    def add_review(self, review: PerformanceReview) -> None:
        """Append a performance review to history."""
        self.reviews.append(review)
        self.last_updated = time.time()

    def latest_review(self) -> PerformanceReview | None:
        """Most recent performance review, or None."""
        return self.reviews[-1] if self.reviews else None

    def promotion_velocity(self) -> float:
        """Promotions per 24-hour period since commissioning."""
        elapsed = time.time() - self.commissioned
        if elapsed <= 0 or self.promotions == 0:
            return 0.0
        days = elapsed / 86400
        return self.promotions / days if days > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "display_name": self.display_name,
            "callsign": self.callsign,
            "department": self.department,
            "pool": self.pool,
            "role": self.role,
            "vision_capable": self.vision_capable,
            "rank": self.rank.value,
            "rank_since": self.rank_since,
            "promotions": self.promotions,
            "demotions": self.demotions,
            "personality": self.personality.to_dict(),
            "personality_baseline": self.personality_baseline.to_dict(),
            "voice": self.voice.to_dict(),
            "appearance": self.appearance.to_dict(),
            "peer_perception": self.peer_perception.to_dict(),
            "perception": self.perception.to_dict(),
            "custom_emotions": {
                k: v.to_dict() for k, v in self.custom_emotions.items()
            },
            "reviews": [r.to_dict() for r in self.reviews],
            "commissioned": self.commissioned,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CrewProfile":
        profile = cls(
            agent_id=data.get("agent_id", ""),
            agent_type=data.get("agent_type", ""),
            display_name=data.get("display_name", ""),
            callsign=data.get("callsign", ""),
            department=data.get("department", ""),
            pool=data.get("pool", ""),
            role=data.get("role", ""),
            vision_capable=data.get("vision_capable", False),
            rank=Rank(data["rank"]) if "rank" in data else Rank.ENSIGN,
            rank_since=data.get("rank_since", 0.0),
            promotions=data.get("promotions", 0),
            demotions=data.get("demotions", 0),
            commissioned=data.get("commissioned", 0.0),
            last_updated=data.get("last_updated", 0.0),
        )
        if "personality" in data:
            profile.personality = PersonalityTraits.from_dict(data["personality"])
        if "personality_baseline" in data:
            profile.personality_baseline = PersonalityTraits.from_dict(data["personality_baseline"])
        if "voice" in data:
            profile.voice = VoiceProfile.from_dict(data["voice"])
        if "appearance" in data:
            profile.appearance = AppearanceProfile.from_dict(data["appearance"])
        if "peer_perception" in data:
            profile.peer_perception = PeerPerceptionProfile.from_dict(data["peer_perception"])
        if "perception" in data:
            profile.perception = PerceptionProfile.from_dict(data["perception"])
        if "custom_emotions" in data:
            profile.custom_emotions = {
                k: EmotionProfile.from_dict(v)
                for k, v in (data["custom_emotions"] or {}).items()
            }
        if "reviews" in data:
            profile.reviews = [PerformanceReview.from_dict(r) for r in data["reviews"]]
        return profile


class ProfileStore:
    """Persistence layer for crew profiles — SQLite backed.

    Follows the same persistence pattern as TrustNetwork and EpisodicMemory.
    """

    def __init__(self, db_path: str = "") -> None:
        self._db_path = db_path or ":memory:"
        self._profiles: dict[str, CrewProfile] = {}
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS crew_profiles ("
            "  agent_id TEXT PRIMARY KEY,"
            "  data TEXT NOT NULL"
            ")"
        )
        self._conn.commit()
        self._load_all()

    def _load_all(self) -> None:
        assert self._conn is not None
        rows = self._conn.execute("SELECT agent_id, data FROM crew_profiles").fetchall()
        for agent_id, data_json in rows:
            try:
                self._profiles[agent_id] = CrewProfile.from_dict(json.loads(data_json))
            except Exception as e:
                logger.warning("Failed to load profile for %s: %s", agent_id, e)

    def get(self, agent_id: str) -> CrewProfile | None:
        """Look up a crew profile by agent ID."""
        return self._profiles.get(agent_id)

    def get_or_create(self, agent_id: str, agent_type: str = "",
                      pool: str = "", **defaults: Any) -> CrewProfile:
        """Get existing profile or create a new one with defaults."""
        if agent_id in self._profiles:
            return self._profiles[agent_id]
        now = time.time()
        profile = CrewProfile(
            agent_id=agent_id,
            agent_type=agent_type,
            pool=pool,
            commissioned=now,
            last_updated=now,
            **defaults,
        )
        self._profiles[agent_id] = profile
        self._persist(agent_id)
        return profile

    def update(self, profile: CrewProfile) -> None:
        """Update and persist a profile."""
        profile.last_updated = time.time()
        self._profiles[profile.agent_id] = profile
        self._persist(profile.agent_id)

    def all_profiles(self) -> list[CrewProfile]:
        """Return all crew profiles."""
        return list(self._profiles.values())

    def by_department(self, department: str) -> list[CrewProfile]:
        """Return all profiles in a department."""
        return [p for p in self._profiles.values() if p.department == department]

    def by_rank(self, rank: Rank) -> list[CrewProfile]:
        """Return all profiles at a given rank."""
        return [p for p in self._profiles.values() if p.rank == rank]

    def _persist(self, agent_id: str) -> None:
        if self._conn is None:
            return
        profile = self._profiles.get(agent_id)
        if profile is None:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO crew_profiles (agent_id, data) VALUES (?, ?)",
            (agent_id, json.dumps(profile.to_dict())),
        )
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


class CallsignRegistry:
    """Ship's universal crew directory. Maps callsigns to agent_type and live agent_id."""

    def __init__(self) -> None:
        self._callsign_to_type: dict[str, str] = {}   # "wesley" -> "scout"
        self._type_to_callsign: dict[str, str] = {}   # "scout" -> "Wesley" (original case)
        self._type_to_profile: dict[str, dict[str, Any]] = {}  # agent_type -> {display_name, department, vision_capable}
        self._agent_registry: AgentRegistry | None = None

    def load_from_profiles(self, profiles_dir: str = "") -> None:
        """Scan all crew profile YAMLs and build the callsign index."""
        if not profiles_dir:
            profiles_dir = str(
                Path(__file__).resolve().parent.parent.parent
                / "config" / "standing_orders" / "crew_profiles"
            )
        profiles_path = Path(profiles_dir)
        if not profiles_path.is_dir():
            return

        import yaml
        for yaml_file in sorted(profiles_path.glob("*.yaml")):
            if yaml_file.stem.startswith("_"):
                continue
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            except Exception:
                logger.debug("Skipping unreadable profile", exc_info=True)
                continue
            callsign = data.get("callsign", "")
            if not callsign:
                continue
            agent_type = yaml_file.stem
            self._callsign_to_type[callsign.lower()] = agent_type
            self._type_to_callsign[agent_type] = callsign
            self._type_to_profile[agent_type] = {
                "display_name": data.get("display_name", ""),
                "department": data.get("department", ""),
                # AD-720d-2: surface vision_capable on the registry profile
                # dict so router gates can consult it without loading the
                # full CrewProfile dataclass.
                "vision_capable": bool(data.get("vision_capable", False)),
            }

    def bind_registry(self, registry: AgentRegistry) -> None:
        """Bind the live AgentRegistry for runtime resolution."""
        self._agent_registry = registry

    def resolve(self, callsign: str) -> dict[str, Any] | None:
        """Resolve a callsign to {callsign, agent_type, agent_id, display_name, department}.

        Returns None if callsign not found.
        If multiple agents share the type, picks the first live one from the registry.
        """
        agent_type = self._callsign_to_type.get(callsign.lower())
        if agent_type is None:
            return None
        profile = self._type_to_profile.get(agent_type, {})
        result: dict[str, Any] = {
            "callsign": self._type_to_callsign.get(agent_type, callsign),
            "agent_type": agent_type,
            "agent_id": None,
            "display_name": profile.get("display_name", ""),
            "department": profile.get("department", ""),
        }
        if self._agent_registry:
            agents = self._agent_registry.get_by_pool(agent_type)
            for agent in agents:
                if agent.is_alive:
                    result["agent_id"] = agent.id
                    break
        return result

    def get_callsign(self, agent_type: str) -> str:
        """Get the display callsign for an agent type. Returns empty string if none."""
        return self._type_to_callsign.get(agent_type, "")

    def all_callsigns(self) -> dict[str, str]:
        """Return {agent_type: display_callsign} snapshot for all registered callsigns."""
        return dict(self._type_to_callsign)

    @property
    def live_callsign_map(self) -> dict[str, str]:
        """Return the live {agent_type: callsign} dict (not a copy).

        Consumers holding this reference see updates from ``set_callsign``
        automatically.  Used by the decomposer so it always has the
        post-onboarding callsigns without needing a refresh call.
        """
        return self._type_to_callsign

    def set_callsign(self, agent_type: str, callsign: str) -> None:
        """Update callsign mapping after naming ceremony (AD-442)."""
        old = self._type_to_callsign.get(agent_type)
        if old:
            # Remove old reverse mapping
            self._callsign_to_type.pop(old.lower(), None)
        self._type_to_callsign[agent_type] = callsign
        self._callsign_to_type[callsign.lower()] = agent_type

    # ------------------------------------------------------------------
    # AD-514: Public API
    # ------------------------------------------------------------------

    def get_profile(self, agent_type: str) -> dict | None:
        """Return the crew profile for the given agent type, or None."""
        return self._type_to_profile.get(agent_type)

    def set_vision_capable(
        self,
        agent_id: str,
        value: bool,
        *,
        reason: str = "",
    ) -> bool:
        """AD-720d-2.1: flip ``vision_capable`` for the agent's profile.

        Resolves ``agent_id`` to the agent's ``agent_type`` via the bound
        ``AgentRegistry``; if no agent is bound or the agent_id is unknown,
        returns False. On success returns True and logs the flip at INFO
        level (audit trail). Idempotent — setting to the same value still
        returns True (the registry profile dict reflects the desired
        value; no event is suppressed).

        Reason is logged for audit; it does NOT flow into trust or Hebbian
        — this is an authorization grant, not a behavior observation.
        """
        if self._agent_registry is None:
            return False
        agent = self._agent_registry.get(agent_id)
        if agent is None:
            return False
        agent_type = agent.agent_type
        profile = self._type_to_profile.get(agent_type)
        if profile is None:
            return False
        prior = bool(profile.get("vision_capable", False))
        profile["vision_capable"] = bool(value)
        logger.info(
            "AD-720d-2.1: vision_capable flipped for agent_id=%s "
            "agent_type=%s prior=%s new=%s reason=%r",
            agent_id, agent_type, prior, bool(value), reason,
        )
        return True


def load_seed_profile(agent_type: str, profiles_dir: str = "") -> dict[str, Any]:
    """Load seed personality and identity from crew_profiles/ YAML.

    Falls back to _default.yaml if no agent-specific file exists.
    """
    if not profiles_dir:
        profiles_dir = str(
            Path(__file__).resolve().parent.parent.parent
            / "config" / "standing_orders" / "crew_profiles"
        )
    profiles_path = Path(profiles_dir)
    agent_file = profiles_path / f"{agent_type}.yaml"
    default_file = profiles_path / "_default.yaml"

    target = agent_file if agent_file.exists() else default_file
    if not target.exists():
        return {}

    import yaml
    with open(target, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


async def load_seed_profile_async(agent_type: str, profiles_dir: str = "") -> dict[str, Any]:
    """Async wrapper for load_seed_profile — runs file I/O in executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, load_seed_profile, agent_type)


def extract_callsign_mention(text: str) -> tuple[str, str] | None:
    """Extract the first @callsign mention from text (BF-009).

    Returns (callsign, remaining_text) or None if no @mention found.
    The remaining_text has the @callsign removed and is stripped.
    """
    match = re.search(r'@(\w+)', text)
    if match:
        callsign = match.group(1)
        remaining = text[:match.start()] + text[match.end():]
        remaining = re.sub(r'  +', ' ', remaining).strip()
        return (callsign, remaining)
    return None


def is_directed_mention(text: str) -> bool:
    """BF #467: distinguish 'message TO someone' from 'message ABOUT someone'.

    A directed mention starts the message (after optional whitespace) with
    ``@callsign``. Any earlier prose before the @ — even a single word —
    means the @mention is referential (broadcast about the agent), not a
    routing directive.

    Returns True when the message should be DM-routed; False when it
    should be broadcast even though it contains an @callsign.
    """
    if not text:
        return False
    stripped = text.lstrip()
    return bool(re.match(r'@\w+', stripped))


def extract_all_leading_callsign_mentions(text: str) -> tuple[list[str], str]:
    """AD-719: extract leading run of @callsign tokens.

    Walks tokens from the start of the (left-stripped) text, peeling off
    @callsign tokens until the first non-mention token is encountered.
    Returns (callsigns, remaining_message). callsigns are returned in the
    order they appeared and lower-cased to match CallsignRegistry.resolve.
    Returns ([], text) if the message does not start with @.

    Reuses the same word-character primitive as extract_callsign_mention.
    """
    if not text:
        return ([], text)
    callsigns: list[str] = []
    remaining = text.lstrip()
    while True:
        m = re.match(r'@(\w+)\s*', remaining)
        if not m:
            break
        callsigns.append(m.group(1).lower())
        remaining = remaining[m.end():]
    return (callsigns, remaining.strip())


def extract_directed_callsign(text: str) -> str | None:
    r"""AD-951: the callsign a message is DIRECTED TO at its start, or None.

    Captures Conversation-Analysis turn-allocation rule 1a ("current speaker
    selects next") for agent-to-agent hand-offs in a group chat: when an agent
    ADDRESSES a peer by callsign, that peer is selected to speak next. Matches a
    LEADING address only — mirroring is_directed_mention / BF #467, so a message
    ABOUT a peer ("I agree with Yeo's read") is NOT treated as a hand-off, only a
    message TO them:

      * "@yeo ..."   -> "yeo"   (chat-native @ form)
      * "Yeo, ..."   -> "yeo"   (vocative comma — natural speech / AD-921 voice)
      * "Yeo: ..."   -> "yeo"   (vocative colon)

    Returns the lower-cased callsign (matching CallsignRegistry.resolve) or None.
    A bare leading word with no @, comma, or colon ("Data shows ...") is NOT an
    address. Resolution to an actual thread participant happens at the call site,
    so a non-participant word (a common opener like "Well," or a non-member name)
    is harmlessly ignored there. Reuses the same @(\w+) word primitive as the
    other parsers in this module.
    """
    if not text:
        return None
    stripped = text.lstrip()
    # @ form first (directed-mention discipline: a LEADING @callsign).
    m = re.match(r'@(\w+)\b', stripped)
    if m:
        return m.group(1).lower()
    # Vocative form: a leading word immediately followed by ',' or ':'.
    m = re.match(r'(\w+)\s*[,:]', stripped)
    if m:
        return m.group(1).lower()
    return None

