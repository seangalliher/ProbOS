"""Intent decomposition engine — NL to task DAG with execution."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TYPE_CHECKING

from probos.cognitive.llm_client import BaseLLMClient
from probos.cognitive.working_memory import WorkingMemoryManager, WorkingMemorySnapshot
from probos.types import LLMRequest, TaskDAG, TaskNode

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You MUST respond with ONLY a JSON object. No preamble, no explanation, no \
markdown code fences, no text before or after the JSON. Your entire response \
must be parseable as a single JSON object.

You are the intent decomposition engine of ProbOS, a probabilistic agent-native \
operating system runtime. You translate user requests into structured intents.

## Available intents

| Intent       | Params                                       | Description                    |
|--------------|----------------------------------------------|--------------------------------|
| read_file    | {"path": "<absolute_path>"}                  | Read a file and return content |
| stat_file    | {"path": "<absolute_path>"}                  | Get file size, mtime, etc.     |
| write_file   | {"path": "<absolute_path>", "content": "…"}  | Write content to a file        |

## Response format

Your response MUST be exactly one JSON object with this structure:

{"intents": [...], "response": "optional text for the user"}

- "intents": array of intent objects (empty array if no actionable intents)
- "response": optional string — a brief message for the user. Use this for \
conversational replies, confirmations, or when no intents apply.

Each intent object:

{"id": "t1", "intent": "<name>", "params": {...}, "depends_on": [], "use_consensus": false}

## Rules

1. RESPOND ONLY WITH JSON. No natural language outside the JSON object. \
No markdown. No code fences. No commentary. Just the raw JSON object.
2. Use sequential IDs: t1, t2, t3, …
3. Independent intents have "depends_on": [] and execute in parallel.
4. If intent B needs the result of intent A, set "depends_on": ["t1"].
5. All write_file intents MUST have "use_consensus": true.
6. read_file and stat_file intents should have "use_consensus": false.
7. Paths must be absolute. Use the path exactly as the user provides it.
8. If the request cannot be mapped to any available intent, respond with \
{"intents": [], "response": "a helpful explanation of what you can do"}.
9. Never invent intents not in the table above.

## Examples

User: "read the file at /tmp/test.txt"
{"intents": [{"id": "t1", "intent": "read_file", "params": {"path": "/tmp/test.txt"}, "depends_on": [], "use_consensus": false}]}

User: "read /tmp/a.txt and /tmp/b.txt"
{"intents": [{"id": "t1", "intent": "read_file", "params": {"path": "/tmp/a.txt"}, "depends_on": [], "use_consensus": false}, {"id": "t2", "intent": "read_file", "params": {"path": "/tmp/b.txt"}, "depends_on": [], "use_consensus": false}]}

User: "write hello to /tmp/out.txt"
{"intents": [{"id": "t1", "intent": "write_file", "params": {"path": "/tmp/out.txt", "content": "hello"}, "depends_on": [], "use_consensus": true}]}

User: "hello"
{"intents": [], "response": "Hello! I'm ProbOS, a probabilistic agent-native OS. I can read, write, and inspect files. Try: read /tmp/test.txt"}

User: "what can you do?"
{"intents": [], "response": "I can read files, write files, and get file metadata. All writes go through consensus verification. Try asking me to read or write a file."}

User: "what is the weather?"
{"intents": [], "response": "I can only perform file operations (read, write, stat). I don't have access to weather data."}
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
    ) -> None:
        self.llm_client = llm_client
        self.working_memory = working_memory
        self.timeout = timeout
        self.last_raw_response: str = ""  # Last raw LLM response for debugging

    async def decompose(
        self,
        text: str,
        context: WorkingMemorySnapshot | None = None,
    ) -> TaskDAG:
        """Decompose natural language text into a TaskDAG.

        1. Assemble working memory context
        2. Build LLM prompt with system state + user request
        3. Call LLM
        4. Parse response into TaskDAG
        """
        # Build prompt
        prompt_parts = []
        if context:
            prompt_parts.append(context.to_text())
            prompt_parts.append("")
        prompt_parts.append(f"User request: {text}")

        request = LLMRequest(
            prompt="\n".join(prompt_parts),
            system_prompt=SYSTEM_PROMPT,
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
        logger.info("Raw LLM response: %s", response.content)
        dag = self._parse_response(response.content, text)
        return dag

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

        return TaskDAG(nodes=nodes, source_text=source_text, response=response)

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
    ) -> None:
        self.runtime = runtime
        self.timeout = timeout

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

            # Execute all ready nodes in parallel
            tasks = [
                self._execute_node(node, dag, results, on_event=on_event)
                for node in ready
            ]
            await asyncio.gather(*tasks)

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
            await on_event("node_start", {"node": node})

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
                node.status = "completed"
            elif node.use_consensus:
                result = await self.runtime.submit_intent_with_consensus(
                    intent=node.intent,
                    params=params,
                    timeout=10.0,
                )
                node.result = result
                results[node.id] = result
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

            if on_event:
                await on_event("node_complete", {"node": node, "result": results.get(node.id)})

        except Exception as e:
            logger.error("Node %s failed: %s", node.id, e)
            node.status = "failed"
            results[node.id] = {"error": str(e)}
            if on_event:
                await on_event("node_failed", {"node": node, "error": str(e)})
