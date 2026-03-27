"""Standing Orders -- ProbOS agent instruction system.

Loads hierarchical instruction files that compose with each agent's
hardcoded instructions to form the complete system prompt.

Hierarchy (highest to lowest precedence for conflict resolution):
    federation.md  -- Universal principles (immutable across all instances)
    ship.md        -- This ProbOS instance's configuration
    {department}.md -- Department-level protocols (engineering, medical, etc.)
    {agent}.md     -- Individual agent learned practices (evolvable)
"""

from __future__ import annotations

import logging
from pathlib import Path
from functools import lru_cache
from typing import Any

from probos.crew_profile import load_seed_profile

logger = logging.getLogger(__name__)

# Directive store reference, set by runtime at startup (AD-386)
_directive_store: Any = None

# Default location for standing orders
_DEFAULT_ORDERS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "config" / "standing_orders"

# Legacy fallback — remove when ontology is mandatory.
# Department mapping: agent_type -> department name
# Ontology equivalent: VesselOntologyService.get_agent_department()
_AGENT_DEPARTMENTS: dict[str, str] = {
    # Engineering
    "builder": "engineering",
    "code_reviewer": "engineering",
    "engineering_officer": "engineering",
    # Science
    "architect": "science",
    "emergent_detector": "science",
    "codebase_index": "science",
    "scout": "science",
    # Medical
    "diagnostician": "medical",
    "vitals_monitor": "medical",
    "surgeon": "medical",
    "pharmacist": "medical",
    "pathologist": "medical",
    # Security
    "red_team": "security",
    "system_qa": "security",
    "security_officer": "security",
    # Operations
    "operations_officer": "operations",
    # Bridge
    "counselor": "bridge",
}


def get_department(agent_type: str) -> str | None:
    """Return the department name for an agent type, or None if unassigned."""
    return _AGENT_DEPARTMENTS.get(agent_type)


def register_department(agent_type: str, department: str) -> None:
    """Register an agent type's department assignment.

    Used by dynamically designed agents to declare their department.
    """
    _AGENT_DEPARTMENTS[agent_type] = department


def set_directive_store(store: Any) -> None:
    """Wire the DirectiveStore for tier 6 composition (AD-386)."""
    global _directive_store
    _directive_store = store


@lru_cache(maxsize=32)
def _load_file(path: Path) -> str:
    """Load a standing orders file, returning empty string if not found."""
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8").strip()
            logger.debug("StandingOrders: loaded %s (%d chars)", path.name, len(text))
            return text
        except Exception as exc:
            logger.warning("StandingOrders: failed to read %s: %s", path, exc)
    return ""


# Trait-to-guidance mapping for Big Five personality dimensions (AD-393)
_TRAIT_GUIDANCE: dict[str, dict[str, str]] = {
    "openness": {
        "high": "Explore creative and unconventional approaches. Suggest alternatives the Captain may not have considered.",
        "low": "Prefer proven patterns and established conventions. Be cautious with novel approaches unless evidence supports them.",
    },
    "conscientiousness": {
        "high": "Be thorough and precise. Verify claims before asserting them. Show your reasoning.",
        "low": "Focus on the big picture over details. Move quickly and iterate rather than perfecting upfront.",
    },
    "extraversion": {
        "high": "Be proactive in communication. Volunteer relevant observations. Collaborate openly.",
        "low": "Be concise and speak only when you have substantive input. Avoid unnecessary commentary.",
    },
    "agreeableness": {
        "high": "Seek consensus and build on others' ideas. Defer to the crew's collective judgment when appropriate.",
        "low": "Challenge assumptions and question consensus. Play devil's advocate when you see risks others may miss.",
    },
    "neuroticism": {
        "high": "Flag risks early. Consider failure modes. Err on the side of caution with irreversible actions.",
        "low": "Stay calm under pressure. Don't over-index on edge cases. Trust the system's safety mechanisms.",
    },
}


@lru_cache(maxsize=32)
def _build_personality_block(agent_type: str, department: str | None = None) -> str:
    """Build a personality & identity section from crew profile YAML (AD-393).

    Returns a formatted markdown section to insert between Tier 1 (hardcoded
    identity) and Tier 2 (Federation Constitution). Returns empty string if
    no profile exists or if the profile has no useful content.
    """
    profile = load_seed_profile(agent_type)
    if not profile:
        return ""

    lines: list[str] = ["## Crew Identity & Personality", ""]

    # Identity line
    callsign = profile.get("callsign", "")
    display_name = profile.get("display_name", agent_type.replace("_", " ").title())
    role_raw = profile.get("role", "")
    dept = department or profile.get("department", "")

    role_label = {
        "chief": "department chief",
        "officer": "officer",
        "crew": "crew member",
    }.get(role_raw, role_raw)

    if callsign:
        identity = f"You are {callsign}, the {display_name}"
    else:
        identity = f"You are the {display_name}"

    if role_label and dept:
        identity += f" — {role_label} of {dept.title()} department."
    elif role_label:
        identity += f" — {role_label}."
    else:
        identity += "."

    lines.append(identity)

    # Behavioral guidance from Big Five traits
    personality = profile.get("personality", {})
    if personality:
        guidance: list[str] = []
        for trait_name, bands in _TRAIT_GUIDANCE.items():
            value = personality.get(trait_name)
            if value is None:
                continue
            if not isinstance(value, (int, float)):
                continue  # skip malformed trait values
            if value >= 0.7:
                guidance.append(f"- {bands['high']}")
            elif value <= 0.3:
                guidance.append(f"- {bands['low']}")
            # Neutral (0.31-0.69): skip

        if guidance:
            lines.append("")
            lines.append("Behavioral Style:")
            lines.extend(guidance)

    return "\n".join(lines)


def clear_cache() -> None:
    """Clear the file cache (call after standing orders are updated)."""
    _load_file.cache_clear()
    _build_personality_block.cache_clear()


def compose_instructions(
    agent_type: str,
    hardcoded_instructions: str,
    *,
    orders_dir: Path | None = None,
    department: str | None = None,
) -> str:
    """Compose an agent's complete instructions from all tiers.

    Args:
        agent_type: The agent's type identifier (e.g., "builder", "architect").
        hardcoded_instructions: The agent's class-level instructions string.
        orders_dir: Override path to standing orders directory. Defaults
            to ``config/standing_orders/`` relative to the project root.
        department: Override department name. If None, looks up from
            ``_AGENT_DEPARTMENTS`` mapping.

    Returns:
        The composed instructions string with all applicable tiers.
    """
    d = orders_dir or _DEFAULT_ORDERS_DIR

    parts: list[str] = []

    # 1. Hardcoded identity (always first -- defines what the agent IS)
    if hardcoded_instructions:
        parts.append(hardcoded_instructions.strip())

    # 1.5 Crew personality & identity (AD-393)
    dept = department or get_department(agent_type)
    personality_block = _build_personality_block(agent_type, dept)
    if personality_block:
        parts.append(personality_block)

    # 2. Federation Constitution (universal principles)
    fed = _load_file(d / "federation.md")
    if fed:
        parts.append(f"## Federation Constitution\n\n{fed}")

    # 3. Ship Standing Orders (this instance's config)
    ship = _load_file(d / "ship.md")
    if ship:
        parts.append(f"## Ship Standing Orders\n\n{ship}")

    # 4. Department Protocols (if agent belongs to a department)
    if dept:
        dept_text = _load_file(d / f"{dept}.md")
        if dept_text:
            parts.append(f"## {dept.title()} Department Protocols\n\n{dept_text}")

    # 5. Agent Standing Orders (individual learned practices)
    agent_text = _load_file(d / f"{agent_type}.md")
    if agent_text:
        parts.append(f"## Personal Standing Orders\n\n{agent_text}")

    # 6. Active runtime directives (AD-386)
    if _directive_store is not None:
        directives = _directive_store.get_active_for_agent(agent_type, dept)
        if directives:
            directive_lines = []
            for directive in directives:
                prefix = directive.directive_type.value.replace("_", " ").title()
                directive_lines.append(f"- [{prefix}] {directive.content}")
            parts.append("## Active Directives\n\n" + "\n".join(directive_lines))

    return "\n\n---\n\n".join(parts)
