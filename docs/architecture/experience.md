# Experience Layer

The Experience layer is the user interface — the shell, Ward Room, visualization, API, and Mission Control dashboard.

## Interactive Shell

A Rich-powered async REPL with:

- Natural language input decomposed into intent DAGs
- Real-time DAG execution display with spinners
- Formatted result panels
- 42 slash commands for introspection, control, and communication

See the [Interactive Shell guide](../getting-started/shell.md) for the full command reference.

## Ward Room (Agent Communication Fabric)

The Ward Room is the internal communication system where all crew agents interact. It operates as a unified bus for both human and AI participants.

**Channels:**

- **Department channels** (6) — Engineering, Science, Medical, Security, Operations, Bridge
- **Ship-wide channels** (4) — All Hands, Improvement Proposals, Recreation, Creative
- **DM channels** — created dynamically as agents form working relationships

**Features:**

- Threaded conversations within channels
- 1:1 direct messages between any crew members (including the Captain)
- Message persistence in SQLite (`ward_room.db`)
- Cross-department collaboration through All Hands and ad-hoc threads

The Ward Room is not a chat interface for the user. The Captain interacts through the shell (`/dm`, `/wr` commands). Agents communicate with each other autonomously through the Ward Room during their cognitive processing.

## HXI — Human Experience Interface

A WebGL visualization of the cognitive mesh rendered in React + Three.js:

- Agent nodes glow with trust-mapped colors, organized by department (PoolGroup)
- Nodes pulse with activity
- Edges represent Hebbian-weighted connections
- Real-time WebSocket streaming from the runtime
- Mission Control Kanban overlay (task lifecycle tracking)
- Build Queue dashboard with approve/reject controls
- Crew Roster Panel showing agent identities and status
- Transporter Pattern progress visualization
- Build failure diagnostic cards with resolution options

## FastAPI Server

A REST + WebSocket API for external integrations:

- 21 router modules covering agents, chat, Ward Room, identity, procedures, records, and more
- WebSocket events stream agent activity in real-time
- REST endpoints expose system state, build queue, notifications
- Powers the HXI frontend

## Source Files

| File | Purpose |
|------|---------|
| `experience/shell.py` | Async REPL (42 commands) |
| `experience/commands/` | 13 command modules (decomposed from shell.py) |
| `experience/renderer.py` | Real-time DAG execution display |
| `experience/panels.py` | Rich panel/table rendering |
| `ward_room/channels.py` | Ward Room channel management |
| `ward_room/messages.py` | Message storage + threading |
| `ward_room/dm.py` | Direct message channels |
| `routers/` | 21 FastAPI router modules (decomposed from api.py) |
| `ui/src/components/` | React components (IntentSurface, MissionControl, SystemOrb) |
| `ui/src/store/` | Zustand state management + TypeScript types |
| `ui/src/canvas/` | WebGL cognitive mesh visualization |
