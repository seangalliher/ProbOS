# AD-723a-2 — WR branch consumer-side sensorium dispatch migration

**Wave:** 161
**Closes:** #625
**Status:** ready to build
**Dependencies:** AD-723a-1 (Wave 148 commit `e066c0b5` — DM consumer-side migration; `_DM_SELF_WRAPPED_KEYS` ClassVar pattern).
**Estimated tests:** +6 pytest, 0 vitest.
**Scope tag:** Server-only. Pure internal refactor. No new deps. Apache 2.0.

---

## Problem

Wave 148 (AD-723a-1) migrated the **DM** branch of `CognitiveAgent._build_user_message` to consume `SENSORIUM_REGISTRY` via the dispatcher (`_dispatch_sensorium_async(SensoriumPath.DM_ONESHOT, ...)`). It deferred the **WR** (Ward Room) branch to AD-723a-2 because:

- WR branch had 15 hand-rolled fragments vs DM's 13.
- WR had 0 self-wrapped sensorium entries that mapped cleanly to the `_DM_SELF_WRAPPED_KEYS` pattern at the time.

AD-723a-3 (Wave 160) shipped `SensoriumEntry.injection_zone` + wrapper metadata. The self-wrapped surface is still the v1 migration scope; non-self-wrapped fragments remain hand-rolled until AD-723a-3a operationalizes per-entry migration.

This AD ships the WR sibling of AD-723a-1: a single dispatcher call site for self-wrapped WR entries, gated by a new `_WR_SELF_WRAPPED_KEYS` ClassVar. **Byte parity with current WR output is required.**

---

## Solution overview

1. Add `_WR_SELF_WRAPPED_KEYS: ClassVar[tuple[str, ...]] = ()` to `CognitiveAgent`. v1 ships with the tuple **empty** — there are currently 0 self-wrapped WR entries. The infrastructure is in place; the first WR-only self-wrapped registry entry will trigger non-empty values without further code changes.
2. In `_build_user_message`'s WR branch, add a single `_dispatch_sensorium_async(SensoriumPath.WR_ONESHOT, observation)` call inside an outer try/except (Tier-2 dispatcher degrade — matches AD-723a-1 contract).
3. The dispatch result is filtered by `_WR_SELF_WRAPPED_KEYS` before injection (the v1 selector pattern). When the tuple is empty, the filter yields nothing — net effect is a NO-OP at runtime today, **byte-identical output to HEAD**.
4. Hand-rolled WR fragments (channel header, thread title, recent messages, etc.) remain untouched. AD-723a-3a covers per-entry migration of non-self-wrapped fragments.

**This AD is intentionally a "wiring without consumers" change.** It establishes the call site and selector ClassVar so future WR-only registry additions land cleanly. The byte-parity tests guarantee zero behavior change in the current registry shape.

---

## Section 1 — Class constant + call site (`src/probos/cognitive/cognitive_agent.py`)

Find the existing DM-branch ClassVar declaration (Wave 148 commit `e066c0b5` added this):

```python
    _DM_SELF_WRAPPED_KEYS: ClassVar[tuple[str, ...]] = (
        "_avatar_self_observation",
        "_intent_self_tag",
    )
```

Add a sibling immediately below:

```python
    # AD-723a-2: WR (Ward Room) sibling of _DM_SELF_WRAPPED_KEYS.
    # Empty in v1 — no self-wrapped sensorium entries currently target
    # SensoriumPath.WR_ONESHOT exclusively. New entries with
    # ``paths=(WR_ONESHOT,)`` and self-wrapped output extend this tuple.
    _WR_SELF_WRAPPED_KEYS: ClassVar[tuple[str, ...]] = ()
```

Then locate the WR branch in `_build_user_message`. Use `grep` against the file for the WR-channel structural marker. The WR branch lives in a conditional below the DM branch — pattern-match against the existing DM dispatcher call:

```python
            try:
                sensorium = await self._dispatch_sensorium_async(
                    SensoriumPath.DM_ONESHOT, observation,
                )
                # ... filter by _DM_SELF_WRAPPED_KEYS ...
            except Exception:
                # Tier-2 degrade.
                logger.warning(...)
```

The WR branch needs the analogous block. **Read the DM branch dispatcher block at HEAD before applying** — the exact filter/inject shape is what we mirror. Pseudo-pattern:

```python
            # AD-723a-2: WR sibling of the DM dispatcher path. Selector
            # ``_WR_SELF_WRAPPED_KEYS`` is currently empty — the iteration
            # below is a no-op until a future AD adds entries. Keeping
            # the call site present means new entries cost zero diff.
            try:
                wr_sensorium = await self._dispatch_sensorium_async(
                    SensoriumPath.WR_ONESHOT, observation,
                )
                for key in self._WR_SELF_WRAPPED_KEYS:
                    fragment = wr_sensorium.get(key)
                    if fragment:
                        parts.append(fragment)
            except Exception:
                # Tier-2: dispatcher failure must not break WR prompt assembly.
                logger.warning(
                    "AD-723a-2: WR sensorium dispatch raised for agent=%s; "
                    "falling through to hand-rolled WR fragments",
                    self.id, exc_info=True,
                )
```

**Implementation note:** the exact insertion point (which local variable replaces `parts` and `observation`) depends on the WR branch's current local-variable names. Read lines around the WR branch construction and adapt to match. Do NOT change variable names in the existing code.

---

## Section 2 — Tests `tests/test_ad723a_2_wr_consumer_migration.py`

Six tests, mirroring AD-723a-1's test suite shape (see `tests/test_ad723a_1_consumer_migration.py` for the template — same `_FakeRuntime` / `_FakeAgent` patterns).

1. **`test_wr_branch_invokes_dispatcher_once`** — patch `_dispatch_sensorium_async` to a `MagicMock` that returns `{}`; call `_build_user_message` on the WR path; assert the mock was called exactly once with `SensoriumPath.WR_ONESHOT` as the first positional arg.
2. **`test_wr_branch_empty_selector_yields_byte_parity`** — capture WR output BEFORE the AD-723a-2 change (snapshot a known message), then after; assert string equality. **Byte parity is the primary regression gate.**
3. **`test_wr_branch_self_wrapped_entry_injects_when_added`** — monkey-patch `_WR_SELF_WRAPPED_KEYS = ("_test_marker",)` and make the dispatcher return `{"_test_marker": "[WR marker]"}`; assert the marker appears in the rendered WR prompt.
4. **`test_wr_dispatcher_failure_tier2_degrade`** — patch `_dispatch_sensorium_async` to raise `RuntimeError("boom")`; assert the WR prompt is still built (no exception propagated), and a WARNING is logged with substring `"AD-723a-2"`.
5. **`test_wr_branch_does_not_call_dm_keys`** — register a sensorium entry with key `"_avatar_self_observation"` (a `_DM_SELF_WRAPPED_KEYS` member) and `paths=(WR_ONESHOT,)`; with `_WR_SELF_WRAPPED_KEYS = ()`, the entry should NOT appear in WR output — confirms the WR selector is independent.
6. **`test_dm_branch_unchanged`** — regression test: run a DM-path `_build_user_message` with current `_DM_SELF_WRAPPED_KEYS = ('_avatar_self_observation', '_intent_self_tag')`, assert AD-723a-1 byte parity (use the same fixture/expected string as `test_ad723a_1_consumer_migration.py` Test 3).

**Test isolation rule:** each test creates its own `_FakeAgent` / `_FakeRuntime`. Tests must pass under `-n 4 --dist=loadfile` AND `-n 0`.

**AD-723a-1 regression gate:** before marking this AD complete, run `pytest tests/test_ad723a_1_consumer_migration.py -v -n 0` and verify all 6 prior tests still pass. AD-723a-2 MUST NOT regress AD-723a-1.

---

## Standing rules (must comply)

- **BF-274** — Single `replace_string_in_file` for the ClassVar addition; separate single `replace_string_in_file` for the dispatcher call insertion. Don't combine into `multi_replace_string_in_file`.
- **BF-280** — N/A; no subprocess.
- **BF-282** — N/A.
- **BF-286** — N/A.
- **AD-731 invariant** — N/A; this AD touches no attachment paths.
- **AD-738b / UI gate** — N/A (no `ui/src/**` files modified).
- **AD-722c-3 forward-marker style** — technical triggers only.
- **No emoji** — ASCII log messages.
- **Phantom-API guard** — `SensoriumPath.WR_ONESHOT` is verified to exist at `src/probos/cognitive/cognitive_agent.py:88`. `SensoriumLayer` (PROPRIOCEPTION / INTEROCEPTION / EXTEROCEPTION) is a DIFFERENT enum at `cognitive_agent.py:54` and is NOT used in this AD. Do not import or reference `SensoriumLayer` here.

---

## Hard-stops (escalate before applying)

- If reading the WR branch of `_build_user_message` reveals it has already been migrated by an out-of-band commit since AD-723a-1, STOP and surface — the migration would be a double-apply.
- If `_DM_SELF_WRAPPED_KEYS` is no longer present at the expected line (refactored / renamed), STOP — the sibling pattern depends on the parent existing.
- If AD-723a-1 tests (`tests/test_ad723a_1_consumer_migration.py`) fail at HEAD before any change, STOP — work on AD-682-class quarantine, not this AD.

---

## Forward markers (file in `docs/development/roadmap.md`)

- **AD-723a-3a** — Per-entry migration of non-self-wrapped fragments (channel header, thread title, recent messages) using `SensoriumEntry.injection_zone` from AD-723a-3. **Trigger:** AD-723a-3 wrapper metadata covers at least two non-self-wrapped fragment shapes (string-return AND list-return), AND `_DM_SELF_WRAPPED_KEYS` tuple reaches 3+ entries demonstrating the v1 selector pattern at scale.
- **AD-723a-2a** — Add a sensorium entry with `paths=(WR_ONESHOT,)` and self-wrapped output to populate `_WR_SELF_WRAPPED_KEYS` for the first real consumer. **Trigger:** any new WR-only context fragment is proposed (no current candidate as of Wave 161).

---

## Acceptance criteria

1. `_WR_SELF_WRAPPED_KEYS: ClassVar[tuple[str, ...]] = ()` exists in `CognitiveAgent`.
2. WR branch of `_build_user_message` invokes `_dispatch_sensorium_async(SensoriumPath.WR_ONESHOT, ...)` once, inside an outer try/except with Tier-2 WARNING log.
3. **Byte-parity test passes** — current WR prompts unchanged.
4. 6 new pytest tests pass.
5. AD-723a-1 6 prior tests still pass (regression gate).
6. `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile` green.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Tracking

- **PROGRESS.md** — Wave 161 in-flight; close #625.
- **DECISIONS.md** — AD-723a-2 entry; reference AD-723a-1 precedent.
- **docs/development/roadmap.md** — forward markers per above.

---

## Verified Against Codebase (2026-05-15)

```
src/probos/cognitive/cognitive_agent.py:
  54: class SensoriumLayer(StrEnum):            # AD-666 — NOT used in this AD
  62: class SensoriumPath(StrEnum):             # AD-723 — THE enum we use
  80:     DM_ONESHOT = "dm_oneshot"
  88:     WR_ONESHOT = "wr_oneshot"
  251:    paths=(SensoriumPath.CHAIN_BASELINE, SensoriumPath.DM_ONESHOT, SensoriumPath.WR_ONESHOT),
  263:    paths=(SensoriumPath.CHAIN_BASELINE, SensoriumPath.WR_ONESHOT),
  269:    paths=(SensoriumPath.WR_ONESHOT,),
  487:    _DM_SELF_WRAPPED_KEYS: ClassVar[tuple[str, ...]] = (   # AD-723a-1 ClassVar; sibling pattern source
  5920:   async def _build_user_message(self, observation: dict) -> str:   # WR branch lives here below DM branch
  6004:       # call site. v1 renders only keys in _DM_SELF_WRAPPED_KEYS at this
  6015:                for _key in self._DM_SELF_WRAPPED_KEYS:

git log: e066c0b5 — AD-723a-1 (Wave 148) DM consumer-side sensorium dispatch migration
        introduced _DM_SELF_WRAPPED_KEYS ClassVar in cognitive_agent.py.

tests/test_ad723a_1_consumer_migration.py: 273 lines (test template to mirror).
```
