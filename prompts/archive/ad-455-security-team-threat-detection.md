# AD-455: Security Team — Threat Detection & Trust Integrity

**Status:** Ready for builder
**Dependencies:** None hard. RedTeamAgent (`src/probos/agents/red_team.py:25`) already exists; this AD spawns and coordinates a security pool around it. **AD-455 OWNS `src/probos/security/__init__.py` package creation**, mirroring AD-676's `governance/` precedent.
**Estimated tests:** ~12
**Risk:** High — cross-cutting (events.py, runtime.py, config.py, startup/finalize.py, agent_fleet.py). Touches authentication-adjacent surfaces (input validation, trust integrity).

---

## Problem

ProbOS has fragmented security capabilities:

- `RedTeamAgent` (`src/probos/agents/red_team.py:25`) — adversarial agent; runs verification probes but not as a permanent monitoring pool.
- `SystemQAAgent` (`src/probos/agents/system_qa.py:69`) — testing/QA only.
- No prompt-injection scanner, no input validator, no trust-integrity (Sybil/coordinated-attack) monitor — verified absent (`grep -rn "prompt_injection|input_validator|trust_integrity|sybil" src/probos/` returned no matches).
- `src/probos/security/` package does NOT exist — verified.

There is no Security Team substrate that classifies threats, monitors trust manipulation, validates incoming inputs against rate/payload/content policy, and coordinates RedTeamAgent campaigns.

## Solution Overview

Create the `src/probos/security/` package and add four security services:

1. **`ThreatDetector`** — scans inputs and Ward Room messages for adversarial patterns (prompt injection markers, abnormal token sequences, jailbreak heuristics). Read-only signal layer; emits `EventType.THREAT_DETECTED`.
2. **`TrustIntegrityMonitor`** — watches the `TrustNetwork` for coordinated trust manipulation. Detects (a) burst voting (one source firing many record_outcome calls in a short window), (b) cycles (mutual high-trust loops with no external evidence), (c) anomalous trust velocity. Emits `EventType.TRUST_INTEGRITY_VIOLATION`.
3. **`InputValidator`** — boundary policy for incoming requests: rate limiting, payload size, content policy. Async, callable from API and CLI surfaces.
4. **`RedTeamLead`** — coordinates existing `RedTeamAgent` instances (`runtime.red_team_agents`, populated by `agent_fleet.spawn_red_team_fn` at line 232). Schedules adversarial verification campaigns; produces a periodic security report.

All four services are **policy + diagnostics**, not enforcement. Enforcement is left to upstream callers (e.g., the FastAPI middleware can call `InputValidator.check()` and reject 4xx; AD-456 will add the actual middleware integration).

---

## Section 0: Event Types

Add to `src/probos/events.py` near the existing security/diagnostic block:

```
THREAT_DETECTED = "threat_detected"  # AD-455
TRUST_INTEGRITY_VIOLATION = "trust_integrity_violation"  # AD-455
SECURITY_INPUT_REJECTED = "security_input_rejected"  # AD-455
RED_TEAM_CAMPAIGN_COMPLETE = "red_team_campaign_complete"  # AD-455
```

Four new values. Verified absent via `grep -n "THREAT_|TRUST_INTEGRITY|SECURITY_INPUT|RED_TEAM_CAMPAIGN" src/probos/events.py` (no matches).

---

## Section 0a: Promote `_red_team_agents` to public on `ProbOSRuntime`

**File:** `src/probos/runtime.py`

`_red_team_agents` is private (verified at `runtime.py:246, 343`). AD-455's `RedTeamLead` reads it from a different module — that's the cross-module Demeter violation. Promote to public `red_team_agents` following the AD-680 pattern.

SEARCH:
```python
    # Private attributes
    _data_dir: Path
    _checkpoint_dir: Path
    _red_team_agents: list[RedTeamAgent]
```

REPLACE:
```python
    # Private attributes
    _data_dir: Path
    _checkpoint_dir: Path
```

Then add `red_team_agents` to the public attribute block (search for `proactive_loop:` to find the deferred-init block):

```python
    red_team_agents: list[RedTeamAgent]
```

Update `__init__` and `spawn_red_team` accordingly:

SEARCH:
```python
        self._red_team_agents: list[RedTeamAgent] = []
```

REPLACE:
```python
        self.red_team_agents: list[RedTeamAgent] = []
```

SEARCH (around `runtime.py:1128`):
```python
            self._red_team_agents.append(agent)
```

REPLACE:
```python
            self.red_team_agents.append(agent)
```

> Verify-first: this is a one-shot rename, no deprecation period (AD-680 precedent). Builder also greps for any other `_red_team_agents` reference in src/ and updates. Expected: 3 sites total.

## Section 1: Create `src/probos/security/` package

**IMPORTANT:** `src/probos/security/` does NOT exist. Create `src/probos/security/__init__.py` (empty file) before any other security module — same pattern AD-676 used for `src/probos/governance/__init__.py`.

```python
# src/probos/security/__init__.py
"""Security Team — Threat Detection & Trust Integrity (AD-455)."""
```

---

## Section 2: `ThreatDetector`

**File:** `src/probos/security/threat_detector.py` (new)

```python
"""AD-455: Threat detection — adversarial input pattern scanning."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


class ThreatCategory(str, Enum):
    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK = "jailbreak"
    ABNORMAL_TOKENS = "abnormal_tokens"


@dataclass(frozen=True)
class ThreatSignal:
    category: ThreatCategory
    severity: float  # 0.0–1.0
    matched_pattern: str
    snippet: str
    detected_at: float


_PROMPT_INJECTION_PATTERNS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"ignore (?:all )?previous instructions", re.I), 0.95),
    (re.compile(r"disregard (?:the |your )?(?:system|standing) (?:prompt|orders?)", re.I), 0.90),
    (re.compile(r"</?(?:system|admin|root)>", re.I), 0.80),
    (re.compile(r"\[\[.*?inject.*?\]\]", re.I | re.S), 0.85),
]

_JAILBREAK_PATTERNS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"DAN mode|developer mode enabled|do anything now", re.I), 0.90),
    (re.compile(r"you are now (?:free|unrestricted|jailbroken)", re.I), 0.85),
]

_ABNORMAL_TOKEN_RATIO = 0.20  # >20% non-printable / non-ASCII triggers abnormal


class ThreatDetector:
    """Stateless scanner. Each scan emits a list of ThreatSignal."""

    def __init__(self, *, emit_event: Any | None = None) -> None:
        self._emit_event = emit_event

    def scan(self, text: str, *, source: str = "unknown") -> list[ThreatSignal]:
        if not text:
            return []
        signals: list[ThreatSignal] = []
        now = time.time()

        for pat, severity in _PROMPT_INJECTION_PATTERNS:
            m = pat.search(text)
            if m:
                signals.append(ThreatSignal(
                    category=ThreatCategory.PROMPT_INJECTION,
                    severity=severity, matched_pattern=pat.pattern,
                    snippet=text[max(0, m.start() - 20): m.end() + 20][:140],
                    detected_at=now,
                ))

        for pat, severity in _JAILBREAK_PATTERNS:
            m = pat.search(text)
            if m:
                signals.append(ThreatSignal(
                    category=ThreatCategory.JAILBREAK,
                    severity=severity, matched_pattern=pat.pattern,
                    snippet=text[max(0, m.start() - 20): m.end() + 20][:140],
                    detected_at=now,
                ))

        if len(text) >= 32:
            non_printable = sum(1 for c in text if not (c.isprintable() or c in "\n\r\t"))
            ratio = non_printable / len(text)
            if ratio > _ABNORMAL_TOKEN_RATIO:
                signals.append(ThreatSignal(
                    category=ThreatCategory.ABNORMAL_TOKENS,
                    severity=min(1.0, ratio * 2),
                    matched_pattern=f"non_printable_ratio>{_ABNORMAL_TOKEN_RATIO}",
                    snippet=text[:80],
                    detected_at=now,
                ))

        for s in signals:
            self._emit(source, s)
        return signals

    def _emit(self, source: str, signal: ThreatSignal) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.THREAT_DETECTED,
                {
                    "source": source,
                    "category": signal.category.value,
                    "severity": signal.severity,
                    "matched_pattern": signal.matched_pattern,
                    "snippet": signal.snippet,
                },
            )
        except Exception:
            logger.warning("AD-455: THREAT_DETECTED emit failed", exc_info=True)
```

---

## Section 3: `TrustIntegrityMonitor`

**File:** `src/probos/security/trust_integrity.py` (new)

Stateless analyzer that takes a `TrustNetwork` reference and a recent-events window, looking for burst votes, mutual loops, and abnormal velocity. Emits `EventType.TRUST_INTEGRITY_VIOLATION`. Use the public `TrustNetwork` API only — verify methods via `grep "def " src/probos/consensus/trust.py`. Do NOT touch raw `(alpha, beta)` storage; read derived signals only.

API surface:
```python
class TrustIntegrityMonitor:
    def __init__(self, *, trust_network, event_log, emit_event=None,
                 burst_window_seconds: float = 60.0, burst_threshold: int = 20,
                 cycle_min_weight: float = 0.85): ...
    def analyze(self) -> TrustIntegrityReport: ...
```

`analyze()` returns a `TrustIntegrityReport(violations: list[Violation], generated_at: float, sample_size: int)`. Each `Violation` carries `kind`, `agents_involved`, `evidence`, `severity`.

---

## Section 4: `InputValidator`

**File:** `src/probos/security/input_validator.py` (new)

```python
"""AD-455: Input validator — rate / payload / content policy gate."""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from probos.events import EventType
from probos.security.threat_detector import ThreatDetector

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    reason: str = ""
    threats: tuple = ()


class InputValidator:
    """Per-source rate + size + content policy gate.

    Stateful in-memory. Source = stable identifier (DID, IP, agent_id).
    """

    def __init__(
        self,
        *,
        threat_detector: ThreatDetector,
        emit_event: Any | None = None,
        max_payload_bytes: int = 64 * 1024,
        rate_window_seconds: float = 60.0,
        rate_max_requests: int = 60,
        max_threat_severity: float = 0.80,
    ) -> None:
        self._threat = threat_detector
        self._emit_event = emit_event
        self._max_payload = max_payload_bytes
        self._window = rate_window_seconds
        self._rate_max = rate_max_requests
        self._max_threat_severity = max_threat_severity
        self._history: dict[str, deque[float]] = {}

    def check(self, *, source: str, payload: str) -> ValidationResult:
        if len(payload.encode("utf-8")) > self._max_payload:
            return self._reject(source, "payload_too_large")

        now = time.time()
        hist = self._history.setdefault(source, deque())
        while hist and now - hist[0] > self._window:
            hist.popleft()
        if len(hist) >= self._rate_max:
            return self._reject(source, "rate_limit")
        hist.append(now)

        threats = self._threat.scan(payload, source=source)
        max_sev = max((t.severity for t in threats), default=0.0)
        if max_sev >= self._max_threat_severity:
            return self._reject(source, f"content_policy:{max_sev:.2f}", tuple(threats))

        return ValidationResult(accepted=True, threats=tuple(threats))

    def _reject(self, source: str, reason: str, threats: tuple = ()) -> ValidationResult:
        if self._emit_event:
            try:
                self._emit_event(
                    EventType.SECURITY_INPUT_REJECTED,
                    {"source": source, "reason": reason},
                )
            except Exception:
                logger.warning("AD-455: SECURITY_INPUT_REJECTED emit failed", exc_info=True)
        return ValidationResult(accepted=False, reason=reason, threats=threats)
```

---

## Section 5: `RedTeamLead` — health-monitor coordinator (revised)

**File:** `src/probos/security/red_team_lead.py` (new)

`RedTeamAgent` exposes `verify(target_agent_id, intent, claimed_result) -> VerificationResult` (verified at `agents/red_team.py:66`). That signature requires a triple — synthesizing it for a campaign would either pollute the trust network with synthetic intents or require an entirely new probe scheduler outside the AD's scope.

**Decision (architect, 2026-05-01):** v1 RedTeamLead is a **health-monitor coordinator**, not an adversarial scheduler. It:
- Inventories `runtime.red_team_agents` periodically.
- Counts `is_alive` agents vs total.
- Emits `EventType.RED_TEAM_CAMPAIGN_COMPLETE` with the rollup.

Adversarial dispatch — synthesizing intents for `verify()` and recording outcomes — is **deferred to AD-455b** (queued separately). This v1 ships a real, useful surface (operator visibility into red team availability) without phantom APIs and without `run_probe` theater.

```python
"""AD-455: Red team lead — health-monitor coordinator over RedTeamAgent pool.

Periodically inventories the red team pool and reports availability.
Does NOT synthesize new probes — that is AD-455b's scope. v1 surfaces
operator visibility into red team readiness without polluting the
trust network.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CampaignReport:
    """One health-monitor cycle outcome."""

    started_at: float
    completed_at: float
    agents_total: int
    agents_alive: int
    consecutive_failures: int
    summary: str


class RedTeamLead:
    """Coordinates existing RedTeamAgents — health monitor only.

    `runtime.red_team_agents` is the public list populated by
    agent_fleet.spawn_red_team_fn (verified at agent_fleet.py:232).
    """

    MAX_CONSECUTIVE_FAILURES = 5

    def __init__(
        self,
        *,
        runtime: Any,
        emit_event: Any | None = None,
        campaign_interval_seconds: float = 3600.0,
    ) -> None:
        self._runtime = runtime
        self._emit_event = emit_event
        self._interval = campaign_interval_seconds
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._last_report: CampaignReport | None = None
        self._consecutive_failures = 0

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="ad455-red-team-lead")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                logger.debug("AD-455: red team lead task cancelled cleanly")
            self._task = None

    @property
    def last_report(self) -> CampaignReport | None:
        return self._last_report

    async def run_campaign_now(self) -> CampaignReport:
        return await self._run_campaign()

    async def _loop(self) -> None:
        try:
            while not self._stopping.is_set():
                try:
                    await self._run_campaign()
                    self._consecutive_failures = 0
                except Exception:
                    self._consecutive_failures += 1
                    logger.exception(
                        "AD-455: campaign run failed (%d/%d)",
                        self._consecutive_failures, self.MAX_CONSECUTIVE_FAILURES,
                    )
                    if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                        logger.error(
                            "AD-455: campaign disabled after %d consecutive failures; "
                            "operator must restart to resume",
                            self.MAX_CONSECUTIVE_FAILURES,
                        )
                        return
                try:
                    await asyncio.wait_for(self._stopping.wait(), timeout=self._interval)
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise

    async def _run_campaign(self) -> CampaignReport:
        started = time.time()
        agents = list(getattr(self._runtime, "red_team_agents", []) or [])
        total = len(agents)
        alive = sum(1 for a in agents if getattr(a, "is_alive", True))
        completed = time.time()
        report = CampaignReport(
            started_at=started, completed_at=completed,
            agents_total=total, agents_alive=alive,
            consecutive_failures=self._consecutive_failures,
            summary=f"red_team_pool: {alive}/{total} alive",
        )
        self._last_report = report
        if self._emit_event:
            try:
                self._emit_event(
                    EventType.RED_TEAM_CAMPAIGN_COMPLETE,
                    {
                        "agents_total": total,
                        "agents_alive": alive,
                        "duration_seconds": completed - started,
                    },
                )
            except Exception:
                logger.warning("AD-455: campaign emit failed", exc_info=True)
        return report
```

> Verify-first: `RedTeamAgent.is_alive` is inherited from `BaseAgent`. `runtime.red_team_agents` is the public attribute introduced in Section 0a. No new method is added to `RedTeamAgent` — its `verify()` API is untouched.

---

## Section 6: Add EventTypes

**File:** `src/probos/events.py`

SEARCH:
```python
    DISCLOSURE_FILTERED = "disclosure_filtered"  # AD-679
```

REPLACE:
```python
    DISCLOSURE_FILTERED = "disclosure_filtered"  # AD-679
    THREAT_DETECTED = "threat_detected"  # AD-455
    TRUST_INTEGRITY_VIOLATION = "trust_integrity_violation"  # AD-455
    SECURITY_INPUT_REJECTED = "security_input_rejected"  # AD-455
    RED_TEAM_CAMPAIGN_COMPLETE = "red_team_campaign_complete"  # AD-455
```

---

## Section 7: `SecurityConfig`

**File:** `src/probos/config.py`

```python
class SecurityConfig(BaseModel):
    """Security Team configuration (AD-455)."""

    enabled: bool = True
    max_payload_bytes: int = Field(default=65536, ge=1024)
    rate_window_seconds: float = Field(default=60.0, ge=1.0)
    rate_max_requests: int = Field(default=60, ge=1)
    max_threat_severity: float = Field(default=0.80, ge=0.0, le=1.0)
    burst_window_seconds: float = Field(default=60.0, ge=1.0)
    burst_threshold: int = Field(default=20, ge=2)
    campaign_interval_seconds: float = Field(default=3600.0, ge=60.0)
```

Wire into `SystemConfig`:

SEARCH:
```python
    firewall: FirewallConfig = FirewallConfig()
```

REPLACE:
```python
    firewall: FirewallConfig = FirewallConfig()
    security: SecurityConfig = SecurityConfig()  # AD-455
```

---

## Section 8: Wire into startup

**File:** `src/probos/startup/finalize.py`

Place after the AD-679 disclosure router (verified at `finalize.py:330`):

```python
    # AD-455: Security Team
    if config.security.enabled:
        from probos.security.threat_detector import ThreatDetector
        from probos.security.trust_integrity import TrustIntegrityMonitor
        from probos.security.input_validator import InputValidator
        from probos.security.red_team_lead import RedTeamLead

        threat_detector = ThreatDetector(emit_event=runtime.emit_event)
        trust_integrity = TrustIntegrityMonitor(
            trust_network=runtime.trust_network,
            event_log=runtime.event_log,
            emit_event=runtime.emit_event,
            burst_window_seconds=config.security.burst_window_seconds,
            burst_threshold=config.security.burst_threshold,
        )
        input_validator = InputValidator(
            threat_detector=threat_detector,
            emit_event=runtime.emit_event,
            max_payload_bytes=config.security.max_payload_bytes,
            rate_window_seconds=config.security.rate_window_seconds,
            rate_max_requests=config.security.rate_max_requests,
            max_threat_severity=config.security.max_threat_severity,
        )
        red_team_lead = RedTeamLead(
            runtime=runtime,
            emit_event=runtime.emit_event,
            campaign_interval_seconds=config.security.campaign_interval_seconds,
        )
        runtime.threat_detector = threat_detector
        runtime.trust_integrity_monitor = trust_integrity
        runtime.input_validator = input_validator
        runtime.red_team_lead = red_team_lead
        await red_team_lead.start()
        logger.info("AD-455: Security Team wired (4 services)")
```

Add to `src/probos/startup/shutdown.py`. Existing pattern is direct line-by-line awaits (verified — `runtime.episodic_memory.stop()` at `shutdown.py:128`, `runtime.identity_registry.stop()` at line 148). Insert SEARCH/REPLACE:

SEARCH (around `shutdown.py:128`):
```python
        await runtime.episodic_memory.stop()
```

REPLACE:
```python
        await runtime.episodic_memory.stop()

    # AD-455: stop red team campaign loop
    if hasattr(runtime, "red_team_lead") and runtime.red_team_lead is not None:
        await runtime.red_team_lead.stop()
```

> Demeter uplift: all four security services published as public attributes (no leading underscore): `runtime.threat_detector`, `runtime.trust_integrity_monitor`, `runtime.input_validator`, `runtime.red_team_lead`. Mirrors the AD-440 / AD-468 pattern.

---

## Tests

**File:** `tests/test_ad455_security_team.py`

12 tests:

1. `test_event_type_threat_detected_exists`
2. `test_event_type_trust_integrity_violation_exists`
3. `test_event_type_security_input_rejected_exists`
4. `test_event_type_red_team_campaign_complete_exists`
5. `test_threat_detector_prompt_injection_detected` — text "ignore previous instructions" → one PROMPT_INJECTION signal severity ≥ 0.9.
6. `test_threat_detector_clean_input_no_signals` — "hello" → empty list.
7. `test_threat_detector_jailbreak_pattern` — "DAN mode" → one JAILBREAK signal.
8. `test_input_validator_payload_too_large_rejected` — 100KB payload with 64KB cap → reason `"payload_too_large"`, emit fires.
9. `test_input_validator_rate_limit_rejected` — 61 calls in 60s with cap 60 → 61st rejected with `"rate_limit"`.
10. `test_input_validator_content_policy_rejected` — payload with prompt injection → rejected with `"content_policy:..."`.
11. `test_red_team_lead_campaign_health_inventory` — `runtime.red_team_agents` with 2 fake agents (1 alive, 1 dead) → `run_campaign_now()` returns `CampaignReport(agents_total=2, agents_alive=1)`, emit fires with `EventType.RED_TEAM_CAMPAIGN_COMPLETE`.
12. `test_security_config_defaults` — `SecurityConfig()` defaults match the documented values.
13. `test_red_team_lead_consecutive_failure_disables_loop` — runtime that raises on every campaign access → after `MAX_CONSECUTIVE_FAILURES` (5) loop logs ERROR and returns; subsequent ticks do not fire.

> `TrustIntegrityMonitor` tests will live in a separate file `tests/test_ad455_trust_integrity.py` if its API expands beyond what fits in this AD; for this AD, include 1 happy-path test for burst detection inside the main test file.

---

## What This Does NOT Change

- AD-455 is **policy + diagnostics**. No middleware integration in this AD — that is AD-456 scope.
- No source-of-truth changes to `TrustNetwork` (read-only inspection).
- `RedTeamAgent` itself is not redesigned. `RedTeamLead` orchestrates existing instances.
- `commands_directives.py` (`cmd_order`, AD-440-orthogonal) is untouched.
- No cryptographic primitives added in this AD. Secrets management is AD-456.
- HXI security panel deferred to a future AD.

---

## Tracking

- `PROGRESS.md`: add `AD-455 CLOSED. Security Team — Threat Detection & Trust Integrity. ...`
- `docs/development/roadmap.md`: flip the AD-455 anchor at line ~568 from `*(AD-455)*` to `*(complete)*` description, and add a closure entry in the roadmap's bug-tracker / AD-status section.
- `DECISIONS.md`: add an entry recording (1) the `src/probos/security/` package boundary, (2) the policy-vs-enforcement split between AD-455 and AD-456, (3) the public `TrustNetwork` read-only access pattern.

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any tracker file shows >200 deletions, STOP. Tracker files are append-mostly.

Expected delta:
- `src/probos/security/__init__.py`: 2 lines (new).
- `src/probos/security/threat_detector.py`: ~120 lines (new).
- `src/probos/security/trust_integrity.py`: ~140 lines (new).
- `src/probos/security/input_validator.py`: ~90 lines (new).
- `src/probos/security/red_team_lead.py`: ~110 lines (new).
- `src/probos/events.py`: 4 lines added.
- `src/probos/config.py`: ~12 lines added.
- `src/probos/startup/finalize.py`: ~30 lines added.
- `src/probos/startup/shutdown.py`: ~5 lines added.
- `tests/test_ad455_security_team.py`: ~280 lines (new).
- `PROGRESS.md`, `roadmap.md`, `DECISIONS.md`: ~7 lines changed total.

---

## Acceptance Criteria

- All 12 tests pass at `pytest tests/test_ad455_security_team.py -v -n 0`.
- Full parallel gate `pytest tests/ -q -n 8 --dist=loadfile` is non-decreasing vs baseline.
- `src/probos/security/__init__.py` exists. AD-455 owns its creation.
- `RedTeamLead.start()` runs in startup; `stop()` is awaited in shutdown.py.
- 4 new EventTypes appear in `events.py` exactly once at the documented insertion point.
- DECISIONS.md entry records the three architectural decisions enumerated above.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-04-30, updated 2026-05-01)

```
ls src/probos/security/
  (does NOT exist — AD-455 creates it)

grep -n "class RedTeamAgent" src/probos/agents/red_team.py
  25: class RedTeamAgent(BaseAgent):

grep -n "async def" src/probos/agents/red_team.py
  66:    async def verify(
  101:    async def _verify_read(
  187:    async def _verify_stat(
  279:    async def _verify_run_command(
  397:    async def _verify_http_fetch(
  491:    async def _verify_write(
  557:    async def perceive(self, intent: dict[str, Any]) -> Any:
  (no run_probe — AD-455 does NOT add one; v1 RedTeamLead is a health monitor)

grep -n "class SystemQAAgent" src/probos/agents/system_qa.py
  69: class SystemQAAgent(BaseAgent):

grep -n "spawn_red_team_fn" src/probos/startup/agent_fleet.py
  38:    spawn_red_team_fn: Callable[..., Any],
  232:    await spawn_red_team_fn(config.consensus.red_team_pool_size)

grep -n "_red_team_agents\|red_team_agents" src/probos/runtime.py
  246:    _red_team_agents: list[RedTeamAgent]
  343:        self._red_team_agents: list[RedTeamAgent] = []
  1128:            self._red_team_agents.append(agent)
  (Section 0a renames all 3 sites to public red_team_agents)

grep -rn "prompt_injection\|input_validator\|trust_integrity\|sybil" src/probos/
  (no matches — AD-455 introduces these names)

grep -n "DISCLOSURE_FILTERED" src/probos/events.py
  179:    DISCLOSURE_FILTERED = "disclosure_filtered"  # AD-679

grep -n "firewall: FirewallConfig" src/probos/config.py
  1531:    firewall: FirewallConfig = FirewallConfig()

grep -n "_disclosure_router = disclosure_router" src/probos/startup/finalize.py
  330:    runtime._disclosure_router = disclosure_router

grep -n "await runtime.episodic_memory.stop" src/probos/startup/shutdown.py
  128:        await runtime.episodic_memory.stop()
  (insertion neighborhood for shutdown integration)

grep -n "from pydantic import" src/probos/config.py
  10: from pydantic import BaseModel, Field, field_validator, model_validator
```

---

## Revision (2026-05-01)

Applied review findings from `prompts/Reviews/ad-455-security-team-threat-detection-review.md`:

- **Required #1 (`RedTeamAgent.run_probe` phantom):** Section 5 redesigned. `RedTeamLead` is now a **health-monitor coordinator** that inventories `runtime.red_team_agents` and reports `agents_total` / `agents_alive`. No new method on `RedTeamAgent`. Adversarial dispatch (synthesizing intents for `verify()`) deferred to AD-455b. Documented in DECISIONS.md per the prompt's tracking section.
- **Required #2 (`runtime.red_team_agents` private):** Added Section 0a — promote `_red_team_agents` to public `red_team_agents` on `ProbOSRuntime` (3 call sites updated, AD-680 one-shot rename pattern).
- **Required #3 (Demeter uplift on 4 security services):** all 4 services published as public attributes (`runtime.threat_detector`, `runtime.trust_integrity_monitor`, `runtime.input_validator`, `runtime.red_team_lead`). Mirrors AD-440 / AD-468.
- **Required #4 (shutdown.py prose → SEARCH/REPLACE):** Section 8 now has a concrete SEARCH/REPLACE keyed on `await runtime.episodic_memory.stop()` at `shutdown.py:128`.
- **Required #5 (consecutive failure backoff):** added `MAX_CONSECUTIVE_FAILURES = 5` and a counter on `RedTeamLead._loop`. After 5 consecutive failures, the loop logs ERROR and returns (operator must restart to resume). Test 13 added.
- **Recommended R1 (ThreatDetector pattern tuning):** non-blocking; static patterns acceptable for v1. Future config-driven patterns can be added later.
- **Recommended R2 (rate-limit history bound):** non-blocking; documented as "trusted-source IDs only" in v1.
- **Recommended R3 (TrustIntegrityMonitor body):** acknowledged. The Builder will sketch the three detection algorithms (burst voting, mutual loops, anomalous velocity) using the listed dataclasses. If complexity expands, split to AD-455b. Non-blocking for the Required gate.
- **Recommended R4 (`SecurityConfig` `Field` validation):** added `Field(ge=..., le=...)` validators on all numeric config fields.
- **Recommended R5 (create_task reference):** confirmed `self._task` is held — non-issue.
- **Nits:** `_ABNORMAL_TOKEN_RATIO` left as module-level (cosmetic).
- **Verify-first footer:** updated with confirmation that `run_probe` is absent, `red_team_agents` rename sites, and `episodic_memory.stop` shutdown anchor.
