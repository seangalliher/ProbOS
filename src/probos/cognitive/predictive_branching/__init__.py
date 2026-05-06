"""AD-633: Predictive Cognitive Branching.

Public exports for the predictive branching package. See `engine.py` for
detailed module-level docstring describing the umbrella scope.
"""

from probos.cognitive.predictive_branching.accuracy import (
    AccuracyRates,
    AccuracyTracker,
    PredictionOutcome,
)
from probos.cognitive.predictive_branching.budget import SpeculationBudget
from probos.cognitive.predictive_branching.cache import SpeculationCache
from probos.cognitive.predictive_branching.engine import (
    ConfidenceTier,
    PredictionDescriptor,
    PredictionEngine,
    compute_signature,
)
from probos.cognitive.predictive_branching.executor import (
    SpeculationExecutor,
    SpeculationRequest,
)
from probos.cognitive.predictive_branching.policy import (
    IdleSpeculationPolicy,
    NoOpIdleSpeculationPolicy,
    NoOpPreplayHook,
    PreplayHook,
)

__all__ = [
    "AccuracyRates",
    "AccuracyTracker",
    "ConfidenceTier",
    "IdleSpeculationPolicy",
    "NoOpIdleSpeculationPolicy",
    "NoOpPreplayHook",
    "PredictionDescriptor",
    "PredictionEngine",
    "PredictionOutcome",
    "PreplayHook",
    "SpeculationBudget",
    "SpeculationCache",
    "SpeculationExecutor",
    "SpeculationRequest",
    "compute_signature",
]
