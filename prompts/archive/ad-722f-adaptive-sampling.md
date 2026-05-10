# AD-722f — Adaptive avatar-telemetry sampling rate (per-agent state machine)

**Status:** READY FOR BUILDER
**Wave:** 141 (Build Group A — second commit, after AD-722-1)
**Dispatch:** [prompts/WAVE-141-DISPATCH.md](WAVE-141-DISPATCH.md)
**Cluster plan:** [prompts/BUILDER-EXECUTION-PLAN-avatar-cluster.md](BUILDER-EXECUTION-PLAN-avatar-cluster.md)
**Depends on:** AD-722 v1 (SHIPPED Wave 140), AD-722-1 (committed earlier in this wave — manifest extraction; not a hard dependency, but the same wave)
**Pairs with:** AD-722-1 (same wave). Forward-paired with AD-722b (Wave 142 WebSocket push).
**Issue:** [#580](https://github.com/seangalliher/ProbOS/issues/580)
**Risk:** **MEDIUM** — new module + new config fields + 4 new wiring sites across 2 files. Read-only contract on the snapshot side is preserved (state-machine writes are confined to `runtime.avatar_sampling_state`; telemetry reads are pure projections of that state).
**Estimated tests:** ≥ 14 Python boundary cases. UI tests unaffected (UI continues to poll at `POLL_MS = 2000`; Wave 142 introduces per-agent push via WS).
**Build order:** Second commit of Wave 141, after AD-722-1 lands.

> **Builder:** read [prompts/WAVE-141-DISPATCH.md](WAVE-141-DISPATCH.md) for the cross-AD checklist and test-gate command. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 1. Goal

Today the avatar-telemetry channel publishes (UI poll) and refreshes (`observe_self_avatar()`) at a single fixed rate (`avatar_telemetry.polling_interval_ms = 2000`). The Captain insight 2026-05-10 ([DECISIONS.md AD-722 addendum (i)](../DECISIONS.md)):

> *"The self-image state needs to be updating at a much faster rate when the agent is interacting visibly with the avatar vs when the agent is just sitting idle or chatting in the ward room. Like a human is much more self-aware in public or in front of another person vs alone."*

This is biologically grounded — interoceptive sampling is genuinely context-dependent (the "spotlight of attention" effect). AD-722f introduces a **per-agent state machine** with three tiers:

| Tier | Default rate | Trigger |
|---|---|---|
| **HIGH** | 250 ms | A direct message from the Captain is in flight (entered on DM receipt; exited on `mark_reply_emitted`). Future: avatar popout open via WS subscribe (Wave 142, NOT in this AD). |
| **NORMAL** | 2000 ms | Multi-step chain reasoning is active (entered on `_execute_chain_with_intent_routing`; exited on chain return). |
| **LOW** | 10000 ms | Default (idle / WR posting / no active trigger). |

Precedence: HIGH > NORMAL > LOW. Concurrent triggers (e.g. chain inside a DM) resolve by reference-counting per trigger type; the highest active tier wins. WR (`ward_room_notification`) **does not** trigger any tier change — per AD-722 addendum (h), WR is peer communication, not Captain-facing self-presentation.

This AD ships:

1. A `runtime.avatar_sampling_state` state machine.
2. Config extension with three operator-configurable rates.
3. Trigger wiring at the four pre-existing call sites (DM enter/exit, chain enter/exit).
4. Snapshot extension exposing the agent's current tier and rate.
5. Documentation of what is **NOT** wired in this AD: the avatar popout WS subscribe (Wave 142), the UI rate switch (Wave 142).

---

## 2. Verified Against Codebase (2026-05-10 @ HEAD)

```
# Existing config — the surface we extend
grep -n "class AvatarTelemetryConfig\|polling_interval_ms\|avatar_telemetry: AvatarTelemetryConfig" src/probos/config.py
   941: class AvatarTelemetryConfig(BaseModel):
   954:     polling_interval_ms: int = 2000          # UI hint; backend does not poll itself.
   963:     @field_validator("polling_interval_ms")
  3166:     avatar_telemetry: AvatarTelemetryConfig = Field(default_factory=AvatarTelemetryConfig)  # AD-722

# DM enter site — AD-722 already calls observe_self_avatar() here. Same site gets the HIGH-tier enter.
grep -n "observe_self_avatar\|@router.post.*chat\|async def agent_chat" src/probos/routers/agents.py
   519: async def agent_chat(agent_id: str, req: AgentChatRequest, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
   546:     if hasattr(agent, 'observe_self_avatar'):
   548:             await agent.observe_self_avatar()

# DM exit site — AD-722 already stamps mark_reply_emitted() here. Same site gets the HIGH-tier exit.
grep -n "mark_reply_emitted" src/probos/routers/agents.py
   721:     if hasattr(agent, 'mark_reply_emitted'):
   722:         agent.mark_reply_emitted()

# Chain enter / exit site — single function, structured try/return path
grep -n "async def _execute_chain_with_intent_routing\|return chain_result\|chain_result is None" src/probos/cognitive/cognitive_agent.py | head -10
   1394:             chain_result = await self._execute_chain_with_intent_routing(observation)
   2216: async def _execute_chain_with_intent_routing(self, observation: dict) -> dict | None:
   # Caller pattern at 1394:
   #     elif self._should_activate_chain(observation):
   #         chain_result = await self._execute_chain_with_intent_routing(observation)
   #         if chain_result is not None: return chain_result
   #         # else fall-through to _decide_via_llm()
   # AD-722f wires NORMAL-tier enter/exit at the caller (line 1394 region) so the state-machine
   # changes match the chain's actual scope (caller handles fall-through to LLM, which is NOT
   # chain-reasoning).

# CognitiveAgent — runtime backref already exists (verified during AD-722)
grep -n "self\._runtime\|self\.id\s*=" src/probos/cognitive/cognitive_agent.py | head -5
# (CognitiveAgent has self._runtime per AD-722; the chain entry/exit can read runtime.avatar_sampling_state via that.)

# Runtime initialization — verify no existing avatar_sampling_state attribute
grep -n "avatar_sampling_state\|avatar_telemetry_state" src/probos/runtime.py src/probos/startup/*.py
# (no matches — greenfield attribute)

# Initialization site for sibling stores — pattern to mirror (init in runtime.__init__, not finalize)
grep -n "self\.profile_store\s*=" src/probos/runtime.py
   408: self.profile_store = ProfileStore(

# AvatarTelemetrySnapshot — surface that gains sampling_rate_ms/sampling_tier
grep -n "@dataclass(frozen=True)\nclass AvatarTelemetrySnapshot\|class AvatarTelemetrySnapshot\|def to_dict" src/probos/avatars/telemetry.py | head -10
   137: class AvatarTelemetrySnapshot:
   170:     def to_dict(self) -> dict[str, Any]:

# UI poll surface — confirms POLL_MS is hard-coded; AD-722f does NOT change this (Wave 142 will)
grep -n "POLL_MS\|setInterval" ui/src/components/profile/SelfImageTab.tsx
   42: const POLL_MS = 2000;
   72:     const id = setInterval(fetchOnce, POLL_MS);

# WR branch — confirms it is intentionally NOT a sampling-state trigger
grep -n "ward_room_notification" src/probos/cognitive/cognitive_agent.py | head -5
# (per AD-722 addendum (h): WR is peer communication, not Captain-facing presentation —
#  no HIGH/NORMAL trigger. Chain reasoning that originates from WR still triggers NORMAL
#  via _execute_chain_with_intent_routing — that is correct, since chain reasoning IS
#  the trigger, not the source intent. Documentation, not code change.)
```

---

## 3. License posture

Apache 2.0 stays Apache 2.0. **Zero new deps.** Pure stdlib + existing Pydantic models.

---

## 4. Architectural decisions (resolved by architect; do not re-litigate)

| Decision | Resolution | Rationale |
|---|---|---|
| State storage location | **`runtime.avatar_sampling_state`** (new attribute, instance of `AvatarSamplingStateMachine` from new module `src/probos/avatars/sampling_state.py`) | The rate is a runtime concern (cross-agent, runtime-lifecycle). Per-agent storage on `CognitiveAgent` would scatter the state machine across instances, complicate testing, and bloat the agent surface. Mirrors `runtime.profile_store` pattern (`runtime.py:408`). |
| Initialization phase | **`runtime.__init__()`** alongside `self.profile_store` (around `runtime.py:408`) | Avoids the BF-259/260/261/262 finalize-phase trap. State-machine has no async deps; can be constructed eagerly at `__init__` time. |
| Concurrent trigger resolution | **Per-trigger reference counting + priority resolution** | `enter_dm` increments a `dm` counter; `exit_dm` decrements. `current_tier` returns HIGH if `dm > 0`, else NORMAL if `chain > 0`, else LOW. Reference counting handles the (rare but possible) case of two concurrent DMs to the same agent. |
| Default tier values | **HIGH=250 / NORMAL=2000 / LOW=10000 ms** | Aligned with AD-722 addendum (i) sketch and existing `polling_interval_ms` baseline. NORMAL == current default (back-compat). All three are operator-configurable. |
| `polling_interval_ms` back-compat | **Kept as-is** (UI hint only, used by `SelfImageTab.tsx` directly) | Wave 142 will collapse `polling_interval_ms` and the new `sampling_rates` into a single per-agent push channel. Until then, `polling_interval_ms` remains the UI's poll cadence (2000 ms = NORMAL); the backend state machine is independent. |
| Snapshot exposure | **`AvatarTelemetrySnapshot` gains `sampling_rate_ms: int` and `sampling_tier: str` fields** | Surfaces the current rate to the API consumer (HXI, future WS subscribers, agent self-introspection). Tier-2 log-and-degrade if `runtime.avatar_sampling_state` is missing (shouldn't happen at runtime; matters for unit tests that build minimal MagicMock runtimes). |
| WR (ward_room) trigger surface | **NOT WIRED — per AD-722 addendum (h)** | WR is peer communication, not Captain-facing self-presentation. The state machine has no `enter_wr`/`exit_wr` methods. A test asserts the absence of these methods (phantom-API guard). Note that chain reasoning *originating* from a WR-driven intent will still fire `enter_chain` → NORMAL via `_execute_chain_with_intent_routing` — that is correct, the trigger is "the agent is reasoning", not "the audience is the Captain". |
| Avatar popout open trigger surface | **FORWARD MARKER — not wired in this AD** | The popout open/close trigger requires a WebSocket channel (Wave 142 / AD-722b) to deliver subscribe/unsubscribe events to the backend. Wiring it on the HTTP poll surface would be a hack. AD-722b will add a `enter_subscriber(agent_id)`/`exit_subscriber(agent_id)` pair to the state machine and call from the WS handler. Documented in this AD's "Out of scope" table. |
| UI rate switch | **NOT IN SCOPE** | `SelfImageTab.tsx:42` keeps `POLL_MS = 2000`. The agent-side state machine is internal to the backend in this wave. Wave 142 replaces UI polling with WS push at the rate dictated by the state machine. |

---

## 5. Scope (this AD only)

Single commit. Five surfaces touched:

1. **Add** `src/probos/avatars/sampling_state.py` — the state machine module.
2. **Modify** `src/probos/config.py` — add `SamplingRatesConfig`; add `sampling_rates` field to `AvatarTelemetryConfig`.
3. **Modify** `src/probos/runtime.py` — initialize `self.avatar_sampling_state` in `__init__()`.
4. **Modify** `src/probos/avatars/telemetry.py` — extend `AvatarTelemetrySnapshot` with `sampling_rate_ms` and `sampling_tier`; populate in `build_telemetry_snapshot()` (tier-2 degrade if state machine missing).
5. **Modify** `src/probos/routers/agents.py` — wire `enter_dm`/`exit_dm` at the existing observe/mark sites.
6. **Modify** `src/probos/cognitive/cognitive_agent.py` — wire `enter_chain`/`exit_chain` around the `_execute_chain_with_intent_routing` call site (the `decide()` body region near line 1394, **at the caller**, not inside the chain function).
7. **Add** `tests/test_ad722f_adaptive_sampling.py` — boundary tests.

---

## 6. Non-goals (deferred forward markers)

| Marker | Deferred to | Why not v1 |
|---|---|---|
| Avatar popout subscribe trigger | AD-722b (Wave 142) | Requires WS channel that doesn't exist yet. State-machine `enter_subscriber` method is forward-marker only. |
| UI per-agent rate switch | AD-722b (Wave 142) | Requires push channel; polling at NORMAL stays. |
| Adaptive rate based on novelty / activity | Future | Captain ruling 2026-05-10 — three discrete tiers are sufficient for v1. |
| Persistence of sampling state across restart | Out of scope forever | Rate is volatile by design (idle on restart = LOW). Tested explicitly. |
| WR-originated state changes | NOT TO BE BUILT | Per AD-722 addendum (h). Tests assert the absence. |

Reviewer fails the prompt if any deliverable touches `ui/src/`, the AD-722-1 manifest file, `apply_voice_modulation()`'s body, `pyproject.toml`, or `ui/package.json`.

---

## 7. Deliverables

### D1 — Config extension in `src/probos/config.py`

**Insert** a new model `SamplingRatesConfig` immediately above `AvatarTelemetryConfig` (around line 940, before line 941):

```python
class SamplingRatesConfig(BaseModel):
    """AD-722f: per-agent avatar-telemetry sampling rates (3 tiers).

    Driven by ``runtime.avatar_sampling_state`` state machine. All three
    fields default — ``SamplingRatesConfig()`` MUST succeed. Operator
    overrides via system.yaml. Validators clamp to a safety floor (250 ms)
    to prevent UI/backend hammering — same floor as ``polling_interval_ms``.
    """

    high_ms: int = 250      # DM in flight, popout open (forward marker — Wave 142)
    normal_ms: int = 2000   # Chain reasoning active
    low_ms: int = 10000     # Idle / WR posting / default

    @field_validator("high_ms", "normal_ms", "low_ms")
    @classmethod
    def _bound_rate(cls, v: int) -> int:
        if v < 250:
            raise ValueError(
                f"sampling-rate field must be >= 250 to prevent UI hammering, got {v}"
            )
        return v

    @model_validator(mode="after")
    def _check_ordering(self) -> "SamplingRatesConfig":
        if not (self.high_ms <= self.normal_ms <= self.low_ms):
            raise ValueError(
                f"sampling rates must satisfy high_ms <= normal_ms <= low_ms; "
                f"got high={self.high_ms}, normal={self.normal_ms}, low={self.low_ms}"
            )
        return self
```

Note: `model_validator` is **already imported** at `config.py:10` (`from pydantic import BaseModel, Field, field_validator, model_validator`). No import-line change required — verified at HEAD 2026-05-10.

**Modify** `AvatarTelemetryConfig` to add the new field. **SEARCH** (around lines 947-957):

```python
class AvatarTelemetryConfig(BaseModel):
    """AD-722: agent-observable avatar telemetry channel.

    Read-only telemetry — exposes the agent's own avatar state via a
    snapshot dataclass. v1 is poll-only (HTTP + in-process method on
    ``CognitiveAgent``); push (WebSocket) is forward marker AD-722b.

    All fields default — ``AvatarTelemetryConfig()`` MUST succeed.
    """

    enabled: bool = True
    inject_into_agent_context: bool = False  # Feature-gated; default OFF.
    mouth_active_window_seconds: float = 3.0
    polling_interval_ms: int = 2000          # UI hint; backend does not poll itself.
```

**REPLACE** with (adding `sampling_rates`):

```python
class AvatarTelemetryConfig(BaseModel):
    """AD-722: agent-observable avatar telemetry channel.

    Read-only telemetry — exposes the agent's own avatar state via a
    snapshot dataclass. v1 is poll-only (HTTP + in-process method on
    ``CognitiveAgent``); push (WebSocket) is forward marker AD-722b.

    AD-722f added per-agent adaptive sampling (``sampling_rates`` field
    + ``runtime.avatar_sampling_state`` state machine). The legacy
    ``polling_interval_ms`` field is retained as a UI hint (consumed
    directly by ``SelfImageTab.tsx``); Wave 142's WS push channel will
    collapse the two surfaces.

    All fields default — ``AvatarTelemetryConfig()`` MUST succeed.
    """

    enabled: bool = True
    inject_into_agent_context: bool = False  # Feature-gated; default OFF.
    mouth_active_window_seconds: float = 3.0
    polling_interval_ms: int = 2000          # AD-722 — UI hint, not backend-driven.
    sampling_rates: SamplingRatesConfig = Field(default_factory=SamplingRatesConfig)  # AD-722f
```

(The two existing field_validators below this block — `_bound_mouth_window`, `_bound_polling` — stay in place unchanged.)

### D2 — State machine module `src/probos/avatars/sampling_state.py` (new file)

```python
"""AD-722f: per-agent avatar-telemetry sampling state machine.

Three tiers with priority resolution: HIGH > NORMAL > LOW. Triggers are
reference-counted per agent — concurrent enters of the same trigger
type are tolerated (rare but possible: two DMs in flight, or a chain
spawned during a DM). The current tier is the highest active trigger.

Trigger surfaces (Wave 141):
  - ``enter_dm`` / ``exit_dm`` — wired at routers/agents.py:agent_chat
    (entry around the existing ``observe_self_avatar()`` call;
    exit around the existing ``mark_reply_emitted()`` call).
  - ``enter_chain`` / ``exit_chain`` — wired at cognitive_agent.py around
    the ``_execute_chain_with_intent_routing`` call site (line ~1394).

Trigger surfaces NOT wired in Wave 141 (forward markers):
  - ``enter_subscriber`` / ``exit_subscriber`` — Wave 142 / AD-722b WebSocket
    subscribe/unsubscribe. Method names reserved here for forward-marker
    discoverability; bodies are NOT defined in this AD.

Per AD-722 addendum (h): WR (ward_room_notification) does NOT trigger
state changes. The state machine does not expose ``enter_wr``/``exit_wr``;
a test asserts their absence.

State is volatile by design — restart resets every agent to LOW.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.config import SamplingRatesConfig

logger = logging.getLogger(__name__)


# Tier names (string literals — match the tier names exposed in the
# AvatarTelemetrySnapshot.sampling_tier field).
TIER_HIGH = "high"
TIER_NORMAL = "normal"
TIER_LOW = "low"


class AvatarSamplingStateMachine:
    """Per-agent reference-counted trigger registry → tier resolution.

    Thread-safe (Lock-guarded) for the FastAPI / asyncio thread-pool
    crossover; trigger entries originate from request handlers (sync
    section of FastAPI) and chain entries from agent code (asyncio
    coroutine). Lock contention is microscopic — typical agent has
    0-2 active triggers at any moment.
    """

    def __init__(self, rates: "SamplingRatesConfig") -> None:
        self._rates = rates
        # nested dict: agent_id -> {trigger_name: refcount}
        self._counts: dict[str, dict[str, int]] = defaultdict(
            lambda: {"dm": 0, "chain": 0},
        )
        self._lock = Lock()

    # ── Trigger surfaces (Wave 141) ─────────────────────────────────

    def enter_dm(self, agent_id: str) -> None:
        with self._lock:
            self._counts[agent_id]["dm"] += 1

    def exit_dm(self, agent_id: str) -> None:
        with self._lock:
            n = self._counts[agent_id]["dm"]
            if n <= 0:
                # Spurious exit (e.g. handler exception path between
                # observe_self_avatar and mark_reply_emitted). Tier-2
                # log-and-degrade — clamp to 0.
                logger.warning(
                    "AD-722f: spurious exit_dm for agent=%s (count was %d); clamping to 0",
                    agent_id, n,
                )
                self._counts[agent_id]["dm"] = 0
                return
            self._counts[agent_id]["dm"] = n - 1

    def enter_chain(self, agent_id: str) -> None:
        with self._lock:
            self._counts[agent_id]["chain"] += 1

    def exit_chain(self, agent_id: str) -> None:
        with self._lock:
            n = self._counts[agent_id]["chain"]
            if n <= 0:
                logger.warning(
                    "AD-722f: spurious exit_chain for agent=%s (count was %d); clamping to 0",
                    agent_id, n,
                )
                self._counts[agent_id]["chain"] = 0
                return
            self._counts[agent_id]["chain"] = n - 1

    # ── Read surface ────────────────────────────────────────────────

    def current_tier(self, agent_id: str) -> str:
        """Resolve the active tier for an agent. HIGH > NORMAL > LOW."""
        with self._lock:
            counts = self._counts.get(agent_id)
            if counts is None:
                return TIER_LOW
            if counts.get("dm", 0) > 0:
                return TIER_HIGH
            if counts.get("chain", 0) > 0:
                return TIER_NORMAL
            return TIER_LOW

    def current_rate_ms(self, agent_id: str) -> int:
        """Resolve the active sampling rate (ms) for an agent."""
        tier = self.current_tier(agent_id)
        if tier == TIER_HIGH:
            return self._rates.high_ms
        if tier == TIER_NORMAL:
            return self._rates.normal_ms
        return self._rates.low_ms

    def snapshot_counts(self, agent_id: str) -> dict[str, int]:
        """Test-only introspection. Returns a copy of the trigger counts."""
        with self._lock:
            counts = self._counts.get(agent_id)
            if counts is None:
                return {"dm": 0, "chain": 0}
            return dict(counts)
```

Notes:
- `from threading import Lock` — Lock is sync. Trigger calls are short and non-blocking; `asyncio.Lock` is unnecessary overhead.
- The state machine is intentionally minimal. No metrics, no event emission, no persistence. Wave 142 may layer those on.
- `TYPE_CHECKING` guard avoids circular import (config.py → sampling_state.py would not naturally cycle, but the discipline is applied per the codebase's import-order rules in `.github/copilot-instructions.md`).

### D3 — Runtime initialization in `src/probos/runtime.py`

**SEARCH** the `self.profile_store = ProfileStore(...)` block (around line 408):

```python
        from probos.crew_profile import ProfileStore
        # Ensure the data_dir exists; ProfileStore connects synchronously in
        # __init__ (unlike TrustNetwork/EventLog which are async-lazy and
        # mkdir on first start()). Tests that run RuntimeBuilder against a
        # tmp path expect this.
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self.profile_store = ProfileStore(
            db_path=str(self._data_dir / "crew_profiles.db"),
        )
        # Red team agents are stored separately — not on the intent bus
        self.red_team_agents: list[RedTeamAgent] = []
```

**REPLACE** with (adding `avatar_sampling_state` after `profile_store`):

```python
        from probos.crew_profile import ProfileStore
        # Ensure the data_dir exists; ProfileStore connects synchronously in
        # __init__ (unlike TrustNetwork/EventLog which are async-lazy and
        # mkdir on first start()). Tests that run RuntimeBuilder against a
        # tmp path expect this.
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self.profile_store = ProfileStore(
            db_path=str(self._data_dir / "crew_profiles.db"),
        )

        # AD-722f: per-agent avatar-telemetry sampling state machine.
        # Initialized in __init__ (not finalize) so consumers in cognitive
        # services / routers can rely on its presence at any startup phase.
        # State is volatile by design — restart resets to LOW for every agent.
        from probos.avatars.sampling_state import AvatarSamplingStateMachine
        self.avatar_sampling_state = AvatarSamplingStateMachine(
            rates=self.config.avatar_telemetry.sampling_rates,
        )

        # Red team agents are stored separately — not on the intent bus
        self.red_team_agents: list[RedTeamAgent] = []
```

### D4 — Snapshot extension in `src/probos/avatars/telemetry.py`

**SEARCH** the `AvatarTelemetrySnapshot` dataclass (around lines 137-185):

```python
@dataclass(frozen=True)
class AvatarTelemetrySnapshot:
    """Read-only snapshot of an agent's avatar state.
```

**(Read the full dataclass at HEAD before editing — it spans ~50 lines.)** The required modifications are:

1. **Add two fields** (after `degraded_reasons: tuple[str, ...]`):

   ```python
       sampling_rate_ms: int                # AD-722f — agent's current adaptive sampling rate
       sampling_tier: str                   # AD-722f — 'high' | 'normal' | 'low'
   ```

   Note: frozen dataclass field-ordering rule — `sampling_rate_ms` and `sampling_tier` have no defaults, so they go after the existing `degraded_reasons` field (which also has no default). Order preserved.

2. **Update `to_dict()`** to include the new fields:

   ```python
       def to_dict(self) -> dict[str, Any]:
           return {
               "agent_id": self.agent_id,
               "expression_resting": self.expression_resting,
               "current_signals": self.current_signals.to_dict(),
               "mouth_active": self.mouth_active,
               "applied_modulation": (
                   self.applied_modulation.to_dict()
                   if self.applied_modulation is not None else None
               ),
               "dsl_summary": (
                   self.dsl_summary.to_dict() if self.dsl_summary is not None else None
               ),
               "last_observed_at": self.last_observed_at,
               "degraded_reasons": list(self.degraded_reasons),
               "sampling_rate_ms": self.sampling_rate_ms,
               "sampling_tier": self.sampling_tier,
           }
   ```

3. **Populate in `build_telemetry_snapshot`** — find every `return AvatarTelemetrySnapshot(...)` site (there are at least two — the agent_not_found early return at HEAD line ~285, and the success-path return at the bottom of the function). For each, add the two new fields. Use a helper to compute them with tier-2 degrade:

   Insert this helper near the top of the module's helpers section (above `_empty_signals`):

   ```python
   def _resolve_sampling(runtime: Any, agent_id: str, reasons: list[str]) -> tuple[int, str]:
       """AD-722f: resolve current adaptive sampling rate + tier for an agent.

       Tier-2 log-and-degrade: when the state machine is missing (test
       runtimes with stripped MagicMocks), fall back to NORMAL using the
       config's default rate; append a degraded reason. NEVER raises.
       """
       state = getattr(runtime, "avatar_sampling_state", None)
       cfg = getattr(runtime, "config", None)
       tcfg = getattr(cfg, "avatar_telemetry", None)
       rates = getattr(tcfg, "sampling_rates", None)
       if state is None:
           reasons.append("avatar_sampling_state_unavailable")
           # Best-effort fallback — mirror the LOW default if config exists,
           # else hard-coded LOW (matches SamplingRatesConfig default).
           low_ms = getattr(rates, "low_ms", 10000)
           return int(low_ms), "low"
       try:
           tier = state.current_tier(agent_id)
           rate = state.current_rate_ms(agent_id)
           return int(rate), str(tier)
       except Exception:
           logger.warning(
               "AD-722f: sampling-state lookup failed for agent=%s; "
               "falling back to LOW",
               agent_id, exc_info=True,
           )
           reasons.append("avatar_sampling_state_unavailable")
           low_ms = getattr(rates, "low_ms", 10000)
           return int(low_ms), "low"
   ```

   Then at every `AvatarTelemetrySnapshot(...)` construction site in `build_telemetry_snapshot`:

   - Just before the construction, add: `sampling_rate_ms, sampling_tier = _resolve_sampling(runtime, agent_id, reasons)`.
   - Pass `sampling_rate_ms=sampling_rate_ms, sampling_tier=sampling_tier` as keyword arguments.

   For the agent_not_found early return (where `reasons` is currently a fresh `("agent_not_found",)` tuple): adapt — call `_resolve_sampling` with a local `local_reasons: list[str] = list(reasons)` if needed, OR (simpler) accept that `agent_not_found` snapshots use the LOW fallback unconditionally:

   ```python
   # AD-722f: agent_not_found path — emit LOW tier with config defaults.
   _early_reasons: list[str] = ["agent_not_found"]
   _early_rate_ms, _early_tier = _resolve_sampling(runtime, agent_id, _early_reasons)
   return AvatarTelemetrySnapshot(
       agent_id=agent_id,
       expression_resting=None,
       current_signals=_empty_signals(),
       mouth_active=False,
       applied_modulation=None,
       dsl_summary=None,
       last_observed_at=now,
       degraded_reasons=tuple(_early_reasons),
       sampling_rate_ms=_early_rate_ms,
       sampling_tier=_early_tier,
   )
   ```

   (Builder: read the actual function body at HEAD — `build_telemetry_snapshot` runs ~140 lines. Apply the same `_resolve_sampling` call + kwargs pattern at every `return AvatarTelemetrySnapshot(...)` site.)

### D5 — Trigger wiring in `src/probos/routers/agents.py`

**SEARCH** the existing DM-entry block (around lines 539-555 — the `observe_self_avatar()` call):

```python
    # AD-722 BF (2026-05-10): refresh self-avatar snapshot before the agent
    # perceives the DM, so the INTEROCEPTION sensorium block has fresh data
    # when prompt assembly runs. Tier-2 log-and-degrade — telemetry must
    # never block a reply. No-op when avatar_telemetry.enabled is False
    # (build_telemetry_snapshot itself short-circuits gracefully).
    if hasattr(agent, 'observe_self_avatar'):
        try:
            await agent.observe_self_avatar()
        except Exception:
            logger.debug(
                "AD-722: self-avatar snapshot refresh failed for %s; "
                "INTEROCEPTION block will use stale or empty data",
                agent_id,
                exc_info=True,
            )
```

**REPLACE** with (adding the AD-722f enter_dm before, and a try/finally so exit_dm always fires):

```python
    # AD-722 BF (2026-05-10): refresh self-avatar snapshot before the agent
    # perceives the DM, so the INTEROCEPTION sensorium block has fresh data
    # when prompt assembly runs. Tier-2 log-and-degrade — telemetry must
    # never block a reply. No-op when avatar_telemetry.enabled is False
    # (build_telemetry_snapshot itself short-circuits gracefully).
    #
    # AD-722f: bracket the DM with HIGH-tier sampling. enter_dm here;
    # exit_dm fires at the mark_reply_emitted site below. The exit is
    # ALSO guaranteed by the spurious-exit clamp in the state machine,
    # so an exception path between enter and exit cannot leak refcount
    # permanently — at worst, the next mark_reply_emitted clamps to 0.
    _sampling_state = getattr(runtime, 'avatar_sampling_state', None)
    if _sampling_state is not None:
        _sampling_state.enter_dm(agent_id)
    if hasattr(agent, 'observe_self_avatar'):
        try:
            await agent.observe_self_avatar()
        except Exception:
            logger.debug(
                "AD-722: self-avatar snapshot refresh failed for %s; "
                "INTEROCEPTION block will use stale or empty data",
                agent_id,
                exc_info=True,
            )
```

**SEARCH** the existing mark_reply_emitted block (around lines 720-723):

```python
    # AD-722: stamp the last-reply emission timestamp. Single source of truth.
    if hasattr(agent, 'mark_reply_emitted'):
        agent.mark_reply_emitted()
```

**REPLACE** with (adding exit_dm immediately after):

```python
    # AD-722: stamp the last-reply emission timestamp. Single source of truth.
    if hasattr(agent, 'mark_reply_emitted'):
        agent.mark_reply_emitted()

    # AD-722f: matched exit for the enter_dm at the top of agent_chat.
    # Spurious-exit clamp in the state machine handles the (rare)
    # exception-path case where enter fired but exit didn't.
    if _sampling_state is not None:
        _sampling_state.exit_dm(agent_id)
```

Note: `_sampling_state` is the local already bound at the entry block; reuse it. If the exception-path between entry and exit dropped out before this site, the local is still bound (Python locals persist through exception handlers in the same function scope when the function continues to completion).

### D6 — Trigger wiring in `src/probos/cognitive/cognitive_agent.py`

**SEARCH** the chain caller block (around lines 1392-1402 — the `elif self._should_activate_chain(observation):` branch in the `decide()` body):

```python
        # Priority 2: intent-driven routing (AD-643a)
        elif self._should_activate_chain(observation):
            chain_result = await self._execute_chain_with_intent_routing(observation)
            if chain_result is not None:
                _cache_ttl = self._get_cache_ttl()
                cache[cache_key] = (chain_result, time.monotonic(), _cache_ttl)
                return chain_result
            # chain_result is None → fall through to _decide_via_llm()
            # Skills may already be loaded in observation from intent routing
```

**REPLACE** with (bracket the chain call with enter/exit; use try/finally to guarantee exit even if the chain raises):

```python
        # Priority 2: intent-driven routing (AD-643a)
        elif self._should_activate_chain(observation):
            # AD-722f: bracket chain reasoning with NORMAL-tier sampling.
            # Wrapped in try/finally so an exception inside the chain
            # cannot leak the refcount. Tier-2 degrade if the runtime is
            # missing the state machine (e.g. test rigs with minimal
            # MagicMock runtimes) — getattr fallback to None is safe.
            _sampling_state = getattr(self._runtime, 'avatar_sampling_state', None)
            if _sampling_state is not None:
                _sampling_state.enter_chain(self.id)
            try:
                chain_result = await self._execute_chain_with_intent_routing(observation)
            finally:
                if _sampling_state is not None:
                    _sampling_state.exit_chain(self.id)
            if chain_result is not None:
                _cache_ttl = self._get_cache_ttl()
                cache[cache_key] = (chain_result, time.monotonic(), _cache_ttl)
                return chain_result
            # chain_result is None → fall through to _decide_via_llm()
            # Skills may already be loaded in observation from intent routing
```

Note: this is the **caller** site, not inside `_execute_chain_with_intent_routing`. Wiring at the caller has two advantages:
- The chain function's own internals stay free of state-machine concerns.
- Fall-through to `_decide_via_llm()` (when `chain_result is None`) correctly does NOT count as chain reasoning — the chain attempt is over by the time we exit.

### D7 — Tests in `tests/test_ad722f_adaptive_sampling.py` (new file)

```python
"""AD-722f: per-agent avatar-telemetry sampling state machine tests."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from probos.avatars.sampling_state import (
    TIER_HIGH,
    TIER_LOW,
    TIER_NORMAL,
    AvatarSamplingStateMachine,
)
from probos.config import AvatarTelemetryConfig, SamplingRatesConfig


# ── Construction & defaults ─────────────────────────────────────────────


def test_state_machine_defaults_to_low_for_unknown_agent():
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    assert sm.current_tier("agent-007") == TIER_LOW
    assert sm.current_rate_ms("agent-007") == 10000


def test_default_rates_match_addendum_sketch():
    rates = SamplingRatesConfig()
    assert rates.high_ms == 250
    assert rates.normal_ms == 2000
    assert rates.low_ms == 10000


def test_custom_rates_propagate_through_state_machine():
    rates = SamplingRatesConfig(high_ms=500, normal_ms=3000, low_ms=15000)
    sm = AvatarSamplingStateMachine(rates=rates)
    sm.enter_dm("a")
    assert sm.current_rate_ms("a") == 500
    sm.exit_dm("a")
    sm.enter_chain("a")
    assert sm.current_rate_ms("a") == 3000


# ── Tier transitions ────────────────────────────────────────────────────


def test_dm_enter_promotes_to_high():
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    sm.enter_dm("a")
    assert sm.current_tier("a") == TIER_HIGH
    sm.exit_dm("a")
    assert sm.current_tier("a") == TIER_LOW


def test_chain_enter_promotes_to_normal():
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    sm.enter_chain("a")
    assert sm.current_tier("a") == TIER_NORMAL
    sm.exit_chain("a")
    assert sm.current_tier("a") == TIER_LOW


def test_concurrent_dm_and_chain_resolve_to_high():
    """DM > chain by priority. Chain entered first then DM still resolves HIGH."""
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    sm.enter_chain("a")
    assert sm.current_tier("a") == TIER_NORMAL
    sm.enter_dm("a")
    assert sm.current_tier("a") == TIER_HIGH
    sm.exit_dm("a")
    # Chain still active → revert to NORMAL.
    assert sm.current_tier("a") == TIER_NORMAL
    sm.exit_chain("a")
    assert sm.current_tier("a") == TIER_LOW


def test_refcount_handles_concurrent_dm_to_same_agent():
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    sm.enter_dm("a")
    sm.enter_dm("a")
    sm.exit_dm("a")
    # Still one DM active.
    assert sm.current_tier("a") == TIER_HIGH
    sm.exit_dm("a")
    assert sm.current_tier("a") == TIER_LOW


def test_spurious_exit_clamps_to_zero(caplog):
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    with caplog.at_level("WARNING"):
        sm.exit_dm("a")
    assert sm.current_tier("a") == TIER_LOW
    assert any("spurious exit_dm" in r.message for r in caplog.records)
    # Should not poison subsequent enters.
    sm.enter_dm("a")
    assert sm.current_tier("a") == TIER_HIGH


# ── Per-agent isolation ─────────────────────────────────────────────────


def test_per_agent_state_does_not_leak():
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    sm.enter_dm("a")
    assert sm.current_tier("a") == TIER_HIGH
    assert sm.current_tier("b") == TIER_LOW


# ── Config integration ──────────────────────────────────────────────────


def test_avatar_telemetry_config_includes_sampling_rates():
    cfg = AvatarTelemetryConfig()
    assert isinstance(cfg.sampling_rates, SamplingRatesConfig)
    assert cfg.sampling_rates.high_ms == 250


def test_sampling_rates_validator_rejects_below_floor():
    with pytest.raises(ValueError, match="must be >= 250"):
        SamplingRatesConfig(high_ms=100)


def test_sampling_rates_validator_rejects_inverted_ordering():
    with pytest.raises(ValueError, match="high_ms <= normal_ms <= low_ms"):
        SamplingRatesConfig(high_ms=3000, normal_ms=500, low_ms=10000)


# ── No phantom WR API (per AD-722 addendum (h)) ─────────────────────────


def test_state_machine_does_not_expose_wr_methods():
    """AD-722 addendum (h): WR is peer communication, not Captain-facing
    self-presentation. The state machine MUST NOT expose enter_wr/exit_wr."""
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    assert not hasattr(sm, "enter_wr")
    assert not hasattr(sm, "exit_wr")


# ── Restart semantics (state is volatile by design) ─────────────────────


def test_fresh_instance_starts_low():
    """AD-722f: state is volatile. Restart resets all agents to LOW."""
    sm1 = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    sm1.enter_dm("a")
    sm1.enter_chain("b")
    # Simulate restart.
    sm2 = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    assert sm2.current_tier("a") == TIER_LOW
    assert sm2.current_tier("b") == TIER_LOW


# ── Snapshot-side integration (telemetry.py) ────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_includes_sampling_rate_and_tier():
    """build_telemetry_snapshot populates sampling_rate_ms + sampling_tier."""
    from probos.avatars.telemetry import build_telemetry_snapshot
    from probos.types import AgentState

    runtime = MagicMock()
    runtime.avatar_sampling_state = AvatarSamplingStateMachine(
        rates=SamplingRatesConfig(),
    )
    runtime.avatar_sampling_state.enter_dm("agent-007")

    # Minimal runtime shape — agent_not_found short-circuits, which is fine
    # because it still resolves sampling on the way out.
    runtime.registry = MagicMock()
    runtime.registry.get.return_value = None

    snap = await build_telemetry_snapshot("agent-007", runtime)
    assert snap.sampling_tier == TIER_HIGH
    assert snap.sampling_rate_ms == 250
    body = snap.to_dict()
    assert body["sampling_rate_ms"] == 250
    assert body["sampling_tier"] == "high"


@pytest.mark.asyncio
async def test_snapshot_degrades_gracefully_when_state_missing():
    """Tier-2: missing avatar_sampling_state → LOW fallback + degraded reason."""
    from probos.avatars.telemetry import build_telemetry_snapshot

    runtime = MagicMock(spec=[])  # no avatar_sampling_state attribute
    runtime.registry = MagicMock()
    runtime.registry.get.return_value = None

    snap = await build_telemetry_snapshot("agent-missing", runtime)
    assert snap.sampling_tier == TIER_LOW
    assert "avatar_sampling_state_unavailable" in snap.degraded_reasons
```

Note: the `test_snapshot_includes_sampling_rate_and_tier` test exercises the agent_not_found path by design — it isolates the sampling-state plumbing without dragging in the full agent / profile / DSL / trust mocks. If the Builder finds a more complete-runtime fixture in the existing `tests/test_ad722_avatar_telemetry.py` (`_make_runtime` helper), feel free to import or replicate that pattern; the test names and assertions stay identical.

---

## 8. Acceptance criteria

- **State machine module** at `src/probos/avatars/sampling_state.py` with `AvatarSamplingStateMachine`, four trigger methods (`enter_dm`, `exit_dm`, `enter_chain`, `exit_chain`), and two read methods (`current_tier`, `current_rate_ms`). No WR methods. No popout/subscriber methods (forward marker for AD-722b).
- **Config extension** — `SamplingRatesConfig` with three int fields, validators (floor + ordering), defaults 250/2000/10000. Mounted on `AvatarTelemetryConfig.sampling_rates`. `AvatarTelemetryConfig()` continues to succeed with zero arguments.
- **Runtime initialization** — `runtime.avatar_sampling_state` initialized in `runtime.__init__()` adjacent to `self.profile_store` (NOT in finalize). Avoids the BF-259/260/261/262 trap.
- **Snapshot fields** — `AvatarTelemetrySnapshot.sampling_rate_ms: int` and `.sampling_tier: str` populated at every construction site. `to_dict()` includes both. Tier-2 degrade if state machine missing (LOW fallback + degraded reason).
- **DM wiring** — `enter_dm` at `routers/agents.py:agent_chat` near the existing `observe_self_avatar()` call; `exit_dm` near the existing `mark_reply_emitted()` call. Both guarded by `getattr` fallback for test runtimes lacking the state machine.
- **Chain wiring** — `enter_chain`/`exit_chain` bracket the `_execute_chain_with_intent_routing` call site at `cognitive_agent.py:~1394` in a try/finally so exceptions inside the chain cannot leak refcounts.
- **WR path NOT wired** — confirm by grep that no new call to `enter_wr` / `exit_wr` exists; the state machine intentionally does not expose those methods.
- **Test count delta** — ≥ 14 new boundary cases in `tests/test_ad722f_adaptive_sampling.py`. The existing `tests/test_ad722_avatar_telemetry.py` 18 cases continue to pass; if any of them assert on `AvatarTelemetrySnapshot` fields by exact equality (not subset-match), update them to include the two new fields.
- **UI unchanged** — `ui/src/components/profile/SelfImageTab.tsx` and `voiceModulation.ts` unmodified by this AD. Vitest count unchanged.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 9. Tracking updates

| File | Update |
|---|---|
| `PROGRESS.md` | Append AD-722f to the "Most recent shipped" section. Bump test-count baseline by +14 (or actual). |
| `docs/development/roadmap.md` | Mark #580 as shipped. |
| `DECISIONS.md` | Append AD-722f entry under the AD-722 addendum block. Document: state-machine location (`runtime.avatar_sampling_state`), trigger surfaces wired (DM, chain), trigger surfaces deferred (popout/subscriber → Wave 142, WR → never per addendum (h)), default rates (250/2000/10000), back-compat with `polling_interval_ms` (UI hint, unchanged). |

The Builder commits a single `git commit -m "AD-722f: per-agent adaptive avatar-telemetry sampling rate"`. Push not required.
