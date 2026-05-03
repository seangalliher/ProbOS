"""AD-526c: Recreation system metadata.

Optional metadata layered on top of the existing ``register_engine`` API.
Does NOT introduce a parallel registry -- the existing
``self._engines: dict[str, GameEngine]`` + ``register_engine`` /
``get_available_games`` API is preserved.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameMetadata:
    """Optional metadata layered on a registered ``GameEngine``."""

    description: str = ""
    agent_count_min: int = 2
    agent_count_max: int = 2
    registered_at: float = 0.0
