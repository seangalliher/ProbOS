"""AD-1143 DD-2 — versioned goal-set loading, hashing, and schema validation.

The goal set is a **content-hashed input**: every committed baseline records
``goalset_sha256`` and ``compare_to_baseline`` refuses to compare across a
change. A goal set is therefore versioned by filename *and* by the
``goalset_version`` key inside it, and is never edited in place.

The schema guard here enforces DD-2's fairness criterion, which is the whole
point of the AD: a goal a single competent agent could solve alone measures
general capability rather than cross-agent knowledge flow, dilutes the effect
toward zero, and makes the harness measure the wrong thing.

No production imports. No I/O at import.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"
GOALSET_V1_PATH = DATA_DIR / "sigma_goals_v1.json"
GOALSET_SMOKE_PATH = DATA_DIR / "sigma_goals_smoke.json"

#: Closed vocabulary. A goal must declare exactly one of these.
DISCRIMINATORS: frozenset[str] = frozenset(
    {"cross_child", "cross_session", "redundancy"}
)

_REQUIRED_GOAL_KEYS = frozenset(
    {
        "id",
        "goal",
        "children_hint",
        "discriminator",
        "discriminator_note",
        "solo_solvable",
        "seed_records",
    }
)


@dataclass(frozen=True)
class Goal:
    """One ablation goal."""

    id: str
    goal: str
    children_hint: int
    discriminator: str
    discriminator_note: str
    solo_solvable: bool
    seed_records: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class GoalSet:
    """A loaded, validated, content-hashed goal set."""

    version: str
    sha256: str
    path: Path
    goals: tuple[Goal, ...]

    def __len__(self) -> int:
        return len(self.goals)


def sha256_file(path: Path) -> str:
    """SHA-256 of a file's exact bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_goalset(payload: dict[str, Any], *, source: str) -> None:
    """Raise ``ValueError`` naming the offending goal on any schema breach.

    Enforced, in order: a ``goalset_version``; a non-empty ``goals`` list;
    per goal, the exact required key set, a unique id, a non-empty goal text, a
    positive ``children_hint``, a ``discriminator`` from the closed vocabulary,
    ``solo_solvable is False``, a non-empty ``discriminator_note``, and — for
    ``cross_session`` only — non-empty ``seed_records`` with a title and body
    on every entry.

    The ``cross_session``/``seed_records`` pairing is load-bearing: without a
    seeded record there is nothing for a later session to retrieve, and the
    goal silently degrades into a capability test.
    """
    version = payload.get("goalset_version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError(f"{source}: missing or empty goalset_version")
    goals = payload.get("goals")
    if not isinstance(goals, list) or not goals:
        raise ValueError(f"{source}: goals must be a non-empty list")

    seen: set[str] = set()
    for index, entry in enumerate(goals):
        where = f"{source}: goals[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} is not an object")
        missing = _REQUIRED_GOAL_KEYS - set(entry)
        if missing:
            raise ValueError(f"{where} missing key(s): {sorted(missing)}")
        extra = set(entry) - _REQUIRED_GOAL_KEYS
        if extra:
            raise ValueError(f"{where} has unexpected key(s): {sorted(extra)}")

        goal_id = entry["id"]
        if not isinstance(goal_id, str) or not goal_id.strip():
            raise ValueError(f"{where} has an empty id")
        if goal_id in seen:
            raise ValueError(f"{source}: duplicate goal id {goal_id!r}")
        seen.add(goal_id)
        where = f"{source}: goal {goal_id}"

        if not isinstance(entry["goal"], str) or not entry["goal"].strip():
            raise ValueError(f"{where} has empty goal text")
        hint = entry["children_hint"]
        if type(hint) is not int or hint < 1:
            raise ValueError(f"{where} children_hint must be a positive int")

        discriminator = entry["discriminator"]
        if discriminator not in DISCRIMINATORS:
            raise ValueError(
                f"{where} discriminator {discriminator!r} is not one of "
                f"{sorted(DISCRIMINATORS)}"
            )
        note = entry["discriminator_note"]
        if not isinstance(note, str) or not note.strip():
            raise ValueError(f"{where} has an empty discriminator_note")

        if entry["solo_solvable"] is not False:
            raise ValueError(
                f"{where} declares solo_solvable={entry['solo_solvable']!r}; a "
                f"solo-solvable goal measures general capability, not "
                f"cross-agent knowledge flow, and dilutes the effect"
            )

        records = entry["seed_records"]
        if not isinstance(records, list):
            raise ValueError(f"{where} seed_records must be a list")
        if discriminator == "cross_session" and not records:
            raise ValueError(
                f"{where} is cross_session but has no seed_records; there "
                f"would be nothing for a later session to retrieve and the "
                f"goal would silently degrade to a capability test"
            )
        for record_index, record in enumerate(records):
            if (
                not isinstance(record, dict)
                or not str(record.get("title", "")).strip()
                or not str(record.get("body", "")).strip()
            ):
                raise ValueError(
                    f"{where} seed_records[{record_index}] needs a non-empty "
                    f"title and body"
                )


def load_goalset(path: Path) -> GoalSet:
    """Load, validate and hash the goal set at ``path``."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_goalset(payload, source=path.name)
    goals = tuple(
        Goal(
            id=entry["id"],
            goal=entry["goal"],
            children_hint=entry["children_hint"],
            discriminator=entry["discriminator"],
            discriminator_note=entry["discriminator_note"],
            solo_solvable=entry["solo_solvable"],
            seed_records=tuple(dict(r) for r in entry["seed_records"]),
        )
        for entry in payload["goals"]
    )
    return GoalSet(
        version=payload["goalset_version"],
        sha256=sha256_file(path),
        path=path,
        goals=goals,
    )
