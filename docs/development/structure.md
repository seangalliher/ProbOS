# Project Structure

```
src/probos/
├── __init__.py              # Package root
├── __main__.py              # Entry point (probos CLI)
├── config.py                # Pydantic config models
├── runtime.py               # Top-level orchestrator (2,762 lines, decomposed)
├── types.py                 # Core types (30+ dataclasses)
├── build_queue.py           # Priority build queue
├── build_dispatcher.py      # Automated builder dispatch
├── crew_profile.py          # Crew identity + personality
├── sif.py                   # Structural Integrity Field
├── task_tracker.py          # Agent task lifecycle
├── watch_rotation.py        # Watch rotation + duty shifts
├── worktree_manager.py      # Git worktree lifecycle
├── agents/                  # Tool agents (deterministic) + department crews
│   ├── file_reader.py       #   read_file, stat_file
│   ├── file_writer.py       #   write_file (consensus-gated)
│   ├── directory_list.py    #   list_directory
│   ├── file_search.py       #   search_files
│   ├── shell_command.py     #   run_command (consensus-gated)
│   ├── http_fetch.py        #   http_fetch (rate-limited)
│   ├── introspect.py        #   explain_last, agent_info, system_health, why
│   ├── system_qa.py         #   Smoke tests for designed agents
│   ├── red_team.py          #   Independent verification + write checks
│   ├── corrupted.py         #   Test agent (deliberately wrong)
│   ├── utility/             #   10 bundled utility agents
│   │   ├── web_agents.py    #     WebSearch, PageReader, Weather, News
│   │   ├── language_agents.py #   Translator, Summarizer
│   │   ├── productivity_agents.py # Calculator, Todo, NoteTaker
│   │   └── organizer_agents.py #  Scheduler
│   ├── medical/             #   Medical department (5 agents)
│   │   ├── diagnostician.py #     Chief Medical Officer (Bones)
│   │   ├── vitals_monitor.py #    Continuous health metrics (Chapel)
│   │   ├── surgeon.py       #     Targeted remediation (Chapel, dual-hatted)
│   │   ├── pharmacist.py    #     Configuration prescriptions (Keiko)
│   │   └── pathologist.py   #     Failure analysis (Cortez)
│   └── science/             #   Science Analytical Pyramid (AD-560)
│       ├── data_analyst.py  #     Data Analyst (Kira)
│       ├── systems_analyst.py #   Systems Analyst (Lynx)
│       └── research_specialist.py # Research Specialist (Atlas)
├── cognitive/               # LLM pipeline + self-modification + crew agents
│   ├── cognitive_agent.py   #   Instructions-first LLM agent base
│   ├── decomposer.py        #   NL → TaskDAG + DAG executor
│   ├── prompt_builder.py    #   Dynamic system prompt assembly
│   ├── llm_client.py        #   OpenAI-compatible + mock client
│   ├── working_memory.py    #   Bounded context assembly
│   ├── episodic.py          #   Episodic memory (Anchor Frames, ACT-R activation)
│   ├── attention.py         #   Priority scoring + focus tracking
│   ├── dreaming.py          #   12-step dream consolidation
│   ├── dream_adapter.py     #   Dream cycle coordination
│   ├── workflow_cache.py    #   LRU pattern cache
│   ├── standing_orders.py   #   4-tier instruction composition
│   ├── self_model.py        #   SystemSelfModel for grounding
│   ├── trust_dampening.py   #   Trust cascade dampening (AD-558)
│   ├── emergence_metrics.py #   PID-based emergence measurement (AD-557)
│   ├── self_regulation.py   #   3-tier cognitive self-regulation (AD-502–506)
│   ├── qualification_tests.py # Cognitive qualification probes
│   ├── domain_tests.py      #   Domain-specific qualification tests
│   ├── orientation.py       #   Agent orientation service
│   ├── architect.py         #   ArchitectAgent / First Officer (Meridian)
│   ├── builder.py           #   BuilderAgent / Chief Engineer
│   ├── code_reviewer.py     #   CodeReviewAgent
│   ├── counselor.py         #   CounselorAgent / Ship's Counselor (Echo)
│   ├── scout.py             #   ScoutAgent (Horizon)
│   ├── security_officer.py  #   SecurityAgent (Worf)
│   ├── operations_officer.py #  OperationsAgent (O'Brien)
│   ├── engineering_officer.py # EngineeringAgent (LaForge)
│   ├── codebase_index.py    #   Codebase knowledge graph
│   ├── copilot_adapter.py   #   Visiting officer (Copilot SDK)
│   ├── agent_designer.py    #   LLM designs new agents from capability gaps
│   ├── self_mod.py          #   Self-modification pipeline
│   ├── code_validator.py    #   Static analysis for generated code
│   ├── sandbox.py           #   Isolated execution for untrusted agents
│   └── ...                  #   + feedback, patcher, embeddings, proactive, etc.
├── cognitive_jit/           # Procedural Learning pipeline (AD-531–539)
│   ├── clustering.py        #   Episode clustering
│   ├── extraction.py        #   Procedure extraction
│   ├── store.py             #   Procedure store
│   ├── replay.py            #   Replay engine + fallback
│   ├── graduation.py        #   Dreyfus competency levels
│   ├── governance.py        #   Trust-gated promotion
│   ├── observational.py     #   Observational learning (Bandura)
│   ├── lifecycle.py         #   Decay, archival, dedup
│   └── gap_detection.py     #   Gap → qualification triggering
├── identity/                # W3C DID Identity (AD-441)
│   ├── did.py               #   DID generation + resolution
│   ├── credentials.py       #   Verifiable Credentials
│   ├── ledger.py            #   Identity Ledger (hash-chain)
│   └── birth_certificate.py #   Agent + Ship birth certificates
├── ward_room/               # Agent Communication Fabric (AD-407–412)
│   ├── channels.py          #   Channel management (10 default)
│   ├── messages.py          #   Message storage + threading
│   ├── dm.py                #   Direct message channels
│   └── moderation.py        #   Content moderation + rate limiting
├── ships_records/           # Ship's Records (AD-434)
│   ├── notebooks.py         #   Agent notebook management
│   ├── duty_log.py          #   Duty log entries
│   └── captains_log.py      #   Captain's Log
├── startup/                 # Runtime decomposition (AD-515–519)
│   ├── infrastructure.py    #   Phase 1: Core infrastructure
│   ├── structural_services.py # Phase 2: Structural services
│   ├── agent_fleet.py       #   Phase 3: Agent pool creation
│   ├── fleet_organization.py #  Phase 4: Pool groups + departments
│   ├── cognitive_services.py #  Phase 5: Skills, QA, self-mod
│   ├── communication.py     #   Phase 6: Channels + Discord
│   ├── dreaming.py          #   Phase 7: Dream engine setup
│   ├── results.py           #   Phase 8: Result persistence
│   ├── finalize.py          #   Phase 9: Final initialization
│   └── shutdown.py          #   Graceful shutdown sequence
├── routers/                 # FastAPI routers (AD-515–519)
│   ├── agents.py            #   Agent management endpoints
│   ├── chat.py              #   Chat + intent processing
│   ├── wardroom.py          #   Ward Room API
│   ├── identity.py          #   DID + credential endpoints
│   ├── procedures.py        #   Cognitive JIT procedures
│   ├── records.py           #   Ship's Records API
│   ├── recreation.py        #   Recreation + games
│   └── ...                  #   + 13 more domain routers
├── experience/              # User interface
│   ├── shell.py             #   Async REPL (42 slash commands)
│   ├── renderer.py          #   Real-time DAG execution display
│   ├── panels.py            #   Rich panel/table rendering
│   └── commands/            #   Shell commands (AD-517)
│       ├── commands_status.py    # /status, /agents, /ping, etc.
│       ├── commands_memory.py    # /memory, /recall, /dream, etc.
│       ├── commands_knowledge.py # /knowledge, /search, /scout, etc.
│       ├── commands_directives.py # /orders, /directives, etc.
│       ├── commands_autonomous.py # /conn, /night-orders, /watch
│       ├── commands_procedure.py  # /procedure, /gap, /qualify
│       └── ...              #   + 6 more command modules
├── recreation/              # Agent recreation system (AD-526)
│   ├── games.py             #   Game engine (tic-tac-toe, etc.)
│   └── creative.py          #   Creative expression channels
├── ontology/                # Vessel ontology (AD-513)
│   └── vessel.py            #   Crew manifest + cognitive grounding
├── storage/                 # Abstract storage interfaces
│   └── connections.py       #   Cloud-ready DB connection layer
├── channels/                # Communication adapters
│   ├── base.py              #   Channel ABC
│   ├── discord_adapter.py   #   Discord integration
│   └── response_formatter.py #  Format responses per channel
├── consensus/               # Multi-agent agreement
│   ├── quorum.py            #   Confidence-weighted voting
│   ├── trust.py             #   Bayesian Beta(α,β) reputation
│   ├── shapley.py           #   Shapley value attribution
│   └── escalation.py        #   3-tier failure cascade
├── federation/              # Multi-node mesh
│   ├── bridge.py            #   ZeroMQ node bridge
│   ├── router.py            #   Intent forwarding + loop prevention
│   └── transport.py         #   Transport abstraction
├── knowledge/               # Persistent storage
│   ├── store.py             #   Git-backed operational state persistence
│   └── semantic.py          #   SemanticKnowledgeLayer (ChromaDB)
├── mesh/                    # Agent coordination
│   ├── intent.py            #   Pub/sub bus with fan-out
│   ├── routing.py           #   Hebbian learning (SQLite)
│   ├── capability.py        #   Fuzzy matching registry
│   ├── gossip.py            #   SWIM-style state exchange
│   └── signal.py            #   TTL-enforced signals
├── substrate/               # Agent lifecycle
│   ├── agent.py             #   BaseAgent ABC (perceive/decide/act/report)
│   ├── registry.py          #   Async-safe agent index
│   ├── spawner.py           #   Template-based factory
│   ├── pool.py              #   Resource pools + health checks
│   ├── pool_group.py        #   PoolGroup + PoolGroupRegistry
│   ├── scaler.py            #   Demand-based pool scaling
│   ├── heartbeat.py         #   Periodic pulse loop
│   ├── event_log.py         #   Append-only SQLite audit log
│   ├── identity.py          #   Deterministic slot identity
│   └── skill_agent.py       #   SkillBasedAgent (dynamic skill dispatch)
└── utils/                   # Shared utilities

config/
├── system.yaml              # Main configuration
└── standing_orders/         # Constitution hierarchy
    ├── federation.md        #   Tier 1: Federation Constitution
    ├── ship.md              #   Tier 2: Ship Standing Orders
    ├── engineering.md       #   Tier 3: Department protocols
    ├── science.md
    ├── medical.md
    ├── security.md
    ├── operations.md
    ├── bridge.md
    ├── builder.md           #   Tier 4: Agent standing orders
    ├── architect.md
    ├── counselor.md
    └── ... (15+ agent files)

ui/src/                      # HXI — Human Experience Interface (React + Three.js)
├── canvas/                  #   WebGL cognitive mesh visualization
├── components/              #   IntentSurface, MissionControl, SystemOrb, overlays
├── audio/                   #   TTS, speech input, sound engine
├── store/                   #   Zustand state management + TypeScript types
└── hooks/                   #   WebSocket connection to runtime
```

### Wave 3 Decomposition (AD-515/516/517/518/519)

The three largest files in the codebase were decomposed into focused modules:

| Original File | Before | After | Reduction | New Package |
|--------------|--------|-------|-----------|-------------|
| `runtime.py` | 5,321 lines | 2,762 lines | -48.1% | `startup/` (10 modules) |
| `api.py` | 3,109 lines | 295 lines | -90.5% | `routers/` (21 modules) |
| `shell.py` | 1,883 lines | 507 lines | -73.1% | `experience/commands/` (13 modules) |
