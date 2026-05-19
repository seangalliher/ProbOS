"""AD-733c-5: Per-agent perception engagement registry.

Thin dict-wrapper around per-agent ``PerceptionModeController`` instances.
Owned by ``ProbOSRuntime`` as ``runtime.perception_engagement_registry``.

For back-compat, ``runtime.perception_mode_controller`` continues to
point at a primary controller (Counselor "e1" if registered, else the
first registered agent). New code SHOULD prefer the registry lookup so
each agent's engagement state is independently controlled.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .mode_controller import Mode, PerceptionModeController

if TYPE_CHECKING:  # pragma: no cover - import-cycle guard
    from ..runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


class PerceptionEngagementRegistry:
    """AD-733c-5: registry of per-agent ``PerceptionModeController`` instances.

    Construction shape is intentionally tiny — the registry owns nothing
    beyond a dict + look-up helpers. Lifecycle (``start``/``stop``) is
    delegated to the controllers themselves.
    """

    def __init__(self, runtime: "ProbOSRuntime") -> None:
        self._runtime = runtime
        self._controllers: dict[str, PerceptionModeController] = {}

    def register(self, agent_id: str, controller: PerceptionModeController) -> None:
        """Add a controller for ``agent_id``. Replaces any existing entry."""
        if not agent_id:
            logger.warning(
                "AD-733c-5: refusing to register controller with empty agent_id"
            )
            return
        self._controllers[agent_id] = controller

    def get(self, agent_id: str) -> PerceptionModeController | None:
        """Return the controller for ``agent_id`` or ``None`` when absent."""
        return self._controllers.get(agent_id)

    def all_controllers(self) -> dict[str, PerceptionModeController]:
        """Return a shallow copy of all registered controllers."""
        return dict(self._controllers)

    def current_modes(self) -> dict[str, str]:
        """Map ``agent_id -> mode-name`` for HXI rendering."""
        return {
            aid: ctrl.current_mode.value
            for aid, ctrl in self._controllers.items()
        }

    def __contains__(self, agent_id: str) -> bool:
        return agent_id in self._controllers

    def __len__(self) -> int:
        return len(self._controllers)


def select_primary_controller(
    registry: PerceptionEngagementRegistry,
) -> PerceptionModeController | None:
    """Pick the back-compat singleton pointer.

    Preference order:
    1. Counselor (``e1``) if registered (matches Wave 175 default crew).
    2. First registered controller.
    3. None when registry is empty.
    """
    counselor = registry.get("e1")
    if counselor is not None:
        return counselor
    controllers = registry.all_controllers()
    if not controllers:
        return None
    return next(iter(controllers.values()))


__all__ = [
    "Mode",
    "PerceptionEngagementRegistry",
    "PerceptionModeController",
    "select_primary_controller",
]
