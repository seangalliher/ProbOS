# WAVE 55 DISPATCH — AD-456b v1 Security Infrastructure: Runtime Sandboxing

**Wave id:** 55
**Single AD:** AD-456b
**Closes:** #398
**Baseline test count:** 11227 (Wave 54, commit `343df76`) → expected **11239** (+12 net), ceiling **+13**
**HEAD at draft:** post-Wave-54 (`343df76`, working tree clean)

## Summary

AD-456 v1 (Wave 7) shipped Secrets / Egress / Audit and wholesale-deferred Runtime Sandboxing to AD-456b. AD-456b v1 closes the deferred follow-up by shipping two complementary OSS pieces:

1. **`RuntimeSandbox`** — bounded-execution surface with wall-clock timeout (asyncio.wait_for), best-effort peak-memory tracking (tracemalloc), and consultation-style capability whitelist (contextvars). Public contract `await execute(coro_factory, *, limits, capabilities) → SandboxOutcome`. Forward-compatible with AD-456b-1 OS-level isolation (the body swaps; the signature does not).

2. **`HttpFetchAgent` ↔ `EgressPolicy` active enforcement** — closes the AD-456 review contract (`prompts/Reviews/archive/ad-456-security-infrastructure-review.md:80,263`). New `HttpFetchAgent._egress_policy` ClassVar + `set_egress_policy()` classmethod mirror the existing `_profile_store` / `set_profile_store` pattern at `agents/http_fetch.py:84-89`. `_validate_url()` consults the policy as a final defense-in-depth check after the existing scheme/host/private-IP guards. Gated on a new `egress_active_enforcement: bool = False` config flag — default False preserves AD-456 v1 consultation-only behavior on existing deployments; Captain flips to True at upgrade time.

5 sections + Section 0 EventTypes, 1 new module file (`security/runtime_sandbox.py`, ~225 lines), 1 new test file (12 tests), 4 source-edit files (`events.py`, `config.py`, `agents/http_fetch.py`, `startup/finalize.py`).

True OS-level process isolation (subprocess + Windows JobObject / Linux cgroups / seccomp / containers), graduated-trust → capability-set policy, AD-660b diagnostic-action consumer wiring, and container-based sandboxing are explicitly deferred (DLogs #1 / #4 / #6 / #8). The v1 public contract is the seam where downstream consumers and commercial overlays plug in.

## Architect calls (Decision Log)

- **DLog #1 — In-process v1; OS-isolation deferred to AD-456b-1 (Wave-10 reframe).** Pre-flight verified `psutil` is NOT installed (`python -c "import psutil"` → `ModuleNotFoundError`) and the `resource` stdlib module is unavailable on Windows. True OS isolation needs `psutil` + cross-platform shim (Windows JobObject, Linux cgroups). Wave-10 reframe rule triggers: ship the public contract (`RuntimeSandbox.execute(coro_factory, *, limits, capabilities) → SandboxOutcome`) in v1 with an in-process body; AD-456b-1 swaps the body without signature change. Forcing function: ship v1, Captain validates that in-process timeout + tracemalloc covers ≥80% of intended use cases (most concretely AD-660b diagnostic actions), then OS-isolation belt becomes specifiable as additive plumbing.

- **DLog #2 — `coro_factory` zero-arg callable, NOT a coroutine.** If `execute` accepted `Awaitable[Any]` directly and short-circuited (e.g., on a fast pre-check), the un-awaited coroutine would emit `RuntimeWarning: coroutine '...' was never awaited`. Factory shape (`Callable[[], Awaitable[Any]]`) makes the construction explicit and lazy. Caller pattern: `await sandbox.execute(lambda: do_thing(arg))` or `await sandbox.execute(do_thing_no_args)`. AD-456b-3 (AD-660b diagnostic-action wiring) uses `lambda: action.execute()` — clean.

- **DLog #3 — `tracemalloc` for memory tracking, not `psutil`.** Cross-platform stdlib (Python 3.4+). Limitation: `tracemalloc.get_traced_memory()` only counts Python-allocated bytes, not C-extension or native-library allocations. Best-effort is the v1 contract (acceptable per "not a security boundary" framing — this is observability + soft enforcement, not adversarial isolation). The `tracemalloc_started_here` guard ensures we don't stop tracing started by another caller (tests, profilers).

- **DLog #4 — Capability consultation, NOT enforcement.** v1 ships `check_capability` / `require_capability` as voluntary calls from sandboxed code via a `contextvars.ContextVar`. Instruction-level interception (e.g., `audithook` blocking arbitrary syscalls) is a Wave 7+ feature class with significant complexity and false-positive surface. Forcing function: AD-456b-2 layers a trust-band → capability-set policy on top of the consultation primitive once production diagnostic-action paths surface concrete capability names (e.g., `net.read`, `fs.write`, `subprocess.spawn`).

- **DLog #5 — `egress_active_enforcement: bool = False` default (anti-pattern #14 + #3 enforcement).** Default-True on a transitional flag is breaking-change-on-first-commit. Existing deployments may have allowlists that don't yet cover their full traffic pattern (AD-456 v1 was advertised as consultation-only, so operators may not have reviewed). Default False; Captain explicitly flips at upgrade time. AD-456b-7 will flip the default to True once fleet-wide allowlist coverage is verified.

- **DLog #6 — AD-660b diagnostic-action wiring is AD-456b-3, NOT this wave.** User explicitly noted: "downstream consumers exist but DO NOT wire them in this wave." v1 ships `runtime.runtime_sandbox` as a public attribute; AD-456b-3 wires `DiagnosticAction.execute()` body to route through it. Cross-AD orthogonality preserved: AD-456b ships the API surface; AD-660b ships the consumer body; AD-456b-3 plugs them together.

- **DLog #7 — `EgressPolicy._emit_blocked` already fires `EGRESS_BLOCKED` on the deny path** (verified at `egress.py:135-149`). v1 active enforcement just adds a real consumer of the existing emit. NO double-emit needed in HttpFetchAgent's `_validate_url`. New `SANDBOX_LIMIT_EXCEEDED` and `SANDBOX_CAPABILITY_DENIED` are RuntimeSandbox-only.

- **DLog #8 — `RedTeamAgent` egress consultation deferred to AD-456b-4.** AD-456 review noted RedTeamAgent as a future consumer; not on the critical path for the production HTTP fetch path. Scope minimization: ship the highest-traffic consumer (HttpFetchAgent) in v1; layer RedTeamAgent in a follow-up.

- **DLog #9 — Defense-in-depth ordering: egress check runs AFTER scheme/host/private-IP guards.** Existing SSRF protection (`_validate_url` lines 144-178) is the substrate layer; egress policy is the policy layer. If a URL fails the SSRF guard, no policy check is needed. If it passes the SSRF guard, the egress policy is the second gate. Tests #10 and #11 lock this ordering.

- **DLog #10 — `HttpFetchAgent._egress_policy` is `ClassVar`, mirroring `_profile_store`** (`agents/http_fetch.py:84`). All pool members share the policy reference. Test fixtures call `set_egress_policy(None)` in `try/finally` to prevent ClassVar leakage across tests (test #11 explicitly locks the default-None contract).

- **DLog #11 — No new pool, agent, module, journal table, or EventType beyond the two listed.** No new Pydantic config beyond `SecurityInfraConfig` field additions. Strictly additive: every existing AD-456 / AD-680 / AD-382 / HttpFetchAgent contract preserved. Backwards compatibility lock: 16 existing AD-456 tests continue to pass without modification.

- **DLog #12 — Phantom-API pre-check status.** Same recurring blocker as Waves 52, 53, 54 — `scripts/phantom-api-precheck.ps1` has a pre-existing PowerShell parser error. Manual verify-first pass performed at draft (16 verifying greps in the prompt's "Verified Against Codebase" table — all confirmed against HEAD `343df76`). Net-new symbols (15 listed, all greenfield: `RuntimeSandbox`, `SandboxLimits`, `SandboxOutcome`, `CapabilityDenied`, `check_capability`, `require_capability`, `runtime.runtime_sandbox`, `HttpFetchAgent._egress_policy`, `HttpFetchAgent.set_egress_policy`, `SANDBOX_LIMIT_EXCEEDED`, `SANDBOX_CAPABILITY_DENIED`, `sandbox_enabled`, `sandbox_default_wall_timeout_seconds`, `sandbox_default_memory_peak_mb`, `egress_active_enforcement`) are intra-prompt-introduction (Sections 0 / 1 / 2 / 3a / 4 SEARCH/REPLACE). Same FP class as Waves 27-54.

- **DLog #13 — Test count target +12, ceiling +13.** 12 explicit new tests in Section 5. The +13 ceiling allows one boundary discovery during build (precedent: Waves 30, 39, 41, 42, 53 all over-shipped by 1+ via fixture splits). If post-build delta is <+12 or >+13, hard-stop and triage before commit.

- **DLog #14 — Commercial-leak audit: clean.** AD-456b is OSS plumbing — bounded-execution surface + EgressPolicy active enforcement. Container-based sandbox / namespace isolation / eBPF policy enforcement is tagged `*(Commercial)*` in the deferral list (AD-456b-4) — the tag describes what plugs in (extension point on the `RuntimeSandbox.execute` contract); pricing, RBAC, SSO, enterprise dashboards belong in the private commercial repo. Zero references to pricing, tier strategy, customer counts, or competitive positioning.

## Highest-risk constraints (re-read before each Section)

1. **Section 2 (`runtime_sandbox.py`) `tracemalloc_started_here` guard.** If sandbox starts `tracemalloc` and the test runner already had it running (e.g., via `pytest-tracemalloc`), `finally` MUST NOT call `tracemalloc.stop()`. The boolean guard handles this. Verify: search for `tracemalloc.is_tracing()` and `tracemalloc_started_here` in the new file; they are paired.

2. **Section 2 `_active_sandbox_capabilities.reset(token)` in `finally`.** Capability context MUST reset on every exit path (success, timeout, capability-denied, exception). Test #8 (`test_capability_context_is_reset_after_execute`) locks this — runs a sandbox with `capabilities={"net.read"}`, then runs a second sandbox without capabilities and asserts `check_capability("net.read") is False` inside the second sandbox.

3. **Section 2 memory-test sizing (test #3).** `bytearray(2 * 1024 * 1024)` allocates 2 MB; cap is `0.001` MB (≈1 KB). Margin is ~2000x — robust against `tracemalloc` granularity and per-platform overhead. If test #3 flakes, increase the bytearray size, never lower the cap below `0.001`.

4. **Section 3a ClassVar shape MUST mirror `_profile_store`.** Test fixtures rely on `HttpFetchAgent._egress_policy` being a class-level ClassVar (test #11 reads `HttpFetchAgent._egress_policy`). If implementer accidentally makes it an instance attribute or a module-level singleton, test #11 fails.

5. **Section 3b egress check ordering.** New consultation block runs AFTER the existing private-IP loop; if an implementer accidentally places it before, SSRF protection becomes secondary to policy — wrong defense-in-depth ordering and a regression vs AD-456 v1 invariants. SEARCH locks lines 170-178 (the trailing `for family ...` loop + `return None`) so REPLACE is unambiguous.

6. **Section 3b `try/except Exception` log-and-degrade.** `EgressPolicy.is_allowed` should never raise (verified at `egress.py:67-70`), but if a future denylist regex or operator-supplied custom policy raises, the `try/except → logger.warning → allow request` path follows tier-2 (log-and-degrade — visible degradation acceptable). NEVER allow an egress policy crash to break HTTP fetch.

7. **Section 4 finalize wiring ORDER.** New RuntimeSandbox + `HttpFetchAgent.set_egress_policy` blocks insert AFTER the AD-456 AuditLog block (lines 1281-1289) and BEFORE the AD-528 `ground_truth_verifier` block (line 1291). SEARCH locks the entire AuditLog block (5 lines + `else: runtime.audit_log = None`) so REPLACE is unambiguous. If new blocks land BEFORE `audit_log` wiring, the dependency on `runtime.egress_policy` (created in the AD-456 EgressPolicy block at line 1268-1279, BEFORE the AuditLog block) is satisfied — but ordering matters for log readability.

8. **Section 4 conditional `HttpFetchAgent.set_egress_policy` call.** MUST check both `config.security_infra.egress_active_enforcement` AND `getattr(runtime, "egress_policy", None) is not None`. If `egress_enabled=False`, `runtime.egress_policy = None` (line 1279) — calling `set_egress_policy(None)` would do nothing harmful, but the `getattr` check is defense-in-depth and matches AD-456 finalize patterns.

9. **Tests #10 + #11 + #12 use `set_egress_policy(None)` in `try/finally` to prevent ClassVar leakage.** ClassVar mutations persist across tests — pytest-xdist parallel runs could see flaky failures if one test sets a policy and another reads `HttpFetchAgent._egress_policy` without isolation. The fixture pattern is explicit in the test file. Builder must NOT remove the `try/finally` blocks.

10. **Do NOT touch `cognitive/sandbox.py:SandboxRunner`** — orthogonal subsystem (self-mod correctness harness).

11. **Do NOT touch `agents/red_team.py`** — RedTeamAgent egress is AD-456b-4.

12. **Do NOT touch `EgressPolicy`** (`security/egress.py`) — `_emit_blocked` already fires `EGRESS_BLOCKED`; no double-emit needed.

13. **Do NOT touch `runtime.egress_policy` / `runtime.audit_log` / `runtime.credential_store` wiring** — AD-456 contracts preserved.

14. **Do NOT touch any AD-660b diagnostic-action code.** v1 ships `runtime.runtime_sandbox` as a public attribute; AD-660b consumer wiring is AD-456b-3.

15. **Do NOT add a new EventType beyond `SANDBOX_LIMIT_EXCEEDED` and `SANDBOX_CAPABILITY_DENIED`.**

16. **Do NOT add a new pool, agent, module beyond `security/runtime_sandbox.py`, or Pydantic config class.**

## Phantom-API pre-check result

Auto-run blocked by pre-existing script parser error (DLog #12, recurring from Waves 52-54). Manual verify-first pass: 16 verifying greps in the prompt's "Verified Against Codebase" table all hit at HEAD `343df76`. Net-new symbols (15 listed in DLog #12) are intra-prompt-introduction (Sections 0 / 1 / 2 / 3a / 4 SEARCH/REPLACE). Same FP class as Waves 27-54.

## Pre-flight gate

```powershell
git pull
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile 2>&1 | Select-Object -Last 5
```

Expected baseline: **11227 passed**.

## Build groups

Single group, sequential:

1. Section 0 — `events.py` adds 2 new EventTypes (insert adjacent to AD-456 group)
2. Section 1 — `config.py` `SecurityInfraConfig` adds 4 new fields (sandbox triplet + `egress_active_enforcement`)
3. Section 2 — `security/runtime_sandbox.py` NEW (~225 lines)
4. Section 3a — `agents/http_fetch.py` adds `_egress_policy` ClassVar + `set_egress_policy` classmethod
5. Section 3b — `agents/http_fetch.py` `_validate_url` adds egress consultation block
6. Section 4 — `startup/finalize.py` wires `runtime.runtime_sandbox` + conditional `HttpFetchAgent.set_egress_policy`
7. Section 5 — `tests/test_ad456b_runtime_sandboxing.py` NEW (12 tests)
8. Run focused gate: `pytest tests/test_ad456b_runtime_sandboxing.py tests/test_ad456_security_infrastructure.py -v -n 0`
9. Run full gate: `pytest tests/ -q -n 8 --dist=loadfile`

## Hard-stop conditions

- An existing test in `test_ad456_security_infrastructure.py` regresses after Sections 0-4 land. The change is strictly additive — `SecurityInfraConfig` gains 4 new fields with defaults; no existing field is renamed or removed. `runtime.egress_policy` / `runtime.audit_log` / `runtime.credential_store` wiring is unchanged. If a regression appears, most likely cause is Section 4 ordering wrong (RuntimeSandbox block landed BEFORE `runtime.egress_policy` assignment, breaking the conditional `set_egress_policy` call).

- An existing HttpFetchAgent test regresses (tests/test_http_fetch_agent.py or similar). New `_egress_policy` ClassVar defaults to `None`; new `_validate_url` block is no-op when `policy is None`. If a regression appears, check that the SEARCH/REPLACE in Section 3b preserved indentation EXACTLY (the new block sits inside the method, after the `for family ... return f"Blocked private/reserved IP: {ip}"` loop and before the final `return None`).

- Test #3 (memory peak detection) flakes in xdist due to per-worker tracemalloc state. Re-run at `-n 0` first per `.github/copilot-instructions.md` triage. If still flakes, increase `bytearray(2 * 1024 * 1024)` to `bytearray(8 * 1024 * 1024)` — never lower the cap below `0.001` MB.

- Test #2 (wall timeout) flakes on slow runners due to `asyncio.sleep(2.0) → wait_for(..., timeout=0.05)` margin. The 40x margin is robust; if it still flakes, inflate the sleep to `5.0` and keep the timeout at `0.05`.

- Tests #10 / #11 / #12 ClassVar leakage across xdist workers. The `try/finally` in each test calls `set_egress_policy(None)` on exit. If a test fails because `_egress_policy` is unexpectedly non-None on entry, another test leaked — find the leaker and add the missing `try/finally`.

- Phantom-API pre-check script remains broken (DLog #12) — non-blocker for THIS wave; cleanup AD remains pending.

- Test count delta < +12 OR > +13 — investigate before commit (drift signal).

- A test fails under `-n 8` parallel xdist but passes serial (`-n 0`). Standard triage: re-run failing file at `-n 0` per `.github/copilot-instructions.md`. If parallel-only, mark `xfail(reason="env-dependent under xdist; AD-682")` rather than expanding the assertion window.

## Tracker updates (post-build, single commit per ask)

- `PROGRESS.md` — prepend AD-456b CLOSED entry.
- `docs/development/roadmap.md` — flip AD-456b row to ✅ shipped under the AD-456 cluster; add AD-456b-1 (OS-level isolation), AD-456b-2 (trust-band → capability-set policy), AD-456b-3 (AD-660b diagnostic-action wiring), AD-456b-4 *(Commercial)* (container/namespace/eBPF), AD-456b-5 (egress-check reordering), AD-456b-6 (HXI allowlist hot-reload), AD-456b-7 (`egress_active_enforcement` default flip) deferral entries with explicit forcing functions.
- `DECISIONS.md` — prepend AD-456b entry at top of Era V.

## Issues to close

GitHub MCP `issue_write` close on **#398** (expect EMU 403 same as Waves 31-54; Captain closes manually).

## Commit message

`AD-456b: Security infrastructure runtime sandboxing v1 (RuntimeSandbox + HttpFetchAgent egress active enforcement) (+12 tests)`

## Concerns for orchestrator at gate_1

1. **Phantom-API pre-check script is broken** (DLog #12, recurring from Waves 52-54). Builder cannot run the standard pre-check; manual verify-first pass already done at draft (16 verifying greps). Forcing function for a tooling-hygiene-AD logged but NOT scoped into this wave.

2. **`psutil` is NOT installed** in the venv — confirmed pre-draft via `python -c "import psutil"` → `ModuleNotFoundError`. v1 RuntimeSandbox body uses ONLY stdlib (`asyncio`, `tracemalloc`, `time`, `contextvars`). Builder must NOT add `import psutil` to `runtime_sandbox.py` — that would force adding a runtime dep, which is AD-456b-1 territory.

3. **`resource` stdlib module is unavailable on Windows** — confirmed pre-draft. POSIX-only. Builder must NOT use `resource.setrlimit` — same reason.

4. **Test count baseline asserted at 11227.** Wave-54 dispatch projected exactly 11220 + 6 = 11226; user's actual baseline post-Wave-54 is 11227 (commit `343df76`, +1 over projection — within Wave 54's +6/+7 ceiling). If pre-flight returns ≠ 11227, hard-stop and triage before dispatching Builder.

5. **Wave 55 is single-AD, sequential, 6 sections + 7 distinct edit points across 4 files + 1 new module file (~225 lines) + 1 new test file (~310 lines, 12 tests).** Comparable scope to Wave 53 (single AD + new module file). Builder envelope: tighter than Waves 50-52, similar to 53.

6. **Strictly additive — zero existing-symbol modifications.** All 16 existing AD-456 tests + all existing HttpFetchAgent tests + all existing finalize tests continue to function unchanged. New `_egress_policy` ClassVar defaults to `None` (test #11 locks); `egress_active_enforcement` defaults to `False` (test #12 locks); new `runtime_sandbox.py` file is greenfield (zero hits at HEAD). The migration is forward-compatible.

7. **No mid-wave reframe expected.** Wave-10 reframe (OS-level isolation deferred to AD-456b-1) is pre-applied at draft time. All known scope-bloat targets — true process isolation, trust-band → capability-set policy, AD-660b diagnostic-action consumer wiring, container-based sandboxing, RedTeamAgent egress integration, HXI allowlist hot-reload — are pre-deferred at the prompt level (DLogs #1, #4, #6, #8 + "Out of scope" section). AD-456b-1 through AD-456b-7 are the explicit forcing functions documented in the prompt body.

8. **No commercial leak.** AD-456b is OSS plumbing: bounded-execution surface + EgressPolicy active enforcement. AD-456b-4 *(Commercial)* deferral entry tags container-based sandbox / namespace isolation / eBPF as the extension-point seam — describes WHAT plugs in (extension point on the `RuntimeSandbox.execute` contract), NOT business model. Pricing, RBAC over sandbox capabilities, SSO over policy management, enterprise dashboards belong in the private commercial repo entirely. v1 ships zero references to pricing, tier strategy, customer counts, or competitive positioning. Commercial-leak audit: **clean**.

9. **AD-660b consumer wiring is explicitly NOT in this wave** (per user constraint). v1 ships `runtime.runtime_sandbox` as a public attribute so AD-660b's diagnostic actions can later route through it; this wave does NOT modify any AD-660b code. AD-456b-3 is the deferred wiring entry.
