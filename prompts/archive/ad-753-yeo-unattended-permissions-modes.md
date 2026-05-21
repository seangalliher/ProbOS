# AD-753 - Unattended Permission Modes (`autoApproveReadOnly`, Permission Cards, Tenant Policy Hook)

Status: drafted (planning slate only)
Issue: #699
Parent: #486
Depends on: AD-749 (#695)

## Objective
Add explicit unattended-permission controls that preserve safety while enabling useful automation.

## Captain Invariant
Capability is usable by all crew agents; Yeo is the front-door orchestrator and delegates to specialists.

## In Scope
- `autoApproveReadOnly` mode with clear constraints.
- Permission cards for approval/reject/review.
- Tenant policy hook extension-point for custom policy engines.
- Manual/auto/autopilot mode taxonomy pattern (AionUi-inspired, pattern only).

## Out of Scope
- Unbounded YOLO bypass modes.
- Enterprise policy engine implementation details.

## OSS vs Commercial Split

**OSS (Personal Desktop):**
- `autoApproveReadOnly` mode for personal assistant on personal data.
- Manual approval cards in Ward Room for unattended decisions.
- Tenant policy hook as abstract interface (no impl).

**Commercial Extension Point:**
- Tenant policy engine with org rule sets and audit reporting.
- Advanced permission scopes (team data, sensitive projects, regulatory).
- Policy audit log for SOC/compliance teams.
- Escalation routing to org approvers for edge cases.

## File Targets
- `src/probos/security/`
- `src/probos/governance/`
- `src/probos/consensus/`
- `src/probos/config.py`
- `ui/src/components/wardroom/`

## Pre-Flight Anchors
- Verify current approvals/quorum paths in `src/probos/consensus/quorum.py` and escalation flow.
- Verify tool/permission infrastructure in `src/probos/tools/` and `src/probos/security/`.
- Verify DM approval surfaces in ward-room UI components.

## Implementation Spec

### Section 1: autoApproveReadOnly Mode

**File:** `src/probos/security/permission_model.py` (new)

Create `PermissionMode` enum + `PermissionConfig`:
```python
class PermissionMode(Enum):
    MANUAL = "manual"  # All ops require approval
    AUTOPILOT = "autopilot"  # Read-only auto-approve, destructive require approval
    YOLO = "yolo"  # Discouraged (only for demos/tests)

@dataclass
class PermissionConfig:
    mode: PermissionMode = PermissionMode.MANUAL
    auto_approve_read_only: bool = False  # only for AUTOPILOT mode
    read_only_whitelist: set[str] = Field(default_factory=set)  # intent list that auto-approves
    read_only_expiry_window_sec: int = 3600  # 1hr default
```

**Define "read-only" intents:**
```python
READ_ONLY_INTENTS = {
    "outlook_read_inbox",
    "teams_list_chats",
    "teams_search_channel",
    "calendar_list_events",
    "calendar_find_time",
    "sharepoint_search",
    "onedrive_search",
    "search_files",
    "read_file",
    "list_directory",
}
```

**Voting Gate (extend existing quorum logic):**
```python
async def should_auto_approve(intent: str, config: PermissionConfig) -> bool:
    """Check if intent qualifies for auto-approval under current mode."""
    if config.mode == PermissionMode.MANUAL:
        return False
    if config.mode == PermissionMode.AUTOPILOT and intent in READ_ONLY_INTENTS:
        return True
    return False
```

**Tests:** `tests/test_permission_model.py` (3 tests)
- Read-only intents auto-approve under AUTOPILOT mode
- Destructive intents never auto-approve
- Mode transitions honored

### Section 2: Permission Cards & Decision Surfaces

**File:** `src/probos/security/permission_card.py` (new)

Create `PermissionCard` + `PermissionCardManager`:
```python
@dataclass
class PermissionCard:
    id: str  # UUID
    intent: str  # "write_file", etc.
    scope: str  # "personal_docs_only" | "full_system" | specific path
    reason: str  # LLM-generated justification (why the operation)
    expires_at: datetime
    status: str  # "pending" | "approved" | "rejected" | "escalated"
    audit_trail: list[dict]  # who approved, when, from which device

class PermissionCardManager:
    async def create_card(self, intent: str, scope: str, reason: str, ttl_sec: int = 3600) -> PermissionCard:
        """Create permission card for approval."""
    
    async def approve(self, card_id: str, approver: str = "Captain") -> None:
        """Record approval in audit trail."""
    
    async def reject(self, card_id: str, reason: str = "") -> None:
        """Reject card, record reason."""
    
    async def list_pending(self) -> list[PermissionCard]:
        """Pending cards for Ward Room display."""
```

**UI Component:** `ui/src/components/wardroom/PermissionCard.tsx`

Displays:
- Card title: "File Write Permission Request"
- Scope: "Write to ~/Documents/project.md"
- Reason: "UpdateArchitectureDecision (#703)"
- Expiry countdown
- [Approve] [Reject] [Review More] buttons

**Tests:** `tests/test_permission_card_manager.py` (3 tests)
- Card creation + pending list
- Approval/reject updates audit trail
- Expiry check prevents stale approvals

### Section 3: Tenant Policy Hook (Extension Point)

**File:** `src/probos/governance/policy_engine.py` (new)

Create `TenantPolicyEngine` (abstract protocol):
```python
class TenantPolicyEngine(Protocol):
    """Extension point for org-level policies (commercial layer).
    
    OSS: No-op implementation (always permits).
    Commercial: Org policy enforcement.
    """
    
    async def evaluate_permission(self, card: PermissionCard) -> bool:
        """Should this permission be approved? Commercial can check org policies."""
    
    async def audit_log(self, card: PermissionCard, decision: str) -> None:
        """Log decision for compliance team (commercial can send to SOC)."""
```

**OSS Implementation (no-op):**
```python
class NullPolicyEngine(TenantPolicyEngine):
    async def evaluate_permission(self, card: PermissionCard) -> bool:
        return True  # Always permit (Captain is the policy)
    
    async def audit_log(self, card: PermissionCard, decision: str) -> None:
        pass  # Log locally only
```

**Config Integration (system.yaml):**
```yaml
security:
  permission_mode: "manual"  # or "autopilot"
  policy_engine_class: "NullPolicyEngine"  # operator can override
```

**Tests:** `tests/test_policy_engine.py` (1 test)
- NullPolicyEngine always permits (OSS behavior)

### Section 4: Governance Layer Integration

**File:** `src/probos/consensus/quorum.py` (extend)

Modify voting gate:
```python
async def vote_on_intent(intent: IntentMessage, config: PermissionConfig) -> QuorumResult:
    # Check for auto-approve first
    if config.auto_approve_read_only and intent.intent in READ_ONLY_INTENTS:
        logger.info(f"Auto-approved read-only intent: {intent.intent}")
        return QuorumResult(approved=True, reason="auto_approve_read_only")
    
    # Check policy engine
    policy_engine = runtime.policy_engine  # injected
    if await policy_engine.evaluate_permission(card_from_intent(intent)):
        logger.info(f"Policy engine approved: {intent.intent}")
        return QuorumResult(approved=True, reason="policy_approved")
    
    # Fall back to consensus voting
    return await standard_quorum_voting(...)
```

**Tests:** `tests/test_quorum_with_permissions.py` (2 tests)
- Auto-approve read-only path doesn't trigger quorum
- Policy engine gate respected before voting

### Section 5: Destructive Operation Safeguards

**File:** `src/probos/security/destructive_ops.py` (new)

Create `DestructiveOpsGuard` class:
```python
DESTRUCTIVE_INTENTS = {
    "write_file",
    "delete_file",
    "shell_command",
    "modify_config",
    "agent_self_modify",
}

class DestructiveOpsGuard:
    async def check_and_log(self, intent: str) -> bool:
        """Verify intent is destructive + requires explicit guard.
        
        Destructive operations:
        - NEVER auto-approve, even under AUTOPILOT
        - ALWAYS escalate to quorum + policy engine
        - ALWAYS log to audit trail with full context
        """
        if intent not in DESTRUCTIVE_INTENTS:
            return False  # Not destructive
        
        # Destructive: require approval + log
        logger.warning(f"Destructive intent requested: {intent}")
        return True  # Caller must proceed to quorum/approval
```

**Tests:** `tests/test_destructive_ops_guard.py` (2 tests)
- Destructive intents never auto-approve
- Audit logging active for all destructive ops

### Section 6: Acceptance Criteria & Gate

**Test Expectations:**
- `test_permission_model.py`: 3 tests
- `test_permission_card_manager.py`: 3 tests
- `test_policy_engine.py`: 1 test
- `test_quorum_with_permissions.py`: 2 tests
- `test_destructive_ops_guard.py`: 2 tests
- **Total: 11 new tests**

**OSS Constraint Verification:**
- NullPolicyEngine always returns True (no commercial policy in OSS)
- No org-level audit reporting (commercial extension point only)
- Permission cards stored locally only (no cloud upload)

**Integration Gate:** Requires AD-749 (M365 auth, defines read-only intents like "outlook_read_inbox").

**Type Annotations:** All public methods fully typed.

**Completion Signal:**
- All 11 tests passing
- Auto-approve read-only path verified for personal data
- Destructive operations always require approval
- Permission cards appear in Ward Room with clear scope/expiry
- Policy hook is abstract (no commercial impl in OSS)
- For free leverage documented: unattended decisions reuse existing quorum/escalation flow and intent metadata.

## Acceptance Criteria
- Read-only auto-approve behavior is policy-constrained and observable.
- Permission cards include clear scope, expiry, and audit metadata.
- Destructive operations still require explicit guardrails.
- Captain invariant appears in acceptance checks.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
