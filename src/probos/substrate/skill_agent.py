"""SkillBasedAgent — general-purpose agent dispatching intents to attached skills."""

from __future__ import annotations

from typing import Any

from probos.substrate.agent import BaseAgent
from probos.types import IntentDescriptor, IntentMessage, IntentResult, Skill


class SkillBasedAgent(BaseAgent):
    """An agent that handles intents via attached skills.

    Unlike specialized agents (FileReaderAgent, ShellCommandAgent),
    the SkillBasedAgent doesn't have hardcoded intent handlers.
    It discovers its capabilities from its _skills list, which can
    be extended at runtime.

    Each skill is a compiled async function that takes an IntentMessage
    and optional LLM client, and returns an IntentResult.
    """

    agent_type = "skill_agent"
    _handled_intents: set[str] = set()
    intent_descriptors: list[IntentDescriptor] = []

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._skills: list[Skill] = []
        self._llm_client = kwargs.get("llm_client")

    def add_skill(self, skill: Skill) -> None:
        """Attach a skill to this agent.

        Updates BOTH instance-level AND class-level _handled_intents
        and intent_descriptors so that both the agent's own dispatch
        and the template-based descriptor collection path work.
        """
        self._skills.append(skill)

        # Instance-level update (for this agent's dispatch)
        self._handled_intents.add(skill.name)
        if skill.descriptor not in self.intent_descriptors:
            self.intent_descriptors.append(skill.descriptor)

        # Class-level update (for template-based descriptor collection in
        # _collect_intent_descriptors, which reads class.intent_descriptors)
        if skill.descriptor not in SkillBasedAgent.intent_descriptors:
            SkillBasedAgent.intent_descriptors.append(skill.descriptor)
        SkillBasedAgent._handled_intents.add(skill.name)

    def remove_skill(self, name: str) -> None:
        """Remove a skill by name.

        Updates both instance and class level.
        """
        self._skills = [s for s in self._skills if s.name != name]
        self._handled_intents.discard(name)
        self.intent_descriptors = [
            d for d in self.intent_descriptors if d.name != name
        ]
        # Class-level cleanup
        SkillBasedAgent._handled_intents.discard(name)
        SkillBasedAgent.intent_descriptors = [
            d for d in SkillBasedAgent.intent_descriptors if d.name != name
        ]

    @property
    def skills(self) -> list[Skill]:
        """Return attached skills."""
        return list(self._skills)

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Dispatch intent to the matching skill handler.

        If no skill handles the intent, return None (decline).
        The skill handler receives the LLM client for intelligence tasks.
        """
        for skill in self._skills:
            if skill.name == intent.intent and skill.handler is not None:
                return await skill.handler(intent, llm_client=self._llm_client)
        return None

    # Lifecycle methods — minimal, agent is a dispatcher
    async def perceive(self, intent: dict) -> Any:
        return intent

    async def decide(self, observation: Any) -> Any:
        return observation

    async def act(self, plan: Any) -> Any:
        return plan

    async def report(self, result: Any) -> dict:
        return {"agent_id": self.id, "result": result}
