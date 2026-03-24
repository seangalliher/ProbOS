"""Web + Content utility agents (AD-248).

All web-facing agents dispatch ``http_fetch`` through the mesh via
``self._runtime.intent_bus.broadcast()`` — never httpx directly.
"""

from __future__ import annotations

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

async def _mesh_fetch(runtime: Any, url: str) -> str | None:
    """Broadcast ``http_fetch`` through the mesh and return body text."""
    if not runtime or not hasattr(runtime, "intent_bus"):
        return None
    msg = IntentMessage(
        intent="http_fetch",
        params={"url": url},
    )
    results = await runtime.intent_bus.broadcast(msg)
    for r in results:
        if r.success and r.result:
            body = r.result
            if isinstance(body, dict):
                body = body.get("body", body.get("content", str(body)))
            return str(body)
    return None


# ------------------------------------------------------------------
# WebSearchAgent
# ------------------------------------------------------------------

class WebSearchAgent(_BundledMixin, CognitiveAgent):
    """Search the web via DuckDuckGo (dispatched through mesh http_fetch)."""

    agent_type = "web_search"
    instructions = (
        "You are a web search agent. When given a search query:\n"
        "1. The system has already fetched DuckDuckGo search results for you.\n"
        "2. Parse the provided HTML to extract the top results (title + snippet + URL).\n"
        "3. Present the results clearly to the user.\n\n"
        "If no results were fetched, explain what went wrong. Never fabricate search results."
    )
    intent_descriptors = [
        IntentDescriptor(
            name="web_search",
            params={"query": "search terms"},
            description="Search the web and return summarized results",
            requires_reflect=True,
        ),
    ]
    _handled_intents = {"web_search"}
    default_capabilities = [CapabilityDescriptor(can="web_search")]

    async def perceive(self, intent: Any) -> dict:
        obs = await super().perceive(intent)
        query = obs.get("params", {}).get("query", "")
        if query and self._runtime:
            encoded = urllib.parse.quote_plus(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded}"
            body = await _mesh_fetch(self._runtime, url)
            if body:
                obs["fetched_content"] = body[:8000]
        return obs

    async def act(self, decision: dict) -> dict:
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}
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
