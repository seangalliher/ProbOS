"""LLM client abstraction with tiered routing and fallback chain."""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx

from probos.types import LLMRequest, LLMResponse

logger = logging.getLogger(__name__)


class BaseLLMClient(ABC):
    """Abstract LLM client interface."""

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Send a completion request and return the response."""

    async def close(self) -> None:
        """Clean up resources."""


class OpenAICompatibleClient(BaseLLMClient):
    """Multi-endpoint OpenAI-compatible LLM client with per-tier routing.

    Each tier (fast/standard/deep) can have its own:
    - base_url (different server)
    - api_key (different auth)
    - model (different model name)
    - timeout (different latency budget)
    - httpx.AsyncClient (separate connection pool)

    When per-tier config is not specified, falls back to shared values.
    Tiers sharing the same base_url share the same httpx.AsyncClient
    (no duplicate connection pools for the same server).
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080/v1",
        api_key: str = "",
        models: dict[str, str] | None = None,
        timeout: float = 30.0,
        default_tier: str = "standard",
        config: Any = None,  # CognitiveConfig — optional, overrides all above
    ) -> None:
        from probos.config import CognitiveConfig

        if config is not None and isinstance(config, CognitiveConfig):
            self._config = config
        else:
            # Build a CognitiveConfig from legacy keyword args
            models = models or {
                "fast": "gpt-4o-mini",
                "standard": "claude-sonnet-4-6",
                "deep": "claude-opus-4-0-20250115",
            }
            self._config = CognitiveConfig(
                llm_base_url=base_url,
                llm_api_key=api_key,
                llm_model_fast=models.get("fast", "gpt-4o-mini"),
                llm_model_standard=models.get("standard", "claude-sonnet-4"),
                llm_model_deep=models.get("deep", "claude-sonnet-4"),
                llm_timeout_seconds=timeout,
            )

        self.default_tier = self._config.default_llm_tier if hasattr(self._config, 'default_llm_tier') else default_tier

        # Resolve per-tier configs
        self._tier_configs: dict[str, dict] = {}
        for tier in ("fast", "standard", "deep"):
            self._tier_configs[tier] = self._config.tier_config(tier)

        # Create httpx clients, deduplicated by (base_url, api_key)
        self._clients: dict[str, httpx.AsyncClient] = {}  # base_url → client
        self._tier_status: dict[str, bool] = {}
        for tier in ("fast", "standard", "deep"):
            tc = self._tier_configs[tier]
            url = tc["base_url"]
            # Ensure trailing slash so httpx relative-path resolution
            # keeps the base path (e.g. /v1/) instead of replacing it.
            normalized = url.rstrip("/") + "/"
            if url not in self._clients:
                headers = {"Content-Type": "application/json"}
                if tc["api_key"]:
                    headers["Authorization"] = f"Bearer {tc['api_key']}"
                self._clients[url] = httpx.AsyncClient(
                    base_url=normalized,
                    headers=headers,
                    timeout=tc["timeout"],
                )

        # Simple response cache keyed by (tier, prompt_hash)
        self._cache: dict[str, LLMResponse] = {}

    # Backward-compat properties
    @property
    def base_url(self) -> str:
        return self._config.llm_base_url

    @property
    def api_key(self) -> str:
        return self._config.llm_api_key

    @property
    def timeout(self) -> float:
        return self._config.llm_timeout_seconds

    @property
    def models(self) -> dict[str, str]:
        return {
            tier: self._tier_configs[tier]["model"]
            for tier in ("fast", "standard", "deep")
        }

    def _cache_key(self, tier: str, prompt: str) -> str:
        return f"{tier}:{hash(prompt)}"

    async def check_connectivity(self) -> dict[str, bool]:
        """Check connectivity for each tier independently.

        Returns {"fast": True/False, "standard": True/False, "deep": True/False}.
        Tiers sharing the same endpoint share the result (no duplicate checks).
        """
        results: dict[str, bool] = {}
        checked_urls: dict[str, bool] = {}

        for tier in ("fast", "standard", "deep"):
            tc = self._tier_configs[tier]
            url = tc["base_url"]
            if url in checked_urls:
                results[tier] = checked_urls[url]
            else:
                reachable = await self._check_endpoint(tier)
                checked_urls[url] = reachable
                results[tier] = reachable
            self._tier_status[tier] = results[tier]

        return results

    async def _check_endpoint(self, tier: str) -> bool:
        """Check if a tier's endpoint is reachable.

        Sends a minimal completion request with a short timeout.
        Any response below HTTP 500 means the server is up.
        """
        tc = self._tier_configs[tier]
        client = self._clients[tc["base_url"]]
        try:
            resp = await client.post(
                "chat/completions",
                json={
                    "model": tc["model"],
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                },
                timeout=5.0,
            )
            return resp.status_code < 500
        except (httpx.ConnectError, httpx.TimeoutException, OSError):
            return False

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Send a completion request with fallback chain.

        Routes to the appropriate tier's endpoint and client.
        Fallback order: live endpoint → cached response → error response.
        """
        tier = request.tier or self.default_tier
        tc = self._tier_configs.get(tier, self._tier_configs["standard"])
        client = self._clients[tc["base_url"]]
        model = tc["model"]
        cache_key = self._cache_key(tier, request.prompt)

        # Try live endpoint
        try:
            response = await self._call_api(request, model, client)
            # Cache successful responses
            self._cache[cache_key] = response
            return response
        except httpx.ConnectError:
            logger.warning("LLM endpoint unreachable at %s", tc["base_url"])
        except httpx.TimeoutException:
            logger.warning(
                "LLM request timed out after %.0fs (model=%s)",
                tc["timeout"], model,
            )
        except httpx.HTTPStatusError as e:
            logger.warning(
                "LLM endpoint returned HTTP %d: %s",
                e.response.status_code,
                e.response.text[:200],
            )
        except Exception as e:
            logger.warning("LLM live call failed: %s: %s", type(e).__name__, e)

        # Try cache
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            logger.debug("Using cached LLM response for request %s", request.id[:8])
            return LLMResponse(
                content=cached.content,
                model=cached.model,
                tier=tier,
                tokens_used=cached.tokens_used,
                cached=True,
                request_id=request.id,
            )

        # Final fallback: error response
        logger.error("LLM unavailable and no cached response for request %s", request.id[:8])
        return LLMResponse(
            content="",
            model=model,
            tier=tier,
            error=f"LLM endpoint at {tc['base_url']} is unavailable and no cached response exists",
            request_id=request.id,
        )

    async def _call_api(self, request: LLMRequest, model: str, client: httpx.AsyncClient) -> LLMResponse:
        """Make the actual API call."""
        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }

        logger.debug("LLM request payload: %s", json.dumps(payload, indent=2))
        logger.debug("LLM request headers: %s", dict(client.headers))

        resp = await client.post("chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()

        logger.debug("Raw HTTP response body: %s", data)

        content = data["choices"][0]["message"]["content"]
        tokens_used = data.get("usage", {}).get("total_tokens", 0)

        return LLMResponse(
            content=content,
            model=model,
            tier=request.tier or self.default_tier,
            tokens_used=tokens_used,
            cached=False,
            request_id=request.id,
        )

    def tier_info(self) -> dict[str, dict]:
        """Return per-tier config for /model display.

        Returns {"fast": {"base_url": ..., "model": ..., "reachable": ...}, ...}
        """
        info = {}
        for tier in ("fast", "standard", "deep"):
            tc = self._tier_configs[tier]
            info[tier] = {
                "base_url": tc["base_url"],
                "model": tc["model"],
                "timeout": tc["timeout"],
                "reachable": self._tier_status.get(tier),
            }
        return info

    async def close(self) -> None:
        """Close all httpx clients."""
        for client in self._clients.values():
            await client.aclose()


class MockLLMClient(BaseLLMClient):
    """Deterministic mock LLM client for testing.

    Returns canned responses based on input pattern matching.
    Patterns are checked in order; first match wins.
    """

    def __init__(self) -> None:
        self._patterns: list[tuple[str, str]] = []
        self._call_log: list[LLMRequest] = []
        self._default_response: str = '{"intents": []}'
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register default pattern → response mappings.

        Order matters — first match wins. New expansion patterns
        are registered before read/write to avoid false matches
        (e.g., "what files are in /tmp" matching read_file).
        """

        # --- Expansion agent patterns (registered first) ---

        # --- Introspection patterns (before expansion to catch NL queries) ---

        # explain_last
        self.add_pattern(
            r"what (?:just )?happened|explain.*(last|previous)|what did you (?:just )?do",
            self._make_explain_last_response,
        )

        # system_health
        self.add_pattern(
            r"how healthy|system (?:health|status)|are you ok",
            self._make_system_health_response,
        )

        # agent_info
        self.add_pattern(
            r"tell me about (.+) agents?|info.*(agent|file_reader|file_writer)",
            self._make_agent_info_response,
        )

        # why
        self.add_pattern(
            r"why did you|why.*(choose|pick|use|select)",
            self._make_why_response,
        )

        # HTTP fetch — must be before read_file (both can match URLs)
        self.add_pattern(
            r"fetch\s+(https?://[\w./\-:?&=%]+)",
            self._make_http_fetch_response,
        )

        # Run shell command
        self.add_pattern(
            r"run\s+(?:the\s+)?(?:command|cmd)\s+(.+)",
            self._make_run_command_response,
        )

        # Search files — must be before list_directory (both use paths)
        self.add_pattern(
            r"(?:find|search)\s+.*?files?\s+.*?((?:/|[A-Za-z]:\\)[\w./\\\-]+)",
            self._make_search_files_response,
        )

        # List directory — must be before read_file
        self.add_pattern(
            r"(?:list|what\s+files|files\s+in|what(?:'s|\s+is)\s+in)\s+.*?((?:/|[A-Za-z]:\\)[\w./\\\-]+)",
            self._make_list_directory_response,
        )

        # --- Original patterns ---

        # Single read_file intent
        self.add_pattern(
            r"read.*file.*((?:/|[A-Za-z]:\\)[\w./\\]+)",
            self._make_read_response,
        )

        # Multiple file reads (parallel)
        self.add_pattern(
            r"read.*(?:/|[A-Za-z]:\\)[\w./\\]+.*and.*(?:/|[A-Za-z]:\\)[\w./\\]+",
            self._make_parallel_read_response,
        )

        # Write file intent
        self.add_pattern(
            r"write.*(?:to|into)\s+((?:/|[A-Za-z]:\\)[\w./\\]+)",
            self._make_write_response,
        )

    def add_pattern(self, pattern: str, handler: Any) -> None:
        """Register a regex pattern with a handler (string or callable)."""
        self._patterns.append((pattern, handler))

    def set_default_response(self, response: str) -> None:
        """Set the response for unmatched inputs."""
        self._default_response = response

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Match input against patterns and return canned response."""
        self._call_log.append(request)

        # Detect escalation arbitration requests
        if (
            request.system_prompt
            and "escalation arbiter" in request.system_prompt
        ):
            content = json.dumps({
                "action": "reject",
                "reason": "MockLLMClient cannot arbitrate — escalating to user",
            })
            return LLMResponse(
                content=content,
                model="mock",
                tier=request.tier,
                tokens_used=len(content) // 4,
                cached=False,
                request_id=request.id,
            )

        # Detect reflection requests (uses REFLECT_PROMPT as system prompt)
        if (
            request.system_prompt
            and "analyzing results returned by ProbOS agents" in request.system_prompt
        ):
            content = self._make_reflect_response(request.prompt)
            return LLMResponse(
                content=content,
                model="mock",
                tier=request.tier,
                tokens_used=len(content) // 4,
                cached=False,
                request_id=request.id,
            )

        # Detect agent design requests (AGENT_DESIGN_PROMPT signature)
        if "UNHANDLED INTENT:" in request.prompt and "Subclass BaseAgent" in request.prompt:
            content = self._make_agent_design_response(request.prompt)
            return LLMResponse(
                content=content,
                model="mock",
                tier=request.tier,
                tokens_used=len(content) // 4,
                cached=False,
                request_id=request.id,
            )

        # Detect skill design requests (SKILL_DESIGN_PROMPT signature)
        if "SKILL TO CREATE:" in request.prompt and "handle_" in request.prompt:
            content = self._make_skill_design_response(request.prompt)
            return LLMResponse(
                content=content,
                model="mock",
                tier=request.tier,
                tokens_used=len(content) // 4,
                cached=False,
                request_id=request.id,
            )

        # Detect research query generation requests
        if "INTENT TO BUILD:" in request.prompt and "search queries" in request.prompt:
            content = json.dumps(["python library docs", "API reference example"])
            return LLMResponse(
                content=content,
                model="mock",
                tier=request.tier,
                tokens_used=len(content) // 4,
                cached=False,
                request_id=request.id,
            )

        # Detect research synthesis requests
        if "DOCUMENTATION FETCHED:" in request.prompt and "reference section" in request.prompt:
            content = "Reference: Use the json module for parsing. Example: json.loads(data)."
            return LLMResponse(
                content=content,
                model="mock",
                tier=request.tier,
                tokens_used=len(content) // 4,
                cached=False,
                request_id=request.id,
            )

        # Detect intent extraction requests
        if "no existing agent can handle it" in request.prompt and "intent_name_snake_case" in request.prompt:
            content = self._make_intent_extraction_response(request.prompt)
            return LLMResponse(
                content=content,
                model="mock",
                tier=request.tier,
                tokens_used=len(content) // 4,
                cached=False,
                request_id=request.id,
            )

        prompt = request.prompt.lower()

        for pattern, handler in self._patterns:
            match = re.search(pattern, prompt, re.IGNORECASE)
            if match:
                if callable(handler):
                    content = handler(prompt, match)
                else:
                    content = handler
                return LLMResponse(
                    content=content,
                    model="mock",
                    tier=request.tier,
                    tokens_used=len(content) // 4,
                    cached=False,
                    request_id=request.id,
                )

        return LLMResponse(
            content=self._default_response,
            model="mock",
            tier=request.tier,
            tokens_used=len(self._default_response) // 4,
            cached=False,
            request_id=request.id,
        )

    @property
    def call_count(self) -> int:
        return len(self._call_log)

    @property
    def last_request(self) -> LLMRequest | None:
        return self._call_log[-1] if self._call_log else None

    # Regex for extracting file paths (Unix and Windows)
    _PATH_WITH_EXT = re.compile(r'((?:/|[A-Za-z]:\\)[\w./\\\-]+\.[\w]+)')
    _PATH_ANY = re.compile(r'((?:/|[A-Za-z]:\\)[\w./\\\-]+)')

    def _extract_paths(self, text: str) -> list[str]:
        """Extract file paths from text, supporting both Unix and Windows."""
        paths = self._PATH_WITH_EXT.findall(text)
        if not paths:
            paths = self._PATH_ANY.findall(text)
        return paths

    def _make_read_response(self, prompt: str, match: re.Match) -> str:
        """Generate a read_file intent response."""
        paths = self._extract_paths(prompt)

        if len(paths) == 1:
            return json.dumps({
                "intents": [
                    {
                        "id": "t1",
                        "intent": "read_file",
                        "params": {"path": paths[0]},
                        "depends_on": [],
                        "use_consensus": False,
                    }
                ]
            })

        # Multiple paths — parallel reads
        intents = []
        for i, path in enumerate(paths):
            intents.append({
                "id": f"t{i + 1}",
                "intent": "read_file",
                "params": {"path": path},
                "depends_on": [],
                "use_consensus": False,
            })
        return json.dumps({"intents": intents})

    def _make_parallel_read_response(self, prompt: str, match: re.Match) -> str:
        """Generate parallel read_file intents."""
        paths = self._extract_paths(prompt)

        intents = []
        for i, path in enumerate(paths):
            intents.append({
                "id": f"t{i + 1}",
                "intent": "read_file",
                "params": {"path": path},
                "depends_on": [],
                "use_consensus": False,
            })
        return json.dumps({"intents": intents})

    def _make_write_response(self, prompt: str, match: re.Match) -> str:
        """Generate a write_file intent response."""
        paths = self._extract_paths(prompt)
        path = paths[0] if paths else "/tmp/output.txt"

        # Try to extract content — look for quoted strings or "write X to"
        content_match = re.search(
            r'write\s+["\']?(.+?)["\']?\s+(?:to|into)\s+(?:/|[A-Za-z]:\\)',
            prompt,
            re.IGNORECASE,
        )
        content = content_match.group(1).strip().strip("'\"") if content_match else "content"

        return json.dumps({
            "intents": [
                {
                    "id": "t1",
                    "intent": "write_file",
                    "params": {"path": path, "content": content},
                    "depends_on": [],
                    "use_consensus": True,
                }
            ]
        })

    def _make_list_directory_response(self, prompt: str, match: re.Match) -> str:
        """Generate a list_directory intent response."""
        paths = self._extract_paths(prompt)
        path = paths[0] if paths else match.group(1)
        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "list_directory",
                "params": {"path": path},
                "depends_on": [],
                "use_consensus": False,
            }]
        })

    def _make_search_files_response(self, prompt: str, match: re.Match) -> str:
        """Generate a search_files intent response."""
        # Extract glob pattern from the prompt
        pattern_match = re.search(r'(?:named|matching|called)\s+(\S+)', prompt, re.IGNORECASE)
        if pattern_match:
            pattern = pattern_match.group(1)
        else:
            # Fallback: look for *.ext patterns
            glob_match = re.search(r'(\*[\w.*]+)', prompt)
            pattern = glob_match.group(1) if glob_match else "*"

        paths = self._extract_paths(prompt)
        path = paths[-1] if paths else match.group(1)

        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "search_files",
                "params": {"path": path, "pattern": pattern},
                "depends_on": [],
                "use_consensus": False,
            }]
        })

    def _make_run_command_response(self, prompt: str, match: re.Match) -> str:
        """Generate a run_command intent response."""
        command = match.group(1).strip().strip("'\"")
        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "run_command",
                "params": {"command": command},
                "depends_on": [],
                "use_consensus": True,
            }]
        })

    def _make_http_fetch_response(self, prompt: str, match: re.Match) -> str:
        """Generate an http_fetch intent response."""
        url = match.group(1)
        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "http_fetch",
                "params": {"url": url, "method": "GET"},
                "depends_on": [],
                "use_consensus": True,
            }]
        })

    def _make_reflect_response(self, prompt: str) -> str:
        """Generate a canned reflection synthesis from agent results."""
        return "Based on the agent results: The operation completed successfully."

    def _make_explain_last_response(self, prompt: str, match: re.Match) -> str:
        """Generate an explain_last intent response."""
        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "explain_last",
                "params": {},
                "depends_on": [],
                "use_consensus": False,
            }],
            "reflect": True,
        })

    def _make_system_health_response(self, prompt: str, match: re.Match) -> str:
        """Generate a system_health intent response."""
        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "system_health",
                "params": {},
                "depends_on": [],
                "use_consensus": False,
            }],
            "reflect": True,
        })

    def _make_agent_info_response(self, prompt: str, match: re.Match) -> str:
        """Generate an agent_info intent response."""
        # Try to extract agent type from the prompt
        type_match = re.search(r"about\s+(\w+)\s+agents?", prompt, re.IGNORECASE)
        agent_type = type_match.group(1) if type_match else "file_reader"
        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "agent_info",
                "params": {"agent_type": agent_type},
                "depends_on": [],
                "use_consensus": False,
            }],
            "reflect": True,
        })

    def _make_why_response(self, prompt: str, match: re.Match) -> str:
        """Generate a why intent response."""
        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "why",
                "params": {"question": prompt},
                "depends_on": [],
                "use_consensus": False,
            }],
            "reflect": True,
        })

    def _make_agent_design_response(self, prompt: str) -> str:
        """Generate a valid agent source code for an agent design request.

        Parses the intent name from the prompt and returns minimal valid
        agent Python source code.
        """
        # Extract intent name from the prompt
        name_match = re.search(r'Name:\s*(\w+)', prompt)
        intent_name = name_match.group(1) if name_match else "count_words"

        # Build class name
        parts = intent_name.split("_")
        class_name = "".join(p.capitalize() for p in parts) + "Agent"

        return (
            'from probos.substrate.agent import BaseAgent\n'
            'from probos.types import IntentMessage, IntentResult, IntentDescriptor\n'
            '\n'
            f'class {class_name}(BaseAgent):\n'
            f'    """Auto-generated agent for {intent_name}."""\n'
            '\n'
            f'    agent_type = "{intent_name}"\n'
            f'    _handled_intents = ["{intent_name}"]\n'
            '    intent_descriptors = [\n'
            '        IntentDescriptor(\n'
            f'            name="{intent_name}",\n'
            '            params={"text": "input text"},\n'
            f'            description="Handle {intent_name} intent",\n'
            '            requires_consensus=False,\n'
            '            requires_reflect=False,\n'
            '        )\n'
            '    ]\n'
            '\n'
            '    def __init__(self, **kwargs):\n'
            '        super().__init__(**kwargs)\n'
            '        self._llm_client = kwargs.get("llm_client")\n'
            '\n'
            '    async def perceive(self, intent):\n'
            '        intent_name = intent.get("intent", "")\n'
            '        if intent_name not in self._handled_intents:\n'
            '            return None\n'
            '        return {"intent": intent_name, "params": intent.get("params", {})}\n'
            '\n'
            '    async def decide(self, observation):\n'
            '        return {"action": "process", "params": observation["params"]}\n'
            '\n'
            '    async def act(self, plan):\n'
            '        text = plan.get("params", {}).get("text", "")\n'
            '        count = len(text.split())\n'
            '        return {"success": True, "data": {"result": count}}\n'
            '\n'
            '    async def report(self, result):\n'
            '        return result\n'
            '\n'
            '    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:\n'
            '        if intent.intent not in self._handled_intents:\n'
            '            return None\n'
            '        observation = await self.perceive(intent.__dict__)\n'
            '        if observation is None:\n'
            '            return None\n'
            '        plan = await self.decide(observation)\n'
            '        result = await self.act(plan)\n'
            '        report = await self.report(result)\n'
            '        success = report.get("success", False)\n'
            '        self.update_confidence(success)\n'
            '        return IntentResult(\n'
            '            intent_id=intent.id,\n'
            '            agent_id=self.id,\n'
            '            success=success,\n'
            '            result=report.get("data"),\n'
            '            error=report.get("error"),\n'
            '            confidence=self.confidence,\n'
            '        )\n'
        )

    def _make_skill_design_response(self, prompt: str) -> str:
        """Generate a valid skill handler function for a skill design request.

        Parses the intent name from the prompt and returns minimal valid
        skill handler Python source code.
        """
        # Extract intent name from the prompt
        name_match = re.search(r'Name:\s*(\w+)', prompt)
        intent_name = name_match.group(1) if name_match else "custom_task"

        return (
            'from probos.types import IntentMessage, IntentResult, LLMRequest\n'
            '\n'
            f'async def handle_{intent_name}(intent: IntentMessage, llm_client=None) -> IntentResult:\n'
            f'    """Handle {intent_name} intent."""\n'
            '    params = intent.params\n'
            '    text = params.get("text", "")\n'
            '    result_data = {"result": f"Processed: {text}"}\n'
            '    if llm_client:\n'
            '        request = LLMRequest(prompt=f"Process: {text}", tier="fast")\n'
            '        response = await llm_client.complete(request)\n'
            '        result_data = {"result": response.content}\n'
            '    return IntentResult(\n'
            '        intent_id=intent.id,\n'
            '        agent_id="skill",\n'
            '        success=True,\n'
            '        result=result_data,\n'
            '    )\n'
        )

    def _make_intent_extraction_response(self, prompt: str) -> str:
        """Generate a valid JSON intent extraction response.

        Parses the user request text from the prompt and returns
        a synthetic intent name.
        """
        # Extract user request text
        req_match = re.search(r'User request:\s*"(.+?)"', prompt)
        user_text = req_match.group(1) if req_match else "count words"

        # Derive a simple intent name from the user text
        words = re.findall(r'[a-z]+', user_text.lower())
        intent_name = "_".join(words[:3]) if words else "custom_task"

        return json.dumps({
            "name": intent_name,
            "description": f"Handle the request: {user_text}",
            "parameters": {"text": "input text"},
            "actual_values": {"text": user_text},
            "requires_consensus": False,
        })
