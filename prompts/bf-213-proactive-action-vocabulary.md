# BF-213: Chain Proactive Analyze Suppresses Structured Actions — Build Prompt

**BF:** 213  
**Issue:** #298  
**Related:** AD-632d (Compose Handler), AD-632f (Chain-Eligible Intents), AD-412 (Improvement Proposals)  
**Scope:** ~10 lines changed across 2 files. Zero new modules.

---

## Problem

Three compounding issues in the cognitive chain suppress all structured actions (proposals, game challenges, DMs, thread replies) during proactive observation cycles:

### Issue 1: Analyze silence bias (PRIMARY)

`analyze.py` `_build_situation_review_prompt()` L.299-306, the non-duty proactive path tells the model:

```
"Silence is professionalism — [NO_RESPONSE] is the expected default."
```

This framing biases the ANALYZE step to return `intended_actions: ["silent"]` on most cycles, even when there's something proposal-worthy or action-worthy. The `intended_actions` vocabulary at L.361-364 includes `proposal`, `dm`, `ward_room_reply`, etc. — but the "silence is the default" prior overrides them.

### Issue 2: Short-circuit kills compose (SECONDARY)

When ANALYZE returns `intended_actions: ["silent"]`, the compose short-circuit (`compose.py` `_should_short_circuit()` L.46) fires and **skips the entire compose LLM call**. The model never reaches compose, never sees standing orders, never gets a chance to generate a proposal.

### Issue 3: Compose framing discourages structured output (TERTIARY)

`compose.py` `_build_proactive_compose_prompt()` L.228-234, the non-duty path says:

```
"compose a brief observation (2-4 sentences)"
```

This primes for short prose, not multi-line structured tags like `[PROPOSAL]` (which needs Title + Rationale + Affected Systems + Priority). Agents that survive the short-circuit are still discouraged from producing structured actions by the framing.

### Issue 4: BF-213 added duplicate action vocabulary (REVERT)

The prior BF-213 build added action tag instructions to compose.py (`_build_proactive_compose_prompt` L.245-284 and `_build_ward_room_compose_prompt` L.138-146). These duplicate the **complete Ward Room Action Vocabulary** already present in standing orders (`config/standing_orders/ship.md` L.108-165), which flows into every compose call via `compose_instructions()`. Duplication across prompt layers has been shown to confuse the model. This must be reverted.

**Result:** Zero improvement proposals this instance. Likely also reduced game initiations, thread replies, and DMs during proactive cycles.

**Observed in prior instance:** Proposals were frequent. The prior instance used the one-shot path (which doesn't have the analyze gate or compose short-circuit).

---

## What Already Exists

- Standing orders (`ship.md` L.108-165) contain **complete** Ward Room Action Vocabulary: ENDORSE, REPLY, NOTEBOOK, DM, PROPOSAL, CHALLENGE, MOVE, NO_RESPONSE, plus "When to act vs. observe" decision tree
- `compose_instructions()` (`standing_orders.py` L.252-255) includes full `ship.md` as "Ship Standing Orders" — flows into every compose call
- Communication-discipline skill: behavioral guidance for ENDORSE, NO_RESPONSE (injected via `_inject_skills()`)
- Notebook-quality skill: behavioral guidance for NOTEBOOK, READ_NOTEBOOK (injected via `_inject_skills()`)
- Analyze `intended_actions` vocabulary (L.361-363): includes `proposal`, `dm`, `ward_room_reply`, `notebook`, `endorse`, `ward_room_post`, `leadership_review`, `silent`
- `_extract_and_post_proposal()` (proactive.py L.1880) and `_extract_and_execute_actions()` (proactive.py L.2002) — all extraction pipelines intact
- Short-circuit bypass for captain, mentions, DMs (`compose.py` L.35-36)

---

## Fix

Four changes, all small. No new modules, no new imports.

### Part A: Rebalance analyze silence bias (analyze.py)

The silence framing is too aggressive. The intent was to prevent noise (agents posting meaningless observations), but it suppresses ALL proactive output including proposals, game challenges, and DMs. The duty path (L.290-298) doesn't have this bias — it says "report your findings."

**In `_build_situation_review_prompt()`, find lines 299-306:**

```python
    else:
        duty_section = (
            f"## Proactive Review — No Scheduled Duty\n\n"
            f"{_agent_metrics}\n\n"
            f"You have no scheduled duty at this time. Post only if you observe "
            f"something genuinely noteworthy or actionable. "
            f"Silence is professionalism — [NO_RESPONSE] is the expected default.\n\n"
        )
```

**Replace with:**

```python
    else:
        duty_section = (
            f"## Proactive Review — No Scheduled Duty\n\n"
            f"{_agent_metrics}\n\n"
            f"You have no scheduled duty at this time. Assess the situation and "
            f"decide what action, if any, is warranted. Options include posting an "
            f"observation, filing a proposal, replying to a thread, sending a DM, "
            f"challenging a crewmate to a game, or staying silent. "
            f"Do not post vague observations — if you act, be specific and actionable. "
            f"If nothing warrants action, [NO_RESPONSE] is appropriate.\n\n"
        )
```

**What changed:**
- Removed "Silence is professionalism — [NO_RESPONSE] is the expected default" — this framing made silence the prior, suppressing all actions
- Added explicit mention of the action types available (proposal, reply, DM, game) — the model needs to know these are options during assessment, not just during composition
- Kept the quality bar: "do not post vague observations" maintains noise suppression
- Kept `[NO_RESPONSE]` as valid: "if nothing warrants action" — silence is still an option, just not the default

### Part B: Broaden compose framing (compose.py)

The "2-4 sentences" framing primes for short prose and discourages structured multi-line output. The duty path (L.215-225) doesn't have this constraint either.

**In `_build_proactive_compose_prompt()`, find lines 226-235:**

```python
    else:
        system_prompt += (
            "\n\nYou are reviewing recent ship activity during a quiet moment. "
            "If you notice something noteworthy — a pattern, a concern, an insight "
            "related to your expertise — compose a brief observation (2-4 sentences). "
            "This will be posted to the Ward Room as a new thread. "
            "Speak in your natural voice. Be specific and actionable. "
            "If there's another way to see this, mention it briefly. "
            "Don't just summarize — interpret."
        )
```

**Replace with:**

```python
    else:
        system_prompt += (
            "\n\nYou are reviewing recent ship activity during a quiet moment. "
            "If you notice something noteworthy — a pattern, a concern, an insight "
            "related to your expertise — act on it. You may compose a Ward Room "
            "observation (2-4 sentences), file an improvement proposal, reply to "
            "an existing thread, send a DM, or challenge a crewmate to a game. "
            "Refer to your standing orders for action tag syntax. "
            "Speak in your natural voice. Be specific and actionable. "
            "If there's another way to see this, mention it briefly. "
            "Don't just summarize — interpret."
        )
```

**What changed:**
- Removed "compose a brief observation" as the sole framing — proposals, replies, DMs, and games are also valid outputs
- Added "Refer to your standing orders for action tag syntax" — points to ship.md's complete vocabulary rather than duplicating it
- Kept the quality bar ("2-4 sentences" for observations, "be specific and actionable")
- Kept the voice guidance ("natural voice", "interpret")

### Part C: Revert BF-213 duplicate action vocabulary (compose.py)

Remove the action vocabulary blocks added by the prior BF-213 build. These duplicate standing orders.

**In `_build_proactive_compose_prompt()`, delete lines 245-284** (the entire `# BF-213: Action vocabulary` block including PROPOSAL, REPLY, DM, CHALLENGE, MOVE instructions).

The code after revert should flow directly from skill injection to user prompt:

```python
    # Skill injection
    system_prompt = _inject_skills(system_prompt, context)

    user_prompt = _build_user_prompt(context, prior_results)

    return system_prompt, user_prompt
```

**In `_build_ward_room_compose_prompt()`, delete lines 138-146** (the `# BF-213: DM tag syntax` block).

The code after revert should flow directly from skill injection to user prompt:

```python
    # Skill injection
    system_prompt = _inject_skills(system_prompt, context)

    # User prompt with analysis and original content
    user_prompt = _build_user_prompt(context, prior_results)

    return system_prompt, user_prompt
```

### Part D: No change to short-circuit (compose.py)

The `_should_short_circuit()` function (L.32-50) is correct as-is. When ANALYZE returns `["silent"]`, compose SHOULD skip the LLM call — that's an efficient optimization. The fix is upstream: Part A ensures ANALYZE doesn't default to silence when actions are warranted. When ANALYZE returns `["proposal"]` or `["ward_room_post", "dm"]`, the short-circuit correctly does NOT fire and compose runs normally.

---

## Verification Checklist

**Analyze rebalance (Part A):**
1. [ ] "Silence is professionalism" removed from non-duty proactive framing
2. [ ] Replacement text mentions proposals, replies, DMs, games as explicit options
3. [ ] Quality bar maintained: "do not post vague observations"
4. [ ] `[NO_RESPONSE]` still mentioned as valid option (not removed, just not the default)
5. [ ] Duty path (L.290-298) NOT modified — it already says "report your findings"

**Compose rebalance (Part B):**
6. [ ] Non-duty compose framing no longer says "compose a brief observation" as sole output type
7. [ ] Replacement text references standing orders for tag syntax
8. [ ] "2-4 sentences" kept for observations but not the sole framing

**Duplication revert (Part C):**
9. [ ] BF-213 action vocabulary block (PROPOSAL/REPLY/DM/CHALLENGE/MOVE) removed from proactive compose
10. [ ] BF-213 DM tag syntax block removed from ward room compose
11. [ ] No action tag syntax duplicated between compose.py and standing orders
12. [ ] Skill injection (`_inject_skills()`) unchanged — skills handle ENDORSE/NOTEBOOK behavioral guidance

**General:**
13. [ ] One-shot path (cognitive_agent.py) NOT modified
14. [ ] Short-circuit logic (`_should_short_circuit()`) NOT modified
15. [ ] All existing tests pass (`pytest tests/ -x -q`)
16. [ ] No imports changed, no new modules

---

## Tests (tests/test_bf213_proactive_action_vocabulary.py)

Replace the existing test file entirely:

```python
"""BF-213: Proactive chain action suppression fix tests."""
import pytest
from probos.cognitive.sub_tasks.analyze import _build_situation_review_prompt
from probos.cognitive.sub_tasks.compose import (
    _build_proactive_compose_prompt,
    _build_ward_room_compose_prompt,
)


class TestAnalyzeSilenceBias:
    """Verify analyze prompt no longer defaults to silence."""

    def _build_analyze_prompt(self, duty=None):
        ctx = {
            "context": "test situation data",
            "_agent_type": "medical_officer",
            "_agent_metrics": "Trust: 0.75, Rank: Lieutenant",
        }
        if duty:
            ctx["_active_duty"] = duty
        _, user_prompt = _build_situation_review_prompt(ctx, [], "Keiko", "medical")
        return user_prompt

    def test_no_silence_is_professionalism(self):
        """Non-duty proactive analyze does not say 'Silence is professionalism'."""
        prompt = self._build_analyze_prompt()
        assert "Silence is professionalism" not in prompt

    def test_no_silence_as_default(self):
        """Non-duty proactive analyze does not frame silence as 'expected default'."""
        prompt = self._build_analyze_prompt()
        assert "expected default" not in prompt

    def test_mentions_proposal_option(self):
        """Non-duty proactive analyze mentions proposals as an action option."""
        prompt = self._build_analyze_prompt()
        assert "proposal" in prompt.lower()

    def test_mentions_game_option(self):
        """Non-duty proactive analyze mentions games as an action option."""
        prompt = self._build_analyze_prompt()
        assert "game" in prompt.lower()

    def test_no_response_still_valid(self):
        """Non-duty proactive analyze still allows [NO_RESPONSE]."""
        prompt = self._build_analyze_prompt()
        assert "[NO_RESPONSE]" in prompt

    def test_quality_bar_maintained(self):
        """Non-duty proactive analyze still discourages vague observations."""
        prompt = self._build_analyze_prompt()
        assert "vague" in prompt.lower() or "specific" in prompt.lower()

    def test_duty_path_unchanged(self):
        """Duty-triggered analyze still says 'report your findings'."""
        prompt = self._build_analyze_prompt(
            duty={"duty_id": "status_report", "description": "Status Report"}
        )
        assert "report your findings" in prompt.lower()


class TestComposeFraming:
    """Verify compose framing allows structured actions, not just observations."""

    def _build_prompt(self, duty=None):
        ctx = {
            "context": "test",
            "mode": "proactive_observation",
            "_agent_type": "medical_officer",
        }
        if duty:
            ctx["_active_duty"] = duty
        system, _ = _build_proactive_compose_prompt(ctx, [], "Keiko", "medical")
        return system

    def test_not_observation_only(self):
        """Non-duty compose framing does not frame observation as the sole output type."""
        system = self._build_prompt()
        # Should not say "compose a brief observation" without mentioning other options
        assert "proposal" in system.lower() or "standing orders" in system.lower()

    def test_references_standing_orders(self):
        """Non-duty compose framing references standing orders for tag syntax."""
        system = self._build_prompt()
        assert "standing orders" in system.lower()

    def test_duty_framing_unchanged(self):
        """Duty-triggered compose framing unchanged."""
        system = self._build_prompt(
            duty={"duty_id": "status_report", "description": "Status Report"}
        )
        assert "scheduled duty" in system.lower()


class TestNoDuplication:
    """Verify no action tag duplication between compose.py and standing orders."""

    def _build_proactive_prompt(self):
        ctx = {
            "context": "test",
            "mode": "proactive_observation",
            "_agent_type": "medical_officer",
        }
        system, _ = _build_proactive_compose_prompt(ctx, [], "Keiko", "medical")
        return system

    def _build_ward_room_prompt(self):
        ctx = {
            "context": "test",
            "mode": "ward_room_response",
            "_agent_type": "medical_officer",
        }
        system, _ = _build_ward_room_compose_prompt(ctx, [], "Keiko", "medical")
        return system

    def test_no_proposal_syntax_in_compose_code(self):
        """[PROPOSAL] syntax comes from standing orders, not compose code.

        Note: [PROPOSAL] WILL appear in the full system prompt because
        compose_instructions() includes ship.md standing orders. This test
        verifies the compose code itself doesn't add a SECOND copy.
        We check that the BF-213 marker comment is gone.
        """
        import inspect
        source = inspect.getsource(_build_proactive_compose_prompt)
        assert "BF-213" not in source

    def test_no_dm_syntax_in_ward_room_compose_code(self):
        """[DM] syntax comes from standing orders, not ward room compose code.

        Same principle: compose_instructions() provides it via ship.md.
        """
        import inspect
        source = inspect.getsource(_build_ward_room_compose_prompt)
        assert "BF-213" not in source
```

Test count: 12 tests across 3 classes.

---

## What This Does NOT Do (Out of Scope)

- **Does not modify the one-shot path.** The one-shot fallback (cognitive_agent.py) is unaffected.
- **Does not modify the short-circuit.** `_should_short_circuit()` is correct — when ANALYZE says silence, compose should skip. The fix is upstream in ANALYZE's framing.
- **Does not modify skills.** Communication-discipline and notebook-quality skills are unchanged.
- **Does not add action tag syntax to compose.py.** Standing orders already provide the complete vocabulary. Compose references them rather than duplicating.
- **Does not modify standing orders.** Ship.md's Ward Room Action Vocabulary (L.108-165) is the source of truth and remains unchanged.
- **Does not modify the duty path.** Both analyze and compose duty paths are already correctly balanced — "report your findings" and "compose a Ward Room post with your findings."

---

## Engineering Principles Compliance

- **DRY:** Eliminates triple/quadruple duplication of action tag syntax. Standing orders are the single source of truth. Skills provide behavioral guidance. Compose references standing orders rather than restating them.
- **SOLID (S):** Each layer has a single responsibility. Standing orders define vocabulary. Skills define behavioral guidance. Analyze assesses the situation. Compose produces output.
- **LLM Independence Principle:** The analyze rebalance is prescriptive — explicitly lists action types available rather than hoping the model discovers them from a large standing orders document. The compose rebalance points the model to standing orders rather than relying on it to find them.
- **Fail Fast:** Short-circuit optimization preserved. When ANALYZE says silence, compose doesn't waste an LLM call.
- **Defense in Depth:** Standing orders provide the vocabulary (Layer 1). Analyze names the action types (Layer 2). Skills provide behavioral discipline for specific tags (Layer 3). Compose frames the output task (Layer 4). Each layer adds value without repeating another.
