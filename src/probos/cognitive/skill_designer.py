"""SkillDesigner — generates skill handler functions via LLM."""

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

SKILL_DESIGN_PROMPT = """You are the cognitive layer of ProbOS, a probabilistic agent-native OS.
The system received an intent that can be handled by adding a skill to an existing agent.

SKILL TO CREATE:
  Name: {intent_name}
  Description: {intent_description}
  Parameters: {parameters}
  Target agent type: {target_agent_type}

RESEARCH CONTEXT:
{research_context}

Generate a Python async function that handles this intent.
The function receives an IntentMessage and an optional LLM client,
and returns an IntentResult.

IntentResult signature (dataclass):
    IntentResult(intent_id: str, agent_id: str, success: bool, result: Any = None, error: str | None = None, confidence: float = 0.0)
    NOTE: The field is "result", NOT "data". There is no "data" parameter.

IntentMessage signature (dataclass):
    IntentMessage(intent: str, params: dict, id: str = auto, source: str = "", priority: float = 0.5)

LLM ACCESS:
    If llm_client is provided, use it for intelligence tasks:
        from probos.types import LLMRequest
        request = LLMRequest(prompt="Your detailed prompt here...", tier="standard", max_tokens=2048)
        response = await llm_client.complete(request)
        result_text = response.content
    Use max_tokens=2048 or higher for tasks that need detailed, thorough output.
    Write clear, specific prompts that tell the LLM exactly what you want.

TEMPLATE:

```python
from probos.types import IntentMessage, IntentResult, LLMRequest

async def handle_{intent_name}(intent: IntentMessage, llm_client=None) -> IntentResult:
    \"\"\"Handle {intent_name} intent.\"\"\"
    params = intent.params
    # YOUR IMPLEMENTATION HERE
    return IntentResult(
        intent_id=intent.id,
        agent_id="skill",
        success=True,
        result={{"result": "..."}},
    )
```

RULES:
- Only use imports from this whitelist: {allowed_imports}
- You have access to `llm_client` for LLM inference — use it for intelligence tasks
- To call the LLM: `response = await llm_client.complete(LLMRequest(prompt="...", tier="standard", max_tokens=2048))`
- Import LLMRequest: `from probos.types import LLMRequest`
- Do NOT use subprocess, eval, exec, __import__, socket, ctypes
- Return the COMPLETE Python code, nothing else
- No markdown code fences, no explanation

Use the above research to inform your implementation.
If research context says "No research available.", rely on your training knowledge.

{platform_context}
"""


class SkillDesigner:
    """Designs skill handler functions via LLM.

    Similar to AgentDesigner but generates a single async function
    instead of a full agent class. The generated function is validated
    by SkillValidator (same forbidden patterns) and tested in sandbox.
    """

    def __init__(self, llm_client: BaseLLMClient, config: SelfModConfig) -> None:
        self._llm = llm_client
        self._config = config

    async def design_skill(
        self,
        intent_name: str,
        intent_description: str,
        parameters: dict[str, str],
        target_agent_type: str,
        research_context: str = "No research available.",
    ) -> str:
        """Generate skill handler source code.

        Returns raw Python source code string containing the handler function.
        Raises ValueError if LLM returns empty or error response.
        """
        prompt = SKILL_DESIGN_PROMPT.format(
            intent_name=intent_name,
            intent_description=intent_description,
            parameters=parameters,
            target_agent_type=target_agent_type,
            research_context=research_context,
            allowed_imports=", ".join(self._config.allowed_imports),
            platform_context=get_platform_context(),
        )

        request = LLMRequest(prompt=prompt, tier="deep", max_tokens=4096)
        response = await self._llm.complete(request)

        if not response.content or response.error:
            raise ValueError(
                f"LLM returned empty or error response: {response.error}"
            )

        # Strip markdown code fences if present
        code = response.content.strip()
        code = re.sub(r'^```python\s*\n', '', code)
        code = re.sub(r'\n```\s*$', '', code)

        return code

    def _build_function_name(self, intent_name: str) -> str:
        """Convert intent_name like 'translate_text' to 'handle_translate_text'."""
        return f"handle_{intent_name}"
