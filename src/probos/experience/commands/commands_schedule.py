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
