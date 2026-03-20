# Build Prompt: CI/CD Pipeline — GitHub Actions (AD-361)

## Context

ProbOS has 2358 Python tests and 34 Vitest frontend tests, but zero CI. Every
build relies on the developer running `pytest` locally. This is the single
highest-leverage infrastructure gap — CI catches regressions automatically,
validates PRs before merge, and enables confidence in the builder pipeline.

**Goal:** Add a GitHub Actions workflow that runs Python tests (pytest) and
frontend tests (vitest) on every push to `main` and every pull request. Include
a separate build-validation job for the TypeScript frontend. Keep it simple —
no linting, no deployment, no coverage upload yet. Just a green/red gate.

---

## File to Create

### `.github/workflows/ci.yml`

Create a single workflow file with two jobs: `python-tests` and `ui-tests`.

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  python-tests:
    runs-on: ubuntu-latest
    timeout-minutes: 15

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install uv
        uses: astral-sh/setup-uv@v5

      - name: Install dependencies
        run: uv sync --group dev

      - name: Run tests
        run: uv run pytest tests/ -x -q --tb=short

  ui-tests:
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: 'npm'
          cache-dependency-path: ui/package-lock.json

      - name: Install dependencies
        working-directory: ui
        run: npm ci

      - name: Run tests
        working-directory: ui
        run: npm run test

      - name: Type check & build
        working-directory: ui
        run: npm run build
```

---

## Design Decisions

### Why `uv` instead of `pip`?

The project already uses `uv` as its package manager (`uv.lock` exists). Using
`uv sync --group dev` installs from the lockfile deterministically, matching
the developer's local environment exactly. The `astral-sh/setup-uv@v5` action
is the official uv installer for GitHub Actions.

### Why `uv run pytest` instead of just `pytest`?

`uv sync` creates a virtual environment managed by uv. `uv run` executes
within that environment without needing explicit activation. This is the
idiomatic uv pattern for CI.

### Why Node 22?

LTS version. The project doesn't specify a Node version, and Node 22 is the
current LTS with the broadest compatibility.

### Why no coverage?

Coverage adds complexity (upload to Codecov/Coveralls, badge management) and
slows the initial pipeline. Add it as a follow-up once CI is green.

### Why no matrix (multiple Python versions)?

The project targets `>=3.12` only. No need to test multiple versions when
there's a single target.

### Why `--tb=short`?

In CI output, full tracebacks for 2358 tests are unreadable. Short tracebacks
show the failure location and message — enough to know what failed. Developers
reproduce locally for full traces.

### Why `-x` (fail fast)?

On CI, a first failure usually means subsequent failures are cascading. Fail
fast saves runner minutes and gives faster feedback.

### Why separate jobs (not one job with both)?

Python and Node tests are independent — they should run in parallel. A failure
in one doesn't affect the other. Separate jobs also make the PR checks UI
clearer (green Python / red UI or vice versa).

### Why `npm run build` in UI?

TypeScript type-checking happens during `tsc -b` (part of `npm run build`).
This catches type errors that the test suite might miss (tests use `jsdom` and
may not cover all components).

### What about `live_llm` tests?

The `conftest.py` auto-skips all `@pytest.mark.live_llm` tests unless
`-m live_llm` is explicitly passed. No special handling needed — these tests
will be silently skipped in CI. No LLM endpoint, no Copilot proxy, no Ollama
needed.

### What about ChromaDB?

ChromaDB uses in-process SQLite for tests (via `tmp_path` fixtures). No
external service needed. The `chromadb` Python package installs with the
standard dev dependencies.

---

## Constraints

- Create ONLY `.github/workflows/ci.yml` — do NOT modify any other files
- Do NOT add linting (ruff, flake8, eslint) — that's a separate future AD
- Do NOT add coverage upload — that's a separate future AD
- Do NOT add deployment steps — the existing `docs.yml` handles docs deployment
- Do NOT modify `pyproject.toml`, `package.json`, or any config files
- Do NOT add a matrix build for multiple Python versions
- Do NOT add environment variables or secrets — no tests need them
- Keep the workflow simple and readable — no custom actions, no complex conditionals

---

## Verification

After creating the file:

1. Validate the YAML syntax is correct
2. Verify the workflow would be triggered on push to main and on PRs to main
3. Confirm both jobs run independently (parallel, not sequential)
4. Confirm the Python job uses uv (not pip) with the lockfile
5. Confirm the UI job caches npm dependencies

The workflow will be validated live on the next push to main.
