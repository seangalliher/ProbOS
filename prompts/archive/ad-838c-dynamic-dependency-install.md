# AD-838c — Dynamic dependency installation for the task/tool-acquisition path (Copilot-style "ask before installing")

**Status:** Ready
**Dependencies:** AD-211–215 (`DependencyResolver` — detect/approve/install machinery), AD-838 (office-skills wiring; this is its `AD-838c` forward marker), AD-214 (shell approval-callback wiring)
**Estimated tests:** 9 pytest
**Parent:** AD-838 (sub-letter; no new top-level AD number consumed)

## Problem

GitHub Copilot will, during *any* task, detect that a needed Python package is missing,
**ask the operator for permission**, and install it. ProbOS already has the *machinery* for
this but it is reachable only from one narrow path.

`DependencyResolver` ([`cognitive/dependency_resolver.py`](../src/probos/cognitive/dependency_resolver.py),
AD-211–215) already:
- AST-parses imports and finds missing packages ([`detect_missing`](../src/probos/cognitive/dependency_resolver.py#L63)),
- maps import → pip name (`bs4`→`beautifulsoup4`, `cv2`→`opencv-python`, …),
- prompts via an `_approval_fn` callback wired to a real interactive prompt in the shell
  ([`shell.py:155`](../src/probos/experience/shell.py#L155) → `user_dep_install_approval`),
- installs via a `pip → uv pip → uv add` fallback chain with `find_spec` verification
  ([`_install_package`](../src/probos/cognitive/dependency_resolver.py#L166)).

Two constraints stop this from being Copilot-like:

1. **It only exists inside the self-modification pipeline.** The resolver is constructed
   *only* when `config.self_mod.enabled`
   ([`cognitive_services.py:127`](../src/probos/startup/cognitive_services.py#L127)) and is
   invoked *only* at `self_mod.py` step 2b when an agent/skill is **designed at runtime**
   ([`self_mod.py:236`](../src/probos/cognitive/self_mod.py#L236),
   [`self_mod.py:444`](../src/probos/cognitive/self_mod.py#L444)). A normal task run by an
   existing agent that imports an un-bundled package never reaches it — it just fails with
   `ModuleNotFoundError`.
2. **It is gated on a hard `allowed_imports` whitelist**
   ([`config.py:2738`](../src/probos/config.py#L2738)). Anything not pre-listed is silently
   skipped, never offered. Copilot offers (almost) anything with operator approval as the
   gate, not a static allow-list.

**Net:** ProbOS can install-on-approval only while *building* an agent, and only from a
fixed list. It cannot do the Copilot move — "this task needs `package X`, may I install it?"
— during ordinary work.

## Solution

Promote `DependencyResolver` to a runtime-level service and add a **request-driven**,
approval-gated install entry point usable from any task path. Keep human approval as the
mandatory gate; relax the *hard* whitelist into a **tiered** policy (auto-approve listed,
prompt for unlisted, hard-deny a forbidden set). No change to the existing self-mod step 2b
behavior — that path keeps its current whitelist semantics by default.

### Section 1 — Tiered import policy on `DependencyResolver`

File: `src/probos/cognitive/dependency_resolver.py`

Add an explicit **policy mode** so the same resolver serves both callers:

- New constructor param `policy: Literal["whitelist", "prompt_unlisted"] = "whitelist"`
  (default preserves AD-213 behavior byte-for-byte).
- New optional `deny_imports: list[str] | None = None` — a hard deny set (never installable,
  never prompted). Seed default `None` → empty.
- In `detect_missing`, when `policy == "prompt_unlisted"`: a missing import that is **not**
  on `allowed_imports` is *still returned* (so it can be offered), **unless** it is in
  `deny_imports` (silently skipped). When `policy == "whitelist"`: unchanged — only
  allow-listed-but-missing are returned.
- `resolve` is unchanged in shape; the approval callback remains the gate. (When a package
  is unlisted, the human prompt IS the authorization.)

Boundary rules: `probos` internal imports and stdlib-resolvable names are still skipped in
both modes (existing `find_spec` / `name == "probos"` guards retained). An import that is
already installed (resolvable via `find_spec`) is **not** returned under `prompt_unlisted`
either — only genuinely-missing imports are offered.

### Section 2 — Config: opt-in dynamic-install policy

File: `src/probos/config.py`

Add a new top-level `DependencyConfig` Pydantic model (do **not** overload `SelfModConfig`),
consumed by the runtime. It reuses `config.self_mod.allowed_imports`
([`config.py:2738`](../src/probos/config.py#L2738)) as the auto-approve tier rather than
duplicating that list. Pydantic, sensible defaults, validated at parse time:

- `dynamic_install_enabled: bool = False` — master opt-in for the task-path resolver.
  Default `False` → zero behavior change, ProbOS boots identically.
- `dynamic_install_policy: Literal["whitelist", "prompt_unlisted"] = "prompt_unlisted"` —
  only consulted when `dynamic_install_enabled`.
- `dynamic_install_deny: list[str] = []` — hard deny set; seed **empty** (approval is the
  gate, not a static block-list). Document that approval is still required regardless.

### Section 3 — Runtime service + request-driven entry point

Files: `src/probos/startup/cognitive_services.py`, `src/probos/runtime.py`

- Construct a `DependencyResolver` for the task path when `dynamic_install_enabled`, even if
  `self_mod` is disabled. Build it with `policy=dynamic_install_policy`,
  `deny_imports=dynamic_install_deny`, and `allowed_imports=config.self_mod.allowed_imports`
  (reused as the auto-approve tier). Expose it on the runtime (e.g. `runtime.dependency_resolver`)
  so non-designed callers can reach it. If `self_mod` is also enabled, **reuse the same
  instance** for both paths (don't construct two).
- Add an async runtime method `ensure_dependency(import_name: str | list[str]) -> DependencyResult`
  that wraps `resolve(...)` for a synthetic import snippet, so an agent/capability that knows
  it needs `package X` can request it directly (not only via AST scan of generated code).
- Wire the approval callback the same way the self-mod path does
  ([`shell.py:155`](../src/probos/experience/shell.py#L155)) so the task-path resolver shares
  the existing `user_dep_install_approval` prompt — one consistent UX.

  **SECURITY (OWASP — required, blocker).** Today the shell wires `_approval_fn` **only**
  inside `if self.runtime.self_mod_pipeline:` ([`shell.py:145`](../src/probos/experience/shell.py#L145)
  → [`shell.py:155`](../src/probos/experience/shell.py#L155)). If `dynamic_install_enabled=True`
  while `self_mod` is disabled, there is no `self_mod_pipeline`, so the approval callback is
  never wired — `_approval_fn` stays `None`, the `if self._approval_fn:` gate in `resolve`
  ([`dependency_resolver.py:122`](../src/probos/cognitive/dependency_resolver.py#L122)) is
  falsy, and packages would install **without consent**. Add a **standalone** wiring branch,
  outside the self-mod guard:

  ```python
  if getattr(self.runtime, "dependency_resolver", None):
      self.runtime.dependency_resolver._approval_fn = (
          lambda pkgs: user_dep_install_approval(self.console, self.renderer, pkgs)
      )
  ```

  **Defense in depth (required).** `ensure_dependency` must hard-decline if any package falls
  under the prompt tier while `_approval_fn is None` — return
  `DependencyResult(success=False, error="approval callback unavailable")` and install
  nothing. Never fall through to an unguarded install.

### Section 4 — Emit governance events

File: `src/probos/runtime.py` (or wherever `ensure_dependency` lives)

Mirror the self-mod event taxonomy so task-path installs are auditable in the event log
exactly like designed-agent installs (AD-215 parity). Use the existing string-event API —
**no new `EventType` enum is needed**: `await self._event_log.log(category="dependency",
event="dependency_check", detail=json.dumps({...}))`, mirroring the self-mod emit pattern
([`self_mod.py:241-266`](../src/probos/cognitive/self_mod.py#L241)). Use a distinct
`category` (e.g. `"dependency"`) to separate task-path installs from self-mod ones. Confirm
the runtime exposes the event log with a `.log(...)` method before wiring. Emit:
`dependency_check`, `dependency_install_approved`,
`dependency_install_success` / `declined` / `failed`.

## Tests

New file: `tests/test_ad838c_dynamic_install.py`

1. **Default disabled is a no-op** — `dynamic_install_enabled=False`; runtime exposes no
   task-path resolver (or `ensure_dependency` declines cleanly), zero-config boot unchanged.
2. **`prompt_unlisted` returns unlisted missing** — `detect_missing` with
   `policy="prompt_unlisted"` returns a missing import that is NOT on `allowed_imports`.
3. **`whitelist` mode unchanged** — same input under `policy="whitelist"` does NOT return the
   unlisted import (AD-213 regression guard).
4. **`deny_imports` blocks** — a denied import is never returned, even under `prompt_unlisted`.
5. **`ensure_dependency` happy path** — stub `install_fn`/`approval_fn` → `DependencyResult.success`,
   package in `installed`.
6. **`ensure_dependency` declined** — approval callback returns `False` → `declined`, nothing
   installed.
7. **Single shared instance** — with both `self_mod.enabled` and `dynamic_install_enabled`,
   the runtime reuses one resolver instance (assert identity).
8. **Governance events** — `ensure_dependency` emits `dependency_check` +
   `dependency_install_approved/success` (or `declined`) via the event hook.
9. **No approval callback → hard-decline (security)** — with `policy="prompt_unlisted"`,
   `_approval_fn = None`, and an unlisted missing import, `ensure_dependency` installs
   **nothing** and returns `DependencyResult(success=False)` (no unguarded install).

Run: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad838c_dynamic_install.py -v -n 0`

## What This Does NOT Change

- No change to the self-mod step-2b flow when `dynamic_install_policy`/`dynamic_install_enabled`
  are at defaults — designed-agent installs behave exactly as AD-213/214/215.
- No change to `forbidden_patterns` / `CodeValidator` (static-analysis security gate is
  orthogonal and stays as-is).
- No automatic, un-prompted installs — human approval remains mandatory in every mode.
- No removal of the `allowed_imports` list — it becomes the auto-approve tier, not deleted.
- No new package-manager backend (reuses the existing `pip → uv pip → uv add` chain).

## Tracking

- `PROGRESS.md` — add AD-838c entry on completion.
- `decisions-era-5-unification.md` — append AD-838c: promote `DependencyResolver` to a
  runtime task-path service with tiered (auto-approve / prompt / deny) policy and a
  request-driven `ensure_dependency` entry point. Copilot-style "ask before installing" for
  ordinary tasks, not just designed-agent code.

## Acceptance Criteria

1. With `dynamic_install_enabled=True`, an agent/task that needs an un-bundled package
   triggers the existing approval prompt and installs on approval — outside the self-mod path.
2. `dynamic_install_policy="prompt_unlisted"` offers packages not on `allowed_imports`;
   `deny_imports` hard-blocks; human approval is always required.
3. Defaults (`dynamic_install_enabled=False`) leave boot and the self-mod path byte-identical.
4. One resolver instance is shared when both paths are enabled.
5. Task-path installs emit the same governance events as designed-agent installs.
6. When `_approval_fn` is unavailable, no package installs under any policy (hard-decline).
7. `tests/test_ad838c_dynamic_install.py` passes (9 tests).
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
