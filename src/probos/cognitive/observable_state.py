"""AD-583f: Observable State Verification.

Provides ground truth verification for agent claims by querying actual
system state. Uses a pluggable StateProvider protocol — extend by adding
providers, not by modifying the verifier.

Satisfies AD-569d: populates convergence_correctness_rate in
BehavioralSnapshot (previously hardcoded None).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VerificationResult:
    """Result of verifying a single claim against observable state."""

    provider_name: str
    claim_text: str
    verified: bool | None  # None = provider can't determine
    ground_truth_summary: str  # Human-readable actual state
    confidence: float  # 0.0-1.0, how confident the provider is


@runtime_checkable
class StateProvider(Protocol):
    """Protocol for pluggable state verification providers (ISP).

    Each provider handles a narrow domain (games, trust, health).
    Returns None if the claim is outside its domain.
    """

    @property
    def name(self) -> str: ...

    async def check(
        self, claim_text: str, context: dict[str, Any]
    ) -> VerificationResult | None: ...


class ObservableStateVerifier:
    """Registry of state providers for ground truth verification.

    Constructor-injected providers (DIP). Log-and-degrade if any
    provider fails — never let a broken provider block verification.
    """

    def __init__(
        self,
        providers: list[StateProvider] | None = None,
        *,
        max_claims: int = 10,
    ) -> None:
        self._providers = list(providers) if providers else []
        self._max_claims = max_claims

    async def verify_claims(
        self,
        claims: list[str],
        context: dict[str, Any] | None = None,
    ) -> list[VerificationResult]:
        """Verify a list of claims against all registered providers.

        Each claim may produce results from multiple providers.
        Providers that raise are skipped (log-and-degrade).
        """
        ctx = context or {}
        results: list[VerificationResult] = []

        for claim in claims[: self._max_claims]:
            for provider in self._providers:
                try:
                    result = await provider.check(claim, ctx)
                    if result is not None:
                        results.append(result)
                except Exception:
                    logger.debug(
                        "AD-583f: Provider %s failed on claim",
                        getattr(provider, "name", "unknown"),
                        exc_info=True,
                    )
        return results


# -- Built-in state providers ------------------------------------------


_GAME_KEYWORDS = frozenset({
    "game", "tic-tac-toe", "move", "board", "winner",
    "draw", "playing", "match",
})


class RecreationStateProvider:
    """Verify game-related claims against RecreationService state."""

    def __init__(self, recreation_service: Any) -> None:
        self._recreation = recreation_service

    @property
    def name(self) -> str:
        return "recreation"

    async def check(
        self, claim_text: str, context: dict[str, Any]
    ) -> VerificationResult | None:
        words = set(claim_text.lower().split())
        if not words & _GAME_KEYWORDS:
            return None  # Not a game claim

        active_games = self._recreation.get_active_games()
        agents = context.get("agents", [])

        # Check if any agent from context has an active game
        player_game = None
        for callsign in agents:
            g = self._recreation.get_game_by_player(callsign)
            if g:
                player_game = g
                break

        if not active_games and not player_game:
            # Claim mentions games but none are active
            claim_lower = claim_text.lower()
            if any(kw in claim_lower for kw in ("stuck", "waiting", "stale")):
                return VerificationResult(
                    provider_name=self.name,
                    claim_text=claim_text,
                    verified=False,
                    ground_truth_summary="No active games found.",
                    confidence=0.8,
                )
            return VerificationResult(
                provider_name=self.name,
                claim_text=claim_text,
                verified=None,
                ground_truth_summary="No active games found.",
                confidence=0.5,
            )

        game = player_game or (active_games[0] if active_games else None)
        if not game:
            return None

        status = game.get("status", "unknown")
        current = game.get("current_player", "")
        summary = f"Game status: {status}, current player: {current}."

        claim_lower = claim_text.lower()
        if "stuck" in claim_lower or "stale" in claim_lower:
            # Game exists and is active → not stuck
            verified = status not in ("active", "in_progress")
            return VerificationResult(
                provider_name=self.name,
                claim_text=claim_text,
                verified=verified,
                ground_truth_summary=summary,
                confidence=0.7,
            )
        if "concluded" in claim_lower or "over" in claim_lower:
            verified = status in ("completed", "forfeited", "draw")
            return VerificationResult(
                provider_name=self.name,
                claim_text=claim_text,
                verified=verified,
                ground_truth_summary=summary,
                confidence=0.8,
            )

        return VerificationResult(
            provider_name=self.name,
            claim_text=claim_text,
            verified=None,
            ground_truth_summary=summary,
            confidence=0.4,
        )


_TRUST_KEYWORDS = frozenset({
    "trust", "confidence", "trust score", "declining", "anomaly",
})


class TrustStateProvider:
    """Verify trust-related claims against TrustNetwork state."""

    def __init__(self, trust_network: Any) -> None:
        self._trust = trust_network

    @property
    def name(self) -> str:
        return "trust"

    async def check(
        self, claim_text: str, context: dict[str, Any]
    ) -> VerificationResult | None:
        words = set(claim_text.lower().split())
        if not words & _TRUST_KEYWORDS:
            return None

        scores = self._trust.all_scores()
        if not scores:
            return VerificationResult(
                provider_name=self.name,
                claim_text=claim_text,
                verified=None,
                ground_truth_summary="No trust scores available.",
                confidence=0.3,
            )

        values = list(scores.values())
        mean_score = sum(values) / len(values) if values else 0.5
        summary = (
            f"Trust scores: {len(scores)} agents, "
            f"mean={mean_score:.2f}, "
            f"range=[{min(values):.2f}, {max(values):.2f}]."
        )

        claim_lower = claim_text.lower()
        if "anomaly" in claim_lower:
            # Check if any score deviates > 2σ from mean
            if len(values) >= 2:
                variance = sum((v - mean_score) ** 2 for v in values) / len(values)
                std = variance ** 0.5
                has_anomaly = any(abs(v - mean_score) > 2 * std for v in values) if std > 0 else False
            else:
                has_anomaly = False
            return VerificationResult(
                provider_name=self.name,
                claim_text=claim_text,
                verified=has_anomaly,
                ground_truth_summary=summary,
                confidence=0.7,
            )
        if "low trust" in claim_lower or "declining" in claim_lower:
            has_low = any(v < 0.3 for v in values)
            return VerificationResult(
                provider_name=self.name,
                claim_text=claim_text,
                verified=has_low,
                ground_truth_summary=summary,
                confidence=0.7,
            )

        return VerificationResult(
            provider_name=self.name,
            claim_text=claim_text,
            verified=None,
            ground_truth_summary=summary,
            confidence=0.4,
        )


_HEALTH_KEYWORDS = frozenset({
    "health", "pool", "degraded", "critical", "failure",
    "offline", "monitoring",
})


class SystemHealthProvider:
    """Verify system health claims against VitalsMonitor snapshot."""

    def __init__(self, vitals_monitor: Any) -> None:
        self._vitals = vitals_monitor

    @property
    def name(self) -> str:
        return "system_health"

    async def check(
        self, claim_text: str, context: dict[str, Any]
    ) -> VerificationResult | None:
        words = set(claim_text.lower().split())
        if not words & _HEALTH_KEYWORDS:
            return None

        # Try scan_now (async) first, fall back to latest_vitals
        vitals = None
        try:
            if hasattr(self._vitals, "scan_now"):
                vitals = await self._vitals.scan_now()
        except Exception:
            logger.debug("AD-583f: scan_now failed", exc_info=True)

        if vitals is None and hasattr(self._vitals, "latest_vitals"):
            vitals = self._vitals.latest_vitals

        if not vitals:
            return VerificationResult(
                provider_name=self.name,
                claim_text=claim_text,
                verified=None,
                ground_truth_summary="No vitals data available.",
                confidence=0.2,
            )

        system_health = vitals.get("system_health", "unknown")
        pool_health = vitals.get("pool_health", {})
        summary = f"System health: {system_health}."
        if pool_health:
            summary += f" Pool statuses: {pool_health}."

        claim_lower = claim_text.lower()
        if "failure" in claim_lower or "critical" in claim_lower:
            is_bad = system_health in ("critical", "failure", "degraded")
            return VerificationResult(
                provider_name=self.name,
                claim_text=claim_text,
                verified=is_bad,
                ground_truth_summary=summary,
                confidence=0.8,
            )
        if "degraded" in claim_lower:
            return VerificationResult(
                provider_name=self.name,
                claim_text=claim_text,
                verified=(system_health == "degraded"),
                ground_truth_summary=summary,
                confidence=0.7,
            )

        return VerificationResult(
            provider_name=self.name,
            claim_text=claim_text,
            verified=None,
            ground_truth_summary=summary,
            confidence=0.4,
        )
