# Review: AD-724 — DM Path Hardening (724-1 + 724-2 + 724-5)
**Verdict:** ⚠️ Conditional
**Duplicate `DmSanityGateConfig` class will break existing tests when new fields are read by `check_repetition` / `process()`.**

## Required (must fix before building)

1. **Two `DmSanityGateConfig` classes; prompt only edits one.** Live grep:
   - `src/probos/cognitive/dm_sanity_gate.py:49` — `class DmSanityGateConfig(BaseModel):` (the gate's internal config, used by `DmSanityGate.__init__` default and by existing `tests/test_ad724_dm_sanity_gate.py:16-22`).
   - `src/probos/config.py:3236` — `class DmSanityGateConfig(BaseModel):  # AD-724` (the SystemConfig field).
   The prompt's "Files to Modify" table and Section 2 only extend the `config.py` version with `repetition_similarity_threshold`, `retry_on_rejection`, `retry_warnings`. But Section 1 adds reads of `self.config.repetition_similarity_threshold` inside `check_repetition`, and Section 2 adds reads of `self.config.retry_on_rejection` / `self.config.retry_warnings` inside `process()`. Existing test at `tests/test_ad724_dm_sanity_gate.py:127` instantiates `DmSanityGate(DmSanityGateConfig(enabled=False))` — its `DmSanityGateConfig` is the `dm_sanity_gate.py` version, which after this prompt will lack the three new fields. Every existing test that calls `gate.process(...)` will `AttributeError` on the new field reads.
   **Fix:** Either (a) add the same three fields to `dm_sanity_gate.py` `DmSanityGateConfig` (preferred — keeps the local cluster invariant noted in the AD-724 archive prompt: "Do not split DmSanityGate, DmSanityGateConfig, and DmSanityResult across multiple files"), OR (b) delete the `dm_sanity_gate.py` duplicate and have it import `DmSanityGateConfig` from `probos.config`. The Files to Modify table must reflect whichever path is chosen.

## Recommended (should fix)

1. **`apply_dm_sanity` parameter typing.** Helper signature is `apply_dm_sanity(runtime: object, agent_id: str, text: str)`. Per the Engineering Principles in [.github/copilot-instructions.md](.github/copilot-instructions.md#L78-L83), public APIs must have full type annotations. Use a `TYPE_CHECKING`-guarded `RuntimeOS` import and annotate as `runtime: "RuntimeOS"` (or a narrow `Protocol` declaring `dm_sanity_gate: DmSanityGate | None`).

2. **Repetition cache poisoning across the retry boundary.** `gate.process()` updates `_last_reply_by_agent[agent_id]` to the cleaned text on every call where `cleaned.strip()` is truthy ([dm_sanity_gate.py:243-244](src/probos/cognitive/dm_sanity_gate.py#L243-L244)). The DM router calls `process()` twice in the retry path: initial reply (rejected) → cache := original; retry → similarity check compares retry against the rejected original. If the agent's retry phrasing is similar (likely on a `length_floor` retry), `repetition` will fire on the retry and the operator sees the warning even though the gate's intent was to give the agent a clean second shot. Either (a) revert the cache when `should_retry=True` before dispatching the retry, or (b) pass an explicit `skip_repetition` flag into the retry's `process()` call. Add a test: `test_724_1_retry_does_not_trigger_repetition_against_rejected_original`.

3. **Missing test for "retry-fires-warnings still ships single retry."** The prompt text in Section 2 says "the gate again, but honor its result without a SECOND retry," but no listed test asserts the router's call-count invariant when the retry's own response also fires warnings. Add a test: `test_724_1_retry_with_warning_does_not_loop` (mock `intent_bus.send` to return text that fails `length_floor`; assert `intent_bus.send` call_count == 2, not 3+).

4. **`is_retry: True` in retry IntentMessage params is dead data.** No documented consumer reads it. Either drop the key or document its purpose (agent-side rate-limit suppression? log tagging?). Currently it inflates the params dict for nothing.

5. **Move `from probos.cognitive.dm_sanity_gate import apply_dm_sanity` to module top of `proactive.py`.** Both `_extract_and_execute_actions` and `_extract_and_execute_replies` are hot paths in proactive cycles. Function-local imports there break the project's standing pattern ("import order: stdlib → third-party → local, separated by blank lines"). Module cache makes it cheap, but the style violation is unnecessary.

## Nits (style/minor)

1. Verification footer's `pip show rapidfuzz → not installed` callout is well-placed for license hygiene; mirror this format in future ADs that consider third-party deps.
2. `_TAG_NOISE_RE` lists hardcoded tags (`CHALLENGE|MOVE|REPLY|/REPLY|DM|/DM|NOTEBOOK|/NOTEBOOK`). When new structured tags are introduced (AD-NN+ probable), this regex must be updated. Worth a brief comment pointing at the registry of tag types if one exists, or a forward-marker note.
3. The "Optional 6 more if scope allows" section gives the Builder room to overshoot the dispatch's `+12 to +18` upper bound. Consider locking the test count to a single number (15) so the post-wave delta check has an unambiguous target.

## Verified (looks good)

- `class DmSanityGateConfig(BaseModel):  # AD-724` at [src/probos/config.py:3236](src/probos/config.py#L3236) — confirmed.
- `dm_sanity_gate: DmSanityGateConfig = Field(default_factory=DmSanityGateConfig)  # AD-724` at [src/probos/config.py:3332](src/probos/config.py#L3332) — confirmed.
- `self.dm_sanity_gate: DmSanityGate = DmSanityGate(self.config.dm_sanity_gate)` at [src/probos/runtime.py:567-570](src/probos/runtime.py#L567-L570) — confirmed.
- `sanity_gate = getattr(runtime, "dm_sanity_gate", None)` at [src/probos/routers/agents.py:1106](src/probos/routers/agents.py#L1106) — confirmed; surrounding `_params` and `message_text` in scope at lines 1041-1058 — confirmed retry block can reference both.
- `# BF-120: Strip markdown formatting that wraps structured tags.` at [src/probos/proactive.py:2517](src/probos/proactive.py#L2517) — confirmed; the surrounding scope has `rt = self._runtime` and `agent.id` available.
- `reply_body = _strip_bracket_markers(reply_body)  # BF-174` at [src/probos/proactive.py:3403](src/probos/proactive.py#L3403) — confirmed.
- `pip show rapidfuzz` confirmed not installed — stdlib `difflib.SequenceMatcher` choice preserves license hygiene.
- `DmSanityResult` is a plain `@dataclass` (not frozen), so adding `should_retry: bool = False` after the existing defaulted `warnings` field is field-ordering-safe.
- Phase ordering: `apply_dm_sanity` reads `getattr(runtime, "dm_sanity_gate", None)`; gate is wired in `RuntimeOS.__init__` body (Phase 0 effectively), well before any phase that consumes it. No phase-order trap.
- No NATS subject/namespace changes; no new event types; no consensus-gate touches.

---

### Re-review (pass-2)
**Verdict:** ✅ Approved
**Pass-1 Required #1 genuinely addressed; no new Required introduced.**

#### Pass-1 Required disposition

1. **Duplicate `DmSanityGateConfig` (pass-1 Required #1) — RESOLVED.** Live grep confirms two copies still in HEAD at [src/probos/cognitive/dm_sanity_gate.py:49](src/probos/cognitive/dm_sanity_gate.py#L49) and [src/probos/config.py:3236](src/probos/config.py#L3236). Revised Section 2 now spells out three new fields (`repetition_similarity_threshold`, `retry_on_rejection`, `retry_warnings`) on BOTH copies with full code blocks for each, plus an explicit "Both copies must stay structurally identical" cluster invariant. Files-to-Modify table updated to list `dm_sanity_gate.py:49–60` as a target. The `from pydantic import Field` add-on for `dm_sanity_gate.py:22` is called out (verified: HEAD imports only `BaseModel`). Existing tests at `tests/test_ad724_dm_sanity_gate.py:22,127` will continue to construct `DmSanityGate(DmSanityGateConfig())` with no AttributeError on the new field reads.

#### Folded Recommendeds

- **#1 (typing on `apply_dm_sanity`)**: Section 3 now uses `TYPE_CHECKING`-guarded `RuntimeOS` import + `runtime: "RuntimeOS"` annotation. Verified.
- **#5 (proactive.py module-top import)**: Files-to-Modify table now says "Import `apply_dm_sanity` at module top (not function-local)"; Section 3 places the import alongside other `probos.cognitive` imports.

Deferrals (#2 cache poisoning, #3 retry-warning loop test, #4 `is_retry: True`) carry written rationale; acceptable per Convention #15 deferral standard.

#### New Required findings — NONE

#### New Recommendeds (drift class)

1. **Solution Overview ↔ Section 3 inconsistency on "remove the duplicate inline strip."** Solution Overview AD-724-5 says "remove the duplicate inline strip." Section 3 removes only the strip in `_extract_and_execute_actions` ([proactive.py:2514](src/probos/proactive.py#L2514)). A second inline BF-120 strip exists at [proactive.py:3479-3480](src/probos/proactive.py#L3479) inside `_extract_and_execute_replies` (live grep confirms). Section 3 inserts `apply_dm_sanity` BEFORE `_strip_bracket_markers` at line 3403 but does NOT remove the duplicate at 3479. Functionally safe — the second strip becomes idempotent (gate already cleaned upstream), and arguably acts as a fallback when the gate is config-disabled (matches the Solution Overview's "If the config is disabled, the markdown strip still runs" invariant). Either (a) update Section 3 to also remove proactive.py:3479-3480, OR (b) soften the Solution Overview to "remove the duplicate inline strip in `_extract_and_execute_actions`; leave the `_extract_and_execute_replies` copy as a disabled-gate fallback." Pick one for narrative clarity. Not blocking.

#### Nits

1. Verification footer cites `BF-120: Strip markdown` at line 2517; live HEAD shows it at line 2514 (3-line drift — within the "around line N" tolerance of review-criteria #6). The verification grep is correct on the symbol but stale on the offset. No Builder impact.

#### Verified Improvements

- Both `DmSanityGateConfig` extensions specified in full with identical field shape.
- `Field` import addition for `dm_sanity_gate.py:22` explicitly called out — Builder won't miss it.
- `apply_dm_sanity` typing now compliant with Engineering Principles type-annotation rule.
- Module-top import in `proactive.py` aligned with project's import-order standard.
- Files-to-Modify table now mentions both `dm_sanity_gate.py` and `config.py` as separate rows.
- No new layer violations.
- No new untested code paths — existing 12-test plan already covers the new field reads.
- No new phantom APIs.
- Cluster invariant from AD-724 archive prompt explicitly cited (good provenance).

---

