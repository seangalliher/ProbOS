# AD-1178: a missing library should become a request, not a traceback

**Repo:** OSS (`d:\ProbOS`), branch `main`, HEAD `7e4c1c1d`
**Type:** AD. Highest assigned: **AD-1180** (shipped `fc64394f`). AD-1179 (#1111) is reserved and
unbuilt. **AD-1178 is already reserved by #1110** — do not mint a new number.
**Issue:** #1110

---

## Problem

When a crew agent writes Python importing a library the venv does not have, it receives a raw
traceback and nothing else.

`CodeExecutionTool._maybe_install_missing` (`tools/code_execution_tool.py:205`) opens:

```python
dep_cfg = getattr(getattr(self._runtime, "config", None), "dependency", None)
if dep_cfg is None or not getattr(dep_cfg, "dynamic_install_enabled", False):
    return None
```

`dependency.dynamic_install_enabled` is **False** by default and False on the reference vessel.
So the function returns `None`, the script runs, and the sandbox output carries a bare
`ModuleNotFoundError: No module named 'reportlab'`. The model is never told which module was
missing in structured form, nor that an approval path exists at all.

AD-1180 now tells every agentic path to *"say plainly what is needed and why"*. This AD makes
that instruction actionable — right now the agent has no structured signal to say it *from*.

## The trap: `detect_missing` cannot be reused

**Verified empirically against the reference vessel's config, 2026-08-02:**

```
dynamic_install_enabled : False
self_mod.enabled        : True
detect_missing('import reportlab\nimport matplotlib\nimport json') -> []
```

Three reasons it returns nothing useful here:

1. `DependencyResolver.__init__` defaults `policy="whitelist"`, and
   `startup/cognitive_services.py:196` constructs the resolver **without a policy** when
   `dynamic_install_enabled` is False. So it runs in whitelist mode.
2. In whitelist mode `detect_missing` `continue`s past any import not on
   `self_mod.allowed_imports` (`dependency_resolver.py:98-107`). `reportlab` and `matplotlib`
   are not on it, so they are filtered out before the availability check.
3. It answers **"which allowlisted packages are missing"**, which is a different question from
   **"which imports in this code will fail"**.

There is also an availability problem: the resolver is only constructed when
`config.self_mod.enabled or dep_cfg.dynamic_install_enabled` (`cognitive_services.py:186`). An
operator with both off has `runtime.dependency_resolver is None`. **This AD must not depend on
the resolver existing.**

---

## Decision

Add a small, self-contained detector and surface its result on the existing tool output.

### 1. A pure detection helper

Module-level in `tools/code_execution_tool.py` (it has exactly one consumer; a new module is not
warranted):

```python
def detect_unimportable(source_code: str) -> list[str]:
```

- `ast.parse`; return `[]` on `SyntaxError` (the run will report the syntax error itself).
- Collect root names from `ast.Import` and `ast.ImportFrom` (mirror the walk in
  `dependency_resolver.detect_missing:83-92` — same shape, no allowlist and no policy).
- Skip relative imports (`node.level > 0` on `ImportFrom`) — they resolve against the workdir,
  not site-packages.
- For each name, `importlib.util.find_spec(name)` is `None` ⇒ unimportable. **Wrap each call in
  `try/except Exception`** — `find_spec` raises `ModuleNotFoundError` for a missing parent and
  `ValueError` for some malformed names; treat any raise as unimportable.
- Sorted, deduplicated.
- The sandbox runs on `sys.executable` in the same venv, so the runtime process is a sound proxy
  for what the subprocess can import. Say so in the docstring.

### 2. Surface it when the run could not import

In `invoke`, after `dep_summary = await self._maybe_install_missing(code)` and **only when
`dep_summary is None`** (the install path is off or found nothing — the existing enabled path is
untouched), compute `detect_unimportable(code)`. When it is non-empty, attach:

```python
output["dependencies"] = {
    "missing": [...],
    "install_enabled": False,
    "guidance": "<one sentence>",
}
```

- **Byte-identical when nothing is unimportable** — no key added, exactly as today.
- **Byte-identical when `dynamic_install_enabled` is True** — `_maybe_install_missing` returns a
  dict, so this branch never runs.
- `stdout`, `stderr`, `exit_code`, `success`, `artifacts` are all untouched. This augments; it
  never replaces.

### 3. No new config flag

State this in the docstring so a later reviewer does not "fix" it. The reasoning: this fires
only when an import is genuinely unresolvable, which is already a failure the model is being
shown a traceback for. It adds information on an error path and removes none. A default-OFF flag
would leave it inert for every operator, which is the exact failure mode this session has been
correcting (AD-1175, AD-1177, AD-1180 were all built-but-unreachable in some path). The tool
already returns `stderr` unconditionally; this is the same category.

### 4. Gap-regex constraint (hard)

The `guidance` string reaches the model. It MUST NOT match `_CAPABILITY_GAP_RE`
(`cognitive/decomposer.py:33`). Read the real regex first. Traps here are dense because the
subject is absence:

- `not (available|supported|possible)` — forbidden
- `lack(?:s|ing)?` — forbidden
- `no (?:built-in |native )?(?:capability|ability|support|way|mechanism|tool)` — forbidden
- `don't have` / `doesn't have` / `cannot` / `can't` / `unable to` — forbidden

Write it as a **request**, not a limitation: name the module, say the Captain can approve
installing it, and say what to do meanwhile. Assert with the real imported `is_capability_gap`.

---

## Target files

| File | Change |
|---|---|
| `src/probos/tools/code_execution_tool.py` | `detect_unimportable`; the guidance constant; the branch in `invoke`. |
| `tests/test_ad1178_missing_dependency.py` | NEW. |

---

## Acceptance criteria

1. **`detect_unimportable` finds a genuinely absent module.** Use one that is really not
   installed — verify at test time with `importlib.util.find_spec` rather than hardcoding a name
   that might get installed later.
2. **It does not flag stdlib or installed packages** — `json`, `pathlib`, and a package known
   present (e.g. `pydantic`) return nothing.
3. **Syntax error ⇒ `[]`** (the run reports the syntax error itself).
4. **Relative imports are skipped.**
5. **`find_spec` raising is treated as unimportable** — monkeypatch it to raise and assert the
   name is still reported.
6. **It is NOT `detect_missing`.** Assert directly that `detect_unimportable` reports a
   non-allowlisted absent module while a whitelist-mode `DependencyResolver.detect_missing`
   returns `[]` for the same source. This test is the record of why the helper exists — without
   it, someone will "simplify" this back to the resolver call.
7. **Output carries the key when a module is missing** — through the real `invoke` with the real
   sandbox.
8. **Byte-identical when nothing is missing** — no `dependencies` key.
9. **Byte-identical when `dynamic_install_enabled` is True** — the AD-1073 path still produces
   its own summary shape and this branch does not fire.
10. **`stdout` / `stderr` / `exit_code` preserved** alongside the new key.
11. **Guidance is gap-regex-safe** via the real imported function.
12. **Works with `runtime.dependency_resolver is None`** — the detector must not touch it.

Expected: **12–16 new tests.**

### Gates

```powershell
$env:PROBOS_DATA_DIR="$env:TEMP\ad1178_$(Get-Random)"; $env:PROBOS_EMBEDDINGS='local'
& d:/ProbOS/.venv/Scripts/python.exe -m pytest `
  tests/test_ad1178_missing_dependency.py `
  tests/test_ad1066_code_execution_tool.py `
  tests/test_ad1073_loop_dependency_install.py `
  tests/test_ad1074d_artifact_roundtrip.py `
  tests/test_dependency_resolver.py `
  -q -n 0
```

(If any of those paths does not exist, substitute the real one and say so — do not silently drop
a gate. `test_ad1074d_*` is the least certain.)

Then ONE full gate, **run synchronously — do not background it and return.**
**Baseline is 22,487 NODES** (BF-705's gate: 22,487 passed, 0 failed). Reconcile
`22,487 + <new tests> == passed + failed` and show the arithmetic. Expect ~1 rotating
environmental flake; re-run any failure `-n 0` before calling it real.

---

## Do NOT build

- **Do not** flip `dynamic_install_enabled`. That is a Captain policy call.
- **Do not** modify `DependencyResolver` or `detect_missing` — other callers depend on the
  allowlist semantics.
- **Do not** modify `_maybe_install_missing`'s enabled path.
- **Do not** file a `CapabilityRequest` or a `FaultReport` from here. Absence is not breakage,
  and an automatic filing per failed run is a flood. Surfacing it to the model is this AD's
  whole scope.
- **Do not** attempt to install anything.
- **Do not** edit `PROGRESS.md`, `DECISIONS.md`, or the roadmap.
- **Do not** stage `config/system.yaml` (skip-worktree).

## Notes

- Stage before the full gate (`test_ad1123_bounded_federation_relay.py` reads *unstaged* diff).
- str-replace end-anchor trap: whatever appears at either END of `oldString` must reappear in
  `newString`.

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
