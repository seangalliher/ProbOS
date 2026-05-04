# AD-645b — EVALUATE Brief Alignment Criterion (AD-645 Phase 4)

**Wave:** 30
**Issue:** [#287](https://github.com/seang/ProbOS/issues/287)
**Depends on:** AD-645 Phases 1–3 (shipped). Brief is produced by ANALYZE
(`analyze.py:184`, `:383`, `:462`), rendered by COMPOSE (`compose.py:415-449`),
and stored as `WorkingMemoryEntry(category="reasoning")` post-REFLECT
(`cognitive_agent.py:2644-2663`). Phase 5 (NATS schema) is deferred to AD-641g.
**Estimated tests:** 7 (over the 6-floor).
**Roadmap:** `docs/development/roadmap.md` AD-645 entry; `docs/research/ad-645-artifact-mediated-cognitive-chain.md` Section 6 Phase 4.

---

## Problem

ANALYZE now produces a `composition_brief` (situation, key_evidence,
response_should_cover, tone, sources_to_draw_on, analytical_reasoning).
COMPOSE renders it. EVALUATE has no signal that the produced response
actually followed the brief. Per the research doc Section 4.3:

> Did COMPOSE use the evidence ANALYZE identified?
> Did the response cover what the brief said it should?
> Did the tone match the brief's guidance?

Today EVALUATE scores novelty, opening_quality, non_redundancy, relevance,
grounding (and on AD-639 mid-trust adds voice). It cannot detect "good
brief, but COMPOSE ignored it" failures (perception OK, execution OK,
plan-to-output alignment unknown). Phase 4 closes that gap with one
additional criterion — **brief_alignment** — assessed by the same LLM
verdict call, additive (not gating) per DD-7.

---

## Solution

Extend the two response-composition evaluation modes —
`ward_room_quality` and `proactive_quality` — with one additional
criterion `brief_alignment`. The criterion is built by:

1. Reading `composition_brief` from the prior ANALYZE result (already
   accessible via the existing `_get_analysis_result(prior_results)`
   helper at `evaluate.py:42`).
2. If the brief is present and is a non-empty dict, the existing mode
   prompt builder appends a brief-alignment criterion line to the
   `criteria` text, adds `brief_alignment` to the JSON schema, and
   renders the brief verbatim into the user prompt under a new
   `## Composition Brief` section. The LLM is instructed to score the
   alignment along three dimensions (covered_topics, used_evidence,
   matched_tone) but **not** to gate pass/fail on brief_alignment alone
   (DD-7 — additive, not gating).
3. If the brief is absent (legacy traces, SILENT contribution_assessment
   that nullified the brief, or chains that bypassed AD-645 Phase 1),
   the criterion is omitted from the LLM prompt entirely and the result
   is post-filled with a neutral entry:
   `{"pass": true, "score": 0.5, "reason": "brief absent",
   "dimensions": {}}`. This preserves the criteria-dict shape so
   downstream consumers can rely on it being present after AD-645b.

`notebook_quality` mode is intentionally untouched in v1 — notebook
entries are conclusions/findings, not direct responses to a composition
brief. Defer to AD-645b-i if observational data justifies extension.

The existing trust-band gates (low → skip evaluation entirely; mid →
adds voice criterion; bypasses for Captain/@mention/DM/boot-camp) are
unchanged. brief_alignment runs only on the LLM-evaluation path that
already runs for high-trust ward_room and proactive contributions.

---

## Section 1 — Helper additions in `evaluate.py`

Insert immediately after the existing `_get_analysis_result` helper at
`src/probos/cognitive/sub_tasks/evaluate.py:42`:

```python
# ---------------------------------------------------------------------------
# AD-645b: Composition brief alignment helpers (Phase 4)
# ---------------------------------------------------------------------------

def _get_composition_brief(prior_results: list[SubTaskResult]) -> dict | None:
    """Extract the composition_brief from the most recent successful Analyze.

    AD-645 Phase 1 schema (analyze.py:184/:383/:462). Returns ``None`` when
    the brief is absent (legacy traces, SILENT contribution, or chains
    without AD-645 Phase 1). Returns ``None`` if the field is present but
    not a dict (defensive against malformed LLM output).
    """
    analysis = _get_analysis_result(prior_results)
    brief = analysis.get("composition_brief") if analysis else None
    if not brief or not isinstance(brief, dict):
        return None
    return brief


_BRIEF_FIELDS_RENDERED: tuple[str, ...] = (
    "situation",
    "key_evidence",
    "response_should_cover",
    "tone",
    "sources_to_draw_on",
)


def _render_brief_for_eval(brief: dict) -> str:
    """Render the composition brief as a Markdown block for the eval LLM.

    Intentionally renders only the five fields most directly assessable
    against the response (situation, key_evidence, response_should_cover,
    tone, sources_to_draw_on). ``analytical_reasoning`` is the agent's
    own narrative reasoning and is not graded against the response.
    """
    parts: list[str] = ["## Composition Brief", ""]
    for key in _BRIEF_FIELDS_RENDERED:
        value = brief.get(key)
        if value is None or value == "" or value == []:
            continue
        label = key.replace("_", " ").title()
        if isinstance(value, list):
            parts.append(f"**{label}:**")
            for item in value:
                parts.append(f"- {item}")
            parts.append("")
        else:
            parts.append(f"**{label}:** {value}")
            parts.append("")
    return "\n".join(parts).rstrip()


_BRIEF_ALIGNMENT_CRITERION_TEXT: str = (
    "**Brief alignment** — Did the response cover what the brief said it "
    "should cover, use the brief's key_evidence, and match the brief's tone? "
    "Score along three sub-dimensions: covered_topics (response addresses each "
    "item in response_should_cover), used_evidence (response references at "
    "least one item from key_evidence), matched_tone (response register fits "
    "the brief's tone guidance). This criterion is informational; do NOT use "
    "it to gate pass/fail on its own.\n"
)


_BRIEF_ALIGNMENT_JSON_SCHEMA_FRAGMENT: str = (
    ', "brief_alignment": {"pass": true/false, "score": 0.0-1.0, '
    '"reason": "...", "dimensions": {"covered_topics": 0.0-1.0, '
    '"used_evidence": 0.0-1.0, "matched_tone": 0.0-1.0}}'
)
```

---

## Section 2 — Extend `_build_ward_room_eval_prompt`

Locate `_build_ward_room_eval_prompt` at `evaluate.py:53`. Two surgical
edits:

### 2a — Add brief alignment to `criteria` text and JSON schema

SEARCH (the AD-639 voice-criterion append block at evaluate.py:80-83):

```python
    # AD-639: Mid trust — add personality preservation criterion
    if trust_band == "mid":
        criteria += (
            "6. **Voice** — Response has a distinct voice consistent with the "
            "agent's personality, not generic or clinical.\n"
        )
```

REPLACE WITH:

```python
    # AD-639: Mid trust — add personality preservation criterion
    if trust_band == "mid":
        criteria += (
            "6. **Voice** — Response has a distinct voice consistent with the "
            "agent's personality, not generic or clinical.\n"
        )

    # AD-645b: Brief alignment criterion (Phase 4) — appended only when a
    # composition brief is available. Numbering after voice (if present).
    brief = _get_composition_brief(prior_results)
    if brief is not None:
        idx = 7 if trust_band == "mid" else 6
        criteria += f"{idx}. " + _BRIEF_ALIGNMENT_CRITERION_TEXT
```

### 2b — Add brief_alignment to JSON schema and render the brief in user prompt

SEARCH (the JSON schema construction at evaluate.py:84-100):

```python
    system_prompt = (
        f"You are evaluating a draft Ward Room response by {callsign} "
        f"({department} department).\n\n"
        f"Score the draft against these criteria:\n{criteria}\n"
        "Respond with JSON only:\n"
        '{"pass": true/false, "score": 0.0-1.0, '
        '"criteria": {"novelty": {"pass": true/false, "reason": "..."}, '
        '"opening_quality": {"pass": true/false, "reason": "..."}, '
        '"non_redundancy": {"pass": true/false, "reason": "..."}, '
        '"relevance": {"pass": true/false, "reason": "..."}, '
        '"grounding": {"pass": true/false, "reason": "..."}'
    )
    if trust_band == "mid":
        system_prompt += ', "voice": {"pass": true/false, "reason": "..."}'
    system_prompt += (
        '}, "recommendation": "approve"|"revise"|"suppress"}'
    )
```

REPLACE WITH:

```python
    system_prompt = (
        f"You are evaluating a draft Ward Room response by {callsign} "
        f"({department} department).\n\n"
        f"Score the draft against these criteria:\n{criteria}\n"
        "Respond with JSON only:\n"
        '{"pass": true/false, "score": 0.0-1.0, '
        '"criteria": {"novelty": {"pass": true/false, "reason": "..."}, '
        '"opening_quality": {"pass": true/false, "reason": "..."}, '
        '"non_redundancy": {"pass": true/false, "reason": "..."}, '
        '"relevance": {"pass": true/false, "reason": "..."}, '
        '"grounding": {"pass": true/false, "reason": "..."}'
    )
    if trust_band == "mid":
        system_prompt += ', "voice": {"pass": true/false, "reason": "..."}'
    if brief is not None:
        system_prompt += _BRIEF_ALIGNMENT_JSON_SCHEMA_FRAGMENT
    system_prompt += (
        '}, "recommendation": "approve"|"revise"|"suppress"}'
    )
```

### 2c — Render brief in user prompt

SEARCH (the user_prompt construction at evaluate.py:104-114):

```python
    compose_output = _get_compose_output(prior_results)
    analysis = _get_analysis_result(prior_results)
    original = context.get("context", "")

    user_prompt = (
        "## Draft Response to Evaluate\n\n"
        f"{compose_output}\n\n"
        "## Analysis That Informed This Draft\n\n"
        f"{json.dumps(analysis, indent=2)}\n\n"
        "## Original Content\n\n"
        f"{original}"
    )

    return system_prompt, user_prompt
```

REPLACE WITH:

```python
    compose_output = _get_compose_output(prior_results)
    analysis = _get_analysis_result(prior_results)
    original = context.get("context", "")

    user_parts: list[str] = [
        "## Draft Response to Evaluate",
        "",
        compose_output,
        "",
    ]
    # AD-645b: Render the brief explicitly so the eval LLM can compare
    # response-against-plan when scoring brief_alignment.
    if brief is not None:
        user_parts.append(_render_brief_for_eval(brief))
        user_parts.append("")
    user_parts.extend([
        "## Analysis That Informed This Draft",
        "",
        json.dumps(analysis, indent=2),
        "",
        "## Original Content",
        "",
        original,
    ])
    user_prompt = "\n".join(user_parts)

    return system_prompt, user_prompt
```

---

## Section 3 — Extend `_build_proactive_eval_prompt`

Same three edits as Section 2, applied to `_build_proactive_eval_prompt`
at `evaluate.py:120`. The proactive-mode criteria use a different
numbering (1–5 base + 6 voice on mid-trust). Append brief_alignment as
index 6 (high) or 7 (mid).

### 3a — After the AD-639 voice append at evaluate.py:147-152

SEARCH:

```python
    # AD-639: Mid trust — add personality preservation criterion
    if trust_band == "mid":
        criteria += (
            "6. **Voice** — Response has a distinct voice consistent with the "
            "agent's personality, not generic or clinical.\n"
        )

    system_prompt = (
        f"You are evaluating a draft proactive observation by {callsign} "
```

REPLACE WITH:

```python
    # AD-639: Mid trust — add personality preservation criterion
    if trust_band == "mid":
        criteria += (
            "6. **Voice** — Response has a distinct voice consistent with the "
            "agent's personality, not generic or clinical.\n"
        )

    # AD-645b: Brief alignment criterion (Phase 4)
    brief = _get_composition_brief(prior_results)
    if brief is not None:
        idx = 7 if trust_band == "mid" else 6
        criteria += f"{idx}. " + _BRIEF_ALIGNMENT_CRITERION_TEXT

    system_prompt = (
        f"You are evaluating a draft proactive observation by {callsign} "
```

### 3b — Add JSON schema fragment

SEARCH (the JSON schema construction at evaluate.py:159-176, the proactive-mode block ending in `recommendation`):

```python
        '"silence_appropriateness": {"pass": true/false, "reason": "..."}, '
        '"grounding": {"pass": true/false, "reason": "..."}'
    )
    if trust_band == "mid":
        system_prompt += ', "voice": {"pass": true/false, "reason": "..."}'
    system_prompt += (
        '}, "recommendation": "approve"|"revise"|"suppress"}'
    )
```

REPLACE WITH:

```python
        '"silence_appropriateness": {"pass": true/false, "reason": "..."}, '
        '"grounding": {"pass": true/false, "reason": "..."}'
    )
    if trust_band == "mid":
        system_prompt += ', "voice": {"pass": true/false, "reason": "..."}'
    if brief is not None:
        system_prompt += _BRIEF_ALIGNMENT_JSON_SCHEMA_FRAGMENT
    system_prompt += (
        '}, "recommendation": "approve"|"revise"|"suppress"}'
    )
```

### 3c — Render brief in user prompt

SEARCH (the user_prompt construction at the end of `_build_proactive_eval_prompt` — same shape as ward_room block at evaluate.py:178-188):

```python
    compose_output = _get_compose_output(prior_results)
    analysis = _get_analysis_result(prior_results)
    original = context.get("context", "")

    user_prompt = (
        "## Draft Response to Evaluate\n\n"
        f"{compose_output}\n\n"
        "## Analysis That Informed This Draft\n\n"
        f"{json.dumps(analysis, indent=2)}\n\n"
        "## Original Content\n\n"
        f"{original}"
    )

    return system_prompt, user_prompt
```

REPLACE WITH:

```python
    compose_output = _get_compose_output(prior_results)
    analysis = _get_analysis_result(prior_results)
    original = context.get("context", "")

    user_parts: list[str] = [
        "## Draft Response to Evaluate",
        "",
        compose_output,
        "",
    ]
    if brief is not None:
        user_parts.append(_render_brief_for_eval(brief))
        user_parts.append("")
    user_parts.extend([
        "## Analysis That Informed This Draft",
        "",
        json.dumps(analysis, indent=2),
        "",
        "## Original Content",
        "",
        original,
    ])
    user_prompt = "\n".join(user_parts)

    return system_prompt, user_prompt
```

> Both ward_room and proactive search-blocks contain the identical
> 11-line user_prompt construction. SEARCH/REPLACE will hit each
> function exactly once because the surrounding context (the
> immediately-preceding `if trust_band == "mid"` JSON schema append)
> differs between the two modes. If the Builder finds two matches,
> apply each surgically. The proactive block has
> `silence_appropriateness` + `grounding` keys before the trust-band
> append; the ward_room block has `relevance` + `grounding`.

---

## Section 4 — Post-LLM brief_alignment fill-in

Locate the result-construction block in `EvaluateHandler.__call__` at
`evaluate.py:567-575`. Insert a backfill block immediately after the
`result = {...}` dict construction so consumers see a present-but-neutral
`brief_alignment` entry whenever the brief was absent (criterion was
omitted from the LLM prompt) or whenever the LLM returned a verdict that
omitted the field despite being asked.

SEARCH:

```python
        # Ensure required keys
        result = {
            "pass": parsed.get("pass", True),
            "score": float(parsed.get("score", 1.0)),
            "criteria": parsed.get("criteria", {}),
            "recommendation": parsed.get("recommendation", "approve"),
        }

        logger.info(
            "AD-632e: Evaluate verdict for %s: pass=%s, score=%.2f, recommendation=%s",
```

REPLACE WITH:

```python
        # Ensure required keys
        result = {
            "pass": parsed.get("pass", True),
            "score": float(parsed.get("score", 1.0)),
            "criteria": parsed.get("criteria", {}),
            "recommendation": parsed.get("recommendation", "approve"),
        }

        # AD-645b Phase 4: Ensure brief_alignment is always present in
        # criteria. When the brief was absent OR the LLM omitted the field
        # despite being asked, post-fill with neutral score 0.5 and an
        # explanatory rationale. Additive-only — never overrides an
        # LLM-supplied verdict.
        _criteria = result["criteria"] if isinstance(result["criteria"], dict) else {}
        if "brief_alignment" not in _criteria:
            _brief_for_fill = _get_composition_brief(prior_results)
            if _brief_for_fill is None:
                _criteria["brief_alignment"] = {
                    "pass": True,
                    "score": 0.5,
                    "reason": "brief absent",
                    "dimensions": {},
                }
            else:
                _criteria["brief_alignment"] = {
                    "pass": True,
                    "score": 0.5,
                    "reason": "verdict omitted criterion",
                    "dimensions": {},
                }
            result["criteria"] = _criteria

        logger.info(
            "AD-632e: Evaluate verdict for %s: pass=%s, score=%.2f, recommendation=%s",
```

> Note: this backfill runs ONLY on the LLM-evaluation path (after JSON
> parse succeeds). The early-return paths (BF-184/187 captain/mention/DM
> bypass, AD-638 boot-camp bypass, AD-639 low-trust skip, BF-191 raw-JSON
> rejection, BF-204 grounding rejection, JSON-parse fallback to
> `_PASS_BY_DEFAULT`) intentionally do NOT carry brief_alignment because
> these paths short-circuit BEFORE any LLM evaluation runs. Consumers
> already key off `bypass_reason`/`rejection_reason` on those paths.

---

## Section 5 — Tests

Create `tests/test_ad645b_evaluate_brief_alignment.py`. Target 7 tests
(one over the 6-floor). The pattern mirrors existing chain-handler tests
that build a mock LLM client (`AsyncMock` returning a `LLMResponse`-shaped
namespace) and a synthetic `prior_results` list of `SubTaskResult`
instances.

```python
"""AD-645b Phase 4: EVALUATE brief alignment criterion tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.sub_task import SubTaskResult, SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.evaluate import (
    EvaluateHandler,
    _get_composition_brief,
    _render_brief_for_eval,
    _BRIEF_FIELDS_RENDERED,
)


def _make_compose_result(output: str) -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.COMPOSE,
        name="compose",
        result={"output": output},
        tokens_used=0,
        duration_ms=0,
        success=True,
        tier_used="",
    )


def _make_analyze_result(*, brief: dict | None) -> SubTaskResult:
    payload: dict = {"contribution_assessment": "RESPOND"}
    if brief is not None:
        payload["composition_brief"] = brief
    return SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name="analyze",
        result=payload,
        tokens_used=0,
        duration_ms=0,
        success=True,
        tier_used="",
    )


_SAMPLE_BRIEF: dict = {
    "situation": "Crew morale dipped after extended yellow alert.",
    "key_evidence": [
        "Backlog of 12 ward-room threads flagged 'urgent'",
        "Sleep-cycle telemetry below baseline for 3 days",
    ],
    "response_should_cover": [
        "Acknowledge the morale dip",
        "Offer one concrete remediation",
    ],
    "tone": "warm and pragmatic",
    "sources_to_draw_on": "ward_room threads, sleep telemetry",
    "analytical_reasoning": "Pattern echoes prior under-resting episodes.",
}


def _make_spec() -> SubTaskSpec:
    return SubTaskSpec(
        sub_task_type=SubTaskType.EVALUATE,
        name="evaluate",
        prompt_template="ward_room_quality",
        tier="standard",
    )


def _make_context() -> dict:
    # High trust path with no early-return bypasses.
    return {
        "_callsign": "Ezri",
        "_department": "Counseling",
        "_chain_trust_band": "high",
        "_agent_type": "ezri",
        "context": "Ward room thread on crew fatigue.",
    }


def test_get_composition_brief_returns_dict_when_present():
    prior = [_make_analyze_result(brief=_SAMPLE_BRIEF)]
    assert _get_composition_brief(prior) == _SAMPLE_BRIEF


def test_get_composition_brief_returns_none_when_absent():
    prior = [_make_analyze_result(brief=None)]
    assert _get_composition_brief(prior) is None


def test_get_composition_brief_returns_none_when_brief_not_dict():
    # Defensive: malformed LLM output stored as a string.
    bad = SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name="analyze",
        result={"composition_brief": "not a dict"},
        tokens_used=0,
        duration_ms=0,
        success=True,
        tier_used="",
    )
    assert _get_composition_brief([bad]) is None


def test_render_brief_includes_all_five_assessable_fields():
    rendered = _render_brief_for_eval(_SAMPLE_BRIEF)
    # All 5 _BRIEF_FIELDS_RENDERED labels show up in the rendered block.
    for key in _BRIEF_FIELDS_RENDERED:
        label = key.replace("_", " ").title()
        assert label in rendered, f"missing label {label!r} in {rendered!r}"
    # analytical_reasoning is intentionally NOT rendered (agent's own narrative).
    assert "Analytical Reasoning" not in rendered


@pytest.mark.asyncio
async def test_brief_alignment_in_prompt_when_brief_present():
    """Happy path: brief present → criterion text + JSON schema fragment +
    rendered brief all appear in the LLM call inputs."""
    captured: dict[str, str] = {}

    async def fake_complete(req):
        captured["system"] = req.system_prompt
        captured["user"] = req.prompt
        return SimpleNamespace(
            content=json.dumps(
                {
                    "pass": True,
                    "score": 0.85,
                    "criteria": {
                        "novelty": {"pass": True, "reason": "ok"},
                        "opening_quality": {"pass": True, "reason": "ok"},
                        "non_redundancy": {"pass": True, "reason": "ok"},
                        "relevance": {"pass": True, "reason": "ok"},
                        "grounding": {"pass": True, "reason": "ok"},
                        "brief_alignment": {
                            "pass": True,
                            "score": 0.9,
                            "reason": "covered all topics, used evidence, matched tone",
                            "dimensions": {
                                "covered_topics": 0.9,
                                "used_evidence": 0.8,
                                "matched_tone": 1.0,
                            },
                        },
                    },
                    "recommendation": "approve",
                }
            ),
            tokens_used=42,
            tier="standard",
        )

    llm = SimpleNamespace(complete=fake_complete)
    handler = EvaluateHandler(llm_client=llm, runtime=None)
    prior = [
        _make_analyze_result(brief=_SAMPLE_BRIEF),
        _make_compose_result(
            "Crew fatigue is showing. Suggest a 24h reduced-ops window."
        ),
    ]
    result = await handler(_make_spec(), _make_context(), prior)

    # System prompt instructs on brief_alignment + JSON schema fragment present.
    assert "Brief alignment" in captured["system"]
    assert "brief_alignment" in captured["system"]
    assert "covered_topics" in captured["system"]
    # User prompt contains the rendered brief.
    assert "## Composition Brief" in captured["user"]
    assert "Warm And Pragmatic" in captured["user"] or "warm and pragmatic" in captured["user"]
    # Result preserves the LLM's brief_alignment dict.
    assert result.success is True
    ba = result.result["criteria"]["brief_alignment"]
    assert ba["score"] == 0.9
    assert ba["dimensions"] == {"covered_topics": 0.9, "used_evidence": 0.8, "matched_tone": 1.0}
    # LLM's overall score is preserved verbatim (additive, not gating — DD-7).
    assert result.result["score"] == 0.85


@pytest.mark.asyncio
async def test_brief_absent_post_fills_neutral_brief_alignment():
    """Backward compat: legacy trace with no brief → criterion not in LLM
    prompt, but post-LLM backfill inserts a neutral entry."""
    captured: dict[str, str] = {}

    async def fake_complete(req):
        captured["system"] = req.system_prompt
        captured["user"] = req.prompt
        return SimpleNamespace(
            content=json.dumps(
                {
                    "pass": True,
                    "score": 0.7,
                    "criteria": {
                        "novelty": {"pass": True, "reason": "ok"},
                        "opening_quality": {"pass": True, "reason": "ok"},
                        "non_redundancy": {"pass": True, "reason": "ok"},
                        "relevance": {"pass": True, "reason": "ok"},
                        "grounding": {"pass": True, "reason": "ok"},
                    },
                    "recommendation": "approve",
                }
            ),
            tokens_used=33,
            tier="standard",
        )

    llm = SimpleNamespace(complete=fake_complete)
    handler = EvaluateHandler(llm_client=llm, runtime=None)
    prior = [
        _make_analyze_result(brief=None),
        _make_compose_result("Some response."),
    ]
    result = await handler(_make_spec(), _make_context(), prior)

    # Criterion NOT in the LLM prompt when brief is absent.
    assert "Brief alignment" not in captured["system"]
    assert "## Composition Brief" not in captured["user"]
    # But result still has brief_alignment with the documented neutral shape.
    ba = result.result["criteria"]["brief_alignment"]
    assert ba == {
        "pass": True,
        "score": 0.5,
        "reason": "brief absent",
        "dimensions": {},
    }


@pytest.mark.asyncio
async def test_brief_present_but_llm_omits_criterion_post_fills_with_distinct_reason():
    """LLM ignored the criterion despite being asked → post-fill marks the
    omission so callers can distinguish 'brief absent' from 'verdict
    omitted'."""

    async def fake_complete(req):
        return SimpleNamespace(
            content=json.dumps(
                {
                    "pass": True,
                    "score": 0.75,
                    "criteria": {
                        "novelty": {"pass": True, "reason": "ok"},
                        "opening_quality": {"pass": True, "reason": "ok"},
                        "non_redundancy": {"pass": True, "reason": "ok"},
                        "relevance": {"pass": True, "reason": "ok"},
                        "grounding": {"pass": True, "reason": "ok"},
                    },
                    "recommendation": "approve",
                }
            ),
            tokens_used=33,
            tier="standard",
        )

    llm = SimpleNamespace(complete=fake_complete)
    handler = EvaluateHandler(llm_client=llm, runtime=None)
    prior = [
        _make_analyze_result(brief=_SAMPLE_BRIEF),
        _make_compose_result("Some response."),
    ]
    result = await handler(_make_spec(), _make_context(), prior)
    ba = result.result["criteria"]["brief_alignment"]
    assert ba["score"] == 0.5
    assert ba["reason"] == "verdict omitted criterion"
    assert ba["dimensions"] == {}
```

(7 tests total: 3 helper-shape, 1 render-shape, 3 handler integration.)

---

## Section 6 — What This Does NOT Change

- Phase 5 NATS schema (deferred to AD-641g) — no NATS subjects touched.
- AD-645 Phase 3 metacognitive storage — `cognitive_agent.py:2644-2663`
  WorkingMemory write of the brief is unchanged.
- The composition brief schema in ANALYZE (`analyze.py:184/383/462`) is
  unchanged. brief_alignment reads the brief; it does not write back.
- Trust-band gating, captain/@mention/DM/boot-camp bypasses, and
  BF-191/BF-204 deterministic rejections — all preserved verbatim.
  brief_alignment runs only on the LLM-eval path that already runs.
- `notebook_quality` mode — left untouched. Defer notebook-mode
  brief_alignment to AD-645b-i if data justifies.
- `pass`/`recommendation` thresholds — DD-7 says additive-not-gating.
  brief_alignment factors into the LLM's overall `score` only via the
  rubric instruction; no code-level pass/fail change.
- `_get_compose_output`, `_get_analysis_result` — unchanged. The new
  `_get_composition_brief` is a pure read on top of the existing helper.
- Aggregator score computation — there is no manual aggregator in
  `evaluate.py`; the LLM returns `score` directly. Section 4 preserves
  the LLM-supplied score and only ensures the criteria dict carries the
  brief_alignment key.

---

## Section 7 — Standing Conventions

- **Engineering Principles** in `.github/copilot-instructions.md` apply.
  Public helpers (`_get_composition_brief`, `_render_brief_for_eval`) are
  module-private (leading underscore) so the public-API typing rule
  applies in spirit; full annotations included regardless.
- **Frozen-dataclass field ordering** — N/A; no new dataclasses.
- **Tier-2 log-and-degrade** — N/A; brief absence is a documented
  domain branch, not a degradation. JSON-parse failure on the LLM
  verdict is already covered by the existing `_PASS_BY_DEFAULT`
  fallback at evaluate.py:556-565.
- **Privacy** — brief contents are rendered only into the
  agent-private LLM prompt context; no event payload changes. No new
  EventType in v1.
- **Test gate** — `pytest tests/ -q -n 8 --dist=loadfile`. Triage
  with `-n 0` if parallel-only failures appear.

---

## Section 8 — Tracking

- `progress-era-4-evolution.md` — append AD-645b CLOSED entry on close.
- `docs/development/roadmap.md` AD-645 entry — flip Phase 4 status to
  *(Complete, OSS, Issue #287)*; leave Phase 5 row as
  *(Deferred → AD-641g)*.
- `DECISIONS.md` — no new entry. DD-7 already documents the
  additive-not-gating choice in the research doc.
- `PROGRESS.md` line 320 (`AD-645 Phase 1-3 Complete...`) — extend to
  `AD-645 Phase 1-4 Complete. ... Phase 5 deferred to AD-641g.` on close.

---

## Section 9 — Acceptance Criteria

1. `_get_composition_brief` and `_render_brief_for_eval` helpers added at
   `evaluate.py:42`-area, fully type-annotated, module-private.
2. `_build_ward_room_eval_prompt` and `_build_proactive_eval_prompt` both
   conditionally include the brief_alignment criterion, JSON schema
   fragment, and rendered brief block when a brief is present.
3. `notebook_quality` mode is not modified.
4. Post-LLM backfill ensures `result["criteria"]["brief_alignment"]` is
   always present after the LLM-evaluation path with `reason="brief
   absent"` (legacy) or `reason="verdict omitted criterion"` (LLM
   regression).
5. Early-return paths (bypasses, deterministic rejections, JSON-parse
   fallback) are not modified.
6. 7 new focused tests pass at
   `tests/test_ad645b_evaluate_brief_alignment.py`.
7. Full gate `pytest tests/ -q -n 8 --dist=loadfile` passes at
   `10920 + 7 = 10927` (no pre-existing test changes; no test
   subtractions).
8. Verify all changes comply with the Engineering Principles in
   `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-04, HEAD `8c19530`)

```
grep -n "composition_brief" src/probos/cognitive/sub_tasks/analyze.py
  184:        f"7. **composition_brief**: Your analytical reasoning and composition plan. Include:\n"
  203:        f"   If contribution_assessment is \"SILENT\", composition_brief should be null.\n"
  383:        "6. **composition_brief**: Your analytical reasoning and composition plan. Include:\n"
  462:        "5. **composition_brief**: Your analytical reasoning and composition plan. Include:\n"

grep -n "composition_brief\|_get_analysis_result\|_get_compose_output" src/probos/cognitive/sub_tasks/compose.py
  418:        brief = analysis.get("composition_brief")

grep -n "_get_analysis_result\|_get_compose_output\|_EVALUATION_MODES\|_PASS_BY_DEFAULT\|trust_band ==" src/probos/cognitive/sub_tasks/evaluate.py
  31: def _get_compose_output(prior_results: list[SubTaskResult]) -> str:
  39: def _get_analysis_result(prior_results: list[SubTaskResult]) -> dict:
  53: def _build_ward_room_eval_prompt(
  68:         "1. **Novelty** ...
  80:     if trust_band == "mid":
  120: def _build_proactive_eval_prompt(
  148:     if trust_band == "mid":
  186:     if trust_band == "mid":
  246: _EVALUATION_MODES: dict[str, EvaluationModeBuilder] = {
  252: _PASS_BY_DEFAULT: dict[str, Any] = {
  539:     if context.get("_chain_trust_band") == "low":
  567:         result = {

grep -n "_composition_brief\|composition_brief" src/probos/cognitive/cognitive_agent.py
  1981:                    "_composition_brief": None,  # AD-645 Phase 3
  2010:        _composition_brief = None
  2013:                _composition_brief = r.result.get("composition_brief")
  2023:            "_composition_brief": _composition_brief,  # AD-645 Phase 3
  2200:                "_composition_brief": None,  # AD-645 Phase 3
  2644:            if _wm and decision.get("sub_task_chain") and decision.get("_composition_brief"):
  2645:                brief = decision["_composition_brief"]
  2663:                            metadata={"composition_brief": brief},
  3315:        brief = decision.get("_composition_brief")
```

All concrete claims in this prompt verified against HEAD `8c19530`.
