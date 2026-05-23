# AD-812: Natural-language scheduled actions

**Status:** Ready for Builder
**Issue:** #736 — closes
**Dependencies:** AD-418 (PersistentTaskStore — shipped), AD-707 (WorkflowCronScheduler — shipped, not used directly), AD-803 (Telegram adapter — shipped), AD-791 (threads — shipped)
**Estimated tests:** 8 new

---

## Problem

The operator wants to say things like

- `/remind me to check the kitchen at 6pm`
- `/schedule every weekday at 7am send my LinkedIn metrics to Telegram`
- `/schedule in 2 hours check the agent fleet`

…and have ProbOS persist a scheduled action that fires on the correct cadence, delivers to the right channel, and survives restart.

The scheduling **substrate already exists** (AD-418 `PersistentTaskStore`): SQLite-backed, supports `once | interval | cron` schedule_type, `cron_expr` via `croniter`, `channel_id` for delivery, `max_runs`, restart-safe replay loop. What's missing is the **NL → ScheduleSpec parser** that translates operator English into a `create_task(...)` call, and the slash-command + API surface that exposes it.

This AD is purely the parser + surface. **It does NOT build a new scheduling store, a new background loop, or a new persistence layer.** The existing AD-418 plumbing handles all of that.

## Out of scope

- Building a parallel scheduler or background drain loop. `PersistentTaskStore.start()` is already wired by `runtime.communications.persistent_task_store` at boot.
- Channel-id resolution beyond best-effort name matching. If the operator says "to Telegram", we set `channel_id="telegram:default"` and let the existing adapter dispatch handle delivery; richer per-chat resolution is a follow-up AD.
- AD-707 `WorkflowCronScheduler` integration. That primitive is for re-firing **cached workflows** by exact `user_input` match (a different feature). AD-812 schedules **new intents** via `PersistentTaskStore`.
- Cron-expression validation beyond what `croniter` already provides.
- A `/schedule pause` command (file as forward marker if requested in review; `enabled=0` toggle exists on the row, but the surface is out of scope here).

## Solution

One new module + two surface bindings:

1. **`src/probos/cognitive/schedule_parser.py`** — pure NL → `ScheduleSpec` parser. Fast-tier LLM with a tight JSON-output prompt. Regex safety net for the cheapest cases ("in N minutes", "in N hours"). Honest-degrade: if no LLM and no regex match, return `ScheduleSpec(kind="error", reason=...)` and the slash command surfaces a usable error.
2. **`src/probos/experience/commands/commands_schedule.py`** — slash command handler module (mirrors `commands_insights.py` shape from AD-810). Implements `/remind`, `/schedule`, `/schedule list`, `/schedule cancel <id>`.
3. **`src/probos/routers/schedule_nl.py`** — `POST /api/schedule/nl` endpoint accepting `{text: str}` and returning the created task dict (or error). Existing `/api/scheduled-tasks` endpoints are not modified; this is a sibling endpoint for the NL surface.

Wire the slash commands into `shell.py` (one import + two dispatch lines, matching the AD-810 pattern). Wire the router into `api.py` (one import + one `app.include_router(...)`).

## License audit

| Dep | License | Decision |
|---|---|---|
| `croniter>=1.3` | MIT | Already a dep. Reuse. |
| `dateparser` | BSD-3 | **Reject.** ~2 MB install, locale-aware NL date parsing duplicates what fast-tier LLM does. Cite as research only. |
| `pytimeparse2` | MIT | **Reject.** Covers only durations; LLM handles superset. Cite as research only. |
| `apscheduler` | MIT | **Reject.** Full scheduler engine; AD-418 already provides the substrate. Cite as research only. |

**Result: zero new runtime deps.** All NL parsing routes through the existing fast-tier LLM; regex safety net is stdlib-only.

## Implementation

### Section 1 — `ScheduleSpec` + parser

New file `src/probos/cognitive/schedule_parser.py`.

```python
"""AD-812: natural-language → ScheduleSpec parser.

Pure function. Translates operator English into a dataclass the
slash-command handler can hand to PersistentTaskStore.create_task(...).

Design notes
------------
- Fast-tier LLM is the primary parse engine. Tight JSON-output prompt.
- Regex safety net handles the cheap "in N minutes/hours" case without
  paying for an LLM call.
- Honest-degrade: if the LLM is unavailable and regex doesn't match,
  return ScheduleSpec(kind="error", ...). The slash-command surfaces
  the error to the operator verbatim — no silent fallback.
- No new dependencies. croniter (MIT, already in deps) is the only
  third-party touched, and only to validate generated cron exprs.

Wave: 812. Issue: #736.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from probos.cognitive.llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

_VALID_KINDS = ("once", "interval", "cron", "error")


@dataclass(frozen=True)
class ScheduleSpec:
    """Parsed schedule. Maps directly onto PersistentTaskStore.create_task."""

    kind: Literal["once", "interval", "cron", "error"]
    intent_text: str = ""                     # the payload to fire
    execute_at: float | None = None           # epoch, used when kind="once"
    interval_seconds: float | None = None     # used when kind="interval"
    cron_expr: str | None = None              # used when kind="cron"
    channel_id: str | None = None             # "telegram:default" etc.
    max_runs: int | None = None
    reason: str = ""                          # populated when kind="error"


_SYSTEM_PROMPT = """You translate natural-language scheduling requests into JSON.

OUTPUT FORMAT (strict JSON, no prose, no markdown fences):
{
  "kind": "once" | "interval" | "cron",
  "intent_text": "<the action to perform, without the time/channel words>",
  "execute_at_iso": "<ISO-8601 datetime>" or null,
  "interval_seconds": <number> or null,
  "cron_expr": "<5-field cron>" or null,
  "channel": "<lowercase channel name or null>",
  "max_runs": <number> or null
}

RULES:
- "kind=once" → execute_at_iso set, others null.
- "kind=interval" → interval_seconds set, others null.
- "kind=cron" → cron_expr set, others null. Use standard 5-field cron (m h dom mon dow).
- Channel words ("to telegram", "via slack", "on discord") populate "channel".
  Otherwise channel is null. Do NOT invent channels.
- "intent_text" is the verb-phrase the operator wants executed, with the
  scheduling and channel words stripped. e.g. "every weekday at 7am send my
  LinkedIn metrics to Telegram" → intent_text="send my LinkedIn metrics".
- "every weekday" → cron_expr="0 H * * 1-5" with H from the parsed hour.
- "every Monday" → cron_expr with dow=1.
- Treat "now" as the current time.
- If the request is ambiguous, pick the most natural interpretation.
- Never output prose. Never wrap in ```json fences. Output the JSON object only.
"""


def _regex_relative(text: str, now: float) -> ScheduleSpec | None:
    """Cheap safety net for 'in N minutes/hours/days' phrasings.

    Returns a `once` ScheduleSpec if it can match, else None. We only
    match the simplest shapes here; anything else goes to the LLM.
    """
    m = re.search(
        r"\bin\s+(\d+)\s+(second|minute|hour|day)s?\b",
        text,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    seconds = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}[unit]
    intent = re.sub(
        r"\bin\s+\d+\s+(second|minute|hour|day)s?\b",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip(" ,.")
    if not intent:
        return None
    return ScheduleSpec(
        kind="once",
        intent_text=intent,
        execute_at=now + n * seconds,
    )


def _channel_to_id(name: str | None) -> str | None:
    """Map a free-form channel name to a `<adapter>:default` id.

    Conservative: only the adapters actually shipped at this AD's
    landing time. Unknown names → None and the slash-command surface
    falls back to no channel binding (REPL output only).
    """
    if not name:
        return None
    n = name.strip().lower()
    known = {"telegram", "slack", "discord", "matrix", "teams", "gmail"}
    if n in known:
        return f"{n}:default"
    return None


def _validate_cron(expr: str) -> bool:
    try:
        from croniter import croniter

        return croniter.is_valid(expr)
    except Exception:
        return False


async def parse_nl_schedule(
    text: str,
    llm_client: "BaseLLMClient | None" = None,
    *,
    now: float | None = None,
) -> ScheduleSpec:
    """Translate natural language into a ScheduleSpec.

    Order of operations:
      1. Regex safety net for "in N minutes/hours/days" — no LLM call.
      2. Fast-tier LLM with a strict JSON-output prompt.
      3. Honest-degrade to ScheduleSpec(kind="error", reason=...)
         when both fail. The caller surfaces the reason verbatim.
    """
    if not text or not text.strip():
        return ScheduleSpec(kind="error", reason="empty input")

    clock = time.time() if now is None else now

    fast = _regex_relative(text, clock)
    if fast is not None:
        logger.debug("AD-812: regex fast-path matched: %r → %s", text, fast)
        return fast

    if llm_client is None:
        return ScheduleSpec(
            kind="error",
            reason="LLM unavailable and request did not match the regex fast-path",
        )

    from probos.types import LLMRequest

    try:
        resp = await llm_client.complete(
            LLMRequest(
                prompt=text,
                system_prompt=_SYSTEM_PROMPT,
                tier="fast",
                max_tokens=256,
                temperature=0.0,
            )
        )
    except Exception as exc:
        logger.warning("AD-812: LLM parse failed (%s); returning error spec", exc)
        return ScheduleSpec(kind="error", reason=f"LLM parse failed: {exc}")

    raw = getattr(resp, "content", None) or getattr(resp, "text", "") or ""
    raw = raw.strip()
    if raw.startswith("```"):
        # Tolerate accidentally-fenced output from non-strict models.
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        obj = json.loads(raw)
    except Exception as exc:
        logger.warning("AD-812: LLM output not JSON (%s): %r", exc, raw[:200])
        return ScheduleSpec(kind="error", reason="LLM returned non-JSON output")

    kind = obj.get("kind")
    if kind not in ("once", "interval", "cron"):
        return ScheduleSpec(kind="error", reason=f"invalid kind {kind!r}")

    intent_text = (obj.get("intent_text") or "").strip()
    if not intent_text:
        return ScheduleSpec(kind="error", reason="intent_text missing")

    channel_id = _channel_to_id(obj.get("channel"))
    max_runs = obj.get("max_runs")
    if max_runs is not None and not isinstance(max_runs, int):
        max_runs = None

    if kind == "once":
        iso = obj.get("execute_at_iso")
        if not iso:
            return ScheduleSpec(kind="error", reason="execute_at_iso missing for kind=once")
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            execute_at = dt.timestamp()
        except Exception as exc:
            return ScheduleSpec(kind="error", reason=f"invalid execute_at_iso: {exc}")
        if execute_at <= clock:
            return ScheduleSpec(kind="error", reason="execute_at is in the past")
        return ScheduleSpec(
            kind="once",
            intent_text=intent_text,
            execute_at=execute_at,
            channel_id=channel_id,
            max_runs=max_runs,
        )

    if kind == "interval":
        secs = obj.get("interval_seconds")
        if not isinstance(secs, (int, float)) or secs <= 0:
            return ScheduleSpec(kind="error", reason="interval_seconds missing or non-positive")
        return ScheduleSpec(
            kind="interval",
            intent_text=intent_text,
            interval_seconds=float(secs),
            channel_id=channel_id,
            max_runs=max_runs,
        )

    # kind == "cron"
    expr = obj.get("cron_expr")
    if not expr or not _validate_cron(expr):
        return ScheduleSpec(kind="error", reason=f"invalid cron_expr: {expr!r}")
    return ScheduleSpec(
        kind="cron",
        intent_text=intent_text,
        cron_expr=expr,
        channel_id=channel_id,
        max_runs=max_runs,
    )
```

### Section 2 — Slash-command handler

New file `src/probos/experience/commands/commands_schedule.py`. Mirrors the `commands_insights.py` shape from AD-810.

```python
"""AD-812: /schedule and /remind slash commands."""

from __future__ import annotations

import logging
from typing import Any

from probos.cognitive.schedule_parser import ScheduleSpec, parse_nl_schedule

logger = logging.getLogger(__name__)


async def _create_from_spec(rt: Any, spec: ScheduleSpec) -> dict[str, Any]:
    """Translate a ScheduleSpec into a PersistentTaskStore.create_task call."""
    store = getattr(rt, "persistent_task_store", None)
    if store is None:
        return {"error": "Persistent task store not available"}
    task = await store.create_task(
        intent_text=spec.intent_text,
        schedule_type=spec.kind,
        execute_at=spec.execute_at,
        interval_seconds=spec.interval_seconds,
        cron_expr=spec.cron_expr,
        channel_id=spec.channel_id,
        max_runs=spec.max_runs,
    )
    return store._task_to_dict(task)


async def cmd_remind(rt: Any, con: Any, arg: str) -> None:
    """`/remind <natural language>` — convenience wrapper for one-shot reminders."""
    text = (arg or "").strip()
    if not text:
        con.print("[yellow]Usage:[/yellow] /remind <when> <what>")
        return
    spec = await parse_nl_schedule(text, llm_client=getattr(rt, "llm_client", None))
    if spec.kind == "error":
        con.print(f"[red]Could not parse:[/red] {spec.reason}")
        return
    result = await _create_from_spec(rt, spec)
    if "error" in result:
        con.print(f"[red]{result['error']}[/red]")
        return
    con.print(f"[green]Reminder scheduled[/green] id={result['id']} kind={spec.kind}")


async def cmd_schedule(rt: Any, con: Any, arg: str) -> None:
    """`/schedule [list | cancel <id> | <natural language>]`."""
    arg = (arg or "").strip()
    store = getattr(rt, "persistent_task_store", None)
    if store is None:
        con.print("[red]Persistent task store not available[/red]")
        return

    if not arg or arg == "list":
        tasks = await store.list_tasks(status="pending")
        if not tasks:
            con.print("[dim]No scheduled tasks pending.[/dim]")
            return
        for t in tasks:
            con.print(
                f"[cyan]{t.id}[/cyan] [{t.schedule_type}] {t.intent_text!r}"
                f" next={t.next_run_at}"
            )
        return

    if arg.startswith("cancel "):
        task_id = arg[len("cancel ") :].strip()
        ok = await store.cancel_task(task_id)
        con.print(
            f"[green]Cancelled[/green] {task_id}" if ok else f"[red]Unknown task[/red] {task_id}"
        )
        return

    spec = await parse_nl_schedule(arg, llm_client=getattr(rt, "llm_client", None))
    if spec.kind == "error":
        con.print(f"[red]Could not parse:[/red] {spec.reason}")
        return
    result = await _create_from_spec(rt, spec)
    if "error" in result:
        con.print(f"[red]{result['error']}[/red]")
        return
    con.print(
        f"[green]Scheduled[/green] id={result['id']} kind={spec.kind}"
        f" channel={spec.channel_id or 'none'}"
    )
```

Wire into `src/probos/experience/shell.py` (mirror the AD-810 pattern verified at lines 34, 115, 254):

```python
# SEARCH (near other commands_* imports, ~line 34):
from probos.experience.commands import commands_insights  # AD-810
# REPLACE WITH:
from probos.experience.commands import commands_insights  # AD-810
from probos.experience.commands import commands_schedule  # AD-812
```

```python
# SEARCH (in the slash help map, near AD-810's entry at ~line 115):
        "/insights":  "Show recent-activity summary (/insights [--days N], default 7) — AD-810",
# REPLACE WITH:
        "/insights":  "Show recent-activity summary (/insights [--days N], default 7) — AD-810",
        "/remind":    "One-shot reminder from natural language (/remind <when> <what>) — AD-812",
        "/schedule":  "Schedule from natural language (/schedule <NL> | list | cancel <id>) — AD-812",
```

```python
# SEARCH (in the dispatch table at ~line 254):
            "/insights":   lambda: commands_insights.cmd_insights(rt, con, arg),
# REPLACE WITH:
            "/insights":   lambda: commands_insights.cmd_insights(rt, con, arg),
            "/remind":     lambda: commands_schedule.cmd_remind(rt, con, arg),
            "/schedule":   lambda: commands_schedule.cmd_schedule(rt, con, arg),
```

If the actual indentation or surrounding lines differ from the verified context, follow the existing pattern — these three sites are the canonical AD-810 surface and AD-812 sits beside them.

### Section 3 — API router

New file `src/probos/routers/schedule_nl.py`:

```python
"""AD-812: POST /api/schedule/nl — natural-language scheduling endpoint."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from probos.cognitive.schedule_parser import parse_nl_schedule

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


class NLScheduleRequest(BaseModel):
    text: str


@router.post("/nl")
async def schedule_from_nl(req: NLScheduleRequest, request: Request) -> dict[str, Any]:
    runtime = request.app.state.runtime
    store = getattr(runtime, "persistent_task_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Persistent task store not available")
    spec = await parse_nl_schedule(
        req.text, llm_client=getattr(runtime, "llm_client", None)
    )
    if spec.kind == "error":
        raise HTTPException(status_code=400, detail=spec.reason)
    task = await store.create_task(
        intent_text=spec.intent_text,
        schedule_type=spec.kind,
        execute_at=spec.execute_at,
        interval_seconds=spec.interval_seconds,
        cron_expr=spec.cron_expr,
        channel_id=spec.channel_id,
        max_runs=spec.max_runs,
    )
    return store._task_to_dict(task)
```

Wire into `src/probos/api.py` (mirror the AD-810 router registration; grep `from probos.routers import insights` and add an analogous line + `app.include_router(schedule_nl.router)` next to it).

## Tests

New file `tests/test_ad812_schedule_parser.py`. Eight tests, all using a `_FakeLLM` stub returning the prompt-author-controlled JSON. No real network calls.

| # | Test | What it asserts |
|---|---|---|
| 1 | `test_regex_fast_path_in_minutes` | `"in 5 minutes pick up groceries"` → `kind="once"`, `execute_at≈now+300`, `intent_text="pick up groceries"`. No LLM called. |
| 2 | `test_regex_fast_path_in_hours` | `"in 2 hours check the agent fleet"` → `kind="once"`, `execute_at≈now+7200`. |
| 3 | `test_llm_once_tomorrow_9am` | LLM returns `{"kind":"once","execute_at_iso":"<+1 day 09:00>","intent_text":"send a status report","channel":null}`. Parser returns matching spec. |
| 4 | `test_llm_cron_weekly_monday` | LLM returns `{"kind":"cron","cron_expr":"0 9 * * 1","intent_text":"send weekly summary","channel":null}`. Parser validates via croniter and returns spec. |
| 5 | `test_llm_cron_with_channel_telegram` | LLM returns `{"kind":"cron","cron_expr":"0 7 * * 1-5","intent_text":"send my LinkedIn metrics","channel":"telegram"}`. Parser sets `channel_id="telegram:default"`. |
| 6 | `test_llm_unavailable_no_regex_match_errors_honestly` | `llm_client=None`, text doesn't match regex. Returns `kind="error"`, `reason` mentions LLM unavailable. **No exception raised.** |
| 7 | `test_llm_returns_non_json_errors_honestly` | LLM stub returns `"sure thing!"`. Parser returns `kind="error"`, `reason="LLM returned non-JSON output"`. |
| 8 | `test_llm_returns_invalid_cron_errors_honestly` | LLM stub returns `{"kind":"cron","cron_expr":"NOT VALID","intent_text":"x"}`. Parser returns `kind="error"`, reason mentions `invalid cron_expr`. |

Optional 9th test (recommended, not required): `test_past_execute_at_rejected` — LLM returns `execute_at_iso` 1 hour before `now`, parser returns `kind="error"` with `reason="execute_at is in the past"`.

```python
# tests/test_ad812_schedule_parser.py
import json
import time
from dataclasses import dataclass

import pytest

from probos.cognitive.schedule_parser import (
    ScheduleSpec,
    parse_nl_schedule,
)


@dataclass
class _FakeResponse:
    content: str = ""


class _FakeLLM:
    """Stub LLM client returning a pre-canned JSON string."""

    def __init__(self, output: str) -> None:
        self.output = output
        self.calls = 0

    async def complete(self, req):
        self.calls += 1
        return _FakeResponse(content=self.output)


@pytest.mark.asyncio
async def test_regex_fast_path_in_minutes():
    now = 1_700_000_000.0
    spec = await parse_nl_schedule(
        "in 5 minutes pick up groceries", llm_client=None, now=now
    )
    assert spec.kind == "once"
    assert spec.execute_at == pytest.approx(now + 300, abs=1)
    assert "pick up" in spec.intent_text
```

…and so on for the remaining seven (the file follows obvious AAA shape; the Builder writes them directly against the API in `schedule_parser.py`).

## What This Does NOT Change

- `src/probos/persistent_tasks.py` — untouched. AD-812 only consumes its public `create_task` / `list_tasks` / `cancel_task` / `_task_to_dict` API.
- `src/probos/cognitive/workflow_cron.py` — untouched. Different primitive (cached-workflow replay).
- `src/probos/routers/scheduled_tasks.py` — untouched. The existing `POST /api/scheduled-tasks` keeps its structured-input contract; AD-812's `/api/schedule/nl` is a sibling.
- The runtime startup sequence — no new background loop, no AD-825 drain registration needed. `PersistentTaskStore.start()` is already wired and AD-824/AD-825 already drain it.
- Channel adapters — untouched. We pass `channel_id="<adapter>:default"` and let the existing dispatcher route.

## Acceptance criteria

1. New file `src/probos/cognitive/schedule_parser.py` exists with `ScheduleSpec` and `parse_nl_schedule`.
2. New file `src/probos/experience/commands/commands_schedule.py` exists with `cmd_remind` and `cmd_schedule`.
3. New file `src/probos/routers/schedule_nl.py` exists; router included in `api.py`.
4. `shell.py` imports `commands_schedule`, lists `/remind` and `/schedule` in help, and dispatches both.
5. New tests in `tests/test_ad812_schedule_parser.py` — **all 8 pass** (9 with the optional past-execute test).
6. **Full regression green at the per-prompt gate:** `pytest tests/test_ad812_schedule_parser.py tests/test_ad810_insights.py tests/test_ad820_*.py tests/test_ad821_*.py tests/test_ad822_*.py tests/test_ad823_*.py tests/test_ad824_*.py tests/test_ad825_*.py tests/test_ad826_*.py tests/test_bf295_*.py -q -n 0` exits 0.
7. **Full parallel gate green:** `pytest tests/ -q -n 4 --dist=loadfile` exits 0.
8. No new runtime dependencies added to `pyproject.toml`.
9. Single commit titled `AD-812: NL-driven scheduled actions` with trailer `Closes #736`.
10. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Tracking

- `PROGRESS.md` — add CLOSED entry under the Era-5 section: `AD-812 — NL scheduled actions (/remind, /schedule). LLM parser + slash + API on existing PersistentTaskStore. 8 tests. Closes #736.`
- `docs/development/roadmap.md` — flip AD-812's "forward marker" status to "shipped".
- `DECISIONS.md` — append one paragraph: `AD-812: parse_nl_schedule consumes existing AD-418 PersistentTaskStore via fast-tier LLM. No new dependency, no new store, no new background loop. Channel binding is best-effort name-to-default-id only.`

## Verified Against Codebase (2026-05-23)

```
grep -n "AD-810" src/probos/experience/shell.py
  34: from probos.experience.commands import commands_insights  # AD-810
  115: "/insights":  "Show recent-activity summary (/insights [--days N], default 7) — AD-810",
  254: "/insights":   lambda: commands_insights.cmd_insights(rt, con, arg),

grep -n "class PersistentTaskStore" src/probos/persistent_tasks.py
  95: class PersistentTaskStore(EventEmitterMixin):

grep -n "async def create_task" src/probos/persistent_tasks.py
  176: async def create_task(

grep -n "_VALID_SCHEDULE_TYPES" src/probos/persistent_tasks.py
  88: _VALID_SCHEDULE_TYPES = {"once", "interval", "cron"}

grep -n "persistent_task_store" src/probos/runtime.py
  262: persistent_task_store: PersistentTaskStore | None
  710: self.persistent_task_store: PersistentTaskStore | None = None
  2081: self.persistent_task_store = comm.persistent_task_store

grep -n "croniter" pyproject.toml
  47: "croniter>=1.3",

grep -n "class LLMRequest" src/probos/types.py
  227: class LLMRequest:
  230:     prompt: str
  231:     system_prompt: str = ""
  232:     tier: str = "standard"
  235:     max_tokens: int = 2048

grep -n "self.llm_client" src/probos/runtime.py
  591: self.llm_client: BaseLLMClient = llm_client or MockLLMClient()
```

All concrete claims (file paths, class names, method signatures, schedule_type values, croniter dep, LLMRequest fields, runtime attribute names) verified against HEAD `510972da`.
