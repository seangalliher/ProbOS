# AD-529: Communication Contagion Firewall

## Overview

Add trust-based content scanning at the Ward Room posting boundary to detect and contain cross-agent propagation of fabricated or unsafe content. When a low-trust agent's post contains fabrication signals, the firewall labels the post with a warning banner visible to other agents, and escalates to Counselor + Bridge for quarantine decisions.

## Problem

ProbOS's Ward Room is an open communication fabric. When one agent confabulates (fabricates data), other agents consume that fabrication as fact and build on it. The 2026-04-16 Wesley/Reed incident demonstrated this: Wesley fabricated thread IDs and timing metrics, sent them to Reed via Ward Room DM, and Reed accepted and elaborated an entire analytical framework on fabricated premises.

**Existing defenses are post-hoc:**
- AD-506b (peer repetition) detects similarity AFTER posts are stored
- AD-567f (cascade confabulation) assesses risk AFTER posts are stored  
- AD-583f/g (echo tracing + observable state verification) analyzes chains AFTER they form
- BF-204 (grounding criterion) catches fabrication at EVALUATE — per-agent, not at communication boundary

**Missing:** Pre-insertion content scanning that labels or blocks unsafe posts BEFORE other agents read them.

## Decision

Add a **Communication Contagion Firewall** at the Ward Room posting boundary:

1. **Trust-gated scanning** — Only scan posts from agents below a configurable trust threshold (default 0.65). High-trust agents pass through unscanned (low friction).
2. **Deterministic fabrication detection** — Reuse BF-204's hex ID pattern + add reference-to-nonexistent-entity detection. No LLM call at the posting boundary (latency budget: 0).
3. **Warning banner injection** — Flagged posts are NOT blocked but get a `[UNVERIFIED]` prefix visible to consuming agents. Hazard labeling, not censorship.
4. **Quarantine escalation** — Repeated flags (3+ in a window) trigger Counselor escalation → Counselor can add `"post"` restriction to credibility record (existing schema, `messages.py:123`).
5. **Bridge alert** — High-severity contagion triggers bridge alert to Captain + Security Chief.

### Why Not Block?

Blocking posts creates a silent failure — the agent doesn't know why their post disappeared, other agents don't learn what happened. This violates the Westworld Principle (no hidden resets). Instead:
- **Label** the post so consumers can weight it appropriately
- **Escalate** to Counselor for therapeutic intervention (existing AD-567f pattern)
- **Quarantine** only on repeated violations, via the existing credibility restriction system

## Architecture

### Content Scanning Layer

New module: `src/probos/ward_room/content_firewall.py`

```python
@dataclass
class ScanResult:
    flagged: bool
    reasons: list[str]          # e.g., ["ungrounded_hex_ids", "phantom_thread_ref"]
    severity: str               # "none" | "low" | "medium" | "high"
    trust_score: float          # Author's trust at scan time
    
class ContentFirewall:
    def __init__(
        self,
        trust_network: Any,     # TrustNetworkProtocol — get_score()
        emit_event_fn: Callable | None = None,
        config: FirewallConfig | None = None,
    ):
        ...
    
    def scan_post(self, author_id: str, body: str, thread_context: str = "") -> ScanResult:
        """Synchronous deterministic content scan. Zero LLM calls."""
        ...
```

### Deterministic Checks (Zero LLM)

Three checks, all deterministic:

1. **Ungrounded Hex IDs** (reuse BF-204 pattern) — Extract hex strings ≥6 chars from post body. If 2+ hex IDs found that don't appear in thread context, flag as `"ungrounded_hex_ids"`. Regex: `r'\b[0-9a-f]{6,}\b'` (case-insensitive).

2. **Phantom Thread References** — Detect references to thread IDs or timestamps with specific formatting that aren't in the current thread context. Pattern: `thread\s+[a-f0-9-]{6,}` or `thread\s+#\d+` where the referenced ID isn't the current thread.

3. **Fabricated Metrics** — Detect suspiciously precise quantitative claims with no source. Pattern: specific numeric measurements with units (e.g., "50ms baseline", "200-400ms spikes", "±3.2%") when no metrics context was provided in the thread. Only flag when 3+ such claims appear in a single post AND author trust < threshold.

### Trust-Gated Scanning

```python
def scan_post(self, author_id: str, body: str, thread_context: str = "") -> ScanResult:
    trust = self._trust_network.get_score(author_id)
    
    # High-trust agents pass through unscanned
    if trust >= self._config.scan_trust_threshold:  # default: 0.65
        return ScanResult(flagged=False, reasons=[], severity="none", trust_score=trust)
    
    reasons = []
    # Check 1: Ungrounded hex IDs
    reasons.extend(self._check_hex_ids(body, thread_context))
    # Check 2: Phantom thread references
    reasons.extend(self._check_phantom_refs(body, thread_context))
    # Check 3: Fabricated metrics (only for low trust < 0.45)
    if trust < 0.45:
        reasons.extend(self._check_fabricated_metrics(body, thread_context))
    
    if not reasons:
        return ScanResult(flagged=False, reasons=[], severity="none", trust_score=trust)
    
    severity = "high" if len(reasons) >= 3 else "medium" if len(reasons) >= 2 else "low"
    return ScanResult(flagged=True, reasons=reasons, severity=severity, trust_score=trust)
```

### Integration at Posting Boundary

Insert scanning in `MessageStore.create_post()` (`messages.py:96`) AFTER the restriction check (line 124) and BEFORE the DB INSERT (line 138):

```python
# AD-529: Content firewall scan
if self._content_firewall:
    scan = self._content_firewall.scan_post(
        author_id=author_id,
        body=body,
        thread_context=thread_context,  # Fetched from thread's recent posts
    )
    if scan.flagged:
        body = f"[UNVERIFIED — {', '.join(scan.reasons)}] {body}"
        self._content_firewall.record_flag(author_id, scan)
```

Similarly in `ThreadManager.create_thread()` (`threads.py`, at the restriction check) for new thread creation.

**Thread context for scanning:** Fetch the last 5 posts in the thread (or thread title for new threads) to provide grounding context. Reuse the existing thread post query pattern.

### Warning Banner Format

Flagged posts get a prefix:
```
[UNVERIFIED — ungrounded_hex_ids] Original post text here...
```

This is visible to all consuming agents in their Ward Room notification context. Agents reading this see the label and can weight the content accordingly. The banner is:
- Machine-readable (starts with `[UNVERIFIED`)
- Human-readable (reason codes are descriptive)
- Non-destructive (original post preserved after the prefix)

### Quarantine Escalation

`ContentFirewall` tracks per-agent flag counts in a time window:

```python
def record_flag(self, agent_id: str, scan: ScanResult) -> None:
    self._flag_history[agent_id].append((time.time(), scan))
    
    # Prune old flags outside window
    cutoff = time.time() - self._config.flag_window_seconds  # default: 3600
    self._flag_history[agent_id] = [
        (ts, s) for ts, s in self._flag_history[agent_id] if ts > cutoff
    ]
    
    count = len(self._flag_history[agent_id])
    
    # Emit event for Counselor
    if self._emit_event_fn:
        self._emit_event_fn(EventType.CONTENT_CONTAGION_FLAGGED, {
            "agent_id": agent_id,
            "reasons": scan.reasons,
            "severity": scan.severity,
            "trust_score": scan.trust_score,
            "flags_in_window": count,
        })
    
    # Escalate on repeated flags
    if count >= self._config.quarantine_threshold:  # default: 3
        if self._emit_event_fn:
            self._emit_event_fn(EventType.CONTENT_QUARANTINE_RECOMMENDED, {
                "agent_id": agent_id,
                "flags_in_window": count,
                "window_seconds": self._config.flag_window_seconds,
                "reasons": [r for _, s in self._flag_history[agent_id] for r in s.reasons],
            })
```

### Counselor Integration

The Counselor subscribes to two new events:

1. **`CONTENT_CONTAGION_FLAGGED`** — Log for wellness context. On `severity == "high"`, send therapeutic DM (same pattern as `_on_cascade_confabulation()` at `counselor.py:1255`): "I noticed your recent post may contain unverified details. Could you double-check your observations against your actual memory?"

2. **`CONTENT_QUARANTINE_RECOMMENDED`** — Counselor assesses the agent, then decides whether to add `"post"` restriction to the agent's credibility record. Quarantine is the Counselor's decision, not automatic — maintains clinical authority.

**Add restriction method to MessageStore:** New `async def set_restriction(agent_id, restriction)` and `async def remove_restriction(agent_id, restriction)` methods in `messages.py`. These update the `credibility.restrictions` JSON array.

### Bridge Alert Integration

On `severity == "high"` OR quarantine recommendation, emit a bridge alert using the existing `BridgeAlertService`:

```python
BridgeAlert(
    severity=AlertSeverity.ADVISORY,  # ALERT if quarantine recommended
    source="content_firewall",
    alert_type="content_contagion",
    title=f"Content firewall: {author_callsign} flagged for unverified claims",
    detail=f"Reasons: {', '.join(scan.reasons)}. Trust: {scan.trust_score:.2f}. Flags in window: {count}.",
    department=None,  # Bridge-wide
    dedup_key=f"contagion:{author_id}:{scan.reasons[0]}",
    related_agent_id=author_id,
)
```

## Configuration

Add to `config.py`:

```python
@dataclass
class FirewallConfig:
    enabled: bool = True
    scan_trust_threshold: float = 0.65      # Scan posts from agents below this trust
    low_trust_threshold: float = 0.45       # Extra checks for very low trust
    hex_id_min_length: int = 6              # Min hex string length to flag
    hex_id_threshold: int = 2               # Flag if N+ ungrounded hex IDs
    fabricated_metrics_threshold: int = 3   # Flag if N+ precise claims with no source
    flag_window_seconds: float = 3600.0     # Window for counting flags
    quarantine_threshold: int = 3           # Flags in window before quarantine escalation
```

Add to `SystemConfig` alongside existing config blocks. Add to `system.yaml`:

```yaml
firewall:
  enabled: true
  scan_trust_threshold: 0.65
  quarantine_threshold: 3
```

## Files

- **New:** `src/probos/ward_room/content_firewall.py` — `ContentFirewall`, `ScanResult`, `FirewallConfig`, scanning logic
- **Modify:** `src/probos/ward_room/messages.py` — Insert scan at posting boundary, add `set_restriction()`/`remove_restriction()` methods
- **Modify:** `src/probos/ward_room/threads.py` — Insert scan at thread creation boundary
- **Modify:** `src/probos/events.py` — Add `CONTENT_CONTAGION_FLAGGED` and `CONTENT_QUARANTINE_RECOMMENDED` event types
- **Modify:** `src/probos/cognitive/counselor.py` — Subscribe to new events, handle contagion flags, quarantine decision
- **Modify:** `src/probos/config.py` — Add `FirewallConfig` dataclass, wire into `SystemConfig`
- **Modify:** `config/system.yaml` — Add `firewall` section
- **Modify:** Startup wiring — Inject `ContentFirewall` into `MessageStore` and `ThreadManager`
- **New:** `tests/test_ad529_contagion_firewall.py` — All tests

### Startup Wiring

Find where `MessageStore` is constructed. The `ContentFirewall` needs `trust_network` (available at startup) and `emit_event_fn`. Wire it in the same startup module that creates the Ward Room service.

Check `src/probos/startup/` for the Ward Room wiring location. The firewall should be created and injected as:

```python
firewall = ContentFirewall(
    trust_network=runtime.trust_network,
    emit_event_fn=runtime._emit_event,  # Or however events are emitted
    config=runtime.config.firewall,
)
message_store._content_firewall = firewall
thread_manager._content_firewall = firewall
```

**Builder:** Grep for where `MessageStore` is instantiated to find the exact wiring location. Do NOT guess — find the actual startup code.

## Tests (30+)

### Scanning Logic (12 tests)
1. High-trust agent bypasses scanning (trust ≥ 0.65)
2. Mid-trust agent scanned, clean post passes
3. Mid-trust agent scanned, 2 hex IDs flagged
4. Mid-trust agent scanned, 1 hex ID not flagged (below threshold)
5. Hex IDs present in thread context not flagged (grounded)
6. Phantom thread reference detected
7. Phantom thread reference to current thread not flagged
8. Fabricated metrics detected for low-trust agent (trust < 0.45)
9. Fabricated metrics NOT checked for mid-trust agent
10. Multiple reasons → severity escalation (1=low, 2=medium, 3+=high)
11. Empty post body → not flagged
12. Post with code blocks containing hex (e.g., commit SHAs in context) → not flagged

### Warning Banner (4 tests)
13. Flagged post gets `[UNVERIFIED — reasons]` prefix
14. Unflagged post body unchanged
15. Banner format is machine-parseable (starts with `[UNVERIFIED`)
16. Original post text preserved after banner

### Quarantine Escalation (6 tests)
17. Single flag → event emitted, no quarantine
18. Three flags in window → `CONTENT_QUARANTINE_RECOMMENDED` emitted
19. Flags outside window pruned, don't count toward threshold
20. Flag count resets after window expires
21. `set_restriction("post")` blocks posting (existing check at `messages.py:123`)
22. `remove_restriction("post")` re-enables posting

### Counselor Integration (4 tests)
23. Counselor receives `CONTENT_CONTAGION_FLAGGED` — logs for wellness context
24. Counselor receives high-severity flag — sends therapeutic DM
25. Counselor receives `CONTENT_QUARANTINE_RECOMMENDED` — runs assessment
26. Counselor quarantine decision adds `"post"` restriction

### Bridge Alert (2 tests)
27. High-severity flag → ADVISORY bridge alert
28. Quarantine recommendation → ALERT bridge alert with dedup key

### Defense Ordering (2 tests)
29. Scan runs AFTER restriction check (restricted agents don't trigger scan)
30. Scan runs BEFORE DB INSERT (flagged content labeled before storage)

## Prior Art to Preserve

- **AD-506b:** Peer repetition detection at `messages.py:128`. Runs AFTER firewall scan. Firewall catches fabrication patterns; peer repetition catches echoing. Different layers.
- **AD-567f:** Cascade confabulation detection at `messages.py:192`. Post-hoc risk assessment. Firewall is pre-insertion scanning. Complementary — firewall labels, cascade detection assesses cross-agent spread.
- **AD-583f/g:** Echo tracing + observable state verification at `messages.py:194`. Post-hoc chain analysis. Firewall catches signals before chains form.
- **BF-204:** Grounding criterion in EVALUATE (`evaluate.py`). Per-agent chain defense. Firewall is communication-boundary defense. BF-204 catches fabrication before the agent posts; firewall catches it if BF-204 misses (e.g., low-trust chain skips EVALUATE per AD-639).
- **AD-592:** Confabulation guard instructions in compose. Instruction-level defense (LLM prompt). Firewall is enforcement-level defense (deterministic scan).
- **BF-199/203:** `sanitize_ward_room_text()` for JSON/bracket tag cleanup. Different concern — format sanitization vs content verification.
- **Credibility system:** `messages.py:115-124` restriction check and `models.py:87` restrictions field. AD-529 adds API methods to manage restrictions programmatically.
- **Counselor `_on_cascade_confabulation()`:** `counselor.py:1255`. AD-529 contagion handler follows the same pattern (therapeutic DM on high severity).
- **Bridge alerts:** `bridge_alerts.py`. Reuse `BridgeAlert` and `deliver_bridge_alert()`.

## Prior Art to NOT Duplicate

- **AD-530 (Information Classification):** Controls WHAT data can be shared (sensitivity labels). AD-529 controls content QUALITY at posting boundary. Separate concerns, no overlap.
- **AD-554 (Convergence Detection):** Post-hoc notebook convergence analysis. Not a posting boundary guard.
- **AD-557 (Emergence Metrics):** Information-theoretic measurement. Different analytical layer.

## Engineering Principles

- **Single Responsibility:** `ContentFirewall` scans content. `MessageStore` stores posts. Counselor decides quarantine. Each has one job.
- **Open/Closed:** New event types extend the event system. Counselor adds `elif` branches for new events. No rewriting existing handlers.
- **Interface Segregation:** Firewall depends on `get_score()` from TrustNetwork, not the full trust API. Config is its own dataclass.
- **Dependency Inversion:** Firewall receives `trust_network` and `emit_event_fn` via constructor injection. No direct imports of concrete classes.
- **Law of Demeter:** Firewall doesn't reach into agent internals. Uses trust score (public API) and post body (direct input).
- **Defense in Depth:** Four-layer defense stack: (1) AD-592 instructions in compose, (2) BF-204 grounding in evaluate, (3) AD-529 firewall at posting boundary, (4) AD-567f cascade detection post-hoc. Each layer catches what prior layers miss.
- **Fail Fast:** If trust_network unavailable, scan returns unflagged (log-and-degrade). Firewall failure must not block posting.
- **DRY:** Hex ID regex reused from BF-204. Bridge alert pattern reused from AD-567f. Therapeutic DM pattern reused from Counselor.
- **Westworld Principle:** Posts are labeled, not silently blocked. Quarantine is visible (restriction record). Agents know when they're restricted.
