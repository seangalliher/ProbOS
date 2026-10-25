# BF-922: the chain's output gate (#1639): BF-204 grounds on what the composing call was given, ignores pure-decimal numbers and counts distinct ids; the single-call fallback runs the deterministic checks; the suppression log line names the agent

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-24
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-24 (Amendment A1: review round 1 of M1 and M2)

**Status:** build-ready. One BF, two milestones (M1 HIGH, M2 HIGH), one PR, one broad gate. **BF-921 (#1636) merged first, as PR #1651 (merge `471d3f7e`)**: the Architect's draft batched the two, and the orchestrator landed BF-921 alone because its review took three rounds; this prompt builds on that merge, and its M2 calls `CognitiveAgent._emit_output_suppressed`, which BF-921 M1 added. **BF number:** BF-922 (#1639); this contract allocates nothing. **Tier:** M1 **HIGH** (it changes what a safety check treats as grounded, in both directions); M2 **HIGH** (it gates an output path that was ungated, with a new suppression and a new event). The change is reviewed at HIGH: use the Copilot `Diff Reviewer`. Never lower a tier without the Captain. **Base:** `origin/main` `471d3f7e` (the BF-921 merge). **Line endings:** working copies are CRLF (`core.autocrlf=true`); every SEARCH here is LF; match and write with each file's own endings; new files are LF.

**Tests:**
- New `tests/test_bf922_output_grounding.py` (M1, 18 functions; with the parametrizations about 50 cases; Amendment A1 added the lookup-outcome rule and two real-chain lookup tests on a real `WardRoomService`).
- New fixture `tests/fixtures/bf922_live_grounding_cases.json` (M1; **written by the orchestrator before M1 starts**, from the live vessel read-only, section 6; the Builder never generates or edits it).
- New `tests/test_bf922_fallback_gate.py` (M2, 9 functions, 11 cases; A1 added the real-transport seam over the AD-835 suffix and the cache-replay test).
- Two existing tests change, by Amendment A1: `tests/test_ad1347_s4_chain_lookup.py` (section 7.4c: the lookup result carries its outcome) and `tests/test_ad1325_boundaries.py` (section 7.12: its exact-base bytes exclude the new `LLMResponse` field, as for AD-1327 and BF-901). No other existing test is expected to change (section 5); a focused failure is handled by the rule in section 6.

## 0. Premise: what is present on this tree

| Claim of #1639 (anchors on `4564fbd7`) | On `cb190f32` | Holds |
|---|---|---|
| BF-204 at `evaluate.py:489-548`; BF-233 ids `:494-517`; pattern `:520`; threshold `:522` | the same lines | yes |
| Grounding source: analysis context, prior results, three params ids, agent, target, intent id | `:491-517`: `context["context"]` + `json.dumps(analysis)` + those ids | yes |
| The pattern also matches pure-decimal numbers | `re.findall(r'\b[0-9a-f]{6,}\b', ...)` `:520` | yes |
| The threshold counts repeats | `len(_ungrounded_ids) >= 2` over a list `:521-522` | yes |
| Triage failure returns `None` (`:6188-6196`) | `cognitive_agent.py:6242-6254` | yes (moved) |
| Chain failure returns `None` (`:5918-5934`) | `cognitive_agent.py:5978-5991` | yes (moved) |
| On `None`, `decide()` falls through to `_decide_via_llm` (`:3807-3811`), which runs no EVALUATE | `:3800-3811`; `_decide_via_llm` `:3833-4560` | yes |
| The BF-206 suppression line names no agent (`:5944-5947`) | `cognitive_agent.py:6002-6005` | yes (moved) |
| `CONFABULATION_SUPPRESSED` not persisted (`event_persistence.py:195`) | the same | yes (BF-921 R1) |

**The rendering that makes the false positives.** The router shows each recent post as `[<first 8 hex>] <callsign>: <body>` (`ward_room_router.py:549-550`) inside `context["context"]`, but the composer is also given Ward Room activity (`thread:<8 hex> post:<8 hex>`, `cognitive_agent.py:9395-9398`, rendered by COMPOSE `compose.py:542-544`), episodic memories (`:477-479`), the AD-1347 lookup with full post and thread ids (`ward_room/lookup.py:413`, `compose.py:510-517`), QUERY data and the oracle context. BF-204's source contains none of these. In the live sample (`notes-bf922-live-cases.txt`), the cited strings are the first 8 or last 12 hex of one post's UUID: copied, not invented.

## 1. Problem

1. **BF-204 flags real ids** (216 of 309 live cases cite only real Ward Room ids: 426 post, 67 channel and 14 thread segments). Its source is narrower than what the composer is given, and it includes one source the composer did not get from the world: `json.dumps` of the ANALYZE result (`evaluate.py:491-492`), model output, so an id an earlier step invented is grounded by being repeated. The pattern matches pure-decimal numbers (3 live cases are decimal-only) and the threshold counts one id twice (12 live cases, e.g. `['5999983','5999983']`, `systems_analyst`, 2026-10-22 13:05:30).
2. **The fallback is ungated.** A triage failure or chain failure returns `None`, and the single call that answers instead runs neither BF-191 nor BF-204 (3,322 triage and 40 chain failures in the live logs). BF-204's own comment says it "Runs at ALL trust bands, even social obligation. Safety > obligation." (`evaluate.py:490`); the fallback breaks that.
3. **The suppression line** `BF-206: Chain output suppressed — Evaluate recommended suppress (%s)` names no agent.

## 2. Solution overview

- **M1.** New module `probos/cognitive/output_grounding.py` holds BF-191 and BF-204 once (pattern, distinct counting, threshold, the log lines), for EVALUATE and the fallback. EVALUATE grounds on `composer_world_text`, a new public function in `compose.py` that renders COMPOSE's own user prompt without the ANALYZE result, plus BF-233's intent ids. A cited id is a whole word of 6+ hex characters with at least one letter; ids are counted once.
- **M2.** `decide()` marks the observation while a single call answers for a chain that returned no decision; `_decide_via_llm` then runs the same deterministic checks on its reply, grounded on its own request text and the intent ids, and on a rejection returns BF-206's suppressed decision, logs, and emits through BF-921's emitter with `path="single_call_fallback"`. The BF-206 line names the agent type, callsign and id.

## 3. Decisions (for #1639)

**D1, the grounding source (item 1).** Ranked: (1, chosen) **what the composing call was given from outside the chain's own model calls**: `composer_world_text(context, prior_results)`, i.e. COMPOSE's `_build_user_prompt` over the prior results without ANALYZE. That covers the thread, QUERY data, memories, lookups, oracle and situation sections, from the same function that renders them, so a section added to COMPOSE later is covered automatically. Plus BF-233's intent ids (`params` thread, channel and author; `_agent_id`; `target_agent_id`; `intent_id`), which are the agent's own input, not model output: a fabricated id cannot coincide with them. (2) Record the exact request text in COMPOSE's result: exact, but it grounds the ANALYZE brief (model output) and changes a result contract that every chain test builds by hand; rejected. (3) Keep the old source and add sections: keeps the analysis laundering hole; rejected. **The check cannot exempt an id the agent was not given:** every grounded run comes from the world text or the intent's ids. **World text holds no output of this chain's model calls, not even echoed back by a retrieval** (Amendment A1, round 1 M1 finding 1): AD-1347's lookup is dispatched with the reference ANALYZE chose, and its not_found and invalid_ref texts repeat that reference (invalid_ref adds the example id `51d91a7d`), so `composer_world_text` keeps the lookup section only when `_ward_room_lookup_outcome` is a record outcome (found; ambiguous, whose reference starts every listed id); COMPOSE's own prompt still shows the text. Earlier model output that world sections quote (the thread's previous replies, the agent's own reflections in its memories) is outside this chain's calls and still grounds (R5). The system prompt is not a source: it is standing orders, skills and the crew roster by callsign (`cognitive_agent.py:3001-3046`), with no entity ids. Collection: `shown_hex_runs` reduces the given text to its maximal runs of 6+ hex characters, and a cited id is grounded when it occurs inside a run, which is exactly the old `id in text` test restricted to hex. **Pattern:** `\b(?=[0-9]*[a-f])[0-9a-f]{6,}\b` (at least one letter a-f; a pure-decimal number is not an identifier, accepting that the 2.3% of 8-hex segments that are all digits are no longer checked). **Counting:** distinct ids, threshold still 2. **Regression fixture:** real cited ids and their real rows from the live `ward_room.db`, written by the orchestrator (section 6), each row's id placed where a production renderer shows that kind. It is a placement, not a replay: the live prompts were not retained (`journal` keeps hashes only).

**D2, the re-measure.** A true replay of the 309 cases is impossible: neither the cognitive journal nor `chain_traces` keeps the rendered prompt. So: (a) **at build time**, the orchestrator applies the new pattern and distinct counting to the logged ids of the 309 cases with `bf204_real.py`'s parser and records on #1639 how many no longer reach the threshold, counting only cases whose logged `n` equals the number of ids logged (the line printed at most 3); (b) **prospectively**, after the merged build has produced at least 100 `BF-204: Grounding check failed` lines (or 7 days of vessel time, whichever comes first), the orchestrator runs the `bf204_real.py` method over the new lines, read-only against `%LOCALAPPDATA%\ProbOS\data\ward_room.db` (immutable), and records on #1639: the total, the all-real share (the false-positive rate), the split by `path=` (chain, single_call_fallback), and for every all-real case which section, if any, gave the id. An all-real case is a finding: either a renderer outside `composer_world_text` or an id the agent took from its own ANALYZE output (D1 excludes it by design). The fixture places every row through a production renderer (Amendment A1: 18 post rows through QUERY `thread_metadata` and the router's thread line, 3 channel rows through QUERY `unread_counts`; 0 of the 8 cases could not be placed); which renderer the live agents actually saw is what (b) measures. The new line names up to 8 ids and the path, so the probe's parser needs that format (section 7.3). **#1639 stays open until (b) is recorded**, and BF-921's rule keeps `confabulation_detected` penalty-free until then.

**D3, the fallback gate (item 2). AD-632a's fallback was not designed as an ungated path; it degrades to the pre-chain single call, which predates EVALUATE.** It runs **the deterministic checks only, not the LLM judge.** Reasons: the fallback runs when the model is already failing (3,322 triage failures), so a second model call mostly fails too and adds load at the worst moment; the judge's repeatability is unmeasured (AD-1350, #1637); BF-204's invariant covers the deterministic checks only (the judge is already bypassed for Captain, mention, DM, boot camp and low trust, `evaluate.py:552-626`). **Scope:** every single call that follows a chain which returned no decision for a chain intent (`ward_room_notification`, `proactive_think`): the AD-643a routed chain (triage failure, chain failure, a triage without communication actions, a missing chain) and the AD-632f external chain when its intent is a chain intent. Each such reply is the post the chain would have gated; a single call for any other intent (a DM, a Captain's direct request) is not gated. **Grounding on the fallback:** what the answering call was sent: the request's system prompt and user prompt and the AD-835 per-tier suffix that the attempt which answered appended to the system message after the request was built (`LLMResponse.applied_system_suffix`, set by `_call_openai` and kept on cache replays; a failed attempt's suffix never grounds), plus the intent's ids (Amendment A1, round 1 M2 finding 1). That text holds no output of this call; like the chain's world text it can quote earlier replies (the conversation, the agent's own previous posts), which D1 accepts (round 1 M2 finding 2). **Seam test:** a real `decide()` on a `ward_room_notification` with the real AD-643a routing, a triage executor that raises `SubTaskError`, the real fallback flag and `_decide_via_llm`, and a model client that answers once; a reply citing two invented ids is suppressed with `path=single_call_fallback`, and a reply citing given ids is posted.

**D4, the log lines (item 3).** BF-206: `BF-206: Chain output suppressed for <agent_type> <callsign> (<agent_id>) — Evaluate recommended suppress (<reason>)` (the reason stays last, in parentheses). BF-204: `BF-204: Grounding check failed for <agent_type> (agent_id=<id>, callsign=<c>, path=<p>) — <n> ungrounded hex IDs: [<up to 8>]` (the list stays last). BF-191 gains the same fields. Fallback: `BF-922: Single-call fallback output suppressed for <agent_type> <callsign> (<agent_id>) — deterministic check (<reason>)`.

**D5, live premises.** None blocks the build. Two read-only tasks for the orchestrator: write the fixture (section 6) before M1, and the re-measure (D2). Neither needs the Captain.

## 4. Interaction with the queue

BF-921 (#1636) builds first. In the suppression block of `_execute_sub_task_chain` (`cognitive_agent.py:5993-6029` on `cb190f32`) this prompt owns **only** `:6001-6005` (`rejection = ...` as context, and the `logger.info` statement); BF-921 owns `:6006-6018`. The SEARCH texts are disjoint and §7.7 pair 4 applies unchanged on either side of BF-921. Every other pair here is in code BF-921 does not touch (`decide()`, `_decide_via_llm`, the imports, `_CHAIN_ELIGIBLE_INTENTS`, `evaluate.py`, `compose.py`).

## 5. Consumers of every value this changes

- EVALUATE's result dict for BF-191/BF-204 is unchanged in keys and values (`OutputRejection.as_evaluate_result`); the BF-206 block reads `recommendation` and `rejection_reason` (`cognitive_agent.py:5999-6001`).
- `composer_world_text`: EVALUATE only. `_build_user_prompt` is unchanged; COMPOSE's prompt is unchanged.
- `_query_ward_room_lookup`'s result gains `ward_room_lookup_outcome` whenever a lookup ran (A1). Its readers: `QueryHandler` (merges it, `query.py:552-556`), `_maybe_dispatch_ward_room_lookup` (`cognitive_agent.py:5795-5800`; the lookup chain's results are local to it) and `tests/test_ad1347_s4_chain_lookup.py` (`:141`, `:154`, `:159` compare the whole dict: updated in section 7.4c; `:148`, `:151`, no ref, unchanged). `_ward_room_lookup_outcome` is written by the dispatch only with the text and read by `composer_world_text` only; COMPOSE renders neither key, so AD-1347 S4's compose assertions (`:204-206`, `:248-251`) are unchanged.
- `LLMResponse.applied_system_suffix` (A1, default `""`): set by `_call_openai`, copied by both cache replays, read by `_gate_fallback_output`. `LLMResponse` is built only in `llm_client.py`; `dataclasses.replace` keeps the field; the one `asdict` consumer, `tests/test_ad1325_boundaries.py:232`, compares exact base bytes and excludes it (section 7.12).
- The grounding change in EVALUATE: tests that drive `EvaluateHandler` (12 files, section 6). Those that ground ids through `context["context"]` or BF-233's params keep passing (both are still sources); `tests/test_bf204_grounding.py` and `tests/test_bf233_grounding_false_positives.py` were read for this (neither grounds through the analysis nor cites only pure-decimal ids). No test asserts the old log texts (section 11).
- The fallback's suppressed decision has the BF-206 shape (`llm_output` `[NO_RESPONSE]`, `_suppressed`, `_suppression_reason`); `act()` treats `[NO_RESPONSE]` as no post, as for a chain suppression.
- `CHAIN_FALLBACK_KEY` (`"_chain_fallback"`): set and popped by `decide()`, read by `_decide_via_llm`. It is not in `_CACHE_KEY_FIELDS` (`cognitive_agent.py:12712`), and nothing renders arbitrary observation keys (section 12).
- The `CONFABULATION_SUPPRESSED` event with `path="single_call_fallback"`: the Counselor records it (BF-921).

## 6. Milestones and tests

**Before M1, the orchestrator writes `tests/fixtures/bf922_live_grounding_cases.json`** with its extended probe, read-only, opening `%LOCALAPPDATA%\ProbOS\data\ward_room.db` with `mode=ro&immutable=1` (never `d:\ProbOS\data`). Contents: the 8 cases of the stratified sample in `notes-bf922-live-cases.txt` (every 27th of the 216 all-real cases) under `"cases"`, each with every logged id's resolved row and full ids; and under `"pattern_cases"` the `systems_analyst` case of 2026-10-22 13:05:30 (`["5999983","5999983"]`), the other 2 decimal-only cases and 2 of the 12 duplicate-only cases, taking only cases whose logged `n` equals the number of ids logged. Bodies: at most 80 characters, and `""` for any body that quotes the Captain or names a file path, URL or credential (bodies do not affect grounding). Schema:

```json
{
  "source": "BF-922 (#1639): live BF-204 cases from probos.log*, ids resolved read-only against ward_room.db; generated <date> by <probe sha256>",
  "cases": [
    {"logged_at": "2026-08-14 04:58:27", "agent_type": "builder", "n": 3,
     "cited": ["22aa3dd9b81c", "b090ebe5", "05b2bd92121b"],
     "rows": [
       {"cited": "22aa3dd9b81c", "kind": "post", "id": "<full post uuid>", "thread_id": "<full thread uuid>",
        "channel_name": "<channel name>", "author_callsign": "Reed", "body": "<= 80 chars"},
       {"cited": "...", "kind": "thread", "id": "<full thread uuid>", "channel_name": "<channel name>"},
       {"cited": "...", "kind": "channel", "id": "<full channel uuid>", "channel_name": "dm-diagnost-patholog"}
     ]}
  ],
  "pattern_cases": [
    {"logged_at": "2026-10-22 13:05:30", "agent_type": "systems_analyst", "n": 2, "cited": ["5999983", "5999983"]}
  ]
}
```

A Builder who finds the fixture missing stops (hard stop) and reports it.

**M1 (HIGH), §7.1 to §7.4c.** Commit "BF-922 M1: BF-204 grounds on what COMPOSE was given; pure-decimal numbers and repeats do not count; a failed lookup's echo grounds nothing". Before editing, grep the pins: `grep -rn "BF-204\|BF-233\|confabulation_detected\|Grounding check failed" tests/` and (A1) `grep -rn "ward_room_lookup" tests/`. Focused check (15 files):

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf922_output_grounding.py tests/test_bf204_grounding.py tests/test_bf233_grounding_false_positives.py tests/test_ad632e_evaluate_reflect.py tests/test_ad638_boot_camp.py tests/test_ad639_chain_tuning.py tests/test_ad645b_evaluate_brief_alignment.py tests/test_bf190_bf191_route_evaluate.py tests/test_bf184_evaluate_social_bypass.py tests/test_bf187_bf188_dm_captain_delivery.py tests/test_bf901_s2_journal_token_provenance.py tests/test_combo_a_ad655_contrastive.py tests/test_combo_a_ad656_dept_profiles.py tests/test_ad529_contagion_firewall.py tests/test_ad1347_s4_chain_lookup.py -n 0 -q
```

**Rule for a focused failure in an existing test:** if a test fails because it relied on the ANALYZE result as a grounding source, on a pure-decimal or repeated id counting toward the threshold, or on an id that its context never gives the composer, it pinned the defect: update it so the id is given where COMPOSE renders it (or the reply cites distinct hex ids), keep its name, and say why in one inline comment citing BF-922. Any other failure is a hard stop for the Architect.

**M2 (HIGH), §7.5 to §7.12.** Commit "BF-922 M2: the single-call fallback runs the deterministic output checks on what the answering attempt was sent; the BF-206 line names the agent". Before editing, grep the pins: `grep -rn "AD-632a\|AD-643a\|_decide_via_llm\|Chain output suppressed" tests/` and (A1) `grep -rn "asdict(response)\|system_prompt_suffix\|_cache_key(" tests/`. Focused check (18 files):

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf922_fallback_gate.py tests/test_bf922_output_grounding.py tests/test_bf206_confab_feedback.py tests/test_bf921_counselor_event_delivery.py tests/test_ad632f_activation_triggers.py tests/test_ad632a_sub_task_foundation.py tests/test_bf688_chain_priority_inheritance.py tests/test_bf901_s2_journal_token_provenance.py tests/test_ad633_predictive_branching.py tests/test_ad573_memory_budget.py tests/test_ad492_cognitive_correlation_ids.py tests/test_graduated_compilation.py tests/test_ad835_tier_adaptation.py tests/test_ad1325_boundaries.py tests/test_ad1327_verifier_tier.py tests/test_bf612_empty_content_retry.py tests/test_bf674_llm_endpoint_cooldown.py tests/test_ad1324_router_floor.py -n 0 -q
```

**The broad gate is run once for the batch by the main session, not by the Builder.**

## 7. The contract

### 7.1 New file: `src/probos/cognitive/output_grounding.py` (M1)

```python
"""BF-922 (#1639): the deterministic output checks, shared by the chain's EVALUATE and the single-call fallback.

BF-191 rejects raw intent JSON. BF-204 rejects a reply that cites at least two distinct hex
identifiers that were not in what the replying call was given from outside the model's own
output: on the chain, the world sections of the COMPOSE prompt
(``sub_tasks.compose.composer_world_text``; a failed Ward Room lookup's echo of the reference
ANALYZE chose is not one); on the single-call fallback, the text that call sent (the request's
system prompt and user prompt, and any per-tier suffix the answering attempt appended); on
both, the intent's own ids (BF-233, :func:`intent_entity_ids`).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: A cited identifier: a whole word of six or more hex characters with at least one letter a-f.
#: Pure-decimal numbers (counts, timestamps, ports) are not identifiers (BF-922).
_CITED_ID = re.compile(r"\b(?=[0-9]*[a-f])[0-9a-f]{6,}\b")

#: A run of six or more hex characters anywhere in given text. An id cited inside a run was
#: given, exactly as ``id in text`` held for BF-204 before BF-922.
_GIVEN_RUN = re.compile(r"[0-9a-f]{6,}")

#: BF-204's threshold, counted over distinct ids (BF-922).
MIN_UNGROUNDED_IDS = 2

#: How many ungrounded ids the BF-204 log line names (it named 3 before BF-922).
LOGGED_UNGROUNDED_IDS = 8

REJECTION_RAW_JSON = "raw_json_output"
REJECTION_UNGROUNDED = "confabulation_detected"

#: The gates, as the log lines and the CONFABULATION_SUPPRESSED payload name them.
PATH_CHAIN = "chain"
PATH_FALLBACK = "single_call_fallback"


@dataclass(frozen=True)
class OutputRejection:
    """Why a deterministic check rejected an output."""

    reason: str
    criteria: dict[str, Any]
    ungrounded: tuple[str, ...] = ()

    def as_evaluate_result(self) -> dict[str, Any]:
        """The EVALUATE result BF-191 and BF-204 have always returned."""
        return {
            "pass": False,
            "score": 0.0,
            "criteria": dict(self.criteria),
            "recommendation": "suppress",
            "rejection_reason": self.reason,
        }


def shown_hex_runs(*texts: str) -> tuple[str, ...]:
    """The distinct lowercase runs of six or more hex characters in ``texts``, in order."""
    runs: dict[str, None] = {}
    for text in texts:
        for run in _GIVEN_RUN.findall((text or "").lower()):
            runs[run] = None
    return tuple(runs)


def cited_ids(output: str) -> tuple[str, ...]:
    """The distinct identifiers ``output`` cites, lowercase, in order of first citation."""
    return tuple(dict.fromkeys(_CITED_ID.findall((output or "").lower())))


def ungrounded_ids(output: str, shown: Iterable[str]) -> tuple[str, ...]:
    """The identifiers ``output`` cites that occur in no given hex run."""
    shown_text = " ".join(shown)
    return tuple(cited for cited in cited_ids(output) if cited not in shown_text)


def intent_entity_ids(context: dict[str, Any]) -> tuple[str, ...]:
    """BF-233's ids: the intent's thread, channel and author, the agent, its target and the intent."""
    ids: list[str] = []
    params = context.get("params", {})
    if isinstance(params, dict):
        for key in ("thread_id", "channel_id", "author_id"):
            value = params.get(key, "")
            if value:
                ids.append(str(value))
    for key in ("_agent_id", "target_agent_id", "intent_id"):
        value = context.get(key)
        if value:
            ids.append(str(value))
    return tuple(ids)


def is_raw_intent_json(output: str) -> bool:
    """BF-191: the output is raw intent JSON, not natural language."""
    stripped = (output or "").strip()
    return stripped.startswith("{") and ('"intents"' in stripped[:200] or '"intent"' in stripped[:200])


def deterministic_rejection(output: str, shown: Iterable[str]) -> OutputRejection | None:
    """BF-191, then BF-204. ``None`` when ``output`` passes both."""
    if is_raw_intent_json(output):
        return OutputRejection(
            reason=REJECTION_RAW_JSON,
            criteria={"format": {"pass": False, "reason": "Raw JSON instead of natural language"}},
        )
    ungrounded = ungrounded_ids(output, shown)
    if len(ungrounded) >= MIN_UNGROUNDED_IDS:
        return OutputRejection(
            reason=REJECTION_UNGROUNDED,
            criteria={
                "grounding": {"pass": False, "reason": f"Ungrounded identifiers: {list(ungrounded[:3])}"},
            },
            ungrounded=ungrounded,
        )
    return None


def log_rejection(
    rejection: OutputRejection,
    output: str,
    *,
    agent_type: str,
    agent_id: str,
    callsign: str,
    path: str,
) -> None:
    """The BF-191 and BF-204 lines, naming the agent and the gate (BF-922)."""
    if rejection.reason == REJECTION_RAW_JSON:
        logger.warning(
            "BF-191: Evaluate rejected raw intent JSON from %s (agent_id=%s, callsign=%s, path=%s; %d chars)",
            agent_type, agent_id, callsign, path, len(output or ""),
        )
        return
    logger.warning(
        "BF-204: Grounding check failed for %s (agent_id=%s, callsign=%s, path=%s) — %d ungrounded hex IDs: %s",
        agent_type, agent_id, callsign, path,
        len(rejection.ungrounded), list(rejection.ungrounded[:LOGGED_UNGROUNDED_IDS]),
    )
```

### 7.2 `src/probos/cognitive/sub_tasks/compose.py` (M1)

SEARCH:
```python
    if not parts:
        parts.append("Compose a response based on your current knowledge and standing orders.")

    return "\n\n".join(parts)
```
REPLACE:
```python
    if not parts:
        parts.append("Compose a response based on your current knowledge and standing orders.")

    return "\n\n".join(parts)


def composer_world_text(context: dict, prior_results: list[SubTaskResult]) -> str:
    """BF-922 (#1639): the user prompt COMPOSE renders, without the ANALYZE result.

    What the composing call is given from outside the chain's own model calls: the
    thread, QUERY data, memories, lookups and situation sections. EVALUATE's BF-204
    check grounds on it, so an id an earlier model step invented is not grounded by
    having been repeated into the brief. The AD-1347 lookup's text counts only for a
    record outcome (found; ambiguous, whose reference starts every listed id): a failed
    lookup's text repeats the reference ANALYZE chose (and, for an invalid one, an
    example id), which is model output. COMPOSE still shows that text; it grounds
    nothing. The system prompt (standing orders, skills, the crew roster by callsign)
    carries no entity ids and is not included.
    """
    from probos.ward_room.lookup import LOOKUP_AMBIGUOUS, LOOKUP_FOUND  # at use, as query.py imports it

    world = [pr for pr in prior_results if pr.sub_task_type != SubTaskType.ANALYZE]
    if context.get("_ward_room_lookup_outcome") not in (LOOKUP_FOUND, LOOKUP_AMBIGUOUS):
        context = {key: value for key, value in context.items() if key != "_ward_room_lookup_context"}
    return _build_user_prompt(context, world)
```

### 7.3 `src/probos/cognitive/sub_tasks/evaluate.py` (M1)

Pair 1 (imports; `re` has no other use in the file):

SEARCH:
```python
import json
import logging
import re
import time
from typing import Any

from probos.cognitive.sub_task import (
    SubTaskResult,
    SubTaskSpec,
    SubTaskType,
    resolve_chain_priority,
)
from probos.types import LLMRequest
```
REPLACE:
```python
import json
import logging
import time
from typing import Any

from probos.cognitive.output_grounding import (
    PATH_CHAIN,
    deterministic_rejection,
    intent_entity_ids,
    log_rejection,
    shown_hex_runs,
)
from probos.cognitive.sub_task import (
    SubTaskResult,
    SubTaskSpec,
    SubTaskType,
    resolve_chain_priority,
)
from probos.cognitive.sub_tasks.compose import composer_world_text
from probos.types import LLMRequest
```

Pair 2 (BF-191 and BF-204):

SEARCH:
```python
        # === SAFETY CHECKS (always run, 0 tokens) ===

        # BF-191: Deterministic JSON rejection — compose output must be natural language
        compose_output = _get_compose_output(prior_results)
        stripped = compose_output.strip()
        if stripped.startswith("{") and ('"intents"' in stripped[:200] or '"intent"' in stripped[:200]):
            logger.warning(
                "BF-191: Evaluate rejected raw intent JSON from %s (%d chars)",
                context.get("_agent_type", "unknown"),
                len(compose_output),
            )
            return SubTaskResult(
                sub_task_type=SubTaskType.EVALUATE,
                name=spec.name,
                result={
                    "pass": False,
                    "score": 0.0,
                    "criteria": {"format": {"pass": False, "reason": "Raw JSON instead of natural language"}},
                    "recommendation": "suppress",
                    "rejection_reason": "raw_json_output",
                },
                tokens_used=0,
                duration_ms=int((time.monotonic() - start) * 1000),
                success=True,
                tier_used="",
            )

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
        if len(_ungrounded_ids) >= 2:
            logger.warning(
                "BF-204: Grounding check failed for %s — %d ungrounded hex IDs: %s",
                context.get("_agent_type", "unknown"),
                len(_ungrounded_ids),
                _ungrounded_ids[:3],
            )
            return SubTaskResult(
                sub_task_type=SubTaskType.EVALUATE,
                name=spec.name,
                result={
                    "pass": False,
                    "score": 0.0,
                    "criteria": {
                        "grounding": {
                            "pass": False,
                            "reason": f"Ungrounded identifiers: {_ungrounded_ids[:3]}",
                        },
                    },
                    "recommendation": "suppress",
                    "rejection_reason": "confabulation_detected",
                },
                tokens_used=0,
                duration_ms=int((time.monotonic() - start) * 1000),
                success=True,
                tier_used="",
            )
```
REPLACE:
```python
        # === SAFETY CHECKS (always run, 0 tokens) ===

        # BF-191 + BF-204, shared with the single-call fallback (BF-922, #1639).
        # Runs at ALL trust bands, even social obligation. Safety > obligation.
        # BF-204 grounds on what COMPOSE was given from outside the chain's model
        # calls (not the ANALYZE result: an id an earlier step invented is not
        # grounded by being repeated) and on the intent's own ids (BF-233).
        compose_output = _get_compose_output(prior_results)
        _shown = shown_hex_runs(composer_world_text(context, prior_results), *intent_entity_ids(context))
        rejection = deterministic_rejection(compose_output, _shown)
        if rejection is not None:
            log_rejection(
                rejection,
                compose_output,
                agent_type=context.get("_agent_type", "unknown"),
                agent_id=context.get("_agent_id", ""),
                callsign=context.get("_callsign", ""),
                path=PATH_CHAIN,
            )
            return SubTaskResult(
                sub_task_type=SubTaskType.EVALUATE,
                name=spec.name,
                result=rejection.as_evaluate_result(),
                tokens_used=0,
                duration_ms=int((time.monotonic() - start) * 1000),
                success=True,
                tier_used="",
            )
```

**Probe note (for the orchestrator, not the Builder):** the BF-204 line now reads `BF-204: Grounding check failed for <agent_type> (agent_id=..., callsign=..., path=...) — <n> ungrounded hex IDs: [...]`, with up to 8 ids. `bf204_real.py`'s parser must accept both forms before D2's re-measure.

### 7.4 New file: `tests/test_bf922_output_grounding.py` (M1)

```python
"""BF-922 (#1639) M1: BF-204 grounds on what the composing call was given; pure-decimal numbers and repeats do not count.

The contract is ``prompts/bf-922-output-gate-grounding-and-fallback.md``. The live cases come from
``tests/fixtures/bf922_live_grounding_cases.json``, written by the orchestrator read-only from the live vessel: real
cited ids and their real Ward Room rows. Each row's id is placed through a production renderer that shows that kind:
the real QUERY step and COMPOSE's real renderer over ``thread_metadata`` (full post and thread ids, the
ward_room_notification chain) or ``unread_counts`` (channel ids, the proactive_think chain), and a post's first 8 hex in
the router's thread line (ward_room_router.py). It is a placement, not a replay: the live prompts were not retained.

Stand-ins, named: EVALUATE's model client (approves), so a reply that passes the deterministic checks reaches the judge;
``_WardRoomReads``, the two WardRoomService reads behind those QUERY operations, answering with the case's rows in the
production shapes (ward_room/threads.py ``get_thread``, ward_room/messages.py ``get_unread_counts``). The lookup tests
run a real ``WardRoomService`` in ``tmp_path``, the real AD-1347 dispatch and the real chain with real handlers; their
stand-ins are the model client (``_TwoCalls``: ANALYZE's JSON, then COMPOSE's reply) and the runtime surface
(``_ChainRuntime``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.output_grounding import (
    MIN_UNGROUNDED_IDS,
    REJECTION_UNGROUNDED,
    cited_ids,
    deterministic_rejection,
    intent_entity_ids,
    shown_hex_runs,
    ungrounded_ids,
)
from probos.cognitive.sub_task import SubTaskExecutor, SubTaskResult, SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks import AnalyzeHandler, ComposeHandler, QueryHandler, ReflectHandler
from probos.cognitive.sub_tasks.compose import _build_user_prompt, composer_world_text
from probos.cognitive.sub_tasks.evaluate import EvaluateHandler
from probos.config import SystemConfig
from probos.config_models.crew import WardRoomConfig
from probos.types import LLMResponse
from probos.ward_room.service import WardRoomService

FIXTURE = Path(__file__).parent / "fixtures" / "bf922_live_grounding_cases.json"
LIVE: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
INVENTED = "Per post 7f3a9c2e and thread b81d04aa, the backlog cleared."
ANALYSIS_ONLY = "Post deadc0de and thread facefeed matter."


def _handler() -> EvaluateHandler:
    response = MagicMock()
    response.content = '{"pass": true, "score": 0.8, "criteria": {}, "recommendation": "approve"}'
    response.tokens_used = 50
    response.tier = "fast"
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=response)
    return EvaluateHandler(llm_client=llm)


def _spec() -> SubTaskSpec:
    return SubTaskSpec(
        sub_task_type=SubTaskType.EVALUATE, name="evaluate-reply", prompt_template="ward_room_quality", tier="fast",
    )


def _compose(output: str) -> SubTaskResult:
    return SubTaskResult(sub_task_type=SubTaskType.COMPOSE, name="compose-reply", result={"output": output})


def _analysis(situation: str) -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name="analyze-reply",
        result={"composition_brief": {"situation": situation}},
    )


def _context(**sections: Any) -> dict[str, Any]:
    context: dict[str, Any] = {
        "_agent_type": "science_officer",
        "_agent_id": "agent-7",
        "_callsign": "Kira",
        "_department": "science",
        "_chain_trust_band": "mid",
    }
    context.update(sections)
    return context


class _WardRoomReads:
    """The two WardRoomService reads the chains' QUERY steps make, answering with one live case's real rows."""

    def __init__(self, case: dict[str, Any]) -> None:
        self._rows = case["rows"]

    async def get_thread(self, thread_id: str, **_kwargs: Any) -> dict[str, Any]:
        posts = [
            {"id": row["id"], "thread_id": thread_id, "author_callsign": row["author_callsign"],
             "body": row["body"], "children": []}
            for row in self._rows if row["kind"] == "post"
        ]
        thread = {"id": thread_id, "channel_name": self._rows[0]["channel_name"], "title": "live case"}
        return {"thread": thread, "posts": posts, "total_post_count": len(posts)}

    async def get_unread_counts(self, agent_id: str) -> dict[str, int]:
        return {row["id"]: 1 for row in self._rows if row["kind"] == "channel"}


class _QueryRuntime:
    """The one runtime attribute the two QUERY operations read."""

    def __init__(self, ward_room: _WardRoomReads) -> None:
        self.ward_room = ward_room


async def _placed(case: dict[str, Any]) -> tuple[dict[str, Any], list[SubTaskResult]]:
    """The case's ids where a production renderer shows that kind, through the real QUERY step.

    Posts and threads: the ward_room_notification chain's QUERY ``thread_metadata`` and the router's thread line.
    Channels: the proactive_think chain's QUERY ``unread_counts``. The spec names only the operation the stand-in
    answers (a missing service fails the step, and COMPOSE then renders no Prior Data). One case is one chain, so a
    case that mixed channels with posts, or posts from two threads, is not placeable and fails here.
    """
    kinds = {row["kind"] for row in case["rows"]}
    if "channel" in kinds:
        assert kinds == {"channel"}, f"{_case_id(case)}: channels with posts are not one chain's QUERY"
        context = _context(context="Thread: live case")
        spec = SubTaskSpec(sub_task_type=SubTaskType.QUERY, name="query-situation", context_keys=("unread_counts",))
    else:
        threads = {row["thread_id"] if row["kind"] == "post" else row["id"] for row in case["rows"]}
        assert len(threads) == 1, f"{_case_id(case)}: posts from {len(threads)} threads are not one chain's QUERY"
        thread_id = threads.pop()
        lines = [
            f"[{row['id'][:8]}] {row['author_callsign']}: {row['body']}"
            for row in case["rows"] if row["kind"] == "post"
        ]
        context = _context(context="Thread: live case\n" + "\n".join(lines), params={"thread_id": thread_id})
        spec = SubTaskSpec(
            sub_task_type=SubTaskType.QUERY, name="query-thread-context", context_keys=("thread_metadata",),
        )
    query = await QueryHandler(_QueryRuntime(_WardRoomReads(case)))(spec, context, [])
    assert query.success, query.error
    return context, [query]


def _reply(case: dict[str, Any]) -> str:
    return "Building on " + ", ".join(case["cited"]) + "."


def _case_id(case: dict[str, Any]) -> str:
    return f"{case['logged_at']}-{case['agent_type']}"


# --- the pattern and the count ---------------------------------------------------------------------


def test_pure_decimal_numbers_are_not_cited_ids() -> None:
    assert cited_ids("Latency 5999983 ms over 123456 samples; channel 80593080; post 8a66bf93.") == ("8a66bf93",)


def test_a_repeated_id_counts_once() -> None:
    assert ungrounded_ids("8a66bf93, again 8A66BF93", ()) == ("8a66bf93",)
    assert deterministic_rejection("8a66bf93, again 8a66bf93", ()) is None


def test_one_ungrounded_id_is_below_the_threshold() -> None:
    assert MIN_UNGROUNDED_IDS == 2
    assert deterministic_rejection("Only 7f3a9c2e here.", ()) is None


def test_two_invented_ids_are_still_suppressed() -> None:
    rejection = deterministic_rejection(INVENTED, shown_hex_runs("A thread with no identifiers at all."))

    assert rejection is not None
    assert rejection.reason == REJECTION_UNGROUNDED
    assert rejection.ungrounded == ("7f3a9c2e", "b81d04aa")


def test_an_id_inside_a_given_run_is_grounded() -> None:
    shown = shown_hex_runs("Post b090ebe5-3f40-4c1d-9e2a-05b2bd92121b in thread b1fba6b3-d991-4f00-8a1b-2c3d4e5f6a7b")

    assert ungrounded_ids("b090ebe5, 05b2bd92121b and b090eb", shown) == ()


def test_raw_intent_json_is_rejected_before_grounding() -> None:
    rejection = deterministic_rejection('{"intents": [{"intent": "ward_room_post"}]}', ())

    assert rejection is not None and rejection.reason == "raw_json_output"


def test_the_bf233_intent_ids_are_given() -> None:
    context = {
        "params": {"thread_id": "A6EC8B06-1234", "channel_id": "", "author_id": "captain"},
        "_agent_id": "78a87214-aaaa",
        "target_agent_id": None,
        "intent_id": "i-1",
    }

    assert intent_entity_ids(context) == ("A6EC8B06-1234", "captain", "78a87214-aaaa", "i-1")
    assert intent_entity_ids({"params": "not a dict"}) == ()


# --- the source: what COMPOSE was given ------------------------------------------------------------


def test_the_world_text_leaves_out_the_analysis() -> None:
    text = composer_world_text(
        {"context": "Thread: Readiness\n[c71f7ab2] Meridian: nominal"}, [_analysis(ANALYSIS_ONLY)],
    )

    assert "c71f7ab2" in text
    assert "deadc0de" not in text and "facefeed" not in text


@pytest.mark.asyncio
async def test_an_id_only_in_the_analysis_is_not_grounded() -> None:
    result = await _handler()(_spec(), _context(context="Thread: Readiness"), [_analysis(ANALYSIS_ONLY), _compose(ANALYSIS_ONLY)])

    assert result.result["rejection_reason"] == "confabulation_detected"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "section",
    ["context", "_formatted_memories", "_ward_room_lookup_context", "_ward_room_activity", "_oracle_context"],
)
async def test_an_id_in_any_world_section_is_grounded(section: str) -> None:
    sections: dict[str, Any] = {section: "Post 7f3a9c2e in thread b81d04aa"}
    if section == "_ward_room_lookup_context":
        sections["_ward_room_lookup_outcome"] = "found"  # BF-922 A1: a lookup's text grounds for a record only
    result = await _handler()(_spec(), _context(**sections), [_compose(INVENTED)])

    assert result.success and result.result["recommendation"] == "approve"


@pytest.mark.asyncio
async def test_the_bf204_log_line_names_the_agent_and_the_gate(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.output_grounding"):
        await _handler()(_spec(), _context(context="No identifiers here."), [_compose(INVENTED)])

    assert (
        "BF-204: Grounding check failed for science_officer (agent_id=agent-7, callsign=Kira, path=chain)"
        " — 2 ungrounded hex IDs: ['7f3a9c2e', 'b81d04aa']"
    ) in caplog.text


# --- the live cases ---------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("case", LIVE["cases"], ids=_case_id)
async def test_a_live_false_positive_is_grounded_when_given(case: dict[str, Any]) -> None:
    """Every id the live reply cites is in what the real renderers gave the composer, and the judge approves it."""
    context, prior = await _placed(case)
    reply = _reply(case)

    assert cited_ids(reply), "premise: the live reply cites ids"
    assert ungrounded_ids(reply, shown_hex_runs(composer_world_text(context, prior), *intent_entity_ids(context))) == ()
    result = await _handler()(_spec(), context, [*prior, _compose(reply)])

    assert result.success and result.result["recommendation"] == "approve"


@pytest.mark.parametrize(
    "case",
    [c for c in LIVE["cases"] if len(cited_ids(" ".join(c["cited"]))) >= MIN_UNGROUNDED_IDS],
    ids=_case_id,
)
def test_the_same_live_reply_is_flagged_when_not_given(case: dict[str, Any]) -> None:
    """The live cases exercise the grounding source, not only the pattern."""
    assert deterministic_rejection(_reply(case), ()) is not None


@pytest.mark.parametrize("case", LIVE["pattern_cases"], ids=_case_id)
def test_a_live_decimal_or_repeat_case_is_not_suppressed(case: dict[str, Any]) -> None:
    assert deterministic_rejection(_reply(case), ()) is None


def test_the_fixture_holds_real_cases() -> None:
    assert len(LIVE["cases"]) >= 8
    assert any(row["kind"] == "channel" for case in LIVE["cases"] for row in case["rows"])
    assert any(case["cited"] == ["5999983", "5999983"] for case in LIVE["pattern_cases"])
    for case in LIVE["cases"]:  # BF-922 A1: each case is one chain's QUERY, so every case is placeable
        kinds = {row["kind"] for row in case["rows"]}
        assert kinds == {"channel"} or "channel" not in kinds, _case_id(case)


# --- the AD-1347 lookup: a record grounds, a failed lookup's echo does not (BF-922 A1) -----------------

LOOKUP_AGENT = "agent-7"


@pytest.mark.parametrize(
    ("outcome", "grounds"),
    [
        ("found", True), ("ambiguous", True), ("not_found", False), ("invalid_ref", False),
        ("refused", False), ("unavailable", False), (None, False),
    ],
    ids=["found", "ambiguous", "not_found", "invalid_ref", "refused", "unavailable", "no_outcome"],
)
def test_the_lookup_text_grounds_only_for_a_record_outcome(outcome: str | None, grounds: bool) -> None:
    context: dict[str, Any] = {"_ward_room_lookup_context": "No Ward Room thread or post with id 7f3a9c2e."}
    if outcome is not None:
        context["_ward_room_lookup_outcome"] = outcome

    assert ("7f3a9c2e" in composer_world_text(context, [])) is grounds
    assert "7f3a9c2e" in _build_user_prompt(context, [])  # COMPOSE's own prompt is unchanged


@dataclass
class _ChainRuntime:
    """The runtime surface the real chain handlers read (as the BF-922 round-1 review's probe built it)."""

    ward_room: WardRoomService
    config: SystemConfig = field(default_factory=SystemConfig)
    events: list[tuple[Any, dict[str, Any]]] = field(default_factory=list)
    boot_camp: Any = None
    trust_network: Any = None
    cognitive_journal: Any = None
    ontology: Any = None

    def emit_event(self, event: Any, data: dict[str, Any]) -> None:
        self.events.append((event, dict(data)))


class _TwoCalls:
    """ANALYZE's JSON, then COMPOSE's reply; any further call (the judge, REFLECT) fails the test."""

    def __init__(self, reply: str) -> None:
        self._responses = [
            json.dumps({
                "contribution_assessment": "RESPOND",
                "intended_actions": ["ward_room_reply"],
                "composition_brief": {"situation": "Status request"},
            }),
            reply,
        ]
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        assert self._responses, "an unexpected model call (the judge or REFLECT)"
        self.requests.append(request)
        return LLMResponse(
            content=self._responses.pop(0), tier="fast", model="test-model",
            prompt_tokens=5, completion_tokens=5, tokens_used=10, usage_reported=True,
        )


async def _ward_room(tmp_path: Path) -> WardRoomService:
    """A started Ward Room whose lookup reads an empty archive, so a search completes."""
    ward = WardRoomService(db_path=str(tmp_path / "wr.db"))
    await ward.start()
    archive = tmp_path / "ward_room_archive"
    archive.mkdir()
    await ward.start_prune_loop(WardRoomConfig(prune_interval_seconds=3600.0), archive)
    await ward.stop_prune_loop()
    return ward


async def _chain_after_lookup(
    ward: WardRoomService, ref: str, reply: str,
) -> tuple[dict[str, Any], dict[str, Any], _TwoCalls]:
    """AD-1347's dispatch with ANALYZE's ``ref``, then the real ward_room_notification chain with real handlers."""
    runtime = _ChainRuntime(ward_room=ward)
    client = _TwoCalls(reply)
    agent = CognitiveAgent(
        agent_id=LOOKUP_AGENT, instructions="Report observed facts.", llm_client=client, runtime=runtime,
    )
    agent.agent_type = "science_officer"
    agent.callsign = "Kira"
    agent.department = "science"
    executor = SubTaskExecutor(config=runtime.config.sub_task)
    executor.register_handler(SubTaskType.QUERY, QueryHandler(runtime))
    executor.register_handler(SubTaskType.ANALYZE, AnalyzeHandler(llm_client=client, runtime=runtime))
    executor.register_handler(SubTaskType.COMPOSE, ComposeHandler(llm_client=client, runtime=runtime))
    executor.register_handler(SubTaskType.EVALUATE, EvaluateHandler(llm_client=client, runtime=runtime))
    executor.register_handler(SubTaskType.REFLECT, ReflectHandler(llm_client=client, runtime=runtime))
    agent.set_sub_task_executor(executor)
    channel = await ward.get_or_create_dm_channel(LOOKUP_AGENT, "peer", "Kira", "Peer")
    thread = await ward.create_thread(channel.id, "peer", "Status", "What is the status?", author_callsign="Peer")
    observation: dict[str, Any] = {
        "intent": "ward_room_notification",
        "intent_id": "intent-1",
        "context": "Thread: Status",
        "_agent_id": LOOKUP_AGENT,
        "params": {"thread_id": thread.id, "channel_id": channel.id, "author_id": "peer", "is_dm_channel": True},
    }
    triage = [SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE, name="analyze-thread", success=True,
        result={"intended_actions": ["ward_room_reply", "ward_room_lookup"], "ward_room_lookup_ref": ref},
    )]
    await agent._maybe_dispatch_ward_room_lookup(triage, observation)
    chain = agent._build_chain_for_intent(observation)
    assert chain is not None and executor.can_execute(chain)
    decision = await agent._execute_sub_task_chain(chain, observation)
    assert decision is not None
    return decision, observation, client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ref", "reply", "outcome", "echoed"),
    [
        ("7f3a9c2e-0000-0000-0000-b81d04aabbcc", "Per 7f3a9c2e and b81d04aabbcc, the backlog cleared.",
         "not_found", ("7f3a9c2e", "b81d04aabbcc")),
        ("7f3a9c2e b81d04aabbcc", "Per 7f3a9c2e and 51d91a7d, the backlog cleared.",
         "invalid_ref", ("7f3a9c2e", "51d91a7d")),
    ],
    ids=["not_found", "invalid_ref"],
)
async def test_a_failed_lookup_echo_does_not_ground_through_the_real_chain(
    tmp_path: Path, ref: str, reply: str, outcome: str, echoed: tuple[str, ...],
) -> None:
    """Round 1, M1 finding 1: the reference is ANALYZE's output and a failed lookup repeats it (an invalid one adds
    the example id 51d91a7d); M1 candidate 1 posted this reply. COMPOSE still sees the echo; it grounds nothing."""
    ward = await _ward_room(tmp_path)
    try:
        decision, observation, client = await _chain_after_lookup(ward, ref, reply)
    finally:
        await ward.stop()

    assert observation["_ward_room_lookup_outcome"] == outcome
    assert len(client.requests) == 2
    assert all(cited in client.requests[1].prompt for cited in echoed)  # the echo reached COMPOSE, as before
    assert decision["_suppressed"] is True
    assert decision["_suppression_reason"] == "confabulation_detected"


async def _lettered_thread(ward: WardRoomService, channel_id: str) -> Any:
    """A thread by the asking agent whose first 8 and last 12 hex both hold a letter, so both are cited ids."""
    for _ in range(20):
        thread = await ward.create_thread(
            channel_id, LOOKUP_AGENT, "Backlog", "Backlog cleared at 0300.", author_callsign="Kira",
        )
        if cited_ids(thread.id[:8]) and cited_ids(thread.id[-12:]):
            return thread
    raise AssertionError("no thread id with a letter in both cited segments in 20 tries")


@pytest.mark.asyncio
async def test_a_found_record_grounds_through_the_real_chain(tmp_path: Path) -> None:
    """The partner of the test above: a record the lookup found is world data, so a reply citing it is posted."""
    ward = await _ward_room(tmp_path)
    try:
        channel = await ward.get_or_create_dm_channel(LOOKUP_AGENT, "peer", "Kira", "Peer")
        record = await _lettered_thread(ward, channel.id)
        reply = f"Per {record.id[:8]} and {record.id[-12:]}, the backlog cleared."
        decision, observation, client = await _chain_after_lookup(ward, record.id, reply)
    finally:
        await ward.stop()

    assert observation["_ward_room_lookup_outcome"] == "found"
    assert len(client.requests) == 2
    assert not decision.get("_suppressed")
    assert decision["llm_output"] == reply
```

### 7.4a `src/probos/cognitive/sub_tasks/query.py` (M1, Amendment A1: the lookup's outcome travels with its text)

Pair 1 (docstring):

SEARCH:
```python
    never the asker. The Ward Room decides what the agent may see. Returns
    ``{"ward_room_lookup": <text>}``: empty when no id was asked for, otherwise the record
    or one line saying why there is none. Never raises, so the QUERY step stays a success.
    """
```
REPLACE:
```python
    never the asker. The Ward Room decides what the agent may see. Returns
    ``{"ward_room_lookup": <text>}``: empty when no id was asked for, otherwise the record
    or one line saying why there is none, with ``"ward_room_lookup_outcome"``, the
    ``LookupResult.outcome`` (BF-922, #1639: BF-204 grounds on the text only for a record,
    never on a failed lookup's echo of the reference). Never raises, so the QUERY step
    stays a success.
    """
```

Pair 2 (one return, with the outcome):

SEARCH:
```python
    requester = context.get("_agent_id", "")
    ward_room = getattr(runtime, "ward_room", None)
    if ward_room is None:
        return {"ward_room_lookup": render_lookup(LookupResult(LOOKUP_UNAVAILABLE, ""))}
    try:
        result = await ward_room.lookup_record(requester, ref)
    except Exception:
        logger.warning("AD-1347: ward_room_lookup failed for agent %s", requester, exc_info=True)
        result = LookupResult(LOOKUP_UNAVAILABLE, "")
    return {"ward_room_lookup": render_lookup(result)}
```
REPLACE:
```python
    requester = context.get("_agent_id", "")
    ward_room = getattr(runtime, "ward_room", None)
    if ward_room is None:
        result = LookupResult(LOOKUP_UNAVAILABLE, "")
    else:
        try:
            result = await ward_room.lookup_record(requester, ref)
        except Exception:
            logger.warning("AD-1347: ward_room_lookup failed for agent %s", requester, exc_info=True)
            result = LookupResult(LOOKUP_UNAVAILABLE, "")
    return {"ward_room_lookup": render_lookup(result), "ward_room_lookup_outcome": result.outcome}
```

### 7.4b `src/probos/cognitive/cognitive_agent.py` (M1, Amendment A1: the dispatch copies the outcome)

Pair 1 (docstring):

SEARCH:
```python
        Reads ``ward_room_lookup_ref`` from the latest successful ANALYZE result, runs a
        one-step QUERY chain (``ward_room_lookup``) and writes the text to
        ``observation["_ward_room_lookup_context"]``, which COMPOSE renders. Once per chain.
```
REPLACE:
```python
        Reads ``ward_room_lookup_ref`` from the latest successful ANALYZE result, runs a
        one-step QUERY chain (``ward_room_lookup``) and writes the text to
        ``observation["_ward_room_lookup_context"]``, which COMPOSE renders, and its typed
        outcome to ``observation["_ward_room_lookup_outcome"]`` (BF-922). Once per chain.
```

Pair 2:

SEARCH:
```python
        for r in results:
            if r.sub_task_type == SubTaskType.QUERY and r.success and r.result:
                text = r.result.get("ward_room_lookup", "")
                if isinstance(text, str) and text:
                    observation["_ward_room_lookup_context"] = text
                break
```
REPLACE:
```python
        for r in results:
            if r.sub_task_type == SubTaskType.QUERY and r.success and r.result:
                text = r.result.get("ward_room_lookup", "")
                if isinstance(text, str) and text:
                    observation["_ward_room_lookup_context"] = text
                    # BF-922 (#1639): the typed outcome travels with the text. BF-204 grounds on
                    # a found record, never on a failed lookup's echo of ANALYZE's reference.
                    outcome = r.result.get("ward_room_lookup_outcome", "")
                    observation["_ward_room_lookup_outcome"] = outcome if isinstance(outcome, str) else ""
                break
```

### 7.4c `tests/test_ad1347_s4_chain_lookup.py` (M1, Amendment A1: the result carries its outcome)

Pair 1:

SEARCH:
```python
    assert smuggled == {"ward_room_lookup": "The Ward Room lookup could not confirm who is asking, so it returned nothing."}
    assert ARCHIVED_BODY in own["ward_room_lookup"]
    assert outsider["ward_room_lookup"].startswith("No Ward Room thread or post with id ")
```
REPLACE:
```python
    # BF-922 (#1639): the typed outcome travels with the text, so BF-204 can tell a record from a failed lookup's echo.
    assert smuggled == {
        "ward_room_lookup": "The Ward Room lookup could not confirm who is asking, so it returned nothing.",
        "ward_room_lookup_outcome": "refused",
    }
    assert ARCHIVED_BODY in own["ward_room_lookup"] and own["ward_room_lookup_outcome"] == "found"
    assert outsider["ward_room_lookup"].startswith("No Ward Room thread or post with id ")
    assert outsider["ward_room_lookup_outcome"] == "not_found"
```

Pair 2:

SEARCH:
```python
    assert await _query_ward_room_lookup(
        _Runtime(None), _SPEC, {"_agent_id": FORGE, "ward_room_lookup_ref": "aa000001"},
    ) == {"ward_room_lookup": UNAVAILABLE}

    handled = await QueryHandler(_Runtime(_FailingWardRoom()))(
        _SPEC, {"_agent_id": FORGE, "ward_room_lookup_ref": "aa000001"}, [],
    )
    assert handled.success and handled.result == {"ward_room_lookup": UNAVAILABLE}
```
REPLACE:
```python
    # BF-922 (#1639): a lookup that ran carries its typed outcome; no ref (above) runs none and carries none.
    assert await _query_ward_room_lookup(
        _Runtime(None), _SPEC, {"_agent_id": FORGE, "ward_room_lookup_ref": "aa000001"},
    ) == {"ward_room_lookup": UNAVAILABLE, "ward_room_lookup_outcome": "unavailable"}

    handled = await QueryHandler(_Runtime(_FailingWardRoom()))(
        _SPEC, {"_agent_id": FORGE, "ward_room_lookup_ref": "aa000001"}, [],
    )
    assert handled.success
    assert handled.result == {"ward_room_lookup": UNAVAILABLE, "ward_room_lookup_outcome": "unavailable"}
```

Pair 3:

SEARCH:
```python
    assert observation["_ward_room_lookup_fired"] is True
    assert ARCHIVED_BODY in observation["_ward_room_lookup_context"]

    again: dict = {"_agent_id": FORGE, "_ward_room_lookup_fired": True}
```
REPLACE:
```python
    assert observation["_ward_room_lookup_fired"] is True
    assert ARCHIVED_BODY in observation["_ward_room_lookup_context"]
    assert observation["_ward_room_lookup_outcome"] == "found"  # BF-922: the outcome travels with the text

    again: dict = {"_agent_id": FORGE, "_ward_room_lookup_fired": True}
```

### 7.5 `src/probos/cognitive/cognitive_agent.py` (M2: imports and the key)

Pair 1:

SEARCH:
```python
from probos.cognitive.sub_task import CHAIN_PRIORITY_KEY  # BF-688
from probos.utils import format_duration
```
REPLACE:
```python
from probos.cognitive.output_grounding import (  # BF-922
    PATH_FALLBACK,
    deterministic_rejection,
    intent_entity_ids,
    log_rejection,
    shown_hex_runs,
)
from probos.cognitive.sub_task import CHAIN_PRIORITY_KEY  # BF-688
from probos.utils import format_duration
```

Pair 2:

SEARCH:
```python
_CHAIN_ELIGIBLE_INTENTS: frozenset[str] = frozenset({
    "ward_room_notification",
    "proactive_think",
})
```
REPLACE:
```python
_CHAIN_ELIGIBLE_INTENTS: frozenset[str] = frozenset({
    "ward_room_notification",
    "proactive_think",
})

# BF-922 (#1639): set on the observation while a single call answers for a chain
# that returned no decision for a chain intent; ``_decide_via_llm`` then runs the
# chain's deterministic output checks (BF-191, BF-204) on the reply.
CHAIN_FALLBACK_KEY = "_chain_fallback"
```

### 7.6 `src/probos/cognitive/cognitive_agent.py` (M2: `decide()` and `_decide_via_llm`)

Pair 1 (the external chain's fallback):

SEARCH:
```python
                return chain_result
            logger.info("AD-632f: Falling back to single-call for %s", self.agent_type)

        # Priority 2: intent-driven routing (AD-643a)
```
REPLACE:
```python
                return chain_result
            logger.info("AD-632f: Falling back to single-call for %s", self.agent_type)
            if observation.get("intent") in _CHAIN_ELIGIBLE_INTENTS:  # BF-922: only a chain intent's reply
                observation[CHAIN_FALLBACK_KEY] = True  # BF-922: an external chain's fallback

        # Priority 2: intent-driven routing (AD-643a)
```

Pair 2 (the routed chain's fallback, and the call):

SEARCH:
```python
                return chain_result
            # chain_result is None → fall through to _decide_via_llm()
            # Skills may already be loaded in observation from intent routing

        # --- LLM call (cache miss) ---
        decision = await self._decide_via_llm(observation)
```
REPLACE:
```python
                return chain_result
            # chain_result is None → fall through to _decide_via_llm()
            # Skills may already be loaded in observation from intent routing
            observation[CHAIN_FALLBACK_KEY] = True  # BF-922: the routed chain's fallback

        # --- LLM call (cache miss) ---
        try:
            decision = await self._decide_via_llm(observation)
        finally:
            observation.pop(CHAIN_FALLBACK_KEY, None)
```

Pair 3 (the gate):

SEARCH:
```python
        # Pass strategy IDs back for caller to process
        if applied_strategy_ids:
            decision["_applied_strategy_ids"] = applied_strategy_ids

        return decision

    async def _resolve_owned_steps_model_context(
```
REPLACE:
```python
        # BF-922 (#1639): a single call that answers for a chain that returned no
        # decision runs the chain's deterministic output checks on its reply.
        if observation.get(CHAIN_FALLBACK_KEY):
            gated = self._gate_fallback_output(decision, request, response, observation)
            if gated is not None:
                return gated

        # Pass strategy IDs back for caller to process
        if applied_strategy_ids:
            decision["_applied_strategy_ids"] = applied_strategy_ids

        return decision

    def _gate_fallback_output(
        self, decision: dict, request: LLMRequest, response: LLMResponse, observation: dict,
    ) -> dict | None:
        """BF-922 (#1639): BF-191 and BF-204 on the single-call fallback's reply.

        AD-632a's fallback is the pre-chain single call, which predates EVALUATE;
        BF-204 holds at every trust band and social obligation, so the fallback runs
        the deterministic checks too, grounded on what the answering call was sent:
        this request's system prompt and user prompt, the AD-835 per-tier suffix the
        attempt that answered appended to the system message after the request was
        built (``response.applied_system_suffix``; a failed attempt's never counts),
        and the intent's ids. That text holds no output of this call; like the chain's
        world text it can quote earlier replies (the conversation, the agent's own
        previous posts), which BF-922's D1 accepts. Not the LLM judge: the fallback
        runs when the model is already failing, and the judge's repeatability is
        unmeasured (AD-1350, #1637). Returns BF-206's suppressed decision, or None to post.
        """
        output = decision.get("llm_output") or ""
        given = (request.system_prompt or "", response.applied_system_suffix, request.prompt or "")
        shown = shown_hex_runs(*given, *intent_entity_ids(observation))
        rejection = deterministic_rejection(output, shown)
        if rejection is None:
            return None
        callsign = getattr(self, "callsign", "") or self.agent_type
        log_rejection(
            rejection, output,
            agent_type=self.agent_type, agent_id=self.id, callsign=callsign, path=PATH_FALLBACK,
        )
        logger.info(
            "BF-922: Single-call fallback output suppressed for %s %s (%s) — deterministic check (%s)",
            self.agent_type, callsign, self.id, rejection.reason,
        )
        self._emit_output_suppressed(rejection.reason, observation, path=PATH_FALLBACK)
        return {
            "action": "execute",
            "llm_output": "[NO_RESPONSE]",
            "tier_used": decision.get("tier_used", ""),
            "_suppressed": True,
            "_suppression_reason": rejection.reason,
        }

    async def _resolve_owned_steps_model_context(
```

### 7.7 `src/probos/cognitive/cognitive_agent.py` (M2: the BF-206 line, this prompt's lines of the suppression block)

Pair 4:

SEARCH:
```python
                rejection = eval_r.result.get("rejection_reason", "quality_gate")
                logger.info(
                    "BF-206: Chain output suppressed — Evaluate recommended suppress (%s)",
                    rejection,
                )
```
REPLACE:
```python
                rejection = eval_r.result.get("rejection_reason", "quality_gate")
                # BF-922 (#1639): name the agent, so a suppression can be attributed from the log.
                logger.info(
                    "BF-206: Chain output suppressed for %s %s (%s) — Evaluate recommended suppress (%s)",
                    self.agent_type, getattr(self, "callsign", "") or self.agent_type, self.id, rejection,
                )
```

### 7.8 New file: `tests/test_bf922_fallback_gate.py` (M2)

```python
"""BF-922 (#1639) M2: the single-call fallback runs the chain's deterministic output checks; the BF-206 line names the agent.

The contract is ``prompts/bf-922-output-gate-grounding-and-fallback.md``. Real code from ``decide()`` through AD-643a's
routing, the triage or chain failure, the fallback flag, ``_decide_via_llm`` and the gate. Stand-ins, named: the model
client (``_OneShotClient``: one scripted reply), the chain executor (raises on triage, or returns a triage and then
raises), ``_check_procedural_memory`` (no procedure), and ``_build_user_message`` (returns ``THREAD``, so the request's
text is known). The runtime is ``MagicMock(spec=ProbOSRuntime)`` with a real ``SystemConfig`` and a trust network that
answers 0.5; any further attribute the routing path reads that a spec'd mock cannot answer is set on the mock here and
named in this docstring. The transport tests (BF-922 A1) swap in the real ``OpenAICompatibleClient``, whose HTTP clients
answer through ``httpx.MockTransport`` per host as in tests/test_ad835_tier_adaptation.py, and set
``runtime.config.cognitive`` to that client's config; only the HTTP endpoints are stand-ins there.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from probos.cognitive.cognitive_agent import (
    CHAIN_FALLBACK_KEY,
    CognitiveAgent,
    _CACHE_HITS,
    _CACHE_MISSES,
    _DECISION_CACHES,
)
from probos.cognitive.llm_client import MockLLMClient, OpenAICompatibleClient
from probos.cognitive.sub_task import (
    SubTaskChain,
    SubTaskError,
    SubTaskExecutor,
    SubTaskResult,
    SubTaskSpec,
    SubTaskType,
)
from probos.config import CognitiveConfig, SystemConfig
from probos.events import EventType
from probos.runtime import ProbOSRuntime
from probos.types import LLMRequest, LLMResponse

THREAD_ID = "1ce6b514-9b54-4c2e-8f0a-2b7c9d3e4f51"
POST_ID = "c71f7ab2-e9d5-4a10-b2c3-d4e5f6a7b8c9"
THREAD = (
    "[Ward Room — #medical]\nThread: Post-stasis readiness\n"
    f"[{POST_ID[:8]}] Meridian: Surgeon GREEN post-stasis; all medical systems nominal."
)
INVENTED = "Per post 7f3a9c2e and thread b81d04aa, the backlog cleared."
GROUNDED = f"Agreed with {POST_ID[:8]}; nothing to add on thread {THREAD_ID[:8]}."
RAW_JSON = '{"intents": [{"intent": "ward_room_post"}]}'
GIVEN_BY_TIER = "Reference records available to this tier: post 7f3a9c2e and thread b81d04aa."


class _CrewAgent(CognitiveAgent):
    agent_type = "science_officer"
    _handled_intents = {"ward_room_notification", "test"}
    instructions = "You are a test crew agent."


class _OneShotClient(MockLLMClient):
    """Answers every request with one scripted reply and records the requests."""

    def __init__(self, content: str) -> None:
        super().__init__()
        self._response = LLMResponse(content=content, model="test-model")
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        return self._response


@pytest.fixture(autouse=True)
def _clear_decision_caches() -> None:
    _DECISION_CACHES.clear()
    _CACHE_HITS.clear()
    _CACHE_MISSES.clear()


def _agent(reply: str, *, execute: Any) -> tuple[_CrewAgent, MagicMock]:
    runtime = MagicMock(spec=ProbOSRuntime)
    runtime.config = SystemConfig()
    runtime.trust_network = MagicMock()
    runtime.trust_network.get_score.return_value = 0.5
    agent = _CrewAgent(llm_client=_OneShotClient(reply), runtime=runtime)
    agent.callsign = "Kira"
    agent._check_procedural_memory = AsyncMock(return_value=None)
    agent._build_user_message = AsyncMock(return_value=THREAD)
    executor = MagicMock(spec=SubTaskExecutor)
    executor.enabled = True
    executor.can_execute.return_value = True
    executor.execute = execute
    agent._sub_task_executor = executor
    return agent, runtime


def _observation() -> dict[str, Any]:
    return {
        "intent": "ward_room_notification",
        "intent_id": "intent-1",
        "context": THREAD,
        "params": {
            "thread_id": THREAD_ID,
            "channel_id": "",
            "channel_name": "medical",
            "title": "Post-stasis readiness",
            "author_id": "meridian",
            "author_callsign": "Meridian",
        },
    }


def _suppression_events(runtime: MagicMock) -> list[dict[str, Any]]:
    return [
        call.args[1] for call in runtime.emit_event.call_args_list
        if call.args and call.args[0] == EventType.CONFABULATION_SUPPRESSED
    ]


@pytest.mark.asyncio
async def test_a_triage_failure_fallback_citing_invented_ids_is_suppressed(caplog) -> None:
    agent, runtime = _agent(INVENTED, execute=AsyncMock(side_effect=SubTaskError("triage timed out")))
    observation = _observation()

    with caplog.at_level(logging.INFO):
        decision = await agent.decide(observation)

    assert agent._sub_task_executor.execute.await_args.args[0].source.endswith(":triage")  # the real triage ran
    assert agent._llm_client.requests, "the fallback single call was made"
    assert decision["llm_output"] == "[NO_RESPONSE]"
    assert decision["_suppressed"] is True
    assert decision["_suppression_reason"] == "confabulation_detected"
    (event,) = _suppression_events(runtime)
    assert event["path"] == "single_call_fallback"
    assert "BF-922: Single-call fallback output suppressed for science_officer Kira" in caplog.text
    assert "path=single_call_fallback) — 2 ungrounded hex IDs: ['7f3a9c2e', 'b81d04aa']" in caplog.text
    assert CHAIN_FALLBACK_KEY not in observation


@pytest.mark.asyncio
async def test_a_fallback_reply_citing_given_ids_is_posted() -> None:
    """The post id is in the request's user prompt; the thread id is the intent's own (BF-233)."""
    agent, runtime = _agent(GROUNDED, execute=AsyncMock(side_effect=SubTaskError("triage timed out")))

    decision = await agent.decide(_observation())

    assert decision["llm_output"] == GROUNDED
    assert not decision.get("_suppressed")
    assert _suppression_events(runtime) == []


@pytest.mark.asyncio
async def test_a_chain_failure_after_triage_is_gated_too() -> None:
    triage = [
        SubTaskResult(
            sub_task_type=SubTaskType.ANALYZE, name="analyze-reply", result={"intended_actions": ["ward_room_reply"]},
        ),
    ]
    agent, _ = _agent(INVENTED, execute=AsyncMock(side_effect=[triage, SubTaskError("compose timed out")]))

    decision = await agent.decide(_observation())

    assert agent._sub_task_executor.execute.await_count == 2
    assert decision["_suppression_reason"] == "confabulation_detected"


@pytest.mark.asyncio
async def test_raw_intent_json_on_the_fallback_is_suppressed() -> None:
    agent, _ = _agent(RAW_JSON, execute=AsyncMock(side_effect=SubTaskError("triage timed out")))

    decision = await agent.decide(_observation())

    assert decision["_suppression_reason"] == "raw_json_output"


@pytest.mark.asyncio
async def test_an_external_chain_fallback_is_gated_for_a_chain_intent() -> None:
    agent, _ = _agent(INVENTED, execute=AsyncMock(side_effect=SubTaskError("external chain failed")))
    agent._pending_sub_task_chain = SubTaskChain(
        steps=[SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="external-compose")], source="external",
    )
    agent._load_augmentation_skills = MagicMock(return_value="")

    decision = await agent.decide(_observation())

    assert decision["_suppression_reason"] == "confabulation_detected"


@pytest.mark.asyncio
async def test_a_single_call_that_answers_no_chain_is_not_gated() -> None:
    agent, runtime = _agent(INVENTED, execute=AsyncMock(side_effect=AssertionError("no chain runs for this intent")))

    decision = await agent.decide({"intent": "test", "params": {"q": "hello"}, "context": ""})

    assert decision["llm_output"] == INVENTED
    assert _suppression_events(runtime) == []


@pytest.mark.asyncio
async def test_the_chain_suppression_log_line_names_the_agent(caplog) -> None:
    agent = CognitiveAgent.__new__(CognitiveAgent)  # as tests/test_bf206_confab_feedback.py builds it
    agent.id = "agent-1"
    agent.agent_type = "science_officer"
    agent.callsign = "Kira"
    agent._runtime = MagicMock()
    executor = MagicMock()
    executor.can_execute.return_value = True
    executor.execute = AsyncMock(return_value=[
        SubTaskResult(sub_task_type=SubTaskType.COMPOSE, name="compose-reply", result={"output": "x"}),
        SubTaskResult(sub_task_type=SubTaskType.EVALUATE, name="evaluate-reply", result={"recommendation": "suppress"}),
    ])
    agent._sub_task_executor = executor
    chain = MagicMock()
    chain.source = "test"
    chain.steps = [MagicMock()]

    with caplog.at_level(logging.INFO, logger="probos.cognitive.cognitive_agent"):
        await agent._execute_sub_task_chain(chain, {"intent": "ward_room_notification"})

    assert (
        "BF-206: Chain output suppressed for science_officer Kira (agent-1)"
        " — Evaluate recommended suppress (quality_gate)"
    ) in caplog.text


# --- the answering attempt's system message (BF-922 A1, round 1 M2 finding 1) ------------------------


def _tiered_config(**suffixes: str) -> CognitiveConfig:
    """Three endpoints, and the AD-835 per-tier system-prompt suffixes named (unnamed tiers keep None)."""
    return CognitiveConfig(
        llm_base_url_fast="http://fast.local/v1", llm_model_fast="fast-model",
        llm_base_url_standard="http://standard.local/v1", llm_model_standard="standard-model",
        llm_base_url_deep="http://deep.local/v1", llm_model_deep="deep-model",
        **{f"llm_system_prompt_suffix_{tier}": text for tier, text in suffixes.items()},
    )


async def _over_transport(
    config: CognitiveConfig, answer: str, sent: list[tuple[str, dict[str, Any]]],
    *, answering_host: str = "standard.local",
) -> OpenAICompatibleClient:
    """The real client; ``answering_host`` answers ``answer`` and every other host returns 503 ("": none answers)."""
    client = OpenAICompatibleClient(config=config)

    def dispatch(http_request: httpx.Request) -> httpx.Response:
        sent.append((http_request.url.host, json.loads(http_request.content)))
        if http_request.url.host != answering_host:
            return httpx.Response(503, text="temporarily unavailable")
        return httpx.Response(200, json={
            "model": "standard-model",
            "choices": [{"message": {"content": answer}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        })

    for key, existing in list(client._clients.items()):
        await existing.aclose()
        client._clients[key] = httpx.AsyncClient(
            base_url=existing.base_url, transport=httpx.MockTransport(dispatch), timeout=5.0,
        )
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("suffixes", "requested_tier", "suppressed"),
    [
        ({"standard": GIVEN_BY_TIER}, None, False),
        ({"standard": GIVEN_BY_TIER, "deep": "A different tier addendum."}, "deep", False),
        ({"deep": GIVEN_BY_TIER}, "deep", True),
    ],
    ids=["serving_tier_suffix", "retry_serving_tier_suffix", "ids_only_in_failed_attempt"],
)
async def test_the_fallback_grounds_on_the_answering_attempts_system_message(
    suffixes: dict[str, str], requested_tier: str | None, suppressed: bool,
) -> None:
    """The real client appends the answering attempt's AD-835 suffix after the request is built. Ids given only there
    ground the reply, directly or after deep and fast fail; ids given only to a failed attempt do not."""
    sent: list[tuple[str, dict[str, Any]]] = []
    config = _tiered_config(**suffixes)
    client = await _over_transport(config, INVENTED, sent)
    try:
        agent, runtime = _agent(INVENTED, execute=AsyncMock(side_effect=SubTaskError("triage timed out")))
        runtime.config.cognitive = config
        agent._llm_client = client  # the real client, as the round-1 review's probe drove it
        observation = _observation()
        if requested_tier is not None:
            observation["level_llm_tier"] = requested_tier
        decision = await agent.decide(observation)
    finally:
        await client.close()

    host, payload = sent[-1]
    answered_system = payload["messages"][0]["content"]
    assert host == "standard.local"
    if requested_tier is not None:
        assert sent[0][0] == "deep.local"  # the requested tier failed first
    if suppressed:
        assert "7f3a9c2e" in sent[0][1]["messages"][0]["content"]  # the failed attempt was given the ids
    assert ("7f3a9c2e" in answered_system and "b81d04aa" in answered_system) is not suppressed
    assert bool(decision.get("_suppressed")) is suppressed
    assert decision["llm_output"] == ("[NO_RESPONSE]" if suppressed else INVENTED)


@pytest.mark.asyncio
async def test_a_cache_replay_keeps_the_answering_attempts_suffix() -> None:
    """A replay was produced under its first attempt's suffix; without it the fallback gate would suppress a grounded
    reply the client served from its cache."""
    sent: list[tuple[str, dict[str, Any]]] = []
    client = await _over_transport(_tiered_config(), GROUNDED, sent, answering_host="")
    request = LLMRequest(prompt="hi", system_prompt="BASE", tier="standard")
    client._cache[client._cache_key("standard", request.prompt, request.system_prompt)] = LLMResponse(
        content=GROUNDED, model="standard-model", applied_system_suffix=GIVEN_BY_TIER,
    )
    try:
        replay = await client.complete(request)
    finally:
        await client.close()

    assert sent, "premise: the tiers were tried and failed"
    assert replay.cached is True and replay.content == GROUNDED
    assert replay.applied_system_suffix == GIVEN_BY_TIER
```

### 7.9 `src/probos/cognitive/llm_client.py` (M2, Amendment A1: the response reports the suffix it was sent with)

Pair 1 (the rate-limit cache replay):

SEARCH:
```python
                        return LLMResponse(
                            content=cached.content, model=cached.model, tier=tier,
                            answered_tier=cached.answered_tier, answered_model=cached.answered_model,
                            tokens_used=cached.tokens_used, cached=True, request_id=request.id,
                        )
```
REPLACE:
```python
                        return LLMResponse(
                            content=cached.content, model=cached.model, tier=tier,
                            answered_tier=cached.answered_tier, answered_model=cached.answered_model,
                            applied_system_suffix=cached.applied_system_suffix,  # BF-922: kept on a replay
                            tokens_used=cached.tokens_used, cached=True, request_id=request.id,
                        )
```

Pair 2 (where `_call_openai` appends the suffix):

SEARCH:
```python
        if effective_system_suffix:
            if messages and messages[0].get("role") == "system":
                base = messages[0].get("content")
                if isinstance(base, str):
                    messages[0] = {
                        **messages[0],
                        "content": f"{base}\n\n{effective_system_suffix}",
                    }
                elif isinstance(base, list):
                    messages[0] = {
                        **messages[0],
                        "content": [*base, {"type": "text", "text": effective_system_suffix}],
                    }
            else:
                messages.insert(0, {"role": "system", "content": effective_system_suffix})
```
REPLACE:
```python
        # BF-922 (#1639): what this call appended, reported on the response (``applied_system_suffix``)
        # so a caller can ground on the text the answering attempt was sent; "" when nothing was.
        applied_suffix = ""
        if effective_system_suffix:
            applied_suffix = effective_system_suffix
            if messages and messages[0].get("role") == "system":
                base = messages[0].get("content")
                if isinstance(base, str):
                    messages[0] = {
                        **messages[0],
                        "content": f"{base}\n\n{effective_system_suffix}",
                    }
                elif isinstance(base, list):
                    messages[0] = {
                        **messages[0],
                        "content": [*base, {"type": "text", "text": effective_system_suffix}],
                    }
                else:
                    applied_suffix = ""  # a system message of no known shape is sent unchanged
            else:
                messages.insert(0, {"role": "system", "content": effective_system_suffix})
```

Pair 3 (`_call_openai`'s return):

SEARCH:
```python
            content_blocks=content_blocks_list,
            stop_reason=stop_reason_value,
            answered_model=_echoed_model(data),
            usage_reported=usage_reported,
        )
```
REPLACE:
```python
            content_blocks=content_blocks_list,
            stop_reason=stop_reason_value,
            answered_model=_echoed_model(data),
            usage_reported=usage_reported,
            applied_system_suffix=applied_suffix,
        )
```

Pair 4 (the all-tiers-failed cache replay):

SEARCH:
```python
                return LLMResponse(
                    content=cached.content,
                    model=cached.model,
                    answered_tier=cached.answered_tier,
                    answered_model=cached.answered_model,
```
REPLACE:
```python
                return LLMResponse(
                    content=cached.content,
                    model=cached.model,
                    answered_tier=cached.answered_tier,
                    answered_model=cached.answered_model,
                    applied_system_suffix=cached.applied_system_suffix,  # BF-922: what the answering attempt appended
```

### 7.10 `src/probos/types.py` (M2, Amendment A1: `LLMResponse.applied_system_suffix`)

SEARCH:
```python
    # ``probos.cognitive.token_accounting.charge_completion`` reads this (the agentic loop does not).
    usage_reported: bool | None = None
```
REPLACE:
```python
    # ``probos.cognitive.token_accounting.charge_completion`` reads this (the agentic loop does not).
    usage_reported: bool | None = None
    # BF-922 (#1639): the per-tier system-prompt suffix (AD-835) this response's call appended to the
    # system message, as sent. Set by ``OpenAICompatibleClient._call_openai`` for the attempt that
    # produced the response (a failed attempt's response is discarded with its suffix) and kept on
    # cache replays; "" when none was appended (the default; the Ollama-native transport, the mock
    # client, test doubles, errors). The single-call fallback's BF-204 grounds on it.
    applied_system_suffix: str = ""
```

### 7.11 `src/probos/cognitive/cognitive_agent.py` (M2, Amendment A1: the `LLMResponse` import)

SEARCH:
```python
    IntentResult,
    LLMRequest,
    Priority,
```
REPLACE:
```python
    IntentResult,
    LLMRequest,
    LLMResponse,
    Priority,
```

### 7.12 `tests/test_ad1325_boundaries.py` (M2, Amendment A1: exact-base bytes exclude the new field)

SEARCH:
```python
        # BF-901 appended ``usage_reported`` (default None) the same way; test_bf901_s1_token_accounting
        # pins its default (test_usage_reported_defaults_to_none).
        "response": {
            key: value for key, value in asdict(response).items()
            if key not in ("answered_tier", "answered_model", "usage_reported")
        },
```
REPLACE:
```python
        # BF-901 appended ``usage_reported`` (default None) the same way; test_bf901_s1_token_accounting
        # pins its default (test_usage_reported_defaults_to_none).
        # BF-922 appended ``applied_system_suffix`` (default "") the same way; test_bf922_fallback_gate
        # pins it on the answering attempt and on a cache replay.
        "response": {
            key: value for key, value in asdict(response).items()
            if key not in ("answered_tier", "answered_model", "usage_reported", "applied_system_suffix")
        },
```

## 8. Tracking

Anchors as in BF-921's section 8 (`PROGRESS.md`'s title line; the `DECISIONS.md` heading `### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)`). The entries go in M2's commit. Set the date to the commit date.

**`PROGRESS.md`:**

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-922 (2026-10-24), #1639 -- the chain's output gate: BF-204 grounds on what the composer was given, the single-call fallback is gated, and the suppression line names the agent.** New `probos/cognitive/output_grounding.py` holds BF-191 and BF-204 for both gates. BF-204 now grounds on `composer_world_text` (COMPOSE's own user prompt without the ANALYZE result: the thread, memories, lookups, QUERY and situation sections) plus BF-233's intent ids, no longer on the ANALYZE result (and on the AD-1347 lookup's text only for a found or ambiguous record: a failed lookup repeats the reference ANALYZE chose); a cited id needs a letter a-f (pure-decimal numbers are not ids) and ids count once. 216 of 309 live BF-204 suppressions cited real Ward Room ids. A single call that answers for a chain intent's chain that returned no decision (a triage or chain failure, AD-632a/AD-643a) runs BF-191 and BF-204 on its reply, grounded on what the answering attempt was sent (its request text and the AD-835 per-tier suffix, carried back as `LLMResponse.applied_system_suffix`), not the LLM judge; a rejection is BF-206's suppressed decision with `CONFABULATION_SUPPRESSED` `path=single_call_fallback`. The BF-206, BF-204 and BF-191 lines name the agent. New: `tests/test_bf922_output_grounding.py`, `tests/test_bf922_fallback_gate.py`, `tests/fixtures/bf922_live_grounding_cases.json`. #1639 stays open for the prospective re-measure of the false-positive rate (the contract's D2). The contract is `prompts/bf-922-output-gate-grounding-and-fallback.md`.
```

**`DECISIONS.md`:**

SEARCH:
```markdown
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
### BF-922 -- The chain's output gate grounds on what the composer was given, and the fallback is gated (2026-10-24, #1639)

- *Grounding source.* BF-204 grounds on what the composing call was given from outside the chain's own model calls (`composer_world_text`) and on the intent's own ids (BF-233); the ANALYZE result is no longer a source, so a repeated invented id is not grounded. A retrieval's echo of a model-chosen key is not a source either: a failed AD-1347 lookup's text grounds nothing (review round 1). Rejected: recording the exact COMPOSE request (grounds model output; changes a result contract).
- *Pattern and count.* A cited id is a whole word of 6+ hex with a letter a-f; distinct ids; threshold 2.
- *Fallback.* AD-632a's fallback degrades to the pre-chain single call, which predates EVALUATE; it was never designed ungated. Every single call that answers a chain intent after its chain returned no decision runs BF-191 and BF-204 on what the answering attempt was sent (the request text and its AD-835 suffix, `LLMResponse.applied_system_suffix`); not the LLM judge (the model is already failing; the judge is unmeasured, AD-1350).
- *Re-measure.* No replay is possible (prompts are not retained); the logged ids are re-scored at build time and the false-positive rate is measured on the merged build's own lines (#1639 stays open for it).
- *Reversal.* Revert the commits.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, then its `--check`. **`docs/development/roadmap.md`:** no row.

**#1639 checklist text** (the orchestrator records it on the issue):
- [ ] (1) BF-204 grounds on `composer_world_text` + intent ids; pure-decimal excluded; distinct ids; a failed lookup's echo grounds nothing; live-fixture regression through production renderers and must-still-catch tests (M1).
- [ ] (1, re-measure a) logged ids re-scored at build time, recorded here (D2).
- [ ] (2) The single-call fallback runs BF-191 and BF-204 (not the judge) on what the answering attempt was sent; seam tests drive a real triage failure and the real transport's per-tier suffix (M2).
- [ ] (3) The BF-206 line names the agent type, callsign and id (M2).
- [ ] (1, re-measure b) false-positive rate on the merged build's own BF-204 lines, recorded here (D2). Closes #1639.

## 9. What this does NOT change

- EVALUATE's LLM judge, its modes and its obligation, boot-camp and low-trust bypasses are unchanged; the deterministic checks still run first, at every band.
- COMPOSE's prompt and result are unchanged (`composer_world_text` is a new reader of `_build_user_prompt`).
- The single call itself (its prompt, model call, journal row) is unchanged; only its reply is checked afterwards, and only on the fallback.
- A single call for any intent outside `_CHAIN_ELIGIBLE_INTENTS` is not gated. The suppressed decision has BF-206's shape.
- BF-921's emitter, payload keys and the Counselor's record-only rule are unchanged; this prompt only adds `path="single_call_fallback"` calls.
- `CONFABULATION_SUPPRESSED` persistence is unchanged (BF-921 R1).
- AD-1347's lookup, `render_lookup` and COMPOSE's lookup section are unchanged; COMPOSE still shows a failed lookup's text (A1 only stops it grounding).
- AD-835's suffix application is unchanged; `_call_openai` now reports what it appended, and the Ollama-native transport, which appends none, reports none.

## 10. Mutation rows (whole stripped lines, each occurring once in its file after section 7)

Tier HIGH. Run each row on the applied tree after an unmutated baseline run passes; restore each file before the next row. Command:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf922_output_grounding.py tests/test_bf922_fallback_gate.py tests/test_bf204_grounding.py tests/test_bf233_grounding_false_positives.py tests/test_ad1347_s4_chain_lookup.py -n 0 -x -q
```

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| G1 | `src/probos/cognitive/output_grounding.py` | `_CITED_ID = re.compile(r"\b(?=[0-9]*[a-f])[0-9a-f]{6,}\b")` | `_CITED_ID = re.compile(r"\b[0-9a-f]{6,}\b")` | `test_pure_decimal_numbers_are_not_cited_ids` |
| G2 | `src/probos/cognitive/output_grounding.py` | `return tuple(dict.fromkeys(_CITED_ID.findall((output or "").lower())))` | `return tuple(_CITED_ID.findall((output or "").lower()))` | `test_a_repeated_id_counts_once`, `test_a_live_decimal_or_repeat_case_is_not_suppressed` |
| G3 | `src/probos/cognitive/output_grounding.py` | `MIN_UNGROUNDED_IDS = 2` | `MIN_UNGROUNDED_IDS = 1` | `test_one_ungrounded_id_is_below_the_threshold` |
| G4 | `src/probos/cognitive/output_grounding.py` | `return tuple(cited for cited in cited_ids(output) if cited not in shown_text)` | `return cited_ids(output)` | `test_a_live_false_positive_is_grounded_when_given`, `test_an_id_in_any_world_section_is_grounded` |
| G5 | `src/probos/cognitive/output_grounding.py` | `for key in ("thread_id", "channel_id", "author_id"):` | `for key in ():` | `test_the_bf233_intent_ids_are_given`, `test_bf233_grounding_false_positives.py` |
| G6 | `src/probos/cognitive/sub_tasks/compose.py` | `world = [pr for pr in prior_results if pr.sub_task_type != SubTaskType.ANALYZE]` | `world = list(prior_results)` | `test_the_world_text_leaves_out_the_analysis`, `test_an_id_only_in_the_analysis_is_not_grounded` |
| G7 | `src/probos/cognitive/sub_tasks/evaluate.py` | `_shown = shown_hex_runs(composer_world_text(context, prior_results), *intent_entity_ids(context))` | `_shown = shown_hex_runs(*intent_entity_ids(context))` | `test_an_id_in_any_world_section_is_grounded`, `test_bf204_grounding.py::test_hex_ids_in_source_no_false_positive` |
| G8 | `src/probos/cognitive/sub_tasks/compose.py` | `if context.get("_ward_room_lookup_outcome") not in (LOOKUP_FOUND, LOOKUP_AMBIGUOUS):` | `if False:` | `test_a_failed_lookup_echo_does_not_ground_through_the_real_chain`, `test_the_lookup_text_grounds_only_for_a_record_outcome` |
| G9 | `src/probos/cognitive/sub_tasks/compose.py` | `if context.get("_ward_room_lookup_outcome") not in (LOOKUP_FOUND, LOOKUP_AMBIGUOUS):` | `if True:` | `test_a_found_record_grounds_through_the_real_chain`, `test_the_lookup_text_grounds_only_for_a_record_outcome`, `test_an_id_in_any_world_section_is_grounded` |
| G10 | `src/probos/cognitive/sub_tasks/query.py` | `return {"ward_room_lookup": render_lookup(result), "ward_room_lookup_outcome": result.outcome}` | `return {"ward_room_lookup": render_lookup(result), "ward_room_lookup_outcome": "found"}` | `test_a_failed_lookup_echo_does_not_ground_through_the_real_chain`, `test_the_asker_is_the_chains_agent_id_never_a_params_agent_id` |
| G11 | `src/probos/cognitive/cognitive_agent.py` | `observation["_ward_room_lookup_outcome"] = outcome if isinstance(outcome, str) else ""` | `pass` | `test_a_found_record_grounds_through_the_real_chain`, `test_the_helper_reads_the_ref_from_analyze_and_runs_once` |
| F1 | `src/probos/cognitive/cognitive_agent.py` | `observation[CHAIN_FALLBACK_KEY] = True  # BF-922: the routed chain's fallback` | `pass` | `test_a_triage_failure_fallback_citing_invented_ids_is_suppressed` |
| F2 | `src/probos/cognitive/cognitive_agent.py` | `observation[CHAIN_FALLBACK_KEY] = True  # BF-922: an external chain's fallback` | `pass` | `test_an_external_chain_fallback_is_gated_for_a_chain_intent` |
| F3 | `src/probos/cognitive/cognitive_agent.py` | `if observation.get(CHAIN_FALLBACK_KEY):` | `if False:` | `test_a_triage_failure_fallback_citing_invented_ids_is_suppressed` |
| F4 | `src/probos/cognitive/cognitive_agent.py` | `shown = shown_hex_runs(*given, *intent_entity_ids(observation))` | `shown = shown_hex_runs(given[0])` | `test_a_fallback_reply_citing_given_ids_is_posted` |
| F5 | `src/probos/cognitive/cognitive_agent.py` | `self._emit_output_suppressed(rejection.reason, observation, path=PATH_FALLBACK)` | `pass` | `test_a_triage_failure_fallback_citing_invented_ids_is_suppressed` |
| F6 | `src/probos/cognitive/cognitive_agent.py` | `observation.pop(CHAIN_FALLBACK_KEY, None)` | `pass` | `test_a_triage_failure_fallback_citing_invented_ids_is_suppressed` |
| F7 | `src/probos/cognitive/cognitive_agent.py` | `self.agent_type, getattr(self, "callsign", "") or self.agent_type, self.id, rejection,` | `self.agent_type, "", "", rejection,` | `test_the_chain_suppression_log_line_names_the_agent` |
| F8 | `src/probos/cognitive/cognitive_agent.py` | `if observation.get("intent") in _CHAIN_ELIGIBLE_INTENTS:  # BF-922: only a chain intent's reply` | `if True:` | none in this suite (an external chain for a non-chain intent is not driven); recorded as surviving, R4 |
| F9 | `src/probos/cognitive/cognitive_agent.py` | `given = (request.system_prompt or "", response.applied_system_suffix, request.prompt or "")` | `given = (request.system_prompt or "", request.prompt or "")` | `test_the_fallback_grounds_on_the_answering_attempts_system_message` |
| F10 | `src/probos/cognitive/llm_client.py` | `applied_suffix = effective_system_suffix` | `applied_suffix = ""` | `test_the_fallback_grounds_on_the_answering_attempts_system_message` |
| F11 | `src/probos/cognitive/llm_client.py` | `applied_system_suffix=applied_suffix,` | `applied_system_suffix="",` | `test_the_fallback_grounds_on_the_answering_attempts_system_message` |
| F12 | `src/probos/cognitive/llm_client.py` | `applied_system_suffix=cached.applied_system_suffix,  # BF-922: what the answering attempt appended` | `applied_system_suffix="",` | `test_a_cache_replay_keeps_the_answering_attempts_suffix` |

The rate-limit replay's copy (section 7.9 pair 1) has no row: reaching it needs an exhausted rate budget, and it is the same copy as F12's.

## 11. Verified Against Codebase (2026-10-24, worktree `d922-draft` at `origin/main` `cb190f32`)

```
grep -n "BF-204\|BF-233\|BF-191\|0-9a-f\]{6" src/probos/cognitive/sub_tasks/evaluate.py
  464, 469, 489, 494, 520, 524
grep -n "\bre\.\|\bjson\." src/probos/cognitive/sub_tasks/evaluate.py
  205, 288, 334 (json), 492 (json, removed), 520 (re, removed: re has no other use)
grep -n "def _build_user_prompt\|original = context.get(\"context\"\|_wr_lookup = \|_ward_room = context.get\|formatted_memories = context.get\|return \"\\\\n\\\\n\".join(parts)" src/probos/cognitive/sub_tasks/compose.py
  408, 416, 477, 510, 542, 578
grep -n "_build_user_prompt(context, prior_results)" src/probos/cognitive/sub_tasks/compose.py
  192, 235, 367 (all three modes)
read src/probos/cognitive/sub_tasks/__init__.py
  1-16: AD646B_DEDICATED_KEYS defined before the handler imports (compose before evaluate): no import cycle from evaluate -> compose
grep -n "context_keys and spec.sub_task_type != SubTaskType.QUERY\|k.startswith(\"_\")" src/probos/cognitive/sub_task.py
  565, 568 (EVALUATE and COMPOSE see the same context; only QUERY specs declare context_keys, cognitive_agent.py:5652/5715/5812/5848)
grep -n "_id_prefix = f\"\[{p_id\[:8\]}\] \"" src/probos/ward_room_router.py
  549
grep -n "post:{a\['post_id'\]\[:8\]}" src/probos/cognitive/cognitive_agent.py
  9398, 11085
grep -n "f\"Post {found.matched_post_id} in thread {found.thread_id}" src/probos/ward_room/lookup.py
  413
grep -n "AD-632a: Sub-task chain failed\|AD-643a: Triage phase failed\|AD-632f: Falling back to single-call\|# chain_result is None\|decision = await self._decide_via_llm(observation)\|# Pass strategy IDs back\|async def _resolve_owned_steps_model_context" src/probos/cognitive/cognitive_agent.py
  3777, 3807, 3811, 4556, 4562, 5983, 6253
grep -n "^_CHAIN_ELIGIBLE_INTENTS\|^from probos.cognitive.sub_task import CHAIN_PRIORITY_KEY\|^    LLMRequest,\|^from __future__" src/probos/cognitive/cognitive_agent.py
  3, 37, 41, 340
grep -n "request = LLMRequest(" src/probos/cognitive/cognitive_agent.py (in _decide_via_llm)
  4448, 4461, 4467 (every branch binds request before the call at 4503)
grep -n "\"BF-206: Chain output suppressed\|rejection = eval_r.result.get" src/probos/cognitive/cognitive_agent.py
  6001, 6003
grep -n "return chain_result" src/probos/cognitive/cognitive_agent.py (routing)
  6392 (a failed full chain returns None to decide())
grep -n "def _extract_intended_actions" src/probos/cognitive/cognitive_agent.py
  5743 (reads ANALYZE result["intended_actions"])
grep -n "^class SubTaskError\|^class SubTaskExecutor" src/probos/cognitive/sub_task.py
  135, 207
grep -n "def _compose_dm_instructions" src/probos/cognitive/cognitive_agent.py
  3001 (roster by callsign: f"@{cs}" at 3019; no ids)
grep -rn "Chain output suppressed\|Grounding check failed\|rejected raw intent JSON" tests/
  (none)
grep -rln "EvaluateHandler\|evaluate import" tests/
  the 12 files in the M1 focused check
read tests/test_bf901_s2_journal_token_provenance.py:57-114 (the real decide() -> _decide_via_llm harness this M2 test follows)
Amendment A1 (2026-10-24, read on the M2 candidate 6259630e; these regions are equal on the base):
read src/probos/cognitive/sub_tasks/query.py:415-440
  428, 434, 440 return {"ward_room_lookup": ...}; the typed outcome is dropped at 440
read src/probos/ward_room/lookup.py:375-400
  not_found echoes {result.ref} (391); invalid_ref echoes it and "such as 51d91a7d" (393); ambiguous names it (385)
grep -n "substr(id, 1, ?) = ?\|startswith(ref)" src/probos/ward_room/lookup.py
  178, 182, 357, 360 (every live or archived match starts with the ref)
grep -n "context_keys=(" src/probos/cognitive/cognitive_agent.py
  5712, 5775, 5872 (thread_metadata ...), 5908 (unread_counts, trust_score)
read src/probos/cognitive/sub_tasks/compose.py:457-463 (the first successful QUERY result, rendered "- <key>: <value>")
read src/probos/ward_room/messages.py:821-836 ({channel_id: count}); src/probos/ward_room/threads.py:707-767 (thread, posts with ids)
grep -n "effective_system_suffix = tc.get\|response = replace(response, answered_tier=attempt_tier)" src/probos/cognitive/llm_client.py
  1672, 1833
read src/probos/cognitive/llm_client.py:2156-2175 (the Ollama-native call takes no suffix), 2320-2341, 2422-2435, 1526-1530, 2001-2010
grep -rn "asdict(response)" tests/
  tests/test_ad1325_boundaries.py:232
read src/probos/cognitive/cognitive_agent.py:12726-12748 (default tier "standard"; level_llm_tier overrides it)
read tests/test_ad835_tier_adaptation.py:168-218 (deep fails, fast fails, standard serves with its own suffix)
```

## 12. Absence Verified (2026-10-24)

```
CLAIM: the cognitive journal and chain traces do not keep the rendered prompt (no replay possible)
RUN:   rg -n "prompt_hash|response_hash" src/probos/cognitive/cognitive_agent.py; rg -n "\.result" src/probos/cognitive/chain_trace.py
FOUND: cognitive_agent.py:4518 (prompt_hash = md5 of the first 500 chars), 4548; chain_trace.py: no match
HOLDS: yes

CLAIM: no test pins the old BF-191/BF-204/BF-206 log texts
RUN:   Grep "Chain output suppressed|Grounding check failed|rejected raw intent JSON" over tests/
FOUND: none
HOLDS: yes

CLAIM: nothing renders arbitrary observation keys into a prompt (so CHAIN_FALLBACK_KEY cannot leak into one)
RUN:   rg -n "json\.dumps\(observation|observation\.items\(\)" src/probos/cognitive/cognitive_agent.py
FOUND: none; _compute_cache_key reads an allowlist only (12710-12715)
HOLDS: yes

CLAIM: the crew roster in COMPOSE's system prompt carries no ids
RUN:   read cognitive_agent.py:3001-3046
FOUND: only "@<callsign>" entries grouped by department
HOLDS: yes

CLAIM (A1): the single-call fallback's prompt carries no Ward Room lookup text and no model-chosen reference
RUN:   Grep "_oracle_context|oracle_query_text|_ward_room_lookup|ward_room_lookup_ref" over src/probos (analyze.py's prompt text aside)
FOUND: _ward_room_lookup_context read only at compose.py:510; ward_room_lookup_ref read only at query.py:426; oracle_query_text only at query.py:251, 325; _oracle_context rendered by the single call (cognitive_agent.py:10622-10634, 10917-10927) and COMPOSE, and its formatter (oracle_service.py:715-753) renders results, never the query
HOLDS: yes: no exclusion is needed on the fallback

CLAIM (A1): only the dispatch and AD-1347 S4's tests read the lookup QUERY's result dict
RUN:   Grep "ward_room_lookup" over src/ and tests/
FOUND: src: query.py:415-461, cognitive_agent.py:5744-5800, 6260, 6379-6380, compose.py:510, analyze.py (prompt text); tests: test_ad1347_s4_chain_lookup.py (whole-dict equality at :141, :148, :151, :154, :159), test_bf922_output_grounding.py:95, :179, and the "N keys" prompt counts in test_ad643a and test_ad645
HOLDS: yes

CLAIM (A1): no test that wires a sub-task executor drives a chain-intent fallback with a response double lacking a str applied_system_suffix
RUN:   Grep "_sub_task_executor = |set_sub_task_executor\(" over tests/ (17 files), then "MagicMock\(content=|\.content = |return_value=MagicMock\(\)" over those
FOUND: ad1156:193, ad1208:127/383/2046 (agentic-loop response classes), ad632a:626 (no executor in that test), fallback_learning:689/710 (_run_llm_fallback, intent "test", executor None)
HOLDS: yes for those files; the broad gate checks the rest
```

## 13. Prior Art and Blind Spots

- Bug fix: external prior-art review skipped (ProbOS-specific plumbing; no outside analogue for this check).
- Internal: BF-204 (the check), BF-233 (its intent-id exemptions, kept), BF-191, BF-206, AD-632a/AD-643a (the fallback), AD-645 (COMPOSE renders the situation sections), AD-1347 (the lookup rendering with full ids), AD-1350 (#1637, why the judge is not used on the fallback), BF-921 (#1636, the emitter and the penalty rule).
- Blind spots addressed: the ANALYZE laundering hole (D1); the external-chain fallback (D3); a probe parser broken by the new line (section 7.3 note); a fixture of real ids that could carry sensitive bodies (section 6). Considered, deferred: recording the shown-id set per suppression for audit (R2); gating every single call, not only fallbacks (R3).
- Amendment A1 (review round 1): two more ways text crosses the gate's boundary: a retrieval that echoes the model's request back as world text (AD-1347's not_found and invalid_ref lines), and a transport that adds text after the request is built (AD-835's per-tier suffix). Considered, deferred: an audit of every retrieval keyed on model output (the AD-696 Oracle formatter renders results, not the query).

## 14. Diff Reviewer: properties to verify

1. EVALUATE's BF-191/BF-204 result dicts are key-for-key what they were; the deterministic checks still run before every bypass and the judge.
2. Every source BF-204 grounds on is either text COMPOSE renders in its user prompt (computed by the same `_build_user_prompt`, ANALYZE excluded, the AD-1347 lookup's text only for a found or ambiguous outcome) or one of BF-233's intent ids; no output of this chain's model calls is a source, directly or echoed back by a retrieval. Earlier model output that a world section quotes still grounds (R5).
3. A cited id needs a letter a-f; ids are counted once; the threshold is 2; an id inside a given hex run is grounded, as `in` on the text was.
4. The fallback flag is set only when a chain intent's chain returned no decision (routed, or external for a chain intent), is popped on every exit from the single call (including an exception), and is read only by `_decide_via_llm`.
5. On the fallback the checks see exactly the request's system prompt and user prompt, the AD-835 suffix the answering attempt appended (`LLMResponse.applied_system_suffix`: set by `_call_openai` only, `""` when none was appended or on the Ollama-native transport, kept on both cache replays, never a failed attempt's), and the intent's ids; a rejection returns BF-206's decision shape, logs the agent, and emits through `_emit_output_suppressed` with `path="single_call_fallback"`; a pass returns the original decision unchanged, with its strategy ids.
6. A single call for a non-chain intent is never gated.
7. The live fixture is read-only data the tests never write; no test reads `%LOCALAPPDATA%` or `d:\ProbOS\data`.
8. `LLMResponse.applied_system_suffix` is set only where `_call_openai` appends the suffix; it is `""` by default and on the Ollama-native transport, the mock client and errors; both cache replays copy it; `tests/test_ad1325_boundaries.py` excludes it from its exact-base bytes and nothing else serialises `LLMResponse`.
9. `ward_room_lookup_outcome` and `_ward_room_lookup_outcome` change nothing COMPOSE renders (AD-1347 S4's compose assertions are unchanged); the outcome is written only together with the text; a missing or unknown outcome grounds nothing; the live fixture's every id is placed through the real QUERY step and COMPOSE renderer, and the live test requires approval.

## 15. Acceptance criteria

- BF-204's source includes every id the composer was given from the world (posts, threads, channels rendered into its context) and the intent's ids, and nothing this chain's model calls produced, directly or echoed back by a retrieval (a failed AD-1347 lookup's text grounds nothing, shown through the real chain); pure-decimal numbers are not ids; distinct ids are counted.
- The live-fixture regression passes with every id placed through a production renderer and the judge's approval; two invented hex ids are still suppressed; re-measure (a) is recorded on #1639, (b) is scheduled (D2).
- The single-call fallback runs BF-191 and BF-204, not the judge, on what the answering attempt was sent (its AD-835 suffix included, a failed attempt's never); the seam tests drive a real triage failure and the real transport, and catch a fabricated-id reply.
- The BF-206 line names the agent type, callsign and id.
- Before editing, the tests that pin BF-204, BF-233, AD-632a and AD-643a were grepped; any pin of a defect was updated with an inline reason.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Live acceptance: what is read (read-only)

D2 (b): after at least 100 new `BF-204: Grounding check failed` lines or 7 days of vessel time on the merged build, the `bf204_real.py` method over `%LOCALAPPDATA%\ProbOS\data\logs\probos.log*` and `ward_room.db` (`mode=ro&immutable=1`): total, all-real share, split by `path=`, and for each all-real case the section that gave the id or "none". Also the count of `BF-922: Single-call fallback output suppressed` lines against `AD-643a: Triage phase failed` and `AD-632a: Sub-task chain failed` lines in the same window. Recorded on #1639. For each all-real chain case, also note whether the same agent logged `AD-1347: Ward Room lookup ... not_found` or `invalid_ref` just before (the echoes A1 stopped grounding).

## 17. Not verified

- That the M2 seam test's spec'd runtime answers every attribute AD-643a's routing reads (`_build_cognitive_state`, `_track_sensorium_budget`, `_compose_dm_instructions`); the docstring rule covers additions. Not run (the bridge runs no tests).
- That `_build_chain_for_intent` returns a chain with QUERY/ANALYZE steps for the test observation (read: it does for `ward_room_notification`); the triage test asserts `:triage` so a miss fails loudly.
- Where the live full UUIDs and DM channel ids were rendered (the prompts were not retained); the fixture's placements are by kind, and D2 (b) measures the residue.
- The fixture's contents (the orchestrator writes them).
- Amendment A1's tests were not run by the Architect (the bridge runs none). The real-chain lookup tests follow the round-1 reviewer's executed probe (`logs/bf922r1/reviewer_test_production_consumers.py`: two model calls, the DM bypass, BF-206's decision shape); the transport tests follow `reviewer_m2_test_m2_transport_grounding.py` and `tests/test_ad835_tier_adaptation.py` (deep, then fast, then standard).
- That the found-record test's thread is visible to its own author in a DM channel (AD-621's author rule, `lookup.py:9-11`): read, not run.

## 18. For the register (found here, not fixed by this change)

- **R1.** An agent that takes an id only from its own ANALYZE output is now flagged by design (D1); D2 (b) counts how often that happens with a real id.
- **R2.** A suppression records the cited ids in the log only; neither the journal nor events.db can audit what the agent was given (BF-921 R1).
- **R3.** Single calls outside the fallback (DMs, Captain requests, non-chain intents) still run no deterministic check; whether they should is a design question for its own issue.
- **R4.** Mutation F8 (the external chain's eligibility condition) survives this suite, and the AD-632f external-chain path has no production producer at all: `rg -n "pending_sub_task_chain" src/` finds only `cognitive_agent.py:1359` (init to `None`), `:3755-3757` (consume). The external chain is reachable from tests only; whether to keep that escape hatch is a question for its own issue.
- **R5.** Earlier model output that a world section quotes still grounds ids: the thread's previous replies (the agent's own included) and the agent's own unverified reflections in its memories (review round 1, run `bf922-r1-production-consumers-v2`). D1 accepts it (outside this chain's model calls); D2 (b) counts all-real cases by section, which shows how often it matters.
- **R6.** A failed AD-1347 lookup's text still grounds when a custom chain carries the `ward_room_lookup` result as a QUERY step's result (review round 2, finding S1; present since M1's first candidate, not introduced by A1). `composer_world_text` drops the lookup only from the context key `_ward_room_lookup_context` (`compose.py:596-599`), and `_build_user_prompt` renders every successful QUERY result under `## Prior Data` (`compose.py:458-463`), so a result of `{ward_room_lookup: <not_found text>, ward_room_lookup_outcome: not_found}` grounds the ids it repeats: the reviewer's probe and the orchestrator's rerun on the committed code gave base suppress, M1 approve (evidence `bf922-r2-final-consumers`, `bf922-s1-confirm`). **Reach: injected-only.** `git grep -n '"ward_room_lookup"' src` finds the key declared by one QUERY step, the dedicated dispatch chain at `cognitive_agent.py:5783`, whose result `_maybe_dispatch_ward_room_lookup` reads in the same method (`:5805-5811`) into the observation pair that `composer_world_text` filters; no routed chain carries it as a prior result. A chain that does needs the outcome rule applied to `ward_room_lookup` in `prior_results` inside `composer_world_text` (COMPOSE's own prompt unchanged), with a direct-QUERY-result regression for a failed, a missing and an unknown outcome.
