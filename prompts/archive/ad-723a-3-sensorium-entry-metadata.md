# AD-723a-3 — `SensoriumEntry` gains `injection_zone` + `wrapper` metadata

**AD:** AD-723a-3. **GH issue closed:** [#626](https://github.com/seangalliher/ProbOS/issues/626).
**Parent ADs:** AD-723 (sensorium dispatch unification), AD-723a-1 (DM_ONESHOT consumer migration, Wave 148), AD-723a-2 (WR branch migration — pending).
**Wave:** 160. **Estimated tests:** +7 pytest. **Estimated wall-time:** ~1.5h. **Risk:** LOW — additive, backward-compatible field extension on a frozen dataclass.

---

## Solution Overview

`SensoriumEntry` (defined at `src/probos/cognitive/cognitive_agent.py:96`) is the AD-723 dispatch-aware record describing how a sensorium injection is consumed across prompt-assembly paths (`CHAIN_BASELINE`, `DM_ONESHOT`, `WR_ONESHOT`). AD-723a-1 (Wave 148) migrated the DM branch but limited consumption to entries whose registered method ALREADY emits its own framing markers — those keys are tracked in `_DM_SELF_WRAPPED_KEYS: ClassVar[tuple[str, ...]]` at `cognitive_agent.py:472`. Today the tuple has TWO entries: `_avatar_self_observation`, `_intent_self_tag`.

Other DM-tagged entries (`_sensorium_temporal_context`, `_sensorium_working_memory`, `_sensorium_self_recognition`) have hand-rolled DM-side framing markers in `_build_user_message` (the `--- Temporal Awareness ---` heading, blank-line padding, etc.) that the registered methods don't emit. To migrate them cleanly into the dispatch path, the entry needs to declare:

1. **Where** in the prompt to render (`injection_zone`).
2. **How** to wrap the raw method output with framing (`wrapper`).

This AD ships those two fields and updates the dispatcher to apply the `wrapper` when present. `_DM_SELF_WRAPPED_KEYS` and `_WR_SELF_WRAPPED_KEYS` are NOT removed in this AD — they remain the v1 selector. Migration of individual entries off the tuple into zone/wrapper-driven dispatch is a separate AD-723a-4 forward marker per zone.

**Frozen dataclass discipline:** `SensoriumEntry` is `@dataclass(frozen=True)`. Field-ordering rule: defaulted fields must come AFTER non-defaulted fields. Current fields are `layer`, `description` (non-defaulted), then `paths`, `priority`, `output_key` (all defaulted). New fields are defaulted ⇒ append to the END of the field list.

**Wrapper callable shape:** `Callable[[str], str] | None`. Receives the raw method output (post-`output_key` mapping); returns the wrapped string. `None` means "no wrapping" (v1 default — preserves existing behavior).

**injection_zone semantics:** opaque string identifier. v1 reserved values: `"temporal_header"`, `"working_memory"`, `"post_episodic"`, `"self_recognition"`. The dispatcher does NOT route by zone in v1 — zone is observation-only metadata that consumers (the prompt-assembly site in `_build_user_message`) can query. The DM path migration (Wave 148) already iterates `_DM_SELF_WRAPPED_KEYS` and renders sequentially; zone-based ordering is a separate AD-723a-3a follow-up.

**Folded:** none.

---

## Files to Modify

| File | Lines | Why |
|---|---|---|
| `src/probos/cognitive/cognitive_agent.py` | `SensoriumEntry` class (line 95..115) | Append `injection_zone` + `wrapper` fields. |
| `src/probos/cognitive/cognitive_agent.py` | `_dispatch_sensorium_async` method | Apply `wrapper` to method output before storing. |
| `tests/test_ad723a3_sensorium_metadata.py` | NEW | 7 boundary tests. |

**Verified anchors:**
- `SensoriumEntry` class: `src/probos/cognitive/cognitive_agent.py:95-115` (frozen `@dataclass`).
- `SensoriumPath` enum: same module (verified — referenced at line 107 `paths: tuple[SensoriumPath, ...]`).
- `SENSORIUM_REGISTRY: ClassVar[dict[str, SensoriumEntry]]`: line 231-. Existing entries: 21 entries listed (lines 233-343).
- `_DM_SELF_WRAPPED_KEYS`: line 472, contains 2 entries (under AD-723a-3 forcing threshold of 3 — exact match for the documented trigger).
- `_dispatch_sensorium_async` method: Builder greps `def _dispatch_sensorium_async` in `cognitive_agent.py` to find exact line (its docstring already exists per Wave 148 / AD-723a-1).

---

## Section 1 — `SensoriumEntry` field extension

In `src/probos/cognitive/cognitive_agent.py` `SensoriumEntry` (around line 95-115), add two new fields at the END of the field list. Update the docstring with a one-paragraph note. Frozen-dataclass field-ordering preserved (all new fields have defaults).

**SEARCH (uses the unique `output_key: str | None = None` line as the anchor — verified single occurrence in `SensoriumEntry`):**

```python
    output_key: str | None = None
    """Key under which the entry's string output is stored in the merged dict.

    When ``None``, the entry's registered method MUST return ``dict[str, str]``
    or ``None`` (no single-key output). When set, the method MUST return
    ``str`` or ``None`` and the dispatcher stores ``result`` under
    ``output_key`` in the merged dict.
    """
```

**REPLACE with:**

```python
    output_key: str | None = None
    """Key under which the entry's string output is stored in the merged dict.

    When ``None``, the entry's registered method MUST return ``dict[str, str]``
    or ``None`` (no single-key output). When set, the method MUST return
    ``str`` or ``None`` and the dispatcher stores ``result`` under
    ``output_key`` in the merged dict.
    """
    injection_zone: str | None = None
    """AD-723a-3: opaque zone identifier describing where in the prompt the
    entry renders. v1 reserved values: ``temporal_header``, ``working_memory``,
    ``post_episodic``, ``self_recognition``. The dispatcher does NOT route by
    zone in v1 — observation metadata only; consumers query as needed.
    """
    wrapper: object | None = None
    """AD-723a-3: optional ``Callable[[str], str]`` that wraps the registered
    method's output with framing markers (e.g., ``--- Temporal Awareness ---``).

    Typed as ``object | None`` instead of ``Callable[[str], str] | None`` so
    the frozen dataclass remains hashable under all Python versions (some
    interpreters trip on the bound-method-vs-function hash divergence under
    ``frozen=True``). The dispatcher runtime-checks via ``callable(...)``.
    """
```

## Section 2 — Dispatcher applies `wrapper`

Find `_dispatch_sensorium_async` in `cognitive_agent.py` (Builder greps `def _dispatch_sensorium_async`). The current loop iterates registered entries, awaits each method, and stores results into a merged dict keyed by `entry.output_key` (or by the method name when `output_key is None`).

After the method-call returns its string result AND before storing into the merged dict, apply the wrapper when present:

```python
                # AD-723a-3: optional wrapper applied to string outputs.
                # Tier-2 — wrapper failure logs DEBUG and stores the
                # raw output unchanged.
                if (
                    isinstance(result, str)
                    and entry.wrapper is not None
                    and callable(entry.wrapper)
                ):
                    try:
                        result = entry.wrapper(result)
                    except Exception:
                        logger.debug(
                            "AD-723a-3: wrapper raised for entry %s; using raw output",
                            method_name, exc_info=True,
                        )
```

Builder reads `_dispatch_sensorium_async` end-to-end first; the exact insertion point is "after the method has been awaited and `result` is a string, but before the merged-dict assignment." Builder picks the matching line in the actual function body. Wrapper application MUST NOT run when `output_key is None` (dict-return contract — wrapping a dict makes no sense; the wrapper contract is string-in-string-out).

## Section 3 — Tests

`tests/test_ad723a3_sensorium_metadata.py` — 7 boundary tests:

1. `test_sensorium_entry_constructs_without_new_fields` — `SensoriumEntry(layer=..., description="...")` ⇒ `injection_zone is None`, `wrapper is None` (backward compat).
2. `test_sensorium_entry_with_zone_only` — `injection_zone="temporal_header"` ⇒ stored on the frozen instance.
3. `test_sensorium_entry_with_wrapper_only` — `wrapper=lambda s: f"[{s}]"` ⇒ stored, callable on retrieval.
4. `test_sensorium_entry_frozen_immutable` — attempting `entry.injection_zone = "x"` raises `FrozenInstanceError`.
5. `test_dispatcher_applies_wrapper_to_string_output` — register a stub entry with `wrapper=lambda s: f"--- A ---\n{s}"`, output_key=`"k"`; dispatch ⇒ merged dict has `"k": "--- A ---\nfoo"` when method returns `"foo"`.
6. `test_dispatcher_skips_wrapper_for_dict_output` — entry with `wrapper=...` AND `output_key is None`; method returns `{"k": "v"}` ⇒ wrapper NOT called, dict-return preserved.
7. `test_dispatcher_wrapper_exception_falls_back_to_raw` — wrapper raises ⇒ merged dict has the RAW method output, no exception bubbles.

Use the existing `_FakeAgent` / `_FakeCognitiveAgent` pattern from `tests/test_ad723*.py` (Builder verifies the test files exist; if `test_ad723.py` is canonical pattern, mirror its fixture shape).

---

## What This Does NOT Change

- `_DM_SELF_WRAPPED_KEYS` and `_WR_SELF_WRAPPED_KEYS` — preserved as the v1 selector. Migration of individual entries off these tuples is AD-723a-3a (per-entry, separate ADs).
- Existing 21 entries in `SENSORIUM_REGISTRY` — none gain `injection_zone` or `wrapper` in this AD (additive field default — entries instantiate identically).
- Dispatcher behavior for entries without `wrapper` — byte-identical.
- AD-731 invariant.

---

## Verification Commands

```powershell
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad723a3_sensorium_metadata.py -v -n 0 | Select-Object -Last 25
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad723*.py -v -n 0 | Select-Object -Last 30
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile | Select-Object -Last 3
```

No UI files modified — `npm run build` not required.

---

## Tracker Updates

- **PROGRESS.md:** `AD-723a-3 — SensoriumEntry gains injection_zone + wrapper metadata (+7 pytest tests; closes #626). Backward-compatible — both fields default None. Dispatcher applies wrapper to string outputs only (dict-return contract unchanged). _DM_SELF_WRAPPED_KEYS still the v1 selector; per-entry migration deferred to AD-723a-3a.`
- **roadmap.md:** remove #626; add forward markers AD-723a-3a (per-entry migration off `_DM_SELF_WRAPPED_KEYS` once 3+ entries have `wrapper` set), AD-723a-3b (zone-driven ordering — dispatcher iterates by `injection_zone` when consumer requests).
- **DECISIONS.md:** append `### AD-723a-3 — SensoriumEntry metadata extension`.

---

## License Disposition

All-internal Apache 2.0. No new deps.

---

## Forward markers (technical-trigger language)

- **AD-723a-3a — Per-entry migration off `_DM_SELF_WRAPPED_KEYS`.** Advances when 3+ existing entries gain `wrapper` set AND consumer code at `_build_user_message:5977-5990` needs zone-driven iteration instead of the tuple selector.
- **AD-723a-3b — Zone-driven ordering.** Advances when prompt-assembly needs deterministic zone ordering across DM and WR paths (currently the registry-insertion order drives iteration, which is fragile across edits).

---

## Acceptance Criteria

- ✅ `SensoriumEntry` gains two fields with `None` defaults.
- ✅ Existing 21 registry entries instantiate identically (no SEARCH/REPLACE inside `SENSORIUM_REGISTRY`).
- ✅ Dispatcher applies `wrapper` only on string outputs.
- ✅ 7 tests pass.
- ✅ All existing AD-723 / AD-723a-1 tests stay green UNCHANGED.
- ✅ Full gate green.
- ✅ Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-14)

```
SensoriumEntry class:
  src/probos/cognitive/cognitive_agent.py:95: @dataclass(frozen=True)
  src/probos/cognitive/cognitive_agent.py:96: class SensoriumEntry:
  src/probos/cognitive/cognitive_agent.py:107: paths: tuple[SensoriumPath, ...] = ()
  src/probos/cognitive/cognitive_agent.py:108: priority: int = 0
  src/probos/cognitive/cognitive_agent.py:109: output_key: str | None = None

_DM_SELF_WRAPPED_KEYS (2 entries — matches AD-723a-3 forcing-function trigger threshold "3+" once a third is added; AD-723 issue #626 explicitly cites this trigger):
  src/probos/cognitive/cognitive_agent.py:472: _DM_SELF_WRAPPED_KEYS: ClassVar[tuple[str, ...]] = (

SENSORIUM_REGISTRY (21 entries):
  src/probos/cognitive/cognitive_agent.py:231: SENSORIUM_REGISTRY: ClassVar[dict[str, "SensoriumEntry"]] = {

DM dispatcher consumer site:
  src/probos/cognitive/cognitive_agent.py:5977-5990 (uses _DM_SELF_WRAPPED_KEYS today)
```
