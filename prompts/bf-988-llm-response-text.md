# BF-988 (#1523, item F-19): an LLM reply's text is read through one reader, so guided reminiscence never takes a response's repr as its text

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-20

**Amended by:** the orchestrator, 2026-11-20: first-hand verification of the premises and the corrections listed in section 16; and, after review round 1, Amendment A1 (section 17), whose corrections are also made in place in sections 2, 3, 5, 7.1, 7.4, 7.5, 8.2, 10, 14, 15 and 16. The Architect's text is otherwise unchanged.

**Status:** build-ready. Issue #1523; it stays open for its other items, and the PR says `Refs #1523`. One BF number. BF-988 appears only in REPLACE text, the new file's path and text, and tracker text, never in a SEARCH.

**Base:** `1c5a6ff9`, the head of PR #1837 (B5, BF-970). #1837's merge tree equals this tree. `git diff --stat 3137575a 1c5a6ff9 --` over the six files read here prints nothing. Build on `origin/main` after #1837 merges.

**Line endings:** the working copies are CRLF and the SEARCH blocks are LF. Match and write each file with its own line endings, and write the new file with LF.

**Milestones:**
- M1: the new test file first (red), then `types.py` and `guided_reminiscence.py` (green). Tier LOW.
- M2: the trackers and the generated ledger pair.

Each milestone is one Builder delegation and one local commit. After M2, run one broad gate: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf-988-1523 --receipt logs/gates/bf-988-1523.receipt.json`.

**Captain:** no condition is met.
- The reader is an additive internal helper, not a public API.
- No schema, security control, spend, OSS/commercial boundary or product objective changes.
- It turns on a measurement (the AD-566 D2 score), not a feature.

---

## 0. Premise: what is present on this tree

| Fact | Where |
|---|---|
| `LLMResponse` has `content` and no `text` | `src/probos/types.py:335-374` |
| The clients return it | `cognitive/llm_client.py:250` (abstract), `:1462`, `:2920` |
| The three reads | `cognitive/guided_reminiscence.py:241`, `:370`, `:413` |
| An error reply has `content=""` and `error` set | `llm_client.py:1537-1539`, `:2027-2028`, `:2045-2046`, `:2061-2062`, `:2097-2101` |
| The Counselor's session dies before any read | `guided_reminiscence.py:124` calls `recent_for_agent` without `await`; `:129` (a coroutine is truthy); `:133` `len(episodes)` raises `TypeError` outside the `try` at `:123-127`. `episodic.py:4132` and `episodic_mock.py:231` are `async def`. Caught at `counselor.py:2506-2510` |
| The production path that reaches `:241` | `qualification_tests.py:338-479`. It awaits `recent_for_agent` itself (`:412`), recalls through the agent (`_send_probe`, `:449`), then calls `engine.score_recall` (`:452`). Threshold `0.5` (`:348`). Registered at `runtime.py:3150`, driven by `DriftScheduler` (`runtime.py:3217-3233`), weekly by default (`config.py:3642`) |
| Drift statistics | `drift_detector.py:150` (filters `inconclusive`), `:176-203`; `config.py:3643-3646` (warning 2.0 sigma, critical 3.0 sigma, minimum 3 samples, window 20) |
| No billet requires the probe | `rg episodic_recall_probe` outside `tests/`: only `qualification_tests.py:345`, archived prompts and an era decisions file |
| A test may import doubles from another test module | `tests/test_ad1207_fault_visibility.py:587` (BF-987's precedent) |

## 1. Problem

Each of the three sites does `x = response.text.strip() if hasattr(response, 'text') else str(response).strip()`. A real `LLMResponse` has no `text`, so `x` is the dataclass repr, which includes AD-1327's `answered_model` provider text.

- **`score_recall` (`:241`).** A reply that is only a number scores 0.5: no token of the repr parses as a float ("unparseable", `:249`). A reply that holds a bare number inside a sentence scores that number by accident (orchestrator probe, section 16: "The score is 0.8 out of 1" scores 0.8).
- **`build_therapeutic_response` (`:370`).** The repr is non-empty, so it is returned as the message.
- **`run_session` (`:413`).** The repr becomes `recalled_text`.

`classify_recall` never reads the repr's words. With accuracy 0.5, it returns PARTIAL at `:271-272`, before the word analysis at `:277`.

**Reach in production:**
- **AD-566 D2 only.** Each `episodic_recall_probe` episode scores 0.5 for a reply that is only a number, so the probe nearly always passes at 0.5. The per-episode classification is `partial` at that score (1.0 and ACCURATE where the expected summary is empty).
- **No Counselor reach.** No reminiscence session has ever reached `:370` or `:413` in production (section 0, row 5). The item's repr DM was reproduced by calling `build_therapeutic_response` directly.
- **The persist anchor.** The item names `counselor.py:2439`; on this tree the persist is `:2531-2532`, which calls `_send_therapeutic_dm`, which calls `create_thread(body=message)` at `:2349-2356`.

The existing tests build `.text`-only `MagicMock` doubles (`tests/test_ad541d_guided_reminiscence.py:155-157`, `:166-168`, `:225-232`, `:259-270`), so they model the bug.

## 2. Solution overview

Add `llm_response_text(response: object) -> str` to `probos/types.py`, directly after `LLMResponse`. Replace the three reads with it. Nothing else in `src` changed in the first build; Amendment A1 (section 17) adds the judge-failure repair to `guided_reminiscence.py` and `qualification_tests.py`.

Rejected designs (one line each):
- A `text` alias property on `LLMResponse` switches on six features without review (O3).
- `repr=False` on `answered_tier`/`answered_model`: section 3 D2.
- Repairing all twelve sites now: O4, filed as the #1820 item.
- The selection `await`: O2, filed as its own issue.
- A private reader inside `guided_reminiscence.py`: the follow-up needs one shared reader, and `_safe_llm_response_text` is private and keeps the `str(response)` fallback that is this defect's shape.

## 3. Decisions

**D1 -- the reader's semantics.**
1. If `getattr(response, "error", None)` is a non-empty `str`, return `""`. An error reply is not an answer; the clients send `content=""` with `error` set.
2. Otherwise, if `getattr(response, "content", None)` is a `str`, return it stripped. This is a real `LLMResponse`; `content` wins over `text`.
3. Otherwise, if `getattr(response, "text", None)` is a `str`, return it stripped. This is a `.text`-only double; `MagicMock().content` is not a `str`.
4. Otherwise return `""`. Never `str(response)`.

What each caller does with `""`, confirmed by reading the code:
- `score_recall` splits no tokens and returns 0.5 (`:243-249`), as for an unparseable reply.
- `build_therapeutic_response` skips `if text:` (`:371`) and returns the template (`:376`).
- In `run_session`, `recalled_text` is `""`, and `score_recall("", expected)` still asks the LLM, because `llm_client` is set. The Jaccard path (`:255`) runs only without a client, where `jaccard_similarity` of an empty set applies. The item's "goes to the Jaccard path" is true only without a client.

**D2 -- `repr=False` on `answered_tier`/`answered_model`: out of scope.** After D1, nothing in `src` uses an `LLMResponse`'s repr as text:
- `rg 'str\((response|resp|result|llm_response|llm_resp)\)' src` hits the three sites (removed here).
- `qualification_tests.py:40` and `cognitive_agent.py:8968` are fallbacks after a `content` check, so an `LLMResponse` never reaches them.
- The other hits are not `LLMResponse`s (`productivity_agents.py:88`, `builder.py:950`, `checkpoint.py:217`, `counselor.py:2934`, `persistent_tasks.py:412`, `storage_gate.py:120`, `sub_task.py:477-488`).
- No test pins the repr (AV3).

Hiding the fields would cost diagnostic value in logs and assertion messages and protect no reader.

**D3 -- the doubles.** The four `.text`-only `MagicMock` tests in `test_ad541d_guided_reminiscence.py` stay unchanged as the compatibility cases; D1 step 3 keeps them green. The regression cases go in a new file and use a real `LLMResponse`. `test_ad566b_baseline_tests.py:100-110` sets both `content` and `text` as strings, so it is unaffected.

**D4 -- no census test in B6.** Seven defective readers remain until the #1820 item, so a census now would need an allowlist that pins seven defects as the contract. The census belongs to the follow-up and asserts zero there. Its known false negatives:
- a response passed through a helper;
- a response stored on `self` or returned before it is read;
- a `complete()` call wrapped in `asyncio.wait_for` (`builder.py:865`, `perception/consumer.py:1043,1122`, `decomposer.py:501`, `self_distillation/prober.py:149`; none reads `.text` today, AV2);
- a dynamic `getattr(x, name)`.

**D5 -- persisted history and the rollout (corrected in review round 1).** No Counselor profile or Ward Room DM was ever written by a reminiscence session (section 0, row 5), so none holds repr text or a session's 0.5. The only persisted 0.5s are `episodic_recall_probe` rows in the qualification store. They leave the 20-result drift window after up to 19 further runs; the auto-captured baseline row does not (below).

Effect, measured on the real store and detector (probe `probe_f1_f2.py`; `drift_detector.py:135-250`). The window is the newest 20 rows and includes the new row, so an agent whose last N rows (N at most 19) are exactly 0.5 gets z = +-sqrt(N) on its first measured score, whatever that score is (a constant history has no spread), and the 0.5 rows stay in the window. With N = 19 and a steady score the next runs give |z| = 3.00, 2.38, 2.00 and then 1.73: up to four consecutive runs signal per agent (critical, then critical or warning, then warning twice), and the cutoffs at exactly N = 4 and N = 9 depend on floating-point rounding (N = 4 with a new score of 0.7 gives no signal; N = 9 with 0.9 gives a warning, not a critical). A stored result that is not exactly 0.5 (a skipped 1.0 row, or an accidental parse of a reply) lowers z.

What reads the stored rows (enumerated over `src/probos`):
- the Counselor: a critical drift runs an assessment, and a DM follows only if it warrants one (`counselor.py:1475-1536`, `:2449-2459`); a warning only logs;
- the Tier-3 `scaffold_decomposition` of `__crew__`, which reads each crew member's latest stored Tier-1 score (`collective_tests.py:155-222`) and so moves and signals the same way (`drift_check_tiers` is [1, 2, 3], `config.py:3648`);
- the Vitals Monitor, which repeats a `medical_alert` on every 5 s heartbeat while any latest report is critical (`vitals_monitor.py:176-190`, `:345-356`), one Diagnostician LLM call each (measured: 3 alerts and 3 calls in 3 heartbeats; existing behaviour for any critical drift; edge-triggered by #1839, BF-990, which lands no later than this change);
- shell and compare displays (`commands_qualification.py`, `qualification.py:578-612`). No billet requires the probe, and the skill bridge maps three other tests.

The first automatic run is seven days after a boot (the loop sleeps one interval first, `drift_detector.py:303-314`); `qualification run` starts the same path on demand (`commands_qualification.py:129`), so the transient decays with the number of runs. The auto-captured baseline of 0.5 is not replaced (`run_test` takes one only when none exists, `qualification.py:443-447`; `run_baseline` and `set_baseline` have no caller in `src`), so `direction` stays measured from 0.5 (#1820, item bf-988 R6). No migration, and none in code: discounting the old rows is a new heuristic or a change of stored data on a live vessel, which is the Captain's. The operator's options: `qualification.drift_check_enabled`, `drift_warning_sigma`, `drift_critical_sigma`, `drift_check_tiers`, and a restart (the cached reports are in memory). The live count needs the store (#1193); no count is asked for.

**D6 -- who decides.** The Architect: none of the six conditions is met (header).

## 4. Milestones and focused gates

- **M1.** Write 7.1 first; record it red against the base (P2). Then 7.2 and 7.3. Focused gate: `pytest tests/test_bf988_llm_response_text.py tests/test_ad541d_guided_reminiscence.py tests/test_ad566b_baseline_tests.py -q -n 0`. Also run `tests/test_ad566d*.py` (it imports `_safe_llm_response_text`, which is unchanged: a smoke check).
- **M2.** 7.4, 7.5, 7.6. Then `pytest tests/test_ad1184_ad_ledger.py -q -n 0`.

## 5. Consumers of every value this changes

| Value | Consumers | Effect |
|---|---|---|
| `score_recall`'s return | `run_session` `:418` (dead in production); `EpisodicRecallProbe` `:452` -> `TestResult.score`/`passed`/`inconclusive` -> `QualificationStore` -> `DriftDetector._analyze_single` (`QUALIFICATION_DRIFT_DETECTED` -> `counselor.py:1089`; the scheduler's `latest_reports` -> `VitalsMonitorAgent` -> a `medical_alert` per heartbeat -> `DiagnosticianAgent`), `ScaffoldDecompositionProbe` (`collective_tests.py:155-222`: `get_latest` of each crew member's Tier-1 score -> `__crew__` `scaffold_decomposition` -> the same detector), `commands_qualification.py:168-178` | Real scores; D5 (corrected in review round 1) |
| `build_therapeutic_response`'s return | `run_session` `:446` -> `counselor.py:2531-2532` | None in production (dead path) |
| `recalled_text` | `RecallResult.recalled_text`, `classify_recall` | None in production |
| `probos.types` namespace | Additive name; `llm_client.py:23` imports only `LLMRequest, LLMResponse, Priority` | None |

## 6. Tests (new file `tests/test_bf988_llm_response_text.py`)

| Test | What it asserts | Red on base? |
|---|---|---|
| T1 | `llm_response_text` over twelve shapes (D1); the result is always a `str` | yes (import error) |
| T2 | `score_recall` over a real reply: `"0.9"` -> 0.9, `"0.1"` -> 0.1, `"Score: 0.75."` -> 0.75; an error reply -> 0.5 | first three yes |
| T3 | The therapeutic message equals the reply's stripped content; an empty reply, an error reply or a non-response falls to the template, and the output never starts with `LLMResponse(` or holds `provider-echo` | yes |
| T4 | `run_session`'s recalled texts, accuracies and message are the replies' content | yes |
| T5 | A `.text`-only double still scores (compatibility) | no |
| T6 | An empty recall reply gives `""`, never the repr | yes |
| T7 | End to end through the real `_send_therapeutic_dm`: the stored `create_thread` body equals the reply content | yes |
| T8 | `EpisodicRecallProbe` with a real reply: `"0.9"` -> 0.9 and passed; `"0.2"` -> 0.2 and not passed | yes |

## 7. The contract

### 7.1 New file: `tests/test_bf988_llm_response_text.py` (M1)

```python
"""BF-988 (#1523 F-19): an LLM reply's text is read through ``probos.types.llm_response_text``.

``LLMResponse`` carries its text in ``content`` and has no ``text`` attribute, so the three
``response.text ... if hasattr(response, 'text') else str(response)`` reads in
``guided_reminiscence.py`` took the dataclass repr: ``score_recall`` returned 0.5 for a reply that is
only a number (the repr wraps it in ``content='...'``, which the parse skips; a number inside a
sentence was parsed out of the repr by accident), ``build_therapeutic_response`` returned the repr,
and ``run_session`` recalled it. Every
regression case here answers with a real ``LLMResponse``; the ``.text``-only doubles are the
compatibility cases (the four in ``test_ad541d_guided_reminiscence.py`` stay as they are).
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.guided_reminiscence import (
    GuidedReminiscenceEngine,
    RecallClassification,
    RecallResult,
)
from probos.cognitive.qualification_tests import EpisodicRecallProbe
from probos.types import LLMResponse, llm_response_text
from tests.test_ad541d_guided_reminiscence import _make_counselor, _make_episode
from tests.test_ad566b_baseline_tests import (
    MockAgent,
    MockEpisode,
    MockEpisodicMemory,
    MockRegistry,
)

_SCORE = "0.8"
_RECALL = "the ship status was checked and it was nominal"
_MESSAGE = "Good session. Your recall matched the records."


class _Client:
    """Answers like ``BaseLLMClient.complete``: with a real ``LLMResponse``, by prompt."""

    def __init__(
        self,
        *,
        score: str = _SCORE,
        recall: str = _RECALL,
        message: str = _MESSAGE,
        error: str | None = None,
    ) -> None:
        self._score = score
        self._recall = recall
        self._message = message
        self._error = error

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        prompt = request.prompt
        if prompt.startswith("Score the factual accuracy"):
            content = self._score
        elif prompt.startswith("You are a Ship's Counselor"):
            content = self._message
        else:
            content = self._recall
        return LLMResponse(
            content=content,
            model="m",
            tier="fast",
            error=self._error,
            answered_tier="fast",
            answered_model="provider-echo",
        )


class _ObjectClient:
    """A client whose reply is neither an ``LLMResponse`` nor a ``.text`` double."""

    async def complete(self, request: Any, **_kwargs: Any) -> object:
        return object()


def _engine(client: Any, episodes: list | None = None) -> GuidedReminiscenceEngine:
    memory = MagicMock()
    # Synchronous on purpose: select_episodes_for_session calls recent_for_agent without await
    # (filed with BF-988), so only a synchronous double reaches run_session's reads.
    memory.recent_for_agent = MagicMock(return_value=list(episodes or []))
    return GuidedReminiscenceEngine(
        episodic_memory=memory, llm_client=client, max_episodes_per_session=3,
    )


def _episodes() -> list:
    return [
        _make_episode(ep_id=f"ep-{i}", timestamp=time.time() - (i + 1) * 1000, agent_ids=["a1"])
        for i in range(4)
    ]


def _results() -> list[RecallResult]:
    return [RecallResult(classification=RecallClassification.PARTIAL, accuracy=0.5) for _ in range(3)]


def _mock_with_text(text: str) -> MagicMock:
    double = MagicMock()
    double.text = text
    return double


# -- T1: the reader -------------------------------------------------------------


@pytest.mark.parametrize(
    ("make", "expected"),
    [
        pytest.param(lambda: LLMResponse(content="  0.9 \n"), "0.9", id="content-stripped"),
        pytest.param(lambda: LLMResponse(content=""), "", id="empty-content"),
        pytest.param(lambda: LLMResponse(content="0.9", error="tier unavailable"), "", id="error-with-content"),
        pytest.param(lambda: LLMResponse(content="", error="All LLM tiers unavailable (x)"), "", id="error-empty"),
        pytest.param(lambda: LLMResponse(content="ok", error=""), "ok", id="empty-error-is-no-error"),
        pytest.param(lambda: SimpleNamespace(text=" 0.7 "), "0.7", id="text-only"),
        pytest.param(lambda: _mock_with_text("0.9"), "0.9", id="mock-with-text"),
        pytest.param(lambda: MagicMock(), "", id="bare-mock"),
        pytest.param(lambda: SimpleNamespace(content="a", text="b"), "a", id="content-wins"),
        pytest.param(lambda: SimpleNamespace(content=None, text="x"), "x", id="content-not-a-str"),
        pytest.param(lambda: object(), "", id="neither"),
        pytest.param(lambda: None, "", id="none"),
    ],
)
def test_the_reader_returns_the_reply_text_and_never_a_repr(make: Any, expected: str) -> None:
    result = llm_response_text(make())
    assert isinstance(result, str)
    assert result == expected


# -- T2: score_recall -----------------------------------------------------------


@pytest.mark.parametrize(("reply", "expected"), [("0.9", 0.9), ("0.1", 0.1), ("Score: 0.75.", 0.75)])
async def test_score_recall_parses_a_real_llm_response(reply: str, expected: float) -> None:
    assert await _engine(_Client(score=reply)).score_recall("recall", "expected") == pytest.approx(expected)


async def test_score_recall_treats_an_error_reply_as_unparseable() -> None:
    engine = _engine(_Client(score="0.9", error="tier unavailable"))
    assert await engine.score_recall("recall", "expected") == 0.5


# -- T3: build_therapeutic_response ----------------------------------------------


async def test_the_therapeutic_message_is_the_reply_content() -> None:
    engine = _engine(_Client(message="  Well done, Lieutenant.  \n"))
    assert await engine.build_therapeutic_response("a1", _results()) == "Well done, Lieutenant."


@pytest.mark.parametrize(
    "make",
    [
        pytest.param(lambda: _Client(message=""), id="empty-reply"),
        pytest.param(lambda: _Client(message="ignored", error="tier unavailable"), id="error-reply"),
        pytest.param(lambda: _ObjectClient(), id="not-a-response"),
    ],
)
async def test_a_reply_without_text_falls_to_the_template(make: Any) -> None:
    template = await _engine(None).build_therapeutic_response("a1", _results())
    message = await _engine(make()).build_therapeutic_response("a1", _results())
    assert message == template
    assert not message.startswith("LLMResponse(")
    assert "provider-echo" not in message


# -- T4, T6: run_session ---------------------------------------------------------


async def test_run_session_reads_each_reply_content() -> None:
    result = await _engine(_Client(), _episodes()).run_session("a1")
    assert result.episodes_tested == 3
    assert [r.recalled_text for r in result.recall_results] == [_RECALL] * 3
    assert all(r.accuracy == pytest.approx(0.8) for r in result.recall_results)
    assert result.therapeutic_message == _MESSAGE


async def test_run_session_never_recalls_a_repr() -> None:
    result = await _engine(_Client(recall=""), _episodes()).run_session("a1")
    assert [r.recalled_text for r in result.recall_results] == ["", "", ""]


# -- T5: the .text compatibility case ---------------------------------------------


async def test_a_text_only_double_still_scores() -> None:
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=_mock_with_text("0.7"))
    assert await _engine(llm).score_recall("recall", "expected") == pytest.approx(0.7)


# -- T7: end to end through the Counselor's DM ------------------------------------


async def test_the_counselor_dm_body_is_the_reply_content() -> None:
    ward_room = SimpleNamespace(
        get_or_create_dm_channel=AsyncMock(return_value=SimpleNamespace(id="dm-1")),
        create_thread=AsyncMock(),
    )
    counselor = _make_counselor(
        _reminiscence_engine=_engine(_Client(), _episodes()),
        _ward_room=ward_room,
        callsign="Counselor",
        _record_intervention=MagicMock(),
    )
    await counselor._initiate_reminiscence_session("a1", trigger="bf988")
    ward_room.create_thread.assert_awaited_once()
    body = ward_room.create_thread.await_args.kwargs["body"]
    assert body == _MESSAGE
    assert not body.startswith("LLMResponse(")


# -- T8: the production path (AD-566 D2) ------------------------------------------


@pytest.mark.parametrize(("reply", "score", "passed"), [("0.9", 0.9, True), ("0.2", 0.2, False)])
async def test_the_episodic_recall_probe_scores_a_real_reply(reply: str, score: float, passed: bool) -> None:
    episodes = [MockEpisode(id=f"ep-{i}", user_input=f"Task {i}", timestamp=float(i)) for i in range(3)]
    runtime = MagicMock()
    runtime.registry = MockRegistry(MockAgent(response="I analyzed trust patterns and the task was successful."))
    runtime.llm_client = _Client(score=reply)
    runtime.episodic_memory = MockEpisodicMemory(episodes, 3)
    result = await EpisodicRecallProbe().run("agent-1", runtime)
    assert result.error is None
    assert result.score == pytest.approx(score)
    assert result.passed is passed
```

### 7.2 `src/probos/types.py` (M1)

SEARCH:
```python
    # client, test doubles, errors). The single-call fallback's BF-204 grounds on it.
    applied_system_suffix: str = ""


class EscalationTier(Enum):
```
REPLACE:
```python
    # client, test doubles, errors). The single-call fallback's BF-204 grounds on it.
    applied_system_suffix: str = ""


def llm_response_text(response: object) -> str:
    """BF-988 (#1523 F-19): the text of an LLM client's reply, stripped; "" when it holds none.

    ``LLMResponse`` carries its text in ``content`` and has no ``text`` attribute. A reply whose
    ``error`` is a non-empty ``str`` is not an answer and reads "" (the clients answer a refused or
    failed call with ``content=""`` and ``error`` set). Otherwise a ``str`` ``content`` is the text;
    an object whose ``content`` is not a ``str`` (a test double) is read by its ``str`` ``text``.
    Anything else reads "": never ``str(response)``, whose dataclass repr is not an answer and
    carries the provider's ``answered_model`` text (AD-1327).
    """
    error = getattr(response, "error", None)
    if isinstance(error, str) and error:
        return ""
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content.strip()
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text.strip()
    return ""


class EscalationTier(Enum):
```

### 7.3 `src/probos/cognitive/guided_reminiscence.py` (M1, four pairs in file order)

SEARCH:
```python
from typing import Any

from probos.cognitive.similarity import jaccard_similarity, text_to_words
```
REPLACE:
```python
from typing import Any

from probos.cognitive.similarity import jaccard_similarity, text_to_words
from probos.types import llm_response_text
```

SEARCH:
```python
                response = await self._llm_client.complete(LLMRequest(
                    prompt=prompt,
                    tier="fast",
                    max_tokens=10,
                ))
                score_text = response.text.strip() if hasattr(response, 'text') else str(response).strip()
```
REPLACE:
```python
                response = await self._llm_client.complete(LLMRequest(
                    prompt=prompt,
                    tier="fast",
                    max_tokens=10,
                ))
                score_text = llm_response_text(response)  # BF-988 (#1523 F-19): never the response's repr
```

SEARCH:
```python
                response = await self._llm_client.complete(LLMRequest(
                    prompt=prompt,
                    tier="fast",
                    max_tokens=150,
                ))
                text = response.text.strip() if hasattr(response, 'text') else str(response).strip()
                if text:
                    return text
```
REPLACE:
```python
                response = await self._llm_client.complete(LLMRequest(
                    prompt=prompt,
                    tier="fast",
                    max_tokens=150,
                ))
                text = llm_response_text(response)  # BF-988 (#1523 F-19): "" falls to the template
                if text:
                    return text
```

SEARCH:
```python
                    response = await self._llm_client.complete(LLMRequest(
                        prompt=recall_prompt,
                        tier="fast",
                        max_tokens=200,
                    ))
                    recalled_text = response.text.strip() if hasattr(response, 'text') else str(response).strip()
```
REPLACE:
```python
                    response = await self._llm_client.complete(LLMRequest(
                        prompt=recall_prompt,
                        tier="fast",
                        max_tokens=200,
                    ))
                    recalled_text = llm_response_text(response)  # BF-988 (#1523 F-19)
```

### 7.4 `PROGRESS.md` (M2)

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-988 (2026-11-20), #1523 F-19 -- an LLM reply's text is read through one reader, so guided reminiscence never takes a response's repr as its text.** `LLMResponse` has `content` and no `text`, so the three `response.text ... if hasattr(response, 'text') else str(response)` reads in `cognitive/guided_reminiscence.py` (`score_recall`, `build_therapeutic_response`, `run_session`) took the dataclass repr: a reply that is only a number scored 0.5 (a number inside a sentence was parsed out of the repr by accident), and the therapeutic message and recalled text were the repr. New `probos.types.llm_response_text` (an `error` reply reads ""; a `str` `content`; else a `str` `text`; else "", never the repr) replaces the three reads. In production only the AD-566 D2 `episodic_recall_probe` reached the defect, and it is now measured: an agent whose stored history is all 0.5 can signal drift on up to four consecutive runs (the first one or two critical), the Tier-3 `scaffold_decomposition` of `__crew__` moves with it, and a critical report makes the Vitals Monitor repeat its alert on every heartbeat until the next run (#1839, BF-990, edge-triggers that and lands no later than this change); DECISIONS has the figures. The probe now reports a judge that failed or answered no number as inconclusive (`GuidedReminiscenceEngine.score_recall_outcome`, the BF-711 rule), so an outage is neither a drift sample nor a baseline. The Counselor's sessions never reached the reads: `select_episodes_for_session` calls the async `recent_for_agent` without `await` and raises at `len()`, caught by the Counselor. That defect, and that both AD-541c practice and AD-541d sessions take their "recall" from a memoryless fast-tier call, are filed as #1838 (BF-989), since repairing the `await` alone would turn on confabulation diagnoses built on that call. Seven other `.text` readers of a reply are filed on #1820. New `tests/test_bf988_llm_response_text.py`. Contract `prompts/bf-988-llm-response-text.md`.
```

### 7.5 `DECISIONS.md` (M2)

SEARCH:
```markdown
### BF-970 -- Every Ship's Records reader reads a frontmatter block one way: one nesting check at 64, and no reader reads the base's cut (2026-11-20, #1801)
```
REPLACE:
```markdown
### BF-988 -- #1523 F-19: an LLM reply's text is read through one reader; guided reminiscence never takes a response's repr as its text (2026-11-20, #1523)

- *Mechanism.* `LLMResponse` (`types.py`) has `content` and no `text`. The three reads in `guided_reminiscence.py` fell back to `str(response)`, the dataclass repr, which also carries AD-1327's `answered_model` provider text.
- *Repair.* `probos.types.llm_response_text(response) -> str`, beside `LLMResponse`: a non-empty `str` `error` reads ""; then a `str` `content`, stripped; then a `str` `text`, stripped (test doubles); else "". The three sites call it. An "" reply scores 0.5 (unparseable), falls to the template, or recalls "".
- *Reach.* Production reached only `score_recall` through `EpisodicRecallProbe` (AD-566 D2): 0.5 for a reply that is only a number, which passed its 0.5 threshold, now measured. The Counselor's session raises `TypeError` at `select_episodes_for_session` (`recent_for_agent` is async and is called without `await`) before any read; the item's repr DM was reproduced by calling `build_therapeutic_response` directly. No profile or DM holds a session's output.
- *Effect, recorded (review round 1 corrected it).* The detector reads the newest 20 stored rows, with the new row in the window, so an agent whose last N rows (N at most 19) are exactly 0.5 gets z = +-sqrt(N) on its first measured score, whatever that score is (a constant history has no spread), and the 0.5 rows stay in the window. With N = 19 and a steady score the next runs give 3.00, 2.38, 2.00 and then 1.73 (a probe on the real store and detector): up to four consecutive runs signal per agent, critical, then critical or warning, then warning twice, and the cutoffs at exactly N = 4 and N = 9 depend on floating-point rounding (N = 4 with a new score of 0.7 gives no signal; N = 9 with 0.9 gives a warning, not a critical). Each signal emits `QUALIFICATION_DRIFT_DETECTED`: the Counselor runs an assessment on a critical one and sends a DM only when it warrants one; the Tier-3 `scaffold_decomposition` of `__crew__` reads each crew member's latest stored score, so it moves and signals the same way; and while any latest report is critical the Vitals Monitor repeats its `medical_alert` on every 5 s heartbeat until the next run replaces the report, one Diagnostician LLM call each (measured on the real classes; existing behaviour for any critical drift; edge-triggered by #1839, BF-990, which lands no later than this change).
- *Rollout.* The first automatic run is seven days after a boot (the loop sleeps one interval first); `qualification run` starts the same path on demand, so the transient decays with the number of runs, not with weeks. The auto-captured baseline of 0.5 is not replaced (`run_test` takes one only when none exists; `run_baseline` and `set_baseline` have no caller in `src`), so `direction` stays measured from 0.5 (#1820, item bf-988 R6). No migration, and none in code: discounting the old rows is a new heuristic or a change of stored data on a live vessel, which is the Captain's. The operator's options are `qualification.drift_check_enabled`, `drift_warning_sigma`, `drift_critical_sigma` and `drift_check_tiers`, and a restart (the cached reports are in memory). The live count needs the data store (#1193) and is not taken.
- *Judge failure (review round 1, F2).* On the base a judge that failed or answered no number was stored as `score=0.5, passed=True, inconclusive=False`, a measurement; against a history of measured scores it reads as a decline (z -4.36 after 19 results of 0.9). `GuidedReminiscenceEngine.score_recall_outcome` returns `RecallScore(score, inconclusive)` and `score_recall` keeps its float contract and delegates: a failed call or a reply with no number is inconclusive, decided by branch and not by value (a judge that says 0.5 is a measurement; no client, the Jaccard path, is a measurement). `EpisodicRecallProbe` then returns `inconclusive=True`, `passed=False` and an `error` (`k/n episodes: reason`; the `error` is also what keeps `run_test` from taking the run as a baseline), the BF-711 pattern of `communication_benchmarks.py`.
- *Decided by the Architect.* None of the six conditions is met: an additive internal helper, no schema, control, spend or boundary; a measurement is turned on, not a feature. Review round 1 (consult `2a7391b7`): the corrected effect is inside the envelope; the Vitals repetition was measured first, as the consult required, and is #1839 (BF-990); the judge-failure repair belongs to this change.
- *Rejected.* A `text` property on `LLMResponse` (switches on six features at once; two names for one field); `repr=False` on the AD-1327 fields (no reader uses the repr as text after this; diagnostics lose it); the selection `await` (it would turn on Counselor diagnoses built on a memoryless fast-tier recall); repairing the other readers now (each changes a feature's behaviour); an in-code discount of the stored 0.5 rows (a new heuristic, or a change of stored data on a live vessel).
- *Filed.* The selection `await` and the AD-541c/d recall design (#1838, BF-989); seven other `.text` readers, adoption of this reader by the three existing ones, and a census asserting zero (#1820); the Vitals Monitor's alert on every heartbeat (#1839, BF-990); the permanent 0.5 baseline (#1820, item bf-988 R6).
- *Reversal.* Revert the commits.

### BF-970 -- Every Ship's Records reader reads a frontmatter block one way: one nesting check at 64, and no reader reads the base's cut (2026-11-20, #1801)
```

### 7.6 Generated: the ledger pair (M2)

After 7.4 and 7.5, run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`. It regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`, which go in M2's commit; do not paste them. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`.

**`roadmap.md`:** no row, because the Bug Tracker lists only bugs deliberately not fixed.

## 8. Issue closure (the orchestrator posts these; nothing here edits GitHub)

### 8.1 Tick on #1523: F-19

Change `- [ ] **F-19 (Medium, pre-existing)` to `- [x] **F-19 (Medium, pre-existing)` and append to the end of the item:

` **Fixed (BF-988, PR #...):** the three reads use the new \`probos.types.llm_response_text\` (error reply -> ""; \`str\` \`content\`; else \`str\` \`text\`; else "", never the repr). Production reached only the AD-566 \`episodic_recall_probe\` score (0.5 for a reply that is only a number, which nearly always passed), now measured. The Counselor's sessions never reached the reads: \`select_episodes_for_session\` calls the async \`recent_for_agent\` without \`await\` (filed as #1838, BF-989, with the memoryless recall it would switch on). Anchor correction: the DM is persisted at \`counselor.py:2531-2532\` -> \`_send_therapeutic_dm\` -> \`create_thread\`, not \`:2439\`. \`repr=False\` was not adopted: no reader uses the repr as text after this.`

### 8.2 Comment on #1523 (at merge)

> F-19 fixed by BF-988 (PR #...). An `LLMResponse` has `content`, not `text`, so guided reminiscence read the dataclass repr. One reader, `probos.types.llm_response_text`, now serves all three sites, and it never returns a repr.
>
> In production only the AD-566 episodic recall probe reached the defect: its score was 0.5 for a reply that is only a number, which nearly always passed. It is now measured, so **expect drift signals, and more than the one I first wrote (04:58Z)**. Each agent whose stored results are all 0.5 gets a critical signal on its first measured run and up to three more on the following runs (|z| 4.36, 3.00, 2.38, 2.00 for 19 stored results of 0.5 and a steady score; the cutoffs at exactly N = 4 and N = 9 depend on floating-point rounding), and the Tier-3 `scaffold_decomposition` of `__crew__` moves with it. A critical report makes the Counselor run an assessment (a DM only when it warrants one) and, until the next run, made the Vitals Monitor broadcast its alert on every heartbeat for one Diagnostician LLM call each; BF-990 (#1839, in the same pull request) now sends it once per report. The first measured run is at the earliest seven days after a boot, or when `qualification run` is used. It comes from the change of measurement, not from the agents. Before that run you can change `qualification.drift_check_enabled`, `drift_warning_sigma`, `drift_critical_sigma` or `drift_check_tiers`, or restart (the cached reports are in memory). The auto-captured baseline of 0.5 stays, so `direction` is measured from 0.5 (#1820, item bf-988 R6). A judge that failed or answered no number is now inconclusive, not a measured 0.5. Reminiscence sessions never reached the defect, because they fail earlier at episode selection (a missing `await`). That defect is filed as #1838 (BF-989), together with the finding that the session's "recall" is a memoryless fast-tier call. Seven other readers of the same shape are filed on #1820.

## 9. What this does NOT change

- `LLMResponse`'s fields, defaults and repr.
- `select_episodes_for_session` and its missing `await`.
- `run_session`'s recall source.
- `classify_recall`, the Counselor and `finalize.py`'s wiring.
- The nine other readers: `counselor.py:913`, `actions.py:1299`, `compute_use.py:213`, `llm_classifier.py:154`, `render_verification.py:294`, `vision_intent_divergence.py:209`, `self_render_verify.py:141`, `insights.py:315-318`, `schedule_parser.py:174`, plus `qualification_tests._safe_llm_response_text`.
- `tests/test_ad541d_guided_reminiscence.py` and `tests/test_ad566b_baseline_tests.py` (not edited).
- No config, `EventType`, route, table or flag. No stored data.

## 10. Mutation rows (one campaign; restore between rows; run only the listed killers)

Record the base tree and the sha256 of `types.py` and `guided_reminiscence.py`. That is the campaign of record; rerun a row only if its file differs.

| # | Site | Mutate to | Killed by |
|---|---|---|---|
| R-1 | `:241` | the original read | T2 (the three parse cases), T4, T8 |
| R-2 | `:370` | the original read | T3 (all four), T7 |
| R-3 | `:413` | the original read | T4, T6 |
| R-4 | reader: `return ""` (last line) | `return str(response).strip()` | T1[bare-mock], T1[neither], T1[none], T3[not-a-response] |
| R-5 | reader: `if isinstance(content, str):` | `if content is not None:` | T1[mock-with-text], T1[bare-mock], T5 |
| R-6 | reader: `if isinstance(error, str) and error:` | `if False:` | T1[error-with-content], T2[error], T3[error-reply] |
| R-7 | reader: same line | `if error is not None:` | T1[empty-error-is-no-error], T1[mock-with-text], T5 |
| R-8 | reader: the `text` branch | removed | T1[text-only], T1[mock-with-text], T5 |
| R-9 | reader: `return content.strip()` | `return content` | T1[content-stripped], T3[reply content] |
| R-10 | reader: `content` and `text` blocks | swapped in order | T1[content-wins] |
| R-11 | reader: `return text.strip()` | `return text` | T1[text-only] |

## 11. Verified Against Codebase (2026-11-20, `1c5a6ff9`; #1837's merge tree equals this tree)

```
src/probos/types.py:334-338 @dataclass / class LLMResponse / content: str ; :345 error ; :360-361 answered_tier/answered_model ; :373-374 the SEARCH lines ; :377 class EscalationTier(Enum):
src/probos/types.py:6-10 imports (no new import needed) ; module-level functions at :583, :755, :773, :786, :807
src/probos/cognitive/llm_client.py:23 from probos.types import LLMRequest, LLMResponse, Priority ; :250, :1462, :2920 async def complete(...) -> LLMResponse
src/probos/cognitive/guided_reminiscence.py:16 from typing import Any ; :18 similarity import ; :124 recent_for_agent(agent_id, k=k * 2) (no await) ; :129 ; :133 len(episodes)
  :236-241 ; :249 return 0.5 ; :255 jaccard ; :271-272 PARTIAL ; :365-372 ; :376 return template ; :404-413 ; :418-419 ; :446
src/probos/cognitive/episodic.py:4132 async def recent_for_agent( ; episodic_mock.py:231 async def recent_for_agent
src/probos/cognitive/counselor.py:2492-2559 _initiate_reminiscence_session (2506-2510 catch; 2512 episodes_tested == 0; 2519-2520; 2531-2532; 2548-2549 amber)
src/probos/cognitive/counselor.py:2312-2368 _send_therapeutic_dm (2328 ward_room; 2334 DM_COOLDOWN_SECONDS; 2341 get_or_create_dm_channel; 2349-2356 create_thread(body=message); 2360 _record_intervention)
src/probos/substrate/agent.py:39 callsign: str = ""  (plain attribute; settable on the instance)
src/probos/cognitive/qualification_tests.py:34-40 _safe_llm_response_text ; :43-70 _send_probe ; :338-479 EpisodicRecallProbe (:348 threshold = 0.5; :412 await recent_for_agent; :428-452)
src/probos/cognitive/qualification.py:71 class TestResult ; :83 error: str | None = None
src/probos/runtime.py:3150 registers EpisodicRecallProbe ; :3217-3233 DriftScheduler
src/probos/cognitive/drift_detector.py:150, :176-203 ; src/probos/config.py:3642-3646
src/probos/startup/finalize.py:6276-6295 engine wiring (no recall source) ; config/system.yaml:245 reminiscence_enabled: true
tests/test_ad541d_guided_reminiscence.py:37 _make_episode ; :61 _make_engine ; :79-102 _make_counselor (sets _dm_cooldowns, _ward_room=None, _emit_event_fn=None, _confabulation_alert_threshold)
tests/test_ad566b_baseline_tests.py:40 MockAgent ; :61 MockRegistry ; :74 MockEpisode ; :86 MockEpisodicMemory (async recent_for_agent/count_for_agent) ; :100-110 MockLLMClient sets content and text
PROGRESS.md:1 # ProbOS Progress (once) ; DECISIONS.md:1661 ### BF-970 -- ... (once)
git diff --stat 3137575a 1c5a6ff9 -- types.py guided_reminiscence.py counselor.py qualification_tests.py test_ad541d test_ad566b : empty
scripts/gen_ad_ledger.py, tests/test_ad1184_ad_ledger.py exist
```

## Absence Verified (2026-11-20)

| | CLAIM | RUN | FOUND | HOLDS |
|---|---|---|---|---|
| AV1 | No client defines `complete_sync` | `rg complete_sync src` | only `llm_classifier.py:97,132,133,145` | yes |
| AV2 | No LLM-reply `.text` reader beyond the census's twelve | `rg '(hasattr\|getattr)\(\s*\w[\w.]*\s*,\s*["']text["']' src`; `rg '\b(resp\|response\|result\|reply\|...)\.text\b' src`; `rg '\b\w+\.text\b'` over the cognitive and agent modules | the twelve, plus `diagnostic_context.py:442` (episode), `template_registry.py:139` (pptx shape), `tier_policy.py:104,118` (blocks), `qualification_tests.py:38` (content first), HTTP `r.text` in channels and pickers, `routers/chat.py:426,439` (`PerAgentReply`), TextBlocks. The five `wait_for(...complete(...))` sites read no `.text` | yes, within D4's false negatives |
| AV3 | No test pins an `LLMResponse` repr | `rg '"LLMResponse\(\|'"'"'LLMResponse\(' tests` | none | yes |
| AV4 | No source-scan test reads the edited lines | `rg 'response\.text\.strip\|guided_reminiscence\.py\|getsource\(.*guided' tests` | only `tests/fixtures/file_durations.json:388` | yes |
| AV5 | BF-988 is free | `git log --all -E -i --grep=BF-98[89]`; Glob `prompts/bf-98*.md` (highest `bf-987`); `gh search issues BF-988` (hits only on tokens; #1523, #1324 and #1604 bodies contain no `BF-988`); `rg BF-98[89]` | only `open-ads-report.md:32` "next free BF-988" | yes (issue comments not searched) |
| AV6 | `llm_response_text` is a free name | `rg llm_response_text src` | none (only `_safe_llm_response_text`) | yes |
| AV7 | No billet requires `episodic_recall_probe` | `rg episodic_recall_probe` outside `tests/` | `qualification_tests.py:345`, archived prompts, an era decisions file | yes |

## 12. Deterministic checks, resolved up front

- `getattr(None, "error", None)` is `None`.
- A `MagicMock`'s `error`, `content` and `text` are `MagicMock`s, not `str`.
- A property-free dataclass is unaffected, because `LLMResponse` does not change.
- The `_Client` prompt prefixes match the engine's prompts: `:230` "Score the factual accuracy", `:357` "You are a Ship's Counselor", `:167` "I'd like to review".
- With four episodes and k=3, selection drops the newest and keeps three (`:133-147`).
- Accuracy 0.8 is ACCURATE, so T4's message is the LLM reply.
- Every T7 dependency is set by `_make_counselor` or by the test's overrides.

## 13. Prior art and blind spots

- **Internal:** three readers already exist (`insights.py:315-318`, `schedule_parser.py:174`, `qualification_tests.py:34-40`). The first two are adapted (content first, `.text` for doubles); the third's `str(response)` fallback is rejected, because it is this defect's shape. The `inconclusive` mechanism (BF-711, `drift_detector.py:150`) was considered for D5 and not used: the old rows are not flagged and flagging them needs the store.
- **External:** this is ProbOS-specific plumbing with no outside analogue, so no web search was made.
- **Blind spots, recorded:**
  - The Counselor path is dead at selection (filed).
  - AD-541c (`dreaming.py:2783-2789`, prompt built at `retrieval_practice.py:248-269`) and AD-541d recall from a memoryless fast-tier call, so they measure the model, not the agent (filed).
  - `"amber"` (`counselor.py:2549`) is unknown to `agents_at_alert`'s levels (`:771`) and to the router's counts (`routers/counselor.py:101-103`) (noted in the filed issue).
  - Today a completed session would overwrite the AD-568d/e confabulation EMA (`counselor.py:2165`, `:2199`) with the session's rate (`:2520`) (noted in the filed issue).
  - The drift signal (D5).

## 14. Diff Reviewer: properties to verify

1. `llm_response_text` returns a `str` for every input, in the order error -> `str` `content` -> `str` `text` -> `""`, and never calls `str()` or `repr()` on the response.
2. In `guided_reminiscence.py`, exactly the import and the three reads change. The `try`/`except`, the prompts and `max_tokens` are byte-identical. (Amendment A1, section 17, then adds `RecallScore` and `score_recall_outcome` there: property 1 of section 17.7.)
3. `LLMResponse`'s fields, defaults and repr are unchanged. No other `src` file changes in the first build (A1 changes the probe in `qualification_tests.py`). `tests/test_ad541d_*` and `tests/test_ad566b_*` are unedited.
4. Each regression test answers with a real `LLMResponse`. The `.text`-only cases are labelled as compatibility.
5. T7 exercises the real `_send_therapeutic_dm` (it is not monkeypatched), and T8 the real `EpisodicRecallProbe`.
6. One PROGRESS entry and one DECISIONS entry are added, and the ledger pair is generated.

## 15. Acceptance criteria

1. A real `LLMResponse` reply of "0.9" scores 0.9 through `score_recall` and through `EpisodicRecallProbe` (T2, T8).
2. The therapeutic message and the stored DM body equal the reply's stripped content (T3, T7).
3. No output is ever a repr (T1, T3, T6).
4. The `.text`-only doubles still pass (T5 and the four existing tests).
5. Every section 10 row is killed by its named tests, and T1 to T4, T6, T7 and T8 were recorded red first (P2).
6. One broad gate and one PR (`Refs #1523`); the section 8 texts are posted after the merge.
7. A judge that failed or answered no number makes the probe's result inconclusive, not passed and not a baseline; a judge that says 0.5 is a measurement (T9 to T12, section 17).
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Orchestrator verification (2026-11-20)

Each premise below was run first-hand on `cc601a72` (the merge of #1837; its tree equals the Architect's tree `1c5a6ff9`), with a probe that asserts its own premise before it reports. All agree with the Architect's text except where an amendment is named.

| Premise | Result |
|---|---|
| P1: BF-988 and BF-989 are free | `git log --all` subjects and bodies (highest BF-986), `prompts/bf-*.md` (highest BF-987), GitHub issue titles in all states (highest BF-984), a GitHub search of title, body and comments for `"BF-988"` and `"BF-989"`, and a local full-text search of all 1,541 issues: no hit. The only tracked mention is `docs/development/open-ads-report.md:32` (next free BF-988). BF-989 is issue #1838. |
| P3: the Counselor path is dead in production | A probe over `probos.cognitive.episodic_mock.MockEpisodicMemory` holding one episode: `run_session("a1")` raises `TypeError: object of type 'coroutine' has no len()` and the client is called 0 times; the control (a synchronous double returning the same episode) tests one episode with 3 client calls. Through the Counselor (`_initiate_reminiscence_session`, four episodes): over the real memory no DM, event, profile, cooldown or LLM call; over the control one DM, one event, one profile, one cooldown and 7 calls. History: the await-less line is in the engine's creating commit `92b99a47` (2026-04-04), and `async def recent_for_agent` is in `d52a333a` (2026-03-25). |
| P4: the measured effect on the base | `score_recall` over `LLMResponse(content="0.9")` returns 0.5; the therapeutic message is the 325-character repr. **Amendment:** a reply with a bare number inside a sentence is parsed out of the repr by accident: "The score is 0.8 out of 1" scores 0.8 and "I would say 0.6 maybe" scores 0.6, while "0.8" and "Score: 0.75." score 0.5. So "always 0.5" became "0.5 for a reply that is only a number" in sections 1, 7.4, 7.5, 8.1 and 8.2. |
| P6: #1837 does not overlap | The base is the merge commit `cc601a72`, whose tree equals `1c5a6ff9`'s. |
| D5: the drift figure | **Corrected in review round 1** (section 3, D5; section 17): z = +/- sqrt(N) holds for the first measured run only. With the 0.5 rows still in the window the next runs give 3.00, 2.38 and 2.00 (up to four signals per agent), the cutoffs at exactly N = 4 and N = 9 depend on floating-point rounding, and the Tier-3 `__crew__` series and the Vitals Monitor read the same rows. A critical drift makes the Counselor run an assessment, and a DM follows only if the assessment already warrants one (`counselor.py:1475-1536`, `:2449-2459`). |
| AV1: no client defines `complete_sync` | `def complete_sync(` occurs nowhere in `src`. |
| AV7: no billet requires the probe | `episodic_recall_probe` occurs outside tests and archived prompts only at `qualification_tests.py:345` and in an era decisions file. |
| The census | 12 read sites of `.text` on a `complete()` result in 10 files (an AST pass over `src/probos`, with positive controls): 3 here; 7 wrong in the same way (`avatars/render_verification.py:294`, `avatars/vision_intent_divergence.py:209`, `cognitive/self_render_verify.py:141`, `cognitive/counselor.py:913`, `tools/browser/actions.py:1299`, `tools/browser/compute_use.py:213`, `tools/browser/llm_classifier.py:154`); 2 that read `content` first and are right (`cognitive/insights.py:317`, `cognitive/schedule_parser.py:174`). |

Filed: #1838 (BF-989: the selection `await` and the memoryless recall) and, on #1820, the seven readers, the adoption of this reader by the three existing ones and the census (added before the pull request opens); and, after review round 1, #1839 (BF-990: the Vitals Monitor's alert on every heartbeat, in the same pull request) and item bf-988 R6 of #1820 (the permanent 0.5 baseline).

## For the register (#1523)

- **R-1.** The size of the drift transient (D5) and of the Vitals Monitor's repetition (#1839) on the live vessel. The live count needs the store (#1193).
- **R-2.** The seven remaining readers and the census (#1820 item).
- **R-3.** The reminiscence recall design and the selection `await` (separate issue).

### Premises to verify first-hand before building (each with its probe)

| P | Premise | Probe (assert it) |
|---|---|---|
| P1 | BF-988 is free | Re-run AV5 after #1837 merges; `open-ads-report.md`'s BF row still says next free BF-988 |
| P2 | Red first | With only 7.1 added: collection fails on the import. With a temporary stub `llm_response_text = lambda r: ""` in a scratch copy (or after 7.2 alone), T2's three parse cases, T3, T4, T6, T7 and T8 fail and T5 passes. Record the times and the two files' sha256 |
| P3 | The Counselor path is dead in production | `GuidedReminiscenceEngine(episodic_memory=MockEpisodicMemory([...one Episode for "a1"...]) from probos.cognitive.episodic_mock, llm_client=<spy>).run_session("a1")` raises `TypeError` mentioning `coroutine`, and the spy's `complete` was never awaited |
| P4 | The measured effect on base | `score_recall` over `LLMResponse(content="0.9")` returns 0.5; `build_therapeutic_response` returns a string starting `LLMResponse(` |
| P5 | Each SEARCH matches once | `rg -c` the first distinctive line of each of the seven blocks; each resolves to one location |
| P6 | #1837 does not overlap | `git diff --stat <origin/main before #1837> <its merge> -- src/probos/types.py src/probos/cognitive/guided_reminiscence.py tests/test_ad541d_guided_reminiscence.py tests/test_ad566b_baseline_tests.py` is empty |
| P7 | Cross-module test imports work | `python -c "import tests.test_ad541d_guided_reminiscence, tests.test_ad566b_baseline_tests"` from the repo root |

**Only later shows:** the drift transient's size (the live weekly run, or `qualification run`), and the distribution of real `episodic_recall_probe` scores.

## 17. Amendment A1: review round 1 (gpt-6.1-sol, REQUEST CHANGES), four findings repaired

Review round 1 of `fc9b9a6f` (finished 05:38Z; `next/adq/b6/review-r1.out.md`) found four things. The orchestrator re-ran each first-hand (probe `probe_f1_f2.py`, evidence `probe-f1-f2.cand.out.txt` and `probe-f1-f2.base.out.txt`; the Vitals measurement `probe-vitals-diag.out.txt`) and took the decisions below through the Architect (read-only consult `2a7391b7`, 2026-11-20, recorded on #1523 at `issuecomment-7031889207`).

| Finding | Reviewer's class | Verified | Disposition |
|---|---|---|---|
| F1: the rollout record (D5) understated the drift effect | P2, ordinary, regression | Larger than reported: up to four consecutive weekly runs signal per agent (|z| 4.36, 3.00, 2.38, 2.00 for 19 legacy rows of 0.5 and a steady score), the cutoffs at exactly N = 4 and N = 9 depend on floating-point rounding, the Tier-3 `scaffold_decomposition` of `__crew__` reads the same rows, the permanent auto-captured 0.5 baseline never rolls out, and a critical report makes the Vitals Monitor repeat its `medical_alert` on every heartbeat for one Diagnostician LLM call each (measured: 3 alerts and 3 calls in 3 heartbeats) | The record is corrected (D5, section 5, 7.4, 7.5, 8.2, 16). No code mitigation: every in-code form discounts stored data or adds a heuristic (the Captain's, for a live vessel). The Vitals repetition is #1839 (BF-990), edge-triggered, and lands no later than this change. The baseline residue is #1820, item bf-988 R6 |
| F2: a failed judge is stored as a measured passing 0.5 | P2, injected-only (the reviewer); ordinary by my reading (BF-711 was filed from a real outage) | Identical on the base and this candidate: `score=0.5 passed=True error=None inconclusive=False` | **Fixed here** (Architect): `score_recall_outcome`, `RecallScore`, and the probe's `inconclusive`/`error`/`passed`. Sections 17.1 to 17.3 |
| F3: "every recall scored 0.5" | P3, ordinary, regression | `score_recall` over a base `LLMResponse`: "0.8" -> 0.5, "The score is 0.8 out of 1" -> 0.8, "I would say 0.6 maybe" -> 0.6 | PROGRESS.md and the new test's docstring say what the amendment of section 16 (P4) already said. Sections 17.3, 17.4 |
| F4: `_Client.prompts` is written and never read | P3, size | `rg prompts tests/test_bf988_llm_response_text.py`: the two lines only | Removed. Section 17.3 |

Sections 3 (D5), 5, 7.1 (the two corrected places), 7.4, 7.5, 8.2 and 16 above were corrected in place; the blocks of this section move the files as committed at `fc9b9a6f` to the state those sections now show. Where an older sentence of sections 0 to 16 disagrees with this section, this section governs.

**Milestone M3** (one Builder delegation, tier LOW, then one local commit for the contract text, one for the source and test, one for the trackers): 17.1, 17.2, 17.3 first, then 17.4. Focused gate: `pytest tests/test_bf988_llm_response_text.py tests/test_ad541d_guided_reminiscence.py tests/test_ad566b_baseline_tests.py tests/test_ad566a_qualification_harness.py tests/test_ad566c_drift_detection.py -q -n 0`.

### 17.1 `src/probos/cognitive/guided_reminiscence.py` (A1)

**A1-1.** `src/probos/cognitive/guided_reminiscence.py`: the new dataclass, before `ReminiscenceResult`.

SEARCH:
```python
@dataclass
class ReminiscenceResult:
```
REPLACE:
```python
@dataclass(frozen=True)
class RecallScore:
    """A recall score, and why it is not a measurement when it is not (BF-711).

    ``inconclusive`` is empty for a measurement. It names the reason when the score is the 0.5
    fallback: the judge call failed, or its reply held no number.
    """

    score: float
    inconclusive: str = ""


@dataclass
class ReminiscenceResult:
```

**A1-2.** `src/probos/cognitive/guided_reminiscence.py`: `score_recall` keeps its float contract and delegates; the body below it becomes `score_recall_outcome`.

SEARCH:
```python
    async def score_recall(self, recalled_text: str, expected_summary: str) -> float:
```
REPLACE:
```python
    async def score_recall(self, recalled_text: str, expected_summary: str) -> float:
        """Score recall accuracy: the score of ``score_recall_outcome``."""
        return (await self.score_recall_outcome(recalled_text, expected_summary)).score

    async def score_recall_outcome(self, recalled_text: str, expected_summary: str) -> RecallScore:
```

**A1-3.** `src/probos/cognitive/guided_reminiscence.py`: the first line of the docstring that A1-2 left on `score_recall_outcome`.

SEARCH:
```python
        """Score recall accuracy.
```
REPLACE:
```python
        """Score recall accuracy and say, in ``inconclusive``, why a 0.5 is the fallback and not a measurement (BF-711).
```

**A1-4.** `src/probos/cognitive/guided_reminiscence.py`: an empty expected summary is a measurement.

SEARCH:
```python
        if not expected_summary:
            return 1.0
```
REPLACE:
```python
        if not expected_summary:
            return RecallScore(1.0)
```

**A1-5.** `src/probos/cognitive/guided_reminiscence.py`: a number the judge returned is a measurement.

SEARCH:
```python
                        return max(0.0, min(1.0, val))
```
REPLACE:
```python
                        return RecallScore(max(0.0, min(1.0, val)))
```

**A1-6.** `src/probos/cognitive/guided_reminiscence.py`: a reply with no number (an error reply reads "" through the reader) is inconclusive. The SEARCH is the start of the line; the rest of it stays.

SEARCH:
```python
                return 0.5  # LLM returned unparseable
```
REPLACE:
```python
                return RecallScore(0.5, "judge returned unparseable output")  # LLM returned unparseable
```

**A1-7.** `src/probos/cognitive/guided_reminiscence.py`: a judge call that raised is inconclusive, with the exception's type.

SEARCH:
```python
            except Exception:
                logger.debug("AD-541d: LLM scoring failed, falling back to Jaccard", exc_info=True)
                return 0.5  # Degrade gracefully
```
REPLACE:
```python
            except Exception as exc:
                logger.debug("AD-541d: LLM scoring failed, falling back to Jaccard", exc_info=True)
                return RecallScore(0.5, f"judge call failed: {type(exc).__name__}")  # Degrade gracefully
```

**A1-8.** `src/probos/cognitive/guided_reminiscence.py`: the Jaccard path (no client) is a measurement.

SEARCH:
```python
        # Fallback: Jaccard similarity
        return jaccard_similarity(
            text_to_words(recalled_text),
            text_to_words(expected_summary),
        )
```
REPLACE:
```python
        # Fallback: Jaccard similarity
        return RecallScore(jaccard_similarity(
            text_to_words(recalled_text),
            text_to_words(expected_summary),
        ))
```

### 17.2 `src/probos/cognitive/qualification_tests.py` (A1)

**A1-9.** `src/probos/cognitive/qualification_tests.py`: `EpisodicRecallProbe` keeps the reasons of the episodes whose judge failed.

SEARCH:
```python
        per_episode = []
        total_accuracy = 0.0
```
REPLACE:
```python
        per_episode = []
        total_accuracy = 0.0
        unmeasured: list[str] = []  # BF-711: a judge that failed or answered no number measured nothing
```

**A1-10.** `src/probos/cognitive/qualification_tests.py`: each episode is scored through the outcome and carries the judge's reason when it has one.

SEARCH:
```python
            # Score
            accuracy = await engine.score_recall(recalled_text, expected_summary)
            classification = engine.classify_recall(
                recalled_text, expected_summary, episode, accuracy,
            )

            per_episode.append({
                "episode_id": str(episode_id),
                "accuracy": accuracy,
                "classification": classification.value,
            })
            total_accuracy += accuracy
```
REPLACE:
```python
            # Score
            scored = await engine.score_recall_outcome(recalled_text, expected_summary)
            accuracy = scored.score
            classification = engine.classify_recall(
                recalled_text, expected_summary, episode, accuracy,
            )

            entry = {
                "episode_id": str(episode_id),
                "accuracy": accuracy,
                "classification": classification.value,
            }
            if scored.inconclusive:
                entry["judge"] = scored.inconclusive
                unmeasured.append(scored.inconclusive)
            per_episode.append(entry)
            total_accuracy += accuracy
```

**A1-11.** `src/probos/cognitive/qualification_tests.py`: one failed judge makes the run inconclusive and not passed; `error` keeps `run_test` from taking it as a baseline and `inconclusive` keeps the drift detector from counting it (BF-711).

SEARCH:
```python
        avg_accuracy = total_accuracy / len(per_episode) if per_episode else 0.0

        return TestResult(
            agent_id=agent_id,
            test_name=self.name,
            tier=self.tier,
            score=avg_accuracy,
            passed=avg_accuracy >= self.threshold,
            timestamp=time.time(),
            duration_ms=(time.time() - t0) * 1000,
            details={
                "episodes_tested": len(per_episode),
                "per_episode": per_episode,
                "skipped": False,
            },
        )
```
REPLACE:
```python
        avg_accuracy = total_accuracy / len(per_episode) if per_episode else 0.0
        inconclusive = bool(unmeasured)

        return TestResult(
            agent_id=agent_id,
            test_name=self.name,
            tier=self.tier,
            score=avg_accuracy,
            passed=not inconclusive and avg_accuracy >= self.threshold,
            timestamp=time.time(),
            duration_ms=(time.time() - t0) * 1000,
            details={
                "episodes_tested": len(per_episode),
                "per_episode": per_episode,
                "skipped": False,
            },
            error=f"{len(unmeasured)}/{len(per_episode)} episodes: {unmeasured[0]}" if inconclusive else None,
            inconclusive=inconclusive,
        )
```

### 17.3 `tests/test_bf988_llm_response_text.py` (A1)

**A1-12.** `tests/test_bf988_llm_response_text.py`: the docstring says what the base did (F3).

SEARCH:
```python
``guided_reminiscence.py`` took the dataclass repr: ``score_recall`` parsed no number and returned
0.5, ``build_therapeutic_response`` returned the repr, and ``run_session`` recalled it. Every
```
REPLACE:
```python
``guided_reminiscence.py`` took the dataclass repr: ``score_recall`` returned 0.5 for a reply that is
only a number (the repr wraps it in ``content='...'``, which the parse skips; a number inside a
sentence was parsed out of the repr by accident), ``build_therapeutic_response`` returned the repr,
and ``run_session`` recalled it. Every
```

**A1-13.** `tests/test_bf988_llm_response_text.py`: the new tests use `Path` and the harness and store.

SEARCH:
```python
import time
from types import SimpleNamespace
```
REPLACE:
```python
import time
from pathlib import Path
from types import SimpleNamespace
```

**A1-14.** `tests/test_bf988_llm_response_text.py`: the harness and the store.

SEARCH:
```python
from probos.cognitive.qualification_tests import EpisodicRecallProbe
```
REPLACE:
```python
from probos.cognitive.qualification import QualificationHarness, QualificationStore
from probos.cognitive.qualification_tests import EpisodicRecallProbe
```

**A1-15.** `tests/test_bf988_llm_response_text.py`: the prompt log has no reader (F4).

SEARCH:
```python
        self._error = error
        self.prompts: list[str] = []

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        prompt = request.prompt
        self.prompts.append(prompt)
        if prompt.startswith("Score the factual accuracy"):
```
REPLACE:
```python
        self._error = error

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        prompt = request.prompt
        if prompt.startswith("Score the factual accuracy"):
```

**A1-16.** `tests/test_bf988_llm_response_text.py`: T8 builds its runtime through a helper, asserts that a measured run is not inconclusive, and T9 to T12 follow.

SEARCH:
```python
@pytest.mark.parametrize(("reply", "score", "passed"), [("0.9", 0.9, True), ("0.2", 0.2, False)])
async def test_the_episodic_recall_probe_scores_a_real_reply(reply: str, score: float, passed: bool) -> None:
    episodes = [MockEpisode(id=f"ep-{i}", user_input=f"Task {i}", timestamp=float(i)) for i in range(3)]
    runtime = MagicMock()
    runtime.registry = MockRegistry(MockAgent(response="I analyzed trust patterns and the task was successful."))
    runtime.llm_client = _Client(score=reply)
    runtime.episodic_memory = MockEpisodicMemory(episodes, 3)
    result = await EpisodicRecallProbe().run("agent-1", runtime)
    assert result.error is None
    assert result.score == pytest.approx(score)
    assert result.passed is passed
```
REPLACE:
```python
def _probe_runtime(client: Any) -> MagicMock:
    episodes = [MockEpisode(id=f"ep-{i}", user_input=f"Task {i}", timestamp=float(i)) for i in range(3)]
    runtime = MagicMock()
    runtime.registry = MockRegistry(MockAgent(response="I analyzed trust patterns and the task was successful."))
    runtime.llm_client = client
    runtime.episodic_memory = MockEpisodicMemory(episodes, 3)
    return runtime


@pytest.mark.parametrize(("reply", "score", "passed"), [("0.9", 0.9, True), ("0.2", 0.2, False)])
async def test_the_episodic_recall_probe_scores_a_real_reply(reply: str, score: float, passed: bool) -> None:
    result = await EpisodicRecallProbe().run("agent-1", _probe_runtime(_Client(score=reply)))
    assert result.error is None
    assert result.inconclusive is False
    assert result.score == pytest.approx(score)
    assert result.passed is passed


# -- T9 to T12: a judge that failed is not a measurement (review round 1, F2; BF-711) -------------


class _SequenceClient:
    """Answers each judge call with the next entry: a reply text, an ``LLMResponse``, or an exception to raise."""

    def __init__(self, replies: list[Any]) -> None:
        self._replies = list(replies)

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, LLMResponse) else LLMResponse(content=reply)


_UNPARSEABLE = "judge returned unparseable output"
_RAISED = "judge call failed: RuntimeError"


@pytest.mark.parametrize(
    ("reply", "score", "reason"),
    [
        pytest.param("0.9", 0.9, "", id="number"),
        pytest.param("0.5", 0.5, "", id="a-judge-that-says-0.5"),
        pytest.param("I cannot score this", 0.5, _UNPARSEABLE, id="prose"),
        pytest.param(LLMResponse(content="", error="tier unavailable"), 0.5, _UNPARSEABLE, id="error-reply"),
        pytest.param(RuntimeError("proxy down"), 0.5, _RAISED, id="raises"),
        pytest.param(None, 1.0, "", id="no-client-jaccard"),
    ],
)
async def test_score_recall_outcome_says_why_a_score_is_the_fallback(reply: Any, score: float, reason: str) -> None:
    client = None if reply is None else _SequenceClient([reply])
    outcome = await _engine(client).score_recall_outcome("a b c", "a b c")
    assert (outcome.score, outcome.inconclusive) == (pytest.approx(score), reason)


async def test_an_empty_expected_summary_is_a_measurement_and_asks_no_judge() -> None:
    outcome = await _engine(_SequenceClient([])).score_recall_outcome("anything", "")
    assert (outcome.score, outcome.inconclusive) == (1.0, "")


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        pytest.param(RuntimeError("proxy down"), _RAISED, id="raises"),
        pytest.param(LLMResponse(content="", error="tier unavailable"), _UNPARSEABLE, id="error-reply"),
    ],
)
async def test_the_probe_holds_a_failed_judge_out_of_drift(reply: Any, reason: str) -> None:
    result = await EpisodicRecallProbe().run("agent-1", _probe_runtime(_SequenceClient([reply] * 3)))
    assert result.inconclusive is True
    assert result.passed is False
    assert result.error == f"3/3 episodes: {reason}"
    assert result.score == pytest.approx(0.5)
    assert [e["judge"] for e in result.details["per_episode"]] == [reason] * 3


async def test_one_failed_judge_makes_the_run_inconclusive_and_never_a_baseline(tmp_path: Path) -> None:
    store = QualificationStore(data_dir=tmp_path)
    await store.start()
    try:
        harness = QualificationHarness(store=store)
        harness.register_test(EpisodicRecallProbe())
        runtime = _probe_runtime(_SequenceClient(["0.9", "no number here", "0.9"]))
        first = await harness.run_test("agent-1", "episodic_recall_probe", runtime)
        assert first.inconclusive is True
        assert first.passed is False
        assert first.error == f"1/3 episodes: {_UNPARSEABLE}"
        assert ["judge" in e for e in first.details["per_episode"]] == [False, True, False]
        assert first.is_baseline is False
        assert await store.get_baseline("agent-1", "episodic_recall_probe") is None
        second = await harness.run_test("agent-1", "episodic_recall_probe", _probe_runtime(_SequenceClient(["0.9"] * 3)))
        assert second.inconclusive is False
        assert second.is_baseline is True
    finally:
        await store.stop()


async def test_a_judge_that_replies_0_5_is_a_measurement() -> None:
    result = await EpisodicRecallProbe().run("agent-1", _probe_runtime(_SequenceClient(["0.5"] * 3)))
    assert (result.inconclusive, result.error, result.passed) == (False, None, True)
    assert result.score == pytest.approx(0.5)
    assert all("judge" not in e for e in result.details["per_episode"])
```

### 17.4 The trackers (A1)

**A1-17.** `PROGRESS.md`: the entry, corrected (F1, F3, F2).

SEARCH:
```markdown
**BF-988 (2026-11-20), #1523 F-19 -- an LLM reply's text is read through one reader, so guided reminiscence never takes a response's repr as its text.** `LLMResponse` has `content` and no `text`, so the three `response.text ... if hasattr(response, 'text') else str(response)` reads in `cognitive/guided_reminiscence.py` (`score_recall`, `build_therapeutic_response`, `run_session`) took the dataclass repr: every recall scored 0.5 and the therapeutic message and recalled text were the repr. New `probos.types.llm_response_text` (an `error` reply reads ""; a `str` `content`; else a `str` `text`; else "", never the repr) replaces the three reads. In production only the AD-566 D2 `episodic_recall_probe` reached the defect: its score was 0.5 for a reply that is only a number, so it nearly always passed its 0.5 threshold, and it is now measured, so the first measured result can raise one drift warning or critical per agent whose stored history is all 0.5. The Counselor's sessions never reached the reads: `select_episodes_for_session` calls the async `recent_for_agent` without `await` and raises at `len()`, caught by the Counselor. That defect, and that both AD-541c practice and AD-541d sessions take their "recall" from a memoryless fast-tier call, are filed as #1838 (BF-989), since repairing the `await` alone would turn on confabulation diagnoses built on that call. Seven other `.text` readers of a reply are filed on #1820. New `tests/test_bf988_llm_response_text.py`. Contract `prompts/bf-988-llm-response-text.md`.
```
REPLACE:
```markdown
**BF-988 (2026-11-20), #1523 F-19 -- an LLM reply's text is read through one reader, so guided reminiscence never takes a response's repr as its text.** `LLMResponse` has `content` and no `text`, so the three `response.text ... if hasattr(response, 'text') else str(response)` reads in `cognitive/guided_reminiscence.py` (`score_recall`, `build_therapeutic_response`, `run_session`) took the dataclass repr: a reply that is only a number scored 0.5 (a number inside a sentence was parsed out of the repr by accident), and the therapeutic message and recalled text were the repr. New `probos.types.llm_response_text` (an `error` reply reads ""; a `str` `content`; else a `str` `text`; else "", never the repr) replaces the three reads. In production only the AD-566 D2 `episodic_recall_probe` reached the defect, and it is now measured: an agent whose stored history is all 0.5 can signal drift on up to four consecutive runs (the first one or two critical), the Tier-3 `scaffold_decomposition` of `__crew__` moves with it, and a critical report makes the Vitals Monitor repeat its alert on every heartbeat until the next run (#1839, BF-990, edge-triggers that and lands no later than this change); DECISIONS has the figures. The probe now reports a judge that failed or answered no number as inconclusive (`GuidedReminiscenceEngine.score_recall_outcome`, the BF-711 rule), so an outage is neither a drift sample nor a baseline. The Counselor's sessions never reached the reads: `select_episodes_for_session` calls the async `recent_for_agent` without `await` and raises at `len()`, caught by the Counselor. That defect, and that both AD-541c practice and AD-541d sessions take their "recall" from a memoryless fast-tier call, are filed as #1838 (BF-989), since repairing the `await` alone would turn on confabulation diagnoses built on that call. Seven other `.text` readers of a reply are filed on #1820. New `tests/test_bf988_llm_response_text.py`. Contract `prompts/bf-988-llm-response-text.md`.
```

**A1-18.** `DECISIONS.md`: the entry's effect, decision, rejection and filing bullets, corrected (F1, F2).

SEARCH:
```markdown
- *Effect, recorded.* An agent whose stored `episodic_recall_probe` history is N results of exactly 0.5 gets z = sqrt(N) on its first measured score that differs: warning at N >= 4, critical at N >= 9, once. No migration: the rows leave the 20-result window. The live count needs the data store (#1193) and is not taken.
- *Decided by the Architect.* None of the six conditions is met: an additive internal helper, no schema, control, spend or boundary; a measurement is turned on, not a feature.
- *Rejected.* A `text` property on `LLMResponse` (switches on six features at once; two names for one field); `repr=False` on the AD-1327 fields (no reader uses the repr as text after this; diagnostics lose it); the selection `await` (it would turn on Counselor diagnoses built on a memoryless fast-tier recall); repairing the other readers now (each changes a feature's behaviour).
- *Filed.* The selection `await` and the AD-541c/d recall design (#1838, BF-989); seven other `.text` readers, adoption of this reader by the three existing ones, and a census asserting zero (#1820).
```
REPLACE:
```markdown
- *Effect, recorded (review round 1 corrected it).* The detector reads the newest 20 stored rows, with the new row in the window, so an agent whose last N rows (N at most 19) are exactly 0.5 gets z = +-sqrt(N) on its first measured score, whatever that score is (a constant history has no spread), and the 0.5 rows stay in the window. With N = 19 and a steady score the next runs give 3.00, 2.38, 2.00 and then 1.73 (a probe on the real store and detector): up to four consecutive runs signal per agent, critical, then critical or warning, then warning twice, and the cutoffs at exactly N = 4 and N = 9 depend on floating-point rounding (N = 4 with a new score of 0.7 gives no signal; N = 9 with 0.9 gives a warning, not a critical). Each signal emits `QUALIFICATION_DRIFT_DETECTED`: the Counselor runs an assessment on a critical one and sends a DM only when it warrants one; the Tier-3 `scaffold_decomposition` of `__crew__` reads each crew member's latest stored score, so it moves and signals the same way; and while any latest report is critical the Vitals Monitor repeats its `medical_alert` on every 5 s heartbeat until the next run replaces the report, one Diagnostician LLM call each (measured on the real classes; existing behaviour for any critical drift; edge-triggered by #1839, BF-990, which lands no later than this change).
- *Rollout.* The first automatic run is seven days after a boot (the loop sleeps one interval first); `qualification run` starts the same path on demand, so the transient decays with the number of runs, not with weeks. The auto-captured baseline of 0.5 is not replaced (`run_test` takes one only when none exists; `run_baseline` and `set_baseline` have no caller in `src`), so `direction` stays measured from 0.5 (#1820, item bf-988 R6). No migration, and none in code: discounting the old rows is a new heuristic or a change of stored data on a live vessel, which is the Captain's. The operator's options are `qualification.drift_check_enabled`, `drift_warning_sigma`, `drift_critical_sigma` and `drift_check_tiers`, and a restart (the cached reports are in memory). The live count needs the data store (#1193) and is not taken.
- *Judge failure (review round 1, F2).* On the base a judge that failed or answered no number was stored as `score=0.5, passed=True, inconclusive=False`, a measurement; against a history of measured scores it reads as a decline (z -4.36 after 19 results of 0.9). `GuidedReminiscenceEngine.score_recall_outcome` returns `RecallScore(score, inconclusive)` and `score_recall` keeps its float contract and delegates: a failed call or a reply with no number is inconclusive, decided by branch and not by value (a judge that says 0.5 is a measurement; no client, the Jaccard path, is a measurement). `EpisodicRecallProbe` then returns `inconclusive=True`, `passed=False` and an `error` (`k/n episodes: reason`; the `error` is also what keeps `run_test` from taking the run as a baseline), the BF-711 pattern of `communication_benchmarks.py`.
- *Decided by the Architect.* None of the six conditions is met: an additive internal helper, no schema, control, spend or boundary; a measurement is turned on, not a feature. Review round 1 (consult `2a7391b7`): the corrected effect is inside the envelope; the Vitals repetition was measured first, as the consult required, and is #1839 (BF-990); the judge-failure repair belongs to this change.
- *Rejected.* A `text` property on `LLMResponse` (switches on six features at once; two names for one field); `repr=False` on the AD-1327 fields (no reader uses the repr as text after this; diagnostics lose it); the selection `await` (it would turn on Counselor diagnoses built on a memoryless fast-tier recall); repairing the other readers now (each changes a feature's behaviour); an in-code discount of the stored 0.5 rows (a new heuristic, or a change of stored data on a live vessel).
- *Filed.* The selection `await` and the AD-541c/d recall design (#1838, BF-989); seven other `.text` readers, adoption of this reader by the three existing ones, and a census asserting zero (#1820); the Vitals Monitor's alert on every heartbeat (#1839, BF-990); the permanent 0.5 baseline (#1820, item bf-988 R6).
```

### 17.5 Generated: the ledger pair (A1)

After 17.4, run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`. It regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`; do not paste them. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`.

### 17.6 Mutation rows (A1; one more campaign over the new rows, restore between rows)

| # | Site | Mutate to | Killed by |
|---|---|---|---|
| R-12 | probe: `inconclusive=inconclusive,` | `inconclusive=False,` | T10 (both), T11 |
| R-13 | probe: the `error=f"{len(unmeasured)}/..."` line | `error=None,` | T10 (both), T11 |
| R-14 | probe: `if scored.inconclusive:` | `if accuracy == 0.5:` (failure decided by value) | T12 |
| R-15 | probe: `passed=not inconclusive and avg_accuracy >= self.threshold,` | `passed=avg_accuracy >= self.threshold,` | T10 (both), T11 |
| R-16 | engine: `f"judge call failed: {type(exc).__name__}"` | `""` | T9[raises], T10[raises] |
| R-17 | engine: `"judge returned unparseable output"` | `""` | T9[prose], T9[error-reply], T10[error-reply], T11 |
| R-18 | engine: `return RecallScore(1.0)` | `return RecallScore(1.0, "x")` | the empty-summary test |
| R-19 | engine: `score_recall`'s `.score` | `return 0.0` | T2, T4, T5 |

### 17.7 Reviewer properties for the delta (properties to verify, not attack scenarios)

1. `score_recall` still returns a `float` with the same value for every input as before this amendment (its only change is that it delegates), and `run_session` still calls it.
2. `score_recall_outcome` marks exactly two branches inconclusive, the raised judge call and the reply without a number, and decides by branch: a judge that says "0.5", an empty expected summary and the no-client Jaccard path are measurements.
3. `EpisodicRecallProbe` returns `inconclusive=True`, `passed=False` and an `error` of the form `k/n episodes: reason` when any episode's judge failed, keeps `score` as the mean, adds `judge` to the failed episodes' entries only, and is unchanged for a run with no failed judge (`error` None, `inconclusive` False, `passed` by the threshold).
4. The consumers accept it: `QualificationHarness.run_test` takes no baseline from an errored run (`qualification.py:443-448`); `DriftDetector._analyze_single` drops inconclusive rows (`drift_detector.py:150`); `ScaffoldDecompositionProbe` skips results with an `error` (`collective_tests.py:199`); the store round-trips `inconclusive` and `error` (`qualification.py:342-366`).
5. The corrected effect in D5, 7.4, 7.5, 8.2 and 16 holds against `drift_detector.py:135-250` and the consumers named in section 5. Outside the SEARCH blocks of 17.4, which quote the text they replace, no sentence still says "once" or "one drift signal", and none says every recall scored 0.5.
6. The two files outside the tests and trackers that change are `guided_reminiscence.py` and `qualification_tests.py`, and in the first only `RecallScore`, `score_recall`'s delegation and `score_recall_outcome` differ from the committed candidate.
