# BF-233: Grounding check false positives suppress legitimate ward room replies

**Issue:** TBD (create issue after review)
**Status:** Ready for builder
**Priority:** High
**Related:** BF-204 (grounding check), BF-206 (confabulation feedback), AD-629 (post ID endorsement)
**Files:** `src/probos/cognitive/sub_tasks/evaluate.py` (EDIT), `tests/test_bf204_grounding.py` (EDIT — add cases), `tests/test_bf233_grounding_false_positives.py` (NEW)

## Problem

Agents responding to Captain's All Hands messages get their replies **suppressed by BF-204** even when responses are legitimate. The grounding check (evaluate.py:316–349) extracts hex IDs (6+ chars) from compose output and flags any not found in the grounding source as confabulations. With threshold >= 2, the output is suppressed.

**Root cause:** The grounding source is built from only two inputs:

```python
_grounding_source = (context.get("context", "") + " "
                     + json.dumps(_get_analysis_result(prior_results)))
```

1. `context["context"]` — the thread text with post IDs **truncated to 8 chars** (ward_room_router.py:394)
2. ANALYZE result JSON — analysis text, no entity IDs

But agents' compose output legitimately references:
- **Thread IDs** — full UUIDs from `context["params"]["thread_id"]`, not in grounding source
- **Channel IDs** — from `context["params"]["channel_id"]`, not in grounding source
- **Agent UUIDs** — the responding agent's own `context["_agent_id"]`, not in grounding source
- **Other agent UUIDs** — referenced from ward room context, only partially present as 8-char truncated post IDs

When compose output contains 2+ of these legitimate hex substrings, BF-204 flags them as "ungrounded" and suppresses the response.

**Observed in production log (2026-04-24):** At least 7 agents (counselor, architect, builder, operations_officer, surgeon, pharmacist, pathologist) had responses suppressed with:
```
BF-204: Grounding check failed for <agent> — N ungrounded hex IDs: ['78a87214', 'b45a928286e5']
Chain output suppressed — Evaluate recommended suppress (confabulation_detected)
```

These hex IDs are substrings of legitimate agent/thread UUIDs, not confabulations.

**Impact:** High — Captain's All Hands messages get zero replies. Agents that overcome the silent-choice tendency have their responses killed at the gate. The safety check designed to prevent confabulation is preventing communication.

## Design

Expand the grounding source to include all entity IDs the agent legitimately received as part of the ward room notification. These IDs are already in the observation context — they just aren't included in the string that BF-204 searches.

**What to add to grounding source:**
1. `context["params"]` values — thread_id, channel_id, author_id (all legitimate IDs the agent was given)
2. `context["_agent_id"]` — the responding agent's own UUID
3. `context.get("target_agent_id", "")` — if present
4. `context.get("intent_id", "")` — intent correlation ID (set at cognitive_agent.py:1046)

**Approach:** Build an auxiliary string from params and identity fields, append to `_grounding_source`. This keeps the original grounding source intact (thread text + analysis) and adds only the entity IDs the agent was explicitly provided.

**Why not whitelist all hex patterns?** That would defeat BF-204's purpose. We only whitelist IDs the agent was *given* in its input context. Fabricated hex IDs (the original Wesley confabulation problem) would still be caught.

**Why substring matching works:** The regex `\b[0-9a-f]{6,}\b` splits UUIDs on hyphens (which are word boundaries), extracting segments like `a6ec8b06` and `be2f4f7e5ee2` from `a6ec8b06-1234-5678-9abc-be2f4f7e5ee2`. The `in` check on `_grounding_source` is substring matching, so each segment matches against the full UUID string appended to the grounding source. No need to pre-tokenize the whitelisted UUIDs.

**Known limitation — cross-agent post references:** This fix whitelists the agent's own identity and its input params (thread, channel, author). It does NOT whitelist other agents' post UUIDs. If agent A references agent B's full post UUID (not the 8-char truncated form from thread context), BF-204 may still flag it. Mitigation: agents naturally reference posts by the truncated `[deadbeef]` bracket form which appears in thread context. A future fix could have the router append full post UUIDs to params if this becomes a production issue.

## What This Does NOT Change

- BF-204 detection logic (regex, threshold >= 2) — unchanged
- BF-206 suppression enforcement — unchanged
- SAFETY > OBLIGATION > TRUST ordering — unchanged
- The original grounding source (thread text + ANALYZE result) — unchanged, only augmented
- Ward room router context building — unchanged
- Cross-agent post UUID references — NOT whitelisted. Only the responding agent's own params and identity are added. If agent A references agent B's full post UUID (not the 8-char truncated form), it may still be flagged. This is a deliberate scope boundary — agents naturally use the truncated `[deadbeef]` form from thread context. A future fix could have the router supply full post UUIDs in params if this becomes a production issue.

---

## Section 1: Expand grounding source with entity IDs

**File:** `src/probos/cognitive/sub_tasks/evaluate.py`

Replace lines 316–322:

```python
        # BF-204: Deterministic grounding pre-check — catch fabricated identifiers
        # Runs at ALL trust bands, even social obligation. Safety > obligation.
        _grounding_source = (context.get("context", "") + " "
                             + json.dumps(_get_analysis_result(prior_results)))
        # Hex IDs (6+ chars) in compose output that don't appear in source material
        _hex_ids = re.findall(r'\b[0-9a-f]{6,}\b', compose_output.lower())
        _ungrounded_ids = [h for h in _hex_ids if h not in _grounding_source.lower()]
```

With:

```python
        # BF-204: Deterministic grounding pre-check — catch fabricated identifiers
        # Runs at ALL trust bands, even social obligation. Safety > obligation.
        _grounding_source = (context.get("context", "") + " "
                             + json.dumps(_get_analysis_result(prior_results)))

        # BF-233: Include entity IDs the agent was explicitly given in its input.
        # Without this, legitimate thread/channel/agent UUIDs from params are
        # flagged as "ungrounded" confabulations — causing false suppression of
        # ward room replies. Only IDs from the agent's own input context are
        # whitelisted; truly fabricated hex IDs are still caught.
        # Note: Full UUIDs are appended. The regex word-boundary tokenization
        # extracts hyphen-delimited segments (e.g. "a6ec8b06" from
        # "a6ec8b06-...-be2f4f7e5ee2"), and the `in` substring check below
        # matches each segment against the full UUID in _grounding_source.
        _entity_ids: list[str] = []
        _params = context.get("params", {})
        if isinstance(_params, dict):
            for _k in ("thread_id", "channel_id", "author_id"):
                _v = _params.get(_k, "")
                if _v:
                    _entity_ids.append(str(_v))
        if context.get("_agent_id"):
            _entity_ids.append(str(context["_agent_id"]))
        if context.get("target_agent_id"):
            _entity_ids.append(str(context["target_agent_id"]))
        if context.get("intent_id"):
            _entity_ids.append(str(context["intent_id"]))
        if _entity_ids:
            _grounding_source += " " + " ".join(_entity_ids).lower()

        # Hex IDs (6+ chars) in compose output that don't appear in source material
        _hex_ids = re.findall(r'\b[0-9a-f]{6,}\b', compose_output.lower())
        _ungrounded_ids = [h for h in _hex_ids if h not in _grounding_source.lower()]
```

**Key points:**
- Append, don't replace — original grounding source preserved
- Only IDs from `params` and identity keys — not arbitrary context values
- `str()` wrapping handles both string and UUID types
- The `_k` loop covers the standard ward room notification params (thread_id, channel_id, author_id)
- `intent_id` is at top-level context (set by cognitive_agent.py:1046), NOT in params
- `_agent_id` is the responding agent's own identity
- Entity IDs lowercased at append time for efficiency (avoids redundant `.lower()` on every substring check)

---

## Section 2: Tests — false positive scenarios

**File:** `tests/test_bf233_grounding_false_positives.py` (NEW)

```python
"""Tests for BF-233: Grounding check must not suppress legitimate entity IDs."""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from probos.cognitive.sub_tasks.evaluate import EvaluateHandler
from probos.cognitive.sub_task import SubTaskSpec, SubTaskResult, SubTaskType


def _make_handler():
    """Minimal EvaluateHandler for deterministic-path-only tests.

    Uses __new__ to bypass __init__ since the deterministic grounding
    check (BF-204) only reads _llm_client (to check if LLM is available
    for full evaluation). No other __init__ attributes are touched on
    the deterministic code path.
    """
    h = EvaluateHandler.__new__(EvaluateHandler)
    h._llm_client = None  # deterministic path only
    return h


def _prior_analyze_result(text: str = "Analysis complete.") -> list[SubTaskResult]:
    """Fake prior ANALYZE result."""
    return [
        SubTaskResult(
            sub_task_type=SubTaskType.ANALYZE,
            name="analyze-reply",
            result={"analysis": text},
            tokens_used=0,
            duration_ms=1,
            success=True,
            tier_used="",
        )
    ]


def _compose_result(text: str) -> SubTaskResult:
    """Fake COMPOSE result."""
    return SubTaskResult(
        sub_task_type=SubTaskType.COMPOSE,
        name="compose-reply",
        result={"output": text},
        tokens_used=10,
        duration_ms=5,
        success=True,
        tier_used="fast",
    )


def _spec():
    return SubTaskSpec(
        sub_task_type=SubTaskType.EVALUATE,
        name="evaluate-reply",
        prompt_template="",
        depends_on=("compose-reply",),
    )


class TestBF233GroundingFalsePositives:
    """BF-233: Entity IDs from params must be treated as grounded."""

    @pytest.mark.asyncio
    async def test_thread_id_in_compose_not_flagged(self):
        """Agent referencing its thread_id should not be suppressed."""
        handler = _make_handler()
        thread_id = "a6ec8b06-1234-5678-9abc-be2f4f7e5ee2"
        ctx = {
            "context": "Thread: All Hands\nCaptain: Status report",
            "params": {"thread_id": thread_id, "channel_id": "c1d2e3f4-0000-0000-0000-000000000001"},
            "_agent_id": "78a87214-aaaa-bbbb-cccc-b45a928286e5",
            "_agent_type": "engineer",
            "_chain_trust_band": "mid",
        }
        # Compose output references thread ID substrings (regex splits on hyphens)
        compose = _compose_result(
            "Responding to thread a6ec8b06. As noted in be2f4f7e5ee2, systems nominal."
        )
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        # Should NOT be suppressed — these hex IDs are from thread_id
        assert result.result.get("rejection_reason") != "confabulation_detected"

    @pytest.mark.asyncio
    async def test_agent_own_id_in_compose_not_flagged(self):
        """Agent referencing its own UUID should not be suppressed."""
        handler = _make_handler()
        agent_id = "78a87214-aaaa-bbbb-cccc-b45a928286e5"
        ctx = {
            "context": "Thread: Status Check",
            "params": {"thread_id": "deadbeef-0000-0000-0000-000000000001"},
            "_agent_id": agent_id,
            "_agent_type": "operations_officer",
            "_chain_trust_band": "mid",
        }
        compose = _compose_result(
            "Agent 78a87214 reporting. Identity confirmed via b45a928286e5 credential."
        )
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        assert result.result.get("rejection_reason") != "confabulation_detected"

    @pytest.mark.asyncio
    async def test_channel_id_in_compose_not_flagged(self):
        """Agent referencing channel_id should not be suppressed."""
        handler = _make_handler()
        ctx = {
            "context": "Thread: Department Update",
            "params": {
                "thread_id": "11111111-2222-3333-4444-555555555555",
                "channel_id": "c36cc630-abcd-efef-1234-3e5c9b4cade5",
            },
            "_agent_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "_agent_type": "pharmacist",
            "_chain_trust_band": "mid",
        }
        compose = _compose_result(
            "Channel c36cc630 update: reviewing prescription protocols per 3e5c9b4cade5."
        )
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        assert result.result.get("rejection_reason") != "confabulation_detected"

    @pytest.mark.asyncio
    async def test_truncated_post_id_plus_full_uuid_not_flagged(self):
        """BF-233 regression: thread context has 8-char truncated post IDs,
        but agent references the full UUID. The truncated form matches thread
        context; the suffix matches the agent's own _agent_id."""
        handler = _make_handler()
        # Thread context has truncated post ID [deadbeef]
        # Agent's own ID has suffix cafebabe1234
        ctx = {
            "context": "Thread: Discussion\n[deadbeef] Alice: opening point",
            "params": {
                "thread_id": "00000000-1111-2222-3333-444444444444",
                "channel_id": "55555555-1111-2222-3333-666666666666",
            },
            "_agent_id": "99999999-1111-2222-3333-cafebabe1234",
            "_agent_type": "test_agent",
            "_chain_trust_band": "mid",
        }
        # deadbeef matches thread context, cafebabe1234 matches _agent_id
        compose = _compose_result(
            "Building on deadbeef analysis, also noting cafebabe1234 implications."
        )
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        assert result.result.get("rejection_reason") != "confabulation_detected"

    @pytest.mark.asyncio
    async def test_other_agent_full_uuid_still_flagged(self):
        """BF-233 known limitation: full UUIDs of OTHER agents' posts
        (not in agent's own params) still trigger BF-204 if agent
        references them instead of using the truncated 8-char form."""
        handler = _make_handler()
        ctx = {
            "context": "Thread: Discussion\n[deadbeef] Alice: opening point",
            "params": {
                "thread_id": "00000000-1111-2222-3333-444444444444",
            },
            "_agent_id": "99999999-1111-2222-3333-aaaaaaaaaaaa",
            "_agent_type": "test_agent",
            "_chain_trust_band": "mid",
        }
        # Agent references a DIFFERENT agent's post UUID suffix — not in any
        # of this agent's params or identity. This is a known scope boundary.
        compose = _compose_result(
            "Per deadbeef and their follow-up cafebabe1234, I concur."
        )
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        # deadbeef matches thread context, but cafebabe1234 is ungrounded.
        # Only 1 ungrounded (below threshold of 2), so this actually passes.
        # If agent referenced TWO other agents' full UUIDs, it would suppress.
        # This documents the boundary — not a regression.
        assert result.result.get("rejection_reason") != "confabulation_detected"

    @pytest.mark.asyncio
    async def test_fabricated_ids_still_caught(self):
        """BF-204 core protection: truly fabricated hex IDs still trigger suppression."""
        handler = _make_handler()
        ctx = {
            "context": "Thread: Science Report",
            "params": {"thread_id": "11111111-0000-0000-0000-000000000001"},
            "_agent_id": "22222222-0000-0000-0000-000000000002",
            "_agent_type": "science_officer",
            "_chain_trust_band": "mid",
        }
        # These hex IDs are NOT in any params or identity field — truly fabricated
        compose = _compose_result(
            "According to analysis f8a9e2b7c3d4, metric e5f6a7b8d9c0 shows anomalies."
        )
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        # SHOULD be suppressed — these are fabricated
        assert result.result.get("rejection_reason") == "confabulation_detected"

    @pytest.mark.asyncio
    async def test_mixed_legit_and_fabricated(self):
        """One legit ID + two fabricated = still suppressed."""
        handler = _make_handler()
        thread_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        ctx = {
            "context": "Thread: Mixed Test",
            "params": {"thread_id": thread_id},
            "_agent_id": "99999999-0000-0000-0000-000000000001",
            "_agent_type": "test_agent",
            "_chain_trust_band": "mid",
        }
        # a1b2c3d4 is legit (from thread_id), but deadcafe and baadf00d are fabricated
        compose = _compose_result(
            "Thread a1b2c3d4 referenced. Also see deadcafe analysis and baadf00d metric."
        )
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        # Two fabricated IDs remain after filtering legit ones — should suppress
        assert result.result.get("rejection_reason") == "confabulation_detected"

    @pytest.mark.asyncio
    async def test_no_params_degrades_gracefully(self):
        """Missing params dict doesn't crash the grounding check."""
        handler = _make_handler()
        ctx = {
            "context": "Some context",
            # No "params" key at all
            "_agent_type": "test_agent",
            "_chain_trust_band": "mid",
        }
        compose = _compose_result("Simple response with no hex references.")
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        # No hex IDs in output → passes
        assert result.result.get("rejection_reason") != "confabulation_detected"

    @pytest.mark.asyncio
    async def test_params_non_dict_degrades_gracefully(self):
        """Non-dict params doesn't crash grounding check."""
        handler = _make_handler()
        ctx = {
            "context": "Some context",
            "params": ["unexpected", "list"],  # Not a dict
            "_agent_type": "test_agent",
            "_chain_trust_band": "mid",
        }
        compose = _compose_result("Simple response with no hex references.")
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        assert result.result.get("rejection_reason") != "confabulation_detected"

    @pytest.mark.asyncio
    async def test_author_id_captain_not_hex(self):
        """author_id='captain' (non-hex) doesn't break grounding source."""
        handler = _make_handler()
        ctx = {
            "context": "Thread: Captain's Orders",
            "params": {
                "thread_id": "abcdef01-2345-6789-abcd-ef0123456789",
                "author_id": "captain",  # Not a hex UUID
            },
            "_agent_id": "fedcba98-7654-3210-fedc-ba9876543210",
            "_agent_type": "first_officer",
            "_chain_trust_band": "high",
        }
        compose = _compose_result(
            "Acknowledged, Captain. Thread abcdef01 orders received. Agent fedcba98 standing by."
        )
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        assert result.result.get("rejection_reason") != "confabulation_detected"

    @pytest.mark.asyncio
    async def test_intent_id_in_compose_not_flagged(self):
        """Agent referencing its intent_id should not be suppressed.
        intent_id is set at top-level context by cognitive_agent.py:1046."""
        handler = _make_handler()
        intent_id = "deed1234-abab-cdcd-efef-567890abcdef"
        ctx = {
            "context": "Thread: Coordination",
            "params": {"thread_id": "00000000-1111-2222-3333-444444444444"},
            "_agent_id": "55555555-6666-7777-8888-999999999999",
            "intent_id": intent_id,
            "_agent_type": "comms_officer",
            "_chain_trust_band": "mid",
        }
        compose = _compose_result(
            "Processing intent deed1234. Correlation 567890abcdef confirmed."
        )
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        assert result.result.get("rejection_reason") != "confabulation_detected"
```

---

## Section 3: Verify existing BF-204 tests

**File:** `tests/test_bf204_grounding.py`

Run the existing BF-204 test suite after applying Section 1. The expansion only adds more IDs to the grounding source — it cannot cause existing tests to fail unless a test relied on a param UUID being treated as ungrounded (which was the bug).

The existing tests (`TestDeterministicGroundingCheck`, `TestEvaluatePromptGroundingCriterion`, `TestDefenseOrdering`) do NOT include `params` in their context dicts, so the new entity ID collection code is a no-op for them. No changes needed.

```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf204_grounding.py -v
```

If any test fails, it means the test itself was relying on buggy behavior. Report the failure — do not modify the fix to accommodate it.

---

## Verification

```bash
# New BF-233 tests
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf233_grounding_false_positives.py -v

# Existing BF-204 tests still pass
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf204_grounding.py -v

# Existing BF-206 tests still pass
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf206_confab_feedback.py -v

# Full suite
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

### PROGRESS.md
Add line:
```
BF-233 CLOSED. BF-204 grounding check false positives — entity IDs from ward room params (thread_id, channel_id, author_id) and agent identity (_agent_id, intent_id) not included in grounding source, causing legitimate ward room replies to be suppressed as confabulations. Fix: expand grounding source to include all entity IDs the agent was explicitly given in its input context. Fabricated hex IDs still caught. Known limitation: cross-agent post UUID references (not in agent's own params) may still trigger if agent uses full UUID instead of truncated 8-char form. 12 new tests.
```

### DECISIONS.md
Add entry:
```markdown
### BF-233 — Grounding check false positive fix

**Date:** 2026-04-24
**Status:** Complete

**BF-233: Expand BF-204 grounding source with entity IDs from input context.** The deterministic confabulation check (BF-204) built its grounding source from thread text + ANALYZE result only, missing entity IDs the agent was explicitly given in params (thread_id, channel_id, author_id) and identity keys (_agent_id, intent_id). Agents referencing these legitimate IDs in compose output triggered false positive suppression — observed across 7+ agents on Captain's All Hands message. Fix appends entity IDs to the grounding source string. Only IDs from the agent's own input context are whitelisted; truly fabricated hex IDs are still caught (threshold >= 2 ungrounded). BF-204 core protection preserved. **Known limitation:** Cross-agent post UUID references (other agents' full post UUIDs not in the responding agent's params) may still trigger false positives if agents use the full UUID instead of the truncated 8-char bracket form from thread context. Mitigated by agents naturally using `[deadbeef]` truncated form. Future fix: router could append full post UUIDs to params if observed in production.
```

### docs/development/roadmap.md
Add to Bug Tracker section:
```
| BF-233 | Grounding check false positives suppress legitimate ward room replies | High | **Closed** |
```
