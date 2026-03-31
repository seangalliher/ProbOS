"""ProbOS API — Build routes (AD-304, AD-345, AD-375)."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from fastapi import APIRouter, Depends

from probos.api_models import (
    BuildApproveRequest, BuildEnqueueRequest, BuildQueueApproveRequest,
    BuildQueueRejectRequest, BuildRequest, BuildResolveRequest,
)
from probos.events import EventType
from probos.routers.deps import get_runtime, get_task_tracker

logger = logging.getLogger(__name__)

# Import shared failure cache from api module
from probos.api import _pending_failures, _clean_expired_failures, _FAILURE_CACHE_TTL

router = APIRouter(prefix="/api/build", tags=["build"])


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
    track_task: Callable = Depends(get_task_tracker),
) -> dict[str, Any]:
    """Execute an approved build — write files, test, commit."""
    from probos.cognitive.builder import BuildSpec
    import pathlib

    spec = BuildSpec(
        title=req.title,
        description=req.description,
        ad_number=req.ad_number,
        branch_name=req.branch_name,
    )

    work_dir = str(pathlib.Path(__file__).resolve().parent.parent.parent.parent)

    track_task(
        _execute_build(req.build_id, req.file_changes, spec, work_dir, runtime),
        name=f"execute-{req.build_id}",
    )

    return {
        "status": "started",
        "build_id": req.build_id,
        "message": "Executing approved build...",
    }


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

    if req.resolution == "abort":
        from probos.cognitive.builder import _git_checkout_main
        await _git_checkout_main(work_dir)
        del _pending_failures[req.build_id]
        runtime._emit_event(EventType.BUILD_RESOLVED, {
            "build_id": req.build_id,
            "resolution": "abort",
            "message": "Build aborted. Returned to main branch.",
        })
        return {"status": "ok", "resolution": "abort"}

    elif req.resolution == "commit_override":
        from probos.cognitive.builder import _git_add_and_commit
        report = cached["report"]
        all_files = report.files_written + report.files_modified
        if not all_files:
            return {"status": "error", "message": "No files to commit."}
        commit_msg = (
            f"{spec.title}"
            + (f" (AD-{spec.ad_number})" if spec.ad_number else "")
            + "\n\n[Test gate overridden by Captain]"
            + "\n\nCo-Authored-By: ProbOS Builder <probos@probos.dev>"
        )
        ok, sha = await _git_add_and_commit(all_files, commit_msg, work_dir)
        del _pending_failures[req.build_id]
        if ok:
            runtime._emit_event(EventType.BUILD_RESOLVED, {
                "build_id": req.build_id,
                "resolution": "commit_override",
                "message": f"Committed with test gate override. Commit: {sha}",
                "commit": sha,
            })
            return {"status": "ok", "resolution": "commit_override", "commit": sha}
        else:
            return {"status": "error", "message": f"Commit failed: {sha}"}

    elif req.resolution in ("retry_extended", "retry_targeted", "retry_fix", "retry_full"):
        del _pending_failures[req.build_id]
        new_build_id = req.build_id

        runtime._emit_event(EventType.BUILD_PROGRESS, {
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
    rt._emit_event(EventType.BUILD_QUEUE_UPDATE, {
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
        rt._emit_event(EventType.BUILD_STARTED, {
            "build_id": build_id,
            "title": req.title,
            "message": f"Starting build: {req.title}...",
        })

        rt._emit_event(EventType.BUILD_PROGRESS, {
            "build_id": build_id,
            "step": "preparing",
            "step_label": "\u25c8 Preparing build context...",
            "current": 1,
            "total": 3,
            "message": "\u25c8 Reading reference files...",
        })

        rt._emit_event(EventType.BUILD_PROGRESS, {
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
            rt._emit_event(EventType.BUILD_FAILURE, {
                "build_id": build_id,
                "message": f"Build failed: {error_msg}",
                "error": error_msg,
            })
            return

        rt._emit_event(EventType.BUILD_PROGRESS, {
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
                result_data = {"llm_output": result_data, "file_changes": [], "change_count": 0}

        file_changes = result_data.get("file_changes", [])
        change_count = result_data.get("change_count", len(file_changes))
        llm_output = result_data.get("llm_output", "")
        builder_source = result_data.get("builder_source", "native")

        rt._emit_event(EventType.BUILD_GENERATED, {
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
        rt._emit_event(EventType.BUILD_FAILURE, {
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
) -> None:
    """Background execution of approved build."""
    from probos.cognitive.builder import execute_approved_build

    try:
        rt._emit_event(EventType.BUILD_PROGRESS, {
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
            run_tests=True,
            llm_client=getattr(rt, "llm_client", None),
            escalation_hook=None,
        )

        if result.success:
            rt._emit_event(EventType.BUILD_SUCCESS, {
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

            rt._emit_event(EventType.BUILD_FAILURE, {
                "build_id": build_id,
                "message": f"Build failed: {report.failure_summary}",
                "report": report.to_dict(),
            })
    except Exception as e:
        logger.warning("Build execution failed: %s", e, exc_info=True)
        rt._emit_event(EventType.BUILD_FAILURE, {
            "build_id": build_id,
            "message": f"Build execution failed: {e}",
            "error": str(e),
        })
