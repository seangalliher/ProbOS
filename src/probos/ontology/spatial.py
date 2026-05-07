"""AD-520: Spatial Knowledge Explorer — deck topology and agent positioning.

Renderer-agnostic SpatialLayout data model. The OSS HXI uses this for the
Phase 2 Spatial Ship Layout view. A future commercial overlay can mount a
WebXR immersive experience against the same layout without backend changes.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_DECK_DIMENSIONS: tuple[float, float, float] = (8.0, 1.5, 6.0)


@dataclass(frozen=True)
class SpatialDeck:
    """A single deck in the ship topology."""

    deck_id: str
    name: str
    department_id: str | None
    position: tuple[float, float, float]
    dimensions: tuple[float, float, float] = _DEFAULT_DECK_DIMENSIONS
    post_offsets: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    accent_color: str = "#666680"

    def to_dict(self) -> dict[str, Any]:
        return {
            "deck_id": self.deck_id,
            "name": self.name,
            "department_id": self.department_id,
            "position": list(self.position),
            "dimensions": list(self.dimensions),
            "accent_color": self.accent_color,
            "post_offsets": {k: list(v) for k, v in self.post_offsets.items()},
        }


@dataclass(frozen=True)
class SpatialLayout:
    """Top-level ship topology — one or more decks."""

    decks: list[SpatialDeck]
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decks": [d.to_dict() for d in self.decks],
        }

    def find_deck_for_department(self, department_id: str | None) -> SpatialDeck | None:
        if not department_id:
            return None
        for d in self.decks:
            if d.department_id == department_id:
                return d
        return None


_DEFAULT_LAYOUT = SpatialLayout(
    decks=[
        SpatialDeck(
            deck_id="bridge",
            name="Bridge",
            department_id="command",
            position=(0.0, 6.0, 0.0),
            dimensions=(8.0, 1.5, 6.0),
            accent_color="#f0b060",
            post_offsets={
                "captain": (0.0, 0.0, -1.0),
                "first_officer": (-1.5, 0.0, 0.0),
                "counselor": (1.5, 0.0, 0.0),
                "yeoman": (0.0, 0.0, 1.5),
            },
        ),
        SpatialDeck(
            deck_id="engineering",
            name="Engineering",
            department_id="engineering",
            position=(0.0, 0.0, 6.0),
            dimensions=(8.0, 2.0, 6.0),
            accent_color="#d8742a",
            post_offsets={"chief_engineer": (0.0, 0.0, 0.0)},
        ),
        SpatialDeck(
            deck_id="sickbay",
            name="Sickbay",
            department_id="medical",
            position=(-6.0, 3.0, 0.0),
            dimensions=(6.0, 1.5, 6.0),
            accent_color="#54c474",
            post_offsets={"chief_medical_officer": (0.0, 0.0, 0.0)},
        ),
        SpatialDeck(
            deck_id="tactical",
            name="Tactical",
            department_id="security",
            position=(6.0, 3.0, 0.0),
            dimensions=(6.0, 1.5, 6.0),
            accent_color="#c84858",
            post_offsets={"chief_of_security": (0.0, 0.0, 0.0)},
        ),
        SpatialDeck(
            deck_id="science_lab",
            name="Science Lab",
            department_id="science",
            position=(0.0, 3.0, -6.0),
            dimensions=(6.0, 1.5, 6.0),
            accent_color="#5ca0d4",
            post_offsets={"chief_science_officer": (0.0, 0.0, 0.0)},
        ),
        SpatialDeck(
            deck_id="computer_core",
            name="Computer Core",
            department_id="ship-systems",
            position=(0.0, -3.0, 0.0),
            dimensions=(6.0, 2.0, 6.0),
            accent_color="#8870c4",
            post_offsets={},
        ),
        SpatialDeck(
            deck_id="common_areas",
            name="Common Areas",
            department_id=None,
            position=(0.0, 1.0, 0.0),
            dimensions=(10.0, 1.0, 10.0),
            accent_color="#666680",
            post_offsets={},
        ),
    ],
    schema_version=1,
)


def load_spatial_layout(path: str | None) -> SpatialLayout:
    """Load a SpatialLayout from YAML, falling back to _DEFAULT_LAYOUT.

    Tier-2 log-and-degrade: any failure (missing file, parse error, schema
    mismatch) returns _DEFAULT_LAYOUT with a WARNING log. Returns
    _DEFAULT_LAYOUT when path is empty/None.
    """
    if not path:
        return _DEFAULT_LAYOUT
    if not os.path.exists(path):
        logger.warning("AD-520: spatial layout file not found at %s; using default", path)
        return _DEFAULT_LAYOUT
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        decks_raw = data.get("decks", [])
        if not isinstance(decks_raw, list) or not decks_raw:
            logger.warning("AD-520: spatial layout %s has empty/invalid decks; using default", path)
            return _DEFAULT_LAYOUT
        decks = []
        for d in decks_raw:
            if not isinstance(d, dict):
                continue
            decks.append(
                SpatialDeck(
                    deck_id=str(d.get("deck_id", "")),
                    name=str(d.get("name", "")),
                    department_id=d.get("department_id"),
                    position=tuple(d.get("position", (0.0, 0.0, 0.0)))[:3],  # type: ignore[arg-type]
                    dimensions=tuple(d.get("dimensions", _DEFAULT_DECK_DIMENSIONS))[:3],  # type: ignore[arg-type]
                    post_offsets={
                        str(k): tuple(v)[:3]  # type: ignore[arg-type]
                        for k, v in (d.get("post_offsets", {}) or {}).items()
                    },
                    accent_color=str(d.get("accent_color", "#666680")),
                )
            )
        if not decks:
            return _DEFAULT_LAYOUT
        return SpatialLayout(decks=decks, schema_version=int(data.get("schema_version", 1)))
    except Exception as exc:  # noqa: BLE001 — tier-2 log-and-degrade
        logger.warning("AD-520: failed to parse spatial layout %s: %s; using default", path, exc)
        return _DEFAULT_LAYOUT


def compute_agent_positions(
    layout: SpatialLayout, manifest: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Map each crew-manifest entry to a 3D position via deck + post-offset.

    Agents without a known deck/department are placed at the 'common_areas'
    deck offset and flagged on_watch=False. Pure helper — no I/O.
    """
    common = next(
        (d for d in layout.decks if d.deck_id == "common_areas"),
        layout.decks[-1] if layout.decks else None,
    )
    out: list[dict[str, Any]] = []
    for entry in manifest:
        agent_id = entry.get("agent_id") or entry.get("agent_type") or ""
        agent_type = entry.get("agent_type") or agent_id
        department = entry.get("department")
        post = entry.get("post") or ""
        known_deck = layout.find_deck_for_department(department)
        deck = known_deck or common
        if deck is None:
            continue
        offset = deck.post_offsets.get(post, (0.0, 0.0, 0.0))
        position = (
            deck.position[0] + offset[0],
            deck.position[1] + offset[1],
            deck.position[2] + offset[2],
        )
        on_watch = bool(entry.get("on_watch", False)) if known_deck is not None else False
        out.append(
            {
                "agent_id": agent_id,
                "agent_type": agent_type,
                "department": department,
                "post": post,
                "deck_id": deck.deck_id,
                "position": list(position),
                "on_watch": on_watch,
            }
        )
    return out
