# AD-580: Alert Resolution Feedback Loop

## Context

Crew-identified design gap (Lynx, Science; Chapel, Medical): Bridge alerts persist indefinitely despite complete analytical resolution by the crew. The monitoring systems (EmergentDetector, BridgeAlertService) operate independently from analytical conclusions — there is no mechanism for the crew or Captain to acknowledge, dismiss, or mark an alert as resolved.

**Current state:** Alerts are emitted, posted to Ward Room, and suppressed only by time-based dedup cooldown (300-600s). When the cooldown expires, the same alert re-fires if the detector still sees the pattern. The crew investigates, resolves the underlying issue, but has no way to tell the system "we've handled this." The detector keeps firing.

**What exists today:**
- `NotificationQueue` (task_tracker.py) has `acknowledge()` and `acknowledge_all()` — but this is for HXI task notifications, not Bridge alerts.
- `BridgeAlertService._should_emit()` has time-based dedup only — no user-driven suppress.
- `EmergentDetector._is_duplicate_pattern()` has cooldown-based dedup only — no external input.
- Roadmap (line ~1437-1438) explicitly lists "dismiss/acknowledge" as future work.

**Lynx's key insight:** Alerts persist "through multi-hour cycles despite complete analytical resolution, indicating monitoring systems operate independently from analytical conclusions." This is a systemic architecture gap — even perfectly calibrated thresholds (BF-124) won't solve it.

## Design

### Core: Alert Acknowledgment API

Add an acknowledgment mechanism to `BridgeAlertService` that allows the Captain (or authorized crew via chain of command) to suppress specific alert patterns for a specified duration or until conditions change.

### Three Acknowledgment Modes

1. **Dismiss** — "We've seen this, stop alerting." Suppresses the specific `dedup_key` for a configurable extended cooldown (default: 4 hours). Alert still logged internally but not posted to Ward Room.

2. **Resolve** — "We've investigated and fixed this." Suppresses the `dedup_key` until the underlying pattern is no longer detected (i.e., cooperation cluster disappears, trust anomaly stabilizes). Re-fires only if the pattern recurs after a clean period.

3. **Mute** — "This is a known condition, stop alerting until I say otherwise." Indefinite suppression of the `dedup_key` until explicitly unmuted.

### Implementation Approach

**File: `src/probos/bridge_alerts.py`**

Add to `BridgeAlertService`:

```python
def dismiss_alert(self, dedup_key: str, duration_seconds: float = 14400.0) -> None:
    """Suppress an alert type for a specified duration (default 4 hours)."""

def resolve_alert(self, dedup_key: str) -> None:
    """Mark an alert as resolved. Re-fires only after a clean detection period."""

def mute_alert(self, dedup_key: str) -> None:
    """Indefinitely suppress an alert type until unmuted."""

def unmute_alert(self, dedup_key: str) -> None:
    """Remove indefinite suppression for an alert type."""

def list_suppressed(self) -> list[dict]:
    """Return all currently suppressed alert keys with mode and expiry."""
```

Update `_should_emit()` to check suppression state before time-based dedup:

```python
def _should_emit(self, dedup_key: str) -> bool:
    # AD-580: Check suppression first
    if self._is_suppressed(dedup_key):
        return False
    # Existing time-based dedup
    ...
```

**Suppression state:** Three dictionaries + detection tracking:
- `_dismissed: dict[str, float]` — dedup_key → expiry monotonic timestamp
- `_resolved: dict[str, float]` — dedup_key → resolved-at timestamp (re-fires after clean period)
- `_muted: set[str]` — permanently muted keys
- `_last_detected: dict[str, float]` — dedup_key → last detection monotonic timestamp (updated on EVERY detection, even when suppressed)

**Detection tracking (critical):** `_should_emit()` must update `_last_detected[dedup_key] = now` at the very top, BEFORE any suppression or dedup check. This is required because `_record()` is only called when alerts are emitted — if resolve suppresses emission, `_record()` never fires, and the clean-period logic would never know the pattern is still active. The detection timestamp must be independent of the emission decision.

**Resolve mode detail:** When an alert is resolved, store the resolution timestamp. The alert re-fires only if:
1. The detection pattern recurs (detector finds it again), AND
2. At least `resolve_clean_period` seconds (default: 3600s / 1 hour) have passed with no detection (check `_last_detected[key]` staleness), AND
3. The pattern then reappears — indicating a genuine recurrence, not residual detection.

**Constructor params:** Add `resolve_clean_period: float = 3600.0` and `default_dismiss_duration: float = 14400.0` to `BridgeAlertService.__init__()`.

**Config:** Add to `BridgeAlertConfig` in `config.py` (line 563):
```python
resolve_clean_period: float = 3600.0       # seconds before resolved alert can re-fire
default_dismiss_duration: float = 14400.0  # default dismiss duration (4 hours)
```

**Startup wiring:** In `startup/communication.py` (lines 196-204), pass new config values:
```python
bridge_alerts = BridgeAlertService(
    cooldown_seconds=config.bridge_alerts.cooldown_seconds,
    trust_drop_threshold=config.bridge_alerts.trust_drop_threshold,
    trust_drop_alert_threshold=config.bridge_alerts.trust_drop_alert_threshold,
    resolve_clean_period=config.bridge_alerts.resolve_clean_period,
    default_dismiss_duration=config.bridge_alerts.default_dismiss_duration,
)
```

### API Endpoints

**File: `src/probos/routers/system.py`**

Add three endpoints:

```
POST /api/alerts/dismiss   {dedup_key: str, duration_seconds?: float}
POST /api/alerts/resolve   {dedup_key: str}
POST /api/alerts/mute      {dedup_key: str}
POST /api/alerts/unmute    {dedup_key: str}
GET  /api/alerts/suppressed
```

### Shell Command

**File: `src/probos/experience/commands/commands_alert.py`** (new file)

Add shell command functions for Captain use:
- `cmd_alert(runtime, console, args)` — dispatcher that routes to subcommands
- Subcommands: `dismiss <pattern>`, `resolve <pattern>`, `mute <pattern>`, `unmute <pattern>`, `list`

Function signature follows existing pattern: `async def cmd_alert(runtime: ProbOSRuntime, console: Console, args: str) -> None`

**File: `src/probos/experience/shell.py`** (MUST also update)

Shell commands require TWO registrations:
1. Add to `COMMANDS` dict: `"/alert": "Manage bridge alert suppression (dismiss/resolve/mute/unmute/list)"`
2. Add to `handlers` dict in `_handle_command()`: `"/alert": lambda: cmd_alert(runtime, console, args)` — import `cmd_alert` from `commands_alert`

**Dedup key UX:** Pattern names should be human-readable. Since actual dedup keys use prefixes (`emergent:cooperation_cluster`, `trust_drop:{agent_id}`, `divergence:{pair}:{topic}`), implement pattern-prefix matching:
- `alert dismiss cooperation_cluster` → matches any key containing `cooperation_cluster`
- `alert dismiss emergent:cooperation_cluster` → exact match
- `alert list` → shows all suppressed keys with their full dedup_key for reference
- If ambiguous (multiple matches), list matches and ask for exact key

### Ward Room Integration

When an alert is dismissed/resolved/muted, post an acknowledgment to the Ward Room. **Important:** `BridgeAlertService` does NOT have Ward Room access (by design — "it returns BridgeAlert objects that the runtime delivers"). Ward Room posting must happen at the **caller** level:

- **Router endpoints:** After calling `runtime.bridge_alerts.dismiss_alert(...)`, post via `runtime.ward_room_router` or `runtime.ward_room.create_post()` to the "all hands" channel with author "Ship's Computer".
- **Shell commands:** Same — post acknowledgment after the suppress call.

Example acknowledgment message:
```
[Ship's Computer] Alert acknowledged — cooperation cluster detection muted by Captain.
```

The `ward_room_router` is available as `runtime.ward_room_router`. Use `create_post()` on the ward_room directly (`runtime.ward_room`) if `deliver_bridge_alert()` is too heavyweight for an acknowledgment.

## Engineering Principles Compliance

| Principle | How Applied |
|-----------|-------------|
| **Single Responsibility** | Suppression logic stays in BridgeAlertService. Ward Room posting at caller level (router/shell). API in router. Shell in command module. No cross-cutting. |
| **Open/Closed** | Extends `_should_emit()` with suppression check without changing detection logic. EmergentDetector unchanged. |
| **DRY** | Reuses existing dedup_key infrastructure. Suppression is a layer on top of existing dedup, not a parallel mechanism. Config values flow through existing `BridgeAlertConfig` → constructor pattern. |
| **Law of Demeter** | Router accesses `runtime.bridge_alerts` (public attribute), not reaching through private members. Ward Room via `runtime.ward_room` or `runtime.ward_room_router`. |
| **HXI Cockpit View** | Shell commands AND API endpoints — Captain always has manual control. |
| **Defense in Depth** | Three suppression modes for different use cases. Dismiss auto-expires. Resolve requires clean period before re-firing. Only mute is permanent. Detection tracking independent of emission. |
| **Fail Fast** | Unknown dedup_key → log warning, no-op. Missing BridgeAlertService → degrade silently. |
| **Cloud-Ready** | Config in `BridgeAlertConfig` (Pydantic BaseModel). Suppression state serializable. Could persist across restarts via state file in future. |

## Tests

**File: `tests/test_ad580_alert_feedback.py`**

### TestAlertDismiss (4 tests)

1. `test_dismiss_suppresses_alert` — Dismissed dedup_key → `_should_emit()` returns False.
2. `test_dismiss_expires` — After duration passes, alert fires again.
3. `test_dismiss_custom_duration` — Custom duration_seconds honored.
4. `test_dismiss_unknown_key_noop` — Unknown key logs warning, no error.

### TestAlertResolve (5 tests)

5. `test_resolve_suppresses_alert` — Resolved alert suppressed immediately.
6. `test_resolve_refires_after_clean_period` — Pattern gone for clean period, then recurs → fires.
7. `test_resolve_no_refire_during_clean_period` — Pattern recurs within clean period → still suppressed.
8. `test_resolve_tracks_last_detected` — Each detection updates `_last_detected` even when suppressed.
9. `test_resolve_continuous_detection_stays_suppressed` — Pattern detected continuously without clean gap → stays suppressed indefinitely (no false re-fire).

### TestAlertMute (3 tests)

10. `test_mute_suppresses_indefinitely` — Muted alert never fires.
11. `test_unmute_allows_firing` — After unmute, alert fires normally.
12. `test_mute_survives_many_cycles` — Muted alert stays muted across many detection cycles.

### TestAlertListSuppressed (2 tests)

13. `test_list_shows_all_suppression_modes` — List returns dismissed, resolved, and muted entries with mode metadata.
14. `test_list_excludes_expired` — Expired dismissals not shown.

### TestAlertDetectionTracking (2 tests)

15. `test_last_detected_updated_on_suppressed_emission` — `_last_detected` updates even when `_should_emit()` returns False.
16. `test_last_detected_not_set_for_unknown_keys` — No phantom entries for keys never seen.

### TestAlertAPI (3 tests)

17. `test_dismiss_endpoint` — POST /api/alerts/dismiss works.
18. `test_suppressed_endpoint` — GET /api/alerts/suppressed returns correct data.
19. `test_mute_unmute_roundtrip` — Mute then unmute via API.

### TestAlertPatternMatching (2 tests)

20. `test_substring_match_finds_prefixed_key` — `dismiss cooperation_cluster` matches `emergent:cooperation_cluster`.
21. `test_exact_key_preferred_over_substring` — When both exact and substring match exist, exact wins.

**Total: 21 tests.**

## Dependencies

- **BF-124** (cooperation cluster calibration) — should be built first. BF-124 reduces false positive frequency; AD-580 gives the crew tools to handle remaining alerts.
- **AD-410** (Bridge Alerts) — existing infrastructure this extends.
- **No new dependencies** introduced.

## Deferred

- **Alert suppression persistence across restarts** — Currently in-memory. Could persist to state file or config. Low priority since stasis/restart resets system state anyway.
- **Crew-level acknowledgment** — Currently Captain-only (shell). Could extend to department chiefs via chain of command. Needs Standing Orders gating.
- **Automated resolve detection** — Instead of manual `/alert resolve`, could automatically clear resolved state when detector stops seeing the pattern. Needs EmergentDetector → BridgeAlertService callback.

## Build Verification

```bash
# 1. New tests pass
python -m pytest tests/ -k "ad580 or alert_feedback" -v

# 2. Existing bridge alert tests still pass
python -m pytest tests/ -k "bridge_alert" -v

# 3. Full suite
python -m pytest tests/ -x -q
```

## Files Modified

| File | Changes |
|------|---------|
| `src/probos/bridge_alerts.py` | `dismiss_alert()`, `resolve_alert()`, `mute_alert()`, `unmute_alert()`, `list_suppressed()`, `_is_suppressed()`, `_last_detected` dict, suppression state dicts, `_should_emit()` detection tracking |
| `src/probos/config.py` | `BridgeAlertConfig` + 2 new fields (`resolve_clean_period`, `default_dismiss_duration`) |
| `src/probos/startup/communication.py` | Pass new config values to `BridgeAlertService` constructor |
| `src/probos/routers/system.py` | 5 new API endpoints |
| `src/probos/experience/commands/commands_alert.py` | New file — `cmd_alert()` with dismiss/resolve/mute/unmute/list subcommands |
| `src/probos/experience/shell.py` | Register `/alert` in COMMANDS dict + handlers dict |
| `tests/test_ad580_alert_feedback.py` | 21 new tests |
