# AD-992 — Crew code execution: tiered isolation for safe Python (Copilot / Claude Code parity)

**Epic.** Give ProbOS crew agents the ability to **create and run Python scripts and
install Python libraries as needed to perform tasks** — the capability GitHub
Copilot and Claude Code have — done the ProbOS way: governed by consensus, logged
to the episodic memory, default-OFF, and isolated through a **pluggable tiered
sandbox** that escalates with the threat model.

- **Status:** Tier 1 **BUILT** (AD-993 + AD-994, 2026-06-13). Tier 2 + Tier 3 **STUBBED** (design only — see §6/§7).
- **Highest AD at authoring:** AD-991. This wave: **AD-992** (epic), **AD-993** (Tier-1 substrate), **AD-994** (Tier-1 capabilities), **AD-995** (Tier-2 stub), **AD-996** (Tier-3 stub).
- **Issues:** #992 (epic) ← #993, #994, #995, #996.

---

## 1. The gap

ProbOS has **no general-purpose Python execution path**. It treats capability
evolution as a *design* problem, not a *runtime-execution* problem:

- `self_mod` **designs persistent agents** (`agent_designer` → `CodeValidator`
  static analysis → `SandboxRunner` importlib test → Beta(1,3) probationary trust
  → register). Heavyweight; the output is a durable agent, not a one-off result.
- `CodeValidator.forbidden_patterns` (config.py) **bans** `subprocess`, `eval`,
  `exec`, `compile`, `__import__`, `os.system` — by design, for designed-agent code.
- `ShellCommandAgent` runs **shell** commands (consensus-gated) but is not a
  Python runtime and validates `argv[0]` exists on PATH.

So **ephemeral one-off computation has no home**. A crew agent that needs to parse
a CSV, do a numeric calc, transform JSON, or try a library either abstains or
over-builds a persistent agent. Copilot/Claude Code solve this with a scratch
working folder + a real interpreter. We want that, *governed*.

> Adjacent finding: `cognitive/sandbox.py SandboxRunner` loads designed-agent code
> **in-process** via `importlib` — a *test harness*, not a security sandbox. The
> AD-993 `SubprocessSandbox` is the substrate to harden that path later (out of
> scope for this wave; tracked separately).

## 2. Design stance — *governed ephemeral execution*, not an ungoverned scratchpad

Copilot/Claude Code run code in a **working folder with process isolation**. That
is the right *ergonomics* but the wrong *governance* for an agent-native OS where
the code author may be an autonomous agent, not a human at a keyboard. ProbOS adds:

1. **Consensus gate** — every execution is quorum-authorized (same path as `run_command`).
2. **Episodic record** — the `IntentResult` (stdout/stderr/exit/timed_out) is logged; the learning loop sees it.
3. **Default-OFF** — the highest-risk capability in the system is inert until the operator opts in.
4. **Tiered isolation** — the *strength* of the sandbox is a config choice that scales with the threat model, behind one stable backend protocol.

## 3. The tiered isolation model

| Tier | Mechanism | Boundary strength | Analogue | Status |
|------|-----------|-------------------|----------|--------|
| **1 — Subprocess** | Fresh ephemeral working folder + child process + resource limits (RLIMIT on POSIX) + timeout + output caps + network-off-by-default | **Process isolation + confinement-by-convention.** NOT kernel containment. | GitHub Copilot working folder | **BUILT (AD-993/994)** |
| **2 — OS sandbox** | OS-native, kernel-enforced confinement: Linux bubblewrap/seccomp, macOS Seatbelt, Windows AppContainer — or Microsoft **MXC** as a cross-platform front | **Kernel-enforced** filesystem/network/syscall boundary | sandbox-exec / firejail / MXC | **STUB (AD-995)** |
| **3 — Container / VM** | Docker / Podman / WSL container or a microVM (Firecracker/gVisor) | **Full environment isolation** + reproducibility + persistence | Cowork containers, devcontainers | **STUB (AD-996)** |

All three implement the **same `IsolationBackend` protocol** (AD-993). The
`CodeRunnerAgent` is written against the protocol, so swapping/adding a tier never
touches agent logic. `config.execution.default_tier` selects the backend.

> **Honesty about Tier 1.** Tier 1 is process isolation, resource bounds, and
> confinement-by-convention **governed by consensus** — it is *not* a
> kernel-enforced containment boundary. A determined payload running at Tier 1 has
> the privileges of the ProbOS process. That is acceptable **only** under the
> default single-operator / own-machine model, with consensus + default-OFF as the
> real controls. Hostile-code or multi-tenant threat models **require Tier 2+**.
> The module docstring states this in-band so no operator is misled.

## 4. What was built (AD-993 + AD-994)

### AD-993 — `src/probos/execution/isolation.py` (Tier-1 substrate)

- `IsolationTier(IntEnum)`: `SUBPROCESS=1`, `OS_SANDBOX=2`, `CONTAINER=3`.
- `ExecutionRequest` (code | argv, workdir, timeout, max_output_bytes,
  max_memory_mb, allow_network, env, python_executable).
- `ExecutionResult` (success, stdout, stderr, exit_code, timed_out, duration_ms,
  tier, error, workdir).
- `IsolationBackend(Protocol)` — `tier`, `available() -> bool`, `async run(req) -> ExecutionResult`.
- `SubprocessSandbox` — the Tier-1 backend:
  - Ephemeral per-task scratch folder (uuid under `scratch_root`), **reaped** in `finally`.
  - `subprocess.Popen` inside `loop.run_in_executor` — mirrors `ShellCommandAgent`
    (Windows `SelectorEventLoop` can't host `create_subprocess_exec`).
  - **Arg-list invocation, never `shell=True`** → no command injection.
  - Code path: `[python, "-I", "-B", script.py]` (isolated, no `.pyc`).
  - Scrubbed env (PATH/SYSTEMROOT passthrough only); `allow_network=False` sets a
    blackhole proxy env (soft deterrent — Tier 1 can't truly cut the network; that
    is a Tier-2 guarantee).
  - POSIX: `start_new_session=True` + `preexec_fn` RLIMIT_AS/CPU/FSIZE; kill the
    **process group** on timeout. Windows: `CREATE_NEW_PROCESS_GROUP`; `proc.kill()`.
  - Output capped per stream. **Honest-degrade: never raises out of `run`.**

### AD-994 — `src/probos/agents/code_runner.py` + `ExecutionConfig`

- `CodeRunnerAgent` (core tier), two **consensus-gated** intents:
  - **`run_python(code, packages?, timeout?)`** — write + run a script in an
    isolated folder. With `packages`, a **throwaway per-task venv** is created and
    the libraries installed first ("install libraries as needed"), then the script
    runs in that venv. No packages → host interpreter, no venv. The whole scratch
    tree (incl. venv) is reaped after.
  - **`install_package(packages)`** — validate a package set installs cleanly into
    a throwaway venv (availability probe). Same machinery, no script run.
- `ExecutionConfig` (config.py, **default OFF**): `enabled=False`, `default_tier=1`,
  `scratch_dir`, `timeout_seconds`, `max_output_bytes`, `max_memory_mb`,
  `allow_package_install=False`, `pip_index_url`, `install_timeout_seconds`.
- Wiring: `runtime.register_template("code_runner", …)`; **gated pool** in
  `startup/agent_fleet.py` (spawned only when `execution.enabled`) with the
  `runtime` kwarg; `fleet_organization.py` core membership. **NOT** added to
  `_MESH_READ_INTENT_POOLS` — these are consensus/WRITE intents, not read.
- Defense in depth: (a) pool not spawned unless enabled; (b) agent refuses at
  `decide()` if disabled; (c) package names sanitized (`_clean_packages` drops
  `-`-prefixed tokens → no pip-flag injection); (d) timeout clamped to ≤300s.

**Not enabled in `config/system.yaml`** — left inert; the operator flips
`execution.enabled` (and `allow_package_install`) after reviewing this spec.

## 5. Escalation model — Tier 1 → Tier 3 *directly*

Tiers are **independent backends behind one protocol**, not a ladder you must climb
rung by rung. A task is either:

- **safe enough for Tier 1** (the configured default), or
- **escalated to a stronger tier** (`default_tier=2` or `3`).

Crucially, **escalation can skip Tier 2 → Tier 3 directly.** If Tier 2 is not
available (MXC immature, no bubblewrap) but the threat model demands kernel-grade
isolation, the operator sets `default_tier=3` (container) and the same
`CodeRunnerAgent` runs unchanged. We do **not** need Tier 2 built before Tier 3 is
useful — that is the whole point of the protocol seam. (This answers the build-order
question: Tier 3 is buildable without Tier 2.)

## 6. AD-995 (STUB) — Tier-2 OS-native sandbox — *waiting for MXC to mature*

**Decision: design-only for now; decide absorb-vs-use later.** Tier 2 is a second
`IsolationBackend` implementation that wraps an OS-native, kernel-enforced
confinement mechanism:

- Linux: `bubblewrap` (`bwrap`) + seccomp, or `firejail`.
- macOS: `sandbox-exec` (Seatbelt) profiles.
- Windows: AppContainer / Win32 app isolation.
- **Or Microsoft MXC** as a single cross-platform front (Windows 11 24H2+
  processcontainer, Linux bubblewrap, macOS seatbelt).

**MXC disposition (researched 2026-06-13):**
- License: **MIT**. Cross-platform Rust binaries (`wxc-exec` / `lxc-exec` /
  `mxc-exec-mac`) + a **TypeScript** SDK (`@microsoft/mxc-sdk`). **No Python SDK.**
- Version **0.7.0-alpha**; schema is churning. The README explicitly states **"no
  MXC profiles should be treated as security boundaries currently."**
- **Disposition:** track as a **forward-marker Tier-2 backend**. Absorb the
  *pattern* (pluggable backends behind one schema — which AD-993 already does).
  **Do not link the SDK** (it's TS; we'd shell to the Rust binary BYO-style, like
  the `rg`/Piper/Rhubarb optional-binary pattern). Re-evaluate when MXC reaches a
  stable, security-boundary-grade release. Until then, an operator needing
  kernel-grade isolation uses Tier 3 (containers), which is mature today.

**Build trigger:** MXC (or a chosen OS-native mechanism) reaches a release that
*does* claim a security boundary, **and** there is demand for kernel-grade
isolation on a host where containers are unavailable/undesirable.

## 7. AD-996 (STUB) — Tier-3 container/VM — *deferred, buildable without Tier 2*

A third `IsolationBackend` that runs the `ExecutionRequest` inside a container
(Docker/Podman/WSL) or microVM (Firecracker/gVisor): full filesystem + network +
process isolation, plus **reproducibility and persistence** a process/venv can't give.

**Answering the design question — "once we have Tier 2, do we need Tier 3?"**

For the **stated goal** (create scripts + install libraries safely) on the
**default single-operator / own-machine** deployment, **Tier 2 is sufficient.**
Kernel-enforced confinement of a child process on the operator's own machine meets
that threat model. **Tier 3 is *not* required for the headline capability.**

Tier 3 earns its place only when one of these is true:

1. **Stronger threat model** — hostile/untrusted code, or **multi-tenant** hosting
   where one tenant's code must not touch another's. Defense-in-depth against
   kernel-escape wants a VM/container boundary, not just a sandbox profile.
2. **Reproducible / persistent environments** — pinned OS + system libs, a durable
   project workspace across runs, GPU passthrough, etc. — beyond an ephemeral venv.

Both of those are **hosted / commercial / multi-tenant** concerns, not the
single-operator OSS default. **Conclusion:** Tier 2 covers the OSS goal; Tier 3 is
primarily a **commercial / hosted-multi-tenant** capability and a defense-in-depth
option — desirable, not required. And because the tiers are independent backends,
Tier 3 can be **built directly after Tier 1, skipping Tier 2**, if the hosted use
case lands first.

## 8. OSS ↔ commercial boundary

- **OSS (this repo):** the tiered substrate + Tier 1 (built) + Tier 2 (the
  *extension point* / future backend). How the capability *works*.
- **Commercial:** hosted multi-tenant execution, the Tier-3 container/microVM
  fleet at scale, per-tenant resource accounting/billing, and policy controls. How
  it *makes money*. Tracked in the private commercial roadmap, not here.

## 9. Acceptance criteria (Tier-1, met)

- `tests/test_ad993_isolation.py` — SubprocessSandbox: stdout capture, argv exec,
  nonzero exit, stderr, timeout-kills, output-capped, bad-executable degrade,
  no-input degrade, internal-scratch reaped, explicit-workdir preserved, POSIX
  memory-limit (skipif win32). **All green.**
- `tests/test_ad994_code_runner.py` — disabled-gate (run_python + install_package),
  no-runtime degrade, run_python happy path / nonzero exit / empty-code / timeout,
  packages-blocked-when-install-off, install no-packages error, **real offline
  venv+pip honest-degrade**, `_clean_packages` flag-strip, timeout clamp, venv
  path. **All green.**
- Regression blast (wiring + descriptor consumers): green.
- Default-OFF verified: pool not spawned and agent refuses unless `execution.enabled`.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 10. Explicitly NOT in this wave

- **Do not** build Tier 2 or Tier 3 backends (design/stubs only).
- **Do not** link the MXC SDK or add any new hard dependency.
- **Do not** enable `execution.enabled` in `config/system.yaml`.
- **Do not** add `run_python`/`install_package` to `_MESH_READ_INTENT_POOLS`.
- **Do not** harden `cognitive/sandbox.py` here (separate, tracked).
- **Do not** wire code execution into the decomposer's default plan templates.
