# AD-1073 — Approval-gated dependency install in the conversational loop

**Issue:** seangalliher/ProbOS#1009 · **Builds on:** AD-1066 (`run_python`), AD-994 (`CodeRunnerAgent`), AD-212/838c (`DependencyResolver`), AD-853 (`CapabilityRequest`)

**Current highest referenced top-level AD: AD-1072** (epic-reserved); AD-1070a shipped this session. This is **AD-1073** — the next free top-level.

---

## Goal

An agent in the conversational `AgenticLoop` (AD-1065) that needs a Python library it doesn't have — e.g. `reportlab` to make a PDF — can **identify the gap, ask the Captain to approve the install, install on approval, and retry** the script. So *"make me a PDF"* → `ModuleNotFoundError: reportlab` → an in-chat **Approve / Deny** card → Captain approves → install → real PDF. Reuses the existing detect → approve → install → verify machinery; no new install backend.

## Verified facts (grepped against HEAD)

- **The gap:** the AD-1066 `CodeExecutionTool` (`tools/code_execution_tool.py`, `tool_id="run_python"`) runs code in a fresh `scratch_dir/exec-<uuid>` workdir via `SubprocessSandbox` using the **base interpreter** (`sys.executable`, `-I` isolated). `input_schema = {code, timeout}` — **no package install, no missing-import handling**.
- `DependencyResolver` (`cognitive/dependency_resolver.py`): `detect_missing(source_code) -> list[str]` (AST import scan + `IMPORT_TO_PACKAGE` map, e.g. `bs4`→`beautifulsoup4`); `resolve(...)` = detect → `_approval_fn(list[str]) -> Awaitable[bool]` → install → verify via `importlib.util.find_spec`.
- `runtime.ensure_dependency(import_name)` (`runtime.py:2945`): **hard-declines when `_approval_fn is None`** (never silent install); auto-approves the `self_mod.allowed_imports` whitelist tier; honors the deny-list. Config `DependencyConfig(dynamic_install_enabled=False default, dynamic_install_policy="prompt_unlisted", dynamic_install_deny=[])`.
- `CapabilityRequest` (`capability_request.py:55`): `kind="install"` rung; `capability_triage` (AD-855) **always leaves `install` pending for the Captain** (no auto-approve fast-path — "reversibility preference"). `CapabilityRequestStore` with the verified ClearanceGrantStore DB+cache shape.
- `CodeRunnerAgent` (`agents/code_runner.py`): `install_package` + `run_python(packages=[...])` intents, both `requires_consensus=True` (the **task path**, via the decomposer).
- Governance events: `dependency_check` / `dependency_install_approved` / `_install_success` / `_install_declined` / `_install_failed`.

## Approach

1. **Detect** — in `CodeExecutionTool.invoke`, before running (or on a caught `ModuleNotFoundError`/`ImportError` from the sandbox), call `DependencyResolver.detect_missing(code)` to resolve the missing import(s) → package name(s).
2. **Request approval IN CHAT** — file an AD-853 `CapabilityRequest(kind="install", target=<package(s)>, rationale="needed to run the script: <import>", agent_id, work_item_id=thread_id)` and surface it to the Captain as an **Approve / Deny card** on the thread (reuse the AD-1053 actionable-notification carrier / the artifact-card render pattern). Honest-degrade (AD-592): no approval surface wired ⇒ return the `ModuleNotFoundError` result unchanged (the agent reports it can't).
3. **Install on approve** — on approval, install into the environment `run_python`'s sandbox imports from (**DESIGN DECISION for the build:** the base `.venv` via `pip` vs a per-thread workspace venv that the sandbox runs against — AD-1066 currently uses the base interpreter with `-I`, so either pip-install into the active env or switch the tool to a per-agent persistent workspace venv like `CodeRunnerAgent`). Verify with `find_spec`.
4. **Retry** — re-run the original script once the dependency verifies; surface the produced artifact as normal.
5. **Govern** — default-OFF (`dependency.dynamic_install_enabled` + an approval surface present); deny-list honored; every step emits the governance events above.

## Do NOT change

- The consensus `run_python` / `install_package` intents on `CodeRunnerAgent` (the task path) — AD-1073 is additive to the AD-1066 loop tool.
- `DependencyResolver` / `ensure_dependency` / `CapabilityRequest` internals — reuse, don't fork.
- `config/system.yaml` — never commit.

## Acceptance

`test_ad1073_*`: missing-lib detected → a `CapabilityRequest(kind="install")` filed + surfaced; approve → install + verify + retry → artifact produced; deny → honest-degrade (no install, agent reports the gap); deny-listed package blocked; no approval surface ⇒ unchanged `ModuleNotFoundError` result; default-OFF byte-identical; governance events emitted. Verify Engineering Principles compliance (`.github/copilot-instructions.md`).
