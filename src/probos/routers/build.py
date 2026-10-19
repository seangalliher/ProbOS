"""ProbOS API — Build routes (AD-304, AD-345, AD-375)."""

from __future__ import annotations

import dataclasses
import logging
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends

from probos.api_models import (
    BuildApproveRequest, BuildEnqueueRequest, BuildQueueApproveRequest,
    BuildQueueRejectRequest, BuildRequest, BuildResolveRequest,
)
from probos.cognitive.builder_paths import operator_checkout_refusal
from probos.events import EventType
from probos.routers.deps import get_runtime, get_task_tracker

logger = logging.getLogger(__name__)

# Import shared failure cache from api module
from probos.api import _pending_failures, _clean_expired_failures, _FAILURE_CACHE_TTL

router = APIRouter(prefix="/api/build", tags=["build"])

# BF-897 (#1559): the checkout this runtime runs from (src/probos/routers -> repository).
_REPO_ROOT = Path(__file__).resolve().parents[3]
APPROVE_REFUSED = (
    "/api/build/approve no longer runs a build (BF-897). "
    "Queue the build instead (/api/build/enqueue): it runs in its own worktree, "
    "and its branch is kept for delivery."
)
#: BF-904a (#1585): the first line of a commit_override build's commit body.
OVERRIDE_MARKER = "[Test gate overridden by Captain]"
#: BF-904a A3 (D29): abort's message after an incomplete cleanup. Fixed text, no cleanup content.
ABORT_CLEANUP_INCOMPLETE = (
    "Build aborted. Its cleanup was incomplete when it failed, so the checkout may not be as the "
    "build found it: check it against the cleanup notes in the failure report."
)
#: BF-904a A3 (D30): why a resolution that runs a build is refused after an incomplete cleanup.
RESOLVE_CLEANUP_INCOMPLETE = (
    "Not run: the failed build's cleanup was incomplete, so its checkout is not known to be as the "
    "build found it and may hold the git configuration its tests left. Check the checkout against "
    "the cleanup notes in the failure report, then abort and start a new build."
)


@router.post("/submit")
async def submit_build(
    req: BuildRequest,
    runtime: Any = Depends(get_runtime),
    track_task: Callable = Depends(get_task_tracker),
) -> dict[str, Any]:
    """Start async build generation. Progress via WebSocket events."""
    import uuid
    build_id = uuid.uuid4().hex[:12]
    track_task(_run_build(req, build_id, runtime), name=f"build-{build_id}")
    return {
        "status": "started",
        "build_id": build_id,
        "message": f"Build '{req.title}' started...",
    }


@router.post("/approve")
async def approve_build(
    req: BuildApproveRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Refuse: this route never executes an approved build (BF-897).

    This used to run ``execute_approved_build`` with ``work_dir`` set to the
    repository root, so the build created a branch, wrote files, ran pytest and
    committed in the operator's own checkout. Nothing here owns a worktree's
    lifecycle; AD-1336 child 5 (the build lane) replaces this refusal with a run in
    a governed worktree. The response keeps its keys; the HXI shows the reason from
    the ``build_failure`` event (``useStore.ts``, the branch without a report).
    The event carries ``not_executed`` so the Night Orders hook does not escalate a
    refusal, and a failing listener cannot turn the refusal into an error.
    """
    logger.warning("build approve refused build_id=%s: %s", req.build_id, APPROVE_REFUSED)
    try:
        runtime.emit_event(EventType.BUILD_FAILURE, {
            "build_id": req.build_id,
            "message": f"Build not executed: {APPROVE_REFUSED}",
            "error": APPROVE_REFUSED,
            "not_executed": True,
        })
    except Exception:
        # The refusal has already taken effect and nothing was scheduled: a failing
        # listener degrades the notice, never the answer.
        logger.warning("build approve refusal notice failed build_id=%s", req.build_id, exc_info=True)
    return {"status": "error", "build_id": req.build_id, "message": APPROVE_REFUSED}


@router.post("/resolve")
async def resolve_build(
    req: BuildResolveRequest,
    runtime: Any = Depends(get_runtime),
    track_task: Callable = Depends(get_task_tracker),
) -> dict[str, Any]:
    """Execute a resolution option for a failed build (AD-345)."""
    _clean_expired_failures()

    if req.build_id not in _pending_failures:
        return {"status": "error", "message": "Build not found or expired. Re-run the build."}

    cached = _pending_failures[req.build_id]
    file_changes = cached["file_changes"]
    spec = cached["spec"]
    work_dir = cached["work_dir"]

    # BF-897: commit_override and a retry execute in work_dir (BF-904a: abort runs no
    # git); the guard refuses the checkout ProbOS runs from (it compares locations,
    # see operator_checkout_refusal).
    checkout_refusal = operator_checkout_refusal(work_dir, _REPO_ROOT)
    if checkout_refusal is not None:
        del _pending_failures[req.build_id]
        return {"status": "error", "message": checkout_refusal}

    # BF-904a A3 (D30): every resolution but abort runs a build in this checkout; after an incomplete
    # cleanup its state and git configuration are unknown, so only abort (no git) is taken. The
    # failure stays cached so abort remains available.
    if req.resolution in ("commit_override", "retry_extended", "retry_targeted", "retry_fix", "retry_full") and cached["report"].cleanup_errors:  # BF-904a A3 (D30)
        return {"status": "error", "message": RESOLVE_CLEANUP_INCOMPLETE}

    if req.resolution == "abort":
        # BF-904a (#1585): runs no git. The failed build already wrote its files back, deleted
        # the ones it created and returned to the ref it started from (execute_approved_build),
        # unless its report lists cleanup errors; then the message says so (A3, D29).
        del _pending_failures[req.build_id]
        cleanup_incomplete = bool(cached["report"].cleanup_errors)  # BF-904a A3: the report's structured cleanup notes
        message = ABORT_CLEANUP_INCOMPLETE if cleanup_incomplete else "Build aborted. Its changes were discarded when it failed."
        runtime.emit_event(EventType.BUILD_RESOLVED, {
            "build_id": req.build_id,
            "resolution": "abort",
            "message": message,
        })
        if cleanup_incomplete:
            return {"status": "ok", "resolution": "abort", "message": message}
        return {"status": "ok", "resolution": "abort"}

    elif req.resolution == "commit_override":
        # BF-904a (#1585): the failed build restored the checkout, so nothing is left to commit
        # in place (the old body committed leftover edits onto whatever branch was checked out,
        # and failed for created files, which had been deleted). The cached changes run again
        # through execute_approved_build with the test gate off, every other guard on, and the
        # override named in the commit body. The outcome arrives as build_success or
        # build_failure, as for the retry paths.
        if not file_changes:
            return {"status": "error", "message": "No files to commit."}
        override_spec = dataclasses.replace(
            spec,
            description=OVERRIDE_MARKER + (f"\n\n{spec.description}" if spec.description else ""),
        )
        del _pending_failures[req.build_id]
        runtime.emit_event(EventType.BUILD_RESOLVED, {
            "build_id": req.build_id,
            "resolution": "commit_override",
            "message": "Re-running the build with the test gate overridden by the Captain.",
        })
        track_task(
            _execute_build(req.build_id, file_changes, override_spec, work_dir, runtime, run_tests=False),  # BF-904a: the test gate is the only guard the override lifts
            name=f"build-resolve-{req.build_id}",
        )
        return {"status": "ok", "resolution": "commit_override", "build_id": req.build_id}

    elif req.resolution in ("retry_extended", "retry_targeted", "retry_fix", "retry_full"):
        del _pending_failures[req.build_id]
        new_build_id = req.build_id

        runtime.emit_event(EventType.BUILD_PROGRESS, {
            "build_id": new_build_id,
            "step": "retrying",
            "step_label": "\u25c8 Retrying build...",
            "current": 1,
            "total": 3,
            "message": f"\u25c8 Resolution: {req.resolution}",
        })

        track_task(
            _execute_build(new_build_id, file_changes, spec, work_dir, runtime),
            name=f"build-resolve-{new_build_id}",
        )
        return {"status": "ok", "resolution": req.resolution, "build_id": new_build_id}

    else:
        return {"status": "error", "message": f"Unknown resolution: {req.resolution}"}


@router.post("/queue/approve")
async def approve_queued_build(
    req: BuildQueueApproveRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Captain approves a queued build — merge worktree to main."""
    if not runtime.build_dispatcher:
        return {"status": "error", "message": "Build dispatcher not running"}
    ok, result = await runtime.build_dispatcher.approve_and_merge(req.build_id)
    if ok:
        _emit_queue_snapshot(runtime)
        return {"status": "ok", "commit": result, "message": f"Build merged: {result[:7]}"}
    return {"status": "error", "message": result}


@router.post("/queue/reject")
async def reject_queued_build(
    req: BuildQueueRejectRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Captain rejects a queued build — discard worktree."""
    if not runtime.build_dispatcher:
        return {"status": "error", "message": "Build dispatcher not running"}
    ok = await runtime.build_dispatcher.reject_build(req.build_id)
    if ok:
        _emit_queue_snapshot(runtime)
        return {"status": "ok", "message": "Build rejected"}
    return {"status": "error", "message": f"Build {req.build_id} not in reviewing status"}


@router.post("/enqueue")
async def enqueue_build(
    req: BuildEnqueueRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Add a build spec to the dispatch queue."""
    if not runtime.build_queue:
        return {"status": "error", "message": "Build queue not running"}
    from probos.cognitive.builder import BuildSpec
    spec = BuildSpec(
        title=req.title,
        description=req.description,
        target_files=req.target_files,
        reference_files=req.reference_files,
        test_files=req.test_files,
        ad_number=req.ad_number,
        constraints=req.constraints,
    )
    build = runtime.build_queue.enqueue(spec, priority=req.priority)
    _emit_queue_snapshot(runtime)
    return {
        "status": "ok",
        "build_id": build.id,
        "message": f"Build '{req.title}' queued at priority {req.priority}",
    }


@router.get("/queue")
async def get_build_queue(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Get the current build queue state."""
    if not runtime.build_queue:
        return {"status": "ok", "items": []}
    items = runtime.build_queue.get_all()
    return {
        "status": "ok",
        "items": [
            {
                "id": b.id,
                "title": b.spec.title,
                "ad_number": b.spec.ad_number,
                "status": b.status,
                "priority": b.priority,
                "worktree_path": b.worktree_path,
                "builder_id": b.builder_id,
                "error": b.error,
                "file_footprint": b.file_footprint,
                "commit_hash": b.result.commit_hash if b.result else "",
            }
            for b in items
        ],
        "active_count": runtime.build_queue.active_count,
    }


# ── Helper functions ──────────────────────────────────────────────

def _emit_queue_snapshot(rt: Any) -> None:
    """Broadcast full queue state to all HXI clients (AD-375)."""
    if not rt.build_queue:
        return
    items = rt.build_queue.get_all()
    rt.emit_event(EventType.BUILD_QUEUE_UPDATE, {
        "items": [
            {
                "id": b.id,
                "title": b.spec.title,
                "ad_number": b.spec.ad_number,
                "status": b.status,
                "priority": b.priority,
                "worktree_path": b.worktree_path,
                "builder_id": b.builder_id,
                "error": b.error,
                "file_footprint": b.file_footprint,
                "commit_hash": b.result.commit_hash if b.result else "",
            }
            for b in items
        ],
    })


async def _run_build(
    req: BuildRequest,
    build_id: str,
    rt: Any,
) -> None:
    """Background build pipeline with WebSocket progress events."""
    try:
        rt.emit_event(EventType.BUILD_STARTED, {
            "build_id": build_id,
            "title": req.title,
            "message": f"Starting build: {req.title}...",
        })

        rt.emit_event(EventType.BUILD_PROGRESS, {
            "build_id": build_id,
            "step": "preparing",
            "step_label": "\u25c8 Preparing build context...",
            "current": 1,
            "total": 3,
            "message": "\u25c8 Reading reference files...",
        })

        rt.emit_event(EventType.BUILD_PROGRESS, {
            "build_id": build_id,
            "step": "generating",
            "step_label": "\u2b21 Generating code...",
            "current": 2,
            "total": 3,
            "message": "\u2b21 Generating code via deep LLM...",
        })

        from probos.types import IntentMessage
        intent = IntentMessage(
            intent="build_code",
            params={
                "title": req.title,
                "description": req.description,
                "target_files": req.target_files,
                "reference_files": req.reference_files,
                "test_files": req.test_files,
                "ad_number": req.ad_number,
                "constraints": req.constraints,
                "force_native": req.force_native,
                "force_visiting": req.force_visiting,
                "model": req.model,
            },
            ttl_seconds=600.0,
        )

        results = await rt.intent_bus.broadcast(intent)

        build_result = None
        for r in results:
            if r and r.success and r.result:
                build_result = r
                break

        if not build_result or not build_result.result:
            error_msg = "BuilderAgent returned no results"
            if results:
                errors = [r.error for r in results if r and r.error]
                if errors:
                    error_msg = "; ".join(errors)
            rt.emit_event(EventType.BUILD_FAILURE, {
                "build_id": build_id,
                "message": f"Build failed: {error_msg}",
                "error": error_msg,
            })
            return

        rt.emit_event(EventType.BUILD_PROGRESS, {
            "build_id": build_id,
            "step": "review",
            "step_label": "\u25ce Ready for review",
            "current": 3,
            "total": 3,
            "message": "\u25ce Code generated \u2014 awaiting Captain approval",
        })

        result_data = build_result.result
        if isinstance(result_data, str):
            import json as _json
            try:
                result_data = _json.loads(result_data)
            except Exception:
                logger.debug("Build context failed", exc_info=True)
                result_data = {"llm_output": result_data, "file_changes": [], "change_count": 0}

        file_changes = result_data.get("file_changes", [])
        change_count = result_data.get("change_count", len(file_changes))
        llm_output = result_data.get("llm_output", "")
        builder_source = result_data.get("builder_source", "native")

        rt.emit_event(EventType.BUILD_GENERATED, {
            "build_id": build_id,
            "title": req.title,
            "description": req.description,
            "ad_number": req.ad_number,
            "file_changes": file_changes,
            "change_count": change_count,
            "llm_output": llm_output,
            "builder_source": builder_source,
            "message": f"Generated {change_count} file(s) for '{req.title}' \u2014 review and approve to apply.",
        })

    except Exception as e:
        logger.warning("Build pipeline failed: %s", e, exc_info=True)
        rt.emit_event(EventType.BUILD_FAILURE, {
            "build_id": build_id,
            "message": f"Build failed: {e}",
            "error": str(e),
        })


async def _execute_build(
    build_id: str,
    file_changes: list[dict],
    spec: Any,
    work_dir: str,
    rt: Any,
    run_tests: bool = True,
) -> None:
    """Background execution of approved build.

    BF-904a (#1585): *run_tests* is False only for the Captain's ``commit_override``.
    """
    from probos.cognitive.builder import execute_approved_build

    try:
        rt.emit_event(EventType.BUILD_PROGRESS, {
            "build_id": build_id,
            "step": "writing",
            "step_label": "\u25c8 Writing files...",
            "current": 1,
            "total": 3,
            "message": "\u25c8 Writing files to disk...",
        })

        result = await execute_approved_build(
            file_changes=file_changes,
            spec=spec,
            work_dir=work_dir,
            run_tests=run_tests,  # BF-904a: False only for the Captain's commit_override
            llm_client=getattr(rt, "llm_client", None),
            escalation_hook=None,
        )

        if result.success:
            rt.emit_event(EventType.BUILD_SUCCESS, {
                "build_id": build_id,
                "branch": result.branch_name,
                "commit": result.commit_hash,
                "files_written": result.files_written + result.files_modified,
                "tests_passed": result.tests_passed,
                "test_result": result.test_result[:500] if result.test_result else "",
                "review": result.review_result,
                "review_issues": result.review_issues,
                "message": (
                    f"\u2b22 Build complete! Branch: {result.branch_name}, "
                    f"Commit: {result.commit_hash}, "
                    f"Files: {len(result.files_written) + len(result.files_modified)}, "
                    f"Tests: {'passed' if result.tests_passed else 'FAILED'}"
                ),
            })
        else:
            from probos.cognitive.builder import classify_build_failure
            report = classify_build_failure(result, spec)
            report.build_id = build_id

            _clean_expired_failures()
            _pending_failures[build_id] = {
                "file_changes": file_changes,
                "spec": spec,
                "work_dir": work_dir,
                "report": report,
                "timestamp": time.time(),
            }

            rt.emit_event(EventType.BUILD_FAILURE, {
                "build_id": build_id,
                "message": f"Build failed: {report.failure_summary}",
                "report": report.to_dict(),
            })
    except Exception as e:
        logger.warning("Build execution failed: %s", e, exc_info=True)
        rt.emit_event(EventType.BUILD_FAILURE, {
            "build_id": build_id,
            "message": f"Build execution failed: {e}",
            "error": str(e),
        })
