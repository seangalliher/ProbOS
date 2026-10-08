# Project Structure

ProbOS is a Python runtime with a React web interface, an Electron desktop host, and a large test suite. This page maps where things live; package descriptions come from each package's own docstring.

## Repository Layout

```
ProbOS/
├── src/probos/          # The runtime — 993 Python modules (~344,000 lines)
├── ui/                  # HXI — React 19, Three.js, Zustand, Vite
├── desktop/             # Electron tray host for the HXI
├── config/              # system.yaml, standing orders, ontology, skills, manuals, profiles
├── docs/                # probos.dev sources (MkDocs Material)
├── tests/               # pytest suite (~40,000 tests)
├── scripts/             # Test gate, CI sharding, AD ledger, config and architecture checks
├── prompts/             # Build prompts for architecture decisions
├── docker/, Dockerfile  # Container build
├── DECISIONS.md         # Architecture decision log
└── PROGRESS.md          # Narrative progress log
```

## Key Modules

| Module | Role |
|--------|------|
| `__main__.py` | The `probos` CLI: shell, `serve`, `setup`, `doctor`, `reset`, `migrate`, backups, channels, pairing |
| `runtime.py` | Top-level orchestrator: boots pools, wires layers, processes natural language |
| `config.py`, `config_models/` | Pydantic configuration models |
| `types.py` | Core dataclasses (`IntentMessage`, `IntentResult`, `TaskDAG`, `IntentDescriptor`, …) |
| `api.py`, `routers/` | FastAPI application and its 67 router modules |
| `events.py`, `ws_event_stream.py` | Typed event registry and the HXI `/ws/events` stream |
| `proactive.py` | Proactive cognitive loop — periodic idle-think for crew agents |
| `workforce.py`, `work_item_steps.py` | Workforce scheduling engine — work items, assignment and durable steps |
| `identity.py`, `identity_keys.py`, `identity_key_binding.py` | DIDs, birth certificates, the identity ledger, Ed25519 keys |
| `earned_agency.py` | Rank-based agency and recall tiers |

## Packages by Layer

### Substrate and Mesh

| Package | Purpose |
|---------|---------|
| `substrate/` | `BaseAgent`, pools and pool groups, spawner, registry, heartbeat, event log, scaler |
| `mesh/` | Intent bus, Hebbian routing, capability registry, gossip, signals, NATS bus |
| `activation/` | TaskEvent protocol and dispatcher; ontology-based task routing |
| `storage/` | Abstract database storage layer |
| `infrastructure/` | Backup and storage abstraction |

### Consensus, Governance and Security

| Package | Purpose |
|---------|---------|
| `consensus/` | Quorum engine, trust network, Shapley attribution, escalation |
| `governance/` | Action risk tiers, decision queue, compensation and recovery, tenant policy hook |
| `security/` | Threat detection, trust integrity, egress and URL guards, permissions, sandboxes, audit |

### Cognitive

| Package | Purpose |
|---------|---------|
| `cognitive/` | `CognitiveAgent`, decomposer, memory, dreaming, procedures, agentic dispatch, crew orchestration, crew agents, self-modification |
| `agents/` | Infrastructure, utility, medical, engineering and operations agents |
| `tools/` | Tool registry and tools: code execution, browser, delegation, work items, knowledge queries |
| `execution/` | Governed ephemeral code execution — tiered isolation |
| `sop/` | Bill System — declarative multi-agent standard operating procedures |
| `crew_development/` | Crew development framework |
| `perception/` | Visual perception — frame ingestion and episode anchoring |
| `consultation/` | Consultation workspaces |
| `creative/`, `recreation/` | Creative expression and social gaming between agents |
| `holodeck/` | Holodeck birth chamber and scenarios |

### Knowledge and Records

| Package | Purpose |
|---------|---------|
| `knowledge/` | Git-backed KnowledgeStore, Ship's Records, semantic layer, knowledge edges, claims |
| `ontology/` | Vessel ontology — structure, organization and schema |
| `artifacts/`, `attachments/` | Versioned, content-addressed artifacts and chat attachments |
| `threads/`, `task_sessions/` | Chat threads and task sessions |
| `maintenance/` | Episodic backups and `rebuild-episodic` |

### Experience

| Package | Purpose |
|---------|---------|
| `experience/` | Rich terminal shell, slash commands, renderer, panels |
| `ward_room/` | Ward Room — the crew communication fabric |
| `channels/` | Discord, Slack, Telegram, Matrix, Teams, Gmail and webhook adapters |
| `audio/`, `voice/`, `avatars/` | Server-side audio, voice and the avatar pipeline |
| `settings/`, `workstations/`, `captain_card/`, `cloud_pickers/`, `a2ui/`, `mcp_apps/` | HXI settings, workstation types, the Captain Card, cloud file pickers, choice widgets, MCP app host |

### Federation, Integrations and Extensions

| Package | Purpose |
|---------|---------|
| `federation/` | Transports, bridge and router, signed envelopes, peer admission, A2A, ARD |
| `integrations/` | MCP bridge, Microsoft 365 |
| `interop/` | Interop adapters (gitagent) |
| `discovery/` | LAN mDNS discovery for the mobile PADD |
| `migration/` | Import from OpenClaw and Hermes Agent |
| `extensions/`, `packs/`, `hooks/` | Extension substrate, capability packs, lifecycle hooks |

### Platform and Operations

| Package | Purpose |
|---------|---------|
| `startup/` | Boot phases: agent fleet, fleet organization, dreaming, finalize, … |
| `doctor/` | Pluggable health checks for `probos doctor` |
| `maturity/` | Capability truth ledger (AD-1270a) |
| `degradation/` | Graceful degradation ("saucer separation") |
| `naval/` | Naval organization protocols, Captain's Log |
| `onboarding/` | Cold-start helpers |
| `utils/` | Shared helpers |

## Configuration

```
config/
├── system.yaml          # Reference configuration (181 sections)
├── standing_orders/     # Federation, ship, department and agent standing orders
│   └── crew_profiles/   #   Crew personalities and seed callsigns
├── ontology/            # Vessel ontology: organization, crew, communication, records, …
├── skills/              # Cognitive skills (SKILL.md)
├── manuals/             # Crew manuals
├── profiles/, extension_profiles/, contracts/, task_orders/
```

## Web Interface

```
ui/src/
├── components/          # React components: bridge, Ward Room, workstations, approvals, profiles, …
├── canvas/              # WebGL cognitive mesh visualization
├── chat/                # Chat surfaces
├── audio/               # TTS, speech input, sound engine
├── avatars/             # Avatar rendering
├── store/               # Zustand state management + TypeScript types
├── hooks/               # WebSocket connection to the runtime
├── pwa/                 # Mobile PADD (progressive web app)
└── __tests__/           # Vitest suites
```

## History: Wave 3 Decomposition (AD-515 to AD-519)

In March 2026 the three largest files were decomposed into focused modules:

| Original File | Before | After | New Package |
|--------------|--------|-------|-------------|
| `runtime.py` | 5,321 lines | 2,762 lines | `startup/` |
| `api.py` | 3,109 lines | 295 lines | `routers/` |
| `shell.py` | 1,883 lines | 507 lines | `experience/commands/` |

`runtime.py` has since grown back to about 6,100 lines as capabilities were added; the [AD-1270 Platform Maturity Program](platform-maturity-program.md) is moving ownership behind bounded facades.
