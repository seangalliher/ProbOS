# AD-644 Phase 4: Standing Orders Additions

**AD:** AD-644 (Agent Situation Awareness Architecture)  
**Phase:** 4 of 5  
**Status:** Ready for builder  
**Depends on:** Phases 1-3 complete  
**Scope:** 1 file modified (`config/standing_orders/ship.md`), ~20 lines added, zero code changes, zero tests

---

## Context

AD-644 migrates 23 context injections from the monolithic `_build_user_message()` into the cognitive chain. Phases 1-3 handled all code-level migrations (duty context, innate faculties, situation awareness). Two parity items remain — both are **behavioral policy** that belongs in standing orders, not code:

| # | Parity Item | What's Missing |
|---|------------|----------------|
| 14 | Source attribution POLICY (AD-568d) | Ship-level guidance on grounding responses in identified sources. Federation.md has the detailed attribution framework (AD-540/541); ship.md needs the practical application rule for how agents should present their basis. |
| 23 | Duty reporting expectations | Policy statement that duty cycles require structured reports and silence during duty requires explicit justification. Currently this is only encoded in prompt rendering code, not standing orders. |

**Why standing orders, not prompt code?** These are behavioral policies — the *rules* agents internalize, not the *data* they perceive. They belong alongside Self-Monitoring (line 189) and Cognitive Zones (line 200) in `ship.md`. The `compose_instructions()` method already loads ship.md into the system prompt for all chain executions (standing_orders.py:253-255). Adding policy here means it flows to both ANALYZE and COMPOSE automatically — no code changes needed.

**Why ship.md, not federation.md?** Federation.md already has the detailed Knowledge Source Attribution framework (AD-540, lines 140-212), Memory Reliability Hierarchy (AD-541), and Memory Anchoring Protocol. These are foundational principles. Ship.md holds the operational application — how crew on *this* ship should behave. The ship-level additions complement, not duplicate, the federation framework.

---

## Implementation

### File: `config/standing_orders/ship.md`

Add two new sections after the existing "Cognitive Zones" section (after line 213). These follow the same pattern as Self-Monitoring and Cognitive Zones — behavioral guidance that agents internalize as policy.

#### Section 1: Source Attribution in Practice

Insert after line 213 (end of Cognitive Zones section):

```markdown

## Source Attribution in Practice

Your context includes a source awareness tag showing what knowledge sources are available for your current response (episodic memories, learned procedures, ship's records, or training knowledge only). Use this to ground your output:

- **When episodic memories are present:** Prefer them as your primary basis. Reference specific observations, duty cycles, or conversations you recall.
- **When only training knowledge is available:** Say so. Do not present general knowledge as personal ship experience. "Based on general systems knowledge [training]" is honest; "I've observed this pattern" without a supporting episode is confabulation.
- **When mixing sources:** Distinguish which parts of your analysis come from ship experience and which from training knowledge. The crew depends on knowing the difference.

This complements the Knowledge Source Attribution framework in Federation Standing Orders (AD-540). The federation framework defines the rules; this section reminds you to apply them in every response.
```

#### Section 2: Duty Reporting Expectations

Insert immediately after the Source Attribution section:

```markdown

## Duty Reporting Expectations

When you are executing a **scheduled duty**, you have an obligation to report:

- **Produce a structured report** of your findings, even if the finding is "nothing unusual observed." A null finding during a duty sweep is operationally valuable — it confirms the system was checked.
- **Silence during a duty cycle requires explicit justification.** Unlike free-form proactive thinking (where `[NO_RESPONSE]` is the professional default), a duty cycle means someone scheduled you to look at something. Not reporting is a dereliction.
- **Frame your report around your duty assignment.** Your duty description tells you what to examine. Stay focused on that scope — don't use a duty cycle to post about unrelated observations.

When you have **no scheduled duty**, the opposite applies:

- `[NO_RESPONSE]` is the expected default. Silence is professionalism.
- Post only if you observe something genuinely noteworthy or actionable.
- If you do post, include a brief justification for why it matters now.
```

---

## What NOT to do

- Do NOT modify any Python files. This is a markdown-only change.
- Do NOT duplicate the federation.md attribution framework. Ship.md complements it, doesn't repeat it.
- Do NOT add tests. Standing orders are loaded by `compose_instructions()` which is already tested. The content is policy text, not executable logic.
- Do NOT modify federation.md. The existing AD-540/541 framework there is correct and complete.
- Do NOT add emoji to the markdown.

---

## Verification

After adding the sections, verify:

1. `ship.md` parses cleanly (no markdown syntax errors)
2. The new sections appear after Cognitive Zones and before the end of file
3. `grep -c "Source Attribution in Practice" config/standing_orders/ship.md` returns 1
4. `grep -c "Duty Reporting Expectations" config/standing_orders/ship.md` returns 1
5. Run existing tests to confirm no regressions: `pytest tests/test_ad644*.py -x -q`

---

## Parity Status After This Phase

23 of 23 items complete. Full parity between chain path and one-shot `_build_user_message()` path.

| Phase | Items | Status |
|-------|-------|--------|
| 1 — Duty Context | #1, #2, #22 | Complete |
| 2 — Innate Faculties | #3, #4, #7, #9, #12, #13, #17, #20, #21 | Complete |
| 3 — Situation Awareness | #5, #6, #8, #15, #16, #18, #19 | Complete |
| 4 — Standing Orders | #14, #23 | **This phase** |
| Already flowing | #10, #11 | Complete |
