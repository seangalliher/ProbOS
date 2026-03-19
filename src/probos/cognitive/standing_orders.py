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

logger = logging.getLogger(__name__)

# Default location for standing orders
_DEFAULT_ORDERS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "config" / "standing_orders"

# Department mapping: agent_type -> department name
_AGENT_DEPARTMENTS: dict[str, str] = {
    # Engineering
    "builder": "engineering",
    "code_reviewer": "engineering",
    # Science
    "architect": "science",
    "emergent_detector": "science",
    "codebase_index": "science",
    # Medical
    "diagnostician": "medical",
    "vitals_monitor": "medical",
    "surgeon": "medical",
    "pharmacist": "medical",
    "pathologist": "medical",
    # Security
    "red_team": "security",
    "system_qa": "security",
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


def clear_cache() -> None:
    """Clear the file cache (call after standing orders are updated)."""
    _load_file.cache_clear()


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

    # 2. Federation Constitution (universal principles)
    fed = _load_file(d / "federation.md")
    if fed:
        parts.append(f"## Federation Constitution\n\n{fed}")

    # 3. Ship Standing Orders (this instance's config)
    ship = _load_file(d / "ship.md")
    if ship:
        parts.append(f"## Ship Standing Orders\n\n{ship}")

    # 4. Department Protocols (if agent belongs to a department)
    dept = department or get_department(agent_type)
    if dept:
        dept_text = _load_file(d / f"{dept}.md")
        if dept_text:
            parts.append(f"## {dept.title()} Department Protocols\n\n{dept_text}")

    # 5. Agent Standing Orders (individual learned practices)
    agent_text = _load_file(d / f"{agent_type}.md")
    if agent_text:
        parts.append(f"## Personal Standing Orders\n\n{agent_text}")

    return "\n\n---\n\n".join(parts)
