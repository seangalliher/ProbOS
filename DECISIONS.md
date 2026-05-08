# ProbOS — Architectural Decisions

Append-only log of architectural decisions made during ProbOS development. Each AD documents the reasoning behind a design choice.

See [PROGRESS.md](PROGRESS.md) for project status. See [docs/development/roadmap.md](docs/development/roadmap.md) for future plans.

**Era archives** (full historical decisions):
- [Era I — Genesis](decisions-era-1-genesis.md)
- [Era II — Emergence](decisions-era-2-emergence.md)
- [Era III — Product](decisions-era-3-product.md)
- [Era IV — Evolution](decisions-era-4-evolution.md)
- [Era V — Unification](decisions-era-5-unification.md) (Apr-May 2026; AD-440 through AD-695)

----

### AD-696 — Wave-Plan Status Field is Documentation Only (2026-05-07)

**Context.** `prompts/wave-plan.yaml` carries a `status:` field on every wave entry. Up through Wave 104 the field had drifted: 23 entries marked `pending` were already shipped per git log. Issue #425.

**Decision.** Keep the `status:` field but make its semantics explicit: the orchestrator (`scripts/wave-orchestrator.ps1`) treats `prompts/wave-orchestrator-state.json` as the source of truth — the YAML field is a courtesy for human readers. Reconciliation pass flipped 23 drifted entries (waves 78, 81-93, 95, 96, 98-104) to `done`. A header note in `wave-plan.yaml` documents the convention. No orchestrator code change — option-3 close-stage write-back was rejected as too invasive for the marginal value over manual reconciliation.

**Out of scope.** Pre-commit hook to enforce reconciliation. Removing the field entirely. Both deferred until a second drift recurrence justifies the tooling cost.

**Cross-links:** Wave 109, BF #425. AD-695 was the previous highest AD.

### AD-697 — Commercial Overlay Extension-Point Registry (2026-05-07)

**Context.** Pre-public-release goal: ship the OSS substrate cleanly while keeping a frictionless seam for a separate private commercial overlay package. The overlay should activate by `pip install` and deactivate by `pip uninstall` — no code change in either repo to flip.

**Decision.** New `probos.extensions.overlay` module with `register_finalize_hook(name, hook, *, provider="")`, `discover_extensions()` (scans `importlib.metadata.entry_points(group="probos.extensions")`), and `run_finalize_hooks(runtime, config)` invoked at the end of `startup/finalize.py`. `runtime.commercial_overlay_loaded` and `runtime.loaded_extension_providers` expose registry state. `GET /api/system/extensions` is the read-only HXI consumption surface. Failure paths log-and-degrade so a broken overlay never blocks the OSS runtime.

**Out of scope.** No actual RBAC/SSO/admin/license logic in this repo (those live in the private commercial repo and plug in via the registry). HXI badge is AD-697-1; first real seam (pre-intent authorization) is AD-698.

**Cross-links:** Wave 111, GH issue #429.

### AD-698 — Pre-Intent Authorization Hook (2026-05-07)

**Context.** AD-697 established the registry; we need a first concrete seam to validate overlay flow end-to-end before commercial work begins.

**Decision.** New `register_pre_intent_authorization_hook(name, hook, *, provider="")` registers a callable invoked by `IntentBus.broadcast` before fanout. Each hook receives the `IntentMessage` and returns `True` (allow) or `False` (deny). All registered hooks must return True for the broadcast to proceed; first denial short-circuits with a structured reason. Default-empty registry → zero overhead. Public `GET /api/system/extensions` echoes registered hook names. The OSS repo ships the seam only; no actual policy.

**Cross-links:** Wave 113, GH issue #432. Companion to AD-697-1 HXI badge (Wave 113, #431).

----

## Forcing-function deferrals (open)

| AD | Forcing function |
|----|------------------|
| AD-574c-ii | DM conversation convergence (full ProfileChatTab refactor — substrate ready) |
| AD-641g-1-1 | flip executor to `await` ANALYZE results from NATS subjects |
| AD-687 backlog | UAAA / federation knowledge sync / Kùzu migration (commercial-tagged) |
