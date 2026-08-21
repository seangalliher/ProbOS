"""BF-807 (#1271): truncation survives the seam between fetch and agent.

`HttpFetchAgent` deliberately STATES truncation rather than leaving it to be
inferred -- an agent holding a 1,048,576-char prefix cannot tell it apart from
a complete document, and on 2026-08-07 that produced a confident wrong
explanation for data that had in fact arrived.

`_mesh_fetch_detailed` returned `(body, status_code, final_url)` and dropped
both truncation fields. PageReader, Weather, News and WebSearch could describe
a capped prefix as a whole page or feed.

The fix is a record rather than a wider tuple: a 3-tuple that becomes a 5-tuple
is the shape that invites the next caller to unpack the first three and discard
the rest -- which is how the status came to be dropped and how BF-772 happened.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from probos.agents.utility import web_agents
from probos.agents.utility.web_agents import (
    FetchOutcome,
    NewsAgent,
    PageReaderAgent,
    WeatherAgent,
    WebSearchAgent,
    _with_truncation_notice,
)
from probos.types import IntentMessage


class _Runtime:
    intent_bus = object()


def _agent(cls: type, monkeypatch, outcome: FetchOutcome):
    async def _fetch(_runtime, _url):
        return outcome

    monkeypatch.setattr(web_agents, "_mesh_fetch_detailed", _fetch)
    agent = cls(agent_id="a1")
    agent._runtime = _Runtime()
    return agent


_PARAMS = {
    PageReaderAgent: {"url": "https://example.com/x"},
    WeatherAgent: {"location": "London"},
    NewsAgent: {"source": "bbc"},
    WebSearchAgent: {"query": "deep agents"},
}

_RSS = (
    "<rss><channel>"
    "<item><title>First</title><description>d1</description></item>"
    "</channel></rss>"
)

_BODIES = {
    PageReaderAgent: "<html><body>a long page</body></html>",
    WeatherAgent: '{"current_condition":[{"temp_C":"12"}]}',
    NewsAgent: _RSS,
    WebSearchAgent: "<html><body>an off-site bang landing page</body></html>",
}


# ── the seam itself ──────────────────────────────────────────────


class TestTheSeamCarriesTruncation:
    """`_mesh_fetch_detailed` is the seam the fields were lost at."""

    @staticmethod
    def _runtime_returning(payload: dict):
        from probos.mesh.intent import IntentBus
        from probos.mesh.signal import SignalManager
        from probos.types import IntentResult

        bus = IntentBus(SignalManager())

        async def _handler(intent):
            return IntentResult(
                intent_id=intent.id, agent_id="http-0", success=True, result=payload
            )

        bus.subscribe("http-0", _handler, ["http_fetch"])
        runtime = MagicMock()
        runtime.intent_bus = bus
        return runtime

    async def test_a_truncated_response_arrives_marked(self):
        runtime = self._runtime_returning(
            {
                "body": "prefix",
                "status_code": 200,
                "url": "https://e.co/x",
                "truncated": True,
                "total_bytes": 5_000_000,
            }
        )

        outcome = await web_agents._mesh_fetch_detailed(runtime, "https://e.co/x")

        assert outcome.truncated is True
        assert outcome.total_bytes == 5_000_000
        assert outcome.body == "prefix"

    async def test_a_whole_response_is_not_marked(self):
        runtime = self._runtime_returning(
            {
                "body": "everything",
                "status_code": 200,
                "url": "https://e.co/x",
                "truncated": False,
                "total_bytes": 10,
            }
        )

        outcome = await web_agents._mesh_fetch_detailed(runtime, "https://e.co/x")

        assert outcome.truncated is False

    async def test_a_producer_that_says_nothing_is_not_assumed_truncated(self):
        """Silence is not a claim of truncation -- marking every unreported
        fetch as partial would teach the agents to hedge on whole documents."""
        runtime = self._runtime_returning({"body": "b", "status_code": 200})

        outcome = await web_agents._mesh_fetch_detailed(runtime, "https://e.co/x")

        assert outcome.truncated is False
        assert outcome.total_bytes is None

    async def test_a_non_bool_truncated_value_is_not_treated_as_truth(self):
        runtime = self._runtime_returning(
            {"body": "b", "status_code": 200, "truncated": "yes"}
        )

        outcome = await web_agents._mesh_fetch_detailed(runtime, "https://e.co/x")

        assert outcome.truncated is False

    async def test_no_runtime_yields_an_empty_outcome_not_a_crash(self):
        outcome = await web_agents._mesh_fetch_detailed(None, "https://e.co/x")

        assert outcome.body is None
        assert outcome.truncated is False


class TestTheSeamIsARecordNotATuple:
    """The issue's stated reason for the shape: a tuple invites the next caller
    to unpack a prefix of it and silently drop the rest."""

    async def test_the_outcome_is_not_iterable_as_a_tuple(self):
        outcome = FetchOutcome(body="b", status_code=200)

        with pytest.raises(TypeError):
            _body, _status, _final = outcome  # type: ignore[misc]

    def test_the_record_is_frozen(self):
        outcome = FetchOutcome(body="b")

        with pytest.raises(Exception):
            outcome.body = "other"  # type: ignore[misc]


# ── what the model actually reads ────────────────────────────────


class TestTheNotice:
    def test_a_whole_document_gets_no_notice(self):
        text = _with_truncation_notice("body", FetchOutcome(body="body"))

        assert text == "body"

    def test_a_truncated_one_states_the_source_size(self):
        outcome = FetchOutcome(body="x" * 100, truncated=True, total_bytes=5000)

        text = _with_truncation_notice("x" * 100, outcome)

        assert "5,000" in text
        assert "partial document" in text

    def test_no_kept_figure_is_stated(self):
        """The producer caps RAW BYTES and decodes afterwards; the agent then
        slices the decoded text to 8,000 CHARACTERS. Three quantities, none of
        which is what the model holds. An earlier draft said "the first
        {len(body)} bytes" and was wrong twice over: it counted characters, and
        it counted them BEFORE the agent's own slice. Measured, a 5-byte cap
        over `e`-acute yields a 3-character body -- neither 5 nor 3 bytes of
        anything the reader has. A wrong number tells the model something false
        with confidence, which is the defect being fixed."""
        outcome = FetchOutcome(body="\u00e9" * 3, truncated=True, total_bytes=20)

        text = _with_truncation_notice("\u00e9" * 3, outcome)

        assert "20" in text
        assert "first 3" not in text
        assert "3 bytes" not in text

    def test_truncation_without_a_size_still_says_so(self):
        outcome = FetchOutcome(body="x", truncated=True, total_bytes=None)

        text = _with_truncation_notice("x", outcome)

        assert "cut off" in text
        assert "partial document" in text

    def test_the_notice_survives_the_agents_own_eight_thousand_char_cap(self):
        """Appended AFTER the slice, deliberately. Prepending would put it
        inside the slice and a long page would cut it away again -- the notice
        would then be missing on exactly the pages that need it most."""
        outcome = FetchOutcome(body="y" * 40_000, truncated=True, total_bytes=99_999)

        text = _with_truncation_notice(("y" * 40_000)[:8000], outcome)

        assert len(text) > 8000
        assert "partial document" in text[8000:]

    def test_the_notice_does_not_read_as_a_capability_gap(self):
        """`_CAPABILITY_GAP_RE` drives self-modification. A truncated page must
        not make the decomposer think the ship lacks a capability."""
        from probos.cognitive.decomposer import is_capability_gap

        outcome = FetchOutcome(body="x", truncated=True, total_bytes=9)
        with_size = _with_truncation_notice("x", outcome)
        without_size = _with_truncation_notice(
            "x", FetchOutcome(body="x", truncated=True)
        )

        assert not is_capability_gap(with_size)
        assert not is_capability_gap(without_size)


# ── the property the issue asks for: it reaches the agent ────────


class TestEveryConsumerCanTellAPrefixFromAWhole:
    """The issue's acceptance criterion, one test per consumer in web_agents."""

    @pytest.mark.parametrize("cls", [PageReaderAgent, WeatherAgent, NewsAgent])
    async def test_a_truncated_body_is_declared_to_the_model(
        self, cls, monkeypatch
    ):
        agent = _agent(
            cls,
            monkeypatch,
            FetchOutcome(
                body=_BODIES[cls],
                status_code=200,
                final_url="https://e.co/x",
                truncated=True,
                total_bytes=2_000_000,
            ),
        )

        obs = await agent.perceive(IntentMessage(intent="x", params=_PARAMS[cls]))

        assert "partial document" in obs["fetched_content"], (
            f"{cls.__name__} presents a capped prefix as the whole thing"
        )
        assert "2,000,000" in obs["fetched_content"]

    @pytest.mark.parametrize("cls", [PageReaderAgent, WeatherAgent, NewsAgent])
    async def test_a_whole_body_is_not_hedged(self, cls, monkeypatch):
        agent = _agent(
            cls,
            monkeypatch,
            FetchOutcome(
                body=_BODIES[cls],
                status_code=200,
                final_url="https://e.co/x",
                truncated=False,
            ),
        )

        obs = await agent.perceive(IntentMessage(intent="x", params=_PARAMS[cls]))

        assert "partial document" not in obs["fetched_content"], (
            f"{cls.__name__} calls a complete document partial"
        )

    async def test_search_declares_a_truncated_result_page(self, monkeypatch):
        page = (
            '<div class="result"><h2><a class="result__a" '
            'href="https://docs.example.com/deep">Deep Agents</a></h2>'
            '<a class="result__snippet">A harness.</a></div>'
        )
        agent = _agent(
            WebSearchAgent,
            monkeypatch,
            FetchOutcome(
                body=page,
                status_code=200,
                final_url="https://html.duckduckgo.com/html/?q=x",
                truncated=True,
                total_bytes=3_000_000,
            ),
        )

        obs = await agent.perceive(
            IntentMessage(intent="web_search", params={"query": "deep agents"})
        )

        assert "Deep Agents" in obs["fetched_content"]
        assert "partial document" in obs["fetched_content"], (
            "a capped search page can hide results, and the model is told it "
            "saw everything"
        )

    async def test_search_declares_a_truncated_bang_landing_page(self, monkeypatch):
        """A DuckDuckGo bang redirects off-site; that body is the page the
        Captain asked for, and it takes the other branch."""
        agent = _agent(
            WebSearchAgent,
            monkeypatch,
            FetchOutcome(
                body="<html><body>wikipedia article text</body></html>",
                status_code=200,
                final_url="https://en.wikipedia.org/wiki/LangChain",
                truncated=True,
                total_bytes=1_500_000,
            ),
        )

        obs = await agent.perceive(
            IntentMessage(intent="web_search", params={"query": "!w langchain"})
        )

        assert "wikipedia article text" in obs["fetched_content"]
        assert "partial document" in obs["fetched_content"]

    async def test_a_failed_fetch_still_fails_rather_than_being_hedged(
        self, monkeypatch
    ):
        """BF-772's property must survive the return-type change: a refusal is
        not content, truncated or otherwise."""
        agent = _agent(
            PageReaderAgent,
            monkeypatch,
            FetchOutcome(
                body="429 Too Many Requests",
                status_code=429,
                final_url="https://e.co/x",
                truncated=True,
                total_bytes=100,
            ),
        )

        obs = await agent.perceive(
            IntentMessage(intent="read_page", params={"url": "https://e.co/x"})
        )

        assert obs["fetch_failed"] is True
        assert "fetched_content" not in obs


# ── producer to consumer, across the real seam ───────────────────


class TestFromTheProducersCapToTheAgentsAnswer:
    """The issue asks for a test crossing HttpFetchAgent truncation to an
    agent's answer. Producer-side and consumer-side tests each passing proves
    only that both halves work -- this one spans them."""

    async def test_a_body_capped_by_http_fetch_reaches_the_agent_as_partial(
        self, monkeypatch
    ):
        import httpx

        from probos.agents.http_fetch import HttpFetchAgent
        from probos.mesh.intent import IntentBus
        from probos.mesh.signal import SignalManager

        HttpFetchAgent._inflight.clear()
        HttpFetchAgent._waiters.clear()
        HttpFetchAgent._domain_state.clear()

        full = b"<html><body>" + (b"z" * 4000) + b"</body></html>"

        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=full)

        transport = httpx.MockTransport(_handler)
        real_client = httpx.AsyncClient
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kw: real_client(transport=transport, **kw),
        )
        monkeypatch.setattr(HttpFetchAgent, "_validate_url", lambda self, url: None)

        async def _no_wait(self, _domain, state):
            state.last_request_time = 0
            return 0.0

        monkeypatch.setattr(HttpFetchAgent, "_wait_for_rate_limit", _no_wait)
        # A cap well below the body, so the producer really truncates.
        monkeypatch.setattr(HttpFetchAgent, "MAX_BODY_BYTES", 500)

        fetcher = HttpFetchAgent(agent_id="http-real", pool="http")
        bus = IntentBus(SignalManager())
        bus.subscribe(fetcher.id, fetcher.handle_intent, ["http_fetch"])

        runtime = MagicMock()
        runtime.intent_bus = bus

        reader = PageReaderAgent(agent_id="reader")
        reader._runtime = runtime

        obs = await reader.perceive(
            IntentMessage(intent="read_page", params={"url": "https://e.co/big"})
        )

        content = obs["fetched_content"]
        assert "partial document" in content, (
            "HttpFetchAgent capped the body and the reader was told nothing; "
            "it will describe a prefix as the whole page"
        )
        assert f"{len(full):,}" in content, (
            "the full size the producer measured did not reach the model"
        )

        HttpFetchAgent._inflight.clear()
        HttpFetchAgent._waiters.clear()
        HttpFetchAgent._domain_state.clear()

    async def test_an_uncapped_body_reaches_the_agent_unhedged(self, monkeypatch):
        """The other half: a body that fit must not be described as partial."""
        import httpx

        from probos.agents.http_fetch import HttpFetchAgent
        from probos.mesh.intent import IntentBus
        from probos.mesh.signal import SignalManager

        HttpFetchAgent._inflight.clear()
        HttpFetchAgent._waiters.clear()
        HttpFetchAgent._domain_state.clear()

        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html><body>short</body></html>")

        transport = httpx.MockTransport(_handler)
        real_client = httpx.AsyncClient
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kw: real_client(transport=transport, **kw),
        )
        monkeypatch.setattr(HttpFetchAgent, "_validate_url", lambda self, url: None)

        async def _no_wait(self, _domain, state):
            state.last_request_time = 0
            return 0.0

        monkeypatch.setattr(HttpFetchAgent, "_wait_for_rate_limit", _no_wait)

        fetcher = HttpFetchAgent(agent_id="http-real-2", pool="http")
        bus = IntentBus(SignalManager())
        bus.subscribe(fetcher.id, fetcher.handle_intent, ["http_fetch"])

        runtime = MagicMock()
        runtime.intent_bus = bus

        reader = PageReaderAgent(agent_id="reader-2")
        reader._runtime = runtime

        obs = await reader.perceive(
            IntentMessage(intent="read_page", params={"url": "https://e.co/small"})
        )

        assert "short" in obs["fetched_content"]
        assert "partial document" not in obs["fetched_content"]

        HttpFetchAgent._inflight.clear()
        HttpFetchAgent._waiters.clear()
        HttpFetchAgent._domain_state.clear()


# ── all the way to the model ─────────────────────────────────────


class _RecordingLLM:
    """Records the prompt the agent actually sends.

    Not a MagicMock: an auto-created attribute would let a renamed field pass
    silently, and the whole point here is that nothing between `perceive` and
    the model quietly drops the notice.
    """

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def complete(self, request, **_kw):
        self.prompts.append(f"{request.prompt}\n{request.system_prompt or ''}")
        resp = MagicMock()
        resp.content = "an answer"
        resp.tokens_used = 10
        resp.tier = "fast"
        return resp


class TestTheNoticeReachesTheModelNotJustTheObservation:
    """`obs["fetched_content"]` is not the boundary that matters. A later slice
    or a renamed field between `perceive` and `complete` would strip the notice
    and leave every test above green -- which is this repo's most common defect
    shape, every link correct and the chain dead."""

    @pytest.mark.parametrize("cls", [PageReaderAgent, WeatherAgent, NewsAgent])
    async def test_the_prompt_carries_the_truncation_notice(self, cls, monkeypatch):
        agent = _agent(
            cls,
            monkeypatch,
            FetchOutcome(
                body=_BODIES[cls],
                status_code=200,
                final_url="https://e.co/x",
                truncated=True,
                total_bytes=2_000_000,
            ),
        )
        llm = _RecordingLLM()
        agent._llm_client = llm

        obs = await agent.perceive(IntentMessage(intent="x", params=_PARAMS[cls]))
        await agent.decide(obs)

        assert llm.prompts, f"{cls.__name__} never called the model"
        assert any("partial document" in p for p in llm.prompts), (
            f"{cls.__name__} dropped the truncation notice between perceive() "
            f"and the model; it will describe a prefix as the whole thing"
        )
        assert any("2,000,000" in p for p in llm.prompts)

    @pytest.mark.parametrize("cls", [PageReaderAgent, WeatherAgent, NewsAgent])
    async def test_a_whole_document_reaches_the_model_unhedged(
        self, cls, monkeypatch
    ):
        agent = _agent(
            cls,
            monkeypatch,
            FetchOutcome(
                body=_BODIES[cls],
                status_code=200,
                final_url="https://e.co/x",
                truncated=False,
            ),
        )
        llm = _RecordingLLM()
        agent._llm_client = llm

        obs = await agent.perceive(IntentMessage(intent="x", params=_PARAMS[cls]))
        await agent.decide(obs)

        assert llm.prompts
        assert not any("partial document" in p for p in llm.prompts)
