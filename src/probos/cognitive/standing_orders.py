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
import re
from pathlib import Path
from functools import lru_cache
from typing import Any

from probos.crew_profile import load_seed_profile

logger = logging.getLogger(__name__)

# Directive store reference, set by runtime at startup (AD-386)
_directive_store: Any = None

# Cognitive skill catalog reference, set by runtime at startup (AD-596b)
_skill_catalog: Any = None

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
    "data_analyst": "science",       # AD-560
    "systems_analyst": "science",    # AD-560
    "research_specialist": "science",  # AD-560
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


def set_skill_catalog(catalog: Any) -> None:
    """Wire the CognitiveSkillCatalog for tier 7 composition (AD-596b)."""
    global _skill_catalog
    _skill_catalog = catalog


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
def _build_personality_block(agent_type: str, department: str | None = None, callsign_override: str | None = None) -> str:
    """Build a personality & identity section from crew profile YAML (AD-393).

    Returns a formatted markdown section to insert between Tier 1 (hardcoded
    identity) and Tier 2 (Federation Constitution). Returns empty string if
    no profile exists or if the profile has no useful content.

    Args:
        callsign_override: Runtime callsign from naming ceremony (BF-083).
            Takes precedence over the seed callsign in the YAML profile.
    """
    profile = load_seed_profile(agent_type)
    if not profile:
        return ""

    lines: list[str] = ["## Crew Identity & Personality", ""]

    # Identity line — BF-083: prefer runtime callsign over YAML seed default
    callsign = callsign_override or profile.get("callsign", "")
    # BF-101: Diagnostic logging when callsign_override differs from YAML seed
    seed_callsign = profile.get("callsign", "")
    if callsign_override and callsign_override != seed_callsign:
        logger.debug("BF-101: %s personality block using override '%s' (seed='%s')",
                     agent_type, callsign_override, seed_callsign)
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
    """Clear the file cache (call after standing orders are updated).

    Note: Billet template resolution (AD-595c) is not separately cached —
    it runs as a post-processing pass on each compose_instructions() call.
    compose_instructions() is called per decide() cycle, so the regex cost
    is real (~30KB per agent per cycle). Currently sub-millisecond; if it
    shows up in profiling, add a version-keyed cache.
    """
    _load_file.cache_clear()
    _build_personality_block.cache_clear()


# Module-level BilletRegistry reference, set at startup (AD-595c).
# Module-level state — assumes single ProbOS runtime per process.
# Tests must save/restore via try/finally.
_billet_registry: "BilletRegistry | None" = None


def set_billet_registry(registry: "BilletRegistry | None") -> None:
    """Wire the BilletRegistry for template substitution (AD-595c).

    Called from finalize.py at startup. Module-level state — single-runtime
    assumption. Tests must save/restore.
    """
    global _billet_registry
    _billet_registry = registry


def _resolve_billet_templates(text: str, registry: "BilletRegistry") -> str:
    """Replace {Billet Title} patterns with resolved callsigns.

    - ``{Chief Engineer}`` → ``LaForge (Chief Engineer)`` if billet filled
    - ``{Chief Engineer}`` → ``Chief Engineer (vacant)`` if billet vacant
    - Non-matching ``{tokens}`` are left unchanged

    Only processes tokens that are 2+ chars and don't contain code-like
    characters (=, (, ), <, >, |, backtick) to avoid mangling code blocks
    or markdown. Tokens inside backtick-fenced code blocks or inline
    backtick spans are also skipped.
    """
    def _replace(match: re.Match) -> str:
        token = match.group(1)
        # Skip code-like tokens: contains =, (, ), <, >, |, backtick
        if any(c in token for c in '=()<>|`'):
            return match.group(0)
        # Skip single-char tokens
        if len(token.strip()) < 2:
            return match.group(0)
        # Skip if the match is inside backticks (inline code)
        start = match.start()
        line_start = text.rfind('\n', 0, start) + 1
        prefix = text[line_start:start]
        if '`' in prefix:
            # Count backticks before match on same line — odd count means inside inline code
            if prefix.count('`') % 2 == 1:
                return match.group(0)
        holder = registry.resolve(token.strip())
        if holder is None:
            return match.group(0)  # Not a known billet — leave unchanged
        if holder.holder_callsign:
            return f"{holder.holder_callsign} ({holder.title})"
        return f"{holder.title} (vacant)"  # Vacant — explicit signal

    # Match {content} but NOT inside backtick-fenced code blocks
    # Process line by line, skip lines inside ``` blocks
    lines = text.split('\n')
    in_code_block = False
    result_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('```') or stripped.startswith('~~~'):
            in_code_block = not in_code_block
            result_lines.append(line)
            continue
        if in_code_block:
            result_lines.append(line)
            continue
        # Process billet templates outside code blocks
        result_lines.append(re.sub(r'\{([^}]+)\}', _replace, line))
    return '\n'.join(result_lines)


def compose_instructions(
    agent_type: str,
    hardcoded_instructions: str,
    *,
    orders_dir: Path | None = None,
    department: str | None = None,
    callsign: str | None = None,
    agent_rank: str | None = None,
    skill_profile: object | None = None,  # AD-625: SkillProfile for proficiency display
) -> str:
    """Compose an agent's complete instructions from all tiers.

    Args:
        agent_type: The agent's type identifier (e.g., "builder", "architect").
        hardcoded_instructions: The agent's class-level instructions string.
        orders_dir: Override path to standing orders directory. Defaults
            to ``config/standing_orders/`` relative to the project root.
        department: Override department name. If None, looks up from
            ``_AGENT_DEPARTMENTS`` mapping.
        callsign: Runtime callsign from naming ceremony (BF-083). If
            provided, overrides the seed callsign from YAML profile.

    Returns:
        The composed instructions string with all applicable tiers.
    """
    d = orders_dir or _DEFAULT_ORDERS_DIR

    parts: list[str] = []

    # 1. Hardcoded identity (always first -- defines what the agent IS)
    if hardcoded_instructions:
        parts.append(hardcoded_instructions.strip())

    # 1.5 Crew personality & identity (AD-393, BF-083)
    dept = department or get_department(agent_type)
    personality_block = _build_personality_block(agent_type, dept, callsign)
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

    # 7. Available cognitive skills (AD-596b/AD-631) — XML format with behavioral primer
    if _skill_catalog is not None:
        skill_descs = _skill_catalog.get_descriptions(
            department=dept,
            agent_rank=agent_rank,
        )
        if skill_descs:
            # AD-625: Build proficiency lookup from skill profile
            _prof_map: dict[str, int] = {}
            if skill_profile is not None:
                for _rec in getattr(skill_profile, 'all_skills', []):
                    if _rec.skill_id:
                        _prof_map[_rec.skill_id] = _rec.proficiency

            skill_lines = ["<available_skills>"]
            for sname, sdesc, skill_id in skill_descs:
                _prof_label = ""
                if skill_id and skill_id in _prof_map:
                    from probos.cognitive.comm_proficiency import format_proficiency_label
                    _prof_label = format_proficiency_label(_prof_map[skill_id])
                _prof_attr = f' proficiency="{_prof_label}"' if _prof_label else ""
                skill_lines.append(f'<skill name="{sname}"{_prof_attr}>{sdesc}</skill>')
            skill_lines.append("</available_skills>")
            parts.append("\n".join(skill_lines))

    composed = "\n\n---\n\n".join(parts)

    # AD-595c: Resolve billet templates
    if _billet_registry is not None:
        composed = _resolve_billet_templates(composed, _billet_registry)

    return composed
