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
        )

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
        return (
            "ORIENTATION ACTIVE: You are newly commissioned. Ground observations in evidence.\n"
            "Distinguish what you observe (episodic) from what you know (parametric).\n"
            "Check anchors before asserting: when, where, who, what caused it."
        )

    def _brief_proactive_supplement(self, ctx: OrientationContext) -> str:
        return (
            "ORIENTATION: Ground claims in evidence. "
            "Distinguish observation from training knowledge."
        )

    def _minimal_proactive_supplement(self, ctx: OrientationContext) -> str:
        return "ORIENTATION: Check your anchors before asserting."
