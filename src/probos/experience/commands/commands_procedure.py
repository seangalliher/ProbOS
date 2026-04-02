"""AD-536/537/538: Procedure promotion governance, observational learning, and lifecycle commands."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


async def cmd_procedure(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Procedure governance commands: list-pending, approve, reject, list-promoted, teach, observed, stale, archived, restore, duplicates, merge."""
    parts = args.split(maxsplit=2) if args else []
    sub = parts[0].lower() if parts else ""

    if sub == "list-pending":
        dept = None
        if len(parts) > 2 and parts[1] == "--department":
            dept = parts[2]
        elif len(parts) > 1:
            dept = parts[1]
        await _list_pending(runtime, console, dept)
    elif sub == "approve":
        if len(parts) < 2:
            console.print("[yellow]Usage: /procedure approve <procedure_id> [--message <msg>][/yellow]")
            return
        proc_id = parts[1]
        msg = ""
        if len(parts) > 2:
            remainder = args.split(maxsplit=2)[2] if len(args.split(maxsplit=2)) > 2 else ""
            if remainder.startswith("--message "):
                msg = remainder[len("--message "):]
        await _approve_procedure(runtime, console, proc_id, msg)
    elif sub == "reject":
        if len(parts) < 2:
            console.print("[yellow]Usage: /procedure reject <procedure_id> --reason <reason>[/yellow]")
            return
        proc_id = parts[1]
        reason = ""
        remainder = args.split(maxsplit=2)[2] if len(args.split(maxsplit=2)) > 2 else ""
        if remainder.startswith("--reason "):
            reason = remainder[len("--reason "):]
        if not reason:
            console.print("[yellow]Rejection requires --reason. Usage: /procedure reject <id> --reason <text>[/yellow]")
            return
        await _reject_procedure(runtime, console, proc_id, reason)
    elif sub == "list-promoted":
        await _list_promoted(runtime, console)
    elif sub == "teach":
        if len(parts) < 3:
            console.print("[yellow]Usage: /procedure teach <procedure_id> <target_callsign>[/yellow]")
            return
        # Re-split to get procedure_id and target callsign
        teach_parts = args.split()
        proc_id = teach_parts[1]
        target = teach_parts[2]
        await _teach_procedure(runtime, console, proc_id, target)
    elif sub == "observed":
        agent_filter = None
        if len(parts) > 2 and parts[1] == "--agent":
            agent_filter = parts[2]
        elif len(parts) > 1 and parts[1] != "--agent":
            agent_filter = parts[1]
        await _list_observed(runtime, console, agent_filter)
    elif sub == "stale":
        days = None
        if len(parts) > 2 and parts[1] == "--days":
            try:
                days = int(parts[2])
            except ValueError:
                console.print("[yellow]--days must be a number[/yellow]")
                return
        await _list_stale(runtime, console, days)
    elif sub == "archived":
        count = 20
        if len(parts) > 2 and parts[1] == "--count":
            try:
                count = int(parts[2])
            except ValueError:
                pass
        await _list_archived(runtime, console, count)
    elif sub == "restore":
        if len(parts) < 2:
            console.print("[yellow]Usage: /procedure restore <procedure_id>[/yellow]")
            return
        await _restore_procedure(runtime, console, parts[1])
    elif sub == "duplicates":
        await _list_duplicates(runtime, console)
    elif sub == "merge":
        merge_parts = args.split()
        if len(merge_parts) < 3:
            console.print("[yellow]Usage: /procedure merge <primary_id> <duplicate_id>[/yellow]")
            return
        await _merge_procedures(runtime, console, merge_parts[1], merge_parts[2])
    else:
        console.print(
            "[bold]Procedure governance commands:[/bold]\n"
            "  /procedure list-pending [--department <dept>]  Show pending promotions\n"
            "  /procedure approve <id> [--message <msg>]      Approve a promotion\n"
            "  /procedure reject <id> --reason <text>         Reject with feedback\n"
            "  /procedure list-promoted                       Show promoted procedures\n"
            "  /procedure teach <id> <target_callsign>        Teach Level 5 procedure\n"
            "  /procedure observed [--agent <callsign>]       Show observed/taught procedures\n"
            "  /procedure stale [--days <N>]                  Show stale procedures\n"
            "  /procedure archived [--count <N>]              Show archived procedures\n"
            "  /procedure restore <id>                        Restore an archived procedure\n"
            "  /procedure duplicates                          Show duplicate candidates\n"
            "  /procedure merge <primary_id> <duplicate_id>   Merge duplicate into primary"
        )


async def _list_pending(
    runtime: ProbOSRuntime, console: Console, department: str | None
) -> None:
    """Show pending promotion requests."""
    store = runtime.procedure_store
    if not store:
        console.print("[red]ProcedureStore not available[/red]")
        return

    pending = await store.get_pending_promotions(department=department)
    if not pending:
        console.print("[dim]No pending promotion requests[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="cyan", no_wrap=True, max_width=10)
    table.add_column("Name", style="")
    table.add_column("Level", justify="center")
    table.add_column("Completions", justify="right")
    table.add_column("Effective", justify="right")
    table.add_column("Criticality", style="")
    table.add_column("Requested", style="dim")

    for p in pending:
        crit = p["criticality"]
        crit_style = {"low": "green", "medium": "yellow", "high": "red", "critical": "bold red"}.get(crit, "")
        table.add_row(
            p["procedure_id"][:8],
            p.get("name", ""),
            str(p["compilation_level"]),
            str(p["total_completions"]),
            f"{p['effective_rate']:.0%}",
            f"[{crit_style}]{crit}[/{crit_style}]",
            p.get("requested_at", "")[:10],
        )

    console.print(table)


async def _approve_procedure(
    runtime: ProbOSRuntime, console: Console, proc_id: str, message: str
) -> None:
    """Approve a procedure promotion — create directive and update store."""
    store = runtime.procedure_store
    if not store:
        console.print("[red]ProcedureStore not available[/red]")
        return

    # Verify procedure exists and is pending
    status = await store.get_promotion_status(proc_id)
    if status != "pending":
        # Try partial ID match
        pending = await store.get_pending_promotions()
        matches = [p for p in pending if p["procedure_id"].startswith(proc_id)]
        if len(matches) == 1:
            proc_id = matches[0]["procedure_id"]
        elif len(matches) > 1:
            console.print(f"[yellow]Ambiguous ID '{proc_id}' matches {len(matches)} procedures. Use full ID.[/yellow]")
            return
        else:
            console.print(f"[red]Procedure {proc_id} is not pending promotion (status: {status})[/red]")
            return

    procedure = await store.get(proc_id)
    if not procedure:
        console.print(f"[red]Procedure {proc_id} not found[/red]")
        return

    # Create RuntimeDirective
    directive_store = runtime.directive_store
    if not directive_store:
        console.print("[red]DirectiveStore not available[/red]")
        return

    from probos.crew_profile import Rank
    from probos.directive_store import DirectiveType

    quality = await store.get_quality_metrics(proc_id)
    effective_rate = quality.get("effective_rate", 0) if quality else 0
    total_comp = quality.get("total_completions", 0) if quality else 0
    steps_text = "\n".join(
        f"  {s.step_number}. {s.action}" for s in procedure.steps
    )

    content = (
        f"When handling {', '.join(procedure.intent_types) or 'related tasks'}, "
        f"follow these steps:\n{steps_text}\n"
        f"This procedure was validated through {total_comp} completions "
        f"with {effective_rate:.0%} success rate. "
        f"Origin: {', '.join(procedure.origin_agent_ids) or 'system'}."
    )

    # Use CAPTAIN_ORDER for promoted procedures — Captain/chief issuing ship-wide directive
    agent_type = procedure.origin_agent_ids[0] if procedure.origin_agent_ids else "*"
    department = None
    if runtime.ontology:
        department = runtime.ontology.get_agent_department(agent_type)

    directive, reason = directive_store.create_directive(
        issuer_type="captain",
        issuer_department=None,
        issuer_rank=Rank.SENIOR,
        target_agent_type=agent_type,
        target_department=department,
        directive_type=DirectiveType.CAPTAIN_ORDER,
        content=content,
        authority=1.0,
        priority=3,
    )

    if not directive:
        console.print(f"[red]Failed to create directive: {reason}[/red]")
        return

    # Update procedure store
    await store.approve_promotion(proc_id, "captain", directive.id)

    console.print(f"\n[bold green]Procedure Promotion Approved[/bold green]")
    console.print(f"  [green]Procedure:[/green] {procedure.name}")
    console.print(f"  [green]ID:[/green]        {proc_id[:8]}")
    console.print(f"  [green]Directive:[/green] {directive.id[:8]}")
    console.print(f"  [green]Target:[/green]    {agent_type}" + (f" ({department})" if department else ""))
    if message:
        console.print(f"  [green]Note:[/green]      {message}")
    console.print(f"  [dim]Procedure promoted to institutional knowledge[/dim]\n")

    # Ward Room announcement
    await _announce_approval(runtime, procedure, directive.id)


async def _reject_procedure(
    runtime: ProbOSRuntime, console: Console, proc_id: str, reason: str
) -> None:
    """Reject a procedure promotion with feedback."""
    store = runtime.procedure_store
    if not store:
        console.print("[red]ProcedureStore not available[/red]")
        return

    # Verify procedure exists and is pending
    status = await store.get_promotion_status(proc_id)
    if status != "pending":
        # Try partial ID match
        pending = await store.get_pending_promotions()
        matches = [p for p in pending if p["procedure_id"].startswith(proc_id)]
        if len(matches) == 1:
            proc_id = matches[0]["procedure_id"]
        elif len(matches) > 1:
            console.print(f"[yellow]Ambiguous ID '{proc_id}' matches {len(matches)} procedures. Use full ID.[/yellow]")
            return
        else:
            console.print(f"[red]Procedure {proc_id} is not pending promotion (status: {status})[/red]")
            return

    procedure = await store.get(proc_id)
    proc_name = procedure.name if procedure else proc_id[:8]

    await store.reject_promotion(proc_id, "captain", reason)

    console.print(f"\n[bold yellow]Procedure Promotion Rejected[/bold yellow]")
    console.print(f"  [yellow]Procedure:[/yellow] {proc_name}")
    console.print(f"  [yellow]ID:[/yellow]        {proc_id[:8]}")
    console.print(f"  [yellow]Reason:[/yellow]    {reason}")
    console.print(f"  [dim]Rejection recorded. 72h cooldown before re-request.[/dim]\n")

    # DM rejection to originating agent (private feedback)
    await _announce_rejection(runtime, proc_id, proc_name, reason)


async def _list_promoted(runtime: ProbOSRuntime, console: Console) -> None:
    """Show all promoted (approved) procedures."""
    store = runtime.procedure_store
    if not store:
        console.print("[red]ProcedureStore not available[/red]")
        return

    promoted = await store.get_promoted_procedures()
    if not promoted:
        console.print("[dim]No promoted procedures[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="cyan", no_wrap=True, max_width=10)
    table.add_column("Name", style="")
    table.add_column("Level", justify="center")
    table.add_column("Completions", justify="right")
    table.add_column("Effective", justify="right")
    table.add_column("Approved By", style="")
    table.add_column("Directive", style="dim", max_width=10)

    for p in promoted:
        table.add_row(
            p["procedure_id"][:8],
            p.get("name", ""),
            str(p["compilation_level"]),
            str(p["total_completions"]),
            f"{p['effective_rate']:.0%}",
            p.get("decided_by", ""),
            (p.get("directive_id") or "")[:8],
        )

    console.print(table)


async def _announce_approval(
    runtime: ProbOSRuntime, procedure: object, directive_id: str
) -> None:
    """Post approval to Ward Room."""
    if not hasattr(runtime, "ward_room") or not runtime.ward_room:
        return
    try:
        channels = await runtime.ward_room.list_channels()
        target = None
        for ch in channels:
            if ch.name == "All Hands":
                target = ch
                break
        if target:
            await runtime.ward_room.create_thread(
                channel_id=target.id,
                author_id="captain",
                title=f"[Promotion Approved] {getattr(procedure, 'name', 'Unknown')}",
                body=f"Procedure '{getattr(procedure, 'name', 'Unknown')}' has been approved for "
                     f"institutional promotion. Directive: {directive_id[:8]}.",
                author_callsign="captain",
            )
    except Exception:
        logger.debug("AD-536: Approval announcement failed", exc_info=True)


async def _announce_rejection(
    runtime: ProbOSRuntime, proc_id: str, proc_name: str, reason: str
) -> None:
    """DM rejection to originating agent (private feedback)."""
    if not hasattr(runtime, "ward_room") or not runtime.ward_room:
        return
    try:
        # Get the originating agent from the procedure
        store = runtime.procedure_store
        if not store:
            return
        procedure = await store.get(proc_id)
        if not procedure or not procedure.origin_agent_ids:
            return

        agent_id = procedure.origin_agent_ids[0]
        dm_channel = await runtime.ward_room.get_or_create_dm_channel(
            "captain", agent_id,
            callsign_a="captain", callsign_b=agent_id,
        )
        await runtime.ward_room.create_thread(
            channel_id=dm_channel.id,
            author_id="captain",
            title=f"Promotion Rejected: {proc_name}",
            body=f"Your procedure '{proc_name}' ({proc_id[:8]}) was not approved for promotion.\n\n"
                 f"**Reason:** {reason}\n\n"
                 f"The procedure remains private. You may re-request promotion after 72 hours "
                 f"if material improvements are made.",
            author_callsign="captain",
        )
    except Exception:
        logger.debug("AD-536: Rejection DM failed", exc_info=True)


async def _teach_procedure(
    runtime: ProbOSRuntime, console: Console, proc_id: str, target: str
) -> None:
    """AD-537: Teach a procedure to another agent."""
    store = runtime.procedure_store
    if not store:
        console.print("[red]ProcedureStore not available[/red]")
        return

    from probos.config import TEACHING_MIN_COMPILATION_LEVEL

    # Resolve partial ID
    procedure = await store.get(proc_id)
    if not procedure:
        # Try partial match
        try:
            active = await store.list_active()
            matches = [p for p in active if p["id"].startswith(proc_id)]
            if len(matches) == 1:
                proc_id = matches[0]["id"]
                procedure = await store.get(proc_id)
            elif len(matches) > 1:
                console.print(f"[yellow]Ambiguous ID '{proc_id}' matches {len(matches)} procedures.[/yellow]")
                return
        except Exception:
            pass
        if not procedure:
            console.print(f"[red]Procedure {proc_id} not found[/red]")
            return

    # Validate Level 5
    if procedure.compilation_level < TEACHING_MIN_COMPILATION_LEVEL:
        console.print(
            f"[red]Procedure must be Level {TEACHING_MIN_COMPILATION_LEVEL}+ to teach "
            f"(current: Level {procedure.compilation_level})[/red]"
        )
        return

    # Validate approved
    status = await store.get_promotion_status(proc_id)
    if status != "approved":
        console.print(f"[red]Procedure must be institutionally approved to teach (status: {status})[/red]")
        return

    # Send teaching DM via Ward Room
    if not hasattr(runtime, "ward_room") or not runtime.ward_room:
        console.print("[red]Ward Room not available[/red]")
        return

    quality = await store.get_quality_metrics(proc_id)
    total_comp = quality.get("total_completions", 0) if quality else 0
    effective_rate = quality.get("effective_rate", 0) if quality else 0
    steps_text = "\n".join(f"  {s.step_number}. {s.action}" for s in procedure.steps)

    body = (
        f"**[TEACHING] Procedure: {procedure.name}**\n\n"
        f"This procedure has been validated through {total_comp} executions "
        f"with {effective_rate:.0%} success rate.\n\n"
        f"**Description:** {procedure.description}\n\n"
        f"**Steps:**\n{steps_text}\n\n"
        f"This procedure has been institutionally approved and promoted to Expert level."
    )

    try:
        dm_channel = await runtime.ward_room.get_or_create_dm_channel(
            "captain", target,
            callsign_a="captain", callsign_b=target,
        )
        await runtime.ward_room.create_thread(
            channel_id=dm_channel.id,
            author_id="captain",
            title=f"[TEACHING] {procedure.name}",
            body=body,
            author_callsign="captain",
        )
        console.print(f"\n[bold green]Teaching Sent[/bold green]")
        console.print(f"  [green]Procedure:[/green] {procedure.name}")
        console.print(f"  [green]Target:[/green]    {target}")
        console.print(f"  [dim]The target agent will learn this in their next dream cycle.[/dim]\n")
    except Exception as e:
        console.print(f"[red]Teaching failed: {e}[/red]")


async def _list_observed(
    runtime: ProbOSRuntime, console: Console, agent_filter: str | None
) -> None:
    """AD-537: List observed/taught procedures."""
    store = runtime.procedure_store
    if not store:
        console.print("[red]ProcedureStore not available[/red]")
        return

    observed = await store.get_observed_procedures(agent=agent_filter)
    if not observed:
        console.print("[dim]No observed or taught procedures[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="cyan", no_wrap=True, max_width=10)
    table.add_column("Name", style="")
    table.add_column("Via", style="")
    table.add_column("From", style="")
    table.add_column("Level", justify="center")
    table.add_column("Completions", justify="right")
    table.add_column("Effective", justify="right")

    for p in observed:
        via = p.get("learned_via", "direct")
        via_style = "green" if via == "taught" else "cyan"
        table.add_row(
            p["procedure_id"][:8],
            p.get("name", ""),
            f"[{via_style}]{via}[/{via_style}]",
            p.get("learned_from", ""),
            str(p.get("compilation_level", 0)),
            str(p.get("total_completions", 0)),
            f"{p.get('effective_rate', 0):.0%}",
        )

    console.print(table)


# ------------------------------------------------------------------
# AD-538: Lifecycle commands
# ------------------------------------------------------------------


async def _list_stale(
    runtime: ProbOSRuntime, console: Console, days: int | None
) -> None:
    """AD-538: List stale procedures that would be decayed."""
    store = runtime.procedure_store
    if not store:
        console.print("[red]ProcedureStore not available[/red]")
        return

    stale = await store.get_stale_procedures(days=days)
    if not stale:
        console.print("[dim]No stale procedures[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="cyan", no_wrap=True, max_width=10)
    table.add_column("Name", style="")
    table.add_column("Level", justify="center")
    table.add_column("Days Unused", justify="right")
    table.add_column("Completions", justify="right")

    for p in stale:
        table.add_row(
            p["id"][:8],
            p.get("name", ""),
            str(p["compilation_level"]),
            str(p["days_unused"]),
            str(p["total_completions"]),
        )

    console.print(table)
    console.print(f"[dim]{len(stale)} stale procedure(s) — decay runs automatically during dream cycles[/dim]")


async def _list_archived(
    runtime: ProbOSRuntime, console: Console, count: int
) -> None:
    """AD-538: List archived procedures."""
    store = runtime.procedure_store
    if not store:
        console.print("[red]ProcedureStore not available[/red]")
        return

    archived = await store.get_archived_procedures(limit=count)
    if not archived:
        console.print("[dim]No archived procedures[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="cyan", no_wrap=True, max_width=10)
    table.add_column("Name", style="")
    table.add_column("Completions", justify="right")
    table.add_column("Archived", style="dim")

    for p in archived:
        import datetime
        archived_ts = p.get("archived_at", 0)
        archived_str = datetime.datetime.fromtimestamp(archived_ts).strftime("%Y-%m-%d") if archived_ts else ""
        table.add_row(
            p["id"][:8],
            p.get("name", ""),
            str(p.get("total_completions", 0)),
            archived_str,
        )

    console.print(table)
    console.print(f"[dim]Use '/procedure restore <id>' to restore an archived procedure[/dim]")


async def _restore_procedure(
    runtime: ProbOSRuntime, console: Console, proc_id: str
) -> None:
    """AD-538: Restore an archived procedure."""
    store = runtime.procedure_store
    if not store:
        console.print("[red]ProcedureStore not available[/red]")
        return

    success = await store.restore_procedure(proc_id)
    if success:
        proc = await store.get(proc_id)
        name = proc.name if proc else proc_id[:8]
        console.print(f"[green]Restored procedure '{name}' to Level 1 (active)[/green]")
    else:
        console.print(f"[red]Could not restore procedure {proc_id} (not found or not archived)[/red]")


async def _list_duplicates(runtime: ProbOSRuntime, console: Console) -> None:
    """AD-538: List duplicate procedure candidates."""
    store = runtime.procedure_store
    if not store:
        console.print("[red]ProcedureStore not available[/red]")
        return

    candidates = await store.find_duplicate_candidates()
    if not candidates:
        console.print("[dim]No duplicate candidates found[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Primary", style="cyan", max_width=10)
    table.add_column("Primary Name", style="")
    table.add_column("Duplicate", style="yellow", max_width=10)
    table.add_column("Duplicate Name", style="")
    table.add_column("Similarity", justify="right")

    for c in candidates:
        table.add_row(
            c["primary_id"][:8],
            c["primary_name"],
            c["duplicate_id"][:8],
            c["duplicate_name"],
            f"{c['similarity']:.1%}",
        )

    console.print(table)
    console.print(f"[dim]Use '/procedure merge <primary_id> <duplicate_id>' to merge[/dim]")


async def _merge_procedures(
    runtime: ProbOSRuntime, console: Console, primary_id: str, duplicate_id: str
) -> None:
    """AD-538: Merge duplicate into primary."""
    store = runtime.procedure_store
    if not store:
        console.print("[red]ProcedureStore not available[/red]")
        return

    primary = await store.get(primary_id)
    duplicate = await store.get(duplicate_id)
    if not primary:
        console.print(f"[red]Primary procedure {primary_id} not found[/red]")
        return
    if not duplicate:
        console.print(f"[red]Duplicate procedure {duplicate_id} not found[/red]")
        return

    success = await store.merge_procedures(primary_id, duplicate_id)
    if success:
        metrics = await store.get_quality_metrics(primary_id)
        total = metrics.get("total_completions", 0) if metrics else 0
        console.print(
            f"[green]Merged '{duplicate.name}' into '{primary.name}'. "
            f"Combined stats: {total} completions.[/green]"
        )
    else:
        console.print(f"[red]Merge failed — ensure both procedures are active[/red]")
