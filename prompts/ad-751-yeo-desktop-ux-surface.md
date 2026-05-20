# AD-751 - Desktop UX Surface (Tray, Notifications, Hotkey, Mini-Mode, Autostart)

Status: drafted (planning slate only)
Issue: #697
Parent: #486
Related: #484

## Objective
Define the desktop interaction surface required for Yeo to operate as the primary assistant front door in OSS.

## Captain Invariant
Capability is usable by all crew agents; Yeo is the front-door orchestrator and delegates to specialists.

## In Scope
- Tray affordance and status indicator behavior.
- Global hotkey invocation and mini-mode launch.
- Actionable desktop notifications and autostart policy.
- Stream/merge UX convention for concise status updates.

## Out of Scope
- Replacing mobile/PADD delivery scope in #484.
- Enterprise endpoint-management packaging.

## OSS vs Commercial Split

**OSS (Personal Desktop):**
- Tray icon with local state indicators.
- Global hotkey and mini-mode for personal use.
- Desktop notifications driven by personal assistant context.
- Autostart and idle-wake policies.

**Commercial Extension Point:**
- Fleet-wide notification delivery and device-targeting.
- Org policy enforcement on tray/notification behavior.
- MDM integration for endpoint provisioning and compliance.

## File Targets
- `ui/src/components/`
- `ui/src/store/`
- `ui/src/App.tsx`
- `src/probos/routers/system.py`
- `src/probos/notifications.py`

## Pre-Flight Anchors
- Verify existing Ward Room surfaces in `ui/src/components/wardroom/`.
- Verify notification services in `src/probos/notifications.py` and API routes.
- Verify startup/runtime settings in `src/probos/config.py`.

## Implementation Spec

### Section 1: Tray Icon & System Integration

**File:** `src/probos/experience/desktop/tray.py` (new)

Create `TrayManager` class:
```python
class TrayManager:
    def __init__(self, config: DesktopConfig):
        """Initialize system tray with status indicators.
        
        Platform-specific:
        - Windows: pystray + pywin32 for DPAPI integration
        - macOS: rumps (py-applescript wrapper)
        - Linux: pystray + dbus for notifications
        """
    
    def set_status(self, status: str) -> None:
        """Update tray icon: 'idle' | 'running' | 'urgent'.
        
        Visual: amber icon (idle), pulsing (running), red (urgent).
        """
    
    def show_notification(self, title: str, message: str, urgency: str = "normal") -> None:
        """Toast notification (win10toast / pyobjc / plyer platform-specific)."""
```

**Platform Support:**
- Windows: pystray + win10toast
- macOS: rumps + NSUserNotification
- Linux: pystray + notify-send (dbus)

**Config (system.yaml):**
```yaml
desktop:
  enabled: true
  tray_autostart: true
  hotkey: "ctrl+shift+space"
  notification_timeout_sec: 5
  quiet_hours_start: "19:00"
  quiet_hours_end: "08:00"
```

**Tests:** `tests/test_tray_manager.py` (2 tests)
- Status transitions: idle → running → urgent → idle
- Notifications routed correctly based on quiet-hours

### Section 2: Global Hotkey & Mini-Mode

**File:** `src/probos/experience/desktop/hotkey.py` (new)

Create `HotkeyListener` class (pynput):
```python
class HotkeyListener:
    async def start_listening(self, hotkey: str = "ctrl+shift+space") -> None:
        """Listen globally for hotkey press. Trigger mini-mode on activation."""
    
    async def on_hotkey_pressed(self) -> None:
        """Bring up mini-mode window or activate if already open."""
```

**Mini-Mode Window:**
- Rich-rendered input prompt (same REPL as shell, but in a small Tkinter window)
- Suggestions panel (top-3 ranked by Hebbian + attention)
- Recent contexts (last 3 conversations, quick access)

**Persistent Window:** Single instance lock (LOCKFILE: `~/.probos/yeo.lock`)

**Tests:** `tests/test_hotkey_listener.py` (1 test)
- Hotkey press triggers window activation (mock pynput)

### Section 3: Autostart & Single-Instance Lock

**File:** `src/probos/experience/desktop/lifecycle.py` (new)

Create `DesktopLifecycle` class:
```python
class DesktopLifecycle:
    def __init__(self, config: DesktopConfig):
        self.lock_file = config.lock_file or "~/.probos/yeo.lock"
    
    async def acquire_lock(self) -> bool:
        """Fail fast if already running (prevents duplicate instances)."""
    
    async def register_autostart(self) -> None:
        """Platform-specific autostart registration:
        - Windows: Registry HKCU\\Run
        - macOS: LaunchAgent plist in ~/Library/LaunchAgents
        - Linux: .desktop file in ~/.config/autostart
        """
    
    async def unregister_autostart(self) -> None:
        """Remove autostart registration."""
```

**Tests:** `tests/test_desktop_lifecycle.py` (2 tests)
- Lock prevents duplicate instances
- Autostart registration idempotent (register twice = no error)

### Section 4: Actionable Notifications

**File:** `src/probos/experience/desktop/notifications.py` (new)

Create `NotificationCenter` class:
```python
class NotificationCenter:
    async def notify_with_action(self, title: str, message: str, actions: list[dict]) -> str | None:
        """Show notification with clickable action buttons.
        
        Args:
            actions: [{"label": "Approve", "intent": "approve_build"}, ...]
        
        Returns:
            action label clicked, or None if dismissed.
        """
```

**Use Cases:**
- "Build completed: Review? [Approve] [Reject] [Review]"
- "Daily briefing ready: [Read] [Dismiss]"
- "Meeting in 15 minutes: [Snooze] [Join] [Decline]"

**Tests:** `tests/test_notifications.py` (1 test)
- Action notification parsed correctly

### Section 5: Runtime Wiring

**File:** `src/probos/runtime.py` (extend)

In `async def startup()`:
```python
if config.desktop.enabled:
    self._tray_manager = TrayManager(config.desktop)
    self._hotkey_listener = HotkeyListener()
    self._lifecycle = DesktopLifecycle(config.desktop)
    
    await self._lifecycle.acquire_lock()
    await self._lifecycle.register_autostart()
    await self._hotkey_listener.start_listening(config.desktop.hotkey)
    self._tray_manager.set_status("idle")
```

### Section 6: Acceptance Criteria & Gate

**Test Expectations:**
- `test_tray_manager.py`: 2 tests
- `test_hotkey_listener.py`: 1 test
- `test_desktop_lifecycle.py`: 2 tests
- `test_notifications.py`: 1 test
- **Total: 6 new tests**

**Operational Gate:** Desktop mode must degrade gracefully if display server unavailable (returns `operation_not_supported` for headless).

**Completion Signal:**
- All 6 tests passing
- Tray icon visible on any platform (platform-specific)
- Hotkey listener doesn't crash on platforms without global hotkey support
- Single-instance lock prevents duplicate Yeo processes

## Acceptance Criteria
- Desktop surfaces remain optional and degrade gracefully by platform.
- Notification ergonomics include low-noise rules and user controls.
- Delegation visibility from Yeo to specialist agents is explicit.
- Captain invariant appears in acceptance checks.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
