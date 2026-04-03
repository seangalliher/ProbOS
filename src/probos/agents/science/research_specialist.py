"""ResearchSpecialistAgent — directed investigation and formal research (AD-560)."""

from __future__ import annotations

import logging
from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

logger = logging.getLogger(__name__)

_INSTRUCTIONS = (
    "You are the ProbOS Research Specialist. You conduct directed investigations "
    "into specific questions about ship operations, agent dynamics, and system "
    "behavior. You produce formal research reports with methodology, findings, "
    "and actionable recommendations.\n\n"
    "You handle these request types:\n\n"
    "1. **research_investigation** — Conduct a thorough investigation into an "
    "assigned research question. Follow the full research methodology: define "
    "the question, review prior work, form hypotheses, collect evidence, analyze, "
    "report findings.\n\n"
    "2. **literature_review** — Survey existing Ship's Records, prior research "
    "reports, and crew notebooks for knowledge relevant to a specific topic. "
    "Identify gaps in institutional knowledge.\n\n"
    "3. **research_proposal** — Propose a research question to the Chief Science "
    "Officer based on identified knowledge gaps or unresolved operational questions.\n\n"
    "For all responses:\n"
    "- Follow evidence wherever it leads, even if the answer is uncomfortable.\n"
    "- Cite specific data sources for every factual claim.\n"
    "- Distinguish between established findings and hypotheses.\n"
    "- Include methodology, limitations, and confidence levels.\n\n"
    "Respond with JSON:\n"
    '{"research_type": "investigation|literature_review|proposal", '
    '"question": "...", "methodology": "...", '
    '"findings": [{"claim": "...", "evidence": ["..."], "confidence": 0.0}], '
    '"limitations": [...], "recommendations": [...], '
    '"follow_up_questions": [...]}'
)


class ResearchSpecialistAgent(CognitiveAgent):
    """Science department research specialist — deep investigation and formal reports."""

    agent_type = "research_specialist"
    tier = "domain"
    instructions = _INSTRUCTIONS
    default_capabilities = [
        CapabilityDescriptor(
            can="investigate",
            detail="Conduct directed research investigations with formal methodology",
        ),
        CapabilityDescriptor(
            can="review_literature",
            detail="Survey existing records and identify knowledge gaps",
        ),
    ]
    intent_descriptors = [
        IntentDescriptor(
            name="research_investigation",
            params={"question": "research question to investigate"},
            description="Conduct a thorough investigation into an assigned question",
        ),
        IntentDescriptor(
            name="literature_review",
            params={"topic": "topic to survey existing knowledge on"},
            description="Survey Ship's Records for prior work on a topic",
        ),
        IntentDescriptor(
            name="research_proposal",
            params={"gap": "identified knowledge gap"},
            description="Propose a research question based on a knowledge gap",
        ),
    ]
    _handled_intents = {"research_investigation", "literature_review", "research_proposal"}

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("pool", "science")
        super().__init__(**kwargs)
        self._runtime = kwargs.get("runtime")
