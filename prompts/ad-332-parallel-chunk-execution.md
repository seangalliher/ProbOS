# AD-332: Parallel Chunk Execution — Matter Stream

*"The matter stream carries deconstructed molecules through the pattern buffer in parallel streams. Each stream reconstructs independently — but all must converge on the same target."*

AD-332 adds the parallel execution engine to the Transporter Pattern. Given a decomposed `BuildBlueprint` (chunks populated by AD-331), it executes each chunk as an independent LLM generation call. Independent chunks run in parallel via `asyncio.gather()`, while dependent chunks wait for their prerequisites. Each call uses a focused prompt containing only that chunk's context — not the full codebase.

The result is a set of `ChunkResult` objects stored on the blueprint, ready for assembly (AD-333). This is where the biological "peripheral processing" principle is realized: multiple cheap focused calls replace one expensive monolithic call, the same way the visual cortex processes different parts of the visual field in parallel.

**Current AD count:** AD-336. This prompt implements AD-332.
**Current test count:** 2,003 pytest + 30 vitest.

---

## Pre-Build Audit

Read these files before writing any code:

1. `src/probos/cognitive/builder.py` — full file. Focus on:
   - `ChunkSpec` (lines 66-81), `ChunkResult` (lines 84-100), `BuildBlueprint` (lines 103-170) — data structures this AD populates
   - `BuildBlueprint.get_ready_chunks()` (lines 154-170) — drives the execution loop
   - `BuilderAgent.instructions` (lines 547-589) — the LLM instruction format. Chunk prompts reuse this format per-chunk
   - `BuilderAgent._parse_file_blocks()` (lines 922-980) — chunk LLM output is parsed with this same parser
   - `decompose_blueprint()` (lines 260-442) — produces the chunks this AD executes
2. `src/probos/types.py` — read `LLMRequest` (lines 186-195), `LLMResponse` (lines 197-208) for LLM call pattern
3. `tests/test_builder_agent.py` — full file, especially `TestDecomposeBlueprint` (most recent test class) for async test patterns

---

## What To Build

### Step 1: Add the `execute_chunks()` async function (AD-332)

**File:** `src/probos/cognitive/builder.py`

Add a new module-level async function **after** `decompose_blueprint()` (after line 442) and **before** the git helpers section (before line 445). This is the Matter Stream.

```python
async def execute_chunks(
    blueprint: BuildBlueprint,
    llm_client: Any,
    per_chunk_timeout: float = 120.0,
    max_retries: int = 1,
) -> BuildBlueprint:
    """Execute all chunks in a decomposed BuildBlueprint in parallel (Matter Stream).

    Respects chunk dependency ordering: independent chunks run concurrently,
    dependent chunks wait for their prerequisites to complete.

    Args:
        blueprint: Blueprint with .chunks populated by decompose_blueprint().
        llm_client: LLM client for deep-tier generation.
        per_chunk_timeout: Timeout per chunk LLM call in seconds.
        max_retries: Max retry attempts per failed chunk (0 = no retries).

    Returns:
        The same blueprint with .results populated.
    """
```

**Implementation details:**

**1a. Execution loop using `get_ready_chunks()`**

The loop runs waves of parallel execution. Each wave executes all chunks whose dependencies are satisfied, then records completions and runs the next wave:

```python
    completed: set[str] = {}  # chunk_ids that have finished (success or final failure)
    results: dict[str, ChunkResult] = {}  # chunk_id -> result

    while True:
        ready = blueprint.get_ready_chunks(completed)
        if not ready:
            break  # No more chunks can be scheduled

        # Execute all ready chunks in parallel
        wave_tasks = [
            _execute_single_chunk(chunk, blueprint, llm_client, per_chunk_timeout, max_retries)
            for chunk in ready
        ]
        wave_results = await asyncio.gather(*wave_tasks, return_exceptions=True)

        # Collect results
        for chunk, result in zip(ready, wave_results):
            if isinstance(result, Exception):
                result = ChunkResult(
                    chunk_id=chunk.chunk_id,
                    success=False,
                    error=str(result),
                    confidence=1,
                )
            results[chunk.chunk_id] = result
            completed.add(chunk.chunk_id)

    # Store results on blueprint in chunk order
    blueprint.results = [
        results.get(c.chunk_id, ChunkResult(chunk_id=c.chunk_id, success=False, error="not executed"))
        for c in blueprint.chunks
    ]

    success_count = sum(1 for r in blueprint.results if r.success)
    total = len(blueprint.results)
    logger.info("Matter Stream: %d/%d chunks succeeded", success_count, total)

    return blueprint
```

Note: `completed` should be initialized as `set()` not `{}` (the code comment above has a typo showing `{}` — use `set()`).

---

### Step 2: Add the `_execute_single_chunk()` helper

**File:** `src/probos/cognitive/builder.py`

Add this helper **before** `execute_chunks()`:

```python
async def _execute_single_chunk(
    chunk: ChunkSpec,
    blueprint: BuildBlueprint,
    llm_client: Any,
    timeout: float,
    max_retries: int,
) -> ChunkResult:
    """Execute a single chunk's LLM generation with timeout and retry.

    Builds a focused prompt from the chunk's context and spec,
    sends it to the deep LLM tier, and parses the output.
    """
    spec = blueprint.spec

    # Build chunk-specific prompt
    prompt = _build_chunk_prompt(chunk, blueprint)

    # System prompt reuses the Builder's instructions format
    system_prompt = (
        "You are the Builder Agent for ProbOS, generating code for one specific chunk "
        "of a larger build. Generate ONLY what this chunk asks for — nothing else.\n\n"
        "OUTPUT FORMAT:\n"
        "For new files:\n"
        "===FILE: path/to/file.py===\n"
        "<complete file contents>\n"
        "===END FILE===\n\n"
        "For modifications to existing files:\n"
        "===MODIFY: path/to/file.py===\n"
        "===SEARCH===\n<exact existing code>\n===REPLACE===\n"
        "<replacement code>\n===END REPLACE===\n===END MODIFY===\n\n"
        "After the code blocks, add a brief DECISIONS section explaining your choices, "
        "and rate your CONFIDENCE (1-5) based on how much context you had:\n"
        "5=full contracts+reference, 4=contracts only, 3=description only, "
        "2=minimal context, 1=near-blind.\n\n"
        "DECISIONS: <your rationale>\n"
        "CONFIDENCE: <1-5>"
    )

    last_error = ""
    for attempt in range(1 + max_retries):
        try:
            request = LLMRequest(
                prompt=prompt if attempt == 0 else prompt + f"\n\n(Previous attempt failed: {last_error})",
                system_prompt=system_prompt,
                tier="deep",
                temperature=0.0,
            )

            response = await asyncio.wait_for(
                llm_client.complete(request),
                timeout=timeout,
            )

            if response.error:
                last_error = response.error
                logger.warning(
                    "Chunk %s attempt %d: LLM error: %s",
                    chunk.chunk_id, attempt + 1, response.error,
                )
                continue

            # Parse the response
            return _parse_chunk_response(chunk, response)

        except asyncio.TimeoutError:
            last_error = f"timeout after {timeout}s"
            logger.warning("Chunk %s attempt %d: %s", chunk.chunk_id, attempt + 1, last_error)
        except Exception as exc:
            last_error = str(exc)
            logger.warning("Chunk %s attempt %d: error: %s", chunk.chunk_id, attempt + 1, exc)

    # All attempts exhausted
    return ChunkResult(
        chunk_id=chunk.chunk_id,
        success=False,
        error=f"Failed after {1 + max_retries} attempts: {last_error}",
        confidence=1,
    )
```

---

### Step 3: Add the `_build_chunk_prompt()` helper

**File:** `src/probos/cognitive/builder.py`

Add this helper **before** `_execute_single_chunk()`:

```python
def _build_chunk_prompt(chunk: ChunkSpec, blueprint: BuildBlueprint) -> str:
    """Build the LLM prompt for a single chunk.

    Includes only the chunk's required context, not the full codebase.
    """
    spec = blueprint.spec
    parts: list[str] = [
        f"# Chunk: {chunk.description}",
        f"Part of build: {spec.title}",
        f"AD Number: AD-{spec.ad_number}" if spec.ad_number else "",
        f"\n## What to Generate\n{chunk.what_to_generate}",
        f"Target file: {chunk.target_file}",
    ]

    if chunk.expected_output:
        parts.append(f"\n## Expected Output\n{chunk.expected_output}")

    if chunk.constraints:
        parts.append("\n## Constraints\n" + "\n".join(f"- {c}" for c in chunk.constraints))

    # Add chunk-specific context (L1-L3 abstractions from _build_chunk_context)
    if chunk.required_context:
        parts.append("\n## Context")
        parts.extend(chunk.required_context)

    # Add results from dependency chunks (so this chunk can reference their output)
    if chunk.depends_on and blueprint.results:
        dep_results: list[str] = []
        for dep_id in chunk.depends_on:
            for result in blueprint.results:
                if result.chunk_id == dep_id and result.success:
                    dep_results.append(
                        f"--- {dep_id}: {result.output_signature} ---\n"
                        f"{result.generated_code[:2000]}"  # Cap at 2000 chars per dep
                    )
        if dep_results:
            parts.append("\n## Completed Dependency Chunks\n" + "\n".join(dep_results))

    return "\n".join(p for p in parts if p)
```

---

### Step 4: Add the `_parse_chunk_response()` helper

**File:** `src/probos/cognitive/builder.py`

Add this helper **before** `_build_chunk_prompt()`:

```python
def _parse_chunk_response(chunk: ChunkSpec, response: Any) -> ChunkResult:
    """Parse an LLM response into a ChunkResult.

    Extracts generated code (file blocks), decisions rationale,
    confidence score, and output signature.
    """
    content = response.content or ""

    # Extract decisions rationale
    decisions = ""
    decisions_match = re.search(r"DECISIONS:\s*(.+?)(?=\nCONFIDENCE:|\Z)", content, re.DOTALL)
    if decisions_match:
        decisions = decisions_match.group(1).strip()

    # Extract confidence score
    confidence = 3  # default
    confidence_match = re.search(r"CONFIDENCE:\s*(\d)", content)
    if confidence_match:
        confidence = max(1, min(5, int(confidence_match.group(1))))

    # Extract file blocks to use as generated_code
    # Reuse the existing parser to validate the output has parseable blocks
    file_blocks = BuilderAgent._parse_file_blocks(content)
    has_code = len(file_blocks) > 0

    # Build output signature from file blocks
    output_sig_parts: list[str] = []
    for block in file_blocks:
        if block["mode"] == "create":
            output_sig_parts.append(f"CREATE {block['path']}")
        else:
            output_sig_parts.append(f"MODIFY {block['path']} ({len(block.get('replacements', []))} replacements)")
    output_signature = "; ".join(output_sig_parts) if output_sig_parts else ""

    return ChunkResult(
        chunk_id=chunk.chunk_id,
        success=has_code,
        generated_code=content,  # Full LLM output — file blocks + rationale
        decisions=decisions,
        output_signature=output_signature,
        confidence=confidence,
        error="" if has_code else "No file blocks found in LLM output",
        tokens_used=response.tokens_used if hasattr(response, "tokens_used") else 0,
    )
```

---

### Step 5: Write tests

**File:** `tests/test_builder_agent.py`

Add new test classes. Import `execute_chunks`, `_execute_single_chunk`, `_build_chunk_prompt`, `_parse_chunk_response` from `probos.cognitive.builder`.

Use the same inline `_MockLLM` pattern from AD-331 tests (or reuse if it already exists). If a `_MockLLM` class already exists in the test file from AD-331, reuse it. Otherwise define one:

```python
class _MockLLM:
    """Minimal mock for chunk execution tests."""
    def __init__(self, response_text: str, error: str = ""):
        self._text = response_text
        self._error = error

    async def complete(self, request):
        from probos.types import LLMResponse
        if self._error:
            return LLMResponse(content="", error=self._error)
        return LLMResponse(content=self._text, tokens_used=100)
```

**5a. `TestBuildChunkPrompt` class** — 3 tests:

1. `test_basic_prompt` — ChunkSpec with description, target_file, what_to_generate. Verify prompt contains "# Chunk:", target file, what_to_generate
2. `test_with_context` — ChunkSpec with `required_context=["## Interface Contracts\ndef foo(): ..."]`. Verify "## Context" and the contract appear in the prompt
3. `test_with_constraints` — ChunkSpec with `constraints=["must be async"]`. Verify "## Constraints" and the constraint appear

**5b. `TestParseChunkResponse` class** — 4 tests:

1. `test_success_with_file_block` — Response content includes `===FILE: src/foo.py===\ndef foo(): pass\n===END FILE===\nDECISIONS: simple function\nCONFIDENCE: 4`. Verify: `success=True`, `confidence=4`, `decisions="simple function"`, `output_signature` contains "CREATE src/foo.py"
2. `test_no_file_blocks` — Response content is just text with no file markers. Verify: `success=False`, `error` mentions "No file blocks"
3. `test_confidence_clamped` — Response with `CONFIDENCE: 9`. Verify: clamped to 5. Response with `CONFIDENCE: 0`. Verify: clamped to 1.
4. `test_modify_block` — Response with a `===MODIFY:===` block. Verify: `success=True`, `output_signature` contains "MODIFY"

**5c. `TestExecuteSingleChunk` class** — 3 tests (async):

1. `test_success` — MockLLM returns valid file block output. Verify: `ChunkResult.success=True`, `generated_code` contains the file block, `tokens_used=100`
2. `test_timeout` — Use a mock that sleeps longer than timeout. Create a mock that delays:
    ```python
    class _SlowLLM:
        async def complete(self, request):
            await asyncio.sleep(10)
            return LLMResponse(content="")
    ```
    Call with `timeout=0.1`. Verify: `success=False`, `error` contains "timeout"
3. `test_retry_on_error` — MockLLM that returns error on first call, success on second. Use a counter-based mock:
    ```python
    class _RetryLLM:
        def __init__(self):
            self.calls = 0
        async def complete(self, request):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(content="", error="rate_limit")
            return LLMResponse(content="===FILE: src/f.py===\npass\n===END FILE===\nDECISIONS: retry worked\nCONFIDENCE: 3")
    ```
    Call with `max_retries=1`. Verify: `success=True` (succeeded on retry)

**5d. `TestExecuteChunks` class** — 5 tests (async):

1. `test_independent_chunks_parallel` — Blueprint with 3 independent chunks (no deps). MockLLM returns valid output for all. Verify: all 3 results present, all `success=True`, blueprint.results has length 3

2. `test_dependent_chunks_ordered` — Blueprint with chunk-0 (no deps) and chunk-1 (`depends_on=["chunk-0"]`). MockLLM returns valid output. Verify: both succeed, chunk-1 prompt includes dependency output from chunk-0 (check by inspecting that `_build_chunk_prompt` with populated results would include the dep section — or just verify both ChunkResults are present and successful)

3. `test_partial_success` — Blueprint with 2 chunks. MockLLM returns valid output for first, error for second. Verify: blueprint.results has 2 entries, first `success=True`, second `success=False`. The function doesn't raise — partial success is OK.

4. `test_empty_chunks` — Blueprint with no chunks. Verify: returns immediately, blueprint.results is empty

5. `test_all_failures` — MockLLM always returns error. Verify: all results have `success=False`

---

## Constraints

- **Deep-tier LLM for generation** — chunk execution uses `tier="deep"` (expensive model for code quality). Only the decomposer (AD-331) uses fast tier
- **Do NOT modify existing methods** — `perceive()`, `act()`, `execute_approved_build()`, `decompose_blueprint()` remain unchanged. Integration comes in AD-336
- **Partial success is OK** — if 2 of 3 chunks succeed, that's a valid result. The assembler (AD-333) and validator (AD-334) handle partial outputs. `execute_chunks()` never raises on chunk failure
- **Timeout per chunk, not total** — each chunk gets its own timeout via `asyncio.wait_for()`. A slow chunk doesn't block other waves
- **No new files** — everything in `builder.py` and `test_builder_agent.py`
- **15 new tests** — 3 + 4 + 3 + 5 = 15 tests

---

## Verification

After completing all steps:

1. Run `python -m pytest tests/test_builder_agent.py -v` — all existing + new tests pass
2. Run `python -m pytest tests/ -x --timeout=30` — full test suite passes (no regressions)
3. Verify imports: `python -c "from probos.cognitive.builder import execute_chunks, _execute_single_chunk, _build_chunk_prompt, _parse_chunk_response; print('OK')"`
