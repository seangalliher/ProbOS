# Build Prompt: Visiting Officer HXI Integration (AD-354)

**Objective:** Fix bugs in the Copilot SDK visiting officer adapter and ensure end-to-end integration with the HXI build pipeline so that `/build` commands in the HXI chat can route through the visiting officer seamlessly.

## Context

The visiting officer (Copilot SDK integration, AD-351–353) is working at the adapter level: `CopilotBuilderAdapter.execute()` can connect to the SDK, generate code with claude-opus-4.6, and capture file changes. However, there are bugs in file capture and gaps in the pipeline integration that prevent it from working end-to-end through the HXI `/build` command.

**Architecture flow (already wired):**
```
HXI /build command
  → api.py _run_build()
    → IntentBus.broadcast(intent="build_code")
      → BuilderAgent.perceive()
        → _should_use_visiting_builder() → True (bootstrap default)
          → CopilotBuilderAdapter.execute()
            → result stored in _transporter_result
      → BuilderAgent.decide() → returns _transporter_result
      → BuilderAgent.act() → passes through file_blocks
    → build_generated WebSocket event → HXI shows diff
```

The chain is already wired. The problems are in the details.

## Bugs to Fix

### Bug 1: Empty content on modify blocks (file path mismatch)

**File:** `src/probos/cognitive/copilot_adapter.py`, `execute()` method (around line 435–446)

The SDK reports changed file paths via `SESSION_WORKSPACE_FILE_CHANGED` events. The adapter does:
```python
abs_path = cwd / rel_path
if abs_path.is_file():
    content = abs_path.read_text(...)
```

**Problem:** The `rel_path` from the SDK event may be an absolute path or use different separators than expected. When `cwd / rel_path` doesn't resolve to the actual file, the `if abs_path.is_file()` check fails silently and produces a file block entry with no content (or skips it entirely). This was observed in testing: modify blocks came back with empty `content`.

**Fix:** Normalize the path from the SDK event:
1. If `rel_path` is absolute and starts with `cwd`, make it relative
2. If `rel_path` is absolute but doesn't start with `cwd`, use it directly
3. Normalize path separators (Windows backslash vs forward slash)
4. Add a `logger.warning` if the file cannot be found after normalization, including both the raw SDK path and the resolved absolute path for debugging

### Bug 2: Visiting builder doesn't pass `model` or `cwd` from config

**File:** `src/probos/cognitive/builder.py`, `perceive()` method (around line 1963–1966)

Currently the adapter is constructed without `model` or `cwd`:
```python
adapter = CopilotBuilderAdapter(
    codebase_index=...,
    runtime=self._runtime,
)
```

**Problem:** This means the adapter uses the default model (`claude-opus-4.6`) and default cwd (`_PROJECT_ROOT` = the ProbOS repo root). The cwd pointing at the real repo root means **the SDK writes files directly into the ProbOS source tree**, which is dangerous — it bypasses the Captain approval gate.

**Fix:** The adapter should use a temporary working directory:
1. Create a temp directory for the build session
2. Copy target files into the temp dir (preserving directory structure) so the SDK can read and modify them
3. Pass the temp dir as `cwd` to the adapter
4. After execution, read results from the temp dir
5. Clean up the temp dir in a finally block
6. Pass `model` through from a configuration source (for now, keep the default `claude-opus-4.6`)

### Bug 3: `_should_use_visiting_builder` lacks force flags from build request

**File:** `src/probos/cognitive/builder.py`, `perceive()` method (around line 1956–1959)

The `_should_use_visiting_builder()` function accepts `force_native` and `force_visiting` parameters, but `perceive()` never passes them. Users have no way to control routing from the HXI.

**Fix:** Read `force_native` and `force_visiting` from the intent params:
```python
if _should_use_visiting_builder(
    spec,
    hebbian_router=...,
    force_native=params.get("force_native", False),
    force_visiting=params.get("force_visiting", False),
):
```

And propagate from `BuildRequest` in `api.py`:
- Add `force_native: bool = False` and `force_visiting: bool = False` fields to the `BuildRequest` Pydantic model
- Pass them through to the intent params in `_run_build()`

## Enhancements

### Enhancement 1: Builder source in WebSocket events

**File:** `src/probos/api.py`, `_run_build()` function (around line 918–927)

When `_run_build()` emits the `build_generated` WebSocket event, include `builder_source` ("visiting" or "native") so the HXI can display which builder produced the code. The `builder_source` is already in the act() result dict — just propagate it to the WebSocket event payload.

### Enhancement 2: Model selection in build request

**File:** `src/probos/api.py`, `BuildRequest` model

Add an optional `model: str = ""` field to `BuildRequest`. When set, pass it to the intent params and through to the `CopilotBuilderAdapter` constructor. This lets users specify which model the visiting officer should use (e.g., `/build --model=gpt-5.4 Title: Description`).

**Note:** Don't over-engineer the CLI parsing. For now, just support it via the API `BuildRequest` field. `/build` command parsing can be enhanced later.

### Enhancement 3: HXI build card shows builder source

**File:** `ui/src/store/useStore.ts` or relevant HXI component

When the `build_generated` WebSocket event includes `builder_source: "visiting"`, the HXI build review card should display a badge or label indicating "Built by Visiting Officer (claude-opus-4.6)" vs "Built by Native Builder". This gives the Captain visibility into which builder produced the code under review.

## Files to Modify

1. **`src/probos/cognitive/copilot_adapter.py`** — Bug 1 (path normalization in execute())
2. **`src/probos/cognitive/builder.py`** — Bug 2 (temp dir isolation), Bug 3 (force flags passthrough)
3. **`src/probos/api.py`** — Bug 3 (BuildRequest fields), Enhancement 1 (builder_source in WS event), Enhancement 2 (model field)
4. **`ui/src/store/useStore.ts`** — Enhancement 3 (builder source badge) — if build event handling exists here
5. **`tests/test_copilot_adapter.py`** — Update/add tests for path normalization
6. **`tests/test_builder.py`** or relevant builder tests — Test force flags passthrough and temp dir isolation

## Testing

1. All existing tests must pass (2,345 total)
2. New tests for:
   - Path normalization: absolute paths, backslash paths, mixed separators
   - Temp dir isolation: verify SDK writes go to temp dir, not project root
   - Force flags: `force_native=True` overrides, `force_visiting=True` overrides
   - Builder source propagation through the pipeline
3. Integration verification: The `/build` command through the HXI should reach `CopilotBuilderAdapter.execute()` when SDK is available (manual test)

## Constraints

- Do NOT modify core files (IntentBus, TrustNetwork, HebbianRouter, Consensus)
- Do NOT change the CopilotBuilderAdapter constructor signature beyond what's already there
- The temp dir approach must clean up reliably (use try/finally)
- All changes must be backward-compatible — native builder path must still work when SDK is unavailable
- Keep the `list_available_models()` method that was added during testing (default model is `claude-opus-4.6`)
