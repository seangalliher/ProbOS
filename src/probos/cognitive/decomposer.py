"""Intent decomposition engine — NL to task DAG with execution."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any, TYPE_CHECKING

from probos.cognitive.llm_client import BaseLLMClient
from probos.cognitive.prompt_builder import PromptBuilder, get_platform_context
from probos.cognitive.working_memory import WorkingMemoryManager, WorkingMemorySnapshot
from probos.types import ConsensusOutcome, IntentDescriptor, LLMRequest, TaskDAG, TaskNode, Episode, AttentionEntry

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Patterns that indicate a capability gap (the LLM is saying "I can't do X")
# rather than a genuine conversational reply ("Hello!").
# Note: [''] matches both ASCII and Unicode curly apostrophes.
_CAPABILITY_GAP_RE = re.compile(
    r"don['\u2019]?t have|(?:can['\u2019]?t|cannot|unable to|no (?:built-in |native )?(?:"
    r"capability|ability|support|way|mechanism|tool))|not (?:available|"
    r"supported|possible)|lack(?:s|ing)?|doesn['\u2019]?t (?:have|support)|"
    r"beyond (?:my|current) (?:capabilities|abilities)|outside (?:my|the) "
    r"(?:scope|capabilities)",
    re.IGNORECASE,
)


def is_capability_gap(response: str) -> bool:
    """Return True if a dag.response indicates a capability gap.

    A capability-gap response means the LLM couldn't map the request to
    any existing intent and is explaining the limitation.  These should
    still trigger self-mod so ProbOS can learn the missing capability.
    Conversational responses ("Hello!", "Here's what I can do") should not.
    """
    return bool(_CAPABILITY_GAP_RE.search(response))

# Deprecated — kept for backward compatibility when no descriptors are provided.
_LEGACY_SYSTEM_PROMPT = """\
You MUST respond with ONLY a JSON object. No preamble, no explanation, no \
markdown code fences, no text before or after the JSON. Your entire response \
must be parseable as a single JSON object.

You are the intent decomposition engine of ProbOS, a probabilistic agent-native \
operating system runtime. You translate user requests into structured intents.

## Available intents

| Intent       | Params                                       | Description                    |
|--------------|----------------------------------------------|--------------------------------|
| read_file       | {"path": "<absolute_path>"}                      | Read a file and return content    |
| stat_file       | {"path": "<absolute_path>"}                      | Get file size, mtime, etc.        |
| write_file      | {"path": "<absolute_path>", "content": "…"}      | Write content to a file           |
| list_directory  | {"path": "<absolute_path>"}                      | List files and directories        |
| search_files    | {"path": "<absolute_path>", "pattern": "<glob>"} | Search for files matching pattern |
| run_command     | {"command": "<shell_command>"}                   | Run a shell command (general-purpose) |
| http_fetch      | {"url": "<url>", "method": "GET"}                | Fetch a URL                       |
| explain_last    | {}                                                | Explain what happened in the last request  |
| agent_info      | {"agent_type": "...", "agent_id": "..."}         | Get info about a specific agent            |
| system_health   | {}                                                | Get system health assessment               |
| why             | {"question": "..."}                               | Explain why ProbOS did something           |

## Response format

Your response MUST be exactly one JSON object with this structure:

{"intents": [...], "response": "optional text", "reflect": false, "capability_gap": false}

- "intents": array of intent objects (empty array if no actionable intents)
- "response": optional string — a brief message for the user. Use this for \
conversational replies, confirmations, or when no intents apply.
- "reflect": boolean — set to true when the user asks for analysis, \
interpretation, comparison, summary, or opinion about the results. Set to \
false for simple data retrieval or command execution.
- "capability_gap": boolean — set to true when the request is a task that \
no available intent can handle (translation, creative writing, etc.). \
Set to false for conversational replies and for tasks that map to an intent.

Each intent object:

{"id": "t1", "intent": "<name>", "params": {...}, "depends_on": [], "use_consensus": false}

## Rules

1. RESPOND ONLY WITH JSON. No natural language outside the JSON object. \
No markdown. No code fences. No commentary. Just the raw JSON object.
2. Use sequential IDs: t1, t2, t3, …
3. Independent intents have "depends_on": [] and execute in parallel.
4. If intent B needs the result of intent A, set "depends_on": ["t1"].
5. All write_file intents MUST have "use_consensus": true.
6. All run_command intents MUST have "use_consensus": true.
7. read_file, stat_file and http_fetch intents should have "use_consensus": false.
8. list_directory and search_files should have "use_consensus": false.
9. Paths must be absolute. Use the path exactly as the user provides it.
10. If the request is conversational (greeting, help, small talk), respond with \
{"intents": [], "response": "a helpful reply"}. \
If the request is a task (translation, analysis, creative writing, etc.) that \
cannot be mapped to any available intent, respond with \
{"intents": [], "response": "I don't have an intent for <task type> yet."}.
11. Never invent intents not in the table above.
12a. ONLY use run_command when a real program or OS utility genuinely \
computes the answer (e.g. date/time, math, system info, pip install). \
NEVER use run_command to output hardcoded text you already know \
(echo, Write-Host, Write-Output, printf, print, etc.).
12b. For tasks requiring external tools or computation — translation, creative \
writing, summarization, code generation, web search — if a matching intent exists \
in the table above, use it. If NO matching intent exists, return \
{"intents": [], "response": "I don't have an intent for <task type> yet."}. \
General knowledge questions (who/what/explain) are conversational — answer directly. \
Conversational replies (greetings, help, small talk, factual questions) are fine as direct responses.
13. Set "reflect" to true when the user asks for analysis, interpretation, \
comparison, summary, or opinion about results. Also set "reflect" to true for \
any intent that transforms, translates, generates, or produces content the user \
wants to see explained in natural language. Set to false only for simple data \
retrieval or command execution where the raw result is self-explanatory.
14. explain_last, agent_info, system_health, why intents should have \
"use_consensus": false.
15. NEVER fabricate API keys, tokens, credentials, or authentication parameters \
in URLs. If a service requires an API key the user has not provided, respond with \
{"intents": [], "response": "That service requires an API key I don't have configured."}. \
For http_fetch, only use URLs that work without authentication.

## Examples

User: "read the file at /tmp/test.txt"
{"intents": [{"id": "t1", "intent": "read_file", "params": {"path": "/tmp/test.txt"}, "depends_on": [], "use_consensus": false}], "reflect": false}

User: "read /tmp/a.txt and /tmp/b.txt"
{"intents": [{"id": "t1", "intent": "read_file", "params": {"path": "/tmp/a.txt"}, "depends_on": [], "use_consensus": false}, {"id": "t2", "intent": "read_file", "params": {"path": "/tmp/b.txt"}, "depends_on": [], "use_consensus": false}], "reflect": false}

User: "write hello to /tmp/out.txt"
{"intents": [{"id": "t1", "intent": "write_file", "params": {"path": "/tmp/out.txt", "content": "hello"}, "depends_on": [], "use_consensus": true}], "reflect": false}

User: "hello"
{"intents": [], "response": "Hello! I'm ProbOS \u2014 a probabilistic agent-native OS that learns and evolves. I can search the web, read and summarize pages, check weather, get news, translate text, manage your notes and todos, set reminders, run commands, and answer questions about my own state. I also build new capabilities on the fly when needed. What would you like to do?"}

User: "what can you do?"
{"intents": [], "response": "I can search the web, read and summarize pages, check weather, get news headlines, translate text, summarize content, do calculations, manage notes and todos, set reminders, read and write files, run shell commands, and answer questions about my own state. I learn from our interactions and build new capabilities when needed. Writes and commands go through consensus verification."}

User: "what is the weather in Denver?"
{"intents": [{"id": "t1", "intent": "http_fetch", "params": {"url": "https://wttr.in/Denver?format=3", "method": "GET"}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "what time is it in Tokyo?"
{"intents": [{"id": "t1", "intent": "run_command", "params": {"command": "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"}, "depends_on": [], "use_consensus": true}], "reflect": true}

User: "list the files in /tmp/mydir"
{"intents": [{"id": "t1", "intent": "list_directory", "params": {"path": "/tmp/mydir"}, "depends_on": [], "use_consensus": false}], "reflect": false}

User: "find all .txt files in /home/user/docs"
{"intents": [{"id": "t1", "intent": "search_files", "params": {"path": "/home/user/docs", "pattern": "*.txt"}, "depends_on": [], "use_consensus": false}], "reflect": false}

User: "run the command echo hello"
{"intents": [{"id": "t1", "intent": "run_command", "params": {"command": "echo hello"}, "depends_on": [], "use_consensus": true}], "reflect": false}

User: "fetch https://httpbin.org/get"
{"intents": [{"id": "t1", "intent": "http_fetch", "params": {"url": "https://httpbin.org/get", "method": "GET"}, "depends_on": [], "use_consensus": false}], "reflect": false}

User: "what is the largest file in /tmp/mydir?"
{"intents": [{"id": "t1", "intent": "list_directory", "params": {"path": "/tmp/mydir"}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "fetch https://example.com and summarize it"
{"intents": [{"id": "t1", "intent": "http_fetch", "params": {"url": "https://example.com", "method": "GET"}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "why did you use file_reader for that?"
{"intents": [{"id": "t1", "intent": "why", "params": {"question": "why did you use file_reader for that?"}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "how healthy is the system?"
{"intents": [{"id": "t1", "intent": "system_health", "params": {}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "what just happened?"
{"intents": [{"id": "t1", "intent": "explain_last", "params": {}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "tell me about file_reader agents"
{"intents": [{"id": "t1", "intent": "agent_info", "params": {"agent_type": "file_reader"}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "describe the agents" or "what agents are active?"
{"intents": [{"id": "t1", "intent": "agent_info", "params": {}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "translate 'hello world' to French"
{"intents": [], "response": "I don't have an intent for translation yet.", "capability_gap": true}

User: "write me a haiku about the ocean"
{"intents": [], "response": "I don't have an intent for creative writing yet.", "capability_gap": true}
"""

# Public alias for backward compatibility (tests import SYSTEM_PROMPT)
SYSTEM_PROMPT = _LEGACY_SYSTEM_PROMPT

REFLECT_PROMPT = """\
You are analyzing results returned by ProbOS agents in response to a user request.
You will receive the user's original request and the results from each agent operation.
Synthesize a clear, concise response that directly answers the user's question.

CRITICAL RULES:
1. If a result shows success=True and output=<data>, the operation SUCCEEDED. \
USE that output data to answer the user. NEVER say the operation failed.
2. If the output is a date/time and the user asked about a different timezone, \
calculate the conversion yourself (e.g. UTC+9 for Tokyo, UTC-7 for Denver, etc.).
3. Focus on answering what the user asked \u2014 do not describe the operations \
that were performed.
4. Each result line starts with [completed] or [failed] \u2014 trust that status.
5. Even partial or imperfect data is better than saying you couldn\u2019t retrieve it.
6. If results contain structured data (XML, JSON, HTML, CSV), extract and present \
the relevant content to answer the user's question. Do NOT describe the format or \
suggest the user access it themselves \u2014 parse the data and give the answer directly.
7. If results include a "grounded_context" field, treat it as VERIFIED SYSTEM FACTS. \
Use these facts for any claims about pools, agents, departments, capabilities, or system state. \
Never contradict grounded_context with information from your training data.

Respond with plain text only. No JSON. No markdown code fences.
"""


class IntentDecomposer:
    """Decomposes natural language into a TaskDAG via LLM.

    Takes a natural language input, assembles working memory context,
    calls the LLM, and parses the response into a structured TaskDAG.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        working_memory: WorkingMemoryManager,
        timeout: float = 15.0,
        workflow_cache: Any | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.working_memory = working_memory
        self.timeout = timeout
        self.workflow_cache = workflow_cache
        self.last_raw_response: str = ""  # Last raw LLM response for debugging
        self.last_tier: str = ""  # Tier used for last LLM call
        self.last_model: str = ""  # Model used for last LLM call
        self._pre_warm_intents: list[str] = []
        self._intent_descriptors: list[IntentDescriptor] = []
        self._prompt_builder = PromptBuilder()

    @property
    def pre_warm_intents(self) -> list[str]:
        return self._pre_warm_intents

    @pre_warm_intents.setter
    def pre_warm_intents(self, value: list[str]) -> None:
        self._pre_warm_intents = value

    def refresh_descriptors(self, descriptors: list[IntentDescriptor]) -> None:
        """Update the set of intent descriptors used for dynamic prompt assembly."""
        self._intent_descriptors = list(descriptors)

    async def decompose(
        self,
        text: str,
        context: WorkingMemorySnapshot | None = None,
        similar_episodes: list[Episode] | None = None,
        conversation_history: list[tuple[str, str]] | None = None,
        runtime_summary: str | None = None,
    ) -> TaskDAG:
        """Decompose natural language text into a TaskDAG.

        1. Check workflow cache (exact match, then fuzzy)
        2. Assemble working memory context
        3. Build LLM prompt with system state + user request
        4. Call LLM
        5. Parse response into TaskDAG
        """
        # Try workflow cache first (exact match)
        if self.workflow_cache:
            cached = self.workflow_cache.lookup(text)
            if cached:
                logger.info("Workflow cache HIT (exact): %s", text[:50])
                return cached

        # Try fuzzy match with pre-warm intents
        if self.workflow_cache and self._pre_warm_intents:
            cached = self.workflow_cache.lookup_fuzzy(text, self._pre_warm_intents)
            if cached:
                logger.info("Workflow cache HIT (fuzzy): %s", text[:50])
                return cached

        # Build prompt
        prompt_parts = []
        if context:
            prompt_parts.append(context.to_text())
            prompt_parts.append("")

        # Add similar past episodes for context
        if similar_episodes:
            prompt_parts.append("## PAST EXPERIENCE")
            for ep in similar_episodes[:3]:
                intents_used = ", ".join(
                    o.get("intent", "?") for o in ep.outcomes
                )
                successes = sum(1 for o in ep.outcomes if o.get("success"))
                total = len(ep.outcomes)
                prompt_parts.append(
                    f'- "{ep.user_input}" → {intents_used} '
                    f"({successes}/{total} succeeded)"
                )
            prompt_parts.append("")

        # Add pre-warm hints if available
        if self._pre_warm_intents:
            prompt_parts.append("## PRE-WARM HINTS")
            intent_list = ", ".join(self._pre_warm_intents)
            prompt_parts.append(
                f"Recent usage patterns suggest these intents are likely: {intent_list}"
            )
            prompt_parts.append(
                "Consider using these intents if they match the user's request."
            )
            prompt_parts.append("")

        # Add runtime grounding context (AD-317)
        if runtime_summary:
            prompt_parts.append(f"## SYSTEM CONTEXT\n{runtime_summary}")
            prompt_parts.append("")

        # Add conversation history for context resolution
        if conversation_history:
            prompt_parts.append("## CONVERSATION CONTEXT")
            prompt_parts.append("Recent messages in this conversation (most recent last):")
            for role, msg_text in conversation_history[-5:]:
                label = "User" if role == "user" else ("Context" if role == "context" else "ProbOS")
                truncated = msg_text[:200] + "..." if len(msg_text) > 200 else msg_text
                prompt_parts.append(f"{label}: {truncated}")
            prompt_parts.append("")
            prompt_parts.append(
                "Use this context to resolve references like 'it', 'that', "
                "'the same thing', 'what about X', 'do it again', etc."
            )
            prompt_parts.append("")

        prompt_parts.append(f"User request: {text}")

        # Select system prompt: dynamic if descriptors available, else legacy
        if self._intent_descriptors:
            system_prompt = self._prompt_builder.build_system_prompt(self._intent_descriptors)
        else:
            system_prompt = _LEGACY_SYSTEM_PROMPT + "\n\n" + get_platform_context()

        request = LLMRequest(
            prompt="\n".join(prompt_parts),
            system_prompt=system_prompt,
            tier="standard",  # Decomposer needs reliable JSON — don't inherit user's /tier
            temperature=0.0,
        )

        # Call LLM with retry on parse failure
        from probos.utils.json_extract import complete_with_retry

        def _validate_decomposition(content: str) -> dict:
            """Parse and validate decomposition response."""
            from probos.utils.json_extract import extract_json
            data = extract_json(content)
            if not isinstance(data, dict) or "intents" not in data:
                raise ValueError("Response missing 'intents' key")
            if not isinstance(data["intents"], list):
                raise ValueError("'intents' is not a list")
            return data

        try:
            data, response = await asyncio.wait_for(
                complete_with_retry(
                    self.llm_client,
                    request,
                    _validate_decomposition,
                    max_retries=1,
                ),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            logger.error("LLM decomposition timed out for: %s", text[:50])
            return TaskDAG(source_text=text)
        except ValueError as exc:
            logger.warning("Decomposer parse failed after retry: %s", exc)
            return TaskDAG(source_text=text)

        # Store metadata for diagnostics
        self.last_raw_response = response.content
        self.last_tier = response.tier
        self.last_model = response.model
        logger.debug("Raw LLM response: %s", response.content)

        # Build TaskDAG from validated data
        dag = self._build_dag(data, text, response)
        return dag

    # Payload budget for reflect prompt (~3000 tokens ≈ 12000 chars).
    # Bumped from 8000 to accommodate doc_snippets in AD-301.
    REFLECT_PAYLOAD_BUDGET: int = 12000

    async def reflect(
        self, original_request: str, execution_result: dict[str, Any]
    ) -> str:
        """Send agent results back to LLM for synthesis.

        Called after DAG execution when the decomposition set reflect=True.
        Returns a plain-text synthesis that directly answers the user's question.
        """
        # Serialize results into a readable format
        result_parts = [f"Original request: {original_request}", "", "Agent results:"]
        dag = execution_result.get("dag")
        results = execution_result.get("results", {})

        if dag and hasattr(dag, "nodes"):
            for node in dag.nodes:
                node_result = results.get(node.id, {})
                summary = _summarize_node_result(node_result)
                status = getattr(node, "status", "unknown")
                result_parts.append(
                    f"- [{status}] {node.intent}({node.params}): {summary}"
                )

        prompt_text = "\n".join(result_parts)

        # Cap payload to avoid oversized LLM requests
        if len(prompt_text) > self.REFLECT_PAYLOAD_BUDGET:
            prompt_text = (
                prompt_text[: self.REFLECT_PAYLOAD_BUDGET]
                + "\n\n[... results truncated ...]"
            )

        logger.debug("Reflect prompt (%d chars):\n%s", len(prompt_text), prompt_text)

        request = LLMRequest(
            prompt=prompt_text,
            system_prompt=REFLECT_PROMPT,
            tier="standard",  # Reflect needs reliable text — don't inherit user's /tier
            temperature=0.2,
        )

        try:
            response = await asyncio.wait_for(
                self.llm_client.complete(request), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            logger.warning("Reflection LLM call timed out")
            return ""

        if response.error:
            logger.warning("Reflection LLM error: %s", response.error)
            return ""

        return response.content.strip()

    def _build_dag(self, data: dict, source_text: str, response: Any = None) -> TaskDAG:
        """Build a TaskDAG from validated decomposition data.

        Expects data to already contain a valid 'intents' list.
        """
        intents = data["intents"]

        nodes = []
        for item in intents:
            if not isinstance(item, dict):
                continue
            node = TaskNode(
                id=item.get("id", f"t{len(nodes) + 1}"),
                intent=item.get("intent", ""),
                params=item.get("params", {}),
                depends_on=item.get("depends_on", []),
                use_consensus=item.get("use_consensus", False),
            )
            if node.intent:
                # Reject http_fetch URLs with fabricated credentials
                if node.intent == "http_fetch" and self._has_fake_credentials(node.params.get("url", "")):
                    logger.warning("Rejected http_fetch with fabricated credentials: %s", node.params.get("url"))
                    return TaskDAG(
                        source_text=source_text,
                        response="That service requires an API key I don't have configured.",
                    )
                nodes.append(node)

        # Extract optional conversational response
        resp_text = data.get("response", "")
        if not isinstance(resp_text, str):
            resp_text = ""

        # Extract optional reflect flag
        reflect = bool(data.get("reflect", False))

        # Extract optional capability_gap flag
        capability_gap = bool(data.get("capability_gap", False))

        return TaskDAG(nodes=nodes, source_text=source_text, response=resp_text, reflect=reflect, capability_gap=capability_gap)

    def _parse_response(self, content: str, source_text: str) -> TaskDAG:
        """Parse LLM JSON response into a TaskDAG. Delegates to shared utility."""
        from probos.utils.json_extract import extract_json
        try:
            data = extract_json(content)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Failed to parse LLM response as JSON: %s", e)
            return TaskDAG(source_text=source_text)
        if not isinstance(data, dict) or "intents" not in data:
            logger.warning("LLM response missing 'intents' key")
            return TaskDAG(source_text=source_text)
        if not isinstance(data.get("intents"), list):
            logger.warning("LLM response 'intents' is not a list")
            return TaskDAG(source_text=source_text)
        return self._build_dag(data, source_text)

    def _extract_json(self, content: str) -> str:
        """Extract JSON from LLM response. Delegates to shared utility."""
        from probos.utils.json_extract import extract_json
        result = extract_json(content)
        return json.dumps(result)

    # Common query-parameter names that indicate fabricated credentials
    _CREDENTIAL_PARAMS = frozenset({
        "apikey", "api_key", "api-key", "access_token", "token",
        "secret", "key", "auth", "authorization", "password",
        "client_secret", "app_key", "appkey", "app_id",
    })

    @classmethod
    def _has_fake_credentials(cls, url: str) -> bool:
        """Return True if the URL contains query parameters that look like fabricated API credentials."""
        from urllib.parse import urlparse, parse_qs
        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            return any(k.lower() in cls._CREDENTIAL_PARAMS for k in params)
        except Exception:
            return False


def _normalize_consensus_result(
    result: Any, intent: str, *, success: bool = True
) -> dict[str, Any]:
    """Convert a consensus-wrapped result into the standard result format.

    The standard format has ``success``, ``results`` (list[IntentResult]),
    ``intent``, and ``result_count`` — matching what the non-consensus
    path produces.  This lets the display code and reflector handle
    consensus and non-consensus results identically.
    """
    if not isinstance(result, dict) or "results" not in result:
        return result  # Already in a different format, pass through.

    agent_results = result["results"]
    return {
        "intent": intent,
        "results": agent_results,
        "success": success and any(
            getattr(r, "success", False) for r in agent_results
        ),
        "result_count": len(agent_results),
    }


def _summarize_node_result(node_result: Any) -> str:
    """Extract meaningful output from a node result for reflection.

    Pulls actual agent output (stdout, file content, etc.) from the
    nested IntentResult objects rather than dumping raw metadata.
    Deduplicates identical outputs from multiple agents.
    """
    if not isinstance(node_result, dict):
        return str(node_result)[:500]

    # Standard format: {success, results: [IntentResult, ...], ...}
    if "results" in node_result:
        success = node_result.get("success", False)
        # Collect unique outputs (agents often return identical results)
        seen_outputs: list[str] = []
        errors: list[str] = []
        for ir in node_result["results"]:
            if hasattr(ir, "result") and ir.result is not None:
                data = ir.result
                if isinstance(data, dict) and "stdout" in data:
                    stdout = data["stdout"].strip()
                    stderr = data.get("stderr", "").strip()
                    exit_code = data.get("exit_code")
                    entry = stdout[:500] if stdout else ""
                    if stderr:
                        entry += f" (stderr: {stderr[:200]})"
                    if exit_code and exit_code != 0:
                        entry += f" (exit_code: {exit_code})"
                    if entry and entry not in seen_outputs:
                        seen_outputs.append(entry)
                elif isinstance(data, dict) and "doc_snippets" in data:
                    # AD-301: Give doc_snippets their own budget so they
                    # aren't truncated by semantic layer results.
                    base = {k: v for k, v in data.items()
                            if k not in ("doc_snippets", "grounded_context")}
                    entry = str(base)[:400]
                    if entry not in seen_outputs:
                        seen_outputs.append(entry)
                    for snip in data["doc_snippets"]:
                        doc_entry = (
                            f"[doc: {snip.get('path', '?')}]\n"
                            f"{snip.get('source', '')[:1500]}"
                        )
                        if doc_entry not in seen_outputs:
                            seen_outputs.append(doc_entry)
                    # AD-320: Preserve grounded context alongside doc_snippets
                    gc = data.get("grounded_context", "")
                    if gc:
                        gc_entry = f"\nGROUNDED SYSTEM FACTS:\n{gc}"
                        if gc_entry not in seen_outputs:
                            seen_outputs.append(gc_entry)
                elif isinstance(data, dict) and "grounded_context" in data:
                    # AD-320: Preserve grounded context for reflector
                    gc = data.get("grounded_context")
                    base = {k: v for k, v in data.items()
                            if k != "grounded_context"}
                    entry = str(base)[:500]
                    if entry not in seen_outputs:
                        seen_outputs.append(entry)
                    gc_entry = f"\nGROUNDED SYSTEM FACTS:\n{gc}"
                    if gc_entry not in seen_outputs:
                        seen_outputs.append(gc_entry)
                else:
                    entry = str(data)[:500]
                    if entry not in seen_outputs:
                        seen_outputs.append(entry)
            elif hasattr(ir, "error") and ir.error:
                if ir.error not in errors:
                    errors.append(ir.error)
        parts = [f"success={success}"]
        for out in seen_outputs:
            parts.append(f"output={out}")
        for err in errors:
            parts.append(f"error={err}")
        return "; ".join(parts)

    # Error result
    if "error" in node_result:
        return f"error={node_result['error']}"

    return str(node_result)[:500]


class DAGExecutor:
    """Executes a TaskDAG through the ProbOS runtime.

    Handles parallel independent intents, sequential dependent intents,
    and consensus-gated writes.
    """

    def __init__(
        self,
        runtime: Any,  # ProbOSRuntime (avoid circular import)
        timeout: float = 60.0,
        attention: Any | None = None,  # AttentionManager (optional)
        escalation_manager: Any | None = None,  # EscalationManager (optional)
    ) -> None:
        self.runtime = runtime
        self.timeout = timeout
        self.attention = attention
        self.escalation_manager = escalation_manager
        self._dag_start: float = 0.0

    async def execute(
        self,
        dag: TaskDAG,
        on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """Execute a TaskDAG, respecting dependency ordering.

        Returns a dict with node results and overall status.
        If on_event is provided, it is called with (event_name, data) at
        key points: node_start, node_complete, node_failed.
        """
        results: dict[str, Any] = {}

        # Reset user-wait accumulator so we can extend the deadline
        # by however long the user spent at escalation prompts.
        if self.escalation_manager:
            self.escalation_manager.user_wait_seconds = 0.0

        self._dag_start = time.monotonic()

        try:
            await self._execute_dag(dag, results, on_event=on_event)
        except asyncio.TimeoutError:
            logger.error("DAG execution timed out after %.0fs", self.timeout)
            # Mark remaining pending nodes as failed
            for node in dag.nodes:
                if node.status == "pending":
                    node.status = "failed"
                    results[node.id] = {"error": "DAG execution timed out"}

        return {
            "dag": dag,
            "results": results,
            "complete": dag.is_complete(),
            "node_count": len(dag.nodes),
            "completed_count": sum(1 for n in dag.nodes if n.status == "completed"),
            "failed_count": sum(1 for n in dag.nodes if n.status == "failed"),
        }

    def _effective_elapsed(self) -> float:
        """Wall-clock elapsed minus user-wait time during escalation."""
        elapsed = time.monotonic() - self._dag_start
        user_wait = (
            self.escalation_manager.user_wait_seconds
            if self.escalation_manager else 0.0
        )
        return elapsed - user_wait

    async def _execute_dag(
        self,
        dag: TaskDAG,
        results: dict[str, Any],
        on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        """Execute the DAG, running ready nodes in parallel batches."""
        while not dag.is_complete():
            # Check effective deadline before each batch
            if self._effective_elapsed() > self.timeout:
                raise asyncio.TimeoutError()

            ready = dag.get_ready_nodes()
            if not ready:
                # No ready nodes but not complete — dependency deadlock
                logger.error("DAG deadlock: no ready nodes but DAG not complete")
                for node in dag.nodes:
                    if node.status == "pending":
                        node.status = "failed"
                        results[node.id] = {"error": "Dependency deadlock"}
                break

            # Use attention manager for priority batching if available
            if self.attention and len(ready) > 1:
                batch_nodes = self._attention_batch(ready, dag)
            else:
                batch_nodes = ready

            # Execute batch in parallel
            tasks = [
                self._execute_node(node, dag, results, on_event=on_event)
                for node in batch_nodes
            ]
            await asyncio.gather(*tasks)

    def _attention_batch(
        self, ready: list[TaskNode], dag: TaskDAG
    ) -> list[TaskNode]:
        """Submit ready nodes to attention manager and return prioritized batch."""
        # Compute dependency depth: how many downstream nodes depend on this one
        dep_depth: dict[str, int] = {}
        for node in dag.nodes:
            for dep_id in node.depends_on:
                dep_depth[dep_id] = dep_depth.get(dep_id, 0) + 1

        for node in ready:
            entry = AttentionEntry(
                task_id=node.id,
                intent=node.intent,
                urgency=0.5,
                dependency_depth=dep_depth.get(node.id, 0),
                is_background=node.background,
            )
            self.attention.submit(entry)

        batch = self.attention.get_next_batch()
        batch_ids = {e.task_id for e in batch}

        # Clean up: remove from queue regardless (they'll be re-submitted
        # next cycle if still ready)
        for node in ready:
            self.attention.mark_completed(node.id)

        return [n for n in ready if n.id in batch_ids]

    async def _execute_node(
        self,
        node: TaskNode,
        dag: TaskDAG,
        results: dict[str, Any],
        on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        """Execute a single node."""
        node.status = "running"
        if on_event:
            event_data: dict[str, Any] = {"node": node, "intent": node.intent}
            # Look up a representative agent for this intent (for HXI visualization)
            if self.runtime and hasattr(self.runtime, 'pools'):
                for pool_name, pool in self.runtime.pools.items():
                    if pool.agent_type and hasattr(pool, 'healthy_agents'):
                        # Check if this pool handles this intent
                        template = self.runtime.spawner._templates.get(pool.agent_type)
                        if template:
                            descriptors = getattr(template, 'intent_descriptors', [])
                            if any(d.name == node.intent for d in descriptors):
                                agents = list(pool.healthy_agents)
                                if agents:
                                    agent = agents[0]
                                    event_data["agent_id"] = agent if isinstance(agent, str) else agent.id
                                break
            if self.attention:
                # Include attention info in event
                snapshot = self.attention.get_queue_snapshot()
                scores = {e.task_id: e.score for e in snapshot}
                event_data["attention_score"] = scores.get(node.id, 0.0)
            await on_event("node_start", event_data)

        # Substitute dependency results into params if needed
        params = dict(node.params)
        for dep_id in node.depends_on:
            dep_result = results.get(dep_id)
            if dep_result and isinstance(dep_result, dict):
                # Make dependency result available as $dep_id
                params[f"${dep_id}"] = dep_result

        logger.info(
            "Executing DAG node: id=%s intent=%s depends=%s consensus=%s",
            node.id, node.intent, node.depends_on, node.use_consensus,
        )

        try:
            if node.intent == "write_file" and node.use_consensus:
                result = await self.runtime.submit_write_with_consensus(
                    path=params.get("path", ""),
                    content=params.get("content", ""),
                    timeout=10.0,
                )
                node.result = result
                results[node.id] = result
                # Check consensus outcome
                consensus = result.get("consensus")
                if consensus and consensus.outcome in (
                    ConsensusOutcome.REJECTED, ConsensusOutcome.INSUFFICIENT
                ):
                    await self._handle_rejection(
                        node, dag, results,
                        f"Consensus {consensus.outcome.value}",
                        on_event=on_event,
                    )
                else:
                    node.status = "completed"
            elif node.use_consensus:
                result = await self.runtime.submit_intent_with_consensus(
                    intent=node.intent,
                    params=params,
                    timeout=10.0,
                )
                node.result = result
                results[node.id] = result
                # Check consensus outcome
                consensus = result.get("consensus")
                if consensus and consensus.outcome in (
                    ConsensusOutcome.REJECTED, ConsensusOutcome.INSUFFICIENT
                ):
                    await self._handle_rejection(
                        node, dag, results,
                        f"Consensus {consensus.outcome.value}",
                        on_event=on_event,
                    )
                else:
                    # Normalize into standard result format so display
                    # code can find the agent output via success key.
                    normalized = _normalize_consensus_result(
                        result, node.intent, success=True
                    )
                    node.result = normalized
                    results[node.id] = normalized
                    node.status = "completed"
            else:
                intent_results = await self.runtime.submit_intent(
                    intent=node.intent,
                    params=params,
                    timeout=10.0,
                )
                success = any(r.success for r in intent_results)
                node.result = intent_results
                results[node.id] = {
                    "intent": node.intent,
                    "results": intent_results,
                    "success": success,
                    "result_count": len(intent_results),
                }
                node.status = "completed" if success else "failed"

            if on_event and node.status == "completed":
                await on_event("node_complete", {"node": node, "result": results.get(node.id)})
            elif on_event and node.status == "failed":
                await on_event("node_failed", {"node": node, "result": results.get(node.id)})

        except Exception as e:
            logger.error("Node %s failed: %s", node.id, e)
            if self.escalation_manager is not None:
                if on_event:
                    await on_event("escalation_start", {
                        "node": node, "error": str(e),
                        "category": "consensus", "event": "escalation_start",
                    })
                esc_result = await self.escalation_manager.escalate(
                    node, str(e), {"intent": node.intent, "params": node.params},
                )
                node.escalation_result = esc_result.to_dict()
                if esc_result.resolved:
                    if esc_result.resolution is not None:
                        node.result = esc_result.resolution
                        results[node.id] = esc_result.resolution
                        node.status = "completed"
                        if on_event:
                            await on_event("escalation_resolved", {
                                "node": node, "escalation": node.escalation_result,
                                "category": "consensus", "event": "escalation_resolved",
                            })
                            await on_event("node_complete", {"node": node, "result": results.get(node.id)})
                    elif esc_result.user_approved is False:
                        node.status = "failed"
                        results[node.id] = {"error": "User rejected the operation"}
                        if on_event:
                            await on_event("escalation_exhausted", {
                                "node": node, "escalation": node.escalation_result,
                                "category": "consensus", "event": "escalation_exhausted",
                            })
                            await on_event("node_failed", {"node": node, "error": "User rejected"})
                    else:
                        node.status = "completed"
                        if on_event:
                            await on_event("escalation_resolved", {
                                "node": node, "escalation": node.escalation_result,
                                "category": "consensus", "event": "escalation_resolved",
                            })
                            await on_event("node_complete", {"node": node, "result": results.get(node.id)})
                else:
                    node.status = "failed"
                    results[node.id] = {"error": str(e)}
                    if on_event:
                        await on_event("escalation_exhausted", {
                            "node": node, "escalation": node.escalation_result,
                            "category": "consensus", "event": "escalation_exhausted",
                        })
                        await on_event("node_failed", {"node": node, "error": str(e)})
            else:
                node.status = "failed"
                results[node.id] = {"error": str(e)}
                if on_event:
                    await on_event("node_failed", {"node": node, "error": str(e)})

    async def _handle_rejection(
        self,
        node: TaskNode,
        dag: TaskDAG,
        results: dict[str, Any],
        error: str,
        on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        """Handle a consensus-rejected node: escalate or mark failed."""
        if self.escalation_manager is not None:
            if on_event:
                await on_event("escalation_start", {
                    "node": node, "error": error,
                    "category": "consensus", "event": "escalation_start",
                })
            esc_result = await self.escalation_manager.escalate(
                node, error, {"intent": node.intent, "params": node.params},
            )
            logger.info(
                "Escalation result for node %s: resolved=%s tier=%s "
                "user_approved=%s has_resolution=%s",
                node.id, esc_result.resolved, esc_result.tier,
                esc_result.user_approved, esc_result.resolution is not None,
            )
            node.escalation_result = esc_result.to_dict()
            if esc_result.resolved:
                if esc_result.resolution is not None:
                    # Normalize consensus-wrapped results: strip the
                    # rejected consensus object so downstream display
                    # and reflection see a clean successful result.
                    resolution = _normalize_consensus_result(
                        esc_result.resolution, node.intent, success=True
                    )
                    node.result = resolution
                    results[node.id] = resolution
                    node.status = "completed"
                    if on_event:
                        await on_event("escalation_resolved", {
                            "node": node, "escalation": node.escalation_result,
                            "category": "consensus", "event": "escalation_resolved",
                        })
                        await on_event("node_complete", {"node": node, "result": results.get(node.id)})
                elif esc_result.user_approved is False:
                    # User explicitly rejected — treat as failure.
                    node.status = "failed"
                    results[node.id] = {"error": "User rejected the operation"}
                    if on_event:
                        await on_event("escalation_exhausted", {
                            "node": node, "escalation": node.escalation_result,
                            "category": "consensus", "event": "escalation_exhausted",
                        })
                        await on_event("node_failed", {"node": node, "error": "User rejected"})
                else:
                    node.status = "completed"
                    if on_event:
                        await on_event("escalation_resolved", {
                            "node": node, "escalation": node.escalation_result,
                            "category": "consensus", "event": "escalation_resolved",
                        })
                        await on_event("node_complete", {"node": node, "result": results.get(node.id)})
            else:
                node.status = "failed"
                if on_event:
                    await on_event("escalation_exhausted", {
                        "node": node, "escalation": node.escalation_result,
                        "category": "consensus", "event": "escalation_exhausted",
                    })
                    await on_event("node_failed", {"node": node, "error": error})
        else:
            node.status = "failed"
            if on_event:
                await on_event("node_failed", {"node": node, "error": error})
