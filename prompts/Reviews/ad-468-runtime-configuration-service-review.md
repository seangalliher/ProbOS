# Review: AD-468 — Runtime Configuration Service (Ship's Computer)

**Reviewer:** Architect (self-review of own draft)
**Date:** 2026-05-01
**Verdict:** ❌ **Not Ready** — three phantom APIs (`runtime.data_dir`, `set_cycle_interval`, `tomli_w` import) and one direct-private-attr write the prompt acknowledges as a TODO. Builder will hit hard-stops at Section 4. Fixable in ~30 minutes architect time.

---

## Required (must fix before building)

### 1. `runtime.data_dir` is a phantom public attribute

The prompt's Section 4 sketch:
```python
store_path = runtime.data_dir / config.runtime_overrides.store_filename
```

Verified — `runtime.data_dir` does NOT exist:
```
grep -n "data_dir\|@property\s+def\s+data_dir" src/probos/runtime.py
  244:    _data_dir: Path
  284:        data_dir: str | Path | None = None,
  289:        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
  290:        self._checkpoint_dir = self._data_dir / "checkpoints"
```

Only `_data_dir` (private) exists. There is no `@property data_dir` accessor. AD-468 cannot reference `runtime.data_dir` without first adding the public property — that addition itself is an architectural decision (small but real) and shouldn't be silent.

**Action:** Choose one of:
- (a) AD-468 adds `@property def data_dir(self) -> Path: return self._data_dir` to `ProbOSRuntime` as Section 4a (one-line public passthrough). Recommended — matches the AD-680 promotion pattern and removes the only Demeter violation in the wiring.
- (b) AD-468 reaches through as `runtime._data_dir`. Not recommended — creates a documented Demeter violation that future review will re-flag.

### 2. `ProactiveCognitiveLoop.set_cycle_interval` does not exist

The prompt's Section 4 sketch:
```python
runtime.proactive_loop.set_cycle_interval(float(val))
```

Verified — no such method:
```
grep -n "def set_cycle_interval\|def set_interval" src/probos/proactive.py
  (no matches)
```

The class has `_interval` (private, set in `__init__` at `proactive.py:170`) and no public setter. The prompt's verify-first note acknowledges this:

> If `set_cycle_interval` is absent, the Builder must add it (single-line public setter on `ProactiveCognitiveLoop`).

**Action:** Promote that note to a hard Section 4a. Add the setter explicitly in the prompt:

```python
def set_cycle_interval(self, seconds: float) -> None:
    """AD-468: public setter for the proactive cycle interval."""
    self._interval = max(10.0, float(seconds))
```

### 3. `_cooldown` direct assignment is a Demeter violation the prompt flags as a TODO

The prompt's Section 4:
```python
runtime.proactive_loop._cooldown = float(val)  # set via existing public setter if added
```

This is private-attribute access across module boundaries — explicit anti-pattern in `.github/copilot-instructions.md`. The prompt's own note says:

> direct `_cooldown` assignment is a TODO marker; if the prompt review flags it, replace with a `set_cooldown(float)` setter.

Reviewer is flagging it. The fix is symmetric with finding #2:

```python
def set_cooldown(self, seconds: float) -> None:
    """AD-468: public setter for the global proactive cooldown default."""
    self._cooldown = max(60.0, min(86400.0, float(seconds)))
```

Note that `set_agent_cooldown(agent_id, cooldown)` exists at `proactive.py:410` — that's per-agent. The new `set_cooldown` is for the global default, which is a different setter. Both should coexist.

**Action:** Add `set_cooldown` as a Section 4b. Replace the direct `_cooldown` assignment in Section 4 with the public setter.

### 4. `tomli_w` is not installed in the venv

The prompt imports:
```python
try:
    import tomli_w
except ImportError:
    tomli_w = None
```

Verified:
```
python -c "import tomli_w"
  ModuleNotFoundError: No module named 'tomli_w'

grep -n "tomli\|tomli_w\|tomli-w" pyproject.toml
  (no matches)
```

The fallback path leaves overrides un-persisted — `set()` would silently lose data on restart. Section 0 of the prompt should add `tomli-w` to `pyproject.toml` `[project.dependencies]` as part of the migration. The pragma-no-cover dance is the wrong primitive — runtime overrides MUST persist for the AD's value proposition to hold.

Two acceptable approaches:
- (a) Add `tomli-w>=1.0` to `pyproject.toml` dependencies. The fallback import becomes redundant; remove it. (Recommended.)
- (b) Use `json` instead of TOML. Runtime overrides are a small dict; JSON has stdlib write support. The prompt's "TOML for human-edit" rationale is weak — this file is written by the runtime, not edited manually. JSON also dodges the dependency.

**Action:** Either add `tomli-w` to `pyproject.toml` and drop the fallback, or switch to JSON. Surface the decision via DECISIONS.md per the prompt's own tracking section.

### 5. Section 5 import of `commands_config` is correct, but the SEARCH/REPLACE block uses a stale anchor

The prompt's Section 5 SEARCH for the import addition:
```python
    commands_introspection,
    commands_alert,
    commands_clearance,
```

Verified at `shell.py:22-24` ✓. Correct.

The handler-dict SEARCH:
```python
            "/explain":    lambda: self._handle_nl("what just happened?"),
```

Verified at `shell.py:286` ✓. Correct.

No issue here — calling out to Section 5's correctness for the audit trail.

---

## Recommended

### R1. `OVERRIDABLE_FIELDS` should be readable from outside the module

The prompt declares `OVERRIDABLE_FIELDS` as a module-level dict. The `/config` slash command consumes it via `rcs.known_fields()`. That's fine, but two test cases (`test_overridable_fields_known`, `test_set_override_unknown_field_rejected`) directly inspect `OVERRIDABLE_FIELDS`. Document the field as part of the public surface (drop the leading-underscore convention in this case — it's already not prefixed, so just confirm).

### R2. The `runtime.proactive_loop` reference at startup should guard for `None`

`proactive_loop: ProactiveCognitiveLoop | None` per `runtime.py:229` and is set during finalize. By the time AD-468's Section 4 runs (also in finalize), it should already be set, but guard anyway for defensive symmetry with the AD-679 pattern. One-line `if runtime.proactive_loop:` wrapper.

### R3. Add a verify-first line for the path layout

Section 1's "Verify-first" note correctly says `src/probos/runtime/` does not exist and the file should be flat at `src/probos/runtime_config_service.py`. Good. Add the same grep evidence to the verify-first footer:

```
ls src/probos/runtime/
  (does NOT exist — runtime.py is a flat file)
```

(The footer already has this — just confirming.)

### R4. Test 11 (`test_load_existing_file`) needs a TOML write helper

If switching to JSON per finding #4, this test simplifies. If staying with TOML, add a fixture that writes a known TOML payload using `tomli_w` — which means tomli_w must be a real test-time dependency.

---

## Nits

- The docstring on `_coerce` says `"unknown type"` for type errors but the prompt's typ allowlist includes only "float|int|bool|str". An unknown typ is a programmer error; the message could be sharper ("validate spec.typ against {float,int,bool,str}").
- The `bool` coercion accepts `"yes"|"on"` strings — fine, but document this in `OVERRIDE_SPEC.description` so operators don't get surprised.
- The handler-dict ordering (`/config` before `/explain`) is alphabetically inconsistent with the surrounding handlers (`/skill` then `/explain` then `/bridge`). Position has no effect; cosmetic.

---

## Verified

- `EventType.CONFIG_CHANGED` is absent in `events.py` — Section 0 introduces cleanly.
- `runtime.proactive_loop` IS a public attribute (`runtime.py:533, 229`).
- `class ProactiveCognitiveLoop` is at `proactive.py:146` ✓
- `commands_introspection`, `commands_alert`, `commands_clearance` all imported at `shell.py:22-24` ✓
- `/explain` handler at `shell.py:286` ✓ (SEARCH anchor is correct)
- `onboarding: OnboardingConfig` at `config.py:1526` ✓ (SEARCH anchor is correct)
- `_disclosure_router = disclosure_router` at `finalize.py:330` ✓ (insertion neighborhood)
- No EventType collision with AD-439/440/455/499 ✓

---

## Required Disposition

❌ **Not Ready.** Four Required findings, two of which (data_dir, tomli_w dependency) introduce architectural decisions the prompt currently glosses over. Build prompts must NOT defer architectural decisions to the Builder. Estimated rework: ~30 minutes architect time.

After fixes, re-pass review; expected verdict ⚠️ Conditional (then ✅ on re-review). The wiring sections require the most care here — Sections 0, 1, 2, 3 are clean.


---

## Second-Pass Review (2026-05-01)

**Verdict:** ✅ **Approved (with one Nit).** All 5 pass-1 Required findings cleanly resolved. JSON over TOML executed cleanly with no live `tomli/tomli_w/tomllib` imports. Public `data_dir` property + `set_cycle_interval`/`set_cooldown` setters all added correctly.

### Resolution Audit

| Pass-1 Required | Status | Evidence in revised prompt |
|---|---|---|
| #1 `runtime.data_dir` phantom | ✅ Resolved | Section 1a (lines 43-72) adds `@property def data_dir(self) -> Path`. Section 4 line 340 uses public property. |
| #2 `set_cycle_interval` phantom | ✅ Resolved | Section 1b (lines 74-104) adds `def set_cycle_interval(self, seconds: float) -> None`. Clamps to 10–3600s. |
| #3 `_cooldown` direct assignment | ✅ Resolved | Section 1b also adds `def set_cooldown(self, seconds: float) -> None` with 60–86400s clamp. Section 4 line 355 uses public setter. |
| #4 `tomli-w` dependency | ✅ Resolved | Section 1 imports `import json` only. `_load` uses `json.load`, `_save` uses `json.dump`. Default filename `runtime_overrides.json`. Verify-first footer line 600 confirms no `tomli` references in `pyproject.toml`. All `tomli/tomli-w` strings remaining in the prompt are in rationale/Revision text only. |
| #5 Section 5 anchors | ✅ Resolved | Anchors confirmed in footer; no change required. |

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| R1 `OVERRIDABLE_FIELDS` public | ✅ Applied — module-level, accessible to tests |
| R2 `proactive_loop is not None` guard | ✅ Applied at Section 4 line 348 |
| R3 verify-first path layout | ✅ Applied — `ls src/probos/runtime/` line 583 confirms flat layout |
| R4 test 11 helper | ✅ Simplified by JSON — no fixture dance needed |

### Cross-cutting Demeter uplift verified

- `runtime.runtime_config_service` (public) at line 345 — ✓
- `/config` slash command reads `getattr(runtime, "runtime_config_service", None)` — ✓
- No collision with existing `runtime.py` attributes — verified

### New Findings (introduced during revision)

1. **Nit (doc only): line 544 acceptance criterion still says `runtime_overrides.toml`.** The actual config default at line 312 is `runtime_overrides.json` and the revision section at line 613 documents the JSON switch. The acceptance criterion is the only stale `.toml` reference outside rationale text. Fix: change `"runtime_overrides.toml"` to `"runtime_overrides.json"` at line 544. Single-character-substring edit; non-blocking for Builder.

### Verified Against Revised Codebase Claims

- `runtime._data_dir` private at `runtime.py:244,289` — confirmed via footer ✓
- `ProactiveCognitiveLoop._interval`/`_cooldown` private at `proactive.py:170,171` — confirmed via footer ✓
- `runtime.proactive_loop` public at `runtime.py:229,533` — confirmed via footer ✓
- `runtime_config_service` absent from `runtime.py` today — verified ✓
- No `tomli` in `pyproject.toml` — confirmed via footer ✓

### Recommended Next Step

Ship to Builder. AD-468 establishes the `data_dir` and proactive-loop-setter pattern that AD-455 / AD-440 / AD-499 mirror — recommended second-build candidate after AD-499's fix lands and AD-439 ships.
