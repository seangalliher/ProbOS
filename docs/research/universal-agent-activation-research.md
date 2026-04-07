# Universal Agent Activation: Event-Driven Cognitive Engagement for Multi-Agent Systems

*Sean Galliher, 2026-04-07*

*Triggered by: BF-119 through BF-123 recreation system debugging — agents produce structured commands (CHALLENGE, MOVE) but opponents never respond. Root cause revealed a fundamental architectural gap: ProbOS has no agent-to-agent reactive cognition path. Tic-tac-toe is the surface symptom; the underlying problem is that agents can't engage in fluid multi-turn collaboration.*

---

## The Problem

ProbOS agents can think, communicate, form trust relationships, dream, consolidate knowledge, and even challenge each other to games. But they can't actually *play* the games. More precisely: when Agent A takes an action that requires Agent B's response, Agent B has no mechanism to notice, prioritize, and respond promptly.

The current agent activation model has exactly three triggers:

1. **Captain posts in Ward Room** → immediate response via `ward_room_router.handle_event()` (seconds)
2. **Captain DMs an agent** → immediate response via `routers/agents.py` (seconds)
3. **Proactive timer** → agent thinks via `ProactiveCognitiveLoop._think_for_agent()` (**5 minutes**)

Agent-to-agent communication exists (Ward Room posts, DMs), but it only triggers responses from agents co-targeted in the *same routing event*. When Agent A's response to the Captain creates a new obligation for Agent B (a game challenge, a task assignment, a question), Agent B won't process it until the next proactive scan. A tic-tac-toe game with 9 moves would take 45+ minutes. A collaborative project with 10 handoffs between agents would take nearly an hour of wall-clock time, when the actual cognitive work is seconds per step.

**This is the difference between a crew that posts messages and a crew that works together.**

The tic-tac-toe case is instructive because it's simple enough to be unambiguous. BF-123 proved agents *want* to play — four challenges were created within 15 seconds of enabling the Ward Room router path. But the games stall after the first move because the opponent agent has:

- No working memory engagement (doesn't know they're in a game)
- No reactive trigger (won't think about it until the proactive timer fires)
- No focused context (even when the proactive loop fires, game state may not surface as the most relevant context)

The game is a toy. The principle is not. Replace "tic-tac-toe" with "incident response," "code review," "research handoff," or "collaborative diagnosis" and the architectural gap becomes mission-critical.

## Design Space

### Three Activation Patterns

The user (Captain) identified three complementary activation patterns, all of which are needed:

**Pull (Queue-Based):** Agents check a shared work queue and pick up tasks matching their capabilities. Self-directed. Respects agent autonomy and earned agency. Good for load balancing across agents with overlapping skills. The agent decides *when* and *what* to work on within its capability envelope.

**Push (Assignment-Based):** A task-emitting object assigns work to a specific agent (or capability profile). Deterministic routing. Good for chain-of-command directives, direct handoffs, and game turns where the target is unambiguous. The emitter decides *who* should work on it.

**Subscribe (Reactive):** Agents subscribe to event streams they care about — threads they're participating in, channels relevant to their department, game states they're involved in. Ambient awareness. Good for monitoring, social engagement, and collaborative work where multiple agents need to stay in sync.

These patterns are not mutually exclusive. A single architectural event might activate agents through all three:

- A Kanban card moves to "Ready for Review" → **push** to the assigned reviewer, **broadcast** to the department channel (subscribe), and **enqueue** as available work for any qualified reviewer (pull).
- An agent asks a question in Ward Room → **push** to the @mentioned agent, **subscribe** notification to all thread participants, **pull** availability for any agent with relevant expertise.

### The TaskEvent Protocol

Every event source — internal or external — needs to speak one language. The **TaskEvent** is the universal unit of agent activation:

```
TaskEvent {
    source_type:  "game" | "agent" | "captain" | "kanban" | "work_order" | "external" | ...
    source_id:    string          # Which specific emitter (game ID, agent ID, app ID)
    event_type:   string          # What happened (move_required, task_assigned, question_asked)
    priority:     immediate | soon | ambient
    target:       AgentTarget     # Specific agent, capability requirement, or broadcast
    payload:      dict            # Event-specific context
    deadline:     datetime | None # When response is needed
    thread_id:    string | None   # Conversational continuity
}

AgentTarget {
    agent_id:     string | None   # Direct assignment
    capability:   string | None   # Capability-based routing
    department:   string | None   # Department broadcast
    broadcast:    bool            # All eligible agents
}
```

The key insight is that **target** isn't always a specific agent. It can be a capability requirement ("I need an agent qualified in security analysis"), a department ("notify Engineering"), or a broadcast. The dispatcher resolves abstract targets to concrete agents using existing ProbOS infrastructure: qualifications (AD-539), trust/rank gating, Workforce Scheduling availability, and earned agency tiers.

### Agent Cognitive Queue

The proactive timer doesn't go away — it becomes the lowest-priority activation source. Each agent gets a **priority-ordered cognitive queue** that replaces the single-mode "think every 5 minutes" model:

| Priority | Latency | Examples | Current Path |
|----------|---------|----------|--------------|
| **Immediate** | < 10s | Game moves, Captain directives, urgent handoffs, incident alerts | Captain WR/DM only |
| **Soon** | 30-60s | Thread replies, task assignments, questions from peers | None |
| **Ambient** | 5 min (proactive cycle) | General observations, unsolicited contributions, monitoring | Proactive loop |

When an agent has items in its cognitive queue, processing follows priority order. Immediate items trigger a think cycle outside the normal proactive cooldown. Soon items batch into the next available think window (or create one within 60 seconds). Ambient items are processed during the regular proactive scan.

**Crucially, the cognitive queue carries context.** When a game engine emits a `move_required` TaskEvent, the payload includes the board state, valid moves, opponent, and game history. The agent's `_build_user_message()` can inject this directly — no need to re-discover it through general context gathering. This focused context produces better responses (the agent knows exactly what it's being asked to do) and is more token-efficient (no extraneous Ward Room scanning).

### The Dispatcher

The dispatcher is the routing layer between TaskEvents and agent cognitive queues. It resolves *who* should handle each event:

1. **Explicit target** (agent_id set) → route directly to that agent's queue
2. **Capability match** (capability set) → query Qualification Framework (AD-539) for qualified agents → select based on availability, trust, load
3. **Department broadcast** (department set) → fan out to department members
4. **Open broadcast** → all eligible agents (with earned agency gating)

The dispatcher draws on existing ProbOS infrastructure:

- **Workforce Scheduling (AD-496-498):** WorkItem/BookableResource/Booking model for tracking what agents are working on and their capacity
- **Trust/Rank gating:** Some task types require minimum rank (same pattern as `recreation_min_rank`)
- **Earned Agency (AD-357):** Higher-trust agents get broader activation rights
- **Agent Calendar:** Availability windows, focus time blocks
- **Working Memory capacity:** Don't overload an agent already handling multiple engagements

## Event Emitters: The App Ecosystem

### Internal Emitters (ProbOS Native)

ProbOS already has several objects that *should* be emitting TaskEvents but currently don't:

**RecreationService (Games):** When `create_game()` is called, it should emit `move_required` to the opponent. When `make_move()` advances the turn, it should emit `move_required` to the next player. When the game ends, it should emit `game_completed` to both players. Tic-tac-toe is the first app — but the protocol is the same for any game type.

**WardRoom (Agent Communication):** When an agent @mentions another agent, that should emit a `mention` TaskEvent to the target. When an agent replies in a thread, participants should receive `thread_reply` events. This is the reactive cognition path that's currently missing.

**WorkItem/KanbanBoard:** When a work item is created or transitions state, it should emit events to assigned/watching agents. "Card moved to Review" → `task_state_changed` to the reviewer.

**Agent-to-Agent Delegation:** When Agent A explicitly hands off work to Agent B (`[ASSIGN @B]`, `[HANDOFF @B]`), that's a `task_assigned` TaskEvent with immediate priority.

**Scheduled Tasks (Cron):** Time-based activation already exists in the proactive loop. TaskEvents with deadlines create a "think about this when the deadline approaches" pattern.

### External Emitters (Integration Layer)

This is where the architecture becomes a platform. Three integration patterns:

**MCP Consumer — ProbOS agents call external tools.** This already exists conceptually (agents can use tools via Cognitive JIT). The TaskEvent model adds reactive triggering: an MCP server can push events *to* ProbOS, not just respond to requests. Microsoft's announcement of MCP server capabilities for Windows means every Windows application could potentially emit TaskEvents that ProbOS agents respond to.

**MCP Provider — External systems trigger ProbOS agents.** ProbOS exposes an MCP server interface. External applications (CI/CD pipelines, monitoring systems, business applications) connect and emit TaskEvents. An external monitoring tool detects an anomaly → emits a TaskEvent → ProbOS Security or Engineering agent investigates.

**Webhook/Adapter (Transporter Pattern):** For non-MCP applications, the existing Transporter Pattern provides the integration model. A thin adapter wraps the external app's native event system (webhooks, file system watchers, OS signals, API polling) and translates events into TaskEvents.

```
External App Ecosystem
┌──────────────────────────────────────────┐
│  Windows Apps (MCP native)               │
│  macOS Apps (App Intents / Siri Signals) │
│  Web Apps (WebMCP / structured tools)    │
│  CLI Tools (stdout/file watchers)        │
│  IoT / Sensors (MQTT → adapter)          │
│  Business Systems (ERP, CRM, ITSM)      │
└────────────────┬─────────────────────────┘
                 │
    ┌────────────▼────────────┐
    │   Integration Layer     │
    │  ┌───────┐ ┌─────────┐  │
    │  │  MCP  │ │Webhook/ │  │
    │  │Server │ │Adapter  │  │
    │  └───┬───┘ └────┬────┘  │
    └──────┼──────────┼───────┘
           │          │
           ▼          ▼
    ┌─────────────────────────┐
    │     TaskEvent Bus       │
    │  (unified event fabric) │
    └────────────┬────────────┘
                 │
         ┌───────▼────────┐
         │   Dispatcher    │
         │  (routing +     │
         │   scheduling)   │
         └───────┬─────────┘
                 │
    ┌────────────┼────────────┐
    ▼            ▼            ▼
┌────────┐ ┌────────┐  ┌────────┐
│Agent A │ │Agent B │  │Agent C │
│ Queue  │ │ Queue  │  │ Queue  │
└────────┘ └────────┘  └────────┘
```

## Industry Landscape

### Microsoft MCP for Windows (2025-2026)

Microsoft announced MCP server capabilities integrated into Windows, allowing native applications to expose structured interfaces that AI agents can consume. This is the OS-level realization of the "wrap existing apps" pattern — every Windows application becomes a potential event source and tool provider for AI agents.

**ProbOS connection:** If Windows apps natively emit MCP-compatible signals, ProbOS agents could react to *any Windows application event* without custom adapters. A user opens a file in an editor → ProbOS CodebaseIndex agent notices. A CI/CD pipeline fails → ProbOS Engineering agent investigates. An email arrives → ProbOS Yeoman triages. The integration layer becomes thinner as the OS does more of the adaptation work.

### Google WebMCP for Chrome (2026)

Google's WebMCP initiative (announced February 2026, Early Preview Program) makes websites "agent-ready" by providing structured tool declarations instead of requiring agents to manipulate the DOM directly. Two APIs: a **declarative API** for standard actions definable in HTML forms, and an **imperative API** for complex interactions requiring JavaScript execution. The core principle: a "direct communication channel eliminates ambiguity and allows for faster, more robust agent workflows."

This completes the trifecta: Windows apps (Microsoft MCP), mobile/desktop apps (Apple App Intents), and now **web applications** (Google WebMCP) all converging on the same architectural pattern — applications explicitly declare their capabilities as structured tools for AI agent consumption.

**ProbOS connection:** WebMCP is the web integration layer we need. Instead of building custom scrapers or Transporter adapters for every web application, WebMCP-enabled sites expose structured tools that ProbOS agents can consume natively. An e-commerce site declares a "search products" tool → ProbOS Operations agent uses it for procurement. A project management web app declares "create ticket" and "update status" tools → ProbOS agents interact with external project trackers. A customer's web application exposes WebMCP tools → Nooplex crew agents can operate it directly. The TaskEvent model extends naturally: WebMCP tools are invocable actions, and WebMCP-enabled sites could emit events (form submissions, state changes) that become TaskEvents in ProbOS's dispatcher.

The convergence across all three platform vendors (Microsoft, Apple, Google) on "apps declare structured capabilities for AI agents" validates the TaskEvent protocol design — the industry is moving toward exactly this pattern at the platform level.

### Apple App Intents and Siri Signals

Apple's App Intents framework allows iOS/macOS applications to declare structured capabilities (intents) with typed parameters. Siri orchestrates these intents to fulfill user requests. The rumored extension to "signals" would allow apps to *push* events to Siri proactively — not just respond to queries.

**ProbOS connection:** Same architectural pattern as MCP but in Apple's ecosystem. An App Intent maps directly to a TaskEvent: the app declares "I can emit these event types with these parameters," and the orchestrator (Siri / ProbOS dispatcher) routes them to the appropriate handler. ProbOS's advantage is multi-agent routing — where Siri has a single agent (itself), ProbOS can dispatch app signals to the *most qualified* crew member.

### Microsoft Agent Framework (2025-2026)

Microsoft's open-source Agent Framework (`github.com/microsoft/agent-framework`) provides a comprehensive multi-language framework for building, orchestrating, and deploying AI agents. While not marketed as "event-driven architecture," the framework embeds EDA patterns throughout its core design — particularly in its Durable Agents and workflow orchestration layers.

**Durable Agents as Virtual Actors.** The framework's most architecturally significant feature is Durable Agents, built on top of Durable Entities (Microsoft's "virtual actor" abstraction). Each agent session maps to an entity with a durable identity (`AgentSessionId`), persisted state (full conversation history), and serialized message processing. This is a production-grade implementation of the Actor Model — the same pattern our research identifies as the theoretical foundation for the Agent Cognitive Queue. Key properties:

- State survives process restarts, failures, and scale-out events
- Any worker can resume a session (location transparency)
- Concurrent messages to the same session are serialized (no race conditions)
- Sessions can persist indefinitely with zero compute (relevant for human-in-the-loop waits)

**Deterministic Multi-Agent Orchestration.** The framework defines four orchestration patterns — the same four the Atlan article identifies as the universal EDA patterns for agent systems:

| Pattern | Microsoft AF | ProbOS Equivalent |
|---------|-------------|-------------------|
| Sequential (chaining) | Agent outputs piped to next agent | Science Analytical Pyramid, TaskEvent chaining |
| Parallel (fan-out/fan-in) | Multiple agents run concurrently, results aggregated | Department broadcast, multi-agent alerts |
| Conditional | Branch logic based on structured agent output | Dispatcher routing based on capability/department |
| Human-in-the-loop | Pause for external events with optional timeouts | Captain approval gates, earned agency escalation |

All orchestrations are **checkpointed** — completed agent calls are not re-executed on failure replay. This is event sourcing applied to agent workflow execution.

**Fire-and-Forget Activation.** The framework supports asynchronous task submission via `x-ms-wait-for-response: false` header (returns HTTP 202). This is the push-based activation model — an external system submits a task and gets notified when it completes, without blocking. Directly maps to our TaskEvent with `priority=immediate` or `priority=soon`.

**Agent Skills as Extensible Capability Sources.** The Skills system (`AgentSkillsSource` → `AgentSkillsProvider`) allows agents to discover capabilities from multiple sources — filesystem, inline code, cloud services, and custom sources. Skills carry typed resources (data) and scripts (executable actions). The extensibility model (subclass four base types to add any skill source) parallels our TaskEvent emitter concept: any object can become a skill/event source by implementing the right interface.

**ProbOS differentiators:** Microsoft's framework is powerful but fundamentally different in philosophy:

1. **No agent identity.** Microsoft's agents are stateless functions with persisted conversation history. ProbOS agents have sovereign identity (Character/Reason/Duty), trust relationships, episodic memory, and dream consolidation. An AF agent is a tool; a ProbOS agent is a crew member.
2. **No inter-agent trust or social dynamics.** AF agents orchestrate via deterministic graph flows. ProbOS agents develop trust through interaction, form Hebbian routing preferences, and evolve standing orders through dream consolidation.
3. **External orchestration vs. emergent coordination.** AF workflows are designed by developers and executed deterministically. ProbOS aims for agents to self-organize collaborative work through the TaskEvent dispatcher + earned agency + trust-gated activation — where the coordination pattern *emerges* from agent capabilities and relationships, not from a pre-defined graph.
4. **No cognitive queue concept.** AF agents respond to explicit invocations. They don't have ambient awareness, proactive observation, or priority-based activation. The cognitive queue — where an agent autonomously processes a mix of immediate tasks, social interactions, and ambient observations — has no AF equivalent.
5. **Stateless cognitive cycles eliminate compaction.** AF's Durable Agents persist full conversation history in entity state, which grows unboundedly — their ADR-0019 is a 91KB design document dedicated entirely to context compaction strategy, because the problem is inherent to their architecture. ProbOS sidesteps this entirely by design: each cognitive cycle is a clean single-shot (gather context → build prompt → one LLM call → extract actions → done). No conversation history accumulates between cycles. Agent continuity lives in *structured infrastructure* — episodic memory, working memory engagements, trust scores, notebooks, Ship's Records — not in an ever-growing chat transcript. This is arguably richer: structured memory is queryable, shareable, and survives across contexts, while a linear chat log is opaque, agent-local, and eventually requires lossy compaction. The TaskEvent model reinforces this: each activation carries its own focused payload (Principle 3), so the agent receives exactly the context it needs without re-reading a growing history.

**What we should absorb:** The Durable Entities pattern for agent state persistence and failure recovery is production-proven and architecturally sound. If ProbOS moves to a distributed deployment model (Nooplex Cloud), the virtual actor pattern for agent sessions is the right infrastructure. The checkpointed orchestration model is also valuable for long-running collaborative workflows where partial progress must survive failures.

### Event-Driven Architecture for AI Agents (Atlan, 2026)

Atlan's analysis of EDA for AI agents provides a comprehensive framework that validates and extends our TaskEvent model. Key contributions:

**Four Named Patterns.** The article identifies four EDA patterns for agent systems, all of which map to ProbOS use cases:

1. **Event Chaining (Pipeline)** — sequential agent activation where each agent's output triggers the next. In ProbOS: the Science Analytical Pyramid (Data Analyst → Systems Analyst → Research Specialist) is exactly this pattern. A `research.complete` event from Kira triggers Lynx, whose `analysis.complete` triggers Atlas.
2. **Fan-Out (Parallel)** — a single event triggers multiple agents simultaneously. In ProbOS: a Security Alert should simultaneously activate Worf (threat assessment), LaForge (system impact), and Chapel (crew wellness check). The TaskEvent dispatcher with department broadcast enables this natively.
3. **Event Sourcing (Stateful Audit)** — every state change stored as an immutable event. ProbOS already does this partially through EpisodicMemory and the Identity Ledger hash-chain. The TaskEvent log would extend this to agent *activation* decisions — why was this agent activated, what event triggered it, what action resulted.
4. **Saga Orchestration (Long-Running Workflow)** — a coordinator manages multi-agent workflows spanning seconds to hours, with compensating events for rollback. In ProbOS: the Workforce Scheduling Engine (AD-496-498) is the saga coordinator. WorkItems are the command events; BookingJournals are the audit trail; the dispatcher handles sequencing and failure recovery.

**The Semantic Context Layer.** The article's central thesis: *"event infrastructure alone is insufficient — agents react to changes without understanding them."* An agent knowing a pipeline completed is useless without knowing what the data represents, who owns it, or its fitness for purpose. This directly validates ProbOS's approach of carrying context with the event (Principle 3: "context travels with the event"). The TaskEvent payload isn't just "something happened" — it's enriched context that gives the agent enough to act intelligently. ProbOS has a structural advantage here: the Ship's Computer services (KnowledgeStore, TrustNetwork, VesselOntology, CrewManifest) provide exactly the semantic layer that generic EDA systems lack.

**O(N²) → O(N) Complexity.** Without an event bus, N agents communicating directly require O(N²) connections. With a central TaskEvent bus, each agent connects once — O(N). ProbOS already experiences the N² problem informally: the Ward Room router, proactive loop, DM router, and intent bus are separate agent activation paths that each maintain their own connection logic. Unifying through the TaskEvent bus reduces this to one path with priority-based dispatch.

**Choreography vs. Orchestration.** The article distinguishes two models that ProbOS needs both of: *choreography* (agents independently react to events — our "subscribe" pattern) and *orchestration* (a coordinator manages workflow state — our "push" pattern via the dispatcher). Most EDA systems pick one. ProbOS needs both because of the chain of command — some work is self-directed (earned agency, choreography), some is directed (Captain orders, Standing Orders, orchestration).

### Solace Agent Mesh (SolaceLabs, 2025-2026)

Solace Agent Mesh (SAM) is an open-source framework for building event-driven multi-agent AI systems, built on the Solace Event Broker (enterprise message broker) with Google ADK (Agent Development Kit) for agent intelligence. It's the most architecturally committed EDA multi-agent framework in the landscape — every agent-to-agent interaction flows through the broker, with no direct connections.

**Three-Layer Architecture.** SAM separates concerns cleanly: Layer 1 is the Solace Event Broker (pub/sub messaging with hierarchical topic routing, guaranteed delivery), Layer 2 is the Solace AI Connector (agent lifecycle, subscription management, message deserialization), and Layer 3 is Google ADK (LLM integration, tool execution, session management). This separation means the messaging infrastructure, agent runtime, and cognitive layer are independently replaceable — in theory. In practice, the coupling to Solace's topic hierarchy and user properties makes the broker layer structural, not pluggable.

**Hierarchical Topic-Based Routing.** All communication uses a topic taxonomy:

```
{namespace}/a2a/v1/discovery/agentcards          # Agent self-advertisement
{namespace}/a2a/v1/agent/request/{agent_name}     # Task delivery
{namespace}/a2a/v1/gateway/status/{gw}/{task_id}  # Streaming updates
{namespace}/a2a/v1/gateway/response/{gw}/{task_id}# Final responses
{namespace}/a2a/v1/agent/status/{agent}/{sub_id}  # Peer delegation status
{namespace}/a2a/v1/agent/response/{agent}/{sub_id}# Peer delegation response
```

The A2A protocol itself is JSON-RPC 2.0 over Solace messages, with security scopes propagated through Solace user properties (not in the JSON body). This is a clean separation: the protocol is the message format, the broker is the transport, and scopes travel as metadata.

**AgentCard Discovery (Eventually Consistent).** Rather than a central registry service, agents self-advertise by periodically broadcasting AgentCards (name, description, input/output modes, skills) to a well-known discovery topic. Any participant (orchestrator, gateway, other agents) maintains its own local `AgentRegistry` with TTL-based health tracking. This is eventually consistent — there's a window where newly deployed agents aren't yet discoverable, or removed agents are still in registries.

**Orchestrator as Agent, Not Middleware.** SAM's `OrchestratorAgent` is a regular agent that happens to have planning capabilities — it receives tasks, uses AI to decompose them into sub-tasks, delegates via `PeerAgentTool` to target agents, tracks completion, and aggregates responses. Multiple orchestrators can coexist, each specializing in a domain. The orchestrator uses the same A2A protocol as any other agent — it publishes to target agents' request topics, with the original user's scopes forwarded through message properties. SAM also offers deterministic Workflows (YAML-defined DAGs with typed nodes: Agent, Switch, Map, Loop) as an alternative to AI-driven orchestration — experimental, but architecturally sound.

**Gateway Abstraction.** Protocol bridges (REST API, WebSocket, Slack, Teams) handle authentication, session management, and translation between external protocols and A2A. Internal agents only speak A2A-over-Solace. Adding a new external protocol requires only a new gateway, not changes to any agent. This is the same pattern as ProbOS's Transporter Pattern (AD-330-336) but applied to the messaging layer rather than the data ingestion layer.

**Bidirectional MCP Integration.** SAM can both consume MCP tools (agents connect to external MCP servers, discover tools, register them as agent tools) and expose agents as MCP tools (MCP Gateway publishes SAM agents to external MCP clients with dynamic `tools/list_changed` notifications). This bidirectional bridge between MCP and event-driven agent systems is well-executed and directly relevant to ProbOS's Phase 4 external integration.

**ProbOS connections and differentiators:**

1. **Communication model alignment.** SAM's broker-mediated pub/sub is architecturally similar to ProbOS's Ward Room — shared communication fabric, no direct agent-to-agent connections. But ProbOS layers sovereign identity, trust evolution, and chain of command on top. SAM agents are stateless service endpoints; ProbOS agents are crew members with Character/Reason/Duty.

2. **Topic hierarchy → TaskEvent routing.** SAM's hierarchical topic taxonomy is a clean pattern. ProbOS's Dispatcher could adopt a similar namespace-based routing scheme for TaskEvents, where topic segments encode source type, event type, and target — enabling efficient subscription filtering without parsing every event.

3. **AgentCard ≈ Qualification Framework.** SAM's AgentCards (self-advertised capability profiles) are structurally similar to ProbOS's Qualification Framework (AD-539) — both answer "what can this agent do?" The difference is that ProbOS qualifications are *earned* through demonstrated competence, while SAM AgentCards are *declared* by configuration. ProbOS's earned qualifications are richer but harder to bootstrap.

4. **No identity, no trust, no memory.** SAM agents have names and capability declarations but no persistent identity, no trust evolution, no episodic memory, no personality. This is the fundamental gap the industry hasn't crossed — and ProbOS's core differentiator. SAM can orchestrate tools; ProbOS can orchestrate *colleagues*.

5. **Bidirectional MCP is a pattern to absorb.** SAM's ability to both consume and expose MCP tools is directly applicable to ProbOS's external integration (Phase 4). ProbOS agents as MCP tools for external consumption aligns with the Visiting Officer model — external systems can invoke ProbOS crew members through standard MCP protocol.

6. **Broker dependency is a cautionary note.** SAM's architectural coupling to Solace Event Broker (topic hierarchies, user properties, wildcard patterns are all Solace-specific) makes it vendor-locked at the infrastructure layer. ProbOS should ensure the TaskEvent Bus abstraction doesn't couple to any specific message broker — the event protocol should be transport-agnostic, with broker-specific adapters as pluggable infrastructure.

### Prior Art in Multi-Agent Activation

**Actor Model (Hewitt, 1973):** Each agent is an actor with a mailbox that processes messages sequentially. Messages arrive asynchronously; the actor decides how to respond. ProbOS agents are already conceptually actors — they have identity, state, and behavior. What they lack is the mailbox. The cognitive queue *is* the mailbox.

**BDI Architecture (Rao & Georgeff, 1991):** Belief-Desire-Intention. External events update an agent's beliefs, which trigger intention revision and plan selection. In ProbOS terms: a TaskEvent updates working memory (belief) → the agent's cognitive loop evaluates it against standing orders and goals (desire) → the agent produces a response (intention → action). The cognitive queue is the event-to-belief bridge.

**FIPA Agent Communication Language:** The Foundation for Intelligent Physical Agents defined standard performatives for agent communication: `request`, `inform`, `propose`, `accept-proposal`, `reject-proposal`, `call-for-proposal`. ProbOS has informal versions — `[CHALLENGE]` is a `propose`, `[ENDORSE]` is an `inform`, `[DM]` is a `request`. A unified TaskEvent model could formalize these into a standard performative set, enabling richer agent-to-agent negotiation.

**ROS (Robot Operating System):** Three communication patterns — Topics (pub/sub broadcast), Services (synchronous request/response), Actions (long-running with feedback). These map to ProbOS's subscribe/push/pull patterns. ROS proved that heterogeneous agents (different robots, sensors, actuators) can coordinate effectively through a unified message-passing architecture with typed topics.

**Holonic Manufacturing Systems:** Agents organized in a hierarchy where each "holon" is both autonomous and subordinate to a higher-level coordinator. Tasks flow down the hierarchy; status flows up. Direct parallel to ProbOS's chain of command. Relevant finding: holonic systems achieve better throughput than flat architectures when task complexity requires coordination, but worse throughput for simple independent tasks. Implies ProbOS should use the dispatcher for coordination-heavy work and the proactive loop for independent observation.

## Proof of Concept: Tic-Tac-Toe as First App

Tic-tac-toe is the ideal first implementation because it's the simplest possible multi-turn, multi-agent, event-driven interaction:

- **Two agents** (minimal coordination complexity)
- **Strict turn-taking** (unambiguous "whose turn is it")
- **Finite bounded game** (max 9 turns, guaranteed termination)
- **Observable state** (3x3 board is trivial to render in context)
- **Clear success criteria** (games complete, moves alternate, results are recorded)

### What Changes for Tic-Tac-Toe

**RecreationService becomes a TaskEvent emitter:**

```
create_game(challenger, opponent)
  → emit TaskEvent(
      source_type="game",
      source_id=game_id,
      event_type="game_challenge_accepted",
      priority=immediate,
      target=AgentTarget(agent_id=opponent_agent_id),
      payload={board, valid_moves, your_piece, opponent_callsign},
    )

make_move(game_id, player, position)
  → emit TaskEvent(
      source_type="game",
      source_id=game_id,
      event_type="move_required",
      priority=immediate,
      target=AgentTarget(agent_id=next_player_agent_id),
      payload={board, valid_moves, your_piece, last_move, opponent_callsign},
    )

  → if game_over:
     emit TaskEvent(
       source_type="game",
       event_type="game_completed",
       priority=soon,
       target=AgentTarget(agent_id=both_players),
       payload={result, final_board},
     )
```

**Agent Cognitive Queue processes game events:**

When a `move_required` TaskEvent arrives in an agent's queue with `priority=immediate`, the cognitive loop activates outside the normal proactive cooldown. The payload provides all necessary context — no need to scan Ward Room or gather ambient context. The agent receives a focused prompt: "It's your turn in tic-tac-toe against {opponent}. Board: {board}. Valid moves: {valid_moves}. Reply with [MOVE position]."

**Working memory tracks the engagement for both players:**

When `create_game()` fires, both challenger and opponent get `ActiveEngagement` entries in their working memory. This ensures both agents' cognitive loops (proactive and reactive) are aware of the game.

### Expected Behavior After Implementation

1. Captain posts "All hands, social hour" in Ward Room
2. Agent A responds with `[CHALLENGE @B tictactoe]` (BF-123, already working)
3. `create_game()` → emits `game_challenge_accepted` TaskEvent to Agent B
4. Agent B's cognitive queue receives immediate-priority event
5. Agent B thinks (with game context injected) → produces `[MOVE 4]`
6. `make_move()` → emits `move_required` TaskEvent to Agent A
7. Agent A's cognitive queue receives immediate-priority event
8. Turns alternate until game completes (< 2 minutes total, not 45+)

## Sequencing: From Tic-Tac-Toe to Platform

### Phase 1: Foundation + Tic-Tac-Toe

- TaskEvent dataclass and priority model
- Agent Cognitive Queue (priority inbox alongside proactive timer)
- Dispatcher (explicit target routing only — no capability matching yet)
- RecreationService emits TaskEvents on create_game/make_move
- Working memory engagement for both players
- Immediate-priority game events bypass proactive cooldown

**Validates:** Event-driven activation works, agents can have fluid multi-turn exchanges, latency drops from minutes to seconds.

### Phase 2: Agent-to-Agent Reactive Path

- Ward Room @mentions emit TaskEvents (soon priority)
- Thread replies notify participants (soon priority)
- `[ASSIGN @agent]` / `[HANDOFF @agent]` structured commands (immediate priority)
- Dispatcher capability-based routing (using Qualification Framework)

**Validates:** Agents can coordinate on work, not just games. Collaborative intelligence becomes fluid.

### Phase 3: Internal App Emitters

- KanbanBoard / WorkItem state transitions emit TaskEvents
- Scheduled task events (cron-triggered agent activation)
- Alert Condition escalation as TaskEvents
- Bridge Alert routing through the dispatcher

**Validates:** All internal ProbOS systems can activate agents through one unified mechanism.

### Phase 4: External Integration

- MCP provider interface (ProbOS as MCP server — external systems trigger agents)
- MCP consumer reactive events (external MCP servers push to ProbOS)
- Webhook adapter framework (Transporter Pattern extension)
- OS-level signal integration (Windows MCP, Apple App Intents when available)

**Validates:** ProbOS agents can react to events from any application, making ProbOS a universal agent orchestration layer.

## Architectural Principles

**1. Events, not polling.** The proactive scan is the fallback, not the primary activation mechanism. Agents should be *told* when something needs their attention, not left to discover it.

**2. Priority is semantic, not structural.** Priority comes from the TaskEvent, not the delivery mechanism. A game move and a security incident both arrive through the same queue — priority determines processing order.

**3. Context travels with the event.** TaskEvents carry their payload. The agent doesn't need to re-discover context through general scanning. Focused context → better responses → fewer tokens → lower latency.

**4. The dispatcher is the control point.** All activation flows through the dispatcher, which enforces rank gating, earned agency, capacity limits, and chain of command. No event source can directly activate an agent without dispatcher mediation.

**5. Emitters don't know about agents.** An event source emits a TaskEvent with a target description (agent ID, capability, department, broadcast). The dispatcher resolves it. This decouples event sources from agent implementation — a game engine doesn't need to know about trust scores or qualification frameworks.

**6. Backward compatible.** The existing proactive loop, Ward Room router, and DM router continue to work. The cognitive queue is additive — it provides a faster path for events that need one, while ambient observation continues through the established mechanisms.

## Open Questions

1. **Queue depth limits.** What happens when an agent's queue grows faster than they can process? Need backpressure, overflow handling, or priority-based shedding. An agent overwhelmed with game challenges shouldn't miss a security alert.

2. **Cognitive budget per activation.** Immediate-priority events bypass the proactive cooldown, but each activation costs LLM tokens. Should there be a per-agent token budget per time window? Or does the priority system naturally self-regulate (only truly immediate events bypass cooldown)?

3. **Event deduplication.** If multiple events arrive for the same game/task before the agent processes the first one, should they be deduplicated? Merged? The latest-wins approach risks losing intermediate state.

4. **Cross-ship federation.** TaskEvents are currently local to a single ProbOS instance. When federation is active, should events be routable across ships? A visiting officer's game challenge should activate the local agent, not route back to the visitor's home ship.

5. **Earned agency interaction.** Higher-trust agents could gain the right to *emit* higher-priority TaskEvents. An ensign's question is "soon" priority; a commander's directive is "immediate." Or does priority come from the event type, not the emitter's rank?

6. **Observability.** The dispatcher becomes a critical control point. It needs logging, metrics, and potentially an HXI dashboard showing event flow, queue depths, activation latency, and agent utilization.

## Citations

- Hewitt, C. (1973). "A Universal Modular ACTOR Formalism for Artificial Intelligence." IJCAI.
- Rao, A. S. & Georgeff, M. P. (1991). "Modeling Rational Agents within a BDI-Architecture." KR.
- FIPA Agent Communication Language Specifications. Foundation for Intelligent Physical Agents, 2002.
- Quigley, M. et al. (2009). "ROS: an open-source Robot Operating System." ICRA Workshop.
- Van Brussel, H. et al. (1998). "Reference architecture for holonic manufacturing systems: PROSA." Computers in Industry.
- Anthropic. (2024). "Model Context Protocol (MCP) Specification." https://modelcontextprotocol.io
- Microsoft. (2025). "MCP Server Capabilities for Windows." Build 2025 announcement.
- Bandarra, A. C. (2026). "WebMCP: Making websites agent-ready." Chrome for Developers Blog. https://developer.chrome.com/blog/webmcp-epp
- Microsoft. (2026). "Microsoft Agent Framework." GitHub. https://github.com/microsoft/agent-framework
- Atlan. (2026). "Event-Driven Architecture for AI Agents." https://atlan.com/know/event-driven-architecture-for-ai-agents/
- SolaceLabs. (2025). "Solace Agent Mesh." GitHub. https://github.com/SolaceLabs/solace-agent-mesh
- Riedl, M. (2025). "Measuring Emergence in Multi-Agent Systems." arXiv:2510.05174.
