"""Web + Content utility agents (AD-248).

All web-facing agents dispatch ``http_fetch`` through the mesh via
``self._runtime.intent_bus.broadcast()`` — never httpx directly.
"""

from __future__ import annotations

import html
import json
import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import (
    CapabilityDescriptor,
    IntentDescriptor,
    IntentMessage,
    IntentResult,
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Bundled agent mixin: self-deselect for unrecognized intents
# ------------------------------------------------------------------

class _BundledMixin:
    """Mixin that guards handle_intent to self-deselect unrecognized intents.

    Without this guard, the mesh broadcasts every intent to every agent.
    CognitiveAgent runs full perceive→decide→act for ANY intent, which
    causes cascading sub-intent broadcasts from perceive() overrides.
    """

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        if intent.intent not in self._handled_intents:
            return None  # Self-deselect
        return await super().handle_intent(intent)


# ------------------------------------------------------------------
# Helper: dispatch http_fetch through the mesh
# ------------------------------------------------------------------

async def _mesh_fetch_detailed(
    runtime: Any, url: str
) -> tuple[str | None, int | None, str | None]:
    """``(body, status_code, final_url)`` for one URL, fetched through the mesh.

    BF-769: the status is what tells a rate-limit page apart from a page with
    nothing on it. ``HttpFetchAgent`` reports EVERY HTTP status as a successful
    fetch -- a 429 challenge and a 200 empty-result page are both
    ``success=True`` -- so a caller that drops the status cannot tell "the
    engine refused me" from "the engine found nothing", and will state the
    second with confidence when the first is true.

    The final URL matters for the same reason: the fetch follows redirects, so
    a DuckDuckGo bang (``!w langchain``) lands on Wikipedia. That body has no
    search-result blocks and is not a search failure -- it is the page the
    Captain asked for.
    """
    if not runtime or not hasattr(runtime, "intent_bus"):
        return None, None, None
    msg = IntentMessage(intent="http_fetch", params={"url": url})
    results = await runtime.intent_bus.broadcast(msg)
    for r in results:
        if r.success and r.result:
            payload = r.result
            if isinstance(payload, dict):
                status = payload.get("status_code")
                final = payload.get("url")
                body = payload.get("body", payload.get("content"))
                if body is None:
                    body = str(payload)
                return (
                    str(body),
                    status if isinstance(status, int) else None,
                    final if isinstance(final, str) else None,
                )
            return str(payload), None, None
    return None, None, None


async def _mesh_fetch(runtime: Any, url: str) -> str | None:
    """Body text for one URL, fetched through the mesh. Status discarded.

    Kept for callers that only ever read a page they expect to exist. Anything
    that must distinguish "refused" from "empty" wants
    :func:`_mesh_fetch_detailed` instead.
    """
    body, _status, _final = await _mesh_fetch_detailed(runtime, url)
    return body


# ------------------------------------------------------------------
# Helper: parse DuckDuckGo HTML search results
# ------------------------------------------------------------------

_DDG_TITLE_RE = re.compile(
    r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_DDG_SNIPPET_RE = re.compile(
    r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


def _strip_tags(fragment: str) -> str:
    """Strip HTML tags and unescape entities from a fragment."""
    text = re.sub(r"<[^>]+>", " ", fragment)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def _decode_ddg_url(href: str) -> str:
    """Decode a DuckDuckGo redirect href to the underlying target URL.

    DDG HTML results wrap the real URL in a redirect of the form
    ``//duckduckgo.com/l/?uddg=<url-encoded-target>&rut=...``. Extract the
    ``uddg`` parameter when present; otherwise return the href unchanged.
    """
    href = html.unescape(href).strip()
    parsed = urllib.parse.urlparse(href)
    if "uddg" in urllib.parse.parse_qs(parsed.query):
        return urllib.parse.parse_qs(parsed.query)["uddg"][0]
    if href.startswith("//"):
        return "https:" + href
    return href


def _parse_ddg_results(body: str, *, max_results: int = 10) -> list[dict[str, str]]:
    """Parse DuckDuckGo HTML into a list of ``{title, url, snippet}`` dicts.

    Titles and snippets are emitted by DDG in parallel order (one snippet per
    result), so they are paired by index; a result missing a snippet gets an
    empty string rather than being dropped.
    """
    titles = _DDG_TITLE_RE.findall(body)
    snippets = _DDG_SNIPPET_RE.findall(body)
    out: list[dict[str, str]] = []
    for i, (href, title_html) in enumerate(titles[:max_results]):
        title = _strip_tags(title_html)
        if not title:
            continue
        snippet = _strip_tags(snippets[i]) if i < len(snippets) else ""
        out.append(
            {"title": title, "url": _decode_ddg_url(href), "snippet": snippet}
        )
    return out


def _format_ddg_results(results: list[dict[str, str]]) -> str:
    """Render parsed results as a compact, LLM-friendly block."""
    blocks = []
    for i, r in enumerate(results, start=1):
        lines = [f"Result {i}:", f"Title: {r['title']}", f"URL: {r['url']}"]
        if r["snippet"]:
            lines.append(f"Snippet: {r['snippet']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


# ------------------------------------------------------------------
# BF-769: telling a refusal apart from a result
# ------------------------------------------------------------------

def _duckduckgo_url(query: str) -> str:
    return "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query)


# The markers on a bot-challenge page. Matching one is sufficient to know the
# search was refused; NOT matching one proves nothing, because this list cannot
# anticipate every block page DuckDuckGo will ever serve. Emptiness is therefore
# never inferred from the absence of a challenge -- see ``perceive``.
#
# Only ever applied to a body that actually came FROM DuckDuckGo: the engine
# echoes the query into its own page, and an unrelated site can mention these
# words in earnest (Wikipedia ships "hcaptcha" in its page config).
_DDG_CHALLENGE_RE = re.compile(
    r"anomaly-modal|bots use duckduckgo|unfortunately, bots|captcha|"
    r"unusual traffic", re.IGNORECASE
)


def _is_duckduckgo(url: str | None) -> bool:
    host = urllib.parse.urlparse(url or "").hostname or ""
    return host == "duckduckgo.com" or host.endswith(".duckduckgo.com")


# ------------------------------------------------------------------
# WebSearchAgent
# ------------------------------------------------------------------

class WebSearchAgent(_BundledMixin, CognitiveAgent):
    """Search the web via DuckDuckGo (dispatched through mesh http_fetch)."""

    agent_type = "web_search"
    instructions = (
        "You are a web search agent. When given a search query:\n"
        "1. The system has already run the search and parsed the results for you.\n"
        "2. Present the results clearly to the user.\n"
        "3. If no results were fetched, say the search failed and why. Do NOT\n"
        "   answer from memory as though you had searched, and never fabricate\n"
        "   results.\n"
    )
    intent_descriptors = [
        IntentDescriptor(
            name="web_search",
            params={"query": "search terms"},
            description="Search the web and return summarized results",
            requires_reflect=True,
            usage_hint="[MESH web_search query=<terms>] (search the web)",
        ),
    ]
    _handled_intents = {"web_search"}
    default_capabilities = [CapabilityDescriptor(can="web_search")]

    async def perceive(self, intent: Any) -> dict:
        obs = await super().perceive(intent)
        query = obs.get("params", {}).get("query", "")
        if not self._runtime:
            return obs
        if not query:
            # Reachable: the tool schema requires the property but permits "".
            # Falling through used to hand the LLM an empty observation, which
            # it answered from anyway -- a fabricated search reported as a
            # success, which is this defect wearing a different hat.
            obs["search_failed"] = True
            obs["search_error"] = "no search results were obtained: the query was empty"
            return obs
        body, status, final_url = await _mesh_fetch_detailed(
            self._runtime, _duckduckgo_url(query)
        )
        results = _parse_ddg_results(body) if body else []
        if results:
            # BF-611: parse the result blocks (title/url/snippet) BEFORE
            # truncating. Passing raw HTML to a fixed char budget spent the
            # budget on page chrome (head/CSS/search form) and cut off the
            # result <div>s, so the LLM never saw any results.
            obs["fetched_content"] = _format_ddg_results(results)[:8000]
            return obs

        on_duckduckgo = final_url is None or _is_duckduckgo(final_url)
        if (
            body
            and (status is None or 200 <= status < 300)
            and not on_duckduckgo
        ):
            # A DuckDuckGo bang (`!w langchain`) redirects off-site. The body is
            # the page the Captain asked for, not a search-result page, so the
            # absence of result blocks is expected rather than a failure.
            obs["fetched_content"] = _strip_tags(body)[:8000]
            return obs

        # BF-769: no results parsed. This used to fall through to tag-stripped
        # page text for EVERY body, so a bot-challenge page was handed to the
        # LLM, narrated as "Search Results Unavailable", and returned as a
        # SUCCESS -- invisible in the trace, and the agent then sourced the
        # answer from whichever tool still worked without saying its search had
        # failed.
        #
        # The reason is reported when it is known, but the OUTCOME is the same
        # either way: no results were obtained. It deliberately does not say
        # "there are none" -- a challenge page, an unfamiliar block page and a
        # genuinely empty result set are indistinguishable here, and asserting
        # absence on that evidence would be a more confident lie than the
        # silence this fixes.
        if body is None:
            reason = "the search request did not come back"
        elif status is not None and not (200 <= status < 300):
            reason = f"the search engine answered HTTP {status}"
        elif _DDG_CHALLENGE_RE.search(body):
            # Reached only for a body that came from DuckDuckGo: an off-site
            # redirect with a usable status returned above, so a page that
            # merely mentions "hcaptcha" in earnest never gets here.
            reason = "the search engine returned a bot challenge"
        else:
            reason = "the search engine returned nothing this parser could read"
        obs["search_failed"] = True
        obs["search_error"] = f"no search results were obtained: {reason}"
        logger.warning(
            "BF-769: web_search obtained no results (%s); reporting failure so "
            "the agent does not answer from memory as though it had searched. "
            "Query length %d chars (not logged: a failed search can carry a "
            "credential the Captain pasted).", reason, len(query),
        )
        return obs

    async def decide(self, observation: dict) -> dict:
        # Short-circuit before the LLM: with no results there is nothing to
        # reason over, and ``act`` discards the output anyway -- so calling the
        # model here spends a request and its latency to produce a string
        # nobody reads, on the path that is already the slowest.
        if observation.get("search_failed"):
            return {
                "action": "search_failed",
                "search_failed": True,
                "search_error": observation.get("search_error", ""),
            }
        return await super().decide(observation)

    async def act(self, decision: dict) -> dict:
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}
        if decision.get("search_failed"):
            return {"success": False, "error": decision.get("search_error", "")}
        return {"success": True, "result": decision.get("llm_output", "")}


# ------------------------------------------------------------------
# PageReaderAgent
# ------------------------------------------------------------------

class PageReaderAgent(_BundledMixin, CognitiveAgent):
    """Read and summarize a web page (fetched through mesh http_fetch)."""

    agent_type = "page_reader"
    instructions = (
        "You are a page reader agent. When given a URL:\n"
        "1. The system has already fetched the page content for you.\n"
        "2. Extract the main text content from the HTML.\n"
        "3. Summarize the content concisely, focusing on the key information.\n\n"
        "If the page couldn't be fetched, explain what happened. Never invent content."
    )
    intent_descriptors = [
        IntentDescriptor(
            name="read_page",
            params={"url": "<url>"},
            description="Read and summarize a web page",
            requires_reflect=True,
            usage_hint="[MESH read_page url=<url>] (read & summarize a web page)",
        ),
    ]
    _handled_intents = {"read_page"}
    default_capabilities = [CapabilityDescriptor(can="read_page")]

    async def perceive(self, intent: Any) -> dict:
        obs = await super().perceive(intent)
        url = obs.get("params", {}).get("url", "")
        if url and self._runtime:
            body = await _mesh_fetch(self._runtime, url)
            if body:
                # Strip HTML tags for cleaner LLM context
                text = re.sub(r"<[^>]+>", " ", body)
                text = re.sub(r"\s+", " ", text).strip()
                obs["fetched_content"] = text[:8000]
        return obs

    async def act(self, decision: dict) -> dict:
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}
        return {"success": True, "result": decision.get("llm_output", "")}


# ------------------------------------------------------------------
# WeatherAgent
# ------------------------------------------------------------------

class WeatherAgent(_BundledMixin, CognitiveAgent):
    """Get current weather for a location (via wttr.in JSON through mesh)."""

    agent_type = "weather"
    instructions = (
        "You are a weather agent. When asked about weather:\n"
        "1. The system has already fetched weather data from wttr.in for you.\n"
        "2. Parse the JSON response to extract current conditions, temperature, humidity, wind.\n"
        "3. Present the weather in a clear, friendly format.\n\n"
        "If the location is ambiguous, make a reasonable assumption and note it."
    )
    intent_descriptors = [
        IntentDescriptor(
            name="get_weather",
            params={"location": "city name"},
            description="Get current weather for a location",
            requires_reflect=True,
        ),
    ]
    _handled_intents = {"get_weather"}
    default_capabilities = [CapabilityDescriptor(can="get_weather")]

    async def perceive(self, intent: Any) -> dict:
        obs = await super().perceive(intent)
        location = obs.get("params", {}).get("location", "")
        if location and self._runtime:
            encoded = urllib.parse.quote_plus(location)
            url = f"https://wttr.in/{encoded}?format=j1"
            body = await _mesh_fetch(self._runtime, url)
            if body:
                obs["fetched_content"] = body[:8000]
        return obs

    async def act(self, decision: dict) -> dict:
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}
        return {"success": True, "result": decision.get("llm_output", "")}


# ------------------------------------------------------------------
# NewsAgent
# ------------------------------------------------------------------

# Default RSS feeds
_DEFAULT_RSS_FEEDS: dict[str, str] = {
    "reuters": "https://feeds.reuters.com/reuters/topNews",
    "bbc": "https://feeds.bbci.co.uk/news/rss.xml",
    "npr": "https://feeds.npr.org/1001/rss.xml",
}


class NewsAgent(_BundledMixin, CognitiveAgent):
    """Get latest news headlines from RSS feeds (fetched through mesh)."""

    agent_type = "news"
    instructions = (
        "You are a news headlines agent. When asked for news:\n"
        "1. The system has already fetched an RSS feed for you.\n"
        "2. The parsed headlines are included in the fetched content.\n"
        "3. Present the top headlines clearly with title and description.\n\n"
        "Default sources: Reuters, BBC, NPR.\n"
        "If the user specifies a source, note which source was used."
    )
    intent_descriptors = [
        IntentDescriptor(
            name="get_news",
            params={"source": "news source (optional)", "topic": "topic (optional)"},
            description="Get latest news headlines",
            requires_reflect=True,
        ),
    ]
    _handled_intents = {"get_news"}
    default_capabilities = [CapabilityDescriptor(can="get_news")]

    async def perceive(self, intent: Any) -> dict:
        obs = await super().perceive(intent)
        source = obs.get("params", {}).get("source", "").lower()

        # Select RSS URL
        rss_url = _DEFAULT_RSS_FEEDS.get(source, _DEFAULT_RSS_FEEDS["reuters"])
        if source and source.startswith("http"):
            rss_url = source

        if self._runtime:
            body = await _mesh_fetch(self._runtime, rss_url)
            if body:
                # Parse RSS XML and extract headlines
                headlines = self._parse_rss(body)
                obs["fetched_content"] = headlines
        return obs

    @staticmethod
    def _parse_rss(xml_text: str) -> str:
        """Extract headlines from RSS XML."""
        items: list[str] = []
        try:
            root = ET.fromstring(xml_text)
            # RSS 2.0: channel/item
            for item in root.iter("item"):
                title = item.findtext("title", "")
                desc = item.findtext("description", "")
                link = item.findtext("link", "")
                if title:
                    entry = f"- {title}"
                    if desc:
                        # Strip HTML from description
                        clean = re.sub(r"<[^>]+>", "", desc).strip()
                        entry += f"\n  {clean[:200]}"
                    if link:
                        entry += f"\n  {link}"
                    items.append(entry)
                if len(items) >= 10:
                    break
        except ET.ParseError:
            return "Failed to parse RSS feed XML."
        if not items:
            return "No headlines found in RSS feed."
        return "\n\n".join(items)

    async def act(self, decision: dict) -> dict:
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}
        return {"success": True, "result": decision.get("llm_output", "")}
