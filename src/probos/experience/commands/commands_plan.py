"""Plan, approve, reject, feedback, and correct commands for ProbOSShell."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from rich.console import Console

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


async def cmd_plan(runtime: ProbOSRuntime, console: Console, renderer: Any, args: str) -> None:
    """Handle /plan command: propose, re-display, or remove nodes."""
    from probos.cognitive.decomposer import is_capability_gap
    from probos.experience.panels import render_dag_proposal

    # /plan remove N
    if args.startswith("remove "):
        remainder = args[len("remove "):].strip()
        if not remainder:
            console.print("[yellow]Usage: /plan remove <N>[/yellow]")
            return
        if runtime._pending_proposal is None:
            console.print("[yellow]No pending proposal.[/yellow]")
            return
        try:
            idx = int(remainder)
        except ValueError:
            console.print(
                "[red]Invalid node index. Use /plan to see current proposal.[/red]"
            )
            return
        removed = await runtime.remove_proposal_node(idx)
        if removed is None:
            console.print(
                "[red]Invalid node index. Use /plan to see current proposal.[/red]"
            )
            return
        console.print(f"[dim]Removed step {idx}: {removed.intent}[/dim]")
        # Re-display updated proposal
        dag = runtime._pending_proposal
        if dag and dag.nodes:
            console.print(render_dag_proposal(dag))
        else:
            console.print("[dim]Proposal is now empty.[/dim]")
        return

    # /plan (no args) — re-display pending proposal
    if not args:
        if runtime._pending_proposal is not None and runtime._pending_proposal.nodes:
            console.print(render_dag_proposal(runtime._pending_proposal))
        elif runtime._pending_proposal is not None:
            console.print("[dim]Pending proposal is empty (all steps removed).[/dim]")
        else:
            console.print("[yellow]Usage: /plan <text> to propose a plan[/yellow]")
        return

    # /plan <text> — propose a new plan
    console.print(f"\n[bold]> /plan {args}[/bold]")
    with console.status(
        "[bold blue]Decomposing intent...[/bold blue]",
        spinner="dots",
    ):
        dag = await runtime.propose(args)

    if not dag.nodes:
        is_gap = dag.capability_gap or (dag.response and is_capability_gap(dag.response))
        if dag.response and not is_gap:
            console.print(f"[cyan]{dag.response}[/cyan]")
            return

        # Capability gap — trigger self-mod flow same as normal NL
        if dag.response:
            console.print(f"[dim]{dag.response}[/dim]")

        if runtime.self_mod_pipeline:
            with console.status(
                "[bold yellow]Analyzing unhandled request...[/bold yellow]",
                spinner="dots",
            ):
                intent_meta = await runtime._extract_unhandled_intent(args)
            if intent_meta:
                console.print(
                    f"[yellow]Capability gap detected: {intent_meta['name']}[/yellow]"
                )
        else:
            console.print("[yellow]No actionable intents recognized.[/yellow]")
        return

    # Display proposed plan
    console.print(render_dag_proposal(dag))
    console.print(
        "[dim]Use /approve to execute, /reject to discard, "
        "or /plan remove N to remove a step[/dim]"
    )


async def cmd_approve(runtime: ProbOSRuntime, console: Console, renderer: Any, args: str) -> None:
    """Execute the pending proposal."""
    if runtime._pending_proposal is None:
        console.print(
            "[yellow]No pending proposal. Use /plan <text> to create one.[/yellow]"
        )
        return

    if not runtime._pending_proposal.nodes:
        console.print("[yellow]Proposal is empty — nothing to execute.[/yellow]")
        await runtime.reject_proposal()
        return

    dag = runtime._pending_proposal
    node_count = len(dag.nodes)
    console.print(f"[bold]Executing {node_count} task(s)...[/bold]")

    # Execute through the renderer's event tracking
    renderer._current_dag = dag
    renderer._node_statuses = {n.id: "pending" for n in dag.nodes}

    renderer._status = console.status(
        f"[bold blue]Executing {node_count} task(s)...[/bold blue]",
        spinner="dots",
    )
    renderer._status.start()
    try:
        execution_result = await runtime.execute_proposal(
            on_event=renderer._on_execution_event,
        )
    finally:
        if renderer._status is not None:
            renderer._status.stop()
            renderer._status = None

    if execution_result is None:
        console.print("[yellow]No pending proposal.[/yellow]")
        return

    # Print progress table
    console.print(renderer._build_progress_table())

    # Force reflect for intents whose descriptors say requires_reflect
    if not dag.reflect and dag.nodes:
        reflect_intents: set[str] = set()
        for desc in runtime._collect_intent_descriptors():
            if desc.requires_reflect:
                reflect_intents.add(desc.name)
        if runtime.self_mod_pipeline:
            for r in runtime.self_mod_pipeline._records:
                if r.status == "active":
                    reflect_intents.add(r.intent_name)
        if any(n.intent in reflect_intents for n in dag.nodes):
            dag.reflect = True

    # Reflect if needed (already done in _execute_dag for the runtime path)
    # But we need to check if it wasn't done there
    if "reflection" not in execution_result and dag.reflect and dag.nodes:
        with console.status(
            "[bold blue]Reflecting on results...[/bold blue]",
            spinner="dots",
        ):
            try:
                reflect_timeout = runtime.config.cognitive.decomposition_timeout_seconds
                reflection = await asyncio.wait_for(
                    runtime.decomposer.reflect(
                        execution_result.get("input", ""),
                        execution_result,
                    ),
                    timeout=reflect_timeout,
                )
                execution_result["reflection"] = reflection
            except Exception:
                execution_result["reflection"] = (
                    "(Reflection unavailable -- results shown above)"
                )

    # Show results
    from probos.experience.panels import render_dag_result
    console.print(render_dag_result(execution_result, debug=renderer.debug))

    # Store execution result for introspection
    runtime._last_execution = execution_result


async def cmd_reject(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Discard the pending proposal."""
    if await runtime.reject_proposal():
        console.print("[dim]Proposal discarded. Feedback recorded for future planning.[/dim]")
    else:
        console.print("[yellow]No pending proposal.[/yellow]")


async def cmd_feedback(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Rate the last execution: /feedback good|bad."""
    args = args.strip().lower()
    if args not in ("good", "bad"):
        console.print(
            "[dim]Usage: /feedback good|bad — rate the last execution[/dim]"
        )
        return

    if not hasattr(runtime, '_last_execution') or runtime._last_execution is None:
        console.print("[yellow]No recent execution to rate.[/yellow]")
        return

    if getattr(runtime, '_last_feedback_applied', False):
        console.print("[yellow]Feedback already recorded for this execution.[/yellow]")
        return

    positive = args == "good"
    result = await runtime.record_feedback(positive)
    if result is None:
        console.print("[yellow]Could not record feedback.[/yellow]")
        return

    label = "positive" if positive else "negative"
    agents = result.agents_updated
    if agents:
        console.print(
            f"[dim]Feedback ({label}) applied to {len(agents)} agent(s). "
            f"Trust and routing weights updated.[/dim]"
        )
    else:
        console.print(f"[dim]Feedback ({label}) recorded.[/dim]")


async def cmd_correct(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Explicit correction command: /correct <what to fix>."""
    if not args:
        console.print(
            "[dim]Usage: /correct <what to fix> — correct the last execution's behavior[/dim]"
        )
        return

    if runtime._last_execution is None:
        console.print("[yellow]No recent execution to correct.[/yellow]")
        return

    if not runtime._correction_detector:
        console.print("[yellow]Correction detection is not enabled.[/yellow]")
        return

    # Detect correction signal
    correction = await runtime._correction_detector.detect(
        user_text=args,
        last_execution_text=runtime._last_execution_text,
        last_execution_dag=runtime._last_execution,
        last_execution_success=runtime.self_mod_manager.was_last_execution_successful() if runtime.self_mod_manager else False,
    )

    if correction is None:
        console.print(
            "[yellow]Could not interpret correction. "
            "Try being more specific about what to change.[/yellow]"
        )
        return

    # Find designed agent record
    record = runtime.self_mod_manager.find_designed_record(correction.target_agent_type) if runtime.self_mod_manager else None
    if record is None:
        console.print(
            f"[yellow]No designed agent found for '{correction.target_agent_type}'. "
            f"Only self-designed agents can be corrected.[/yellow]"
        )
        return

    if not runtime._agent_patcher:
        console.print("[yellow]Agent patching is not enabled.[/yellow]")
        return

    # Patch the agent
    console.print("[dim]Generating patched agent...[/dim]")
    patch_result = await runtime._agent_patcher.patch(
        record, correction, runtime._last_execution_text or args,
    )

    if not patch_result.success:
        console.print(
            f"[red]Correction failed: patched code did not pass validation[/red]"
        )
        if patch_result.error:
            console.print(f"  [red]Error: {patch_result.error}[/red]")
        console.print(
            "  [dim]You can try /feedback bad to mark this execution as negative.[/dim]"
        )
        return

    # Apply correction (hot-reload + retry)
    if runtime.self_mod_manager:
        runtime.self_mod_manager._last_execution = runtime._last_execution
        runtime.self_mod_manager._last_execution_text = runtime._last_execution_text
        result = await runtime.self_mod_manager.apply_correction(
            correction, patch_result, record,
        )
    else:
        console.print("[yellow]SelfModManager not initialized.[/yellow]")
        return

    if result.success:
        console.print(
            f"[green]Correction applied to {result.agent_type} agent[/green]"
        )
        if result.changes_description:
            console.print(f"  [dim]Changed: {result.changes_description}[/dim]")
        if result.retried:
            if result.retry_result and result.retry_result.get("success"):
                total = result.retry_result.get("total", 0)
                ok = result.retry_result.get("completed", 0)
                console.print(
                    f"  [dim]Retrying original request...[/dim]"
                )
                console.print(
                    f"  [green]Retry successful — {ok}/{total} tasks completed[/green]"
                )
            else:
                console.print(
                    "  [yellow]Retry did not fully succeed.[/yellow]"
                )
    else:
        console.print(
            f"[red]Correction could not be applied to {result.agent_type}[/red]"
        )
        console.print(
            "  [dim]You can try /feedback bad to mark this execution as negative.[/dim]"
        )
