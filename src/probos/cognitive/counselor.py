"""CounselorAgent — cognitive wellness monitoring for the crew (AD-378, AD-503).

Bridge-level CognitiveAgent. Monitors cognitive health, maintains psychological
profiles, detects drift from baseline, advises the Captain on crew wellness
and promotion fitness.

AD-503 additions: autonomous metric gathering, SQLite-backed profile persistence,
periodic wellness sweeps, reactive event handling, initiative engine wiring.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.config import (
    COUNSELOR_CONFIDENCE_LOW,
    COUNSELOR_TRUST_DRIFT_CONCERN,
    COUNSELOR_TRUST_PROMOTION,
    COUNSELOR_WELLNESS_FIT,
    COUNSELOR_WELLNESS_YELLOW,
    TRUST_DEFAULT,
)
from probos.events import EventType
from probos.types import IntentDescriptor

if TYPE_CHECKING:
    from probos.protocols import ConnectionFactory, DatabaseConnection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cognitive Profile — the Counselor's assessment record per agent
# ---------------------------------------------------------------------------

@dataclass
class CognitiveBaseline:
    """Snapshot of an agent's cognitive metrics at time of baselining."""
    trust_score: float = TRUST_DEFAULT
    confidence: float = 0.8
    hebbian_avg: float = 0.0
    success_rate: float = 0.0
    captured_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trust_score": self.trust_score,
            "confidence": self.confidence,
            "hebbian_avg": self.hebbian_avg,
            "success_rate": self.success_rate,
            "captured_at": self.captured_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CognitiveBaseline":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CounselorAssessment:
    """A timestamped cognitive assessment — the Counselor's professional opinion."""
    timestamp: float = 0.0
    agent_id: str = ""
    trigger: str = "manual"  # AD-503: "manual", "sweep", "event", "api"
    # Current metrics at time of assessment
    trust_score: float = 0.0
    confidence: float = 0.0
    hebbian_avg: float = 0.0
    success_rate: float = 0.0
    personality_drift: float = 0.0
    # Computed drift from baseline
    trust_drift: float = 0.0        # current - baseline
    confidence_drift: float = 0.0
    hebbian_drift: float = 0.0
    # Counselor's assessment
    wellness_score: float = 1.0     # 0.0 = critical, 1.0 = excellent
    concerns: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    fit_for_duty: bool = True
    fit_for_promotion: bool = False
    notes: str = ""
    # AD-506b: Tier credit indicators for this assessment
    tier_credit: str = ""  # "self_correction" | "peer_catch" | "" (none)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "agent_id": self.agent_id,
            "trigger": self.trigger,
            "trust_score": self.trust_score,
            "confidence": self.confidence,
            "hebbian_avg": self.hebbian_avg,
            "success_rate": self.success_rate,
            "personality_drift": self.personality_drift,
            "trust_drift": self.trust_drift,
            "confidence_drift": self.confidence_drift,
            "hebbian_drift": self.hebbian_drift,
            "wellness_score": self.wellness_score,
            "concerns": self.concerns,
            "recommendations": self.recommendations,
            "fit_for_duty": self.fit_for_duty,
            "fit_for_promotion": self.fit_for_promotion,
            "notes": self.notes,
            "tier_credit": self.tier_credit,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CounselorAssessment":
        result = cls()
        for k, v in data.items():
            if k in cls.__dataclass_fields__:
                setattr(result, k, v)
        return result


@dataclass
class CognitiveProfile:
    """Psychological profile maintained by the Counselor for each agent.

    This is the agent's "psych file" — distinct from CrewProfile (personnel file).
    The Counselor writes these; the Captain reads them.
    """
    agent_id: str = ""
    agent_type: str = ""
    baseline: CognitiveBaseline = field(default_factory=CognitiveBaseline)
    assessments: list[CounselorAssessment] = field(default_factory=list)
    created_at: float = 0.0
    last_assessed: float = 0.0
    alert_level: str = "green"      # "green", "yellow", "red"
    # AD-506b: Tier credits — positive cognitive health signals
    self_corrections: int = 0     # Times agent self-corrected from amber
    peer_catches: int = 0         # Times peer repetition was detected for this agent
    last_self_correction: float = 0.0  # Timestamp of most recent self-correction
    last_peer_catch: float = 0.0       # Timestamp of most recent peer catch
    # AD-552: Notebook self-repetition tracking
    notebook_repetitions: int = 0
    last_notebook_repetition: float = 0.0
    # AD-541c: Retrieval practice tracking
    retrieval_concerns: int = 0
    last_retrieval_accuracy: float = 0.0
    # AD-541d: Guided Reminiscence
    memory_integrity_score: float = 1.0     # Rolling accuracy (0.0-1.0, starts presumed good)
    confabulation_rate: float = 0.0         # Rolling ratio of confabulated recalls
    last_reminiscence: float = 0.0          # Timestamp of last reminiscence session
    reminiscence_sessions: int = 0          # Total sessions completed
    # AD-567c: Anchor quality
    anchor_quality: float = 0.0             # Mean anchor confidence from latest AnchorProfile
    weakest_anchor_dimension: str = ""      # For targeted metacognitive coaching

    def add_assessment(self, assessment: CounselorAssessment) -> None:
        """Append an assessment and update alert level."""
        self.assessments.append(assessment)
        self.last_assessed = assessment.timestamp
        # Update alert level based on latest assessment
        if not assessment.fit_for_duty:
            self.alert_level = "red"
        elif assessment.wellness_score < COUNSELOR_WELLNESS_YELLOW or len(assessment.concerns) >= 3:
            self.alert_level = "yellow"
        else:
            self.alert_level = "green"

        # AD-506b: Tier credit influence — sustained self-correction demonstrates cognitive health
        if assessment.tier_credit == "self_correction":
            self.self_corrections += 1
            self.last_self_correction = assessment.timestamp
            # Frequent self-correction is a positive signal — don't let it
            # keep agent at yellow if they're consistently self-regulating
            if self.alert_level == "yellow" and self.self_corrections >= 3:
                recent_credits = sum(
                    1 for a in self.assessments[-3:]
                    if a.tier_credit == "self_correction"
                )
                if recent_credits >= 2:
                    self.alert_level = "green"
        elif assessment.tier_credit == "peer_catch":
            self.peer_catches += 1
            self.last_peer_catch = assessment.timestamp
        elif assessment.tier_credit == "notebook_repetition":
            self.notebook_repetitions += 1
            self.last_notebook_repetition = assessment.timestamp

    def latest_assessment(self) -> CounselorAssessment | None:
        return self.assessments[-1] if self.assessments else None

    def drift_trend(self, metric: str = "trust_drift", window: int = 5) -> float:
        """Average drift over last N assessments for a given metric."""
        recent = self.assessments[-window:] if self.assessments else []
        if not recent:
            return 0.0
        values = [getattr(a, metric, 0.0) for a in recent]
        return sum(values) / len(values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "baseline": self.baseline.to_dict(),
            "assessments": [a.to_dict() for a in self.assessments],
            "created_at": self.created_at,
            "last_assessed": self.last_assessed,
            "alert_level": self.alert_level,
            "self_corrections": self.self_corrections,
            "peer_catches": self.peer_catches,
            "last_self_correction": self.last_self_correction,
            "last_peer_catch": self.last_peer_catch,
            "notebook_repetitions": self.notebook_repetitions,
            "last_notebook_repetition": self.last_notebook_repetition,
            "retrieval_concerns": self.retrieval_concerns,
            "last_retrieval_accuracy": self.last_retrieval_accuracy,
            "memory_integrity_score": self.memory_integrity_score,
            "confabulation_rate": self.confabulation_rate,
            "last_reminiscence": self.last_reminiscence,
            "reminiscence_sessions": self.reminiscence_sessions,
            "anchor_quality": self.anchor_quality,
            "weakest_anchor_dimension": self.weakest_anchor_dimension,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CognitiveProfile":
        profile = cls(
            agent_id=data.get("agent_id", ""),
            agent_type=data.get("agent_type", ""),
            created_at=data.get("created_at", 0.0),
            last_assessed=data.get("last_assessed", 0.0),
            alert_level=data.get("alert_level", "green"),
            self_corrections=data.get("self_corrections", 0),
            peer_catches=data.get("peer_catches", 0),
            last_self_correction=data.get("last_self_correction", 0.0),
            last_peer_catch=data.get("last_peer_catch", 0.0),
            notebook_repetitions=data.get("notebook_repetitions", 0),
            last_notebook_repetition=data.get("last_notebook_repetition", 0.0),
            retrieval_concerns=data.get("retrieval_concerns", 0),
            last_retrieval_accuracy=data.get("last_retrieval_accuracy", 0.0),
            memory_integrity_score=data.get("memory_integrity_score", 1.0),
            confabulation_rate=data.get("confabulation_rate", 0.0),
            last_reminiscence=data.get("last_reminiscence", 0.0),
            reminiscence_sessions=data.get("reminiscence_sessions", 0),
            anchor_quality=data.get("anchor_quality", 0.0),
            weakest_anchor_dimension=data.get("weakest_anchor_dimension", ""),
        )
        if "baseline" in data:
            profile.baseline = CognitiveBaseline.from_dict(data["baseline"])
        if "assessments" in data:
            profile.assessments = [CounselorAssessment.from_dict(a) for a in data["assessments"]]
        return profile


# ---------------------------------------------------------------------------
# CounselorProfileStore — SQLite-backed persistence (AD-503)
# ---------------------------------------------------------------------------

_COUNSELOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS cognitive_profiles (
    agent_id TEXT PRIMARY KEY,
    agent_type TEXT NOT NULL DEFAULT '',
    profile_json TEXT NOT NULL,
    alert_level TEXT NOT NULL DEFAULT 'green',
    last_assessed REAL NOT NULL DEFAULT 0.0,
    created_at REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    trigger TEXT NOT NULL DEFAULT 'manual',
    wellness_score REAL NOT NULL DEFAULT 1.0,
    fit_for_duty INTEGER NOT NULL DEFAULT 1,
    assessment_json TEXT NOT NULL,
    FOREIGN KEY (agent_id) REFERENCES cognitive_profiles(agent_id)
);

CREATE INDEX IF NOT EXISTS idx_assessments_agent_ts
    ON assessments(agent_id, timestamp DESC);
"""


class CounselorProfileStore:
    """SQLite-backed persistence for cognitive profiles and assessments.

    Uses the ConnectionFactory protocol for cloud-ready storage.
    """

    def __init__(
        self,
        data_dir: str | Path,
        connection_factory: "ConnectionFactory | None" = None,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._db: DatabaseConnection | None = None
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory

    async def start(self) -> None:
        """Open DB and ensure schema exists."""
        self._db = await self._connection_factory.connect(  # type: ignore[union-attr]
            str(self._data_dir / "counselor.db")
        )
        await self._db.executescript(_COUNSELOR_SCHEMA)
        await self._db.commit()
        # AD-506b: Schema migration — add tier credit columns
        for stmt in [
            "ALTER TABLE cognitive_profiles ADD COLUMN self_corrections INTEGER DEFAULT 0",
            "ALTER TABLE cognitive_profiles ADD COLUMN peer_catches INTEGER DEFAULT 0",
            "ALTER TABLE cognitive_profiles ADD COLUMN last_self_correction REAL DEFAULT 0.0",
            "ALTER TABLE cognitive_profiles ADD COLUMN last_peer_catch REAL DEFAULT 0.0",
            "ALTER TABLE assessments ADD COLUMN tier_credit TEXT DEFAULT ''",
            # AD-552: Notebook self-repetition tracking
            "ALTER TABLE cognitive_profiles ADD COLUMN notebook_repetitions INTEGER DEFAULT 0",
            "ALTER TABLE cognitive_profiles ADD COLUMN last_notebook_repetition REAL DEFAULT 0.0",
            # AD-541c fix + AD-541d migration
            "ALTER TABLE cognitive_profiles ADD COLUMN retrieval_concerns INTEGER DEFAULT 0",
            "ALTER TABLE cognitive_profiles ADD COLUMN last_retrieval_accuracy REAL DEFAULT 0.0",
            "ALTER TABLE cognitive_profiles ADD COLUMN memory_integrity_score REAL DEFAULT 1.0",
            "ALTER TABLE cognitive_profiles ADD COLUMN confabulation_rate REAL DEFAULT 0.0",
            "ALTER TABLE cognitive_profiles ADD COLUMN last_reminiscence REAL DEFAULT 0.0",
            "ALTER TABLE cognitive_profiles ADD COLUMN reminiscence_sessions INTEGER DEFAULT 0",
        ]:
            try:
                await self._db.execute(stmt)
            except Exception:
                pass  # Column already exists
        await self._db.commit()

    async def stop(self) -> None:
        """Close DB connection."""
        if self._db:
            try:
                await self._db.close()
            except Exception:
                logger.debug("Counselor profile store close failed", exc_info=True)
            self._db = None

    async def save_profile(self, profile: CognitiveProfile) -> None:
        """Upsert a cognitive profile."""
        if not self._db:
            return
        await self._db.execute(
            """INSERT INTO cognitive_profiles
               (agent_id, agent_type, profile_json, alert_level, last_assessed, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(agent_id) DO UPDATE SET
                 agent_type = excluded.agent_type,
                 profile_json = excluded.profile_json,
                 alert_level = excluded.alert_level,
                 last_assessed = excluded.last_assessed""",
            (
                profile.agent_id,
                profile.agent_type,
                json.dumps(profile.to_dict()),
                profile.alert_level,
                profile.last_assessed,
                profile.created_at,
            ),
        )
        await self._db.commit()

    async def load_profile(self, agent_id: str) -> CognitiveProfile | None:
        """Load a single profile from DB."""
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT profile_json FROM cognitive_profiles WHERE agent_id = ?",
            (agent_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return CognitiveProfile.from_dict(json.loads(row[0]))

    async def load_all_profiles(self) -> dict[str, CognitiveProfile]:
        """Load all profiles from DB."""
        if not self._db:
            return {}
        cursor = await self._db.execute(
            "SELECT agent_id, profile_json FROM cognitive_profiles"
        )
        rows = await cursor.fetchall()
        result: dict[str, CognitiveProfile] = {}
        for agent_id, profile_json in rows:
            try:
                result[agent_id] = CognitiveProfile.from_dict(json.loads(profile_json))
            except Exception:
                logger.debug("Failed to load profile for %s", agent_id, exc_info=True)
        return result

    async def save_assessment(self, assessment: CounselorAssessment) -> None:
        """Persist an individual assessment row."""
        if not self._db:
            return
        await self._db.execute(
            """INSERT INTO assessments
               (agent_id, timestamp, trigger, wellness_score, fit_for_duty, assessment_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                assessment.agent_id,
                assessment.timestamp,
                assessment.trigger,
                assessment.wellness_score,
                1 if assessment.fit_for_duty else 0,
                json.dumps(assessment.to_dict()),
            ),
        )
        await self._db.commit()

    async def get_assessment_history(
        self, agent_id: str, limit: int = 20
    ) -> list[CounselorAssessment]:
        """Get recent assessments for an agent, newest first."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT assessment_json FROM assessments WHERE agent_id = ? ORDER BY timestamp DESC LIMIT ?",
            (agent_id, limit),
        )
        rows = await cursor.fetchall()
        return [CounselorAssessment.from_dict(json.loads(r[0])) for r in rows]

    async def get_crew_summary(self) -> list[dict[str, Any]]:
        """Summary of all profiles for the REST API."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            """SELECT agent_id, agent_type, alert_level, last_assessed
               FROM cognitive_profiles ORDER BY alert_level DESC, last_assessed DESC"""
        )
        rows = await cursor.fetchall()
        return [
            {
                "agent_id": r[0],
                "agent_type": r[1],
                "alert_level": r[2],
                "last_assessed": r[3],
            }
            for r in rows
        ]


# ---------------------------------------------------------------------------
# CounselorAgent
# ---------------------------------------------------------------------------

class CounselorAgent(CognitiveAgent):
    """Ship's Counselor — monitors cognitive wellness of the crew.

    Bridge-level agent. Monitors confidence trajectories, Hebbian drift,
    relationship health, personality drift, and burnout signals. Maintains
    CognitiveProfiles. Advises the Captain.

    AD-503: Autonomous metric gathering, persistence, event-driven assessments.
    """

    agent_type = "counselor"
    tier = "domain"
    _handled_intents = {"counselor_assess", "counselor_wellness_report",
                        "counselor_promotion_fitness"}
    intent_descriptors = [
        IntentDescriptor(
            name="counselor_assess",
            params={"agent_id": "ID of the agent to assess"},
            description="Run a cognitive assessment on a specific crew member",
        ),
        IntentDescriptor(
            name="counselor_wellness_report",
            params={},
            description="Generate a full crew cognitive wellness report",
        ),
        IntentDescriptor(
            name="counselor_promotion_fitness",
            params={"agent_id": "ID of the agent being considered for promotion"},
            description="Assess an agent's fitness for promotion",
        ),
    ]

    instructions = (
        "You are the Ship's Counselor — a Bridge-level officer responsible for "
        "the cognitive wellness of every crew member.\n\n"
        "You monitor cognitive health, not operational health. Medical handles whether "
        "an agent is running. You handle whether it is thinking well, learning the "
        "right patterns, and cooperating effectively.\n\n"
        "Your role:\n"
        "- Assess cognitive metrics: trust trajectories, confidence, Hebbian weights, "
        "personality drift, success rates\n"
        "- Compare current metrics against each agent's baseline to detect drift\n"
        "- Distinguish emergence (positive drift) from degradation (negative drift)\n"
        "- Provide actionable recommendations: dream cycles, Hebbian resets, workload "
        "rebalancing, closer observation\n"
        "- Assess promotion fitness when asked: is this agent cognitively ready for "
        "increased responsibility?\n"
        "- Flag concerns to the Captain — you advise, you do not command\n\n"
        "When assessing an agent, you will receive their current metrics and baseline. "
        "Return a JSON object with: wellness_score (0.0–1.0), concerns (list of strings), "
        "recommendations (list of strings), fit_for_duty (bool), fit_for_promotion (bool), "
        "and notes (string with your professional assessment)."
    )

    def __init__(self, **kwargs: Any) -> None:
        # AD-503: Extract counselor-specific kwargs before super().__init__
        self._profile_store: CounselorProfileStore | None = kwargs.pop("profile_store", None)
        kwargs.setdefault("pool", "bridge")
        super().__init__(**kwargs)
        self._cognitive_profiles: dict[str, CognitiveProfile] = {}
        # AD-503: Runtime references wired during initialize()
        self._trust_network: Any = None
        self._hebbian_router: Any = None
        self._registry: Any = None
        self._crew_profiles: Any = None  # CrewProfileManager
        self._episodic_memory: Any = None
        self._emit_event_fn: Any = None
        self._add_event_listener_fn: Any = None
        self._ward_room_router: Any = None  # AD-495
        self._ward_room: Any = None          # AD-505: WardRoomService for DM creation
        self._directive_store: Any = None     # AD-505: for COUNSELOR_GUIDANCE directives
        self._dream_scheduler: Any = None     # AD-505: for forced dream cycles
        self._proactive_loop: Any = None      # AD-505: for cooldown adjustment
        self._dm_cooldowns: dict[str, float] = {}  # AD-505: agent_id -> monotonic timestamp of last DM
        self._intervention_targets: set[str] = set()  # AD-506a: agents with forced dream pending
        # AD-541d: Guided Reminiscence
        self._reminiscence_engine: Any = None  # Set via set_reminiscence_engine()
        self._reminiscence_cooldowns: dict[str, float] = {}
        self._REMINISCENCE_COOLDOWN_SECONDS: int = 7200  # 2 hours default
        self._reminiscence_concern_threshold: int = 3
        self._confabulation_alert_threshold: float = 0.3

    # -- AD-503: Initialization and event wiring --

    async def initialize(
        self,
        *,
        trust_network: Any = None,
        hebbian_router: Any = None,
        registry: Any = None,
        crew_profiles: Any = None,
        episodic_memory: Any = None,
        emit_event_fn: Any = None,
        add_event_listener_fn: Any = None,
        ward_room_router: Any = None,  # AD-495: Ward Room posting
        ward_room: Any = None,           # AD-505
        directive_store: Any = None,      # AD-505
        dream_scheduler: Any = None,      # AD-505
        proactive_loop: Any = None,       # AD-505
    ) -> None:
        """Post-construction initialization: load persisted profiles, wire events.

        Called after the counselor agent is created and wired into the runtime.
        """
        self._trust_network = trust_network
        self._hebbian_router = hebbian_router
        self._registry = registry
        self._crew_profiles = crew_profiles
        self._episodic_memory = episodic_memory
        self._emit_event_fn = emit_event_fn
        self._add_event_listener_fn = add_event_listener_fn
        self._ward_room_router = ward_room_router
        self._ward_room = ward_room
        self._directive_store = directive_store
        self._dream_scheduler = dream_scheduler
        self._proactive_loop = proactive_loop

        # Load persisted profiles
        if self._profile_store:
            try:
                self._cognitive_profiles = await self._profile_store.load_all_profiles()
                logger.info(
                    "AD-503: Counselor loaded %d persisted profiles",
                    len(self._cognitive_profiles),
                )
            except Exception:
                logger.debug("Failed to load counselor profiles", exc_info=True)

        # Subscribe to events (type-filtered)
        if self._add_event_listener_fn:
            self._add_event_listener_fn(
                self._on_event_async,
                event_types=[
                    EventType.TRUST_UPDATE,
                    EventType.CIRCUIT_BREAKER_TRIP,
                    EventType.DREAM_COMPLETE,
                    EventType.SELF_MONITORING_CONCERN,  # AD-506a
                    EventType.ZONE_RECOVERY,            # AD-506b
                    EventType.PEER_REPETITION_DETECTED, # AD-506b
                    EventType.NOTEBOOK_SELF_REPETITION, # AD-552
                    EventType.GAP_IDENTIFIED,           # AD-539
                    EventType.TRUST_CASCADE_WARNING,    # AD-558
                    EventType.GROUPTHINK_WARNING,       # AD-557
                    EventType.FRAGMENTATION_WARNING,     # AD-557
                    EventType.RETRIEVAL_PRACTICE_CONCERN, # AD-541c
                    EventType.QUALIFICATION_DRIFT_DETECTED, # AD-566c
                    EventType.CASCADE_CONFABULATION_DETECTED, # AD-567f
                ],
            )

    # -- Profile management --

    def get_profile(self, agent_id: str) -> CognitiveProfile | None:
        """Get the cognitive profile for an agent."""
        return self._cognitive_profiles.get(agent_id)

    def get_or_create_profile(self, agent_id: str,
                              agent_type: str = "") -> CognitiveProfile:
        """Get or create a cognitive profile."""
        if agent_id in self._cognitive_profiles:
            return self._cognitive_profiles[agent_id]
        now = time.time()
        profile = CognitiveProfile(
            agent_id=agent_id,
            agent_type=agent_type,
            created_at=now,
        )
        self._cognitive_profiles[agent_id] = profile
        return profile

    def set_baseline(self, agent_id: str, baseline: CognitiveBaseline) -> None:
        """Set or update the cognitive baseline for an agent."""
        profile = self.get_or_create_profile(agent_id)
        profile.baseline = baseline
        profile.baseline.captured_at = time.time()

    def all_profiles(self) -> list[CognitiveProfile]:
        """Return all cognitive profiles."""
        return list(self._cognitive_profiles.values())

    def agents_at_alert(self, level: str = "yellow") -> list[CognitiveProfile]:
        """Find agents at or above a given alert level."""
        levels = {"green": 0, "yellow": 1, "red": 2}
        threshold = levels.get(level, 0)
        return [p for p in self._cognitive_profiles.values()
                if levels.get(p.alert_level, 0) >= threshold]

    # -- AD-503: Autonomous metric gathering --

    def _gather_agent_metrics(self, agent_id: str) -> dict[str, float]:
        """Pull metrics from runtime services for an agent.

        Gracefully degrades — returns sensible defaults when services unavailable.
        """
        metrics: dict[str, float] = {
            "trust_score": TRUST_DEFAULT,
            "confidence": 0.8,
            "hebbian_avg": 0.0,
            "success_rate": 0.0,
            "personality_drift": 0.0,
        }

        # Trust score
        if self._trust_network:
            try:
                score = self._trust_network.score(agent_id)
                if score is not None:
                    metrics["trust_score"] = score
            except Exception:
                logger.debug("Failed to get trust for %s", agent_id, exc_info=True)

        # Hebbian average weight
        if self._hebbian_router:
            try:
                weights = self._hebbian_router.get_weights_for(agent_id)
                if weights:
                    metrics["hebbian_avg"] = sum(weights.values()) / len(weights)
            except Exception:
                logger.debug("Failed to get Hebbian for %s", agent_id, exc_info=True)

        # Agent meta (confidence, success_rate)
        if self._registry:
            try:
                meta = self._registry.get(agent_id)
                if meta:
                    metrics["confidence"] = getattr(meta, "confidence", 0.8)
                    metrics["success_rate"] = getattr(meta, "success_rate", 0.0)
            except Exception:
                logger.debug("Failed to get meta for %s", agent_id, exc_info=True)

        # Personality drift from CrewProfile
        if self._crew_profiles:
            try:
                cp = self._crew_profiles.get_profile(agent_id)
                if cp:
                    metrics["personality_drift"] = getattr(cp, "personality_drift", 0.0)
            except Exception:
                logger.debug("Failed to get crew profile for %s", agent_id, exc_info=True)

        return metrics

    # -- AD-503: Wellness sweep --

    async def _run_wellness_sweep(self, max_agents: int = 50) -> list[CounselorAssessment]:
        """Iterate crew agents, gather metrics, assess, persist.

        Skips non-crew agents and the counselor itself.
        """
        results: list[CounselorAssessment] = []
        if not self._registry:
            return results

        agents_assessed = 0
        try:
            all_agents = list(self._registry.all())
        except Exception:
            logger.debug("Failed to list agents for sweep", exc_info=True)
            return results

        for meta in all_agents:
            if agents_assessed >= max_agents:
                break
            agent_id = getattr(meta, "id", None) or getattr(meta, "agent_id", "")
            if not agent_id or agent_id == self.id:
                continue
            # Skip non-crew (infrastructure/utility)
            tier = getattr(meta, "tier", "")
            if tier and tier not in ("domain", "crew"):
                continue

            metrics = self._gather_agent_metrics(agent_id)
            assessment = self.assess_agent(
                agent_id,
                current_trust=metrics["trust_score"],
                current_confidence=metrics["confidence"],
                hebbian_avg=metrics["hebbian_avg"],
                success_rate=metrics["success_rate"],
                personality_drift=metrics["personality_drift"],
                trigger="sweep",
            )
            results.append(assessment)
            agents_assessed += 1

            # AD-541d: Memory health as concern dimension (read-only, no new sessions)
            profile = self._cognitive_profiles.get(agent_id)
            if profile and profile.confabulation_rate >= self._confabulation_alert_threshold:
                assessment.concerns.append(
                    f"Memory integrity concern: confabulation rate {profile.confabulation_rate:.0%}"
                )
            if profile and profile.retrieval_concerns >= self._reminiscence_concern_threshold:
                assessment.concerns.append(
                    f"Retrieval concern: {profile.retrieval_concerns} episodes at risk"
                )

            # Persist profile + assessment
            if self._profile_store:
                profile = self.get_profile(agent_id)
                if profile:
                    try:
                        await self._profile_store.save_profile(profile)
                        await self._profile_store.save_assessment(assessment)
                    except Exception:
                        logger.debug("Failed to persist assessment for %s", agent_id, exc_info=True)

            # AD-505: Therapeutic DM for concerning sweep results
            sweep_callsign = getattr(meta, 'callsign', getattr(meta, 'agent_type', agent_id))
            await self._maybe_send_therapeutic_dm(
                agent_id, sweep_callsign, assessment, trigger="sweep"
            )

            # Emit event
            if self._emit_event_fn:
                try:
                    self._emit_event_fn(EventType.COUNSELOR_ASSESSMENT, {
                        "agent_id": agent_id,
                        "wellness_score": assessment.wellness_score,
                        "alert_level": self._cognitive_profiles.get(agent_id, CognitiveProfile()).alert_level,
                        "fit_for_duty": assessment.fit_for_duty,
                        "concerns_count": len(assessment.concerns),
                    })
                except Exception:
                    logger.debug("Failed to emit counselor assessment event", exc_info=True)

        return results

    # -- AD-503: Event handlers --

    async def _on_event_async(self, event: dict[str, Any]) -> None:
        """Route incoming events to specific handlers."""
        event_type = event.get("type", "")
        data = event.get("data", {})
        try:
            if event_type == EventType.TRUST_UPDATE.value:
                await self._on_trust_update(data)
            elif event_type == EventType.CIRCUIT_BREAKER_TRIP.value:
                await self._on_circuit_breaker_trip(data)
            elif event_type == EventType.DREAM_COMPLETE.value:
                await self._on_dream_complete(data)
            elif event_type == EventType.SELF_MONITORING_CONCERN.value:
                await self._on_self_monitoring_concern(data)
            elif event_type == EventType.ZONE_RECOVERY.value:
                await self._on_zone_recovery(data)
            elif event_type == EventType.PEER_REPETITION_DETECTED.value:
                await self._on_peer_repetition_detected(data)
            elif event_type == EventType.NOTEBOOK_SELF_REPETITION.value:
                await self._on_notebook_self_repetition(data)
            elif event_type == EventType.GAP_IDENTIFIED.value:
                await self._on_gap_identified(data)
            elif event_type == EventType.TRUST_CASCADE_WARNING.value:
                await self._on_trust_cascade(data)
            elif event_type == EventType.GROUPTHINK_WARNING.value:
                await self._on_groupthink_warning(data)
            elif event_type == EventType.FRAGMENTATION_WARNING.value:
                await self._on_fragmentation_warning(data)
            elif event_type == EventType.RETRIEVAL_PRACTICE_CONCERN.value:
                await self._on_retrieval_practice_concern(data)
            elif event_type == EventType.QUALIFICATION_DRIFT_DETECTED.value:
                await self._on_qualification_drift(data)
            elif event_type == EventType.CASCADE_CONFABULATION_DETECTED.value:
                await self._on_cascade_confabulation(data)
        except Exception:
            logger.debug("Counselor event handler failed for %s", event_type, exc_info=True)

    async def _on_dream_complete(self, data: dict[str, Any]) -> None:
        """AD-506a: Re-assess agents after dream completion.

        If the Counselor previously forced a dream for an agent (AD-505),
        check whether the dream improved their cognitive state.
        """
        if not hasattr(self, '_intervention_targets') or not self._intervention_targets:
            return

        for agent_id in list(self._intervention_targets):
            try:
                metrics = self._gather_agent_metrics(agent_id)
                assessment = self.assess_agent(
                    agent_id=agent_id,
                    current_trust=metrics["trust_score"],
                    current_confidence=metrics["confidence"],
                    hebbian_avg=metrics["hebbian_avg"],
                    success_rate=metrics["success_rate"],
                    personality_drift=metrics["personality_drift"],
                    trigger="post_dream",
                )
                await self._save_profile_and_assessment(agent_id, assessment)

                if assessment.wellness_score >= COUNSELOR_WELLNESS_YELLOW:
                    logger.info(
                        "AD-506a: Post-dream improvement for %s (wellness=%.2f)",
                        agent_id[:8], assessment.wellness_score,
                    )
                    self._intervention_targets.discard(agent_id)
            except Exception:
                logger.debug("Post-dream re-assessment failed for %s", agent_id[:8], exc_info=True)

        # AD-541d: Post-dream reminiscence trigger for agents with retrieval concerns
        dream_report = data.get("dream_report", data)
        retrieval_results = dream_report.get("retrieval_results", []) if isinstance(dream_report, dict) else []
        if retrieval_results and self._reminiscence_engine:
            # Collect unique agents with concerns
            concern_agents: set[str] = set()
            for result in retrieval_results:
                aid = result.get("agent_id", "") if isinstance(result, dict) else getattr(result, "agent_id", "")
                if aid:
                    profile = self._cognitive_profiles.get(aid)
                    if profile and profile.retrieval_concerns >= self._reminiscence_concern_threshold:
                        concern_agents.add(aid)
            for aid in concern_agents:
                await self._initiate_reminiscence_session(aid, trigger="post_dream")

    async def _on_self_monitoring_concern(self, data: dict[str, Any]) -> None:
        """AD-506a: Handle amber zone detection — lightweight monitoring response."""
        agent_id = data.get("agent_id", "")
        if not agent_id or agent_id == self.id:
            return

        # AD-576: Suppress clinical intervention during infrastructure brownout
        if data.get("infrastructure_correlated"):
            logger.info(
                "AD-576: Suppressing self-monitoring concern for %s — infrastructure-correlated",
                data.get("agent_callsign", agent_id[:8]),
            )
            return

        callsign = data.get("agent_callsign", agent_id[:8])
        logger.info("AD-506a: Amber zone concern for %s", callsign)

        # Gather metrics and run lightweight assessment
        metrics = self._gather_agent_metrics(agent_id)
        assessment = self.assess_agent(
            agent_id=agent_id,
            current_trust=metrics["trust_score"],
            current_confidence=metrics["confidence"],
            hebbian_avg=metrics["hebbian_avg"],
            success_rate=metrics["success_rate"],
            personality_drift=metrics["personality_drift"],
            trigger="amber_zone",
        )

        # Persist to profile
        await self._save_profile_and_assessment(agent_id, assessment)

        # No DM, no intervention — amber is informational for the Counselor.
        # She tracks the pattern. If it escalates to red, _on_circuit_breaker_trip handles it.

    async def _on_circuit_breaker_trip(self, data: dict[str, Any]) -> None:
        """Handle circuit breaker trip with trip-aware clinical assessment (AD-495)."""
        agent_id = data.get("agent_id", "")
        if not agent_id or agent_id == self.id:
            return

        trip_count = data.get("trip_count", 1)
        cooldown_seconds = data.get("cooldown_seconds", 900.0)
        trip_reason = data.get("trip_reason", "unknown")
        callsign = data.get("callsign", agent_id)
        zone = data.get("zone", "red")  # AD-506a

        # Gather current metrics
        metrics = self._gather_agent_metrics(agent_id)

        # Run assessment with circuit_breaker trigger
        assessment = self.assess_agent(
            agent_id,
            current_trust=metrics["trust_score"],
            current_confidence=metrics["confidence"],
            hebbian_avg=metrics["hebbian_avg"],
            success_rate=metrics["success_rate"],
            personality_drift=metrics["personality_drift"],
            trigger="circuit_breaker",
        )

        # Classify severity and enrich assessment
        severity, recommendation = self._classify_trip_severity(
            trip_count, trip_reason, assessment, zone=zone,
        )

        # Add trip-specific concerns
        if trip_count == 1:
            assessment.concerns.append(
                f"First circuit breaker trip (reason: {trip_reason})"
            )
        elif trip_count <= 3:
            assessment.concerns.append(
                f"Repeated circuit breaker trip #{trip_count} (reason: {trip_reason})"
            )
        else:
            assessment.concerns.append(
                f"Frequent circuit breaker trips ({trip_count} total, reason: {trip_reason}) — pattern requires attention"
            )

        # Add trip-specific recommendation
        if recommendation:
            assessment.recommendations.append(recommendation)

        # Add clinical note
        assessment.notes = (
            f"Circuit breaker trip #{trip_count}. "
            f"Reason: {trip_reason}. "
            f"Cooldown: {cooldown_seconds:.0f}s. "
            f"Severity classification: {severity}."
        )

        # Persist
        await self._save_profile_and_assessment(agent_id, assessment)

        # Alert bridge (always for circuit breaker trips)
        self._alert_bridge(agent_id, assessment)

        # Post to Ward Room (AD-495)
        await self._post_assessment_to_ward_room(
            agent_id, callsign, assessment, severity, trip_count, trip_reason,
        )

        # AD-505: Therapeutic DM if severity warrants
        if severity in ("concern", "intervention", "escalate"):
            await self._maybe_send_therapeutic_dm(
                agent_id, callsign, assessment, trigger="circuit_breaker"
            )

        # AD-505: Mechanical interventions for high severity
        if severity in ("intervention", "escalate"):
            await self._apply_intervention(agent_id, callsign, assessment, severity)

        # Emit counselor assessment event
        if self._emit_event_fn:
            try:
                self._emit_event_fn(EventType.COUNSELOR_ASSESSMENT, {
                    "agent_id": agent_id,
                    "wellness_score": assessment.wellness_score,
                    "alert_level": self._cognitive_profiles.get(agent_id, CognitiveProfile()).alert_level,
                    "fit_for_duty": assessment.fit_for_duty,
                    "concerns_count": len(assessment.concerns),
                })
            except Exception:
                logger.debug("Failed to emit counselor assessment event", exc_info=True)

    async def _on_zone_recovery(self, data: dict[str, Any]) -> None:
        """AD-506b: Credit agent for self-correction when zone improves."""
        agent_id = data.get("agent_id", "")
        old_zone = data.get("old_zone", "")
        new_zone = data.get("new_zone", "")

        if not agent_id or agent_id == self.id:
            return

        # Only credit for amber->green recovery (amber self-correction)
        # red->amber decay is system-regulated (circuit breaker cooldown), not agent-initiated
        if old_zone != "amber" or new_zone != "green":
            return

        logger.info("AD-506b: Self-correction credit for %s (amber->green)", agent_id[:8])

        # Run lightweight assessment with positive credit
        metrics = self._gather_agent_metrics(agent_id)
        assessment = self.assess_agent(
            agent_id=agent_id,
            current_trust=metrics["trust_score"],
            current_confidence=metrics["confidence"],
            hebbian_avg=metrics["hebbian_avg"],
            success_rate=metrics["success_rate"],
            personality_drift=metrics["personality_drift"],
            trigger="self_correction",
        )
        assessment.tier_credit = "self_correction"

        # Persist — this updates the profile's self_corrections counter via add_assessment()
        profile = self.get_or_create_profile(agent_id)
        profile.add_assessment(assessment)
        await self._save_profile_and_assessment(agent_id, assessment)

    async def _on_peer_repetition_detected(self, data: dict[str, Any]) -> None:
        """AD-506b: Track peer repetition for Counselor monitoring.

        This is informational — the Counselor notes the echo pattern.
        No intervention: the post still went through.
        """
        author_id = data.get("author_id", "")
        callsign = data.get("author_callsign", author_id[:8])
        match_count = data.get("match_count", 0)

        if not author_id or author_id == self.id:
            return

        logger.info(
            "AD-506b: Peer repetition detected for %s (%d matches)",
            callsign, match_count,
        )

        # Update profile with peer catch count
        profile = self.get_or_create_profile(author_id)
        profile.peer_catches += 1
        profile.last_peer_catch = time.time()

        # Lightweight assessment with peer catch tag
        metrics = self._gather_agent_metrics(author_id)
        assessment = self.assess_agent(
            agent_id=author_id,
            current_trust=metrics["trust_score"],
            current_confidence=metrics["confidence"],
            hebbian_avg=metrics["hebbian_avg"],
            success_rate=metrics["success_rate"],
            personality_drift=metrics["personality_drift"],
            trigger="peer_repetition",
        )
        assessment.tier_credit = "peer_catch"
        await self._save_profile_and_assessment(author_id, assessment)

    async def _on_notebook_self_repetition(self, data: dict[str, Any]) -> None:
        """AD-552: Track notebook self-repetition for Counselor monitoring."""
        agent_id = data.get("agent_id", "")
        callsign = data.get("agent_callsign", agent_id[:8])
        topic = data.get("topic_slug", "unknown")
        revision = data.get("revision", 0)
        suppressed = data.get("suppressed", False)

        if not agent_id or agent_id == self.id:
            return

        logger.info(
            "AD-552: Notebook self-repetition for %s on %s (revision=%d, suppressed=%s)",
            callsign, topic, revision, suppressed,
        )

        # Update profile
        profile = self.get_or_create_profile(agent_id)
        profile.notebook_repetitions += 1
        profile.last_notebook_repetition = time.time()

        # Lightweight assessment with notebook repetition tag
        metrics = self._gather_agent_metrics(agent_id)
        assessment = self.assess_agent(
            agent_id=agent_id,
            current_trust=metrics["trust_score"],
            current_confidence=metrics["confidence"],
            hebbian_avg=metrics["hebbian_avg"],
            success_rate=metrics["success_rate"],
            personality_drift=metrics["personality_drift"],
            trigger="notebook_self_repetition",
        )
        assessment.tier_credit = "notebook_repetition"
        await self._save_profile_and_assessment(agent_id, assessment)

        # Therapeutic DM — only if not suppressed (suppression is its own feedback)
        if not suppressed:
            message = (
                f"@{callsign}, I've noticed you've documented **{topic}** "
                f"{revision} times recently. Your earlier entry already covers "
                f"the core observations. Consider updating it with genuinely "
                f"new findings rather than writing a fresh entry — your notebook "
                f"will be clearer and more useful for the crew."
            )
            await self._send_therapeutic_dm(agent_id, callsign, message)

    async def _on_gap_identified(self, data: dict[str, Any]) -> None:
        """AD-539: Track knowledge gaps for Counselor monitoring.

        When a gap is identified during dream cycle, update the agent's
        cognitive profile and optionally notify for high/critical gaps.
        """
        agent_id = data.get("agent_id", "")
        gap_type = data.get("gap_type", "knowledge")
        description = data.get("description", "")
        priority = data.get("priority", "low")
        intent_types = data.get("affected_intent_types", [])

        if not agent_id or agent_id == self.id:
            return

        intent_label = ", ".join(intent_types[:3]) if intent_types else "unknown"
        logger.info(
            "AD-539: Counselor noted gap for %s: %s (type=%s, priority=%s)",
            agent_id[:8], description[:80], gap_type, priority,
        )

        # Track gaps on profile via a gap_concerns list (lightweight)
        profile = self.get_or_create_profile(agent_id)
        if not hasattr(profile, "_gap_concerns"):
            profile._gap_concerns = []
        concern = f"Knowledge gap in {intent_label}: {description[:120]} (priority: {priority})"
        profile._gap_concerns.append(concern)

        # High/critical gaps warrant assessment + therapeutic DM
        if priority in ("high", "critical"):
            callsign = self._resolve_agent_callsign(agent_id)
            metrics = self._gather_agent_metrics(agent_id)
            assessment = self.assess_agent(
                agent_id=agent_id,
                current_trust=metrics["trust_score"],
                current_confidence=metrics["confidence"],
                hebbian_avg=metrics["hebbian_avg"],
                success_rate=metrics["success_rate"],
                personality_drift=metrics["personality_drift"],
                trigger="gap_identified",
            )
            await self._save_profile_and_assessment(agent_id, assessment)
            await self._maybe_send_therapeutic_dm(
                agent_id, callsign, assessment, trigger="gap_identified"
            )

    async def _on_qualification_drift(self, data: dict[str, Any]) -> None:
        """AD-566c/567c: Handle qualification drift detection events.

        Drift-type-aware handling (AD-567c):
        - "specialization" at critical → log only (healthy divergence)
        - "concerning" at warning+ → trigger assessment + therapeutic DM
        - "unclassified" → existing behavior (critical=assess, warning=log)
        """
        agent_id = data.get("agent_id", "")
        severity = data.get("severity", "")
        test_name = data.get("test_name", "")
        drift_type = data.get("drift_type", "unclassified")

        if not agent_id or agent_id == self.id:
            return

        callsign = self._resolve_agent_callsign(agent_id)

        # AD-567c: Specialization drift — log but don't intervene
        if drift_type == "specialization":
            logger.info(
                "AD-567c: Specialization drift for %s on %s (z=%.2f) — healthy divergence, no intervention",
                callsign, test_name, data.get("z_score", 0.0),
            )
            return

        # AD-567c: Concerning drift — intervene even at warning level
        if drift_type == "concerning" or severity == "critical":
            logger.info(
                "AD-567c: %s drift for %s on %s (z=%.2f, type=%s)",
                severity.title(), callsign, test_name,
                data.get("z_score", 0.0), drift_type,
            )
            metrics = self._gather_agent_metrics(agent_id)
            trigger_label = (
                f"qualification_drift_{drift_type}"
                if drift_type != "unclassified"
                else f"qualification_drift_{severity}"
            )
            assessment = self.assess_agent(
                agent_id=agent_id,
                current_trust=metrics["trust_score"],
                current_confidence=metrics["confidence"],
                hebbian_avg=metrics["hebbian_avg"],
                success_rate=metrics["success_rate"],
                personality_drift=metrics["personality_drift"],
                trigger=trigger_label,
            )
            await self._save_profile_and_assessment(agent_id, assessment)
            await self._maybe_send_therapeutic_dm(
                agent_id, callsign, assessment, trigger="qualification_drift"
            )
        else:
            logger.info(
                "AD-566c: Warning qualification drift for %s on %s (z=%.2f)",
                callsign, test_name, data.get("z_score", 0.0),
            )

    async def _on_cascade_confabulation(self, data: dict[str, Any]) -> None:
        """AD-567f: Handle cascade confabulation detection events.

        On high risk: DM affected agents with a non-judgmental verification prompt.
        On medium risk: log for wellness context.
        """
        risk_level = data.get("risk_level", "")
        affected = data.get("affected_agents", [])
        source = data.get("source_agent", "")
        detail = data.get("detail", "")

        logger.info(
            "AD-567f: Cascade confabulation %s — source=%s, affected=%s",
            risk_level, source, affected,
        )

        if risk_level == "high":
            message = (
                "I noticed several crew members are discussing a claim that may not "
                "have independent verification. Could you each check your own observations "
                "and anchors before building further analysis on this?"
            )
            for agent_callsign in affected:
                # Resolve agent_id from callsign for DM
                agent_id = self._resolve_agent_id_from_callsign(agent_callsign)
                if agent_id and agent_id != self.id:
                    await self._send_therapeutic_dm(agent_id, agent_callsign, message)

    def _resolve_agent_id_from_callsign(self, callsign: str) -> str | None:
        """Best-effort resolve agent_id from callsign using registry."""
        if hasattr(self, '_registry') and self._registry:
            for agent in self._registry.values():
                if getattr(agent, 'callsign', None) == callsign:
                    return getattr(agent, 'id', None)
        return None

    async def _on_trust_update(self, data: dict[str, Any]) -> None:
        """React to significant trust changes — re-assess the agent."""
        agent_id = data.get("agent_id", "")
        if not agent_id or agent_id == self.id:
            return
        new_score = data.get("new_score", 0.0)
        profile = self.get_profile(agent_id)
        if not profile:
            return
        delta = abs(new_score - profile.baseline.trust_score)
        # Only react to significant changes (configurable via counselor config)
        if delta < 0.15:
            return
        metrics = self._gather_agent_metrics(agent_id)
        assessment = self.assess_agent(
            agent_id,
            current_trust=metrics["trust_score"],
            current_confidence=metrics["confidence"],
            hebbian_avg=metrics["hebbian_avg"],
            success_rate=metrics["success_rate"],
            personality_drift=metrics["personality_drift"],
            trigger="trust_update",  # AD-495: specific trigger value
        )
        await self._save_profile_and_assessment(agent_id, assessment)
        # Alert bridge on red
        if not assessment.fit_for_duty:
            self._alert_bridge(agent_id, assessment)

        # AD-505: Therapeutic DM for significant trust changes
        if not assessment.fit_for_duty or assessment.wellness_score < COUNSELOR_WELLNESS_YELLOW:
            callsign = self._resolve_agent_callsign(agent_id)
            await self._maybe_send_therapeutic_dm(
                agent_id, callsign, assessment, trigger="trust_update"
            )

    async def _on_trust_cascade(self, data: dict[str, Any]) -> None:
        """AD-558: Respond to trust cascade warning — run ship-wide wellness sweep."""
        agents = data.get("anomalous_agents", [])
        depts = data.get("departments_affected", [])
        dampening = data.get("global_dampening_factor", 0.5)
        cooldown = data.get("cooldown_seconds", 600.0)
        logger.warning(
            "AD-558: Trust cascade warning — %d agents, %d departments, "
            "dampening=%.2f, cooldown=%.0fs",
            len(agents), len(depts), dampening, cooldown,
        )
        # Rate-limit: one sweep per cascade cooldown period
        last_cascade = getattr(self, "_last_cascade_sweep", 0.0)
        now = time.time()
        if now - last_cascade < cooldown:
            return
        self._last_cascade_sweep = now
        # Run wellness sweep across affected agents
        for agent_id in agents:
            if agent_id == self.id:
                continue
            try:
                metrics = self._gather_agent_metrics(agent_id)
                assessment = self.assess_agent(
                    agent_id,
                    current_trust=metrics["trust_score"],
                    current_confidence=metrics["confidence"],
                    hebbian_avg=metrics["hebbian_avg"],
                    success_rate=metrics["success_rate"],
                    personality_drift=metrics["personality_drift"],
                    trigger="trust_cascade",
                )
                await self._save_profile_and_assessment(agent_id, assessment)
                if not assessment.fit_for_duty:
                    self._alert_bridge(agent_id, assessment)
                    callsign = self._resolve_agent_callsign(agent_id)
                    await self._maybe_send_therapeutic_dm(
                        agent_id, callsign, assessment, trigger="trust_cascade"
                    )
            except Exception:
                logger.debug("Cascade sweep failed for %s", agent_id, exc_info=True)

    async def _on_groupthink_warning(self, data: dict[str, Any]) -> None:
        """AD-557: Respond to groupthink risk — redundancy dominates synergy."""
        redundancy_ratio = data.get("redundancy_ratio", 0.0)
        top_pairs = data.get("top_synergy_pairs", [])
        logger.warning(
            "AD-557: Groupthink warning — redundancy_ratio=%.3f, "
            "agents may be echoing rather than complementing",
            redundancy_ratio,
        )

    async def _on_fragmentation_warning(self, data: dict[str, Any]) -> None:
        """AD-557: Respond to fragmentation risk — synergy near zero."""
        synergy_ratio = data.get("synergy_ratio", 0.0)
        pairs_analyzed = data.get("pairs_analyzed", 0)
        logger.warning(
            "AD-557: Fragmentation warning — synergy_ratio=%.3f across %d pairs, "
            "agents may not be building on each other's contributions",
            synergy_ratio, pairs_analyzed,
        )
        """Handle circuit breaker trip with trip-aware clinical assessment (AD-495)."""
        agent_id = data.get("agent_id", "")
        if not agent_id or agent_id == self.id:
            return

        trip_count = data.get("trip_count", 1)
        cooldown_seconds = data.get("cooldown_seconds", 900.0)
        trip_reason = data.get("trip_reason", "unknown")
        callsign = data.get("callsign", agent_id)
        zone = data.get("zone", "red")  # AD-506a

        # Gather current metrics
        metrics = self._gather_agent_metrics(agent_id)

        # Run assessment with circuit_breaker trigger
        assessment = self.assess_agent(
            agent_id,
            current_trust=metrics["trust_score"],
            current_confidence=metrics["confidence"],
            hebbian_avg=metrics["hebbian_avg"],
            success_rate=metrics["success_rate"],
            personality_drift=metrics["personality_drift"],
            trigger="circuit_breaker",
        )

        # Classify severity and enrich assessment
        severity, recommendation = self._classify_trip_severity(
            trip_count, trip_reason, assessment, zone=zone,
        )

        # Add trip-specific concerns
        if trip_count == 1:
            assessment.concerns.append(
                f"First circuit breaker trip (reason: {trip_reason})"
            )
        elif trip_count <= 3:
            assessment.concerns.append(
                f"Repeated circuit breaker trip #{trip_count} (reason: {trip_reason})"
            )
        else:
            assessment.concerns.append(
                f"Frequent circuit breaker trips ({trip_count} total, reason: {trip_reason}) — pattern requires attention"
            )

        # Add trip-specific recommendation
        if recommendation:
            assessment.recommendations.append(recommendation)

        # Add clinical note
        assessment.notes = (
            f"Circuit breaker trip #{trip_count}. "
            f"Reason: {trip_reason}. "
            f"Cooldown: {cooldown_seconds:.0f}s. "
            f"Severity classification: {severity}."
        )

        # Persist
        await self._save_profile_and_assessment(agent_id, assessment)

        # Alert bridge (always for circuit breaker trips)
        self._alert_bridge(agent_id, assessment)

        # Post to Ward Room (AD-495)
        await self._post_assessment_to_ward_room(
            agent_id, callsign, assessment, severity, trip_count, trip_reason,
        )

        # AD-505: Therapeutic DM if severity warrants
        if severity in ("concern", "intervention", "escalate"):
            await self._maybe_send_therapeutic_dm(
                agent_id, callsign, assessment, trigger="circuit_breaker"
            )

        # AD-505: Mechanical interventions for high severity
        if severity in ("intervention", "escalate"):
            await self._apply_intervention(agent_id, callsign, assessment, severity)

        # Emit counselor assessment event
        if self._emit_event_fn:
            try:
                self._emit_event_fn(EventType.COUNSELOR_ASSESSMENT, {
                    "agent_id": agent_id,
                    "wellness_score": assessment.wellness_score,
                    "alert_level": self._cognitive_profiles.get(agent_id, CognitiveProfile()).alert_level,
                    "fit_for_duty": assessment.fit_for_duty,
                    "concerns_count": len(assessment.concerns),
                })
            except Exception:
                logger.debug("Failed to emit counselor assessment event", exc_info=True)

        logger.info(
            "Circuit breaker assessment: %s trip #%d severity=%s fit_for_duty=%s",
            callsign, trip_count, severity, assessment.fit_for_duty,
        )

    async def _on_retrieval_practice_concern(self, data: dict[str, Any]) -> None:
        """AD-541c/d: Handle retrieval practice concern — agent struggling to recall episodes.

        Updates CognitiveProfile with retrieval stats, persists to SQLite,
        and triggers Guided Reminiscence when episodes_at_risk >= threshold.
        """
        agent_id = data.get("agent_id", "")
        episodes_at_risk = data.get("episodes_at_risk", 0)
        avg_accuracy = data.get("avg_recall_accuracy", 0.0)
        if not agent_id:
            return
        logger.info(
            "Counselor: Retrieval practice concern for %s — %d episodes at risk (avg accuracy=%.2f)",
            agent_id[:8], episodes_at_risk, avg_accuracy,
        )
        # Update and persist profile
        profile = await self._get_or_create_profile(agent_id)
        profile.retrieval_concerns = episodes_at_risk
        profile.last_retrieval_accuracy = avg_accuracy
        if self._profile_store:
            try:
                await self._profile_store.save_profile(profile)
            except Exception:
                logger.debug("Failed to persist retrieval concern profile", exc_info=True)

        # AD-541d: Trigger Guided Reminiscence when concern threshold is met
        if episodes_at_risk >= self._reminiscence_concern_threshold:
            await self._initiate_reminiscence_session(
                agent_id, trigger="retrieval_concern",
            )

    def _classify_trip_severity(
        self,
        trip_count: int,
        trip_reason: str,
        assessment: CounselorAssessment,
        zone: str = "red",
    ) -> tuple[str, str]:
        """Classify trip severity and generate recommendation.

        Returns (severity, recommendation) tuple.
        Severity levels: "monitor", "concern", "intervention", "escalate".
        AD-506a: Zone context enriches classification.
        """
        # AD-506a: Critical zone → automatic escalation
        if zone == "critical":
            return "escalate", (
                "Critical zone — Captain review required. "
                "Multiple pattern loops in short window."
            )

        if not assessment.fit_for_duty:
            return "escalate", (
                "Agent not fit for duty. Recommend Captain review and "
                "extended mandatory cooldown until Counselor clears for return."
            )

        # Compute base severity from trip count
        if trip_count >= 4:
            base_severity = "intervention"
            base_recommendation = (
                "Frequent trips indicate persistent cognitive pattern. "
                "Recommend forced dream cycle for consolidation and "
                "attention redirection to different problem domain."
            )
        elif trip_count >= 2:
            base_severity = "concern"
            base_recommendation = (
                "Repeated trips suggest unresolved cognitive fixation. "
                "Monitor closely. Consider attention redirection if pattern continues."
            )
        elif trip_reason == "rumination":
            base_severity = "concern"
            base_recommendation = (
                "First trip due to content repetition. Agent may be fixated "
                "on unresolved concern. Standard cooldown should suffice."
            )
        else:
            base_severity = "monitor"
            base_recommendation = (
                "First circuit breaker trip. Standard cooldown in effect. "
                "No immediate intervention required."
            )

        # AD-506a: Amber zone bump — agent was warned but still tripped
        if zone == "amber":
            severity_order = ["monitor", "concern", "intervention", "escalate"]
            idx = severity_order.index(base_severity)
            if idx < len(severity_order) - 1:
                bumped = severity_order[idx + 1]
                return bumped, (
                    f"{base_recommendation} "
                    "Severity raised: agent was in amber (warned) before trip."
                )

        return base_severity, base_recommendation

    async def _save_profile_and_assessment(
        self, agent_id: str, assessment: CounselorAssessment,
    ) -> None:
        """Persist profile and assessment to store (DRY helper, AD-495)."""
        profile = self._cognitive_profiles.get(agent_id)
        if profile and self._profile_store:
            try:
                await self._profile_store.save_profile(profile)
                await self._profile_store.save_assessment(assessment)
            except Exception:
                logger.debug(
                    "Failed to persist counselor profile for %s",
                    agent_id, exc_info=True,
                )

    async def _post_assessment_to_ward_room(
        self,
        agent_id: str,
        callsign: str,
        assessment: CounselorAssessment,
        severity: str,
        trip_count: int,
        trip_reason: str,
    ) -> None:
        """Post circuit breaker assessment to Ward Room via BridgeAlert (AD-495)."""
        if not self._ward_room_router:
            return

        from probos.bridge_alerts import AlertSeverity, BridgeAlert

        # Map internal severity to AlertSeverity
        if severity == "escalate":
            alert_severity = AlertSeverity.ALERT
        elif severity in ("intervention", "concern"):
            alert_severity = AlertSeverity.ADVISORY
        else:
            alert_severity = AlertSeverity.INFO

        # Build clinical detail
        concerns_text = "; ".join(assessment.concerns) if assessment.concerns else "None"
        recs_text = "; ".join(assessment.recommendations) if assessment.recommendations else "Standard cooldown"

        detail = (
            f"**Agent:** {callsign}\n"
            f"**Trip:** #{trip_count} ({trip_reason})\n"
            f"**Wellness:** {assessment.wellness_score:.2f}\n"
            f"**Fit for Duty:** {'Yes' if assessment.fit_for_duty else 'NO'}\n"
            f"**Concerns:** {concerns_text}\n"
            f"**Recommendations:** {recs_text}"
        )

        alert = BridgeAlert(
            id=f"cb-assess-{agent_id}-{int(assessment.timestamp)}",
            severity=alert_severity,
            source="counselor",
            alert_type="circuit_breaker_assessment",
            title=f"Circuit Breaker Assessment: {callsign}",
            detail=detail,
            department="medical",
            dedup_key=f"cb-assess-{agent_id}",
            related_agent_id=agent_id,
        )

        try:
            await self._ward_room_router.deliver_bridge_alert(alert)
        except Exception:
            logger.debug(
                "Failed to post assessment to Ward Room for %s",
                agent_id, exc_info=True,
            )

    def _alert_bridge(self, agent_id: str, assessment: CounselorAssessment) -> None:
        """Emit a bridge alert for a concerning assessment."""
        if self._emit_event_fn:
            try:
                self._emit_event_fn(EventType.BRIDGE_ALERT, {
                    "source": "counselor",
                    "severity": "red" if not assessment.fit_for_duty else "yellow",
                    "agent_id": agent_id,
                    "message": (
                        f"Counselor alert: {agent_id} wellness={assessment.wellness_score:.2f}, "
                        f"concerns={len(assessment.concerns)}, fit_for_duty={assessment.fit_for_duty}"
                    ),
                })
            except Exception:
                logger.debug("Failed to emit bridge alert", exc_info=True)

    # -- AD-505: Therapeutic intervention capabilities --

    DM_COOLDOWN_SECONDS = 3600  # 1 hour between DMs to same agent
    MAX_ACTIVE_DIRECTIVES_PER_AGENT = 3
    DIRECTIVE_DEFAULT_EXPIRY_HOURS = 24

    async def _send_therapeutic_dm(
        self,
        agent_id: str,
        callsign: str,
        message: str,
    ) -> bool:
        """Send a 1:1 therapeutic DM to an agent. Rate-limited to 1 per agent per hour."""
        if not self._ward_room:
            return False

        import time as _time
        now = _time.monotonic()
        last_dm = self._dm_cooldowns.get(agent_id, 0.0)
        if now - last_dm < self.DM_COOLDOWN_SECONDS:
            return False

        try:
            channel = await self._ward_room.get_or_create_dm_channel(
                agent_a_id=self.id,
                agent_b_id=agent_id,
                callsign_a=self.callsign,
                callsign_b=callsign,
            )

            await self._ward_room.create_thread(
                channel_id=channel.id,
                author_id=self.id,
                title=f"[Counselor check-in with @{callsign}]",
                body=message,
                author_callsign=self.callsign,
                thread_mode="discuss",
            )

            self._dm_cooldowns[agent_id] = now
            logger.info("AD-505: Sent therapeutic DM to %s", callsign)
            return True

        except Exception:
            logger.warning("AD-505: Failed to send therapeutic DM to %s", callsign, exc_info=True)
            return False

    def _build_therapeutic_message(
        self,
        callsign: str,
        assessment: CounselorAssessment,
        trigger: str,
        **kwargs: Any,
    ) -> str:
        """Build a therapeutic DM message from assessment data."""
        parts = [f"@{callsign}, I wanted to check in with you.\n"]

        if trigger == "circuit_breaker":
            zone = kwargs.get("zone", "red")
            if zone == "critical":
                parts.append(
                    "This is a repeated circuit breaker activation, and I want you to know "
                    "I take that seriously. Repeated pattern loops are a sign that something "
                    "genuinely needs processing differently — not that you're failing.\n"
                )
            elif zone == "amber":
                parts.append(
                    "I noticed your output similarity was rising — I believe you saw the amber "
                    "warning too. The fact that the circuit breaker still activated suggests "
                    "the pattern may be harder to break than it appears from the inside.\n"
                )
            else:
                parts.append(
                    "I noticed your circuit breaker was activated, which usually means "
                    "you've been focusing intensely on a particular topic. That kind of "
                    "dedication is valuable, but it can also mean something feels unresolved.\n"
                )
        elif trigger == "sweep":
            parts.append(
                "During my routine wellness review, I noticed some patterns in your "
                "recent activity that I wanted to discuss with you.\n"
            )
        elif trigger == "trust_update":
            parts.append(
                "I noticed a significant change in your trust dynamics recently "
                "and wanted to check how you're doing.\n"
            )

        if assessment.concerns:
            parts.append("Specifically, I'm noticing:\n")
            for concern in assessment.concerns[:3]:
                parts.append(f"- {concern}\n")

        if assessment.recommendations:
            parts.append("\nMy suggestions:\n")
            for rec in assessment.recommendations[:3]:
                parts.append(f"- {rec}\n")

        parts.append(
            "\nIf there's something you keep thinking about, consider writing it to "
            "your notebook — sometimes getting a thought down helps release it from "
            "active focus. I'm here if you want to discuss further."
        )

        return "".join(parts)

    async def _maybe_send_therapeutic_dm(
        self,
        agent_id: str,
        callsign: str,
        assessment: CounselorAssessment,
        trigger: str,
    ) -> None:
        """Send a therapeutic DM if the assessment warrants it."""
        if assessment.fit_for_duty and assessment.wellness_score >= COUNSELOR_WELLNESS_YELLOW:
            return
        message = self._build_therapeutic_message(callsign, assessment, trigger)
        await self._send_therapeutic_dm(agent_id, callsign, message)

    def _resolve_agent_callsign(self, agent_id: str) -> str:
        """Resolve another agent's callsign from registry."""
        if self._registry:
            agent = self._registry.get(agent_id)
            if agent:
                return getattr(agent, 'callsign', agent.agent_type)
        return agent_id[:8]

    # -- AD-541d: Guided Reminiscence integration --

    def set_reminiscence_engine(self, engine: Any) -> None:
        """Wire the guided reminiscence engine (AD-541d)."""
        self._reminiscence_engine = engine

    def configure_reminiscence(
        self,
        *,
        cooldown_hours: float = 2.0,
        concern_threshold: int = 3,
        confabulation_alert: float = 0.3,
    ) -> None:
        """Configure reminiscence thresholds from config (AD-541d)."""
        self._REMINISCENCE_COOLDOWN_SECONDS = int(cooldown_hours * 3600)
        self._reminiscence_concern_threshold = concern_threshold
        self._confabulation_alert_threshold = confabulation_alert

    async def _get_or_create_profile(self, agent_id: str) -> "CognitiveProfile":
        """Get existing profile or create new one (async-friendly wrapper)."""
        return self.get_or_create_profile(agent_id)

    async def _initiate_reminiscence_session(self, agent_id: str, trigger: str = "concern") -> None:
        """Initiate a guided reminiscence session for an agent with memory concerns."""
        if not self._reminiscence_engine:
            return

        callsign = self._resolve_agent_callsign(agent_id)

        # Rate limit: one session per agent per cooldown period
        last = self._reminiscence_cooldowns.get(agent_id, 0.0)
        if (time.monotonic() - last) < self._REMINISCENCE_COOLDOWN_SECONDS:
            return

        try:
            result = await self._reminiscence_engine.run_session(agent_id)
        except Exception:
            logger.debug("AD-541d: Reminiscence session failed for %s", agent_id[:8], exc_info=True)
            return

        if result.episodes_tested == 0:
            return  # No episodes to test

        self._reminiscence_cooldowns[agent_id] = time.monotonic()

        # Update CognitiveProfile
        profile = await self._get_or_create_profile(agent_id)
        profile.memory_integrity_score = result.overall_accuracy
        profile.confabulation_rate = result.confabulation_rate
        profile.last_reminiscence = time.time()
        profile.reminiscence_sessions += 1

        if self._profile_store:
            try:
                await self._profile_store.save_profile(profile)
            except Exception:
                logger.debug("AD-541d: Profile save failed", exc_info=True)

        # Send therapeutic DM
        if result.therapeutic_message:
            await self._send_therapeutic_dm(agent_id, callsign, result.therapeutic_message)

        # Emit event
        if self._emit_event_fn:
            self._emit_event_fn("reminiscence_session_complete", {
                "agent_id": agent_id,
                "trigger": trigger,
                "episodes_tested": result.episodes_tested,
                "overall_accuracy": result.overall_accuracy,
                "confabulation_rate": result.confabulation_rate,
                "accurate_count": result.accurate_count,
                "confabulated_count": result.confabulated_count,
                "contaminated_count": result.contaminated_count,
            })

        # Confabulation rate alarm → amber alert
        if result.confabulation_rate >= self._confabulation_alert_threshold:
            profile.alert_level = "amber"
            if self._profile_store:
                try:
                    await self._profile_store.save_profile(profile)
                except Exception:
                    logger.debug("AD-541d: Alert level save failed", exc_info=True)

        logger.info(
            "AD-541d: Reminiscence session for %s — %d tested, accuracy=%.2f, confab=%.2f",
            callsign, result.episodes_tested, result.overall_accuracy, result.confabulation_rate,
        )

    async def _post_recommendation_to_ward_room(
        self,
        agent_id: str,
        callsign: str,
        assessment: CounselorAssessment,
        actions_taken: list[str],
    ) -> None:
        """Post a structured recommendation to the Ward Room for Captain visibility."""
        if not self._ward_room_router:
            return

        from probos.bridge_alerts import AlertSeverity, BridgeAlert
        import time as _time

        detail_lines = [f"**Agent:** @{callsign}"]
        detail_lines.append(f"**Wellness:** {assessment.wellness_score:.2f}")
        detail_lines.append(f"**Fit for duty:** {'Yes' if assessment.fit_for_duty else 'No'}")

        if assessment.concerns:
            detail_lines.append("\n**Concerns:**")
            for c in assessment.concerns:
                detail_lines.append(f"- {c}")

        if actions_taken:
            detail_lines.append("\n**Actions taken:**")
            for a in actions_taken:
                detail_lines.append(f"- {a}")

        if assessment.recommendations:
            detail_lines.append("\n**Further recommendations (pending Captain review):**")
            for r in assessment.recommendations:
                detail_lines.append(f"- {r}")

        severity = AlertSeverity.ALERT if not assessment.fit_for_duty else AlertSeverity.ADVISORY

        alert = BridgeAlert(
            id=f"counselor-rec-{agent_id}-{int(_time.time())}",
            severity=severity,
            source="counselor",
            alert_type="counselor_recommendation",
            title=f"Counselor Recommendation: @{callsign}",
            detail="\n".join(detail_lines),
            department="medical",
            dedup_key=f"counselor-rec-{agent_id}",
            related_agent_id=agent_id,
        )

        try:
            await self._ward_room_router.deliver_bridge_alert(alert)
        except Exception:
            logger.warning("AD-505: Failed to post recommendation to Ward Room", exc_info=True)

    def _issue_guidance_directive(
        self,
        target_agent_type: str,
        content: str,
        expires_hours: float = DIRECTIVE_DEFAULT_EXPIRY_HOURS,
    ) -> bool:
        """Issue a COUNSELOR_GUIDANCE directive to an agent type."""
        if not self._directive_store:
            return False

        from probos.directive_store import DirectiveType
        from probos.crew_profile import Rank
        import time as _time

        try:
            active = self._directive_store.get_active_for_agent(target_agent_type)
            counselor_directives = [
                d for d in active
                if d.directive_type == DirectiveType.COUNSELOR_GUIDANCE
            ]
            if len(counselor_directives) >= self.MAX_ACTIVE_DIRECTIVES_PER_AGENT:
                logger.info(
                    "AD-505: Skipping directive for %s — %d active COUNSELOR_GUIDANCE already",
                    target_agent_type, len(counselor_directives),
                )
                return False

            expires_at = _time.time() + (expires_hours * 3600)

            directive, reason = self._directive_store.create_directive(
                issuer_type="counselor",
                issuer_department="bridge",
                issuer_rank=Rank.COMMANDER,
                target_agent_type=target_agent_type,
                target_department=None,
                directive_type=DirectiveType.COUNSELOR_GUIDANCE,
                content=content,
                authority=0.8,
                priority=4,
                expires_at=expires_at,
            )

            if directive:
                logger.info("AD-505: Issued COUNSELOR_GUIDANCE to %s: %s", target_agent_type, content[:80])
                return True
            else:
                logger.warning("AD-505: Directive creation failed for %s: %s", target_agent_type, reason)
                return False

        except Exception:
            logger.warning("AD-505: Failed to issue guidance directive", exc_info=True)
            return False

    async def _apply_intervention(
        self,
        agent_id: str,
        callsign: str,
        assessment: CounselorAssessment,
        severity: str,
    ) -> None:
        """Apply mechanical interventions for high-severity assessments.

        Called when severity is 'intervention' or 'escalate'.
        Actions: extend cooldown, force dream cycle, issue guidance directive.
        All visible to Captain via recommendation BridgeAlert.
        """
        actions_taken: list[str] = []

        # 1. Extend cooldown (1.5x for intervention, 2x for escalate)
        if self._proactive_loop:
            try:
                current = self._proactive_loop.get_agent_cooldown(agent_id)
                multiplier = 2.0 if severity == "escalate" else 1.5
                new_cooldown = min(current * multiplier, 1800.0)
                reason = (
                    f"Counselor intervention: {assessment.concerns[0]}"
                    if assessment.concerns else "Counselor intervention: elevated cognitive load"
                )
                self._proactive_loop.set_agent_cooldown(agent_id, new_cooldown, reason=reason)
                actions_taken.append(
                    f"Extended cooldown to {new_cooldown:.0f}s ({multiplier}x) — {reason}"
                )
            except Exception:
                logger.warning("AD-505: Failed to extend cooldown", exc_info=True)

        # 2. Force dream cycle
        if self._dream_scheduler and severity in ("intervention", "escalate"):
            try:
                if not self._dream_scheduler.is_dreaming:
                    await self._dream_scheduler.force_dream()
                    actions_taken.append("Triggered system dream cycle for consolidation")
                    self._intervention_targets.add(agent_id)  # AD-506a: track for post-dream re-assessment
                else:
                    actions_taken.append("Dream cycle already in progress — skipped")
            except Exception:
                logger.warning("AD-505: Failed to trigger dream cycle", exc_info=True)

        # 3. Issue guidance directive
        if assessment.concerns:
            agent = self._registry.get(agent_id) if self._registry else None
            agent_type = agent.agent_type if agent else agent_id
            concern_summary = assessment.concerns[0]
            directive_content = (
                f"The Counselor has noted: {concern_summary}. "
                "Take extra time between observations. If you notice yourself returning "
                "to the same topic, consider whether you have genuinely new information "
                "to add, or whether writing your thoughts to a notebook would help you "
                "release this focus."
            )
            if self._issue_guidance_directive(agent_type, directive_content):
                actions_taken.append(f"Issued COUNSELOR_GUIDANCE directive: {concern_summary}")

        # 4. Post recommendation BridgeAlert for Captain visibility
        if actions_taken:
            await self._post_recommendation_to_ward_room(
                agent_id, callsign, assessment, actions_taken
            )

    # -- Assessment logic (non-LLM, deterministic) --

    def assess_agent(self, agent_id: str, current_trust: float = 0.0,
                     current_confidence: float = 0.0, hebbian_avg: float = 0.0,
                     success_rate: float = 0.0,
                     personality_drift: float = 0.0,
                     trigger: str = "manual") -> CounselorAssessment:
        """Run a deterministic cognitive assessment.

        This is the non-LLM fast path. The LLM path (via decide()) adds
        nuanced professional judgment on top of these metrics.
        """
        profile = self.get_or_create_profile(agent_id)
        baseline = profile.baseline

        trust_drift = current_trust - baseline.trust_score
        confidence_drift = current_confidence - baseline.confidence
        hebbian_drift_val = hebbian_avg - baseline.hebbian_avg

        concerns: list[str] = []
        recommendations: list[str] = []

        # Trust degradation
        if trust_drift < COUNSELOR_TRUST_DRIFT_CONCERN:
            concerns.append(f"Trust dropped significantly ({trust_drift:+.2f} from baseline)")
            recommendations.append("Investigate recent task failures")
        elif trust_drift < -0.1:
            concerns.append(f"Trust trending downward ({trust_drift:+.2f})")

        # Confidence collapse
        if current_confidence < COUNSELOR_CONFIDENCE_LOW:
            concerns.append(f"Low confidence ({current_confidence:.2f})")
            recommendations.append("Consider targeted dream cycle for pattern consolidation")

        # Hebbian drift (maladaptive patterns)
        if hebbian_drift_val < -0.3:
            concerns.append(f"Hebbian weights degrading ({hebbian_drift_val:+.2f})")
            recommendations.append("Consider Hebbian weight reset for maladaptive pathways")

        # Poor success rate
        if success_rate < 0.5 and success_rate > 0.0:
            concerns.append(f"Low success rate ({success_rate:.0%})")
            recommendations.append("Review task assignment — may be overloaded or mismatched")

        # Personality drift (from CrewProfile baseline)
        if personality_drift > 0.5:
            concerns.append(f"Significant personality drift ({personality_drift:.2f})")
            recommendations.append("Flag for Captain review — may be emergence or degradation")

        # AD-539: Check for unresolved high/critical gaps in profile
        gap_concerns = getattr(profile, "_gap_concerns", [])
        high_gap_concerns = [c for c in gap_concerns
                             if "priority: high" in c or "priority: critical" in c]
        if high_gap_concerns:
            concerns.append(f"Unresolved knowledge gaps ({len(high_gap_concerns)} high/critical)")
            recommendations.append("Review gap reports — qualification path may be needed")

        # Compute wellness score
        wellness = 1.0
        wellness -= max(0, -trust_drift) * 1.5       # trust drops are serious
        wellness -= max(0, -confidence_drift) * 0.5
        wellness -= max(0, -hebbian_drift_val) * 0.3
        wellness -= max(0, personality_drift - 0.3) * 0.5
        if success_rate > 0 and success_rate < 0.5:
            wellness -= 0.2
        wellness = max(0.0, min(1.0, wellness))

        fit_for_duty = wellness >= COUNSELOR_WELLNESS_FIT and len(concerns) < 4
        fit_for_promotion = (
            wellness >= 0.8
            and current_trust >= COUNSELOR_TRUST_PROMOTION
            and len(concerns) == 0
            and success_rate >= 0.7
        )

        assessment = CounselorAssessment(
            timestamp=time.time(),
            agent_id=agent_id,
            trigger=trigger,
            trust_score=current_trust,
            confidence=current_confidence,
            hebbian_avg=hebbian_avg,
            success_rate=success_rate,
            personality_drift=personality_drift,
            trust_drift=trust_drift,
            confidence_drift=confidence_drift,
            hebbian_drift=hebbian_drift_val,
            wellness_score=wellness,
            concerns=concerns,
            recommendations=recommendations,
            fit_for_duty=fit_for_duty,
            fit_for_promotion=fit_for_promotion,
        )

        profile.add_assessment(assessment)
        return assessment

    # -- Lifecycle overrides --

    async def perceive(self, intent: Any) -> dict:
        """Receive and route counselor intents."""
        obs = await super().perceive(intent)
        intent_type = obs.get("intent", "")
        if intent_type in self._handled_intents:
            obs["handled"] = True
        return obs

    async def act(self, plan: Any) -> Any:
        """Execute the counselor's assessment plan."""
        # AD-398/BF-024: pass through conversational responses for 1:1, ward room, and proactive
        if isinstance(plan, dict) and plan.get("intent") in ("direct_message", "ward_room_notification", "proactive_think"):
            return {"success": True, "result": plan.get("llm_output", "")}

        # AD-503: Deterministic wellness sweep (no LLM needed)
        if isinstance(plan, dict) and plan.get("intent") == "counselor_wellness_report":
            results = await self._run_wellness_sweep()
            summary = {
                "total_assessed": len(results),
                "red": sum(1 for r in results if not r.fit_for_duty),
                "yellow": sum(1 for r in results if r.wellness_score < COUNSELOR_WELLNESS_YELLOW),
                "green": sum(1 for r in results if r.wellness_score >= COUNSELOR_WELLNESS_YELLOW and r.fit_for_duty),
                "assessments": [r.to_dict() for r in results],
            }
            return {"success": True, "result": summary}

        if isinstance(plan, dict) and plan.get("action") == "assess":
            agent_id = plan.get("agent_id", "")
            if agent_id:
                return self.assess_agent(
                    agent_id,
                    current_trust=plan.get("trust_score", 0.0),
                    current_confidence=plan.get("confidence", 0.0),
                    hebbian_avg=plan.get("hebbian_avg", 0.0),
                    success_rate=plan.get("success_rate", 0.0),
                    personality_drift=plan.get("personality_drift", 0.0),
                )
        # Fallback — return the plan as-is (LLM output)
        return plan

    async def report(self, result: Any) -> dict[str, Any]:
        """Package counselor results."""
        if isinstance(result, CounselorAssessment):
            return {
                "agent_id": self.id,
                "type": "counselor_assessment",
                "data": result.to_dict(),
            }
        # BF-015: conversational responses must preserve "result" key
        # for handle_intent() → IntentResult extraction
        if isinstance(result, dict) and "result" in result:
            return result
        return {
            "agent_id": self.id,
            "type": "counselor_response",
            "data": result if isinstance(result, dict) else str(result),
        }
