# AD-304/305: Builder Agent API + HXI Approval Surface

*"Engineering to Bridge — the blueprints are ready for your review, Captain."*

This adds the API endpoint and HXI frontend to trigger the BuilderAgent, show progress, and let the Captain review and approve generated code. Mirrors the existing self-mod approval flow (AD-270/271) but adapted for general code generation.

**Current AD count:** AD-303. This prompt uses AD-304+.
**Current test count:** 1775 pytest + 21 vitest.

---

## Pre-Build Audit

Read these files before writing any code:

1. `src/probos/api.py` — existing selfmod approve flow (lines 94-106 for request models, lines 302-533 for the full pipeline). Mirror this pattern exactly.
2. `src/probos/cognitive/builder.py` — BuilderAgent, BuildSpec, BuildResult, execute_approved_build, _parse_file_blocks. This is what you're wiring up.
3. `src/probos/runtime.py` — `_emit_event()` method (lines 227-228), builder pool registration
4. `ui/src/store/types.ts` — SelfModProposal, ChatMessage interfaces. You'll add BuildProposal here.
5. `ui/src/store/useStore.ts` — handleEvent switch (lines 548-591 for self_mod events). You'll add build_* event handlers here.
6. `ui/src/components/IntentSurface.tsx` — selfmod approval buttons (lines 233-251 for approveSelfMod, lines 358-409 for inline buttons). You'll add parallel build approval buttons.

---

## What To Build

### Step 1: API request/response models (AD-304)

**File:** `src/probos/api.py`

Add new Pydantic models alongside the existing SelfModRequest (around line 106):

```python
class BuildRequest(BaseModel):
    """Request to trigger the BuilderAgent."""
    title: str
    description: str
    target_files: list[str] = []
    reference_files: list[str] = []
    test_files: list[str] = []
    ad_number: int = 0
    constraints: list[str] = []


class BuildApproveRequest(BaseModel):
    """Request to approve and execute a generated build."""
    build_id: str
    file_changes: list[dict[str, Any]] = []
    title: str = ""
    description: str = ""
    ad_number: int = 0
    branch_name: str = ""
```

### Step 2: Build submission endpoint (AD-304)

**File:** `src/probos/api.py`

Add a new endpoint `POST /api/build/submit` inside `create_app()`, placed after the selfmod endpoints (after line 533). This endpoint kicks off the BuilderAgent asynchronously — same fire-and-forget pattern as `/api/selfmod/approve`:

```python
@app.post("/api/build/submit")
async def submit_build(req: BuildRequest) -> dict[str, Any]:
    """Start async build generation. Progress via WebSocket events."""
    # Generate a unique build_id
    import uuid
    build_id = uuid.uuid4().hex[:12]

    asyncio.create_task(_run_build(req, build_id, runtime))

    return {
        "status": "started",
        "build_id": build_id,
        "message": f"Build '{req.title}' started...",
    }
```

### Step 3: Background build pipeline function (AD-304)

**File:** `src/probos/api.py`

Add `_run_build()` as a module-level async function inside `create_app()`, modeled on `_run_selfmod()`. This function:

1. Emits `build_started` event via `runtime._emit_event()`
2. Emits `build_progress` events at each step
3. Dispatches a `build_code` intent through the intent bus with the BuildSpec params
4. On success: Emits `build_generated` event with the file changes and LLM output for Captain review
5. On failure: Emits `build_failure` event with error details

```python
async def _run_build(
    req: BuildRequest,
    build_id: str,
    rt: Any,
) -> None:
    """Background build pipeline with WebSocket progress events."""
    try:
        rt._emit_event("build_started", {
            "build_id": build_id,
            "title": req.title,
            "message": f"Starting build: {req.title}...",
        })

        # Step 1: Reading reference files
        rt._emit_event("build_progress", {
            "build_id": build_id,
            "step": "preparing",
            "step_label": "\u2692 Preparing build context...",
            "current": 1,
            "total": 3,
            "message": "\u2692 Reading reference files...",
        })

        # Step 2: Generate code via BuilderAgent through intent bus
        rt._emit_event("build_progress", {
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
            },
        )

        results = await rt.intent_bus.broadcast(intent)

        # Find the successful result from the BuilderAgent
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
            rt._emit_event("build_failure", {
                "build_id": build_id,
                "message": f"Build failed: {error_msg}",
                "error": error_msg,
            })
            return

        # Step 3: Present for review
        rt._emit_event("build_progress", {
            "build_id": build_id,
            "step": "review",
            "step_label": "\u25ce Ready for review",
            "current": 3,
            "total": 3,
            "message": "\u25ce Code generated — awaiting Captain approval",
        })

        # Extract result data
        result_data = build_result.result
        if isinstance(result_data, str):
            # handle case where result is a string
            import json as _json
            try:
                result_data = _json.loads(result_data)
            except Exception:
                result_data = {"llm_output": result_data, "file_changes": [], "change_count": 0}

        file_changes = result_data.get("file_changes", [])
        change_count = result_data.get("change_count", len(file_changes))
        llm_output = result_data.get("llm_output", "")

        rt._emit_event("build_generated", {
            "build_id": build_id,
            "title": req.title,
            "description": req.description,
            "ad_number": req.ad_number,
            "file_changes": file_changes,
            "change_count": change_count,
            "llm_output": llm_output,
            "message": f"Generated {change_count} file(s) for '{req.title}' — review and approve to apply.",
        })

    except Exception as e:
        logger.warning("Build pipeline failed: %s", e, exc_info=True)
        rt._emit_event("build_failure", {
            "build_id": build_id,
            "message": f"Build failed: {e}",
            "error": str(e),
        })
```

### Step 4: Build approval endpoint (AD-304)

**File:** `src/probos/api.py`

Add `POST /api/build/approve` — called after the Captain reviews the generated code and clicks "Approve Build":

```python
@app.post("/api/build/approve")
async def approve_build(req: BuildApproveRequest) -> dict[str, Any]:
    """Execute an approved build — write files, test, commit."""
    from probos.cognitive.builder import BuildSpec, execute_approved_build

    spec = BuildSpec(
        title=req.title,
        description=req.description,
        ad_number=req.ad_number,
        branch_name=req.branch_name,
    )

    # Determine the project root directory
    import pathlib
    work_dir = str(pathlib.Path(__file__).resolve().parent.parent.parent)

    asyncio.create_task(_execute_build(req.build_id, req.file_changes, spec, work_dir, runtime))

    return {
        "status": "started",
        "build_id": req.build_id,
        "message": "Executing approved build...",
    }
```

Add the async execution function:

```python
async def _execute_build(
    build_id: str,
    file_changes: list[dict],
    spec: Any,
    work_dir: str,
    rt: Any,
) -> None:
    """Background execution of approved build."""
    from probos.cognitive.builder import BuildSpec, execute_approved_build

    try:
        rt._emit_event("build_progress", {
            "build_id": build_id,
            "step": "writing",
            "step_label": "\u270d Writing files...",
            "current": 1,
            "total": 3,
            "message": "\u270d Writing files to disk...",
        })

        result = await execute_approved_build(
            file_changes=file_changes,
            spec=spec,
            work_dir=work_dir,
            run_tests=True,
        )

        if result.success:
            rt._emit_event("build_success", {
                "build_id": build_id,
                "branch": result.branch_name,
                "commit": result.commit_hash,
                "files_written": result.files_written,
                "tests_passed": result.tests_passed,
                "test_result": result.test_result[:500] if result.test_result else "",
                "message": (
                    f"\u2b22 Build complete! Branch: {result.branch_name}, "
                    f"Commit: {result.commit_hash}, "
                    f"Files: {len(result.files_written)}, "
                    f"Tests: {'passed' if result.tests_passed else 'FAILED'}"
                ),
            })
        else:
            rt._emit_event("build_failure", {
                "build_id": build_id,
                "message": f"Build execution failed: {result.error}",
                "error": result.error,
                "test_result": result.test_result[:500] if result.test_result else "",
            })
    except Exception as e:
        logger.warning("Build execution failed: %s", e, exc_info=True)
        rt._emit_event("build_failure", {
            "build_id": build_id,
            "message": f"Build execution failed: {e}",
            "error": str(e),
        })
```

**Run tests after this step:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

### Step 5: HXI types (AD-305)

**File:** `ui/src/store/types.ts`

Add a `BuildProposal` interface alongside `SelfModProposal`:

```typescript
export interface BuildProposal {
  build_id: string;
  title: string;
  description: string;
  ad_number: number;
  file_changes: Array<{
    path: string;
    content: string;
    mode: 'create' | 'modify';
    after_line: string | null;
  }>;
  change_count: number;
  llm_output: string;
  status: 'generating' | 'review' | 'approved' | 'rejected';
}
```

Add `buildProposal` as an optional field to `ChatMessage`:

```typescript
export interface ChatMessage {
  id: string;
  role: 'user' | 'system';
  text: string;
  timestamp: number;
  selfModProposal?: SelfModProposal;
  buildProposal?: BuildProposal;        // <-- add this line
}
```

### Step 6: Zustand store — build event handlers (AD-305)

**File:** `ui/src/store/useStore.ts`

Add state fields to the HXI state interface (near the existing `selfModProgress`):

```typescript
buildProgress: { step: string; current: number; total: number; label: string } | null;
```

Initialize it as `null` in the initial state.

Add event handlers in the `handleEvent` function's switch/case block (alongside the existing `self_mod_*` handlers). Handle these WebSocket event types:

- **`build_started`**: Add a chat message: `data.message`
- **`build_progress`**: Set `buildProgress` state with `{step, current, total, label: data.step_label}`, add chat message with `data.message`
- **`build_generated`**: Clear `buildProgress` to null. Store the build proposal on the chat message using `addChatMessage('system', data.message, { buildProposal: { build_id, title, description, ad_number, file_changes, change_count, llm_output, status: 'review' } })`. This triggers the inline approval UI.
- **`build_success`**: Clear `buildProgress` to null. Add a chat message with `data.message`. Optionally play `soundEngine.playSelfModSpawn()` (reuse the existing success sound).
- **`build_failure`**: Clear `buildProgress` to null. Add a chat message with `data.message`.

Important: `buildProposal` on ChatMessage should NOT be serialized to localStorage — same pattern as `selfModProposal`. It's transient UI state.

### Step 7: HXI IntentSurface — build approval UI (AD-305)

**File:** `ui/src/components/IntentSurface.tsx`

Add inline approval buttons for build proposals, mirroring the self-mod proposal buttons. When a chat message has a `buildProposal` attached (and `status === 'review'`), render:

1. **A file change summary** — show the list of file paths that will be created/modified, with a count. Keep it compact:
   ```
   Generated 3 files:
   • src/probos/foo/bar.py (create)
   • src/probos/foo/baz.py (create)
   • tests/test_bar.py (create)
   ```

2. **A collapsible "View Code" section** — clicking it expands to show the LLM output (the raw generated code). Use a `<details>` element or simple toggle state. This lets the Captain review the actual code before approving.

3. **Three buttons:**
   - **"Approve Build"** (green) — calls `POST /api/build/approve` with `{ build_id, file_changes, title, description, ad_number }`. On click, update `buildProposal.status` to `'approved'` and disable buttons.
   - **"Reject"** (red/gray) — sets `buildProposal.status` to `'rejected'`, adds a chat message "Build rejected by Captain." No API call needed.
   - **"View Full Output"** — toggles showing the full `llm_output` in a scrollable pre-formatted block

Add an `approveBuild` callback function similar to `approveSelfMod`:

```typescript
const approveBuild = useCallback(async (proposal: BuildProposal) => {
  addChatMessage('system', `Executing build: ${proposal.title}...`);
  try {
    await fetch('/api/build/approve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        build_id: proposal.build_id,
        file_changes: proposal.file_changes,
        title: proposal.title,
        description: proposal.description,
        ad_number: proposal.ad_number,
      }),
    });
    // Progress and results come via WebSocket events
  } catch {
    addChatMessage('system', '(Build approval request failed)');
  }
}, [addChatMessage]);
```

### Step 8: Build command in chat (AD-304)

**File:** `src/probos/api.py`

Add a `/build` slash command handler in `_handle_slash_command()` (the function that processes slash commands). When the user types `/build <title>: <description>`, it should trigger the build submission:

```python
if command == "build":
    # Parse "title: description" format
    parts = args.split(":", 1) if args else ["", ""]
    title = parts[0].strip()
    description = parts[1].strip() if len(parts) > 1 else ""
    if not title:
        return {"response": "Usage: /build <title>: <description>"}

    import uuid
    build_id = uuid.uuid4().hex[:12]
    asyncio.create_task(_run_build(
        BuildRequest(title=title, description=description),
        build_id,
        runtime,
    ))
    return {
        "response": f"Build '{title}' submitted (id: {build_id}). Progress will appear below.",
        "build_id": build_id,
    }
```

Note: `_run_build` is defined inside `create_app()` so it has access to the `runtime` closure. The `/build` command handler must also be inside `create_app()` to access `_run_build`. Make sure `_run_build` is defined before `_handle_slash_command` references it (or use forward reference).

**Run tests after this step:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

### Step 9: Tests (AD-304)

**File:** `tests/test_builder_api.py` (new file)

Write tests covering:

1. **BuildRequest model validation** — required fields, defaults
2. **BuildApproveRequest model validation** — required fields, defaults
3. **`/api/build/submit` endpoint** — mock runtime, verify it returns `{"status": "started", "build_id": ...}` and creates a background task
4. **`/api/build/approve` endpoint** — mock runtime and `execute_approved_build`, verify it returns started status
5. **`/build` slash command parsing** — test with valid input (`/build My Feature: do the thing`), missing title, empty input
6. **`_run_build` event emission** — mock intent_bus.broadcast, verify the sequence of events emitted: `build_started` → `build_progress` (x3) → `build_generated` (on success) or `build_failure` (on error)
7. **`_execute_build` event emission** — mock `execute_approved_build`, verify `build_success` event on success and `build_failure` on failure

Use `httpx.AsyncClient` with `ASGITransport` for endpoint tests — follow the pattern in existing API tests (e.g., `tests/test_hxi_chat_integration.py`).

For the frontend changes, add Vitest tests only if there are existing patterns for component testing. If not, skip frontend tests — the existing self-mod UI has no dedicated component tests either.

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_builder_api.py -x -v`

Then full suite: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

Then vitest: `cd ui && npx vitest run`

---

## AD Summary

| AD | Decision |
|----|----------|
| AD-304 | Builder API — `POST /api/build/submit` triggers BuilderAgent via intent bus, emits `build_started/progress/generated/failure` WebSocket events. `POST /api/build/approve` calls `execute_approved_build()` with `build_success/failure` events. `/build` slash command parses `title: description` format. Fire-and-forget pattern matching selfmod flow |
| AD-305 | Builder HXI — `BuildProposal` type with file changes and review status. Zustand store handles `build_*` events with `buildProgress` state. IntentSurface renders inline approval UI: file change summary, collapsible code view, Approve/Reject buttons. `buildProposal` on ChatMessage is transient (not serialized to localStorage) |

---

## Do NOT Build

- **Build spec file parser** — reading build prompts from `prompts/*.md` and converting to BuildSpec is a separate step (Step 3 on the northstar path). This prompt only wires up the API + HXI
- **Build history/persistence** — no storing of past builds in a database or knowledge store. Builds are transient in this iteration
- **Automatic build triggering** — builds are only triggered by explicit user action (`/build` command or future Architect Agent). No auto-triggering
- **MODIFY mode execution** — already deferred in AD-303. Continue skipping MODIFY blocks with a warning
- **3D canvas animation for builds** — reuse the existing SelfModBloom animation sound if desired, but don't create a new animation

---

## Constraints

- Do NOT modify `src/probos/cognitive/builder.py` — that file is complete from AD-302/303
- Do NOT modify existing self-mod endpoints or their behavior — the build flow is parallel, not a replacement
- Do NOT add new Python dependencies
- Follow the exact same async fire-and-forget pattern as selfmod: POST returns immediately, all progress via WebSocket events
- The `/build` command must work from both the CLI shell and the HXI chat
- `buildProposal` must NOT be persisted to localStorage (same transient pattern as `selfModProposal`)
- Run tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
- Run vitest: `cd d:/ProbOS/ui && npx vitest run`

---

## Update PROGRESS.md When Done

Add to the AD table:

```
| AD-304 | Builder API — `/api/build/submit` triggers BuilderAgent via intent bus, `/api/build/approve` executes `execute_approved_build()`. `/build` slash command. WebSocket events: build_started, build_progress, build_generated, build_success, build_failure. Fire-and-forget async pattern matching selfmod |
| AD-305 | Builder HXI — BuildProposal type, Zustand build_* event handlers, IntentSurface inline approval UI with file summary, code review toggle, Approve/Reject buttons. Transient buildProposal on ChatMessage (not persisted to localStorage) |
```

Update the status line test count to reflect any new tests added.
