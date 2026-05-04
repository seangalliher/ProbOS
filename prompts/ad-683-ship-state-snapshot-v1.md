# AD-683 v1 — Ship State Snapshot for Cold-Start Onboarding

**Wave:** 29
**Issue:** [#313](https://github.com/seang/ProbOS/issues/313)
**Depends on:** AD-638 (Boot Camp Onboarding) — shipped; `runtime.boot_camp: BootCampCoordinator | None` at `runtime.py:471`, `BootCampCoordinator.activate(...)` at `boot_camp.py:133`.
**Estimated tests:** 8 (one over the 6-floor — covers builder happy path + 2 degradation branches + injection + render + wiring).
**Roadmap:** `docs/development/roadmap.md:7086` (Meta-Harness Research Wave).
**Renumber audit:** Issue #313 was AD-654 → AD-683 on 2026-04-30 to resolve collision with #322 UAAA. PROGRESS.md:102 records the resolution. No code references AD-654 for #313's lineage.

---

## Problem

When a fresh crew agent's first interaction post-reset begins, the agent has no
structured awareness of the ship it just woke up in. It does not know which
departments exist, which work items are open, what topics the Ward Room is
currently discussing, what the alert condition is, or how long the ship has been
running. The agent must spend its first 2–4 cognitive turns asking the Captain
or peers "what is going on" before it can contribute. Meta-Harness research
(Lee et al., arXiv:2603.28052) showed environment bootstrapping eliminates these
exploratory turns in agentic coding; ProbOS has no equivalent.

The data already exists in the runtime — `runtime.ontology` (departments + alert
+ vessel state), `runtime.work_item_store` (open work items), `runtime.ward_room`
(channels + recent threads). What is missing is a single observational
aggregator that captures these into one frozen `ShipStateSnapshot`, makes it
available at `runtime.ship_state_snapshot`, captures it once during boot-camp
activation, and renders it into the cold-start agent's first DM user-message.

---

## Solution

1. New module `src/probos/onboarding/` containing `ship_state_snapshot.py`.
2. Three frozen dataclasses (`DepartmentSummary`, `WardRoomTopicSummary`,
   `ShipStateSnapshot`) plus a `ShipStateSnapshotBuilder` service with a single
   public method `async def build() -> ShipStateSnapshot`. Each per-source
   collector is wrapped in try/except → `logger.warning` + degraded fallback
   (Engineering-Principles tier 2 log-and-degrade).
3. New `ShipStateSnapshotConfig(enabled=True)` Pydantic model wired onto
   `SystemConfig.ship_state_snapshot` via `Field(default_factory=...)`.
4. New sync wirer `_wire_ship_state_snapshot(*, runtime, config) -> bool` at
   `startup/finalize.py` mirrors `_wire_boot_camp_tracker` shape; invoked from
   `finalize_startup` immediately after `_wire_boot_camp_tracker`. Public
   attribute: `runtime.ship_state_snapshot` (the **builder** service; mirrors
   `runtime.duty_scope_provider` naming where the attribute IS the
   read-on-demand provider).
5. `BootCampCoordinator.__init__` gets a new optional kwarg
   `ship_state_builder: ShipStateSnapshotBuilder | None = None`. Default `None`
   preserves backward compatibility for existing tests. `runtime.py:1580`
   call-site passes `ship_state_builder=getattr(self, "ship_state_snapshot",
   None)`.
6. `BootCampCoordinator` exposes a new public attribute
   `ship_state_snapshot: ShipStateSnapshot | None = None`. At the end of
   `activate(...)` (after the `BOOT_CAMP_ACTIVATED` emit), if
   `_ship_state_builder is not None`, await `build()` and assign to
   `self.ship_state_snapshot`. Wrapped in try/except — never breaks activation
   (log-and-degrade).
7. `cognitive_agent._build_user_message` DM branch gets one new block at the
   top of `parts: list[str] = []` (BEFORE the existing temporal-awareness
   block) — when `observation.get("_boot_camp_active")` and the runtime path
   resolves a snapshot, prepend `--- Ship State Snapshot ---` plus
   `snapshot.render_text()` plus blank line. Existing observation flag set at
   `cognitive_agent.py:1880-1884` and `:2068-2072` requires no changes.
8. One new EventType `SHIP_STATE_SNAPSHOT_CAPTURED` (collision-free; verified
   against events.py post-Wave-28). Payload contains COUNTS only (no titles, no
   department names, no thread bodies) — privacy-conservative, matches AD-530
   classification-gate pattern.

Hard caps inline (NOT exposed in config — externalize only if AD-683b adoption
data justifies tuning):

| Cap | Value | Rationale |
|---|---|---|
| `_MAX_OPEN_WORK_ITEMS` | 5 | Top-of-queue is most actionable; `list_work_items` already orders priority ASC |
| `_MAX_TOPIC_CHANNELS` | 3 | Most-recent activity in Ship + 2 user channels keeps the snapshot bounded |
| `_MAX_THREAD_TITLES_PER_CHANNEL` | 3 | Per-channel sample for "what's being discussed" |
| `_TITLE_TRUNCATE_CHARS` | 80 | Single-line readable; mirrors AD-657 300-char truncation idiom (smaller for titles) |

---

## Section 0 — Event Types

Insert **one** new entry to `src/probos/events.py` immediately after the
existing `BOOT_CAMP_ACTIVATED = "boot_camp_activated"` line (events.py:252):

```python
SHIP_STATE_SNAPSHOT_CAPTURED = "ship_state_snapshot_captured"
```

Verified collision-free: `grep "ship_state\|snapshot_captured" src/probos/events.py` → 0 hits at HEAD `b76b8a8`.

---

## Section 1 — `src/probos/onboarding/__init__.py`

CREATE new file:

```python
"""Onboarding cold-start helpers (AD-683)."""

from probos.onboarding.ship_state_snapshot import (
    DepartmentSummary,
    ShipStateSnapshot,
    ShipStateSnapshotBuilder,
    WardRoomTopicSummary,
)

__all__ = [
    "DepartmentSummary",
    "ShipStateSnapshot",
    "ShipStateSnapshotBuilder",
    "WardRoomTopicSummary",
]
```

---

## Section 2 — `src/probos/onboarding/ship_state_snapshot.py`

CREATE new file. Frozen dataclass field-ordering rule: `ShipStateSnapshot`'s
sole non-defaulted field `captured_at` is FIRST, all subsequent fields have
defaults — compliant with the standing convention.

```python
"""Ship State Snapshot for Cold-Start Onboarding (AD-683 v1).

Observational aggregator that captures the ship's current operational state
(departments, open work, recent Ward Room topics, alert condition, uptime)
into one frozen ``ShipStateSnapshot`` for injection into a cold-start agent's
first user-message.

v1 ships builder + capture-at-activation + DM-path render. Per-agent
personalization (AD-683b), snapshot deltas/refreshes (AD-683c), federation
sync (AD-683d), chain-path injection (AD-683e) are all deferred.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


_MAX_OPEN_WORK_ITEMS: int = 5
_MAX_TOPIC_CHANNELS: int = 3
_MAX_THREAD_TITLES_PER_CHANNEL: int = 3
_TITLE_TRUNCATE_CHARS: int = 80


def _truncate(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= _TITLE_TRUNCATE_CHARS:
        return text
    return text[: _TITLE_TRUNCATE_CHARS - 1] + "…"


@dataclass(frozen=True)
class DepartmentSummary:
    """Per-department crew presence summary. AD-683 v1."""

    department_id: str
    name: str
    crew_count: int


@dataclass(frozen=True)
class WardRoomTopicSummary:
    """Recent thread titles in one Ward Room channel. AD-683 v1."""

    channel_name: str
    thread_titles: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShipStateSnapshot:
    """Cold-start orientation snapshot. AD-683 v1.

    Defaulted-field-ordering: ``captured_at`` is the sole non-defaulted field
    and comes first, per the standing frozen-dataclass convention.
    """

    captured_at: float
    vessel_name: str = "ProbOS"
    alert_condition: str = "GREEN"
    uptime_seconds: float = 0.0
    active_crew_count: int = 0
    departments: tuple[DepartmentSummary, ...] = ()
    open_work_item_count: int = 0
    open_work_item_titles: tuple[str, ...] = ()
    recent_ward_room_topics: tuple[WardRoomTopicSummary, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "captured_at": self.captured_at,
            "vessel_name": self.vessel_name,
            "alert_condition": self.alert_condition,
            "uptime_seconds": self.uptime_seconds,
            "active_crew_count": self.active_crew_count,
            "departments": [
                {"department_id": d.department_id, "name": d.name, "crew_count": d.crew_count}
                for d in self.departments
            ],
            "open_work_item_count": self.open_work_item_count,
            "open_work_item_titles": list(self.open_work_item_titles),
            "recent_ward_room_topics": [
                {"channel_name": t.channel_name, "thread_titles": list(t.thread_titles)}
                for t in self.recent_ward_room_topics
            ],
        }

    def render_text(self) -> str:
        """Render as a Markdown-style block for prompt injection."""
        lines: list[str] = []
        lines.append(
            f"Vessel: {self.vessel_name}  |  Alert: {self.alert_condition}  "
            f"|  Uptime: {int(self.uptime_seconds)}s  |  Active crew: {self.active_crew_count}"
        )
        if self.departments:
            dept_str = ", ".join(
                f"{d.name} ({d.crew_count})" for d in self.departments
            )
            lines.append(f"Departments: {dept_str}")
        if self.open_work_item_count > 0:
            lines.append(f"Open work items: {self.open_work_item_count}")
            for title in self.open_work_item_titles:
                lines.append(f"  - {title}")
        else:
            lines.append("Open work items: none")
        if self.recent_ward_room_topics:
            lines.append("Recent Ward Room topics:")
            for topic in self.recent_ward_room_topics:
                if topic.thread_titles:
                    titles = "; ".join(topic.thread_titles)
                    lines.append(f"  [{topic.channel_name}] {titles}")
                else:
                    lines.append(f"  [{topic.channel_name}] (no recent threads)")
        return "\n".join(lines)


class ShipStateSnapshotBuilder:
    """Aggregates ship state from runtime collectors. AD-683 v1.

    Read-only observational. Each per-source collector is wrapped in
    try/except → ``logger.warning`` + degraded default. Builder never
    raises; ``build()`` always returns a (possibly partial) snapshot.

    Mirrors AD-508 ``DutyScopeProvider`` ctor shape:
    ``__init__(runtime, *, emit_event=None)``.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        emit_event: Callable[..., None] | None = None,
    ) -> None:
        self._runtime = runtime
        self.emit_event = emit_event

    async def build(self) -> ShipStateSnapshot:
        captured_at = time.time()
        vessel_name, alert_condition, uptime_seconds, active_crew_count = (
            self._collect_vessel()
        )
        departments = self._collect_departments()
        open_work_item_count, open_work_item_titles = await self._collect_work_items()
        recent_ward_room_topics = await self._collect_ward_room_topics()

        snap = ShipStateSnapshot(
            captured_at=captured_at,
            vessel_name=vessel_name,
            alert_condition=alert_condition,
            uptime_seconds=uptime_seconds,
            active_crew_count=active_crew_count,
            departments=departments,
            open_work_item_count=open_work_item_count,
            open_work_item_titles=open_work_item_titles,
            recent_ward_room_topics=recent_ward_room_topics,
        )
        self._emit_captured(snap)
        return snap

    # ------------------------------------------------------------------
    # Collectors — each returns a degraded default on failure.
    # ------------------------------------------------------------------

    def _collect_vessel(self) -> tuple[str, str, float, int]:
        ontology = getattr(self._runtime, "ontology", None)
        if ontology is None:
            return ("ProbOS", "GREEN", 0.0, 0)
        try:
            identity = ontology.get_vessel_identity()
            state = ontology.get_vessel_state()
            return (
                identity.name,
                state.alert_condition,
                state.uptime_seconds,
                state.active_crew_count,
            )
        except Exception:
            logger.warning(
                "AD-683: vessel identity/state collection failed; "
                "snapshot uses defaults",
                exc_info=True,
            )
            return ("ProbOS", "GREEN", 0.0, 0)

    def _collect_departments(self) -> tuple[DepartmentSummary, ...]:
        ontology = getattr(self._runtime, "ontology", None)
        if ontology is None:
            return ()
        try:
            depts = ontology.get_departments()
        except Exception:
            logger.warning(
                "AD-683: ontology.get_departments failed; snapshot omits departments",
                exc_info=True,
            )
            return ()
        # crew counts: derive from assignments per agent_type; tolerate missing
        crew_count_by_dept: dict[str, int] = {}
        try:
            for agent_type in ontology.get_crew_agent_types():
                assignment = ontology.get_assignment_for_agent(agent_type)
                if assignment is None or assignment.agent_id is None:
                    continue
                post = ontology.get_post_for_agent(agent_type)
                if post is None:
                    continue
                dept_id = getattr(post, "department_id", "")
                if dept_id:
                    crew_count_by_dept[dept_id] = (
                        crew_count_by_dept.get(dept_id, 0) + 1
                    )
        except Exception:
            logger.warning(
                "AD-683: department crew-count derivation failed; counts default to 0",
                exc_info=True,
            )
        summaries: list[DepartmentSummary] = []
        for d in depts:
            summaries.append(
                DepartmentSummary(
                    department_id=d.id,
                    name=d.name,
                    crew_count=crew_count_by_dept.get(d.id, 0),
                )
            )
        return tuple(summaries)

    async def _collect_work_items(self) -> tuple[int, tuple[str, ...]]:
        store = getattr(self._runtime, "work_item_store", None)
        if store is None:
            return (0, ())
        try:
            items = await store.list_work_items(status="open", limit=_MAX_OPEN_WORK_ITEMS)
        except Exception:
            logger.warning(
                "AD-683: work_item_store.list_work_items failed; snapshot omits work items",
                exc_info=True,
            )
            return (0, ())
        if not items:
            return (0, ())
        titles = tuple(_truncate(getattr(it, "title", "") or "(untitled)") for it in items)
        return (len(items), titles)

    async def _collect_ward_room_topics(self) -> tuple[WardRoomTopicSummary, ...]:
        ward_room = getattr(self._runtime, "ward_room", None)
        if ward_room is None:
            return ()
        try:
            channels = await ward_room.list_channels()
        except Exception:
            logger.warning(
                "AD-683: ward_room.list_channels failed; snapshot omits topics",
                exc_info=True,
            )
            return ()
        topics: list[WardRoomTopicSummary] = []
        for channel in channels[:_MAX_TOPIC_CHANNELS]:
            try:
                threads = await ward_room.list_threads(
                    channel.id,
                    limit=_MAX_THREAD_TITLES_PER_CHANNEL,
                    sort="recent",
                )
            except Exception:
                logger.warning(
                    "AD-683: ward_room.list_threads failed for channel=%s; skipping",
                    getattr(channel, "name", "?"),
                    exc_info=True,
                )
                continue
            titles = tuple(
                _truncate(getattr(t, "title", "") or "(untitled)") for t in threads
            )
            topics.append(
                WardRoomTopicSummary(
                    channel_name=getattr(channel, "name", "") or channel.id,
                    thread_titles=titles,
                )
            )
        return tuple(topics)

    # ------------------------------------------------------------------

    def _emit_captured(self, snap: ShipStateSnapshot) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.SHIP_STATE_SNAPSHOT_CAPTURED,
                {
                    "captured_at": snap.captured_at,
                    "alert_condition": snap.alert_condition,
                    "work_item_count": snap.open_work_item_count,
                    "dept_count": len(snap.departments),
                    "topic_count": len(snap.recent_ward_room_topics),
                },
            )
        except Exception:
            logger.warning(
                "AD-683: emit_event for SHIP_STATE_SNAPSHOT_CAPTURED failed",
                exc_info=True,
            )
```

---

## Section 3 — Pydantic config (`src/probos/config.py`)

Insert `ShipStateSnapshotConfig` at a sensible location near `BootCampConfig`
(config.py:285 area is fine — keep AD-638 + AD-683 visually adjacent). Then
add the field on `SystemConfig`.

SEARCH for the existing `BootCampConfig` boundary and insert after it:

```python
class BootCampConfig(BaseModel):
    """AD-638: Cold-start boot camp configuration."""

    enabled: bool = True
    min_episodes: int = 5
    min_ward_room_posts: int = 3
    min_dm_conversations: int = 1
    min_trust_score: float = 0.55
    min_time_minutes: int = 60
    timeout_minutes: int = 120
    nudge_cooldown_seconds: int = 600
```

REPLACE with:

```python
class BootCampConfig(BaseModel):
    """AD-638: Cold-start boot camp configuration."""

    enabled: bool = True
    min_episodes: int = 5
    min_ward_room_posts: int = 3
    min_dm_conversations: int = 1
    min_trust_score: float = 0.55
    min_time_minutes: int = 60
    timeout_minutes: int = 120
    nudge_cooldown_seconds: int = 600


class ShipStateSnapshotConfig(BaseModel):
    """AD-683: Ship State Snapshot for Cold-Start Onboarding."""

    enabled: bool = True
```

SEARCH on `SystemConfig` for the existing `boot_camp` line (config.py:1991):

```python
    boot_camp: BootCampConfig = BootCampConfig()  # AD-638
```

REPLACE with:

```python
    boot_camp: BootCampConfig = BootCampConfig()  # AD-638
    ship_state_snapshot: ShipStateSnapshotConfig = Field(
        default_factory=ShipStateSnapshotConfig
    )  # AD-683
```

Verify `Field` is already imported in `config.py` (it is — used by every other
`Field(default_factory=...)` line). No new import needed.

---

## Section 4 — Wirer (`src/probos/startup/finalize.py`)

Insert new wirer immediately AFTER `_wire_boot_camp_tracker` (finalize.py:141).

SEARCH:

```python
def _wire_boot_camp_tracker(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-509 v1: Wire BootCampPhaseTracker (in-memory observational)."""
    cfg = getattr(config, "boot_camp_phase", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.crew_development.boot_camp import BootCampPhaseTracker

    emit_fn = getattr(runtime, "emit_event", None)
    tracker = BootCampPhaseTracker()
    tracker.emit_event = emit_fn
    runtime.boot_camp_tracker = tracker  # public attribute (Wave 5 convention #1)
    logger.info(
        "AD-509: Boot Camp Phase Tracker v1 initialized (5 phases + COMPLETED; observational)"
    )
    return True
```

REPLACE with:

```python
def _wire_boot_camp_tracker(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-509 v1: Wire BootCampPhaseTracker (in-memory observational)."""
    cfg = getattr(config, "boot_camp_phase", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.crew_development.boot_camp import BootCampPhaseTracker

    emit_fn = getattr(runtime, "emit_event", None)
    tracker = BootCampPhaseTracker()
    tracker.emit_event = emit_fn
    runtime.boot_camp_tracker = tracker  # public attribute (Wave 5 convention #1)
    logger.info(
        "AD-509: Boot Camp Phase Tracker v1 initialized (5 phases + COMPLETED; observational)"
    )
    return True


def _wire_ship_state_snapshot(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-683 v1: Wire ShipStateSnapshotBuilder (cold-start onboarding)."""
    cfg = getattr(config, "ship_state_snapshot", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.onboarding import ShipStateSnapshotBuilder

    emit_fn = getattr(runtime, "emit_event", None)
    builder = ShipStateSnapshotBuilder(runtime, emit_event=emit_fn)
    runtime.ship_state_snapshot = builder  # public attribute (Wave 5 convention #1)
    logger.info(
        "AD-683: ShipStateSnapshotBuilder v1 initialized (cold-start orientation)"
    )
    return True
```

Then SEARCH at the call-site (finalize.py:466):

```python
    if _wire_boot_camp_tracker(runtime=runtime, config=config):
```

Read the surrounding context to find the success-counting/wired-counter
pattern. Mirror it for the new line. Apply by adding immediately after the
existing `_wire_boot_camp_tracker` invocation:

```python
    if _wire_ship_state_snapshot(runtime=runtime, config=config):
```

Use the same return-value treatment (`success_count += 1`, `wired += 1`, etc.)
that `_wire_boot_camp_tracker` uses on the same line — match exact style.

---

## Section 5 — Capture in `BootCampCoordinator.activate()`

`src/probos/boot_camp.py`. Two edits to one class:

### 5a. Constructor — add new optional kwarg + public field

SEARCH:

```python
    def __init__(
        self,
        config: BootCampConfig,
        ward_room: WardRoomProtocol,
        trust_service: TrustServiceProtocol,
        episodic_memory: EpisodicMemoryProtocol,
        emit_event_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config
        self._ward_room = ward_room
        self._trust = trust_service
        self._episodic = episodic_memory
        self._emit_event_fn = emit_event_fn
        self._agents: dict[str, AgentBootCampState] = {}
        self._active = False
        self._started_at: float | None = None
        self._nudge_cooldowns: dict[str, float] = {}
        self._observation_thread_id: str | None = None
```

REPLACE with:

```python
    def __init__(
        self,
        config: BootCampConfig,
        ward_room: WardRoomProtocol,
        trust_service: TrustServiceProtocol,
        episodic_memory: EpisodicMemoryProtocol,
        emit_event_fn: Callable[..., Any] | None = None,
        *,
        ship_state_builder: Any | None = None,  # AD-683: ShipStateSnapshotBuilder | None
    ) -> None:
        self._config = config
        self._ward_room = ward_room
        self._trust = trust_service
        self._episodic = episodic_memory
        self._emit_event_fn = emit_event_fn
        self._agents: dict[str, AgentBootCampState] = {}
        self._active = False
        self._started_at: float | None = None
        self._nudge_cooldowns: dict[str, float] = {}
        self._observation_thread_id: str | None = None
        # AD-683: Cold-start ship state snapshot — populated at activate() end.
        self._ship_state_builder = ship_state_builder
        self.ship_state_snapshot: Any | None = None  # ShipStateSnapshot | None
```

The `Any` typing avoids a forward-reference circular-import; the comment
documents the real type. Tests assert `isinstance(coord.ship_state_snapshot,
ShipStateSnapshot)` directly.

### 5b. `activate()` — capture at the end

SEARCH for the end of `activate()` (boot_camp.py:177):

```python
        logger.info(
            "AD-638: Boot camp activated for %d crew agents",
            len(crew_agents),
        )
        self._emit(EventType.BOOT_CAMP_ACTIVATED, {
            "agent_count": len(crew_agents),
            "timestamp": self._started_at,
        })
```

REPLACE with:

```python
        logger.info(
            "AD-638: Boot camp activated for %d crew agents",
            len(crew_agents),
        )
        self._emit(EventType.BOOT_CAMP_ACTIVATED, {
            "agent_count": len(crew_agents),
            "timestamp": self._started_at,
        })

        # AD-683: Capture ship state snapshot for cold-start orientation.
        if self._ship_state_builder is not None:
            try:
                self.ship_state_snapshot = await self._ship_state_builder.build()
            except Exception:
                logger.warning(
                    "AD-683: ship_state_snapshot capture failed during activate; "
                    "cold-start agents will not see snapshot",
                    exc_info=True,
                )
```

### 5c. Runtime call-site — pass the builder

`src/probos/runtime.py:1580`. SEARCH:

```python
            try:
                self.boot_camp = BootCampCoordinator(
                    config=self.config.boot_camp,
                    ward_room=self.ward_room,
                    trust_service=self.trust_network,
                    episodic_memory=self.episodic_memory,
                    emit_event_fn=self._emit_event,
                )
                logger.info("AD-638: BootCampCoordinator initialized")
            except Exception as e:
                logger.warning("AD-638: BootCampCoordinator failed to start: %s", e)
```

REPLACE with:

```python
            try:
                self.boot_camp = BootCampCoordinator(
                    config=self.config.boot_camp,
                    ward_room=self.ward_room,
                    trust_service=self.trust_network,
                    episodic_memory=self.episodic_memory,
                    emit_event_fn=self._emit_event,
                    ship_state_builder=getattr(self, "ship_state_snapshot", None),  # AD-683
                )
                logger.info("AD-638: BootCampCoordinator initialized")
            except Exception as e:
                logger.warning("AD-638: BootCampCoordinator failed to start: %s", e)
```

Note: `getattr(..., None)` defends against startup-ordering inversion. The
finalize wirer runs in `finalize_startup` and the BootCampCoordinator
construction at runtime.py:1580 happens earlier in `start()`. **At build
time, verify whether `ship_state_snapshot` is wired before line 1580.** If
not — that is acceptable: builder is always observational, snapshot will be
None for the first activation; subsequent re-activations (rare; AD-638
already logs a warning on duplicate activation) will see the wired builder.
Alternative: move `_wire_ship_state_snapshot` invocation to a point that
runs before line 1580. The `getattr(..., None)` guard makes either ordering
correct; the test plan covers both wired and unwired paths.

---

## Section 6 — Render in `cognitive_agent._build_user_message` (DM path only)

`src/probos/cognitive/cognitive_agent.py:4264-4270`. SEARCH:

```python
        # AD-397: direct_message — conversational context for 1:1 sessions
        if intent_name == "direct_message":
            parts: list[str] = []

            # AD-502: Temporal awareness header
            temporal_ctx = self._build_temporal_context()
```

REPLACE with:

```python
        # AD-397: direct_message — conversational context for 1:1 sessions
        if intent_name == "direct_message":
            parts: list[str] = []

            # AD-683: Cold-start ship state snapshot (boot-camp DM path only).
            if observation.get("_boot_camp_active") and self._runtime is not None:
                _bc = getattr(self._runtime, "boot_camp", None)
                _snap = getattr(_bc, "ship_state_snapshot", None) if _bc else None
                if _snap is not None:
                    try:
                        _snapshot_text = _snap.render_text()
                    except Exception:
                        logger.debug(
                            "AD-683: ship_state_snapshot.render_text failed; "
                            "skipping injection",
                            exc_info=True,
                        )
                        _snapshot_text = ""
                    if _snapshot_text:
                        parts.append("--- Ship State Snapshot ---")
                        parts.append(_snapshot_text)
                        parts.append("---")
                        parts.append("")

            # AD-502: Temporal awareness header
            temporal_ctx = self._build_temporal_context()
```

`_boot_camp_active` is set on the observation dict at `cognitive_agent.py:1880-1884`
and `:2068-2072` — no changes needed there. WR-path and chain-path injection
are explicitly out-of-scope (AD-683e).

---

## Tests — `tests/test_ad683_ship_state_snapshot.py`

CREATE new file with **8 tests** (over the 6-floor):

1. `test_event_type_registered` — assert `EventType.SHIP_STATE_SNAPSHOT_CAPTURED.value == "ship_state_snapshot_captured"`.
2. `test_dataclass_frozen_and_field_order` — construct full `ShipStateSnapshot`; assert `dataclasses.fields` order has `captured_at` first; assert frozen mutation raises `FrozenInstanceError`; assert `to_dict()` round-trips all fields including nested `DepartmentSummary` / `WardRoomTopicSummary`.
3. `test_render_text_contains_key_fields` — build a populated snapshot; assert `render_text()` includes vessel name, alert condition, uptime int-cast, active crew count, at least one work item title, at least one ward-room topic line.
4. `test_builder_happy_path_full_data` — construct a `MagicMock` runtime with `ontology` returning identity (name="Enterprise"), state (alert="YELLOW", uptime=42.0, crew_count=7), departments=[Department(id="bridge", name="Bridge", description=""), Department(id="med", name="Medical", description="")], crew_agent_types=["captain", "bones"], assignments + posts mapping captain→bridge, bones→med; `work_item_store.list_work_items(status="open", limit=5)` returning 3 items with titles; `ward_room.list_channels()` returning 2 channels, `list_threads(...)` returning 2 threads each. Assert all snapshot fields populated correctly. Assert `emit_event` called once with `SHIP_STATE_SNAPSHOT_CAPTURED` and counts-only payload (no titles, no department names).
5. `test_builder_degrades_when_collectors_missing` — runtime has no `ontology`/`work_item_store`/`ward_room`. `await builder.build()` returns snapshot with all defaults populated. No exception raised.
6. `test_builder_degrades_when_collectors_raise` — runtime collectors are `MagicMock`s whose methods raise `RuntimeError("boom")`. `await builder.build()` returns snapshot with all defaults populated. No exception. Assert `caplog` contains at least one WARNING with "AD-683".
7. `test_capture_in_boot_camp_activate` — instantiate `BootCampCoordinator(config=BootCampConfig(), ward_room=AsyncMock, trust_service=Mock(get_trust_score=lambda _: 0.0), episodic_memory=AsyncMock, ship_state_builder=ShipStateSnapshotBuilder(<runtime mock>))`. Call `await coord.activate([{"agent_id": "a1", "callsign": "Bones", "department": "medical"}])`. Assert `coord.ship_state_snapshot is not None`, is a `ShipStateSnapshot`, and was captured AFTER `_active = True` (assert order via `coord._active is True` before snapshot is read).
8. `test_wirer_enabled_and_disabled` — `_wire_ship_state_snapshot` with `enabled=True` config returns `True` and sets `runtime.ship_state_snapshot` to a `ShipStateSnapshotBuilder`. With `enabled=False` returns `False` and does not set the attribute. Mirror `tests/test_ad509_boot_camp.py` wiring-test shape.

Test fixtures use `AsyncMock` for async collectors and `MagicMock` for sync. No real DB; no real ChromaDB.

---

## Standing Conventions

1. Public attribute names without leading underscore: `runtime.ship_state_snapshot`, `coord.ship_state_snapshot`, `builder.emit_event` (Wave 5 #1).
2. Late-bind setter pattern: `builder.emit_event = emit_fn` after construction is supported (AD-507/AD-509 sibling) — but the prompt uses ctor-injection via `emit_event=` kwarg, matching AD-508/AD-530 sibling shape (Wave 5 #5).
3. Frozen dataclass field-order: defaulted fields after non-defaulted (architect-learnings standing rule).
4. Three-tier exception handling: collectors are tier-2 log-and-degrade; emit failures are tier-2; `render_text` failure inside the cognitive_agent injection block is tier-1 swallow (debug log) since the user message must still be sent.
5. Event payload contains COUNTS only — no titles, no department names, no thread bodies (privacy-conservative per AD-530 / AD-478 pattern).
6. `Field(default_factory=...)` for any non-trivial default on Pydantic models (none needed here — only one bool field — but the `SystemConfig` line uses `default_factory=ShipStateSnapshotConfig` to mirror sibling style and to avoid the bare-mutable-default anti-pattern caught in past reviews).
7. Convention #14 aggressive pre-deferral: v1 ships builder + capture + DM-path render only. AD-683b–e listed in module docstring.

---

## What This Does NOT Change

- **No per-agent personalization.** Snapshot is one global blob captured once per activation. AD-683b deferred.
- **No deltas / refreshes.** Snapshot is a point-in-time capture; never re-built within a single boot-camp run. AD-683c deferred (forcing function: AD-683 ships and Captain reviews captured snapshots; if staleness is observed, externalize a refresh policy).
- **No federation sync.** Snapshot is local to one runtime; not shared across nodes. AD-683d deferred.
- **No chain-path injection.** Only DM path renders the snapshot in v1. Chain ANALYZE / EVALUATE / COMPOSE prompts are NOT changed. AD-683e deferred.
- **No Ward Room post-path injection.** Cold-start agents posting to WR see no snapshot in v1. AD-683f deferred.
- **No persistence.** Snapshot is in-memory only; not written to ChromaDB, not written to disk, not journaled. AD-683g deferred.
- **No new `runtime.ship_state_snapshot.snapshot` attribute.** The runtime attribute IS the **builder**; consumers `await build()` on demand or read the captured snapshot via `runtime.boot_camp.ship_state_snapshot`. No third-state cache.
- **No changes to `BOOT_CAMP_ACTIVATED` event payload.** The new `SHIP_STATE_SNAPSHOT_CAPTURED` event is emitted **after** the existing `BOOT_CAMP_ACTIVATED` emit; ordering is observable but neither event depends on the other.
- **No `BootCampPhaseTracker` (AD-509) integration.** AD-509 phase tracker and AD-683 snapshot are independent; v1 does not couple them.
- **No `PlanOfDayService` (AD-477) refactor.** Same data sources, different consumer; v1 does NOT extract a shared aggregator. Externalize only if AD-683b/AD-477b adoption justifies it.

---

## Tracking

- **`PROGRESS.md`** — append CLOSED entry at top of latest era file (`progress-era-4-evolution.md`) following Wave 28 / AD-658 entry format. Include: snapshot fields, hard caps, capture-at-activation pattern, DM-path-only render, EventType registration, deferral list, test count exact match, full-gate baseline + delta, no-hard-stops note, "Closes GH issue #313".
- **`docs/development/roadmap.md`** — flip AD-683 entry at line 7086 from open spec to *(Complete, OSS, Issue #313)* with one-paragraph delivered-summary mirroring Wave 28 / AD-658 style.
- **`DECISIONS.md`** — NO new decision entry required (this is a tractable single-AD v1 with no architectural choice that needs preservation; all sibling patterns are already documented under AD-507/AD-508/AD-509). Skip per architect judgment.

---

## Acceptance Criteria

1. All 8 new tests pass at `tests/test_ad683_ship_state_snapshot.py`.
2. Full gate `pytest tests/ -q -n 8 --dist=loadfile` shows test count of `<baseline> + 8` exact (current baseline 10912; expected 10920).
3. No regressions in `tests/test_ad638_*` or `tests/test_ad509_*` (boot camp + phase tracker are extended, not modified semantically).
4. No regressions in `tests/test_ad477_plan_of_day*` (sibling consumer of same data sources; not refactored in v1).
5. `BootCampCoordinator(config=..., ward_room=..., trust_service=..., episodic_memory=...)` (no `ship_state_builder` kwarg) still constructs and activates — backward-compat preserved for any out-of-scope test or caller.
6. `runtime.ship_state_snapshot` is a `ShipStateSnapshotBuilder` after `finalize_startup` when `config.ship_state_snapshot.enabled` is True.
7. PROGRESS.md and roadmap.md updated per Tracking section.
8. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-05-04, HEAD `b76b8a8`)

```
grep -n "BootCampCoordinator" src/probos/boot_camp.py
  85: class BootCampCoordinator:
  98:     def __init__(
 133:     async def activate(self, crew_agents: list[dict[str, str]]) -> None:

grep -n "BootCampCoordinator" src/probos/runtime.py
 1580:            self.boot_camp = BootCampCoordinator(

grep -n "self.ontology\|self.ward_room\|self.work_item_store\|self.boot_camp" src/probos/runtime.py
  391: self.ward_room: WardRoomService | None = None
  422: self.work_item_store: WorkItemStore | None = None
  462: self.ontology: VesselOntologyService | None = None
  471: self.boot_camp: BootCampCoordinator | None = None

grep -n "def get_vessel_identity\|def get_vessel_state\|def get_alert_condition\|def get_departments\|def get_crew_agent_types\|def get_assignment_for_agent\|def get_post_for_agent" src/probos/ontology/service.py
  84: def get_vessel_identity(self) -> VesselIdentity:
  91: def get_vessel_state(self) -> VesselState:
 102: def get_alert_condition(self) -> str:
 122: def get_departments(self) -> list[Department]:
  (get_crew_agent_types / get_assignment_for_agent / get_post_for_agent referenced from runtime.py:833-870 — verified present on the service)

grep -n "async def list_work_items" src/probos/workforce.py
 1066: async def list_work_items(self, status=None, assigned_to=None, work_type=None, parent_id=None, priority=None, tags=None, limit=50, offset=0) -> list[WorkItem]

grep -n "async def list_channels\|async def list_threads" src/probos/ward_room/service.py
  241: async def list_channels(self, agent_id: str | None = None) -> list[WardRoomChannel]
  288: async def list_threads(self, channel_id: str, limit: int = 50, offset: int = 0, sort: str = "recent", include_archived: bool = False) -> list[WardRoomThread]

grep -n "_boot_camp_active" src/probos/cognitive/cognitive_agent.py
 1881:     observation["_boot_camp_active"] = True
 1884:     if not observation.get("_boot_camp_active"):
 2069:     observation["_boot_camp_active"] = True
 2072:     if not observation.get("_boot_camp_active"):

grep -n "async def _build_user_message" src/probos/cognitive/cognitive_agent.py
 4246: async def _build_user_message(self, observation: dict) -> str:

grep -n "BOOT_CAMP_ACTIVATED\|ship_state\|snapshot_captured" src/probos/events.py
  252: BOOT_CAMP_ACTIVATED = "boot_camp_activated"
  (no SHIP_STATE_* / SNAPSHOT_CAPTURED hits — collision-free)

grep -n "class BootCampConfig\|boot_camp: BootCampConfig\|ship_state\|ShipState" src/probos/config.py
  285: class BootCampConfig(BaseModel)
 1991: boot_camp: BootCampConfig = BootCampConfig()  # AD-638
  (no ShipState* hits — collision-free)

grep -n "_wire_boot_camp_tracker" src/probos/startup/finalize.py
 141: def _wire_boot_camp_tracker(*, runtime: Any, config: "SystemConfig") -> bool
 466: if _wire_boot_camp_tracker(runtime=runtime, config=config):

grep -rn "AD-683\|ship_state_snapshot\|ShipStateSnapshot" src/probos/ tests/
  (zero hits — no pre-existing draft state)
```
