# Project Structure

```
src/probos/
├── __init__.py              # Package root
├── __main__.py              # Entry point (probos CLI)
├── api.py                   # FastAPI server + WebSocket events
├── config.py                # Pydantic config models
├── runtime.py               # Top-level orchestrator (~2500 lines)
├── types.py                 # Core types (30+ dataclasses)
├── agents/                  # Tool agents (deterministic)
│   ├── file_reader.py       #   read_file, stat_file
│   ├── file_writer.py       #   write_file (consensus-gated)
│   ├── directory_list.py    #   list_directory
│   ├── file_search.py       #   search_files
│   ├── shell_command.py     #   run_command (consensus-gated)
│   ├── http_fetch.py        #   http_fetch (rate-limited, consensus-gated)
│   ├── introspect.py        #   explain_last, agent_info, system_health, why
│   ├── system_qa.py         #   Smoke tests for designed agents
│   ├── red_team.py          #   Independent verification
│   ├── corrupted.py         #   Test agent (deliberately wrong)
│   └── bundled/             #   10 CognitiveAgent types ("useful on Day 1")
│       ├── web_agents.py    #     WebSearch, PageReader, Weather, News
│       ├── language_agents.py #   Translator, Summarizer
│       ├── productivity_agents.py # Calculator, Todo, NoteTaker
│       └── organizer_agents.py #  Scheduler
├── cognitive/               # LLM pipeline + self-modification
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
│   └── research.py          #   Web research phase for agent design
├── consensus/               # Multi-agent agreement
│   ├── quorum.py            #   Confidence-weighted voting
│   ├── trust.py             #   Bayesian Beta(α,β) reputation
│   ├── shapley.py           #   Shapley value attribution
│   └── escalation.py        #   3-tier failure cascade
├── experience/              # User interface
│   ├── shell.py             #   Async REPL (20+ commands)
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
    ├── scaler.py            #   Demand-based pool scaling
    ├── heartbeat.py         #   Periodic pulse loop
    ├── event_log.py         #   Append-only SQLite audit log
    ├── identity.py          #   Persistent agent identity
    └── skill_agent.py       #   SkillBasedAgent (dynamic skill dispatch)

ui/src/                      # HXI — Human Experience Interface (React + Three.js)
├── canvas/                  #   WebGL cognitive mesh visualization
├── components/              #   CognitiveCanvas, AgentTooltip, overlays
├── audio/                   #   TTS, speech input, sound engine
├── store/                   #   Zustand state management
└── hooks/                   #   WebSocket connection to runtime
```
