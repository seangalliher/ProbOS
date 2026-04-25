# AD-398: Crew Identity Alignment — Three-Tier Agent Architecture

## Context

AD-397 introduced callsign addressing (`@callsign`) and 1:1 crew sessions. Testing revealed that `@wesley` only returns scout reports instead of having a conversation. Root cause: the agent's `act()` override parses LLM output for domain-specific format (===SCOUT_REPORT=== blocks) and discards conversational responses.

Deeper analysis revealed a category confusion in the agent architecture. Non-cognitive agents (BaseAgent subclasses with no LLM) were classified as department crew with callsigns, blurring the line between infrastructure and crew. This AD establishes a clean three-tier architecture and fixes 1:1 conversations.

## Architecture Decision

### Three Agent Tiers

| Tier | Identity | LLM | Callsign | 1:1 Sessions | Base Class |
|------|----------|-----|----------|---------------|------------|
| **Core Infrastructure** | Ship's Computer function | Optional | No | No | `BaseAgent` |
| **Utility** | General-purpose tool | Yes | No | No | `CognitiveAgent` (with `_BundledMixin`) |
| **Crew** | Sovereign individual | Yes | Yes | Yes | `CognitiveAgent` |

**Principle:** If it doesn't have Character/Reason/Duty — if it's not a sovereign individual — it's not crew. The Ship's Computer can use LLMs but has no personality, no episodic memory shard, no dreams, no trust growth.

### Reclassifications (Infrastructure, Not Crew)

These agents are infrastructure. Remove their crew profiles (callsigns):

| Agent | Current | Why Infrastructure |
|-------|---------|-------------------|
| IntrospectAgent ("Data") | Core, has callsign | Ship's Computer self-analysis |
| VitalsMonitor ("Chapel") | Medical dept | Programmatic heartbeat monitor |
| RedTeamAgent ("Worf") | Security dept | Programmatic security scanner |
| SystemQAAgent ("O'Brien") | Self-mod dept | Programmatic QA checks |

### New Cognitive Crew Agents

| Callsign | Department | Role | What They Do |
|----------|------------|------|-------------|
| **Worf** | Security | Chief | Cognitive security analysis — threat assessment, vulnerability review, code security audit, access control analysis. Unlike the programmatic RedTeamAgent which runs automated scans, Worf reasons about security risks and provides strategic security guidance. |
| **O'Brien** | Operations | Chief | Cognitive operations management — resource analysis, cross-department coordination, task optimization, capacity planning, system efficiency analysis. Thinks about how to keep the ship running smoothly. |
| **LaForge** | Engineering | Chief | Cognitive systems engineering — performance analysis, architecture review, system optimization, technical debt assessment, infrastructure health. Complements Scotty (Builder) who writes code — LaForge thinks about systems holistically. |

## Changes Required

### Part 1: Fix 1:1 Conversations in Existing Crew Agents

The `CognitiveAgent.handle_intent()` correctly bypasses `_handled_intents` for targeted `direct_message` intents (AD-397). The LLM receives the message and responds conversationally. But agent subclasses with overridden `act()` methods parse for domain-specific output formats and discard conversational text.

**Fix**: Add a `direct_message` early-return guard at the top of each overridden `act()`:

```python
async def act(self, decision: dict[str, Any]) -> dict[str, Any]:
    # AD-398: pass through conversational responses for 1:1 sessions
    if decision.get("intent") == "direct_message":
        return {"success": True, "result": decision.get("llm_output", "")}
    # ... existing domain-specific logic unchanged ...
```

**IMPORTANT**: For this guard to work, the `intent` field must be available in the `decision` dict. Currently, `decide()` does NOT include it. You need to propagate the intent name through the lifecycle. The cleanest approach: in `handle_intent()`, after `decide()` returns, inject the intent name into the decision dict before passing to `act()`:

In `cognitive_agent.py`, `handle_intent()`, after line `decision = await self.decide(observation)`, add:
```python
decision["intent"] = intent.intent
```

This makes the intent name available to all `act()` overrides without changing any method signatures.

**Agents requiring the act() guard** (5 files):

1. **ScoutAgent** (`src/probos/cognitive/scout.py`) — `act()` parses `===SCOUT_REPORT===` blocks. Without the guard, conversational responses are parsed as empty findings → "No significant findings today."

2. **BuilderAgent** (`src/probos/cognitive/builder.py`) — `act()` parses file change blocks (CREATE/MODIFY/SEARCH/REPLACE). Without the guard, conversational responses are parsed as empty changes.

3. **ArchitectAgent** (`src/probos/cognitive/architect.py`) — `act()` parses `===PROPOSAL===` blocks into `ArchitectProposal` dataclass. Without the guard, conversational responses fail parsing.

4. **SurgeonAgent** (`src/probos/agents/medical/surgeon.py`) — `act()` parses JSON for remediation actions (force_dream, surge_pool, recycle_agent). Has an `else` fallback that accidentally works, but the explicit guard is needed for safety.

5. **CounselorAgent** (`src/probos/cognitive/counselor.py`) — `act()` checks for `action=="assess"`. Has a fallback that returns plan as-is, but add the explicit guard for consistency.

### Part 2: Remove Crew Profiles from Infrastructure Agents

**Delete these crew profile YAML files** (the agents keep working, they just lose callsigns):

- `config/standing_orders/crew_profiles/introspect.yaml`
- `config/standing_orders/crew_profiles/vitals_monitor.yaml`
- `config/standing_orders/crew_profiles/red_team.yaml`
- `config/standing_orders/crew_profiles/system_qa.yaml`
- `config/standing_orders/crew_profiles/emergent_detector.yaml` (orphaned — no agent class exists)

**Move infrastructure agents to core pool group** in `runtime.py`:

Current pool group memberships:
- `medical` group contains `medical_vitals` — remove it
- `security` group contains `red_team` — remove it
- `self_mod` group contains `system_qa` — remove it
- `introspect` is already in `core`

Add these pools to the `core` pool group:
```python
pool_names={"system", "filesystem", "filesystem_writers", "directory", "search", "shell", "http", "introspect", "medical_vitals", "red_team", "system_qa"},
```

If removing `red_team` from the `security` pool group leaves it empty, that's fine — the new cognitive Security agent will be added to it (see Part 3).

If removing `medical_vitals` from the `medical` pool group, that's fine — medical still has diagnostician, surgeon, pharmacist, pathologist.

### Part 3: Create New Cognitive Crew Agents

Create three new `CognitiveAgent` subclasses following the **pharmacist pattern** (cleanest — no `act()` override, base `act()` passes LLM output through). This ensures 1:1 conversations work out of the box.

#### 3a. SecurityAgent — "Worf" (Security Chief)

**File:** `src/probos/cognitive/security_officer.py`

```python
"""SecurityAgent — cognitive security analysis and threat assessment (AD-398)."""

from __future__ import annotations
from typing import Any
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import CapabilityDescriptor, IntentDescriptor
```

**Class attributes:**
- `agent_type = "security_officer"`
- `tier = "domain"`
- `instructions` — System prompt defining Worf's role: security analysis, threat assessment, vulnerability review, code security audit, access control analysis. Should reflect personality: direct, disciplined, protective, values honor and duty. Naturally skeptical. Speaks with military precision. Follows the pattern of existing instructions (see scout.py, diagnostician.py for style).

**Intent descriptors:**
```python
intent_descriptors = [
    IntentDescriptor(
        name="security_assess",
        params={"target": "component, file, or system area to assess"},
        description="Assess security posture of a component or system area",
    ),
    IntentDescriptor(
        name="security_review",
        params={"code": "code or file path to review for security issues"},
        description="Review code or configuration for security vulnerabilities",
    ),
]
_handled_intents = {"security_assess", "security_review"}
```

**`__init__`:**
```python
def __init__(self, **kwargs: Any) -> None:
    kwargs.setdefault("pool", "security_officer")
    super().__init__(**kwargs)
    self._runtime = kwargs.get("runtime")
```

**No `perceive()` or `act()` overrides** — use base CognitiveAgent implementations. The base `act()` returns LLM output directly, which works for both domain intents and `direct_message` conversations.

**Crew profile** — `config/standing_orders/crew_profiles/security_officer.yaml`:
```yaml
display_name: "Security Officer"
callsign: "Worf"
department: "security"
role: "chief"
personality:
  openness: 0.4           # Conservative, security-minded
  conscientiousness: 0.9   # Extremely disciplined
  extraversion: 0.3        # Reserved, speaks when necessary
  agreeableness: 0.2       # Naturally skeptical, challenges assumptions
  neuroticism: 0.5         # Vigilant, alert to threats
```

#### 3b. OperationsAgent — "O'Brien" (Operations Chief)

**File:** `src/probos/cognitive/operations_officer.py`

**Class attributes:**
- `agent_type = "operations_officer"`
- `tier = "domain"`
- `instructions` — System prompt defining O'Brien's role: resource analysis, cross-department coordination, capacity planning, task optimization, system efficiency. Should reflect personality: practical, hardworking, down-to-earth problem solver. Worries about edge cases. Gets things done without fanfare. The NCO who keeps everything running.

**Intent descriptors:**
```python
intent_descriptors = [
    IntentDescriptor(
        name="ops_status",
        params={"focus": "optional area to focus on"},
        description="Analyze current operational status — resource usage, coordination, efficiency",
    ),
    IntentDescriptor(
        name="ops_coordinate",
        params={"task": "task or initiative requiring cross-department coordination"},
        description="Plan cross-department coordination for a task or initiative",
    ),
]
_handled_intents = {"ops_status", "ops_coordinate"}
```

**`__init__`:**
```python
def __init__(self, **kwargs: Any) -> None:
    kwargs.setdefault("pool", "operations_officer")
    super().__init__(**kwargs)
    self._runtime = kwargs.get("runtime")
```

**No `perceive()` or `act()` overrides.**

**Crew profile** — `config/standing_orders/crew_profiles/operations_officer.yaml`:
```yaml
display_name: "Operations Officer"
callsign: "O'Brien"
department: "operations"
role: "chief"
personality:
  openness: 0.4           # Practical, proven approaches
  conscientiousness: 0.9   # Meticulous, reliable
  extraversion: 0.4        # Approachable but not flashy
  agreeableness: 0.7       # Team player, cooperative
  neuroticism: 0.5         # Worrier — catches edge cases
```

#### 3c. EngineeringAgent — "LaForge" (Engineering Chief)

**File:** `src/probos/cognitive/engineering_officer.py`

**Class attributes:**
- `agent_type = "engineering_officer"`
- `tier = "domain"`
- `instructions` — System prompt defining LaForge's role: performance analysis, architecture review, system optimization, technical debt assessment, infrastructure health. Should reflect personality: analytical, innovative, collaborative. Sees the big engineering picture. Optimistic but realistic. Loves solving impossible problems.

**Intent descriptors:**
```python
intent_descriptors = [
    IntentDescriptor(
        name="engineering_analyze",
        params={"target": "system, component, or area to analyze"},
        description="Analyze system performance, architecture, or technical health",
    ),
    IntentDescriptor(
        name="engineering_optimize",
        params={"target": "component or system to optimize", "constraint": "optional constraint"},
        description="Propose optimizations for system performance or architecture",
    ),
]
_handled_intents = {"engineering_analyze", "engineering_optimize"}
```

**`__init__`:**
```python
def __init__(self, **kwargs: Any) -> None:
    kwargs.setdefault("pool", "engineering_officer")
    super().__init__(**kwargs)
    self._runtime = kwargs.get("runtime")
```

**No `perceive()` or `act()` overrides.**

**Crew profile** — `config/standing_orders/crew_profiles/engineering_officer.yaml`:
```yaml
display_name: "Engineering Officer"
callsign: "LaForge"
department: "engineering"
role: "chief"
personality:
  openness: 0.8           # Innovative, creative problem-solver
  conscientiousness: 0.8   # Methodical and thorough
  extraversion: 0.6        # Collaborative, explains well
  agreeableness: 0.7       # Team-oriented, supportive
  neuroticism: 0.2         # Calm under pressure, optimistic
```

### Part 4: Register New Agents in Runtime

In `runtime.py`:

**1. Add imports** at the top with the other cognitive agent imports:
```python
from probos.cognitive.security_officer import SecurityAgent
from probos.cognitive.operations_officer import OperationsAgent
from probos.cognitive.engineering_officer import EngineeringAgent
```

**2. Register templates** (in the template registration section, after the Science team block):
```python
# Security team (AD-398)
self.spawner.register_template("security_officer", SecurityAgent)
# Operations team (AD-398)
self.spawner.register_template("operations_officer", OperationsAgent)
# Engineering team (AD-398)
self.spawner.register_template("engineering_officer", EngineeringAgent)
```

**3. Update pool group definitions:**

Security pool group — replace `red_team` with `security_officer`:
```python
self.pool_groups.register(PoolGroup(
    name="security",
    display_name="Security",
    pool_names={"security_officer"},
    exclude_from_scaler=True,
))
```

Engineering pool group — add `engineering_officer`:
```python
self.pool_groups.register(PoolGroup(
    name="engineering",
    display_name="Engineering",
    pool_names={"builder", "engineering_officer"},
    exclude_from_scaler=True,
))
```

Add new Operations pool group:
```python
# Operations team (AD-398)
self.pool_groups.register(PoolGroup(
    name="operations",
    display_name="Operations",
    pool_names={"operations_officer"},
    exclude_from_scaler=True,
))
```

**4. Spawn the new agents.** Follow the existing spawn pattern used for other cognitive agents. Look at how scout, architect, builder, and the medical agents are spawned. The new agents need:
- Pool creation with `min_agents=1, max_agents=1`
- Agent spawning into the pool
- IntentBus subscription

Search for existing spawn patterns (e.g., `_spawn_science_team` or similar) and follow the same pattern for the new agents.

### Part 5: Update Existing Department Role Hierarchy

With LaForge as Engineering Chief, update Scotty/Builder's crew profile to `role: "officer"` (he was previously `chief`):

In `config/standing_orders/crew_profiles/builder.yaml`, change:
```yaml
role: "officer"
```

LaForge is the department chief; Scotty is the senior officer who executes builds.

## Testing Requirements

### Unit Tests

1. **direct_message passthrough** — For each agent with an `act()` override (Scout, Builder, Architect, Surgeon, Counselor), test that when `decision` contains `intent: "direct_message"`, the `act()` method returns `{"success": True, "result": llm_output}` without processing domain logic.

2. **Crew profile removal** — Test that `CallsignRegistry.load_from_profiles()` no longer finds callsigns for Data, Chapel, old Worf, old O'Brien, Dax.

3. **New crew profiles** — Test that `CallsignRegistry` resolves "Worf" → `security_officer`, "O'Brien" → `operations_officer`, "LaForge" → `engineering_officer`.

4. **New agents instantiate** — Test that `SecurityAgent`, `OperationsAgent`, `EngineeringAgent` can be constructed with mock LLM client and have correct `agent_type`, `instructions`, `intent_descriptors`, `_handled_intents`.

5. **New agents handle direct_message** — Test the full `handle_intent()` path with a `direct_message` IntentMessage targeted to each new agent. Verify the LLM is called and the response is returned.

6. **Pool group membership** — Test that `red_team`, `medical_vitals`, `system_qa` are in the `core` pool group, and `security_officer`, `operations_officer`, `engineering_officer` are in their respective department pool groups.

7. **Intent propagation** — Test that the `intent` field is present in the `decision` dict after `decide()` in `CognitiveAgent.handle_intent()`.

### Regression

Run the full test suite. Key areas to watch:
- `tests/test_callsign_registry.py` — callsign count will change (profiles removed + added)
- `tests/test_cognitive_agent.py` — cognitive lifecycle tests
- Any tests referencing the old callsigns (Data, Chapel, old Worf/O'Brien)
- Medical, security, and engineering pool/spawn tests

## Files Modified

| File | Change |
|------|--------|
| `src/probos/cognitive/cognitive_agent.py` | Add `decision["intent"] = intent.intent` in `handle_intent()` |
| `src/probos/cognitive/scout.py` | Add direct_message guard in `act()` |
| `src/probos/cognitive/builder.py` | Add direct_message guard in `act()` |
| `src/probos/cognitive/architect.py` | Add direct_message guard in `act()` |
| `src/probos/cognitive/counselor.py` | Add direct_message guard in `act()` |
| `src/probos/agents/medical/surgeon.py` | Add direct_message guard in `act()` |
| `src/probos/cognitive/security_officer.py` | **NEW** — SecurityAgent |
| `src/probos/cognitive/operations_officer.py` | **NEW** — OperationsAgent |
| `src/probos/cognitive/engineering_officer.py` | **NEW** — EngineeringAgent |
| `src/probos/runtime.py` | Import new agents, register templates, update pool groups, spawn agents |
| `config/standing_orders/crew_profiles/security_officer.yaml` | **NEW** |
| `config/standing_orders/crew_profiles/operations_officer.yaml` | **NEW** |
| `config/standing_orders/crew_profiles/engineering_officer.yaml` | **NEW** |
| `config/standing_orders/crew_profiles/builder.yaml` | Change role from "chief" to "officer" |
| `config/standing_orders/crew_profiles/introspect.yaml` | **DELETE** |
| `config/standing_orders/crew_profiles/vitals_monitor.yaml` | **DELETE** |
| `config/standing_orders/crew_profiles/red_team.yaml` | **DELETE** |
| `config/standing_orders/crew_profiles/system_qa.yaml` | **DELETE** |
| `config/standing_orders/crew_profiles/emergent_detector.yaml` | **DELETE** (orphaned) |

## Commit Message

```
Add three-tier agent architecture and fix 1:1 crew conversations (AD-398)

Establish clean separation: Core Infrastructure (ship systems), Utility
(bundled tools), and Crew (sovereign individuals with callsigns).
Reclassify non-cognitive agents as infrastructure, add direct_message
guard to cognitive act() overrides, and create SecurityAgent (Worf),
OperationsAgent (O'Brien), and EngineeringAgent (LaForge) as new
cognitive crew members.
```
