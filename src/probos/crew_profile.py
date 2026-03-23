"""CrewProfile — formal identity, personality, and performance records for every agent (AD-376).

Every ProbOS agent is a crew member with a personnel file. This module provides:
- CrewProfile: identity, rank, department, personality traits, specialization
- PersonalityTraits: Big Five personality dimensions, seeded and evolvable
- Rank enum: Ensign → Lieutenant → Commander → Senior Officer
- PerformanceReview: timestamped performance snapshot
- ProfileStore: persistence and lookup
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, TYPE_CHECKING

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
        if trust_score >= 0.85:
            return cls.SENIOR
        elif trust_score >= 0.7:
            return cls.COMMANDER
        elif trust_score >= 0.5:
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

    # Rank
    rank: Rank = Rank.ENSIGN
    rank_since: float = 0.0        # timestamp of last rank change
    promotions: int = 0
    demotions: int = 0

    # Personality
    personality: PersonalityTraits = field(default_factory=PersonalityTraits)
    personality_baseline: PersonalityTraits = field(default_factory=PersonalityTraits)

    # Performance
    reviews: list[PerformanceReview] = field(default_factory=list)

    # Timestamps
    commissioned: float = 0.0      # when profile was created
    last_updated: float = 0.0

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
            "rank": self.rank.value,
            "rank_since": self.rank_since,
            "promotions": self.promotions,
            "demotions": self.demotions,
            "personality": self.personality.to_dict(),
            "personality_baseline": self.personality_baseline.to_dict(),
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
        self._type_to_profile: dict[str, dict[str, str]] = {}  # agent_type -> {display_name, department}
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
                with open(yaml_file, "r") as f:
                    data = yaml.safe_load(f) or {}
            except Exception:
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

    def all_callsigns(self) -> list[str]:
        """List all registered callsigns (display case). For tab-completion."""
        return list(self._type_to_callsign.values())


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
    with open(target, "r") as f:
        return yaml.safe_load(f) or {}


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
