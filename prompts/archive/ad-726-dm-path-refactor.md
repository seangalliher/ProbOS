# AD-726 — Refactor the DM one-shot path's post-LLM cleanup chain into `DmReplyPipeline`

**AD:** AD-726. **GH issue closed:** [#584](https://github.com/seangalliher/ProbOS/issues/584) (partial — see SCOPE STATEMENT).
**Sub-AD opened:** AD-726a (pre-LLM `DmContextPrep` extraction), AD-726b (`DmPromptAssembler` extraction from `_build_user_message`).
**Parent ADs:** AD-722 / AD-723 / AD-724 / AD-725 (each created a seam this AD leverages).
**Wave:** 160. **Estimated tests:** +12 pytest (boundary tests on extracted pipeline steps). **Estimated wall-time:** ~3h. **Risk:** MED — touches the hot DM path; behavior MUST stay byte-identical.

**Also lands:** AD-722c-3 (#654) — architect-style-guide bullet appended to `prompts/BUILDER-EXECUTION-PLAN.md`. Bundled here because this prompt files the most forward markers and most directly benefits from the rule.

---

## SCOPE STATEMENT (read-first — narrows #584)

GH issue #584 originally specified THREE extractions (`DmContextPrep`, `DmPromptAssembler`, `DmReplyPipeline`) + frozen-dataclass cross-phase shapes + handler shrink to ≤60 lines + assembler shrink to ≤30 lines + a byte-identical snapshot fixture suite. That is a ~10h refactor and would dominate a wave on its own.

**In scope (this AD):**

- Extract the **post-LLM cleanup chain** in `agent_chat` (`routers/agents.py:1278..1572`, 295 lines including the response-dict assembly and `return response`) into a new `DmReplyPipeline` class under `src/probos/cognitive/dm/reply_pipeline.py`. Eight pipeline steps: (1) DM sanity gate / one-shot retry; (2) challenge parse + Recreation thread create; (3) move parse + game execution; (4) HXI 1:1 episodic store; (5) DM working-memory record; (6) AD-722a divergence check; (7) `mark_reply_emitted` + AD-722f exit_dm + AD-722b event wake; (8) AD-738e-1 emotion resolution for the TTS response payload. `build_response()` produces the final dict (replaces lines 1561..1572).
- Each step is an `async def step_*(self, ctx: DmReplyContext) -> None` method on the pipeline class.
- `DmReplyContext` is a `@dataclass` (NOT frozen — steps mutate `ctx.response_text` and `ctx.emotion`; freezing would force ten `dataclasses.replace` calls).
- Pure structural refactor: every step's body is a verbatim move of the existing code block. Comments, log strings, exception-tier choices, AD references all preserved.
- `agent_chat` shrinks by ~280 lines; the handler becomes `pipeline = DmReplyPipeline(runtime, agent, ...); await pipeline.run(); return pipeline.build_response()`.
- 12 new boundary tests on the pipeline (happy path + one degrade per step + missing-runtime-attribute defenses).

**Out of scope (explicit defer):**

- Pre-LLM `DmContextPrep` extraction (the AD-725 targeted-recall block, AD-730 vision-message build, AD-720d text augmentation, AD-722 self-observation refresh). → **AD-726a**, forward marker.
- `DmPromptAssembler` extraction from `cognitive_agent.py:_build_user_message` DM branch. → **AD-726b**, forward marker.
- Frozen-dataclass cross-phase shapes (`DmObservation`, `DmReply`). The `DmReplyContext` here is intentionally mutable for v1; freezing waits for AD-726a/b. → **AD-726c**, forward marker.
- `agent_chat` ≤ 60-line target. Post-this-AD `agent_chat` lands at ~280 lines (down from 574) — the remaining bulk is pre-LLM prep that AD-726a will absorb.
- Byte-identical snapshot fixture suite. v1 relies on existing `tests/test_*.py` coverage continuing to pass unchanged; snapshot suite is AD-726c-1 forward marker.
- Any WR path refactor (`_execute_chain_with_intent_routing`). Explicitly rejected per System-1/System-2 ruling (issue body, "Out of scope").

**Rationale for narrowing:** A 3-phase refactor in one wave triples the regression risk on a hot path the operator hits every Captain DM. Shipping the post-LLM seam first proves the pipeline shape before extending it backward.

---

## Solution Overview

`routers/agents.py:agent_chat` is **574 lines** (lines 1000-1574) — well past the "no god objects" rule's 500-line / 15-method threshold from `.github/copilot-instructions.md`. Lines 1278-1572 are pure post-LLM cleanup + response assembly: eight independent concerns interleaved with `try/except` blocks, with the cumulative `response_text` flowing top-to-bottom and the final response dict assembled at line 1561.

This AD extracts that 273-line block into a pipeline class with one method per concern. The handler keeps:
- Authentication / agent-existence checks (lines 1000-1010).
- Pre-LLM context prep (lines 1011-1267 — AD-725 + AD-730 + AD-720d + AD-722). **Deferred to AD-726a.**
- `runtime.intent_bus.send(...)` LLM dispatch.
- `pipeline.run()` + `pipeline.build_response()`.

Each pipeline step is independently unit-testable with a minimal `_FakeRuntime` + `_FakeAgent` fixture. The existing integration tests (`test_callsign_routing.py`, `test_ad724_dm_sanity_gate.py`, `test_ad725_dm_targeted_lookup.py`, `test_ad722a_divergence_detector.py`, `test_ad738e1_emotion_response.py`) continue to exercise the full path and MUST stay green unmodified.

**Folded:** AD-722c-3 (#654) — one bullet appended to `prompts/BUILDER-EXECUTION-PLAN.md` Standing Rules section. Pure docs edit.

---

## Files to Modify

| File | Lines | Why |
|---|---|---|
| `src/probos/cognitive/dm/__init__.py` | NEW (empty / `__all__ = ["DmReplyPipeline", "DmReplyContext"]`) | Package marker. |
| `src/probos/cognitive/dm/reply_pipeline.py` | NEW (~420 lines) | `DmReplyPipeline` class + `DmReplyContext` dataclass + 8 step methods. |
| `src/probos/routers/agents.py` | 1278-1572 → replaced by ~23 lines | Handler shrinks. |
| `tests/test_ad726_dm_reply_pipeline.py` | NEW (~280 lines) | 12 boundary tests. |
| `prompts/BUILDER-EXECUTION-PLAN.md` | Standing Rules section | AD-722c-3 bullet append. |

**Verified anchors:**
- `agent_chat` def: `src/probos/routers/agents.py:1000`, end-of-function: `src/probos/routers/agents.py:1572`.
- Post-LLM cleanup block start: line 1278 (`# AD-724: DM sanity gate ...` comment).
- Post-LLM cleanup block end: line 1572 (the bare `return response` after the response dict assembled at 1561). Verified by `read_file` 2026-05-14.
- `sanity_gate` assignment site: line 1280 (`sanity_gate = getattr(runtime, "dm_sanity_gate", None)`).
- `sanity_result` assignment site: line 1282 (`sanity_result = sanity_gate.process(...)`) — INSIDE the moved span. NOT in ctx (per-step local).
- `_params` source: line 1216 (BEFORE the moved span — safe to pass through ctx).
- `message_text` source: line 1046 (BEFORE the moved span — safe to pass through ctx).
- `apply_divergence_check` import path: `probos.avatars.divergence_detector` (line 1498 — `from probos.avatars.divergence_detector import apply_divergence_check`).
- `resolve_emotion_to_v1` public alias: `probos.avatars.divergence_detector.resolve_emotion_to_v1` (defined at `src/probos/avatars/divergence_detector.py:131-135`, public — no underscore prefix).
- `sanity_gate.extract_challenge` / `extract_move` / `strip_challenge` / `strip_move`: verified in-use at lines 1327, 1384, 1386, 1431-1444.
- `runtime.recreation_service`, `runtime.callsign_registry`, `runtime.ward_room`, `runtime.episodic_memory`, `runtime.profile_store`, `runtime.divergence_results`: all guarded by `hasattr` / `getattr` in the existing code; preserved verbatim.

---

## Section 1 — New package `src/probos/cognitive/dm/`

Create `src/probos/cognitive/dm/__init__.py`:

```python
"""AD-726: DM one-shot path internal pipeline package.

Public surface limited to ``DmReplyPipeline`` and ``DmReplyContext``.
The pre-LLM ``DmContextPrep`` (AD-726a) and prompt-side ``DmPromptAssembler``
(AD-726b) will land in this package as their forward markers advance.
"""

from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline

__all__ = ["DmReplyContext", "DmReplyPipeline"]
```

## Section 2 — `src/probos/cognitive/dm/reply_pipeline.py` (NEW)

Create the file with this skeleton. Each `step_N_*` method's BODY is a verbatim move of the corresponding block in `routers/agents.py:1278..1572` — preserve every comment, every log call, every `try/except` tier, every AD reference.

```python
"""AD-726: post-LLM cleanup pipeline for the DM one-shot path.

Eight ordered steps replicate the prior inline cascade in
``routers/agents.py:agent_chat``. Each step is a Tier-2
log-and-degrade boundary internally; the orchestrator
(:meth:`run`) wraps the whole chain in a top-level guard so a
runaway step never blocks the reply. Step ordering is load-bearing:
sanity gate MUST run before challenge / move parsers (challenge/move
markers are stripped by the sanity gate's retry path); divergence
check MUST run before ``mark_reply_emitted`` (snap-time invariant);
emotion resolution MUST run after divergence (reads ``divergence_results``).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DmReplyContext:
    """Mutable context threaded through every pipeline step.

    NOT frozen by design: ``response_text`` and ``emotion`` are mutated
    in place by the sanity gate, challenge/move strip, divergence check,
    and emotion-resolution steps. AD-726c will introduce a frozen
    ``DmReply`` final shape once AD-726a + AD-726b land and the full
    contract stabilizes.
    """

    runtime: Any
    agent: Any
    agent_id: str
    callsign: str | None
    req_message: str
    response_text: str
    has_image_attachment: bool
    per_attachment: list[dict[str, object]]
    sanity_gate: Any | None
    # AD-726 revision (2026-05-14): params + message_text are read by
    # step_1_sanity_gate_retry when building the AD-724-1 retry IntentMessage.
    # Sourced from the handler's pre-LLM scope (line 1216 / 1046) — safe to
    # pass through unchanged.
    params: dict[str, object]
    message_text: str
    sampling_state: Any | None
    avatar_event_bus: Any | None
    emotion: str | None = None
    game_move_result: dict[str, Any] | None = None
    # NOTE: ``sanity_result`` is intentionally NOT a ctx field — it is
    # produced and consumed entirely within step_1_sanity_gate_retry.


class DmReplyPipeline:
    """Eight-step post-LLM cleanup chain for the DM one-shot path."""

    def __init__(self, ctx: DmReplyContext) -> None:
        self.ctx = ctx

    async def run(self) -> None:
        """Execute every step in order. Top-level guard preserves the
        Tier-2 contract: a runaway step is logged but never blocks the
        reply. Per-step guards inside the methods are preserved verbatim
        from the prior inline code; the top-level guard is belt-and-braces.
        """
        for step in (
            self.step_1_sanity_gate_retry,
            self.step_2_challenge_parse,
            self.step_3_move_parse,
            self.step_4_episodic_store,
            self.step_5_working_memory_record,
            self.step_6_divergence_check,
            self.step_7_mark_emitted,
            self.step_8_emotion_resolve,
        ):
            try:
                await step()
            except Exception:
                logger.warning(
                    "AD-726: pipeline step %s raised for agent=%s; continuing",
                    step.__name__, self.ctx.agent_id, exc_info=True,
                )

    # --- step 1: DM sanity gate one-shot retry (AD-724-1) ---
    async def step_1_sanity_gate_retry(self) -> None:
        """Verbatim move of routers/agents.py:1278..1325."""
        # ... move existing block here unchanged ...

    # --- step 2: BF-119 challenge parse (AD-724) ---
    async def step_2_challenge_parse(self) -> None:
        """Verbatim move of routers/agents.py:1324..1387."""
        # ... move existing block here unchanged ...

    # --- step 3: AD-572 move parse ---
    async def step_3_move_parse(self) -> None:
        """Verbatim move of routers/agents.py:1389..1444."""
        # ... move existing block here unchanged ...

    # --- step 4: AD-430b HXI 1:1 episodic store ---
    async def step_4_episodic_store(self) -> None:
        """Verbatim move of routers/agents.py:1446..1481."""
        # ... move existing block here unchanged ...

    # --- step 5: AD-573 working-memory record ---
    async def step_5_working_memory_record(self) -> None:
        """Verbatim move of routers/agents.py:1483..1493."""
        # ... move existing block here unchanged ...

    # --- step 6: AD-722a divergence check ---
    async def step_6_divergence_check(self) -> None:
        """Verbatim move of routers/agents.py:1495..1511."""
        # ... move existing block here unchanged ...

    # --- step 7: mark_reply_emitted + AD-722f exit_dm + AD-722b wake ---
    async def step_7_mark_emitted(self) -> None:
        """Verbatim move of routers/agents.py:1513..1522."""
        # ... move existing block here unchanged ...

    # --- step 8: AD-738e-1 emotion resolution ---
    async def step_8_emotion_resolve(self) -> None:
        """Verbatim move of routers/agents.py:1524..1551."""
        # ... move existing block here unchanged ...

    def build_response(self) -> dict[str, Any]:
        """Return the final response dict — verbatim move of routers/agents.py:1553..1559."""
        response: dict[str, Any] = {
            "response": self.ctx.response_text,
            "callsign": self.ctx.callsign,
            "agentId": self.ctx.agent_id,
            "emotion": self.ctx.emotion,
        }
        if self.ctx.game_move_result:
            response["gameMoveExecuted"] = True
            response["gameStatus"] = self.ctx.game_move_result.get("state", {}).get("status", "")
        return response
```

**Builder verification before SEARCH/REPLACE in routers/agents.py:**

1. Read `routers/agents.py:1278..1572` end-to-end (295 lines).
2. For each step method above, copy the corresponding block VERBATIM into the method body. Preserve every comment line, every blank line, every `try/except` indent level.
3. Replace every `response_text` reference inside a method body with `self.ctx.response_text`. Replace every `agent_id` with `self.ctx.agent_id`. Replace every `agent` with `self.ctx.agent`. Replace every `runtime` with `self.ctx.runtime`. Replace `req.message` with `self.ctx.req_message`. Replace `callsign` with `self.ctx.callsign`. Replace `_sampling_state` with `self.ctx.sampling_state`. Replace `_avatar_event_bus` with `self.ctx.avatar_event_bus`. Replace `sanity_gate` with `self.ctx.sanity_gate`. Replace `has_image_attachment` with `self.ctx.has_image_attachment`. Replace `per_attachment` with `self.ctx.per_attachment`. Replace `game_move_result = ...` ASSIGNMENTS with `self.ctx.game_move_result = ...`. Replace `game_move_result` READS with `self.ctx.game_move_result`. Replace `_emotion` with `self.ctx.emotion`. **Carve-outs**:
   - `sanity_result` is a per-step local in `step_1_sanity_gate_retry`; do NOT rebind to `self.ctx.*`. Leave the assignment `sanity_result = sanity_gate.process(...)` and subsequent reads as plain local names.
   - `_params` references inside step_1's retry-intent build become `self.ctx.params`.
   - `message_text` references inside step_1's retry-intent build become `self.ctx.message_text`.
   - The declaration line `_emotion: str | None = None` (line 1532 in pre-move) is DROPPED — `ctx.emotion` already defaults to `None`. Replace that line with `# AD-726: emotion lives on ctx; pre-initialized in DmReplyContext default.`
   - `IntentMessage` import in step_1 is lazy: `from probos.types import IntentMessage` inside the method body.
4. The `if sanity_gate is not None` / `if response_text and hasattr(runtime, ...)` style guards are preserved as-is (Tier-2 in-place).
5. Imports needed at module top of `reply_pipeline.py`: `import logging`, `import re`, `from dataclasses import dataclass, field`, `from typing import Any`. Step bodies do `from probos.X import Y` lazily (mirroring the original code's lazy import pattern).

## Section 3 — `routers/agents.py` handler shrinks

In `src/probos/routers/agents.py`, replace lines 1278..1572 with the shrink block below. Lines 1000-1277 (auth + pre-LLM context prep) and line 1573+ (next route handler `agent_chat_history`) are PRESERVED unchanged.

**SEARCH (line 1278, the AD-724 sanity-gate comment is the unique top-of-block anchor):**

```python
    # AD-724: DM sanity gate (migrates BF-120 markdown strip + adds 3 log-only checks).
```

through line 1572 inclusive (the bare `return response` line that follows the response dict assembly). Use ONE `replace_string_in_file` call, NOT `multi_replace_string_in_file` — per BF-274 hazard rule, adjacent-block multi-replace is high-risk on large spans.

**REPLACE with:**

```python
    # AD-726: post-LLM cleanup pipeline (AD-724/AD-572/AD-430b/AD-573/AD-722a/
    # AD-722f/AD-722b/AD-738e-1 cascade extracted into DmReplyPipeline). Each
    # step preserves its prior Tier-2 boundary; the top-level run() guard is
    # belt-and-braces. Behavior is byte-identical to pre-AD-726 inline form.
    # ``sanity_gate`` is resolved here (NOT inside the pipeline) so that step_1
    # AND step_2/step_3 (which also call extract_challenge / extract_move) all
    # see the same instance via ``self.ctx.sanity_gate``.
    sanity_gate = getattr(runtime, "dm_sanity_gate", None)
    from probos.cognitive.dm import DmReplyContext, DmReplyPipeline
    pipeline = DmReplyPipeline(DmReplyContext(
        runtime=runtime,
        agent=agent,
        agent_id=agent_id,
        callsign=callsign,
        req_message=req.message,
        response_text=response_text,
        has_image_attachment=has_image_attachment,
        per_attachment=per_attachment,
        sanity_gate=sanity_gate,
        params=_params,
        message_text=message_text,
        sampling_state=_sampling_state,
        avatar_event_bus=_avatar_event_bus,
    ))
    await pipeline.run()
    return pipeline.build_response()
```

Net delta on `routers/agents.py`: -295 lines (1572-1278+1) + 23 lines = **-272 net lines**. `agent_chat` post-refactor: 574 - 272 = **~302 lines** (still over the 60-line target from #584 — the remainder is pre-LLM prep deferred to AD-726a).

## Section 4 — `tests/test_ad726_dm_reply_pipeline.py` (NEW)

Twelve boundary tests:

1. `test_run_executes_all_eight_steps_in_order` — happy path; verify each `step_N_*` is invoked exactly once via `monkeypatch` spy.
2. `test_run_continues_when_step_1_raises` — top-level guard contract.
3. `test_step_1_sanity_gate_retry_no_warnings_skips_retry` — branch coverage.
4. `test_step_2_challenge_parse_no_recreation_service_skips` — `hasattr(runtime, 'recreation_service') = False` degrade path.
5. `test_step_3_move_parse_no_active_game_skips` — `rec_svc.get_game_by_player(...)` returns None.
6. `test_step_4_episodic_store_no_episodic_memory_skips` — `hasattr(runtime, 'episodic_memory') = False`.
7. `test_step_5_working_memory_no_wm_skips` — `agent.working_memory = None`.
8. `test_step_6_divergence_disabled_skips` — `t_cfg.divergence_detection = False`.
9. `test_step_7_mark_emitted_no_method_skips` — `hasattr(agent, 'mark_reply_emitted') = False`.
10. `test_step_8_emotion_no_divergence_results_emotion_stays_none` — graceful degrade.
11. `test_build_response_includes_game_status_when_move_executed` — `ctx.game_move_result = {"state": {"status": "...", ...}}` branch.
12. `test_build_response_omits_game_keys_when_no_move` — counter-case to 11.

Each test constructs a minimal `_FakeRuntime` / `_FakeAgent` (mirror the pattern in `tests/test_ad724_dm_sanity_gate.py` — verified by `grep_search`). DO NOT use `MagicMock` chains — per user-memory standing rule, prefer `_Fake*` stub classes.

## Section 5 — `prompts/BUILDER-EXECUTION-PLAN.md` (AD-722c-3 / #654 fold)

Append ONE bullet to the "Standing rules" section. Find the existing rule block ending with the `multi_replace_string_in_file hazard` rule (introduced Wave 154). Append immediately after that bullet:

```markdown
11. **AD-722c-3 — Architect forward markers use TECHNICAL triggers, not commercial-tier language.** Forward markers that describe when commercial-overlay extensions might trigger MUST use technical / capability-based phrasing. Examples: ❌ "enterprise tier requires queryable backend" → ✅ "queryable-backend deployment requires SQL replacement". ❌ "commercial overlay can swap JSONL for SQL" → ✅ "deployments needing queryable analytics can swap JSONL for SQL via the Protocol." Boundary rule (AD-450 / Wave 154 retrospective): OSS repo describes WHAT extension points exist, not HOW they're priced or monetized. The pre-commit boundary hook will fire on common pricing-adjacent words ("enterprise tier", "commercial overlay", "pricing").
```

Builder MUST locate the exact line that ends the prior bullet (`multi_replace_string_in_file` hazard, near line 35-50 of `BUILDER-EXECUTION-PLAN.md`) using a unique anchor like `BF-274` or `multi_replace_string_in_file deletes` and SEARCH/REPLACE inserts the new bullet immediately after. Use single `replace_string_in_file`, not multi — BF-274.

---

## What This Does NOT Change

- `cognitive_agent.py:_build_user_message` — prompt assembly is AD-726b.
- `agent_chat` pre-LLM prep block (lines 1000-1277) — AD-726a.
- `_execute_chain_with_intent_routing` — chain path, explicitly out of scope.
- `direct_message` handler in `cognitive_agent.py` — that's the receiving end; this AD is router-side only.
- Any test fixtures, log strings, AD references, or exception tiers in the moved code.
- `SensoriumEntry`, `apply_divergence_check`, `resolve_emotion_to_v1` public surfaces.
- AD-731 invariant (attachments still ref-shape).

---

## Test Plan

**Boundary tests (NEW, +12):** see Section 4.

**Regression coverage (existing tests MUST stay green UNCHANGED):**

- `tests/test_callsign_routing.py` (DM end-to-end happy path).
- `tests/test_ad719_chat_fanout.py` (chat fan-out behavior).
- `tests/test_ad724_dm_sanity_gate.py` (sanity-gate retry).
- `tests/test_ad724_2_sequencematcher.py` (fuzzy-repetition fork).
- `tests/test_ad724_5_proactive_sanity.py` (shared apply_dm_sanity helper).
- `tests/test_ad725_dm_targeted_lookup.py` (DM sub-intent dispatch).
- `tests/test_ad730_*.py` (vision pipe-through).
- `tests/test_ad722a_divergence_detector.py` (divergence semantics).
- `tests/test_ad738e1_emotion_response.py` (emotion field in response).

If ANY of these break, the refactor is NOT byte-identical and the prompt has a bug. Stop and surface.

---

## Verification Commands

```powershell
# Pre-flight: baseline green.
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile | Select-Object -Last 3

# Focused — new boundary tests.
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad726_dm_reply_pipeline.py -v -n 0 | Select-Object -Last 30

# Regression — full DM-path coverage.
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_callsign_routing.py tests/test_ad719_chat_fanout.py tests/test_ad724_dm_sanity_gate.py tests/test_ad725_dm_targeted_lookup.py tests/test_ad722a_divergence_detector.py tests/test_ad738e1_emotion_response.py -v -n 0 | Select-Object -Last 30

# Full gate.
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile | Select-Object -Last 3
```

**No UI files modified** — `npm run build` not required for this prompt.

---

## Tracker Updates

- **PROGRESS.md:** add closure line `AD-726 — DM post-LLM cleanup pipeline extracted to DmReplyPipeline (+12 pytest tests; closes #584 partial — pre-LLM prep deferred to AD-726a/b/c forward markers). agent_chat shrinks 574→~302 lines. AD-722c-3 (#654) folded — BEP standing rule bullet for technical-not-commercial forward-marker language.`
- **docs/development/roadmap.md:** remove #584 row from Bug Tracker; add three forward-marker rows AD-726a (pre-LLM `DmContextPrep`), AD-726b (`DmPromptAssembler`), AD-726c (frozen-dataclass cross-phase shapes + byte-identical snapshot suite).
- **DECISIONS.md:** append `### AD-726 — DM post-LLM cleanup pipeline (partial close of #584)` with the SCOPE STATEMENT condensed to 2 paragraphs.

---

## License Disposition

All-internal Apache 2.0. New code under `src/probos/cognitive/dm/` is original. No new pip / npm deps. No external absorption.

---

## Forward markers (technical-trigger language per AD-722c-3)

- **AD-726a — Pre-LLM context prep extraction.** Advances when `agent_chat` pre-LLM block exceeds 350 lines OR when a third pre-LLM concern (beyond AD-725/AD-730/AD-720d/AD-722) is added.
- **AD-726b — `DmPromptAssembler` extraction.** Advances when `cognitive_agent.py:_build_user_message` DM branch exceeds 200 lines OR `_DM_SELF_WRAPPED_KEYS` reaches 5+ entries.
- **AD-726c — Frozen cross-phase shapes + snapshot fixture suite.** Advances when AD-726a AND AD-726b have both landed.

---

## Acceptance Criteria

- ✅ `src/probos/cognitive/dm/__init__.py` and `src/probos/cognitive/dm/reply_pipeline.py` created.
- ✅ `routers/agents.py:agent_chat` shrinks by ~272 net lines (~302 lines post-refactor, down from 574). Builder reports the exact post-refactor line count in the build report.
- ✅ `tests/test_ad726_dm_reply_pipeline.py` adds 12 boundary tests, all passing.
- ✅ The 9 regression test files listed above stay green UNCHANGED.
- ✅ Full gate `pytest tests/ -q -n 4 --dist=loadfile` green.
- ✅ `prompts/BUILDER-EXECUTION-PLAN.md` Standing Rules gains bullet #11 (AD-722c-3 fold).
- ✅ No new files in `pyproject.toml` / `ui/package.json`.
- ✅ No `multi_replace_string_in_file` used on `routers/agents.py:1278..1572` span (BF-274 hazard).
- ✅ Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-14)

```
agent_chat span:
  grep -n "^async def agent_chat" src/probos/routers/agents.py
    1000: async def agent_chat(agent_id: str, req: AgentChatRequest, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:

post-LLM block boundaries:
  src/probos/routers/agents.py:1278: # AD-724: DM sanity gate (migrates BF-120 markdown strip + adds 3 log-only checks).
  src/probos/routers/agents.py:1280: sanity_gate = getattr(runtime, "dm_sanity_gate", None)
  src/probos/routers/agents.py:1282: sanity_result = sanity_gate.process(agent_id, response_text)
  src/probos/routers/agents.py:1572: return response  (last line of cleanup + dict assembly; verified via read_file 2026-05-14)

Local-variable provenance (used INSIDE moved span, defined BEFORE it):
  src/probos/routers/agents.py:1046: message_text = req.message
  src/probos/routers/agents.py:1216: _params: dict[str, object] = {

apply_divergence_check (public, line 372):
  src/probos/avatars/divergence_detector.py:372: def apply_divergence_check(

resolve_emotion_to_v1 (public alias, line 131):
  src/probos/avatars/divergence_detector.py:131: resolve_emotion_to_v1 = _resolve_intent_name

SensoriumEntry (frozen @dataclass):
  src/probos/cognitive/cognitive_agent.py:95: @dataclass(frozen=True)
  src/probos/cognitive/cognitive_agent.py:96: class SensoriumEntry:

_DM_SELF_WRAPPED_KEYS (2 entries — under AD-723a-3 forcing threshold of 3):
  src/probos/cognitive/cognitive_agent.py:472-475

Reply emission anchor:
  src/probos/routers/agents.py:1513: if hasattr(agent, 'mark_reply_emitted'):

Response dict assembly:
  src/probos/routers/agents.py:1561-1569: response = {...}
  src/probos/routers/agents.py:1572: return response  (final line of moved span)

BUILDER-EXECUTION-PLAN.md (Standing rules anchor for AD-722c-3 fold):
  grep -n "multi_replace_string_in_file" prompts/BUILDER-EXECUTION-PLAN.md
    (Builder confirms anchor before SEARCH/REPLACE.)
```

---

## Revision (2026-05-14)

Pass-1 review (`prompts/Reviews/ad-726-dm-path-refactor-review.md`) raised 3 Required findings + 4 Recommended. Revision addresses all 3 Required and 2 of the 4 Recommended (#1 LOC math; #4 sanity_gate scoping). Remaining Recommended (#2 outer-guard log strings; #3 step-count prose) absorbed inline above.

| # | Finding | Resolution |
|---|---|---|
| Required 1 | `step_1_sanity_gate_retry` reads `_params` / `message_text` not in ctx | Added `params: dict[str, object]` and `message_text: str` fields to `DmReplyContext`; ctor call passes `_params` and `message_text` from the handler's pre-LLM scope. Section 2's rebind-rules block now carves out `self.ctx.params` / `self.ctx.message_text` for the retry-intent build, and lazy-imports `IntentMessage` inside step_1. |
| Required 2 | `sanity_result` passed to ctor before assignment | `sanity_result` REMOVED from `DmReplyContext`; it remains a per-step local inside `step_1_sanity_gate_retry`. Rebind-rules carve-out added explicitly. |
| Required 3 | `_emotion: str | None = None` redeclaration shadows ctx | Rebind-rules now instruct Builder to DROP that line entirely and replace with a comment; `ctx.emotion` already defaults to `None`. |
| Recommended 1 | -281/+16 net delta math off-by-one | Span recomputed against live HEAD: `1278..1572` = 295 lines. REPLACE block = 23 lines. Net = -272. Acceptance criterion changed from "exactly 265" to "~272 net lines / ~302 post-refactor lines, Builder reports exact count." |
| Recommended 4 | `sanity_gate` undefined at line 1278 (assigned at line 1280) | REPLACE block now hoists `sanity_gate = getattr(runtime, "dm_sanity_gate", None)` BEFORE the pipeline construction call. SEARCH anchor unchanged (`# AD-724: DM sanity gate ...` comment at line 1278 is still unique). `sanity_gate` is shared across step_1 (sanity gate), step_2 (`extract_challenge`), and step_3 (`extract_move`) \u2014 hoisting once at the call site keeps the verbatim move clean. |

**Out-of-scope for this revision** (deferred per "no scope expansion" rule):

- Recommended #2 (outer-guard log content vs. inner Tier-2) \u2014 documented as expected behavior in the SCOPE STATEMENT; if a regression test asserts the original inner log string, it will continue to fire (inner Tier-2 logs are preserved verbatim). The outer `AD-726: pipeline step X raised` log is NEW and additive; pre-existing logs are unchanged.
- Recommended #3 step-count prose \u2014 already corrected in the SCOPE STATEMENT edit ("Eight pipeline steps").
- Nits 1-3 \u2014 left to Builder discretion (drop unused `field` import; trim BEP anchor line-numbers; SCOPE STATEMENT step count already corrected).

**Cross-prompt coordination:** AD-722a-4 Section 5 (revised pass-2) now prepends a slot-clear block to `DmReplyPipeline.step_1_sanity_gate_retry`. AD-726's step_1 verbatim move provides the function body; AD-722a-4 appends ONE additional Builder instruction to prepend a small block at the top of step_1. No structural conflict.
