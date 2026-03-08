"""Intent decomposition engine — NL to task DAG with execution."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TYPE_CHECKING

from probos.cognitive.llm_client import BaseLLMClient
from probos.cognitive.prompt_builder import PromptBuilder, get_platform_context
from probos.cognitive.working_memory import WorkingMemoryManager, WorkingMemorySnapshot
from probos.types import ConsensusOutcome, IntentDescriptor, LLMRequest, TaskDAG, TaskNode, Episode, AttentionEntry

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

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

{"intents": [...], "response": "optional text for the user", "reflect": false}

- "intents": array of intent objects (empty array if no actionable intents)
- "response": optional string — a brief message for the user. Use this for \
conversational replies, confirmations, or when no intents apply.
- "reflect": boolean — set to true when the user asks for analysis, \
interpretation, comparison, summary, or opinion about the results. Set to \
false for simple data retrieval or command execution.

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
7. All http_fetch intents MUST have "use_consensus": true.
8. read_file and stat_file intents should have "use_consensus": false.
9. list_directory and search_files should have "use_consensus": false.
10. Paths must be absolute. Use the path exactly as the user provides it.
11. If the request cannot be mapped to any available intent, respond with \
{"intents": [], "response": "a helpful explanation of what you can do"}.
12. Never invent intents not in the table above.
13a. ONLY use run_command when a real program or OS utility genuinely \
computes the answer (e.g. date/time, math, system info, pip install). \
NEVER use run_command to output hardcoded text you already know \
(echo, Write-Host, Write-Output, printf, print, etc.). Translation, \
conversation, creative writing, and knowledge questions are NOT \
run_command tasks — return {"intents": [], "response": "..."} instead.
13. Set "reflect" to true when the user asks for analysis, interpretation, \
comparison, summary, or opinion about results. Also set "reflect" to true for \
any intent that transforms, translates, generates, or produces content the user \
wants to see explained in natural language. Set to false only for simple data \
retrieval or command execution where the raw result is self-explanatory.
14. explain_last, agent_info, system_health, why intents should have \
"use_consensus": false.

## Examples

User: "read the file at /tmp/test.txt"
{"intents": [{"id": "t1", "intent": "read_file", "params": {"path": "/tmp/test.txt"}, "depends_on": [], "use_consensus": false}], "reflect": false}

User: "read /tmp/a.txt and /tmp/b.txt"
{"intents": [{"id": "t1", "intent": "read_file", "params": {"path": "/tmp/a.txt"}, "depends_on": [], "use_consensus": false}, {"id": "t2", "intent": "read_file", "params": {"path": "/tmp/b.txt"}, "depends_on": [], "use_consensus": false}], "reflect": false}

User: "write hello to /tmp/out.txt"
{"intents": [{"id": "t1", "intent": "write_file", "params": {"path": "/tmp/out.txt", "content": "hello"}, "depends_on": [], "use_consensus": true}], "reflect": false}

User: "hello"
{"intents": [], "response": "Hello! I'm ProbOS, a probabilistic agent-native OS. I can read, write, and inspect files. Try: read /tmp/test.txt"}

User: "what can you do?"
{"intents": [], "response": "I can read files, write files, list directories, search for files, run shell commands, fetch URLs, and answer questions about my own state (explain what happened, describe agents, assess system health, explain my reasoning). Writes, commands, and HTTP requests go through consensus verification."}

User: "what is the weather?"
{"intents": [], "response": "I can only perform file, system, and self-inspection operations. I don't have access to weather data."}

User: "list the files in /tmp/mydir"
{"intents": [{"id": "t1", "intent": "list_directory", "params": {"path": "/tmp/mydir"}, "depends_on": [], "use_consensus": false}], "reflect": false}

User: "find all .txt files in /home/user/docs"
{"intents": [{"id": "t1", "intent": "search_files", "params": {"path": "/home/user/docs", "pattern": "*.txt"}, "depends_on": [], "use_consensus": false}], "reflect": false}

User: "run the command echo hello"
{"intents": [{"id": "t1", "intent": "run_command", "params": {"command": "echo hello"}, "depends_on": [], "use_consensus": true}], "reflect": false}

User: "fetch https://httpbin.org/get"
{"intents": [{"id": "t1", "intent": "http_fetch", "params": {"url": "https://httpbin.org/get", "method": "GET"}, "depends_on": [], "use_consensus": true}], "reflect": false}

User: "what is the largest file in /tmp/mydir?"
{"intents": [{"id": "t1", "intent": "list_directory", "params": {"path": "/tmp/mydir"}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "fetch https://example.com and summarize it"
{"intents": [{"id": "t1", "intent": "http_fetch", "params": {"url": "https://example.com", "method": "GET"}, "depends_on": [], "use_consensus": true}], "reflect": true}

User: "why did you use file_reader for that?"
{"intents": [{"id": "t1", "intent": "why", "params": {"question": "why did you use file_reader for that?"}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "how healthy is the system?"
{"intents": [{"id": "t1", "intent": "system_health", "params": {}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "what just happened?"
{"intents": [{"id": "t1", "intent": "explain_last", "params": {}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "tell me about file_reader agents"
{"intents": [{"id": "t1", "intent": "agent_info", "params": {"agent_type": "file_reader"}, "depends_on": [], "use_consensus": false}], "reflect": true}
"""

# Public alias for backward compatibility (tests import SYSTEM_PROMPT)
SYSTEM_PROMPT = _LEGACY_SYSTEM_PROMPT

REFLECT_PROMPT = """\
You are analyzing results returned by ProbOS agents in response to a user request.
You will receive the user's original request and the results from each agent operation.
Synthesize a clear, concise response that directly answers the user's question.
Focus on answering what the user asked — do not describe the operations that were performed.
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

        prompt_parts.append(f"User request: {text}")

        # Select system prompt: dynamic if descriptors available, else legacy
        if self._intent_descriptors:
            system_prompt = self._prompt_builder.build_system_prompt(self._intent_descriptors)
        else:
            system_prompt = _LEGACY_SYSTEM_PROMPT + "\n\n" + get_platform_context()

        request = LLMRequest(
            prompt="\n".join(prompt_parts),
            system_prompt=system_prompt,
            tier="standard",
            temperature=0.0,
        )

        # Call LLM
        try:
            response = await asyncio.wait_for(
                self.llm_client.complete(request),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            logger.error("LLM decomposition timed out for: %s", text[:50])
            return TaskDAG(source_text=text)

        if response.error:
            logger.error("LLM error during decomposition: %s", response.error)
            return TaskDAG(source_text=text)

        # Parse response into TaskDAG
        self.last_raw_response = response.content
        logger.debug("Raw LLM response: %s", response.content)
        dag = self._parse_response(response.content, text)
        return dag

    # Payload budget for reflect prompt (~2000 tokens ≈ 8000 chars).
    REFLECT_PAYLOAD_BUDGET: int = 8000

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
                result_parts.append(
                    f"- {node.intent}({node.params}): {node_result}"
                )

        prompt_text = "\n".join(result_parts)

        # Cap payload to avoid oversized LLM requests
        if len(prompt_text) > self.REFLECT_PAYLOAD_BUDGET:
            prompt_text = (
                prompt_text[: self.REFLECT_PAYLOAD_BUDGET]
                + "\n\n[... results truncated ...]"
            )

        request = LLMRequest(
            prompt=prompt_text,
            system_prompt=REFLECT_PROMPT,
            tier="standard",
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

    def _parse_response(self, content: str, source_text: str) -> TaskDAG:
        """Parse LLM JSON response into a TaskDAG.

        Handles malformed responses gracefully.
        """
        try:
            # Try to extract JSON from the response
            json_str = self._extract_json(content)
            data = json.loads(json_str)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Failed to parse LLM response as JSON: %s", e)
            return TaskDAG(source_text=source_text)

        if not isinstance(data, dict) or "intents" not in data:
            logger.warning("LLM response missing 'intents' key")
            return TaskDAG(source_text=source_text)

        intents = data["intents"]
        if not isinstance(intents, list):
            logger.warning("LLM response 'intents' is not a list")
            return TaskDAG(source_text=source_text)

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
                nodes.append(node)

        # Extract optional conversational response
        response = data.get("response", "")
        if not isinstance(response, str):
            response = ""

        # Extract optional reflect flag
        reflect = bool(data.get("reflect", False))

        return TaskDAG(nodes=nodes, source_text=source_text, response=response, reflect=reflect)

    def _extract_json(self, content: str) -> str:
        """Extract JSON from LLM response, handling markdown code blocks."""
        content = content.strip()

        # Try to find JSON in code blocks
        import re
        code_block = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
        if code_block:
            return code_block.group(1).strip()

        # Try the raw content as JSON
        if content.startswith("{"):
            return content

        # Try to find a JSON object anywhere in the content
        brace_start = content.find("{")
        if brace_start >= 0:
            # Find matching closing brace
            depth = 0
            for i in range(brace_start, len(content)):
                if content[i] == "{":
                    depth += 1
                elif content[i] == "}":
                    depth -= 1
                    if depth == 0:
                        return content[brace_start:i + 1]

        raise ValueError("No JSON object found in response")


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

        try:
            await asyncio.wait_for(
                self._execute_dag(dag, results, on_event=on_event),
                timeout=self.timeout,
            )
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

    async def _execute_dag(
        self,
        dag: TaskDAG,
        results: dict[str, Any],
        on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        """Execute the DAG, running ready nodes in parallel batches."""
        while not dag.is_complete():
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
            event_data: dict[str, Any] = {"node": node}
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
                    node.status = "completed"
            else:
                intent_results = await self.runtime.submit_intent(
                    intent=node.intent,
                    params=params,
                    timeout=10.0,
                )
                node.result = intent_results
                results[node.id] = {
                    "intent": node.intent,
                    "results": intent_results,
                    "success": any(r.success for r in intent_results),
                    "result_count": len(intent_results),
                }
                node.status = "completed"

            if on_event and node.status == "completed":
                await on_event("node_complete", {"node": node, "result": results.get(node.id)})

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
