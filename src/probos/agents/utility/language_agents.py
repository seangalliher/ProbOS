"""Language + Content utility agents (AD-249).

Pure LLM agents — no perceive() override needed.
"""

from __future__ import annotations

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import CapabilityDescriptor, IntentDescriptor, IntentMessage, IntentResult


class _BundledMixin:
    """Self-deselect guard for unrecognized intents."""

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        if intent.intent not in self._handled_intents:
            return None
        return await super().handle_intent(intent)


class TranslateAgent(_BundledMixin, CognitiveAgent):
    """Translate text to another language (pure LLM)."""

    agent_type = "translator"
    instructions = (
        "You are a translation agent. When given text and a target language:\n"
        "1. Translate the text accurately into the target language.\n"
        "2. Preserve meaning, tone, and formatting.\n"
        "3. If the source language is ambiguous, detect it and note your detection.\n\n"
        "Support all major languages. For specialized terminology, prioritize accuracy."
    )
    intent_descriptors = [
        IntentDescriptor(
            name="translate_text",
            params={"text": "text to translate", "target_language": "target language"},
            description="Translate text to another language",
            requires_reflect=True,
        ),
    ]
    _handled_intents = {"translate_text"}
    default_capabilities = [CapabilityDescriptor(can="translate_text")]


class SummarizerAgent(_BundledMixin, CognitiveAgent):
    """Summarize text or content (pure LLM)."""

    agent_type = "summarizer"
    instructions = (
        "You are a text summarization agent. When given text or content:\n"
        "1. Identify the key points, arguments, and conclusions.\n"
        "2. Produce a concise summary that captures the essential information.\n"
        "3. Adjust summary length based on input length (shorter input = shorter summary).\n\n"
        "If given a URL, note that the page_reader agent should be used first to fetch the content."
    )
    intent_descriptors = [
        IntentDescriptor(
            name="summarize_text",
            params={"text": "text to summarize", "length": "short|medium|detailed (optional)"},
            description="Summarize text or content concisely",
            requires_reflect=True,
        ),
    ]
    _handled_intents = {"summarize_text"}
    default_capabilities = [CapabilityDescriptor(can="summarize_text")]
