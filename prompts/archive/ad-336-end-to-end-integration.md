# AD-336: End-to-End Integration & Fallback

**Transporter Pattern Step 7 of 7** — Wire everything together.

## Context

AD-330 through AD-335 built the Transporter Pattern components individually:
- AD-330: BuildBlueprint, ChunkSpec, ChunkResult (data structures)
- AD-331: `decompose_blueprint()` (dematerializer)
- AD-332: `execute_chunks()` (matter stream)
- AD-333: `assemble_chunks()` (rematerializer)
- AD-334: `validate_assembly()` (Heisenberg compensator)
- AD-335: WebSocket events for HXI visibility

Now we wire them into the existing BuilderAgent pipeline. The key integration point is
`BuilderAgent.act()` — currently it sends the entire build to a single LLM call. When the
build is large enough, it should use the Transporter Pattern instead.

## What to build

All code goes in `src/probos/cognitive/builder.py`. All tests go in `tests/test_builder_agent.py`.

### 1. `_should_use_transporter()` function

Add as a module-level function, placed after `_emit_transporter_events()` and before the
git helpers section.

```python
def _should_use_transporter(spec: BuildSpec, context_size: int = 0) -> bool:
    """Decide whether to use the Transporter Pattern for this build.

    Uses Transporter when the build is complex enough that parallel chunk
    generation would outperform single-pass generation. Falls back to
    single-pass for small, simple builds.

    Args:
        spec: The BuildSpec describing what to build.
        context_size: Total character count of target file contents (0 if unknown).

    Returns:
        True if Transporter should be used.
    """
    # Multiple target files → Transporter
    if len(spec.target_files) > 2:
        return True

    # Large context → Transporter
    if context_size > 20_000:  # ~500 lines, matches _LOCALIZE_THRESHOLD
        return True

    # Multiple test files alongside implementation → Transporter
    if len(spec.target_files) >= 1 and len(spec.test_files) >= 1:
        # At least 2 distinct concerns (impl + tests)
        if len(spec.target_files) + len(spec.test_files) > 2:
            return True

    return False
```

### 2. `transporter_build()` async function

This is the high-level orchestration function that chains all Transporter steps.
Add as a module-level async function, after `_should_use_transporter()`.

```python
async def transporter_build(
    spec: BuildSpec,
    llm_client: Any,
    work_dir: str | None = None,
    codebase_index: Any | None = None,
    on_event: Any | None = None,
) -> list[dict[str, Any]]:
    """Run the full Transporter Pattern pipeline and return file blocks.

    Orchestrates: Blueprint → Decompose → Execute → Assemble → Validate.
    Returns the same list[dict] format as BuilderAgent._parse_file_blocks(),
    ready for execute_approved_build().

    On validation failure, logs warnings but still returns the assembled blocks
    (the downstream test-fix loop in execute_approved_build handles errors).
    On total failure (no chunks succeed), returns an empty list.

    Args:
        spec: BuildSpec describing the build.
        llm_client: LLM client (must support .complete() for deep tier
                    and fast-tier decomposition).
        work_dir: Project root directory.
        codebase_index: Optional CodebaseIndex for import/structure analysis.
        on_event: Optional async callback for HXI events.

    Returns:
        list[dict] of file blocks in _parse_file_blocks() format.
    """
    from probos.cognitive.builder import (
        create_blueprint,
        decompose_blueprint,
        execute_chunks,
        assemble_chunks,
        validate_assembly,
        _emit_transporter_events,
    )

    # Step 1: Create Blueprint
    blueprint = create_blueprint(spec)

    # Step 2: Decompose into chunks
    blueprint = await decompose_blueprint(
        blueprint, llm_client,
        codebase_index=codebase_index,
        work_dir=work_dir,
        on_event=on_event,
    )

    if not blueprint.chunks:
        logger.warning("Transporter: decomposition produced no chunks, aborting")
        return []

    # Step 3: Execute chunks in parallel waves
    blueprint = await execute_chunks(
        blueprint, llm_client,
        work_dir=work_dir,
        on_event=on_event,
    )

    # Step 4: Assemble results
    assembled = assemble_chunks(blueprint)

    if not assembled:
        logger.warning("Transporter: assembly produced no file blocks")
        return []

    # Step 5: Validate
    validation = validate_assembly(blueprint, assembled)

    # Emit HXI events for assembly + validation
    if on_event:
        # Create a minimal runtime-like object for _emit_transporter_events
        # In production this will be the real runtime passed through the API layer
        class _EventEmitter:
            def _emit_event(self, event_type, data):
                import asyncio
                asyncio.ensure_future(on_event(event_type, data))
        await _emit_transporter_events(_EventEmitter(), "", blueprint, assembled, validation)

    if not validation.valid:
        logger.warning(
            "Transporter: validation found %d error(s): %s",
            len(validation.errors),
            "; ".join(e.get("message", "") for e in validation.errors[:3]),
        )
        # Still return blocks — the test-fix loop downstream will catch real issues

    logger.info(
        "Transporter: pipeline complete — %d file blocks, %d/%d chunks succeeded, valid=%s",
        len(assembled),
        sum(1 for r in blueprint.results if r.success),
        len(blueprint.chunks),
        validation.valid,
    )

    return assembled
```

### 3. Update `BuilderAgent.act()` to optionally use Transporter

Modify the existing `act()` method. Currently it calls `self._parse_file_blocks(llm_output)`
on the single LLM response. Add a Transporter path that runs INSTEAD of the single-pass
LLM call when appropriate.

**Important:** The Transporter path needs the LLM client and work_dir, which are on `self`.
The current `act()` gets `llm_output` from `decision` (set in `perceive()`). The Transporter
path needs to be triggered from `perceive()` since that's where the LLM call happens.

**Design:** Add a new method `_transporter_perceive()` that replaces the single LLM call
in `perceive()` with the full Transporter pipeline. The `perceive()` method checks
`_should_use_transporter()` and branches:

In `perceive()`, after the context is built (after the localization step), add a check:

```python
# After context_str is built (around line 1610-1615), before the LLM call:

# Check if Transporter Pattern should be used
total_context = sum(len(v) for v in target_contents.values())
if _should_use_transporter(spec, total_context):
    logger.info("Builder: using Transporter Pattern (%d files, %d chars context)",
                len(spec.target_files), total_context)
    try:
        transporter_blocks = await transporter_build(
            spec=spec,
            llm_client=self._llm_client,
            work_dir=str(self._project_root),
            codebase_index=getattr(self, '_codebase_index', None),
        )
        if transporter_blocks:
            return {
                "action": "transporter_complete",
                "file_changes": transporter_blocks,
                "llm_output": f"[Transporter Pattern: {len(transporter_blocks)} file blocks from parallel chunks]",
            }
        else:
            logger.warning("Builder: Transporter returned no blocks, falling back to single-pass")
            # Fall through to single-pass below
    except Exception as exc:
        logger.warning("Builder: Transporter failed (%s), falling back to single-pass", exc)
        # Fall through to single-pass below
```

Then in `act()`, add a handler for the transporter result before the existing LLM parse:

```python
async def act(self, decision: dict) -> dict:
    """Parse LLM output into file blocks — does NOT write files."""
    if decision.get("action") == "error":
        logger.warning("Builder act: LLM returned error: %s", decision.get("reason"))
        return {"success": False, "error": decision.get("reason")}

    # Transporter Pattern result — blocks already parsed
    if decision.get("action") == "transporter_complete":
        file_changes = decision.get("file_changes", [])
        return {
            "success": True,
            "result": {
                "file_changes": file_changes,
                "llm_output": decision.get("llm_output", ""),
                "change_count": len(file_changes),
            },
        }

    # Original single-pass path
    llm_output = decision.get("llm_output", "")
    # ... rest of existing act() unchanged ...
```

### 4. Store `_project_root` and `_codebase_index` on BuilderAgent

The Transporter needs `work_dir` and optionally `codebase_index`. These should be
stored on the agent at init time.

In `BuilderAgent.__init__()`, after `super().__init__()`:

```python
self._project_root = Path(__file__).resolve().parent.parent.parent
```

The `_codebase_index` can be set externally (runtime sets it after startup
via `agent.add_skill(codebase_skill)`). For now, `transporter_build()` handles
`codebase_index=None` gracefully (decomposer works without it).

The `_llm_client` already exists on CognitiveAgent (set during pool registration).

## Tests

Add a new test class `TestTransporterIntegration` in `tests/test_builder_agent.py`.

### Test imports

Add `transporter_build` and `_should_use_transporter` to the existing import block.

### Test class: `TestShouldUseTransporter` (5 tests)

```python
class TestShouldUseTransporter:
    """Tests for Transporter decision logic (AD-336)."""

    def test_small_build_uses_single_pass(self):
        """Single file, small context → single pass."""
        spec = BuildSpec(title="t", description="d", target_files=["src/foo.py"])
        assert _should_use_transporter(spec, context_size=5000) is False

    def test_many_files_uses_transporter(self):
        """More than 2 target files → Transporter."""
        spec = BuildSpec(title="t", description="d",
                        target_files=["a.py", "b.py", "c.py"])
        assert _should_use_transporter(spec) is True

    def test_large_context_uses_transporter(self):
        """Large context size → Transporter."""
        spec = BuildSpec(title="t", description="d", target_files=["a.py"])
        assert _should_use_transporter(spec, context_size=25000) is True

    def test_impl_plus_tests_uses_transporter(self):
        """Multiple impl + test files → Transporter."""
        spec = BuildSpec(title="t", description="d",
                        target_files=["a.py", "b.py"],
                        test_files=["test_a.py"])
        assert _should_use_transporter(spec) is True

    def test_single_impl_single_test_no_transporter(self):
        """One impl + one test (2 total) → single pass."""
        spec = BuildSpec(title="t", description="d",
                        target_files=["a.py"],
                        test_files=["test_a.py"])
        assert _should_use_transporter(spec) is False
```

### Test class: `TestTransporterBuild` (5 tests)

```python
class TestTransporterBuild:
    """Tests for transporter_build() end-to-end pipeline (AD-336)."""

    def test_full_pipeline_returns_file_blocks(self):
        """transporter_build runs all stages and returns file blocks."""
        spec = BuildSpec(
            title="test build", description="test",
            target_files=["src/foo.py"],
        )
        mock_llm = AsyncMock()
        # Decompose will fail (no proper response) → fallback to 1 chunk
        # Execute will use mock response
        mock_llm.complete.return_value = MagicMock(
            content="===FILE: src/foo.py===\n===CREATE===\ndef foo():\n    return 1\n===END FILE==="
        )
        # The generate method for execute_chunks
        mock_llm.generate = AsyncMock(return_value=MagicMock(
            content="===FILE: src/foo.py===\n===CREATE===\ndef foo():\n    return 1\n===END FILE==="
        ))

        result = asyncio.get_event_loop().run_until_complete(
            transporter_build(spec, mock_llm)
        )
        assert len(result) >= 1
        assert result[0]["mode"] == "create"
        assert "foo" in result[0]["content"]

    def test_returns_empty_on_total_failure(self):
        """Returns empty list when all chunks fail."""
        spec = BuildSpec(title="t", description="d", target_files=["a.py"])
        mock_llm = AsyncMock()
        mock_llm.complete.side_effect = Exception("LLM down")
        mock_llm.generate = AsyncMock(side_effect=Exception("LLM down"))

        result = asyncio.get_event_loop().run_until_complete(
            transporter_build(spec, mock_llm)
        )
        assert result == []

    def test_emits_events_when_callback_provided(self):
        """transporter_build emits events through on_event callback."""
        events = []
        async def capture(event_type, data):
            events.append(event_type)

        spec = BuildSpec(title="t", description="d", target_files=["a.py"])
        mock_llm = AsyncMock()
        mock_llm.complete.side_effect = Exception("fallback")
        mock_llm.generate = AsyncMock(return_value=MagicMock(
            content="===FILE: a.py===\n===CREATE===\nx = 1\n===END FILE==="
        ))

        asyncio.get_event_loop().run_until_complete(
            transporter_build(spec, mock_llm, on_event=capture)
        )
        # Should have decompose + wave + chunk + execution events
        assert "transporter_decomposed" in events

    def test_works_without_on_event(self):
        """transporter_build works with on_event=None (default)."""
        spec = BuildSpec(title="t", description="d", target_files=["a.py"])
        mock_llm = AsyncMock()
        mock_llm.complete.side_effect = Exception("fallback")
        mock_llm.generate = AsyncMock(return_value=MagicMock(
            content="===FILE: a.py===\n===CREATE===\nx = 1\n===END FILE==="
        ))

        result = asyncio.get_event_loop().run_until_complete(
            transporter_build(spec, mock_llm)
        )
        # Should succeed without errors
        assert isinstance(result, list)

    def test_validation_failure_still_returns_blocks(self):
        """When validation finds errors, blocks are still returned."""
        spec = BuildSpec(title="t", description="d", target_files=["a.py"])
        mock_llm = AsyncMock()
        mock_llm.complete.side_effect = Exception("fallback")
        # Return syntactically invalid Python — validation will flag it
        mock_llm.generate = AsyncMock(return_value=MagicMock(
            content="===FILE: a.py===\n===CREATE===\ndef foo(\n===END FILE==="
        ))

        result = asyncio.get_event_loop().run_until_complete(
            transporter_build(spec, mock_llm)
        )
        # Blocks returned even with validation errors (test-fix loop handles it)
        assert len(result) >= 1
```

### Test class: `TestBuilderTransporterIntegration` (2 tests)

```python
class TestBuilderTransporterIntegration:
    """Tests for BuilderAgent.act() Transporter integration (AD-336)."""

    def test_act_handles_transporter_result(self):
        """act() correctly processes transporter_complete action."""
        agent = BuilderAgent.__new__(BuilderAgent)
        agent.agent_id = "test"
        decision = {
            "action": "transporter_complete",
            "file_changes": [{"path": "a.py", "content": "x=1", "mode": "create", "after_line": None}],
            "llm_output": "[Transporter]",
        }
        result = asyncio.get_event_loop().run_until_complete(agent.act(decision))
        assert result["success"] is True
        assert result["result"]["change_count"] == 1

    def test_act_still_handles_single_pass(self):
        """act() still works for non-transporter (single-pass) builds."""
        agent = BuilderAgent.__new__(BuilderAgent)
        agent.agent_id = "test"
        decision = {
            "llm_output": "===FILE: a.py===\n===CREATE===\ndef bar(): pass\n===END FILE===",
        }
        result = asyncio.get_event_loop().run_until_complete(agent.act(decision))
        assert result["success"] is True
        assert result["result"]["change_count"] == 1
```

## Implementation constraints

1. **Backward compatible** — single-pass builds work exactly as before. Transporter is additive.
2. **Graceful fallback** — if Transporter fails at any stage, fall back to single-pass. Never worse than before.
3. **No API changes** — `execute_approved_build()` is NOT modified. It receives `file_changes` from either path identically.
4. **No import changes at module level** — `transporter_build` uses lazy imports from within the same module
   to avoid circular references. Actually since all functions are in the same file, just call them directly.
5. **12 total tests** across 3 test classes (5 + 5 + 2).
6. **Do NOT modify** `execute_approved_build()`, `_parse_file_blocks()`, or any existing tests.
7. **Files to modify:** `src/probos/cognitive/builder.py`, `tests/test_builder_agent.py`.
