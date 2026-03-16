# Experience Layer

The Experience layer is the user interface — the shell, visualization, and API.

## Interactive Shell

A Rich-powered async REPL with:

- Natural language input decomposed into intent DAGs
- Real-time DAG execution display with spinners
- Formatted result panels
- 16+ slash commands for introspection and control

See the [Interactive Shell guide](../getting-started/shell.md) for the full command reference.

## HXI — Human Experience Interface

A WebGL visualization of the cognitive mesh rendered in React + Three.js:

- Agent nodes glow with trust-mapped colors
- Nodes pulse with activity
- Edges represent Hebbian-weighted connections
- Real-time WebSocket streaming from the runtime

## FastAPI Server

A REST + WebSocket API for external integrations:

- WebSocket events stream agent activity in real-time
- REST endpoints expose system state
- Powers the HXI frontend

## Source Files

| File | Purpose |
|------|---------|
| `experience/shell.py` | Async REPL (20+ commands) |
| `experience/renderer.py` | Real-time DAG execution display |
| `experience/panels.py` | Rich panel/table rendering |
| `experience/knowledge_panel.py` | Knowledge store panels |
| `experience/qa_panel.py` | QA result panels |
| `api.py` | FastAPI server + WebSocket events |
