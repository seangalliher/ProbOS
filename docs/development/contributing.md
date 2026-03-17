# Contributing

ProbOS is open source under the Apache License 2.0. Contributions are welcome!

## Getting Started

```bash
# Clone and install
git clone https://github.com/seangalliher/ProbOS.git
cd ProbOS
uv sync

# Run the test suite
uv run pytest tests/ -v
```

## Development Workflow

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run the test suite — all tests must pass
5. Submit a pull request

## Code Style

- Python 3.12+ with type annotations
- Async-first — most interfaces are `async`
- Pydantic for configuration and data models
- `pytest` + `pytest-asyncio` for testing

## Architecture Guidelines

- **Three capability tiers: Agents, Tools, Skills.** Agents are the unit of behavior (crew members who think and decide). Tools are the unit of action (instruments like tricorders — typed callables shared across agents). Skills are the unit of knowledge (data access attached to agents). Rule of thumb: if someone would ask for it, it's an agent. If it performs a specific action any agent might need, it's a tool. If an agent needs reference data to do its job, it's a skill.
- **Self-describing agents.** Every agent declares `IntentDescriptor` metadata so the system discovers it automatically.
- **Consensus for side effects.** Any operation that modifies external state must go through the consensus layer.
- **Test everything.** Each layer has comprehensive tests. New code should maintain coverage.

## Dependencies

| Package | Purpose |
|---------|---------|
| [pydantic](https://docs.pydantic.dev/) >=2.0 | Configuration validation |
| [pyyaml](https://pyyaml.org/) >=6.0 | YAML config loading |
| [aiosqlite](https://github.com/omnilib/aiosqlite) >=0.19 | Async SQLite |
| [rich](https://rich.readthedocs.io/) >=13.0 | Terminal UI |
| [httpx](https://www.python-httpx.org/) >=0.27 | HTTP client |
| [pyzmq](https://pyzmq.readthedocs.io/) >=27.1 | ZeroMQ transport |
| [chromadb](https://docs.trychroma.com/) >=1.0 | Vector database |
| [fastapi](https://fastapi.tiangolo.com/) >=0.115 | API server |
| [uvicorn](https://www.uvicorn.org/) >=0.34 | ASGI server |

Dev: pytest >=8.0, pytest-asyncio >=0.23, vitest (UI)
