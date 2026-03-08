"""ResearchPhase — researches documentation before agent/skill design."""

from __future__ import annotations

import json
import logging
import urllib.parse
from typing import Any, TYPE_CHECKING

from probos.types import LLMRequest

if TYPE_CHECKING:
    from probos.cognitive.llm_client import BaseLLMClient
    from probos.config import SelfModConfig

logger = logging.getLogger(__name__)


RESEARCH_QUERY_PROMPT = """You are helping ProbOS design a new agent capability.

INTENT TO BUILD:
  Name: {intent_name}
  Description: {intent_description}
  Parameters: {parameters}

What documentation or reference material would help build this?
Generate 2-3 search queries that would find relevant Python library docs,
API references, or code examples.

Respond with ONLY a JSON array of search queries:
["query 1", "query 2", "query 3"]
"""

RESEARCH_SYNTHESIS_PROMPT = """You are preparing reference material for an agent designer.

INTENT TO BUILD:
  Name: {intent_name}
  Description: {intent_description}

DOCUMENTATION FETCHED:
{fetched_content}

Extract the key information needed to implement this intent:
1. Required Python libraries (must be in this whitelist: {allowed_imports})
2. API patterns or function signatures
3. Common pitfalls or error handling patterns
4. Example code snippets (adapted to use only whitelisted imports)

Respond with a concise reference section (max 500 words).
If the fetched content is not useful, say "No useful documentation found."
"""


class ResearchPhase:
    """Researches documentation before agent/skill design.

    Flow:
    1. Ask LLM to generate 2-3 search queries for the intent
    2. Convert queries to documentation site URLs via urllib.parse
    3. Fetch each URL via the mesh (submit_intent for http_fetch)
    4. Truncate fetched content to configured max chars per page
    5. Ask LLM to synthesize relevant information
    6. Return synthesis as additional context for the design prompt

    Security constraints:
    - Only fetches via the mesh (uses existing HttpFetchAgent + consensus)
    - Fetched content is truncated before LLM processing
    - Research output is context for code generation, never executed directly
    - All generated code still goes through CodeValidator + SandboxRunner
    - URL construction uses urllib.parse (no raw string concatenation)
    """

    _DOMAIN_SEARCH_PATHS: dict[str, str] = {
        "docs.python.org": "https://docs.python.org/3/search.html",
        "pypi.org": "https://pypi.org/search/",
        "developer.mozilla.org": "https://developer.mozilla.org/en-US/search",
        "learn.microsoft.com": "https://learn.microsoft.com/en-us/search/",
    }

    def __init__(
        self,
        llm_client: BaseLLMClient,
        submit_intent_fn: Any,  # async callable to submit http_fetch intents
        config: SelfModConfig,
    ) -> None:
        self._llm = llm_client
        self._submit_intent = submit_intent_fn
        self._config = config

    async def research(
        self,
        intent_name: str,
        intent_description: str,
        parameters: dict[str, str],
    ) -> str:
        """Research documentation for an intent.

        Returns a synthesized reference section string.
        Returns "No research available." on any failure.
        Never raises — all errors are caught and logged.
        """
        try:
            # 1. Generate search queries
            queries = await self._generate_queries(
                intent_name, intent_description, parameters,
            )
            if not queries:
                return "No research available."

            # 2. Convert to URLs
            urls = self._queries_to_urls(queries)
            if not urls:
                return "No research available."

            # 3. Fetch pages
            fetched = await self._fetch_pages(urls)
            successful = [f for f in fetched if f["success"]]
            if not successful:
                return "No research available."

            # 4. Synthesize
            synthesis = await self._synthesize(
                intent_name, intent_description, successful,
            )
            return synthesis

        except Exception as e:
            logger.warning("Research failed for %s: %s", intent_name, e)
            return "No research available."

    async def _generate_queries(
        self,
        intent_name: str,
        intent_description: str,
        parameters: dict[str, str],
    ) -> list[str]:
        """Ask LLM to generate search queries. Returns list of query strings."""
        prompt = RESEARCH_QUERY_PROMPT.format(
            intent_name=intent_name,
            intent_description=intent_description,
            parameters=parameters,
        )

        request = LLMRequest(prompt=prompt, tier="fast")
        response = await self._llm.complete(request)

        if not response.content or response.error:
            return []

        try:
            queries = json.loads(response.content)
            if isinstance(queries, list):
                return [str(q) for q in queries[:3]]
        except (json.JSONDecodeError, TypeError):
            pass

        return []

    def _queries_to_urls(self, queries: list[str]) -> list[str]:
        """Convert search queries to fetchable documentation URLs.

        For each query, constructs a search URL for each whitelisted domain
        using _DOMAIN_SEARCH_PATHS and urllib.parse.urlencode().

        Total URLs capped at config.research_max_pages.
        """
        if not queries:
            return []

        whitelist = set(self._config.research_domain_whitelist)
        urls: list[str] = []

        for query in queries:
            for domain, base_url in self._DOMAIN_SEARCH_PATHS.items():
                if domain not in whitelist:
                    continue
                # Build URL using urllib.parse — never raw string concat
                params = urllib.parse.urlencode({"q": query})
                sep = "&" if "?" in base_url else "?"
                url = f"{base_url}{sep}{params}"
                urls.append(url)

                if len(urls) >= self._config.research_max_pages:
                    return urls

        return urls

    async def _fetch_pages(self, urls: list[str]) -> list[dict]:
        """Fetch each URL via the mesh's http_fetch intent.

        Returns list of {"url": str, "content": str, "success": bool}.
        Each page content is truncated to config.research_max_content_per_page chars.
        Failed fetches are included with success=False.
        """
        results = []
        max_content = self._config.research_max_content_per_page

        for url in urls:
            try:
                fetch_results = await self._submit_intent(
                    "http_fetch",
                    params={"url": url, "method": "GET"},
                )
                # Extract content from results
                content = ""
                if fetch_results:
                    for r in fetch_results:
                        if r.success and r.result:
                            if isinstance(r.result, dict):
                                content = str(r.result.get("body", r.result.get("content", "")))
                            else:
                                content = str(r.result)
                            break

                # Truncate
                if len(content) > max_content:
                    content = content[:max_content]

                results.append({
                    "url": url,
                    "content": content,
                    "success": bool(content),
                })
            except Exception as e:
                logger.warning("Research fetch failed for %s: %s", url, e)
                results.append({
                    "url": url,
                    "content": "",
                    "success": False,
                })

        return results

    async def _synthesize(
        self,
        intent_name: str,
        intent_description: str,
        fetched: list[dict],
    ) -> str:
        """Ask LLM to synthesize relevant information from fetched docs.

        Returns a concise reference section string.
        """
        # Build fetched content section
        content_parts = []
        for f in fetched:
            if f["content"]:
                content_parts.append(f"--- {f['url']} ---\n{f['content']}")

        fetched_content = "\n\n".join(content_parts) or "No content available."

        prompt = RESEARCH_SYNTHESIS_PROMPT.format(
            intent_name=intent_name,
            intent_description=intent_description,
            fetched_content=fetched_content,
            allowed_imports=", ".join(self._config.allowed_imports),
        )

        request = LLMRequest(prompt=prompt, tier="fast")
        response = await self._llm.complete(request)

        if not response.content or response.error:
            return "No useful documentation found."

        return response.content
