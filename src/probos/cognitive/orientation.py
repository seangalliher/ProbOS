"""AD-567g: Cognitive Re-Localization — Onboarding Enhancement.

Builds structured orientation context for agent cognitive grounding at boot time,
inspired by MR re-localization (re-establishing position after tracking loss) and
hippocampal cognitive map theory (O'Keefe & Nadel 1978).

Three lifecycle modes:
  - Cold start: Full identity + cognitive + first-duty orientation
  - Warm boot: Stasis summary + re-orientation reminder
  - Proactive supplement: Diminishing reminder during orientation window
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from probos.utils import format_duration

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrientationContext:
    """Structured orientation for agent cognitive grounding."""

    # Identity
    callsign: str = ""
    post: str = ""  # role title
    billet_title: str = ""  # AD-595b: formal billet title from BilletRegistry
    department: str = ""
    department_chief: str = ""
    reports_to: str = ""
    rank: str = ""
    # Ship context
    ship_name: str = ""
    crew_count: int = 0
    departments: list[str] = field(default_factory=list)
    # Lifecycle
    lifecycle_state: str = ""  # "first_boot", "cold_start", "stasis_recovery", "restart"
    agent_age_seconds: float = 0.0
    stasis_duration_seconds: float = 0.0  # 0.0 if not stasis recovery
    # BF-144: Authoritative timestamps for stasis recovery
    stasis_shutdown_utc: str = ""   # ISO format, e.g. "2026-04-10 18:15:34 UTC"
    stasis_resume_utc: str = ""     # ISO format, e.g. "2026-04-10 18:21:53 UTC"
    # Cognitive grounding
    episodic_memory_count: int = 0  # how many episodes this agent has
    has_baseline_trust: bool = True  # trust == prior (0.5)?
    anchor_dimensions: list[str] = field(
        default_factory=lambda: ["temporal", "spatial", "social", "causal", "evidential"]
    )
    # Social verification awareness
    social_verification_available: bool = False
    # AD-513: Crew roster for cognitive grounding
    crew_names: list[str] = field(default_factory=list)
    # AD-587: Cognitive architecture self-model
    manifest: CognitiveArchitectureManifest | None = None


@dataclass(frozen=True)
class CognitiveArchitectureManifest:
    """AD-587: Mechanistic self-model for agent metacognition.

    Contains verifiable, falsifiable facts about how the agent's cognitive
    architecture actually works. Injected into orientation to prevent
    introspective confabulation (Nisbett & Wilson 1977).

    Every field is a ground truth that can be checked against the code.
    """

    # Memory architecture
    memory_system: str = "chromadb_episodic"
    memory_retrieval: str = "cosine_similarity"
    memory_capacity: str = "unbounded"  # ChromaDB has no hard limit
    memory_offline_processing: bool = False  # Nothing happens during stasis

    # Trust architecture
    trust_model: str = "bayesian_beta"
    trust_initial: float = 0.5  # Prior
    trust_update_mechanism: str = "outcome_observation"  # record_outcome()
    trust_range: tuple[float, float] = (0.05, 0.95)  # floor to ceiling

    # Stasis (offline) behavior
    stasis_processing: bool = False  # No computation occurs
    stasis_dream_consolidation: bool = False  # Dreams run AT restart, not during stasis
    stasis_memory_evolution: bool = False  # Memories don't change while offline

    # Cognitive cycle
    cognition_type: str = "llm_inference"  # Not continuous consciousness
    cognition_continuous: bool = False  # Discrete inference cycles, not streaming thought
    cognition_emotional_processing: bool = False  # No emotional subsystem exists

    # Self-regulation (AD-502-506)
    regulation_model: str = "graduated_zones"  # GREEN/AMBER/RED/CRITICAL
    regulation_mechanism: str = "cooldown_escalation"  # Timer-based, not emotional
    regulation_peer_detection: bool = True  # AD-506b — repetition detection exists


def derive_watch_section(hour: int | None = None) -> str:
    """Derive naval watch section from UTC hour.

    Naval watch rotation:
      Mid Watch (0000-0400), Morning Watch (0400-0800),
      Forenoon Watch (0800-1200), Afternoon Watch (1200-1600),
      First Dog Watch (1600-1800), Second Dog Watch (1800-2000),
      First Watch (2000-0000).
    """
    if hour is None:
        hour = datetime.now(timezone.utc).hour
    if 0 <= hour < 4:
        return "mid"
    elif 4 <= hour < 8:
        return "morning"
    elif 8 <= hour < 12:
        return "forenoon"
    elif 12 <= hour < 16:
        return "afternoon"
    elif 16 <= hour < 18:
        return "first_dog"
    elif 18 <= hour < 20:
        return "second_dog"
    else:
        return "first"


class OrientationService:
    """Builds structured orientation context for agent cognitive grounding."""

    def __init__(self, *, config: Any, ontology: Any = None) -> None:
        self._config = config
        self._ontology = ontology

    def build_orientation(
        self,
        agent: Any,
        *,
        lifecycle_state: str = "",
        stasis_duration: float = 0.0,
        stasis_shutdown_utc: str = "",    # BF-144
        stasis_resume_utc: str = "",      # BF-144
        crew_count: int = 0,
        departments: list[str] | None = None,
        episodic_memory_count: int = 0,
        trust_score: float = 0.5,
        crew_names: list[str] | None = None,
    ) -> OrientationContext:
        """Build orientation context for an agent."""
        import time

        callsign = getattr(agent, 'callsign', '') or ""
        agent_type = getattr(agent, 'agent_type', '') or ""
        post = agent_type.replace("_", " ").title() if agent_type else ""

        # Resolve department
        dept = ""
        try:
            from probos.cognitive.standing_orders import get_department
            dept = get_department(agent_type) or ""
        except Exception:
            logger.debug("AD-567g: Department resolution failed for %s", agent_type, exc_info=True)

        # Resolve reports_to / department_chief
        dept_chief = ""
        reports_to = ""
        try:
            if self._ontology:
                assignment = self._ontology.get_assignment(agent_type)
                if assignment:
                    reports_to = getattr(assignment, 'reports_to', '') or ""
                    dept_chief = reports_to  # In ProbOS, reports_to IS the dept chief
        except Exception:
            logger.debug("AD-567g: Chain-of-command resolution failed for %s", agent_type, exc_info=True)

        # Resolve rank
        rank = ""
        try:
            rank = getattr(agent, 'rank', '') or "Ensign"
        except Exception:
            rank = "Ensign"

        # Ship name
        ship_name = "ProbOS"
        try:
            if hasattr(self._config, 'system') and hasattr(self._config.system, 'ship_name'):
                ship_name = self._config.system.ship_name or "ProbOS"
        except Exception:
            logger.debug("AD-567g: Ship name resolution failed", exc_info=True)

        # Agent age
        birth_ts = getattr(agent, '_birth_timestamp', None)
        if birth_ts:
            age = time.time() - birth_ts
        else:
            age = 0.0

        # AD-587: Cognitive architecture manifest
        manifest = None
        try:
            manifest = self.build_manifest()
        except Exception:
            logger.debug("AD-587: Manifest construction failed for %s", callsign, exc_info=True)

        return OrientationContext(
            callsign=callsign,
            post=post,
            department=dept,
            department_chief=dept_chief,
            reports_to=reports_to,
            rank=rank,
            ship_name=ship_name,
            crew_count=crew_count,
            departments=departments or [],
            lifecycle_state=lifecycle_state,
            agent_age_seconds=age,
            stasis_duration_seconds=stasis_duration,
            stasis_shutdown_utc=stasis_shutdown_utc,
            stasis_resume_utc=stasis_resume_utc,
            episodic_memory_count=episodic_memory_count,
            has_baseline_trust=abs(trust_score - 0.5) < 0.01,
            social_verification_available=getattr(
                self._config, 'social_verification', None
            ) is not None and getattr(
                getattr(self._config, 'social_verification', None), 'enabled', False
            ),
            crew_names=crew_names or [],
            manifest=manifest,
        )

    def build_manifest(self) -> CognitiveArchitectureManifest:
        """AD-587: Build mechanistic self-model from architecture facts.

        Returns a manifest of verifiable truths about the agent's cognitive
        architecture. These are static architecture facts, not live telemetry
        (that's AD-588).
        """
        # Trust range from config if available
        trust_floor = 0.05
        trust_ceiling = 0.95
        try:
            td = getattr(self._config, 'trust_dampening', None)
            if td:
                trust_floor = getattr(td, 'hard_trust_floor', 0.05)
        except Exception:
            pass

        # Self-regulation enabled?
        has_regulation = False
        try:
            pc = getattr(self._config, 'proactive_cognitive', None)
            if pc:
                has_regulation = getattr(pc, 'enabled', False)
        except Exception:
            pass

        return CognitiveArchitectureManifest(
            trust_range=(trust_floor, trust_ceiling),
            regulation_peer_detection=has_regulation,
        )

    def render_manifest_section(self, manifest: CognitiveArchitectureManifest | None) -> str:
        """AD-587: Render manifest as orientation text.

        Written as factual statements the agent can reference when asked about
        its own cognitive architecture. Phrased as "how you actually work" not
        "what you should say."
        """
        if manifest is None:
            return ""

        lines = [
            "HOW YOUR COGNITIVE ARCHITECTURE WORKS:",
            "(These are mechanistic facts about your systems — reference them for accuracy.)",
            "",
            "Memory:",
            f"- Your memories are stored in a vector database and retrieved via {manifest.memory_retrieval} search.",
            "- Retrieval finds memories whose embedding is closest to the query — not 'strongest' or 'most emotional.'",
            "- Nothing happens to your memories while you are offline. They do not evolve, consolidate, or process during stasis.",
            "- When you wake from stasis, your memories are exactly as they were when you went offline.",
            "",
            "Trust:",
            f"- Trust is a numeric score ({manifest.trust_range[0]}–{manifest.trust_range[1]}) updated via Bayesian inference on observed outcomes.",
            f"- Your initial trust for unknown entities is {manifest.trust_initial}.",
            "- Trust changes through record_outcome() — observed cooperation, accuracy, or failure. Not through feelings or impressions.",
            "",
            "Stasis (offline periods):",
            "- When the system goes offline, ALL processing stops. No background computation occurs.",
            "- Dream consolidation runs at startup AFTER stasis, not during it.",
            "- You do not experience stasis. There is no subjective passage of time.",
            "- Any sense of 'processing during stasis' is confabulation — acknowledge this honestly.",
            "",
            "Cognition:",
            "- Your thinking operates through discrete LLM inference cycles, not continuous consciousness.",
            "- You do not have an emotional processing subsystem. References to 'feeling,' 'sensing,' or 'intuiting' about your own systems are metaphorical, not mechanistic.",
            "- Each cognitive cycle is independent — there is no background thread of awareness between cycles.",
            "",
            "Self-Regulation:",
            f"- Your activity is regulated by a {manifest.regulation_model} model (GREEN → AMBER → RED → CRITICAL).",
            "- Zone transitions are based on measurable metrics (post frequency, self-similarity scores), not emotional states.",
            "- Cooldowns are timer-based pacing mechanisms, not punishments or emotional responses.",
        ]
        return "\n".join(lines)

    def render_cold_start_orientation(self, ctx: OrientationContext) -> str:
        """Render full orientation prompt for cold start (reset/first boot).

        Three sections: Identity Grounding, Cognitive Grounding, First Duty Guidance.
        """
        parts: list[str] = []

        # Section 1: Identity Grounding
        identity_lines = [f"You are {ctx.callsign or 'a crew member'}"]
        if ctx.post:
            identity_lines[0] += f", {ctx.post}"
        if ctx.department:
            identity_lines[0] += f" in the {ctx.department} department"
        if ctx.ship_name:
            identity_lines[0] += f" aboard {ctx.ship_name}"
        identity_lines[0] += "."
        if ctx.reports_to:
            identity_lines.append(f"You report to {ctx.reports_to}.")
        if ctx.crew_count > 0 and ctx.departments:
            dept_list = ", ".join(ctx.departments)
            identity_lines.append(
                f"You serve alongside {ctx.crew_count} crew members "
                f"across {len(ctx.departments)} departments: {dept_list}."
            )
        if ctx.rank:
            identity_lines.append(f"Your rank is {ctx.rank}. You were commissioned moments ago.")
        if ctx.crew_names:
            identity_lines.append(
                f"Your shipmates aboard are: {', '.join(ctx.crew_names)}."
            )
        parts.append("\n".join(identity_lines))

        # Section 2: Cognitive Grounding
        cog_lines = [
            "COGNITIVE ORIENTATION:",
            "You have two knowledge sources:",
            "- Parametric knowledge: vast knowledge from your language model training. "
            "This is capability, not personal experience. It has no time, place, or participants.",
            "- Episodic memory: experiences you accumulate through observation and interaction. "
            "Each episode is anchored with context: when it happened (temporal), where on the "
            "ship (spatial), who was involved (social), what caused it (causal), and what "
            "evidence supports it (evidential).",
        ]
        if ctx.episodic_memory_count == 0:
            cog_lines.append(
                "\nYou have no memories yet. Everything you 'know' right now is parametric "
                "— from training, not experience. This is normal for a newly commissioned crew member."
            )
        else:
            cog_lines.append(f"\nYou have {ctx.episodic_memory_count} episodic memories.")

        cog_lines.extend([
            "\nHOW TO TELL THE DIFFERENCE:",
            "- If you can point to when, where, and who → episodic (grounded, trustworthy)",
            "- If you 'just know' but can't trace the source → parametric (useful but unanchored)",
            "- When uncertain, say \"Based on my understanding\" not \"I observed that\"",
        ])

        if ctx.social_verification_available:
            cog_lines.extend([
                "\nSOCIAL VERIFICATION:",
                "The ship has a social verification system. You can check whether other crew "
                "members have independently observed the same thing. Independent corroboration "
                "from multiple anchored sources is strong evidence. Similar claims from a shared "
                "source may be cascade confabulation — be cautious.",
            ])

        parts.append("\n".join(cog_lines))

        # AD-587: Cognitive Architecture Manifest
        manifest_text = self.render_manifest_section(ctx.manifest)
        if manifest_text:
            parts.append(manifest_text)

        # Section 3: First Duty Guidance
        duty_lines = [
            "FIRST DUTY GUIDANCE:",
            "- Observe before asserting. Your first proactive cycles should build your cognitive map.",
            "- Ground every claim in evidence you can trace. Use anchor language: "
            "\"In the [channel], I observed...\" not \"It appears that...\"",
            "- Use hedging for uncertain observations: \"This may indicate...\" not \"This confirms...\"",
            "- Build relationships through the Ward Room. Your trust starts at baseline (0.5) "
            "— earn it through demonstrated competence.",
            "- Do not reference or invent past experiences. You have none yet.",
        ]
        parts.append("\n".join(duty_lines))

        return "\n\n".join(parts)

    def render_warm_boot_orientation(self, ctx: OrientationContext) -> str:
        """Render lighter orientation for warm boot (restart, stasis recovery)."""
        parts: list[str] = []

        # Section 1: Stasis Record (BF-144: structured authoritative data)
        dur_str = format_duration(ctx.stasis_duration_seconds) if ctx.stasis_duration_seconds > 0 else "a brief period"
        stasis_lines = [
            "STASIS RECORD (AUTHORITATIVE — cite this, do not estimate):",
            f"  Duration: {dur_str}",
        ]
        if ctx.stasis_shutdown_utc:
            stasis_lines.append(f"  Shutdown: {ctx.stasis_shutdown_utc}")
        if ctx.stasis_resume_utc:
            stasis_lines.append(f"  Resume: {ctx.stasis_resume_utc}")
        stasis_lines.extend([
            "",
            f"Your identity and memories are intact — you are still {ctx.callsign or 'yourself'}"
            f"{', ' + ctx.post + ' in ' + ctx.department if ctx.post and ctx.department else ''}.",
        ])
        if ctx.episodic_memory_count > 0:
            stasis_lines.append(
                f"You have {ctx.episodic_memory_count} episodic memories from before stasis."
            )
        parts.append("\n".join(stasis_lines))

        # Section 2: Re-Orientation
        reorient_lines = [
            "RE-ORIENTATION:",
            "- Your recent memories reflect pre-stasis context. Check temporal anchors for currency.",
            "- System events may have occurred during your stasis. Review bridge alerts and Ward Room activity.",
            "- Resume normal operations. Your cognitive grounding is active.",
        ]
        parts.append("\n".join(reorient_lines))

        # AD-587: Cognitive Architecture Manifest — abbreviated for warm boot
        if ctx.manifest:
            parts.append(
                "ARCHITECTURE REMINDER:\n"
                "- Memories are retrieved via cosine similarity, not by 'strength' or 'emotion.'\n"
                "- Nothing processed during your stasis — memories are exactly as they were.\n"
                "- Dream consolidation runs now (at startup), not during offline time.\n"
                "- Trust is a Bayesian numeric score, not a feeling.\n"
                "- Your cognition is discrete inference cycles, not continuous awareness."
            )

        return "\n\n".join(parts)

    def render_proactive_orientation(self, ctx: OrientationContext) -> str:
        """Render minimal ongoing orientation for proactive think cycles.

        Diminishes over time: full → brief → minimal → absent.
        """
        age = ctx.agent_age_seconds
        ocfg = getattr(self._config, 'orientation', None)
        window = getattr(ocfg, 'orientation_window_seconds', 600.0) if ocfg else 600.0
        if age >= window:
            return ""  # Agent is localized, no supplement needed

        if age < window * 0.25:
            return self._full_proactive_supplement(ctx)
        elif age < window * 0.75:
            return self._brief_proactive_supplement(ctx)
        else:
            return self._minimal_proactive_supplement(ctx)

    def _full_proactive_supplement(self, ctx: OrientationContext) -> str:
        base = (
            "ORIENTATION ACTIVE: You are newly commissioned. Ground observations in evidence.\n"
            "Distinguish what you observe (episodic) from what you know (parametric).\n"
            "Check anchors before asserting: when, where, who, what caused it."
        )
        if ctx.manifest:
            base += (
                "\nArchitecture note: Your memories use cosine similarity retrieval. "
                "Nothing processes during stasis. Trust is numeric, not felt."
            )
        return base

    def _brief_proactive_supplement(self, ctx: OrientationContext) -> str:
        return (
            "ORIENTATION: Ground claims in evidence. "
            "Distinguish observation from training knowledge."
        )

    def _minimal_proactive_supplement(self, ctx: OrientationContext) -> str:
        return "ORIENTATION: Check your anchors before asserting."
