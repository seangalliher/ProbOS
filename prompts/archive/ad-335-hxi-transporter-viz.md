# AD-335: HXI Transporter Visualization

**Transporter Pattern Step 6 of 7** — WebSocket events for chunk lifecycle and UI display.

## Context

The Transporter Pattern (AD-330–334) executes code generation in parallel chunks, but the HXI
(Human Experience Interface) has no visibility into this process. The user sees "Generating code..."
and then gets the result. They can't see the chunks being decomposed, executing in parallel waves,
assembling, or validating.

This AD adds WebSocket event emission from the Transporter pipeline functions, plus UI handling
in the IntentSurface chat panel. The events follow the same pattern as existing `build_progress`
events but carry richer chunk-level detail.

**Note:** This AD focuses on chat panel messages and state tracking. The Cognitive Canvas
"matter stream" visualization (animated particles flowing between chunks) is deferred to a
future enhancement — it requires significant Three.js work that is out of scope for the
Transporter Pattern MVP.

## What to build

### Part 1: Backend — Event Emission (builder.py)

Add `on_event` callback parameters to three Transporter functions so the API layer
can pass in the event emitter. Events are **optional** — when `on_event` is None,
the functions work exactly as before (pure logic, no side effects).

#### 1a. Update `decompose_blueprint()` signature

**File:** `src/probos/cognitive/builder.py`

Add an optional `on_event` parameter:

```python
async def decompose_blueprint(
    blueprint: BuildBlueprint,
    llm_client: Any,
    codebase_index: Any | None = None,
    work_dir: str | None = None,
    on_event: Any | None = None,  # ADD THIS
) -> BuildBlueprint:
```

Emit events at key points (only if `on_event is not None`):

After successful decomposition (after `blueprint.chunks = chunks` near the end):
```python
if on_event:
    import asyncio
    asyncio.ensure_future(on_event("transporter_decomposed", {
        "chunk_count": len(blueprint.chunks),
        "chunks": [
            {"chunk_id": c.chunk_id, "description": c.description, "target_file": c.target_file}
            for c in blueprint.chunks
        ],
    }))
```

After fallback decomposition (inside the except/fallback path, after `_fallback_decompose` returns):
```python
if on_event:
    import asyncio
    asyncio.ensure_future(on_event("transporter_decomposed", {
        "chunk_count": len(blueprint.chunks),
        "chunks": [
            {"chunk_id": c.chunk_id, "description": c.description, "target_file": c.target_file}
            for c in blueprint.chunks
        ],
        "fallback": True,
    }))
```

#### 1b. Update `execute_chunks()` signature

Add `on_event` parameter:

```python
async def execute_chunks(
    blueprint: BuildBlueprint,
    llm_client: Any,
    work_dir: str | None = None,
    on_event: Any | None = None,  # ADD THIS
) -> BuildBlueprint:
```

Emit events at key points:

At the start of each wave (inside the while loop, after computing `ready`):
```python
if on_event:
    await on_event("transporter_wave_start", {
        "wave": wave_num,  # You'll need to add a wave counter
        "chunk_ids": [c.chunk_id for c in ready],
        "message": f"Wave {wave_num}: executing {len(ready)} chunks in parallel",
    })
```

Add a `wave_num = 0` counter before the while loop, increment at the top: `wave_num += 1`.

After each individual chunk completes (after `results[chunk.chunk_id] = result`):
```python
if on_event:
    await on_event("transporter_chunk_done", {
        "chunk_id": chunk.chunk_id,
        "success": result.success,
        "confidence": result.confidence,
        "target_file": chunk.target_file,
        "error": result.error if not result.success else "",
    })
```

After all waves complete (after the while loop, before `return blueprint`):
```python
if on_event:
    success_count = sum(1 for r in blueprint.results if r.success)
    await on_event("transporter_execution_done", {
        "total_chunks": len(blueprint.chunks),
        "successful": success_count,
        "failed": len(blueprint.chunks) - success_count,
        "waves": wave_num,
    })
```

#### 1c. Add event emission after assembly and validation

These are called from `api.py`, not from `builder.py` functions directly. The events will
be emitted in the API layer (Part 2 below), not inside `assemble_chunks()` or `validate_assembly()`,
because those functions are synchronous and don't take `on_event`.

### Part 2: Backend — API Integration (api.py)

**File:** `src/probos/api.py`

This is where the Transporter events get wired into the build pipeline. However, the current
build pipeline in `api.py` does NOT yet use the Transporter Pattern (that's AD-336). So for
AD-335, we add **helper functions** that the AD-336 integration will call.

Add a new helper function after the existing `_run_build_pipeline` function:

```python
async def _emit_transporter_events(
    rt: Any,
    build_id: str,
    blueprint: Any,
    assembled_blocks: list,
    validation_result: Any,
) -> None:
    """Emit summary transporter events for HXI display.

    Called after the transporter pipeline completes. Emits assembly
    and validation results so the UI can display the full chunk lifecycle.
    """
    from probos.cognitive.builder import assembly_summary

    rt._emit_event("transporter_assembled", {
        "build_id": build_id,
        "file_count": len(assembled_blocks),
        "summary": assembly_summary(blueprint),
    })

    rt._emit_event("transporter_validated", {
        "build_id": build_id,
        "valid": validation_result.valid,
        "errors": validation_result.errors,
        "warnings": validation_result.warnings,
        "checks_passed": validation_result.checks_passed,
        "checks_failed": validation_result.checks_failed,
    })
```

### Part 3: Frontend — Event Handling (useStore.ts)

**File:** `ui/src/store/useStore.ts`

Add new state field for transporter progress in the HXI state interface (near `buildProgress`):

```typescript
// In the state interface (near line 190):
transporterProgress: {
  phase: string;
  chunks: Array<{ chunk_id: string; description: string; target_file: string; status: string }>;
  waves_completed: number;
  total_chunks: number;
  successful: number;
  failed: number;
} | null;
```

Initialize it in the create block (near line 259):
```typescript
transporterProgress: null,
```

Add event handlers in the `handleEvent` switch (after the `build_failure` case, before `design_started`):

```typescript
case 'transporter_decomposed': {
  const chunks = (data.chunks as Array<{ chunk_id: string; description: string; target_file: string }>) || [];
  const fallback = data.fallback as boolean;
  set({
    transporterProgress: {
      phase: 'decomposed',
      chunks: chunks.map(c => ({ ...c, status: 'pending' })),
      waves_completed: 0,
      total_chunks: chunks.length,
      successful: 0,
      failed: 0,
    },
  });
  const suffix = fallback ? ' (fallback)' : '';
  get().addChatMessage('system', `⬡ Transporter: decomposed into ${chunks.length} chunks${suffix}`);
  break;
}

case 'transporter_wave_start': {
  const wave = data.wave as number;
  const chunkIds = (data.chunk_ids as string[]) || [];
  const tp = get().transporterProgress;
  if (tp) {
    const updated = tp.chunks.map(c =>
      chunkIds.includes(c.chunk_id) ? { ...c, status: 'executing' } : c
    );
    set({ transporterProgress: { ...tp, chunks: updated } });
  }
  get().addChatMessage('system', `⬡ Wave ${wave}: ${chunkIds.length} chunks executing...`);
  break;
}

case 'transporter_chunk_done': {
  const chunkId = data.chunk_id as string;
  const success = data.success as boolean;
  const confidence = data.confidence as number;
  const tp = get().transporterProgress;
  if (tp) {
    const updated = tp.chunks.map(c =>
      c.chunk_id === chunkId ? { ...c, status: success ? 'done' : 'failed' } : c
    );
    set({
      transporterProgress: {
        ...tp,
        chunks: updated,
        successful: success ? tp.successful + 1 : tp.successful,
        failed: success ? tp.failed : tp.failed + 1,
      },
    });
  }
  if (!success) {
    const err = data.error as string;
    get().addChatMessage('system', `⬡ Chunk ${chunkId} failed: ${err}`);
  }
  break;
}

case 'transporter_execution_done': {
  const total = data.total_chunks as number;
  const successful = data.successful as number;
  const waves = data.waves as number;
  const tp = get().transporterProgress;
  if (tp) {
    set({ transporterProgress: { ...tp, phase: 'executed', waves_completed: waves } });
  }
  get().addChatMessage('system', `⬡ Matter stream complete: ${successful}/${total} chunks in ${waves} wave(s)`);
  break;
}

case 'transporter_assembled': {
  const fileCount = data.file_count as number;
  const tp = get().transporterProgress;
  if (tp) {
    set({ transporterProgress: { ...tp, phase: 'assembled' } });
  }
  get().addChatMessage('system', `⬡ Rematerialized: ${fileCount} file(s) assembled`);
  break;
}

case 'transporter_validated': {
  const valid = data.valid as boolean;
  const errCount = (data.errors as Array<unknown>)?.length || 0;
  const warnCount = (data.warnings as Array<unknown>)?.length || 0;
  const tp = get().transporterProgress;
  if (tp) {
    set({ transporterProgress: { ...tp, phase: valid ? 'valid' : 'invalid' } });
  }
  if (valid) {
    get().addChatMessage('system', `⬡ Heisenberg compensator: all checks passed${warnCount > 0 ? ` (${warnCount} warnings)` : ''}`);
  } else {
    get().addChatMessage('system', `⬡ Heisenberg compensator: ${errCount} error(s) detected`);
  }
  // Clear transporter progress after validation
  set({ transporterProgress: null });
  break;
}
```

### Part 4: Frontend — Type Definitions (types.ts)

**File:** `ui/src/store/types.ts`

Add the transporter progress type (near the `BuildProposal` interface):

```typescript
export interface TransporterChunkStatus {
  chunk_id: string;
  description: string;
  target_file: string;
  status: 'pending' | 'executing' | 'done' | 'failed';
}

export interface TransporterProgress {
  phase: 'decomposed' | 'executing' | 'executed' | 'assembled' | 'valid' | 'invalid';
  chunks: TransporterChunkStatus[];
  waves_completed: number;
  total_chunks: number;
  successful: number;
  failed: number;
}
```

## Tests

All tests go in `tests/test_builder_agent.py`.

### Test imports

Add `execute_chunks` to the existing import block if not already there (it should be from AD-332).

### Test class: `TestTransporterEvents` (8 tests)

```python
class TestTransporterEvents:
    """Tests for Transporter Pattern event emission (AD-335)."""

    def test_decompose_emits_event(self):
        """decompose_blueprint emits transporter_decomposed when on_event provided."""
        events = []
        async def capture_event(event_type, data):
            events.append((event_type, data))

        bp = BuildBlueprint(spec=BuildSpec(
            title="test", description="test",
            target_files=["src/foo.py"],
        ))
        # Use fallback path (no LLM) by providing no llm_client
        mock_llm = AsyncMock(side_effect=Exception("no LLM"))
        asyncio.get_event_loop().run_until_complete(
            decompose_blueprint(bp, mock_llm, on_event=capture_event)
        )
        # Should have emitted transporter_decomposed
        assert any(e[0] == "transporter_decomposed" for e in events)
        decomposed = [e for e in events if e[0] == "transporter_decomposed"][0][1]
        assert decomposed["chunk_count"] > 0
        assert decomposed.get("fallback") is True

    def test_decompose_no_event_when_none(self):
        """decompose_blueprint works without on_event (backward compatible)."""
        bp = BuildBlueprint(spec=BuildSpec(
            title="test", description="test",
            target_files=["src/foo.py"],
        ))
        mock_llm = AsyncMock(side_effect=Exception("no LLM"))
        # Should not raise — on_event defaults to None
        result = asyncio.get_event_loop().run_until_complete(
            decompose_blueprint(bp, mock_llm)
        )
        assert len(result.chunks) > 0

    def test_execute_emits_wave_events(self):
        """execute_chunks emits wave_start and chunk_done events."""
        events = []
        async def capture_event(event_type, data):
            events.append((event_type, data))

        bp = BuildBlueprint(spec=BuildSpec(title="test", description="test"))
        bp.chunks = [
            ChunkSpec(chunk_id="c1", description="d1", target_file="f1.py", what_to_generate="code"),
        ]
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = MagicMock(
            content="===FILE: f1.py===\n===CREATE===\ndef foo(): pass\n===END==="
        )
        asyncio.get_event_loop().run_until_complete(
            execute_chunks(bp, mock_llm, on_event=capture_event)
        )
        event_types = [e[0] for e in events]
        assert "transporter_wave_start" in event_types
        assert "transporter_chunk_done" in event_types
        assert "transporter_execution_done" in event_types

    def test_execute_no_event_when_none(self):
        """execute_chunks works without on_event (backward compatible)."""
        bp = BuildBlueprint(spec=BuildSpec(title="test", description="test"))
        bp.chunks = [
            ChunkSpec(chunk_id="c1", description="d1", target_file="f1.py", what_to_generate="code"),
        ]
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = MagicMock(
            content="===FILE: f1.py===\n===CREATE===\ndef foo(): pass\n===END==="
        )
        result = asyncio.get_event_loop().run_until_complete(
            execute_chunks(bp, mock_llm)
        )
        assert len(result.results) == 1

    def test_wave_start_includes_chunk_ids(self):
        """Wave start event includes correct chunk IDs."""
        events = []
        async def capture_event(event_type, data):
            events.append((event_type, data))

        bp = BuildBlueprint(spec=BuildSpec(title="test", description="test"))
        bp.chunks = [
            ChunkSpec(chunk_id="c1", description="d1", target_file="f1.py", what_to_generate="code"),
            ChunkSpec(chunk_id="c2", description="d2", target_file="f2.py", what_to_generate="code"),
        ]
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = MagicMock(
            content="===FILE: f1.py===\n===CREATE===\ndef foo(): pass\n===END==="
        )
        asyncio.get_event_loop().run_until_complete(
            execute_chunks(bp, mock_llm, on_event=capture_event)
        )
        wave_events = [e for e in events if e[0] == "transporter_wave_start"]
        assert len(wave_events) >= 1
        # First wave should have both chunks (no deps)
        assert "c1" in wave_events[0][1]["chunk_ids"]
        assert "c2" in wave_events[0][1]["chunk_ids"]

    def test_chunk_done_reports_failure(self):
        """Chunk done event correctly reports failure."""
        events = []
        async def capture_event(event_type, data):
            events.append((event_type, data))

        bp = BuildBlueprint(spec=BuildSpec(title="test", description="test"))
        bp.chunks = [
            ChunkSpec(chunk_id="c1", description="d1", target_file="f1.py", what_to_generate="code"),
        ]
        mock_llm = AsyncMock()
        mock_llm.generate.side_effect = Exception("LLM error")
        asyncio.get_event_loop().run_until_complete(
            execute_chunks(bp, mock_llm, on_event=capture_event)
        )
        chunk_events = [e for e in events if e[0] == "transporter_chunk_done"]
        assert len(chunk_events) == 1
        assert chunk_events[0][1]["success"] is False

    def test_execution_done_summary(self):
        """Execution done event includes correct summary counts."""
        events = []
        async def capture_event(event_type, data):
            events.append((event_type, data))

        bp = BuildBlueprint(spec=BuildSpec(title="test", description="test"))
        bp.chunks = [
            ChunkSpec(chunk_id="c1", description="d1", target_file="f1.py", what_to_generate="code"),
        ]
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = MagicMock(
            content="===FILE: f1.py===\n===CREATE===\ndef foo(): pass\n===END==="
        )
        asyncio.get_event_loop().run_until_complete(
            execute_chunks(bp, mock_llm, on_event=capture_event)
        )
        done_events = [e for e in events if e[0] == "transporter_execution_done"]
        assert len(done_events) == 1
        assert done_events[0][1]["total_chunks"] == 1
        assert done_events[0][1]["waves"] >= 1

    def test_emit_transporter_events_helper(self):
        """_emit_transporter_events emits assembled and validated events."""
        emitted = []
        class FakeRuntime:
            def _emit_event(self, event_type, data):
                emitted.append((event_type, data))

        from probos.cognitive.builder import ValidationResult
        rt = FakeRuntime()
        bp = BuildBlueprint(spec=BuildSpec(title="test", description="test"))
        bp.chunks = [ChunkSpec(chunk_id="c1", description="d", target_file="f.py", what_to_generate="code")]
        bp.results = [ChunkResult(chunk_id="c1", success=True, confidence=4)]
        blocks = [{"path": "f.py", "content": "x = 1", "mode": "create", "after_line": None}]
        vr = ValidationResult(valid=True, checks_passed=5)

        asyncio.get_event_loop().run_until_complete(
            _emit_transporter_events(rt, "build-1", bp, blocks, vr)
        )
        event_types = [e[0] for e in emitted]
        assert "transporter_assembled" in event_types
        assert "transporter_validated" in event_types
```

### Test imports update

Add `_emit_transporter_events` to the import block from `probos.cognitive.builder` — wait, it's
in `api.py`. Instead, import it from the api module:

Actually, the helper is in `api.py` which may be hard to import in tests. **Alternative**: make
`_emit_transporter_events` a module-level async function in `builder.py` instead:

```python
async def _emit_transporter_events(
    rt: Any,
    build_id: str,
    blueprint: BuildBlueprint,
    assembled_blocks: list,
    validation_result: Any,
) -> None:
```

This keeps all Transporter code in builder.py and makes testing straightforward. Place it after
`assembly_summary()` and before `validate_assembly()`.

Add `_emit_transporter_events` to the import block in `tests/test_builder_agent.py`.

## Implementation constraints

1. **Backward compatible** — all `on_event` parameters default to `None`. Existing callers unchanged.
2. **Event naming** — all events prefixed with `transporter_` to namespace cleanly.
3. **No Cognitive Canvas changes** — only chat panel messages. Canvas visualization is deferred.
4. **Follow existing patterns** — events use `rt._emit_event()` or `on_event()` exactly like
   existing `build_progress` events.
5. **TypeScript strictness** — new types added to `types.ts`, state initialized to `null`.
6. **Do NOT modify** existing event handlers or existing tests.
7. **8 total tests** in one test class.
8. **Files to modify:** `src/probos/cognitive/builder.py`, `src/probos/api.py`,
   `ui/src/store/useStore.ts`, `ui/src/store/types.ts`, `tests/test_builder_agent.py`.
