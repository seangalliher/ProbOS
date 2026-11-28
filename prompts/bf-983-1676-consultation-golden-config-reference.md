# BF-983 (#1676): an AD-594 consultation reaches the LLM, the AD-1152 golden says how it is refreshed, and the config reference has a section for every path

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-18

**Corrected by:** the orchestrator, 2026-11-18, after its first oracle run of M2: §7.3's backfill line read `config["medical"]`, but BF-924 (`091f1143`) removed the four fields from `CounselorConfig`, whose section is `counselor` (`config.py:3989`); `MedicalConfig` (`config.py:3988`) keeps its own `enabled`. The line, its comment and the three lines of §11 that named `medical` now name `counselor`. Nothing else changed.

**Corrected again by:** the orchestrator, 2026-11-18, after review round 1 (two P3 findings on section 7.4, each confirmed against `git log -p` on the golden): the lineage paragraph named two kinds of refresh, but a third exists (AD-1321, `0debd77b`, four keys holding null under `persisted.endpoint.work_item`), and the page stated the original capture's observation checksum without saying so. Section 7.4 now names the three kinds, counts all 17 refreshes since the capture (14 for the default configuration digest, two for the composed standing orders, one for the work-item shape), and labels the checksum (the new pair 7.4b). Section 14 property 8 follows. Nothing else changed.

**Status:** build-ready. Issue #1676 (labels: `latent`), batch B3 of the order of work (`48b6aed2`). **One BF number covers the batch.** Item 2 is a production defect, and items 3 and 4 are defects in a test's lineage and in a generator. The orchestrator allocated BF-983 on 2026-11-18 (the ceiling was BF-982, from issue titles and prompt filenames) and replaced the draft's placeholder everywhere; it appears only in REPLACE text and tracker text, never in a SEARCH and never in a path.

**Base:** `origin/main` `9f43697fd8433071dd0f0afc394fba06de905a0c` (2026-11-17). #1680 and #1811 build first. Neither touches a file this contract searches, except `PROGRESS.md` and `DECISIONS.md`, whose anchors are a title and a heading that their insertions leave in place. P6 checks this.

**Line endings:** the working copies are CRLF (`core.autocrlf=true`). The SEARCH blocks are LF. Match and write each file with its own line endings, and write new files LF.

**Milestones:** M1 item 2 (production, tier MEDIUM: a dormant path). M2 items 3 and 1 (tests and docs only, LOW). M3 item 4 (generator, its output and its test, LOW, with a wide generated diff). M4 trackers. Each milestone is one Builder delegation and one local commit, in order. One broad gate after M4: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf-983-1676 --receipt logs/gates/bf-983-1676.receipt.json`.

**Captain:** nothing here meets a Captain condition. Item 6 keeps the status quo (report-only), and the Captain may overrule it after the fact. Item 5's wire-contract change is not made here; it moves to #1658.

---

## 0. Premise: what is present on this tree

| Fact | Where |
|---|---|
| The consultation handler builds `LLMRequest(system_prompt=..., user_message=..., tier="fast")` | `cognitive/cognitive_agent.py:8958-8962` |
| `LLMRequest` has no `user_message`, and its `prompt` has no default | `types.py:306-312` |
| The `TypeError` is caught, logged as "AD-594: LLM call failed for consultation by %s; providing fallback" and answered with confidence 0.2 | `cognitive_agent.py:8971-8979` |
| The handler is registered by `set_consultation_protocol`; startup calls it for every agent | `cognitive_agent.py:1735-1739`; `startup/finalize.py:6063-6064` |
| `handle_consultation_request` (stop check, admission hold) delegates to `_answer_consultation` (AD-1346 M3d2) | `cognitive_agent.py:8888-8915`, `:8917-8995` |
| `consult` → `protocol.request_consultation` is the only route in; nothing in `src/probos` calls `.consult(` | `cognitive_agent.py:8997-9069`; AV1 |
| The real client reports a refused or failed call as `LLMResponse(content="", error=...)`, not as an exception | `cognitive/llm_client.py:1537-1539`, `:2027-2028`, `:2097-2101` |
| The AD-1152 golden's `default_config_sha256` was refreshed 14 times after its capture (`b29dd37a`) | `git log -p -- tests/fixtures/ad1152_agentic_off_golden.json` (§11) |
| The lineage document calls the golden immutable and says only AD-1152's own leaf is removed | `docs/development/agentic-event-correlation.md:133-139` |
| The generator keys `seen` on the leaf name and uses that name as the heading | `scripts/gen_config_reference.py:138-144`, `:184` |
| Three sections are missing because of that key: `security.memory`, `proactive_cognitive.duty_schedule` and the **top-level** `discovery` (AD-708e) | §11 AV11; `config.py:2974`, `:3220`, `:4145` |
| The reference is pinned by `--check` in a test and in the gate | `tests/test_config_reference_current.py:41-59`; `scripts/run_test_gate.py:1101` |

## 1. Problem

**Item 2.** Every AD-594 consultation raises `TypeError` while building its LLM request, so the expert always answers "I did not complete a full analysis…" with confidence 0.2. The path is dormant: no production code calls `consult` (AV1). It becomes reachable as soon as anything does. A second defect sits behind the first. A response the client marks failed (`error` set, no text) would be returned as an empty answer with confidence 0.6.

**Item 3.** The AD-1152 default-off golden is not the pristine capture its document describes. The config digest has been refreshed 14 times:
- eight config changes between 2026-10-08 and 2026-10-13, absorbed by refreshing the digest with no line in the test;
- six later changes: deletions in BF-924, BF-926, AD-1270 slice 4c (×2) and BF-962/963, and BF-937's changed default.

The issue's premise that "every added field is popped" holds only from AD-1206 onward. A deleted field still leaves no trace in the test. The working rule (refresh by measurement, one-key diff: `prompts/ad-1327-…:1845`, `prompts/bf-962-963-…:1149-1153`) is written only in prompts. The next author never reads those.

**Item 4.** `_describe_model` skips any model whose leaf name an earlier section already used, and it heads each section with that leaf name. This omits three sections, not one: `security.memory` (`MemorySecurityConfig`, the `enforce_*` flags), `proactive_cognitive.duty_schedule` (`DutyScheduleConfig`) and the top-level `discovery` (`DiscoveryConfig`, AD-708e LAN mDNS). It also leaves 32 nested sections headed by an ambiguous leaf name.

## 2. Solution overview

1. **Item 2.** Build the request with `prompt=` and keep `system_prompt` and `tier="fast"` as they are. Treat a response with `error` set, or with no text, as a failed call: it raises inside the existing `try`, so the one fallback path answers it (DRY).
2. **Item 3.** One rule, written where the next author lands, which is the test's own failure message and `_off_observation`:
   - an added field is popped with its default asserted;
   - a deleted field or a changed default leaves a line that names it, and the digest is refreshed by measurement.

   The deletions and the changed default since BF-924 are backfilled as such lines. The document is corrected. **The golden file does not change.**
3. **Item 4.** The dotted path from `SystemConfig` is both the key and the heading. The `seen` set is removed, because a path cannot repeat. A new test pins one heading per model path, in order.
4. **Item 1.** The resolver docstring gains (f) and (g) and (a)'s `__call__` reach, so all seven limitations are disclosed with their directions.

Heavier designs rejected (one line each):
- **Item 2:** add `agent_id`/AD-1324 routing, or parse the model's self-rated confidence. Both change behaviour of a path nobody calls; they are feature work (register R-B3-1).
- **Item 3:** re-insert deleted defaults and restore the pristine digest. That needs a reverse migration of 14 refreshes, and each future deletion would add a dead key to a frozen test (BF-962/963 already rejected it).
- **Item 4:** path key with leaf headings (three duplicate headings and colliding anchors); key by model class (still drops a class used at a second path, and the name stays ambiguous).

## 3. Decisions

- **D1 (item 2, the request).** `prompt=user_message`. `system_prompt` and `tier="fast"` are unchanged. Nothing else is added.
- **D2 (item 2, a failed response).** `getattr(llm_response, "error", None)` or blank text raises `RuntimeError` inside the `try`. The existing WARNING (with `exc_info`) and the 0.2 fallback answer it. `getattr` matches the line above it, which already allows a non-`LLMResponse` return (`str(llm_response)`).
- **D3 (item 3, the rule).** Added field: pop it with its default asserted (unchanged). Deleted field: `assert "<key>" not in <section>`. Changed default: assert the new value. For both of these, refresh `default_config_sha256` and then `observation_sha256` by measurement, never by re-capture. The rule lives in three places:
  - `_DEFAULT_CONFIG_RULE`, the failure message of the `default_config_sha256` comparison (what the next author sees);
  - the comment at the backfilled lines;
  - the document.
- **D4 (item 3, backfill).** Lines for every deletion and changed default since BF-924 (§7.3 pair 2). The October changes absorbed by refresh are not backfilled; the document lists them (register R-B3-2).
- **D5 (item 4, key and heading).** The dotted path. `_INTRO_BY_SECTION` keys are top-level names and are unchanged. The header gains one sentence explaining the path headings.
- **D6 (item 4, the pin).** It stays `--check` (test plus gate preflight). The new test pins structure (one heading per model path, in order) independently of the generator.
- **D7 (item 1).** Accepted as disclosed. The docstring lists (a) to (g) with their directions.
- **D8 (item 5).** No change here; it moves to #1658 (§8.3 note). **D9 (item 6).** The check stays report-only (§8.3).

## 4. Milestones and focused gates

Run each focused gate with `d:/ProbOS/.venv/Scripts/pytest.exe -n 0`. Stage explicit paths only; never `git add -A`. Write M1's and M3's new tests first and run them on the milestone's base; §6 names what fails there. If a test outside these lists fails, stop and report it. Never delete or loosen a test.

| M | Files (§7) | Focused gate (re-derived by Grep, AV12) |
|---|---|---|
| **M1** | 7.1 `src/probos/cognitive/cognitive_agent.py`; 7.2 new `tests/test_ad594_consultation_reaches_the_llm.py` | `tests/test_ad594_consultation_reaches_the_llm.py tests/test_ad594b_consult_primitive.py tests/test_ad594_consultation_protocol.py tests/test_ad1343_agent_stop.py tests/test_ad1343_stop_crossing.py tests/test_ad1343_stop_seam_inventory.py tests/test_ad1346_admission_shadow_seams.py tests/test_ad1346_admission_ticket_issue.py tests/test_bf925_guard_names.py tests/test_ad1270b_architecture_fitness.py` |
| **M2** | 7.3 `tests/test_ad1152_agentic_correlation.py`; 7.4 `docs/development/agentic-event-correlation.md`; 7.5 `tests/test_bf927_boot_claims.py` | `tests/test_ad1152_agentic_correlation.py tests/test_bf927_boot_claims.py` |
| **M3** | 7.6 `scripts/gen_config_reference.py`; 7.7 `tests/test_config_reference_current.py`; 7.8 generated `docs/development/config-reference.md` | `tests/test_config_reference_current.py tests/test_ad1270_boot_camp_orientation.py tests/test_ad1155_loop_until_done.py::test_the_config_reference_documents_the_four_way_worst_case "tests/test_ad1154_approval_inbox.py" -k "config_reference or not config_reference"` (whole file; it is the only pin of `## \`approval_inbox\``) `tests/test_run_test_gate.py`; then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_config_reference.py --check` |
| **M4** | 7.9 `PROGRESS.md`, `DECISIONS.md`; the ledger pair | `tests/test_ad1184_ad_ledger.py`; `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check` |

**Expected counts** (the orchestrator measures each base and corrects):
- M1 = base of the nine existing files + **5** (the new file: C1, C2 ×3, C3, C4 = 6 cases; see §6, so **+6**).
- M2 = base + 0: no new case; the AD-1152 file's cases are unchanged in number.
- M3 = base + **1**.
- M4 = base.
- No new skips.

### 5. Commit messages
- M1: `BF-983 M1: an AD-594 consultation builds its LLM request with prompt and falls back on a failed response (#1676 item 2)`
- M2: `BF-983 M2: the AD-1152 golden names its deleted fields and says how it is refreshed; the boot-claims resolver discloses all seven limits (#1676 items 3 and 1)`
- M3: `BF-983 M3: the config reference heads each section with its path, so security.memory, proactive_cognitive.duty_schedule and discovery appear (#1676 item 4)`
- M4: `BF-983 M4: trackers (#1676)`

Each ends with `Refs #1676.` and the attribution lines.

## 5. Consumers of every value this changes

| Value | Consumers | Effect |
|---|---|---|
| `_answer_consultation`'s answer, confidence and reasoning | `ConsultationProtocol.request_consultation` (`consultation.py:221-288`): in-memory `_completed` and the `CONSULTATION_COMPLETED` event (persisted, `event_persistence.py:194`, confidence only). Reached only through `consult` (AV1) and the tests that drive the handler | Once a caller exists: the LLM's text at 0.6 instead of the fallback at 0.2. Today nothing changes in production |
| The consultation's LLM call | The agent's `_llm_client`, which is the runtime's shared client (`runtime.py:1022` and others), fast tier, under its per-tier rate limit (`llm_client.py:1531-1539`). No `agent_id`, so AD-1324 routing correlation stays unarmed | One fast-tier call per consultation, previously zero. Bounded by the protocol (20 per requester per hour, 10 pending, 30 s timeout: `consultation.py:126-128`) |
| The admitted consultation on a booted runtime with `MockLLMClient` | `test_ad1346_admission_ticket_issue.py::test_with_the_switch_on_and_off_the_issue_points_answer_byte_identically` (`:527-548`, `_drive_issue_points` `:231-239`) | Its JSON now holds the mock's answer and 0.6 in both runs. The test compares on against off, not against a fixture, so it holds if the mock is deterministic (P7) |
| `_DEFAULT_CONFIG_RULE`; the backfilled lines | `test_default_off_matches_pinned_base` only | Reads only; the hashed dict is not mutated; the golden is unchanged |
| `_describe_model(path, model)` (the `seen` parameter is removed) | Called only inside the script (AV5) | Internal |
| `config-reference.md` headings | Tests pin top-level headings only (`approval_inbox`, `boot_camp`, `agentic_loop`, `agentic_tools`, `records`, `consensus`, `memory`); no anchor links (AV4); mkdocs nav links the page (`mkdocs.yml:94`) | 32 nested headings and their mkdocs anchors change (R-B3-3) |

## 6. Tests

New file `tests/test_ad594_consultation_reaches_the_llm.py` (M1). Real `CognitiveAgent` methods (built without `__init__`, as `tests/test_ad594b_consult_primitive.py:28-37` does), the real `ConsultationProtocol`, and a `BaseLLMClient` subclass.

| # | Test | Proves | On the base |
|---|---|---|---|
| C1 | `test_a_consultation_reaches_the_experts_llm_and_returns_its_answer` | The whole seam: `consult` → protocol → the expert's registered handler → its LLM. The request carries `prompt`, the system prompt and `tier="fast"`. The answer is the LLM's text, 0.6, "Consulted on …". No fallback is logged | Fails at its first assertion after the premise: the fallback records' exception names are `['TypeError']` (the reproduction) |
| C2 | `test_a_response_that_carries_an_error_or_no_text_is_the_low_confidence_fallback[error-response, error-with-text, empty-answer]` | D2: an `error` response, or one with blank text, answers the fallback at 0.2 with one WARNING whose exception is `RuntimeError` | All three fail at `len(llm.requests) == 1` (0: the `TypeError` came first) |
| C3 | `test_an_llm_client_that_raises_is_the_low_confidence_fallback` | A raising client: fallback 0.2, WARNING with `ConnectionError` | Fails at `len(llm.requests) == 1` |
| C4 | `test_with_no_llm_client_the_answer_says_so` | The no-client branch: 0.1, "No LLM client available" (the None boundary) | Passes (a guard) |

M2 adds no test function:
- The backfilled lines are assertions inside `_off_observation`, so the three AD-1152 cases that call it run them.
- The changed failure message is exercised by mutation row E-5.
- 7.5 changes a docstring only.

M3 adds one test to `tests/test_config_reference_current.py`: **R1** `test_every_model_has_one_section_headed_by_its_path`. It walks `SystemConfig` independently of the generator and asserts that the committed doc's `## \`…\`` headings equal the model paths, in order. On the base it fails at the first nested heading: `'attention'` against `'memory.attention'`.

## 7. The contract

### 7.1 `src/probos/cognitive/cognitive_agent.py` (M1)

SEARCH:
```python
        """``handle_consultation_request``'s work past its stop check, moved here by AD-1346 M3d2, unchanged but for this
        import, so that its ticket ends in one ``finally``."""
```
REPLACE:
```python
        """``handle_consultation_request``'s work past its stop check, moved here by AD-1346 M3d2, unchanged but for this
        import, so that its ticket ends in one ``finally``. BF-983 (#1676) builds its LLM request with ``prompt`` (it raised
        ``TypeError`` before) and answers the fallback for a response that carries an error or no text."""
```

SEARCH:
```python
                llm_request = LLMRequest(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    tier="fast",
                )
                llm_response = await llm.complete(llm_request)
                answer = (
                    llm_response.content
                    if hasattr(llm_response, "content")
                    else str(llm_response)
                )
                confidence = 0.6
```
REPLACE:
```python
                llm_request = LLMRequest(
                    prompt=user_message,  # BF-983 (#1676): LLMRequest's field; it has no user_message
                    system_prompt=system_prompt,
                    tier="fast",
                )
                llm_response = await llm.complete(llm_request)
                answer = (
                    llm_response.content
                    if hasattr(llm_response, "content")
                    else str(llm_response)
                )
                # BF-983 (#1676): the client answers a refused or failed call (a rate limit, every tier unavailable) with
                # ``error`` set and no text rather than raising, so that response takes the fallback below as well.
                if getattr(llm_response, "error", None) or not str(answer).strip():
                    raise RuntimeError(f"no usable answer: {getattr(llm_response, 'error', None) or 'empty content'}")
                confidence = 0.6
```

### 7.2 New file: `tests/test_ad594_consultation_reaches_the_llm.py` (M1)

```python
"""BF-983 (#1676 item 2): an AD-594 consultation reaches the expert's LLM and comes back with its answer.

``_answer_consultation`` built ``LLMRequest(user_message=...)``. ``LLMRequest`` has no such field and its ``prompt`` has
no default, so every consultation raised ``TypeError`` inside the handler's ``try`` and answered the low-confidence
fallback. C1 crosses the whole seam: ``consult`` on one agent, the real ``ConsultationProtocol``, the other agent's
registered handler and its LLM client. The client is a ``BaseLLMClient`` subclass that keeps each request. Each agent is
built without its ``__init__``, as ``tests/test_ad594b_consult_primitive.py`` builds one, and holds no runtime, so no
stop service and no admission service take part.
"""

from __future__ import annotations

import logging

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.consultation import ConsultationProtocol, ConsultationRequest
from probos.cognitive.llm_client import BaseLLMClient
from probos.types import LLMRequest, LLMResponse, Priority

_AGENT_LOGGER = "probos.cognitive.cognitive_agent"
_FALLBACK_LOG = "AD-594: LLM call failed for consultation by %s; providing fallback"
_QUESTION = "How stable is the warp core?"
_FALLBACK_ANSWER = "I did not complete a full analysis of 'Warp core' at this time."


class _ExpertLLM(BaseLLMClient):
    """Answers every request with one scripted response, or raises one error, and keeps each request."""

    def __init__(self, response: LLMResponse | None = None, error: Exception | None = None) -> None:
        self.requests: list[LLMRequest] = []
        self._response = response
        self._error = error

    async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def _agent(agent_id: str, callsign: str, llm: BaseLLMClient | None) -> CognitiveAgent:
    """A CognitiveAgent holding only what the consultation paths read: id, type, callsign, LLM client, protocol."""
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent.id = agent_id
    agent.agent_type = "test_agent"
    agent.callsign = callsign
    agent._llm_client = llm
    agent._consultation_protocol = None
    return agent


def _fallbacks(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == _AGENT_LOGGER and r.msg == _FALLBACK_LOG]


def _request() -> ConsultationRequest:
    return ConsultationRequest(requester_id="requester-1", topic="Warp core", question=_QUESTION, target_agent_id="expert-1")


async def test_a_consultation_reaches_the_experts_llm_and_returns_its_answer(caplog: pytest.LogCaptureFixture) -> None:
    """C1: requester.consult -> ConsultationProtocol -> expert.handle_consultation_request -> the expert's LLM."""
    caplog.set_level(logging.WARNING, logger=_AGENT_LOGGER)
    llm = _ExpertLLM(LLMResponse(content="Stable within tolerance."))
    protocol = ConsultationProtocol()
    expert = _agent("expert-1", "Expert", llm)
    requester = _agent("requester-1", "Asker", None)
    expert.set_consultation_protocol(protocol)
    requester.set_consultation_protocol(protocol)

    response = await requester.consult(_QUESTION, target_agent_id="expert-1")

    assert response is not None  # premise: the protocol routed the request to the expert's handler
    assert [r.exc_info[0].__name__ for r in _fallbacks(caplog) if r.exc_info] == []  # the base logs TypeError here
    assert len(llm.requests) == 1
    sent = llm.requests[0]
    assert sent.prompt == _QUESTION
    assert "You are Expert, responding to an expert consultation." in sent.system_prompt
    assert f"Question: {_QUESTION}" in sent.system_prompt
    assert sent.tier == "fast"
    assert response.responder_id == "expert-1"
    assert response.answer == "Stable within tolerance."
    assert response.confidence == 0.6
    assert response.reasoning_summary == f"Consulted on {_QUESTION}"
    assert _fallbacks(caplog) == []


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(LLMResponse(content="", error="LLM rate limit exceeded for tier fast"), id="error-response"),
        pytest.param(LLMResponse(content="Stable within tolerance.", error="stream interrupted"), id="error-with-text"),
        pytest.param(LLMResponse(content="   "), id="empty-answer"),
    ],
)
async def test_a_response_that_carries_an_error_or_no_text_is_the_low_confidence_fallback(
    response: LLMResponse, caplog: pytest.LogCaptureFixture,
) -> None:
    """C2 (D2): the client reports a failed call as a response, not an exception; it is answered as a failed call."""
    caplog.set_level(logging.WARNING, logger=_AGENT_LOGGER)
    llm = _ExpertLLM(response)
    expert = _agent("expert-1", "Expert", llm)

    answer = await expert.handle_consultation_request(_request())

    assert len(llm.requests) == 1  # premise: the LLM was reached (on the base the request raised TypeError first)
    assert answer.answer == _FALLBACK_ANSWER
    assert answer.confidence == 0.2
    assert answer.reasoning_summary == "LLM call failed; low-confidence fallback response"
    [record] = _fallbacks(caplog)
    assert record.exc_info is not None and record.exc_info[0] is RuntimeError


async def test_an_llm_client_that_raises_is_the_low_confidence_fallback(caplog: pytest.LogCaptureFixture) -> None:
    """C3: a client that raises is answered by the same fallback, with its own exception logged."""
    caplog.set_level(logging.WARNING, logger=_AGENT_LOGGER)
    llm = _ExpertLLM(error=ConnectionError("provider unreachable"))
    expert = _agent("expert-1", "Expert", llm)

    answer = await expert.handle_consultation_request(_request())

    assert len(llm.requests) == 1  # premise: the LLM was reached
    assert answer.answer == _FALLBACK_ANSWER
    assert answer.confidence == 0.2
    [record] = _fallbacks(caplog)
    assert record.exc_info is not None and record.exc_info[0] is ConnectionError


async def test_with_no_llm_client_the_answer_says_so() -> None:
    """C4: no client on the agent and no runtime: the no-LLM answer, unchanged by BF-983 (a guard)."""
    expert = _agent("expert-1", "Expert", None)

    answer = await expert.handle_consultation_request(_request())

    assert answer.confidence == 0.1
    assert answer.reasoning_summary == "No LLM client available"
```

### 7.3 `tests/test_ad1152_agentic_correlation.py` (M2)

SEARCH:
```python
BASE_COMMIT = "7dd9542289fbe3b574b09f4e9b5fe934c35f424c"
GOLDEN_PATH = Path(__file__).parent / "fixtures" / "ad1152_agentic_off_golden.json"
```
REPLACE:
```python
BASE_COMMIT = "7dd9542289fbe3b574b09f4e9b5fe934c35f424c"
GOLDEN_PATH = Path(__file__).parent / "fixtures" / "ad1152_agentic_off_golden.json"
# BF-983 (#1676): what the next author does when the default configuration's digest no longer matches the golden.
_DEFAULT_CONFIG_RULE = (
    "default_config_sha256: the default SystemConfig dump changed. An added field: pop it in _off_observation with its "
    "default asserted; the golden stays. A deleted field or a changed default: add a line in _off_observation that "
    "names it (assert the key is absent, or assert its new value), then refresh by measurement: run "
    "test_default_off_matches_pinned_base with -n 0, confirm default_config_sha256 is the only key that differs, copy "
    "the actual digest into the golden's observation.default_config_sha256, run again and copy the reported "
    "observation digest into observation_sha256. Never re-capture the golden. "
    "See docs/development/agentic-event-correlation.md, 'Validation lineage'."
)
```

SEARCH:
```python
    assert config["records"].pop("git_last_commit_warn_hours") == 24.0
    runtime = _local_runtime()
```
REPLACE:
```python
    assert config["records"].pop("git_last_commit_warn_hours") == 24.0
    # Deleted fields and changed defaults (BF-983, #1676). Each one moved the digest, which was refreshed by measurement
    # (_DEFAULT_CONFIG_RULE); the line names what the pinned digest no longer contains, or now contains.
    # BF-924 (#1654) removed the Counselor's four unread fields.
    assert not {"enabled", "profile_retention_days", "alert_on_red", "alert_on_yellow"} & set(config["counselor"])
    # BF-926 (#1656) deleted AD-607d's leak-guard flag.
    assert "enforce_leak_guard" not in config["security"]["memory"]
    # AD-1270 slice 4c (#1324) deleted AD-509's phase-tracker section, then boot camp's nudge cooldown.
    assert "boot_camp_phase" not in config
    assert "nudge_cooldown_seconds" not in config["boot_camp"]
    # BF-962/963 (#1792) deleted the unread orientation flag.
    assert "populate_ward_room_department" not in config["orientation"]
    # BF-937 (#1678) changed a default: promoted agents go to {data_dir}/promoted-agents, never the source checkout.
    assert config["self_improvement"]["persistence_root_dir"] == ""
    runtime = _local_runtime()
```

SEARCH:
```python
    actual = await _off_observation(tmp_path, monkeypatch)
    for key, expected in golden["observation"].items():
        assert actual[key] == expected, key
```
REPLACE:
```python
    actual = await _off_observation(tmp_path, monkeypatch)
    for key, expected in golden["observation"].items():
        assert actual[key] == expected, (_DEFAULT_CONFIG_RULE if key == "default_config_sha256" else key)
```

### 7.4 `docs/development/agentic-event-correlation.md` (M2)

SEARCH:
```markdown
The immutable [OFF golden](../../tests/fixtures/ad1152_agentic_off_golden.json)
was captured with production files still pristine at
`7dd9542289fbe3b574b09f4e9b5fe934c35f424c`, before production edits. It contains
the base source blob IDs, deterministic requests/results/events, seven
constructor calls, raw SQLite metadata, reopened API output and associated
hashes. Only the new default-False config leaf is removed before comparing the
pre-existing default configuration digest.
```
REPLACE:
```markdown
The [OFF golden](../../tests/fixtures/ad1152_agentic_off_golden.json)
was captured with production files still pristine at
`7dd9542289fbe3b574b09f4e9b5fe934c35f424c`, before production edits. It contains
the base source blob IDs, deterministic requests/results/events, seven
constructor calls, raw SQLite metadata, reopened API output and associated
hashes. The capture is never regenerated. Later work refreshes three kinds of
value in it by measurement, and nothing else: the default configuration digest
(`observation.default_config_sha256`), the observation text that embeds the
native builder's composed standing orders (BF-936, AD-1359), and the shape of
the work item in the reopened API output (AD-1321 added four keys that hold
null). `observation_sha256`, the digest of the whole observation, follows any of
them. A refresh runs the test's own `_off_observation` on the changed tree and
copies only the values that moved; for a config change, that is one key.

**When the default configuration changes** (#1676). An added field is popped in
`_off_observation` with its default asserted, so the digest stays. A deleted
field, or a changed default, leaves a line in `_off_observation` that names it
(the key is absent, or has its new value), and the digest is refreshed by
measurement. The test's failure message for `default_config_sha256` repeats
this rule. A deleted field's old default is not re-inserted to keep an old
digest: the digest stopped being the pristine one on 2026-10-08.

The golden has been refreshed 17 times since the capture
(`git log -- tests/fixtures/ad1152_agentic_off_golden.json`): 14 times for the
default configuration digest, twice for the composed standing orders and once
for the work-item shape. Eight of the 14 were config changes between 2026-10-08
and 2026-10-13 (the Sonnet 5.5 defaults, budget awareness, AD-1315, AD-1322 to
AD-1325 and AD-1327), absorbed with no line in the test. The other six are named
in the test since #1676: the deletions of BF-924, BF-926, AD-1270 slice 4c (two)
and BF-962/963, and BF-937's changed default.
```

### 7.4b `docs/development/agentic-event-correlation.md` (M2)

SEARCH:
```markdown
The observation SHA-256 is
`3a95dbc861da39ef946143029abaeb431820b237747ce95a984c55ce732497f3`.
An initial non-deterministic capture was rejected, not used as an oracle.
```
REPLACE:
```markdown
The observation SHA-256 of the initial capture was
`3a95dbc861da39ef946143029abaeb431820b237747ce95a984c55ce732497f3`; every
refresh above changes it, and the golden's `observation_sha256` holds the
current value.
An initial non-deterministic capture was rejected, not used as an oracle.
```

### 7.5 `tests/test_bf927_boot_claims.py` (M2, docstring only)

SEARCH:
```python
(a) Silent: a typed parameter is keyed by its callable's short name (the class for ``__init__``)
and the parameter name, so a keyword hand-off to another callable with the same two names is
exempt as if typed.
```
REPLACE:
```python
(a) Silent: a typed parameter is keyed by its callable's short name (the class for ``__init__``)
and the parameter name, so a keyword hand-off to another callable with the same two names is
exempt as if typed. Since A5 this reaches the ``.__call__`` spelling too
(``lookup.submit.__call__(gate=runtime.gate)`` reads as ``lookup.submit(gate=runtime.gate)``).
```

SEARCH:
```python
(e) Loud: a Python 3.12 type parameter (``def f[getattr]()``) is not collected as a binding, so a
builtin of that name stays trusted in its module and can count a false caller.
"""
```
REPLACE:
```python
(e) Loud: a Python 3.12 type parameter (``def f[getattr]()``) is not collected as a binding, so a
builtin of that name stays trusted in its module and can count a false caller.
(f) Silent: a decorator application is not indexed as a call (only explicit ``ast.Call`` nodes
are), so ``@runtime.threat_detector.scan`` above a ``def`` invokes the entry at decoration time
unseen (#1676 counted 3,208 production decorators, none spelled as an entry).
(g) Silent: a holder reached through the ``__self__`` of a non-entry bound method handed on
(``sink(holder.reset)``, listed under "cannot see" above) is not traced, so a call made through
it is not counted.
These seven stay disclosed rather than fixed (#1676 item 1): the resolver is test machinery with
no production reach, and the 12 production states it pins are unchanged.
"""
```

### 7.6 `scripts/gen_config_reference.py` (M3)

SEARCH:
```python
ProbOS runs with **zero configuration** — every field has a default. The
shipped `config/system.yaml` deliberately does not list every knob; this page
does.
```
REPLACE:
```python
ProbOS runs with **zero configuration** — every field has a default. The
shipped `config/system.yaml` deliberately does not list every knob; this page
does.

Each section is headed by its dotted path from the root: `security.memory` is
the `memory` block inside `security`, nested the same way in YAML.
```

SEARCH:
```python
def _describe_model(name: str, model: type, seen: set[str]) -> list[str]:
    """Render one Pydantic model as a markdown section, recursing into children."""
    if name in seen:
        return []
    seen.add(name)

    lines = [f"## `{name}`", ""]
    intro = _INTRO_BY_SECTION.get(name)
```
REPLACE:
```python
def _describe_model(path: str, model: type) -> list[str]:
    """Render one Pydantic model as a markdown section headed by its dotted path, then each nested model.

    BF-983 (#1676): the path is the heading, so every model-typed field at every path has its own section. A ``seen``
    set keyed on the field name used to leave out a model whose name an earlier section had used: ``security.memory``
    after ``memory``, ``proactive_cognitive.duty_schedule`` after ``duty_schedule``, and the top-level ``discovery``
    after ``federation.discovery``. A path cannot repeat, so nothing is skipped. No config model is recursive; one
    that were would raise ``RecursionError`` here rather than drop a section.
    """
    lines = [f"## `{path}`", ""]
    intro = _INTRO_BY_SECTION.get(path)
```

SEARCH:
```python
    for child_name, child_model in nested:
        lines += _describe_model(child_name, child_model, seen)
```
REPLACE:
```python
    for child_name, child_model in nested:
        lines += _describe_model(f"{path}.{child_name}", child_model)
```

SEARCH:
```python
    lines = [_HEADER]
    seen: set[str] = set()
    for field_name, field in SystemConfig.model_fields.items():
        annotation = field.annotation
        if hasattr(annotation, "model_fields"):
            lines += _describe_model(field_name, annotation, seen)
```
REPLACE:
```python
    lines = [_HEADER]
    for field_name, field in SystemConfig.model_fields.items():
        annotation = field.annotation
        if hasattr(annotation, "model_fields"):
            lines += _describe_model(field_name, annotation)
```

### 7.7 `tests/test_config_reference_current.py` (M3)

SEARCH:
```python
    text = _DOC.read_text(encoding="utf-8")
    assert "tool_result_max_chars" in text
    assert "unbounded" in text.lower()
```
REPLACE:
```python
    text = _DOC.read_text(encoding="utf-8")
    assert "tool_result_max_chars" in text
    assert "unbounded" in text.lower()


def _model_paths(model: type, prefix: str = "") -> list[str]:
    """Each model-typed field's dotted path below ``model``, depth first in declaration order."""
    paths: list[str] = []
    for name, field in model.model_fields.items():
        if hasattr(field.annotation, "model_fields"):
            path = f"{prefix}{name}"
            paths += [path, *_model_paths(field.annotation, f"{path}.")]
    return paths


def test_every_model_has_one_section_headed_by_its_path() -> None:
    """BF-983 (#1676 item 4): one section per model-typed field at every path, headed by that path, in model order.

    The generator keyed a ``seen`` set on the field name, so a model whose name an earlier section had used was left
    out: ``security.memory`` (after ``memory``), ``proactive_cognitive.duty_schedule`` (after ``duty_schedule``) and
    the top-level ``discovery`` (after ``federation.discovery``). This walk reads the models, not the generator.
    """
    from probos.config import SystemConfig

    paths = _model_paths(SystemConfig)
    assert {  # premise: the three colliding names exist at both of their paths
        "memory", "security.memory", "duty_schedule", "proactive_cognitive.duty_schedule",
        "federation.discovery", "discovery",
    } <= set(paths)
    headings = [
        line[len("## `"):-1]
        for line in _DOC.read_text(encoding="utf-8").splitlines()
        if line.startswith("## `") and line.endswith("`")
    ]
    assert headings == paths
```

### 7.8 Generated: `docs/development/config-reference.md` (M3)

Not pasted. After 7.6, run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_config_reference.py`, then `… --check`. **Check the diff** (`git diff -U0 docs/development/config-reference.md`); it must contain exactly the following:

1. **The header.** Two added lines plus one blank line (the sentence in 7.6 pair 1).
2. **32 renamed headings**, each a `-## \`leaf\`` / `+## \`path\`` pair with no other line changed:
   - `memory.attention`
   - `federation.mcp_server`, `federation.a2a`, `federation.ard`, `federation.peer_trust`, `federation.tls`, `federation.discovery`, `federation.cluster_monitor`
   - `execution.command_policy`
   - `security.permissions`
   - `duty_schedule.work_hours`, `duty_schedule.quiet_hours`
   - `proactive_scan.inbox`, `proactive_scan.calendar`
   - `channels.discord`, `channels.slack`, `channels.webhook`
   - `browser_tool.credential_vault`
   - `avatars.baseline_vrms`
   - `avatar_telemetry.sampling_rates`
   - `dm_agentic.economic_judgment`, `dm_agentic.economic_judgment.completion_calibration`, `dm_agentic.economic_judgment.continue_extension`, `dm_agentic.economic_judgment.tier_choice`
   - `cloud_pickers.google_drive`, `cloud_pickers.onedrive`, `cloud_pickers.dropbox`
   - `perception.camera`, `perception.screen`
   - `qualification.communication_benchmarks`
   - `naval_organization.captains_log`, `naval_organization.plan_of_day`
3. **Three added sections, nothing else added:**
   - `## \`security.memory\`` between `security`'s table and `## \`security.permissions\``. Its summary is "AD-607: Memory security framework configuration." It has 5 rows: `enforce_recall`, `enforce_provenance`, `enforce_store`, `anchor_mismatch_threshold` (≥ 0.0, ≤ 1.0), `dp_min_cohort_size` (≥ 1).
   - `## \`proactive_cognitive.duty_schedule\`` directly after `proactive_cognitive`'s table. Its summary is "Duty schedule definitions per agent type (AD-419)." It has 3 rows: `enabled`, `schedules`, `use_work_items`.
   - `## \`discovery\`` last, after `## \`desktop\``. Its summary is "AD-708e: LAN mDNS service advertisement for PADD discovery (#484)." It has 5 rows: `enabled`, `service_type`, `hostname`, `instance_name`, `txt_path`.
4. **No other removed line.** Every `-` line in the hunk set is one of the 32 old headings. No section moves except by those insertions. The heading count goes from 225 to 228.

If the diff shows anything else, stop: a model this contract did not enumerate has changed.

### 7.9 Trackers (M4)

**`PROGRESS.md`:**

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-983 (DATE), #1676 -- an AD-594 consultation reaches the LLM, the AD-1152 golden says how it is refreshed, and the config reference has a section for every path.**
- **Consultation (item 2).** `_answer_consultation` built `LLMRequest(user_message=...)`, which raised `TypeError` on every call, so every consultation answered the 0.2 fallback. It now sends `prompt=`, and a response the client marks failed (`error` set) or that has no text takes the same fallback. Dormant: nothing in `src/probos` calls `consult`. New `tests/test_ad594_consultation_reaches_the_llm.py` crosses consult, protocol, handler and LLM.
- **AD-1152 golden (item 3).** The rule for a default-config change is now in the test's failure message and the lineage document: an added field is popped, while a deleted field or a changed default leaves a named line and the digest is refreshed by measurement. Lines for the deletions and the changed default since BF-924 are added; the golden itself is unchanged. The document no longer calls the golden immutable: its config digest has been refreshed 14 times.
- **Config reference (item 4).** Sections are keyed and headed by their dotted path. `security.memory`, `proactive_cognitive.duty_schedule` and the top-level `discovery` were missing because an earlier section used the same name; 32 nested headings now show their paths. A new test pins one heading per model path.
- **Dispositions.** Item 1: the boot-claims resolver's docstring lists all seven limitations with their directions. Item 5 moves to #1658. Item 6: the config-reader check stays report-only. Contract `prompts/bf-983-1676-consultation-golden-config-reference.md`.
```

**`DECISIONS.md`:**

SEARCH:
```markdown
### A judged withdrawal is recorded apart from a lost action, with its reason, and a retried think settles once (2026-11-17, #1807)
```
REPLACE:
```markdown
### BF-983 -- #1676: an AD-594 consultation reaches the LLM, the AD-1152 golden's refresh rule, a config reference section per path (DATE, #1676)

- *Consultation request.* `prompt=` replaces the field `LLMRequest` never had. A response with `error` set or no text is a failed call, because the client reports rate limits and unavailable tiers that way rather than raising. Rejected for now: `agent_id` routing correlation and parsing the model's self-rated confidence, which are feature work on a path nothing calls.
- *Golden refresh rule.* An added default field is popped with its default asserted. A deleted field or a changed default leaves a line that names it, and the digest is refreshed by measurement, never re-captured. Rejected: re-inserting a deleted field's old default to keep a pristine digest. The digest had been refreshed 14 times, and each deletion would leave a dead key in a frozen test.
- *Config reference key.* The dotted path is the key and the heading. Rejected: path key with leaf headings (duplicate `memory`, `duty_schedule` and `discovery` headings), and keying by model class (still drops a class used at a second path).
- *Config-reader check.* It stays report-only. Under-reporting from a check that gates nothing costs no build. A version that resolves each read to its owning model comes first if the Captain decides to enforce it.
- *Reversal.* Revert the commits: the consultation raises `TypeError` again, the golden's lines and message go, and the reference returns to leaf headings without the three sections.

### A judged withdrawal is recorded apart from a lost action, with its reason, and a retried think settles once (2026-11-17, #1807)
```

After both edits run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`. It regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`, which go in M4's commit. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`. Set DATE to the commit date. **`roadmap.md`:** no row (the Bug Tracker lists only bugs deliberately not fixed).

## 8. Issue closure (the orchestrator posts these; nothing here edits GitHub)

### 8.1 Checklist update on #1676
Edit the body. Turn each `- [ ] **N.` into `- [x] **N.`, and append one line under **Items**:
`**Dispositions (BF-983, PR #…):** 1 disclosed (docstring (a)–(g)); 2 fixed; 3 fixed (rule + lines; golden unchanged); 4 fixed (path headings; also proactive_cognitive.duty_schedule and top-level discovery); 5 moved to #1658 (note linked); 6 decided: stays report-only.`

### 8.2 Close after the batch merges, only if every item is dispositioned
| Item | Disposition | Condition to close |
|---|---|---|
| 1 | Disclosed (7.5) | M2 merged |
| 2 | Fixed (7.1, 7.2) | M1 merged |
| 3 | Fixed (7.3, 7.4) | M2 merged |
| 4 | Fixed (7.6–7.8) | M3 merged |
| 5 | Moved to #1658 | The §8.3 note is posted on #1658 **before** #1676 closes |
| 6 | Decided | The §8.3 closure text is posted |

### 8.3 Texts

**Item 1 (comment on #1676):**
> Item 1: accepted as disclosed (BF-983). `tests/test_bf927_boot_claims.py`'s docstring now lists all seven limitations, each with its direction against a "not invoked" claim:
> - (a) silent, including the `.__call__` spelling since A5;
> - (b), (c) and (e) loud;
> - (d) loud and silent;
> - (f) silent: decorator applications are not indexed as calls;
> - (g) silent: a holder reached through `__self__`.
>
> The 12 production states are unchanged. The one design that closes all seven (resolve callees, owners and imports to their definitions; bind positional arguments; index decorators; follow `__self__`; collect type parameters) is not scheduled. The resolver is test machinery with no production reach, and the item's acceptance is "fixed, or disclosed with its direction".

**Item 5 (note on #1658):**
> **Added from #1676 item 5 (BF-983 batch).** `GET /api/disclosure-clearances` (`src/probos/routers/system.py:204-213`; the router prefix is `/api`, not `/api/system`) answers `"status": "active"` whenever the AD-679 `DisclosureRouter` is built (`startup/finalize.py:4458-4459`). Nothing in `src/probos` calls its filter: `rg -n "\.filter_permitted\(" src/` finds 0 (it is defined at `mesh/disclosure.py:111`). The router is built but never invoked, the same shape as this issue's producers.
>
> The value is a wire contract: `tests/test_ad679_selective_disclosure_routing.py:114` pins `"active"`, and no HXI code reads the route. When this issue decides, for each uncalled producer, whether it gets a caller (observe-first) or is marked inert, decide this route's value with it:
> - `"active"` stays only if the filter gains a caller;
> - otherwise use a value that says the clearances are configured but not applied, and migrate the pin in the same change.
>
> P3: nothing is disclosed or withheld differently today, because nothing filters.

**Item 6 (comment on #1676):**
> Item 6: decided. `scripts/check_config_readers.py` stays report-only: it exits 0 on every input and is not a gate phase (DECISIONS, BF-926 "Report-only reader check"). It matches names, so it under-reports: `MemorySecurityConfig.dp_min_cohort_size` (`config_models/crew.py:161`) looks read because `FederationConfig.dp_min_cohort_size` is (`agents/federation_recall_agent.py:164`). Under-reporting from a check that gates nothing costs no build. If the Captain decides to enforce the check, that change starts with a version that resolves each read to its owning model. The Captain can overrule this.

## 9. What this does NOT change

- `ConsultationProtocol` (rate limit, expert selection, timeout, events), `consult`, the stop check and admission hold in `handle_consultation_request`, the system prompt text, `tier="fast"`, the 0.6, 0.2 and 0.1 confidences.
- No caller of `consult` is added; the path stays dormant.
- `tests/fixtures/ad1152_agentic_off_golden.json` (no byte), the pop list, `_captured_path_representation`, the other AD-1152 tests.
- The boot-claims resolver's code and its 12 production states.
- `_render_value`, `_format_default`, `_constraints`, `_INTRO_BY_SECTION`, `--check`'s behaviour, `check_config_facade.py`, `config-profiles.yaml`, `config/system.yaml`.
- `routers/system.py` and the AD-679 pin (item 5). `scripts/check_config_readers.py` (item 6).
- No config field, `EventType`, route, table or flag.

## 10. Mutation rows (one campaign on the M3 tree; restore between rows; run only the listed killers)

| # | M | File | Line (stripped, once in its file after §7) | Mutate to | Killed by |
|---|---|---|---|---|---|
| E-1 | M1 | `src/probos/cognitive/cognitive_agent.py` | `prompt=user_message,  # BF-983 (#1676): LLMRequest's field; it has no user_message` | `user_message=user_message,` | C1, C2[error-response], C2[error-with-text], C2[empty-answer], C3 |
| E-2 | M1 | same | `if getattr(llm_response, "error", None) or not str(answer).strip():` | `if False:` | C2 (all three) |
| E-3 | M1 | same | same line | `if not str(answer).strip():` | C2[error-with-text] |
| E-4 | M1 | same | same line | `if getattr(llm_response, "error", None):` | C2[empty-answer] |
| E-5 | M2 | `tests/test_ad1152_agentic_correlation.py` | `assert "enforce_leak_guard" not in config["security"]["memory"]` | `config["security"]["memory"]["enforce_leak_guard"] = False` | `test_default_off_matches_pinned_base` (fails with `_DEFAULT_CONFIG_RULE`), `test_default_off_golden_pins_only_descriptor_owner_platform[linux]`, `[win32]` |
| E-6 | M3 | `scripts/gen_config_reference.py` | `lines += _describe_model(f"{path}.{child_name}", child_model)` | `lines += _describe_model(child_name, child_model)` | `test_the_reference_matches_the_models` |
| E-7 | M3 | same | ``lines = [f"## `{path}`", ""]`` | ``lines = [f"## `{path.rsplit('.', 1)[-1]}`", ""]`` | `test_the_reference_matches_the_models` |
| E-8 | M3 | `docs/development/config-reference.md` | ``## `security.memory` `` | ``## `memory` `` | R1, `test_the_reference_matches_the_models` |

E-5 is the rule's own demonstration: re-inserting a deleted default breaks the refreshed pin instead of restoring it. E-6 and E-7 mutate the script, so R1, which reads the committed doc, does not see them; the `--check` test does. E-8 mutates the committed doc, which R1 pins. No row for:
- the backfilled absence lines (a mutant that drops one passes by design: it is a guard against a re-added name);
- `_DEFAULT_CONFIG_RULE`'s text;
- 7.4 and 7.5 (prose).

## 11. Verified Against Codebase (2026-11-18, `9f43697fd8433071dd0f0afc394fba06de905a0c`)

```
Read src/probos/cognitive/cognitive_agent.py:8888-9069
  8888: async def handle_consultation_request(self, request: Any) -> Any:
  8917: async def _answer_consultation(self, request: Any) -> Any:
  8918-8919: docstring "unchanged but for this / import, so that its ticket ends in one ``finally``."
  8958-8962: llm_request = LLMRequest(system_prompt=..., user_message=user_message, tier="fast",)
  8969: confidence = 0.6 ; 8973: "AD-594: LLM call failed for consultation by %s; providing fallback" ; 8978: confidence = 0.2 ; 8985: confidence = 0.1
  8997: async def consult(  ; 9069: return await protocol.request_consultation(request)
grep -n "set_consultation_protocol" src/probos  -> cognitive_agent.py:1735,1739 ; startup/finalize.py:6063-6064
Read src/probos/types.py:306-331  -> 310: prompt: str  (no default); no user_message field
grep -n "self._llm_client = " cognitive_agent.py -> 1403: self._llm_client = kwargs.get("llm_client")
grep -n "llm_client=self.llm_client" src/probos/runtime.py -> 1022, 1043, 1058, 1073, ...
Read src/probos/cognitive/llm_client.py:246-266 -> class BaseLLMClient(ABC); abstract complete(request, *, priority=Priority.NORMAL)
grep llm_client.py -> 23: from probos.types import LLMRequest, LLMResponse, Priority ; 1537-1539, 2027-2028, 2097-2101: LLMResponse(content="", ..., error=...)
Read src/probos/cognitive/consultation.py:33-288 -> ConsultationRequest defaults (request_id factory, created_at); ConsultationProtocol() no-config defaults 30.0 s/20/10; handler awaited under wait_for; CONSULTATION_COMPLETED carries confidence
grep -n "^logger = " cognitive_agent.py -> 69: logger = logging.getLogger(__name__)
grep -rn "propagate\s*=\s*False" src/probos -> none
Read src/probos/admission/seam.py:40-57 -> shadow_at/hold_at return None/NO_HOLD for a non-AdmissionService
Read tests/test_ad1346_admission_ticket_issue.py:192-195, 224-248, 527-548 -> MockLLMClient boot; on/off byte-identity, no fixture
pyproject.toml:181 asyncio_mode = "auto"
Read tests/test_bf925_guard_names.py:1-19 -> a guard's name must be defined in src (dataclass fields count): LLMResponse.error (types.py:345)

git log -p --format="COMMIT %h" -- tests/fixtures/ad1152_agentic_off_golden.json | grep default_config_sha256
  -> 14 changes: 221705d7, 7aaa3abf, 9d71e934, ebd57eb8, 6f94608b, 091f1143, b84591a6, 42878345, 096bb2cc, e7b7ee71, 7b13bca0, a4c538a0, 36ff39b3, 21f8a0a5; capture b29dd37a; ed0101d9, b647032a, 0debd77b change other lines
git show 091f1143 -- config_models/emergence.py -> removes counselor enabled, profile_retention_days, alert_on_red, alert_on_yellow (CounselorConfig; corrected by the orchestrator)
git show 6f94608b -- config_models/crew.py -> removes enforce_leak_guard (others only gain descriptions)
git show ebd57eb8 -- config.py -> removes boot_camp_phase: BootCampPhaseConfig
git show 9d71e934 -- config/system.yaml -> removes boot_camp nudge_cooldown_seconds (crew.py fields re-added with descriptions)
prompts/bf-962-963-ward-room-identity-keys.md:1145 -> populate_ward_room_department removed from orientation
git show 7aaa3abf -- config_models/knowledge.py -> persistence_root_dir default "src/probos/agents/designed" -> ""
grep src/probos -> config.py:4131 (boot_camp_phase removed), crew.py:52 (nudge removed), crew.py:157 (enforce_leak_guard deleted), emergence.py:255 (counselor four), knowledge.py:398 populate_watch_section only
grep -n ": OrientationConfig|: SelfImprovementConfig" config.py -> 4056 orientation, 4061 self_improvement ; 3989 counselor ; 3973 security ; 2974 memory: "MemorySecurityConfig"
Read tests/test_ad1152_agentic_correlation.py:51-52, 216-338, 527-544
Read docs/development/agentic-event-correlation.md:131-149

Read scripts/gen_config_reference.py:1-227 -> 138 def _describe_model(name, model, seen); 140-142 seen; 144 heading; 173-174 recursion; 183-188 render
grep -c "^## " docs/development/config-reference.md -> 225 ; headings listed (§7.8): 435 federation's `discovery`, 1022 `security` then 1040 `permissions`, last `desktop` at 3217
Read src/probos/config.py:3909-4145 (SystemConfig) ; 2506 discovery: FederationDiscoveryConfig ; 4145 discovery: DiscoveryConfig ; 3220 duty_schedule: DutyScheduleConfig (ProactiveCognitiveConfig 3211) ; 3981 duty_schedule: DutyPolicyConfig
grep nested model fields config.py <3909 and config_models -> the 32 + 3 paths of §7.8
Read src/probos/config_models/crew.py:148-161 (MemorySecurityConfig, 5 fields) ; config_models/agentic.py:1212-1232 (DiscoveryConfig, 5 fields) ; config.py:3174-3178 (DutyScheduleConfig, 3 fields)
Read tests/test_config_reference_current.py:1-117 ; scripts/run_test_gate.py:1101 runs --check
Read tests/test_ad1270_boot_camp_orientation.py:365-369 ; test_ad1154_approval_inbox.py:2281 ; test_ad1155_loop_until_done.py:1637-1641

Read tests/test_bf927_boot_claims.py:1-65 -> (a)-(e) labelled; __self__ at 16-18 under "cannot see"; no "decorator"; no decorator_list (grep)
grep src/probos/routers/system.py -> 32 prefix="/api" ; 204-213 "status": "active"
grep -n "dp_min_cohort_size" src/probos -> federation_recall_agent.py:164, config.py:2518, crew.py:161
grep scripts/check_config_readers.py -> 3 REPORT-ONLY; 182, 194 return 0
gh issue view 1658 -> AD-1352, OPEN; body and comments: no "disclosure"
```

## Absence Verified (2026-11-18)

```
AV1  CLAIM: nothing in src calls .consult(
     RUN:   Grep "\.consult\(|request_consultation\(|handle_consultation_request|set_consultation_protocol" *.py
     FOUND: .consult( only tests/test_ad594b_consult_primitive.py:43,54,74,100,125,138; request_consultation( in src only cognitive_agent.py:9069 (+def consultation.py:162)
     HOLDS: yes
AV2  CLAIM: no test pins the "unchanged but for this" docstring; tier="fast", is once in cognitive_agent.py
     RUN:   Grep "unchanged but for this|tier=\"fast\"," tests + cognitive_agent.py
     FOUND: cognitive_agent.py:8918, :8961 only in src
     HOLDS: yes
AV3  CLAIM: nothing calls DisclosureRouter's filter
     RUN:   Grep "\.filter_permitted\(" src
     FOUND: none
     HOLDS: yes
AV4  CLAIM: no link uses a config-reference anchor
     RUN:   Grep "config-reference(\.md)?#" repo
     FOUND: none
     HOLDS: yes
AV5  CLAIM: _describe_model has no caller outside the script
     RUN:   Grep "_describe_model|gen_config_reference import" *.py
     FOUND: gen_config_reference.py:138,174,188 only
     HOLDS: yes
AV6  CLAIM: nothing pins agentic-event-correlation.md's text
     RUN:   Grep "agentic-event-correlation|Validation lineage" tests scripts docs mkdocs.yml
     FOUND: the document itself only
     HOLDS: yes
AV7  CLAIM: nothing pins test_bf927_boot_claims.py's docstring
     RUN:   Grep "test_bf927_boot_claims|Known approximations" *.{py,md,yaml,yml,toml}
     FOUND: the file itself; prompts; PROGRESS; the issue
     HOLDS: yes
AV8  CLAIM: tests pin only top-level reference headings
     RUN:   Grep "config-reference.md" tests -> test_ad1155:1634, test_ad1154:2278, test_ad1270_boot_camp_orientation:365, test_config_reference_current
     FOUND: headings approval_inbox, boot_camp, agentic_loop, agentic_tools, records, consensus, memory (all top-level)
     HOLDS: yes
AV9  CLAIM: no HXI reader of /api/disclosure-clearances
     RUN:   Grep "disclosure-clearances|disclosure_clearances" (repo minus prompts, .adq)
     FOUND: routers/system.py, tests/test_ad679_*, two era docs
     HOLDS: yes
AV10 CLAIM: the AD-1346/AD-1343 tests do not compare the consultation's answer to a fixture
     RUN:   Grep "_drive_issue_points|did not complete a full analysis|LLM call failed|golden" tests/test_ad1346_admission_ticket_issue.py
     FOUND: 224, 536, 541 (on/off comparison only)
     HOLDS: yes
AV11 CLAIM: security.memory, proactive_cognitive.duty_schedule and top-level discovery are absent from the reference
     RUN:   Grep "_probos\._tcp|enforce_|AD-708e" config-reference.md ; read headings 1113-1164, 1022-1040, last heading
     FOUND: enforce_required_departments (805), enforce_sealed_core (2085) only; no AD-708e; duty_schedule then work_hours, quiet_hours, proactive_cognitive, proactive_scan; desktop last
     HOLDS: yes
AV12 CLAIM: the M1 gate list is every test file driving the consultation path
     RUN:   Grep "\.consult\(|handle_consultation_request|ConsultationProtocol\(|_answer_consultation" tests
     FOUND: test_ad1343_agent_stop, test_ad1343_stop_crossing, test_ad1343_stop_seam_inventory, test_ad1346_admission_shadow_seams, test_ad1346_admission_ticket_issue, test_ad594_consultation_protocol, test_ad594b_consult_primitive (+ fixtures/ad1343_seam_registry.py, not a test)
     HOLDS: yes
```

## 12. Deterministic checks, resolved up front

| Check | Result |
|---|---|
| SRP | No method is added to `CognitiveAgent` (a frozen debt class, `architecture-baseline.yaml:407-413`); `_answer_consultation` grows by 4 lines. The generator keeps its function set; `_describe_model` loses a parameter |
| Layer | No new import in `src/`. The new test imports `probos.cognitive.cognitive_agent`, `.consultation`, `.llm_client` and `probos.types` |
| Phantom precheck | New names: `_DEFAULT_CONFIG_RULE`, `_ExpertLLM`, `_agent`, `_fallbacks`, `_request`, `_QUESTION`, `_FALLBACK_ANSWER`, `_AGENT_LOGGER`, `_FALLBACK_LOG`, `_model_paths`, test names C1–C4 and R1. Every other name is in §11 |
| Kwarg check | `LLMRequest(prompt=, system_prompt=, tier=)` (`types.py:310-312`); `LLMResponse(content=, error=)` (`:338`, `:345`); `ConsultationRequest(requester_id=, topic=, question=, target_agent_id=)`; `ConsultationProtocol()`; `consult(question, target_agent_id=)` |
| Hidden pins | BF-925 guard names: `error` is a dataclass field, so it counts as defined. AD-1343 seam inventory (`:113`, `handle_consultation_request` untouched). AD-1346 I9 on/off identity (P7). The generator's `--check` in `run_test_gate.py:1101`. `test_run_test_gate.py:262` (command string, unchanged) |
| Unowned tasks | None |
| Config, store, event | None |

## 13. Prior art and blind spots

No external search. This batch is ProbOS plumbing (a wrong keyword, a test's lineage, a generator's key), not a design AD, so `docs/research/reference-projects.md` was not consulted. Internal prior art adopted:
- the one-key refresh by measurement (`prompts/ad-1327-…:1845`, `prompts/bf-962-963-…:1149-1153`), now written where it is read;
- BF-962/963's rejection of re-inserting a removed key.

Blind spots found:
1. A failed call reported as a response (`error` set, no text): D2, C2.
2. Two more reference omissions than the issue names, `proactive_cognitive.duty_schedule` and the top-level `discovery`: §7.8, R1.
3. The golden's drift is wider than deletions (14 refreshes, additions absorbed in October): 7.4, R-B3-2.
4. The issue's stale anchors: `cognitive_agent.py:8668` → `:8888`; `gen_config_reference.py:136-138` → `:140-142`; `crew.py:125` → `:161`; the route is `/api/…`, not `/api/system/…`.
5. The consultation's confidence goes into a persisted event once a caller exists (§5).
6. The answer is ungrounded text at a fixed 0.6 (R-B3-1).
7. Changed mkdocs anchors (R-B3-3).
8. In a worktree, the test's `probos` import must be this checkout's (P8).

## 14. Diff Reviewer: properties to verify

1. `_answer_consultation` builds `LLMRequest` with `prompt=user_message`, the unchanged `system_prompt` and `tier="fast"`, and no other argument.
2. A response with `error` set, or whose text is blank, reaches the same `except` as a raising client: one WARNING with `exc_info`, and the 0.2 fallback answer and reasoning, unchanged. A response with text and no error gives that text at 0.6.
3. No production line outside `_answer_consultation` and its docstring changes. No caller of `consult` is added.
4. C1 crosses consult → protocol → registered handler → LLM with no mock of any of those. On the base its first post-premise assertion shows a `TypeError` fallback record. C2 and C3 assert the LLM was reached before asserting the fallback.
5. The golden fixture has no byte changed. The lines added to `_off_observation` only read `config`; none mutates the hashed dict.
6. Each backfilled line names a key that §11 shows was deleted (or, for BF-937, changed) after the capture, and each holds on the base tree.
7. The `default_config_sha256` comparison's failure message is `_DEFAULT_CONFIG_RULE`, and the rule says: added = pop; deleted or changed = named line plus refresh by measurement; never re-capture. The document says the same.
8. The document no longer calls the golden immutable or says only AD-1152's leaf is removed; it names the three kinds of value that were refreshed, its counts (17 refreshes since the capture: 14, two and one; and the eight and six within the 14) match `git log` on the fixture, and its observation checksum is labelled as the initial capture's.
9. 7.5 changes only the docstring of `tests/test_bf927_boot_claims.py`, which lists (a) to (g), each with a direction.
10. `_describe_model` heads each section with its dotted path and skips nothing. `render` passes the top-level name. No `seen` remains.
11. The regenerated reference matches §7.8 exactly: header lines, 32 heading renames, three added sections, and no other removed line.
12. R1 derives paths from the models, not from the generator, and asserts equality and order with the committed headings.
13. Trackers: one PROGRESS entry and one DECISIONS entry, plus the ledger pair regenerated by script.

## 15. Acceptance criteria

1. A consultation through `consult` returns the expert LLM's answer at 0.6 with no fallback logged (C1; E-1).
2. An error-marked or blank response, and a raising client, give the 0.2 fallback with the cause logged (C2, C3; E-2 to E-4).
3. The AD-1152 golden is byte-unchanged, its test names every deletion and changed default since BF-924, and its failure message and the document state the refresh rule (7.3, 7.4; E-5).
4. The resolver docstring discloses (a) to (g) with their directions (7.5).
5. The config reference has one section per model path, headed by the path, including `security.memory`, `proactive_cognitive.duty_schedule` and `discovery` (R1, `--check`; E-6 to E-8).
6. The §8 dispositions are posted, and #1676 closes only after the #1658 note is posted.
7. Every §10 row is killed by its named tests. One broad gate and one PR.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## For the register (#1523)

**R-B3-1.** Once anything calls `consult`, the expert's answer is raw LLM text at a fixed confidence of 0.6. The prompt asks the model to rate its confidence, but nothing parses it, and the text passes no output-grounding gate. Revisit when a caller is wired.

**R-B3-2.** The eight AD-1152 digest refreshes of 2026-10-08 to 2026-10-13 (additions and changed defaults) have no line in the test. They are listed in the lineage document, not backfilled.

**R-B3-3.** The 32 nested sections' mkdocs anchors change with their headings. No in-repo link uses them (AV4); an external bookmark would land on the page top.

### Premises to verify first-hand before building (each with its probe)

| P | Premise | Probe (assert it) |
|---|---|---|
| P1 | The base raises `TypeError` at the request | `python -c "from probos.types import LLMRequest; LLMRequest(system_prompt='s', user_message='u', tier='fast')"` raises `TypeError: … unexpected keyword argument 'user_message'` |
| P2 | `.consult(` has no `src` caller | `rg -n "\.consult\(" src/` prints nothing |
| P3 | C1 to C3 fail on the base as §6 says, and C4 passes | Run the new file on M1's base with the test only |
| P4 | 7.3's lines hold on the base and the golden is unchanged | Run the AD-1152 file after M2; `git diff --stat tests/fixtures/` is empty |
| P5 | The regeneration diff is §7.8 exactly | `git diff -U0 docs/development/config-reference.md`; count the `^-## ` lines (32) and the `^+## ` lines (35); confirm no other `^-` line |
| P6 | #1680 and #1811 change no default config field and no searched line | `git diff 9f43697f..<merged base> -- src/probos/config.py src/probos/config_models config/system.yaml scripts/gen_config_reference.py tests/test_ad1152_agentic_correlation.py src/probos/cognitive/cognitive_agent.py`. If a default field is deleted or changed, add its line to 7.3 pair 2 per the rule |
| P7 | `MockLLMClient` answers prompt `"q"` the same way in both I9 runs | Run `test_with_the_switch_on_and_off_the_issue_points_answer_byte_identically` after M1 |
| P8 | Under pytest in the worktree, `probos` resolves to this checkout | `python -c "import probos; print(probos.__file__)"` with the gate's environment points under the worktree |
