"""AD-833 v1: Improvement-proposal grounding gate.

A provider-based verifier that grounds agent-authored `CapabilityProposal`s
against observable system state BEFORE they surface for crew/Captain review.
Mirrors the AD-734 `ObservableStateVerifier` shape (``observable_state.py``):
a constructor-injected list of narrow `GroundingProvider` plugins (Interface
Segregation), each independently inspects a proposal and returns structured
evidence with a partial score and a ``verified: bool | None`` determination.

Grounding is ADVISORY — a low/None score is information, not a veto. A provider
that raises is caught, logged, and skipped (log-and-degrade); it never blocks
proposal authoring.

v1 ships the verifier scaffold + `SymbolExistenceProvider` (failure classes 1
phantom-symbol and 4 conflated-subsystem). `TrackerCrossRefProvider` (AD-833a)
and `BenignTelemetryProvider` (AD-833b) stay deferred until their query APIs land.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from probos.cognitive.self_improvement.proposal import CapabilityProposal

if TYPE_CHECKING:
    from probos.cognitive.codebase_index import CodebaseIndex

logger = logging.getLogger(__name__)

# Single source of truth for the grounding-verified threshold (do not inline).
_GROUNDING_VERIFIED_THRESHOLD: float = 0.5

# Identifier-shaped tokens: snake_case, CamelCase, EVENT_NAMES, dotted intents
# (e.g. ``vision_observation``, ``CapabilityProposal``, ``CAPABILITY_PROPOSAL_CREATED``).
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


@dataclass(frozen=True)
class GroundingFinding:
    """Result of one provider inspecting a proposal."""

    provider_name: str
    verified: bool | None  # True=grounded, False=contradicted, None=undetermined/abstain
    score: float  # 0.0-1.0 contribution
    evidence: list[str]  # human-readable, surfaced in the UI


@dataclass(frozen=True)
class ProposalGroundingResult:
    """Aggregate grounding evidence attached to a proposal."""

    score: float  # aggregate 0.0-1.0 (mean of finding scores; 1.0 when empty)
    verified: bool  # threshold + no-False (see ProposalGroundingVerifier.verify)
    findings: list[GroundingFinding]
    confidence: float  # fraction of findings whose verified is not None


@runtime_checkable
class GroundingProvider(Protocol):
    """Protocol for pluggable grounding providers (ISP).

    Each provider inspects a proposal for one failure class and returns a
    `GroundingFinding`. A provider ABSTAINS by returning a finding with
    ``verified=None`` and ``score=0.0`` — NOT by returning ``None`` — so the
    aggregation math stays simple and ``confidence`` is meaningful.
    """

    name: str

    async def check(self, proposal: CapabilityProposal) -> GroundingFinding: ...


def _is_symbol_like(token: str) -> bool:
    """A token is symbol-like if it has ``_``, ``.``, or an interior capital."""
    if "_" in token or "." in token:
        return True
    return any(c.isupper() for c in token[1:])


def _extract_symbols(text: str) -> list[str]:
    """Extract identifier-shaped, symbol-like tokens from prose.

    Over-extraction is acceptable; only symbol-like tokens (CamelCase /
    snake_case / dotted / EVENT_NAME) are returned, so plain English prose
    contributes nothing and cannot lower the score.
    """
    seen: set[str] = set()
    symbols: list[str] = []
    for match in _TOKEN_RE.findall(text):
        if match in seen:
            continue
        if _is_symbol_like(match):
            seen.add(match)
            symbols.append(match)
    return symbols


class SymbolExistenceProvider:
    """Grounds phantom-symbol (class 1) and conflated-subsystem (class 4) faults.

    Extracts symbol-like tokens from ``proposal.summary`` + ``proposal.fit_assessment``
    and resolves each against the `CodebaseIndex`. Resolution counts a hit in
    ``query(token)["matching_*"]``, a non-empty ``find_callers(token)``, or
    presence in ``get_full_api_surface()`` (class name or method name).
    """

    name = "symbol_existence"

    def __init__(self, codebase_index: CodebaseIndex) -> None:
        self._index = codebase_index

    def _resolve(self, token: str) -> str | None:
        """Return a short 'where it resolved' string, or None if unresolved."""
        try:
            q = self._index.query(token)
            if q.get("matching_files") or q.get("matching_agents") or q.get("matching_methods"):
                return "query"
        except Exception:
            logger.debug(
                "AD-833: query(%r) raised in SymbolExistenceProvider", token, exc_info=True
            )
        try:
            if self._index.find_callers(token):
                return "find_callers"
        except Exception:
            logger.debug(
                "AD-833: find_callers(%r) raised in SymbolExistenceProvider", token, exc_info=True
            )
        try:
            surface = self._index.get_full_api_surface()
            if token in surface:
                return "api_surface"
            for methods in surface.values():
                if any(m.get("method") == token for m in methods):
                    return "api_surface"
        except Exception:
            logger.debug(
                "AD-833: get_full_api_surface() raised in SymbolExistenceProvider",
                exc_info=True,
            )
        return None

    async def check(self, proposal: CapabilityProposal) -> GroundingFinding:
        text = f"{proposal.summary}\n{proposal.fit_assessment}"
        tokens = _extract_symbols(text)
        if not tokens:
            return GroundingFinding(
                provider_name=self.name,
                verified=None,
                score=0.0,
                evidence=["no symbol-like tokens to ground (prose-only proposal)"],
            )
        evidence: list[str] = []
        resolved_count = 0
        any_unresolved = False
        for token in tokens:
            where = self._resolve(token)
            if where is not None:
                resolved_count += 1
                evidence.append(f"{token}: resolved via {where}")
            else:
                any_unresolved = True
                evidence.append(f"{token}: UNRESOLVED (likely phantom)")
        score = resolved_count / len(tokens)
        verified = not any_unresolved
        return GroundingFinding(
            provider_name=self.name,
            verified=verified,
            score=score,
            evidence=evidence,
        )


class ProposalGroundingVerifier:
    """Registry of grounding providers (DIP).

    Constructor-injected providers. Log-and-degrade if any provider raises —
    a broken provider is skipped, never blocks verification or authoring.
    """

    def __init__(self, providers: list[GroundingProvider]) -> None:
        self._providers = list(providers)

    async def verify(self, proposal: CapabilityProposal) -> ProposalGroundingResult:
        """Run all providers and aggregate into one grounding result.

        - ``score`` = mean of finding scores (empty findings -> 1.0).
        - ``verified`` = ``score >= _GROUNDING_VERIFIED_THRESHOLD`` AND no
          finding has ``verified is False``.
        - ``confidence`` = fraction of findings whose ``verified is not None``
          (0.0 when there are no findings).
        """
        findings: list[GroundingFinding] = []
        for provider in self._providers:
            try:
                findings.append(await provider.check(proposal))
            except Exception:
                logger.warning(
                    "AD-833: grounding provider %s raised; skipping (advisory degrade)",
                    getattr(provider, "name", "unknown"),
                    exc_info=True,
                )

        if not findings:
            return ProposalGroundingResult(
                score=1.0, verified=True, findings=[], confidence=0.0
            )

        score = sum(f.score for f in findings) / len(findings)
        no_false = all(f.verified is not False for f in findings)
        verified = score >= _GROUNDING_VERIFIED_THRESHOLD and no_false
        determined = sum(1 for f in findings if f.verified is not None)
        confidence = determined / len(findings)
        return ProposalGroundingResult(
            score=score,
            verified=verified,
            findings=findings,
            confidence=confidence,
        )
