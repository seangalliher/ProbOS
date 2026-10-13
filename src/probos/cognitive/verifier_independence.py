"""AD-1327 (#1511): which model the crew verifier judges with, and how independent it is.

``crew_verifier.SubtaskVerifier`` asks one LLM to refute crew work. MASS
(arXiv:2610.12176; docs/research/mass-self-supervision-absorption.md, finding 3)
names the risk of a judge that shares the worker's model: a flawed judgement is
accepted, then reinforced. This module decides the tier the verifier requests and
classifies the judge's model against the models of the text tiers crew workers
run on (``llm_client.TEXT_TIERS``):

- ``cognitive.llm_model_verifier`` unset: the verifier requests ``standard``, the
  request it sent before AD-1327, and judges with the standard tier's model.
- set: it requests the ``verifier`` tier. ``OpenAICompatibleClient`` falls back
  from it to standard, fast and deep; a verdict the requested tier is not shown to
  have answered (``LLMResponse.answered_tier``) is marked ``fallback`` and never
  ``independent``. The judge's model is the id the provider's reply named
  (``LLMResponse.answered_model``), never the id the client sent.

Sameness compares normalised model ids (``model_registry.normalise_model_id``),
not endpoints. Families come from ``model_registry.model_family``; a family it
does not know makes the outcome ``unknown``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from probos.cognitive.crew_verdict import (
    JudgeIndependence,
    JudgeProvenance,
    is_persistable_judge_model,
)
from probos.cognitive.llm_client import TEXT_TIERS, VERIFIER_TIER
from probos.cognitive.model_registry import model_family, normalise_model_id

if TYPE_CHECKING:
    from probos.config import CognitiveConfig

_STANDARD_TIER = "standard"

VERIFIER_REMEDIATION = (
    "Set cognitive.llm_model_verifier to a model of a different family from the fast, "
    "standard and deep tiers' models (with llm_base_url_verifier and llm_api_key_verifier "
    "when another endpoint serves it). Until then each verdict records that its judge "
    "is not independent."
)

_OUTCOME_TEXT: dict[str, str] = {
    "same_model": "the same model as a crew tier, so its verdicts are not independent",
    "same_family": "a model of the same family as a crew tier, so its verdicts are not independent",
    "unknown": "a model whose family is not known, so its independence is not established",
    "independent": "a model of a different family from every crew tier",
}


def is_verifier_tier_configured(cognitive: CognitiveConfig) -> bool:
    """AD-1327: whether ``cognitive.llm_model_verifier`` names a model.

    The verifier tier's base URL and key fall back to the shared ones, as the
    text tiers' do, so the model alone decides it. The setup module's
    ``TIER_CONFIGURED_CHECKS``, ``model_router.routed_tiers`` and
    ``VerifierJudgePolicy`` all read this one check.
    """
    return bool(cognitive.llm_model_verifier)


def classify_independence(judge_model: str, crew_models: Iterable[str]) -> JudgeIndependence:
    """AD-1327: how independent ``judge_model`` is of the models in ``crew_models``.

    ``same_model`` when its normalised id equals a crew model's; else
    ``same_family`` when its family is a crew model's family; else ``unknown``
    when there is nothing to compare or a family involved is not known; else
    ``independent``. Empty names in ``crew_models`` are ignored.
    """
    crew = [model for model in crew_models if model]
    judge = normalise_model_id(judge_model) if judge_model else ""
    if not judge or not crew:
        return "unknown"
    if judge in {normalise_model_id(model) for model in crew}:
        return "same_model"
    judge_family = model_family(judge_model)
    crew_families = {model_family(model) for model in crew}
    if judge_family is not None and judge_family in crew_families:
        return "same_family"
    if judge_family is None or None in crew_families:
        return "unknown"
    return "independent"


@dataclass(frozen=True)
class VerifierJudgePolicy:
    """AD-1327: the tier the crew verifier requests and the crew models it is compared with.

    Built once from ``CognitiveConfig`` when the crew orchestrator is wired and
    injected into ``SubtaskVerifier``, so each verdict's judge record, the startup
    line and ``probos doctor`` read one decision.
    """

    request_tier: str
    configured_model: str
    crew_models: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.request_tier not in (VERIFIER_TIER, _STANDARD_TIER):
            raise ValueError(f"verifier_judge_tier_invalid: {self.request_tier!r}")

    @classmethod
    def from_cognitive(cls, cognitive: CognitiveConfig) -> VerifierJudgePolicy:
        crew = tuple(cognitive.tier_config(tier)["model"] or "" for tier in TEXT_TIERS)
        if is_verifier_tier_configured(cognitive):
            return cls(VERIFIER_TIER, cognitive.llm_model_verifier, crew)
        return cls(_STANDARD_TIER, cognitive.tier_config(_STANDARD_TIER)["model"] or "", crew)

    @property
    def dedicated(self) -> bool:
        """Whether a verifier model is configured, so the verifier tier is requested."""
        return self.request_tier == VERIFIER_TIER

    def assess(self) -> JudgeIndependence:
        """The configured judge model's independence (the startup line and ``probos doctor``)."""
        return classify_independence(self.configured_model, self.crew_models)

    def provenance(self, *, answered_tier: object, answered_model: object) -> JudgeProvenance:
        """The judge record for one response, from what the LLM client says answered it.

        ``answered_model`` is the model id the provider's reply named
        (``LLMResponse.answered_model``); ``None``, a value that is not a string, or one
        ``is_persistable_judge_model`` refuses (NUL, longer than ``MAX_JUDGE_MODEL_CHARS``,
        not strict UTF-8) is recorded as ``""`` with ``unknown``. ``answered_tier`` is the tier whose attempt answered
        (``LLMResponse.answered_tier``); ``fallback`` is True unless it is the tier this
        policy requests, so a response that does not say is never ``independent``.
        Model ids never decide ``fallback``. Does not raise for any input (a test pins this).
        """
        model = answered_model if type(answered_model) is str else ""
        if not is_persistable_judge_model(model):
            model = ""
        fallback = not (type(answered_tier) is str and answered_tier == self.request_tier)
        independence = classify_independence(model, self.crew_models)
        if fallback and independence == "independent":
            independence = "unknown"
        return JudgeProvenance(
            tier=self.request_tier, model=model, independence=independence, fallback=fallback,
        )


def verifier_independence_report(policy: VerifierJudgePolicy) -> tuple[JudgeIndependence, str]:
    """AD-1327: the configured judge's independence and a one-line description of it.

    The line names models. The reports that show it to an operator (``probos doctor`` and
    the endpoint banner in ``__main__``) redact configured keys with the setup module's
    ``redact_keys``; the startup log line names the model as the runtime's other
    model logs do.
    """
    independence = policy.assess()
    source = (
        "cognitive.llm_model_verifier"
        if policy.dedicated
        else "the standard tier; cognitive.llm_model_verifier is unset"
    )
    detail = (
        f"{independence} -- judges with {policy.configured_model or '<none>'} ({source}), "
        f"{_OUTCOME_TEXT[independence]}"
    )
    return independence, detail
