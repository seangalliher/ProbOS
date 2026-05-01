# Review: AD-455 — Security Team (Threat Detection & Trust Integrity)

**Reviewer:** Architect (self-review of own draft)
**Date:** 2026-05-01
**Verdict:** ❌ **Not Ready** — two phantom APIs (`RedTeamAgent.run_probe`, `runtime.red_team_agents`) cause the RedTeamLead campaign to silently no-op in production. Dispatch's pre-flag was on the right finding. Largest, highest-risk Wave 5 prompt; merits a full re-pass.

---

## Required (must fix before building)

### 1. `RedTeamAgent.run_probe` does NOT exist; the prompt asks the Builder to define a phantom interface

Verified — `RedTeamAgent` exposes a different public API:

```
grep -n "async def" src/probos/agents/red_team.py
  66: async def verify(
  101: async def _verify_read(
  187: async def _verify_stat(
  279: async def _verify_run_command(
  397: async def _verify_http_fetch(
  491: async def _verify_write(
  557: async def perceive(self, intent: dict[str, Any]) -> Any:
  560: async def decide(self, observation: Any) -> Any:
  563: async def act(self, plan: Any) -> Any:
  566: async def report(self, result: Any) -> dict[str, Any]:
```

The actual public verification API is `verify(...)`. AD-455's Section 5 calls `await agent.run_probe()` and the builder note says:

> verify-first via `grep "def run_probe\b" src/probos/agents/red_team.py`. If absent, the Builder must add a minimal `async def run_probe(self) -> ProbeResult` to `RedTeamAgent` that returns `ProbeResult(found_issue=False)` as a no-op default. This is the only source-code change outside the new `security/` package.

This is wrong on two counts:
- **Phantom API in the body, not just the verify-first.** A build prompt must NOT defer phantom-API resolution to the Builder. Either (a) the prompt designs and adds `run_probe` as a Section, or (b) AD-455 uses the existing `verify()` API.
- **The proposed default no-ops the campaign.** A `run_probe` that returns `found_issue=False` regardless of ship state means RedTeamLead's campaign produces always-zero findings. The deliverable is theater.

**Action:** Pick one:
- (a) AD-455 dispatches existing `RedTeamAgent.verify()` calls with a curated set of synthetic intents. RedTeamLead becomes a coordinator over the real verification path; no new method on `RedTeamAgent`.
- (b) AD-455 adds `run_probe` as a real method that selects a meaningful probe target (e.g., random-sample tool invocation, sample of recent agent intents). This is a substantial design decision; surface to a separate AD if pursued.

Recommended (a). The existing verify-driven probe surface is rich; coordinator-pattern reuse is straightforward.

### 2. `runtime.red_team_agents` does NOT exist; private name silently no-ops

The prompt's Section 5 reads:

```python
agents = list(getattr(self._runtime, "red_team_agents", []) or [])
```

Verified — only `_red_team_agents` (private) exists:

```
grep -n "red_team_agents" src/probos/runtime.py
  246:    _red_team_agents: list[RedTeamAgent]
  343:        self._red_team_agents: list[RedTeamAgent] = []
  1128:            self._red_team_agents.append(agent)

grep -n "red_team_agents" src/probos/startup/agent_fleet.py
  231:    # Spawn red team agents (populates runtime._red_team_agents in-place)
  232:    await spawn_red_team_fn(config.consensus.red_team_pool_size)
  238:        red_team_agents=[],  # populated directly on runtime by spawn_red_team_fn
```

The `getattr(rt, "red_team_agents", [])` returns the default `[]` because the public name doesn't exist. Loop body never runs. Silent failure — tests that pass a mock with the public name pass, production wiring stays broken.

**Action:** AD-455 must promote `_red_team_agents` to public — either rename it to `red_team_agents` or add a `@property`:

```python
@property
def red_team_agents(self) -> list[RedTeamAgent]:
    return self._red_team_agents
```

Pattern from AD-680. Add this as a Section 0a or Section 1a.

### 3. `runtime._threat_detector`, `_trust_integrity_monitor`, `_input_validator`, `_red_team_lead` are all written as private — same Demeter issue as AD-440 finding #1

Section 8 sets four private attributes on the runtime:

```python
runtime._threat_detector = threat_detector
runtime._trust_integrity_monitor = trust_integrity
runtime._input_validator = input_validator
runtime._red_team_lead = red_team_lead
```

Same anti-pattern as AD-440. AD-455 should publish these as public attributes (no underscore) per the AD-680 standard. This sets the precedent for AD-456 onwards, where security middleware will need to consume `runtime.input_validator` from FastAPI dependency wiring.

**Action:** Drop the leading underscore on all four. Update Section 8 wiring + any references in `RedTeamLead.__init__(runtime=runtime)` (which reads `getattr(runtime, "red_team_agents", ...)` per finding #2).

### 4. `shutdown.py` integration prose is fuzzy — needs a concrete SEARCH/REPLACE

Section 8 says:

> Add a `stop_security_team()` invocation in `src/probos/startup/shutdown.py` that awaits `runtime._red_team_lead.stop()` if present. Mirror the pattern used by other start/stop services in shutdown.py.

The existing pattern (verified) is direct line-by-line awaits, not a wrapper function:

```
grep -n "stop\|await" src/probos/startup/shutdown.py | head -10
  54:        await runtime.event_log.log(category="system", event="stopping")
  128:        await runtime.episodic_memory.stop()
  133:        await _eviction_audit.stop()
  143:        await runtime.acm.stop()
  148:        await runtime.identity_registry.stop()
```

There is no `stop_security_team()` wrapper convention. The Builder will guess where to put the line. Provide a real SEARCH/REPLACE block keyed on an existing await (e.g., insert after `runtime.episodic_memory.stop()`).

**Action:** Replace the prose with a SEARCH/REPLACE block.

### 5. `RedTeamLead._loop` exception handling swallows non-cancellation exceptions silently

```python
except asyncio.CancelledError:
    raise
```

is correct, but the inner loop:

```python
try:
    await self._run_campaign()
except Exception:
    logger.exception("AD-455: campaign run failed")
```

Then the loop continues. A persistent failure (e.g., `runtime.red_team_agents` raises every cycle) emits a log every interval forever. Either:
- (a) Add a consecutive-failure counter that disables the campaign loop after N failures, with one ERROR log on disable.
- (b) Document that the campaign is best-effort and persistent failures are operator's responsibility to diagnose via logs.

**Action:** Pick (b) and add a one-line note in the docstring; or pick (a) and add a counter. Either is fine for a v1; making the choice explicit avoids a future BF.

---

## Recommended

### R1. `ThreatDetector` patterns are static `re.compile`d at import time — cannot be tuned

`_PROMPT_INJECTION_PATTERNS` and `_JAILBREAK_PATTERNS` are hardcoded module-level lists. Operators will want to tune severity weights or add domain-specific patterns. Move them to `SecurityConfig` (Pydantic) so config can override. v1 can ship the static list with a follow-up note.

### R2. `InputValidator` rate-limit history is unbounded

`self._history: dict[str, deque[float]] = {}` grows one entry per source. A high-cardinality source space (e.g., per-IP) could OOM the runtime. Add a `max_sources: int = 1024` LRU eviction or a periodic prune. Non-blocking for v1 if scope is documented as "trusted-source IDs only."

### R3. `TrustIntegrityMonitor` API is described but not implemented in Section 3

Section 3 says:

> API surface:
> ```python
> class TrustIntegrityMonitor:
>     def __init__(self, *, trust_network, event_log, emit_event=None, ...): ...
>     def analyze(self) -> TrustIntegrityReport: ...
> ```

The body of `analyze()` is left to the Builder. For a Required-section AD prompt, the body should be specified — at minimum, the three detection algorithms (burst voting, mutual loops, anomalous velocity) need pseudocode or sketch. Without it, two Builder implementations would produce two different trust-integrity surfaces.

**Action:** Add a 30-line sketch for `analyze()` with each of the three checks. Or split AD-455 — `TrustIntegrityMonitor` could be its own AD (e.g., AD-455b) since it is the most algorithmically dense of the four services.

### R4. `SecurityConfig` defaults need `Field` validation

`max_payload_bytes: int = 65536` — accepts negative values. Add `Field(ge=1024)`. Same for the rate fields. Pattern from `health_probe_interval_seconds` at `config.py:1587`.

### R5. Section 5 `RedTeamLead.start()` creates a task but doesn't store it as a strong reference until later

The line `self._task = asyncio.create_task(...)` does store the reference correctly. Verified clean. Calling out for the audit trail since "fire-and-forget create_task" is a flagged anti-pattern.

---

## Nits

- `_ABNORMAL_TOKEN_RATIO = 0.20` is module-level but only used inside `ThreatDetector.scan`. Either move it inside the class or document why module-level. Cosmetic.
- `tests/test_ad455_trust_integrity.py` is mentioned as a possible split-out file. Decide before Builder picks up; "may live in" is ambiguous.
- `EventType.SECURITY_INPUT_REJECTED` — the noun is "input"; the verb form `_REJECTED` matches the codebase's emit-on-deny convention. Fine.
- `RedTeamLead.start()` is idempotent (returns early if `_task is not None`). Good.

---

## Verified

- `class RedTeamAgent` at `agents/red_team.py:25` ✓
- `class SystemQAAgent` at `agents/system_qa.py:69` ✓
- `spawn_red_team_fn` at `agent_fleet.py:38, 232` ✓
- `runtime.trust_network` (public) at `runtime.py:335` ✓
- `runtime.event_log` (public) at `runtime.py:314` ✓
- `runtime.emit_event` post-AD-680 ✓
- No `prompt_injection|input_validator|trust_integrity|sybil` symbols in src/ ✓
- `DISCLOSURE_FILTERED` at `events.py:179` (insertion neighborhood) ✓
- `firewall: FirewallConfig` at `config.py:1531` (config insertion neighborhood) ✓
- `_disclosure_router = disclosure_router` at `finalize.py:330` (wiring neighborhood) ✓
- `src/probos/security/` does NOT exist — AD-455 owns directory creation ✓
- No EventType collision with AD-439/440/468/499 ✓

---

## Required Disposition

❌ **Not Ready.** Five Required findings, two of which (`run_probe` phantom, `red_team_agents` private-name silent failure) cause the AD's primary deliverable to no-op in production. Estimated rework: ~45 minutes architect time — this is the heaviest revision in Wave 5.

After fixes, re-pass review. AD-455 should land **after** AD-468 (which establishes the Demeter pattern for new public attributes) and before AD-440 (which mirrors that pattern). Recommended Wave 5 build order: AD-499 → AD-439 → AD-468 → AD-455 → AD-440.
