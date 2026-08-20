"""BF-772: a refused fetch is not content, on every agent that fetches.

`HttpFetchAgent` reports EVERY HTTP status as a successful fetch, so a 429
challenge page and a 200 content page are indistinguishable to a caller that
drops the status. BF-769 gave `WebSearchAgent` the status-aware seam; the three
siblings kept reading the error body as the page.

The matrix is the point of this file. Each agent is driven through its real
`perceive -> decide -> act` with an injected non-2xx, because the defect is a
refusal arriving as an answer, and only the answer shows that.
"""

from __future__ import annotations

import pytest

from probos.agents.utility import web_agents
from probos.agents.utility.web_agents import (
    NewsAgent,
    PageReaderAgent,
    WeatherAgent,
    _FetchGatedMixin,
)


class _Runtime:
    """Enough runtime for ``perceive``; the fetch itself is monkeypatched."""

    intent_bus = object()


def _intent(**params: object) -> object:
    from probos.types import IntentMessage

    return IntentMessage(intent="x", params=dict(params))


def _agent(cls: type, monkeypatch: pytest.MonkeyPatch, fetch: object) -> object:
    monkeypatch.setattr(web_agents, "_mesh_fetch_detailed", fetch)
    agent = cls(agent_id="a1")
    agent._runtime = _Runtime()
    return agent


#: ``(class, params, body_that_a_naive_reader_would_have_used)``
_AGENTS = [
    pytest.param(
        PageReaderAgent,
        {"url": "https://example.com/x"},
        "429 Too Many Requests",
        id="page-reader",
    ),
    pytest.param(
        WeatherAgent,
        {"location": "London"},
        "<html>rate limited</html>",
        id="weather",
    ),
    pytest.param(
        NewsAgent,
        {"source": "reuters"},
        "<html>rate limited</html>",
        id="news",
    ),
]


@pytest.mark.parametrize("cls,params,error_body", _AGENTS)
async def test_a_non_2xx_is_reported_as_failure_not_read_as_content(
    cls: type, params: dict, error_body: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point: the Captain is told it failed, not told the error page.

    Driven end to end. Asserting only that ``perceive`` set a flag would pass
    while ``act`` still returned ``success=True`` -- which is precisely the
    shape that let this survive BF-769.
    """
    async def _fetch(runtime: object, url: str) -> tuple[str, int, str]:
        return error_body, 429, url

    agent = _agent(cls, monkeypatch, _fetch)

    obs = await agent.perceive(_intent(**params))
    assert obs.get("fetch_failed") is True
    assert "429" in obs.get("fetch_error", "")
    assert "fetched_content" not in obs

    decision = await agent.decide(obs)
    result = await agent.act(decision)

    assert result["success"] is False
    assert "429" in result["error"]
    # The error body must not reach the Captain as though it were the answer.
    assert error_body not in str(result)


@pytest.mark.parametrize("cls,params,error_body", _AGENTS)
async def test_a_2xx_still_reads_normally(
    cls: type, params: dict, error_body: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The success path is unchanged -- this is a gate, not a new behaviour."""
    good = (
        "<rss><channel><item><title>Headline</title></item></channel></rss>"
        if cls is NewsAgent
        else "<html><body>real content here</body></html>"
    )

    async def _fetch(runtime: object, url: str) -> tuple[str, int, str]:
        return good, 200, url

    agent = _agent(cls, monkeypatch, _fetch)

    obs = await agent.perceive(_intent(**params))
    assert not obs.get("fetch_failed")
    assert obs.get("fetched_content")


@pytest.mark.parametrize("cls,params,error_body", _AGENTS)
async def test_a_fetch_that_never_came_back_is_also_a_failure(
    cls: type, params: dict, error_body: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fetch(runtime: object, url: str) -> tuple[None, None, None]:
        return None, None, None

    agent = _agent(cls, monkeypatch, _fetch)

    obs = await agent.perceive(_intent(**params))
    assert obs.get("fetch_failed") is True
    assert "did not come back" in obs.get("fetch_error", "")


async def test_an_unserved_feed_no_longer_claims_the_feed_was_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worst shape in the issue, pinned on its own.

    "No headlines found in RSS feed." is a confident statement about the world.
    Produced by a refusal it is a lie, and it is the exact defect class BF-769
    fixed in search: a failure narrated as a fact.
    """
    async def _fetch(runtime: object, url: str) -> tuple[str, int, str]:
        return "<html>429</html>", 429, url

    agent = _agent(NewsAgent, monkeypatch, _fetch)

    obs = await agent.perceive(_intent(source="reuters"))
    result = await agent.act(await agent.decide(obs))

    assert result["success"] is False
    assert "No headlines found" not in str(result)


# ── structural guards ───────────────────────────────────────────────────────


@pytest.mark.parametrize("cls", [PageReaderAgent, WeatherAgent, NewsAgent])
def test_the_gate_is_not_shadowed_by_an_agents_own_act(cls: type) -> None:
    """``NewsAgent`` kept its own ``act`` through the first draft of this fix.

    It shadowed the mixin, so News -- the agent whose failure mode the issue
    calls the worst -- would have flagged the observation and then returned
    ``success=True`` anyway. Every check above passed for the other two, which
    is exactly why this is asserted structurally rather than trusted.
    """
    assert cls.act is _FetchGatedMixin.act, (
        f"{cls.__name__} overrides act, so the fetch gate never reaches the "
        "Captain-visible result"
    )
    assert cls.decide is _FetchGatedMixin.decide, (
        f"{cls.__name__} overrides decide, so the LLM short-circuit is skipped"
    )


def test_the_status_discarding_helper_is_gone() -> None:
    """Answers the question the issue closes with.

    `_mesh_fetch` returned the body and dropped the status. Keeping it after
    moving its last three callers would leave the next author a helper whose
    whole shape is this defect. It is deleted rather than deprecated; the
    status-aware `_mesh_fetch_detailed` is the only way to fetch here now.
    """
    assert not hasattr(web_agents, "_mesh_fetch"), (
        "a status-discarding fetch helper is back; every caller must be able "
        "to tell a refusal from an empty page"
    )
    assert hasattr(web_agents, "_mesh_fetch_detailed")


# ── the seam the monkeypatched fixture above does NOT cross ─────────────────


def _provider_envelope(status: int, body: str, url: str) -> dict[str, object]:
    """The shape ``HttpFetchAgent`` really puts in ``IntentResult.result``.

    ``handle_intent`` sets ``result=report.get("data")``, so the agents receive
    this inner dict, not the outer ``{"success", "data"}`` wrapper.
    """
    return {
        "url": url,
        "status_code": status,
        "headers": {},
        "body": body,
        "body_length": len(body),
        "truncated": False,
        "total_bytes": len(body),
        "rate_limit_delay": 0.0,
    }


class _ProviderBus:
    """A bus returning a real ``IntentResult`` carrying the real envelope."""

    def __init__(self, status: int, body: str, url: str) -> None:
        self._envelope = _provider_envelope(status, body, url)

    async def broadcast(self, msg: object) -> list[object]:
        from probos.types import IntentResult

        return [IntentResult(
            intent_id="i1",
            agent_id="http_fetch_1",
            success=True,
            result=self._envelope,
            confidence=0.9,
        )]


class _ProviderRuntime:
    def __init__(self, bus: _ProviderBus) -> None:
        self.intent_bus = bus


@pytest.mark.parametrize("cls,params,_body", _AGENTS)
async def test_a_refusal_crosses_the_real_result_envelope_to_a_failed_answer(
    cls: type, params: dict, _body: str,
) -> None:
    """Provider envelope -> _mesh_fetch_detailed -> mixin -> decide -> act.

    The parametrized tests above monkeypatch ``_mesh_fetch_detailed``, so they
    prove the mixin and nothing about the contract it reads. Review called that
    out: every intermediate seam can be correct while the chain is dead. This
    one hands the agents the dict ``HttpFetchAgent`` actually emits and asserts
    the answer, with no patching of production code.

    It does NOT cross the httpx layer -- the envelope is constructed rather
    than fetched. ``test_the_reader_and_the_provider_agree_on_the_envelope``
    below is what pins those key names together.
    """
    agent = cls(agent_id="a1")
    agent._runtime = _ProviderRuntime(
        _ProviderBus(429, "429 Too Many Requests", "https://example.com/x")
    )

    result = await agent.act(await agent.decide(await agent.perceive(_intent(**params))))

    assert result["success"] is False
    assert "429" in str(result["error"])


@pytest.mark.parametrize("cls,params,_body", _AGENTS)
async def test_an_empty_2xx_is_a_failure_not_a_confident_absence(
    cls: type, params: dict, _body: str,
) -> None:
    """An empty 200 is not evidence, and News proved why it must not pass.

    The first draft let an empty 2xx through, reasoning that an empty page had
    genuinely been served. Review drove it and got ``success=True`` carrying a
    fabricated headline set: with no ``fetched_content`` the agent still calls
    the LLM, with nothing to reason from. An empty response is also not a valid
    RSS feed -- a served feed with no items is real XML and still reaches the
    honest "No headlines found".
    """
    agent = cls(agent_id="a1")
    agent._runtime = _ProviderRuntime(
        _ProviderBus(200, "   ", "https://example.com/x")
    )

    result = await agent.act(await agent.decide(await agent.perceive(_intent(**params))))

    assert result["success"] is False
    assert "empty" in str(result["error"]).lower()


def test_the_reader_and_the_provider_agree_on_the_envelope() -> None:
    """The key names are a contract between two modules that never import each other.

    ``_mesh_fetch_detailed`` reads ``status_code``/``url``/``body`` out of a
    dict that ``http_fetch`` builds. A rename on either side is silent: the
    reader falls back and the agents lose the status again, which is the whole
    defect. Pin them together.
    """
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "probos"
    provider = (src / "agents" / "http_fetch.py").read_text(encoding="utf-8")

    for key in ("status_code", "url", "body"):
        assert f'"{key}":' in provider, (
            f"http_fetch no longer emits {key!r}; _mesh_fetch_detailed reads it "
            "and will silently fall back to a status-less body"
        )


def test_every_fetching_agent_in_the_module_is_status_gated() -> None:
    """The property, not the identifier.

    The reintroduction guard above rejects the NAME ``_mesh_fetch``. Review
    showed that is weaker than it reads: a ``_mesh_fetch_body`` with the same
    status-discarding shape passes it. This asserts what actually matters --
    every agent in this module that fetches reaches a status-aware seam.

    ``WebSearchAgent`` is exempt because BF-769 gave it its own gate inline
    rather than through the mixin; it calls ``_mesh_fetch_detailed`` directly
    and inspects the status itself.
    """
    import inspect

    exempt = {"WebSearchAgent"}
    offenders: list[str] = []

    for name, obj in inspect.getmembers(web_agents, inspect.isclass):
        if obj.__module__ != web_agents.__name__ or "agent_type" not in vars(obj):
            continue
        try:
            source = inspect.getsource(obj)
        except OSError:  # pragma: no cover - source always available here
            continue
        if "_mesh_fetch_detailed" not in source and "_fetch_or_fail" not in source:
            continue
        if name in exempt:
            continue
        if not issubclass(obj, _FetchGatedMixin):
            offenders.append(name)

    assert not offenders, (
        f"{offenders} fetch but do not inherit _FetchGatedMixin, so a non-2xx "
        "body reaches the LLM as content again"
    )


def test_the_designer_teaches_new_agents_to_check_the_status() -> None:
    """The largest invitation to repeat this was the TEMPLATE, not the helper.

    #1229 asked whether keeping a status-discarding helper invites the defect
    back. Deleting it is half the answer: ``agent_designer`` hands every
    self-designed web agent a ``perceive`` example, and both examples took the
    body whenever ``r.success`` was true. A 429 would have become
    ``fetched_content`` for the next agent the ship designs itself.
    """
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "probos"
    designer = (src / "cognitive" / "agent_designer.py").read_text(encoding="utf-8")

    fetch_examples = designer.count('intent="http_fetch"')
    assert fetch_examples >= 2, "the fetch examples moved; re-point this guard"
    assert designer.count('body.get("status_code")') >= fetch_examples, (
        "a designer fetch example takes the body without reading the status; "
        "every self-designed web agent it produces will read a refusal as "
        "content"
    )
