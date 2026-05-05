# WAVE 65 DISPATCH — AD-635e v1 Clinical Telemetry: Shell Command

**Wave id:** 65
**Single AD:** AD-635e
**Closes:** #394
**Baseline test count:** 11368 (HEAD `3738f2e`, post-Wave-64) → expected **11386** (+18 net), window **[+15, +20]**
**HEAD at draft:** `3738f2e`, working tree clean
**Builder:** required

## Summary

AD-635 v1 (Wave 60) shipped `ClinicalTelemetryService` as an in-process query facade. AD-635b/c (Waves 62/63) added audit persistence and circuit-breaker history. AD-635d (Wave 64, last) added the four `/api/clinical/*` REST endpoints for external operator access.

What's still missing: **the Captain has no in-shell path to clinical telemetry.** Today the Captain must `curl localhost:8080/api/clinical/dreams?requester_agent_id=...` from a side terminal, where the `requester_agent_id` query parameter is gated against `_authorize_clinical_query` — and the Captain (`agent_id="captain"`) is not in `CLINICAL_ROLES = {"diagnostician", "counselor"}` (`clinical_telemetry.py:57`), so even the Captain can't read clinical data through the REST surface without impersonating Chapel or Echo.

The roadmap entry at `docs/development/roadmap.md:5964` defines the AD-635e scope literally:

> *"Shell command (`/clinical` or `/medbay`) for Captain to query clinical telemetry data directly. Captain bypasses clearance gate (Fleet Admiral authority). Depends on: AD-635 v1 (COMPLETE). Related: AD-635d (REST endpoints)."*

Verified at HEAD `3738f2e`:

```
src/probos/cognitive/clinical_telemetry.py:65    class ClinicalTelemetryService
src/probos/cognitive/clinical_telemetry.py:93    async def query_dream_history(*, requester_agent_id, limit=20) -> list[dict]
src/probos/cognitive/clinical_telemetry.py:139   async def query_agent_chain_traces(*, requester_agent_id, target_agent_id, limit=20) -> list[dict]
src/probos/cognitive/clinical_telemetry.py:206   @property def audit_log(self) -> list[dict]   (snapshot list copy)
src/probos/cognitive/clinical_telemetry.py:211   async def query_circuit_breaker_history(*, requester_agent_id, target_agent_id=None, limit=50) -> list[dict]
src/probos/cognitive/clinical_telemetry.py:284   def _authorize_clinical_query(self, agent_id) -> bool   (deny-by-default)
src/probos/cognitive/clinical_telemetry.py:340   def _record_audit(self, requester_agent_id, query_type, *, granted, result_count, target_agent_id=None) -> None
src/probos/cognitive/clinical_telemetry.py:57    CLINICAL_ROLES = frozenset({"diagnostician", "counselor"})  # captain NOT included
src/probos/experience/shell.py:52                COMMANDS dict (one-line entries, /<verb>: "Description")
src/probos/experience/shell.py:11-29             from probos.experience.commands import (commands_status, ..., commands_manifest)
src/probos/experience/shell.py:228+              handlers: dict[str, Any] = {"/status": ..., "/quit": ...}
src/probos/experience/shell.py:380+              _cmd_<name>(self, arg) backward-compat proxies (AD-519); _cmd_cache at :506, _cmd_explain at :509
src/probos/experience/commands/commands_memory.py:14   async def cmd_memory(runtime, console, args) -> None  (reference shape)
src/probos/experience/commands/__init__.py:1     "Extracted command modules for ProbOSShell."
src/probos/experience/panels.py:75               render_status_panel(status: dict[str, Any]) -> Panel  (reference shape)
src/probos/experience/panels.py:690              render_dream_panel(report: DreamReport | None) -> Panel  (reference shape)
src/probos/runtime.py                            runtime.clinical_telemetry attribute set in startup/finalize.py:598 (None when cfg.enabled=False)
ward_room_router.py:325                          is_captain = (author_id == "captain")  (canonical Captain id)
clearance_grants.py:111                          issued_by: str = "captain"   (canonical Captain id)
DECISIONS.md highest                             AD-695 — AD-635e is unique
PROGRESS.md baseline                             11368 tests collected (post-Wave-64, HEAD 3738f2e)
docs/development/roadmap.md:5964                 AD-635e *(Scoped, OSS, Issue #394)*
```

**The gap closed by AD-635e:** the Captain — who currently has zero clinical read-path because she holds neither a clinical role nor a clearance grant in the standard test fixtures — gets a `/clinical` slash command that surfaces all four data domains (dreams, chain-traces, circuit-breakers, audit) directly in the shell, with the underlying audit ring stamped `by_captain=True` so the existing observability surface still records every query.

AD-635e v1 ships:

1. **Service-side surgical extension** (`clinical_telemetry.py`): the three `query_*` methods grow ONE keyword-only parameter, `captain_override: bool = False`. When True, the clearance gate is skipped and the audit-ring entry is stamped with `by_captain=True`. Existing call sites — including the AD-635d REST router — pass nothing and continue to behave bit-for-bit identically (kwarg-only with default; not exposed via REST).
2. **Shell command module** (`commands/commands_clinical.py`, NEW): `cmd_clinical(runtime, console, args)` with five subcommands — `dreams [N]`, `traces <agent_id> [N]`, `breakers [<agent_id>] [N]`, `audit [N]`, and the bare `/clinical` (overview / help). Always invokes the service with `requester_agent_id="captain", captain_override=True`. Service-disabled (`runtime.clinical_telemetry is None`) prints a clear message and returns — same shape as `cmd_dream` when `dream_scheduler is None` (`commands_memory.py:90`).
3. **Panel renderers** (`panels.py`): four new render functions — `render_clinical_dreams_panel`, `render_clinical_traces_panel`, `render_clinical_breakers_panel`, `render_clinical_audit_panel` — each takes a list-of-dicts and returns a `rich.Panel` with a `Table` inside. Mirrors the existing `render_dream_panel`/`render_event_log_table` shape.
4. **Shell wiring** (`shell.py`): one entry in `COMMANDS`, one entry in `handlers`, one entry in the import tuple, one `_cmd_clinical` backward-compat proxy.
5. **Tests** (`test_ad635e_clinical_shell_command.py`, NEW): 18 tests across four test classes (service captain-override, command dispatch, command output, panel rendering).

No EventTypes added. No mutation of `CircuitBreakerHistoryStore`, `ClinicalAuditStore`, `CognitiveCircuitBreaker`, `ClinicalTelemetryConfig`, `ProactiveCognitiveLoop`, `_authorize_clinical_query`, `routers/clinical.py`, `api.py`, or any startup wiring. The AD-635d REST tests must continue to pass without modification because the new kwarg defaults to False — REST code does not pass it.

**Deferred at the prompt level:**
- AD-635e-1 — `/medbay` alias. The roadmap line says `/clinical` *or* `/medbay`; v1 ships one canonical verb. Alias added in a follow-up if user feedback warrants.
- AD-635e-2 — `--since <duration>` time-range filter on dreams / traces / breakers / audit. v1 takes `limit` only (matches AD-635d-3 deferral on REST).
- AD-635e-3 — non-Captain shell users. ProbOS shell currently has one user (the Captain — see `commands_clearance.py`, `clearance_grants.py:111`, `ward_room_router.py:325`). When multi-user shell auth lands, the `/clinical` command will need a real identity check. AD-635e-3 covers that.
- AD-635e-4 — fleet-wide breaker view at the REST layer. `/clinical breakers` (no agent_id) already calls `query_circuit_breaker_history(target_agent_id=None)` in v1; the REST sibling deferral is AD-635d-2.
- AD-635e-5 — *(Commercial)* tenant-scoped clinical shell command (per-mesh runtime resolver behind a tenant prefix). The OSS shell command remains tenant-agnostic; the seam is the runtime injection point.
- AD-635e-6 — pagination cursors on the audit subcommand. v1 server-side slices the in-memory ring as `audit_log[-limit:]` (mirrors AD-635d-4).
- AD-635e-7 — interactive subcommand tab-completion. v1 uses positional argument parsing (`args.split()`) — keystroke completion is a separate UX AD.

## Architect calls (Decision Log)

- **DLog #1 — Captain bypass via keyword-only `captain_override: bool = False`, NOT via `_authorize_clinical_query` patch.** Two patterns were considered: (a) special-case `agent_id == "captain"` inside `_authorize_clinical_query`, or (b) a kwarg-only `captain_override` on each query method. Pattern (a) opens the AD-635d REST surface to a `?requester_agent_id=captain` backdoor — every unauthenticated REST caller could pass that string and bypass the gate. Pattern (b) is invisible to REST (the router doesn't forward the kwarg) and audit-trail-stamped (`by_captain=True`). v1 ships pattern (b). Tests #1, #4, #7 lock the bypass; #2, #5, #8 lock the audit-ring stamp.

- **DLog #2 — `_authorize_clinical_query` is NOT modified.** The function's contract — "deny by default, return True only when caller holds a clinical role AND a qualifying tier" — is preserved bit-for-bit. The Captain bypass is an *additional* fast-path branch BEFORE the gate is consulted, not a modification of the gate itself. This keeps the AD-635 v1 / AD-635b / AD-635c authorization tests passing without touching them. SOLID-D: bypass is opt-in via parameter, not patched into the authorization primitive.

- **DLog #3 — REST router (`routers/clinical.py`) is NOT modified.** The router calls `service.query_*(requester_agent_id=..., limit=..., target_agent_id=...)` and never knows about `captain_override`. The kwarg defaults to False; REST callers cannot reach it. Verified at `routers/clinical.py:69-73`, `:97-101`, `:124-128`. The 14 AD-635d REST tests must pass unchanged after this AD lands. Hard-stop condition #2.

- **DLog #4 — Audit ring schema additive: `by_captain` is OPTIONAL field, only present when `captain_override=True`.** `_record_audit` ALREADY uses optional-field-on-condition shape (`target_agent_id` is only added when not None — see `clinical_telemetry.py:357-358`). The new `by_captain` field follows the same pattern: only inserted when `True`. Existing audit-ring tests that check exact entry shape continue to pass because the field is absent on non-captain calls. Tests #2, #5, #8 assert the field's presence on captain calls; existing AD-635 tests already lock its absence on non-captain calls (because they never set the new param).

- **DLog #5 — Service-disabled (cfg.enabled=False) shell behavior: print "[yellow]Clinical telemetry is not enabled.[/yellow]" and return.** Mirrors `commands_memory.py:90` (`cmd_dream` when `dream_scheduler is None`) and `commands_memory.py:32` (`cmd_history` when `episodic_memory is None`). Default ProbOS config has `clinical_telemetry.enabled=False`, so this is the most common path for first-time users; the message must be discoverable and actionable. Test #11 locks the message text.

- **DLog #6 — Subcommand surface: `dreams`, `traces`, `breakers`, `audit`, plus bare `/clinical` overview.** The four data-domain verbs map 1:1 to the four AD-635d REST endpoints (`/api/clinical/dreams`, `/chain-traces/{id}`, `/circuit-breakers/{id}`, `/audit`). Bare `/clinical` prints a help panel listing the subcommands with one-line descriptions and example invocations (mirrors `cmd_procedure` in `commands_procedure.py` when invoked with no args). Unknown subcommand prints a usage error and the help panel. Tests #12, #13, #14 lock dispatch.

- **DLog #7 — `breakers` accepts an optional `<agent_id>`, mirroring `query_circuit_breaker_history(target_agent_id: str | None)`.** `/clinical breakers` (no id) → fleet-wide. `/clinical breakers <agent_id>` → per-agent. This diverges from the AD-635d REST sibling (which is per-agent only and defers fleet-wide to AD-635d-2) — that's intentional: the in-process service ALREADY supports the fleet-wide path, and the shell is in-process; no REST-shaped restriction applies. Test #15 locks the fleet-wide path; test #16 locks the per-agent path.

- **DLog #8 — `limit` parsing: positional integer, default per-domain (20/20/50/200), no upper cap at the shell layer.** The service-side ceilings (`max(0, int(limit))`) are already in place at `clinical_telemetry.py:118, 184, 246`. The shell parses the trailing positional arg as int (rejecting non-int with a usage error). No `min(...)` clamp at the shell — the service decides. Defaults match the underlying methods (dreams/traces=20, breakers=50, audit=200 per DLog #11). Test #17 locks the int-parse error path.

- **DLog #9 — Argument parsing: `args.split()` with a small dispatch table.** No `argparse`, no `click`. The existing shell-command modules (`commands_memory`, `commands_directives`, `commands_procedure`) all use `args.split()` or `args.split(maxsplit=N)` for sub-verb dispatch. AD-635e follows precedent — adding `argparse` here would diverge from the established shell idiom. The dispatch is a `match`/`if-elif` over the first token.

- **DLog #10 — Audit subcommand bypasses the service `query_*` methods entirely.** `audit_log` is a public property at `clinical_telemetry.py:206-208` — no clearance gate, no captain-override needed. The shell reads `service.audit_log[-limit:]` directly (slice mirrors AD-635d's REST endpoint at `routers/clinical.py:148+` per the audit-shape DLog in the AD-635d dispatch). Test #10 locks the slice direction; test #18 locks the empty-ring case.

- **DLog #11 — Audit subcommand default limit = 200.** Mirrors AD-635d's audit endpoint default cap of 200. Larger than dreams/traces (20) because audit entries are smaller and the default ring size is 1000 — showing 200 fits comfortably in a terminal without paging.

- **DLog #12 — Captain identity is the literal string `"captain"`.** The codebase canonicalizes Captain via lowercase string comparison throughout: `ward_room_router.py:325` (`is_captain = (author_id == "captain")`), `clearance_grants.py:111` (`issued_by: str = "captain"` default), `acm.py:250` (`initiated_by: str = "captain"` default), `assignment.py:33` (`created_by: str` doc says "captain" or agent_id). The shell command hardcodes `requester_agent_id="captain"` for every call; this is the existing canonical Captain identifier and matches every other Captain-action surface. AD-635e-3 (multi-user shell) is the forcing function for replacing the hardcode.

- **DLog #13 — Panel rendering: four small renderers, each takes `list[dict]` and returns `rich.Panel`.** Mirrors `render_dream_panel(report: DreamReport | None) -> Panel` at `panels.py:690+`. Every clinical panel: `Panel(Table(...))` with title `"Clinical: <Domain>"`, border style `"cyan"` (matches workflow-cache border) for query views, `"magenta"` (matches dream-panel border) for dreams. Empty-list path renders "[dim]No <domain> entries.[/dim]" inside the panel. Tests #19-#21 lock empty-state rendering for three of four domains (audit empty-state covered by test #18).

- **DLog #14 — Shell command registration: 4 SEARCH/REPLACE blocks in `shell.py`.** (1) Add `commands_clinical` to the `from probos.experience.commands import (...)` tuple at `shell.py:11-29`. (2) Add `"/clinical": "Show clinical telemetry (..)"` in `COMMANDS` dict at `shell.py:52-107`. (3) Add `"/clinical": lambda: commands_clinical.cmd_clinical(rt, con, arg)` in `handlers` dict at `shell.py:228+`. (4) Add `async def _cmd_clinical(self, arg: str) -> None` backward-compat proxy in the AD-519 proxy block (insert after `_cmd_cache` at `shell.py:506`, before `_cmd_explain` at `:509`). All four blocks have at least 3 lines of context BEFORE and AFTER. No mutation of the dispatch logic itself.

- **DLog #15 — Wave-10 reframe NOT triggered.** The producer-side change (3 `query_*` method signatures + `_record_audit` shape) is small and additive — kwarg-only default-False, optional audit field. Existing call sites do not need to be modified (verified at `routers/clinical.py:69-73`, `:97-101`, `:124-128`; the only in-process callers are the REST router, which doesn't pass the new param, and the test files for AD-635/635b/635c, which also don't pass it). Single Builder cycle is tractable. The shell side is one new file plus four small edits in two existing files.

- **DLog #16 — Phantom-API pre-check status.** Same recurring blocker as Waves 52-64 — `scripts/phantom-api-precheck.ps1` has a pre-existing PowerShell parser error (logged in user-memory). Manual verify-first pass performed at draft (16 verifying greps in this dispatch + the prompt's "Verified Against Codebase" table — all confirmed against HEAD `3738f2e`). Net-new symbols are intra-prompt-introduction (`commands_clinical.cmd_clinical`; the four `render_clinical_*_panel` functions; the `captain_override` kwarg; the `by_captain` audit field; the `_cmd_clinical` proxy). Same FP class as Waves 27-64.

- **DLog #17 — Test count target +18 (within window [+15, +20]).** Service captain-override path × 3 query methods × (bypass-grants + audit-stamp) = 6; subcommand dispatch (registered, listed in /help, unknown subcommand error, service-disabled message) = 4; subcommand output rendering (dreams happy + empty, traces happy + missing-arg, breakers fleet + per-agent, audit happy + empty) = 8 → ~18. The +15 floor is the no-coverage-loss minimum; the +20 ceiling absorbs two more boundary tests if the Builder discovers a corner. If post-build delta is <+15 or >+20, hard-stop and triage before commit.

- **DLog #18 — Commercial-leak audit: clean.** AD-635e is OSS plumbing — one new shell command file, four panel renderers, additive `captain_override` kwarg on three service methods, four small edits in `shell.py`, eighteen tests. The AD-635e-5 *(Commercial)* deferral names tenant-scoped variants; the OSS shell command remains tenant-agnostic. The dispatch contains zero pricing, revenue model, customer counts, professional-services positioning, competitive analysis, or GTM language. Commercial-leak audit: **clean.**

## Builder workflow (standard)

1. Pre-flight gate: `pytest tests/ -q -n 4 --dist=loadfile` → confirm 11368 collected at HEAD `3738f2e`.
2. Apply Section 0 (`clinical_telemetry.py` — 4 SEARCH/REPLACE blocks: 3 query methods + `_record_audit`).
3. Run `pytest tests/test_ad635*.py -n 0` to confirm AD-635 / AD-635b / AD-635c / AD-635d tests still pass with the new kwarg defaulting to False.
4. Apply Section 1 (`panels.py` — append 4 new render functions at end of file).
5. Apply Section 2 (NEW `commands_clinical.py`).
6. Apply Section 3 (`shell.py` — 4 SEARCH/REPLACE blocks).
7. Run `python -c "from probos.experience.commands import commands_clinical; print(commands_clinical.cmd_clinical)"` to confirm import path.
8. Run `python -c "from probos.experience.shell import ProbOSShell; assert '/clinical' in ProbOSShell.COMMANDS"` to confirm registration.
9. Apply Section 4 (NEW test file). Add the 18 tests one at a time; confirm each passes before adding the next.
10. Final gate: `pytest tests/ -q -n 4 --dist=loadfile` → expect 11386 (+18 net target; window [+15, +20] = [11383, 11388]).
11. Update tracking: `PROGRESS.md` (append CLOSED entry), `docs/development/roadmap.md:5964` (flip `*(Scoped, OSS, Issue #394)*` → `*(complete)*`), `prompts/wave-plan.yaml` (id 65 → status: done).

## Hard-stop conditions

1. Test count delta lands outside [+15, +20]. → Triage which test class over- or under-shot.
2. Existing AD-635 / AD-635b / AD-635c / AD-635d tests fail. → The `captain_override` kwarg or `by_captain` audit field is breaking the existing audit-shape contract. Hard-stop and re-read DLog #2 / DLog #4.
3. Real working-tree changes appear in source files NOT named in this dispatch (`src/probos/cognitive/clinical_telemetry.py`, `src/probos/experience/panels.py`, `src/probos/experience/commands/commands_clinical.py`, `src/probos/experience/shell.py`, `tests/test_ad635e_clinical_shell_command.py`, plus tracking files). → Hard stop, surface to Captain.
4. Any test or any source file inserts a special-case branch in `_authorize_clinical_query`. → That's the rejected pattern (DLog #1). Hard-stop.
5. Any test passes `captain_override=True` through the AD-635d REST router. → REST is a backdoor surface (DLog #3); hard-stop.
6. Any test inserts a runtime fixture that boots a real `ProbOSRuntime`. → Use `MagicMock(spec=ProbOSRuntime)` per `tests/test_commands_memory.py:25-34` precedent. Full-runtime fixtures explode wave-gate runtime budget. Hard-stop.

## Tracking

| Tracker | Update |
|---|---|
| `PROGRESS.md` | Append `AD-635e v1 CLOSED.` paragraph (one-paragraph CLOSED entry mirroring AD-635d). |
| `docs/development/roadmap.md:5964` | Flip `*(Scoped, OSS, Issue #394)*` to `*(complete)*`. |
| `DECISIONS.md` | NOT modified (textbook shell-command sibling pattern; `commands_clinical.py` mirrors `commands_memory.py` shape). |
| `prompts/wave-plan.yaml` (id: 65) | Set `status: done` post-archive. |
| GH issue #394 | Closed by Captain post-merge with commit hash. |
