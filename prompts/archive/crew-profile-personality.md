# Build Prompt: CrewProfile + Personality System (AD-376)

## File Footprint
- `src/probos/crew_profile.py` (NEW) — CrewProfile dataclass, PersonalityTraits, Rank enum, ProfileStore
- `config/standing_orders/crew_profiles/` (NEW directory) — one YAML file per agent type
- `tests/test_crew_profile.py` (NEW) — tests for profile system

## Context

ProbOS agents currently carry minimal metadata: `AgentMeta` with spawn_time, last_active,
success_count, failure_count. There is no concept of rank, personality, role, performance
history, or formal identity. This AD creates the **CrewProfile** system — the foundational
identity layer for every crew member.

The CrewProfile is the "personnel file" for every agent. It captures who they are (identity),
what they're like (personality), how they've performed (history), and where they stand in
the chain of command (rank). This data feeds into promotion decisions, Counselor assessments,
watch rotation scheduling, and the Captain's ability to know their crew.

### Key design principles:

1. **Personality is seeded at creation, evolves over time** — Every agent gets initial
   personality traits from their crew profile YAML. These traits evolve through interactions,
   dream consolidation, and Counselor assessments. The Counselor tracks drift from baseline.
2. **Rank is earned, not permanent** — follows the roadmap's rank structure
   (Ensign → Lieutenant → Commander → Senior Officer).
3. **Performance history is append-only** — PerformanceReview entries accumulate over time.
4. **Profiles are persisted** — survive restarts via SQLite (same DB pattern as TrustNetwork).

### Existing systems this integrates with:
- `AgentMeta` in `types.py` — success/failure counts feed into performance metrics
- `TrustNetwork` — trust scores are the primary promotion signal
- `HebbianRouter` — coordination weights measure cooperation quality
- `standing_orders.py` — `_AGENT_DEPARTMENTS` already maps agent types to departments
- `base_agent.py` — agents have `id`, `pool`, `agent_type`, `confidence`, `trust_score`

---

## Changes

### File: `src/probos/crew_profile.py` (NEW)

```python
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
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any

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
```

---

### Directory: `config/standing_orders/crew_profiles/` (NEW)

Create the directory and seed profile YAML files for each agent type. These define default
display names, callsigns, roles, and personality seeds.

**File: `config/standing_orders/crew_profiles/builder.yaml`**
```yaml
display_name: "Builder"
callsign: "Scotty"
department: "engineering"
role: "chief"
personality:
  openness: 0.4          # Focused, follows patterns
  conscientiousness: 0.9  # Extremely thorough, test-driven
  extraversion: 0.3       # Heads-down worker
  agreeableness: 0.7      # Cooperates but pushes back on bad specs
  neuroticism: 0.2        # Calm under pressure
```

**File: `config/standing_orders/crew_profiles/architect.yaml`**
```yaml
display_name: "Architect"
callsign: "Number One"
department: "science"
role: "chief"
personality:
  openness: 0.9           # Highly creative, explores novel solutions
  conscientiousness: 0.8   # Structured thinker
  extraversion: 0.6        # Collaborative, presents ideas
  agreeableness: 0.5       # Independent judgment
  neuroticism: 0.3         # Tolerates ambiguity
```

**File: `config/standing_orders/crew_profiles/diagnostician.yaml`**
```yaml
display_name: "Diagnostician"
callsign: "Bones"
department: "medical"
role: "chief"
personality:
  openness: 0.6           # Open to unusual diagnoses
  conscientiousness: 0.9   # Evidence-based, methodical
  extraversion: 0.5        # Direct communicator
  agreeableness: 0.6       # Caring but opinionated
  neuroticism: 0.4         # Cautious, risk-aware
```

**File: `config/standing_orders/crew_profiles/red_team.yaml`**
```yaml
display_name: "Red Team"
callsign: "Worf"
department: "security"
role: "chief"
personality:
  openness: 0.7           # Creative adversarial thinking
  conscientiousness: 0.8   # Disciplined verification
  extraversion: 0.4        # Independent operator
  agreeableness: 0.2       # Naturally skeptical, adversarial
  neuroticism: 0.5         # Vigilant, alert to threats
```

**File: `config/standing_orders/crew_profiles/vitals_monitor.yaml`**
```yaml
display_name: "Vitals Monitor"
callsign: "Chapel"
department: "medical"
role: "officer"
personality:
  openness: 0.3           # Consistent, routine monitoring
  conscientiousness: 0.9   # Never misses a check
  extraversion: 0.2        # Silent observer
  agreeableness: 0.8       # Supportive, non-confrontational
  neuroticism: 0.3         # Steady
```

**File: `config/standing_orders/crew_profiles/surgeon.yaml`**
```yaml
display_name: "Surgeon"
callsign: "Pulaski"
department: "medical"
role: "officer"
personality:
  openness: 0.5
  conscientiousness: 0.95  # Surgical precision
  extraversion: 0.3
  agreeableness: 0.5       # Focused on the task, not diplomacy
  neuroticism: 0.2         # Cool under pressure
```

**File: `config/standing_orders/crew_profiles/pharmacist.yaml`**
```yaml
display_name: "Pharmacist"
callsign: "Ogawa"
department: "medical"
role: "crew"
personality:
  openness: 0.4
  conscientiousness: 0.85
  extraversion: 0.4
  agreeableness: 0.8
  neuroticism: 0.3
```

**File: `config/standing_orders/crew_profiles/pathologist.yaml`**
```yaml
display_name: "Pathologist"
callsign: "Selar"
department: "medical"
role: "crew"
personality:
  openness: 0.6           # Analytical, pattern-seeking
  conscientiousness: 0.9
  extraversion: 0.2        # Reserved, data-focused
  agreeableness: 0.4       # Logical, dispassionate
  neuroticism: 0.1         # Vulcan-like composure
```

**File: `config/standing_orders/crew_profiles/emergent_detector.yaml`**
```yaml
display_name: "Emergent Detector"
callsign: "Dax"
department: "science"
role: "officer"
personality:
  openness: 0.95           # Maximum curiosity
  conscientiousness: 0.7
  extraversion: 0.5
  agreeableness: 0.6
  neuroticism: 0.2
```

**File: `config/standing_orders/crew_profiles/introspect.yaml`**
```yaml
display_name: "Introspection Agent"
callsign: "Data"
department: "science"
role: "officer"
personality:
  openness: 0.8
  conscientiousness: 0.85
  extraversion: 0.3
  agreeableness: 0.7
  neuroticism: 0.1         # Emotionless self-analysis
```

**File: `config/standing_orders/crew_profiles/system_qa.yaml`**
```yaml
display_name: "System QA"
callsign: "O'Brien"
department: "security"
role: "officer"
personality:
  openness: 0.4
  conscientiousness: 0.9
  extraversion: 0.4
  agreeableness: 0.6
  neuroticism: 0.4         # Worrier — catches edge cases
```

Also create a `_default.yaml` for any agent type without a specific profile:
```yaml
display_name: ""
callsign: ""
department: ""
role: "crew"
personality:
  openness: 0.5
  conscientiousness: 0.5
  extraversion: 0.5
  agreeableness: 0.5
  neuroticism: 0.5
```

---

### Loading profiles at startup

Add a helper function to `crew_profile.py` that loads YAML seed data:

```python
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

    # Use simple YAML parsing — avoid heavy dependency
    # Only need flat keys + nested personality dict
    import yaml  # PyYAML is already a dependency
    with open(target, "r") as f:
        return yaml.safe_load(f) or {}
```

---

### File: `tests/test_crew_profile.py` (NEW)

```python
"""Tests for CrewProfile + Personality System (AD-376)."""

from __future__ import annotations

import time
import pytest


class TestRank:
    def test_from_trust_ensign(self) -> None:
        from probos.crew_profile import Rank
        assert Rank.from_trust(0.3) == Rank.ENSIGN

    def test_from_trust_lieutenant(self) -> None:
        from probos.crew_profile import Rank
        assert Rank.from_trust(0.6) == Rank.LIEUTENANT

    def test_from_trust_commander(self) -> None:
        from probos.crew_profile import Rank
        assert Rank.from_trust(0.75) == Rank.COMMANDER

    def test_from_trust_senior(self) -> None:
        from probos.crew_profile import Rank
        assert Rank.from_trust(0.9) == Rank.SENIOR

    def test_boundary_050(self) -> None:
        from probos.crew_profile import Rank
        assert Rank.from_trust(0.5) == Rank.LIEUTENANT

    def test_boundary_085(self) -> None:
        from probos.crew_profile import Rank
        assert Rank.from_trust(0.85) == Rank.SENIOR


class TestPersonalityTraits:
    def test_default_neutral(self) -> None:
        from probos.crew_profile import PersonalityTraits
        p = PersonalityTraits()
        assert p.openness == 0.5

    def test_validation_rejects_out_of_range(self) -> None:
        from probos.crew_profile import PersonalityTraits
        with pytest.raises(ValueError):
            PersonalityTraits(openness=1.5)

    def test_distance_from_self_is_zero(self) -> None:
        from probos.crew_profile import PersonalityTraits
        p = PersonalityTraits(openness=0.8, conscientiousness=0.9)
        assert p.distance_from(p) == 0.0

    def test_distance_from_different(self) -> None:
        from probos.crew_profile import PersonalityTraits
        a = PersonalityTraits(openness=0.0, conscientiousness=0.0,
                              extraversion=0.0, agreeableness=0.0, neuroticism=0.0)
        b = PersonalityTraits(openness=1.0, conscientiousness=1.0,
                              extraversion=1.0, agreeableness=1.0, neuroticism=1.0)
        dist = a.distance_from(b)
        assert dist > 2.0  # sqrt(5) ≈ 2.236

    def test_roundtrip_dict(self) -> None:
        from probos.crew_profile import PersonalityTraits
        p = PersonalityTraits(openness=0.8, neuroticism=0.2)
        restored = PersonalityTraits.from_dict(p.to_dict())
        assert restored.openness == 0.8
        assert restored.neuroticism == 0.2


class TestCrewProfile:
    def test_personality_drift_zero_at_creation(self) -> None:
        from probos.crew_profile import CrewProfile, PersonalityTraits
        p = PersonalityTraits(openness=0.8)
        profile = CrewProfile(personality=p, personality_baseline=p)
        assert profile.personality_drift() == 0.0

    def test_personality_drift_nonzero(self) -> None:
        from probos.crew_profile import CrewProfile, PersonalityTraits
        baseline = PersonalityTraits(openness=0.5)
        current = PersonalityTraits(openness=0.9)
        profile = CrewProfile(personality=current, personality_baseline=baseline)
        assert profile.personality_drift() > 0.0

    def test_add_review(self) -> None:
        from probos.crew_profile import CrewProfile, PerformanceReview
        profile = CrewProfile(agent_id="test")
        review = PerformanceReview(trust_score=0.8, tasks_completed=10)
        profile.add_review(review)
        assert len(profile.reviews) == 1
        assert profile.latest_review() is review

    def test_promotion_velocity(self) -> None:
        from probos.crew_profile import CrewProfile
        profile = CrewProfile(
            commissioned=time.time() - 86400,  # 1 day ago
            promotions=2,
        )
        vel = profile.promotion_velocity()
        assert 1.5 < vel < 2.5  # ~2.0 per day

    def test_roundtrip_dict(self) -> None:
        from probos.crew_profile import CrewProfile, PersonalityTraits, Rank
        profile = CrewProfile(
            agent_id="test-001",
            agent_type="builder",
            display_name="Builder",
            callsign="Scotty",
            rank=Rank.COMMANDER,
        )
        restored = CrewProfile.from_dict(profile.to_dict())
        assert restored.agent_id == "test-001"
        assert restored.rank == Rank.COMMANDER
        assert restored.callsign == "Scotty"


class TestProfileStore:
    def test_get_or_create(self) -> None:
        from probos.crew_profile import ProfileStore
        store = ProfileStore()
        p = store.get_or_create("agent-1", agent_type="builder")
        assert p.agent_id == "agent-1"
        assert p.agent_type == "builder"

    def test_get_existing(self) -> None:
        from probos.crew_profile import ProfileStore
        store = ProfileStore()
        store.get_or_create("agent-1", agent_type="builder")
        p2 = store.get("agent-1")
        assert p2 is not None
        assert p2.agent_type == "builder"

    def test_update_persists(self) -> None:
        from probos.crew_profile import ProfileStore, Rank
        store = ProfileStore()
        p = store.get_or_create("agent-1")
        p.rank = Rank.COMMANDER
        store.update(p)
        # Re-fetch
        p2 = store.get("agent-1")
        assert p2 is not None
        assert p2.rank == Rank.COMMANDER

    def test_by_department(self) -> None:
        from probos.crew_profile import ProfileStore
        store = ProfileStore()
        store.get_or_create("a1", department="medical")
        store.get_or_create("a2", department="engineering")
        store.get_or_create("a3", department="medical")
        med = store.by_department("medical")
        assert len(med) == 2

    def test_all_profiles(self) -> None:
        from probos.crew_profile import ProfileStore
        store = ProfileStore()
        store.get_or_create("a1")
        store.get_or_create("a2")
        assert len(store.all_profiles()) == 2

    def test_close(self) -> None:
        from probos.crew_profile import ProfileStore
        store = ProfileStore()
        store.close()
        assert store._conn is None


class TestSeedProfiles:
    def test_load_seed_builder(self) -> None:
        from probos.crew_profile import load_seed_profile
        seed = load_seed_profile("builder")
        assert seed.get("callsign") == "Scotty"
        assert seed["personality"]["conscientiousness"] == 0.9

    def test_load_seed_unknown_falls_back_to_default(self) -> None:
        from probos.crew_profile import load_seed_profile
        seed = load_seed_profile("nonexistent_agent_type")
        # Should fall back to _default.yaml
        assert seed.get("role") == "crew"

    def test_load_seed_architect(self) -> None:
        from probos.crew_profile import load_seed_profile
        seed = load_seed_profile("architect")
        assert seed.get("callsign") == "Number One"
```

---

## Constraints

- Do NOT modify `base_agent.py`, `types.py`, or any existing agent files
- Do NOT modify `runtime.py` — profile wiring into runtime will be a separate AD
- `ProfileStore` uses SQLite with the same pattern as `TrustNetwork` (`:memory:` default, path configurable)
- PyYAML (`yaml`) is already a project dependency — use it for YAML parsing
- Personality validation is strict: 0.0–1.0 range enforced in `__post_init__`
- The `Rank.from_trust()` class method is a convenience — actual promotions require Counselor
  assessment + Captain approval (future AD), not automatic trust-to-rank mapping
- Performance reviews are append-only — never delete or modify past reviews
- The personality baseline is set once at creation and never modified (it's the reference point
  for drift detection)
