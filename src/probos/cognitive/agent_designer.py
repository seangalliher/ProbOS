"""AgentDesigner — generates agent code via LLM for unhandled intents."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from probos.cognitive.prompt_builder import get_platform_context
from probos.types import LLMRequest

if TYPE_CHECKING:
    from probos.cognitive.llm_client import BaseLLMClient
    from probos.config import SelfModConfig

logger = logging.getLogger(__name__)

AGENT_DESIGN_PROMPT = """You are the cognitive layer of ProbOS, a probabilistic agent-native OS.
The system received an intent that no existing agent can handle.

UNHANDLED INTENT:
  Name: {intent_name}
  Description: {intent_description}
  Parameters: {parameters}

Your job is to write a Python agent class that handles this intent.
The agent MUST:
1. Subclass BaseAgent
2. Define intent_descriptors as a class variable
3. Implement handle_intent(self, intent: IntentMessage) -> IntentResult
4. Implement the four lifecycle methods: perceive, decide, act, report
5. Return IntentResult with the correct fields (see signature below)
6. Be self-contained (~50-100 lines)

IntentResult signature (dataclass):
    IntentResult(intent_id: str, agent_id: str, success: bool, result: Any = None, error: str | None = None, confidence: float = 0.0)
    NOTE: The field is "result", NOT "data". There is no "data" parameter.

IntentMessage signature (dataclass):
    IntentMessage(intent: str, params: dict, id: str = auto, source: str = "", priority: float = 0.5)

BaseAgent key attributes (inherited via super().__init__):
    self.id          — the agent's unique ID (NOT self.agent_id)
    self.pool        — pool name
    self.confidence  — current confidence score

LLM ACCESS (for inference — translation, summarization, creative writing):
    self._llm_client is an LLM client injected at runtime (may be None in sandbox).
    Use ONLY for tasks where the LLM itself is the tool — translation, summarization,
    creative writing, text analysis, reformatting. Do NOT use the LLM to answer factual
    questions — it has no internet access and may hallucinate.

        from probos.types import LLMRequest
        request = LLMRequest(prompt="Translate 'hello' to French. Reply with ONLY the translation, nothing else.", tier="fast")
        response = await self._llm_client.complete(request)
        translated = response.content  # the LLM's text response

    IMPORTANT: Always check `if self._llm_client:` before calling it.
    If self._llm_client is None (sandbox testing), return a placeholder result.

MESH ACCESS (for external data — web lookups, factual questions, current info):
    self._runtime is injected at runtime (may be None in sandbox).
    Use it to dispatch sub-intents to other agents via the intent bus.
    For any task that needs external/real-world data (person lookup, web search,
    current events, factual questions), dispatch an http_fetch sub-intent:

        from probos.types import IntentMessage as IM
        if self._runtime:
            fetch_intent = IM(intent="http_fetch", params={{"url": "https://en.wikipedia.org/api/rest_v1/page/summary/Python_(programming_language)", "method": "GET"}})
            results = await self._runtime.intent_bus.broadcast(fetch_intent, timeout=15.0)
            successful = [r for r in results if r.success]
            if successful:
                data = successful[0].result  # raw HTTP response data
                # Then optionally use self._llm_client to summarize/synthesize the fetched data

    IMPORTANT: Always check `if self._runtime:` before using it.
    If self._runtime is None (sandbox testing), return a placeholder result.
    For factual/knowledge tasks, ALWAYS fetch from the web first, then optionally
    use the LLM to synthesize/summarize the fetched content. NEVER use the LLM
    alone to answer factual questions — it cannot access the internet.

TEMPLATE (fill in the implementation):

```python
from probos.substrate.agent import BaseAgent
from probos.types import IntentMessage, IntentResult, IntentDescriptor, LLMRequest

class {class_name}(BaseAgent):
    \"\"\"Auto-generated agent for {intent_name}.\"\"\"

    agent_type = "{agent_type}"
    _handled_intents = ["{intent_name}"]
    intent_descriptors = [
        IntentDescriptor(
            name="{intent_name}",
            params={param_schema},
            description="{intent_description}",
            requires_consensus={requires_consensus},
            requires_reflect=True,
        )
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._llm_client = kwargs.get("llm_client")

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        if intent.intent not in self._handled_intents:
            return None
        # YOUR IMPLEMENTATION HERE

    async def perceive(self, intent: dict) -> any:
        intent_name = intent.get("intent", "")
        if intent_name not in self._handled_intents:
            return None
        return {{"intent": intent_name, "params": intent.get("params", {{}})}}

    async def decide(self, observation: any) -> any:
        if observation is None:
            return None
        return {{"action": observation["intent"], "params": observation["params"]}}

    async def act(self, plan: any) -> any:
        if plan is None:
            return {{"success": False, "error": "No plan"}}
        from probos.types import IntentMessage as IM
        intent = IM(intent=plan["action"], params=plan["params"])
        result = await self.handle_intent(intent)
        if result is None:
            return {{"success": False, "error": "Unhandled"}}
        return result.result if result.result else {{"success": result.success}}

    async def report(self, result: any) -> dict:
        return result if isinstance(result, dict) else {{"result": result}}
```

RULES:
- Only use imports from this whitelist: {allowed_imports}, probos.types.LLMRequest
- Do NOT use subprocess, eval, exec, __import__, socket, ctypes
- Do NOT write files (no open() with 'w' mode) — use the existing FileWriterAgent for writes
- Do NOT make direct network calls (no socket, no urllib.request, no httpx) — \
dispatch http_fetch sub-intents through self._runtime.intent_bus instead
- You MUST keep the __init__(self, **kwargs) that calls super().__init__(**kwargs) AND self._llm_client = kwargs.get("llm_client") exactly as shown
- For INFERENCE tasks (translation, summarization, creative writing, text analysis), use self._llm_client
- For EXTERNAL DATA tasks (person/topic lookup, factual questions, current events, \
web search), use self._runtime.intent_bus to dispatch http_fetch sub-intents, \
then optionally use self._llm_client to synthesize the fetched content
- NEVER use self._llm_client alone to answer factual/knowledge questions — it has \
no internet access and will hallucinate
- Return the COMPLETE Python file content, nothing else
- No markdown code fences, no explanation, just the Python code
- You MUST include ALL four lifecycle methods (perceive, decide, act, report) exactly as shown in the template

RESEARCH CONTEXT:
{research_context}

Use the above research to inform your implementation.
If research context says "No research available.", rely on your training knowledge.

{platform_context}
"""


class AgentDesigner:
    """Designs new agent types via LLM when unhandled intents are detected.

    Flow:
    1. Receives unhandled intent description
    2. Builds prompt from AGENT_DESIGN_PROMPT template
    3. Calls LLM (standard tier) to generate agent code
    4. Returns raw code string for validation pipeline
    """

    def __init__(self, llm_client: BaseLLMClient, config: SelfModConfig) -> None:
        self._llm = llm_client
        self._config = config

    async def design_agent(
        self,
        intent_name: str,
        intent_description: str,
        parameters: dict[str, str],
        requires_consensus: bool = False,
        research_context: str = "No research available.",
    ) -> str:
        """Generate agent source code for an unhandled intent.

        Returns raw Python source code string.
        Raises ValueError if LLM returns unparseable output.
        """
        class_name = self._build_class_name(intent_name)
        agent_type = self._build_agent_type(intent_name)

        prompt = AGENT_DESIGN_PROMPT.format(
            intent_name=intent_name,
            intent_description=intent_description,
            parameters=parameters,
            class_name=class_name,
            agent_type=agent_type,
            param_schema=parameters,
            requires_consensus=requires_consensus,
            allowed_imports=", ".join(self._config.allowed_imports),
            research_context=research_context,
            platform_context=get_platform_context(),
        )

        request = LLMRequest(prompt=prompt, tier="standard", max_tokens=4096)
        response = await self._llm.complete(request)

        if not response.content or response.error:
            raise ValueError(
                f"LLM returned empty or error response: {response.error}"
            )

        # Strip <think>...</think> blocks (common with reasoning models)
        code = re.sub(r'<think>.*?</think>', '', response.content, flags=re.DOTALL).strip()
        # Strip markdown code fences if present
        code = re.sub(r'^```python\s*\n', '', code)
        code = re.sub(r'\n```\s*$', '', code)

        return code

    def _build_class_name(self, intent_name: str) -> str:
        """Convert intent_name like 'count_words' to 'CountWordsAgent'."""
        parts = intent_name.split("_")
        return "".join(p.capitalize() for p in parts) + "Agent"

    def _build_agent_type(self, intent_name: str) -> str:
        """Convert intent_name like 'count_words' to 'count_words'."""
        return intent_name
