# AD-536: Trust-Gated Procedure Promotion

**Type:** Build Prompt
**AD:** 536
**Title:** Trust-Gated Procedure Promotion
**Depends:** AD-535 ✅ (Graduated Compilation Levels), AD-339 ✅ (Standing Orders), Chain of Command (existing), DirectiveStore (existing)
**Branch:** `ad-536-procedure-promotion`

---

## Context

Cognitive JIT procedures are currently agent-private knowledge. An agent learns a procedure through experience, refines it through evolution (AD-532b), and replays it at graduated compilation levels (AD-535). But procedures never leave the originating agent. Even a Level 4 Autonomous procedure — proven reliable through consecutive successes — stays locked to one agent.

AD-536 adds governance: when a procedure proves itself, the agent can request promotion to shared institutional knowledge. Two-tier approval mirrors the chain of command — department chiefs approve routine promotions within their domain, the Captain approves critical or cross-department procedures. Approved procedures become Runtime Directives (via DirectiveStore), injected into recipient agents' system prompts. Rejected promotions become negative annotations — "Captain said don't do this because..." is institutional learning.

This is the pipeline: **dream consolidation identifies pattern → procedure crystallizes → compilation levels validate → AD-536 governs promotion → Standing Orders evolve.**

---

## Engineering Principles Compliance

- **SOLID (S):** PromotionRequest as its own concern, separate from ProcedureStore and DirectiveStore. ProcedurePromotion service coordinates but doesn't embed business logic in existing classes.
- **SOLID (O):** Extends ProcedureStore and DirectiveStore via public APIs. No private member patching.
- **SOLID (D):** Depend on ProcedureStore, DirectiveStore, WardRoomService abstractions. Constructor injection.
- **Law of Demeter:** Don't reach through procedure.store._db. Use public methods.
- **Fail Fast:** Invalid promotion requests fail immediately with clear reason. Don't silently swallow routing errors.
- **DRY:** Reuse DirectiveStore's PENDING_APPROVAL → approve() flow. Reuse quality metrics from ProcedureStore.get_quality_metrics().
- **Cloud-Ready Storage:** ProcedureStore already uses abstract connection interface. New columns follow existing migration pattern.

---

## What to Build

### Part 0: Config Constants

File: `src/probos/config.py`

Add constants:

```python
# AD-536: Procedure Promotion
PROMOTION_MIN_COMPILATION_LEVEL: int = 4          # Must be Level 4+ to request promotion
PROMOTION_MIN_TOTAL_COMPLETIONS: int = 10          # Minimum successful completions
PROMOTION_MIN_EFFECTIVE_RATE: float = 0.7           # Minimum effective_rate
PROMOTION_REJECTION_COOLDOWN_HOURS: int = 72        # Anti-loop: no re-submit within 72h
PROMOTION_CRITICALITY_CAPTAIN_THRESHOLD: str = "high"  # "high"/"critical" → Captain
```

### Part 1: Criticality Classification

File: `src/probos/cognitive/procedure_store.py`

Add a `classify_criticality()` function that maps procedure metadata to a criticality level. Simple heuristic for v1:

```python
class ProcedureCriticality(str, Enum):
    LOW = "low"          # Read-only operations, reporting, analysis
    MEDIUM = "medium"    # Standard CRUD, routine operations
    HIGH = "high"        # Security changes, data mutations, cross-department
    CRITICAL = "critical"  # System configuration, destructive operations

def classify_criticality(procedure: Procedure) -> ProcedureCriticality:
    """Classify procedure criticality from its metadata.

    Rules (first match wins):
    - If procedure has steps with agent_role containing "security" → HIGH
    - If procedure is compound (multi-agent) → HIGH (cross-department)
    - If procedure.intent_pattern contains destructive keywords → CRITICAL
    - If procedure has >5 steps → MEDIUM (complex procedure = more risk)
    - Default → LOW
    """
```

Keywords for destructive detection: `delete`, `remove`, `destroy`, `reset`, `drop`, `purge`, `force`, `override`. These should be a configurable set, not hardcoded.

### Part 2: ProcedureStore Promotion Tracking

File: `src/probos/cognitive/procedure_store.py`

Add columns to the `procedure_records` table via migration:

```sql
ALTER TABLE procedure_records ADD COLUMN promotion_status TEXT DEFAULT 'private';
-- Values: 'private', 'pending', 'approved', 'rejected'
ALTER TABLE procedure_records ADD COLUMN promotion_requested_at TEXT;
ALTER TABLE procedure_records ADD COLUMN promotion_decided_at TEXT;
ALTER TABLE procedure_records ADD COLUMN promotion_decided_by TEXT;
ALTER TABLE procedure_records ADD COLUMN promotion_rejection_reason TEXT;
ALTER TABLE procedure_records ADD COLUMN promotion_directive_id TEXT;
-- Links to the RuntimeDirective created on approval
```

Add methods:

```python
async def request_promotion(self, procedure_id: str) -> dict:
    """Mark procedure as pending promotion. Returns promotion request summary.

    Validates eligibility:
    - compilation_level >= PROMOTION_MIN_COMPILATION_LEVEL
    - total_completions >= PROMOTION_MIN_TOTAL_COMPLETIONS
    - effective_rate >= PROMOTION_MIN_EFFECTIVE_RATE
    - promotion_status not 'pending'
    - Not within PROMOTION_REJECTION_COOLDOWN_HOURS of a rejection

    Returns dict with: eligible (bool), reason (str if ineligible),
    procedure_summary, quality_metrics, criticality.
    """

async def approve_promotion(self, procedure_id: str, decided_by: str, directive_id: str) -> None:
    """Mark procedure as approved. Link to the created directive."""

async def reject_promotion(self, procedure_id: str, decided_by: str, reason: str) -> None:
    """Mark procedure as rejected. Store rejection reason as institutional knowledge."""

async def get_pending_promotions(self, department: str | None = None) -> list[dict]:
    """Get all procedures with promotion_status='pending', optionally filtered by department."""
```

### Part 3: Promotion Request Generation

File: `src/probos/cognitive/cognitive_agent.py`

In `handle_intent()`, after a successful compilation level promotion to Level 4+, check if the procedure is eligible for institutional promotion:

```python
# After existing promotion logic in handle_intent():
if new_level >= PROMOTION_MIN_COMPILATION_LEVEL and procedure.promotion_status == "private":
    promotion_result = await self._request_procedure_promotion(procedure_id)
    if promotion_result["eligible"]:
        # Post promotion request to Ward Room
        await self._announce_promotion_request(procedure_id, promotion_result)
```

Add method `_request_procedure_promotion(procedure_id: str) -> dict`:
1. Call `store.request_promotion(procedure_id)` for eligibility check
2. Classify criticality via `classify_criticality()`
3. Determine routing: criticality < PROMOTION_CRITICALITY_CAPTAIN_THRESHOLD → department chief, else → Captain
4. Return routing info

Add method `_announce_promotion_request(procedure_id: str, promotion_result: dict)`:
1. Post to Ward Room (department channel for routine, Bridge channel for critical)
2. Format: procedure summary, quality metrics, compilation level history, criticality assessment, recommended approver
3. DM the target approver (department chief callsign or @captain)

### Part 4: Approval Routing

File: `src/probos/cognitive/cognitive_agent.py`

Add method `_route_promotion_approval(procedure_id: str, criticality: ProcedureCriticality) -> str`:

Determine who approves:
- `LOW` or `MEDIUM` → department chief for the procedure's origin department
- `HIGH` or `CRITICAL` → Captain

Department chief resolution — add a helper that maps department → chief callsign:

```python
_DEPARTMENT_CHIEFS: dict[str, str] = {
    "engineering": "laforge",
    "medical": "bones",
    "science": "number_one",  # dual-hatted
    "security": "worf",
    "operations": "obrien",
    "bridge": "captain",  # Bridge procedures always go to Captain
}
```

This is a simple lookup. If the department is unknown or the chief can't be resolved, fall back to Captain.

### Part 5: Approval Processing

This requires a way for the Captain or department chief to approve/reject. Two mechanisms:

**(a) Captain shell command:**

File: `src/probos/experience/commands/procedure_cmd.py` (new file in existing commands package)

Add commands accessible via shell:
- `procedure list-pending [--department <dept>]` — Show pending promotion requests
- `procedure approve <procedure_id> [--message <msg>]` — Approve a promotion
- `procedure reject <procedure_id> --reason <reason>` — Reject with feedback
- `procedure list-promoted` — Show all promoted procedures

Register in `src/probos/experience/commands/__init__.py`.

**(b) API endpoints:**

File: `src/probos/routers/procedure_router.py` (new file in existing routers package)

```
GET  /api/procedures/pending          — List pending promotions
POST /api/procedures/{id}/approve     — Approve promotion
POST /api/procedures/{id}/reject      — Reject promotion (body: {reason: str})
GET  /api/procedures/promoted         — List promoted procedures
```

Register in `src/probos/routers/__init__.py`.

### Part 6: Directive Creation on Approval

When a promotion is approved:

1. Create a `RuntimeDirective` via `DirectiveStore.create_directive()`:
   - `directive_type = DirectiveType.LEARNED_LESSON`
   - `issuer_type = "procedure_promotion"`
   - `target_agent_type` = None (ship-wide) or specific agent types in the procedure's department
   - `target_department` = procedure's origin department (routine) or None (critical/cross-department)
   - `content` = formatted procedure summary: "When handling [intent_pattern], follow these steps: [procedure steps]. This procedure was validated through [N completions] with [effective_rate]% success rate. Origin: [agent callsign/type]."
   - `authority = "captain"` or `"department_chief"`
   - `status = DirectiveStatus.ACTIVE`

2. Update ProcedureStore: `approve_promotion(procedure_id, decided_by, directive_id)`

3. Post approval announcement to Ward Room (department channel + All Hands for critical)

4. **Unlock Level 5 for the originating agent's procedure.** Update `COMPILATION_MAX_LEVEL` handling: promoted procedures can reach Level 5 (Expert). Only promoted procedures — private procedures remain capped at Level 4. Add check in `_max_compilation_level_for_trust()`: if `procedure.promotion_status == "approved" and trust_score >= TRUST_COMMANDER`, allow Level 5.

### Part 7: Rejection Learning

When a promotion is rejected:

1. Update ProcedureStore: `reject_promotion(procedure_id, decided_by, reason)`

2. Store rejection reason as a negative annotation on the procedure. The rejection reason becomes part of the procedure's metadata — future evolution attempts (AD-532b) can reference why the procedure was rejected.

3. Post rejection to Ward Room DM to the originating agent (not public — rejections are private feedback).

4. Anti-loop guard: record `promotion_decided_at` timestamp. `request_promotion()` checks that `PROMOTION_REJECTION_COOLDOWN_HOURS` have elapsed since last rejection. During cooldown, the procedure must also show material change: new evolution (FIX/DERIVED), additional consecutive successes beyond the previous request's level, or different quality metrics.

### Part 8: Ward Room Integration

All Ward Room posts use the existing pattern from `proactive.py`:

```python
# Get department channel
channel = await rt.ward_room.get_or_create_channel(department_name)
# Create thread
await rt.ward_room.create_thread(
    channel_id=channel.id,
    author_id=agent_id,
    title=f"[Promotion Request] {procedure.intent_pattern}",
    body=formatted_summary,
    author_callsign=callsign,
)
```

For DMs to the approver:
```python
await rt.ward_room.create_dm(
    from_id=agent_id,
    to_callsign=approver_callsign,
    body=f"Procedure promotion request requires your review: {procedure.intent_pattern}. "
         f"Quality: {effective_rate:.0%} effective over {total_completions} completions. "
         f"Criticality: {criticality}. Use `procedure approve {procedure_id}` to approve.",
)
```

### Part 9: HXI Surface (Minimal)

This is NOT a full HXI feature build. Just ensure the existing HXI infrastructure can display promotion status:

- The procedure list API endpoint (`/api/procedures/promoted` from Part 5b) returns data the existing HXI can query
- Promotion status appears in the Agent Profile Panel (AD-406) work tab if procedures are shown there

Full HXI dashboarding for procedure governance belongs in a later AD (connects to AD-555 quality dashboard).

---

## What NOT to Build

- **Level 5 teaching mechanics** — That's AD-537 (Observational Learning). AD-536 only unlocks Level 5 eligibility on approval.
- **Async approval workflow with checkpointing** — The PydanticAI deferred-execution pattern is overkill. Promotion requests are posted to Ward Room and wait for Captain/chief action at their convenience. No blocking or resumption needed.
- **Automated bulk approval** — The roadmap mentions department chiefs batch-approving during scheduled review periods. That's a Duty Schedule integration for later. For now, one-at-a-time approval via shell command and API.
- **Cross-ship (Federation) procedure sharing** — That's Federation Remotes (roadmap). AD-536 is ship-internal governance only.
- **Full HXI procedure governance dashboard** — Minimal API endpoints only. Full UI is future work.

---

## Test Strategy

**Target: 50-65 tests across 7-8 test files.**

### test_procedure_criticality.py (~8 tests)
- Security keywords → HIGH
- Multi-agent compound → HIGH
- Destructive keywords → CRITICAL
- Simple procedure → LOW
- Multi-step procedure → MEDIUM
- Edge cases: empty steps, no intent pattern

### test_promotion_eligibility.py (~10 tests)
- Eligible: Level 4+, sufficient completions, good effective rate → success
- Ineligible: Level 3 → rejected with reason
- Ineligible: low completions → rejected
- Ineligible: low effective rate → rejected
- Already pending → rejected
- Within rejection cooldown → rejected
- Past cooldown but no material change → rejected
- Past cooldown with new evolution → eligible
- Private → can request; approved → cannot re-request

### test_promotion_routing.py (~8 tests)
- LOW criticality → department chief
- MEDIUM criticality → department chief
- HIGH criticality → Captain
- CRITICAL criticality → Captain
- Unknown department → falls back to Captain
- Cross-department compound → Captain
- Bridge department → Captain

### test_promotion_approval.py (~10 tests)
- Approve: creates RuntimeDirective, updates promotion_status, links directive_id
- Approve: directive content includes procedure steps and quality metrics
- Approve: unlocks Level 5 for promoted procedure
- Approve: posts Ward Room announcement
- Reject: stores reason, sets promotion_decided_at
- Reject: sends DM to originating agent (not public)
- Reject: anti-loop prevents re-request within cooldown
- Approve then demote: if promoted procedure later fails, Level 5 → Level 2 demotion still works

### test_promotion_commands.py (~8 tests)
- Shell: `procedure list-pending` shows pending promotions
- Shell: `procedure approve <id>` approves and creates directive
- Shell: `procedure reject <id> --reason "..."` rejects with feedback
- Shell: `procedure list-promoted` shows approved procedures
- API: GET /api/procedures/pending returns pending list
- API: POST /api/procedures/{id}/approve creates directive
- API: POST /api/procedures/{id}/reject stores reason

### test_promotion_integration.py (~8 tests)
- End-to-end: procedure reaches Level 4 → auto-requests promotion → approve → directive created → injected into system prompt
- End-to-end: rejection → anti-loop → evolution → re-request after cooldown
- Level 5 trust gating: approved procedure + Commander trust → Level 5 allowed
- Level 5 trust gating: approved procedure + Lieutenant trust → capped at Level 4
- Private procedure → Level 5 blocked regardless of trust

### test_procedure_store_promotion.py (~8 tests)
- Schema migration adds new columns
- request_promotion() sets status and timestamp
- approve_promotion() links directive_id
- reject_promotion() stores reason
- get_pending_promotions() filters by department
- get_pending_promotions() excludes non-pending

---

## Files Modified (Expected)

| File | Change |
|------|--------|
| `src/probos/config.py` | 5 new constants |
| `src/probos/cognitive/procedure_store.py` | 6 new columns (migration), 5 new methods, ProcedureCriticality enum, classify_criticality() |
| `src/probos/cognitive/cognitive_agent.py` | Promotion request trigger in handle_intent(), _request_procedure_promotion(), _announce_promotion_request(), _route_promotion_approval(), Level 5 unlock logic in _max_compilation_level_for_trust() |
| `src/probos/experience/commands/procedure_cmd.py` | **New file.** Shell commands for procedure governance |
| `src/probos/experience/commands/__init__.py` | Register procedure commands |
| `src/probos/routers/procedure_router.py` | **New file.** API endpoints for procedure governance |
| `src/probos/routers/__init__.py` | Register procedure router |
| `tests/test_procedure_criticality.py` | **New file** |
| `tests/test_promotion_eligibility.py` | **New file** |
| `tests/test_promotion_routing.py` | **New file** |
| `tests/test_promotion_approval.py` | **New file** |
| `tests/test_promotion_commands.py` | **New file** |
| `tests/test_promotion_integration.py` | **New file** |
| `tests/test_procedure_store_promotion.py` | **New file** |

Update existing test files that mock ProcedureStore to include new columns in mock schemas if needed (same pattern as AD-535 fixes).

---

## Verification

1. Run AD-536 tests: `uv run pytest tests/test_procedure_criticality.py tests/test_promotion_eligibility.py tests/test_promotion_routing.py tests/test_promotion_approval.py tests/test_promotion_commands.py tests/test_promotion_integration.py tests/test_procedure_store_promotion.py -v`
2. Run all Cognitive JIT tests: `uv run pytest tests/test_cognitive_jit*.py tests/test_procedure*.py tests/test_replay*.py tests/test_multi_agent*.py tests/test_fallback*.py tests/test_graduated_compilation.py tests/test_promotion*.py -v`
3. Run full suite to check for regressions: `uv run pytest tests/ -x -q`
4. Verify no pre-commit hook violations (no emoji, no commercial content in OSS)
