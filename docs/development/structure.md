# Project Structure

```
src/probos/
├── __init__.py              # Package root
├── __main__.py              # Entry point (probos CLI)
├── api.py                   # FastAPI server + WebSocket events
├── config.py                # Pydantic config models
├── runtime.py               # Top-level orchestrator
├── types.py                 # Core types (30+ dataclasses)
├── build_queue.py           # Priority build queue (AD-371)
├── build_dispatcher.py      # Automated builder dispatch (AD-372)
├── crew_profile.py          # Crew identity + personality (AD-376)
├── sif.py                   # Structural Integrity Field (AD-370)
├── task_tracker.py          # Agent task lifecycle (AD-316)
├── watch_rotation.py        # Watch rotation + duty shifts (AD-377)
├── worktree_manager.py      # Git worktree lifecycle (AD-371)
├── agents/                  # Tool agents (deterministic)
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
│   ├── utility/             #   10 CognitiveAgent types ("useful on Day 1")
│   │   ├── web_agents.py    #     WebSearch, PageReader, Weather, News
│   │   ├── language_agents.py #   Translator, Summarizer
│   │   ├── productivity_agents.py # Calculator, Todo, NoteTaker
│   │   └── organizer_agents.py #  Scheduler
│   └── medical/             #   Medical department (5 agents)
│       ├── diagnostician.py #     Chief Medical Officer
│       ├── vitals_monitor.py #    Continuous health metrics
│       ├── surgeon.py       #     Targeted remediation
│       ├── pharmacist.py    #     Configuration prescriptions
│       └── pathologist.py   #     Failure analysis
├── cognitive/               # LLM pipeline + self-modification + crew agents
│   ├── decomposer.py        #   NL → TaskDAG + DAG executor
│   ├── prompt_builder.py    #   Dynamic system prompt assembly
│   ├── llm_client.py        #   OpenAI-compatible + mock client
│   ├── cognitive_agent.py   #   Instructions-first LLM agent base
│   ├── working_memory.py    #   Bounded context assembly
│   ├── episodic.py          #   ChromaDB semantic long-term memory
│   ├── attention.py         #   Priority scoring + focus tracking
│   ├── dreaming.py          #   Offline consolidation + pre-warm
│   ├── workflow_cache.py    #   LRU pattern cache
│   ├── agent_designer.py    #   LLM designs new agents from capability gaps
│   ├── self_mod.py          #   Self-modification pipeline orchestrator
│   ├── code_validator.py    #   Static analysis for generated code
│   ├── sandbox.py           #   Isolated execution for untrusted agents
│   ├── skill_designer.py    #   Skill template generation
│   ├── skill_validator.py   #   Skill safety validation
│   ├── behavioral_monitor.py #  Runtime behavior tracking post-deploy
│   ├── feedback.py          #   Human feedback → trust/Hebbian/episodic
│   ├── correction_detector.py # Distinguishes corrections from new requests
│   ├── agent_patcher.py     #   Hot-patches designed agent code
│   ├── strategy.py          #   StrategyRecommender (skill attachment)
│   ├── dependency_resolver.py # Auto-install agent dependencies (uv)
│   ├── emergent_detector.py #   5 algorithms for emergent behavior
│   ├── embeddings.py        #   Embedding utilities
│   ├── research.py          #   Web research phase for agent design
│   ├── architect.py         #   ArchitectAgent (First Officer / CSO)
│   ├── builder.py           #   BuilderAgent (Chief Engineer, Transporter)
│   ├── code_reviewer.py     #   CodeReviewAgent (Standing Orders gate)
│   ├── counselor.py         #   CounselorAgent (Ship's Counselor)
│   ├── codebase_index.py    #   Codebase knowledge graph (AST, imports)
│   ├── codebase_skill.py    #   Skill interface to codebase index
│   ├── copilot_adapter.py   #   Visiting officer (Copilot SDK)
│   ├── standing_orders.py   #   Instruction composition (4-tier)
│   ├── self_model.py        #   SystemSelfModel for grounding
│   └── task_scheduler.py    #   Task scheduling
├── channels/                # Communication adapters
│   ├── base.py              #   Channel ABC
│   ├── discord_adapter.py   #   Discord integration
│   └── response_formatter.py #  Format responses per channel
├── consensus/               # Multi-agent agreement
│   ├── quorum.py            #   Confidence-weighted voting
│   ├── trust.py             #   Bayesian Beta(α,β) reputation
│   ├── shapley.py           #   Shapley value attribution
│   └── escalation.py        #   3-tier failure cascade
├── experience/              # User interface
│   ├── shell.py             #   Async REPL (36+ commands)
│   ├── renderer.py          #   Real-time DAG execution display
│   ├── panels.py            #   Rich panel/table rendering
│   ├── knowledge_panel.py   #   Knowledge store panels
│   └── qa_panel.py          #   QA result panels
├── federation/              # Multi-node mesh
│   ├── bridge.py            #   ZeroMQ node bridge
│   ├── router.py            #   Intent forwarding + loop prevention
│   └── transport.py         #   Transport abstraction
├── knowledge/               # Persistent storage
│   ├── store.py             #   Git-backed artifact persistence
│   └── semantic.py          #   SemanticKnowledgeLayer (5 ChromaDB collections)
├── mesh/                    # Agent coordination
│   ├── intent.py            #   Pub/sub bus with fan-out
│   ├── routing.py           #   Hebbian learning (SQLite)
│   ├── capability.py        #   Fuzzy matching registry
│   ├── gossip.py            #   SWIM-style state exchange
│   └── signal.py            #   TTL-enforced signals
└── substrate/               # Agent lifecycle
    ├── agent.py             #   BaseAgent ABC (perceive/decide/act/report)
    ├── registry.py          #   Async-safe agent index
    ├── spawner.py           #   Template-based factory
    ├── pool.py              #   Resource pools + health checks
    ├── pool_group.py        #   PoolGroup + PoolGroupRegistry (7 depts)
    ├── scaler.py            #   Demand-based pool scaling
    ├── heartbeat.py         #   Periodic pulse loop
    ├── event_log.py         #   Append-only SQLite audit log
    ├── identity.py          #   Persistent agent identity
    └── skill_agent.py       #   SkillBasedAgent (dynamic skill dispatch)

config/
├── system.yaml              # Main configuration
└── standing_orders/         # Constitution hierarchy
    ├── federation.md        #   Tier 1: Federation Constitution
    ├── ship.md              #   Tier 2: Ship Standing Orders
    ├── engineering.md       #   Tier 3: Department protocols
    ├── science.md
    ├── medical.md
    ├── security.md
    ├── bridge.md
    ├── builder.md           #   Tier 4: Agent standing orders
    ├── architect.md
    ├── counselor.md
    ├── diagnostician.md
    └── ... (12 agent files)

ui/src/                      # HXI — Human Experience Interface (React + Three.js)
├── canvas/                  #   WebGL cognitive mesh visualization
├── components/              #   IntentSurface, MissionControl, SystemOrb, overlays
├── audio/                   #   TTS, speech input, sound engine
├── store/                   #   Zustand state management + TypeScript types
└── hooks/                   #   WebSocket connection to runtime
```
