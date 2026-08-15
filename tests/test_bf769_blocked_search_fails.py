"""BF-769: a search that did not happen must not read as a search that found nothing.

The Captain asked Ezri to research LangChain Deep Agents and got an answer
sourced from Microsoft documentation. The persisted crew trace showed why: one
of her two ``web_search`` calls hit a DuckDuckGo bot challenge, and the
challenge page came back as a SUCCESS carrying tag-stripped page text. The LLM
narrated it as "Search Results Unavailable", the trace recorded
``is_error=False``, and she quietly sourced the answer from the one tool that
still worked -- never saying her search had failed.

Measured on the live vessel 2026-08-14: DuckDuckGo serves ~2 queries and then
returns an anomaly page for the rest of a burst (6 of 8 sequential queries
blocked), recovering within minutes.

What is pinned here:
  1. results are still parsed and delivered on the happy path;
  2. a challenge, a non-2xx status, or an unreadable page all FAIL the intent,
     so the trace records is_error and the agent is told;
  3. the failure never claims the query has no results -- a block page and an
     empty result set are indistinguishable at this seam, and asserting absence
     would be a more confident lie than the silence being fixed;
  4. the failure path does not spend an LLM call whose output is discarded.
"""
from unittest.mock import MagicMock

import pytest

from probos.agents.utility import web_agents
from probos.agents.utility.web_agents import WebSearchAgent
from probos.cognitive.llm_client import MockLLMClient
from probos.types import IntentMessage


def _make_agent(cls, agent_id="bf769-1"):
    return cls(agent_id=agent_id, llm_client=MockLLMClient())


# A real DuckDuckGo anomaly page: 200 OK, readable, and not a search result.
_DDG_BLOCKED_PAGE = (
    "<html><head><title>DuckDuckGo</title></head><body>"
    "<div class='anomaly-modal__title'>Unfortunately, bots use DuckDuckGo too."
    "</div><div class='anomaly-modal__description'>Please try again.</div>"
    "</body></html>"
)

_DDG_GOOD_PAGE = (
    '<div class="result"><h2><a class="result__a" '
    'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.langchain.com%2Fdeep">'
    "Deep Agents overview</a></h2>"
    '<a class="result__snippet">Batteries-included harness.</a></div>'
)


def _agent_with_fetch(body, status=200, final_url=None):
    """A WebSearchAgent whose mesh fetch returns ``(body, status, final_url)``."""
    agent = _make_agent(WebSearchAgent)
    agent._runtime = MagicMock()
    calls: list[str] = []

    async def _fake_fetch(_runtime, url):
        calls.append(url)
        return body, status, final_url

    return agent, calls, _fake_fetch


class TestBF769HappyPath:

    @pytest.mark.asyncio
    async def test_results_are_parsed_and_delivered(self, monkeypatch):
        agent, calls, fake = _agent_with_fetch(_DDG_GOOD_PAGE)
        monkeypatch.setattr(web_agents, "_mesh_fetch_detailed", fake)

        obs = await agent.perceive(
            IntentMessage(intent="web_search", params={"query": "deep agents"})
        )

        assert "Deep Agents overview" in obs["fetched_content"]
        assert "https://docs.langchain.com/deep" in obs["fetched_content"]
        assert not obs.get("search_failed")
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_the_query_is_url_encoded_into_the_search_url(self, monkeypatch):
        agent, calls, fake = _agent_with_fetch(_DDG_GOOD_PAGE)
        monkeypatch.setattr(web_agents, "_mesh_fetch_detailed", fake)

        await agent.perceive(
            IntentMessage(intent="web_search", params={"query": "a b&c"})
        )

        assert calls == ["https://html.duckduckgo.com/html/?q=a+b%26c"]

    @pytest.mark.asyncio
    async def test_act_succeeds_on_an_ordinary_search(self):
        agent = _make_agent(WebSearchAgent)
        out = await agent.act({"llm_output": "Here are the results."})
        assert out["success"] is True
        assert out["result"] == "Here are the results."

    @pytest.mark.asyncio
    async def test_a_bang_redirect_off_duckduckgo_still_yields_page_content(
        self, monkeypatch
    ):
        # `!w langchain` redirects to Wikipedia. The body has no DDG result
        # blocks, and that is expected -- it is the page the Captain asked for,
        # not a failed search. Failing here would take away something the old
        # tag-stripping fallback did give them.
        agent, _calls, fake = _agent_with_fetch(
            "<html><body><p>LangChain is a framework.</p></body></html>",
            final_url="https://en.wikipedia.org/wiki/LangChain",
        )
        monkeypatch.setattr(web_agents, "_mesh_fetch_detailed", fake)

        obs = await agent.perceive(
            IntentMessage(intent="web_search", params={"query": "!w langchain"})
        )

        assert not obs.get("search_failed")
        assert "LangChain is a framework." in obs["fetched_content"]

    @pytest.mark.asyncio
    async def test_challenge_words_on_a_redirected_page_are_not_a_bot_challenge(
        self, monkeypatch
    ):
        # Wikipedia ships "hcaptcha" in its page config. Applying the challenge
        # regex to a body that did not come from DuckDuckGo reported a bot
        # challenge for a page that was served perfectly.
        agent, _calls, fake = _agent_with_fetch(
            "<html><body><p>Real content.</p><script>hcaptcha</script></body></html>",
            final_url="https://en.wikipedia.org/wiki/LangChain",
        )
        monkeypatch.setattr(web_agents, "_mesh_fetch_detailed", fake)

        obs = await agent.perceive(
            IntentMessage(intent="web_search", params={"query": "!w langchain"})
        )

        assert not obs.get("search_failed")
        assert "Real content." in obs["fetched_content"]

    @pytest.mark.asyncio
    async def test_a_redirect_that_still_failed_is_not_treated_as_content(
        self, monkeypatch
    ):
        agent, _calls, fake = _agent_with_fetch(
            "<html>gone</html>", status=404,
            final_url="https://en.wikipedia.org/wiki/Nope",
        )
        monkeypatch.setattr(web_agents, "_mesh_fetch_detailed", fake)

        obs = await agent.perceive(
            IntentMessage(intent="web_search", params={"query": "!w nope"})
        )

        assert obs["search_failed"] is True
        assert "HTTP 404" in obs["search_error"]

    def test_the_search_host_itself_counts_as_duckduckgo(self):
        # The load-bearing direction: html.duckduckgo.com MUST be recognised.
        # If it were not, a challenge page would look like an off-site redirect
        # and be returned to the agent as content -- the original defect.
        assert web_agents._is_duckduckgo("https://html.duckduckgo.com/html/?q=x")
        assert web_agents._is_duckduckgo("https://duckduckgo.com/?q=x")
        assert not web_agents._is_duckduckgo("https://en.wikipedia.org/wiki/X")
        # A lookalike is not the search engine. Misreading one as DDG only
        # costs a failed search, but it must not be able to claim the name.
        assert not web_agents._is_duckduckgo("https://duckduckgo.com.evil.test/x")
        assert not web_agents._is_duckduckgo("https://notduckduckgo.com/x")
        assert not web_agents._is_duckduckgo(None)

    @pytest.mark.asyncio
    async def test_a_challenge_served_from_the_search_host_still_fails(
        self, monkeypatch
    ):
        # Same body as the redirect tests, but served BY DuckDuckGo: the host
        # check is what keeps this on the failure path.
        agent, _calls, fake = _agent_with_fetch(
            _DDG_BLOCKED_PAGE,
            final_url="https://html.duckduckgo.com/html/?q=deep+agents",
        )
        monkeypatch.setattr(web_agents, "_mesh_fetch_detailed", fake)

        obs = await agent.perceive(
            IntentMessage(intent="web_search", params={"query": "deep agents"})
        )

        assert obs["search_failed"] is True
        assert "fetched_content" not in obs


class TestBF769BlockedSearchFails:

    @pytest.mark.asyncio
    async def test_a_bot_challenge_fails_the_intent(self, monkeypatch):
        agent, _calls, fake = _agent_with_fetch(_DDG_BLOCKED_PAGE)
        monkeypatch.setattr(web_agents, "_mesh_fetch_detailed", fake)

        obs = await agent.perceive(
            IntentMessage(intent="web_search", params={"query": "deep agents"})
        )

        assert obs["search_failed"] is True
        assert "bot challenge" in obs["search_error"]

    @pytest.mark.asyncio
    async def test_the_challenge_page_text_never_reaches_the_llm(self, monkeypatch):
        # The pre-BF-769 behaviour tag-stripped the challenge page into
        # fetched_content, which is what produced a confident "Search Results
        # Unavailable" narrative delivered as a success.
        agent, _calls, fake = _agent_with_fetch(_DDG_BLOCKED_PAGE)
        monkeypatch.setattr(web_agents, "_mesh_fetch_detailed", fake)

        obs = await agent.perceive(
            IntentMessage(intent="web_search", params={"query": "deep agents"})
        )

        assert "fetched_content" not in obs

    @pytest.mark.asyncio
    async def test_a_non_2xx_status_fails_even_with_a_readable_body(
        self, monkeypatch
    ):
        # HttpFetchAgent reports every status as a successful fetch, so without
        # the status the body below is indistinguishable from a real page.
        agent, _calls, fake = _agent_with_fetch(
            "<html><body>No results.</body></html>", status=429
        )
        monkeypatch.setattr(web_agents, "_mesh_fetch_detailed", fake)

        obs = await agent.perceive(
            IntentMessage(intent="web_search", params={"query": "deep agents"})
        )

        assert obs["search_failed"] is True
        assert "HTTP 429" in obs["search_error"]

    @pytest.mark.asyncio
    async def test_an_unreadable_page_fails_rather_than_being_summarised(
        self, monkeypatch
    ):
        # An unfamiliar block page matches no challenge marker. It still must
        # not become content, and must not become "there are no results".
        agent, _calls, fake = _agent_with_fetch(
            "<html><body>Access temporarily restricted.</body></html>"
        )
        monkeypatch.setattr(web_agents, "_mesh_fetch_detailed", fake)

        obs = await agent.perceive(
            IntentMessage(intent="web_search", params={"query": "deep agents"})
        )

        assert obs["search_failed"] is True
        assert "fetched_content" not in obs

    @pytest.mark.asyncio
    async def test_no_response_at_all_fails(self, monkeypatch):
        agent, _calls, fake = _agent_with_fetch(None, status=None)
        monkeypatch.setattr(web_agents, "_mesh_fetch_detailed", fake)

        obs = await agent.perceive(
            IntentMessage(intent="web_search", params={"query": "deep agents"})
        )

        assert obs["search_failed"] is True
        assert "did not come back" in obs["search_error"]

    @pytest.mark.asyncio
    async def test_the_failure_never_asserts_the_query_has_no_results(
        self, monkeypatch
    ):
        # A block page and a genuinely empty result set are indistinguishable
        # here. DuckDuckGo fuzzy-matches almost any query, so a truly empty page
        # is rare and could not be reproduced live -- claiming absence on this
        # evidence would be a more confident lie than the silence being fixed.
        for body, status in (
            (_DDG_BLOCKED_PAGE, 200),
            ("<html><body>Access temporarily restricted.</body></html>", 200),
            ("<html><body>No results.</body></html>", 503),
        ):
            agent, _calls, fake = _agent_with_fetch(body, status=status)
            monkeypatch.setattr(web_agents, "_mesh_fetch_detailed", fake)

            obs = await agent.perceive(
                IntentMessage(intent="web_search", params={"query": "deep agents"})
            )

            error = obs["search_error"]
            assert "no search results were obtained" in error
            assert "no results were found" not in error.lower()
            assert "there are no" not in error.lower()


class TestBF769FailureReachesTheMesh:

    @pytest.mark.asyncio
    async def test_decide_carries_the_failure_to_act(self, monkeypatch):
        agent, _calls, fake = _agent_with_fetch(_DDG_BLOCKED_PAGE)
        monkeypatch.setattr(web_agents, "_mesh_fetch_detailed", fake)

        obs = await agent.perceive(
            IntentMessage(intent="web_search", params={"query": "deep agents"})
        )
        decision = await agent.decide(obs)

        assert decision["search_failed"] is True

    @pytest.mark.asyncio
    async def test_the_failure_path_does_not_spend_an_llm_call(self, monkeypatch):
        # act() discards the model's output on this path, so calling it buys a
        # request and its latency to produce a string nobody reads.
        agent, _calls, fake = _agent_with_fetch(_DDG_BLOCKED_PAGE)
        monkeypatch.setattr(web_agents, "_mesh_fetch_detailed", fake)
        called = []

        async def _boom(_observation):
            called.append(1)
            raise AssertionError("the LLM must not be consulted with no results")

        monkeypatch.setattr(type(agent).__mro__[2], "decide", _boom, raising=False)

        obs = await agent.perceive(
            IntentMessage(intent="web_search", params={"query": "deep agents"})
        )
        decision = await agent.decide(obs)

        assert decision["search_failed"] is True
        assert called == []

    @pytest.mark.asyncio
    async def test_act_reports_failure_so_the_trace_records_an_error(self):
        agent = _make_agent(WebSearchAgent)

        out = await agent.act({
            "llm_output": "I could not find anything.",
            "search_failed": True,
            "search_error": "no search results were obtained: blocked",
        })

        assert out["success"] is False
        assert "no search results were obtained" in out["error"]

    @pytest.mark.asyncio
    async def test_a_blocked_search_surfaces_as_an_unsuccessful_intent(
        self, monkeypatch
    ):
        # End to end through the agent contract: this is what makes the failure
        # visible in the persisted trace instead of looking like a normal answer.
        agent, _calls, fake = _agent_with_fetch(_DDG_BLOCKED_PAGE)
        monkeypatch.setattr(web_agents, "_mesh_fetch_detailed", fake)

        result = await agent.handle_intent(
            IntentMessage(intent="web_search", params={"query": "deep agents"})
        )

        assert result is not None
        assert result.success is False


class TestBF769FetchCarriesStatus:

    @pytest.mark.asyncio
    async def test_the_real_http_agent_supplies_the_status(self, monkeypatch):
        # The status gate is only as good as the field it reads. Driving the
        # REAL HttpFetchAgent means this goes red if that agent ever stops
        # emitting status_code -- a synthetic handler injecting the field would
        # stay green through exactly that regression.
        import httpx

        from probos.agents.http_fetch import HttpFetchAgent
        from probos.mesh.intent import IntentBus
        from probos.mesh.signal import SignalManager

        class _Response:
            def __init__(self, url):
                self.url = url
                self.status_code = 429
                self.content = b"No results."
                self.headers = {"content-type": "text/html"}

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_a):
                return False

            async def request(self, _method, url):
                return _Response(url)

        agent = HttpFetchAgent(agent_id="http-real")
        monkeypatch.setattr(HttpFetchAgent, "_validate_url", lambda self, url: None)

        async def _no_wait(self, _domain, state):
            state.last_request_time = 0
            return 0.0

        monkeypatch.setattr(HttpFetchAgent, "_wait_for_rate_limit", _no_wait)
        monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: _Client())

        bus = IntentBus(SignalManager())
        bus.subscribe(agent.id, agent.handle_intent, ["http_fetch"])
        runtime = MagicMock()
        runtime.intent_bus = bus

        body, status, final = await web_agents._mesh_fetch_detailed(
            runtime, "https://html.duckduckgo.com/html/?q=x"
        )

        assert body == "No results."
        assert status == 429
        assert final == "https://html.duckduckgo.com/html/?q=x"

    @pytest.mark.asyncio
    async def test_a_result_without_a_status_yields_none_not_a_crash(self):
        from probos.mesh.intent import IntentBus
        from probos.mesh.signal import SignalManager
        from probos.types import IntentResult as _IR

        bus = IntentBus(SignalManager())

        async def _no_status(intent):
            return _IR(intent_id=intent.id, agent_id="http-0", success=True,
                       result={"body": _DDG_GOOD_PAGE})

        bus.subscribe("http-0", _no_status, ["http_fetch"])
        runtime = MagicMock()
        runtime.intent_bus = bus

        body, status, final = await web_agents._mesh_fetch_detailed(
            runtime, "https://e.co/x"
        )

        assert body == _DDG_GOOD_PAGE
        assert status is None
        assert final is None

    @pytest.mark.asyncio
    async def test_the_plain_wrapper_still_returns_just_the_body(self):
        # PageReader/Weather/News still use it; they must be unaffected.
        from probos.mesh.intent import IntentBus
        from probos.mesh.signal import SignalManager
        from probos.types import IntentResult as _IR

        bus = IntentBus(SignalManager())

        async def _ok(intent):
            return _IR(intent_id=intent.id, agent_id="http-0", success=True,
                       result={"body": "page text", "status_code": 200})

        bus.subscribe("http-0", _ok, ["http_fetch"])
        runtime = MagicMock()
        runtime.intent_bus = bus

        assert await web_agents._mesh_fetch(runtime, "https://e.co/x") == "page text"


class TestBF769NotASearch:

    @pytest.mark.asyncio
    async def test_without_a_runtime_no_search_is_attempted_or_claimed(self):
        # No runtime means no mesh to fetch through. That is not a failed
        # search, so it must not be reported as one.
        agent = _make_agent(WebSearchAgent)
        agent._runtime = None

        obs = await agent.perceive(
            IntentMessage(intent="web_search", params={"query": "deep agents"})
        )

        assert not obs.get("search_failed")
        assert "fetched_content" not in obs

    @pytest.mark.asyncio
    async def test_an_empty_query_fails_rather_than_being_answered(self, monkeypatch):
        # CORRECTED: an earlier version of this test asserted the opposite --
        # that an empty query quietly succeeds. That pinned the defect as the
        # contract. The tool schema requires the property but permits "", and
        # the registry does not validate, so this IS reachable; falling through
        # handed the LLM an empty observation which it answered from anyway.
        agent, calls, fake = _agent_with_fetch(_DDG_GOOD_PAGE)
        monkeypatch.setattr(web_agents, "_mesh_fetch_detailed", fake)

        obs = await agent.perceive(
            IntentMessage(intent="web_search", params={"query": ""})
        )

        assert obs["search_failed"] is True
        assert "query was empty" in obs["search_error"]
        assert calls == []
