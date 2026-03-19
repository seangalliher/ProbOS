"""SystemSelfModel — structured runtime self-knowledge (AD-318)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PoolSnapshot:
    """Snapshot of a single pool's state."""
    name: str
    agent_type: str
    agent_count: int
    department: str = ""


@dataclass
class SystemSelfModel:
    """Compact, always-current snapshot of verified runtime facts.

    Level 2 of self-knowledge grounding (AD-318).
    Injected into the Decomposer's user prompt as SYSTEM CONTEXT.
    """

    # Identity
    version: str = ""

    # Topology
    pool_count: int = 0
    agent_count: int = 0
    pools: list[PoolSnapshot] = field(default_factory=list)
    departments: list[str] = field(default_factory=list)
    intent_count: int = 0

    # Health
    system_mode: str = "active"  # active | idle | dreaming
    uptime_seconds: float = 0.0
    recent_errors: list[str] = field(default_factory=list)  # last 5 error summaries
    last_capability_gap: str = ""  # last unhandled intent description

    def to_context(self) -> str:
        """Serialize to compact text for LLM context injection.

        Designed to stay under ~500 chars to fit within context budget.
        """
        lines: list[str] = []

        # Identity + mode
        mode_line = "System: ProbOS"
        if self.version:
            mode_line += f" {self.version}"
        mode_line += f" | Mode: {self.system_mode}"
        if self.uptime_seconds > 0:
            mins = int(self.uptime_seconds // 60)
            mode_line += f" | Uptime: {mins}m"
        lines.append(mode_line)

        # Topology summary
        lines.append(
            f"Pools: {self.pool_count} | Agents: {self.agent_count} "
            f"| Intents: {self.intent_count}"
        )

        # Departments
        if self.departments:
            lines.append(f"Departments: {', '.join(self.departments)}")

        # Per-pool breakdown (compact: "name(type×count)" format)
        if self.pools:
            pool_parts = []
            for p in self.pools:
                pool_parts.append(f"{p.name}({p.agent_type}\u00d7{p.agent_count})")
            lines.append(f"Pool roster: {', '.join(pool_parts)}")

        # Health signals
        if self.last_capability_gap:
            lines.append(f"Last capability gap: {self.last_capability_gap}")
        if self.recent_errors:
            lines.append(f"Recent errors ({len(self.recent_errors)}): {'; '.join(self.recent_errors[:3])}")

        return "\n".join(lines)
