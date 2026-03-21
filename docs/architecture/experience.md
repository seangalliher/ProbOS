# Experience Layer

The Experience layer is the user interface — the shell, visualization, API, and Mission Control dashboard.

## Interactive Shell

A Rich-powered async REPL with:

- Natural language input decomposed into intent DAGs
- Real-time DAG execution display with spinners
- Formatted result panels
- 36+ slash commands for introspection and control

See the [Interactive Shell guide](../getting-started/shell.md) for the full command reference.

## HXI — Human Experience Interface

A WebGL visualization of the cognitive mesh rendered in React + Three.js:

- Agent nodes glow with trust-mapped colors, organized by department (PoolGroup)
- Nodes pulse with activity
- Edges represent Hebbian-weighted connections
- Real-time WebSocket streaming from the runtime
- Mission Control Kanban overlay (task lifecycle tracking)
- Build Queue dashboard with approve/reject controls
- Transporter Pattern progress visualization
- Build failure diagnostic cards with resolution options

## FastAPI Server

A REST + WebSocket API for external integrations:

- WebSocket events stream agent activity in real-time
- REST endpoints expose system state, build queue, notifications
- Powers the HXI frontend

## Source Files

| File | Purpose |
|------|---------|
| `experience/shell.py` | Async REPL (36+ commands) |
| `experience/renderer.py` | Real-time DAG execution display |
| `experience/panels.py` | Rich panel/table rendering |
| `experience/knowledge_panel.py` | Knowledge store panels |
| `experience/qa_panel.py` | QA result panels |
| `api.py` | FastAPI server + WebSocket events |
| `ui/src/components/` | React components (IntentSurface, MissionControl, SystemOrb) |
| `ui/src/store/` | Zustand state management + TypeScript types |
| `ui/src/canvas/` | WebGL cognitive mesh visualization |
