# AD-721d-2 — Counselor-mediated avatar revision (vs Captain-driven hint)

**Wave:** 162
**Closes:** #618
**Status:** ready to build
**Dependencies:** AD-721d-1 (Wave 145 — Captain-driven DSL request-revision shipped); AD-718a (voice proposal pattern); CounselorAgent (existing). Note: roadmap.md line 379 references this issue as #621 in the table; user dispatch references it as #618. Builder confirms #618 is the active issue by `gh issue view 618`.
**Estimated tests:** +8 pytest (+2 vitest for HXI surface).
**Scope tag:** Server-only + small UI tweak. No new pip/npm deps. Apache 2.0.

---

## Problem

[Issue #618](https://github.com/seangalliher/ProbOS/issues/618) — AD-721d-1 (Wave 145) ships **Captain-driven** agent self-revision: the Captain types a 280-char hint, the agent re-proposes its avatar DSL. The flow puts the entire revision-judgment burden on the Captain.

The forward-marker scope: route revision hints through the **Counselor** (or domain-appropriate agent), so the Captain says *"Counselor, Echo's avatar feels too formal — work with her on something warmer"* and the Counselor mediates. New intent: `mediate_appearance_revision(target_agent_id, captain_hint)`.

---

## Solution overview

1. New intent + IntentDescriptor: `mediate_appearance_revision`, handled by the CounselorAgent. Destructive? No — read-only mediation that produces a NEW proposal via the existing AD-721d-1 path.
2. Counselor's handler:
   - Reads target agent's current DSL.
   - Constructs a Counselor-flavored prompt: original Captain hint + her own framing (warmer/less formal/etc.) + the target agent's current DSL.
   - Calls the LLM to produce a refined hint (≤280 chars) that the target agent can act on.
   - Invokes the existing AD-721d-1 `POST /agents/{target_id}/appearance/propose` endpoint with `captain_note=<refined_hint>` and `previous_dsl=<target's current DSL>`.
3. New endpoint `POST /agents/{captain or counselor}/appearance/mediate` — surfaces the flow to the HXI. Body: `{target_agent_id, captain_hint}`.
4. HXI surface: a small "Counselor-mediated" button on the existing CrewAvatarPopout (or in the chat shortcut bar). Vitest test for the button render.

### What this does NOT change

- AD-721d-1 Captain-driven flow (still works; this AD ADDS a mediated path).
- The DSL proposal-history sidecar (AD-721d-4 — entries from mediated revisions land with the same structure; `source` field optionally records "counselor_mediated").
- The CounselorAgent's existing duties (this AD adds a new intent handler).
- The renderer (AD-721i).
- AD-731 / vision-tier invariants.

---

## Section 0 — IntentDescriptor + EventType

`src/probos/events.py`:
```python
APPEARANCE_REVISION_MEDIATED = "appearance_revision_mediated"  # AD-721d-2
```

Counselor IntentDescriptor registration (location depends on Counselor's existing descriptor list — read `src/probos/agents/counselor*.py` or equivalent):
```python
IntentDescriptor(
    intent="mediate_appearance_revision",
    description="Counselor mediates Captain's avatar revision hint, producing a refined hint for the target agent.",
    requires_consensus=False,  # read-only / mediation, not destructive
    parameters={
        "target_agent_id": "str",
        "captain_hint": "str (≤280 chars)",
    },
)
```

---

## Section 1 — Counselor handler

Add to `src/probos/agents/counselor.py` (or wherever Counselor lives — grep for the class):

```python
async def _handle_mediate_appearance_revision(
    self,
    target_agent_id: str,
    captain_hint: str,
) -> dict:
    """AD-721d-2: refine the Captain's hint and forward to target agent's
    AD-721d-1 propose endpoint.
    """
    if not captain_hint or len(captain_hint) > 280:
        return {"ok": False, "reason": "invalid_hint_length"}

    # Read target agent and its current DSL via the registry.
    # `crew.appearance.dsl` is the canonical persisted DSL (see
    # `routers/agents.py:550` for the write site).
    target_agent = self._runtime.registry.get(target_agent_id)
    if target_agent is None:
        return {"ok": False, "reason": "target_agent_unknown"}
    target_crew = getattr(target_agent, "crew", None) or getattr(
        self._runtime, "crew_registry", None,
    )
    try:
        # Prefer agent.crew.appearance.dsl when present; fall back to
        # the runtime-level crew profile lookup. Builder: verify the
        # accessor path against the live agent shape; do NOT invent
        # a new field.
        target_dsl = (
            getattr(getattr(target_agent, "appearance", None), "dsl", None)
            or (target_crew.get(target_agent_id).appearance.dsl
                if hasattr(target_crew, "get") else None)
        )
    except Exception:
        target_dsl = None
    if target_dsl is None:
        return {"ok": False, "reason": "target_dsl_unavailable"}

    refine_prompt = (
        f"You are the Ship's Counselor. The Captain wants to revise "
        f"{target_agent_id}'s avatar with this hint:\n\n"
        f"\"{captain_hint}\"\n\n"
        f"Their current avatar (DSL summary): {self._summarize_dsl(target_dsl)}\n\n"
        f"Refine the Captain's hint into a ≤280 char directive for "
        f"{target_agent_id} that respects: (a) their agency, (b) the Captain's intent, "
        f"(c) your own clinical judgment. Output only the refined hint, no preface."
    )
    try:
        refined = await self._runtime.llm_client.complete(
            tier="standard",
            prompt=refine_prompt,
        )
        refined = (refined or "").strip()[:280]
        if not refined:
            return {"ok": False, "reason": "refinement_empty"}
    except Exception:
        logger.warning(
            "AD-721d-2: refinement LLM call failed target=%s",
            target_agent_id, exc_info=True,
        )
        return {"ok": False, "reason": "refinement_failed"}

    # Invoke the target agent's AD-721d propose flow directly via the
    # registered agent's public method. This is the same call shape
    # `routers/agents.py:454` uses (`await agent.propose_appearance(captain_note=...)`).
    # Note: `propose_appearance` does NOT take `previous_dsl` — the
    # endpoint validates `previous_dsl` server-side BEFORE the LLM call
    # (`routers/agents.py:421-431`) and the cognitive method itself
    # reflects on the agent's own persisted appearance.
    try:
        if not hasattr(target_agent, "propose_appearance"):
            return {"ok": False, "reason": "target_not_proposable"}
        proposed_dsl = await target_agent.propose_appearance(captain_note=refined)
    except Exception:
        logger.warning(
            "AD-721d-2: target.propose_appearance failed target=%s",
            target_agent_id, exc_info=True,
        )
        return {"ok": False, "reason": "propose_failed"}

    # Record into AD-721d-1 proposal_history sidecar — same module
    # `routers/agents.py` uses on the unmediated path.
    from probos.avatars import proposal_history
    proposal_iteration = proposal_history.iteration_count(target_agent_id) + 1

    self._emit_event(
        EventType.APPEARANCE_REVISION_MEDIATED,
        {"target_agent_id": target_agent_id,
         "captain_hint": captain_hint,
         "refined_hint": refined,
         "proposal_iteration": proposal_iteration},
    )
    return {"ok": True, "refined_hint": refined,
            "proposal_iteration": proposal_iteration,
            "proposed_dsl": proposed_dsl.model_dump()}
```

Builder: the live API surface used here is grep-confirmed:
- `runtime.registry.get(agent_id)` — standard agent registry lookup (used throughout `routers/agents.py`).
- `agent.propose_appearance(captain_note=...)` — `cognitive_agent.py:3246`.
- `proposal_history.iteration_count(agent_id)` — `avatars/proposal_history.py` (referenced from `routers/agents.py:438`).
- `runtime.llm_client.complete(...)` — verify against the live tier-aware client API in `cognitive/llm_client.py`; adapt parameter shape if needed.

The `source="counselor_mediated"` tag on the proposal-history sidecar is OPTIONAL — if AD-721d-1's `ProposalEntry` doesn't have a `source` field, omit (skip-don't-block; file forward marker AD-721d-2a to add source-tagging if Captain wants the audit signal).

---

## Section 2 — API endpoint surface

In `routers/agents.py`, add:

```python
class MediateAppearanceRevision(BaseModel):
    target_agent_id: str
    captain_hint: str = Field(..., min_length=1, max_length=280)


@router.post("/{agent_id}/appearance/mediate")
async def mediate_appearance_revision(
    agent_id: str,  # the mediator's agent_id (Counselor or domain-appropriate)
    req: MediateAppearanceRevision,
    runtime: Any = Depends(get_runtime),
):
    """AD-721d-2: route a Captain's revision hint through a mediator.

    The mediator's agent_id is in the path. Body carries target + hint.
    """
    # Dispatch the mediate_appearance_revision intent to the mediator agent.
    # Real targeted-RPC primitive: `IntentBus.send` at
    # `src/probos/mesh/intent.py:360` (`async def send(self, intent: IntentMessage) -> IntentResult | None`).
    # Do NOT use `IntentBus.broadcast` here — broadcast fans out to ALL
    # subscribers (memory: "IntentBus fan-out side effects").
    from probos.types import IntentMessage
    msg = IntentMessage(
        intent="mediate_appearance_revision",
        target_agent_id=agent_id,  # the mediator
        params={"target_agent_id": req.target_agent_id,
                "captain_hint": req.captain_hint},
    )
    intent_result = await runtime.intent_bus.send(msg)
    if intent_result is None:
        raise HTTPException(503, detail="mediator_unreachable")
    result = intent_result.result if hasattr(intent_result, "result") else intent_result
    if not isinstance(result, dict) or not result.get("ok"):
        reason = (result.get("reason") if isinstance(result, dict) else "mediation_failed") or "mediation_failed"
        raise HTTPException(422, detail=reason)
    return result
```

Builder: confirm `IntentMessage` field names against `src/probos/types.py` (the field is `target_agent_id` per the bus's `send` dispatch — grep to verify). The `IntentResult.result` accessor follows the established AD-720 pattern; if the bus returns the dict directly without a wrapper, adapt accordingly. Do NOT use `intent_bus.broadcast(...)` — broadcast fans out to all subscribers and would re-trigger the mediator multiple times when more than one Counselor-class agent is registered.

---

## Section 3 — HXI surface (small button)

In `ui/src/components/CrewAvatarPopout.tsx` (or wherever AD-721d-1's "Request revisions" button lives — grep `ui/src/` for `request-revision` / `RequestRevision`), add a sibling "Counselor-mediated revision" button. On click, opens a modal accepting `captain_hint` and POSTs to `/api/agent/<counselor_id>/appearance/mediate`.

Single `replace_string_in_file` per edit (BF-274).

UI test (Vitest): button renders for non-Counselor agents (Counselor mediating self is conceptually invalid — gate the button or simply allow it for v1; Builder picks the simpler shape).

**AD-738b reminder**: any UI change requires BOTH `cd ui ; npx vitest run` AND `cd ui ; npm run build`. Vitest greens are NOT a build proof.

---

## Section 4 — Tests

Python (`tests/test_ad721d_2_counselor_mediated_revision.py`) — 8 tests:

1. `test_mediate_happy_path` — POST hits Counselor, refined hint produced, AD-721d-1 propose called, event emitted.
2. `test_mediate_empty_hint_422`.
3. `test_mediate_hint_over_280_chars_422`.
4. `test_mediate_target_dsl_unavailable_returns_error` — registry returns an agent whose `appearance.dsl` is None → `{"ok": False, "reason": "target_dsl_unavailable"}`.
5. `test_mediate_llm_refinement_empty_returns_error`.
6. `test_mediate_propose_failure_returns_error` — `target_agent.propose_appearance` raises → `{"ok": False, "reason": "propose_failed"}`.
7. `test_mediated_proposal_history_entry_tagged_source` — sidecar entry carries `source="counselor_mediated"` (if AD-721d-1 supports the field; skip if not).
8. `test_mediated_proposal_does_not_skip_iteration_counter` — mediated revisions consume an iteration slot like Captain-driven ones (AD-721d-1 iteration cap respected).

Vitest (`ui/src/__tests__/CrewAvatarPopout.test.tsx` or sibling) — 2 tests:
1. `test_mediated_button_renders`.
2. `test_mediated_button_posts_to_mediate_endpoint`.

---

## Tracking

- `PROGRESS.md` — Wave 162 bullet.
- `docs/development/roadmap.md` — flip AD-721d-2 row to SHIPPED Wave 162. Forward markers: AD-721d-2a (`source` field on ProposalEntry if AD-721d-1 doesn't carry one — technical trigger: when audit signal is needed), AD-721d-2b (per-domain mediator selection — not always the Counselor; e.g., Engineering officer mediates engineering avatars — technical trigger: when ≥2 domain agents need their own avatar palettes mediated).
- `DECISIONS.md` — append entry.

---

## Acceptance criteria

- New intent `mediate_appearance_revision` registered with Counselor.
- New endpoint `POST /agents/{agent_id}/appearance/mediate` lands.
- Counselor handler refines hint via standard-tier LLM, forwards to AD-721d-1 propose path.
- AD-721d-1 iteration counter respected (mediated revisions count against the cap).
- HXI button added; Vitest tests green; `npm run build` green.
- New `EventType.APPEARANCE_REVISION_MEDIATED` registered.
- 8 pytest + 2 vitest tests green at `-n 0` and parallel.
- AD-731 invariant: no image bytes touch this code path (avatar DSL is structured text, not pixels).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-15)

- `src/probos/api_models.py:269-294` — AD-721d / AD-721d-1 proposal model shape confirmed (this AD's MediateAppearanceRevision sits as a sibling).
- `src/probos/avatars/proposal_history.py:1` — AD-721d-1 history module confirmed.
- `src/probos/routers/agents.py:390` — `@router.post("/{agent_id}/appearance/propose", ...)` confirmed.
- `src/probos/routers/agents.py:421-431` — AD-721d-1 `previous_dsl` validation + iteration counter confirmed.
- `config/standing_orders/counselor.md:1` — Counselor standing orders confirmed; she has ship-wide cognitive-wellness authority — mediation is in-scope.
- `docs/development/roadmap.md:379` — AD-721d-2 row confirmed (issue # in roadmap says #621; user dispatch says #618 — Builder confirms #618 via `gh issue view 618` at the start of work).
