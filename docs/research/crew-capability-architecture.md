# Crew Capability Architecture

**Date:** 2026-04-04
**Author:** Architect (Sean Galliher)
**Status:** Design Document — connects existing ADs into a unified personnel management model
**Triggered by:** Gap analysis of how ProbOS defines agent Role, Skills, Tools, Qualifications, Duties, and Privileges

---

## 1. Problem Statement

ProbOS has built substantial infrastructure for agent identity, skills, memory, trust, and procedures — but these systems are **designed in parallel, not connected end-to-end**. The result is that we cannot answer the fundamental workforce management question:

> **"What can this agent do, and why?"**

A Navy personnel officer can look up any sailor and see: Rating (job), NECs (qualifications), PQS status (certifications), assigned equipment (tools), current watch station (duty), service record (history), and rank (authority). ProbOS has analogs for all of these, but no unified model connecting them.

### The Fragmentation

| Capability Aspect | ProbOS Component | AD | Location | Connected To |
|---|---|---|---|---|
| Role definition | Standing Orders + Ontology Post | AD-339/429a | Config + YAML | ✅ compose_instructions() |
| Skill tracking | Skill Framework | AD-428 | skill_framework.py | ❌ Not wired to tool access |
| Qualification testing | Qualification Battery | AD-566 | qualification.py | ❌ Not wired to skill proficiency |
| Tool access | Tool capabilities (schema only) | AD-423 | resources.yaml | ❌ No runtime code |
| Duty assignment | Pool + Intent Bus | Core | agent_onboarding.py | ✅ Functional but static |
| Authority/Privileges | Earned Agency | AD-357 | earned_agency.py | ✅ Gates actions |
| Learned abilities | Executable Skills + Cognitive JIT | AD-531-539 | procedures.py + types.py | ✅ Procedural replay works |
| Personnel records | Episodic Memory + Ship's Records | AD-434/441 | episodic.py + identity.py | ✅ Separate systems |
| Crew roster | Agent Fleet startup | Core | agent_fleet.py | ❌ Hardcoded, no manifest |

### What "Connected" Looks Like

When a new crew member is onboarded, the system should be able to:

1. Look up their **Post** (organization.yaml) → determines department, chain of command, authority
2. Load their **Role Template** (skills.yaml) → determines required skills and proficiency targets
3. Assign **Tool Access** (resources.yaml) → determines which tools they can use, gated by rank
4. Check **Qualification Status** (qualification.py) → determines if they've demonstrated competency
5. Load **Procedures** (procedure_store.py) → determines what they can do without LLM reasoning
6. Apply **Standing Orders** (standing_orders/) → determines behavioral guidance
7. Set **Earned Agency** (earned_agency.py) → determines action space based on trust

Currently, steps 1, 6, and 7 work. Steps 2-5 exist as independent systems with no connecting fabric.

---

## 2. The Navy Model

The U.S. Navy's personnel management system provides the organizing metaphor. ProbOS already uses naval terminology — this document formalizes the mapping.

### Navy Personnel Management

```
┌─────────────────────────────────────────────────────────────┐
│  SAILOR'S SERVICE RECORD                                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  RATING (Job Category)                                      │
│  ├─ e.g., MM (Machinist's Mate), ET (Electronics Tech)     │
│  ├─ Determines: training pipeline, career path, billets    │
│  └─ ProbOS: Agent Type + Ontology Post                     │
│                                                             │
│  NECs (Navy Enlisted Classifications)                       │
│  ├─ Specific skill qualifications beyond rating             │
│  ├─ Earned through: schools, OJT, demonstrated competency  │
│  ├─ e.g., NEC 4234 (Nuclear Propulsion Plant Operator)     │
│  └─ ProbOS: Skill Framework (AD-428) proficiency records   │
│                                                             │
│  PQS (Personnel Qualification Standards)                    │
│  ├─ Formal competency certification process                 │
│  ├─ Study → Practical Demo → Oral Board → Sign-off         │
│  ├─ Required before standing a watch                        │
│  └─ ProbOS: Qualification Battery (AD-566)                 │
│                                                             │
│  AUTHORIZED EQUIPMENT                                       │
│  ├─ Ship's equipment the sailor is qualified to operate     │
│  ├─ Gated by: NEC + PQS + rank + commanding officer        │
│  ├─ e.g., can operate the lathe, cannot operate the reactor │
│  └─ ProbOS: Tool Registry (AD-423) — NOT YET BUILT         │
│                                                             │
│  WATCH STATION                                              │
│  ├─ Current duty assignment on the watch bill               │
│  ├─ Requires: PQS qualification for that station            │
│  ├─ Rotation: 3-section, port/starboard, etc.              │
│  └─ ProbOS: Pool + Intent Bus + Watch Manager              │
│                                                             │
│  PMS CARDS (Planned Maintenance System)                     │
│  ├─ Procedural checklists for maintenance tasks             │
│  ├─ Define: steps, tools required, qualifications needed    │
│  ├─ Tracked: completion, periodicity, deferred items        │
│  └─ ProbOS: Cognitive JIT Procedures (AD-531-539)          │
│                                                             │
│  STANDING ORDERS                                            │
│  ├─ Rules of engagement for the watch                       │
│  ├─ Hierarchy: OPNAV → fleet → ship → department → watch   │
│  └─ ProbOS: Standing Orders (AD-339) 4-tier hierarchy      │
│                                                             │
│  RANK / RATE                                                │
│  ├─ Authority level determining scope of action             │
│  ├─ Earned through: time-in-rate + PQS + eval + board      │
│  └─ ProbOS: Earned Agency (AD-357) trust-based rank        │
│                                                             │
│  SERVICE RECORD                                             │
│  ├─ Complete career history                                 │
│  ├─ Evaluations, awards, qualifications, assignments        │
│  └─ ProbOS: Episodic Memory + Ship's Records + DIDs        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Key Navy Insight: Tools ≠ Personnel

In the Navy, a wrench has no personality. A Machinist's Mate is **qualified** to operate a lathe (NEC/PQS), and the lathe is **ship's equipment** (inventoried, maintained, tracked). The MM's qualification certifies they can use the tool safely. Different MMs may have different tool qualifications.

ProbOS's "everything is an agent" model conflated the sailor and the lathe. `FileReaderAgent` is both "the tool" and "the agent." The Three-Tier Architecture (AD-398) acknowledged this by classifying agents as infrastructure/utility/crew, and Asset Tags (AD-441c) formalized the identity split ("Even microwaves get serial numbers. But a serial number is not a birth certificate."). The next step is making infrastructure/utility agents into **tools that crew agents can use**.

---

## 3. The Hybrid Architecture

### Design Decision: Keep Both, Connect Them

The "everything is an agent" model provides genuine architectural advantages at the infrastructure layer:

1. **Observability** — every operation flows through the intent bus, auditable and interceptable
2. **Distributability** — in federation, any agent could be on a different node
3. **Evolvability** — infrastructure agents can get smarter over time
4. **Uniform protocol** — `IntentMessage`/`IntentResult` for everything

These advantages are **real and worth preserving**. The solution is not to replace agents-as-tools, but to add a **tool binding layer** on top that gives crew agents composable capabilities while infrastructure agents continue doing the actual work.

### Three Capability Types for Crew Agents

```
┌─────────────────────────────────────────────────────────────┐
│  CREW MEMBER CAPABILITY PROFILE                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. ASSIGNED TOOLS (ship's equipment)                       │
│  ├─ Defined by: Role Template (ontology) + Rank            │
│  ├─ Gated by: Trust tier (Earned Agency) + Qualification   │
│  ├─ Execute via: Infrastructure Agents (intent bus)         │
│  ├─ Registered in: Tool Registry (AD-423)                  │
│  └─ Examples: read_file, search_codebase, ward_room_post   │
│                                                             │
│  2. LEARNED SKILLS (Executable Skills)                      │
│  ├─ Acquired through: Cognitive JIT (experience)           │
│  ├─ Proficiency tracked: Skill Framework (Dreyfus levels)  │
│  ├─ Execute: directly on agent (no bus, no LLM at L4+)     │
│  ├─ Trust-gated: compilation level by rank                 │
│  └─ Examples: agent-specific procedures, optimized flows   │
│                                                             │
│  3. COGNITIVE CAPABILITIES (LLM-powered reasoning)          │
│  ├─ Defined by: Standing Orders + Instructions (system     │
│  │   prompt) — what the agent KNOWS HOW TO REASON ABOUT    │
│  ├─ Not mechanically gated — shaped by prompt engineering   │
│  ├─ Execute via: LLM call in decide()                      │
│  └─ Examples: design_feature, diagnose_system,             │
│     security_assess — things requiring judgment             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### How They Interact

```
Intent arrives at agent
        │
        ▼
   ┌─────────┐
   │ Skill?  │──yes──► Executable Skill handler (no LLM, no bus)
   └────┬────┘         Learned through Cognitive JIT
        │ no
        ▼
   ┌─────────┐
   │  Tool?  │──yes──► Tool binding → Infrastructure Agent (via bus)
   └────┬────┘         Assigned by role, gated by rank
        │ no
        ▼
   ┌─────────┐
   │ Handled │──yes──► Full cognitive lifecycle (perceive/decide/act)
   │ Intent? │         LLM-powered reasoning per Standing Orders
   └────┬────┘
        │ no
        ▼
    Decline (return None)
```

---

## 4. Tool Type Taxonomy

A "tool" in ProbOS is any capability a crew agent can invoke. The delivery mechanism is irrelevant — what matters is: does the agent have access, and can it execute? AD-422 defines 8 categories; this section maps those to the runtime abstraction the Tool Registry (AD-423) must support.

### Tool Types

| Type | Description | Execution Model | Examples |
|---|---|---|---|
| **Onboard Utility Agent** | ProbOS agents that provide capabilities as tools. No sovereign identity. | Intent bus → agent.handle_intent() | BuilderAgent, CodeReviewerAgent, SkillEngine |
| **Infrastructure Service** | Ship's Computer services. Shared substrate, always available. | Direct function call (same process) | CodebaseIndex, EpisodicMemory, TrustNetwork |
| **MCP Server** | Standardized JSON-RPC protocol tools. Hot-pluggable. | stdio/HTTP JSON-RPC per MCP spec | Filesystem MCP, Postgres MCP, Serena (LSP) |
| **Remote API / LLM Gateway** | Cloud services over HTTP/SDK. Token-metered. | HTTP request/response or SDK call | Copilot SDK, GitHub API, Anthropic API |
| **Computer Use** | Desktop/GUI automation. Highest risk category. | Vision model + input simulation | PyAutoGUI, Anthropic Computer Use |
| **Browser Automation** | Web interaction via DOM or accessibility tree. | Playwright/Puppeteer + browser DevTools | Page navigation, form filling, screen reading |
| **Communication Channel** | Outbound messaging to humans/external systems. | Protocol-specific adapter | Discord, Slack, Email, Webhooks |
| **Federation Service** | Capabilities sourced from other ProbOS ships. | Federation gossip protocol | Cross-ship queries, fleet-wide Hebbian |
| **Deterministic Function** | Pure code procedures with no LLM. Executable Skills from Cognitive JIT. | Direct function call (handler invocation) | Learned procedures at L4+, compiled skills |

### Key Design Insight: Adapter Uniformity

From the crew member's perspective, all tool types look identical. The crew member says "search the codebase" — whether that invokes CodebaseIndex directly, an MCP server, or a federated query on another ship is an adapter implementation detail behind the `Tool` protocol (AD-423a).

The `AgenticToolAdapter` (AD-543/unified-tool-layer.md) is a specialization for tools that run their own agentic loop (e.g., BuilderAgent, Copilot SDK). A single `ToolRegistry` registers both simple tools and agentic tools — the difference is execution duration and token cost, not protocol.

### Deterministic Functions (Executable Skills as Tools)

This is the OpenClaw pattern. Cognitive JIT (AD-531-539) extracts procedures from LLM-guided experience and compiles them into deterministic handlers. At Dreyfus Level 4+ (Autonomous), these execute with zero tokens — no LLM call, pure code replay.

These are both **skills** (tracked in Skill Framework for proficiency) and **tools** (registered in Tool Registry for access). The distinction:
- **As a skill:** Proficiency level, how it was learned, when it was last used, Ebbinghaus decay
- **As a tool:** Can it be invoked right now? Does this agent have permission? What inputs/outputs?

This dual registration is how the capability profile stays unified — one system tracks competency, another tracks access.

---

## 5. Task → Skill → Tool Execution Flow

### The Question

> "What happens when an agent receives a task that requires a skill, and that skill requires a tool?"

This is the core execution flow that connects all the capability systems. Three scenarios:

### Scenario 1: LLM Reasoning Needs Tool Mid-Thought

The agent is doing cognitive work (perceive/decide/act) and needs to invoke a tool as part of its reasoning.

```
Intent: "analyze module X for performance issues"
Agent: LaForge (Engineering Chief)

1. handle_intent() → no matching executable skill
2. decide() invoked → LLM begins reasoning
3. LLM identifies need: "I need to read the module source"
4. Tool call: read_file(path="src/probos/module_x.py")
   ├─ Check: Does LaForge have read_file tool assigned? → Yes (role: chief_engineer)
   ├─ Check: Does LaForge's rank permit this? → Yes (Lieutenant+ for filesystem read)
   └─ Execute: FileReaderAgent via intent bus → returns file content
5. LLM continues reasoning with file content
6. LLM identifies need: "I need to check performance metrics"
7. Tool call: query_metrics(agent_id="module_x")
   ├─ Check: tool assigned? → Yes
   ├─ Check: rank permits? → Yes
   └─ Execute: VitalsMonitor via intent bus → returns metrics
8. LLM completes analysis → act() returns IntentResult
```

**This is the AD-543 (Native SWE Harness) model.** The `AgenticLoop` manages the interleaved text + tool_use + tool_result conversation. `ToolExecutor` handles permission checks and execution dispatch. Each tool call goes through the Tool Registry for authorization.

### Scenario 2: Learned Procedure Has Steps Requiring Tools

The agent has a Cognitive JIT procedure for this task, compiled to Level 3+ (Validated). The procedure steps reference tools.

```
Intent: "run standard health check on module X"
Agent: Chapel (Chief Medical)

1. handle_intent() → matches executable skill "standard_health_check"
2. Skill handler invoked (no LLM call)
3. ProcedureStep 1: collect_vitals
   ├─ required_tools: [vitals_query]          ← NEW FIELD on ProcedureStep
   ├─ tool_context.has_tool("vitals_query")   ← NEW: scoped tool access
   └─ Execute: tool_context.invoke("vitals_query", params={...})
4. ProcedureStep 2: compare_baselines
   ├─ required_tools: [knowledge_query]
   └─ Execute: tool_context.invoke("knowledge_query", params={...})
5. ProcedureStep 3: generate_report
   ├─ required_tools: []  (pure computation)
   └─ Execute: handler logic only
6. Return result (zero LLM tokens consumed)
```

**What needs to be added:**
- `ProcedureStep.required_tools: list[str]` — declares which tools each step needs
- `ToolContext` — a scoped, permission-filtered view of the Tool Registry passed to skill handlers
- `SkillHandler(intent, tool_context)` — skill handlers receive tool access as a parameter

### Scenario 3: Skill Handler Can't Complete Without Tool — Fallback

The procedure exists but a required tool is unavailable (permission denied, tool offline, federation timeout).

```
Intent: "search for security vulnerabilities in module X"
Agent: Worf (Chief Security)

1. handle_intent() → matches executable skill "vulnerability_scan"
2. Skill handler invoked
3. ProcedureStep 1: read_module_source
   ├─ required_tools: [read_file]
   └─ Execute: tool_context.invoke("read_file", params={...}) → SUCCESS
4. ProcedureStep 2: run_static_analysis
   ├─ required_tools: [static_analyzer]
   └─ Execute: tool_context.invoke("static_analyzer") → TOOL UNAVAILABLE
5. FALLBACK CASCADE:
   ├─ Level 1: Retry with alternative tool (if registered)
   ├─ Level 2: Degrade to LLM-guided reasoning (re-enter decide() for this step)
   └─ Level 3: Escalate via chain of command (report inability, request assistance)
6. Worf escalates step 2 to LaForge who has static_analyzer access
```

### The Fallback Cascade

```
Executable Skill (zero tokens)
        │
        │ tool unavailable / step failure
        ▼
LLM-Guided (decide() with tool context, costs tokens)
        │
        │ LLM can't resolve / permission denied
        ▼
Chain of Command Escalation (request assistance from peer/superior)
        │
        │ no one can help / critical failure
        ▼
Report to Bridge (Captain/XO informed of capability gap)
```

This cascade means agents degrade gracefully rather than failing hard. A missing tool doesn't halt the agent — it triggers the same chain of command that a human crew would use: try yourself, ask for help, escalate to command.

### ToolContext: The Permission-Filtered View

`ToolContext` is NOT the full Tool Registry. It is a **scoped view** created for each agent based on:

1. **Role template** — which tools the agent's post is assigned (from resources.yaml/skills.yaml)
2. **Rank** — Earned Agency level determines read/write/execute permissions per tool
3. **Qualification** — PQS completion may unlock additional tool access (AD-566f bridge)
4. **Department** — some tools are department-scoped (e.g., security tools only for Security dept)
5. **Captain overrides** — explicit grants/denials from the Captain

```python
# Conceptual API (AD-423a design target)
class ToolContext:
    """Scoped, permission-filtered tool access for a specific agent."""

    def available_tools(self) -> list[ToolDescriptor]: ...
    def has_tool(self, tool_id: str) -> bool: ...
    async def invoke(self, tool_id: str, **params) -> ToolResult: ...
    # invoke() checks permissions internally — no way to bypass
```

The ToolContext is constructed at onboarding (`wire_agent()`) and updated when rank changes, qualifications are earned, or Captain overrides are applied. Crew agents never see the raw Tool Registry — they see their ToolContext.

---

## 6. The Connection Map

### What's Built (solid lines) vs What's Needed (dashed lines)

```
                    STANDING ORDERS (AD-339) ✅
                    ┌─────────────────────┐
                    │  Federation → Ship  │
                    │  → Dept → Agent     │
                    │  Behavioral guidance │
                    └─────────┬───────────┘
                              │ shapes reasoning
                              ▼
┌──────────────┐    ┌─────────────────────┐    ┌──────────────────┐
│  VESSEL      │    │  CREW MEMBER        │    │  EARNED AGENCY   │
│  ONTOLOGY    │───►│                     │◄───│  (AD-357) ✅     │
│  (AD-429) ✅ │    │  Agent Type + Post  │    │  Trust → Rank    │
│              │    │  Department         │    │  Rank → Actions  │
│  8 domains   │    │  Chain of Command   │    │  Gates tool use  │
└──────┬───────┘    └────────┬────────────┘    └──────────────────┘
       │                     │
       │ defines             │ has
       ▼                     ▼
┌──────────────┐    ┌─────────────────────┐    ┌──────────────────┐
│  ROLE        │- - │  SKILL PROFILE      │    │  QUALIFICATION   │
│  TEMPLATE    │    │  (AD-428) ✅        │◄ - │  BATTERY         │
│  skills.yaml │    │                     │    │  (AD-566) 🔧     │
│  ✅ schema   │    │  PCCs + Role Skills  │    │  Tests → scores  │
│  ❌ not wired│    │  + Acquired Skills   │    │  Baseline + drift│
│  at onboard  │    │  Proficiency levels  │    │  ❌ not wired to │
└──────┬───────┘    └────────┬────────────┘    │  skill proficiency│
       │                     │                 └──────────────────┘
       │ requires            │ qualifies for
       ▼                     ▼
┌──────────────┐    ┌─────────────────────┐    ┌──────────────────┐
│  TOOL        │- - │  TOOL ACCESS        │    │  COGNITIVE JIT   │
│  REGISTRY    │    │  (TOOL BINDINGS)    │    │  (AD-531-539) ✅ │
│  (AD-423) ❌ │    │                     │    │                  │
│  Designed    │    │  Which tools this   │    │  Procedures →    │
│  Not built   │    │  agent can invoke   │    │  Executable      │
│              │    │  Gated by rank +    │    │  Skills          │
│              │    │  qualification      │    │  Zero-token      │
└──────┬───────┘    └────────┬────────────┘    │  replay at L4+   │
       │                     │                 └──────────────────┘
       │ provides            │ executes via
       ▼                     ▼
┌──────────────┐    ┌─────────────────────┐
│  INFRA       │    │  INTENT BUS         │
│  AGENTS      │◄───│  (Core) ✅          │
│  (AD-398) ✅ │    │                     │
│              │    │  Observable,         │
│  FileReader  │    │  distributable,     │
│  FileWriter  │    │  auditable          │
│  Shell       │    │                     │
│  HttpFetch   │    │                     │
│  CodebaseIdx │    │                     │
└──────────────┘    └─────────────────────┘
```

**Legend:** ✅ Built | 🔧 Building | ❌ Not built | `- -` Connection needed

### The Six Missing Connections

| # | Connection | From → To | What It Does | Enabling AD |
|---|---|---|---|---|
| C1 | Role → Tool Assignment | skills.yaml role_template → Tool Registry | At onboarding, assign tools to agent based on role | AD-423 + new wiring |
| C2 | Qualification → Skill Proficiency | AD-566 test results → AD-428 AgentSkillService | Passing a qualification test updates skill proficiency | AD-566f (new) |
| C3 | Qualification → Tool Authorization | AD-566 completion → Tool Registry permissions | Completing PQS unlocks tool access | AD-423 + AD-566f |
| C4 | Skill Proficiency → Earned Agency | AD-428 proficiency levels → promotion requirements | Qualification paths gate rank advancement | AD-566/428 bridge (exists in AD-539 gap predictor, needs formalization) |
| C5 | Tool Registry → Onboarding | AD-423 → agent_onboarding.py | Wire tool bindings during `wire_agent()` | AD-423 |
| C6 | Crew Manifest → Unified Query | All systems → single API | "What can this agent do?" query | AD-513 |

---

## 7. The AD Landscape

### Built ADs (Foundation Layer)

| AD | Name | What It Provides | Status |
|---|---|---|---|
| AD-339 | Standing Orders | 4-tier behavioral guidance hierarchy | ✅ Complete |
| AD-357 | Earned Agency | Trust-based rank gating action space | ✅ Complete |
| AD-398 | Three-Tier Architecture | Crew/Utility/Infrastructure classification | ✅ Complete |
| AD-422 | Tool Taxonomy | 8-category tool classification + design doc | ✅ Complete |
| AD-428 | Skill Framework | Competency tracking, proficiency, qualification paths | ✅ Complete |
| AD-429a-e | Vessel Ontology | 8-domain formal model (org, crew, skills, resources, etc.) | ✅ Complete |
| AD-441a-c | Persistent Identity | DIDs, birth certificates, asset tags | ✅ Complete |
| AD-496-498 | Workforce Scheduling | Work items, bookings, calendars, scrumban | ✅ Complete |
| AD-531-539 | Cognitive JIT | Procedure extraction, replay, gap detection, qualification triggering | ✅ Complete |

### Building ADs (In Progress)

| AD | Name | What It Provides | Status |
|---|---|---|---|
| AD-566a | Qualification Harness | Test protocol, store, harness engine | ✅ Complete |
| AD-566b | Tier 1 Baseline Tests | Personality, memory, confabulation probes | 🔧 Builder |
| AD-566c | Drift Detection Pipeline | Scheduled testing, statistical thresholds, alerts | Planned |
| AD-566d | Tier 2 Domain Tests | Role-specific competency tests | Planned |
| AD-566e | Tier 3 Collective Tests | Crew-wide coordination measurement | Planned |

### Unbuilt ADs (Connection Layer)

| AD | Name | What It Provides | Gap It Fills | Dependencies |
|---|---|---|---|---|
| AD-423 | Tool Registry | Runtime tool catalog, permissions, scoping, discovery | C1, C3, C5 | AD-422 (done), AD-398 (done) |
| AD-483 | Tool Layer — Instruments | `Tool` base class, `ToolRegistry` class, tool trust | C1 (programming model) | AD-423 (scope overlap — reconcile) |
| AD-438 | Ontology-Based Task Routing | Directed assignment using role + skills + tools | Routing optimization | AD-429 (done), AD-428 (done), AD-423 |
| AD-513 | Crew Manifest | Unified queryable crew roster | C6 | AD-429 (done), AD-441 (done), AD-357 (done) |
| AD-543-549 | Native SWE Harness | ToolCall protocol, agentic loop | Tool execution model | AD-423 |

### New ADs Needed

| AD | Name | What It Provides | Gap It Fills |
|---|---|---|---|
| AD-566f (new) | Qualification → Skill Bridge | Test results update Skill Framework proficiency | C2 |
| AD-423+ (new scope) | Role-Based Tool Assignment | At onboarding, assign tools from role template | C1, C5 |
| AD-423+ (new scope) | Qualification-Gated Tool Access | PQS completion unlocks tool permissions | C3 |

---

## 8. AD-423 and AD-483: Reconciliation

AD-423 and AD-483 both define "Tool Registry" but from different angles:

| Aspect | AD-423 | AD-483 |
|---|---|---|
| Focus | Operational management | Programming abstraction |
| Scope | Permissions, scoping, lifecycle, discovery | `Tool` base class, `ToolRegistry` class, trust |
| Designed in | tool-taxonomy.md (detailed) | roadmap feature spec |
| Key features | CRUD+O permissions, dept scoping, Captain overrides | Tool base class, Beta-distribution trust, MCP compat |
| Overlapping | ToolRegistry class, tool registration | ToolRegistry class, tool registration |

**Recommendation:** Merge into a single AD sequence (AD-423a/b/c):

- **AD-423a: Tool Foundation** — `Tool` protocol + `ToolRegistry` class + registration schema (absorbs AD-483's programming model)
- **AD-423b: Tool Permissions & Scoping** — CRUD+O permissions, department scoping, Earned Agency gates, Captain overrides (AD-423's operational model)
- **AD-423c: Role-Based Tool Assignment** — Onboarding wiring, role template → tool bindings, qualification gates (the new connection layer)

This gives us the `Tool` abstraction, the permission model, and the onboarding wiring in a clean build sequence.

---

## 9. Build Order

The build order respects dependencies and maximizes value at each step:

### Phase A: Complete Testing Infrastructure (current)

```
AD-566a ✅ → AD-566b 🔧 → AD-566c → AD-566d → AD-566e
```

Establishes the measurement framework before making changes. All testing infrastructure in place.

### Phase B: Tool Foundation

```
AD-423a (Tool protocol + ToolRegistry)
  → AD-423b (Permissions + scoping + Earned Agency gates)
    → AD-423c (Role-based assignment at onboarding)
```

The keystone. Gives crew agents composable tool access. Infrastructure agents become "ship's equipment" that crew agents can use through tool bindings.

### Phase C: Connect the Dots

```
AD-566f (Qualification → Skill Bridge)
  → AD-513 (Crew Manifest — unified query)
    → AD-438 (Ontology-Based Task Routing)
```

Closes the remaining connections. Qualification results flow into skill proficiency. Crew Manifest provides the "what can this agent do?" query. Task routing uses the full capability profile for intelligent assignment.

### Phase D: Memory Architecture (existing plan)

```
AD-567a → AD-567b (absorbs AD-462) → AD-567c → AD-567d
  → AD-566 re-run (measure impact)
    → AD-567e → AD-567f → AD-567g
```

Memory improvements, measured against the baselines established in Phase A.

### Phase E: Advanced Integration

```
AD-543-549 (Native SWE Harness — ToolCall protocol + agentic loop)
AD-439 (Emergent Leadership Detection)
AD-440 (Chain of Command Delegation)
```

Higher-order capabilities that build on the connected fabric.

---

## 10. The Complete Crew Member Capability Profile

When all phases are complete, querying an agent's capability profile returns:

```yaml
agent_id: "did:probos:ship-001:agent-meridian-uuid"
callsign: "Meridian"
agent_type: architect
post: first_officer
department: science
rank: commander
trust_score: 0.82
lifecycle_state: active

# Character (Personality)
personality:
  openness: 0.9
  conscientiousness: 0.8
  extraversion: 0.5
  agreeableness: 0.7
  neuroticism: 0.2
  drift_from_seed: 0.08  # Euclidean distance

# Standing Orders (Behavioral Guidance)
standing_orders:
  federation: "config/standing_orders/federation.md"
  ship: "config/standing_orders/ship.md"
  department: "config/standing_orders/science.md"
  personal: "config/standing_orders/architect.md"

# Cognitive Capabilities (LLM-powered, from _handled_intents)
handled_intents:
  - name: design_feature
    tier: deep
    description: "Analyze codebase and produce architectural proposals"

# Assigned Tools (from role template + rank + qualification)
tools:
  - tool_id: codebase_query
    provider: codebase_index
    permission: ORW
    qualified: true
    qualification_date: "2026-04-01"
  - tool_id: ward_room_post
    provider: ward_room
    permission: ORW
    gated_by: earned_agency
    qualified: true
  - tool_id: ward_room_endorse
    provider: ward_room
    permission: ORW
    gated_by: lieutenant_plus
    qualified: true
  - tool_id: episodic_recall
    provider: episodic_memory
    permission: OR
    scope: own_shard_only
    qualified: true
  - tool_id: knowledge_query
    provider: knowledge_store
    permission: OR
    qualified: true

# Learned Skills (from Cognitive JIT)
executable_skills:
  - name: codebase_knowledge
    origin: built_in
    compilation_level: 3
  # ... additional learned skills from experience

# Skill Proficiency (from Skill Framework)
skill_profile:
  pccs:
    - skill_id: chain_of_command
      proficiency: 5  # Advise
    - skill_id: communication
      proficiency: 5
    - skill_id: collaboration
      proficiency: 4  # Enable
  role_skills:
    - skill_id: architecture_review
      proficiency: 5
    - skill_id: pattern_recognition
      proficiency: 4
  acquired_skills: []

# Qualification Status (from AD-566)
qualifications:
  baseline_set: true
  latest_battery:
    bfi2_personality_probe: { score: 0.87, passed: true }
    episodic_recall_accuracy: { score: 0.92, passed: true }
    confabulation_resistance: { score: 0.95, passed: true }
  qualification_path: lieutenant_to_commander
  path_progress: "4/5 requirements met"

# Procedures (from Cognitive JIT)
procedures:
  total: 12
  by_level:
    novice: 0
    guided: 3
    validated: 5
    autonomous: 3
    expert: 1

# Duty Assignment
current_duty:
  pool: architect
  watch: alpha
  intent_subscriptions: ["design_feature"]

# Service Record
service_record:
  birth_date: "2026-03-15T08:00:00Z"
  total_episodes: 847
  success_rate: 0.91
  trust_trajectory: improving
  promotions: ["ensign→lieutenant (2026-03-18)", "lieutenant→commander (2026-03-25)"]
```

This is the **Crew Manifest** (AD-513) query result — the unified view that connects every system.

---

## 11. Relationship to Commercial Systems

### Agent Capital Management (ACM)

ACM is the commercial financial backbone that builds on the OSS capability profile:

| OSS (Crew Capability Profile) | Commercial (ACM) |
|---|---|
| What the agent CAN do | What the agent COSTS |
| Skill proficiency | Billable skill rates |
| Tool access | Tool licensing costs |
| Qualification status | Certification revenue |
| Duty assignment | Project assignment |
| Service record | Performance evaluation |

**Boundary rule:** "How it works" → OSS. "How it makes money" → Commercial. The capability profile is OSS. Billing, scheduling optimization, capacity planning, and customer-facing management are commercial.

### Agent Services Automation (ASA)

ASA (AD-C-010 through AD-C-015) is the commercial execution engine. It consumes the capability profile to:
- Match agents to work items based on skills + tools + availability
- Schedule agents across ProbOS instances (workforce mobility)
- Track billable time via BookingJournals
- Optimize resource allocation

The OSS capability profile is the **input**. ASA is the **consumer**.

---

## 12. Design Principles

1. **Tools are not personnel.** Infrastructure agents remain agents (for observability, distributability, evolvability). But crew agents get tool bindings — composable capabilities assigned by role.

2. **Qualification gates access.** Completing PQS (AD-566) updates skill proficiency (AD-428) which unlocks tool permissions (AD-423). No shortcuts. The pathway is: learn → test → qualify → access.

3. **Rank modulates scope.** Same tool, different permission level by rank. Ensigns get read-only. Commanders get full access. Seniors get cross-department access. Captain overrides everything.

4. **Skills are dual-path.** Assigned skills come from role templates (what you're EXPECTED to know). Learned skills come from Cognitive JIT (what you FIGURED OUT). Both tracked in the same Skill Framework.

5. **The ontology is the schema of truth.** All capability definitions live in YAML (organization.yaml, skills.yaml, resources.yaml). Runtime code reads from the ontology. Changes to capability structure are ontology changes, not code changes.

6. **Crew Manifest is the query surface.** One API call returns the complete capability profile. No agent should need to query 8 different services to understand itself. AD-513 assembles the view.

7. **Preserve Society of Mind at infrastructure layer.** The intent bus, infrastructure agents, and uniform protocol are genuine architectural advantages. The tool binding layer is additive, not a replacement.

8. **Tools are delivery-mechanism agnostic.** A tool can be an onboard utility agent, an MCP server, a remote API, a desktop automation session, a browser, a federation service, or a deterministic function. The crew member doesn't know or care. The `Tool` protocol and `ToolContext` abstract the delivery mechanism. What matters is: can I use it, and does it work?

9. **Graceful degradation through chain of command.** When a tool is unavailable or a skill can't complete, the agent doesn't fail — it falls back to LLM reasoning, then escalates via chain of command. The fallback cascade mirrors how a human crew handles missing equipment: try yourself, ask for help, report to command.

---

## 13. Prior Work Absorbed

| Source | What Was Absorbed |
|---|---|
| U.S. Navy personnel management (BUPERS/PQS/NEC/3-M) | Organizing metaphor for the entire architecture |
| AD-422 tool-taxonomy.md | 8-category tool classification, CRUD+O permissions, department scoping |
| AD-423 roadmap spec | Tool Registry design, registration schema, discovery flow |
| AD-483 unified-tool-layer.md | `AgenticToolAdapter` protocol, skill-to-tool binding concept |
| AD-429 Vessel Ontology (all 8 domains) | Formal model connecting org, crew, skills, resources |
| AD-428 Skill Framework | Three-category taxonomy, Dreyfus proficiency, role templates |
| AD-441c Asset Tags | Two-tier identity (birth certificates vs serial numbers) |
| AD-531-539 Cognitive JIT | Learned procedures as Executable Skills |
| AD-566a Qualification Harness | Test protocol, store, comparison API |
| MOISE+ (organizational specification) | Structural specification for agent organizations |
| O*NET / ESCO (competency taxonomies) | Skill taxonomy design (referenced in ontology research) |
| Fokoue et al. (2026) | Same LLM + different contexts = different analytical lenses |
| Ge et al. (2026, IRT) | Decomposing LLM ability from scaffold ability |
| Jeong (2026, MTI) | Behavioral profiling for drift detection |
| Claude Code / OpenClaw analysis | Plug-and-play skill/tool composition patterns |
| AD-422 tool-taxonomy.md (8 categories) | Tool type diversity — 8 categories from utility agents to federation services |
| AD-543 unified-tool-layer.md | `AgenticToolAdapter` protocol, ToolContext concept, adapter uniformity |
| AD-543 ToolCall protocol spec (roadmap) | `ToolCallRequest`/`ToolCallResult`/`ContentBlock` wire format, `ToolExecutor`, agentic loop |

---

## 14. Deferred Items and Future ADs

| Item | Proposed AD | Dependencies | Notes |
|---|---|---|---|
| AD-423/483 reconciliation into AD-423a/b/c | AD-423a/b/c | AD-422 (done) | Merge scope, build in sequence |
| Qualification → Skill proficiency bridge | AD-566f | AD-566a-e, AD-428 | New AD needed |
| Role-based tool assignment at onboarding | Part of AD-423c | AD-423a/b | Wiring in agent_onboarding.py |
| Qualification-gated tool authorization | Part of AD-423c | AD-423a/b, AD-566 | PQS completion → tool unlock |
| Crew Manifest unified query | AD-513 | AD-423, AD-429, AD-441 | Already planned |
| Ontology-Based Task Routing | AD-438 | AD-423, AD-428, AD-429 | Already planned |
| Emergent Leadership Detection | AD-439 | AD-429, Hebbian | Already planned |
| Chain of Command Delegation | AD-440 | AD-429 | Already planned |
| Business Process Execution | Future (post-Phase E) | AD-423, AD-496, AD-438 | Multi-step workflows using tools + skills + procedures |
| Personal Ontology (from research) | Future | AD-429 | Agent's self-model of own capabilities |
| ToolContext scoped view construction | Part of AD-423c | AD-423a/b | Permission-filtered tool view per agent, wired at onboarding |
| ProcedureStep.required_tools field | Part of AD-423c or AD-539+ | AD-423a, AD-531-539 | Declares which tools each procedure step needs |
| Fallback cascade (skill→LLM→escalate) | Part of AD-534b+ | AD-534 (done), AD-423 | Graceful degradation when tools unavailable |

All deferred items now have AD assignments.
