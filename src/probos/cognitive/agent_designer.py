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

Your job is to write a CognitiveAgent subclass that handles this intent.
CognitiveAgent is a base class where decide() consults an LLM guided by
per-agent instructions.  You write the instructions (system prompt) —
the LLM does the reasoning at runtime.

The agent MUST:
1. Subclass CognitiveAgent (NOT BaseAgent)
2. Define an `instructions` class attribute — a detailed system prompt that
   tells the LLM how to reason about this domain
3. Define `intent_descriptors` as a class variable
4. Define `agent_type` and `_handled_intents`
5. Override `act()` to parse the LLM's output into structured results
6. Be self-contained (~30-60 lines)

CognitiveAgent provides (you inherit these, do NOT redefine them):
- perceive() — packages the IntentMessage as an observation dict
- decide() — sends observation to LLM with instructions as system prompt
- report() — packages result dict as IntentResult
- handle_intent() — runs the full perceive->decide->act->report lifecycle
- __init__(**kwargs) — extracts instructions, llm_client, runtime from kwargs

act() receives a decision dict from decide():
  {{"action": "execute", "llm_output": "...", "tier_used": "..."}}
  OR {{"action": "error", "reason": "..."}}
Your act() override should parse the llm_output string. The base class
act() just returns the raw string — override it for structured output.

IntentResult signature (dataclass):
    IntentResult(intent_id: str, agent_id: str, success: bool, result: Any = None, error: str | None = None, confidence: float = 0.0)
    NOTE: The field is "result", NOT "data". There is no "data" parameter.

IntentMessage signature (dataclass):
    IntentMessage(intent: str, params: dict, id: str = auto, source: str = "", priority: float = 0.5)

TEMPLATE:

```python
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import IntentDescriptor

class {class_name}(CognitiveAgent):
    \"\"\"Cognitive agent for {intent_name}.\"\"\"

    agent_type = "{agent_type}"
    _handled_intents = {{"{intent_name}"}}
    instructions = (
        "You are a specialist for {intent_name} tasks. "
        "... describe the domain, reasoning approach, output format ... "
        "Respond with a clear, structured answer."
    )
    intent_descriptors = [
        IntentDescriptor(
            name="{intent_name}",
            params={param_schema},
            description="{intent_description}",
            requires_consensus={requires_consensus},
            requires_reflect=True,
            tier="domain",
        )
    ]

    async def act(self, decision: dict) -> dict:
        if decision.get("action") == "error":
            return {{"success": False, "error": decision.get("reason")}}
        llm_output = decision.get("llm_output", "")
        return {{"success": True, "result": llm_output}}
```

INSTRUCTIONS GUIDELINES — the `instructions` string should include:
- What domain this agent covers
- What output format the agent should produce (so act() can parse it)
- What constraints the agent operates under
- How the agent should handle edge cases
- That the agent should be concise and structured

RULES:
- Only use imports from this whitelist: {allowed_imports}, probos.cognitive.cognitive_agent
- Do NOT use subprocess, eval, exec, __import__, socket, ctypes
- Do NOT redefine perceive(), decide(), report(), handle_intent(), or __init__()
- Do NOT import BaseAgent — use CognitiveAgent instead
- The instructions string is the CORE output — make it detailed and specific
- Return the COMPLETE Python file content, nothing else
- No markdown code fences, no explanation, just the Python code

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
