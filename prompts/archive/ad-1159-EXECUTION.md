# AD-1159 — Execution instructions

Read the spec first: `prompts/ad-1159-work-permit.md`.

This document restates only the constraints whose violation is expensive. They are
deliberately redundant with the spec.

---

## The five that matter most

**1. Nothing consumes the store in this AD.**
No edits to `BrowserTool`, `DispatchToolExecutor`, `agentic_dispatch.py`,
`finalize.py`, `runtime.py`, any router, or anything under `ui/`. If your diff
touches a file outside `src/probos/tools/work_permits.py`, `src/probos/config.py`
and `tests/test_ad1159_work_permits.py`, stop and re-read Section 6.
AD-1154's precedent: shipping a gate together with the thing it gates means the
gate's first exercise is in production.

**2. `ConnectionFactory`, never `aiosqlite.connect()` directly.**
`.github/copilot-instructions.md` Cloud-Ready Storage rule. Mirror
`src/probos/tools/action_approvals.py` exactly — it is the proven shape and yours
is the fifth instance of it. Prove it with a test that injects a custom factory.

**3. `expires_at` is NOT NULL in the schema, not merely in the signature.**
`ttl_seconds` is a required parameter. Do not add an `expires_at: float | None`
overload "for flexibility". AD-1154's reasoning: a standing authority with no TTL
is a permanent privilege escalation nobody remembers granting.

**4. Reject `bool` for `max_tier`.**
`isinstance(True, int)` is `True` in Python. `max_tier=True` would silently mean
tier 1 — an authorization created by a typo. Use `type(value) is not int`, the
same shape the `CrewSessionContract` validators use. Test both `True` and `False`.

**5. Run the FULL suite before reporting done.**
```powershell
$env:PROBOS_DATA_DIR="$env:TEMP\ad1159_$(Get-Random)"; $env:PROBOS_EMBEDDINGS='local'
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/ -q --timeout=600
```
Baseline: **21,711 passed, 34 skipped**. A name-filtered run cannot prove blast
radius — that lesson cost a CI failure earlier today (BF-688a: 28 test files'
doubles broke on a signature change that a filtered run reported green).

---

## Git

- `git ls-files -v config/system.yaml` must print `S`. **Never `git add` that file.**
- Commit with `git commit -F <file>`. Inline `-m` in PowerShell silently swallows
  `$`, which corrupts messages.
- One commit. `git status --short` must be empty afterwards.

## If a reference in the spec does not match the tree

The spec's line numbers were verified when written, but **locate by symbol**. If a
symbol is genuinely absent or its signature differs, **stop and report** rather
than adapting the design around it. A wrong assumption silently accommodated is
how AD-566a produced four would-break-build errors.

## Definition of done

- Every invariant in Section 5.3 has its own named test.
- Every public method has happy-path, error and empty/None coverage.
- Full type annotations on all public methods.
- Log messages state what failed, why it matters, what happens next.
- Full suite green, count reported.
- Compliance with `.github/copilot-instructions.md` explicitly confirmed.
