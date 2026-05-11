# AD-723a-1 — DM Consumer-Side Sensorium Dispatch Migration

**Status:** Ready for Builder
**Dependencies:** AD-723 (producer-side dispatch, shipped Wave 144)
**GH issue:** [#617](https://github.com/seangalliher/seangalliher/ProbOS/issues/617)
**Estimated tests added:** ≥5 in new `tests/test_ad723a_1_consumer_migration.py`

## Problem

Wave 144 shipped `SENSORIUM_REGISTRY` as a dispatch table on the producer side. Every method registers an entry with a `paths` tuple. Chain paths (`CHAIN_BASELINE`, `CHAIN_EXTENSIONS`, `CHAIN_SITUATION`) iterate via `_dispatch_sensorium_sync`. The async dispatcher `_dispatch_sensorium_async` ships alongside, parked for DM/WR.

The DM branch of `_build_user_message` (`src/probos/cognitive/cognitive_agent.py:5740-5865`) does NOT use the async dispatcher. It hand-rolls every fragment, including two AD-722 sensorium injections at lines ~5805-5821:

```python
try:
    _avatar_block = self._build_avatar_self_observation(observation)
    if _avatar_block:
        parts.append(_avatar_block)
        parts.append("")
    _intent_tag_line = self._build_intent_self_tag_instruction()
    if _intent_tag_line:
        parts.append(_intent_tag_line)
        parts.append("")
except Exception:
    logger.debug(
        "AD-722: avatar self-observation injection in DM path failed",
        exc_info=True,
    )
```

Today's AD-722 BFs proved the cost: every new DM-side sensorium has to be wired in two places (registry + manual `_build_user_message` injection).

## Solution

Migrate the AD-722 injection block to consume `_dispatch_sensorium_async`. v1 limits the migration to entries that already produce **self-wrapped output** — output that can be appended to `parts` without DM-specific framing markers. Today that's two entries:
- `_build_avatar_self_observation` → `output_key="_avatar_self_observation"`
- `_build_intent_self_tag_instruction` → `output_key="_intent_self_tag"`

A class-level constant `_DM_SELF_WRAPPED_KEYS` enumerates which dispatched keys render at the AD-722 zone in v1. Future self-wrapped DM sensorium additions only need to register and add their `output_key` to this tuple. When the tuple grows to 3+ keys, that's the forcing function for AD-723a-3 (position metadata on entries).

## Files touched

| File | Change |
|---|---|
| `src/probos/cognitive/cognitive_agent.py` | Add `_DM_SELF_WRAPPED_KEYS` class constant; replace AD-722 manual injection block. |
| `tests/test_ad723a_1_consumer_migration.py` | NEW — 6 tests. |
| `PROGRESS.md` | Update. |
| `docs/development/roadmap.md` | Mark shipped + add 723a-2/a-3 rows. |

---

## Section 1 — `_DM_SELF_WRAPPED_KEYS` class constant

The constant lives immediately after the `SENSORIUM_REGISTRY` declaration. Use `ClassVar` to keep dataclass-style typing consistent.

**SEARCH:**
```python
        "_build_user_message": SensoriumEntry(
            layer=SensoriumLayer.EXTEROCEPTION,
            description="Primary prompt assembly (DM/WR paths) — orchestrator (inventory)",
        ),
    }

    def __init__(self, **kwargs: Any) -> None:
```

**REPLACE:**
```python
        "_build_user_message": SensoriumEntry(
            layer=SensoriumLayer.EXTEROCEPTION,
            description="Primary prompt assembly (DM/WR paths) — orchestrator (inventory)",
        ),
    }

    # AD-723a-1 (Wave 148): keys from the DM_ONESHOT dispatch result that
    # render at the post-working-memory / pre-episodic injection zone
    # (where AD-722 currently injects). v1 limits migration to entries
    # whose registered method returns a self-wrapped block — i.e., output
    # that needs no DM-side framing markers. Other DM-tagged entries
    # (_temporal_context, _working_memory_context, _self_recognition_cue)
    # have hand-rolled DM-side wrappers that differ from registered
    # output; they migrate when AD-723a-3 lands position + wrapper
    # metadata on SensoriumEntry. When this tuple grows to 3+ keys,
    # AD-723a-3 becomes the forcing function.
    _DM_SELF_WRAPPED_KEYS: ClassVar[tuple[str, ...]] = (
        "_avatar_self_observation",
        "_intent_self_tag",
    )

    def __init__(self, **kwargs: Any) -> None:
```

---

## Section 2 — Replace AD-722 manual injection with dispatcher call

The replacement preserves exact ordering and blank-line separators so AD-722 callers see a byte-identical prompt.

**SEARCH:**
```python
            # AD-722 BF (2026-05-10): avatar self-observation on the DM one-shot path.
            # The chain path picks this up via _build_cognitive_baseline, but DMs
            # bypass cognitive_state entirely and assemble inline here. Method is
            # feature-gated by avatar_telemetry.inject_into_agent_context and
            # returns "" when the cached snapshot is missing — safe to call.
            try:
                _avatar_block = self._build_avatar_self_observation(observation)
                if _avatar_block:
                    parts.append(_avatar_block)
                    parts.append("")
                # AD-722a: append the self-tag instruction (default OFF).
                _intent_tag_line = self._build_intent_self_tag_instruction()
                if _intent_tag_line:
                    parts.append(_intent_tag_line)
                    parts.append("")
            except Exception:
                logger.debug(
                    "AD-722: avatar self-observation injection in DM path failed",
                    exc_info=True,
                )
```

**REPLACE:**
```python
            # AD-723a-1 (Wave 148): dispatch self-wrapped DM_ONESHOT sensorium
            # entries. Replaces the prior hand-rolled AD-722 + AD-722a manual
            # call site. v1 renders only keys in _DM_SELF_WRAPPED_KEYS at this
            # zone (post-working-memory, pre-episodic); other DM-tagged entries
            # stay inline pending AD-723a-3 (position + wrapper metadata).
            # The dispatcher iterates SENSORIUM_REGISTRY entries whose paths
            # include DM_ONESHOT, awaiting async-registered methods and
            # tolerating per-method failure (Tier-2 degrade inside the
            # dispatcher itself).
            try:
                _dm_sensorium = await self._dispatch_sensorium_async(
                    SensoriumPath.DM_ONESHOT, observation,
                )
                for _key in self._DM_SELF_WRAPPED_KEYS:
                    _block = _dm_sensorium.get(_key)
                    if _block:
                        parts.append(_block)
                        parts.append("")
            except Exception:
                logger.debug(
                    "AD-723a-1: DM sensorium dispatch failed; "
                    "degrading (Tier-2: skipping injection zone).",
                    exc_info=True,
                )
```

**Builder verification before applying:**

The grep'd line numbers (5805-5821 in the current source) may have shifted. Builder MUST run `grep -n "AD-722 BF (2026-05-10): avatar self-observation on the DM one-shot path" src/probos/cognitive/cognitive_agent.py` to confirm the exact insertion point before SEARCH/REPLACE.

Confirm `_dispatch_sensorium_async` signature with:
```
grep -n "async def _dispatch_sensorium_async" src/probos/cognitive/cognitive_agent.py
```

Expected signature: `async def _dispatch_sensorium_async(self, path: SensoriumPath, observation: dict[str, Any]) -> dict[str, str]`. If signature differs, surface to Architect.

---

## Section 3 — Tests

Create `tests/test_ad723a_1_consumer_migration.py`. Mirror the stub-agent pattern from `tests/test_ad722a_divergence_detector.py` and the registry-monkeypatch pattern from `tests/test_ad723_sensorium_dispatch.py`.

### Required tests (6 total)

1. **`test_dm_dispatch_includes_avatar_block_when_enabled`**
   - Stub agent with `inject_into_agent_context=True` + cached `_last_self_avatar_snap`.
   - Build `direct_message` observation. Call `await agent._build_user_message(observation)`.
   - Assert: result contains the avatar block (`"Your current avatar state:"`) at the AD-722 zone (post-working-memory, pre-`"Captain says:"`).

2. **`test_dm_dispatch_omits_avatar_block_when_disabled`**
   - Stub agent with `inject_into_agent_context=False`.
   - Assert: `"Your current avatar state:"` not in prompt; `"Captain says:"` still present.

3. **`test_dm_dispatch_byte_parity_with_direct_method_call`**
   - Compare `await agent._build_user_message(obs)` against a manually-assembled reference prompt that calls `_build_avatar_self_observation(obs)` and `_build_intent_self_tag_instruction()` directly and threads the result through the same `parts.append(...)` ordering. Byte-equal.

4. **`test_dm_dispatch_picks_up_new_registered_entry`**
   - Monkeypatch `CognitiveAgent.SENSORIUM_REGISTRY` to add a stub entry (`paths=(SensoriumPath.DM_ONESHOT,)`, `output_key="_test_block"`).
   - Monkeypatch `_DM_SELF_WRAPPED_KEYS` to include `"_test_block"`.
   - Register a stub method returning `"STUB-OUTPUT"`.
   - Assert: `"STUB-OUTPUT"` appears at the injection zone.

5. **`test_dm_dispatch_tier2_degrade_on_dispatcher_failure`**
   - Monkeypatch `_dispatch_sensorium_async` to raise `RuntimeError`.
   - Build DM prompt; capture log.
   - Assert: no exception leaks, prompt still ends with `"Captain says:"`, `logger.debug` call contains `"AD-723a-1: DM sensorium dispatch failed"`.

6. **`test_no_direct_avatar_method_call_remains_in_build_user_message`** (single-call-site invariant)
   - Static check: `inspect.getsource(CognitiveAgent._build_user_message)` does NOT contain `"_build_avatar_self_observation("` or `"_build_intent_self_tag_instruction("` as method-call patterns.
   - This is the regression gate that prevents re-introducing the hand-rolled call site.

---

## What this does NOT change

- **Producer side.** `SENSORIUM_REGISTRY`, `_dispatch_sensorium_sync`, `_dispatch_sensorium_async`, all `_sensorium_*` wrappers — untouched.
- **WR branch of `_build_user_message`.** Deferred to AD-723a-2.
- **`_build_avatar_self_observation` and `_build_intent_self_tag_instruction` method bodies.** Untouched.
- **Other DM hand-rolled fragments** (boot-camp ship state, temporal, cognitive zone, introspective telemetry, working memory, episodic memories, Oracle context, source attribution, session history, active game, Captain-says line) — 11 fragments stay inline.
- **Chain paths** — already consume the registry; no change.
- **Configuration.** No new fields. Dispatch is unconditional infrastructure.

---

## Forward markers (file at retrospective)

- **AD-723a-2** — WR branch consumer migration. WR has 15 hand-rolled fragments. **Forcing function:** when WR gains a registered entry whose registered output is self-wrapped.
- **AD-723a-3** — position + wrapper metadata on `SensoriumEntry`. Adds `injection_zone: str | None` and optional `wrapper: Callable[[str], str] | None`. **Forcing function:** when `_DM_SELF_WRAPPED_KEYS` reaches 3+ keys OR when AD-723a-2 needs to render a non-self-wrapped entry.

---

## Engineering Principles compliance

- **(S)** `_DM_SELF_WRAPPED_KEYS` owns "which dispatch keys render at the DM zone."
- **(O)** Future self-wrapped DM sensorium additions extend via registry + constant append, not by editing `_build_user_message`.
- **DRY** — removes hand-rolled call pair duplicating registry information.
- **Three-tier exception handling** — outer `try/except` around dispatcher call is Tier-2 (log-and-degrade); inner per-method Tier-2 already lives inside `_dispatch_sensorium_async`.
- **Async hygiene** — `await` on `_dispatch_sensorium_async`; no fire-and-forget.
- **Type annotations** — `_DM_SELF_WRAPPED_KEYS: ClassVar[tuple[str, ...]]`.
- **Logging quality** — Log message includes what failed, what the system did, and AD tag for forensics.

---

## Verified Against Codebase (2026-05-10, HEAD bcc3209)

```
grep -n "SENSORIUM_REGISTRY" src/probos/cognitive/cognitive_agent.py
  188: SENSORIUM_REGISTRY: ClassVar[dict[str, "SensoriumEntry"]] = {

grep -n "_dispatch_sensorium_async" src/probos/cognitive/cognitive_agent.py
  4719: #   * ``_dispatch_sensorium_async`` — DM / WR one-shot paths.
  4825: async def _dispatch_sensorium_async(

grep -n "_build_avatar_self_observation" src/probos/cognitive/cognitive_agent.py
  300: "_build_avatar_self_observation": SensoriumEntry(
  2938: def _build_avatar_self_observation(self, observation: dict) -> str:
  5808: _avatar_block = self._build_avatar_self_observation(observation)

grep -n "_build_intent_self_tag_instruction" src/probos/cognitive/cognitive_agent.py
  291: "_build_intent_self_tag_instruction": SensoriumEntry(
  3016: def _build_intent_self_tag_instruction(self, observation: dict | None = None) -> str:
  5814: _intent_tag_line = self._build_intent_self_tag_instruction()

grep -n "async def _build_user_message" src/probos/cognitive/cognitive_agent.py
  5720: async def _build_user_message(self, observation: dict) -> str:

grep -n "DM_ONESHOT" src/probos/cognitive/cognitive_agent.py
  80: DM_ONESHOT = "dm_oneshot"
  291: paths=(..., SensoriumPath.DM_ONESHOT),    # _build_intent_self_tag_instruction
  300: paths=(..., SensoriumPath.DM_ONESHOT),    # _build_avatar_self_observation
```

**Fragment counts:**
- DM branch (lines 5740-5865): 13 hand-rolled fragments.
- WR branch (lines 5867-6045): 15 hand-rolled fragments.

**Wave-10 rule applied:** WR exceeds 8-fragment threshold AND has zero self-wrapped DM_ONESHOT-equivalent entries → defer entire WR migration to AD-723a-2.

---

## Acceptance criteria

1. All 6 new tests pass.
2. Pre-existing tests stay green (especially `tests/test_ad722*` byte-parity).
3. Full parallel gate green (modulo 4 documented pre-existing flakes).
4. Phantom-API precheck zero new phantoms.
5. Single-call-site invariant test 6 passes — no `_build_avatar_self_observation(` or `_build_intent_self_tag_instruction(` calls in `_build_user_message` source.
6. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
