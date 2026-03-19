# Ship Standing Orders

These orders apply to all agents aboard this ProbOS instance.

## Import Conventions

- All imports use full module paths: `from probos.experience.shell import ProbOSShell`
- Never use relative-looking paths: `from experience.shell import ...`
- Cross-cutting imports go through `probos.runtime` or `probos.types`

## Testing Standards

- Tests use pytest + pytest-asyncio
- Prefer `_Fake*` stub classes over complex Mock() chains
- Test files mirror source paths
- Every public function/method needs a test
- Run tests with: `pytest tests/ -x -q`
- UI changes require Vitest component tests
- API endpoints need at least 2 tests (happy path + error)

## Code Patterns

- Use `from __future__ import annotations` in all modules
- Use `asyncio.get_running_loop()`, never `get_event_loop()`
- Follow existing patterns -- check how similar things are done before inventing
- New destructive intents must set `requires_consensus=True`
- HTTP in designed agents must use mesh-fetch pattern, not raw httpx
- Restored designed agent code must pass CodeValidator before importlib loading

## Scope Discipline

- Do NOT expand scope beyond what was asked
- Do NOT add features, refactor adjacent code, or "improve" things not in the spec
- Do NOT add emoji to UI -- use stroke-based SVG icons (HXI Design Principle #3)
