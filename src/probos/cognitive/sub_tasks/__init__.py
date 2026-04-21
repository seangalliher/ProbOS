"""AD-632b+: Sub-task handler implementations for Level 3 cognitive escalation."""

# AD-646b: Keys with dedicated rendering sections — excluded from
# generic "Prior Data" rendering to prevent double-display.
AD646B_DEDICATED_KEYS: frozenset[str] = frozenset({
    "self_monitoring",
    "introspective_telemetry",
})

from probos.cognitive.sub_tasks.analyze import AnalyzeHandler
from probos.cognitive.sub_tasks.compose import ComposeHandler
from probos.cognitive.sub_tasks.evaluate import EvaluateHandler
from probos.cognitive.sub_tasks.query import QueryHandler
from probos.cognitive.sub_tasks.reflect import ReflectHandler

__all__ = ["AnalyzeHandler", "ComposeHandler", "EvaluateHandler", "QueryHandler", "ReflectHandler", "AD646B_DEDICATED_KEYS"]
