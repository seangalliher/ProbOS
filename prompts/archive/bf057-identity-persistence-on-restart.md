# BF-057: Identity Persistence on Restart (CRITICAL)

## Context

Restarting ProbOS without a reset causes every crew agent to re-run the naming ceremony from seed callsigns and pick entirely new names. Instance 3 crew (Curie, Pax, Keiko, Tesla, Reeves…) became Cortex, Bones, Hatch, Geordi, Sentinel on restart. Agents lose their identity every time the system restarts. This undermines the entire Persistent Agent Identity model (AD-441).

The birth certificate system (`identity.db`) DOES persist callsigns correctly — `resolve_or_issue()` returns the existing cert on warm boot. But the naming ceremony runs BEFORE identity resolution, so it never sees the existing cert. The fix is to check for an existing identity before running the naming ceremony.

## Prerequisites

- Read ALL files listed under each section below before modifying them
- Understand the boot ordering: agent spawn → naming ceremony → birth certificate resolution

---

## Root Cause Chain

1. **`CallsignRegistry.load_from_profiles()`** (crew_profile.py line 312) loads callsigns from YAML profile files → seed callsigns (Scotty, Number One, Wesley, LaForge…)
2. **Agent spawn** sets `agent.callsign` from the registry → always the seed callsign
3. **Naming ceremony** (runtime.py line 4006) guard: `if is_crew and self.config.onboarding.enabled and self.config.onboarding.naming_ceremony:` — runs unconditionally, no check for existing identity
4. **LLM call** chooses a new name from the seed callsign as "Suggested callsign" → new name every time
5. **`set_callsign()`** (crew_profile.py line 380) updates in-memory registry — never persists to disk
6. **Birth cert `resolve_or_issue()`** (identity.py line 731) runs AFTER naming ceremony, finds existing cert with the OLD callsign, but the agent already has a new one. The cert's callsign field goes stale.

## Fix Overview

**Strategy:** Before running the naming ceremony, check if the identity registry already has a birth certificate for this agent's slot. If yes, restore that callsign and skip the ceremony. The birth certificate IS the source of truth for agent identity across restarts.

---

## Fix 1: Skip naming ceremony when identity already exists

**File to modify:**
- `src/probos/runtime.py` — the agent registration block around lines 4004-4020

**Implementation:**

Replace the naming ceremony block (lines 4004-4020) with:

```python
        # AD-442: Self-naming ceremony for crew agents
        # BF-057: Check for existing identity FIRST — skip ceremony on warm boot
        is_crew = self._is_crew_agent(agent)
        _existing_identity_callsign = ""
        if is_crew and self.identity_registry:
            existing_cert = self.identity_registry.get_by_slot(agent.id)
            if existing_cert and existing_cert.callsign:
                _existing_identity_callsign = existing_cert.callsign

        if _existing_identity_callsign:
            # Warm boot — restore persisted identity, skip naming ceremony
            if agent.callsign != _existing_identity_callsign:
                agent.callsign = _existing_identity_callsign
                self.callsign_registry.set_callsign(agent.agent_type, _existing_identity_callsign)
                # BF-049: Sync ontology so peers/reports_to show current callsigns
                if hasattr(self, 'ontology') and self.ontology:
                    self.ontology.update_assignment_callsign(agent.agent_type, _existing_identity_callsign)
                logger.info("BF-057: %s identity restored from birth certificate: '%s'",
                           agent.agent_type, _existing_identity_callsign)
        elif is_crew and self.config.onboarding.enabled and self.config.onboarding.naming_ceremony:
            # Cold start — run naming ceremony
            if hasattr(agent, '_llm_client') and agent._llm_client:
                try:
                    chosen_callsign = await self._run_naming_ceremony(agent)
                    if chosen_callsign != agent.callsign:
                        old_callsign = agent.callsign
                        agent.callsign = chosen_callsign
                        # Update the registry so other agents see the new name
                        self.callsign_registry.set_callsign(agent.agent_type, chosen_callsign)
                        # BF-049: Sync ontology so peers/reports_to show current callsigns
                        if hasattr(self, 'ontology') and self.ontology:
                            self.ontology.update_assignment_callsign(agent.agent_type, chosen_callsign)
                        logger.info("AD-442: %s renamed from '%s' to '%s'", agent.agent_type, old_callsign, chosen_callsign)
                except Exception as e:
                    logger.warning("AD-442: Naming ceremony error for %s: %s", agent.agent_type, e)
```

Key logic:
- **If birth certificate exists for this slot** → restore callsign from cert, skip ceremony entirely
- **If no birth certificate** (cold start / first boot) → run naming ceremony as before
- The identity check MUST happen before the ceremony decision, not after

**IMPORTANT:** The `self.identity_registry` must be initialized and started before agent registration reaches this point. Verify that `identity_registry.start()` runs before `_register_agent()` is called. Read the boot sequence to confirm. If `identity_registry` is not yet started when agents are registered, the slot cache will be empty and the fix won't work. In that case, move the identity registry initialization earlier in the boot sequence.

---

## Fix 2: Verify boot ordering (identity registry before agent spawn)

**File to read:**
- `src/probos/runtime.py` — the `start()` method

**Check:** Find where `self.identity_registry` is started (the `await self.identity_registry.start(data_dir)` call) and where agents are spawned/registered. The identity registry MUST be started and its database loaded BEFORE any call to `_register_agent()`.

If the ordering is wrong, move the identity registry start earlier. If it's already correct (identity is one of the early infrastructure services), no changes needed here — just verify.

**Evidence from the boot log:** The log shows `Identity registry loaded 39 certificates, 46 asset tags` BEFORE the naming ceremonies start, which suggests the ordering is correct. But verify in code to be sure.

---

## Fix 3: Ensure birth certificate callsign stays in sync

**File to modify:**
- `src/probos/runtime.py` — after naming ceremony, when issuing birth certificate

**Current code** (line 4048):
```python
_callsign = getattr(agent, 'callsign', '') or agent.agent_type
```

This already uses `agent.callsign` which will have the ceremony-chosen name on cold start, or the restored name on warm boot. No change needed here — but verify that `resolve_or_issue()` does NOT overwrite the callsign on the existing cert when it finds one by slot_id.

**Check in `identity.py`** (line 731-733):
```python
existing = self.get_by_slot(slot_id)
if existing:
    return existing  # Returns existing cert unchanged — correct!
```

This is correct — it returns the existing cert as-is, doesn't update it. The callsign in the cert stays as it was at first issuance. **No changes needed here.**

---

## Tests

**New file: `tests/test_identity_persistence.py`**

```python
"""BF-057: Test identity persistence across restarts."""
import pytest

# Test 1: Naming ceremony skipped when identity exists
async def test_naming_ceremony_skipped_with_existing_identity():
    """When an agent has an existing birth certificate, naming ceremony should not run."""
    # Setup:
    # - Create a mock identity_registry with get_by_slot returning a cert with callsign="Tesla"
    # - Create a mock agent with callsign="LaForge" (seed callsign)
    # - Run the registration logic
    # Assert:
    # - agent.callsign == "Tesla" (restored from cert)
    # - callsign_registry has "Tesla" for engineering_officer
    # - No LLM call was made (naming ceremony skipped)

# Test 2: Naming ceremony runs when no identity exists
async def test_naming_ceremony_runs_without_identity():
    """On cold start (no existing cert), naming ceremony should run normally."""
    # Setup:
    # - Create a mock identity_registry with get_by_slot returning None
    # - Create a mock agent with LLM client
    # - Mock LLM to return "Forge"
    # - Run the registration logic
    # Assert:
    # - agent.callsign == "Forge" (ceremony-chosen)
    # - LLM call was made

# Test 3: Ontology synced on warm boot restore
async def test_ontology_synced_on_identity_restore():
    """When callsign is restored from cert, ontology should be updated."""
    # Setup:
    # - Mock identity_registry with cert callsign="Tesla"
    # - Mock ontology with update_assignment_callsign
    # - Run registration logic
    # Assert:
    # - ontology.update_assignment_callsign called with ("engineering_officer", "Tesla")

# Test 4: Log message confirms warm boot identity restore
async def test_warm_boot_identity_restore_logged():
    """BF-057 restore should log an info message."""
    # Setup: same as test 1
    # Assert: "BF-057: engineering_officer identity restored from birth certificate: 'Tesla'" logged

# Test 5: Identity registry empty slot returns None (cold start path)
async def test_identity_registry_empty_slot():
    """get_by_slot for non-existent slot should return None, triggering naming ceremony."""
    # Direct unit test of identity_registry.get_by_slot with unknown slot_id

# Test 6: Callsign registry updated on warm boot
async def test_callsign_registry_updated_on_restore():
    """CallsignRegistry should reflect restored callsign, not seed callsign."""
    # Setup: restore from cert with callsign="Tesla"
    # Assert: callsign_registry.get_callsign("engineering_officer") == "Tesla"
    # Assert: callsign_registry.resolve("tesla") returns engineering_officer
```

These tests should mock or stub the identity_registry, ontology, and LLM client. They should NOT require a running ProbOS instance. Pattern: use the same mocking style as `tests/test_onboarding.py`.

---

## Verification

1. **Targeted tests** — `uv run pytest tests/test_identity_persistence.py -v`
2. **Regression** — `uv run pytest tests/test_onboarding.py tests/test_callsign_validation.py tests/test_ontology_callsign_sync.py -v`
3. **Manual verification** — most important:
   - `uv run probos reset -y` → fresh start, all agents run naming ceremony, pick names
   - Note the names (e.g., Tesla, Reeves, Curie, Pax…)
   - Stop ProbOS (Ctrl+C)
   - `uv run probos serve --interactive` → restart WITHOUT reset
   - Verify: agents should restore their previous names with `BF-057:` log messages
   - NO naming ceremony LLM calls on warm boot
   - Crew names should be identical to pre-restart

## Files Summary

**Modify:**
- `src/probos/runtime.py` — add identity check before naming ceremony (~lines 4004-4020)

**Verify (read but may not need changes):**
- `src/probos/runtime.py` — boot sequence ordering (identity registry start vs agent spawn)
- `src/probos/identity.py` — `resolve_or_issue()` behavior (should be correct as-is)

**Create:**
- `tests/test_identity_persistence.py` — 6 tests for identity persistence

## Tracking

Update on completion:
- `PROGRESS.md` — mark BF-057 closed
- `DECISIONS.md` — add BF-057 entry
- `docs/development/roadmap.md` — update bug tracker entry to Closed
