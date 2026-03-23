# BF-011: Discord Adapter Shutdown Hang on Windows

## Problem

When ProbOS shuts down (via `/quit` or Ctrl+C) with the Discord adapter running, the process hangs instead of exiting cleanly. The user must force-kill the process.

`os._exit(0)` exists as a nuclear fallback at `__main__.py:445`, but the process hangs in `await` calls **before** it reaches that line.

## Root Cause

Three compounding issues, all specific to Windows `SelectorEventLoop` + discord.py:

### Issue 1: `bot.close()` blocks the event loop

discord.py's `close()` internally does SSL/WebSocket teardown that can make blocking calls on Windows `SelectorEventLoop`. When the event loop is blocked, `asyncio.wait_for()` timeouts **never fire** — the timer callback can't execute because the loop isn't processing events.

Current code (`discord_adapter.py:137`):
```python
await asyncio.wait_for(self._bot.close(), timeout=3.0)
```

This timeout is unreliable because `bot.close()` can block the loop itself, preventing the timeout from being processed.

### Issue 2: Double `close()` via task cancellation

After `bot.close()` times out, the code cancels `_bot_task` (line 143). But cancelling the task running `bot.start()` causes discord.py's internal cleanup to call `close()` **again**. The second `close()` hangs for the same reason as the first.

### Issue 3: `os._exit(0)` is unreachable

The `os._exit(0)` at `__main__.py:445` should be the final backstop, but the process is stuck in `await asyncio.wait_for(adapter.stop(), timeout=5)` at line 425. If the event loop is blocked (Issue 1), this outer timeout also never fires.

## Fix: Thread-Isolated Shutdown with Hard Deadline

The key insight: **don't await discord cleanup on the main event loop**. Run the entire teardown in a background thread with its own event loop, so discord.py's blocking behavior can't stall the main loop.

### Implementation

Replace the `stop()` method in `src/probos/channels/discord_adapter.py`:

```python
async def stop(self) -> None:
    """Close the Discord connection.

    discord.py's shutdown path can block the event loop on Windows
    (SSL teardown, keep-alive thread joins). We isolate the teardown
    in a dedicated thread with its own event loop so blocking calls
    can't defeat asyncio.wait_for() timeouts on the main loop.
    """
    if not self._started:
        return

    # ---- Suppress known discord.py shutdown noise ----

    _original_excepthook = threading.excepthook

    def _suppress_keepalive(args: threading.ExceptHookArgs) -> None:
        if (
            args.exc_type is RuntimeError
            and args.thread
            and "keep-alive" in (args.thread.name or "")
        ):
            return
        _original_excepthook(args)

    threading.excepthook = _suppress_keepalive
    warnings.filterwarnings(
        "ignore",
        message="coroutine.*was never awaited",
        category=RuntimeWarning,
    )

    # ---- Thread-isolated teardown ----

    bot = self._bot
    bot_task = self._bot_task

    def _teardown_in_thread() -> None:
        """Run discord teardown in a separate thread with a hard deadline.

        This prevents discord.py's blocking SSL/WebSocket cleanup from
        stalling the main event loop on Windows SelectorEventLoop.
        """
        if bot and not bot.is_closed():
            # Create a fresh event loop for the teardown
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    asyncio.wait_for(bot.close(), timeout=2.0)
                )
            except Exception:
                pass
            finally:
                try:
                    loop.close()
                except Exception:
                    pass

        # Force-close the HTTP session if still open
        if bot and hasattr(bot, "http"):
            http = bot.http
            session = getattr(http, "_HTTPClient__session", None)
            if session and not session.closed:
                loop2 = asyncio.new_event_loop()
                try:
                    loop2.run_until_complete(session.close())
                except Exception:
                    pass
                finally:
                    try:
                        loop2.close()
                    except Exception:
                        pass

    # Run teardown in a thread with a hard 3-second wall-clock deadline.
    # threading.Thread.join(timeout) is a real OS timeout that can't be
    # blocked by asyncio event loop issues.
    teardown_thread = threading.Thread(
        target=_teardown_in_thread,
        name="discord-teardown",
        daemon=True,
    )
    teardown_thread.start()
    # Use to_thread so we don't block the main event loop while waiting
    await asyncio.to_thread(teardown_thread.join, 3.0)

    # Cancel the bot task (don't await — avoids the double-close hang)
    if bot_task and not bot_task.done():
        bot_task.cancel()

    self._bot = None
    self._bot_task = None
    self._started = False
    logger.info("Discord adapter stopped")
```

### Why this works

1. **`_teardown_in_thread()` runs on a daemon thread** with `asyncio.new_event_loop()`. discord.py's blocking SSL calls happen on this thread's loop, not the main loop. The main event loop stays responsive.

2. **`teardown_thread.join(3.0)` is a real OS-level timeout** — `threading.Thread.join(timeout)` uses the OS thread scheduler, not asyncio timers. It **always** returns after 3 seconds regardless of what discord.py does.

3. **`daemon=True`** means if the thread is still running when the process exits, Python kills it. No zombie threads.

4. **Task cancellation without await** — `bot_task.cancel()` without awaiting avoids the double-close hang. The task will be cleaned up when the event loop closes.

5. **`await asyncio.to_thread(teardown_thread.join, 3.0)`** wraps the blocking `join()` so the main event loop stays responsive during the wait. Other shutdown work can proceed.

### What NOT to change

- Keep the `threading.excepthook` suppression — still needed for the keep-alive thread.
- Keep the `warnings.filterwarnings` — still needed for unawaited coroutine warnings.
- Keep `os._exit(0)` in `__main__.py` as the final backstop — belt and suspenders.
- Don't change `start()` — the single-event-loop design is correct for runtime integration.
- Don't change `__main__.py` shutdown sequence — the 5-second outer timeout at line 425 is fine; it will now actually fire because the main loop stays unblocked.

## Files Modified

| File | Change |
|------|--------|
| `src/probos/channels/discord_adapter.py` | Replace `stop()` with thread-isolated teardown |

One file. No new dependencies.

## Testing

1. **Manual test (primary):** Start ProbOS with Discord adapter enabled. Send a message via Discord to confirm it's connected. Type `/quit` in the shell. Verify:
   - "Stopping DiscordAdapter... done" appears (not "timed out")
   - "ProbOS stopped." appears
   - Process exits within ~5 seconds
   - No hang, no force-kill needed

2. **Manual test (no Discord):** Start ProbOS without Discord. `/quit`. Verify no regression — shutdown still works cleanly.

3. **Unit test:** Mock `discord.Client` with a `close()` that hangs forever (never returns). Call `adapter.stop()`. Verify it returns within 5 seconds despite the hanging `close()`.

4. **KBoard interrupt test:** Start with Discord, press Ctrl+C. Verify clean exit.

## Commit Message

```
Fix Discord adapter shutdown hang on Windows (BF-011)

discord.py's close() blocks the event loop during SSL/WebSocket
teardown on Windows SelectorEventLoop, defeating asyncio.wait_for()
timeouts. Isolate the teardown in a daemon thread with its own event
loop and use threading.Thread.join(timeout) for a real OS-level
deadline that can't be blocked.
```
