# AD-673: Automated Anomaly Window Detection

**Status:** Ready for builder
**Issue:** #356
**Dependencies:** AD-558 (trust cascade dampening), AD-567a (AnchorFrame), AD-662 (anomaly_window_id field)
**Estimated tests:** 14

---

## Problem

`AnchorFrame` has an `anomaly_window_id: str = ""` field (added by AD-662) but nothing populates it. `SocialVerificationService` in `social_verification.py` applies `anomaly_window_discount` via `_in_anomaly_window()`, but has no supplier of window IDs. Episodes stored during system anomalies (trust cascades, LLM degradation) are not tagged, so corroboration scoring cannot account for degraded-state observations.

## Solution

Add an `AnomalyWindowManager` that opens/closes named anomaly windows in response to system events. Hook into `EpisodicMemory.store()` to stamp episodes with the active window ID. This populates the existing `AnchorFrame.anomaly_window_id` field.

---

## Implementation

### 1. AnomalyWindowManager

**New file:** `src/probos/cognitive/anomaly_window.py`

```python
class AnomalyWindowManager:
    def __init__(
        self,
        config: "AnomalyWindowConfig",
        emit_event_fn: Callable[[str, dict], None] | None = None,
    ) -> None:
```

State:
- `_active_window_id: str | None = None`
- `_active_signal_type: str = ""`
- `_active_details: str = ""`
- `_opened_at: float = 0.0`
- `_affected_count: int = 0` — episodes stamped during this window
- `_config: AnomalyWindowConfig`
- `_emit_event_fn: Callable | None`

Methods:

**`open_window(signal_type: str, details: str = "") -> str`**
If a window is already active, increment `_affected_count` and return the existing window ID (concurrent signals merge into one window). Otherwise:
- Generate window ID: `f"aw-{uuid.uuid4().hex[:8]}"`
- Store signal_type, details, `time.monotonic()` as opened_at
- Reset affected_count to 0
- Emit `ANOMALY_WINDOW_OPENED` event with `{"window_id": ..., "signal_type": ..., "details": ...}`
- Return window ID

**`close_window(window_id: str) -> None`**
If `window_id` matches active window:
- Compute duration = `time.monotonic() - _opened_at`
- Emit `ANOMALY_WINDOW_CLOSED` event with `{"window_id": ..., "duration_seconds": ..., "affected_episodes": ..., "signal_type": ...}`
- Clear active window state
- Log at INFO level

If `window_id` does not match (or no active window), log warning and no-op.

**`get_active_window() -> str | None`**
Return `_active_window_id` if active and not expired. Check auto-expiry: if `time.monotonic() - _opened_at > config.max_window_duration_seconds`, auto-close and return None.

**`is_active() -> bool`**
Return `get_active_window() is not None`.

**`tag_recent(window_id: str, lookback_seconds: float) -> int`**
Retrospective tagging stub. Currently returns 0 and logs a debug message. The actual implementation requires EpisodicMemory mutation which is complex for frozen Episodes — defer to a follow-up AD. This method exists to define the interface.

**`record_episode_stamped() -> None`**
Increment `_affected_count` by 1. Called by the episode stamping hook.

### 2. Events

**File:** `src/probos/events.py`

Add to `EventType` enum (in the Counselor / Cognitive Health section or after it):
```python
# Anomaly windows (AD-673)
ANOMALY_WINDOW_OPENED = "anomaly_window_opened"
ANOMALY_WINDOW_CLOSED = "anomaly_window_closed"
```

### 3. AnomalyWindowConfig

**File:** `src/probos/config.py`

Add `AnomalyWindowConfig(BaseModel)`:
```python
class AnomalyWindowConfig(BaseModel):
    """Anomaly window detection configuration (AD-673)."""
    enabled: bool = True
    max_window_duration_seconds: float = 1800.0  # 30 min auto-close
    lookback_seconds: float = 60.0  # retrospective tagging window (future use)
```

Add to `SystemConfig`:
```python
anomaly_window: AnomalyWindowConfig = AnomalyWindowConfig()
```

### 4. Episode Stamping Hook

**File:** `src/probos/cognitive/episodic.py`

Add to `EpisodicMemory`:
```python
def set_anomaly_window_manager(self, manager: Any) -> None:
    """AD-673: Wire anomaly window manager for episode stamping."""
    self._anomaly_window_manager = manager
```

Initialize `self._anomaly_window_manager: Any = None` in `__init__()`.

In the `store()` method, after the importance scoring step (around line ~928, after the `compute_importance` call) and before the actual ChromaDB insertion, add:

```python
# AD-673: Stamp episode with active anomaly window ID
if self._anomaly_window_manager and hasattr(self._anomaly_window_manager, "get_active_window"):
    active_window = self._anomaly_window_manager.get_active_window()
    if active_window and episode.anchors is not None:
        # AnchorFrame is frozen — rebuild with window ID
        anchor_dict = dataclasses.asdict(episode.anchors)
        anchor_dict["anomaly_window_id"] = active_window
        episode = dataclasses.replace(episode, anchors=AnchorFrame(**anchor_dict))
        self._anomaly_window_manager.record_episode_stamped()
```

**Note:** `Episode` is a dataclass (not frozen), so `dataclasses.replace()` works. `AnchorFrame` IS frozen, so we must rebuild it.

### 5. Signal Event Subscriptions

**File:** `src/probos/startup/finalize.py` (or `src/probos/startup/dreaming.py` — wherever event subscriptions are wired)

Add a helper function:
```python
def _wire_anomaly_window(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-673: Wire AnomalyWindowManager and subscribe to signal events."""
    if not config.anomaly_window.enabled:
        return False

    from probos.cognitive.anomaly_window import AnomalyWindowManager

    emit_fn = getattr(runtime, "_emit_event", None)
    manager = AnomalyWindowManager(
        config=config.anomaly_window,
        emit_event_fn=emit_fn,
    )

    # Wire into EpisodicMemory
    episodic = getattr(runtime, "_episodic_memory", None)
    if episodic and hasattr(episodic, "set_anomaly_window_manager"):
        episodic.set_anomaly_window_manager(manager)

    # Subscribe to signal events
    subscribe = getattr(runtime, "subscribe", None)
    if subscribe:
        def on_trust_cascade(data: Any) -> None:
            manager.open_window("trust_cascade", str(data))

        def on_llm_health(data: Any) -> None:
            status = data.get("status", "") if isinstance(data, dict) else ""
            if status in ("degraded", "offline"):
                manager.open_window("llm_degraded", f"LLM status: {status}")
            elif status == "healthy" and manager.is_active():
                active = manager.get_active_window()
                if active:
                    manager.close_window(active)

        subscribe("trust_cascade_warning", on_trust_cascade)
        subscribe("llm_health_changed", on_llm_health)

    runtime._anomaly_window_manager = manager
    return True
```

Call from `finalize_startup()` after other wiring calls. Log success.

**Signal sources:**
- `TRUST_CASCADE_WARNING` ("trust_cascade_warning") — already emitted by TrustNetwork when cascade breaker trips (AD-558). Opens a window.
- `LLM_HEALTH_CHANGED` ("llm_health_changed") — already emitted by LLM proxy (BF-069). "degraded"/"offline" opens window, "healthy" closes it.
- No `ALERT_CONDITION_CHANGED` event exists in the codebase. Alert condition changes are managed via `VesselOntologyService.set_alert_condition()` which does not emit events. This can be added in a follow-up AD if needed.

### 6. Verify AnchorFrame Field

**File:** `src/probos/types.py`

Verify `anomaly_window_id: str = ""` exists on `AnchorFrame` (line ~385). No change needed — the field already exists per AD-662.

---

## Tests

**File:** `tests/test_ad673_anomaly_window.py`

14 tests:

1. `test_open_window` — opens a window, returns non-empty string starting with "aw-"
2. `test_close_window` — close an active window, verify is_active() returns False
3. `test_get_active_window` — returns window ID when active, None when inactive
4. `test_is_active` — True when window open, False when closed
5. `test_auto_expire` — set max_window_duration_seconds to 0.01, wait briefly, verify window auto-closes on next get_active_window() call
6. `test_window_id_format` — verify window ID matches pattern `aw-[0-9a-f]{8}`
7. `test_episode_stamping` — create EpisodicMemory (use _FakeCollection stub), store an episode while window is active, verify episode.anchors.anomaly_window_id is set
8. `test_no_stamp_when_inactive` — store episode when no window active, verify anomaly_window_id remains ""
9. `test_retrospective_tagging` — tag_recent returns 0 (stub behavior documented)
10. `test_trust_cascade_triggers` — simulate trust_cascade_warning event, verify window opens
11. `test_llm_degraded_triggers` — simulate llm_health_changed with status="degraded", verify window opens
12. `test_llm_healthy_closes` — open window via degraded, then send healthy, verify window closes
13. `test_config_disabled` — when config.enabled is False, _wire_anomaly_window returns False
14. `test_concurrent_signals_single_window` — call open_window twice, verify same window ID returned (no second window opened)

Use `_Fake*` stubs for ChromaDB collection. Use `tmp_path` for any file paths.

---

## What This Does NOT Change

- No ML-based anomaly detection or prediction
- No cross-instance anomaly correlation
- No retrospective episode mutation (tag_recent is a stub for the interface)
- No alert condition event emission (would require changes to VesselOntologyService — separate AD)
- No changes to SocialVerificationService — it already handles anomaly_window_id when present
- No changes to EmergentDetector anomaly_window thresholds
- No changes to DreamingEngine

---

## Tracking

- `PROGRESS.md`: Add AD-673 as CLOSED
- `DECISIONS.md`: Add entry — "AD-673: AnomalyWindowManager populates AnchorFrame.anomaly_window_id. Triggered by trust cascade and LLM health events. Single concurrent window model. Episodes stamped during store() via frozen-dataclass rebuild. Retrospective tagging deferred (stub only)."
- `docs/development/roadmap.md`: Update AD-673 row status
