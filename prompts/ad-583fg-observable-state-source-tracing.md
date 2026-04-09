# AD-583f/583g: Observable State Verification + Convergence Source Tracing

**Status:** Ready for builder
**Type:** Cognitive / Safety
**Depends on:** AD-583 (wrong convergence), AD-567f (social verification), AD-506b (peer repetition), AD-569 (behavioral metrics)
**Issue:** seangalliher/ProbOS#117
**Case study:** 2026-04-09 — 4 Medical agents spiraled a stale game state into "critical medical monitoring failure" over multiple Ward Room posts. Zero notebook writes. AD-583 saw nothing.

## Problem

AD-583 (Wrong Convergence Detection) only monitors **notebook entries**. Ward Room echo chambers — where agents amplify false claims in real-time discussion — are invisible to the independence scoring pipeline.

Current state:
- AD-583 triggers on notebook writes via `records_store.check_cross_agent_convergence()` — never on Ward Room posts
- AD-506b `check_peer_similarity()` detects post-level similarity but not thread-level amplification chains
- AD-567f `check_cascade_risk()` detects cascade risk but not verifiable falsehoods
- AD-569 `_compute_convergence_correctness()` returns hardcoded zeros — comment says "Ground truth integration deferred to AD-569d" (`behavioral_metrics.py:468`)
- `BehavioralSnapshot.convergence_correctness_rate` is always `None` (`behavioral_metrics.py:62`)
- No system can answer: "Is what the agents are claiming actually true?"

The case study showed: Chapel observed stale working memory (valid), 3 agents amplified into "synchronization failure," "treatment tracking integrity," "critical medical monitoring" — all fabricated system concerns with no evidence. No agent checked observable state.

## Design — 4 Phases

Build phases in order. Each phase is independently testable.

---

### Phase 1: Ward Room Thread Echo Detector (AD-583g foundation)

Detect when multiple agents in a Ward Room thread are amplifying the same content without independent evidence.

#### Phase 1a: New query — `get_thread_posts_temporal()`

**File:** `src/probos/ward_room/threads.py`

Add method to `ThreadManager` (after `get_thread()` at line 548):

```python
async def get_thread_posts_temporal(self, thread_id: str) -> list[dict[str, Any]]:
    """Return all posts in a thread, flat and ordered by created_at.

    Unlike get_thread() which nests into a tree, this returns a flat list
    suitable for temporal flow analysis. Includes parent_id for reply-chain
    reconstruction.

    AD-583g: Foundation for source tracing — trace how content propagates
    through a thread over time.
    """
```

Returns list of dicts with keys: `id`, `thread_id`, `parent_id`, `author_id`, `author_callsign`, `body`, `created_at`. Ordered by `created_at ASC`. Include the thread's own body as the first entry (with `parent_id=None`, `author_id` and `author_callsign` from the thread row).

**Why not reuse `get_thread()`?** It nests posts into a `children` tree. Source tracing needs flat temporal ordering with `parent_id` preserved for reply-chain analysis. `get_recent_activity()` (`threads.py:223`) is channel-scoped and lacks `parent_id`.

#### Phase 1b: Thread Echo Analyzer

**New file:** `src/probos/ward_room/thread_echo.py`

```python
"""AD-583g: Ward Room thread echo detection and source tracing.

Analyzes a Ward Room thread's post history to identify amplification
chains — where multiple agents echo the same content without independent
evidence. Identifies the "Patient Zero" (source post) and the propagation
chain.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PropagationStep:
    """One step in an echo propagation chain."""
    callsign: str
    post_id: str
    timestamp: float
    similarity_to_source: float


@dataclass(frozen=True)
class ThreadEchoResult:
    """Result of thread echo analysis.

    echo_detected=False means the thread does not show amplification patterns.
    When True, source_* fields identify Patient Zero and propagation_chain
    shows how the content spread.
    """
    echo_detected: bool
    thread_id: str
    source_post_id: str = ""
    source_callsign: str = ""
    source_timestamp: float = 0.0
    propagation_chain: list[PropagationStep] = field(default_factory=list)
    chain_length: int = 0
    anchor_independence_score: float = 1.0


class ThreadManagerProtocol(Protocol):
    """Narrow protocol for thread data access (ISP)."""
    async def get_thread_posts_temporal(self, thread_id: str) -> list[dict[str, Any]]: ...


class ThreadEchoAnalyzer:
    """Analyze Ward Room threads for echo amplification patterns.

    Constructor-injected dependencies (DIP). Uses ThreadManagerProtocol
    to access thread data, not the full ThreadManager.
    """

    def __init__(
        self,
        thread_manager: ThreadManagerProtocol,
        *,
        min_chain_length: int = 3,
        similarity_threshold: float = 0.4,
    ) -> None: ...

    async def analyze(self, thread_id: str) -> ThreadEchoResult: ...
```

**`analyze()` algorithm:**

1. Call `thread_manager.get_thread_posts_temporal(thread_id)`.
2. If fewer than `min_chain_length` posts (counting unique authors), return `echo_detected=False`.
3. Import `jaccard_similarity`, `text_to_words` from `probos.cognitive.similarity`.
4. Tokenize each post's body. Group by author — keep the first post per author (their initial contribution to the thread).
5. For each author's first post, compute Jaccard similarity to every earlier post by a DIFFERENT author.
6. Build a propagation chain: start from the thread's first post (the thread body itself). For each subsequent author, if their post has `similarity >= threshold` to the source, add them to the chain.
7. If `chain_length >= min_chain_length`, compute `anchor_independence_score`:
   - Import `compute_anchor_independence` from `probos.cognitive.social_verification` (the pure function at line 98).
   - Create lightweight `SimpleNamespace` objects for each chain participant with `.anchors` (containing `thread_id` — all same, so independence will be low) and `.timestamp`.
   - Score will be near 0.0 for same-thread echo (correct — same thread = not independent).
8. Return `ThreadEchoResult`.

**Reuse:** `jaccard_similarity()` + `text_to_words()` from `cognitive/similarity.py:4,17`. `compute_anchor_independence()` from `social_verification.py:98` (pure function, import directly).

#### Phase 1c: Config

**File:** `src/probos/config.py`

Add after `SocialVerificationConfig` (line 514):

```python
class SourceTracingConfig(BaseModel):
    """AD-583g: Ward Room echo detection and source tracing."""
    echo_min_chain_length: int = 3
    echo_similarity_threshold: float = 0.4
    echo_analysis_enabled: bool = True
```

Add to `SystemConfig` as `source_tracing: SourceTracingConfig = SourceTracingConfig()`.

---

### Phase 2: Observable State Verifier (AD-583f)

A pluggable registry of state providers that can answer "Is this claim true?" by querying actual system state.

#### Phase 2a: Verifier core + StateProvider protocol

**New file:** `src/probos/cognitive/observable_state.py`

```python
"""AD-583f: Observable State Verification.

Provides ground truth verification for agent claims by querying actual
system state. Uses a pluggable StateProvider protocol — extend by adding
providers, not by modifying the verifier.

Satisfies AD-569d: populates convergence_correctness_rate in
BehavioralSnapshot (previously hardcoded None).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VerificationResult:
    """Result of verifying a single claim against observable state."""
    provider_name: str
    claim_text: str
    verified: bool | None  # None = provider can't determine
    ground_truth_summary: str  # Human-readable actual state
    confidence: float  # 0.0-1.0, how confident the provider is


@runtime_checkable
class StateProvider(Protocol):
    """Protocol for pluggable state verification providers (ISP).

    Each provider handles a narrow domain (games, trust, health).
    Returns None if the claim is outside its domain.
    """
    @property
    def name(self) -> str: ...

    async def check(self, claim_text: str, context: dict[str, Any]) -> VerificationResult | None: ...


class ObservableStateVerifier:
    """Registry of state providers for ground truth verification.

    Constructor-injected providers (DIP). Log-and-degrade if any
    provider fails — never let a broken provider block verification.
    """

    def __init__(self, providers: list[StateProvider] | None = None) -> None: ...

    async def verify_claims(
        self,
        claims: list[str],
        context: dict[str, Any] | None = None,
    ) -> list[VerificationResult]: ...
```

**`verify_claims()` algorithm:**
1. For each claim, iterate providers. Call `provider.check(claim, context)`.
2. If provider returns a `VerificationResult` (not None), collect it.
3. If provider raises, log warning and skip (log-and-degrade).
4. Return all collected results. A claim may have results from multiple providers.
5. Bound: process at most `max_claims_per_thread` claims (from config).

#### Phase 2b: Initial State Providers (3)

All in `src/probos/cognitive/observable_state.py`, below the verifier class.

**1. `RecreationStateProvider`**
```python
class RecreationStateProvider:
    """Verify game-related claims against RecreationService state."""

    def __init__(self, recreation_service: Any) -> None: ...

    @property
    def name(self) -> str:
        return "recreation"

    async def check(self, claim_text: str, context: dict[str, Any]) -> VerificationResult | None: ...
```

- **Relevance detection:** keyword match for "game", "tic-tac-toe", "move", "board", "winner", "draw", "playing", "match".
- **Ground truth query:** `recreation_service.get_active_games()`. If a callsign from `context.get("agents", [])` has an active game: report board state, status, whose turn. If no active games: report "No active games found."
- **Verification:** If claim says "game is stuck" or "waiting for move" → check `state["status"]` and `state["current_player"]`. If claim says "game concluded" → check if game is absent from active games.

**2. `TrustStateProvider`**
```python
class TrustStateProvider:
    """Verify trust-related claims against TrustNetwork state."""

    def __init__(self, trust_network: Any) -> None: ...
```

- **Relevance detection:** keyword match for "trust", "confidence", "trust score", "declining", "anomaly".
- **Ground truth query:** `trust_network.all_scores()` for global view, `trust_network.get_score(agent_id)` for specific agent. `trust_network.get_recent_events(10)` for trend.
- **Verification:** If claim says "trust anomaly" → check if any score deviates > 2σ from mean. If claim says "low trust" → check actual score vs 0.3 floor.

**3. `SystemHealthProvider`**
```python
class SystemHealthProvider:
    """Verify system health claims against VitalsMonitor snapshot."""

    def __init__(self, vitals_monitor: Any) -> None: ...
```

- **Relevance detection:** keyword match for "health", "pool", "degraded", "critical", "failure", "offline", "monitoring".
- **Ground truth query:** Call `vitals_monitor.scan_now()` (line 165 of `vitals_monitor.py`) if available, else `vitals_monitor.latest_vitals`.
- **Verification:** If claim says "system failure" → check `system_health`. If claim says "pool degraded" → check `pool_health` dict.

**Important:** All providers take `Any` typed constructor args. Access only via public API methods documented above. Never reach into private attributes (Law of Demeter).

#### Phase 2c: Config

**File:** `src/probos/config.py`

Add after `SourceTracingConfig`:

```python
class ObservableStateConfig(BaseModel):
    """AD-583f: Observable state verification."""
    verification_enabled: bool = True
    max_claims_per_thread: int = 10
```

Add to `SystemConfig` as `observable_state: ObservableStateConfig = ObservableStateConfig()`.

---

### Phase 3: Events, Alerts, and Counselor

#### Phase 3a: Event Types

**File:** `src/probos/events.py`

Add to `EventType` enum (after `WRONG_CONVERGENCE_DETECTED` at line 148):

```python
WARD_ROOM_ECHO_DETECTED = "ward_room_echo_detected"           # AD-583g
OBSERVABLE_STATE_MISMATCH = "observable_state_mismatch"        # AD-583f
```

Add typed event dataclasses (after `WrongConvergenceDetectedEvent` at line 576):

```python
@dataclass
class WardRoomEchoDetectedEvent:
    """AD-583g: Echo amplification chain detected in Ward Room thread."""
    thread_id: str
    channel_id: str
    source_callsign: str
    chain_length: int
    independence_score: float
    affected_callsigns: list[str]
    source: str = "ward_room_echo"

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "channel_id": self.channel_id,
            "source_callsign": self.source_callsign,
            "chain_length": self.chain_length,
            "independence_score": self.independence_score,
            "affected_callsigns": self.affected_callsigns,
            "source": self.source,
        }


@dataclass
class ObservableStateMismatchEvent:
    """AD-583f: Agent claims contradicted by observable system state."""
    thread_id: str
    claims_checked: int
    claims_failed: int
    ground_truth_summary: str
    agents_involved: list[str]
    source: str = "observable_state"

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "claims_checked": self.claims_checked,
            "claims_failed": self.claims_failed,
            "ground_truth_summary": self.ground_truth_summary,
            "agents_involved": self.agents_involved,
            "source": self.source,
        }
```

#### Phase 3b: Bridge Alerts

**File:** `src/probos/bridge_alerts.py`

Add two methods to `BridgeAlertService`, following the `check_wrong_convergence()` pattern (line 525):

```python
def check_ward_room_echo(self, echo_result: dict) -> list[BridgeAlert]:
    """AD-583g: Alert when Ward Room thread shows echo amplification."""
    if not echo_result.get("echo_detected"):
        return []
    chain_length = echo_result.get("chain_length", 0)
    independence = echo_result.get("anchor_independence_score", 1.0)
    if independence >= 0.3:
        return []  # Independent enough — not an echo chamber

    source = echo_result.get("source_callsign", "unknown")
    thread_id = echo_result.get("thread_id", "")
    affected = echo_result.get("affected_callsigns", [])

    dedup_key = f"ward_room_echo:{thread_id}"
    if not self._should_emit(dedup_key):
        return []

    alert = BridgeAlert(
        id=str(uuid.uuid4()),
        severity=AlertSeverity.ALERT,
        source="ward_room_monitor",
        alert_type="ward_room_echo_detected",
        title="Ward Room Echo Chamber Detected",
        detail=(
            f"Thread shows {chain_length}-agent amplification chain "
            f"(independence={independence:.2f}). Source: {source}. "
            f"Affected: {', '.join(affected)}."
        ),
        dedup_key=dedup_key,
        timestamp=time.time(),
    )
    self._record(alert)
    return [alert]


def check_observable_mismatch(self, verification_result: dict) -> list[BridgeAlert]:
    """AD-583f: Alert when agent claims contradict observable state."""
    claims_failed = verification_result.get("claims_failed", 0)
    if claims_failed == 0:
        return []

    thread_id = verification_result.get("thread_id", "")
    dedup_key = f"state_mismatch:{thread_id}"
    if not self._should_emit(dedup_key):
        return []

    severity = AlertSeverity.ALERT if claims_failed >= 2 else AlertSeverity.ADVISORY
    alert = BridgeAlert(
        id=str(uuid.uuid4()),
        severity=severity,
        source="observable_state_monitor",
        alert_type="observable_state_mismatch",
        title="Agent Claims Contradict Observable State",
        detail=verification_result.get("ground_truth_summary", ""),
        dedup_key=dedup_key,
        timestamp=time.time(),
    )
    self._record(alert)
    return [alert]
```

#### Phase 3c: Counselor Subscriptions

**File:** `src/probos/cognitive/counselor.py`

Add event subscriptions to `_subscribe_to_events()` (follow the pattern of `WRONG_CONVERGENCE_DETECTED` subscription at line 598):

```python
self._subscribe(EventType.WARD_ROOM_ECHO_DETECTED, self._on_ward_room_echo)
self._subscribe(EventType.OBSERVABLE_STATE_MISMATCH, self._on_observable_mismatch)
```

Add handler methods (follow `_on_wrong_convergence()` pattern at line 1342):

```python
async def _on_ward_room_echo(self, event_data: dict) -> None:
    """AD-583g: Counsel agents involved in Ward Room echo chain."""
    source = event_data.get("source_callsign", "")
    affected = event_data.get("affected_callsigns", [])
    chain_length = event_data.get("chain_length", 0)
    independence = event_data.get("independence_score", 1.0)

    if independence >= 0.3:
        return  # Independent enough

    for callsign in affected:
        if callsign == source:
            continue  # Don't counsel the source — they made the original observation
        await self._send_therapeutic_dm(
            callsign,
            f"I noticed you reinforced {source}'s conclusion along with "
            f"{chain_length - 1} others. Consider whether you independently "
            f"verified the claim before agreeing, or if you were responding "
            f"to social signal rather than evidence.",
            reason="ward_room_echo",
        )


async def _on_observable_mismatch(self, event_data: dict) -> None:
    """AD-583f: Counsel agents whose claims contradict observable state."""
    agents = event_data.get("agents_involved", [])
    summary = event_data.get("ground_truth_summary", "")
    claims_failed = event_data.get("claims_failed", 0)

    if claims_failed == 0:
        return

    for callsign in agents[:3]:  # Limit DMs
        await self._send_therapeutic_dm(
            callsign,
            f"A recent discussion contained claims that don't match "
            f"observable system state. {summary} Consider verifying "
            f"claims against actual system state before amplifying.",
            reason="observable_state_mismatch",
        )
```

**Important:** Use existing `_send_therapeutic_dm()` method (already has rate limiting and cooldown). Check method signature — it may take `callsign` or `agent_id`. Match whichever the existing method uses.

---

### Phase 4: Pipeline Integration

#### Phase 4a: Ward Room Helper

**File:** `src/probos/ward_room/_helpers.py`

Add after `check_and_emit_cascade_risk()` (line 50), following the same pattern:

```python
async def check_and_trace_echo(
    thread_echo_analyzer: Any,
    observable_state_verifier: Any,
    emit_fn: Callable | None,
    bridge_alerts: Any,
    ward_room_router: Any,
    *,
    thread_id: str,
    channel_id: str,
    peer_matches: list[dict],
) -> None:
    """AD-583f/583g: Trace echo chain and verify claims on echo detection.

    Called after check_and_emit_cascade_risk() when peer_matches are found.
    Runs thread echo analysis and, if echo detected, runs observable state
    verification on the thread content.
    """
    if not peer_matches or not thread_echo_analyzer:
        return
    try:
        echo_result = await thread_echo_analyzer.analyze(thread_id)
        if not echo_result.echo_detected:
            return

        # AD-583g: Emit echo event
        if emit_fn:
            from probos.events import EventType as _ET
            emit_fn(_ET.WARD_ROOM_ECHO_DETECTED, {
                "thread_id": thread_id,
                "channel_id": channel_id,
                "source_callsign": echo_result.source_callsign,
                "chain_length": echo_result.chain_length,
                "independence_score": echo_result.anchor_independence_score,
                "affected_callsigns": [
                    step.callsign for step in echo_result.propagation_chain
                ],
            })

        # AD-583g: Bridge alert
        if bridge_alerts:
            import dataclasses
            alerts = bridge_alerts.check_ward_room_echo(
                dataclasses.asdict(echo_result),
            )
            if alerts and ward_room_router:
                for alert in alerts:
                    await ward_room_router.deliver_bridge_alert(alert)

        # AD-583f: Observable state verification on echo content
        if observable_state_verifier and echo_result.chain_length >= 3:
            # Extract unique claims from the echo thread
            # (thread body + source post content are the claims to verify)
            claims = [
                step.callsign  # Placeholder — actual implementation
                # should extract claim text from post bodies
            ]
            # Implementation: collect post bodies from the echo chain,
            # pass to verifier.verify_claims(), emit events/alerts on mismatch.

    except Exception:
        logger.debug("AD-583f/g: Echo trace failed", exc_info=True)
```

**Builder note:** The claim extraction needs work — extract actual post body text from the thread posts. The `analyze()` result contains `source_post_id` and `propagation_chain` with `post_id`s. Use `thread_manager.get_thread_posts_temporal()` to get the post bodies by ID for claim verification.

#### Phase 4b: Wire into Ward Room post creation

**File:** `src/probos/ward_room/threads.py`

In `create_thread()`, after the `_check_cascade_risk()` call (line 370), add:

```python
# AD-583f/583g: Echo chain tracing when peer similarity detected
await self._check_echo_trace(peer_matches, thread.id, channel_id)
```

Add the method to `ThreadManager`:

```python
async def _check_echo_trace(
    self, peer_matches: list[dict], thread_id: str, channel_id: str,
) -> None:
    """AD-583f/583g: Delegate to helper for echo tracing."""
    from probos.ward_room._helpers import check_and_trace_echo
    await check_and_trace_echo(
        self._thread_echo_analyzer,
        self._observable_state_verifier,
        self._emit,
        self._bridge_alerts,
        self._ward_room_router,
        thread_id=thread_id,
        channel_id=channel_id,
        peer_matches=peer_matches,
    )
```

Add `set_echo_services()` late-binding method (follows `set_social_verification()` pattern at line 110):

```python
def set_echo_services(
    self,
    thread_echo_analyzer: Any = None,
    observable_state_verifier: Any = None,
    bridge_alerts: Any = None,
    ward_room_router: Any = None,
) -> None:
    """AD-583f/583g: Late-bind echo detection and state verification services."""
    self._thread_echo_analyzer = thread_echo_analyzer
    self._observable_state_verifier = observable_state_verifier
    self._bridge_alerts = bridge_alerts
    self._ward_room_router = ward_room_router
```

**File:** `src/probos/ward_room/messages.py`

Same integration in `create_post()` — after the `_check_cascade_risk()` call (line 163):

```python
# AD-583f/583g: Echo chain tracing
await self._check_echo_trace(peer_matches, thread_id, thread_channel_id)
```

Add the same `_check_echo_trace()` and `set_echo_services()` methods to `MessageStore`.

#### Phase 4c: Startup Wiring

**File:** `src/probos/startup/cognitive_services.py`

Find where `SocialVerificationService` is created and wired (search for `social_verification` or `set_social_verification`). After that wiring, add:

```python
# AD-583f/583g: Observable State Verification + Source Tracing
from probos.ward_room.thread_echo import ThreadEchoAnalyzer
from probos.cognitive.observable_state import (
    ObservableStateVerifier,
    RecreationStateProvider,
    TrustStateProvider,
    SystemHealthProvider,
)

# Build state providers from available services
providers = []
if hasattr(runtime, "recreation_service") and runtime.recreation_service:
    providers.append(RecreationStateProvider(runtime.recreation_service))
if hasattr(runtime, "trust_network") and runtime.trust_network:
    providers.append(TrustStateProvider(runtime.trust_network))
# VitalsMonitor is an agent, not a direct service — use runtime if vitals are available
# Builder: check how VitalsMonitor is accessed. It may be via the agent registry
# or via a vitals snapshot service. Use whatever is available.

observable_verifier = ObservableStateVerifier(providers) if providers else None

# Thread echo analyzer
src_cfg = runtime.config.source_tracing
thread_echo = ThreadEchoAnalyzer(
    thread_manager=runtime.ward_room._thread_manager,  # Check actual accessor
    min_chain_length=src_cfg.echo_min_chain_length,
    similarity_threshold=src_cfg.echo_similarity_threshold,
) if src_cfg.echo_analysis_enabled else None

# Late-bind to Ward Room components
if hasattr(runtime.ward_room, "_thread_manager"):
    runtime.ward_room._thread_manager.set_echo_services(
        thread_echo_analyzer=thread_echo,
        observable_state_verifier=observable_verifier,
        bridge_alerts=runtime.bridge_alerts,
        ward_room_router=runtime.ward_room_router,
    )
if hasattr(runtime.ward_room, "_message_store"):
    runtime.ward_room._message_store.set_echo_services(
        thread_echo_analyzer=thread_echo,
        observable_state_verifier=observable_verifier,
        bridge_alerts=runtime.bridge_alerts,
        ward_room_router=runtime.ward_room_router,
    )
```

**Builder note:** Check the actual way `ThreadManager` and `MessageStore` are accessed from `WardRoomService`. They may be private attributes or accessible via public methods. Verify by reading `ward_room/service.py`. If private, consider adding a public `set_echo_services()` on `WardRoomService` that delegates to both sub-components (Law of Demeter).

#### Phase 4d: Behavioral Metrics Integration

**File:** `src/probos/cognitive/behavioral_metrics.py`

Wire `ObservableStateVerifier` into `_compute_convergence_correctness()` (line 460) to replace the hardcoded zeros. This satisfies AD-569d.

Add constructor parameter:

```python
def __init__(
    self, ...,
    observable_state_verifier: Any = None,  # AD-583f
):
    ...
    self._verifier = observable_state_verifier
```

In `_compute_convergence_correctness()` (line 460), after convergence detection (line 504-505), if `self._verifier` is available:

1. Extract claim text from converging posts' bodies.
2. Call `await self._verifier.verify_claims(claims)`.
3. Count `verified=True` (correct) and `verified=False` (incorrect) results.
4. Populate the return dict with actual counts instead of zeros.

```python
# Replace the hardcoded return at line 507-513:
if self._verifier and convergence_events > 0:
    # Collect claim texts from converging threads
    all_claims = []
    for thread in threads:
        posts = thread["posts"]
        for post in posts:
            body = post.get("body", "")
            if body:
                all_claims.append(body[:500])  # Bound claim length

    try:
        results = await self._verifier.verify_claims(all_claims[:10])
        correct = sum(1 for r in results if r.verified is True)
        incorrect = sum(1 for r in results if r.verified is False)
        total_verified = correct + incorrect
        return {
            "total": convergence_events,
            "correct": correct,
            "incorrect": incorrect,
            "unverified": convergence_events - total_verified,
            "correctness_rate": correct / total_verified if total_verified > 0 else None,
        }
    except Exception:
        logger.debug("AD-583f: Verification in convergence correctness failed", exc_info=True)

# Fallback: unchanged behavior
return {
    "total": convergence_events,
    "correct": 0,
    "incorrect": 0,
    "unverified": convergence_events,
    "correctness_rate": None,
}
```

**Note:** `_compute_convergence_correctness()` is currently synchronous. The verifier is async. Builder needs to either: (a) make `_compute_convergence_correctness()` async (check callers — `compute_behavioral_metrics()` at line 104 is already async), or (b) use a sync wrapper. Option (a) is cleaner.

---

## Engineering Principles Compliance

| Principle | How Satisfied |
|---|---|
| **SRP** | `ThreadEchoAnalyzer` = echo detection. `ObservableStateVerifier` = claim verification. Separate files, separate concerns. |
| **OCP** | State providers are pluggable via `StateProvider` protocol. Add providers without modifying verifier. |
| **LSP** | All providers implement `StateProvider` protocol, interchangeable. |
| **ISP** | `ThreadManagerProtocol` is narrow (one method). `StateProvider` is narrow (one method + name property). |
| **DIP** | Constructor injection for all dependencies. Depend on protocols, not concretions. |
| **Law of Demeter** | Use public APIs: `get_score()`, `get_active_games()`, `scan_now()`. Never reach through private attrs. Check Ward Room service accessor pattern. |
| **DRY** | Reuse `compute_anchor_independence()`, `jaccard_similarity()`, `BridgeAlert` pattern, `_helpers.py` pattern. |
| **Fail Fast** | Log-and-degrade for unavailable providers. All providers catch exceptions, log, skip. |
| **Cloud-Ready** | No new SQLite. Reads existing `ward_room.db` via `ThreadManager`. New query uses existing DB layer. |
| **Defense in Depth** | Validate at service boundary. Handle `None` providers. Bound claim count via config. |

---

## Test Plan — 40 tests across 2 files

### `tests/test_ad583g_source_tracing.py` (~20 tests)

1. `test_thread_echo_analyzer_construction` — accepts ThreadManagerProtocol + config
2. `test_thread_echo_analyzer_config_defaults` — min_chain_length=3, similarity_threshold=0.4
3. `test_source_tracing_config_exists` — `SourceTracingConfig` in `config.py`
4. `test_get_thread_posts_temporal_returns_flat_list` — no nested children, ordered by created_at
5. `test_get_thread_posts_temporal_includes_thread_body` — thread body is first entry
6. `test_get_thread_posts_temporal_includes_parent_id` — parent_id present on each dict
7. `test_echo_chain_detected_three_agents` — 3 agents echoing same content → echo_detected=True
8. `test_echo_chain_detected_four_agents` — 4 agents → chain_length=4
9. `test_echo_chain_source_identification` — earliest post with echoed content → source_callsign correct
10. `test_echo_chain_propagation_order` — chain ordered by timestamp ascending
11. `test_echo_chain_similarity_scores` — each step has similarity_to_source > 0
12. `test_independence_score_low_same_thread` — same thread → independence ≈ 0.0
13. `test_short_thread_no_echo` — 2 posts (< min_chain_length) → echo_detected=False
14. `test_dissimilar_posts_no_echo` — posts below similarity threshold → echo_detected=False
15. `test_echo_result_dataclass_fields` — ThreadEchoResult has all expected fields
16. `test_propagation_step_dataclass_fields` — PropagationStep has callsign, post_id, timestamp, similarity
17. `test_ward_room_echo_event_type_exists` — `EventType.WARD_ROOM_ECHO_DETECTED` in enum
18. `test_ward_room_echo_event_serialization` — `WardRoomEchoDetectedEvent.to_dict()` works
19. `test_bridge_alert_fires_on_echo` — `check_ward_room_echo()` returns ALERT when independence < 0.3
20. `test_bridge_alert_dedup_echo` — second call with same thread_id suppressed

### `tests/test_ad583f_observable_state.py` (~20 tests)

1. `test_observable_state_verifier_construction` — accepts list of providers
2. `test_verifier_no_providers` — empty provider list → empty results
3. `test_observable_state_config_exists` — `ObservableStateConfig` in `config.py`
4. `test_recreation_provider_detects_game_claim` — keyword "game" → provider engages
5. `test_recreation_provider_verifies_active_game` — game exists → verified=True with board state
6. `test_recreation_provider_rejects_false_game_claim` — no active games → verified=False
7. `test_recreation_provider_ignores_non_game_claim` — no game keywords → returns None
8. `test_trust_provider_detects_trust_claim` — keyword "trust" → provider engages
9. `test_trust_provider_verifies_trust_score` — actual score matches claim → verified=True
10. `test_trust_provider_rejects_false_trust_claim` — claim contradicts actual score → verified=False
11. `test_health_provider_detects_health_claim` — keyword "health"/"degraded" → engages
12. `test_health_provider_verifies_system_health` — vitals show healthy → verified=True
13. `test_provider_exception_graceful_skip` — provider raises → skipped, others still run
14. `test_verification_result_dataclass` — VerificationResult fields correct
15. `test_observable_state_mismatch_event_exists` — `EventType.OBSERVABLE_STATE_MISMATCH` in enum
16. `test_observable_state_mismatch_event_serialization` — to_dict() works
17. `test_bridge_alert_fires_on_mismatch` — `check_observable_mismatch()` returns alert when claims_failed > 0
18. `test_bridge_alert_severity_escalation` — 1 failed → ADVISORY, 2+ failed → ALERT
19. `test_bridge_alert_dedup_mismatch` — second call suppressed
20. `test_behavioral_metrics_correctness_populated` — `convergence_correctness_rate` is not None when verifier wired

---

## Deferred (explicitly out of scope)

- **AD-583h:** Cross-thread echo detection — same false claim across multiple threads/channels
- **AD-583i:** Automated correction — system auto-posts ground truth corrections
- **AD-559:** Full provenance model — per-claim cross-system evidence chains
- **Additional state providers:** HebbianStateProvider, EmergenceStateProvider, AlertHistoryProvider
- **LLM-based claim extraction:** Current approach uses keyword matching for claim relevance. Future: LLM-based claim decomposition for richer verification

---

## Prior Work Checklist (Builder: verify before building)

- [ ] `compute_anchor_independence()` is still at `social_verification.py:98` (pure function, module-level)
- [ ] `check_peer_similarity()` signature unchanged at `ward_room/threads.py:22`
- [ ] `_compute_convergence_correctness()` still returns hardcoded zeros at `behavioral_metrics.py:507-513`
- [ ] `check_wrong_convergence()` pattern at `bridge_alerts.py:525` — verify `_should_emit()` and `_record()` usage
- [ ] `check_and_emit_cascade_risk()` at `ward_room/_helpers.py:20` — verify helper pattern
- [ ] `ThreadManager.get_thread()` at `ward_room/threads.py:500` — verify query pattern for new method
- [ ] `RecreationService` public API: `get_active_games()`, `get_game_by_player()`, `render_board()` at `recreation/service.py`
- [ ] `VitalsMonitor.scan_now()` or `latest_vitals` — verify accessor
- [ ] `CounselorAgent._send_therapeutic_dm()` — verify method name and signature
- [ ] `startup/cognitive_services.py` — verify where `SocialVerificationService` is wired (pattern to follow)
- [ ] `WardRoomService` internal accessors — how to reach `ThreadManager` and `MessageStore`
- [ ] `config.py` `SystemConfig` field additions — verify pattern at line 831+
