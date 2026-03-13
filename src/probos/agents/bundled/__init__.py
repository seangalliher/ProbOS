"""Bundled agent suite — pre-built CognitiveAgent subclasses (Phase 22)."""

from probos.agents.bundled.web_agents import (
    WebSearchAgent,
    PageReaderAgent,
    WeatherAgent,
    NewsAgent,
)
from probos.agents.bundled.language_agents import (
    TranslateAgent,
    SummarizerAgent,
)
from probos.agents.bundled.productivity_agents import (
    CalculatorAgent,
    TodoAgent,
)
from probos.agents.bundled.organizer_agents import (
    NoteTakerAgent,
    SchedulerAgent,
)

__all__ = [
    "WebSearchAgent",
    "PageReaderAgent",
    "WeatherAgent",
    "NewsAgent",
    "TranslateAgent",
    "SummarizerAgent",
    "CalculatorAgent",
    "TodoAgent",
    "NoteTakerAgent",
    "SchedulerAgent",
]
