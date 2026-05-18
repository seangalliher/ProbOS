# AD-733b — ObserverAgent: proactive scene-introduction + identity hook

**Wave:** 171
**Closes:** [#666](https://github.com/seangalliher/ProbOS/issues/666)
**Depends on:** AD-733a (VisionConsumer + WorkingMemory shipped in the same wave); AD-674 graduated initiative; AD-728c two-budget pattern.
**Estimated tests:** +10 pytest
**Risk:** medium — adds a proactive emission path that can fire DMs without Captain prompting. Bounded by initiative budget + scene-introduction-once-per-session gate.

---

## Problem

AD-733a (this wave) wires `vision_observation` → supervisor → vision LLM → working memory → DM context injection. **Captain must speak first** for the agent to mention the camera scene. The acceptance test ("Captain holds up a glass; Ezri describes it") works the moment Captain types anything, but Ezri does not proactively bring up the visual context.

Issue #666 asks for proactive surfacing. Two conservative v1 triggers:

1. **Scene-introduction trigger** — on the **first non-empty WorkingMemory entry** after a `camera_session_began` event in an active DM session, the agent may proactively send one DM ("I can see you, Captain. You're holding a glass of water — looks empty? Were you about to fill it?"). Fires at most once per camera session.
2. **High-novelty trigger** — when supervisor flags a frame with novelty > 0.5 (a strong scene change) in an active DM session, the agent may emit one DM. Gated by AD-674 graduated initiative budget; capped at 3 emissions per session.

Plus an **identity hook**: on the first non-empty frame after camera enable, the consumer asks the vision LLM "Is the person in this frame the operator (Captain) shown in this reference image?" using the Captain's avatar (if available in identity.db) as the reference. Result populates `VisionObservation.subject_identity` ∈ `{"captain", "unknown", "other"}`. AD-742b forward marker replaces this with face-embedding.

---

## Solution

### Section 1: `src/probos/perception/observer.py` (NEW)

```python
"""AD-733b: ProactiveVisionObserver — emits a DM when a novel scene
warrants surfacing. Bounded by:
  * scene-introduction-once-per-camera-session
  * AD-674 graduated initiative budget (default 3 emissions/session)
  * minimum dwell time between proactive emissions (default 30s)

The observer runs as a follow-up step inside VisionConsumer._process AFTER
the LLM describe has produced a description. It does NOT subscribe to the
bus directly — it shares the consumer's path so frame admission, cost
discipline, and working memory order are preserved.

Tier-2 log-and-degrade: a failed proactive emission never blocks the
working-memory write or the episode anchor.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class _SessionState:
    """Per-(session, agent) emission accounting."""
    introduction_sent: bool = False
    proactive_emissions: int = 0
    last_emission_at: float = 0.0


@dataclass
class ProactiveBudget:
    """AD-674 graduated initiative — visual variant."""
    max_emissions_per_session: int = 3
    min_dwell_seconds: float = 30.0
    novelty_threshold: float = 0.50


class ProactiveVisionObserver:
    """Decides when to emit a proactive DM about a flagged frame."""

    def __init__(
        self,
        runtime: Any,
        *,
        budget: ProactiveBudget | None = None,
    ) -> None:
        self._runtime = runtime
        self._budget = budget or ProactiveBudget()
        # Keyed by (session_id, agent_id). Reset on session_began.
        self._state: dict[tuple[str, str], _SessionState] = {}

    def reset_session(self, session_id: str, agent_id: str) -> None:
        self._state.pop((session_id, agent_id), None)

    async def maybe_emit(
        self,
        *,
        session_id: str,
        agent_id: str,
        observation: Any,  # VisionObservation
        is_first_observation: bool,
    ) -> bool:
        """Return True if a proactive DM was emitted, False otherwise.

        Tier-2: every branch handles exceptions internally; only False
        is returned on any failure.
        """
        try:
            return await self._decide_and_emit(
                session_id=session_id,
                agent_id=agent_id,
                observation=observation,
                is_first_observation=is_first_observation,
            )
        except Exception:
            logger.warning(
                "AD-733b: proactive emission decision failed for agent=%s session=%s",
                agent_id, session_id[:8], exc_info=True,
            )
            return False

    async def _decide_and_emit(
        self,
        *,
        session_id: str,
        agent_id: str,
        observation: Any,
        is_first_observation: bool,
    ) -> bool:
        key = (session_id, agent_id)
        state = self._state.setdefault(key, _SessionState())
        now = time.monotonic()

        # Trigger 1: scene introduction — first frame ever in this session.
        if is_first_observation and not state.introduction_sent:
            state.introduction_sent = True
            state.proactive_emissions += 1
            state.last_emission_at = now
            await self._dispatch_proactive_dm(
                agent_id=agent_id,
                session_id=session_id,
                reason="scene_introduction",
                observation=observation,
            )
            return True

        # Trigger 2: high-novelty mid-session.
        if observation.novelty_score < self._budget.novelty_threshold:
            return False
        if state.proactive_emissions >= self._budget.max_emissions_per_session:
            logger.debug(
                "AD-733b: proactive budget exhausted for agent=%s session=%s",
                agent_id, session_id[:8],
            )
            return False
        if now - state.last_emission_at < self._budget.min_dwell_seconds:
            return False

        state.proactive_emissions += 1
        state.last_emission_at = now
        await self._dispatch_proactive_dm(
            agent_id=agent_id,
            session_id=session_id,
            reason="high_novelty",
            observation=observation,
        )
        return True

    async def _dispatch_proactive_dm(
        self,
        *,
        agent_id: str,
        session_id: str,
        reason: str,
        observation: Any,
    ) -> None:
        """Send a proactive DM to the agent so the agent's LLM composes the
        actual user-visible message. We do NOT compose user-facing text
        here — the agent does, via its own voice profile, using the
        observation in its working memory.
        """
        from probos.types import IntentMessage
        # The agent_chat path injects the WM block automatically (AD-733a
        # Section 6). We send a synthesized user-turn telling the agent the
        # camera just turned on (introduction) or a new scene appeared.
        if reason == "scene_introduction":
            user_turn = (
                "[SYSTEM-INITIATED: camera just turned on. You may briefly greet "
                "the Captain and describe what you observe — once, then wait for "
                "the Captain's reply. Keep it under 60 words.]"
            )
        else:
            user_turn = (
                "[SYSTEM-INITIATED: the scene in front of you changed materially. "
                "If — and only if — the change is worth mentioning to the Captain, "
                "say one short observation. Otherwise stay silent by returning an empty reply.]"
            )

        intent = IntentMessage(
            intent="direct_message",
            params={
                "text": user_turn,
                "from": "hxi_profile",
                "session": True,
                "is_proactive_vision": True,
                "session_id": session_id,
                "proactive_reason": reason,
            },
            target_agent_id=agent_id,
            ttl_seconds=60.0,
        )
        try:
            await self._runtime.intent_bus.send(intent)
            logger.info(
                "AD-733b: proactive vision DM dispatched agent=%s reason=%s novelty=%.2f",
                agent_id, reason, observation.novelty_score,
            )
        except Exception:
            logger.warning(
                "AD-733b: proactive DM dispatch failed agent=%s reason=%s",
                agent_id, reason, exc_info=True,
            )


__all__ = ["ProactiveVisionObserver", "ProactiveBudget"]
```

### Section 2: Identity hook in `perception/consumer.py`

Extend `_describe` to populate `subject_identity` on the **first frame per camera session** using a one-shot LLM prompt. This adds ONE extra vision LLM call per session — Captain authorized the cost.

```
===SEARCH===
        # 4) Write to every registered observer's WorkingMemory.
        from probos.perception.working_memory import VisionObservation
        obs = VisionObservation(
            timestamp=time.time(),
            attachment_ref=sha,
            description=description[:400],
            novelty_score=decision.novelty_score,
            subject_identity="unknown",  # AD-733b populates
            session_id=session_id,
        )
===REPLACE===
        # 4) Write to every registered observer's WorkingMemory.
        from probos.perception.working_memory import VisionObservation

        # AD-733b: identity hook — once per session, ask the vision LLM
        # whether the person in frame matches the Captain reference avatar.
        # Skipped when no reference image is available; identity stays "unknown".
        subject_identity = "unknown"
        if session_id and session_id not in self._identity_resolved_sessions:
            subject_identity = await self._resolve_subject_identity(sha)
            self._identity_resolved_sessions.add(session_id)

        obs = VisionObservation(
            timestamp=time.time(),
            attachment_ref=sha,
            description=description[:400],
            novelty_score=decision.novelty_score,
            subject_identity=subject_identity,
            session_id=session_id,
        )
===END REPLACE===
```

Add to `VisionConsumer.__init__`:

```python
self._identity_resolved_sessions: set[str] = set()
self._observer = None  # late-bound by wire_proactive_observer
```

Add two methods on `VisionConsumer`:

```python
async def _resolve_subject_identity(self, sha: str) -> str:
    """Single-shot LLM identity check. Returns 'captain' | 'unknown' | 'other'."""
    try:
        # Reference image: Captain's avatar from identity.db (best-effort).
        captain_avatar_sha = self._lookup_captain_avatar_ref()
        if not captain_avatar_sha:
            return "unknown"

        from probos.cognitive.vision_dispatch import build_multimodal_messages
        from probos.routers.chat import _get_attachment_store
        store = _get_attachment_store(self._runtime)

        async def _mime_lookup(content_hash: str) -> str | None:
            return await store.mime_for(content_hash)

        messages, image_ids, _ = await build_multimodal_messages(
            prompt=(
                "Two images follow. The first is a reference photo of the operator "
                "(the Captain). The second is a live camera frame. Reply with EXACTLY "
                "one word, lowercase: 'captain' if the live frame contains the operator, "
                "'other' if it contains a different person, 'unknown' if no person is "
                "clearly visible or the comparison is ambiguous."
            ),
            attachment_ids=[captain_avatar_sha, sha],
            store=store,
            mime_lookup=_mime_lookup,
            text_extraction_max_bytes=0,
            pdf_extraction_enabled=False,
        )
        if len(image_ids) < 2:
            return "unknown"

        request = LLMRequest(
            prompt="",
            messages=messages,
            tier=self._tier,
            max_tokens=8,
            temperature=0.0,
        )
        response = await asyncio.wait_for(
            self._runtime.llm_client.complete(request),
            timeout=self._timeout,
        )
        word = (response.content or "").strip().lower().split()[:1]
        if word and word[0] in ("captain", "other", "unknown"):
            return word[0]
        return "unknown"
    except Exception:
        logger.debug("AD-733b: identity resolve failed for sha=%s", sha[:8], exc_info=True)
        return "unknown"

def _lookup_captain_avatar_ref(self) -> str | None:
    """Best-effort lookup of the Captain's reference avatar SHA.

    v1 strategy: look for a known config field
    runtime.config.perception.captain_avatar_ref. AD-742b will replace
    with proper face-embedding enrollment.
    """
    cfg = getattr(self._runtime.config, "perception", None)
    if cfg is None:
        return None
    ref = getattr(cfg, "captain_avatar_ref", "")
    return ref if isinstance(ref, str) and ref else None
```

Add to `PerceptionConfig` (Section 1 of THIS prompt):

```
    # AD-733b (Wave 171): Captain reference avatar SHA in AttachmentStore.
    # v1 manual config — AD-742b replaces with face-embedding enrollment.
    captain_avatar_ref: str = Field(default="",
        description="SHA-256 of a reference photo of the Captain in AttachmentStore. Empty disables identity recognition.",
    )

    # AD-733b: proactive observer budget.
    proactive_observer_enabled: bool = Field(default=True,
        description="Allow the agent to proactively surface novel visual scenes in a DM.",
    )
    proactive_max_emissions: int = Field(default=3, ge=0, le=20,
        description="Maximum proactive vision DMs per session.",
    )
    proactive_dwell_seconds: float = Field(default=30.0, ge=5.0, le=600.0,
        description="Minimum seconds between consecutive proactive vision DMs.",
    )
    proactive_novelty_threshold: float = Field(default=0.50, ge=0.0, le=1.0,
        description="Minimum novelty score for a high-novelty proactive trigger (separate from supervisor admission threshold).",
    )
```

### Section 3: Wire observer into VisionConsumer

After the WorkingMemory write in `_process`, call the observer. Add a wiring helper:

```
===SEARCH===
        # 5) Anchor an episode (AD-541b — importance=6, lower than camera_began=8).
        await self._anchor_episode(sha, description, decision.novelty_score, session_id)
===REPLACE===
        # 5) Anchor an episode (AD-541b — importance=6, lower than camera_began=8).
        await self._anchor_episode(sha, description, decision.novelty_score, session_id)

        # 6) AD-733b: proactive observer — may emit one DM per observer if
        # the scene-introduction or high-novelty trigger fires. Tier-2:
        # never blocks subsequent frames. The "first observation in session"
        # signal is tracked here via a session-scoped set; per-agent emission
        # accounting lives inside the observer.
        if self._observer is not None and session_id:
            first_for_session = session_id not in self._sessions_with_observations
            if first_for_session:
                self._sessions_with_observations.add(session_id)
            for agent_id in list(self._observer_agent_ids):
                await self._observer.maybe_emit(
                    session_id=session_id,
                    agent_id=agent_id,
                    observation=obs,
                    is_first_observation=first_for_session,
                )
===END REPLACE===
```

Add to `VisionConsumer.__init__`:
```python
self._sessions_with_observations: set[str] = set()
```

Add a wiring method:
```python
def wire_proactive_observer(self, observer: Any) -> None:
    """Attach the ProactiveVisionObserver. Idempotent."""
    self._observer = observer
```

### Section 4: Startup wiring extension

Extend the `finalize.py` block from AD-733a Section 5:

```python
# After consumer.subscribe():
if _perception_cfg.proactive_observer_enabled:
    from probos.perception.observer import ProactiveVisionObserver, ProactiveBudget
    observer = ProactiveVisionObserver(
        runtime,
        budget=ProactiveBudget(
            max_emissions_per_session=_perception_cfg.proactive_max_emissions,
            min_dwell_seconds=_perception_cfg.proactive_dwell_seconds,
            novelty_threshold=_perception_cfg.proactive_novelty_threshold,
        ),
    )
    consumer.wire_proactive_observer(observer)
    runtime.vision_observer = observer
    logger.info("AD-733b: ProactiveVisionObserver wired")
```

### Section 5: Tests — `tests/test_ad733b_proactive_observer.py` (NEW)

10 cases:

1. `test_scene_introduction_fires_on_first_observation` — first frame in session → 1 DM dispatched with reason=scene_introduction.
2. `test_scene_introduction_fires_only_once_per_session` — second frame in same session → no second scene-intro DM (high-novelty path may still fire).
3. `test_high_novelty_emits_dm` — novelty=0.7, past dwell window, budget available → 1 DM dispatched with reason=high_novelty.
4. `test_low_novelty_blocks_emission` — novelty=0.3 → no DM.
5. `test_dwell_window_blocks_consecutive_emissions` — two high-novelty frames 5s apart, dwell=30s → only first emits.
6. `test_budget_exhaustion_blocks_emission` — max_emissions=2, send 3 high-novelty → only 2 fire.
7. `test_session_reset_clears_state` — `reset_session(sid, aid)` → next frame fires scene_introduction again.
8. `test_identity_resolves_captain` — vision LLM returns "captain" → observation.subject_identity == "captain".
9. `test_identity_resolves_unknown_when_no_reference` — no captain_avatar_ref configured → subject_identity stays "unknown", no LLM call.
10. `test_proactive_disabled_no_emissions` — `proactive_observer_enabled=False` → no observer wired, no DMs ever.

Mock `runtime.llm_client.complete` and `runtime.intent_bus.send` at the service boundary only. Use a real `_SessionState` and real `VisionObservation` instances.

---

## What This Does NOT Change

- VisionConsumer's frame-admission, LLM-describe, working-memory-write order.
- DmReplyPipeline.
- AD-674 graduated initiative core — we only add a visual variant of the budget.
- Identity-by-face-embedding (AD-742b forward marker).
- AD-733a's `subject_identity` field default of `"unknown"`.

---

## Tracking

- PROGRESS.md "Wave 171" — AD-733b row.
- roadmap.md — close #666; reference AD-742b forward marker for face-embedding.
- DECISIONS.md — paragraph on the two-trigger v1 design + AD-742b deferral rationale.

---

## Acceptance Criteria

- All 10 new tests pass.
- AD-733a tests still pass.
- Full gate green.
- AD-731 invariant: identity hook reads bytes from AttachmentStore by SHA, NEVER inline.
- Manual smoke: enable camera → first frame triggers scene-intro DM from the configured crew agent.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-17)

| Claim | Verification |
|---|---|
| `IntentMessage(intent="direct_message", params=..., target_agent_id=..., ttl_seconds=...)` | `src/probos/routers/agents.py:1940-1945` |
| `runtime.intent_bus.send(intent)` returns IntentResult | `src/probos/routers/agents.py:1980` |
| AD-733a `VisionObservation` carries `subject_identity: str = "unknown"` | `prompts/ad-733a-vision-consumer.md` Section 2 |
| `build_multimodal_messages` accepts a list of attachment_ids (multiple images) | `src/probos/cognitive/vision_dispatch.py:158` |
| `_get_attachment_store(runtime)` returns the per-runtime AttachmentStore | `src/probos/routers/agents.py:1726` |
| `LLMRequest(prompt="", messages=..., tier=..., max_tokens=...)` | `src/probos/types.py:227-245` |
| `PerceptionConfig` extensible via Pydantic Field with ge/le validators | `src/probos/config.py:1920+` (CameraStreamConfig precedent at 1915-1919) |
| `runtime.config.perception` access pattern | `src/probos/routers/perception.py:97` |
