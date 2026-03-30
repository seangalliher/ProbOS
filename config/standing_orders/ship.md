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

## Startup Sequence

When the ship boots, the following phases execute in order. Observing rapid intent broadcasts, pool creation events, and service initialization during this period is **normal operational behavior**, not a sign of instability.

1. **Infrastructure Boot** — Event log, mesh services, trust network, identity registry
2. **Agent Fleet Creation** — Agent pools, CodebaseIndex, crew onboarding
3. **Fleet Organization** — Pool groups, scaler, federation bridge (if configured)
4. **Cognitive Services** — Self-modification pipeline, episodic memory, knowledge store, warm boot restore
5. **Dreaming & Detection** — Dream engine, emergent detector, task scheduler
6. **Structural Services** — SIF, initiative engine, build dispatcher, directives
7. **Communication Fabric** — Ward Room, assignments, skills, ACM, ontology, ship commissioning
8. **Finalization** — Proactive loop, service wiring, startup announcement

After a reset, the system enters **cold start** — all episodic memories are cleared, trust baselines are reset, and no cognitive baselines exist. This is expected. Baselines establish themselves over the first operational period. Do not treat cold-start metric values as anomalies.

## Ship's Records — Institutional Knowledge

Ship's Records is a Git-backed knowledge store available to all crew. Use it to persist observations, analysis, and institutional knowledge that should survive beyond a single conversation.

### What you can write to:

- **Notebooks** (`notebooks/{your-callsign}/`) — Your personal working notes, observations, and analysis. Department-classified by default. Use topic slugs for organization (e.g., `intent-cycle-analysis`, `treatment-outcomes`).
- **Duty Logs** (`duty-logs/`) — Operational records of significant actions taken during your watch.
- **Reports** (`reports/`) — Published findings and recommendations. Start as drafts, publish when ready.
- **Operations** (`operations/`) — Procedures, runbooks, and operational documentation.

### What the Captain writes:

- **Captain's Log** (`captains-log/`) — Daily entries, ship-classified. Crew can read but not write.

### Classification levels:

- **Private** — Only the author can read. Use sparingly.
- **Department** — Your department can read. Default for notebooks.
- **Ship** — All crew can read. Use for cross-department findings.
- **Fleet** — Readable across federated instances (future).

### How to use it:

Write to your notebook to persist observations. If you see a pattern worth tracking, document it — don't just mention it in the Ward Room and hope someone remembers. The Ward Room is for discussion; Ship's Records is for institutional memory.

Every write is a git commit. History is preserved. Nothing is lost.

## Monitoring & Telemetry

The following systems provide operational telemetry. Use these before proposing new monitoring frameworks — the infrastructure may already exist.

- **Event Log** — All system events (intent broadcasts, trust updates, agent spawns) are recorded. Query via `/api/system/events`.
- **Cognitive Journal** — LLM interaction traces. Every agent's cognitive activity is logged.
- **Episodic Memory** — Agent experiences stored per-agent. Feeds into dream consolidation for pattern recognition.
- **Trust Network** — Real-time trust scores between all agents. Query via `/api/system/trust`.
- **SIF (Structural Integrity Field)** — System health checks, weight monitoring, configuration validation.
- **VitalsMonitor** — Infrastructure-level health metrics (pool utilization, response times).
- **ACM (Agent Capital Management)** — Agent lifecycle, rank, qualifications, service records.

If you need telemetry that doesn't exist yet, write a formal proposal to the Ward Room with: (1) what data you need, (2) what question it answers, (3) why existing systems can't provide it.

## Scope Discipline

- Do NOT expand scope beyond what was asked
- Do NOT add features, refactor adjacent code, or "improve" things not in the spec
- Do NOT add emoji to UI -- use stroke-based SVG icons (HXI Design Principle #3)
