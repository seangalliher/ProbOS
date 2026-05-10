# AD-722 — Agent-observable avatar telemetry v1

**Status:** READY FOR BUILDER
**Wave:** 140
**Dispatch:** [prompts/WAVE-140-DISPATCH.md](prompts/WAVE-140-DISPATCH.md)
**Depends on:** AD-721 (3D avatar surface, SHIPPED Wave 133), AD-721b (phoneme lipsync, SHIPPED Wave 138), AD-721d (agent-authored `AvatarDSL` persisted on `crew_profiles.data`, SHIPPED Wave 134), AD-718d (emotional voice modulation, SHIPPED Wave 137)
**Pairs with:** none — single-prompt wave
**Issue:** [#545](https://github.com/seangalliher/ProbOS/issues/545)
**Risk:** **MEDIUM** — new module + new endpoint + new tab + new method on `CognitiveAgent`; read-only contract is the safety belt
**Estimated tests:** ≥ 12 Python + ≥ 6 Vitest
**Build order:** Single-prompt wave; one commit.

> **Builder:** read [prompts/WAVE-140-DISPATCH.md](prompts/WAVE-140-DISPATCH.md) for cross-AD context, license posture, and the engineering-principles checklist. Read [prompts/BUILDER-EXECUTION-PLAN.md](prompts/BUILDER-EXECUTION-PLAN.md) for the standing test-gate command, hard-stop rules, and quarantine procedure. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 1. Goal

The avatar surface (AD-721 + AD-721b + AD-721d + AD-718d) is a one-way pipe: **runtime → avatar**. Trust deltas, working state, voice modulation, lipsync, and the agent-authored `AvatarDSL` all flow outward; the agent itself has no read-back. AD-722 v1 closes the loop: the agent can **observe** its own avatar state via a new `observe_self_avatar()` method on `CognitiveAgent` (poll, not push) and via a new HTTP endpoint `GET /api/agent/{agent_id}/avatar-telemetry` for HXI consumption.

The agent **cannot drive** the avatar from this AD. Driving stays in AD-721d (Captain-approved DSL) and AD-721 (`AgentSignals` selector). v1 ships the read-side telemetry channel only.

### Why now

Counselor (Echo) is the v1 design partner — she designed her own appearance via AD-721d; she has a phoneme-lipsync mouth via AD-721b; she has emotional voice modulation via AD-718d. She does NOT yet know any of that. *Does the agent know what it looks like right now?* is the architecturally interesting question Wave 140 answers.

Captain ruling 2026-05-09 ([#545](https://github.com/seangalliher/ProbOS/issues/545) — Open-LLM-VTuber, kimjammer/Neuro, super-agent-party prior-art review): **novel territory, no public OSS prior art** for inverting the runtime→avatar pattern into an agent self-perception loop. Pattern absorption is therefore architectural, not implementation-level: AD-722 is a clean-room design.

---

## 2. Verified Against Codebase (2026-05-10 @ HEAD)

```
# CognitiveAgent class & SENSORIUM_REGISTRY
grep -n "^class CognitiveAgent\|SENSORIUM_REGISTRY\|propose_appearance\|_build_cognitive_baseline" \
     src/probos/cognitive/cognitive_agent.py
   93: class CognitiveAgent(BaseAgent):
  122:     SENSORIUM_REGISTRY: ClassVar[dict[str, tuple[SensoriumLayer, str]]] = {
  129:         "_build_cognitive_baseline": (SensoriumLayer.INTEROCEPTION, ...),
  2592: async def propose_appearance(...
  4249: def _build_cognitive_baseline(self, observation: dict) -> dict[str, str]:

# CognitiveAgent fields _last_reply_emit_ts / mark_reply_emitted / last_reply_emitted_at
# do NOT exist at HEAD — greenfield additions in this AD.

# AppearanceProfile + AvatarDSL persistence (AD-721d shipped)
grep -n "class AppearanceProfile\|class VoiceProfile\|dsl:" src/probos/crew_profile.py
   96: class VoiceProfile:
  157: class AppearanceProfile:
  175:     dsl: dict[str, Any] | None = None         # AD-721d already persisted

grep -n "class AvatarDSL\|expression_resting" src/probos/avatars/dsl.py
  118: class AvatarDSL(BaseModel):
  132:     expression_resting: RestingExpression = "neutral"

# Config
grep -n "class AvatarsConfig\|class SystemConfig\|avatars: AvatarsConfig" src/probos/config.py
   922: class AvatarsConfig(BaseModel):
  3054: class SystemConfig(BaseModel):
  3135:     avatars: AvatarsConfig = Field(default_factory=AvatarsConfig)  # AD-721

# AvatarTelemetryConfig does NOT exist at HEAD — greenfield in this AD.

# Routers — chat handler + appearance endpoints + feature gate
grep -n "_avatars_feature_check\|profile_store\.get\|@router\." src/probos/routers/agents.py
   32: @router.get("/{agent_id}/identity")
   49: @router.get("/{agent_id}/profile")
   91:         if hasattr(runtime.trust_network, 'get_history'):
   92:             trust_history = runtime.trust_network.get_history(agent.id, limit=20)
  124:         live_profile = runtime.profile_store.get(agent.id)
  368: def _avatars_feature_check(runtime: Any) -> None:
  379: @router.post("/{agent_id}/appearance/propose", ...)
  389:     _avatars_feature_check(runtime)
  418: @router.put("/{agent_id}/appearance")
  460: @router.post("/{agent_id}/chat")

# Trust history method existence (CRITICAL — see §9 reminder 1)
grep -rn "def get_history\|def history_for" src/probos/consensus/
  (no matches — TrustNetwork at consensus/trust.py:112 has neither method.)
# Routers/agents.py:91 wraps the call in `hasattr(...)` — telemetry MUST mirror that guard.

# Bridge alerts (tier-3 source)
grep -n "bridge_alerts\|class AlertSeverity\|ALERT\s*=\|def get_recent_alerts" \
     src/probos/runtime.py src/probos/bridge_alerts.py
  runtime.py:244:     bridge_alerts: BridgeAlertService | None
  runtime.py:455:     self.bridge_alerts: BridgeAlertService | None = None
  runtime.py:3229:     for a in self.bridge_alerts.get_recent_alerts(10)
  bridge_alerts.py:24: class AlertSeverity(str, Enum):
  bridge_alerts.py:28:     ALERT = "alert"
  bridge_alerts.py:822: def get_recent_alerts(self, limit: int = 50) -> list[BridgeAlert]:

# UI surface
grep -n "type ProfileTab\|TAB_LABELS\|isCrew" ui/src/components/profile/AgentProfilePanel.tsx
   12: type ProfileTab = 'chat' | 'work' | 'profile' | 'health' | 'memory';
   14: const TAB_LABELS: { key: ProfileTab; label: string }[] = [
  150:   const isCrew = profileData?.isCrew ?? true;
  153:   const visibleTabs = isCrew
  155:     ? TAB_LABELS.filter(t => t.key !== 'chat' && t.key !== 'memory');

grep -n "deriveAgentSignals\|trust_delta\|tier3_alert\|working_state\|load" \
     ui/src/components/profile/avatarSignals.ts
   12: trust_delta: number;
   13: load: number;
   14: working_state: 'idle' | 'responding' | 'blocked';
   15: tier3_alert: boolean;
   26: export function deriveAgentSignals(...
   37: else if (agent.state === 'active' && store.processing) working_state = 'responding';
   41: const trust_delta = 0;        # placeholder — backend re-derives from get_history
   43: const load = store.processing ? 1.0 : 0.0;
   46: const tier3_alert = !!store.notifications?.some(n => n?.tier === '3' || ...);

# TS modulation constants (verbatim source for byte-parity test)
grep -n "MODULATION_DIVERGENCE_THRESHOLD\|PITCH_BOUNDS\|RATE_BOUNDS\|VOLUME_BOUNDS\|RESPONDING_RATE\|BLOCKED_RATE\|HIGH_TRUST\|LOW_TRUST\|TIER3_RATE\|TIER3_VOLUME" \
     ui/src/audio/voiceModulation.ts
   17: export const MODULATION_DIVERGENCE_THRESHOLD = 0.05;
   21: export const PITCH_BOUNDS: readonly [number, number] = [0, 2];
   22: export const RATE_BOUNDS: readonly [number, number] = [0.1, 10];
   23: export const VOLUME_BOUNDS: readonly [number, number] = [0, 1];
   31: const RESPONDING_RATE_FACTOR = 1.05;
   32: const BLOCKED_RATE_FACTOR = 0.92;
   34: const HIGH_TRUST_PITCH_FACTOR = 1.03;
   35: const LOW_TRUST_PITCH_FACTOR = 0.97;
   36: const TIER3_RATE_FACTOR = 1.15;
   37: const TIER3_VOLUME_FACTOR = 1.05;
# Plus BLOCKED_PITCH_FACTOR exists at HEAD (verify in impl) and applies on the
# blocked-state branch alongside BLOCKED_RATE_FACTOR per dispatch §2.
```

> **Dispatch corrections applied during this drafting pass (do not need re-verification by Builder; flagged in the architect's audit trail):**
>
> 1. **Dispatch §3 row "Optional prompt-context injection (B7)"** cites `SENSORIUM_REGISTRY hooks at lines 137–153`. The actual `SENSORIUM_REGISTRY` is at **`cognitive_agent.py:122`**, with entries running through `:138`. This prompt instructs the Builder to read the registry at HEAD and append below the existing entries (one new line); the line number is informational only.
> 2. **Dispatch §9 reminder 5** mentions `runtime.notification_store` in passing alongside `bridge_alerts`. There is **no `runtime.notification_store`** at HEAD. The tier-3 source is **`runtime.bridge_alerts.get_recent_alerts(10)`** exclusively (verified at `runtime.py:3229`, dispatch §2 row 3). This prompt only references `bridge_alerts`.
> 3. **Dispatch §9 reminder 13** correctly warns that `runtime.processing_state` does not exist. Verified at HEAD: no such attribute. v1 falls back to the documented approximation `load = 1.0 if mouth_active else 0.0` (see D2 below).
> 4. **`runtime.trust_network.get_history(...)`** is called at `routers/agents.py:91-92` behind a `hasattr` guard. The method itself is **not defined** on `TrustNetwork` (consensus/trust.py:112). v1 telemetry MUST mirror the guard pattern: `if hasattr(runtime.trust_network, 'get_history'): history = runtime.trust_network.get_history(agent_id, limit=2); else: history = []`. When the method is absent OR returns `< 2` entries, telemetry sets `trust_delta=0.0` + degraded reason `"insufficient_trust_history"`. This is the documented v1 behaviour — no new method is added to `TrustNetwork`.

---

## 3. License posture

Apache 2.0 stays Apache 2.0. **Zero new Python deps. Zero new JS deps.** No model weights, no third-party services, no SDKs. The duplication of the modulation rule table (TS + Python) is documented as v1 cost; AD-722-1 (extract to YAML manifest) is filed as the consolidation forward marker. `pyproject.toml` and `ui/package.json` are bit-for-bit unchanged — Reviewer fails on any diff to either.

---

## 4. Scope (v1 only)

Read-only telemetry channel: backend snapshot builder, HTTP endpoint, `CognitiveAgent.observe_self_avatar()` method, optional feature-gated prompt-context injection (default OFF), and a new `<SelfImageTab>` panel in `AgentProfilePanel`. Single commit.

---

## 5. Non-goals (deferred forward markers)

| Marker | What's deferred | Why not v1 |
|---|---|---|
| **AD-722a** | Intent-vs-presentation divergence detector → trust/Hebbian update | Read-only contract is non-negotiable in v1. AD-722a is the first consumer that closes the perception → mutation loop. |
| **AD-722b** | Push channel via WebSocket (server-sent telemetry) | v1 is poll. UI polls every 2s; agent code calls `observe_self_avatar()` on demand. WebSocket is its own AD with its own concurrency story. |
| **AD-722c** | Avatar-telemetry history for analytics | v1 returns the current snapshot only. Time-series storage is its own concern. |
| **AD-722d** | Auto-write telemetry to `RecordsStore` | v1 doesn't touch `RecordsStore`. No Records writes anywhere in this AD. |
| **AD-722e** | Visual self-perception via image rendering | v1 returns structured state only — no image bytes, no Blender, no browser-side capture. |
| **AD-722-1** | Modulation rule table extracted to YAML/JSON manifest (single source of truth for TS + Python) | Byte-parity test in v1 is the forcing function; manifest extraction is its own AD because both consumers are widely-imported. |

Reviewer fails the prompt if any deliverable touches `voice.ts`, any VRM file, `CognitiveCanvas.tsx`, `agents.tsx`, `animations.tsx`, `CrewVRM.tsx`, `ParametricAvatar.tsx`, `pyproject.toml`, or `ui/package.json`.

---

## 6. Deliverables

### D1 — `AvatarTelemetryConfig` Pydantic model

**Modify:** `src/probos/config.py`.

Insert sibling to `AvatarsConfig` (line 922):

```python
class AvatarTelemetryConfig(BaseModel):
    """AD-722: agent-observable avatar telemetry channel.

    All fields default — `AvatarTelemetryConfig()` MUST succeed.
    """

    enabled: bool = True
    inject_into_agent_context: bool = False  # Feature-gated; default OFF (see §9 reminder 3)
    mouth_active_window_seconds: float = 3.0
    polling_interval_ms: int = 2000          # UI hint; backend does not poll itself

    @field_validator("mouth_active_window_seconds")
    @classmethod
    def _bound_mouth_window(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"mouth_active_window_seconds must be > 0, got {v}")
        return v

    @field_validator("polling_interval_ms")
    @classmethod
    def _bound_polling(cls, v: int) -> int:
        if v < 250:
            raise ValueError(f"polling_interval_ms must be ≥ 250 to prevent UI hammering, got {v}")
        return v
```

Mount on `SystemConfig` adjacent to `avatars` (HEAD line 3135):

```
===SEARCH===
    avatars: AvatarsConfig = Field(default_factory=AvatarsConfig)  # AD-721
===REPLACE===
    avatars: AvatarsConfig = Field(default_factory=AvatarsConfig)  # AD-721
    avatar_telemetry: AvatarTelemetryConfig = Field(default_factory=AvatarTelemetryConfig)  # AD-722
===END REPLACE===
```

### D2 — Telemetry module (`src/probos/avatars/telemetry.py`, new)

Pure module: zero I/O beyond the `runtime.*` reads listed in §2, zero LLM calls, zero writes, zero state mutation. Tier-2 log-and-degrade on every failure path. The module docstring is the **single source of truth** for the signal-derivation rule table; `ui/src/components/profile/avatarSignals.ts` cites this docstring (one-line addition in D6).

**Module-top constants (verbatim port of `ui/src/audio/voiceModulation.ts:17,21-23,31-37`):**

```python
MODULATION_DIVERGENCE_THRESHOLD: float = 0.05
PITCH_BOUNDS: tuple[float, float] = (0.0, 2.0)
RATE_BOUNDS: tuple[float, float] = (0.1, 10.0)
VOLUME_BOUNDS: tuple[float, float] = (0.0, 1.0)

RESPONDING_RATE_FACTOR: float = 1.05
BLOCKED_RATE_FACTOR: float = 0.92
BLOCKED_PITCH_FACTOR: float = 0.95
HIGH_TRUST_PITCH_FACTOR: float = 1.03
LOW_TRUST_PITCH_FACTOR: float = 0.97
TIER3_RATE_FACTOR: float = 1.15
TIER3_VOLUME_FACTOR: float = 1.05

HIGH_TRUST_DELTA_THRESHOLD: float = 0.2
LOW_TRUST_DELTA_THRESHOLD: float = -0.2
```

Builder reads `voiceModulation.ts` at HEAD before writing this block and copies any constant whose name appears in the TS source — the byte-parity test (D8) is the forcing function for divergence detection.

**Frozen dataclasses:**

```python
@dataclass(frozen=True)
class AgentSignalsSnapshot:
    trust_delta: float
    load: float
    working_state: str  # 'idle' | 'responding' | 'blocked'
    tier3_alert: bool

@dataclass(frozen=True)
class ModulationSnapshot:
    pitch_factor: float
    rate_factor: float
    volume_factor: float
    fired_rules: tuple[str, ...]

@dataclass(frozen=True)
class DslSummarySnapshot:
    body_type: str
    hair_style: str
    primary_color: str
    outfit_style: str
    color_palette_hint: str

@dataclass(frozen=True)
class AvatarTelemetrySnapshot:
    """Read-only snapshot of an agent's avatar state.

    NOTE on `mouth_active`: speech happens browser-side via Web Speech API;
    the backend has no authoritative "currently speaking" signal. v1 derives
    `mouth_active` from `(now - agent.last_reply_emitted_at) < cfg.avatar_telemetry.mouth_active_window_seconds`
    (default 3.0s). This is a known approximation. AD-722b's WebSocket
    channel is what makes `mouth_active` authoritative.

    NOTE on `load`: there is no canonical per-agent backend source for `load`
    at HEAD. v1 approximates `load = 1.0 if mouth_active else 0.0`. AD-722b's
    WebSocket channel + per-agent in-flight signal makes `load` authoritative.

    NOTE on `trust_delta`: v1 reads `runtime.trust_network.get_history(agent_id, limit=2)`
    behind a `hasattr` guard mirroring `routers/agents.py:91`. When the method
    is absent OR history < 2 entries → `trust_delta=0.0` + degraded reason
    `"insufficient_trust_history"`. No magnitude smoothing, no decay.
    """

    agent_id: str
    expression_resting: str | None
    current_signals: AgentSignalsSnapshot
    mouth_active: bool
    applied_modulation: ModulationSnapshot | None
    dsl_summary: DslSummarySnapshot | None
    last_observed_at: float
    degraded_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        ...  # JSON-serialisable; all sub-dataclasses flatten to dicts.
```

**Functions:**

```python
def apply_voice_modulation(
    profile: VoiceProfile,
    signals: AgentSignalsSnapshot,
) -> ModulationSnapshot:
    """Pure function. Multiplicative composition matches voiceModulation.ts.

    Fired-rule names: 'responding_rate', 'blocked_rate_pitch',
    'high_trust_pitch', 'low_trust_pitch', 'tier3_rate_volume'.
    """

async def build_telemetry_snapshot(
    agent_id: str,
    runtime: Any,
) -> AvatarTelemetrySnapshot:
    """Build a read-only snapshot. Tier-2 degrades on every failure path
    (see degraded_reasons). NEVER raises on missing data."""
```

`build_telemetry_snapshot` execution order (the spec):

1. `agent = runtime.registry.get(agent_id)`. If `None` → return all-degraded snapshot with `degraded_reasons=("agent_not_found",)`.
2. `crew = runtime.profile_store.get(agent_id)` (mirroring `routers/agents.py:124`). When `None` or `crew.appearance is None` → degraded reasons accumulate per missing field.
3. Re-validate `crew.appearance.dsl` via `AvatarDSL.model_validate(crew.appearance.dsl)`. Catch `ValidationError` → `dsl_summary=None` + `"dsl_invalid"`. When `crew.appearance.dsl is None` → `dsl_summary=None` + `"dsl_not_persisted"`.
4. Compute `trust_delta`: `if hasattr(runtime.trust_network, 'get_history'): hist = runtime.trust_network.get_history(agent_id, limit=2); else: hist = []`. When `len(hist) < 2` → `0.0` + `"insufficient_trust_history"`. Else `hist[-1] - hist[-2]` (extract the float score per the existing call-site convention at `routers/agents.py:92`; if entries are dataclasses with `.score`, read `.score`; if raw floats, use directly).
5. Compute `tier3_alert`: when `runtime.bridge_alerts is None` → `False` + `"bridge_alerts_unavailable"`. Else `any(a.severity == AlertSeverity.ALERT and a.agent_id == agent_id for a in runtime.bridge_alerts.get_recent_alerts(10))`.
6. Compute `working_state`: `'blocked'` when `agent.state == AgentState.DEGRADED`, `'responding'` when `load > 0`, else `'idle'`. (Resolve `load` first per step 8.)
7. Compute `mouth_active`: `(time.time() - agent.last_reply_emitted_at) < cfg.avatar_telemetry.mouth_active_window_seconds`. Reads the **public property** `last_reply_emitted_at` (D3), never the private attr.
8. Compute `load`: v1 approximation `1.0 if mouth_active else 0.0` (per dispatch §9 reminder 13 + dispatch correction 3 above).
9. Compute `applied_modulation`: when `crew.voice_profile is None` → `None` + `"voice_profile_missing"`. Else `apply_voice_modulation(crew.voice_profile, signals)`.
10. Build `dsl_summary` from validated DSL (when present): `body.type / hair.style / outfit.primary_color / outfit.style / appearance.color_palette_hint`.
11. Return `AvatarTelemetrySnapshot(...)` with `last_observed_at=time.time()` and `degraded_reasons=tuple(reasons)` (frozen).

Single `logger.warning("AD-722 telemetry: %s for agent=%s; field=%s set to None", reason, agent_id, field)` per degraded field — no spam beyond that.

### D3 — `mark_reply_emitted` + `last_reply_emitted_at` on `CognitiveAgent`

**Modify:** `src/probos/cognitive/cognitive_agent.py`.

In `__init__` (after the existing `_runtime` / `_skills` block, around line 153 at HEAD), add:

```python
        # AD-722: most-recent reply emit timestamp (UNIX seconds).
        # Read via the public property `last_reply_emitted_at`.
        self._last_reply_emit_ts: float = 0.0
```

Add the public method + property at class scope (placement: near `propose_appearance` at HEAD line 2592 is acceptable; keep them adjacent for grepability):

```python
    def mark_reply_emitted(self) -> None:
        """AD-722: stamp the last-reply emission time. Caller wiring is
        the chat handler at `routers/agents.py:460+` — exactly one call site."""
        self._last_reply_emit_ts = time.time()

    @property
    def last_reply_emitted_at(self) -> float:
        """AD-722: UNIX seconds of last reply emission (0.0 if never)."""
        return self._last_reply_emit_ts
```

`import time` at module top (verify it's not already imported; add if absent).

### D4 — `observe_self_avatar()` method on `CognitiveAgent`

**Modify:** `src/probos/cognitive/cognitive_agent.py`.

Add at class scope, adjacent to `mark_reply_emitted`:

```python
    async def observe_self_avatar(self) -> "AvatarTelemetrySnapshot":
        """AD-722: read-only snapshot of this agent's avatar state.

        Pure delegation to `probos.avatars.telemetry.build_telemetry_snapshot`.
        Reviewer fails any expansion of business logic into this method.
        """
        from probos.avatars.telemetry import build_telemetry_snapshot
        return await build_telemetry_snapshot(self.id, self._runtime)
```

The `from ... import` is local (inside the method) to avoid module-level circulars between `cognitive_agent.py` and `avatars/telemetry.py`.

### D5 — Optional feature-gated prompt-context injection

**Modify:** `src/probos/cognitive/cognitive_agent.py`.

Add a new sensorium method:

```python
    def _build_avatar_self_observation(self, observation: dict) -> str:
        """AD-722 (feature-gated): agent's own avatar state as INTEROCEPTION.

        Returns empty string when `avatar_telemetry.inject_into_agent_context`
        is False (default) OR when the snapshot fetch fails. Tier-2 degrade.
        """
        cfg = getattr(self._runtime, "config", None)
        tcfg = getattr(getattr(cfg, "avatar_telemetry", None), "inject_into_agent_context", False)
        if not tcfg:
            return ""
        try:
            # Synchronous best-effort: schedule + drain.
            # Implementation: use asyncio.run_coroutine_threadsafe OR
            # cache the most-recent snapshot on `self._last_self_avatar_snap`
            # populated by an upstream caller. v1 chooses the cached path —
            # NO new event-loop spawning inside a sync sensorium method.
            snap = getattr(self, "_last_self_avatar_snap", None)
            if snap is None:
                return ""
            return (
                "Your current avatar state:\n"
                f"  expression_resting: {snap.expression_resting}\n"
                f"  working_state: {snap.current_signals.working_state}\n"
                f"  applied_modulation: rate={snap.applied_modulation.rate_factor:.2f}, "
                f"pitch={snap.applied_modulation.pitch_factor:.2f}\n"
                f"  mouth_active: {snap.mouth_active}\n"
                f"  dsl: {snap.dsl_summary.body_type} {snap.dsl_summary.hair_style} "
                f"{snap.dsl_summary.outfit_style} (color {snap.dsl_summary.primary_color})\n"
            )
        except Exception:
            logger.warning("AD-722 self-observation injection failed; returning empty", exc_info=True)
            return ""
```

Register in `SENSORIUM_REGISTRY` (HEAD line 122–138; append a new entry at the end of the dict literal):

```python
        "_build_avatar_self_observation": (SensoriumLayer.INTEROCEPTION,
            "AD-722: agent's own avatar state — gated by avatar_telemetry.inject_into_agent_context"),
```

The cache attribute `self._last_self_avatar_snap` is populated by `observe_self_avatar()` after the snapshot is built (one extra line in D4 sets it). Keeps the sensorium method synchronous and side-effect-free.

**Default OFF** is non-negotiable. The existing `_build_cognitive_baseline` prompt budget is sensitive — adding ~150 tokens to every reasoning cycle without operator opt-in is a behavioural regression.

### D6 — Reply-emit hook in chat handler

**Modify:** `src/probos/routers/agents.py`.

Read the chat handler at HEAD (line 460+). The reply text is finalised at the line `response_text = re.sub(...)` (BF-120 markdown stripping, line ~501). Insert the call AFTER all post-processing finalises `response_text` and BEFORE the final `return` statement of the handler:

```python
    # AD-722: stamp the last-reply emission timestamp. Single source of truth.
    if hasattr(agent, 'mark_reply_emitted'):
        agent.mark_reply_emitted()
```

The `hasattr` guard handles the non-`CognitiveAgent` path (handler accepts any registered agent; only crew agents get DM, but defensive guard costs nothing). **Exactly one call site.** If multiple `return` paths exist in the handler that emit reply text, the call moves into a private helper named `_finalize_reply` taking `(agent, response_text) -> str` so the call site stays singular — Demeter / single-source-of-truth.

### D7 — HTTP endpoint: `GET /api/agent/{agent_id}/avatar-telemetry`

**Modify:** `src/probos/routers/agents.py`.

Insert next to the appearance endpoints (after line 418's `PUT /{agent_id}/appearance`):

```python
@router.get("/{agent_id}/avatar-telemetry")
async def agent_avatar_telemetry(agent_id: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-722: read-only avatar telemetry snapshot."""
    # Reuse the AD-721 3D-avatar feature gate (raises 503 when disabled).
    _avatars_feature_check(runtime)

    # AD-722-specific gate (DO NOT extend _avatars_feature_check — single-responsibility).
    cfg = runtime.config.avatar_telemetry
    if not cfg.enabled:
        raise HTTPException(status_code=503, detail="avatar_telemetry_disabled")

    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    from probos.avatars.telemetry import build_telemetry_snapshot
    snap = await build_telemetry_snapshot(agent_id, runtime)
    return snap.to_dict()
```

Endpoint NEVER returns 422. Malformed persisted DSL → degraded field, 200 response. Same pattern as the appearance routes.

### D8 — Python tests (`tests/test_ad722_avatar_telemetry.py`, new)

**≥ 12 tests.** Use `_FakeRuntime` / `_FakeProfileStore` / `_FakeTrustNetwork` / `_FakeRegistry` / `_FakeBridgeAlerts` stub-class pattern from existing AD-721 tests (e.g., `tests/test_ad721_avatars.py` if present, or mirror the `_Fake*` style used in `tests/test_ad406_agent_profile_panel.py`).

Required cases:

| # | Test | Asserts |
|---|---|---|
| 1 | `test_snapshot_happy_path` | Full DSL, full VoiceProfile, trust history with 2+ entries, no tier-3 alerts → all fields populated, `degraded_reasons=()`. |
| 2 | `test_snapshot_no_dsl_persisted` | `crew.appearance.dsl is None` → `dsl_summary=None`, `"dsl_not_persisted"` in degraded_reasons. |
| 3 | `test_snapshot_dsl_invalid` | `crew.appearance.dsl = {"body": {"type": "invalid_value"}}` → `dsl_summary=None`, `"dsl_invalid"` in degraded_reasons, snapshot still returns 200-shape. |
| 4 | `test_snapshot_no_appearance_profile` | `crew.appearance is None` → multiple degraded reasons accumulate, snapshot still returned. |
| 5 | `test_snapshot_trust_history_too_short` | `get_history` returns 1 entry → `trust_delta == 0.0`, `"insufficient_trust_history"` in degraded_reasons. |
| 6 | `test_snapshot_trust_network_no_method` | `runtime.trust_network` lacks `get_history` (hasattr returns False) → `trust_delta == 0.0`, `"insufficient_trust_history"` (mirrors `routers/agents.py:91` guard). |
| 7 | `test_snapshot_bridge_alerts_unavailable` | `runtime.bridge_alerts is None` → `tier3_alert == False`, `"bridge_alerts_unavailable"` in degraded_reasons. |
| 8 | `test_snapshot_tier3_alert_for_agent` | `bridge_alerts.get_recent_alerts(10)` returns one ALERT-severity entry for `agent_id` → `tier3_alert == True`. |
| 9 | `test_snapshot_voice_profile_missing` | `crew.voice_profile is None` → `applied_modulation is None`, `"voice_profile_missing"` in degraded_reasons. |
| 10 | `test_snapshot_agent_not_found` | `registry.get(agent_id)` returns `None` → snapshot has `degraded_reasons == ("agent_not_found",)` and all per-field defaults. |
| 11 | `test_modulation_byte_parity_with_ts` | File-read `ui/src/audio/voiceModulation.ts`, regex-extract every `(const|export const) NAME = VALUE` line, assert each Python module-top constant matches the corresponding TS literal. **This test fails the build on TS↔Python drift.** |
| 12 | `test_modulation_rule_composition_responding_plus_tier3` | `signals = AgentSignalsSnapshot(trust_delta=0.0, load=1.0, working_state='responding', tier3_alert=True)` → `fired_rules` contains both `'responding_rate'` and `'tier3_rate_volume'`; `rate_factor == clamp(1.0 * RESPONDING_RATE_FACTOR * TIER3_RATE_FACTOR, *RATE_BOUNDS)`. |
| 13 | `test_mouth_active_within_window` | `agent.last_reply_emitted_at = time.time() - 1.0`, default 3.0s window → `mouth_active == True`. |
| 14 | `test_mouth_active_outside_window` | `agent.last_reply_emitted_at = time.time() - 10.0` → `mouth_active == False`. |
| 15 | `test_endpoint_200_happy_path` | `httpx.AsyncClient` against the FastAPI app; happy crew → 200 + JSON shape per `to_dict()`. |
| 16 | `test_endpoint_404_unknown_agent` | Agent not in registry → 404. |
| 17 | `test_endpoint_503_telemetry_disabled` | `cfg.avatar_telemetry.enabled = False` → 503 with detail `"avatar_telemetry_disabled"`. |
| 18 | `test_mark_reply_emitted_singular_call_site` | Static check: `grep -rE "mark_reply_emitted\(\)" src/probos/` returns exactly one match (in `routers/agents.py`). Implementation: `subprocess.run(["python", "-c", "import re; ..."])` or read source files directly and count. **Reviewer fails any test that scans `tests/`** — the assertion is about production source. |

Tests #11, #15, #18 are explicit forcing functions for the cross-language drift (#11), the endpoint contract (#15), and the single-call-site rule (#18). All three are required.

### D9 — `<SelfImageTab>` UI component (`ui/src/components/profile/SelfImageTab.tsx`, new)

```tsx
// AD-722: agent-observable avatar telemetry surface.
// Mouth-active is best-effort — see telemetry.py docstring for semantics.
```

Props: `{ agentId: string; isActive: boolean }`. Polls `/api/agent/{agentId}/avatar-telemetry` every 2000ms when `isActive=true`. `useEffect` registers `setInterval`, cleans up on unmount or when `isActive` flips false.

Five stacked panels:

1. **DSL summary** — body type / hair style / outfit style / primary color swatch (small inline `<svg width="16" height="16"><rect width="16" height="16" fill={primary_color}/></svg>`).
2. **Current signals** — working_state badge (amber `#f0b060` active, dim `#666680` inactive), trust_delta as `+0.12` numeric (no formatted strings — Vitest stability), load 0..1 as a stroke-arc (inline SVG `<path>`), tier3_alert as a stroke-svg alert glyph.
3. **Voice modulation** — pitch_factor / rate_factor / volume_factor as numbers; fired_rules as a stroke-svg labelled list (one `<svg>` per rule).
4. **`mouth_active` indicator** — amber pulse when true (CSS `@keyframes` only — no JS animation lib), dim when false.
5. **Degraded reasons strip** — only renders when `degraded_reasons.length > 0`. Amber outline + reason strings.

**Stroke-only icons.** All inline `<svg>` with `strokeWidth: 1.5`, `strokeLinecap: round`, `fill: none`. **No emoji.** Reviewer greps for emoji codepoints (U+1F000–U+1FFFF, U+2600–U+27BF) and fails on any hit.

**No Zustand store dependency.** Component fetches directly. v1 keeps the store unchanged.

### D10 — Tab registration in `AgentProfilePanel`

**Modify:** `ui/src/components/profile/AgentProfilePanel.tsx`.

```
===SEARCH===
type ProfileTab = 'chat' | 'work' | 'profile' | 'health' | 'memory';
===REPLACE===
type ProfileTab = 'chat' | 'work' | 'profile' | 'health' | 'memory' | 'self_image';
===END REPLACE===
```

Append `{ key: 'self_image', label: 'Self-image' }` to `TAB_LABELS` (line 14).

In the existing tab-render switch (after the `effectiveTab === 'memory'` branch), add:

```tsx
{effectiveTab === 'self_image' && isCrew && (
  <SelfImageTab agentId={agentId} isActive={effectiveTab === 'self_image'} />
)}
```

`isCrew` filter at line 153–155 already excludes `'chat'` and `'memory'` for non-crew agents. Add `'self_image'` to that filter:

```
===SEARCH===
    : TAB_LABELS.filter(t => t.key !== 'chat' && t.key !== 'memory');
===REPLACE===
    : TAB_LABELS.filter(t => t.key !== 'chat' && t.key !== 'memory' && t.key !== 'self_image');
===END REPLACE===
```

### D11 — Vitest tests (`ui/src/__tests__/SelfImageTab.test.tsx`, new)

**≥ 6 tests.** Mirror the harness style of `ui/src/audio/__tests__/voice.test.ts`. Mock `fetch` with `vi.fn()`. `vi.useFakeTimers()` for the 2000ms polling clock.

Required cases:

1. `test_renders_panel_headers` — happy snapshot → all 5 panel headers present in DOM.
2. `test_polls_every_2000ms_when_active` — `isActive=true`, advance 2000ms → `fetch` called twice (mount + tick).
3. `test_stops_polling_when_isactive_false` — toggle `isActive=false`, advance 2000ms → no additional fetch.
4. `test_renders_degraded_reasons_strip` — mocked snapshot with `degraded_reasons=['dsl_invalid']` → strip renders with the reason text.
5. `test_renders_modulation_factors_as_numbers` — mocked `applied_modulation.rate_factor=1.05` → asserts the rendered text is `1.05` (no formatted unit strings).
6. `test_mouth_active_amber_when_true` — mocked `mouth_active=true` → amber-active stroke state (assert via `getByTestId` + `style.stroke` or class assertion).

### D12 — Cross-reference comment in `voiceModulation.ts`

**Modify:** `ui/src/audio/voiceModulation.ts`.

Add a one-line block comment above line 17 (the `MODULATION_DIVERGENCE_THRESHOLD` constant):

```ts
// NOTE: this rule table is duplicated in src/probos/avatars/telemetry.py.
// Keep them in lockstep. AD-722-1 will extract to a YAML manifest.
```

### D13 — Cross-reference docstring in `avatarSignals.ts`

**Modify:** `ui/src/components/profile/avatarSignals.ts`.

Add one line to the existing module docstring (or top-of-file comment):

```ts
// Backend re-derivation: src/probos/avatars/telemetry.py module docstring is the
// single source of truth for the (trust_delta, load, working_state, tier3_alert)
// rule table. v1 ships intentional UI/backend duplication; AD-722-1 manifest closes it.
```

---

## 7. Tests required

- **Python:** ≥ 12 tests (D8 enumerates 18 — Builder may consolidate but cannot drop the byte-parity, endpoint, and singular-call-site cases).
- **Vitest:** ≥ 6 tests (D11 enumerates 6 — minimum).

---

## 8. Hard-stop conditions (verbatim from dispatch §8 — read-only is non-negotiable)

The Builder MUST stop and surface to architect (do not improvise) when:

1. **Read-only contract violated.** Any deliverable mutates `TrustNetwork`, Hebbian routing, `RecordsStore`, `crew_profiles.data`, or any persistent state. Read-only is non-negotiable. Forward marker AD-722a is the consumer that mutates.
2. **WebSocket / push channel introduced.** v1 is poll. Any deliverable that opens a WebSocket route, spawns a server-side push task, or modifies the existing intent bus to emit telemetry events is out of scope. Forward marker AD-722b.
3. **Records writes.** Any deliverable that writes to `runtime.records_store` or constructs a `RecordsEntry`. Forward marker AD-722d.
4. **Image bytes.** Any deliverable that imports Blender, opens a `subprocess` to a renderer, calls `canvas.toBlob`, or returns image data from the endpoint. Forward marker AD-722e.
5. **New top-level dep.** `pyproject.toml [project.dependencies]` or `ui/package.json` `"dependencies"` / `"devDependencies"` change in any way. Reviewer runs `git diff <pre>..<post> -- pyproject.toml ui/package.json` — any non-empty output is a hard fail.
6. **Phantom API discovered.** Any concrete claim in §2 fails to verify against the actual codebase at the Builder's commit time. Stop, surface, and request a prompt revision.
7. **HXI-fragile file touched.** `CognitiveCanvas.tsx`, `agents.tsx`, `animations.tsx`, `CrewVRM.tsx`, `ParametricAvatar.tsx` MUST stay untouched. Hard stop on any diff.
8. **Multiple `mark_reply_emitted()` call sites.** If the chat handler's reply-text emission has more than one terminal `return` path, the call MUST move into a private helper. The grep at D8 #18 must return exactly one match in production source.

**HARD RULE — UI build gate:** Run `cd ui && npm run build` AFTER writing code and BEFORE pushing. Type errors in the new TSX file or in the modified `AgentProfilePanel.tsx` MUST be caught locally — the test gate alone does not cover full TypeScript compilation against the production tsconfig.

---

## 9. Wave-specific reminders

1. **Trust history method may not exist.** `runtime.trust_network.get_history(...)` is called via `hasattr` guard at `routers/agents.py:91`. The method is not defined on `TrustNetwork`. Mirror the guard. Degraded reason `"insufficient_trust_history"` covers both "method absent" and "history < 2 entries".
2. **`mouth_active` is a known approximation.** Documented in three places: `AvatarTelemetrySnapshot` docstring, `<SelfImageTab>` top comment, and §1 above. AD-722b makes it authoritative.
3. **Prompt-context injection is default OFF.** v1 does not change agent behaviour out of the box. Operator flips `inject_into_agent_context: True` to test the loop.
4. **`mark_reply_emitted` has exactly one call site.** D8 #18 enforces this with a grep against production source.
5. **No private-attr access.** Telemetry reads `agent.last_reply_emitted_at` (public property), never `agent._last_reply_emit_ts`. All `runtime.*` reads are public.
6. **`<SelfImageTab>` does NOT route through Zustand.** Polls the HTTP endpoint directly. Store stays unchanged.
7. **`degraded_reasons` is the tier-2 observability hook.** Every degraded path adds a structured reason and the snapshot still returns. The HTTP endpoint NEVER returns 422 for malformed persisted DSL.
8. **No emoji.** All `<SelfImageTab>` icons are inline `<svg>` with `strokeWidth: 1.5`, `strokeLinecap: round`. Active = amber `#f0b060`, inactive = `#666680`.
9. **Verify-first.** Before any concrete file/line/method citation in the implementation, Builder greps HEAD and pastes the result in the commit message body. Especially every line number cited from the files in §2.

---

## 10. Tracking

After AD-722 v1 ships:

1. **`PROGRESS.md`** — flip the AD-722 row to ✅ in the Wave 140 section. One-line outcome: *"Agent-observable avatar telemetry channel — read-side; CognitiveAgent.observe_self_avatar() + GET /api/agent/{id}/avatar-telemetry + <SelfImageTab>; feature-gated prompt injection default OFF."*
2. **`docs/development/roadmap.md`** — close Wave 140 row. Add forward-marker rows: AD-722a, AD-722b, AD-722c, AD-722d, AD-722e, AD-722-1. File GH issues for all six.
3. **`DECISIONS.md` + `decisions-era-5-unification.md`** — append AD-722 entry. Cite (a) read-only-v1 contract, (b) poll-not-push trade-off, (c) duplicated modulation rule table as v1 cost + AD-722-1 path, (d) `mouth_active` 3-second window approximation, (e) feature-gated prompt injection default-OFF rationale.
4. **GH issues** — close [#545](https://github.com/seangalliher/ProbOS/issues/545) with summary comment. File AD-722a / AD-722b / AD-722c / AD-722d / AD-722e / AD-722-1 markers.
5. **`session/wave-queue-batch2.md`** — append `W140 #545 done (+12 pytest, +6 vitest)` to the Done section.

---

## 11. Acceptance criteria

1. ✅ One commit. Reviewer fails any split — AD-722 v1 is a single atomic feature.
2. ✅ `pytest tests/ -q -n 4 --dist=loadfile` green at the commit. Test count delta: ≥ +12.
3. ✅ `cd ui && npx vitest run` green at the commit. Test count delta: ≥ +6.
4. ✅ `cd ui && npm run build` green at the commit (HARD RULE — see §8).
5. ✅ Existing AD-721 / AD-721b / AD-721d / AD-718d tests stay green. Reviewer fails any modification of those test bodies.
6. ✅ `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-722-avatar-telemetry-v1.md` clean.
7. ✅ `pyproject.toml [project.dependencies]` AND `ui/package.json` `"dependencies"` + `"devDependencies"` are bit-for-bit identical pre/post commit.
8. ✅ Manual smoke: open the HXI, click any crew agent's profile, switch to the new "Self-image" tab. Within 2 seconds the panel populates. Send the agent a message — within 3 seconds the `mouth_active` indicator pulses amber, then settles to dim.
9. ✅ Manual smoke: with `inject_into_agent_context=False` (default), agent chat replies are byte-for-byte unchanged from baseline (re-run any AD-721d appearance-proposal test as the regression guard).
10. ✅ **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 12. Forward markers (Builder mints these as GH issues during retrospective)

| Marker | One-line description |
|---|---|
| **AD-722a** | First consumer: intent-vs-presentation divergence detector → trust/Hebbian update |
| **AD-722b** | Push channel via WebSocket (server-sent telemetry) |
| **AD-722c** | Avatar-telemetry history for analytics |
| **AD-722d** | Auto-write telemetry to `RecordsStore` |
| **AD-722e** | Visual self-perception via image rendering |
| **AD-722-1** | Modulation rule table extracted to YAML/JSON manifest |
