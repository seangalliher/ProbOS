# AD-435: Restart Announcements

**Goal:** When ProbOS shuts down or restarts, post a system announcement to the Ward Room "All Hands" channel so agents have context on reboots. Without this, agents observe cold restarts and misinterpret dev-cycle reboots as system instability (observed: Bones, Ogawa, Selar all flagged restarts as pathological).

**Scope:** Small. Two integration points — shutdown and startup.

---

## Design

### 1. Shutdown Announcement

In `runtime.py` `stop()`, **before** tearing down services, post a system announcement to the "All Hands" Ward Room channel.

Add an optional `reason` parameter to `stop()`:

```python
async def stop(self, reason: str = "") -> None:
```

Post the announcement early in `stop()`, right after the existing `event_log.log(category="system", event="stopping")` call (line ~1344), **before** any services are torn down (Ward Room must still be alive):

```python
# AD-435: Announce shutdown to Ward Room
if self.ward_room and self.ward_room._db:
    try:
        # Find All Hands channel by name
        all_hands = None
        async with self.ward_room._db.execute(
            "SELECT id FROM channels WHERE name = 'All Hands' LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                all_hands = row[0]
        if all_hands:
            msg = "System shutdown initiated."
            if reason:
                msg += f" Reason: {reason}"
            await self.ward_room.create_thread(
                channel_id=all_hands,
                author_id="system",
                title="System Restart",
                body=msg,
                author_callsign="Ship's Computer",
                thread_mode="announce",
                max_responders=0,
            )
    except Exception:
        pass  # best-effort, don't block shutdown
```

**Key points:**
- Use `thread_mode="announce"` and `max_responders=0` — this is a notification, not a discussion
- Author is `"system"` with callsign `"Ship's Computer"` — consistent with channel creation author
- Best-effort: wrapped in try/except, must never block shutdown
- Ward Room must still be initialized when this runs (post BEFORE teardown)

### 2. Shell `/quit` — Pass Reason

Update `_cmd_quit()` in `experience/shell.py` to accept an optional reason and pass it to `runtime.stop()`:

```python
async def _cmd_quit(self, arg: str) -> None:
    self._quit_reason = arg.strip() if arg else ""
    self._running = False
    self.console.print("[dim]Shutting down...[/dim]")
```

Then in the shell's main loop cleanup (wherever `runtime.stop()` is called after the loop exits), pass the reason:

```python
await runtime.stop(reason=self._quit_reason)
```

Find where `runtime.stop()` is called from the shell/main entry point and ensure the reason is threaded through. If the shell doesn't directly call `runtime.stop()`, store the reason on the shell instance and have the caller retrieve it. The important thing: the reason must reach `runtime.stop(reason=...)`.

### 3. Startup Context (Lightweight)

In `runtime.py` `start()`, **after** Ward Room is initialized and channels are seeded, post a brief startup announcement:

```python
# AD-435: Announce startup to Ward Room
if self.ward_room:
    try:
        all_hands = None
        async with self.ward_room._db.execute(
            "SELECT id FROM channels WHERE name = 'All Hands' LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                all_hands = row[0]
        if all_hands:
            await self.ward_room.create_thread(
                channel_id=all_hands,
                author_id="system",
                title="System Online",
                body="ProbOS startup complete. All systems operational.",
                author_callsign="Ship's Computer",
                thread_mode="announce",
                max_responders=0,
            )
    except Exception:
        pass  # best-effort
```

Place this **after** all services are started and agents are wired — it should be the last thing in `start()` before returning.

---

## Tests

Add to `tests/test_ward_room.py` or a new `tests/test_restart_announcements.py`:

### Test 1: Shutdown posts announcement
```python
async def test_shutdown_announcement(self):
    """AD-435: runtime.stop() posts shutdown announcement to All Hands."""
    # Setup: runtime with ward_room initialized, All Hands channel exists
    # Act: await runtime.stop(reason="Development build")
    # Assert: All Hands channel has a thread titled "System Restart"
    #         with body containing "Development build"
    #         thread_mode is "announce"
```

### Test 2: Shutdown without reason
```python
async def test_shutdown_announcement_no_reason(self):
    """AD-435: Shutdown announcement works without a reason."""
    # Act: await runtime.stop()  (no reason)
    # Assert: Thread body is "System shutdown initiated." (no "Reason:" suffix)
```

### Test 3: Shutdown survives missing Ward Room
```python
async def test_shutdown_no_ward_room(self):
    """AD-435: stop() doesn't crash when Ward Room is unavailable."""
    # Setup: runtime.ward_room = None
    # Act: await runtime.stop()
    # Assert: No exception raised
```

### Test 4: Startup posts online announcement
```python
async def test_startup_announcement(self):
    """AD-435: runtime.start() posts 'System Online' to All Hands."""
    # Setup: start runtime with ward_room
    # Assert: All Hands has a thread titled "System Online"
```

### Test 5: Shell /quit passes reason
```python
async def test_quit_with_reason(self):
    """AD-435: /quit stores reason for shutdown announcement."""
    # Act: shell._cmd_quit("Deploying AD-435")
    # Assert: shell._quit_reason == "Deploying AD-435"
```

---

## Files Modified

| File | Change |
|------|--------|
| `src/probos/runtime.py` | `stop(reason="")` param, shutdown announcement, startup announcement |
| `src/probos/experience/shell.py` | `/quit` reason threading |
| `tests/test_restart_announcements.py` | 5 new tests |

## Out of Scope

- Distinguishing crash vs. graceful shutdown in agent reasoning (future: if no shutdown announcement precedes a startup, agents can infer a crash occurred)
- Restart-specific command (`/restart`) — currently ProbOS doesn't have one
- Per-agent shutdown notifications (all agents get context via All Hands)
