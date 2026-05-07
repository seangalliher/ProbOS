"""AD-486: Sequential department activation scheduler.

Per the AD spec at docs/development/roadmap.md:4130, departments are
activated sequentially with observation windows: Security/Operations
first (rapid-assessment trait profile), then Engineering/Science, then
Medical last (thoroughness/perfectionism causes longer calibration).

Observation criterion (NOT a timer): the next department-group is
admitted when every admitted agent in the previous group has reached
HolodeckPhase.SELF_DISCOVERY or higher. This anchors the gate to
completion criteria per the AD-486 spec invariant.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Callable

from probos.holodeck.phases import HolodeckPhase, PHASE_ORDER

logger = logging.getLogger(__name__)


class DepartmentActivationScheduler:
    """Tracks department-grouped admission queue + sequential activation."""

    def __init__(
        self,
        department_order: list[str],
        get_phase_fn: Callable[[str], HolodeckPhase | None],
    ) -> None:
        # Lowercased department names. Empty list = first-come-first-served.
        self._department_order: tuple[str, ...] = tuple(
            d.lower() for d in department_order
        )
        self._get_phase_fn = get_phase_fn
        # Insertion-ordered: agent_id -> (agent_type, department_lc)
        self._queue: "OrderedDict[str, tuple[str, str]]" = OrderedDict()
        self._admitted: set[str] = set()
        self._graduated: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_admission(
        self, agent_id: str, agent_type: str, department: str
    ) -> int:
        """Add an agent to the queue. Returns 1-based queue position."""
        dept_lc = (department or "").lower()
        self._queue[agent_id] = (agent_type, dept_lc)
        return len(self._queue)

    def next_admit_candidate(self) -> str | None:
        """Return the next eligible agent id, or None if blocked.

        v1 algorithm: walk department_order; for each department, if any
        queued non-admitted agent is in that department AND every
        already-admitted agent in earlier departments has reached
        SELF_DISCOVERY or higher, return the next queued agent.
        """
        if not self._department_order:
            for agent_id, _ in self._queue.items():
                if agent_id not in self._admitted:
                    return agent_id
            return None

        for dept in self._department_order:
            if not self._previous_groups_eligible(dept):
                return None
            for agent_id, (_atype, agent_dept) in self._queue.items():
                if agent_id in self._admitted:
                    continue
                if agent_dept == dept:
                    return agent_id
        # Fallthrough — anyone whose department is not in department_order
        for agent_id, (_atype, agent_dept) in self._queue.items():
            if agent_id in self._admitted:
                continue
            if agent_dept not in self._department_order:
                return agent_id
        return None

    def mark_admitted(self, agent_id: str) -> None:
        self._admitted.add(agent_id)

    def mark_graduated(self, agent_id: str) -> None:
        self._graduated.add(agent_id)

    def admitted_count(self) -> int:
        return len(self._admitted)

    def graduated_count(self) -> int:
        return len(self._graduated)

    def queue_size(self) -> int:
        return len(self._queue)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _previous_groups_eligible(self, current_dept: str) -> bool:
        """All earlier-department admitted agents have reached SELF_DISCOVERY+."""
        try:
            current_idx = self._department_order.index(current_dept)
        except ValueError:
            return True  # not in ordered list -> no precedence block
        if current_idx == 0:
            return True
        earlier = set(self._department_order[:current_idx])
        threshold_idx = PHASE_ORDER.index(HolodeckPhase.SELF_DISCOVERY)
        for agent_id in self._admitted:
            entry = self._queue.get(agent_id)
            if entry is None:
                continue
            _, agent_dept = entry
            if agent_dept not in earlier:
                continue
            phase = self._get_phase_fn(agent_id)
            if phase is None:
                return False
            try:
                phase_idx = PHASE_ORDER.index(phase)
            except ValueError:
                return False
            if phase_idx < threshold_idx:
                return False
        return True
