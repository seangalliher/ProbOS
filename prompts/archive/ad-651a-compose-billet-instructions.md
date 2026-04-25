# AD-651a: Compose Billet Instructions — Proposal Format & Duty Report Framing

**Status:** Ready for builder
**Scope:** `src/probos/cognitive/sub_tasks/compose.py` (1 file modified)
**Tests:** 10 new tests in `tests/test_ad651a_compose_billet.py`
**Risk:** Low — additive prompt changes only, no structural changes
**Principle:** Billet Instruction (AD-651) — each chain step gets only the operational instructions it needs, prescriptively.

## Problem

Two action types that the prior crew produced reliably are now absent under the cognitive chain pipeline:

1. **Zero improvement proposals.** ANALYZE lists `"proposal"` as an `intended_actions` option (L.366) and COMPOSE mentions "file an improvement proposal" (L.221) but says "Refer to your standing orders for action tag syntax." The `[PROPOSAL]` block format (Title/Rationale/Affected Systems/Priority) is buried in standing orders (~2K tokens). COMPOSE has to *find* it in a large document — a fragile dependency on model attention. The extraction pipeline in `proactive.py:_extract_and_post_proposal()` (L.1893-1956) requires the exact `[PROPOSAL]...[/PROPOSAL]` format with structured fields. Without prescriptive format guidance, the LLM never produces it.

2. **No structured duty reports.** Duties execute and agents post observations, but the compose duty framing (L.206-214) says "Compose a Ward Room post with your findings (2-4 sentences)" — identical register to ad-hoc observations. Standing orders (ship.md L.225-237) say "Produce a structured report" and "Silence during a duty cycle requires explicit justification" but these instructions are buried in `compose_instructions()`. The prior crew's recognizable "Duty Cycle Report" format came from the one-shot path where all instructions influenced a single LLM call.

Both are instances of the AD-651 billet instruction gap: COMPOSE needs prescriptive operational guidance for specific output types, not a reference to a large document.

## Design

### Part A: Inject Proposal Format When Analyze Requests It

In `_build_proactive_compose_prompt()` (the non-duty branch, starting at L.217), after the existing framing, add conditional proposal format injection:

1. Read `intended_actions` from the analyze result via `_get_analysis_result(prior_results)`
2. If `"proposal"` is in the `intended_actions` list, append the `[PROPOSAL]` block syntax directly to the system prompt

**Implementation:**

After line 227 (end of the else-branch system_prompt), before the crew manifest injection (L.229), add:

```python
    # AD-651a: Billet instruction — inject proposal format when analyze requests it
    analysis = _get_analysis_result(prior_results)
    intended = analysis.get("intended_actions", [])
    if isinstance(intended, list) and "proposal" in intended:
        system_prompt += (
            "\n\n**You decided to file an improvement proposal.** Use this exact format "
            "as a SEPARATE block AFTER your observation text:\n"
            "```\n"
            "[PROPOSAL]\n"
            "Title: <short descriptive title>\n"
            "Rationale: <why this matters and what it would improve — be specific, "
            "cite evidence from your analysis>\n"
            "Affected Systems: <comma-separated subsystem names>\n"
            "Priority: low|medium|high\n"
            "[/PROPOSAL]\n"
            "```\n"
            "The proposal will be automatically posted to the Improvement Proposals channel. "
            "Your observation text will also be posted normally to your department channel."
        )
```

**Important:** This must also be injected in the duty branch (when `_active_duty` is present, L.203-215) since an agent could discover something proposal-worthy during a duty cycle. Add the same block after L.215.

### Part B: Structured Duty Report Framing

Replace the duty branch compose framing (L.203-215) with structured duty report guidance:

**Current** (L.206-214):
```python
        system_prompt += (
            f"\n\nYou are performing a scheduled duty: {_duty_desc}. "
            "Compose a Ward Room post with your findings (2-4 sentences). "
            "Speak in your natural voice. Be specific and actionable. "
            "Show your reasoning — explain what you found and why it matters, "
            "not just the data points. "
            "If there's another way to see this, mention it briefly. "
            "Don't just summarize — interpret. "
            "If nothing noteworthy to report, "
            "respond with exactly: [NO_RESPONSE]"
        )
```

**Replace with:**
```python
        system_prompt += (
            f"\n\n## Duty Report: {_duty_desc}\n\n"
            "You are performing a **scheduled duty**. This is not a casual observation — "
            "someone scheduled you to examine this area. You are obligated to report.\n\n"
            "**Format your response as a structured duty report:**\n"
            f"1. Start with a header: **Duty Report: {_duty_desc}**\n"
            "2. **Findings:** What you observed — cite specific metrics, counts, "
            "trends (improving/declining/stable), or notable events. Be evidence-based.\n"
            "3. **Assessment:** Your professional interpretation — what does this mean "
            "for the ship? Is this nominal, concerning, or noteworthy?\n"
            "4. **Recommendation:** If action is warranted, what should happen next? "
            "If nominal, say so explicitly — a null finding is valuable.\n\n"
            "Speak in your natural voice. Show your reasoning.\n"
            "A duty report saying 'nothing unusual — systems nominal' is better than "
            "silence. Silence during a duty cycle is dereliction.\n"
            "Do NOT respond with [NO_RESPONSE] during a duty cycle — report your findings, "
            "even if the finding is that everything is normal."
        )
```

**Key change:** Remove the `[NO_RESPONSE]` option from duty cycles. Standing orders (ship.md L.229-230) explicitly say "Silence during a duty cycle requires explicit justification" and "Not reporting is a dereliction." The prior compose framing contradicted this by offering `[NO_RESPONSE]` as an option.

### Part C: No Changes Needed Elsewhere

- `_extract_and_post_proposal()` (proactive.py L.1893-1956) already handles the `[PROPOSAL]...[/PROPOSAL]` extraction correctly — no changes needed there.
- `_build_user_prompt()` already passes the full analyze result including `intended_actions` via `_get_analysis_result()` — no changes needed.
- The `_should_short_circuit()` function already handles the `["silent"]` case — no changes needed.
- Standing orders remain unchanged — the operational instructions are being **copied into** the compose billet, not removed from standing orders. Standing orders remain the single source of truth; compose billets are derived extracts.

## Verification

```bash
# Targeted tests only
pytest tests/test_ad651a_compose_billet.py -x -q
```

## Tests — `tests/test_ad651a_compose_billet.py`

### Class: TestProposalBilletInjection

1. **`test_proposal_format_injected_when_analyze_requests_proposal`**
   - Setup: Create `prior_results` with analyze result containing `intended_actions: ["ward_room_post", "proposal"]`
   - Call `_build_proactive_compose_prompt()` with no active duty context
   - Assert: system prompt contains `"[PROPOSAL]"` format block AND `"Title:"` AND `"Rationale:"` AND `"Affected Systems:"` AND `"Priority:"`

2. **`test_proposal_format_not_injected_when_no_proposal_action`**
   - Setup: `intended_actions: ["ward_room_post"]` (no proposal)
   - Call `_build_proactive_compose_prompt()` with no active duty context
   - Assert: system prompt does NOT contain `"[PROPOSAL]"` format block

3. **`test_proposal_format_not_injected_when_silent`**
   - Setup: `intended_actions: ["silent"]`
   - Call `_build_proactive_compose_prompt()` — note: this will short-circuit, but the system prompt builder should still handle gracefully
   - Assert: system prompt does NOT contain `"[PROPOSAL]"` format block

4. **`test_proposal_format_injected_during_duty_cycle`**
   - Setup: `intended_actions: ["ward_room_post", "proposal"]` AND `_active_duty` context present
   - Call `_build_proactive_compose_prompt()` with duty context
   - Assert: system prompt contains BOTH duty report framing AND `"[PROPOSAL]"` format block

5. **`test_proposal_format_handles_missing_intended_actions`**
   - Setup: analyze result with no `intended_actions` key
   - Call `_build_proactive_compose_prompt()`
   - Assert: No crash, no `[PROPOSAL]` block injected

### Class: TestDutyReportFraming

6. **`test_duty_report_structured_format`**
   - Setup: `_active_duty: {"duty_id": "systems_check", "description": "Review engineering systems health"}`
   - Call `_build_proactive_compose_prompt()` with duty context
   - Assert: system prompt contains `"Duty Report:"` AND `"Findings:"` AND `"Assessment:"` AND `"Recommendation:"`

7. **`test_duty_report_no_no_response_option`**
   - Setup: same duty context
   - Call `_build_proactive_compose_prompt()` with duty context
   - Assert: system prompt does NOT contain `"[NO_RESPONSE]"` in the duty-specific framing section

8. **`test_duty_report_mentions_dereliction`**
   - Setup: same duty context
   - Call `_build_proactive_compose_prompt()` with duty context
   - Assert: system prompt contains `"dereliction"` — reinforces that silence is not acceptable during duty

9. **`test_non_duty_still_allows_no_response`**
   - Setup: no `_active_duty` in context
   - Call `_build_proactive_compose_prompt()` without duty context
   - Assert: the non-duty framing still works (mentions "observation", "proposal", "reply", etc.)

10. **`test_duty_report_includes_duty_description`**
    - Setup: `_active_duty: {"duty_id": "security_audit", "description": "Review system security posture"}`
    - Call `_build_proactive_compose_prompt()` with duty context
    - Assert: system prompt contains `"Review system security posture"` — duty description is injected into the report framing

## Engineering Principles Checklist

- **SOLID (SRP):** compose.py remains responsible for building compose prompts. No new modules, no new classes. The billet instruction logic is local to the prompt builder functions.
- **SOLID (OCP):** Extends behavior by adding conditional blocks within existing builder function. Does not modify the compose handler's call protocol.
- **LLM Independence Principle:** Proposal format and duty report structure are now prescriptive — a weaker model gets the exact format it needs rather than navigating a large document.
- **Billet Instruction Principle (AD-651):** Each compose invocation gets only the operational instructions relevant to its specific output type. Proposal format only when analyze decided to propose. Duty framing only when a duty is active.
- **Fail Fast:** Missing `intended_actions` handled gracefully (defaults to empty list, no injection). Standing orders remain as fallback — this is additive guidance, not a replacement.
- **Defense in Depth:** Standing orders still contain the canonical format definitions. Compose billets are derived extracts. If the billet injection fails, the standing orders path remains.
- **DRY:** The `[PROPOSAL]` format appears in both ship.md and the billet injection. This is intentional and acceptable — the standing orders are the canonical reference, the billet is a prescriptive extract for the compose step. When AD-651 Phase 2 lands, the billet instructions will be the sole source and standing orders will reference them.
