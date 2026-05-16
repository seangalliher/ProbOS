# AD-728c — Agent-initiated render self-check with contextual rate limits

**Status:** Draft for Wave 164
**Dependencies:** AD-728 ✅ (Wave 163, ships `verify_render_coherence` + `RenderCoherenceResult`), AD-722a-1 ✅ (`VisionLLMRateLimit`), AD-723a-3 ✅ (SensoriumEntry `injection_zone` / `wrapper`), AD-722 ✅ (`mark_reply_emitted` / `last_reply_emitted_at`), AD-731 (image-bytes-as-refs invariant), AD-727 safety inheritance.
**Closes:** (gh issue filed during Wave 163 closeout — title "AD-728c: Agent-initiated render self-check with contextual rate limits")
**Estimated tests:** 12 pytest
**Highest AD before this prompt:** AD-738 (per `PROGRESS.md:10`). AD-728c is a sub-AD of AD-728, no new top-level number consumed.

## Problem

AD-728 ships the vision-LLM render-coherence mirror with three triggers:

1. `captain_command` — live, via `/verify-render <agent_id>` slash command.
2. `divergence_followup` — gated by `cfg.avatars.render_verification_followup_enabled`, default OFF.
3. `agent_initiated_stub` — **hard-rejected** in `src/probos/avatars/render_verification.py:115-117` with `skipped_reason="agent_initiated_disabled"`. The path exists "so future AD flips the gate."

Counselor reported during a live conversation: *"I get telemetry, not perception. I have no way to know if what's rendering on your end actually matches those parameters."*

Captain authorized closing the gap with this constraint: *"Like a person looking in a mirror — they don't do it constantly. Configurable rate limits. An agent actively communicating with a human may want to check before the interaction and periodically during the conversation."*

## Solution overview

Flip the `agent_initiated_stub` trigger from hard-reject to a gated, rate-limited path. REUSE the existing `verify_render_coherence` callsite — do NOT duplicate the vision-LLM call. The new behavior is:

1. New `CognitiveAgent.check_own_render(reason: str | None = None)` async method that agents call from their instructions when they want to "look in the mirror."
2. **Two-budget rate limit**: a per-hour budget AND a per-active-conversation budget; the active-conversation budget applies INSTEAD OF the hourly budget when the agent has a live DM (not additive). The hourly budget is the fallback when the agent is NOT in an active conversation.
3. **Working-memory injection**: every result (coherent, divergent, AND rate-limited) becomes a `WorkingMemoryEntry` (category `observation`) so the agent's next LLM call sees the mirror outcome. This diverges from AD-728's cost discipline on the SENSORIUM side: agent-initiated coherent observations ARE surfaced to the agent's own working memory, because trust-building (the mirror confirms my warm modulation looked warm) is the entire point of letting an agent self-check.
4. **Event-bus emission remains AD-728's rule**: only divergent observations emit `EventType.RENDER_DIVERGENCE_OBSERVED` to the bus. AD-728c adds NO new event types.
5. Three new config knobs on `AvatarsConfig`, all default-OFF / conservative.

## Section 0: No new event types

This AD reuses `EventType.RENDER_DIVERGENCE_OBSERVED` (AD-728). No edits to `src/probos/events.py`.

## Section 1: Config

Extend `AvatarsConfig` (`src/probos/config.py`) immediately after the existing `render_verification_followup_enabled` field (currently `config.py:1123`).

```python
# AD-728c: agent-initiated render self-check (default-OFF transitional).
render_self_check_enabled: bool = Field(
    default=False,
    description=(
        "AD-728c: flip agent_initiated_stub trigger from hard-reject to "
        "a gated, rate-limited self-check. Default OFF; flip after "
        "AD-728 telemetry confirms vision-tier cost is bounded."
    ),
)
render_self_check_max_per_hour_per_agent: int = Field(
    default=3,
    ge=0,
    description=(
        "AD-728c: per-agent hourly cap for agent-initiated render "
        "self-checks. Applies when the agent is NOT in an active "
        "conversation. 0 disables. Uses the AD-722a-1 "
        "VisionLLMRateLimit primitive under scope "
        "'render_self_check_hour'."
    ),
)
render_self_check_max_per_active_conversation: int = Field(
    default=2,
    ge=0,
    description=(
        "AD-728c: per-agent budget within a single active conversation "
        "window. Pattern: 'before reply + 1 mid-conversation'. Applies "
        "INSTEAD OF the hourly budget while the agent is in an active "
        "conversation. 0 disables self-check during active conversations."
    ),
)
render_self_check_active_window_seconds: int = Field(
    default=600,
    ge=0,
    description=(
        "AD-728c: seconds since the agent's last reply emission to "
        "consider it 'in an active conversation' for self-check budget "
        "selection. Default 600s = 10 minutes. Uses CognitiveAgent."
        "last_reply_emitted_at (AD-722)."
    ),
)
```

**Verify-first floor:** the new fields are siblings of `render_verification_*` (which sit at `config.py:1107-1132`); do NOT introduce a new sub-config class. Real `SystemConfig()` fixtures in tests — never MagicMock at the config boundary (BF-287).

## Section 2: Flip the trigger in `render_verification.py`

`src/probos/avatars/render_verification.py:115-117` currently reads:

```python
    if trigger == "agent_initiated_stub":
        # Path exists so future AD flips the gate; currently hard-rejected.
        return _result(coherent=None, skipped="agent_initiated_disabled")
```

Replace with a gated check that honours `cfg.avatars.render_self_check_enabled`. When enabled AND the trigger is `agent_initiated_stub`, fall through to the rest of `verify_render_coherence` AS-IS — the existing `render_verification_enabled` / `backend_render_unavailable` / `tier_unavailable` / phrasing / emission machinery applies unchanged. The ONLY differences are:

- Replace the existing `max_per_hour` rate-limit gate (currently at `render_verification.py:130-133`) for THIS trigger with the two-budget logic from Section 3.
- Cost discipline for SENSORIUM-side observation (Section 4) is owned by the caller (`CognitiveAgent.check_own_render`), not by `verify_render_coherence`. The function itself continues to emit `RENDER_DIVERGENCE_OBSERVED` only on divergence; agent-initiated coherent calls do NOT alter that.

The trigger string remains `agent_initiated_stub` (do not rename — preserves the AD-728 string-stability contract; the "_stub" suffix is now historical but renaming would break AD-728 tests and the public trigger surface). Document in a one-line code comment that the name is retained for compat; the behavior is no longer a stub.

**Builder verify-first:** the existing `_VALID_TRIGGERS` frozenset at `render_verification.py:40-44` already includes `"agent_initiated_stub"`. No edit there.

## Section 3: Two-budget rate limit

Add a small helper inside `render_verification.py` (NOT a public surface; module-private). Pseudocode shape:

```python
def _agent_initiated_rate_check(
    *,
    runtime: Any,
    agent_id: str,
    avatars_cfg: Any,
    now: float,
) -> str | None:
    """Return a skipped_reason string if rate-limited, else None.

    Two-budget logic:
      * If agent is in an active conversation (last_reply_emitted_at within
        active_window_seconds), apply the per-conversation budget.
      * Else, apply the hourly budget.

    The two budgets are NEVER additive. Captain explicitly said an agent
    "may want to check more often" during conversations; the per-
    conversation budget is the override, not an add-on.
    """
    active_window = int(getattr(avatars_cfg, "render_self_check_active_window_seconds", 600))
    last_reply = _last_reply_emitted_at(runtime, agent_id)   # see below
    in_active = (
        last_reply > 0.0 and active_window > 0
        and (now - last_reply) <= active_window
    )

    if in_active:
        budget = int(getattr(avatars_cfg, "render_self_check_max_per_active_conversation", 0))
        if budget <= 0:
            return "rate_limited_self_check"
        rate = VisionLLMRateLimit(
            scope=f"render_self_check_conv:{int(last_reply)}",
            max_per_hour=budget,
        )
    else:
        budget = int(getattr(avatars_cfg, "render_self_check_max_per_hour_per_agent", 0))
        if budget <= 0:
            return "rate_limited_self_check"
        rate = VisionLLMRateLimit(
            scope="render_self_check_hour",
            max_per_hour=budget,
        )

    if not rate.under_limit(agent_id):
        return "rate_limited_self_check"
    rate.note_call(agent_id)
    return None
```

**Conversation-scope key:** the `last_reply_emitted_at` timestamp is bucketed into the scope name so each conversation gets its own (scope, agent) tuple in `VisionLLMRateLimit._windows`. A subsequent reply (new `last_reply_emitted_at` timestamp) starts a fresh per-conversation bucket. The 3600s window in `VisionLLMRateLimit` is irrelevant for the conversation bucket — what matters is that the bucket KEY changes when the agent next replies.

**Known limitation (forward marker AD-728c-3):** `VisionLLMRateLimit._windows` is class-level shared state. Per-conversation scope keys (`render_self_check_conv:<ts>`) accumulate one stale bucket per Captain reply, never garbage-collected. Acceptable for AD-728c because (a) each bucket is a tiny `deque[float]` and (b) the 3600s sliding-window eviction inside `under_limit` keeps each bucket from growing. Total memory pressure is O(replies_per_runtime_lifetime) of empty deques. Bucket GC deferred to AD-728c-3 (see Forward markers section).

**`_last_reply_emitted_at` lookup:** the runtime exposes registered agents via `runtime.registry.get(agent_id)` (public API per BF-287). Each `CognitiveAgent` instance has `last_reply_emitted_at` as a public `@property` (`cognitive_agent.py:3115`). Honest-degrade to `0.0` when the registry lacks the agent or the agent lacks the attribute.

**Replacement of the AD-728 rate gate:** for the `agent_initiated_stub` trigger, SKIP the existing `render_verification_max_per_hour_per_agent` gate at `render_verification.py:130-133`. The two-budget logic IS the rate gate for this trigger. Other triggers continue using the original gate unchanged.

**Wire-up:** call `_agent_initiated_rate_check` from inside `verify_render_coherence` along the agent-initiated branch BEFORE the existing AD-728 hourly gate. If it returns a non-None reason, `_result(coherent=None, skipped=reason)`.

## Section 4: `CognitiveAgent.check_own_render`

New async method on `CognitiveAgent` (`src/probos/cognitive/cognitive_agent.py`). Place it near `mark_reply_emitted` (currently `cognitive_agent.py:3090`) since both are AD-722 avatar telemetry callsites.

```python
async def check_own_render(self, reason: str | None = None) -> None:
    """AD-728c: agent-initiated render self-check.

    Calls `verify_render_coherence` with trigger='agent_initiated_stub'
    and folds the result into the agent's working memory as an
    observation. Both coherent and divergent (and rate-limited) outcomes
    are surfaced so the agent can adapt its next reply.

    reason: short tag (<=64 chars) describing why the agent is checking
        (e.g. "before_reply", "mid_conversation", "user_corrected
        _appearance"). Stored on the resulting WorkingMemoryEntry for
        downstream salience. None becomes "unspecified".
    """
```

Body:

1. Resolve `digital_state_summary` and `backend_render_ref` the SAME WAY AD-728's captain_command path does (re-use whatever helper that path uses; do NOT reimplement projection). If either is unavailable, fold a brief observation noting `skipped_reason="backend_render_unavailable"` into working memory and return.
2. Call `await verify_render_coherence(runtime=self._runtime, agent_id=self.id, trigger="agent_initiated_stub", digital_state_summary=..., backend_render_ref=...)`.
3. Build a `summary` string from the `RenderCoherenceResult`:
   - `result.coherent is True`: `f"Self-check (reason={tag}): vision-LLM confirms my rendered avatar matches my intent."`
   - `result.coherent is False`: `f"Self-check (reason={tag}): vision-LLM reports my avatar shows '{result.analog_description}' but I intended '{result.digital_description}'. Summary: {result.divergence_summary}."`
   - `result.skipped_reason == "rate_limited_self_check"`: `f"Self-check (reason={tag}) was throttled by rate limit; no observation captured this call."`
   - Any other `skipped_reason`: `f"Self-check (reason={tag}) honest-degraded: {result.skipped_reason}."`
4. Call `self._working_memory.record_observation(summary, source="render_self_check", metadata={"reason": tag, "trigger": "agent_initiated_stub", "coherent": result.coherent, "skipped_reason": result.skipped_reason}, knowledge_source="self_perception")`.
5. NEVER raise — every internal error is `logger.warning(...)` with `exc_info=True` and a "honest-degraded" working-memory entry.

**Why `record_observation` and not SensoriumEntry:** the `SENSORIUM_REGISTRY` (`cognitive_agent.py:246-`) is class-level static dispatch metadata describing *which method* renders a sensorium block at perception time. It is NOT a runtime mailbox for ephemeral observations. The correct runtime ingress for "the agent just observed X" is `AgentWorkingMemory.record_observation` (`agent_working_memory.py:404`), which feeds the agent's recent-observations buffer and the named `"ship"` buffer. The user-request prose mentions SensoriumEntry / `injection_zone="self_perception"` / `wrapper=None`; those are the wrong primitive — they're metadata on static class registrations, not a runtime injection surface. The semantic intent ("the agent sees this observation in its next LLM call") IS satisfied by `record_observation`. Document this divergence prominently in the prompt body and in the AD-728c code comments.

## Section 5: Honest-degrade on rate-limit

Section 3 returns `skipped_reason="rate_limited_self_check"` from the rate-check helper. Section 4 step 3 turns that into a brief observation. Together they satisfy the user requirement: the agent knows it tried and was throttled, rather than silent drop.

## Section 6: AD-728 cost discipline divergence (explicit)

AD-728 says coherent observations are NOT logged. AD-728c PRESERVES that on the EVENT-BUS side: `_emit_render_divergence` is still only called when `coherent is False` (no change to `render_verification.py:200-209`). The divergence is only in the agent's OWN working memory — a private observation in the agent's recent buffer, not an emitted event. Document this distinction in the AD-728c module docstring delta.

## Section 7: Tests

`tests/test_ad728c_render_self_check.py` (new file). At minimum:

1. `agent_initiated_stub` trigger no longer returns `skipped_reason="agent_initiated_disabled"` when `render_self_check_enabled=True` AND the call would otherwise succeed.
2. Default-OFF: with `render_self_check_enabled=False`, agent-initiated trigger returns `skipped_reason="agent_initiated_disabled"` (preserves AD-728 baseline behavior).
3. Hourly budget enforced: 4th call within an hour (default budget 3) when NOT in an active conversation returns `skipped_reason="rate_limited_self_check"`.
4. Active-conversation budget enforced: with `last_reply_emitted_at` recent, 3rd call within the same conversation (default budget 2) returns `skipped_reason="rate_limited_self_check"`.
5. Budget-switch correctness: an agent in an active conversation does NOT consume the hourly bucket; once `(now - last_reply_emitted_at) > active_window_seconds`, the hourly bucket governs and is independent of any per-conversation calls made earlier.
6. Coherent observation injected: `CognitiveAgent.check_own_render(reason="before_reply")` happy path records a `category="observation"` entry whose `content` includes "vision-LLM confirms" and whose metadata carries `coherent=True, reason="before_reply"`.
7. Divergent observation injected: divergent vision-LLM response records an observation whose content includes the analog/digital phrases and metadata `coherent=False`.
8. Rate-limited observation injected: throttled call still produces a `category="observation"` entry whose metadata carries `skipped_reason="rate_limited_self_check"`.
9. `CognitiveAgent.check_own_render` is `inspect.iscoroutinefunction(...)` True (regression guard against accidental sync rewrite — BF-254 family).
10. AD-731 invariant preserved: source-scan `render_verification.py` for `b64encode` / `base64.b64` returns empty AFTER the Section 2/3 edits.
11. `verify_render_coherence` STILL emits `RENDER_DIVERGENCE_OBSERVED` exactly once on agent-initiated divergent calls (AD-728c does not break AD-728's event contract).
12. `verify_render_coherence` does NOT emit on agent-initiated coherent calls (cost-discipline preserved on the event-bus side, even though the agent's working memory IS updated).

Use real `SystemConfig()` fixtures (BF-287). Use a real `AgentWorkingMemory` fixture for tests 6–8 (do NOT MagicMock the working-memory boundary — BF-287 / AD-722b-4 retrospective). For tests 1–5/9–12, the `_FakeRuntime` / `_FakeLLMClient` shapes from `tests/test_ad728_render_verification.py:42-65` can be reused; extend `_FakeRuntime` with a `registry` shim whose `.get(agent_id)` returns a **hand-rolled `@dataclass` agent stub** with a real `last_reply_emitted_at: float` attribute. **The agent stub MUST NOT be `MagicMock(spec=CognitiveAgent)`** — BF-287 (Wave 160 retrospective) shows that MagicMock's auto-attribute behavior silently passes tests against phantom attribute names. Hand-rolled dataclass forces a real attribute lookup that fails fast if the production code reads the wrong name.

## Section 8: Builder Standing Rules

- **BF-274**: single `replace_string_in_file` for adjacent edits. NO `multi_replace_string_in_file` for adjacent SEARCH blocks (the Section 2 edit is one small block — single replace).
- **BF-280**: NO `asyncio.create_subprocess_*`. None expected here.
- **BF-282**: NO binary stdout capture on Windows. None expected here.
- **BF-286**: test scaffolding mirrors production async/event-loop shape. The `check_own_render` test runs under `pytest-asyncio` like `tests/test_ad728_render_verification.py`.
- **BF-287**: use public registry API (`registry.get(agent_id)`), NOT `registry.agents`. The `_FakeRuntime.registry` shim in tests exposes `.get(...)` as a real method.
- **AD-731 invariant**: image bytes flow through `AttachmentStore` SHA-256 refs. Verified by Test 10.
- **AD-722c-3**: any forward marker filed by this prompt uses TECHNICAL triggers.
- **AD-738b**: no UI changes in AD-728c, so no `cd ui ; npm run build` gate. Confirmed.
- **Real Pydantic config fixtures in tests** — no MagicMock at the config boundary.

## What this does NOT change

- The `captain_command` trigger (unchanged — its rate gate, projection, and emission are all preserved).
- The `divergence_followup` trigger (still gated by `render_verification_followup_enabled` default-OFF).
- The `_VALID_TRIGGERS` frozenset (still contains `agent_initiated_stub`; name retained for compat).
- `EventType` (no additions).
- `RenderCoherenceResult` shape (no field additions; `skipped_reason="rate_limited_self_check"` is a new string value of an existing field).
- The AD-728 cost-discipline rule on the event bus (coherent → no emission).
- `VisionLLMRateLimit` class itself (only adds two new scope keys: `render_self_check_hour` and `render_self_check_conv:<ts>`).
- Cross-agent perception (AD-722a-6 already shipped Wave 163).
- Embedding-distance scoring (AD-728a forward marker — out of scope).
- Auto-correction proposals (AD-728b forward marker — out of scope).
- HXI surface (AD-728c is server-side only; no Counselor mediation hand-off, no `/check-render` shell command).

## Tracking

- `PROGRESS.md`: append Wave 164 CLOSED entry for AD-728c.
- `docs/development/roadmap.md`: AD-728c row added under the AD-728 family with reference to the gh issue.
- `DECISIONS.md`: append AD-728c entry — agent-initiated self-check, two-budget contextual rate limit, working-memory ingress via `record_observation`, event-bus cost-discipline preserved.

## Forward markers (TECHNICAL triggers per AD-722c-3)

- **AD-728c-1 — Per-conversation budget reset on Captain-acknowledged correction.** Trigger: when AD-572 correction-detector is producing per-conversation correction signals AND AD-728c telemetry shows agents exhausting their per-conversation budget before resolving a divergence. Goal: when the Captain explicitly acknowledges a render correction, reset the per-conversation budget so the agent can re-verify post-fix without consuming a fresh conversation slot. Issue file deferred.
- **AD-728c-2 — Counselor mediation of self-check requests.** Trigger: when AD-721d-2 Counselor-mediated avatar revision is generalized to render self-checks AND ≥3 distinct agents have requested self-checks via instructions in production traffic. Issue file deferred.
- **AD-728c-3 — `VisionLLMRateLimit` per-conversation bucket GC.** Trigger: when `VisionLLMRateLimit._windows` size exceeds 1000 entries in production (proxy for runtime lifetime × Captain reply rate) OR when any other AD reuses the `render_self_check_conv:<ts>` scope pattern. Goal: add a class-level eviction sweep that drops `(scope, agent_id)` keys whose deque is empty AND whose last `note_call` is older than the 3600s window. Issue file deferred.

## Acceptance Criteria

1. All Section 1–6 deliverables landed.
2. ≥12 pytest tests pass: `pytest tests/test_ad728c_render_self_check.py -v -n 0`.
3. Full parallel gate green: `pytest tests/ -q -n 4 --dist=loadfile`.
4. AD-728's existing 15 tests in `tests/test_ad728_render_verification.py` STILL pass without modification, except test #228 (`test_agent_initiated_stub_hard_rejected`) which MUST be updated to assert the new default-OFF behavior (`render_self_check_enabled=False` → still `skipped_reason="agent_initiated_disabled"`). Document the update in the commit message.
5. AD-731 invariant test (Test 10) explicitly source-scans `render_verification.py` for `b64encode` / `base64.b64` — must be empty.
6. AD-727 trust-isolation preserved: source-scan `render_verification.py` for `trust_network` / `hebbian` — must remain empty (AD-728 invariant inherited).
7. Zero new pip/npm dependencies.
8. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-16)

```
grep -n "agent_initiated_stub" src/probos/avatars/render_verification.py
   10:     3. ``agent_initiated_stub`` — Path exists but hard-rejected pending future
   43:     "agent_initiated_stub",
  115:     if trigger == "agent_initiated_stub":
  117:         return _result(coherent=None, skipped="agent_initiated_disabled")

grep -n "class VisionLLMRateLimit" src/probos/avatars/vision_intent_divergence.py
   57: class VisionLLMRateLimit:

grep -n "render_verification_" src/probos/config.py
  1107: render_verification_enabled: bool = Field(
  1114: render_verification_max_per_hour_per_agent: int = Field(
  1123: render_verification_followup_enabled: bool = Field(

grep -n "last_reply_emitted_at\|mark_reply_emitted" src/probos/cognitive/cognitive_agent.py
  3090: def mark_reply_emitted(self) -> None:
  3115: def last_reply_emitted_at(self) -> float:

grep -n "def record_observation" src/probos/cognitive/agent_working_memory.py
   404: def record_observation(

grep -n "class SensoriumEntry\|PROPRIOCEPTION" src/probos/cognitive/cognitive_agent.py
   57: PROPRIOCEPTION = "proprioception"
   96: class SensoriumEntry:
  # SENSORIUM_REGISTRY entries are class-level dispatch metadata, NOT
  # a runtime mailbox. AD-728c uses AgentWorkingMemory.record_observation
  # instead — see Section 4 rationale.

grep -n "RENDER_DIVERGENCE_OBSERVED" src/probos/events.py
   (confirmed present per AD-728 Wave 163 ship; AD-728c adds NO new event types)
```

**Phantom check 1 — SensoriumEntry as runtime mailbox.** The user-request text describes injecting a `SensoriumEntry` with `injection_zone="self_perception"` / `wrapper=None` directly into the agent's working memory. Grep of `cognitive_agent.py:246-` confirms `SENSORIUM_REGISTRY` is a `ClassVar[dict[str, SensoriumEntry]]` mapping internal method names (e.g. `"_sensorium_temporal_context"`) to static dispatch records. It is NOT a runtime injection surface. The correct runtime ingress for "the agent observed X right now" is `AgentWorkingMemory.record_observation` (verified `agent_working_memory.py:404`). Section 4 uses that primitive; the rationale paragraph in Section 4 documents the deviation from the user-request prose.

**Phantom check 2 — `runtime.registry.get(agent_id)`.** BF-287 retrospective requires use of the public registry API. The `_last_reply_emitted_at` lookup in Section 3 calls `runtime.registry.get(agent_id)`. The test harness (`_FakeRuntime.registry`) MUST expose `.get(...)` as a real method, not via MagicMock auto-attribute (BF-287). Re-affirmed in Section 7 test scaffolding.

**Phantom check 3 — trigger string rename.** The user-request prose says "Flip `agent_initiated` trigger." The actual trigger string in `_VALID_TRIGGERS` (`render_verification.py:43`) is `"agent_initiated_stub"`. Section 2 explicitly retains the historical name to preserve AD-728 test stability; the prompt does NOT rename.

**Phantom check 4 — projection helper sharing.** Section 4 says "Resolve `digital_state_summary` and `backend_render_ref` the SAME WAY AD-728's captain_command path does." The AD-728 captain-command callsite lives in `experience/shell.py` (AD-728 prompt Section 4 §1). Builder MUST verify the projection helper invoked there is callable from `CognitiveAgent.check_own_render` (likely already module-level / importable). If the helper is private to `shell.py`, Builder either promotes it to a module-level function in `avatars/` OR extracts a thin shared helper. This is a Section-4 implementation detail — flag in build-report if the helper is not already share-able.
