# AD-758 - Yeo Feature-Complete Integration Gate

Status: drafted (planning slate only)
Issue: #704
Parent: #486
Depends on: AD-749 through AD-757
Dedupe refs: #480, #484, #538

## Objective
Define completion rubric and integration gate for the Yeo OSS feature-complete program.

## Captain Invariant
Capability is usable by all crew agents; Yeo is the front-door orchestrator and delegates to specialists.

## In Scope
- Program-level checklist across AD-749..AD-757.
- Cross-crew capability exposure verification.
- Delegation-policy conformance verification.
- "For free" learning upgrades surfaced explicitly in each child AD acceptance criteria.
- No-duplicate gate against existing open issues and shipped waves.

## Out of Scope
- Production implementation work.
- DECISIONS.md architectural logging updates.

## OSS vs Commercial Split

**OSS (Personal Desktop) Completeness Gate:**
- All AD-749..AD-757 child prompts include OSS scopes fully realized.
- No production code depends on commercial-only extension points.
- Every personal-workflow scenario has a "works today" implementation.

**Commercial Extension Points Documented (Not Implemented):**
- Multi-tenant auth/provisioning.
- Org policy engine and compliance reporting.
- Fleet management and cross-device sync.
- DLP and advanced security controls.
- Team-level features and analytics.

## File Targets
- `prompts/ad-749-*.md` through `prompts/ad-757-*.md`
- `docs/development/roadmap.md`
- `PROGRESS.md`
- `prompts/wave-plan.yaml`

## Pre-Flight Anchors
- Verify umbrella and existing issue set in roadmap/open issues.
- Verify wave 175-180 shipped scope already covers voice/perception stacks.
- Verify dedupe references to #480, #484, #538 and #486.

## Implementation Spec

### Section 1: Program-Level Completion Rubric

Create checklist to verify all AD-749..AD-757 deliverables are shipped:

| Phase | AD | Feature | Status | Tests | Notes |
|-------|----|---------|-|----|
| 1 (Foundation) | AD-749 | M365 Auth + Connectors | ☐ | 24 | 5 agents (Outlook/Teams/Calendar/SharePoint/OneDrive) |
| 1 | AD-750 | Semantic Work Layer | ☐ | 9 | Tasks, meetings, commitments, threads + queries |
| 1 | AD-751 | Desktop UX Surface | ☐ | 6 | Tray, hotkey, notifications, autostart |
| 1 | AD-752 | Proactive Scheduling | ☐ | 11 | Work-hours, quiet-hours, daily briefing, heartbeat scans |
| 2 (Safety) | AD-753 | Unattended Permissions | ☐ | 11 | autoApproveReadOnly, permission cards, policy hook |
| 2 | AD-754 | Data Hardening | ☐ | 14 | Encryption, PII redaction, audit log, "forget this" |
| 2 | AD-755 | Office Doc Skills | ☐ | 10 | DOCX/PPTX/XLSX agents + templates + SharePoint routing |
| 3 (UX) | AD-756 | Conversational Front-Door | ☐ | 10 | Suggested actions, daily briefing, delegation visibility, stream merge |
| 3 | AD-757 | Identity + Continuity | ☐ | 9 | Captain Card, session recovery, voice/avatar, task recovery |
| Gate | AD-758 | Integration Gate | ☐ | (N/A) | Program verification + cross-crew exposure audit |

**Total Expected Tests:** 24+9+6+11+11+14+10+10+9 = 104 new tests

**Expected Test Timeline:**
- AD-749: ~2h
- AD-750..AD-752: ~3h (parallelizable)
- AD-753..AD-755: ~3h (parallelizable)
- AD-756..AD-757: ~2h (dependency: AD-750 onwards)
- AD-758: ~30m (gate verification)
- **Total: ~12-14h cumulative build time**

### Section 2: Cross-Crew Capability Exposure Verification

**Verification Gate:** Every capability registered in AD-749..AD-757 must be accessible to all crew agents, not Yeo-exclusive.

**Check List:**
```python
async def verify_captain_invariant():
    """Verify all Yeo capabilities usable by crew agents."""
    
    # All M365 connectors available to other agents
    for intent in ["outlook_read_inbox", "teams_list_chats", "calendar_find_time"]:
        agents = runtime.find_agents_for_intent(intent)
        assert len(agents) >= 1, f"No agent found for {intent}"
    
    # Semantic work layer accessible to all via runtime APIs
    work_layer = runtime.semantic_store
    assert work_layer is not None, "Semantic store not initialized"
    
    # Desktop UX optional but present
    if config.desktop.enabled:
        assert runtime._tray_manager is not None
    
    # Unattended permissions enforced at consensus layer
    assert runtime.permission_model is not None
    
    # Audit log tracks all actions
    assert runtime.audit_log is not None
    
    logger.info("Captain Invariant verified: all crew can use all capabilities")
```

**Tests:** `tests/test_captain_invariant_exposure.py` (1 test)
- All AD-749..AD-757 capabilities accessible to non-Yeo agents

### Section 3: OSS Scope Verification (No Commercial Code in OSS)

**Verification Gate:** No production code in OSS repo depends on commercial-only extension points.

**Check List:**
```python
def verify_oss_scope():
    """Verify no commercial-only features implemented in OSS."""
    
    # Auth: no multi-tenant code
    assert "multi_tenant" not in read_file("src/probos/integrations/m365_token_manager.py")
    
    # Policy: NullPolicyEngine only (abstract hook, no impl)
    policy_impl = read_file("src/probos/governance/policy_engine.py")
    assert "class NullPolicyEngine" in policy_impl
    assert "class TenantPolicyEngine(Protocol)" in policy_impl  # Abstract only
    
    # Data: no DLP/HSM/compliance overlays
    assert "dataloss" not in read_file("src/probos/security/data_hardening.py").lower()
    assert "hsm" not in read_file("src/probos/security/credential_encryption.py").lower()
    
    # Desktop: personal-only, no fleet management
    assert "fleet" not in read_file("src/probos/experience/desktop/lifecycle.py").lower()
    
    # Office: personal templates only, no org library
    registry = read_file("src/probos/integrations/template_registry.py")
    assert "local" in registry and "git" in registry
    assert "org_library" not in registry and "sharepoint_library" not in registry
    
    logger.info("OSS Scope verified: no commercial-only code present")
```

**Tests:** `tests/test_oss_scope_verification.py` (1 test)
- No commercial-only code patterns detected in OSS

### Section 4: Delegation Policy Conformance

**Verification Gate:** All crew-to-Yeo interactions follow explicit delegation contracts.

**Check List:**
```python
async def verify_delegation_policy():
    """Every agent-to-Yeo interaction has explicit reasoning."""
    
    # All agent intents declared in registry
    intents = runtime.list_all_intents()
    for intent in intents:
        descriptor = runtime.get_intent_descriptor(intent)
        assert descriptor.description, f"Intent {intent} missing description"
    
    # Delegation from Yeo to crew tracked in session
    session = runtime.active_session
    assert hasattr(session, 'delegations'), "Session missing delegation tracking"
    
    # Crew can re-delegate back to Yeo or other crew
    # (e.g. OutlookAgent can ask for ArchitectAgent help via intent bus)
    assert runtime.intent_bus is not None
    
    logger.info("Delegation policy verified: all interactions traceable")
```

**Tests:** `tests/test_delegation_policy.py` (1 test)
- All intents have descriptions
- Delegation chain traceable

### Section 5: "For Free" Learning Upgrades

**Verification Gate:** Every child AD documents "for free" value from infrastructure already shipped.

**Check List:**
Each AD acceptance criteria MUST include a line like:
- AD-749: "M365 token-refresh automatic without extra work (leveraging existing async supervision)"
- AD-750: "Semantic search free (using existing ChromaDB integration + Episodic memory)"
- AD-752: "Proactive scans free (APScheduler already in dependencies)"
- AD-754: "PII redaction free (all log records flow through formatter layer)"

**Tests:** `tests/test_for_free_documentation.py` (1 test)
- Each AD-749..AD-757 includes "for free" learning in acceptance criteria

### Section 6: Integration Gate Execution

**Verification Steps (Order Matters):**

1. **Dependency Order:** Build AD-749 → AD-750 → (AD-751 || AD-752 || AD-753) → AD-754..AD-755 → AD-756 → AD-757 → AD-758
2. **Unit Test Passing:** All 104 tests green before merging each AD
3. **Integration Test:** Cross-crew scenario tests (e.g., ArchitectAgent uses Outlook connector delegated from Yeo)
4. **Captain Invariant Spot Check:** Manually verify one capability is accessible to 2+ crew agents
5. **OSS Scope Audit:** `grep` for commercial keywords + no-commercial-only code patterns
6. **Delegation Policy Audit:** Trace one Yeo-to-crew-to-Yeo flow end-to-end
7. **"For Free" Checklist:** Verify each AD captures infrastructure leverage

### Section 7: Acceptance Criteria & Gate

**Completion Requirements:**
1. All 104 child tests passing
2. Captain Invariant verified (all crew can use all capabilities)
3. OSS scope verified (no commercial-only code)
4. Delegation policy traced end-to-end
5. All child ADs document "for free" leverage
6. Dedupe check passed (no conflicts with #480, #484, #538, #486)

**Final Output:**
- `PROGRESS.md` updated: "Yeo OSS feature-complete [AD-749..AD-757] shipped Wave 181"
- `docs/development/roadmap.md` updated: AD-749..AD-758 marked done, wave 182 activated
- `prompts/wave-plan.yaml` updated: Wave 181 closure with final metrics

**Gate Decision:**
- ✅ All checks pass → Wave 181 complete, merge to main
- ❌ Any check fails → File FIX AD (e.g. AD-758-FIX-1) with specific gap

## Acceptance Criteria
- Completion rubric is objective, testable, and ordered by dependency.
- Every child AD includes Captain invariant text.
- Program gate explicitly blocks duplicate scope against existing issues.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
