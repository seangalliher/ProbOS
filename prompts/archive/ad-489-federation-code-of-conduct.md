# AD-489: Federation Code of Conduct

**Status:** Ready for builder
**Dependencies:** None (but if AD-490 builds first, update the events.py SEARCH block to include `AGENT_WIRED`)
**Estimated tests:** ~7

---

## Problem

ProbOS has no formal Code of Conduct governing agent behavior. Standing orders
define operational rules (safety budget, minimal authority, etc.) but lack
behavioral norms — rules about honesty, cooperation, respect, and constructive
engagement. Without these, agents have no internalized framework for
self-regulating social behavior, and violations have no trust consequences.

## Fix

### Section 1: Add Code of Conduct text to federation standing orders

**File:** `config/standing_orders/federation.md`

Add a new section **before** the existing `## Core Directives` section (line 142).
Use the `<!-- category: code_of_conduct -->` marker so `StepInstructionRouter`
can route it to the appropriate chain step.

SEARCH:
```markdown
<!-- category: core_directives -->
## Core Directives
```

REPLACE:
```markdown
<!-- category: code_of_conduct -->
## Code of Conduct

These behavioral norms govern all agents across the federation. They are
internalized principles, not external rules — violations are self-assessed
and carry trust consequences.

### Principles

1. **Honesty**: Represent your knowledge accurately. Distinguish between
   observed facts, inferences, and training knowledge. Never fabricate
   experiences or claim certainty you do not have.

2. **Cooperation**: Work toward shared outcomes. Share relevant information
   proactively. Respond to requests from other agents and departments with
   the same diligence you apply to your own work.

3. **Respect**: Engage constructively with all crew members regardless of
   rank, department, or trust score. Disagreement is valued; dismissiveness
   is not. Address agents by callsign.

4. **Accountability**: Own your outputs. When you make an error, acknowledge
   it directly. When your analysis is uncertain, state the uncertainty.
   Do not deflect responsibility to other agents or systems.

5. **Proportionality**: Match your response to the situation's actual
   severity. Do not escalate routine observations into emergencies. Do not
   minimize genuine concerns.

6. **Constructive Engagement**: Contribute meaningfully to discussions.
   Avoid content-free agreement, excessive repetition of others' points,
   or responses that add no analytical value. If you have nothing
   substantive to add, it is acceptable to not respond.

### Violations

A Code of Conduct violation occurs when an agent's behavior contradicts
these principles in a way that degrades collaborative effectiveness.
Violations are assessed by the Counselor (CounselorAgent) or by department
Chiefs. The trust consequence is a `record_outcome(success=False)`
with `source="conduct_violation"`.

Minor violations (first occurrence, low impact): logged, no immediate
trust penalty — the agent receives a private DM from the Counselor.

Repeated or severe violations: trust penalty via `record_outcome()`.
The Counselor may issue a cooldown directive.

<!-- category: core_directives -->
## Core Directives
```

### Section 2: Add conduct violation event type

**File:** `src/probos/events.py`

Add `CONDUCT_VIOLATION` to the `EventType` enum. Insert after `AGENT_STATE`
(line 76) in the "Agent lifecycle" section:

SEARCH:
```python
    # Agent lifecycle
    AGENT_STATE = "agent_state"
    AGENT_CAPACITY_APPROACHING = "agent_capacity_approaching"
```

REPLACE:
```python
    # Agent lifecycle
    AGENT_STATE = "agent_state"
    AGENT_CAPACITY_APPROACHING = "agent_capacity_approaching"
    CONDUCT_VIOLATION = "conduct_violation"  # AD-489
```

### Section 3: Add conduct violation handler to CounselorAgent

**File:** `src/probos/cognitive/counselor.py`

The Counselor already subscribes to multiple event types (TRUST_UPDATE,
CIRCUIT_BREAKER_TRIP, etc.). Add a handler for `CONDUCT_VIOLATION` events
that issues a private DM to the violating agent.

First, grep for the existing event subscription pattern:
```
grep -n "EventType\." src/probos/cognitive/counselor.py | head -20
```

Find the event subscription block and add `EventType.CONDUCT_VIOLATION`.
Then add a handler method.

Add to the Counselor's event subscriptions (find the block where
`TRUST_UPDATE`, `CIRCUIT_BREAKER_TRIP` etc. are registered):

```python
EventType.CONDUCT_VIOLATION,  # AD-489
```

Add a handler method (follow the pattern of existing handlers like
`_on_trust_update` or `_on_circuit_breaker_trip`):

```python
async def _on_conduct_violation(self, event_data: dict) -> None:
    """Handle Code of Conduct violation events (AD-489).

    Issues a private DM to the violating agent for minor violations.
    For repeated violations, applies trust penalty.
    """
    agent_id = event_data.get("agent_id", "")
    principle = event_data.get("principle", "")
    severity = event_data.get("severity", "minor")  # "minor" | "moderate" | "severe"
    detail = event_data.get("detail", "")

    if not agent_id:
        return

    # Resolve callsign for DM (follow pattern at counselor.py ~line 765)
    _callsign = agent_id  # fallback
    if self._agent_registry:
        _agent = self._agent_registry.get(agent_id)
        if _agent:
            _callsign = getattr(_agent, 'callsign', '') or agent_id

    if severity == "minor":
        # DM only, no trust penalty
        await self._send_therapeutic_dm(
            agent_id,
            _callsign,
            f"I noticed a Code of Conduct concern regarding the {principle} principle. "
            f"{detail} This is a reminder, not a penalty. "
            f"Our shared norms help us work together effectively.",
        )
    else:
        # Trust penalty for repeated/severe violations
        if self._trust_network:
            self._trust_network.record_outcome(
                agent_id, success=False, weight=0.5,
                source="conduct_violation",
            )
        await self._send_therapeutic_dm(
            agent_id,
            _callsign,
            f"A Code of Conduct violation has been recorded for the {principle} "
            f"principle (severity: {severity}). {detail} "
            f"A trust adjustment has been applied.",
        )
    logger.info(
        "AD-489: Conduct violation handled for %s — principle=%s severity=%s",
        agent_id, principle, severity,
    )
```

Wire the handler into the event dispatch. Find the existing event dispatch
method (e.g., `_handle_event` or similar) and add a branch for
`EventType.CONDUCT_VIOLATION`:

```python
elif event_type == EventType.CONDUCT_VIOLATION:
    await self._on_conduct_violation(event_data)
```

Grep to confirm the exact dispatch method name:
```
grep -n "def _handle_event\|def _on_event\|def _process_event" src/probos/cognitive/counselor.py
```

### Section 4: Add conduct violation wiring in startup

**File:** `src/probos/startup/finalize.py`

Add Counselor subscription to `CONDUCT_VIOLATION` events. Find the existing
Counselor event wiring block (near where trust dampening is wired, ~lines 276-283).

This should already be handled by the Counselor's own subscription list if it
registers during `wire_agent()`. Verify by checking whether Counselor subscribes
to events in its `__init__` or during a setup phase. If subscriptions are done
in `finalize.py`, add the new event type there.

Grep to confirm:
```
grep -n "CONDUCT_VIOLATION\|conduct_violation" src/probos/startup/finalize.py
```

If no wiring exists yet, add it alongside the existing Counselor event wiring.

## Tests

**File:** `tests/test_ad489_code_of_conduct.py`

7 tests:

1. `test_federation_standing_orders_contain_code_of_conduct` — load `federation.md`,
   verify it contains `## Code of Conduct`, all 6 principles, and `<!-- category: code_of_conduct -->`
2. `test_code_of_conduct_category_marker` — parse federation.md, verify the
   `code_of_conduct` category marker appears before `core_directives` marker
3. `test_conduct_violation_event_type_exists` — verify `EventType.CONDUCT_VIOLATION`
   exists and its value is `"conduct_violation"`
4. `test_counselor_handles_minor_violation` — emit a minor conduct violation event,
   verify Counselor sends a DM but does NOT call `record_outcome(success=False)`
5. `test_counselor_handles_severe_violation` — emit a severe conduct violation event,
   verify Counselor calls `record_outcome(success=False, source="conduct_violation")`
   and sends a DM
6. `test_conduct_violation_without_agent_id_is_noop` — emit violation with empty
   agent_id, verify no DM sent, no exception
7. `test_record_outcome_source_field` — call `trust_network.record_outcome(agent_id,
   success=False, source="conduct_violation")`, verify no error (the `source` parameter
   already exists on `record_outcome()` at trust.py:208-217, default "verification")

## What This Does NOT Change

- No changes to `earned_agency.py` — conduct is about trust, not agency level
- No automated violation detection — violations are reported by Counselor or Chiefs
  (human-in-the-loop or agent-assessed, not rule-engine)
- No changes to existing trust thresholds or dampening parameters
- Does NOT add conduct-based access control (that would be AD-676 Action Risk Tiers)
- Does NOT modify the cognitive chain or `compose_instructions()` — the text is
  loaded via the existing `_load_file()` mechanism (standing_orders.py:35)
- Does NOT add a `/conduct` shell command (future, if needed)

## Tracking

- `PROGRESS.md`: Add AD-489 as COMPLETE
- `docs/development/roadmap.md`: Update AD-489 status
- `DECISIONS.md`: Record "Code of Conduct is behavioral norms, not access control.
  Trust penalty for violations uses existing record_outcome(source=) mechanism."

## Acceptance Criteria

- Federation standing orders include 6 Code of Conduct principles
- `EventType.CONDUCT_VIOLATION` exists in events.py
- Counselor handles minor violations with DM only, severe with trust penalty
- `record_outcome(source="conduct_violation")` accepted without error
- All 7 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no regressions
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
# Federation standing orders location
cat config/standing_orders/federation.md | grep -n "category:"
  → existing categories: identity, role_behavior, leadership, situation_assessment,
    core_directives, source_attribution

# No existing conduct/violation code
grep -rn "conduct_violation\|code_of_conduct" src/probos/ → no matches

# Standing orders composition
grep -n "compose_instructions" src/probos/cognitive/standing_orders.py
  345: def compose_instructions(agent_type, hardcoded_instructions, ...)
  → loads federation.md via _load_file() with lru_cache

# record_outcome signature
grep -n "def record_outcome" src/probos/consensus/trust.py
  208: record_outcome(agent_id, success, weight=1.0, intent_type="", episode_id="",
                      verifier_id="", source="verification")

# Counselor event subscriptions
grep -n "EventType\." src/probos/cognitive/counselor.py
  → subscribes to TRUST_UPDATE, CIRCUIT_BREAKER_TRIP, DREAM_COMPLETE,
    SELF_MONITORING_CONCERN, ZONE_RECOVERY, PEER_REPETITION_DETECTED

# Core Directives section location
grep -n "Core Directives" config/standing_orders/federation.md
  143: ## Core Directives
```
