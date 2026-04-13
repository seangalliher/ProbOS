# Standard Operating Procedures: The Bill System

**AD-618 Research Document**
**Date:** 2026-04-12
**Author:** Architect (human) + Claude (research synthesis)
**Status:** Research Complete — Ready for Scoping

---

## 1. The Missing Middle Layer

ProbOS has two layers that govern agent behavior:

- **Standing Orders (T1):** Behavioral constraints and identity. Federation → Ship → Department → Agent. Loaded in system prompt every cycle. Defines *who the agent is* and *how they should behave*. Policy-level, not task-level.
- **Cognitive JIT (T3):** Learned procedures compiled from experience (AD-531–539). Bottom-up — agents acquire these through doing, not through instruction. Zero-token replay at L4+ proficiency. Individual agent scope.

What's missing: **a declarative layer for multi-agent business processes.** Authored procedures that define *how multiple agents coordinate to accomplish a complex objective* — with explicit roles, steps, decision points, inputs, outputs, and hand-offs.

Standing Orders say "be collaborative." Cognitive JIT captures what one agent learned to do. Neither provides a reusable, inspectable, shared definition of *how the crew works together to do X.*

This is the gap observed when the BF-163 DM flood occurred: agents autonomously attempted to schedule meetings and coordinate research — demonstrating the *instinct* for collaboration but lacking any *procedure* to follow. The result was 8,448 messages in 90 minutes. The agents' social judgment was correct; they had no playbook.

### Position in the Four-Tier Capability Model

The Crew Capability Architecture (documented in `docs/research/crew-capability-architecture.md`) defines four tiers:

| Tier | Name | Scope | Examples |
|------|------|-------|----------|
| T1 | Standing Orders | Identity + behavioral standards | federation.md, science.md |
| T2 | Cognitive Skills | Task-specific, instruction-defined (SKILL.md) | architecture-review, threat-assessment |
| T3 | Executable Skills | Learned procedures (Cognitive JIT) | Agent-specific compiled procedures |
| T4 | Assigned Tools | Ship's equipment via Tool Registry | read_file, search_codebase, ward_room_post |

SOPs sit **between T1 and T2** — or more precisely, they *compose* T2 skills and T4 tools into multi-agent workflows:

```
T1  Standing Orders      WHO agents are
    ─────────────────────────────────────────
 ★  SOPs / Bills         HOW agents work together  ← AD-618
    ─────────────────────────────────────────
T2  Cognitive Skills     WHAT agents know how to do
T3  Executable Skills    WHAT agents learned to do
T4  Assigned Tools       WHAT agents can use
```

A SOP references T2 skills ("perform threat assessment"), requires T4 tools ("use ward_room_post"), and is constrained by T1 standing orders ("defer to department chief"). It does not replace any tier — it orchestrates them.

### Connection to Crew Consultation (AD-594)

AD-594 defines the consultation primitive: multi-agent collaborative problem-solving with structured phases (workspace creation, parallel contribution, synthesis, delivery). A consultation IS an SOP — or more precisely, the consultation protocol should be expressible as a Bill. AD-594's decomposition (workspace, primitive, parallel execution, delivery pipeline) maps directly to SOP steps with role assignments.

The "consultation-as-learning" pathway is key: successful consultation executions feed EpisodicMemory, Hebbian reinforcement, and Trust. Through Cognitive JIT (AD-531–539), repeated SOP executions can compile into T3 executable skills — the authored SOP graduates to a learned procedure.

```
Authored SOP (AD-618)
    │ Agent executes their role in the SOP
    ▼
Episode recorded (EpisodicMemory)
    │ Cognitive JIT observes (AD-531)
    ▼
Procedure extracted (AD-532) → stored (AD-533)
    │ Graduated compilation (AD-535)
    ▼
T3 Executable Skill — agent's role in the SOP runs at zero tokens
```

This means SOPs are both immediately useful (agents follow them from day one) and self-improving (agents get faster at their roles through practice).

---

## 2. Navy Source Material

### 2.1 Ship's Organization and Regulations Manual (SORM)

The SORM (OPNAVINST 3120.32D) is the Navy's primary organizational directive. Every ship maintains a SORM that defines:

- **Watch Organization:** Who does what, when, and where. Watch sections, watchstation assignments, rotation schedules.
- **Administrative Organization:** Department/division structure, reporting relationships, qualification requirements.
- **Bills:** Named multi-person procedures for specific situations (see below).
- **Standard Operating Procedures:** Routine processes that ensure consistent execution.

The SORM is the Navy's equivalent of Standing Orders + SOPs combined. ProbOS already has the Standing Orders half (AD-339). AD-618 provides the Bills/SOPs half.

### 2.2 Bills

A Bill is a **named multi-person procedure** that assigns:
- **Stations** — where each person goes (physical or functional position)
- **Duties** — what each person does at their station
- **Sequence** — order of operations with decision points
- **Authority** — who can activate the bill and who has overall responsibility

Key characteristics:
- **Role-based, not name-based.** "Damage Control Assistant" executes Step 3, not "Petty Officer Smith." Anyone qualified for that role can fill it.
- **Condition-activated.** Bills activate on specific triggers: General Quarters, Man Overboard, Fire, UNREP, etc.
- **Exhaustive.** Every person on the ship has an assignment in every major bill. No one is unaccounted for.
- **Drilled.** Bills are practiced regularly. Performance is graded. Qualifications are earned.

Examples of Navy Bills:

| Bill | Trigger | Key Roles | ProbOS Analog |
|------|---------|-----------|---------------|
| General Quarters | Combat/emergency | All hands to battle stations | Ship-wide alert response |
| Fire Bill | Fire detected | Scene Leader, Hose Team, Boundary, Investigator | Incident response SOP |
| Man Overboard | Person overboard | OOD, Bridge, Lookout, Boat Crew, CIC | Lost agent recovery |
| UNREP | Alongside replenishment | Rig Captain, Safety Officer, Winch Operator | External integration procedure |
| Damage Control | Hull breach/flooding | DCA, Repair Locker, DC Central | System degradation response |
| Abandon Ship | Catastrophic damage | CO, Division Officers, Boat Coxswains | Graceful shutdown procedure |

### 2.3 Maintenance Requirement Cards (MRCs)

MRCs (3-M System, OPNAVINST 4790.4) are the atomic unit of naval procedure:

```
┌────────────────────────────────────────────────────┐
│ MRC: F-123-4567                                     │
│ Title: Clean and Inspect Main Feed Pump Strainer    │
│ Periodicity: Quarterly (Q)                          │
│ Man-Hours: 2.0                                      │
├────────────────────────────────────────────────────┤
│ PREREQUISITES:                                      │
│   - System tagged out per TQSO                      │
│   - Tool Kit #3 drawn from tool room                │
│                                                     │
│ SAFETY PRECAUTIONS:                                 │
│   - Ensure zero energy state verified               │
│   - PPE: steel-toed boots, safety glasses            │
│                                                     │
│ TOOLS/PARTS:                                        │
│   - Torque wrench (30 ft-lb range)                  │
│   - Replacement gasket (NSN: 5330-01-234-5678)      │
│                                                     │
│ PROCEDURE:                                          │
│   1. Verify tag-out complete per TQSO               │
│   2. Remove strainer housing (6 bolts, 30 ft-lb)    │
│   3. Extract strainer element                        │
│   4. Inspect for damage (cracks, deformation)        │
│   5. Clean with fresh water and approved solvent     │
│   6. Inspect housing seat for scoring                │
│   7. Install new gasket                              │
│   8. Reinstall strainer element                      │
│   9. Torque bolts to spec (30 ft-lb, star pattern)  │
│  10. Remove tags per TQSO                            │
│  11. Test run, verify no leaks                       │
│                                                     │
│ EXPECTED RESULTS:                                   │
│   - Strainer housing dry, no leaks                  │
│   - Differential pressure within limits              │
│                                                     │
│ SIGN-OFF: ___________ Date: ___________             │
└────────────────────────────────────────────────────┘
```

The MRC format maps directly to an SOP step definition:
- **Prerequisites** → preconditions (state checks before execution)
- **Safety Precautions** → standing order constraints applied during execution
- **Tools/Parts** → T4 tool requirements (Tool Registry)
- **Procedure** → numbered imperative steps
- **Expected Results** → success criteria (assertions)
- **Sign-Off** → audit trail (episodic memory + trust update)

### 2.4 Watch, Quarter, and Station Bill (WQSB)

The WQSB is the master assignment matrix: for each bill (column) and each sailor (row), it specifies their exact station and duties. This is the Navy's "who does what in each situation" lookup table.

ProbOS analog: Role templates (AD-429) + Earned Agency (AD-357) + qualification programs (AD-566) determine which agents can fill which SOP roles. The WQSB equivalent is computed at runtime from agent capabilities, trust levels, and availability — not statically assigned.

---

## 3. BPMN Vocabulary (Not Engine)

Business Process Model and Notation (BPMN 2.0, ISO 19510) provides a mature vocabulary for describing multi-participant processes. ProbOS should absorb the **vocabulary and concepts**, not the XML schema or execution engine.

### Concepts to Absorb

| BPMN Concept | Description | ProbOS Mapping |
|--------------|-------------|----------------|
| **Pool** | Independent organizational entity | ProbOS instance (ship) |
| **Lane** | Role within a pool | Agent role (by qualification, not name) |
| **Task** | Atomic unit of work | SOP step |
| **User Task** | Requires human input | Captain approval gate |
| **Service Task** | Automated execution | T3/T4 tool execution |
| **Send/Receive Task** | Inter-participant message | Ward Room post/DM |
| **XOR Gateway** | Exclusive decision (if/else) | Conditional branch in SOP |
| **AND Gateway** | Parallel split/join | Concurrent agent execution |
| **OR Gateway** | Inclusive decision (one or more paths) | Flexible branching |
| **Timer Event** | Time-based trigger | Scheduled activation |
| **Signal Event** | Broadcast trigger | Alert Condition / event bus |
| **Message Event** | Specific message trigger | Ward Room message, DM, bridge alert |
| **Sub-Process** | Embedded procedure | Nested SOP / Bill reference |

### Concepts to Exclude

| BPMN Concept | Why Excluded |
|--------------|--------------|
| Process Engine (BPEL runtime) | Over-engineered. ProbOS agents have judgment — they don't need a state machine to tell them what comes next. SOPs are reference documents, not execution scripts. |
| Compensation/Transaction boundaries | Agent systems handle failure through trust degradation + Counselor intervention, not transaction rollback. |
| Complex Event Processing | ProbOS has its own event system (intent bus, alert conditions). No need for BPMN's CEP. |
| XML serialization | YAML is the project standard for configuration. Human-readable SOPs in YAML, not BPMN XML. |

### Design Principle: Procedure IS Documentation

In BPMN-based enterprise systems, the process model and the documentation are separate artifacts that drift apart. In ProbOS, **the SOP definition file IS the documentation.** The YAML file that agents parse is the same file that humans read. No separate process diagram that gets out of sync.

This mirrors the Navy MRC model — the card itself is both the procedure and the record. It doesn't reference a separate manual.

---

## 4. Agent Workflow Research

### 4.1 MetaGPT SOPs (Absorbed)

MetaGPT's SOP concept (Hong et al., 2023) defines role-based workflows with structured output schemas. ProbOS absorbed the structured output templates (AD-599/600) but not the behavioral procedures. MetaGPT SOPs are execution-level prescriptions ("SoftwareArchitect produces PRD") — they're closer to T2 cognitive skills than T1/T2 orchestration processes.

**Key difference:** MetaGPT SOPs are production pipelines with fixed role assignments. ProbOS Bills are role-based with qualification gating — any qualified agent can fill any role. This enables resilience (if one agent is unavailable, another qualified agent can step in) and learning (agents build proficiency by practicing different roles).

### 4.2 ProAgent (AAAI 2024)

ProAgent introduces "procedural analysis" where agents dynamically build understanding of multi-step processes. Relevant insight: agents need both static procedure knowledge (SOPs) and dynamic adaptation (adjusting to runtime conditions). ProbOS already has dynamic adaptation through the cognitive cycle; SOPs provide the static knowledge complement.

### 4.3 FlowMind (Flow Engineering)

FlowMind generates workflows as flowcharts using BPMN-like notation, then translates to executable agent chains. Validates the approach: BPMN vocabulary for human-readable process definition, agent execution for runtime behavior. FlowMind uses full BPMN XML; ProbOS should use minimal YAML.

### 4.4 AFlow (MCTS-Based Workflow Optimization)

AFlow uses Monte Carlo Tree Search to optimize multi-agent workflows through experience. Relevant insight: workflow definitions should be evolvable. ProbOS's Cognitive JIT pipeline (AD-531–539) provides this — repeated SOP executions compile into increasingly efficient T3 skills. No need for a separate optimization engine.

### 4.5 MDMP (Military Decision Making Process)

The Military Decision Making Process (FM 5-0) is an 8-step planning procedure:

| MDMP Step | ProbOS Mapping |
|-----------|----------------|
| 1. Receipt of Mission | Captain directive / alert trigger |
| 2. Mission Analysis | Science department research consultation |
| 3. COA Development | Multi-agent brainstorming (Ward Room thread) |
| 4. COA Analysis (War Gaming) | Holodeck simulation / Red Team challenge |
| 5. COA Comparison | Structured voting / Hebbian consensus |
| 6. COA Approval | Captain approval gate |
| 7. Orders Production | SOP instantiation with role assignments |
| 8. Rehearsal/Execution | Bill execution with monitoring |

MDMP is itself a Bill — and could be expressed as one in the ProbOS Bill System. This demonstrates that the system can define meta-procedures (procedures about how to create procedures).

---

## 5. Proposed Design: The Bill System

### 5.1 Core Concepts

| Concept | Definition | Navy Analog |
|---------|-----------|-------------|
| **Bill** | A named, versioned, declarative multi-agent procedure | Ship's Bill |
| **Step** | Atomic unit of work within a Bill | MRC procedure step |
| **Role** | Functional position filled by a qualified agent | Watchstation |
| **Activation** | Condition that triggers Bill execution | Condition (GQ, Fire, etc.) |
| **Instance** | A specific execution of a Bill with assigned agents | Bill activation record |

### 5.2 YAML Schema (Minimal)

```yaml
# Example: Research Consultation Bill
bill: research-consultation
version: 1
title: "Research Consultation"
description: "Multi-department research and analysis producing a written report"
author: captain  # who authored this SOP
activation:
  trigger: manual  # manual | alert:<condition> | schedule:<cron> | event:<type>
  authority: department_chief  # minimum rank to activate

roles:
  lead_researcher:
    qualifications: [research, analysis]
    department: science
    min_rank: lieutenant
  domain_expert:
    qualifications: [domain_knowledge]
    department: any
    count: 1-3  # flexible headcount
  reviewer:
    qualifications: [peer_review]
    department: any
    min_rank: lieutenant
  approver:
    qualifications: []
    department: bridge
    min_rank: commander

steps:
  - id: receive_request
    name: "Receive Research Request"
    role: lead_researcher
    action: receive_message
    inputs:
      - name: topic
        source: activation_data
    outputs:
      - name: research_question
        type: text

  - id: scope_research
    name: "Scope Research Plan"
    role: lead_researcher
    action: cognitive_skill
    skill: research-planning  # T2 cognitive skill reference
    inputs:
      - name: research_question
        source: step:receive_request.research_question
    outputs:
      - name: research_plan
        type: document
    gate: captain_approval  # requires Captain sign-off before proceeding

  - id: parallel_research
    name: "Parallel Domain Research"
    type: parallel  # AND gateway — all roles execute concurrently
    roles: [lead_researcher, domain_expert]
    action: cognitive_skill
    skill: deep-research
    inputs:
      - name: research_plan
        source: step:scope_research.research_plan
    outputs:
      - name: findings
        type: document
    timeout: 3600  # seconds

  - id: synthesize
    name: "Synthesize Findings"
    role: lead_researcher
    action: cognitive_skill
    skill: research-synthesis
    inputs:
      - name: findings
        source: step:parallel_research.findings  # aggregated from all parallel executions
    outputs:
      - name: draft_report
        type: document

  - id: peer_review
    name: "Peer Review"
    role: reviewer
    action: cognitive_skill
    skill: peer-review
    inputs:
      - name: draft_report
        source: step:synthesize.draft_report
    outputs:
      - name: reviewed_report
        type: document
      - name: review_verdict
        type: enum
        values: [approved, revision_needed]

  - id: review_decision
    name: "Review Decision"
    type: xor_gateway  # XOR — exclusive decision
    condition: step:peer_review.review_verdict
    branches:
      approved: deliver
      revision_needed: synthesize  # loop back

  - id: deliver
    name: "Deliver Report"
    role: lead_researcher
    action: post_to_channel
    channel: bridge
    inputs:
      - name: reviewed_report
        source: step:peer_review.reviewed_report

  - id: sign_off
    name: "Commander Sign-Off"
    role: approver
    action: captain_approval
    inputs:
      - name: reviewed_report
        source: step:peer_review.reviewed_report

expected_results:
  - "Research report posted to bridge channel"
  - "All contributing agents have episodic records of their contributions"
  - "Hebbian weights reinforced between collaborating agents"

standing_order_constraints:
  - "Federation communication protocols apply to all inter-department messaging"
  - "Classification restrictions per AD-339 apply to report content"
```

### 5.3 Gateway Types

Following BPMN vocabulary:

| Type | YAML Key | Behavior |
|------|----------|----------|
| **Sequential** | *(default)* | Steps execute in order |
| **Parallel (AND)** | `type: parallel` | All assigned roles execute concurrently; join when all complete |
| **Exclusive (XOR)** | `type: xor_gateway` | One branch taken based on condition |
| **Inclusive (OR)** | `type: or_gateway` | One or more branches taken based on conditions |
| **Loop** | Branch target = earlier step ID | Repeat until condition met |

### 5.4 Action Types

| Action | Description | Tier |
|--------|-------------|------|
| `cognitive_skill` | Execute a T2 SKILL.md | T2 |
| `tool` | Execute a T4 tool | T4 |
| `post_to_channel` | Post to Ward Room channel | T4 |
| `send_dm` | Send a direct message | T4 |
| `receive_message` | Wait for input | Event |
| `captain_approval` | Captain approval gate | Gate |
| `sub_bill` | Execute another Bill as a nested procedure | Composition |

### 5.5 Role Assignment at Runtime

When a Bill is activated:

1. **Parse role requirements** from the Bill definition
2. **Query agent capabilities** via Crew Manifest (AD-513) / qualification records (AD-566)
3. **Filter by availability** via Agent Calendar (AD-496)
4. **Rank candidates** by: qualification match → trust level → Hebbian affinity with other assigned roles → workload
5. **Assign agents to roles** — store in Bill Instance record
6. **Notify assigned agents** via Ward Room DM with their role, steps, and expected inputs

This is the runtime WQSB — computed from live agent state, not statically assigned.

---

## 6. Bill Lifecycle

```
1. AUTHOR      Captain/Chief writes Bill YAML     → stored in Ship's Records
2. VALIDATE    Schema validation + role coherence  → Bill registered, available
3. ACTIVATE    Trigger fires (manual/alert/event)  → Bill Instance created
4. ASSIGN      Runtime WQSB matches agents → roles → agents notified
5. EXECUTE     Agents execute their steps           → steps tracked in Instance
6. MONITOR     Progress visible in HXI              → alerts on stalls/failures
7. COMPLETE    All steps done, expected results met → Instance archived
8. LEARN       Episodes feed Cognitive JIT          → agents get better at their roles

     ┌──────────────────────────────────────────────────────┐
     │  Successful executions → Cognitive JIT (AD-531-539)  │
     │  Agents gradually compile their SOP roles into       │
     │  T3 executable skills. The SOP never changes;        │
     │  the agents just get faster at following it.          │
     └──────────────────────────────────────────────────────┘
```

---

## 7. Built-in Bills (Ship's Defaults)

Every ProbOS instance should ship with a core set of Bills — the "standing bills" that define baseline crew operations:

| Bill | Trigger | Description |
|------|---------|-------------|
| **General Quarters** | Alert Condition RED | All agents to duty stations, non-essential cognitive load suspended |
| **Research Consultation** | Manual / Captain directive | Multi-dept research producing a report (see example above) |
| **Code Review** | Build pipeline trigger | Engineering review of proposed changes |
| **Incident Response** | Alert Condition AMBER+ | Diagnosis → containment → remediation → post-mortem |
| **Onboarding** | New agent creation | Orientation, qualification testing, integration |
| **Daily Operations Brief** | Schedule (0800) | Department chiefs report status to bridge |
| **Self-Modification Review** | Self-mod proposal event | Review → Red Team challenge → Captain approval |
| **Federation Handshake** | Federation discovery event | Trust establishment, capability exchange, SOP sync |

These are authored by the system (or Captain) and available from first boot. Custom Bills can be added by the Captain or department chiefs.

---

## 8. Storage and Discovery

### File-Based Storage (Ship's Records)

Bills are YAML files stored in Ship's Records (AD-434):

```
ship_records/
├── bills/
│   ├── general-quarters.bill.yaml
│   ├── research-consultation.bill.yaml
│   ├── code-review.bill.yaml
│   ├── incident-response.bill.yaml
│   └── custom/
│       └── weekly-architecture-review.bill.yaml
└── bill_instances/
    ├── 2026-04-12_research-consultation_001.yaml
    └── 2026-04-12_incident-response_042.yaml
```

### Discovery

Agents discover available Bills through:
1. **Standing Orders reference** — department standing orders can reference required Bills
2. **Ward Room query** — "What Bill applies to this situation?"
3. **Alert Condition mapping** — alert conditions automatically reference their Bills
4. **Captain directive** — "Execute the Research Consultation Bill for topic X"

---

## 9. AD Decomposition

### AD-618: Bill System Foundation

| Sub-AD | Scope | Dependencies |
|--------|-------|-------------|
| **AD-618a: Bill Schema + Parser** | YAML schema definition, validation, `BillDefinition` dataclass, parser. Ship's Records integration for storage. | AD-434 (Ship's Records) |
| **AD-618b: Bill Instance + Runtime** | `BillInstance` tracking, role assignment engine (runtime WQSB), step state machine, progress monitoring. | AD-618a, AD-566 (qualifications), AD-429 (role ontology) |
| **AD-618c: Built-in Bills** | Author the default ship's Bills (General Quarters, Research Consultation, Incident Response, etc.). | AD-618a |
| **AD-618d: HXI Bill Dashboard** | Bill activation UI, instance monitoring, role assignment view, progress tracking. | AD-618b |
| **AD-618e: Cognitive JIT Bridge** | Successful Bill step executions feed Cognitive JIT. Agent's role-specific steps compile to T3 skills over time. | AD-618b, AD-531–539 (Cognitive JIT) |

### Phase Placement

AD-618 sits at the boundary of Phase E (Advanced Integration) and Phase F. It depends on:
- AD-434 (Ship's Records) — storage ✅ (complete)
- AD-429 (Role Ontology) — role matching (partial, planned)
- AD-566 (Qualification Programs) — qualification gates (partial, Phase A)
- AD-423 (Tool Registry) — tool references in steps (Phase B)
- AD-496–498 (Workforce Scheduling) — availability checking (planned)

AD-618a/618c can be built independently. AD-618b needs AD-429 and AD-566 for full role assignment. AD-618e needs AD-531–539 (complete).

### OSS / Commercial Boundary

**OSS (how it works):**
- Bill YAML schema and parser
- Bill runtime (instance creation, step tracking, role assignment)
- Built-in Bills
- HXI dashboard
- Cognitive JIT bridge
- API for Bill CRUD and activation

**Commercial (how it makes money):**
- Pre-built SOP libraries for vertical industries (consulting, engineering, healthcare)
- Visual Bill Designer (drag-and-drop BPMN-vocabulary editor → YAML output)
- SOP Marketplace (share/sell Bills across Nooplex fleet)
- Enterprise process governance (compliance auditing, SOX/ISO controls on Bill execution)
- Process mining (analyze Bill Instance history for optimization opportunities)
- M365/Teams integration (Bill step notifications in Teams, approval gates in Power Automate)
- Cross-instance Bill synchronization via federation protocol
- SLA monitoring on Bill execution times

---

## 10. Design Principles

1. **Role-based, not name-based.** Bills reference roles with qualification requirements, not specific agents. Any qualified agent can fill any role.

2. **Procedure IS documentation.** The YAML file agents parse is the same file humans read. No separate process diagram that drifts out of sync.

3. **Reference, not engine.** Bills are consulted by agents with judgment, not executed by a state machine. Agents follow the Bill; they aren't puppeted by it. This preserves sovereignty.

4. **Standing Orders are separate.** Bills don't override Standing Orders — they operate within them. A Bill step that would violate a Standing Order is an error in the Bill, not a permission to violate.

5. **Composable.** Bills can reference other Bills as sub-procedures. The Research Consultation Bill might invoke the Peer Review Bill as a sub-step.

6. **Observable.** Bill execution produces episodic records, trust updates, Hebbian reinforcement. Every step is auditable.

7. **Learnable.** Through Cognitive JIT, agents get better at their Bill roles over time. The procedure doesn't change; the agents' proficiency at following it increases.

8. **Drillable.** Bills can be executed in Holodeck simulation mode for training without real side effects. Performance feeds qualification assessments.

---

## 11. Research Sources

### Navy
- OPNAVINST 3120.32D (Ship's Organization and Regulations Manual — SORM)
- OPNAVINST 4790.4 (Ships' Maintenance and Material Management — 3-M System, MRCs)
- FM 5-0 (Military Decision Making Process — MDMP)
- NAVEDTRA 43100 (PQS / Personnel Qualification Standards)
- Navy Watch Quarter and Station Bill (WQSB) procedures

### Academic / Industry
- Hong et al., "MetaGPT: Meta Programming for Multi-Agent Collaborative Framework" (2023)
- Zhang et al., "ProAgent: Building Proactive Cooperative AI with Large Language Models" (AAAI 2024)
- Bao et al., "FlowMind: Automatic Workflow Generation with LLMs" (2024)
- Zhang et al., "AFlow: Automating Agentic Workflow Generation" (2024)
- OMG, "Business Process Model and Notation (BPMN) 2.0.2" (ISO 19510:2013)
- Yao et al., "ReAct: Synergizing Reasoning and Acting in Language Models" (ICLR 2023)

### ProbOS Internal
- `docs/research/crew-capability-architecture.md` — Four-tier capability model, Phase A-E build order
- Crew Consultation Pattern Research (commercial repo, 2026-04-11) — MDMP mapping, AD-594 decomposition, consultation-as-learning
- AD-339 (Standing Orders), AD-434 (Ship's Records), AD-531–539 (Cognitive JIT), AD-566 (Qualifications), AD-594 (Consultation), AD-496–498 (Workforce Scheduling)
