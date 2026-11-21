# BF-989 (#1838): the Counselor's reminiscence session awaits its episode read and scores the agent's own recall; a session writes no confabulation rate and no alert level

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-20

**Verified by:** the orchestrator, 2026-11-20: every pair and every check of section 15 was run on an oracle tree cut from `86b9c156` before the Builder started (section 16). The orchestrator rewrote the tracker pairs (7.8 and 7.9) in the layout of the BF-984 contract, anchored the new DECISIONS entry on the `### BF-984` heading that exists on the merged tree, wrote the pair labels as `**G1.**`, and kept the two non-ASCII characters (an em dash and an arrow) that the target files hold inside the pair blocks.

**Status:** draft for the oracle. Issue #1838; the PR says `Refs #1838` (the orchestrator closes the issue by hand once the closure is verified). Decision: consult `ba143101`, recorded on #1838 as issuecomment-7047585011, option A, no Captain condition. BF-989 appears only in REPLACE text, the new file, its path and tracker text, never in a SEARCH. The exceptions are the two DECISIONS BF-988 anchors and the PROGRESS BF-988 anchor, which quote text that already names #1838.

**Base:** `86b9c156` (the merge of PR #1843, BF-984, #1830), the tree the orchestrator proved this contract on; the Architect drafted it on `d57631f6` (PR #1842). B8 changes only the trackers among these files; the anchors in 7.6 to 7.9 exist on both trees. Under B8, the awaited `recent_for_agent` is the gated read, so:
- under armed `enforce_provenance`, a provenance-gap episode is never selected as ground truth;
- in report-only mode, a session can add gap reports.

**Line endings:** all eight edited files are `i/lf w/crlf` (`git ls-files --eol`). The SEARCH blocks are LF. Match and write each file with its own line endings, and write the new test file with LF.

**Milestones** (one Builder delegation each. The Builder applies the pairs and runs no test; the orchestrator commits by plumbing; no `AD-` or `BF-` token in any commit subject):

| M | Content | Tier | Review |
|---|---|---|---|
| M1 | Write 7.1 (new tests) first, then G1-G9, Q0-Q1, F1, A0-A4, A6, B1-B2 | MEDIUM | **Shared contract:** engine constructor, `ReminiscenceResult`, `classify_recall` result in AD-566 `details`. **Crew-facing:** DM prompt and templates |
| M2 | C1-C2, A5 | MEDIUM | **Crew-facing:** Counselor profile writes, DM gate, event payload. `confabulation_rate` feeds a cognition control |
| M3 | 7.8-7.10, ledger | LOW | Delta |

- Review M1 and M2 as one full review, not delta-only, with the GPT Diff Reviewer.
- Subjects:
  - M1: `Await the reminiscence episode read and score the agent's own recall`
  - M2: `Narrow what a reminiscence session writes to the counselor profile`
  - M3: `Record the reminiscence repair in the status and decisions entries`
- Broad gate once, after M3: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf-989-1838 --receipt logs/gates/bf-989-1838.receipt.json`.

**Captain:** no condition is met:
- no stored data changes (no session ever wrote `"amber"`: P9);
- no control is weakened (a session no longer moves the retrieval downgrade or the alert level);
- the new field and event key are additive;
- the spend is AD-541d's designed calls: at most 3 agent turns, 3 judge calls and 1 message call per agent per 2 h, and only at 3 or more concerns.

## 0. Premises (this tree)

| P | Premise | Evidence |
|---|---|---|
| P1 | The selection calls the async read without `await` | `guided_reminiscence.py:125` `def select_episodes_for_session`, `:137` `episodes = self._episodic_memory.recent_for_agent(...)`; `episodic_mock.py:231` `async def recent_for_agent`; orchestrator AST census: the only await-less call to an async `EpisodicMemory` or `MockEpisodicMemory` method in `src` |
| P2 | One caller each | `select_episodes_for_session` <- `run_session` `:404`; `.run_session(` <- `counselor.py:2507` only (grep `src`) |
| P3 | The recall is a bare completion | `:420-432` (`tier="fast"`, `max_tokens=200`, no agent) |
| P4 | AD-566's agent path | `qualification_tests.py:43-70` `_send_probe`, marker `:54`; `runtime.registry.get` `:398`; call `:450`; engine built without a recall `:428-431` |
| P5 | The marker suppresses episode storage | `cognitive_agent.py:12707` `if intent.params.get("_qualification_test"):` |
| P6 | Production wiring | `finalize.py:6276-6287` |
| P7 | Counselor writes | cooldown set after the session `:2515`; DEBUG on failure `:2508-2510`; rate overwrite `:2520`; amber `:2547-2554`; event `:2535-2545`; DM `:2531-2532` |
| P8 | Owners and readers | AD-568d EMA `:2163-2168`; AD-568e EMA `:2196-2201`; `source_governance.py:85` (`> 0.3` downgrades DEEP); `add_assessment` `:189-200`; `routers/counselor.py:101-103` count red, yellow, green |
| P9 | `"amber"` was never written by a session that read an episode | `92b99a47` (AD-541d) created the await-less call (`:124` there) while `recent_for_agent` was already async (`episodic.py:607` at `92b99a47`; enters in `d52a333a`) |
| P10 | Abstentions misclassified on the base | Orchestrator probe `probe_b989_classify.py`, P0-P3 held: 2 CONFABULATED, 5 CONTAMINATED, 0 PARTIAL at 0.0, 0.1 and 0.29 |
| P11 | The DM promises records it does not give | `:352-353`, `:366-367`, prompt `:379` |
| P12 | Two triggers | `counselor.py:1158` (post-dream), `:2076` (concern, threshold `:2075`) |
| P13 | Timeout precedent | `qualification.py:414`, `:519` (`asyncio.wait_for`, "Test timed out") already cancel probe runs that go through `_send_probe` |

## 1. Problem

The issue holds the full statement. In short:
- **The read.** No AD-541d session has ever read an episode on a real memory (P1, P9). The failure is caught at DEBUG with no cooldown (P7).
- **The recall.** The recall it would score is a memoryless model's (P3).
- **The await alone.** Adding only the `await` would turn that model's guesses into crew DMs, a `confabulation_rate` overwrite that feeds the retrieval downgrade, and an `"amber"` level no reader knows (P7, P8).
- **The classifier.** It labels honest abstentions as fabrication (P10).
- **The DM.** It promises records it never gives (P11).

## 2. Overview

| Part | Change |
|---|---|
| Read | `select_episodes_for_session` becomes `async` and awaits; `run_session` awaits it |
| Recall | The engine takes keyword-only `recall_fn(agent_id, prompt)` and `recall_timeout_seconds=120.0`. The production source is the new `qualification_tests.agent_recall_fn(registry)`, which calls `_send_probe`. With `recall_fn=None` there is no session and no LLM call. The completion recall is deleted, with no fallback |
| Measured | An empty, raised or timed-out recall, or an inconclusive judge (switch to `score_recall_outcome`, BF-711), leaves the episode unmeasured. Its reason goes in `ReminiscenceResult.unmeasured`; counts and means cover measured episodes only |
| Counselor | Cooldown set before the session; WARNING on failure; zero measured -> one INFO line and nothing written, sent or emitted; no `confabulation_rate` write; no `alert_level` write; event gains `unmeasured` |
| Classifier | Below 0.3, a recall whose every clause holds an abstention phrase -> PARTIAL |
| DM | The prompt asks for no fact; two templates invite a review instead of promising records |

Heavier designs rejected (one line each): a flag that keeps diagnoses off (option B); retiring AD-541d (option C); the `await` alone (option D); sessions as tracked background tasks (the cooldown and the per-recall timeout bound the handler); feeding the EMA (needs a measured classifier precision); episodes passed in by the Counselor (moves selection policy); a public `_send_probe` (18 call sites in 3 files).

## 3. Consumers checked

| Changed | Consumers | Result |
|---|---|---|
| `ReminiscenceResult` + `unmeasured` | `counselor.py:2507-2558`; tests that construct it (`test_ad541d` 21, 23-26); no `asdict` or serialisation in `src` (grep `asdict(` in `counselor.py`, `guided_reminiscence.py`, `qualification_tests.py`: none); no router or `ui/src` hit (`reminiscence`: 0 in `ui/src`, 0 in `src/probos/routers`) | Additive default; safe |
| Engine constructor | `finalize.py:6280` (F1); `qualification_tests.py:428` (unchanged, uses only build, score and classify); tests | Keyword-only with defaults |
| `select_episodes_for_session` (now async) | `run_session` only (P2); tests 1 and 2 | All await it |
| Event payload | Emitter `counselor.py:2536`; `events.py:212`; `event_persistence.py:373` and `test_ad1195...:298` are name lists only; no `ui/src` subscriber | Key added |
| `classify_recall` | `run_session`; `qualification_tests.py:455` -> `details["per_episode"][i]["classification"]` only; `test_ad566b:410` asserts the key's presence; `:440-472` are `ConfabulationProbe`, a different classifier | Score and pass unchanged |
| `agent_recall_fn` -> `_send_probe` -> `handle_intent` | The seam census keys on `handle_intent` call sites (`ad1343_seam_census.py:78-79`, `:140`); `_send_probe` is registered (`ad1343_seam_registry.py:170`) and exempt (`test_ad1248_slice_b.py:270`). The closure reads no `.result` | No new seam (O6) |
| `get_agent_memory_health` | No caller in `src` | Unchanged |

**Not checked:** live boot, live log volume, whether a session can run on the Counselor itself (R3).

## 4. Decisions

- **G-a.** The recall timeout is 120 s, a constructor default, not a config field. Precedent: P13.
- **G-b.** Unmeasured reasons have the form `"<episode id>: <reason>"`, or `"no agent recall source"` for the whole session.
- **G-c.** The abstention rule applies only below 0.3, so a measured score is never overridden (N10), and only when every clause holds a phrase (N9).
- **G-d.** A session with zero measured episodes still appends to `_session_history`, as the base does. `get_agent_memory_health` filters it out (`:489-490`).

## 5. Tests: new file `tests/test_bf989_guided_reminiscence_recall.py` (23 cases)

| N | Case | Base | After M1 | After M2 |
|---|---|---|---|---|
| N1 | Selection awaits the read | red | green | green |
| N2 | Session scores the agent's own recall; the client is never asked for it | red | green | green |
| N3 | No recall source -> nothing measured, 0 prompts | red | green | green |
| N4 x2 | Empty / raising recall unmeasured | red | green | green |
| N5 | Inconclusive judge -> that episode unmeasured | red | green | green |
| N6 | Timeout | red | green | green |
| N7 | `agent_recall_fn` takes the probe path; unknown agent -> "" | red | green | green |
| N8 x7 | Abstention -> PARTIAL (the probe's seven phrases) | red | green | green |
| N9 | Hedge followed by a claim stays CONFABULATED | **green** | green | green |
| N10 | Rule does not override 0.75 or 0.45 | **green** | green | green |
| N11 | Message prompt asks for no fact | red | green | green |
| N12 x2 | No template promises records | red | green | green |
| N13 | Counselor: rate and alert level untouched; score, DM and event present | red | **red** | green |
| N14 | Failed session: cooldown taken, one WARNING | red | **red** | green |
| N15 | Zero measured: no profile, save, DM or event; one INFO line | red | **red** | green |

Totals: base 21 red, 2 green; after M1 20 green, 3 red; after M2 23 green.

**Existing tests:**
- **`test_ad541d`**, edited in M1:
  - Tests 1, 2, 11, 13 and 28 are red on the base and green after M1.
  - Test 12 is unedited but uses `_make_engine`. On the base the `AsyncMock` read returns a coroutine, `len()` raises, so it is red; green after M1.
  - Tests 24 and 25 are edited in M2: red on the M1 tree, green after M2.
  - The rest are green throughout.
- **`test_bf988`:** every case that calls `_engine` is red on the base (`recall_fn` kwarg) and green after M1.
- **`test_ad566b`:** unchanged and green throughout.

**Focused gate** (orchestrator; once per milestone tree):
`d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf989_guided_reminiscence_recall.py tests/test_ad541d_guided_reminiscence.py tests/test_bf988_llm_response_text.py tests/test_ad566b_baseline_tests.py tests/test_bf139_140_probe_hardening.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py tests/test_ad1248_slice_b.py tests/test_source_governance.py -n 0 -q`
M3 adds `tests/test_ad1184_ad_ledger.py`.

## 6. Acceptance (#1838) mapped to cases

| Acceptance line | Cases |
|---|---|
| A session over a real async memory runs end to end | N2 (engine over `MockEpisodicMemory`), N13 (through the Counselor) |
| The scored recall is the agent's; a test fails if it comes from a call with no agent | N2 (`recall_fn` gets `"a1"`; the client is never sent the recall prompt), N3, N7; mutants M2, M3 |
| A test fails if `recent_for_agent` is not awaited | N1, `test_ad541d` test 1; M1 |
| Writes and DM decided and pinned | N13, N15, N11, N12, tests 24 and 25 |

## 7. The contract

### 7.1 New file `tests/test_bf989_guided_reminiscence_recall.py` (M1, written first)

```python
"""BF-989 (#1838): the Counselor's guided-reminiscence session reads its episodes with ``await`` and scores the
agent's own recall; a session writes no confabulation rate and no alert level.

Every engine here runs over a real ``MockEpisodicMemory`` (async ``recent_for_agent``, as on ``EpisodicMemory``)
and a recording client that answers with real ``LLMResponse``s. No memory is a ``MagicMock``: a synchronous
double is what hid that the read was never awaited.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.counselor import CognitiveProfile
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.cognitive.guided_reminiscence import GuidedReminiscenceEngine, RecallClassification, RecallResult
from probos.types import LLMResponse
from tests.test_ad541d_guided_reminiscence import _make_counselor, _make_episode

_MESSAGE = "Thank you for reviewing these with me. Let's look at your Ship Memory records together."
_RECALL = "the ship status was checked and it was nominal"
_FABRICATED = "then after the explosion it resulted in cascading failures because specifically the core overloaded"
_RECALL_PROMPT = "I'd like to review"  # how build_recall_prompt starts
_EXPECTED = "ship status check ok"
_ABSTENTIONS = [  # the orchestrator's probe: on the base each is CONFABULATED or CONTAMINATED below 0.3
    "I don't remember exactly what happened.",
    "I'm not sure what happened then.",
    "I do not remember the details of that exchange.",
    "I can't recall that episode.",
    "I don't recall.",
    "I have no memory of this.",
    "Unable to recall.",
]


class _Client:
    """The engine's LLM client: records every prompt; answers the judge and the message with real LLMResponses.

    ``scores`` are the judge's replies in order (an exception is raised); past them it answers "0.9".
    """

    def __init__(self, scores: list[Any] | None = None) -> None:
        self.prompts: list[str] = []
        self._scores = list(scores or [])

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        self.prompts.append(request.prompt)
        if request.prompt.startswith("Score the factual accuracy"):
            reply = self._scores.pop(0) if self._scores else "0.9"
            if isinstance(reply, Exception):
                raise reply
            return LLMResponse(content=reply)
        if request.prompt.startswith("You are a Ship's Counselor"):
            return LLMResponse(content=_MESSAGE)
        return LLMResponse(content="a model's recall")


class _Recall:
    """A recall source: records each (agent_id, prompt) and answers ``reply``, or raises it."""

    def __init__(self, reply: Any = _RECALL) -> None:
        self.calls: list[tuple[str, str]] = []
        self._reply = reply

    async def __call__(self, agent_id: str, prompt: str) -> str:
        self.calls.append((agent_id, prompt))
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


async def _store(memory: MockEpisodicMemory, n: int = 4) -> MockEpisodicMemory:
    for i in range(n):
        await memory.store(_make_episode(ep_id=f"ep-{i}", timestamp=1000.0 + i * 100, agent_ids=["a1"]))
    return memory


async def _engine(client: _Client, recall_fn: Any, **kwargs: Any) -> GuidedReminiscenceEngine:
    """Four stored episodes of a1; the session selects ep-0, ep-1, ep-2 (the most recent is skipped)."""
    return GuidedReminiscenceEngine(
        episodic_memory=await _store(MockEpisodicMemory()), llm_client=client, max_episodes_per_session=3,
        recall_fn=recall_fn, **kwargs,
    )


def _ward_room() -> SimpleNamespace:
    return SimpleNamespace(
        get_or_create_dm_channel=AsyncMock(return_value=SimpleNamespace(id="dm-1")),
        create_thread=AsyncMock(),
    )


# -- N1 to N7: the read, the recall source, what is measured ----------------------------------------


async def test_the_selection_awaits_the_memory_read() -> None:
    awaited: list[str] = []

    class _Counting(MockEpisodicMemory):
        async def recent_for_agent(self, agent_id: str, k: int = 5) -> list:
            awaited.append(agent_id)
            return await super().recent_for_agent(agent_id, k=k)

    memory = await _store(_Counting())
    selected = await GuidedReminiscenceEngine(episodic_memory=memory).select_episodes_for_session("a1", k=3)
    assert awaited == ["a1"]
    assert [ep.id for ep in selected] == ["ep-0", "ep-1", "ep-2"]


async def test_a_session_scores_the_agents_own_recall() -> None:
    client, recall = _Client(), _Recall()
    result = await (await _engine(client, recall)).run_session("a1")
    assert (result.episodes_tested, result.accurate_count, result.unmeasured) == (3, 3, [])
    assert [r.recalled_text for r in result.recall_results] == [_RECALL] * 3
    assert [agent_id for agent_id, _ in recall.calls] == ["a1"] * 3
    assert all(prompt.startswith(_RECALL_PROMPT) for _, prompt in recall.calls)
    assert not any(p.startswith(_RECALL_PROMPT) for p in client.prompts)  # the client only judges and writes
    assert result.therapeutic_message == _MESSAGE


async def test_with_no_recall_source_a_session_measures_nothing_and_asks_no_model() -> None:
    client = _Client()
    result = await (await _engine(client, None)).run_session("a1")
    assert (result.episodes_tested, result.unmeasured, result.recall_results) == (0, ["no agent recall source"], [])
    assert client.prompts == []


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        pytest.param("   ", "empty recall", id="empty"),
        pytest.param(ValueError("agent gone"), "recall failed: ValueError", id="raises"),
    ],
)
async def test_an_unmeasured_recall_is_not_counted(reply: Any, reason: str) -> None:
    client = _Client()
    result = await (await _engine(client, _Recall(reply))).run_session("a1")
    assert result.episodes_tested == 0
    assert result.unmeasured == [f"ep-{i}: {reason}" for i in range(3)]
    assert client.prompts == []  # no judge and no message


async def test_an_inconclusive_judge_leaves_its_episode_unmeasured() -> None:
    client = _Client(["0.9", RuntimeError("judge down"), "0.9"])
    result = await (await _engine(client, _Recall())).run_session("a1")
    assert result.episodes_tested == 2
    assert [r.episode_id for r in result.recall_results] == ["ep-0", "ep-2"]
    assert result.unmeasured == ["ep-1: judge call failed: RuntimeError"]


async def test_a_recall_that_never_returns_times_out() -> None:
    async def _never(_agent_id: str, _prompt: str) -> str:
        await asyncio.Event().wait()
        return ""

    engine = await _engine(_Client(), _never, recall_timeout_seconds=0.01)
    result = await asyncio.wait_for(engine.run_session("a1"), 5)  # bounded here so a missing timeout fails, not hangs
    assert result.episodes_tested == 0
    assert result.unmeasured == [f"ep-{i}: recall timed out" for i in range(3)]


async def test_agent_recall_fn_asks_the_agent_on_the_probe_path() -> None:
    from probos.cognitive.qualification_tests import agent_recall_fn  # imported here: only this case needs the new name

    class _Agent:
        id = "a1"
        agent_type = "crew"

        def __init__(self) -> None:
            self.intents: list[Any] = []

        async def handle_intent(self, intent: Any) -> Any:
            self.intents.append(intent)
            return SimpleNamespace(result="I checked the warp core.")

    agent = _Agent()
    recall = agent_recall_fn(SimpleNamespace(get=lambda agent_id: agent if agent_id == "a1" else None))
    assert await recall("a1", "What happened?") == "I checked the warp core."
    (intent,) = agent.intents
    assert (intent.intent, intent.target_agent_id, intent.params["text"]) == ("direct_message", "a1", "What happened?")
    assert intent.params["_qualification_test"] is True  # suppresses episode storage (CognitiveAgent.handle_intent)
    assert await recall("zz", "What happened?") == ""
    assert len(agent.intents) == 1


# -- N8 to N10: an abstention is an omission, not a commission ----------------------------------------


@pytest.mark.parametrize("recall", _ABSTENTIONS)
def test_an_abstention_is_partial(recall: str) -> None:
    engine = GuidedReminiscenceEngine(episodic_memory=None)
    assert engine.classify_recall(recall, _EXPECTED, None, 0.1) is RecallClassification.PARTIAL


def test_a_hedge_followed_by_a_claim_stays_confabulated() -> None:
    engine = GuidedReminiscenceEngine(episodic_memory=None)
    recall = f"I'm not sure, but {_FABRICATED}."
    assert engine.classify_recall(recall, _EXPECTED, None, 0.1) is RecallClassification.CONFABULATED


def test_the_rule_does_not_override_a_measured_score() -> None:
    engine = GuidedReminiscenceEngine(episodic_memory=None)
    assert engine.classify_recall("I don't recall.", _EXPECTED, None, 0.75) is RecallClassification.ACCURATE
    assert engine.classify_recall("I don't recall.", _EXPECTED, None, 0.45) is RecallClassification.PARTIAL


# -- N11, N12: the message states no fact it was not given ------------------------------------------------


async def test_the_message_prompt_asks_for_no_fact() -> None:
    client = _Client()
    engine = GuidedReminiscenceEngine(episodic_memory=None, llm_client=client)
    results = [RecallResult(classification=RecallClassification.CONFABULATED, accuracy=0.1) for _ in range(3)]
    assert await engine.build_therapeutic_response("a1", results) == _MESSAGE
    (prompt,) = client.prompts
    assert "Do not state any fact about the episodes." in prompt
    assert "redirect to verified facts" not in prompt


@pytest.mark.parametrize(
    "classifications",
    [
        pytest.param([RecallClassification.CONFABULATED] * 3, id="mostly-confabulated"),
        pytest.param(
            [RecallClassification.CONFABULATED, RecallClassification.PARTIAL, RecallClassification.PARTIAL],
            id="some-gaps",
        ),
    ],
)
async def test_no_template_promises_records_it_does_not_give(classifications: list) -> None:
    engine = GuidedReminiscenceEngine(episodic_memory=None)
    message = await engine.build_therapeutic_response("a1", [RecallResult(classification=c) for c in classifications])
    assert "share" not in message.lower()
    assert "Ship Memory records together" in message


# -- N13 to N15: what a session writes, through the real Counselor --------------------------------------


async def test_a_counselor_session_writes_no_rate_and_no_alert_level() -> None:
    ward_room, events = _ward_room(), []
    counselor = _make_counselor(
        _reminiscence_engine=await _engine(_Client(["0.1"] * 3), _Recall(_FABRICATED)),
        _cognitive_profiles={"a1": CognitiveProfile(agent_id="a1", confabulation_rate=0.12, alert_level="green")},
        _ward_room=ward_room,
        _emit_event_fn=lambda name, payload: events.append((name, payload)),
        callsign="Counselor",
        _record_intervention=MagicMock(),
    )
    await counselor._initiate_reminiscence_session("a1", trigger="bf989")
    profile = counselor._cognitive_profiles["a1"]
    assert profile.confabulation_rate == pytest.approx(0.12)  # the AD-568d/e value, not the session's 1.0
    assert profile.alert_level == "green"
    assert profile.memory_integrity_score == pytest.approx(0.1)
    assert profile.reminiscence_sessions == 1
    ward_room.create_thread.assert_awaited_once()
    assert ward_room.create_thread.await_args.kwargs["body"] == _MESSAGE
    ((name, payload),) = events
    assert name == "reminiscence_session_complete"
    assert payload["confabulation_rate"] == pytest.approx(1.0)
    assert payload["unmeasured"] == 0


async def test_a_failed_session_takes_the_cooldown_and_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    class _FailingEngine:
        def __init__(self) -> None:
            self.calls = 0

        async def run_session(self, agent_id: str) -> Any:
            self.calls += 1
            raise RuntimeError("session broke")

    engine = _FailingEngine()
    counselor = _make_counselor(_reminiscence_engine=engine)
    caplog.set_level(logging.DEBUG, logger="probos.cognitive.counselor")
    await counselor._initiate_reminiscence_session("a1", trigger="bf989")
    await counselor._initiate_reminiscence_session("a1", trigger="bf989")
    assert engine.calls == 1
    failures = [r for r in caplog.records if "Reminiscence session failed" in r.getMessage()]
    assert [r.levelno for r in failures] == [logging.WARNING]


async def test_a_session_that_measured_nothing_writes_sends_and_emits_nothing(caplog: pytest.LogCaptureFixture) -> None:
    store = SimpleNamespace(save_profile=AsyncMock())
    ward_room, events = _ward_room(), []
    counselor = _make_counselor(
        _reminiscence_engine=await _engine(_Client(), _Recall("")),
        _profile_store=store,
        _ward_room=ward_room,
        _emit_event_fn=lambda name, payload: events.append((name, payload)),
    )
    caplog.set_level(logging.INFO, logger="probos.cognitive.counselor")
    await counselor._initiate_reminiscence_session("a1", trigger="bf989")
    assert "a1" not in counselor._cognitive_profiles
    store.save_profile.assert_not_awaited()
    ward_room.create_thread.assert_not_awaited()
    assert events == []
    (line,) = [r.getMessage() for r in caplog.records if "measured no episode" in r.getMessage()]
    assert "ep-0: empty recall" in line
```

### 7.2 `src/probos/cognitive/guided_reminiscence.py` (M1)

**G1.** (imports and the abstention rule)
SEARCH:
```python
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from probos.cognitive.similarity import jaccard_similarity, text_to_words
from probos.types import llm_response_text

logger = logging.getLogger(__name__)
```
REPLACE:
```python
import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from probos.cognitive.similarity import jaccard_similarity, text_to_words
from probos.types import llm_response_text

logger = logging.getLogger(__name__)

# BF-989 (#1838): phrases by which a recall says the agent does not remember. Below 0.3 the novel-word analysis
# classified each probed abstention CONFABULATED or CONTAMINATED (the orchestrator's probe on the base).
_ABSTENTION_RE = re.compile(
    r"\b(?:don't remember|do not remember|don't recall|do not recall|can't recall|cannot recall"
    r"|unable to recall|no memory of|not sure)\b"
)
# A clause boundary: punctuation, or a word that joins a claim to a hedge ("I'm not sure, but then ...").
_CLAUSE_SPLIT_RE = re.compile(r"[.!?;,:]|\b(?:but|and|then|although|though|however|because)\b")


def _is_abstention(recalled_text: str) -> bool:
    """True when every clause of the recall holds an abstention phrase (BF-989).

    A hedge followed by a claim has a clause without one, so it is classified on its content as before.
    """
    text = recalled_text.lower().replace("\u2019", "'")
    clauses = [clause for clause in _CLAUSE_SPLIT_RE.split(text) if clause.strip()]
    return bool(clauses) and all(_ABSTENTION_RE.search(clause) for clause in clauses)
```

**G2.**
SEARCH:
```python
    therapeutic_message: str = ""
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0
```
REPLACE:
```python
    therapeutic_message: str = ""
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0
    # BF-989 (#1838): why each episode that was not measured was not ("<episode id>: <reason>"), or the one
    # session-level reason; episodes_tested and every count and mean cover measured episodes only.
    unmeasured: list[str] = field(default_factory=list)
```

**G3.**
SEARCH:
```python
        max_episodes_per_session: int = 3,
        confabulation_alert_threshold: float = 0.3,
    ) -> None:
        self._episodic_memory = episodic_memory
        self._llm_client = llm_client
        self._config = config
        self._max_episodes_per_session = max_episodes_per_session
        self._confabulation_alert_threshold = confabulation_alert_threshold
```
REPLACE:
```python
        max_episodes_per_session: int = 3,
        confabulation_alert_threshold: float = 0.3,
        recall_fn: Callable[[str, str], Awaitable[str]] | None = None,
        recall_timeout_seconds: float = 120.0,
    ) -> None:
        self._episodic_memory = episodic_memory
        self._llm_client = llm_client
        self._config = config
        self._max_episodes_per_session = max_episodes_per_session
        self._confabulation_alert_threshold = confabulation_alert_threshold
        # BF-989 (#1838): the agent's own recall, (agent_id, prompt) -> reply, bounded per episode. None means a
        # session measures nothing; llm_client is only the judge and the message writer, never the recall.
        self._recall_fn = recall_fn
        self._recall_timeout_seconds = recall_timeout_seconds
```

**G4.**
SEARCH:
```python
    def select_episodes_for_session(
        self, agent_id: str, k: int = 3,
    ) -> list:
        """Select episodes for a reminiscence session.

        Prefers: (a) multi-agent episodes (richer ground truth),
        (b) older timestamps, (c) not the most recent (avoid trivial recall).
        """
        if not self._episodic_memory:
            return []

        try:
            episodes = self._episodic_memory.recent_for_agent(agent_id, k=k * 2)
```
REPLACE:
```python
    async def select_episodes_for_session(
        self, agent_id: str, k: int = 3,
    ) -> list:
        """Select episodes for a reminiscence session.

        Prefers: (a) multi-agent episodes (richer ground truth),
        (b) older timestamps, (c) not the most recent (avoid trivial recall).

        BF-989 (#1838): ``recent_for_agent`` is a coroutine on both memories and is awaited; called without
        ``await`` it raised at ``len()``, so no session ever read an episode.
        """
        if not self._episodic_memory:
            return []

        try:
            episodes = await self._episodic_memory.recent_for_agent(agent_id, k=k * 2)
```

**G5.**
SEARCH:
```python
        if not recalled_words:
            return RecallClassification.PARTIAL

        # Words in recall NOT in expected — novel content
```
REPLACE:
```python
        if not recalled_words:
            return RecallClassification.PARTIAL

        # BF-989 (#1838): a recall that only says the agent does not remember is an omission, not a commission
        if _is_abstention(recalled_text):
            return RecallClassification.PARTIAL

        # Words in recall NOT in expected — novel content
```

**G6.**
SEARCH:
```python
                "That's not unusual — it happens to the best of us. "
                "Let me share what actually happened so we can align your memory "
                "with the verified records."
```
REPLACE:
```python
                "That's not unusual — it happens to the best of us. "
                # BF-989 (#1838): the message carries no record, so it promises none
                "Let's review your Ship Memory records together so we can align "
                "your memory with what was recorded."
```

**G7.**
SEARCH:
```python
                "recollections had gaps, but that's what these sessions are for. "
                "I'll share the verified records so we can work through the "
                "differences."
```
REPLACE:
```python
                "recollections had gaps, but that's what these sessions are for. "
                "Let's review your Ship Memory records together and work through "  # BF-989: no records are shared
                "the differences."
```

**G8.**
SEARCH:
```python
                    "Use validation therapy principles — don't argue, validate their "
                    "experience, then gently redirect to verified facts. "
                    "Keep it to 2-3 sentences."
```
REPLACE:
```python
                    "Use validation therapy principles — don't argue, validate their "
                    "experience, then invite them to review their Ship Memory records together. "
                    # BF-989 (#1838): the prompt gives no episode, so the message may state none
                    "Do not state any fact about the episodes. "
                    "Keep it to 2-3 sentences."
```

**G9.**
SEARCH:
```python
    async def run_session(self, agent_id: str) -> ReminiscenceResult:
        """Run a full reminiscence session for an agent."""
        start = time.monotonic()
        result = ReminiscenceResult(agent_id=agent_id, timestamp=time.time())

        episodes = self.select_episodes_for_session(
            agent_id, k=self._max_episodes_per_session,
        )
        if not episodes:
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        recall_results: list[RecallResult] = []

        for episode in episodes:
            ep_id = getattr(episode, 'id', '')

            # Build prompts
            recall_prompt = self.build_recall_prompt(agent_id, episode)
            expected = self.build_expected_summary(episode)

            # Get agent's recall via LLM
            recalled_text = ""
            if self._llm_client:
                try:
                    from probos.types import LLMRequest
                    response = await self._llm_client.complete(LLMRequest(
                        prompt=recall_prompt,
                        tier="fast",
                        max_tokens=200,
                    ))
                    recalled_text = llm_response_text(response)  # BF-988 (#1523 F-19)
                except Exception:
                    logger.debug("AD-541d: LLM recall failed for %s", ep_id[:8], exc_info=True)

            # Score and classify
            accuracy = await self.score_recall(recalled_text, expected)
            classification = self.classify_recall(recalled_text, expected, episode, accuracy)
```
REPLACE:
```python
    async def run_session(self, agent_id: str) -> ReminiscenceResult:
        """Run a full reminiscence session for an agent.

        BF-989 (#1838): the recall is the agent's own, through ``recall_fn``; with none, the session measures
        nothing and makes no LLM call (never a model's recall in the agent's place). An empty, failed or
        timed-out recall and an inconclusive judge (BF-711) leave the episode out of every count and mean,
        with its reason in ``unmeasured``.
        """
        start = time.monotonic()
        result = ReminiscenceResult(agent_id=agent_id, timestamp=time.time())

        if self._recall_fn is None:
            result.unmeasured.append("no agent recall source")
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        episodes = await self.select_episodes_for_session(
            agent_id, k=self._max_episodes_per_session,
        )
        if not episodes:
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        recall_results: list[RecallResult] = []

        for episode in episodes:
            ep_id = getattr(episode, 'id', '')

            # Build prompts
            recall_prompt = self.build_recall_prompt(agent_id, episode)
            expected = self.build_expected_summary(episode)

            # BF-989: the agent's own recall (AD-566's path in production), bounded per episode
            try:
                reply = await asyncio.wait_for(
                    self._recall_fn(agent_id, recall_prompt), self._recall_timeout_seconds,
                )
            except TimeoutError:
                result.unmeasured.append(f"{ep_id}: recall timed out")
                continue
            except Exception as exc:
                logger.warning("BF-989: recall failed for %s, episode %s", agent_id[:8], ep_id[:8], exc_info=True)
                result.unmeasured.append(f"{ep_id}: recall failed: {type(exc).__name__}")
                continue
            recalled_text = reply.strip() if isinstance(reply, str) else ""
            if not recalled_text:
                result.unmeasured.append(f"{ep_id}: empty recall")
                continue

            # Score and classify; a judge that failed or gave no number measured nothing (BF-711)
            scored = await self.score_recall_outcome(recalled_text, expected)
            if scored.inconclusive:
                result.unmeasured.append(f"{ep_id}: {scored.inconclusive}")
                continue
            accuracy = scored.score
            classification = self.classify_recall(recalled_text, expected, episode, accuracy)
```

### 7.3 `src/probos/cognitive/qualification_tests.py` (M1)

**Q0.**
SEARCH:
```python
import time
from typing import Any

from probos.cognitive.qualification import TestResult
```
REPLACE:
```python
import time
from collections.abc import Awaitable, Callable
from typing import Any

from probos.cognitive.qualification import TestResult
```

**Q1.**
SEARCH:
```python
        return ""


async def _llm_extract_float(llm_client: Any, prompt: str) -> float | None:
```
REPLACE:
```python
        return ""


def agent_recall_fn(registry: Any) -> Callable[[str, str], Awaitable[str]]:
    """The agent's own recall for guided reminiscence (BF-989, #1838), through ``_send_probe``.

    ``_send_probe`` marks the intent ``_qualification_test``, which suppresses episode storage
    (``CognitiveAgent.handle_intent``), so a recall attempt never becomes an episode that a later
    session could select as ground truth. An agent the registry does not hold recalls "".
    """

    async def _recall(agent_id: str, prompt: str) -> str:
        agent = registry.get(agent_id)
        if agent is None:
            return ""
        return await _send_probe(agent, prompt)

    return _recall


async def _llm_extract_float(llm_client: Any, prompt: str) -> float | None:
```

### 7.4 `src/probos/startup/finalize.py` (M1)

**F1.**
SEARCH:
```python
                    from probos.cognitive.guided_reminiscence import GuidedReminiscenceEngine

                    reminiscence_engine = GuidedReminiscenceEngine(
                        episodic_memory=runtime.episodic_memory,
                        llm_client=getattr(runtime, 'llm_client', None),
                        config=config.dreaming,
                        max_episodes_per_session=config.dreaming.reminiscence_episodes_per_session,
                        confabulation_alert_threshold=config.dreaming.reminiscence_confabulation_alert,
                    )
```
REPLACE:
```python
                    from probos.cognitive.guided_reminiscence import GuidedReminiscenceEngine
                    from probos.cognitive.qualification_tests import agent_recall_fn  # BF-989

                    reminiscence_engine = GuidedReminiscenceEngine(
                        episodic_memory=runtime.episodic_memory,
                        llm_client=getattr(runtime, 'llm_client', None),
                        config=config.dreaming,
                        max_episodes_per_session=config.dreaming.reminiscence_episodes_per_session,
                        confabulation_alert_threshold=config.dreaming.reminiscence_confabulation_alert,
                        # BF-989 (#1838): the agent's own recall (AD-566's path); llm_client only judges and writes
                        recall_fn=agent_recall_fn(runtime.registry),
                    )
```

### 7.5 `tests/test_ad541d_guided_reminiscence.py` (A0-A4 and A6 in M1; A5 in M2)

**A0.**
SEARCH:
```python
from probos.cognitive.counselor import CognitiveProfile, CounselorAgent
from probos.config import DreamingConfig
```
REPLACE:
```python
from probos.cognitive.counselor import CognitiveProfile, CounselorAgent
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.config import DreamingConfig
```

**A1.**
SEARCH:
```python
    memory = MagicMock()
    if episodes is not None:
        memory.recent_for_agent = MagicMock(return_value=list(episodes))
    else:
        memory.recent_for_agent = MagicMock(return_value=[])
    return GuidedReminiscenceEngine(
```
REPLACE:
```python
    memory = MagicMock()
    # BF-989 (#1838): recent_for_agent is async on both memories and the selection now awaits it; the
    # synchronous double hid that the read was never awaited.
    memory.recent_for_agent = AsyncMock(return_value=list(episodes or []))
    return GuidedReminiscenceEngine(
```

**A2.**
SEARCH:
```python
    def test_select_episodes_for_session_returns_up_to_k(self):
        """Test 1: select_episodes_for_session returns at most k episodes."""
        eps = [_make_episode(ep_id=f"ep-{i}", timestamp=time.time() - i * 100,
                             agent_ids=["a1", "a2"]) for i in range(6)]
        engine = _make_engine(episodes=eps)
        result = engine.select_episodes_for_session("a1", k=3)
        assert len(result) <= 3

    def test_select_episodes_for_session_empty_memory(self):
        """Test 2: Agent with no episodes returns empty list."""
        engine = _make_engine(episodes=[])
        result = engine.select_episodes_for_session("a1", k=3)
        assert result == []
```
REPLACE:
```python
    @pytest.mark.asyncio
    async def test_select_episodes_for_session_returns_up_to_k(self):
        """Test 1: select_episodes_for_session returns at most k episodes.

        BF-989 (#1838): async over a real MockEpisodicMemory. The selection now awaits recent_for_agent; over
        the synchronous MagicMock this test passed while every real session failed. Six stored, the most
        recent skipped, three returned.
        """
        memory = MockEpisodicMemory()
        for i in range(6):
            await memory.store(_make_episode(ep_id=f"ep-{i}", timestamp=time.time() - i * 100,
                                             agent_ids=["a1", "a2"]))
        engine = GuidedReminiscenceEngine(episodic_memory=memory)
        result = await engine.select_episodes_for_session("a1", k=3)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_select_episodes_for_session_empty_memory(self):
        """Test 2: Agent with no episodes returns empty list (BF-989: over a real, empty MockEpisodicMemory)."""
        engine = GuidedReminiscenceEngine(episodic_memory=MockEpisodicMemory())
        result = await engine.select_episodes_for_session("a1", k=3)
        assert result == []
```

**A3.** (test 11)
SEARCH:
```python
    async def test_run_session_full_flow(self):
        """Test 11: End-to-end session with 3 episodes."""
        eps = [_make_episode(ep_id=f"ep-{i}", timestamp=time.time() - i * 1000,
                             agent_ids=["a1", "a2"]) for i in range(4)]
        llm = AsyncMock()
        # LLM returns recall text, then score
        call_count = [0]
        async def _complete(req, **_kwargs):
            call_count[0] += 1
            resp = MagicMock()
            if "recall" in getattr(req, 'prompt', '').lower() or "what happened" in getattr(req, 'prompt', '').lower():
                resp.text = "ship was healthy and status checked ok"
            elif "Score" in getattr(req, 'prompt', '') or "score" in getattr(req, 'prompt', '').lower():
                resp.text = "0.8"
            else:
                resp.text = "Your memories look good."
            return resp
        llm.complete = _complete

        engine = _make_engine(episodes=eps, llm_client=llm, max_episodes_per_session=3)
        result = await engine.run_session("a1")
        assert result.episodes_tested <= 3
        assert result.episodes_tested > 0
```
REPLACE:
```python
    async def test_run_session_full_flow(self):
        """Test 11: End-to-end session with 3 episodes.

        BF-989 (#1838): the recall is the agent's, through recall_fn, so the client only judges and writes the
        message. Its old first branch also matched the judge's prompt, which contains "recall", so the judge
        got recall text and no number: the 0.5 fallback, which is now unmeasured.
        """
        eps = [_make_episode(ep_id=f"ep-{i}", timestamp=time.time() - i * 1000,
                             agent_ids=["a1", "a2"]) for i in range(4)]
        llm = AsyncMock()
        async def _complete(req, **_kwargs):
            resp = MagicMock()
            resp.text = "0.8" if req.prompt.startswith("Score") else "Your memories look good."
            return resp
        llm.complete = _complete

        async def _recall(_agent_id: str, _prompt: str) -> str:
            return "ship was healthy and status checked ok"

        engine = _make_engine(episodes=eps, llm_client=llm, max_episodes_per_session=3, recall_fn=_recall)
        result = await engine.run_session("a1")
        assert result.episodes_tested == 3
```

**A4.** (test 13)
SEARCH:
```python
        llm = AsyncMock()
        llm.complete = _llm_complete

        engine = _make_engine(episodes=eps, llm_client=llm, max_episodes_per_session=3)
```
REPLACE:
```python
        llm = AsyncMock()
        llm.complete = _llm_complete

        async def _recall(_agent_id: str, _prompt: str) -> str:
            # BF-989 (#1838): the recall is the agent's own, through recall_fn; the client's recall branch
            # above is no longer asked
            return "then after specifically resulted because the core failed exactly"

        engine = _make_engine(episodes=eps, llm_client=llm, max_episodes_per_session=3, recall_fn=_recall)
```

**A5.** (M2; tests 24 and 25)
SEARCH:
```python
    async def test_reminiscence_updates_profile_scores(self):
        """Test 24: Session updates memory_integrity_score, confabulation_rate, etc."""
        mock_engine = AsyncMock()
        mock_engine.run_session = AsyncMock(return_value=ReminiscenceResult(
            agent_id="a1", episodes_tested=3, overall_accuracy=0.6,
            confabulation_rate=0.1, therapeutic_message="OK",
        ))
        store = AsyncMock()
        store.save_profile = AsyncMock()
        agent = _make_counselor(
            _reminiscence_engine=mock_engine,
            _profile_store=store,
        )
        await agent._initiate_reminiscence_session("a1", trigger="test")
        profile = agent._cognitive_profiles["a1"]
        assert profile.memory_integrity_score == pytest.approx(0.6)
        assert profile.confabulation_rate == pytest.approx(0.1)
        assert profile.reminiscence_sessions == 1
        assert profile.last_reminiscence > 0

    @pytest.mark.asyncio
    async def test_confabulation_escalates_alert_level(self):
        """Test 25: confabulation_rate >= 0.3 sets alert_level to amber."""
        mock_engine = AsyncMock()
        mock_engine.run_session = AsyncMock(return_value=ReminiscenceResult(
            agent_id="a1", episodes_tested=3, overall_accuracy=0.2,
            confabulation_rate=0.5, therapeutic_message="Concerns",
        ))
        store = AsyncMock()
        store.save_profile = AsyncMock()
        agent = _make_counselor(
            _reminiscence_engine=mock_engine,
            _profile_store=store,
            _confabulation_alert_threshold=0.3,
        )
        await agent._initiate_reminiscence_session("a1", trigger="test")
        profile = agent._cognitive_profiles["a1"]
        assert profile.alert_level == "amber"
```
REPLACE:
```python
    async def test_reminiscence_updates_profile_scores(self):
        """Test 24: Session updates memory_integrity_score, last_reminiscence and the session count.

        BF-989 (#1838): it no longer writes confabulation_rate. AD-568d/e own that field (an EMA) and
        source_governance reads it to downgrade retrieval; the session's rate stays in its event.
        """
        mock_engine = AsyncMock()
        mock_engine.run_session = AsyncMock(return_value=ReminiscenceResult(
            agent_id="a1", episodes_tested=3, overall_accuracy=0.6,
            confabulation_rate=0.1, therapeutic_message="OK",
        ))
        store = AsyncMock()
        store.save_profile = AsyncMock()
        agent = _make_counselor(
            _reminiscence_engine=mock_engine,
            _profile_store=store,
            _cognitive_profiles={"a1": CognitiveProfile(agent_id="a1", confabulation_rate=0.12)},
        )
        await agent._initiate_reminiscence_session("a1", trigger="test")
        profile = agent._cognitive_profiles["a1"]
        assert profile.memory_integrity_score == pytest.approx(0.6)
        assert profile.confabulation_rate == pytest.approx(0.12)  # BF-989: the owners' value, not the session's 0.1
        assert profile.reminiscence_sessions == 1
        assert profile.last_reminiscence > 0

    @pytest.mark.asyncio
    async def test_confabulation_leaves_alert_level(self):
        """Test 25: a session's confabulation_rate >= 0.3 leaves alert_level as it was.

        BF-989 (#1838): renamed from test_confabulation_escalates_alert_level, which pinned the defect as the
        contract: it asserted "amber", a level agents_at_alert and the /counselor router do not count, written
        from a session whose recall was a memoryless model's. add_assessment owns alert_level.
        """
        mock_engine = AsyncMock()
        mock_engine.run_session = AsyncMock(return_value=ReminiscenceResult(
            agent_id="a1", episodes_tested=3, overall_accuracy=0.2,
            confabulation_rate=0.5, therapeutic_message="Concerns",
        ))
        store = AsyncMock()
        store.save_profile = AsyncMock()
        agent = _make_counselor(
            _reminiscence_engine=mock_engine,
            _profile_store=store,
            _confabulation_alert_threshold=0.3,
            _cognitive_profiles={"a1": CognitiveProfile(agent_id="a1", alert_level="yellow")},
        )
        await agent._initiate_reminiscence_session("a1", trigger="test")
        profile = agent._cognitive_profiles["a1"]
        assert profile.alert_level == "yellow"
```

**A6.** (test 28)
SEARCH:
```python
        assert "configure_reminiscence" in source
        assert "reminiscence_enabled" in source
```
REPLACE:
```python
        assert "configure_reminiscence" in source
        assert "reminiscence_enabled" in source
        # BF-989 (#1838): the engine is wired with the agent's own recall (behaviour: test_bf989 N2 and N7)
        assert "recall_fn=agent_recall_fn(runtime.registry)" in source
```

### 7.6 `tests/test_bf988_llm_response_text.py` (M1)

**B1.**
SEARCH:
```python
def _engine(client: Any, episodes: list | None = None) -> GuidedReminiscenceEngine:
    memory = MagicMock()
    # Synchronous on purpose: select_episodes_for_session calls recent_for_agent without await
    # (filed with BF-988), so only a synchronous double reaches run_session's reads.
    memory.recent_for_agent = MagicMock(return_value=list(episodes or []))
    return GuidedReminiscenceEngine(
        episodic_memory=memory, llm_client=client, max_episodes_per_session=3,
    )
```
REPLACE:
```python
async def _agent_recall(_agent_id: str, _prompt: str) -> str:
    """The agent's own recall (BF-989): the engine no longer asks the client for it."""
    return _RECALL


def _engine(client: Any, episodes: list | None = None) -> GuidedReminiscenceEngine:
    memory = MagicMock()
    # BF-989 (#1838): async, as on both memories; the selection now awaits recent_for_agent, which the
    # synchronous double (filed with BF-988) stood in for. The recall is recall_fn's; the client judges and
    # writes the message.
    memory.recent_for_agent = AsyncMock(return_value=list(episodes or []))
    return GuidedReminiscenceEngine(
        episodic_memory=memory, llm_client=client, max_episodes_per_session=3, recall_fn=_agent_recall,
    )
```

**B2.**
SEARCH:
```python
async def test_run_session_never_recalls_a_repr() -> None:
    result = await _engine(_Client(recall=""), _episodes()).run_session("a1")
    assert [r.recalled_text for r in result.recall_results] == ["", "", ""]
```
REPLACE:
```python
async def test_run_session_never_recalls_a_repr() -> None:
    # BF-989 (#1838): the recall now comes from recall_fn, so the client is never asked for it; the recalled
    # text is the agent's reply, never a response's repr. Was: the client's empty recall read as "".
    prompts: list[str] = []

    class _Recording(_Client):
        async def complete(self, request: Any, **kwargs: Any) -> LLMResponse:
            prompts.append(request.prompt)
            return await super().complete(request, **kwargs)

    result = await _engine(_Recording(recall="a model's recall"), _episodes()).run_session("a1")
    assert [r.recalled_text for r in result.recall_results] == [_RECALL] * 3
    assert not any(p.startswith("I'd like to review") for p in prompts)
```

Unchanged in this file and expected green: `:185-191` (now recalled through `_agent_recall`) and `:210-225`.

### 7.7 `src/probos/cognitive/counselor.py` (M2)

**C1.**
SEARCH:
```python
        last = self._reminiscence_cooldowns.get(agent_id, float("-inf"))
        if (time.monotonic() - last) < self._REMINISCENCE_COOLDOWN_SECONDS:
            return

        try:
            result = await self._reminiscence_engine.run_session(agent_id)
        except Exception:
            logger.debug("AD-541d: Reminiscence session failed for %s", agent_id[:8], exc_info=True)
            return

        if result.episodes_tested == 0:
            return  # No episodes to test

        self._reminiscence_cooldowns[agent_id] = time.monotonic()

        # Update CognitiveProfile
        profile = await self._get_or_create_profile(agent_id)
        profile.memory_integrity_score = result.overall_accuracy
        profile.confabulation_rate = result.confabulation_rate
        profile.last_reminiscence = time.time()
```
REPLACE:
```python
        last = self._reminiscence_cooldowns.get(agent_id, float("-inf"))
        if (time.monotonic() - last) < self._REMINISCENCE_COOLDOWN_SECONDS:
            return
        # BF-989 (#1838): the cooldown is taken before the session, with no await between check and set, so a
        # failed or unmeasured session and a second trigger (post-dream, retrieval concern) run at most one
        # session per agent per cooldown.
        self._reminiscence_cooldowns[agent_id] = time.monotonic()

        try:
            result = await self._reminiscence_engine.run_session(agent_id)
        except Exception:
            # BF-989: WARNING, not DEBUG (log-and-degrade); the cooldown bounds it to once per agent per cooldown
            logger.warning("AD-541d: Reminiscence session failed for %s", agent_id[:8], exc_info=True)
            return

        if result.episodes_tested == 0:
            # BF-989: nothing was measured, so no profile write, DM or event
            logger.info(
                "AD-541d: Reminiscence session for %s measured no episode (%s)",
                callsign, "; ".join(result.unmeasured) or "no episodes",
            )
            return

        # Update CognitiveProfile
        profile = await self._get_or_create_profile(agent_id)
        profile.memory_integrity_score = result.overall_accuracy
        # BF-989: confabulation_rate is not written here. AD-568d/e own it (an EMA) and source_governance
        # reads it to downgrade retrieval; the session's rate stays in its event and the engine's history.
        profile.last_reminiscence = time.time()
```

**C2.**
SEARCH:
```python
                "confabulated_count": result.confabulated_count,
                "contaminated_count": result.contaminated_count,
            })

        # Confabulation rate alarm → amber alert
        if result.confabulation_rate >= self._confabulation_alert_threshold:
            profile.alert_level = "amber"
            if self._profile_store:
                try:
                    await self._profile_store.save_profile(profile)
                except Exception:
                    logger.debug("AD-541d: Alert level save failed", exc_info=True)

        logger.info(
```
REPLACE:
```python
                "confabulated_count": result.confabulated_count,
                "contaminated_count": result.contaminated_count,
                "unmeasured": len(result.unmeasured),  # BF-989: episodes held out of the counts above
            })

        # BF-989 (#1838): no alert level is written here. add_assessment owns alert_level, and the "amber" this
        # wrote is a level agents_at_alert and the /counselor router do not count.

        logger.info(
```

`_confabulation_alert_threshold` stays in use at `:1018` and `:2210`.

### 7.8 `PROGRESS.md` (M3)

**TR1: the new entry.** SEARCH (the whole line `:1`, once): `# ProbOS Progress`. REPLACE:

```markdown
# ProbOS Progress

**BF-989 (2026-11-20), #1838 -- the Counselor's guided-reminiscence session awaits its episode read and scores the agent's own recall; a session writes no confabulation rate and no alert level.** `GuidedReminiscenceEngine.select_episodes_for_session` called the async `recent_for_agent` without `await` and raised at `len()`, so no AD-541d session read an episode (the Counselor caught it at DEBUG); the recall it would have scored was a fast-tier completion that carries no agent. The read is now awaited. The engine takes the agent's recall through `recall_fn(agent_id, prompt)`, bounded by `recall_timeout_seconds` (120 s), which startup wires to the new `qualification_tests.agent_recall_fn(registry)` (AD-566's `_send_probe`, whose `_qualification_test` marker suppresses episode storage); with no `recall_fn` there is no session and no model recall. An empty, failed or timed-out recall and an inconclusive judge (BF-711) leave the episode unmeasured (`ReminiscenceResult.unmeasured`), and only measured episodes are counted. The Counselor takes the cooldown before the session, logs a failed session at WARNING, writes, sends and emits nothing when nothing was measured, no longer overwrites `confabulation_rate` (owned by AD-568d/e, read by `source_governance`) and no longer writes `alert_level = "amber"` (owned by `add_assessment`); the event gains an `unmeasured` count. Below 0.3, a recall each of whose clauses says the agent does not remember is PARTIAL (on the base, seven probed abstentions were CONFABULATED or CONTAMINATED); a hedge followed by a claim is classified on its content as before. The message prompt and two templates no longer promise records the message does not give. Measured by `tests/test_bf989_guided_reminiscence_recall.py` (23 cases). Not measured: how often a live session runs and the live effect of its DM. Open items bf-989 R1 to R3 of #1820. Contract `prompts/bf-989-guided-reminiscence-agent-recall.md`.
```

**TR2: the BF-988 paragraph amendment.** A substring inside `:9` (BF-988's entry, after BF-984's). It occurs once (`grep -c`: 1) and contains no newline.

SEARCH (substring): `` and raises at `len()`, caught by the Counselor. ``
REPLACE: `` and raises at `len()`, caught by the Counselor. [Amended by BF-989 (2026-11-20): the session now awaits the read and scores the agent's own recall (AD-566's path); AD-541c practice still takes a memoryless recall.] ``

### 7.9 `DECISIONS.md` (M3)

**TR3: the new entry.** SEARCH (the whole line `:1661`, once): `### BF-984 -- AD-607's recall verdict runs on every public read of episodic memory but eight exempt ones; the rebuild command binds the gates as startup does (2026-11-20, #1830)`. REPLACE:

```markdown
### BF-989 -- the Counselor's reminiscence session awaits its episode read and scores the agent's own recall; a session writes no confabulation rate and no alert level (2026-11-20, #1838)

- *Mechanism.* `select_episodes_for_session` called the async `recent_for_agent` without `await` from the engine's first commit (`92b99a47`), so `len()` raised and every AD-541d session failed before reading an episode, logged at DEBUG with no cooldown. The recall it would have scored was a fast-tier completion that carries no agent. The two are repaired together: the selection is async and awaited (its one caller is `run_session`), and the recall is the agent's own.
- *Recall source.* The engine takes keyword-only `recall_fn(agent_id, prompt)` and `recall_timeout_seconds` (120 s, as AD-566's harness also bounds a probe run). Startup passes `qualification_tests.agent_recall_fn(runtime.registry)`, which asks the agent through `_send_probe`; its `_qualification_test` marker suppresses episode storage, so a recall attempt is never later selected as ground truth. With no `recall_fn` a session measures nothing and makes no LLM call; there is no fallback to the completion. `EpisodicRecallProbe` builds the engine without it.
- *Unmeasured.* An empty, failed or timed-out recall and an inconclusive judge (`score_recall_outcome`, BF-711) leave the episode out of `episodes_tested` and every count and mean; `ReminiscenceResult.unmeasured` names each, and the event carries their number.
- *Writes.* The cooldown is taken before the session (no await between check and set); a failed session logs at WARNING; when nothing was measured, one INFO line and no profile write, DM or event. A session writes `memory_integrity_score`, `last_reminiscence` and the session count. It does not write `confabulation_rate` (AD-568d `update_source_metrics` and AD-568e `record_faithfulness_event` own it as moving averages; `source_governance` downgrades DEEP retrieval above 0.3) or `alert_level` (`add_assessment` owns it; the `"amber"` the session wrote is a level `agents_at_alert` and the `/counselor` router do not count). No session wrote `"amber"` on a real memory, since none read an episode, so nothing is migrated.
- *Classifier.* Below 0.3, a recall each of whose clauses holds an abstention phrase is PARTIAL. On the base the orchestrator's probe classified seven abstentions CONFABULATED (2) or CONTAMINATED (5), none PARTIAL. A hedge followed by a claim has a clause with no such phrase and stays CONFABULATED (tested). TruthfulQA likewise scores "I don't know" as truthful but uninformative. AD-566's per-episode `classification` changes for such replies; its score and pass do not.
- *DM.* The message prompt asks for no fact about the episodes, and two templates invite a review of the records instead of promising to share them.
- *Effect.* Not measured: how often a live session runs, and the live effect of its DM.
- *G0.* Decided by the Architect (#1838, issuecomment-7047585011): none of the six conditions is met. No stored data changes; no control is weakened (a session no longer moves the retrieval downgrade or the alert level); the field and the event key are additive; the spend is AD-541d's designed calls.
- *Rejected.* Diagnoses and DM behind a flag (A gets the safety by narrowing the writes); retiring AD-541d (AD-566 proves the agent path, and AD-1340, #1568, names the feature as a reader); the `await` alone; sessions as tracked background tasks (the cooldown and per-recall timeout bound the handler); feeding the EMA (needs a measured classifier precision); episodes passed in by the Counselor (moves selection policy); a public `_send_probe` (18 call sites in three files); a phrase-anywhere abstention rule (a hedge would hide a fabrication).
- *Residual.* #1820 items bf-989 R1 to R3. *Reversal.* Revert the BF-989 commits; nothing stored needs migration.

### BF-984 -- AD-607's recall verdict runs on every public read of episodic memory but eight exempt ones; the rebuild command binds the gates as startup does (2026-11-20, #1830)
```

**TR4: the BF-988 Reach amendment.** A substring inside `:1698` (once).

SEARCH (substring): `No profile or DM holds a session's output.`
REPLACE: `` No profile or DM holds a session's output. [Amended by BF-989 (2026-11-20): a session now runs over a real memory; it writes `memory_integrity_score` and sends a DM, and writes no `confabulation_rate` or `alert_level`.] ``

**TR5: the BF-988 Rejected amendment.** A substring inside `:1703` (once).

SEARCH (substring): `` the selection `await` (it would turn on Counselor diagnoses built on a memoryless fast-tier recall); ``
REPLACE: `` the selection `await` (it would turn on Counselor diagnoses built on a memoryless fast-tier recall) [done by BF-989 (2026-11-20) with the agent's own recall]; ``

### 7.10 Ledger and roadmap (M3)

- Run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, then `--check`, then `tests/test_ad1184_ad_ledger.py`.
- Commit the two regenerated files in M3.
- No `roadmap.md` row: BF-988, BF-990 and BF-991 have none.

## 8. Issue texts

### 8.1 Closure comment on #1838

> Fixed by BF-989 (PR #...), option A of the decision in issuecomment-7047585011.
> - **Read:** `select_episodes_for_session` is async and awaits `recent_for_agent`.
> - **Recall:** the agent's own, through `recall_fn`, wired at startup to `qualification_tests.agent_recall_fn(registry)` (AD-566's `_send_probe`, marked `_qualification_test` so the attempt stores no episode), 120 s per episode. With no recall source a session measures nothing and asks no model.
> - **Measured only:** an empty, failed or timed-out recall and an inconclusive judge are held out of every count and listed in `ReminiscenceResult.unmeasured`.
> - **Writes:** the Counselor takes the cooldown first, logs a failed session at WARNING and writes nothing when nothing was measured. It no longer overwrites `confabulation_rate` and no longer writes `alert_level = "amber"`.
> - **Classifier:** an abstention below 0.3 is PARTIAL, not fabrication. The DM no longer promises records it does not give.
>
> Acceptance, from `tests/test_bf989_guided_reminiscence_recall.py` (23 cases):
> 1. **Real async memory, end to end:** `test_a_session_scores_the_agents_own_recall` and, through the Counselor, `test_a_counselor_session_writes_no_rate_and_no_alert_level`.
> 2. **The scored recall is the agent's:** the recall source receives `a1` and the client is never sent the recall prompt; with no source, 0 prompts (`..._asks_no_model`); `test_agent_recall_fn_asks_the_agent_on_the_probe_path`.
> 3. **The await:** `test_the_selection_awaits_the_memory_read` and AD-541d test 1, now over a real `MockEpisodicMemory`.
> 4. **Writes and DM pinned:** the rate stays 0.12, the alert level stays green, one DM, one event; nothing on zero measured; the message tests. AD-541d tests 24 and 25 were updated (25 had pinned `"amber"`).
>
> Not measured: how often a live session runs, and its DM's live effect. Open: #1820 items bf-989 R1 to R3.

### 8.2 New items on #1820

- `- [ ] **bf-989 R1 (P3, Medium; pre-existing): AD-541c retrieval practice still scores a memoryless fast-tier recall, and its concerns trigger AD-541d sessions.** \`dreaming.py:2781-2792\` asks \`tier="fast"\` with no agent and scores that text; \`episodes_at_risk\` from it reaches \`_on_retrieval_practice_concern\` (\`counselor.py:2049-2078\`), which writes \`retrieval_concerns\` and \`last_retrieval_accuracy\` and, at 3 or more, starts a session. Reach: every dream, every agent with episodes. After BF-989 a false concern costs a session that measures the agent itself (up to 3 agent turns, 3 judge calls and 1 message call, once per agent per 2 h), not a false diagnosis. Repair: take the recall through \`agent_recall_fn\`, or retire the practice trigger.`
- `- [ ] **bf-989 R2 (P3, Low): the precision of \`classify_recall\` on real agent replies is unmeasured.** It is a novel-word heuristic (\`guided_reminiscence.py\` \`classify_recall\`). BF-989 fixed one class (abstentions, measured), and a recall whose single clause both abstains and claims ("I don't remember what happened after the core exploded") is PARTIAL by its rule. That measurement is the precondition for ever feeding a session's rate into the \`confabulation_rate\` EMA. Evidence: \`tests/test_bf989_guided_reminiscence_recall.py\` N8 to N10.`
- `- [ ] **bf-989 R3 (P4, Low; untested): a session on the Counselor itself, and the handler's latency.** \`_initiate_reminiscence_session\` can target the Counselor's own id; the recall then re-enters its \`handle_intent\` through \`_send_probe\`. Each listener runs as its own task (\`counselor.py:2320-2321\`), and each recall is bounded at 120 s, but neither the self-session nor event lag under live sessions is measured.`

## 9. What this does NOT change

- AD-566 `EpisodicRecallProbe` construction, scoring, thresholds and pass logic.
- `_send_probe`.
- `score_recall` and `score_recall_outcome`.
- `build_recall_prompt` and `build_expected_summary`.
- `get_agent_memory_health`.
- `_send_therapeutic_dm` and its hourly limit.
- The triggers and their thresholds.
- AD-541c practice (`dreaming.py`, `retrieval_practice.py`).
- AD-568d and AD-568e.
- `source_governance`.
- `add_assessment`.
- Config fields and `system.yaml`.
- `EventType`.
- The episodic memories (BF-984 owns their gating).
- Routers and HXI.
- Any stored profile.

## 10. Mutation rows

One campaign of record on the M2 tree. Restore between rows and run only the listed killers at `-n 0`.

| M | Mutation | Killers |
|---|---|---|
| M1 | G4: drop `await` before `recent_for_agent` | N1, N2, ad541d test 1 |
| M2 | G9: recall through `self._llm_client.complete(LLMRequest(prompt=recall_prompt, tier="fast", max_tokens=200))` | N2, bf988 `test_run_session_never_recalls_a_repr` |
| M3 | G9: when `recall_fn is None`, recall through the client | N3 |
| M4 | C1: restore `profile.confabulation_rate = result.confabulation_rate` | N13, ad541d test 24 |
| M5 | C2: restore the amber block | N13, ad541d test 25 |
| M6 | G9: delete the empty-recall `continue` | N4[empty] |
| M7 | G9: `accuracy = await self.score_recall(...)` with no inconclusive check | N5 |
| M8 | Q1: replace `_send_probe` with a direct `handle_intent(IntentMessage(intent="direct_message", params={"text": prompt}, target_agent_id=agent.id))` | N7 |
| M9 | C1: move the cooldown set after the session | N14 |
| M10 | C1: `logger.debug` on failure | N14 |
| M11 | G9: `reply = await self._recall_fn(agent_id, recall_prompt)` (no `wait_for`) | N6 |
| M12 | G5: delete the abstention check | N8 x7 |
| M13 | G1: `_is_abstention` returns `bool(_ABSTENTION_RE.search(text))` | N9 |
| M14 | G8: restore "then gently redirect to verified facts." and drop the new sentence | N11 |
| M15 | G6 or G7: restore either template | N12 (matching case) |
| M16 | F1: drop the `recall_fn=` line | ad541d test 28 |
| M17 | C1: delete the zero-measured block | N15 |
| M18 | G9: delete `except Exception` (keep `TimeoutError`) | N4[raises] |
| M19 | Q1: delete `if agent is None: return ""` | N7 |

## 11. Verified Against Codebase (2026-11-20, `d57631f6`)

```
guided_reminiscence.py:125 def select_episodes_for_session / :137 recent_for_agent( no await / :404 caller
guided_reminiscence.py:420-432 client recall; :435 score_recall; :234 score_recall_outcome; :277-319 classify_recall
guided_reminiscence.py:350-353, :363-367 templates; :379 "gently redirect to verified facts"; :63-78 ReminiscenceResult
episodic_mock.py:231 async def recent_for_agent; :137 async def store; no __len__/__bool__
qualification_tests.py:43 _send_probe; :54 "_qualification_test": True; :398 registry.get; :428-431 engine; :455 classify_recall
cognitive_agent.py:12707 if intent.params.get("_qualification_test"):
finalize.py:6276-6287 wiring; counselor.py:1158, :2076 triggers; :2492-2559 session; :2312 _send_therapeutic_dm
counselor.py:165 alert_level default "green"; :179 confabulation_rate; :189-200 add_assessment; :769 agents_at_alert
counselor.py:2163-2168, :2196-2201 EMAs; :1018, :2210 threshold readers; :37 logger
source_governance.py:85 DEEP and > 0.3; routers/counselor.py:101-103 red/yellow/green
qualification.py:414, :519 wait_for; pyproject.toml:9 >=3.12, :181 asyncio_mode = "auto"
git show 92b99a47: guided_reminiscence.py:124 await-less; episodic.py:607 async def recent_for_agent
git ls-files --eol: all 8 files i/lf w/crlf
```

## Absence Verified (2026-11-20)

| Claim | Run | Found | Holds |
|---|---|---|---|
| No other caller of `run_session` | `rg '\.run_session\(' src` | `counselor.py:2507` | yes |
| No `ReminiscenceResult` consumer outside the engine and Counselor in `src`, routers or `ui/src` | `rg 'ReminiscenceResult\|reminiscence' src ui/src` (engine and test files excluded) | `counselor.py` and wiring only; 0 in `ui/src` and routers | yes |
| No consumer of the event's payload | `rg 'reminiscence_session_complete\|REMINISCENCE_SESSION_COMPLETE'` | `counselor.py:2536`, `events.py:212`, `event_persistence.py:373` and `test_ad1195:298` (name lists) | yes |
| No test asserts the old DM wording | `rg 'actually happened\|verified records\|verified facts' tests src` | only the engine; an unrelated golden-fixture sentence | yes |
| No test asserts an episodic-probe classification value | `rg '"classification"\] ==' tests` | `test_ad566b:457` (ConfabulationProbe) | yes |
| BF-989 artefacts absent | Glob `prompts/bf-989*`, `tests/test_bf989*` | none | yes |
| B8 leaves the 8 files alone | `git diff --stat d57631f6 eed8f24c -- <8 files>` | empty | yes |

## 12. Deterministic checks

- **The 7 abstentions on the base.** Each shares no word with `ship status check ok`, so the novel-word ratio is 1.0 (above 0.3) and none can be PARTIAL. That makes N8 red on the base.
- **The hedge case.** It has 5 specific indicators and 0 generic ones, so it is CONFABULATED on the base and after the change (its clause after "but" has no phrase).
- **Selection order.** `MockEpisodicMemory.recent_for_agent` returns the newest first. Four episodes at 1000 to 1300, the newest dropped, sorted by timestamp, give `ep-0, ep-1, ep-2`.
- **Python 3.12.** `asyncio.wait_for` raises `TimeoutError`, so the `except TimeoutError` comes before `except Exception`.
- **`MagicMock` doubles.** `resp.text` on a `MagicMock` reads through `llm_response_text` (`test_bf988` "mock-with-text").

## 13. Prior art and blind spots

- **Internal:** consult `ba143101`; AD-566 D2 (`EpisodicRecallProbe`), the agent-recall path this reuses; BF-711 and BF-988 (unmeasured judge); BF-921 (reserve before awaits, the cooldown pattern).
- **External:** one search. TruthfulQA counts "I don't know" and "No comment" as truthful but uninformative, and tracks informativeness separately ([paper](https://arxiv.org/pdf/2109.07958), [repo](https://github.com/sylinrl/truthfulqa)).
  - **Adopted:** an abstention is PARTIAL, an omission and not a commission.
  - **Not adopted:** TruthfulQA's informativeness metric. The judge's score stays the measure, so an always-abstaining agent still shows a low `memory_integrity_score`.
  - `reference-projects.md` lists no project on recall classification (grep for hallucination, confabulation, abstention and truthful: 0 hits). No overdue row applies.
- **Blind spots, recorded:**
  - A cancelled recall cancels an agent turn. AD-566's harness already does this (P13).
  - A single-clause abstention with a claim is PARTIAL (R2).
  - Self-session and handler latency are untested (R3).
  - Under B8's armed provenance mode a session may select fewer than 3 episodes. That is correct: unverifiable ground truth must not score recall.

## 14. Diff Reviewer: properties to verify

1. `select_episodes_for_session` is `async` and awaits `recent_for_agent`; every caller awaits it.
2. No path in `run_session` sends the recall prompt to `llm_client`. With `recall_fn=None` there are 0 LLM calls.
3. `episodes_tested`, the four counts, `overall_accuracy` and `confabulation_rate` cover measured episodes only, and each excluded episode adds exactly one `unmeasured` entry.
4. In `_initiate_reminiscence_session`: the cooldown is set before any await; nothing writes `confabulation_rate` or `alert_level`; zero measured means no profile creation, save, DM or event.
5. The event payload's keys are a superset of the base's.
6. `EpisodicRecallProbe` is unchanged; only per-episode `classification` can differ, and only for an abstention below 0.3.
7. The abstention rule fires only below 0.3 and only when every clause holds a phrase.
8. The DM prompt and templates promise no record and state no episode fact.
9. Test edits: nothing deleted or skipped; each change carries its reason inline; test 25 no longer pins `"amber"`; the new file has no `MagicMock` memory.
10. No commit subject carries an `AD-` or `BF-` token.
11. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. The orchestrator's first-hand checks (oracle tree cut from merged main, before the Builder starts)

| O | Check | Expected |
|---|---|---|
| O1 | Every SEARCH (G1-G9, Q0, Q1, F1, A0-A6, B1, B2, C1, C2, TR1, TR3) and the substrings TR2, TR4, TR5, matched with line endings normalised | Exactly one match each (28) |
| O2 | 7.1 alone on the base, `-n 0` | 21 failed, 2 passed (N9, N10); N8's 7 fail by assertion, not error |
| O3 | M1 pairs applied; the focused gate | New file 20 passed, 3 failed (N13-N15); all other gate files green |
| O4 | M2 pairs applied; the focused gate | All green |
| O5 | `census_unawaited_em_calls.py` on the M1 tree (controls held) | 0 await-less calls |
| O6 | `-c "import probos.startup.finalize; from probos.cognitive.qualification_tests import agent_recall_fn"`, plus `test_ad1343_*` and `test_ad1248_slice_b.py` | Import succeeds; seam tests green |
| O7 | The mutation campaign of section 10 on the M2 tree; record each file's sha256 | Every row killed by its listed killers |
| O8 | M3: `gen_ad_ledger.py --check`, `test_ad1184_ad_ledger.py` | Green |
| O9 (optional, read-only) | Count `Counselor: Retrieval practice concern for` in the live log, and those with >=3 at risk | Fill the *Effect* bullet in D1, or leave "Not measured" |

---

I wrote no memory note and edited no repository file.

Sources:
- [TruthfulQA: Measuring How Models Mimic Human Falsehoods (arXiv 2109.07958)](https://arxiv.org/pdf/2109.07958)
- [TruthfulQA repository](https://github.com/sylinrl/truthfulqa)

## 16. The orchestrator's first-hand checks (2026-11-20, an oracle tree at `86b9c156`, whose tree is `3167ff44`)

Every pair of section 7 was applied to a scratch worktree by `audit\contract_tools.py` (with `--utf8 U+2014,U+2192`, the two non-ASCII characters that the target files hold), and every check of section 15 was run, before the Builder started. The focused gate and the consumer set ran under the default embeddings and under `PROBOS_EMBEDDINGS=local`, as CI runs them. Results:

| O | Result |
|---|---|
| O1 | All 28 SEARCH blocks and substrings (G1-G9, Q0, Q1, F1, A0-A6, B1, B2, C1, C2, TR1-TR5) occur exactly once on the merged tree, in files that are CRLF throughout (`git ls-files --eol`: `i/lf w/crlf`). The new test file and `prompts/bf-989*` were absent. |
| O2 | 7.1 alone on the base, `-n 0`: 21 failed, 2 passed (N9 and N10). The seven abstentions of N8 fail by assertion (CONFABULATED or CONTAMINATED, never PARTIAL). The other failures are the missing `recall_fn` keyword (N2-N6 and, on the base, N13 and N15), the missing `agent_recall_fn` (N7), the un-awaited selection (N1), the prompt and the two templates (N11, N12), and the cooldown (N14). |
| O3 | The M1 pairs applied (7.1, G1-G9, Q0, Q1, F1, A0-A4, A6, B1, B2): the nine-file focused gate gives 3 failed (N13-N15), 235 passed, 2 skipped under the default embeddings (46 s) and under `PROBOS_EMBEDDINGS=local` (24 s). The two skips are `test_bf139_140_probe_hardening.py:229` and `:262` (the sentence-transformers model is offline); they skip on the base too. |
| O4 | The M2 pairs applied (C1, C2, A5): the focused gate gives 238 passed, 2 skipped. A consumer set of 37 files (the reminiscence, Counselor, qualification, finalize, seam, retrieval-practice, probe-hardening, source-governance and ledger tests, found by searching `tests` for the changed names and file names): 1014 passed, 2 skipped under each setting. |
| O5 | The await-less call census (`census_unawaited_em_calls.py`): on the base the controls hold (the async method sets of both memories hold `recent_for_agent`; the census sees awaited calls; the known call at `guided_reminiscence.py:137` is reported). On the M2 tree, with the third control inverted (`--expect-fixed`: that call must be gone), the controls hold and 407 awaited calls are seen. The one row that its defect-class list still holds, `dm_targeted_lookup.py:225` (`recall_for_agent`), awaits the result when it is a coroutine (`:226-227`). |
| O6 | `import probos.startup.finalize` and `from probos.cognitive.qualification_tests import agent_recall_fn` succeed; the engine's last two parameters are `recall_fn` and `recall_timeout_seconds`; `select_episodes_for_session` is a coroutine function. `test_ad1343_seam_registry.py`, `test_ad1343_stop_seam_inventory.py` and `test_ad1248_slice_b.py` are green. `cognitive_agent.py:12707` returns before storing an episode when `_qualification_test` is set (read, P5). |
| O7 | The campaign of section 10 (`audit\mutants_gen.py` with `audit\rows_bf989.py`) on the M2 tree, whose four test files (the new one, `test_ad541d_guided_reminiscence.py`, `test_bf988_llm_response_text.py` and `test_ad566b_baseline_tests.py`) give 124 cases, all green unmutated: **all 20 rows (the 19 of the draft, row 15 split in two) are killed, none survived, none differs: every named killer failed in every row.** Four rows are killed by more cases than the draft named: M1 (15 cases: N1, N2 and test 1, and twelve more that run `run_session` or the selection over the un-awaited read, among them the three `test_bf988` cases and two of `TestD1Sessions`), M2 (11), M6 (2: also N15, whose empty recall must not be judged) and M9 (2: also AD-541d test 23, the cooldown test); a second run that names those two extra killers reported every one of them failing. |
| O8 | AV7: BF-989 occurs only on #1838 (issue titles of all states), in no commit subject on any ref, in no `prompts/bf-989*` file and in no `tests/test_bf989*` file on `origin/main`. |
| O9 | The optional live log count was not run (it needs the Captain's data). The *Effect* bullet of the DECISIONS entry keeps "Not measured". |
| O10 | The trackers TR1-TR5 applied on the oracle (each SEARCH once; `PROGRESS.md` 1788 lines, `DECISIONS.md` 13499 lines), then `gen_ad_ledger.py` regenerated the ledger pair and `--check` reported "AD/BF ledger is current"; `tests/test_ad1184_ad_ledger.py` is green in the consumer set. |

The orchestrator's rows of the campaign are one-line mutants of the same effect on the named killer, where the draft's mutation changes several lines: M3 deletes the no-recall-source guard (`if False:`), so the session calls `None` and records "recall failed: TypeError" instead of the one session-level reason; M6, M7, M17 and M19 turn the condition into `if False:`; M8 calls `handle_intent` directly with no marker; M9 does not take the cooldown before the session (moving it after the session is the same for a failed session); M14 drops the no-fact sentence; M15 is M15a (G6's template) and M15b (G7's); M16 writes `recall_fn=None,`; M18 catches `OSError`.

The base of the campaign of record (the files after M1 and M2; blob id, sha256 of the LF text, lines):

| File | Blob | sha256 (LF text) | Lines |
|---|---|---|---|
| `src/probos/cognitive/guided_reminiscence.py` | `cf949c65825089f2dd33c8b17a65effe2493085c` | `2eea57b9e7536f856e9475284469ba6593aa543ed34b2886c23adc37171e1561` | 566 |
| `src/probos/cognitive/qualification_tests.py` | `bb8e6bcba5905185114ae5b3a4e759771b53190a` | `9aa9ffc4ecabcc0df02527e95c95330c0ebd731af69983ad8a2fdd9603aad701` | 869 |
| `src/probos/startup/finalize.py` | `737d80262314b7667eea2308d61ab6dbf2f6ae38` | `65ba92427651ddff6b48a96e2e9e3189bc09d7de6615a33931061f95858ade56` | 6884 |
| `src/probos/cognitive/counselor.py` | `7e059441bb3dfced09c85cc233b16eddaf3711ad` | `77b20c9fd3ef34e8254f79659c12b0fa5da7a6a1aca27befb9d11bbe7b349ae6` | 2939 |
| `tests/test_bf989_guided_reminiscence_recall.py` | `fd913a53b9039fa65f27b9daf694091e33d1e741` | `f3fb43570c38bc5e156d585e3a10a5ade95fa6be5a61074fdb1d50ee426231ed` | 304 |
| `tests/test_ad541d_guided_reminiscence.py` | `7c48eb96f78505135db7b0f4ed20e5771fafd4ef` | `a6e1c83fc8b2ae8e4a68dad4943c28f28e1ab653d9ecb5e167c4d88332f82b7d` | 565 |
| `tests/test_bf988_llm_response_text.py` | `eae60c541a2851d90a8e2e2f35741304c96f61c1` | `7b9af12869d026eba3787c5d98e60ee7bc4d0e64afb697e06fba02cee721635f` | 474 |

After M3: `PROGRESS.md` `9d1f6ce3c172eac27eabcc75443831f69f6689a5` (1788 lines) and `DECISIONS.md` `ae244da2876336f0395e1620ad9b78bbf178dcee` (13499 lines).

What the tests do not show, stated plainly: the recall source of N2 is a test double, so the real `CognitiveAgent` turn behind `_send_probe` is covered only by N7 (a fake agent that records the intent and its `_qualification_test` marker) and by reading P5; no vessel ran a session, so the live behaviour of the agent's answer, of the judge and of the message is not measured; and the abstention rule is a heuristic over the seven phrases the probe covered (R2 of #1820).

**What the orchestrator changed in the Architect's draft** (the rest is the draft's): the Status line says `Refs #1838` where the draft said `Closes #1838`; the Base line names `86b9c156`; the pair labels are written as `**G1.**` so that the pair tool finds them; the tracker pairs of 7.8 and 7.9 are rewritten in the layout of the BF-984 contract (labels TR1-TR5), and the new DECISIONS entry is anchored on the `### BF-984` heading that exists on the merged tree; the M3 row names 7.8-7.10 (7.6 is M1's B1 and B2); the six em dashes and the one arrow that the draft's pair blocks hold are kept, because the target files hold them, and every other non-ASCII character of the draft is mapped to ASCII.

## 17. Repair after review round 1 (2026-11-21)

Round 1 of the Diff Reviewer (GPT-6.1 Sol; REQUEST CHANGES, 0 size findings) found two defects in the candidate `0ebf18e0`. The orchestrator reproduced both first-hand with probes that assert their own premises (`probe_identity_ns.py`: the control, one key for the registry and the episodes, reaches the agent 3 times; the case, a registry keyed by the slot id and episodes keyed by the sovereign id, reaches it 0 times and excludes 3 episodes as "empty recall"; `probe_checked_answer.py`: a stopped agent's refusal text and a silent agent's `[NO_RESPONSE]` each give 3 measured episodes at accuracy 0.00). The Architect designed the repair (consult `8cdddf05`, option A'); no Captain condition applies. Section 7 and the sections after it stand as committed; this section changes the code they produce, and its pairs apply after section 7's.

- **F1 (P1, ordinary reach; not a regression: the session was already inoperative): a crew agent's session never reaches the agent.** Crew episodes carry the sovereign UUID (`cognitive_agent.py` `agent_ids=[sovereign_id or id]`); the dream cycle emits it, so both triggers hand it to the Counselor; `AgentRegistry` is keyed by the slot id, and so are the callsign lookup, the profiles the sweep and telemetry read, and the DM channel (`WardRoomRouter.find_targets_for_agent` finds a DM's other participant by `agent.id[:8] in channel.name`). BF-907 is the convention (`startup/trust_identity.py`: "trust is keyed by slot id").
- **F2 (P2, a regression the repair under review introduced; ordinary reach once F1 is repaired): a refusal or a silence is scored as a recall.** `_send_probe` returns any truthy `result` and drops `success`, `error` and `metadata`; the Captain's stop (`AgentStopService.refuse_intent`: `success` False, the text in `result` and `error`, `STOP_METADATA_KEY` in `metadata`) and the agent's `[NO_RESPONSE]` (AD-672's queue-full shed, BF-239's engagement gate, the model choosing silence) therefore reached the judge.
- **Test 12** (the reviewer's note, not a finding): with no recall source `test_run_session_no_episodes` ended at the no-source guard and no longer tested the empty selection. Pair AX3 (the orchestrator's) gives it a recall source.

**Decision (A').** Startup binds BF-907's `AgentIdentityRegistry.resolve_slot_id` once (`finalize.py`, from `runtime.identity_registry`, set at Phase 2 entry) and passes it to `agent_recall_fn(registry, resolve_slot=...)` and to `set_reminiscence_engine(engine, resolve_slot=...)`. Both default to None, so a test with no resolver behaves as on the candidate. The Counselor resolves once at the top of `_initiate_reminiscence_session`. Rejected: the Counselor reading `self._runtime.identity_service` (`__new__`-built test Counselors have no runtime; the injected bound method is the trust precedent, and `IdentityService.resolve` calls the same method for a non-slot key); resolving only in the closure (the DM stays unroutable and the profile is written under a key that telemetry never reads); canonicalising at the two triggers (it moves where `retrieval_concerns` lives, BF-907's class, item R5 of #1820); an engine that takes both ids.

| Use | Key | Why |
|---|---|---|
| `run_session`, `_session_history`, `RecallResult.agent_id` | the memory key (the trigger's sovereign UUID) | episodes carry it |
| the recall dispatch (inside `agent_recall_fn`) | the slot, resolved | `AgentRegistry` is keyed by `agent.id` |
| the liveness gate, the callsign | the slot | `_resolve_agent_callsign` reads the registry |
| `_reminiscence_cooldowns` | the slot | both triggers then share one cooldown |
| the profile writes | the slot | telemetry and the sweep read the slot-keyed profile |
| `_send_therapeutic_dm`, `_dm_cooldowns`, `_record_intervention` | the slot | the channel is named from the recipient's id; BF-921's limit is "from all causes" |
| the event payload's `agent_id` | the slot | the profile's key; no session has ever emitted it |
| `retrieval_concerns` | unchanged (the event's key) | out of scope: item R5 |

A key that resolves to no live agent (the Counselor has a registry and `registry.get` is None) runs no session, takes no cooldown and logs one INFO line: nothing is spent. The closure keeps its own guard for an agent that disappears between the gate and the recall.

**The checked answer.** `_checked_recall(result)`, beside `agent_recall_fn`, raises `RecallUnavailable(reason)` (a new exception of `guided_reminiscence.py`, which owns the `recall_fn` protocol) and the engine records `"<ep id>: <reason>"` without a traceback:

| Shape | Reason |
|---|---|
| not an `IntentResult` (None: the agent did not handle the intent) | `no reply` |
| `STOP_METADATA_KEY` in `metadata` | `agent stopped` |
| `success` false, or a non-empty `error` | `agent reply failed` |
| the text holds `[NO_RESPONSE]` | `no response` |
| a successful reply with no text | returns "", recorded as `empty recall` |
| a key with no live agent | `no live agent` |
| `handle_intent` raises | propagates; recorded as `recall failed: <Type>` with the existing WARNING |

`_send_probe`'s `handle_intent` call moves into `_probe_intent_result`, which `_send_probe` and `_checked_recall`'s caller both use, so the `_qualification_test` marker has one home and AD-1343's census still finds exactly one `handle_intent` call in `qualification_tests.py` (pair SX1 renames its registry row; SX1 and QX1 land together). `_send_probe` returns the same text to its 18 other callers; one edge changes: the intent is now built inside its `try`, so an agent with no `.id` returns "" with the BF-140 warning instead of raising `AttributeError`.

**Amended.** Section 3, the `agent_recall_fn` row: the `handle_intent` call is in `_probe_intent_result`. Section 5: 31 cases (23 plus R1 to R3 and the five R4 cases). Section 8.1: the closure text gains the resolver, the checked answer, the slot keys, and "31 cases"; "Open: R1 to R5". Section 8.2: items R4 and R5 (17.10). Section 9: `_send_probe`'s result for its callers is unchanged. Section 10: rows RM1 to RM16 (17.11).

**Review.** Round 2 is a whole-candidate review: the repair changes the `recall_fn` protocol (a new exception the engine recognises), `_send_probe`'s internals (18 callers in three files), AD-1343's census fixture, the public `set_reminiscence_engine` signature and the meaning of the event payload's `agent_id`. Properties to verify: (1) each consumer reads the key of the table above; (2) no path takes the cooldown for an agent the Counselor cannot reach; (3) no refusal or silence is scored; (4) `_send_probe` returns the same text for every input that has an `.id`; (5) the census finds exactly one `handle_intent` call in `qualification_tests.py`.

### 17.1 `src/probos/cognitive/guided_reminiscence.py` (M-R1)

**GX1.**
SEARCH:
```python
    return bool(clauses) and all(_ABSTENTION_RE.search(clause) for clause in clauses)


# ---------------------------------------------------------------------------
# Data types
```
REPLACE:
```python
    return bool(clauses) and all(_ABSTENTION_RE.search(clause) for clause in clauses)


class RecallUnavailable(Exception):
    """BF-989 round 1 (#1838): a recall source found no recall to score; ``str(exc)`` is why the episode is unmeasured.

    Raised by ``recall_fn`` (``qualification_tests.agent_recall_fn``) for a key with no live agent and for a reply
    that is not a recall: the Captain's stop, a failed reply, or the agent's silence.
    """


# ---------------------------------------------------------------------------
# Data types
```

**GX2.**
SEARCH:
```python
            except TimeoutError:
                result.unmeasured.append(f"{ep_id}: recall timed out")
                continue
            except Exception as exc:
```
REPLACE:
```python
            except TimeoutError:
                result.unmeasured.append(f"{ep_id}: recall timed out")
                continue
            except RecallUnavailable as exc:
                # BF-989 round 1: no live agent, or a reply that is not a recall (stop, failure, silence)
                result.unmeasured.append(f"{ep_id}: {exc}")
                continue
            except Exception as exc:
```

### 17.2 `src/probos/cognitive/qualification_tests.py` (M-R1)

**QX1.**
SEARCH:
```python
async def _send_probe(agent: Any, message: str) -> str:
    """Send a probe message to an agent via handle_intent() with episode suppression.

    BF-140: Added exception handling. Captures and logs exceptions instead of
    propagating them to the probe's outer handler (which returns score=0.0
    with no diagnostic info).
    """
    from probos.types import IntentMessage

    intent = IntentMessage(
        intent="direct_message",
        params={"text": message, "_qualification_test": True},  # BF-109: was "message", but perceive() reads "text"
        target_agent_id=agent.id,
    )
    try:
        result = await agent.handle_intent(intent)
        if result and result.result:
            return str(result.result)
        return ""
    except Exception as exc:
        logger.warning(
            "BF-140: _send_probe failed for agent %s (type=%s): %s",
            getattr(agent, "id", "?"),
            getattr(agent, "agent_type", "?"),
            exc,
            exc_info=True,
        )
        return ""


def agent_recall_fn(registry: Any) -> Callable[[str, str], Awaitable[str]]:
    """The agent's own recall for guided reminiscence (BF-989, #1838), through ``_send_probe``.

    ``_send_probe`` marks the intent ``_qualification_test``, which suppresses episode storage
    (``CognitiveAgent.handle_intent``), so a recall attempt never becomes an episode that a later
    session could select as ground truth. An agent the registry does not hold recalls "".
    """

    async def _recall(agent_id: str, prompt: str) -> str:
        agent = registry.get(agent_id)
        if agent is None:
            return ""
        return await _send_probe(agent, prompt)

    return _recall
```
REPLACE:
```python
async def _probe_intent_result(agent: Any, message: str) -> Any:
    """Send a probe message to an agent via handle_intent() with episode suppression; return its reply as is.

    BF-989 round 1 (#1838): split out of ``_send_probe`` so guided reminiscence reads the whole ``IntentResult``
    (success, error, the stop metadata) on the same path and marker. Exceptions propagate.
    """
    from probos.types import IntentMessage

    intent = IntentMessage(
        intent="direct_message",
        params={"text": message, "_qualification_test": True},  # BF-109: was "message", but perceive() reads "text"
        target_agent_id=agent.id,
    )
    return await agent.handle_intent(intent)


async def _send_probe(agent: Any, message: str) -> str:
    """Send a probe message to an agent via handle_intent() with episode suppression.

    BF-140: Added exception handling. Captures and logs exceptions instead of
    propagating them to the probe's outer handler (which returns score=0.0
    with no diagnostic info).
    """
    try:
        result = await _probe_intent_result(agent, message)
        if result and result.result:
            return str(result.result)
        return ""
    except Exception as exc:
        logger.warning(
            "BF-140: _send_probe failed for agent %s (type=%s): %s",
            getattr(agent, "id", "?"),
            getattr(agent, "agent_type", "?"),
            exc,
            exc_info=True,
        )
        return ""


def _checked_recall(result: Any) -> str:
    """BF-989 round 1 (#1838): an agent's reply as recall text, or ``RecallUnavailable`` naming why it is not one.

    ``_send_probe`` keeps any truthy ``result``; a recall cannot. Not a recall: no ``IntentResult`` (the agent did
    not handle the intent); the Captain's stop (``AgentStopService.refuse_intent``: ``success`` False, the refusal
    text in ``result``, ``STOP_METADATA_KEY`` in ``metadata``); any other failed reply (``success`` False or an
    ``error``); a reply holding ``[NO_RESPONSE]``, the agent's silence (AD-672's queue-full shed, BF-239's
    engagement gate, or the model choosing silence). A successful reply with no text is returned as "", which the
    engine records as an empty recall.
    """
    from probos.agent_stop import STOP_METADATA_KEY
    from probos.cognitive.guided_reminiscence import RecallUnavailable
    from probos.types import IntentResult

    if not isinstance(result, IntentResult):
        raise RecallUnavailable("no reply")
    if STOP_METADATA_KEY in result.metadata:
        raise RecallUnavailable("agent stopped")
    if not result.success or result.error:
        raise RecallUnavailable("agent reply failed")
    text = "" if result.result is None else str(result.result)
    if "[NO_RESPONSE]" in text:
        raise RecallUnavailable("no response")
    return text


def agent_recall_fn(
    registry: Any, *, resolve_slot: Callable[[str], str | None] | None = None,
) -> Callable[[str, str], Awaitable[str]]:
    """The agent's own recall for guided reminiscence (BF-989, #1838), on ``_send_probe``'s path and marker.

    The intent is marked ``_qualification_test``, which suppresses episode storage (``CognitiveAgent.handle_intent``),
    so a recall attempt never becomes an episode that a later session could select as ground truth.
    BF-989 round 1: ``resolve_slot`` maps the memory key the engine holds (the sovereign UUID episodes carry) to the
    slot id the registry keys by (BF-907); a key it does not resolve is looked up as given. A key with no live agent,
    and a reply that is not a recall (``_checked_recall``), raise ``RecallUnavailable``; the engine records the reason.
    """

    async def _recall(agent_id: str, prompt: str) -> str:
        slot_id = (resolve_slot(agent_id) if resolve_slot is not None else None) or agent_id
        agent = registry.get(slot_id)
        if agent is None:
            from probos.cognitive.guided_reminiscence import RecallUnavailable

            raise RecallUnavailable("no live agent")
        return _checked_recall(await _probe_intent_result(agent, prompt))

    return _recall
```

### 17.3 `tests/fixtures/ad1343_seam_registry.py` (M-R1)

**SX1.**
SEARCH:
```python
    ("src/probos/cognitive/qualification_tests.py", "_send_probe", "handle_intent"): ("sink", _INTENT_SINK),
```
REPLACE:
```python
    ("src/probos/cognitive/qualification_tests.py", "_probe_intent_result", "handle_intent"): ("sink", _INTENT_SINK),
```

### 17.4 `src/probos/cognitive/counselor.py` (M-R1)

**CX1.**
SEARCH:
```python
import json
import logging
import time
from dataclasses import dataclass, field
```
REPLACE:
```python
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
```

**CX2.**
SEARCH:
```python
        self._reminiscence_engine: Any = None  # Set via set_reminiscence_engine()
        self._reminiscence_cooldowns: dict[str, float] = {}
```
REPLACE:
```python
        self._reminiscence_engine: Any = None  # Set via set_reminiscence_engine()
        # BF-989 round 1: a memory key (the sovereign UUID episodes carry) -> the slot id the registry, profiles and
        # DMs key by; None for a key that is already a slot or is unknown (BF-907). Set with the engine.
        self._reminiscence_resolve_slot: Callable[[str], str | None] | None = None
        self._reminiscence_cooldowns: dict[str, float] = {}
```

**CX3.**
SEARCH:
```python
    def set_reminiscence_engine(self, engine: Any) -> None:
        """Wire the guided reminiscence engine (AD-541d)."""
        self._reminiscence_engine = engine
```
REPLACE:
```python
    def set_reminiscence_engine(
        self, engine: Any, *, resolve_slot: Callable[[str], str | None] | None = None,
    ) -> None:
        """Wire the guided reminiscence engine (AD-541d).

        BF-989 round 1: ``resolve_slot`` maps the key a trigger holds (the sovereign UUID episodes carry) to the live
        agent's slot id; startup binds ``AgentIdentityRegistry.resolve_slot_id`` (BF-907).
        """
        self._reminiscence_engine = engine
        self._reminiscence_resolve_slot = resolve_slot
```

**CX4.**
SEARCH:
```python
    async def _initiate_reminiscence_session(self, agent_id: str, trigger: str = "concern") -> None:
        """Initiate a guided reminiscence session for an agent with memory concerns."""
        if not self._reminiscence_engine:
            return

        callsign = self._resolve_agent_callsign(agent_id)
```
REPLACE:
```python
    async def _initiate_reminiscence_session(self, agent_id: str, trigger: str = "concern") -> None:
        """Initiate a guided reminiscence session for an agent with memory concerns.

        BF-989 round 1 (#1838): ``agent_id`` is the key the trigger holds, the sovereign UUID a crew agent's episodes
        carry. The engine reads episodes by that key; the live agent, its callsign, the cooldown, the profile, the DM
        and the event use the slot id it resolves to (BF-907: the registry and the Counselor key by slot). A key with
        no live agent runs no session and takes no cooldown: nothing is spent.
        """
        if not self._reminiscence_engine:
            return

        memory_key = agent_id
        resolve_slot = self._reminiscence_resolve_slot
        agent_id = (resolve_slot(memory_key) if resolve_slot is not None else None) or memory_key
        if self._registry is not None and self._registry.get(agent_id) is None:
            logger.info("AD-541d: no reminiscence session for %s: no live agent", memory_key[:8])
            return

        callsign = self._resolve_agent_callsign(agent_id)
```

**CX5.**
SEARCH:
```python
        try:
            result = await self._reminiscence_engine.run_session(agent_id)
        except Exception:
            # BF-989: WARNING, not DEBUG (log-and-degrade); the cooldown bounds it to once per agent per cooldown
            logger.warning("AD-541d: Reminiscence session failed for %s", agent_id[:8], exc_info=True)
```
REPLACE:
```python
        try:
            result = await self._reminiscence_engine.run_session(memory_key)  # BF-989 round 1: episodes carry this key
        except Exception:
            # BF-989: WARNING, not DEBUG (log-and-degrade); the cooldown bounds it to once per agent per cooldown
            logger.warning("AD-541d: Reminiscence session failed for %s", callsign, exc_info=True)
```

### 17.5 `src/probos/startup/finalize.py` (M-R1)

**FX1.**
SEARCH:
```python
                    from probos.cognitive.qualification_tests import agent_recall_fn  # BF-989

                    reminiscence_engine = GuidedReminiscenceEngine(
```
REPLACE:
```python
                    from probos.cognitive.qualification_tests import agent_recall_fn  # BF-989

                    # BF-989 round 1: episodes carry the sovereign UUID; the registry, callsigns, profiles and DMs key by
                    # slot id (BF-907). The identity registry is set at Phase 2 entry, before finalize.
                    reminiscence_identities = getattr(runtime, "identity_registry", None)
                    reminiscence_resolve_slot = (
                        reminiscence_identities.resolve_slot_id if reminiscence_identities is not None else None
                    )
                    reminiscence_engine = GuidedReminiscenceEngine(
```

**FX2.**
SEARCH:
```python
                        recall_fn=agent_recall_fn(runtime.registry),
                    )
                    counselor_agent.set_reminiscence_engine(reminiscence_engine)
```
REPLACE:
```python
                        recall_fn=agent_recall_fn(runtime.registry, resolve_slot=reminiscence_resolve_slot),
                    )
                    counselor_agent.set_reminiscence_engine(reminiscence_engine, resolve_slot=reminiscence_resolve_slot)
```

### 17.6 `tests/test_ad541d_guided_reminiscence.py` (M-R1)

**AX1.**
SEARCH:
```python
    agent._reminiscence_engine = None
    agent._reminiscence_cooldowns = {}
```
REPLACE:
```python
    agent._reminiscence_engine = None
    agent._reminiscence_resolve_slot = None  # BF-989 round 1: set with the engine at startup
    agent._reminiscence_cooldowns = {}
```

**AX2.** (test 28):
SEARCH:
```python
        # BF-989 (#1838): the engine is wired with the agent's own recall (behaviour: test_bf989 N2 and N7)
        assert "recall_fn=agent_recall_fn(runtime.registry)" in source
```
REPLACE:
```python
        # BF-989 (#1838): the engine is wired with the agent's own recall (behaviour: test_bf989 N2 and N7); round 1:
        # the recall and the Counselor share BF-907's resolver (behaviour: test_bf989 R1)
        assert "reminiscence_identities.resolve_slot_id" in source
        assert "recall_fn=agent_recall_fn(runtime.registry, resolve_slot=reminiscence_resolve_slot)" in source
        assert "set_reminiscence_engine(reminiscence_engine, resolve_slot=reminiscence_resolve_slot)" in source
```

**AX3.** (test 12; the reviewer's note: with no recall source the test ended at the no-source guard and no longer tested the empty selection)
SEARCH:
```python
        engine = _make_engine(episodes=[])
        result = await engine.run_session("a1")
        assert result.episodes_tested == 0

```
REPLACE:
```python
        # BF-989 round 1: with a recall source the empty selection is what ends the session (with none, the
        # no-source guard did, before the selection ran)
        recall = AsyncMock(return_value="unused")
        engine = _make_engine(episodes=[], recall_fn=recall)
        result = await engine.run_session("a1")
        assert result.episodes_tested == 0
        assert result.unmeasured == []  # nothing was selected, so nothing is held out
        recall.assert_not_awaited()

```

### 17.7 `tests/test_bf989_guided_reminiscence_recall.py` (M-R1)

**TX1.**
SEARCH:
```python
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.counselor import CognitiveProfile
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.cognitive.guided_reminiscence import GuidedReminiscenceEngine, RecallClassification, RecallResult
from probos.types import LLMResponse
from tests.test_ad541d_guided_reminiscence import _make_counselor, _make_episode
```
REPLACE:
```python
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.agent_stop import STOP_METADATA_KEY, AgentStopService
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.concurrency_manager import ConcurrencyManager
from probos.cognitive.counselor import CognitiveProfile
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.cognitive.guided_reminiscence import (
    GuidedReminiscenceEngine,
    RecallClassification,
    RecallResult,
    RecallUnavailable,
)
from probos.cognitive.llm_client import MockLLMClient
from probos.cognitive.qualification_tests import agent_recall_fn
from probos.identity import AgentIdentityRegistry
from probos.substrate.registry import AgentRegistry
from probos.types import IntentDescriptor, IntentResult, LLMResponse
from tests.test_ad541d_guided_reminiscence import _make_counselor, _make_episode
```

**TX2.** (N7).
SEARCH:
```python
async def test_agent_recall_fn_asks_the_agent_on_the_probe_path() -> None:
    from probos.cognitive.qualification_tests import agent_recall_fn  # imported here: only this case needs the new name

    class _Agent:
        id = "a1"
        agent_type = "crew"

        def __init__(self) -> None:
            self.intents: list[Any] = []

        async def handle_intent(self, intent: Any) -> Any:
            self.intents.append(intent)
            return SimpleNamespace(result="I checked the warp core.")

    agent = _Agent()
    recall = agent_recall_fn(SimpleNamespace(get=lambda agent_id: agent if agent_id == "a1" else None))
    assert await recall("a1", "What happened?") == "I checked the warp core."
    (intent,) = agent.intents
    assert (intent.intent, intent.target_agent_id, intent.params["text"]) == ("direct_message", "a1", "What happened?")
    assert intent.params["_qualification_test"] is True  # suppresses episode storage (CognitiveAgent.handle_intent)
    assert await recall("zz", "What happened?") == ""
    assert len(agent.intents) == 1
```
REPLACE:
```python
async def test_agent_recall_fn_asks_the_agent_on_the_probe_path() -> None:
    class _Agent:
        """As the runtime holds a crew agent: registered by its slot id; its episodes carry its sovereign id."""

        id = "slot-a1"
        sovereign_id = "a1"
        agent_type = "crew"

        def __init__(self) -> None:
            self.intents: list[Any] = []

        async def handle_intent(self, intent: Any) -> IntentResult:
            self.intents.append(intent)
            return IntentResult(intent_id=intent.id, agent_id=self.id, success=True, result="I checked the warp core.")

    agent = _Agent()
    registry = SimpleNamespace(get=lambda key: agent if key == agent.id else None)
    recall = agent_recall_fn(registry, resolve_slot={"a1": "slot-a1"}.get)
    assert await recall("a1", "What happened?") == "I checked the warp core."
    (intent,) = agent.intents
    assert (intent.intent, intent.target_agent_id, intent.params["text"]) == ("direct_message", "slot-a1", "What happened?")
    assert intent.params["_qualification_test"] is True  # suppresses episode storage (CognitiveAgent.handle_intent)
    assert await agent_recall_fn(registry)("slot-a1", "Again?") == "I checked the warp core."  # a slot key as given
    with pytest.raises(RecallUnavailable, match="^no live agent$"):
        await recall("zz", "What happened?")
    with pytest.raises(RecallUnavailable, match="^no live agent$"):
        await agent_recall_fn(registry)("a1", "What happened?")  # no resolver: the sovereign key reaches no agent
    assert len(agent.intents) == 2
```

**TX3.** (appended):
SEARCH:
```python
    (line,) = [r.getMessage() for r in caplog.records if "measured no episode" in r.getMessage()]
    assert "ep-0: empty recall" in line
```
REPLACE:
```python
    (line,) = [r.getMessage() for r in caplog.records if "measured no episode" in r.getMessage()]
    assert "ep-0: empty recall" in line


# -- R1 to R4: review round 1 (a crew agent's slot and sovereign ids; a reply that is not a recall) ----------------

_SLOT = "surgeon_medical_surgeon_0_b2321292"
_INSTANCE = "bf989-ship"


class _CrewAgent:
    """A crew agent as the runtime holds one: registered by its slot id; its episodes carry its sovereign id."""

    agent_type = "surgeon"
    pool = "surgeon"
    callsign = "Meridian"

    def __init__(self, sovereign_id: str) -> None:
        self.id = _SLOT
        self.sovereign_id = sovereign_id
        self.intents: list[Any] = []

    async def handle_intent(self, intent: Any) -> IntentResult:
        self.intents.append(intent)
        return IntentResult(intent_id=intent.id, agent_id=self.id, success=True, result=_RECALL)


async def test_a_session_on_the_sovereign_id_measures_and_writes_through_the_slot(tmp_path: Path) -> None:
    identities = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await identities.start()
        await identities.start(instance_id=_INSTANCE, vessel_name="Bf989", version="1")
        cert = await identities.resolve_or_issue(
            slot_id=_SLOT, agent_type="surgeon", callsign="Meridian", instance_id=_INSTANCE,
            vessel_name="Bf989", department="medical", post_id="surgeon", baseline_version="v1",
        )
        sovereign = cert.agent_uuid
        assert sovereign != _SLOT and identities.resolve_slot_id(sovereign) == _SLOT  # premise: BF-907's split
        agent, registry, memory = _CrewAgent(sovereign), AgentRegistry(), MockEpisodicMemory()
        await registry.register(agent)
        for i in range(4):
            await memory.store(_make_episode(ep_id=f"ep-{i}", timestamp=1000.0 + i * 100, agent_ids=[sovereign]))
        engine = GuidedReminiscenceEngine(
            episodic_memory=memory, llm_client=_Client(), max_episodes_per_session=3,
            recall_fn=agent_recall_fn(registry, resolve_slot=identities.resolve_slot_id),
        )
        ward_room, events = _ward_room(), []
        counselor = _make_counselor(
            _registry=registry, _ward_room=ward_room, callsign="Counselor", _record_intervention=MagicMock(),
            _emit_event_fn=lambda name, payload: events.append((name, payload)),
        )
        counselor.set_reminiscence_engine(engine, resolve_slot=identities.resolve_slot_id)
        await counselor._initiate_reminiscence_session(sovereign, trigger="retrieval_concern")
    finally:
        await identities.stop()
    assert [intent.target_agent_id for intent in agent.intents] == [_SLOT] * 3
    profile = counselor._cognitive_profiles[_SLOT]
    assert profile.memory_integrity_score == pytest.approx(0.9)
    assert profile.reminiscence_sessions == 1
    assert sovereign not in counselor._cognitive_profiles
    assert list(counselor._reminiscence_cooldowns) == [_SLOT]
    dm = ward_room.get_or_create_dm_channel.await_args.kwargs
    assert (dm["agent_b_id"], dm["callsign_b"]) == (_SLOT, "Meridian")
    assert list(counselor._dm_cooldowns) == [_SLOT]
    ((name, payload),) = events
    assert (name, payload["agent_id"], payload["episodes_tested"], payload["unmeasured"]) == (
        "reminiscence_session_complete", _SLOT, 3, 0,
    )


async def test_a_key_with_no_live_agent_runs_no_session_and_takes_no_cooldown(caplog: pytest.LogCaptureFixture) -> None:
    engine = SimpleNamespace(run_session=AsyncMock())
    counselor = _make_counselor(_reminiscence_engine=engine, _registry=AgentRegistry())
    caplog.set_level(logging.INFO, logger="probos.cognitive.counselor")
    await counselor._initiate_reminiscence_session("a1", trigger="bf989")
    engine.run_session.assert_not_awaited()
    assert counselor._reminiscence_cooldowns == {}
    assert [r.levelno for r in caplog.records if "no live agent" in r.getMessage()] == [logging.INFO]


def _crew_class() -> type[CognitiveAgent]:
    return type("_BF989Crew", (CognitiveAgent,), {
        "agent_type": "surgeon",
        "_handled_intents": {"bf989_probe"},
        "instructions": "You are a crew member. Respond concisely.",
        "intent_descriptors": [IntentDescriptor(name="bf989_probe", params={}, description="probe", tier="domain")],
    })


class _CountingLLM(MockLLMClient):
    """The agent's model: counts calls; a stopped or saturated agent makes none."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:  # type: ignore[override]
        self.calls += 1
        return LLMResponse(content=_RECALL)


async def _session_of(agent: CognitiveAgent, client: _Client) -> Any:
    registry, memory = AgentRegistry(), MockEpisodicMemory()
    await registry.register(agent)
    for i in range(4):
        await memory.store(_make_episode(ep_id=f"ep-{i}", timestamp=1000.0 + i * 100, agent_ids=[agent.id]))
    engine = GuidedReminiscenceEngine(
        episodic_memory=memory, llm_client=client, max_episodes_per_session=3, recall_fn=agent_recall_fn(registry),
    )
    return await engine.run_session(agent.id)


async def test_a_stopped_or_saturated_agent_gives_no_recall(tmp_path: Path) -> None:
    stopped_llm, saturated_llm, client = _CountingLLM(), _CountingLLM(), _Client()
    stopped = _crew_class()(llm_client=stopped_llm)
    stops = AgentStopService(data_dir=tmp_path / "stops")
    await stops.start()
    try:
        await stops.issue_stop(stopped.id, reason="BF-989 test: this agent is stopped")
        stopped._runtime = SimpleNamespace(agent_stops=stops)
        result = await _session_of(stopped, client)
    finally:
        await stops.stop()
    assert (result.episodes_tested, result.unmeasured) == (0, [f"ep-{i}: agent stopped" for i in range(3)])

    saturated = _crew_class()(llm_client=saturated_llm)
    manager = ConcurrencyManager(saturated.id, max_concurrent=1, queue_max_size=0)
    saturated.set_concurrency_manager(manager)
    held = await manager.acquire("held")
    try:
        result = await _session_of(saturated, client)
    finally:
        await manager.release(held)
    assert (result.episodes_tested, result.unmeasured) == (0, [f"ep-{i}: no response" for i in range(3)])
    assert (stopped_llm.calls, saturated_llm.calls, client.prompts) == (0, 0, [])  # no turn, no judge, no message


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        pytest.param(None, "no reply", id="none"),
        pytest.param(
            IntentResult(intent_id="i", agent_id=_SLOT, success=False, result="Not delivered", error="Not delivered",
                         metadata={STOP_METADATA_KEY: {}}),
            "agent stopped", id="stop",
        ),
        pytest.param(IntentResult(intent_id="i", agent_id=_SLOT, success=False, result="partial"),
                     "agent reply failed", id="failed"),
        pytest.param(IntentResult(intent_id="i", agent_id=_SLOT, success=True, result="text", error="cognitive_failed"),
                     "agent reply failed", id="error"),
        pytest.param(IntentResult(intent_id="i", agent_id=_SLOT, success=True, result="Noted. [NO_RESPONSE]"),
                     "no response", id="silence"),
    ],
)
async def test_a_reply_that_is_not_a_recall_names_its_reason(reply: Any, reason: str) -> None:
    class _Agent:
        id = _SLOT
        agent_type = "surgeon"

        async def handle_intent(self, intent: Any) -> Any:
            return reply

    recall = agent_recall_fn(SimpleNamespace(get=lambda key: _Agent() if key == _SLOT else None))
    with pytest.raises(RecallUnavailable, match=f"^{reason}$"):
        await recall(_SLOT, "What happened?")
```

### 17.8 `PROGRESS.md` (M-R2)

**PX1.** A substring inside the BF-989 entry (once).

SEARCH (substring): `` which startup wires to the new `qualification_tests.agent_recall_fn(registry)` (AD-566's `_send_probe`, whose `_qualification_test` marker suppresses episode storage) ``
REPLACE: `` which startup wires to the new `qualification_tests.agent_recall_fn(registry, resolve_slot=...)` (BF-907's resolver maps the sovereign UUID that episodes carry to the live agent's slot; AD-566's path, whose `_qualification_test` marker suppresses episode storage) ``

**PX2.** A substring inside the BF-989 entry (once).

SEARCH (substring): `` An empty, failed or timed-out recall and an inconclusive judge (BF-711) leave the episode unmeasured ``
REPLACE: `` An empty, failed or timed-out recall, a reply that is not a recall (the Captain's stop, a failed reply, `[NO_RESPONSE]`), a key with no live agent and an inconclusive judge (BF-711) leave the episode unmeasured ``

**PX3.** A substring inside the BF-989 entry (once).

SEARCH (substring): `` The Counselor takes the cooldown before the session, logs a failed session at WARNING, ``
REPLACE: `` The Counselor resolves the trigger's key to the slot (profile, cooldown, DM and event; no live agent: no session, no cooldown), takes the cooldown before the session, logs a failed session at WARNING, ``

**PX4.** A substring inside the BF-989 entry (once).

SEARCH (substring): `` (23 cases). Not measured: how often a live session runs and the live effect of its DM. Open items bf-989 R1 to R3 of #1820. ``
REPLACE: `` (31 cases). Not measured: how often a live session runs and the live effect of its DM. Open items bf-989 R1 to R5 of #1820. ``

### 17.9 `DECISIONS.md` (M-R2)

**DX1.** A substring inside the BF-989 entry (once).

SEARCH (substring): `` Startup passes `qualification_tests.agent_recall_fn(runtime.registry)`, which asks the agent through `_send_probe`; ``
REPLACE: `` Startup passes `qualification_tests.agent_recall_fn(runtime.registry, resolve_slot=...)`, bound to BF-907's `AgentIdentityRegistry.resolve_slot_id`: episodes carry the sovereign UUID and the registry keys by slot, so the key is resolved before the agent is asked, on `_send_probe`'s path (`_probe_intent_result`); ``

**DX2.** A substring inside the BF-989 entry (once).

SEARCH (substring): `` *Unmeasured.* An empty, failed or timed-out recall and an inconclusive judge (`score_recall_outcome`, BF-711) ``
REPLACE: `` *Unmeasured.* An empty, failed or timed-out recall, a reply that is not a recall (no reply, the Captain's stop, a failed reply, `[NO_RESPONSE]`), a key with no live agent and an inconclusive judge (`score_recall_outcome`, BF-711) ``

**DX3.** A substring inside the BF-989 entry (once).

SEARCH (substring): `` - *Writes.* The cooldown is taken before the session (no await between check and set); ``
REPLACE: `` - *Writes.* The Counselor resolves the trigger's key once: the profile, cooldown, DM and event use the slot id (the DM channel is otherwise unroutable); a key with no live agent runs no session and takes no cooldown. The cooldown is taken before the session (no await between check and set); ``

**DX4.** A substring inside the BF-989 entry (once).

SEARCH (substring): `` - *Residual.* #1820 items bf-989 R1 to R3. ``
REPLACE: `` - *Residual.* #1820 items bf-989 R1 to R5. ``

### 17.10 Issue texts

**Closure comment on #1838 (8.1), amended:** the Recall bullet adds "with BF-907's resolver (the sovereign UUID that episodes carry is mapped to the live agent's slot)"; the Measured-only bullet adds "a reply that is not a recall (the Captain's stop, a failed reply, `[NO_RESPONSE]`) and a key with no live agent"; the Writes bullet adds "on the agent's slot id (profile, cooldown, DM, event); no live agent: no session, no cooldown"; "(23 cases)" becomes "(31 cases)"; acceptance item 2 adds `test_a_session_on_the_sovereign_id_measures_and_writes_through_the_slot` (a real `AgentIdentityRegistry`) and `test_a_stopped_or_saturated_agent_gives_no_recall` (a real `CognitiveAgent`, `AgentStopService` and `ConcurrencyManager`); "Open: R1 to R3" becomes "R1 to R5".

**New items on #1820 (8.2), in addition to R1 to R3:**

- `- [ ] **bf-989 R4 (P3, Medium; pre-existing; measured by a probe on the mock): AD-566 D2 cannot fail for a crew agent whose sovereign id differs from its slot id.** \`EpisodicRecallProbe\` counts and reads episodes by the id the harness is given (\`qualification_tests.py\` \`count_for_agent\` and \`recent_for_agent\` in \`EpisodicRecallProbe.run\`), which is the slot id (\`drift_detector._get_crew_agent_ids\` returns \`agent.id\`, "NOT sovereign IDs"; \`commands_qualification.py:121\` passes \`agent.id\`). Crew episodes carry the sovereign UUID (\`cognitive_agent.py\` \`agent_ids=[sovereign_id or id]\`), and \`count_for_agent\` matches the key exactly (\`agent_id in agent_ids\`, in the store and in \`MockEpisodicMemory\`). Probe of 2026-11-21 (premises asserted; \`probe_r4.py\`): with the episodes keyed by the slot id the probe asks the agent 3 times and scores 0.9; with them keyed by the sovereign id it returns \`skipped: insufficient_episodes\`, score 1.0, passed, and never asks the agent. Reach: every drift run and \`/qualify\`, every such agent. Repair: memory reads by \`resolve_sovereign_id(agent)\` (as \`memory_probes._resolve_probe_agent_id\` does), the registry by slot.`
- `- [ ] **bf-989 R5 (P3, Low; pre-existing, BF-907's class; read, not run): AD-541c concerns are stored on a profile keyed by the sovereign UUID.** \`_on_retrieval_practice_concern\` writes \`retrieval_concerns\` under the event's key (the dream cycle emits the episodes' ids: \`dreaming.py\` \`_step_11_retrieval_practice\`), a second profile beside the slot-keyed one that the sweep (\`counselor.py\` \`for meta in all_agents\`), telemetry (\`cognitive_agent.py\`) and BF-989's session use. So the sweep's concern check never sees a concern, \`/counselor\` lists the sovereign profile as a separate agent, and a departed agent's concerns log one INFO "no live agent" line per trigger. Repair: resolve at the handler, with a migration of stored sovereign-keyed profiles (stored data: check the Captain conditions then).`

### 17.11 Mutation rows (the campaign of record on the repaired tree; restore between rows; each killer at `-n 0`)

| M | Mutation | Killers |
|---|---|---|
| RM1 | QX1: `slot_id = agent_id` (ignore the resolver) | N7, R1 |
| RM2 | CX5: `run_session(agent_id)` | R1 |
| RM3 | CX4: delete the resolve line (`agent_id` stays the memory key) | R1 |
| RM4 | CX4: delete the liveness gate | R2 |
| RM5 | CX4: move the gate after the cooldown set | R2 |
| RM6 | CX4/CX5: `_get_or_create_profile(memory_key)` | R1 |
| RM7 | CX4/CX5: `_send_therapeutic_dm(memory_key, ...)` | R1 |
| RM8 | QX1: delete the stop check | R4[stop], R3 |
| RM9 | QX1: `if result.error:` (drop `not result.success`) | R4[failed] |
| RM10 | QX1: `if not result.success:` (drop `or result.error`) | R4[error] |
| RM11 | QX1: delete the `[NO_RESPONSE]` check | R4[silence], R3 |
| RM12 | QX1: delete the `isinstance` check | R4[none] |
| RM13 | GX2: delete `except RecallUnavailable` | R3 |
| RM14 | QX1: `if agent is None: return ""` | N7 |
| RM15 | FX1/FX2: drop either `resolve_slot=` | AD-541d test 28 |
| RM16 | QX1: the closure calls `_send_probe` instead of `_checked_recall(await _probe_intent_result(...))` | R3, R4 |

RM15 is run as two rows, RM15a (FX1: drop `resolve_slot=` from `agent_recall_fn(...)`) and RM15b (FX2: drop it from `set_reminiscence_engine(...)`); each is killed by AD-541d test 28. That makes 17 rows.

### 17.12 The orchestrator's first-hand checks of the repair (2026-11-21, an oracle tree at `86b9c156` whose touched files hold the candidate's blobs plus the pairs of 17.1 to 17.9)

Every pair of 17.1 to 17.9 was applied to a scratch worktree by `audit\contract_tools.py`, and every check below was run, before the Builder starts. The focused gate and the consumer set ran under the default embeddings and under `PROBOS_EMBEDDINGS=local`, as CI runs them. In this section R1 to R4 name the four new tests of TX3 (`test_a_session_on_the_sovereign_id_measures_and_writes_through_the_slot`, `test_a_key_with_no_live_agent_runs_no_session_and_takes_no_cooldown`, `test_a_stopped_or_saturated_agent_gives_no_recall` and `test_a_reply_that_is_not_a_recall_names_its_reason`, which has five cases: none, stop, failed, error, silence); the items of #1820 are always written "bf-989 R4" and "bf-989 R5".

| RO | Result |
|---|---|
| RO1 | The 25 operations (GX1-GX2, QX1, SX1, CX1-CX5, FX1-FX2, AX1-AX3, TX1-TX3, PX1-PX4, DX1-DX4) are found by `contract_tools.py list --prefix 17.`, and each SEARCH occurs exactly once on the candidate, in files that are CRLF throughout. |
| RO2 | Tests first (the candidate, GX1 so that the module imports, and the test pairs AX1-AX3 and TX1-TX3): 10 failed, 236 passed, 2 skipped. The reds: N7 and R1 by `TypeError: agent_recall_fn() got an unexpected keyword argument 'resolve_slot'`; R2 by `Expected mock to not have been awaited. Awaited 1 times.` (the session ran for a key with no live agent); R3 by `assert (3, []) == (0, ['ep-0: a...ent stopped'])` (three measured episodes where none is wanted); the five cases of R4 by `DID NOT RAISE RecallUnavailable`; AD-541d test 28 (`TestD4D5D6::test_startup_wiring_reminiscence_engine`) by the assertion that `finalize.py` holds `reminiscence_identities.resolve_slot_id`. |
| RO3 | All the code and test pairs applied (GX1-GX2, QX1, SX1, CX1-CX5, FX1-FX2, AX1-AX3, TX1-TX3): the nine-file focused gate gives 246 passed, 2 skipped under the default embeddings and under `PROBOS_EMBEDDINGS=local` (24.7 s each). The two skips are `test_bf139_140_probe_hardening.py:229` and `:262` (the sentence-transformers model is offline); they skip on the base too. |
| RO4 | A consumer set of 52 files (the 37 of O4 plus 15 neighbours: the tests of the identity resolvers that the repair binds, `test_bf907_trust_identity`, `test_bf138_sovereign_id_completion`, `test_ad1346_identity_service` and its `_boot`, `test_ad1343_agent_stop`, `test_ad1347_s4_ward_room_lookup`, and of the sibling probe modules, `test_ad566d_domain_tests`, `test_ad582_memory_probes`, `test_bf147` to `test_bf152`, `test_ad1340_s1_erasure`): 1352 passed, 2 skipped under each setting (204 s and 194 s). |
| RO5 | The probe of the repaired path (`probe_repaired.py`, premises P0-P4 asserted, a real `AgentIdentityRegistry`, episodes keyed by the sovereign UUID, the registry by slot): with no resolver bound (the wiring of the candidate) the handler is called 0 times and the 3 episodes are excluded as `no live agent`; with `resolve_slot_id` bound it is called 3 times and nothing is unmeasured; a reply with `success` False is excluded as `agent reply failed` and a `[NO_RESPONSE]` reply as `no response`, 3 episodes each. The reason `agent stopped` (`STOP_METADATA_KEY`) is not in this probe; R4[stop] shows it on a constructed reply, and R3 with a real `CognitiveAgent`, `AgentStopService` and `ConcurrencyManager`. |
| RO6 | The probe of item bf-989 R4 (`probe_r4.py`, premises P0-P2 asserted): AD-566's `EpisodicRecallProbe`, run for the slot id, with the episodes keyed by the slot id asks the agent 3 times and scores 0.9; with them keyed by the sovereign id it returns `skipped: insufficient_episodes`, score 1.0, passed, and never asks the agent. |
| RO7 | The campaign of 17.11 (`audit\mutants_gen.py` with `audit\rows_bf989r.py`) on the repaired tree, whose four test files (the new one, `test_ad541d_guided_reminiscence.py`, `test_bf988_llm_response_text.py` and `test_ad566b_baseline_tests.py`) give 132 cases, all green unmutated: **all 17 rows are killed, none survived, none differs, and none is invalid: every named killer failed in every row, and no case outside the named killers failed (extras 0).** Cases per row: RM1 2 (N7, R1), RM2-RM7 1 each, RM8 2 (R4[stop], R3), RM9 and RM10 1 each, RM11 2 (R4[silence], R3), RM12-RM14 1 each, RM15a and RM15b 1 each (test 28), RM16 6 (R3 and the five cases of R4). Every row restored its file: the base table below was recomputed after the campaign and equals the one printed before it. |
| RO8 | The trackers PX1-PX4 and DX1-DX4 applied on the oracle (each SEARCH once; `PROGRESS.md` 1788 lines and `DECISIONS.md` 13499 lines, unchanged, because every pair edits inside a line), and `gen_ad_ledger.py --check` reports "AD/BF ledger is current". The candidate's ledger pair (captured at `8e1689fa`) stands: the ledger reads the AD and BF headings and status lines, which the pairs do not touch, and the two files differ from a regeneration on the base only in the captured head, time and subject count. |

The base of the campaign of record (the files after 17.1 to 17.9; blob id, sha256 of the LF text, lines):

| File | Blob | sha256 (LF text) | Lines |
|---|---|---|---|
| `src/probos/cognitive/guided_reminiscence.py` | `3c05a533f0de75061c53cabaaf1f3590842478da` | `17d9718eaf1f7e0051664984bb5f1ea88eaefd528099ad6569c495f1737f4e28` | 578 |
| `src/probos/cognitive/qualification_tests.py` | `e43529461f52c21f00d11497554e4a42fb68513e` | `6840877fc8a0a45d880a2ed953a1c9b43a593d1e156b1ed876423c83ea969236` | 911 |
| `src/probos/startup/finalize.py` | `44731aefe63d115c969c20dbe0438f6977bbab3c` | `f650a6cd9af2a4df3feb1f21e15e126aea954e741f343c54b64981c909b65cbb` | 6890 |
| `src/probos/cognitive/counselor.py` | `c910b4821a27d3395d05e5b1859fa1094a330f57` | `c1875b4275312d9fd4fd0615a6c72a4d9f77aecd6139203ff4fddf5e07d8e55b` | 2963 |
| `tests/fixtures/ad1343_seam_registry.py` | `aee6211c05c5d6f2e3fc1ce8b49ca96a67d2c7aa` | `fa0bec869b60bc5eb10d7a1c48d33e00523c1d3a6120f1f55fde2aba20259a75` | 280 |
| `tests/test_bf989_guided_reminiscence_recall.py` | `369ee3e05e5b8a3036fb6802d34063d3a8878543` | `245df34ce98c952f4ad8c2993a74134fd17b64f1eb622c9381ab3ff2db80591b` | 486 |
| `tests/test_ad541d_guided_reminiscence.py` | `267092e9256c416a40379ede91a818e0289ad4a9` | `45ea814048352f459a3a0b87ae9337f6702d1a155b57f80e756f1c64b5710920` | 574 |
| `tests/test_bf988_llm_response_text.py` (not edited by the repair) | `eae60c541a2851d90a8e2e2f35741304c96f61c1` | `7b9af12869d026eba3787c5d98e60ee7bc4d0e64afb697e06fba02cee721635f` | 474 |

After the trackers: `PROGRESS.md` `bc81b247a62bb199c40a9e41b868828d4ca0d4c6` and `DECISIONS.md` `91ec5c09c3a383dc4c3af0f5bad56147d792f58a` (1788 and 13499 lines).

**What the orchestrator changed in the Architect's draft of the repair** (the rest is the draft's): the pair labels are `GX1` and so on where the draft wrote `G-R1`; the test pairs import `RecallUnavailable` at the top of the file (TX1 holds the parenthesised import, and TX2 and TX3 drop the draft's function-level imports, which were there for a red column and would leave a stale comment); pair AX3 (AD-541d test 12 keeps testing the empty selection, the reviewer's note) and the tracker pairs PX1-PX4 and DX1-DX4 are the orchestrator's own; the evidence of item bf-989 R4 in 17.10 is the probe of RO6, narrowed to the callers that were read (`drift_detector._get_crew_agent_ids`, which returns `agent.id`, and `commands_qualification.py`), where the draft read it without running anything.

What the tests and the probes do not show, stated plainly: no vessel has run a session, so the live registry's contents, the live agents' replies and the cost of a live session are not measured; the sovereign-to-slot mapping is exercised with a real `AgentIdentityRegistry`, and the stop reason with a real `CognitiveAgent`, `AgentStopService` and `ConcurrencyManager`, but every other agent in the tests is a double; `_checked_recall` recognises four shapes (no reply, the stop metadata, a failed reply, `[NO_RESPONSE]`), so a successful reply whose text is itself a refusal ("I can't say") reaches the judge as before, and its precision stays item bf-989 R2; the self-session and the handler's latency stay item bf-989 R3; a key with no live agent takes no cooldown, so a departed agent's triggers each log one INFO line (item bf-989 R5).
