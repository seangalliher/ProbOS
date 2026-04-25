# Fix: ProbOS Serve Graceful Shutdown Hangs

## Problem

`probos serve` prints "ProbOS shutting down..." but then hangs indefinitely. The user has to force-kill the process or close the terminal. This happens on every Ctrl+C.

## Root Cause (investigate these)

The shutdown sequence likely hangs on one of:

1. **ChromaDB PersistentClient** — `client.close()` or background threads not terminating
2. **aiosqlite connections** — `HebbianRouter.stop()` or `TrustNetwork.stop()` waiting on uncommitted transactions
3. **DreamScheduler `_monitor_loop`** — asyncio task not being cancelled properly
4. **uvicorn shutdown** — WebSocket connections holding the event loop open
5. **KnowledgeStore flush** — `_schedule_commit()` timer or Git subprocess blocking

## Fix

**File:** `src/probos/__main__.py` — in the `serve` command handler

Add a forced shutdown timeout. After the graceful shutdown starts, if it hasn't completed in 5 seconds, force exit:

```python
import signal
import sys

async def _shutdown_with_timeout(runtime, timeout=5):
    """Attempt graceful shutdown, force exit if it hangs."""
    try:
        await asyncio.wait_for(runtime.stop(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("Graceful shutdown timed out after %ds — forcing exit", timeout)
    except Exception as e:
        logger.warning("Shutdown error: %s", e)
    finally:
        # Force exit regardless
        os._exit(0)
```

Wire this into the signal handler or the Ctrl+C handling:

```python
# In the serve command, after uvicorn stops:
try:
    await _shutdown_with_timeout(runtime, timeout=5)
except:
    os._exit(0)
```

Alternatively, if the serve command uses `uvicorn.run()` (which blocks), add a signal handler:

```python
import os
import signal

def _force_exit(signum, frame):
    """Force exit on second Ctrl+C or after timeout."""
    logger.info("Force shutdown.")
    os._exit(0)

signal.signal(signal.SIGINT, _force_exit)  # Second Ctrl+C force-kills
```

## Also check

- Does `runtime.stop()` call `await` on all subsystem `.stop()` methods?
- Is `DreamScheduler.stop()` cancelling its task and awaiting it?
- Is `EpisodicMemory.stop()` closing ChromaDB's client cleanly?
- Is there a `finally` block ensuring `os._exit(0)` runs even if shutdown hangs?

## After fix

1. Restart `probos serve`
2. Press Ctrl+C
3. Should exit within 5 seconds, printing "ProbOS shutting down..." then exiting cleanly
4. Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q` to verify no regressions
