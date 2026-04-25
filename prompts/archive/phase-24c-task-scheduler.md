# Phase 24c: Lightweight Task Scheduler (AD-281 through AD-284)

> **Context:** ProbOS identified its own lack of background scheduling as an
> architectural gap during a self-assessment conversation via Discord. When asked
> "can you send me a message in one minute?" it honestly admitted it had no
> background timer. This phase adds a session-scoped task scheduler so ProbOS can
> execute deferred and recurring tasks within a running `probos serve` session.
>
> **Scope boundary:** This is a lightweight, in-session scheduler. Tasks do NOT
> survive server restarts. Persistent tasks with checkpointing and resume-after-
> restart remain in Phase 25.

## Pre-read

Before starting, read these files to understand existing patterns:
- `src/probos/agents/bundled/organizer_agents.py` — existing `SchedulerAgent` (line ~184). Currently stores reminders to file but cannot execute them on a timer. This agent will be upgraded.
- `src/probos/runtime.py` — `ProbOSRuntime`, look at how `_dreaming_engine` runs on a background loop as a pattern for background asyncio tasks
- `src/probos/cognitive/dreaming.py` — `DreamingEngine` pattern: background `asyncio.Task` with interval-based execution
- `src/probos/substrate/scaler.py` — `PoolScaler` pattern: another background loop with configured intervals
- `src/probos/channels/base.py` — `ChannelAdapter.send_response()` for delivering results to channels
- `src/probos/types.py` — existing dataclasses for reference
- `PROGRESS.md` line 2 — current test count

## Step 1: Create TaskScheduler Engine (AD-281)

Create `src/probos/cognitive/task_scheduler.py`.

**Design:**
- `ScheduledTask` dataclass: `id`, `created_at`, `execute_at`, `interval_seconds` (None for one-shot, float for recurring), `intent_text` (natural language to process), `channel_id` (optional — which channel to deliver results to), `status` (pending/running/completed/failed), `last_result`
- `TaskScheduler` class:
  - Holds a `dict[str, ScheduledTask]` of pending tasks
  - `start()` / `stop()` manage a background `asyncio.Task` that ticks every 1 second
  - On each tick, check for tasks where `execute_at <= now`:
    - Set status to "running"
    - Call `runtime.process_natural_language(task.intent_text)` to execute
    - Store result in `last_result`, set status to "completed" (or "failed")
    - If `interval_seconds` is set, compute next `execute_at` and reset status to "pending"
    - If `channel_id` is set, deliver result text via the appropriate channel adapter
  - `schedule(text, delay_seconds, interval_seconds=None, channel_id=None) -> ScheduledTask`
  - `cancel(task_id) -> bool`
  - `list_tasks() -> list[ScheduledTask]`
  - `get_stats() -> dict` — count by status, next upcoming task
- The tick loop should use `asyncio.sleep(1)` and catch all exceptions per-task (one task failure must not crash the scheduler)
- Follow the `DreamingEngine` pattern for the background loop lifecycle

**Tests** (in `tests/test_task_scheduler.py`):
1. `schedule()` creates a task with correct `execute_at`
2. One-shot task executes after delay and moves to "completed"
3. Recurring task re-schedules after execution
4. `cancel()` removes a pending task
5. `list_tasks()` returns all tasks sorted by execute_at
6. Failed task execution sets status to "failed", doesn't crash scheduler
7. `stop()` cancels the background loop cleanly

Use a `FakeRuntime` with a mock `process_natural_language` for testing.

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

## Step 2: Wire TaskScheduler into Runtime (AD-282)

**Files to modify:**

1. `src/probos/runtime.py`:
   - Create `TaskScheduler` in `__init__()` (similar to `_dreaming_engine`)
   - Call `task_scheduler.start()` in `start()` after pools are running
   - Call `task_scheduler.stop()` in `stop()` before pools shut down
   - Expose `task_scheduler` as a property for shell/introspection access

2. `src/probos/__main__.py`:
   - Pass channel adapters list to runtime (or to TaskScheduler) so scheduled tasks can deliver results to Discord/other channels

**Tests:**
1. Runtime starts and stops TaskScheduler without error
2. Scheduled task executes via runtime integration

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

## Step 3: Upgrade SchedulerAgent (AD-283)

**Files to modify:**

1. `src/probos/agents/bundled/organizer_agents.py` — `SchedulerAgent`:
   - Remove the "no background timer" disclaimer from `instructions`
   - Update instructions: reminders now actually execute on schedule within the session
   - In `act()`, when action is "remind" with a time, call `runtime.task_scheduler.schedule()`
   - For "list", call `runtime.task_scheduler.list_tasks()`
   - For "cancel", call `runtime.task_scheduler.cancel(task_id)`
   - Keep file-backed persistence for reminders that should survive restart (store task definitions in reminders.json, reload on boot)
   - On boot: reload reminders.json and re-schedule any future-dated tasks

2. Update `instructions` to reflect new capabilities:
   - "Reminders will now be delivered on schedule as long as ProbOS is running"
   - "For recurring tasks, specify an interval (e.g., 'every hour', 'every day')"
   - "Tasks do not survive server restarts — they will be re-loaded from saved reminders on next boot"

**Tests:**
1. SchedulerAgent "remind" action creates a scheduled task
2. SchedulerAgent "list" action returns tasks from TaskScheduler
3. SchedulerAgent "cancel" action cancels a scheduled task
4. Reminders persist to file and reload on boot

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

## Step 4: Channel Delivery for Scheduled Tasks (AD-284)

When a scheduled task has a `channel_id`, the result should be delivered to the appropriate channel (Discord, future Slack, etc.) rather than just stored silently.

**Files to modify:**

1. `src/probos/cognitive/task_scheduler.py`:
   - Accept a `channel_adapters: list` in constructor (or a callback)
   - After task execution, if `channel_id` is set, find the adapter and call `send_response(channel_id, result_text)`

2. `src/probos/channels/base.py`:
   - Ensure `send_response()` can be called from the scheduler context (it's already async, so this should work)

3. `src/probos/channels/discord_adapter.py`:
   - Verify `send_response()` works when called outside of `on_message` context

**Tests:**
1. Scheduled task with channel_id delivers result via adapter
2. Scheduled task without channel_id stores result silently
3. Channel delivery failure doesn't crash the scheduler

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

## Step 5: Update PROGRESS.md

- Update test count on line 2
- Add Phase 24c section with AD-281 through AD-284
- Note the SchedulerAgent upgrade removes "no background timer" limitation
- Update Phase 25 roadmap to note that in-session scheduling is now complete; Phase 25 focuses on persistence across restarts

## Verification

After all steps, the following should work:
- "Send me a message in one minute" → ProbOS schedules a task → message delivered after 60 seconds
- "Check my stocks every hour" → recurring task created → executes hourly
- "Cancel my stock check" → task cancelled
- "What's scheduled?" → list of pending tasks
- Via Discord: scheduled results delivered to the Discord channel
- All existing tests still pass
- Report final test count
