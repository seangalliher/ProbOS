# AD-323: Agent Notification Queue

## Goal

Give agents a persistent notification channel to the Captain. Today, agent communications appear only in the chat stream and are easy to miss. The notification queue provides a bell icon in the HXI header with an unread count badge — persistent, actionable notifications that stay pinned until the Captain acknowledges them.

## Architecture

Notifications are stored in the TaskTracker (AD-316) alongside tasks. The backend provides an API to create and acknowledge notifications. The frontend renders a bell icon dropdown.

## Files to Create

### `src/probos/notifications.py` (~120 lines)

```python
"""AD-323: Agent Notification Queue."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class NotificationType(str, Enum):
    INFO = "info"
    ACTION_REQUIRED = "action_required"
    ERROR = "error"
    SUCCESS = "success"


@dataclass
class AgentNotification:
    """A notification from an agent to the Captain."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    agent_id: str = ""
    agent_type: str = ""
    notification_type: NotificationType = NotificationType.INFO
    title: str = ""
    detail: str = ""
    task_id: str = ""  # link to related AgentTask, if any
    created_at: float = field(default_factory=time.time)
    acknowledged: bool = False
    acknowledged_at: float = 0.0

    def acknowledge(self) -> None:
        self.acknowledged = True
        self.acknowledged_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "notification_type": self.notification_type.value,
            "title": self.title,
            "detail": self.detail,
            "task_id": self.task_id,
            "created_at": self.created_at,
            "acknowledged": self.acknowledged,
            "acknowledged_at": self.acknowledged_at,
        }


class NotificationQueue:
    """Persistent notification queue for agent-to-Captain communication (AD-323).

    Stores notifications. Emits events via callback for WebSocket broadcast.
    """

    def __init__(self, on_event: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        self._notifications: dict[str, AgentNotification] = {}
        self._on_event = on_event
        self._max_acknowledged: int = 100

    def notify(
        self,
        *,
        agent_id: str = "",
        agent_type: str = "",
        notification_type: NotificationType = NotificationType.INFO,
        title: str = "",
        detail: str = "",
        task_id: str = "",
    ) -> AgentNotification:
        notif = AgentNotification(
            agent_id=agent_id,
            agent_type=agent_type,
            notification_type=notification_type,
            title=title,
            detail=detail,
            task_id=task_id,
        )
        self._notifications[notif.id] = notif
        self._emit("notification_created", notif)
        return notif

    def acknowledge(self, notification_id: str) -> bool:
        notif = self._notifications.get(notification_id)
        if not notif:
            return False
        notif.acknowledge()
        self._emit("notification_updated", notif)
        self._prune_acknowledged()
        return True

    def acknowledge_all(self) -> int:
        count = 0
        for notif in self._notifications.values():
            if not notif.acknowledged:
                notif.acknowledge()
                count += 1
        if count > 0:
            self._emit_snapshot()
        self._prune_acknowledged()
        return count

    def unread_count(self) -> int:
        return sum(1 for n in self._notifications.values() if not n.acknowledged)

    def unread(self) -> list[AgentNotification]:
        return [n for n in self._notifications.values()
                if not n.acknowledged]

    def all_notifications(self) -> list[AgentNotification]:
        return sorted(self._notifications.values(),
                       key=lambda n: n.created_at, reverse=True)

    def snapshot(self) -> dict[str, Any]:
        return {
            "notifications": [n.to_dict() for n in self.all_notifications()],
            "unread_count": self.unread_count(),
        }

    def _emit(self, event_type: str, notif: AgentNotification) -> None:
        if self._on_event:
            self._on_event(event_type, {
                "notification": notif.to_dict(),
                **self.snapshot(),
            })

    def _emit_snapshot(self) -> None:
        if self._on_event:
            self._on_event("notification_snapshot", self.snapshot())

    def _prune_acknowledged(self) -> None:
        acked = [n for n in self._notifications.values() if n.acknowledged]
        if len(acked) > self._max_acknowledged:
            acked.sort(key=lambda n: n.acknowledged_at)
            for n in acked[: len(acked) - self._max_acknowledged]:
                del self._notifications[n.id]
```

## Files to Modify

### `src/probos/runtime.py`

**1. Add import** near the task_tracker import:

```python
from probos.notifications import NotificationQueue
```

**2. Add field** in `__init__()` after `self.task_tracker`:

```python
# --- Notification Queue (AD-323) ---
self.notification_queue: NotificationQueue | None = None
```

**3. Initialize in `start()`** after task_tracker initialization:

```python
# --- Notification Queue (AD-323) ---
self.notification_queue = NotificationQueue(on_event=self._emit_event)
logger.info("notification-queue started")
```

**4. Cleanup in `stop()`** after task_tracker cleanup:

```python
if self.notification_queue:
    self.notification_queue = None
```

**5. Add to `build_state_snapshot()`**:

```python
if self.notification_queue:
    snapshot["notifications"] = self.notification_queue.snapshot()
```

### `src/probos/api.py`

Add two endpoints after the existing build queue endpoints:

**1. Acknowledge a notification:**

```python
class NotificationAckRequest(BaseModel):
    notification_id: str

@app.post("/api/notifications/acknowledge")
async def acknowledge_notification(req: NotificationAckRequest) -> dict[str, Any]:
    if not runtime or not runtime.notification_queue:
        return {"ok": False, "error": "Notification queue not available"}
    ok = runtime.notification_queue.acknowledge(req.notification_id)
    return {"ok": ok}
```

**2. Acknowledge all notifications:**

```python
@app.post("/api/notifications/acknowledge-all")
async def acknowledge_all_notifications() -> dict[str, Any]:
    if not runtime or not runtime.notification_queue:
        return {"ok": False, "error": "Notification queue not available"}
    count = runtime.notification_queue.acknowledge_all()
    return {"ok": True, "acknowledged": count}
```

**3. Get notifications:**

```python
@app.get("/api/notifications")
async def get_notifications() -> dict[str, Any]:
    if not runtime or not runtime.notification_queue:
        return {"notifications": [], "unread_count": 0}
    return runtime.notification_queue.snapshot()
```

### `ui/src/store/types.ts`

Add after `AgentTaskView`:

```typescript
export interface AgentNotificationView {
  id: string;
  agent_id: string;
  agent_type: string;
  notification_type: 'info' | 'action_required' | 'error' | 'success';
  title: string;
  detail: string;
  task_id: string;
  created_at: number;
  acknowledged: boolean;
  acknowledged_at: number;
}
```

### `ui/src/store/useStore.ts`

**1. Add import** — add `AgentNotificationView` to the import from `./types`.

**2. Add state fields** to `HXIState` interface:

```typescript
notifications: AgentNotificationView[] | null;
unreadNotificationCount: number;
notificationDrawerOpen: boolean;
```

**3. Initialize** in the state object:

```typescript
notifications: null,
unreadNotificationCount: 0,
notificationDrawerOpen: false,
```

**4. Add event handler cases** in `handleEvent` switch:

```typescript
case 'notification_created':
case 'notification_updated':
case 'notification_snapshot': {
  const notifications = (data.notifications || []) as AgentNotificationView[];
  const unreadCount = (data.unread_count ?? 0) as number;
  set({
    notifications: notifications.length > 0 ? notifications : null,
    unreadNotificationCount: unreadCount,
  });
  break;
}
```

**5. Update `state_snapshot` handler** — add after tasks hydration:

```typescript
if (data.notifications) {
  const snap = data.notifications as { notifications: AgentNotificationView[]; unread_count: number };
  set({
    notifications: snap.notifications.length > 0 ? snap.notifications : null,
    unreadNotificationCount: snap.unread_count ?? 0,
  });
}
```

### `ui/src/components/IntentSurface.tsx`

Add a bell icon button in the header area (near the Mission Control toggle button). Implementation:

**1. Add a bell icon button** next to the Mission Control toggle:

```tsx
{/* Notification bell (AD-323) */}
<button
  onClick={() => useStore.getState().set?.({ notificationDrawerOpen: !useStore.getState().notificationDrawerOpen })}
  style={{
    background: 'none', border: 'none', cursor: 'pointer',
    color: unreadNotificationCount > 0 ? '#ffaa44' : '#555',
    fontSize: 14, position: 'relative', padding: '4px 8px',
  }}
  title="Notifications"
>
  &#x1F514;
  {unreadNotificationCount > 0 && (
    <span style={{
      position: 'absolute', top: 0, right: 2,
      background: '#ff5555', color: '#fff',
      borderRadius: '50%', width: 14, height: 14,
      fontSize: 8, fontWeight: 700,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      {unreadNotificationCount > 9 ? '9+' : unreadNotificationCount}
    </span>
  )}
</button>
```

**2. Add notification dropdown render** — when `notificationDrawerOpen` is true, render a dropdown panel below the bell icon showing the list of notifications. Each notification shows:
- Notification type badge (info=blue, action_required=amber, error=red, success=green)
- Title (bold) and detail (lighter)
- Agent type
- Relative time (e.g. "2m ago")
- Unread indicator (dot)
- Click to acknowledge individual notification (POST to `/api/notifications/acknowledge`)
- "Mark all read" button at top (POST to `/api/notifications/acknowledge-all`)

Position the dropdown as an absolute-positioned panel below the bell, right-aligned, max-height 400px with overflow scroll. Style consistent with existing HXI dark theme.

## Files to Create — Tests

### `tests/test_notifications.py`

Test these behaviors:
1. `NotificationQueue()` creates with empty state
2. `notify()` creates a notification and emits `notification_created`
3. `acknowledge()` marks notification as acknowledged with timestamp
4. `acknowledge()` returns False for unknown id
5. `acknowledge_all()` acknowledges all unread, returns count
6. `unread_count()` counts only unacknowledged
7. `unread()` returns only unacknowledged notifications
8. `all_notifications()` returns sorted by created_at descending
9. `snapshot()` includes notifications list and unread_count
10. `_prune_acknowledged()` removes oldest acknowledged when exceeding max
11. `AgentNotification.to_dict()` includes all fields
12. Event callback receives both individual notification and full snapshot

Use `unittest.TestCase`.

## Verification

```bash
cd d:\ProbOS
.venv/Scripts/python.exe -m pytest tests/test_notifications.py -v
```

All tests must pass. Do NOT modify any files not listed in this prompt.
