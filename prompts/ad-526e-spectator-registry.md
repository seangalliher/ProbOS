# AD-526e v1: Spectator Registry — Recreation Read-Side Analytics

**Status:** Build prompt for Wave 70 (single-AD reframe of the AD-526c–h combo)
**Dependencies:** AD-526a (RecreationService), AD-526d (GamePreferenceTracker — pattern source)
**Estimated tests:** +12 (window [+10, +14])
**Baseline:** 11419 → expected 11431
**HEAD:** `66c89ff`

## Problem

ProbOS recreation games (`RecreationService` AD-526a) currently support exactly two participant roles per game: challenger and challenged. There is no surface for a third agent to observe a running game, post commentary about it, or react to a finished game.

The AD-526d docstring explicitly names spectator commentary as one of the four siblings that will share the read-side analytics pattern (`src/probos/recreation/preferences.py:4-6`):

```python
"""AD-526d: Game preference tracking.

Per-agent per-game-type play frequency. Read-side analytics surface
exposing the data-collection hook that AD-526e/f/g/h (spectator
commentary, holodeck integration, creative content, chess engine)
will share.
"""
```

But no producer or store has been wired. AD-526e v1 ships the missing analytics surface as a thin, in-memory, observation-only registry. Producer wiring (cognitive integration, end-of-game cleanup, HXI rendering) is deferred to AD-526e-1/-2/-3.

## Solution

New `src/probos/recreation/spectators.py` with a single `SpectatorRegistry` class that mirrors `GamePreferenceTracker` (AD-526d) shape exactly:

- In-memory dicts (no persistence).
- 2 new EventTypes: `RECREATION_SPECTATOR_JOINED`, `RECREATION_SPECTATOR_COMMENTARY`.
- Late-bind `set_event_callback(emit_fn)` (Wave-5 convention #1).
- Public attribute `runtime.recreation_spectator_registry` (constructor-wired in `runtime.py`, mirror of AD-526d block at `runtime.py:457-461`).
- Tier-2 log-and-degrade on emit failure (state mutation NOT wrapped — only emits).
- 14 boundary tests in a new file.

**No service-side change** to `RecreationService`, `GameEngine`, `TicTacToeEngine`, or `WardRoomService`. **No new Pydantic config.** **No producer wiring** — agents do NOT call `add_spectator` or `record_commentary` in v1.

---

## Section 1 — Add 2 new EventTypes

**File:** `src/probos/events.py`
**Mode:** SEARCH/REPLACE
**Insertion point:** directly below the existing AD-526c `RECREATION_GAME_REGISTERED` line at line 232. Mirror placement of sibling. Do NOT introduce a new `# ── ` section header (AD-526e is a sibling of AD-526c/d, not a new family).

```search
    RECREATION_GAME_REGISTERED = "recreation_game_registered"  # AD-526c
    CONTRASTIVE_RECALL = "contrastive_recall"  # AD-655
```

```replace
    RECREATION_GAME_REGISTERED = "recreation_game_registered"  # AD-526c
    RECREATION_SPECTATOR_JOINED = "recreation_spectator_joined"  # AD-526e
    RECREATION_SPECTATOR_COMMENTARY = "recreation_spectator_commentary"  # AD-526e
    CONTRASTIVE_RECALL = "contrastive_recall"  # AD-655
```

---

## Section 2 — New module `src/probos/recreation/spectators.py`

**File:** `src/probos/recreation/spectators.py`
**Mode:** CREATE (full file content)

```python
"""AD-526e: Spectator Registry — Recreation read-side analytics.

Tracks per-game spectator membership and per-game commentary as a thin
in-memory surface. Mirrors the AD-526d ``GamePreferenceTracker`` shape
(read-side analytics first, producers wired in -1/-2/-3 children).

Public API (Wave-5 convention #1: no leading underscore):

- ``add_spectator(game_id, agent_id) -> bool`` — idempotent; returns True
  on first add per (game_id, agent_id) and emits
  ``RECREATION_SPECTATOR_JOINED``; returns False on duplicate without
  re-emitting.
- ``remove_spectator(game_id, agent_id) -> bool`` — returns True when the
  agent was a spectator (silent no event).
- ``get_spectators(game_id) -> tuple[str, ...]`` — frozen tuple of
  agent_ids in insertion order.
- ``record_commentary(game_id, agent_id, text) -> None`` — empty-suppress
  on missing inputs; emits ``RECREATION_SPECTATOR_COMMENTARY``.
- ``get_commentary(game_id) -> tuple[dict[str, Any], ...]`` — frozen tuple
  of ``{"agent_id": str, "text": str, "timestamp": float}`` entries in
  insertion order.
- ``clear_game(game_id) -> None`` — drop all spectators and commentary
  for a game; intended for the future AD-526e-2 end-of-game wiring.
- ``set_event_callback(emit_fn)`` — late-bind event emission (mirrors
  ``BilletRegistry`` and ``GamePreferenceTracker``).

Lifecycle is best-effort (Wave-5 tier-2): swallow emit-side exceptions,
log, continue. State-mutation exceptions (e.g. non-string agent_id) are
NOT wrapped — they fail loud.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


class SpectatorRegistry:
    """Per-game spectator membership + commentary log. AD-526e v1."""

    def __init__(self) -> None:
        self._spectators: dict[str, list[str]] = {}  # game_id -> ordered agent_ids
        self._commentary: dict[str, list[dict[str, Any]]] = {}  # game_id -> entries
        self._emit_event_fn: Callable[..., None] | None = None

    # ------------------------------------------------------------------
    # Public API (Wave-5 convention #1: no leading underscore)
    # ------------------------------------------------------------------

    def set_event_callback(
        self, emit_fn: Callable[..., None],
    ) -> None:
        """Late-bind event emission callback (mirror BilletRegistry pattern)."""
        self._emit_event_fn = emit_fn

    def add_spectator(self, game_id: str, agent_id: str) -> bool:
        """Idempotently add ``agent_id`` to the spectator list for ``game_id``.

        Returns True when newly added (and emits
        ``RECREATION_SPECTATOR_JOINED``); False on duplicate without
        re-emitting. No-op + return False on empty inputs.
        """
        if not game_id or not agent_id:
            return False
        agents = self._spectators.setdefault(game_id, [])
        if agent_id in agents:
            return False
        agents.append(agent_id)
        if self._emit_event_fn is not None:
            try:
                self._emit_event_fn(
                    EventType.RECREATION_SPECTATOR_JOINED,
                    {
                        "game_id": game_id,
                        "agent_id": agent_id,
                        "spectator_count": len(agents),
                    },
                )
            except Exception:
                logger.warning(
                    "AD-526e: RECREATION_SPECTATOR_JOINED emit failed for %s/%s",
                    game_id, agent_id, exc_info=True,
                )
        return True

    def remove_spectator(self, game_id: str, agent_id: str) -> bool:
        """Remove ``agent_id`` from the spectator list for ``game_id``.

        Returns True when the agent was present and removed; False when
        the agent was not a spectator. Does NOT emit (mirrors AD-526d's
        no-removal-event pattern).
        """
        if not game_id or not agent_id:
            return False
        agents = self._spectators.get(game_id)
        if agents is None or agent_id not in agents:
            return False
        agents.remove(agent_id)
        return True

    def get_spectators(self, game_id: str) -> tuple[str, ...]:
        """Return frozen tuple of spectator agent_ids in insertion order."""
        agents = self._spectators.get(game_id)
        if agents is None:
            return ()
        return tuple(agents)

    def record_commentary(
        self, game_id: str, agent_id: str, text: str,
    ) -> None:
        """Record a commentary entry for ``game_id``.

        No-op when any input is empty/whitespace-only. Best-effort on event
        emission failure.
        """
        if not game_id or not agent_id or not text or not text.strip():
            return
        entry: dict[str, Any] = {
            "agent_id": agent_id,
            "text": text,
            "timestamp": time.time(),
        }
        entries = self._commentary.setdefault(game_id, [])
        entries.append(entry)
        if self._emit_event_fn is not None:
            try:
                self._emit_event_fn(
                    EventType.RECREATION_SPECTATOR_COMMENTARY,
                    {
                        "game_id": game_id,
                        "agent_id": agent_id,
                        "comment_count": len(entries),
                    },
                )
            except Exception:
                logger.warning(
                    "AD-526e: RECREATION_SPECTATOR_COMMENTARY emit failed for %s/%s",
                    game_id, agent_id, exc_info=True,
                )

    def get_commentary(self, game_id: str) -> tuple[dict[str, Any], ...]:
        """Return frozen tuple of commentary entries in insertion order.

        Each entry is ``{"agent_id": str, "text": str, "timestamp": float}``.
        Caller MUST NOT mutate the returned dicts.
        """
        entries = self._commentary.get(game_id)
        if entries is None:
            return ()
        return tuple(entries)

    def clear_game(self, game_id: str) -> None:
        """Drop all spectators and commentary for ``game_id``.

        Intended for the future AD-526e-2 end-of-game RecreationService
        wiring. Safe to call on unknown ``game_id`` (no-op).
        """
        if not game_id:
            return
        self._spectators.pop(game_id, None)
        self._commentary.pop(game_id, None)
```

---

## Section 3 — Wire into `runtime.py`

**File:** `src/probos/runtime.py`
**Mode:** SEARCH/REPLACE
**Insertion point:** directly below the AD-526d `recreation_preference_tracker` block at line 461. Mirror block exactly.

```search
        # --- Recreation Preference Tracker (AD-526d) ---
        from probos.recreation.preferences import GamePreferenceTracker
        self.recreation_preference_tracker: GamePreferenceTracker = (
            GamePreferenceTracker()
        )
        self.recreation_preference_tracker.set_event_callback(self.emit_event)

        # --- TaskEvent Dispatcher (AD-654c) ---
```

```replace
        # --- Recreation Preference Tracker (AD-526d) ---
        from probos.recreation.preferences import GamePreferenceTracker
        self.recreation_preference_tracker: GamePreferenceTracker = (
            GamePreferenceTracker()
        )
        self.recreation_preference_tracker.set_event_callback(self.emit_event)

        # --- Recreation Spectator Registry (AD-526e) ---
        from probos.recreation.spectators import SpectatorRegistry
        self.recreation_spectator_registry: SpectatorRegistry = SpectatorRegistry()
        self.recreation_spectator_registry.set_event_callback(self.emit_event)

        # --- TaskEvent Dispatcher (AD-654c) ---
```

---

## Section 4 — New test file `tests/test_ad526e_spectator_registry.py`

**File:** `tests/test_ad526e_spectator_registry.py`
**Mode:** CREATE (full file content)

```python
"""AD-526e: SpectatorRegistry tests."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from probos.events import EventType
from probos.recreation.spectators import SpectatorRegistry


# ----------------------------------------------------------------------
# Section 1 — EventType existence
# ----------------------------------------------------------------------


def test_event_type_recreation_spectator_joined_exists() -> None:
    assert EventType.RECREATION_SPECTATOR_JOINED.value == "recreation_spectator_joined"


def test_event_type_recreation_spectator_commentary_exists() -> None:
    assert (
        EventType.RECREATION_SPECTATOR_COMMENTARY.value
        == "recreation_spectator_commentary"
    )


# ----------------------------------------------------------------------
# Section 2 — add_spectator / remove_spectator behavior
# ----------------------------------------------------------------------


def test_add_spectator_first_call_returns_true_and_emits() -> None:
    emit = MagicMock()
    reg = SpectatorRegistry()
    reg.set_event_callback(emit)
    assert reg.add_spectator("g1", "a1") is True
    assert emit.call_count == 1
    args, _ = emit.call_args
    assert args[0] is EventType.RECREATION_SPECTATOR_JOINED
    assert args[1] == {"game_id": "g1", "agent_id": "a1", "spectator_count": 1}


def test_add_spectator_duplicate_returns_false_and_does_not_re_emit() -> None:
    emit = MagicMock()
    reg = SpectatorRegistry()
    reg.set_event_callback(emit)
    assert reg.add_spectator("g1", "a1") is True
    assert reg.add_spectator("g1", "a1") is False
    assert emit.call_count == 1


def test_remove_spectator_present_returns_true() -> None:
    reg = SpectatorRegistry()
    reg.add_spectator("g1", "a1")
    assert reg.remove_spectator("g1", "a1") is True
    assert reg.get_spectators("g1") == ()


def test_remove_spectator_absent_returns_false() -> None:
    reg = SpectatorRegistry()
    assert reg.remove_spectator("g1", "a1") is False
    reg.add_spectator("g1", "a1")
    assert reg.remove_spectator("g1", "a2") is False


# ----------------------------------------------------------------------
# Section 3 — get_spectators ordering + frozen contract
# ----------------------------------------------------------------------


def test_get_spectators_returns_frozen_tuple_in_insertion_order() -> None:
    reg = SpectatorRegistry()
    reg.add_spectator("g1", "a1")
    reg.add_spectator("g1", "a2")
    reg.add_spectator("g1", "a3")
    spectators = reg.get_spectators("g1")
    assert isinstance(spectators, tuple)
    assert spectators == ("a1", "a2", "a3")


def test_get_spectators_unknown_game_returns_empty_tuple() -> None:
    reg = SpectatorRegistry()
    assert reg.get_spectators("nonexistent") == ()


# ----------------------------------------------------------------------
# Section 4 — record_commentary + get_commentary
# ----------------------------------------------------------------------


def test_record_commentary_stores_entry_and_emits_event() -> None:
    emit = MagicMock()
    reg = SpectatorRegistry()
    reg.set_event_callback(emit)
    reg.record_commentary("g1", "a1", "Nice move!")
    entries = reg.get_commentary("g1")
    assert len(entries) == 1
    assert entries[0]["agent_id"] == "a1"
    assert entries[0]["text"] == "Nice move!"
    assert isinstance(entries[0]["timestamp"], float)
    assert emit.call_count == 1
    args, _ = emit.call_args
    assert args[0] is EventType.RECREATION_SPECTATOR_COMMENTARY
    assert args[1] == {"game_id": "g1", "agent_id": "a1", "comment_count": 1}


def test_record_commentary_empty_inputs_no_op() -> None:
    emit = MagicMock()
    reg = SpectatorRegistry()
    reg.set_event_callback(emit)
    reg.record_commentary("", "a1", "x")
    reg.record_commentary("g1", "", "x")
    reg.record_commentary("g1", "a1", "")
    reg.record_commentary("g1", "a1", "   ")  # whitespace-only suppressed
    assert reg.get_commentary("g1") == ()
    assert emit.call_count == 0


def test_get_commentary_returns_frozen_tuple_with_timestamp() -> None:
    reg = SpectatorRegistry()
    reg.record_commentary("g1", "a1", "first")
    reg.record_commentary("g1", "a2", "second")
    entries = reg.get_commentary("g1")
    assert isinstance(entries, tuple)
    assert len(entries) == 2
    assert entries[0]["text"] == "first"
    assert entries[1]["text"] == "second"
    assert entries[0]["timestamp"] <= entries[1]["timestamp"]


# ----------------------------------------------------------------------
# Section 5 — clear_game lifecycle
# ----------------------------------------------------------------------


def test_clear_game_drops_spectators_and_commentary() -> None:
    reg = SpectatorRegistry()
    reg.add_spectator("g1", "a1")
    reg.add_spectator("g1", "a2")
    reg.record_commentary("g1", "a1", "hi")
    reg.clear_game("g1")
    assert reg.get_spectators("g1") == ()
    assert reg.get_commentary("g1") == ()
    # Safe to call on unknown game_id
    reg.clear_game("nonexistent")


# ----------------------------------------------------------------------
# Section 6 — emit-failure log-and-degrade
# ----------------------------------------------------------------------


def test_emit_failure_logged_and_swallowed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def bad_emit(*_args, **_kwargs):
        raise RuntimeError("emitter exploded")

    reg = SpectatorRegistry()
    reg.set_event_callback(bad_emit)
    with caplog.at_level(logging.WARNING):
        # State mutation must succeed despite emit failure
        assert reg.add_spectator("g1", "a1") is True
        reg.record_commentary("g1", "a1", "comment")
    assert reg.get_spectators("g1") == ("a1",)
    assert len(reg.get_commentary("g1")) == 1
    assert any("AD-526e" in rec.message for rec in caplog.records)


# ----------------------------------------------------------------------
# Section 7 — runtime wiring (no-boot smoke)
# ----------------------------------------------------------------------


def test_runtime_wires_recreation_spectator_registry_with_callback() -> None:
    """Verify runtime.py constructs SpectatorRegistry + binds emit_event.

    Reads runtime.py source directly to avoid booting a real ProbOSRuntime
    (per Wave 13/66/67 fixture precedent — full-runtime fixtures explode
    wave-gate runtime budget).
    """
    from pathlib import Path

    runtime_src = Path(__file__).resolve().parents[1] / "src" / "probos" / "runtime.py"
    text = runtime_src.read_text(encoding="utf-8")
    assert "from probos.recreation.spectators import SpectatorRegistry" in text
    assert (
        "self.recreation_spectator_registry: SpectatorRegistry = SpectatorRegistry()"
        in text
    )
    assert (
        "self.recreation_spectator_registry.set_event_callback(self.emit_event)"
        in text
    )
```

---

## What this AD does NOT change

- `src/probos/recreation/service.py` — RecreationService is not extended; `complete_game` does not call `clear_game` (deferred AD-526e-2).
- `src/probos/recreation/engine.py` — GameEngine protocol is not extended.
- `src/probos/recreation/metadata.py` — GameMetadata is not extended.
- `src/probos/recreation/preferences.py` — GamePreferenceTracker is not modified.
- `src/probos/recreation/__init__.py` — public surface re-exports are not changed (callers use `from probos.recreation.spectators import SpectatorRegistry` directly, mirror of AD-526d's pattern at `runtime.py:457`).
- `src/probos/cognitive/cognitive_agent.py` — no `[SPECTATE]` / `[COMMENT]` action tags (deferred AD-526e-1).
- `src/probos/cognitive/proactive.py` — no spectator-action extraction (deferred AD-526e-1).
- `src/probos/config.py` — no Pydantic config field added.
- `config/system.yaml` — no config block added.
- `src/probos/startup/finalize.py` — no finalize-side wirer (constructor-wired in `runtime.py`, mirror AD-526d).
- `ui/src/components/GamePanel.tsx` — no UI rendering of spectators/commentary (deferred AD-526e-3).

## Tracking updates (after final gate passes)

1. `PROGRESS.md` — append CLOSED paragraph for AD-526e v1 + the Wave 70 partial-close stance for #101.
2. `docs/development/roadmap.md:3042` — flip the AD-526e entry from `*(planned, depends: AD-526a)*` to `*(complete via AD-526e v1, Wave 70 — observational SpectatorRegistry; cognitive integration deferred to AD-526e-1, end-of-game cleanup wiring deferred to AD-526e-2, HXI rendering deferred to AD-526e-3)*`.
3. `prompts/wave-plan.yaml` (id 70) — `status: done`. Note: "Reframed combo → single AD; 2 of 6 already shipped (c partial, d full), 3 of 6 deferred with forcing functions (f→AD-486 Holodeck, g→AD-525b/d, h→python-chess dep decision), 1 of 6 shipping (e)."
4. GH issue #101 — close with comment listing the six child statuses + this commit hash + the three forcing functions.

## Acceptance Criteria

1. Full gate passes at 11431 ± 2.
2. All Section 1–4 SEARCH/REPLACE blocks applied byte-for-byte as specified.
3. 14 new tests in `tests/test_ad526e_spectator_registry.py` all pass.
4. No file outside the dispatch's named set is modified (other than tracking files: `PROGRESS.md`, `docs/development/roadmap.md`, `prompts/wave-plan.yaml`).
5. The Builder build report cites the test count delta + the seven "what this AD does NOT change" verifications.
6. The Builder build report explicitly cites that AD-526f/g/h were NOT shipped this wave and names the three forcing functions.
7. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-05, HEAD `66c89ff`)

```
grep -n "RECREATION_GAME_REGISTERED" src/probos/events.py
  232:  RECREATION_GAME_REGISTERED = "recreation_game_registered"  # AD-526c

grep -n "GAME_PREFERENCE_RECORDED" src/probos/events.py
  312:  GAME_PREFERENCE_RECORDED = "game_preference_recorded"  # AD-526d

grep -n "RECREATION_SPECTATOR" src/probos/events.py
  (no matches — collision-free)

grep -n "recreation_preference_tracker" src/probos/runtime.py
  458:  self.recreation_preference_tracker: GamePreferenceTracker = (
  461:  self.recreation_preference_tracker.set_event_callback(self.emit_event)

grep -n "recreation_spectator_registry" src/probos/runtime.py
  (no matches — collision-free)

ls src/probos/recreation/
  __init__.py  engine.py  metadata.py  preferences.py  service.py
  (NO spectators.py — net-new file confirmed)

grep -n "test_ad526e" tests/
  (no matches — net-new test file confirmed)
```
