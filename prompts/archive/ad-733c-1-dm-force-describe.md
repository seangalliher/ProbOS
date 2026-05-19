# AD-733c-1 — DM-receive force describe

**Status:** Drafted 2026-05-18, awaiting GATE 1.
**Closes (part of):** #675.
**Estimated tests:** +6 pytest.
**Depends on:** AD-733a (`VisionConsumer`, shipped Wave 171), BF-302 (`force` param on `vision_observation`), BF-304 (single-flight lock).

## Problem

The agent's DM reply is grounded in whatever happens to be in `VisionWorkingMemory` at the moment of `render_for_prompt()`. With a 3s supervisor `min_interval` and a static-pose scene, the WM may contain a 20s-old observation when the Captain types "what am I holding?". The reply lags reality.

**Solution:** before the WM is rendered for the DM, force-describe the latest captured frame so the WM contains a fresh entry for THIS message. Single-flight lock (BF-304) keeps cost bounded; 4s timeout means the DM never blocks waiting for the vision LLM.

## Solution overview

1. `VisionConsumer` caches the most recent frame SHA per session (and globally) in a small in-memory dict, updated in `_handle()` BEFORE supervisor admission. This makes the SHA available even when the supervisor would normally drop the frame.
2. New `VisionConsumer.force_describe_current_frame(session_id: str | None = None) -> str | None`. Looks up the cached SHA (per-session if provided, else globally most recent), constructs an internal `IntentMessage` with `force=True`, calls `_process()` directly (no bus broadcast — avoids fan-out), awaits with a 4s timeout, returns the description string or `None` on timeout/missing.
3. `routers/agents.py:agent_chat` calls `force_describe_current_frame()` just BEFORE the AD-733a `render_for_prompt()` scene block injection. Best-effort: 4s timeout → log warning → continue.
4. AD-541b anchored episode is already written inside `_process()`; no change to that path.

### Section 1: VisionConsumer per-session SHA cache + force-describe API

`src/probos/perception/consumer.py`

SEARCH (find the `__init__` end with `self._observer: Any = None`):
```python
        # AD-733b: identity-resolution + proactive-observer state. The hooks
        # are no-ops when the observer is not wired or the captain reference
        # avatar is empty — the AD-733a code path stays intact.
        self._identity_resolved_sessions: set[str] = set()
        self._sessions_with_observations: set[str] = set()
        self._observer: Any = None
```
REPLACE WITH:
```python
        # AD-733b: identity-resolution + proactive-observer state. The hooks
        # are no-ops when the observer is not wired or the captain reference
        # avatar is empty — the AD-733a code path stays intact.
        self._identity_resolved_sessions: set[str] = set()
        self._sessions_with_observations: set[str] = set()
        self._observer: Any = None
        # AD-733c-1: per-session latest-frame SHA cache. Updated in
        # ``_handle`` BEFORE supervisor admission so dropped/throttled frames
        # still register. Used by ``force_describe_current_frame`` to fetch
        # the most recent visible frame on a DM-receive hook. Each value is
        # ``(sha, captured_at)``. Module-scoped per-runtime; cleared in
        # ``reset_working_memories_for_tests``.
        self._latest_frame_by_session: dict[str, tuple[str, float]] = {}
        self._latest_frame_global: tuple[str, float] | None = None
```

SEARCH (find `_handle` start):
```python
    async def _handle(self, msg: IntentMessage) -> IntentResult | None:
        """Bus handler — supervisor-gate, LLM-describe, WM-write, episode-anchor."""
        if msg.intent != self.INTENT_NAME:
            return None
        try:
            await self._process(msg)
```
REPLACE WITH:
```python
    async def _handle(self, msg: IntentMessage) -> IntentResult | None:
        """Bus handler — supervisor-gate, LLM-describe, WM-write, episode-anchor."""
        if msg.intent != self.INTENT_NAME:
            return None
        # AD-733c-1: record the SHA BEFORE supervisor gating so force-describe
        # can fetch it even when the supervisor dropped this frame for
        # low-novelty / throttled reasons.
        try:
            _sha = msg.params.get("attachment_ref")
            _captured_at = float(msg.params.get("captured_at", time.time()))
            _session_id = str(msg.params.get("session_id", ""))
            if isinstance(_sha, str) and _sha:
                if _session_id:
                    self._latest_frame_by_session[_session_id] = (_sha, _captured_at)
                self._latest_frame_global = (_sha, _captured_at)
        except Exception:
            logger.debug("AD-733c-1: latest-frame cache update failed", exc_info=True)
        try:
            await self._process(msg)
```

Now add the public method. SEARCH (find `async def _describe` to anchor):
```python
    async def _describe(self, sha: str) -> str:
        """Call the vision LLM on a single frame. Returns description or empty string."""
```
REPLACE WITH:
```python
    async def force_describe_current_frame(
        self,
        session_id: str | None = None,
        *,
        timeout_s: float = 4.0,
    ) -> str | None:
        """AD-733c-1: synchronously describe the latest cached frame.

        Looks up the most recent frame SHA for ``session_id`` (or globally
        if no session given), runs the standard ``_process`` path with
        ``force=True`` (bypasses the supervisor), and returns the
        description as written to working memory. Tier-2 honest-degrade:
        on timeout / no cached frame / LLM error, returns ``None`` and
        logs at WARNING (not ERROR — the DM still proceeds without the
        fresh frame).

        ``timeout_s`` is a hard wall-clock cap: the caller (DM hook) must
        not block on a slow vision tier. BF-304 single-flight lock means
        spamming this call collapses to one describe per supervisor
        window.
        """
        if session_id and session_id in self._latest_frame_by_session:
            sha, captured_at = self._latest_frame_by_session[session_id]
        elif self._latest_frame_global is not None:
            sha, captured_at = self._latest_frame_global
        else:
            logger.debug(
                "AD-733c-1: force_describe — no cached frame for session=%s",
                str(session_id or "*")[:8],
            )
            return None
        synthetic = IntentMessage(
            intent=self.INTENT_NAME,
            params={
                "attachment_ref": sha,
                "mime": "image/jpeg",
                "captured_at": captured_at,
                "source": "force_describe",
                "session_id": session_id or "",
                "force": True,
            },
        )
        try:
            await asyncio.wait_for(self._process(synthetic), timeout=timeout_s)
        except asyncio.TimeoutError:
            logger.warning(
                "AD-733c-1: force_describe timed out after %.1fs sha=%s",
                timeout_s, sha[:8],
            )
            return None
        except Exception:
            logger.warning(
                "AD-733c-1: force_describe raised for sha=%s; DM proceeds without fresh frame",
                sha[:8], exc_info=True,
            )
            return None
        # Pull the just-written description out of any observer's WM.
        # The describe path wrote the same VisionObservation to every
        # observer's WM, so the first observer's most-recent entry is the
        # description we just produced.
        for agent_id in list(self._observer_agent_ids):
            wm = get_or_create_working_memory(agent_id, capacity=self._wm_capacity)
            entries = list(wm.entries())
            if entries and entries[-1].attachment_ref == sha:
                return entries[-1].description
        return None

    async def _describe(self, sha: str) -> str:
        """Call the vision LLM on a single frame. Returns description or empty string."""
```

SEARCH (find `reset_working_memories_for_tests`):
```python
def reset_working_memories_for_tests() -> None:
    """Test-only — clears the module-level WM registry."""
    _WORKING_MEMORIES.clear()
```
REPLACE WITH:
```python
def reset_working_memories_for_tests() -> None:
    """Test-only — clears the module-level WM registry."""
    _WORKING_MEMORIES.clear()


def _reset_latest_frame_cache_for_tests(consumer: Any) -> None:
    """AD-733c-1 test helper — clears per-consumer latest-frame caches."""
    consumer._latest_frame_by_session.clear()
    consumer._latest_frame_global = None
```

### Section 2: agent_chat DM hook

`src/probos/routers/agents.py` — locate the AD-733a scene injection block at ~line 1932 and prepend the force-describe call.

SEARCH:
```python
    # AD-733a (Wave 171): prepend the agent's current visual context.
    # Confabulation guard (BF-294 lesson): render_for_prompt returns a
    # non-empty "no data" sentinel when the buffer is empty, so the agent
    # never silently invents a scene. Tier-2 — failure logs at debug and
    # drops the visual block; the DM still goes through. The injection is
    # gated on perception.enabled so disabling the subsystem cleanly
    # removes the block from every DM (BF-294: silent-omit is acceptable
    # when the subsystem is off; the agent has no vision expectation).
    try:
        _perception_cfg = getattr(getattr(runtime, "config", None), "perception", None)
        if _perception_cfg is not None and getattr(_perception_cfg, "enabled", False):
            from probos.perception.consumer import get_or_create_working_memory
            _wm = get_or_create_working_memory(agent_id)
            _scene_block = _wm.render_for_prompt()
            if _scene_block:
                message_text = f"{_scene_block}\n\n{message_text}"
    except Exception:
        logger.debug(
            "AD-733a: scene-context injection failed for %s",
            agent_id, exc_info=True,
        )
```
REPLACE WITH:
```python
    # AD-733a (Wave 171): prepend the agent's current visual context.
    # Confabulation guard (BF-294 lesson): render_for_prompt returns a
    # non-empty "no data" sentinel when the buffer is empty, so the agent
    # never silently invents a scene. Tier-2 — failure logs at debug and
    # drops the visual block; the DM still goes through. The injection is
    # gated on perception.enabled so disabling the subsystem cleanly
    # removes the block from every DM (BF-294: silent-omit is acceptable
    # when the subsystem is off; the agent has no vision expectation).
    try:
        _perception_cfg = getattr(getattr(runtime, "config", None), "perception", None)
        if _perception_cfg is not None and getattr(_perception_cfg, "enabled", False):
            # AD-733c-1: force-describe the latest captured frame before
            # rendering the scene block. Best-effort + bounded (4s timeout
            # via VisionConsumer.force_describe_current_frame). When the
            # cache is empty or the LLM is slow, we silently fall back to
            # whatever the WM already contains.
            _consumer = getattr(runtime, "vision_consumer", None)
            if _consumer is not None and getattr(
                _perception_cfg, "dm_force_describe_enabled", True,
            ):
                try:
                    await _consumer.force_describe_current_frame(timeout_s=4.0)
                except Exception:
                    logger.debug(
                        "AD-733c-1: force_describe raised for %s",
                        agent_id, exc_info=True,
                    )
            from probos.perception.consumer import get_or_create_working_memory
            _wm = get_or_create_working_memory(agent_id)
            _scene_block = _wm.render_for_prompt()
            if _scene_block:
                message_text = f"{_scene_block}\n\n{message_text}"
    except Exception:
        logger.debug(
            "AD-733a: scene-context injection failed for %s",
            agent_id, exc_info=True,
        )
```

### Section 3: PerceptionConfig field

`src/probos/config.py` — add `dm_force_describe_enabled` to `PerceptionConfig` next to the existing vision-consumer fields.

SEARCH:
```python
    vision_tier: str = Field(default="vision",
        description="LLM tier name for vision describe calls. AD-742a forward marker for vision_fast split.",
    )

    # AD-733b (Wave 171): Captain reference avatar SHA in AttachmentStore.
```
REPLACE WITH:
```python
    vision_tier: str = Field(default="vision",
        description="LLM tier name for vision describe calls. AD-742a forward marker for vision_fast split.",
    )

    # AD-733c-1 (Wave 172): DM-receive force-describe of the latest cached frame
    # before the agent's reply is composed. 4s wall-clock timeout enforced by
    # VisionConsumer.force_describe_current_frame. Default True so the
    # subsystem benefits from fresh-frame grounding out of the box; operator
    # can disable for cost-discipline experiments.
    dm_force_describe_enabled: bool = Field(default=True,
        description="On every DM, synchronously describe the latest captured frame before composing the reply (4s timeout floor).",
    )

    # AD-733b (Wave 171): Captain reference avatar SHA in AttachmentStore.
```

### Tests

New file: `tests/test_ad733c1_force_describe.py`. Six tests:

1. `test_handle_caches_sha_before_supervisor` — verify `_handle` populates `_latest_frame_by_session` and `_latest_frame_global` even when supervisor drops the frame (use a manually-throttled supervisor).
2. `test_force_describe_returns_description_for_session` — seed cache for a session, call `force_describe_current_frame(session_id)`, assert returned string matches the stubbed LLM response.
3. `test_force_describe_falls_back_to_global` — no session-specific cache, only global → returns description.
4. `test_force_describe_returns_none_when_cache_empty` — empty caches → returns `None`, no LLM call attempted (assert on mock client).
5. `test_force_describe_times_out_gracefully` — stub LLM client that sleeps 10s; `timeout_s=0.5` → returns `None`, no raise. WARNING log captured.
6. `test_agent_chat_dm_hook_calls_force_describe` — integration: build a real-but-minimal runtime, hit `agent_chat`, assert `_consumer.force_describe_current_frame` was called exactly once. Use a `_FakeVisionConsumer` (not MagicMock) per BF-287.

Reuse the `_FakeAttachmentStore` / `_FakeLLMClient` patterns from `tests/test_ad733a_vision_consumer.py`. Do NOT use MagicMock at substrate boundaries.

### What this does NOT change

- `cognitive/dm/reply_pipeline.py` — untouched. The pipeline is post-LLM; force-describe is pre-LLM.
- `VisionSupervisor` / `PerceptualHashStrategy` — untouched. Force path bypasses via `force=True` (BF-302).
- `routers/perception.py` frame intake — untouched. Cache is populated by the existing bus broadcast path.
- AD-731 invariant — preserved. Force path passes SHA refs only; never inline bytes.
- AD-541b anchored episode — still written by `_process()` on the force path (the existing code calls `_anchor_episode` after WM write, regardless of `force`).

### Tracking

- **PROGRESS.md:** append AD-733c-1 entry under Wave 172. Tracker bump = current + 6.
- **DECISIONS.md:** append AD-733c-1 entry (this file is the canonical detail; one paragraph in DECISIONS).
- **roadmap.md:** none — issue #675 stays open until AD-733c-4 closes the umbrella.

### Acceptance criteria

- All 6 new pytest tests pass under `pytest -n 4 --dist=loadfile`.
- Existing 19+1 AD-733a tests still pass (no regression).
- Existing 10 AD-733b tests still pass.
- `routers/agents.py:agent_chat` still passes its existing test suite.
- AD-731 source-scan test still finds zero `b64encode` in perception modules.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-18)

```
grep -n "self._observer: Any = None" src/probos/perception/consumer.py
  113: self._observer: Any = None

grep -n "async def _handle" src/probos/perception/consumer.py
  146: async def _handle(self, msg: IntentMessage) -> IntentResult | None:

grep -n "async def _describe" src/probos/perception/consumer.py
  256: async def _describe(self, sha: str) -> str:

grep -n "reset_working_memories_for_tests" src/probos/perception/consumer.py
  49: def reset_working_memories_for_tests() -> None:

grep -n "AD-733a (Wave 171): prepend" src/probos/routers/agents.py
  1928: # AD-733a (Wave 171): prepend the agent's current visual context.

grep -n "vision_tier: str = Field" src/probos/config.py
  1955: vision_tier: str = Field(default="vision",

grep -n "force.*BF-302" src/probos/perception/consumer.py
  173: # 2) Supervisor gate. BF-302: ``force=True`` in intent params bypasses
```

All SEARCH anchors confirmed present at HEAD. The added `dm_force_describe_enabled` field is introduced by this prompt, so its absence at HEAD is expected.
