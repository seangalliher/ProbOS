# AD-733c-5 — Per-agent perception engagement

**Issue:** [#676](https://github.com/seangalliher/ProbOS/issues/676)
**Status:** GATE 1 — drafting (Wave 176)
**Depends on:** AD-733c-2 (`PerceptionModeController` shipped Wave 172),
AD-733c-3 (engage endpoint shipped Wave 172), AD-733c-6 (engaged-budget
enforcement shipped Wave 175), AD-722b (callsign wake routing —
`WakeRoute.agentCallsign` already per-agent), AD-742c (per-agent camera
— sibling AD in this wave; SHARES the `CrewProfile.perception` block
introduced here).
**Estimated tests:** +11 pytest, +3 vitest.

---

## Problem

AD-733c shipped per-runtime mode (all agents transition together):
when Captain says "Hello Ezri" the entire mesh switches to ENGAGED,
including Atlas in the next room. Per-agent engagement is the obvious
next step:

- "Hello Counselor" → only Ezri's controller transitions to ENGAGED;
  Atlas stays AMBIENT.
- "Hello Engineering" → Worf's controller engages; Ezri stays.
- Vision call budget (AD-733c-6) becomes per-agent: each agent has its
  own 200-call session cap, not shared.

The wake routing is ALREADY per-agent (`WakeRoute.agentCallsign`
shipped Wave 172, see `routers/agents.py:296`). The missing piece is
the mode controller itself.

## Solution

Promote `PerceptionModeController` from singleton to per-agent
instance, keyed by `agent_id`. Introduce a `PerceptionEngagementRegistry`
(thin dict-wrapper) that owns the controllers and threads them through
the existing `note_*` callsites.

### New `CrewProfile.perception` block (shared with AD-742c)

```python
@dataclass
class PerceptionProfile:
    """AD-733c-5 + AD-742c: per-agent perception bindings."""
    engagement_enabled: bool = True       # AD-733c-5 master toggle
    initial_mode: str = "ambient"         # AD-733c-5 startup mode
    camera_device_id: str = ""            # AD-742c per-agent camera
    # Forward markers AD-733c-5-1 / AD-742c-1 expand here.
```

This block lives on `CrewProfile` (`src/probos/crew_profile.py`).
Both AD-733c-5 (this AD) and AD-742c (#671 sibling AD) write to it.
Build order matters: AD-733c-5 ships the block FIRST with
`camera_device_id` reserved but unused; AD-742c (built next) adds the
camera-binding wire-up.

### Engagement registry

`src/probos/perception/engagement_registry.py`:

- `class PerceptionEngagementRegistry`:
  - `__init__(self, runtime)` — constructs an empty dict.
  - `register(self, agent_id: str, controller: PerceptionModeController)`.
  - `get(self, agent_id: str) -> PerceptionModeController | None`.
  - `all_controllers() -> dict[str, PerceptionModeController]`.
  - `current_modes() -> dict[str, Mode]` — used by the HXI dashboard.

### Wire-up changes

- `startup/finalize.py:4122` — REPLACE the singleton construction:
  ```python
  _controller = PerceptionModeController(...)
  runtime.perception_mode_controller = _controller
  ```
  with a per-agent loop after `VisionConsumer.register_observer`:
  ```python
  registry = PerceptionEngagementRegistry(runtime)
  for agent in runtime.registry.all():  # BF-287 — public API
      profile = callsign_registry.get_profile(agent.id)
      if profile is None or not profile.perception.engagement_enabled:
          continue
      ctrl = PerceptionModeController(
          consumer=consumer,
          initial_mode=Mode(profile.perception.initial_mode),
          agent_id=agent.id,  # NEW kwarg
      )
      await ctrl.start()
      registry.register(agent.id, ctrl)
  runtime.perception_engagement_registry = registry
  # BACK-COMPAT: keep singleton attribute pointing at the *primary*
  # agent's controller for transitional callers. Choose Counselor
  # (Ezri) if present, else first registered.
  runtime.perception_mode_controller = registry.get("e1") or (
      next(iter(registry.all_controllers().values()), None)
  )
  ```
- `PerceptionModeController.__init__` — add `agent_id: str = ""`
  kwarg (default empty string for back-compat; new code passes it).
  All log messages prefixed with `agent_id` when non-empty.
- `routers/agents.py:1959` (`note_dm_activity` callsite inside
  `agent_chat`) — REPLACE:
  ```python
  _mode_ctrl = getattr(runtime, "perception_mode_controller", None)
  ```
  with:
  ```python
  _registry = getattr(runtime, "perception_engagement_registry", None)
  _mode_ctrl = _registry.get(agent_id) if _registry is not None else (
      getattr(runtime, "perception_mode_controller", None)
  )
  ```
  (back-compat fallback to singleton if registry not wired.)
- `routers/perception.py:262` (`POST /api/perception/mode`) — accept
  optional `agent_id` query param; default = `"_runtime"` sentinel for
  back-compat (runtime-wide override). When `agent_id` is non-empty,
  routes to `registry.get(agent_id).transition_to(mode)`.
- `routers/perception.py:293` (`POST /api/perception/engage` shipped
  AD-733c-3) — body already accepts optional `agent` field; route to
  the matching controller via the registry. Falls back to the legacy
  singleton path when `agent` is empty (back-compat).
- `routers/perception.py:219` (`GET /api/perception/mode`) — extend the
  response with `per_agent: {agent_id: mode}` so the HXI can render
  per-agent badges.
- `ProactiveVisionObserver` (`perception/observer.py:41`) —
  `note_high_novelty_event` already calls the singleton controller via
  the runtime. Update to look up via the registry by the observer's
  active `agent_id` (which the observer already has from the WM
  subscription).
- `VisionConsumer._record_vision_call` (AD-733c-6 enforcement) —
  budget enforcement transitions ONLY the agent associated with the
  current describe. Pass `agent_id` through `_maybe_enforce_budget`.

### HXI surface

- `CameraLiveIndicator.tsx` — already renders ONE mode badge
  (AD-733c-2). Extend to render N badges, one per agent in
  `useEngagementStore`. Compact format: `EZRI:ENGAGED` /
  `ATLAS:AMBIENT`. Keep amber stroke-only per HXI Principle #3.
- New `ui/src/store/usePerceptionEngagementStore.ts` Zustand slice
  exporting `{ perAgent: Record<string, PerceptionMode>, refresh() }`
  that polls the extended `GET /api/perception/mode` endpoint at 2s.
- `PerceptionLivePanel.tsx` MODE section — extend to render the
  per-agent rows in a table.

## Cross-AD interaction notes

- **AD-742c shares `CrewProfile.perception`** — this AD ships the
  block; AD-742c populates `camera_device_id`. Builder MUST commit
  AD-733c-5 BEFORE AD-742c in the wave so the block exists.
- **AD-733c-7 (Silero VAD)** adds a `note_voice_activity()` hook to
  the SAME `PerceptionModeController` class — orthogonal trigger,
  NOT a strategy plugin. After this AD lands, the VAD hook just calls
  `registry.get(agent_id).note_voice_activity()`.
- **AD-742d STRATEGY_REGISTRY is NOT reused** — supervisor-frame
  admission ≠ engagement-mode state. Different abstractions.
- **AD-733c-6 budget enforcement** continues to fire `transition_to`
  on whatever controller called `_record_vision_call`. After this AD,
  that's the per-agent controller; budget caps apply per-agent.

## Scope

- New file: `src/probos/perception/engagement_registry.py`.
- New dataclass: `PerceptionProfile` in `crew_profile.py` (after
  `PeerPerceptionProfile` at line 306). Wire `to_dict` + `from_dict`.
- New field on `CrewProfile`: `perception: PerceptionProfile =
  field(default_factory=PerceptionProfile)` (after `peer_perception`
  at line 372).
- Modify: `PerceptionModeController.__init__` to accept `agent_id`
  kwarg.
- Modify: `startup/finalize.py` per-agent loop.
- Modify: `routers/agents.py` registry lookup.
- Modify: `routers/perception.py` endpoints (mode GET + POST + engage).
- Modify: `perception/observer.py` registry lookup in
  `note_high_novelty_event` dispatch.
- Modify: `perception/consumer.py` `_maybe_enforce_budget` agent_id
  threading.
- New: `ui/src/store/usePerceptionEngagementStore.ts`.
- Modify: `ui/src/components/perception/CameraLiveIndicator.tsx` (per-
  agent badge list).
- Modify: `ui/src/components/settings/sections/PerceptionLivePanel.tsx`
  (MODE section per-agent table).

## NOT in scope

- Per-agent supervisor strategy override (different agents using
  different supervisor strategies) → AD-742d-2 forward marker.
- Per-agent camera binding wire-up → AD-742c (this wave, sibling).
- Per-agent vision tier selection (Ezri uses qwen vs Atlas uses
  moondream) → AD-742a-1 forward marker.
- Captain UI for editing `CrewProfile.perception` from the HXI →
  forward marker AD-733c-5-1 (operator can hand-edit profile JSON for
  v1).
- Federation-cross-host engagement state sync → AD-742f-1 forward
  marker.

## Pre-flight grep anchors (Builder MUST verify before locking edits)

1. `src/probos/crew_profile.py:306` — `class PeerPerceptionProfile`
   anchor exists. Insert `PerceptionProfile` AFTER this class.
2. `src/probos/crew_profile.py:372` — `peer_perception:
   PeerPerceptionProfile = field(...)` line. Insert `perception:
   PerceptionProfile = field(...)` after it.
3. `src/probos/crew_profile.py:454` — `to_dict` includes
   `peer_perception`. Add `perception` key.
4. `src/probos/crew_profile.py:489-490` — `from_dict` parses
   `peer_perception`. Add `perception` parse.
5. `src/probos/perception/mode_controller.py:101` — `__init__`
   signature. Add `agent_id: str = ""` kwarg.
6. `src/probos/perception/mode_controller.py:91` — `class
   PerceptionModeController` defined. Verify no subclasses or
   monkeypatching in `tests/`.
7. `src/probos/startup/finalize.py:4122` — `_controller =
   PerceptionModeController(` exact line. Per-agent loop replaces this.
8. `src/probos/routers/agents.py:1959` —
   `_mode_ctrl.note_dm_activity()` exact callsite.
9. `src/probos/routers/perception.py:294` — `async def
   post_perception_engage` accepts `agent?` field per AD-733c-3 ship.
10. `src/probos/perception/observer.py:41` — `class
    ProactiveVisionObserver` and its `_dispatch_proactive_dm` need
    the registry lookup.
11. `src/probos/perception/consumer.py:77` —
    `class VisionConsumer` `__init__`; `_maybe_enforce_budget` is on
    this class.
12. `ui/src/components/perception/CameraLiveIndicator.tsx` exists at
    HEAD (shipped Wave 170).

## Engineering-principles audit

- **SOLID load-bearing**: Open/Closed — extending the existing
  `PerceptionModeController` via composition (registry) without
  modifying its core mode-transition contract. The class gains ONE
  optional kwarg; back-compat preserved.
- **Defaults preserve behavior**: When `CrewProfile.perception` is
  absent from the on-disk profile JSON (legacy profiles),
  `from_dict` defaults to `PerceptionProfile()` — engagement_enabled
  True with initial_mode AMBIENT, identical to the singleton's
  current behavior.
- **AD-731 invariant**: N/A (no image bytes touched). Source-scan
  test on `engagement_registry.py`.
- **AD-541b memory integrity**: N/A (no episodic writes).
- **Hot-reload posture**:
  - `PerceptionProfile.engagement_enabled` toggle → restart-required
    (controller spawning happens at finalize).
  - `PerceptionProfile.initial_mode` → restart-required (initial mode
    is just startup state; live mode is controlled by `note_*` hooks).
  - Forward marker AD-733c-5-2 for hot-reload of profile.
- **Anti-deadlock**: Registry methods are sync. `transition_to` is
  sync. No new async locks introduced.
- **Async discipline**: Per-agent `controller.start()` each owns
  ONE `asyncio.Task` per existing AD-733c-2 contract. The registry
  itself owns no async tasks; lifecycle (start/stop) delegated to the
  controllers.
- **License posture**: 0-line diff on all 5 license files.
- **Test scaffolding**: Real `CrewProfile()` + real `CallsignRegistry`
  + real `PerceptionModeController` (BF-287). Fake supervisor strategy
  via dataclass stub.
- **HXI Principle #3**: Per-agent badges render uppercase mono text +
  stroke-only colors. No emoji.

## Test plan (+11 pytest, +3 vitest)

`tests/test_ad733c5_per_agent_engagement.py`:

1. `test_perception_profile_default_values` — `engagement_enabled=True`,
   `initial_mode="ambient"`, `camera_device_id=""`.
2. `test_crew_profile_roundtrip_with_perception` — JSON write/read.
3. `test_crew_profile_legacy_json_backcompat` — old profile JSON
   without `perception` key → default `PerceptionProfile`.
4. `test_engagement_registry_register_get` — registry contract.
5. `test_per_agent_controllers_independent_transitions` — Ezri
   transitions to ENGAGED, Atlas stays AMBIENT. Verify via
   `registry.current_modes()`.
6. `test_agent_chat_routes_to_correct_controller` — DM to Ezri only
   triggers Ezri's `note_dm_activity`.
7. `test_engage_endpoint_routes_per_agent` — `POST /api/perception/engage
   {agent: "e1"}` only transitions Ezri.
8. `test_engage_endpoint_unknown_agent_404` — `agent: "nonexistent"`
   returns 404 honest-degrade.
9. `test_get_mode_returns_per_agent_dict` — `GET /api/perception/mode`
   response includes `per_agent` field.
10. `test_back_compat_singleton_attribute_still_points_at_primary` —
    `runtime.perception_mode_controller is registry.get("e1")` when
    Ezri present.
11. `test_engagement_disabled_profile_skipped_at_finalize` — profile
    with `engagement_enabled=False` → no controller created for that
    agent.

`ui/src/__tests__/PerAgentModeBadge.test.tsx` (+3 vitest):

1. Per-agent badges render when registry returns multiple agents.
2. Single-agent case renders ONE badge (back-compat).
3. Empty registry → no badges rendered.

## Tracker updates (Builder)

- `PROGRESS.md` — Wave 176 line under "Wave 176 in flight."
- `docs/development/roadmap.md` — add `AD-733c-5` row + forward
  markers AD-733c-5-1 (HXI editor), AD-733c-5-2 (hot-reload profile),
  AD-733c-5-3 (federation sync).
- `DECISIONS.md` — append at build time.

## Acceptance criteria

1. `PerceptionProfile` block exists on `CrewProfile` with default
   values matching current singleton behavior.
2. Legacy profile JSON without `perception` block loads without error
   (`test_crew_profile_legacy_json_backcompat`).
3. After finalize, each crew agent with `engagement_enabled=True` has
   its own `PerceptionModeController` instance.
4. `runtime.perception_engagement_registry` is the canonical lookup;
   `runtime.perception_mode_controller` is a back-compat pointer at
   the primary controller.
5. DM to one agent does NOT transition the other agent's mode.
6. Wake "Hello Counselor" → only Ezri transitions
   (existing AD-733c-3 path with `agent` field routes through
   registry).
7. AD-733c-6 budget enforcement transitions ONLY the agent whose
   describe hit the cap (regression test against shared-state
   reset bug).
8. All 11 pytest + 3 vitest pass.
9. `cd ui && npm run build` exit 0.
10. Zero new pip / npm deps. 0-line diff on all 5 license files.
11. **Verify all changes comply with the Engineering Principles in
    `.github/copilot-instructions.md`.**
