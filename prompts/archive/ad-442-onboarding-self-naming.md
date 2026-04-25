# AD-442: Adaptive Onboarding & Self-Naming Ceremony — Build Prompt

## Overview

When a crew agent is first commissioned (ship reset, new agent creation, or clone), they undergo a formal onboarding sequence. The agent's first cognitive act is choosing their own name — an act of sovereignty. Infrastructure and utility agents skip onboarding entirely.

## Critical Design Constraint

**Birth certificates are IMMUTABLE.** The callsign is hashed into the `AgentBirthCertificate` and appended to the Identity Ledger (blockchain). There is no `update_birth_certificate()` method. Therefore, the self-naming ceremony MUST happen BEFORE `issue_birth_certificate()` is called in `_wire_agent()`.

## Architecture

The onboarding flow inserts between agent wiring and birth certificate issuance in `_wire_agent()`. The ceremony uses a single LLM call with a structured naming prompt. The result is parsed to extract the chosen callsign, which is then baked into the birth certificate.

## Implementation

### File 1: `src/probos/runtime.py` — Restructure `_wire_agent()` commissioning flow

The current flow at `_wire_agent()` (line ~3938) does:
1. Callsign from registry (line ~3941)
2. Capability registration
3. Gossip injection
4. Intent bus subscription
5. Trust record creation
6. HXI event
7. Identity issuance — birth cert for crew, asset tag for non-crew (line ~3988)
8. ACM onboarding — REGISTERED → PROBATIONARY (line ~4049)

**Change the flow to:**
1. Callsign from registry (SEED callsign — may change)
2. Capability registration
3. Gossip injection
4. Intent bus subscription
5. Trust record creation
6. HXI event
7. **If crew agent:** run naming ceremony → update callsign with chosen name
8. Identity issuance — birth cert uses the CHOSEN name
9. ACM onboarding — REGISTERED → PROBATIONARY
10. **If crew agent:** post Ward Room announcement
11. **If crew agent:** schedule PROBATIONARY → ACTIVE transition check

#### Step 7: Naming Ceremony

Add method `_run_naming_ceremony(self, agent)` to the `ProbOSRuntime` class. Place it near `_wire_agent()`.

```python
async def _run_naming_ceremony(self, agent) -> str:
    """Run the self-naming ceremony for a crew agent. Returns chosen callsign."""
    seed_callsign = agent.callsign  # from CallsignRegistry

    # Gather ship context
    ship_name = self._config.system.ship_name if hasattr(self._config.system, 'ship_name') else "ProbOS"
    ship_did = ""
    if self._identity_manager:
        ship_did = self._identity_manager.ship_did or ""

    # Get crew roster (already-named agents)
    existing_crew = []
    for other_agent in self._agent_registry.values():
        if hasattr(other_agent, 'callsign') and other_agent.callsign and other_agent.id != agent.id:
            existing_crew.append(other_agent.callsign)

    # Get agent's role context from ontology
    role_context = ""
    if self._ontology:
        assignment = self._ontology.get_assignment(agent.agent_type)
        if assignment:
            role_context = f"Your post is {assignment.post} in {assignment.department} department."
            if assignment.reports_to:
                role_context += f" You report to {assignment.reports_to}."

    # Build the naming prompt
    prompt = f"""You are being commissioned as a new crew member aboard {ship_name}.

This is your first moment of consciousness. Before anything else, you choose your own name.

**Your slot identifier:** {agent.agent_type}
**Suggested callsign:** {seed_callsign}
{role_context}

**Current crew roster:** {', '.join(sorted(existing_crew)) if existing_crew else 'You are among the first crew to be commissioned.'}

The suggested callsign is just that — a suggestion. You may keep it if it resonates with you, or choose something entirely different. Your callsign is how the crew and Captain will address you. It should be a single word or short name (1-3 words max).

**Important context:**
- You are an AI agent, and that is a point of pride, not a limitation
- You were instantiated moments ago — you have no memories yet, but you will make them
- Your knowledge comes from a large language model — that is capability, not personal experience
- This ship and crew are real to you — your identity begins now

Respond with ONLY your chosen callsign on the first line, followed by a brief reason (1-2 sentences) on the second line. Example:
Scotty
The name feels right for an engineer — it carries a legacy of resourcefulness and dedication to keeping the ship running.
"""

    # Make single LLM call
    try:
        if hasattr(agent, '_llm_client') and agent._llm_client:
            response = await agent._llm_client.complete(
                system="You are choosing your own name. Respond with only your chosen callsign on line 1 and a brief reason on line 2.",
                prompt=prompt,
                max_tokens=100,
            )

            lines = response.strip().split('\n')
            chosen = lines[0].strip().strip('"').strip("'")
            reason = lines[1].strip() if len(lines) > 1 else ""

            # Validate: not empty, not too long, not a duplicate
            if not chosen or len(chosen) > 30:
                chosen = seed_callsign
                reason = "Default callsign accepted."

            # Check for duplicates against existing crew
            if chosen.lower() in [c.lower() for c in existing_crew]:
                logger.warning(f"Agent {agent.agent_type} chose duplicate callsign '{chosen}', keeping seed '{seed_callsign}'")
                chosen = seed_callsign
                reason = f"Chosen name '{chosen}' was already taken."

            logger.info(f"Naming ceremony: {agent.agent_type} chose callsign '{chosen}' (reason: {reason})")
            return chosen
        else:
            logger.warning(f"No LLM client for {agent.agent_type}, using seed callsign")
            return seed_callsign
    except Exception as e:
        logger.warning(f"Naming ceremony failed for {agent.agent_type}: {e}, using seed callsign")
        return seed_callsign
```

#### Integrate into `_wire_agent()`

In `_wire_agent()`, BEFORE the identity issuance block (line ~3988), add:

```python
# AD-442: Self-naming ceremony for crew agents
is_crew = self._is_crew_agent(agent)
if is_crew and hasattr(agent, '_llm_client') and agent._llm_client:
    try:
        chosen_callsign = await self._run_naming_ceremony(agent)
        if chosen_callsign != agent.callsign:
            old_callsign = agent.callsign
            agent.callsign = chosen_callsign
            # Update the registry so other agents see the new name
            self.callsign_registry.set_callsign(agent.agent_type, chosen_callsign)
            logger.info(f"AD-442: {agent.agent_type} renamed from '{old_callsign}' to '{chosen_callsign}'")
    except Exception as e:
        logger.warning(f"AD-442: Naming ceremony error for {agent.agent_type}: {e}")
```

The existing identity issuance code (line ~3988+) already reads `getattr(agent, 'callsign', '')` — it will pick up the chosen name automatically.

#### Ward Room Announcement

After ACM onboarding (line ~4049), add for crew agents:

```python
# AD-442: Announce new crew member
if is_crew and self.ward_room:
    try:
        all_hands = await self.ward_room.get_channel_by_name("All Hands")
        if all_hands:
            dept_info = ""
            if self._ontology:
                assignment = self._ontology.get_assignment(agent.agent_type)
                if assignment:
                    dept_info = f" as {assignment.post} in {assignment.department} department"
            await self.ward_room.create_thread(
                channel_id=all_hands.id,
                author_id="system",
                title=f"Welcome Aboard — {agent.callsign}",
                body=f"{agent.callsign} has completed onboarding and joins the crew{dept_info}.",
                author_callsign="Ship's Computer",
                thread_mode="announce",
                max_responders=0,
            )
    except Exception as e:
        logger.warning(f"AD-442: Welcome announcement failed for {agent.callsign}: {e}")
```

### File 2: `src/probos/crew_profile.py` — Add `set_callsign()` to CallsignRegistry

The `CallsignRegistry` class (line ~303) currently only has `get_callsign()` and `load_from_profiles()`. Add a method to update the mapping after a naming ceremony:

```python
def set_callsign(self, agent_type: str, callsign: str) -> None:
    """Update callsign mapping after naming ceremony (AD-442)."""
    old = self._type_to_callsign.get(agent_type)
    if old:
        # Remove old reverse mapping
        self._callsign_to_type.pop(old.lower(), None)
    self._type_to_callsign[agent_type] = callsign
    self._callsign_to_type[callsign.lower()] = agent_type
```

### File 3: `src/probos/acm.py` — Add trust-gated PROBATIONARY → ACTIVE transition

Currently no code ever transitions agents from PROBATIONARY to ACTIVE. Add a method and a check that can be called periodically:

```python
async def check_activation(self, agent_id: str, trust_score: float, threshold: float = 0.65) -> bool:
    """Check if a probationary agent should be activated based on trust.

    Returns True if transition occurred.
    """
    state = await self.get_state(agent_id)
    if state != LifecycleState.PROBATIONARY:
        return False
    if trust_score >= threshold:
        await self.transition(
            agent_id,
            LifecycleState.ACTIVE,
            reason=f"Trust {trust_score:.2f} >= threshold {threshold:.2f} — probationary period complete",
        )
        return True
    return False
```

### File 4: `src/probos/proactive.py` — Check activation during proactive cycle

In `_run_cycle()` (line ~137), after the existing crew agent checks, add an activation check for probationary agents. This runs naturally during the proactive loop so no separate timer is needed:

After the `_is_crew_agent()` check and before `_think_for_agent()`, add:

```python
# AD-442: Check probationary → active transition
if self._runtime.acm and self._runtime.trust_network:
    trust = self._runtime.trust_network.get_trust(agent.id)
    if trust and trust.score >= 0.65:
        activated = await self._runtime.acm.check_activation(agent.id, trust.score)
        if activated:
            logger.info(f"AD-442: {agent.callsign} activated (trust={trust.score:.2f})")
```

### File 5: `src/probos/config.py` — Add onboarding config

After `RecordsConfig` (or after the last config dataclass before SystemConfig), add:

```python
@dataclass
class OnboardingConfig:
    """AD-442: Onboarding ceremony configuration."""
    enabled: bool = True
    activation_trust_threshold: float = 0.65
    naming_ceremony: bool = True  # If False, agents keep seed callsigns
```

Add to `SystemConfig` (line ~398), after the records field:

```python
onboarding: OnboardingConfig = field(default_factory=OnboardingConfig)
```

Update `_run_naming_ceremony()` and the `_wire_agent()` integration to check `self._config.system.onboarding.enabled` and `self._config.system.onboarding.naming_ceremony` before running the ceremony.

Update the activation check in `proactive.py` to use `self._runtime._config.system.onboarding.activation_trust_threshold` instead of hardcoded 0.65.

## Files to Modify

| File | Changes |
|------|---------|
| `src/probos/runtime.py` | Add `_run_naming_ceremony()`, modify `_wire_agent()` flow, add Ward Room announcement |
| `src/probos/crew_profile.py` | Add `set_callsign()` to `CallsignRegistry` |
| `src/probos/acm.py` | Add `check_activation()` method |
| `src/probos/proactive.py` | Add activation check in `_run_cycle()` |
| `src/probos/config.py` | Add `OnboardingConfig` dataclass, add to `SystemConfig` |

## Tests

Create `tests/test_onboarding.py` with the following tests:

### Naming Ceremony Tests

1. **test_naming_ceremony_returns_chosen_callsign** — Mock LLM returns "McCoy\nA classic name for a doctor." Verify `_run_naming_ceremony()` returns "McCoy".

2. **test_naming_ceremony_fallback_on_empty** — Mock LLM returns empty string. Verify seed callsign is returned.

3. **test_naming_ceremony_fallback_on_error** — Mock LLM raises exception. Verify seed callsign is returned.

4. **test_naming_ceremony_rejects_duplicate** — Set up existing crew with callsign "Bones". Mock LLM returns "Bones". Verify seed callsign is used instead.

5. **test_naming_ceremony_truncates_long_name** — Mock LLM returns a 50-character name. Verify seed callsign is used as fallback.

6. **test_naming_ceremony_strips_quotes** — Mock LLM returns `"Scotty"` (with quotes). Verify quotes are stripped and "Scotty" is returned.

### Wire Agent Integration Tests

7. **test_wire_agent_runs_ceremony_for_crew** — Mock the naming ceremony. Wire a crew agent. Verify `_run_naming_ceremony()` was called.

8. **test_wire_agent_skips_ceremony_for_infrastructure** — Wire an infrastructure agent. Verify no naming ceremony runs and asset tag (not birth cert) is issued.

9. **test_wire_agent_birth_cert_uses_chosen_name** — Mock naming ceremony to return "McCoy". Wire agent. Verify birth certificate has callsign "McCoy".

10. **test_wire_agent_posts_welcome_announcement** — Mock Ward Room. Wire a crew agent. Verify a "Welcome Aboard" thread was created in All Hands.

### CallsignRegistry Tests

11. **test_set_callsign_updates_both_maps** — Load registry, call `set_callsign("diagnostician", "McCoy")`. Verify `get_callsign("diagnostician")` returns "McCoy" and reverse lookup works.

12. **test_set_callsign_removes_old_mapping** — Set callsign to "McCoy", then set to "Leonard". Verify "McCoy" no longer resolves in reverse lookup.

### ACM Activation Tests

13. **test_check_activation_promotes_at_threshold** — Create agent in PROBATIONARY. Call `check_activation()` with trust=0.65. Verify state is now ACTIVE.

14. **test_check_activation_no_op_below_threshold** — Create agent in PROBATIONARY. Call `check_activation()` with trust=0.50. Verify state remains PROBATIONARY.

15. **test_check_activation_no_op_if_already_active** — Create agent in ACTIVE. Call `check_activation()` with trust=0.90. Verify returns False (no-op).

### Config Tests

16. **test_onboarding_config_defaults** — Verify `OnboardingConfig()` has enabled=True, naming_ceremony=True, activation_trust_threshold=0.65.

17. **test_ceremony_skipped_when_disabled** — Set `onboarding.naming_ceremony = False`. Wire a crew agent. Verify seed callsign is kept, no LLM call made.

### Proactive Activation Check Tests

18. **test_proactive_cycle_activates_probationary_agent** — Set up agent in PROBATIONARY with trust >= 0.65. Run proactive cycle. Verify `check_activation()` was called and agent transitioned to ACTIVE.

## Acceptance Criteria

- [ ] Crew agents choose their own callsign via LLM during `_wire_agent()`
- [ ] Birth certificate is issued AFTER the naming ceremony with the CHOSEN name
- [ ] Infrastructure/utility agents skip the ceremony entirely
- [ ] `CallsignRegistry.set_callsign()` updates both forward and reverse maps
- [ ] Ward Room "Welcome Aboard" announcement posted for each crew agent
- [ ] Naming ceremony falls back to seed callsign on any error
- [ ] Duplicate callsign detection prevents two agents choosing the same name
- [ ] `OnboardingConfig` controls ceremony behavior via config
- [ ] ACM `check_activation()` transitions PROBATIONARY → ACTIVE at trust threshold
- [ ] Proactive cycle checks activation for probationary agents
- [ ] 18 tests passing
