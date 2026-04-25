# AD-323: Agent Notification Queue

## Overview

Add a persistent notification system that any agent can emit to, with a bell
icon in the HXI header and a notification dropdown panel. Notifications persist
until the Captain acknowledges them.

## Architecture

Follow the exact patterns established by TaskTracker (AD-316) and
ActivityDrawer (AD-321):

```
Agent calls rt.notify()
    → NotificationQueue stores it
    → _emit_event("notification", ...) fires
    → WebSocket broadcasts to HXI
    → Zustand updates notifications state
    → Bell icon shows unread count
    → Dropdown renders notification cards
```

## Python — Backend

### 1. `AgentNotification` dataclass

Add to `src/probos/task_tracker.py` (alongside `AgentTask`):

```python
@dataclass
class AgentNotification:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    agent_id: str = ""
    agent_type: str = ""
    department: str = ""
    notification_type: str = "info"  # "info" | "action_required" | "error"
    title: str = ""
    detail: str = ""
    action_url: str = ""  # optional link context (e.g. task_id, intent)
    created_at: float = field(default_factory=time.time)
    acknowledged: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "department": self.department,
            "notification_type": self.notification_type,
            "title": self.title,
            "detail": self.detail,
            "action_url": self.action_url,
            "created_at": self.created_at,
            "acknowledged": self.acknowledged,
        }
```

### 2. `NotificationQueue` service

Add to `src/probos/task_tracker.py` (alongside `TaskTracker`):

```python
class NotificationQueue:
    def __init__(self, on_event: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        self._notifications: dict[str, AgentNotification] = {}
        self._on_event = on_event
        self._max_acknowledged: int = 50  # keep last 50 acked for history

    def notify(
        self,
        agent_id: str,
        agent_type: str,
        department: str,
        title: str,
        detail: str = "",
        notification_type: str = "info",
        action_url: str = "",
    ) -> AgentNotification:
        n = AgentNotification(
            agent_id=agent_id,
            agent_type=agent_type,
            department=department,
            title=title,
            detail=detail,
            notification_type=notification_type,
            action_url=action_url,
        )
        self._notifications[n.id] = n
        self._emit("notification", n)
        return n

    def acknowledge(self, notification_id: str) -> bool:
        n = self._notifications.get(notification_id)
        if not n:
            return False
        n.acknowledged = True
        self._emit("notification_ack", n)
        self._prune_acknowledged()
        return True

    def acknowledge_all(self) -> int:
        count = 0
        for n in self._notifications.values():
            if not n.acknowledged:
                n.acknowledged = True
                count += 1
        if count > 0:
            self._emit_snapshot()
        self._prune_acknowledged()
        return count

    def snapshot(self) -> list[dict[str, Any]]:
        return [n.to_dict() for n in sorted(
            self._notifications.values(),
            key=lambda n: n.created_at,
            reverse=True,
        )]

    def unread_count(self) -> int:
        return sum(1 for n in self._notifications.values() if not n.acknowledged)

    def _emit(self, event_type: str, n: AgentNotification) -> None:
        if self._on_event:
            self._on_event(event_type, {
                "notification": n.to_dict(),
                "notifications": self.snapshot(),
                "unread_count": self.unread_count(),
            })

    def _emit_snapshot(self) -> None:
        if self._on_event:
            self._on_event("notification_snapshot", {
                "notifications": self.snapshot(),
                "unread_count": self.unread_count(),
            })

    def _prune_acknowledged(self) -> None:
        acked = [n for n in self._notifications.values() if n.acknowledged]
        if len(acked) > self._max_acknowledged:
            for n in sorted(acked, key=lambda n: n.created_at)[:len(acked) - self._max_acknowledged]:
                del self._notifications[n.id]
```

### 3. Wire into Runtime

In `src/probos/runtime.py`:

- Import `NotificationQueue` from `task_tracker`
- In `__init__`, create: `self.notification_queue = NotificationQueue(on_event=self._emit_event)`
- Add convenience method:
  ```python
  def notify(self, agent_id: str, title: str, detail: str = "",
             notification_type: str = "info", action_url: str = "") -> None:
      """Let any agent emit a notification to the Captain."""
      agent = self._find_agent(agent_id)
      agent_type = agent.agent_type if agent else "unknown"
      department = self._get_agent_department(agent_id) if agent else ""
      self.notification_queue.notify(
          agent_id=agent_id, agent_type=agent_type, department=department,
          title=title, detail=detail,
          notification_type=notification_type, action_url=action_url,
      )
  ```
- In `build_state_snapshot()`, add `"notifications": self.notification_queue.snapshot()` and `"unread_count": self.notification_queue.unread_count()` to the snapshot dict

Note: `_find_agent` and `_get_agent_department` are helper methods. If they
don't exist, implement them:
- `_find_agent(agent_id)`: iterate `self.pools`, check each pool's agents
- `_get_agent_department(agent_id)`: find pool containing agent, look up its
  pool group name

### 4. API Endpoints

In `src/probos/api.py`, add two endpoints:

```python
@app.post("/api/notifications/{notification_id}/ack")
async def ack_notification(notification_id: str):
    ok = runtime.notification_queue.acknowledge(notification_id)
    return {"acknowledged": ok}

@app.post("/api/notifications/ack-all")
async def ack_all_notifications():
    count = runtime.notification_queue.acknowledge_all()
    return {"acknowledged": count}
```

## TypeScript — Frontend

### 5. Notification type

Add to `ui/src/store/types.ts`:

```typescript
export interface NotificationView {
    id: string;
    agent_id: string;
    agent_type: string;
    department: string;
    notification_type: 'info' | 'action_required' | 'error';
    title: string;
    detail: string;
    action_url: string;
    created_at: number;
    acknowledged: boolean;
}
```

### 6. Zustand store

In `ui/src/store/useStore.ts`:

- Add to `HXIState` interface: `notifications: NotificationView[] | null;`
- Add initial state: `notifications: null,`
- Add `handleEvent` cases for `notification`, `notification_ack`, and
  `notification_snapshot` — all update `notifications` from `data.notifications`
- In the `state_snapshot` handler, hydrate notifications from
  `(data as any).notifications`

### 7. NotificationDropdown component

Create `ui/src/components/NotificationDropdown.tsx`:

- **Dropdown panel** — NOT a full-width drawer. Position absolutely below the
  bell button, width ~320px, max-height ~400px with overflow scroll
- **Glass styling** matching ActivityDrawer: `rgba(10, 10, 18, 0.92)`,
  `backdropFilter: 'blur(16px)'`, `border: 1px solid rgba(255,255,255,0.08)`
- **Header** — "NOTIFICATIONS" label (amber, 11px, letterSpacing 2) + "Mark
  all read" button (only shown when unread > 0) + close X button
- **Notification cards** — similar to TaskCard pattern:
  - Left border color by notification type: info=#5090d0, action_required=#f0b060, error=#ff5555
  - Title (bold), detail (dim), agent type + department tags, relative time
  - Unread cards have slightly brighter background (`rgba(255,255,255,0.06)`)
  - Click to acknowledge (single notification)
- **Empty state** — "No notifications" centered text when list is empty
- Props: `open: boolean`, `onClose: () => void`
- Call `POST /api/notifications/{id}/ack` on card click
- Call `POST /api/notifications/ack-all` on "Mark all read" click

### 8. Bell button in IntentSurface

In `ui/src/components/IntentSurface.tsx`:

- Import `NotificationDropdown`
- Add state: `const [notifOpen, setNotifOpen] = useState(false);`
- Read from store: `const notifications = useStore(s => s.notifications);`
- Compute: `const unreadCount = notifications?.filter(n => !n.acknowledged).length ?? 0;`
- Add bell button using the same pattern as ACTIVITY button:
  - Position: `right: 210, top: 12, zIndex: 25`  (shift left of ACTIVITY at 110)
  - Label text: use unicode bell `\u{1F514}` or text `NOTIF` with count badge
  - Badge styling: if `unreadCount > 0`, show count in parentheses and use
    amber color (`#f0b060`)
  - Active state when dropdown is open (same `background: rgba(...)` pattern)
- Render `<NotificationDropdown open={notifOpen} onClose={() => setNotifOpen(false)} />`
  positioned below the bell button

## Tests

### Python tests (`tests/test_task_tracker.py` or new `tests/test_notifications.py`):

1. **test_notify_creates_notification** — call `notify()`, verify returned
   notification has correct fields
2. **test_notify_emits_event** — mock `on_event`, verify `"notification"` event
   fired with correct data including `unread_count`
3. **test_acknowledge_marks_read** — create notification, acknowledge it,
   verify `acknowledged=True`
4. **test_acknowledge_nonexistent_returns_false** — acknowledge unknown id
5. **test_acknowledge_all** — create 3 notifications, ack all, verify count
6. **test_snapshot_sorted_newest_first** — create notifications at different
   times, verify sort order
7. **test_prune_old_acknowledged** — create >50 acknowledged notifications,
   verify pruning
8. **test_unread_count** — mix of read/unread, verify count
9. **test_runtime_notify_convenience** — mock a runtime with pools, call
   `rt.notify()`, verify notification created with correct agent_type/department

### Vitest tests (`ui/src/components/__tests__/NotificationDropdown.test.tsx`):

1. **test renders notification cards** — pass mock notifications, verify cards render
2. **test unread count badge** — verify badge shows correct count
3. **test empty state** — verify "No notifications" shown when empty

## Files to modify

- `src/probos/task_tracker.py` — add `AgentNotification` + `NotificationQueue`
- `src/probos/runtime.py` — wire `NotificationQueue`, add `notify()` method,
  update `build_state_snapshot()`
- `src/probos/api.py` — add ack endpoints
- `ui/src/store/types.ts` — add `NotificationView`
- `ui/src/store/useStore.ts` — add notifications state + event handlers
- `ui/src/components/IntentSurface.tsx` — add bell button
- `ui/src/components/NotificationDropdown.tsx` — **new file**

## Files to read first

- `src/probos/task_tracker.py` — full file, follow `TaskTracker` + `AgentTask` patterns
- `src/probos/runtime.py` — `__init__()`, `build_state_snapshot()`, `_emit_event()`
- `src/probos/api.py` — existing endpoints pattern, WebSocket events
- `ui/src/store/useStore.ts` — `handleEvent` switch, `HXIState` interface
- `ui/src/store/types.ts` — existing type patterns (`AgentTaskView`)
- `ui/src/components/ActivityDrawer.tsx` — glass styling, card layout patterns
- `ui/src/components/IntentSurface.tsx` — header button positioning

## Acceptance criteria

- Agents can call `rt.notify()` to emit notifications
- Notifications persist until acknowledged
- Bell button in HXI header shows unread count
- Dropdown panel renders notification cards with type-colored left borders
- Single-click acknowledges individual notifications
- "Mark all read" acknowledges all
- `action_required` notifications visually distinct (amber styling)
- State hydrated from snapshot on WebSocket connect
- All existing tests pass
- New Python + Vitest tests cover the notification lifecycle
