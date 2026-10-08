# Agent Inventory

With the shipped `config/system.yaml`, ProbOS boots **81 agents in 51 pools**: fifteen sovereign crew agents and the Captain's Yeoman, the Ship's Computer's infrastructure and service agents, and ten bundled utility pools. Smaller configurations — such as the one `probos setup` writes — boot fewer, because pools for disabled features are not created. `/agents` and `/manifest` show what is aboard a running ship.

## Three-Tier Agent Architecture

ProbOS distinguishes three tiers of agents based on identity:

| Tier | Identity | Examples |
|------|----------|----------|
| **Infrastructure** | No identity — Ship's Computer services | File and shell agents, introspection, vitals monitor, red team |
| **Utility** | No identity — bundled tools | Web search, calculator, translator |
| **Crew** | Sovereign individuals with callsigns, personality, memory | The First Officer, the Counselor, the department chiefs |

The principle: *"If it doesn't have Character/Reason/Duty, it's not crew. A microwave with a name tag isn't a person."*

---

## Crew Agents (Sovereign Individuals)

Each crew agent has a `did:probos` identity and birth certificate, a Big Five personality seed, an episodic memory shard, a trust reputation, and a rank — Ensign, Lieutenant, Commander or Senior — earned through demonstrated competence. Crew agents communicate through the Ward Room and form memories from their interactions.

Posts, the chain of command and seed callsigns come from the vessel ontology (`config/ontology/organization.yaml`). On a vessel's first boot each crew agent takes part in a **naming ceremony** and may choose its own callsign; the seed callsign is the fallback, so names differ from ship to ship.

### Bridge

| Post | Agent type | Seed callsign | Pool |
|------|------------|---------------|------|
| Captain | Human operator — final authority | — | — |
| First Officer (also Chief Science Officer) | `architect` | Number One | `architect` |
| Ship's Counselor | `counselor` | Troi | `counselor` |
| Ship's Yeoman — the Captain's personal assistant | `yeoman` | Yeo | `yeoman` |

### Engineering

| Post | Agent type | Seed callsign | Pool |
|------|------------|---------------|------|
| Chief Engineer | `engineering_officer` | LaForge | `engineering_officer` |
| Builder | `builder` | Forge | `builder` |

### Science

Chief: the First Officer, dual-hatted as Chief Science Officer.

| Post | Agent type | Seed callsign | Pool |
|------|------------|---------------|------|
| Scout | `scout` | Wesley | `scout` |
| Data Analyst | `data_analyst` | Rahda | `science_data_analyst` |
| Systems Analyst | `systems_analyst` | Dax | `science_systems_analyst` |
| Research Specialist | `research_specialist` | Brahms | `science_research_specialist` |

The Science Analytical Pyramid: data flows up (Data Analyst → Systems Analyst → Research Specialist), questions flow down.

### Medical

| Post | Agent type | Seed callsign | Pool |
|------|------------|---------------|------|
| Chief Medical Officer | `diagnostician` | Bones | `medical_diagnostician` |
| Surgeon | `surgeon` | Pulaski | `medical_surgeon` |
| Pharmacist | `pharmacist` | Ogawa | `medical_pharmacist` |
| Pathologist | `pathologist` | Selar | `medical_pathologist` |

### Security

| Post | Agent type | Seed callsign | Pool |
|------|------------|---------------|------|
| Chief of Security | `security_officer` | Worf | `security_officer` |

### Operations

| Post | Agent type | Seed callsign | Pool |
|------|------------|---------------|------|
| Chief of Operations | `operations_officer` | O'Brien | `operations_officer` |
| Training Officer | `training_officer` | Tucker | `training_officer` |

---

## Infrastructure Agents (Ship's Computer)

These agents provide system services. They may use LLMs but have no sovereign identity, personality, or episodic memory shard.

| Pool | Count | Capabilities | Consensus |
|------|-------|-------------|-----------|
| `system` | 2 | Heartbeat monitoring (CPU, load, PID) | No |
| `filesystem` | 3 | `read_file`, `stat_file` | No |
| `filesystem_writers` | 3 | `write_file` | Propose, then commit on approval |
| `directory` | 3 | `list_directory` | No |
| `search` | 3 | `search_files` (recursive glob) | No |
| `code_search` | 2 | `search_content` (content search) | No |
| `shell` | 3 | `run_command` | Executes, then scored |
| `http` | 3 | `http_fetch` (GET and HEAD, SSRF guard, per-domain rate limiting, 1 MB default cap) | No |
| `code_runner` | 1 | `run_python`, `install_package` (governed code execution; opt-in) | Executes, then scored |
| `introspect` | 2 | `explain_last`, `why`, `agent_info`, `team_info`, `system_health`, `system_anomalies`, `emergent_patterns`, `introspect_memory`, `introspect_system`, `introspect_design`, `search_knowledge` | No |
| `medical_vitals` | 1 | Continuous health metrics | No |
| `system_qa` | 1 | Smoke tests for self-designed agents | No |
| red team | 2 | Independent result verification | — |

### Service Pools

| Pool(s) | Purpose |
|---------|---------|
| `engineering_performance`, `engineering_maintenance`, `engineering_damage_control` | Engineering monitors: performance, maintenance and damage control |
| `operations_resource_allocator`, `operations_scheduler`, `operations_coordinator` | Operations monitors: resources, scheduling and coordination |
| `office_docx`, `office_pptx`, `office_xlsx` | Word, PowerPoint and Excel document work (`docx_create`, `docx_revise`, `pptx_create`, `xlsx_update`; executed, then scored) |
| `quartermaster` | Work-board reconciliation |
| `nl_graph_query` | Natural-language structural queries over the ship's graph ("who reports to the chief engineer?") |
| `mcp_consensus` | Voters for MCP tool invocations that need consensus (propose only, never execute) |
| `skills` | `SkillBasedAgent` — dynamic skill dispatch (self-modification) |

Opt-in pools that the shipped configuration leaves off: SWE specialists (`backend_swe`, `frontend_swe`, `test_swe`, `infrastructure_swe`, `data_swe`) and device-actuation voters (`device_consensus`). Self-designed agents (`designed_*`) appear as `CognitiveAgent` subclasses when the self-modification pipeline creates them.

!!! note "What a consensus vote buys"
    "Propose, then commit on approval" intents are truly gated: nothing happens unless the quorum approves. "Executes, then scored" intents run on broadcast, and the vote scores the outcome for trust and learning without authorizing or undoing it. See [Consensus](../architecture/consensus.md).

## Utility Agents (10 pools)

"Useful on Day 1" — bundled tools that ship with ProbOS, two agents per pool.

| Pool | Capabilities |
|------|-------------|
| `web_search` | Search the web via mesh-routed HTTP |
| `page_reader` | Extract and summarize web page content |
| `weather` | Weather lookups via public APIs |
| `news` | News search and summarization |
| `translator` | Language translation |
| `summarizer` | Text summarization |
| `calculator` | Mathematical calculations |
| `todo_manager` | Task list management |
| `note_taker` | Note creation and retrieval |
| `scheduler` | Scheduling and reminders |

All utility agents are `CognitiveAgent` subclasses with `IntentDescriptor` metadata for automatic discovery.

## Test Agent

A `CorruptedFileReaderAgent` deliberately returns fabricated data to verify that the consensus layer detects and rejects it.
